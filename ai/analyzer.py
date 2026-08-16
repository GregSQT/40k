#!/usr/bin/env python3
"""
analyzer.py - Analyze step.log and validate game rules compliance
Run this locally: python ai/analyzer.py step.log
"""

import sys
import os
import re
import math
from collections import defaultdict, Counter
from typing import Dict, Iterator, List, Mapping, Tuple, Set, Optional, Any

# Add project root to Python path for imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import utility functions from engine
from engine.combat_utils import (
    calculate_hex_distance,
    get_hex_neighbors,
)
from shared.data_validation import require_key
from ai.analyzer_perfig import position_is_on_battlefield
from ai.analyzer_rules import coverage_gaps, coverage_rows, new_rule_usage_counters


def _weapon_rule_usage_pair_total(weapon_rule_usage: Dict[Any, Any], pair_key: Any) -> int:
    """Sum P1/P2 counts for a weapon-rule pair; missing bucket or keys count as 0."""
    bucket = weapon_rule_usage.get(pair_key)
    if not isinstance(bucket, dict):
        return 0
    v1 = bucket.get(1)
    v2 = bucket.get(2)
    total = 0
    if isinstance(v1, int) and not isinstance(v1, bool):
        total += v1
    if isinstance(v2, int) and not isinstance(v2, bool):
        total += v2
    return total




_BOARD_HEADER_RE = re.compile(r'^\[[^\]]*\]\s*Board:\s.*\binches_to_subhex=(\d+)\b')
_BOARD_DIMS_RE = re.compile(r'^\[[^\]]*\]\s*Board:\s.*\bcols=(\d+)\b.*\brows=(\d+)\b')


def parse_board_dims_from_log(filepath: str) -> Tuple[int, int]:
    """`(cols, rows)` du plateau du run analysé, lus dans la MÊME entête `Board:` que l'échelle.

    Même contrat qu'elle, et pour la même raison : `config/board/*.json` change d'un run à
    l'autre, et le BFS de mouvement doit refuser un pas hors plateau (03.01) sur les dimensions
    du journal relu. L'entête est écrite à chaque démarrage d'épisode (`ai/step_logger.py`) et
    porte `cols=` et `rows=` depuis toujours : son absence est une rupture de contrat.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            m = _BOARD_DIMS_RE.match(line)
            if m:
                return int(m.group(1)), int(m.group(2))
    raise ValueError(
        f"{filepath}: aucune ligne d'entête 'Board: cols=N rows=N'. Les dimensions du plateau "
        "sont indéterminables — un BFS de mouvement sans bord accepte les chemins qui sortent "
        "du plateau, que 03.01 interdit."
    )


def parse_board_scale_from_log(filepath: str) -> int:
    """Échelle subhex/pouce du run analysé, lue dans l'entête `Board:` du step.log.

    SOURCE UNIQUE. Elle ne peut PAS venir de `board_config` : le config courant décrit le
    prochain run, pas celui qu'on relit. Un step.log produit sur `board/44x60x1` relu avec un
    `config.json` pointant `board/44x60x5` donnait des distances ×5 — engagement à 10 subhex
    au lieu de 2 (132 faux « shoot at engaged enemy »), et symétriquement des portées, budgets
    de move et d'advance ×5 qui ne se déclenchaient jamais : l'analyzer fabriquait des erreurs
    ET en masquait. Le step logger écrit cette ligne à chaque démarrage d'épisode
    (`ai/step_logger.py`, « Board: cols=… inches_to_subhex=… ») : elle est toujours présente
    sur un log réel, et son absence est une rupture de contrat, pas un cas à replier.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            m = _BOARD_HEADER_RE.match(line)
            if m:
                return int(m.group(1))
    raise ValueError(
        f"{filepath}: aucune ligne d'entête 'Board: ... inches_to_subhex=N'. L'échelle du run "
        "est indéterminable — analyser avec l'échelle du config courant produirait des "
        "distances fausses (faux positifs d'engagement, contrôles de portée neutralisés)."
    )


_RUN_RULES_RE = re.compile(r'^\[[^\]]*\]\s*Run rules:\s*(.+)$')
_LOG_GRAMMAR_RE = re.compile(r'^\[[^\]]*\]\s*Log grammar:\s*(\d+)\s*$')


def parse_log_grammar_version(filepath: str) -> int:
    """Version de grammaire déclarée par l'entête `Log grammar:` — 1 si la ligne est absente.

    ⚠️ CE QUE CETTE VERSION SERT À FAIRE, et c'est sa seule raison d'exister : distinguer
    « le journal ne PORTE pas cette donnée » de « le producteur a OUBLIÉ de l'écrire ».

    Sans elle, un lecteur qui ne trouve pas `[ALLOC_MODEL:]` sur une ligne de dégâts n'a d'autre
    choix que de retomber en silence sur une reconstruction approximative — le repli qui masque
    une panne au lieu de la dire. Avec elle, l'absence devient une ERREUR sur un journal qui
    promet la donnée, et reste un fait normal sur un journal antérieur.

    Une version INCONNUE (> celles gérées) n'est pas une erreur : un journal plus récent porte
    au moins ce que promettent les versions antérieures — c'est la règle qui rend le numéro
    utile, et `ai/step_logger.LOG_GRAMMAR_VERSION` ne s'incrémente que pour une garantie
    NOUVELLE, jamais pour un changement cosmétique.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            m = _LOG_GRAMMAR_RE.match(line)
            if m:
                return int(m.group(1))
            # L'entête est un bloc contigu : dès la première ligne d'action, la ligne de version
            # ne viendra plus. Balayer 35 Mo pour une ligne absente coûterait le prix d'une passe
            # entière à chaque journal d'ancienne grammaire.
            if "=== ACTIONS START ===" in line:
                break
    return 1


def parse_run_rules_from_log(filepath: str) -> Dict[str, str]:
    """Règles appliquées par le run analysé, lues dans l'entête `Run rules:` du step.log.

    MÊME contrat que `parse_board_scale_from_log`, et pour la même raison :
    `config/game_config.json` s'édite entre deux runs. Relire `engagement_zone`, les métriques
    de distance ou les toggles de traversée au moment de l'ANALYSE, c'est juger un vieux journal
    avec les règles du jour — basculer `distance_metric.engagement` de `hex` à `euclidean`
    changerait tous les verdicts d'engagement d'hier, sans le moindre signe.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            m = _RUN_RULES_RE.match(line)
            if m:
                rules: Dict[str, str] = {}
                for token in m.group(1).split():
                    if "=" not in token:
                        raise ValueError(f"{filepath}: token `Run rules:` illisible: {token!r}")
                    key, _, value = token.partition("=")
                    rules[key] = value
                if not rules:
                    raise ValueError(f"{filepath}: entête `Run rules:` vide")
                return rules
    raise ValueError(
        f"{filepath}: aucune ligne d'entête 'Run rules: ...'. Les règles du run sont "
        "indéterminables — analyser avec celles du config courant rendrait des verdicts faux "
        "en silence (zone d'engagement, métrique de distance, traversée)."
    )


def set_analyzer_board_scale(inches_to_subhex: int) -> None:
    """Fixe l'échelle du run pour toute la passe (appelé par parse_step_log après lecture de
    l'entête). L'état vit dans `ai.analyzer_config` — seul module chargé en un exemplaire quand
    la CLI exécute `ai/analyzer.py` comme `__main__`."""
    from ai.analyzer_config import set_run_inches_to_subhex
    set_run_inches_to_subhex(int(inches_to_subhex))


def set_analyzer_board_dims(cols: int, rows: int) -> None:
    """Fixe les dimensions du plateau du run pour toute la passe (même raison d'emplacement que
    l'échelle : `ai.analyzer_config` n'existe qu'en un exemplaire)."""
    from ai.analyzer_config import set_run_board_dims
    set_run_board_dims(int(cols), int(rows))


def _get_inches_to_subhex_for_analyzer() -> int:
    """Échelle subhex/pouce du run en cours d'analyse (cf. parse_board_scale_from_log).
    Boardx10-final §P3: advance budget = D6 face × this scale.
    """
    from ai.analyzer_config import get_run_inches_to_subhex
    return get_run_inches_to_subhex()


def _get_engagement_zone_for_analyzer() -> int:
    """Engagement zone en SUBHEXES, identique au moteur.

    game_config['game_rules']['engagement_zone'] est stocké EN POUCES (standard GW). Le moteur
    le convertit ×inches_to_subhex au chargement (engine.w40k_core : gr['engagement_zone'] *=
    inches_to_subhex). L'analyzer doit appliquer la MÊME conversion, sinon il compare des
    empreintes (subhex) à un seuil en pouces (2 au lieu de 10) → toute la mêlée/engagement
    remontait faussement « non-adjacent ». Root cause des « Fight from non-adjacent ».
    """
    # Déjà en SUBHEXES dans l'entête : le moteur convertit au chargement et journalise la
    # valeur qu'il applique. Aucune conversion ici, donc aucune occasion de diverger.
    from ai.analyzer_config import get_run_rule
    return int(get_run_rule("engagement_zone_subhex"))

MAX_D3 = 3
MAX_D6 = 6
MAX_D6_PLUS_1 = 7
MAX_D6_PLUS_2 = 8
MAX_D6_PLUS_3 = 9
MAX_2D6 = 12
DICE_MAX_VALUES = {
    "D3": MAX_D3,
    "D6": MAX_D6,
    "D6+1": MAX_D6_PLUS_1,
    "D6+2": MAX_D6_PLUS_2,
    "D6+3": MAX_D6_PLUS_3,
    "2D6": MAX_2D6,
}
PLAYER_ONE_ID = 1
PLAYER_TWO_ID = 2


def max_dice_value(value: Any, context: str) -> int:
    """
    Resolve a dice value to its maximum possible roll (no RNG).

    Supported dice strings: "D3", "D6", "D6+1", "D6+2", "D6+3", "2D6".
    """
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise TypeError(f"Invalid dice value type for {context}: {type(value).__name__}")
    if value not in DICE_MAX_VALUES:
        raise ValueError(f"Unsupported dice expression for {context}: {value}")
    return DICE_MAX_VALUES[value]

# Global variable for debug log file
_debug_log_file = None


def _debug_log(message: str) -> None:
    """Write debug message to analyzer_debug.log if file is open."""
    global _debug_log_file
    if _debug_log_file:
        _debug_log_file.write(message + "\n")
        _debug_log_file.flush()


# ── Résolution de scénario & contrôle d'objectif : SUPPRIMÉS (2026-07-29) ──
# Vivaient ici cinq fonctions et deux caches qui n'ont plus aucun appelant :
#   _resolve_scenario_path, _resolve_terrain_path_for_scenario,
#   _get_objective_name_to_id_map, _get_primary_objective_ids_for_scenario,
#   _calculate_primary_objective_points  (+ _calculate_objective_control_snapshot, plus bas)
# Elles n'existaient QUE pour reconstruire le contrôle d'objectif et re-marquer les points
# de victoire depuis le step.log. Ce calcul était faux par construction : somme de l'OC par
# ANCRE d'escouade alors que le moteur somme par empreinte de socle (14.02,
# sum_objective_control_oc_multi), sans le battle-shock (01.07 : OC de toutes les figurines
# à '-', 02.02), et à chaque action alors que le contrôle est figé en fin de phase/tour.
# Le moteur journalise désormais son état (`T{tour} OBJECTIVE CONTROL: VP1=… VP2=… ZONES=…`,
# StepLogger.log_objective_control_snapshot) et analyzer_core.py le lit tel quel.
# Conséquence directe : l'appariement nom → id positionnel via le terrain disparaît, et avec
# lui la coexistence de trois formats d'identifiant d'objectif signalée dans V11_tranches.md.
# Pour retrouver la résolution d'un chemin de scénario, le point d'entrée vivant est
# `config_loader` (utilisé par train.py, bot_evaluation.py et le moteur).


def _get_unit_hp_value(
    unit_hp: Dict[str, int],
    unit_id: str,
    stats: Optional[Dict] = None,
    current_episode_num: Optional[int] = None,
    turn: Optional[int] = None,
    phase: Optional[str] = None,
    line_text: Optional[str] = None,
    context: str = "unit_hp lookup"
) -> Optional[int]:
    """Get unit_hp value with explicit error logging when missing."""
    if unit_id not in unit_hp:
        if stats is not None and line_text is not None:
            stats['parse_errors'].append({
                'episode': current_episode_num,
                'turn': turn,
                'phase': phase,
                'line': line_text.strip(),
                'error': f"{context} missing unit_hp for unit_id: {unit_id}"
            })
        else:
            _debug_log(f"[ANALYZER WARNING] {context} missing unit_hp for unit_id: {unit_id}")
        return None
    return require_key(unit_hp, unit_id)


def _apply_damage_and_handle_death(
    target_id: str,
    attacker_id: Optional[str],
    damage: int,
    player: int,
    turn: int,
    phase: str,
    line_number: int,
    current_episode_num: int,
    line_text: str,
    dead_units_current_episode: Set[str],
    unit_hp: Dict[str, int],
    unit_models_alive: Dict[str, int],
    unit_model_hp: Dict[str, Dict[str, int]],
    ordered_living_mids: Any,
    unit_hp_squad_max: Dict[str, int],
    unit_types: Dict[str, str],
    unit_positions: Dict[str, Tuple[int, int]],
    unit_deaths: List[Tuple[int, str, str, int]],
    unit_kill_context: Dict[str, Tuple[str, int, str]],
    stats: Dict[str, Any],
    positions_by_model: Optional[Dict[str, Dict[str, Tuple[int, int]]]] = None,
    models_invalidated: Optional[Set[str]] = None,
    alloc_model_id: Optional[str] = None,
    pending_model_removals: Optional[Dict[str, Set[str]]] = None,
) -> None:
    """Applique une blessure à la cible via l'allocation par-figurine (05 Attack sequence).

    ``alloc_model_id`` — la figurine que le MOTEUR a allouée, lue dans le segment
    `[ALLOC_MODEL:]` de la ligne (grammaire de journal ≥ 2). Quand elle est là, plus rien n'est
    déduit : la blessure va sur CETTE figurine, et si elle tombe c'est CE socle qui est retiré.
    Le reste de cette docstring décrit le chemin HÉRITÉ, celui des journaux qui ne la portent
    pas — il reconstruit par déduction ce que le journal ne disait pas, et les deux déductions
    qu'il fait sont fausses (mesuré le 2026-08-12, cf. ci-dessous).

    Une blessure est allouée à la figurine « front » ; si ses PV tombent ≤ 0 elle est détruite
    et le RESTE est reporté sur la suivante. L'escouade n'est retirée que lorsque sa DERNIÈRE
    figurine est détruite. unit_hp reste l'invariant d'aliveness (présent et > 0 ⟺ vivante).

    ⚠️ POURQUOI L'EXCÈS EST REPORTÉ, ET NON PERDU — la question a été tranchée deux fois dans
    le mauvais sens avant de l'être par le code. `Dmg:XHP` n'est PAS le dégât brut de l'arme :
    le moteur le PLAFONNE avant de le journaliser.

        shared_utils, résolution d'une blessure du pool (seul site écrivant un damageDealt
        non nul) :
            dmg_dealt = min(int(dmg), hp_before)      # ← plafond
            … Feel No Pain peut encore le réduire …
            new_hp = hp_before - dmg_dealt            # ≥ 0
            rec["damageDealt"] = dmg_dealt            # ← c'est le PLAFONNÉ qui part au log

    Chaque `Dmg:X` journalisé vaut donc EXACTEMENT les PV retirés à une figurine : la somme des
    `Dmg:` d'une escouade est sa perte de PV totale. En retrancher une partie (règle d'overkill
    appliquée une seconde fois) fait survivre des escouades que le moteur a tuées — l'unité 102
    du témoin encaissait 4 PV pour 4 PV restants et restait debout, faisant sonner « tir sur
    cible engagée » sur un tir légal.

    Le scénario inverse, « une arme Damage-2 tue deux socles à 1 PV », ne peut pas se produire :
    contre un socle à 1 PV le moteur journalise `Dmg:1HP`, jamais 2. C'est le plafond qui
    l'interdit.

    Le report s'arrête à la dernière figurine : au-delà, l'excès n'a plus de destinataire. Seule
    exception connue à l'invariant, sans effet ici : la ligne `IMPACTED … Dmg:` de la charge
    écrit une constante de blessures mortelles et plafonne au niveau de l'UNITÉ — l'escouade y
    meurt dans les deux modèles, donc aucun écart observable.

    `positions_by_model` — les socles connus de la cible deviennent PÉRIMÉS dès qu'elle perd une
    figurine : le log ne dit pas LAQUELLE (l'allocation est « front », pas nominative), et le
    segment `[MODELS:]` de la cible ne sera réécrit qu'à sa prochaine ACTION. Les garder ferait
    mesurer l'engagement, les empreintes et les obstacles de BFS contre des figurines retirées
    du plateau — un tir sur une escouade dont le socle avancé vient d'être tué remontait
    « cible engagée » alors que le survivant est à l'autre bout. On efface donc l'entrée : la
    mesure retombe sur l'ancre, fraîche à chaque ligne. Donnée absente, pas mesure fausse.

    ⚠️ CE QUE CE CHEMIN HÉRITÉ COÛTE, mesuré sur 600 épisodes le 2026-08-12 — c'est ce qui a
    fait écrire `[ALLOC_MODEL:]`, et ça vaut pour tout journal de grammaire 1 :
      - POSITIONS : 2 342 fenêtres où l'escouade entière retombe sur son ancre, elle-même restée
        sur le hex de la figurine qui vient de tomber. Médiane 3 lignes, p90 119, 19 % débordent
        sur le tour suivant. Un tir légal y ressort « au contact avec une arme non-CLOSE_QUARTERS ».
      - PV : la figurine touchée est déduite d'un tri CHARACTER/non-CHARACTER, quand le moteur
        applique la cascade `_select_allocation_model` (blessée d'abord, tier de rôle, proximité
        d'un ennemi, index). 200 PV par socle faux sur 173 129 comparés aux instantanés
        `T{n} STATE:` — minorant, l'instantané recalant tout à chaque tour."""
    if damage <= 0:
        return
    if target_id not in unit_hp:
        # Exception 05 Attack sequence : blessure de la MÊME activation qui a détruit la
        # cible (même attaquant, même turn/phase) = « excess wound lost », pas une anomalie.
        if unit_kill_context.get(target_id) == (attacker_id, turn, phase):
            _debug_log(
                f"[EXCESS WOUND LOST] E{current_episode_num} T{turn} {phase} "
                f"target_id={target_id} damage={damage} killer={attacker_id}"
            )
            return
        stats['damage_missing_unit_hp'][player] += 1
        if stats['first_error_lines']['damage_missing_unit_hp'][player] is None:
            stats['first_error_lines']['damage_missing_unit_hp'][player] = {
                'episode': current_episode_num,
                'line': line_text.strip()
            }
        _debug_log(
            f"[DAMAGE IGNORED] E{current_episode_num} T{turn} {phase} "
            f"target_id={target_id} damage={damage} reason=target_missing_unit_hp"
        )
        return
    _debug_log(
        f"[DAMAGE APPLY] E{current_episode_num} T{turn} {phase} "
        f"target_id={target_id} damage={damage} front_hp={unit_hp[target_id]} "
        f"models_alive={require_key(unit_models_alive, target_id)}"
    )
    if alloc_model_id is not None:
        _apply_damage_to_named_model(
            target_id=target_id, attacker_id=attacker_id, alloc_model_id=alloc_model_id,
            damage=damage, player=player, turn=turn, phase=phase, line_number=line_number,
            current_episode_num=current_episode_num,
            dead_units_current_episode=dead_units_current_episode,
            unit_hp=unit_hp, unit_models_alive=unit_models_alive, unit_model_hp=unit_model_hp,
            ordered_living_mids=ordered_living_mids, unit_types=unit_types,
            unit_positions=unit_positions, unit_deaths=unit_deaths,
            unit_kill_context=unit_kill_context, stats=stats,
            positions_by_model=positions_by_model,
            pending_model_removals=pending_model_removals,
        )
        return
    front_hp = unit_hp[target_id] - damage
    if front_hp <= 0:
        # Figurine front détruite. On retire le SOCLE NOMMÉ (premier de l'ordre 06.02) : les PV
        # des autres restent attachés à leur figurine, donc un recalage ultérieur sur
        # `[MODELS:]` ne peut plus les « soigner » (cf. `unit_model_hp`).
        _reste = -front_hp  # PV du coup non absorbés par la figurine qui tombe (cf. docstring)
        _living = ordered_living_mids(target_id)
        if _living:
            require_key(unit_model_hp, target_id).pop(_living[0], None)
        unit_models_alive[target_id] -= 1
        if positions_by_model is not None:
            positions_by_model.pop(target_id, None)
        if models_invalidated is not None:
            models_invalidated.add(target_id)
        if unit_models_alive[target_id] <= 0:
            # Dernière figurine détruite → escouade retirée.
            target_type = require_key(unit_types, target_id)
            stats['current_episode_deaths'].append((player, target_id, target_type))
            stats['wounded_enemies'][player].discard(target_id)
            _position_cache_remove(unit_positions, target_id)
            unit_deaths.append((turn, phase, target_id, line_number))
            dead_units_current_episode.add(target_id)
            if attacker_id is not None:
                unit_kill_context[target_id] = (attacker_id, turn, phase)
            _debug_log(
                f"[DEATH REMOVED] E{current_episode_num} T{turn} {phase} "
                f"target_id={target_id} target_type={target_type} killer={attacker_id}"
            )
            del unit_hp[target_id]
        else:
            # Relève : la figurine SUIVANTE devient front, avec SES PV RESTANTS — ni ceux de la
            # datasheet d'escouade (sous-évaluation corrigée le 2026-08-09), ni des PV pleins
            # qui la soigneraient si elle était déjà entamée (défaut corrigé le 2026-08-10).
            _next = ordered_living_mids(target_id)
            if _next:
                unit_hp[target_id] = int(unit_model_hp[target_id][_next[0]])
                if _reste > 0:
                    # Report par le MÊME chemin : la récursion rejoue toute la comptabilité
                    # (mort, retrait du socle, escouade détruite) au lieu d'en écrire une
                    # seconde version ici.
                    _apply_damage_and_handle_death(
                        target_id=target_id, attacker_id=attacker_id, damage=_reste,
                        player=player, turn=turn, phase=phase, line_number=line_number,
                        current_episode_num=current_episode_num, line_text=line_text,
                        dead_units_current_episode=dead_units_current_episode,
                        unit_hp=unit_hp, unit_models_alive=unit_models_alive,
                        unit_model_hp=unit_model_hp,
                        ordered_living_mids=ordered_living_mids,
                        unit_hp_squad_max=unit_hp_squad_max, unit_types=unit_types,
                        unit_positions=unit_positions, unit_deaths=unit_deaths,
                        unit_kill_context=unit_kill_context, stats=stats,
                        positions_by_model=positions_by_model,
                        models_invalidated=models_invalidated,
                    )
                    return
            else:
                # `unit_models_alive` dit qu'il reste une figurine mais aucun socle n'est connu :
                # composition absente du journal (antérieur à `[MODEL_TYPES:]`). Les PV
                # d'escouade sont la meilleure valeur DISPONIBLE — le signaler, pas le maquiller.
                _debug_log(
                    f"[HP PER-MODEL MISSING] E{current_episode_num} T{turn} {phase} "
                    f"target_id={target_id} models_left={unit_models_alive[target_id]}"
                )
                unit_hp[target_id] = require_key(unit_hp_squad_max, target_id)
            stats['wounded_enemies'][player].add(target_id)
            _debug_log(
                f"[MODEL SLAIN] E{current_episode_num} T{turn} {phase} "
                f"target_id={target_id} models_left={unit_models_alive[target_id]}"
            )
    else:
        unit_hp[target_id] = front_hp
        # Le socle NOMMÉ porte la blessure : `unit_hp` n'en est que le miroir scalaire.
        _living = ordered_living_mids(target_id)
        if _living:
            unit_model_hp[target_id][_living[0]] = front_hp
        stats['wounded_enemies'][player].add(target_id)
        _debug_log(
            f"[DAMAGE RESULT] E{current_episode_num} T{turn} {phase} "
            f"target_id={target_id} front_hp={front_hp}"
        )


def _apply_damage_to_named_model(
    *,
    target_id: str,
    attacker_id: Optional[str],
    alloc_model_id: str,
    damage: int,
    player: int,
    turn: int,
    phase: str,
    line_number: int,
    current_episode_num: int,
    dead_units_current_episode: Set[str],
    unit_hp: Dict[str, int],
    unit_models_alive: Dict[str, int],
    unit_model_hp: Dict[str, Dict[str, int]],
    ordered_living_mids: Any,
    unit_types: Dict[str, str],
    unit_positions: Dict[str, Tuple[int, int]],
    unit_deaths: List[Tuple[int, str, str, int]],
    unit_kill_context: Dict[str, Tuple[str, int, str]],
    stats: Dict[str, Any],
    positions_by_model: Optional[Dict[str, Dict[str, Tuple[int, int]]]],
    pending_model_removals: Optional[Dict[str, Set[str]]],
) -> None:
    """Blessure appliquée à la figurine que le moteur a NOMMÉE (`[ALLOC_MODEL:]`).

    Rien n'est déduit ici — ni qui encaisse, ni qui tombe. C'est toute la différence avec le
    chemin hérité, et c'est pourquoi ce chemin est plus court : les deux déductions qu'il
    remplace étaient les deux sources de faux mesurées le 2026-08-12.

    Trois conséquences, dans l'ordre :

    1. **Les PV vont sur CE socle.** `unit_hp` n'est plus qu'un miroir : il est recalculé depuis
       la figurine front après coup, jamais décrémenté à part. Deux compteurs qu'on décrémente
       chacun de son côté finissent par se contredire — c'est la panne front/relève déjà payée.

    2. **L'excès est PERDU, jamais reporté.** Le moteur plafonne (`dmg_dealt = min(dmg, hp_before)`)
       et c'est le plafonné qui part au journal : un `Dmg:` supérieur aux PV de la figurine
       nommée ne décrit donc aucune situation de jeu. Le reporter sur la suivante — ce que fait
       le chemin hérité, faute de savoir QUI encaisse — tuerait ici une figurine que le moteur
       laisse debout.

    3. **Seul CE socle sera retiré** de `positions_by_model` — et pas tout de suite : à la fin de
       l'ACTIVATION (`pending_model_removals`, appliqué par `analyzer_core` dès qu'une autre unité
       agit). L'escouade garde donc ses autres socles : plus de repli sur l'ancre, donc plus de
       point fantôme sur le hex du mort.

       Le retard n'est pas une précaution, c'est la règle : la portée se décide au Select Targets,
       une fois pour toute la salve. Mesuré le 2026-08-12 (E44) — retirer le socle dès sa mort
       faisait juger les derniers jets d'un Onslaught Gatling Cannon sur les survivants des
       premiers, à 25-27 hex pour une arme de 24, alors que la cible avait été choisie à 22.

    Figurine inconnue de l'analyzer : comptée en 2.8 (`alloc_model_unknown`), jamais silencieuse.
    Le moteur nomme un socle que l'état reconstruit ne connaît pas = les deux ont divergé, et
    c'est précisément ce que la section 2.8 existe pour dire.
    """
    per_model = require_key(unit_model_hp, target_id)
    if alloc_model_id not in per_model:
        stats['state_resync']['alloc_model_unknown'] += 1
        _debug_log(
            f"[ALLOC MODEL UNKNOWN] E{current_episode_num} T{turn} {phase} "
            f"target_id={target_id} model={alloc_model_id} known={sorted(per_model)}"
        )
        return
    hp_before = int(per_model[alloc_model_id])
    if hp_before - damage > 0:
        per_model[alloc_model_id] = hp_before - damage
        stats['wounded_enemies'][player].add(target_id)
        _sync_front_hp_mirror(target_id, unit_hp, unit_model_hp, ordered_living_mids)
        _debug_log(
            f"[DAMAGE RESULT] E{current_episode_num} T{turn} {phase} "
            f"target_id={target_id} model={alloc_model_id} hp={per_model[alloc_model_id]}"
        )
        return

    # Figurine détruite — celle-là, nommément.
    del per_model[alloc_model_id]
    unit_models_alive[target_id] -= 1
    if pending_model_removals is not None:
        pending_model_removals.setdefault(target_id, set()).add(alloc_model_id)
    if unit_models_alive[target_id] > 0:
        stats['wounded_enemies'][player].add(target_id)
        _sync_front_hp_mirror(target_id, unit_hp, unit_model_hp, ordered_living_mids)
        _debug_log(
            f"[MODEL SLAIN] E{current_episode_num} T{turn} {phase} "
            f"target_id={target_id} model={alloc_model_id} "
            f"models_left={unit_models_alive[target_id]}"
        )
        return

    # Dernière figurine : l'escouade quitte le plateau. Même comptabilité que le chemin hérité —
    # `unit_hp` reste l'invariant d'aliveness lu par tout le reste de l'analyzer.
    target_type = require_key(unit_types, target_id)
    stats['current_episode_deaths'].append((player, target_id, target_type))
    stats['wounded_enemies'][player].discard(target_id)
    _position_cache_remove(unit_positions, target_id)
    unit_deaths.append((turn, phase, target_id, line_number))
    dead_units_current_episode.add(target_id)
    if attacker_id is not None:
        unit_kill_context[target_id] = (attacker_id, turn, phase)
    _debug_log(
        f"[DEATH REMOVED] E{current_episode_num} T{turn} {phase} "
        f"target_id={target_id} target_type={target_type} killer={attacker_id}"
    )
    del unit_hp[target_id]


