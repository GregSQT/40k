"""Verrou §11.04 : budget de charge par-figurine dans le chemin gym (translation rigide).

Scénario : escouade à (25, 30), jet de charge = 7 (budget = 7 hexes à x1).
La destination (17, 32) est à 8 hexes de l'ancre (hex_distance = max(8,2,6) = 8).
Le pool peut contenir (17,32) si extra >= 1 (décalage empreinte compensant la cible).
Sans le verrou : _attempt_charge_to_destination acceptait la destination — chaque figurine
co-localisée avec l'ancre se déplace de 8 hexes pour un jet de 7 (violation §11.04).
Avec le verrou : rejet immédiat dès que anchor_distance > roll_subhex.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.phase_handlers.charge_handlers import _attempt_charge_to_destination
from tests._state_invariants import turn_state_invariants, unit_invariants

# Ancre du chargeur et destination sur-budget (hex_distance = 8 > roll = 7).
START_COL, START_ROW = 25, 30
DEST_COL, DEST_ROW = 17, 32
CHARGE_ROLL = 7  # 2D6 en inches ; à x1 sub-hex = hex step


def _unit() -> Dict[str, Any]:
    return {
        **unit_invariants(),
        "id": "1",
        "player": 1,
        "col": START_COL,
        "row": START_ROW,
        "HP_CUR": 2,
        "HP_MAX": 2,
        "BASE_SIZE": 1,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
        "UNIT_KEYWORDS": [],
    }


def _make_gs(unit: Dict[str, Any]) -> Dict[str, Any]:
    """État minimal pour atteindre le contrôle §11.04 dans _attempt_charge_to_destination."""
    gs: Dict[str, Any] = {
        **turn_state_invariants(),
        "board_cols": 30,
        "board_rows": 35,
        "current_player": 1,
        "phase": "charge",
        "wall_hexes": set(),
        "inches_to_subhex": 1,
        "units": [unit],
        "unit_by_id": {str(unit["id"]): unit},
        # Pool : contient manuellement la destination sur-budget, simulant le bug où
        # _charge_bfs_max_distance retourne roll+extra et y inscrit (17,32).
        "valid_charge_destinations_pool": {(DEST_COL, DEST_ROW)},
        "charge_roll_values": {str(unit["id"]): CHARGE_ROLL},
        "charge_activation_pool": [],
        "_charge_initial_rolls": {},
    }
    # Cache minimal : col/row lus par require_unit_position.
    gs["units_cache"] = {
        "1": {
            "col": START_COL,
            "row": START_ROW,
            "level": 0,
            "player": 1,
            "on_battlefield": True,
            "HP_CUR": 2,
            "BASE_SIZE": 1,
            "BASE_SHAPE": "round",
            "occupied_hexes": {(START_COL, START_ROW)},
        }
    }
    return gs


class TestChargePerModelBudget:
    """§11.04 : le delta d'ancre ne peut pas dépasser le jet de charge par-figurine."""

    def test_overbudget_destination_is_rejected(self) -> None:
        """(17,32) à 8 hexes de (25,30) doit être refusé pour un jet de 7."""
        unit = _unit()
        gs = _make_gs(unit)

        ok, result = _attempt_charge_to_destination(gs, unit, DEST_COL, DEST_ROW, ["2"], {})

        assert not ok, (
            f"_attempt_charge_to_destination a accepté une destination à 8 hexes pour un jet de "
            f"{CHARGE_ROLL} : violation §11.04. result={result}"
        )
        assert result.get("error") == "charge_exceeds_roll_per_model", result

    def test_onbudget_destination_passes_budget_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """(18,32) à 7 hexes de (25,30) ne doit PAS être rejeté par le contrôle §11.04.

        On neutralise les étapes aval (_is_valid_charge_destination, translate_squad) pour
        isoler uniquement le contrôle budget : le test ne doit pas lever
        charge_exceeds_roll_per_model.
        """
        import engine.phase_handlers.charge_handlers as ch

        monkeypatch.setattr(ch, "_is_valid_charge_destination", lambda *_a, **_kw: True)
        monkeypatch.setattr(
            "engine.phase_handlers.shared_utils.translate_squad_to_destination",
            lambda *_a, **_kw: None,
        )

        unit = _unit()
        gs = _make_gs(unit)
        # (18,32) : hex_distance = max(7,2,5) = 7 == CHARGE_ROLL → dans le budget.
        gs["valid_charge_destinations_pool"] = {(18, 32)}
        gs["charge_roll_values"] = {"1": CHARGE_ROLL}

        # On tolère une erreur aval (state incomplet) mais PAS charge_exceeds_roll_per_model.
        try:
            ok, result = _attempt_charge_to_destination(gs, unit, 18, 32, ["2"], {})
            assert result.get("error") != "charge_exceeds_roll_per_model", (
                f"Destination dans le budget (7 hexes = jet de 7) rejetée à tort : {result}"
            )
        except Exception as exc:
            # Crash aval acceptable tant que ce n'est pas le verrou budget.
            assert "charge_exceeds_roll_per_model" not in str(exc), (
                f"Verrou budget déclenché à tort pour une distance dans le budget : {exc}"
            )
