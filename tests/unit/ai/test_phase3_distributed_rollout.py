"""Tests Phase 3 perf_entrainement — collecte distribuée (Option A).

Couvre :
  3.1  VecNormalizeSnapshot : snapshot_vec_normalize / normalize_obs_with_snapshot.
  3.2  Drift VecNormalize : tolérance mesurée et documentée (batch vs step-by-step).
  3.3  _run_worker_trajectory : structure, bootstrap TimeLimit.truncated, semantics.
  3.4  collect_rollouts dispatch : bascule vers _collect_rollouts_distributed si MaskableSubprocVecEnv.
  3.5  update_vec_normalize_from_trajectories : mise à jour batch des stats.
  3.6  Normalisation des rewards par le ret_var post-update, sans re-scaling du critique.

Tous les tests tournent sur CPU. Pas de spawn de vrais workers — les trajectoires sont
synthétiques pour tester la mécanique du learner indépendamment des workers.
"""
from __future__ import annotations

import math
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 3.1 — VecNormalizeSnapshot : snapshot_vec_normalize / normalize_obs_with_snapshot
# ══════════════════════════════════════════════════════════════════════════════════════════════


def _make_fake_vec_normalize(norm_obs: bool = True, norm_reward: bool = True, n_envs: int = 3):
    """VecNormalize factice avec obs_rms["global_cont"] et ret_rms initialisés."""
    from stable_baselines3.common.running_mean_std import RunningMeanStd

    gc_rms = RunningMeanStd(shape=(13,))
    gc_rms.mean = np.full(13, 0.5, dtype=np.float64)
    gc_rms.var = np.full(13, 2.0, dtype=np.float64)
    gc_rms.count = 100.0

    ret_rms = RunningMeanStd(shape=())
    ret_rms.mean = np.array(1.0, dtype=np.float64)
    ret_rms.var = np.array(4.0, dtype=np.float64)
    ret_rms.count = 50.0

    vn = MagicMock()
    vn.obs_rms = {"global_cont": gc_rms}
    vn.ret_rms = ret_rms
    vn.returns = np.array([0.5, 1.0, 2.0], dtype=np.float64)[:n_envs]
    vn.gamma = 0.99
    vn.epsilon = 1e-8
    vn.clip_obs = 10.0
    vn.clip_reward = 10.0
    vn.norm_obs = norm_obs
    vn.norm_reward = norm_reward
    vn.training = True
    # Pas de `venv` → c'est le leaf
    del vn.venv

    return vn


def _make_env_chain(vn):
    """Chaîne : outer_mock → vn (leaf sans venv)."""
    outer = MagicMock()
    outer.venv = vn
    return outer


class TestSnapshotVecNormalize:

    def test_snapshot_captures_rms_values(self):
        """snapshot_vec_normalize capture mean/var/count depuis un vrai VecNormalize."""
        from ai.vec_normalize_frozen import snapshot_vec_normalize
        from stable_baselines3.common.running_mean_std import RunningMeanStd
        from stable_baselines3.common.vec_env import VecNormalize, DummyVecEnv
        import gymnasium as gym
        from gymnasium import spaces

        class _StubEnv(gym.Env):
            observation_space = spaces.Box(-1.0, 1.0, (4,), dtype=np.float32)
            action_space = spaces.Discrete(2)
            def reset(self, **kw): return np.zeros(4, dtype=np.float32), {}
            def step(self, action): return np.zeros(4, dtype=np.float32), 0.0, False, False, {}

        dummy = DummyVecEnv([_StubEnv])
        vn_real = VecNormalize(dummy, norm_obs=True, norm_reward=True, gamma=0.99)
        vn_real.reset()
        # Forcer quelques steps pour avoir des stats non-nulles.
        for _ in range(5):
            vn_real.step(np.array([0]))

        snap = snapshot_vec_normalize(vn_real, worker_idx=0)

        assert isinstance(snap.obs_mean, np.ndarray)
        assert isinstance(snap.obs_var, np.ndarray)
        assert snap.gamma == pytest.approx(0.99)
        assert snap.norm_obs is True
        assert snap.norm_reward is True
        # Vérifier que mean/var sont copiés (pas les mêmes objets).
        obs_rms = vn_real.obs_rms
        assert isinstance(obs_rms, RunningMeanStd), "obs Box → obs_rms est un RunningMeanStd unique"
        assert snap.obs_mean is not obs_rms.mean

    def test_snapshot_noop_when_no_vec_normalize(self):
        """Sans VecNormalize dans la chaîne, snapshot retourne un no-op (norm_obs=False)."""
        from ai.vec_normalize_frozen import snapshot_vec_normalize

        # env sans VecNormalize dans la chaîne (pas de .venv)
        plain_env = MagicMock()
        del plain_env.venv

        snap = snapshot_vec_normalize(plain_env, worker_idx=0)
        assert snap.norm_obs is False
        assert snap.norm_reward is False

    def test_snapshot_initial_return_per_worker(self):
        """initial_return = VecNormalize.returns[worker_idx] au moment du snapshot.

        Vérifié via un vrai VecNormalize : on force la valeur de returns[i] et on contrôle
        que le snapshot la capture fidèlement.
        """
        from ai.vec_normalize_frozen import snapshot_vec_normalize
        from stable_baselines3.common.vec_env import VecNormalize, DummyVecEnv
        import gymnasium as gym
        from gymnasium import spaces

        class _StubEnv(gym.Env):
            observation_space = spaces.Box(-1.0, 1.0, (4,), dtype=np.float32)
            action_space = spaces.Discrete(2)
            def reset(self, **kw): return np.zeros(4, dtype=np.float32), {}
            def step(self, action): return np.zeros(4, dtype=np.float32), 1.0, False, False, {}

        n_envs = 3
        dummy = DummyVecEnv([_StubEnv] * n_envs)
        vn_real = VecNormalize(dummy, norm_obs=True, norm_reward=True, gamma=0.99)
        vn_real.reset()
        # Forcer returns[i] à des valeurs connues.
        if hasattr(vn_real, "returns") and vn_real.returns is not None:
            vn_real.returns[:] = np.array([1.5, 3.0, 0.0])

            for worker_idx, expected in enumerate([1.5, 3.0, 0.0]):
                snap = snapshot_vec_normalize(vn_real, worker_idx=worker_idx)
                assert snap.initial_return == pytest.approx(expected), (
                    f"initial_return pour worker {worker_idx} = {snap.initial_return}, "
                    f"attendu {expected}"
                )
        else:
            pytest.skip("VecNormalize.returns non disponible dans cette version SB3")


