"""Origine d'étape des sondes : `ExploiterProbeCallback`, `PoolEarlyStoppingCallback`, `stage_origin`.

Reproduit le run P2 du 2026-09-04 : reprise `from:P1` à 80 000 épisodes, `bot_eval_freq` 10 000.
`_next_probe_episode` partait de 10 000 alors que le tracker (cumulatif sur la lignée) démarrait
à 80 000 : la sonde se déclenchait au premier pas, puis à CHAQUE pas suivant jusqu'à ce que le
cap rattrape 80 000 — 8 sondes de 300 épisodes consécutives (8 × 18 min) avant le premier vrai
épisode. `min_steps` (50 000) comparé aux 13,7 M de `num_timesteps` hérités de l'archive ne
gardait plus rien. Le jumeau exploiteur portait le même défaut, en plus grave : un `budget_cap`
comparé au compteur cumulé d'une lignée reprise `from:P3` aurait censuré le run au premier pas.

Les deux callbacks reçoivent désormais à la construction l'origine de l'étape, lue sur l'ARCHIVE
SOURCE de l'étape par `ai.curriculum.stage_origin` — pas sur le modèle repris, qui après un
`--resume-from` de crash est un checkpoint de milieu d'étape — et toutes leurs grandeurs
(cadence, plafond de pas, budget, courbe) se comptent DEPUIS cette origine.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from ai.curriculum import stage_model_path, stage_origin
from ai.run_state import save_run_state
from ai.training_callbacks import ExploiterProbeCallback, PoolEarlyStoppingCallback
from shared.data_validation import ConfigurationError
from tests.unit.ai._fabriques import (
    POOL_EARLY_STOP_CFG,
    exploiter_probe_callback,
    pool_early_stopping_callback,
)

# Valeurs du run mesuré : offset de reprise et `num_timesteps` relu dans model_ArmageddonAgent_x1_P1.zip.
P2_EPISODE_OFFSET = 80_000
P1_NUM_TIMESTEPS = 13_749_576


def _tracker(episode_count: int) -> MagicMock:
    tracker = MagicMock()
    tracker.episode_count = episode_count
    return tracker


def _pool_callback(**overrides: Any) -> PoolEarlyStoppingCallback:
    """Cadence du run mesuré (10 000 épisodes, 300 par éval) posée sur la fabrique partagée.

    `parity_label` suit `episode_origin` : le constructeur refuse une reprise à chaud sans
    étiquette de parité (cf. `test_pool_parity_lock.py`), et le label du pool de la fabrique est
    « champion ».
    """
    if overrides.get("episode_origin") and "parity_label" not in overrides:
        overrides["parity_label"] = "champion"
    callback = pool_early_stopping_callback(
        "/fake/P1.zip", eval_freq_episodes=10_000, n_eval_episodes=300, **overrides
    )
    callback.num_timesteps = 0
    return callback


def _exploiter_callback(**overrides: Any) -> ExploiterProbeCallback:
    """Budget du run mesuré (`budget_cap` 200 000) posé sur la fabrique partagée."""
    return exploiter_probe_callback(
        "/fake/P3.zip",
        probe_every_episodes=2_000,
        probe_cheap_n=100,
        probe_confirm_n=500,
        win_rate_target=0.7,
        budget_cap=200_000,
        **overrides,
    )


def _count_pool_probes(callback: PoolEarlyStoppingCallback, score: float = 0.3) -> List[int]:
    """Enregistre le compteur cumulé à chaque sonde ; le score reste sous le seuil (pas d'arrêt).

    Les labels rendus sont ceux du pool du callback : un score manquant ferait ignorer l'éval
    (`scores manquants`) et le test passerait sans exercer la comparaison au seuil.
    """
    probed: List[int] = []

    def fake_probe(full_pool: bool = True) -> Dict[str, float]:
        probed.append(callback._current_episode())
        return {label: score for _, label in callback._archives_for(full_pool)}

    callback._probe = fake_probe  # type: ignore[method-assign]
    return probed


# ── PoolEarlyStoppingCallback ───────────────────────────────────────────────────────────────────


def test_pool_resume_does_not_chain_probes_before_the_first_stage_interval():
    """Reprise à 80 000 : aucune sonde avant 90 000, puis UNE par tranche de 10 000."""
    callback = _pool_callback(episode_origin=P2_EPISODE_OFFSET)
    tracker = _tracker(P2_EPISODE_OFFSET)
    callback.metrics_tracker = tracker
    callback.num_timesteps = P1_NUM_TIMESTEPS + 24
    probed = _count_pool_probes(callback)

    # Les pas du run mesuré : premier pas à l'offset, puis quelques épisodes, puis juste sous le cap.
    for count in (P2_EPISODE_OFFSET, P2_EPISODE_OFFSET + 24, 89_999):
        tracker.episode_count = count
        assert callback._on_step() is True
    assert probed == [], "aucune sonde ne doit partir avant 10 000 épisodes DE L'ÉTAPE"

    tracker.episode_count = 90_000
    callback._on_step()
    tracker.episode_count = 90_010  # le pas suivant ne doit PAS resonder (c'était l'enchaînement)
    callback._on_step()
    tracker.episode_count = 100_003
    callback._on_step()
    assert probed == [90_000, 100_003]


def test_pool_decision_gates_count_episodes_from_the_stage_start():
    """Les deux paliers de décision comptent en épisodes D'ÉTAPE, jamais depuis la lignée.

    Remplace `test_pool_min_steps_counts_from_the_stage_start_not_from_the_archive` : le garde
    `min_steps`, exprimé en PAS, a été supprimé le 2026-09-07 avec les décisions en pas. Le
    défaut qu'il protégeait est le même — un compteur cumulé sur la lignée (80 000 épisodes hérités
    de P1) franchirait `promote_min_episodes` (500 dans la fabrique) dès le premier pas et
    promouvrait l'étape avant qu'elle n'ait joué.
    """
    # 50 000 : au-DESSUS des 10 000 épisodes d'étape joués, au-DESSOUS des 90 000 du cumul de
    # lignée. C'est exactement l'écart qui distingue les deux lectures.
    callback = _pool_callback(
        episode_origin=P2_EPISODE_OFFSET,
        early_stop_cfg={**POOL_EARLY_STOP_CFG, "promote_min_episodes": 50_000,
                        "destroy_min_episodes": 20_000},
    )
    tracker = _tracker(P2_EPISODE_OFFSET + 10_000)
    callback.metrics_tracker = tracker
    # Scores très au-dessus des seuils de promotion : seul le compteur d'épisodes peut retenir.
    callback._probe = lambda full_pool=True: {  # type: ignore[method-assign]
        label: 0.99 for _, label in callback._archives_for(full_pool)
    }

    assert callback._on_step() is True, (
        "10 000 épisodes D'ÉTAPE : sous promote_min_episodes lu en cumul de lignée (90 000), "
        "l'étape aurait été promue au premier pas"
    )
    assert callback.stop_verdict is None


def test_pool_resume_from_crash_does_not_chain_the_missed_probes():
    """`--resume-from` en MILIEU d'étape : une seule sonde, pas les treize crans manqués.

    L'origine est ancrée sur l'archive SOURCE, donc `_stage_episode()` vaut d'emblée 130 000 alors
    que `_next_probe_episode` part du premier cran (10 000). Avec une incrémentation, les crans
    10 000 … 130 000 se déclenchaient sur treize pas CONSÉCUTIFS, sans une seule mise à jour de
    politique entre eux ; à la deuxième, l'historique atteignait deux points et
    `evaluate_pool_decision` rendait un verdict — sur deux mesures des mêmes poids, à un
    `stage_episodes` (130 000) très au-dessus de `promote_min_episodes`. Le run de reprise
    s'arrêtait donc avant d'avoir entraîné.
    """
    stage_episode_at_crash = 130_000
    callback = _pool_callback(
        episode_origin=P2_EPISODE_OFFSET,
        early_stop_cfg={**POOL_EARLY_STOP_CFG, "promote_min_episodes": 50_000,
                        "destroy_min_episodes": 20_000},
    )
    tracker = _tracker(P2_EPISODE_OFFSET + stage_episode_at_crash)
    callback.metrics_tracker = tracker
    # Scores au-dessus des seuils de promotion : si un deuxième point entrait dans l'historique,
    # le verdict tomberait et le run s'arrêterait.
    probed = _count_pool_probes(callback, score=0.99)

    for _ in range(13):
        assert callback._on_step() is True

    assert probed == [P2_EPISODE_OFFSET + stage_episode_at_crash], (
        "les crans manqués doivent être rattrapés d'un coup, pas rejoués un par un"
    )
    assert callback.stop_verdict is None
    assert callback._next_probe_episode == 140_000

    # La cadence reprend normalement au cran suivant.
    tracker.episode_count = P2_EPISODE_OFFSET + 140_000
    callback._on_step()
    assert len(probed) == 2


def test_exploiter_resume_from_crash_does_not_chain_the_missed_probes():
    """Jumeau exploiteur : `_next_probe_episode` rattrape aussi la cadence."""
    lineage_count = 530_000
    callback = _exploiter_callback(episode_origin=lineage_count)
    tracker = _tracker(lineage_count + 50_000)  # 25 crans de 2 000 manqués
    callback.metrics_tracker = tracker
    probes: List[str] = []
    callback._probe = lambda n_episodes, label: probes.append(label) or 0.1  # type: ignore[method-assign]

    for _ in range(25):
        assert callback._on_step() is True

    assert probes == ["bon-marche"], "une seule sonde, pas les 25 crans manqués"
    assert callback._next_probe_episode == 52_000


def test_pool_fresh_run_keeps_its_cadence():
    """Run neuf (origine 0/0, la valeur par défaut) : sonde dès 10 000 épisodes, comme avant."""
    callback = _pool_callback()
    tracker = _tracker(9_999)
    callback.metrics_tracker = tracker
    probed = _count_pool_probes(callback)

    callback._on_step()
    tracker.episode_count = 10_000
    callback._on_step()
    assert probed == [10_000]


# ── ExploiterProbeCallback ──────────────────────────────────────────────────────────────────────


def test_exploiter_resumed_lineage_is_not_censored_at_the_first_step():
    """E1 `from:P3` : le cumul de la lignée dépasse `budget_cap` dès le premier pas."""
    lineage_count = 530_000  # > budget_cap 200 000
    callback = _exploiter_callback(episode_origin=lineage_count)
    tracker = _tracker(lineage_count)
    callback.metrics_tracker = tracker
    callback._probe = lambda n_episodes, label: 0.1  # type: ignore[method-assign]

    assert callback._on_step() is True
    assert callback.censored is False
    assert callback.win_rate_curve == [], "aucune sonde avant probe_every_episodes DE L'ÉTAPE"

    tracker.episode_count = lineage_count + 200_000
    assert callback._on_step() is False
    assert callback.censored is True


def test_exploiter_budget_and_curve_are_stage_relative():
    """Le budget journalisé (curriculum.log) est un nombre d'épisodes DE L'ÉTAPE."""
    lineage_count = 530_000
    callback = _exploiter_callback(episode_origin=lineage_count)
    tracker = _tracker(lineage_count)
    callback.metrics_tracker = tracker
    callback._probe = lambda n_episodes, label: 0.9  # type: ignore[method-assign]

    tracker.episode_count = lineage_count + 1_999
    assert callback._on_step() is True
    assert callback.win_rate_curve == []

    tracker.episode_count = lineage_count + 2_000
    assert callback._on_step() is False, "seuil confirmé : arrêt demandé"
    assert callback.budget == 2_000
    assert [episode for episode, _ in callback.win_rate_curve] == [2_000, 2_000]


# ── Validation des origines ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", [-1, 1.5, True, "80000"])
def test_constructors_reject_non_integer_or_negative_origins(bad: Any):
    with pytest.raises(ValueError, match="episode_origin"):
        _pool_callback(episode_origin=bad)
    with pytest.raises(ValueError, match="episode_origin"):
        _exploiter_callback(episode_origin=bad)


def test_stage_episode_is_counted_from_the_origin():
    callback = _exploiter_callback(episode_origin=100)
    callback.metrics_tracker = _tracker(123)
    assert callback._current_episode() == 123
    assert callback._stage_episode() == 23


# ── stage_origin : l'origine est celle de l'ARCHIVE SOURCE, pas du checkpoint repris ───────────


def _write_sb3_like_zip(path: Path, num_timesteps: int) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data", json.dumps({"num_timesteps": num_timesteps, "ent_coef": 0.01}))


def test_stage_origin_reads_the_source_archive_not_the_resumed_checkpoint(tmp_path: Path):
    """E1 `from:P3` repris par `--resume-from` après crash : l'origine reste celle de P3.

    Le canonique porte l'état du checkpoint (680 000 épisodes) ; `stage_origin` doit rendre celui
    de l'archive P3 (530 000), sinon `budget_cap` repartirait du point de crash.
    """
    canonical = tmp_path / "model_Agent.zip"
    _write_sb3_like_zip(canonical, num_timesteps=20_000_000)
    save_run_state(str(canonical), 680_000)
    source = Path(stage_model_path(str(canonical), "P3"))
    _write_sb3_like_zip(source, num_timesteps=P1_NUM_TIMESTEPS)
    save_run_state(str(source), 530_000)

    assert stage_origin(str(canonical), {"init": "from:P3"}) == 530_000


def test_stage_origin_is_zero_for_a_new_stage(tmp_path: Path):
    assert stage_origin(str(tmp_path / "model_Agent.zip"), {"init": "new"}) == 0


def test_stage_origin_refuses_a_missing_source_archive(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="from:P3"):
        stage_origin(str(tmp_path / "model_Agent.zip"), {"init": "from:P3"})


# ── PoolEarlyStoppingCallback : sonde baseline au démarrage en warm start ──────────────────────


def test_pool_warm_start_fires_baseline_probe_at_stage_episode_zero():
    """Warm start : _on_training_start déclenche UNE sonde baseline à _stage_episode() == 0.

    Sans ce point, la première sonde normale (à eval_freq_episodes DE L'ÉTAPE) est lue sans
    référence — cause directe des investigations 2026-09-05/06 (0,347 lu comme chute depuis 0,472).
    """
    episode_origin = P2_EPISODE_OFFSET
    callback = _pool_callback(episode_origin=episode_origin)
    tracker = _tracker(episode_origin)
    callback.metrics_tracker = tracker

    probe_calls: List[int] = []

    def fake_probe(full_pool: bool = True) -> dict:
        probe_calls.append(callback._stage_episode())
        return {label: 0.50 for _, label in callback.pool_archives}

    callback._probe = fake_probe  # type: ignore[method-assign]

    callback._on_training_start()

    assert probe_calls == [0], "la baseline doit sonder exactement à _stage_episode() == 0"
    assert callback.stop_verdict is None, "la baseline ne prend AUCUNE décision d'arrêt"
    assert callback._next_probe_episode == 10_000, "_next_probe_episode doit rester inchangé"


def test_pool_warm_start_baseline_above_threshold_does_not_trigger_early_stop():
    """Baseline très au-dessus des seuils de promotion : c'est un point de référence, pas une éval.

    Elle n'entre NI dans l'historique glissant NI dans un verdict — sans quoi une étape serait
    promue sur la seule mesure de son propre modèle de départ, avant d'avoir joué un épisode.
    """
    episode_origin = P2_EPISODE_OFFSET
    callback = _pool_callback(episode_origin=episode_origin)
    callback.metrics_tracker = _tracker(episode_origin)
    callback._probe = lambda full_pool=True: {  # type: ignore[method-assign]
        label: 0.60 for _, label in callback._archives_for(full_pool)
    }

    callback._on_training_start()

    assert callback.stop_verdict is None
    assert callback._probe_score_history == {}
    assert callback._next_probe_episode == 10_000


def test_pool_fresh_run_does_not_fire_baseline_probe():
    """Run neuf (episode_origin == 0) : _on_training_start ne sonde pas."""
    callback = _pool_callback()
    callback.metrics_tracker = _tracker(0)

    probe_calls: List[int] = []
    callback._probe = lambda full_pool=True: probe_calls.append(0) or {}  # type: ignore[method-assign]

    callback._on_training_start()

    assert probe_calls == [], "aucune sonde baseline sur un run neuf"


def test_pool_warm_start_baseline_is_idempotent_across_multiple_learn_calls():
    """SB3 appelle _on_training_start à chaque learn() : la baseline ne tire qu'une fois.

    La boucle budgétée de train_with_scenario_rotation enchaîne un learn() par tranche de
    quatre updates — sans flag idempotent, _probe() serait appelée des dizaines de fois.
    """
    episode_origin = P2_EPISODE_OFFSET
    callback = _pool_callback(episode_origin=episode_origin)
    callback.metrics_tracker = _tracker(episode_origin)

    probe_calls: List[int] = []

    def fake_probe(full_pool: bool = True) -> dict:
        probe_calls.append(callback._stage_episode())
        return {label: 0.5 for _, label in callback.pool_archives}

    callback._probe = fake_probe  # type: ignore[method-assign]

    for _ in range(5):
        callback._on_training_start()

    assert probe_calls == [0], "exactement une sonde baseline quel que soit le nombre de learn()"
