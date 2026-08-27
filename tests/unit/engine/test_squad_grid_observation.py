"""Rasterisation de la grille egocentrique (ObservationBuilder.build_squad_grid).

Spec : Documentation/Reference/training/move_action_space_spatial_rework.md §7 T1.
Corrige le defaut §4.1 : l'obs squad 108-d ne contenait AUCUN terrain.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import numpy as np
import pytest

from engine.observation_builder import ObservationBuilder
from engine.spatial_grid import (
    GRID_CHANNELS,
    GRID_CH_ALLY,
    GRID_CH_ENEMY,
    GRID_CH_EZ,
    GRID_CH_LEVEL,
    GRID_CH_MOVE_COST,
    GRID_CH_OBJECTIVE,
    GRID_CH_SELF,
    GRID_CH_WALL,
    GRID_SIZE,
    grid_half_extent_subhex,
    hex_to_cell,
)
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "code": "test_weapon", "display_name": "Test Bolter",
    }


def _unit_cfg(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 3, "HP_MAX": 3, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": 1, "VALUE": 100,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
    }


# Ancre p1 en (20,20), ennemi loin (40,20). Mur adjacent, mur lointain hors grille.
ANCHOR_COL, ANCHOR_ROW = 20, 20
NEAR_WALL = (24, 20)
FAR_WALL = (60, 60)


def _config(walls, objectives) -> Dict[str, Any]:
    obs_params = {
        "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET,
    }
    return {
        "board": {
            "default": {
                "cols": 80, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
                "wall_hexes": walls, "objectives": objectives, "inches_to_subhex": 1,
            }
        },
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
        },
        "charge": {"charge_max_distance": 12},
        # Toggles de traversee requis par le pool BFS (valeurs reelles de config/game_config.json).
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [
            _unit_cfg(1, 1, ANCHOR_COL, ANCHOR_ROW),
            _unit_cfg(2, 2, 40, 20),
        ],
    }


@pytest.fixture
def engine():
    walls = [list(NEAR_WALL), list(FAR_WALL)]
    objectives = [{"id": "obj1", "name": "Alpha", "hexes": [[22, 22]]}]
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(_config(walls, objectives)))
    eng.reset()
    return eng


def _grid(engine) -> np.ndarray:
    return engine.obs_builder.build_squad_grid(engine.game_state, "1")


def test_grid_shape_is_channels_first(engine):
    """(C,H,W) = convention CNN sb3."""
    assert _grid(engine).shape == (GRID_CHANNELS, GRID_SIZE, GRID_SIZE)
    assert _grid(engine).dtype == np.float32


def test_half_extent_is_max_advance_budget(engine):
    """MOVE 6 x scale 1 + 6" advance max x 1 = 12 subhex (spec §6.2)."""
    assert grid_half_extent_subhex(engine.game_state, "1") == 12


def test_half_extent_ignores_the_actual_advance_roll(engine):
    """La geometrie ne bouge pas avec le D6 : elle est indexee sur le jet MAXIMAL.

    Sinon l'echelle spatiale respirerait au gre du jet et la semantique apprise par le CNN
    serait incoherente d'un step a l'autre (spec §6.2).
    """
    before = grid_half_extent_subhex(engine.game_state, "1")
    engine.game_state["_squad_advance_rolls"] = {"1": 1}
    engine.game_state.setdefault("advance_rolls", {})["1"] = 1
    engine.game_state.setdefault("units_advanced", set()).add("1")
    assert grid_half_extent_subhex(engine.game_state, "1") == before


def test_active_squad_is_painted_on_self_channel_at_center(engine):
    """V11 §0.32 T-L : l'escouade ACTIVE a son canal a elle, pas celui des allies.

    La grille est centree sur elle : sans ce canal, elle etait indistinguable d'une escouade
    amie voisine alors que c'est SON bloc que chaque cellule jouable translate.
    """
    grid = _grid(engine)
    center = GRID_SIZE // 2
    assert grid[GRID_CH_SELF, center, center] == 1.0
    assert grid[GRID_CH_ALLY, center, center] == 0.0


