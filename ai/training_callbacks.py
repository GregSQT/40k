#!/usr/bin/env python3
"""
ai/training_callbacks.py - Training callbacks for Stable-Baselines3

Contains:
- LearningRateScheduleCallback: Linearly reduce learning rate during training
- EntropyScheduleCallback: Linearly reduce entropy coefficient during training
- EpisodeTerminationCallback: Terminate training after exact episode count
- MetricsCollectionCallback: Collect training metrics for W40KMetricsTracker
- BotEvaluationCallback: Test agent against evaluation bots with best model saving

Extracted from ai/train.py during refactoring (2025-01-21)
"""

import json
import os
import time
import re
import math
import shutil
import tempfile
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
import numpy as np
import torch
import gymnasium as gym
from typing import Dict, Optional, Any, List, cast
from stable_baselines3.common.callbacks import BaseCallback

from shared.data_validation import require_key, require_present
from ai.vec_normalize_utils import get_vec_normalize_path
from config_loader import get_config_loader

# Les sept classes de bots d'evaluation etaient importees ici sous try/except ImportError, avec
# un drapeau EVALUATION_BOTS_AVAILABLE qui gardait trois blocs. Cette protection n'avait pas de
# raison d'etre : ai/evaluation_bots.py est dans le depot, ce n'est pas une dependance optionnelle,
# et il n'y a pas de cycle d'import a eviter (il ne tire que engine/* et shared/*, et engine
# n'importe ai que paresseusement, jamais ai.training_callbacks ni ai.evaluation_bots). Le drapeau
# valait donc toujours True, et les gardes etaient du code mort deguise en robustesse.
# Aucune des sept classes n'est plus referencee ici : les adversaires d'evaluation sont instancies
# par ai/bot_evaluation.evaluate_against_bots, importe la ou il sert.

# V11 §10.5 : adversaires RESERVES a l'evaluation, jamais rencontres a l'entrainement.
# Ils sont mesures et affiches, mais exclus de TOUT signal de selection de modele
# (combined, worst_bot, gating, score robuste) : un holdout sur lequel la selection
# optimise n'est plus un holdout.
HOLDOUT_BOT_NAMES = frozenset(["tactical"])

# Nom de classe reel de chaque adversaire d'evaluation, pour les tags TensorBoard : une courbe
# `03_eval/<scenario>/defensive` n'identifie pas l'adversaire pour qui lit le dashboard, alors
# que le code n'echange que ces cles courtes. Table EXPLICITE et non derivee de la cle (un
# `''.join(part.capitalize()) + 'Bot'` rendrait le bon nom aujourd'hui et divergerait en silence
# a la premiere classe qui ne suit pas la convention) ; verrouillee contre les classes reelles
# de ai/evaluation_bots par tests/unit/ai/test_eval_bot_display_names.py.
BOT_DISPLAY_NAMES = {
    "random": "RandomBot",
    "greedy": "GreedyBot",
    "defensive": "DefensiveBot",
    "control": "ControlBot",
    "adaptive": "AdaptiveBot",
    "value_trade": "ValueTradeBot",
    "tactical": "TacticalBot",
}

ALL_BOT_NAMES = frozenset([
    "random", "greedy", "defensive", "control", "adaptive", "value_trade",
]) | HOLDOUT_BOT_NAMES

# Bots qui pilotent la selection (gating, worst_bot, score robuste). Le holdout en est exclu.
SELECTION_BOT_NAMES = ALL_BOT_NAMES - HOLDOUT_BOT_NAMES


def selection_worst_bot(scores):
    """Retourne (nom, win-rate) du pire bot de SELECTION.

    Le holdout (`HOLDOUT_BOT_NAMES`) est MESURE mais EXCLU de ce signal (V11 §10.5) : un poids
    nul ne protege pas un ``min`` qui itere sur des NOMS de bots. Source unique pour les deux
    sites de calcul du worst_bot (par-scenario dans bot_evaluation, eval-only dans train.py).

    Raises:
        ValueError: si aucun bot de selection ne subsiste hors holdout (signal impossible).
    """
    selection = {bn: score for bn, score in scores.items() if bn not in HOLDOUT_BOT_NAMES}
    if not selection:
        raise ValueError(
            "Aucun bot de selection hors holdout "
            f"(HOLDOUT_BOT_NAMES={sorted(HOLDOUT_BOT_NAMES)}) parmi {sorted(scores)} : "
            "worst_bot serait pilote par le holdout (V11 §10.5)."
        )
    return min(selection.items(), key=lambda item: item[1])

__all__ = [
    'LearningRateScheduleCallback',
    'EntropyScheduleCallback',
    'EpisodeTerminationCallback',
    'MetricsCollectionCallback',
    'BotEvaluationCallback'
]

def _require_progress_bar_width(config_key: str) -> int:
    """Load and validate progress bar width from config/config.json."""
    config_loader = get_config_loader()
    global_config = config_loader.load_config("config", force_reload=False)
    progress_bar_cfg = require_key(global_config, "progress_bar")
    width = require_key(progress_bar_cfg, config_key)
    if not isinstance(width, int) or isinstance(width, bool):
        raise TypeError(
            f"config.progress_bar.{config_key} must be an integer "
            f"(got {type(width).__name__})"
        )
    if width <= 0:
        raise ValueError(
            f"config.progress_bar.{config_key} must be > 0 (got {width})"
        )
    return width


class LearningRateScheduleCallback(BaseCallback):
    """Callback to linearly reduce learning rate during training (episode-based)."""

    def __init__(
        self,
        start_lr: float,
        end_lr: float,
        total_episodes: int,
        initial_episode_count: int = 0,
        verbose: int = 0
    ):
        super().__init__(verbose)
        self.start_lr = start_lr
        self.end_lr = end_lr
        self.total_episodes = total_episodes
        if initial_episode_count < 0:
            raise ValueError(f"initial_episode_count must be >= 0 (got {initial_episode_count})")
        self.episode_count = initial_episode_count
        self.last_update_step = 0

    @staticmethod
    def _set_model_learning_rate(model, lr_value: float) -> None:
        """Apply learning rate to all SB3 learning-rate access points."""
        model.learning_rate = lr_value
        # PPO uses lr_schedule internally during train(); keep it aligned with episode-based LR.
        model.lr_schedule = lambda _progress_remaining: lr_value
        if hasattr(model, 'policy') and hasattr(model.policy, 'optimizer'):
            for param_group in model.policy.optimizer.param_groups:
                param_group["lr"] = lr_value

    def _on_training_start(self) -> None:
        progress = min(1.0, self.episode_count / self.total_episodes)
        initial_lr = self.start_lr + (self.end_lr - self.start_lr) * progress
        self._set_model_learning_rate(self.model, initial_lr)

    def _on_step(self) -> bool:
        # Detect episode end using dones array (more reliable than info dict)
        if hasattr(self, 'locals') and 'dones' in self.locals:
            dones = self.locals['dones']
            episodes_finished = sum(dones) if hasattr(dones, '__iter__') else (1 if dones else 0)

            if episodes_finished > 0:
                self.episode_count += episodes_finished
                progress = min(1.0, self.episode_count / self.total_episodes)
                new_lr = self.start_lr + (self.end_lr - self.start_lr) * progress
                self._set_model_learning_rate(self.model, new_lr)

                if self.verbose > 0 and self.num_timesteps - self.last_update_step >= 1000:
                    # Keep internal throttling state in sync without printing a separate line.
                    # Progress display is handled by EpisodeTerminationCallback.
                    self.last_update_step = self.num_timesteps
        return True


class EntropyScheduleCallback(BaseCallback):
    """Callback to linearly reduce entropy coefficient during training."""

    def __init__(
        self,
        start_ent: float,
        end_ent: float,
        total_episodes: int,
        initial_episode_count: int = 0,
        verbose: int = 0
    ):
        super().__init__(verbose)
        self.start_ent = start_ent
        self.end_ent = end_ent
        self.total_episodes = total_episodes
        if initial_episode_count < 0:
            raise ValueError(f"initial_episode_count must be >= 0 (got {initial_episode_count})")
        self.episode_count = initial_episode_count
        self.last_update_step = 0

    def _on_training_start(self) -> None:
        progress = min(1.0, self.episode_count / self.total_episodes)
        initial_ent = self.start_ent + (self.end_ent - self.start_ent) * progress
        cast(Any, self.model).ent_coef = initial_ent

    def _on_step(self) -> bool:
        # Detect episode end using dones array (more reliable than info dict)
        if hasattr(self, 'locals') and 'dones' in self.locals:
            dones = self.locals['dones']
            # Count number of episodes that finished in this step
            episodes_finished = sum(dones) if hasattr(dones, '__iter__') else (1 if dones else 0)

            if episodes_finished > 0:
                self.episode_count += episodes_finished
                # Linear interpolation: ent = start + (end - start) * progress
                progress = min(1.0, self.episode_count / self.total_episodes)
                new_ent = self.start_ent + (self.end_ent - self.start_ent) * progress
                cast(Any, self.model).ent_coef = new_ent

                if self.verbose > 0 and self.num_timesteps - self.last_update_step >= 1000:
                    # Keep internal throttling state in sync without printing a separate line.
                    # Progress display is handled by EpisodeTerminationCallback.
                    self.last_update_step = self.num_timesteps
        return True

