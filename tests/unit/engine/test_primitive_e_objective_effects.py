"""Primitive E — `secure_objective_on_control` et `oc_bonus` (chantier 06, passe 5).

Deux capacités couvertes :
- `secure_objective_on_control` : en fin de phase de commandement, un objectif contrôlé par une
  unité avec cette règle est sécurisé (`secured_objectives`) — l'adversaire doit avoir STRICTEMENT
  plus d'OC pour le reprendre, même si le `control_method` global est « default ».
- `oc_bonus` : ajoute +N à l'OC de chaque figurine de l'unité pour le contrôle d'objectif.

Plan rouge → vert sur les invariants moteurs.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.game_state import (
    GameStateManager,
    apply_secure_objective_on_control,
    objective_control_contributions,
    unit_effective_oc,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

ZONE_HEX = (5, 5)
LOIN_HEX = (20, 20)
OBJ_ID = 1


def _unit(
    uid: str,
    player: int,
    col: int,
    row: int,
    oc: int = 2,
    unit_rules: List[Dict[str, Any]] | None = None,
    battle_shocked: bool = False,
) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "OC": oc,
        "battle_shocked": battle_shocked,
        "UNIT_RULES": unit_rules or [],
    }


def _model(uid: str, col: int, row: int) -> Dict[str, Any]:
    return {"col": col, "row": row, "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1}


def _state(
    units: List[Dict[str, Any]],
    *,
    current_player: int = 1,
    objective_col: int = ZONE_HEX[0],
    objective_row: int = ZONE_HEX[1],
    objective_controllers: Dict[str, Any] | None = None,
    secured_objectives: Dict[str, Any] | None = None,
    control_method: str = "default",
) -> Dict[str, Any]:
    """État minimal pour les tests Primitive E."""
    objectives = [{"id": OBJ_ID, "hexes": [[objective_col, objective_row]]}]
    primary_objective = {
        "id": "po",
        "scoring": {"start_turn": 2, "max_points_per_turn": 5, "rules": []},
        "timing": {"default_phase": "command", "round5_second_player_phase": "fight"},
        "control": {
            "method": "oc_sum_greater",
            "control_method": control_method,
            "tie_behavior": "no_control",
        },
        "objective_hexes": [[objective_col, objective_row]],
    }
    units_cache = {}
    models_cache = {}
    squad_models = {}
    for u in units:
        uid = str(u["id"])
        col = u.get("col", LOIN_HEX[0])
        row = u.get("row", LOIN_HEX[1])
        units_cache[uid] = {"player": u["player"], "col": col, "row": row, "orientation": 0}
        mid = f"{uid}#0"
        squad_models[uid] = [mid]
        models_cache[mid] = _model(uid, col, row)
    gs: Dict[str, Any] = {
        "units": units,
        "units_cache": units_cache,
        "models_cache": models_cache,
        "squad_models": squad_models,
        "objectives": objectives,
        "primary_objective": primary_objective,
        "objective_controllers": dict(objective_controllers or {}),
        "current_player": current_player,
        "turn": 2,
        "phase": "command",
        "victory_points": {1: 0, 2: 0},
        "command_points": {1: 0, 2: 0},
        "action_logs": [],
        "action_log_seq": 0,
        "config": {
            "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
            "controlled_player": 1,
        },
    }
    if secured_objectives is not None:
        gs["secured_objectives"] = dict(secured_objectives)
    return gs


def _manager(gs: Dict[str, Any]) -> GameStateManager:
    return GameStateManager(gs["config"])


# ─────────────────────────────────────────────────────────────────────────────
# oc_bonus — unit_effective_oc
# ─────────────────────────────────────────────────────────────────────────────

def test_oc_effectif_sans_bonus_renvoie_oc_base() -> None:
    u = _unit("1", 1, 5, 5, oc=2)
    assert unit_effective_oc(u) == 2


def test_oc_effectif_avec_oc_bonus_ajoute_le_bonus() -> None:
    u = _unit("1", 1, 5, 5, oc=2, unit_rules=[
        {"ruleId": "oc_bonus", "displayName": "Relic Banner", "rule_args": {"oc_bonus": 1}},
    ])
    assert unit_effective_oc(u) == 3


def test_oc_bonus_absent_de_rule_args_leve() -> None:
    u = _unit("1", 1, 5, 5, oc=2, unit_rules=[
        {"ruleId": "oc_bonus", "displayName": "Relic Banner", "rule_args": {}},
    ])
    with pytest.raises(ValueError, match="oc_bonus"):
        unit_effective_oc(u)


def test_oc_bonus_dans_objective_control_contributions() -> None:
    """Verrou principal oc_bonus : la contribution réelle au contrôle d'objectif augmente."""
    u_sans = _unit("1", 1, *ZONE_HEX, oc=2)
    u_avec = _unit("2", 1, *ZONE_HEX, oc=2, unit_rules=[
        {"ruleId": "oc_bonus", "displayName": "Relic Banner", "rule_args": {"oc_bonus": 1}},
    ])
    # Ajouter la position à l'unité pour le helper _state
    u_sans["col"], u_sans["row"] = ZONE_HEX
    u_avec["col"], u_avec["row"] = ZONE_HEX

    gs_sans = _state([u_sans])
    gs_avec = _state([u_avec])

    zone = {(ZONE_HEX[0], ZONE_HEX[1])}
    contrib_sans = objective_control_contributions(gs_sans, [zone])
    contrib_avec = objective_control_contributions(gs_avec, [zone])

    # OC 2 sans bonus → contribution 2
    assert contrib_sans["1"][1] == [2]
    # OC 2 + 1 bonus → contribution 3
    assert contrib_avec["2"][1] == [3]