def test_enemy_is_not_on_ally_channel(engine):
    """L'ennemi (40,20) est a 20 subhex : hors grille (half_extent=12) -> canal ennemi vide."""
    grid = _grid(engine)
    assert grid[GRID_CH_ENEMY].sum() == 0.0


def test_enemy_within_grid_is_painted_on_enemy_channel(engine):
    """Rapproche l'ennemi dans la grille : il apparait sur SON canal, pas sur celui des allies."""
    gs = engine.game_state
    for cache in (gs["units_cache"]["2"], gs["models_cache"][next(iter(gs["squad_models"]["2"]))]):
        cache["col"], cache["row"] = 26, 20
    for unit in gs["units"]:
        if str(unit["id"]) == "2":
            unit["col"], unit["row"] = 26, 20

    grid = _grid(engine)
    cell = hex_to_cell(26, 20, ANCHOR_COL, ANCHOR_ROW, grid_half_extent_subhex(gs, "1"))
    assert cell is not None
    gx, gy = cell
    assert grid[GRID_CH_ENEMY, gy, gx] == 1.0
    assert grid[GRID_CH_ALLY, gy, gx] == 0.0


def test_near_wall_is_painted_on_wall_channel(engine):
    """LE point de la refonte : l'agent percoit enfin les murs (§4.1)."""
    grid = _grid(engine)
    cell = hex_to_cell(*NEAR_WALL, ANCHOR_COL, ANCHOR_ROW, grid_half_extent_subhex(engine.game_state, "1"))
    assert cell is not None, "le mur proche doit tomber dans la grille"
    gx, gy = cell
    assert grid[GRID_CH_WALL, gy, gx] == 1.0


def test_far_wall_is_not_painted(engine):
    """Hors grille -> jamais rabattu sur le bord : sinon l'agent verrait un mur fantome."""
    grid = _grid(engine)
    assert hex_to_cell(*FAR_WALL, ANCHOR_COL, ANCHOR_ROW, grid_half_extent_subhex(engine.game_state, "1")) is None
    assert grid[GRID_CH_WALL].sum() == 1.0  # uniquement NEAR_WALL


def test_objective_is_painted_from_list_hexes(engine):
    """Les objectifs viennent du SCENARIO (w40k_core.py:6376), pas de la config board."""
    engine.game_state["objectives"] = [{"id": "obj1", "hexes": [[22, 22]]}]
    # reset() a deja bati le cache statique (obs Dict construite au reset) : on injecte des
    # objectifs apres coup -> invalider le cache, comme le fait reset() sur un vrai scenario.
    engine.game_state.pop("_grid_static_hex_arrays", None)
    grid = _grid(engine)
    cell = hex_to_cell(22, 22, ANCHOR_COL, ANCHOR_ROW, grid_half_extent_subhex(engine.game_state, "1"))
    assert cell is not None
    gx, gy = cell
    assert grid[GRID_CH_OBJECTIVE, gy, gx] == 1.0


def test_objective_is_painted_from_dict_hexes(engine):
    """L'autre forme d'hex rencontree dans les scenarios : {"col":…, "row":…}."""
    engine.game_state["objectives"] = [{"id": "obj1", "hexes": [{"col": 22, "row": 22}]}]
    engine.game_state.pop("_grid_static_hex_arrays", None)
    grid = _grid(engine)
    cell = hex_to_cell(22, 22, ANCHOR_COL, ANCHOR_ROW, grid_half_extent_subhex(engine.game_state, "1"))
    assert cell is not None
    gx, gy = cell
    assert grid[GRID_CH_OBJECTIVE, gy, gx] == 1.0


def test_ez_channel_is_populated_from_the_engine_cache(engine):
    """Le canal EZ vient du meme ensemble que le pool BFS (source unique de la regle)."""
    gs = engine.game_state
    gs[f"enemy_adjacent_hexes_player_1"] = {(21, 20), (22, 20)}
    grid = _grid(engine)
    half = grid_half_extent_subhex(gs, "1")
    for col, row in ((21, 20), (22, 20)):
        cell = hex_to_cell(col, row, ANCHOR_COL, ANCHOR_ROW, half)
        assert cell is not None
        gx, gy = cell
        assert grid[GRID_CH_EZ, gy, gx] == 1.0


