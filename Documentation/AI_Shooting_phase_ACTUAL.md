🎯 SHOOTING PHASE - Complete Function Call Mapping

PHASE ENTRY:
├── build_shoot_activation_pool(game_state) [Lines 13-85]
│   ├── What it does: Iterates through all units, applies AI_TURN.md eligibility checks
│   ├── Calls: _is_adjacent_to_enemy_within_cc_range(), _has_los_to_enemies_within_range()
│   ├── Modifies: game_state["shoot_activation_pool"] = [eligible_unit_ids]
│   └── Returns: List[str] of eligible unit IDs

UNIT ACTIVATION SEQUENCE:
├── execute_action(game_state, unit, {"action": "activate_unit"}, config) [Lines 605-640]
│   ├── What it does: Routes action to appropriate handler
│   └── Calls: start_unit_activation() then _execute_while_loop()
│
├── start_unit_activation(game_state, unit_id) [Lines 282-295]
│   ├── What it does: Initialize unit shooting state
│   ├── Sets: valid_target_pool=[], TOTAL_ATTACK_LOG="", SHOOT_LEFT=RNG_NB, selected_target_id=None
│   ├── Modifies: game_state["active_shooting_unit"] = unit_id
│   └── Returns: {"success": True, "unitId": unit_id, "shootLeft": unit["SHOOT_LEFT"]}
│
└── _execute_while_loop(game_state, unit_id) [Lines 737-770] - AUTOMATIC CALL
    ├── What it does: Implements AI_TURN.md while SHOOT_LEFT > 0 logic
    ├── Calls: build_valid_target_pool(), _end_activation() if needed
    ├── Returns: Preview data dict or end_activation result
    └── **FUNCTION EXITS - BACKEND WAITS**

TARGET POOL BUILDING:
├── build_valid_target_pool(game_state, unit_id) [Lines 298-318]
│   ├── What it does: Find all valid enemies this unit can shoot
│   ├── Calls: _is_valid_shooting_target() for each enemy
│   ├── Modifies: unit["valid_target_pool"] = [valid_enemy_ids]
│   └── Returns: List[str] of valid target IDs
│
└── _is_valid_shooting_target(game_state, shooter, target) [Lines 138-177]
    ├── What it does: Validate single target per AI_TURN.md rules
    ├── Calls: _calculate_hex_distance(), _has_line_of_sight()
    ├── Checks: Range, not adjacent, not friendly adjacent, LoS
    └── Returns: bool

FIRST TARGET CLICK:
├── execute_action(game_state, unit, {"action": "left_click", "targetId": X}) [Lines 634-647]
│   ├── What it does: Route left click based on context
│   ├── Calls: _get_shooting_context(), then _handle_top_level_left_click()
│   └── **FUNCTION EXITS - BACKEND WAITS**
│
├── _get_shooting_context(game_state, unit) [Lines 600-603]
│   ├── What it does: Determine if target already selected
│   ├── Checks: unit.get("selected_target_id") exists
│   └── Returns: "target_selected" or "no_target_selected"
│
├── _handle_top_level_left_click(game_state, unit, target_id, click_target) [Lines 812-844]
│   ├── What it does: Handle clicks when no target selected
│   ├── Calls: handle_target_selection() for enemy targets
│   └── **FUNCTION EXITS - BACKEND WAITS**
│
└── handle_target_selection(game_state, unit_id, target_id) [Lines 321-346]
    ├── What it does: Set selected target, start blinking
    ├── Validates: target_id in unit["valid_target_pool"]
    ├── Sets: unit["selected_target_id"] = target_id
    └── Returns: {"action": "target_selected", "startBlinking": True}

SECOND TARGET CLICK (SHOOT):
├── execute_action(game_state, unit, {"action": "left_click", "targetId": X}) [Lines 634-647]
│   ├── What it does: Route left click (context now "target_selected")
│   ├── Calls: _get_shooting_context(), then _handle_nested_left_click()
│   └── **FUNCTION EXITS - BACKEND WAITS**
│
├── _handle_nested_left_click(game_state, unit, target_id, click_target) [Lines 773-809]
│   ├── What it does: Handle clicks when target already selected
│   ├── Calls: execute_shot() if same target clicked twice
│   └── **FUNCTION EXITS - BACKEND WAITS**
│
├── execute_shot(game_state, unit_id, target_id) [Lines 349-374]
│   ├── What it does: Execute actual shooting attack
│   ├── Calls: _execute_attack_sequence_rng()
│   ├── Modifies: unit["SHOOT_LEFT"] -= 1, unit["TOTAL_ATTACK_LOG"]
│   ├── Cleans: Dead targets from valid_target_pool
│   └── Returns: {"action": "shot_executed", "result": shot_result, "shootLeft": X}
│
└── _execute_attack_sequence_rng(shooter, target) [Lines 377-444]
    ├── What it does: Roll dice, calculate damage per W40K rules
    ├── Calls: _calculate_wound_target()
    ├── Modifies: target["HP_CUR"] if damage dealt
    └── Returns: Complete attack result with all rolls

LOOP CONTINUATION:
├── _execute_while_loop() CALLED AGAIN automatically after execute_shot()
│   ├── What it does: Check if more shots available, rebuild target pool
│   ├── SHOOT_LEFT > 0 and targets exist? → Return preview data again
│   └── Otherwise → Call _end_activation()

ACTIVATION END:
└── _end_activation(game_state, unit, arg1, arg2, arg3, arg4) [Lines 547-583]
    ├── What it does: Clean up unit state, apply AI_TURN.md tracking
    ├── Modifies: episode_steps, units_shot, shoot_activation_pool
    ├── Cleans: valid_target_pool, TOTAL_ATTACK_LOG, selected_target_id, SHOOT_LEFT
    ├── Sets: game_state.pop("active_shooting_unit", None)
    └── Returns: {"activation_ended": True, "endType": arg1, "unitId": unit_id}