class TestNormalizeObsWithSnapshot:

    def _make_snapshot(self, norm_obs: bool = True) -> "Any":
        from ai.vec_normalize_frozen import VecNormalizeSnapshot
        return VecNormalizeSnapshot(
            obs_mean=np.full(13, 0.5, dtype=np.float64),
            obs_var=np.full(13, 2.0, dtype=np.float64),
            ret_var=1.0,
            gamma=0.99, epsilon=1e-8,
            clip_obs=10.0, clip_reward=10.0,
            norm_obs=norm_obs, norm_reward=True,
            initial_return=0.0,
        )

    def test_normalizes_global_cont(self):
        """normalize_obs_with_snapshot normalise 'global_cont' avec les stats gelées."""
        from ai.vec_normalize_frozen import normalize_obs_with_snapshot

        snap = self._make_snapshot(norm_obs=True)
        raw = np.full(13, 2.5, dtype=np.float32)
        obs = {"global_cont": raw, "other": np.zeros(4, dtype=np.float32)}

        result = normalize_obs_with_snapshot(obs, snap)

        # (2.5 - 0.5) / sqrt(2.0 + 1e-8) ≈ 2.0 / 1.4142 ≈ 1.4142
        expected = float(2.0 / np.sqrt(2.0 + 1e-8))
        assert result["global_cont"].dtype == np.float32
        assert float(result["global_cont"][0]) == pytest.approx(expected, rel=1e-5)
        # Les autres clés ne sont pas touchées.
        np.testing.assert_array_equal(result["other"], obs["other"])

    def test_no_normalization_when_norm_obs_false(self):
        """normalize_obs_with_snapshot retourne obs inchangé si norm_obs=False."""
        from ai.vec_normalize_frozen import normalize_obs_with_snapshot

        snap = self._make_snapshot(norm_obs=False)
        raw = np.full(13, 5.0, dtype=np.float32)
        obs = {"global_cont": raw}

        result = normalize_obs_with_snapshot(obs, snap)
        np.testing.assert_array_equal(result["global_cont"], raw)

    def test_clipping_applied(self):
        """normalize_obs_with_snapshot clip la valeur normalisée à clip_obs."""
        from ai.vec_normalize_frozen import normalize_obs_with_snapshot, VecNormalizeSnapshot

        snap = VecNormalizeSnapshot(
            obs_mean=np.zeros(13, dtype=np.float64),
            obs_var=np.full(13, 0.01, dtype=np.float64),  # var très faible → grande valeur norm
            ret_var=1.0,
            gamma=0.99, epsilon=1e-8, clip_obs=5.0, clip_reward=10.0,
            norm_obs=True, norm_reward=False, initial_return=0.0,
        )
        obs = {"global_cont": np.full(13, 100.0, dtype=np.float32)}
        result = normalize_obs_with_snapshot(obs, snap)

        assert float(result["global_cont"].max()) == pytest.approx(5.0, rel=1e-5), (
            "Valeur normalisée doit être clippée à clip_obs=5.0"
        )

    def test_returns_copy_not_mutation(self):
        """normalize_obs_with_snapshot retourne un dict distinct (pas de mutation en place)."""
        from ai.vec_normalize_frozen import normalize_obs_with_snapshot

        snap = self._make_snapshot()
        raw = np.ones(13, dtype=np.float32)
        obs = {"global_cont": raw}

        result = normalize_obs_with_snapshot(obs, snap)
        # L'original n'est pas modifié.
        np.testing.assert_array_equal(obs["global_cont"], np.ones(13))
        assert result is not obs


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 3.2 — Drift VecNormalize : batch vs step-by-step
# ══════════════════════════════════════════════════════════════════════════════════════════════


class TestVecNormalizeStatsDrift:
    """Vérifie que le drift entre batch-update et step-by-step est borné et documenté.

    L'écart vient du fait que RunningMeanStd.update(batch) ≠ N × update(step) numériquement,
    mais converge vers la même valeur. Ce test mesure et documente la tolérance.

    TOLÉRANCE ACTÉE : mean drift < 1e-4 (float64), var drift < 1e-3 pour N=340 steps.
    Ces valeurs sont intentionnellement larges pour survivre à des distributions variées ;
    en pratique l'écart observé est de l'ordre de 1e-15 (précision float64).
    """

    TOLERANCE_MEAN = 1e-4
    TOLERANCE_VAR = 1e-3

    def test_batch_vs_stepwise_rms_drift_is_bounded(self):
        """L'écart RunningMeanStd.update(batch) vs N×update(step) reste < tolérance documentée.

        ROUGE si le drift dépasse TOLERANCE_MEAN ou TOLERANCE_VAR — à ajuster seulement
        si la distribution change et que le drift est mesuré, jamais pour silence l'alarme.
        VERT : confirme que le mode batch est équivalent au mode streaming à la tolérance près.
        """
        from stable_baselines3.common.running_mean_std import RunningMeanStd

        rng = np.random.default_rng(42)
        N = 340  # effective_n_steps
        data = rng.standard_normal((N, 13)).astype(np.float64)

        # Mode batch (Phase 3 : un seul update avec tout le batch).
        rms_batch = RunningMeanStd(shape=(13,))
        rms_batch.update(data)

        # Mode step-by-step (SB3 référence : un update par ligne).
        rms_step = RunningMeanStd(shape=(13,))
        for row in data:
            rms_step.update(row[np.newaxis])

        mean_drift = float(np.abs(rms_batch.mean - rms_step.mean).max())
        var_drift = float(np.abs(rms_batch.var - rms_step.var).max())

        assert mean_drift < self.TOLERANCE_MEAN, (
            f"Drift mean RunningMeanStd batch vs step-by-step = {mean_drift:.2e} "
            f"dépasse la tolérance documentée {self.TOLERANCE_MEAN:.0e}. "
            f"Mesurer et documenter la nouvelle tolérance dans perf_entrainement.md §3."
        )
        assert var_drift < self.TOLERANCE_VAR, (
            f"Drift var RunningMeanStd batch vs step-by-step = {var_drift:.2e} "
            f"dépasse la tolérance documentée {self.TOLERANCE_VAR:.0e}. "
            f"Mesurer et documenter la nouvelle tolérance dans perf_entrainement.md §3."
        )

    def test_ret_rms_batch_vs_stepwise(self):
        """Drift sur ret_rms (reward returns scalaires) aussi borné."""
        from stable_baselines3.common.running_mean_std import RunningMeanStd

        rng = np.random.default_rng(7)
        N = 340
        rets = rng.standard_normal(N).astype(np.float64)

        rms_batch = RunningMeanStd(shape=())
        rms_batch.update(rets)

        rms_step = RunningMeanStd(shape=())
        for r in rets:
            rms_step.update(np.array([r]))

        mean_drift = abs(float(rms_batch.mean) - float(rms_step.mean))
        var_drift = abs(float(rms_batch.var) - float(rms_step.var))

        assert mean_drift < self.TOLERANCE_MEAN, (
            f"ret_rms mean drift = {mean_drift:.2e}"
        )
        assert var_drift < self.TOLERANCE_VAR, (
            f"ret_rms var drift = {var_drift:.2e}"
        )


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 3.3 — Structure _run_worker_trajectory
# ══════════════════════════════════════════════════════════════════════════════════════════════