def test_level_channel_is_zero_without_floors(engine):
    """Aucun etage declare -> canal a 0 : le sol EST le niveau 0, pas une donnee manquante."""
    assert _grid(engine)[GRID_CH_LEVEL].sum() == 0.0


def test_static_hex_cache_is_purged_on_reset(engine):
    """`game_state` est le MEME objet d'un reset a l'autre et le scenario change par episode.

    Sans purge, les tableaux memoises de murs/objectifs seraient ceux de l'episode precedent :
    l'agent observerait un terrain qui n'existe plus. Corruption silencieuse -> test dedie.
    """
    _grid(engine)
    first = engine.game_state["_grid_static_hex_arrays"]
    assert first is not None, "le cache doit exister apres un build"
    engine.reset()
    # reset() purge le cache ; l'obs Dict construite au reset le reconstruit aussitot. La
    # garantie anti-terrain-perime n'est donc pas "cache absent" mais "cache reconstruit a
    # neuf" : l'objet memoise ne doit PAS etre celui de l'episode precedent.
    second = engine.game_state.get("_grid_static_hex_arrays")
    assert second is not None, "l'obs du reset doit reconstruire le cache"
    assert second is not first, "cache non purge au reset (memoise l'episode precedent)"


def test_grid_follows_walls_after_scenario_change(engine):
    """Preuve fonctionnelle de la purge : changer les murs change la grille."""
    before = _grid(engine)[GRID_CH_WALL].sum()
    engine.reset()
    engine.game_state["wall_hexes"] = {(21, 20), (22, 20), (23, 20)}
    # Sur un vrai changement de scenario, _reload_scenario ecrit wall_hexes AVANT l'obs du
    # reset ; ici on ecrit apres coup -> invalider le cache statique bati au reset.
    engine.game_state.pop("_grid_static_hex_arrays", None)
    after = _grid(engine)[GRID_CH_WALL].sum()
    assert before == 1.0
    assert after == 3.0


def test_dead_squad_returns_empty_grid(engine):
    """Miroir de build_squad_observation : squad absent -> grille nulle, pas d'exception."""
    grid = engine.obs_builder.build_squad_grid(engine.game_state, "999")
    assert grid.shape == (GRID_CHANNELS, GRID_SIZE, GRID_SIZE)
    assert grid.sum() == 0.0


# ---------------------------------------------------------------------------
# T7 (V11 §9.10) — canal « couvert »
# ---------------------------------------------------------------------------

def test_cover_channel_paints_terrain_areas(engine):
    """Canal couvert = hexes des terrain areas (règle 13.08 « within a terrain area »).

    Contre-épreuve : avant ce canal, la grille ne portait le terrain que comme MUR binaire —
    l'agent ne pouvait pas distinguer une case qui donne le couvert d'un simple bloqueur de
    vue, donc « se déplacer vers le couvert » n'était pas dérivable de l'observation.
    """
    from engine.spatial_grid import GRID_CH_COVER

    gs = engine.game_state
    cover_hex = (22, 20)
    gs["terrain_areas"] = [{
        "id": "area1",
        "obscuring": True,
        "polygon_vertices": [[21, 19], [23, 19], [23, 21], [21, 21]],
        "hexes": [list(cover_hex)],
    }]
    gs.pop("_grid_static_hex_arrays", None)  # les statiques sont memoises

    grid = _grid(engine)
    half_extent = grid_half_extent_subhex(gs, "1")
    cover_cell = hex_to_cell(cover_hex[0], cover_hex[1], ANCHOR_COL, ANCHOR_ROW, half_extent)
    assert cover_cell is not None, "l'hex de couvert doit tomber dans la grille"
    gx, gy = cover_cell
    assert grid[GRID_CH_COVER, gy, gx] == 1.0
    # Le mur voisin, lui, n'est PAS du couvert (aucune terrain area ne le contient).
    wall_cell = hex_to_cell(NEAR_WALL[0], NEAR_WALL[1], ANCHOR_COL, ANCHOR_ROW, half_extent)
    assert wall_cell is not None, "le mur proche doit tomber dans la grille"
    wx, wy = wall_cell
    assert grid[GRID_CH_COVER, wy, wx] == 0.0
    assert grid[GRID_CH_WALL, wy, wx] == 1.0


