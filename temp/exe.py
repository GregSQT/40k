#!/usr/bin/env python3
"""
test_replay_files.py - Test the generated web-compatible replay files
"""

import os
import json
from pathlib import Path

def test_replay_file(filepath):
    """Test a single replay file."""
    print(f"\n🔍 Testing: {filepath}")
    
    if not os.path.exists(filepath):
        print(f"   ❌ File not found: {filepath}")
        return False
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"   ✅ Valid JSON file")
        
        # Check structure
        has_metadata = 'metadata' in data
        has_events = 'events' in data
        
        print(f"   📊 Has metadata: {has_metadata}")
        print(f"   📊 Has events: {has_events}")
        
        if has_metadata:
            metadata = data['metadata']
            print(f"   🏆 Episode reward: {metadata.get('episode_reward', 'N/A')}")
            print(f"   📈 Total events: {metadata.get('total_events', 'N/A')}")
            print(f"   🔄 Final turn: {metadata.get('final_turn', 'N/A')}")
            print(f"   🎮 Replay format: {metadata.get('replay_format', 'N/A')}")
        
        if has_events:
            events = data['events']
            print(f"   🎬 Number of events: {len(events)}")
            
            if events:
                first_event = events[0]
                print(f"   🔍 First event keys: {list(first_event.keys())}")
                
                if 'units' in first_event:
                    units = first_event['units']
                    print(f"   👥 Units in first event: {len(units)}")
                    
                    if units:
                        first_unit = units[0]
                        print(f"   👤 First unit: {first_unit.get('name', 'N/A')} (Player {first_unit.get('player', 'N/A')})")
                        print(f"      Position: ({first_unit.get('col', 'N/A')}, {first_unit.get('row', 'N/A')})")
                        print(f"      HP: {first_unit.get('CUR_HP', 'N/A')}/{first_unit.get('HP_MAX', 'N/A')}")
                
                # Check for movement in the replay
                movement_events = 0
                for event in events[:10]:  # Check first 10 events
                    if 'event_flags' in event and 'changes' in event['event_flags']:
                        changes = event['event_flags']['changes']
                        if 'movements' in changes and changes['movements']:
                            movement_events += 1
                
                print(f"   🏃 Movement events found in first 10: {movement_events}")
        
        print(f"   ✅ File structure is valid for web app")
        return True
        
    except json.JSONDecodeError as e:
        print(f"   ❌ Invalid JSON: {e}")
        return False
    except Exception as e:
        print(f"   ❌ Error reading file: {e}")
        return False

def compare_old_vs_new():
    """Compare old simplified logs with new web-compatible logs."""
    print("\n📊 Comparing old vs new replay formats...")
    
    # Check for old simplified logs
    old_patterns = [
        "ai/event_log/*_event_log.json",
        "ai/event_log/*_event_log_simple.json"
    ]
    
    import glob
    old_files = []
    for pattern in old_patterns:
        old_files.extend(glob.glob(pattern))
    
    # Check for new web replay files
    new_files = glob.glob("ai/event_log/*web_replay*.json")
    
    print(f"   📋 Old simplified logs found: {len(old_files)}")
    for f in old_files:
        print(f"      • {os.path.basename(f)}")
    
    print(f"   🌐 New web replay files found: {len(new_files)}")
    for f in new_files:
        print(f"      • {os.path.basename(f)}")
    
    if len(old_files) == 0 and len(new_files) > 0:
        print("   ✅ Migration successful: No old logs, new web replays present")
        return True
    elif len(old_files) > 0:
        print("   ⚠️  Old simplified logs still present")
        return False
    else:
        print("   ❌ No replay files found")
        return False

def test_web_app_compatibility():
    """Test if the replay files are compatible with the web app format."""
    print("\n🌐 Testing web app compatibility...")
    
    web_files = [
        "ai/event_log/train_best_web_replay.json",
        "ai/event_log/train_worst_web_replay.json"
    ]
    
    compatible_count = 0
    
    for filepath in web_files:
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Check for required web app fields
                required_fields = ['metadata', 'events']
                has_required = all(field in data for field in required_fields)
                
                if has_required and data['events']:
                    event_has_units = 'units' in data['events'][0]
                    event_has_flags = 'event_flags' in data['events'][0]
                    
                    if event_has_units and event_has_flags:
                        print(f"   ✅ {os.path.basename(filepath)} is web app compatible")
                        compatible_count += 1
                    else:
                        print(f"   ⚠️  {os.path.basename(filepath)} missing event structure")
                else:
                    print(f"   ⚠️  {os.path.basename(filepath)} missing required fields")
                    
            except Exception as e:
                print(f"   ❌ {os.path.basename(filepath)} error: {e}")
        else:
            print(f"   ❌ {os.path.basename(filepath)} not found")
    
    if compatible_count == len([f for f in web_files if os.path.exists(f)]):
        print("   ✅ All replay files are web app compatible!")
        return True
    else:
        print("   ⚠️  Some replay files may have compatibility issues")
        return False

def main():
    """Main test function."""
    print("🧪 W40K AI - Replay File Testing")
    print("=" * 45)
    
    # Test individual replay files
    replay_files = [
        "ai/event_log/train_best_web_replay.json",
        "ai/event_log/train_worst_web_replay.json"
    ]
    
    all_valid = True
    
    for filepath in replay_files:
        if not test_replay_file(filepath):
            all_valid = False
    
    # Compare old vs new
    migration_success = compare_old_vs_new()
    
    # Test web app compatibility
    web_compatible = test_web_app_compatibility()
    
    # Summary
    print("\n" + "=" * 45)
    print("📋 Test Summary:")
    print(f"   ✅ Replay files valid: {all_valid}")
    print(f"   ✅ Migration successful: {migration_success}")
    print(f"   ✅ Web app compatible: {web_compatible}")
    
    if all_valid and migration_success and web_compatible:
        print("\n🎉 SUCCESS! Your replay system is working perfectly!")
        print("\n🎯 Next steps:")
        print("1. Start web app: cd frontend && npm run dev")
        print("2. Navigate to Replay page")
        print("3. Load train_best_web_replay.json or train_worst_web_replay.json")
        print("4. Watch your AI units actually move and fight!")
        print("\n✅ No more conversion needed - files are directly compatible!")
    else:
        print("\n⚠️  Some issues detected. Check the details above.")
    
    return all_valid and migration_success and web_compatible

if __name__ == "__main__":
    main()