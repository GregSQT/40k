"""17.01 — les MONSTER/VEHICLE traversent les figurines pendant leur move normal ou leur advance.

« Each time you make a normal or advance move with a unit, MONSTER/VEHICLE models in that unit
can be moved through friendly and enemy models (excluding other MONSTER/VEHICLE models). »

Le moteur ne l'appliquait pas : il arrêtait un Dreadnought comme n'importe quelle infanterie. En
partie, ces unités étaient donc moins mobiles que la règle ne le permet ; à l'entraînement,
l'agent apprenait une géométrie qui n'est pas celle du jeu. L'écart a été trouvé en instrumentant
l'analyzer, qui, lui, appliquait déjà la règle — et ne pouvait donc PAS le signaler, un moteur
plus strict que la règle ne produisant jamais de ligne fautive.

Ce fichier verrouille les quatre bornes de l'exemption, parce que chacune est une condition écrite
dans la règle et non une précaution : le mot-clé de la FIGURINE, l'exclusion des autres M/V, la
phase de mouvement, et le fait que traverser n'est pas s'arrêter.

Tout passe par `build_move_traversal_blocked`, qui est la source unique des figurines bloquantes
depuis ce chantier — les sept sites qui posaient la question chacun de leur côté (pool NumPy,
pool d'ancre euclidien, pool par-figurine, BFS par-figurine, descente et montée d'étage, borne de
trajet de la validation) la lisent tous ici. Tester ailleurs ne testerait qu'une des sept copies.
"""

from typing import Iterable, Tuple

import pytest

from engine.phase_handlers.shared_utils import (
    build_move_traversal_blocked,
    build_move_transit_blocked,
    geodesic_move_reach,
    squad_traverses_models_17_01,
)
from tests._state_invariants import turn_state_invariants, unit_invariants


MOVE_SUBHEX = 30
MOVER_ANCHOR = (10, 10)
#: Écran ennemi : une colonne pleine, assez loin du mobile pour qu'il ne soit PAS engagé (la zone
#: d'engagement vaut 1 ici, donc l'adjacence). Un mobile engagé ferait un fall-back, que 17.01 ne
#: couvre pas — la géométrie doit donc écarter ce cas, pas s'y appuyer.
SCREEN_COL = 16
#: L'écran couvre TOUTE la hauteur du plateau : un écran partiel se contourne dans le budget, et
#: le test mesurerait alors la longueur du détour, pas la traversée.
SCREEN = tuple((SCREEN_COL, row) for row in range(60))
BEYOND = (18, 10)

VEHICLE_KEYWORDS = [{"keywordId": "VEHICLE"}]


def _model(col, row, player, squad_id, keywords):
    return {
        "col": col, "row": row, "level": 0, "player": player, "squad_id": squad_id,
        "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        "UNIT_KEYWORDS": list(keywords),
    }