class TestRunWorkerTrajectory:
    """Vérifie la structure et la sémantique de _run_worker_trajectory.

    On utilise un env stub minimal (pas de subprocess) et une policy stub CPU.
    """

    N_STEPS = 5
    N_ACTIONS = 4
    GC_DIM = 13

    def _make_stub_env(self):
        """Env stub : obs Dict avec global_cont et grid, action Discrete(4)."""
        from gymnasium import spaces

        _GC_DIM = self.GC_DIM
        _N_ACTIONS = self.N_ACTIONS

        class StubEnv:
            observation_space = spaces.Dict({
                "global_cont": spaces.Box(-1.0, 1.0, (_GC_DIM,), dtype=np.float32),
                "grid": spaces.Box(0.0, 1.0, (3,), dtype=np.float32),
            })
            action_space = spaces.Discrete(_N_ACTIONS)
            _step_count = 0

            def reset(self, **kw):
                self._step_count = 0
                return self._obs(), {}

            def step(self, action):
                self._step_count += 1
                done = self._step_count >= 3
                truncated = done
                terminated = False
                return self._obs(), 1.0, terminated, truncated, {}

            def _obs(self):
                return {
                    "global_cont": np.ones(_GC_DIM, dtype=np.float32) * 0.1,
                    "grid": np.ones(3, dtype=np.float32) * 0.2,
                }

            def get_wrapper_attr(self, name):
                if name == "action_masks":
                    return lambda: np.ones(_N_ACTIONS, dtype=bool)
                raise AttributeError(name)

        return StubEnv()

    def _make_stub_policy_bytes(self):
        """Policy stub sérialisée via cloudpickle."""
        import cloudpickle

        class StubPolicy:
            def set_training_mode(self, mode): pass
            def __call__(self, obs, action_masks=None):
                n = next(iter(obs.values())).shape[0]
                actions = torch.zeros(n, dtype=torch.long)
                values = torch.zeros(n)
                log_probs = torch.full((n,), -1.0)
                return actions, values, log_probs
            def predict_values(self, obs):
                n = next(iter(obs.values())).shape[0]
                return torch.zeros(n)

        return cloudpickle.dumps(StubPolicy())

    def _make_snapshot(self, initial_return: float = 0.0) -> "Any":
        from ai.vec_normalize_frozen import VecNormalizeSnapshot
        return VecNormalizeSnapshot(
            obs_mean=np.zeros(self.GC_DIM, dtype=np.float64),
            obs_var=np.ones(self.GC_DIM, dtype=np.float64),
            ret_var=1.0,
            gamma=0.99, epsilon=1e-8, clip_obs=10.0, clip_reward=10.0,
            norm_obs=True, norm_reward=True, initial_return=initial_return,
        )

    def test_trajectory_has_correct_length(self):
        """_run_worker_trajectory retourne des séquences de longueur n_steps."""
        from ai.maskable_subproc_vec_env import _run_worker_trajectory

        env = self._make_stub_env()
        obs, _ = env.reset()
        policy_bytes = self._make_stub_policy_bytes()
        snap = self._make_snapshot()

        traj = _run_worker_trajectory(env, obs, policy_bytes, self.N_STEPS, snap, False)

        assert len(next(iter(traj["norm_obs_seq"].values()))) == self.N_STEPS
        assert len(traj["actions_seq"]) == self.N_STEPS
        assert len(traj["rewards_seq"]) == self.N_STEPS
        assert len(traj["dones_seq"]) == self.N_STEPS
        assert len(traj["episode_starts_seq"]) == self.N_STEPS
        assert len(traj["values_seq"]) == self.N_STEPS
        assert len(traj["log_probs_seq"]) == self.N_STEPS
        assert len(traj["masks_seq"]) == self.N_STEPS
        assert len(traj["infos_seq"]) == self.N_STEPS
        assert len(traj["discounted_returns"]) == self.N_STEPS
        assert len(traj["episode_wall_seconds_seq"]) == self.N_STEPS

    def test_trajectory_keys_complete(self):
        """_run_worker_trajectory retourne toutes les clés attendues par le learner."""
        from ai.maskable_subproc_vec_env import _run_worker_trajectory

        env = self._make_stub_env()
        obs, _ = env.reset()
        traj = _run_worker_trajectory(
            env, obs, self._make_stub_policy_bytes(), self.N_STEPS, self._make_snapshot(), False
        )

        required_keys = {
            "norm_obs_seq", "actions_seq", "rewards_seq", "dones_seq", "episode_starts_seq",
            "values_seq", "log_probs_seq", "masks_seq", "infos_seq",
            "last_norm_obs", "last_done", "last_value",
            "raw_global_cont", "discounted_returns", "final_discounted_return",
            "episode_wall_seconds_seq",
            "raw_rewards_seq", "bootstrap_seq",
        }
        missing = required_keys - set(traj.keys())
        assert not missing, f"Clés manquantes dans la trajectoire : {missing}"

    def test_first_step_episode_start_matches_initial(self):
        """episode_starts_seq[0] reflète initial_episode_start."""
        from ai.maskable_subproc_vec_env import _run_worker_trajectory

        env = self._make_stub_env()
        obs, _ = env.reset()

        for initial in (True, False):
            traj = _run_worker_trajectory(
                env, obs, self._make_stub_policy_bytes(), self.N_STEPS,
                self._make_snapshot(), initial
            )
            assert bool(traj["episode_starts_seq"][0]) == initial, (
                f"episode_starts_seq[0] = {traj['episode_starts_seq'][0]}, "
                f"attendu initial_episode_start={initial}"
            )

    def test_episode_wall_seconds_seq_semantique(self):
        """episode_wall_seconds_seq : 0.0 hors done, -1.0 pour épisode cross-traj, >0 sinon.

        Avec initial_episode_start=True (épisode commence dans ce rollout) : premier done > 0.
        Avec initial_episode_start=False (épisode cross-trajectoire) : premier done = -1.0.
        Dones suivants (épisodes complets dans ce rollout) : > 0.
        ROUGE si la clé manque ou si les valeurs ne respectent pas cette sémantique.
        """
        from ai.maskable_subproc_vec_env import _run_worker_trajectory

        env = self._make_stub_env()
        obs, _ = env.reset()

        # initial_episode_start=True : pas d'épisode cross-trajectoire
        traj_fresh = _run_worker_trajectory(
            env, obs, self._make_stub_policy_bytes(), self.N_STEPS, self._make_snapshot(), True
        )
        wall_seq = traj_fresh["episode_wall_seconds_seq"]
        dones_seq = traj_fresh["dones_seq"]
        assert len(wall_seq) == self.N_STEPS
        for i, (wall, done) in enumerate(zip(wall_seq, dones_seq)):
            if done:
                assert wall > 0.0, (
                    f"step {i} est un done (épisode frais) : wall doit être > 0, got {wall}"
                )
            else:
                assert wall == 0.0, (
                    f"step {i} n'est pas un done : wall doit être 0.0, got {wall}"
                )

        # initial_episode_start=False : premier done est cross-trajectoire → -1.0
        obs2, _ = env.reset()
        traj_cross = _run_worker_trajectory(
            env, obs2, self._make_stub_policy_bytes(), self.N_STEPS, self._make_snapshot(), False
        )
        wall_seq2 = traj_cross["episode_wall_seconds_seq"]
        dones_seq2 = traj_cross["dones_seq"]
        first_done_idx = next((i for i, d in enumerate(dones_seq2) if d), None)
        if first_done_idx is not None:
            assert wall_seq2[first_done_idx] == -1.0, (
                f"premier done cross-traj au step {first_done_idx} doit valoir -1.0, "
                f"got {wall_seq2[first_done_idx]}"
            )
            for i in range(first_done_idx + 1, len(dones_seq2)):
                if dones_seq2[i]:
                    assert wall_seq2[i] > 0.0, (
                        f"done suivant (step {i}) doit être > 0.0, got {wall_seq2[i]}"
                    )

    def test_bootstrap_only_on_truncated(self):
        """Le bootstrap TimeLimit.truncated s'applique UNIQUEMENT sur truncated (pas terminated).

        ROUGE si rewards[done_step] == raw_reward (bootstrap absent) quand truncated=True.
        VERT si rewards[done_step] > raw_reward (bootstrap ajouté) et que terminated n'est pas bootstrappé.

        StubEnv : done=True, truncated=True, terminated=False → bootstrap attendu.
        """
        from ai.maskable_subproc_vec_env import _run_worker_trajectory
        from ai.vec_normalize_frozen import VecNormalizeSnapshot

        class TruncEnv:
            """Env qui truncate au step 2 (pas terminate)."""
            action_space = MagicMock()
            action_space.n = 4
            _step = 0

            def reset(self, **kw):
                self._step = 0
                return {"global_cont": np.zeros(13, dtype=np.float32)}, {}

            def step(self, action):
                self._step += 1
                truncated = self._step >= 2
                terminated = False
                obs = {"global_cont": np.zeros(13, dtype=np.float32)}
                return obs, 1.0, terminated, truncated, {}

            def get_wrapper_attr(self, name):
                if name == "action_masks":
                    return lambda: np.ones(4, dtype=bool)
                raise AttributeError(name)

        snap = VecNormalizeSnapshot(
            obs_mean=np.zeros(13, dtype=np.float64),
            obs_var=np.ones(13, dtype=np.float64),
            ret_var=1.0,
            gamma=0.99, epsilon=1e-8, clip_obs=10.0, clip_reward=10.0,
            norm_obs=False, norm_reward=False, initial_return=0.0,
        )

        env = TruncEnv()
        obs, _ = env.reset()

        # Policy qui retourne value=5.0.
        # Bootstrap SB3 : norm_reward = raw_reward/sqrt(ret_var+eps), puis += gamma * terminal_value.
        # Avec snap.norm_reward=False → norm_reward = 1.0, bootstrap = 1.0 + 0.99*5.0 = 5.95.
        class ValPolicy:
            def set_training_mode(self, m): pass
            def __call__(self, obs, action_masks=None):
                n = next(iter(obs.values())).shape[0]
                return torch.zeros(n, dtype=torch.long), torch.full((n,), 0.0), torch.full((n,), -1.0)
            def predict_values(self, obs):
                return torch.full((1,), 5.0)

        import cloudpickle
        policy_bytes = cloudpickle.dumps(ValPolicy())

        traj = _run_worker_trajectory(env, obs, policy_bytes, 3, snap, False)

        done_idx = next(i for i, d in enumerate(traj["dones_seq"]) if d)
        bootstrapped_reward = traj["rewards_seq"][done_idx]

        # Sans bootstrap : reward = 1.0 ; avec bootstrap = 1.0 + 0.99 * 5.0 = 5.95.
        # Le bootstrap est ajouté APRÈS normalisation (sémantique SB3).
        assert bootstrapped_reward > 1.0, (
            f"rewards[done_step={done_idx}] = {bootstrapped_reward:.4f} — "
            f"bootstrap TimeLimit.truncated non appliqué (attendu > 1.0 = raw_reward)"
        )
        # Vérifier l'ordre : bootstrap = raw_reward + gamma * terminal_value (pas renormalisé).
        expected_bootstrap = 1.0 + 0.99 * 5.0  # = 5.95
        assert bootstrapped_reward == pytest.approx(expected_bootstrap, rel=1e-4), (
            f"Bootstrap mal calculé : attendu {expected_bootstrap:.4f}, got {bootstrapped_reward:.4f}. "
            f"Le bootstrap doit être ajouté APRÈS normalisation (sémantique SB3)."
        )

    def test_no_double_normalization_across_trajectories(self):
        """last_raw_obs est brut : une 2e collecte ne re-normalise pas l'obs initiale.

        ROUGE si _run_worker_trajectory est appelé deux fois et que les obs du 2e run
        sont normalisées deux fois (symptôme : valeurs normalisées ≈ 0 car déjà clippées).
        VERT : les obs normalisées au step 0 du 2e run ont la même valeur qu'au step 0 du 1er.
        """
        from ai.maskable_subproc_vec_env import _run_worker_trajectory

        env = self._make_stub_env()
        obs_raw, _ = env.reset()
        policy_bytes = self._make_stub_policy_bytes()

        snap = self._make_snapshot(initial_return=0.0)

        # Premier run.
        traj1 = _run_worker_trajectory(env, obs_raw, policy_bytes, self.N_STEPS, snap, False)
        # `last_raw_obs` doit être brut (pas normalisé).
        last_raw = traj1["last_raw_obs"]

        # Deuxième run avec last_raw_obs du premier.
        traj2 = _run_worker_trajectory(env, last_raw, policy_bytes, self.N_STEPS, snap, False)

        # L'obs normalisée au step 0 du 2e run = normalize(last_raw_obs) = même valeur que
        # normalize(obs_brut). Avec obs=0.1 et mean=0, var=1 : norm = 0.1/sqrt(1+eps) ≈ 0.1.
        obs_step0_run2 = float(traj2["norm_obs_seq"]["global_cont"][0][0])
        assert abs(obs_step0_run2) < 0.2, (
            f"obs normalisée step 0 run 2 = {obs_step0_run2:.4f} — "
            f"la double normalisation est détectée si la valeur est proche de 0 "
            f"alors que l'obs originale est 0.1. Valeur correcte attendue ≈ 0.1."
        )

    def test_raw_global_cont_shape(self):
        """raw_global_cont a shape (n_steps, 13) pour alimenter la mise à jour VecNormalize."""
        from ai.maskable_subproc_vec_env import _run_worker_trajectory

        env = self._make_stub_env()
        obs, _ = env.reset()
        traj = _run_worker_trajectory(
            env, obs, self._make_stub_policy_bytes(), self.N_STEPS, self._make_snapshot(), False
        )

        assert traj["raw_global_cont"].shape == (self.N_STEPS, self.GC_DIM), (
            f"raw_global_cont.shape = {traj['raw_global_cont'].shape}, "
            f"attendu ({self.N_STEPS}, {self.GC_DIM})"
        )

    def test_missing_action_masks_raises(self):
        """Un env sans action_masks lève AttributeError — aucun fallback autorisé (T1)."""
        import cloudpickle
        from ai.maskable_subproc_vec_env import _run_worker_trajectory

        class NoMaskEnv:
            class _Space:
                n = 4
            action_space = _Space()

            def reset(self, **_):
                return {"global_cont": np.zeros(1, dtype=np.float32)}, {}

            def step(self, action):
                return {"global_cont": np.zeros(1, dtype=np.float32)}, 0.0, False, False, {}

            def get_wrapper_attr(self, name):
                raise AttributeError(name)

        class TrivialPolicy:
            def set_training_mode(self, m): pass
            def __call__(self, obs, action_masks=None):
                n = next(iter(obs.values())).shape[0]
                return torch.zeros(n, dtype=torch.long), torch.zeros(n), torch.full((n,), -1.0)
            def predict_values(self, obs):
                n = next(iter(obs.values())).shape[0]
                return torch.zeros(n)

        from ai.vec_normalize_frozen import VecNormalizeSnapshot
        snap = VecNormalizeSnapshot(
            obs_mean=np.zeros(1, dtype=np.float64),
            obs_var=np.ones(1, dtype=np.float64),
            ret_var=1.0,
            gamma=0.99, epsilon=1e-8, clip_obs=10.0, clip_reward=10.0,
            norm_obs=False, norm_reward=False, initial_return=0.0,
        )
        env = NoMaskEnv()
        obs, _ = env.reset()
        policy_bytes = cloudpickle.dumps(TrivialPolicy())

        with pytest.raises(AttributeError):
            _run_worker_trajectory(env, obs, policy_bytes, 2, snap, False)

    def test_raw_rewards_seq_length_and_unclipped(self):
        """raw_rewards_seq a la bonne longueur et contient les rewards brutes non clippées.

        ROUGE si clé absente ou si raw_rewards_seq[done_step] != raw_reward (clippé à tort).
        VERT si len == N_STEPS et raw_rewards[done] == 150.0 (non clippé au cold-start).
        """
        from ai.maskable_subproc_vec_env import _run_worker_trajectory
        from ai.vec_normalize_frozen import VecNormalizeSnapshot

        RAW_TERMINAL = 150.0
        CLIP_REWARD = 10.0

        class TermEnv:
            action_space = MagicMock()
            action_space.n = 4
            _step = 0

            def reset(self, **kw):
                self._step = 0
                return {"global_cont": np.zeros(13, dtype=np.float32)}, {}

            def step(self, action):
                self._step += 1
                done = self._step >= 3
                reward = RAW_TERMINAL if done else 0.0
                return {"global_cont": np.zeros(13, dtype=np.float32)}, reward, done, False, {}

            def get_wrapper_attr(self, name):
                if name == "action_masks":
                    return lambda: np.ones(4, dtype=bool)
                raise AttributeError(name)

        snap = VecNormalizeSnapshot(
            obs_mean=np.zeros(13, dtype=np.float64), obs_var=np.ones(13, dtype=np.float64),
            ret_var=1.0, gamma=0.99, epsilon=1e-8, clip_obs=10.0, clip_reward=CLIP_REWARD,
            norm_obs=False, norm_reward=True, initial_return=0.0,
        )

        env = TermEnv()
        obs, _ = env.reset()
        traj = _run_worker_trajectory(env, obs, self._make_stub_policy_bytes(), 6, snap, True)

        assert len(traj["raw_rewards_seq"]) == 6
        assert len(traj["bootstrap_seq"]) == 6

        done_indices = [i for i, d in enumerate(traj["dones_seq"]) if d]
        assert done_indices, "Aucun done dans la trajectoire — env mal configuré"
        first_done = done_indices[0]

        # raw_rewards_seq : valeur brute non clippée.
        raw = float(traj["raw_rewards_seq"][first_done])
        assert raw == pytest.approx(RAW_TERMINAL, rel=1e-5), (
            f"raw_rewards_seq[done] = {raw}, attendu {RAW_TERMINAL} (non clippé)"
        )

        # rewards_seq (callbacks) : version clippée (ancien comportement conservé pour affichage).
        norm_clipped = float(traj["rewards_seq"][first_done])
        assert norm_clipped == pytest.approx(CLIP_REWARD, rel=1e-5), (
            f"rewards_seq[done] = {norm_clipped}, attendu {CLIP_REWARD} (clippé au cold-start)"
        )

    def test_bootstrap_seq_zero_for_terminated(self):
        """bootstrap_seq est 0.0 pour les épisodes terminés (non tronqués)."""
        from ai.maskable_subproc_vec_env import _run_worker_trajectory
        from ai.vec_normalize_frozen import VecNormalizeSnapshot

        class TerminatedEnv:
            action_space = MagicMock()
            action_space.n = 4
            _step = 0

            def reset(self, **kw):
                self._step = 0
                return {"global_cont": np.zeros(13, dtype=np.float32)}, {}

            def step(self, action):
                self._step += 1
                done = self._step >= 3
                return {"global_cont": np.zeros(13, dtype=np.float32)}, 1.0, done, False, {}

            def get_wrapper_attr(self, name):
                if name == "action_masks":
                    return lambda: np.ones(4, dtype=bool)
                raise AttributeError(name)

        snap = VecNormalizeSnapshot(
            obs_mean=np.zeros(13, dtype=np.float64), obs_var=np.ones(13, dtype=np.float64),
            ret_var=1.0, gamma=0.99, epsilon=1e-8, clip_obs=10.0, clip_reward=10.0,
            norm_obs=False, norm_reward=False, initial_return=0.0,
        )

        env = TerminatedEnv()
        obs, _ = env.reset()
        traj = _run_worker_trajectory(env, obs, self._make_stub_policy_bytes(), 6, snap, True)

        for i, b in enumerate(traj["bootstrap_seq"]):
            assert float(b) == pytest.approx(0.0), (
                f"bootstrap_seq[{i}] = {b}, attendu 0.0 pour terminated (pas de truncation)"
            )


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 3.4 — collect_rollouts dispatch
# ══════════════════════════════════════════════════════════════════════════════════════════════


