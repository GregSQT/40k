"""Moyenne glissante des sondes de `PoolEarlyStoppingCallback` — et ce qu'elle DÉCIDE.

Avant le 2026-09-07, la moyenne n'était qu'une trace : le gate d'arrêt lisait la sonde BRUTE, et
la moyenne servait à lire une tendance à côté. C'est l'inverse depuis : les deux verdicts —
promotion anticipée et arrêt pour destruction — se prennent sur la moyenne, la brute restant
publiée pour la lecture.

MESURE qui l'impose (2026-09-07) : deux appels de sonde sur un modèle figé rendaient le même
score au bit près. Les sauts de ±5 points entre sondes voisines ne sont donc PAS du bruit
d'échantillonnage mais des blocs de parties corrélées qui basculent ensemble quand la politique
bouge ; décider sur une brute revient à décider sur leur amplitude.

Ce fichier vérifie :
1. Historique mis à jour correctement sur plusieurs sondes (fenêtre glissante).
2. Pas de moyenne PUBLIÉE à la première sonde — mais une moyenne RENDUE, car c'est elle qui décide.
3. L'historique est tenu même sans `metrics_tracker` : un verdict ne doit pas dépendre d'un
   writer TensorBoard.
4. Les verdicts lisent la moyenne, pas la brute.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from ai.curriculum import POOL_VERDICT_CONTINUE, POOL_VERDICT_DESTROY, POOL_VERDICT_PROMOTE
from tests.unit.ai._fabriques import POOL_EARLY_STOP_CFG, pool_early_stopping_callback


# ── Helpers ──────────────────────────────────────────────────────────────────


def _callback_with_tracker(archive, **overrides):
    tracker = MagicMock()
    cb = pool_early_stopping_callback(archive, metrics_tracker=tracker, **overrides)
    return cb, tracker


def _step_at(cb, episode: int) -> bool:
    """Force une sonde à `episode` épisodes D'ÉTAPE et rend le verdict de `_on_step`."""
    cb._next_probe_episode = 0
    with patch.object(cb, "_stage_episode", return_value=episode), \
         patch.object(cb, "_current_episode", return_value=episode):
        return cb._on_step()


# ── Tests : historique et moyenne ──────────────────────────────────────────


def test_first_probe_emits_no_rolling_mean_but_returns_one(tmp_path):
    """La première sonde ne PUBLIE pas de moyenne (identique au brut) mais en REND une.

    La publication et la décision ont deux besoins différents : une courbe `_3ep` qui doublerait
    la brute au premier point n'apprend rien, alors que la valeur rendue est ce que lit
    `evaluate_pool_decision` — dont les paliers d'épisodes, eux, n'ouvrent qu'après deux sondes.
    """
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, tracker = _callback_with_tracker(archive)

    means = cb._log_probe_scores({"champion": 0.453}, episode=100)

    tracker.log_pool_probe.assert_called_once_with("champion", 0.453, None, 100)
    assert means == {"champion": pytest.approx(0.453)}


def test_second_probe_emits_mean_of_two(tmp_path):
    """A la deuxième sonde la moyenne porte les deux valeurs."""
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, tracker = _callback_with_tracker(archive)

    cb._log_probe_scores({"champion": 0.453}, episode=100)
    tracker.reset_mock()

    means = cb._log_probe_scores({"champion": 0.557}, episode=200)

    expected_mean = pytest.approx((0.453 + 0.557) / 2)
    tracker.log_pool_probe.assert_called_once_with("champion", 0.557, expected_mean, 200)
    assert means["champion"] == expected_mean


def test_window_slides_after_three_probes(tmp_path):
    """A la quatrième sonde la fenêtre glisse : la première valeur est écartée."""
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, tracker = _callback_with_tracker(archive)

    scores = [0.453, 0.557, 0.487, 0.420]
    for i, v in enumerate(scores):
        cb._log_probe_scores({"champion": v}, episode=(i + 1) * 100)

    # Quatrième appel : fenêtre = [0.557, 0.487, 0.420]
    expected_mean = pytest.approx((0.557 + 0.487 + 0.420) / 3)
    last_call = tracker.log_pool_probe.call_args_list[-1]
    assert last_call == call("champion", 0.420, expected_mean, 400)


