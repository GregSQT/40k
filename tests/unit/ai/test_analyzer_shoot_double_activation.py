"""Marqueur d'activation SHOOT (10.02) — « each unit can only shoot once per Shooting phase ».

SHOT est émis par ATTAQUE (des dizaines par activation), pas par activation ; c'est le PREMIER
SHOT d'un nouvel acteur qui constitue la frontière d'activation. Avant ce chantier, la clé
`double_activation_by_phase['SHOOT']` n'était jamais incrémentée — 10.02 n'était pas contrôlé.

Mécanisme : `shoot_last_activator` suit le dernier acteur de la phase SHOOT. Dès qu'un SHOT
arrive avec `actor_id != shoot_last_activator`, c'est une nouvelle activation ; si l'unité a déjà
activé dans cette phase (`phase_activation_seen`), c'est un doublon. Les tirs CONSÉCUTIFS de la
même escouade ont `shoot_last_activator == actor_id` → pas de faux positif.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import ai.analyzer as an
from tests.unit.ai._fabriques import entete_step_log

# Trois unités : 1 et 2 (P1, tireurs), 101 (P2, cible).
# Positionnées loin pour éviter tout contrôle d'engagement ou de LoS.
_UNITS = (
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (5,5), HP_MAX=2 "
    "[MODELS: 1#0@(5,5,z0)]\n"
    "[10:00:00] Unit 2 (Intercessor) P1: Starting position (5,10), HP_MAX=2 "
    "[MODELS: 2#0@(5,10,z0)]\n"
    "[10:00:00] Unit 101 (Intercessor) P2: Starting position (5,30), HP_MAX=2 "
    "[MODELS: 101#0@(5,30,z0)]\n"
)
_END = (
    "[12:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, "
    "Total=0, Duration=1.000s"
)
_COMMON: dict[str, Any] = dict(
    units=_UNITS,
    inches_to_subhex=1,
    board="cols=44 rows=60",
    walls="none",
    metric_ranged="hex",
    rosters="scale=500pts AGENT_PLAYER=1 AGENT=a (a.json) OPPONENT=o (o.json)",
    objectives=None,
)


def _run(tmp_path: Path, body: list[str]) -> dict:
    path = tmp_path / "step.log"
    path.write_text(
        entete_step_log("\n".join(body) + "\n" + _END + "\n", **_COMMON),
        encoding="utf-8",
    )
    return an.parse_step_log(str(path))


def _shot(turn: int, player: int, uid: str, scol: int, srow: int) -> str:
    """Ligne SHOT minimale — pas de weapon pour rester hors du bloc weapon_match."""
    return (
        f"[12:00:0{turn}] E1 T{turn} P{player} SHOOT : "
        f"Unit {uid}({scol},{srow}) SHOT Unit 101(5,30) Dmg:0HP [SUCCESS]"
    )


def test_salve_de_plusieurs_tirs_par_la_meme_unite_nest_pas_un_doublon(tmp_path: Path) -> None:
    """VERROU : tirs consécutifs d'une même escouade = une seule activation.

    shoot_last_activator est mis à jour après le premier tir de l'escouade ; les tirs suivants
    voient shoot_last_activator == actor_id et ne comptent pas comme une nouvelle activation.
    """
    stats = _run(tmp_path, [
        _shot(1, 1, "1", 5, 5),   # première activation de Unit 1
        _shot(1, 1, "1", 5, 5),   # deuxième tir : même acteur, pas un doublon
        _shot(1, 1, "1", 5, 5),   # troisième tir : même acteur, pas un doublon
    ])
    assert stats["double_activation_by_phase"]["SHOOT"] == 0, stats["double_activation_by_phase"]


def test_unite_qui_tire_deux_fois_dans_la_meme_phase_est_detectee(tmp_path: Path) -> None:
    """Le contrôle doit attraper le vrai défaut : une unité qui tire après qu'une autre ait agi.

    Séquence : Unit 1 → Unit 2 → Unit 1 à nouveau. La reprise de Unit 1 est une double
    activation car shoot_last_activator porte l'ID de Unit 2 au moment du troisième tir.
    """
    stats = _run(tmp_path, [
        _shot(1, 1, "1", 5, 5),    # activation Unit 1 — shoot_last_activator = "1"
        _shot(1, 1, "2", 5, 10),   # activation Unit 2 — shoot_last_activator = "2"
        _shot(1, 1, "1", 5, 5),    # Unit 1 tire à nouveau : shoot_last_activator "2" ≠ "1" → doublon
    ])
    assert stats["double_activation_by_phase"]["SHOOT"] == 1, stats["double_activation_by_phase"]
