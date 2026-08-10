"""Tests — ventilation des courbes 00_critical par MODE DE DEPLOIEMENT.

CE QUE CES TESTS VERROUILLENT. `deployment_mode_schedule` fait monter la part d'episodes joues
en deploiement ACTIF de 0% a 80% sur la duree du run. La population mesuree change donc en
continu pendant tout l'entrainement, alors que l'EVALUATION impose toujours un deploiement. Une
courbe agregee melange les deux populations dans des proportions mouvantes : elle s'aplatit
quand l'agent progresse mais que la tache durcit a la meme vitesse, ce qui est indiscernable
d'un agent qui plafonne. C'est cette confusion — observee sur un run de 50 000 episodes, ou les
metriques d'episode stagnaient pendant que les scores d'evaluation acceleraient — que la
ventilation leve.

CE QUI SE CASSE EN SILENCE ICI, et que chaque test cible :
  * un episode impute au MAUVAIS mode : les deux series se contaminent et l'ecart disparait ;
  * un episode SANS mode (scheduler inactif) impute d'office a `auto` : la serie se remplit
    d'episodes qu'aucun tirage n'y a places ;
  * une courbe ventilee emise depuis `log_critical_dashboard` : elle serait decalee d'un
    episode, ce dashboard tournant AVANT `log_tactical_metrics` qui produit les valeurs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from ai.metrics_tracker import W40KMetricsTracker


class _RecordingWriter:
    """Doublure typee du writer TensorBoard : conserve TOUTES les ecritures, doublons inclus."""

    def __init__(self) -> None:
        self.scalars: List[Tuple[str, float, int]] = []

    def add_scalar(self, key: str, value: float, step: int, /) -> None:
        self.scalars.append((key, value, step))

    def add_custom_scalars(self, layout: Dict[str, Any], /) -> None:
        pass

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


def _tracker(tmp_path: Any, window: int = 1) -> Tuple[W40KMetricsTracker, _RecordingWriter]:
    """Vrai constructeur : un attribut retire du __init__ doit se voir ici.

    Fenetres ramenees a `window` : ces tests portent sur l'appariement episode <-> serie, pas
    sur la taille des fenetres de production (500), qui obligerait a rejouer des centaines
    d'episodes par cas.
    """
    tracker = W40KMetricsTracker(
        "ArmageddonAgent", log_dir=str(tmp_path), show_banner=False,
        perf_window=window, perf_window_fast=window,
    )
    tracker.writer = _RecordingWriter()
    tracker.episode_count = 1
    return tracker, tracker.writer  # type: ignore[return-value]


def _episode(
    tracker: W40KMetricsTracker,
    *,
    mode: Optional[str],
    reward: float,
    won: bool,
) -> None:
    """Fin d'episode reelle, allegee des deux methodes qui ne concernent pas la ventilation."""
    tracker.compute_and_log_phase_metrics = lambda: None  # type: ignore[method-assign]
    tracker.log_critical_dashboard = lambda: None  # type: ignore[method-assign]
    tracker.log_episode_end({
        "total_reward": reward,
        "episode_length": 100,
        "winner": 1 if won else 2,
        "controlled_player": 1,
        "deployment_mode": mode,
    })


def _values(recording: _RecordingWriter, tag: str) -> List[float]:
    return [value for key, value, _step in recording.scalars if key == tag]


def test_reward_and_win_are_routed_to_the_series_of_their_own_mode() -> None:
    """Chaque episode alimente la serie de SON mode, et aucune autre.

    Le montage discrimine une imputation croisee : les deux modes portent des recompenses
    disjointes (10 vs 90). Une seule serie recevant les deux, ou les deux se contaminant,
    produirait des valeurs melangees au lieu des deux constantes attendues.
    """
    tracker, recording = _tracker("/tmp", window=1)  # noqa: S108 — SummaryWriter jamais ecrit
    _episode(tracker, mode="active", reward=10.0, won=True)
    _episode(tracker, mode="auto", reward=90.0, won=False)
    _episode(tracker, mode="active", reward=10.0, won=True)

    assert _values(recording, "00_critical/p_reward_deploy_active") == [10.0, 10.0]
    assert _values(recording, "00_critical/p_reward_deploy_auto") == [90.0]
    assert _values(recording, "00_critical/r_win_rate_deploy_active") == [1.0, 1.0]
    assert _values(recording, "00_critical/r_win_rate_deploy_auto") == [0.0]


def test_an_episode_without_mode_feeds_no_series_at_all() -> None:
    """Scheduler inactif -> aucune courbe ventilee, PAS un versement d'office dans `auto`.

    C'est le defaut le plus tentant : `None` signifie que le mode est laisse au JSON du
    scenario, donc souvent fixe dans les faits. L'imputer a `auto` remplirait la serie
    d'episodes qu'aucun tirage n'y a places, et l'ecart mesure entre les deux populations ne
    voudrait plus rien dire.
    """
    tracker, recording = _tracker("/tmp", window=1)  # noqa: S108
    _episode(tracker, mode=None, reward=10.0, won=True)

    ventilated = [
        key for key, _v, _s in recording.scalars
        if "_deploy_" in key or key.endswith("deploy_active_share")
    ]
    assert ventilated == [], f"aucune courbe ventilee attendue, obtenu {ventilated}"


def test_active_share_tracks_the_real_proportion_of_active_episodes() -> None:
    """La part d'episodes actifs est la variable EXPLICATIVE : sans elle, l'ecart est illisible.

    Fenetre de 4, quatre episodes dont trois actifs -> 0.75. Un compteur cumulatif au lieu
    d'une fenetre glissante donnerait la meme valeur ici ; c'est le test de fenetre generique
    (`test_no_point_is_emitted_before_the_window_is_full`) qui couvre cet aspect-la.
    """
    tracker, recording = _tracker("/tmp", window=4)  # noqa: S108
    for mode in ("active", "auto", "active", "active"):
        _episode(tracker, mode=mode, reward=1.0, won=True)

    assert _values(recording, "00_critical/s_deploy_active_share") == [0.75]


def test_objectives_held_diff_is_ventilated_through_emit_game() -> None:
    """La courbe tactique passe par `_emit_game`, appele APRES `log_episode_end`.

    C'est l'ordre reel du callback (log_episode_end puis log_tactical_metrics). Il impose que
    le mode soit pose en tete de log_episode_end : pose plus tard, ou lu depuis
    log_critical_dashboard, la valeur ventilee serait celle de l'episode PRECEDENT.
    """
    tracker, recording = _tracker("/tmp", window=1)  # noqa: S108
    _episode(tracker, mode="active", reward=1.0, won=True)
    tracker._emit_game("01_VP/d_objectives_held_diff", "objectives_held_diff", 2.0)
    _episode(tracker, mode="auto", reward=1.0, won=True)
    tracker._emit_game("01_VP/d_objectives_held_diff", "objectives_held_diff", -3.0)

    assert _values(recording, "00_critical/q_obj_held_diff_deploy_active") == [2.0]
    assert _values(recording, "00_critical/q_obj_held_diff_deploy_auto") == [-3.0]
    # La courbe agregee reste emise a l'identique : la ventilation s'ajoute, ne remplace pas.
    assert _values(recording, "01_VP/d_objectives_held_diff") == [2.0, -3.0]


def test_an_unknown_mode_raises_instead_of_creating_a_silent_bucket() -> None:
    tracker, _recording = _tracker("/tmp", window=1)  # noqa: S108
    with pytest.raises(ValueError, match=r"deployment_mode.*must be one of"):
        _episode(tracker, mode="ACTIVE", reward=1.0, won=True)
