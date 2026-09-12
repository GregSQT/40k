#!/usr/bin/env python3
"""VERROU : les tags par defaut de `--decaying-tags` existent reellement dans un run.

`compute_schedule_diagnostic` ne leve pas sur un tag absent : `points_by_tag.get(tag, [])` rend
une liste vide et le diagnostic sort `{"status": "MISSING"}`. Un defaut qui nomme un tag mort ne
casse donc rien — il rend le diagnostic de rythme MUET, seed apres seed, sans un message.

C'est exactement ce qui est arrive le 2026-09-11 : le tracker a cesse de recopier
`train/learning_rate` sous le nom `training_diagnostic/learning_rate`, et le defaut du script
pointait encore sur la recopie.
"""

from pathlib import Path
from typing import List, Set

import pytest

from tests._chargeur_script import charger_script
from tests.unit.ai._fabriques import ppo_update_stats, tracker_avec_writer_espion


def _defauts_decroissants(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    """Relit le defaut de `--decaying-tags` par le parser lui-meme, sans le recopier ici.

    `parse_args` construit son parser en interne et lit `sys.argv` : le defaut ne s'atteint que
    par un appel, d'ou l'argv minimal qui satisfait les seuls arguments requis.
    """
    module = charger_script("scripts/aggregate_seed_results.py")
    monkeypatch.setattr(
        "sys.argv", ["aggregate_seed_results.py", "--runs-root", ".", "--seeds", "1"]
    )
    return list(module.parse_args().decaying_tags)


def _tags_ecrits_par_le_tracker(tmp_path: Path) -> Set[str]:
    t, writer = tracker_avec_writer_espion(tmp_path)
    t.log_training_metrics(ppo_update_stats())
    return writer.tags()


def test_chaque_tag_decroissant_par_defaut_a_un_ecrivain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chaque defaut est ecrit soit par le tracker, soit par le logger de SB3.

    Les deux ecrivains publient dans le MEME dossier de run (`attach_run_logger`), donc
    `EventAccumulator` les lit tous les deux. `train/*` et `diag/*` sont le namespace de SB3 ;
    tout le reste doit sortir du tracker, ce que ce test constate en le faisant ecrire.
    """
    defauts = _defauts_decroissants(monkeypatch)
    assert defauts, "defaut vide : le verrou ne regarderait rien"

    ecrits = _tags_ecrits_par_le_tracker(tmp_path)
    assert ecrits, "le tracker n'a rien ecrit sur un dump d'update complet"

    orphelins = [
        tag for tag in defauts
        if tag not in ecrits and not tag.startswith(("train/", "diag/", "time/", "rollout/"))
    ]
    assert orphelins == [], (
        f"tags par defaut sans ecrivain : {orphelins} — `compute_schedule_diagnostic` rendra "
        "silencieusement MISSING pour chaque seed"
    )
