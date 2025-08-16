#!/usr/bin/env python3
"""
shared/gameMechanics.py
COMPLETE unified game mechanics for both PvP and AI training systems.
EXACT copy of ALL PvP mechanics from BoardPvp.tsx, useGameActions.ts, and usePhaseTransition.ts.

DO NOT modify without checking both PvP and training implementations.
"""

from typing import Dict, List, Any, Set, Optional, Tuple
from shared.gameRules import are_units_adjacent as areUnitsAdjacent, is_unit_in_range as isUnitInRange, offset_to_cube as offsetToCube, cube_distance as cubeDistance, roll_2d6 as roll2D6

# === CUBE COORDINATE SYSTEM (EXACT from frontend) ===

# Cube directions for proper hex neighbors (EXACT from BoardPvp.tsx)
CUBE_DIRECTIONS = [
    [1, -1, 0], [1, 0, -1], [0, 1, -1], 
    [-1, 1, 0], [-1, 0, 1], [0, -1, 1]
]

def get_cube_neighbors(col: int, row: int) -> List[Tuple[int, int]]:
    """Get all 6 hex neighbors using cube coordinates (EXACT from BoardPvp.tsx)."""
    current_cube = offsetToCube(col, row)
    neighbors = []
    
    # Handle both tuple and dict formats from offsetToCube
    if isinstance(current_cube, tuple):
        current_x, current_y, current_z = current_cube
    else:
        current_x, current_y, current_z = current_cube['x'], current_cube['y'], current_cube['z']
    
    for dx, dy, dz in CUBE_DIRECTIONS:
        neighbor_cube = {
            'x': current_x + dx,
            'y': current_y + dy,
            'z': current_z + dz
        }
        
        # Convert back to offset coordinates
        neighbor_col = neighbor_cube['x']
        neighbor_row = neighbor_cube['z'] + ((neighbor_cube['x'] - (neighbor_cube['x'] & 1)) >> 1)
        
        neighbors.append((neighbor_col, neighbor_row))
    
    return neighbors

# === MOVEMENT VALIDATION (EXACT from BoardPvp.tsx BFS) ===

def calculate_available_move_cells(unit: Dict[str, Any], 
                                  units: List[Dict[str, Any]], 
                                  board_config: Dict[str, Any],
                                  board_cols: int, 
                                  board_rows: int) -> List[Dict[str, int]]:
    """
    EXACT copy of BoardPvp.tsx runMovementBFS logic.
    Calculate all valid movement destinations using BFS pathfinding.
    """
    if "MOVE" not in unit:
        raise KeyError(f"Unit {unit.get('id')} missing required MOVE property")
    
    center_col = unit["col"]
    center_row = unit["row"]
    
    visited = {}
    queue = [(center_col, center_row, 0)]
    available_cells = []
    
    # Collect all forbidden hexes (adjacent to any enemy + wall hexes) using cube coordinates
    forbidden_set = set()
    
    # Add all wall hexes as forbidden (EXACT from BoardPvp.tsx)
    wall_hexes = board_config.get('wall_hexes', [])
    for wall_hex in wall_hexes:
        if isinstance(wall_hex, (list, tuple)) and len(wall_hex) == 2:
            forbidden_set.add(f"{wall_hex[0]},{wall_hex[1]}")
    
    # Add enemy positions and all adjacent hexes as forbidden (EXACT from BoardPvp.tsx)
    moving_unit_player = unit["player"]
    for other_unit in units:
        # Skip friendly units - only enemy units create forbidden zones
        if other_unit["player"] == moving_unit_player:
            continue
        
        # Skip dead units - they don't create forbidden zones
        if not other_unit.get("alive", True):
            continue
        
        # Add enemy position itself
        forbidden_set.add(f"{other_unit['col']},{other_unit['row']}")
        
        # Use cube coordinates for proper hex adjacency (EXACT from BoardPvp.tsx)
        enemy_neighbors = get_cube_neighbors(other_unit["col"], other_unit["row"])
        for adj_col, adj_row in enemy_neighbors:
            if (0 <= adj_col < board_cols and 0 <= adj_row < board_rows):
                forbidden_set.add(f"{adj_col},{adj_row}")
    
    # BFS pathfinding (EXACT from BoardPvp.tsx)
    while queue:
        col, row, steps = queue.pop(0)
        key = f"{col},{row}"
        
        if key in visited and steps >= visited[key]:
            continue
        
        visited[key] = steps
        
        # Skip forbidden positions completely - don't expand from them (EXACT from BoardPvp.tsx)
        if key in forbidden_set and steps > 0:
            continue
        
        # Check if hex is blocked by another unit (EXACT from BoardPvp.tsx)
        blocked = any(u["col"] == col and u["row"] == row and u["id"] != unit["id"] for u in units)
        
        # Add valid cells (EXACT from BoardPvp.tsx)
        if steps > 0 and steps <= unit["MOVE"] and not blocked and key not in forbidden_set:
            available_cells.append({"col": col, "row": row})
        
        if steps >= unit["MOVE"]:
            continue
        
        # Explore neighbors using cube coordinates (EXACT from BoardPvp.tsx)
        neighbors = get_cube_neighbors(col, row)
        for ncol, nrow in neighbors:
            nkey = f"{ncol},{nrow}"
            next_steps = steps + 1
            
            if (0 <= ncol < board_cols and 
                0 <= nrow < board_rows and 
                next_steps <= unit["MOVE"] and 
                nkey not in forbidden_set):
                
                nblocked = any(u["col"] == ncol and u["row"] == nrow and u["id"] != unit["id"] for u in units)
                
                if (not nblocked and 
                    (nkey not in visited or visited[nkey] > next_steps)):
                    queue.append((ncol, nrow, next_steps))
    
    return available_cells

