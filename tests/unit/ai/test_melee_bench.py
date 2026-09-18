"""Verrou de `scripts/melee_bench.py` : une partie bot contre bot, sondes non vacantes.

Le scénario est `MELEE_SCENARIO` (paire pré-engagée + charge sûre) : c'est le seul du dépôt où
la phase de combat se joue à coup sûr, donc où « au moins une activation de mêlée mesurée » est
une assertion et pas un pari. Le banc de référence, lui, se joue sur le scénario d'entraînement
(`--scenario` par défaut) ; le test n'exerce que le chemin de mesure.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.unit.engine._melee_scenario import MELEE_SCENARIO


@pytest.fixture()
def melee_scenario_file(tmp_path: Path) -> str:
    path = tmp_path / "melee.json"
    path.write_text(json.dumps(MELEE_SCENARIO))
    return str(path)


def test_run_bench_one_game_measures_the_fight(melee_scenario_file: str, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("W40K_BOARD_PATH", "board/44x60x1")
    from scripts.melee_bench import _PLAYER_COUNTERS, run_bench

    out = tmp_path / "bench.json"
    report = run_bench(n_episodes=1, scenario_file=melee_scenario_file, out_path=str(out), workers=1)

    # Structure : les compteurs promis existent pour les deux joueurs, et le JSON est le rapport.
    for p in ("1", "2"):
        assert set(_PLAYER_COUNTERS) <= set(report["by_player"][p])
        assert "derived" in report["by_player"][p]
    assert json.loads(out.read_text(encoding="utf-8"))["totals"] == report["totals"]
    assert report["meta"]["board_path"] == "board/44x60x1"
    assert report["meta"]["engine_commit"]

    # Non-vacuité : la partie s'est jouée (un vainqueur, ≥ 1 tour) et la mêlée a été MESURÉE.
    assert len(report["episodes"]) == 1
    assert report["episodes"][0]["winner"] in (1, 2, 0)
    assert report["episodes"][0]["turns"] >= 1
    totals = report["totals"]
    assert totals["fight_activations"] >= 1, "aucune activation de mêlée sondée sur un scénario pré-engagé"
    assert totals["models_engaged"] >= 1
    assert totals["attacks_possible"] >= totals["attacks_declared"] > 0
    assert totals["charges_declared"] >= 1
    # Chaque figurine d'un pile-in journalisé est classée exactement une fois.
    assert (
        totals["after_pile_in_contact"] + totals["after_pile_in_engaged"] + totals["after_pile_in_out"]
    ) >= 1
    assert sum(report["by_player"][p]["wins"] for p in ("1", "2")) == report["by_seat"]["agent_seat"]["wins"] + report["by_seat"]["opponent_seat"]["wins"]


def test_run_bench_refuses_unfixed_resolution(melee_scenario_file: str, monkeypatch):
    monkeypatch.delenv("W40K_BOARD_PATH", raising=False)
    from scripts.melee_bench import run_bench

    with pytest.raises(RuntimeError, match="W40K_BOARD_PATH"):
        run_bench(n_episodes=1, scenario_file=melee_scenario_file, out_path=None)


def test_probe_restores_the_engine_after_the_run(melee_scenario_file: str, monkeypatch):
    """Les sondes sont retirées après la tranche : un second banc (ou un test suivant) ne doit
    pas mesurer deux fois."""
    monkeypatch.setenv("W40K_BOARD_PATH", "board/44x60x1")
    import engine.action_log_utils as alu
    import engine.phase_handlers.fight_handlers as fh
    import engine.phase_handlers.shared_utils as su
    from scripts.melee_bench import run_bench

    before = (alu._append_entry, fh.build_manual_fight_allocation, su.squad_consolidate_plan_with_targets,
              fh.fight_v11_consolidation_freeze_new_foes)
    run_bench(n_episodes=1, scenario_file=melee_scenario_file, out_path=None, workers=1)
    after = (alu._append_entry, fh.build_manual_fight_allocation, su.squad_consolidate_plan_with_targets,
             fh.fight_v11_consolidation_freeze_new_foes)
    assert before == after
    assert os.environ["W40K_BOARD_PATH"] == "board/44x60x1"
