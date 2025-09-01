#!/usr/bin/env python3
"""
ai/api/get_ai_action.py
Simple AI action API endpoint for Player vs AI mode
Loads trained model and returns single action for current game state
"""

import os
import json
import sys
from typing import Dict, Any, Optional, List, Tuple
from flask import Flask, request, jsonify
from flask_cors import CORS
import numpy as np

# Add project root directory to path for imports  
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from config_loader import ConfigLoader
from stable_baselines3 import DQN
import tempfile
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for frontend requests

# Global model cache
_model_cache = {}
_config_cache = None

def get_model_path(agent_key: str = "SpaceMarine") -> str:
    """Get path to trained model file"""
    model_dir = os.path.join(os.path.dirname(__file__), '..', 'models')
    model_file = f"default_model_{agent_key}.zip"
    return os.path.join(model_dir, model_file)

def load_trained_model(agent_key: str = "SpaceMarine") -> Optional[DQN]:
    """Load trained AI model with caching"""
    global _model_cache
    
    if agent_key in _model_cache:
        return _model_cache[agent_key]
    
    model_path = get_model_path(agent_key)
    
    if not os.path.exists(model_path):
        logger.warning(f"No trained model found at {model_path}")
        return None
    
    try:
        # Load the model
        model = DQN.load(model_path)
        _model_cache[agent_key] = model
        logger.info(f"Loaded trained model: {agent_key}")
        return model
    except Exception as e:
        logger.error(f"Failed to load model {agent_key}: {e}")
        return None

def get_config() -> ConfigLoader:
    """Get configuration with caching"""
    global _config_cache
    
    if _config_cache is None:
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config')
        _config_cache = ConfigLoader(config_path)
    
    return _config_cache

def convert_to_gym_observation(game_state: Dict[str, Any]) -> np.ndarray:
    """Convert frontend game state to gym observation format"""
    # This should match the observation space in gym40k.py
    # For now, create a simple flattened representation
    
    units = game_state.get('units', [])
    board_size = 24 * 18  # Standard board size
    
    # Create observation array (simplified version)
    # In production, this should match exact gym environment observation space
    obs = np.zeros(board_size + len(units) * 10)  # Simplified observation space
    
    # Encode unit positions and stats
    for i, unit in enumerate(units):
        if i >= 10:  # Limit units for now
            break
        
        base_idx = board_size + i * 10
        obs[base_idx] = unit.get('player', 0)
        obs[base_idx + 1] = unit.get('col', 0)
        obs[base_idx + 2] = unit.get('row', 0)
        obs[base_idx + 3] = unit.get('CUR_HP', 0)
        obs[base_idx + 4] = unit.get('HP_MAX', 0)
        obs[base_idx + 5] = unit.get('MOVE', 0)
        obs[base_idx + 6] = unit.get('RNG_RNG', 0)
        obs[base_idx + 7] = unit.get('RNG_ATK', 0)
        obs[base_idx + 8] = unit.get('CC_RNG', 0)
        obs[base_idx + 9] = unit.get('CC_ATK', 0)
    
    return obs

def decode_gym_action(action: int, game_state: Dict[str, Any], unit_id: int, phase: str) -> Dict[str, Any]:
    """Convert gym action integer to readable action"""
    # This is a simplified decoder - should match gym40k.py action space
    
    units = game_state.get('units', [])
    unit = next((u for u in units if u['id'] == unit_id), None)
    
    if not unit:
        return {"success": False, "action": "skip", "unitId": unit_id, "error": "Unit not found"}
    
    # Simple action mapping (expand based on actual gym environment)
    if phase == "move":
        if action == 0:
            return {"success": True, "action": "skip", "unitId": unit_id}
        else:
            # Simplified move action - in production, decode actual coordinates
            adjacent_positions = [
                (unit['col'] + 1, unit['row']),
                (unit['col'] - 1, unit['row']),
                (unit['col'], unit['row'] + 1),
                (unit['col'], unit['row'] - 1),
            ]
            
            if 1 <= action <= len(adjacent_positions):
                dest_col, dest_row = adjacent_positions[action - 1]
                return {
                    "success": True,
                    "action": "move",
                    "unitId": unit_id,
                    "destinationCol": max(0, min(23, dest_col)),
                    "destinationRow": max(0, min(17, dest_row))
                }
    
    elif phase == "shoot":
        if action == 0:
            return {"success": True, "action": "skip", "unitId": unit_id}
        else:
            # Find shootable enemies
            enemy_units = [u for u in units if u['player'] != unit['player'] and u['CUR_HP'] > 0]
            if enemy_units and 1 <= action <= len(enemy_units):
                target = enemy_units[action - 1]
                return {
                    "success": True,
                    "action": "shoot",
                    "unitId": unit_id,
                    "targetId": target['id']
                }
    
    elif phase == "charge":
        if action == 0:
            return {"success": True, "action": "skip", "unitId": unit_id}
        else:
            # Find chargeable enemies
            enemy_units = [u for u in units if u['player'] != unit['player'] and u['CUR_HP'] > 0]
            if enemy_units and 1 <= action <= len(enemy_units):
                target = enemy_units[action - 1]
                return {
                    "success": True,
                    "action": "charge",
                    "unitId": unit_id,
                    "targetId": target['id']
                }
    
    elif phase == "combat":
        if action == 0:
            return {"success": True, "action": "skip", "unitId": unit_id}
        else:
            # Find attackable enemies in combat range
            enemy_units = [u for u in units if u['player'] != unit['player'] and u['CUR_HP'] > 0]
            combat_enemies = []
            for enemy in enemy_units:
                distance = max(abs(unit['col'] - enemy['col']), abs(unit['row'] - enemy['row']))
                if distance <= unit.get('CC_RNG', 1):
                    combat_enemies.append(enemy)
            
            if combat_enemies and 1 <= action <= len(combat_enemies):
                target = combat_enemies[action - 1]
                return {
                    "success": True,
                    "action": "attack",
                    "unitId": unit_id,
                    "targetId": target['id']
                }
    
    # Default to skip if no valid action
    return {"success": True, "action": "skip", "unitId": unit_id}