# ─────────────────────────────────────────────────────────────────────────────
# secure_objective_on_control — apply_secure_objective_on_control
# ─────────────────────────────────────────────────────────────────────────────

def test_apply_secure_sans_porteur_renvoie_vide() -> None:
    u = _unit("1", 1, *ZONE_HEX, oc=2)
    u["col"], u["row"] = ZONE_HEX
    gs = _state([u], objective_controllers={str(OBJ_ID): 1})
    assert apply_secure_objective_on_control(gs) == []
    assert "secured_objectives" not in gs


def test_apply_secure_porteur_hors_zone_ne_secure_pas() -> None:
    u = _unit("1", 1, *LOIN_HEX, oc=2, unit_rules=[
        {"ruleId": "secure_objective_on_control", "displayName": "Get da Good Bitz"},
    ])
    u["col"], u["row"] = LOIN_HEX
    gs = _state([u], objective_controllers={str(OBJ_ID): 1})
    result = apply_secure_objective_on_control(gs)
    assert result == []
    assert gs.get("secured_objectives", {}) == {}


def test_apply_secure_porteur_dans_zone_secure_objectif() -> None:
    u = _unit("1", 1, *ZONE_HEX, oc=2, unit_rules=[
        {"ruleId": "secure_objective_on_control", "displayName": "Get da Good Bitz"},
    ])
    u["col"], u["row"] = ZONE_HEX
    gs = _state([u], objective_controllers={str(OBJ_ID): 1})
    result = apply_secure_objective_on_control(gs)
    assert OBJ_ID in result
    assert gs["secured_objectives"][str(OBJ_ID)] == 1


def test_apply_secure_objectif_non_controle_ne_secure_pas() -> None:
    """L'objectif doit être contrôlé par le joueur actif pour être sécurisé."""
    u1 = _unit("1", 1, *ZONE_HEX, oc=2, unit_rules=[
        {"ruleId": "secure_objective_on_control", "displayName": "Get da Good Bitz"},
    ])
    u1["col"], u1["row"] = ZONE_HEX
    # Adversaire avec OC strictement supérieur → il contrôle l'objectif après calculate
    u2 = _unit("2", 2, *ZONE_HEX, oc=4)
    u2["col"], u2["row"] = ZONE_HEX
    gs = _state([u1, u2], current_player=1)
    result = apply_secure_objective_on_control(gs)
    assert result == []
    assert gs.get("secured_objectives", {}) == {}


