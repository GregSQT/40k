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

    La publication et la décision ont deux besoins différents : une courbe de moyenne qui
    doublerait la brute au premier point n'apprend rien, alors que la valeur rendue est ce que lit
    `evaluate_pool_decision` — dont les paliers d'épisodes, eux, n'ouvrent qu'après deux sondes.
    """
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, tracker = _callback_with_tracker(archive)

    means = cb._log_probe_scores({"champion": 0.453}, episode=100)

    tracker.log_pool_probe.assert_called_once_with("champion", 0.453, None, 100, 3)
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
    tracker.log_pool_probe.assert_called_once_with("champion", 0.557, expected_mean, 200, 3)
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
    assert last_call == call("champion", 0.420, expected_mean, 400, 3)


def test_the_window_length_comes_from_the_config(tmp_path):
    """`probe_window` gouverne la fenêtre : 2 déclaré, deux points retenus, pas trois."""
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, _ = _callback_with_tracker(
        archive, early_stop_cfg={**POOL_EARLY_STOP_CFG, "probe_window": 2}
    )

    means: dict[str, float] = {}
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
        snapshot_model_path=str(tmp_path / "model_T.zip"),
    )
    cb.model = MagicMock()

    cb._log_probe_scores({"label_a": 0.5, "label_b": 0.4}, episode=100)
    cb._log_probe_scores({"label_a": 0.6, "label_b": 0.3}, episode=200)

    calls = tracker.log_pool_probe.call_args_list
    # Deuxième sonde : chaque label a sa moyenne indépendante
    assert call("label_a", 0.6, pytest.approx((0.5 + 0.6) / 2), 200, 3) in calls
    assert call("label_b", 0.3, pytest.approx((0.4 + 0.3) / 2), 200, 3) in calls


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

    with patch.object(cb, "_probe", side_effect=lambda full_pool=True: {"champion": next(probe_values)}):
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

    with patch.object(cb, "_probe", side_effect=lambda full_pool=True: {"champion": next(probe_values)}):
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

    with patch.object(cb, "_probe", side_effect=lambda full_pool=True: {"champion": next(probe_values)}):
        assert _step_at(cb, 220) is True, "une seule sonde : pas encore de moyenne"
        assert _step_at(cb, 250) is False

    assert cb.stop_verdict == POOL_VERDICT_DESTROY
    assert "0.300" in cb.stop_reason


def test_nothing_is_decided_before_the_destruction_gate(tmp_path):
    """Sous `destroy_min_episodes` (200), une moyenne effondrée n'arrête rien."""
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, _ = _callback_with_tracker(archive)

    with patch.object(cb, "_probe", side_effect=lambda full_pool=True: {"champion": 0.05}):
        assert _step_at(cb, 100) is True
        assert _step_at(cb, 199) is True, "moyenne complète à 0.05, mais le palier n'est pas ouvert"

    assert cb.stop_verdict is None
    assert len(cb._probe_score_history["champion"]) == 2


def test_an_incomplete_probe_stops_the_run(tmp_path):
    """Score manquant en cours de run : LÈVE, comme la baseline et comme le gate de fin d'étape.

    Ce test verrouillait l'inverse jusqu'au 2026-09-07 — « l'éval est écartée, l'entraînement
    continue » — au motif que seule la baseline portait une décision. Ce n'est plus vrai : la
    sonde périodique porte les DEUX verdicts. Une archive écartée à chaque sonde laissait donc
    `_probe_score_history` vide, `evaluate_pool_decision` jamais appelé, et l'étape brûlait ses
    300 000 épisodes avec promotion et destruction mortes, pour seule trace une ligne ⚠️ par sonde.

    Une archive écartée est un défaut de contrat — fichier absent, architecture incompatible — et
    aucun des deux ne se répare en cours de run.
    """
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, _ = _callback_with_tracker(archive)

    with patch.object(cb, "_probe", side_effect=lambda full_pool=True: {}):
        with pytest.raises(RuntimeError, match="scores manquants"):
            _step_at(cb, 900)

    assert cb.stop_verdict is None, "l'arrêt vient de l'exception, pas d'un verdict de pool"
    assert cb._probe_score_history == {}


