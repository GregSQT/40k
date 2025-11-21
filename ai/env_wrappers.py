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

__all__ = ['BotControlledEnv', 'SelfPlayWrapper']


class BotControlledEnv(gym.Wrapper):
    """Wrapper for bot-controlled Player 1 evaluation."""

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

    def reset(self, seed=None, options=None):
        obs, info = self.env.reset(seed=seed, options=options)
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

        return obs, info

    def step(self, agent_action):
        # DIAGNOSTIC: Track AI shoot phase decisions BEFORE executing action
        game_state = self.engine.game_state
        current_phase = game_state.get("phase", "")
        action_mask = self.engine.get_action_mask()

        if current_phase == "shoot" and 4 in [i for i in range(12) if action_mask[i]]:
            self.ai_shoot_opportunities += 1
            if agent_action in [4, 5, 6, 7, 8]:  # Shoot actions (target slots 0-4)
                self.ai_shoot_actions += 1
            elif agent_action == 11:  # Wait action
                self.ai_wait_actions += 1

        # Execute agent action
        obs, reward, terminated, truncated, info = self.env.step(agent_action)
        self.episode_reward += reward
        self.episode_length += 1

        # CRITICAL FIX: Loop through ALL bot turns until control returns to agent
        while not (terminated or truncated) and self.engine.game_state["current_player"] == 1:
            debug_bot = self.episode_length < 10
            bot_action = self._get_bot_action(debug=debug_bot)
            obs, reward, terminated, truncated, info = self.env.step(bot_action)
            self.episode_length += 1

        return obs, reward, terminated, truncated, info

    def _get_bot_action(self, debug=False) -> int:
        game_state = self.engine.game_state
        action_mask = self.engine.get_action_mask()
        valid_actions = [i for i in range(12) if action_mask[i]]

        if not valid_actions:
            return 11

        # DIAGNOSTIC: Track shoot phase opportunities
        current_phase = game_state.get("phase", "")
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
    Wrapper for self-play training where Player 1 is controlled by a frozen copy of the model.

    Key features:
    - Player 0: Learning agent (receives gradient updates from SB3)
    - Player 1: Frozen opponent (uses copy of model from N episodes ago)
    - Frozen model updates periodically to keep opponent challenging
    - Naturally targets ~50% win rate as learning agent improves
    """

    def __init__(self, base_env, frozen_model=None, update_frequency=500):
        """
        Args:
            base_env: W40KEngine wrapped in ActionMasker
            frozen_model: Initial frozen model for Player 1 (optional, will use random if None)
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
        self.player0_wins = 0
        self.player1_wins = 0
        self.draws = 0

    def reset(self, seed=None, options=None):
        """Reset environment for new episode."""
        obs, info = self.env.reset(seed=seed, options=options)
        self.episode_reward = 0.0
        self.episode_length = 0
        return obs, info

    def step(self, agent_action):
        """
        Execute one step in the environment.

        If it's Player 0's turn: Execute the provided action
        If it's Player 1's turn: Use frozen model action instead
        """
        # CRITICAL: First handle any pending Player 1 turns before Player 0's action
        # This shouldn't happen normally, but safety check
        obs = None
        reward = 0.0
        terminated = False
        truncated = False
        info = {}

        # Track P1 actions for diagnostic
        p1_actions_before = 0
        p1_terminal_reward = 0.0  # Capture lose penalty if P1 ends game before P0 acts
        while not (terminated or truncated) and self.engine.game_state["current_player"] == 1:
            player1_action = self._get_frozen_model_action()
            obs, reward, terminated, truncated, info = self.env.step(player1_action)
            self.episode_length += 1
            p1_actions_before += 1

            # If P1's action ended the game before P0 could act, capture the reward
            if terminated or truncated:
                p1_terminal_reward = reward

        # Now execute Player 0's action (if game not over)
        p0_reward = p1_terminal_reward  # Start with any terminal reward from P1's pre-emptive kill
        if not (terminated or truncated):
            obs, reward, terminated, truncated, info = self.env.step(agent_action)
            p0_reward = reward  # CRITICAL: Save P0's reward before P1 overwrites it
            self.episode_reward += reward
            self.episode_length += 1

            # DIAGNOSTIC: Log P0's reward for debugging (disabled for cleaner output)
            # if self.total_episodes < 3 and abs(reward) > 0.1:
            #     phase = self.engine.game_state.get("phase", "?")
            #     print(f"      [P0 Reward] action={agent_action}, reward={reward:.2f}, phase={phase}")

            # Handle any Player 1 turns that follow
            p1_actions_after = 0
            while not (terminated or truncated) and self.engine.game_state["current_player"] == 1:
                player1_action = self._get_frozen_model_action()
                # CRITICAL FIX: Capture reward when P1's action ends game!
                # When P1 kills last P0 unit, reward contains P0's LOSE penalty
                obs, p1_step_reward, terminated, truncated, info = self.env.step(player1_action)
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
            winner = info.get("winner", -1)
            if winner == 0:
                self.player0_wins += 1
            elif winner == 1:
                self.player1_wins += 1
            else:
                self.draws += 1

        return obs, reward, terminated, truncated, info

    def _get_frozen_model_action(self) -> int:
        """
        Get action from frozen model for Player 1.
        Falls back to random valid action if no frozen model available.
        """
        if self.frozen_model is None:
            # No frozen model yet - use random valid action
            action_mask = self.engine.get_action_mask()
            valid_actions = [i for i in range(12) if action_mask[i]]
            if not valid_actions:
                return 11  # Wait action
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
        """Get win rate statistics for Player 0 (learning agent)."""
        total_games = self.player0_wins + self.player1_wins + self.draws
        if total_games == 0:
            return {
                'player0_wins': 0,
                'player1_wins': 0,
                'draws': 0,
                'player0_win_rate': 0.0,
                'total_games': 0
            }

        return {
            'player0_wins': self.player0_wins,
            'player1_wins': self.player1_wins,
            'draws': self.draws,
            'player0_win_rate': self.player0_wins / total_games * 100,
            'total_games': total_games
        }

    def close(self):
        """Close the wrapped environment."""
        self.env.close()