def test_cover_channel_is_empty_without_terrain_areas(engine):
    """Sans terrain area, le canal couvert reste nul (aucun couvert n'est inventé)."""
    from engine.spatial_grid import GRID_CH_COVER

    assert engine.game_state["terrain_areas"] == []
    assert float(_grid(engine)[GRID_CH_COVER].sum()) == 0.0


def test_cover_channel_is_dilated_by_base_radius():
    """13.08 : le couvert s'obtient dès que le SOCLE chevauche la zone, pas seulement l'ancre.

    Contre-épreuve : même zone, deux escouades — l'une à socle 1 subhex, l'autre à socle 16.
    La grande base doit voir une couronne de cases couvrantes autour de la zone que la petite
    ne voit pas. Sans dilatation, les deux canaux seraient identiques (bug corrigé).
    """
    from engine.spatial_grid import GRID_CH_COVER, cover_dilation_cells

    def _cover_sum(base_size: int) -> float:
        cfg = _config([], [{"id": "obj1", "name": "Alpha", "hexes": [[22, 22]]}])
        for unit in cfg["units"]:
            unit["BASE_SIZE"] = base_size
        with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
             patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
            eng = W40KEngine(config=build_engine_config(cfg))
        eng.reset()
        gs = eng.game_state
        gs["terrain_areas"] = [{
            "id": "area1", "obscuring": True,
            "polygon_vertices": [[21, 19], [23, 19], [23, 21], [21, 21]],
            "hexes": [[22, 20]],
        }]
        gs.pop("_grid_static_hex_arrays", None)
        half_extent = grid_half_extent_subhex(gs, "1")
        dilation = cover_dilation_cells(base_size, half_extent)
        assert (dilation == 0) if base_size == 1 else (dilation > 0), (
            f"fixture : socle {base_size} -> dilatation {dilation} inattendue"
        )
        return float(eng.obs_builder.build_squad_grid(gs, "1")[GRID_CH_COVER].sum())

    small = _cover_sum(1)
    large = _cover_sum(16)
    assert small == 1.0, "socle d'un hex : la seule case de la zone"
    assert large > small, "grande base : la couronne alentour couvre aussi"


# ============================================================================
# V11 §0.32 T-L — canal SELF distinct du canal ALLIE
# ============================================================================


def _engine_with_friendly_neighbour(neighbour_col: int, neighbour_row: int) -> W40KEngine:
    """Meme scenario + une SECONDE escouade du joueur 1, dans la fenetre de grille."""
    cfg = _config(
        [list(NEAR_WALL), list(FAR_WALL)], [{"id": "obj1", "name": "Alpha", "hexes": [[22, 22]]}]
    )
    cfg["units"].append(_unit_cfg(3, 1, neighbour_col, neighbour_row))
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(cfg))
    eng.reset()
    return eng


def test_other_friendly_squad_is_on_ally_channel_not_self():
    """T-L, contre-epreuve : l'escouade amie VOISINE reste sur le canal allie.

    Le correctif ne consiste pas a vider `GRID_CH_ALLY` : il le reserve aux AUTRES escouades du
    joueur actif. Si `self` et `ally` etaient le meme canal (bug), cette assertion et
    `test_active_squad_is_painted_on_self_channel_at_center` ne pourraient pas etre vraies
    en meme temps.
    """
    eng = _engine_with_friendly_neighbour(23, 20)
    gs = eng.game_state
    grid = eng.obs_builder.build_squad_grid(gs, "1")
    cell = hex_to_cell(23, 20, ANCHOR_COL, ANCHOR_ROW, grid_half_extent_subhex(gs, "1"))
    assert cell is not None, "fixture : l'escouade amie doit tomber dans la grille"
    gx, gy = cell
    assert grid[GRID_CH_ALLY, gy, gx] == 1.0, "l'escouade amie voisine est sur le canal allie"
    assert grid[GRID_CH_SELF, gy, gx] == 0.0, "elle n'est PAS sur le canal self"

    center = GRID_SIZE // 2
    assert grid[GRID_CH_SELF, center, center] == 1.0
    assert grid[GRID_CH_ALLY, center, center] == 0.0


