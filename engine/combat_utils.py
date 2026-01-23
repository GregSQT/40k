#!/usr/bin/env python3
"""
combat_utils.py - Pure utility functions for combat calculations
"""

from typing import Dict, List, Tuple, Any

# ============================================================================
# COORDINATE NORMALIZATION
# ============================================================================

def normalize_coordinate(coord: Any) -> int:
    """
    Normalize coordinate to int. Raises ValueError if conversion fails.
    
    CRITICAL: All hex coordinates must be int. This function ensures type consistency
    and raises clear errors if coordinates are invalid.
    
    Args:
        coord: Coordinate value (int, float, or numeric string)
    
    Returns:
        int: Normalized coordinate as integer
    
    Raises:
        ValueError: If coordinate string cannot be converted
        TypeError: If coordinate type is not supported
    """
    if isinstance(coord, int):
        return coord
    elif isinstance(coord, float):
        return int(coord)
    elif isinstance(coord, str):
        try:
            return int(float(coord))
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid coordinate string '{coord}': {e}")
    else:
        raise TypeError(f"Invalid coordinate type {type(coord).__name__}: {coord}. Expected int, float, or numeric string.")


def normalize_coordinates(col: Any, row: Any) -> Tuple[int, int]:
    """
    Normalize both coordinates to int. Raises ValueError if conversion fails.
    
    Args:
        col: Column coordinate (int, float, or numeric string)
        row: Row coordinate (int, float, or numeric string)
    
    Returns:
        Tuple[int, int]: Normalized (col, row) as integers
    """
    return normalize_coordinate(col), normalize_coordinate(row)


def get_unit_coordinates(unit: Dict[str, Any]) -> Tuple[int, int]:
    """
    Extract and normalize unit coordinates from unit dict.
    
    CRITICAL: Always use this function to get unit coordinates to ensure
    they are normalized to int for consistent comparison.
    
    Args:
        unit: Unit dictionary with "col" and "row" keys
    
    Returns:
        Tuple[int, int]: Normalized (col, row) coordinates
    
    Raises:
        KeyError: If unit dict missing "col" or "row" keys
    """
    return normalize_coordinates(unit["col"], unit["row"])


def set_unit_coordinates(unit: Dict[str, Any], col: Any, row: Any) -> None:
    """
    Set and normalize unit coordinates in unit dict.
    
    CRITICAL: Always use this function to set unit coordinates to ensure
    they are normalized to int before storage.
    
    Args:
        unit: Unit dictionary to update
        col: Column coordinate (int, float, or numeric string)
        row: Row coordinate (int, float, or numeric string)
    
    Raises:
        ValueError: If coordinate conversion fails
        TypeError: If coordinate type is not supported
    """
    unit["col"], unit["row"] = normalize_coordinates(col, row)


# ============================================================================
# DISTANCE CALCULATION
# ============================================================================

def calculate_hex_distance(col1: int, row1: int, col2: int, row2: int) -> int:
        """Calculate hex distance using cube coordinates (matching handlers).

        WARNING: This is straight-line distance, ignoring walls!
        For pathfinding distance that respects walls, use calculate_pathfinding_distance().
        """
        # Convert offset to cube
        x1 = col1
        z1 = row1 - ((col1 - (col1 & 1)) >> 1)
        y1 = -x1 - z1

        x2 = col2
        z2 = row2 - ((col2 - (col2 & 1)) >> 1)
        y2 = -x2 - z2

        # Cube distance
        return max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))


