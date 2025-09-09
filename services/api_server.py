#!/usr/bin/env python3
"""
services/api_server.py - HTTP API Server for W40K Engine
Connects AI_TURN.md compliant engine to frontend board visualization
"""

import json
import os
import sys
from typing import Dict, Any, Optional
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

# Add parent directory (project root) to path
parent_dir = os.path.join(os.path.dirname(__file__), '..')
abs_parent = os.path.abspath(parent_dir)
sys.path.insert(0, abs_parent)

# Add engine subdirectory to path
engine_dir = os.path.join(abs_parent, 'engine')
sys.path.insert(0, engine_dir)

from engine.w40k_engine import W40KEngine
from main import load_config

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for frontend requests

# Global engine instance
engine: Optional[W40KEngine] = None

def initialize_engine():
    """Initialize the W40K engine with configuration."""
    global engine
    try:
        # Change to project root directory for config loading
        original_cwd = os.getcwd()
        project_root = os.path.join(os.path.dirname(__file__), '..')
        os.chdir(os.path.abspath(project_root))
        config = load_config()
        engine = W40KEngine(config)
        
        # Restore original working directory
        os.chdir(original_cwd)
        
        print("✅ W40K Engine initialized successfully")
        return True
    except Exception as e:
        # Restore original working directory on error
        if 'original_cwd' in locals():
            os.chdir(original_cwd)
        print(f"❌ Failed to initialize engine: {e}")
        print(f"❌ Exception type: {type(e).__name__}")
        import traceback
        print(f"❌ Full traceback: {traceback.format_exc()}")
        return False

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "engine_initialized": engine is not None
    })

@app.route('/api/debug/engine-test', methods=['GET'])
def test_engine():
    """Test engine initialization directly."""
    try:
        # Test config loading
        original_cwd = os.getcwd()
        project_root = os.path.join(os.path.dirname(__file__), '..')
        os.chdir(os.path.abspath(project_root))
        
        from main import load_config
        config = load_config()
        
        os.chdir(original_cwd)
        
        return jsonify({
            "success": True,
            "config_loaded": True,
            "units_count": len(config.get("units", [])),
            "board_config": bool(config.get("board"))
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": str(e.__class__.__name__)
        }), 500

@app.route('/api/game/start', methods=['POST'])
def start_game():
    """Start a new game session."""
    global engine
    
    if not engine:
        if not initialize_engine():
            return jsonify({"success": False, "error": "Engine initialization failed"}), 500
    
    try:
        # Reset the engine for new game
        obs, info = engine.reset()
        
        # Convert sets to lists for JSON serialization
        serializable_state = dict(engine.game_state)
        for key, value in serializable_state.items():
            if isinstance(value, set):
                serializable_state[key] = list(value)
        
        # Add max_turns from game config
        from config_loader import get_config_loader
        config = get_config_loader()
        serializable_state["max_turns"] = config.get_max_turns()
        
        return jsonify({
            "success": True,
            "game_state": serializable_state,
            "message": "Game started successfully"
        })
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Failed to start game: {str(e)}"
        }), 500

@app.route('/api/game/action', methods=['POST'])
def execute_action():
    """Execute a semantic action in the game."""
    global engine
    
    if not engine:
        return jsonify({"success": False, "error": "Engine not initialized"}), 400
    
    try:
        data = request.json
        if not data:
            return jsonify({"success": False, "error": "No JSON data provided"}), 400
        
        # Extract complete action dictionary (not just the action field)
        action = data  # Use the entire request data as the action
        if not action:
            return jsonify({"success": False, "error": "No action provided"}), 400
        
        # AI_TURN.md: Route shooting actions directly to compliant handlers
        current_phase = engine.game_state.get("phase", "move")
        action_type = action.get("action")
        
        if current_phase == "shoot" and action_type in ["activate_unit", "left_click", "right_click"]:
            # Import from correct engine location
            import sys
            import os
            # Navigate from services/ to engine/phase_handlers/
            # Direct file loading to bypass module structure requirements
            handlers_file = os.path.join(os.path.dirname(__file__), '..', 'engine', 'phase_handlers', 'shooting_handlers.py')
            import importlib.util
            spec = importlib.util.spec_from_file_location("shooting_handlers", handlers_file)
            shooting_handlers = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(shooting_handlers)
            
            # Get active unit if exists, otherwise pass None
            active_unit = None
            if engine.game_state.get("active_shooting_unit"):
                active_unit = next(
                    (u for u in engine.game_state["units"] 
                     if u["id"] == engine.game_state["active_shooting_unit"]), 
                    None
                )
            
            # Handle unit selection for shooting_handlers compatibility
            if action_type == "activate_unit":
                # Unit activation - find unit from action
                target_unit_id = action.get("unitId")
                target_unit = next(
                    (u for u in engine.game_state["units"] if u["id"] == target_unit_id), 
                    None
                )
                if not target_unit:
                    success, result = False, {"error": "unit_not_found", "unitId": target_unit_id}
                else:
                    success, result = shooting_handlers.execute_action(engine.game_state, target_unit, action, engine.config)
            elif active_unit:
                # Active unit exists - use it
                success, result = shooting_handlers.execute_action(engine.game_state, active_unit, action, engine.config)
            else:
                # No active unit - this shouldn't happen in shooting phase
                success, result = False, {"error": "no_active_shooting_unit", "action": action_type}
        else:
            # Other phases use engine
            success, result = engine.step(action)
        
        # Convert sets to lists for JSON serialization
        serializable_state = dict(engine.game_state)
        for key, value in serializable_state.items():
            if isinstance(value, set):
                serializable_state[key] = list(value)
        
        # Debug critical game state
        print(f"🔍 API RESPONSE DEBUG:")
        print(f"  - Phase: {serializable_state.get('phase')}")
        print(f"  - Current player: {serializable_state.get('current_player')}")
        print(f"  - Move pool: {serializable_state.get('move_activation_pool')}")
        print(f"  - Shoot pool: {serializable_state.get('shoot_activation_pool')}")
        
        return jsonify({
            "success": success,
            "result": result,
            "game_state": serializable_state,
            "message": "Action executed successfully" if success else "Action failed"
        })
    
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"🔥 FULL ERROR TRACEBACK:")
        print(error_details)
        print(f"🔥 ERROR TYPE: {type(e).__name__}")
        print(f"🔥 ERROR MESSAGE: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Action execution failed: {str(e)}",
            "traceback": error_details
        }), 500