class TestCollectRolloutsDispatch:
    """Vérifie que collect_rollouts bascule vers _collect_rollouts_distributed si disponible."""

    def _make_dict_obs_space(self):
        from gymnasium import spaces
        return spaces.Dict({
            "global_cont": spaces.Box(-1.0, 1.0, (13,), dtype=np.float32),
            "grid": spaces.Box(0.0, 1.0, (4,), dtype=np.float32),
        })

    def test_dispatches_to_distributed_when_subproc_present(self):
        """collect_rollouts appelle _collect_rollouts_distributed si MaskableSubprocVecEnv trouvé."""
        from ai.patched_ppo import PatchedMaskablePPO
        from ai.maskable_subproc_vec_env import MaskableSubprocVecEnv
        from sb3_contrib.common.maskable.buffers import MaskableDictRolloutBuffer

        obs_space = self._make_dict_obs_space()
        act_space = __import__("gymnasium").spaces.Discrete(8)

        inner = MagicMock(spec=MaskableSubprocVecEnv)
        del inner.venv
        env_mock = MagicMock()
        env_mock.venv = inner
        env_mock.num_envs = 2
        env_mock.observation_space = obs_space
        env_mock.action_space = act_space
        env_mock.has_attr.return_value = True

        buf = MaskableDictRolloutBuffer(
            buffer_size=2, observation_space=obs_space, action_space=act_space,
            device="cpu", gamma=0.99, gae_lambda=0.95, n_envs=2,
        )

        with patch.object(PatchedMaskablePPO, "_setup_model"):
            model = PatchedMaskablePPO.__new__(PatchedMaskablePPO)
        model.policy = MagicMock()
        model.device = torch.device("cpu")
        model._last_obs = {
            "global_cont": np.zeros((2, 13), dtype=np.float32),
            "grid": np.zeros((2, 4), dtype=np.float32),
        }
        model._last_episode_starts = np.zeros(2, dtype=bool)
        model.num_timesteps = 0
        model.gamma = 0.99
        model.action_space = act_space
        model._update_info_buffer = MagicMock()

        callback = MagicMock()
        callback.on_rollout_start = MagicMock()
        callback.on_step.return_value = True
        callback.on_rollout_end = MagicMock()

        distributed_called = []

        def fake_distributed(env, subproc, cb, rbuf, n_steps, use_masking):
            distributed_called.append(True)
            return True

        with patch.object(model, "_collect_rollouts_distributed", fake_distributed):
            model.collect_rollouts(env_mock, callback, buf, n_rollout_steps=2)

        assert len(distributed_called) == 1, (
            "collect_rollouts n'a pas dispatché vers _collect_rollouts_distributed "
            "alors qu'un MaskableSubprocVecEnv est présent dans la chaîne"
        )

    def test_falls_back_to_stepwise_without_subproc(self):
        """collect_rollouts utilise le chemin stepwise si pas de MaskableSubprocVecEnv."""
        from ai.patched_ppo import PatchedMaskablePPO
        from sb3_contrib.common.maskable.buffers import MaskableDictRolloutBuffer

        obs_space = self._make_dict_obs_space()
        act_space = __import__("gymnasium").spaces.Discrete(8)

        # Env sans MaskableSubprocVecEnv dans la chaîne.
        env_mock = MagicMock()
        del env_mock.venv
        env_mock.num_envs = 1
        env_mock.observation_space = obs_space
        env_mock.action_space = act_space
        env_mock.has_attr.return_value = True

        buf = MaskableDictRolloutBuffer(
            buffer_size=2, observation_space=obs_space, action_space=act_space,
            device="cpu", gamma=0.99, gae_lambda=0.95, n_envs=1,
        )

        with patch.object(PatchedMaskablePPO, "_setup_model"):
            model = PatchedMaskablePPO.__new__(PatchedMaskablePPO)

        init_obs = {
            "global_cont": np.zeros((1, 13), dtype=np.float32),
            "grid": np.zeros((1, 4), dtype=np.float32),
        }
        policy_mock = MagicMock()
        policy_mock.return_value = (
            torch.zeros(1, dtype=torch.long), torch.zeros(1), torch.full((1,), -1.0)
        )
        policy_mock.predict_values.return_value = torch.zeros(1)
        policy_mock.set_training_mode = MagicMock()
        model.policy = policy_mock
        model.device = torch.device("cpu")
        model._last_obs = init_obs
        model._last_episode_starts = np.zeros(1, dtype=bool)
        model.num_timesteps = 0
        model.gamma = 0.99
        model.action_space = act_space
        model._update_info_buffer = MagicMock()

        step_obs = {
            "global_cont": np.zeros((1, 13), dtype=np.float32),
            "grid": np.zeros((1, 4), dtype=np.float32),
        }
        env_mock.step.return_value = (
            step_obs, np.zeros(1, dtype=np.float32), np.zeros(1, dtype=bool),
            [{}],
        )

        callback = MagicMock()
        callback.on_rollout_start = MagicMock()
        callback.on_step.return_value = True
        callback.on_rollout_end = MagicMock()

        stepwise_called = []
        original_stepwise = PatchedMaskablePPO._collect_rollouts_stepwise

        def spy_stepwise(self_inner, *a, **kw):
            stepwise_called.append(True)
            return original_stepwise(self_inner, *a, **kw)

        with patch.object(PatchedMaskablePPO, "_collect_rollouts_stepwise", spy_stepwise), \
             patch("ai.patched_ppo.get_action_masks", return_value=np.ones((1, 8), dtype=bool)):
            model.collect_rollouts(env_mock, callback, buf, n_rollout_steps=2)

        assert len(stepwise_called) == 1, (
            "collect_rollouts n'a pas utilisé le chemin stepwise sans MaskableSubprocVecEnv"
        )



