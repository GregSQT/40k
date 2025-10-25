#!/usr/bin/env python3
"""Diagnostic script to check what metrics are actually being logged"""
import os
import glob
from tensorboard.backend.event_processing import event_accumulator

# Find your latest training run
tensorboard_dir = "./tensorboard/"
subdirs = [d for d in glob.glob(f"{tensorboard_dir}/*") if os.path.isdir(d)]

if not subdirs:
    print("❌ No tensorboard directories found")
    exit(1)

latest_dir = max(subdirs, key=os.path.getmtime)
print(f"📂 Checking: {latest_dir}\n")

# Find event file
event_files = glob.glob(f"{latest_dir}/events.out.tfevents.*")
if not event_files:
    print("❌ No event files found")
    exit(1)

event_file = event_files[0]
print(f"📄 Event file: {os.path.basename(event_file)}\n")

# Load events
ea = event_accumulator.EventAccumulator(event_file)
ea.Reload()

# Get all scalar tags
all_tags = ea.Tags()['scalars']

print("=" * 70)
print("METRICS ACTUALLY BEING LOGGED")
print("=" * 70)

# Organize by namespace
namespaces = {}
for tag in sorted(all_tags):
    namespace = tag.split('/')[0] if '/' in tag else 'root'
    if namespace not in namespaces:
        namespaces[namespace] = []
    namespaces[namespace].append(tag)

for namespace, tags in sorted(namespaces.items()):
    print(f"\n📊 {namespace}/ ({len(tags)} metrics)")
    print("-" * 70)
    for tag in tags:
        values = ea.Scalars(tag)
        print(f"   ✅ {tag} ({len(values)} data points)")

print("\n" + "=" * 70)
print("MISSING CRITICAL METRICS")
print("=" * 70)

expected_critical = [
    'game_critical/win_rate_100ep',
    'game_critical/episode_reward',
    'game_critical/episode_length',
    'game_critical/units_killed_vs_lost_ratio',
    'game_critical/invalid_action_rate',
    'train/policy_gradient_loss',
    'train/value_loss',
    'train/explained_variance',
    'train/clip_fraction',
    'train/approx_kl',
]

missing = [metric for metric in expected_critical if metric not in all_tags]

if missing:
    print("\n❌ MISSING:")
    for metric in missing:
        print(f"   • {metric}")
else:
    print("\n✅ All critical metrics present!")