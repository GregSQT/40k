"""Verrous de l'agregation du rapport perf (`python3 engine/perf_timing.py <log>`).

Chacun de ces tests correspond a un defaut qui a REELLEMENT produit un chiffre faux, et qu'aucun
controle ne signalait — le rapport s'affichait, simplement il mentait :

- episodes fusionnes entre processus (compteur `episode_number` par worker, log commun) ;
- dernier episode de chaque processus, tronque par l'arret du run, compte pour un episode entier ;
- ms/ep arrondi AVANT comparaison, donc un gain de 33 % sur une petite ligne affiche +0,0 % ;
- evenement dont toutes les lignes sont `episode=?` : disparaissait du rapport.

Le module s'execute en tant que script (`if __name__ == "__main__"`), donc l'agregation n'est pas
importable : on la charge via `runpy` avec un argv controle, et on relit le `.score.json` produit.
"""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest

PERF_TIMING = Path(__file__).resolve().parents[3] / "engine" / "perf_timing.py"


def _scores(tmp_path: Path, lignes: list[str], nom: str = "perf.log") -> dict:
    """Ecrit un log, lance l'agregateur en mode « un log », rend le `.score.json`."""
    log = tmp_path / nom
    log.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    argv = sys.argv
    sys.argv = ["perf_timing.py", str(log)]
    try:
        runpy.run_path(str(PERF_TIMING), run_name="__main__")
    finally:
        sys.argv = argv
    return json.loads((tmp_path / f"{nom}.score.json").read_text(encoding="utf-8"))


def _ligne(event: str, episode, pid: int, total_s: float, champ: str = "total_s") -> str:
    return f"{event} episode={episode} {champ}={total_s:.9f} pid={pid}"


def test_episodes_distincts_par_processus(tmp_path: Path) -> None:
    """Deux workers jouant chacun les episodes 1..3 font SIX episodes, pas trois. Sans le champ
    `pid`, l'agregation les fusionnait et divisait par 3 : le cout par episode doublait."""
    lignes = [_ligne("MOVE_POOL_BUILD", ep, pid, 0.010)
              for pid in (7, 8) for ep in (1, 2, 3)]
    scores = _scores(tmp_path, lignes)
    # 3 episodes par worker, moins le dernier de chacun (tronque) = 2 x 2 retenus.
    assert scores["__n_processes"] == 2
    assert scores["__n_episodes"] == 4


def test_dernier_episode_de_chaque_processus_ecarte(tmp_path: Path) -> None:
    """Il est coupe net par l'arret du run : une fraction de temps au numerateur, un episode
    entier au denominateur. Le garder tirait ms/ep vers le bas."""
    lignes = [_ligne("MOVE_POOL_BUILD", ep, 7, 0.010) for ep in (1, 2, 3)]
    scores = _scores(tmp_path, lignes)
    assert scores["__n_episodes"] == 2
    assert scores["__truncated_episodes"] == 1
    assert scores["MOVE_POOL_BUILD"]["calls"] == 2, "les lignes de l'episode tronque sont restees"
    assert scores["MOVE_POOL_BUILD"]["ms_per_episode"] == pytest.approx(10.0)


def test_un_seul_episode_par_processus_supprime_le_ms_par_episode(tmp_path: Path) -> None:
    """Cas limite : tous les episodes sont le dernier de leur worker, donc tous tronques. Il ne
    reste aucun episode complet — le rapport doit le DIRE, pas afficher un ms/ep de fractions."""
    lignes = [_ligne("MOVE_POOL_BUILD", 1, pid, 0.010) for pid in (7, 8)]
    scores = _scores(tmp_path, lignes)
    assert scores["__n_episodes"] == 0
    assert scores["__all_episodes_truncated"] is True
    assert scores["__truncated_episodes"] == 2
    # ... mais le rapport ne doit pas etre VIDE pour autant : filtrer ici supprimerait toutes
    # les lignes, mettrait `__total_s` a 0, et le mode diff etiquetterait « absent » des
    # evenements pourtant presents dans le log. Sans ms/ep a produire, l'exclusion n'a plus
    # d'objet et les sommes brutes restent la seule chose lisible.
    assert "MOVE_POOL_BUILD" in scores, "le rapport est vide alors que le log a des lignes"
    assert scores["MOVE_POOL_BUILD"]["calls"] == 2
    assert "ms_per_episode" not in scores["MOVE_POOL_BUILD"]
    assert scores["__total_calls"] == 2


