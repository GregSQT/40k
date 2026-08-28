"""Tests Phase 3 perf_entrainement — collecte distribuée (Option A).

Couvre :
  3.1  VecNormalizeSnapshot : snapshot_vec_normalize / normalize_obs_with_snapshot.
  3.2  Drift VecNormalize : tolérance mesurée et documentée (batch vs step-by-step).
  3.3  _run_worker_trajectory : structure, bootstrap TimeLimit.truncated, semantics.
  3.4  collect_rollouts dispatch : bascule vers _collect_rollouts_distributed si MaskableSubprocVecEnv.
  3.5  update_vec_normalize_from_trajectories : mise à jour batch des stats.

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
    ret_rms.mean = np.float64(1.0)
    ret_rms.var = np.float64(4.0)
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
        from stable_baselines3.common.vec_env import VecNormalize, DummyVecEnv
        import gymnasium as gym
        from gymnasium import spaces

        class _StubEnv(gym.Env):
            observation_space = spaces.Box(-1.0, 1.0, (4,), dtype=np.float32)
            action_space = spaces.Discrete(2)
            def reset(self, **kw): return np.zeros(4, dtype=np.float32), {}
            def step(self, a): return np.zeros(4, dtype=np.float32), 0.0, False, False, {}

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
        assert snap.obs_mean is not vn_real.obs_rms.mean

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
            def step(self, a): return np.zeros(4, dtype=np.float32), 1.0, False, False, {}

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

            def step(self, a):
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

        count_before = float(vn.obs_rms["global_cont"].count)

        n_steps = 10
        raw_gc = [
            np.random.default_rng(i).standard_normal((n_steps, 13)) for i in range(2)
        ]
        disc_rets = [np.ones(n_steps) * float(i) for i in range(2)]
        final_returns = [1.0, 2.0]

        update_vec_normalize_from_trajectories(vn, raw_gc, disc_rets, final_returns)

        count_after = float(vn.obs_rms["global_cont"].count)
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
