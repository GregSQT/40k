"""07.02 — ordre des phases et alternance des joueurs.

Les phases doivent se succéder dans l'ordre COMMAND→MOVE→SHOOT→CHARGE→FIGHT au sein d'un tour.
Le joueur qui ouvre COMMAND doit alterner entre tours consécutifs.

Mécanisme : `phase_seq_current_turn` accumule les phases vues dans le tour courant.
`_check_phase_seq` est appelé au changement de tour (et à EPISODE END pour le dernier tour).
"""
from __future__ import annotations

from pathlib import Path

import ai.analyzer as an
from tests.unit.ai._fabriques import entete_step_log

_UNITS = (
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (5,5), HP_MAX=2 "
    "[MODELS: 1#0@(5,5,z0)]\n"
    "[10:00:00] Unit 2 (Intercessor) P2: Starting position (5,30), HP_MAX=2 "
    "[MODELS: 2#0@(5,30,z0)]\n"
)
_END = (
    "[12:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, "
    "Total=0, Duration=1.000s"
)


def _action(turn: int, player: int, phase: str, uid: str = "1") -> str:
    return (
        f"[10:00:0{turn}] E1 T{turn} P{player} {phase} : "
        f"Unit {uid}(5,5) WAITED [SUCCESS]"
    )


def _run(tmp_path: Path, body: list[str]) -> dict:
    path = tmp_path / "step.log"
    path.write_text(
        entete_step_log(
            "\n".join(body) + "\n" + _END + "\n",
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
    return an.parse_step_log(str(path))


def test_ordre_correct_ne_declenche_pas_de_violation(tmp_path: Path) -> None:
    """VERROU : COMMAND→MOVE→SHOOT = séquence valide, 0 violation."""
    stats = _run(tmp_path, [
        _action(1, 1, "COMMAND"),
        _action(1, 1, "MOVE"),
        _action(1, 1, "SHOOT"),
    ])
    assert stats["phase_order_violations"] == 0, stats["phase_order_violations"]


def test_retour_en_arriere_declenche_une_violation(tmp_path: Path) -> None:
    """07.02 — MOVE après SHOOT dans le même tour = violation d'ordre."""
    stats = _run(tmp_path, [
        _action(1, 1, "COMMAND"),
        _action(1, 1, "SHOOT"),
        _action(1, 1, "MOVE"),   # antérieur à SHOOT → violation
    ])
    assert stats["phase_order_violations"] == 1, stats["phase_order_violations"]



def test_sequence_isolee_a_un_seul_tour_validee_a_episode_end(tmp_path: Path) -> None:
    """La séquence du DERNIER tour est validée à EPISODE END, pas seulement au changement de tour."""
    # Un seul tour → _check_phase_seq déclenché seulement à EPISODE END.
    stats = _run(tmp_path, [
        _action(1, 1, "COMMAND"),
        _action(1, 1, "FIGHT"),    # saute MOVE/SHOOT/CHARGE
        _action(1, 1, "MOVE"),     # retour en arrière → violation
    ])
    assert stats["phase_order_violations"] == 1, stats["phase_order_violations"]


def test_alternance_player_correcte_pas_de_violation(tmp_path: Path) -> None:
    """P1 ouvre T1, P2 ouvre T2 → alternance correcte, 0 violation."""
    stats = _run(tmp_path, [
        _action(1, 1, "COMMAND"),   # T1 : P1 ouvre COMMAND
        _action(2, 2, "COMMAND"),   # T2 : P2 ouvre COMMAND
    ])
    assert stats["player_alternation_violations"] == 0, stats["player_alternation_violations"]


def test_meme_joueur_deux_tours_consecutifs_declenche_violation(tmp_path: Path) -> None:
    """07.02 alternance — P1 ouvre COMMAND deux tours de suite = violation."""
    stats = _run(tmp_path, [
        _action(1, 1, "COMMAND"),   # T1 : P1 ouvre
        _action(2, 1, "COMMAND"),   # T2 : P1 ouvre encore → violation attendue au T3-change
        _action(3, 2, "COMMAND"),   # T3 : P2 ouvre (déclenche le check de T2)
    ])
    assert stats["player_alternation_violations"] == 1, stats["player_alternation_violations"]