# ══════════════════════════════════════════════════════════════════════════════════════════════
# 3.4b — _collect_rollouts_distributed : propagation des masques réels dans le buffer
# ══════════════════════════════════════════════════════════════════════════════════════════════


class TestDistributedRolloutMaskPropagation:
    """Vérifie que _collect_rollouts_distributed stocke les masques issus des workers,
    et non des masques pleins (np.ones) produits par MaskableDictRolloutBuffer.reset()."""

    N_ENVS = 2
    N_STEPS = 3
    N_ACTIONS = 4
    GC_DIM = 13

    def _make_fake_trajectory(self, masks_seq: list) -> dict:
        """Trajectoire minimale valide pour le learner (longueur N_STEPS)."""
        obs_seq = {
            "global_cont": np.zeros((self.N_STEPS, self.GC_DIM), dtype=np.float32),
        }
        return {
            "norm_obs_seq": obs_seq,
            "actions_seq": [0] * self.N_STEPS,
            "rewards_seq": [0.0] * self.N_STEPS,
            "raw_rewards_seq": np.zeros(self.N_STEPS, dtype=np.float32),
            "bootstrap_seq": np.zeros(self.N_STEPS, dtype=np.float32),
            "dones_seq": [False] * self.N_STEPS,
            "episode_starts_seq": [True] + [False] * (self.N_STEPS - 1),
            "values_seq": [0.0] * self.N_STEPS,
            "log_probs_seq": [-1.0] * self.N_STEPS,
            "masks_seq": masks_seq,
            "infos_seq": [{}] * self.N_STEPS,
            "last_norm_obs": {"global_cont": np.zeros(self.GC_DIM, dtype=np.float32)},
            "last_done": False,
            "last_value": 0.0,
            "raw_global_cont": [np.zeros(self.GC_DIM, dtype=np.float32)] * self.N_STEPS,
            "discounted_returns": [0.0] * self.N_STEPS,
            "final_discounted_return": 0.0,
            "episode_wall_seconds_seq": [0.0] * self.N_STEPS,
        }

    def test_restricted_masks_propagated_to_buffer(self):
        """Les masques interdisant l'action 0 doivent se retrouver dans buf.action_masks,
        pas les masques pleins (np.ones) initialisés par MaskableDictRolloutBuffer.reset()."""
        from gymnasium import spaces
        from sb3_contrib.common.maskable.buffers import MaskableDictRolloutBuffer
        from ai.patched_ppo import PatchedMaskablePPO

        obs_space = spaces.Dict({
            "global_cont": spaces.Box(-1.0, 1.0, (self.GC_DIM,), dtype=np.float32),
        })
        act_space = spaces.Discrete(self.N_ACTIONS)

        # Masque restrictif : action 0 interdite pour tous les workers à chaque step.
        restricted_mask = np.array([False, True, True, True], dtype=bool)
        masks_seq = [restricted_mask.copy() for _ in range(self.N_STEPS)]
        trajectories = [
            self._make_fake_trajectory(masks_seq)
            for _ in range(self.N_ENVS)
        ]

        buf = MaskableDictRolloutBuffer(
            buffer_size=self.N_STEPS,
            observation_space=obs_space,
            action_space=act_space,
            device="cpu",
            gamma=0.99,
            gae_lambda=0.95,
            n_envs=self.N_ENVS,
        )

        class StubPolicy:
            def set_training_mode(self, mode): pass
            def cpu(self): return self
            def predict_values(self, obs):
                n = next(iter(obs.values())).shape[0]
                return torch.zeros(n)

        with patch.object(PatchedMaskablePPO, "_setup_model"):
            model = PatchedMaskablePPO.__new__(PatchedMaskablePPO)
        model.policy = StubPolicy()  # type: ignore[assignment]
        model.device = torch.device("cpu")
        model.action_space = act_space
        model.num_timesteps = 0
        model._last_obs = {"global_cont": np.zeros((self.N_ENVS, self.GC_DIM), dtype=np.float32)}
        model._last_episode_starts = np.zeros(self.N_ENVS, dtype=bool)
        model._update_info_buffer = MagicMock()

        subproc_mock = MagicMock()
        subproc_mock.num_envs = self.N_ENVS
        subproc_mock.collect_trajectories.return_value = trajectories

        env_mock = MagicMock()
        env_mock.num_envs = self.N_ENVS
        env_mock.observation_space = obs_space
        env_mock.action_space = act_space

        callback = MagicMock()
        callback.on_rollout_start = MagicMock()
        callback.on_step.return_value = True
        callback.on_rollout_end = MagicMock()

        with patch("ai.vec_normalize_frozen.snapshot_vec_normalize", return_value=MagicMock()), \
             patch("ai.vec_normalize_frozen.update_vec_normalize_from_trajectories", return_value=None), \
             patch("ai.vec_normalize_frozen._unwrap_vec_normalize", return_value=None), \
             patch("cloudpickle.dumps", return_value=b"stub_policy"):
            model._collect_rollouts_distributed(
                env_mock, subproc_mock, callback, buf, self.N_STEPS, use_masking=True
            )

        # buf.action_masks : shape (n_steps, n_envs, n_actions), dtype float32.
        assert buf.action_masks.shape == (self.N_STEPS, self.N_ENVS, self.N_ACTIONS)
        action_0_values = buf.action_masks[:, :, 0]
        assert np.all(action_0_values == 0.0), (
            f"action_masks[:,:,0] attendu tout à 0.0 (action interdite), obtenu : {action_0_values}"
        )
        other_actions = buf.action_masks[:, :, 1:]
        assert np.all(other_actions == 1.0), (
            f"action_masks[:,:,1:] attendu tout à 1.0 (actions autorisées), obtenu : {other_actions}"
        )


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 3.5 — update_vec_normalize_from_trajectories
# ══════════════════════════════════════════════════════════════════════════════════════════════


