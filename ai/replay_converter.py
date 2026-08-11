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
from shared.torch_safe_globals import register_torch_safe_globals

# Avant tout `MaskablePPO.load` de ce module : torch >= 2.6 charge en `weights_only=True`.
register_torch_safe_globals()

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

    # UN replay = UNE partie. `generate_steplog_and_replay` ecrit les N episodes de
    # `--test-episodes` dans le MEME steplog et les tours repartent a T1 a chaque episode :
    # tout convertir empilait plusieurs parties dans un seul `combat_log` (une unite y saute
    # d'un coup a sa position de depart de l'episode suivant, et `total_turns` devient le max
    # sur toutes les parties au lieu de la duree de celle qu'on rejoue).
    #
    # Le decoupage se fait sur le DELIMITEUR que `step_logger` ecrit pour ca
    # (`=== EPISODE n START ===`, step_logger.py:300), comme le font deja
    # `services/replay_parser.py` et `frontend/src/utils/replayParser.ts`. Filtrer plutot sur le
    # prefixe `E<n>` des lignes d'action ne PEUT PAS segmenter : `step_logger` ecrit les
    # transitions de phase sans ce prefixe (`[ts] T1 P1 MOVE phase Start`, step_logger.py:1006),
    # donc les changements de phase de TOUS les episodes seraient restes dans le replay.
    # De meme, `=== ACTIONS START ===` (step_logger.py:404) delimite l'en-tete : le reniflage
    # « premiere ligne qui ressemble a une action » s'allumait sur `[ts] T1 OBJECTIVE CONTROL:`.
    episode_starts = [i for i, line in enumerate(lines) if '=== EPISODE ' in line]
    if episode_starts:
        _first, _next = episode_starts[0], episode_starts[1:]
        episode_lines = lines[_first:_next[0]] if _next else lines[_first:]
        if _next:
            print(f"   ⚠️  {len(episode_starts)} episodes dans ce steplog — seul le premier est "
                  f"converti (un replay decrit une partie). {len(_next)} ecarte(s).")
    else:
        # Steplog sans delimiteur : un seul episode par fichier (ancien format).
        episode_lines = lines

    try:
        _actions_start = next(i for i, line in enumerate(episode_lines) if '=== ACTIONS START ===' in line)
        action_lines = episode_lines[_actions_start + 1:]
    except StopIteration:
        action_lines = episode_lines

    # Parse action entries
    actions = []
    max_turn = 1
    units_positions = {}

    # Regex patterns for parsing. `(?:E\d+ )?` : le prefixe d'episode est present sur les lignes
    # d'action et absent des transitions de phase — les deux formes doivent matcher, comme le
    # fait deja `ai/hidden_action_finder.py`.
    action_pattern = r'\[([^\]]+)\] (?:E\d+ )?T(\d+) P(\d+) (\w+) : (.+?) \[(SUCCESS|FAILED)\](?: \[STEP: (YES|NO)\])?'
    phase_pattern = r'\[([^\]]+)\] (?:E\d+ )?T(\d+) P(\d+) (\w+) phase Start'

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
                    # Aiguillage sur la DONNEE (`endHex` present), pas sur le type d'action : les
                    # deplacements portent desormais le vocabulaire du replay (move / advance /
                    # flee / reactive_move / deploy), et un test `type == 'move'` aurait fait
                    # retomber une avance ou un repli sur la position de DEPART lue dans le
                    # libelle — l'unite serait restee la ou elle etait avant de bouger.
                    end_hex = action_data.get('endHex')
                    pos_match = re.match(r'\((\d+),\s*(\d+)\)', end_hex) if end_hex else None
                    if pos_match is None and 'message' in action_data:
                        # Action sans deplacement : la position est celle du libelle. `\s*` :
                        # `step_logger` ecrit `Unit 3(5,48)` SANS espace ; exiger l'espace ne
                        # trouvait jamais la position, et l'unite restait au point ou le scenario
                        # l'avait deposee.
                        pos_match = re.search(r'Unit \d+\((\d+),\s*(\d+)\)', action_data['message'])
                    if pos_match:
                        col, row = pos_match.groups()
                        units_positions[unit_id] = {
                            'col': int(col),
                            'row': int(row),
                            'last_seen_turn': int(turn)
                        }
        
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

# ── Grammaire des lignes d'action de `ai/step_logger.py` ─────────────────────────────────────
# Marqueurs optionnels ecrits entre le verbe et la suite : nom de la capacite qui a autorise
# l'action (`[ASSAULT]`, `[WAAAGH!]`) puis `[FLY]` (21.03). `[^\]]+` et non une classe enumeree —
# un nom de capacite n'est pas un identifiant — comme `ai/hidden_action_finder.py`.
_ABILITY = r'(?:\s+\[[^\]]+\])*'
# `\s*` apres la virgule : `step_logger` ecrit `(5,48)` SANS espace.
_POS = r'\((\d+),\s*(\d+)\)'
_UNIT = r'Unit (\d+)\([^)]+\)'