def is_valid_move_destination(unit: Dict[str, Any], 
                             dest_col: int, 
                             dest_row: int,
                             units: List[Dict[str, Any]], 
                             board_config: Dict[str, Any],
                             board_cols: int, 
                             board_rows: int) -> bool:
    """Check if destination is a valid move target."""
    available_cells = calculate_available_move_cells(unit, units, board_config, board_cols, board_rows)
    return any(cell["col"] == dest_col and cell["row"] == dest_row for cell in available_cells)

# === CHARGE MECHANICS (EXACT from useGameActions.ts) ===

def get_charge_max_distance() -> int:
    """Get charge max distance from config"""
    from config_loader import get_config_loader
    config = get_config_loader()
    game_config = config.get_game_config()
    return game_config["game_rules"]["charge_max_distance"]

def calculate_charge_destinations(unit: Dict[str, Any], 
                                 charge_roll: int,
                                 units: List[Dict[str, Any]], 
                                 board_config: Dict[str, Any],
                                 board_cols: int, 
                                 board_rows: int) -> List[Dict[str, int]]:
    """
    EXACT copy of useGameActions.ts getChargeDestinations logic.
    Calculate valid charge destinations using BFS with charge distance.
    """
    visited = {}
    queue = [(unit["col"], unit["row"], 0)]
    valid_destinations = []
    
    # Same forbidden set logic as movement but without enemy adjacency restriction
    forbidden_set = set()
    
    # Add wall hexes
    wall_hexes = board_config.get('wall_hexes', [])
    for wall_hex in wall_hexes:
        if isinstance(wall_hex, (list, tuple)) and len(wall_hex) == 2:
            forbidden_set.add(f"{wall_hex[0]},{wall_hex[1]}")
    
    # Add occupied positions (but NOT enemy adjacent hexes for charging)
    for other_unit in units:
        if other_unit["id"] != unit["id"]:
            forbidden_set.add(f"{other_unit['col']},{other_unit['row']}")
    
    # BFS for charge movement (EXACT from useGameActions.ts)
    while queue:
        col, row, steps = queue.pop(0)
        key = f"{col},{row}"
        
        if key in visited and steps >= visited[key]:
            continue
        
        visited[key] = steps
        
        # Skip forbidden positions (can't move through them)
        if key in forbidden_set and steps > 0:
            continue
        
        # Check if this position is adjacent to a chargeable enemy and within charge range
        if steps > 0 and steps <= charge_roll and key not in forbidden_set:
            chargeable_enemy_adjacent = any(
                enemy["player"] != unit["player"] and
                max(abs(col - enemy["col"]), abs(row - enemy["row"])) == 1 and
                cubeDistance(offsetToCube(unit["col"], unit["row"]), 
                           offsetToCube(enemy["col"], enemy["row"])) <= get_charge_max_distance()
                for enemy in units
            )
            
            if chargeable_enemy_adjacent:
                valid_destinations.append({"col": col, "row": row})
        
        if steps >= charge_roll:
            continue
        
        # Explore neighbors
        neighbors = get_cube_neighbors(col, row)
        for ncol, nrow in neighbors:
            nkey = f"{ncol},{nrow}"
            next_steps = steps + 1
            
            if (0 <= ncol < board_cols and 
                0 <= nrow < board_rows and 
                next_steps <= charge_roll and 
                (nkey not in visited or visited[nkey] > next_steps)):
                queue.append((ncol, nrow, next_steps))
    
    return valid_destinations