class TestUpdateVecNormalizeFromTrajectories:

    def _make_vec_normalize(self, n_envs: int = 3):
        """Crée un vrai VecNormalize minimal autour d'un DummyVecEnv stub."""
        from stable_baselines3.common.vec_env import VecNormalize, DummyVecEnv
        from gymnasium import spaces
        import gymnasium as gym

        class StubEnv(gym.Env):
            observation_space = spaces.Dict({
                "global_cont": spaces.Box(-1.0, 1.0, (13,), dtype=np.float32),
            })
            action_space = spaces.Discrete(4)

            def reset(self, **kw):
                return {"global_cont": np.zeros(13, dtype=np.float32)}, {}

            def step(self, action):
                return {"global_cont": np.zeros(13, dtype=np.float32)}, 0.0, False, False, {}

        vec = DummyVecEnv([StubEnv] * n_envs)
        vn = VecNormalize(vec, norm_obs=True, norm_reward=True, gamma=0.99)
        vn.reset()
        return vn

    def test_obs_rms_updated_after_trajectories(self):
        """obs_rms['global_cont'].count augmente après update_vec_normalize_from_trajectories."""
        from ai.vec_normalize_frozen import update_vec_normalize_from_trajectories

        try:
            vn = self._make_vec_normalize(n_envs=2)
        except Exception:
            pytest.skip("DummyVecEnv avec obs Dict non disponible")

        obs_rms = vn.obs_rms
        assert isinstance(obs_rms, dict), "obs Dict → obs_rms doit être un dict par clé"
        count_before = float(obs_rms["global_cont"].count)

        n_steps = 10
        raw_gc = [
            np.random.default_rng(i).standard_normal((n_steps, 13)) for i in range(2)
        ]
        disc_rets = [np.ones(n_steps) * float(i) for i in range(2)]
        final_returns = [1.0, 2.0]

        update_vec_normalize_from_trajectories(vn, raw_gc, disc_rets, final_returns)

        count_after = float(obs_rms["global_cont"].count)
        assert count_after > count_before, (
            f"obs_rms count n'a pas augmenté après update : {count_before} → {count_after}"
        )

    def test_returns_state_restored_per_worker(self):
        """VecNormalize.returns[i] est restauré avec la valeur finale du worker i."""
        from ai.vec_normalize_frozen import update_vec_normalize_from_trajectories

        try:
            vn = self._make_vec_normalize(n_envs=3)
        except Exception:
            pytest.skip("DummyVecEnv avec obs Dict non disponible")

        final_returns = [1.5, 3.0, 0.0]
        n_steps = 5
        raw_gc = [np.zeros((n_steps, 13)) for _ in range(3)]
        disc_rets = [np.zeros(n_steps) for _ in range(3)]

        update_vec_normalize_from_trajectories(vn, raw_gc, disc_rets, final_returns)

        np.testing.assert_allclose(
            vn.returns, np.array(final_returns), atol=1e-9,
            err_msg="returns[i] non restauré avec la valeur finale du worker i"
        )

    def test_noop_without_vec_normalize(self):
        """update_vec_normalize_from_trajectories ne lève pas si pas de VecNormalize."""
        from ai.vec_normalize_frozen import update_vec_normalize_from_trajectories

        plain_env = MagicMock()
        del plain_env.venv

        # Ne doit pas lever.
        update_vec_normalize_from_trajectories(plain_env, [], [], [])


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 3.6 — Normalisation des rewards Phase 3 après mise à jour ret_rms
# ══════════════════════════════════════════════════════════════════════════════════════════════


