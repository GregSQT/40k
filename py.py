#!/usr/bin/env python3
# test_numpy.py - Test numpy installation and functionality

import sys
import os

print("🔍 Python Environment Diagnostic")
print("=" * 50)

print(f"Python version: {sys.version}")
print(f"Python executable: {sys.executable}")
print(f"Current working directory: {os.getcwd()}")
print()

# Test numpy import
try:
    import numpy as np
    print("✅ Numpy imported successfully")
    print(f"   Numpy version: {np.__version__}")
    
    # Test basic functionality
    arr = np.array([1, 2, 3, 4, 5])
    print(f"   Basic array operation: {arr.mean()}")
    print("✅ Numpy functionality working")
    
except ImportError as e:
    print(f"❌ Numpy import failed: {e}")
    sys.exit(1)

# Test stable_baselines3
try:
    from stable_baselines3 import DQN
    print("✅ Stable Baselines3 imported successfully")
except ImportError as e:
    print(f"❌ Stable Baselines3 import failed: {e}")
    print("   Install with: pip install stable-baselines3[extra]")

# Test gym environment
try:
    sys.path.insert(0, "./ai")
    from gym40k import W40KEnv
    print("✅ W40K Environment imported successfully")
    
    # Quick environment test
    env = W40KEnv()
    obs, info = env.reset()
    print(f"   Environment created: {len(env.units)} units")
    env.close()
    
except ImportError as e:
    print(f"❌ W40K Environment import failed: {e}")
except Exception as e:
    print(f"⚠️  Environment creation warning: {e}")

print()
print("🎯 Diagnosis complete!")
print("Note: Pylance warnings about numpy are normal and can be ignored.")