@app.route('/ai/api/get_ai_action', methods=['POST'])
def get_ai_action():
    """Main API endpoint for getting AI action"""
    try:
        data = request.json
        
        if not data:
            return jsonify({"success": False, "error": "No JSON data provided"}), 400
        
        game_state = data.get('game_state')
        unit_id = data.get('unit_id')
        phase = data.get('phase')
        agent_key = data.get('agent_key', 'SpaceMarine')  # Default agent
        
        if not all([game_state, unit_id is not None, phase]):
            return jsonify({
                "success": False, 
                "error": "Missing required fields: game_state, unit_id, phase"
            }), 400
        
        # Load trained model
        model = load_trained_model(agent_key)
        
        if model is None:
            # Fallback to simple rule-based AI
            logger.info(f"No trained model available, using rule-based AI for unit {unit_id}")
            return jsonify(get_rule_based_action(game_state, unit_id, phase))
        
        # Convert to gym observation
        observation = convert_to_gym_observation(game_state)
        
        # Get AI action prediction
        action, _ = model.predict(observation, deterministic=False)
        action = int(action)
        
        # Decode action to readable format
        result = decode_gym_action(action, game_state, unit_id, phase)
        
        logger.info(f"AI action for unit {unit_id} in {phase}: {result['action']}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"AI API error: {e}")
        return jsonify({
            "success": False,
            "error": f"AI processing failed: {str(e)}"
        }), 500

def get_rule_based_action(game_state: Dict[str, Any], unit_id: int, phase: str) -> Dict[str, Any]:
    """Fallback rule-based AI when no trained model is available"""
    units = game_state.get('units', [])
    unit = next((u for u in units if u['id'] == unit_id), None)
    
    if not unit:
        return {"success": False, "action": "skip", "unitId": unit_id, "error": "Unit not found"}
    
    enemy_units = [u for u in units if u['player'] != unit['player'] and u['CUR_HP'] > 0]
    
    if phase == "move":
        # Move towards nearest enemy
        if enemy_units:
            nearest_enemy = min(enemy_units, key=lambda e: 
                abs(unit['col'] - e['col']) + abs(unit['row'] - e['row']))
            
            # Simple movement toward enemy
            if unit['col'] < nearest_enemy['col']:
                dest_col = min(23, unit['col'] + 1)
            elif unit['col'] > nearest_enemy['col']:
                dest_col = max(0, unit['col'] - 1)
            else:
                dest_col = unit['col']
            
            if unit['row'] < nearest_enemy['row']:
                dest_row = min(17, unit['row'] + 1)
            elif unit['row'] > nearest_enemy['row']:
                dest_row = max(0, unit['row'] - 1)
            else:
                dest_row = unit['row']
            
            return {
                "success": True,
                "action": "move",
                "unitId": unit_id,
                "destinationCol": dest_col,
                "destinationRow": dest_row
            }
    
    elif phase == "shoot":
        # Shoot at nearest enemy in range
        rng_range = unit.get('RNG_RNG', 0)
        if rng_range > 0 and enemy_units:
            for enemy in enemy_units:
                distance = max(abs(unit['col'] - enemy['col']), abs(unit['row'] - enemy['row']))
                if distance <= rng_range:
                    return {
                        "success": True,
                        "action": "shoot",
                        "unitId": unit_id,
                        "targetId": enemy['id']
                    }
    
    elif phase == "charge":
        # Charge nearest enemy
        if enemy_units:
            nearest_enemy = min(enemy_units, key=lambda e: 
                max(abs(unit['col'] - e['col']), abs(unit['row'] - e['row'])))
            return {
                "success": True,
                "action": "charge",
                "unitId": unit_id,
                "targetId": nearest_enemy['id']
            }
    
    elif phase == "combat":
        # Attack nearest enemy in combat range
        cc_range = unit.get('CC_RNG', 1)
        combat_enemies = []
        for enemy in enemy_units:
            distance = max(abs(unit['col'] - enemy['col']), abs(unit['row'] - enemy['row']))
            if distance <= cc_range:
                combat_enemies.append(enemy)
        
        if combat_enemies:
            target = combat_enemies[0]  # Attack first available enemy
            return {
                "success": True,
                "action": "attack",
                "unitId": unit_id,
                "targetId": target['id']
            }
    
    # Default to skip
    return {"success": True, "action": "skip", "unitId": unit_id}

@app.route('/ai/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "models_loaded": len(_model_cache)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)