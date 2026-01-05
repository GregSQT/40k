#!/usr/bin/env python3
"""
Validate training logs for game rule compliance.

Checks:
1. All moves respect walls (pathfinding validation)
2. All shots are to units actually in LoS
3. Units not shooting - verify if they actually have LoS or not

Usage:
    python check/validate_train_log.py [train_step.log]
"""

import json
import os
import re
import sys
from collections import namedtuple
from typing import Dict, List, Set, Tuple, Any

# ============================================================================
# HEX COORDINATE UTILITIES (from shooting_handlers.py)
# ============================================================================

CubeCoordinate = namedtuple('CubeCoordinate', ['x', 'y', 'z'])


def _offset_to_cube(col: int, row: int) -> CubeCoordinate:
    """Convert offset coordinates to cube coordinates."""
    x = col
    z = row - ((col - (col & 1)) >> 1)
    y = -x - z
    return CubeCoordinate(x, y, z)


def _cube_to_offset(cube: CubeCoordinate) -> Tuple[int, int]:
    """Convert cube coordinates back to offset."""
    col = cube.x
    row = cube.z + ((cube.x - (cube.x & 1)) >> 1)
    return (col, row)


def _cube_round(x: float, y: float, z: float) -> CubeCoordinate:
    """Round fractional cube coordinates to nearest hex."""
    rx = round(x)
    ry = round(y)
    rz = round(z)

    x_diff = abs(rx - x)
    y_diff = abs(ry - y)
    z_diff = abs(rz - z)

    if x_diff > y_diff and x_diff > z_diff:
        rx = -ry - rz
    elif y_diff > z_diff:
        ry = -rx - rz
    else:
        rz = -rx - ry

    return CubeCoordinate(rx, ry, rz)


def get_hex_line(start_col: int, start_row: int, end_col: int, end_row: int) -> List[Tuple[int, int]]:
    """Accurate hex line using cube coordinates."""
    start_cube = _offset_to_cube(start_col, start_row)
    end_cube = _offset_to_cube(end_col, end_row)

    distance = max(abs(start_cube.x - end_cube.x), abs(start_cube.y - end_cube.y), abs(start_cube.z - end_cube.z))
    path = []

    for i in range(distance + 1):
        t = i / distance if distance > 0 else 0

        cube_x = start_cube.x + t * (end_cube.x - start_cube.x)
        cube_y = start_cube.y + t * (end_cube.y - start_cube.y)
        cube_z = start_cube.z + t * (end_cube.z - start_cube.z)

        rounded_cube = _cube_round(cube_x, cube_y, cube_z)
        offset_col, offset_row = _cube_to_offset(rounded_cube)
        path.append((offset_col, offset_row))

    return path


def get_hex_neighbors(col: int, row: int) -> List[Tuple[int, int]]:
    """
    Get all 6 hex neighbors using odd-q layout (same as engine).

    CRITICAL FIX: Changed from odd-r to odd-q layout to match engine.
    This was causing 43.8% false positives - validator used row parity,
    engine uses column parity.
    """
    # Offset coordinate neighbors (odd-q layout - based on column parity)
    parity = col & 1  # 0 for even, 1 for odd

    if parity == 0:  # Even column
        neighbors = [
            (col, row - 1),      # N
            (col + 1, row - 1),  # NE
            (col + 1, row),      # SE
            (col, row + 1),      # S
            (col - 1, row),      # SW
            (col - 1, row - 1)   # NW
        ]
    else:  # Odd column
        neighbors = [
            (col, row - 1),      # N
            (col + 1, row),      # NE
            (col + 1, row + 1),  # SE
            (col, row + 1),      # S
            (col - 1, row + 1),  # SW
            (col - 1, row)       # NW
        ]
    return neighbors


def calculate_hex_distance(col1: int, row1: int, col2: int, row2: int) -> int:
    """Calculate proper hex distance using cube coordinates."""
    x1 = col1
    z1 = row1 - ((col1 - (col1 & 1)) >> 1)
    y1 = -x1 - z1

    x2 = col2
    z2 = row2 - ((col2 - (col2 & 1)) >> 1)
    y2 = -x2 - z2

    return max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))


# ============================================================================
# LINE OF SIGHT VALIDATION
# ============================================================================