def test_a_partially_complete_probe_stops_the_run_too(tmp_path):
    """Un pool à deux membres dont UN seul répond : la moyenne du manquant n'existerait pas.

    Le cas du finding : `evaluate_against_checkpoints` écarte une archive et rend les autres. Un
    verdict pris sur le sous-ensemble survivant jugerait l'étape sur un pool qui n'est pas le sien.
    """
    from ai.training_callbacks import PoolEarlyStoppingCallback

    archives = [(str(tmp_path / "a.zip"), "champion"), (str(tmp_path / "b.zip"), "E1")]
    for path, _ in archives:
        open(path, "wb").close()
    cb = PoolEarlyStoppingCallback(
        pool_archives=archives,
        stage_name="P-test",
        champion_label="champion",
        early_stop_cfg=dict(POOL_EARLY_STOP_CFG),
        eval_freq_episodes=100,
        n_eval_episodes=10,
        training_config_name="test",
        rewards_config_name="test",
        metrics_tracker=MagicMock(),
        parity_label=None,
        parity_range=(0.40, 0.60),
        snapshot_model_path=str(tmp_path / "model_T.zip"),
    )
    cb.model = MagicMock()

    with patch.object(cb, "_probe", side_effect=lambda full_pool=True: {"champion": 0.52}):
        with pytest.raises(RuntimeError, match=r"scores manquants pour \['E1'\]"):
            _step_at(cb, 900)


def test_the_verdict_is_the_one_the_curriculum_computes(tmp_path):
    """Le callback ne réimplémente pas la règle : il appelle `evaluate_pool_decision`.

    La même fonction sert le gate de fin d'étape. Deux copies de la règle laisseraient un run
    s'arrêter sur un critère plus faible que celui qui le jugera ensuite.

    La doublure vise `ai.training_callbacks.evaluate_pool_decision` et NON `ai.curriculum...` :
    l'import a quitté le corps de `_on_step` pour la portée module (cd091ac1), donc le nom est
    résolu une fois pour toutes dans le namespace du callback. Patcher le module d'origine ne
    changeait plus rien — le vrai verdict s'exécutait, `_on_step` rendait False et le test
    échouait sur la valeur de retour, sans jamais dire que sa doublure n'avait pas pris.
    """
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, _ = _callback_with_tracker(archive)

    with patch.object(cb, "_probe", side_effect=lambda full_pool=True: {"champion": 0.01}):
        _step_at(cb, 90_000)  # première sonde : la règle n'est pas encore consultée
        with patch("ai.training_callbacks.evaluate_pool_decision") as fake:
            fake.return_value = MagicMock(verdict=POOL_VERDICT_CONTINUE, reason="doublure")
            assert _step_at(cb, 100_000) is True

    assert fake.call_count == 1
    stage_name, champion_label, means, stage_episodes, cfg = fake.call_args[0]
    assert (stage_name, champion_label, stage_episodes) == ("P-test", "champion", 100_000)
    assert means == {"champion": pytest.approx(0.01)}
    assert cfg is cb.early_stop_cfg


# ── DEUX CADENCES : le champion à chaque sonde, le reste du pool tous les N ──────────────────


def _multi_pool_callback(tmp_path, every: int):
    """Pool de trois membres, cadence de pool entier configurable."""
    from ai.training_callbacks import PoolEarlyStoppingCallback

    archives = []
    for label in ("champion", "vieux_a", "vieux_b"):
        path = tmp_path / f"{label}.zip"
        path.touch()
        archives.append((str(path), label))
    cb = PoolEarlyStoppingCallback(
        pool_archives=archives,
        stage_name="P-test",
        champion_label="champion",
        early_stop_cfg={**POOL_EARLY_STOP_CFG, "full_pool_probe_every": every},
        eval_freq_episodes=100,
        n_eval_episodes=10,
        training_config_name="test",
        rewards_config_name="test",
        metrics_tracker=None,
        parity_label=None,
        parity_range=(0.40, 0.60),
        snapshot_model_path=str(tmp_path / "model_T.zip"),
    )
    cb.model = MagicMock()
    return cb


def _record_probes(cb, scores: dict) -> list:
    """Doublure de `_probe` qui note les labels demandés à chaque tour."""
    demandes: list = []

    def _probe(full_pool: bool = True) -> dict:
        labels = [label for _, label in cb._archives_for(full_pool)]
        demandes.append(labels)
        return {label: scores[label] for label in labels}

    cb._probe = _probe  # type: ignore[method-assign]
    return demandes


def test_only_the_champion_is_probed_between_two_full_pool_rounds(tmp_path):
    """Les deux premiers tours sont pleins, puis un sur trois ; entre eux, le champion seul.

    C'est la décision de coût du 2026-09-07 : le prix d'une sonde suivait la taille du pool, qui
    croît d'une étape à l'autre — 117 000 épisodes d'évaluation bloquants pour 300 000 entraînés à
    la dernière étape.
    """
    cb = _multi_pool_callback(tmp_path, every=3)
    demandes = _record_probes(cb, {"champion": 0.52, "vieux_a": 0.52, "vieux_b": 0.52})

    for episode in (100, 200, 300, 400, 500, 600):
        _step_at(cb, episode)

    plein = ["champion", "vieux_a", "vieux_b"]
    assert demandes == [plein, plein, ["champion"], plein, ["champion"], ["champion"]]


