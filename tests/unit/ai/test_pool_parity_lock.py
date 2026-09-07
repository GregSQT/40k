"""Verrou de PARITE a l'ouverture d'une etape reprise a chaud.

CE QUE CE VERROU DIT. Une etape `init: from:<source>` demarre AVEC LES POIDS de `<source>`, et
`<source>` est dans son pool. A l'episode 0, l'agent et cet adversaire sont donc le MEME modele :
son win-rate contre lui vaut 0.50 par IDENTITE, pas par esperance. Un ecart hors fenetre ne peut
pas etre un resultat — c'est une panne d'appariement, et elle est deja la avant le premier
episode d'entrainement : mauvaise archive reprise, `_vec_normalize.pkl` absent ou desapparie,
espace d'observation ou normalisation qui a change entre les deux etapes.

POURQUOI IL ARRETE LE RUN au lieu de le signaler. Les 2026-09-04 et 2026-09-05 ont chacun produit
des heures d'entrainement sur une baseline aberrante lue comme une mesure : 0,477 puis 0,118
contre P1, la ou la parite etait garantie. Un avertissement dans un journal de plusieurs milliers
de lignes n'a arrete ni l'un ni l'autre.

BORNES LARGES, ±0.10 autour de la parite. La sonde est une mesure finie (300 episodes, soit une
erreur-type de 2,9 points pres de 0.5) et le modele repris n'est jamais rejoue bit a bit — le
normalizer continue d'accumuler. 0.40 et 0.60 sont a plus de trois erreurs-types : ce que ce
verrou attrape est une panne, jamais une fluctuation.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from tests.unit.ai._fabriques import pool_early_stopping_callback

# Reprise `from:P1` du run mesure : 80 000 episodes deja joues par l'archive source.
EPISODE_ORIGIN = 80_000


def _tracker(episode_count: int) -> MagicMock:
    tracker = MagicMock()
    tracker.episode_count = episode_count
    return tracker


def _warm_started_callback(tmp_path, **overrides: Any):
    """Callback d'une etape `from:P1`, pool a deux membres (le champion repris + un ancien)."""
    archives = [
        (str(tmp_path / "model_P1.zip"), "P1"),
        (str(tmp_path / "model_P0.zip"), "P0"),
    ]
    for path, _ in archives:
        open(path, "wb").close()
    params: Dict[str, Any] = dict(
        pool_archives=archives,
        stage_name="P2",
        champion_label="P1",
        parity_label="P1",
        parity_range=(0.40, 0.60),
        episode_origin=EPISODE_ORIGIN,
        timesteps_origin=13_749_576,
    )
    params.update(overrides)
    callback = pool_early_stopping_callback(archives[0][0], **params)
    callback.metrics_tracker = _tracker(EPISODE_ORIGIN)
    return callback


def _fake_baseline(callback, scores: Dict[str, float]) -> List[int]:
    """Branche `_probe` sur des scores fixes et rend la liste des appels."""
    appels: List[int] = []

    def _probe() -> Dict[str, float]:
        appels.append(callback._stage_episode())
        return dict(scores)

    callback._probe = _probe  # type: ignore[method-assign]
    return appels


# ── LE VERROU ──────────────────────────────────────────────────────────────────────────────


def test_a_baseline_at_parity_lets_the_run_start(tmp_path) -> None:
    """0.50 contre l'archive reprise : c'est la valeur attendue, le run demarre."""
    callback = _warm_started_callback(tmp_path)
    appels = _fake_baseline(callback, {"P1": 0.50, "P0": 0.62})

    callback._on_training_start()

    assert appels == [0], "la baseline doit sonder exactement a _stage_episode() == 0"


@pytest.mark.parametrize("score", [0.40, 0.60])
def test_the_window_bounds_are_inclusive(tmp_path, score: float) -> None:
    """Les bornes sont dans la fenetre : un run a exactement 0.40 ou 0.60 n'est pas refuse."""
    callback = _warm_started_callback(tmp_path)
    _fake_baseline(callback, {"P1": score, "P0": 0.62})

    callback._on_training_start()  # ne leve pas


