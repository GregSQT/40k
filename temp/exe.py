#!/usr/bin/env python3
"""
cleanup_nested_ai.py - Fix the nested ai/ai/ directory issue
"""

import os
import shutil
import json
from datetime import datetime

def cleanup_nested_ai():
    """Clean up the nested ai/ai/ directory structure."""
    
    print("🔧 Cleaning up nested ai/ai/ directory structure")
    print("=" * 50)
    
    # Check if the problem exists
    nested_ai_path = "ai/ai"
    if not os.path.exists(nested_ai_path):
        print("✅ No nested ai/ai/ directory found. Nothing to clean up.")
        return True
    
    print(f"📁 Found nested directory: {nested_ai_path}")
    
    # Create backup timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = f"ai_cleanup_backup_{timestamp}"
    
    # Step 1: Backup the entire ai/ directory before making changes
    print(f"📦 Creating backup: {backup_dir}")
    try:
        shutil.copytree("ai", backup_dir)
        print(f"✅ Backup created successfully")
    except Exception as e:
        print(f"❌ Failed to create backup: {e}")
        return False
    
    # Step 2: Identify and merge files from nested directory
    nested_files_to_merge = []
    
    # Check for event_log directory
    nested_event_log = os.path.join(nested_ai_path, "event_log")
    main_event_log = "ai/event_log"
    
    if os.path.exists(nested_event_log):
        print(f"📋 Found nested event logs in: {nested_event_log}")
        
        # Ensure main event_log directory exists
        os.makedirs(main_event_log, exist_ok=True)
        
        # List files in nested event_log
        for file in os.listdir(nested_event_log):
            nested_file = os.path.join(nested_event_log, file)
            main_file = os.path.join(main_event_log, file)
            
            if os.path.isfile(nested_file):
                # Check if file already exists in main location
                if os.path.exists(main_file):
                    # Compare file sizes and modification times
                    nested_stat = os.stat(nested_file)
                    main_stat = os.stat(main_file)
                    
                    if nested_stat.st_mtime > main_stat.st_mtime:
                        print(f"   📄 {file}: Nested version is newer, will replace")
                        nested_files_to_merge.append((nested_file, main_file, "replace"))
                    else:
                        print(f"   📄 {file}: Main version is newer, keeping main")
                        nested_files_to_merge.append((nested_file, main_file, "keep_main"))
                else:
                    print(f"   📄 {file}: Only in nested, will move")
                    nested_files_to_merge.append((nested_file, main_file, "move"))
    
    # Check for scenario.json
    nested_scenario = os.path.join(nested_ai_path, "scenario.json")
    main_scenario = "ai/scenario.json"
    
    if os.path.exists(nested_scenario):
        print(f"📄 Found nested scenario.json")
        if os.path.exists(main_scenario):
            # Compare the files
            try:
                with open(nested_scenario, 'r') as f:
                    nested_data = json.load(f)
                with open(main_scenario, 'r') as f:
                    main_data = json.load(f)
                
                if nested_data == main_data:
                    print(f"   📄 scenario.json: Files are identical")
                    nested_files_to_merge.append((nested_scenario, main_scenario, "identical"))
                else:
                    print(f"   📄 scenario.json: Files differ, will backup nested as scenario_nested.json")
                    backup_scenario = "ai/scenario_nested.json"
                    nested_files_to_merge.append((nested_scenario, backup_scenario, "move"))
            except Exception as e:
                print(f"   ⚠️  Could not compare scenario files: {e}")
                backup_scenario = "ai/scenario_nested.json"
                nested_files_to_merge.append((nested_scenario, backup_scenario, "move"))
        else:
            print(f"   📄 scenario.json: Only in nested, will move")
            nested_files_to_merge.append((nested_scenario, main_scenario, "move"))
    
    # Step 3: Execute the merge operations
    print(f"\n🔄 Executing file operations...")
    
    for source, target, operation in nested_files_to_merge:
        try:
            if operation == "replace":
                print(f"   🔄 Replacing {target} with newer version")
                shutil.copy2(source, target)
            elif operation == "move":
                print(f"   📁 Moving {os.path.basename(source)} to main location")
                shutil.copy2(source, target)
            elif operation == "keep_main":
                print(f"   ✅ Keeping existing {os.path.basename(target)}")
            elif operation == "identical":
                print(f"   ✅ Files identical: {os.path.basename(target)}")
        except Exception as e:
            print(f"   ❌ Failed to process {source}: {e}")
    
    # Step 4: Remove the nested ai/ directory
    print(f"\n🗑️  Removing nested directory: {nested_ai_path}")
    try:
        shutil.rmtree(nested_ai_path)
        print(f"✅ Nested directory removed successfully")
    except Exception as e:
        print(f"❌ Failed to remove nested directory: {e}")
        return False
    
    # Step 5: Verify the cleanup
    print(f"\n🔍 Verifying cleanup...")
    
    if os.path.exists(nested_ai_path):
        print(f"❌ Nested directory still exists!")
        return False
    
    # Check that main files exist
    essential_files = [
        "ai/gym40k.py",
        "ai/train.py", 
        "ai/scenario.json",
        "ai/event_log"  # directory
    ]
    
    missing_files = []
    for file_path in essential_files:
        if not os.path.exists(file_path):
            missing_files.append(file_path)
    
    if missing_files:
        print(f"⚠️  Warning: Some essential files are missing:")
        for missing in missing_files:
            print(f"   - {missing}")
    else:
        print(f"✅ All essential files present")
    
    # Step 6: Summary
    print(f"\n📊 CLEANUP SUMMARY")
    print(f"=" * 30)
    print(f"✅ Nested ai/ai/ directory removed")
    print(f"📦 Backup created: {backup_dir}")
    print(f"📁 Files processed: {len(nested_files_to_merge)}")
    
    if missing_files:
        print(f"⚠️  Missing files: {len(missing_files)}")
    
    print(f"\n🎯 Next Steps:")
    print(f"1. Test your AI training: python ai/train.py --debug")
    print(f"2. If everything works, you can delete: {backup_dir}")
    print(f"3. If problems occur, restore from: {backup_dir}")
    
    return True

def restore_from_backup():
    """Helper function to restore from backup if needed."""
    import glob
    
    backups = glob.glob("ai_cleanup_backup_*")
    if not backups:
        print("❌ No cleanup backups found")
        return False
    
    # Find the most recent backup
    latest_backup = max(backups, key=os.path.getmtime)
    
    print(f"🔄 Restoring from backup: {latest_backup}")
    
    # Remove current ai/ directory
    if os.path.exists("ai"):
        shutil.rmtree("ai")
    
    # Restore from backup
    shutil.copytree(latest_backup, "ai")
    
    print(f"✅ Restored from backup successfully")
    return True

def main():
    """Main cleanup function."""
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--restore":
        return restore_from_backup()
    
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("🔧 AI Directory Cleanup Tool")
        print("=" * 30)
        print("Usage:")
        print("  python cleanup_nested_ai.py           # Clean up nested directories")
        print("  python cleanup_nested_ai.py --restore # Restore from backup")
        print("  python cleanup_nested_ai.py --help    # Show this help")
        return True
    
    return cleanup_nested_ai()

if __name__ == "__main__":
    try:
        success = main()
        if success:
            print("\n✅ Cleanup completed successfully!")
        else:
            print("\n❌ Cleanup failed!")
    except KeyboardInterrupt:
        print("\n⏹️  Cleanup interrupted")
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        import traceback
        traceback.print_exc()