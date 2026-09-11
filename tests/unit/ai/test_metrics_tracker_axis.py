#!/usr/bin/env python3
"""VERROU d'abscisse UNIQUE du tracker TensorBoard.

Un meme writer ecrivait ses scalaires sur DEUX abscisses incompatibles : 32 appels a
`add_scalar` dates en `episode_count`, 14 dates en `step_count` (= `model.num_timesteps`).
Mesure sur tensorboard/x1_lineage_ArmageddonAgent_x1/run_20260911-062637 : 331 tags couvrant
80 066 -> 90 827 (episodes) contre 15 tags couvrant 8 866 752 -> 10 025 472 (pas), soit un
facteur ~110 dans un meme fichier d'evenements. Le cas le plus net etait une mesure UNIQUE
publiee sur deux axes : `00_critical/m_explained_var` en pas et sa jumelle declaree
`00_critical/h_explained_variance` en episodes ; idem pour `l_approx_kl_max` et `j_approx_kl`.

Ce fichier verrouille les deux proprietes qui ferment le defaut :
  1. aucune paire de jumelles declaree ne s'ecrit sur deux abscisses ;
  2. tout scalaire emis par le chemin d'update PPO est date en episodes.
"""

from pathlib import Path
from typing import Any, Dict, List, Tuple

from ai.metrics_tracker import W40KMetricsTracker

_AGENT_KEY = "ArmageddonAgent_x1"

#: Jumelles declarees par la docstring de `log_critical_dashboard` : meme mesure, l'une lissee
#: sur 20 updates et l'autre brute. Elles n'ont d'interet que lues cote a cote, donc sur la
#: MEME abscisse.
_JUMELLES: Tuple[Tuple[str, str], ...] = (
    ("00_critical/h_explained_variance", "00_critical/m_explained_var"),
    ("00_critical/j_approx_kl", "00_critical/l_approx_kl_max"),
)

#: Un dump d'update PPO complet, tel que `training_callbacks` le passe depuis
#: `model.logger.name_to_value` (avec `train/ent_coef` injecte par le callback).
_UPDATE_STATS: Dict[str, float] = {
    "train/learning_rate": 3e-4,
    "train/policy_gradient_loss": -0.2,
    "train/value_loss": 0.3,
    "train/entropy_loss": 0.05,
    "train/ent_coef": 0.01,
    "train/clip_fraction": 0.2,
    "train/approx_kl": 0.01,
    "train/approx_kl_max": 0.034,
    "train/explained_variance": 0.42,
    "train/n_updates": 10,
    "train/gradient_norm": 0.8,
    "train/grad_clip_fraction": 0.15,
    "diag/grad_share_policy_mb0": 0.235,
    "time/fps": 100.0,
}


class _RecordingWriter:
    """Writer double : retient (tag, valeur, abscisse) de chaque scalaire."""

    def __init__(self) -> None:
        self.scalars: List[Tuple[str, float, int]] = []

    def add_scalar(self, tag: str, scalar_value: float, global_step: int, /) -> None:
        self.scalars.append((tag, float(scalar_value), int(global_step)))

    def add_custom_scalars(self, layout: Dict[str, Any], /) -> None:
        return None

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


def _tracker(tmp_path: Path, episode_count: int) -> Tuple[W40KMetricsTracker, _RecordingWriter]:
    """Un VRAI tracker (pas une doublure d'etat) dont seul le writer est espionne.

    Le tracker construit par `__init__` est le seul qui prouve quelque chose sur l'abscisse :
    une doublure d'etat recopierait a la main les compteurs que ce test interroge.
    """
    t = W40KMetricsTracker(
        _AGENT_KEY,
        log_dir=str(tmp_path),
        show_banner=False,
        perf_window=1,
        perf_window_fast=1,
    )
    t.writer.close()
    writer = _RecordingWriter()
    t.writer = writer
    # Abscisse volontairement eloignee de 0 et des valeurs de `_UPDATE_STATS` : une egalite
    # accidentelle rendrait les assertions muettes.
    t.episode_count = episode_count
    # `log_critical_dashboard` sort tot si aucun episode n'a ete joue, et les courbes de sante
    # PPO sont gardees par `len(liste) >= 1`. Sans cette amorce le test serait VERT VACANT.
    t.all_episode_rewards = [1.0]
    return t, writer


def test_aucune_jumelle_declaree_ne_s_ecrit_sur_deux_abscisses(tmp_path: Path) -> None:
    """VERROU 1 : les deux paires de jumelles partagent leur abscisse.

    `m_explained_var` partait a `step_count` (millions de pas) et `h_explained_variance` a
    `episode_count` (dizaines de milliers d'episodes) : superposer la valeur brute et sa version
    lissee etait impossible, alors que c'est la seule raison pour laquelle les deux existent.
    """
    episode_count = 4_242
    t, writer = _tracker(tmp_path, episode_count)

    t.log_training_metrics(dict(_UPDATE_STATS))
    t.log_critical_dashboard()

    emis = {tag for tag, _v, _s in writer.scalars}
    for lisse, brut in _JUMELLES:
        assert lisse in emis and brut in emis, (
            f"jumelle absente du writer : {lisse}={lisse in emis}, {brut}={brut in emis} — "
            "le verrou ne comparerait rien"
        )
        axes_lisse = {s for tag, _v, s in writer.scalars if tag == lisse}
        axes_brut = {s for tag, _v, s in writer.scalars if tag == brut}
        assert axes_lisse == axes_brut == {episode_count}, (
            f"{lisse} sur {axes_lisse} et {brut} sur {axes_brut} : deux abscisses pour une "
            f"meme mesure (attendu {{episode_count={episode_count}}})"
        )


def test_le_chemin_d_update_ppo_date_tout_en_episodes(tmp_path: Path) -> None:
    """VERROU 2 : pas un seul scalaire du chemin d'update ne repart sur l'axe des pas.

    Verrou plus large que le precedent : il couvre aussi les tags qui n'ont pas de jumelle
    (`training_diagnostic/entropy_coef`, `training_diagnostic/n_updates`) et les huit lignes
    `thresholds/*`, qui n'ont de sens que superposees aux courbes qu'elles annotent.
    """
    episode_count = 4_242
    t, writer = _tracker(tmp_path, episode_count)

    # Deux updates : le premier consomme le sentinel `_last_ppo_health_capture = -1`, le second
    # fait passer les lignes `thresholds/*` (gatees par `ppo_capture_count > 0`).
    for _ in range(2):
        t.log_training_metrics(dict(_UPDATE_STATS))
        t.log_critical_dashboard()

    assert writer.scalars, "aucun scalaire emis : le verrou ne regarderait rien"
    assert any(tag.startswith("thresholds/") for tag, _v, _s in writer.scalars), (
        "aucune ligne de seuil emise : le cas le plus expose au desalignement n'est pas couvert"
    )
    hors_axe = sorted({
        (tag, step) for tag, _v, step in writer.scalars if step != episode_count
    })
    assert hors_axe == [], (
        f"scalaires dates hors de l'axe des episodes ({episode_count}) : {hors_axe}"
    )