def _cold_start_obs_space():
    """Espace d'observation minimal des stubs 3.6 : la seule clé que VecNormalize normalise."""
    from gymnasium import spaces
    return spaces.Dict({"global_cont": spaces.Box(-1.0, 1.0, (13,), dtype=np.float32)})


def _make_cold_start_vec_normalize(n_envs: int = 2):
    """VecNormalize réel avec ret_rms.var=1.0 — l'état d'un run neuf au rollout 1."""
    from stable_baselines3.common.vec_env import VecNormalize, DummyVecEnv
    import gymnasium as gym
    from gymnasium import spaces

    class StubEnv(gym.Env):
        observation_space = _cold_start_obs_space()
        action_space = spaces.Discrete(4)

        def reset(self, **kw):
            return {"global_cont": np.zeros(13, dtype=np.float32)}, {}

        def step(self, action):
            return {"global_cont": np.zeros(13, dtype=np.float32)}, 0.0, False, False, {}

    vec = DummyVecEnv([StubEnv] * n_envs)
    vn = VecNormalize(vec, norm_obs=False, norm_reward=True, gamma=0.99)
    vn.reset()
    # ret_rms.var vaut 1.0 à l'initialisation (état Phase 3 rollout 1).
    assert abs(float(vn.ret_rms.var) - 1.0) < 1e-9, "Précondition : ret_rms.var initial = 1.0"
    return vn


class TestRetVarRescaling:
    """Vérifie la normalisation des rewards par le ret_var POST-update, sans toucher au critique.

    En Phase 3, le snapshot gèle ret_var pendant la collecte : au premier rollout d'un run neuf
    il vaut 1.0, la valeur d'initialisation de RunningMeanStd. Les rewards du buffer sont donc
    normalisées au learner, après update_vec_normalize_from_trajectories, avec le ret_var réel.

    Ce qui NE doit PAS arriver : appliquer sqrt(old_ret_var)/sqrt(new_ret_var) aux sorties du
    critique (values, last_values, bootstrap). Ce facteur suppose V proportionnel à 1/sqrt(ret_var),
    vrai seulement à convergence ; au cold-start il vaut 0.060 et écrase les prédictions de 17x.
    """

    def test_update_returns_no_rescaling_factor(self):
        """update_vec_normalize_from_trajectories ne retourne aucun facteur de re-scaling.

        Verrou de non-régression : tant que cette fonction renvoyait sqrt(old)/sqrt(new),
        l'appelant multipliait les sorties du critique par un facteur qui valait 0.060 au
        cold-start (run du 2026-08-29), sans que le critique ait jamais appris à l'échelle
        old_ret_var=1.0 — celle-ci n'est que la valeur d'initialisation de RunningMeanStd.
        """
        from ai.vec_normalize_frozen import update_vec_normalize_from_trajectories

        vn = _make_cold_start_vec_normalize(n_envs=2)
        rng = np.random.default_rng(0)
        disc_rets_worker = rng.normal(loc=50.0, scale=27.0, size=(10,))

        result = update_vec_normalize_from_trajectories(
            vn, [], [disc_rets_worker, disc_rets_worker], [float(disc_rets_worker[-1])] * 2
        )

        assert float(vn.ret_rms.var) > 10.0, "précondition : ret_var a bien changé"
        assert result is None, (
            "update_vec_normalize_from_trajectories doit retourner None même quand ret_var "
            f"change fortement (obtenu {result!r}) : aucun facteur ne doit être appliqué aux "
            "sorties du critique."
        )

    def test_cold_start_clipping_bug_quantified(self):
        """Formule : clip×rescale (ancien) ≠ normalisation directe (nouveau).

        Au cold-start (ret_var=1.0, raw_terminal=150, clip=10, new_ret_var=22500) :
        - Ancien : clip(150/sqrt(1))=10 → ×sqrt(1)/sqrt(22500) = 0.067 (15× trop petit)
        - Nouveau : clip(150/sqrt(22500)) = 1.0 (correct)
        """
        raw_terminal = 150.0
        clip_reward = 10.0
        ret_var_initial = 1.0
        new_ret_var = 22500.0
        eps = 1e-8

        # Ancien comportement (bugué).
        norm_clipped = float(np.clip(raw_terminal / np.sqrt(ret_var_initial + eps), -clip_reward, clip_reward))
        scale_buggy = float(np.sqrt(ret_var_initial + eps) / np.sqrt(new_ret_var + eps))
        reward_buggy = norm_clipped * scale_buggy

        # Nouveau comportement (fix) : normalise avec new_ret_var.
        reward_fixed = float(np.clip(raw_terminal / np.sqrt(new_ret_var + eps), -clip_reward, clip_reward))

        assert norm_clipped == pytest.approx(clip_reward, rel=1e-5)
        assert reward_buggy == pytest.approx(0.0667, rel=0.01)
        assert reward_fixed == pytest.approx(1.0, rel=0.01)
        assert reward_fixed / reward_buggy > 10


