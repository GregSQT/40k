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
from textwrap import dedent
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

# En-tête minimal partagé entre les deux épisodes du log multi-épisodes.
_EPISODE_HEADER = (
    "[10:00:00] Scenario: scenario_bot-01\n"
    "[10:00:00] Opponent: SelfplayBot\n"
    "[10:00:00] Rosters: scale=500pts AGENT_PLAYER=1 AGENT=a (a.json) OPPONENT=o (o.json)\n"
    "[10:00:00] Walls: none\n"
    "[10:00:00] Board: cols=44 rows=60 inches_to_subhex=1 hex_radius=2.78 margin=1\n"
    "[10:00:00] Run rules: cohesion.global_subhex=9 cohesion.min_neighbors=1 "
    "cohesion.model_subhex=2 engagement_zone_subhex=2 engagement_zone_vertical_inches=5.0 "
    "metric.engagement=hex metric.ranged=hex move.thru_enemy=False "
    "move.thru_ez=True move.thru_friendly=True\n"
    + _UNITS
    + "[10:00:00] === ACTIONS START ===\n"
)


def _run(tmp_path: Path, body: list[str]) -> dict:
    path = tmp_path / "step.log"
    path.write_text(
        entete_step_log("\n".join(body) + "\n" + _END + "\n", **_COMMON),
        encoding="utf-8",
    )
    return an.parse_step_log(str(path))


def _run_two_episodes(tmp_path: Path, ep1_body: list[str], ep2_body: list[str]) -> dict:
    """Log avec deux épisodes complets (tour 1 chacun) pour tester l'isolation inter-épisodes."""
    content = (
        "=== STEP-BY-STEP ACTION LOG ===\n"
        "================================================================================\n\n"
        "[10:00:00] === EPISODE 1 START ===\n"
        + _EPISODE_HEADER
        + "\n".join(ep1_body) + "\n"
        + _END + "\n"
        + "[10:00:01] === EPISODE 2 START ===\n"
        + _EPISODE_HEADER
        + "\n".join(ep2_body) + "\n"
        + "[12:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, "
        "Total=0, Duration=1.000s\n"
    )
    path = tmp_path / "step.log"
    path.write_text(content, encoding="utf-8")
    return an.parse_step_log(str(path))


def _shot(turn: int, player: int, uid: str, scol: int, srow: int) -> str:
    """Ligne SHOT minimale — pas de weapon pour rester hors du bloc weapon_match."""
    return (
        f"[12:00:0{turn}] E1 T{turn} P{player} SHOOT : "
        f"Unit {uid}({scol},{srow}) SHOT Unit 101(5,30) Dmg:0HP [SUCCESS]"
    )


def _non_shot_shoot_action(turn: int, player: int, uid: str, scol: int, srow: int) -> str:
    """Action SHOOT-phase par uid sans SHOT (simule une capacité/wait intercalée par un autre acteur)."""
    return (
        f"[12:00:0{turn}] E1 T{turn} P{player} SHOOT : "
        f"Unit {uid}({scol},{srow}) WAITED [SUCCESS]"
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


def test_action_non_tir_intercalee_ne_produit_pas_de_faux_positif(tmp_path: Path) -> None:
    """VERROU : une action SHOOT-phase non-SHOT d'une autre unité ne rompt pas la salve de A.

    Avant le fix, shoot_last_activator était mis à jour pour TOUTE action (_dmg_actor_match),
    y compris les capacités/wait d'une unité tierce. La continuation de la salve de Unit 1
    après le WAIT de Unit 2 était alors comptée à tort comme une seconde activation.
    """
    stats = _run(tmp_path, [
        _shot(1, 1, "1", 5, 5),              # activation Unit 1 — shoot_last_activator = "1"
        _non_shot_shoot_action(1, 1, "2", 5, 10),  # WAIT de Unit 2 : pas un SHOT, ne doit pas flipper shoot_last_activator
        _shot(1, 1, "1", 5, 5),              # continuation de la salve de Unit 1 — pas un doublon
    ])
    assert stats["double_activation_by_phase"]["SHOOT"] == 0, stats["double_activation_by_phase"]


def test_shoot_last_activator_non_fuite_entre_episodes(tmp_path: Path) -> None:
    """VERROU : shoot_last_activator est réinitialisé à chaque début d'épisode.

    Sans le fix, last_turn n'était pas remis à 0 dans handle_episode_start. Si l'épisode N
    finissait au tour 1, last_turn = 1 ; l'épisode N+1 commençait aussi au tour 1 → le bloc
    turn-change (turn != last_turn) ne se déclenchait pas → shoot_last_activator de l'épisode N
    contaminait l'épisode N+1. La première activation de Unit 1 en épisode 2 n'était pas
    enregistrée dans phase_activation_seen, faisant manquer sa double activation réelle.
    """
    # Épisode 1 : Unit 1 tire en dernier → shoot_last_activator = "1" à la fin de l'épisode.
    ep1 = [
        _shot(1, 1, "2", 5, 10),  # Unit 2 tire d'abord
        _shot(1, 1, "1", 5, 5),   # Unit 1 tire en dernier — shoot_last_activator = "1"
    ]
    # Épisode 2, tour 1 : Unit 1 → Unit 2 → Unit 1 à nouveau (vraie double activation).
    ep2 = [
        _shot(1, 1, "1", 5, 5),   # activation Unit 1
        _shot(1, 1, "2", 5, 10),  # activation Unit 2
        _shot(1, 1, "1", 5, 5),   # double activation de Unit 1 — DOIT être détectée
    ]
    stats = _run_two_episodes(tmp_path, ep1, ep2)
    # Seul l'épisode 2 contient une double activation.
    assert stats["double_activation_by_phase"]["SHOOT"] == 1, stats["double_activation_by_phase"]
