"""Tests — log_abilities_metrics (W40KMetricsTracker).

Trois invariants verrouillés :

1. TAGS ÉMIS — chaque règle×camp produit une courbe de count et une courbe
   d'exposure_rate sous le préfixe `abilities/`.

2. ACCUMULATION — l'exposure_rate est un TAUX CUMULÉ (n_épisodes_exposés / total) ;
   un deuxième épisode non exposé fait descendre le taux.

3. REQUIRE_KEY — retirer `abilities_counts` de tactical_data lève KeyError (verrou
   anti-données-manquantes, pattern de tous les compteurs moteur).
"""

from collections import defaultdict
from typing import Any, Dict, List, Tuple

import pytest

from ai.metrics_tracker import W40KMetricsTracker
from shared.data_validation import ConfigurationError


# ──────────────────────────────────────────────────────────────────────────────
# Harnais minimal
# ──────────────────────────────────────────────────────────────────────────────

class _RecordingWriter:
    """SummaryWriter stub : conserve l'historique complet."""

    def __init__(self) -> None:
        self.history: List[Tuple[str, float, int]] = []

    def add_scalar(self, tag: str, value: Any, step: int) -> None:
        self.history.append((tag, float(value), int(step)))

    def latest(self, tag: str) -> float:
        vals = [v for t, v, _ in self.history if t == tag]
        if not vals:
            raise AssertionError(f"tag jamais émis : {tag!r}")
        return vals[-1]

    def count_emissions(self, tag: str) -> int:
        return sum(1 for t, _, _ in self.history if t == tag)


def _tracker() -> Tuple[W40KMetricsTracker, _RecordingWriter]:
    """Tracker initialisé avec uniquement l'état abilities — évite les dépendances lourdes."""
    t = W40KMetricsTracker.__new__(W40KMetricsTracker)
    writer = _RecordingWriter()
    t.writer = writer  # type: ignore[assignment]
    # État nécessaire pour log_abilities_metrics.
    t._abilities_tracking = {'total_episodes': 0, 'counts': defaultdict(int), 'exposures': defaultdict(int)}
    t.episode_count = 0
    return t, writer


