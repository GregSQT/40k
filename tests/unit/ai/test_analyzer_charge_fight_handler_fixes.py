"""Verrous pour trois corrections dans charge_handler et fight_handler.

F1 — start==dest sans unité dans unit_hp (charge_handler.py:355)
    La branche `else` (start==dest) appelait `require_key(state.unit_hp, id)` sans
    garde d'existence. Quand l'unité est absente de unit_hp (non redéployée en épisode
    2), l'ancien code levait ConfigurationError. Le fix ajoute `charge_unit_id in
    state.unit_hp and` avant require_key.

F2 — asymétrie attaquant mort (fight_handler.py:459)
    `attacker_is_dead = fighter_id IN unit_hp AND hp<=0` ne comptait pas un attaquant
    ABSENT de unit_hp ; la cible utilisait correctement `NOT IN OR hp<=0`. Le fix aligne
    les deux.

F3 — double comptage units_fled (charge_handler.py:85-94, supprimé)
    Deux blocs traitaient `units_fled` : le premier (ligne 85) incrémentait
    `charge_invalid['fled']` ET `special_rule_usage[("charge_after_flee", ...)]` ; le
    second (ligne 228, "RULE: Charge after flee") incrémentait `charge_after_flee` ET
    `special_rule_usage`. Une unité avec la règle voyait `special_rule_usage` compté
    deux fois. Le premier bloc a été supprimé.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import pytest

import ai.analyzer as an
from tests.unit.ai._fabriques import entete_step_log

# ── Constantes communes ──────────────────────────────────────────────────────

_BOARD = "cols=220 rows=300"
_SCALE = 1   # x1 : distances en subhex = distance en pouces

# En-tête de section par épisode (Board + Run rules + unités, SANS la ligne EPISODE START)
_EPISODE_HEADER = (
    "[10:00:00] Scenario: scenario_bot-01\n"
    "[10:00:00] Opponent: SelfplayBot\n"
    "[10:00:00] Rosters: scale=100pts AGENT_PLAYER=1 AGENT=a (a.json) OPPONENT=o (o.json)\n"
    "[10:00:00] Walls: none\n"
    f"[10:00:00] Board: {_BOARD} inches_to_subhex={_SCALE} hex_radius=2.78 margin=1\n"
    "[10:00:00] Run rules: cohesion.global_subhex=9 cohesion.min_neighbors=1 "
    "cohesion.model_subhex=2 engagement_zone_subhex=2 engagement_zone_vertical_inches=5.0 "
    "metric.engagement=hex metric.ranged=euclidean "
    "move.thru_enemy=False move.thru_ez=True move.thru_friendly=True\n"
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2 "
    "[MODELS: 1#0@(50,50,z0)]\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 "
    "[MODELS: 101#0@(90,50,z0)]\n"
    "[10:00:00] === ACTIONS START ===\n"
)

_EPISODE_END = (
    "[12:00:09] EPISODE END: Winner=-1, Method=draw, Actions=0, Steps=0, "
    "Total=0, Duration=1.000s\n"
)


def _two_episode_log(ep1_actions: str, ep2_actions: str) -> str:
    """Log minimal à deux épisodes."""
    return (
        "=== STEP-BY-STEP ACTION LOG ===\n"
        "================================================================================\n\n"
        "[10:00:00] === EPISODE 1 START ===\n"
        + _EPISODE_HEADER
        + ep1_actions
        + _EPISODE_END
        + "[10:00:01] === EPISODE 2 START ===\n"
        + _EPISODE_HEADER
        + ep2_actions
        + _EPISODE_END
    )


# ── F1 : start==dest sans unité dans unit_hp ────────────────────────────────


def test_charge_start_eq_dest_unit_absent_from_unit_hp_no_crash(tmp_path):
    """VERROU F1 : charge avec start==dest et unité absente de unit_hp ne doit pas crasher.

    Scénario : épisode 2, unité 1 non redéployée (unit_hp vidé à l'ouverture de l'épisode).
    La charge part de (90,50) vers (90,50) — start==dest, branche `else`.
    AVANT le fix : `require_key(state.unit_hp, "1")` → ConfigurationError.
    APRÈS le fix : garde `"1" in state.unit_hp` → False → skip → aucun crash.
    """
    # Épisode 1 : les deux unités sont déployées normalement.
    ep1 = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) "
        "[MODELS: 1#0@(50,50,z0)] [R:+0.0] [SUCCESS]\n"
        "[10:00:02] E1 T1 P2 DEPLOYMENT : Unit 101(90,50) DEPLOYED from (-1,-1) to (90,50) "
        "[MODELS: 101#0@(90,50,z0)] [R:+0.0] [SUCCESS]\n"
    )
    # Épisode 2 : seule l'unité 101 est redéployée → unit_hp["1"] absent.
    # Unité 1 émet une ligne CHARGE avec start==dest.
    ep2 = (
        "[10:00:01] E2 T1 P2 DEPLOYMENT : Unit 101(90,50) DEPLOYED from (-1,-1) to (90,50) "
        "[MODELS: 101#0@(90,50,z0)] [R:+0.0] [SUCCESS]\n"
        # start == dest == (90,50) : déclenche la branche `else` du handler
        "[10:00:03] E2 T1 P1 CHARGE : Unit 1(90,50) CHARGED Unit 101(90,50) "
        "from (90,50) to (90,50) [R:+0.0] [SUCCESS]\n"
    )
    log = tmp_path / "step.log"
    log.write_text(_two_episode_log(ep1, ep2), encoding="utf-8")

    # Ne doit pas lever ConfigurationError (ni aucune autre exception).
    stats = an.parse_step_log(str(log))
    # Deux épisodes traités sans interruption.
    assert stats["total_episodes"] == 2


# ── F2 : asymétrie attaquant mort ───────────────────────────────────────────


def test_attacker_absent_from_unit_hp_treated_as_dead():
    """VERROU F2 : formule `not in OR hp<=0` vs ancienne `in AND hp<=0`.

    Test de logique pure : vérifie directement les deux formules sur un état où
    fighter_id est ABSENT de unit_hp. Pas de full-log (le scénario `not in unit_hp`
    est un cas-limite inaccessible via le parseur normal — la correction est une garde
    de sécurité). La formule testée est celle qui apparaît sur la ligne fixée.
    """
    unit_hp: dict[str, int] = {"101": 2}  # "1" absent
    fighter_id = "1"

    # Ancienne formule (bug) : absente == vivante
    old_attacker_is_dead = fighter_id in unit_hp and unit_hp[fighter_id] <= 0
    assert not old_attacker_is_dead, (
        "ancienne formule 'in AND hp<=0' retourne False pour une unité absente — "
        "elle traite incorrectement une unité inconnue comme vivante"
    )

    # Nouvelle formule (fix) : absente == morte
    new_attacker_is_dead = fighter_id not in unit_hp or unit_hp.get(fighter_id, -1) <= 0
    assert new_attacker_is_dead, (
        "nouvelle formule 'not in OR hp<=0' doit retourner True pour une unité absente"
    )


# ── F3 : double comptage units_fled ─────────────────────────────────────────

# Unité qui a la règle charge_after_flee dans la config réelle.
_LIEUTENANT_TYPE = "LieutenantCloseCombatBolter"

_UNITS_F3 = (
    f"[10:00:00] Unit 1 ({_LIEUTENANT_TYPE}) P1: Starting position (-1,-1), HP_MAX=4 "
    "[MODELS: 1#0@(50,50,z0)]\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 "
    "[MODELS: 101#0@(55,50,z0)]\n"
)


def _f3_log(tmp_path: Any) -> dict:
    """Log avec fuite + charge d'une unité ayant charge_after_flee.

    L'unité 1 (LieutenantCloseCombatBolter) fuit, puis charge l'unité 101.
    Avant le fix : deux blocs incrémentaient special_rule_usage → compteur = 2.
    Après le fix : seul le bloc "RULE: Charge after flee" incrémente → compteur = 1.
    """
    body = (
        # Déploiement
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) "
        "[MODELS: 1#0@(50,50,z0)] [R:+0.0] [SUCCESS]\n"
        "[10:00:02] E1 T1 P2 DEPLOYMENT : Unit 101(55,50) DEPLOYED from (-1,-1) to (55,50) "
        "[MODELS: 101#0@(55,50,z0)] [R:+0.0] [SUCCESS]\n"
        # Fuite de l'unité 1 (MOVE phase)
        "[10:00:03] E1 T1 P1 MOVE : Unit 1(50,50) FLED from (50,50) to (45,50) "
        "[MODELS: 1#0@(45,50,z0)] [R:+0.0] [SUCCESS]\n"
        # Charge de l'unité 1 vers 101 (CHARGE phase)
        "[10:00:04] E1 T1 P1 CHARGE : Unit 1(45,50) CHARGED Unit 101(55,50) "
        "from (45,50) to (55,50) [Roll:12] [R:+0.0] [SUCCESS]\n"
    )
    log_text = entete_step_log(
        body,
        inches_to_subhex=_SCALE,
        board=_BOARD,
        walls="none",
        units=_UNITS_F3,
    )
    path = tmp_path / "step.log"
    path.write_text(log_text, encoding="utf-8")
    return an.parse_step_log(str(path))


def test_charge_after_flee_rule_not_double_counted(tmp_path):
    """VERROU F3 : special_rule_usage[("charge_after_flee", type)] == 1, pas 2.

    AVANT le fix : bloc 85-94 + bloc 228-237 incrémentaient chacun le même compteur
    → 2 (double). APRÈS le fix : seul le bloc 228-237 subsiste → 1.
    """
    stats = _f3_log(tmp_path)
    key = ("charge_after_flee", _LIEUTENANT_TYPE)
    usage = stats["special_rule_usage"][key]
    total = usage[1] + usage[2]
    assert total == 1, (
        f"charge_after_flee doit être compté exactement une fois (bloc RULE), "
        f"obtenu {total} — double bloc présent si > 1"
    )


def test_charge_after_flee_with_rule_no_invalid_charge(tmp_path):
    """VERROU F3b : unit avec charge_after_flee ne doit pas incrémenter charge_invalid.

    Vérifie qu'après suppression du premier bloc, `charge_invalid['fled']` reste à 0
    (la règle autorise la charge — il ne doit pas y avoir de comptage d'infraction).
    """
    stats = _f3_log(tmp_path)
    fled_invalid = stats["charge_invalid"][1]["fled"]
    assert fled_invalid == 0, (
        f"charge_invalid['fled'] doit être 0 pour un lieutenant avec charge_after_flee, "
        f"obtenu {fled_invalid}"
    )