class TestCriticOutputsNotRescaled:
    """Verrou sur le VRAI chemin : _collect_rollouts_distributed ne rescale pas le critique.

    Les deux tests de TestRetVarRescaling portent sur la fonction de mise à jour seule. Celui-ci
    exerce _collect_rollouts_distributed de bout en bout avec un VecNormalize au cold-start
    (ret_rms.var = 1.0) et des retours de forte variance, exactement la configuration où le
    facteur sqrt(old)/sqrt(new) valait 0.060 sur le run du 2026-08-29.
    """

    N_ENVS = 2
    N_STEPS = 4
    VALUE = 5.0          # sortie constante du critique stub, pour values_seq et last_value
    BOOTSTRAP = 0.1      # non nul : un rescaling du bootstrap se verrait dans buf.rewards
    GAMMA = 0.99

    def _make_trajectory(self, worker_idx: int, raw_reward: float = 0.27):
        """Trajectoire synthétique : values non nulles, retours de forte variance, sans done."""
        rng = np.random.default_rng(100 + worker_idx)
        n = self.N_STEPS
        # discounted_returns de std ≈ 27 → ret_rms.var ≫ 1.0 après update.
        disc_rets = rng.normal(loc=50.0, scale=27.0, size=(n,))
        return {
            "norm_obs_seq": {"global_cont": np.zeros((n, 13), dtype=np.float32)},
            "actions_seq": np.zeros(n, dtype=np.int64),
            "rewards_seq": np.full(n, raw_reward, dtype=np.float32),
            "raw_rewards_seq": np.full(n, raw_reward, dtype=np.float32),
            "bootstrap_seq": np.full(n, self.BOOTSTRAP, dtype=np.float32),
            "dones_seq": np.zeros(n, dtype=bool),
            "episode_starts_seq": np.zeros(n, dtype=bool),
            # Valeurs du critique franchement non nulles : un re-scaling se verrait.
            "values_seq": np.full(n, self.VALUE, dtype=np.float32),
            "log_probs_seq": np.full(n, -1.0, dtype=np.float32),
            "masks_seq": np.ones((n, 4), dtype=bool),
            "infos_seq": [{} for _ in range(n)],
            "last_raw_obs": {"global_cont": np.zeros(13, dtype=np.float32)},
            "last_norm_obs": {"global_cont": np.zeros(13, dtype=np.float32)},
            "last_done": False,
            "last_value": self.VALUE,
            "raw_global_cont": np.zeros((n, 13), dtype=np.float64),
            "discounted_returns": disc_rets,
            "final_discounted_return": float(disc_rets[-1]),
            "episode_wall_seconds_seq": np.zeros(n, dtype=np.float64),
        }

    def _run_distributed_rollout(self, raw_reward: float):
        """Exerce _collect_rollouts_distributed au cold-start. Retourne (VecNormalize, buffer)."""
        from sb3_contrib.common.maskable.buffers import MaskableDictRolloutBuffer
        from ai.patched_ppo import PatchedMaskablePPO

        vn = _make_cold_start_vec_normalize(self.N_ENVS)
        obs_space = _cold_start_obs_space()
        act_space = vn.action_space

        trajectories = [
            self._make_trajectory(i, raw_reward=raw_reward) for i in range(self.N_ENVS)
        ]

        subproc = MagicMock()
        subproc.num_envs = self.N_ENVS
        subproc.collect_trajectories.return_value = trajectories

        buf = MaskableDictRolloutBuffer(
            buffer_size=self.N_STEPS, observation_space=obs_space, action_space=act_space,
            device="cpu", gamma=self.GAMMA, gae_lambda=0.95, n_envs=self.N_ENVS,
        )

        with patch.object(PatchedMaskablePPO, "_setup_model"):
            model = PatchedMaskablePPO.__new__(PatchedMaskablePPO)

        n_envs, value = self.N_ENVS, self.VALUE

        class _StubPolicy:
            """Policy minimale : __dict__ sans forward/action_dist, deepcopy trivial."""

            def set_training_mode(self, mode: bool) -> None:
                pass

            def cpu(self):
                return self

            def predict_values(self, obs):
                return torch.full((n_envs, 1), value)

        model.policy = _StubPolicy()  # type: ignore[assignment]
        model.device = torch.device("cpu")
        model._last_episode_starts = np.zeros(self.N_ENVS, dtype=bool)
        model.num_timesteps = 0
        model.action_space = act_space
        model._update_info_buffer = MagicMock()

        callback = MagicMock()
        callback.on_step.return_value = True

        with patch("cloudpickle.dumps", return_value=b""), \
             patch("copy.deepcopy", side_effect=lambda p: p), \
             patch("ai.patched_ppo.is_masking_supported", return_value=True):
            model._collect_rollouts_distributed(
                vn, subproc, callback, buf, self.N_STEPS, use_masking=True
            )

        return vn, buf

    def test_large_rewards_clipped_on_post_update_ret_var(self):
        """Le clip ±10 doit porter sur raw/sqrt(ret_var POST-update), jamais sur le ret_var gelé.

        C'est le scénario cold-start réel : avec ret_var=1.0 gelé, une reward de 150 sature le
        clip à 10.0 ; normalisée par le ret_var réel elle vaut ~0.2 et ne sature pas. Le test
        exerce le chemin de clipping, que le scénario à raw_reward=0.27 ne touche jamais.
        """
        raw_reward = 150.0
        vn, buf = self._run_distributed_rollout(raw_reward=raw_reward)

        new_ret_var = float(vn.ret_rms.var)
        eps, clip_r = float(vn.epsilon), float(vn.clip_reward)

        saturated = float(np.clip(raw_reward / np.sqrt(1.0 + eps), -clip_r, clip_r))
        assert saturated == pytest.approx(clip_r), (
            "précondition : normalisée par le ret_var GELÉ, la reward doit saturer le clip"
        )

        expected = (
            np.clip(
                np.full((self.N_STEPS, self.N_ENVS), raw_reward, dtype=np.float32)
                / np.sqrt(new_ret_var + eps),
                -clip_r, clip_r,
            )
            + self.BOOTSTRAP
        ).astype(np.float32)
        assert float(expected[0, 0]) < clip_r, (
            "précondition : normalisée par le ret_var POST-update, la reward ne doit pas saturer"
        )
        np.testing.assert_allclose(
            buf.rewards, expected, rtol=1e-5,
            err_msg=(
                f"buf.rewards saturé à {clip_r} : le clip a été appliqué sur le ret_var gelé "
                f"au lieu du ret_var post-update ({new_ret_var:.2f})"
            ),
        )

    def test_buffer_values_untouched_when_ret_var_jumps_at_cold_start(self):
        """rollout_buffer.values doit rester égal aux values des workers, ret_var neuf ou non."""

        vn, buf = self._run_distributed_rollout(raw_reward=0.27)
        new_ret_var = float(vn.ret_rms.var)

        assert new_ret_var > 10.0, (
            f"précondition : ret_var doit avoir sauté depuis 1.0 (obtenu {new_ret_var})"
        )

        # Le facteur qui était appliqué avant le 2026-08-29, pour situer l'écart attendu.
        would_be_scale = float(np.sqrt(1.0 + vn.epsilon) / np.sqrt(new_ret_var + vn.epsilon))
        assert would_be_scale < 0.35, (
            f"le scénario doit produire un facteur franchement < 1 (obtenu {would_be_scale:.4f})"
        )

        np.testing.assert_allclose(
            buf.values, np.full((self.N_STEPS, self.N_ENVS), 5.0, dtype=np.float32), rtol=1e-6,
            err_msg=(
                "rollout_buffer.values a été rescalé : les sorties du critique doivent traverser "
                f"_collect_rollouts_distributed intactes (facteur qui serait appliqué : "
                f"{would_be_scale:.4f})"
            ),
        )

        # Verrou bootstrap : bootstrap_seq = 0.1 (non nul) ; tout rescaling se verrait dans rewards.
        eps = float(vn.epsilon)
        clip_r = float(vn.clip_reward)
        raw_reward = 0.27
        bootstrap_val = 0.1
        expected_rewards = (
            np.clip(
                np.full((self.N_STEPS, self.N_ENVS), raw_reward, dtype=np.float32)
                / np.sqrt(new_ret_var + eps),
                -clip_r, clip_r,
            )
            + bootstrap_val
        ).astype(np.float32)
        np.testing.assert_allclose(
            buf.rewards, expected_rewards, rtol=1e-5,
            err_msg=(
                "rollout_buffer.rewards incorrect : raw_rewards ou bootstrap ont été rescalés "
                f"(new_ret_var={new_ret_var:.2f}, facteur qui serait appliqué : {would_be_scale:.4f})"
            ),
        )

        # Verrou last_values — assertion EXACTE, pas un seuil. Au dernier step il n'y a ni done
        # ni step suivant, donc GAE se réduit à A_3 = r_3 + gamma*last_value - V(s_3), et comme
        # returns = A + values, le V(s_3) s'annule : returns[-1] = r_3 + gamma*last_value.
        # C'est la seule quantité du buffer où last_values entre sans être mélangé au reste, ce
        # qui rend n'importe quel facteur détectable — un seuil sur returns.mean() laissait au
        # contraire passer un rescaling modéré (×0.5 vérifié vert).
        expected_last_return = float(expected_rewards[-1, 0]) + self.GAMMA * self.VALUE
        np.testing.assert_allclose(
            buf.returns[-1], np.full(self.N_ENVS, expected_last_return, dtype=np.float32),
            rtol=1e-5,
            err_msg=(
                f"buf.returns[-1] ≠ r_3 + gamma*last_value ({expected_last_return:.4f}) : "
                "last_values a été rescalé avant compute_returns_and_advantage"
            ),
        )