def can_unit_charge_basic(unit: Dict[str, Any], 
                         units: List[Dict[str, Any]], 
                         units_fled: Set[int], 
                         units_charged: Set[int]) -> bool:
    """EXACT copy of useGameActions.ts charge eligibility logic."""
    if unit["id"] in units_charged:
        return False  # Already charged
    if unit["id"] in units_fled:
        return False  # Fled units can't charge
    
    enemy_units = [u for u in units if u["player"] != unit["player"]]
    
    # Check if adjacent to any enemy (already in combat)
    is_adjacent = any(areUnitsAdjacent(unit, enemy) for enemy in enemy_units)
    if is_adjacent:
        return False
    
    # Check if any enemies within 12-hex charge range
    has_enemies_within_12_hexes = any(
        cubeDistance(offsetToCube(unit["col"], unit["row"]), 
                    offsetToCube(enemy["col"], enemy["row"])) <= get_charge_max_distance()
        for enemy in enemy_units
    )
    
    return has_enemies_within_12_hexes

# === UNIT ELIGIBILITY (EXACT from useGameActions.ts) ===

def is_unit_eligible(unit: Dict[str, Any], 
                    current_player: int, 
                    phase: str, 
                    units: List[Dict[str, Any]], 
                    units_moved: Set[int], 
                    units_charged: Set[int], 
                    units_attacked: Set[int], 
                    units_fled: Set[int],
                    combat_sub_phase: Optional[str] = None,
                    combat_active_player: Optional[int] = None) -> bool:
    """
    EXACT copy of PvP isUnitEligible logic from useGameActions.ts.
    Check if unit is eligible for selection in current phase.
    """
    if unit["player"] != current_player:
        return False

    # Get enemy units once for efficiency (EXACT from PvP)
    enemy_units = [u for u in units if u["player"] != current_player]

    if phase == "move":
        # Units can always move, even if adjacent to enemies (EXACT from PvP)
        return unit["id"] not in units_moved
    
    elif phase == "shoot":
        if unit["id"] in units_moved:
            return False
        # NEW RULE: Units that fled cannot shoot (EXACT from PvP)
        if unit["id"] in units_fled:
            return False
        # Check if unit is adjacent to any enemy (engaged in combat) (EXACT from PvP)
        has_adjacent_enemy_shoot = any(areUnitsAdjacent(unit, enemy) for enemy in enemy_units)
        if has_adjacent_enemy_shoot:
            return False
        # Check if unit has enemies in shooting range that are NOT adjacent to friendly units (EXACT from PvP)
        friendly_units = [u for u in units if u["player"] == unit["player"] and u["id"] != unit["id"]]
        
        def can_shoot_enemy(enemy):
            if not isUnitInRange(unit, enemy, unit["RNG_RNG"]):
                return False
            # Rule 2: Cannot shoot enemy units adjacent to friendly units (EXACT from PvP)
            is_enemy_adjacent_to_friendly = any(
                max(abs(friendly["col"] - enemy["col"]), abs(friendly["row"] - enemy["row"])) == 1
                for friendly in friendly_units
            )
            return not is_enemy_adjacent_to_friendly
        
        return any(can_shoot_enemy(enemy) for enemy in enemy_units)
    
    elif phase == "charge":
        return can_unit_charge_basic(unit, units, units_fled, units_charged)
    
    elif phase == "combat":
        if unit["id"] in units_attacked:
            return False
        
        # Combat sub-phase logic (EXACT from useGameActions.ts)
        if combat_sub_phase == "charged_units":
            if unit["player"] != current_player:
                return False
            if not unit.get("hasChargedThisTurn", False):
                return False
        elif combat_sub_phase == "alternating_combat":
            if combat_active_player is None:
                return False
            if unit["player"] != combat_active_player:
                return False
            if unit.get("hasChargedThisTurn", False):
                return False
        else:
            if unit["player"] != current_player:
                return False
        
        # Must have enemies in combat range (EXACT from useGameActions.ts)
        if "CC_RNG" not in unit:
            raise KeyError("unit.CC_RNG is required")
        combat_range = unit["CC_RNG"]
        
        # Only units adjacent to enemies should be eligible for combat
        actual_enemy_units = [u for u in units if u["player"] != unit["player"]]
        has_adjacent_enemy = any(
            max(abs(unit["col"] - enemy["col"]), abs(unit["row"] - enemy["row"])) == combat_range
            for enemy in actual_enemy_units
        )
        return has_adjacent_enemy
    
    else:
        return False

