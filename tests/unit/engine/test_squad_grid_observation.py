"""Rasterisation de la grille egocentrique (ObservationBuilder.build_squad_grid).

Spec : Documentation/Implementation/A_faire/move_action_space_spatial_rework.md §7 T1.
Corrige le defaut §4.1 : l'obs squad 108-d ne contenait AUCUN terrain.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import numpy as np
import pytest

from engine.spatial_grid import (
    GRID_CHANNELS,
    GRID_CH_ALLY,
    GRID_CH_ENEMY,
    GRID_CH_EZ,
    GRID_CH_LEVEL,
    GRID_CH_OBJECTIVE,
    GRID_CH_WALL,
    GRID_SIZE,
    grid_half_extent_subhex,
    hex_to_cell,
)
from engine.w40k_core import W40KEngine


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "display_name": "Test Bolter",
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
        "perception_radius": 25, "max_nearby_units": 10, "max_valid_targets": 5,
        "obs_size": 108, "action_space_size": 1047,
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
        eng = W40KEngine(config=_config(walls, objectives))
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


def test_active_squad_is_painted_on_ally_channel_at_center(engine):
    grid = _grid(engine)
    center = GRID_SIZE // 2
    assert grid[GRID_CH_ALLY, center, center] == 1.0


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
