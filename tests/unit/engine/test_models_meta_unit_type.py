"""``models_meta_by_model`` expose le type PAR FIGURINE.

Le frontend en tire l'initiale affichée quand l'illustration d'une figurine est absente ou
introuvable (UnitRenderer.drawUnitInitial). Sans ``unit_type`` par figurine, un personnage
attaché hérite de l'initiale de son escouade d'accueil (chaplain dans des vanguard veterans
→ « V » au lieu de « C »).
"""

from __future__ import annotations

from typing import Any, Dict, List

from engine.phase_handlers.shared_utils import build_units_cache
from tests._state_invariants import turn_state_invariants, unit_invariants


def _model(col: int, row: int, **overrides: Any) -> Dict[str, Any]:
    # VALUE par figurine : exigé par _build_models_for_unit (jamais la valeur d'escouade).
    return {"col": col, "row": row, "VALUE": 20, "HP_MAX": 2, "HP_CUR": 2, **overrides}


def _squad(uid: str, models: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {**unit_invariants(),
        "id": uid,
        "player": 1,
        "col": models[0]["col"],
        "row": models[0]["row"],
        "unitType": "VanguardVeteran",
        "DISPLAY_NAME": "Vanguard Veterans",
        "ICON": "/icons/VanguardVeteran.webp",
        "ICON_SCALE": 1.0,
        "HP_CUR": len(models) * 2,
        "HP_MAX": len(models) * 2,
        "VALUE": 100,
        "OC": 1,
        "T": 4,
        "ARMOR_SAVE": 3,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "BASE_SIZE": 1,
        "BASE_SHAPE": "round",
        "MODEL_HEIGHT": 2.5,
        "MOVE": 6,
        "UNIT_RULES": [],
        "models": models,
    }


def _game_state(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {**turn_state_invariants(),
        "config": {
            "game_rules": {
                "engagement_zone": 1,
                "engagement_zone_vertical": 5,
                "max_base_size_hex": 35,
                "unit_model_cohesion_range": 2,
                "unit_global_cohesion_range": 9,
                "squad_min_neighbors": 1,
                "cohesion_distance_mode": "euclidean",
            },
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 40,
        "board_rows": 30,
        "current_player": 1,
        "phase": "move",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "console_logs": [],
        "_unit_move_version": 0,
    }
    build_units_cache(gs)
    return gs


def test_personnage_attache_expose_son_propre_unit_type():
    """Escouade hétérogène : la figurine attachée porte SON type, pas celui de l'escouade."""
    squad = _squad(
        "1",
        [
            _model(5, 10),
            _model(6, 10),
            _model(
                7,
                10,
                unit_type="ChaplainPowerWeapon",
                DISPLAY_NAME="Chaplain",
                ICON="/icons/ChaplainPowerWeapon.webp",
                ICON_SCALE=1.0,
            ),
        ],
    )
    gs = _game_state([squad])

    metas = gs["units_cache"]["1"]["models_meta_by_model"]
    assert metas["1#0"]["unit_type"] == "VanguardVeteran"
    assert metas["1#1"]["unit_type"] == "VanguardVeteran"
    assert metas["1#2"]["unit_type"] == "ChaplainPowerWeapon"


def test_escouade_homogene_n_expose_pas_de_meta_par_figurine():
    """Aucune figurine ne diffère de l'escouade → payload par-figurine non émis (inchangé)."""
    squad = _squad("1", [_model(5, 10), _model(6, 10)])
    gs = _game_state([squad])

    assert "models_meta_by_model" not in gs["units_cache"]["1"]
