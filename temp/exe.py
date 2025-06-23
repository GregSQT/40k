#!/usr/bin/env python3
"""
check_project.py - Diagnostic script to check project structure and imports
"""

import os
import sys

def check_project_structure():
    """Check if the project has the expected structure."""
    print("🔍 Project Structure Diagnostic")
    print("=" * 40)
    
    # Get current directory
    current_dir = os.getcwd()
    print(f"Current directory: {current_dir}")
    print()
    
    # Check for key files and directories
    checks = [
        ("ai/", "AI directory"),
        ("ai/gym40k.py", "Gym environment file"),
        ("ai/__init__.py", "AI package init (optional)"),
        ("frontend/", "Frontend directory"),
        ("frontend/src/", "Frontend source"),
        ("ai/rewards_master.json", "Rewards configuration"),
        ("ai/scenario.json", "Scenario file (optional)"),
        ("ai/model.zip", "Trained model (optional)"),
    ]
    
    print("📁 File/Directory Check:")
    for path, description in checks:
        exists = os.path.exists(path)
        status = "✓" if exists else "❌"
        print(f"  {status} {path:<20} - {description}")
    
    print()
    
    # Check Python path
    print("🐍 Python Path:")
    for i, path in enumerate(sys.path[:5]):  # Show first 5 entries
        print(f"  {i}: {path}")
    if len(sys.path) > 5:
        print(f"  ... and {len(sys.path) - 5} more")
    
    print()
    
    # Check imports
    print("📦 Import Test:")
    
    # Test stable-baselines3
    try:
        from stable_baselines3 import DQN
        print("  ✓ stable-baselines3 import successful")
    except ImportError as e:
        print(f"  ❌ stable-baselines3 import failed: {e}")
    
    # Test gym40k import methods
    import_methods = [
        ("from gym40k import W40KEnv", "Direct import"),
        ("from ai.gym40k import W40KEnv", "Module import"),
        ("import ai.gym40k", "Module reference"),
    ]
    
    for import_code, description in import_methods:
        try:
            exec(import_code)
            print(f"  ✓ {description}: {import_code}")
            break
        except ImportError as e:
            print(f"  ❌ {description}: {import_code} - {e}")
    else:
        print("  ❌ All import methods failed!")
        print()
        print("🔧 Suggested fixes:")
        print("  1. Make sure you're running from the project root directory")
        print("  2. Check that ai/gym40k.py exists and contains W40KEnv class")
        print("  3. Try adding an empty __init__.py file to the ai/ directory")
        return False
    
    print()
    
    # Check ai/gym40k.py content
    gym_file = "ai/gym40k.py"
    if os.path.exists(gym_file):
        print("🔍 Checking ai/gym40k.py content:")
        try:
            with open(gym_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if "class W40KEnv" in content:
                print("  ✓ W40KEnv class found")
            else:
                print("  ❌ W40KEnv class not found in file")
            
            if "import gymnasium" in content or "import gym" in content:
                print("  ✓ Gymnasium/Gym import found")
            else:
                print("  ⚠ No Gymnasium/Gym import found")
                
            print(f"  📊 File size: {len(content)} characters")
            
        except Exception as e:
            print(f"  ❌ Error reading file: {e}")
    
    print()
    
    # Recommendations
    print("💡 Next Steps:")
    if not os.path.exists("ai/gym40k.py"):
        print("  1. ❌ Critical: ai/gym40k.py is missing!")
        print("     - This file should contain the W40KEnv class")
        print("     - Check your ai/ directory")
    else:
        print("  1. ✓ ai/gym40k.py exists")
    
    if not os.path.exists("ai/__init__.py"):
        print("  2. Create ai/__init__.py (can be empty)")
        print("     - This makes ai/ a Python package")
        print("     - Run: touch ai/__init__.py  (Unix) or type nul > ai\\__init__.py  (Windows)")
    
    print("  3. Run training from project root:")
    print("     - python ai/simple_train.py --quick")
    
    print("  4. If imports still fail, run this diagnostic again")
    
    return True

def create_init_files():
    """Create missing __init__.py files."""
    print("\n🔧 Creating missing __init__.py files:")
    
    directories = ["ai"]
    
    for directory in directories:
        if os.path.exists(directory):
            init_file = os.path.join(directory, "__init__.py")
            if not os.path.exists(init_file):
                try:
                    with open(init_file, 'w') as f:
                        f.write('# AI module\n')
                    print(f"  ✓ Created {init_file}")
                except Exception as e:
                    print(f"  ❌ Failed to create {init_file}: {e}")
            else:
                print(f"  ✓ {init_file} already exists")
        else:
            print(f"  ⚠ {directory}/ directory not found")

def main():
    """Main diagnostic function."""
    try:
        success = check_project_structure()
        
        # Offer to create missing files
        if success:
            response = input("\nCreate missing __init__.py files? (y/n): ").lower().strip()
            if response in ['y', 'yes']:
                create_init_files()
                print("\n✅ Setup completed! Try running the training script now.")
            else:
                print("\n📝 Manual setup required - see recommendations above.")
        
        return success
        
    except KeyboardInterrupt:
        print("\n⏹️ Diagnostic interrupted")
        return False
    except Exception as e:
        print(f"\n💥 Diagnostic failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)