class EpisodeTerminationCallback(BaseCallback):
    """Callback to terminate training after exact episode count."""

    def __init__(self, max_episodes: int, expected_timesteps: int, verbose: int = 0,
                 total_episodes: Optional[int] = None, scenario_info: Optional[str] = None,
                 disable_early_stopping: bool = False, global_start_time: Optional[float] = None,
                 phase_label: Optional[str] = None,
                 phase_episode_offset: int = 0,
                 gate_display_state: Optional[Dict[str, Any]] = None,
                 training_config: Optional[Dict[str, Any]] = None):
        super().__init__(verbose)
        if max_episodes <= 0:
            raise ValueError("max_episodes must be positive - no defaults allowed")
        if expected_timesteps <= 0:
            raise ValueError("expected_timesteps must be positive - no defaults allowed")
        self.max_episodes = max_episodes
        self.expected_timesteps = expected_timesteps
        self.episode_count = 0
        self.step_count = 0
        self.start_time = global_start_time  # Use provided global start time if available
        # For global progress tracking in rotation mode
        self.total_episodes = total_episodes if total_episodes else max_episodes
        self.scenario_info = scenario_info  # e.g., "Cycle 8 | Scenario: phase2-1"
        self.global_episode_offset = 0  # Set by rotation code to track overall progress
        self.phase_label = phase_label
        if phase_episode_offset < 0:
            raise ValueError(
                f"phase_episode_offset must be >= 0 (got {phase_episode_offset})"
            )
        self.phase_episode_offset = int(phase_episode_offset)
        # ROTATION FIX: Disable early stopping to let model.learn() consume all timesteps
        self.disable_early_stopping = disable_early_stopping
        # EMA for smooth ETA estimation (weights recent episodes more heavily)
        self.ema_episode_time = None
        self.last_display_time = None
        self.last_display_episode_count = None
        self.ema_alpha = 0.1  # Smoothing factor (higher = more weight on recent)
        self._last_progress_line_len = 0
        self.max_episode_duration_seconds = 0.0
        # +inf et non 0.0 : un minimum initialise a zero resterait a zero pour toujours et
        # afficherait un ecart min/max flatteur sans qu'aucun episode ne l'ait justifie. La
        # valeur n'est lue que sous `if episode_ended`, donc apres au moins un `min()`.
        self.min_episode_duration_seconds = float("inf")
        self.last_episode_duration_seconds = 0.0
        self._episode_wall_time_by_env: Optional[List[float]] = None
        self._episode_eval_time_by_env: Optional[List[float]] = None
        self._last_step_perf_time: Optional[float] = None
        self.gate_display_state = gate_display_state
        self.total_eval_time_at_last_display = 0.0
        self.training_progress_bar_length = _require_progress_bar_width("training_width")
        self.training_config = training_config

    def _on_training_start(self) -> None:
        """Initialize timing on training start."""
        import time
        # Only set start_time if not already set (preserves global start time in rotation mode)
        if self.start_time is None:
            self.start_time = time.time()

    def _compute_training_roster_count(self, display_episode_count: int) -> Optional[int]:
        """Compute active training roster count (per side) for progress display."""
        if self.training_config is None:
            return None
        if not isinstance(self.training_config, dict):
            raise TypeError(
                f"EpisodeTerminationCallback.training_config must be dict (got {type(self.training_config).__name__})"
            )
        schedule_raw = self.training_config.get("roster_pool_schedule")
        if schedule_raw is None:
            return None
        if not isinstance(schedule_raw, dict):
            raise TypeError(
                f"training_config.roster_pool_schedule must be dict (got {type(schedule_raw).__name__})"
            )
        enabled = schedule_raw.get("enabled")
        if not isinstance(enabled, bool):
            raise TypeError("training_config.roster_pool_schedule.enabled must be bool")
        if not enabled:
            return None

        training_schedule = schedule_raw.get("training")
        if not isinstance(training_schedule, dict):
            raise TypeError("training_config.roster_pool_schedule.training must be dict")
        start_counts_raw = training_schedule.get("start_counts")
        end_counts_raw = training_schedule.get("end_counts")
        if not isinstance(start_counts_raw, dict) or not isinstance(end_counts_raw, dict):
            raise TypeError(
                "training_config.roster_pool_schedule.training.start_counts and end_counts must be dict"
            )

        classes = ("swarm", "troop", "elite")
        start_counts: Dict[str, int] = {}
        end_counts: Dict[str, int] = {}
        for cls in classes:
            start_value = start_counts_raw.get(cls)
            end_value = end_counts_raw.get(cls)
            if not isinstance(start_value, int) or isinstance(start_value, bool):
                raise TypeError(f"start_counts.{cls} must be integer")
            if not isinstance(end_value, int) or isinstance(end_value, bool):
                raise TypeError(f"end_counts.{cls} must be integer")
            if start_value <= 0 or end_value <= 0:
                raise ValueError(f"start_counts/end_counts.{cls} must be > 0")
            if end_value < start_value:
                raise ValueError(
                    f"end_counts.{cls} must be >= start_counts.{cls} ({end_value} < {start_value})"
                )
            start_counts[cls] = int(start_value)
            end_counts[cls] = int(end_value)

        total_episodes = self.training_config.get("total_episodes")
        n_envs = self.training_config.get("n_envs")
        if not isinstance(total_episodes, int) or isinstance(total_episodes, bool):
            raise TypeError("training_config.total_episodes must be integer when roster schedule is enabled")
        if not isinstance(n_envs, int) or isinstance(n_envs, bool):
            raise TypeError("training_config.n_envs must be integer when roster schedule is enabled")
        if total_episodes <= 0 or n_envs <= 0:
            raise ValueError("training_config.total_episodes and n_envs must be > 0 when roster schedule is enabled")

        # Schedule runs per environment episode index, aligned with engine/game_state.py.
        per_env_episode_index = max(0, int(math.ceil(float(display_episode_count) / float(n_envs))) - 1)
        episodes_per_env = int(math.ceil(float(total_episodes) / float(n_envs)))
        denominator = max(1, episodes_per_env - 1)
        progress = min(1.0, max(0.0, float(per_env_episode_index) / float(denominator)))

        total_active = 0
        for cls in classes:
            start_value = start_counts[cls]
            end_value = end_counts[cls]
            interpolated = start_value + int(math.floor((end_value - start_value) * progress))
            active_count = max(start_value, min(end_value, interpolated))
            total_active += int(active_count)
        return total_active

    def _on_step(self) -> bool:
        """Track episodes and display progress."""
        self.step_count += 1
        if not hasattr(self, 'locals'):
            raise KeyError("EpisodeTerminationCallback missing required callback locals")
        if 'dones' not in self.locals:
            raise KeyError("EpisodeTerminationCallback missing required 'dones' field in callback locals")

        # Track per-env episode stats from callback done flags.
        dones = self.locals['dones']
        now_perf = time.perf_counter()
        try:
            done_flags = [bool(d) for d in dones]
        except TypeError:
            done_flags = [bool(dones)]

        n_envs = len(done_flags)
        if n_envs <= 0:
            raise ValueError("dones must contain at least one environment flag")
        # L'horloge doit avancer strictement : `now_perf` sert d'origine aux durees d'episode
        # ci-dessous, un delta nul ou negatif les rendrait insensees.
        if self._last_step_perf_time is not None:
            delta_step_seconds = now_perf - self._last_step_perf_time
            if delta_step_seconds <= 0:
                raise ValueError(
                    f"Non-positive callback step delta: {delta_step_seconds} "
                    f"(now={now_perf}, prev={self._last_step_perf_time})"
                )
        self._last_step_perf_time = now_perf
        # Cumul du temps passe en evaluation bot, retranche des durees d'episode ci-dessous : une
        # eval periodique bloque TOUS les slots, et le slot qui l'enjambe se verrait sinon
        # imputer ses minutes d'attente. Mesure : une eval de 120 s portait `max` a 121,80 s
        # contre 1,20 s de duree reelle, ce qui rend la colonne `min/max` aveugle a ce qu'elle
        # sert a reperer — une dispersion d'origine MOTEUR.
        total_eval_seconds = (
            self.gate_display_state.get("total_eval_time", 0.0)
            if self.gate_display_state else 0.0
        )
        if self._episode_wall_time_by_env is None:
            self._episode_wall_time_by_env = [now_perf] * n_envs
            self._episode_eval_time_by_env = [total_eval_seconds] * n_envs
        elif len(self._episode_wall_time_by_env) != n_envs:
            raise ValueError(
                "Environment count changed during training; cannot maintain per-env episode timing"
            )
        if self._episode_eval_time_by_env is None:
            raise RuntimeError("Per-env eval time tracking not initialized")

        episodes_finished = 0
        for env_index, done in enumerate(done_flags):
            if not done:
                continue
            episodes_finished += 1
            wall_duration = (
                (now_perf - self._episode_wall_time_by_env[env_index])
                - (total_eval_seconds - self._episode_eval_time_by_env[env_index])
            )
            self._episode_wall_time_by_env[env_index] = now_perf
            self._episode_eval_time_by_env[env_index] = total_eval_seconds
            self.max_episode_duration_seconds = max(
                self.max_episode_duration_seconds,
                wall_duration
            )
            self.min_episode_duration_seconds = min(
                self.min_episode_duration_seconds,
                wall_duration
            )
            self.last_episode_duration_seconds = wall_duration

        episode_ended = episodes_finished > 0
        if episode_ended:
            self.episode_count += episodes_finished
            # Le chrono N'EST PAS retro-date du premier lot d'episodes. Il l'etait, et ce recul
            # valait `total_episode_duration_seconds`, SOMME des durees de chaque slot arrive :
            # a n_envs=48 avec des episodes de 10 s, il reculait de 480 s au lieu de 10, puis
            # figeait ce decalage pour tout le run (mesure du 2026-08-01 : un "demarrage" de
            # -19,5 s a n_envs=16). Le recul est de toute facon sans objet : `start_time` est
            # deja pose au debut de `learn()` (ou au demarrage du process en mode rotation),
            # donc AVANT le premier episode — le retro-dater ne pouvait que compter deux fois.

        # Update progress display on episode end
        if episode_ended:
            current_time = time.time()
            # In curriculum mode (phase_label set), progress must be phase-local.
            # Outside curriculum, keep global progress across rotations.
            if self.phase_label:
                display_episode_count = self.phase_episode_offset + self.episode_count
                display_total_episodes = self.total_episodes
            else:
                display_episode_count = self.global_episode_offset + self.episode_count
                display_total_episodes = self.total_episodes

            # Update progress every 10 episodes, or on final episode of this callback.
            if display_episode_count % 10 == 0 or display_episode_count == 1 or self.episode_count >= self.max_episodes:
                global_progress_pct = (display_episode_count / display_total_episodes) * 100

                # Global progress bar (full width)
                bar_length = self.training_progress_bar_length
                filled = int(bar_length * display_episode_count / display_total_episodes)
                bar = '█' * filled + '░' * (bar_length - filled)

                # Calculate time with EMA for smooth, accurate ETA estimates
                # `start_time` est pose au plus tard par `_on_training_start` (hook SB3 appele
                # avant tout `_on_step`) et au plus tot par le constructeur en mode rotation. Un
                # None ici signifie que le callback tourne hors du cycle d'entrainement : une barre
                # muette masquerait ce cas, alors que toutes les durees affichees en dependent.
                if self.start_time is None:
                    raise RuntimeError(
                        "EpisodeTerminationCallback.start_time not initialized: "
                        "_on_training_start must run before _on_step"
                    )
                # Total elapsed time from start
                elapsed = current_time - self.start_time

                # Update EMA from real deltas (time and episodes), no fixed-batch assumption.
                if (
                    self.last_display_time is not None
                    and self.last_display_episode_count is not None
                ):
                    eval_delta = total_eval_seconds - self.total_eval_time_at_last_display
                    delta_time = current_time - self.last_display_time - eval_delta
                    self.total_eval_time_at_last_display = total_eval_seconds
                    delta_episodes = display_episode_count - self.last_display_episode_count
                    if delta_time > 0 and delta_episodes > 0:
                        avg_time_per_episode = delta_time / delta_episodes
                        if self.ema_episode_time is None:
                            # Initialize EMA with first valid measurement
                            self.ema_episode_time = avg_time_per_episode
                        else:
                            # new_ema = alpha * new_value + (1 - alpha) * old_ema
                            self.ema_episode_time = (
                                self.ema_alpha * avg_time_per_episode
                                + (1 - self.ema_alpha) * self.ema_episode_time
                            )
                self.last_display_time = current_time
                self.last_display_episode_count = display_episode_count

                # Calculate ETA using EMA; use overall average when EMA not yet available (early episodes)
                remaining_episodes = display_total_episodes - display_episode_count
                # Secondes d'ENTRAINEMENT par episode produit, hors evaluation.
                # Numerateur : le temps d'eval bot est retranche, comme le fait deja l'EMA
                # ci-dessus. Une eval periodique bloque la boucle plusieurs minutes (13 min
                # mesurees contre 21 s d'entrainement sur un run de 6 episodes) : l'y laisser
                # rendrait un chiffre plusieurs fois trop lent, et surtout incomparable entre
                # deux runs de cadences d'eval differentes — ce que cette colonne existe
                # justement pour permettre. `total_eval_time` est porte par `gate_display_state`,
                # construit dans `setup_callbacks` (ai/train.py:3536) donc de meme portee que
                # `start_time` : les deux datent du chunk courant.
                # Denominateur : `episode_count`, le compteur LOCAL a ce callback, et surtout PAS
                # `display_episode_count`. En rotation de scenarios un callback neuf est construit
                # a chaque chunk avec un `global_start_time` lui aussi remis a `time.time()`
                # (ai/train.py:3032), tandis que les offsets d'affichage CUMULENT les chunks
                # precedents (ai/train.py:4381-4382) : diviser un temps local par un compteur
                # cumulatif rend un taux effondre — a l'offset 992, 0.000 pour un vrai 0,031 s/ep.
                # Non garde : on est sous `if episode_ended`, qui vient d'incrementer le compteur.
                training_elapsed = elapsed - total_eval_seconds
                avg_training_time_per_episode = training_elapsed / self.episode_count

                if self.ema_episode_time is not None:
                    eta = self.ema_episode_time * remaining_episodes
                else:
                    # Use overall average when EMA not yet available (early episodes)
                    eta = avg_training_time_per_episode * remaining_episodes

                # Format times as HH:MM:SS or MM:SS depending on duration
                def format_time(seconds):
                    hours = int(seconds // 3600)
                    minutes = int((seconds % 3600) // 60)
                    secs = int(seconds % 60)
                    if hours > 0:
                        return f"{hours}:{minutes:02d}:{secs:02d}"
                    else:
                        return f"{minutes:02d}:{secs:02d}"

                elapsed_str = format_time(elapsed)
                eta_str = format_time(eta)
                time_info = f"{elapsed_str}<{eta_str}"

                # TOUTE la ligne est en secondes de wall-clock PAR EPISODE PRODUIT, et le
                # diviseur est annonce UNE fois en tete. Melanger deux echelles sur une meme
                # ligne est precisement ce qui a fait conclure a un ralentissement le
                # 2026-08-01 : `cur`, `min` et `max` sont mesures PAR SLOT (l'intervalle entre
                # deux `done` d'un meme environnement, attente de synchronisation comprise),
                # donc ~n_envs fois la seconde par episode reellement ecoulee — le passage de 8
                # a 48 envs les a multipliees par 3,4 alors que le debit avait double. Les
                # ramener ici a l'echelle de `moy` les rend comparables entre deux runs de
                # `n_envs` differents. C'est un CHANGEMENT D'UNITE, pas une estimation : chaque
                # valeur reste la duree d'UN episode, exprimee en secondes de wall par episode
                # produit — « si les n_envs slots tenaient ce rythme ». Aucun biais de remplissage
                # ici, contrairement a la moyenne par slot (cf. plus bas) : rien n'est somme sur
                # les slots, et `n_envs` est constant sur la duree du run (garde plus haut sur
                # `_episode_wall_time_by_env`).
                # `:.3f` et non `:.2f` : a n_envs=48 une duree par slot de 12 s tombe a 0,250, et
                # deux decimales ecraseraient la dispersion que `min/max` sert a montrer. Sous
                # ~0,005 s par episode (soit une duree par slot inferieure a 0,25 s a n_envs=48,
                # regime que ce moteur n'atteint pas), il faudrait une decimale de plus.
                # `moy` n'est PAS divise : il vaut deja temps d'entrainement / episodes produits.
                # Il ne se calcule surtout pas comme `moyenne par slot / n_envs`, division qui
                # n'est exacte qu'une fois que CHAQUE slot a fini un episode et rend `n_envs/k`
                # fois trop peu tant que seuls `k` slots sont arrives — 48x sur le premier
                # affichage. Les quatre valeurs excluent le temps d'eval bot, retranche a la
                # source dans la boucle des durees.
                duration_display = (
                    f"s/ep ({n_envs} env): "
                    f"cur {self.last_episode_duration_seconds / n_envs:.3f}, "
                    f"moy {avg_training_time_per_episode:.3f}, "
                    f"min/max: {self.min_episode_duration_seconds / n_envs:.3f}"
                    f"/{self.max_episode_duration_seconds / n_envs:.3f}"
                )
                gate_label = "Gate 🧱"
                robust_status_text = ""
                if self.gate_display_state is not None:
                    label_value = self.gate_display_state.get("label")
                    if isinstance(label_value, str) and label_value.strip():
                        gate_label = label_value.strip()
                    robust_value = self.gate_display_state.get("best_robust_score")
                    robust_trend = self.gate_display_state.get("robust_trend_symbol")
                    if isinstance(robust_value, (float, int)) and robust_value > -float("inf"):
                        robust_status_text = f" | robust={float(robust_value):.4f}"
                    else:
                        robust_status_text = " | robust=NA"
                    if isinstance(robust_trend, str) and robust_trend.strip():
                        robust_status_text += f" {robust_trend.strip()}"

                # Use \r for overwriting progress, but add spaces to clear previous longer lines
                phase_display = f" | {self.phase_label}" if self.phase_label else ""
                roster_display = ""
                roster_count = self._compute_training_roster_count(display_episode_count)
                if roster_count is not None:
                    roster_display = f" | Rosters: {roster_count}"
                progress_line = (
                    f"{global_progress_pct:3.0f}% {bar} {display_episode_count}/{display_total_episodes}"
                    f" [{time_info}] [{duration_display}] {gate_label}"
                    f"{robust_status_text}{roster_display}{phase_display}"
                )
                # CRITICAL: Read prev_len BEFORE overwriting — eval may have set a longer line
                prev_len = self._last_progress_line_len
                if self.gate_display_state is not None:
                    if "last_progress_line_len" not in self.gate_display_state:
                        self.gate_display_state["last_progress_line_len"] = 0
                    prev_len = max(prev_len, int(require_key(self.gate_display_state, "last_progress_line_len")))
                clear_padding = " " * max(0, prev_len - len(progress_line))
                print(f"\r{progress_line}{clear_padding}", end='', flush=True)
                self._last_progress_line_len = len(progress_line)
                # Store training prefix and current len AFTER display (for next eval)
                if self.gate_display_state is not None:
                    self.gate_display_state["training_prefix"] = (
                        f"{global_progress_pct:3.0f}% {bar} {display_episode_count}/{display_total_episodes}"
                        f" [{time_info}] [{duration_display}] "
                    )
                    self.gate_display_state["last_progress_line_len"] = len(progress_line)

        # CRITICAL: Stop when max episodes reached (unless disabled for rotation mode)
        if self.episode_count >= self.max_episodes:
            if self.disable_early_stopping:
                # Rotation mode: Let model.learn() consume all timesteps
                # Don't stop early - just continue tracking episodes for metrics
                return True
            else:
                # Normal mode: Stop when episode count reached (silent for rotation training)
                print()
                return False

        return True

# La classe EpisodeBasedEvalCallback (evaluation declenchee tous les N episodes plutot que tous
# les N pas) occupait cette place. Elle etait exportee dans __all__ et importee par ai/train.py,
# mais JAMAIS instanciee — preuve dans les quatre directions : aucun `EpisodeBasedEvalCallback(`
# dans le depot, aucune sous-classe ni acces par attribut, aucune mention dans les configs JSON
# ni construction de callback par nom (les seuls getattr sur un callback visent l'instance
# bot_eval_callback deja construite, par attribut litteral), et un unique import sans usage.
# L'evaluation periodique reelle est faite par BotEvaluationCallback, qui sait deja compter en
# episodes (use_episode_freq) : c'est la qu'il faut regarder, pas ici.


class MetricsCollectionCallback(BaseCallback):
    """Callback to collect training metrics and send to W40KMetricsTracker."""
    
    def __init__(self, metrics_tracker: Any, model: Any, controlled_agent: Any = None, verbose: int = 0):
        super().__init__(verbose)
        self.metrics_tracker: Any = metrics_tracker
        self.model = model
        self.controlled_agent = controlled_agent  # CRITICAL FIX: Store controlled_agent for bot evaluation
        self.episode_count = 0
        
        # Initialize episode tracking with ALL metrics
        self.episode_tactical_data = {
            # Combat metrics
            'shots_fired': 0,
            'hits': 0,
            'total_enemy_units': 0,
            'killed_enemies': 0,
            
            # NEW: Damage tracking
            'damage_dealt': 0,
            'damage_received': 0,
            
            # NEW: Unit tracking
            'units_lost': 0,
            'units_killed': 0,
            'enemy_value_destroyed': 0.0,
            'ally_value_lost': 0.0,
            
            # NEW: Action tracking
            'valid_actions': 0,
            'invalid_actions': 0,
            'wait_actions': 0,
            'total_actions': 0,
            
            # Phase tracking
            'phases_completed': 0,
            'total_phases': 6
        }
        
        # Track initial unit state for damage/loss calculations
        self.initial_agent_units = []
        self.initial_enemy_units = []
        
        # Add immediate reward ratio history for smoothing
        self.immediate_reward_ratio_history = []
        self.max_reward_ratio_history = 50  # Keep last 50 episodes
        
        # Metriques d'observation par phase, UN accumulateur PAR ENVIRONNEMENT — meme raison
        # que la ventilation de recompense : un dictionnaire unique melangeait les 48 parties
        # et etait vide par celle qui finissait la premiere.
        self.episode_observation_phase_data_by_env: Dict[int, Dict[str, Dict[str, List[float]]]] = {}

    def _get_observation_batch_from_locals(self):
        """Get current observation batch from callback locals."""
        if not hasattr(self, 'locals'):
            return None
        if 'new_obs' in self.locals:
            return self.locals['new_obs']
        if 'obs' in self.locals:
            return self.locals['obs']
        return None

    def _extract_valid_target_metrics_from_obs(self, obs_vector: np.ndarray) -> Dict[str, List[float]]:
        """
        Extract valid-target metrics from observation vector.
        Valid target block: 5 slots × 8 features at [273:313].
        """
        if obs_vector.ndim != 1:
            raise ValueError(f"Expected 1D observation vector, got shape={obs_vector.shape}")
        if obs_vector.shape[0] < 313:
            raise ValueError(f"Observation size too small for valid target block: size={obs_vector.shape[0]}")

        base_idx = 273
        slot_size = 8
        max_slots = 5
        kill_values: List[float] = []
        danger_values: List[float] = []
        valid_count = 0

        for slot_idx in range(max_slots):
            slot_base = base_idx + (slot_idx * slot_size)
            is_valid = float(obs_vector[slot_base + 0])
            if is_valid > 0.5:
                valid_count += 1
                kill_values.append(float(obs_vector[slot_base + 2]))
                danger_values.append(float(obs_vector[slot_base + 3]))

        return {
            'best_kill_probability': kill_values,
            'danger_to_me': danger_values,
            'valid_target_count': [float(valid_count)],
        }
    
    _PPO_KEYS = frozenset({
        'train/policy_gradient_loss', 'train/value_loss', 'train/entropy_loss',
        'train/clip_fraction', 'train/approx_kl', 'train/explained_variance',
        'train/learning_rate',
    })

    def _on_training_start(self) -> None:
        """Wrap logger.dump to capture PPO metrics BEFORE SB3 clears name_to_value."""
        if not (hasattr(self.model, 'logger') and self.model.logger and hasattr(self, 'metrics_tracker') and self.metrics_tracker):
            return
        _original_dump = self.model.logger.dump
        _tracker = self.metrics_tracker
        _model = self.model

        def _dump_with_capture(step: int = 0) -> None:
            ntv = getattr(_model.logger, 'name_to_value', {})
            if ntv:
                model_stats: Dict[str, Any] = dict(ntv)
                if hasattr(_model, 'policy') and hasattr(_model.policy, 'parameters'):
                    total_norm = 0.0
                    param_count = 0
                    for p in cast(Any, _model.policy).parameters():
                        if p.grad is not None:
                            param_norm = p.grad.data.norm(2)
                            total_norm += param_norm.item() ** 2
                            param_count += 1
                    if param_count > 0:
                        model_stats['train/gradient_norm'] = total_norm ** 0.5
                if hasattr(_model, "ent_coef"):
                    ent_coef_value: Any = cast(Any, _model).ent_coef
                    if isinstance(ent_coef_value, torch.Tensor):
                        ent_coef_value = float(ent_coef_value.detach().item())
                    else:
                        ent_coef_value = float(ent_coef_value)
                    model_stats['train/ent_coef'] = ent_coef_value
                _tracker.log_training_metrics(model_stats)
                _tracker.step_count = cast(Any, _model).num_timesteps
            _original_dump(step)

        self.model.logger.dump = _dump_with_capture

    def _on_rollout_start(self) -> None:
        pass
    
    def print_final_training_summary(self, model=None, training_config=None, training_config_name=None, rewards_config_name=None):
        """Print comprehensive training summary with final bot evaluation"""
        
        if model and training_config and training_config_name and rewards_config_name:
            # Extract n_episodes from config
            if 'callback_params' not in training_config:
                raise KeyError("training_config missing required 'callback_params' field")
            if 'bot_eval_final' not in training_config['callback_params']:
                raise KeyError("training_config['callback_params'] missing required 'bot_eval_final' field")
            n_final = training_config['callback_params']['bot_eval_final']
            if n_final <= 0:
                print("\n" + "="*80)
                print("🎯 TRAINING COMPLETE - FINAL EVALUATION SKIPPED")
                print("="*80)
                print("ℹ️  Final bot evaluation skipped (bot_eval_final=0)")
                bot_results = None
            else:
                print("\n" + "="*80)
                print("🎯 TRAINING COMPLETE - RUNNING FINAL EVALUATION")
                print("="*80)
                bot_results = self._run_final_bot_eval(model, training_config, training_config_name, rewards_config_name)
            
            if bot_results:
                # Log to metrics_tracker for TensorBoard
                if hasattr(self, 'metrics_tracker') and self.metrics_tracker:
                    self.metrics_tracker.log_bot_evaluations(bot_results)
                    # Le gap par roster doit exister AU SCORE LIVRE, pas seulement sur les
                    # evaluations intermediaires : c'est le point de mesure que l'on cite.
                    self.metrics_tracker.log_faction_scores(
                        require_key(bot_results, 'faction_scores'),
                        bot_results.get('roster_gap'),
                    )
                    # Flush to ensure metrics are written immediately
                    self.metrics_tracker.writer.flush()
                
                # Print results
                for bk in ALL_BOT_NAMES:
                    if bk in bot_results:
                        label = bk.replace("_", " ").title() + "Bot"
                        print(f"vs {label+':':<22s}{bot_results[bk]:.2f} ({bot_results.get(f'{bk}_wins', '?')}/{n_final} wins)")
                print(f"\nCombined Score:   {bot_results['combined']:.2f} {'✅' if bot_results['combined'] >= 0.70 else '⚠️'}")
                scenario_scores = bot_results.get("scenario_scores")
                if isinstance(scenario_scores, dict) and scenario_scores:
                    ranking = sorted(
                        scenario_scores.items(),
                        key=lambda item: item[1]["combined"],
                        reverse=True
                    )
                    print("\nScenario ranking (combined):")
                    for scenario_name, values in ranking:
                        print(
                            f"  - {scenario_name}: combined={values['combined']:.3f} "
                            f"| worst_bot_score={values['worst_bot_score']:.3f}"
                        )
        
        # Critical metrics check
        print(f"\n📊 CRITICAL METRICS:")
        
        # Check clip_fraction
        if len(self.metrics_tracker.hyperparameter_tracking['clip_fractions']) >= 20:
            recent_clip = np.mean(self.metrics_tracker.hyperparameter_tracking['clip_fractions'][-20:])
            clip_status = "✅" if 0.1 <= recent_clip <= 0.3 else "⚠️ "
            print(f"   Clip Fraction:      {recent_clip:.3f} {clip_status} (target: 0.1-0.3)")
            if recent_clip < 0.1:
                print(f"      ->  Increase learning_rate (policy not updating enough)")
            elif recent_clip > 0.3:
                print(f"      -> Decrease learning_rate (too aggressive updates)")
        
        # Check explained_variance
        if len(self.metrics_tracker.hyperparameter_tracking['explained_variances']) >= 20:
            recent_ev = np.mean(self.metrics_tracker.hyperparameter_tracking['explained_variances'][-20:])
            ev_status = "✅" if recent_ev > 0.3 else "⚠️ "
            print(f"   Explained Variance: {recent_ev:.3f} {ev_status} (target: >0.3)")
            if recent_ev < 0.3:
                print(f"      -> Value function struggling - check reward signal")
        
        # Check entropy
        if len(self.metrics_tracker.hyperparameter_tracking['entropy_losses']) >= 20:
            recent_entropy = np.mean(self.metrics_tracker.hyperparameter_tracking['entropy_losses'][-20:])
            entropy_status = "✅" if 0.5 <= recent_entropy <= 2.0 else "⚠️ "
            print(f"   Entropy Loss:       {recent_entropy:.3f} {entropy_status} (target: 0.5-2.0)")
            if recent_entropy < 0.5:
                print(f"      -> Increase ent_coef (exploration too low)")
            elif recent_entropy > 2.0:
                print(f"      -> Decrease ent_coef (exploration too high)")
        
        # Check gradient_norm
        if hasattr(self.metrics_tracker, 'latest_gradient_norm') and self.metrics_tracker.latest_gradient_norm:
            grad_norm = self.metrics_tracker.latest_gradient_norm
            grad_status = "✅" if grad_norm < 10 else "⚠️ "
            print(f"   Gradient Norm:      {grad_norm:.3f} {grad_status} (target: <10)")
            if grad_norm > 10:
                print(f"      -> Reduce max_grad_norm or learning_rate")
        
        print(f"\n💡 TensorBoard: {self.metrics_tracker.log_dir}")
        print(f"   -> Focus on 00_critical/ namespace for hyperparameter tuning")
        print("="*80 + "\n")
    
    def _run_final_bot_eval(self, model, training_config, training_config_name, rewards_config_name):
        """Run final comprehensive bot evaluation using standalone function"""
        # Lazy import to avoid circular dependency
        from ai.bot_evaluation import evaluate_against_bots

        controlled_agent = self.controlled_agent  # CRITICAL FIX: Use stored controlled_agent instead of looking in training_config

        # Extract n_episodes from callback_params in training_config
        if 'callback_params' not in training_config:
            raise KeyError("training_config missing required 'callback_params' field")
        if 'bot_eval_final' not in training_config['callback_params']:
            raise KeyError("training_config['callback_params'] missing required 'bot_eval_final' field")
        n_episodes = training_config['callback_params']['bot_eval_final']
        eval_deterministic = require_key(training_config['callback_params'], 'eval_deterministic')
        if not isinstance(eval_deterministic, bool):
            raise ValueError(
                f"callback_params.eval_deterministic must be boolean "
                f"(got {type(eval_deterministic).__name__})"
            )

        # Use standalone function with progress bar for final eval
        # `scenario_pool` est EXPLICITE : l'éval finale est une éval de MESURE, elle doit porter
        # sur le holdout (§10.5 — le holdout porte sur l'adversaire). Miroir des 3 autres sites
        # de mesure (train.py:3012, :4257, :4646), qui codent la même valeur en dur ; la clé de
        # config `bot_eval_scenario_pool` n'alimente, elle, que l'éval INTERMÉDIAIRE (gating).
        # Ne PAS retirer cet argument : la signature de `evaluate_against_bots` a pour défaut
        # `"training"`, donc l'omettre fait silencieusement mesurer le scénario D'ENTRAÎNEMENT.
        # C'était le bug V11 §0.12 (mesuré : `Scenario ranking: training_armageddon`).
        return evaluate_against_bots(
            model=model,
            training_config_name=training_config_name,
            rewards_config_name=rewards_config_name,
            n_episodes=n_episodes,
            controlled_agent=controlled_agent,
            show_progress=True,
            deterministic=eval_deterministic,
            scenario_pool="holdout",
        )
    
    def _on_step(self) -> bool:
        """Collect step-level data including actions, damage, and unit changes"""
        obs_batch = self._get_observation_batch_from_locals()
        # `self.episode_reward += rewards[0]` et `self.episode_length += 1` occupaient cette
        # place. Aucun lecteur : la recompense et la longueur d'episode logguees viennent de
        # `info["episode"]` ("r" et "l", poses par le Monitor de CHAQUE env), pas d'eux. Ils
        # etaient de surcroit faux par construction avec n_envs=48 — somme des recompenses du
        # seul env 0, incrementee une fois par pas de VecEnv (donc 48 pas de jeu), et remise a
        # zero par la fin d'episode de n'importe lequel des environnements.
        if hasattr(self, 'locals'):
            # Process info dict for action tracking
            if 'infos' in self.locals:
                for idx, info in enumerate(self.locals['infos']):
                    is_controlled_action = bool(info.get('is_controlled_action', False))
                    phase_name = info.get('phase')
                    if (
                        is_controlled_action
                        and isinstance(phase_name, str)
                        and phase_name in self.OBSERVATION_PHASES
                        and obs_batch is not None
                    ):
                        if isinstance(obs_batch, np.ndarray) and obs_batch.ndim == 2:
                            if idx >= obs_batch.shape[0]:
                                raise IndexError(
                                    f"Observation batch index out of range: idx={idx}, shape={obs_batch.shape}"
                                )
                            obs_vector = obs_batch[idx]
                        elif isinstance(obs_batch, np.ndarray) and obs_batch.ndim == 1:
                            obs_vector = obs_batch
                        elif isinstance(obs_batch, list):
                            if idx >= len(obs_batch):
                                raise IndexError(
                                    f"Observation batch index out of range: idx={idx}, len={len(obs_batch)}"
                                )
                            obs_vector = np.asarray(obs_batch[idx], dtype=np.float32)
                        else:
                            raise TypeError(
                                f"Unsupported observation batch type for metrics extraction: {type(obs_batch).__name__}"
                            )

                        extracted = self._extract_valid_target_metrics_from_obs(np.asarray(obs_vector))
                        phase_data = self.episode_observation_phase_data_by_env.setdefault(
                            idx, self._empty_observation_phase_data()
                        )[phase_name]
                        phase_data['best_kill_probability'].extend(extracted['best_kill_probability'])
                        phase_data['danger_to_me'].extend(extracted['danger_to_me'])
                        phase_data['valid_target_count'].extend(extracted['valid_target_count'])

                    # Le comptage de `valid_actions` / `invalid_actions` / `total_actions` /
                    # `wait_actions` occupait cette place, depuis `info['success']` et
                    # `info['action']`. Il ne servait a rien : le MOTEUR compte les memes
                    # quantites dans `episode_tactical_data` (seat-aware, sur le vrai step de
                    # l'agent), et le `.update(info['tactical_data'])` de fin d'episode ecrasait
                    # les compteurs du callback avant toute lecture. Un compteur unique nourri
                    # par 48 environnements n'aurait de toute facon rien mesure.

                    # Track zone intent steps (SubprocVecEnv-safe: read from info dict).
                    # ECRIVAIN UNIQUE de ces compteurs : le moteur ne compte plus lui-meme (son
                    # `_metrics_tracker` n'etait arme qu'a n_envs==1, donc `--step` comptait
                    # double). Les deux cles sont posees ensemble par la branche zone_intent de
                    # w40k_core : leur absence est un defaut de cablage, pas un cas nominal.
                    if is_controlled_action and info.get('action') == 'zone_intent' and self.metrics_tracker is not None:
                        self.metrics_tracker.log_zone_intent_step(
                            int(require_key(info, 'intent_value')),
                            float(require_key(info, 'zone_control')),
                        )

                    # `if 'totalDamage' in info: episode_tactical_data['damage_dealt'] += ...`
                    # occupait cette place. Aucun producteur : `totalDamage` n'est ecrit nulle
                    # part cote Python (info vient de result.copy(), et aucun handler ne pose
                    # cette cle). Meme defaut silencieux que position_score. La valeur etait de
                    # toute facon ecrasee a la fin de l'episode par le `episode_tactical_data`
                    # du moteur (voir .update(info['tactical_data']) plus bas), ou damage_dealt
                    # est initialise a 0 et jamais incremente non plus : la courbe
                    # game_detailed/damage_dealt, gardee par `> 0`, n'a jamais ete emise.

                    # CHARGE SUCCESS TRACKING: Log successful charges (optional per step)
                    if is_controlled_action and info.get('charge_succeeded', False):  # get allowed
                        cast(Any, self.metrics_tracker).log_combat_kill('charge')

                    # Handle episode end - check for 'episode' key (Monitor wrapper adds this)
                    if 'episode' in info:
                        self._handle_episode_end(info, idx)

        # Le suivi periodique des Q-values (train/q_value_mean_smooth, toutes les 100 etapes)
        # occupait cette place. Meme raison que son jumeau d'EpisodeBasedEvalCallback (classe
        # depuis supprimee, voir la trace plus haut dans ce fichier) :
        # il etait garde par `hasattr(self.model, 'q_net')`, et seul MaskablePPO est instancie
        # dans ce projet — un actor-critic, sans q_net. Le commentaire qui l'accompagnait
        # l'admettait deja. self.q_value_history / max_q_value_history partent avec lui.

        # Log training step data
        step_data = {}
        if hasattr(self.model, 'learning_rate'):
            # learning_rate may be a callable schedule function - evaluate it
            lr = self.model.learning_rate
            if callable(lr):
                # Call with current progress (1.0 at start, 0.0 at end)
                step_data['learning_rate'] = lr(self.model._current_progress_remaining if hasattr(self.model, '_current_progress_remaining') else 1.0)
            else:
                step_data['learning_rate'] = lr
        if hasattr(self.model, 'logger') and hasattr(self.model.logger, 'name_to_value'):
            if 'train/loss' in self.model.logger.name_to_value:
                step_data['loss'] = self.model.logger.name_to_value['train/loss']
        # `if hasattr(self.model, 'exploration_rate'): step_data['exploration_rate'] = ...`
        # occupait cette place. exploration_rate est l'epsilon d'une politique epsilon-greedy
        # (DQN) : MaskablePPO explore par l'entropie de sa politique, il n'a pas cet attribut.
        # La cle n'etait donc jamais posee, et la courbe training_diagnostic/exploration_rate
        # cote metrics_tracker n'a jamais rien recu.

        if step_data:
            cast(Any, self.metrics_tracker).log_training_step(step_data)
        
        # NOTE: PPO training metrics are captured in _on_rollout_start()
        # SB3 only populates model.logger.name_to_value during train() which happens BETWEEN rollouts
        
        return True
    
    #: Phases dont l'observation est instrumentee (cf. log_observation_phase_metrics).
    OBSERVATION_PHASES = ('shoot', 'fight', 'charge')

    @classmethod
    def _empty_observation_phase_data(cls) -> Dict[str, Dict[str, List[float]]]:
        """Accumulateur d'observation vide, une entree par phase instrumentee."""
        return {
            phase: {'best_kill_probability': [], 'danger_to_me': [], 'valid_target_count': []}
            for phase in cls.OBSERVATION_PHASES
        }

    def _flush_observation_phase_data(self, env_index: int) -> None:
        """Publie les metriques d'observation de l'episode qui finit, et de LUI SEUL.

        Les 47 autres environnements sont au milieu de leur propre episode : ni leur contenu
        ni leur remise a zero ne les concerne.
        """
        phase_data = self.episode_observation_phase_data_by_env.get(int(env_index))  # get allowed
        if phase_data is None:
            # Cet environnement n'a encore produit aucune observation instrumentee : il n'y a
            # pas d'accumulateur. Un episode instrumente mais sans cible valide publie bien ses
            # listes vides, que le tracker sait ne pas transformer en courbe.
            return
        self.metrics_tracker.log_observation_phase_metrics(phase_data)
        self.episode_observation_phase_data_by_env[int(env_index)] = self._empty_observation_phase_data()

    def _handle_episode_end(self, info, env_index: int):
        """Handle episode completion and log metrics."""
        self.episode_count += 1

        # CRITICAL: Update step_count BEFORE logging episode metrics
        # This ensures 00_critical/ metrics use timesteps (not episodes) as x-axis
        self.metrics_tracker.step_count = self.model.num_timesteps

        # Extract episode data (we are only called when 'episode' in info; engine sets info["episode"] = {"r","l","t"})
        ep = info['episode']
        episode_data = {
            'total_reward': float(ep['r']),
            'episode_length': int(ep['l']),
            'winner': info['winner'] if 'winner' in info else None,
            'controlled_player': int(require_key(info, 'controlled_player')),
            'win_method': (
                str(require_key(info, 'win_method'))
                if ('winner' in info and info['winner'] is not None)
                else None
            ),
            # "active" | "fixed" | None (scheduler inactif). Cle EXIGEE : le moteur la pose a
            # chaque episode termine (w40k_core, bloc `if terminated`), donc son absence est un
            # defaut de cablage, pas un episode sans mode.
            'deployment_mode': require_key(info, 'deployment_mode'),
        }

        # GAMMA MONITORING: Track discount factor effects
        if hasattr(self.model, 'gamma'):
            gamma = cast(Any, self.model).gamma
           
            # Calculate temporal metrics
            immediate_reward_ratio = self._calculate_immediate_vs_future_ratio(info)
            planning_horizon = self._estimate_planning_horizon(gamma)
           
            # Track ratio history for smoothing
            self.immediate_reward_ratio_history.append(immediate_reward_ratio)
            if len(self.immediate_reward_ratio_history) > self.max_reward_ratio_history:
                self.immediate_reward_ratio_history.pop(0)
           
            # Calculate smoothed mean
            ratio_mean = sum(self.immediate_reward_ratio_history) / len(self.immediate_reward_ratio_history)
           
            # Log gamma-related metrics
            if hasattr(self.model, 'logger') and self.model.logger:
                self.model.logger.record('config/discount_factor', gamma)
                self.model.logger.record('config/immediate_reward_ratio', immediate_reward_ratio)
                self.model.logger.record('config/immediate_reward_ratio_mean', ratio_mean)
                self.model.logger.record('config/planning_horizon', planning_horizon)
                # Force tensorboard dump to ensure gamma metrics are written
                self.model.logger.dump(step=self.model.num_timesteps)

        # tactical_data du moteur — cle EXIGEE, pas testee.
        # Le `if 'tactical_data' in info:` qui gardait ce bloc laissait passer un episode sans
        # donnees tactiques : log_tactical_metrics etait appele juste apres DE TOUTE FACON, avec
        # le dict de l'episode PRECEDENT, non reinitialise. Chaque courbe tactique aurait alors
        # recompte deux fois le meme episode sans que rien ne le signale.
        # L'exigence est structurelle : W40KEngine.step pose info["episode"] et
        # info["tactical_data"] dans le MEME bloc `if terminated:` — on n'entre ici que sur
        # info["episode"], donc l'un ne peut pas arriver sans l'autre. Verifie sur le run
        # complet : 50 000 episodes joues, 50 000 points logues sur chaque courbe tactique.
        tactical_data = require_key(info, 'tactical_data')
        self.episode_tactical_data.update(tactical_data)
        if 'total_actions' not in tactical_data:
            valid_actions = int(require_key(tactical_data, 'valid_actions'))
            invalid_actions = int(require_key(tactical_data, 'invalid_actions'))
            self.episode_tactical_data['total_actions'] = valid_actions + invalid_actions

        victory_points_cumulative_episode = float(
            require_key(tactical_data, 'victory_points_cumulative_episode')
        )
        self.metrics_tracker.log_victory_points_cumulative(victory_points_cumulative_episode)

        # Log to metrics tracker (KEEP for state tracking)
        self.metrics_tracker.log_episode_end(episode_data)
        self.metrics_tracker.log_tactical_metrics(self.episode_tactical_data)
        self._flush_observation_phase_data(env_index)
        
        # CRITICAL FIX: Write game_critical metrics directly to model.logger
        # This ensures metrics appear in same TensorBoard directory as train/ metrics
        if hasattr(self.model, 'logger') and self.model.logger:
            total_reward = episode_data['total_reward']
            episode_length = episode_data['episode_length']
            winner = episode_data['winner']
            win_method = episode_data['win_method']
            
            # Game critical metrics
            self.model.logger.record('game_critical/episode_reward', total_reward)
            self.model.logger.record('game_critical/episode_length', episode_length)
            
            # Win rate calculation (need rolling window)
            if not hasattr(self, 'win_rate_window'):
                self.win_rate_window = deque(maxlen=100)

            if winner is not None:
                controlled_player = int(require_key(episode_data, 'controlled_player'))
                agent_won = 1.0 if winner == controlled_player else 0.0
                self.win_rate_window.append(agent_won)
                if win_method is None:
                    raise ValueError("win_method is required when winner is not None")

                # SEAT-AWARE metrics for TensorBoard (global + per controlled side)
                if not hasattr(self, 'seat_aware_counts'):
                    self.seat_aware_counts = {
                        'episodes_agent_p1': 0,
                        'episodes_agent_p2': 0,
                        'wins_agent_p1': 0.0,
                        'wins_agent_p2': 0.0,
                    }
                if controlled_player == 1:
                    self.seat_aware_counts['episodes_agent_p1'] += 1
                    self.seat_aware_counts['wins_agent_p1'] += agent_won
                elif controlled_player == 2:
                    self.seat_aware_counts['episodes_agent_p2'] += 1
                    self.seat_aware_counts['wins_agent_p2'] += agent_won
                else:
                    raise ValueError(f"controlled_player must be 1 or 2 (got {controlled_player})")

                total_seat_episodes = (
                    self.seat_aware_counts['episodes_agent_p1'] + self.seat_aware_counts['episodes_agent_p2']
                )
                total_seat_wins = (
                    self.seat_aware_counts['wins_agent_p1'] + self.seat_aware_counts['wins_agent_p2']
                )
                if total_seat_episodes > 0:
                    self.model.logger.record(
                        'seat_aware/winrate_global',
                        float(total_seat_wins / total_seat_episodes)
                    )
                if self.seat_aware_counts['episodes_agent_p1'] > 0:
                    self.model.logger.record(
                        'seat_aware/winrate_agent_p1',
                        float(
                            self.seat_aware_counts['wins_agent_p1']
                            / self.seat_aware_counts['episodes_agent_p1']
                        )
                    )
                if self.seat_aware_counts['episodes_agent_p2'] > 0:
                    self.model.logger.record(
                        'seat_aware/winrate_agent_p2',
                        float(
                            self.seat_aware_counts['wins_agent_p2']
                            / self.seat_aware_counts['episodes_agent_p2']
                        )
                    )
                self.model.logger.record(
                    'seat_aware/episodes_agent_p1',
                    float(self.seat_aware_counts['episodes_agent_p1'])
                )
                self.model.logger.record(
                    'seat_aware/episodes_agent_p2',
                    float(self.seat_aware_counts['episodes_agent_p2'])
                )

                # Win-method diagnostics: helps identify objective/tiebreaker seat bias.
                if not hasattr(self, 'win_method_counts'):
                    self.win_method_counts = {
                        'objectives': 0,
                        'value_tiebreaker': 0,
                        'draw': 0,
                        'step_limit': 0,
                    }
                if win_method not in self.win_method_counts:
                    raise ValueError(f"Unexpected win_method '{win_method}'")
                self.win_method_counts[win_method] += 1
                win_method_total = float(sum(self.win_method_counts.values()))
                self.model.logger.record(
                    'game_critical/win_method_objectives_rate',
                    float(self.win_method_counts['objectives']) / win_method_total
                )
                self.model.logger.record(
                    'game_critical/win_method_value_tiebreaker_rate',
                    float(self.win_method_counts['value_tiebreaker']) / win_method_total
                )
                self.model.logger.record(
                    'game_critical/win_method_draw_rate',
                    float(self.win_method_counts['draw']) / win_method_total
                )
                self.model.logger.record(
                    'game_critical/win_method_step_limit_rate',
                    float(self.win_method_counts['step_limit']) / win_method_total
                )

                # Fenetre PLEINE exigee, pas 10 episodes : sous la fenetre, la moyenne porte
                # sur tout l'historique et converge en descendant depuis un echantillon de
                # depart bruite. Cette descente n'est pas une degradation de l'agent, mais
                # elle en a l'allure exacte (cf. PERF_WINDOW dans ai/metrics_tracker.py).
                if len(self.win_rate_window) == self.win_rate_window.maxlen:
                    rolling_win_rate = np.mean(self.win_rate_window)
                    self.model.logger.record('game_critical/win_rate_100ep', rolling_win_rate)
            
            # Tactical metrics (after update from info['tactical_data'], engine guarantees these keys)
            units_killed = self.episode_tactical_data['units_killed']
            units_lost = self.episode_tactical_data['units_lost']
            if units_lost > 0:
                kill_loss_ratio = units_killed / units_lost
                self.model.logger.record('game_critical/units_killed_vs_lost_ratio', kill_loss_ratio)

            # Invalid action rate
            total_actions = self.episode_tactical_data['total_actions']
            if total_actions > 0:
                invalid_rate = self.episode_tactical_data['invalid_actions'] / total_actions
                self.model.logger.record('game_critical/invalid_action_rate', invalid_rate)

            # Dump metrics to TensorBoard
            self.model.logger.dump(step=self.model.num_timesteps)
        
        # Ventilation de la recompense : cumulee par le MOTEUR sur tout l'episode (chaque step
        # moteur y ajoute sa part) et transmise dans `tactical_data`. Le callback ne peut pas
        # l'accumuler lui-meme : il ne voit qu'un info par step gym, celui du dernier step
        # moteur, donc celui du bot des que le wrapper d'adversaire rejoue apres l'agent.
        self.metrics_tracker.log_reward_decomposition(
            require_key(self.episode_tactical_data, 'reward_breakdown')
        )

        # Reset episode tracking with ALL fields
        self.episode_tactical_data = {
            # Combat metrics
            'shots_fired': 0,
            'hits': 0,
            'total_enemy_units': 0,
            'killed_enemies': 0,
            
            # Damage tracking
            'damage_dealt': 0,
            'damage_received': 0,
            
            # Unit tracking
            'units_lost': 0,
            'units_killed': 0,
            'enemy_value_destroyed': 0.0,
            'ally_value_lost': 0.0,
            
            # Action tracking
            'valid_actions': 0,
            'invalid_actions': 0,
            'wait_actions': 0,
            'total_actions': 0,
            
            # Phase tracking
            'phases_completed': 0,
            'total_phases': 6
        }
        # Les observations sont remises a zero PAR ENVIRONNEMENT au moment de leur publication
        # (voir plus haut) : les reinitialiser ici viderait aussi les 47 autres, en plein
        # milieu de leur episode.

    def _calculate_immediate_vs_future_ratio(self, info):
        """Calculate ratio of immediate vs future-oriented actions"""
        # Analyze action patterns to detect myopic vs strategic behavior
        immediate_actions = 0  # Shooting, direct attacks
        future_actions = 0     # Movement, positioning
        
        if hasattr(self.training_env, 'envs') and len(cast(Any, self.training_env).envs) > 0:
            env = cast(Any, self.training_env).envs[0]
            if hasattr(env, 'unwrapped') and hasattr(env.unwrapped, 'game_state'):
                gs = env.unwrapped.game_state
                action_logs = gs['action_logs']  # engine always sets it
                for log in action_logs:
                    action_type = log['type']  # engine always sets "type" when appending to action_logs
                    if action_type in ['shoot', 'combat']:
                        immediate_actions += 1
                    elif action_type in ['move', 'wait']:
                        future_actions += 1
        
        total_actions = immediate_actions + future_actions
        return immediate_actions / max(1, total_actions)
    
    def _estimate_planning_horizon(self, gamma):
        """Estimate effective planning horizon from discount factor"""
        # Planning horizon = how many turns ahead agent effectively considers
        # Formula: horizon ≈ 1 / (1 - gamma)
        if gamma >= 0.99:
            return float('inf')  # Very long-term planning
        else:
            return 1.0 / (1.0 - gamma)


class BotEvaluationCallback(BaseCallback):
    """Callback to test agent against evaluation bots with best model saving"""

    def __init__(self, eval_freq: int = 5000, n_eval_episodes: int = 20,
                 best_model_save_path: Optional[str] = None, metrics_tracker: Any = None,
                 use_episode_freq: bool = False, verbose: int = 1,
                 training_config_name: Optional[str] = None, rewards_config_name: Optional[str] = None,
                 save_best_robust: bool = False, robust_window: int = 3,
                 save_best_robust_seed: bool = False,
                 robust_seed_value: Optional[int] = None,
                 robust_drawdown_penalty: float = 0.5,
                 robust_penalty_bot: float = 0.0,
                 robust_penalty_hard: float = 0.0,
                 model_gating_enabled: bool = False,
                 model_gating_min_combined: Optional[float] = None,
                 model_gating_min_worst_bot: Optional[float] = None,
                 model_gating_min_worst_scenario_combined: Optional[float] = None,
                 model_gating_min_vs_control: Optional[float] = None,
                 gate_display_state: Optional[Dict[str, Any]] = None,
                 eval_deterministic: bool = True,
                 final_summary_target_episodes: Optional[int] = None,
                 initial_episode_marker: int = 0,
                 show_eval_progress: bool = False,
                 phase_progress_total_episodes: Optional[int] = None,
                 phase_progress_episode_offset: int = 0,
                 scenario_pool: str = "training",
                 async_eval_enabled: bool = True,
                 early_stopping_patience: int = 0,
                 save_best_min_episodes: int = 0):
        super().__init__(verbose)
        if not training_config_name or not rewards_config_name:
            raise ValueError("BotEvaluationCallback requires training_config_name and rewards_config_name")
        if robust_window <= 0:
            raise ValueError(f"robust_window must be > 0 (got {robust_window})")
        if robust_drawdown_penalty < 0.0:
            raise ValueError(
                f"robust_drawdown_penalty must be >= 0.0 (got {robust_drawdown_penalty})"
            )
        if not isinstance(eval_deterministic, bool):
            raise ValueError(
                f"eval_deterministic must be boolean (got {type(eval_deterministic).__name__})"
            )
        self.training_config_name = training_config_name
        self.rewards_config_name = rewards_config_name
        self.eval_freq = eval_freq
        self.n_eval_episodes = n_eval_episodes
        self.best_model_save_path = best_model_save_path
        self.metrics_tracker = metrics_tracker
        self.use_episode_freq = use_episode_freq
        if not isinstance(self.eval_freq, int) or isinstance(self.eval_freq, bool) or self.eval_freq <= 0:
            raise ValueError(
                f"BotEvaluationCallback.eval_freq must be a positive integer (got {self.eval_freq!r})"
            )
        if (
            not isinstance(self.n_eval_episodes, int)
            or isinstance(self.n_eval_episodes, bool)
            or self.n_eval_episodes <= 0
        ):
            raise ValueError(
                f"BotEvaluationCallback.n_eval_episodes must be a positive integer "
                f"(got {self.n_eval_episodes!r})"
            )
        if not isinstance(self.use_episode_freq, bool):
            raise ValueError(
                f"BotEvaluationCallback.use_episode_freq must be boolean "
                f"(got {type(self.use_episode_freq).__name__})"
            )
        if initial_episode_marker < 0:
            raise ValueError(
                f"initial_episode_marker must be >= 0 (got {initial_episode_marker})"
            )
        if not isinstance(show_eval_progress, bool):
            raise ValueError(
                f"show_eval_progress must be boolean (got {type(show_eval_progress).__name__})"
            )
        if phase_progress_total_episodes is not None and phase_progress_total_episodes <= 0:
            raise ValueError(
                f"phase_progress_total_episodes must be > 0 (got {phase_progress_total_episodes})"
            )
        if phase_progress_episode_offset < 0:
            raise ValueError(
                f"phase_progress_episode_offset must be >= 0 (got {phase_progress_episode_offset})"
            )
        self.last_eval_episode = int(initial_episode_marker)
        self.last_eval_marker: Optional[int] = None
        if not isinstance(async_eval_enabled, bool):
            raise ValueError(
                f"async_eval_enabled must be boolean (got {type(async_eval_enabled).__name__})"
            )
        self.async_eval_enabled = async_eval_enabled
        self.show_eval_progress = show_eval_progress
        self.phase_progress_total_episodes = phase_progress_total_episodes
        self.phase_progress_episode_offset = int(phase_progress_episode_offset)
        self.scenario_pool = scenario_pool
        self.early_stopping_patience = int(early_stopping_patience)
        self.save_best_min_episodes = int(save_best_min_episodes)
        # Signal d'early stopping : le `combined` de SELECTION (holdout exclu). Il remplace
        # l'ancienne moyenne « palier 2 », dont deux des trois bots ont ete supprimes.
        self.best_early_stop_score = -float('inf')
        self.evals_without_improvement = 0
        self.should_stop_early = False
        self.eval_count = int(initial_episode_marker // eval_freq) if use_episode_freq and eval_freq > 0 else 0
        self.best_combined_win_rate = 0.0
        self.save_best_robust = save_best_robust
        if not isinstance(save_best_robust_seed, bool):
            raise ValueError(
                f"save_best_robust_seed must be boolean (got {type(save_best_robust_seed).__name__})"
            )
        self.save_best_robust_seed = save_best_robust_seed
        if self.save_best_robust_seed:
            if robust_seed_value is None:
                raise ValueError(
                    "robust_seed_value is required when save_best_robust_seed=true"
                )
            if not isinstance(robust_seed_value, int) or isinstance(robust_seed_value, bool):
                raise ValueError(
                    "robust_seed_value must be an integer when save_best_robust_seed=true "
                    f"(got {type(robust_seed_value).__name__})"
                )
            self.robust_seed_value = int(robust_seed_value)
        else:
            self.robust_seed_value = None
        self.robust_window = robust_window
        self.robust_drawdown_penalty = robust_drawdown_penalty
        self.robust_penalty_bot = robust_penalty_bot
        self.robust_penalty_hard = robust_penalty_hard
        if self.robust_penalty_bot < 0.0:
            raise ValueError(
                f"robust_penalty_bot must be >= 0.0 (got {self.robust_penalty_bot})"
            )
        if self.robust_penalty_hard < 0.0:
            raise ValueError(
                f"robust_penalty_hard must be >= 0.0 (got {self.robust_penalty_hard})"
            )
        self._validate_hard_penalty_is_measurable()
        if not isinstance(model_gating_enabled, bool):
            raise ValueError(
                f"model_gating_enabled must be boolean (got {type(model_gating_enabled).__name__})"
            )
        self.model_gating_enabled = model_gating_enabled
        self.model_gating_min_combined = model_gating_min_combined
        self.model_gating_min_worst_bot = model_gating_min_worst_bot
        self.model_gating_min_worst_scenario_combined = model_gating_min_worst_scenario_combined
        # Plancher sur le SEUL adversaire qui joue la condition de victoire (les VP d'objectifs
        # decident la partie ; les kills ne tranchent qu'a egalite). Il s'AJOUTE a `combined` et
        # `worst_bot` : « control decide » ne doit pas vouloir dire « on ne regarde plus que
        # control », un modele effondre contre les trois autres resterait alors selectionnable.
        self.model_gating_min_vs_control = model_gating_min_vs_control
        # Valide TOUJOURS, pas seulement gating arme : ce plancher s'applique aussi quand le
        # gating complet est desarme (cf. `_evaluate_model_gate`). `train.py` le resout donc
        # inconditionnellement, et le lit DIRECTEMENT dans le profil de l'agent : il n'y a
        # justement PAS de repli sur `_training_common.json` (train.py, resolution de
        # `model_gating_min_vs_control`), un seuil qui decide si un modele est sauve ou jete
        # devant etre un choix explicite du profil.
        if self.model_gating_min_vs_control is None:
            raise ValueError("model_gating_min_vs_control is required (0.0 pour le desarmer)")
        if not 0.0 <= float(self.model_gating_min_vs_control) <= 1.0:
            raise ValueError(
                f"model_gating_min_vs_control must be between 0.0 and 1.0 "
                f"(got {self.model_gating_min_vs_control})"
            )
        if self.model_gating_enabled:
            for metric_name, metric_value in (
                ("model_gating_min_combined", self.model_gating_min_combined),
                ("model_gating_min_worst_bot", self.model_gating_min_worst_bot),
                ("model_gating_min_worst_scenario_combined", self.model_gating_min_worst_scenario_combined),
            ):
                if metric_value is None:
                    raise ValueError(f"{metric_name} is required when model_gating_enabled=true")
                if metric_value < 0.0 or metric_value > 1.0:
                    raise ValueError(
                        f"{metric_name} must be between 0.0 and 1.0 (got {metric_value})"
                    )
        self.gating_pass_count = 0
        self.gating_fail_count = 0
        self.gating_skipped_unreliable_count = 0
        self.last_gate_pass: Optional[bool] = None
        self.gating_history: List[Dict[str, Any]] = []
        self.best_gating_criteria_mean: Optional[float] = None
        self.thresholds_ever_passed = False
        self.gate_display_state = gate_display_state
        if self.gate_display_state is not None:
            self.gate_display_state["label"] = "Gate 🧱"
            self.gate_display_state["learning_status_circle"] = "⚪"
            self.gate_display_state["learning_status_streak_count"] = 0
            self.gate_display_state["learning_status_streak_circle"] = "⚪"
            self.gate_display_state["best_robust_score"] = -float("inf")
            self.gate_display_state["robust_trend_symbol"] = "→"
        self.eval_deterministic = eval_deterministic
        self.combined_history = deque(maxlen=robust_window)
        self.best_robust_score = -float("inf")
        self.best_robust_combined = -float("inf")
        self.best_robust_eval_marker: Optional[int] = None
        self.best_robust_model_path: Optional[str] = None
        self.best_robust_worst_bot_name: Optional[str] = None
        self.best_robust_worst_bot_score: Optional[float] = None
        self.best_robust_worst_scenario_name: Optional[str] = None
        self.best_robust_worst_scenario_combined: Optional[float] = None
        self.best_robust_worst_holdout_regular_name: Optional[str] = None
        self.best_robust_worst_holdout_regular_combined: Optional[float] = None
        self.best_robust_worst_holdout_hard_name: Optional[str] = None
        self.best_robust_worst_holdout_hard_combined: Optional[float] = None
        self.final_summary_target_episodes = final_summary_target_episodes
        self.last_eval_results: Optional[Dict[str, Any]] = None
        self._async_eval_executor: Optional[ThreadPoolExecutor] = (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="bot-eval")
            if self.async_eval_enabled
            else None
        )
        self._pending_eval_future: Optional[Future] = None
        self._pending_eval_marker: Optional[int] = None
        self._pending_eval_snapshot_path: Optional[str] = None
        self.async_eval_skipped_count = 0
        self.curriculum_phase_progress_bar_length = _require_progress_bar_width(
            "curriculum_phase_width"
        )

        # Un dictionnaire self.bots (random / greedy / defensive, instancies avec 15% d'actions
        # aleatoires) etait construit ici. Personne ne le relisait : l'evaluation instancie ses
        # propres adversaires dans ai/bot_evaluation.evaluate_against_bots, appele par
        # _evaluate_against_bots. Trois casts servaient a contourner le fait que les classes
        # etaient declarees Optional par l'import protege ci-dessus, lui aussi supprime.

    def _update_learning_status_display(self, circle: str) -> None:
        """Update consecutive status streak shown in progress bar."""
        if self.gate_display_state is None:
            return
        previous_circle = self.gate_display_state.get("learning_status_streak_circle")
        previous_count = self.gate_display_state.get("learning_status_streak_count")
        count = previous_count if isinstance(previous_count, int) and previous_count > 0 else 0
        if previous_circle == circle:
            count += 1
        else:
            count = 1
        self.gate_display_state["learning_status_circle"] = circle
        self.gate_display_state["learning_status_streak_circle"] = circle
        self.gate_display_state["learning_status_streak_count"] = count

    def _compute_robust_trend_symbol(self, valid_window_size: int = 5) -> str:
        """Compute robust trend symbol from last valid gating evaluations."""
        valid_entries: List[Dict[str, Any]] = []
        for entry in reversed(self.gating_history):
            status = entry.get("status")
            criteria_mean = entry.get("criteria_mean")
            if status in {"PASS", "FAIL"} and isinstance(criteria_mean, (float, int)):
                valid_entries.append(entry)
            if len(valid_entries) >= valid_window_size:
                break
        if len(valid_entries) < 2:
            return "→"
        oldest = float(valid_entries[-1]["criteria_mean"])
        newest = float(valid_entries[0]["criteria_mean"])
        delta = newest - oldest
        if delta >= 0.02:
            return "↗↗"
        if delta >= 0.008:
            return "↗"
        if delta <= -0.02:
            return "↘↘"
        if delta <= -0.008:
            return "↘"
        return "→"

    def _control_floor_pass(self, results: Dict[str, Any]) -> bool:
        """Le score contre `ControlBot` atteint-il le plancher ? (0.0 = plancher desarme)

        `ControlBot` est le seul adversaire du panel dont la doctrine est de prendre et tenir
        les objectifs, or ce sont eux qui decident la partie (`determine_winner_with_method` :
        les kills ne tranchent qu'a egalite). Mesure fondatrice : sur deux runs successifs le
        `combined` a MONTE (0.62 -> 0.65) pendant que `vs_control` BAISSAIT (0.33 -> 0.27) —
        une moyenne ponderee peut donc progresser en perdant la competence decisive.

        C'est un bot PONDERE, jamais le holdout : si un plancher est arme, l'absence de son
        score est une config d'evaluation incoherente, pas un cas a contourner par un defaut.
        """
        floor = float(
            require_present(self.model_gating_min_vs_control, "model_gating_min_vs_control")
        )
        if floor <= 0.0:
            return True
        return float(require_key(results, "control")) >= floor

    def _evaluate_model_gate(self, results: Dict[str, Any], eval_marker: int) -> bool:
        """Evaluate model gating thresholds and store explicit PASS/FAIL history."""
        control_floor_pass = self._control_floor_pass(results)
        if not self.model_gating_enabled:
            # ⚠️ Le plancher `vs_control` s'applique MEME gating desarme. Le conditionner a
            # `model_gating_enabled` l'aurait rendu inerte : les profils portent `false`, donc
            # cette methode rendait True sans rien regarder et les DEUX chemins de sauvegarde
            # (best_combined et best_robust, tous deux gardes par `gate_pass`) auraient accepte
            # un modele a 0 % contre ControlBot — exactement ce que ce plancher existe pour
            # empecher. Un seuil a 0.0 le neutralise explicitement, c'est le seul desarmement.
            self.last_gate_pass = control_floor_pass
            return control_floor_pass

        combined_score = float(require_key(results, "combined"))
        # V11 §10.5 : le holdout ne pilote pas le gating.
        bot_score_keys = [k for k in results if k in SELECTION_BOT_NAMES]
        if not bot_score_keys:
            raise ValueError("No bot scores found in results")
        worst_bot_score = min(float(results[k]) for k in bot_score_keys)

        scenario_scores = require_key(results, "scenario_scores")
        if not isinstance(scenario_scores, dict) or not scenario_scores:
            raise ValueError("scenario_scores must be a non-empty dict for model gating")
        worst_scenario_combined = min(
            float(require_key(values, "combined"))
            for values in scenario_scores.values()
        )

        checks = [
            (
                "combined",
                combined_score,
                float(require_present(self.model_gating_min_combined, "model_gating_min_combined")),
            ),
            (
                "worst_bot",
                worst_bot_score,
                float(require_present(self.model_gating_min_worst_bot, "model_gating_min_worst_bot")),
            ),
            (
                "worst_scenario_combined",
                worst_scenario_combined,
                float(require_present(self.model_gating_min_worst_scenario_combined, "model_gating_min_worst_scenario_combined")),
            ),
            (
                "vs_control",
                # ControlBot est un adversaire PONDERE, jamais le holdout : son score est
                # toujours present quand le gate tourne. Son absence est une config d'eval
                # incoherente avec le gate, pas un cas a contourner par un defaut.
                float(require_key(results, "control")),
                float(require_present(self.model_gating_min_vs_control, "model_gating_min_vs_control")),
            ),
        ]
        gate_pass = all(actual >= threshold for _, actual, threshold in checks)
        criteria_mean = float(np.mean([combined_score, worst_bot_score, worst_scenario_combined]))
        has_improved_mean = False
        if self.best_gating_criteria_mean is None or criteria_mean > self.best_gating_criteria_mean:
            has_improved_mean = True
            self.best_gating_criteria_mean = criteria_mean
        self.last_gate_pass = gate_pass
        if gate_pass:
            self.gating_pass_count += 1
            self.thresholds_ever_passed = True
        else:
            self.gating_fail_count += 1

        marker_name = "episodes" if self.use_episode_freq else "timesteps"
        check_rows: List[Dict[str, Any]] = []
        for label, actual, threshold in checks:
            check_rows.append(
                {
                    "label": label,
                    "actual": float(actual),
                    "threshold": float(threshold),
                    "status": "PASS" if actual >= threshold else "FAIL",
                }
            )
        self.gating_history.append(
            {
                "marker_name": marker_name,
                "marker_value": int(eval_marker),
                "status": "PASS" if gate_pass else "FAIL",
                "criteria_mean": criteria_mean,
                "has_improved_mean": has_improved_mean,
                "thresholds_ever_passed": self.thresholds_ever_passed,
                "checks": check_rows,
            }
        )
        if self.gate_display_state is not None:
            self.gate_display_state["robust_trend_symbol"] = self._compute_robust_trend_symbol(
                valid_window_size=5
            )
        if self.gate_display_state is not None:
            if self.thresholds_ever_passed:
                if gate_pass or has_improved_mean:
                    self.gate_display_state["label"] = "Gate 🏁"
                    self._update_learning_status_display("🟢")
                else:
                    self.gate_display_state["label"] = "Gate 🏁"
                    self._update_learning_status_display("🔴")
            else:
                if has_improved_mean:
                    self.gate_display_state["label"] = "Gate 🧱"
                    self._update_learning_status_display("🟠")
                else:
                    self.gate_display_state["label"] = "Gate 🧱"
                    self._update_learning_status_display("🔴")

        return gate_pass

    def _mark_unreliable_eval_skip(self, eval_marker: int, failed_episodes: int) -> None:
        """Record a skipped gate decision when eval results are marked unreliable."""
        self.last_gate_pass = False
        self.gating_skipped_unreliable_count += 1

        marker_name = "episodes" if self.use_episode_freq else "timesteps"
        self.gating_history.append(
            {
                "marker_name": marker_name,
                "marker_value": int(eval_marker),
                "status": "SKIP_UNRELIABLE",
                "criteria_mean": None,
                "has_improved_mean": False,
                "thresholds_ever_passed": self.thresholds_ever_passed,
                "reason": f"total_failed_episodes={failed_episodes}",
                "checks": [],
            }
        )
        if self.gate_display_state is not None:
            self.gate_display_state["robust_trend_symbol"] = self._compute_robust_trend_symbol(
                valid_window_size=5
            )
        if self.gate_display_state is not None:
            self.gate_display_state["label"] = "Gate ⚠️"
            self._update_learning_status_display("🟠")

    @staticmethod
    def _ensure_zip_path(model_path: str) -> str:
        """Return a model path that always ends with .zip."""
        return model_path if model_path.endswith(".zip") else f"{model_path}.zip"

    def _save_model_with_vecnormalize(self, save_path: str) -> str:
        """Save model (.zip) and associated VecNormalize statistics.

        Returns:
            Absolute/relative path to the saved model zip.
        """
        model_zip_path = self._ensure_zip_path(save_path)
        policy = self.model.policy
        patched_forward = vars(policy).pop("forward", None)
        patched_train = vars(self.model).pop("train", None)
        try:
            self.model.save(model_zip_path)
        finally:
            if patched_forward is not None:
                policy.forward = patched_forward
            if patched_train is not None:
                setattr(self.model, "train", patched_train)
        if not os.path.exists(model_zip_path):
            raise FileNotFoundError(
                f"Model save did not produce expected .zip artifact: {model_zip_path}"
            )
        # Pas de try/except avaleur : ce snapshot alimente l'evaluation ASYNCHRONE — un echec
        # d'ecriture des stats avale ici ressortait comme 600/600 episodes en erreur 5 h 30
        # plus tard (V11 §0.35). Le retour False (env non enveloppe) = VecNormalize desactive.
        from ai.vec_normalize_utils import save_vec_normalize
        save_vec_normalize(self.model.get_env(), model_zip_path)
        return model_zip_path

    def _infer_agent_key(self) -> str:
        """Infer agent key from best-model save directory."""
        if not self.best_model_save_path:
            raise ValueError("best_model_save_path is required to infer agent key")
        agent_key = os.path.basename(os.path.normpath(self.best_model_save_path))
        if not agent_key:
            raise ValueError(f"Cannot infer agent key from path: {self.best_model_save_path}")
        return agent_key

    def _build_robust_model_zip_path(self, robust_score: float) -> str:
        """Build robust checkpoint path with explicit .zip extension."""
        agent_key = self._infer_agent_key()
        robust_score_str = f"{robust_score:.4f}"
        if self.save_best_robust_seed:
            if self.robust_seed_value is None:
                raise ValueError(
                    "robust_seed_value must be set when save_best_robust_seed=true"
                )
            filename = f"{agent_key}_{self.robust_seed_value}_robust_{robust_score_str}"
        else:
            filename = f"{agent_key}_robust_{robust_score_str}"
        model_base_path = os.path.join(
            require_present(self.best_model_save_path, "best_model_save_path"),
            filename
        )
        return self._ensure_zip_path(model_base_path)

    def _build_canonical_model_path(self) -> str:
        """Build canonical model path model_<agent>.zip."""
        agent_key = self._infer_agent_key()
        return os.path.join(require_present(self.best_model_save_path, "best_model_save_path"), f"model_{agent_key}.zip")

    def _get_canonical_robust_meta_path(self) -> str:
        """Path to sidecar file storing robust score of canonical model."""
        agent_key = self._infer_agent_key()
        return os.path.join(require_present(self.best_model_save_path, "best_model_save_path"), f"model_{agent_key}_robust_meta.json")

    def _read_canonical_robust_score(self) -> Optional[float]:
        """Return robust score of current canonical model, or None if unknown."""
        meta_path = self._get_canonical_robust_meta_path()
        canonical_path = self._build_canonical_model_path()
        if not os.path.exists(meta_path) or not os.path.exists(canonical_path):
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return float(require_key(data, "robust_score"))
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def _write_canonical_robust_meta(self, robust_score: float) -> None:
        """Persist robust score of canonical model after copy."""
        meta_path = self._get_canonical_robust_meta_path()
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"robust_score": robust_score}, f, indent=0)

    def _remove_model_artifacts(self, model_zip_path: str) -> None:
        """Remove model zip and associated VecNormalize stats if they exist."""
        if os.path.exists(model_zip_path):
            os.remove(model_zip_path)
        vec_path = get_vec_normalize_path(model_zip_path)
        if os.path.exists(vec_path):
            os.remove(vec_path)

    def _copy_model_artifacts(self, src_model_zip: str, dst_model_zip: str) -> None:
        """Copy model zip and VecNormalize stats from src to dst."""
        if not os.path.exists(src_model_zip):
            raise FileNotFoundError(f"Source model zip not found: {src_model_zip}")
        shutil.copy2(src_model_zip, dst_model_zip)

        src_vec_path = get_vec_normalize_path(src_model_zip)
        if os.path.exists(src_vec_path):
            dst_vec_path = get_vec_normalize_path(dst_model_zip)
            shutil.copy2(src_vec_path, dst_vec_path)

    def _cleanup_legacy_best_robust_artifacts(self) -> None:
        """Remove legacy best_robust_model artifacts from previous naming scheme."""
        if not self.best_model_save_path:
            raise ValueError("best_model_save_path is required for legacy cleanup")
        legacy_zip_path = os.path.join(self.best_model_save_path, "best_robust_model.zip")
        self._remove_model_artifacts(legacy_zip_path)

    @staticmethod
    def _scenario_metric_slug(scenario_name: str) -> str:
        """Convert scenario label to TensorBoard-safe metric suffix."""
        normalized = re.sub(r"[^a-zA-Z0-9]+", "_", scenario_name.strip()).strip("_").lower()
        if not normalized:
            raise ValueError(f"Invalid scenario name for metric slug: '{scenario_name}'")
        return normalized

    def _log_scenario_scores(self, results: Dict[str, Any]) -> None:
        """
        Log per-scenario bot evaluation scores to TensorBoard.

        Metrics namespace:
          bot_eval/scenario/<slug>/combined
          bot_eval/scenario/<slug>/worst_bot_score
          03_eval/<holdout_scenario_slug>/<BotName> (win-rate de CE bot sur CE scenario)

        Le namespace 03_eval/ portait jusqu'ici un scalaire par scenario holdout, valant son
        `worst_bot_score` : le nom du tag designait le scenario (`bot-01` = un fichier de
        matchup de rosters, pas un adversaire) et la valeur venait d'un bot different d'une
        evaluation a l'autre — impossible de savoir de qui parlait la courbe. Il porte
        desormais un win-rate par (scenario, bot), tag stable et adversaire nomme.
        """
        scenario_scores = results.get("scenario_scores")
        if scenario_scores is None:
            return
        if not isinstance(scenario_scores, dict):
            raise TypeError(
                f"scenario_scores must be dict (got {type(scenario_scores).__name__})"
            )
        if hasattr(self.model, "logger") and self.model.logger:
            for scenario_name, values in scenario_scores.items():
                if not isinstance(values, dict):
                    raise TypeError(
                        f"scenario_scores['{scenario_name}'] must be dict "
                        f"(got {type(values).__name__})"
                    )
                slug = self._scenario_metric_slug(str(scenario_name))
                self.model.logger.record(
                    f"bot_eval/scenario/{slug}/combined",
                    float(require_key(values, "combined"))
                )
                self.model.logger.record(
                    f"bot_eval/scenario/{slug}/worst_bot_score",
                    float(require_key(values, "worst_bot_score"))
                )
                scenario_name_str = str(scenario_name)
                if (
                    scenario_name_str.startswith("holdout_regular_")
                    or scenario_name_str.startswith("holdout_hard_")
                ):
                    per_bot = require_key(
                        require_key(results, "scenario_bot_stats"), scenario_name_str
                    )
                    for bot_key, stats in per_bot.items():
                        display_name = require_key(BOT_DISPLAY_NAMES, str(bot_key))
                        self.model.logger.record(
                            f"03_eval/{slug}/{display_name}",
                            float(require_key(stats, "win_rate"))
                        )
            scenario_split_scores = results.get("scenario_split_scores")
            if scenario_split_scores is not None:
                if not isinstance(scenario_split_scores, dict):
                    raise TypeError(
                        f"scenario_split_scores must be dict "
                        f"(got {type(scenario_split_scores).__name__})"
                    )
                for metric_key, score in scenario_split_scores.items():
                    self.model.logger.record(
                        f"bot_split/{metric_key}",
                        float(score)
                    )
            self.model.logger.dump(step=self.model.num_timesteps)

    @staticmethod
    def _extract_robust_worst_cases(results: Dict[str, Any]) -> Dict[str, Optional[Any]]:
        """Extract worst bot/scenario identifiers and scores from evaluation results."""
        # V11 §10.5 : le holdout ne pilote pas la selection du meilleur modele.
        bot_score_keys = [k for k in results if k in SELECTION_BOT_NAMES]
        if not bot_score_keys:
            raise ValueError("No bot scores found in results")
        bot_scores = {k: float(results[k]) for k in bot_score_keys}
        worst_bot_name, worst_bot_score = min(bot_scores.items(), key=lambda item: item[1])

        scenario_scores = require_key(results, "scenario_scores")
        if not isinstance(scenario_scores, dict) or not scenario_scores:
            raise ValueError("scenario_scores must be a non-empty dict for robust summary")

        worst_scenario_name: Optional[str] = None
        worst_scenario_combined: Optional[float] = None
        worst_holdout_regular_name: Optional[str] = None
        worst_holdout_regular_combined: Optional[float] = None
        worst_holdout_hard_name: Optional[str] = None
        worst_holdout_hard_combined: Optional[float] = None

        for scenario_name, values in scenario_scores.items():
            if not isinstance(values, dict):
                raise TypeError(
                    f"scenario_scores['{scenario_name}'] must be dict "
                    f"(got {type(values).__name__})"
                )
            combined = float(require_key(values, "combined"))

            if worst_scenario_combined is None or combined < worst_scenario_combined:
                worst_scenario_name = str(scenario_name)
                worst_scenario_combined = combined

            if str(scenario_name).startswith("holdout_regular_"):
                if (
                    worst_holdout_regular_combined is None
                    or combined < worst_holdout_regular_combined
                ):
                    worst_holdout_regular_name = str(scenario_name)
                    worst_holdout_regular_combined = combined

            if str(scenario_name).startswith("holdout_hard_"):
                if worst_holdout_hard_combined is None or combined < worst_holdout_hard_combined:
                    worst_holdout_hard_name = str(scenario_name)
                    worst_holdout_hard_combined = combined

        return {
            "worst_bot_name": worst_bot_name,
            "worst_bot_score": worst_bot_score,
            "worst_scenario_name": worst_scenario_name,
            "worst_scenario_combined": worst_scenario_combined,
            "worst_holdout_regular_name": worst_holdout_regular_name,
            "worst_holdout_regular_combined": worst_holdout_regular_combined,
            "worst_holdout_hard_name": worst_holdout_hard_name,
            "worst_holdout_hard_combined": worst_holdout_hard_combined,
        }

    def _validate_hard_penalty_is_measurable(self) -> None:
        """
        Refuse AU DEMARRAGE une penalite hard que l'evaluation ne pourra jamais mesurer.

        `robust_penalty_hard` s'applique a `holdout_hard_mean`, que
        `_compute_holdout_split_metrics` ne produit QUE si
        `callback_params.holdout_hard_scenarios` est declare et que le pool est "holdout".
        Le controle equivalent existe aussi au moment du calcul du score robuste, mais il
        n'y est atteint qu'apres `robust_window` evaluations — soit 10 000 episodes avec
        le profil x1 (bot_eval_freq=2000, robust_window=5). Une incoherence purement
        statique doit couter une seconde, pas plusieurs heures de run.
        """
        if self.robust_penalty_hard <= 0.0 or not self.save_best_robust:
            return
        if not self.training_config_name or not self.rewards_config_name:
            # Configs non nommees (tests, usages programmatiques) : rien a relire ici, le
            # controle au moment du calcul reste le filet.
            return
        training_cfg = get_config_loader().load_agent_training_config(
            self.rewards_config_name, self.training_config_name
        )
        callback_params = require_key(training_cfg, "callback_params")
        hard_scenarios = callback_params.get("holdout_hard_scenarios")
        if self.scenario_pool == "holdout" and hard_scenarios:
            return
        raise ValueError(
            f"robust_penalty_hard={self.robust_penalty_hard} is configured but the hard "
            f"holdout split cannot be measured: scenario_pool={self.scenario_pool!r} and "
            f"callback_params.holdout_hard_scenarios="
            f"{hard_scenarios!r}. The penalty would silently weigh 0 in the robust score. "
            f"Set robust_penalty_hard to 0.0, or build the hard split with "
            f"scripts/build_holdout_benchmark.py and declare it in holdout_hard_scenarios."
        )

    def _apply_eval_results(self, results: Dict[str, Any], eval_marker: int) -> None:
        """Apply evaluation results (gating, logging, checkpoints)."""
        self.last_eval_results = results
        self.last_eval_marker = int(eval_marker)

        total_failed_episodes = int(require_key(results, "total_failed_episodes"))
        total_timeout_episodes = int(require_key(results, "total_timeout_episodes"))
        total_error_episodes = int(require_key(results, "total_error_episodes"))
        eval_duration_seconds = float(require_key(results, "eval_duration_seconds"))

        # V11 §0.27 : un CRASH de worker reste un arret immediat — c'est un bug moteur, il ne
        # doit jamais etre absorbe.
        if total_error_episodes > 0:
            raise RuntimeError(
                "Bot evaluation crashed episodes detected: "
                f"marker={eval_marker}, error_episodes={total_error_episodes}, "
                f"timeout_episodes={total_timeout_episodes}, "
                f"duration_seconds={eval_duration_seconds:.1f}. "
                "Training stops immediately to enforce strict evaluation reliability."
            )

        # V11 §0.27 : un TIMEOUT n'est pas un bug, c'est de la LENTEUR (parties degenerees x cout
        # geodesique du move par-figurine). Tuer un run de 36 h pour ca est disproportionne. Mais
        # le score est calcule sur un denominateur tronque : il ne doit alimenter AUCUN signal.
        # On sort donc AVANT le gate, le log de metrique, la sauvegarde du best model,
        # l'early stopping et l'historique robuste. Le marker reste synchronise pour que le gate
        # de curriculum (train.py) ne se declare pas desynchronise ; c'est LUI qui refuse de
        # valider une phase sur `eval_reliable=False`.
        if total_timeout_episodes > 0:
            print(
                f"\n⚠️  Évaluation NON FIABLE au marker {eval_marker} : "
                f"{total_timeout_episodes} épisode(s) abandonné(s) sur TIMEOUT de task "
                f"(durée {eval_duration_seconds:.1f}s). Aucun crash moteur. "
                "Le training CONTINUE ; ce point de mesure est ignoré (pas de gate, pas de "
                "best model, pas de métrique). Réduire `bot_eval_intermediate` ou augmenter "
                "`bot_eval_task_timeout_seconds` si le cas se répète."
            )
            if self.metrics_tracker is not None:
                self.metrics_tracker.writer.add_scalar(
                    "00_critical/0_eval_timeout_episodes",
                    float(total_timeout_episodes),
                    int(eval_marker),
                )
            return
        # Le COUT de l'evaluation, sur le chemin normal. Il n'etait affiche que par les chemins
        # d'echec (crash, timeout) : sur un run sain, `eval_duration_seconds` etait calcule puis
        # jete, et la barre de progression de l'eval est desactivee en mode async
        # (`effective_show_eval_progress`, pour ne pas se disputer la ligne avec la barre
        # d'entrainement). Une evaluation pouvait donc peser des dizaines de minutes par marqueur
        # sans qu'aucune sortie ne le dise. Une seule ligne, emise a la CONSOMMATION du resultat
        # (thread principal), donc sans collision avec la barre.
        # Le marqueur seul identifie l'evaluation : `self.eval_count` n'ajouterait rien et
        # ferait dependre l'affichage d'un attribut que cette methode n'utilise pas autrement.
        episodes_played = int(require_key(results, "total_episodes_played"))
        rate = episodes_played / eval_duration_seconds if eval_duration_seconds > 0 else 0.0
        print(
            f"\n⏱️  Eval marker {eval_marker} : {episodes_played} épisodes "
            f"en {int(eval_duration_seconds // 60):02d}:{int(eval_duration_seconds % 60):02d} "
            f"({rate:.2f} ep/s)"
        )

        gate_pass = self._evaluate_model_gate(results, eval_marker)

        combined_win_rate = require_key(results, 'combined')

        if self.metrics_tracker:
            bot_results = {
                'combined': combined_win_rate
            }
            for bk in ALL_BOT_NAMES:
                if bk in results:
                    bot_results[bk] = results[bk]
            if 'holdout_hard_mean' in results:
                bot_results['holdout_hard_mean'] = float(results['holdout_hard_mean'])
            self.metrics_tracker.log_bot_evaluations(bot_results, step=int(eval_marker))
            self.metrics_tracker.log_faction_scores(
                require_key(results, 'faction_scores'),
                results.get('roster_gap'),
                step=int(eval_marker),
            )

        if hasattr(self.model, 'logger') and self.model.logger:
            self.model.logger.record('eval_bots/combined_win_rate', combined_win_rate)
        self._log_scenario_scores(results)

        if gate_pass and combined_win_rate > self.best_combined_win_rate and eval_marker >= self.save_best_min_episodes:
            self.best_combined_win_rate = combined_win_rate
            if self.best_model_save_path:
                save_path = f"{self.best_model_save_path}/best_model"
                self._save_model_with_vecnormalize(save_path)

        if self.early_stopping_patience > 0:
            if combined_win_rate > self.best_early_stop_score:
                self.best_early_stop_score = combined_win_rate
                self.evals_without_improvement = 0
            else:
                self.evals_without_improvement += 1
                if self.evals_without_improvement >= self.early_stopping_patience:
                    print(
                        f"\n🛑 Early stopping: bot_eval/combined n'a pas progressé depuis "
                        f"{self.evals_without_improvement} évaluations "
                        f"(best={self.best_early_stop_score:.4f}, current={combined_win_rate:.4f})"
                    )
                    self.should_stop_early = True

        self.combined_history.append(combined_win_rate)
        if self.save_best_robust and len(self.combined_history) >= self.robust_window:
            current_peak = max(self.combined_history)
            current_drawdown = current_peak - combined_win_rate
            moving_average = float(np.mean(self.combined_history))
            robust_base = moving_average - (self.robust_drawdown_penalty * current_drawdown)

            if self.model_gating_min_worst_bot is None:
                raise ValueError(
                    "robust scoring requires model_gating_min_worst_bot to be set "
                    "(used as tau_b threshold for penalty_bot)"
                )
            if self.model_gating_min_worst_scenario_combined is None:
                raise ValueError(
                    "robust scoring requires model_gating_min_worst_scenario_combined to be set "
                    "(used as tau_h threshold for penalty_hard)"
                )
            tau_b = float(self.model_gating_min_worst_bot)
            tau_h = float(self.model_gating_min_worst_scenario_combined)

            # V11 §10.5 : le holdout n'entre pas dans le score robuste.
            robust_bot_keys = [k for k in results if k in SELECTION_BOT_NAMES]
            worst_bot_score = min(float(results[k]) for k in robust_bot_keys)
            penalty_bot = self.robust_penalty_bot * max(0.0, tau_b - worst_bot_score) ** 2

            penalty_hard = 0.0
            if "holdout_hard_mean" in results:
                holdout_hard_mean = float(results["holdout_hard_mean"])
                penalty_hard = self.robust_penalty_hard * max(0.0, tau_h - holdout_hard_mean) ** 2
            elif self.robust_penalty_hard > 0.0:
                # FILET, pas la detection principale : le cas statique (penalite configuree
                # sans split hard declare) est refuse au demarrage par
                # _validate_hard_penalty_is_measurable. On n'arrive ici que si le split etait
                # DECLARE mais n'a produit aucun `holdout_hard_mean` — trop peu d'episodes pour
                # couvrir chaque scenario hard, cas que _compute_holdout_split_metrics tolere
                # DELIBEREMENT ("Keep evaluation running, but skip split aggregates").
                # On ne tue donc PAS le run : on saute ce point de mesure, exactement comme le
                # chemin timeout plus haut. Scorer quand meme reviendrait a comparer un score
                # a deux termes avec un score a trois selon les evaluations, et a sauvegarder
                # le best robust model sur cette incoherence.
                print(
                    f"\n⚠️  Score robuste ignoré au marker {eval_marker} : "
                    f"robust_penalty_hard={self.robust_penalty_hard} est configurée mais cette "
                    f"évaluation n'a produit aucun 'holdout_hard_mean' (couverture incomplète "
                    f"des scénarios hard). Le training CONTINUE ; ce point n'entre ni dans la "
                    f"courbe ni dans la sélection du best robust model. Augmenter "
                    f"`bot_eval_intermediate` si le cas se répète."
                )
                return
            robust_score = robust_base - penalty_bot - penalty_hard

            if self.metrics_tracker is not None:
                step = int(eval_marker)
                # Prefixe `o_` et non `0_` : TensorBoard trie les tags alphabetiquement, ce
                # score est un critere de DECISION (il pilote la sauvegarde du best robust
                # model, plus bas) et non un diagnostic a lire en tete de tableau de bord.
                self.metrics_tracker.writer.add_scalar(
                    "00_critical/o_robust_current_score", robust_score, step,
                )

            if gate_pass and robust_score > self.best_robust_score and eval_marker >= self.save_best_min_episodes:
                previous_robust_model_path = self.best_robust_model_path
                self.best_robust_score = robust_score
                self.best_robust_combined = combined_win_rate
                self.best_robust_eval_marker = eval_marker
                robust_worst_cases = self._extract_robust_worst_cases(results)
                self.best_robust_worst_bot_name = robust_worst_cases["worst_bot_name"]
                self.best_robust_worst_bot_score = robust_worst_cases["worst_bot_score"]
                self.best_robust_worst_scenario_name = robust_worst_cases["worst_scenario_name"]
                self.best_robust_worst_scenario_combined = robust_worst_cases["worst_scenario_combined"]
                self.best_robust_worst_holdout_regular_name = robust_worst_cases["worst_holdout_regular_name"]
                self.best_robust_worst_holdout_regular_combined = robust_worst_cases["worst_holdout_regular_combined"]
                self.best_robust_worst_holdout_hard_name = robust_worst_cases["worst_holdout_hard_name"]
                self.best_robust_worst_holdout_hard_combined = robust_worst_cases["worst_holdout_hard_combined"]
                if self.best_model_save_path:
                    robust_model_zip_path = self._build_robust_model_zip_path(robust_score)
                    saved_robust_zip_path = self._save_model_with_vecnormalize(robust_model_zip_path)
                    self.best_robust_model_path = saved_robust_zip_path
                    self._cleanup_legacy_best_robust_artifacts()

                    if (
                        previous_robust_model_path is not None
                        and previous_robust_model_path != self.best_robust_model_path
                    ):
                        self._remove_model_artifacts(previous_robust_model_path)

                    canonical_model_path = self._build_canonical_model_path()
                    current_canonical_score = self._read_canonical_robust_score()
                    if current_canonical_score is not None and current_canonical_score >= robust_score:
                        pass
                    else:
                        self._copy_model_artifacts(self.best_robust_model_path, canonical_model_path)
                        self._write_canonical_robust_meta(robust_score)
                if self.gate_display_state is not None:
                    self.gate_display_state["best_robust_score"] = float(self.best_robust_score)

    def _cleanup_pending_snapshot(self) -> None:
        """Delete pending async snapshot artifacts if they exist."""
        if self._pending_eval_snapshot_path:
            self._remove_model_artifacts(self._pending_eval_snapshot_path)
            self._pending_eval_snapshot_path = None

    def _consume_async_eval_if_ready(self, force_wait: bool = False) -> None:
        """Consume completed async evaluation result and apply it."""
        if self._pending_eval_future is None:
            return
        if not force_wait and not self._pending_eval_future.done():
            return
        if self._pending_eval_marker is None:
            raise RuntimeError("Pending async eval marker is missing")
        eval_marker = self._pending_eval_marker
        try:
            results = self._pending_eval_future.result()
        finally:
            self._pending_eval_future = None
            self._pending_eval_marker = None
            self._cleanup_pending_snapshot()
        self._apply_eval_results(results, eval_marker)

    def _submit_async_eval(self, eval_marker: int) -> None:
        """Submit async bot evaluation using a frozen model snapshot."""
        if self._async_eval_executor is None:
            self._async_eval_executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="bot-eval",
            )
        if self._pending_eval_future is not None:
            self.async_eval_skipped_count += 1
            return

        fd, snapshot_path = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        snapshot_zip_path = self._save_model_with_vecnormalize(snapshot_path)
        self._pending_eval_snapshot_path = snapshot_zip_path
        self._pending_eval_marker = int(eval_marker)
        self._pending_eval_future = self._async_eval_executor.submit(
            self._evaluate_against_bots,
            int(eval_marker),
            snapshot_zip_path,
        )

    def _on_step(self) -> bool:
        # Determine if we should evaluate based on mode
        should_evaluate = False
        eval_marker = self.num_timesteps
        if self.use_episode_freq:
            # Episode-based evaluation
            if self.metrics_tracker:
                current_episode = self.metrics_tracker.episode_count
                # Vectorized training can skip exact multiples (e.g., jump from 490 to 530),
                # so trigger when we have progressed by at least eval_freq episodes.
                if current_episode > 0 and (current_episode - self.last_eval_episode) >= self.eval_freq:
                    should_evaluate = True
                    eval_marker = int(current_episode)
        else:
            # Timestep-based evaluation (original behavior)
            if self.num_timesteps % self.eval_freq == 0:
                should_evaluate = True

        # In async mode, harvest completed evals without blocking training.
        if self.async_eval_enabled:
            self._consume_async_eval_if_ready(force_wait=False)

        if should_evaluate:
            self.eval_count += 1
            if self.use_episode_freq and self.metrics_tracker is not None:
                self.last_eval_episode = int(self.metrics_tracker.episode_count)
            if self.async_eval_enabled:
                self._submit_async_eval(eval_marker)
                # When early stopping is active, wait for this eval immediately
                # so the stopping decision is made before continuing training.
                if self.early_stopping_patience > 0:
                    self._consume_async_eval_if_ready(force_wait=True)
            else:
                results = self._evaluate_against_bots(eval_marker)
                self._apply_eval_results(results, eval_marker)

        if self.should_stop_early:
            return False
        return True

    def _on_training_end(self) -> None:
        """Print robust-checkpoint summary at end of training."""
        if self.async_eval_enabled:
            self._consume_async_eval_if_ready(force_wait=True)
            if self._async_eval_executor is not None:
                self._async_eval_executor.shutdown(wait=True)
                self._async_eval_executor = None
        if self.final_summary_target_episodes is not None:
            if self.metrics_tracker is None:
                return
            if self.metrics_tracker.episode_count < self.final_summary_target_episodes:
                return
        if self.model_gating_enabled:
            print("\n🧱 Model gating summary")
            print(f"   Evaluations gated: {len(self.gating_history)}")
            print(f"   PASS: {self.gating_pass_count} | FAIL: {self.gating_fail_count}")
            print(f"   SKIP_UNRELIABLE: {self.gating_skipped_unreliable_count}")
            if self.gating_history:
                marker_name = self.gating_history[0]["marker_name"]
                latest = self.gating_history[-1]
                print(
                    f"   Latest eval: {marker_name}={latest['marker_value']} -> {latest['status']}"
                )
                if latest["status"] == "SKIP_UNRELIABLE":
                    print(f"   - Reason: {latest['reason']}")
                else:
                    for row in latest["checks"]:
                        print(
                            f"   - {row['label']:<24} {row['actual']:.3f} >= {row['threshold']:.3f} [{row['status']}]"
                        )

                # Keep output compact: show only FAIL history entries (most actionable).
                fail_history = [entry for entry in self.gating_history if entry["status"] == "FAIL"]
                if fail_history:
                    print("   Failure history:")
                    for entry in fail_history:
                        failed_checks = [
                            f"{row['label']} ({row['actual']:.3f} < {row['threshold']:.3f})"
                            for row in entry["checks"]
                            if row["status"] == "FAIL"
                        ]
                        fail_details = ", ".join(failed_checks) if failed_checks else "unknown"
                        print(
                            f"   - {entry['marker_name']}={entry['marker_value']}: {fail_details}"
                        )

        if not self.save_best_robust:
            return
        if self.best_robust_score == -float("inf"):
            if self.model_gating_enabled:
                print("\n📌 Robust checkpoint summary")
                print("   No robust checkpoint selected (all gated evaluations failed or no eligible eval window).")
                print(
                    "   Gating stats: "
                    f"pass={self.gating_pass_count}, fail={self.gating_fail_count}, "
                    f"skip_unreliable={self.gating_skipped_unreliable_count}"
                )
            return
        print("\n📌 Robust checkpoint summary")
        marker_name = "episodes" if self.use_episode_freq else "timesteps"
        marker_value = self.best_robust_eval_marker if self.best_robust_eval_marker is not None else self.num_timesteps
        print(f"   Best robust score: {self.best_robust_score:.4f}")
        print(f"   Combined at robust best: {self.best_robust_combined:.4f}")
        if (
            self.best_robust_worst_bot_name is not None
            and self.best_robust_worst_bot_score is not None
        ):
            print(
                "   Worst bot score at robust best: "
                f"{self.best_robust_worst_bot_name} = {self.best_robust_worst_bot_score:.4f}"
            )
        if (
            self.best_robust_worst_scenario_name is not None
            and self.best_robust_worst_scenario_combined is not None
        ):
            print(
                "   Worst scenario combined at robust best: "
                f"{self.best_robust_worst_scenario_name} = {self.best_robust_worst_scenario_combined:.4f}"
            )
        if (
            self.best_robust_worst_holdout_regular_name is not None
            and self.best_robust_worst_holdout_regular_combined is not None
        ):
            print(
                "   Worst holdout regular combined at robust best: "
                f"{self.best_robust_worst_holdout_regular_name} = "
                f"{self.best_robust_worst_holdout_regular_combined:.4f}"
            )
        else:
            print("   Worst holdout regular combined at robust best: N/A")
        if (
            self.best_robust_worst_holdout_hard_name is not None
            and self.best_robust_worst_holdout_hard_combined is not None
        ):
            print(
                "   Worst holdout hard combined at robust best: "
                f"{self.best_robust_worst_holdout_hard_name} = "
                f"{self.best_robust_worst_holdout_hard_combined:.4f}"
            )
        else:
            print("   Worst holdout hard combined at robust best: N/A")
        print(f"   Selected at {marker_name}: {marker_value}")
        if self.best_robust_model_path:
            print(f"   Robust model path: {self.best_robust_model_path}")
        if self.model_gating_enabled:
            print(
                "   Gating stats: "
                f"pass={self.gating_pass_count}, fail={self.gating_fail_count}, "
                f"skip_unreliable={self.gating_skipped_unreliable_count}"
            )

    def _build_eval_progress_prefix(self, eval_marker: int) -> Optional[str]:
        """Build phase progress prefix for inline evaluation display."""
        if self.phase_progress_total_episodes is None:
            return None
        phase_episode_count = max(0, eval_marker - self.phase_progress_episode_offset)
        bounded_episodes = min(phase_episode_count, self.phase_progress_total_episodes)
        progress_ratio = bounded_episodes / self.phase_progress_total_episodes
        progress_pct = progress_ratio * 100.0
        bar_length = self.curriculum_phase_progress_bar_length
        filled = int(bar_length * progress_ratio)
        bar = '█' * filled + '░' * (bar_length - filled)
        return f"{progress_pct:3.0f}% {bar} {bounded_episodes}/{self.phase_progress_total_episodes}"

    def _evaluate_against_bots(
        self,
        eval_marker: int,
        model_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Evaluate agent against bots using standalone function"""
        import os
        import time
        eval_start = time.time()
        if os.environ.get("LOS_ENV_TRACE") == "1":
            import sys
            train_env = self.model.get_env() if hasattr(self.model, "get_env") else None
            n_envs = getattr(train_env, "num_envs", "?") if train_env is not None else "?"
            sys.stderr.write(
                f"[LOS_ENV_TRACE] training_callbacks _evaluate_against_bots eval_marker={eval_marker} "
                f"pid={os.getpid()} train_env.num_envs={n_envs}\n"
            )
            sys.stderr.flush()
        from ai.bot_evaluation import evaluate_against_bots
        # Avoid terminal output collisions in async mode: keep training bar only.
        effective_show_eval_progress = self.show_eval_progress and not self.async_eval_enabled
        eval_progress_prefix = None
        if effective_show_eval_progress and self.gate_display_state is not None:
            eval_progress_prefix = self.gate_display_state.get("training_prefix", "")
        results = evaluate_against_bots(
            model=self.model,
            training_config_name=self.training_config_name,
            rewards_config_name=self.rewards_config_name,
            n_episodes=self.n_eval_episodes,
            controlled_agent=self.rewards_config_name,
            show_progress=effective_show_eval_progress,
            deterministic=self.eval_deterministic,
            eval_progress_label=f"Eval {self.eval_count}" if effective_show_eval_progress else None,
            show_summary=not effective_show_eval_progress,
            eval_progress_prefix=eval_progress_prefix,
            line_length_state=self.gate_display_state,
            scenario_pool=self.scenario_pool,
            model_path=model_path,
        )
        if self.gate_display_state is not None:
            self.gate_display_state["total_eval_time"] = (
                self.gate_display_state.get("total_eval_time", 0.0)
                + (time.time() - eval_start)
            )
        return results
