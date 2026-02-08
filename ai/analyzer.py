#!/usr/bin/env python3
"""
analyzer.py - Analyze step.log and validate game rules compliance
Run this locally: python ai/analyzer.py step.log
"""

import sys
import os
import re
import math
import json
from collections import defaultdict, Counter
from typing import Dict, List, Tuple, Set, Optional, Any

# Add project root to Python path for imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import utility functions from engine
from engine.combat_utils import (
    calculate_hex_distance,
    get_hex_line,
    get_hex_neighbors,
    normalize_coordinates,
)
from shared.data_validation import require_key

MAX_D3 = 3
MAX_D6 = 6
DICE_MAX_VALUES = {"D3": MAX_D3, "D6": MAX_D6}
PLAYER_ONE_ID = 1
PLAYER_TWO_ID = 2


def max_dice_value(value: Any, context: str) -> int:
    """
    Resolve a dice value to its maximum possible roll (no RNG).

    Supported dice strings: "D3", "D6".
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
_scenario_objective_name_to_id_cache: Dict[str, Dict[str, int]] = {}
_scenario_primary_objective_ids_cache: Dict[str, List[str]] = {}


def _debug_log(message: str) -> None:
    """Write debug message to analyzer_debug.log if file is open."""
    global _debug_log_file
    if _debug_log_file:
        _debug_log_file.write(message + "\n")
        _debug_log_file.flush()


def _resolve_scenario_path(scenario_name: str) -> str:
    """Resolve scenario path from scenario name (no fallbacks)."""
    if not scenario_name or scenario_name == "Unknown":
        raise ValueError("Scenario name is missing or unknown; cannot resolve objectives mapping")
    candidate_names = [scenario_name]
    if not scenario_name.endswith(".json"):
        candidate_names.append(f"{scenario_name}.json")
    candidate_paths = []
    for name in candidate_names:
        candidate_paths.append(os.path.join(project_root, name))
        candidate_paths.append(os.path.join(project_root, "config", name))
    existing_paths = [path for path in candidate_paths if os.path.exists(path)]
    if len(existing_paths) == 1:
        return existing_paths[0]
    if len(existing_paths) > 1:
        raise ValueError(f"Ambiguous scenario path for '{scenario_name}': {existing_paths}")
    scenarios_root = os.path.join(project_root, "config", "agents")
    if os.path.exists(scenarios_root):
        matches = []
        for root, _, files in os.walk(scenarios_root):
            if os.path.basename(root) != "scenarios":
                continue
            for name in candidate_names:
                if name in files:
                    matches.append(os.path.join(root, name))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"Ambiguous scenario path for '{scenario_name}': {matches}")
    raise FileNotFoundError(f"Scenario file not found for '{scenario_name}'")


def _get_objective_name_to_id_map(scenario_name: str) -> Dict[str, int]:
    """Load objective name->id mapping from scenario file."""
    scenario_path = _resolve_scenario_path(scenario_name)
    if scenario_path in _scenario_objective_name_to_id_cache:
        return _scenario_objective_name_to_id_cache[scenario_path]
    with open(scenario_path, "r", encoding="utf-8-sig") as f:
        scenario_data = json.load(f)
    objectives = scenario_data.get("objectives")
    if not isinstance(objectives, list) or not objectives:
        raise ValueError(f"Scenario '{scenario_name}' missing objectives list: {scenario_path}")
    mapping: Dict[str, int] = {}
    for entry in objectives:
        if "id" not in entry or "name" not in entry:
            raise KeyError(f"Objective entry missing id or name in {scenario_path}: {entry}")
        name = str(entry["name"]).strip()
        if not name:
            raise ValueError(f"Objective entry has empty name in {scenario_path}: {entry}")
        if name in mapping:
            raise ValueError(f"Duplicate objective name '{name}' in {scenario_path}")
        mapping[name] = int(entry["id"])
    _scenario_objective_name_to_id_cache[scenario_path] = mapping
    return mapping


def _get_primary_objective_ids_for_scenario(scenario_name: str) -> List[str]:
    """Load primary objective ids list from scenario file (no fallbacks)."""
    scenario_path = _resolve_scenario_path(scenario_name)
    if scenario_path in _scenario_primary_objective_ids_cache:
        return list(_scenario_primary_objective_ids_cache[scenario_path])
    with open(scenario_path, "r", encoding="utf-8-sig") as f:
        scenario_data = json.load(f)
    if "primary_objectives" in scenario_data:
        primary_ids = scenario_data["primary_objectives"]
    elif "primary_objective" in scenario_data:
        primary_ids = [scenario_data["primary_objective"]]
    else:
        raise KeyError(
            f"Scenario '{scenario_name}' missing primary_objectives (or primary_objective): {scenario_path}"
        )
    if not isinstance(primary_ids, list) or not primary_ids:
        raise ValueError(
            f"Scenario '{scenario_name}' has invalid primary_objectives: {primary_ids!r}"
        )
    normalized_ids = []
    for obj_id in primary_ids:
        if not obj_id:
            raise ValueError(
                f"Scenario '{scenario_name}' has empty primary objective id: {primary_ids!r}"
            )
        normalized_ids.append(str(obj_id))
    _scenario_primary_objective_ids_cache[scenario_path] = normalized_ids
    return list(normalized_ids)


def _calculate_primary_objective_points(
    control_snapshot: Dict[int, Dict[str, Any]],
    primary_objective_cfg: Dict[str, Any],
    player_id: int
) -> int:
    """Calculate primary objective points for a player from control snapshot."""
    scoring_cfg = require_key(primary_objective_cfg, "scoring")
    max_points_per_turn = require_key(scoring_cfg, "max_points_per_turn")
    rules = require_key(scoring_cfg, "rules")

    counts = {PLAYER_ONE_ID: 0, PLAYER_TWO_ID: 0}
    for _, data in control_snapshot.items():
        controller = require_key(data, "controller")
        if controller in counts:
            counts[controller] += 1

    opponent_id = PLAYER_ONE_ID if player_id == PLAYER_TWO_ID else PLAYER_TWO_ID
    total_points = 0
    for rule in rules:
        condition = require_key(rule, "condition")
        points = require_key(rule, "points")
        if condition == "control_at_least_one":
            if counts[player_id] >= 1:
                total_points += points
        elif condition == "control_at_least_two":
            if counts[player_id] >= 2:
                total_points += points
        elif condition == "control_more_than_opponent":
            if counts[player_id] > counts[opponent_id]:
                total_points += points
        else:
            raise ValueError(f"Unsupported primary objective condition: {condition}")

    if total_points > max_points_per_turn:
        total_points = max_points_per_turn
    return total_points


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
    damage: int,
    player: int,
    turn: int,
    phase: str,
    line_number: int,
    current_episode_num: int,
    line_text: str,
    dead_units_current_episode: Set[str],
    unit_hp: Dict[str, int],
    unit_types: Dict[str, str],
    unit_positions: Dict[str, Tuple[int, int]],
    unit_deaths: List[Tuple[int, str, str, int]],
    stats: Dict[str, Any]
) -> None:
    """Apply damage to target and remove unit when HP <= 0."""
    if damage <= 0:
        return
    if target_id not in unit_hp:
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
    if damage > unit_hp[target_id]:
        # Overkill is valid in W40K (e.g., multi-damage weapons vs 1HP targets).
        # Keep as debug signal only, do not count as error.
        _debug_log(
            f"[DAMAGE OVERKILL] E{current_episode_num} T{turn} {phase} "
            f"target_id={target_id} damage={damage} hp_before={unit_hp[target_id]}"
        )
    _debug_log(
        f"[DAMAGE APPLY] E{current_episode_num} T{turn} {phase} "
        f"target_id={target_id} damage={damage} old_hp={unit_hp[target_id]}"
    )
    unit_hp[target_id] -= damage
    if unit_hp[target_id] <= 0:
        target_type = require_key(unit_types, target_id)
        stats['current_episode_deaths'].append((player, target_id, target_type))
        stats['wounded_enemies'][player].discard(target_id)
        _position_cache_remove(unit_positions, target_id)
        # Track death with line number for chronological order checking
        unit_deaths.append((turn, phase, target_id, line_number))
        dead_units_current_episode.add(target_id)
        _debug_log(
            f"[DEATH REMOVED] E{current_episode_num} T{turn} {phase} "
            f"target_id={target_id} target_type={target_type}"
        )
        del unit_hp[target_id]
    else:
        stats['wounded_enemies'][player].add(target_id)
        _debug_log(
            f"[DAMAGE RESULT] E{current_episode_num} T{turn} {phase} "
            f"target_id={target_id} new_hp={unit_hp[target_id]}"
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


def has_line_of_sight(shooter_col: int, shooter_row: int, target_col: int, target_row: int, wall_hexes: Set[Tuple[int, int]]) -> bool:
    """
    Check line of sight using the same algorithm as the game engine.
    
    CRITICAL: Uses _get_accurate_hex_line algorithm (cube coordinates) to match
    the game engine's LoS calculation exactly. This ensures analyzer detects
    the same LoS violations as the game engine.
    
    Algorithm:
    1. Calculate hex path from shooter to target using cube coordinates
    2. Check if any hex in path (excluding start and end) is a wall
    3. If any wall found, LoS is blocked; otherwise, LoS is clear
    """
    if not wall_hexes:
        return True
    
    # CRITICAL: Use the same algorithm as game engine (_get_accurate_hex_line)
    # get_hex_line from combat_utils calls shooting_handlers._get_accurate_hex_line
    try:
        # CRITICAL: Normalize input coordinates to int before calculating path
        # This ensures consistent comparison with wall_hexes set
        shooter_col_int = int(shooter_col)
        shooter_row_int = int(shooter_row)
        target_col_int = int(target_col)
        target_row_int = int(target_row)
        
        # Calculate hex path from shooter to target
        hex_path = get_hex_line(shooter_col_int, shooter_row_int, target_col_int, target_row_int)
        
        # Check if any hex in path (excluding start and end) is a wall
        # CRITICAL: Convert coordinates to int for consistent comparison with wall_hexes set
        for i, (col, row) in enumerate(hex_path):
            # Skip start and end hexes (same as game engine)
            if i == 0 or i == len(hex_path) - 1:
                continue
            
            # CRITICAL: Convert to int for consistent comparison with wall_hexes set
            col_int = int(col)
            row_int = int(row)
            
            if (col_int, row_int) in wall_hexes:
                # Wall found in path - LoS is blocked
                return False
        
        # No walls blocking - line of sight is clear
        return True
        
    except Exception as e:
        # On error, deny line of sight (fail-safe, same as game engine)
        return False


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


def is_adjacent_to_enemy(col: int, row: int, unit_player: Dict[str, int], unit_positions: Dict[str, Tuple[int, int]], 
                         unit_hp: Dict[str, int], player: int) -> bool:
    """Check if a hex is adjacent to any enemy unit."""
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


def _build_occupied_positions(
    unit_positions: Dict[str, Tuple[int, int]],
    unit_hp: Dict[str, int],
    exclude_unit_id: str
) -> Set[Tuple[int, int]]:
    """Build set of occupied positions (alive units only), excluding one unit."""
    occupied = set()
    for uid, pos in unit_positions.items():
        if uid == exclude_unit_id:
            continue
        if uid not in unit_hp:
            continue
        if require_key(unit_hp, uid) <= 0:
            continue
        occupied.add(pos)
    return occupied


def _bfs_shortest_path_length(
    start_col: int,
    start_row: int,
    dest_col: int,
    dest_row: int,
    max_steps: int,
    wall_hexes: Set[Tuple[int, int]],
    occupied_positions: Set[Tuple[int, int]],
    enemy_adjacent_hexes: Set[Tuple[int, int]]
) -> Optional[int]:
    """Compute shortest path length using movement BFS rules."""
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
            next_dist = current_dist + 1
            if neighbor == dest_pos:
                return next_dist
            visited[neighbor] = next_dist
            queue.append(neighbor)
    return None


def _track_action_phase_accuracy(
    stats: Dict[str, Any],
    action_type: str,
    phase: str,
    current_episode_num: int,
    line_text: str
) -> None:
    """Track action/phase alignment accuracy."""
    expected_phase_by_action = {
        "move": "MOVE",
        "fled": "MOVE",
        "shoot": "SHOOT",
        "advance": "SHOOT",
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


def is_engaged(unit_id: str, unit_player: Dict[str, int], unit_positions: Dict[str, Tuple[int, int]], 
               unit_hp: Dict[str, int]) -> bool:
    """Check if a unit is engaged (adjacent to an enemy)."""
    if unit_id not in unit_positions:
        return False
    
    player = require_key(unit_player, unit_id)
    
    unit_pos = unit_positions[unit_id]
    return is_adjacent_to_enemy(unit_pos[0], unit_pos[1], unit_player, unit_positions, unit_hp, player)


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


def _calculate_objective_control_snapshot(
    objective_hexes: Dict[int, Set[Tuple[int, int]]],
    objective_controllers: Dict[int, Optional[int]],
    unit_positions: Dict[str, Tuple[int, int]],
    unit_player: Dict[str, int],
    unit_types: Dict[str, str],
    unit_registry: Any,
) -> Dict[int, Dict[str, Any]]:
    """
    Calculate persistent objective control snapshot for analyzer history.
    """
    snapshot: Dict[int, Dict[str, Any]] = {}
    for obj_id, hexes in objective_hexes.items():
        player_1_oc = 0
        player_2_oc = 0
        for unit_id, unit_pos in unit_positions.items():
            normalized_pos = normalize_coordinates(unit_pos[0], unit_pos[1])
            if normalized_pos in hexes:
                unit_type = require_key(unit_types, unit_id)
                unit_data = require_key(unit_registry.units, unit_type)
                oc = require_key(unit_data, "OC")
                unit_player_id = require_key(unit_player, unit_id)
                unit_player_int = int(unit_player_id)
                if unit_player_int == PLAYER_ONE_ID:
                    player_1_oc += oc
                elif unit_player_int == PLAYER_TWO_ID:
                    player_2_oc += oc
                else:
                    raise ValueError(
                        f"Unexpected unit player id {unit_player_id} for unit {unit_id}"
                    )

        if obj_id not in objective_controllers:
            objective_controllers[obj_id] = None
        current_controller = objective_controllers[obj_id]
        new_controller = current_controller
        if player_1_oc > player_2_oc:
            new_controller = PLAYER_ONE_ID
        elif player_2_oc > player_1_oc:
            new_controller = PLAYER_TWO_ID
        objective_controllers[obj_id] = new_controller

        snapshot[obj_id] = {
            "player_1_oc": player_1_oc,
            "player_2_oc": player_2_oc,
            "controller": new_controller,
        }

    return snapshot


def parse_step_log(filepath: str) -> Dict:
    """Parse step.log and extract statistics with rule validation."""
    
    # Open debug log file
    global _debug_log_file
    debug_log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'analyzer_debug.log')
    _debug_log_file = open(debug_log_path, 'w', encoding='utf-8')
    _debug_log(f"=== ANALYZER DEBUG LOG ===")
    _debug_log(f"Analyzing {filepath}")
    _debug_log("=" * 80)
    
    # Load unit weapons at script start
    from ai.unit_registry import UnitRegistry
    from config_loader import get_config_loader
    
    unit_registry = UnitRegistry()
    config_loader = get_config_loader()
    unit_weapons_cache = {}  # unit_type -> list of weapons with {display_name, RNG, WEAPON_RULES, is_pistol}
    unit_attack_limits = {}  # unit_type -> {'rng_nb_by_weapon': Dict[str, int], 'cc_nb_by_weapon': Dict[str, int]}
    unit_combi_by_weapon = {}  # unit_type -> {weapon_display_name: combi_key}
    unit_rules_by_type = {}  # unit_type -> set(ruleId)
    
    # Load weapons for each unit type
    for unit_type, unit_data in unit_registry.units.items():
        rng_weapons = require_key(unit_data, "RNG_WEAPONS")
        cc_weapons = require_key(unit_data, "CC_WEAPONS")
        rng_nb_by_weapon = {}
        combi_by_weapon = {}
        for weapon in rng_weapons:
            if isinstance(weapon, dict):
                weapon_name = require_key(weapon, "display_name")
                rng_nb_by_weapon[weapon_name] = max_dice_value(
                    require_key(weapon, "NB"),
                    "analyzer_rng_nb",
                )
                combi_key = weapon.get("COMBI_WEAPON")
                if combi_key is not None:
                    combi_by_weapon[weapon_name] = combi_key
        cc_nb_by_weapon = {}
        for weapon in cc_weapons:
            if isinstance(weapon, dict):
                weapon_name = require_key(weapon, "display_name")
                cc_nb_by_weapon[weapon_name] = max_dice_value(
                    require_key(weapon, "NB"),
                    "analyzer_cc_nb",
                )
        unit_attack_limits[unit_type] = {
            'rng_nb_by_weapon': rng_nb_by_weapon,
            'cc_nb_by_weapon': cc_nb_by_weapon
        }
        weapons_info = []
        for weapon in rng_weapons:
            if isinstance(weapon, dict):
                weapon_rules = require_key(weapon, "WEAPON_RULES")
                weapons_info.append({
                    'name': require_key(weapon, 'display_name'),
                    'range': require_key(weapon, 'RNG'),
                    'rules': weapon_rules,
                    'is_pistol': 'PISTOL' in weapon_rules
                })
        unit_weapons_cache[unit_type] = weapons_info
        unit_combi_by_weapon[unit_type] = combi_by_weapon
        unit_rules = require_key(unit_data, "UNIT_RULES")
        unit_rules_by_type[unit_type] = {require_key(rule, "ruleId") for rule in unit_rules}

    # Statistics structure
    stats = {
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
        'shots_after_advance': {1: 0, 2: 0},
        'pistol_shots': {
            1: {'adjacent': 0, 'not_adjacent': 0},
            2: {'adjacent': 0, 'not_adjacent': 0}
        },
        'non_pistol_adjacent_shots': {1: 0, 2: 0},
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
        'wounded_enemies': {1: set(), 2: set()},
        # Rule violations
        'wall_collisions': {1: 0, 2: 0},
        'move_to_adjacent_enemy': {1: 0, 2: 0},
        'dead_unit_moving': {1: 0, 2: 0},
        'charge_from_adjacent': {1: 0, 2: 0},
        'advance_from_adjacent': {1: 0, 2: 0},
        'dead_unit_advancing': {1: 0, 2: 0},
        'shoot_through_wall': {1: 0, 2: 0},
        'shoot_after_fled': {1: 0, 2: 0},
        'shoot_at_friendly': {1: 0, 2: 0},
        'shoot_at_engaged_enemy': {1: 0, 2: 0},
        'shoot_dead_unit': {1: 0, 2: 0},
        'shoot_at_dead_unit': {1: 0, 2: 0},
        'shoot_over_rng_nb': {1: 0, 2: 0},
        'shoot_combi_profile_conflicts': {1: 0, 2: 0},
        'dead_unit_waiting': {1: 0, 2: 0},
        'dead_unit_skipping': {1: 0, 2: 0},
        'charge_after_fled': {1: 0, 2: 0},
        'charge_dead_unit': {1: 0, 2: 0},
        'dead_unit_charging': {1: 0, 2: 0},
        'fight_from_non_adjacent': {1: 0, 2: 0},
        'fight_friendly': {1: 0, 2: 0},
        'fight_dead_unit_attacker': {1: 0, 2: 0},
        'fight_dead_unit_target': {1: 0, 2: 0},
        'fight_over_cc_nb': {1: 0, 2: 0},
        'double_activation_by_phase': {
            'MOVE': 0, 'SHOOT': 0, 'CHARGE': 0, 'FIGHT': 0
        },
        'advance_after_shoot': {1: 0, 2: 0},
        'position_log_mismatch': {
            'move': {'total': 0, 'mismatch': 0, 'missing': 0},
            'advance': {'total': 0, 'mismatch': 0, 'missing': 0},
            'charge': {'total': 0, 'mismatch': 0, 'missing': 0}
        },
        'damage_missing_unit_hp': {1: 0, 2: 0},
        'damage_exceeds_hp': {1: 0, 2: 0},
        'unit_revived': {1: 0, 2: 0},
        'shoot_invalid': {
            1: {'total': 0, 'no_los': 0, 'out_of_range': 0, 'adjacent_non_pistol': 0},
            2: {'total': 0, 'no_los': 0, 'out_of_range': 0, 'adjacent_non_pistol': 0}
        },
        'charge_invalid': {
            1: {'total': 0, 'distance_over_roll': 0, 'advanced': 0, 'fled': 0},
            2: {'total': 0, 'distance_over_roll': 0, 'advanced': 0, 'fled': 0}
        },
        'charge_after_advance_used': {1: 0, 2: 0},
        'move_adjacent_before_non_flee': {1: 0, 2: 0},
        'move_distance_over_limit': {
            'move': {1: 0, 2: 0},
            'advance': {1: 0, 2: 0}
        },
        'move_path_blocked': {
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
            'shoot_through_wall': {1: None, 2: None},
            'shoot_after_fled': {1: None, 2: None},
            'shoot_at_friendly': {1: None, 2: None},
            'shoot_at_engaged_enemy': {1: None, 2: None},
            'shoot_dead_unit': {1: None, 2: None},
            'shoot_at_dead_unit': {1: None, 2: None},
            'shoot_over_rng_nb': {1: None, 2: None},
            'shoot_combi_profile_conflicts': {1: None, 2: None},
            'dead_unit_waiting': {1: None, 2: None},
            'dead_unit_skipping': {1: None, 2: None},
            'charge_after_fled': {1: None, 2: None},
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
            'advance_after_shoot': {1: None, 2: None},
            'damage_missing_unit_hp': {1: None, 2: None},
            'damage_exceeds_hp': {1: None, 2: None},
            'unit_revived': {1: None, 2: None},
            'fled_action': {1: None, 2: None},
            'shoot_invalid': {
                1: None,
                2: None
            },
            'charge_invalid': {1: None, 2: None},
            'move_adjacent_before_non_flee': {1: None, 2: None},
            'move_distance_over_limit': {
                'move': {1: None, 2: None},
                'advance': {1: None, 2: None}
            },
            'move_path_blocked': {
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
        'objective_control_history': {},
        'sample_actions': {
            'move': None,
            'shoot': None,
            'advance': None,
            'charge': None,
            'fight': None
        }
    }

    # Current episode state
    current_episode = []
    current_episode_num = 0
    current_scenario = 'Unknown'
    episode_turn = 0
    episode_actions = 0
    last_turn = 0
    episode_start_time = None  # Timestamp of episode start for duration calculation

    # Unit tracking
    unit_hp = {}
    unit_player = {}
    # Position cache: unit_id -> (col, row). Single source of truth for positions in the analyzer.
    # Updated on every: UNIT (init), MOVE, FLED, ADVANCE, CHARGE, SHOT (shooter + target when coords in log),
    # FIGHT (target). Removed on unit death. Use _position_cache_set / _position_cache_remove for all updates.
    unit_positions = {}
    unit_types = {}
    unit_move = {}
    wall_hexes = set()
    objective_hexes: Dict[int, Set[Tuple[int, int]]] = {}
    objective_controllers: Dict[int, Optional[int]] = {}
    
    # Track unit deaths with line numbers for chronological order checking
    unit_deaths = []  # List of (turn, phase, unit_id, line_num) tuples
    line_number = 0  # Track line number for chronological order
    dead_units_current_episode = set()
    revived_units_current_episode = set()
    
    # Track all unit movements from logs (source of truth for collision detection)
    # Maps unit_id -> list of (position, timestamp, action_type) tuples
    unit_movement_history = {}
    shot_sequence_counts = {}
    fight_sequence_counts = {}
    last_shoot_shooter_id = None
    last_shoot_weapon = None
    last_shoot_target_id = None
    last_fight_fighter_id = None
    last_fight_weapon = None
    
    # Turn/phase markers
    units_moved = set()
    units_shot = set()
    units_fled = set()
    units_advanced = set()
    units_fought = set()
    charged_units_current_fight = set()
    charged_units_fought = set()
    positions_at_turn_start = {}
    positions_at_move_phase_start = {}  # Track positions at start of MOVE phase to detect fled
    last_player = None  # Track last player to detect phase MOVE start for each player
    last_phase = None
    phase_activation_seen: Dict[Tuple[int, str, int], Set[str]] = {}
    fight_phase_seq_id = 0
    episode_step_index = 0
    last_objective_snapshot = None
    seen_turn_player: Set[Tuple[int, int]] = set()
    episode_victory_points = {PLAYER_ONE_ID: 0, PLAYER_TWO_ID: 0}
    scored_turns: Set[Tuple[str, int, int]] = set()
    primary_objective_configs: List[Dict[str, Any]] = []

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line_number += 1
            # Episode start
            if '=== EPISODE' in line and 'START ===' in line:
                if current_episode:
                    stats['episodes_without_end'].append({
                        'episode_num': current_episode_num,
                        'actions': episode_actions,
                        'turn': episode_turn,
                        'last_line': current_episode[-1][:100] if current_episode else 'N/A'
                    })
                    
                    if stats['current_episode_deaths']:
                        stats['death_orders'].append(tuple(stats['current_episode_deaths']))

                    stats['episode_lengths'].append((current_episode_num, episode_actions))
                    if episode_turn > 0:
                        stats['turns_distribution'][episode_turn] += 1

                current_episode = []
                stats['total_episodes'] += 1
                current_episode_num = stats['total_episodes']
                episode_turn = 0
                episode_actions = 0
                episode_step_index = 0
                # Capture episode start timestamp for duration calculation
                episode_start_time = parse_timestamp_to_seconds(line)
                stats['current_episode_deaths'] = []
                stats['wounded_enemies'] = {1: set(), 2: set()}
                unit_hp = {}
                unit_player = {}
                unit_positions = {}
                unit_types = {}
                unit_move = {}
                wall_hexes = set()
                objective_hexes = {}
                objective_controllers = {}
                positions_at_turn_start = {}
                positions_at_move_phase_start = {}
                dead_units_current_episode = set()
                revived_units_current_episode = set()
                current_scenario = 'Unknown'
                units_moved = set()
                units_shot = set()
                units_fled = set()  # Reset at episode start is correct
                units_advanced = set()
                units_fought = set()
                charged_units_current_fight = set()
                charged_units_fought = set()
                unit_movement_history = {}  # Reset movement history for new episode
                shot_sequence_counts = {}
                fight_sequence_counts = {}
                last_fight_fighter_id = None
                last_fight_weapon = None
                combi_profile_usage = {}
                combi_conflicts_seen = set()
                unit_deaths = []  # Reset deaths tracking for new episode
                stats['objective_control_history'][current_episode_num] = []
                last_objective_snapshot = None
                seen_turn_player = set()
                episode_victory_points = {PLAYER_ONE_ID: 0, PLAYER_TWO_ID: 0}
                scored_turns = set()
                primary_objective_configs = []
                continue

            # Skip header lines
            if line.startswith('===') or line.startswith('AI_TURN') or line.startswith('STEP') or \
               line.startswith('NO STEP') or line.startswith('FAILED') or not line.strip():
                continue

            # Parse scenario
            scenario_match = re.search(r'Scenario: (.+)$', line)
            if scenario_match:
                current_scenario = scenario_match.group(1).strip()
                primary_objective_ids = _get_primary_objective_ids_for_scenario(current_scenario)
                primary_objective_configs = [
                    config_loader.load_primary_objective_config(obj_id)
                    for obj_id in primary_objective_ids
                ]
                continue

            # Parse walls
            wall_match = re.search(r'Walls: (.+)$', line)
            if wall_match:
                wall_str = wall_match.group(1).strip()
                if wall_str != 'none':
                    for coord_match in re.finditer(r'\((\d+),(\d+)\)', wall_str):
                        col, row = int(coord_match.group(1)), int(coord_match.group(2))
                        wall_hexes.add((col, row))
                continue

            # Parse objectives
            objectives_match = re.search(r'Objectives:\s*(.+)$', line)
            if objectives_match:
                objectives_payload = objectives_match.group(1).strip()
                if not objectives_payload:
                    raise ValueError(
                        f"Objectives line missing payload in episode {current_episode_num}: {line.strip()[:200]}"
                    )
                objective_hexes = {}
                for entry in objectives_payload.split('|'):
                    entry = entry.strip()
                    if not entry:
                        raise ValueError(
                            f"Objectives line contains empty entry in episode {current_episode_num}: {line.strip()[:200]}"
                        )
                    if ':' not in entry:
                        raise ValueError(
                            f"Objectives entry missing ':' in episode {current_episode_num}: {entry}"
                        )
                    name_part, hex_part = entry.split(':', 1)
                    name_part = name_part.strip()
                    obj_id_match = re.match(r'Obj(\d+)$', name_part)
                    if obj_id_match:
                        obj_id = int(obj_id_match.group(1))
                    else:
                        objective_name_map = _get_objective_name_to_id_map(current_scenario)
                        if name_part not in objective_name_map:
                            raise ValueError(
                                f"Invalid objective name '{name_part}' in episode {current_episode_num} "
                                f"(no mapping found in scenario '{current_scenario}')"
                            )
                        obj_id = objective_name_map[name_part]
                    if obj_id in objective_hexes:
                        raise ValueError(
                            f"Duplicate objective id {obj_id} in episode {current_episode_num}"
                        )
                    hexes: List[Tuple[int, int]] = []
                    for hex_str in hex_part.split(';'):
                        hex_str = hex_str.strip()
                        if not hex_str:
                            raise ValueError(
                                f"Empty objective hex in episode {current_episode_num}: {entry}"
                            )
                        coord_match = re.match(r'\((\d+),\s*(\d+)\)', hex_str)
                        if not coord_match:
                            raise ValueError(
                                f"Invalid objective hex '{hex_str}' in episode {current_episode_num}"
                            )
                        col, row = normalize_coordinates(
                            int(coord_match.group(1)),
                            int(coord_match.group(2)),
                        )
                        hexes.append((col, row))
                    if not hexes:
                        raise ValueError(
                            f"Objective {obj_id} has no hexes in episode {current_episode_num}"
                        )
                    objective_hexes[obj_id] = set(hexes)
                continue

            # Parse unit starting positions
            unit_start_match = re.match(r'.*Unit (\d+) \((\w+)\) P(\d+): Starting position \((\d+),\s*(\d+)\)', line)
            if unit_start_match:
                unit_id = unit_start_match.group(1)
                unit_type = unit_start_match.group(2)
                player = int(unit_start_match.group(3))
                col = int(unit_start_match.group(4))
                row = int(unit_start_match.group(5))
                
                # CRITICAL: Get HP_MAX from registry (REAL HP, not guessed)
                unit_data = require_key(unit_registry.units, unit_type)
                hp_max = require_key(unit_data, "HP_MAX")
                _debug_log(f"[ANALYZER] Unit {unit_id} ({unit_type}) HP_MAX={hp_max} from registry")
                unit_move_value = require_key(unit_data, "MOVE")
                
                # Initialize HP_CUR = HP_MAX (unit starts at full HP)
                unit_hp[unit_id] = hp_max
                
                unit_player[unit_id] = player
                _position_cache_set(unit_positions, unit_id, col, row)
                unit_types[unit_id] = unit_type
                stats['unit_types'][unit_id] = unit_type
                unit_move[unit_id] = unit_move_value
                positions_at_turn_start[unit_id] = (col, row)
                unit_movement_history[unit_id] = [{"position": (col, row)}]
                continue

            # Episode end
            if 'EPISODE END' in line:
                if stats['current_episode_deaths']:
                    stats['death_orders'].append(tuple(stats['current_episode_deaths']))

                # Save turn distribution for this episode
                if episode_turn > 0:
                    stats['turns_distribution'][episode_turn] += 1
                stats['episode_lengths'].append((current_episode_num, episode_actions))
                
                # Calculate episode duration from Duration= field (wall-clock from step_logger)
                duration_match = re.search(r'Duration=(\d+(?:\.\d+)?)\s*s?\b', line)
                if not duration_match:
                    raise ValueError(
                        f"Missing Duration= in EPISODE END line for episode {current_episode_num}: "
                        f"{line.strip()[:200]}"
                    )
                duration_seconds = float(duration_match.group(1))
                stats['episode_durations'].append((current_episode_num, duration_seconds))

                winner_match = re.search(r'Winner=(-?\d+)', line)
                method_match = re.search(r'Method=(\w+)', line)

                if winner_match:
                    winner = int(winner_match.group(1))
                    win_method = method_match.group(1) if method_match else None

                    if winner == 1:
                        stats['wins_by_scenario'][current_scenario]['p1'] += 1
                    elif winner == 2:
                        stats['wins_by_scenario'][current_scenario]['p2'] += 1
                    elif winner == -1:
                        stats['wins_by_scenario'][current_scenario]['draws'] += 1

                    if win_method:
                        if winner in stats['win_methods'] and win_method in stats['win_methods'][winner]:
                            stats['win_methods'][winner][win_method] += 1
                        elif winner == -1:
                            stats['win_methods'][-1]['draw'] += 1
                    else:
                        stats['episodes_without_method'].append({
                            'winner': winner,
                            'line': line.strip()[:100]
                        })

                if primary_objective_configs:
                    if last_objective_snapshot is None:
                        raise ValueError(
                            f"Missing objective control snapshot at episode end {current_episode_num}"
                        )
                    if last_turn == 5 and last_player == PLAYER_TWO_ID:
                        for cfg in primary_objective_configs:
                            objective_id = require_key(cfg, "id")
                            score_key = (objective_id, last_turn, PLAYER_TWO_ID)
                            if score_key in scored_turns:
                                continue
                            points = _calculate_primary_objective_points(
                                last_objective_snapshot,
                                cfg,
                                PLAYER_TWO_ID
                            )
                            episode_victory_points[PLAYER_TWO_ID] += points
                            scored_turns.add(score_key)
                    stats['victory_points_by_episode'][current_episode_num] = {
                        PLAYER_ONE_ID: episode_victory_points[PLAYER_ONE_ID],
                        PLAYER_TWO_ID: episode_victory_points[PLAYER_TWO_ID],
                    }
                    stats['victory_points_values'][PLAYER_ONE_ID].append(
                        episode_victory_points[PLAYER_ONE_ID]
                    )
                    stats['victory_points_values'][PLAYER_TWO_ID].append(
                        episode_victory_points[PLAYER_TWO_ID]
                    )

                stats['current_episode_deaths'] = []
                stats['wounded_enemies'] = {1: set(), 2: set()}
                current_episode = []
                continue

            # Parse action line
            # Support both old format (T\d+) and new format (E\d+ T\d+)
            # STEP marker is optional (removed from logs)
            match = re.match(r'\[.*?\] (?:E\d+ )?T(\d+) P(\d+) (\w+) : (.*?) \[(SUCCESS|FAILED)\](?: \[STEP: (YES|NO)\])?', line)
            if match:
                turn = int(match.group(1))
                player = int(match.group(2))
                phase = match.group(3)
                action_desc = match.group(4)
                success = match.group(5) == 'SUCCESS'
                step_marker_present = match.group(6) is not None
                step_inc = match.group(6) == 'YES' if step_marker_present else True

                # CRITICAL: Apply damage regardless of STEP marker
                # Non-step lines still contain real attacks/shots and can kill units.
                # If we ignore STEP: NO damage, later rule checks (e.g., adjacency) can produce false positives
                # by treating dead units as alive.
                if 'shot at unit' in action_desc.lower():
                    target_match = re.search(r'SHOT at Unit (\d+)', action_desc, re.IGNORECASE)
                    if target_match:
                        target_id = target_match.group(1)
                        damage_match = re.search(r'Dmg:(\d+)HP', action_desc)
                        if damage_match:
                            damage = int(damage_match.group(1))
                            # RULE: Shoot at dead unit (target already dead when shot)
                            if 'shot at unit' in action_desc.lower() and damage > 0:
                                target_already_dead = target_id not in unit_hp or require_key(unit_hp, target_id) <= 0
                                if target_already_dead:
                                    stats['shoot_at_dead_unit'][player] += 1
                                    if stats['first_error_lines']['shoot_at_dead_unit'][player] is None:
                                        stats['first_error_lines']['shoot_at_dead_unit'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            _apply_damage_and_handle_death(
                                target_id, damage, player, turn, phase, line_number, current_episode_num,
                                line, dead_units_current_episode, unit_hp, unit_types, unit_positions, unit_deaths, stats
                            )
                
                if 'attacked unit' in action_desc.lower():
                    target_match = re.search(r'ATTACKED Unit (\d+)', action_desc, re.IGNORECASE)
                    if target_match:
                        target_id = target_match.group(1)
                        damage_match = re.search(r'Dmg:(\d+)HP', action_desc)
                        if damage_match:
                            damage = int(damage_match.group(1))
                            _apply_damage_and_handle_death(
                                target_id, damage, player, turn, phase, line_number, current_episode_num,
                                line, dead_units_current_episode, unit_hp, unit_types, unit_positions, unit_deaths, stats
                            )

                actor_match = re.match(r'Unit (\d+)\(', action_desc)
                if actor_match:
                    actor_id = actor_match.group(1)
                    _track_unit_reappearance(
                        actor_id,
                        unit_hp,
                        unit_player,
                        dead_units_current_episode,
                        revived_units_current_episode,
                        stats,
                        current_episode_num,
                        line
                    )
                    action_desc_upper = action_desc.upper()
                    is_activation_marker = (
                        " MOVED " in action_desc_upper
                        or " ADVANCED " in action_desc_upper
                        or " CHARGED " in action_desc_upper
                        or " FAILED CHARGE " in action_desc_upper
                        or " FLED " in action_desc_upper
                    )
                    # Double-activation should only count unit activations, not per-shot/per-attack logs.
                    if phase in ('MOVE', 'SHOOT', 'CHARGE') and is_activation_marker:
                        if player is None:
                            raise ValueError("player is required for double-activation check")
                        phase_key = (turn, phase, int(player))
                        seen_units = phase_activation_seen.setdefault(phase_key, set())
                        if actor_id in seen_units:
                            double_activation_by_phase = require_key(stats, "double_activation_by_phase")
                            double_activation_by_phase[phase] += 1
                            first_errors = require_key(stats, "first_error_lines")
                            double_activation_first = require_key(first_errors, "double_activation_by_phase")
                            if double_activation_first[phase] is None:
                                double_activation_first[phase] = {'episode': current_episode_num, 'line': line.strip()}
                        else:
                            seen_units.add(actor_id)

                # Reset markers when turn changes
                if turn != last_turn:
                    units_moved = set()
                    units_shot = set()
                    # CRITICAL: Reset units_fled at the start of each turn
                    # According to AI_TURN.md and command_phase_start(), units_fled is reset at the start of each turn
                    # A unit that fled in T1 SHOULD be able to shoot/charge in T2
                    units_fled = set()
                    units_advanced = set()
                    units_fought = set()
                    charged_units_current_fight = set()
                    charged_units_fought = set()
                    positions_at_turn_start = unit_positions.copy()
                    positions_at_move_phase_start = {}
                    last_player = None  # Reset last player on turn change
                    last_phase = None
                    last_shoot_shooter_id = None
                    last_shoot_weapon = None
                    last_shoot_target_id = None
                    last_fight_fighter_id = None
                    last_fight_weapon = None
                    last_turn = turn

                # Track positions at start of MOVE phase for fled detection
                # CRITICAL: Must track positions at the start of EACH player's MOVE phase, not just the first MOVE of the turn
                # When player changes OR when we see the first MOVE action of a turn, capture positions
                # BUT: Don't fill it yet - we'll fill it with positions "from" of MOVE actions below
                if phase == 'MOVE' and (last_player != player or not positions_at_move_phase_start):
                    # Don't fill positions_at_move_phase_start here - it will be filled below using "from" positions from log
                    positions_at_move_phase_start = {}
                
                # Update last_player after processing the action
                last_player = player

                if phase != last_phase:
                    if phase == 'MOVE':
                        # Reset snapshot at the start of each MOVE phase
                        positions_at_move_phase_start = {}
                        charged_units_current_fight = set()
                        charged_units_fought = set()
                    if phase == 'SHOOT':
                        # Reset shot sequence counts at the start of each SHOOT phase
                        shot_sequence_counts = {}
                        last_shoot_shooter_id = None
                        last_shoot_weapon = None
                        last_shoot_target_id = None
                        combi_profile_usage = {}
                        combi_conflicts_seen = set()
                    if phase == 'FIGHT':
                        fight_phase_seq_id += 1
                        last_fight_fighter_id = None
                        last_fight_weapon = None
                    last_phase = phase

                episode_turn = max(episode_turn, turn)

                if step_inc:
                    stats['total_actions'] += 1
                    episode_actions += 1
                    stats['actions_by_phase'][phase] += 1

                # Determine action type and validate rules
                is_shoot_action = "shot at unit" in action_desc.lower()
                if not is_shoot_action:
                    last_shoot_shooter_id = None
                    last_shoot_weapon = None
                    last_shoot_target_id = None
                if "SHOT at Unit" in action_desc:
                        action_type = 'shoot'
                        stats['shoot_vs_wait']['shoot'] += 1
                        stats['shoot_vs_wait_by_player'][player]['shoot'] += 1
                        shooter_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\)', action_desc)
                        target_match = re.search(r'SHOT at Unit (\d+)(?:\((\d+),\s*(\d+)\))?', action_desc, re.IGNORECASE)

                        if shooter_match and target_match:
                            shooter_id = shooter_match.group(1)
                            shooter_col = int(shooter_match.group(2))
                            shooter_row = int(shooter_match.group(3))
                            target_id = target_match.group(1)
                            units_shot.add(shooter_id)
                            stats['shoot_invalid'][player]['total'] += 1
                            _track_action_phase_accuracy(stats, "shoot", phase, current_episode_num, line)
                            
                            # CRITICAL: Update position cache with shooter position from log (source of truth)
                            _position_cache_set(unit_positions, shooter_id, shooter_col, shooter_row)
                            
                            if target_match.group(2) and target_match.group(3):
                                target_col = int(target_match.group(2))
                                target_row = int(target_match.group(3))
                                target_pos = (target_col, target_row)
                                # CRITICAL: Update target position in cache from log (avoids stale positions)
                                if target_id in unit_hp and require_key(unit_hp, target_id) > 0:
                                    _position_cache_set(unit_positions, target_id, target_col, target_row)
                            elif target_id in unit_positions:
                                target_pos = unit_positions[target_id]
                            else:
                                target_pos = None

                            # RULE: Dead unit shooting (CRITICAL BUG)
                            # Check if shooter is dead, but filter false positives (unit dies AFTER shooting in same phase)
                            # CRITICAL: Only check if unit is in unit_hp - if not in dict, unit may not have been initialized yet
                            shooter_is_dead = shooter_id in unit_hp and require_key(unit_hp, shooter_id) <= 0
                            if shooter_is_dead:
                                # Check if this is a false positive: unit dies AFTER this shoot action in same turn/phase
                                is_false_positive = False
                                phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
                                current_phase_order = require_key(phase_order, phase)
                                
                                # Find when this unit died (if it did)
                                unit_died_before_shoot = False
                                for death_turn, death_phase, dead_unit_id, death_line_num in unit_deaths:
                                    if dead_unit_id == shooter_id:
                                        # Unit died - check if it's BEFORE this shoot action
                                        if death_turn < turn:
                                            # Unit died in previous turn - REAL BUG (died before shoot)
                                            unit_died_before_shoot = True
                                            break
                                        elif death_turn == turn:
                                            # Same turn - check phase order and line number
                                            death_phase_order = require_key(phase_order, death_phase)
                                            if death_phase_order < current_phase_order:
                                                # Unit died in earlier phase of same turn - REAL BUG
                                                unit_died_before_shoot = True
                                                break
                                            elif death_phase_order == current_phase_order and death_line_num < line_number:
                                                # Unit died in same phase but BEFORE this shoot action - REAL BUG
                                                unit_died_before_shoot = True
                                                break
                                            elif death_phase_order == current_phase_order and death_line_num > line_number:
                                                # Unit dies in same phase but AFTER this shoot action - FALSE POSITIVE
                                                is_false_positive = True
                                                break
                                
                                # Only report if it's a real bug (unit died before shooting)
                                if unit_died_before_shoot and not is_false_positive:
                                    stats['shoot_dead_unit'][player] += 1
                                    if stats['first_error_lines']['shoot_dead_unit'][player] is None:
                                        stats['first_error_lines']['shoot_dead_unit'][player] = {'episode': current_episode_num, 'line': line.strip()}

                            # RULE: Shoot after fled
                            # CRITICAL: Normalize shooter_id to string for consistent comparison (units_fled stores strings)
                            if str(shooter_id) in units_fled:
                                stats['shoot_after_fled'][player] += 1
                                if stats['first_error_lines']['shoot_after_fled'][player] is None:
                                    stats['first_error_lines']['shoot_after_fled'][player] = {'episode': current_episode_num, 'line': line.strip()}

                            # RULE: Shoot at friendly
                            # CRITICAL: Use shooter's actual player, not phase player
                            # The phase player (P1/P2) indicates whose turn it is, not which player the shooter belongs to
                            shooter_actual_player = require_key(unit_player, shooter_id)
                            # CRITICAL: Normalize player values to int for consistent comparison (handles int/string mismatches)
                            shooter_actual_player_int = int(shooter_actual_player) if shooter_actual_player is not None else None
                            target_player = unit_player.get(target_id) if target_id in unit_player else None
                            target_player_int = int(target_player) if target_player is not None else None
                            if target_id in unit_player and shooter_actual_player_int is not None and target_player_int == shooter_actual_player_int:
                                # Use shooter's player for stats (not phase player)
                                stats['shoot_at_friendly'][shooter_actual_player] += 1
                                if stats['first_error_lines']['shoot_at_friendly'][shooter_actual_player] is None:
                                    stats['first_error_lines']['shoot_at_friendly'][shooter_actual_player] = {'episode': current_episode_num, 'line': line.strip()}

                            # RULE: Shoot through wall
                            if target_pos and not has_line_of_sight(shooter_col, shooter_row, target_pos[0], target_pos[1], wall_hexes):
                                stats['shoot_through_wall'][player] += 1
                                if stats['first_error_lines']['shoot_through_wall'][player] is None:
                                    stats['first_error_lines']['shoot_through_wall'][player] = {'episode': current_episode_num, 'line': line.strip()}
                                stats['shoot_invalid'][player]['no_los'] += 1
                                if stats['first_error_lines']['shoot_invalid'][player] is None:
                                    stats['first_error_lines']['shoot_invalid'][player] = {'episode': current_episode_num, 'line': line.strip()}

                            # Check PISTOL weapon rules (needed before shoot_at_engaged_enemy check)
                            weapon_match = re.search(r'with \[([^\]]+)\]', action_desc)
                            is_pistol = False
                            weapon_found = False
                            weapon_range = None
                            
                            # CRITICAL: Validate that shooter_id matches expected unit type
                            # This detects cases where unit ID is wrong in the log
                            shooter_unit_type = require_key(unit_types, shooter_id)
                            shooter_player_from_types = require_key(unit_player, shooter_id)
                            
                            if weapon_match:
                                weapon_display_name = weapon_match.group(1)
                                weapon_name_lower = weapon_display_name.lower()
                                
                                weapons_info = require_key(unit_weapons_cache, shooter_unit_type)
                                
                                for weapon_info in weapons_info:
                                    if weapon_info['name'].lower() == weapon_name_lower:
                                        is_pistol = weapon_info['is_pistol']
                                        weapon_range = weapon_info['range']
                                        weapon_found = True
                                        break
                                
                                # CRITICAL: Detect unit ID/type mismatch
                                # If weapon not found AND it's clearly from wrong faction, suspect ID error
                                if not weapon_found and shooter_unit_type:
                                    # Check if weapon is Tyranid but unit type suggests Space Marine or vice versa
                                    tyranid_weapons = ['deathspitter', 'fleshborer', 'devourer', 'scything talons', 'bonesword', 'lash whip']
                                    space_marine_weapons = ['bolt rifle', 'bolt pistol', 'chainsword', 'power sword', 'power fist', 'stalker bolt rifle']
                                    
                                    weapon_is_tyranid = any(tyranid_wpn in weapon_name_lower for tyranid_wpn in tyranid_weapons)
                                    weapon_is_space_marine = any(sm_wpn in weapon_name_lower for sm_wpn in space_marine_weapons)
                                    
                                    unit_is_space_marine = 'intercessor' in shooter_unit_type.lower() or 'captain' in shooter_unit_type.lower() or 'spacemarine' in shooter_unit_type.lower()
                                    unit_is_tyranid = 'tyranid' in shooter_unit_type.lower() or 'genestealer' in shooter_unit_type.lower() or 'hormagaunt' in shooter_unit_type.lower() or 'termagant' in shooter_unit_type.lower()
                                    
                                    # If weapon faction doesn't match unit faction, it's likely an ID mismatch bug
                                    if (weapon_is_tyranid and unit_is_space_marine) or (weapon_is_space_marine and unit_is_tyranid):
                                        # This suggests shooter_id in log is wrong - log as ID mismatch
                                        if 'unit_id_mismatches' not in stats:
                                            stats['unit_id_mismatches'] = []
                                        stats['unit_id_mismatches'].append({
                                            'episode': current_episode_num,
                                            'turn': turn,
                                            'phase': phase,
                                            'shooter_id_logged': shooter_id,
                                            'shooter_type_registered': shooter_unit_type,
                                            'shooter_player_registered': shooter_player_from_types,
                                            'weapon_logged': weapon_display_name,
                                            'shooter_position': (shooter_col, shooter_row),
                                            'line': line.strip()
                                        })
                            if weapon_match:
                                shooter_unit_type = require_key(unit_types, shooter_id)
                                if shooter_unit_type:
                                    limits = require_key(unit_attack_limits, shooter_unit_type)
                                    rng_nb_by_weapon = require_key(limits, "rng_nb_by_weapon")
                                    weapon_name_for_limits = weapon_display_name.strip()
                                    if weapon_name_for_limits not in rng_nb_by_weapon:
                                        stats['parse_errors'].append({
                                            'episode': current_episode_num,
                                            'turn': turn,
                                            'phase': phase,
                                            'line': line.strip(),
                                            'error': f"Weapon '{weapon_name_for_limits}' missing RNG_NB for unit type {shooter_unit_type}"
                                        })
                                    else:
                                        rng_nb = rng_nb_by_weapon[weapon_name_for_limits]
                                        combi_key = None
                                        if shooter_unit_type in unit_combi_by_weapon:
                                            combi_by_weapon = unit_combi_by_weapon[shooter_unit_type]
                                            if weapon_name_for_limits in combi_by_weapon:
                                                combi_key = combi_by_weapon[weapon_name_for_limits]
                                        if combi_key is not None:
                                            if shooter_id not in combi_profile_usage:
                                                combi_profile_usage[shooter_id] = {}
                                            if combi_key not in combi_profile_usage[shooter_id]:
                                                combi_profile_usage[shooter_id][combi_key] = set()
                                            combi_profiles = combi_profile_usage[shooter_id][combi_key]
                                            combi_profiles.add(weapon_name_for_limits)
                                            conflict_key = (current_episode_num, turn, shooter_id, combi_key)
                                            if len(combi_profiles) > 1 and conflict_key not in combi_conflicts_seen:
                                                shooter_player_for_stats = require_key(unit_player, shooter_id)
                                                stats['shoot_combi_profile_conflicts'][shooter_player_for_stats] += 1
                                                if stats['first_error_lines']['shoot_combi_profile_conflicts'][shooter_player_for_stats] is None:
                                                    stats['first_error_lines']['shoot_combi_profile_conflicts'][shooter_player_for_stats] = {
                                                        'episode': current_episode_num,
                                                        'line': line.strip()
                                                    }
                                                combi_conflicts_seen.add(conflict_key)
                                        seq_key = (current_episode_num, turn, shooter_id, weapon_name_for_limits)
                                        if (last_shoot_shooter_id != shooter_id or
                                                last_shoot_weapon != weapon_name_for_limits or
                                                last_shoot_target_id != target_id):
                                            shot_sequence_counts[seq_key] = 0
                                        elif step_marker_present and step_inc:
                                            shot_sequence_counts[seq_key] = 0
                                        if seq_key not in shot_sequence_counts:
                                            shot_sequence_counts[seq_key] = 0
                                        shot_sequence_counts[seq_key] += 1
                                        if shot_sequence_counts[seq_key] > rng_nb:
                                            shooter_player_for_stats = require_key(unit_player, shooter_id)
                                            stats['shoot_over_rng_nb'][shooter_player_for_stats] += 1
                                            if stats['first_error_lines']['shoot_over_rng_nb'][shooter_player_for_stats] is None:
                                                stats['first_error_lines']['shoot_over_rng_nb'][shooter_player_for_stats] = {'episode': current_episode_num, 'line': line.strip()}
                                        last_shoot_shooter_id = shooter_id
                                        last_shoot_weapon = weapon_name_for_limits
                                        last_shoot_target_id = target_id

                            # RULE: Shoot at engaged enemy
                            # CRITICAL: According to AI_TURN.md, PISTOL weapons CAN shoot at engaged enemies
                            # So we must exclude PISTOL weapons from this violation
                            # CRITICAL: is_engaged uses unit_positions which should be current at this point
                            # But we need to ensure target_pos is used if available (more accurate)
                            if target_pos:
                                # Use target_pos from log if available (more accurate than unit_positions)
                                if target_id not in unit_player:
                                    stats['parse_errors'].append({
                                        'episode': current_episode_num,
                                        'turn': turn,
                                        'phase': phase,
                                        'line': line.strip(),
                                        'error': f"Engagement check missing unit_player for target_id: {target_id}"
                                    })
                                    target_engaged = False
                                else:
                                    missing_ids = [uid for uid in unit_positions if uid not in unit_hp or uid not in unit_player]
                                    for missing_id in missing_ids:
                                        stats['parse_errors'].append({
                                            'episode': current_episode_num,
                                            'turn': turn,
                                            'phase': phase,
                                            'line': line.strip(),
                                            'error': f"Engagement check missing unit data for unit_id: {missing_id}"
                                        })
                                    positions_for_engagement = {
                                        uid: pos for uid, pos in unit_positions.items()
                                        if uid in unit_hp and uid in unit_player
                                    }
                                    target_engaged = is_adjacent_to_enemy(
                                        target_pos[0],
                                        target_pos[1],
                                        unit_player,
                                        positions_for_engagement,
                                        unit_hp,
                                        require_key(unit_player, target_id)
                                    )
                            elif target_id in unit_positions:
                                stats['parse_errors'].append({
                                    'episode': current_episode_num,
                                    'turn': turn,
                                    'phase': phase,
                                    'line': line.strip(),
                                    'error': f"Engagement check missing target_pos in log; using unit_positions for target_id: {target_id}"
                                })
                                # Use unit_positions when target_pos is missing
                                if target_id not in unit_player:
                                    stats['parse_errors'].append({
                                        'episode': current_episode_num,
                                        'turn': turn,
                                        'phase': phase,
                                        'line': line.strip(),
                                        'error': f"Engagement check missing unit_player for target_id: {target_id}"
                                    })
                                    target_engaged = False
                                else:
                                    missing_ids = [uid for uid in unit_positions if uid not in unit_hp or uid not in unit_player]
                                    for missing_id in missing_ids:
                                        stats['parse_errors'].append({
                                            'episode': current_episode_num,
                                            'turn': turn,
                                            'phase': phase,
                                            'line': line.strip(),
                                            'error': f"Engagement check missing unit data for unit_id: {missing_id}"
                                        })
                                    positions_for_engagement = {
                                        uid: pos for uid, pos in unit_positions.items()
                                        if uid in unit_hp and uid in unit_player
                                    }
                                    target_pos_from_cache = positions_for_engagement.get(target_id)
                                    if target_pos_from_cache:
                                        target_engaged = is_adjacent_to_enemy(
                                            target_pos_from_cache[0],
                                            target_pos_from_cache[1],
                                            unit_player,
                                            positions_for_engagement,
                                            unit_hp,
                                            require_key(unit_player, target_id)
                                        )
                                    else:
                                        target_engaged = False
                            else:
                                target_engaged = False
                            
                            # Only report violation if target is engaged AND weapon is NOT a PISTOL
                            if target_engaged and not is_pistol:
                                stats['shoot_at_engaged_enemy'][player] += 1
                                if stats['first_error_lines']['shoot_at_engaged_enemy'][player] is None:
                                    stats['first_error_lines']['shoot_at_engaged_enemy'][player] = {'episode': current_episode_num, 'line': line.strip()}

                            # Track PISTOL weapon shots (for statistics)
                            if weapon_match and target_pos and weapon_found:
                                distance = calculate_hex_distance(shooter_col, shooter_row, target_pos[0], target_pos[1])
                                
                                if is_pistol:
                                    if distance == 1:
                                        stats['pistol_shots'][player]['adjacent'] += 1
                                    else:
                                        stats['pistol_shots'][player]['not_adjacent'] += 1
                                else:
                                    if distance == 1:
                                        stats['non_pistol_adjacent_shots'][player] += 1
                                        stats['shoot_invalid'][player]['adjacent_non_pistol'] += 1
                                        if stats['first_error_lines']['shoot_invalid'][player] is None:
                                            stats['first_error_lines']['shoot_invalid'][player] = {'episode': current_episode_num, 'line': line.strip()}
                                if weapon_range is not None and distance > weapon_range:
                                    stats['shoot_invalid'][player]['out_of_range'] += 1
                                    if stats['first_error_lines']['shoot_invalid'][player] is None:
                                        stats['first_error_lines']['shoot_invalid'][player] = {'episode': current_episode_num, 'line': line.strip()}

                            # Track shots after advance
                            if shooter_id in units_advanced:
                                stats['shots_after_advance'][player] += 1

                            # Target priority analysis
                            stats['target_priority'][player]['total_shots'] += 1
                            target_was_wounded = target_id in stats['wounded_enemies'][player]
                            
                            wounded_in_los = set()
                            for wounded_id in stats['wounded_enemies'][player]:
                                if wounded_id in unit_positions and wounded_id in unit_hp and require_key(unit_hp, wounded_id) > 0:
                                    wounded_pos = unit_positions[wounded_id]
                                    if has_line_of_sight(shooter_col, shooter_row, wounded_pos[0], wounded_pos[1], wall_hexes):
                                        wounded_in_los.add(wounded_id)

                            if target_was_wounded:
                                stats['target_priority'][player]['shots_at_wounded_in_los'] += 1
                            elif len(wounded_in_los) > 0:
                                stats['target_priority'][player]['shots_at_full_hp_while_wounded_in_los'] += 1
                            else:
                                stats['target_priority'][player]['shots_at_wounded_in_los'] += 1

                        # Sample action
                        if not stats['sample_actions']['shoot']:
                            stats['sample_actions']['shoot'] = line.strip()

                elif " WAIT" in action_desc:
                        action_type = 'wait'
                        stats['shoot_vs_wait']['wait'] += 1
                        stats['shoot_vs_wait_by_player'][player]['wait'] += 1
                        
                        wait_unit_match = re.search(r'Unit (\d+)', action_desc)
                        if wait_unit_match:
                            wait_unit_id = wait_unit_match.group(1)
                            wait_unit_dead = wait_unit_id not in unit_hp or require_key(unit_hp, wait_unit_id) <= 0
                            if wait_unit_dead:
                                unit_died_before_wait = False
                                phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
                                current_phase_order = require_key(phase_order, phase)
                                for death_turn, death_phase, dead_unit_id, death_line_num in unit_deaths:
                                    if dead_unit_id == wait_unit_id:
                                        if death_turn < turn:
                                            unit_died_before_wait = True
                                            break
                                        if death_turn == turn:
                                            death_phase_order = require_key(phase_order, death_phase)
                                            if death_phase_order < current_phase_order:
                                                unit_died_before_wait = True
                                                break
                                            if death_phase_order == current_phase_order and death_line_num < line_number:
                                                unit_died_before_wait = True
                                                break
                                if unit_died_before_wait:
                                    stats['dead_unit_waiting'][player] += 1
                                    if stats['first_error_lines']['dead_unit_waiting'][player] is None:
                                        stats['first_error_lines']['dead_unit_waiting'][player] = {'episode': current_episode_num, 'line': line.strip()}

                        if phase == 'SHOOT':
                            unit_match = re.search(r'Unit (\d+)\((\d+), (\d+)\)', action_desc)
                            if unit_match:
                                wait_unit_id = unit_match.group(1)
                                wait_col = int(unit_match.group(2))
                                wait_row = int(unit_match.group(3))
                                
                                wait_unit_type = require_key(unit_types, wait_unit_id)
                                available_weapons = require_key(unit_weapons_cache, wait_unit_type)
                                ranged_weapons = [w for w in available_weapons if require_key(w, 'range') > 0]
                                
                                enemy_player = 3 - player
                                # CRITICAL: Normalize player values to int for consistent comparison (handles int/string mismatches)
                                enemy_player_int = int(enemy_player) if enemy_player is not None else None
                                is_adj = False
                                for uid, p in unit_player.items():
                                    # CRITICAL: Normalize player value to int for consistent comparison (handles int/string mismatches)
                                    p_int = int(p) if p is not None else None
                                    if p_int == enemy_player_int and uid in unit_positions:
                                        hp_value = _get_unit_hp_value(
                                            unit_hp,
                                            uid,
                                            stats,
                                            current_episode_num,
                                            turn,
                                            phase,
                                            line,
                                            "Wait adjacency"
                                        )
                                        if hp_value is None or hp_value <= 0:
                                            continue
                                        enemy_pos = unit_positions[uid]
                                        if is_adjacent(wait_col, wait_row, enemy_pos[0], enemy_pos[1]):
                                            is_adj = True
                                            break
                                
                                if is_adj:
                                    has_pistol = any(require_key(w, 'is_pistol') for w in ranged_weapons)
                                    if not has_pistol:
                                        stats['shoot_vs_wait']['wait'] -= 1
                                        stats['shoot_vs_wait_by_player'][player]['wait'] -= 1
                                        stats['shoot_vs_wait']['skip'] += 1
                                        stats['shoot_vs_wait_by_player'][player]['skip'] += 1
                                        continue
                                
                                valid_targets = []
                                # CRITICAL: Normalize player values to int for consistent comparison (handles int/string mismatches)
                                enemy_player_int = int(enemy_player) if enemy_player is not None else None
                                for uid, p in unit_player.items():
                                    # CRITICAL: Normalize player value to int for consistent comparison (handles int/string mismatches)
                                    p_int = int(p) if p is not None else None
                                    if p_int == enemy_player_int and uid in unit_positions:
                                        hp_value = _get_unit_hp_value(
                                            unit_hp,
                                            uid,
                                            stats,
                                            current_episode_num,
                                            turn,
                                            phase,
                                            line,
                                            "Wait valid targets"
                                        )
                                        if hp_value is None or hp_value <= 0:
                                            continue
                                        enemy_pos = unit_positions[uid]
                                        distance = calculate_hex_distance(wait_col, wait_row, enemy_pos[0], enemy_pos[1])
                                        
                                        if not has_line_of_sight(wait_col, wait_row, enemy_pos[0], enemy_pos[1], wall_hexes):
                                            continue
                                        
                                        can_reach = False
                                        for weapon in ranged_weapons:
                                            weapon_range = require_key(weapon, 'range')
                                            is_pistol = require_key(weapon, 'is_pistol')
                                            
                                            if distance > weapon_range:
                                                continue
                                            
                                            if distance == 1 and not is_pistol:
                                                continue
                                            
                                            target_in_melee = False
                                            # CRITICAL: Normalize player values to int for consistent comparison (handles int/string mismatches)
                                            player_int = int(player) if player is not None else None
                                            for friendly_id, friendly_p in unit_player.items():
                                                # CRITICAL: Normalize player value to int for consistent comparison (handles int/string mismatches)
                                                friendly_p_int = int(friendly_p) if friendly_p is not None else None
                                                if friendly_p_int == player_int and friendly_id != wait_unit_id:
                                                    if friendly_id in unit_positions:
                                                        friendly_pos = unit_positions[friendly_id]
                                                        if is_adjacent(enemy_pos[0], enemy_pos[1], friendly_pos[0], friendly_pos[1]):
                                                            target_in_melee = True
                                                            break
                                            
                                            if target_in_melee:
                                                continue
                                            
                                            can_reach = True
                                            break
                                        
                                        if can_reach:
                                            valid_targets.append(uid)

                                if valid_targets:
                                    stats['wait_by_phase'][player]['wait_with_los'] += 1
                                    stats['shoot_vs_wait_by_player'][player]['wait_with_targets'] += 1
                                else:
                                    stats['wait_by_phase'][player]['wait_no_los'] += 1
                                    stats['shoot_vs_wait_by_player'][player]['wait_no_targets'] += 1
                            else:
                                stats['wait_by_phase'][player]['wait_no_los'] += 1
                                stats['shoot_vs_wait_by_player'][player]['wait_no_targets'] += 1
                        elif phase == 'MOVE':
                            stats['wait_by_phase'][player]['move_wait'] += 1

                elif " SKIP" in action_desc:
                        action_type = 'skip'
                        stats['shoot_vs_wait']['skip'] += 1
                        stats['shoot_vs_wait_by_player'][player]['skip'] += 1
                        
                        skip_unit_match = re.search(r'Unit (\d+)', action_desc)
                        if skip_unit_match:
                            skip_unit_id = skip_unit_match.group(1)
                            skip_unit_dead = skip_unit_id not in unit_hp or require_key(unit_hp, skip_unit_id) <= 0
                            if skip_unit_dead:
                                unit_died_before_skip = False
                                phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
                                current_phase_order = require_key(phase_order, phase)
                                for death_turn, death_phase, dead_unit_id, death_line_num in unit_deaths:
                                    if dead_unit_id == skip_unit_id:
                                        if death_turn < turn:
                                            unit_died_before_skip = True
                                            break
                                        if death_turn == turn:
                                            death_phase_order = require_key(phase_order, death_phase)
                                            if death_phase_order < current_phase_order:
                                                unit_died_before_skip = True
                                                break
                                            if death_phase_order == current_phase_order and death_line_num < line_number:
                                                unit_died_before_skip = True
                                                break
                                if unit_died_before_skip:
                                    stats['dead_unit_skipping'][player] += 1
                                    if stats['first_error_lines']['dead_unit_skipping'][player] is None:
                                        stats['first_error_lines']['dead_unit_skipping'][player] = {'episode': current_episode_num, 'line': line.strip()}

                elif "ADVANCED from" in action_desc:
                        action_type = 'advance'
                        
                        if phase == 'SHOOT':
                            stats['shoot_vs_wait']['advance'] += 1
                            stats['shoot_vs_wait_by_player'][player]['advance'] += 1

                        advance_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\) ADVANCED from \((\d+),\s*(\d+)\) to \((\d+),\s*(\d+)\)', action_desc)
                        if advance_match:
                            advance_unit_id = advance_match.group(1)
                            start_col = int(advance_match.group(4))
                            start_row = int(advance_match.group(5))
                            dest_col = int(advance_match.group(6))
                            dest_row = int(advance_match.group(7))
                            _track_action_phase_accuracy(stats, "advance", phase, current_episode_num, line)
                            
                            stats['position_log_mismatch']['advance']['total'] += 1
                            if advance_unit_id not in unit_positions:
                                stats['position_log_mismatch']['advance']['missing'] += 1
                                if stats['first_error_lines']['position_log_mismatch']['advance'] is None:
                                    stats['first_error_lines']['position_log_mismatch']['advance'] = {
                                        'episode': current_episode_num,
                                        'line': line.strip()
                                    }
                            elif unit_positions[advance_unit_id] != (start_col, start_row):
                                stats['position_log_mismatch']['advance']['mismatch'] += 1
                                if stats['first_error_lines']['position_log_mismatch']['advance'] is None:
                                    stats['first_error_lines']['position_log_mismatch']['advance'] = {
                                        'episode': current_episode_num,
                                        'line': line.strip()
                                    }
                            
                            # RULE: Dead unit advancing
                            advance_unit_dead = advance_unit_id not in unit_hp or require_key(unit_hp, advance_unit_id) <= 0
                            if advance_unit_dead:
                                unit_died_before_advance = False
                                phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
                                current_phase_order = require_key(phase_order, phase)
                                for death_turn, death_phase, dead_unit_id, death_line_num in unit_deaths:
                                    if dead_unit_id == advance_unit_id:
                                        if death_turn < turn:
                                            unit_died_before_advance = True
                                            break
                                        if death_turn == turn:
                                            death_phase_order = require_key(phase_order, death_phase)
                                            if death_phase_order < current_phase_order:
                                                unit_died_before_advance = True
                                                break
                                            if death_phase_order == current_phase_order and death_line_num < line_number:
                                                unit_died_before_advance = True
                                                break
                                if unit_died_before_advance:
                                    stats['dead_unit_advancing'][player] += 1
                                    if stats['first_error_lines']['dead_unit_advancing'][player] is None:
                                        stats['first_error_lines']['dead_unit_advancing'][player] = {'episode': current_episode_num, 'line': line.strip()}

                            advance_roll_match = re.search(r'\[Roll:\s*(\d+)\]', action_desc)
                            if not advance_roll_match:
                                stats['parse_errors'].append({
                                    'episode': current_episode_num,
                                    'turn': turn,
                                    'phase': phase,
                                    'line': line.strip(),
                                    'error': f"Advance action missing roll for distance validation: {action_desc[:100]}"
                                })
                            else:
                                advance_roll = int(advance_roll_match.group(1))
                                occupied_positions = _build_occupied_positions(unit_positions, unit_hp, advance_unit_id)
                                enemy_adjacent_hexes = _build_enemy_adjacent_hexes(unit_positions, unit_player, unit_hp, player)
                                shortest_steps = _bfs_shortest_path_length(
                                    start_col,
                                    start_row,
                                    dest_col,
                                    dest_row,
                                    advance_roll,
                                    wall_hexes,
                                    occupied_positions,
                                    enemy_adjacent_hexes
                                )
                                if shortest_steps is None:
                                    stats['move_path_blocked']['advance'][player] += 1
                                    if stats['first_error_lines']['move_path_blocked']['advance'][player] is None:
                                        stats['first_error_lines']['move_path_blocked']['advance'][player] = {
                                            'episode': current_episode_num,
                                            'line': line.strip()
                                        }
                                elif shortest_steps > advance_roll:
                                    stats['move_distance_over_limit']['advance'][player] += 1
                                    if stats['first_error_lines']['move_distance_over_limit']['advance'][player] is None:
                                        stats['first_error_lines']['move_distance_over_limit']['advance'][player] = {
                                            'episode': current_episode_num,
                                            'line': line.strip()
                                        }
                            
                            units_advanced.add(advance_unit_id)
                            
                            # RULE: Advance after shoot
                            # CRITICAL: Check if unit shot before advancing in the same phase
                            # Units should not advance after shooting in the SHOOT phase
                            if advance_unit_id in units_shot:
                                stats['advance_after_shoot'][player] += 1
                                if stats['first_error_lines']['advance_after_shoot'][player] is None:
                                    stats['first_error_lines']['advance_after_shoot'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            
                            # CRITICAL: Sync position cache with log start position before processing
                            if advance_unit_id in unit_positions and unit_positions[advance_unit_id] != (start_col, start_row):
                                _position_cache_set(unit_positions, advance_unit_id, start_col, start_row)
                            positions_at_advance = dict(unit_positions)
                            unit_hp_at_advance = dict(unit_hp)
                            positions_at_advance_reconciled = {}
                            for uid in positions_at_advance.keys():
                                latest_pos = _get_latest_position_from_history(
                                    uid, positions_at_advance, unit_movement_history
                                )
                                if latest_pos is not None:
                                    positions_at_advance_reconciled[uid] = latest_pos
                            
                            # RULE: Advance from adjacent
                            if is_adjacent_to_enemy(start_col, start_row, unit_player, positions_at_advance_reconciled, unit_hp_at_advance, player):
                                adjacent_enemies = get_adjacent_enemies(
                                    start_col, start_row, unit_player, positions_at_advance_reconciled, unit_hp_at_advance, unit_types, player
                                )
                                adjacent_enemy_positions = []
                                for enemy_id in adjacent_enemies:
                                    if enemy_id in positions_at_advance_reconciled:
                                        enemy_pos = positions_at_advance_reconciled[enemy_id]
                                        enemy_hp = unit_hp_at_advance.get(enemy_id)
                                        adjacent_enemy_positions.append(
                                            f"{enemy_id}@({enemy_pos[0]},{enemy_pos[1]}) HP={enemy_hp}"
                                        )
                                _debug_log(
                                    f"[ADVANCE_FROM_ADJACENT] E{current_episode_num} T{turn} P{player} "
                                    f"Unit {advance_unit_id} at ({start_col},{start_row}) adjacent_enemies={adjacent_enemies}"
                                )
                                _debug_log(
                                    f"[ADVANCE_FROM_ADJACENT POS] E{current_episode_num} T{turn} P{player} "
                                    f"Unit {advance_unit_id} adjacent_enemy_positions={adjacent_enemy_positions}"
                                )
                                stats['advance_from_adjacent'][player] += 1
                                if stats['first_error_lines']['advance_from_adjacent'][player] is None:
                                    stats['first_error_lines']['advance_from_adjacent'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            
                            # Record this movement in history (source of truth)
                            if advance_unit_id not in unit_movement_history:
                                unit_movement_history[advance_unit_id] = []
                            timestamp_match = re.search(r'\[(\d+:\d+:\d+)\]', line)
                            timestamp = timestamp_match.group(1) if timestamp_match else None
                            unit_movement_history[advance_unit_id].append({
                                'position': (dest_col, dest_row),
                                'timestamp': timestamp,
                                'action': 'advance',
                                'turn': turn,
                                'episode': current_episode_num
                            })
                            
                            # RULE: Position collision
                            # CRITICAL: Check for collisions BEFORE updating position
                            # This catches cases where another unit is already at the destination
                            # before this unit moves there
                            # Store positions of potential colliding units BEFORE we update
                            colliding_units_before = {}
                            for uid, current_pos in unit_positions.items():
                                if current_pos != (dest_col, dest_row) or uid == advance_unit_id:
                                    continue
                                if uid not in unit_hp:
                                    stats['parse_errors'].append({
                                        'episode': current_episode_num,
                                        'turn': turn,
                                        'phase': phase,
                                        'line': line.strip(),
                                        'error': f"Advance collision missing unit_hp for unit_id: {uid}"
                                    })
                                    continue
                                hp_value = _get_unit_hp_value(
                                    unit_hp,
                                    uid,
                                    stats,
                                    current_episode_num,
                                    turn,
                                    phase,
                                    line,
                                    "Advance collision"
                                )
                                if hp_value is None:
                                    continue
                                if hp_value > 0:
                                    colliding_units_before[uid] = current_pos
                            
                            # Update position cache (only if unit still alive)
                            if advance_unit_id not in unit_hp:
                                stats['parse_errors'].append({
                                    'episode': current_episode_num,
                                    'turn': turn,
                                    'phase': phase,
                                    'line': line.strip(),
                                    'error': f"Advance action for unknown unit_id (missing in unit_hp): {advance_unit_id}"
                                })
                                continue
                            if require_key(unit_hp, advance_unit_id) > 0:
                                old_position = unit_positions.get(advance_unit_id)
                                _position_cache_set(unit_positions, advance_unit_id, dest_col, dest_row)
                            
                            # CRITICAL: Verify collision is real by checking:
                            # 1. Colliding unit is STILL at destination after position update
                            # 2. Colliding unit is still alive
                            # 3. Colliding unit's position hasn't changed (i.e., it didn't move at this timestamp)
                            # 4. Colliding unit actually moved to this position according to movement history (source of truth)
                            real_colliding_units = []
                            for uid, pos_before in colliding_units_before.items():
                                # Check if this unit is still at the destination AFTER we updated our position
                                # AND still alive (HP > 0)
                                # AND its position hasn't changed (i.e., it didn't move at this timestamp)
                                if (uid in unit_positions and 
                                    unit_positions[uid] == (dest_col, dest_row) and
                                    unit_positions[uid] == pos_before and  # Position hasn't changed
                                    uid in unit_hp and
                                    require_key(unit_hp, uid) > 0):
                                    # CRITICAL: Verify that this unit actually moved to this position according to logs
                                    # Check movement history to confirm this is a real collision
                                    if uid in unit_movement_history:
                                        # Check if this unit has a movement record to this position
                                        # AND it was in the SAME episode and turn (to avoid cross-episode/turn false positives)
                                        has_moved_to_dest = any(
                                            move['position'] == (dest_col, dest_row) 
                                            and move.get('turn') == turn
                                            and move.get('episode') == current_episode_num
                                            for move in unit_movement_history[uid]
                                        )
                                        if has_moved_to_dest:
                                            real_colliding_units.append(uid)
                                    else:
                                        # Unit has no movement history - it might be at starting position
                                        # This is likely a false positive, skip it
                                        pass
                            
                            # Only report collision if there are real colliding units
                            # AND the colliding unit actually moved to this position according to logs
                            if real_colliding_units:
                                stats['unit_position_collisions'].append({
                                    'episode': current_episode_num,
                                    'turn': turn,
                                    'position': (dest_col, dest_row),
                                    'units': real_colliding_units + [advance_unit_id],
                                    'action': 'advance',
                                    'advance_from': (start_col, start_row),
                                    'advance_to': (dest_col, dest_row)
                                })
                            
                            # RULE: Move into wall
                            if (dest_col, dest_row) in wall_hexes:
                                stats['wall_collisions'][player] += 1
                                if stats['first_error_lines']['wall_collisions'][player] is None:
                                    stats['first_error_lines']['wall_collisions'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            
                            # Sample action
                            if not stats['sample_actions']['advance']:
                                stats['sample_actions']['advance'] = line.strip()
                        else:
                            stats['parse_errors'].append({
                                'episode': current_episode_num,
                                'turn': turn,
                                'phase': phase,
                                'line': line.strip(),
                                'error': f"Advance action missing 'from/to' format: {action_desc[:100]}"
                            })

                elif "CHARGED Unit" in action_desc:
                        action_type = 'charge'
                        
                        # Try successful charge format: "Unit X(col,row) CHARGED Unit Y(col,row) from (start_col,start_row) to (dest_col,dest_row)"
                        charge_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\) CHARGED Unit (\d+)(?:\((\d+),\s*(\d+)\))? from \((\d+),\s*(\d+)\) to \((\d+),\s*(\d+)\)', action_desc)
                        if charge_match:
                            charge_unit_id = charge_match.group(1)
                            charge_target_id = charge_match.group(4)  # Target unit ID
                            dest_col = int(charge_match.group(9))  # from "to (dest_col,dest_row)"
                            dest_row = int(charge_match.group(10))
                            start_col = int(charge_match.group(7))  # from "from (start_col,start_row)"
                            start_row = int(charge_match.group(8))
                            _track_action_phase_accuracy(stats, "charge", phase, current_episode_num, line)
                            stats['charge_invalid'][player]['total'] += 1
                            if charge_unit_id in units_advanced:
                                charge_unit_type = require_key(unit_types, charge_unit_id)
                                unit_rules = require_key(unit_rules_by_type, charge_unit_type)
                                if "charge_after_advance" in unit_rules:
                                    stats['charge_after_advance_used'][player] += 1
                                else:
                                    stats['charge_invalid'][player]['advanced'] += 1
                                    if stats['first_error_lines']['charge_invalid'][player] is None:
                                        stats['first_error_lines']['charge_invalid'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            if charge_unit_id in units_fled:
                                stats['charge_invalid'][player]['fled'] += 1
                                if stats['first_error_lines']['charge_invalid'][player] is None:
                                    stats['first_error_lines']['charge_invalid'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            charge_roll_match = re.search(r'\[Roll:(\d+)\]', action_desc)
                            if charge_roll_match:
                                charge_roll = int(charge_roll_match.group(1))
                                charge_distance = calculate_hex_distance(start_col, start_row, dest_col, dest_row)
                                if charge_distance > charge_roll:
                                    stats['charge_invalid'][player]['distance_over_roll'] += 1
                                    if stats['first_error_lines']['charge_invalid'][player] is None:
                                        stats['first_error_lines']['charge_invalid'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            
                            stats['position_log_mismatch']['charge']['total'] += 1
                            if charge_unit_id not in unit_positions:
                                stats['position_log_mismatch']['charge']['missing'] += 1
                                if stats['first_error_lines']['position_log_mismatch']['charge'] is None:
                                    stats['first_error_lines']['position_log_mismatch']['charge'] = {
                                        'episode': current_episode_num,
                                        'line': line.strip()
                                    }
                            elif unit_positions[charge_unit_id] != (start_col, start_row):
                                stats['position_log_mismatch']['charge']['mismatch'] += 1
                                if stats['first_error_lines']['position_log_mismatch']['charge'] is None:
                                    stats['first_error_lines']['position_log_mismatch']['charge'] = {
                                        'episode': current_episode_num,
                                        'line': line.strip()
                                    }
                            
                            # RULE: Dead unit charging
                            charge_unit_dead = charge_unit_id not in unit_hp or require_key(unit_hp, charge_unit_id) <= 0
                            if charge_unit_dead:
                                unit_died_before_charge = False
                                phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
                                current_phase_order = require_key(phase_order, phase)
                                for death_turn, death_phase, dead_unit_id, death_line_num in unit_deaths:
                                    if dead_unit_id == charge_unit_id:
                                        if death_turn < turn:
                                            unit_died_before_charge = True
                                            break
                                        if death_turn == turn:
                                            death_phase_order = require_key(phase_order, death_phase)
                                            if death_phase_order < current_phase_order:
                                                unit_died_before_charge = True
                                                break
                                            if death_phase_order == current_phase_order and death_line_num < line_number:
                                                unit_died_before_charge = True
                                                break
                                if unit_died_before_charge:
                                    stats['dead_unit_charging'][player] += 1
                                    if stats['first_error_lines']['dead_unit_charging'][player] is None:
                                        stats['first_error_lines']['dead_unit_charging'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            if charge_unit_id in unit_hp and require_key(unit_hp, charge_unit_id) > 0:
                                charged_units_current_fight.add(charge_unit_id)
                            
                            # CRITICAL: Sync position cache with log start position before processing
                            if charge_unit_id in unit_positions and unit_positions[charge_unit_id] != (start_col, start_row):
                                _position_cache_set(unit_positions, charge_unit_id, start_col, start_row)
                            
                            # RULE: Charge from adjacent
                            # CRITICAL: Use the log's "from" position (start_col, start_row) which is the actual position
                            # the unit is at when charging. This matches the engine logic which checks get_unit_coordinates(unit)
                            # at charge activation time. The log's "from" position is the source of truth for where the unit
                            # actually was when it charged, regardless of what unit_positions contains.
                            # CRITICAL: If unit advanced before charging, it should not be in charge pool (units_advanced cannot charge).
                            # So skip adjacency check for advanced units - this should be caught by "charge after advance" check instead.
                            # However, if unit did charge after advancing, we still check adjacency at charge position for completeness.
                            if charge_unit_id not in units_advanced:
                                # Only check adjacency if unit did NOT advance (normal case)
                                if is_adjacent_to_enemy(start_col, start_row, unit_player, unit_positions, unit_hp, player):
                                    # DEBUG: Log which enemy is adjacent for debugging
                                    adjacent_enemies = get_adjacent_enemies(start_col, start_row, unit_player, unit_positions, unit_hp, unit_types, player)
                                    if adjacent_enemies:
                                        _debug_log(f"[CHARGE DEBUG] E{current_episode_num} T{turn} Unit {charge_unit_id} at ({start_col},{start_row}) is adjacent to enemies: {adjacent_enemies}")
                                    stats['charge_from_adjacent'][player] += 1
                                    if stats['first_error_lines']['charge_from_adjacent'][player] is None:
                                        stats['first_error_lines']['charge_from_adjacent'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            
                            # RULE: Charge after fled
                            if charge_unit_id in units_fled:
                                stats['charge_after_fled'][player] += 1
                                if stats['first_error_lines']['charge_after_fled'][player] is None:
                                    stats['first_error_lines']['charge_after_fled'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            
                            # RULE: Charge a dead unit
                            # Target ID is already extracted from charge_match above
                            # Check if target is dead at the time of charge
                            # CRITICAL: Check if target died BEFORE this charge action
                            target_is_dead = charge_target_id not in unit_hp or require_key(unit_hp, charge_target_id) <= 0
                            if target_is_dead:
                                # Verify this is a real bug (target died before charge, not after)
                                is_false_positive = False
                                phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
                                current_phase_order = require_key(phase_order, phase)
                                
                                # Find when target died (if it did)
                                target_died_before_charge = False
                                for death_turn, death_phase, dead_unit_id, death_line_num in unit_deaths:
                                    if dead_unit_id == charge_target_id:
                                        # Target died - check if it's BEFORE this charge action
                                        if death_turn < turn:
                                            target_died_before_charge = True
                                            break
                                        elif death_turn == turn:
                                            death_phase_order = require_key(phase_order, death_phase)
                                            if death_phase_order < current_phase_order:
                                                target_died_before_charge = True
                                                break
                                            elif death_phase_order == current_phase_order and death_line_num < line_number:
                                                target_died_before_charge = True
                                                break
                                
                                # Only report if target died before charge
                                if target_died_before_charge:
                                    stats['charge_dead_unit'][player] += 1
                                    if stats['first_error_lines']['charge_dead_unit'][player] is None:
                                        stats['first_error_lines']['charge_dead_unit'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            
                            # Record this movement in history (source of truth)
                            if charge_unit_id not in unit_movement_history:
                                unit_movement_history[charge_unit_id] = []
                            timestamp_match = re.search(r'\[(\d+:\d+:\d+)\]', line)
                            timestamp = timestamp_match.group(1) if timestamp_match else None
                            unit_movement_history[charge_unit_id].append({
                                'position': (dest_col, dest_row),
                                'timestamp': timestamp,
                                'action': 'charge',
                                'turn': turn,
                                'episode': current_episode_num
                            })
                            
                            # RULE: Position collision
                            # CRITICAL: Check for collisions BEFORE updating position
                            # This catches cases where another unit is already at the destination
                            # before this unit moves there
                            if (start_col, start_row) != (dest_col, dest_row):
                                # Store positions of potential colliding units BEFORE we update
                                colliding_units_before = {}
                                for uid, current_pos in unit_positions.items():
                                    if current_pos != (dest_col, dest_row) or uid == charge_unit_id:
                                        continue
                                    if uid not in unit_hp:
                                        stats['parse_errors'].append({
                                            'episode': current_episode_num,
                                            'turn': turn,
                                            'phase': phase,
                                            'line': line.strip(),
                                            'error': f"Charge collision missing unit_hp for unit_id: {uid}"
                                        })
                                        continue
                                    hp_value = _get_unit_hp_value(
                                        unit_hp,
                                        uid,
                                        stats,
                                        current_episode_num,
                                        turn,
                                        phase,
                                        line,
                                        "Charge collision"
                                    )
                                    if hp_value is None:
                                        continue
                                    if hp_value > 0:
                                        colliding_units_before[uid] = current_pos
                                
                                # Update position cache (only if unit still alive)
                                if charge_unit_id not in unit_hp:
                                    stats['parse_errors'].append({
                                        'episode': current_episode_num,
                                        'turn': turn,
                                        'phase': phase,
                                        'line': line.strip(),
                                        'error': f"Charge action for unknown unit_id (missing in unit_hp): {charge_unit_id}"
                                    })
                                    continue
                                if require_key(unit_hp, charge_unit_id) > 0:
                                    old_position = unit_positions.get(charge_unit_id)
                                    _position_cache_set(unit_positions, charge_unit_id, dest_col, dest_row)
                                
                                # CRITICAL: Verify collision is real by checking:
                                # 1. Colliding unit is STILL at destination after position update
                                # 2. Colliding unit is still alive
                                # 3. Colliding unit's position hasn't changed (i.e., it didn't move at this timestamp)
                                # 4. Colliding unit actually moved to this position according to movement history (source of truth)
                                real_colliding_units = []
                                for uid, pos_before in colliding_units_before.items():
                                    # Check if this unit is still at the destination AFTER we updated our position
                                    # AND still alive (HP > 0)
                                    # AND its position hasn't changed (i.e., it didn't move at this timestamp)
                                    if (uid in unit_positions and 
                                        unit_positions[uid] == (dest_col, dest_row) and
                                        unit_positions[uid] == pos_before and  # Position hasn't changed
                                        uid in unit_hp and
                                        require_key(unit_hp, uid) > 0):
                                        # CRITICAL: Verify that this unit actually moved to this position according to logs
                                        # Since we process actions line by line, we need to check if this unit
                                        # has already been processed and moved to this position
                                        # OR if it will be processed later (we can't know, so we skip it)
                                        # The safest approach is to only report collisions for units that have
                                        # already been processed (i.e., have movement history)
                                        if uid in unit_movement_history:
                                            # Check if this unit has a movement record to this position
                                            # AND it was in the SAME episode and turn (to avoid cross-episode/turn false positives)
                                            # CRITICAL: Only report collision if the movement history matches
                                            # the exact episode, turn, and position
                                            # Also verify that the episode number is valid (should be > 0)
                                            # CRITICAL: Only report collision if the movement history matches
                                            # the exact episode, turn, and position
                                            # Verify that episode is defined and matches current_episode_num
                                            has_moved_to_dest = any(
                                                move['position'] == (dest_col, dest_row) 
                                                and move.get('turn') == turn
                                                and move.get('episode') is not None
                                                and move.get('episode') == current_episode_num
                                                and current_episode_num > 0  # Additional safety check
                                                for move in unit_movement_history[uid]
                                            )
                                            if has_moved_to_dest:
                                                real_colliding_units.append(uid)
                                        else:
                                            # Unit has no movement history - it hasn't been processed yet
                                            # OR it's at its starting position
                                            # Since we can't know if it will move to this position later,
                                            # we skip it to avoid false positives
                                            # This means we might miss some real collisions, but it's better
                                            # than reporting false positives
                                            pass
                                
                                # Only report collision if there are real colliding units
                                # AND the colliding unit's position hasn't changed (i.e., it didn't move at this timestamp)
                                if real_colliding_units:
                                    stats['unit_position_collisions'].append({
                                        'episode': current_episode_num,
                                        'turn': turn,
                                        'position': (dest_col, dest_row),
                                        'units': real_colliding_units + [charge_unit_id],
                                        'action': 'charge',
                                        'charge_from': (start_col, start_row),
                                        'charge_to': (dest_col, dest_row)
                                    })
                            else:
                                # No movement - just update position cache if unit still alive
                                if require_key(unit_hp, charge_unit_id) > 0:
                                    _position_cache_set(unit_positions, charge_unit_id, dest_col, dest_row)
                            
                            # Sample action
                            if not stats['sample_actions']['charge']:
                                stats['sample_actions']['charge'] = line.strip()
                        else:
                            # Check if it's a FAILED charge (valid format, just failed)
                            # Format: Unit X(col,row) FAILED CHARGE unit Y from (a,b) to (c,d)
                            failed_charge_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\) FAILED CHARGE unit (\d+) from \((\d+),\s*(\d+)\) to \((\d+),\s*(\d+)\)', action_desc)
                            if failed_charge_match:
                                # Extract failed charge data (for potential future analysis)
                                failed_charge_unit_id = failed_charge_match.group(1)
                                failed_charge_target_id = failed_charge_match.group(4)
                                start_col = int(failed_charge_match.group(5))
                                start_row = int(failed_charge_match.group(6))
                                dest_col = int(failed_charge_match.group(7))
                                dest_row = int(failed_charge_match.group(8))
                                
                                # Note: Failed charges don't move units, so we don't update unit_positions
                                # But we could track failed charge attempts for statistics if needed
                                
                                # Sample action (if not already set)
                                if not stats['sample_actions']['charge']:
                                    stats['sample_actions']['charge'] = line.strip()
                            else:
                                # Only log as parse error if it's not a FAILED charge
                                stats['parse_errors'].append({
                                    'episode': current_episode_num,
                                    'turn': turn,
                                    'phase': phase,
                                    'line': line.strip(),
                                    'error': f"Charge action missing expected format: {action_desc[:100]}"
                                })

                elif "MOVED from" in action_desc or "FLED from" in action_desc:
                        action_type = 'move'
                        
                        # CRITICAL: Detect explicit FLED actions first
                        fled_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\) FLED from \((\d+),\s*(\d+)\) to \((\d+),\s*(\d+)\)', action_desc)
                        if fled_match:
                            move_unit_id = fled_match.group(1)
                            start_col = int(fled_match.group(4))
                            start_row = int(fled_match.group(5))
                            dest_col = int(fled_match.group(6))
                            dest_row = int(fled_match.group(7))
                            action_type = 'fled'
                            
                            units_moved.add(move_unit_id)
                            # CRITICAL: Explicit FLED action - mark as fled
                            units_fled.add(move_unit_id)
                            _track_action_phase_accuracy(stats, "fled", phase, current_episode_num, line)
                            if stats['first_error_lines']['fled_action'][player] is None:
                                stats['first_error_lines']['fled_action'][player] = {
                                    'episode': current_episode_num,
                                    'line': line.strip()
                                }
                            
                            # DEBUG: Log FLED action processing
                            _debug_log(f"[FLED DEBUG] E{current_episode_num} T{turn} P{player}: Unit {move_unit_id} FLED from ({start_col},{start_row}) to ({dest_col},{dest_row})")
                            if move_unit_id in unit_positions:
                                _debug_log(f"[FLED DEBUG] BEFORE sync: unit_positions[{move_unit_id}] = {unit_positions[move_unit_id]}")
                            else:
                                stats['parse_errors'].append({
                                    'episode': current_episode_num,
                                    'turn': turn,
                                    'phase': phase,
                                    'line': line.strip(),
                                    'error': f"FLED debug missing unit position for unit_id: {move_unit_id}"
                                })
                                _debug_log(f"[FLED DEBUG] BEFORE sync: unit_positions[{move_unit_id}] is missing")
                            
                            # CRITICAL FIX: For FLED actions, don't synchronize with start position
                            # The log already contains both start and destination positions
                            # We should use the destination position directly, not synchronize with start
                            # This prevents unit_positions from being set to (start_col, start_row) and then
                            # potentially not being updated to (dest_col, dest_row) if unit_hp <= 0
                            # Instead, we update directly to the destination position
                            # CRITICAL: Only update position if unit is still alive
                            # Dead units should not have their positions updated (they were removed when they died)
                            if move_unit_id not in unit_hp:
                                stats['parse_errors'].append({
                                    'episode': current_episode_num,
                                    'turn': turn,
                                    'phase': phase,
                                    'line': line.strip(),
                                    'error': f"FLED update missing unit_hp for unit_id: {move_unit_id}"
                                })
                                continue
                            unit_hp_value = require_key(unit_hp, move_unit_id)
                            _debug_log(f"[FLED DEBUG] BEFORE update: unit_hp[{move_unit_id}] = {unit_hp_value}")
                            if unit_hp_value > 0:
                                old_position = unit_positions.get(move_unit_id)
                                _position_cache_set(unit_positions, move_unit_id, dest_col, dest_row)
                                _debug_log(f"[FLED DEBUG] AFTER update: unit_positions[{move_unit_id}] = {unit_positions[move_unit_id]} (was {old_position})")
                            else:
                                _debug_log(f"[FLED DEBUG] SKIPPED update: unit_hp[{move_unit_id}] = {unit_hp_value} (<= 0)")
                            
                            # Record this movement in history (source of truth)
                            if move_unit_id not in unit_movement_history:
                                unit_movement_history[move_unit_id] = []
                            timestamp_match = re.search(r'\[(\d+:\d+:\d+)\]', line)
                            timestamp = timestamp_match.group(1) if timestamp_match else None
                            unit_movement_history[move_unit_id].append({
                                'position': (dest_col, dest_row),
                                'timestamp': timestamp,
                                'action': 'fled',
                                'turn': turn,
                                'episode': current_episode_num
                            })
                            
                            if (start_col, start_row) != (dest_col, dest_row):
                                # RULE: Position collision
                                # CRITICAL FIX: Only report collision if colliding unit is STILL at destination
                                # after we update positions. This prevents false positives where Unit A moves to X,
                                # then Unit B moves to X after Unit A has left.
                                colliding_units = []
                                for uid, current_pos in unit_positions.items():
                                    if current_pos != (dest_col, dest_row) or uid == move_unit_id:
                                        continue
                                    if uid not in unit_hp:
                                        stats['parse_errors'].append({
                                            'episode': current_episode_num,
                                            'turn': turn,
                                            'phase': phase,
                                            'line': line.strip(),
                                            'error': f"Collision check missing unit_hp for unit_id: {uid}"
                                        })
                                        continue
                                    hp_value = _get_unit_hp_value(
                                        unit_hp,
                                        uid,
                                        stats,
                                        current_episode_num,
                                        turn,
                                        phase,
                                        line,
                                        "Move collision"
                                    )
                                    if hp_value is None:
                                        continue
                                    if hp_value > 0:
                                        colliding_units.append(uid)
                                
                                # Position already updated above - check if collision is real
                                
                                # CRITICAL: Verify collision is real by checking if colliding units
                                # are STILL at destination after position update
                                # If a colliding unit has moved away, it's not a real collision
                                real_colliding_units = []
                                for uid in colliding_units:
                                    # Check if this unit is still at the destination
                                    # If unit_positions[uid] has changed, it means the unit moved away
                                    # and this is not a real collision
                                    if uid in unit_positions and unit_positions[uid] == (dest_col, dest_row):
                                        real_colliding_units.append(uid)
                                
                                # Only report collision if there are real colliding units
                                if real_colliding_units:
                                    stats['unit_position_collisions'].append({
                                        'episode': current_episode_num,
                                        'turn': turn,
                                        'position': (dest_col, dest_row),
                                        'units': real_colliding_units + [move_unit_id],
                                        'action': 'move',
                                        'move_from': (start_col, start_row),
                                        'move_to': (dest_col, dest_row)
                                    })
                                
                                # RULE: Move into wall
                                if (dest_col, dest_row) in wall_hexes:
                                    stats['wall_collisions'][player] += 1
                            else:
                                # No movement - just update position cache if unit still alive
                                if require_key(unit_hp, move_unit_id) > 0:
                                    _position_cache_set(unit_positions, move_unit_id, dest_col, dest_row)
                            
                            # Sample action
                            if not stats['sample_actions']['move']:
                                stats['sample_actions']['move'] = line.strip()
                            continue  # Skip normal move processing for FLED
                        
                        move_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\) MOVED from \((\d+),\s*(\d+)\) to \((\d+),\s*(\d+)\)', action_desc)
                        if move_match:
                            move_unit_id = move_match.group(1)
                            start_col = int(move_match.group(4))
                            start_row = int(move_match.group(5))
                            dest_col = int(move_match.group(6))
                            dest_row = int(move_match.group(7))
                            _track_action_phase_accuracy(stats, "move", phase, current_episode_num, line)
                            
                            stats['position_log_mismatch']['move']['total'] += 1
                            if move_unit_id not in unit_positions:
                                stats['position_log_mismatch']['move']['missing'] += 1
                                if stats['first_error_lines']['position_log_mismatch']['move'] is None:
                                    stats['first_error_lines']['position_log_mismatch']['move'] = {
                                        'episode': current_episode_num,
                                        'line': line.strip()
                                    }
                            elif unit_positions[move_unit_id] != (start_col, start_row):
                                stats['position_log_mismatch']['move']['mismatch'] += 1
                                if stats['first_error_lines']['position_log_mismatch']['move'] is None:
                                    stats['first_error_lines']['position_log_mismatch']['move'] = {
                                        'episode': current_episode_num,
                                        'line': line.strip()
                                    }
                            
                            # RULE: Dead unit moving
                            move_unit_dead = move_unit_id not in unit_hp or require_key(unit_hp, move_unit_id) <= 0
                            if move_unit_dead:
                                unit_died_before_move = False
                                phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
                                current_phase_order = require_key(phase_order, phase)
                                for death_turn, death_phase, dead_unit_id, death_line_num in unit_deaths:
                                    if dead_unit_id == move_unit_id:
                                        if death_turn < turn:
                                            unit_died_before_move = True
                                            break
                                        if death_turn == turn:
                                            death_phase_order = require_key(phase_order, death_phase)
                                            if death_phase_order < current_phase_order:
                                                unit_died_before_move = True
                                                break
                                            if death_phase_order == current_phase_order and death_line_num < line_number:
                                                unit_died_before_move = True
                                                break
                                if unit_died_before_move:
                                    stats['dead_unit_moving'][player] += 1
                                    if stats['first_error_lines']['dead_unit_moving'][player] is None:
                                        stats['first_error_lines']['dead_unit_moving'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            
                            units_moved.add(move_unit_id)
                            
                            # CRITICAL: Rebuild positions_at_move_phase_start using "from" positions from log
                            # This ensures we have accurate positions at the start of MOVE phase
                            # The "from" position in the log is the position at the start of the movement
                            # CRITICAL FIX (Episodes 32, 112): When rebuilding positions_at_move_phase_start,
                            # we must use the "from" positions from ALL MOVE actions in the current phase,
                            # not just unit_positions which may contain stale positions from previous phases
                            # The issue: unit_positions may contain stale positions for enemy units that moved in P1 MOVE
                            # Solution: Update positions_at_move_phase_start for enemy units using their current positions
                            # from unit_positions, but only if they haven't moved yet in P2 MOVE
                            # If they have moved in P2 MOVE, their "from" position is already in positions_at_move_phase_start
                            # CRITICAL: Sync position cache with log start position before filling snapshot
                            if move_unit_id not in unit_positions or unit_positions[move_unit_id] != (start_col, start_row):
                                _position_cache_set(unit_positions, move_unit_id, start_col, start_row)
                            
                            if move_unit_id not in positions_at_move_phase_start:
                                # First MOVE action for this unit in this MOVE phase - add its "from" position
                                positions_at_move_phase_start[move_unit_id] = (start_col, start_row)
                                # CRITICAL FIX: For other units, use their current positions from unit_positions
                                # BUT: unit_positions must be synchronized with log first (done above)
                                # This ensures positions_at_move_phase_start contains accurate positions
                                for uid, pos in unit_positions.items():
                                    if uid not in positions_at_move_phase_start:
                                        positions_at_move_phase_start[uid] = pos
                                # CRITICAL FIX (Episode 85): After filling positions_at_move_phase_start, verify that
                                # enemy units that FLED in P1 MOVE have their correct positions (destination, not source)
                                # This is a safety check to ensure positions_at_move_phase_start reflects the state
                                # at the START of P2 MOVE, not during P1 MOVE
                            
                            # RULE: Detect fled (was adjacent to enemy at start of MOVE phase, then moved)
                            # CRITICAL: Use positions_at_move_phase_start which now contains accurate positions
                            # reconstructed from "from" positions in the log
                            # CRITICAL FIX (Episode 24): Only detect FLED if the unit was actually adjacent to an enemy
                            # at its starting position using the CORRECT enemy positions at the start of THIS player's MOVE phase
                            # The check must use positions_at_move_phase_start for enemy positions, but this may be incomplete
                            # if this is the first move of the phase. For safety, require BOTH checks to agree to avoid false positives.
                            if move_unit_id in positions_at_move_phase_start:
                                start_pos = positions_at_move_phase_start[move_unit_id]
                                # CRITICAL: positions_at_move_phase_start may not have all enemy positions if this is the first move
                                # Filter positions_at_move_phase_start to only include enemy units that are alive
                                # This ensures we only check adjacency against valid enemies
                                # CRITICAL: Normalize player values to int for consistent comparison (handles int/string mismatches)
                                enemy_player = 3 - player
                                enemy_player_int = int(enemy_player) if enemy_player is not None else None
                                enemy_positions_in_snapshot = {}
                                for uid, pos in positions_at_move_phase_start.items():
                                    if uid not in unit_player or uid not in unit_hp:
                                        _debug_log(
                                            f"[ANALYZER DEBUG] Snapshot adjacency missing unit data for unit_id: {uid} "
                                            f"(episode={current_episode_num}, turn={turn}, phase={phase})"
                                        )
                                        continue
                                    hp_value = _get_unit_hp_value(
                                        unit_hp,
                                        uid,
                                        stats,
                                        current_episode_num,
                                        turn,
                                        phase,
                                        line,
                                        "Snapshot adjacency"
                                    )
                                    if hp_value is None:
                                        continue
                                    if (int(require_key(unit_player, uid)) if require_key(unit_player, uid) is not None else None) == enemy_player_int and hp_value > 0:
                                        enemy_positions_in_snapshot[uid] = pos
                                # Also filter unit_positions for current check
                                enemy_positions_current = {}
                                for uid, pos in unit_positions.items():
                                    if uid not in unit_player or uid not in unit_hp:
                                        _debug_log(
                                            f"[ANALYZER DEBUG] Current adjacency missing unit data for unit_id: {uid} "
                                            f"(episode={current_episode_num}, turn={turn}, phase={phase})"
                                        )
                                        continue
                                    hp_value = _get_unit_hp_value(
                                        unit_hp,
                                        uid,
                                        stats,
                                        current_episode_num,
                                        turn,
                                        phase,
                                        line,
                                        "Current adjacency"
                                    )
                                    if hp_value is None:
                                        continue
                                    if (int(require_key(unit_player, uid)) if require_key(unit_player, uid) is not None else None) == enemy_player_int and hp_value > 0:
                                        enemy_positions_current[uid] = pos
                                # CRITICAL FIX: Use filtered enemy positions for both checks
                                was_adjacent_in_snapshot = is_adjacent_to_enemy(start_pos[0], start_pos[1], unit_player, 
                                                                               enemy_positions_in_snapshot, unit_hp, player)
                                was_adjacent_in_current = is_adjacent_to_enemy(start_pos[0], start_pos[1], unit_player, 
                                                                              enemy_positions_current, unit_hp, player)
                                # CRITICAL FIX (Episodes 32, 112, 85): Require BOTH checks to agree (reduces false positives)
                                # AND require that we have at least 2 units in snapshot (this unit + at least one other)
                                # AND require that enemy_positions_current has at least one enemy (ensures unit_positions is up-to-date)
                                # AND require that enemy_positions_in_snapshot has at least one enemy (ensures snapshot has enemy data)
                                # This ensures we have enough data to make a reliable decision
                                # The snapshot check may use stale positions for enemy units that moved in P1 MOVE,
                                # but the current check uses unit_positions which should be up-to-date after processing all P1 MOVE actions
                                # CRITICAL: If the two checks disagree, it means positions_at_move_phase_start contains stale positions
                                # (e.g., enemy unit FLED in P1 MOVE but positions_at_move_phase_start has its pre-FLED position)
                                # In this case, we should NOT mark the unit as having fled, as it's likely a false positive
                                # Only mark as fled if BOTH checks agree AND we have sufficient data in BOTH sources
                                if (was_adjacent_in_snapshot and was_adjacent_in_current and 
                                    len(positions_at_move_phase_start) >= 2 and 
                                    len(enemy_positions_current) > 0 and 
                                    len(enemy_positions_in_snapshot) > 0):
                                    _debug_log(f"[FLED DEBUG] E{current_episode_num} T{turn} P{player}: Unit {move_unit_id} FLED from {start_pos} to ({dest_col},{dest_row}) - explicit FLED only (no inferred flag)")
                                elif was_adjacent_in_snapshot and not was_adjacent_in_current:
                                    # Snapshot says adjacent but current says not - this indicates stale positions in snapshot
                                    # Don't mark as fled to avoid false positives
                                    _debug_log(f"[FLED DEBUG] E{current_episode_num} T{turn} P{player}: Unit {move_unit_id} at {start_pos} - snapshot says adjacent but current says not (stale positions in snapshot), NOT marking as fled")
                                elif not was_adjacent_in_snapshot and was_adjacent_in_current:
                                    # Current says adjacent but snapshot says not - this indicates unit_positions is stale
                                    # Don't mark as fled to avoid false positives
                                    _debug_log(f"[FLED DEBUG] E{current_episode_num} T{turn} P{player}: Unit {move_unit_id} at {start_pos} - current says adjacent but snapshot says not (stale positions in unit_positions), NOT marking as fled")
                                elif len(enemy_positions_in_snapshot) == 0:
                                    # No enemy data in snapshot - cannot reliably detect fled
                                    # Don't mark as fled to avoid false positives
                                    _debug_log(f"[FLED DEBUG] E{current_episode_num} T{turn} P{player}: Unit {move_unit_id} at {start_pos} - no enemy data in snapshot, NOT marking as fled")
                            
                            if (start_col, start_row) != (dest_col, dest_row):
                                # Record this movement in history (source of truth)
                                if move_unit_id not in unit_movement_history:
                                    unit_movement_history[move_unit_id] = []
                                # Extract timestamp from line if available
                                timestamp_match = re.search(r'\[(\d+:\d+:\d+)\]', line)
                                timestamp = timestamp_match.group(1) if timestamp_match else None
                                unit_movement_history[move_unit_id].append({
                                    'position': (dest_col, dest_row),
                                    'timestamp': timestamp,
                                    'action': 'move',
                                    'turn': turn,
                                    'episode': current_episode_num
                                })
                                
                                # CRITICAL FIX: Save ALL unit positions BEFORE updating for adjacency check
                                # This ensures we use positions at the moment of movement, not after other units moved
                                # CRITICAL: Use positions_at_move_phase_start if available, as it contains positions
                                # reconstructed from log "from" positions, which are more accurate than unit_positions
                                # which may contain stale positions for enemy units
                                if positions_at_move_phase_start:
                                    positions_at_movement = dict(positions_at_move_phase_start)
                                    # Update with current unit_positions for units that have moved in this phase
                                    for uid, pos in unit_positions.items():
                                        if uid in units_moved:
                                            positions_at_movement[uid] = pos
                                else:
                                    positions_at_movement = dict(unit_positions)
                                
                                # CRITICAL FIX: Save unit_hp snapshot at movement time to prevent false positives
                                # If a unit dies AFTER movement but BEFORE check, we should use its HP at movement time
                                unit_hp_at_movement = dict(unit_hp)

                                move_range_raw = require_key(unit_move, move_unit_id)
                                move_range = int(move_range_raw)
                                occupied_positions = _build_occupied_positions(positions_at_movement, unit_hp_at_movement, move_unit_id)
                                enemy_adjacent_hexes = _build_enemy_adjacent_hexes(positions_at_movement, unit_player, unit_hp_at_movement, player)
                                shortest_steps = _bfs_shortest_path_length(
                                    start_col,
                                    start_row,
                                    dest_col,
                                    dest_row,
                                    move_range,
                                    wall_hexes,
                                    occupied_positions,
                                    enemy_adjacent_hexes
                                )
                                if shortest_steps is None:
                                    stats['move_path_blocked']['move'][player] += 1
                                    if stats['first_error_lines']['move_path_blocked']['move'][player] is None:
                                        stats['first_error_lines']['move_path_blocked']['move'][player] = {
                                            'episode': current_episode_num,
                                            'line': line.strip()
                                        }
                                elif shortest_steps > move_range:
                                    stats['move_distance_over_limit']['move'][player] += 1
                                    if stats['first_error_lines']['move_distance_over_limit']['move'][player] is None:
                                        stats['first_error_lines']['move_distance_over_limit']['move'][player] = {
                                            'episode': current_episode_num,
                                            'line': line.strip()
                                        }
                                
                                # RULE: Position collision
                                # CRITICAL: Check for collisions BEFORE updating position
                                # This catches cases where another unit is already at the destination
                                # before this unit moves there
                                # Store positions of potential colliding units BEFORE we update
                                colliding_units_before = {}
                                for uid, current_pos in unit_positions.items():
                                    if current_pos != (dest_col, dest_row) or uid == move_unit_id:
                                        continue
                                    if uid not in unit_hp:
                                        stats['parse_errors'].append({
                                            'episode': current_episode_num,
                                            'turn': turn,
                                            'phase': phase,
                                            'line': line.strip(),
                                            'error': f"Move collision missing unit_hp for unit_id: {uid}"
                                        })
                                        continue
                                    hp_value = _get_unit_hp_value(
                                        unit_hp,
                                        uid,
                                        stats,
                                        current_episode_num,
                                        turn,
                                        phase,
                                        line,
                                        "Move collision"
                                    )
                                    if hp_value is None:
                                        continue
                                    if hp_value > 0:
                                        colliding_units_before[uid] = current_pos
                                
                                # Update position cache (only if unit still alive)
                                if move_unit_id not in unit_hp:
                                    stats['parse_errors'].append({
                                        'episode': current_episode_num,
                                        'turn': turn,
                                        'phase': phase,
                                        'line': line.strip(),
                                        'error': f"Move action for unknown unit_id (missing in unit_hp): {move_unit_id}"
                                    })
                                    continue
                                if require_key(unit_hp, move_unit_id) > 0:
                                    old_position = unit_positions.get(move_unit_id)
                                    _position_cache_set(unit_positions, move_unit_id, dest_col, dest_row)
                                    # CRITICAL FIX (Episodes 32, 112): Update positions_at_move_phase_start for enemy units
                                    # If this is an enemy unit that moved in P1 MOVE, we need to track its position
                                    # so that when P2 MOVE starts, positions_at_move_phase_start has correct enemy positions
                                    # This prevents false "fled" detection when P2 units check adjacency
                                    # NOTE: positions_at_move_phase_start is reset at the start of each MOVE phase,
                                    # so we can't update it here for P1 units. Instead, we rely on unit_positions
                                    # being up-to-date, which it should be after this update.
                                    # The real fix is to ensure unit_positions is always up-to-date (which it is here)
                                
                                # CRITICAL: Verify collision is real by checking:
                                # 1. Colliding unit is STILL at destination after position update
                                # 2. Colliding unit is still alive
                                # 3. Colliding unit's position hasn't changed (i.e., it didn't move at this timestamp)
                                # 4. Colliding unit actually moved to this position according to movement history (source of truth)
                                real_colliding_units = []
                                for uid, pos_before in colliding_units_before.items():
                                    # Check if this unit is still at the destination AFTER we updated our position
                                    # AND still alive (HP > 0)
                                    # AND its position hasn't changed (i.e., it didn't move at this timestamp)
                                    if (uid in unit_positions and 
                                        unit_positions[uid] == (dest_col, dest_row) and
                                        unit_positions[uid] == pos_before and  # Position hasn't changed
                                        uid in unit_hp and
                                        require_key(unit_hp, uid) > 0):
                                        # CRITICAL: Verify that this unit actually moved to this position according to logs
                                        # Since we process actions line by line, we need to check if this unit
                                        # has already been processed and moved to this position
                                        # OR if it will be processed later (we can't know, so we skip it)
                                        # The safest approach is to only report collisions for units that have
                                        # already been processed (i.e., have movement history)
                                        if uid in unit_movement_history:
                                            # Check if this unit has a movement record to this position
                                            # AND it was in the SAME episode and turn (to avoid cross-episode/turn false positives)
                                            # CRITICAL: Only report collision if the movement history matches
                                            # the exact episode, turn, and position
                                            # Also verify that the episode number is valid (should be > 0)
                                            # CRITICAL: Only report collision if the movement history matches
                                            # the exact episode, turn, and position
                                            # Verify that episode is defined and matches current_episode_num
                                            has_moved_to_dest = any(
                                                move['position'] == (dest_col, dest_row) 
                                                and move.get('turn') == turn
                                                and move.get('episode') is not None
                                                and move.get('episode') == current_episode_num
                                                and current_episode_num > 0  # Additional safety check
                                                for move in unit_movement_history[uid]
                                            )
                                            if has_moved_to_dest:
                                                real_colliding_units.append(uid)
                                        else:
                                            # Unit has no movement history - it hasn't been processed yet
                                            # OR it's at its starting position
                                            # Since we can't know if it will move to this position later,
                                            # we skip it to avoid false positives
                                            # This means we might miss some real collisions, but it's better
                                            # than reporting false positives
                                            pass
                                
                                # Only report collision if there are real colliding units
                                # AND the colliding unit actually moved to this position according to logs
                                if real_colliding_units:
                                    stats['unit_position_collisions'].append({
                                        'episode': current_episode_num,
                                        'turn': turn,
                                        'position': (dest_col, dest_row),
                                        'units': real_colliding_units + [move_unit_id],
                                        'action': 'move',
                                        'move_from': (start_col, start_row),
                                        'move_to': (dest_col, dest_row)
                                    })
                                
                                # RULE: Move to adjacent enemy
                                # CRITICAL FIX: Use positions_at_movement (saved BEFORE this unit's position update)
                                # to check adjacency. This ensures we use positions at the moment of movement,
                                # not after other units moved in the same turn.
                                # Only update this unit's position in the snapshot for the "after" check
                                positions_for_adjacency_check = dict(positions_at_movement)
                                positions_for_adjacency_check[move_unit_id] = (dest_col, dest_row)
                                
                                # CRITICAL FIX: Filter out dead units from positions_for_adjacency_check
                                # to prevent false positives. Dead units should not be considered for adjacency checks.
                                # Use unit_hp_at_movement (snapshot at movement time) instead of current unit_hp
                                positions_for_adjacency_check_filtered = {}
                                for uid, hp_value in unit_hp_at_movement.items():
                                    if hp_value <= 0:
                                        continue
                                    pos = positions_for_adjacency_check.get(uid)
                                    if pos is None:
                                        _debug_log(
                                            f"[ANALYZER DEBUG] Move adjacency missing position snapshot for unit_id: {uid} "
                                            f"(episode={current_episode_num}, turn={turn}, phase={phase})"
                                        )
                                        continue
                                    positions_for_adjacency_check_filtered[uid] = pos

                                positions_at_movement_filtered = {}
                                for uid, hp_value in unit_hp_at_movement.items():
                                    if hp_value <= 0:
                                        continue
                                    pos = positions_at_movement.get(uid)
                                    if pos is None:
                                        _debug_log(
                                            f"[ANALYZER DEBUG] Move adjacency (before) missing position snapshot for unit_id: {uid} "
                                            f"(episode={current_episode_num}, turn={turn}, phase={phase})"
                                        )
                                        continue
                                    positions_at_movement_filtered[uid] = pos
                                adjacent_before = get_adjacent_enemies(
                                    start_col,
                                    start_row,
                                    unit_player,
                                    positions_at_movement_filtered,
                                    unit_hp_at_movement,
                                    unit_types,
                                    player
                                )
                                if adjacent_before:
                                    stats['move_adjacent_before_non_flee'][player] += 1
                                    if stats['first_error_lines']['move_adjacent_before_non_flee'][player] is None:
                                        stats['first_error_lines']['move_adjacent_before_non_flee'][player] = {
                                            'episode': current_episode_num,
                                            'line': line.strip(),
                                            'adjacent_before': adjacent_before
                                        }
                                
                                # Check if destination is adjacent to enemy using positions at movement time
                                # Use unit_hp_at_movement (snapshot at movement time) instead of current unit_hp
                                # DEBUG: Log enemy positions used for adjacency check
                                # CRITICAL: Normalize player values to int for consistent comparison (handles int/string mismatches)
                                enemy_player = 3 - player
                                enemy_player_int = int(enemy_player) if enemy_player is not None else None
                                enemy_positions_str = ', '.join([f"Unit {uid} at {pos} (HP={require_key(unit_hp_at_movement, uid)})" for uid, pos in positions_for_adjacency_check_filtered.items() if (int(require_key(unit_player, uid)) if require_key(unit_player, uid) is not None else None) == enemy_player_int])
                                _debug_log(f"[ANALYZER DEBUG] E{current_episode_num} T{turn} MOVE: Unit {move_unit_id} checking adjacency at ({dest_col},{dest_row}) against {len(positions_for_adjacency_check_filtered)} enemy positions: {enemy_positions_str}")
                                dest_adjacent = is_adjacent_to_enemy(dest_col, dest_row, unit_player, positions_for_adjacency_check_filtered, unit_hp_at_movement, player)
                                
                                # Only report violation if unit was NOT adjacent before move (flee is allowed)
                                # If unit was already adjacent, moving to another adjacent hex is a flee (not a violation)
                                if dest_adjacent:
                                    # Only report violation if unit was NOT adjacent before move
                                    if not adjacent_before:
                                        stats['move_to_adjacent_enemy'][player] += 1
                                        if stats['first_error_lines']['move_to_adjacent_enemy'][player] is None:
                                            # Use positions_for_adjacency_check_filtered (after this unit moved) for "after" check
                                            # Use unit_hp_at_movement (snapshot at movement time) instead of current unit_hp
                                            adjacent_after = get_adjacent_enemies(dest_col, dest_row, unit_player, positions_for_adjacency_check_filtered, unit_hp_at_movement, unit_types, player)
                                            stats['first_error_lines']['move_to_adjacent_enemy'][player] = {
                                                'episode': current_episode_num, 
                                                'line': line.strip(),
                                                'adjacent_before': adjacent_before,
                                                'adjacent_after': adjacent_after
                                            }
                                
                                # RULE: Move into wall
                                if (dest_col, dest_row) in wall_hexes:
                                    stats['wall_collisions'][player] += 1
                            else:
                                # No movement - just update position if needed
                                # CRITICAL: Only update position if unit is still alive
                                # Dead units should not have their positions updated (they were removed when they died)
                                if require_key(unit_hp, move_unit_id) > 0:
                                    _position_cache_set(unit_positions, move_unit_id, dest_col, dest_row)
                            
                            # Sample action
                            if not stats['sample_actions']['move']:
                                stats['sample_actions']['move'] = line.strip()
                        else:
                            stats['parse_errors'].append({
                                'episode': current_episode_num,
                                'turn': turn,
                                'phase': phase,
                                'line': line.strip(),
                                'error': f"Move action missing 'from/to' format: {action_desc[:100]}"
                            })

                elif "ATTACKED Unit" in action_desc:
                        action_type = 'fight'
                        units_fought.add(unit_id) if 'unit_id' in locals() else None
                        
                        fight_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\) ATTACKED Unit (\d+)\((\d+),\s*(\d+)\)', action_desc)
                        if fight_match:
                            fighter_id = fight_match.group(1)
                            fighter_col = int(fight_match.group(2))
                            fighter_row = int(fight_match.group(3))
                            target_id = fight_match.group(4)
                            target_col = int(fight_match.group(5))
                            target_row = int(fight_match.group(6))
                            _track_action_phase_accuracy(stats, "fight", phase, current_episode_num, line)
                            attacker_player = require_key(unit_player, fighter_id)
                            fight_attacks_by_unit = require_key(stats, 'fight_attacks_by_unit')
                            fight_attacks_by_player = require_key(fight_attacks_by_unit, attacker_player)
                            fight_over_by_unit = require_key(stats, 'fight_over_cc_nb_by_unit')
                            fight_over_by_player = require_key(fight_over_by_unit, attacker_player)
                            if fighter_id not in fight_attacks_by_player:
                                fight_attacks_by_player[fighter_id] = 0
                            if fighter_id not in fight_over_by_player:
                                fight_over_by_player[fighter_id] = 0
                            fight_attacks_by_player[fighter_id] = fight_attacks_by_player[fighter_id] + 1
                            if fighter_id in charged_units_current_fight:
                                charged_units_fought.add(fighter_id)
                            else:
                                eligible_charged_units = []
                                for charged_id in charged_units_current_fight:
                                    if charged_id in charged_units_fought:
                                        continue
                                    if charged_id not in unit_positions:
                                        continue
                                    if charged_id not in unit_hp or require_key(unit_hp, charged_id) <= 0:
                                        continue
                                    charged_pos = unit_positions[charged_id]
                                    charged_player = require_key(unit_player, charged_id)
                                    if is_adjacent_to_enemy(charged_pos[0], charged_pos[1], unit_player, unit_positions, unit_hp, charged_player):
                                        eligible_charged_units.append(charged_id)
                                if eligible_charged_units:
                                    stats['fight_alternation_violations'][attacker_player] += 1
                                    if stats['first_error_lines']['fight_alternation_violations'][attacker_player] is None:
                                        stats['first_error_lines']['fight_alternation_violations'][attacker_player] = {
                                            'episode': current_episode_num,
                                            'line': line.strip(),
                                            'eligible_charged_units': eligible_charged_units
                                        }

                            weapon_match = re.search(r'with \[([^\]]+)\]', action_desc)
                            if weapon_match:
                                weapon_display_name = weapon_match.group(1).strip()
                                fighter_unit_type = require_key(unit_types, fighter_id)
                                if fighter_unit_type:
                                    limits = require_key(unit_attack_limits, fighter_unit_type)
                                    cc_nb_by_weapon = require_key(limits, "cc_nb_by_weapon")
                                    if weapon_display_name not in cc_nb_by_weapon:
                                        stats['parse_errors'].append({
                                            'episode': current_episode_num,
                                            'turn': turn,
                                            'phase': phase,
                                            'line': line.strip(),
                                            'error': f"Weapon '{weapon_display_name}' missing CC_NB for unit type {fighter_unit_type}"
                                        })
                                    else:
                                        cc_nb = cc_nb_by_weapon[weapon_display_name]
                                        seq_key = (fight_phase_seq_id, fighter_id, weapon_display_name)
                                        if (last_fight_fighter_id != fighter_id or
                                                last_fight_weapon != weapon_display_name):
                                            fight_sequence_counts[seq_key] = 0
                                        last_fight_fighter_id = fighter_id
                                        last_fight_weapon = weapon_display_name
                                        if seq_key not in fight_sequence_counts:
                                            fight_sequence_counts[seq_key] = 0
                                        elif step_marker_present and step_inc:
                                            fight_sequence_counts[seq_key] = 0
                                        fight_sequence_counts[seq_key] += 1
                                        if fight_sequence_counts[seq_key] > cc_nb:
                                            attacker_player = require_key(unit_player, fighter_id)
                                            stats['fight_over_cc_nb'][attacker_player] += 1
                                            fight_over_by_unit = require_key(stats, 'fight_over_cc_nb_by_unit')
                                            fight_over_by_player = require_key(fight_over_by_unit, attacker_player)
                                            if fighter_id not in fight_over_by_player:
                                                raise KeyError(f"Missing fight_over_cc_nb_by_unit for fighter_id={fighter_id}, player={attacker_player}")
                                            fight_over_by_player[fighter_id] = fight_over_by_player[fighter_id] + 1
                                            if stats['first_error_lines']['fight_over_cc_nb'][attacker_player] is None:
                                                stats['first_error_lines']['fight_over_cc_nb'][attacker_player] = {'episode': current_episode_num, 'line': line.strip()}
                            else:
                                stats['parse_errors'].append({
                                    'episode': current_episode_num,
                                    'turn': turn,
                                    'phase': phase,
                                    'line': line.strip(),
                                    'error': "Fight action missing weapon name for CC_NB check"
                                })
                            
                            # CRITICAL: Update position cache for target from log (source of truth at fight time)
                            if target_id in unit_hp and require_key(unit_hp, target_id) > 0:
                                _position_cache_set(unit_positions, target_id, target_col, target_row)
                            
                            # CRITICAL: Track damage and deaths in fight phase (same as shoot phase)
                            # This ensures dead units are properly removed from unit_hp and unit_positions
                            # Damage application is handled earlier (regardless of STEP marker).
                            
                            # RULE: Fight from non-adjacent
                            if not is_adjacent(fighter_col, fighter_row, target_col, target_row):
                                stats['fight_from_non_adjacent'][player] += 1
                                if stats['first_error_lines']['fight_from_non_adjacent'][player] is None:
                                    stats['first_error_lines']['fight_from_non_adjacent'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            
                            # RULE: Fight friendly
                            # CRITICAL: Compare target player with attacker player, not action player
                            # In alternating fight phase, a unit can attack during opponent's turn
                            if (target_id in unit_player and fighter_id in unit_player and 
                                unit_player[target_id] == unit_player[fighter_id]):
                                # Use attacker's player for stats tracking
                                attacker_player = unit_player[fighter_id]
                                stats['fight_friendly'][attacker_player] += 1
                                if stats['first_error_lines']['fight_friendly'][attacker_player] is None:
                                    stats['first_error_lines']['fight_friendly'][attacker_player] = {'episode': current_episode_num, 'line': line.strip()}
                            
                            # RULE: Dead unit Fighting (attacker is dead)
                            # CRITICAL: Check if attacker is dead, but filter false positives (unit dies AFTER fighting in same phase)
                            attacker_is_dead = fighter_id in unit_hp and require_key(unit_hp, fighter_id) <= 0
                            if attacker_is_dead:
                                # Check if this is a false positive: unit dies AFTER this fight action in same phase
                                is_false_positive = False
                                phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
                                current_phase_order = require_key(phase_order, phase)
                                
                                # Find when attacker died (if it did)
                                attacker_died_before_fight = False
                                for death_turn, death_phase, dead_unit_id, death_line_num in unit_deaths:
                                    if dead_unit_id == fighter_id:
                                        # Attacker died - check if it's BEFORE this fight action
                                        if death_turn < turn:
                                            attacker_died_before_fight = True
                                            break
                                        elif death_turn == turn:
                                            death_phase_order = require_key(phase_order, death_phase)
                                            if death_phase_order < current_phase_order:
                                                attacker_died_before_fight = True
                                                break
                                            elif death_phase_order == current_phase_order and death_line_num < line_number:
                                                attacker_died_before_fight = True
                                                break
                                
                                # Only report if attacker died before fight
                                if attacker_died_before_fight:
                                    attacker_player = require_key(unit_player, fighter_id)
                                    stats['fight_dead_unit_attacker'][attacker_player] += 1
                                    if stats['first_error_lines']['fight_dead_unit_attacker'][attacker_player] is None:
                                        stats['first_error_lines']['fight_dead_unit_attacker'][attacker_player] = {'episode': current_episode_num, 'line': line.strip()}
                            
                            # RULE: Fight a dead unit (target is dead)
                            # CRITICAL: Check if target is dead, but filter false positives (target dies AFTER being attacked in same phase)
                            target_is_dead = target_id not in unit_hp or require_key(unit_hp, target_id) <= 0
                            if target_is_dead:
                                # Verify this is a real bug (target died before fight, not after)
                                is_false_positive = False
                                phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
                                current_phase_order = require_key(phase_order, phase)
                                
                                # Find when target died (if it did)
                                target_died_before_fight = False
                                for death_turn, death_phase, dead_unit_id, death_line_num in unit_deaths:
                                    if dead_unit_id == target_id:
                                        # Target died - check if it's BEFORE this fight action
                                        if death_turn < turn:
                                            target_died_before_fight = True
                                            break
                                        elif death_turn == turn:
                                            death_phase_order = require_key(phase_order, death_phase)
                                            if death_phase_order < current_phase_order:
                                                target_died_before_fight = True
                                                break
                                            elif death_phase_order == current_phase_order and death_line_num < line_number:
                                                target_died_before_fight = True
                                                break
                                
                                # Only report if target died before fight
                                if target_died_before_fight:
                                    attacker_player = require_key(unit_player, fighter_id)
                                    stats['fight_dead_unit_target'][attacker_player] += 1
                                    if stats['first_error_lines']['fight_dead_unit_target'][attacker_player] is None:
                                        stats['first_error_lines']['fight_dead_unit_target'][attacker_player] = {'episode': current_episode_num, 'line': line.strip()}
                            
                            # Sample action
                            if not stats['sample_actions']['fight']:
                                stats['sample_actions']['fight'] = line.strip()
                        else:
                            stats['parse_errors'].append({
                                'episode': current_episode_num,
                                'turn': turn,
                                'phase': phase,
                                'line': line.strip(),
                                'error': f"Fight action missing expected format: {action_desc[:100]}"
                            })
                else:
                    action_type = 'other'

                if step_inc:
                    if not objective_hexes:
                        raise ValueError(
                            f"Objectives not parsed before step action in episode {current_episode_num}: "
                            f"{line.strip()[:200]}"
                        )
                    episode_step_index += 1
                    snapshot = _calculate_objective_control_snapshot(
                        objective_hexes,
                        objective_controllers,
                        unit_positions,
                        unit_player,
                        unit_types,
                        unit_registry,
                    )
                    stats['objective_control_history'][current_episode_num].append({
                        "step_index": episode_step_index,
                        "control": snapshot,
                    })
                    if not primary_objective_configs:
                        raise ValueError(
                            f"Primary objectives not loaded before step action in episode {current_episode_num}"
                        )
                    turn_player_key = (turn, player)
                    if turn >= 2 and turn_player_key not in seen_turn_player:
                        if turn == 5 and player == PLAYER_TWO_ID:
                            seen_turn_player.add(turn_player_key)
                        else:
                            if last_objective_snapshot is None:
                                raise ValueError(
                                    f"Missing objective control snapshot before scoring "
                                    f"(episode {current_episode_num}, turn {turn}, player {player})"
                                )
                            for cfg in primary_objective_configs:
                                objective_id = require_key(cfg, "id")
                                score_key = (objective_id, turn, player)
                                if score_key in scored_turns:
                                    continue
                                points = _calculate_primary_objective_points(
                                    last_objective_snapshot,
                                    cfg,
                                    player
                                )
                                episode_victory_points[player] += points
                                scored_turns.add(score_key)
                            seen_turn_player.add(turn_player_key)
                    last_objective_snapshot = snapshot

                stats['actions_by_type'][action_type] += 1
                stats['actions_by_player'][player][action_type] += 1

                current_episode.append(line.strip())
    
    # Check if last episode ended without EPISODE END
    if current_episode:
        stats['episodes_without_end'].append({
            'episode_num': current_episode_num,
            'actions': episode_actions,
            'turn': episode_turn,
            'last_line': current_episode[-1][:100] if current_episode else 'N/A'
        })
        
        stats['episode_lengths'].append((current_episode_num, episode_actions))
        # Save turn distribution for last episode
        if episode_turn > 0:
            stats['turns_distribution'][episode_turn] += 1

    # Close debug log file
    if _debug_log_file:
        _debug_log_file.close()
        _debug_log_file = None

    return stats


def parse_step_timings_from_debug(debug_log_path: str) -> Optional[List[Tuple[int, int, float, Optional[int]]]]:
    """
    LOG TEMPORAIRE: Parse STEP_TIMING lines from debug.log (only written when --debug).
    Returns list of (episode, step_index, duration_s, step_calls or None) or None if file missing.
    step_calls = number of step() calls between this step_increment and the previous.
    """
    if not os.path.isfile(debug_log_path):
        return None
    result: List[Tuple[int, int, float, Optional[int]]] = []
    # With optional step_calls= (LOG TEMPORAIRE)
    pattern = re.compile(r'STEP_TIMING episode=(\d+) step_index=(\d+) duration_s=([\d.]+)(?: step_calls=(\d+))?')
    try:
        with open(debug_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                m = pattern.search(line)
                if m:
                    step_calls = int(m.group(4)) if m.group(4) else None
                    result.append((int(m.group(1)), int(m.group(2)), float(m.group(3)), step_calls))
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


def print_statistics(stats: Dict, output_f=None, step_timings: Optional[List[Tuple[int, int, float, Optional[int]]]] = None, predict_timings: Optional[List[Tuple[int, int, float]]] = None, get_mask_timings: Optional[List[Tuple[int, int, float]]] = None, console_log_write_timings: Optional[List[Tuple[int, int, float, int]]] = None, cascade_timings: Optional[List[Tuple[int, int, str, str, float]]] = None, step_breakdowns: Optional[List[Tuple[int, int, float, float, float, float, float, float, float]]] = None, between_step_timings: Optional[List[Tuple[int, int, float]]] = None, reset_timings: Optional[List[Tuple[int, float]]] = None, post_step_timings: Optional[List[Tuple[int, int, float]]] = None, pre_step_timings: Optional[List[Tuple[int, int, float]]] = None, wrapper_step_timings: Optional[List[Tuple[int, int, float]]] = None, after_step_increment_timings: Optional[List[Tuple[int, int, float]]] = None, debug_section_filter: Optional[str] = None, output_lines: Optional[List[str]] = None, emit_console: bool = True):
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
        "2.1": "DEAD UNITS INTERACTIONS",
        "2.2": "POSITION / LOG COHERENCE",
        "2.3": "DMG ISSUES",
        "2.4": "EPISODES STATISTICS",
        "2.5": "EPISODES ENDING",
        "2.6": "SAMPLE MISSING",
        "2.7": "CORE ISSUES",
    }
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
        
        # Find min and max episodes (lengths is list of (episode_num, action_count) tuples)
        min_episode_num, min_length = min(lengths_list, key=lambda x: x[1])
        max_episode_num, max_length = max(lengths_list, key=lambda x: x[1])
        max_length_episode = max_episode_num
        avg_length = sum(action_count for _, action_count in lengths_list) / len(lengths_list)
        
        # Get durations for min/max episodes
        min_duration = require_key(durations_dict, min_episode_num)
        max_duration = require_key(durations_dict, max_episode_num)
        
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
        
        # Find min and max episodes (durations is list of (episode_num, duration) tuples)
        min_episode_num, min_duration = min(durations_list, key=lambda x: x[1])
        max_episode_num, max_duration = max(durations_list, key=lambda x: x[1])
        max_duration_episode = max_episode_num
        avg_duration = sum(duration for _, duration in durations_list) / len(durations_list)
        
        # Get action counts for min/max episodes
        min_actions = require_key(lengths_dict, min_episode_num)
        max_actions = require_key(lengths_dict, max_episode_num)
        
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
        # step_timings: (episode, step_index, duration_s, step_calls or None)
        by_index: Dict[int, List[float]] = defaultdict(list)
        for _ep, idx, dur, _sc in step_timings:
            by_index[idx].append(dur)
        all_durations = [d for _e, _i, d, _sc in step_timings]
        n_steps = len(all_durations)
        avg_all = sum(all_durations) / n_steps if n_steps else 0.0
        min_all = min(all_durations) if all_durations else 0.0
        max_all = max(all_durations) if all_durations else 0.0
        # Which (episode, step_index) has min/max duration (global over all steps)
        min_ep, min_idx, min_val, _ = min(step_timings, key=lambda t: t[2])
        max_ep, max_idx, max_val, max_sc = max(step_timings, key=lambda t: t[2])
        log_print(f"Step Durations (from debug.log): {avg_all:.3f}s (average), Min: {min_all:.3f}s, Max: {max_all:.3f}s (n={n_steps} steps)")
        log_print(f"  Min: {min_val:.3f}s (Episode {min_ep}, step index {min_idx})")
        max_line = f"  Max: {max_val:.3f}s (Episode {max_ep}, step index {max_idx})"
        if max_sc is not None:
            max_line += f", {max_sc} step() calls"
        log_print(max_line)
        # LOG TEMPORAIRE: step_calls stats when present (--debug)
        step_calls_list = [sc for _e, _i, _d, sc in step_timings if sc is not None]
        if step_calls_list:
            n_sc = len(step_calls_list)
            avg_sc = sum(step_calls_list) / n_sc
            max_step_calls = max(step_calls_list)
            log_print(f"  Step calls between step_increment: avg={avg_sc:.1f}, max={max_step_calls} (n={n_sc} with data)")
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
    log_print("\n" + "-" * 80)
    log_print("WIN METHODS")
    log_print("-" * 80)
    log_print(f"{'Method':<20} {'Agent Wins (P1)':>18} {'Bot Wins (P2)':>18}")
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
        log_print("\n" + "-" * 80)
        log_print("WINS BY SCENARIO")
        log_print("-" * 80)
        log_print(f"{'Scenario':<40} {'Agent (P1)':>15} {'Bot (P2)':>15} {'Draws':>10}")
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
    log_print("\n" + "-" * 80)
    log_print("ACTIONS BY TYPE")
    log_print("-" * 80)
    log_print(f"{'Action':<12} {'Agent (P1)':>18} {'Bot (P2)':>18}")
    log_print("-" * 80)
    
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
        log_print(f"{action_type:<12} {agent_count:6d} ({agent_pct:5.1f}%)   {bot_count:6d} ({bot_pct:5.1f}%)")
    
    # SHOOTING PHASE BEHAVIOR
    log_print("\n" + "-" * 80)
    log_print("SHOOTING PHASE BEHAVIOR")
    log_print("-" * 80)
    log_print(f"{'Action':<12} {'Agent (P1)':>18} {'Bot (P2)':>18}")
    log_print("-" * 80)
    
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
        log_print(f"{action.capitalize():<12} {agent_count:6d} ({agent_pct:5.1f}%)   {bot_count:6d} ({bot_pct:5.1f}%)")
    
    agent_wait_with = stats['shoot_vs_wait_by_player'][1]['wait_with_targets']
    bot_wait_with = stats['shoot_vs_wait_by_player'][2]['wait_with_targets']
    agent_wait_with_pct = (agent_wait_with / agent_shoot_total * 100) if agent_shoot_total > 0 else 0
    bot_wait_with_pct = (bot_wait_with / bot_shoot_total * 100) if bot_shoot_total > 0 else 0
    log_print(f"{'Wait (targets)':<12} {agent_wait_with:6d} ({agent_wait_with_pct:5.1f}%)   {bot_wait_with:6d} ({bot_wait_with_pct:5.1f}%)")
    
    agent_wait_no = stats['shoot_vs_wait_by_player'][1]['wait_no_targets']
    bot_wait_no = stats['shoot_vs_wait_by_player'][2]['wait_no_targets']
    agent_wait_no_pct = (agent_wait_no / agent_shoot_total * 100) if agent_shoot_total > 0 else 0
    bot_wait_no_pct = (bot_wait_no / bot_shoot_total * 100) if bot_shoot_total > 0 else 0
    log_print(f"{'Wait (no targets)':<12} {agent_wait_no:6d} ({agent_wait_no_pct:5.1f}%)   {bot_wait_no:6d} ({bot_wait_no_pct:5.1f}%)")
    
    agent_shots_after_advance = stats['shots_after_advance'][1]
    bot_shots_after_advance = stats['shots_after_advance'][2]
    agent_pct_after_advance = (agent_shots_after_advance / agent_shoot_total * 100) if agent_shoot_total > 0 else 0
    bot_pct_after_advance = (bot_shots_after_advance / bot_shoot_total * 100) if bot_shoot_total > 0 else 0
    log_print(f"{'Shoot+Advance':<12} {agent_shots_after_advance:6d} ({agent_pct_after_advance:5.1f}%)   {bot_shots_after_advance:6d} ({bot_pct_after_advance:5.1f}%)")
    
    # PISTOL WEAPON SHOTS
    log_print("\nDetails:")
    log_print("-" * 80)
    log_print("PISTOL WEAPON SHOTS BY ADJACENCY")
    log_print("-" * 80)
    log_print(f"{'':30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
    log_print("-" * 80)
    agent_pistol_adj = stats['pistol_shots'][1]['adjacent']
    bot_pistol_adj = stats['pistol_shots'][2]['adjacent']
    agent_pistol_not_adj = stats['pistol_shots'][1]['not_adjacent']
    bot_pistol_not_adj = stats['pistol_shots'][2]['not_adjacent']
    agent_pistol_total = agent_pistol_adj + agent_pistol_not_adj
    bot_pistol_total = bot_pistol_adj + bot_pistol_not_adj
    
    agent_pistol_adj_pct = (agent_pistol_adj / agent_pistol_total * 100) if agent_pistol_total > 0 else 0
    bot_pistol_adj_pct = (bot_pistol_adj / bot_pistol_total * 100) if bot_pistol_total > 0 else 0
    agent_pistol_not_adj_pct = (agent_pistol_not_adj / agent_pistol_total * 100) if agent_pistol_total > 0 else 0
    bot_pistol_not_adj_pct = (bot_pistol_not_adj / bot_pistol_total * 100) if bot_pistol_total > 0 else 0
    
    log_print(f"PISTOL shots (adjacent):       {agent_pistol_adj:6d} ({agent_pistol_adj_pct:5.1f}%)  {bot_pistol_adj:6d} ({bot_pistol_adj_pct:5.1f}%)")
    log_print(f"PISTOL shots (not adjacent):   {agent_pistol_not_adj:6d} ({agent_pistol_not_adj_pct:5.1f}%)  {bot_pistol_not_adj:6d} ({bot_pistol_not_adj_pct:5.1f}%)")
    log_print(f"Total PISTOL shots:            {agent_pistol_total:6d}           {bot_pistol_total:6d}")
    
    agent_non_pistol_adj = stats['non_pistol_adjacent_shots'][1]
    bot_non_pistol_adj = stats['non_pistol_adjacent_shots'][2]
    log_print(f"Non-PISTOL shots (adjacent):   {agent_non_pistol_adj:6d}           {bot_non_pistol_adj:6d}")

    log_print("\nDetails:")
    log_print("-" * 80)
    log_print("SHOOTING VALIDITY")
    log_print("-" * 80)
    log_print(f"{'':30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
    log_print("-" * 80)
    agent_invalid_total = (
        stats['shoot_invalid'][1]['no_los'] +
        stats['shoot_invalid'][1]['out_of_range'] +
        stats['shoot_invalid'][1]['adjacent_non_pistol']
    )
    bot_invalid_total = (
        stats['shoot_invalid'][2]['no_los'] +
        stats['shoot_invalid'][2]['out_of_range'] +
        stats['shoot_invalid'][2]['adjacent_non_pistol']
    )
    agent_shot_total = stats['shoot_invalid'][1]['total']
    bot_shot_total = stats['shoot_invalid'][2]['total']
    agent_invalid_pct = (agent_invalid_total / agent_shot_total * 100) if agent_shot_total > 0 else 0
    bot_invalid_pct = (bot_invalid_total / bot_shot_total * 100) if bot_shot_total > 0 else 0
    log_print(f"Invalid shots total:           {agent_invalid_total:6d} ({agent_invalid_pct:5.1f}%)  {bot_invalid_total:6d} ({bot_invalid_pct:5.1f}%)")
    log_print(f"No LoS:                        {stats['shoot_invalid'][1]['no_los']:6d}           {stats['shoot_invalid'][2]['no_los']:6d}")
    log_print(f"Out of range:                  {stats['shoot_invalid'][1]['out_of_range']:6d}           {stats['shoot_invalid'][2]['out_of_range']:6d}")
    log_print(f"Adjacent non-pistol:           {stats['shoot_invalid'][1]['adjacent_non_pistol']:6d}           {stats['shoot_invalid'][2]['adjacent_non_pistol']:6d}")
    if stats['first_error_lines']['shoot_invalid'][1]:
        first_err = stats['first_error_lines']['shoot_invalid'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['first_error_lines']['shoot_invalid'][2]:
        first_err = stats['first_error_lines']['shoot_invalid'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    
    # WAIT BEHAVIOR
    log_print("\n" + "-" * 80)
    log_print("WAIT BEHAVIOR BY PHASE")
    log_print("-" * 80)
    log_print(f"{'':30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
    log_print("-" * 80)
    agent_move_wait = stats['wait_by_phase'][1]['move_wait']
    bot_move_wait = stats['wait_by_phase'][2]['move_wait']
    agent_wait_los = stats['wait_by_phase'][1]['wait_with_los']
    bot_wait_los = stats['wait_by_phase'][2]['wait_with_los']
    agent_wait_no_los = stats['wait_by_phase'][1]['wait_no_los']
    bot_wait_no_los = stats['wait_by_phase'][2]['wait_no_los']
    
    log_print(f"MOVE phase waits:             {agent_move_wait:6d}           {bot_move_wait:6d}")
    log_print(f"SHOOT waits (enemies in LOS): {agent_wait_los:6d}           {bot_wait_los:6d}")
    log_print(f"SHOOT waits (no LOS):         {agent_wait_no_los:6d}           {bot_wait_no_los:6d}")
    
    # TARGET PRIORITY
    log_print("\n" + "-" * 80)
    log_print("TARGET PRIORITY ANALYSIS (Focus Fire)")
    log_print("-" * 80)
    log_print(f"{'':30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
    log_print("-" * 80)
    
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
    
    log_print(f"FAILURES (shot full HP while")
    log_print(f"  wounded in LOS):            {agent_bad:6d} ({agent_bad_pct:5.1f}%)  {bot_bad:6d} ({bot_bad_pct:5.1f}%)")
    log_print(f"SUCCESS (shot wounded or")
    log_print(f"  no wounded in LOS):         {agent_good:6d} ({agent_good_pct:5.1f}%)  {bot_good:6d} ({bot_good_pct:5.1f}%)")
    log_print(f"Total shots:                  {agent_total_shots:6d}           {bot_total_shots:6d}")
    
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
        log_print(f"{('1.1 ' + debug_sections['1.1']):<30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
        log_print("-" * 80)
        agent_walls = stats['wall_collisions'][1]
        bot_walls = stats['wall_collisions'][2]
        log_print(f"Moves into walls:             {agent_walls:6d}           {bot_walls:6d}")
        if agent_walls > 0 and stats['first_error_lines']['wall_collisions'][1]:
            first_err = stats['first_error_lines']['wall_collisions'][1]
            log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        if bot_walls > 0 and stats['first_error_lines']['wall_collisions'][2]:
            first_err = stats['first_error_lines']['wall_collisions'][2]
            log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        agent_move_adj = stats['move_to_adjacent_enemy'][1]
        bot_move_adj = stats['move_to_adjacent_enemy'][2]
        log_print(f"Moves to adjacent enemy:      {agent_move_adj:6d}           {bot_move_adj:6d}")
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
        log_print(f"Move with adjacent_before:   {agent_adj_before_move:6d}           {bot_adj_before_move:6d}")
        if agent_adj_before_move > 0 and stats['first_error_lines']['move_adjacent_before_non_flee'][1]:
            first_err = stats['first_error_lines']['move_adjacent_before_non_flee'][1]
            log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        if bot_adj_before_move > 0 and stats['first_error_lines']['move_adjacent_before_non_flee'][2]:
            first_err = stats['first_error_lines']['move_adjacent_before_non_flee'][2]
            log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        agent_move_over = stats['move_distance_over_limit']['move'][1]
        bot_move_over = stats['move_distance_over_limit']['move'][2]
        log_print(f"Move distance > MOVE:        {agent_move_over:6d}           {bot_move_over:6d}")
        if agent_move_over > 0 and stats['first_error_lines']['move_distance_over_limit']['move'][1]:
            first_err = stats['first_error_lines']['move_distance_over_limit']['move'][1]
            log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        if bot_move_over > 0 and stats['first_error_lines']['move_distance_over_limit']['move'][2]:
            first_err = stats['first_error_lines']['move_distance_over_limit']['move'][2]
            log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        agent_move_blocked = stats['move_path_blocked']['move'][1]
        bot_move_blocked = stats['move_path_blocked']['move'][2]
        log_print(f"Move path blocked (BFS):     {agent_move_blocked:6d}           {bot_move_blocked:6d}")
        if agent_move_blocked > 0 and stats['first_error_lines']['move_path_blocked']['move'][1]:
            first_err = stats['first_error_lines']['move_path_blocked']['move'][1]
            log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
        if bot_move_blocked > 0 and stats['first_error_lines']['move_path_blocked']['move'][2]:
            first_err = stats['first_error_lines']['move_path_blocked']['move'][2]
            log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    # SHOOTING ERRORS
    active_debug_section = "1.2"
    log_print("\n" + "-" * 80)
    log_print(f"{('1.2 ' + debug_sections['1.2']):<30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
    log_print("-" * 80)
    agent_shoot_invalid = (
        stats['shoot_invalid'][1]['no_los'] +
        stats['shoot_invalid'][1]['out_of_range'] +
        stats['shoot_invalid'][1]['adjacent_non_pistol']
    )
    bot_shoot_invalid = (
        stats['shoot_invalid'][2]['no_los'] +
        stats['shoot_invalid'][2]['out_of_range'] +
        stats['shoot_invalid'][2]['adjacent_non_pistol']
    )
    log_print("Tirs invalides")
    log_print(f"(LoS/portée/adjacent non-pistol): {agent_shoot_invalid:6d}           {bot_shoot_invalid:6d}")
    if agent_shoot_invalid > 0 and stats['first_error_lines']['shoot_invalid'][1]:
        first_err = stats['first_error_lines']['shoot_invalid'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_shoot_invalid > 0 and stats['first_error_lines']['shoot_invalid'][2]:
        first_err = stats['first_error_lines']['shoot_invalid'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_shoot_over_rng = stats['shoot_over_rng_nb'][1]
    bot_shoot_over_rng = stats['shoot_over_rng_nb'][2]
    log_print(f"Shots over RNG_NB:            {agent_shoot_over_rng:6d}           {bot_shoot_over_rng:6d}")
    if agent_shoot_over_rng > 0 and stats['first_error_lines']['shoot_over_rng_nb'][1]:
        first_err = stats['first_error_lines']['shoot_over_rng_nb'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_shoot_over_rng > 0 and stats['first_error_lines']['shoot_over_rng_nb'][2]:
        first_err = stats['first_error_lines']['shoot_over_rng_nb'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_shoot_combi = stats['shoot_combi_profile_conflicts'][1]
    bot_shoot_combi = stats['shoot_combi_profile_conflicts'][2]
    log_print(f"COMBI profiles in same phase: {agent_shoot_combi:6d}           {bot_shoot_combi:6d}")
    if agent_shoot_combi > 0 and stats['first_error_lines']['shoot_combi_profile_conflicts'][1]:
        first_err = stats['first_error_lines']['shoot_combi_profile_conflicts'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_shoot_combi > 0 and stats['first_error_lines']['shoot_combi_profile_conflicts'][2]:
        first_err = stats['first_error_lines']['shoot_combi_profile_conflicts'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_shoot_wall = stats['shoot_through_wall'][1]
    bot_shoot_wall = stats['shoot_through_wall'][2]
    log_print(f"Shoot through wall:           {agent_shoot_wall:6d}           {bot_shoot_wall:6d}")
    if agent_shoot_wall > 0 and stats['first_error_lines']['shoot_through_wall'][1]:
        first_err = stats['first_error_lines']['shoot_through_wall'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_shoot_wall > 0 and stats['first_error_lines']['shoot_through_wall'][2]:
        first_err = stats['first_error_lines']['shoot_through_wall'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_shoot_fled = stats['shoot_after_fled'][1]
    bot_shoot_fled = stats['shoot_after_fled'][2]
    log_print(f"Shoot after fled:             {agent_shoot_fled:6d}           {bot_shoot_fled:6d}")
    if agent_shoot_fled > 0 and stats['first_error_lines']['shoot_after_fled'][1]:
        first_err = stats['first_error_lines']['shoot_after_fled'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_shoot_fled > 0 and stats['first_error_lines']['shoot_after_fled'][2]:
        first_err = stats['first_error_lines']['shoot_after_fled'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_shoot_friendly = stats['shoot_at_friendly'][1]
    bot_shoot_friendly = stats['shoot_at_friendly'][2]
    log_print(f"Shoot at friendly unit:       {agent_shoot_friendly:6d}           {bot_shoot_friendly:6d}")
    if agent_shoot_friendly > 0 and stats['first_error_lines']['shoot_at_friendly'][1]:
        first_err = stats['first_error_lines']['shoot_at_friendly'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_shoot_friendly > 0 and stats['first_error_lines']['shoot_at_friendly'][2]:
        first_err = stats['first_error_lines']['shoot_at_friendly'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_shoot_engaged = stats['shoot_at_engaged_enemy'][1]
    bot_shoot_engaged = stats['shoot_at_engaged_enemy'][2]
    log_print(f"Shoot at engaged enemy:       {agent_shoot_engaged:6d}           {bot_shoot_engaged:6d}")
    if agent_shoot_engaged > 0 and stats['first_error_lines']['shoot_at_engaged_enemy'][1]:
        first_err = stats['first_error_lines']['shoot_at_engaged_enemy'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_shoot_engaged > 0 and stats['first_error_lines']['shoot_at_engaged_enemy'][2]:
        first_err = stats['first_error_lines']['shoot_at_engaged_enemy'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_non_pistol_adj = stats['non_pistol_adjacent_shots'][1]
    bot_non_pistol_adj = stats['non_pistol_adjacent_shots'][2]
    log_print(f"Non-pistol adjacent shots:   {agent_non_pistol_adj:6d}           {bot_non_pistol_adj:6d}")
    agent_advance_after_shoot = stats['advance_after_shoot'][1]
    bot_advance_after_shoot = stats['advance_after_shoot'][2]
    log_print(f"Advance after shoot:          {agent_advance_after_shoot:6d}           {bot_advance_after_shoot:6d}")
    if agent_advance_after_shoot > 0 and stats['first_error_lines']['advance_after_shoot'][1]:
        first_err = stats['first_error_lines']['advance_after_shoot'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_advance_after_shoot > 0 and stats['first_error_lines']['advance_after_shoot'][2]:
        first_err = stats['first_error_lines']['advance_after_shoot'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_adv_over = stats['move_distance_over_limit']['advance'][1]
    bot_adv_over = stats['move_distance_over_limit']['advance'][2]
    log_print(f"Advance distance > roll:     {agent_adv_over:6d}           {bot_adv_over:6d}")
    if agent_adv_over > 0 and stats['first_error_lines']['move_distance_over_limit']['advance'][1]:
        first_err = stats['first_error_lines']['move_distance_over_limit']['advance'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_adv_over > 0 and stats['first_error_lines']['move_distance_over_limit']['advance'][2]:
        first_err = stats['first_error_lines']['move_distance_over_limit']['advance'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_advance_adj = stats['advance_from_adjacent'][1]
    bot_advance_adj = stats['advance_from_adjacent'][2]
    log_print(f"Advances from adjacent hex:   {agent_advance_adj:6d}           {bot_advance_adj:6d}")
    if agent_advance_adj > 0 and stats['first_error_lines']['advance_from_adjacent'][1]:
        first_err = stats['first_error_lines']['advance_from_adjacent'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_advance_adj > 0 and stats['first_error_lines']['advance_from_adjacent'][2]:
        first_err = stats['first_error_lines']['advance_from_adjacent'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_adv_blocked = stats['move_path_blocked']['advance'][1]
    bot_adv_blocked = stats['move_path_blocked']['advance'][2]
    log_print(f"Advance path blocked (BFS):  {agent_adv_blocked:6d}           {bot_adv_blocked:6d}")
    if agent_adv_blocked > 0 and stats['first_error_lines']['move_path_blocked']['advance'][1]:
        first_err = stats['first_error_lines']['move_path_blocked']['advance'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_adv_blocked > 0 and stats['first_error_lines']['move_path_blocked']['advance'][2]:
        first_err = stats['first_error_lines']['move_path_blocked']['advance'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    
    # CHARGE ERRORS
    active_debug_section = "1.3"
    log_print("\n" + "-" * 80)
    log_print(f"{('1.3 ' + debug_sections['1.3']):<30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
    log_print("-" * 80)
    agent_charge_adj = stats['charge_from_adjacent'][1]
    bot_charge_adj = stats['charge_from_adjacent'][2]
    log_print(f"Charges from adjacent hex:     {agent_charge_adj:6d}           {bot_charge_adj:6d}")
    if agent_charge_adj > 0 and stats['first_error_lines']['charge_from_adjacent'][1]:
        first_err = stats['first_error_lines']['charge_from_adjacent'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_charge_adj > 0 and stats['first_error_lines']['charge_from_adjacent'][2]:
        first_err = stats['first_error_lines']['charge_from_adjacent'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_charge_fled = stats['charge_invalid'][1]['fled']
    bot_charge_fled = stats['charge_invalid'][2]['fled']
    log_print(f"Charges after fled:           {agent_charge_fled:6d}           {bot_charge_fled:6d}")
    agent_charge_adv_used = stats['charge_after_advance_used'][1]
    bot_charge_adv_used = stats['charge_after_advance_used'][2]
    log_print(f"Charge after advance (rule):  {agent_charge_adv_used:6d}           {bot_charge_adv_used:6d}")
    agent_charge_adv = stats['charge_invalid'][1]['advanced']
    bot_charge_adv = stats['charge_invalid'][2]['advanced']
    log_print(f"Charges after advance:        {agent_charge_adv:6d}           {bot_charge_adv:6d}")
    agent_charge_over = stats['charge_invalid'][1]['distance_over_roll']
    bot_charge_over = stats['charge_invalid'][2]['distance_over_roll']
    log_print(f"Distance > roll:              {agent_charge_over:6d}           {bot_charge_over:6d}")
    if stats['first_error_lines']['charge_invalid'][1]:
        first_err = stats['first_error_lines']['charge_invalid'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['first_error_lines']['charge_invalid'][2]:
        first_err = stats['first_error_lines']['charge_invalid'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")

    # FIGHT ERRORS
    active_debug_section = "1.4"
    log_print("\n" + "-" * 80)
    log_print(f"{('1.4 ' + debug_sections['1.4']):<30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
    log_print("-" * 80)
    agent_fight_non_adj = stats['fight_from_non_adjacent'][1]
    bot_fight_non_adj = stats['fight_from_non_adjacent'][2]
    log_print(f"Fight from non-adjacent hex:  {agent_fight_non_adj:6d}           {bot_fight_non_adj:6d}")
    if agent_fight_non_adj > 0 and stats['first_error_lines']['fight_from_non_adjacent'][1]:
        first_err = stats['first_error_lines']['fight_from_non_adjacent'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_fight_non_adj > 0 and stats['first_error_lines']['fight_from_non_adjacent'][2]:
        first_err = stats['first_error_lines']['fight_from_non_adjacent'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_fight_friendly = stats['fight_friendly'][1]
    bot_fight_friendly = stats['fight_friendly'][2]
    log_print(f"Fight a friendly unit:        {agent_fight_friendly:6d}           {bot_fight_friendly:6d}")
    if agent_fight_friendly > 0 and stats['first_error_lines']['fight_friendly'][1]:
        first_err = stats['first_error_lines']['fight_friendly'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_fight_friendly > 0 and stats['first_error_lines']['fight_friendly'][2]:
        first_err = stats['first_error_lines']['fight_friendly'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_fight_over_cc = stats['fight_over_cc_nb'][1]
    bot_fight_over_cc = stats['fight_over_cc_nb'][2]
    log_print(f"Attacks over CC_NB:           {agent_fight_over_cc:6d}           {bot_fight_over_cc:6d}")
    if agent_fight_over_cc > 0 and stats['first_error_lines']['fight_over_cc_nb'][1]:
        first_err = stats['first_error_lines']['fight_over_cc_nb'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_fight_over_cc > 0 and stats['first_error_lines']['fight_over_cc_nb'][2]:
        first_err = stats['first_error_lines']['fight_over_cc_nb'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_fight_alt = stats['fight_alternation_violations'][1]
    bot_fight_alt = stats['fight_alternation_violations'][2]
    log_print(f"Fight alternation violations: {agent_fight_alt:6d}           {bot_fight_alt:6d}")
    if agent_fight_alt > 0 and stats['first_error_lines']['fight_alternation_violations'][1]:
        first_err = stats['first_error_lines']['fight_alternation_violations'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_fight_alt > 0 and stats['first_error_lines']['fight_alternation_violations'][2]:
        first_err = stats['first_error_lines']['fight_alternation_violations'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")

    
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
        if winner == 1:
            without_method_p1 += 1
        elif winner == 2:
            without_method_p2 += 1
        else:
            without_method_unknown += 1

    # DEAD UNITS INTERACTIONS
    active_debug_section = "2.1"
    log_print("\n" + "-" * 80)
    log_print(f"{('2.1 ' + debug_sections['2.1']):<30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
    log_print("-" * 80)
    log_print(f"Incomplete episodes:         {incomplete_p1:6d}           {incomplete_p2:6d}")
    log_print(f"Dead unit moving:            {stats['dead_unit_moving'][1]:6d}           {stats['dead_unit_moving'][2]:6d}")
    if stats['dead_unit_moving'][1] > 0 and stats['first_error_lines']['dead_unit_moving'][1]:
        first_err = stats['first_error_lines']['dead_unit_moving'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['dead_unit_moving'][2] > 0 and stats['first_error_lines']['dead_unit_moving'][2]:
        first_err = stats['first_error_lines']['dead_unit_moving'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    log_print(f"Dead unit shooting:          {stats['shoot_dead_unit'][1]:6d}           {stats['shoot_dead_unit'][2]:6d}")
    if stats['shoot_dead_unit'][1] > 0 and stats['first_error_lines']['shoot_dead_unit'][1]:
        first_err = stats['first_error_lines']['shoot_dead_unit'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['shoot_dead_unit'][2] > 0 and stats['first_error_lines']['shoot_dead_unit'][2]:
        first_err = stats['first_error_lines']['shoot_dead_unit'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    log_print(f"Shoot at dead unit:          {stats['shoot_at_dead_unit'][1]:6d}           {stats['shoot_at_dead_unit'][2]:6d}")
    if stats['shoot_at_dead_unit'][1] > 0 and stats['first_error_lines']['shoot_at_dead_unit'][1]:
        first_err = stats['first_error_lines']['shoot_at_dead_unit'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['shoot_at_dead_unit'][2] > 0 and stats['first_error_lines']['shoot_at_dead_unit'][2]:
        first_err = stats['first_error_lines']['shoot_at_dead_unit'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    log_print(f"Dead unit advancing:         {stats['dead_unit_advancing'][1]:6d}           {stats['dead_unit_advancing'][2]:6d}")
    if stats['dead_unit_advancing'][1] > 0 and stats['first_error_lines']['dead_unit_advancing'][1]:
        first_err = stats['first_error_lines']['dead_unit_advancing'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['dead_unit_advancing'][2] > 0 and stats['first_error_lines']['dead_unit_advancing'][2]:
        first_err = stats['first_error_lines']['dead_unit_advancing'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    log_print(f"Dead unit charging:          {stats['dead_unit_charging'][1]:6d}           {stats['dead_unit_charging'][2]:6d}")
    if stats['dead_unit_charging'][1] > 0 and stats['first_error_lines']['dead_unit_charging'][1]:
        first_err = stats['first_error_lines']['dead_unit_charging'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['dead_unit_charging'][2] > 0 and stats['first_error_lines']['dead_unit_charging'][2]:
        first_err = stats['first_error_lines']['dead_unit_charging'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    log_print(f"Charge a dead unit:           {stats['charge_dead_unit'][1]:6d}           {stats['charge_dead_unit'][2]:6d}")
    if stats['charge_dead_unit'][1] > 0 and stats['first_error_lines']['charge_dead_unit'][1]:
        first_err = stats['first_error_lines']['charge_dead_unit'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['charge_dead_unit'][2] > 0 and stats['first_error_lines']['charge_dead_unit'][2]:
        first_err = stats['first_error_lines']['charge_dead_unit'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    log_print(f"Dead unit fighting:           {stats['fight_dead_unit_attacker'][1]:6d}           {stats['fight_dead_unit_attacker'][2]:6d}")
    if stats['fight_dead_unit_attacker'][1] > 0 and stats['first_error_lines']['fight_dead_unit_attacker'][1]:
        first_err = stats['first_error_lines']['fight_dead_unit_attacker'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['fight_dead_unit_attacker'][2] > 0 and stats['first_error_lines']['fight_dead_unit_attacker'][2]:
        first_err = stats['first_error_lines']['fight_dead_unit_attacker'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    log_print(f"Fight a dead unit:            {stats['fight_dead_unit_target'][1]:6d}           {stats['fight_dead_unit_target'][2]:6d}")
    if stats['fight_dead_unit_target'][1] > 0 and stats['first_error_lines']['fight_dead_unit_target'][1]:
        first_err = stats['first_error_lines']['fight_dead_unit_target'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['fight_dead_unit_target'][2] > 0 and stats['first_error_lines']['fight_dead_unit_target'][2]:
        first_err = stats['first_error_lines']['fight_dead_unit_target'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    log_print(f"Dead unit waiting:           {stats['dead_unit_waiting'][1]:6d}           {stats['dead_unit_waiting'][2]:6d}")
    if stats['dead_unit_waiting'][1] > 0 and stats['first_error_lines']['dead_unit_waiting'][1]:
        first_err = stats['first_error_lines']['dead_unit_waiting'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['dead_unit_waiting'][2] > 0 and stats['first_error_lines']['dead_unit_waiting'][2]:
        first_err = stats['first_error_lines']['dead_unit_waiting'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    log_print(f"Dead unit skipping:          {stats['dead_unit_skipping'][1]:6d}           {stats['dead_unit_skipping'][2]:6d}")
    if stats['dead_unit_skipping'][1] > 0 and stats['first_error_lines']['dead_unit_skipping'][1]:
        first_err = stats['first_error_lines']['dead_unit_skipping'][1]
        log_print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if stats['dead_unit_skipping'][2] > 0 and stats['first_error_lines']['dead_unit_skipping'][2]:
        first_err = stats['first_error_lines']['dead_unit_skipping'][2]
        log_print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    log_print(f"Unités revenues après mort:  {stats['unit_revived'][1]:6d}           {stats['unit_revived'][2]:6d}")
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
        pct = (mismatch / total * 100.0) if total > 0 else 0.0
        log_print(
            f"{action_key.upper():8s} total={total:6d} mismatch={mismatch:6d} "
            f"missing={missing:6d} mismatch_pct={pct:6.2f}%"
        )
    log_print("---")
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

    move_errors = (
        stats['wall_collisions'][1] + stats['wall_collisions'][2] +
        stats['move_to_adjacent_enemy'][1] + stats['move_to_adjacent_enemy'][2] +
        stats['move_adjacent_before_non_flee'][1] + stats['move_adjacent_before_non_flee'][2] +
        stats['move_distance_over_limit']['move'][1] + stats['move_distance_over_limit']['move'][2] +
        stats['move_path_blocked']['move'][1] + stats['move_path_blocked']['move'][2]
    )
    shoot_invalid_total = (
        stats['shoot_invalid'][1]['no_los'] + stats['shoot_invalid'][1]['out_of_range'] + stats['shoot_invalid'][1]['adjacent_non_pistol'] +
        stats['shoot_invalid'][2]['no_los'] + stats['shoot_invalid'][2]['out_of_range'] + stats['shoot_invalid'][2]['adjacent_non_pistol']
    )
    shooting_errors = (
        stats['shoot_over_rng_nb'][1] + stats['shoot_over_rng_nb'][2] +
        stats['shoot_combi_profile_conflicts'][1] + stats['shoot_combi_profile_conflicts'][2] +
        stats['shoot_through_wall'][1] + stats['shoot_through_wall'][2] +
        stats['shoot_after_fled'][1] + stats['shoot_after_fled'][2] +
        stats['shoot_at_friendly'][1] + stats['shoot_at_friendly'][2] +
        stats['shoot_at_engaged_enemy'][1] + stats['shoot_at_engaged_enemy'][2] +
        stats['advance_after_shoot'][1] + stats['advance_after_shoot'][2] +
        stats['move_distance_over_limit']['advance'][1] + stats['move_distance_over_limit']['advance'][2] +
        stats['advance_from_adjacent'][1] + stats['advance_from_adjacent'][2] +
        stats['move_path_blocked']['advance'][1] + stats['move_path_blocked']['advance'][2] +
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
    def summary_icon(is_warning: bool) -> str:
        return "⚠️ " if is_warning else "✅"

    long_episode_warn = (max_duration is not None and avg_duration is not None and max_duration > avg_duration * 3)
    actions_episode_warn = (max_length is not None and avg_length is not None and max_length > avg_length * 3)
    log_print("-" * 80)
    log_print("PHASES")
    log_print("-" * 80)
    log_print(f"{summary_icon(move_errors > 0)} 1.1 Erreurs en phase de move : {move_errors}")
    log_print(f"{summary_icon(shooting_errors > 0)} 1.2 Erreurs en phase de shooting : {shooting_errors}")
    log_print(f"{summary_icon(charge_errors > 0)} 1.3 Erreurs en phase de charge : {charge_errors}")
    log_print(f"{summary_icon(fight_errors > 0)} 1.4 Erreurs en phase de fight : {fight_errors}")
    action_phase_accuracy = require_key(stats, "action_phase_accuracy")
    wrong_phase_total = sum(require_key(action_phase_accuracy[key], "wrong") for key in action_phase_accuracy)
    log_print(f"{summary_icon(wrong_phase_total > 0)} 1.5 Actions occuring in the wrong phase : {wrong_phase_total}")
    double_activation_by_phase = require_key(stats, "double_activation_by_phase")
    double_activation_total = sum(double_activation_by_phase.values())
    log_print(f"{summary_icon(double_activation_total > 0)} 1.6 Double-activation par phase : {double_activation_total}")
    dmg_issues_total = (
        stats['damage_missing_unit_hp'][1] + stats['damage_missing_unit_hp'][2] +
        stats['damage_exceeds_hp'][1] + stats['damage_exceeds_hp'][2]
    )
    core_issues_total = len(stats['parse_errors']) + len(stats['unit_id_mismatches'])
    log_print("-" * 80)
    log_print("INTEGRITY")
    log_print("-" * 80)
    log_print(f"{summary_icon(dead_unit_interactions_total > 0)} 2.1 Dead units interactions : {dead_unit_interactions_total}")
    log_print(f"{summary_icon(pos_mismatch_total > 0)} 2.2 Positions/logs incohérents : {pos_mismatch_total}")
    log_print(f"{summary_icon(dmg_issues_total > 0)} 2.3 DMG issues : {dmg_issues_total}")
    if max_duration_episode is not None and avg_duration is not None:
        durations_list = require_key(stats, 'episode_durations')
        min_duration_episode, min_duration = min(durations_list, key=lambda x: x[1])
        log_print(f"{summary_icon(long_episode_warn)} 2.4 Episodes duration : Min: {min_duration:.2f}s (E{min_duration_episode}) - Avg: {avg_duration:.2f}s - Max: {max_duration:.2f}s (E{max_duration_episode})")
    else:
        log_print(f"{summary_icon(False)} 2.4 Episodes duration : N/A")
    if max_length_episode is not None and avg_length is not None:
        lengths_list = require_key(stats, 'episode_lengths')
        min_length_episode, min_length = min(lengths_list, key=lambda x: x[1])
        log_print(f"{summary_icon(actions_episode_warn)} 2.41 Episodes actions : Min: {min_length} (E{min_length_episode}) - Avg: {avg_length:.1f} - Max: {max_length} (E{max_length_episode})")
    else:
        log_print(f"{summary_icon(False)} 2.41 Episodes actions : N/A")
    episodes_ending_total = len(stats['episodes_without_end']) + len(stats['episodes_without_method'])
    log_print(f"{summary_icon(episodes_ending_total > 0)} 2.5 Episode ending : {episodes_ending_total}")
    log_print(f"{summary_icon(len(missing_samples) > 0)} 2.6 Sample missing ({len(missing_samples)}/{len(sample_action_types)}) : {missing_samples_label}")
    log_print(f"{summary_icon(core_issues_total > 0)} 2.7 Core issue : {core_issues_total}")

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
            stats['shoot_invalid'][1]['no_los'] + stats['shoot_invalid'][1]['out_of_range'] + stats['shoot_invalid'][1]['adjacent_non_pistol'] +
            stats['shoot_invalid'][2]['no_los'] + stats['shoot_invalid'][2]['out_of_range'] + stats['shoot_invalid'][2]['adjacent_non_pistol']
        )
        move_errors = (
            stats['wall_collisions'][1] + stats['wall_collisions'][2] +
            stats['move_to_adjacent_enemy'][1] + stats['move_to_adjacent_enemy'][2] +
            stats['move_adjacent_before_non_flee'][1] + stats['move_adjacent_before_non_flee'][2] +
            stats['move_distance_over_limit']['move'][1] + stats['move_distance_over_limit']['move'][2] +
            stats['move_path_blocked']['move'][1] + stats['move_path_blocked']['move'][2]
        )
        shooting_errors = (
            stats['shoot_over_rng_nb'][1] + stats['shoot_over_rng_nb'][2] +
            stats['shoot_through_wall'][1] + stats['shoot_through_wall'][2] +
            stats['shoot_after_fled'][1] + stats['shoot_after_fled'][2] +
            stats['shoot_at_friendly'][1] + stats['shoot_at_friendly'][2] +
            stats['shoot_at_engaged_enemy'][1] + stats['shoot_at_engaged_enemy'][2] +
            stats['advance_after_shoot'][1] + stats['advance_after_shoot'][2] +
            stats['move_distance_over_limit']['advance'][1] + stats['move_distance_over_limit']['advance'][2] +
            stats['advance_from_adjacent'][1] + stats['advance_from_adjacent'][2] +
            stats['move_path_blocked']['advance'][1] + stats['move_path_blocked']['advance'][2] +
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
            len(missing_samples)
        )

        status_line = (
            f"⚠️  {total_errors} erreur(s) détectée(s)   -   Output : {output_file}"
            if total_errors > 0
            else f"✅ Aucune erreur détectée   -   Output : {output_file}"
        )

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

        if total_errors > 0:
            _print_section_lines([f"⚠️  {total_errors} erreur(s) détectée(s)   -   Output : {output_file}"])
        else:
            _print_section_lines([f"✅ Aucune erreur détectée   -   Output : {output_file}"])

    except Exception as e:
        log_print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        output_f.close()