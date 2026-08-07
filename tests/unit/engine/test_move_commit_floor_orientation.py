"""13.06 — le commit d'un move retient l'étage validé par le preview, pivot compris.

Pourquoi ce fichier existe. Le niveau EFFECTIF d'une figurine dépend de son EMPREINTE : elle est
à l'étage seulement si son socle tient entièrement sur le plancher (``resolve_model_floor_level``).
Sur un socle non rond, l'empreinte dépend de l'ORIENTATION — un plancher étroit n'accueille le
socle que pivoté. Le preview par-figurine résout l'étage avec l'orientation VISÉE du plan (le
pivot molette, 5ᵉ élément, pas encore committé) ; le commit, lui, la lisait sur ``models_cache``,
donc l'orientation d'AVANT le pivot. Résultat : le preview validait l'étage 1, le commit
recalculait 0 — et appliquait quand même le pivot. La figurine finissait pivotée au sol, sur une
case que l'UI venait d'afficher comme légale à l'étage.

Le test CONSTRUIT le seul cas qui distingue les deux lectures : un plancher réduit à la bande de
trois hexes que le socle oval couvre à l'orientation 3, et pas à l'orientation 0.

Règles citées : Documentation/40k_rules/13 Terrain, /03 Moving.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from engine.hex_utils import compute_occupied_hexes
from engine.phase_handlers import movement_handlers as mh
from engine.phase_handlers.shared_utils import build_units_cache
from tests._state_invariants import turn_state_invariants, unit_invariants

#: Plancher de niveau 1, réduit à la bande verticale que couvre le socle oval [4, 2] pivoté à 3.
_FLOOR_HEXES = [(20, 19), (20, 20), (20, 21)]
_FLOOR_POLYGON = [[0.0, 0.0], [200.0, 0.0], [200.0, 200.0], [0.0, 200.0]]
_PIVOTED = 3
_UNPIVOTED = 0


def _unit(uid: str, player: int, models: Sequence[Tuple[int, int]]) -> Dict[str, Any]:
    col, row = models[0]
    return {**unit_invariants(),
        "id": uid, "player": player, "col": col, "row": row,
        "HP_CUR": len(models), "HP_MAX": len(models), "VALUE": 100, "OC": 1, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [], "CC_WEAPONS": [], "BASE_SIZE": [4, 2], "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "oval", "MOVE": 6, "UNIT_RULES": [],
        "models": [
            {"col": c, "row": r, "VALUE": 10, "orientation": _UNPIVOTED} for c, r in models
        ],
    }


def _make_gs(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {**turn_state_invariants(),
        "config": {
            "game_rules": {
                "engagement_zone": 1, "engagement_zone_vertical": 5,
                "max_base_size_hex": 35, "unit_model_cohesion_range": 2,
                "unit_global_cohesion_range": 9, "squad_min_neighbors": 1,
                "cohesion_distance_mode": "euclidean",
            },
            "move": {"can_move_through_enemy_engagement_zone": True,
                     "can_move_through_enemy_model": False,
                     "can_move_through_friendly_model": True},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 60, "board_rows": 60,
        "current_player": 1,
        "phase": "move",
        "wall_hexes": set(),
        "terrain_areas": [{
            "id": "ruin", "polygon_vertices": _FLOOR_POLYGON, "hexes": _FLOOR_HEXES,
            "floors": [{"level": 1, "height_inches": 3.0, "hexes": _FLOOR_HEXES,
                        "polygon_vertices": _FLOOR_POLYGON}],
        }],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_charged": set(), "units_fled": set(), "units_advanced": set(),
        "units_moved": set(),
        "_unit_move_version": 0,
        "inches_to_subhex": 1,
        "action_logs": [], "action_log_seq": 0, "current_turn": 1,
        "enemy_adjacent_hexes_player_1": set(), "enemy_adjacent_hexes_player_2": set(),
    }
    build_units_cache(gs)
    return gs


def test_the_plan_orientation_decides_the_committed_floor_level():
    """VERROU : preview et commit résolvent l'étage avec la MÊME orientation — celle du plan."""
    gs = _make_gs([_unit("1", 1, [(18, 20)])])
    floor = set(_FLOOR_HEXES)

    # Prémisses : le socle ne tient sur ce plancher QUE pivoté. Sans elles, un commit à l'étage 1
    # prouverait seulement que le plancher est large, pas que l'orientation a été lue.
    assert set(compute_occupied_hexes(20, 20, "oval", [4, 2], _PIVOTED)) <= floor
    assert not set(compute_occupied_hexes(20, 20, "oval", [4, 2], _UNPIVOTED)) <= floor
    assert gs["models_cache"]["1#0"]["orientation"] == _UNPIVOTED, (
        "prémisse : le pivot ne doit PAS encore être committé"
    )

    plan = [["1#0", 20, 20, 1, _PIVOTED]]
    preview = mh.movement_preview_move_plan(gs, "1", [tuple(plan[0])])
    assert preview["can_validate"] is True, preview

    ok, res = mh.movement_commit_move_plan_handler(gs, "1", {"plan": plan})
    assert ok is True, res

    model = gs["models_cache"]["1#0"]
    assert model["orientation"] == _PIVOTED, "le pivot du plan n'a pas été appliqué"
    assert model["level"] == 1, (
        "étage validé par le preview perdu au commit : la figurine est retombée au sol "
        "tout en gardant son pivot"
    )
