"""Relocaliser une escouade déplace ses FIGURINES, pas seulement son ancre.

`update_units_cache_position` recale l'ANCRE — sa docstring le dit, et prévient : « à ne pas
confondre » avec `translate_squad_to_destination`, qui translate le bloc. Deux appelants s'en
servaient pourtant comme mécanisme de déplacement :

  - `_apply_move_after_shooting` (état RÉEL) — la capacité `move_after_shooting` est portée par
    le Gargoyle, une escouade multi-figurines. L'ancre partait à destination, les figurines
    restaient en place ;
  - `_apply_preview_placement` branche `"anchor"` (copie d'APERÇU) — `preview_shoot_from_position`
    répondait donc, pour chaque case survolée, avec la ligne de vue et les cibles de la position
    COURANTE de l'escouade.

Tant que `occupied_hexes` était réécrit avec l'empreinte de l'ancre, l'incohérence était
masquée : le champ « suivait » l'ancre en laissant `occupied_hexes_by_model` derrière. Depuis que
l'empreinte est l'union des socles vivants (correction du 2026-08-12), elle reste franchement à
l'origine — c'est le même défaut, devenu visible.
"""

import pytest

from engine.phase_handlers.shared_utils import (
    translate_squad_to_destination,
    update_units_cache_position,
)

SQUAD, PLAYER = "1", 1
POSITIONS = {"1#0": (10, 10), "1#1": (11, 10), "1#2": (12, 10)}
DEST = (20, 30)


def _gs():
    models_cache = {
        mid: {"col": c, "row": r, "level": 0, "player": PLAYER, "squad_id": SQUAD,
              "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0}
        for mid, (c, r) in POSITIONS.items()
    }
    return {
        "models_cache": models_cache,
        "squad_models": {SQUAD: list(POSITIONS)},
        "units_cache": {SQUAD: {
            "col": POSITIONS["1#0"][0], "row": POSITIONS["1#0"][1], "player": PLAYER,
            "HP_CUR": len(POSITIONS), "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
            "occupied_hexes": set(POSITIONS.values()),
            "occupied_hexes_by_model": dict(POSITIONS),
            "floor_height_by_model": {m: 0.0 for m in POSITIONS},
            "level_by_model": {m: 0 for m in POSITIONS},
            "orientation_by_model": {m: 0 for m in POSITIONS},
            "MODEL_HEIGHT": 2.0,
        }},
        "board_cols": 44, "board_rows": 60, "wall_hexes": set(),
        "_unit_move_version": 0, "terrain_areas": [], "inches_to_subhex": 1,
        "config": {"game_rules": {"engagement_zone": 2, "max_base_size_hex": 12}},
    }


def test_translation_moves_every_model_and_the_footprint():
    """La primitive de déplacement translate le bloc entier — c'est ce qu'un move exige."""
    gs = _gs()
    translate_squad_to_destination(gs, SQUAD, DEST[0], DEST[1])

    entry = gs["units_cache"][SQUAD]
    assert (entry["col"], entry["row"]) == DEST
    assert set(entry["occupied_hexes_by_model"].values()) == set(entry["occupied_hexes"]), (
        "les deux cartes de position décrivent des endroits différents"
    )
    assert POSITIONS["1#0"] not in entry["occupied_hexes"], (
        f"l'empreinte est restée à l'origine : {sorted(entry['occupied_hexes'])}"
    )


@pytest.mark.parametrize("n_models", [1, 3], ids=["mono", "multi"])
def test_translation_refreshes_the_per_model_orientation_map(n_models):
    """`orientation_by_model` n'a qu'un producteur : le resync par-figurine de la translation.

    Le front (`useEngineAPI`, `BoardPvp`) préfère cette carte à l'orientation d'unité : la
    laisser périmée fait rendre un socle non rond à son ANCIENNE facing après un pivot.

    LES DEUX TAILLES, et c'est le sujet : au-dessus d'une figurine, l'écrivain d'ancre recalcule
    lui-même toutes les cartes ; à UNE figurine il prend une branche courte qui écrit la position,
    la hauteur et le niveau — mais pas l'orientation. C'est cette branche-là que l'appel final de
    `translate_squad_to_destination` protège, et un test qui ne l'exercerait pas laisserait
    supprimer cet appel sans qu'aucun rouge n'apparaisse.
    """
    gs = _gs()
    kept = list(POSITIONS)[:n_models]
    gs["squad_models"][SQUAD] = kept
    for mid in list(gs["models_cache"]):
        if mid.startswith(f"{SQUAD}#") and mid not in kept:
            del gs["models_cache"][mid]
    gs["units_cache"][SQUAD].pop("orientation_by_model")
    for mid in kept:
        gs["models_cache"][mid]["orientation"] = 3

    translate_squad_to_destination(gs, SQUAD, DEST[0], DEST[1])

    orient = gs["units_cache"][SQUAD].get("orientation_by_model")
    assert orient, (
        f"orientation_by_model non réécrite pour une escouade de {n_models} figurine(s) : "
        "le front rendra une facing périmée"
    )
    assert set(orient.values()) == {3}, orient


def test_anchor_resync_never_relocates_the_models():
    """L'autre primitive garde sa sémantique : recaler l'ancre SANS toucher aux figurines.

    C'est ce qu'exige son seul usage légitime — la mort d'une figurine, après laquelle l'ancre
    change alors que les survivantes n'ont pas bougé. Un appelant qui veut DÉPLACER doit donc
    prendre `translate_squad_to_destination`, et ce test dit pourquoi les deux ne sont pas
    interchangeables.
    """
    gs = _gs()
    update_units_cache_position(gs, SQUAD, DEST[0], DEST[1])

    entry = gs["units_cache"][SQUAD]
    assert (entry["col"], entry["row"]) == DEST, "l'ancre doit suivre"
    assert dict(entry["occupied_hexes_by_model"]) == POSITIONS, (
        "les figurines ont bougé : ce n'est pas la sémantique de cette primitive"
    )
    assert set(entry["occupied_hexes"]) == set(POSITIONS.values()), (
        "l'empreinte doit rester l'union des socles VIVANTS, où qu'aille l'ancre"
    )
