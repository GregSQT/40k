#!/usr/bin/env python3
"""engine/ability_calls.py — APPEL DE CAPACITÉ : « you can … » rendu à l'agent (2026-09-18).

Une capacité ACTIVABLE (Da Jump, Grot Orderly, Finest Hour, …) est un point de choix du joueur :
l'utiliser maintenant, ou passer. Ce module est le SOCLE unique de ces choix — chaque capacité
n'y apporte que deux fonctions (son EFFET et l'HEURISTIQUE du bot), jamais un mécanisme.

Mécanisme : `push_ability_call` empile un prompt de la file `pending_rule_choice_queue`
(`w40k_core._emit_next_rule_choice_prompt_if_needed` la sert déjà aux TROIS sièges — humain
`waiting_for_rule_choice` + panneau rule_choice, bot `_select_ai_rule_choice_option`, gym décision
`rule_choice` + `CHOICE_i`) avec DEUX candidats : [accorde `effect_id`] et [`declines`]. Le
candidat qui accorde est décrit à l'agent par l'`obs_id` de l'effet (`decision_options_effect_ids`,
la MÊME table d'embedding que « ce que j'ai » sur les entités) : ouvrir une capacité activable
coûte donc 0 colonne et 0 scalaire — c'est ce que la refonte du bloc candidat existe pour garantir.

L'APPLICATION de l'effet est déléguée à la capacité (`ABILITY_CALL_HANDLERS`), jamais au chemin de
grant de tour des `rule_choice` classiques (`_selected_granted_rule_id`, effacé par
`_clear_turn_scoped_rule_choices` à chaque phase de commandement) : une activation 1×/partie ou
1×/tour pose ses PROPRES drapeaux, et c'est elle qui sait quoi consommer. Le refus ne consomme
rien : il appartient au poseur de reproposer ou non (Grot Orderly : au tour suivant ; Finest
Hour : à la prochaine sélection).

Chaque capacité est ENREGISTRÉE (`register_ability_call`) avec son gestionnaire ET sa politique de
bot : un effet sans politique déclarée ne peut pas être proposé — jamais un tirage silencieux au
siège bot.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from engine.observation_entities import UNIT_RULE_EFFECT_IDS
from shared.data_validation import require_key

#: `kind` des prompts de la file `pending_rule_choice_queue` posés par ce module ; les prompts
#: classiques (`_enqueue_rule_choice_candidates`, `usage: or|unique`) n'en portent pas.
ABILITY_CALL_PROMPT_KIND = "ability_call"

#: `display_rule_id` du candidat qui PASSE. Ce n'est pas une règle : le front l'affiche par son
#: `label` et son drapeau `declines`, le moteur ne le résout jamais vers un effet.
ABILITY_CALL_DECLINE_ID = "decline"

#: `trigger` des prompts d'appel de capacité (le front lit d'abord `phase` pour son libellé).
ABILITY_CALL_TRIGGER = "ability_call"

#: Phases où un appel de capacité peut être posé — le poseur DIT à quel moment de règle il pose.
ABILITY_CALL_PHASES = ("command", "move", "shoot", "charge", "fight")

#: Gestionnaire d'EFFET : `(game_state, squad_id, accepted) -> payload`. Appelé pour les deux
#: réponses — un refus peut avoir à journaliser ou à noter quelque chose côté capacité. Le payload
#: rendu est fusionné dans la réponse du moteur (un gestionnaire qui pose une décision d'agent y
#: met `waiting_for_player: True`).
AbilityCallHandler = Callable[[Dict[str, Any], str, bool], Dict[str, Any]]

#: Politique du siège BOT (PvE hors gym) : `(game_state, squad_id) -> accepte ?`. DÉCLARÉE par
#: capacité, jamais un tirage.
AbilityCallBotPolicy = Callable[[Dict[str, Any], str], bool]

ABILITY_CALL_HANDLERS: Dict[str, AbilityCallHandler] = {}
ABILITY_CALL_BOT_POLICIES: Dict[str, AbilityCallBotPolicy] = {}


def register_ability_call(
    effect_id: str, *, handler: AbilityCallHandler, bot_policy: AbilityCallBotPolicy
) -> None:
    """Déclare une capacité activable : son effet ET la politique de son siège bot, ensemble.

    L'effet doit appartenir au vocabulaire OBSERVÉ (`UNIT_RULE_EFFECT_IDS`) : c'est son `obs_id`
    qui décrit le candidat à l'agent. Une seconde déclaration du même effet LÈVE — deux
    gestionnaires pour une capacité, c'est un import en double ou une capacité mal nommée.
    """
    if effect_id not in UNIT_RULE_EFFECT_IDS:
        raise KeyError(
            f"register_ability_call: effet '{effect_id}' absent de UNIT_RULE_EFFECT_IDS — sans "
            f"obs_id, l'agent ne pourrait pas percevoir ce que le candidat lui accorde."
        )
    if effect_id in ABILITY_CALL_HANDLERS:
        raise ValueError(f"register_ability_call: effet '{effect_id}' déjà enregistré")
    ABILITY_CALL_HANDLERS[effect_id] = handler
    ABILITY_CALL_BOT_POLICIES[effect_id] = bot_policy


def is_ability_call_prompt(prompt: Dict[str, Any]) -> bool:
    """Le prompt de la file est-il un appel de capacité (et non un `rule_choice` de datasheet) ?"""
    return prompt.get("kind") == ABILITY_CALL_PROMPT_KIND  # get allowed : absent = rule_choice


def ability_call_effect_id(prompt: Dict[str, Any]) -> str:
    """L'effet qu'un prompt d'appel de capacité propose d'activer."""
    if not is_ability_call_prompt(prompt):
        raise ValueError(f"ability_call_effect_id: le prompt n'est pas un appel de capacité : {prompt!r}")
    return str(require_key(prompt, "rule_id"))


def ability_call_display_name(game_state: Dict[str, Any], effect_id: str) -> str:
    """Nom AFFICHÉ de la capacité (registre `config/unit_rules.json`, clé `name`)."""
    from config_loader import get_config_loader

    registry = get_config_loader().load_unit_rules_config()
    if effect_id not in registry:
        raise KeyError(f"ability_call: effet '{effect_id}' absent de config/unit_rules.json")
    name = require_key(registry[effect_id], "name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"ability_call: la règle '{effect_id}' doit déclarer un 'name' non vide")
    return name.strip()


def pending_ability_call_prompts(
    game_state: Dict[str, Any], *, squad_id: Optional[str] = None, effect_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Les appels de capacité encore dans la file (actif compris), filtrés."""
    queue = game_state.get("pending_rule_choice_queue")  # get allowed : file jamais initialisée
    if not isinstance(queue, list):
        return []
    found: List[Dict[str, Any]] = []
    for prompt in queue:
        if not is_ability_call_prompt(prompt):
            continue
        if squad_id is not None and str(require_key(prompt, "unit_id")) != str(squad_id):
            continue
        if effect_id is not None and ability_call_effect_id(prompt) != effect_id:
            continue
        found.append(prompt)
    return found