def has_line_of_sight(start_col: int, start_row: int, end_col: int, end_row: int, wall_hexes: Set[Tuple[int, int]]) -> bool:
    """Check if there is clear line of sight between two hexes."""
    hex_path = get_hex_line(start_col, start_row, end_col, end_row)

    # Check if any hex in path is a wall (excluding start and end)
    for i, (col, row) in enumerate(hex_path):
        # Skip start and end hexes
        if i == 0 or i == len(hex_path) - 1:
            continue

        if (col, row) in wall_hexes:
            return False

    return True


# ============================================================================
# PATHFINDING VALIDATION (BFS)
# ============================================================================

def is_reachable(start_col: int, start_row: int, end_col: int, end_row: int,
                 move_range: int, wall_hexes: Set[Tuple[int, int]],
                 occupied_hexes: Set[Tuple[int, int]], board_size: Tuple[int, int],
                 enemy_positions: Set[Tuple[int, int]] = None) -> bool:
    """
    Check if end position is reachable from start using BFS pathfinding.

    CRITICAL: Cannot move THROUGH or TO hexes adjacent to enemies (AI_TURN.md).

    Args:
        start_col, start_row: Starting position
        end_col, end_row: Target position
        move_range: Movement range
        wall_hexes: Set of wall positions
        occupied_hexes: Set of occupied positions (excluding start)
        board_size: (cols, rows)
        enemy_positions: Set of enemy unit positions (for adjacency check)

    Returns:
        True if reachable, False otherwise
    """
    start_pos = (start_col, start_row)
    end_pos = (end_col, end_row)

    if start_pos == end_pos:
        return True  # Already at destination

    cols, rows = board_size

    # Default enemy_positions to empty set if not provided (backward compatibility)
    if enemy_positions is None:
        enemy_positions = set()

    # Helper: Check if hex is adjacent to any enemy
    def is_adjacent_to_enemy(col: int, row: int) -> bool:
        hex_neighbors = set(get_hex_neighbors(col, row))
        return bool(hex_neighbors & enemy_positions)

    # BFS pathfinding
    visited = {start_pos}
    queue = [(start_pos, 0)]  # [(position, distance)]

    while queue:
        current_pos, current_dist = queue.pop(0)
        current_col, current_row = current_pos

        # If we've reached max movement, don't explore further
        if current_dist >= move_range:
            continue

        # Explore all 6 hex neighbors
        neighbors = get_hex_neighbors(current_col, current_row)

        for neighbor_col, neighbor_row in neighbors:
            neighbor_pos = (neighbor_col, neighbor_row)

            # Skip if already visited
            if neighbor_pos in visited:
                continue

            # Check board boundaries
            if neighbor_col < 0 or neighbor_col >= cols or neighbor_row < 0 or neighbor_row >= rows:
                continue

            # Check if traversable (not wall, not occupied)
            if neighbor_pos in wall_hexes:
                continue
            if neighbor_pos in occupied_hexes and neighbor_pos != end_pos:
                continue

            # Mark as visited
            visited.add(neighbor_pos)

            # Found the destination!
            if neighbor_pos == end_pos:
                # BUT: Cannot move TO hexes adjacent to enemies (AI_TURN.md)
                if is_adjacent_to_enemy(neighbor_col, neighbor_row):
                    return False  # Destination is adjacent to enemy - INVALID
                return True  # Valid destination found

            # CRITICAL FIX: Cannot move THROUGH hexes adjacent to enemies
            # Only add to queue if NOT adjacent to enemy (matches engine logic)
            if not is_adjacent_to_enemy(neighbor_col, neighbor_row):
                queue.append((neighbor_pos, current_dist + 1))

    return False


# ============================================================================
# LOG PARSING
# ============================================================================

def parse_move_action(line: str) -> Dict[str, Any]:
    """
    Parse movement line.
    Example: [01:55:52] T1 P0 MOVE : Unit 1(3, 9) MOVED from (9, 12) to (3, 9) [SUCCESS] [STEP: YES]
    """
    match = re.search(r'Unit (\d+)\((\d+), (\d+)\) MOVED from \((\d+), (\d+)\) to \((\d+), (\d+)\)', line)
    if match:
        unit_id = int(match.group(1))
        # end_col, end_row = int(match.group(2)), int(match.group(3))  # Same as to_col, to_row
        from_col, from_row = int(match.group(4)), int(match.group(5))
        to_col, to_row = int(match.group(6)), int(match.group(7))

        return {
            'type': 'move',
            'unit_id': unit_id,
            'from': (from_col, from_row),
            'to': (to_col, to_row),
            'line': line
        }
    return None


