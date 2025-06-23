#!/usr/bin/env python3
# quick_start.py - One-click training starter with fixed paths

import os
import subprocess
import sys

def main():
    print("W40K AI Training - Quick Start")
    print("=" * 40)
    
    # Ensure we're in the right directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    # Check if we have a model
    if os.path.exists("ai/model.zip"):
        print("Found existing model!")
        choice = input("What do you want to do?\n1. Test existing model\n2. Resume training\n3. Start new training\nChoice (1-3): ")
        
        if choice == "1":
            print("\nTesting model...")
            subprocess.run([sys.executable, os.path.join("ai", "test_model.py")])
        elif choice == "2":
            print("\nResuming training...")
            subprocess.run([sys.executable, os.path.join("ai", "simple_train.py"), "--resume"])
        elif choice == "3":
            print("\nStarting new training...")
            subprocess.run([sys.executable, os.path.join("ai", "simple_train.py")])
        else:
            print("Invalid choice")
    else:
        print("No model found. Starting training...")
        mode = input("Training mode?\n1. Quick (10k steps)\n2. Normal (100k steps)\n3. Full (1M steps)\nChoice (1-3): ")
        
        if mode == "1":
            subprocess.run([sys.executable, os.path.join("ai", "simple_train.py"), "--quick"])
        elif mode == "2":
            subprocess.run([sys.executable, os.path.join("ai", "simple_train.py")])
        elif mode == "3":
            subprocess.run([sys.executable, os.path.join("ai", "simple_train.py"), "--full"])
        else:
            print("Invalid choice, using normal mode")
            subprocess.run([sys.executable, os.path.join("ai", "simple_train.py")])

if __name__ == "__main__":
    main()