def calculate_pathfinding_distance(col1: int, row1: int, col2: int, row2: int,
                                    game_state: Dict[str, Any],
                                    max_search_distance: int = 50) -> int:
    """
    Calculate actual pathfinding distance using BFS, respecting walls.

    This is the CORRECT distance function for AI decision-making.
    Returns the number of hexes needed to travel from (col1, row1) to (col2, row2),
    avoiding walls and impassable terrain.

    Args:
        col1, row1: Start position
        col2, row2: End position
        game_state: Game state with wall_hexes
        max_search_distance: Maximum BFS depth (performance limit)

    Returns:
        Actual path distance, or max_search_distance+1 if unreachable

    PERFORMANCE: Uses game_state cache for repeated lookups.
    Cache key: ((col1, row1), (col2, row2))
    """
    # Quick check: same position
    if col1 == col2 and row1 == row2:
        return 0

    # Check cache first
    cache_key = ((col1, row1), (col2, row2))
    if "pathfinding_distance_cache" in game_state:
        if cache_key in game_state["pathfinding_distance_cache"]:
            return game_state["pathfinding_distance_cache"][cache_key]

    # Import here to avoid circular imports
    from engine.phase_handlers.movement_handlers import _get_hex_neighbors

    # Get wall set for O(1) lookup
    wall_set = set()
    if "wall_hexes" in game_state:
        wall_set = {tuple(w) if isinstance(w, list) else w for w in game_state["wall_hexes"]}

    # BFS to find shortest path
    start_pos = (col1, row1)
    end_pos = (col2, row2)

    visited = {start_pos: 0}
    queue = [(start_pos, 0)]

    while queue:
        current_pos, current_dist = queue.pop(0)

        # Found target
        if current_pos == end_pos:
            # Cache result
            if "pathfinding_distance_cache" not in game_state:
                game_state["pathfinding_distance_cache"] = {}
            game_state["pathfinding_distance_cache"][cache_key] = current_dist
            return current_dist

        # Stop searching if we've gone too far
        if current_dist >= max_search_distance:
            continue

        # Explore neighbors
        neighbors = _get_hex_neighbors(current_pos[0], current_pos[1])

        for neighbor_col, neighbor_row in neighbors:
            neighbor_pos = (neighbor_col, neighbor_row)

            # Skip if already visited
            if neighbor_pos in visited:
                continue

            # Skip walls
            if neighbor_pos in wall_set:
                continue

            # Skip out of bounds (basic check)
            if neighbor_col < 0 or neighbor_row < 0:
                continue
            if "board_cols" in game_state and neighbor_col >= game_state["board_cols"]:
                continue
            if "board_rows" in game_state and neighbor_row >= game_state["board_rows"]:
                continue

            neighbor_dist = current_dist + 1
            visited[neighbor_pos] = neighbor_dist
            queue.append((neighbor_pos, neighbor_dist))

    # Target not reachable within max_search_distance
    unreachable_dist = max_search_distance + 1

    # Cache the unreachable result too
    if "pathfinding_distance_cache" not in game_state:
        game_state["pathfinding_distance_cache"] = {}
    game_state["pathfinding_distance_cache"][cache_key] = unreachable_dist

    return unreachable_dist


def get_hex_line(start_col: int, start_row: int, end_col: int, end_row: int) -> List[Tuple[int, int]]:
        """Get hex line using handler delegation."""
        from engine.phase_handlers import shooting_handlers
        return shooting_handlers._get_accurate_hex_line(start_col, start_row, end_col, end_row)


# ============================================================================
# LINE OF SIGHT
# ============================================================================