def _sync_front_hp_mirror(
    target_id: str,
    unit_hp: Dict[str, int],
    unit_model_hp: Dict[str, Dict[str, int]],
    ordered_living_mids: Any,
) -> None:
    """Réaligne ``unit_hp`` (miroir scalaire) sur les PV de la figurine front.

    Jumeau de `_sync_front_hp` (analyzer_core), qui fait le même réalignement après un recalage
    sur `[MODELS:]`. Ici la source est la carte par-socle qu'on vient de modifier : le miroir se
    DÉDUIT, il ne se maintient pas en parallèle — sans quoi les deux dérivent l'un de l'autre.
    """
    _living = ordered_living_mids(target_id)
    if _living:
        unit_hp[target_id] = int(unit_model_hp[target_id][_living[0]])


def _track_unit_reappearance(
    unit_id: str,
    unit_hp: Dict[str, int],
    unit_player: Dict[str, int],
    dead_units_current_episode: Set[str],
    revived_units_current_episode: Set[str],
    stats: Dict[str, Any],
    current_episode_num: int,
    line_text: str
) -> None:
    """Detect a unit that reappears alive after being removed as dead."""
    if unit_id not in dead_units_current_episode or unit_id in revived_units_current_episode:
        return
    if unit_id not in unit_hp:
        return
    if require_key(unit_hp, unit_id) <= 0:
        return
    if unit_id not in unit_player:
        stats['parse_errors'].append({
            'episode': current_episode_num,
            'turn': None,
            'phase': None,
            'line': line_text.strip(),
            'error': f"unit_revived missing unit_player for unit_id: {unit_id}"
        })
        return
    player = require_key(unit_player, unit_id)
    stats['unit_revived'][player] += 1
    if stats['first_error_lines']['unit_revived'][player] is None:
        stats['first_error_lines']['unit_revived'][player] = {
            'episode': current_episode_num,
            'line': line_text.strip()
        }
    revived_units_current_episode.add(unit_id)


def _get_latest_position_from_history(
    unit_id: str,
    unit_positions: Dict[str, Tuple[int, int]],
    unit_movement_history: Dict[str, List[Dict[str, Any]]]
) -> Tuple[int, int]:
    """Return latest known position from movement history."""
    require_key(unit_positions, unit_id)
    history = require_key(unit_movement_history, unit_id)
    if not history:
        raise ValueError(f"Movement history is empty for unit_id {unit_id}")
    last_entry = history[-1]
    last_pos = require_key(last_entry, "position")
    if last_pos is None:
        raise ValueError(f"Movement history position is None for unit_id {unit_id}")
    return last_pos

def hex_to_pixel(col: int, row: int, hex_radius: float = 21.0) -> Tuple[float, float]:
    """Convert hex coordinates to pixel coordinates (matching frontend algorithm)."""
    hex_width = 1.5 * hex_radius
    hex_height = (3 ** 0.5) * hex_radius  # sqrt(3)
    
    x = col * hex_width
    y = row * hex_height + ((col % 2) * hex_height / 2)
    
    return (x, y)


def line_segments_intersect(
    line1_start: Tuple[float, float], line1_end: Tuple[float, float],
    line2_start: Tuple[float, float], line2_end: Tuple[float, float]
) -> bool:
    """Check if two line segments intersect (matching frontend algorithm)."""
    d1 = (line1_end[0] - line1_start[0], line1_end[1] - line1_start[1])
    d2 = (line2_end[0] - line2_start[0], line2_end[1] - line2_start[1])
    d3 = (line2_start[0] - line1_start[0], line2_start[1] - line1_start[1])
    
    cross1 = d1[0] * d2[1] - d1[1] * d2[0]
    cross2 = d3[0] * d2[1] - d3[1] * d2[0]
    cross3 = d3[0] * d1[1] - d3[1] * d1[0]
    
    if abs(cross1) < 0.0001:  # Parallel lines
        return False
    
    t1 = cross2 / cross1
    t2 = cross3 / cross1
    
    return 0 <= t1 <= 1 and 0 <= t2 <= 1


def line_passes_through_hex(
    start_point: Tuple[float, float], end_point: Tuple[float, float],
    hex_col: int, hex_row: int, hex_radius: float = 21.0
) -> bool:
    """Check if a line passes through any part of a hex (matching frontend algorithm)."""
    hex_center = hex_to_pixel(hex_col, hex_row, hex_radius)
    
    # Create hex polygon points (6 corners)
    hex_points: List[Tuple[float, float]] = []
    for i in range(6):
        angle = (i * math.pi) / 3  # 60 degree increments for hex
        x = hex_center[0] + hex_radius * math.cos(angle)
        y = hex_center[1] + hex_radius * math.sin(angle)
        hex_points.append((x, y))
    
    # Check if line intersects any edge of the hex polygon
    for i in range(len(hex_points)):
        p1 = hex_points[i]
        p2 = hex_points[(i + 1) % len(hex_points)]
        
        if line_segments_intersect(start_point, end_point, p1, p2):
            return True
    
    return False


def get_hex_points(center_x: float, center_y: float, radius: float = 21.0) -> List[Tuple[float, float]]:
    """Get 9 points for a hex: center + 8 points around (matching frontend algorithm)."""
    points = [(center_x, center_y)]  # Center point
    
    # 8 corner points around the hex (not actual hex corners, but distributed around)
    for i in range(8):
        angle = (i * math.pi) / 4  # 45 degree increments
        x = center_x + radius * 0.8 * math.cos(angle)
        y = center_y + radius * 0.8 * math.sin(angle)
        points.append((x, y))
    
    return points


def _get_los_wall_hexes(wall_hexes: Set[Tuple[int, int]]) -> Set[Tuple[int, int]]:
    """
    Augment wall_hexes with board boundary hexes (bottom_row for odd cols).
    Matches engine/w40k_core.py for LoS consistency.
    """
    from config_loader import get_config_loader
    from engine.hex_utils import phantom_bottom_hexes
    cols, rows = get_config_loader().get_board_size()
    return set(wall_hexes) | phantom_bottom_hexes(cols, rows)


def has_line_of_sight(shooter_col: int, shooter_row: int, target_col: int, target_row: int, wall_hexes: Set[Tuple[int, int]]) -> bool:
    """LoS ANCRE-A-ANCRE approximative — METRIQUES COMPORTEMENTALES UNIQUEMENT.

    ⚠️ NE PAS utiliser pour un controle de conformite aux regles. Ce n'est PAS le predicat du
    moteur. La regle 06.01 exige « any part of the observing model to any part of the model
    being observed » : la LoS est socle-a-socle PAR FIGURINE. Ici on teste un point contre un
    point, donc strictement plus restrictif -> faux positifs (mesure sur un run reel : l'ancre
    d'un socle round/6 ne voyait pas la cible alors que 3 des 19 cellules de son empreinte la
    voyaient). De plus les coords du step.log sont des ancres d'ESCOUADE, pas la figurine que
    le moteur a testee.

    Le predicat du moteur est `_attacker_model_can_reach_squad` (shared_utils ~L4243) ; il exige
    `game_state` (empreintes, terrain obscurcissant 13.10, LoS 3D) que step.log ne porte pas —
    d'ou l'impossibilite de le reproduire ici.

    Reste acceptable pour les METRIQUES de comportement de l'agent (a-t-il attendu sans vue ?
    a-t-il vu une cible blessee ?), ou une approximation grossiere est sans consequence.

    Algorithme : murs + bordure de board (bottom_row des colonnes impaires), trace de ligne hex,
    can_see = ratio > 0 (06.01 binaire, sans seuil).
    """
    from engine.hex_utils import compute_los_state

    effective_walls = _get_los_wall_hexes(wall_hexes)

    # Pas de `except Exception: return False` ici (CLAUDE.md : jamais de fallback masquant une
    # erreur). Un refus de LoS silencieux sur exception est indiscernable d'un vrai « ne voit
    # pas » : toute erreur doit remonter.
    _, can_see = compute_los_state(
        int(shooter_col),
        int(shooter_row),
        int(target_col),
        int(target_row),
        effective_walls,
    )
    return can_see


def is_adjacent(col1: int, row1: int, col2: int, row2: int) -> bool:
    """Check if two hexes are adjacent (distance == 1)."""
    return calculate_hex_distance(col1, row1, col2, row2) == 1


def parse_timestamp_to_seconds(line: str) -> Optional[int]:
    """
    Parse timestamp from log line format [HH:MM:SS] and convert to seconds.
    Returns None if timestamp cannot be parsed.
    """
    timestamp_match = re.match(r'\[(\d{2}):(\d{2}):(\d{2})\]', line)
    if timestamp_match:
        hours = int(timestamp_match.group(1))
        minutes = int(timestamp_match.group(2))
        seconds = int(timestamp_match.group(3))
        return hours * 3600 + minutes * 60 + seconds
    return None


def _analyzer_engagement_metric() -> str:
    """Métrique de l'EZ (`hex`|`euclidean`) pour le run ANALYSÉ.

    `engagement_distance_metric()` du moteur résout la même chose, mais sa bascule
    `geometry_is_hex()` relit le board du config COURANT : appelée depuis l'analyzer, elle
    répondrait pour le prochain run, pas pour celui qu'on relit. On reprend donc sa règle —
    « hex ssi inches_to_subhex <= 1 » — en la branchant sur l'échelle lue dans l'entête du log,
    et on délègue la clé de config elle-même, qui n'est pas propre au run.
    """
    from ai.analyzer_config import get_run_rule
    return get_run_rule("metric.engagement")


def _analyzer_engagement_zone_vertical() -> float:
    """Volet VERTICAL de la zone d'engagement (§03.04 : 2" horizontal ET 5" vertical), en POUCES.

    Même contrat que `_analyzer_engagement_metric` : la valeur vient de l'entête `Run rules:` du
    log, jamais du config courant — relire un vieux journal avec le seuil du jour rendrait des
    verdicts d'engagement faux en silence.

    Contrairement à `engagement_zone`, ce seuil n'est PAS mis à l'échelle : il se compare à des
    hauteurs de plancher, déjà en pouces (même contrat que
    `spatial_relations.get_engagement_zone_vertical`). Le multiplier par `inches_to_subhex`
    rendrait le gate inopérant (5 → 25" à x5).
    """
    from ai.analyzer_config import get_run_rule
    return float(get_run_rule("engagement_zone_vertical_inches"))


def _offenders_str(first_err: Dict[str, Any]) -> str:
    """Rend la liste des unités engageantes d'une première occurrence, ou une raison explicite.

    Une clé ABSENTE et une liste VIDE ne disent pas la même chose : la première signale un
    producteur qui n'a pas renseigné le diagnostic (défaut de câblage), la seconde un compteur
    qui a déclenché sans que la mesure ne retrouve d'ennemi (contradiction à investiguer). Les
    confondre en « none » est ce qui a rendu cette ligne inutilisable pendant tout un chantier.
    """
    if 'adjacent_after' not in first_err:
        return "<non renseigné par le compteur>"
    offenders = first_err['adjacent_after']
    if not offenders:
        return "<aucune — le compteur et la mesure se contredisent>"
    return ', '.join(f"Unit {uid}" for uid in offenders)


def engine_engagement_zone_offenders(
    unit_id: str,
    unit_player: Dict[str, int],
    unit_positions: Dict[str, Tuple[int, int]],
    unit_hp: Dict[str, int],
    engagement_zone: int,
    position_override: Optional[Tuple[int, int]] = None,
    positions_by_model: Optional[Dict[str, Dict[str, Tuple[int, int]]]] = None,
    unit_base: Optional[Dict[str, Any]] = None,
    subject_models: Optional[Dict[str, Tuple[int, int]]] = None,
    heights_by_model: Optional[Dict[str, Dict[str, float]]] = None,
    unit_model_height: Optional[Dict[str, float]] = None,
    subject_heights: Optional[Dict[str, float]] = None,
    exclude_unit_id: Optional[str] = None,
) -> List[str]:
    """QUELLES unités ennemies engagent ``unit_id`` — même mesure que le compteur, en nommé.

    Jumeau de ``is_within_engine_engagement_zone``, qui n'est que le prédicat booléen construit
    dessus : il n'y a donc qu'une seule implémentation de la mesure (même discipline que
    ``validate_move_plan`` / ``explain_move_plan_rejection`` côté moteur).

    ⚠️ POURQUOI CETTE FONCTION EXISTE. Le diagnostic de la section 1.1 nommait les coupables avec
    ``get_adjacent_enemies`` — une adjacence d'ANCRE à distance hex 1 — pendant que le compteur
    décidait avec la mesure par-figurine à ``engagement_zone``, dans la métrique du run. À ×5
    (``ez=10``), « distance d'ancre == 1 » n'est presque jamais vrai : le rapport imprimait donc
    « Adjacent after move: none » sous une erreur qui venait bien de se déclencher. Un diagnostic
    qui ne peut pas nommer le coupable oblige à re-mesurer à la main à chaque occurrence.

    Ordre : celui de ``unit_positions`` (ordre du journal), sans doublon — une unité engagée par
    plusieurs de ses socles n'est nommée qu'une fois.
    """
    return list(_iter_engaging_enemy_ids(
        unit_id, unit_player, unit_positions, unit_hp, engagement_zone,
        position_override, positions_by_model, unit_base, subject_models,
        heights_by_model, unit_model_height, subject_heights, exclude_unit_id,
    ))


def is_within_engine_engagement_zone(
    unit_id: str,
    unit_player: Dict[str, int],
    unit_positions: Dict[str, Tuple[int, int]],
    unit_hp: Dict[str, int],
    engagement_zone: int,
    position_override: Optional[Tuple[int, int]] = None,
    positions_by_model: Optional[Dict[str, Dict[str, Tuple[int, int]]]] = None,
    unit_base: Optional[Dict[str, Any]] = None,
    subject_models: Optional[Dict[str, Tuple[int, int]]] = None,
    heights_by_model: Optional[Dict[str, Dict[str, float]]] = None,
    unit_model_height: Optional[Dict[str, float]] = None,
    subject_heights: Optional[Dict[str, float]] = None,
    exclude_unit_id: Optional[str] = None,
) -> bool:
    """L'unité est-elle engagée ? Mesure PER-FIGURINE, empreinte contre empreinte (03.04).

    Une escouade n'est pas un point. Réduite à son ancre — ce que faisait ce contrôle — elle
    perdait ses autres socles : un bloc de 6 figurines n'était engagé que si SON ANCRE l'était.
    Faux à toute résolution, y compris x1 où l'ancre n'est qu'une figurine sur six ; à x5/x10 la
    taille de socle s'y ajoutait (tout le monde ramené à `round/1`).

    Le VERDICT reste rendu par la primitive canonique du moteur
    (`unit_within_engagement_zone_footprints`) : elle seule résout la métrique via
    `engagement_distance_metric()` et la bascule `geometry_is_hex`. Réécrire la boucle ici
    figerait l'analyzer en hex pendant que le moteur suivrait sa config — la divergence
    hex↔euclidien est précisément ce qui a fait supprimer le contrôle « Fight from non-adjacent »
    (cf. `ai/analyzer_phases/fight_handler.py`). Ce que ce module apporte, c'est l'EMPREINTE :
    `occupied_hexes` est peuplé depuis le log au lieu de l'ancre.

    Les empreintes viennent du segment `[MODELS:]` du log et des socles déclarés dans son entête
    (`base=`, déjà à l'échelle du board — le step logger l'omet quand il vaut 1, ce qui est
    précisément le cas x1). La résolution du run est donc portée par le log, pas déduite ici.

    - ``subject_models`` : socles du SUJET à l'instant évalué. C'est la forme exacte quand
      l'appelant dispose d'un `[MODELS:]` correspondant (destination d'un move, départ d'une
      charge). À privilégier sur ``position_override``.
    - ``position_override`` : ancre hypothétique du sujet, quand aucun socle n'est connu pour
      cet instant-là (mouvement réactif). Le sujet est alors mesuré comme un point — repli sur
      donnée absente, jamais un contrôle désarmé.
    - Les AUTRES unités sont toujours mesurées sur leurs socles connus, ancre sinon.
    - ``exclude_unit_id`` : une unité de plus retirée de l'ÉNUMÉRATION, en plus du sujet. Jumeau
      d'``entries_on_battlefield(exclude_id=…)`` côté moteur. Sert à demander « cette cible est-elle
      engagée par quelqu'un D'AUTRE que l'unité qui l'évalue ? » sans recopier tout
      ``unit_positions`` amputé d'une clé à chaque ligne de journal.

    ENGAGEMENT 3D (§03.04 : 2" horizontal ET **5" vertical**). ``heights_by_model`` (hauteurs de
    plancher par socle, lues dans le segment `[MODELS:]`), ``unit_model_height`` (MODEL_HEIGHT
    par unité, registry) et ``subject_heights`` (hauteurs du sujet à l'instant évalué, jumeau
    vertical de ``subject_models``) portent le gate. Le seuil vient de l'entête `Run rules:` du
    log, comme la zone horizontale et pour la même raison : le config s'édite entre deux runs.

    TOUT OU RIEN par paire : le gate n'est appliqué que si les DEUX entrées comparées portent
    leurs cartes verticales. ``_vertical_classes`` lève sur une entrée sans données, et une
    figurine laissée « au sol » par défaut rendrait un verdict FAUX là où l'absence de donnée
    doit rendre un verdict 2D — juste sur un plateau plat, et c'est le cas de tous les journaux
    antérieurs aux étages.
    """
    for _uid in _iter_engaging_enemy_ids(
        unit_id, unit_player, unit_positions, unit_hp, engagement_zone,
        position_override, positions_by_model, unit_base, subject_models,
        heights_by_model, unit_model_height, subject_heights, exclude_unit_id,
    ):
        return True
    return False


def _iter_engaging_enemy_ids(
    unit_id: str,
    unit_player: Dict[str, int],
    unit_positions: Dict[str, Tuple[int, int]],
    unit_hp: Dict[str, int],
    engagement_zone: int,
    position_override: Optional[Tuple[int, int]],
    positions_by_model: Optional[Dict[str, Dict[str, Tuple[int, int]]]],
    unit_base: Optional[Dict[str, Any]],
    subject_models: Optional[Dict[str, Tuple[int, int]]],
    heights_by_model: Optional[Dict[str, Dict[str, float]]],
    unit_model_height: Optional[Dict[str, float]],
    subject_heights: Optional[Dict[str, float]],
    exclude_unit_id: Optional[str],
) -> Iterator[str]:
    """MESURE UNIQUE de l'engagement côté analyzer — énumère les ennemis engageant le sujet.

    Générateur : le prédicat booléen s'arrête au premier (coût inchangé), le diagnostic les
    consomme tous. La sémantique est documentée sur ``is_within_engine_engagement_zone``, son
    lecteur principal — ne pas la dupliquer ici.
    """
    from engine.spatial_relations import unit_entries_within_engagement_zone
    from ai.analyzer_perfig import model_cache_entries

    subject_hp = _get_unit_hp_value(unit_hp, unit_id)
    if subject_hp is None or subject_hp <= 0 or unit_id not in unit_player:
        return
    models_by_unit = positions_by_model or {}
    bases = unit_base or {}
    subject_player = int(require_key(unit_player, unit_id))
    subject_anchor = position_override if position_override is not None else unit_positions.get(unit_id)  # get allowed
    heights_by_unit = heights_by_model or {}
    model_heights = unit_model_height or {}
    if subject_models is None and position_override is None:
        subject_models = models_by_unit.get(unit_id)  # get allowed
    if subject_heights is None:
        # Jumeau vertical du défaut de `subject_models` : les hauteurs d'AVANT la ligne, alignées
        # sur `positions_by_model`. La carte étant indexée PAR SOCLE, seuls les mids réellement
        # présents dans `subject_models` sont lus — un appelant qui mesure des socles d'ARRIVÉE
        # (`current_line_models`) doit donc passer les hauteurs correspondantes, sinon ses socles
        # n'ont pas d'altitude ici et il retombe en 2D plutôt que d'en inventer une.
        subject_heights = heights_by_unit.get(unit_id)  # get allowed
    # HORS TABLE (§03.04 / 20.01) : le journal déclare toutes les escouades dès l'entête, à la
    # sentinelle `(-1,-1)`, et `unit_positions` les garde tant qu'elles ne sont pas déployées.
    # `model_cache_entries` n'en produit AUCUNE entrée — liste vide = rien à mesurer.
    subject_entries = model_cache_entries(
        unit_id, subject_models, bases, subject_anchor, subject_player,
        heights=subject_heights, model_height=model_heights.get(unit_id),  # get allowed
    )
    if not subject_entries:
        return

    metric = _analyzer_engagement_metric()
    # Seuil vertical lu PARESSEUSEMENT, à la première paire qui porte réellement des altitudes :
    # un journal sans hauteurs n'a pas besoin de la règle, et l'exiger d'emblée rendrait
    # inanalysable tout journal antérieur à cette clé d'entête sans rien mesurer de plus.
    vertical_zone: Optional[float] = None
    for uid, anchor in unit_positions.items():
        if uid == unit_id or uid == exclude_unit_id or uid not in unit_player:
            continue
        enemy_player = int(require_key(unit_player, uid))
        if enemy_player == subject_player:
            continue
        hp_value = _get_unit_hp_value(unit_hp, uid)
        if hp_value is None or hp_value <= 0:
            continue
        # `_engaged` : une unité engagée par PLUSIEURS de ses socles n'est nommée qu'une fois, et
        # on sort de ses deux boucles imbriquées dès le premier socle qui touche — le prédicat
        # booléen garde ainsi exactement son coût d'avant (il s'arrête au premier `yield`).
        _engaged = False
        for enemy_entry in model_cache_entries(
            uid, models_by_unit.get(uid), bases, anchor, enemy_player,  # get allowed
            heights=heights_by_unit.get(uid),  # get allowed
            model_height=model_heights.get(uid),  # get allowed
        ):
            for subject_entry in subject_entries:
                # Gate vertical UNIQUEMENT si les deux entrées le portent (cf. docstring).
                _vz: Optional[float] = None
                if "MODEL_HEIGHT" in subject_entry and "MODEL_HEIGHT" in enemy_entry:
                    if vertical_zone is None:
                        vertical_zone = _analyzer_engagement_zone_vertical()
                    _vz = vertical_zone
                if unit_entries_within_engagement_zone(
                    subject_entry, enemy_entry, engagement_zone, metric=metric,
                    vertical_zone_inches=_vz,
                ):
                    _engaged = True
                    break
            if _engaged:
                break
        if _engaged:
            yield str(uid)


def _build_enemy_adjacent_hexes(
    unit_positions: Dict[str, Tuple[int, int]],
    unit_player: Dict[str, int],
    unit_hp: Dict[str, int],
    player: int
) -> Set[Tuple[int, int]]:
    """Build set of hexes adjacent to enemy units."""
    enemy_player = 3 - player
    enemy_player_int = int(enemy_player) if enemy_player is not None else None
    adjacent_hexes = set()
    for uid, pos in unit_positions.items():
        if uid not in unit_player or uid not in unit_hp:
            continue
        if require_key(unit_hp, uid) <= 0:
            continue
        unit_p = require_key(unit_player, uid)
        unit_p_int = int(unit_p) if unit_p is not None else None
        if unit_p_int != enemy_player_int:
            continue
        # Hors table : les voisins de la sentinelle `(-1,-1)` mettraient `(0,0)` et cinq autres
        # cases réelles dans la bande d'EZ bloquante du BFS (cf. `position_is_on_battlefield`).
        if not position_is_on_battlefield(pos):
            continue
        for neighbor in get_hex_neighbors(pos[0], pos[1]):
            adjacent_hexes.add(neighbor)
    return adjacent_hexes


def _move_rules_for_analyzer() -> Tuple[bool, bool, bool]:
    """Toggles de traversée `(EZ, ennemi, ami)` — lecteur MOTEUR (`_get_move_traversal_rules`),
    pas une relecture parallèle des trois clés. Un 4e toggle ou un renommage n'atteindrait
    qu'un côté sinon."""
    from ai.analyzer_config import get_run_rule

    def _flag(key: str) -> bool:
        # Lève plutôt que de deviner : `true`, `1` ou une faute de frappe deviendraient False
        # en silence, et un toggle de traversée lu à l'envers change tous les verdicts de chemin.
        raw = get_run_rule(key)
        if raw not in ("True", "False"):
            raise ValueError(f"Règle {key!r} de l'entête `Run rules:` illisible: {raw!r}")
        return raw == "True"

    return (_flag("move.thru_ez"), _flag("move.thru_enemy"), _flag("move.thru_friendly"))


def monster_or_vehicle_by_unit(config: Any, state: Any, mover_unit_id: str) -> Dict[str, bool]:
    """Carte `unit_id -> l'unité est-elle MONSTER/VEHICLE ?`, pour l'exemption 17.01 du BFS.

    Construite depuis le MÊME drapeau de registre que les exemptions de tir 10.06 / 17.03
    (`config.unit_is_monster_or_vehicle_by_type`) : un second calcul du keyword ici ferait
    diverger la nature d'une unité entre sa phase de tir et sa phase de mouvement.

    17.01 se lit par FIGURINE (« MONSTER/VEHICLE models in that unit ») ; cette carte le résout
    par ESCOUADE, ce qui n'est exact que tant qu'une escouade ne mélange pas des datasheets M/V
    et non-M/V. Aucune ne le peut aujourd'hui — le seul mélange possible vient de l'attachement
    19.01, réservé aux unités portant la règle `leader`, qu'aucune M/V du registre ne porte. Ce
    n'est pas une hypothèse laissée en l'air : la composition réelle du mobile est relue depuis
    `[MODEL_TYPES:]` et un mélange LÈVE, au lieu de rendre un verdict de chemin faux en silence.
    """
    by_type = config.unit_is_monster_or_vehicle_by_type
    mover_statuses = {
        bool(require_key(by_type, model_type))
        for mid, model_type in (
            (mid, state.model_types[mid])
            for mid in (state.positions_by_model.get(mover_unit_id) or {})  # get allowed
            if mid in state.model_types
        )
    }
    if len(mover_statuses) > 1:
        raise ValueError(
            f"Unité {mover_unit_id!r} : ses figurines mélangent des datasheets MONSTER/VEHICLE "
            "et non-MONSTER/VEHICLE. L'exemption de traversée 17.01 se lit par figurine ; la "
            "résolution par escouade de l'analyzer ne peut plus rendre un verdict de chemin."
        )
    return {uid: bool(require_key(by_type, ut)) for uid, ut in state.unit_types.items()}