def test_the_window_length_comes_from_the_config(tmp_path):
    """`probe_window` gouverne la fenêtre : 2 déclaré, deux points retenus, pas trois."""
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, _ = _callback_with_tracker(
        archive, early_stop_cfg={**POOL_EARLY_STOP_CFG, "probe_window": 2}
    )

    for i, v in enumerate([0.10, 0.20, 0.90]):
        means = cb._log_probe_scores({"champion": v}, episode=(i + 1) * 100)

    assert means["champion"] == pytest.approx((0.20 + 0.90) / 2)


def test_multiple_labels_tracked_independently(tmp_path):
    """Deux labels ont chacun leur propre historique."""
    archives = [(str(tmp_path / "a.zip"), "label_a"), (str(tmp_path / "b.zip"), "label_b")]
    for path, _ in archives:
        (tmp_path / path.split("/")[-1]).touch()

    from ai.training_callbacks import PoolEarlyStoppingCallback

    tracker = MagicMock()
    cb = PoolEarlyStoppingCallback(
        pool_archives=archives,
        stage_name="P-test",
        champion_label="label_a",
        early_stop_cfg=dict(POOL_EARLY_STOP_CFG),
        eval_freq_episodes=100,
        n_eval_episodes=10,
        training_config_name="test",
        rewards_config_name="test",
        metrics_tracker=tracker,
        parity_label=None,
        parity_range=(0.40, 0.60),
    )
    cb.model = MagicMock()

    cb._log_probe_scores({"label_a": 0.5, "label_b": 0.4}, episode=100)
    cb._log_probe_scores({"label_a": 0.6, "label_b": 0.3}, episode=200)

    calls = tracker.log_pool_probe.call_args_list
    # Deuxième sonde : chaque label a sa moyenne indépendante
    assert call("label_a", 0.6, pytest.approx((0.5 + 0.6) / 2), 200) in calls
    assert call("label_b", 0.3, pytest.approx((0.4 + 0.3) / 2), 200) in calls


def test_the_history_is_kept_without_a_metrics_tracker(tmp_path):
    """Sans tracker, la PUBLICATION s'arrête — pas l'historique.

    L'ancien code sortait avant la mise à jour quand `metrics_tracker` valait None. C'était sans
    conséquence tant que la moyenne n'était qu'une trace ; depuis qu'elle porte les verdicts, cela
    ferait dépendre un arrêt de run de la présence d'un writer TensorBoard.
    """
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb = pool_early_stopping_callback(archive, metrics_tracker=None)

    cb._log_probe_scores({"champion": 0.4}, episode=100)
    means = cb._log_probe_scores({"champion": 0.6}, episode=200)

    assert means["champion"] == pytest.approx(0.5)


# ── Tests : les verdicts lisent la MOYENNE, pas la brute ──────────────────


def test_a_single_high_probe_does_not_promote(tmp_path):
    """Brute à 0.90, moyenne à 0.59 : sous `promote_score_vs_champion` (0.60), rien ne s'arrête.

    C'est le renversement du 2026-09-07. L'ancien gate comptait des sondes BRUTES au-dessus du
    seuil ; deux bascules consécutives d'un bloc de parties corrélées suffisaient donc à arrêter
    un run, et l'amplitude de ces bascules a été mesurée à ±5 points sur un modèle qui bouge peu.
    """
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, _ = _callback_with_tracker(archive)

    probe_values = iter([0.42, 0.45, 0.90])

    with patch.object(cb, "_probe", side_effect=lambda: {"champion": next(probe_values)}):
        for episode in (600, 700, 800):
            assert _step_at(cb, episode) is True

    assert cb.stop_verdict is None
    assert cb._probe_score_history["champion"] == pytest.approx([0.42, 0.45, 0.90])
    # Moyenne finale 0.59, sous le plancher de promotion 0.60, alors que la brute vaut 0.90.
    assert sum([0.42, 0.45, 0.90]) / 3 < POOL_EARLY_STOP_CFG["promote_score_vs_champion"]


