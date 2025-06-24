#!/usr/bin/env python3
"""
Replay Format Converter - Convert simple replay format to web app format
"""

import json
import os
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
        
        # Default starting positions (you might want to adjust these)
        self.default_positions = {
            1: {"col": 23, "row": 12},  # P-I
            2: {"col": 1, "row": 12},   # P-A  
            3: {"col": 0, "row": 5},    # A-I
            4: {"col": 22, "row": 3}    # A-A
        }
        
        # Action mapping for better display
        self.action_names = {
            0: "move_close",
            1: "move_away", 
            2: "move_to_safe",
            3: "shoot",
            4: "charge",
            5: "wait",
            6: "attack",
            7: "end_turn"
        }
        
        # Phase mapping based on action types
        self.action_to_phase = {
            0: "move", 1: "move", 2: "move",  # Movement actions
            3: "shoot",                        # Shooting
            4: "charge",                       # Charging
            6: "combat",                       # Combat
            5: "move", 7: "move"              # Wait/end turn
        }

    def load_simple_replay(self, filename: str) -> List[Dict[str, Any]]:
        """Load the simple replay format."""
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
            
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'log' in data:
                return data['log']
            else:
                print(f"❌ Unexpected replay format in {filename}")
                return []
                
        except FileNotFoundError:
            print(f"❌ File not found: {filename}")
            return []
        except json.JSONDecodeError as e:
            print(f"❌ JSON decode error in {filename}: {e}")
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
            unit_id = event.get("unit_id")
            
            if unit_id is not None:
                # Find the unit in our list
                unit = next((u for u in units if u["id"] == unit_id), None)
                if unit:
                    # Update position if provided
                    if "position" in event and len(event["position"]) >= 2:
                        unit["col"] = event["position"][0]
                        unit["row"] = event["position"][1]
                    
                    # Update HP if provided
                    if "hp" in event:
                        unit["CUR_HP"] = max(0, event["hp"])
        
        return units

    def convert_to_web_format(self, simple_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert simple format to web app format."""
        web_events = []
        
        for i, event in enumerate(simple_events):
            # Get basic event info
            turn = event.get("turn", i // 4)  # Approximate turn calculation
            unit_id = event.get("unit_id")
            action = event.get("action", 0)
            
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
                    "action_id": action
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
        
        print(f"   📖 Loaded {len(simple_events)} events")
        
        # Convert to web format
        web_events = self.convert_to_web_format(simple_events)
        
        # Determine output filename
        if output_file is None:
            base_name = os.path.splitext(input_file)[0]
            output_file = f"{base_name}_web.json"
        
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

    def find_replay_files(self) -> List[str]:
        """Find replay files to convert."""
        replay_files = []
        
        # Common replay file locations
        possible_files = [
            "ai/best_event_log.json",
            "ai/worst_event_log.json",
            "best_event_log.json", 
            "worst_event_log.json",
            "ai/best_episode.json",
            "ai/worst_episode.json"
        ]
        
        for file_path in possible_files:
            if os.path.exists(file_path):
                replay_files.append(file_path)
        
        # Also check for other JSON files in ai/ directory
        if os.path.exists("ai"):
            for filename in os.listdir("ai"):
                if filename.endswith(("_log.json", "_episode.json")) and filename not in [os.path.basename(f) for f in replay_files]:
                    full_path = os.path.join("ai", filename)
                    replay_files.append(full_path)
        
        return replay_files

    def convert_all(self):
        """Convert all found replay files."""
        print("🎮 WH40K Replay Converter for Web App")
        print("=" * 40)
        
        replay_files = self.find_replay_files()
        
        if not replay_files:
            print("❌ No replay files found!")
            print("\nLooking for files like:")
            print("  - ai/best_event_log.json")
            print("  - ai/worst_event_log.json") 
            print("  - best_event_log.json")
            print("  - worst_event_log.json")
            return
        
        print(f"📁 Found {len(replay_files)} replay files:")
        for file in replay_files:
            print(f"   • {file}")
        print()
        
        # Convert each file
        success_count = 0
        for file in replay_files:
            if self.convert_file(file):
                success_count += 1
            print()  # Add spacing between files
        
        print("=" * 40)
        print(f"✅ Conversion complete: {success_count}/{len(replay_files)} files converted")
        
        if success_count > 0:
            print("\n🌐 How to use in web app:")
            print("1. Start the web app: cd frontend && npm run dev")
            print("2. Navigate to the Replay page")
            print("3. Click 'Load Replay File'")
            print("4. Select one of the *_web.json files")
            print("5. Watch your AI gameplay in the web interface!")

def main():
    converter = ReplayConverter()
    
    if len(sys.argv) > 1:
        # Convert specific file
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else None
        
        if not os.path.exists(input_file):
            print(f"❌ File not found: {input_file}")
            return
        
        print("🎮 WH40K Replay Converter")
        print("=" * 30)
        converter.convert_file(input_file, output_file)
    else:
        # Convert all found files
        converter.convert_all()

if __name__ == "__main__":
    main()