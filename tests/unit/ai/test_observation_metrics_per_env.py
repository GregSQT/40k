"""Tests — les metriques d'observation par phase sont accumulees PAR ENVIRONNEMENT.

CE QUI A ETE MANQUE. `MetricsCollectionCallback` accumulait les echantillons d'observation
(meilleure probabilite de kill, danger, nombre de cibles) dans un dictionnaire UNIQUE, alimente
par les 48 environnements et vide par celui qui terminait son episode le premier. Les courbes
`obs/*` melangeaient donc 48 parties et perdaient tout ce qui n'avait pas ete publie a temps.

POURQUOI AUCUN TEST NE L'A VU : aucun ne pilotait `_on_step` avec plus d'un environnement.
Avec un seul env, le defaut est invisible.
"""

from __future__ import annotations

from typing import Any, Dict, List, cast

import numpy as np
import pytest

import ai.training_callbacks as training_callbacks


class _RecordingTracker:
    """Doublure du tracker : conserve chaque publication."""

    def __init__(self) -> None:
        self.published_observations: List[Dict[str, Dict[str, List[float]]]] = []

    def log_observation_phase_metrics(
        self, phase_metrics: Dict[str, Dict[str, List[float]]]
    ) -> None:
        self.published_observations.append(
            {phase: {k: list(v) for k, v in data.items()} for phase, data in phase_metrics.items()}
        )


def _callback() -> Any:
    """Callback reel, sans __init__ : seuls les attributs du chemin teste sont poses.

    Idiome de tests/unit/ai/test_final_eval_uses_holdout.py — le vrai code s'execute, mais on
    n'a pas a monter un modele SB3 pour observer une accumulation.
    """
    cb = training_callbacks.MetricsCollectionCallback.__new__(
        training_callbacks.MetricsCollectionCallback
    )
    cb.metrics_tracker = _RecordingTracker()
    # `_on_step` interroge le modele par `hasattr` a la fin (learning_rate, logger) : un objet
    # nu suffit, il n'expose ni l'un ni l'autre.
    cb.model = cast(Any, object())
    cb.episode_tactical_data = {'valid_actions': 0, 'invalid_actions': 0,
                                'total_actions': 0, 'wait_actions': 0}
    cb.episode_observation_phase_data_by_env = {}
    return cb


def _step(cb: Any, infos: List[Dict[str, Any]], obs: Any = None) -> None:
    """Un pas de VecEnv passe par le vrai `_on_step`."""
    cb.locals = {'infos': infos}
    if obs is not None:
        cb.locals['new_obs'] = obs
    cb._on_step()


def _observed(cb: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Remplace l'extraction par un marqueur lisible : la 1ere valeur du vecteur d'obs.

    Ce qui est teste ici est l'AIGUILLAGE par environnement, pas le decodage du vecteur
    d'observation (couvert ailleurs) : un marqueur rend l'assertion lisible et n'oblige pas a
    fabriquer un vecteur de 313 cases realiste.
    """
    monkeypatch.setattr(
        type(cb), '_extract_valid_target_metrics_from_obs',
        lambda self, obs_vector: {
            'best_kill_probability': [float(obs_vector[0])],
            'danger_to_me': [], 'valid_target_count': [],
        },
    )


def test_observation_metrics_are_accumulated_per_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chaque env accumule SES observations : un dict unique melangeait les 48 parties."""
    cb = _callback()
    _observed(cb, monkeypatch)

    _step(
        cb,
        [{'is_controlled_action': True, 'phase': 'shoot'},
         {'is_controlled_action': True, 'phase': 'shoot'}],
        obs=np.array([[1.0] * 4, [2.0] * 4]),
    )

    by_env = cb.episode_observation_phase_data_by_env
    assert by_env[0]['shoot']['best_kill_probability'] == [pytest.approx(1.0)]
    assert by_env[1]['shoot']['best_kill_probability'] == [pytest.approx(2.0)]


def test_observation_flush_touches_only_the_ending_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La fin d'episode d'un env ne vide pas les observations des autres."""
    cb = _callback()
    _observed(cb, monkeypatch)

    _step(
        cb,
        [{'is_controlled_action': True, 'phase': 'shoot'},
         {'is_controlled_action': True, 'phase': 'shoot'}],
        obs=np.array([[1.0] * 4, [2.0] * 4]),
    )
    cb._flush_observation_phase_data(0)

    published = cb.metrics_tracker.published_observations
    assert len(published) == 1
    assert published[0]['shoot']['best_kill_probability'] == [pytest.approx(1.0)]
    assert cb.episode_observation_phase_data_by_env[0]['shoot']['best_kill_probability'] == []
    assert cb.episode_observation_phase_data_by_env[1]['shoot']['best_kill_probability'] == [
        pytest.approx(2.0)
    ], "l'env 1 est au milieu de son episode : ses observations doivent survivre"