def test_a_baseline_at_030_stops_the_run_before_any_training(tmp_path) -> None:
    """0.30 contre l'archive dont l'etape REPREND les poids : impossible, donc c'est une panne.

    Le refus doit nommer le score, l'archive et la fenetre : c'est ce qui permet de distinguer
    une panne d'appariement d'un mauvais resultat sans rouvrir un zip.
    """
    callback = _warm_started_callback(tmp_path)
    _fake_baseline(callback, {"P1": 0.30, "P0": 0.62})

    with pytest.raises(RuntimeError) as excinfo:
        callback._on_training_start()

    message = str(excinfo.value)
    assert "0.300" in message
    assert "P1" in message
    assert "[0.40, 0.60]" in message


def test_a_baseline_above_the_window_stops_the_run_too(tmp_path) -> None:
    """Le verrou est BILATERAL : 0.85 contre soi-meme est aussi impossible que 0.30.

    Un ecart vers le haut n'est pas une bonne nouvelle a laisser passer — il dit que l'adversaire
    charge n'est pas le modele repris, ou qu'il joue sans sa normalisation.
    """
    callback = _warm_started_callback(tmp_path)
    _fake_baseline(callback, {"P1": 0.85, "P0": 0.90})

    with pytest.raises(RuntimeError, match="parite d'ouverture VIOLEE|VIOL"):
        callback._on_training_start()


def test_the_parity_is_read_on_the_resumed_archive_not_on_the_champion(tmp_path) -> None:
    """`parity_label` suit l'`init`, pas le champion : les deux peuvent differer.

    C'est le cas des exploiteurs depuis le 2026-09-07 — ils reprennent P0 et jouent leur cible.
    Lire la parite sur le champion y mesurerait un score qui n'a aucune raison d'etre a 0.50.
    """
    callback = _warm_started_callback(tmp_path, parity_label="P0")
    _fake_baseline(callback, {"P1": 0.12, "P0": 0.51})

    callback._on_training_start()  # le champion a 0.12 ne concerne pas ce verrou


def test_a_fresh_run_has_no_parity_to_hold(tmp_path) -> None:
    """Run neuf (`episode_origin == 0`) : aucune baseline, donc aucun verrou a poser."""
    archive = tmp_path / "champ.zip"
    archive.touch()
    callback = pool_early_stopping_callback(archive, parity_label=None)
    callback.metrics_tracker = _tracker(0)
    appels = _fake_baseline(callback, {"champion": 0.05})

    callback._on_training_start()

    assert appels == [], "aucune sonde baseline sur un run neuf"


# ── CE QUE LE CONSTRUCTEUR REFUSE ──────────────────────────────────────────────────────────


def test_a_warm_start_without_a_parity_label_is_refused(tmp_path) -> None:
    """Sans etiquette, le verrou serait silencieusement inoperant sur le chemin qu'il protege."""
    with pytest.raises(ValueError, match="parity_label est obligatoire"):
        _warm_started_callback(tmp_path, parity_label=None)


def test_a_parity_label_outside_the_probed_pool_is_refused(tmp_path) -> None:
    """L'archive reprise DOIT etre sondee : sinon rien ne mesure l'identite qui vaut 0.50."""
    with pytest.raises(ValueError, match="parity_label"):
        _warm_started_callback(tmp_path, parity_label="P7")


def test_a_window_that_misses_parity_is_refused(tmp_path) -> None:
    """Une fenetre qui n'encadre pas 0.5 refuserait TOUT run : elle est fausse, pas stricte."""
    with pytest.raises(ValueError, match="ENCADRER"):
        _warm_started_callback(tmp_path, parity_range=(0.55, 0.65))


def test_an_incomplete_baseline_stops_the_run(tmp_path) -> None:
    """Score manquant = le verrou ne peut RIEN refuser. Continuer serait entrainer a l'aveugle.

    L'ancien code se contentait d'un avertissement et laissait le run partir ; c'etait tolerable
    quand la baseline n'etait qu'un point de reference a lire, ca ne l'est plus depuis qu'elle
    porte ce verrou.
    """
    callback = _warm_started_callback(tmp_path)
    _fake_baseline(callback, {"P0": 0.62})  # P1 absent : archive ecartee par l'evaluation

    with pytest.raises(RuntimeError, match="baseline d'ouverture incomplète"):
        callback._on_training_start()
