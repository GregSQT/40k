#!/usr/bin/env python3
"""
ai/replay_converter.py - Steplog to replay conversion functions

Contains:
- resolve_agent_bot_scenario: Resolve the bot scenario a replay must be rebuilt against
- convert_steplog_to_replay: Convert existing steplog file to replay JSON
- generate_steplog_and_replay: Generate steplog and replay from training run
- parse_steplog_file: Parse steplog file into structured data
- parse_action_message: Parse action message from steplog
- calculate_episode_reward_from_actions: Calculate episode reward from actions
- convert_to_replay_format: Convert steplog data to replay JSON format

Extracted from ai/train.py during refactoring (2025-01-21)
"""

import os
import re
import json
from datetime import datetime

from shared.data_validation import require_key

# Import required modules for generate_steplog_and_replay
from ai.step_logger import StepLogger
from ai.training_utils import setup_imports
from config_loader import get_config_loader
from sb3_contrib import MaskablePPO  # CRITICAL: Use MaskablePPO, not PPO - all trained models use action masking

__all__ = [
    'resolve_agent_bot_scenario',
    'convert_steplog_to_replay',
    'generate_steplog_and_replay',
    'parse_steplog_file',
    'parse_action_message',
    'calculate_episode_reward_from_actions',
    'convert_to_replay_format'
]

def resolve_agent_bot_scenario(config, agent_name):
    """Resolve the bot scenario file a replay must be rebuilt against, for one agent.

    Le replay reconstruit l'etat initial depuis le scenario : sans lui, il ne connait ni
    les unites ni leurs positions de depart. Il n'y a donc pas de valeur par defaut
    possible — l'appelant doit fournir un agent.
    """
    if not agent_name:
        raise ValueError("--agent required: the replay needs the agent's bot scenario to rebuild unit data")

    from ai.training_utils import get_scenario_list_for_phase

    scenario_list = get_scenario_list_for_phase(config, agent_name, "bot")
    if not scenario_list:
        raise RuntimeError(f"No bot scenarios found for agent {agent_name}")

    return scenario_list[0]

