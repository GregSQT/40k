"""09.05/03.04 — l'empreinte d'une escouade ne doit pas se réduire à son ancre quand celle-ci meurt.

`units_cache[squad]["occupied_hexes"]` est l'UNION des socles vivants. C'est ce champ que
`build_enemy_adjacent_hexes` dilate pour produire `enemy_adjacent_hexes_player_N`, la zone
d'engagement que `validate_move_plan` oppose à chaque déplacement (et que lisent aussi la LoS et
le ciblage).

DÉFAUT VERROUILLÉ, mesuré le 2026-08-12 sur un run x1 instrumenté (E4 T5). `destroy_model`
recalcule correctement l'union après un retrait, PUIS recalcule l'ancre — et quand la figurine
d'index minimum est celle qui meurt, l'ancre change et `update_units_cache_position` réécrivait
`occupied_hexes` avec l'empreinte de la SEULE ancre. L'escouade 102, 11 socles étalés de (0,35)
à (7,38), se retrouvait ainsi avec `occupied_hexes == {(1,38)}` :

  - sa zone d'engagement se réduisait à un disque autour de (1,38) ;
  - l'unité 3 a terminé son move NORMAL en (7,37), à 1 subhex de 102#7@(6,38) — donc ENGAGÉE,
    ce que 09.05 « AFTER MOVING: Your unit must be unengaged » interdit ;
  - `explain_move_plan_rejection` ne voyait rien à redire : la case n'était pas dans le set.

C'est la cause des 17 « move to adjacent enemy / fall-back finit engagé / advance depuis une case
adjacente » du rapport d'analyzer du 2026-08-12, et elle est rare pour une raison précise : il
faut que ce soit l'ANCRE qui tombe.
"""

import pytest

from engine.phase_handlers.shared_utils import (
    build_enemy_adjacent_hexes,
    destroy_model,
    explain_move_plan_rejection,
)

SQUAD, ENEMY_PLAYER = "102", 2
MOVER, MOVER_PLAYER = "3", 1
# Positions du témoin. 102#0 est l'ANCRE (index minimum) et c'est elle qui meurt.
ANCHOR_MODEL, ANCHOR_POS = "102#0", (1, 38)
# Ordre d'insertion = ordre de `squad_models`, donc ordre de reprise de l'ancre : la NOUVELLE
# ancre sera 102#3@(2,37), loin de la destination. Sans cette précaution le témoin passerait
# par accident — l'ancre de repli couvrirait elle-même la case visée.
OTHERS = {"102#3": (2, 37), "102#5": (4, 38), "102#7": (6, 38)}
# Destination du move normal : à 1 subhex de 102#7, donc dans la zone d'engagement (EZ=2),
# mais LOIN de l'ancre — c'est tout l'objet du témoin.
DEST = (7, 37)
EZ = 2