# === FLEE DETECTION (EXACT from useGameActions.ts confirmMove) ===

def detect_flee_on_move(unit: Dict[str, Any], 
                       dest_col: int, 
                       dest_row: int, 
                       units: List[Dict[str, Any]]) -> bool:
    """
    EXACT copy of PvP flee detection logic from confirmMove in useGameActions.ts.
    Check if unit is fleeing (was adjacent to enemy at start, ends not adjacent).
    """
    enemy_units = [u for u in units if u["player"] != unit["player"]]
    
    # EXACT from PvP: Check adjacency at ORIGINAL position before move
    was_adjacent_to_enemy = any(
        max(abs(unit["col"] - enemy["col"]), abs(unit["row"] - enemy["row"])) == 1
        for enemy in enemy_units
    )
    
    if was_adjacent_to_enemy:
        # Check if unit will still be adjacent after the move
        will_be_adjacent_to_enemy = any(
            max(abs(dest_col - enemy["col"]), abs(dest_row - enemy["row"])) == 1
            for enemy in enemy_units
        )
        
        # Only mark as fled if unit was adjacent and will no longer be adjacent
        if not will_be_adjacent_to_enemy:
            return True
    
    return False

# === PHASE TRANSITION LOGIC (EXACT from usePhaseTransition.ts) ===

def should_transition_from_move(units: List[Dict[str, Any]], 
                               current_player: int, 
                               units_moved: Set[int]) -> bool:
    """EXACT copy of PvP shouldTransitionFromMove logic."""
    player_units = [u for u in units if u["player"] == current_player]
    return all(unit["id"] in units_moved for unit in player_units)

def should_transition_from_shoot(units: List[Dict[str, Any]], 
                                current_player: int, 
                                units_shot: Set[int], 
                                units_fled: Set[int]) -> bool:
    """EXACT copy of PvP shouldTransitionFromShoot logic."""
    player_units = [u for u in units if u["player"] == current_player]
    enemy_units = [u for u in units if u["player"] != current_player]
    
    print(f"🎯 SHARED should_transition_from_shoot DEBUG:")
    print(f"  Player {current_player} units: {len(player_units)}")
    print(f"  units_shot: {list(units_shot)}")
    
    if len(player_units) == 0:
        print(f"  → TRUE: No player units")
        return True

    # Find units that can still shoot (EXACT from TypeScript)
    shootable_units = []
    for unit in player_units:
        unit_id = unit["id"]
        print(f"  Checking unit {unit_id}:")
        
        # Check if unit already shot this phase
        if unit["id"] in units_shot:
            print(f"    ❌ Already shot (in units_shot)")
            continue
        
        # Units that fled cannot shoot
        if unit["id"] in units_fled:
            print(f"    ❌ Unit fled")
            continue
        
        # Check if unit has shots remaining (EXACT from TypeScript: unit.SHOOT_LEFT === undefined || unit.SHOOT_LEFT <= 0)
        if "SHOOT_LEFT" not in unit or unit["SHOOT_LEFT"] is None or unit["SHOOT_LEFT"] <= 0:
            print(f"    ❌ No shots left (SHOOT_LEFT: {unit.get('SHOOT_LEFT')})")
            continue
        
        # Can't shoot if adjacent to enemy (engaged in combat)
        has_adjacent_enemy = any(areUnitsAdjacent(unit, enemy) for enemy in enemy_units)
        if has_adjacent_enemy:
            print(f"    ❌ Adjacent to enemy")
            continue
        
        # Must have enemy within shooting range
        if "RNG_RNG" not in unit:
            raise KeyError(f"Unit missing required 'RNG_RNG' field: {unit}")
        has_target_in_range = any(isUnitInRange(unit, enemy, unit["RNG_RNG"]) for enemy in enemy_units)
        if has_target_in_range:
            print(f"    ✅ Can shoot - adding to shootable_units")
            shootable_units.append(unit)
        else:
            print(f"    ❌ No targets in range (RNG_RNG: {unit['RNG_RNG']})")

    print(f"  Total shootable units: {len(shootable_units)}")
    result = len(shootable_units) == 0
    print(f"  → {result}")
    return result