def _game_state(*, mover_keywords: Iterable = (), screen_keywords: Iterable = (), phase="move"):
    """Mobile solo en (10,10), écran ennemi colonne 16. Les mots-clés des deux côtés varient."""
    models_cache = {"1#0": _model(*MOVER_ANCHOR, 1, "1", mover_keywords)}
    for i, (col, row) in enumerate(SCREEN):
        models_cache[f"2#{i}"] = _model(col, row, 2, "2", screen_keywords)
    unit = {**unit_invariants(),
        "id": 1, "player": 1, "col": MOVER_ANCHOR[0], "row": MOVER_ANCHOR[1],
        "MOVE": MOVE_SUBHEX, "HP_CUR": 1, "BASE_SIZE": 1, "BASE_SHAPE": "round",
        "UNIT_KEYWORDS": list(mover_keywords),
    }
    enemy = {**unit_invariants(),
        "id": 2, "player": 2, "col": SCREEN[0][0], "row": SCREEN[0][1],
        "MOVE": MOVE_SUBHEX, "HP_CUR": 1, "BASE_SIZE": 1, "BASE_SHAPE": "round",
        "UNIT_KEYWORDS": list(screen_keywords),
    }
    return {**turn_state_invariants(),
        "models_cache": models_cache,
        "squad_models": {"1": ["1#0"], "2": [f"2#{i}" for i in range(len(SCREEN))]},
        "units_cache": {
            "1": {"col": MOVER_ANCHOR[0], "row": MOVER_ANCHOR[1], "player": 1,
                  "occupied_hexes": {MOVER_ANCHOR}, "BASE_SHAPE": "round", "BASE_SIZE": 1,
                  "HP_CUR": 1},
            "2": {"col": SCREEN[0][0], "row": SCREEN[0][1], "player": 2,
                  "occupied_hexes": set(SCREEN), "BASE_SHAPE": "round", "BASE_SIZE": 1,
                  "HP_CUR": 1},
        },
        "units": [unit, enemy],
        "unit_by_id": {"1": unit, "2": enemy},
        "board_cols": 44,
        "board_rows": 60,
        "wall_hexes": set(),
        "enemy_adjacent_hexes_player_1": set(),
        "config": {
            "game_rules": {"engagement_zone": 1},
            "move": {"can_move_through_enemy_engagement_zone": True,
                     "can_move_through_enemy_model": False,
                     "can_move_through_friendly_model": True},
        },
        "phase": phase,
        "inches_to_subhex": 1,
        "units_took_to_skies": set(),
        "terrain_areas": [],
    }


def _enemy_blocked(gs):
    return build_move_traversal_blocked(gs, "1", 1, 0)[0]


def _can_reach_beyond(gs) -> bool:
    """Le mobile atteint-il l'autre côté de l'écran, dans son budget, par un vrai chemin ?"""
    transit = build_move_transit_blocked(gs, "1", 1, 0)
    field = geodesic_move_reach(*MOVER_ANCHOR, MOVE_SUBHEX, transit, 44, 60)
    return BEYOND in field


# ─────────────────────────────────────────────────────────────────────────────
# Prémisses : sans elles, « le véhicule passe » ne prouverait rien
# ─────────────────────────────────────────────────────────────────────────────

def test_premise_the_screen_really_stops_infantry():
    """Une escouade sans mot-clé est arrêtée par l'écran : la géométrie mord."""
    gs = _game_state()
    assert set(SCREEN) <= _enemy_blocked(gs), "l'écran ne bloque plus personne"
    assert not _can_reach_beyond(gs), "l'infanterie traverse : le test ne démontrerait rien"