def _model(col, row, player, squad):
    return {"col": col, "row": row, "level": 0, "player": player, "squad_id": squad,
            "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0}


def _gs():
    enemy_models = {ANCHOR_MODEL: ANCHOR_POS, **OTHERS}
    models_cache = {mid: _model(c, r, ENEMY_PLAYER, SQUAD) for mid, (c, r) in enemy_models.items()}
    models_cache[f"{MOVER}#0"] = _model(20, 37, MOVER_PLAYER, MOVER)
    gs = {
        "models_cache": models_cache,
        "squad_models": {SQUAD: list(enemy_models), MOVER: [f"{MOVER}#0"]},
        "units_cache": {
            SQUAD: {"col": ANCHOR_POS[0], "row": ANCHOR_POS[1], "player": ENEMY_PLAYER,
                    "HP_CUR": len(enemy_models), "BASE_SHAPE": "round", "BASE_SIZE": 1,
                    "orientation": 0, "occupied_hexes": set(enemy_models.values()),
                    "occupied_hexes_by_model": dict(enemy_models),
                    "floor_height_by_model": {m: 0.0 for m in enemy_models},
                    "level_by_model": {m: 0 for m in enemy_models}, "MODEL_HEIGHT": 2.0},
            MOVER: {"col": 20, "row": 37, "player": MOVER_PLAYER, "HP_CUR": 1,
                    "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
                    "occupied_hexes": {(20, 37)}, "occupied_hexes_by_model": {f"{MOVER}#0": (20, 37)},
                    "floor_height_by_model": {f"{MOVER}#0": 0.0},
                    "level_by_model": {f"{MOVER}#0": 0}, "MODEL_HEIGHT": 2.0},
        },
        "board_cols": 44, "board_rows": 60, "wall_hexes": set(),
        "_unit_move_version": 0, "terrain_areas": [],
        "inches_to_subhex": 1,
        # destroy_model émet un event "dead" via append_action_log → action_log_seq requis.
        "action_logs": [],
        "action_log_seq": 0,
        "config": {
            "game_rules": {"engagement_zone": EZ, "max_base_size_hex": 12,
                           "unit_model_cohesion_range": 2, "unit_global_cohesion_range": 9,
                           "squad_min_neighbors": 1, "cohesion_distance_mode": "euclidean"},
            "move": {"can_move_through_enemy_engagement_zone": True,
                     "can_move_through_enemy_model": False,
                     "can_move_through_friendly_model": True},
        },
        "phase": "move",
    }
    # Seul le cache du joueur qui BOUGE est observé (c'est celui que `explain_move_plan_rejection`
    # oppose au plan) : construire l'autre suggérerait que la symétrie fait partie du témoin.
    build_enemy_adjacent_hexes(gs, MOVER_PLAYER)
    return gs


def _kill_the_anchor(gs):
    """Retire la figurine d'ancre — le seul cas où le défaut se déclenche."""
    destroy_model(gs, ANCHOR_MODEL, reason="combat")
    build_enemy_adjacent_hexes(gs, MOVER_PLAYER)


def test_premise_the_dead_model_is_really_the_anchor():
    """Sans ce fait, le témoin ne reproduit rien : l'ancre est l'index minimum vivant."""
    gs = _gs()
    assert (gs["units_cache"][SQUAD]["col"], gs["units_cache"][SQUAD]["row"]) == ANCHOR_POS
    _kill_the_anchor(gs)
    assert (gs["units_cache"][SQUAD]["col"], gs["units_cache"][SQUAD]["row"]) != ANCHOR_POS, (
        "l'ancre n'a pas changé : le chemin fautif n'est pas emprunté, le test est inopérant"
    )


def test_the_footprint_stays_the_union_of_the_survivors():
    """Le champ que dilate la zone d'engagement doit couvrir TOUS les socles vivants."""
    gs = _gs()
    _kill_the_anchor(gs)

    occupied = gs["units_cache"][SQUAD]["occupied_hexes"]
    for mid, pos in OTHERS.items():
        assert pos in occupied, (
            f"{mid}@{pos} absente de occupied_hexes={sorted(occupied)} — l'empreinte a été "
            "réduite à l'ancre, et avec elle la zone d'engagement de l'escouade"
        )
    assert ANCHOR_POS not in occupied, "la figurine morte occupe encore une case"


def test_the_engagement_zone_still_covers_the_far_models():
    """La conséquence directe : la case visée doit redevenir interdite au move normal."""
    gs = _gs()
    _kill_the_anchor(gs)

    assert DEST in gs[f"enemy_adjacent_hexes_player_{MOVER_PLAYER}"], (
        "la destination n'est plus dans la zone d'engagement : un move normal peut y finir"
    )


def test_a_normal_move_ending_engaged_is_refused():
    """09.05 « AFTER MOVING: Your unit must be unengaged » — le verdict du témoin."""
    gs = _gs()
    _kill_the_anchor(gs)

    reason = explain_move_plan_rejection(
        [(f"{MOVER}#0", DEST[0], DEST[1], 0)], gs,
        {"budget_per_model": None, "require_coherency": False, "forbid_enemy_er": True},
    )

    assert reason is not None, (
        "plan accepté alors que la figurine finit à 1 subhex d'un socle ennemi (EZ=2) — "
        "c'est le move commité par le moteur le 2026-08-12 (E4 T5)"
    )
    assert "ER ennemie" in reason, f"refusé pour une autre raison que l'EZ : {reason}"