def test_self_channel_follows_the_active_squad():
    """Le canal `self` est bien EGOCENTRIQUE : construit pour l'escouade 3, il peint l'escouade 3.

    Verrouille que `self` n'est pas « le premier squad du joueur » fige, mais bien
    `active_squad_id` — sinon le canal mentirait des que l'activation change.

    Hors phase de move : en move, `build_squad_grid` exige la carte de cellules memoisee par le
    masque (T-K), qui n'existe que pour le squad reellement active. C'est le contrat, pas un
    contournement — ici seule la separation self/allie est en cause.
    """
    eng = _engine_with_friendly_neighbour(23, 20)
    gs = eng.game_state
    gs["phase"] = "shoot"
    grid = eng.obs_builder.build_squad_grid(gs, "3")
    center = GRID_SIZE // 2
    assert grid[GRID_CH_SELF, center, center] == 1.0, "l'escouade 3 est au centre de SA grille"

    cell = hex_to_cell(ANCHOR_COL, ANCHOR_ROW, 23, 20, grid_half_extent_subhex(gs, "3"))
    assert cell is not None
    gx, gy = cell
    assert grid[GRID_CH_ALLY, gy, gx] == 1.0, "l'escouade 1 est devenue l'alliee"
    assert grid[GRID_CH_SELF, gy, gx] == 0.0


def test_enemy_is_never_on_the_self_channel(engine):
    """L'ennemi ne fuit pas dans `self` (le tri se fait sur le squad, pas sur le joueur seul)."""
    gs = engine.game_state
    for cache in (gs["units_cache"]["2"], gs["models_cache"][next(iter(gs["squad_models"]["2"]))]):
        cache["col"], cache["row"] = 26, 20
    for unit in gs["units"]:
        if str(unit["id"]) == "2":
            unit["col"], unit["row"] = 26, 20
    grid = _grid(engine)
    cell = hex_to_cell(26, 20, ANCHOR_COL, ANCHOR_ROW, grid_half_extent_subhex(gs, "1"))
    assert cell is not None
    gx, gy = cell
    assert grid[GRID_CH_ENEMY, gy, gx] == 1.0
    assert grid[GRID_CH_SELF, gy, gx] == 0.0


# ============================================================================
# V11 §0.32 T-K — canal COUT GEODESIQUE
# ============================================================================

# Barriere de murs ETANCHE sur la colonne 22 (rows 17..23) : pour rejoindre l'autre cote il faut
# la contourner par (22,16) ou (22,24). MOVE 12 -> budget normal 12, demi-etendue 18 : le detour
# tient dans le budget, donc la cellule cible EST dans le pool — c'est ce qui rend l'oracle
# observable (une cellule hors pool porterait 0 et ne prouverait rien).
BARRIER_HEXES = [[22, r] for r in range(17, 24)]
BEHIND_WALL = (26, 20)
# Symetrique de BEHIND_WALL par rapport a l'ancre : MEME distance a vol d'oiseau, cote degage.
OPEN_SIDE = (14, 20)


def _engine_behind_wall() -> W40KEngine:
    cfg = _config(BARRIER_HEXES, [{"id": "obj1", "name": "Alpha", "hexes": [[22, 22]]}])
    for unit in cfg["units"]:
        unit["MOVE"] = 12
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(cfg))
    eng.reset()
    return eng