def _abilities_data(
    *,
    reactive_move_agent: int = 0,
    reactive_move_opp: int = 0,
    charge_impact_agent: int = 0,
    charge_impact_opp: int = 0,
    charge_after_advance_agent: int = 0,
    charge_after_advance_opp: int = 0,
    charge_after_flee_agent: int = 0,
    charge_after_flee_opp: int = 0,
    move_after_shooting_agent: int = 0,
    move_after_shooting_opp: int = 0,
    hit_reroll_agent: int = 0,
    hit_reroll_opp: int = 0,
    wound_reroll_agent: int = 0,
    wound_reroll_opp: int = 0,
    oath_wound_bonus_agent: int = 0,
    oath_wound_bonus_opp: int = 0,
    # Exposition (0 ou 1 par règle×camp)
    reactive_move_agent_exp: int = 0,
    reactive_move_opp_exp: int = 0,
    charge_impact_agent_exp: int = 0,
    charge_impact_opp_exp: int = 0,
    charge_after_advance_agent_exp: int = 0,
    charge_after_advance_opp_exp: int = 0,
    charge_after_flee_agent_exp: int = 0,
    charge_after_flee_opp_exp: int = 0,
    move_after_shooting_agent_exp: int = 0,
    move_after_shooting_opp_exp: int = 0,
    hit_reroll_agent_exp: int = 0,
    hit_reroll_opp_exp: int = 0,
    wound_reroll_agent_exp: int = 0,
    wound_reroll_opp_exp: int = 0,
    oath_wound_bonus_agent_exp: int = 0,
    oath_wound_bonus_opp_exp: int = 0,
) -> Dict[str, Any]:
    return {
        'abilities_counts': {
            'reactive_move_agent': reactive_move_agent,
            'reactive_move_opp': reactive_move_opp,
            'charge_impact_agent': charge_impact_agent,
            'charge_impact_opp': charge_impact_opp,
            'charge_after_advance_agent': charge_after_advance_agent,
            'charge_after_advance_opp': charge_after_advance_opp,
            'charge_after_flee_agent': charge_after_flee_agent,
            'charge_after_flee_opp': charge_after_flee_opp,
            'move_after_shooting_agent': move_after_shooting_agent,
            'move_after_shooting_opp': move_after_shooting_opp,
            'hit_reroll_agent': hit_reroll_agent,
            'hit_reroll_opp': hit_reroll_opp,
            'wound_reroll_agent': wound_reroll_agent,
            'wound_reroll_opp': wound_reroll_opp,
            'oath_wound_bonus_agent': oath_wound_bonus_agent,
            'oath_wound_bonus_opp': oath_wound_bonus_opp,
        },
        'abilities_exposure': {
            'reactive_move_agent': reactive_move_agent_exp,
            'reactive_move_opp': reactive_move_opp_exp,
            'charge_impact_agent': charge_impact_agent_exp,
            'charge_impact_opp': charge_impact_opp_exp,
            'charge_after_advance_agent': charge_after_advance_agent_exp,
            'charge_after_advance_opp': charge_after_advance_opp_exp,
            'charge_after_flee_agent': charge_after_flee_agent_exp,
            'charge_after_flee_opp': charge_after_flee_opp_exp,
            'move_after_shooting_agent': move_after_shooting_agent_exp,
            'move_after_shooting_opp': move_after_shooting_opp_exp,
            'hit_reroll_agent': hit_reroll_agent_exp,
            'hit_reroll_opp': hit_reroll_opp_exp,
            'wound_reroll_agent': wound_reroll_agent_exp,
            'wound_reroll_opp': wound_reroll_opp_exp,
            'oath_wound_bonus_agent': oath_wound_bonus_agent_exp,
            'oath_wound_bonus_opp': oath_wound_bonus_opp_exp,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# 1. Tags émis
# ──────────────────────────────────────────────────────────────────────────────

def test_tags_emis_par_regle() -> None:
    """Chaque règle×camp produit un tag count et un tag exposure_rate."""
    t, writer = _tracker()
    t.log_abilities_metrics(_abilities_data(reactive_move_agent=2, reactive_move_agent_exp=1))

    assert writer.latest("abilities/reactive_move_agent") == 2.0
    assert writer.latest("abilities/reactive_move_agent_exposure_rate") == 1.0


def test_toutes_les_regles_emettent_un_count() -> None:
    """Toutes les règles (y compris à 0) émettent leur courbe de count."""
    t, writer = _tracker()
    t.log_abilities_metrics(_abilities_data())
    expected_count_tags = {
        "abilities/reactive_move_agent", "abilities/reactive_move_opp",
        "abilities/charge_impact_agent", "abilities/charge_impact_opp",
        "abilities/charge_after_advance_agent", "abilities/charge_after_advance_opp",
        "abilities/charge_after_flee_agent", "abilities/charge_after_flee_opp",
        "abilities/move_after_shooting_agent", "abilities/move_after_shooting_opp",
        "abilities/hit_reroll_agent", "abilities/hit_reroll_opp",
        "abilities/wound_reroll_agent", "abilities/wound_reroll_opp",
        "abilities/oath_wound_bonus_agent", "abilities/oath_wound_bonus_opp",
    }
    emitted = {tag for tag, _, _ in writer.history}
    for tag in expected_count_tags:
        assert tag in emitted, f"tag manquant : {tag!r}"


def test_toutes_les_regles_emettent_un_exposure_rate() -> None:
    """Toutes les règles émettent leur courbe d'exposure_rate."""
    t, writer = _tracker()
    t.log_abilities_metrics(_abilities_data())
    expected_exposure_tags = {
        "abilities/reactive_move_agent_exposure_rate",
        "abilities/reactive_move_opp_exposure_rate",
        "abilities/charge_impact_agent_exposure_rate",
        "abilities/charge_impact_opp_exposure_rate",
        "abilities/charge_after_advance_agent_exposure_rate",
        "abilities/charge_after_advance_opp_exposure_rate",
        "abilities/charge_after_flee_agent_exposure_rate",
        "abilities/charge_after_flee_opp_exposure_rate",
        "abilities/move_after_shooting_agent_exposure_rate",
        "abilities/move_after_shooting_opp_exposure_rate",
        "abilities/hit_reroll_agent_exposure_rate",
        "abilities/hit_reroll_opp_exposure_rate",
        "abilities/wound_reroll_agent_exposure_rate",
        "abilities/wound_reroll_opp_exposure_rate",
        "abilities/oath_wound_bonus_agent_exposure_rate",
        "abilities/oath_wound_bonus_opp_exposure_rate",
    }
    emitted = {tag for tag, _, _ in writer.history}
    for tag in expected_exposure_tags:
        assert tag in emitted, f"tag manquant : {tag!r}"


# ──────────────────────────────────────────────────────────────────────────────
# 2. Accumulation de l'exposure_rate
# ──────────────────────────────────────────────────────────────────────────────

def test_exposure_rate_cumule_sur_plusieurs_episodes() -> None:
    """
    VERROU 2 : l'exposure_rate est un taux cumulé, pas la valeur de l'épisode.

    Épisode 1 : exposé → taux = 1/1 = 1.0
    Épisode 2 : non exposé → taux = 1/2 = 0.5
    """
    t, writer = _tracker()
    t.log_abilities_metrics(_abilities_data(charge_impact_agent_exp=1))
    assert writer.latest("abilities/charge_impact_agent_exposure_rate") == 1.0

    t.episode_count += 1
    t.log_abilities_metrics(_abilities_data(charge_impact_agent_exp=0))
    assert writer.latest("abilities/charge_impact_agent_exposure_rate") == 0.5


def test_counts_cumulent_mean() -> None:
    """Le count brut est émis par épisode (pas cumulé) — chaque épisode repart à 0."""
    t, writer = _tracker()
    t.log_abilities_metrics(_abilities_data(reactive_move_agent=3))
    assert writer.latest("abilities/reactive_move_agent") == 3.0

    t.episode_count += 1
    t.log_abilities_metrics(_abilities_data(reactive_move_agent=0))
    assert writer.latest("abilities/reactive_move_agent") == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# 3. Clé manquante → KeyError (verrou anti-données-manquantes)
# ──────────────────────────────────────────────────────────────────────────────

def test_leve_si_abilities_counts_absent() -> None:
    """VERROU 3 : données manquantes → erreur bruyante (ConfigurationError via require_key)."""
    t, _ = _tracker()
    with pytest.raises((KeyError, ConfigurationError)):
        t.log_abilities_metrics({'abilities_exposure': {}})


def test_leve_si_abilities_exposure_absent() -> None:
    t, _ = _tracker()
    with pytest.raises((KeyError, ConfigurationError)):
        t.log_abilities_metrics({'abilities_counts': {}})


def test_leve_si_exposure_hors_domaine() -> None:
    """exposure doit être 0 ou 1 — une valeur de 2 lève."""
    t, _ = _tracker()
    data = _abilities_data()
    data['abilities_exposure']['reactive_move_agent'] = 2  # invalide
    with pytest.raises(ValueError):
        t.log_abilities_metrics(data)