def convert_steplog_to_replay(steplog_path, scenario_file):
    """Convert existing steplog file to replay JSON format.

    Args:
        steplog_path: steplog file to parse.
        scenario_file: scenario the steplog was produced on, used to rebuild the initial state.
    """
    import re
    from datetime import datetime

    if not os.path.exists(steplog_path):
        raise FileNotFoundError(f"Steplog file not found: {steplog_path}")

    print(f"🔄 Converting steplog: {steplog_path}")

    # Parse steplog file
    steplog_data = parse_steplog_file(steplog_path)

    # Convert to replay format
    replay_data = convert_to_replay_format(steplog_data, scenario_file)

    # Nom de sortie constant. `extract_scenario_name_for_replay()` occupait cette ligne :
    # elle consultait deux attributs de fonction (`_current_template_name` sur elle-meme,
    # `_detected_template_name` sur `convert_to_replay_format`) censes porter un nom de
    # "scenario template". Aucun code de production n'a jamais ecrit ces attributs — seuls
    # les tests les posaient — donc la fonction retournait toujours "scenario". Les templates
    # de scenarios ont disparu avec le ScenarioManager ; il n'y a plus rien a lire.
    output_file = "ai/event_log/replay_scenario.json"

    # Ensure output directory exists
    os.makedirs("ai/event_log", exist_ok=True)
    
    # Save replay file
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(replay_data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Conversion complete: {output_file}")
    print(f"   📊 {len(require_key(replay_data, 'combat_log'))} combat log entries")
    print(f"   🎯 {len(require_key(replay_data, 'game_states'))} game state snapshots")
    game_info = require_key(replay_data, 'game_info')
    print(f"   🎮 {require_key(game_info, 'total_turns')} turns")
    
    return True

def generate_steplog_and_replay(config, args):
    """Generate steplog AND convert to replay in one command - the perfect workflow!"""
    from datetime import datetime
    
    print("🎮 W40K Replay Generator - One-Shot Workflow")
    print("=" * 50)

    # Ressource a rendre QUOI QU'IL ARRIVE : le `except Exception` en fin de fonction convertit
    # toute erreur en `return False`, donc un `env.close()` place dans le chemin nominal etait
    # saute des qu'une erreur survenait dans la boucle d'episodes.
    env = None

    try:
        if not args.agent:
            raise ValueError("--agent required to read step_log_buffer_size from agent training config")
        from shared.data_validation import require_key
        tc = config.load_agent_training_config(args.agent, args.training_config or "default")
        step_log_buffer_size = require_key(tc, "step_log_buffer_size")
        # Step 1: Enable step logging temporarily
        temp_steplog = "temp_steplog_for_replay.log"
        temp_step_logger = StepLogger(temp_steplog, enabled=True, buffer_size=step_log_buffer_size)

        # Step 2: Load model for testing
        print("🎯 Loading model for steplog generation...")
        
        # Use explicit model path if provided, otherwise use config default
        if args.model:
            model_path = args.model
            if not os.path.exists(model_path):
                raise FileNotFoundError(f"Specified model not found: {model_path}")
        else:
            models_root = config.get_models_root()
            model_path = os.path.join(models_root, args.agent, f"model_{args.agent}.zip")
            if not os.path.exists(model_path):
                # List available models for user guidance
                models_dir = os.path.dirname(model_path)
                if os.path.exists(models_dir):
                    available_models = [f for f in os.listdir(models_dir) if f.endswith('.zip')]
                    if available_models:
                        raise FileNotFoundError(f"Default model not found: {model_path}\nAvailable models in {models_dir}: {available_models}\nUse --model to specify a model file")
                    else:
                        raise FileNotFoundError(f"Default model not found: {model_path}\nNo models found in {models_dir}")
                else:
                    raise FileNotFoundError(f"Default model not found: {model_path}\nModels directory does not exist: {models_dir}")
        
        W40KEngine, _ = setup_imports()
        from ai.unit_registry import UnitRegistry
        unit_registry = UnitRegistry()
        
        # Use actual bot scenarios instead of generating dynamic ones
        # This ensures the scenario matches what the model was trained on
        bot_scenario_file = resolve_agent_bot_scenario(config, args.agent)
        print(f"Using bot scenario: {os.path.basename(bot_scenario_file)}")

        # Test-only mode requires agent parameter
        if not args.agent:
            raise ValueError("--agent parameter required for test-only mode")
        # La duree de bataille vient de game_rules.max_turns (source unique). L'ancien
        # override temporaire, qui recopiait 'max_turns_per_episode' du training config
        # dans game_rules le temps de construire l'env, n'a plus d'objet.
        print(f"🎯 Battle length: {config.get_max_turns()} turns (game_rules.max_turns)")

        env = W40KEngine(
            rewards_config=args.rewards_config,
            training_config_name=args.training_config,
            controlled_agent=args.agent,  # Required for agent-specific rewards
            active_agents=None,
            scenario_file=bot_scenario_file,
            unit_registry=unit_registry,
            quiet=True,
            gym_training_mode=True,
            training_n_envs=1,  # UN environnement, joue en serie
        )

        # Connect step logger directly to W40KEngine — SEUL branchement necessaire.
        # Un `globals()['step_logger'] = temp_step_logger` l'accompagnait, sauvegarde puis
        # restauree : ce global n'etait lu NULLE PART (ni ici, ni ailleurs dans le depot), et sur
        # un process neuf la « restauration » ecrivait None dans un attribut qui n'existait pas.
        # Ne pas le remettre : c'est cette ligne-ci qui alimente le steplog.
        env.step_logger = temp_step_logger
        model = MaskablePPO.load(model_path, env=env)
        
        # Step 3: Run test episodes with step logging
        if not hasattr(args, 'test_episodes') or args.test_episodes is None:
            raise ValueError("--test-episodes required for replay generation - no default episodes allowed")
        episodes = args.test_episodes
        print(f"🎲 Running {episodes} episodes with step logging...")
        
        for episode in range(episodes):
            print(f"   Episode {episode + 1}/{episodes}")
            obs, info = env.reset()
            done = False
            step_count = 0
            
            while not done and step_count < 1000:
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, info = env.step(int(action))
                if obs is None:
                    # `W40KEngine.step` ne rend `None` que si l'appelant a arme
                    # `defer_observation` (report d'observation du wrapper d'entrainement).
                    # Ici le moteur est pilote NU, sans BotControlledEnv : le report n'est
                    # jamais arme et personne ne construirait l'observation a notre place.
                    raise RuntimeError(
                        "replay_converter: W40KEngine.step a rendu une observation None alors "
                        "que le report n'est pas arme — contrat de _step_observation rompu."
                    )
                done = terminated or truncated
                step_count += 1

        # Step 4: Convert steplog to replay
        print("🔄 Converting steplog to replay format...")
        
        success = convert_steplog_to_replay(temp_steplog, bot_scenario_file)

        # Step 5: Cleanup temporary files
        if os.path.exists(temp_steplog):
            os.remove(temp_steplog)
            print("🧹 Cleaned up temporary steplog file")

        # Le scenario n'est PAS supprime ici. Ce bloc effacait autrefois un scenario genere a
        # la volee ; depuis que la source est `get_scenario_list_for_phase`, le chemin designe
        # un vrai fichier versionne de config/agents/<agent>/scenarios/training/ — le supprimer
        # amputait le jeu d'entrainement. Le nettoyage du contexte de template a disparu avec
        # les attributs de fonction qui le portaient : l'etat passe maintenant par parametre.

        if success:
            print("✅ One-shot replay generation complete!")
            return True
        else:
            print("❌ Replay conversion failed")
            return False

    except Exception as e:
        print(f"❌ One-shot workflow failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if env is not None:
            env.close()

def parse_steplog_file(steplog_path):
    """Parse steplog file and extract structured data."""
    import re
    
    print(f"📖 Parsing steplog file...")
    
    with open(steplog_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    lines = content.strip().split('\n')
    
    # Skip header lines (everything before first action)
    action_lines = []
    in_actions = False
    
    for line in lines:
        if line.startswith('[') and '] T' in line:
            in_actions = True
        if in_actions:
            action_lines.append(line)
    
    # Parse action entries
    actions = []
    max_turn = 1
    units_positions = {}
    
    # Regex patterns for parsing
    action_pattern = r'\[([^\]]+)\] T(\d+) P(\d+) (\w+) : (.+?) \[(SUCCESS|FAILED)\](?: \[STEP: (YES|NO)\])?'
    phase_pattern = r'\[([^\]]+)\] T(\d+) P(\d+) (\w+) phase Start'
    
    for line in action_lines:
        # Try to match action pattern
        action_match = re.match(action_pattern, line)
        if action_match:
            timestamp, turn, player, phase, message, success, step_increment = action_match.groups()
            step_increment_flag = step_increment == 'YES' if step_increment is not None else True
            
            # Parse action details from message
            action_data = parse_action_message(message, {
                'timestamp': timestamp,
                'turn': int(turn),
                'player': int(player), 
                'phase': phase.lower(),
                'success': success == 'SUCCESS',
                'step_increment': step_increment_flag
            })
            
            if action_data:
                actions.append(action_data)
                max_turn = max(max_turn, int(turn))
                
                # Update unit positions from ALL actions (move, shoot, combat, charge, wait)
                unit_id = action_data.get('unitId')
                if unit_id:
                    # Try to extract position from action message if available
                    position_extracted = False
                    
                    if action_data['type'] == 'move' and 'startHex' in action_data and 'endHex' in action_data:
                        # Parse coordinates from "(col, row)" format
                        import re
                        end_match = re.match(r'\((\d+),\s*(\d+)\)', action_data['endHex'])
                        if end_match:
                            end_col, end_row = end_match.groups()
                            units_positions[unit_id] = {
                                'col': int(end_col),
                                'row': int(end_row),
                                'last_seen_turn': int(turn)
                            }
                            position_extracted = True
                    
                    # For non-move actions, try to extract position from message format
                    if not position_extracted and 'message' in action_data:
                        import re
                        # Look for "Unit X(col, row)" pattern in any message
                        pos_match = re.search(r'Unit \d+\((\d+), (\d+)\)', action_data['message'])
                        if pos_match:
                            col, row = pos_match.groups()
                            units_positions[unit_id] = {
                                'col': int(col),
                                'row': int(row),
                                'last_seen_turn': int(turn)
                            }
                            position_extracted = True
        
        # Try to match phase change pattern  
        phase_match = re.match(phase_pattern, line)
        if phase_match:
            timestamp, turn, player, phase = phase_match.groups()
            
            phase_data = {
                'type': 'phase_change',
                'message': f'{phase.capitalize()} phase Start',
                'turnNumber': int(turn),
                'phase': phase.lower(),
                'player': int(player),
                'timestamp': timestamp
            }
            actions.append(phase_data)
    
    print(f"   📝 Parsed {len(actions)} action entries")
    print(f"   🎮 {max_turn} total turns detected")
    print(f"   👥 {len(units_positions)} units tracked")
    
    return {
        'actions': actions,
        'max_turn': max_turn,
        'units_positions': units_positions
    }

def parse_action_message(message, context):
    """Parse action message and extract details."""
    import re
    
    action_type = None
    details = {
        'turnNumber': context['turn'],
        'phase': context['phase'],
        'player': context['player'],
        'timestamp': context['timestamp']
    }
    
    # Parse different action types based on message content
    if "MOVED from" in message:
        # Unit X(col, row) MOVED from (start_col, start_row) to (end_col, end_row)
        move_match = re.match(r'Unit (\d+)\((\d+), (\d+)\) MOVED from \((\d+), (\d+)\) to \((\d+), (\d+)\)', message)
        if move_match:
            unit_id, _, _, start_col, start_row, end_col, end_row = move_match.groups()
            action_type = 'move'
            details.update({
                'type': action_type,
                'message': message,
                'unitId': int(unit_id),
                'startHex': f"({start_col}, {start_row})",
                'endHex': f"({end_col}, {end_row})"
            })
    
    elif "SHOT Unit" in message:
        # Unit X(col, row) SHOT Unit Y - details...
        shoot_match = re.match(r'Unit (\d+)\([^)]+\) SHOT(?: \[[^\]]+\])*\s+Unit (\d+)', message)
        if shoot_match:
            unit_id, target_id = shoot_match.groups()
            action_type = 'shoot'
            details.update({
                'type': action_type,
                'message': message,
                'unitId': int(unit_id),
                'targetUnitId': int(target_id)
            })
    
    elif "FOUGHT" in message:
        # Unit X(col, row) FOUGHT Unit Y - details...
        combat_match = re.match(r'Unit (\d+)\([^)]+\) FOUGHT Unit (\d+)', message)
        if combat_match:
            unit_id, target_id = combat_match.groups()
            action_type = 'combat'
            details.update({
                'type': action_type,
                'message': message,
                'unitId': int(unit_id),
                'targetUnitId': int(target_id)
            })
    
    elif "CHARGED" in message:
        # Unit X(col, row) CHARGED Unit Y from (start) to (end)
        charge_match = re.match(r'Unit (\d+)\([^)]+\) CHARGED Unit (\d+)', message)
        if charge_match:
            unit_id, target_id = charge_match.groups()
            action_type = 'charge'
            details.update({
                'type': action_type,
                'message': message,
                'unitId': int(unit_id),
                'targetUnitId': int(target_id)
            })
    
    elif "WAIT" in message:
        # Unit X(col, row) WAIT
        wait_match = re.match(r'Unit (\d+)\([^)]+\) WAIT', message)
        if wait_match:
            unit_id = wait_match.groups()[0]
            action_type = 'wait'
            details.update({
                'type': action_type,
                'message': message,
                'unitId': int(unit_id)
            })
    
    return details if action_type else None

def calculate_episode_reward_from_actions(actions, winner):
    """Calculate episode reward from action log and winner."""
    # Simple reward calculation based on winner and action count
    if winner is None:
        return 0.0
    
    # Basic reward: winner gets positive, loser gets negative
    base_reward = 10.0 if winner == 0 else -10.0
    
    # Add small bonus/penalty based on action efficiency
    action_count = len([a for a in actions if a.get('type') != 'phase_change'])
    efficiency_bonus = max(-5.0, min(5.0, (50 - action_count) * 0.1))
    
    return base_reward + efficiency_bonus

def convert_to_replay_format(steplog_data, scenario_file):
    """Convert parsed steplog data to frontend-compatible replay format.

    Args:
        steplog_data: parsed steplog (actions, max_turn, units_positions).
        scenario_file: scenario the steplog was produced on; source of the initial unit data.
    """
    from datetime import datetime
    from ai.unit_registry import UnitRegistry

    print(f"🔄 Converting to replay format...")

    # Un attribut `_detected_agents` etait remis a None ici "pour la generation du nom de
    # fichier" : il n'a jamais ete relu nulle part, et le nom de fichier ne depend d'aucun
    # agent. Supprime avec l'etat fantome porte par les attributs de fonction.

    actions = steplog_data['actions']
    max_turn = steplog_data['max_turn']
    
    # Load unit registry for complete unit data
    unit_registry = UnitRegistry()
    
    # Load config for board size and other settings
    config = get_config_loader()
    
    # Get board size from board_config.json (single source of truth)
    board_cols, board_rows = config.get_board_size()
    board_size = [board_cols, board_rows]
    
    # Le chemin du scenario arrive par parametre. Il transitait avant par un attribut pose sur
    # cet objet fonction (`convert_to_replay_format._scenario_file`) : jamais remis a zero entre
    # deux conversions du meme processus, et double d'un repli sur `config/scenario.json`, un
    # fichier qui n'existe pas dans le depot.
    if not os.path.exists(scenario_file):
        raise FileNotFoundError(f"Scenario file not found: {scenario_file}")
    
    with open(scenario_file, 'r') as f:
        scenario_data = json.load(f)
    
    # Determine winner from final actions
    winner = None
    for action in reversed(actions):
        if action.get('type') == 'phase_change' and 'winner' in action:
            winner = action['winner']
            break
    
    # Build initial state using actual unit registry data
    initial_units = []
    if not steplog_data['units_positions']:
        raise ValueError("No unit position data found in steplog - cannot generate replay without unit data")
    
    # Get initial scenario units for complete unit data
    if 'units' not in scenario_data:
        raise KeyError("Scenario missing required 'units' field")
    
    scenario_units = {unit['id']: unit for unit in scenario_data['units']}
    
    # No need to detect scenario name - handled by filename extraction
    
    # Use ALL units from scenario, not just those tracked in steplog
    for unit_id, scenario_unit in scenario_units.items():
        if 'col' not in scenario_unit or 'row' not in scenario_unit:
            raise KeyError(f"Unit {unit_id} missing required position data (col/row) in scenario")
        
        # Get unit statistics from unit registry
        if 'unit_type' not in scenario_unit:
            raise KeyError(f"Unit {unit_id} missing required 'unit_type' field")
        
        try:
            unit_stats = unit_registry.get_unit_data(scenario_unit['unit_type'])
        except ValueError as e:
            raise ValueError(f"Failed to get unit data for '{scenario_unit['unit_type']}': {e}")
        
        # Get final position from steplog tracking or use initial position
        if unit_id in steplog_data['units_positions']:
            final_col = steplog_data['units_positions'][unit_id]['col']
            final_row = steplog_data['units_positions'][unit_id]['row']
        else:
            final_col = scenario_unit['col']
            final_row = scenario_unit['row']
        
        # Build complete unit data with FINAL positions from steplog tracking
        unit_data = {
            'id': unit_id,
            'unit_type': scenario_unit['unit_type'],
            'player': require_key(scenario_unit, 'player'),
            'col': final_col,  # Use FINAL position from steplog tracking
            'row': final_row   # Use FINAL position from steplog tracking
        }
        
        # Copy all unit statistics from registry (preserves UPPERCASE field names)
        for field_name, field_value in unit_stats.items():
            if field_name.isupper():  # Only copy UPPERCASE fields per AI_TURN.md
                unit_data[field_name] = field_value
        
        # Ensure CUR_HP is set to HP_MAX initially
        if 'HP_MAX' in unit_stats:
            unit_data['CUR_HP'] = unit_stats['HP_MAX']
        
        initial_units.append(unit_data)
    
    # Game states require actual game state snapshots from steplog - not generated defaults
    game_states = []
    # Note: Real implementation would need to capture actual game states during steplog generation
    
    # Build replay data structure matching frontend expectations
    replay_data = {
        'game_info': {
            'scenario': 'steplog_conversion',
            'ai_behavior': 'sequential_activation',
            'total_turns': max_turn,
            'winner': winner
        },
        'metadata': {
            'total_combat_log_entries': len(actions),
            'final_turn': max_turn,
            'episode_reward': 0.0,
            'format_version': '2.0',
            'replay_type': 'steplog_converted',
            'conversion_timestamp': datetime.now().isoformat(),
            'source_file': 'steplog'
        },
        'initial_state': {
            'units': initial_units,
            'board_size': board_size
        },
        'combat_log': actions,
        'game_states': game_states,
        'episode_steps': len([a for a in actions if a.get('type') != 'phase_change']),
        'episode_reward': calculate_episode_reward_from_actions(actions, winner)
    }
    
    return replay_data