def test_premise_the_screen_is_out_of_engagement_range():
    """Un mobile ENGAGÉ ferait un fall-back, que 17.01 ne couvre pas. La géométrie doit donc
    placer l'écran hors de portée d'engagement, sinon le test mesurerait l'autre règle."""
    gs = _game_state(mover_keywords=VEHICLE_KEYWORDS)
    assert squad_traverses_models_17_01(gs, "1"), (
        "le mobile est considéré engagé (ou hors phase de mouvement) : l'exemption ne s'applique "
        "pas, et les tests suivants ne mesureraient plus 17.01"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 17.01
# ─────────────────────────────────────────────────────────────────────────────

def test_a_vehicle_moves_through_enemy_infantry():
    gs = _game_state(mover_keywords=VEHICLE_KEYWORDS)
    assert not (set(SCREEN) & _enemy_blocked(gs)), "l'écran d'infanterie bloque encore un VEHICLE"
    assert _can_reach_beyond(gs), "le VEHICLE n'atteint pas l'autre côté de l'écran (17.01)"


def test_a_vehicle_does_not_move_through_other_vehicles():
    """« excluding other MONSTER/VEHICLE models » — l'exemption s'arrête là, et seulement là."""
    gs = _game_state(mover_keywords=VEHICLE_KEYWORDS, screen_keywords=VEHICLE_KEYWORDS)
    assert set(SCREEN) <= _enemy_blocked(gs), "un M/V a traversé un autre M/V"
    assert not _can_reach_beyond(gs)


def test_the_exemption_does_not_apply_outside_the_movement_phase():
    """12.03 : le pile-in et la consolidation sont des déplacements de la phase de COMBAT.
    17.01 ne parle que du move normal et de l'advance."""
    gs = _game_state(mover_keywords=VEHICLE_KEYWORDS, phase="fight")
    assert not squad_traverses_models_17_01(gs, "1")
    assert set(SCREEN) <= _enemy_blocked(gs), (
        "l'exemption de mouvement s'applique en phase de combat : un pile-in traverserait les "
        "figurines ennemies"
    )


def test_the_exemption_does_not_apply_to_an_engaged_mover():
    """Dans la phase de mouvement, une escouade engagée ne peut faire qu'un fall-back (09.05 et
    09.06 exigent `unengaged`), et le fall-back a sa propre traversée — Desperate Escape."""
    gs = _game_state(mover_keywords=VEHICLE_KEYWORDS)
    # Une SECONDE escouade ennemie vient au contact du mobile : il devient engagé, donc en
    # fall-back. Une escouade à part, et non une figurine ajoutée à l'écran : c'est l'ANCRE qui
    # porte l'engagement à cette résolution.
    contact = (MOVER_ANCHOR[0] + 1, MOVER_ANCHOR[1])
    gs["models_cache"]["3#0"] = _model(*contact, 2, "3", ())
    gs["squad_models"]["3"] = ["3#0"]
    gs["units_cache"]["3"] = {
        "col": contact[0], "row": contact[1], "player": 2, "occupied_hexes": {contact},
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "HP_CUR": 1,
    }
    assert not squad_traverses_models_17_01(gs, "1"), (
        "l'exemption s'applique à un mobile engagé : elle couvrirait le fall-back, que la règle "
        "en exclut"
    )


def test_traversing_is_not_stopping_on_top_of_a_model():
    """17.01 autorise à TRAVERSER. La destination reste filtrée par l'occupation — un véhicule ne
    finit pas son mouvement sur une figurine ennemie."""
    from engine.phase_handlers.shared_utils import build_enemy_occupied_positions_set

    gs = _game_state(mover_keywords=VEHICLE_KEYWORDS)
    occupied = build_enemy_occupied_positions_set(gs, current_player=1, level=0)
    assert set(SCREEN) <= occupied, (
        "l'occupation ennemie a été amputée par 17.01 : le filtre de destination laisserait un "
        "véhicule se poser sur une figurine"
    )


def test_a_mixed_squad_raises_instead_of_guessing():
    """La règle se lit par FIGURINE. Un pool d'ancre ne connaît que l'escouade : plutôt que de
    trancher pour toute l'escouade, il lève. Aucune escouade ne peut être mixte aujourd'hui —
    l'attachement 19.01 exige la règle `leader`, qu'aucune M/V du registre ne porte."""
    gs = _game_state(mover_keywords=VEHICLE_KEYWORDS)
    gs["models_cache"]["1#1"] = _model(MOVER_ANCHOR[0], MOVER_ANCHOR[1] + 1, 1, "1", ())
    gs["squad_models"]["1"].append("1#1")
    with pytest.raises(ValueError, match=r"17\.01"):
        squad_traverses_models_17_01(gs, "1")


def test_the_per_model_verdict_wins_when_the_model_is_known():
    """Les pools par-figurine passent le `model` : le verdict est alors exact, sans garde."""
    gs = _game_state(mover_keywords=VEHICLE_KEYWORDS)
    gs["models_cache"]["1#1"] = _model(MOVER_ANCHOR[0], MOVER_ANCHOR[1] + 1, 1, "1", ())
    gs["squad_models"]["1"].append("1#1")
    assert squad_traverses_models_17_01(gs, "1", gs["models_cache"]["1#0"]) is True
    assert squad_traverses_models_17_01(gs, "1", gs["models_cache"]["1#1"]) is False
