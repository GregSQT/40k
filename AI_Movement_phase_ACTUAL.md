🏃 MOVEMENT PHASE - Complete Function Call Mapping

PHASE ENTRY - ELIGIBILITY CHECK:
├── get_eligible_units(game_state) [Lines 17-36]
│   ├── What it does: Iterates through all units, applies AI_TURN.md eligibility checks
│   ├── For each unit in game_state["units"]:
│   │   ├── unit["HP_CUR"] <= 0? → YES → Skip (Dead unit)
│   │   ├── unit["player"] != current_player? → YES → Skip (Wrong player)
│   │   ├── unit["id"] in game_state["units_moved"]? → YES → Skip (Already moved)
│   │   └── ALL PASSED → Add unit["id"] to eligible_units list
│   └── Returns: List[str] of eligible unit IDs

ACTION EXECUTION SEQUENCE:
├── execute_action(game_state, unit, action, config) [Lines 42-60]
│   ├── What it does: Routes movement actions to appropriate handlers
│   ├── action_type == "move":
│   │   ├── dest_col/dest_row missing? → RETURN (False, "missing_destination")
│   │   └── Calls: _attempt_movement_to_destination()
│   ├── action_type == "skip":
│   │   ├── Adds: game_state["units_moved"].add(unit["id"])
│   │   └── RETURN (True, skip_result_dict)
│   └── Unknown action_type → RETURN (False, "invalid_action_for_phase")

MOVEMENT EXECUTION:
├── _attempt_movement_to_destination(game_state, unit, dest_col, dest_row, config) [Lines 63-85]
│   ├── What it does: Validate destination and execute movement with flee detection
│   ├── Calls: _is_valid_destination(game_state, dest_col, dest_row, unit, config)
│   ├── Invalid destination? → RETURN (False, "invalid_destination")
│   ├── Calls: was_adjacent = _is_adjacent_to_enemy(game_state, unit)
│   ├── EXECUTE MOVEMENT:
│   │   ├── Store: orig_col, orig_row = unit["col"], unit["row"]
│   │   ├── Update: unit["col"] = dest_col, unit["row"] = dest_row
│   │   ├── Track: game_state["units_moved"].add(unit["id"])
│   │   └── IF was_adjacent: game_state["units_fled"].add(unit["id"])
│   └── RETURN (True, movement_result_with_flee_status)

VALIDATION FUNCTIONS:
├── _is_valid_destination(game_state, col, row, unit, config) [Lines 88-107]
│   ├── What it does: Validate movement destination per AI_TURN.md restrictions
│   ├── Board bounds check:
│   │   └── (col < 0 or row < 0 or col >= board_width or row >= board_height)? → RETURN False
│   ├── Wall collision check:
│   │   └── (col, row) in game_state["wall_hexes"]? → RETURN False
│   ├── Unit occupation check:
│   │   └── Another unit at destination with HP_CUR > 0? → RETURN False
│   ├── Calls: _is_hex_adjacent_to_enemy(game_state, col, row, unit["player"])
│   │   └── Adjacent to enemy at destination? → RETURN False
│   └── ALL PASSED → RETURN True
│
├── _is_adjacent_to_enemy(game_state, unit) [Lines 110-122]
│   ├── What it does: Check if unit is adjacent to enemy for flee detection
│   ├── Gets: cc_range = unit["CC_RNG"]
│   ├── For each enemy with HP_CUR > 0:
│   │   ├── Calculates: distance = max(abs(unit["col"] - enemy["col"]), abs(unit["row"] - enemy["row"]))
│   │   └── distance <= cc_range? → RETURN True
│   └── No adjacent enemies → RETURN False
│
└── _is_hex_adjacent_to_enemy(game_state, col, row, player) [Lines 125-136]
    ├── What it does: Check if specific hex position is adjacent to any enemy
    ├── For each enemy with different player and HP_CUR > 0:
    │   ├── Calculates: distance = max(abs(col - enemy["col"]), abs(row - enemy["row"]))
    │   └── distance <= 1? → RETURN True (Adjacent check)
    └── No adjacent enemies → RETURN False

COMPLETE EXECUTION FLOW:
└── Single API Call Pattern:
    ├── Frontend → execute_action({"action": "move", "destCol": X, "destRow": Y})
    ├── _attempt_movement_to_destination() validates immediately
    ├── If valid: unit moves, tracking updated, result returned
    ├── If invalid: error returned, no state changes
    └── **PROCESS COMPLETE - NO ADDITIONAL CALLS NEEDED**