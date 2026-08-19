#!/usr/bin/env python3
"""
game_utils.py - Shared utility functions for all engine modules

Majoritairement des lookups purs, MAIS pas exclusivement : la journalisation
(`add_console_log`, `add_debug_log`) et le registre `_once_claims` ci-dessous ecrivent dans
`game_state`. Le docstring d'origine annoncait « pure lookup functions, no game logic » —
il decrivait mal le module et induisait en erreur sur l'endroit ou poser de l'etat partage.
"""

import os
from typing import Dict, Any, Literal, Optional
from shared.data_validation import require_key, ConfigurationError

_debug_log_initialized = False

#: File des phases FRANCHIES depuis le dernier solde de frontiere. Ecrite par `enter_phase`,
#: DRAINEE par `GameStateManager.refresh_objective_control_on_boundary` (regle 14.02). Prefixe `_` :
#: memo moteur, jamais serialise vers le client.
PHASES_TRAVERSED_KEY = "_phases_traversed_since_boundary"


def _write_diagnostic_to_debug_log(message: str) -> None:
    """Write diagnostic message directly to debug.log"""
    try:
        # Get project root (parent of engine directory)
        # Use os imported at module level (line 7)
        current_file = os.path.abspath(__file__)
        engine_dir = os.path.dirname(current_file)
        project_root = os.path.dirname(engine_dir)
        debug_log_path = os.path.join(project_root, 'debug.log')
        global _debug_log_initialized
        if not _debug_log_initialized:
            with open(debug_log_path, 'w', encoding='utf-8', errors='replace') as f:
                f.write(message + "\n")
                f.flush()
            _debug_log_initialized = True
            return
        with open(debug_log_path, 'a', encoding='utf-8', errors='replace') as f:
            f.write(message + "\n")
            f.flush()
    except Exception:
        # Silently fail - diagnostics are not critical
        pass


def add_debug_file_log(game_state: Dict[str, Any], message: str) -> None:
    """
    Write debug message to debug.log only if debug_mode is enabled.
    
    Args:
        game_state: Game state dictionary (must contain "debug_mode" key)
        message: Debug message to log
    """
    if not game_state.get("debug_mode", False):
        return
    _write_diagnostic_to_debug_log(message)


# ─────────────────────────────────────────────────────────────────────────────
# Registre « cette etape a deja ete resolue » (marqueurs once)
# ─────────────────────────────────────────────────────────────────────────────
#
# UN seul registre pour toutes les etapes qui ne doivent se resoudre qu'une fois par
# (tour, joueur) : game_state["_once_claims"] -> {famille: set(cles)}.
#
#
# POURQUOI un registre et pas une cle de game_state par famille : chaque famille devait
# etre declaree DEUX fois dans w40k_core (dict d'init ET dict de reset), et l'oubli du
# cote RESET est SILENCIEUX. La cle existe encore (heritee de l'init), le set garde donc
# les marqueurs de l'episode precedent ; comme les cles sont indexees sur le tour (∈ 1..5)
# elles se REPETENT d'un episode a l'autre. A partir de l'episode 2 l'etape est consideree
# resolue pour toujours, sans lever la moindre erreur. Ce n'est pas theorique : c'est ce
# qui est arrive a `_choice_timing_fired_events` — MESURE sur 3 episodes enchaines,
# 16 decisions puis 2 puis 0, le mecanisme de decision entier devenu inerte. Le registre
# naît paresseusement et se purge en UN point (`W40KEngine.reset`) : l'oubli n'existe plus.
#
# DEUX fonctions et pas un test-and-set unique : les sites ne posent PAS le marqueur au
# meme instant, et c'est ce qui les rend corrects. `movement_step_cp_gain_on_objective` et
# `_enqueue_rule_choice_candidates` doivent RESERVER avant d'agir (des lances, prompt
# empile : rejouer coute un CP ou un doublon). Les trois autres marquent APRES l'effet,
# parce que leur travail garde est PUR (lecture de `objective_controllers`, comptage) — et
# deux d'entre eux ont une sortie anticipee ENTRE la garde et la pose (`if not
# acting_unit`) qui ne doit pas consommer le tour. Un `claim_once()` unique imposerait
# reserver-avant-agir a tout le monde.
ONCE_CLAIMS_KEY = "_once_claims"

