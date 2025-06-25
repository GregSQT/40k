# ai/agent.py

import numpy as np
from stable_baselines3 import DQN

class RLAgent:
    def __init__(self, model_path="ai/model.zip"):
        self.model = DQN.load(model_path)

    def state_to_obs(self, state_dict):
        """
        Convert your game state dict (from frontend) to a flat obs vector
        Modify as needed for your game.
        """
        units = state_dict["units"]
        # Example: Flatten a list of unit attributes (pad to N units)
        obs = []
        for u in units:
            obs.extend([
                u.get("player", 0), 
                u.get("col", 0), 
                u.get("row", 0), 
                u.get("CUR_HP", 0),
                u.get("MOVE", 0),
                u.get("RNG_RNG", 0), 
                u.get("RNG_DMG", 0), 
                u.get("CC_DMG", 0)
            ])
        while len(obs) < 7 * 10:  # pad for 10 units
            obs.append(0)
        return np.array(obs, dtype=np.float32)

    def moveToRngRng(self, unit, state):
        """
        Move to a position where at least one enemy is as close as possible to the unit's RNG_RNG distance.
        Returns new (col, row) for the unit.
        """
        import itertools

        def chebyshev_dist(a, b):
            return max(abs(a[0] - b[0]), abs(a[1] - b[1]))

        # Find all legal positions (including not moving)
        positions = []
        move_range = unit.get("MOVE", 1)
        start = (unit["col"], unit["row"])
        for dx in range(-move_range, move_range + 1):
            for dy in range(-move_range, move_range + 1):
                if abs(dx) + abs(dy) > move_range:
                    continue
                new_col = unit["col"] + dx
                new_row = unit["row"] + dy
                # skip if would land on another unit (except self)
                occupied = any(
                    (u["col"] == new_col and u["row"] == new_row and u["id"] != unit["id"])
                    for u in state["units"]
                )
                if not occupied:
                    positions.append((new_col, new_row))

        enemy_positions = [
            (u["col"], u["row"])
            for u in state["units"]
            if u["player"] != unit["player"]
        ]
        rng_rng = unit.get("RNG_RNG", 1)
        best_pos = (unit["col"], unit["row"])
        best_error = float('inf')

        for pos in positions:
            dists = [chebyshev_dist(pos, ep) for ep in enemy_positions]
            if not dists:
                continue
            min_error = min([abs(d - rng_rng) for d in dists])
            # At least one enemy must be within movement range after move (optional: can require <= MOVE)
            if min_error < best_error:
                best_error = min_error
                best_pos = pos

        return best_pos

    def moveCloseToLowestHpAvoidingCharge(self, unit, state):
        """
        Move as close as possible to the enemy with the lowest HP,
        but don't end the move within any enemy's charge range.
        Returns new (col, row) for the unit.
        """
        def chebyshev_dist(a, b):
            return max(abs(a[0] - b[0]), abs(a[1] - b[1]))

        # Find all legal positions (including not moving)
        positions = []
        move_range = unit.get("MOVE", 1)
        start = (unit["col"], unit["row"])
        for dx in range(-move_range, move_range + 1):
            for dy in range(-move_range, move_range + 1):
                if abs(dx) + abs(dy) > move_range:
                    continue
                new_col = unit["col"] + dx
                new_row = unit["row"] + dy
                # skip if would land on another unit (except self)
                occupied = any(
                    (u["col"] == new_col and u["row"] == new_row and u["id"] != unit["id"])
                    for u in state["units"]
                )
                if not occupied:
                    positions.append((new_col, new_row))

        enemy_units = [u for u in state["units"] if u["player"] != unit["player"]]
        if not enemy_units:
            return (unit["col"], unit["row"])
        # Find enemy with the lowest HP
        target_enemy = min(enemy_units, key=lambda u: u.get("CUR_HP", 9999))
        target_pos = (target_enemy["col"], target_enemy["row"])

        # For each possible move, score by distance to lowest HP enemy
        best_pos = (unit["col"], unit["row"])
        best_dist = float('inf')
        for pos in positions:
            dist = chebyshev_dist(pos, target_pos)
            # Check: Is this cell out of ALL enemy charge ranges?
            safe = True
            for e in enemy_units:
                charge_range = e.get("MOVE", 1)  # Assuming MOVE=charge range for all
                if chebyshev_dist(pos, (e["col"], e["row"])) <= charge_range:
                    safe = False
                    break
            if safe and dist < best_dist:
                best_dist = dist
                best_pos = pos

        return best_pos


    def predict(self, state_dict):
        obs = self.state_to_obs(state_dict)
        action = None

        # Example: If action==43, use moveToRngRng (single unified action for closer or farther)
        action_idx, _ = self.model.predict(obs, deterministic=True)
        if action_idx == 43:
            units = state_dict["units"]
            my_units = [u for u in units if u.get("player", 0) == 1]
            if my_units:
                unit = my_units[0]
                new_col, new_row = self.moveToRngRng(unit, state_dict)
                return {
                    "action": "move_to_rng_rng",
                    "unitId": unit["id"],
                    "destCol": new_col,
                    "destRow": new_row
                }
        # Otherwise, return standard discrete action
        return action_idx

