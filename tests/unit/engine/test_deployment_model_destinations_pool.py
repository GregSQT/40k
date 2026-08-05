"""Pool par-figurine de mise en place (`deployment_build_model_destinations_pool`).

Cette fonction décide de TOUTES les cases où le joueur peut poser une figurine — au déploiement
comme à l'arrivée de réserves (20.04), qui emprunte la même chaîne avec une autre aire légale.
Elle n'avait aucun test direct, alors qu'elle porte trois décisions distinctes :

  - l'ÉROSION : l'empreinte translatée tient entièrement dans les cases acceptables (zone moins
    murs, moins occupation) ;
  - le NIVEAU EFFECTIF (§13.06) : étage de vue si l'empreinte tient sur le plancher, sinon sol —
    et l'occupation consultée est celle DE CE NIVEAU ;
  - la CLAIRANCE euclidienne contre les sœurs de l'escouade, plus fine que le blocage par cases.

Les tests ci-dessous vérifient les PROPRIÉTÉS qui définissent ces trois décisions, sur le
scénario à étages du dépôt. Chacun commence par prouver que l'échantillon n'est pas vide : un
pool vide satisferait n'importe quelle propriété universelle (« vert vacant »).
"""
from __future__ import annotations

from typing import Any, Dict, Set, Tuple

import pytest


def _floors_engine():
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x5_debug",
        controlled_agent="ArmageddonAgent",
        scenario_file="config/board/44x60x5/scenario/scenario_floors_test.json",
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    eng.reset(seed=0)
    return eng


def _pool_over_the_upper_floor(game_state: Dict[str, Any], level: int) -> Set[Tuple[int, int]]:
    """Plancher de l'étage + une marge de sol autour : force la branche « candidate en étage ».

    La zone de déploiement du scénario ne recouvre pas forcément un plancher ; sans cette
    construction, le niveau effectif vaudrait 0 partout et la moitié de la fonction ne serait
    jamais exercée. Le test CONSTRUIT donc la situation qu'il observe.
    """
    from engine.terrain_utils import floor_hexes_at_level

    floor = {(int(c), int(r)) for c, r in floor_hexes_at_level(game_state["terrain_areas"], level)}
    pool = set(floor)
    cols, rows = int(game_state["board_cols"]), int(game_state["board_rows"])
    for c, r in sorted(floor)[:400]:
        for dc in range(-3, 4):
            for dr in range(-3, 4):
                cc, rr = c + dc, r + dr
                if 0 <= cc < cols and 0 <= rr < rows:
                    pool.add((cc, rr))
    return pool


@pytest.fixture(scope="module")
def floors_case():
    eng = _floors_engine()
    gs = eng.game_state
    pool = _pool_over_the_upper_floor(gs, 1)
    assert len(pool) > 1000, "pool de test trop petit — les propriétés ne prouveraient rien"
    return eng, gs, pool


def _pool_for(monkeypatch, gs, model_id: str, pool, level: int):
    from engine.phase_handlers import deployment_handlers as dh

    monkeypatch.setattr(dh, "_deploy_pool_set", lambda g, p, o=None: pool)
    return dh.deployment_build_model_destinations_pool(gs, model_id, level=level)["destinations"]


def _first_climbing_model(gs) -> str:
    from engine.game_state import unit_can_occupy_upper_floor

    for squad_id, mids in gs["squad_models"].items():
        unit = next(u for u in gs["units"] if str(u["id"]) == str(squad_id))
        if unit_can_occupy_upper_floor(unit["UNIT_KEYWORDS"]) and mids:
            return mids[0]
    raise AssertionError("aucune figurine capable de monter à l'étage dans le scénario")


def test_upper_level_candidates_exist_and_hold_their_footprint_on_the_floor(
    floors_case, monkeypatch
):
    """§13.06 — une candidate n'est taguée ÉTAGE que si son empreinte tient sur le plancher."""
    from engine.terrain_utils import (
        floor_hexes_at_level, floor_polys_at_level, footprint_within_floor,
    )

    _eng, gs, pool = floors_case
    model_id = _first_climbing_model(gs)
    model = gs["models_cache"][model_id]
    dests = _pool_for(monkeypatch, gs, model_id, pool, level=1)

    upper = [(c, r) for c, r, lv in dests if lv == 1]
    assert upper, "aucune candidate en étage — la branche §13.06 n'est pas exercée"
    assert len(upper) < len(dests), "toutes les candidates en étage : le sol n'est pas exercé"

    floor_hexes = floor_hexes_at_level(gs["terrain_areas"], 1)
    shape, base = model["BASE_SHAPE"], model["BASE_SIZE"]
    polys = floor_polys_at_level(gs["terrain_areas"], 1) if shape == "round" else None
    for c, r in upper:
        assert footprint_within_floor(
            c, r, shape, base, int(model.get("orientation", 0)), floor_hexes, polys
        ), f"candidate ({c},{r}) taguée étage sans que son empreinte tienne sur le plancher"


def test_every_destination_level_is_ground_or_the_requested_view(floors_case, monkeypatch):
    """Le niveau rendu est 0 ou le niveau DEMANDÉ — jamais un niveau inventé."""
    _eng, gs, pool = floors_case
    model_id = _first_climbing_model(gs)
    for level in (0, 1, 2):
        dests = _pool_for(monkeypatch, gs, model_id, pool, level=level)
        assert dests, f"pool vide au niveau {level} — rien à vérifier"
        assert {lv for _c, _r, lv in dests} <= {0, level}


