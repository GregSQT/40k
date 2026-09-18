"""V11 §0.34 — le masque de move et l'exécution doivent mesurer la MEME grandeur.

Trois divergences mesurées in-engine (43 crashes / 650 pas d'actions légales aléatoires sur
`scenario_pvp_test`), toutes de la famille « masque ⊆ exécutable » :

1. **Frontière normal/advance** — le pool d'ancre retranche le coût de descente §13.06 de son
   budget (`movement_build_valid_destinations_pool`) et `resolve_squad_move_constraints` le
   retranche aussi à l'exécution, mais la CLASSIFICATION comparait le coût au `MOVE` BRUT `M`.
   Les cellules de la bande `(M - descente, M]` étaient donc classées `normal` puis validées
   avec `M - descente` → `execute_squad_move a échoué … trajet légal > budget`.

2. **Niveau de destination** — `build_rigid_plan` n'émettait pas de niveau, et « pas de niveau »
   signifie pour `commit_move` « garder le niveau courant » : une figurine partie d'un étage
   restait marquée à l'étage sur une case de sol → `floor_height_at: no floor at level 1
   contains cell …`, et sa destination était testée contre l'occupation d'un AUTRE étage.

3. **Mesure FLY sous métrique hex** — la validation borne la distance CUBE, la comptabilisation
   mesurait un champ EUCLIDIEN converti par `× 1,5` alors qu'un pas vers le sud vaut `sqrt(3)` :
   un plan validé ressortait « injoignable » de sa propre mesure.

Géométrie des fixtures : `inches_to_subhex = 1`, escouade mono-figurine sur un plancher de
niveau 1 haut de 3" → `MOVE = 6`, descente = 3, frontière = 3, budget Advance = 6 + jet - 3.
"""

from typing import Any, Dict, List, Tuple

import pytest

from engine.phase_handlers.movement_handlers import (
    get_eligible_units,
    model_rigid_level_map,
    movement_build_valid_destinations_pool,
    squad_floor_level_map,
)
from engine.terrain_utils import floor_hexes_at_level
from engine.phase_handlers.shared_utils import (
    SQUAD_RIGID_MOVE_DESTINATION_LEVEL,
    build_rigid_plan,
    build_squad_move_cell_map,
    explain_move_plan_rejection,
    infer_squad_move_type,
    move_plan_path_distances,
    resolve_squad_move_constraints,
    squad_normal_move_frontier_subhex,
)
from tests._state_invariants import turn_state_invariants, unit_invariants

MOVE = 6
FLOOR_HEIGHT_INCHES = 3.0
ADVANCE_ROLL = 2
START = (10, 20)


