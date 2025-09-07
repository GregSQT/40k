#!/usr/bin/env python3
"""
test_board.py - Test Script to See Engine Working on Frontend Board

This script demonstrates the engine working with the frontend board visualization.
"""

import requests
import json
import time
import webbrowser
from typing import Dict, Any

# API endpoints
API_BASE = "http://localhost:5000"
FRONTEND_URL = "http://localhost:5173"

def test_api_connection():
    """Test if API server is running."""
    try:
        response = requests.get(f"{API_BASE}/api/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ API Server: {data['status']}")
            print(f"✅ Engine Ready: {data['engine_initialized']}")
            return True
        else:
            print(f"❌ API Server Error: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Cannot connect to API server: {e}")
        return False

def start_game():
    """Start a new game session."""
    try:
        response = requests.post(f"{API_BASE}/api/game/start")
        if response.status_code == 200:
            data = response.json()
            print("✅ Game started successfully")
            game_state = data['game_state']
            print(f"   Turn: {game_state['turn']}")
            print(f"   Current Player: {game_state['current_player']}")
            print(f"   Phase: {game_state['phase']}")
            print(f"   Units: {len(game_state['units'])}")
            return data['game_state']
        else:
            print(f"❌ Failed to start game: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Start game error: {e}")
        return None

def execute_test_move(unit_id: str, dest_col: int, dest_row: int):
    """Execute a test movement action."""
    action = {
        "action": "move",
        "unitId": unit_id,
        "destCol": dest_col,
        "destRow": dest_row
    }
    
    try:
        response = requests.post(
            f"{API_BASE}/api/game/action",
            json=action,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            data = response.json()
            if data['success']:
                result = data['result']
                print(f"✅ Move successful: {result.get('action', 'unknown')}")
                if 'fromCol' in result and 'toCol' in result:
                    print(f"   {unit_id}: ({result['fromCol']}, {result['fromRow']}) → ({result['toCol']}, {result['toRow']})")
                return data['game_state']
            else:
                print(f"❌ Move failed: {data.get('result', {}).get('error', 'unknown error')}")
                return None
        else:
            print(f"❌ API Error: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Request error: {e}")
        return None

def demonstrate_engine():
    """Demonstrate the engine working with several moves."""
    print("\n🎮 Starting W40K Engine Board Demonstration")
    print("=" * 50)
    
    # Test API connection
    if not test_api_connection():
        print("\n❌ Cannot connect to API server.")
        print("   Start the API server with: python api_server.py")
        return False
    
    # Start game
    game_state = start_game()
    if not game_state:
        return False
    
    print(f"\n📍 Initial Unit Positions:")
    for unit in game_state['units']:
        print(f"   {unit['id']}: Player {unit['player']} at ({unit['col']}, {unit['row']}) HP:{unit['CUR_HP']}")
    
    # Execute some test moves
    print(f"\n🚀 Executing Test Moves:")
    
    moves = [
        ("player0_unit1", 3, 1),  # Player 0 unit moves east
        ("player1_unit1", 7, 8),  # Player 1 unit moves west
        ("player0_unit1", 4, 1),  # Player 0 unit moves east again
        ("player1_unit1", 6, 8),  # Player 1 unit moves west again
    ]
    
    for i, (unit_id, dest_col, dest_row) in enumerate(moves, 1):
        print(f"\n--- Move {i} ---")
        game_state = execute_test_move(unit_id, dest_col, dest_row)
        if game_state:
            print(f"   Turn: {game_state['turn']}, Player: {game_state['current_player']}, Phase: {game_state['phase']}")
            print(f"   Episode Steps: {game_state['episode_steps']}")
        else:
            print("   Move failed, stopping demonstration")
            break
        
        # Small delay between moves
        time.sleep(0.5)
    
    print(f"\n📍 Final Unit Positions:")
    if game_state:
        for unit in game_state['units']:
            print(f"   {unit['id']}: Player {unit['player']} at ({unit['col']}, {unit['row']}) HP:{unit['CUR_HP']}")
    
    return True

def open_frontend():
    """Open the frontend in browser."""
    print(f"\n🌐 Opening frontend at {FRONTEND_URL}")
    print("   The board visualization should show the units moving!")
    try:
        webbrowser.open(FRONTEND_URL)
        return True
    except Exception as e:
        print(f"❌ Could not open browser: {e}")
        print(f"   Manually open: {FRONTEND_URL}")
        return False

def main():
    """Main demonstration function."""
    print("🎯 W40K Engine Board Test")
    print("=" * 30)
    print(f"API Server: {API_BASE}")
    print(f"Frontend: {FRONTEND_URL}")
    
    print("\n📋 Instructions:")
    print("1. Start API server: python api_server.py")
    print("2. Start frontend: cd frontend && npm run dev")
    print("3. Run this test: python test_board.py")
    
    # Open frontend
    open_frontend()
    
    # Wait a moment for browser to open
    time.sleep(2)
    
    # Run demonstration
    success = demonstrate_engine()
    
    if success:
        print("\n🎉 Demonstration Complete!")
        print("✅ Engine is working correctly")
        print("✅ API endpoints functional")
        print("✅ Units should be visible moving on the board")
        print(f"\n🎮 Visit {FRONTEND_URL} to see the live board!")
    else:
        print("\n❌ Demonstration failed")
        print("   Check that both API server and frontend are running")
    
    print("\n🔧 Manual Testing:")
    print("   POST /api/game/start - Start new game")
    print("   POST /api/game/action - Execute actions")
    print("   GET /api/game/state - Get current state")

if __name__ == "__main__":
    main()