"""09.03 / 09.06 : advance déclaré + engagement au commit → re-downgrade fall_back.

Cas : l'unité A déclare Advance (roll stocké dans ``advance_rolls`` / ``units_advanced``),
puis un mouvement réactif adverse la met dans l'Engagement Range avant le commit.
``movement_commit_move_plan_handler`` réévalue l'engagement à la ligne 4557 et choisit
``fall_back`` — jamais ``advance`` — parce que 09.03 interdit d'avancer depuis l'ER.

Vérifications :
  - ``result["action"] == "flee"`` (libellé renvoyé par ``finalize_flee_marking``)
  - ``units_fled`` contient l'unité
  - ``action_logs`` porte ``action_name="FLED"`` et ``was_flee=True``
"""
from __future__ import annotations

from typing import Any, Dict, List

from engine.phase_handlers.movement_handlers import movement_commit_move_plan_handler
from engine.phase_handlers.shared_utils import build_units_cache
from tests._state_invariants import turn_state_invariants, unit_invariants
from tests.unit.engine._config_helpers import build_game_rules, build_move_rules


def _unit(uid: str, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        **unit_invariants(),
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": 1,
        "HP_MAX": 1,
        "VALUE": 50,
        "OC": 1,
        "T": 4,
        "ARMOR_SAVE": 3,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
        "models": [{"col": col, "row": row, "level": 0, "VALUE": 50}],
    }


def _make_gs(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        **turn_state_invariants(),
        "config": {
            "game_rules": build_game_rules(),
            "move": build_move_rules(),
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 60,
        "board_rows": 60,
        "current_player": 1,
        "phase": "move",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "enemy_adjacent_hexes_player_1": set(),
        "enemy_adjacent_hexes_player_2": set(),
        "inches_to_subhex": 1,
        "current_turn": 1,
    }
    build_units_cache(gs)
    return gs


def test_advance_downgrade_to_fall_back_when_engaged_at_commit():
    """VERROU : advance roll présent + engagement au commit → move_type fall_back.

    Simule un mouvement réactif ennemi survenu APRÈS la déclaration d'Advance :
    l'ennemi (P2) est positionné adjacent à l'unité (P1) avant le commit, et
    ``was_engaged`` vaut True. La branche ligne 4557 choisit alors ``fall_back``
    malgré ``_adv_roll is not None`` (invariant 09.03).
    """
    # P1 en (10,10), P2 adjacent en (10,11) — dans l'EZ (EZ≥1 subhex à x1).
    units = [
        _unit("1", 1, 10, 10),
        _unit("2", 2, 10, 11),
    ]
    gs = _make_gs(units)

    # Injection : l'unité 1 a déclaré Advance (roll = 3) avant que l'ennemi ne réagisse.
    gs["units_advanced"].add("1")
    gs["advance_rolls"]["1"] = 3

    # Plan : déplacement vers (5, 10) — hors EZ ennemie, dans le budget advance (9 subhex).
    plan = [["1#0", 5, 10, 0]]

    ok, result = movement_commit_move_plan_handler(gs, "1", {"plan": plan})

    assert ok is True, f"handler échoué : {result}"

    # L'avance est invalidée au commit → le libellé doit être "flee" (fall_back), pas "move".
    assert result["action"] == "flee", (
        f"attendu 'flee' (fall_back), obtenu {result['action']!r} — "
        "le re-downgrade advance→fall_back (ligne 4557) n'est pas actif"
    )

    # L'unité est marquée comme ayant fui.
    assert "1" in gs["units_fled"], (
        "units_fled ne contient pas l'unité 1 après le fall_back"
    )

    # L'action_log confirme FLED, pas ADVANCED.
    move_log = next(
        (e for e in gs["action_logs"] if e.get("unitId") == "1" and e.get("type") == "move"),
        None,
    )
    assert move_log is not None, "aucun action_log type='move' pour l'unité 1"
    assert move_log["action_name"] == "FLED", (
        f"action_log : attendu 'FLED', obtenu {move_log['action_name']!r}"
    )
    assert move_log["was_flee"] is True, "was_flee doit être True pour un fall_back"
