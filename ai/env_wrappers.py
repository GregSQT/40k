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
from shared.data_validation import require_key, require_present

__all__ = ['BotControlledEnv', 'SelfPlayWrapper']


class BotControlledEnv(gym.Wrapper):
    """Wrapper for bot-controlled Player 2 evaluation."""

    def __init__(self, base_env, bot, unit_registry):
        super().__init__(base_env)
        self.bot = bot
        self.unit_registry = unit_registry
        self.episode_reward = 0.0
        self.episode_length = 0

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

    def reset(self, seed=None, options=None):
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

        # DIAGNOSTIC: Reset shoot tracking for new episode
        self.shoot_opportunities = 0
        self.shoot_actions = 0
        self.wait_actions = 0

        # DIAGNOSTIC: Reset AI shoot tracking
        self.ai_shoot_opportunities = 0
        self.ai_shoot_actions = 0
        self.ai_wait_actions = 0
        self._last_step_return_time = None
        return obs, info

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
        # DIAGNOSTIC: Track AI shoot phase decisions BEFORE executing action
        # PERFORMANCE: Only track if diagnostics are enabled (shoot stats will be collected)
        # Skip get_action_mask() call here to avoid redundant computation - action_masks are already computed
        # by ActionMasker wrapper and passed to model.predict() in bot_evaluation.py
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
        self.episode_reward += reward
        self.episode_length += 1

        # CRITICAL FIX: Loop through ALL bot turns until control returns to agent
        bot_loop_count = 0
        max_bot_iterations = 1000  # Safety guard against infinite loops
        while not (terminated or truncated) and self.engine.game_state["current_player"] == 2:
            bot_loop_count += 1
            if bot_loop_count > max_bot_iterations:
                current_phase = require_key(self.engine.game_state, "phase")
                print(f"\n[DEBUG] BotControlledEnv: Infinite loop detected! Loop count: {bot_loop_count}, episode_length: {self.episode_length}, phase: {current_phase}", flush=True)
                raise RuntimeError(f"BotControlledEnv infinite loop: {bot_loop_count} iterations, phase={current_phase}")
            debug_bot = self.episode_length < 10
            bot_action = self._get_bot_action(debug=debug_bot)
            # LOG TEMPORAIRE: time full env.step(bot_action) (--debug)
            t0_bot = time.perf_counter() if debug_mode else None
            obs, reward, terminated, truncated, info = self.env.step(bot_action)
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

        if debug_mode:
            self._last_step_return_time = time.perf_counter()
        return obs, reward, terminated, truncated, info

    def _get_bot_action(self, debug=False) -> int:
        game_state = self.engine.game_state
        action_mask = self.engine.get_action_mask()
        valid_actions = [i for i in range(12) if action_mask[i]]

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

        if bot_choice not in valid_actions:
            return valid_actions[0]

        # DIAGNOSTIC: Track actual shoot/wait decisions in shoot phase
        if current_phase == "shoot":
            if bot_choice in [4, 5, 6, 7, 8]:  # Shoot actions (target slots 0-4)
                self.shoot_actions += 1
            elif bot_choice == 11:  # Wait action
                self.wait_actions += 1

        return bot_choice

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
            if winner == 1:
                self.player1_wins += 1
            elif winner == 2:
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
            action_mask = self.engine.get_action_mask()
            valid_actions = [i for i in range(12) if action_mask[i]]
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
        obs = self.engine.obs_builder.build_observation(self.engine.game_state)
        action_mask = self.engine.get_action_mask()

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
