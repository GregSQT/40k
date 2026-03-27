#!/usr/bin/env python3
"""
ai/env_wrappers.py - Gym environment wrappers for training

Contains:
- BotControlledEnv: Bot-controlled opponent wrapper for evaluation
- SelfPlayWrapper: Self-play training wrapper with frozen model

Extracted from ai/train.py during refactoring (2025-01-21)
"""

import gymnasium as gym
from typing import Optional, Any
import random
import os
import time
import hashlib
import numpy as np
from shared.data_validation import require_key, require_present
from engine.action_decoder import ActionValidationError

__all__ = ['BotControlledEnv', 'SelfPlayWrapper']
PLAYER_ONE_ID = 1
PLAYER_TWO_ID = 2


class BotControlledEnv(gym.Wrapper):
    """Wrapper for bot-controlled Player 2 evaluation.

    Accepts either:
    - bot: single bot instance (for evaluation, deterministic opponent)
    - bots: list of bot instances (for training, random selection per episode)
    """

    def __init__(
        self,
        base_env,
        bot=None,
        unit_registry=None,
        bots=None,
        agent_seat_mode: str = "p1",
        global_seed: Optional[int] = None,
        env_rank: int = 0,
        episode_start_index: int = 0,
        self_play_opponent_enabled: bool = False,
        self_play_ratio_start: Optional[float] = None,
        self_play_ratio_end: Optional[float] = None,
        self_play_total_episodes: Optional[int] = None,
        self_play_warmup_episodes: Optional[int] = None,
        self_play_snapshot_path: Optional[str] = None,
        self_play_snapshot_refresh_episodes: Optional[int] = None,
        self_play_snapshot_device: Optional[str] = None,
        self_play_deterministic: bool = False,
    ):
        super().__init__(base_env)
        # Support: bots=[...] for random selection, or bot=X for single opponent
        # Also accept legacy positional: BotControlledEnv(env, bot, unit_registry)
        if bots is not None and len(bots) > 0:
            self._bots = list(bots)
            self.bot = self._bots[0]
            self._use_random_bots = True
        elif bot is not None and not isinstance(bot, (list, tuple)):
            self._bots = None
            self.bot = bot
            self._use_random_bots = False
        else:
            raise ValueError("BotControlledEnv requires either 'bot' or 'bots' (non-empty list)")
        self.unit_registry = unit_registry
        self.episode_reward = 0.0
        self.episode_length = 0
        if agent_seat_mode not in {"p1", "p2", "random"}:
            raise ValueError(
                f"agent_seat_mode must be one of 'p1', 'p2', 'random' (got {agent_seat_mode!r})"
            )
        self.agent_seat_mode = agent_seat_mode
        if self.agent_seat_mode == "random":
            if global_seed is None:
                raise ValueError("global_seed is required when agent_seat_mode='random'")
            self._global_seed = int(global_seed)
        else:
            self._global_seed = None
        if episode_start_index < 0:
            raise ValueError(f"episode_start_index must be >= 0 (got {episode_start_index})")
        self._episode_index = int(episode_start_index)
        self._env_rank = int(env_rank)
        self.controlled_player = 1
        self.bot_player = 2
        self.episodes_agent_p1 = 0
        self.episodes_agent_p2 = 0
        self.timesteps_agent_p1 = 0
        self.timesteps_agent_p2 = 0
        self._self_play_opponent_enabled = bool(self_play_opponent_enabled)
        self._episode_uses_self_play_opponent = False
        self._self_play_ratio_current = 0.0
        self._self_play_episodes = 0
        self._bot_episodes = 0
        self._frozen_model = None
        self._frozen_model_mtime: Optional[float] = None
        self._episodes_since_snapshot_refresh = 0
        self._self_play_deterministic = bool(self_play_deterministic)
        if self._self_play_opponent_enabled:
            if self_play_ratio_start is None:
                raise KeyError(
                    "self_play_ratio_start is required when self_play_opponent_enabled=true"
                )
            if self_play_ratio_end is None:
                raise KeyError(
                    "self_play_ratio_end is required when self_play_opponent_enabled=true"
                )
            if self_play_total_episodes is None:
                raise KeyError(
                    "self_play_total_episodes is required when self_play_opponent_enabled=true"
                )
            if self_play_warmup_episodes is None:
                raise KeyError(
                    "self_play_warmup_episodes is required when self_play_opponent_enabled=true"
                )
            if self_play_snapshot_path is None or not str(self_play_snapshot_path).strip():
                raise KeyError(
                    "self_play_snapshot_path is required when self_play_opponent_enabled=true"
                )
            if self_play_snapshot_refresh_episodes is None:
                raise KeyError(
                    "self_play_snapshot_refresh_episodes is required when self_play_opponent_enabled=true"
                )
            if self_play_snapshot_device is None or not str(self_play_snapshot_device).strip():
                raise KeyError(
                    "self_play_snapshot_device is required when self_play_opponent_enabled=true"
                )
            self._self_play_ratio_start = float(self_play_ratio_start)
            self._self_play_ratio_end = float(self_play_ratio_end)
            self._self_play_total_episodes = int(self_play_total_episodes)
            self._self_play_warmup_episodes = int(self_play_warmup_episodes)
            self._self_play_snapshot_path = str(self_play_snapshot_path)
            self._self_play_snapshot_refresh_episodes = int(self_play_snapshot_refresh_episodes)
            self._self_play_snapshot_device = str(self_play_snapshot_device).strip().lower()
            if not (0.0 <= self._self_play_ratio_start <= 1.0):
                raise ValueError(
                    f"self_play_ratio_start must be in [0,1] "
                    f"(got {self._self_play_ratio_start})"
                )
            if not (0.0 <= self._self_play_ratio_end <= 1.0):
                raise ValueError(
                    f"self_play_ratio_end must be in [0,1] "
                    f"(got {self._self_play_ratio_end})"
                )
            if self._self_play_total_episodes <= 0:
                raise ValueError(
                    f"self_play_total_episodes must be > 0 "
                    f"(got {self._self_play_total_episodes})"
                )
            if self._self_play_warmup_episodes < 0:
                raise ValueError(
                    f"self_play_warmup_episodes must be >= 0 "
                    f"(got {self._self_play_warmup_episodes})"
                )
            if self._self_play_warmup_episodes > self._self_play_total_episodes:
                raise ValueError(
                    "self_play_warmup_episodes must be <= self_play_total_episodes "
                    f"(got {self._self_play_warmup_episodes} > "
                    f"{self._self_play_total_episodes})"
                )
            if self._self_play_snapshot_refresh_episodes <= 0:
                raise ValueError(
                    "self_play_snapshot_refresh_episodes must be > 0 "
                    f"(got {self._self_play_snapshot_refresh_episodes})"
                )
            if self._self_play_snapshot_device not in {"cpu", "auto"}:
                raise ValueError(
                    "self_play_snapshot_device must be either 'cpu' or 'auto' "
                    f"(got {self._self_play_snapshot_device!r})"
                )
        else:
            self._self_play_ratio_start = 0.0
            self._self_play_ratio_end = 0.0
            self._self_play_total_episodes = 1
            self._self_play_warmup_episodes = 0
            self._self_play_snapshot_path = ""
            self._self_play_snapshot_refresh_episodes = 1
            self._self_play_snapshot_device = "auto"

        # Unwrap ActionMasker to get actual engine
        # self.env is set by gym.Wrapper.__init__ to base_env
        self.engine = self.env
        if hasattr(self.env, 'env'):
            # ActionMasker wraps the actual engine in .env attribute
            self.engine = self.env.env

        # DIAGNOSTIC: Track shoot phase decisions FOR BOT
        self.shoot_opportunities = 0  # Times shoot was available
        self.shoot_actions = 0        # Times bot actually shot
        self.wait_actions = 0          # Times bot waited in shoot phase

        # DIAGNOSTIC: Track shoot phase decisions FOR AI AGENT
        self.ai_shoot_opportunities = 0
        self.ai_shoot_actions = 0
        self.ai_wait_actions = 0
        # LOG TEMPORAIRE: time between step() return and next step() call (--debug)
        self._last_step_return_time = None

    def _run_bot_until_not_bot_turn(
        self,
        terminated: bool,
        truncated: bool,
        obs: Any,
        info: dict,
        debug_mode: bool,
        accumulate_reward: bool,
        cumulative_reward: float,
    ) -> tuple[Any, bool, bool, dict, float]:
        """Execute consecutive bot turns until control leaves bot player or episode ends."""
        bot_loop_count = 0
        max_bot_iterations = 1000
        while not (terminated or truncated):
            decision_owner, has_valid_actions, _eligible_count = self._get_decision_owner_from_mask()
            if decision_owner != self.bot_player:
                break
            if not has_valid_actions:
                raise RuntimeError(
                    "BotControlledEnv detected bot-owned eligible units with empty action mask. "
                    "Engine must expose at least one legal action for eligible owner."
                )
            bot_loop_count += 1
            if bot_loop_count > max_bot_iterations:
                current_phase = require_key(self.engine.game_state, "phase")
                print(
                    f"\n[DEBUG] BotControlledEnv: Infinite loop detected! "
                    f"Loop count: {bot_loop_count}, episode_length: {self.episode_length}, phase: {current_phase}",
                    flush=True,
                )
                raise RuntimeError(
                    f"BotControlledEnv infinite loop: {bot_loop_count} iterations, phase={current_phase}"
                )
            debug_bot = self.episode_length < 10
            bot_action = self._get_opponent_action(debug=debug_bot)
            t0_bot = time.perf_counter() if debug_mode else None
            obs, reward, terminated, truncated, info = self.env.step(bot_action)
            if accumulate_reward:
                cumulative_reward += float(reward)
                self.episode_reward += float(reward)
            if debug_mode and t0_bot is not None:
                ep = int(require_key(self.engine.game_state, "episode_number"))
                step_idx = int(require_key(self.engine.game_state, "episode_steps"))
                duration_s = time.perf_counter() - t0_bot
                try:
                    debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                    with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                        f.write(f"WRAPPER_STEP_TIMING episode={ep} step_index={step_idx} duration_s={duration_s:.6f}\n")
                except (OSError, IOError):
                    pass
            self.episode_length += 1
        return obs, terminated, truncated, info, cumulative_reward

    def _get_decision_owner_from_mask(self) -> tuple[Optional[int], bool, int]:
        """
        Determine which player currently owns the decision from eligible units/action mask.

        Returns:
            (decision_owner, has_valid_actions, eligible_count)
            - decision_owner: 1|2 when eligible units exist, None when no eligible unit
        """
        action_mask, eligible_units = self.engine.action_decoder.get_action_mask_and_eligible_units(
            self.engine.game_state
        )
        has_valid_actions = bool(np.any(np.asarray(action_mask, dtype=bool)))
        if not eligible_units:
            return None, has_valid_actions, 0

        owners = {int(require_key(unit, "player")) for unit in eligible_units}
        if len(owners) != 1:
            raise RuntimeError(
                f"Eligible unit pool has mixed owners: {owners}. "
                "Pool must contain units from a single acting side."
            )
        return owners.pop(), has_valid_actions, len(eligible_units)

    def _ensure_actionable_controlled_turn(
        self,
        terminated: bool,
        truncated: bool,
        obs: Any,
        info: dict,
        debug_mode: bool,
        accumulate_reward: bool,
        cumulative_reward: float,
    ) -> tuple[Any, bool, bool, dict, float]:
        """
        Advance deterministic no-choice states so controlled player always gets a non-empty mask.
        """
        while not (terminated or truncated):
            decision_owner, has_valid_actions, eligible_count = self._get_decision_owner_from_mask()

            if decision_owner == self.bot_player:
                obs, terminated, truncated, info, cumulative_reward = self._run_bot_until_not_bot_turn(
                    terminated=terminated,
                    truncated=truncated,
                    obs=obs,
                    info=info,
                    debug_mode=debug_mode,
                    accumulate_reward=accumulate_reward,
                    cumulative_reward=cumulative_reward,
                )
                continue

            if decision_owner == self.controlled_player:
                if has_valid_actions:
                    break
                # Controlled owner selected but no valid action: try explicit WAIT to advance.
            elif decision_owner is None:
                # No eligible units: can be phase transition edge or terminal.
                pass
            else:
                current_player = int(require_key(self.engine.game_state, "current_player"))
                raise RuntimeError(
                    f"Unexpected decision owner {decision_owner} in BotControlledEnv "
                    f"(controlled_player={self.controlled_player}, bot_player={self.bot_player}, "
                    f"current_player={current_player})"
                )

            # If controlled player has no eligible units and game is over, terminate cleanly.
            if eligible_count == 0:
                self.engine.game_state["game_over"] = self.engine._check_game_over()
                if self.engine.game_state["game_over"]:
                    terminated = True
                    obs = self.engine._build_observation()
                    winner, win_method = self.engine._determine_winner_with_method()
                    info = {
                        "winner": winner,
                        "win_method": win_method,
                        "phase_auto_advanced": True,
                    }
                    break

            # No actionable decision for controlled player: force WAIT to advance phase/turn.
            t0_wait = time.perf_counter() if debug_mode else None
            try:
                obs, reward, terminated, truncated, info = self.env.step(11)
            except RuntimeError as e:
                err = str(e)
                if "advance_phase failed" in err and "game_over" in err:
                    self.engine.game_state["game_over"] = True
                    terminated = True
                    obs = self.engine._build_observation()
                    winner, win_method = self.engine._determine_winner_with_method()
                    info = {
                        "winner": winner,
                        "win_method": win_method,
                        "phase_auto_advanced": True,
                    }
                    break
                raise
            if accumulate_reward:
                cumulative_reward += float(reward)
                self.episode_reward += float(reward)
            if debug_mode and t0_wait is not None:
                ep = int(require_key(self.engine.game_state, "episode_number"))
                step_idx = int(require_key(self.engine.game_state, "episode_steps"))
                duration_s = time.perf_counter() - t0_wait
                try:
                    debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                    with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                        f.write(f"WRAPPER_STEP_TIMING episode={ep} step_index={step_idx} duration_s={duration_s:.6f}\n")
                except (OSError, IOError):
                    pass
            self.episode_length += 1

        return obs, terminated, truncated, info, cumulative_reward

    def _resolve_controlled_player_for_episode(self) -> int:
        """Resolve controlled player for this episode from seat mode."""
        if self.agent_seat_mode == "p1":
            return 1
        if self.agent_seat_mode == "p2":
            return 2
        # random mode
        seed_material = f"{self._global_seed}:{self._env_rank}:{self._episode_index}"
        seed_hash = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()
        selector = int(seed_hash[:8], 16)
        return 1 if selector % 2 == 0 else 2

    def _apply_episode_seat(self) -> None:
        """Set controlled/opponent players in engine config and game_state."""
        self.controlled_player = self._resolve_controlled_player_for_episode()
        self.bot_player = 2 if self.controlled_player == 1 else 1
        self.engine.config["controlled_player"] = self.controlled_player
        self.engine.config["opponent_player"] = self.bot_player
        self.engine.config["agent_seat_mode"] = self.agent_seat_mode

    def _compute_self_play_ratio_for_episode(self) -> float:
        """Compute scheduled self-play ratio for current episode index."""
        if not self._self_play_opponent_enabled:
            return 0.0
        current_idx = self._episode_index
        if current_idx <= self._self_play_warmup_episodes:
            return self._self_play_ratio_start
        effective_idx = current_idx - self._self_play_warmup_episodes
        effective_total = self._self_play_total_episodes - self._self_play_warmup_episodes
        if effective_total <= 0:
            return self._self_play_ratio_end
        progress = min(1.0, max(0.0, float(effective_idx) / float(effective_total)))
        return self._self_play_ratio_start + (
            (self._self_play_ratio_end - self._self_play_ratio_start) * progress
        )

    def _reload_self_play_snapshot_if_needed(self, force: bool = False) -> None:
        """Load/reload frozen model snapshot used as self-play opponent."""
        if not self._self_play_opponent_enabled:
            return
        snapshot_path = self._self_play_snapshot_path
        if not os.path.exists(snapshot_path):
            raise FileNotFoundError(
                f"Self-play snapshot not found: {snapshot_path}. "
                "Training loop must publish snapshot before self-play episodes."
            )
        current_mtime = float(os.path.getmtime(snapshot_path))
        if (
            not force
            and self._frozen_model is not None
            and self._frozen_model_mtime is not None
            and current_mtime == self._frozen_model_mtime
            and self._episodes_since_snapshot_refresh < self._self_play_snapshot_refresh_episodes
        ):
            return
        from sb3_contrib import MaskablePPO
        self._frozen_model = MaskablePPO.load(
            snapshot_path,
            device=self._self_play_snapshot_device,
        )
        self._frozen_model_mtime = current_mtime
        self._episodes_since_snapshot_refresh = 0

    def _select_opponent_mode_for_episode(self) -> None:
        """Choose bot opponent or frozen self-play opponent for current episode."""
        self._episode_uses_self_play_opponent = False
        self._self_play_ratio_current = 0.0
        if not self._self_play_opponent_enabled:
            self._bot_episodes += 1
            return
        ratio = self._compute_self_play_ratio_for_episode()
        self._self_play_ratio_current = ratio
        seed_material = f"{self._global_seed}:{self._env_rank}:{self._episode_index}:self_play"
        draw_hash = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()
        draw = int(draw_hash[:8], 16) / float(0xFFFFFFFF)
        self._episode_uses_self_play_opponent = bool(draw < ratio)
        if self._episode_uses_self_play_opponent:
            self._reload_self_play_snapshot_if_needed(force=False)
            self._self_play_episodes += 1
        else:
            self._bot_episodes += 1

    def _get_self_play_opponent_action(self) -> int:
        """Get action from frozen self-play opponent model."""
        action_mask, eligible_units = self.engine.action_decoder.get_action_mask_and_eligible_units(
            self.engine.game_state
        )
        if not eligible_units:
            return 11
        valid_actions = [i for i in range(len(action_mask)) if action_mask[i]]
        if not valid_actions:
            raise RuntimeError(
                "BotControlledEnv self-play opponent encountered empty action mask. "
                "Engine must advance phase/turn instead of exposing empty masks."
            )
        if self._frozen_model is None:
            raise RuntimeError(
                "Self-play opponent model is not loaded while episode is in self-play mode."
            )
        obs = self.engine._build_observation()
        action, _ = self._frozen_model.predict(
            obs,
            deterministic=self._self_play_deterministic,
            action_masks=action_mask,
        )
        return int(action)

    def _get_opponent_action(self, debug: bool = False) -> int:
        """Get action from selected opponent mode for current episode."""
        if self._episode_uses_self_play_opponent:
            return self._get_self_play_opponent_action()
        return self._get_bot_action(debug=debug)

    def _play_bot_until_control_returns(self, debug_mode: bool):
        """
        Advance environment until controlled player has an actionable decision state.

        This includes:
        - executing consecutive bot turns,
        - executing forced controlled WAIT when controlled player has no legal action.

        Returns:
            obs, cumulative_reward, terminated, truncated, info
        """
        obs = None
        info = {}
        obs, terminated, truncated, info, cumulative_reward = self._ensure_actionable_controlled_turn(
            terminated=False,
            truncated=False,
            obs=obs,
            info=info,
            debug_mode=debug_mode,
            accumulate_reward=True,
            cumulative_reward=0.0,
        )
        if obs is None:
            # Keep vectorized env stacking stable: always return a real observation.
            obs = self.engine._build_observation()
        return obs, float(cumulative_reward), terminated, truncated, info

    def reset(self, seed=None, options=None):
        debug_mode = require_key(self.engine.game_state, "debug_mode")
        max_reset_attempts = 64
        last_failure: Optional[str] = None

        for attempt_idx in range(max_reset_attempts):
            self._apply_episode_seat()
            t0 = time.perf_counter() if debug_mode else None
            obs, info = self.env.reset(
                seed=seed if attempt_idx == 0 else None,
                options=options,
            )
            self._episode_index += 1
            game_state = self.engine.game_state
            game_state["controlled_player"] = self.controlled_player
            game_state["opponent_player"] = self.bot_player
            if self.controlled_player == 1:
                self.episodes_agent_p1 += 1
            else:
                self.episodes_agent_p2 += 1
            info["controlled_player"] = self.controlled_player
            info["opponent_player"] = self.bot_player
            info["agent_seat_mode"] = self.agent_seat_mode
            if debug_mode and t0 is not None:
                reset_s = time.perf_counter() - t0
                ep = int(require_key(self.engine.game_state, "episode_number"))
                try:
                    debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                    with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                        f.write(f"RESET_TIMING episode={ep} duration_s={reset_s:.6f}\n")
                except (OSError, IOError):
                    pass
            self.episode_reward = 0.0
            self.episode_length = 0

            # Random bot selection: pick a new opponent for this episode
            if self._use_random_bots:
                self.bot = random.choice(self._bots)
            if self._self_play_opponent_enabled:
                self._episodes_since_snapshot_refresh += 1
            self._select_opponent_mode_for_episode()

            # DIAGNOSTIC: Reset shoot tracking for new episode
            self.shoot_opportunities = 0
            self.shoot_actions = 0
            self.wait_actions = 0

            # DIAGNOSTIC: Reset AI shoot tracking
            self.ai_shoot_opportunities = 0
            self.ai_shoot_actions = 0
            self.ai_wait_actions = 0

            # Enforce reset contract for policy learning: return only controlled actionable states.
            bot_obs, _, terminated, truncated, bot_info = self._play_bot_until_control_returns(
                debug_mode=debug_mode
            )
            if bot_obs is not None:
                obs = bot_obs
            if bot_info:
                info.update(bot_info)
            if terminated or truncated:
                winner = self.engine.game_state.get("winner")
                episode_number = self.engine.game_state.get("episode_number")
                last_failure = (
                    "Episode ended before first controlled decision during reset "
                    f"(attempt={attempt_idx + 1}, controlled_player={self.controlled_player}, "
                    f"opponent_player={self.bot_player}, winner={winner}, "
                    f"episode_number={episode_number})"
                )
                continue

            # Defensive validation: wrapper must return on actionable controlled decision owner.
            decision_owner, has_valid_actions, _eligible_count = self._get_decision_owner_from_mask()
            if decision_owner != self.controlled_player or not has_valid_actions:
                current_player = require_key(self.engine.game_state, "current_player")
                raise RuntimeError(
                    "BotControlledEnv reset returned non-actionable controlled state: "
                    f"decision_owner={decision_owner}, has_valid_actions={has_valid_actions}, "
                    f"current_player={current_player}, controlled_player={self.controlled_player}"
                )

            self._last_step_return_time = None
            info["controlled_player"] = self.controlled_player
            info["opponent_player"] = self.bot_player
            info["agent_seat_mode"] = self.agent_seat_mode
            info["opponent_mode"] = (
                "self_play" if self._episode_uses_self_play_opponent else "bot"
            )
            info["self_play_ratio_current"] = self._self_play_ratio_current
            return obs, info

        raise RuntimeError(
            "BotControlledEnv reset exceeded max attempts without reaching a controlled actionable state "
            f"(max_reset_attempts={max_reset_attempts}). "
            f"Last failure: {last_failure}"
        )

    def step(self, agent_action):
        # LOG TEMPORAIRE: time between previous step() return and this step() call (SB3 loop = predict + overhead, --debug)
        debug_mode = require_key(self.engine.game_state, "debug_mode")
        if debug_mode and self._last_step_return_time is not None:
            between_s = time.perf_counter() - self._last_step_return_time
            ep = int(require_key(self.engine.game_state, "episode_number"))
            step_idx = int(require_key(self.engine.game_state, "episode_steps"))
            try:
                debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                    f.write(f"BETWEEN_STEP_TIMING episode={ep} step_index={step_idx} duration_s={between_s:.6f}\n")
            except (OSError, IOError):
                pass
        # Ensure it's really the controlled decision owner's turn before applying agent_action.
        terminated = False
        truncated = False
        obs = None
        reward = 0.0
        cumulative_reward = 0.0
        info = {}
        obs, bot_reward_before, terminated, truncated, info = self._play_bot_until_control_returns(
            debug_mode=debug_mode
        )
        cumulative_reward += float(bot_reward_before)
        if not (terminated or truncated):
            decision_owner, has_valid_actions, _eligible_count = self._get_decision_owner_from_mask()
            if decision_owner != self.controlled_player or not has_valid_actions:
                raise RuntimeError(
                    "BotControlledEnv.step reached non-actionable controlled state before policy action: "
                    f"decision_owner={decision_owner}, has_valid_actions={has_valid_actions}, "
                    f"controlled_player={self.controlled_player}"
                )

        # DIAGNOSTIC: Track AI shoot phase decisions BEFORE executing action
        # PERFORMANCE: Only track if diagnostics are enabled (shoot stats will be collected)
        # Skip get_action_mask() call here to avoid redundant computation - action_masks are already computed
        # by ActionMasker wrapper and passed to model.predict() in bot_evaluation.py
        if not (terminated or truncated):
            game_state = self.engine.game_state
            current_phase = require_key(game_state, "phase")
            # Track actions for diagnostics WITHOUT calling get_action_mask() (performance optimization)
            # We can infer shoot opportunities from action type instead of checking mask
            if current_phase == "shoot":
                # Infer shoot opportunity from action type (action 4-8 are shoot actions)
                # This avoids expensive get_action_mask() call
                if agent_action in [4, 5, 6, 7, 8]:  # Shoot actions (target slots 0-4)
                    self.ai_shoot_opportunities += 1  # If agent shot, opportunity existed
                    self.ai_shoot_actions += 1
                elif agent_action == 11:  # Wait action
                    self.ai_wait_actions += 1

            # Execute agent action
            # LOG TEMPORAIRE: time full env.step() call (--debug) to compare with STEP_TIMING
            t0_agent = time.perf_counter() if debug_mode else None
            obs, reward, terminated, truncated, info = self.env.step(agent_action)
            cumulative_reward += float(reward)
            self.episode_reward += float(reward)
            if debug_mode and t0_agent is not None:
                ep = int(require_key(self.engine.game_state, "episode_number"))
                step_idx = int(require_key(self.engine.game_state, "episode_steps"))
                duration_s = time.perf_counter() - t0_agent
                try:
                    debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                    with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                        f.write(f"WRAPPER_STEP_TIMING episode={ep} step_index={step_idx} duration_s={duration_s:.6f}\n")
                except (OSError, IOError):
                    pass
            self.episode_length += 1

        # Execute bot turns only while episode is still running.
        if not (terminated or truncated):
            obs, bot_reward_after, terminated, truncated, info = self._play_bot_until_control_returns(
                debug_mode=debug_mode
            )
            cumulative_reward += float(bot_reward_after)

        if debug_mode:
            self._last_step_return_time = time.perf_counter()
        if terminated or truncated:
            if self.controlled_player == 1:
                self.timesteps_agent_p1 += self.episode_length
            else:
                self.timesteps_agent_p2 += self.episode_length
        info["controlled_player"] = self.controlled_player
        info["opponent_player"] = self.bot_player
        info["agent_seat_mode"] = self.agent_seat_mode
        info["opponent_mode"] = (
            "self_play" if self._episode_uses_self_play_opponent else "bot"
        )
        info["self_play_ratio_current"] = self._self_play_ratio_current
        return obs, float(cumulative_reward), terminated, truncated, info

    def _get_bot_action(self, debug=False) -> int:
        game_state = self.engine.game_state
        action_mask, eligible_units = self.engine.action_decoder.get_action_mask_and_eligible_units(game_state)
        if not eligible_units:
            # Pool empty -> advance phase via WAIT/invalid action handling
            return 11
        valid_actions = [i for i in range(len(action_mask)) if action_mask[i]]

        if not valid_actions:
            # AI_IMPLEMENTATION.md: No hidden contracts on magic actions.
            # An empty mask here means the engine exposed a phase/turn with no
            # legal actions instead of advancing itself. This must be treated
            # as an explicit engine/flow error, not patched by returning a
            # dummy action.
            raise RuntimeError(
                "BotControlledEnv encountered an empty action mask. "
                "Engine must advance phase/turn instead of exposing "
                "no-op action spaces."
            )

        # DIAGNOSTIC: Track shoot phase opportunities
        current_phase = require_key(game_state, "phase")
        if current_phase == "shoot" and 4 in valid_actions:
            self.shoot_opportunities += 1

        if hasattr(self.bot, 'select_action_with_state'):
            bot_choice = self.bot.select_action_with_state(valid_actions, game_state)
        else:
            bot_choice = self.bot.select_action(valid_actions)

        try:
            bot_action = self.engine.action_decoder.normalize_action_input(
                raw_action=bot_choice,
                phase=current_phase,
                source="bot_controlled_env",
                action_space_size=len(action_mask),
            )
            self.engine.action_decoder.validate_action_against_mask(
                action_int=bot_action,
                action_mask=action_mask,
                phase=current_phase,
                source="bot_controlled_env",
                unit_id=(eligible_units[0]["id"] if eligible_units else None),
            )
        except ActionValidationError as e:
            raise RuntimeError(f"Bot action validation failed: {e}") from e

        # DIAGNOSTIC: Track actual shoot/wait decisions in shoot phase
        if current_phase == "shoot":
            if bot_action in [4, 5, 6, 7, 8]:  # Shoot actions (target slots 0-4)
                self.shoot_actions += 1
            elif bot_action == 11:  # Wait action
                self.wait_actions += 1

        return bot_action

    def get_shoot_stats(self) -> dict:
        """Return shooting statistics for diagnostic analysis."""
        shoot_rate = (self.shoot_actions / self.shoot_opportunities * 100) if self.shoot_opportunities > 0 else 0
        wait_rate = (self.wait_actions / self.shoot_opportunities * 100) if self.shoot_opportunities > 0 else 0

        ai_shoot_rate = (self.ai_shoot_actions / self.ai_shoot_opportunities * 100) if self.ai_shoot_opportunities > 0 else 0
        ai_wait_rate = (self.ai_wait_actions / self.ai_shoot_opportunities * 100) if self.ai_shoot_opportunities > 0 else 0

        return {
            'shoot_opportunities': self.shoot_opportunities,
            'shoot_actions': self.shoot_actions,
            'wait_actions': self.wait_actions,
            'shoot_rate': shoot_rate,
            'wait_rate': wait_rate,
            'ai_shoot_opportunities': self.ai_shoot_opportunities,
            'ai_shoot_actions': self.ai_shoot_actions,
            'ai_wait_actions': self.ai_wait_actions,
            'ai_shoot_rate': ai_shoot_rate,
            'ai_wait_rate': ai_wait_rate
        }

    def get_seat_stats(self) -> dict:
        """Return seat distribution stats for audit."""
        total_episodes = self.episodes_agent_p1 + self.episodes_agent_p2
        total_timesteps = self.timesteps_agent_p1 + self.timesteps_agent_p2
        p1_episode_share = (self.episodes_agent_p1 / total_episodes * 100.0) if total_episodes > 0 else 0.0
        p2_episode_share = (self.episodes_agent_p2 / total_episodes * 100.0) if total_episodes > 0 else 0.0
        p1_timestep_share = (self.timesteps_agent_p1 / total_timesteps * 100.0) if total_timesteps > 0 else 0.0
        p2_timestep_share = (self.timesteps_agent_p2 / total_timesteps * 100.0) if total_timesteps > 0 else 0.0
        return {
            "agent_seat_mode": self.agent_seat_mode,
            "episodes_agent_p1": self.episodes_agent_p1,
            "episodes_agent_p2": self.episodes_agent_p2,
            "episodes_vs_bots": self._bot_episodes,
            "episodes_vs_self_play": self._self_play_episodes,
            "timesteps_agent_p1": self.timesteps_agent_p1,
            "timesteps_agent_p2": self.timesteps_agent_p2,
            "episode_share_agent_p1_pct": p1_episode_share,
            "episode_share_agent_p2_pct": p2_episode_share,
            "timestep_share_agent_p1_pct": p1_timestep_share,
            "timestep_share_agent_p2_pct": p2_timestep_share,
        }