def push_ability_call(
    game_state: Dict[str, Any], squad_id: str, effect_id: str, phase: str
) -> Dict[str, Any]:
    """Pose l'appel de capacité `effect_id` à l'escouade `squad_id` (observateur = l'escouade).

    Le prompt est EMPILÉ dans `pending_rule_choice_queue` ; c'est l'appelant moteur qui le sert
    aux sièges (`_emit_next_rule_choice_prompt_if_needed`), comme pour tout prompt de la file. Le
    poseur garantit les conditions de règle (porteur vivant, usage non dépensé, moment) : ici ne
    sont vérifiés que les invariants du socle — effet enregistré, escouade vivante et porteuse de
    l'effet, phase déclarée, pas de doublon dans la file.
    """
    from engine.phase_handlers.shared_utils import is_unit_alive, require_unit_by_id, unit_has_rule_effect

    if effect_id not in ABILITY_CALL_HANDLERS:
        raise KeyError(
            f"push_ability_call: effet '{effect_id}' sans gestionnaire ni politique de bot "
            f"(`register_ability_call`) — un appel sans siège bot déclaré serait un tirage."
        )
    if phase not in ABILITY_CALL_PHASES:
        raise ValueError(
            f"push_ability_call: phase {phase!r} inconnue (attendu : {ABILITY_CALL_PHASES})"
        )
    squad_id = str(squad_id)
    unit = require_unit_by_id(game_state, squad_id)
    if not is_unit_alive(squad_id, game_state):
        raise ValueError(f"push_ability_call: l'escouade {squad_id} n'est plus vivante")
    if not unit_has_rule_effect(unit, effect_id):
        raise ValueError(
            f"push_ability_call: l'escouade {squad_id} ne porte pas l'effet '{effect_id}' "
            f"(source morte ou règle absente) — la capacité ne peut pas lui être proposée"
        )
    if pending_ability_call_prompts(game_state, squad_id=squad_id, effect_id=effect_id):
        raise RuntimeError(
            f"push_ability_call: appel '{effect_id}' déjà en attente pour l'escouade {squad_id} "
            f"— le poseur se rejoue sans garde"
        )
    name = ability_call_display_name(game_state, effect_id)
    prompt: Dict[str, Any] = {
        "kind": ABILITY_CALL_PROMPT_KIND,
        "trigger": ABILITY_CALL_TRIGGER,
        "phase": phase,
        "player": int(require_key(unit, "player")),
        "unit_id": squad_id,
        "rule_id": effect_id,
        "display_name": name,
        "usage": "unique",
        # ORDRE CONTRACTUEL (§9.6) : candidat 0 = activer, candidat 1 = passer. `CHOICE_0` active.
        "options": [
            {
                "display_rule_id": effect_id,
                "technical_rule_id": effect_id,
                "label": name,
                "declines": False,
            },
            {
                "display_rule_id": ABILITY_CALL_DECLINE_ID,
                "technical_rule_id": None,
                "label": f"Passer ({name})",
                "declines": True,
            },
        ],
    }
    queue = game_state.setdefault("pending_rule_choice_queue", [])
    if not isinstance(queue, list):
        raise TypeError("pending_rule_choice_queue must be a list")
    queue.append(prompt)
    return prompt


