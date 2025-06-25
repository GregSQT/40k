#!/usr/bin/env python3
"""
Enhanced Game Replay Viewer - Watch replays as if you were playing
"""

import json
import time
import os
import sys
from typing import List, Dict, Any

# ANSI color codes for better visualization
class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    BLACK = '\033[30m'
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_BLUE = '\033[44m'
    BG_YELLOW = '\033[43m'
    BG_BLACK = '\033[40m'
    BG_WHITE = '\033[47m'

BOARD_WIDTH = 24
BOARD_HEIGHT = 18

class GameReplayViewer:
    def __init__(self, event_log: List[Dict[str, Any]]):
        self.event_log = event_log
        self.current_step = 0
        self.paused = False
        self.speed = 1.0  # seconds between steps
        
        # Track all units throughout the game for better state reconstruction
        self.all_units = self._discover_units()
        
    def _discover_units(self) -> Dict[int, Dict[str, Any]]:
        """Discover all units that appear in the replay."""
        units = {}
        
        for event in self.event_log:
            # Handle different event formats
            if "units" in event and isinstance(event["units"], list):
                # Full format with units array
                for unit in event["units"]:
                    unit_id = unit.get("id")
                    if unit_id is not None:
                        units[unit_id] = {
                            "id": unit_id,
                            "name": unit.get("name", f"Unit-{unit_id}"),
                            "unit_type": unit.get("unit_type", "Intercessor"),
                            "player": unit.get("player", 1 if unit_id in [3, 4] else 0),
                            "hp_max": unit.get("hp_max", 4 if unit_id in [2, 4] else 3),
                            "alive": True
                        }
            elif "unit_id" in event:
                # Simple format with just unit_id
                unit_id = event["unit_id"]
                if unit_id not in units:
                    units[unit_id] = {
                        "id": unit_id,
                        "name": f"Unit-{unit_id}",
                        "unit_type": "AssaultIntercessor" if unit_id in [2, 4] else "Intercessor",
                        "player": 1 if unit_id in [3, 4] else 0,
                        "hp_max": 4 if unit_id in [2, 4] else 3,
                        "alive": True
                    }
        
        return units
    
    def _reconstruct_game_state(self, event_index: int) -> List[Dict[str, Any]]:
        """Reconstruct the game state at a given event index."""
        units = []
        
        # Start with discovered units and update their states
        for unit_id, base_unit in self.all_units.items():
            unit = base_unit.copy()
            unit["col"] = 0
            unit["row"] = 0
            unit["cur_hp"] = unit["hp_max"]
            unit["alive"] = True
            
            # Apply all events up to current index for this unit
            for i in range(min(event_index + 1, len(self.event_log))):
                event = self.event_log[i]
                
                if "units" in event and isinstance(event["units"], list):
                    # Full format
                    for event_unit in event["units"]:
                        if event_unit.get("id") == unit_id:
                            unit.update(event_unit)
                            break
                elif event.get("unit_id") == unit_id:
                    # Simple format - update position and hp
                    if "position" in event and len(event["position"]) >= 2:
                        unit["col"] = event["position"][0]
                        unit["row"] = event["position"][1]
                    if "hp" in event:
                        unit["cur_hp"] = event["hp"]
                        unit["alive"] = event["hp"] > 0
            
            units.append(unit)
        
        return units
        
    def clear_screen(self):
        """Clear the terminal screen."""
        os.system("cls" if os.name == "nt" else "clear")
    
    def get_unit_symbol(self, unit: Dict[str, Any]) -> str:
        """Get the display symbol for a unit matching your game style."""
        if not unit.get("alive", True):
            return f"{Colors.RED}💀{Colors.RESET}"
        
        player = unit.get("player", 0)
        unit_type = unit.get("unit_type", "Unknown")
        
        # Color by player (matching your game: Blue for Player 0, Red for Player 1/AI)
        if player == 0:
            color = Colors.BLUE
            if "Intercessor" in unit_type and "Assault" not in unit_type:
                symbol = "🔵"  # Blue circle for player ranged
            else:
                symbol = "🔷"  # Blue diamond for player melee
        else:
            color = Colors.RED  
            if "Intercessor" in unit_type and "Assault" not in unit_type:
                symbol = "🔴"  # Red circle for AI ranged
            else:
                symbol = "🔶"  # Red diamond for AI melee
        
        return f"{color}{symbol}{Colors.RESET}"
    
    def draw_board(self, units: List[Dict[str, Any]], acting_unit_id: int = None):
        """Draw the game board with units in hex grid style."""
        # Create empty board
        board = [["⬜" for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)]
        
        # Place units on board
        for unit in units:
            if not unit.get("alive", True):
                continue
                
            col = unit.get("col", 0)
            row = unit.get("row", 0)
            
            if 0 <= row < BOARD_HEIGHT and 0 <= col < BOARD_WIDTH:
                symbol = self.get_unit_symbol(unit)
                
                # Highlight acting unit
                if unit.get("id") == acting_unit_id:
                    symbol = f"{Colors.BG_YELLOW}{Colors.BLACK}{symbol}{Colors.RESET}"
                
                board[row][col] = symbol
        
        # Draw hex grid similar to your game
        print(f"{Colors.GREEN}╔══════════════════════════════════════════════════╗{Colors.RESET}")
        print(f"{Colors.GREEN}║{Colors.RESET}              WH40K TACTICS BOARD                {Colors.GREEN}║{Colors.RESET}")
        print(f"{Colors.GREEN}╚══════════════════════════════════════════════════╝{Colors.RESET}")
        
        # Print column numbers
        print("    " + "".join(f"{i:2}" for i in range(BOARD_WIDTH)))
        
        # Print board with row numbers and hex-like styling
        for row_idx, row in enumerate(board):
            row_display = f"{row_idx:2} "
            for col_idx, cell in enumerate(row):
                if cell != "⬜":
                    # Replace white square with actual unit symbol
                    row_display += f" {cell}"
                else:
                    # Draw hex cell outline
                    row_display += f" {Colors.GREEN}⬡{Colors.RESET}"
            print(row_display)
        print()
    
    def display_unit_stats(self, units: List[Dict[str, Any]]):
        """Display unit statistics in a table format."""
        print(f"{Colors.BOLD}=== UNIT STATUS ==={Colors.RESET}")
        print(f"{'ID':<3} {'Name':<12} {'Type':<18} {'Player':<6} {'HP':<6} {'Pos':<8} {'Status':<8}")
        print("-" * 70)
        
        for unit in units:
            unit_id = unit.get("id", "?")
            name = unit.get("name", f"Unit-{unit_id}")
            unit_type = unit.get("unit_type", "Unknown")
            player = f"P{unit.get('player', '?')}"
            hp = f"{unit.get('cur_hp', '?')}/{unit.get('hp_max', '?')}"
            pos = f"({unit.get('col', '?')}, {unit.get('row', '?')})"
            status = "Alive" if unit.get("alive", True) else f"{Colors.RED}Dead{Colors.RESET}"
            
            # Color by player
            player_color = Colors.BLUE if unit.get('player') == 0 else Colors.RED
            
            print(f"{unit_id:<3} {name:<12} {unit_type:<18} {player_color}{player:<6}{Colors.RESET} {hp:<6} {pos:<8} {status}")
        print()
    
    def display_event_info(self, event: Dict[str, Any]):
        """Display information about the current event."""
        print(f"{Colors.BOLD}=== TURN {event.get('turn', '?')} - PHASE: {event.get('phase', 'Unknown').upper()} ==={Colors.RESET}")
        
        acting_unit = event.get('acting_unit_idx')
        target_unit = event.get('target_unit_idx')
        action = event.get('action', 'Unknown')
        flags = event.get('event_flags', {})
        stats = event.get('unit_stats', {})
        
        print(f"{Colors.CYAN}Acting Unit:{Colors.RESET} {acting_unit}")
        print(f"{Colors.CYAN}Target Unit:{Colors.RESET} {target_unit if target_unit is not None else 'None'}")
        print(f"{Colors.CYAN}Action:{Colors.RESET} {action}")
        
        if flags:
            print(f"{Colors.CYAN}Event Flags:{Colors.RESET} {', '.join(f'{k}={v}' for k, v in flags.items())}")
        
        if stats:
            print(f"{Colors.CYAN}Unit Stats:{Colors.RESET} {', '.join(f'{k}={v}' for k, v in stats.items())}")
        
        print()
    
    def display_controls(self):
        """Display control instructions."""
        print(f"{Colors.YELLOW}CONTROLS:{Colors.RESET}")
        print("  [SPACE] - Pause/Resume")
        print("  [→] or [d] - Next step")
        print("  [←] or [a] - Previous step") 
        print("  [+] - Speed up")
        print("  [-] - Slow down")
        print("  [r] - Restart from beginning")
        print("  [q] - Quit")
        print("  [h] - Show this help")
        print()
    
    def get_user_input(self):
        """Get user input without blocking (non-blocking input)."""
        try:
            import select
            import termios
            import tty
            
            # Unix/Linux implementation
            old_settings = termios.tcgetattr(sys.stdin)
            tty.cbreak(sys.stdin.fileno())
            
            if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
                key = sys.stdin.read(1)
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                return key
            else:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                return None
                
        except ImportError:
            # Windows implementation or fallback
            try:
                import msvcrt
                if msvcrt.kbhit():
                    return msvcrt.getch().decode('utf-8')
            except ImportError:
                pass
            return None
    
    def handle_input(self, key: str):
        """Handle user input."""
        if key is None:
            return True
            
        key = key.lower()
        
        if key == 'q':
            return False
        elif key == ' ':
            self.paused = not self.paused
            status = "PAUSED" if self.paused else "PLAYING"
            print(f"{Colors.GREEN}[{status}]{Colors.RESET}")
        elif key in ['d', '\x1b[C']:  # 'd' or right arrow
            self.next_step()
        elif key in ['a', '\x1b[D']:  # 'a' or left arrow
            self.previous_step()
        elif key == '+' or key == '=':
            self.speed = max(0.1, self.speed - 0.2)
            print(f"{Colors.GREEN}Speed: {self.speed:.1f}s{Colors.RESET}")
        elif key == '-':
            self.speed = min(3.0, self.speed + 0.2)
            print(f"{Colors.GREEN}Speed: {self.speed:.1f}s{Colors.RESET}")
        elif key == 'r':
            self.current_step = 0
            print(f"{Colors.GREEN}Restarted from beginning{Colors.RESET}")
        elif key == 'h':
            self.display_controls()
        
        return True
    
    def next_step(self):
        """Move to the next step."""
        if self.current_step < len(self.event_log) - 1:
            self.current_step += 1
        else:
            print(f"{Colors.YELLOW}End of replay reached{Colors.RESET}")
    
    def previous_step(self):
        """Move to the previous step."""
        if self.current_step > 0:
            self.current_step -= 1
        else:
            print(f"{Colors.YELLOW}Beginning of replay reached{Colors.RESET}")
    
    def play(self):
        """Main replay loop."""
        print(f"{Colors.BOLD}{Colors.GREEN}🎮 GAME REPLAY VIEWER 🎮{Colors.RESET}")
        print(f"Loaded replay with {len(self.event_log)} events")
        self.display_controls()
        
        try:
            while True:
                # Handle user input
                key = self.get_user_input()
                if not self.handle_input(key):
                    break
                
                # Auto-advance if not paused
                if not self.paused:
                    current_event = self.event_log[self.current_step]
                    
                    # Clear screen and display current state
                    self.clear_screen()
                    
                    # Display progress
                    progress = (self.current_step + 1) / len(self.event_log) * 100
                    print(f"{Colors.BOLD}Progress: {self.current_step + 1}/{len(self.event_log)} ({progress:.1f}%){Colors.RESET}")
                    print()
                    
                    # Display event information
                    self.display_event_info(current_event)
                    
                    # Get units for current state (reconstruct from events)
                    if "units" in current_event and current_event["units"]:
                        units = current_event["units"]
                    else:
                        # Reconstruct game state from event history
                        units = self._reconstruct_game_state(self.current_step)
                    
                    # Display board
                    acting_unit = current_event.get("acting_unit_idx") or current_event.get("unit_id")
                    self.draw_board(units, acting_unit)
                    
                    # Display unit stats
                    self.display_unit_stats(units)
                    
                    # Show speed and status
                    status = f"{Colors.RED}PAUSED{Colors.RESET}" if self.paused else f"{Colors.GREEN}PLAYING{Colors.RESET}"
                    print(f"Status: {status} | Speed: {self.speed:.1f}s | Press 'h' for help")
                    
                    # Auto-advance
                    if self.current_step < len(self.event_log) - 1:
                        time.sleep(self.speed)
                        self.current_step += 1
                    else:
                        print(f"\n{Colors.BOLD}{Colors.GREEN}🎉 REPLAY FINISHED! 🎉{Colors.RESET}")
                        print("Press 'r' to restart or 'q' to quit")
                        self.paused = True
                
                else:
                    time.sleep(0.1)  # Small delay when paused
                    
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}Replay interrupted by user{Colors.RESET}")

