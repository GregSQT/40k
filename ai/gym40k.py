# ai/gym40k.py

import gymnasium as gym
import numpy as np
from gymnasium import spaces
import json
import os
import copy

REWARDS_PATH = os.path.join(os.path.dirname(__file__), "rewards_master.json")
SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "scenario.json") 

with open(REWARDS_PATH, "r") as f:
    REWARDS_MASTER = json.load(f)

def scripted_unit_action(unit, enemy_units):
    # Example: if ranged and in range, attack lowest-HP enemy in range. Otherwise, wait.
    in_range = [
        e for e in enemy_units
        if e["alive"] and max(abs(unit["col"] - e["col"]), abs(unit["row"] - e["row"])) <= unit.get("rng_rng", 0)
    ]
    if unit.get("is_ranged", False) and in_range:
        # Attack lowest-HP enemy
        return in_range[0]  # Simplest: pick the first one (could be sorted by HP)
    return None

class W40KEnv(gym.Env):
    def __init__(self, n_units=4, board_size=(24, 18), scripted_opponent=False):
        super().__init__()
        self.board_size = board_size
        self.scripted_opponent = scripted_opponent

        # --- Load scenario from JSON ONCE at init ---
        with open(SCENARIO_PATH, "r") as f:
            self.base_scenario = json.load(f)
        self.n_units = len(self.base_scenario)
        self.observation_space = spaces.Box(low=0, high=100, shape=(self.n_units * 7,), dtype=np.float32)
        self.action_space = spaces.Discrete(8)
        self.reset()  # will copy the scenario

        self.episode_logs = []    # Will store (event_log, total_reward) for each episode
        self.episode_rewards = []

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        # --- Deep copy units from base_scenario every time ---
        self.units = copy.deepcopy(self.base_scenario)
        self.state = []
        for u in self.units:
            self.state.extend([
                u["player"], u["col"], u["row"], u["cur_hp"], u["rng_rng"], u["rng_dmg"], u["cc_dmg"]
            ])
        self.state = np.array(self.state, dtype=np.float32)
        self.turn = 0
        self.game_over = False
        self.event_log = []
        self.winner = None
        self.episode_reward = 0
        return self.state.copy(), {}

    # ---------- Action Masking Helper ----------
    def eligible_units(self, player_idx, kind=None):
        return [
            u for u in self.units
            if u["alive"] and not u["has_acted_this_phase"] and u["player"] == player_idx
            and (kind is None or u.get(kind, False))
        ]

    # ---------- Custom Event Functions ----------
    def is_focus_fire(self, target, enemy_units):
        living_enemies = [e for e in enemy_units if e["alive"]]
        if not living_enemies:
            return False  # No focus fire if there are no living enemies
        min_hp = min(e["cur_hp"] for e in living_enemies)
        return target["cur_hp"] == min_hp


    def is_wasted_attack(self, target):
        return target is None

    def overkill(self, target, dmg, old_hp):
        # No overkill if HP == damage at time of attack
        return target and old_hp == dmg

    # ---------- Target Selection Functions ----------
    def best_stat(self, enemy, stats=["rng_dmg", "cc_dmg"]):
        return max(enemy.get(stat, 0) for stat in stats)

    def units_in_range(self, acting_unit, enemy_units, range_key):
        return [
            e for e in enemy_units if max(abs(acting_unit["col"] - e["col"]), abs(acting_unit["row"] - e["row"])) <= acting_unit[range_key]
            and e["alive"]
        ]

    def can_be_killed(self, attacker, target, dmg_key):
        return target["cur_hp"] <= attacker[dmg_key]

    def select_ranged_target(self, acting_unit, our_melee, enemy_units):
        candidates = self.units_in_range(acting_unit, enemy_units, "rng_rng")
        candidates = sorted(candidates, key=lambda e: self.best_stat(e), reverse=True)
        for enemy in candidates:
            for m in our_melee:
                if m["alive"]:
                    dist = max(abs(m["col"] - enemy["col"]), abs(m["row"] - enemy["row"]))
                    if dist <= m["move"] and enemy["cur_hp"] > m["cc_dmg"]:
                        return enemy
        for enemy in candidates:
            if self.can_be_killed(acting_unit, enemy, "rng_dmg"):
                return enemy
        killable = [e for e in candidates if self.can_be_killed(acting_unit, e, "rng_dmg")]
        if killable:
            killable = sorted(killable, key=lambda e: (self.best_stat(e), -e["cur_hp"]), reverse=True)
            return killable[0]
        return candidates[0] if candidates else None

    def select_charge_target_melee(self, acting_unit, enemy_units):
        candidates = self.units_in_range(acting_unit, enemy_units, "move")
        candidates = sorted(candidates, key=lambda e: self.best_stat(e), reverse=True)
        for enemy in candidates:
            if self.can_be_killed(acting_unit, enemy, "cc_dmg"):
                return enemy
        filtered = [e for e in candidates if e["cur_hp"] >= acting_unit["cc_dmg"]]
        if filtered:
            filtered = sorted(filtered, key=lambda e: (self.best_stat(e), -e["cur_hp"]), reverse=True)
            return filtered[0]
        if candidates:
            candidates = sorted(candidates, key=lambda e: (self.best_stat(e), -e["cur_hp"]), reverse=True)
            return candidates[0]
        return None

    def select_charge_target_ranged(self, acting_unit, enemy_units):
        candidates = self.units_in_range(acting_unit, enemy_units, "move")
        candidates = sorted(candidates, key=lambda e: (self.best_stat(e), e["cur_hp"]), reverse=True)
        for enemy in candidates:
            if self.can_be_killed(acting_unit, enemy, "cc_dmg"):
                return enemy
        return candidates[0] if candidates else None

    def select_melee_attack_target(self, acting_unit, enemy_units):
        candidates = self.units_in_range(acting_unit, enemy_units, "move")
        candidates = sorted(candidates, key=lambda e: self.best_stat(e), reverse=True)
        for enemy in candidates:
            if self.can_be_killed(acting_unit, enemy, "cc_dmg"):
                return enemy
        if candidates:
            candidates = sorted(candidates, key=lambda e: (self.best_stat(e), -e["cur_hp"]), reverse=True)
            return candidates[0]
        return None

    # ---------- Phase Logic (with event logging & per-unit stats) ----------
    def reset_phase_flags(self):
        for unit in self.units:
            unit["has_acted_this_phase"] = False
        self.move_close = False
        self.move_away = False
        self.move_to_safe = False
        self.move_to_rng = False
        self.move_to_charge = False
        self.move_to_rng_charge = False
        self.ranged_attack = False
        self.enemy_killed_r = False
        self.enemy_killed_lowests_hp_r = False
        self.enemy_killed_no_overkill_r = False
        self.charge_success = False
        self.being_charged = False
        self.attack = False
        self.enemy_killed_m = False
        self.enemy_killed_lowests_hp_m = False
        self.enemy_killed_no_overkill_m = False
        self.loose_hp = False
        self.killed_in_melee = False
        self.atk_wasted_r = False
        self.atk_wasted_m = False
        self.wait = False

    def ranged_phase(self, player_idx):
        self.reset_phase_flags()
        our_melee = [u for u in self.units if u["is_melee"] and u["player"] == player_idx]
        enemy_units = [e for e in self.units if e["player"] != player_idx and e["alive"]]
        for unit in self.eligible_units(player_idx, "is_ranged"):
            if self.scripted_opponent and player_idx == 0:
                # Scripted logic for bot units
                target = scripted_unit_action(unit, enemy_units)
                if target:
                    dmg = unit["rng_dmg"]
                    old_hp = target["cur_hp"]
                    target["cur_hp"] -= dmg
                    unit["shots_fired"] += 1
                    unit["attacks_made"] += 1
                    unit["damage_dealt"] += min(dmg, max(0, old_hp))
                    if target["cur_hp"] <= 0:
                        target["cur_hp"] = 0
                        target["alive"] = False
                        unit["kills"] += 1
                unit["has_acted_this_phase"] = True
                continue
            # --- RL-controlled player (AI) ---
            target = self.select_ranged_target(unit, our_melee, enemy_units)
            event_flags = {}
            old_hp = target["cur_hp"] if target else None
            # --------- Set flags ----------
            if target:
                dmg = unit["rng_dmg"]
                target["cur_hp"] -= dmg
                self.ranged_attack = True
                unit["shots_fired"] += 1
                unit["attacks_made"] += 1
                unit["damage_dealt"] += min(dmg, old_hp)
                if target["cur_hp"] <= 0:
                    target["cur_hp"] = 0
                    target["alive"] = False
                    unit["kills"] += 1
                    self.enemy_killed_r = True
                    if self.overkill(target, dmg, old_hp):
                        self.enemy_killed_no_overkill_r = True
                    if self.is_focus_fire(target, enemy_units):
                        self.enemy_killed_lowests_hp_r = True
            else:
                self.atk_wasted_r = True
            # Record flags for this action
            event_flags.update({
                "ranged_attack": self.ranged_attack,
                "enemy_killed_r": self.enemy_killed_r,
                "enemy_killed_no_overkill_r": self.enemy_killed_no_overkill_r,
                "enemy_killed_lowests_hp_r": self.enemy_killed_lowests_hp_r,
                "atk_wasted_r": self.atk_wasted_r,
            })
            # Log event history
            self.event_log.append({
                "turn": self.turn,
                "phase": "ranged",
                "acting_unit_idx": self.units.index(unit),
                "target_unit_idx": self.units.index(target) if target else None,
                "event_flags": event_flags,
                "unit_stats": {
                    "damage_dealt": unit["damage_dealt"],
                    "attacks_made": unit["attacks_made"],
                    "shots_fired": unit["shots_fired"],
                    "kills": unit["kills"]
                },
                "units": [u.copy() for u in self.units]
            })
            unit["has_acted_this_phase"] = True


    def charge_phase(self, player_idx):
        self.reset_phase_flags()
        enemy_units = [e for e in self.units if e["player"] != player_idx and e["alive"]]
        for unit in self.eligible_units(player_idx):
            if self.scripted_opponent and player_idx == 0:
                # (Example: melee units always charge closest, ranged units wait)
                if unit["is_melee"]:
                    target = self.select_charge_target_melee(unit, enemy_units)
                else:
                    target = None
                if target:
                    # Implement any effect or just log; simple script here does nothing special
                    pass
                unit["has_acted_this_phase"] = True
                continue
            # --- RL-controlled player (AI) ---
            if unit["is_melee"]:
                target = self.select_charge_target_melee(unit, enemy_units)
            else:
                target = self.select_charge_target_ranged(unit, enemy_units)
            event_flags = {}
            if target:
                self.charge_success = True
            else:
                self.wait = True
            event_flags.update({
                "charge_success": self.charge_success,
                "wait": self.wait
            })
            self.event_log.append({
                "turn": self.turn,
                "phase": "charge",
                "acting_unit_idx": self.units.index(unit),
                "target_unit_idx": self.units.index(target) if target else None,
                "event_flags": event_flags,
                "unit_stats": {
                    "damage_dealt": unit["damage_dealt"],
                    "attacks_made": unit["attacks_made"],
                    "shots_fired": unit["shots_fired"],
                    "kills": unit["kills"]
                },
                "units": [u.copy() for u in self.units]
            })
            unit["has_acted_this_phase"] = True

    def melee_phase(self, player_idx):
        self.reset_phase_flags()
        enemy_units = [e for e in self.units if e["player"] != player_idx and e["alive"]]
        for unit in self.eligible_units(player_idx):
            if self.scripted_opponent and player_idx == 0:
                # Always attack lowest-HP adjacent enemy if any
                adjacent = [
                    e for e in enemy_units
                    if max(abs(unit["col"] - e["col"]), abs(unit["row"] - e["row"])) <= 1 and e["alive"]
                ]
                if adjacent:
                    target = min(adjacent, key=lambda e: e["cur_hp"])
                    dmg = unit["cc_dmg"]
                    old_hp = target["cur_hp"]
                    target["cur_hp"] -= dmg
                    unit["attacks_made"] += 1
                    unit["damage_dealt"] += min(dmg, max(0, old_hp))
                    if target["cur_hp"] <= 0:
                        target["cur_hp"] = 0
                        target["alive"] = False
                        unit["kills"] += 1
                unit["has_acted_this_phase"] = True
                continue
            # --- RL-controlled player (AI) ---
            target = self.select_melee_attack_target(unit, enemy_units)
            event_flags = {}
            old_hp = target["cur_hp"] if target else None
            if target:
                dmg = unit["cc_dmg"]
                target["cur_hp"] -= dmg
                self.attack = True
                unit["attacks_made"] += 1
                unit["damage_dealt"] += min(dmg, old_hp)
                if target["cur_hp"] <= 0:
                    target["cur_hp"] = 0
                    target["alive"] = False
                    unit["kills"] += 1
                    self.enemy_killed_m = True
                    if self.overkill(target, dmg, old_hp):
                        self.enemy_killed_no_overkill_m = True
                    if self.is_focus_fire(target, enemy_units):
                        self.enemy_killed_lowests_hp_m = True
            else:
                self.atk_wasted_m = True
            event_flags.update({
                "attack": self.attack,
                "enemy_killed_m": self.enemy_killed_m,
                "enemy_killed_no_overkill_m": self.enemy_killed_no_overkill_m,
                "enemy_killed_lowests_hp_m": self.enemy_killed_lowests_hp_m,
                "atk_wasted_m": self.atk_wasted_m
            })
            self.event_log.append({
                "turn": self.turn,
                "phase": "melee",
                "acting_unit_idx": self.units.index(unit),
                "target_unit_idx": self.units.index(target) if target else None,
                "event_flags": event_flags,
                "unit_stats": {
                    "damage_dealt": unit["damage_dealt"],
                    "attacks_made": unit["attacks_made"],
                    "shots_fired": unit["shots_fired"],
                    "kills": unit["kills"]
                },
                "units": [u.copy() for u in self.units]
            })
            unit["has_acted_this_phase"] = True

    def check_win_condition(self):
        ai_alive = any(u["alive"] and u["player"] == 1 for u in self.units)
        human_alive = any(u["alive"] and u["player"] == 0 for u in self.units)
        if not ai_alive:
            self.game_over = True
            self.winner = 0
        elif not human_alive:
            self.game_over = True
            self.winner = 1

    def did_win(self):
        return getattr(self, "winner", None) == 1

    def _get_obs(self):
        obs = []
        for u in self.units:
            obs.extend([
                u["player"], u["col"], u["row"], u["cur_hp"], u["rng_rng"], u["rng_dmg"], u["cc_dmg"]
            ])
        return np.array(obs, dtype=np.float32)

    def step(self, action):
        self.ranged_phase(player_idx=1)
        self.charge_phase(player_idx=1)
        self.melee_phase(player_idx=1)
        self.check_win_condition()
        acting_unit = next(
            (u for u in self.units if u["alive"] and u["player"] == 1), self.units[0]
        )
        acting_unit_type = acting_unit["unit_type"]
        rewards = REWARDS_MASTER.get(acting_unit_type, {})
        reward = 0
        # Reward logic with more explicit flags as needed, example:
        if self.game_over:
            if self.did_win():
                reward = rewards.get("win", 0)
            else:
                reward = rewards.get("lose", 0)
        elif acting_unit["is_ranged"] and self.enemy_killed_no_overkill_r:
            reward = rewards.get("enemy_killed_no_overkill_r", 0)
        elif acting_unit["is_ranged"] and self.enemy_killed_lowests_hp_r:
            reward = rewards.get("enemy_killed_lowests_hp_r", 0)
        elif acting_unit["is_ranged"] and self.enemy_killed_r:
            reward = rewards.get("enemy_killed_r", 0)
        elif acting_unit["is_ranged"] and self.ranged_attack:
            reward = rewards.get("ranged_attack", 0)
        elif acting_unit["is_ranged"] and self.atk_wasted_r:
            reward = rewards.get("atk_wasted_r", 0)
        elif acting_unit["is_melee"] and self.enemy_killed_no_overkill_m:
            reward = rewards.get("enemy_killed_no_overkill_m", 0)
        elif acting_unit["is_melee"] and self.enemy_killed_lowests_hp_m:
            reward = rewards.get("enemy_killed_lowests_hp_m", 0)
        elif acting_unit["is_melee"] and self.enemy_killed_m:
            reward = rewards.get("enemy_killed_m", 0)
        elif acting_unit["is_melee"] and self.attack:
            reward = rewards.get("attack", 0)
        elif acting_unit["is_melee"] and self.atk_wasted_m:
            reward = rewards.get("atk_wasted_m", 0)
        self.episode_reward += reward
        terminated = self.game_over
        truncated = self.turn > 50
        info = {}
        obs = self._get_obs()
        if self.game_over or self.turn > 50:
            # At the end of the episode, save the event_log and reward
            self.episode_logs.append((list(self.event_log), self.episode_reward))
        self.turn += 1
        return obs, reward, terminated, truncated, info