def ability_call_selection_is_accept(prompt: Dict[str, Any], selected_display_rule_id: str) -> bool:
    """Le candidat choisi ACTIVE-t-il la capacité ? Toute autre valeur que les deux candidats LÈVE."""
    effect_id = ability_call_effect_id(prompt)
    if selected_display_rule_id == effect_id:
        return True
    if selected_display_rule_id == ABILITY_CALL_DECLINE_ID:
        return False
    raise ValueError(
        f"ability_call: candidat {selected_display_rule_id!r} inconnu pour l'appel '{effect_id}' "
        f"(attendu {effect_id!r} ou {ABILITY_CALL_DECLINE_ID!r})"
    )


def apply_ability_call(
    game_state: Dict[str, Any], prompt: Dict[str, Any], accepted: bool
) -> Dict[str, Any]:
    """Applique la réponse : le gestionnaire de la capacité fait le reste."""
    effect_id = ability_call_effect_id(prompt)
    handler = ABILITY_CALL_HANDLERS.get(effect_id)  # get allowed : contrôlé juste après
    if handler is None:
        raise KeyError(f"apply_ability_call: effet '{effect_id}' sans gestionnaire enregistré")
    result = handler(game_state, str(require_key(prompt, "unit_id")), bool(accepted))
    if not isinstance(result, dict):
        raise TypeError(
            f"apply_ability_call: le gestionnaire de '{effect_id}' doit rendre un dict, "
            f"reçu {type(result).__name__}"
        )
    return result


def bot_accepts_ability_call(game_state: Dict[str, Any], prompt: Dict[str, Any]) -> bool:
    """Réponse du siège BOT : la politique DÉCLARÉE de la capacité, jamais un tirage."""
    effect_id = ability_call_effect_id(prompt)
    policy = ABILITY_CALL_BOT_POLICIES.get(effect_id)  # get allowed : contrôlé juste après
    if policy is None:
        raise KeyError(f"bot_accepts_ability_call: effet '{effect_id}' sans politique de bot")
    return bool(policy(game_state, str(require_key(prompt, "unit_id"))))
