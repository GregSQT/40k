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
from typing import Tuple

from tests.unit.ai._fabriques import ppo_update_stats, tracker_avec_writer_espion

#: Jumelles declarees par la docstring de `log_critical_dashboard` : meme mesure, l'une lissee
#: sur 20 updates et l'autre brute. Elles n'ont d'interet que lues cote a cote, donc sur la
#: MEME abscisse.
_JUMELLES: Tuple[Tuple[str, str], ...] = (
    ("00_critical/h_explained_variance", "00_critical/m_explained_var"),
    ("00_critical/j_approx_kl", "00_critical/l_approx_kl_max"),
)

#: Abscisse volontairement eloignee de 0 et des valeurs du dump d'update : une egalite
#: accidentelle rendrait les assertions muettes.
_EPISODE_COUNT = 4_242


def _tracker(tmp_path: Path):
    """Tracker REEL a writer espionne, amorce pour que le tableau de bord ait de quoi ecrire."""
    t, writer = tracker_avec_writer_espion(tmp_path, episode_count=_EPISODE_COUNT)
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
    t, writer = _tracker(tmp_path)

    t.log_training_metrics(ppo_update_stats())
    t.log_critical_dashboard()

    emis = writer.tags()
    for lisse, brut in _JUMELLES:
        assert lisse in emis and brut in emis, (
            f"jumelle absente du writer : {lisse}={lisse in emis}, {brut}={brut in emis} — "
            "le verrou ne comparerait rien"
        )
        axes_lisse = {s for tag, _v, s in writer.scalars if tag == lisse}
        axes_brut = {s for tag, _v, s in writer.scalars if tag == brut}
        assert axes_lisse == axes_brut == {_EPISODE_COUNT}, (
            f"{lisse} sur {axes_lisse} et {brut} sur {axes_brut} : deux abscisses pour une "
            f"meme mesure (attendu {{episode_count={_EPISODE_COUNT}}})"
        )


def test_le_chemin_d_update_ppo_date_tout_en_episodes(tmp_path: Path) -> None:
    """VERROU 2 : pas un seul scalaire du chemin d'update ne repart sur l'axe des pas.

    Verrou plus large que le precedent : il couvre aussi les tags qui n'ont pas de jumelle
    (`training_diagnostic/entropy_coef`, `training_diagnostic/n_updates`) et les huit lignes
    `thresholds/*`, qui n'ont de sens que superposees aux courbes qu'elles annotent.
    """
    t, writer = _tracker(tmp_path)

    # Deux updates : le premier consomme le sentinel `_last_ppo_health_capture = -1`, le second
    # fait passer les lignes `thresholds/*` (gatees par `ppo_capture_count > 0`).
    for _ in range(2):
        t.log_training_metrics(ppo_update_stats())
        t.log_critical_dashboard()

    assert writer.scalars, "aucun scalaire emis : le verrou ne regarderait rien"
    assert any(tag.startswith("thresholds/") for tag, _v, _s in writer.scalars), (
        "aucune ligne de seuil emise : le cas le plus expose au desalignement n'est pas couvert"
    )
    hors_axe = sorted({
        (tag, step) for tag, _v, step in writer.scalars if step != _EPISODE_COUNT
    })
    assert hors_axe == [], (
        f"scalaires dates hors de l'axe des episodes ({_EPISODE_COUNT}) : {hors_axe}"
    )
