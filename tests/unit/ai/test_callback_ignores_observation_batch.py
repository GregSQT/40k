"""Verrou — le callback de metriques ne relit JAMAIS le batch d'observation.

`MetricsCollectionCallback._on_step` lisait `locals['new_obs']` pour en extraire des metriques
`obs/<phase>_*`, sur un layout d'observation PLAT disparu depuis la migration aux entites.

POURQUOI CA N'A PAS SAUTE PLUS TOT — le piege que ce fichier verrouille. La branche etait gardee
par `info['phase'] in ('shoot','fight','charge')`, garde qu'aucune action d'agent ne satisfaisait
alors : le lecteur paraissait atteint en revue, il ne l'etait pas en rollout. `select_activation`
(V11 L2) est la premiere a porter `phase="shoot"` — elle a tue le run des la premiere phase de
tir. Mesures et arbitrage : `Documentation/Chantiers/v11/V11_agent_rework.md` §0.68.

Ce fichier verifie que `_on_step` traverse ce cas exact — observation `Dict`, action d'agent en
phase de tir — sans lever, et que la classe n'expose plus aucun lecteur d'observation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np


class _StubWriter:
    """Writer TensorBoard double : retient les tags ecrits, n'ouvre aucun fichier."""

    def __init__(self) -> None:
        self.scalars: List[str] = []

    def add_scalar(self, tag: str, value: float, step: int) -> None:
        self.scalars.append(tag)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeModel:
    num_timesteps = 1234


def _tracker(tmp_path) -> Tuple[Any, _StubWriter]:
    """Tracker nominal, writer double RENDU A PART.

    Le rendre a part n'est pas une commodite : relu depuis `tracker.writer`, il porte le type
    declare `MetricsWriter`, et l'assertion sur `.scalars` ne passe pas le typage.
    """
    from ai.metrics_tracker import W40KMetricsTracker

    tracker = W40KMetricsTracker(
        "ArmageddonAgent", str(tmp_path), perf_window=10, perf_window_fast=5,
        initial_episode_count=0,
    )
    writer = _StubWriter()
    tracker.writer = writer  # type: ignore[assignment]
    return tracker, writer


def _callback(tmp_path) -> Tuple[Any, _StubWriter]:
    from ai.training_callbacks import MetricsCollectionCallback

    tracker, writer = _tracker(tmp_path)
    return MetricsCollectionCallback(tracker, _FakeModel()), writer


def _dict_observation_batch(n_envs: int = 2) -> Dict[str, np.ndarray]:
    """La FORME de production : un `Dict` d'entites, pas un vecteur plat.

    Les cles et tailles exactes n'ont aucune importance ici — ce qui compte est le TYPE, seul
    responsable du `TypeError`. Les reproduire figerait le contrat d'observation dans un test
    qui ne parle pas de lui.
    """
    return {
        "global_cont": np.zeros((n_envs, 8), dtype=np.float32),
        "enemies_cont": np.zeros((n_envs, 12, 16), dtype=np.float32),
    }


def test_an_agent_action_in_a_shooting_phase_does_not_read_the_observation(tmp_path) -> None:
    """Le cas EXACT qui tuait le run : `select_activation` en phase de tir, observation `Dict`.

    Avant le retrait, cette combinaison levait `TypeError` — c'est la signature de l'incident.
    """
    callback, writer = _callback(tmp_path)
    callback.locals = {  # type: ignore[assignment]
        "new_obs": _dict_observation_batch(),
        "infos": [
            {"is_controlled_action": True, "phase": "shoot", "action": "select_activation"},
            {"is_controlled_action": True, "phase": "fight", "action": "select_activation"},
        ],
        "dones": np.array([False, False]),
    }

    assert callback._on_step() is True, "le callback doit laisser la collecte continuer"
    assert not [tag for tag in writer.scalars if tag.startswith("obs/")], (
        "une courbe `obs/*` est reapparue : elle ne peut venir que d'une relecture du batch"
    )


def test_the_callback_exposes_no_observation_reader(tmp_path) -> None:
    """Anti-recidive : aucun membre du callback ne relit le batch d'observation.

    Le cas ci-dessus ne verrouille qu'un chemin ; celui-ci verrouille l'ABSENCE du mecanisme,
    de sorte qu'un extracteur reintroduit sous un autre garde de phase se fasse voir tout de
    suite plutot qu'au premier run.
    """
    callback, _writer = _callback(tmp_path)
    forbidden = [
        name
        for name in dir(callback)
        if any(token in name for token in ("observation_batch", "valid_target_metrics",
                                           "observation_phase_data", "OBSERVATION_PHASES"))
    ]
    assert forbidden == [], (
        f"lecteurs d'observation reintroduits dans le callback : {forbidden}"
    )


def test_the_tracker_no_longer_publishes_observation_phase_curves(tmp_path) -> None:
    """Jumeau cote tracker : les 12 scalaires `obs/<phase>_*` n'ont plus d'emetteur."""
    tracker, _writer = _tracker(tmp_path)
    assert not hasattr(tracker, "log_observation_phase_metrics"), (
        "le producteur des courbes `obs/*` est de retour sans son consommateur"
    )