def test_the_verdict_still_reads_the_whole_pool_on_a_champion_only_round(tmp_path):
    """Un tour champion seul décide quand même sur TOUT le pool, avec les dernières valeurs connues.

    Ne passer que le champion à `evaluate_pool_decision` promouvrait sur son seul score — la
    régression exacte que le pool entier a été introduit pour fermer.
    """
    cb = _multi_pool_callback(tmp_path, every=3)
    # Le champion est franchement au-dessus des deux planchers ; `vieux_a` est SOUS
    # `promote_score_vs_others` (0.55) et n'est pas mesuré au tour où le verdict tombe.
    _record_probes(cb, {"champion": 0.90, "vieux_a": 0.20, "vieux_b": 0.90})

    for episode in (600, 700, 800):
        assert _step_at(cb, episode) is True, "vieux_a sous son plancher : aucune promotion"

    assert cb.stop_verdict is None
    # `vieux_a` n'a ete sonde qu'aux deux premiers tours : sa fenetre est intacte, et c'est elle
    # qui a retenu la promotion au tour ou il n'etait pas mesure.
    assert list(cb._probe_score_history["vieux_a"]) == pytest.approx([0.20, 0.20])


def test_destruction_still_fires_at_its_own_gate_with_a_degraded_cadence(tmp_path):
    """La destruction reste servie au deuxième tour, comme à cadence pleine.

    Elle ne lit que le champion et doit couper vite. Si un seul tour plein ouvrait la série, aucun
    membre n'aurait deux points avant le retour du pool entier, et le verdict attendrait
    2 × `destroy_min_episodes`.
    """
    cb = _multi_pool_callback(tmp_path, every=3)
    _record_probes(cb, {"champion": 0.30, "vieux_a": 0.90, "vieux_b": 0.90})

    assert _step_at(cb, 220) is True, "une seule sonde : pas encore de moyenne"
    assert _step_at(cb, 250) is False, "deuxième tour : la destruction doit pouvoir tomber"
    assert cb.stop_verdict == POOL_VERDICT_DESTROY


def test_every_one_keeps_probing_the_whole_pool(tmp_path):
    """`full_pool_probe_every: 1` rend exactement le comportement d'avant la décision."""
    cb = _multi_pool_callback(tmp_path, every=1)
    demandes = _record_probes(cb, {"champion": 0.52, "vieux_a": 0.52, "vieux_b": 0.52})

    for episode in (100, 200, 300, 400):
        _step_at(cb, episode)

    assert demandes == [["champion", "vieux_a", "vieux_b"]] * 4


# ── Instantanés à seuils, historique du champion, runs de check (2026-09-17) ───────────────


def _probing(cb, values):
    """Doublure de `_probe` rendant les scores du champion dans l'ordre donné."""
    it = iter(values)
    return patch.object(cb, "_probe", side_effect=lambda full_pool=True: {"champion": next(it)})


def test_a_snapshot_is_written_once_per_threshold_on_the_raw_probe(tmp_path):
    """0.50 au premier franchissement (0.55), 0.60 au sien (0.65) ; jamais deux fois."""
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, _ = _callback_with_tracker(
        archive, early_stop_cfg={**POOL_EARLY_STOP_CFG, "snapshot_thresholds": [0.5, 0.6]}
    )
    written = []
    with patch.object(cb, "_write_threshold_snapshot", side_effect=lambda t, raw, ep: written.append((t, raw, ep))), \
         _probing(cb, [0.45, 0.55, 0.52, 0.65, 0.70]):
        for episode in (100, 200, 300, 400, 500):
            _step_at(cb, episode)
    assert written == [(0.5, 0.55, 200), (0.6, 0.65, 400)]


def test_the_champion_mean_history_starts_when_the_window_is_full(tmp_path):
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, _ = _callback_with_tracker(archive)
    with _probing(cb, [0.50, 0.56, 0.59, 0.62]):
        for episode in (100, 200, 300, 400):
            _step_at(cb, episode)
    assert cb.champion_mean_history == pytest.approx([0.55, 0.59])


def test_run_to_plateau_and_the_history_reach_the_decision(tmp_path):
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, _ = _callback_with_tracker(archive, run_to_plateau=True)
    with patch("ai.training_callbacks.evaluate_pool_decision") as fake, _probing(cb, [0.5, 0.5, 0.5]):
        fake.return_value = MagicMock(verdict=POOL_VERDICT_CONTINUE, reason="r")
        for episode in (100, 200, 300):
            _step_at(cb, episode)
    kwargs = fake.call_args.kwargs
    assert kwargs["run_to_plateau"] is True
    assert kwargs["champion_mean_history"] is cb.champion_mean_history
    assert cb.champion_mean_history == pytest.approx([0.5])


