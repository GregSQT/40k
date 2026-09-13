"""Statistiques de `scripts/grad_signal_probe.py` sur des gradients SYNTHÉTIQUES.

Chaque test construit ses K « gradients de rollouts » avec un gradient vrai et un bruit connus,
donc une valeur attendue calculable à la main : sans bruit f = 1, bruit pur f ≈ 0, ‖G‖² sans biais
retrouve ‖μ‖² là où la moyenne des carrés de norme le surestime, et tout est invariant d'échelle.
"""
from __future__ import annotations

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