def parse_shoot_action(line: str) -> Dict[str, Any]:
    """
    Parse shooting line.
    Example: [01:55:52] T1 P0 SHOOT : Unit 4(9, 9) SHOT at unit 5 - Hit:3+:6(HIT) ...
    """
    match = re.search(r'Unit (\d+)\((\d+), (\d+)\) SHOT at unit (\d+)', line)
    if match:
        shooter_id = int(match.group(1))
        shooter_col, shooter_row = int(match.group(2)), int(match.group(3))
        target_id = int(match.group(4))

        return {
            'type': 'shoot',
            'shooter_id': shooter_id,
            'shooter_pos': (shooter_col, shooter_row),
            'target_id': target_id,
            'line': line
        }
    return None


def parse_shoot_wait(line: str) -> Dict[str, Any]:
    """
    Parse shooting wait line.
    Example: [01:55:52] T1 P1 SHOOT : Unit 6(11, 7) WAIT [SUCCESS] [STEP: YES]
    """
    match = re.search(r'T\d+ P\d+ SHOOT : Unit (\d+)\((\d+), (\d+)\) WAIT', line)
    if match:
        unit_id = int(match.group(1))
        unit_col, unit_row = int(match.group(2)), int(match.group(3))

        return {
            'type': 'shoot_wait',
            'unit_id': unit_id,
            'unit_pos': (unit_col, unit_row),
            'line': line
        }
    return None


def parse_unit_start_position(line: str) -> Dict[str, Any]:
    """
    Parse unit starting position.
    Example: [01:55:52] Unit 1 (Intercessor) P0: Starting position (9, 12)
    """
    match = re.search(r'Unit (\d+) \(.+?\) P(\d+): Starting position \((\d+), (\d+)\)', line)
    if match:
        unit_id = int(match.group(1))
        player = int(match.group(2))
        col, row = int(match.group(3)), int(match.group(4))

        return {
            'unit_id': unit_id,
            'player': player,
            'col': col,
            'row': row
        }
    return None


# ============================================================================
# VALIDATION LOGIC
# ============================================================================

class GameStateTracker:
    """Track unit positions throughout the game."""

    def __init__(self, board_size: Tuple[int, int], wall_hexes: Set[Tuple[int, int]]):
        self.board_size = board_size
        self.wall_hexes = wall_hexes
        self.units = {}  # unit_id -> {'col': int, 'row': int, 'player': int, 'move_range': int}
        self.current_episode = 0

    def reset_episode(self):
        """Reset for new episode."""
        self.units = {}
        self.current_episode += 1

    def add_unit(self, unit_id: int, player: int, col: int, row: int, move_range: int = 6):
        """Add unit at starting position."""
        self.units[unit_id] = {
            'col': col,
            'row': row,
            'player': player,
            'move_range': move_range
        }

    def update_unit_position(self, unit_id: int, col: int, row: int):
        """Update unit position after move."""
        if unit_id in self.units:
            self.units[unit_id]['col'] = col
            self.units[unit_id]['row'] = row

    def get_unit_position(self, unit_id: int) -> Tuple[int, int]:
        """Get current unit position."""
        if unit_id not in self.units:
            return None
        return (self.units[unit_id]['col'], self.units[unit_id]['row'])

    def get_occupied_hexes(self, exclude_unit_id: int = None) -> Set[Tuple[int, int]]:
        """Get all occupied hexes (excluding specified unit)."""
        occupied = set()
        for uid, unit in self.units.items():
            if uid != exclude_unit_id:
                occupied.add((unit['col'], unit['row']))
        return occupied

    def get_enemy_positions(self, player: int) -> Set[Tuple[int, int]]:
        """Get positions of all enemy units (different player)."""
        enemy_positions = set()
        for uid, unit in self.units.items():
            if unit['player'] != player:
                enemy_positions.add((unit['col'], unit['row']))
        return enemy_positions