def test_apply_secure_battle_shocked_ne_securise_pas() -> None:
    u = _unit("1", 1, *ZONE_HEX, oc=2, unit_rules=[
        {"ruleId": "secure_objective_on_control", "displayName": "Get da Good Bitz"},
    ], battle_shocked=True)
    u["col"], u["row"] = ZONE_HEX
    gs = _state([u], objective_controllers={str(OBJ_ID): 1})
    result = apply_secure_objective_on_control(gs)
    assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# secure_objective_on_control — calculate_objective_control avec secured_objectives
# ─────────────────────────────────────────────────────────────────────────────

def test_secured_objective_garde_controle_avec_oc_egal() -> None:
    """Invariant principal : objectif sécurisé reste contrôlé même à OC égaux (control_method=default).

    Rouge → vert : sans la logique secured_objectives dans calculate_objective_control,
    un objectif en mode 'default' passerait à None (contesté) à OC égaux.
    """
    # Joueur 1 et 2 ont tous les deux 2 OC sur l'objectif → égalité
    u1 = _unit("1", 1, *ZONE_HEX, oc=2)
    u1["col"], u1["row"] = ZONE_HEX
    u2 = _unit("2", 2, *ZONE_HEX, oc=2)
    u2["col"], u2["row"] = ZONE_HEX

    gs = _state(
        [u1, u2],
        current_player=1,
        control_method="default",
        objective_controllers={str(OBJ_ID): 1},
        secured_objectives={str(OBJ_ID): 1},
    )
    _manager(gs).calculate_objective_control(gs)
    # Objectif sécurisé par P1 → P1 garde malgré l'égalité
    assert gs["objective_controllers"][str(OBJ_ID)] == 1


def test_secured_objective_perdu_si_adversaire_plus_grand_oc() -> None:
    """Un objectif sécurisé est perdu si l'adversaire a STRICTEMENT plus d'OC."""
    u1 = _unit("1", 1, *ZONE_HEX, oc=2)
    u1["col"], u1["row"] = ZONE_HEX
    u2 = _unit("2", 2, *ZONE_HEX, oc=4)
    u2["col"], u2["row"] = ZONE_HEX

    gs = _state(
        [u1, u2],
        control_method="default",
        objective_controllers={str(OBJ_ID): 1},
        secured_objectives={str(OBJ_ID): 1},
    )
    _manager(gs).calculate_objective_control(gs)
    # P2 a plus d'OC → P2 capture l'objectif
    assert gs["objective_controllers"][str(OBJ_ID)] == 2
    # Le statut secured est effacé
    assert gs["secured_objectives"].get(str(OBJ_ID)) is None


def test_secured_objectives_vide_default_mode_passe_a_none() -> None:
    """Contrepartie rouge : sans secured_objectives, égalité OC = pas de contrôle (mode default).

    Ce test verrouille que la logique par défaut reste intacte.
    """
    u1 = _unit("1", 1, *ZONE_HEX, oc=2)
    u1["col"], u1["row"] = ZONE_HEX
    u2 = _unit("2", 2, *ZONE_HEX, oc=2)
    u2["col"], u2["row"] = ZONE_HEX

    gs = _state(
        [u1, u2],
        control_method="default",
        objective_controllers={str(OBJ_ID): 1},
        # Pas de secured_objectives
    )
    _manager(gs).calculate_objective_control(gs)
    # Égalité sans secured → contesté (None)
    assert gs["objective_controllers"][str(OBJ_ID)] is None
