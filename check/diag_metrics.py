#!/usr/bin/env python3
"""
Diagnostic script to find WHERE metrics_tracker is actually writing files.
This will tell us if the _on_training_start() fix worked.
"""
import os
import glob

print("=" * 70)
print("TENSORBOARD DIRECTORY STRUCTURE")
print("=" * 70)

tensorboard_base = "./tensorboard/"

if not os.path.exists(tensorboard_base):
    print(f"❌ {tensorboard_base} does not exist")
    exit(1)

# Find all subdirectories
subdirs = [d for d in glob.glob(f"{tensorboard_base}/*") if os.path.isdir(d)]

if not subdirs:
    print(f"❌ No subdirectories in {tensorboard_base}")
    exit(1)

print(f"\n📂 Found {len(subdirs)} subdirectories:\n")

for subdir in sorted(subdirs):
    dir_name = os.path.basename(subdir)
    event_files = glob.glob(f"{subdir}/events.out.tfevents.*")
    
    if event_files:
        # Get file size and modification time
        latest_event = max(event_files, key=os.path.getmtime)
        file_size = os.path.getsize(latest_event)
        mod_time = os.path.getmtime(latest_event)
        
        print(f"📁 {dir_name}/")
        print(f"   📄 Event file: {os.path.basename(latest_event)}")
        print(f"   📊 Size: {file_size:,} bytes")
        print(f"   🕒 Modified: {os.path.getmtime(latest_event)}")
        print()

print("=" * 70)
print("ANALYSIS")
print("=" * 70)

# Check for common patterns
ppo_dirs = [d for d in subdirs if 'PPO' in os.path.basename(d)]
agent_dirs = [d for d in subdirs if 'SpaceMarine' in os.path.basename(d) or 'phase' in os.path.basename(d)]

print(f"\n🤖 SB3 directories (PPO_*): {len(ppo_dirs)}")
for d in ppo_dirs:
    print(f"   • {os.path.basename(d)}")

print(f"\n🎯 Agent-specific directories: {len(agent_dirs)}")
for d in agent_dirs:
    print(f"   • {os.path.basename(d)}")

if len(ppo_dirs) > 0 and len(agent_dirs) > 0:
    print("\n❌ PROBLEM DETECTED: Both SB3 and agent-specific directories exist")
    print("   This means _on_training_start() fix did NOT work")
    print("   Metrics are being written to separate directories")
elif len(ppo_dirs) > 0 and len(agent_dirs) == 0:
    print("\n✅ FIX WORKED: Only SB3 directories exist")
    print("   All metrics should be in the same location")
elif len(ppo_dirs) == 0 and len(agent_dirs) > 0:
    print("\n⚠️  UNEXPECTED: Only agent-specific directories exist")
    print("   SB3 should have created PPO_* directories")

print("\n" + "=" * 70)