def should_transition_from_charge(units: List[Dict[str, Any]], 
                                 current_player: int, 
                                 phase: str,
                                 units_moved: Set[int], 
                                 units_charged: Set[int], 
                                 units_attacked: Set[int], 
                                 units_fled: Set[int]) -> bool:
    """EXACT copy of PvP shouldTransitionFromCharge logic."""
    player_units = [u for u in units if u["player"] == current_player]
    
    if len(player_units) == 0:
        return True

    # Check if all units have acted in charge phase (moved, fled, or charged)
    units_that_can_act = [
        unit for unit in player_units 
        if unit["id"] not in units_moved and unit["id"] not in units_fled and unit["id"] not in units_charged
    ]
    
    return len(units_that_can_act) == 0

def should_transition_from_charged_units_phase(units: List[Dict[str, Any]], 
                                              current_player: int, 
                                              phase: str, 
                                              combat_sub_phase: Optional[str], 
                                              units_moved: Set[int], 
                                              units_charged: Set[int], 
                                              units_attacked: Set[int], 
                                              units_fled: Set[int]) -> bool:
    """EXACT copy of PvP shouldTransitionFromChargedUnitsPhase logic."""
    if phase != "combat" or combat_sub_phase != "charged_units":
        return False
    
    active_player_units = [u for u in units if u["player"] == current_player]
    
    # Check if all charged units have attacked
    charged_units_not_attacked = [
        unit for unit in active_player_units 
        if unit.get("hasChargedThisTurn", False) and unit["id"] not in units_attacked
    ]
    
    return len(charged_units_not_attacked) == 0

def should_end_alternating_combat(units: List[Dict[str, Any]], 
                                 phase: str, 
                                 combat_sub_phase: Optional[str], 
                                 units_moved: Set[int], 
                                 units_charged: Set[int], 
                                 units_attacked: Set[int], 
                                 units_fled: Set[int]) -> bool:
    """EXACT copy of PvP shouldEndAlternatingCombat logic."""
    if phase != "combat" or combat_sub_phase != "alternating_combat":
        return False
    
    # Check if any player has eligible units (EXACT from PvP)
    all_players = [0, 1]
    
    for player in all_players:
        player_units = [u for u in units if u["player"] == player]
        
        # Check non-charged units that haven't attacked and are adjacent to enemies
        eligible_units = [
            unit for unit in player_units 
            if (not unit.get("hasChargedThisTurn", False) and 
                unit["id"] not in units_attacked and
                any(max(abs(unit["col"] - enemy["col"]), abs(unit["row"] - enemy["row"])) <= (
                    unit["CC_RNG"] if "CC_RNG" in unit else 
                    (_ for _ in ()).throw(KeyError(f"Unit missing required 'CC_RNG' field: {unit}"))
                ) for enemy in units if enemy["player"] != player))
        ]
        
        if len(eligible_units) > 0:
            return False  # Still has eligible units
    
    return True  # No eligible units for any player

def should_end_turn(units: List[Dict[str, Any]]) -> bool:
    """Check if turn should end (game over condition)."""
    # Check if any player has no units left
    all_players = [0, 1]
    
    for player in all_players:
        player_units = [u for u in units if u["player"] == player]
        if len(player_units) == 0:
            return True  # Game should end
    
    return False

# === TURN STATE MANAGEMENT ===

def reset_turn_state():
    """Returns empty sets for turn tracking (EXACT from PvP)."""
    return {
        "units_moved": set(),
        "units_charged": set(), 
        "units_attacked": set(),
        "units_fled": set()
    }

def ensure_charged_this_turn_defaults(units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ensure all units have hasChargedThisTurn property set (EXACT from usePhaseTransition.ts)."""
    updated_units = []
    for unit in units:
        updated_unit = unit.copy()
        if "hasChargedThisTurn" not in updated_unit:
            updated_unit["hasChargedThisTurn"] = False
        updated_units.append(updated_unit)
    return updated_units

# === UTILITY FUNCTIONS ===

def get_current_player_units(units: List[Dict[str, Any]], current_player: int) -> List[Dict[str, Any]]:
    """Get current player's units."""
    return [u for u in units if u["player"] == current_player]

def get_enemy_units(units: List[Dict[str, Any]], current_player: int) -> List[Dict[str, Any]]:
    """Get enemy units."""
    return [u for u in units if u["player"] != current_player]