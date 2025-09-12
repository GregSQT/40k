```javascript
ENGINE ORCHESTRATION:
├── w40k_engine._process_shooting_phase(action)
│   ├── First call to phase? → shooting_phase_start(game_state)
│   ├── FULL DELEGATION: shooting_handlers.execute_action(game_state, unit, action, config)
│   └── Check response for phase_complete flag

HANDLER MANAGES EVERYTHING:

PHASE INITIALIZATION:
├── ⭐shooting_phase_start(game_state)                                                    **[NEW FUNCTION]**
│   ├── Set: game_state["phase"] = "shoot" 
│   ├── ⭐shooting_build_activation_pool(game_state)
│   ├── Add console log: "SHOOT POOL BUILT"
│   └── Enter UNIT_ACTIVABLE_CHECK loop

ACTIVATION POOL BUILD
│   ├── ⭐shooting_build_activation_pool(game_state)
│   │   └── For each PLAYER unit → ELIGIBILITY CHECK:
│   │       │   ├── unit.HP_CUR > 0? → NO → ❌ → Skip
│   │       │   ├── unit.player === current_player? → NO → ❌ → Skip  
│   │       │   ├── units_fled.includes(unit.id)? → YES → ❌ → Skip
│   │       │   ├── Adjacent to enemy within CC_RNG? → YES → ❌ → Skip
│   │       │   ├── unit.RNG_NB > 0? → NO → ❌ → Skip
│   │       │   ├── Has LOS to enemies within RNG_RNG? → NO → ❌ → Skip
│   │       │   └── ALL PASSED → ✅ Add to shoot_activation_pool
│   │       └── 📋Updates: game_state["shoot_activation_pool"] = [eligible_unit_ids]
│   │           └── Highlight the units in shoot_activation_pool with a green circle around its icon


########################################################################################################################################
#### PHASE OVERVIEW - FUNCTION LEVEL ####
########################################################################################################################################
├── ⭐shooting_phase_start(game_state)
│   ├── Set: game_state["phase"] = "shoot" 
│   ├── ⭐shooting_build_activation_pool(game_state)
│   ├── Add console log: "SHOOT POOL BUILT"
│   └── Enter UNIT_ACTIVABLE_CHECK loop
├── ⭐_is_valid_shooting_unit() : STEP : UNIT_ACTIVABLE_CHECK → is shoot_activation_pool NOT empty ?
│   ├── YES → Current player is an AI player ?
│   │   ├── YES → 
│   │   └── NO → ⭐execute_action(game_state, unit, action, config) : STEP : UNIT_ACTIVATION → Human player → player activate one unit from shoot_activation_pool
│   │       ├── ⭐shooting_unit_activation_start()
│   │       ├── ⭐_shooting_unit_execution_loop() : While SHOOT_LEFT > 0
│   │       │   ├── ⭐shooting_build_valid_target_pool() : Build 📋 valid_target_pool
│   │       │   └── ⭐_is_valid_shooting_target() : valid_target_pool NOT empty ?
│   │       │       ├── YES → SHOOTING PHASE ACTIONS AVAILABLE
│   │       │       │   ├── ⭐shooting_preview()
│   │       │       │   └── ⭐shooting_click_handler() STEP : PLAYER_ACTION_SELECTION
│   │       │       │       ├── ACTION : Left click on a target in 📋valid_target_pool : ⭐shooting_target_selection_handler()
│   │       │       │       ├── ACTION : Left click on another unit in shoot_activation_pool ? ⭐_handle_unit_switch_with_context()
│   │       │       │       ├── ACTION : Left click on the active_unit → No effect
│   │       │       │       ├── ACTION : Right click on the active_unit
│   │       │       │       └── ACTION : Left OR Right click anywhere else on the board
│   │       │       └── NO → SHOOT_LEFT = RNG_NB ?
│   │       │           ├── NO → ⭐end_activation() (ACTION, 1, SHOOTING, SHOOTING) → shot the last target available in 📋valid_target_pool
│   │       │           └── YES → ⭐end_activation() (PASS, 1, PASS, SHOOTING) → no target available in 📋valid_target_pool at activation → no shoot
│   │       └── End of shooting → ⭐end_activation() (ACTION, 1, SHOOTING, SHOOTING)
│   └── NO → ⭐shooting_phase_end()
└── End of shooting phase → Advance to charge phase



########################################################################################################################################
#### COMPLETE TREE ####
########################################################################################################################################
│ELIGIBILITY & POOL BUILDING:
├── ⭐shooting_phase_start(game_state)                                                    **[NEW FUNCTION]**
│   ├── ⭐shooting_build_activation_pool(game_state)
│   ├── Add console log: "SHOOT POOL BUILT"
│   └── Enter UNIT_ACTIVABLE_CHECK loop
│
├── ⭐_is_valid_shooting_unit() : STEP : UNIT_ACTIVABLE_CHECK → is shoot_activation_pool NOT empty ?
│   ├── YES → Current player is an AI player ?
│   │   └── NO → ⭐execute_action(game_state, unit, action, config) : STEP : UNIT_ACTIVATION → Human player → player activate one unit from shoot_activation_pool
│   │       ├── ⭐shooting_unit_activation_start()
│   │       │   ├── Clear any unit remaining in 📋 valid_target_pool
│   │       │   ├── Clear TOTAL_ATTACK log
│   │       │   ├── SHOOT_LEFT = RNG_NB
│   │       ├── ⭐_shooting_unit_execution_loop() : While SHOOT_LEFT > 0
│   │       │   ├── ⭐shooting_build_valid_target_pool() : Build 📋 valid_target_pool :
│   │       │   │   ├── selected target.player === current_player?
│   │       │   │   │   └── YES → ❌ Not a valid target
│   │       │   │   ├── Adjacent to friendly unit?
│   │       │   │   │   └── YES → ❌ Not a valid target
│   │       │   │   ├── ⭐_calculate_hex_distance() : target NOT within RNG_RNG distance ?
│   │       │   │   │   └── NO → ❌ Not a valid target
│   │       │   │   ├── ⭐_has_line_of_sight() : has NO LOS on the target ?
│   │       │   │   │   └── NO → ❌ Not a valid target
│   │       │   │   └── ALL conditions met → ✅ Add to 📋valid_target_pool
│   │       │   └── ⭐_is_valid_shooting_target() : valid_target_pool NOT empty ?
│   │       │       ├── YES → SHOOTING PHASE ACTIONS AVAILABLE
│   │       │       │   ├── ⭐shooting_preview() 
│   │       │       │   │   ├── Display the shooting preview (all the hexes with LoS and RNG_RNG are red)
│   │       │       │   │   └── Display the HP bar blinking animation for every unit in 📋valid_target_pool
│   │       │       │   └── ⭐shooting_click_handler() STEP : PLAYER_ACTION_SELECTION
│   │       │       │       ├── ACTION : Left click on a target in 📋valid_target_pool : ⭐shooting_target_selection_handler()
│   │       │       │       │   ├── Execute ⭐attack_sequence(RNG)
│   │       │       │       │   ├── SHOOT_LEFT -= 1
│   │       │       │       │   ├── Concatenate Return to TOTAL_ACTION log
│   │       │       │       │   ├── selected_target dies → Remove from 📋valid_target_pool, continue
│   │       │       │       │   ├── selected_target survives → Continue
│   │       │       │       │   └── AUTOMATIC RETURN: shooting_unit_execution_loop() called again
│   │       │       │       ├── ACTION : Left click on another unit in shoot_activation_pool ? ⭐_handle_unit_switch_with_context()
│   │       │       │       │   └── SHOOT_LEFT = RNG_NB ?
│   │       │       │       │       ├── YES → Postpone the shooting phase for this unit
│   │       │       │       │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK ⭐_is_valid_shooting_target()
│   │       │       │       │       └── NO → The unit must end its activation when started
│   │       │       │       │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │       │       │       ├── ACTION : Left click on the active_unit → No effect
│   │       │       │       ├── ACTION : Right click on the active_unit
│   │       │       │       │    └── SHOOT_LEFT = RNG_NB ?
│   │       │       │       │       ├── NO → ⭐end_activation() (ACTION, 1, SHOOTING, SHOOTING)
│   │       │       │       │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │       │       │       │       └── YES → ⭐end_activation() (WAIT, 1, PASS, SHOOTING)
│   │       │       │       │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │       │       │       └── ACTION : Left OR Right click anywhere else on the board
│   │       │       │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │       │       └── NO → SHOOT_LEFT = RNG_NB ?
│   │       │           ├── NO → shot the last target available in 📋valid_target_pool → ⭐end_activation() (ACTION, 1, SHOOTING, SHOOTING)
│   │       │           └── YES → no target available in 📋valid_target_pool at activation → no shoot → ⭐end_activation() (PASS, 1, PASS, SHOOTING)
│   │       └── End of shooting → ⭐end_activation() (ACTION, 1, SHOOTING, SHOOTING)
│   └── NO → ⭐shooting_phase_end()                                                                         **[NEW FUNCTION]**
│        ├── Final cleanup of phase state
│        ├── Console log: "SHOOTING PHASE COMPLETE"
│        └── RETURN: {"phase_complete": True, "next_phase": "charge"}
└── End of shooting phase → Advance to charge phase


SAUVEGARDE


│ELIGIBILITY & POOL BUILDING:
├── ⭐shooting_phase_start(game_state)                                                    **[NEW FUNCTION]**
│   ├── Set: game_state["phase"] = "shoot"
│   ├── ⭐shooting_build_activation_pool(game_state)
│   │   └── For each PLAYER unit → ELIGIBILITY CHECK:
│   │       │   ├── unit.HP_CUR > 0? → NO → ❌ → Skip
│   │       │   ├── unit.player === current_player? → NO → ❌ → Skip  
│   │       │   ├── units_fled.includes(unit.id)? → YES → ❌ → Skip
│   │       │   ├── Adjacent to enemy within CC_RNG? → YES → ❌ → Skip
│   │       │   ├── unit.RNG_NB > 0? → NO → ❌ → Skip
│   │       │   ├── Has LOS to enemies within RNG_RNG? → NO → ❌ → Skip
│   │       │   └── ALL PASSED → ✅ Add to shoot_activation_pool
│   │       └── 📋Updates: game_state["shoot_activation_pool"] = [eligible_unit_ids]
│   │           └── Highlight the units in shoot_activation_pool with a green circle around its icon
│   ├── Add console log: "SHOOT POOL BUILT"
│   └── Enter UNIT_ACTIVABLE_CHECK loop
│
│
├── ⭐_is_valid_shooting_unit() : STEP : UNIT_ACTIVABLE_CHECK → is shoot_activation_pool NOT empty ?
│   ├── YES → Current player is an AI player ?
│   │   └── NO → Human player → ⭐shooting_unit_activation_controller() : STEP : UNIT_ACTIVATION → player activate one unit from shoot_activation_pool by left clicking on it
│   │       ├── ⭐shooting_unit_activation_start()
│   │       │   ├── Clear any unit remaining in 📋 valid_target_pool
│   │       │   ├── Clear TOTAL_ATTACK log
│   │       │   ├── SHOOT_LEFT = RNG_NB
│   │       ├── ⭐_shooting_unit_execution_loop() : While SHOOT_LEFT > 0
│   │       │   ├── ⭐shooting_build_valid_target_pool() : Build 📋 valid_target_pool :
│   │       │   │   ├── selected target.player === current_player?
│   │       │   │   │   └── YES → ❌ Not a valid target
│   │       │   │   ├── Adjacent to friendly unit?
│   │       │   │   │   └── YES → ❌ Not a valid target
│   │       │   │   ├── ⭐_calculate_hex_distance() : target NOT within RNG_RNG distance ?
│   │       │   │   │   └── NO → ❌ Not a valid target
│   │       │   │   ├── ⭐_has_line_of_sight() : has NO LOS on the target ?
│   │       │   │   │   └── NO → ❌ Not a valid target
│   │       │   │   └── ALL conditions met → ✅ Add to 📋valid_target_pool
│   │       │   └── ⭐_is_valid_shooting_target() : valid_target_pool NOT empty ?
│   │       │       ├── YES → SHOOTING PHASE ACTIONS AVAILABLE
│   │       │       │   ├── ⭐shooting_preview() 
│   │       │       │   │   ├── Display the shooting preview (all the hexes with LoS and RNG_RNG are red)
│   │       │       │   │   └── Display the HP bar blinking animation for every unit in 📋valid_target_pool
│   │       │       │   └── ⭐execute_action(game_state, unit, action, config)STEP : PLAYER_ACTION_SELECTION
│   │       │       │       ├── ACTION : Left click on a target in 📋valid_target_pool : ⭐shooting_target_selection_handler()
│   │       │       │       │   ├── Execute ⭐attack_sequence(RNG)
│   │       │       │       │   ├── SHOOT_LEFT -= 1
│   │       │       │       │   ├── Concatenate Return to TOTAL_ACTION log
│   │       │       │       │   ├── selected_target dies → Remove from 📋valid_target_pool, continue
│   │       │       │       │   ├── selected_target survives → Continue
│   │       │       │       │   └── AUTOMATIC RETURN: shooting_unit_execution_loop() called again
│   │       │       │       ├── ACTION : Left click on another unit in shoot_activation_pool ? ⭐_handle_unit_switch_with_context()
│   │       │       │       │   └── SHOOT_LEFT = RNG_NB ?
│   │       │       │       │       ├── YES → Postpone the shooting phase for this unit
│   │       │       │       │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK ⭐_is_valid_shooting_target()
│   │       │       │       │       └── NO → The unit must end its activation when started
│   │       │       │       │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │       │       │       ├── ACTION : Left click on the active_unit → No effect
│   │       │       │       ├── ACTION : Right click on the active_unit
│   │       │       │       │    └── SHOOT_LEFT = RNG_NB ?
│   │       │       │       │       ├── NO → ⭐end_activation() (ACTION, 1, SHOOTING, SHOOTING)
│   │       │       │       │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │       │       │       │       └── YES → ⭐end_activation() (WAIT, 1, PASS, SHOOTING)
│   │       │       │       │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │       │       │       └── ACTION : Left OR Right click anywhere else on the board
│   │       │       │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │       │       └── NO → SHOOT_LEFT = RNG_NB ?
│   │       │           ├── NO → shot the last target available in 📋valid_target_pool → ⭐end_activation() (ACTION, 1, SHOOTING, SHOOTING)
│   │       │           └── YES → no target available in 📋valid_target_pool at activation → no shoot → ⭐end_activation() (PASS, 1, PASS, SHOOTING)
│   │       └── End of shooting → ⭐end_activation() (ACTION, 1, SHOOTING, SHOOTING)
│   └── NO → ⭐shooting_phase_end()                                                                         **[NEW FUNCTION]**
│        ├── Final cleanup of phase state
│        ├── Console log: "SHOOTING PHASE COMPLETE"
│        └── RETURN: {"phase_complete": True, "next_phase": "charge"}
└── End of shooting phase → Advance to charge phase
```