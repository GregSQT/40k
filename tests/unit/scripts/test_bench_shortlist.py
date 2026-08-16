"""Invariants de scripts/bench_shortlist.py.

INVARIANTS VÉRIFIÉS
--------------------
1. K = référence (24) → taux = 0 pour tout bot, tout scénario.
2. Bots sans terme de tir (w_fire = w_risk = 0) exclus des résultats.
3. K ≥ n_candidats → taux = 0 (shortlist ne coupe rien).
4. _decision restaure DESTINATION_SHORTLIST après l'appel (idempotent).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import ai.bot_doctrines as doc
import bench_shortlist as bench


# ── Fixtures ──────────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _patch_damage():
    """Patch _damage_on avant chaque test ; restaure à la fin."""
    orig = doc._damage_on
    bench._install_damage_patch()
    yield
    doc._damage_on = orig


def _simple_state(
    unit_col: int = 15,
    unit_row: int = 15,
    enemy_col: int = 30,
    enemy_row: int = 15,
    my_rng: int = 24,
    enemy_rng: int = 12,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(state, unit_dict) minimal reproductible."""
    state = bench._make_state(
        unit_col, unit_row,
        [(enemy_col, enemy_row)],
        my_rng, enemy_rng,
    )
    unit = state["unit_by_id"]["A"]
    return state, unit


# ── Invariant 1 : K = référence → taux = 0 ────────────────────────────────────────────────────

def test_reference_shortlist_produces_zero_divergence() -> None:
    """K=24 vs ref=24 : chaque bot doit toujours choisir la même destination."""
    results = bench.run_bench(
        shortlists=[bench.REFERENCE_SHORTLIST],
        n_episodes=30,
        rng_seed=0,
    )
    for scen_name, scen_data in results.items():
        for bot_name, ks in scen_data.items():
            rate = ks.get(bench.REFERENCE_SHORTLIST, 0.0)
            assert rate == 0.0, (
                f"scénario={scen_name} bot={bot_name} K=ref → taux attendu 0, obtenu {rate}"
            )


# ── Invariant 2 : bots sans terme de tir exclus ────────────────────────────────────────────────

def test_zero_fire_bots_excluded_from_results() -> None:
    """RacerBot et AlphaStrikeBot (w_fire=0, w_risk=0) n'apparaissent dans aucun résultat."""
    results = bench.run_bench(shortlists=[8], n_episodes=20, rng_seed=1)
    zero_fire_bots = {"RacerBot", "AlphaStrikeBot"}
    for scen_name, scen_data in results.items():
        found = zero_fire_bots & set(scen_data)
        assert not found, (
            f"scénario={scen_name} : bots sans terme de tir trouvés dans les résultats : {found}"
        )


def test_w_fire_nonzero_returns_false_for_racer() -> None:
    """_w_fire_nonzero détecte correctement un bot sans terme de tir."""
    state, unit = _simple_state()
    bot = doc.RacerBot()
    assert not bench._w_fire_nonzero(bot, state, unit)


def test_w_fire_nonzero_returns_true_for_scorer() -> None:
    """_w_fire_nonzero détecte correctement un bot avec terme de tir."""
    state, unit = _simple_state()
    bot = doc.ScorerBot()
    assert bench._w_fire_nonzero(bot, state, unit)


# ── Invariant 3 : K ≥ n_candidats → taux = 0 ──────────────────────────────────────────────────

def test_shortlist_at_least_as_large_as_pool_gives_zero_divergence() -> None:
    """Quand K ≥ len(candidates), tous les candidats sont évalués : même résultat que K=ref."""
    state, unit = _simple_state()
    # Grille minimale : radius=1, max 8 candidats
    candidates = bench._candidate_grid(15, 15, radius=1)
    assert len(candidates) <= 8, f"rayon=1 devrait donner ≤ 8 candidats, obtenu {len(candidates)}"

    bot = doc.ScorerBot()
    # K=8 ≥ len(candidates) : le shortlist ne coupe rien, la décision est identique à K=24
    ref = bench._decision(bot, state, unit, candidates, bench.REFERENCE_SHORTLIST)
    small_k = bench._decision(bot, state, unit, candidates, 8)
    assert ref == small_k, (
        f"K=8 ≥ {len(candidates)} candidats : attendu {ref}, obtenu {small_k}"
    )


def test_candidate_grid_size_grows_with_radius() -> None:
    """La grille de candidats est strictement plus grande avec un rayon plus grand (bord interne)."""
    small = bench._candidate_grid(20, 20, radius=2)
    large = bench._candidate_grid(20, 20, radius=3)
    assert len(small) < len(large)


# ── Invariant 4 : _decision restaure DESTINATION_SHORTLIST ─────────────────────────────────────

def test_decision_restores_shortlist_after_call() -> None:
    """DESTINATION_SHORTLIST revient à sa valeur initiale même après l'appel."""
    state, unit = _simple_state()
    candidates = bench._candidate_grid(15, 15)
    bot = doc.ScorerBot()
    original = doc.DESTINATION_SHORTLIST
    try:
        bench._decision(bot, state, unit, candidates, 8)
        assert doc.DESTINATION_SHORTLIST == original, (
            f"après _decision(K=8), DESTINATION_SHORTLIST vaut {doc.DESTINATION_SHORTLIST} "
            f"au lieu de {original}"
        )
    finally:
        doc.DESTINATION_SHORTLIST = original


def test_decision_restores_shortlist_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """DESTINATION_SHORTLIST revient à sa valeur initiale même si select_movement_destination lève."""
    state, unit = _simple_state()
    candidates = bench._candidate_grid(15, 15)
    bot = doc.ScorerBot()
    original = doc.DESTINATION_SHORTLIST

    monkeypatch.setattr(
        bot, "select_movement_destination",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("injection de test")),
    )
    try:
        with pytest.raises(RuntimeError):
            bench._decision(bot, state, unit, candidates, 8)
        assert doc.DESTINATION_SHORTLIST == original, (
            f"après exception, DESTINATION_SHORTLIST vaut {doc.DESTINATION_SHORTLIST} "
            f"au lieu de {original}"
        )
    finally:
        doc.DESTINATION_SHORTLIST = original
