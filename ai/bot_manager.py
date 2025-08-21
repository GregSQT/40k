# ai/bot_manager.py
#!/usr/bin/env python3
"""
ai/bot_manager.py - Centralized bot/enemy AI management with proper action logging
"""

import copy
from typing import List, Dict, Optional, Tuple
from shared.gameRules import execute_shooting_sequence, execute_combat_sequence

class BotManager:
    """Centralized management for enemy/bot AI behavior with proper logging integration."""
    
    def __init__(self, env):
        """Initialize bot manager with environment reference."""
        self.env = env
        self.quiet = getattr(env, 'quiet', False)
        # Ensure we have access to current_phase for logging
        if not hasattr(env, 'current_phase'):
            raise AttributeError("Environment must have 'current_phase' attribute for BotManager")
        
    def execute_bot_turn(self) -> bool:
        """Execute complete bot turn for current phase with proper logging."""
        if not hasattr(self.env, 'unit_manager'):
            if not self.quiet:
                print(f"❌ BotManager: No unit_manager available")
            return False
            
        enemy_units = self.env.unit_manager.get_alive_enemy_units()
        if not enemy_units:
            if not self.quiet:
                print(f"🤖 BotManager: No enemy units to act")
            return False
            
        if not self.quiet:
            print(f"🤖 BotManager: {len(enemy_units)} enemy units in {self.env.training_state.game_state["phase"]} phase")
            
        actions_executed = 0
        
        for enemy in enemy_units[:]:  # Use slice to avoid modification during iteration
            if not self.env.unit_manager.is_target_valid(enemy):
                if not self.quiet:
                    print(f"🤖 BotManager: Unit {enemy.get('id')} not valid target")
                continue
                
            # Execute phase-specific action with proper logging
            action_executed = self._execute_bot_phase_action(enemy)
            if action_executed:
                actions_executed += 1
            elif not self.quiet:
                print(f"🤖 BotManager: Unit {enemy.get('id')} no action executed")
                
        if not self.quiet:
            print(f"🤖 BotManager: Completed turn with {actions_executed} actions")
            
        return actions_executed > 0
        
    def _execute_bot_phase_action(self, bot_unit: Dict) -> bool:
        """Execute single bot action for current phase with logging."""
        phase = self.env.training_state.game_state["phase"]
        reward = 0.0  # Initialize reward at start
        
        # Store pre-action state for logging
        pre_action_units = copy.deepcopy(self.env.unit_manager.units) if hasattr(self.env, 'unit_manager') else []
        
        # Find best target for this bot
        target = self._get_best_target(bot_unit)
        if not target:
            if not self.quiet:
                print(f"🤖 Unit {bot_unit.get('id')}: No target found in {phase} phase")
            # Still execute wait action and log it
            action_executed = True
            action_type = 7  # Wait
            reward = 0.0
        else:
            if not self.quiet:
                print(f"🤖 Unit {bot_unit.get('id')}: Target {target.get('id')} found in {phase} phase")
            
            action_executed = False
            action_type = 7  # Default to wait
            
            # Execute phase-specific behavior
            if phase == "move":
                action_executed, action_type = self._bot_move_action(bot_unit, target)
            elif phase == "shoot":
                action_executed, action_type = self._bot_shoot_action(bot_unit, target)
            elif phase == "charge":
                action_executed, action_type = self._bot_charge_action(bot_unit, target)
            elif phase == "combat":
                action_executed, action_type = self._bot_combat_action(bot_unit, target)
            
            if not action_executed:
                # Fallback to wait if no action succeeded
                action_executed = True
                action_type = 7
                reward = 0.0
                if not self.quiet:
                    print(f"🤖 Unit {bot_unit.get('id')}: Falling back to wait action")
            
        # Log action through same system as AI actions
        if hasattr(self.env, 'replay_logger') and self.env.replay_logger:
            try:
                post_action_units = copy.deepcopy(self.env.unit_manager.units) if hasattr(self.env, 'unit_manager') else []
                
                # CRITICAL: Log to combat_log first (same as AI actions)
                self.env.replay_logger.log_action(
                    action=action_type,
                    reward=reward,
                    pre_action_units=pre_action_units,
                    post_action_units=post_action_units,
                    acting_unit_id=bot_unit.get('id'),
                    target_unit_id=target.get('id') if target else None,
                    description=f"Bot unit {bot_unit.get('id')} performs {self._get_action_name(action_type)}"
                )
                
                # Create action ID in same format as AI (unit_index * 8 + action_type)
                bot_units = self.env.unit_manager.get_alive_enemy_units()
                unit_index = next((i for i, u in enumerate(bot_units) if u.get('id') == bot_unit.get('id')), 0)
                action_id = unit_index * 8 + action_type
                
                # Manual game state creation (same as AI actions)
                self._create_bot_game_state(bot_unit, target, action_id, action_type, reward)
                
                if not self.quiet:
                    print(f"🤖 Unit {bot_unit.get('id')}: Logged {self._get_action_name(action_type)} action")
                
            except Exception as e:
                if not self.quiet:
                    print(f"⚠️ Bot action logging failed: {e}")
                    import traceback
                    traceback.print_exc()
                if not self.quiet:
                    print(f"⚠️ Bot action logging failed: {e}")
                    import traceback
                    traceback.print_exc()
                    
        return action_executed
        
    def _create_bot_game_state(self, bot_unit: Dict, target: Optional[Dict], action_id: int, action_type: int, reward: float):
        """Create game state snapshot for bot action"""
        try:
            if not hasattr(self.env.replay_logger, 'game_states'):
                self.env.replay_logger.game_states = []
                
            # Create units data with current positions
            units_data = []
            for unit_snapshot in self.env.unit_manager.units:
                # Validate required fields exist - no defaults allowed
                if 'id' not in unit_snapshot:
                    raise ValueError(f"Unit missing required 'id' field")
                if 'unit_type' not in unit_snapshot:
                    raise ValueError(f"Unit {unit_snapshot['id']} missing required 'unit_type' field")
                if 'player' not in unit_snapshot:
                    raise ValueError(f"Unit {unit_snapshot['id']} missing required 'player' field")
                if 'row' not in unit_snapshot:
                    raise ValueError(f"Unit {unit_snapshot['id']} missing required 'row' field")
                if 'col' not in unit_snapshot:
                    raise ValueError(f"Unit {unit_snapshot['id']} missing required 'col' field")
                if 'HP' not in unit_snapshot:
                    raise ValueError(f"Unit {unit_snapshot['id']} missing required 'HP' field")
                if 'alive' not in unit_snapshot:
                    raise ValueError(f"Unit {unit_snapshot['id']} missing required 'alive' field")
                
                unit_data = {
                    "id": unit_snapshot['id'],
                    "name": unit_snapshot.get("name", f"{unit_snapshot['unit_type']} {unit_snapshot['id']+1}"),
                    "unit_type": unit_snapshot['unit_type'],
                    "player": unit_snapshot['player'],
                    "row": unit_snapshot['row'],
                    "col": unit_snapshot['col'],
                    "HP": unit_snapshot['HP'],
                    "alive": unit_snapshot['alive']
                }
                units_data.append(unit_data)
                
            # Create state snapshot
            state = {
                "turn": self.env.training_state.game_state["current_turn"],
                "phase": self.env.training_state.game_state["phase"],
                "active_player": self.env.training_state.game_state["current_player"],
                "units": units_data,
                "board_state": {
                    "width": self.env.board_size[0],
                    "height": self.env.board_size[1]
                },
                "event_flags": {
                    "action_id": action_id,
                    "acting_unit_id": bot_unit.get('id'),
                    "target_unit_id": target.get('id') if target else None,
                    "reward": reward,
                    "description": f"Bot unit {bot_unit.get('id')} performs {self._get_action_name(action_type)}",
                    "step_number": len(self.env.replay_logger.game_states) + 1
                }
            }
            
            self.env.replay_logger.game_states.append(state)
            
        except Exception as e:
            if not self.quiet:
                print(f"❌ Bot game state creation failed: {e}")
                
    def _bot_move_action(self, bot_unit: Dict, target: Dict) -> Tuple[bool, int]:
        """Execute bot movement action."""
        distance = self._get_hex_distance(bot_unit, target)
        
        # Don't move if already adjacent or in optimal position
        if distance <= 1:
            return False, 7  # Wait
            
        bot_range = bot_unit.get("rng_rng", 1)
        if distance <= bot_range and bot_unit.get("rng_dmg", 0) > 0:
            return False, 7  # In shooting range, wait
            
        # Calculate target position
        old_col, old_row = bot_unit["col"], bot_unit["row"]
        target_col, target_row = self._calculate_bot_target_position(bot_unit, target)
        
        # Use environment's movement validation
        movement_succeeded = self.env._execute_validated_movement(bot_unit, target_col, target_row)
        
        if not movement_succeeded:
            return False, 7  # Path blocked, wait
            
        # Determine action type based on movement direction
        if target_row < old_row:
            action_type = 0  # move_north
        elif target_row > old_row:
            action_type = 1  # move_south
        elif target_col > old_col:
            action_type = 2  # move_east
        elif target_col < old_col:
            action_type = 3  # move_west
        else:
            action_type = 7  # wait (no movement)
            
        return True, action_type
        
    def _bot_shoot_action(self, bot_unit: Dict, target: Dict) -> Tuple[bool, int]:
        """Execute bot shooting action with target validation."""
        # CRITICAL: Multi-level target validation to prevent shooting dead units
        if not self._is_target_valid(target):
            if not self.quiet:
                print(f"🤖 Bot unit {bot_unit.get('id')}: Target {target.get('id')} invalid - first check")
            return False, 7  # Target died, fallback to wait
        
        # CRITICAL: Second validation using UnitManager (authoritative source)
        if hasattr(self.env, 'unit_manager') and not self.env.unit_manager.is_target_valid(target):
            if not self.quiet:
                print(f"🤖 Bot unit {bot_unit.get('id')}: Target {target.get('id')} invalid - UnitManager check")
            return False, 7  # Target died, fallback to wait
        
        bot_range = bot_unit.get("rng_rng", 1)
        bot_damage = bot_unit.get("rng_dmg", 1)
        
        if bot_damage <= 0:
            return False, 7  # No ranged weapons
            
        distance = self._get_hex_distance(bot_unit, target)
        if distance > bot_range or distance <= 1:
            return False, 7  # Out of range or too close
            
        # Execute shooting through shared system
        result = execute_shooting_sequence(bot_unit, target)
        self.env.unit_manager.apply_shooting_damage(bot_unit, target, result)
        
        return True, 4  # shoot action
        
    def _bot_charge_action(self, bot_unit: Dict, target: Dict) -> Tuple[bool, int]:
        """Execute bot charge action with target validation."""
        # CRITICAL: Validate target before charging
        if not self._is_target_valid(target):
            return False, 7  # Target died, fallback to wait
        
        distance = self._get_hex_distance(bot_unit, target)
        move_range = bot_unit.get("move", 6)
        
        if distance <= 1 or distance > move_range:
            return False, 7  # Already adjacent or out of range
            
        # Find adjacent position and move there
        old_col, old_row = bot_unit["col"], bot_unit["row"]
        adjacent_positions = [
            (target["col"] + 1, target["row"]),
            (target["col"] - 1, target["row"]),
            (target["col"], target["row"] + 1),
            (target["col"], target["row"] - 1)
        ]
        
        # Find valid adjacent position
        for target_col, target_row in adjacent_positions:
            if (0 <= target_col < self.env.board_size[0] and 
                0 <= target_row < self.env.board_size[1]):
                if self.env._execute_validated_movement(bot_unit, target_col, target_row):
                    return True, 5  # charge action
                    
        return False, 7  # Charge failed
        
    def _bot_combat_action(self, bot_unit: Dict, target: Dict) -> Tuple[bool, int]:
        """Execute bot combat action with target validation."""
        # CRITICAL: Validate target before attacking
        if not self._is_target_valid(target):
            return False, 7  # Target died, fallback to wait
        
        combat_range = bot_unit.get("cc_rng", 1)
        combat_damage = bot_unit.get("cc_dmg", 1)
        
        if combat_damage <= 0:
            return False, 7  # No melee weapons
            
        distance = self._get_hex_distance(bot_unit, target)
        if distance > combat_range:
            return False, 7  # Out of combat range
            
        # Execute combat through shared system
        result = execute_combat_sequence(bot_unit, target)
        self.env.unit_manager.apply_combat_damage(bot_unit, target, result)
        
        return True, 6  # attack action
        
    def _get_best_target(self, bot_unit: Dict) -> Optional[Dict]:
        """Get best target for bot unit with phase-specific logic."""
        ai_units = self.env.unit_manager.get_alive_ai_units()
        if not ai_units:
            if not self.quiet:
                print(f"🤖 Unit {bot_unit.get('id')}: No AI units found")
            return None
        
        phase = self.env.training_state.game_state["phase"]
        
        # Phase-specific target selection
        if phase == "move":
            # In move phase, target nearest AI unit
            target = min(ai_units, key=lambda u: self._get_hex_distance(bot_unit, u))
        elif phase == "shoot":
            # In shoot phase, target units in shooting range
            in_range = [u for u in ai_units if self._get_hex_distance(bot_unit, u) <= bot_unit.get("rng_rng", 1)]
            if in_range:
                for unit in in_range:
                    if 'HP' not in unit:
                        raise ValueError(f"Unit {unit.get('id', 'unknown')} missing required 'HP' field")
                target = min(in_range, key=lambda u: u['HP'])  # Lowest HP in range
            else:
                target = min(ai_units, key=lambda u: self._get_hex_distance(bot_unit, u))  # Nearest
        elif phase == "charge":
            # In charge phase, target units within charge range
            move_range = bot_unit.get("move", 6)
            chargeable = [u for u in ai_units if 1 < self._get_hex_distance(bot_unit, u) <= move_range]
            if chargeable:
                for unit in chargeable:
                    if 'HP' not in unit:
                        raise ValueError(f"Unit {unit.get('id', 'unknown')} missing required 'HP' field")
                target = min(chargeable, key=lambda u: u['HP'])  # Lowest HP chargeable
            else:
                target = None  # No chargeable targets
        elif phase == "combat":
            # In combat phase, target adjacent units
            adjacent = [u for u in ai_units if self._get_hex_distance(bot_unit, u) <= bot_unit.get("cc_rng", 1)]
            if adjacent:
                for unit in adjacent:
                    if 'HP' not in unit:
                        raise ValueError(f"Unit {unit.get('id', 'unknown')} missing required 'HP' field")
                target = min(adjacent, key=lambda u: u['HP'])  # Lowest HP adjacent
            else:
                target = None  # No adjacent targets
        else:
            # Default: nearest unit
            target = min(ai_units, key=lambda u: self._get_hex_distance(bot_unit, u))
        
        if not self.quiet and target:
            distance = self._get_hex_distance(bot_unit, target)
            print(f"🤖 Unit {bot_unit.get('id')}: Selected target {target.get('id')} at distance {distance}")
        elif not self.quiet:
            print(f"🤖 Unit {bot_unit.get('id')}: No valid target for {phase} phase")
            
        return target
        
    def _get_hex_distance(self, unit1: Dict, unit2: Dict) -> int:
        """Calculate hex distance between units."""
        return max(abs(unit1["col"] - unit2["col"]), abs(unit1["row"] - unit2["row"]))
        
    def _calculate_bot_target_position(self, bot_unit: Dict, target: Dict) -> Tuple[int, int]:
        """Calculate where bot wants to move (same logic as existing method)."""
        dx = target["col"] - bot_unit["col"]
        dy = target["row"] - bot_unit["row"]
        move_distance = bot_unit.get("move", 6)
        
        if abs(dx) > abs(dy):
            step = min(move_distance, abs(dx)) * (1 if dx > 0 else -1)
            target_col = max(0, min(self.env.board_size[0] - 1, bot_unit["col"] + step))
            target_row = bot_unit["row"]
        else:
            step = min(move_distance, abs(dy)) * (1 if dy > 0 else -1)
            target_col = bot_unit["col"]
            target_row = max(0, min(self.env.board_size[1] - 1, bot_unit["row"] + step))
            
        return target_col, target_row
        
    def _get_action_name(self, action_type: int) -> str:
        """Get human-readable action name."""
        action_names = {
            0: "move_north", 1: "move_south", 2: "move_east", 3: "move_west",
            4: "shoot", 5: "charge", 6: "attack", 7: "wait"
        }
        return action_names.get(action_type, f"action_{action_type}")
    
    def _is_target_valid(self, target):
        """Validate that target is still alive and attackable."""
        if not target:
            return False
        
        # Check basic validity
        if 'HP' not in target:
            raise ValueError(f"Target unit missing required 'HP' field")
        if 'alive' not in target:
            raise ValueError(f"Target unit missing required 'alive' field")
        CUR_HP = target['HP']
        alive = target['alive']
        
        if CUR_HP <= 0:
            return False
        if not alive:
            return False
        
        # Verify target still exists in environment
        if hasattr(self.env, 'unit_manager'):
            return self.env.unit_manager.is_target_valid(target)
        
        return True