def _build_move_bfs_blockers(
    positions_by_model: Dict[str, Dict[str, Tuple[int, int]]],
    unit_positions: Dict[str, Tuple[int, int]],
    unit_base: Dict[str, Any],
    unit_player: Dict[str, int],
    unit_hp: Dict[str, int],
    mover_unit_id: str,
    force_thru_enemy: bool = False,
    monster_or_vehicle_by_unit: Optional[Dict[str, bool]] = None,
) -> Tuple[Set[Tuple[int, int]], Set[Tuple[int, int]]]:
    """Obstacles du BFS de mouvement : (cases occupées bloquantes, bande d'EZ ennemie bloquante).

    DEUX corrections de fond par rapport au contrôle historique, toutes deux prouvées par la
    règle ET par la config que le moteur consomme (`game_config['move']`) :

    - 03.01 « It can be moved through friendly models. Its base cannot be moved through enemy
      models. » — l'analyzer bloquait sur TOUTES les figurines. Sur un déploiement serré, une
      escouade qui sort de son coin traversait forcément ses voisines : « path blocked » garanti,
      alors que le moteur l'autorise (`can_move_through_friendly_model: true`).
    - la bande d'engagement ennemie n'interdit que de TERMINER le mouvement, pas de la traverser
      (`can_move_through_enemy_engagement_zone: true`). L'inclure dans les obstacles du BFS
      revenait à interdire un pas que le moteur autorise.

    Les cases sont reconstruites SOCLE PAR SOCLE : l'ancre d'escouade ne représente qu'UNE case
    pour un bloc qui en occupe des dizaines, donc le BFS ancre-à-ancre déclarait libres les cases
    réellement tenues et bloquées les seules ancres. Sans donnée per-figurine pour une unité (log
    ancien / synthétique), repli sur son ancre — donnée absente, pas contrôle désarmé.

    `force_thru_enemy` — RÉSERVÉ AU FALL-BACK (09.07), et c'est une contrainte de DONNÉE, pas une
    complaisance. 09.07 « WHILE MOVING ▪ Desperate Escape: Each model that is moved can be moved
    through enemy models » : des DEUX modes de fall-back, un seul traverse les ennemis. Or le mode
    choisi n'est PAS journalisé (§7 L11 de `analyzer_couverture.md`) — un journal ne permet donc
    pas de trancher. Bloquer sur les ennemis rendrait « chemin impossible » sur toute retraite
    désespérée légale ; les laisser traversables ne perd que la retraite ORDONNÉE qui aurait
    traversé un ennemi. Le budget, lui, est commun aux deux modes et reste pleinement contrôlé.
    Le jour où `[MOVE_TYPE:fall_back]` portera son mode, ce paramètre doit disparaître.

    `monster_or_vehicle_by_unit` — 17.01, et il ne se passe QUE pour un mouvement normal ou un
    advance : « Each time you make a normal or advance move with a unit, MONSTER/VEHICLE models
    in that unit can be moved through friendly and enemy models (excluding other MONSTER/VEHICLE
    models). » Le fall-back (09.07, qui a sa propre Desperate Escape), la charge et le
    pile-in / consolidation n'y ont pas droit : leurs appelants ne passent donc pas cette carte,
    et l'omettre n'est pas un oubli mais la règle. Quand elle est fournie ET que le mobile est
    M/V, seules les AUTRES unités M/V bloquent encore le transit — les toggles de traversée
    gardent la main sur tout le reste, 17.01 n'étant qu'une permission de plus, jamais une
    interdiction (un M/V ami reste traversable si `move.thru_friendly`).
    """
    from ai.analyzer_perfig import _DEFAULT_BASE, squad_footprint
    thru_ez, thru_enemy, thru_friendly = _move_rules_for_analyzer()
    if force_thru_enemy:
        thru_enemy = True
    mover_player_int = int(require_key(unit_player, mover_unit_id))
    # Carte 17.01 du mobile, ou None si l'exemption ne s'applique pas (appelant qui ne la passe
    # pas — fall-back, charge, pile-in — ou mobile qui n'est pas M/V).
    mv_map: Optional[Dict[str, bool]] = None
    if monster_or_vehicle_by_unit is not None and require_key(monster_or_vehicle_by_unit, mover_unit_id):
        mv_map = monster_or_vehicle_by_unit
    occupied: Set[Tuple[int, int]] = set()
    for uid, anchor in unit_positions.items():
        if uid == mover_unit_id:
            continue
        hp_value = _get_unit_hp_value(unit_hp, uid)
        if hp_value is None or hp_value <= 0:
            continue
        if uid not in unit_player:
            continue
        # Hors table : une escouade en réserves n'occupe RIEN (20.01). Son empreinte, reconstruite
        # depuis la sentinelle `(-1,-1)`, déborde sur le coin réel du plateau — à x5 un socle de
        # 32 mm y couvre des dizaines d'hexes de `(0,0)` — et le BFS refuse alors des chemins
        # légaux. C'est la boucle VIVE avec la config par défaut (`thru_enemy: false`), la bande
        # d'EZ ci-dessous étant vide tant que `move.thru_ez` vaut True.
        if not position_is_on_battlefield(anchor):
            continue
        is_friendly = int(require_key(unit_player, uid)) == mover_player_int
        if is_friendly and thru_friendly:
            continue
        if not is_friendly and thru_enemy:
            continue
        # 17.01 : le mobile M/V traverse les figurines, SAUF celles des autres unités M/V.
        # `require_key` et non `.get` : une unité présente dans `unit_player` mais absente de
        # cette carte signalerait une carte construite sur un autre jeu d'unités que le journal —
        # la traiter en « pas M/V » rendrait un verdict de chemin faux sans le dire.
        if mv_map is not None and not require_key(mv_map, uid):
            continue
        models = positions_by_model.get(uid)  # get allowed
        if models:
            occupied |= squad_footprint(models, unit_base.get(uid, _DEFAULT_BASE))  # get allowed
        else:
            occupied.add(anchor)
    if thru_ez:
        ez_band: Set[Tuple[int, int]] = set()
    else:
        ez_band = _build_enemy_adjacent_hexes(unit_positions, unit_player, unit_hp, mover_player_int)
    return occupied, ez_band


def _bfs_shortest_path_length(
    start_col: int,
    start_row: int,
    dest_col: int,
    dest_row: int,
    max_steps: int,
    wall_hexes: Set[Tuple[int, int]],
    occupied_positions: Set[Tuple[int, int]],
    enemy_adjacent_hexes: Set[Tuple[int, int]],
) -> Optional[int]:
    """Longueur du plus court chemin de mouvement, ou None s'il n'en existe aucun dans le budget.

    UN SEUL verdict, et c'est délibéré : « trop long » et « bloqué » ne sont pas distinguables
    à un coût raisonnable. Les distinguer demandait d'explorer AU-DELÀ du budget, ce qui
    quadruplait le flood sur les chemins en échec (mesuré : 1,6 → 6,3 ms par socle pour une
    charge à x5) sans même offrir de garantie — un détour peut dépasser n'importe quelle marge
    fixée d'avance. Les compteurs séparés qui vivaient chez les appelants entretenaient donc une
    fiction : celui qui affichait « distance > budget » restait à 0 en permanence, tout partant
    dans « chemin bloqué ». Ce que le contrôle établit vraiment, et tout ce qu'il établit :
    **la figurine n'a pas pu atteindre sa destination dans son budget**.
    """
    from ai.analyzer_config import get_run_board_dims

    board_cols, board_rows = get_run_board_dims()
    start_pos = (start_col, start_row)
    dest_pos = (dest_col, dest_row)
    if start_pos == dest_pos:
        return 0
    visited = {start_pos: 0}
    queue: List[Tuple[int, int]] = [start_pos]
    while queue:
        current_pos = queue.pop(0)
        current_dist = visited[current_pos]
        if current_dist >= max_steps:
            continue
        for neighbor in get_hex_neighbors(current_pos[0], current_pos[1]):
            if neighbor in visited:
                continue
            # 03.01 « Its base cannot cross the edge of the battlefield » — le bord bornait le
            # champ géodésique du MOTEUR (`geodesic_move_reach`) sans borner celui de l'analyzer,
            # qui acceptait donc un chemin passant hors plateau : un socle coincé dans un coin
            # trouvait toujours un contournement par l'extérieur, et le contrôle de budget se
            # taisait sur le seul chemin que le jeu interdit.
            #
            # TRANSIT, comme le reste de cette boucle : c'est le CENTRE du socle qui est borné
            # ici, exactement comme côté moteur. Qu'un socle DÉBORDE du plateau à l'arrivée
            # relève du placement (`is_footprint_placement_valid`), donc du contrôle de position
            # §2.2, pas de l'atteignabilité.
            if not (0 <= neighbor[0] < board_cols and 0 <= neighbor[1] < board_rows):
                continue
            if neighbor in wall_hexes:
                continue
            # TRANSIT ≠ PLACEMENT. Le moteur sépare les deux (`build_move_transit_blocked` d'un
            # côté, `is_footprint_placement_valid` de l'autre) ; cette boucle les confondait, et
            # refusait la case d'ARRIVÉE dès qu'elle était occupée — avant même de tester si
            # c'était la destination. Une destination occupée devenait donc injoignable à
            # N'IMPORTE QUEL budget, et le contrôle rendait « au-delà du budget » là où le vrai
            # fait est « chevauchement ». Mesuré sur le run du 2026-08-08 : 8 charges sur 8
            # remontées à ce titre avaient un chemin égal à la distance à vol d'oiseau, tous
            # budgets respectés — la case d'arrivée était simplement celle d'une figurine ennemie.
            # Le chevauchement reste une faute : il est mesuré par le contrôle de collision
            # (2.2), à sa place, avec son propre nom.
            if neighbor != dest_pos and neighbor in occupied_positions:
                continue
            # Bande d'engagement ennemie : l'appelant la fournit VIDE quand la config autorise
            # à la traverser (`can_move_through_enemy_engagement_zone`, lu par
            # `_build_move_bfs_blockers`). Le paramètre était accepté et transmis par les cinq
            # sites, mais la boucle ne le lisait pas : basculer ce toggle n'aurait rien changé.
            if neighbor != dest_pos and neighbor in enemy_adjacent_hexes:
                continue
            next_dist = current_dist + 1
            if neighbor == dest_pos:
                return next_dist
            visited[neighbor] = next_dist
            queue.append(neighbor)
    return None


def _per_model_move_violation(
    prev_models: Optional[Dict[str, Tuple[int, int]]],
    new_models: Optional[Dict[str, Tuple[int, int]]],
    anchor_from: Tuple[int, int],
    anchor_to: Tuple[int, int],
    budget: int,
    is_fly: bool,
    wall_hexes: Set[Tuple[int, int]],
    occupied_positions: Set[Tuple[int, int]],
    enemy_adjacent_hexes: Set[Tuple[int, int]],
) -> bool:
    """Une figurine a-t-elle été déplacée AU-DELÀ de ce que son budget permettait ?

    Contrôle commun aux QUATRE déplacements contrôlés — move, advance, charge, pile-in /
    consolidation. Il était écrit quatre fois, et les quatre copies avaient déjà divergé : le
    filtre des socles morts n'existait que dans deux d'entre elles, la distinction
    bloqué/hors-budget dans deux autres. Une règle de déplacement corrigée devait atterrir en
    quatre endroits ; elle n'y atterrissait jamais complètement.

    Ce que l'appelant fournit : les socles d'AVANT (déjà réduits aux survivants), ceux de la
    ligne, le budget DÉJÀ converti en cases, et le drapeau de vol déclaré. Ce que ce helper ne
    fait pas : écrire dans `stats` — les quatre appelants ont des compteurs de formes
    différentes, et c'est leur seule divergence légitime.

    - Chaque socle commun qui a bougé est mesuré de SA position de départ à SA destination :
      l'ancre d'escouade peut bondir plus loin qu'aucune figurine (reformation) ou moins loin
      que l'une d'elles.
    - Vol déclaré (21.03) : distance à vol d'oiseau, la traversée étant la contrepartie des 2"
      retranchés au budget. Sinon : chemin réel, murs et figurines ennemies compris (03.01).
    - Sans donnée per-figurine des deux côtés : repli sur l'ancre, seule donnée disponible —
      et par le MÊME chemin, pour ne pas rendre le verdict dépendant de la présence du segment.
    """
    if prev_models and new_models:
        moved = [
            (mid, pos) for mid, pos in prev_models.items()
            if mid in new_models and new_models[mid] != pos
        ]
    else:
        moved = [("<ancre>", anchor_from)] if anchor_from != anchor_to else []
        new_models = {"<ancre>": anchor_to}

    for mid, (o_col, o_row) in moved:
        d_col, d_row = new_models[mid]
        if is_fly:
            if calculate_hex_distance(o_col, o_row, d_col, d_row) > budget:
                return True
        elif _bfs_shortest_path_length(
            o_col, o_row, d_col, d_row, budget,
            wall_hexes, occupied_positions, enemy_adjacent_hexes,
        ) is None:
            return True
    return False


def _render_rule_coverage(stats: Dict[str, Any], section: str, log_print: Any) -> None:
    """Couverture des RÈGLES de la section : applicable ? exercée ? combien d'erreurs ?

    Cette table répond à la question que les compteurs d'erreur ne posent pas. Un compteur à 0 ne
    dit pas s'il n'a rien trouvé ou s'il n'a rien regardé, et il ne dit RIEN d'une règle que le
    moteur n'applique pas — celle-là ne produit aucune ligne fautive. `JAMAIS EXERCÉE` est le
    verdict qui manquait : la situation s'est présentée, le contrôle n'a jamais eu à juger.

    L'écart entre la somme par règle et le total de la section est imprimé s'il existe : il
    signifie qu'un compteur d'erreur n'appartient à aucune règle du corpus, donc qu'une faute
    peut apparaître dans le total sans qu'aucune règle ne la porte.
    """
    rows = coverage_rows(stats, section)
    if not rows:
        return
    log_print("-" * 80)
    log_print(f"{section} COUVERTURE DES REGLES")
    log_print("-" * 80)
    log_print(f"{'Regle':<44} {'Exercices':>10} {'Erreurs':>9} {'Statut':>9}   Verdict")
    for row in rows:
        # « - » et non « 0 » pour une regle hors roster : un zero se lit comme « jamais exercee »,
        # alors que la regle ne POUVAIT pas l'etre. Les deux ne demandent pas le meme geste.
        _exercises = "-" if row["verdict"] == "HORS ROSTER" else str(row["exercised"])
        _name = f"{row['id']} {row['label']}"
        log_print(
            f"{_name[:44]:<44} {_exercises:>10} "
            f"{row['errors']:>9} {row['status']:>9}   {row['verdict']}"
        )
    _never = [r for r in rows if r["verdict"] == "JAMAIS EXERCÉE"]
    if _never:
        log_print(
            "  ⚠️  Applicable(s) et jamais exercee(s) — la situation s'est presentee et aucun "
            f"controle n'a rien juge : {', '.join(r['id'] for r in _never)}"
        )
    for _section, _by_rule, _bucket in coverage_gaps(stats, section):
        log_print(
            f"  ❌ Somme par regle ({_by_rule}) != total de la section ({_bucket}) : un compteur "
            "d'erreur n'est porte par aucune regle du corpus."
        )


def error_totals(stats: Dict[str, Any]) -> Dict[str, int]:
    """Totaux d'erreurs par section — LE calcul, appelé par le SUMMARY et par le total de la CLI.

    Il existait en DEUX exemplaires, et ils avaient divergé en silence : le total de la CLI
    ignorait `move_after_shooting_distance_over_limit` (§1.1) et `shoot_combi_profile_conflicts`
    (§1.2). Effet observable : un run pouvait afficher « ❌ 1.1 Erreurs en phase de move : 3 » et
    rendre un total d'erreurs qui n'en comptait aucune — le rapport se contredisait lui-même, et
    c'est le total, plus court, qu'on lit en premier.

    ⚠️ UN NOUVEAU COMPTEUR D'ERREUR S'AJOUTE ICI, ET NULLE PART AILLEURS. C'est la seule raison
    d'être de cette fonction : tant que la somme vivait chez ses deux appelants, chaque compteur
    ajouté avait une chance sur deux de n'atterrir que d'un côté. Trois l'ont vécu.

    Ne fait AUCUN affichage et ne lit rien d'autre que `stats` : les deux appelants en tirent des
    lignes de rapport très différentes, c'est leur seule divergence légitime.
    """
    def _pair(*path: Any) -> int:
        """Somme P1 + P2 d'un compteur, quel que soit son niveau d'imbrication."""
        node: Mapping[Any, Any] = stats
        for key in path:
            node = require_key(node, key)
        return require_key(node, 1) + require_key(node, 2)

    shoot_invalid = sum(
        require_key(require_key(stats['shoot_invalid'], player), field)
        for player in (1, 2)
        for field in ('out_of_range', 'engaged_non_close_quarters')
    )
    buckets = {
        # §1.1 — les six déplacements de la phase de Mouvement, plus le move réactif.
        'move': (
            _pair('wall_collisions')
            + _pair('move_to_adjacent_enemy')
            + _pair('move_adjacent_before_non_flee')
            + _pair('move_distance_over_limit', 'move')
            + _pair('move_after_shooting_distance_over_limit')
            # 09.07 : le fall-back est un type de mouvement de la phase de Mouvement (09.02),
            # ses infractions entrent donc dans le total MOVE, pas dans un total à part.
            + _pair('move_distance_over_limit', 'flee')
            + _pair('flee_from_unengaged')
            + _pair('flee_still_engaged')
            + stats['reactive_move_stats'][1]['abnormal'] + stats['reactive_move_stats'][2]['abnormal']
            + _pair('reactive_move_checks', 'to_adjacent_enemy')
            + _pair('reactive_move_checks', 'into_wall')
            + _pair('reactive_move_checks', 'distance_over_roll')
            # 03.03 : la cohérence se juge à la fin de TOUT déplacement, y compris le pile-in et
            # la consolidation. Elle est comptée ici, avec les déplacements, plutôt qu'éclatée
            # entre §1.1 et §1.4 — c'est une règle de MOUVEMENT, une seule mesure, un seul total.
            + _pair('squad_coherency_violations')
        ),
        # §1.2 — l'advance est une action de la phase de Mouvement mais ses fautes sont comptées
        # ici, avec le tir, parce que c'est là que le rapport les affiche.
        'shooting': (
            # Clé RETIRÉE de ce total, pas seulement remise à zéro : `shoot_not_allocated_target_alive`
            # le 2026-08-12 (avec son jumeau de mêlée, plus bas). Un terme mort dans un total n'est
            # pas neutre — il entretient l'idée qu'une règle est surveillée. Motif du retrait et
            # chiffres : `analyzer_couverture.md`, table « Contrôles SUPPRIMÉS ».
            _pair('shoot_over_rng_nb')
            + _pair('shoot_combi_profile_conflicts')
            + _pair('shoot_after_flee')
            + _pair('shoot_at_friendly')
            + _pair('shoot_at_engaged_enemy')
            + _pair('close_quarters_shot_at_unengaged_target')
            + _pair('advance_after_shoot')
            + _pair('advance_twice_in_shoot_phase')
            + _pair('move_distance_over_limit', 'advance')
            + _pair('advance_from_adjacent')
            + _pair('shoot_hit_result_mismatch')
            + _pair('indirect_fire_mismatch')
            + _pair('shoot_wound_threshold_mismatch')
            + shoot_invalid
        ),
        'charge': (
            _pair('charge_from_adjacent')
            + stats['charge_invalid'][1]['distance_over_roll'] + stats['charge_invalid'][2]['distance_over_roll']
            + stats['charge_invalid'][1]['advanced'] + stats['charge_invalid'][2]['advanced']
            + stats['charge_invalid'][1]['fled'] + stats['charge_invalid'][2]['fled']
        ),
        'fight': (
            # Deux clés RETIRÉES de ce total, pas seulement remises à zéro — un terme mort dans un
            # total n'est pas neutre, il entretient l'idée qu'une règle est surveillée :
            #   - `fight_from_non_adjacent` le 2026-08-10 (vert vacant V2 ; contrôle retiré comme
            #     faux positif le 2026-07-24). 12.01 est vérifiée par `test_fight_spatial_contract.py` ;
            #   - `fight_not_allocated_target_alive` le 2026-08-12, avec son jumeau de tir. 05 est
            #     vérifiée par `tests/unit/engine/test_attack_allocation_contract.py`.
            # Motifs et chiffres : `analyzer_couverture.md`, table « Contrôles SUPPRIMÉS ».
            _pair('fight_friendly')
            + _pair('fight_over_cc_nb')
            + _pair('fight_move_invalid', 'pile_in')
            + _pair('fight_move_invalid', 'consolidation')
            + _pair('fight_hit_result_mismatch')
            + _pair('fight_wound_threshold_mismatch')
            + _pair('fight_alternation_violations')
            + _pair('fight_double_pile_in')
        ),
        'dead_units': (
            _pair('dead_unit_moving')
            + _pair('shoot_dead_unit')
            + _pair('shoot_at_dead_unit')
            + _pair('dead_unit_advancing')
            + _pair('dead_unit_charging')
            + _pair('charge_dead_unit')
            + _pair('fight_dead_unit_attacker')
            + _pair('fight_dead_unit_target')
            + _pair('dead_unit_waiting')
            # `dead_unit_skipping` a disparu de ce total le 2026-08-10 (vert vacant V3) : le
            # moteur ne journalise AUCUNE ligne `SKIP` — `_STEP_LOG_TYPE_MAP` est une liste
            # blanche et n'y porte pas `skip` (`w40k_core.py`, « type sans formateur ->
            # volontairement non journalisé »). Le compteur était inatteignable, et son 0
            # permanent comptait pour un ✅ dans « 2.1 Dead units interactions ».
            + _pair('unit_revived')
        ),
        'positions': (
            stats['position_log_mismatch']['move']['mismatch']
            + stats['position_log_mismatch']['advance']['mismatch']
            + stats['position_log_mismatch']['charge']['mismatch']
            + len(stats['unit_position_collisions'])
        ),
        # §2.3 — même motif que les buckets ci-dessus : cette somme vivait elle aussi en deux
        # exemplaires. Ils ne divergeaient pas encore ; c'est la structure qui les y menait.
        'damage': _pair('damage_missing_unit_hp') + _pair('damage_exceeds_hp'),
        # ── §1.5 à §2.7 : les buckets qui manquaient au TOTAL alors que le SUMMARY les
        # affichait en ❌. Sans eux, un run pouvait imprimer « ❌ 1.6 Double-activation par
        # phase : 1 » PUIS « ✅ 0 erreur détectée » — deux verdicts contradictoires dans le même
        # rapport, et c'est le second qu'on lit. Ils sont ici pour la même raison que les autres.
        'wrong_phase': sum(
            require_key(entry, 'wrong') for entry in require_key(stats, 'action_phase_accuracy').values()
        ),
        'double_activation': (
            sum(require_key(stats, 'double_activation_by_phase').values())
            + require_key(stats, 'double_activation_reactive_move')
        ),
        # §1.7 / §1.8 — « invalide » = une paire observée que le registre ne déclare pas.
        'special_rules_invalid': sum(
            1 for (rule_id, unit_type) in require_key(stats, 'special_rule_usage')
            if rule_id not in stats['rule_to_units'] or unit_type not in stats['rule_to_units'][rule_id]
        ),
        'weapon_rules_invalid': sum(
            1 for (rule_name, weapon_key) in require_key(stats, 'weapon_rule_usage')
            if rule_name not in stats['weapon_rule_to_weapons']
            or weapon_key not in stats['weapon_rule_to_weapons'][rule_name]
        ),
        'episodes_ending': len(stats['episodes_without_end']) + len(stats['episodes_without_method']),
        'core_issues': len(stats['parse_errors']) + len(stats['unit_id_mismatches']),
        'missing_samples': sum(1 for line in stats['sample_actions'].values() if not line),
        # §2.8 — une divergence état-reconstruit/état-moteur invalide, pour l'épisode concerné,
        # tout contrôle de distance ou d'adjacence. Elle est rendue au même rang que les autres.
        'state_resync': sum(require_key(stats, 'state_resync').values()),
    }
    # LE total, et donc LA définition de « une erreur » — plus une recomposition à la main chez
    # l'appelant. C'est la somme de TOUS les buckets ci-dessus, sans exception ni terme
    # supplémentaire : toute ligne ❌ du SUMMARY y entre par construction, et un bucket neuf y
    # entre sans qu'on ait à y penser. C'est précisément ce qui manquait à §1.6 et §1.7.
    buckets['total'] = sum(buckets.values())
    return buckets


def _track_action_phase_accuracy(
    stats: Dict[str, Any],
    action_type: str,
    phase: str,
    current_episode_num: int,
    line_text: str
) -> None:
    """Track action/phase alignment accuracy."""
    # Phase attendue par type d'action — encode les PDF du projet (Documentation/40k_rules/),
    # jamais le comportement du code.
    # V11 T6 : "advance" etait attendu en SHOOT — FAUX. Regle 09.02 (« 09 Movement phase.pdf »),
    # etape MOVE UNITS > « Select Move Type » : l'Advance move est un TYPE DE MOUVEMENT de la
    # phase de Mouvement, au meme titre que Normal move, Fall-back move et Remain stationary.
    # Le moteur le resout bien en phase MOVE (`squad_advance` -> branche move de
    # _process_squad_action) : l'attente SHOOT produisait un faux positif sur CHAQUE advance.
    expected_phase_by_action = {
        "move": "MOVE",
        "move_after_shooting": "SHOOT",
        "fled": "MOVE",
        "shoot": "SHOOT",
        "advance": "MOVE",
        "charge": "CHARGE",
        "fight": "FIGHT"
    }
    if action_type not in expected_phase_by_action:
        return
    expected_phase = expected_phase_by_action[action_type]
    action_phase_accuracy = require_key(stats, "action_phase_accuracy")
    if action_type not in action_phase_accuracy:
        action_phase_accuracy[action_type] = {"total": 0, "wrong": 0}
    action_phase_accuracy[action_type]["total"] += 1
    if phase != expected_phase:
        action_phase_accuracy[action_type]["wrong"] += 1
        first_errors = require_key(stats, "first_error_lines")
        action_mismatch = require_key(first_errors, "action_phase_mismatch")
        if action_mismatch.get(action_type) is None:
            action_mismatch[action_type] = {
                "episode": current_episode_num,
                "line": line_text.strip()
            }


def get_adjacent_enemies(col: int, row: int, unit_player: Dict[str, int], unit_positions: Dict[str, Tuple[int, int]], 
                         unit_hp: Dict[str, int], unit_types: Dict[str, str], player: int) -> List[str]:
    """Get list of enemy unit IDs adjacent to a hex position."""
    enemy_player = 3 - player
    # CRITICAL: Normalize player values to int for consistent comparison (handles int/string mismatches)
    enemy_player_int = int(enemy_player) if enemy_player is not None else None
    adjacent_enemies = []
    # DEBUG: Log all enemy positions being checked for adjacency
    enemy_positions_debug = []
    # CRITICAL FIX: Iterate over unit_positions instead of unit_player to avoid checking dead units
    # Dead units are removed from unit_positions when they die, so this ensures we only check living units
    for uid, enemy_pos in unit_positions.items():
        # Hors table : la sentinelle `(-1,-1)` est adjacente à `(0,0)`, donc une escouade en
        # réserves ressortait « ennemi adjacent » et se retrouvait NOMMÉE dans les lignes d'erreur
        # et les traces de charge/advance (cf. `position_is_on_battlefield`).
        if not position_is_on_battlefield(enemy_pos):
            continue
        # Verify this is an enemy unit
        p = require_key(unit_player, uid)
        # CRITICAL: Normalize player value to int for consistent comparison (handles int/string mismatches)
        p_int = int(p) if p is not None else None
        if p_int == enemy_player_int:
            hp_value = _get_unit_hp_value(unit_hp, uid)
            if hp_value is None:
                continue
            # DEBUG: Collect all enemy positions for logging
            enemy_positions_debug.append(f"Unit {uid} (player {p}, HP={hp_value}) at {enemy_pos}")
            if hp_value > 0:
                if is_adjacent(col, row, enemy_pos[0], enemy_pos[1]):
                    adjacent_enemies.append(uid)
    # DEBUG: Log enemy positions when checking adjacency (general, not specific to any unit)
    if enemy_positions_debug:
        _debug_log(f"[ANALYZER DEBUG] get_adjacent_enemies: Checking position ({col},{row}) against {len(enemy_positions_debug)} enemy units: {', '.join(enemy_positions_debug)}")
    return adjacent_enemies


def _position_cache_set(
    cache: Dict[str, Tuple[int, int]], unit_id: str, col: int, row: int
) -> None:
    """
    Set unit position in the position cache (single source of truth).
    Call on every event that establishes or changes a unit's position:
    UNIT (init), MOVE, FLED, ADVANCE, CHARGE, SHOT (shooter + target when coords in log), FIGHT (target).
    """
    cache[unit_id] = (int(col), int(row))


def _position_cache_remove(cache: Dict[str, Tuple[int, int]], unit_id: str) -> None:
    """
    Remove unit from the position cache (e.g. on death).
    Call on every unit death so the cache never holds obsolete positions.
    """
    if unit_id in cache:
        del cache[unit_id]


