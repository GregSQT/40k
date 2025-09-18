#!/usr/bin/env python3
"""
services/api_server.py - HTTP API Server for W40K Engine
Connects AI_TURN.md compliant engine to frontend board visualization
"""

import json
import os
import sys
import time
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

# Minimal Flask logging for debugging when needed
flask_request_logs = []

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
        
        # Load configuration and scenario
        config = load_config()
        scenario_file = os.path.join("config", "scenario.json")
        
        # Initialize unit registry
        from ai.unit_registry import UnitRegistry
        unit_registry = UnitRegistry()
        
        # Create engine with proper parameters
        engine = W40KEngine(
            config=config,
            rewards_config="default",
            training_config_name="default",
            controlled_agent=None,
            active_agents=None,
            scenario_file=scenario_file,
            unit_registry=unit_registry,
            quiet=True
        )
        
        # Restore original working directory
        os.chdir(original_cwd)
        
        print("✅ W40K Engine initialized successfully (PvP mode)")
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

def initialize_pve_engine():
    """Initialize the W40K engine for PvE mode with AI Player 2."""
    global engine
    try:
        # Change to project root directory for config loading
        original_cwd = os.getcwd()
        project_root = os.path.join(os.path.dirname(__file__), '..')
        os.chdir(os.path.abspath(project_root))
        
        # Load configuration and scenario
        config = load_config()
        scenario_file = os.path.join("config", "scenario.json")
        
        # Initialize unit registry
        from ai.unit_registry import UnitRegistry
        unit_registry = UnitRegistry()
        
        # Create engine with PvE configuration - set pve_mode in config
        config["pve_mode"] = True
        
        engine = W40KEngine(
            config=config,
            rewards_config="default",
            training_config_name="default",
            controlled_agent="SpaceMarine_Infantry_Troop_RangedSwarm",  # Player 2 AI agent
            active_agents=None,
            scenario_file=scenario_file,
            unit_registry=unit_registry,
            quiet=True
        )
        
        # AI model loading handled by engine's _load_ai_model_for_pve() method
        # No duplicate model loading logic needed in API layer
        print(f"✅ PvE: Engine initialized with built-in AI model loading")
        
        # Restore original working directory
        os.chdir(original_cwd)
        
        print("✅ W40K Engine initialized successfully (PvE mode)")
        return True
    except Exception as e:
        # Restore original working directory on error
        if 'original_cwd' in locals():
            os.chdir(original_cwd)
        print(f"❌ Failed to initialize PvE engine: {e}")
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
    """Start a new game session with optional PvE mode."""
    global engine
    
    try:
        # Check for PvE mode in request
        data = request.get_json() or {}
        pve_mode = data.get('pve_mode', False)
        
        # CRITICAL: Always reinitialize engine based on requested mode to prevent mode contamination
        if pve_mode:
            print("DEBUG: Initializing engine for PvE mode")
            if not initialize_pve_engine():
                return jsonify({"success": False, "error": "PvE engine initialization failed"}), 500
        else:
            print("DEBUG: Initializing engine for PvP mode")
            if not initialize_engine():
                return jsonify({"success": False, "error": "PvP engine initialization failed"}), 500
            # Ensure PvE mode is explicitly disabled for PvP
            engine.is_pve_mode = False
        
        print("DEBUG: About to call engine.reset()")
        # Reset the engine for new game
        try:
            obs, info = engine.reset()
        except Exception as reset_error:
            print(f"CRITICAL ERROR in engine.reset(): {reset_error}")
            print(f"ERROR TYPE: {type(reset_error).__name__}")
            import traceback
            print(f"FULL TRACEBACK:\n{traceback.format_exc()}")
            raise
        print("DEBUG: engine.reset() completed successfully")
        
        # Convert sets to lists for JSON serialization
        serializable_state = dict(engine.game_state)
        for key, value in serializable_state.items():
            if isinstance(value, set):
                serializable_state[key] = list(value)
        
        # Add max_turns from game config
        from config_loader import get_config_loader
        config = get_config_loader()
        serializable_state["max_turns"] = config.get_max_turns()
        
        # Add PvE mode flag to response
        serializable_state["pve_mode"] = getattr(engine, 'is_pve_mode', False)
        
        return jsonify({
            "success": True,
            "game_state": serializable_state,
            "message": f"Game started successfully ({'PvE' if pve_mode else 'PvP'} mode)"
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
        
        # Convert frontend hex click to engine semantic action format
        if "col" in data and "row" in data and "selectedUnitId" in data:
            action = {
                "action": "move",
                "unitId": str(data["selectedUnitId"]),
                "destCol": data["col"],
                "destRow": data["row"]
            }
        else:
            action = data  # Pass through already formatted actions
        
        if not action:
            return jsonify({"success": False, "error": "No action provided"}), 400
        
        # AI_TURN.md: Route ALL actions through engine consistently
        success, result = engine.execute_semantic_action(action)
        
        # Convert sets to lists for JSON serialization
        serializable_state = dict(engine.game_state)
        for key, value in serializable_state.items():
            if isinstance(value, set):
                serializable_state[key] = list(value)
        
        # Extract and send detailed action logs to frontend
        action_logs = serializable_state.get("action_logs", [])
        if action_logs:
            # Clear logs from ORIGINAL engine.game_state to prevent duplication
            engine.game_state["action_logs"] = []
            serializable_state["action_logs"] = []
        
        return jsonify({
            "success": success,
            "result": result,
            "game_state": serializable_state,
            "action_logs": action_logs,
            "message": "Action executed successfully" if success else "Action failed"
        })
    
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"🔥 FULL ERROR TRACEBACK:")
        print(error_details)
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

@app.route('/api/game/ai-turn', methods=['POST'])
def execute_ai_turn():
    """Execute AI turn - pure HTTP wrapper."""
    global engine
    
    if not engine:
        return jsonify({"success": False, "error": "Engine not initialized"}), 400
    
    try:
        # Debug: Check engine state before AI turn
        print(f"DEBUG AI_TURN: AI model loaded = {hasattr(engine, '_ai_model') and engine._ai_model is not None}")
        success, result = engine.execute_ai_turn()
        print(f"DEBUG AI_TURN: execute_ai_turn returned success={success}, result={result}")
        
        if not success:
            error_type = result.get("error", "unknown_error")
            if error_type in ["not_pve_mode", "not_ai_player_turn"]:
                return jsonify({"success": False, "error": result}), 400
            else:
                return jsonify({"success": False, "error": result}), 500
        
        # Convert sets to lists for JSON serialization
        serializable_state = dict(engine.game_state)
        for key, value in serializable_state.items():
            if isinstance(value, set):
                serializable_state[key] = list(value)
        
        # Extract action logs
        action_logs = serializable_state.get("action_logs", [])
        if action_logs:
            engine.game_state["action_logs"] = []
            serializable_state["action_logs"] = []
        
        return jsonify({
            "success": True,
            "result": result,
            "game_state": serializable_state,
            "action_logs": action_logs
        })
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

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
            "ai_turn": "/api/game/ai-turn",
            "get_state": "/api/game/state",
            "reset_game": "/api/game/reset",
            "board_config": "/api/config/board",
            "debug_actions": "/api/debug/actions"
        },
        "instructions": [
            "1. Start frontend: cd frontend && npm run dev",
            "2. API server runs on http://localhost:5000",
            "3. Frontend runs on http://localhost:5173",
            "4. POST /api/game/start with pve_mode:true for AI",
            "5. POST /api/game/action with semantic actions",
            "6. POST /api/game/ai-turn to execute AI Player 2 turn"
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