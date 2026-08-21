"""Masque ⊆ exécutable — une formation DÉJÀ hors coherency n'offre AUCUNE destination.

Défaut corrigé : `erode_move_pool_by_squad_block` documentait `require_coherency` comme « déjà
garanti par le pool d'ancre », au motif qu'il est invariant par translation rigide. L'invariance
est vraie (`test_coherency_translation_invariance`) mais elle SE RETOURNE : depuis une formation
déjà incohérente, la translation préserve l'incohérence, donc `explain_move_plan_rejection`
refuse CHAQUE candidate que le pool laisse passer.

Le masque offrait alors tout son pool à une escouade dont aucun mouvement n'est exécutable, et
`execute_squad_move` levait, tuant le worker :

    ValueError: execute_squad_move a échoué : squad=101 type=normal dest=(24,10) depuis (19,6)
    … Contrainte violée : coherency du plan invalide (formation actuelle DEJA incoherente)

C'est la variante complémentaire du crash verrouillé par `test_coherency_translation_invariance`
(« formation actuelle **coherente** ») : les deux moitiés du même invariant.

Comportement attendu — pool VIDE, et c'est LA RÈGLE, pas un repli :
  - 03.01 ENDING A MOVE : une unité qui ne peut pas finir en coherency « cannot make that move »,
    ses figurines reviennent à leur position de départ, elle reste stationnaire (09.04) ;
  - 03.03 REGAINING COHERENCY : la fin de tour retire des figurines jusqu'au retour en coherency,
    donc l'immobilisation dure au plus le reste du tour — ce n'est pas un gel définitif.

Cycle rouge→vert : supprimer le court-circuit « Formation d'ORIGINE deja hors coherency » de
`build_squad_move_cell_map` fait passer `test_incoherent_origin_yields_empty_move_pool` en rouge.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple

from engine.phase_handlers.shared_utils import (
    build_squad_move_cell_map,
    validate_squad_coherency,
)
from tests._state_invariants import turn_state_invariants, unit_invariants

MOVE_SUBHEX = 8

# Cohérence 03.03 à x1 : voisin à <= 2 cases, aucune paire au-delà de 9.
COH_RANGE = 2
COH_MAX = 9


def _game_state(model_positions: Iterable[Tuple[int, int]]) -> Dict[str, Any]:
    """Escouade "1" dont les figurines occupent exactement `model_positions` (ancre = 1re)."""
    positions = list(model_positions)
    models_cache = {
        f"1#{i}": {
            "col": col, "row": row, "level": 0, "player": 1, "squad_id": "1", "HP_CUR": 1,
            "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        }
        for i, (col, row) in enumerate(positions)
    }
    anchor_col, anchor_row = positions[0]
    unit = {
        **unit_invariants(),
        "id": 1, "player": 1, "col": anchor_col, "row": anchor_row, "MOVE": MOVE_SUBHEX,
        "HP_CUR": 1, "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": [],
    }
    return {
        **turn_state_invariants(),
        "models_cache": models_cache,
        "squad_models": {"1": [f"1#{i}" for i in range(len(positions))]},
        "units_cache": {
            "1": {
                "col": anchor_col, "row": anchor_row, "player": 1, "occupied_hexes": set(),
                "BASE_SHAPE": "round", "BASE_SIZE": 1, "level": 0,
            }
        },
        "units": [unit],
        "unit_by_id": {"1": unit},
        "board_cols": 44,
        "board_rows": 60,
        "wall_hexes": set(),
        "enemy_adjacent_hexes_player_1": set(),
        "config": {
            "game_rules": {
                "engagement_zone": 1,
                "unit_model_cohesion_range": COH_RANGE,
                "unit_global_cohesion_range": COH_MAX,
                "squad_min_neighbors": 1,
                "cohesion_distance_mode": "footprint",
            },
            "move": {
                "can_move_through_enemy_engagement_zone": True,
                "can_move_through_enemy_model": False,
                "can_move_through_friendly_model": True,
            },
        },
        "phase": "move",
        "current_player": 1,
        "inches_to_subhex": 1,
        "units_took_to_skies": set(),
        "terrain_areas": [],
    }


# Formation serrée : chaque figurine a une voisine à 1 case → cohérente.
COHERENT = [(10, 10), (11, 10), (12, 10)]
# Même escouade après des pertes : la figurine de liaison a disparu et les deux survivantes
# sont à 6 cases l'une de l'autre (> 2) → deux composantes, formation incohérente.
INCOHERENT = [(10, 10), (16, 10)]


def test_coherent_origin_still_offers_destinations() -> None:
    """Garde-fou anti vert-vacant : la formation cohérente, elle, garde un pool NON vide.

    Sans ce test, « pool vide » passerait aussi avec une fixture qui ne produit jamais de
    destination (budget nul, plateau saturé) — le verrou ne mesurerait alors plus rien.
    """
    gs = _game_state(COHERENT)
    assert validate_squad_coherency(gs, "1"), "fixture invalide : formation censée être cohérente"

    cell_map = build_squad_move_cell_map(gs, "1", None)

    assert cell_map, "une escouade cohérente doit se voir offrir des destinations"


def test_incoherent_origin_yields_empty_move_pool() -> None:
    """Formation déjà hors coherency → pool VIDE (03.01 : l'unité ne peut pas faire ce move)."""
    gs = _game_state(INCOHERENT)
    assert not validate_squad_coherency(gs, "1"), (
        "fixture invalide : formation censée être incohérente"
    )

    cell_map = build_squad_move_cell_map(gs, "1", None)

    assert cell_map == {}, (
        "le masque offre des destinations à une escouade hors coherency : la translation rigide "
        "préserve l'incohérence, donc validate_move_plan les refusera TOUTES et "
        f"execute_squad_move lèvera. Cellules offertes : {len(cell_map)}"
    )