def test_move_cost_channel_is_a_geodesic_cost_not_a_straight_line_distance():
    """ORACLE T-K : derriere un mur, la cellule porte le cout de CONTOURNEMENT.

    C'est LE point du canal. Une cellule a 6 subhex a vol d'oiseau mais atteignable seulement par
    un detour doit porter le cout du detour : c'est lui qui arbitre normal vs advance, donc le
    droit de tirer et de charger. Si le canal portait la distance a vol d'oiseau, il mentirait
    exactement la ou l'agent en a besoin.
    """
    from engine.combat_utils import calculate_hex_distance
    from engine.phase_handlers.shared_utils import read_squad_move_cell_map
    from engine.spatial_grid import cell_index

    eng = _engine_behind_wall()
    gs = eng.game_state
    half = grid_half_extent_subhex(gs, "1")
    grid = eng.obs_builder.build_squad_grid(gs, "1")
    cell_map = read_squad_move_cell_map(gs, "1")

    # Oracle COMPARATIF, a distance a vol d'oiseau EGALE : (26,20) est derriere la barriere,
    # (14,20) est son symetrique du cote degage. Comparer deux cellules du meme canal evite toute
    # conversion d'unite — un pas de BFS ne vaut PAS 1 dans l'echelle des couts (metrique hex), si
    # bien qu'un seuil ecrit en « distance hex + 1 » comparerait des grandeurs differentes.
    def _value_and_dest(target: tuple[int, int]):
        cell = hex_to_cell(target[0], target[1], ANCHOR_COL, ANCHOR_ROW, half)
        assert cell is not None, f"fixture : {target} doit tomber dans la grille"
        gx, gy = cell
        assert cell_index(gx, gy) in cell_map, f"fixture : {target} doit etre dans le pool"
        return float(grid[GRID_CH_MOVE_COST, gy, gx]), cell_map[cell_index(gx, gy)][0]

    blocked_value, blocked_dest = _value_and_dest(BEHIND_WALL)
    open_value, open_dest = _value_and_dest(OPEN_SIDE)
    assert blocked_value > 0.0 and open_value > 0.0

    d_blocked = calculate_hex_distance(ANCHOR_COL, ANCHOR_ROW, int(blocked_dest[0]), int(blocked_dest[1]))
    d_open = calculate_hex_distance(ANCHOR_COL, ANCHOR_ROW, int(open_dest[0]), int(open_dest[1]))
    assert d_blocked == d_open, (
        f"fixture : les deux cellules designent {blocked_dest} et {open_dest}, a distances directes "
        f"{d_blocked} != {d_open} — l'oracle ne prouverait rien"
    )
    assert blocked_value > open_value, (
        f"a distance a vol d'oiseau EGALE ({d_blocked}), la cellule derriere le mur porte "
        f"{blocked_value} et celle du cote degage {open_value} : le canal ne porte pas le cout "
        f"geodesique mais une distance directe"
    )


def test_move_cost_channel_is_zero_off_pool_and_on_walls():
    """Hors pool -> 0. Les hexes de la barriere ne sont pas des destinations."""
    eng = _engine_behind_wall()
    gs = eng.game_state
    half = grid_half_extent_subhex(gs, "1")
    grid = eng.obs_builder.build_squad_grid(gs, "1")
    checked = 0
    for col, row in BARRIER_HEXES:
        cell = hex_to_cell(col, row, ANCHOR_COL, ANCHOR_ROW, half)
        assert cell is not None, f"fixture : le mur ({col},{row}) doit tomber dans la grille"
        gx, gy = cell
        if grid[GRID_CH_WALL, gy, gx] != 1.0:
            continue  # cellule partagee : la projection du pool a retenu un hex libre voisin
        checked += 1
        assert grid[GRID_CH_MOVE_COST, gy, gx] == 0.0, f"mur ({col},{row}) porte un cout de move"
    assert checked > 0, "fixture : aucune cellule purement murale a verifier"


def test_move_cost_channel_is_normalised_into_the_observation_box():
    """L'espace d'obs de la grille est Box(0,1) : le canal DOIT y tenir.

    Normalise par la demi-etendue = budget Advance MAXIMAL, borne superieure de tout cout du pool
    quel que soit le regime (normal / advance / fall back).
    """
    eng = _engine_behind_wall()
    channel = eng.obs_builder.build_squad_grid(eng.game_state, "1")[GRID_CH_MOVE_COST]
    assert float(channel.min()) >= 0.0
    assert float(channel.max()) <= 1.0
    assert float(channel.max()) > 0.0, "fixture : le pool doit etre non vide"