def test_destinations_never_overlap_a_squadmate_base(floors_case, monkeypatch):
    """La clairance euclidienne contre les sœurs : aucune candidate ne chevauche leur socle.

    C'est la propriété que la BORNE DE PORTÉE doit préserver — elle évite l'appel géométrique
    hors d'atteinte, elle ne doit rien laisser passer à l'intérieur.
    """
    from engine.hex_utils import Socle, footprints_overlap
    from engine.phase_handlers.deployment_handlers import _model_footprint

    _eng, gs, pool = floors_case
    # Escouade MULTI-figurines et posée : sans sœur sur la table, la clairance intra-escouade
    # n'existe pas et le test ne prouverait rien (il se contentait de sauter).
    squad_id = next(
        (
            sid for sid, mids in gs["squad_models"].items()
            if len([m for m in mids
                    if (int(gs["models_cache"][m]["col"]), int(gs["models_cache"][m]["row"]))
                    != (-1, -1)]) >= 2
        ),
        None,
    )
    assert squad_id is not None, "aucune escouade multi-figurines posée dans le scénario"
    model_id = gs["squad_models"][squad_id][0]
    model = gs["models_cache"][model_id]
    dests = _pool_for(monkeypatch, gs, model_id, pool, level=0)
    assert dests, "pool vide — test sans portée"

    siblings = []
    for mid in gs["squad_models"][squad_id]:
        if str(mid) == str(model_id):
            continue
        sib = gs["models_cache"][mid]
        sc, sr = int(sib["col"]), int(sib["row"])
        if (sc, sr) == (-1, -1):
            continue
        fp = None if sib["BASE_SHAPE"] == "round" else _model_footprint(gs, sib, sc, sr)
        siblings.append(
            Socle(shape=sib["BASE_SHAPE"], base_size=sib["BASE_SIZE"], col=sc, row=sr, fp=fp)
        )
    assert siblings, "aucune sœur posée — la clairance intra-escouade n'est pas exercée"

    shape, base = model["BASE_SHAPE"], model["BASE_SIZE"]
    for c, r, _lv in dests:
        cand = Socle(shape=shape, base_size=base, col=c, row=r, fp=None if shape == "round" else
                     _model_footprint(gs, model, c, r))
        for sib in siblings:
            assert not footprints_overlap(cand, sib), (
                f"candidate ({c},{r}) chevauche le socle d'une sœur en ({sib.col},{sib.row})"
            )


def test_destinations_are_confined_to_the_pool_and_avoid_walls(floors_case, monkeypatch):
    """L'érosion : l'empreinte entière tient dans le pool, aucune case sur un mur."""
    from engine.phase_handlers.deployment_handlers import _model_footprint

    _eng, gs, pool = floors_case
    model_id = _first_climbing_model(gs)
    model = gs["models_cache"][model_id]
    walls = {(int(c), int(r)) for c, r in gs.get("wall_hexes", set())}
    dests = _pool_for(monkeypatch, gs, model_id, pool, level=1)
    assert dests, "pool vide — test sans portée"
    for c, r, _lv in dests:
        for cell in _model_footprint(gs, model, c, r):
            cell = (int(cell[0]), int(cell[1]))
            assert cell in pool, f"empreinte de ({c},{r}) débordant du pool en {cell}"
            assert cell not in walls, f"empreinte de ({c},{r}) sur un mur en {cell}"


def test_erosion_primitive_handles_offsets_that_exclude_the_anchor():
    """L'érosion ne suppose PAS que l'objet couvre son ancre.

    Les deux appelants d'aujourd'hui (empreinte d'une figurine, empreinte d'un bloc) contiennent
    tous deux l'hex de l'ancre, ce qui masque la question : une ancre située hors de l'ensemble
    acceptable reste valide si l'OBJET, lui, y retombe entièrement. Écarter d'avance les ancres
    hors de la boîte de `allowed` rendait alors l'ensemble vide au lieu de la bonne réponse.
    Oracle naïf en toutes lettres, comme pour l'érosion du bloc.
    """
    from engine.hex_utils import offset_to_cube
    from engine.phase_handlers.deployment_handlers import erode_pool_by_block_offsets

    pool = {(c, r) for c in range(0, 12) for r in range(0, 12)}
    allowed = {(c, r) for c in range(6, 12) for r in range(0, 12)}
    # Objet décalé de +4 colonnes : son ancre est à gauche de `allowed`, l'objet à droite.
    ref = offset_to_cube(0, 0)
    offsets = [
        tuple(a - b for a, b in zip(offset_to_cube(4 + dc, 0), ref)) for dc in range(0, 2)
    ]
    assert (0, 0, 0) not in offsets, "ce test perd son objet si l'origine est dans les offsets"

    allowed_cube = {offset_to_cube(c, r) for c, r in allowed}
    naive = set()
    for c, r in pool:
        bx, by, bz = offset_to_cube(c, r)
        if all((bx + ox, by + oy, bz + oz) in allowed_cube for ox, oy, oz in offsets):
            naive.add((c, r))
    assert naive, "VERT VACANT : aucune ancre retenue, l'égalité ne prouverait rien"
    assert erode_pool_by_block_offsets(pool, offsets, allowed=allowed) == naive