def _gs(*, level: int, fly: bool = False, move: int = MOVE) -> Dict[str, Any]:
    """`game_state` minimal — uniquement ce que lisent le pool, la validation et la mesure.

    `level=1` place la figurine sur le plancher de niveau 1 (dont l'empreinte contient sa case) :
    `squad_descent_penalty_subhex` facture alors 3 subhexes de descente. `level=0` est le témoin
    tout-au-sol, où la descente vaut 0 et où rien ne doit changer.
    """
    keywords = [{"keywordId": "fly"}] if fly else []
    unit = {**unit_invariants(),
        "id": 1, "player": 1, "col": START[0], "row": START[1], "MOVE": move,
        "HP_CUR": 1, "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": keywords,
        "level": level,
    }
    models_cache = {
        "1#0": {
            "col": START[0], "row": START[1], "level": level, "player": 1, "squad_id": "1",
            "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        },
    }
    # Plancher de niveau 1 couvrant la case de départ (sinon `floor_height_at` lève, cf. bug 2).
    floor_hexes = [[START[0] + dc, START[1] + dr] for dc in (-1, 0, 1) for dr in (-1, 0, 1)]
    # Polygone du plancher (col/row), comme en production (`game_state.py`) : le confinement
    # euclidien d'un socle rond (`resolve_model_floor_level`) le lit dès qu'une figurine en
    # hauteur cherche où son étage continue (`model_rigid_level_map`).
    floor_polygon = [
        [START[0] - 2, START[1] - 2], [START[0] + 3, START[1] - 2],
        [START[0] + 3, START[1] + 3], [START[0] - 2, START[1] + 3],
    ]
    return {**turn_state_invariants(),
        "models_cache": models_cache,
        "squad_models": {"1": ["1#0"]},
        "units_cache": {"1": {"col": START[0], "row": START[1], "player": 1,
                              "occupied_hexes": set(), "BASE_SHAPE": "round", "BASE_SIZE": 1}},
        "units": [unit],
        "unit_by_id": {"1": unit},
        "board_cols": 44, "board_rows": 60,
        "wall_hexes": set(),
        "enemy_adjacent_hexes_player_1": set(),
        "config": {
            # `unit_model_cohesion_range` en subhexes (déjà converti, cf. `game_state.py`) : la
            # coherency 03.03 est lue par la validation de plan dès qu'il y a 2 figurines.
            "game_rules": {
                "engagement_zone": 1, "unit_model_cohesion_range": 2,
                "unit_global_cohesion_range": 9, "cohesion_distance_mode": "euclidean",
                "squad_min_neighbors": 1,
            },
            "move": {"can_move_through_enemy_engagement_zone": True,
                     "can_move_through_enemy_model": False,
                     "can_move_through_friendly_model": True},
        },
        "phase": "move",
        "gym_training_mode": True,  # → métrique hex (move_gym)
        "inches_to_subhex": 1,
        "units_took_to_skies": set(),
        "current_player": 1,
        "terrain_areas": [
            {"floors": [{"level": 1, "height_inches": FLOOR_HEIGHT_INCHES, "hexes": floor_hexes,
                         "polygon_vertices": floor_polygon}]},
        ],
    }


def _plan(cell: Tuple[int, int], gs: Dict[str, Any]) -> List[Tuple[Any, ...]]:
    plan = build_rigid_plan(cell[0], cell[1], "1", gs)
    assert plan is not None, "escouade '1' sans figurine vivante"
    return plan


# ── 1. Frontière normal/advance ──────────────────────────────────────────────────────────


def test_descent_shrinks_the_normal_advance_frontier():
    """La frontière est le budget normal EXECUTABLE, pas le `MOVE` brut."""
    gs_ground = _gs(level=0)
    gs_floor = _gs(level=1)
    assert squad_normal_move_frontier_subhex(gs_ground, "1") == MOVE
    assert squad_normal_move_frontier_subhex(gs_floor, "1") == MOVE - int(FLOOR_HEIGHT_INCHES)


def test_dead_band_cost_is_classified_advance_not_normal():
    """Un coût dans `(M - descente, M]` exige un Advance : le classer `normal` le rend
    inexécutable (budget appliqué = `M - descente`). C'est LA ligne de la divergence."""
    gs = _gs(level=1)
    dead_band_cost = float(MOVE)  # 6 : <= M, mais > M - descente = 3
    assert infer_squad_move_type(gs, "1", dead_band_cost) == "advance"
    assert infer_squad_move_type(gs, "1", 3.0) == "normal"


def test_every_masked_cell_of_a_descending_squad_is_executable():
    """Invariant « masque ⊆ exécutable » sur le cas MONO-figurine partie de l'étage.

    Le court-circuit mono-figurine de `erode_move_pool_by_squad_block` ne s'applique pas en
    hauteur (le trajet à l'étage n'est pas le BFS de sol du pool d'ancre) : c'est l'érosion
    par-figurine, frontière exécutable comprise, qui tient ici l'invariant — et c'est
    exactement la configuration qui crashait le training quand la frontière était fausse.
    """
    gs = _gs(level=1)
    cell_map = build_squad_move_cell_map(gs, "1", ADVANCE_ROLL)
    assert cell_map, "pool vide : la fixture n'exerce rien"
    frontier = squad_normal_move_frontier_subhex(gs, "1")
    dead_band = 0
    for (cell, cost) in cell_map.values():
        move_type = infer_squad_move_type(gs, "1", cost)
        if frontier < cost <= MOVE:
            dead_band += 1
        constraints = resolve_squad_move_constraints(
            "1", gs, move_type, ADVANCE_ROLL if move_type == "advance" else None
        )
        reason = explain_move_plan_rejection(_plan(cell, gs), gs, constraints)
        assert reason is None, (
            f"cellule {cell} (coût {cost}, type {move_type}) offerte par le masque mais REFUSÉE "
            f"par la validation : {reason}"
        )
    assert dead_band > 0, (
        "aucune cellule dans la bande morte (M - descente, M] : le test ne prouve rien"
    )


def test_ground_squad_frontier_is_unchanged():
    """Contre-épreuve : sans descente, la frontière reste le MOVE — zéro régression au sol."""
    gs = _gs(level=0)
    assert infer_squad_move_type(gs, "1", float(MOVE)) == "normal"
    assert infer_squad_move_type(gs, "1", MOVE + 0.5) == "advance"


def _gs_pair(*, level: int) -> Dict[str, Any]:
    """Même fixture, mais à DEUX figurines : l'érosion par bloc n'est plus court-circuitée."""
    gs = _gs(level=level)
    sister = (START[0] + 2, START[1])
    gs["models_cache"]["1#1"] = {
        "col": sister[0], "row": sister[1], "level": level, "player": 1, "squad_id": "1",
        "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
    }
    gs["squad_models"]["1"] = ["1#0", "1#1"]
    gs["terrain_areas"][0]["floors"][0]["hexes"].extend(
        [[sister[0] + dc, sister[1] + dr] for dc in (-1, 0, 1) for dr in (-1, 0, 1)]
    )
    return gs


def test_erosion_keeps_the_dead_band_cells_of_a_descending_squad():
    """L'érosion doit appliquer la MÊME frontière que le masque et le décodeur.

    Comparée au `MOVE` brut, elle traitait les cellules de `(M - descente, M]` comme du `normal`
    et les érodait comme « hors budget » — pas de crash, mais des Advances légaux SUPPRIMÉS du
    masque. Ce test verrouille le second usage de la frontière.
    """
    gs = _gs_pair(level=1)
    frontier = squad_normal_move_frontier_subhex(gs, "1")
    assert frontier < MOVE, "fixture sans descente : rien à prouver"
    cell_map = build_squad_move_cell_map(gs, "1", ADVANCE_ROLL)
    kept_dead_band = [
        (cell, cost) for (cell, cost) in cell_map.values() if frontier < cost <= MOVE
    ]
    assert kept_dead_band, (
        "toutes les cellules de la bande morte ont été érodées : l'érosion n'utilise pas la "
        "frontière exécutable"
    )
    for cell, cost in kept_dead_band:
        move_type = infer_squad_move_type(gs, "1", cost)
        assert move_type == "advance"
        constraints = resolve_squad_move_constraints("1", gs, move_type, ADVANCE_ROLL)
        assert explain_move_plan_rejection(_plan(cell, gs), gs, constraints) is None


def test_erosion_reads_the_single_frontier_source(monkeypatch):
    """Verrou de CÂBLAGE : l'érosion LIT `squad_normal_move_frontier_subhex`, elle ne re-duplique
    pas la formule `max(0, M - descente)` en ligne. Ré-inliner la formule ferait diverger
    l'érosion du masque en silence à la prochaine évolution de la pénalité — ce test rougit."""
    import engine.phase_handlers.shared_utils as su

    gs = _gs_pair(level=1)
    calls: List[str] = []
    real = su.squad_normal_move_frontier_subhex

    def spy(state: Dict[str, Any], squad_id: str) -> int:
        calls.append(str(squad_id))
        return real(state, squad_id)

    monkeypatch.setattr(su, "squad_normal_move_frontier_subhex", spy)
    su.erode_move_pool_by_squad_block(
        gs, "1", {START: 0.0, (START[0] + 1, START[1]): 1.0}, move_budget=None
    )
    assert calls == ["1"], "l'érosion n'a pas lu la source unique de la frontière"


# ── 1 bis. Éligibilité et pool : même budget NET ─────────────────────────────────────────


def test_a_squad_whose_descent_eats_its_normal_budget_stays_eligible_for_advance():
    """L'ÉLIGIBILITÉ ne retranche PAS la descente — et elle ne doit pas.

    Le pool la retranche parce qu'il construit un régime déjà choisi ; l'éligibilité, elle,
    PRÉCÈDE le choix. Une escouade dont la descente mange tout son budget normal a un pool normal
    vide mais un Advance parfaitement légal — et l'Advance se déclare APRÈS activation
    (`movement_set_advance_mode_handler`), donc seulement si l'escouade est restée dans
    `move_activation_pool`. Aligner l'éligibilité sur le pool supprimerait ce mouvement pour toute
    la phase : c'est la régression que ce test verrouille, dans le sens masque ⊇ exécutable.
    """
    gs = _gs(level=1, move=int(FLOOR_HEIGHT_INCHES))  # MOVE 3, descente 3 → budget normal net 0
    assert movement_build_valid_destinations_pool(gs, "1", read_only=True) == [], (
        "fixture sans descente bloquante : le test ne prouve rien"
    )
    assert get_eligible_units(gs) == ["1"]

    # …et l'Advance rend bien des destinations : le pool vide ci-dessus n'est pas une impasse.
    gs["units_advanced"] = {"1"}
    gs["advance_rolls"] = {"1": ADVANCE_ROLL + 2}
    assert movement_build_valid_destinations_pool(gs, "1", read_only=True), (
        "l'Advance ne rattrape rien : la fixture ne prouve pas que l'escouade doit rester éligible"
    )


def test_a_descending_squad_that_can_still_move_stays_eligible():
    """Descente PARTIELLE (3 sur 6) : pool normal non vide, escouade éligible."""
    gs = _gs(level=1)
    assert movement_build_valid_destinations_pool(gs, "1", read_only=True)
    assert get_eligible_units(gs) == ["1"]


def test_a_ground_squad_is_unaffected():
    """Zéro régression au sol : sans descente, budget net == budget brut."""
    gs = _gs(level=0)
    assert get_eligible_units(gs) == ["1"]


# ── 2. Niveau de destination du plan rigide ──────────────────────────────────────────────


def test_rigid_plan_lands_on_the_ground_level_off_the_floor():
    """Le plan PORTE le niveau d'arrivée. Hors de l'empreinte du plancher, c'est le sol : sans
    lui, `commit_move` garde le niveau d'origine et la figurine reste marquée à l'étage hors
    empreinte de plancher."""
    gs = _gs(level=1)
    for entry in _plan((START[0] + 4, START[1] + 4), gs):
        assert len(entry) >= 4 and entry[3] == SQUAD_RIGID_MOVE_DESTINATION_LEVEL


def test_rigid_plan_keeps_the_floor_where_it_continues():
    """13.06 : bouger le long d'un plancher est un mouvement horizontal — sans déclaration de
    montée, une figurine partie de l'étage y RESTE là où la case d'arrivée le porte. Le niveau
    est celui de `model_rigid_level_map`, la même carte que lit l'érosion du masque."""
    gs = _gs(level=1)
    for entry in _plan((START[0] + 1, START[1]), gs):
        assert len(entry) >= 4 and entry[3] == 1


def test_masked_cells_of_a_floor_squad_carry_the_level_of_their_cell():
    """La légalité des cellules est évaluée au niveau d'ARRIVÉE : le plan et la validation
    lisent la même carte, étage conservé sur le plancher, sol ailleurs — et le masque offre
    les deux sortes de cellules (sans quoi l'une des deux branches n'est pas éprouvée)."""
    gs = _gs(level=1)
    cell_map = build_squad_move_cell_map(gs, "1", None)
    assert cell_map
    level_map = model_rigid_level_map(gs, gs["models_cache"]["1#0"], False)
    seen_levels = set()
    for (cell, _cost) in cell_map.values():
        for entry in _plan(cell, gs):
            expected = level_map.get((entry[1], entry[2]), SQUAD_RIGID_MOVE_DESTINATION_LEVEL)
            assert entry[3] == expected, (cell, entry, expected)
            seen_levels.add(entry[3])
    assert seen_levels == {SQUAD_RIGID_MOVE_DESTINATION_LEVEL, 1}


def _gs_under_a_higher_floor() -> Dict[str, Any]:
    """`1#0` à l'étage 1, et un plancher de niveau 2 qui RECOUVRE tout l'étage 1.

    La carte « niveau le plus haut » (`floor_level_by_cell`) résout alors chaque cellule à 2 :
    une figurine qui garde SON étage doit lire la carte par niveau, pas celle-là.
    """
    gs = _gs(level=1)
    floor_1 = gs["terrain_areas"][0]["floors"][0]
    gs["terrain_areas"][0]["floors"].append({
        "level": 2, "height_inches": 2 * FLOOR_HEIGHT_INCHES,
        "hexes": [list(h) for h in floor_1["hexes"]],
        "polygon_vertices": [list(v) for v in floor_1["polygon_vertices"]],
    })
    return gs


def test_rigid_plan_keeps_its_own_floor_under_a_higher_one():
    """13.06 ne force jamais la descente : sans déclaration de montée, une figurine à l'étage 1
    y RESTE là où l'étage 1 continue, même sous un plancher 2 — translation nulle comprise.
    La carte « niveau le plus haut » y voit 2 ≠ 1 et l'enverrait au sol."""
    gs = _gs_under_a_higher_floor()
    model = gs["models_cache"]["1#0"]
    assert squad_floor_level_map(gs, model).get(START) == 2, "la fixture ne superpose pas 2 sur 1"
    assert model_rigid_level_map(gs, model, False).get(START) == 1
    for entry in _plan((START[0] + 1, START[1]), gs):
        assert len(entry) >= 4 and entry[3] == 1, entry


# ── 2bis. Paire SUPERPOSÉE sur deux étages (socle rendu REVIVED, pile-in) ───────────────────


def _gs_stacked() -> Dict[str, Any]:
    """`1#0` à l'étage et `1#1` au SOL sur la MÊME case — l'état qui a tué le gate de P1.

    Aplaties toutes deux au sol par le plan rigide, elles entraient en collision sur TOUTE
    destination ; le masque, qui supposait la collision intra-plan invariante par translation,
    les offrait quand même → `ValueError « collision intra-plan »` à l'exécution.
    """
    gs = _gs(level=1)
    gs["models_cache"]["1#1"] = {
        "col": START[0], "row": START[1], "level": 0, "player": 1, "squad_id": "1",
        "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
    }
    gs["squad_models"]["1"] = ["1#0", "1#1"]
    return gs


def test_stacked_pair_masked_cells_are_executable_on_two_floors():
    """Masque ⊆ exécutable sur la paire superposée, ET la paire reste sur deux étages.

    Chaque cellule offerte passe la validation ; la figurine de l'étage y RESTE (niveau 1) et sa
    sœur reste au sol — donc pas de collision.
    """
    gs = _gs_stacked()
    cell_map = build_squad_move_cell_map(gs, "1", None)
    assert cell_map, "masque vide : la paire superposée est clouée au sol"
    floor_cells = floor_hexes_at_level(gs["terrain_areas"], 1)
    for (cell, cost) in cell_map.values():
        plan = _plan(cell, gs)
        by_mid = {entry[0]: entry for entry in plan}
        assert by_mid["1#0"][3] == 1 and by_mid["1#1"][3] == 0, (cell, plan)
        assert (by_mid["1#0"][1], by_mid["1#0"][2]) in floor_cells
        move_type = infer_squad_move_type(gs, "1", cost)
        constraints = resolve_squad_move_constraints("1", gs, move_type, None)
        reason = explain_move_plan_rejection(plan, gs, constraints)
        assert reason is None, (cell, reason)


def test_stacked_pair_off_floor_anchors_are_eroded():
    """Les ancres où l'étage ne continue pas (les deux figurines retomberaient au sol sur la
    même case) sont dans le pool d'ancre brut et ABSENTES du masque : c'est l'érosion par
    `(niveau, case)` qui les retire, miroir du contrôle de la validation."""
    gs = _gs_stacked()
    floor_cells = floor_hexes_at_level(gs["terrain_areas"], 1)
    raw_pool = {
        (int(d[0]), int(d[1]))
        for d in movement_build_valid_destinations_pool(gs, "1", read_only=True)
    }
    off_floor = raw_pool - floor_cells
    assert off_floor, "le pool d'ancre brut n'offre aucune ancre hors plancher : rien à éroder"
    masked = {cell for (cell, _c) in build_squad_move_cell_map(gs, "1", None).values()}
    assert not (off_floor & masked), (
        f"ancres hors plancher offertes au masque (les deux figurines y retombent au sol sur la "
        f"même case) : {sorted(off_floor & masked)}"
    )


def test_stacked_pair_off_floor_anchor_is_refused_by_validation():
    """Contre-épreuve du prédicat miroir : l'ancre hors plancher que l'érosion retire est bien
    celle que la validation refuse pour « collision intra-plan » — même règle des deux côtés."""
    gs = _gs_stacked()
    plan = _plan((START[0] + 3, START[1]), gs)
    levels = {entry[3] for entry in plan}
    assert levels == {SQUAD_RIGID_MOVE_DESTINATION_LEVEL}, plan
    reason = explain_move_plan_rejection(
        plan, gs, {"budget_per_model": None, "require_coherency": False}
    )
    assert reason is not None and "collision intra-plan" in reason, reason


# ── 3. Mesure FLY sous métrique hex ──────────────────────────────────────────────────────


@pytest.mark.parametrize("d_row", [4, 8, 12])
def test_fly_move_is_measured_with_the_cube_distance_it_was_validated_with(d_row):
    """FLY + métrique hex : la mesure doit rendre la distance CUBE, celle que la validation
    borne. Mesurée avec le champ euclidien, un déplacement en RANGÉES (pas de `sqrt(3)` contre
    une borne convertie par `× 1,5`) ressortait « injoignable » alors que le plan était valide.

    MOVE=14 et non 12 : 21.03 retranche 2" à la distance maximale d'une unité qui prend les airs,
    donc le budget effectif vaut bien 12 — celui que ce test veut éprouver jusqu'à `d_row=12`.
    (Avant la conformité 21.03, l'unité IA volait sans payer et 12 suffisait.)
    """
    gs = _gs(level=0, fly=True, move=14)
    dest = (START[0], START[1] + d_row)
    plan = _plan(dest, gs)
    constraints = resolve_squad_move_constraints("1", gs, "normal")
    assert explain_move_plan_rejection(plan, gs, constraints) is None
    distances = move_plan_path_distances(plan, gs, "normal")
    assert distances["1#0"] == pytest.approx(float(d_row))