def test_lignes_sans_episode_exploitable_ne_disparaissent_pas(tmp_path: Path) -> None:
    """Des emetteurs ecrivent `episode=?` quand `episode_number` manque du game_state. Ces
    lignes sortent du ratio ms/ep — mais un evenement qui n'a que ca s'evaporait du rapport."""
    lignes = [_ligne("MOVE_POOL_BUILD", ep, 7, 0.010) for ep in (1, 2, 3)]
    lignes += [_ligne("CHARGE_DEST_BFS", "?", 7, 0.005) for _ in range(2)]
    scores = _scores(tmp_path, lignes)
    assert "CHARGE_DEST_BFS" in scores, "l'evenement a disparu du rapport"
    assert scores["CHARGE_DEST_BFS"]["calls"] == 2
    assert "ms_per_episode" not in scores["CHARGE_DEST_BFS"], "un ms/ep a ete calcule sans episode"
    assert scores["__undated_records"] == 2


def test_lignes_d_episodes_tronques_ne_repassent_pas_par_le_repli(tmp_path: Path) -> None:
    """Un evenement entierement contenu dans des episodes ecartes ne doit PAS etre reintroduit
    par le repli des lignes non datees : sa population differerait de toutes les autres lignes,
    et l'etiquette `episode=?` accuserait un emetteur qui n'a rien fait."""
    lignes = [_ligne("MOVE_POOL_BUILD", ep, 7, 0.010) for ep in (1, 2, 3)]
    lignes += [_ligne("CHARGE_DEST_BFS", 3, 7, 0.005)]  # episode 3 = dernier, donc ecarte
    scores = _scores(tmp_path, lignes)
    assert "CHARGE_DEST_BFS" not in scores
    assert scores["__undated_records"] == 0, "une ligne datee a ete comptee comme `episode=?`"


def test_ms_par_episode_garde_sa_precision(tmp_path: Path) -> None:
    """Stocke arrondi a 2 decimales, il quantifiait par pas de 0,01 ms : sur une ligne a
    0,03 ms/ep (ordre de grandeur reel de CHARGE_DEST_BFS), un gain de 33 % s'affichait +0,0 %."""
    # Valeur DELIBEREMENT non ronde : 0,0335 ms/ep. Un arrondi a 2 decimales la ramenerait a
    # 0,03 — indiscernable de 0,0301 comme de 0,0349, donc un ecart de 15 % invisible. Tester
    # avec 0,03 pile ne prouverait rien : la valeur est son propre arrondi.
    lignes = [_ligne("MOVE_POOL_BUILD", ep, 7, 0.010) for ep in (1, 2, 3)]
    lignes += [_ligne("CHARGE_DEST_BFS", ep, 7, 0.0000335) for ep in (1, 2, 3)]
    scores = _scores(tmp_path, lignes)
    assert scores["CHARGE_DEST_BFS"]["ms_per_episode"] == pytest.approx(0.0335, abs=1e-9)
    assert scores["CHARGE_DEST_BFS"]["sum_s"] == pytest.approx(0.000067, abs=1e-9)


def test_pid_present_sur_chaque_ligne_ecrite(tmp_path: Path, monkeypatch) -> None:
    """L'etiquetage par processus est ce qui rend le denominateur fiable. Il est pose au point
    de passage unique des ecritures — s'il disparait, tout le reste redevient faux en silence."""
    import os

    import engine.perf_timing as pt

    cible = tmp_path / "ecriture.log"
    monkeypatch.setenv("W40K_PERF_TIMING_LOG", str(cible))
    monkeypatch.setattr(pt, "_PERF_FILE_HANDLE", None)
    monkeypatch.setattr(pt, "_PERF_FILE_PATH", None)
    pt.append_perf_timing_line("MOVE_POOL_BUILD episode=1 total_s=0.001")
    pt._flush_perf_file()
    assert cible.read_text(encoding="utf-8").strip().endswith(f"pid={os.getpid()}")
