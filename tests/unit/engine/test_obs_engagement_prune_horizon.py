"""VERROU : l'horizon de pruning de l'observation ne doit JAMAIS rétrécir.

`ObservationBuilder._engagement_relevant_entries` réduit la liste des escouades adverses avant
de mesurer la zone d'engagement. Sa docstring promet une « sur-approximation STRICTE » : tout ce
qui est éliminé doit être hors de portée d'engagement quelle que soit la forme des socles. Une
prune qui se trompe dans l'autre sens ne crashe pas — elle fait dire à l'observation « pas en
zone d'engagement » sur une paire qui l'est, et le modèle apprend sur une mesure fausse.

Elle plafonnait pourtant le socle ennemi par `min(span, max_base_size_hex)` (35), alors que
`movement_handlers._enemy_items_within_move_engagement_horizon` — son jumeau déclaré, « mêmes
helpers » — avait retiré ce même plafond en documentant précisément ce mode de panne. À x10 un
WarTrakk porte un `oval` [41, 27] : le plafond lui rend un rayon de 18 au lieu de 21, soit trois
subhex d'horizon perdus.

Le test confronte la prune au CONTRAT (`unit_entries_within_engagement_zone`) sur une paire que
le plafond éliminait, et non à un seuil écrit à la main : c'est la seule forme qui reste vraie
si les rayons changent.
"""

from typing import Any, Dict, List, Tuple

from engine.hex_utils import compute_occupied_hexes
from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.shared_utils import build_units_cache, get_engagement_zone
from engine.spatial_relations import unit_entries_within_engagement_zone
from tests._state_invariants import turn_state_invariants, unit_invariants

#: Plateau ×10 : c'est la seule résolution où un socle du dépôt dépasse `max_base_size_hex` (35).
ISH = 10
EZ_SUBHEX = 2 * ISH
#: WarTrakk (`config/armies/armageddon_orks.json`) : `oval` [41, 27] en unités datasheet, donc
#: [41, 27] à ×10 — span 41, au-delà du plafond 35.
WARTRAKK_BASE = [41, 27]


def _unit(uid: int, player: int, col: int, row: int, shape: str, size: Any) -> Dict[str, Any]:
    return {**unit_invariants(),
        "id": uid, "player": player, "col": col, "row": row,
        "HP_CUR": 4, "HP_MAX": 4, "VALUE": 100, "OC": 1, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [], "CC_WEAPONS": [],
        "BASE_SHAPE": shape, "BASE_SIZE": size, "orientation": 0,
        "MODEL_HEIGHT": 2.5, "MOVE": 6, "UNIT_RULES": [], "UNIT_KEYWORDS": [], "level": 0,
    }


def _gs(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {**turn_state_invariants(),
        "config": {
            "game_rules": {
                "engagement_zone": EZ_SUBHEX,
                "engagement_zone_vertical": 5,
                "max_base_size_hex": 35,
            },
            "charge": {"charge_max_distance": 12 * ISH},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 400, "board_rows": 300,
        "current_player": 1, "phase": "movement",
        "wall_hexes": set(), "terrain_areas": [],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "console_logs": [], "_unit_move_version": 0,
        "inches_to_subhex": ISH,
    }
    build_units_cache(gs)
    return gs


def _engaging_pair() -> Tuple[Dict[str, Any], int]:
    """Place un WarTrakk face à un socle d'infanterie, à la distance d'ancres la PLUS GRANDE où
    l'engagement tient encore. C'est là, et seulement là, que la largeur de l'horizon tranche."""
    reference_col = 100
    row = 150
    for enemy_col in range(reference_col + 90, reference_col, -1):
        units = [
            _unit(1, 1, reference_col, row, "round", 12),
            _unit(2, 2, enemy_col, row, "oval", WARTRAKK_BASE),
        ]
        gs = _gs(units)
        if unit_entries_within_engagement_zone(
            gs["units_cache"]["1"], gs["units_cache"]["2"], get_engagement_zone(gs)
        ):
            return gs, enemy_col - reference_col
    raise AssertionError("fixture cassée : aucune position engagée trouvée")


def test_the_fixture_puts_the_pair_beyond_the_capped_horizon():
    """Prémisse : sans elle, le test passerait pour une paire que le plafond n'éliminait pas."""
    from engine.phase_handlers.movement_handlers import (
        _hex_radius_upper_for_engagement_prune,
        _move_preview_footprint_span,
    )

    gs, anchor_distance = _engaging_pair()
    enemy_entry = gs["units_cache"]["2"]
    ref_entry = gs["units_cache"]["1"]
    ref_r = _hex_radius_upper_for_engagement_prune(
        ref_entry["BASE_SHAPE"], _move_preview_footprint_span(ref_entry)
    )
    capped_r = _hex_radius_upper_for_engagement_prune(
        enemy_entry["BASE_SHAPE"], min(_move_preview_footprint_span(enemy_entry), 35)
    )
    capped_horizon = EZ_SUBHEX + ref_r + capped_r + 1
    assert anchor_distance > capped_horizon, (
        f"prémisse cassée : la paire est à {anchor_distance}, l'horizon plafonné vaut "
        f"{capped_horizon} — le plafond ne l'éliminait pas, ce test ne prouve rien"
    )


def test_the_engagement_prune_keeps_a_pair_that_is_actually_engaged():
    """Le contrat : tout ce que la prune élimine est hors de portée d'engagement."""
    gs, _anchor_distance = _engaging_pair()
    kept = ObservationBuilder._engagement_relevant_entries(
        gs, gs["units_cache"]["1"], get_engagement_zone(gs), enemy_of_player=1
    )
    kept_ids = {id(entry) for entry in kept}
    assert id(gs["units_cache"]["2"]) in kept_ids, (
        "la prune a éliminé une escouade avec laquelle la référence EST en zone d'engagement : "
        "l'observation la déclarerait non engagée"
    )


def test_the_prune_still_drops_a_squad_far_out_of_reach():
    """Contre-épreuve : une prune qui ne rejette plus rien passerait le test ci-dessus."""
    units = [
        _unit(1, 1, 100, 150, "round", 12),
        _unit(2, 2, 300, 150, "oval", WARTRAKK_BASE),
    ]
    gs = _gs(units)
    assert not unit_entries_within_engagement_zone(
        gs["units_cache"]["1"], gs["units_cache"]["2"], get_engagement_zone(gs)
    ), "fixture cassée : les deux socles sont engagés"
    kept = ObservationBuilder._engagement_relevant_entries(
        gs, gs["units_cache"]["1"], get_engagement_zone(gs), enemy_of_player=1
    )
    assert id(gs["units_cache"]["2"]) not in {id(entry) for entry in kept}


def test_the_fixture_really_builds_a_footprint_wider_than_the_cap():
    """Sans un socle au-delà de `max_base_size_hex`, le plafond n'a aucun effet et le fichier
    entier deviendrait un vert vacant."""
    from engine.phase_handlers.movement_handlers import _move_preview_footprint_span

    gs = _gs([_unit(1, 1, 100, 150, "oval", WARTRAKK_BASE)])
    assert _move_preview_footprint_span(gs["units_cache"]["1"]) > 35
    assert len(compute_occupied_hexes(100, 150, "oval", WARTRAKK_BASE, 0)) > 1