class SelfPlayWrapper(gym.Wrapper):
    """
    Wrapper for self-play training where Player 2 is controlled by a frozen copy of the model.

    Key features:
    - Player 1: Learning agent (receives gradient updates from SB3)
    - Player 2: Frozen opponent (uses copy of model from N episodes ago)
    - Frozen model updates periodically to keep opponent challenging
    - Naturally targets ~50% win rate as learning agent improves
    """

    def __init__(self, base_env, frozen_model=None, update_frequency=500):
        """
        Args:
            base_env: W40KEngine wrapped in ActionMasker
            frozen_model: Initial frozen model for Player 2 (optional, will use random if None)
            update_frequency: Episodes between frozen model updates
        """
        super().__init__(base_env)
        self.frozen_model = frozen_model
        self.update_frequency = update_frequency
        self.episodes_since_update = 0
        self.total_episodes = 0

        # Unwrap to get actual W40KEngine
        # Wrapping order: SelfPlayWrapper(ActionMasker(W40KEngine))
        # self.env is set by gym.Wrapper.__init__ to base_env (ActionMasker)
        self.engine = self.env
        while hasattr(self.engine, 'env'):
            self.engine = self.engine.env

        # Episode tracking
        self.episode_reward = 0.0
        self.episode_length = 0

        # Self-play statistics
        self.player1_wins = 0
        self.player2_wins = 0
        self.draws = 0
        # LOG TEMPORAIRE: time between step() return and next step() call (--debug)
        self._last_step_return_time = None

    def reset(self, seed=None, options=None):
        """Reset environment for new episode."""
        # LOG TEMPORAIRE: time reset() when --debug (to explain slow step index 0)
        debug_mode = require_key(self.engine.game_state, "debug_mode")
        t0 = time.perf_counter() if debug_mode else None
        obs, info = self.env.reset(seed=seed, options=options)
        if debug_mode and t0 is not None:
            reset_s = time.perf_counter() - t0
            ep = int(require_key(self.engine.game_state, "episode_number"))
            try:
                debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                    f.write(f"RESET_TIMING episode={ep} duration_s={reset_s:.6f}\n")
            except (OSError, IOError):
                pass
        self.episode_reward = 0.0
        self.episode_length = 0
        self._last_step_return_time = None
        return obs, info

    def step(self, agent_action):
        """
        Execute one step in the environment.

        If it's Player 1's turn: Execute the provided action
        If it's Player 2's turn: Use frozen model action instead
        """
        # LOG TEMPORAIRE: time between previous step() return and this step() call (SB3 loop = predict + overhead, --debug)
        debug_mode = require_key(self.engine.game_state, "debug_mode")
        if debug_mode and self._last_step_return_time is not None:
            between_s = time.perf_counter() - self._last_step_return_time
            ep = int(require_key(self.engine.game_state, "episode_number"))
            step_idx = int(require_key(self.engine.game_state, "episode_steps"))
            try:
                debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                    f.write(f"BETWEEN_STEP_TIMING episode={ep} step_index={step_idx} duration_s={between_s:.6f}\n")
            except (OSError, IOError):
                pass
        # CRITICAL: First handle any pending Player 2 turns before Player 1's action
        # This shouldn't happen normally, but safety check
        obs = None
        reward = 0.0
        terminated = False
        truncated = False
        info = {}

        # Track P1 actions for diagnostic
        p1_actions_before = 0
        p1_terminal_reward = 0.0  # Capture lose penalty if P1 ends game before P0 acts
        max_iterations = 1000  # Safety guard against infinite loops
        while not (terminated or truncated) and self.engine.game_state["current_player"] == 2:
            p1_actions_before += 1
            if p1_actions_before > max_iterations:
                current_phase = require_key(self.engine.game_state, "phase")
                print(f"\n[DEBUG] SelfPlayEnvWrapper: Infinite loop detected in P1 before loop! Count: {p1_actions_before}, episode_length: {self.episode_length}, phase: {current_phase}", flush=True)
                raise RuntimeError(f"SelfPlayEnvWrapper infinite loop (P1 before): {p1_actions_before} iterations, phase={current_phase}")
            player1_action = self._get_frozen_model_action()
            # LOG TEMPORAIRE: time full env.step() (--debug)
            t0_p1 = time.perf_counter() if debug_mode else None
            obs, reward, terminated, truncated, info = self.env.step(player1_action)
            if debug_mode and t0_p1 is not None:
                ep = int(require_key(self.engine.game_state, "episode_number"))
                step_idx = int(require_key(self.engine.game_state, "episode_steps"))
                duration_s = time.perf_counter() - t0_p1
                try:
                    debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                    with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                        f.write(f"WRAPPER_STEP_TIMING episode={ep} step_index={step_idx} duration_s={duration_s:.6f}\n")
                except (OSError, IOError):
                    pass
            self.episode_length += 1

            # If P1's action ended the game before P0 could act, capture the reward
            if terminated or truncated:
                p1_terminal_reward = reward

        # Now execute Player 0's action (if game not over)
        p0_reward = p1_terminal_reward  # Start with any terminal reward from P1's pre-emptive kill
        if not (terminated or truncated):
            # LOG TEMPORAIRE: time full env.step() (--debug)
            t0_p0 = time.perf_counter() if debug_mode else None
            obs, reward, terminated, truncated, info = self.env.step(agent_action)
            if debug_mode and t0_p0 is not None:
                ep = int(require_key(self.engine.game_state, "episode_number"))
                step_idx = int(require_key(self.engine.game_state, "episode_steps"))
                duration_s = time.perf_counter() - t0_p0
                try:
                    debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                    with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                        f.write(f"WRAPPER_STEP_TIMING episode={ep} step_index={step_idx} duration_s={duration_s:.6f}\n")
                except (OSError, IOError):
                    pass
            p0_reward = reward  # CRITICAL: Save P0's reward before P1 overwrites it
            self.episode_reward += reward
            self.episode_length += 1

            # DIAGNOSTIC: Log P0's reward for debugging (disabled for cleaner output)
            # if self.total_episodes < 3 and abs(reward) > 0.1:
            #     phase = self.engine.game_state.get("phase", "?")
            #     print(f"      [P0 Reward] action={agent_action}, reward={reward:.2f}, phase={phase}")

            # Handle any Player 1 turns that follow
            p1_actions_after = 0
            while not (terminated or truncated) and self.engine.game_state["current_player"] == 2:
                p1_actions_after += 1
                if p1_actions_after > max_iterations:
                    current_phase = require_key(self.engine.game_state, "phase")
                    print(f"\n[DEBUG] SelfPlayEnvWrapper: Infinite loop detected in P1 after loop! Count: {p1_actions_after}, episode_length: {self.episode_length}, phase: {current_phase}", flush=True)
                    raise RuntimeError(f"SelfPlayEnvWrapper infinite loop (P1 after): {p1_actions_after} iterations, phase={current_phase}")
                player1_action = self._get_frozen_model_action()
                # CRITICAL FIX: Capture reward when P1's action ends game!
                # When P1 kills last P0 unit, reward contains P0's LOSE penalty
                # LOG TEMPORAIRE: time full env.step() (--debug)
                t0_p1_after = time.perf_counter() if debug_mode else None
                obs, p1_step_reward, terminated, truncated, info = self.env.step(player1_action)
                if debug_mode and t0_p1_after is not None:
                    ep = int(require_key(self.engine.game_state, "episode_number"))
                    step_idx = int(require_key(self.engine.game_state, "episode_steps"))
                    duration_s = time.perf_counter() - t0_p1_after
                    try:
                        debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                        with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                            f.write(f"WRAPPER_STEP_TIMING episode={ep} step_index={step_idx} duration_s={duration_s:.6f}\n")
                    except (OSError, IOError):
                        pass
                self.episode_length += 1
                p1_actions_after += 1

                # If P1's action ended the game, P0 needs the situational reward (win/lose)
                # The engine returns P0's perspective reward even for P1's actions
                if terminated or truncated:
                    p0_reward += p1_step_reward  # Add win/lose bonus to P0's total

            # DIAGNOSTIC: Log if P1 took actions (disabled for cleaner output)
            # if (p1_actions_before + p1_actions_after) > 0 and self.total_episodes < 3:
            #     phase = self.engine.game_state.get("phase", "?")
            #     print(f"    [SelfPlay] P0 action={agent_action}, P1 took {p1_actions_before}+{p1_actions_after} actions, phase={phase}")

        # CRITICAL: Return P0's reward to SB3, not P1's!
        reward = p0_reward

        # Track episode end statistics
        if terminated or truncated:
            self.total_episodes += 1
            self.episodes_since_update += 1

            # Track wins/losses
            winner = require_present(require_key(info, "winner"), "winner")
            if winner == PLAYER_ONE_ID:
                self.player1_wins += 1
            elif winner == PLAYER_TWO_ID:
                self.player2_wins += 1
            else:
                self.draws += 1

        if debug_mode:
            self._last_step_return_time = time.perf_counter()
        return obs, reward, terminated, truncated, info

    def _get_frozen_model_action(self) -> int:
        """
        Get action from frozen model for Player 2.
        Falls back to random valid action if no frozen model available.
        """
        if self.frozen_model is None:
            # No frozen model yet - use random valid action
            action_mask, eligible_units = self.engine.action_decoder.get_action_mask_and_eligible_units(self.engine.game_state)
            if not eligible_units:
                # Pool empty -> advance phase via WAIT/invalid action handling
                return 11
            valid_actions = [i for i in range(len(action_mask)) if action_mask[i]]
            if not valid_actions:
                # AI_IMPLEMENTATION.md: Empty masks indicate a flow/phase bug;
                # SelfPlayWrapper must not silently inject dummy actions.
                raise RuntimeError(
                    "SelfPlayWrapper encountered an empty action mask for Player 2. "
                    "Engine must advance phase/turn instead of exposing empty masks."
                )
            return random.choice(valid_actions)

        # Use frozen model to predict action WITH action masking
        # CRITICAL: MaskablePPO requires action_masks parameter for proper masked inference
        action_mask, eligible_units = self.engine.action_decoder.get_action_mask_and_eligible_units(self.engine.game_state)
        if not eligible_units:
            # Pool empty -> advance phase via WAIT/invalid action handling
            return 11
        obs = self.engine._build_observation()

        # MaskablePPO.predict() expects action_masks as keyword argument
        # CRITICAL: Use deterministic=False so P1 explores like P0 (fair self-play)
        action, _ = self.frozen_model.predict(obs, deterministic=False, action_masks=action_mask)

        return int(action)

    def update_frozen_model(self, new_model):
        """
        Update the frozen model with a copy of the current learning model.
        Should be called periodically (e.g., every N episodes).

        Note: This method is deprecated. Use the persistent_frozen_model approach
        in the training loop instead, which properly saves/loads via temp file.
        """
        # Set directly - the caller is responsible for providing an independent copy
        self.frozen_model = new_model
        self.episodes_since_update = 0
        print(f"  🔄 Self-play: Updated frozen opponent (Episode {self.total_episodes})")

    def should_update_frozen_model(self) -> bool:
        """Check if it's time to update the frozen model."""
        return self.episodes_since_update >= self.update_frequency

    def get_win_rate_stats(self) -> dict:
        """Get win rate statistics for Player 1 (learning agent)."""
        total_games = self.player1_wins + self.player2_wins + self.draws
        if total_games == 0:
            return {
                'player1_wins': 0,
                'player2_wins': 0,
                'draws': 0,
                'player1_win_rate': 0.0,
                'total_games': 0
            }

        return {
            'player1_wins': self.player1_wins,
            'player2_wins': self.player2_wins,
            'draws': self.draws,
            'player1_win_rate': self.player1_wins / total_games * 100,
            'total_games': total_games
        }

    def close(self):
        """Close the wrapped environment."""
        self.env.close()
