"""13.09 Hidden — le volet « ni pendant le tour précédent » sur le chemin du moteur de tir.

Règle lue (Documentation/40k_rules/13 Terrain.pdf, 13.09) :

    A model is hidden while all of the following apply to it:
     ▪ That model has the INFANTRY/BEASTS/SWARM keyword and is within a terrain area that
       contains one or more dense terrain features.
     ▪ That model's unit did not make one or more ranged attacks **during this turn or during
       the previous turn**.

Le second membre repose sur deux clés : ``units_shot`` (ce tour) et ``units_shot_previous_turn``
(tour précédent, recopié depuis ``units_shot`` par ``command_phase_start``). Les trois lectures de
``units_shot_previous_turn`` dans ``shooting_handlers`` sont des ``.get(..., set())`` : une fixture
qui omet la clé ne casse pas, elle observe simplement « personne n'a tiré au tour précédent » —
c'est-à-dire un demi-13.09, en silence. Ces tests exercent la clé NON vide sur le chemin réel
(``compute_hidden_statuses``) et sur le chemin de preview (``preview_hidden_models_from_position``),
que le drapeau d'observation ne couvre pas.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers.shared_utils import build_units_cache
from engine.phase_handlers.shooting_handlers import (
    compute_hidden_statuses,
    preview_hidden_models_from_position,
)
from tests._state_invariants import turn_state_invariants, unit_invariants

# Zone obscurante couvrant les colonnes 10..14, lignes 10..12.
_AREA_HEXES = [[c, r] for c in range(10, 15) for r in range(10, 13)]
_AREA_POLYGON = [[10, 10], [14, 10], [14, 12], [10, 12]]


def _unit(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {**unit_invariants(),
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": 3,
        "HP_MAX": 3,
        "VALUE": 100,
        "OC": 1,
        "T": 4,
        "ARMOR_SAVE": 4,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "MOVE": 6,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 2.5,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "UNIT_RULES": [],
        "UNIT_KEYWORDS": ["INFANTRY"],
        "hideable": True,
    }


def _make_gs(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        **turn_state_invariants(),
        "config": {
            "game_rules": {
                "engagement_zone": 1,
                "engagement_zone_vertical": 5,
                "max_base_size_hex": 35,
            },
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 25,
        "board_rows": 21,
        "current_player": 1,
        "phase": "shoot",
        "turn": 2,
        "wall_hexes": set(),
        "terrain_areas": [
            {
                "id": "area1",
                "obscuring": True,
                "polygon_vertices": _AREA_POLYGON,
                "hexes": _AREA_HEXES,
            }
        ],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
    }
    build_units_cache(gs)
    return gs


@pytest.fixture
def gs() -> Dict[str, Any]:
    # L'unité 1 est dans la zone obscurante, l'unité 2 (ennemie) est loin.
    return _make_gs([_unit(1, 1, 12, 11), _unit(2, 2, 22, 5)])


def test_hidden_when_no_ranged_attack_this_turn_nor_previous(gs: Dict[str, Any]) -> None:
    """hidden_1309_base : dans l'obscurant, sans tir ce tour ni au précédent → caché."""
    compute_hidden_statuses(gs)

    assert gs["unit_by_id"]["1"]["hidden"] is True


def test_shot_previous_turn_breaks_hidden(gs: Dict[str, Any]) -> None:
    """hidden_1309_prev : avoir tiré au tour PRÉCÉDENT suffit à retirer le statut caché.

    C'est le membre de règle qu'aucune fixture ne pouvait exercer : ``units_shot`` reste vide,
    seul ``units_shot_previous_turn`` porte l'information.
    """
    gs["units_shot_previous_turn"].add("1")

    compute_hidden_statuses(gs)

    assert gs["units_shot"] == set(), "le tir de CE tour ne doit pas être en cause ici"
    assert gs["unit_by_id"]["1"]["hidden"] is False
    assert gs["unit_by_id"]["1"]["hidden_models"] == []


def test_shot_previous_turn_breaks_hidden_preview(gs: Dict[str, Any]) -> None:
    """hidden_1309_prev_preview : le preview de destination applique le même membre de règle.

    Preview et drop doivent donner le même statut — sinon l'agent voit une case « cachée »
    qu'il perdra en s'y posant.
    """
    avant = preview_hidden_models_from_position(gs, "1", 12, 11)
    assert avant["hidden"] is True

    gs["units_shot_previous_turn"].add("1")

    apres = preview_hidden_models_from_position(gs, "1", 12, 11)
    assert apres["hidden"] is False
    assert apres["hidden_models"] == []