def test_the_mean_above_both_floors_promotes_and_stops(tmp_path):
    """Moyenne 0.70 > 0.60 après `promote_min_episodes` : le run s'arrête, verdict promotion."""
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, _ = _callback_with_tracker(archive)

    probe_values = iter([0.65, 0.75])

    with patch.object(cb, "_probe", side_effect=lambda: {"champion": next(probe_values)}):
        assert _step_at(cb, 600) is True, "une seule sonde : la moyenne EST la brute, rien à décider"
        assert cb.stop_verdict is None
        assert _step_at(cb, 700) is False, "moyenne 0.70 au-dessus de 0.60 : promotion"

    assert cb.stop_verdict == POOL_VERDICT_PROMOTE
    assert "seuils de promotion" in cb.stop_reason


def test_a_collapsing_mean_stops_the_run_for_destruction(tmp_path):
    """Moyenne 0.30 sous `destroy_score_vs_champion` : l'étape a défait ce qu'elle a reçu.

    Une étape part à 0.50 contre son champion par construction. Le run du 2026-09-04 est descendu
    de 0,477 à 0,297 en 10 000 épisodes et n'est jamais remonté : une fois cette pente prise, le
    budget restant est perdu.
    """
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, _ = _callback_with_tracker(archive)

    probe_values = iter([0.32, 0.28])

    with patch.object(cb, "_probe", side_effect=lambda: {"champion": next(probe_values)}):
        assert _step_at(cb, 220) is True, "une seule sonde : pas encore de moyenne"
        assert _step_at(cb, 250) is False

    assert cb.stop_verdict == POOL_VERDICT_DESTROY
    assert "0.300" in cb.stop_reason


def test_nothing_is_decided_before_the_destruction_gate(tmp_path):
    """Sous `destroy_min_episodes` (200), une moyenne effondrée n'arrête rien."""
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, _ = _callback_with_tracker(archive)

    with patch.object(cb, "_probe", side_effect=lambda: {"champion": 0.05}):
        assert _step_at(cb, 100) is True
        assert _step_at(cb, 199) is True, "moyenne complète à 0.05, mais le palier n'est pas ouvert"

    assert cb.stop_verdict is None
    assert len(cb._probe_score_history["champion"]) == 2


def test_an_incomplete_probe_is_ignored_without_deciding(tmp_path):
    """Score manquant en cours de run : l'éval est écartée, l'entraînement continue.

    Contrairement à la baseline d'ouverture, qui LÈVE : elle porte le verrou de parité, donc un
    score manquant y rend le verrou incapable de refuser quoi que ce soit.
    """
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, _ = _callback_with_tracker(archive)

    with patch.object(cb, "_probe", side_effect=lambda: {}):
        assert _step_at(cb, 900) is True

    assert cb.stop_verdict is None
    assert cb._probe_score_history == {}


def test_the_verdict_is_the_one_the_curriculum_computes(tmp_path):
    """Le callback ne réimplémente pas la règle : il appelle `evaluate_pool_decision`.

    La même fonction sert le gate de fin d'étape. Deux copies de la règle laisseraient un run
    s'arrêter sur un critère plus faible que celui qui le jugera ensuite.
    """
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, _ = _callback_with_tracker(archive)

    with patch.object(cb, "_probe", side_effect=lambda: {"champion": 0.01}):
        _step_at(cb, 90_000)  # première sonde : la règle n'est pas encore consultée
        with patch("ai.curriculum.evaluate_pool_decision") as fake:
            fake.return_value = MagicMock(verdict=POOL_VERDICT_CONTINUE, reason="doublure")
            assert _step_at(cb, 100_000) is True

    assert fake.call_count == 1
    stage_name, champion_label, means, stage_episodes, cfg = fake.call_args[0]
    assert (stage_name, champion_label, stage_episodes) == ("P-test", "champion", 100_000)
    assert means == {"champion": pytest.approx(0.01)}
    assert cfg is cb.early_stop_cfg