def test_move_cost_channel_puts_the_advance_frontier_on_a_constant():
    """LE point de l'encodage : la frontiere normal/advance est a une valeur CONSTANTE.

    La grille passe SEULE dans le CNN (`spatial_extractor` : `self.cnn(observations["grid"])`), le
    vecteur n'est concatene qu'apres l'aplatissement. Un canal `cout / demi-etendue` mettrait la
    frontiere a `MOVE / (MOVE + 6)`, differente pour chaque unite : le CNN devrait la retrouver en
    croisant avec un MOVE qui ne lui parvient jamais. Ici, `cout <= M` <=> `valeur <= seuil`, pour
    toute unite et toute echelle.
    """
    from engine.phase_handlers.shared_utils import get_squad_move_budget, read_squad_move_cell_map
    from engine.spatial_grid import MOVE_COST_ADVANCE_THRESHOLD

    eng = _engine_behind_wall()
    gs = eng.game_state
    grid = eng.obs_builder.build_squad_grid(gs, "1")
    cell_map = read_squad_move_cell_map(gs, "1")
    normal_budget = get_squad_move_budget("1", gs, "normal")

    normals = advances = 0
    for cell_idx, (_dest, cost) in cell_map.items():
        gy, gx = divmod(cell_idx, GRID_SIZE)
        value = float(grid[GRID_CH_MOVE_COST, gy, gx])
        if cost <= normal_budget:
            normals += 1
            assert value <= MOVE_COST_ADVANCE_THRESHOLD + 1e-6, (
                f"cellule NORMALE (cout {cost} <= M={normal_budget}) au-dessus du seuil : {value}"
            )
        else:
            advances += 1
            assert value > MOVE_COST_ADVANCE_THRESHOLD, (
                f"cellule ADVANCE (cout {cost} > M={normal_budget}) sous le seuil : {value}"
            )
    assert normals > 0 and advances > 0, (
        f"fixture sans pouvoir de discrimination : {normals} normales / {advances} advance"
    )