@app.route('/api/game/state', methods=['GET'])
def get_game_state():
    """Get current game state."""
    global engine
    
    if not engine:
        return jsonify({"success": False, "error": "Engine not initialized"}), 400
    
    return jsonify({
        "success": True,
        "game_state": engine.game_state
    })

@app.route('/api/game/reset', methods=['POST'])
def reset_game():
    """Reset the current game."""
    global engine
    
    if not engine:
        return jsonify({"success": False, "error": "Engine not initialized"}), 400
    
    try:
        obs, info = engine.reset()
        
        return jsonify({
            "success": True,
            "game_state": engine.game_state,
            "message": "Game reset successfully"
        })
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Reset failed: {str(e)}"
        }), 500

@app.route('/api/config/board', methods=['GET'])
def get_board_config():
    """Get board configuration for frontend."""
    try:
        # Load board config from file
        board_config_path = "config/board_config.json"
        if os.path.exists(board_config_path):
            with open(board_config_path, 'r', encoding='utf-8-sig') as f:
                board_data = json.loads(f.read())
            return jsonify({
                "success": True,
                "config": board_data["default"]
            })
        else:
            return jsonify({
                "success": False,
                "error": "Board config not found"
            }), 404
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Config load failed: {str(e)}"
        }), 500

@app.route('/api/debug/actions', methods=['GET'])
def get_available_actions():
    """Get list of available semantic actions for debugging."""
    return jsonify({
        "success": True,
        "actions": {
            "move": {
                "description": "Move a unit to specific destination",
                "format": {
                    "action": "move",
                    "unitId": "unit_id_string",
                    "destCol": "integer",
                    "destRow": "integer"
                },
                "example": {
                    "action": "move",
                    "unitId": "player0_unit1",
                    "destCol": 5,
                    "destRow": 3
                }
            },
            "skip": {
                "description": "Skip current unit's activation",
                "format": {
                    "action": "skip",
                    "unitId": "unit_id_string"
                },
                "example": {
                    "action": "skip",
                    "unitId": "player0_unit1"
                }
            }
        }
    })

@app.route('/', methods=['GET'])
def serve_frontend():
    """Serve frontend instructions."""
    return jsonify({
        "message": "W40K Engine API Server",
        "frontend_url": "http://localhost:5173",
        "api_endpoints": {
            "health": "/api/health",
            "start_game": "/api/game/start",
            "execute_action": "/api/game/action",
            "get_state": "/api/game/state",
            "reset_game": "/api/game/reset",
            "board_config": "/api/config/board",
            "debug_actions": "/api/debug/actions"
        },
        "instructions": [
            "1. Start frontend: cd frontend && npm run dev",
            "2. API server runs on http://localhost:5000",
            "3. Frontend runs on http://localhost:5173",
            "4. POST /api/game/start to initialize",
            "5. POST /api/game/action with semantic actions"
        ]
    })

if __name__ == '__main__':
    print("🚀 Starting W40K Engine API Server...")
    print("📡 Server will run on http://localhost:5000")
    print("🎮 Frontend should connect to this API")
    print("✨ Use AI_TURN.md compliant semantic actions")
    
    # Initialize engine on startup
    if initialize_engine():
        print("⚡ Ready to serve the board!")
    else:
        print("⚠️  Engine initialization failed - will retry on first request")
    
    app.run(host='0.0.0.0', port=5000, debug=True)