# Familles ENUMEREES et non chaine libre : le nom est retape a la garde ET a la pose, sur
# deux lignes parfois eloignees. Une faute de frappe sur UN des deux ne leverait rien — la
# garde ne verrait jamais la pose — et l'etape se rejouerait a chaque passage (jet de des
# et CP en double sur `cp_gain_on_objective_resolved`) ou ne se declencherait jamais. Le
# registre supprime ce silence pour les cles de `game_state` ; sans cette union il le
# reintroduirait un cran plus bas. Pyright refuse desormais toute famille hors liste, a
# chaque site d'appel. Les CLES, elles, restent `Any` : leur forme varie legitimement
# (2-uplet, 3-uplet avec l'id d'objectif, chaine pour les evenements de choix).
OnceClaimFamily = Literal[
    "primary_objective_scored_turns",
    "objective_rewarded_turns",
    "coherency_penalized_turns",
    "cp_gain_on_objective_resolved",
    "_choice_timing_fired_events",
]


def once_claimed(game_state: Dict[str, Any], family: OnceClaimFamily, key: Any) -> bool:
    """True si `key` a deja ete reclamee dans `family` durant cet episode.

    Garde sur l'ABSENCE et non `require_key` : le registre naît a la PREMIERE reclamation.
    « Cle absente » signifie « rien n'a encore ete resolu », un etat de jeu valide (debut
    d'episode ou apres le `pop` de reset), pas une donnee manquante — meme lecture que
    `_objective_control_last_boundary`. Une valeur `None` explicite, elle, n'est produite
    nulle part et leve.
    """
    if ONCE_CLAIMS_KEY not in game_state:
        return False
    return key in game_state[ONCE_CLAIMS_KEY].get(family, ())


def once_claim(game_state: Dict[str, Any], family: OnceClaimFamily, key: Any) -> None:
    """Reclame `key` dans `family` : `once_claimed` repondra True jusqu'au prochain reset."""
    claims = game_state.setdefault(ONCE_CLAIMS_KEY, {})
    claims.setdefault(family, set()).add(key)