def load_replay(filename: str) -> List[Dict[str, Any]]:
    """Load replay data from JSON file and handle different formats."""
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
        
        # Handle different replay formats
        if isinstance(data, list):
            # Check if it's the simple format like your best_event_log.json
            if data and isinstance(data[0], dict):
                # Convert simple format to full event format
                converted_events = []
                for i, event in enumerate(data):
                    # Create a more complete event structure
                    full_event = {
                        "turn": event.get("turn", i // 2),
                        "phase": "movement",  # Default phase
                        "acting_unit_idx": event.get("unit_id"),
                        "target_unit_idx": None,
                        "action": event.get("action", 0),
                        "event_flags": {},
                        "unit_stats": {},
                        "units": []
                    }
                    
                    # Try to reconstruct unit positions from the event
                    if "position" in event and "hp" in event and "unit_id" in event:
                        unit = {
                            "id": event["unit_id"],
                            "col": event["position"][0] if len(event["position"]) > 0 else 0,
                            "row": event["position"][1] if len(event["position"]) > 1 else 0,
                            "cur_hp": event["hp"],
                            "hp_max": 4 if event["unit_id"] in [2, 4] else 3,  # AssaultIntercessor vs Intercessor
                            "player": 1 if event["unit_id"] in [3, 4] else 0,
                            "alive": event["hp"] > 0,
                            "unit_type": "AssaultIntercessor" if event["unit_id"] in [2, 4] else "Intercessor",
                            "name": f"Unit-{event['unit_id']}"
                        }
                        full_event["units"] = [unit]
                    
                    converted_events.append(full_event)
                
                return converted_events
            return data
        elif isinstance(data, dict):
            if 'log' in data:
                return data['log']
            elif 'events' in data:
                return data['events']
            else:
                # Single event, wrap in list
                return [data]
        else:
            print(f"{Colors.RED}Error: Invalid replay format{Colors.RESET}")
            return []
            
    except FileNotFoundError:
        print(f"{Colors.RED}Error: Replay file '{filename}' not found{Colors.RESET}")
        return []
    except json.JSONDecodeError:
        print(f"{Colors.RED}Error: Invalid JSON in replay file{Colors.RESET}")
        return []

def find_replay_files() -> List[str]:
    """Find available replay files."""
    replay_files = []
    possible_paths = [
        "ai/best_event_log.json",
        "ai/worst_event_log.json", 
        "best_event_log.json",
        "worst_event_log.json",
        "ai/best_episode.json",
        "ai/worst_episode.json"
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            replay_files.append(path)
    
    # Also check for any other JSON files in ai/ directory
    if os.path.exists("ai"):
        for file in os.listdir("ai"):
            if file.endswith(("_log.json", "_episode.json", "_replay.json")):
                full_path = os.path.join("ai", file)
                if full_path not in replay_files:
                    replay_files.append(full_path)
    
    return replay_files

def main():
    """Main function."""
    print(f"{Colors.BOLD}{Colors.CYAN}🎮 WH40K Game Replay Viewer 🎮{Colors.RESET}")
    print()
    
    # Check for command line argument
    if len(sys.argv) > 1:
        replay_file = sys.argv[1]
    else:
        # Find available replay files
        replay_files = find_replay_files()
        
        if not replay_files:
            print(f"{Colors.RED}No replay files found!{Colors.RESET}")
            print("Looking for files like:")
            print("  - ai/best_event_log.json")
            print("  - ai/worst_event_log.json")
            print("  - best_event_log.json")
            print("  - worst_event_log.json")
            return
        
        # Let user choose
        print("Available replay files:")
        for i, file in enumerate(replay_files, 1):
            size = os.path.getsize(file)
            print(f"  {i}. {file} ({size} bytes)")
        
        while True:
            try:
                choice = input(f"\nSelect replay file (1-{len(replay_files)}): ").strip()
                if choice.lower() == 'q':
                    return
                
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(replay_files):
                    replay_file = replay_files[choice_idx]
                    break
                else:
                    print(f"{Colors.RED}Invalid choice. Please enter 1-{len(replay_files)}{Colors.RESET}")
            except ValueError:
                print(f"{Colors.RED}Invalid input. Please enter a number or 'q' to quit{Colors.RESET}")
            except KeyboardInterrupt:
                print(f"\n{Colors.YELLOW}Cancelled{Colors.RESET}")
                return
    
    # Load and play replay
    print(f"\nLoading replay: {replay_file}")
    event_log = load_replay(replay_file)
    
    if not event_log:
        print(f"{Colors.RED}Failed to load replay or replay is empty{Colors.RESET}")
        return
    
    print(f"{Colors.GREEN}Loaded {len(event_log)} events{Colors.RESET}")
    print(f"{Colors.YELLOW}Starting replay in 3 seconds...{Colors.RESET}")
    
    for i in range(3, 0, -1):
        print(f"{i}...")
        time.sleep(1)
    
    # Create and start viewer
    viewer = GameReplayViewer(event_log)
    viewer.play()
    
    print(f"\n{Colors.CYAN}Thanks for watching! 🎮{Colors.RESET}")

if __name__ == "__main__":
    main()