# TABLE des formes reconnues, essayees DANS L'ORDRE. Chaque entree : (regex, type d'action,
# extracteur des champs propres a la forme). Les cinq branches `if/elif` qu'elle remplace
# repetaient le meme corps `details.update(...)`, et la derniere (`WAIT`) etait restee sur un
# test de sous-chaine — precisement la forme qui rendait invisibles les lignes `SHOT [ASSAULT]`.
# Ajouter un verbe = ajouter une ligne ici.
#
# ORDRE SIGNIFIANT sur les verbes de mouvement : les formes longues d'abord, sinon `MOVED`
# mordrait le debut de `MOVED AFTER SHOOTING`. Le `type` reprend le VOCABULAIRE deja rendu par
# le frontend (`replayParser.ts` : move / advance / flee / reactive_move / deploy) plutot qu'un
# champ maison : c'est celui-la que le renderer sait lire.
_MOVE_TYPES = (
    ('REACTIVE MOVED', 'reactive_move'),
    ('MOVED AFTER SHOOTING', 'move'),
    ('MOVED', 'move'),
    ('ADVANCED', 'advance'),
    ('FLED', 'flee'),
    ('DEPLOYED', 'deploy'),
)


def _move_fields(match):
    """`Unit N(c,r) <VERBE> [marqueurs] from (c,r) to (c,r)` — depart et arrivee."""
    _uid, start_col, start_row, end_col, end_row = match.groups()
    return {'startHex': f"({start_col}, {start_row})", 'endHex': f"({end_col}, {end_row})"}


def _destination_fields(match):
    """`Unit N(c,r) <VERBE> to (c,r)` — forme SANS depart (step_logger.py:454 et :514).

    Elle etait perdue : seule la forme `from ... to ...` etait reconnue, donc un move logge par
    ce chemin ne mettait pas la position a jour et tout ce qui suivait etait rejoue contre un
    fantome. Pas de `startHex` a inventer — l'appelant retombe sur `Unit N(c,r)` pour la position.
    """
    _uid, end_col, end_row = match.groups()
    return {'endHex': f"({end_col}, {end_row})"}


def _target_fields(match):
    """`Unit N(c,r) <VERBE> [marqueurs] Unit M` — cible."""
    _uid, target_id = match.groups()
    return {'targetUnitId': int(target_id)}


def _no_fields(_match):
    return {}


def _build_action_grammar():
    """Construit la table (regex compilee, type, extracteur). Appelee UNE fois a l'import."""
    grammar = []
    for verb, action_type in _MOVE_TYPES:
        grammar.append((
            re.compile(r'Unit (\d+)\([^)]+\) ' + verb + _ABILITY + r' from ' + _POS + r' to ' + _POS),
            action_type, _move_fields,
        ))
    for verb, action_type in _MOVE_TYPES:
        grammar.append((
            re.compile(r'Unit (\d+)\([^)]+\) ' + verb + _ABILITY + r' to ' + _POS),
            action_type, _destination_fields,
        ))
    for verb, action_type in (('SHOT', 'shoot'), ('FOUGHT', 'combat'), ('CHARGED', 'charge')):
        grammar.append((
            re.compile(_UNIT + r' ' + verb + _ABILITY + r'\s+Unit (\d+)'),
            action_type, _target_fields,
        ))
    grammar.append((re.compile(_UNIT + r' WAIT'), 'wait', _no_fields))
    return tuple(grammar)


_ACTION_GRAMMAR = _build_action_grammar()


def parse_action_message(message, context):
    """Parse action message and extract details."""
    details = {
        'turnNumber': context['turn'],
        'phase': context['phase'],
        'player': context['player'],
        'timestamp': context['timestamp']
    }

    for pattern, action_type, extract in _ACTION_GRAMMAR:
        match = pattern.match(message)
        if match is None:
            continue
        details.update({
            'type': action_type,
            'message': message,
            'unitId': int(match.group(1)),
            **extract(match),
        })
        return details
    return None

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
        
        # Position de DEPART = celle du scenario. Ce bloc lisait `units_positions`, c'est-a-dire
        # la DERNIERE position vue dans le steplog : `initial_state` decrivait alors le plateau de
        # FIN de partie pour les unites ayant agi, et celui de depart pour les autres — un etat
        # initial qui n'a jamais existe. Le frontend rejoue `combat_log` PAR-DESSUS cet etat, donc
        # chaque deplacement y etait applique une seconde fois, depuis son arrivee.
        # Le code etait inatteignable avant la correction du parser (`units_positions` restait
        # vide, donc le `raise` ci-dessus partait systematiquement) : premiere execution reelle.
        unit_data = {
            'id': unit_id,
            'unit_type': scenario_unit['unit_type'],
            'player': require_key(scenario_unit, 'player'),
            'col': scenario_unit['col'],
            'row': scenario_unit['row'],
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