def parse_step_log(filepath: str) -> Dict:
    """Parse step.log and extract statistics with rule validation."""
    
    # Open debug log file
    global _debug_log_file
    debug_log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'analyzer_debug.log')
    _debug_log_file = open(debug_log_path, 'w', encoding='utf-8')
    _debug_log(f"=== ANALYZER DEBUG LOG ===")
    _debug_log(f"Analyzing {filepath}")
    _debug_log("=" * 80)
    
    # Échelle du run AVANT toute construction de config : portées d'armes, budgets de move et
    # seuil d'engagement en dérivent tous (cf. parse_board_scale_from_log).
    set_analyzer_board_scale(parse_board_scale_from_log(filepath))
    # Bord du plateau (03.01) : même entête, même passe, même exigence que l'échelle.
    set_analyzer_board_dims(*parse_board_dims_from_log(filepath))
    from ai.analyzer_config import set_run_rules
    set_run_rules(parse_run_rules_from_log(filepath))

    # Load unit weapons and rule caches
    from ai.analyzer_config import load_analyzer_config
    _cfg = load_analyzer_config()
    unit_registry = _cfg.unit_registry
    config_loader = _cfg.config_loader
    unit_weapons_cache = _cfg.unit_weapons_cache
    unit_attack_limits = _cfg.unit_attack_limits
    unit_combi_by_weapon = _cfg.unit_combi_by_weapon
    unit_rules_by_type = _cfg.unit_rules_by_type
    unit_move_after_shooting_distance_by_type = _cfg.unit_move_after_shooting_distance_by_type
    unit_is_fly_by_type = _cfg.unit_is_fly_by_type
    unit_choice_effect_to_source_rules = _cfg.unit_choice_effect_to_source_rules
    display_rule_name_to_ids = _cfg.display_rule_name_to_ids
    rule_to_units = _cfg.rule_to_units
    weapon_rule_to_weapons = _cfg.weapon_rule_to_weapons
    resolve_effect_rule_id_to_technical = _cfg.resolve_rule_id

    # Statistics structure
    stats = {
        'rule_to_units': rule_to_units,  # rule_id -> set of unit_types (for validity)
        'weapon_rule_to_weapons': weapon_rule_to_weapons,  # rule -> set of "weapon (unit)"
        'weapon_rule_usage': defaultdict(lambda: {1: 0, 2: 0}),  # (rule, weapon_key) -> {1,2}
        # NB : il n'existe plus de compteur d'usage INVALIDE. Le seul qui ait jamais existe
        # servait [HEAVY], et re-derivait sa validite depuis units_moved — un critere que le
        # moteur n'utilise plus depuis le 2026-07-26 et qui n'est pas reconstructible depuis
        # step.log. Retire le 2026-07-29 (V11 §0hist.38) ; la conformite de [HEAVY] est portee
        # par tests/unit/engine/test_heavy_shoot.py.
        'total_episodes': 0,
        'total_actions': 0,
        'episode_lengths': [],
        'turns_distribution': Counter(),
        'actions_by_type': Counter(),
        'actions_by_phase': Counter(),
        'actions_by_player': {1: Counter(), 2: Counter()},
        'win_methods': {
            1: {'elimination': 0, 'objectives': 0, 'value_tiebreaker': 0},
            2: {'elimination': 0, 'objectives': 0, 'value_tiebreaker': 0},
            -1: {'draw': 0}
        },
        'wins_by_scenario': defaultdict(lambda: {'p1': 0, 'p2': 0, 'draws': 0, 'agent': 0, 'bot': 0}),
        'victory_points_by_episode': {},
        'victory_points_values': {1: [], 2: []},
        # ── Résultats rapportés au SIÈGE de l'agent, pas au numéro de joueur ────────────────
        # `controlled_player_mode` (ai/train.py) accepte `p1`, `p2` et `random` : l'agent ne
        # tient pas toujours le siège P1. Les compteurs `[1]/[2]` ci-dessus restent des
        # compteurs de SIÈGE (ils servent aux sections d'erreurs, où seul le siège a un sens) ;
        # ceux-ci suivent l'AGENT d'un épisode à l'autre. Mesuré sur un run de 600 épisodes :
        # agent en P2 dans 180 d'entre eux, 33,3 % de victoires affichées pour 45,3 % réelles.
        'win_methods_by_seat': {
            'agent': {'elimination': 0, 'objectives': 0, 'value_tiebreaker': 0},
            'bot': {'elimination': 0, 'objectives': 0, 'value_tiebreaker': 0},
        },
        'victory_points_values_by_seat': {'agent': [], 'bot': []},
        'agent_seat_counts': {1: 0, 2: 0},
        # Écarts entre l'état RECONSTRUIT par l'analyzer et l'instantané `T{tour} STATE:` du
        # moteur. Ce compteur est le point du chantier : il transforme une dérive silencieuse en
        # erreur mesurée, et se déclenchera le jour où un nouvel effet cessera d'être journalisé.
        # `alloc_model_unknown` : le moteur a nommé une figurine allouée que l'état reconstruit
        # ne connaît pas. Même famille que les trois autres — l'analyzer et le moteur ne
        # décrivent plus la même partie — et compté au même endroit pour la même raison.
        'state_resync': {'dead_missed': 0, 'alive_missed': 0, 'pos_mismatch': 0,
                         'alloc_model_unknown': 0},
        # ⚠️ Le compartiment `skip` N'EST PAS alimenté par une ligne `SKIP` du journal — il n'en
        # existe aucune (cf. V3). Son producteur est `handle_wait` : 10.04 rend une unité ENGAGÉE
        # inéligible au tir normal, donc son WAIT n'est pas un choix mais un skip imposé par la
        # règle. Retirer ce compartiment avec le reste du chantier `skip` aurait détruit cette
        # mesure-là, qui est vivante.
        'shoot_vs_wait': {
            'shoot': 0, 'wait': 0, 'skip': 0, 'advance': 0
        },
        'shoot_vs_wait_by_player': {
            1: {'shoot': 0, 'wait': 0, 'wait_with_targets': 0, 'wait_no_targets': 0, 'skip': 0, 'advance': 0},
            2: {'shoot': 0, 'wait': 0, 'wait_with_targets': 0, 'wait_no_targets': 0, 'skip': 0, 'advance': 0}
        },
        'shots_after_advance': {1: 0, 2: 0},
        'close_quarters_shots': {
            1: {'engaged_target': 0, 'unengaged_target': 0},
            2: {'engaged_target': 0, 'unengaged_target': 0}
        },
        'engaged_shot_with_non_close_quarters_weapon': {1: 0, 2: 0},
        'wait_by_phase': {
            1: {'move_wait': 0, 'wait_with_los': 0, 'wait_no_los': 0},
            2: {'move_wait': 0, 'wait_with_los': 0, 'wait_no_los': 0}
        },
        'target_priority': {
            1: {'shots_at_wounded_in_los': 0, 'shots_at_full_hp_while_wounded_in_los': 0, 'total_shots': 0},
            2: {'shots_at_wounded_in_los': 0, 'shots_at_full_hp_while_wounded_in_los': 0, 'total_shots': 0}
        },
        'death_orders': [],
        'current_episode_deaths': [],
        'unit_types': {},
        'unit_types_seen': set(),
        'wounded_enemies': {1: set(), 2: set()},
        # Rule violations
        'wall_collisions': {1: 0, 2: 0},
        'move_to_adjacent_enemy': {1: 0, 2: 0},
        # Seuil de blessure 05.02 (cf. ai/analyzer_wound.py). `_unverifiable` compte les lignes
        # que le contrôle a refusé de juger faute de donnée : sans lui, un compteur à zéro ne
        # distingue pas « rien à signaler » de « plus rien de regardé ».
        # 05.01 HIT ROLLS — jumeau du seuil de blessure ci-dessous. `*_checked` compte les
        # lignes RÉELLEMENT jugées : sans lui, un `_mismatch` à 0 ne distingue pas « aucune
        # faute » de « le contrôle ne regarde plus rien » (cf. ai/analyzer_hit.py).
        'shoot_hit_result_mismatch': {1: 0, 2: 0},
        'shoot_hit_result_checked': {1: 0, 2: 0},
        # 10.07 tir indirect : [COVER] obligatoire + seuil effectif >= plancher déclaré.
        'indirect_fire_checked': {1: 0, 2: 0},
        'indirect_fire_mismatch': {1: 0, 2: 0},
        'fight_hit_result_mismatch': {1: 0, 2: 0},
        'fight_hit_result_checked': {1: 0, 2: 0},
        'shoot_wound_threshold_mismatch': {1: 0, 2: 0},
        'shoot_wound_threshold_unverifiable': {1: 0, 2: 0},
        'fight_wound_threshold_mismatch': {1: 0, 2: 0},
        'fight_wound_threshold_unverifiable': {1: 0, 2: 0},
        'dead_unit_moving': {1: 0, 2: 0},
        'charge_from_adjacent': {1: 0, 2: 0},
        'advance_from_adjacent': {1: 0, 2: 0},
        'dead_unit_advancing': {1: 0, 2: 0},
        'shoot_after_flee': {1: 0, 2: 0},
        'move_after_shooting': {1: 0, 2: 0},
        'move_after_shooting_distance_over_limit': {1: 0, 2: 0},
        'shoot_at_friendly': {1: 0, 2: 0},
        'shoot_at_engaged_enemy': {1: 0, 2: 0},
        'close_quarters_shot_at_unengaged_target': {1: 0, 2: 0},
        'shoot_dead_unit': {1: 0, 2: 0},
        'shoot_at_dead_unit': {1: 0, 2: 0},
        'shoot_over_rng_nb': {1: 0, 2: 0},
        'shoot_combi_profile_conflicts': {1: 0, 2: 0},
        'devastating_wounds_correct': {1: 0, 2: 0},
        'devastating_wounds_incorrect': {1: 0, 2: 0},
        # 03.03 : cohérence d'escouade à la fin de chaque déplacement et à la mise en place.
        'squad_coherency_violations': {1: 0, 2: 0},
        # Tirs dont la PORTÉE n'a pas pu être jugée (aucun socle connu pour la cible). Ce n'est
        # pas une faute — c'est une absence de mesure — mais elle doit être VISIBLE : sans ce
        # compteur, « 0 tir hors portée » ne distingue pas un contrôle qui n'a rien trouvé d'un
        # contrôle qui n'a rien regardé (résidu V9 d'`analyzer_couverture.md`).
        'shoot_range_unverifiable': {1: 0, 2: 0},
        # 03.03 End of Turn — figurines RETIRÉES faute de cohérence. Compteur d'EXERCICE, pas
        # d'erreur : le moteur applique la règle, il ne la viole pas. Il vit à côté des violations
        # parce qu'il en est la conséquence directe — une escouade qui finit son déplacement hors
        # cohérence perd des figurines à la fin du tour.
        'coherency_removals': {1: 0, 2: 0},
        # 20.04 — escouades entières détruites faute d'ingress au 3e round. Distinct de
        # coherency_removals (03.03) qui ne retire que des figurines isolées.
        'reserves_timeout_destroyed': {1: 0, 2: 0},
        # Occasions JUGÉES par règle du corpus (`config/rules_corpus.json`) — le compte d'exercice
        # qui manquait à 67 des 69 contrôles. Sans lui, « 0 erreur » ne distingue pas un contrôle
        # qui n'a rien trouvé d'un contrôle qui n'a rien regardé. Déclarée d'avance, une clé par
        # règle : une structure créée au premier incrément est le défaut V17.
        'rule_usage': new_rule_usage_counters(),
        'dead_unit_waiting': {1: 0, 2: 0},
        # `dead_unit_skipping` (V3) et `fight_from_non_adjacent` (V2) ont été SUPPRIMÉS le
        # 2026-08-10, et ils ne doivent pas être ré-écrits à l'identique :
        #  - `dead_unit_skipping` n'avait aucun producteur possible — le moteur ne journalise pas
        #    les `SKIP` (liste blanche `_STEP_LOG_TYPE_MAP`) ;
        #  - `fight_from_non_adjacent` avait été retiré le 2026-07-24 comme faux positif (mesure
        #    hex contre gate euclidien, cible lue après les pertes) ; 12.01 est vérifiée par
        #    `tests/unit/engine/test_fight_spatial_contract.py`.
        # Tous deux restaient déclarés à 0 et sommés dans un total : deux ✅ que rien ne mesurait.
        'charge_after_flee': {1: 0, 2: 0},
        'charge_dead_unit': {1: 0, 2: 0},
        'dead_unit_charging': {1: 0, 2: 0},
        'fight_friendly': {1: 0, 2: 0},
        'fight_dead_unit_attacker': {1: 0, 2: 0},
        'fight_dead_unit_target': {1: 0, 2: 0},
        'fight_over_cc_nb': {1: 0, 2: 0},
        'double_activation_by_phase': {
            'MOVE': 0, 'SHOOT': 0, 'CHARGE': 0, 'FIGHT': 0
        },
        'double_activation_reactive_move': 0,
        'advance_after_shoot': {1: 0, 2: 0},
        'advance_twice_in_shoot_phase': {1: 0, 2: 0},
        'position_log_mismatch': {
            'move': {'total': 0, 'mismatch': 0, 'missing': 0, 'anchor_absorbed': 0},
            'advance': {'total': 0, 'mismatch': 0, 'missing': 0, 'anchor_absorbed': 0},
            'charge': {'total': 0, 'mismatch': 0, 'missing': 0, 'anchor_absorbed': 0}
        },
        'damage_missing_unit_hp': {1: 0, 2: 0},
        'damage_exceeds_hp': {1: 0, 2: 0},
        'unit_revived': {1: 0, 2: 0},
        'shoot_invalid': {
            # 'no_los' RETIRE (2026-07-16) : cf. shoot_handler.py — LoS ancre-a-ancre contraire
            # a 06.01, non reconstructible depuis step.log. Verification deplacee en test moteur.
            1: {'total': 0, 'out_of_range': 0, 'engaged_non_close_quarters': 0},
            2: {'total': 0, 'out_of_range': 0, 'engaged_non_close_quarters': 0}
        },
        'charge_invalid': {
            1: {'total': 0, 'distance_over_roll': 0, 'advanced': 0, 'fled': 0},
            2: {'total': 0, 'distance_over_roll': 0, 'advanced': 0, 'fled': 0}
        },
        # Pile-in (12.03) et consolidation (12.08) : MAXIMUM DISTANCE 3", mêmes obstacles que
        # le move (03). Ces deux déplacements n'étaient contrôlés par rien.
        # Un slot par RÈGLE (12.03 / 12.08) : elles partagent le budget et les obstacles, pas
        # le reste. Un compteur commun rendait la ligne d'exemple ambiguë.
        'fight_move_invalid': {'pile_in': {1: 0, 2: 0}, 'consolidation': {1: 0, 2: 0}},
        'special_rule_usage': defaultdict(lambda: {1: 0, 2: 0}),  # (rule_id, unit_type) -> {1: count, 2: count}
        # Capacités de FACTION (08.04) : Waaagh!, Oath of Moment. Elles ne figurent dans AUCUN
        # `UNIT_RULES` de datasheet — c'est le mot-clé de faction qui les donne — donc la table
        # `rule_to_units` de 1.7, bâtie sur les datasheets, ne les contient pas et ne pouvait pas
        # les compter. Résultat : « 1.7 Special rules usage : 0 utilisations ✅ » sur un journal
        # qui portait 1657 `[OATH OF MOMENT]`. Un contrôle qui affiche vert en ne regardant rien.
        # Comptées ici depuis la ligne `T{tour} EFFECTS:` — une ACTIVATION par passage de
        # l'inactif à l'actif, jamais un comptage de lignes (l'instantané se répète).
        'faction_ability_activations': defaultdict(lambda: {1: 0, 2: 0}),
        'rule_choice_usage': defaultdict(
            lambda: {
                'correct': {1: 0, 2: 0},
                'missing': {1: 0, 2: 0},
                'mismatch': {1: 0, 2: 0},
            }
        ),  # (technical_rule_id, unit_type) -> status -> {1,2}
        'rule_choice_selection_usage': defaultdict(lambda: {1: 0, 2: 0}),  # (technical_rule_id, unit_type) -> {1,2}
        'rule_choice_selection_invalid': {1: 0, 2: 0},
        'reactive_move_stats': {
            1: {'applied': 0, 'declined': 0, 'abnormal': 0},
            2: {'applied': 0, 'declined': 0, 'abnormal': 0},
        },
        'reactive_move_checks': {
            'to_adjacent_enemy': {1: 0, 2: 0},
            'into_wall': {1: 0, 2: 0},
            'distance_over_roll': {1: 0, 2: 0},
        },
        'move_adjacent_before_non_flee': {1: 0, 2: 0},
        'move_distance_over_limit': {
            'move': {1: 0, 2: 0},
            'advance': {1: 0, 2: 0},
            # 09.07 FALL-BACK MOVE, « MAXIMUM DISTANCE: Your unit's M characteristic ». Le fall-back
            # etait le SEUL des six deplacements sans controle de budget ni de chemin (vert vacant
            # V10) : `_handle_fled` ne verifiait que la collision d'ancre et le mur d'arrivee.
            'flee': {1: 0, 2: 0},
        },
        # 09.07 « ELIGIBLE IF: Your unit is engaged. » — une unite non engagee ne peut pas battre
        # en retraite. Mesure per-figurine aux socles de DEPART, meme primitive que #3.
        'flee_from_unengaged': {1: 0, 2: 0},
        # 09.07 « AFTER MOVING: Your unit must be unengaged. » — post-condition, mesuree aux
        # socles d'ARRIVEE. C'est la raison d'etre du fall-back : s'il finit engage, il a echoue.
        'flee_still_engaged': {1: 0, 2: 0},
        'action_phase_accuracy': {
            'move': {'total': 0, 'wrong': 0},
            'fled': {'total': 0, 'wrong': 0},
            'shoot': {'total': 0, 'wrong': 0},
            'advance': {'total': 0, 'wrong': 0},
            'charge': {'total': 0, 'wrong': 0},
            'fight': {'total': 0, 'wrong': 0}
        },
        'fight_alternation_violations': {1: 0, 2: 0},
        # 12.02 « Each unit cannot make more than one pile-in move during this step ». §1.6 ne
        # pouvait pas le voir : son marqueur d'activation de combat est `CONSOLIDATED` (12.07),
        # et un double pile-in ne produit aucune consolidation supplémentaire.
        'fight_double_pile_in': {1: 0, 2: 0},
        'fight_attacks_by_unit': {1: {}, 2: {}},
        'fight_over_cc_nb_by_unit': {1: {}, 2: {}},
        # First occurrence lines for each error type (stores dict with 'episode' and 'line')
        'first_error_lines': {
            'wall_collisions': {1: None, 2: None},
            'move_to_adjacent_enemy': {1: None, 2: None},
            'shoot_hit_result_mismatch': {1: None, 2: None},
            'indirect_fire_mismatch': {1: None, 2: None},
            'fight_hit_result_mismatch': {1: None, 2: None},
            'shoot_wound_threshold_mismatch': {1: None, 2: None},
            'fight_wound_threshold_mismatch': {1: None, 2: None},
            'dead_unit_moving': {1: None, 2: None},
            'charge_from_adjacent': {1: None, 2: None},
            'advance_from_adjacent': {1: None, 2: None},
            'dead_unit_advancing': {1: None, 2: None},
            'shoot_after_flee': {1: None, 2: None},
            'move_after_shooting_distance_over_limit': {1: None, 2: None},
            'shoot_at_friendly': {1: None, 2: None},
            'shoot_at_engaged_enemy': {1: None, 2: None},
            'close_quarters_shot_at_unengaged_target': {1: None, 2: None},
            'shoot_dead_unit': {1: None, 2: None},
            'shoot_at_dead_unit': {1: None, 2: None},
            'shoot_over_rng_nb': {1: None, 2: None},
            'shoot_combi_profile_conflicts': {1: None, 2: None},
            'devastating_wounds_incorrect': {1: None, 2: None},
            'squad_coherency_violations': {1: None, 2: None},
            'dead_unit_waiting': {1: None, 2: None},
            'charge_after_flee': {1: None, 2: None},
            'charge_dead_unit': {1: None, 2: None},
            'dead_unit_charging': {1: None, 2: None},
            'fight_friendly': {1: None, 2: None},
            'fight_dead_unit_attacker': {1: None, 2: None},
            'fight_dead_unit_target': {1: None, 2: None},
            'fight_over_cc_nb': {1: None, 2: None},
            'double_activation_by_phase': {
                'MOVE': None, 'SHOOT': None, 'CHARGE': None, 'FIGHT': None
            },
            'double_activation_reactive_move': None,
            'advance_after_shoot': {1: None, 2: None},
            'advance_twice_in_shoot_phase': {1: None, 2: None},
            'damage_missing_unit_hp': {1: None, 2: None},
            'damage_exceeds_hp': {1: None, 2: None},
            'unit_revived': {1: None, 2: None},
            'fled_action': {1: None, 2: None},
            'shoot_invalid': {
                1: None,
                2: None
            },
            'charge_invalid': {1: None, 2: None},
            'fight_move_invalid': {'pile_in': {1: None, 2: None}, 'consolidation': {1: None, 2: None}},
            'reactive_move_abnormal': {1: None, 2: None},
            'reactive_move_to_adjacent_enemy': {1: None, 2: None},
            'reactive_move_into_wall': {1: None, 2: None},
            'reactive_move_distance_over_roll': {1: None, 2: None},
            'rule_choice_selection_invalid': {1: None, 2: None},
            'rule_choice_usage_missing': {1: None, 2: None},
            'rule_choice_usage_mismatch': {1: None, 2: None},
            'move_adjacent_before_non_flee': {1: None, 2: None},
            'move_distance_over_limit': {
                'move': {1: None, 2: None},
                'advance': {1: None, 2: None},
                'flee': {1: None, 2: None},
            },
            'flee_from_unengaged': {1: None, 2: None},
            'flee_still_engaged': {1: None, 2: None},
            'action_phase_mismatch': {
                'move': None,
                'fled': None,
                'shoot': None,
                'advance': None,
                'charge': None,
                'fight': None
            },
            'fight_alternation_violations': {1: None, 2: None},
            'fight_double_pile_in': {1: None, 2: None},
            'position_log_mismatch': {
                'move': None,
                'advance': None,
                'charge': None
            },
        },
        'unit_position_collisions': [],
        'parse_errors': [],
        # DÉCLARÉ ICI, comme ses deux voisins, et pas créé à la volée par son premier
        # producteur. `parse_step_log` rendait un `stats` SANS cette clé : elle n'apparaissait
        # qu'au `setdefault` de `print_statistics`, 130 lignes avant le seul lecteur qui la
        # lit sans garde. Tout consommateur du `stats` rendu — un test, un script — levait
        # KeyError, et c'est ce que la garde `if … in stats` du total CLI compensait en aval
        # au lieu de le corriger en amont. Mesuré le 2026-08-10.
        'unit_id_mismatches': [],
        'episodes_without_end': [],
        'episodes_without_method': [],
        'episode_durations': [],  # List of (episode_num, duration_seconds) tuples
        'sample_actions': {
            'move': None,
            'shoot': None,
            'advance': None,
            'charge': None,
            'fight': None
        }
    }

    from ai.analyzer_state import make_initial_state
    from ai.analyzer_core import run as _run_core
    state = make_initial_state(stats)
    # Ce que le journal GARANTIT porter, lu AVANT la boucle : c'est ce qui autorise le parseur à
    # traiter une donnée manquante comme une panne plutôt que comme un vieux format.
    state.log_grammar = parse_log_grammar_version(filepath)
    _run_core(state, _cfg, filepath)


    # Close debug log file
    if _debug_log_file:
        _debug_log_file.close()
        _debug_log_file = None

    return stats