def test_the_first_promotable_probe_is_dated_once_and_only_after_the_floor(tmp_path):
    """Planchers tenus dès 0.65/0.75 (moyenne 0.70) mais avant 500 : pas daté ; à 600 : daté."""
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, _ = _callback_with_tracker(archive, run_to_plateau=True)
    with _probing(cb, [0.65, 0.75, 0.80, 0.85]):
        _step_at(cb, 300)
        _step_at(cb, 400)
        assert cb.first_promotable_episode is None
        _step_at(cb, 600)
        assert cb.first_promotable_episode == 600
        _step_at(cb, 700)
    assert cb.first_promotable_episode == 600
    assert cb.stop_verdict is None, "run de check : la promotion n'arrête pas le run"


def test_a_check_stage_stops_on_a_plateau_and_promotes_on_its_live_weights(tmp_path):
    """Patience 2 (fabrique), min_delta 0.02, min_episodes 500 : 3 moyennes à 0.70 → plateau."""
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, _ = _callback_with_tracker(archive, run_to_plateau=True)
    with _probing(cb, [0.70] * 8):
        verdicts = [_step_at(cb, ep) for ep in range(100, 900, 100)]
    # Historique des moyennes : ep300 [0.7], ep400 [0.7, 0.7], ep500 [0.7, 0.7, 0.7] → plateau
    # décidable (3 > patience 2) à 500 ≥ min_episodes 500, planchers tenus (≥ 500) : promotion.
    assert verdicts[:4] == [True] * 4 and verdicts[4] is False
    assert cb.stop_verdict == POOL_VERDICT_PROMOTE
    assert "PLATEAU" in cb.stop_reason


def test_the_snapshot_writer_produces_the_four_files_of_an_archive(tmp_path, monkeypatch):
    from ai.run_state import load_run_state
    from ai.training_contract import contract_path

    canonical = tmp_path / "model_T.zip"
    archive = tmp_path / "model_T_P0.zip"
    archive.touch()
    contract_path(str(canonical))  # chemin seulement
    (tmp_path / "model_T_training_contract.json").write_text("{}", encoding="utf-8")
    cb = pool_early_stopping_callback(
        archive, snapshot_model_path=str(canonical), stage_name="P1", champion_label="champion",
    )

    class _Model:
        def save(self, path):
            open(path, "wb").write(b"zip")
        def get_env(self):
            return "env"

    cb.model = _Model()
    monkeypatch.setattr(
        "ai.vec_normalize_utils.save_vec_normalize",
        lambda env, path: (open(path[:-4] + "_vec_normalize.pkl", "wb").write(b"pkl"), True)[1],
    )
    with patch.object(cb, "_current_episode", return_value=12345):
        path = cb._write_threshold_snapshot(0.6, 0.63, 4000)

    assert path == str(tmp_path / "model_T_P1_vschampion_060.zip")
    assert (tmp_path / "model_T_P1_vschampion_060_vec_normalize.pkl").exists()
    assert (tmp_path / "model_T_P1_vschampion_060_training_contract.json").exists()
    assert load_run_state(path) == 12345


def test_the_snapshot_writer_refuses_a_model_without_normalisation_stats(tmp_path, monkeypatch):
    canonical = tmp_path / "model_T.zip"
    archive = tmp_path / "model_T_P0.zip"
    archive.touch()
    cb = pool_early_stopping_callback(archive, snapshot_model_path=str(canonical))
    cb.model = MagicMock()
    monkeypatch.setattr("ai.vec_normalize_utils.save_vec_normalize", lambda env, path: False)
    with pytest.raises(RuntimeError, match="VecNormalize"):
        cb._write_threshold_snapshot(0.5, 0.51, 100)


def test_a_snapshot_already_on_disk_is_kept_not_rewritten(tmp_path):
    """Reprise après crash : le premier franchissement est celui du fichier existant."""
    archive = tmp_path / "champ.zip"
    archive.touch()
    (tmp_path / "model_T_P-test_vschampion_050.zip").write_bytes(b"premier")
    cb, _ = _callback_with_tracker(
        archive, early_stop_cfg={**POOL_EARLY_STOP_CFG, "snapshot_thresholds": [0.5]},
        snapshot_model_path=str(tmp_path / "model_T.zip"),
    )
    written = []
    with patch.object(cb, "_write_threshold_snapshot", side_effect=lambda t, raw, ep: written.append(t)), \
         _probing(cb, [0.70, 0.71]):
        _step_at(cb, 100)
        _step_at(cb, 200)
    assert written == []
    assert (tmp_path / "model_T_P-test_vschampion_050.zip").read_bytes() == b"premier"
    assert cb.snapshots_written == {0.5: str(tmp_path / "model_T_P-test_vschampion_050.zip")}
