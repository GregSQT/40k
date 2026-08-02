"""Verrou de la SOURCE UNIQUE des rampes par-épisode (`engine/episode_schedule.py`).

Cette formule vivait en quatre exemplaires manuscrits, dont deux faux (V11 §0.57). Les tests des
consommateurs (moteur, wrapper self-play, callback roster) vérifient qu'ils l'appellent ; celui-ci
verrouille ce qu'elle rend.
"""

from __future__ import annotations

import pytest

from engine.episode_schedule import episodes_per_env, ramp_progress
from shared.data_validation import ConfigurationError


def test_episodes_per_env_rounds_up() -> None:
    """Arrondi SUPÉRIEUR : à l'arrondi inférieur, les derniers épisodes du run sortent de la rampe."""
    assert episodes_per_env(40, 4) == 10
    assert episodes_per_env(41, 4) == 11
    assert episodes_per_env(200000, 48) == 4167
    assert episodes_per_env(3, 48) == 1


def test_ramp_progress_spans_the_whole_per_env_budget() -> None:
    """Premier épisode = 0.0, dernier = 1.0, dans l'échelle d'UN environnement."""
    assert ramp_progress(0, 40, 4) == pytest.approx(0.0)
    assert ramp_progress(9, 40, 4) == pytest.approx(1.0)
    assert ramp_progress(4, 40, 4) == pytest.approx(4 / 9)
    # Au-delà du budget, la rampe reste bornée (un run peut dépasser son total visé).
    assert ramp_progress(999, 40, 4) == pytest.approx(1.0)


def test_ramp_progress_reproduces_the_measured_run() -> None:
    """Point de mesure de x1_long : 78 477 épisodes globaux / 48 envs, rampe 0.3 → 0.8."""
    progress = ramp_progress(78477 // 48, 200000, 48)
    assert 0.3 + 0.5 * progress == pytest.approx(0.496, abs=0.005)


@pytest.mark.parametrize("total,n_envs", [(0, 4), (40, 0), (40, None), (None, 4), (40, True), (40, 1.5)])
def test_invalid_budgets_are_explicit_errors(total, n_envs) -> None:
    """Aucune valeur par défaut : un budget absent ou absurde lève, il ne se devine pas.

    `True` est inclus : `bool` hérite d'`int`, donc `n_envs=True` passerait pour 1 sans exclusion.
    """
    with pytest.raises(ConfigurationError):
        episodes_per_env(total, n_envs)