def load_board_config(config_path: str = "config/board_config.json") -> Tuple[Tuple[int, int], Set[Tuple[int, int]]]:
    """Load board configuration."""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Board config not found: {config_path}")

    with open(config_path, 'r', encoding='utf-8-sig') as f:
        config = json.load(f)

    board = config['default']
    cols = board['cols']
    rows = board['rows']

    wall_hexes = set()
    for wall_hex in board['wall_hexes']:
        if isinstance(wall_hex, (list, tuple)) and len(wall_hex) >= 2:
            wall_hexes.add((wall_hex[0], wall_hex[1]))

    return (cols, rows), wall_hexes


def validate_log(log_path: str):
    """Validate entire training log."""

    # Load board configuration
    print("Loading board configuration...")
    board_size, wall_hexes = load_board_config()
    print(f"Board: {board_size[0]}x{board_size[1]} with {len(wall_hexes)} wall hexes")

    # Validation counters
    total_moves = 0
    invalid_moves = 0
    total_shots = 0
    invalid_shots = 0
    total_wait_shots = 0
    wait_with_los = 0
    wait_without_los = 0

    # Detailed error tracking
    move_errors = []
    shot_errors = []
    wait_warnings = []

    # Game state tracker
    tracker = GameStateTracker(board_size, wall_hexes)

    print(f"\nProcessing log: {log_path}")

    with open(log_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()

            # Episode start
            if "=== EPISODE START ===" in line:
                tracker.reset_episode()
                continue

            # Parse unit starting positions
            unit_start = parse_unit_start_position(line)
            if unit_start:
                tracker.add_unit(
                    unit_start['unit_id'],
                    unit_start['player'],
                    unit_start['col'],
                    unit_start['row'],
                    move_range=6  # Intercessor default
                )
                continue

            # Parse move action
            move = parse_move_action(line)
            if move:
                total_moves += 1
                unit_id = move['unit_id']
                from_pos = move['from']
                to_pos = move['to']

                # Get occupied hexes (excluding the moving unit)
                occupied = tracker.get_occupied_hexes(exclude_unit_id=unit_id)

                # Validate pathfinding
                unit = tracker.units.get(unit_id)
                if unit:
                    move_range = unit['move_range']
                    player = unit['player']

                    # CRITICAL FIX: Get enemy positions for adjacency check
                    enemy_positions = tracker.get_enemy_positions(player)

                    reachable = is_reachable(
                        from_pos[0], from_pos[1],
                        to_pos[0], to_pos[1],
                        move_range,
                        wall_hexes,
                        occupied,
                        board_size,
                        enemy_positions  # Now includes enemy adjacency check
                    )

                    if not reachable:
                        invalid_moves += 1
                        error = {
                            'line_num': line_num,
                            'unit_id': unit_id,
                            'from': from_pos,
                            'to': to_pos,
                            'move_range': move_range,
                            'line': line
                        }
                        move_errors.append(error)

                    # Update tracker
                    tracker.update_unit_position(unit_id, to_pos[0], to_pos[1])

                continue

            # Parse shoot action
            shoot = parse_shoot_action(line)
            if shoot:
                total_shots += 1
                shooter_id = shoot['shooter_id']
                shooter_pos = shoot['shooter_pos']
                target_id = shoot['target_id']

                # Get target position
                target_pos = tracker.get_unit_position(target_id)

                if target_pos:
                    # Validate LoS
                    has_los = has_line_of_sight(
                        shooter_pos[0], shooter_pos[1],
                        target_pos[0], target_pos[1],
                        wall_hexes
                    )

                    if not has_los:
                        invalid_shots += 1
                        error = {
                            'line_num': line_num,
                            'shooter_id': shooter_id,
                            'shooter_pos': shooter_pos,
                            'target_id': target_id,
                            'target_pos': target_pos,
                            'line': line
                        }
                        shot_errors.append(error)

                continue

            # Parse shoot wait
            shoot_wait = parse_shoot_wait(line)
            if shoot_wait:
                total_wait_shots += 1
                unit_id = shoot_wait['unit_id']
                unit_pos = shoot_wait['unit_pos']

                # Check if unit has LoS to ANY enemy
                has_any_los = False
                unit = tracker.units.get(unit_id)
                if unit:
                    unit_player = unit['player']

                    # Check LoS to all enemy units
                    for enemy_id, enemy in tracker.units.items():
                        if enemy['player'] != unit_player:
                            enemy_pos = (enemy['col'], enemy['row'])
                            if has_line_of_sight(unit_pos[0], unit_pos[1], enemy_pos[0], enemy_pos[1], wall_hexes):
                                has_any_los = True
                                break

                    if has_any_los:
                        wait_with_los += 1
                        warning = {
                            'line_num': line_num,
                            'unit_id': unit_id,
                            'unit_pos': unit_pos,
                            'line': line
                        }
                        wait_warnings.append(warning)
                    else:
                        wait_without_los += 1

                continue

    # Print results
    print("\n" + "="*80)
    print("VALIDATION RESULTS")
    print("="*80)

    print(f"\n[MOVEMENT VALIDATION]")
    print(f"  Total moves:      {total_moves}")
    print(f"  Invalid moves:    {invalid_moves} ({100*invalid_moves/total_moves if total_moves > 0 else 0:.1f}%)")
    print(f"  Valid moves:      {total_moves - invalid_moves} ({100*(total_moves-invalid_moves)/total_moves if total_moves > 0 else 0:.1f}%)")

    if invalid_moves > 0:
        print(f"\n[X] INVALID MOVES (showing first 10):")
        for error in move_errors[:10]:
            print(f"  Line {error['line_num']}: Unit {error['unit_id']} moved from {error['from']} to {error['to']}")
            print(f"    Move range: {error['move_range']}, but path blocked by walls or occupied hexes")
            print(f"    {error['line'][:120]}")

    print(f"\n[SHOOTING VALIDATION]")
    print(f"  Total shots:      {total_shots}")
    print(f"  Invalid shots:    {invalid_shots} ({100*invalid_shots/total_shots if total_shots > 0 else 0:.1f}%)")
    print(f"  Valid shots:      {total_shots - invalid_shots} ({100*(total_shots-invalid_shots)/total_shots if total_shots > 0 else 0:.1f}%)")

    if invalid_shots > 0:
        print(f"\n[X] INVALID SHOTS (showing first 10):")
        for error in shot_errors[:10]:
            print(f"  Line {error['line_num']}: Unit {error['shooter_id']} at {error['shooter_pos']} shot unit {error['target_id']} at {error['target_pos']}")
            print(f"    NO LINE OF SIGHT - blocked by walls")
            print(f"    {error['line'][:120]}")

    print(f"\n[SHOOT WAIT ANALYSIS]")
    print(f"  Total wait actions:     {total_wait_shots}")
    print(f"  Wait WITH LoS:          {wait_with_los} ({100*wait_with_los/total_wait_shots if total_wait_shots > 0 else 0:.1f}%)")
    print(f"  Wait WITHOUT LoS:       {wait_without_los} ({100*wait_without_los/total_wait_shots if total_wait_shots > 0 else 0:.1f}%)")

    if wait_with_los > 0:
        print(f"\n[!] WAIT WITH LoS (tactical decision, not error - showing first 5):")
        for warning in wait_warnings[:5]:
            print(f"  Line {warning['line_num']}: Unit {warning['unit_id']} at {warning['unit_pos']} chose to wait despite having LoS")
            print(f"    {warning['line'][:120]}")

    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)

    if invalid_moves == 0 and invalid_shots == 0:
        print("\n✅ ✅ ✅ ALL ACTIONS VALID! ✅ ✅ ✅")
        print("   - All movements respect walls and pathfinding")
        print("   - All shots have clear line of sight")
        print("   - No rule violations detected")
        print("\n🎉 PATHFINDING VALIDATION PASSED! 🎉\n")
    else:
        print("\n❌ ❌ ❌ VALIDATION FAILED! ❌ ❌ ❌")
        if invalid_moves > 0:
            print(f"   - {invalid_moves} invalid movements detected ({100*invalid_moves/total_moves:.1f}% of moves)")
        if invalid_shots > 0:
            print(f"   - {invalid_shots} invalid shots detected ({100*invalid_shots/total_shots:.1f}% of shots)")
        print()

    print("\n")
    return invalid_moves == 0 and invalid_shots == 0


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    log_file = sys.argv[1] if len(sys.argv) > 1 else "train_step.log"

    if not os.path.exists(log_file):
        print(f"Error: Log file not found: {log_file}")
        sys.exit(1)

    success = validate_log(log_file)
    sys.exit(0 if success else 1)