def get_unit_by_id(unit_id: str, game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    AI_TURN.md COMPLIANCE: Direct lookup from game_state.
    Pure utility function - no dependencies on other modules.

    CRITICAL: Compare both sides as strings to handle int/string ID mismatches.
    Pool unit IDs are integers, but some lookups pass strings.

    REQUIRES: game_state["unit_by_id"] (built at reset/reload). Absence = bug, raise explicitly.
    """
    unit_by_id = require_key(game_state, "unit_by_id")
    return unit_by_id.get(str(unit_id))


def require_unit_by_id(game_state: Dict[str, Any], unit_id: str) -> Dict[str, Any]:
    """Lookup unit by ID; raise ConfigurationError if absent.

    Passer un non-str est un bug de l'appelant : aucune coercition silencieuse.
    REQUIRES: game_state['unit_by_id'] (built at reset/reload).
    """
    unit_by_id = require_key(game_state, "unit_by_id")
    unit = unit_by_id.get(unit_id)
    if unit is None:
        raise ConfigurationError(f"Unit '{unit_id}' not found in game_state.")
    return unit


def add_console_log(game_state: Dict[str, Any], message: str) -> None:
    """
    Add message to console_logs. Only when debug_mode is True (--debug).
    When debug_mode is False, does nothing to avoid building a large list and slowing training.
    
    Args:
        game_state: Game state dictionary (must contain "debug_mode" key when used in engine)
        message: Message to log
    """
    if not game_state.get("debug_mode", False):
        return
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    game_state["console_logs"].append(message)


def add_debug_log(game_state: Dict[str, Any], message: str) -> None:
    """
    Add debug message to console_logs ONLY if debug_mode is enabled.
    
    Args:
        game_state: Game state dictionary (must contain "debug_mode" key)
        message: Debug message to log
    """
    if not game_state.get("debug_mode", False):
        return  # Skip logging if debug_mode is not enabled
    
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    game_state["console_logs"].append(message)


def safe_print(game_state: Dict[str, Any], *args, **kwargs) -> None:
    """
    Conditionally print based on debug mode.
    DISABLED: Logs are written to file only, not printed to console to avoid flooding.
    
    Args:
        game_state: Game state dictionary
        *args, **kwargs: Arguments to pass to print()
    """
    # DISABLED: Do not print to console, logs are written to file only
    return


def conditional_debug_print(game_state: Dict[str, Any], message: str) -> None:
    """
    Conditionally print debug message to console only if debug_mode is enabled.
    DISABLED: Logs are written to file only, not printed to console to avoid flooding.
    
    Args:
        game_state: Game state dictionary (must contain "debug_mode" key)
        message: Message to print
    """
    # DISABLED: Do not print to console, logs are written to file only
    return

def get_effective_turn_limit(game_state: Dict[str, Any]) -> Optional[int]:
    """Nombre de tours au-dela duquel la bataille s'arrete, ou None si illimitee.

    SOURCE UNIQUE de la duree d'une bataille : ``game_rules.max_turns`` (regle 40k :
    une bataille dure 5 rounds). Le training ne redefinit plus cette duree — l'ancienne
    cle ``max_turns_per_episode`` des training configs dupliquait la meme valeur et
    pouvait diverger silencieusement de la regle.

    ``unlimited_turns`` (drapeau du game_state) exprime le seul cas metier sans limite :
    l'Endless Duty, base sur des vagues et non sur des tours.
    """
    # get allowed (drapeau optionnel, absence = bataille LIMITEE). Ce n'est pas un masquage
    # d'erreur : la regle 40k impose une duree bornee, et seul l'Endless Duty pose
    # explicitement le drapeau pour s'en affranchir.
    if game_state.get("unlimited_turns", False):
        return None
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    max_turns = require_key(game_rules, "max_turns")
    if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns <= 0:
        raise ValueError(f"game_rules.max_turns must be a positive int, got {max_turns!r}")
    return max_turns


def get_controlled_player(game_state: Dict[str, Any]) -> int:
    """Retourne le numéro du joueur contrôlé (config.controlled_player)."""
    return int(require_key(require_key(game_state, "config"), "controlled_player"))


def turn_limit_reached(game_state: Dict[str, Any]) -> bool:
    """True quand le tour courant depasse la duree de bataille (cf. get_effective_turn_limit)."""
    limit = get_effective_turn_limit(game_state)
    if limit is None:
        return False
    return int(require_key(game_state, "turn")) > limit


def enter_phase(game_state: Dict[str, Any], phase: str) -> None:
    """ECRIVAIN UNIQUE de ``game_state["phase"]`` : pose la phase ET enregistre le passage.

    POURQUOI un ecrivain unique. Le controle d objectif (14.02) est determine A LA FIN de chaque
    phase, et son declencheur
    (``GameStateManager.refresh_objective_control_on_boundary``) n observe l etat que par
    intermittence : une fois par step moteur, une fois par serialisation d API. Or
    ``W40KEngine.execute_semantic_action`` enchaine plusieurs phases DANS LA MEME action
    (cascade de `phase_complete`). Les phases intermediaires n etaient alors visibles de
    personne, et leur fin n etait jamais soldee.

    MESURE (2026-08-12, scenario PvE) : la derniere pose de deploiement enchainait
    ``deployment -> command -> move`` en une action ; la seule frontiere observee etait
    ``deployment -> move``, qui ne correspond a AUCUN point de
    ``game_config.objective_control_check.points``. Le checkpoint de fin de phase de
    commandement du tour 1 etait perdu : un Dreadnought pose dans un terrain-objectif laissait
    l objectif neutre, sans une ligne au journal, pendant TOUTE la phase de mouvement.

    La file ``PHASES_TRAVERSED_KEY`` porte donc la SUITE des phases franchies depuis le dernier
    solde. Elle est drainee par le declencheur, qui solde chaque frontiere une par une. Ajouter
    ``deployment/end`` aux points aurait ferme ce cas-la seulement, et laisse le meme trou sur
    toute autre cascade (une phase de tir sans tireur eligible, par exemple).

    Une reecriture de la MEME phase n est pas une frontiere : elle n empile rien.

    Ici et pas dans ``game_state.py`` : ce module est sans dependance interne, donc importable
    au niveau module par les six `phase_handlers` et par `w40k_core`, qui importent
    ``game_state`` en differe pour cause de cycle.
    """
    if not isinstance(phase, str) or not phase:
        raise ValueError(f"enter_phase: phase doit etre une chaine non vide, recu {phase!r}")
    if game_state.get("phase") == phase:  # get allowed (aucune phase posee = 1re pose)
        return
    if PHASES_TRAVERSED_KEY not in game_state:
        game_state[PHASES_TRAVERSED_KEY] = []
    game_state[PHASES_TRAVERSED_KEY].append(phase)
    game_state["phase"] = phase
