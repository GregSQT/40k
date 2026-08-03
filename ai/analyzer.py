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
from typing import Dict, List, Tuple, Set, Optional, Any

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
    unit_hp_max_per_model: Dict[str, int],
    unit_types: Dict[str, str],
    unit_positions: Dict[str, Tuple[int, int]],
    unit_deaths: List[Tuple[int, str, str, int]],
    unit_kill_context: Dict[str, Tuple[str, int, str]],
    stats: Dict[str, Any],
    positions_by_model: Optional[Dict[str, Dict[str, Tuple[int, int]]]] = None,
    models_invalidated: Optional[Set[str]] = None,
) -> None:
    """Applique une blessure à la cible via l'allocation par-figurine (05 Attack sequence).

    Une blessure est allouée à la figurine « front » ; si ses PV tombent ≤ 0 elle est
    détruite et l'excès de dégâts est PERDU (jamais reporté sur la figurine suivante).
    L'escouade n'est retirée que lorsque sa DERNIÈRE figurine est détruite. unit_hp reste
    l'invariant d'aliveness (présent et > 0 ⟺ escouade vivante).

    `positions_by_model` — les socles connus de la cible deviennent PÉRIMÉS dès qu'elle perd une
    figurine : le log ne dit pas LAQUELLE (l'allocation est « front », pas nominative), et le
    segment `[MODELS:]` de la cible ne sera réécrit qu'à sa prochaine ACTION. Les garder ferait
    mesurer l'engagement, les empreintes et les obstacles de BFS contre des figurines retirées
    du plateau — un tir sur une escouade dont le socle avancé vient d'être tué remontait
    « cible engagée » alors que le survivant est à l'autre bout. On efface donc l'entrée : la
    mesure retombe sur l'ancre, fraîche à chaque ligne. Donnée absente, pas mesure fausse."""
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
    front_hp = unit_hp[target_id] - damage
    if front_hp <= 0:
        # Figurine front détruite ; l'excès (overkill) est perdu, pas reporté (05.xx).
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
            # Nouvelle figurine front à PV pleins ; escouade toujours vivante.
            unit_hp[target_id] = require_key(unit_hp_max_per_model, target_id)
            stats['wounded_enemies'][player].add(target_id)
            _debug_log(
                f"[MODEL SLAIN] E{current_episode_num} T{turn} {phase} "
                f"target_id={target_id} models_left={unit_models_alive[target_id]}"
            )
    else:
        unit_hp[target_id] = front_hp
        stats['wounded_enemies'][player].add(target_id)
        _debug_log(
            f"[DAMAGE RESULT] E{current_episode_num} T{turn} {phase} "
            f"target_id={target_id} front_hp={front_hp}"
        )


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
    cols, rows = get_config_loader().get_board_size()
    result = set(wall_hexes)
    bottom_row = rows - 1
    for col in range(cols):
        if col % 2 == 1:
            result.add((col, bottom_row))
    return result


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


def is_hex_anchor_adjacent_to_enemy(
    col: int,
    row: int,
    unit_player: Dict[str, int],
    unit_positions: Dict[str, Tuple[int, int]],
    unit_hp: Dict[str, int],
    player: int,
) -> bool:
    """Check legacy analyzer A/anchor hex adjacency against any enemy unit."""
    enemy_player = 3 - player
    # CRITICAL: Normalize player values to int for consistent comparison (handles int/string mismatches)
    enemy_player_int = int(enemy_player) if enemy_player is not None else None
    # CRITICAL FIX: Iterate over unit_positions instead of unit_player to avoid checking dead units
    # Dead units are removed from unit_positions when they die, so this ensures we only check living units
    for uid, enemy_pos in unit_positions.items():
        # Verify this is an enemy unit
        if uid not in unit_player:
            _debug_log(f"[ANALYZER WARNING] get_adjacent_enemies missing unit_player for unit_id: {uid}")
            continue
        p = require_key(unit_player, uid)
        # CRITICAL: Normalize player value to int for consistent comparison (handles int/string mismatches)
        p_int = int(p) if p is not None else None
        hp_value = _get_unit_hp_value(unit_hp, uid)
        if hp_value is None:
            continue
        if p_int == enemy_player_int and hp_value > 0:
            if is_adjacent(col, row, enemy_pos[0], enemy_pos[1]):
                return True
    return False


