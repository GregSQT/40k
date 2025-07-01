#!/usr/bin/env python3
"""
Replay Format Converter - Convert simple replay format to web app format
"""

import os
import json
import sys
from typing import List, Dict, Any, Optional

class ReplayConverter:
    def __init__(self):
        # Define unit templates based on your game
        self.unit_templates = {
            1: {
                "id": 1,
                "name": "P-I",
                "type": "Intercessor", 
                "player": 0,
                "color": 0x244488,
                "MOVE": 4,
                "HP_MAX": 3,
                "RNG_RNG": 8,
                "RNG_DMG": 2,
                "CC_DMG": 1,
                "ICON": "/icons/Intercessor.webp"
            },
            2: {
                "id": 2,
                "name": "P-A",
                "type": "Assault Intercessor",
                "player": 0,
                "color": 0xff3333,
                "MOVE": 6,
                "HP_MAX": 4,
                "RNG_RNG": 4,
                "RNG_DMG": 1,
                "CC_DMG": 2,
                "ICON": "/icons/AssaultIntercessor.webp"
            },
            3: {
                "id": 3,
                "name": "A-I",
                "type": "Intercessor",
                "player": 1,
                "color": 0x882222,
                "MOVE": 4,
                "HP_MAX": 3,
                "RNG_RNG": 8,
                "RNG_DMG": 2,
                "CC_DMG": 1,
                "ICON": "/icons/Intercessor.webp"
            },
            4: {
                "id": 4,
                "name": "A-A",
                "type": "Assault Intercessor",
                "player": 1,
                "color": 0x6633cc,
                "MOVE": 6,
                "HP_MAX": 4,
                "RNG_RNG": 4,
                "RNG_DMG": 1,
                "CC_DMG": 2,
                "ICON": "/icons/AssaultIntercessor.webp"
            }
        }
        
        # Default starting positions (from your scenario.json)
        self.default_positions = {
            1: {"col": 23, "row": 17},  # P-I
            2: {"col": 1, "row": 17},   # P-A  
            3: {"col": 0, "row": 1},    # A-I
            4: {"col": 22, "row": 1}    # A-A
        }
        
        # Action mapping for better display
        self.action_names = {
            0: "move_closer",
            1: "move_away", 
            2: "move_to_safe",
            3: "shoot_closest",
            4: "shoot_weakest",
            5: "charge_closest",
            6: "wait",
            7: "attack_adjacent"
        }
        
        # Phase mapping based on action types
        self.action_to_phase = {
            0: "move", 1: "move", 2: "move",  # Movement actions
            3: "shoot", 4: "shoot",           # Shooting actions
            5: "charge",                      # Charging
            7: "combat",                      # Combat
            6: "move"                         # Wait/end turn
        }

    def find_replay_files(self) -> List[str]:
        """Find replay files in new unified structure."""
        replay_files = []
        
        # New unified event log locations
        event_log_locations = [
            "ai/event_log/",           # Main unified location
            "ai/ai/event_log/",        # Nested location (your current structure)
            "ai/",                     # Direct in ai/ folder
            "./"                       # Current directory
        ]
        
        # File patterns to look for
        file_patterns = [
            "train_best_game_replay.json",    # Primary required format from AI_INSTRUCTIONS.md
            "train_best_event_log.json",
            "train_worst_event_log.json",
            "eval_best_event_log.json", 
            "eval_worst_event_log.json",
            "best_event_log.json",      # Legacy naming
            "worst_event_log.json",     # Legacy naming
            "best_episode.json",
            "worst_episode.json"
        ]
        
        print("🔍 Searching for replay files...")
        
        for location in event_log_locations:
            if os.path.exists(location):
                print(f"   📁 Checking: {location}")
                
                if os.path.isdir(location):
                    # Check directory for replay files
                    for filename in os.listdir(location):
                        if any(pattern in filename for pattern in file_patterns):
                            full_path = os.path.join(location, filename)
                            if full_path not in replay_files:
                                replay_files.append(full_path)
                                print(f"      ✅ Found: {filename}")
                
                # Also check for direct file matches
                for pattern in file_patterns:
                    full_path = os.path.join(location, pattern)
                    if os.path.exists(full_path) and full_path not in replay_files:
                        replay_files.append(full_path)
                        print(f"      ✅ Found: {pattern}")
        
        return replay_files

    def load_simple_replay(self, filename: str) -> List[Dict[str, Any]]:
        """Load replay file handling different formats."""
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
            
            if isinstance(data, list):
                print(f"   📋 Loaded {len(data)} events from list format")
                return data
            elif isinstance(data, dict):
                if 'log' in data:
                    print(f"   📋 Loaded {len(data['log'])} events from log format")
                    return data['log']
                elif 'events' in data:
                    print(f"   📋 Loaded {len(data['events'])} events from events format")
                    return data['events']
                else:
                    # Single event, wrap in list
                    print(f"   📋 Loaded single event, wrapping in list")
                    return [data]
            else:
                print(f"   ❌ Unexpected format in {filename}")
                return []
                
        except FileNotFoundError:
            print(f"   ❌ File not found: {filename}")
            return []
        except json.JSONDecodeError as e:
            print(f"   ❌ JSON decode error in {filename}: {e}")
            return []

    def reconstruct_game_state(self, events: List[Dict[str, Any]], up_to_index: int) -> List[Dict[str, Any]]:
        """Reconstruct the full game state at a given point in time."""
        units = []
        
        # Initialize all units with default values
        for unit_id, template in self.unit_templates.items():
            unit = template.copy()
            
            # Set initial position
            if unit_id in self.default_positions:
                unit.update(self.default_positions[unit_id])
            else:
                unit.update({"col": 0, "row": 0})
            
            # Set initial HP
            unit["CUR_HP"] = unit["HP_MAX"]
            
            units.append(unit)
        
        # Apply all events up to the current index
        for i in range(min(up_to_index + 1, len(events))):
            event = events[i]
            
            # Handle different event formats
            if "units" in event and isinstance(event["units"], list):
                # Full format with units array - update all units
                for event_unit in event["units"]:
                    unit_id = event_unit.get("id")
                    if unit_id is not None:
                        # Find the unit in our list and update it
                        for unit in units:
                            if unit["id"] == unit_id:
                                unit.update(event_unit)
                                break
            else:
                # Simple format - try to extract info
                unit_id = event.get("unit_id")
                if unit_id is not None:
                    # Find the unit in our list
                    for unit in units:
                        if unit["id"] == unit_id:
                            # Update position if provided
                            if "position" in event and len(event["position"]) >= 2:
                                unit["col"] = event["position"][0]
                                unit["row"] = event["position"][1]
                            
                            # Update HP if provided
                            if "hp" in event:
                                unit["CUR_HP"] = max(0, event["hp"])
                            
                            # Estimate HP based on game progression (fallback)
                            if "ai_units_alive" in event and "enemy_units_alive" in event:
                                # This is very basic - you might want to improve this
                                pass
                            
                            break
        
        return units

    def convert_to_web_format(self, simple_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert simple format to web app format."""
        web_events = []
        
        for i, event in enumerate(simple_events):
            # Get basic event info
            turn = event.get("turn", (i // 2) + 1)  # Approximate turn calculation
            action = event.get("action", 0)
            unit_id = event.get("unit_id", 1)  # Default to first unit if not specified
            
            # Determine phase from action
            phase = self.action_to_phase.get(action, "move")
            
            # Reconstruct game state at this point
            units = self.reconstruct_game_state(simple_events, i)
            
            # Create web format event
            web_event = {
                "turn": turn,
                "phase": phase,
                "acting_unit_idx": unit_id,
                "target_unit_idx": None,  # Simple format doesn't track targets
                "event_flags": {
                    "action_name": self.action_names.get(action, f"action_{action}"),
                    "action_id": action,
                    "reward": event.get("reward", 0),
                    "ai_units_alive": event.get("ai_units_alive", 2),
                    "enemy_units_alive": event.get("enemy_units_alive", 2)
                },
                "unit_stats": {},
                "units": units
            }
            
            web_events.append(web_event)
        
        return web_events

    def convert_file(self, input_file: str, output_file: Optional[str] = None) -> bool:
        """Convert a single replay file."""
        print(f"🔄 Converting {input_file}...")
        
        # Load simple format
        simple_events = self.load_simple_replay(input_file)
        if not simple_events:
            return False
        
        print(f"   📊 Processing {len(simple_events)} events")
        
        # Convert to web format
        web_events = self.convert_to_web_format(simple_events)
        
        # Determine output filename
        if output_file is None:
            # Create output filename based on input
            input_dir = os.path.dirname(input_file)
            input_name = os.path.basename(input_file)
            
            # Remove extension and add _web suffix
            base_name = os.path.splitext(input_name)[0]
            output_name = f"{base_name}_web.json"
            
            # Place in same directory as input, or current directory if input is in nested structure
            if "ai/ai/" in input_file:
                output_file = os.path.join("ai/event_log", output_name)
                os.makedirs("ai/event_log", exist_ok=True)
            else:
                output_file = os.path.join(input_dir, output_name)
        
        # Save converted format
        try:
            with open(output_file, 'w') as f:
                json.dump(web_events, f, indent=2)
            
            print(f"   ✅ Converted to {output_file}")
            print(f"   📊 Generated {len(web_events)} web events")
            return True
            
        except Exception as e:
            print(f"   ❌ Failed to save {output_file}: {e}")
            return False

    def convert_all(self):
        """Convert all found replay files."""
        print("🎮 WH40K Replay Converter for Web App (Updated)")
        print("=" * 50)
        
        replay_files = self.find_replay_files()
        
        if not replay_files:
            print("❌ No replay files found!")
            print("\n📁 Current directory structure:")
            
            # Show what we actually found
            for root, dirs, files in os.walk("ai"):
                level = root.replace("ai", "").count(os.sep)
                indent = " " * 2 * level
                print(f"{indent}📁 {os.path.basename(root)}/")
                subindent = " " * 2 * (level + 1)
                for file in files:
                    if file.endswith('.json'):
                        print(f"{subindent}📄 {file}")
            
            print("\n🔍 Looking for files like:")
            print("  - ai/event_log/train_best_event_log.json")
            print("  - ai/event_log/train_worst_event_log.json")
            print("  - ai/ai/event_log/train_best_event_log.json")
            print("  - ai/ai/event_log/train_worst_event_log.json")
            return
        
        print(f"📁 Found {len(replay_files)} replay files:")
        for file in replay_files:
            size = os.path.getsize(file) if os.path.exists(file) else 0
            print(f"   • {file} ({size} bytes)")
        print()
        
        # Convert each file
        success_count = 0
        for file in replay_files:
            if self.convert_file(file):
                success_count += 1
            print()  # Add spacing between files
        
        print("=" * 50)
        print(f"✅ Conversion complete: {success_count}/{len(replay_files)} files converted")
        
        if success_count > 0:
            print("\n🌐 How to use in web app:")
            print("1. Start the web app: cd frontend && npm run dev")
            print("2. Navigate to the Replay page")
            print("3. Click 'Load Replay File'")
            print("4. Select one of the *_web.json files")
            print("5. Watch your AI gameplay in the web interface!")
            
            print("\n📁 Web-ready files created:")
            # List the web files that were created
            for root, dirs, files in os.walk("."):
                for file in files:
                    if file.endswith("_web.json"):
                        print(f"   • {os.path.join(root, file)}")

def main():
    converter = ReplayConverter()
    
    if len(sys.argv) > 1:
        # Convert specific file
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else None
        
        if not os.path.exists(input_file):
            print(f"❌ File not found: {input_file}")
            return
        
        print("🎮 WH40K Replay Converter (Updated)")
        print("=" * 35)
        converter.convert_file(input_file, output_file)
    else:
        # Convert all found files
        converter.convert_all()

if __name__ == "__main__":
    main()