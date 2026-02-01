#!/usr/bin/env python3
"""Compare agent performance vs different bots"""

import re

episode = 0
bot_type = "Unknown"
p0_damage = {"random": 0, "greedy": 0, "defensive": 0}
p1_damage = {"random": 0, "greedy": 0, "defensive": 0}

with open("train_step.log", "r", encoding="utf-8") as f:
    for line in f:
        if "=== EPISODE START ===" in line:
            episode += 1
            if episode <= 48:
                bot_type = "random"
            elif episode <= 96:
                bot_type = "greedy"
            else:
                bot_type = "defensive"

        # Track damage dealt
        if "SHOT at Unit" in line and "Dmg:" in line:
            match = re.search(r'(P[01]).*Dmg:(\d+)HP', line)
            if match:
                player = match.group(1)
                damage = int(match.group(2))
                if player == "P0":
                    p0_damage[bot_type] += damage
                else:
                    p1_damage[bot_type] += damage

print("=" * 60)
print("DAMAGE COMPARISON BY BOT TYPE")
print("=" * 60)
print()
print(f"vs RandomBot (48 games):")
print(f"  Agent (P0):      {p0_damage['random']:3d} damage")
print(f"  RandomBot (P1):  {p1_damage['random']:3d} damage")
print(f"  Advantage:       {p0_damage['random'] - p1_damage['random']:+3d}")
print()
print(f"vs GreedyBot (48 games):")
print(f"  Agent (P0):      {p0_damage['greedy']:3d} damage")
print(f"  GreedyBot (P1):  {p1_damage['greedy']:3d} damage")
print(f"  Advantage:       {p0_damage['greedy'] - p1_damage['greedy']:+3d}")
print()
print(f"vs DefensiveBot (48 games):")
print(f"  Agent (P0):      {p0_damage['defensive']:3d} damage")
print(f"  DefensiveBot (P1): {p1_damage['defensive']:3d} damage")
print(f"  Advantage:       {p0_damage['defensive'] - p1_damage['defensive']:+3d}")
print()
print("=" * 60)
print("INSIGHT")
print("=" * 60)

if p0_damage['random'] - p1_damage['random'] > p0_damage['greedy'] - p1_damage['greedy']:
    print("Agent has LARGER damage advantage vs RandomBot than GreedyBot!")
    print("Yet agent gets 0% wins vs RandomBot and 4% vs GreedyBot.")
    print()
    print("Possible causes:")
    print("1. RandomBot survives better despite taking more damage")
    print("2. Agent units die faster vs RandomBot")
    print("3. Damage is spread across units vs focused (no kills)")
else:
    print("Agent has larger advantage vs GreedyBot - makes sense.")