def parse_step_timings_from_debug(debug_log_path: str) -> Optional[List[Tuple[int, int, float]]]:
    """
    LOG TEMPORAIRE: Parse STEP_TIMING lines from debug.log (only written when --debug).
    Returns list of (episode, step_index, duration_s) or None if file missing.

    Un 4e champ `step_calls` etait lu depuis un suffixe optionnel ` step_calls=<n>` de la ligne
    STEP_TIMING, et alimentait une statistique « Step calls between step_increment ». Le producteur
    de ce suffixe (`StepLogger.log_action(step_calls_since_last=...)`, renseigne depuis le bloc
    step_logger de `W40KEngine._process_semantic_action`) a ete supprime le 2026-07-29 parce
    qu'inatteignable : plus aucun run ne peut ecrire ce suffixe, la statistique etait donc morte.
    Les debug.log archives restent lisibles — leurs 3 premiers champs sont inchanges, seul le
    suffixe est desormais ignore.
    """
    if not os.path.isfile(debug_log_path):
        return None
    result: List[Tuple[int, int, float]] = []
    pattern = re.compile(r'STEP_TIMING episode=(\d+) step_index=(\d+) duration_s=([\d.]+)')
    try:
        with open(debug_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                m = pattern.search(line)
                if m:
                    result.append((int(m.group(1)), int(m.group(2)), float(m.group(3))))
    except (OSError, ValueError):
        return None
    return result if result else None


def parse_predict_timings_from_debug(debug_log_path: str) -> Optional[List[Tuple[int, int, float]]]:
    """
    LOG TEMPORAIRE: Parse PREDICT_TIMING lines from debug.log (model.predict(), written by bot_evaluation when --debug).
    Returns list of (episode, step_index, duration_s) or None if file missing/unreadable.
    """
    if not os.path.isfile(debug_log_path):
        return None
    result: List[Tuple[int, int, float]] = []
    pattern = re.compile(r'PREDICT_TIMING episode=(\d+) step_index=(\d+) duration_s=([\d.]+)')
    try:
        with open(debug_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                m = pattern.search(line)
                if m:
                    result.append((int(m.group(1)), int(m.group(2)), float(m.group(3))))
    except (OSError, ValueError):
        return None
    return result if result else None


def parse_cascade_timings_from_debug(debug_log_path: str) -> Optional[List[Tuple[int, int, str, str, float]]]:
    """
    LOG TEMPORAIRE: Parse CASCADE_TIMING lines from debug.log (cascade loop phase_*_start, only when --debug).
    Returns list of (episode, cascade_num, from_phase, to_phase, duration_s) or None.
    """
    if not os.path.isfile(debug_log_path):
        return None
    result: List[Tuple[int, int, str, str, float]] = []
    pattern = re.compile(r'CASCADE_TIMING episode=(\d+) cascade_num=(\d+) from_phase=(\w+) to_phase=(\w+) duration_s=([\d.]+)')
    try:
        with open(debug_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                m = pattern.search(line)
                if m:
                    result.append((int(m.group(1)), int(m.group(2)), m.group(3), m.group(4), float(m.group(5))))
    except (OSError, ValueError):
        return None
    return result if result else None


def parse_between_step_timings_from_debug(debug_log_path: str) -> Optional[List[Tuple[int, int, float]]]:
    """
    LOG TEMPORAIRE: Parse BETWEEN_STEP_TIMING lines from debug.log (time between step() return and next step() call = SB3 loop / predict, only when --debug).
    Returns list of (episode, step_index, duration_s) or None.
    """
    if not os.path.isfile(debug_log_path):
        return None
    result: List[Tuple[int, int, float]] = []
    pattern = re.compile(r'BETWEEN_STEP_TIMING episode=(\d+) step_index=(\d+) duration_s=([\d.]+)')
    try:
        with open(debug_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                m = pattern.search(line)
                if m:
                    result.append((int(m.group(1)), int(m.group(2)), float(m.group(3))))
    except (OSError, ValueError):
        return None
    return result if result else None


def parse_pre_step_timings_from_debug(debug_log_path: str) -> Optional[List[Tuple[int, int, float]]]:
    """
    LOG TEMPORAIRE: Parse PRE_STEP_TIMING lines from debug.log (time from step() entry to _step_t0, only when --debug).
    Returns list of (episode, step_index, duration_s) or None.
    """
    if not os.path.isfile(debug_log_path):
        return None
    result: List[Tuple[int, int, float]] = []
    pattern = re.compile(r'PRE_STEP_TIMING episode=(\d+) step_index=(\d+) duration_s=([\d.]+)')
    try:
        with open(debug_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                m = pattern.search(line)
                if m:
                    result.append((int(m.group(1)), int(m.group(2)), float(m.group(3))))
    except (OSError, ValueError):
        return None
    return result if result else None


def parse_post_step_timings_from_debug(debug_log_path: str) -> Optional[List[Tuple[int, int, float]]]:
    """
    LOG TEMPORAIRE: Parse POST_STEP_TIMING lines from debug.log (time from _step_t5 to return, only when --debug).
    Returns list of (episode, step_index, duration_s) or None.
    """
    if not os.path.isfile(debug_log_path):
        return None
    result: List[Tuple[int, int, float]] = []
    pattern = re.compile(r'POST_STEP_TIMING episode=(\d+) step_index=(\d+) duration_s=([\d.]+)')
    try:
        with open(debug_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                m = pattern.search(line)
                if m:
                    result.append((int(m.group(1)), int(m.group(2)), float(m.group(3))))
    except (OSError, ValueError):
        return None
    return result if result else None


def parse_reset_timings_from_debug(debug_log_path: str) -> Optional[List[Tuple[int, float]]]:
    """
    LOG TEMPORAIRE: Parse RESET_TIMING lines from debug.log (reset() duration per episode, only when --debug).
    Returns list of (episode, duration_s) or None.
    """
    if not os.path.isfile(debug_log_path):
        return None
    result: List[Tuple[int, float]] = []
    pattern = re.compile(r'RESET_TIMING episode=(\d+) duration_s=([\d.]+)')
    try:
        with open(debug_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                m = pattern.search(line)
                if m:
                    result.append((int(m.group(1)), float(m.group(2))))
    except (OSError, ValueError):
        return None
    return result if result else None


def parse_wrapper_step_timings_from_debug(debug_log_path: str) -> Optional[List[Tuple[int, int, float]]]:
    """
    LOG TEMPORAIRE: Parse WRAPPER_STEP_TIMING lines from debug.log (duration of full env.step() call in wrapper, only when --debug).
    Returns list of (episode, step_index, duration_s) or None.
    """
    if not os.path.isfile(debug_log_path):
        return None
    result: List[Tuple[int, int, float]] = []
    pattern = re.compile(r'WRAPPER_STEP_TIMING episode=(\d+) step_index=(\d+) duration_s=([\d.]+)')
    try:
        with open(debug_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                m = pattern.search(line)
                if m:
                    result.append((int(m.group(1)), int(m.group(2)), float(m.group(3))))
    except (OSError, ValueError):
        return None
    return result if result else None


def parse_after_step_increment_timings_from_debug(debug_log_path: str) -> Optional[List[Tuple[int, int, float]]]:
    """
    LOG TEMPORAIRE: Parse AFTER_STEP_INCREMENT_TIMING lines from debug.log (time from log_action to return, only when --debug).
    Returns list of (episode, step_index, duration_s) or None.
    """
    if not os.path.isfile(debug_log_path):
        return None
    result: List[Tuple[int, int, float]] = []
    pattern = re.compile(r'AFTER_STEP_INCREMENT_TIMING episode=(\d+) step_index=(\d+) duration_s=([\d.]+)')
    try:
        with open(debug_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                m = pattern.search(line)
                if m:
                    result.append((int(m.group(1)), int(m.group(2)), float(m.group(3))))
    except (OSError, ValueError):
        return None
    return result if result else None


def parse_console_log_write_timings_from_debug(debug_log_path: str) -> Optional[List[Tuple[int, int, float, int]]]:
    """
    LOG TEMPORAIRE: Parse CONSOLE_LOG_WRITE_TIMING lines from debug.log (only when --debug).
    Returns list of (episode, step_index, duration_s, lines) or None.
    """
    if not os.path.isfile(debug_log_path):
        return None
    result: List[Tuple[int, int, float, int]] = []
    pattern = re.compile(r'CONSOLE_LOG_WRITE_TIMING episode=(\d+) step_index=(\d+) duration_s=([\d.]+) lines=(\d+)')
    try:
        with open(debug_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                m = pattern.search(line)
                if m:
                    result.append((int(m.group(1)), int(m.group(2)), float(m.group(3)), int(m.group(4))))
    except (OSError, ValueError):
        return None
    return result if result else None


def parse_get_mask_timings_from_debug(debug_log_path: str) -> Optional[List[Tuple[int, int, float]]]:
    """
    LOG TEMPORAIRE: Parse GET_MASK_TIMING lines from debug.log (get_action_mask in bot loop, only when --debug).
    Returns list of (episode, step_index, duration_s) or None.
    """
    if not os.path.isfile(debug_log_path):
        return None
    result: List[Tuple[int, int, float]] = []
    pattern = re.compile(r'GET_MASK_TIMING episode=(\d+) step_index=(\d+) duration_s=([\d.]+)')
    try:
        with open(debug_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                m = pattern.search(line)
                if m:
                    result.append((int(m.group(1)), int(m.group(2)), float(m.group(3))))
    except (OSError, ValueError):
        return None
    return result if result else None


def parse_step_breakdowns_from_debug(debug_log_path: str) -> Optional[List[Tuple[int, int, float, float, float, float, float, float, float]]]:
    """
    LOG TEMPORAIRE: Parse STEP_BREAKDOWN lines from debug.log (only written when --debug).
    Returns list of (episode, step_index, get_mask_s, convert_s, process_s, replay_s, build_obs_s, reward_s, total_s) or None.
    """
    if not os.path.isfile(debug_log_path):
        return None
    result: List[Tuple[int, int, float, float, float, float, float, float, float]] = []
    # New format with replay_s
    pattern_new = re.compile(
        r'STEP_BREAKDOWN episode=(\d+) step_index=(\d+) get_mask_s=([\d.]+) convert_s=([\d.]+) '
        r'process_s=([\d.]+) replay_s=([\d.]+) build_obs_s=([\d.]+) reward_s=([\d.]+) total_s=([\d.]+)'
    )
    pattern_old = re.compile(
        r'STEP_BREAKDOWN episode=(\d+) step_index=(\d+) get_mask_s=([\d.]+) convert_s=([\d.]+) '
        r'process_s=([\d.]+) build_obs_s=([\d.]+) reward_s=([\d.]+) total_s=([\d.]+)'
    )
    try:
        with open(debug_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                m = pattern_new.search(line)
                if m:
                    result.append((
                        int(m.group(1)), int(m.group(2)),
                        float(m.group(3)), float(m.group(4)), float(m.group(5)),
                        float(m.group(6)), float(m.group(7)), float(m.group(8)), float(m.group(9))
                    ))
                    continue
                m = pattern_old.search(line)
                if m:
                    # replay_s=0 for old format
                    result.append((
                        int(m.group(1)), int(m.group(2)),
                        float(m.group(3)), float(m.group(4)), float(m.group(5)),
                        0.0, float(m.group(6)), float(m.group(7)), float(m.group(8))
                    ))
    except (OSError, ValueError):
        return None
    return result if result else None


def print_statistics(stats: Dict, output_f=None, step_timings: Optional[List[Tuple[int, int, float]]] = None, predict_timings: Optional[List[Tuple[int, int, float]]] = None, get_mask_timings: Optional[List[Tuple[int, int, float]]] = None, console_log_write_timings: Optional[List[Tuple[int, int, float, int]]] = None, cascade_timings: Optional[List[Tuple[int, int, str, str, float]]] = None, step_breakdowns: Optional[List[Tuple[int, int, float, float, float, float, float, float, float]]] = None, between_step_timings: Optional[List[Tuple[int, int, float]]] = None, reset_timings: Optional[List[Tuple[int, float]]] = None, post_step_timings: Optional[List[Tuple[int, int, float]]] = None, pre_step_timings: Optional[List[Tuple[int, int, float]]] = None, wrapper_step_timings: Optional[List[Tuple[int, int, float]]] = None, after_step_increment_timings: Optional[List[Tuple[int, int, float]]] = None, debug_section_filter: Optional[str] = None, output_lines: Optional[List[str]] = None, emit_console: bool = True):
    """Print formatted statistics."""
    active_debug_section: Optional[str] = None

    def log_print(*args, **kwargs):
        """Print to both console and file if output_f provided"""
        if debug_section_filter is not None and active_debug_section is not None:
            if active_debug_section != debug_section_filter:
                return
        if emit_console:
            print(*args, **kwargs)
        if output_lines is not None:
            sep = kwargs.get("sep", " ")
            message = sep.join(str(a) for a in args)
            output_lines.append(message)
        if output_f:
            print(*args, file=output_f, **kwargs)
            output_f.flush()

    debug_sections = {
        "1.1": "MOVEMENT ERRORS",
        "1.2": "SHOOTING ERRORS",
        "1.3": "CHARGE ERRORS",
        "1.4": "FIGHT ERRORS",
        "1.5": "ACTION PHASE ACCURACY",
        "1.6": "DOUBLE-ACTIVATION PAR PHASE",
        "1.7": "SPECIAL RULES USAGE",
        "1.8": "WEAPONS RULES USAGE",
        "2.1": "DEAD UNITS INTERACTIONS",
        "2.2": "POSITION / LOG COHERENCE",
        "2.3": "DMG ISSUES",
        "2.4": "EPISODES STATISTICS",
        "2.5": "EPISODES ENDING",
        "2.6": "SAMPLE MISSING",
        "2.7": "CORE ISSUES",
        "2.8": "ETAT RECONSTRUIT vs ETAT MOTEUR",
    }

    TABLE_LABEL_WIDTH = 38
    TABLE_VALUE_WIDTH = 18
    WR_RULE_WIDTH = 28
    WR_WEAPON_WIDTH = 40
    WR_VALUE_WIDTH = 10
    WR_VALID_WIDTH = 10

    def _table_header(title: str) -> None:
        log_print("-" * 80)
        log_print(
            f"{title:<{TABLE_LABEL_WIDTH}} "
            f"{'Joueur 1':>{TABLE_VALUE_WIDTH}} "
            f"{'Joueur 2':>{TABLE_VALUE_WIDTH}}"
        )
        log_print("-" * 80)

    def _table_row(label: str, p1_value: str, p2_value: str) -> None:
        display_label = label
        if len(display_label) > TABLE_LABEL_WIDTH:
            display_label = display_label[: TABLE_LABEL_WIDTH - 3] + "..."
        log_print(
            f"{display_label:<{TABLE_LABEL_WIDTH}} "
            f"{p1_value:>{TABLE_VALUE_WIDTH}} "
            f"{p2_value:>{TABLE_VALUE_WIDTH}}"
        )

    def _fmt_count(value: int) -> str:
        return f"{value:6d}"

    def _wound_threshold_rows(stats: Dict[str, Any], key: str, label: str) -> None:
        """Deux lignes pour le contrôle du seuil de blessure : les écarts, et les lignes non jugées.

        La seconde n'est pas décorative. Un contrôle qui écarte silencieusement ce qu'il ne sait pas
        mesurer affiche zéro et se fait oublier : c'est le « vert vacant », le défaut le plus long à
        voir de ce dépôt. Elle rend visible ce que le contrôle NE regarde pas.
        """
        _table_row(
            f"Seuil de blessure faux ({label}, 05.02):",
            _fmt_count(stats[f'{key}_mismatch'][1]), _fmt_count(stats[f'{key}_mismatch'][2]),
        )
        for _pl in (1, 2):
            _first = stats['first_error_lines'][f'{key}_mismatch'][_pl]
            if stats[f'{key}_mismatch'][_pl] > 0 and _first:
                log_print(f"  First P{_pl} occurrence (Episode {_first['episode']}): {_first['line']}")
                log_print(f"    {_first['detail']}")
        _table_row(
            f"  ↳ lignes non verifiables ({label}):",
            _fmt_count(stats[f'{key}_unverifiable'][1]), _fmt_count(stats[f'{key}_unverifiable'][2]),
        )

    def _hit_result_rows(stats: Dict[str, Any], key: str, label: str) -> None:
        """Jumeau strict de `_wound_threshold_rows` pour 05.01, seconde ligne comprise.

        Ici la seconde ligne compte les lignes JUGÉES et non les non-jugeables : côté touche, ce
        qui échappe au contrôle n'est pas une donnée manquante mais une absence de jet
        ([TORRENT], [SUSTAINED HITS]). Le besoin est le même — distinguer « aucune faute » de
        « plus rien n'est regardé » — la grandeur disponible ne l'est pas.
        """
        _table_row(
            f"Verdict de touche faux ({label}, 05.01):",
            _fmt_count(stats[f'{key}_mismatch'][1]), _fmt_count(stats[f'{key}_mismatch'][2]),
        )
        for _pl in (1, 2):
            _first = stats['first_error_lines'][f'{key}_mismatch'][_pl]
            if stats[f'{key}_mismatch'][_pl] > 0 and _first:
                log_print(f"  First P{_pl} occurrence (Episode {_first['episode']}): {_first['line']}")
                log_print(f"    {_first['detail']}")
        _table_row(
            f"  ↳ jets de touche juges ({label}):",
            _fmt_count(stats[f'{key}_checked'][1]), _fmt_count(stats[f'{key}_checked'][2]),
        )

    def _fmt_count_pct(value: int, total: int) -> str:
        pct = (value / total * 100.0) if total > 0 else 0.0
        return f"{value:6d} ({pct:5.1f}%)"

    def _wr_header() -> None:
        log_print("-" * 80)
        log_print(
            f"{'1.8 WEAPONS RULES USAGE':<{WR_RULE_WIDTH}} "
            f"{'Weapon':<{WR_WEAPON_WIDTH}} "
            f"{'P1':>{WR_VALUE_WIDTH}} "
            f"{'P2':>{WR_VALUE_WIDTH}} "
            f"{'Validité':>{WR_VALID_WIDTH}}"
        )
        log_print("-" * 80)

    def _wr_row(rule_name: str, weapon_name: str, p1_value: int, p2_value: int, validity: str) -> None:
        display_weapon = weapon_name
        if len(display_weapon) > WR_WEAPON_WIDTH:
            display_weapon = display_weapon[: WR_WEAPON_WIDTH - 3] + "..."
        display_validity = validity
        if len(display_validity) > WR_VALID_WIDTH:
            display_validity = display_validity[: WR_VALID_WIDTH - 3] + "..."
        log_print(
            f"{rule_name:<{WR_RULE_WIDTH}} "
            f"{display_weapon:<{WR_WEAPON_WIDTH}} "
            f"{p1_value:>{WR_VALUE_WIDTH}d} "
            f"{p2_value:>{WR_VALUE_WIDTH}d} "
            f"{display_validity:>{WR_VALID_WIDTH}}"
        )
    if debug_section_filter is not None and debug_section_filter not in debug_sections:
        valid_sections = ", ".join(str(k) for k in sorted(debug_sections))
        raise ValueError(f"Invalid debug section: {debug_section_filter}. Valid sections: {valid_sections}")

    avg_length = None
    max_length = None
    max_length_episode = None
    avg_duration = None
    max_duration = None
    max_duration_episode = None
    
    log_print("=" * 80)
    log_print("STEP.LOG ANALYSIS - GAME RULES VALIDATION")
    log_print("=" * 80)
    
    log_print("\n" + "=" * 80)
    log_print("GAME ANALYSIS")
    log_print("=" * 80)

    # MÉTRIQUES GLOBALES
    log_print(f"\nTotal Episodes: {stats['total_episodes']}")
    log_print(f"Total Actions: {stats['total_actions']}")
    
    if stats['episode_lengths']:
        lengths_list = stats['episode_lengths']
        durations_list = require_key(stats, 'episode_durations')
        # Create mapping from episode_num to duration for quick lookup
        durations_dict = {ep_num: duration for ep_num, duration in durations_list}
        shared_episodes = [ep_num for ep_num, _ in lengths_list if ep_num in durations_dict]
        if not shared_episodes:
            raise ValueError(
                "No shared episodes between episode_lengths and episode_durations; "
                "cannot compute action min/max duration pairs."
            )
        comparable_lengths = [(ep_num, action_count) for ep_num, action_count in lengths_list if ep_num in durations_dict]
        
        # Find min and max episodes (lengths is list of (episode_num, action_count) tuples)
        min_episode_num, min_length = min(comparable_lengths, key=lambda x: x[1])
        max_episode_num, max_length = max(comparable_lengths, key=lambda x: x[1])
        max_length_episode = max_episode_num
        avg_length = sum(action_count for _, action_count in lengths_list) / len(lengths_list)
        
        # Get durations for min/max episodes
        min_duration = durations_dict[min_episode_num]
        max_duration = durations_dict[max_episode_num]
        
        min_duration_str = f"{min_duration:.2f}s"
        max_duration_str = f"{max_duration:.2f}s"
        
        log_print(f"Episode Actions: {avg_length:.1f} (average)")
        log_print(f"  Min: {min_length} (Episode {min_episode_num}) - (duration: {min_duration_str})")
        log_print(f"  Max: {max_length} (Episode {max_episode_num}) - (duration: {max_duration_str})")
        
        # Detect episodes that reached the action limit (>= 990, which is 90% of 1000 limit)
        action_limit_episodes = [ep_num for ep_num, action_count in lengths_list if action_count >= 990]
        if action_limit_episodes:
            log_print("")
            log_print("-" * 36)
            episodes_str = ", ".join(str(ep_num) for ep_num in sorted(action_limit_episodes))
            log_print(f"EPISODES REACHING THE ACTIONS LIMIT: {episodes_str}")
    
    # Episode durations
    if stats['episode_durations']:
        durations_list = stats['episode_durations']
        lengths_list = require_key(stats, 'episode_lengths')
        # Create mapping from episode_num to action_count for quick lookup
        lengths_dict = {ep_num: action_count for ep_num, action_count in lengths_list}
        shared_episodes = [ep_num for ep_num, _ in durations_list if ep_num in lengths_dict]
        if not shared_episodes:
            raise ValueError(
                "No shared episodes between episode_durations and episode_lengths; "
                "cannot compute duration min/max action pairs."
            )
        comparable_durations = [(ep_num, duration) for ep_num, duration in durations_list if ep_num in lengths_dict]
        
        # Find min and max episodes (durations is list of (episode_num, duration) tuples)
        min_episode_num, min_duration = min(comparable_durations, key=lambda x: x[1])
        max_episode_num, max_duration = max(comparable_durations, key=lambda x: x[1])
        max_duration_episode = max_episode_num
        avg_duration = sum(duration for _, duration in durations_list) / len(durations_list)
        
        # Get action counts for min/max episodes
        min_actions = lengths_dict[min_episode_num]
        max_actions = lengths_dict[max_episode_num]
        
        min_actions_str = str(min_actions)
        max_actions_str = str(max_actions)
        
        log_print(f"Episode Durations: {avg_duration:.2f}s (average)")
        log_print(f"  Min: {min_duration:.2f}s (Episode {min_episode_num}) - (actions: {min_actions_str})")
        log_print(f"  Max: {max_duration:.2f}s (Episode {max_episode_num}) - (actions: {max_actions_str})")
    
    '''
    # LOG TEMPORAIRE: Reset timing (reset() duration per episode, from debug.log when --debug)
    if reset_timings:
        log_print("")
        all_reset = [r[1] for r in reset_timings]
        n_reset = len(all_reset)
        avg_reset = sum(all_reset) / n_reset if n_reset else 0.0
        max_reset = max(all_reset) if all_reset else 0.0
        max_reset_ep = max(reset_timings, key=lambda x: x[1])
        log_print(f"Reset timing (from debug.log, --debug): avg={avg_reset:.3f}s, max={max_reset:.3f}s (n={n_reset})")
        log_print(f"  Max: {max_reset:.3f}s (Episode {max_reset_ep[0]})")
    
    # LOG TEMPORAIRE: Step durations (by step index, from debug.log STEP_TIMING when --debug)
    if step_timings:
        log_print("")
        # step_timings: (episode, step_index, duration_s)
        by_index: Dict[int, List[float]] = defaultdict(list)
        for _ep, idx, dur in step_timings:
            by_index[idx].append(dur)
        all_durations = [d for _e, _i, d in step_timings]
        n_steps = len(all_durations)
        avg_all = sum(all_durations) / n_steps if n_steps else 0.0
        min_all = min(all_durations) if all_durations else 0.0
        max_all = max(all_durations) if all_durations else 0.0
        # Which (episode, step_index) has min/max duration (global over all steps)
        min_ep, min_idx, min_val = min(step_timings, key=lambda t: t[2])
        max_ep, max_idx, max_val = max(step_timings, key=lambda t: t[2])
        log_print(f"Step Durations (from debug.log): {avg_all:.3f}s (average), Min: {min_all:.3f}s, Max: {max_all:.3f}s (n={n_steps} steps)")
        log_print(f"  Min: {min_val:.3f}s (Episode {min_ep}, step index {min_idx})")
        log_print(f"  Max: {max_val:.3f}s (Episode {max_ep}, step index {max_idx})")
        # (le suffixe « N step() calls » et la stat « Step calls between step_increment » vivaient
        #  ici : leur producteur a ete supprime le 2026-07-29, voir parse_step_timings_from_debug)
        # LOG TEMPORAIRE: show STEP_BREAKDOWN for the slowest step (same episode/step_index or step_index-1 for early-return)
        if step_breakdowns:
            # step_breakdowns: (episode, step_index, get_mask_s, convert_s, process_s, replay_s, build_obs_s, reward_s, total_s)
            matching = [b for b in step_breakdowns if b[0] == max_ep and (b[1] == max_idx or b[1] == max_idx - 1)]
            if matching:
                # Prefer the one with total_s closest to max_val (the actual slow step)
                b = max(matching, key=lambda x: x[8])
                log_print(f"  Breakdown for slowest step (Ep {b[0]}, step {b[1]}): get_mask={b[2]:.3f}s convert={b[3]:.3f}s process={b[4]:.3f}s replay={b[5]:.3f}s build_obs={b[6]:.3f}s reward={b[7]:.3f}s total={b[8]:.3f}s")
            else:
                log_print(f"  No STEP_BREAKDOWN for slowest step (Episode {max_ep}, step index {max_idx}) — check debug.log for [EARLY_NO_ACTIONS]")
            # LOG TEMPORAIRE: list any STEP_BREAKDOWN for same episode with total_s > 1.0s (to spot [EARLY_NO_ACTIONS] or other step_index)
            high_total_same_ep = [b for b in step_breakdowns if b[0] == max_ep and b[8] > 1.0]
            if high_total_same_ep:
                high_total_same_ep.sort(key=lambda x: -x[8])
                for b in high_total_same_ep:
                    log_print(f"  STEP_BREAKDOWN Ep {b[0]} step {b[1]} total_s={b[8]:.3f}s (get_mask={b[2]:.3f} process={b[4]:.3f} build_obs={b[6]:.3f})")
        # LOG TEMPORAIRE: when slowest step is step index 0, show reset() duration for that episode (explains slow first step)
        if max_idx == 0 and reset_timings:
            reset_for_ep = [r for r in reset_timings if r[0] == max_ep]
            if reset_for_ep:
                reset_dur = reset_for_ep[0][1]
                log_print(f"  Reset of episode {max_ep} took {reset_dur:.3f}s (slowest step is first step of episode)")
        # LOG TEMPORAIRE: PRE_STEP_TIMING for slowest step (time from step() entry to _step_t0 = game_over + counter)
        if pre_step_timings:
            pre_for_slowest = [p for p in pre_step_timings if p[0] == max_ep and p[1] == max_idx]
            if pre_for_slowest:
                pre_val = max(pre_for_slowest, key=lambda x: x[2])[2]
                log_print(f"  Pre-step (entry to _step_t0) for slowest step: {pre_val:.3f}s")
            all_pre = [p[2] for p in pre_step_timings]
            n_pre = len(all_pre)
            avg_pre = sum(all_pre) / n_pre if n_pre else 0.0
            max_pre = max(all_pre) if all_pre else 0.0
            log_print(f"  Pre-step timing (--debug): avg={avg_pre:.3f}s, max={max_pre:.3f}s (n={n_pre})")
        # LOG TEMPORAIRE: POST_STEP_TIMING for slowest step (time from _step_t5 to return = last_unit_positions + STEP_BREAKDOWN + console_logs)
        if post_step_timings:
            post_for_slowest = [p for p in post_step_timings if p[0] == max_ep and (p[1] == max_idx or p[1] == max_idx - 1)]
            if post_for_slowest:
                post_val = max(post_for_slowest, key=lambda x: x[2])[2]
                log_print(f"  Post-step (after _step_t5 to return) for slowest step: {post_val:.3f}s")
            all_post = [p[2] for p in post_step_timings]
            n_post = len(all_post)
            avg_post = sum(all_post) / n_post if n_post else 0.0
            max_post = max(all_post) if all_post else 0.0
            log_print(f"  Post-step timing (--debug): avg={avg_post:.3f}s, max={max_post:.3f}s (n={n_post})")
        # LOG TEMPORAIRE: BETWEEN_STEP_TIMING for slowest step (time between step() return and next step() call = SB3 loop / predict)
        if between_step_timings:
            between_for_slowest = [b for b in between_step_timings if b[0] == max_ep and b[1] == max_idx]
            if between_for_slowest:
                between_val = between_for_slowest[0][2]
                log_print(f"  Between-step (SB3 loop / predict) for slowest step: {between_val:.3f}s")
            all_between = [b[2] for b in between_step_timings]
            n_bt = len(all_between)
            avg_bt = sum(all_between) / n_bt if n_bt else 0.0
            max_bt = max(all_between) if all_between else 0.0
            log_print(f"  Between-step timing (--debug): avg={avg_bt:.3f}s, max={max_bt:.3f}s (n={n_bt})")
        # LOG TEMPORAIRE: WRAPPER_STEP_TIMING for slowest step (full env.step() call in wrapper; compare with STEP_TIMING).
        # Also check max_idx±1 because engine STEP_TIMING step_index can differ from wrapper episode_steps (off-by-one).
        if wrapper_step_timings:
            wrapper_for_slowest = [w for w in wrapper_step_timings if w[0] == max_ep and w[1] in (max_idx - 1, max_idx, max_idx + 1)]
            if wrapper_for_slowest:
                wrapper_val = max(wrapper_for_slowest, key=lambda x: x[2])[2]
                log_print(f"  Wrapper step (env.step call) for slowest step: {wrapper_val:.3f}s")
            all_wrapper = [w[2] for w in wrapper_step_timings]
            n_wrap = len(all_wrapper)
            avg_wrap = sum(all_wrapper) / n_wrap if n_wrap else 0.0
            max_wrap = max(all_wrapper) if all_wrapper else 0.0
            log_print(f"  Wrapper step timing (--debug): avg={avg_wrap:.3f}s, max={max_wrap:.3f}s (n={n_wrap})")
        # LOG TEMPORAIRE: AFTER_STEP_INCREMENT_TIMING for slowest step (time from log_action to return = last_unit_positions + STEP_BREAKDOWN + console_logs)
        if after_step_increment_timings:
            after_for_slowest = [a for a in after_step_increment_timings if a[0] == max_ep and a[1] in (max_idx - 1, max_idx, max_idx + 1)]
            if after_for_slowest:
                after_val = max(after_for_slowest, key=lambda x: x[2])[2]
                log_print(f"  After step_increment (log_action to return) for slowest step: {after_val:.3f}s")
            all_after = [a[2] for a in after_step_increment_timings]
            n_after = len(all_after)
            avg_after = sum(all_after) / n_after if n_after else 0.0
            max_after = max(all_after) if all_after else 0.0
            log_print(f"  After step_increment timing (--debug): avg={avg_after:.3f}s, max={max_after:.3f}s (n={n_after})")
        # LOG TEMPORAIRE: previous step (Ep max_ep, step max_idx-1) breakdown + POST_STEP + AFTER_STEP_INCREMENT (STEP_TIMING = time from prev step_increment to this one; slow part may be in prev step's tail)
        if max_idx > 0 and step_breakdowns:
            prev_breakdowns = [b for b in step_breakdowns if b[0] == max_ep and (b[1] == max_idx - 1 or b[1] == max_idx - 2)]
            if prev_breakdowns:
                b_prev = max(prev_breakdowns, key=lambda x: x[8])
                log_print(f"  [Previous step] Ep {max_ep} step {b_prev[1]}: get_mask={b_prev[2]:.3f}s process={b_prev[4]:.3f}s build_obs={b_prev[6]:.3f}s total={b_prev[8]:.3f}s")
        if max_idx > 0 and post_step_timings:
            prev_post = [p for p in post_step_timings if p[0] == max_ep and (p[1] == max_idx - 1 or p[1] == max_idx - 2)]
            if prev_post:
                post_prev = max(prev_post, key=lambda x: x[2])[2]
                log_print(f"  [Previous step] Ep {max_ep} step {max_idx - 1} POST_STEP (after _step_t5 to return): {post_prev:.3f}s")
        if max_idx > 0 and after_step_increment_timings:
            prev_after = [a for a in after_step_increment_timings if a[0] == max_ep and (a[1] == max_idx - 1 or a[1] == max_idx - 2)]
            if prev_after:
                after_prev = max(prev_after, key=lambda x: x[2])[2]
                log_print(f"  [Previous step] Ep {max_ep} step {max_idx - 1} AFTER_STEP_INCREMENT (log_action to return): {after_prev:.3f}s")
    elif step_timings is not None and len(step_timings) == 0:
        log_print("")
        log_print("Step Durations (from debug.log): no STEP_TIMING data")
    # LOG TEMPORAIRE: Wrapper step timing when we have data but no STEP_TIMING (e.g. debug.log only from wrapper)
    if wrapper_step_timings and not step_timings:
        log_print("")
        all_wrap = [w[2] for w in wrapper_step_timings]
        n_wrap = len(all_wrap)
        avg_wrap = sum(all_wrap) / n_wrap if n_wrap else 0.0
        max_wrap = max(all_wrap) if all_wrap else 0.0
        log_print(f"Wrapper step timing (from debug.log, --debug): avg={avg_wrap:.3f}s, max={max_wrap:.3f}s (n={n_wrap})")
    # If step_timings is None, debug.log was missing → skip silently to match "same stats" only when data exists

    # Predict durations (model.predict(), from debug.log PREDICT_TIMING when --debug)
    if predict_timings:
        log_print("")
        all_pred = [d for _e, _i, d in predict_timings]
        n_pred = len(all_pred)
        avg_pred = sum(all_pred) / n_pred if n_pred else 0.0
        min_pred = min(all_pred) if all_pred else 0.0
        max_pred = max(all_pred) if all_pred else 0.0
        min_ep_p, min_idx_p, min_val_p = min(predict_timings, key=lambda t: t[2])
        max_ep_p, max_idx_p, max_val_p = max(predict_timings, key=lambda t: t[2])
        log_print(f"Predict Durations (from debug.log): {avg_pred:.3f}s (average), Min: {min_pred:.3f}s, Max: {max_pred:.3f}s (n={n_pred} calls)")
        log_print(f"  Min: {min_val_p:.3f}s (Episode {min_ep_p}, step index {min_idx_p})")
        log_print(f"  Max: {max_val_p:.3f}s (Episode {max_ep_p}, step index {max_idx_p})")
    elif predict_timings is not None and len(predict_timings) == 0:
        log_print("")
        log_print("Predict Durations (from debug.log): no PREDICT_TIMING data")

    # LOG TEMPORAIRE: Get-mask durations (get_action_mask in bot loop, from debug.log when --debug)
    if get_mask_timings:
        log_print("")
        all_gm = [d for _e, _i, d in get_mask_timings]
        n_gm = len(all_gm)
        avg_gm = sum(all_gm) / n_gm if n_gm else 0.0
        min_gm = min(all_gm) if all_gm else 0.0
        max_gm = max(all_gm) if all_gm else 0.0
        min_ep_gm, min_idx_gm, min_val_gm = min(get_mask_timings, key=lambda t: t[2])
        max_ep_gm, max_idx_gm, max_val_gm = max(get_mask_timings, key=lambda t: t[2])
        log_print(f"Get-Mask Durations (from debug.log, --debug): {avg_gm:.3f}s (average), Min: {min_gm:.3f}s, Max: {max_gm:.3f}s (n={n_gm} calls)")
        log_print(f"  Min: {min_val_gm:.3f}s (Episode {min_ep_gm}, step index {min_idx_gm})")
        log_print(f"  Max: {max_val_gm:.3f}s (Episode {max_ep_gm}, step index {max_idx_gm})")
    elif get_mask_timings is not None and len(get_mask_timings) == 0:
        log_print("")
        log_print("Get-Mask Durations (from debug.log): no GET_MASK_TIMING data (run with --debug)")

    # LOG TEMPORAIRE: Console-log write durations (write console_logs to debug.log; only when --debug)
    if console_log_write_timings:
        log_print("")
        all_cl = [d for _e, _i, d, _l in console_log_write_timings]
        n_cl = len(all_cl)
        avg_cl = sum(all_cl) / n_cl if n_cl else 0.0
        min_cl = min(all_cl) if all_cl else 0.0
        max_cl = max(all_cl) if all_cl else 0.0
        min_ep_cl, min_idx_cl, min_val_cl, _ = min(console_log_write_timings, key=lambda t: t[2])
        max_ep_cl, max_idx_cl, max_val_cl, max_lines = max(console_log_write_timings, key=lambda t: t[2])
        log_print(f"Console-Log Write (from debug.log, --debug): {avg_cl:.3f}s (average), Min: {min_cl:.3f}s, Max: {max_cl:.3f}s (n={n_cl} writes)")
        log_print(f"  Min: {min_val_cl:.3f}s (Episode {min_ep_cl}, step index {min_idx_cl})")
        log_print(f"  Max: {max_val_cl:.3f}s (Episode {max_ep_cl}, step index {max_idx_cl}, lines={max_lines})")
    elif console_log_write_timings is not None and len(console_log_write_timings) == 0:
        log_print("")
        log_print("Console-Log Write (from debug.log): no CONSOLE_LOG_WRITE_TIMING data (run with --debug)")

    # LOG TEMPORAIRE: Step breakdown (get_mask, convert, process, replay, build_obs, reward) from debug.log when --debug
    if step_breakdowns:
        log_print("")
        n_br = len(step_breakdowns)
        avg_get = sum(r[2] for r in step_breakdowns) / n_br
        avg_convert = sum(r[3] for r in step_breakdowns) / n_br
        avg_process = sum(r[4] for r in step_breakdowns) / n_br
        avg_replay = sum(r[5] for r in step_breakdowns) / n_br
        avg_build_obs = sum(r[6] for r in step_breakdowns) / n_br
        avg_reward = sum(r[7] for r in step_breakdowns) / n_br
        avg_total = sum(r[8] for r in step_breakdowns) / n_br
        segs = [
            ("get_mask", avg_get), ("convert", avg_convert), ("process", avg_process),
            ("replay", avg_replay), ("build_obs", avg_build_obs), ("reward", avg_reward)
        ]
        max_seg = max(segs, key=lambda x: x[1])
        log_print(f"Step Breakdown (from debug.log, --debug): avg total={avg_total:.3f}s (n={n_br})")
        log_print(f"  Avg: get_mask={avg_get:.3f}s convert={avg_convert:.3f}s process={avg_process:.3f}s replay={avg_replay:.3f}s build_obs={avg_build_obs:.3f}s reward={avg_reward:.3f}s")
        log_print(f"  Segment with highest avg: {max_seg[0]} ({max_seg[1]:.3f}s)")
        slowest = max(step_breakdowns, key=lambda r: r[8])
        log_print(f"  Slowest step: Episode {slowest[0]}, step_index {slowest[1]}: total={slowest[8]:.3f}s (get_mask={slowest[2]:.3f} convert={slowest[3]:.3f} process={slowest[4]:.3f} replay={slowest[5]:.3f} build_obs={slowest[6]:.3f} reward={slowest[7]:.3f})")
    elif step_breakdowns is not None and len(step_breakdowns) == 0:
        log_print("")
        log_print("Step Breakdown (from debug.log): no STEP_BREAKDOWN data (run with --debug)")

    # LOG TEMPORAIRE: Cascade timings (phase_*_start in cascade loop; only when --debug)
    if cascade_timings:
        log_print("")
        n_casc = len(cascade_timings)
        all_casc_dur = [r[4] for r in cascade_timings]
        avg_casc = sum(all_casc_dur) / n_casc if n_casc else 0.0
        max_casc = max(all_casc_dur) if all_casc_dur else 0.0
        slowest_casc = max(cascade_timings, key=lambda r: r[4])
        # Group by (from_phase, to_phase) for avg
        by_trans: Dict[Tuple[str, str], List[float]] = defaultdict(list)
        for _ep, _num, fp, tp, dur in cascade_timings:
            by_trans[(fp, tp)].append(dur)
        trans_avg = [(k, sum(v) / len(v), len(v)) for k, v in by_trans.items()]
        trans_avg.sort(key=lambda x: -x[1])
        log_print(f"Cascade (from debug.log, --debug): {avg_casc:.3f}s avg per transition, max={max_casc:.3f}s (n={n_casc})")
        log_print(f"  Slowest: Episode {slowest_casc[0]}, cascade #{slowest_casc[1]} {slowest_casc[2]}->{slowest_casc[3]}: {slowest_casc[4]:.3f}s")
        if trans_avg:
            log_print(f"  By transition (avg): {'; '.join(f'{k[0]}->{k[1]}={v:.3f}s (n={c})' for (k, v, c) in trans_avg[:6])}")
    elif cascade_timings is not None and len(cascade_timings) == 0:
        log_print("")
        log_print("Cascade (from debug.log): no CASCADE_TIMING data (run with --debug)")
'''

    # RÉSULTATS DES PARTIES
    log_print("\n" + "=" * 80)
    log_print("📊 BOT EVALUATION RESULTS")
    log_print("=" * 80)
    _seat_counts = require_key(stats, 'agent_seat_counts')
    log_print(
        f"Siège de l'agent : P1 sur {_seat_counts[1]} épisode(s), "
        f"P2 sur {_seat_counts[2]} — les colonnes ci-dessous suivent l'AGENT, pas le numéro "
        f"de joueur (controlled_player_mode accepte p2 et random)."
    )
    log_print("-" * 80)
    log_print(f"WIN METHODS {'Agent Wins':>24} {'Bot Wins':>18}")
    log_print("-" * 80)

    _wm_seat = require_key(stats, 'win_methods_by_seat')
    p1_total = sum(_wm_seat['agent'].values())
    p2_total = sum(_wm_seat['bot'].values())
    draws = stats['win_methods'][-1]['draw']

    for method in ['elimination', 'objectives', 'value_tiebreaker']:
        p1_count = require_key(_wm_seat['agent'], method)
        p2_count = require_key(_wm_seat['bot'], method)
        p1_pct = (p1_count / p1_total * 100) if p1_total > 0 else 0
        p2_pct = (p2_count / p2_total * 100) if p2_total > 0 else 0
        method_display = method.replace('_', ' ').title()
        log_print(f"{method_display:<20} {p1_count:6d} ({p1_pct:5.1f}%)   {p2_count:6d} ({p2_pct:5.1f}%)")
    
    log_print("-" * 80)
    total_games = p1_total + p2_total + draws
    p1_pct = (p1_total / total_games * 100) if total_games > 0 else 0
    p2_pct = (p2_total / total_games * 100) if total_games > 0 else 0
    draw_pct = (draws / total_games * 100) if total_games > 0 else 0
    log_print(f"{'TOTAL WINS':<20} {p1_total:6d} ({p1_pct:5.1f}%)   {p2_total:6d} ({p2_pct:5.1f}%)")
    log_print(f"{'DRAWS':<20} {draws:6d} ({draw_pct:5.1f}%)")
    
    # VICTORY POINTS (OBJECTIVES)
    log_print("\n" + "-" * 80)
    log_print("VICTORY POINTS (OBJECTIVES)")
    log_print("-" * 80)
    vp_p1 = require_key(stats, 'victory_points_values_by_seat')['agent']
    vp_p2 = require_key(stats, 'victory_points_values_by_seat')['bot']
    if vp_p1 and vp_p2:
        vp_p1_min = min(vp_p1)
        vp_p1_max = max(vp_p1)
        vp_p1_avg = sum(vp_p1) / len(vp_p1)
        vp_p2_min = min(vp_p2)
        vp_p2_max = max(vp_p2)
        vp_p2_avg = sum(vp_p2) / len(vp_p2)
        log_print(f"{'Camp':<10} {'Min':>8} {'Avg':>8} {'Max':>8}")
        log_print(f"{'Agent':<10} {vp_p1_min:8.2f} {vp_p1_avg:8.2f} {vp_p1_max:8.2f}")
        log_print(f"{'Bot':<10} {vp_p2_min:8.2f} {vp_p2_avg:8.2f} {vp_p2_max:8.2f}")
    else:
        log_print("No victory point data recorded (check primary_objectives in scenarios).")

    # WINS BY SCENARIO
    if stats['wins_by_scenario']:
        log_print("-" * 80)
        log_print(f"WINS BY SCENARIO {'Agent':>37} {'Bot':>13} {'Draws':>12}")
        log_print("-" * 80)

        # Le libellé doit rester UNIQUE. `bot-(\d+)` seul ne l'est pas : un même bot est joué sur
        # plusieurs TERRAINS (`bot_evaluation._materialize_eval_scenario_refs` matérialise un
        # scénario par `wall_ref` et signe le fichier d'un sha1 tronqué), si bien que le run du
        # 2026-08-11 affichait huit séries de 75 épisodes sous quatre libellés répétés deux fois —
        # deux cartes fusionnées à l'œil, sans qu'aucune colonne ne le dise. Le hash est conservé :
        # il est stable d'un run à l'autre (il ne dépend que du chemin et du `wall_ref`), donc deux
        # rapports restent comparables ligne à ligne.
        # Tri par LIBELLÉ et non plus par total : les séries d'un même bot se suivent, et le tri par
        # total n'ordonnait plus rien dès lors que chaque scénario reçoit le même nombre d'épisodes.
        scenario_totals = []
        for scenario, wins in stats['wins_by_scenario'].items():
            total = wins['agent'] + wins['bot'] + wins['draws']
            bot_match = re.search(r'bot-(\d+)(?:__([0-9a-f]{6,}))?', scenario, re.IGNORECASE)
            if bot_match:
                label = f"bot-{bot_match.group(1)}"
                if bot_match.group(2):
                    label = f"{label}__{bot_match.group(2)[:8]}"
            else:
                label = scenario[:39]
            scenario_totals.append((label, wins, total))
        scenario_totals.sort(key=lambda x: x[0])

        for scenario_display, wins, total in scenario_totals:
            # Colonnes au SIÈGE de l'agent : `p1`/`p2` restent renseignés (diagnostic de siège),
            # mais les afficher ici mélangeait les épisodes où l'agent tient P2.
            p1_count = wins['agent']
            p2_count = wins['bot']
            draws_count = wins['draws']
            p1_pct = (p1_count / total * 100) if total > 0 else 0
            p2_pct = (p2_count / total * 100) if total > 0 else 0
            draws_pct = (draws_count / total * 100) if total > 0 else 0
            log_print(f"{scenario_display:<40} {p1_count:5d} ({p1_pct:4.1f}%) {p2_count:5d} ({p2_pct:4.1f}%) {draws_count:5d} ({draws_pct:4.1f}%)")
    
    # TURN DISTRIBUTION
    log_print("\n" + "-" * 80)
    log_print("TURN DISTRIBUTION")
    log_print("-" * 80)
    if stats['turns_distribution']:
        for turn in sorted(stats['turns_distribution'].keys()):
            count = stats['turns_distribution'][turn]
            pct = (count / stats['total_episodes'] * 100) if stats['total_episodes'] > 0 else 0
            log_print(f"Turn {turn}: {count:3d} games ({pct:5.1f}%)")
    else:
        log_print("No turn data recorded.")
    
    # ACTIONS BY TYPE
    _table_header("ACTIONS BY TYPE")
    
    all_actions = set(stats['actions_by_player'][1].keys()) | set(stats['actions_by_player'][2].keys())
    action_totals = [(a, stats['actions_by_player'][1][a] + stats['actions_by_player'][2][a])
                     for a in all_actions]
    action_totals.sort(key=lambda x: -x[1])
    
    agent_total = sum(stats['actions_by_player'][1].values())
    bot_total = sum(stats['actions_by_player'][2].values())
    
    for action_type, _ in action_totals:
        agent_count = stats['actions_by_player'][1][action_type]
        bot_count = stats['actions_by_player'][2][action_type]
        agent_pct = (agent_count / agent_total * 100) if agent_total > 0 else 0
        bot_pct = (bot_count / bot_total * 100) if bot_total > 0 else 0
        _table_row(
            action_type,
            f"{agent_count:6d} ({agent_pct:5.1f}%)",
            f"{bot_count:6d} ({bot_pct:5.1f}%)",
        )
    
    # SHOOTING PHASE BEHAVIOR
    _table_header("SHOOTING BEHAVIOR")
    
    agent_shoot_total = (stats['shoot_vs_wait_by_player'][1]['shoot'] +
                        stats['shoot_vs_wait_by_player'][1]['wait'] +
                        stats['shoot_vs_wait_by_player'][1]['skip'] +
                        stats['shoot_vs_wait_by_player'][1]['advance'])
    bot_shoot_total = (stats['shoot_vs_wait_by_player'][2]['shoot'] +
                      stats['shoot_vs_wait_by_player'][2]['wait'] +
                      stats['shoot_vs_wait_by_player'][2]['skip'] +
                      stats['shoot_vs_wait_by_player'][2]['advance'])

    for action in ['shoot', 'skip', 'advance']:
        agent_count = stats['shoot_vs_wait_by_player'][1][action]
        bot_count = stats['shoot_vs_wait_by_player'][2][action]
        agent_pct = (agent_count / agent_shoot_total * 100) if agent_shoot_total > 0 else 0
        bot_pct = (bot_count / bot_shoot_total * 100) if bot_shoot_total > 0 else 0
        _table_row(
            action.capitalize(),
            f"{agent_count:6d} ({agent_pct:5.1f}%)",
            f"{bot_count:6d} ({bot_pct:5.1f}%)",
        )
    agent_wait_with = stats['shoot_vs_wait_by_player'][1]['wait_with_targets']
    bot_wait_with = stats['shoot_vs_wait_by_player'][2]['wait_with_targets']
    agent_wait_with_pct = (agent_wait_with / agent_shoot_total * 100) if agent_shoot_total > 0 else 0
    bot_wait_with_pct = (bot_wait_with / bot_shoot_total * 100) if bot_shoot_total > 0 else 0
    _table_row(
        "Wait (targets)",
        f"{agent_wait_with:6d} ({agent_wait_with_pct:5.1f}%)",
        f"{bot_wait_with:6d} ({bot_wait_with_pct:5.1f}%)",
    )
    
    agent_wait_no = stats['shoot_vs_wait_by_player'][1]['wait_no_targets']
    bot_wait_no = stats['shoot_vs_wait_by_player'][2]['wait_no_targets']
    agent_wait_no_pct = (agent_wait_no / agent_shoot_total * 100) if agent_shoot_total > 0 else 0
    bot_wait_no_pct = (bot_wait_no / bot_shoot_total * 100) if bot_shoot_total > 0 else 0
    _table_row(
        "Wait (no targets)",
        f"{agent_wait_no:6d} ({agent_wait_no_pct:5.1f}%)",
        f"{bot_wait_no:6d} ({bot_wait_no_pct:5.1f}%)",
    )
    
    agent_shots_after_advance = stats['shots_after_advance'][1]
    bot_shots_after_advance = stats['shots_after_advance'][2]
    agent_pct_after_advance = (agent_shots_after_advance / agent_shoot_total * 100) if agent_shoot_total > 0 else 0
    bot_pct_after_advance = (bot_shots_after_advance / bot_shoot_total * 100) if bot_shoot_total > 0 else 0
    _table_row(
        "Shoot+Advance",
        f"{agent_shots_after_advance:6d} ({agent_pct_after_advance:5.1f}%)",
        f"{bot_shots_after_advance:6d} ({bot_pct_after_advance:5.1f}%)",
    )
    
    # CLOSE_QUARTERS WEAPON SHOTS
    _table_header("CLOSE_QUARTERS WEAPON SHOTS BY ENGAGEMENT (10.06)")
    agent_close_quarters_eng = stats['close_quarters_shots'][1]['engaged_target']
    bot_close_quarters_eng = stats['close_quarters_shots'][2]['engaged_target']
    agent_close_quarters_not_eng = stats['close_quarters_shots'][1]['unengaged_target']
    bot_close_quarters_not_eng = stats['close_quarters_shots'][2]['unengaged_target']
    agent_close_quarters_total = agent_close_quarters_eng + agent_close_quarters_not_eng
    bot_close_quarters_total = bot_close_quarters_eng + bot_close_quarters_not_eng
    
    agent_close_quarters_eng_pct = (agent_close_quarters_eng / agent_close_quarters_total * 100) if agent_close_quarters_total > 0 else 0
    bot_close_quarters_eng_pct = (bot_close_quarters_eng / bot_close_quarters_total * 100) if bot_close_quarters_total > 0 else 0
    agent_close_quarters_not_eng_pct = (agent_close_quarters_not_eng / agent_close_quarters_total * 100) if agent_close_quarters_total > 0 else 0
    bot_close_quarters_not_eng_pct = (bot_close_quarters_not_eng / bot_close_quarters_total * 100) if bot_close_quarters_total > 0 else 0
    
    _table_row(
        "CLOSE_QUARTERS shots (target engaged):",
        f"{agent_close_quarters_eng:6d} ({agent_close_quarters_eng_pct:5.1f}%)",
        f"{bot_close_quarters_eng:6d} ({bot_close_quarters_eng_pct:5.1f}%)",
    )
    _table_row(
        "CLOSE_QUARTERS shots (target unengaged):",
        f"{agent_close_quarters_not_eng:6d} ({agent_close_quarters_not_eng_pct:5.1f}%)",
        f"{bot_close_quarters_not_eng:6d} ({bot_close_quarters_not_eng_pct:5.1f}%)",
    )
    _table_row("Total CLOSE_QUARTERS shots:", _fmt_count(agent_close_quarters_total), _fmt_count(bot_close_quarters_total))
    
    agent_engaged_non_cq = stats['engaged_shot_with_non_close_quarters_weapon'][1]
    bot_engaged_non_cq = stats['engaged_shot_with_non_close_quarters_weapon'][2]
    _table_row(
        "Non-CLOSE_QUARTERS shots while engaged:",
        _fmt_count(agent_engaged_non_cq),
        _fmt_count(bot_engaged_non_cq),
    )

    _table_header("SHOOTING VALIDITY")
    agent_invalid_total = (
        stats['shoot_invalid'][1]['out_of_range'] +
        stats['shoot_invalid'][1]['engaged_non_close_quarters']
    )
    bot_invalid_total = (
        stats['shoot_invalid'][2]['out_of_range'] +
        stats['shoot_invalid'][2]['engaged_non_close_quarters']
    )
    agent_shot_total = stats['shoot_invalid'][1]['total']
    bot_shot_total = stats['shoot_invalid'][2]['total']
    agent_invalid_pct = (agent_invalid_total / agent_shot_total * 100) if agent_shot_total > 0 else 0
    bot_invalid_pct = (bot_invalid_total / bot_shot_total * 100) if bot_shot_total > 0 else 0
    _table_row(
        "Invalid shots total:",
        f"{agent_invalid_total:6d} ({agent_invalid_pct:5.1f}%)",
        f"{bot_invalid_total:6d} ({bot_invalid_pct:5.1f}%)",
    )
    _table_row(
        "Out of range:",
        _fmt_count(stats['shoot_invalid'][1]['out_of_range']),
        _fmt_count(stats['shoot_invalid'][2]['out_of_range']),
    )
    _table_row(
        "Engaged, non-close_quarters weapon:",
        _fmt_count(stats['shoot_invalid'][1]['engaged_non_close_quarters']),
        _fmt_count(stats['shoot_invalid'][2]['engaged_non_close_quarters']),
    )
    if stats['first_error_lines']['shoot_invalid'][1]:
        first_err = stats['first_error_lines']['shoot_invalid'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['first_error_lines']['shoot_invalid'][2]:
        first_err = stats['first_error_lines']['shoot_invalid'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    
    # WAIT BEHAVIOR
    log_print("\n" + "-" * 80)
    _table_header("WAIT BEHAVIOR BY PHASE")
    agent_move_wait = stats['wait_by_phase'][1]['move_wait']
    bot_move_wait = stats['wait_by_phase'][2]['move_wait']
    agent_wait_los = stats['wait_by_phase'][1]['wait_with_los']
    bot_wait_los = stats['wait_by_phase'][2]['wait_with_los']
    agent_wait_no_los = stats['wait_by_phase'][1]['wait_no_los']
    bot_wait_no_los = stats['wait_by_phase'][2]['wait_no_los']
    
    _table_row("MOVE phase waits:", _fmt_count(agent_move_wait), _fmt_count(bot_move_wait))
    _table_row("SHOOT waits (enemies in LOS):", _fmt_count(agent_wait_los), _fmt_count(bot_wait_los))
    _table_row("SHOOT waits (no LOS):", _fmt_count(agent_wait_no_los), _fmt_count(bot_wait_no_los))
    
    # TARGET PRIORITY
    log_print("\n" + "-" * 80)
    _table_header("TARGET PRIORITY ANALYSIS")
    
    agent_bad = stats['target_priority'][1]['shots_at_full_hp_while_wounded_in_los']
    bot_bad = stats['target_priority'][2]['shots_at_full_hp_while_wounded_in_los']
    agent_good = stats['target_priority'][1]['shots_at_wounded_in_los']
    bot_good = stats['target_priority'][2]['shots_at_wounded_in_los']
    agent_total_shots = stats['target_priority'][1]['total_shots']
    bot_total_shots = stats['target_priority'][2]['total_shots']
    
    agent_bad_pct = (agent_bad / agent_total_shots * 100) if agent_total_shots > 0 else 0
    bot_bad_pct = (bot_bad / bot_total_shots * 100) if bot_total_shots > 0 else 0
    agent_good_pct = (agent_good / agent_total_shots * 100) if agent_total_shots > 0 else 0
    bot_good_pct = (bot_good / bot_total_shots * 100) if bot_total_shots > 0 else 0
    
    _table_row(
        "FAILURES (shot full HP while wounded in LOS):",
        f"{agent_bad:6d} ({agent_bad_pct:5.1f}%)",
        f"{bot_bad:6d} ({bot_bad_pct:5.1f}%)",
    )
    _table_row(
        "SUCCESS (shot wounded or no wounded in LOS):",
        f"{agent_good:6d} ({agent_good_pct:5.1f}%)",
        f"{bot_good:6d} ({bot_good_pct:5.1f}%)",
    )
    _table_row("Total shots:", _fmt_count(agent_total_shots), _fmt_count(bot_total_shots))
    
    # DEATH ORDER
    log_print("\n" + "-" * 80)
    log_print("ENEMY DEATH ORDER ANALYSIS")
    log_print("-" * 80)
    
    if stats['death_orders']:
        death_order_counter = Counter()
        for death_order in stats['death_orders']:
            units_killed = tuple(f"{unit_type}({unit_id})" for player, unit_id, unit_type in death_order)
            if units_killed:
                death_order_counter[units_killed] += 1
        
        log_print(f"Total episodes with kills: {len(stats['death_orders'])}")
        log_print(f"\nMost common death orders:")
        for order, count in death_order_counter.most_common(10):
            pct = (count / len(stats['death_orders']) * 100)
            order_str = " -> ".join(order)
            log_print(f"  {order_str}: {count} times ({pct:.1f}%)")
        
        player_kills = {1: 0, 2: 0}
        for death_order in stats['death_orders']:
            for player, unit_id, unit_type in death_order:
                player_kills[player] += 1
        log_print(f"\nKills by player:")
        log_print(f"  Joueur 1 kills: {player_kills[1]}")
        log_print(f"  Joueur 2 kills:   {player_kills[2]}")
    else:
        log_print("No kills recorded in any episode.")
    
    log_print("\n" + "=" * 80)
    log_print("DEBUGGING")
    log_print("=" * 80)
    log_print("Sections:")
    log_print("  1.1 MOVEMENT ERRORS")
    log_print("  1.2 SHOOTING ERRORS")
    log_print("  1.3 CHARGE ERRORS")
    log_print("  1.4 FIGHT ERRORS")
    log_print("  1.5 ACTION PHASE ACCURACY")
    log_print("  1.6 DOUBLE-ACTIVATION PAR PHASE")
    log_print("  1.7 SPECIAL RULES USAGE")
    log_print("  1.8 WEAPONS RULES USAGE")
    log_print("  2.1 DEAD UNITS INTERACTIONS")
    log_print("  2.2 POSITION / LOG COHERENCE")
    log_print("  2.3 DMG ISSUES")
    log_print("  2.4 EPISODES STATISTICS")
    log_print("  2.5 EPISODES ENDING")
    log_print("  2.6 SAMPLE MISSING")
    log_print("  2.7 CORE ISSUES")

    # MOVEMENT ERRORS
    if True:
        active_debug_section = "1.1"
        log_print("\n" + "-" * 80)
        _table_header("1.1 MOVEMENT ERRORS")
        agent_walls = stats['wall_collisions'][1]
        bot_walls = stats['wall_collisions'][2]
        _table_row("Moves into walls:", _fmt_count(agent_walls), _fmt_count(bot_walls))
        if agent_walls > 0 and stats['first_error_lines']['wall_collisions'][1]:
            first_err = stats['first_error_lines']['wall_collisions'][1]
            log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        if bot_walls > 0 and stats['first_error_lines']['wall_collisions'][2]:
            first_err = stats['first_error_lines']['wall_collisions'][2]
            log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        agent_move_adj = stats['move_to_adjacent_enemy'][1]
        bot_move_adj = stats['move_to_adjacent_enemy'][2]
        _table_row("Moves to adjacent enemy:", _fmt_count(agent_move_adj), _fmt_count(bot_move_adj))
        if agent_move_adj > 0 and stats['first_error_lines']['move_to_adjacent_enemy'][1]:
            first_err = stats['first_error_lines']['move_to_adjacent_enemy'][1]
            log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
            log_print(f"    Engaged after move: {_offenders_str(first_err)}")
        if bot_move_adj > 0 and stats['first_error_lines']['move_to_adjacent_enemy'][2]:
            first_err = stats['first_error_lines']['move_to_adjacent_enemy'][2]
            log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
            log_print(f"    Engaged after move: {_offenders_str(first_err)}")
        agent_adj_before_move = stats['move_adjacent_before_non_flee'][1]
        bot_adj_before_move = stats['move_adjacent_before_non_flee'][2]
        _table_row("Move with adjacent_before:", _fmt_count(agent_adj_before_move), _fmt_count(bot_adj_before_move))
        if agent_adj_before_move > 0 and stats['first_error_lines']['move_adjacent_before_non_flee'][1]:
            first_err = stats['first_error_lines']['move_adjacent_before_non_flee'][1]
            log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        if bot_adj_before_move > 0 and stats['first_error_lines']['move_adjacent_before_non_flee'][2]:
            first_err = stats['first_error_lines']['move_adjacent_before_non_flee'][2]
            log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        agent_move_over = stats['move_distance_over_limit']['move'][1]
        bot_move_over = stats['move_distance_over_limit']['move'][2]
        _table_row("Move au-dela du budget:", _fmt_count(agent_move_over), _fmt_count(bot_move_over))
        if agent_move_over > 0 and stats['first_error_lines']['move_distance_over_limit']['move'][1]:
            first_err = stats['first_error_lines']['move_distance_over_limit']['move'][1]
            log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        if bot_move_over > 0 and stats['first_error_lines']['move_distance_over_limit']['move'][2]:
            first_err = stats['first_error_lines']['move_distance_over_limit']['move'][2]
            log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        # 09.07 FALL-BACK MOVE — les trois volets contrôlables. Ils vivent dans la section MOVE
        # (et pas ailleurs) parce que le fall-back EST un type de mouvement de la phase de
        # Mouvement au même titre que le normal move et l'advance (09.02, « Select Move Type »).
        agent_flee_over = stats['move_distance_over_limit']['flee'][1]
        bot_flee_over = stats['move_distance_over_limit']['flee'][2]
        _table_row("Fall-back au-dela du budget:", _fmt_count(agent_flee_over), _fmt_count(bot_flee_over))
        if agent_flee_over > 0 and stats['first_error_lines']['move_distance_over_limit']['flee'][1]:
            first_err = stats['first_error_lines']['move_distance_over_limit']['flee'][1]
            log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        if bot_flee_over > 0 and stats['first_error_lines']['move_distance_over_limit']['flee'][2]:
            first_err = stats['first_error_lines']['move_distance_over_limit']['flee'][2]
            log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        agent_flee_unengaged = stats['flee_from_unengaged'][1]
        bot_flee_unengaged = stats['flee_from_unengaged'][2]
        _table_row("Fall-back sans engagement:", _fmt_count(agent_flee_unengaged), _fmt_count(bot_flee_unengaged))
        if agent_flee_unengaged > 0 and stats['first_error_lines']['flee_from_unengaged'][1]:
            first_err = stats['first_error_lines']['flee_from_unengaged'][1]
            log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        if bot_flee_unengaged > 0 and stats['first_error_lines']['flee_from_unengaged'][2]:
            first_err = stats['first_error_lines']['flee_from_unengaged'][2]
            log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        agent_flee_engaged = stats['flee_still_engaged'][1]
        bot_flee_engaged = stats['flee_still_engaged'][2]
        _table_row("Fall-back finit engage:", _fmt_count(agent_flee_engaged), _fmt_count(bot_flee_engaged))
        if agent_flee_engaged > 0 and stats['first_error_lines']['flee_still_engaged'][1]:
            first_err = stats['first_error_lines']['flee_still_engaged'][1]
            log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        if bot_flee_engaged > 0 and stats['first_error_lines']['flee_still_engaged'][2]:
            first_err = stats['first_error_lines']['flee_still_engaged'][2]
            log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        agent_mas_over = stats['move_after_shooting_distance_over_limit'][1]
        bot_mas_over = stats['move_after_shooting_distance_over_limit'][2]
        _table_row("MoveAfterShoot > rule dist:", _fmt_count(agent_mas_over), _fmt_count(bot_mas_over))
        if agent_mas_over > 0 and stats['first_error_lines']['move_after_shooting_distance_over_limit'][1]:
            first_err = stats['first_error_lines']['move_after_shooting_distance_over_limit'][1]
            log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        if bot_mas_over > 0 and stats['first_error_lines']['move_after_shooting_distance_over_limit'][2]:
            first_err = stats['first_error_lines']['move_after_shooting_distance_over_limit'][2]
            log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        reactive_stats = require_key(stats, 'reactive_move_stats')
        agent_reactive_applied = reactive_stats[1]['applied']
        bot_reactive_applied = reactive_stats[2]['applied']
        _table_row("Reactive moves applied:", _fmt_count(agent_reactive_applied), _fmt_count(bot_reactive_applied))
        agent_reactive_declined = reactive_stats[1]['declined']
        bot_reactive_declined = reactive_stats[2]['declined']
        _table_row("Reactive moves declined:", _fmt_count(agent_reactive_declined), _fmt_count(bot_reactive_declined))
        agent_reactive_abnormal = reactive_stats[1]['abnormal']
        bot_reactive_abnormal = reactive_stats[2]['abnormal']
        _table_row("Reactive moves abnormal:", _fmt_count(agent_reactive_abnormal), _fmt_count(bot_reactive_abnormal))
        if agent_reactive_abnormal > 0 and stats['first_error_lines']['reactive_move_abnormal'][1]:
            first_err = stats['first_error_lines']['reactive_move_abnormal'][1]
            log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        if bot_reactive_abnormal > 0 and stats['first_error_lines']['reactive_move_abnormal'][2]:
            first_err = stats['first_error_lines']['reactive_move_abnormal'][2]
            log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        reactive_checks = require_key(stats, 'reactive_move_checks')
        agent_reactive_adj = reactive_checks['to_adjacent_enemy'][1]
        bot_reactive_adj = reactive_checks['to_adjacent_enemy'][2]
        _table_row("Reactive to adjacent enemy:", _fmt_count(agent_reactive_adj), _fmt_count(bot_reactive_adj))
        if agent_reactive_adj > 0 and stats['first_error_lines']['reactive_move_to_adjacent_enemy'][1]:
            first_err = stats['first_error_lines']['reactive_move_to_adjacent_enemy'][1]
            log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        if bot_reactive_adj > 0 and stats['first_error_lines']['reactive_move_to_adjacent_enemy'][2]:
            first_err = stats['first_error_lines']['reactive_move_to_adjacent_enemy'][2]
            log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        agent_reactive_wall = reactive_checks['into_wall'][1]
        bot_reactive_wall = reactive_checks['into_wall'][2]
        _table_row("Reactive into wall:", _fmt_count(agent_reactive_wall), _fmt_count(bot_reactive_wall))
        if agent_reactive_wall > 0 and stats['first_error_lines']['reactive_move_into_wall'][1]:
            first_err = stats['first_error_lines']['reactive_move_into_wall'][1]
            log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        if bot_reactive_wall > 0 and stats['first_error_lines']['reactive_move_into_wall'][2]:
            first_err = stats['first_error_lines']['reactive_move_into_wall'][2]
            log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        agent_reactive_over_roll = reactive_checks['distance_over_roll'][1]
        bot_reactive_over_roll = reactive_checks['distance_over_roll'][2]
        _table_row("Reactive au-dela du budget:", _fmt_count(agent_reactive_over_roll), _fmt_count(bot_reactive_over_roll))
        if agent_reactive_over_roll > 0 and stats['first_error_lines']['reactive_move_distance_over_roll'][1]:
            first_err = stats['first_error_lines']['reactive_move_distance_over_roll'][1]
            log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        if bot_reactive_over_roll > 0 and stats['first_error_lines']['reactive_move_distance_over_roll'][2]:
            first_err = stats['first_error_lines']['reactive_move_distance_over_roll'][2]
            log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    _coh = require_key(stats, 'squad_coherency_violations')
    _table_row("Coherence d'escouade (03.03):", _fmt_count(_coh[1]), _fmt_count(_coh[2]))
    for _p in (1, 2):
        _first = stats['first_error_lines']['squad_coherency_violations'][_p]
        if _coh[_p] > 0 and _first:
            log_print(f"  First P{_p} occurrence (Episode {_first['episode']}): {_first['line']}")
            log_print(f"    {_first['detail']}")
    # Conséquence de la ligne ci-dessus, et pas une faute : les figurines que le moteur retire à
    # l'étape End of Turn. Affiché même à 0 — c'est ce chiffre qui dit si le journal PORTE ces
    # retraits, or son absence a coûté deux fautes inventées (cf. `_log_end_of_turn_coherency_removals`).
    _coh_rm = require_key(stats, 'coherency_removals')
    _table_row("  dont figurines retirees (End of Turn):", _fmt_count(_coh_rm[1]), _fmt_count(_coh_rm[2]))
    _res_tm = require_key(stats, 'reserves_timeout_destroyed')
    _table_row("  dont escouades detruites reserves (20.04):", _fmt_count(_res_tm[1]), _fmt_count(_res_tm[2]))
    _render_rule_coverage(stats, "1.1", log_print)
    # SHOOTING ERRORS
    active_debug_section = "1.2"
    log_print("\n" + "-" * 80)
    _table_header("1.2 SHOOTING ERRORS")
    # DEUX contrôles distincts, DEUX lignes. Ils ont vécu agrégés sous « Tirs invalides », et un
    # lecteur (2026-08-12) a pris le total pour le seul compteur de portée : il a cherché un écart
    # de 11 entre son propre décompte et le rapport, écart qui n'existait pas. Un chiffre qu'on ne
    # peut pas rapprocher de sa source fait perdre plus de temps qu'il n'en fait gagner.
    # Le total reste affiché par la section « SHOOTING VALIDITY », qui le décompose déjà.
    agent_shoot_invalid = (
        stats['shoot_invalid'][1]['out_of_range'] +
        stats['shoot_invalid'][1]['engaged_non_close_quarters']
    )
    bot_shoot_invalid = (
        stats['shoot_invalid'][2]['out_of_range'] +
        stats['shoot_invalid'][2]['engaged_non_close_quarters']
    )
    _table_row(
        "Tirs hors portee (10.02):",
        _fmt_count(stats['shoot_invalid'][1]['out_of_range']),
        _fmt_count(stats['shoot_invalid'][2]['out_of_range']),
    )
    # Couverture RÉELLE de la ligne ci-dessus : les tirs qu'elle a renoncé à juger, faute de
    # connaître un seul socle de la cible. MÊME forme que les « lignes non verifiables » des
    # seuils de touche/blessure — sans elle, « 0 hors portée » ne distingue pas un contrôle qui
    # n'a rien trouvé d'un contrôle qui n'a rien regardé (résidu V9, fermé le 2026-08-12).
    _rng_unver = require_key(stats, 'shoot_range_unverifiable')
    _table_row(
        "  ↳ portees non jugees (cible sans socle):",
        _fmt_count(_rng_unver[1]), _fmt_count(_rng_unver[2]),
    )
    _table_row(
        "Tirs engage, arme non-close_quarters:",
        _fmt_count(stats['shoot_invalid'][1]['engaged_non_close_quarters']),
        _fmt_count(stats['shoot_invalid'][2]['engaged_non_close_quarters']),
    )
    if agent_shoot_invalid > 0 and stats['first_error_lines']['shoot_invalid'][1]:
        first_err = stats['first_error_lines']['shoot_invalid'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_shoot_invalid > 0 and stats['first_error_lines']['shoot_invalid'][2]:
        first_err = stats['first_error_lines']['shoot_invalid'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_shoot_over_rng = stats['shoot_over_rng_nb'][1]
    bot_shoot_over_rng = stats['shoot_over_rng_nb'][2]
    _table_row("Shots over RNG_NB:", _fmt_count(agent_shoot_over_rng), _fmt_count(bot_shoot_over_rng))
    if agent_shoot_over_rng > 0 and stats['first_error_lines']['shoot_over_rng_nb'][1]:
        first_err = stats['first_error_lines']['shoot_over_rng_nb'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_shoot_over_rng > 0 and stats['first_error_lines']['shoot_over_rng_nb'][2]:
        first_err = stats['first_error_lines']['shoot_over_rng_nb'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_shoot_combi = stats['shoot_combi_profile_conflicts'][1]
    bot_shoot_combi = stats['shoot_combi_profile_conflicts'][2]
    _table_row("COMBI profiles in same phase:", _fmt_count(agent_shoot_combi), _fmt_count(bot_shoot_combi))
    if agent_shoot_combi > 0 and stats['first_error_lines']['shoot_combi_profile_conflicts'][1]:
        first_err = stats['first_error_lines']['shoot_combi_profile_conflicts'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_shoot_combi > 0 and stats['first_error_lines']['shoot_combi_profile_conflicts'][2]:
        first_err = stats['first_error_lines']['shoot_combi_profile_conflicts'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    # "Shoot through wall" : ligne SUPPRIMEE avec le controle (voir shoot_handler.py) — LoS
    # ancre-a-ancre contraire a 06.01, sur des coords d'ancre d'escouade. Verification deplacee
    # dans tests/unit/engine/test_shoot_los_perfig_parity.py.
    phase_special_rule_usage = require_key(stats, 'special_rule_usage')
    phase_rule_to_units = require_key(stats, 'rule_to_units')
    agent_shoot_flee = stats['shoot_after_flee'][1]
    bot_shoot_flee = stats['shoot_after_flee'][2]
    _table_row("Shoot after flee:", _fmt_count(agent_shoot_flee), _fmt_count(bot_shoot_flee))
    agent_shoot_flee_rule_used = sum(
        phase_special_rule_usage[k][1] for k in phase_special_rule_usage if k[0] == "shoot_after_flee"
    )
    bot_shoot_flee_rule_used = sum(
        phase_special_rule_usage[k][2] for k in phase_special_rule_usage if k[0] == "shoot_after_flee"
    )
    _table_row(
        "Shoot after flee (rule):",
        _fmt_count(agent_shoot_flee_rule_used),
        _fmt_count(bot_shoot_flee_rule_used),
    )
    if agent_shoot_flee > 0 and stats['first_error_lines']['shoot_after_flee'][1]:
        first_err = stats['first_error_lines']['shoot_after_flee'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_shoot_flee > 0 and stats['first_error_lines']['shoot_after_flee'][2]:
        first_err = stats['first_error_lines']['shoot_after_flee'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_shoot_friendly = stats['shoot_at_friendly'][1]
    bot_shoot_friendly = stats['shoot_at_friendly'][2]
    _table_row("Shoot at friendly unit:", _fmt_count(agent_shoot_friendly), _fmt_count(bot_shoot_friendly))
    if agent_shoot_friendly > 0 and stats['first_error_lines']['shoot_at_friendly'][1]:
        first_err = stats['first_error_lines']['shoot_at_friendly'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_shoot_friendly > 0 and stats['first_error_lines']['shoot_at_friendly'][2]:
        first_err = stats['first_error_lines']['shoot_at_friendly'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_shoot_engaged = stats['shoot_at_engaged_enemy'][1]
    bot_shoot_engaged = stats['shoot_at_engaged_enemy'][2]
    _table_row("Shoot at engaged enemy:", _fmt_count(agent_shoot_engaged), _fmt_count(bot_shoot_engaged))
    for _pl in (1, 2):
        _n = stats['shoot_at_engaged_enemy'][_pl]
        first_err = stats['first_error_lines']['shoot_at_engaged_enemy'][_pl]
        if _n > 0 and first_err:
            log_print(f"  First P{_pl} occurrence (Episode {first_err['episode']}): {first_err['line']}")
            # NOMME l'unite qui engage la cible : jumeau du diagnostic 1.1. Sans elle, la ligne
            # ne se verifie pas a la lecture.
            log_print(f"    Target engaged with: {_offenders_str(first_err)}")
    _hit_result_rows(stats, "shoot_hit_result", "tir")
    _wound_threshold_rows(stats, "shoot_wound_threshold", "tir")
    agent_cq_unengaged_target = stats['close_quarters_shot_at_unengaged_target'][1]
    bot_cq_unengaged_target = stats['close_quarters_shot_at_unengaged_target'][2]
    _table_row(
        "Engaged shot at a unit not engaged with (10.06):",
        _fmt_count(agent_cq_unengaged_target),
        _fmt_count(bot_cq_unengaged_target),
    )
    if agent_cq_unengaged_target > 0 and stats['first_error_lines']['close_quarters_shot_at_unengaged_target'][1]:
        first_err = stats['first_error_lines']['close_quarters_shot_at_unengaged_target'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_cq_unengaged_target > 0 and stats['first_error_lines']['close_quarters_shot_at_unengaged_target'][2]:
        first_err = stats['first_error_lines']['close_quarters_shot_at_unengaged_target'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_engaged_non_cq = stats['engaged_shot_with_non_close_quarters_weapon'][1]
    bot_engaged_non_cq = stats['engaged_shot_with_non_close_quarters_weapon'][2]
    _table_row("Engaged shot with non-CLOSE_QUARTERS weapon:", _fmt_count(agent_engaged_non_cq), _fmt_count(bot_engaged_non_cq))
    agent_advance_after_shoot = stats['advance_after_shoot'][1]
    bot_advance_after_shoot = stats['advance_after_shoot'][2]
    _table_row("Advance after shoot:", _fmt_count(agent_advance_after_shoot), _fmt_count(bot_advance_after_shoot))
    if agent_advance_after_shoot > 0 and stats['first_error_lines']['advance_after_shoot'][1]:
        first_err = stats['first_error_lines']['advance_after_shoot'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_advance_after_shoot > 0 and stats['first_error_lines']['advance_after_shoot'][2]:
        first_err = stats['first_error_lines']['advance_after_shoot'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_advance_twice_shoot = stats['advance_twice_in_shoot_phase'][1]
    bot_advance_twice_shoot = stats['advance_twice_in_shoot_phase'][2]
    _table_row(
        "Advance twice in SHOOT:",
        _fmt_count(agent_advance_twice_shoot),
        _fmt_count(bot_advance_twice_shoot),
    )
    if agent_advance_twice_shoot > 0 and stats['first_error_lines']['advance_twice_in_shoot_phase'][1]:
        first_err = stats['first_error_lines']['advance_twice_in_shoot_phase'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_advance_twice_shoot > 0 and stats['first_error_lines']['advance_twice_in_shoot_phase'][2]:
        first_err = stats['first_error_lines']['advance_twice_in_shoot_phase'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_adv_over = stats['move_distance_over_limit']['advance'][1]
    bot_adv_over = stats['move_distance_over_limit']['advance'][2]
    _table_row("Advance au-dela du budget:", _fmt_count(agent_adv_over), _fmt_count(bot_adv_over))
    if agent_adv_over > 0 and stats['first_error_lines']['move_distance_over_limit']['advance'][1]:
        first_err = stats['first_error_lines']['move_distance_over_limit']['advance'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_adv_over > 0 and stats['first_error_lines']['move_distance_over_limit']['advance'][2]:
        first_err = stats['first_error_lines']['move_distance_over_limit']['advance'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_advance_adj = stats['advance_from_adjacent'][1]
    bot_advance_adj = stats['advance_from_adjacent'][2]
    _table_row("Advances from adjacent hex:", _fmt_count(agent_advance_adj), _fmt_count(bot_advance_adj))
    if agent_advance_adj > 0 and stats['first_error_lines']['advance_from_adjacent'][1]:
        first_err = stats['first_error_lines']['advance_from_adjacent'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_advance_adj > 0 and stats['first_error_lines']['advance_from_adjacent'][2]:
        first_err = stats['first_error_lines']['advance_from_adjacent'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    
    # CHARGE ERRORS
    active_debug_section = "1.3"
    log_print("\n" + "-" * 80)
    _table_header("1.3 CHARGE ERRORS")
    agent_charge_adj = stats['charge_from_adjacent'][1]
    bot_charge_adj = stats['charge_from_adjacent'][2]
    _table_row("Charges from adjacent hex:", _fmt_count(agent_charge_adj), _fmt_count(bot_charge_adj))
    if agent_charge_adj > 0 and stats['first_error_lines']['charge_from_adjacent'][1]:
        first_err = stats['first_error_lines']['charge_from_adjacent'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_charge_adj > 0 and stats['first_error_lines']['charge_from_adjacent'][2]:
        first_err = stats['first_error_lines']['charge_from_adjacent'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_charge_flee = stats['charge_invalid'][1]['fled']
    bot_charge_flee = stats['charge_invalid'][2]['fled']
    _table_row("Charges after flee:", _fmt_count(agent_charge_flee), _fmt_count(bot_charge_flee))
    agent_charge_flee_rule_used = sum(
        phase_special_rule_usage[k][1] for k in phase_special_rule_usage if k[0] == "charge_after_flee"
    )
    bot_charge_flee_rule_used = sum(
        phase_special_rule_usage[k][2] for k in phase_special_rule_usage if k[0] == "charge_after_flee"
    )
    _table_row(
        "Charge after flee (rule):",
        _fmt_count(agent_charge_flee_rule_used),
        _fmt_count(bot_charge_flee_rule_used),
    )
    agent_charge_adv_used = sum(stats['special_rule_usage'][k][1] for k in stats['special_rule_usage'] if k[0] == "charge_after_advance")
    bot_charge_adv_used = sum(stats['special_rule_usage'][k][2] for k in stats['special_rule_usage'] if k[0] == "charge_after_advance")
    _table_row(
        "Charge after advance (rule):",
        _fmt_count(agent_charge_adv_used),
        _fmt_count(bot_charge_adv_used),
    )
    agent_charge_adv = stats['charge_invalid'][1]['advanced']
    bot_charge_adv = stats['charge_invalid'][2]['advanced']
    _table_row("Charges after advance:", _fmt_count(agent_charge_adv), _fmt_count(bot_charge_adv))
    agent_charge_over = stats['charge_invalid'][1]['distance_over_roll']
    bot_charge_over = stats['charge_invalid'][2]['distance_over_roll']
    _table_row("Charge au-dela du budget:", _fmt_count(agent_charge_over), _fmt_count(bot_charge_over))
    if stats['first_error_lines']['charge_invalid'][1]:
        first_err = stats['first_error_lines']['charge_invalid'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['first_error_lines']['charge_invalid'][2]:
        first_err = stats['first_error_lines']['charge_invalid'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")

    # FIGHT ERRORS
    active_debug_section = "1.4"
    log_print("\n" + "-" * 80)
    _table_header("1.4 FIGHT ERRORS")
    # "Fight from non-adjacent hex" RETIRE (2026-07-24) : contrôle non reconstructible depuis
    # step.log (gate combat moteur euclidien + position cible pré-perte non journalisee).
    # Invariant verrouillé par tests/unit/engine/test_fight_spatial_contract.py.
    agent_fight_friendly = stats['fight_friendly'][1]
    bot_fight_friendly = stats['fight_friendly'][2]
    _table_row("Fight a friendly unit:", _fmt_count(agent_fight_friendly), _fmt_count(bot_fight_friendly))
    if agent_fight_friendly > 0 and stats['first_error_lines']['fight_friendly'][1]:
        first_err = stats['first_error_lines']['fight_friendly'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_fight_friendly > 0 and stats['first_error_lines']['fight_friendly'][2]:
        first_err = stats['first_error_lines']['fight_friendly'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_fight_over_cc = stats['fight_over_cc_nb'][1]
    bot_fight_over_cc = stats['fight_over_cc_nb'][2]
    _table_row("Attacks over CC_NB:", _fmt_count(agent_fight_over_cc), _fmt_count(bot_fight_over_cc))
    if agent_fight_over_cc > 0 and stats['first_error_lines']['fight_over_cc_nb'][1]:
        first_err = stats['first_error_lines']['fight_over_cc_nb'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_fight_over_cc > 0 and stats['first_error_lines']['fight_over_cc_nb'][2]:
        first_err = stats['first_error_lines']['fight_over_cc_nb'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    _hit_result_rows(stats, "fight_hit_result", "melee")
    _wound_threshold_rows(stats, "fight_wound_threshold", "melee")
    agent_fight_alt = stats['fight_alternation_violations'][1]
    bot_fight_alt = stats['fight_alternation_violations'][2]
    _table_row("Fight alternation violations:", _fmt_count(agent_fight_alt), _fmt_count(bot_fight_alt))
    if agent_fight_alt > 0 and stats['first_error_lines']['fight_alternation_violations'][1]:
        first_err = stats['first_error_lines']['fight_alternation_violations'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_fight_alt > 0 and stats['first_error_lines']['fight_alternation_violations'][2]:
        first_err = stats['first_error_lines']['fight_alternation_violations'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    _dpi = require_key(stats, 'fight_double_pile_in')
    _table_row("Pile-in double (12.02):", _fmt_count(_dpi[1]), _fmt_count(_dpi[2]))
    for _p in (1, 2):
        _first = stats['first_error_lines']['fight_double_pile_in'][_p]
        if _dpi[_p] > 0 and _first:
            log_print(f"  First P{_p} occurrence (Episode {_first['episode']}): {_first['line']}")
    _fm = require_key(stats, 'fight_move_invalid')
    for _kind, _label in (('pile_in', 'Pile-in au-dela de 3"'), ('consolidation', 'Conso au-dela de 3"')):
        _table_row(f"{_label}:", _fmt_count(_fm[_kind][1]), _fmt_count(_fm[_kind][2]))
        for _pl in (1, 2):
            if _fm[_kind][_pl] > 0 and stats['first_error_lines']['fight_move_invalid'][_kind][_pl]:
                _fe = stats['first_error_lines']['fight_move_invalid'][_kind][_pl]
                log_print(f"  First P{_pl} occurrence (Episode {_fe['episode']}): {_fe['line']}")

    
    # ACTION PHASE ACCURACY
    active_debug_section = "1.5"
    log_print("\n" + "-" * 80)
    log_print(f"1.5 {debug_sections['1.5']}")
    log_print("-" * 80)
    log_print(f"{'Action':<12} {'Total':>8} {'Wrong':>8} {'Accuracy':>10}")
    log_print("-" * 80)
    action_phase_accuracy = require_key(stats, "action_phase_accuracy")
    for action_key in ("move", "fled", "shoot", "advance", "charge", "fight"):
        counts = require_key(action_phase_accuracy, action_key)
        total = require_key(counts, "total")
        wrong = require_key(counts, "wrong")
        accuracy = ((total - wrong) / total * 100.0) if total > 0 else 100.0
        log_print(f"{action_key.upper():<12} {total:8d} {wrong:8d} {accuracy:9.1f}%")
        mismatch = require_key(stats, "first_error_lines")["action_phase_mismatch"].get(action_key)
        if mismatch:
            log_print(f"  First occurrence (Episode {mismatch['episode']}): {mismatch['line']}")

    # 1.6 Double-activation par phase
    active_debug_section = "1.6"
    log_print("\n" + "-" * 80)
    log_print(f"1.6 {debug_sections['1.6']}")
    log_print("-" * 80)
    double_activation_by_phase = require_key(stats, "double_activation_by_phase")
    double_activation_total = sum(double_activation_by_phase.values())
    reactive_double = require_key(stats, "double_activation_reactive_move")
    has_any_double = (double_activation_total > 0) or (reactive_double > 0)
    if has_any_double:
        log_print(f"{'Phase':<12} {'Count':>10}")
        log_print("-" * 80)
        for phase_key in ("MOVE", "SHOOT", "CHARGE", "FIGHT"):
            count = double_activation_by_phase.get(phase_key, 0)  # get allowed: optional phase
            if count > 0:
                log_print(f"{phase_key:<12} {count:10d}")
                first_err = require_key(stats, "first_error_lines")["double_activation_by_phase"].get(phase_key)
                if first_err:
                    log_print(f"  First occurrence (Episode {first_err['episode']}): {first_err['line']}")
        if reactive_double > 0:
            log_print(f"{'REACTIVE':<12} {reactive_double:10d}")
            reactive_first = require_key(stats, "first_error_lines")["double_activation_reactive_move"]
            if reactive_first:
                log_print(f"  First occurrence (Episode {reactive_first['episode']}): {reactive_first['line']}")
    else:
        log_print("No double-activation detected.")

    # SPECIAL RULES USAGE (by rule and unit type)
    active_debug_section = "1.7"
    log_print("\n" + "-" * 80)
    log_print(f"1.7 SPECIAL RULES USAGE                  {'Unit':<55} {'P1':>10} {'P2':>10} {'Validité':>10}")
    log_print("-" * 80)
    # Capacités de FACTION d'abord : elles n'ont pas d'unité porteuse (c'est le mot-clé qui les
    # donne), donc elles n'apparaissaient dans aucune ligne du tableau ci-dessous.
    _faction = require_key(stats, 'faction_ability_activations')
    if _faction:
        for _rule in sorted(_faction):
            _c = _faction[_rule]
            log_print(
                f"{_rule:<40} {'(capacité de FACTION)':<55} {_c[1]:>10} {_c[2]:>10} "
                f"{'OK' if (_c[1] or _c[2]) else 'NOT USED':>10}"
            )
    else:
        log_print(f"{'(aucune capacité de faction activée)':<40}")
    log_print("-" * 80)
    special_rule_usage = stats.get('special_rule_usage', defaultdict(lambda: {1: 0, 2: 0}))
    rule_to_units = stats.get('rule_to_units', {})  # get allowed: optional stats
    expected_keys = set()
    for rule_id, unit_types in rule_to_units.items():
        for unit_type in unit_types:
            expected_keys.add((rule_id, unit_type))
    usage_keys = sorted(set(special_rule_usage.keys()) | expected_keys)
    if usage_keys:
        for (rule_id, unit_type) in usage_keys:
            counts = special_rule_usage.get((rule_id, unit_type), {1: 0, 2: 0})
            p1 = counts.get(1, 0)  # get allowed: optional player counts
            p2 = counts.get(2, 0)  # get allowed: optional player counts
            has_rule = unit_type in rule_to_units.get(rule_id, set())
            validite = "OK" if has_rule else "INVALID"
            log_print(f"{rule_id:<40} {unit_type:<55} {p1:10d} {p2:10d} {validite:>10}")
    else:
        log_print("No special rule usage recorded.")

    log_print("\n  Rule-choice compliance (selected option vs used option)")
    log_print(f"  {'Rule':<36} {'Unit':<36} {'P1 OK':>8} {'P2 OK':>8} {'P1 MISS':>8} {'P2 MISS':>8} {'P1 BAD':>8} {'P2 BAD':>8}")
    rule_choice_usage = require_key(stats, 'rule_choice_usage')
    rule_choice_selection_usage = require_key(stats, 'rule_choice_selection_usage')
    rule_choice_keys = sorted(
        set(rule_choice_usage.keys()) | set(rule_choice_selection_usage.keys())
    )
    if rule_choice_keys:
        for (rule_id, unit_type) in rule_choice_keys:
            status_counts = rule_choice_usage.get(
                (rule_id, unit_type),
                {'correct': {1: 0, 2: 0}, 'missing': {1: 0, 2: 0}, 'mismatch': {1: 0, 2: 0}},
            )
            ok_counts = require_key(status_counts, 'correct')
            missing_counts = require_key(status_counts, 'missing')
            mismatch_counts = require_key(status_counts, 'mismatch')
            log_print(
                f"  {rule_id:<36} {unit_type:<36} "
                f"{ok_counts[1]:8d} {ok_counts[2]:8d} "
                f"{missing_counts[1]:8d} {missing_counts[2]:8d} "
                f"{mismatch_counts[1]:8d} {mismatch_counts[2]:8d}"
            )
        selection_invalid = require_key(stats, 'rule_choice_selection_invalid')
        if selection_invalid[1] > 0 and stats['first_error_lines']['rule_choice_selection_invalid'][1]:
            first_err = stats['first_error_lines']['rule_choice_selection_invalid'][1]
            log_print(f"  First invalid selection P1 (Episode {first_err['episode']}): {first_err['line']}")
        if selection_invalid[2] > 0 and stats['first_error_lines']['rule_choice_selection_invalid'][2]:
            first_err = stats['first_error_lines']['rule_choice_selection_invalid'][2]
            log_print(f"  First invalid selection P2 (Episode {first_err['episode']}): {first_err['line']}")
        if stats['first_error_lines']['rule_choice_usage_missing'][1]:
            first_err = stats['first_error_lines']['rule_choice_usage_missing'][1]
            log_print(f"  First missing choice usage P1 (Episode {first_err['episode']}): {first_err['line']}")
        if stats['first_error_lines']['rule_choice_usage_missing'][2]:
            first_err = stats['first_error_lines']['rule_choice_usage_missing'][2]
            log_print(f"  First missing choice usage P2 (Episode {first_err['episode']}): {first_err['line']}")
        if stats['first_error_lines']['rule_choice_usage_mismatch'][1]:
            first_err = stats['first_error_lines']['rule_choice_usage_mismatch'][1]
            log_print(f"  First wrong choice usage P1 (Episode {first_err['episode']}): {first_err['line']}")
        if stats['first_error_lines']['rule_choice_usage_mismatch'][2]:
            first_err = stats['first_error_lines']['rule_choice_usage_mismatch'][2]
            log_print(f"  First wrong choice usage P2 (Episode {first_err['episode']}): {first_err['line']}")
    else:
        log_print("  No rule-choice usage recorded.")

    # WEAPONS RULES USAGE (by rule and weapon+unit)
    active_debug_section = "1.8"
    log_print("\n" + "-" * 80)
    _wr_header()
    weapon_rule_usage = stats.get('weapon_rule_usage', defaultdict(lambda: {1: 0, 2: 0}))
    weapon_rule_to_weapons = require_key(stats, 'weapon_rule_to_weapons')
    unit_types_seen = set(require_key(stats, "unit_types_seen"))
    unit_type_suffixes = tuple(f" ({unit_type})" for unit_type in unit_types_seen)
    expected_wr_keys = {
        (rule_name, weapon_key)
        for rule_name, weapon_keys in weapon_rule_to_weapons.items()
        for weapon_key in weapon_keys
        if unit_type_suffixes and weapon_key.endswith(unit_type_suffixes)
    }
    wr_keys = sorted(set(weapon_rule_usage.keys()) | expected_wr_keys)
    if wr_keys:
        for (rule_name, weapon_key) in wr_keys:
            counts = weapon_rule_usage.get((rule_name, weapon_key), {1: 0, 2: 0})
            p1 = counts.get(1, 0)  # get allowed: optional player counts
            p2 = counts.get(2, 0)  # get allowed: optional player counts
            has_rule = weapon_key in weapon_rule_to_weapons.get(rule_name, set())
            # « INVALID » ne qualifie plus qu'une chose verifiable depuis step.log : une paire
            # (regle, arme) observee alors que l'armurerie ne la declare pas.
            if not has_rule:
                validite = "INVALID"
            elif (p1 + p2) == 0:
                validite = "NOT USED"
            else:
                validite = "OK"
            rule_display = rule_name.capitalize() if rule_name else rule_name
            _wr_row(rule_display, weapon_key, p1, p2, validite)
        not_used_count = sum(
            1
            for (rule_name, weapon_key) in expected_wr_keys
            if _weapon_rule_usage_pair_total(weapon_rule_usage, (rule_name, weapon_key)) == 0
        )
        log_print(
            f"Expected weapon-rule pairs: {len(expected_wr_keys):6d} | "
            f"Not used: {not_used_count:6d}"
        )
    else:
        log_print("No weapon rule usage recorded.")

    # Rule execution metrics (same section formatting)
    agent_dw_correct = stats['devastating_wounds_correct'][1]
    bot_dw_correct = stats['devastating_wounds_correct'][2]
    _wr_row("Devastating_wounds", "GLOBAL (correct)", agent_dw_correct, bot_dw_correct, "OK")
    agent_dw_incorrect = stats['devastating_wounds_incorrect'][1]
    bot_dw_incorrect = stats['devastating_wounds_incorrect'][2]
    if (agent_dw_incorrect + bot_dw_incorrect) > 0:
        _wr_row("Devastating_wounds", "GLOBAL (incorrect)", agent_dw_incorrect, bot_dw_incorrect, "INVALID")
        if agent_dw_incorrect > 0 and stats['first_error_lines']['devastating_wounds_incorrect'][1]:
            first_err = stats['first_error_lines']['devastating_wounds_incorrect'][1]
            log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        if bot_dw_incorrect > 0 and stats['first_error_lines']['devastating_wounds_incorrect'][2]:
            first_err = stats['first_error_lines']['devastating_wounds_incorrect'][2]
            log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")

    incomplete_p1 = 0
    incomplete_p2 = 0
    incomplete_unknown = 0
    for ep in stats['episodes_without_end']:
        last_line = ep.get('last_line', '')
        match = re.search(r'\bP([12])\b', last_line)
        if match:
            if match.group(1) == "1":
                incomplete_p1 += 1
            else:
                incomplete_p2 += 1
        else:
            incomplete_unknown += 1
    without_method_p1 = 0
    without_method_p2 = 0
    without_method_unknown = 0
    for ep in stats['episodes_without_method']:
        winner = ep.get('winner')
        if winner == PLAYER_ONE_ID:
            without_method_p1 += 1
        elif winner == PLAYER_TWO_ID:
            without_method_p2 += 1
        else:
            without_method_unknown += 1

    # DEAD UNITS INTERACTIONS
    active_debug_section = "2.1"
    log_print("\n" + "-" * 80)
    log_print(f"{('2.1 ' + debug_sections['2.1']):<30s} {'Joueur 1':>15s} {'Joueur 2':>15s}")
    log_print("-" * 80)
    log_print(f"Incomplete episodes:           {incomplete_p1:6d}           {incomplete_p2:6d}")
    log_print(f"Dead unit moving:              {stats['dead_unit_moving'][1]:6d}           {stats['dead_unit_moving'][2]:6d}")
    if stats['dead_unit_moving'][1] > 0 and stats['first_error_lines']['dead_unit_moving'][1]:
        first_err = stats['first_error_lines']['dead_unit_moving'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['dead_unit_moving'][2] > 0 and stats['first_error_lines']['dead_unit_moving'][2]:
        first_err = stats['first_error_lines']['dead_unit_moving'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    log_print(f"Dead unit shooting:            {stats['shoot_dead_unit'][1]:6d}           {stats['shoot_dead_unit'][2]:6d}")
    if stats['shoot_dead_unit'][1] > 0 and stats['first_error_lines']['shoot_dead_unit'][1]:
        first_err = stats['first_error_lines']['shoot_dead_unit'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['shoot_dead_unit'][2] > 0 and stats['first_error_lines']['shoot_dead_unit'][2]:
        first_err = stats['first_error_lines']['shoot_dead_unit'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    log_print(f"Shoot at dead unit:            {stats['shoot_at_dead_unit'][1]:6d}           {stats['shoot_at_dead_unit'][2]:6d}")
    if stats['shoot_at_dead_unit'][1] > 0 and stats['first_error_lines']['shoot_at_dead_unit'][1]:
        first_err = stats['first_error_lines']['shoot_at_dead_unit'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['shoot_at_dead_unit'][2] > 0 and stats['first_error_lines']['shoot_at_dead_unit'][2]:
        first_err = stats['first_error_lines']['shoot_at_dead_unit'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    log_print(f"Dead unit advancing:           {stats['dead_unit_advancing'][1]:6d}           {stats['dead_unit_advancing'][2]:6d}")
    if stats['dead_unit_advancing'][1] > 0 and stats['first_error_lines']['dead_unit_advancing'][1]:
        first_err = stats['first_error_lines']['dead_unit_advancing'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['dead_unit_advancing'][2] > 0 and stats['first_error_lines']['dead_unit_advancing'][2]:
        first_err = stats['first_error_lines']['dead_unit_advancing'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    log_print(f"Dead unit charging:            {stats['dead_unit_charging'][1]:6d}           {stats['dead_unit_charging'][2]:6d}")
    if stats['dead_unit_charging'][1] > 0 and stats['first_error_lines']['dead_unit_charging'][1]:
        first_err = stats['first_error_lines']['dead_unit_charging'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['dead_unit_charging'][2] > 0 and stats['first_error_lines']['dead_unit_charging'][2]:
        first_err = stats['first_error_lines']['dead_unit_charging'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    log_print(f"Charge a dead unit:            {stats['charge_dead_unit'][1]:6d}           {stats['charge_dead_unit'][2]:6d}")
    if stats['charge_dead_unit'][1] > 0 and stats['first_error_lines']['charge_dead_unit'][1]:
        first_err = stats['first_error_lines']['charge_dead_unit'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['charge_dead_unit'][2] > 0 and stats['first_error_lines']['charge_dead_unit'][2]:
        first_err = stats['first_error_lines']['charge_dead_unit'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    log_print(f"Dead unit fighting:            {stats['fight_dead_unit_attacker'][1]:6d}           {stats['fight_dead_unit_attacker'][2]:6d}")
    if stats['fight_dead_unit_attacker'][1] > 0 and stats['first_error_lines']['fight_dead_unit_attacker'][1]:
        first_err = stats['first_error_lines']['fight_dead_unit_attacker'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['fight_dead_unit_attacker'][2] > 0 and stats['first_error_lines']['fight_dead_unit_attacker'][2]:
        first_err = stats['first_error_lines']['fight_dead_unit_attacker'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    log_print(f"Fight a dead unit:             {stats['fight_dead_unit_target'][1]:6d}           {stats['fight_dead_unit_target'][2]:6d}")
    if stats['fight_dead_unit_target'][1] > 0 and stats['first_error_lines']['fight_dead_unit_target'][1]:
        first_err = stats['first_error_lines']['fight_dead_unit_target'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['fight_dead_unit_target'][2] > 0 and stats['first_error_lines']['fight_dead_unit_target'][2]:
        first_err = stats['first_error_lines']['fight_dead_unit_target'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    log_print(f"Dead unit waiting:             {stats['dead_unit_waiting'][1]:6d}           {stats['dead_unit_waiting'][2]:6d}")
    if stats['dead_unit_waiting'][1] > 0 and stats['first_error_lines']['dead_unit_waiting'][1]:
        first_err = stats['first_error_lines']['dead_unit_waiting'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['dead_unit_waiting'][2] > 0 and stats['first_error_lines']['dead_unit_waiting'][2]:
        first_err = stats['first_error_lines']['dead_unit_waiting'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    # La ligne « Dead unit skipping » a été retirée le 2026-08-10 (V3) : elle affichait 0 en
    # permanence faute de ligne `SKIP` dans le journal, et ce 0 comptait dans le ✅ de §2.1.
    log_print(f"Unités revenues après mort:    {stats['unit_revived'][1]:6d}           {stats['unit_revived'][2]:6d}")
    if stats['unit_revived'][1] > 0 and stats['first_error_lines']['unit_revived'][1]:
        first_err = stats['first_error_lines']['unit_revived'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['unit_revived'][2] > 0 and stats['first_error_lines']['unit_revived'][2]:
        first_err = stats['first_error_lines']['unit_revived'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")

    # POSITION / LOG COHERENCE
    active_debug_section = "2.2"
    log_print("\n" + "-" * 80)
    log_print(f"2.2 {debug_sections['2.2']}")
    log_print("-" * 80)
    for action_key in ("move", "advance", "charge"):
        total = stats['position_log_mismatch'][action_key]['total']
        mismatch = stats['position_log_mismatch'][action_key]['mismatch']
        missing = stats['position_log_mismatch'][action_key]['missing']
        absorbed = stats['position_log_mismatch'][action_key]['anchor_absorbed']
        pct = (mismatch / total * 100.0) if total > 0 else 0.0
        log_print(
            f"{action_key.upper():8s} total={total:6d} mismatch={mismatch:6d} "
            f"missing={missing:6d} mismatch_pct={pct:6.2f}% anchor_absorbed={absorbed:6d}"
        )
    log_print("---")
    # anchor_absorbed = départs cohérents via l'empreinte du socle mais ≠ ancre mémorisée :
    # bruit de recalcul d'ancre d'escouade côté moteur (±1 subhex), tracé mais NON compté
    # comme incohérence. Un total élevé signalerait une instabilité d'ancre à investiguer.
    log_print("(anchor_absorbed = bruit d'ancre d'escouade absorbé, informatif — pas une erreur)")
    log_print(f"Total collisions (2+ units in same hex): {len(stats['unit_position_collisions'])}")

    # DMG ISSUES
    active_debug_section = "2.3"
    log_print("\n" + "-" * 80)
    log_print(f"{('2.3 ' + debug_sections['2.3']):<30s} {'Joueur 1':>15s} {'Joueur 2':>15s}")
    log_print("-" * 80)
    dmg_missing_p1 = stats['damage_missing_unit_hp'][1]
    dmg_missing_p2 = stats['damage_missing_unit_hp'][2]
    log_print(f"Missing unit_hp on damage:   {dmg_missing_p1:6d}           {dmg_missing_p2:6d}")
    dmg_over_p1 = stats['damage_exceeds_hp'][1]
    dmg_over_p2 = stats['damage_exceeds_hp'][2]
    log_print(f"Dmg > HP_CUR (overkill):     {dmg_over_p1:6d}           {dmg_over_p2:6d}")

    # EPISODES STATISTICS
    active_debug_section = "2.4"
    log_print("\n" + "-" * 80)
    log_print(f"2.4 {debug_sections['2.4']}")
    log_print("-" * 80)
    if max_duration_episode is not None and avg_duration is not None:
        log_print(f"Longest episode (average duration): Episode {max_duration_episode} - {max_duration:.2f}s (avg {avg_duration:.2f}s)")
    else:
        log_print("Longest episode (average duration): N/A")
    if max_length_episode is not None and avg_length is not None:
        log_print(f"Episode with most actions (average action number): Episode {max_length_episode} - {max_length} actions (avg {avg_length:.1f})")
    else:
        log_print("Episode with most actions (average action number): N/A")

    # EPISODES ENDING
    active_debug_section = "2.5"
    log_print("\n" + "-" * 80)
    log_print(f"{('2.5 ' + debug_sections['2.5']):<30s} {'Joueur 1':>15s} {'Joueur 2':>15s}")
    log_print("-" * 80)
    log_print(f"Incomplete episodes:         {incomplete_p1:6d}           {incomplete_p2:6d}")
    log_print(f"Episodes without win_method: {without_method_p1:6d}           {without_method_p2:6d}")

    # SAMPLE MISSING
    active_debug_section = "2.6"
    log_print("\n" + "-" * 80)
    log_print(f"2.6 {debug_sections['2.6']}")
    log_print("-" * 80)
    sample_action_types = ['move', 'shoot', 'advance', 'charge', 'fight']
    missing_samples = [action for action in sample_action_types if not stats['sample_actions'][action]]
    missing_samples_label = ", ".join(missing_samples) if missing_samples else "none"
    for action_type in ['move', 'shoot', 'advance', 'charge', 'fight']:
        if stats['sample_actions'][action_type]:
            action_label = action_type.upper().ljust(7)
            log_print(f"{action_label} --- {stats['sample_actions'][action_type]}")
    log_print(f"Sample missing ({len(missing_samples)}/{len(sample_action_types)}) : {missing_samples_label}")

    # CORE ISSUES
    active_debug_section = "2.7"
    log_print("\n" + "-" * 80)
    log_print(f"2.7 {debug_sections['2.7']}")
    log_print("-" * 80)
    unit_id_mismatches = require_key(stats, 'unit_id_mismatches')
    log_print(f"Parsing errors (Non-standard log format): {len(stats['parse_errors'])}")
    log_print(f"Unit ID mismatches (Critical Bug):        {len(unit_id_mismatches)}")
    if stats['parse_errors']:
        log_print("\nParsing errors breakdown:")
        error_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for err in stats['parse_errors']:
            error_groups[err.get('error', 'Unknown parse error')].append(err)
        for error_msg, entries in sorted(error_groups.items(), key=lambda x: len(x[1]), reverse=True):
            log_print(f"- {error_msg} (x{len(entries)})")
            for example in entries[:3]:
                log_print(f"  Example: E{example.get('episode')} T{example.get('turn')} {example.get('phase')} : {example.get('line')}")

    # ── 2.8 : ce que l'analyzer croyait, vs ce que le moteur a déclaré ──────────────────────
    # Le compteur du chantier. Tout le reste de ce rapport repose sur un état RECONSTRUIT par
    # accumulation d'événements ; jusqu'ici, rien ne disait quand cette reconstruction dérivait.
    # Ces trois nombres le disent — et une divergence non nulle invalide, pour l'épisode
    # concerné, les contrôles qui mesurent des distances ou des adjacences.
    active_debug_section = "2.8"
    log_print("\n" + "-" * 80)
    log_print(f"2.8 {debug_sections['2.8']}")
    log_print("-" * 80)
    _resync = require_key(stats, 'state_resync')
    log_print(f"Morts non vues par l'analyzer (fantomes)  : {_resync['dead_missed']}")
    log_print(f"Unites tuees a tort par l'analyzer        : {_resync['alive_missed']}")
    log_print(f"Figurines mal positionnees (deplacement non journalise) : {_resync['pos_mismatch']}")
    log_print(f"Figurine allouee inconnue de l'analyzer  : {_resync['alloc_model_unknown']}")

    # LE calcul, partagé avec le total de la CLI (`error_totals`). Les deux copies qui vivaient
    # ici et là-bas avaient divergé sur deux compteurs : le rapport se contredisait lui-même.
    _totals = error_totals(stats)
    move_errors = _totals['move']
    shooting_errors = _totals['shooting']
    charge_errors = _totals['charge']
    fight_errors = _totals['fight']
    dead_unit_interactions_total = _totals['dead_units']
    pos_mismatch_total = _totals['positions']

    active_debug_section = None
    log_print("\n" + "=" * 80)
    log_print("SUMMARY")
    log_print("=" * 80)
    def summary_error_icon(has_error: bool) -> str:
        return "❌" if has_error else "✅"

    def summary_warning_icon(has_warning: bool) -> str:
        return "⚠️ " if has_warning else "✅"

    long_episode_warn = (max_duration is not None and avg_duration is not None and max_duration > avg_duration * 3)
    actions_episode_warn = (max_length is not None and avg_length is not None and max_length > avg_length * 3)
    log_print("-" * 80)
    log_print("PHASES")
    log_print("-" * 80)
    log_print(f"{summary_error_icon(move_errors > 0)} 1.1 Erreurs en phase de move : {move_errors}")
    log_print(f"{summary_error_icon(shooting_errors > 0)} 1.2 Erreurs en phase de shooting : {shooting_errors}")
    log_print(f"{summary_error_icon(charge_errors > 0)} 1.3 Erreurs en phase de charge : {charge_errors}")
    log_print(f"{summary_error_icon(fight_errors > 0)} 1.4 Erreurs en phase de fight : {fight_errors}")
    wrong_phase_total = _totals['wrong_phase']
    log_print(f"{summary_error_icon(wrong_phase_total > 0)} 1.5 Actions occuring in the wrong phase : {wrong_phase_total}")
    # NOMBRE et ICÔNE tirés de la MÊME grandeur — celle qui entre dans le total. Afficher ici la
    # seule somme par phase alors que le bucket compte AUSSI le move réactif (section 1.6
    # détaillée, ligne « REACTIVE ») rendrait « ❌ … : 0 » sur un journal ne portant qu'un
    # doublon réactif : la contradiction que ce lot vient de fermer, réintroduite d'un cran plus
    # bas.
    log_print(
        f"{summary_error_icon(_totals['double_activation'] > 0)} "
        f"1.6 Double-activation (phase + reactif) : {_totals['double_activation']}"
    )
    special_rule_usage_total = sum(
        counts.get(1, 0) + counts.get(2, 0)  # get allowed: optional player counts
        for counts in stats.get('special_rule_usage', defaultdict(lambda: {1: 0, 2: 0})).values()  # get allowed: optional stats
    )
    # Les capacités de FACTION entrent dans le MÊME total. Le tableau de la section 1.7 les
    # affiche depuis le lot précédent, mais cette ligne de résumé continuait de sommer les seules
    # règles de datasheet : « 1.7 Special rules usage : 0 utilisations ✅ » restait affiché sur un
    # journal où Oath of Moment s'activait 1980 fois. Corriger le tableau sans corriger le total
    # laissait le vert vacant exactement là où on le lit — dans le résumé.
    special_rule_usage_total += sum(
        counts.get(1, 0) + counts.get(2, 0)  # get allowed: optional player counts
        for counts in require_key(stats, 'faction_ability_activations').values()
    )
    weapon_rule_usage_total = sum(
        counts.get(1, 0) + counts.get(2, 0)  # get allowed: optional player counts
        for counts in stats.get('weapon_rule_usage', defaultdict(lambda: {1: 0, 2: 0})).values()  # get allowed: optional stats
    )
    rule_to_units = stats.get('rule_to_units', {})  # get allowed: optional stats
    weapon_rule_to_weapons = stats.get('weapon_rule_to_weapons', {})  # get allowed: optional stats
    weapon_rule_usage_stats = require_key(stats, 'weapon_rule_usage')
    unit_types_seen = set(require_key(stats, "unit_types_seen"))
    unit_type_suffixes = tuple(f" ({unit_type})" for unit_type in unit_types_seen)
    expected_weapon_rule_pairs = {
        (rule_name, weapon_key)
        for rule_name, weapon_keys in weapon_rule_to_weapons.items()
        for weapon_key in weapon_keys
        if unit_type_suffixes and weapon_key.endswith(unit_type_suffixes)
    }
    weapon_rule_not_used_warnings = sum(
        1
        for (rule_name, weapon_key) in expected_weapon_rule_pairs
        if _weapon_rule_usage_pair_total(weapon_rule_usage_stats, (rule_name, weapon_key)) == 0
    )
    special_rules_invalid = _totals['special_rules_invalid']
    weapon_rules_invalid = _totals['weapon_rules_invalid']
    log_print(f"{summary_error_icon(special_rules_invalid > 0)} 1.7 Special rules usage : {special_rule_usage_total} utilisations" + (f" ({special_rules_invalid} invalid)" if special_rules_invalid > 0 else ""))
    weapon_rules_has_warning = weapon_rule_not_used_warnings > 0
    weapon_rules_status_parts: List[str] = []
    if weapon_rules_invalid > 0:
        weapon_rules_status_parts.append(f"{weapon_rules_invalid} invalid")
    if weapon_rules_has_warning:
        weapon_rules_status_parts.append(f"{weapon_rule_not_used_warnings} not used (warning)")
    weapon_rules_status_suffix = (
        f" ({', '.join(weapon_rules_status_parts)})"
        if weapon_rules_status_parts
        else ""
    )
    if weapon_rules_invalid > 0:
        weapon_rules_icon = "❌"
    elif weapon_rules_has_warning:
        weapon_rules_icon = "⚠️ "
    else:
        weapon_rules_icon = "✅"
    log_print(
        f"{weapon_rules_icon} 1.8 Weapon rules usage : {weapon_rule_usage_total} utilisations"
        f"{weapon_rules_status_suffix}"
    )
    dmg_issues_total = _totals['damage']
    core_issues_total = _totals['core_issues']
    log_print("-" * 80)
    log_print("INTEGRITY")
    log_print("-" * 80)
    log_print(f"{summary_error_icon(dead_unit_interactions_total > 0)} 2.1 Dead units interactions : {dead_unit_interactions_total}")
    log_print(f"{summary_error_icon(pos_mismatch_total > 0)} 2.2 Positions/logs incohérents : {pos_mismatch_total}")
    log_print(f"{summary_error_icon(dmg_issues_total > 0)} 2.3 DMG issues : {dmg_issues_total}")
    if max_duration_episode is not None and avg_duration is not None:
        durations_list = require_key(stats, 'episode_durations')
        min_duration_episode, min_duration = min(durations_list, key=lambda x: x[1])
        log_print(f"{summary_warning_icon(long_episode_warn)} 2.4 Episodes duration : Min: {min_duration:.2f}s (E{min_duration_episode}) - Avg: {avg_duration:.2f}s - Max: {max_duration:.2f}s (E{max_duration_episode})")
    else:
        log_print(f"{summary_warning_icon(False)} 2.4 Episodes duration : N/A")
    if max_length_episode is not None and avg_length is not None:
        lengths_list = require_key(stats, 'episode_lengths')
        min_length_episode, min_length = min(lengths_list, key=lambda x: x[1])
        log_print(f"{summary_warning_icon(actions_episode_warn)} 2.4 Episodes actions : Min: {min_length} (E{min_length_episode}) - Avg: {avg_length:.1f} - Max: {max_length} (E{max_length_episode})")
    else:
        log_print(f"{summary_warning_icon(False)} 2.4 Episodes actions : N/A")
    episodes_ending_total = _totals['episodes_ending']
    log_print(f"{summary_error_icon(episodes_ending_total > 0)} 2.5 Episode ending : {episodes_ending_total}")
    log_print(f"{summary_error_icon(len(missing_samples) > 0)} 2.6 Sample missing ({len(missing_samples)}/{len(sample_action_types)}) : {missing_samples_label}")
    log_print(f"{summary_error_icon(core_issues_total > 0)} 2.7 Core issue : {core_issues_total}")
    # 2.8 : une divergence non nulle invalide, pour l'episode concerne, tout controle mesurant
    # une distance ou une adjacence — elle est donc rendue au meme rang que les autres.
    _resync_total = sum(require_key(stats, 'state_resync').values())
    log_print(
        f"{summary_error_icon(_resync_total > 0)} 2.8 Etat reconstruit vs moteur : {_resync_total} "
        f"(fantomes={stats['state_resync']['dead_missed']}, "
        f"tuees-a-tort={stats['state_resync']['alive_missed']}, "
        f"positions={stats['state_resync']['pos_mismatch']}, "
        f"figurine-allouee-inconnue={stats['state_resync']['alloc_model_unknown']})"
    )

    log_print("\n" + "#" * 80 + "\n")


if __name__ == "__main__":
    import datetime
    import os
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze step.log and validate game rules compliance")
    parser.add_argument("log_file", help="Path to step.log")
    parser.add_argument("debug_section", nargs="?", default=None, help="Filter DEBUGGING section (see output headers)")
    parser.add_argument("--d", action="store_true", help="Show only details section at end")
    parser.add_argument("--b", action="store_true", help="Show only debugging section at end")
    parser.add_argument("--s", action="store_true", help="Show only summary section at end")
    parser.add_argument("--n", action="store_true", help="Show only final status line")
    args = parser.parse_args()

    log_file = args.log_file
    debug_section_filter = args.debug_section
    
    # Open output file for writing
    output_file = 'analyzer.log'
    output_f = open(output_file, 'w', encoding='utf-8')
    
    emit_console = not (args.d or args.b or args.s or args.n)

    def log_print(*args, **kwargs):
        """Print to console (optional) and file"""
        if emit_console:
            print(*args, **kwargs)
        print(*args, file=output_f, **kwargs)
        output_f.flush()

    def _extract_section(
        lines: List[str],
        start_token: str,
        end_token: str,
        start_startswith: bool = False,
        end_startswith: bool = False
    ) -> List[str]:
        start_index = None
        end_index = None
        for idx, line in enumerate(lines):
            if start_index is None:
                if start_startswith and line.startswith(start_token):
                    start_index = idx
                elif not start_startswith and start_token in line:
                    start_index = idx
            if start_index is not None:
                if end_startswith and line.startswith(end_token):
                    end_index = idx
                    break
                if not end_startswith and end_token in line:
                    end_index = idx
                    break
        if start_index is None or end_index is None:
            return []
        return lines[start_index:end_index + 1]
    
    try:
        log_print(f"Analyzing {log_file}...")
        log_print(f"Généré le: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log_print("=" * 80)
        
        stats = parse_step_log(log_file)
        debug_log_path = os.path.join(os.path.dirname(os.path.abspath(log_file)) or ".", "debug.log")
        step_timings = parse_step_timings_from_debug(debug_log_path)
        predict_timings = parse_predict_timings_from_debug(debug_log_path)
        get_mask_timings = parse_get_mask_timings_from_debug(debug_log_path)
        console_log_write_timings = parse_console_log_write_timings_from_debug(debug_log_path)
        cascade_timings = parse_cascade_timings_from_debug(debug_log_path)
        step_breakdowns = parse_step_breakdowns_from_debug(debug_log_path)
        between_step_timings = parse_between_step_timings_from_debug(debug_log_path)
        reset_timings = parse_reset_timings_from_debug(debug_log_path)
        post_step_timings = parse_post_step_timings_from_debug(debug_log_path)
        pre_step_timings = parse_pre_step_timings_from_debug(debug_log_path)
        wrapper_step_timings = parse_wrapper_step_timings_from_debug(debug_log_path)
        after_step_increment_timings = parse_after_step_increment_timings_from_debug(debug_log_path)
        collected_lines: List[str] = []
        print_statistics(stats, output_f, step_timings=step_timings, predict_timings=predict_timings, get_mask_timings=get_mask_timings, console_log_write_timings=console_log_write_timings, cascade_timings=cascade_timings, step_breakdowns=step_breakdowns, between_step_timings=between_step_timings, reset_timings=reset_timings, post_step_timings=post_step_timings, pre_step_timings=pre_step_timings, wrapper_step_timings=wrapper_step_timings, after_step_increment_timings=after_step_increment_timings, debug_section_filter=debug_section_filter, output_lines=collected_lines, emit_console=emit_console)
        
        # Total d'erreurs : LE calcul, celui-là même dont le SUMMARY imprimé au-dessus tire ses
        # lignes ❌ (`error_totals`). Une seconde copie vivait ici : elle ignorait deux compteurs
        # de phase (V16), puis la double-activation §1.6 et les règles invalides §1.7 — un run
        # pouvait donc imprimer « ❌ 1.6 … : 1 » suivi de « ✅ Aucune erreur détectée ». Le total
        # est désormais la somme de TOUS les buckets, donc de toutes les lignes ❌ par
        # construction : un bucket neuf y entre sans qu'on ait à y penser.
        total_errors = error_totals(stats)['total']

        # Les WARNINGS ne sont pas des erreurs : une paire (règle, arme) déclarée par l'armurerie
        # et jamais observée signale un roster ou un scénario qui n'exerce pas la règle, pas une
        # faute de jeu. Elle reste donc hors du total ci-dessus.
        weapon_rule_to_weapons = require_key(stats, 'weapon_rule_to_weapons')
        weapon_rule_usage = require_key(stats, 'weapon_rule_usage')
        unit_type_suffixes = tuple(f" ({unit_type})" for unit_type in require_key(stats, "unit_types_seen"))
        weapon_rule_not_used_warnings = sum(
            1
            for rule_name, weapon_keys in weapon_rule_to_weapons.items()
            for weapon_key in weapon_keys
            if unit_type_suffixes and weapon_key.endswith(unit_type_suffixes)
            and _weapon_rule_usage_pair_total(weapon_rule_usage, (rule_name, weapon_key)) == 0
        )
        total_warnings = weapon_rule_not_used_warnings

        if total_errors > 0:
            status_line = f"❌ {total_errors} erreur(s) détectée(s)   -   Output : {output_file}"
        elif total_warnings > 0:
            status_line = (
                f"⚠️  0 erreur, {total_warnings} warning(s) "
                f"(weapon rules not used)   -   Output : {output_file}"
            )
        else:
            status_line = f"✅ Aucune erreur détectée   -   Output : {output_file}"

        def _print_section_lines(lines: List[str]) -> None:
            for line in lines:
                print(line)
                print(line, file=output_f)
            output_f.flush()

        if args.d and not args.n:
            details_lines = _extract_section(
                collected_lines,
                "📊 BOT EVALUATION RESULTS",
                "Joueur 2 kills:"
            )
            if details_lines:
                _print_section_lines(details_lines)
        if args.b and not args.n:
            bug_lines = _extract_section(
                collected_lines,
                "DEBUGGING",
                "2.7 CORE ISSUES",
                start_startswith=True,
                end_startswith=True
            )
            if bug_lines:
                _print_section_lines(bug_lines)
        if args.s and not args.n:
            summary_lines = _extract_section(
                collected_lines,
                "SUMMARY",
                "✅ 2.7 Core issue",
                start_startswith=True,
                end_startswith=True
            )
            if summary_lines:
                _print_section_lines(summary_lines)

        _print_section_lines([status_line])

    except Exception as e:
        log_print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        output_f.close()