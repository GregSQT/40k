"""P2 — fin de partie (turn_limit + cohérence méthode victoire).

Contrôles :
- game_turn_exceeded_count : episode_turn > max_turns (lu de game_config).
- win_method_mismatch_count : méthode=elimination mais le perdant a encore des unités vivantes.

max_turns est lu par AnalyzerConfig via config_loader.get_max_turns(). Dans les tests, on forge
une config analytique avec max_turns=3 via un monkeypatch minimal.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import ai.analyzer as an
import config_loader as cl
from tests.unit.ai._fabriques import entete_step_log

_UNITS = (
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (5,5), HP_MAX=4 "
    "[MODELS: 1#0@(5,5,z0) 1#1@(5,6,z0)]\n"
    "[10:00:00] Unit 2 (Intercessor) P2: Starting position (5,30), HP_MAX=4 "
    "[MODELS: 2#0@(5,30,z0) 2#1@(5,31,z0)]\n"
)


def _action(turn: int, player: int, phase: str = "COMMAND", uid: str = "1") -> str:
    return (
        f"[10:00:0{turn}] E1 T{turn} P{player} {phase} : "
        f"Unit {uid}(5,5) WAITED [SUCCESS]"
    )


def _episode_end(winner: int = 1, method: str = "objectives", turn: int = 3) -> str:
    return (
        f"[12:00:09] EPISODE END: Winner={winner}, Method={method}, Actions=0, Steps=0, "
        f"Total=0, Duration=1.000s"
    )


def _run(tmp_path: Path, body: list[str], end_line: str, max_turns: int = 3) -> dict:
    """Tourne parse_step_log avec max_turns patchée."""
    path = tmp_path / "step.log"
    path.write_text(
        entete_step_log(
            "\n".join(body) + "\n" + end_line + "\n",
            units=_UNITS,
            inches_to_subhex=1,
            board="cols=44 rows=60",
            walls="none",
            metric_ranged="hex",
            rosters="scale=500pts AGENT_PLAYER=1 AGENT=a (a.json) OPPONENT=o (o.json)",
            objectives=None,
        ),
        encoding="utf-8",
    )
    with patch.object(cl.ConfigLoader, "get_max_turns", return_value=max_turns):
        return an.parse_step_log(str(path))


def test_partie_dans_les_limites_pas_de_violation(tmp_path: Path) -> None:
    """Tour 3 ≤ max_turns=3 → aucune violation de dépassement."""
    stats = _run(tmp_path, [
        _action(3, 1),
    ], _episode_end(winner=1, method="objectives"))
    assert stats["game_turn_exceeded_count"] == 0, stats["game_turn_exceeded_count"]


def test_tour_superieur_a_max_declenche_compteur(tmp_path: Path) -> None:
    """Tour 4 > max_turns=3 → game_turn_exceeded_count == 1."""
    stats = _run(tmp_path, [
        _action(4, 1),
    ], _episode_end(winner=1, method="objectives"), max_turns=3)
    assert stats["game_turn_exceeded_count"] == 1, stats["game_turn_exceeded_count"]


def test_methode_objectives_ne_declenche_pas_mismatch_check(tmp_path: Path) -> None:
    """Méthode=objectives → le contrôle elimination n'est pas appliqué, 0 mismatch."""
    stats = _run(tmp_path, [
        _action(1, 1),
    ], _episode_end(winner=1, method="objectives"))
    assert stats["win_method_mismatch_count"] == 0, stats["win_method_mismatch_count"]


def test_elimination_avec_perdant_vivant_declenche_mismatch(tmp_path: Path) -> None:
    """Méthode=elimination mais le perdant P2 a encore des unités → incohérence détectée."""
    # Aucune mort de P2 → P2 a encore des unités avec unit_hp > 0 → mismatch.
    stats = _run(tmp_path, [
        _action(1, 1),
    ], _episode_end(winner=1, method="elimination"))
    assert stats["win_method_mismatch_count"] == 1, stats["win_method_mismatch_count"]