def test_move_cost_channel_is_monotonic_in_the_geodesic_cost():
    """Rien n'est perdu par le recalage : l'encodage reste strictement croissant en cout."""
    from engine.phase_handlers.shared_utils import get_squad_move_budget, read_squad_move_cell_map

    eng = _engine_behind_wall()
    gs = eng.game_state
    grid = eng.obs_builder.build_squad_grid(gs, "1")
    normal_budget = get_squad_move_budget("1", gs, "normal")
    assert normal_budget > 0, "fixture : budget normal nul, le test ne prouverait rien"

    pairs = sorted(
        (float(cost), float(grid[GRID_CH_MOVE_COST, cell_idx // GRID_SIZE, cell_idx % GRID_SIZE]))
        for cell_idx, (_dest, cost) in read_squad_move_cell_map(gs, "1").items()
    )
    # Les couts du BFS ne sont PAS entiers (metrique hex : un pas vaut 2/sqrt(3)) et deux chemins
    # de meme longueur peuvent differer de quelques 1e-15 : en deca de 1e-9 on exige l'egalite,
    # au-dela la croissance stricte.
    for (c1, v1), (c2, v2) in zip(pairs, pairs[1:]):
        if c2 - c1 > 1e-9:
            assert v2 > v1, f"cout {c1}->{c2} mais valeur {v1}->{v2} : encodage non monotone"
        else:
            assert v2 == pytest.approx(v1, abs=1e-6), "meme cout, valeurs differentes"


def test_move_cost_channel_matches_the_mask_cell_map_exactly():
    """Le canal EST la carte du masque — pas un 2e BFS.

    Verrouille l'invariant qui rend T-K gratuit : l'obs relit la carte memoisee par le masque
    (`read_squad_move_cell_map`), donc obs / masque / decoder parlent des memes cellules et des
    memes couts. Un recalcul independant reintroduirait un BFS geodesique par step — exactement
    le poste a 95,6 % du training (§0.22).
    """
    from engine.phase_handlers.shared_utils import get_squad_move_budget, read_squad_move_cell_map
    from engine.spatial_grid import normalize_move_costs

    eng = _engine_behind_wall()
    gs = eng.game_state
    half = grid_half_extent_subhex(gs, "1")
    grid = eng.obs_builder.build_squad_grid(gs, "1")
    cell_map = read_squad_move_cell_map(gs, "1")
    assert cell_map, "fixture : la carte du masque doit etre non vide"
    normal_budget = get_squad_move_budget("1", gs, "normal")

    for cell_idx, (_dest, cost) in cell_map.items():
        gy, gx = divmod(cell_idx, GRID_SIZE)
        expected = float(normalize_move_costs(np.array([cost]), normal_budget, half, engaged=False)[0])
        assert float(grid[GRID_CH_MOVE_COST, gy, gx]) == pytest.approx(expected, abs=1e-6)

    painted = int((grid[GRID_CH_MOVE_COST] > 0.0).sum())
    zero_cost_cells = sum(1 for _d, c in cell_map.values() if c <= 0.0)
    assert painted == len(cell_map) - zero_cost_cells


def test_move_cost_channel_is_empty_outside_the_move_phase():
    """Hors phase de mouvement il n'y a AUCUN pool de deplacement en cours : le canal vaut 0.

    Le canal decrit les destinations de l'activation de move courante. En tir, en charge ou en
    combat, aucune n'existe — peindre le pool d'une phase passee ferait croire a l'agent qu'il
    peut encore bouger.
    """
    eng = _engine_behind_wall()
    gs = eng.game_state
    assert float(eng.obs_builder.build_squad_grid(gs, "1")[GRID_CH_MOVE_COST].sum()) > 0.0
    gs["phase"] = "shoot"
    assert float(eng.obs_builder.build_squad_grid(gs, "1")[GRID_CH_MOVE_COST].sum()) == 0.0


def test_move_cost_channel_uses_the_mask_engagement_predicate(monkeypatch):
    """Verrou de CÂBLAGE : le canal lit `_squad_is_in_enemy_er` — le prédicat du MASQUE.

    Engagée, tout mouvement est un Fall Back (09.05) qui coûte le tir : chaque cellule peinte
    passe au-dessus du seuil. Un prédicat local recalculé autrement pourrait diverger du masque.
    """
    import engine.phase_handlers.shared_utils as su

    from engine.spatial_grid import MOVE_COST_ADVANCE_THRESHOLD

    eng = _engine_behind_wall()
    gs = eng.game_state
    free = eng.obs_builder.build_squad_grid(gs, "1")[GRID_CH_MOVE_COST]
    free_vals = free[free > 0.0]
    assert (free_vals <= MOVE_COST_ADVANCE_THRESHOLD + 1e-6).any(), (
        "fixture : non engagée, des cellules du régime normal doivent exister"
    )
    monkeypatch.setattr(su, "_squad_is_in_enemy_er", lambda _gs, _sid: True)
    engaged = eng.obs_builder.build_squad_grid(gs, "1")[GRID_CH_MOVE_COST]
    engaged_vals = engaged[engaged > 0.0]
    assert engaged_vals.size > 0
    assert (engaged_vals > MOVE_COST_ADVANCE_THRESHOLD).all(), (
        "escouade engagée : toute cellule peinte doit être au-dessus du seuil (Fall Back)"
    )


def test_grid_requires_the_phase_key():
    """`phase` est REQUIS par la grille comme par le vecteur (§0.32 T-J) : une phase absente
    doit lever, pas produire silencieusement un canal de coût vide."""
    from shared.data_validation import ConfigurationError

    eng = _engine_behind_wall()
    gs = eng.game_state
    del gs["phase"]
    with pytest.raises(ConfigurationError, match="phase"):
        eng.obs_builder.build_squad_grid(gs, "1")