def has_line_of_sight(shooter: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
        """
        Check line of sight between shooter and target.

        PERFORMANCE: Uses hex-coordinate cache (5-10x speedup on cache hits).
        Cache key: ((from_col, from_row), (to_col, to_row))
        Walls are static within episode, so LoS from hex A to hex B is constant.
        """
        from engine.phase_handlers import shooting_handlers

        # Extract and normalize coordinates
        from_col_int, from_row_int = get_unit_coordinates(shooter)
        to_col_int, to_row_int = get_unit_coordinates(target)

        # Check hex-coordinate cache first
        if "hex_los_cache" in game_state:
            cache_key = ((from_col_int, from_row_int), (to_col_int, to_row_int))
            if cache_key in game_state["hex_los_cache"]:
                return game_state["hex_los_cache"][cache_key]

        # Cache miss: compute LoS (expensive)
        has_los = shooting_handlers._has_line_of_sight(game_state, shooter, target)

        # Store in cache for future lookups
        if "hex_los_cache" not in game_state:
            game_state["hex_los_cache"] = {}
        game_state["hex_los_cache"][((from_col_int, from_row_int), (to_col_int, to_row_int))] = has_los

        return has_los


def has_line_of_sight_coords(from_col: int, from_row: int, to_col: int, to_row: int,
                              game_state: Dict[str, Any]) -> bool:
        """
        Check line of sight between two hex coordinates.

        PERFORMANCE: Direct coordinate-based LoS check with caching.
        Use this when you don't have unit dicts, only coordinates.
        """
        from engine.phase_handlers import shooting_handlers

        # CRITICAL: Normalize coordinates to int for consistent comparison
        from_col_int, from_row_int = normalize_coordinates(from_col, from_row)
        to_col_int, to_row_int = normalize_coordinates(to_col, to_row)
        
        # Check hex-coordinate cache first
        if "hex_los_cache" in game_state:
            cache_key = ((from_col_int, from_row_int), (to_col_int, to_row_int))
            if cache_key in game_state["hex_los_cache"]:
                return game_state["hex_los_cache"][cache_key]

        # Cache miss: compute LoS using temp unit dicts
        temp_shooter = {"col": from_col_int, "row": from_row_int}
        temp_target = {"col": to_col_int, "row": to_row_int}
        has_los = shooting_handlers._has_line_of_sight(game_state, temp_shooter, temp_target)

        # Store in cache
        if "hex_los_cache" not in game_state:
            game_state["hex_los_cache"] = {}
        game_state["hex_los_cache"][((from_col_int, from_row_int), (to_col_int, to_row_int))] = has_los

        return has_los


def check_los_cached(shooter: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> float:
        """
        Check LoS using cache if available, fallback to calculation.
        AI_TURN.md COMPLIANCE: Direct field access, uses game_state cache.
        
        Returns:
        - 1.0 = Clear line of sight
        - 0.0 = Blocked line of sight
        """
        # AI_TURN_SHOOTING_UPDATE.md: Use shooter["los_cache"] (new architecture)
        target_id = target["id"]
        
        if "los_cache" in shooter and shooter["los_cache"]:
            if target_id in shooter["los_cache"]:
                return 1.0 if shooter["los_cache"][target_id] else 0.0
        
        # Fallback: calculate LoS (happens if cache not built yet or used outside shooting phase)
        from engine.phase_handlers import shooting_handlers
        has_los = shooting_handlers._has_line_of_sight(game_state, shooter, target)
        return 1.0 if has_los else 0.0

# ============================================================================
# COMBAT VALIDATION
# ============================================================================

def calculate_wound_target(strength: int, toughness: int) -> int:
        """W40K wound chart - basic calculation without external dependencies"""
        if strength >= toughness * 2:
            return 2  # 2+
        elif strength > toughness:
            return 3  # 3+
        elif strength == toughness:
            return 4  # 4+
        elif strength * 2 <= toughness:
            return 6  # 6+
        else:
            return 5  # 5+


def has_valid_shooting_targets(unit: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
        """Check if unit has valid shooting targets per AI_TURN.md restrictions."""
        from engine.phase_handlers import shooting_handlers
        for enemy in game_state["units"]:
            if (enemy["player"] != unit["player"] and 
                enemy["HP_CUR"] > 0 and
                shooting_handlers._is_valid_shooting_target(game_state, unit, enemy)):
                return True
        return False


def is_valid_shooting_target(shooter: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
        """REMOVED: Redundant with handler. Use shooting_handlers._is_valid_shooting_target exclusively."""
        # AI_IMPLEMENTATION.md: Complete delegation to handler for consistency
        from engine.phase_handlers import shooting_handlers
        return shooting_handlers._is_valid_shooting_target(game_state, shooter, target)