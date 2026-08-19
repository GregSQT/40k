"""Contrat des constructeurs d'unités : le champ ``battle_shocked`` est TOUJOURS posé.

Règle 01.07 : une unité battle-shocked a l'OC de toutes ses figurines modifié à '-' (02.02),
donc elle n'apporte aucun contrôle d'objectif (14.02). ``sum_objective_control_oc_multi`` lit
ce champ SANS valeur par défaut (``require_key``) : un constructeur qui l'oublie ne produit pas
un silence, il fait planter le décompte d'objectifs en production.

Ces tests verrouillent les DEUX constructeurs écrits à la main hors du moteur — ceux que rien
n'exerçait. Les constructeurs du moteur (``create_unit`` / ``_build_enhanced_unit``) sont
couverts côté moteur par ``test_command_phase.py::test_engine_units_all_carry_battle_shocked_field``.
"""

from __future__ import annotations

import copy
from typing import Any, Dict

from services.api_server import _build_units_from_army_config
from services.endless_duty_runtime import _build_unit_from_registry


_UNIT_DATA: Dict[str, Any] = {
    "DISPLAY_NAME": "Test Unit",
    "HP_MAX": 3,
    "MOVE": 6,
    "MODEL_HEIGHT": 2.5,
    "T": 4,
    "ARMOR_SAVE": 3,
    "INVUL_SAVE": 7,
    "RNG_WEAPONS": [],
    "CC_WEAPONS": [],
    "LD": 7,
    "OC": 1,
    "VALUE": 100,
    "ICON": "t",
    "ICON_SCALE": 1.0,
    "ILLUSTRATION_RATIO": 1.0,
    "UNIT_RULES": [],
    "UNIT_KEYWORDS": [],
    "BASE_SHAPE": "round",
    "BASE_SIZE": 1,
}


class _StubRegistry:
    def get_unit_data(self, unit_type: str) -> Dict[str, Any]:
        return copy.deepcopy(_UNIT_DATA)


class _StubEngine:
    def __init__(self) -> None:
        self.unit_registry = _StubRegistry()
        self.game_state = {"inches_to_subhex": 1}


def test_army_config_builder_sets_battle_shocked() -> None:
    """api_server._build_units_from_army_config : champ posé à False (roster PvP/PvE)."""
    units, _ = _build_units_from_army_config(
        {"units": [{"unit_type": "T", "count": 2}]}, player=1, next_unit_id=1,
        engine_instance=_StubEngine(),
    )

    assert len(units) == 2
    for unit in units:
        assert "battle_shocked" in unit, "change_roster produirait une unité au champ manquant"
        assert unit["battle_shocked"] is False


def test_endless_duty_builder_sets_battle_shocked() -> None:
    """endless_duty_runtime._build_unit_from_registry : champ posé à False (spawn ennemi)."""
    unit = _build_unit_from_registry(
        _StubEngine(), unit_type="T", player=2, unit_id=7, col=4, row=4
    )

    assert "battle_shocked" in unit, "le spawn endless duty produirait une unité au champ manquant"
    assert unit["battle_shocked"] is False


def test_builders_output_survives_objective_control_read() -> None:
    """Le décompte 14.02 doit accepter les unités de ces constructeurs sans lever."""
    from engine.game_state import sum_objective_control_oc
    from engine.phase_handlers.shared_utils import build_units_cache

    army_units, _ = _build_units_from_army_config(
        {"units": [{"unit_type": "T", "count": 1}]}, player=1, next_unit_id=1,
        engine_instance=_StubEngine(),
    )
    spawned = _build_unit_from_registry(
        _StubEngine(), unit_type="T", player=2, unit_id=2, col=5, row=5
    )
    for unit in army_units:
        unit["col"], unit["row"] = 5, 5
        unit["BASE_SHAPE"], unit["BASE_SIZE"] = "round", 1
    spawned["BASE_SHAPE"], spawned["BASE_SIZE"] = "round", 1
    spawned["MODEL_HEIGHT"] = 2.5

    units = [*army_units, spawned]
    gs: Dict[str, Any] = {
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "config": {
            "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
    }
    build_units_cache(gs)

    # OC 1 de chaque cote sur (5,5) : la lecture aboutit, aucun require_key ne saute.
    assert sum_objective_control_oc(gs, {(5, 5)}) == (1, 1)
