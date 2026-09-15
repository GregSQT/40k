"""Tests — sonde de STRUCTURE de la tête Q (scripts/q_head_structure_probe.py, §5.13.1).

Sur des vecteurs CONSTRUITS (offset connu, part centrée connue, résidu connu), la décomposition
retrouve chaque part, sa somme est exacte, et les parts de variance sont celles de la
construction ; `summarize` pool par nombre de pas et rend des intervalles jackknife ;
`require_q_head_model` refuse un checkpoint `gae` (miroir de `refuse_q_head_model`).
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from scripts.grad_signal_probe import refuse_q_head_model
from scripts.q_head_structure_probe import (
    ROLLOUT_STATS,
    decompose,
    pooled,
    require_q_head_model,
    summarize,
)


def _construct(seed: int, n: int = 20_000, sd_offset: float = 0.222, sd_centered: float = 0.027,
               sd_noise: float = 0.5) -> dict[str, np.ndarray]:
    """A = c + A_c avec c ⊥ A_c ; R = c + bruit : l'offset PRÉDIT le résidu, la part centrée non."""
    rng = np.random.default_rng(seed)
    c = rng.normal(0.0, sd_offset, n)
    a_c = rng.normal(0.0, sd_centered, n)
    noise = rng.normal(0.0, sd_noise, n)
    values = rng.normal(1.0, 0.3, n)
    returns = values + c + noise
    return {
        "returns": returns, "values": values, "adv": c + a_c, "offset": c,
        "sd_within": np.full(n, sd_centered),
        "c": c, "a_c": a_c,
    }


def test_la_decomposition_somme_exactement_et_retrouve_chaque_part() -> None:
    d = _construct(1)
    s = decompose(d["returns"], d["values"], d["adv"], d["offset"], d["sd_within"])
    r = d["returns"] - d["values"]
    assert s["gap"] == pytest.approx(s["q_loss"] - s["value_loss"])
    assert s["gap"] == pytest.approx(s["gap_offset"] + s["gap_centered"] + s["gap_cross"], abs=1e-12)
    assert s["gap_offset"] == pytest.approx(float(np.mean(d["c"] ** 2 - 2 * d["c"] * r)))
    assert s["gap_centered"] == pytest.approx(float(np.mean(d["a_c"] ** 2 - 2 * d["a_c"] * r)))
    # L'offset prédit le résidu (R = c + bruit) : sa part vaut −E[c²] < 0 ; la part centrée est
    # du bruit pur : +E[A_c²] > 0.
    assert s["gap_offset"] == pytest.approx(-float(np.mean(d["c"] ** 2)), abs=3 * 0.222 * 0.5 * 2 / np.sqrt(20_000))
    assert s["gap_offset"] < 0
    assert s["gap_centered"] > 0
    assert s["gap_centered"] == pytest.approx(0.027 ** 2, abs=3 * 0.027 * 0.5 * 2 / np.sqrt(20_000))


def test_les_parts_de_variance_sont_celles_de_la_construction() -> None:
    d = _construct(2)
    s = decompose(d["returns"], d["values"], d["adv"], d["offset"], d["sd_within"])
    assert s["var_a"] == pytest.approx(s["var_offset"] + s["var_centered"] + 2 * s["cov_offset_centered"], rel=1e-9)
    share = s["var_offset"] / s["var_a"]
    expected = 0.222 ** 2 / (0.222 ** 2 + 0.027 ** 2)  # 0,985
    assert share == pytest.approx(expected, abs=0.01)
    assert np.sqrt(s["var_offset"]) == pytest.approx(0.222, abs=0.01)
    assert s["sd_within"] == pytest.approx(0.027)
    assert s["abs_offset"] > s["abs_centered"] > 0.0


def test_un_offset_nul_met_tout_dans_la_part_centree() -> None:
    d = _construct(3, sd_offset=0.0)
    s = decompose(d["returns"], d["values"], d["adv"], d["offset"], d["sd_within"])
    assert s["gap_offset"] == 0.0 and s["gap_cross"] == 0.0 and s["var_offset"] == 0.0
    assert s["gap"] == pytest.approx(s["gap_centered"])


def test_decompose_refuse_des_formes_incoherentes() -> None:
    v = np.zeros(5)
    with pytest.raises(ValueError, match="formes"):
        decompose(v, v, np.zeros(4), v, v)
    with pytest.raises(ValueError, match="formes"):
        decompose(v, v, np.zeros((5, 1)), v, v)
    one = np.zeros(1)
    with pytest.raises(ValueError, match="2 pas"):
        decompose(one, one, one, one, one)


def test_summarize_pool_par_nombre_de_pas_et_rend_des_intervalles_jackknife() -> None:
    rows = []
    for seed, n in ((10, 4000), (11, 8000), (12, 6000)):
        d = _construct(seed, n=n)
        s = decompose(d["returns"], d["values"], d["adv"], d["offset"], d["sd_within"])
        rows.append([s[name] for name in ROLLOUT_STATS])
    per_rollout = np.asarray(rows)
    out = summarize(per_rollout)
    assert out["rollouts"] == 3 and out["n_steps_total"] == 18_000
    n = per_rollout[:, ROLLOUT_STATS.index("n_steps")]
    gap_col = per_rollout[:, ROLLOUT_STATS.index("gap")]
    assert out["gap"]["estimate"] == pytest.approx(float(np.sum(gap_col * n) / np.sum(n)))
    assert pooled(per_rollout, np.array([0, 2]), "gap") == pytest.approx(
        float((gap_col[0] * n[0] + gap_col[2] * n[2]) / (n[0] + n[2]))
    )
    for key in ("gap", "gap_offset", "gap_centered", "offset_var_share", "sd_offset_over_sd_within"):
        stat = out[key]
        assert np.isfinite(stat["se"]) and stat["low"] <= stat["estimate"] <= stat["high"], key
    assert out["gap_offset"]["high"] < 0.0, "VERT VACANT : l'offset construit prédit le résidu"
    assert out["gap_centered"]["low"] > 0.0
    assert out["offset_var_share"]["estimate"] == pytest.approx(0.985, abs=0.01)
    assert out["sd_offset_over_sd_within"]["estimate"] == pytest.approx(0.222 / 0.027, rel=0.05)
    with pytest.raises(ValueError, match="colonnes"):
        summarize(per_rollout[:, :3])


def test_require_q_head_model_est_le_miroir_du_refus() -> None:
    require_q_head_model(SimpleNamespace(advantage_source="q_head"))
    with pytest.raises(ValueError, match="q_head"):
        require_q_head_model(SimpleNamespace(advantage_source="gae"))
    with pytest.raises(ValueError, match="q_head"):
        require_q_head_model(SimpleNamespace())
    # La sonde de gradient garde son refus : les deux gardes sont complémentaires, jamais
    # satisfaites par le même checkpoint.
    with pytest.raises(NotImplementedError):
        refuse_q_head_model(SimpleNamespace(advantage_source="q_head"))
    refuse_q_head_model(SimpleNamespace(advantage_source="gae"))