def is_adjacent_to_enemy(col: int, row: int, unit_player: Dict[str, int], unit_positions: Dict[str, Tuple[int, int]], 
                         unit_hp: Dict[str, int], player: int) -> bool:
    """Backward-compatible analyzer alias for legacy A/anchor hex adjacency."""
    return is_hex_anchor_adjacent_to_enemy(col, row, unit_player, unit_positions, unit_hp, player)


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
    """
    from engine.spatial_relations import unit_entries_within_engagement_zone
    from ai.analyzer_perfig import model_cache_entries

    subject_hp = _get_unit_hp_value(unit_hp, unit_id)
    if subject_hp is None or subject_hp <= 0 or unit_id not in unit_player:
        return False
    models_by_unit = positions_by_model or {}
    bases = unit_base or {}
    subject_player = int(require_key(unit_player, unit_id))
    subject_anchor = position_override if position_override is not None else unit_positions.get(unit_id)  # get allowed
    if subject_models is None and position_override is None:
        subject_models = models_by_unit.get(unit_id)  # get allowed
    subject_entries = model_cache_entries(
        unit_id, subject_models, bases, subject_anchor, subject_player
    )
    if not subject_entries:
        return False

    metric = _analyzer_engagement_metric()
    for uid, anchor in unit_positions.items():
        if uid == unit_id or uid not in unit_player:
            continue
        enemy_player = int(require_key(unit_player, uid))
        if enemy_player == subject_player:
            continue
        hp_value = _get_unit_hp_value(unit_hp, uid)
        if hp_value is None or hp_value <= 0:
            continue
        for enemy_entry in model_cache_entries(
            uid, models_by_unit.get(uid), bases, anchor, enemy_player  # get allowed
        ):
            for subject_entry in subject_entries:
                if unit_entries_within_engagement_zone(
                    subject_entry, enemy_entry, engagement_zone, metric=metric
                ):
                    return True
    return False


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


def _build_move_bfs_blockers(
    positions_by_model: Dict[str, Dict[str, Tuple[int, int]]],
    unit_positions: Dict[str, Tuple[int, int]],
    unit_base: Dict[str, Any],
    unit_player: Dict[str, int],
    unit_hp: Dict[str, int],
    mover_unit_id: str,
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
    """
    from ai.analyzer_perfig import _DEFAULT_BASE, squad_footprint
    thru_ez, thru_enemy, thru_friendly = _move_rules_for_analyzer()
    mover_player_int = int(require_key(unit_player, mover_unit_id))
    occupied: Set[Tuple[int, int]] = set()
    for uid, anchor in unit_positions.items():
        if uid == mover_unit_id:
            continue
        hp_value = _get_unit_hp_value(unit_hp, uid)
        if hp_value is None or hp_value <= 0:
            continue
        if uid not in unit_player:
            continue
        is_friendly = int(require_key(unit_player, uid)) == mover_player_int
        if is_friendly and thru_friendly:
            continue
        if not is_friendly and thru_enemy:
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
            if neighbor in wall_hexes:
                continue
            if neighbor in occupied_positions:
                continue
            # Bande d'engagement ennemie : l'appelant la fournit VIDE quand la config autorise
            # à la traverser (`can_move_through_enemy_engagement_zone`, lu par
            # `_build_move_bfs_blockers`). Le paramètre était accepté et transmis par les cinq
            # sites, mais la boucle ne le lisait pas : basculer ce toggle n'aurait rien changé.
            if neighbor in enemy_adjacent_hexes:
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
        'wins_by_scenario': defaultdict(lambda: {'p1': 0, 'p2': 0, 'draws': 0}),
        'victory_points_by_episode': {},
        'victory_points_values': {1: [], 2: []},
        'shoot_vs_wait': {
            'shoot': 0, 'wait': 0, 'skip': 0, 'advance': 0
        },
        'shoot_vs_wait_by_player': {
            1: {'shoot': 0, 'wait': 0, 'wait_with_targets': 0, 'wait_no_targets': 0, 'skip': 0, 'advance': 0},
            2: {'shoot': 0, 'wait': 0, 'wait_with_targets': 0, 'wait_no_targets': 0, 'skip': 0, 'advance': 0}
        },
        'advance_by_strategy': {
            1: {'aggressive': 0, 'tactical': 0, 'defensive': 0, 'objective': 0},
            2: {'aggressive': 0, 'tactical': 0, 'defensive': 0, 'objective': 0},
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
        'dead_unit_waiting': {1: 0, 2: 0},
        'dead_unit_skipping': {1: 0, 2: 0},
        'charge_after_flee': {1: 0, 2: 0},
        'charge_dead_unit': {1: 0, 2: 0},
        'dead_unit_charging': {1: 0, 2: 0},
        # 'fight_from_non_adjacent' RETIRE (2026-07-24) : cf. analyzer_phases/fight_handler.py —
        # gate combat moteur EUCLIDIEN + position cible pré-perte non journalisee → non
        # reconstructible. Cle conservee a 0 (jamais incrementee) pour la retro-compat des totaux.
        'fight_from_non_adjacent': {1: 0, 2: 0},
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
            'advance': {1: 0, 2: 0}
        },
        'action_phase_accuracy': {
            'move': {'total': 0, 'wrong': 0},
            'fled': {'total': 0, 'wrong': 0},
            'shoot': {'total': 0, 'wrong': 0},
            'advance': {'total': 0, 'wrong': 0},
            'charge': {'total': 0, 'wrong': 0},
            'fight': {'total': 0, 'wrong': 0}
        },
        'fight_alternation_violations': {1: 0, 2: 0},
        'fight_attacks_by_unit': {1: {}, 2: {}},
        'fight_over_cc_nb_by_unit': {1: {}, 2: {}},
        # First occurrence lines for each error type (stores dict with 'episode' and 'line')
        'first_error_lines': {
            'wall_collisions': {1: None, 2: None},
            'move_to_adjacent_enemy': {1: None, 2: None},
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
            'dead_unit_waiting': {1: None, 2: None},
            'dead_unit_skipping': {1: None, 2: None},
            'charge_after_flee': {1: None, 2: None},
            'charge_dead_unit': {1: None, 2: None},
            'dead_unit_charging': {1: None, 2: None},
            'fight_from_non_adjacent': {1: None, 2: None},
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
                'advance': {1: None, 2: None}
            },
            'action_phase_mismatch': {
                'move': None,
                'fled': None,
                'shoot': None,
                'advance': None,
                'charge': None,
                'fight': None
            },
            'fight_alternation_violations': {1: None, 2: None},
            'position_log_mismatch': {
                'move': None,
                'advance': None,
                'charge': None
            },
        },
        'unit_position_collisions': [],
        'parse_errors': [],
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
            f"{'Agent (P1)':>{TABLE_VALUE_WIDTH}} "
            f"{'Bot (P2)':>{TABLE_VALUE_WIDTH}}"
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
    log_print("-" * 80)
    log_print(f"WIN METHODS {'Agent Wins (P1)':>24} {'Bot Wins (P2)':>18}")
    log_print("-" * 80)
    
    p1_total = sum(stats['win_methods'][1].values())
    p2_total = sum(stats['win_methods'][2].values())
    draws = stats['win_methods'][-1]['draw']
    
    for method in ['elimination', 'objectives', 'value_tiebreaker']:
        p1_count = require_key(stats['win_methods'][1], method)
        p2_count = require_key(stats['win_methods'][2], method)
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
    vp_p1 = stats['victory_points_values'][PLAYER_ONE_ID]
    vp_p2 = stats['victory_points_values'][PLAYER_TWO_ID]
    if vp_p1 and vp_p2:
        vp_p1_min = min(vp_p1)
        vp_p1_max = max(vp_p1)
        vp_p1_avg = sum(vp_p1) / len(vp_p1)
        vp_p2_min = min(vp_p2)
        vp_p2_max = max(vp_p2)
        vp_p2_avg = sum(vp_p2) / len(vp_p2)
        log_print(f"{'Player':<10} {'Min':>8} {'Avg':>8} {'Max':>8}")
        log_print(f"{'P1':<10} {vp_p1_min:8.2f} {vp_p1_avg:8.2f} {vp_p1_max:8.2f}")
        log_print(f"{'P2':<10} {vp_p2_min:8.2f} {vp_p2_avg:8.2f} {vp_p2_max:8.2f}")
    else:
        log_print("No victory point data recorded (check primary_objectives in scenarios).")

    # WINS BY SCENARIO
    if stats['wins_by_scenario']:
        log_print("-" * 80)
        log_print(f"WINS BY SCENARIO {'Agent (P1)':>37} {'Bot (P2)':>13} {'Draws':>12}")
        log_print("-" * 80)
        
        scenario_totals = []
        for scenario, wins in stats['wins_by_scenario'].items():
            total = wins['p1'] + wins['p2'] + wins['draws']
            scenario_totals.append((scenario, wins, total))
        scenario_totals.sort(key=lambda x: -x[2])
        
        for scenario, wins, total in scenario_totals:
            p1_count = wins['p1']
            p2_count = wins['p2']
            draws_count = wins['draws']
            p1_pct = (p1_count / total * 100) if total > 0 else 0
            p2_pct = (p2_count / total * 100) if total > 0 else 0
            draws_pct = (draws_count / total * 100) if total > 0 else 0
            bot_match = re.search(r'bot-(\d+)', scenario, re.IGNORECASE)
            if bot_match:
                scenario_display = f"bot-{bot_match.group(1)}"
            else:
                scenario_display = scenario[:39]
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
        if action == 'advance':
            agent_adv_total = stats['shoot_vs_wait_by_player'][1]['advance']
            bot_adv_total = stats['shoot_vs_wait_by_player'][2]['advance']
            for strat in ['aggressive', 'tactical', 'defensive', 'objective']:
                agent_s = stats['advance_by_strategy'][1][strat]
                bot_s = stats['advance_by_strategy'][2][strat]
                agent_s_pct = (agent_s / agent_adv_total * 100) if agent_adv_total > 0 else 0
                bot_s_pct = (bot_s / bot_adv_total * 100) if bot_adv_total > 0 else 0
                _table_row(
                    f"  ↳ {strat.capitalize()}",
                    f"{agent_s:6d} ({agent_s_pct:5.1f}%)",
                    f"{bot_s:6d} ({bot_s_pct:5.1f}%)",
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
        log_print(f"  Agent (P1) kills: {player_kills[1]}")
        log_print(f"  Bot (P2) kills:   {player_kills[2]}")
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
            if 'adjacent_before' in first_err and 'adjacent_after' in first_err:
                before_str = ', '.join([f"Unit {uid}" for uid in first_err['adjacent_before']]) if first_err['adjacent_before'] else 'none'
                after_str = ', '.join([f"Unit {uid}" for uid in first_err['adjacent_after']]) if first_err['adjacent_after'] else 'none'
                log_print(f"    Adjacent before move: {before_str}")
                log_print(f"    Adjacent after move: {after_str}")
        if bot_move_adj > 0 and stats['first_error_lines']['move_to_adjacent_enemy'][2]:
            first_err = stats['first_error_lines']['move_to_adjacent_enemy'][2]
            log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
            if 'adjacent_before' in first_err and 'adjacent_after' in first_err:
                before_str = ', '.join([f"Unit {uid}" for uid in first_err['adjacent_before']]) if first_err['adjacent_before'] else 'none'
                after_str = ', '.join([f"Unit {uid}" for uid in first_err['adjacent_after']]) if first_err['adjacent_after'] else 'none'
                log_print(f"    Adjacent before move: {before_str}")
                log_print(f"    Adjacent after move: {after_str}")
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
    # SHOOTING ERRORS
    active_debug_section = "1.2"
    log_print("\n" + "-" * 80)
    _table_header("1.2 SHOOTING ERRORS")
    agent_shoot_invalid = (
        stats['shoot_invalid'][1]['out_of_range'] +
        stats['shoot_invalid'][1]['engaged_non_close_quarters']
    )
    bot_shoot_invalid = (
        stats['shoot_invalid'][2]['out_of_range'] +
        stats['shoot_invalid'][2]['engaged_non_close_quarters']
    )
    _table_row(
        "Tirs invalides (portee / arme non-close_quarters engage):",
        _fmt_count(agent_shoot_invalid),
        _fmt_count(bot_shoot_invalid),
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
    if agent_shoot_engaged > 0 and stats['first_error_lines']['shoot_at_engaged_enemy'][1]:
        first_err = stats['first_error_lines']['shoot_at_engaged_enemy'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_shoot_engaged > 0 and stats['first_error_lines']['shoot_at_engaged_enemy'][2]:
        first_err = stats['first_error_lines']['shoot_at_engaged_enemy'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
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
    agent_fight_alt = stats['fight_alternation_violations'][1]
    bot_fight_alt = stats['fight_alternation_violations'][2]
    _table_row("Fight alternation violations:", _fmt_count(agent_fight_alt), _fmt_count(bot_fight_alt))
    if agent_fight_alt > 0 and stats['first_error_lines']['fight_alternation_violations'][1]:
        first_err = stats['first_error_lines']['fight_alternation_violations'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_fight_alt > 0 and stats['first_error_lines']['fight_alternation_violations'][2]:
        first_err = stats['first_error_lines']['fight_alternation_violations'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
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
    log_print(f"{('2.1 ' + debug_sections['2.1']):<30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
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
    log_print(f"Dead unit skipping:            {stats['dead_unit_skipping'][1]:6d}           {stats['dead_unit_skipping'][2]:6d}")
    if stats['dead_unit_skipping'][1] > 0 and stats['first_error_lines']['dead_unit_skipping'][1]:
        first_err = stats['first_error_lines']['dead_unit_skipping'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['dead_unit_skipping'][2] > 0 and stats['first_error_lines']['dead_unit_skipping'][2]:
        first_err = stats['first_error_lines']['dead_unit_skipping'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
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
    log_print(f"{('2.3 ' + debug_sections['2.3']):<30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
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
    log_print(f"{('2.5 ' + debug_sections['2.5']):<30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
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
    unit_id_mismatches = stats.setdefault('unit_id_mismatches', [])
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

    move_errors = (
        stats['wall_collisions'][1] + stats['wall_collisions'][2] +
        stats['move_to_adjacent_enemy'][1] + stats['move_to_adjacent_enemy'][2] +
        stats['move_adjacent_before_non_flee'][1] + stats['move_adjacent_before_non_flee'][2] +
        stats['move_distance_over_limit']['move'][1] + stats['move_distance_over_limit']['move'][2] +
        stats['move_after_shooting_distance_over_limit'][1] + stats['move_after_shooting_distance_over_limit'][2] +
        stats['reactive_move_stats'][1]['abnormal'] + stats['reactive_move_stats'][2]['abnormal'] +
        stats['reactive_move_checks']['to_adjacent_enemy'][1] + stats['reactive_move_checks']['to_adjacent_enemy'][2] +
        stats['reactive_move_checks']['into_wall'][1] + stats['reactive_move_checks']['into_wall'][2] +
        stats['reactive_move_checks']['distance_over_roll'][1] + stats['reactive_move_checks']['distance_over_roll'][2]
    )
    shoot_invalid_total = (
        stats['shoot_invalid'][1]['out_of_range'] + stats['shoot_invalid'][1]['engaged_non_close_quarters'] +
        stats['shoot_invalid'][2]['out_of_range'] + stats['shoot_invalid'][2]['engaged_non_close_quarters']
    )
    shooting_errors = (
        stats['shoot_over_rng_nb'][1] + stats['shoot_over_rng_nb'][2] +
        stats['shoot_combi_profile_conflicts'][1] + stats['shoot_combi_profile_conflicts'][2] +
        stats['shoot_after_flee'][1] + stats['shoot_after_flee'][2] +
        stats['shoot_at_friendly'][1] + stats['shoot_at_friendly'][2] +
        stats['shoot_at_engaged_enemy'][1] + stats['shoot_at_engaged_enemy'][2] +
        stats['close_quarters_shot_at_unengaged_target'][1] + stats['close_quarters_shot_at_unengaged_target'][2] +
        stats['advance_after_shoot'][1] + stats['advance_after_shoot'][2] +
        stats['advance_twice_in_shoot_phase'][1] + stats['advance_twice_in_shoot_phase'][2] +
        stats['move_distance_over_limit']['advance'][1] + stats['move_distance_over_limit']['advance'][2] +
        stats['advance_from_adjacent'][1] + stats['advance_from_adjacent'][2] +
        shoot_invalid_total
    )
    charge_errors = (
        stats['charge_from_adjacent'][1] + stats['charge_from_adjacent'][2] +
        stats['charge_invalid'][1]['distance_over_roll'] + stats['charge_invalid'][2]['distance_over_roll'] +
        stats['charge_invalid'][1]['advanced'] + stats['charge_invalid'][2]['advanced'] +
        stats['charge_invalid'][1]['fled'] + stats['charge_invalid'][2]['fled']
    )
    fight_alternation_total = stats['fight_alternation_violations'][1] + stats['fight_alternation_violations'][2]
    fight_errors = (
        stats['fight_from_non_adjacent'][1] + stats['fight_from_non_adjacent'][2] +
        stats['fight_friendly'][1] + stats['fight_friendly'][2] +
        stats['fight_over_cc_nb'][1] + stats['fight_over_cc_nb'][2] +
        stats['fight_move_invalid']['pile_in'][1] + stats['fight_move_invalid']['pile_in'][2] +
        stats['fight_move_invalid']['consolidation'][1] + stats['fight_move_invalid']['consolidation'][2] +
        fight_alternation_total
    )
    dead_unit_actions = stats.setdefault('dead_unit_actions', [])
    dead_unit_interactions_total = (
        stats['dead_unit_moving'][1] + stats['dead_unit_moving'][2] +
        stats['shoot_dead_unit'][1] + stats['shoot_dead_unit'][2] +
        stats['shoot_at_dead_unit'][1] + stats['shoot_at_dead_unit'][2] +
        stats['dead_unit_advancing'][1] + stats['dead_unit_advancing'][2] +
        stats['dead_unit_charging'][1] + stats['dead_unit_charging'][2] +
        stats['charge_dead_unit'][1] + stats['charge_dead_unit'][2] +
        stats['fight_dead_unit_attacker'][1] + stats['fight_dead_unit_attacker'][2] +
        stats['fight_dead_unit_target'][1] + stats['fight_dead_unit_target'][2] +
        stats['dead_unit_waiting'][1] + stats['dead_unit_waiting'][2] +
        stats['dead_unit_skipping'][1] + stats['dead_unit_skipping'][2] +
        stats['unit_revived'][1] + stats['unit_revived'][2]
    )
    unit_collisions = len(stats['unit_position_collisions'])
    pos_mismatch_total = (
        stats['position_log_mismatch']['move']['mismatch'] +
        stats['position_log_mismatch']['advance']['mismatch'] +
        stats['position_log_mismatch']['charge']['mismatch'] +
        unit_collisions
    )

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
    action_phase_accuracy = require_key(stats, "action_phase_accuracy")
    wrong_phase_total = sum(require_key(action_phase_accuracy[key], "wrong") for key in action_phase_accuracy)
    log_print(f"{summary_error_icon(wrong_phase_total > 0)} 1.5 Actions occuring in the wrong phase : {wrong_phase_total}")
    double_activation_by_phase = require_key(stats, "double_activation_by_phase")
    double_activation_total = sum(double_activation_by_phase.values())
    log_print(f"{summary_error_icon(double_activation_total > 0)} 1.6 Double-activation par phase : {double_activation_total}")
    special_rule_usage_total = sum(
        counts.get(1, 0) + counts.get(2, 0)  # get allowed: optional player counts
        for counts in stats.get('special_rule_usage', defaultdict(lambda: {1: 0, 2: 0})).values()  # get allowed: optional stats
    )
    weapon_rule_usage_total = sum(
        counts.get(1, 0) + counts.get(2, 0)  # get allowed: optional player counts
        for counts in stats.get('weapon_rule_usage', defaultdict(lambda: {1: 0, 2: 0})).values()  # get allowed: optional stats
    )
    rule_to_units = stats.get('rule_to_units', {})  # get allowed: optional stats
    weapon_rule_to_weapons = stats.get('weapon_rule_to_weapons', {})  # get allowed: optional stats
    special_rule_usage_stats = require_key(stats, 'special_rule_usage')
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
    special_rules_invalid = sum(
        1 for (rid, ut) in special_rule_usage_stats.keys()
        if (rid not in rule_to_units) or (ut not in rule_to_units[rid])
    )
    weapon_rules_invalid = sum(
        1 for (rname, wkey) in weapon_rule_usage_stats.keys()
        if (rname not in weapon_rule_to_weapons) or (wkey not in weapon_rule_to_weapons[rname])
    )
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
    dmg_issues_total = (
        stats['damage_missing_unit_hp'][1] + stats['damage_missing_unit_hp'][2] +
        stats['damage_exceeds_hp'][1] + stats['damage_exceeds_hp'][2]
    )
    core_issues_total = len(stats['parse_errors']) + len(stats['unit_id_mismatches'])
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
    episodes_ending_total = len(stats['episodes_without_end']) + len(stats['episodes_without_method'])
    log_print(f"{summary_error_icon(episodes_ending_total > 0)} 2.5 Episode ending : {episodes_ending_total}")
    log_print(f"{summary_error_icon(len(missing_samples) > 0)} 2.6 Sample missing ({len(missing_samples)}/{len(sample_action_types)}) : {missing_samples_label}")
    log_print(f"{summary_error_icon(core_issues_total > 0)} 2.7 Core issue : {core_issues_total}")

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
        
        # Calculate total errors (all error counts between MOVEMENT ERRORS and SAMPLE ACTIONS)
        shoot_invalid_total = (
            stats['shoot_invalid'][1]['out_of_range'] + stats['shoot_invalid'][1]['engaged_non_close_quarters'] +
            stats['shoot_invalid'][2]['out_of_range'] + stats['shoot_invalid'][2]['engaged_non_close_quarters']
        )
        move_errors = (
            stats['wall_collisions'][1] + stats['wall_collisions'][2] +
            stats['move_to_adjacent_enemy'][1] + stats['move_to_adjacent_enemy'][2] +
            stats['move_adjacent_before_non_flee'][1] + stats['move_adjacent_before_non_flee'][2] +
            stats['move_distance_over_limit']['move'][1] + stats['move_distance_over_limit']['move'][2] +
                stats['reactive_move_stats'][1]['abnormal'] + stats['reactive_move_stats'][2]['abnormal'] +
            stats['reactive_move_checks']['to_adjacent_enemy'][1] + stats['reactive_move_checks']['to_adjacent_enemy'][2] +
            stats['reactive_move_checks']['into_wall'][1] + stats['reactive_move_checks']['into_wall'][2] +
                stats['reactive_move_checks']['distance_over_roll'][1] + stats['reactive_move_checks']['distance_over_roll'][2]
        )
        shooting_errors = (
            stats['shoot_over_rng_nb'][1] + stats['shoot_over_rng_nb'][2] +
            stats['shoot_after_flee'][1] + stats['shoot_after_flee'][2] +
            stats['shoot_at_friendly'][1] + stats['shoot_at_friendly'][2] +
            stats['shoot_at_engaged_enemy'][1] + stats['shoot_at_engaged_enemy'][2] +
            stats['close_quarters_shot_at_unengaged_target'][1] + stats['close_quarters_shot_at_unengaged_target'][2] +
            stats['advance_after_shoot'][1] + stats['advance_after_shoot'][2] +
            stats['advance_twice_in_shoot_phase'][1] + stats['advance_twice_in_shoot_phase'][2] +
            stats['move_distance_over_limit']['advance'][1] + stats['move_distance_over_limit']['advance'][2] +
            stats['advance_from_adjacent'][1] + stats['advance_from_adjacent'][2] +
                shoot_invalid_total
        )
        charge_errors = (
            stats['charge_from_adjacent'][1] + stats['charge_from_adjacent'][2] +
            stats['charge_invalid'][1]['distance_over_roll'] + stats['charge_invalid'][2]['distance_over_roll'] +
            stats['charge_invalid'][1]['advanced'] + stats['charge_invalid'][2]['advanced'] +
            stats['charge_invalid'][1]['fled'] + stats['charge_invalid'][2]['fled']
        )
        fight_errors = (
            stats['fight_from_non_adjacent'][1] + stats['fight_from_non_adjacent'][2] +
            stats['fight_friendly'][1] + stats['fight_friendly'][2] +
            stats['fight_over_cc_nb'][1] + stats['fight_over_cc_nb'][2] +
            stats['fight_move_invalid']['pile_in'][1] + stats['fight_move_invalid']['pile_in'][2] +
            stats['fight_move_invalid']['consolidation'][1] + stats['fight_move_invalid']['consolidation'][2] +
            stats['fight_alternation_violations'][1] + stats['fight_alternation_violations'][2]
        )
        action_phase_accuracy = require_key(stats, "action_phase_accuracy")
        wrong_phase_total = sum(require_key(action_phase_accuracy[key], "wrong") for key in action_phase_accuracy)
        dead_unit_interactions_total = (
            stats['dead_unit_moving'][1] + stats['dead_unit_moving'][2] +
            stats['shoot_dead_unit'][1] + stats['shoot_dead_unit'][2] +
            stats['shoot_at_dead_unit'][1] + stats['shoot_at_dead_unit'][2] +
            stats['dead_unit_advancing'][1] + stats['dead_unit_advancing'][2] +
            stats['dead_unit_charging'][1] + stats['dead_unit_charging'][2] +
            stats['charge_dead_unit'][1] + stats['charge_dead_unit'][2] +
            stats['fight_dead_unit_attacker'][1] + stats['fight_dead_unit_attacker'][2] +
            stats['fight_dead_unit_target'][1] + stats['fight_dead_unit_target'][2] +
            stats['dead_unit_waiting'][1] + stats['dead_unit_waiting'][2] +
            stats['dead_unit_skipping'][1] + stats['dead_unit_skipping'][2] +
            stats['unit_revived'][1] + stats['unit_revived'][2]
        )
        pos_mismatch_total = (
            stats['position_log_mismatch']['move']['mismatch'] +
            stats['position_log_mismatch']['advance']['mismatch'] +
            stats['position_log_mismatch']['charge']['mismatch'] +
            len(stats['unit_position_collisions'])
        )
        dmg_issues_total = (
            stats['damage_missing_unit_hp'][1] + stats['damage_missing_unit_hp'][2] +
            stats['damage_exceeds_hp'][1] + stats['damage_exceeds_hp'][2]
        )
        episodes_ending_total = len(stats['episodes_without_end']) + len(stats['episodes_without_method'])
        unit_id_mismatch_total = len(stats['unit_id_mismatches']) if 'unit_id_mismatches' in stats else 0
        core_issues_total = len(stats['parse_errors']) + unit_id_mismatch_total
        weapon_rule_to_weapons = require_key(stats, 'weapon_rule_to_weapons')
        weapon_rule_usage = require_key(stats, 'weapon_rule_usage')
        unit_types_seen = set(require_key(stats, "unit_types_seen"))
        unit_type_suffixes = tuple(f" ({unit_type})" for unit_type in unit_types_seen)
        expected_weapon_rule_pairs = {
            (rname, wkey)
            for rname, wkeys in weapon_rule_to_weapons.items()
            for wkey in wkeys
            if unit_type_suffixes and wkey.endswith(unit_type_suffixes)
        }
        weapon_rule_not_used_warnings = sum(
            1
            for (rname, wkey) in expected_weapon_rule_pairs
            if _weapon_rule_usage_pair_total(weapon_rule_usage, (rname, wkey)) == 0
        )
        weapon_rules_invalid = sum(
            1 for (rname, wkey) in weapon_rule_usage.keys()
            if (rname not in weapon_rule_to_weapons) or (wkey not in weapon_rule_to_weapons[rname])
        )
        sample_action_types = ['move', 'shoot', 'advance', 'charge', 'fight']
        missing_samples = [action for action in sample_action_types if not stats['sample_actions'][action]]
        total_errors = (
            move_errors +
            shooting_errors +
            charge_errors +
            fight_errors +
            wrong_phase_total +
            dead_unit_interactions_total +
            pos_mismatch_total +
            dmg_issues_total +
            episodes_ending_total +
            core_issues_total +
            weapon_rules_invalid +
            len(missing_samples)
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
                "Bot (P2) kills:"
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