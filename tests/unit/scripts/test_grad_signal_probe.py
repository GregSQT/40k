"""Statistiques de `scripts/grad_signal_probe.py` sur des gradients SYNTHÉTIQUES.

Chaque test construit ses K « gradients de rollouts » avec un gradient vrai et un bruit connus,
donc une valeur attendue calculable à la main : sans bruit f = 1, bruit pur f ≈ 0, ‖G‖² sans biais
retrouve ‖μ‖² là où la moyenne des carrés de norme le surestime, et tout est invariant d'échelle.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch.nn as nn

from scripts.grad_signal_probe import (
    ACCEPTANCE_BOUNDS,
    OUTCOME_REWARD,
    apply_rule,
    check_acceptance,
    cosine_stats,
    cross_gram_matrix,
    diagonal_mean,
    gram_matrix,
    jackknife,
    off_diagonal_mean,
    outcome_returns,
    parameter_groups,
    signal_stats,
    swap_and_flatten,
)

K = 24
D = 2000
BATCH_STEPS = 8160
MINIBATCHES = 8


def _rollouts(rng: np.random.Generator, mu: np.ndarray, sigma: float) -> tuple[np.ndarray, np.ndarray]:
    """K gradients de rollouts μ + N(0, σ²I) et leurs M gradients de mini-lots (bruit × √M).

    Un rollout est la moyenne de ses M mini-lots ; les mini-lots portent donc un bruit √M fois
    plus grand. Les carrés de norme des mini-lots sont ce que le script accumule.
    """
    minibatch = mu[None, None, :] + rng.normal(0.0, sigma * np.sqrt(MINIBATCHES), size=(K, MINIBATCHES, D))
    rollout = minibatch.mean(axis=1)
    mb_sq = (minibatch ** 2).sum(axis=2)
    return rollout, mb_sq


def test_sans_bruit_f_vaut_un_et_b_noise_zero():
    mu = np.linspace(-1.0, 1.0, D)
    rollout = np.tile(mu, (K, 1))
    mb_sq = np.tile((mu ** 2).sum(), (K, MINIBATCHES))
    st = signal_stats(gram_matrix(rollout), mb_sq, BATCH_STEPS)
    assert st["signal_detected"]
    assert st["true_sq"]["estimate"] == pytest.approx((mu ** 2).sum())
    assert st["f_batch"]["estimate"] == pytest.approx(1.0)
    assert st["f_minibatch"]["estimate"] == pytest.approx(1.0)
    assert st["b_noise"]["estimate"] == pytest.approx(0.0, abs=1e-9)
    assert st["f_batch"]["se"] == pytest.approx(0.0, abs=1e-9)


def test_bruit_pur_signal_non_detecte_et_f_dans_l_intervalle_de_zero():
    rng = np.random.default_rng(7)
    rollout, mb_sq = _rollouts(rng, np.zeros(D), sigma=1.0)
    st = signal_stats(gram_matrix(rollout), mb_sq, BATCH_STEPS)
    assert not st["signal_detected"]
    assert st["true_sq"]["low"] <= 0.0 <= st["true_sq"]["high"]
    # f_B = ‖G‖²_unb / E‖G_k‖² : l'estimation est ~0 et son intervalle contient 0.
    assert abs(st["f_batch"]["estimate"]) < 0.05
    assert st["f_batch"]["low"] <= 0.0 <= st["f_batch"]["high"]
    assert st["rollout_sq"]["estimate"] == pytest.approx(D, rel=0.1)
    # Sans signal, B_noise n'est pas défini : nan, jamais un nombre inventé.
    assert np.isnan(st["b_noise"]["estimate"]) or st["b_noise"]["estimate"] < 0
    assert apply_rule(st)["branch"] == 1


def test_norme_sans_biais_retrouve_mu_la_ou_la_diagonale_surestime():
    rng = np.random.default_rng(11)
    mu = rng.normal(0.0, 0.05, size=D)  # ‖μ‖² ≈ 5
    sigma = 0.3                          # tr(Σ_rollout) = D σ² = 180 ≫ ‖μ‖²
    rollout, mb_sq = _rollouts(rng, mu, sigma)
    gram = gram_matrix(rollout)
    true_sq = float((mu ** 2).sum())
    st = signal_stats(gram, mb_sq, BATCH_STEPS)
    assert st["signal_detected"]
    assert st["true_sq"]["low"] <= true_sq <= st["true_sq"]["high"]
    assert st["true_sq"]["estimate"] == pytest.approx(true_sq, rel=0.15)
    # La moyenne des carrés de norme porte le biais tr(Σ) : elle vaut ‖μ‖² + D σ².
    assert diagonal_mean(gram) == pytest.approx(true_sq + D * sigma ** 2, rel=0.1)
    # B_noise = tr(Σ_rollout) · B / ‖G‖² = D σ² · B / ‖μ‖².
    expected_b_noise = D * sigma ** 2 * BATCH_STEPS / true_sq
    assert st["b_noise"]["estimate"] == pytest.approx(expected_b_noise, rel=0.25)
    # f_B = ‖μ‖² / (‖μ‖² + D σ²) ; f_mb = ‖μ‖² / (‖μ‖² + M D σ²).
    assert st["f_batch"]["estimate"] == pytest.approx(true_sq / (true_sq + D * sigma ** 2), rel=0.2)
    assert st["f_minibatch"]["estimate"] == pytest.approx(true_sq / (true_sq + MINIBATCHES * D * sigma ** 2), rel=0.2)
    assert apply_rule(st)["branch"] == 2  # f_B ≈ 0,027 < 0,1 : update = bruit
    assert apply_rule(st)["factor"] == pytest.approx(st["b_noise"]["estimate"] / BATCH_STEPS)


def test_invariance_d_echelle():
    rng = np.random.default_rng(3)
    mu = rng.normal(0.0, 0.2, size=D)
    rollout, mb_sq = _rollouts(rng, mu, sigma=0.3)
    st1 = signal_stats(gram_matrix(rollout), mb_sq, BATCH_STEPS)
    scale = 7.0
    st2 = signal_stats(gram_matrix(rollout * scale), mb_sq * scale ** 2, BATCH_STEPS)
    for key in ("f_batch", "f_minibatch", "b_noise"):
        for field in ("estimate", "low", "high"):
            assert st2[key][field] == pytest.approx(st1[key][field], rel=1e-9), key
    assert st2["true_sq"]["estimate"] == pytest.approx(st1["true_sq"]["estimate"] * scale ** 2, rel=1e-9)


def test_signal_propre_branche_3_et_entre_deux_branche_4():
    rng = np.random.default_rng(5)
    mu = rng.normal(0.0, 1.0, size=D)  # ‖μ‖² ≈ 2000
    rollout, mb_sq = _rollouts(rng, mu, sigma=0.3)  # D σ² = 180 → f_B ≈ 0,92
    st = signal_stats(gram_matrix(rollout), mb_sq, BATCH_STEPS)
    assert st["f_batch"]["estimate"] > 0.5
    assert apply_rule(st)["branch"] == 3
    rollout, mb_sq = _rollouts(rng, mu, sigma=1.5)  # D σ² = 4500 → f_B ≈ 0,31
    st = signal_stats(gram_matrix(rollout), mb_sq, BATCH_STEPS)
    assert 0.1 < st["f_batch"]["estimate"] < 0.5
    assert apply_rule(st)["branch"] == 4


def test_cosinus_sans_biais_retrouve_l_angle_et_refuse_le_bruit_pur():
    rng = np.random.default_rng(13)
    u = rng.normal(0.0, 0.3, size=D)
    w = rng.normal(0.0, 0.3, size=D)
    v = 0.6 * u + 0.8 * w  # cos(u, v) ≈ 0,6 (u ⟂ w en espérance)
    expected = float(u @ v / np.sqrt((u @ u) * (v @ v)))
    a = u[None, :] + rng.normal(0.0, 0.5, size=(K, D))
    b = v[None, :] + rng.normal(0.0, 0.5, size=(K, D))
    c = cosine_stats(cross_gram_matrix(a, b), gram_matrix(a), gram_matrix(b))
    assert c["measurable"]
    assert c["cosine"]["low"] <= expected <= c["cosine"]["high"]
    assert c["cosine"]["estimate"] == pytest.approx(expected, abs=0.15)
    # Le cosinus NAÏF (moyennes des gradients bruités) est tiré vers 0 par le bruit ; l'estimateur
    # croisé ne l'est pas.
    naive = float(a.mean(0) @ b.mean(0) / np.sqrt((a.mean(0) @ a.mean(0)) * (b.mean(0) @ b.mean(0))))
    assert abs(c["cosine"]["estimate"] - expected) < abs(naive - expected)
    # Bruit pur des deux côtés : non mesurable.
    a0 = rng.normal(0.0, 1.0, size=(K, D))
    b0 = rng.normal(0.0, 1.0, size=(K, D))
    c0 = cosine_stats(cross_gram_matrix(a0, b0), gram_matrix(a0), gram_matrix(b0))
    assert not c0["measurable"]
    # Normes sans biais trop bruitées : le quotient sort de [-1, 1] → non mesurable même si
    # l'intervalle exclut 0.
    unit = np.ones((K, K)) + np.eye(K)
    c_out = cosine_stats(5.0 * unit, unit, unit)
    assert c_out["cosine"]["estimate"] == pytest.approx(5.0)
    assert not c_out["measurable"]
    # Estimation dans [-1, 1] mais intervalle qui en sort (une paire de rollouts aberrante) :
    # non mesurable aussi.
    cross = 0.5 * unit
    cross[0, 1] = cross[1, 0] = 60.0
    c_wide = cosine_stats(cross, unit, unit)
    assert abs(c_wide["cosine"]["estimate"]) <= 1.0
    assert c_wide["cosine"]["high"] > 1.0
    assert not c_wide["measurable"]
    # Le même cosinus sans la paire aberrante est mesurable.
    assert cosine_stats(0.5 * unit, unit, unit)["measurable"]


def test_jackknife_intervalle_couvre_la_moyenne_et_se_ferme_sans_bruit():
    rng = np.random.default_rng(17)
    x = rng.normal(2.0, 1.0, size=K)
    est = jackknife(lambda keep: float(x[keep].mean()), K)
    assert est["estimate"] == pytest.approx(x.mean())
    # Pour une moyenne, l'erreur-type jackknife est exactement s/√K.
    assert est["se"] == pytest.approx(x.std(ddof=1) / np.sqrt(K))
    const = jackknife(lambda keep: 4.0, K)
    assert const["low"] == const["high"] == 4.0
    with pytest.raises(ValueError):
        jackknife(lambda keep: 0.0, 2)


def test_off_diagonal_et_diagonale():
    m = np.array([[1.0, 2.0, 3.0], [2.0, 4.0, 5.0], [3.0, 5.0, 6.0]])
    assert off_diagonal_mean(m) == pytest.approx((2 + 3 + 5) * 2 / 6)
    assert diagonal_mean(m) == pytest.approx(11 / 3)
    with pytest.raises(ValueError):
        off_diagonal_mean(np.ones((1, 1)))


def test_retours_d_issue_sur_les_seuls_episodes_complets():
    gamma = 0.9
    # env 0 : queue d'un épisode ouvert avant (t=0, invalide), épisode complet t=1..3 gagné,
    #         épisode entamé t=4..5 non fini (invalide).
    # env 1 : épisode complet t=0..1 perdu, épisode complet t=2..2 nul, puis t=3..5 non fini.
    starts = np.array([[False, True], [True, False], [False, True], [False, True], [True, False], [False, False]])
    dones = np.array([[True, False], [False, True], [False, True], [True, False], [False, False], [False, False]])
    outcome = np.zeros((6, 2))
    outcome[0, 0] = OUTCOME_REWARD          # fin de la queue : ne doit PAS compter
    outcome[3, 0] = OUTCOME_REWARD
    outcome[1, 1] = -OUTCOME_REWARD
    outcome[2, 1] = 0.0
    returns, valid = outcome_returns(starts, dones, outcome, gamma)
    assert valid[:, 0].tolist() == [False, True, True, True, False, False]
    assert valid[:, 1].tolist() == [True, True, True, False, False, False]
    assert returns[1:4, 0] == pytest.approx([OUTCOME_REWARD * gamma ** 2, OUTCOME_REWARD * gamma, OUTCOME_REWARD])
    assert returns[0, 0] == 0.0
    assert returns[0:2, 1] == pytest.approx([-OUTCOME_REWARD * gamma, -OUTCOME_REWARD])
    assert returns[2, 1] == 0.0 and valid[2, 1]
    assert (returns[3:, 1] == 0.0).all()
    assert returns.shape == valid.shape == (6, 2)


def test_swap_and_flatten_suit_la_disposition_sb3():
    arr = np.arange(6).reshape(3, 2)  # (T=3, N=2)
    # SB3 : env-major, les T pas d'un env se suivent.
    assert swap_and_flatten(arr).tolist() == [0, 2, 4, 1, 3, 5]


def test_groupes_de_parametres_dedoublonnent_les_alias_et_tranchent_par_module():
    class Net(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.features_extractor = nn.Linear(4, 3)
            self.pi_features_extractor = self.features_extractor  # alias, comme SB3
            self.vf_features_extractor = self.features_extractor
            self.action_net = nn.Linear(3, 2)
            self.value_net = nn.Linear(3, 1)

    net = Net()
    params, groups, n = parameter_groups(list(net.named_parameters()))
    assert n == (4 * 3 + 3) + (3 * 2 + 2) + (3 + 1)
    assert list(groups) == ["features_extractor", "action_net", "value_net"]
    assert groups["features_extractor"] == (0, 15)
    assert groups["action_net"] == (15, 23)
    assert groups["value_net"] == (23, 27)
    assert len(params) == 6
    # Un alias qui aurait survécu à l'énumération est refusé, pas compté deux fois.
    dup = list(net.named_parameters()) + [("pi_features_extractor.weight", net.features_extractor.weight)]
    with pytest.raises(ValueError):
        parameter_groups(dup)


def test_acceptation_liste_les_ecarts_et_accepte_la_reference():
    reference = {
        "grad_norm_policy_mb0": 0.354, "grad_norm_value_mb0": 0.218, "grad_norm_entropy_mb0": 0.0046,
        "explained_variance": 0.889, "ep_len_mean": 111.9, "returns_mean": 1.644, "pool_episode_share": 0.70,
    }
    assert check_acceptance(reference) == []
    broken = dict(reference, explained_variance=-0.3, returns_mean=float("nan"))
    failures = check_acceptance(broken)
    assert len(failures) == 2
    assert any(f.startswith("explained_variance") for f in failures)
    assert any(f.startswith("returns_mean") for f in failures)
    assert set(ACCEPTANCE_BOUNDS) == set(reference)


# ── Balayage λ, décomposition de variance, contrôle positif (2026-09-13) ─────────────────────


def _synthetic_rollout(rng: np.random.Generator, n_steps: int = 200, n_envs: int = 4):
    """Rewards / values / episode_starts (T, N) float32 + last_values / last_dones (N,) plausibles."""
    rewards = rng.normal(0.0, 1.0, size=(n_steps, n_envs)).astype(np.float32)
    values = rng.normal(0.5, 2.0, size=(n_steps, n_envs)).astype(np.float32)
    starts = (rng.random((n_steps, n_envs)) < 0.05)
    starts[0, :] = rng.random(n_envs) < 0.5  # certains envs reprennent un épisode ouvert avant
    last_values = rng.normal(0.5, 2.0, size=n_envs).astype(np.float32)
    last_dones = rng.random(n_envs) < 0.5
    return rewards, values, starts.astype(np.float32), last_values, last_dones


@pytest.mark.parametrize("gae_lambda", [0.95, 0.8, 0.0])
def test_gae_recalcule_reproduit_sb3_au_1e_6(gae_lambda):
    import torch as th
    from gymnasium import spaces
    from stable_baselines3.common.buffers import RolloutBuffer

    from scripts.grad_signal_probe import GAE_ATOL, gae_advantages

    rng = np.random.default_rng(23)
    rewards, values, starts, last_values, last_dones = _synthetic_rollout(rng)
    n_steps, n_envs = rewards.shape
    gamma = 0.99
    buf = RolloutBuffer(n_steps, spaces.Box(-1, 1, (2,)), spaces.Discrete(3), device="cpu",
                        gamma=gamma, gae_lambda=gae_lambda, n_envs=n_envs)
    buf.rewards = rewards.copy()
    buf.values = values.copy()
    buf.episode_starts = starts.copy()
    buf.compute_returns_and_advantage(th.as_tensor(last_values).reshape(n_envs, 1), last_dones)
    adv, ret = gae_advantages(rewards, values, starts, last_values, last_dones, gamma, gae_lambda)
    assert adv.shape == ret.shape == (n_steps, n_envs)
    assert np.max(np.abs(adv - buf.advantages)) <= GAE_ATOL
    assert np.max(np.abs(ret - buf.returns)) <= GAE_ATOL
    # VERT VACANT : les avantages ne sont pas triviaux (épisodes, bootstrap, valeurs non nulles).
    assert np.abs(adv).max() > 1.0 and starts.sum() > 0


def test_lambda_zero_donne_delta_et_lambda_un_le_retour_monte_carlo():
    from scripts.grad_signal_probe import bootstrap_value_change, gae_advantages

    rng = np.random.default_rng(29)
    rewards, values, starts, last_values, last_dones = _synthetic_rollout(rng)
    n_steps, n_envs = rewards.shape
    gamma = 0.9
    delta_v = bootstrap_value_change(values, starts, last_values, last_dones, gamma)
    adv0, _ = gae_advantages(rewards, values, starts, last_values, last_dones, gamma, 0.0)
    assert adv0 == pytest.approx(rewards.astype(np.float64) + delta_v, abs=1e-5)
    # ΔV coupe bien au bord d'épisode : là où le pas suivant ouvre un épisode, ΔV = −V(s_t).
    t, n = np.argwhere(starts[1:] == 1.0)[0]
    assert delta_v[t, n] == pytest.approx(-float(values[t, n]))
    # λ = 1 : retour Monte-Carlo actualisé avec bootstrap, calculé indépendamment vers l'avant.
    adv1, ret1 = gae_advantages(rewards, values, starts, last_values, last_dones, gamma, 1.0)
    for env in range(n_envs):
        # Découpe en segments [début, fin[ par les episode_starts et la borne du rollout.
        bounds = [0, *(np.flatnonzero(starts[1:, env] == 1.0) + 1), n_steps]
        for seg_start, seg_end in zip(bounds[:-1], bounds[1:], strict=True):
            closes = seg_end < n_steps or last_dones[env]
            g = 0.0 if closes else float(last_values[env])
            for t in range(seg_end - 1, seg_start - 1, -1):
                g = float(rewards[t, env]) + gamma * g
                assert ret1[t, env] == pytest.approx(g, abs=1e-4)
    assert ret1 == pytest.approx(adv1 + values, abs=1e-6)


def test_decomposition_de_variance_somme_exacte_globalement_et_par_famille():
    from scripts.grad_signal_probe import DeltaVarianceAccumulator

    rng = np.random.default_rng(31)
    acc = DeltaVarianceAccumulator()
    all_r, all_d, all_f = [], [], []
    for _ in range(3):  # trois rollouts accumulés ; la variance doit être celle de la concaténation
        r = rng.normal(0.0, 1.0, size=(50, 4))
        d = 0.5 * r + rng.normal(0.0, 2.0, size=(50, 4))  # corrélé à r : Cov ≠ 0
        f = rng.choice(["move_cell", "shoot_slot", "wait"], size=(50, 4), p=[0.6, 0.3, 0.1])
        acc.add(r, d, f)
        all_r.append(r.ravel())
        all_d.append(d.ravel())
        all_f.append(f.ravel())
    r, d, f = np.concatenate(all_r), np.concatenate(all_d), np.concatenate(all_f)
    out = acc.result()
    for name, mask in [("all", np.ones(r.size, bool)), *[(fam, f == fam) for fam in np.unique(f)]]:
        got = out["all"] if name == "all" else out["by_family"][name]
        assert got["n"] == int(mask.sum())
        assert got["var_reward"] == pytest.approx(np.var(r[mask]))
        assert got["var_delta_v"] == pytest.approx(np.var(d[mask]))
        assert got["cov"] == pytest.approx(np.cov(r[mask], d[mask], bias=True)[0, 1])
        # L'identité Var(δ) = Var(r) + Var(ΔV) + 2 Cov, contre la variance directe de δ = r + ΔV.
        assert got["var_delta"] == pytest.approx(np.var(r[mask] + d[mask]))
        assert got["share_reward"] + got["share_delta_v"] + got["share_cov"] == pytest.approx(1.0)
        assert abs(got["cov"]) > 0.1  # VERT VACANT : la covariance n'est pas nulle par construction
    assert set(out["by_family"]) == set(np.unique(f))
    with pytest.raises(ValueError):
        DeltaVarianceAccumulator().result()
    # Une famille vue UNE fois sur tout le run : rapportée en nan, jamais levée (lever ici
    # jetterait toute la collecte pour une ligne auxiliaire).
    acc.add(np.array([0.7]), np.array([-0.2]), np.array(["shoot_indirect_slot"]))
    rare = acc.result()["by_family"]["shoot_indirect_slot"]
    assert rare["n"] == 1 and rare["mean_reward"] == pytest.approx(0.7)
    assert all(np.isnan(rare[k]) for k in ("var_reward", "var_delta_v", "cov", "var_delta", "share_reward"))
    assert acc.result()["all"]["n"] == r.size + 1
    with pytest.raises(ValueError):
        acc.add(np.zeros(0), np.zeros(0), np.zeros(0, dtype=str))


def test_parts_de_variance_nan_quand_delta_est_constant_a_l_arrondi_pres():
    """Récompense déterministe + critic exact en float32 : δ = 0 à l'arrondi près, Var(δ) est un
    résidu positif (~5e-14 pour Var(r) ≈ 0,18) ; diviser par lui rendait des parts de 1e12."""
    from scripts.grad_signal_probe import VAR_DELTA_REL_FLOOR, DeltaVarianceAccumulator

    rng = np.random.default_rng(2)
    r = rng.choice([0.0, 1.0, 0.3], size=(50, 2))
    v = np.zeros((51, 2), np.float32)
    for t in reversed(range(50)):
        v[t] = (r[t] + 0.99 * v[t + 1]).astype(np.float32)
    delta_v = (np.float32(0.99) * v[1:] - v[:-1]).astype(np.float64)
    acc = DeltaVarianceAccumulator()
    acc.add(r.astype(np.float32).astype(np.float64), delta_v, np.full(r.shape, "shoot_slot"))
    got = acc.result()["all"]
    # VERT VACANT : le résidu est bien strictement positif (le garde « > 0 » l'aurait laissé passer).
    assert 0.0 < got["var_delta"] < VAR_DELTA_REL_FLOOR * (got["var_reward"] + got["var_delta_v"])
    assert got["var_reward"] > 0.1
    assert all(np.isnan(got[k]) for k in ("share_reward", "share_delta_v", "share_cov"))


def test_phases_depuis_global_bin_et_familles_dependent_de_la_phase():
    from engine.macro_intents import ACTION_WAIT, DEPLOY_SLOTS, MOVE_CELLS, SHOOT_SLOTS
    from engine.observation_entities import GLOBAL_BIN_SIZE, OBS_PHASE_IDS, global_bin_index
    from scripts.grad_signal_probe import phases_from_global_bin, step_families

    phases = np.array([["deployment", "move"], ["shoot", "move"], ["move", "fight"]], dtype=object)
    g = np.zeros((3, 2, GLOBAL_BIN_SIZE), dtype=np.float32)
    for t in range(3):
        for n in range(2):
            g[t, n, global_bin_index(f"phase_{phases[t, n]}")] = 1.0
    assert phases_from_global_bin(g).tolist() == phases.tolist()
    assert set(OBS_PHASE_IDS) >= set(phases.ravel())
    deploy_id = DEPLOY_SLOTS[0]  # slot de déploiement EN PHASE deployment, cellule de move ailleurs
    assert deploy_id in MOVE_CELLS
    actions = np.array([[deploy_id, deploy_id], [SHOOT_SLOTS[0], ACTION_WAIT], [deploy_id, ACTION_WAIT]])
    setting_up = np.zeros((3, 2), dtype=bool)
    setting_up[2, 0] = True  # mise en place depuis les réserves en phase move : slot de POSE
    fam = step_families(actions, phases_from_global_bin(g), setting_up)
    assert fam.tolist() == [
        ["deploy_slot", "move_cell"],
        ["shoot_slot", "wait"],
        ["deploy_slot", "wait"],
    ]
    # Un one-hot de phase sans bit levé LÈVE.
    g[1, 1, global_bin_index("phase_move")] = 0.0
    with pytest.raises(ValueError):
        phases_from_global_bin(g)


def test_resolve_probe_model_charge_le_controle_avec_son_pkl_et_resout_les_liens(tmp_path):
    """Le canonique vit derrière un lien symbolique (`ai/models` dans les worktrees) : le désigner
    par son chemin résolu ne doit ni en faire un contrôle, ni servir son pkl à un autre zip."""
    from ai.vec_normalize_utils import get_vec_normalize_path
    from scripts.grad_signal_probe import resolve_probe_model

    real_dir = tmp_path / "real_models"
    real_dir.mkdir()
    (tmp_path / "models").symlink_to(real_dir, target_is_directory=True)
    canonical = tmp_path / "models" / "model_A.zip"  # orthographe via le lien
    canonical_real = real_dir / "model_A.zip"
    control = tmp_path / "ctrl" / "model_B_20260913.zip"
    control.parent.mkdir()
    for zip_path in (canonical, control):
        zip_path.write_bytes(b"zip")
        Path(get_vec_normalize_path(str(zip_path))).write_bytes(b"pkl")
    canonical_pkl = get_vec_normalize_path(str(canonical))
    control_pkl = get_vec_normalize_path(str(control))
    assert control_pkl != canonical_pkl and str(canonical_real) != str(canonical)

    assert resolve_probe_model(str(canonical), None) == (str(canonical), canonical_pkl, False)
    assert resolve_probe_model(str(canonical), str(control)) == (str(control), control_pkl, True)
    # Le canonique en --model, par le lien ou résolu : refusé, jamais « contrôle ».
    with pytest.raises(ValueError, match="désigne le canonique"):
        resolve_probe_model(str(canonical), str(canonical))
    with pytest.raises(ValueError, match="désigne le canonique"):
        resolve_probe_model(str(canonical), str(canonical_real))
    # Un autre zip dont le pkl compagnon EST celui du canonique (lien de fichier) : refusé.
    alias = tmp_path / "ctrl" / "model_C.zip"
    alias.write_bytes(b"zip")
    Path(get_vec_normalize_path(str(alias))).symlink_to(canonical_real.parent / Path(canonical_pkl).name)
    with pytest.raises(ValueError):
        resolve_probe_model(str(canonical), str(alias))
    with pytest.raises(FileNotFoundError):
        resolve_probe_model(str(canonical), str(tmp_path / "absent.zip"))
    Path(control_pkl).unlink()
    with pytest.raises(FileNotFoundError):
        resolve_probe_model(str(canonical), str(control))  # pas de repli sur un autre pkl


def test_parse_gae_lambdas_et_ancrage_au_lambda_du_modele():
    from scripts.grad_signal_probe import DEFAULT_GAE_LAMBDAS, parse_gae_lambdas, sweep_lambdas

    assert parse_gae_lambdas(DEFAULT_GAE_LAMBDAS) == [0.8, 0.5, 0.2, 0.0]
    assert parse_gae_lambdas(" 1, 0.5 ,") == [1.0, 0.5]
    for bad in ("", "1.5", "0.5,0.5", "-0.1"):
        with pytest.raises(ValueError):
            parse_gae_lambdas(bad)
    # Le λ du modèle est toujours balayé, en tête, quel que soit le profil ; jamais en double.
    assert sweep_lambdas(0.95, [0.8, 0.5]) == [0.95, 0.8, 0.5]
    assert sweep_lambdas(0.9, [0.95, 0.9, 0.5]) == [0.9, 0.95, 0.5]
    assert sweep_lambdas(0.9, []) == [0.9]


def test_balayage_lambda_differences_appairees():
    from scripts.grad_signal_probe import lambda_sweep_stats

    rng = np.random.default_rng(37)
    mu = rng.normal(0.0, 0.2, size=D)
    clean, mb_clean = _rollouts(rng, mu, sigma=0.3)   # f ≈ 0,5
    noisy = clean + rng.normal(0.0, 0.6, size=clean.shape)  # même signal, bruit ajouté : f plus bas
    mb_noisy = mb_clean + 0.36 * D * MINIBATCHES
    half = D // 2
    grams = {0.95: {"all": gram_matrix(clean), "head": gram_matrix(clean[:, :half])},
             0.5: {"all": gram_matrix(clean), "head": gram_matrix(clean[:, :half])},
             0.0: {"all": gram_matrix(noisy), "head": gram_matrix(noisy[:, :half])}}
    mbs = {0.95: {"all": mb_clean, "head": mb_clean / 2}, 0.5: {"all": mb_clean, "head": mb_clean / 2},
           0.0: {"all": mb_noisy, "head": mb_noisy / 2}}
    stats = {lam: {g: signal_stats(grams[lam][g], mbs[lam][g], BATCH_STEPS) for g in grams[lam]} for lam in grams}
    out = lambda_sweep_stats(grams, stats)
    assert out["lambdas"] == [0.95, 0.5, 0.0]
    assert out["per_lambda"] == stats  # repris tels quels, par λ et par groupe
    assert out["per_lambda"][0.95]["head"]["true_sq"]["estimate"] < out["per_lambda"][0.95]["all"]["true_sq"]["estimate"]
    by_pair = {(p["lambda_a"], p["lambda_b"]): p for p in out["pairs"]}
    assert set(by_pair) == {(0.95, 0.5), (0.95, 0.0), (0.5, 0.0)}
    same = by_pair[(0.95, 0.5)]
    assert same["f_batch_diff"]["estimate"] == pytest.approx(0.0, abs=1e-12)
    assert same["f_batch_diff"]["se"] == pytest.approx(0.0, abs=1e-12)
    assert not same["f_batch_diff_excludes_zero"]
    diff = by_pair[(0.95, 0.0)]
    assert diff["f_batch_diff"]["estimate"] > 0.1
    assert diff["f_batch_diff_excludes_zero"]
    assert diff["f_batch_diff"]["low"] > 0.0
    # Le signal vrai est le même des deux côtés : Δ‖G‖² appairé contient 0.
    assert diff["true_sq_diff"]["low"] <= 0.0 <= diff["true_sq_diff"]["high"]
    with pytest.raises(ValueError):
        lambda_sweep_stats(grams, {0.95: stats[0.95]})
    with pytest.raises(ValueError):
        lambda_sweep_stats({lam: {"head": g["head"]} for lam, g in grams.items()}, stats)  # « all » requis


class _TinyPolicy(nn.Module):
    """Policy jouet : logits et valeur linéaires sur une observation plate, masque appliqué."""

    def __init__(self, obs_dim: int, n_actions: int) -> None:
        super().__init__()
        self.pi = nn.Linear(obs_dim, n_actions)
        self.vf = nn.Linear(obs_dim, 1)

    def evaluate_actions(self, obs, actions, action_masks):
        import torch as th

        logits = self.pi(obs).masked_fill(~action_masks, -1e9)
        dist = th.distributions.Categorical(logits=logits)
        return self.vf(obs).flatten(), dist.log_prob(actions), dist.entropy()


def test_pertes_policy_des_lambdas_supplementaires_dans_la_meme_passe_avant():
    """`policy_sweep[λ]` est EXACTEMENT la perte policy qu'un mini-lot portant ces avantages
    donnerait (mêmes ratios, même normalisation), et son gradient aussi ; au λ du modèle,
    avantages identiques → perte identique."""
    from types import SimpleNamespace

    import torch as th
    from gymnasium import spaces

    from scripts.grad_signal_probe import flat_grad, minibatch_term_losses

    th.manual_seed(3)
    obs_dim, n_actions, batch = 6, 5, 32
    policy = _TinyPolicy(obs_dim, n_actions)
    model = SimpleNamespace(
        policy=policy, action_space=spaces.Discrete(n_actions), clip_range=lambda _p: 0.2,
        _current_progress_remaining=1.0, normalize_advantage=True, clip_range_vf=None,
        vf_coef=0.5, ent_coef=0.01, entropy_normalize_by_legal=False,
    )
    obs = th.randn(batch, obs_dim)
    actions = th.randint(0, n_actions, (batch, 1)).float()
    masks = th.ones(batch, n_actions, dtype=th.bool)
    with th.no_grad():
        _, old_log_prob, _ = policy.evaluate_actions(obs, actions.long().flatten(), action_masks=masks)
    old_log_prob = old_log_prob + 0.1 * th.randn(batch)  # ratios ≠ 1 : le clip mord
    adv_model = th.randn(batch)
    adv_other = th.randn(batch) * 3.0

    def data(advantages):
        return SimpleNamespace(
            observations=obs, actions=actions, action_masks=masks, old_log_prob=old_log_prob,
            advantages=advantages, old_values=th.zeros(batch), returns=th.randn(batch),
        )

    zeros = th.zeros(batch)
    params = list(policy.parameters())
    losses = minibatch_term_losses(model, data(adv_model), zeros, zeros, {0.95: adv_model.clone(), 0.5: adv_other})
    assert set(losses["policy_sweep"]) == {0.95, 0.5}
    assert th.equal(losses["policy_sweep"][0.95], losses["policy"])
    direct = minibatch_term_losses(model, data(adv_other), zeros, zeros)
    assert direct["policy_sweep"] == {}
    assert th.equal(losses["policy_sweep"][0.5], direct["policy"])
    # VERT VACANT : les deux λ donnent des pertes différentes, et leurs gradients aussi.
    assert not th.equal(losses["policy_sweep"][0.5], losses["policy"])
    g_sweep = flat_grad(losses["policy_sweep"][0.5], params, retain_graph=True)
    g_direct = flat_grad(direct["policy"], params, retain_graph=False)
    g_model = flat_grad(losses["policy"], params, retain_graph=False)
    assert th.allclose(g_sweep, g_direct, atol=1e-7) and g_sweep.abs().max() > 0
    assert not th.allclose(g_sweep, g_model)


def test_un_checkpoint_a_tete_q_est_refuse_par_la_sonde():
    """Sous `advantage_source='q_head'` (S14), `train` n'applique pas le terme policy que la sonde
    construit sur les avantages GAE et ajoute un terme Q qu'elle ignore : la mesure porterait
    un nom faux. Refus explicite, au niveau du mini-lot comme au chargement (`refuse_q_head_model`)."""
    from types import SimpleNamespace

    import pytest
    import torch as th
    from gymnasium import spaces

    from scripts.grad_signal_probe import minibatch_term_losses, refuse_q_head_model

    obs_dim, n_actions, batch = 6, 5, 8
    policy = _TinyPolicy(obs_dim, n_actions)
    base = dict(
        policy=policy, action_space=spaces.Discrete(n_actions), clip_range=lambda _p: 0.2,
        _current_progress_remaining=1.0, normalize_advantage=True, clip_range_vf=None,
        vf_coef=0.5, ent_coef=0.01, entropy_normalize_by_legal=False,
    )
    data = SimpleNamespace(
        observations=th.randn(batch, obs_dim), actions=th.zeros(batch, 1),
        action_masks=th.ones(batch, n_actions, dtype=th.bool), old_log_prob=th.zeros(batch),
        advantages=th.randn(batch), old_values=th.zeros(batch), returns=th.randn(batch),
    )
    zeros = th.zeros(batch)
    with pytest.raises(NotImplementedError, match="q_head"):
        minibatch_term_losses(SimpleNamespace(**base, advantage_source="q_head"), data, zeros, zeros)
    with pytest.raises(NotImplementedError, match="q_head"):
        refuse_q_head_model(SimpleNamespace(advantage_source="q_head"))
    # `gae` explicite et attribut absent (modèle antérieur à S14) passent tous deux.
    refuse_q_head_model(SimpleNamespace(advantage_source="gae"))
    assert "policy" in minibatch_term_losses(SimpleNamespace(**base), data, zeros, zeros)


def test_reset_policy_parameters_change_tout_et_est_reproductible():
    import torch as th

    from scripts.grad_signal_probe import reset_policy_parameters

    def make() -> nn.Module:
        th.manual_seed(1)
        net = nn.Sequential(nn.Linear(6, 5), nn.LayerNorm(5), nn.Linear(5, 2))
        with th.no_grad():
            for p in net.parameters():
                p.add_(3.0)  # « entraîné » loin de l'init
        return net

    a, b = make(), make()
    before = th.cat([p.detach().flatten().clone() for p in a.parameters()])
    assert reset_policy_parameters(a, 7) == 3
    assert reset_policy_parameters(b, 7) == 3
    after_a = th.cat([p.detach().flatten() for p in a.parameters()])
    after_b = th.cat([p.detach().flatten() for p in b.parameters()])
    assert th.equal(after_a, after_b)  # même graine → mêmes poids
    assert float((before != after_a).float().mean()) > 0.99
    # Un module sans reset_parameters garde ses poids : la fonction LÈVE.
    class Frozen(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.w = nn.Parameter(th.ones(50))

    with pytest.raises(RuntimeError):
        reset_policy_parameters(nn.Sequential(nn.Linear(2, 2), Frozen()), 7)


def test_acceptation_plomberie_ne_juge_que_la_part_pool():
    from scripts.grad_signal_probe import PLUMBING_ACCEPTANCE_KEYS, check_acceptance

    ok = {"pool_episode_share": 0.68, "explained_variance": -5.0, "grad_norm_policy_mb0": 9.0}
    assert check_acceptance(ok, keys=PLUMBING_ACCEPTANCE_KEYS) == []
    failures = check_acceptance({"pool_episode_share": 0.2}, keys=PLUMBING_ACCEPTANCE_KEYS)
    assert len(failures) == 1 and failures[0].startswith("pool_episode_share")


def _done_info(winner: int | None, controlled: int = 1, truncated: bool = False, **extra) -> dict:
    return {"episode": {"l": 90, "r": 1.0}, "opponent_mode": "self_play", "winner": winner,
            "controlled_player": controlled, "TimeLimit.truncated": truncated, "action": "wait", **extra}


def test_recorder_score_les_issues_et_leve_sur_une_troncature_du_moteur():
    """Le moteur ne rend jamais `winner = None` : sa limite anti-runaway pose un NUL avec
    `truncated = True`. Le signal gym `TimeLimit.truncated` est le seul discriminant ; sans lui,
    l'épisode tronqué passait pour un nul et le bootstrap replié dans sa récompense entrait dans
    Var(r)."""
    from engine.constants import DRAW_WINNER
    from scripts.grad_signal_probe import OUTCOME_REWARD, make_recorder

    rec = make_recorder(3)
    rec.locals = {"dones": np.array([True, False, True]),
                  "infos": [_done_info(1), {"TimeLimit.truncated": False, "action": "ingress_move"}, _done_info(2)]}
    assert rec._on_step() is True
    rec.locals = {"dones": np.array([False, True, False]),
                  "infos": [{"TimeLimit.truncated": False}, _done_info(DRAW_WINNER), {"TimeLimit.truncated": False}]}
    rec._on_step()
    dones, outcomes, setting_up = rec.arrays()
    assert dones.shape == (2, 3) and outcomes[0].tolist() == [OUTCOME_REWARD, 0.0, -OUTCOME_REWARD]
    assert outcomes[1].tolist() == [0.0, 0.0, 0.0]
    assert setting_up.tolist() == [[False, True, False], [False, False, False]]
    assert rec.episodes_total == 3 and rec.episodes_pool == 3 and rec.episode_lengths == [90, 90, 90]
    # Un nul par limite anti-runaway est TRONQUÉ : levée avec le diagnostic du moteur, jamais scoré.
    debug = {"turn": 4, "phase": "move", "steps": 5000}
    rec.locals = {"dones": np.array([False, True, False]),
                  "infos": [{"TimeLimit.truncated": False}, _done_info(
                      DRAW_WINNER, truncated=True, win_method="step_limit",
                      truncation_reason="episode_steps_limit", truncation_debug=debug), {"TimeLimit.truncated": False}]}
    with pytest.raises(RuntimeError, match="step_limit.*'steps': 5000"):
        rec._on_step()
    # Un vainqueur None sur un épisode fini viole le contrat du moteur : levée, pas comptée.
    rec.locals = {"dones": np.array([True, False, False]),
                  "infos": [_done_info(None), {"TimeLimit.truncated": False}, {"TimeLimit.truncated": False}]}
    with pytest.raises(RuntimeError):
        rec._on_step()
    rec._on_rollout_start()
    assert rec.episodes_total == 0 and rec.dones == []


def test_la_sonde_applique_la_temperature_du_profil_au_checkpoint():
    """S9 : `logits_temperature` est un régime de run exclu du zip ; la sonde doit mesurer π_T
    comme le run, donc poser la valeur du PROFIL sur le modèle rechargé (1,0 si absente)."""
    from types import SimpleNamespace

    from scripts.grad_signal_probe import apply_run_temperature

    messages: list[str] = []
    model = SimpleNamespace(logits_temperature=1.0)
    assert apply_run_temperature(model, {"logits_temperature": 2.0}, messages.append) == 2.0
    assert model.logits_temperature == 2.0 and any("T = 2.0" in m for m in messages)
    other = SimpleNamespace(logits_temperature=1.0)
    assert apply_run_temperature(other, {}, messages.append) == 1.0
    assert other.logits_temperature == 1.0

