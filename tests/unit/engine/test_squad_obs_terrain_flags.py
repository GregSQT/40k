"""T4 — drapeaux d'escouade liés au terrain : hidden (13.09), gone to ground (13.5),
à couvert (13.08), dans la zone d'engagement ennemie.

Règles lues (Documentation/40k_rules/13 Terrain.pdf, 13-5 gone to ground.jpg) :
- 13.08 Benefit of Cover : l'unité a le couvert si CHAQUE figurine remplit l'une des deux
  conditions ; la première — « INFANTRY/BEASTS/SWARM ET within a terrain area » — ne dépend PAS
  de l'attaquant. Si toutes mes figurines la remplissent, j'ai le couvert contre TOUTE attaque
  à distance : c'est ce que porte le drapeau (condition suffisante exacte, pas une heuristique).
- 13.09 Hidden : hideable + within une zone obscurante + l'unité n'a pas tiré ce tour ni au
  précédent.
- 13.5 Gone to Ground : hidden + within un terrain Solid + « pas entièrement visible pour la
  figurine attaquante ». Le dernier volet dépend du tireur et n'existe pas au niveau escouade ;
  le drapeau porte les deux premiers (« prêt à »).

Contre-épreuves intégrées :
- `test_flags_are_fresh_during_move` : les drapeaux sont recalculés à chaud. Lire
  `unit['hidden']` (rafraîchi seulement au début de la phase de tir) donnerait 0 ici.
- `test_cover_requires_every_model_in_terrain` : une seule figurine hors zone annule le couvert
  (règle « every model in that unit »).
- `test_hidden_lost_after_shooting` : le volet « n'a pas tiré ce tour ou au précédent ».
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from engine.w40k_core import W40KEngine
from engine.observation_builder import ObservationBuilder
from engine.observation_entities import unit_bin_index

BIN_HIDDEN = unit_bin_index("hidden")
BIN_GTG = unit_bin_index("gone_to_ground")
BIN_COVER = unit_bin_index("in_cover")
BIN_IN_EZ = unit_bin_index("engaged")

# Zone de terrain rectangulaire couvrant les colonnes 28..36, lignes 18..22.
_AREA_COLS = range(28, 37)
_AREA_ROWS = range(18, 23)
_AREA_HEXES = [[c, r] for c in _AREA_COLS for r in _AREA_ROWS]
_AREA_POLYGON = [[28, 18], [36, 18], [36, 22], [28, 22]]
# Mur dense (Solid, 13.11) a l'interieur de la zone -> la zone contient un terrain Solid.
_DENSE_WALL = [[28, 18]]


def _terrain_area(obscuring: bool) -> Dict[str, Any]:
    return {
        "id": "area1",
        "obscuring": obscuring,
        "polygon_vertices": _AREA_POLYGON,
        "hexes": _AREA_HEXES,
    }


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "display_name": "Test Bolter",
    }


def _unit_cfg(uid: int, player: int, positions: List[Tuple[int, int]], keywords: List[str]) -> Dict[str, Any]:
    specs = [{"col": c, "row": r, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10} for c, r in positions]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(specs), "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [_weapon_cfg()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [{"keywordId": k} for k in keywords],
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _config(
    my_positions: List[Tuple[int, int]],
    enemy_positions: List[Tuple[int, int]],
    keywords: List[str],
) -> Dict[str, Any]:
    obs_params = {
        "perception_radius": 25, "max_nearby_units": 10, "max_valid_targets": 5,
        "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET, "action_space_size": 1047,
    }
    return {
        "board": {
            "default": {
                "cols": 120, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
                "wall_hexes": [], "inches_to_subhex": 1,
            }
        },
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            "unit_model_cohesion_range": 2, "unit_global_cohesion_range": 9,
            "squad_min_neighbors": 1, "cohesion_distance_mode": "euclidean",
        },
        "charge": {"charge_max_distance": 12},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "scenario_objectives": [],
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [
            _unit_cfg(1, 1, my_positions, keywords),
            _unit_cfg(2, 2, enemy_positions, ["INFANTRY"]),
        ],
    }


def _make_engine(cfg: Dict[str, Any], obscuring: bool = True, dense: bool = True) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=cfg)
    eng.reset()
    gs = eng.game_state
    gs["terrain_areas"] = [_terrain_area(obscuring)]
    gs["dense_wall_hexes"] = _DENSE_WALL if dense else []
    for key in ("_dense_wall_set_cache", "_obs_solid_terrain_areas", "_obscuring_area_sets_cache"):
        gs.pop(key, None)
    return eng


def _flags(engine) -> Dict[str, float]:
    # Ligne 0 des allies = l'unite ACTIVE (contrat de l'observation entite, V11 §0.30 T-D).
    binv = engine.obs_builder.build_squad_observation(engine.game_state, "1")["allies_bin"][0]
    return {
        "hidden": float(binv[BIN_HIDDEN]),
        "gtg": float(binv[BIN_GTG]),
        "cover": float(binv[BIN_COVER]),
        "in_ez": float(binv[BIN_IN_EZ]),
    }


def test_flags_are_fresh_during_move():
    """Escouade INFANTRY entierement dans une zone obscurante Solid : hidden + GtG + couvert.

    Contre-epreuve de fraicheur : on est en phase move, `unit['hidden']` n'a jamais ete calcule
    (il ne l'est qu'au debut de la phase de tir) — le lire au lieu de recalculer donnerait 0.
    """
    eng = _make_engine(_config([(30, 20), (32, 20)], [(80, 20)], ["INFANTRY"]))
    assert not eng.game_state["units"][0].get("hidden"), "fixture : le champ moteur n'est pas encore pose"
    f = _flags(eng)
    assert f["hidden"] == 1.0
    assert f["gtg"] == 1.0
    assert f["cover"] == 1.0
    assert f["in_ez"] == 0.0


def test_cover_requires_every_model_in_terrain():
    """Regle 13.08 « if EVERY model in that unit » : une figurine dehors annule le couvert."""
    eng = _make_engine(_config([(30, 20), (60, 20)], [(80, 20)], ["INFANTRY"]))
    f = _flags(eng)
    assert f["cover"] == 0.0
    assert f["hidden"] == 0.0


def test_cover_requires_hideable_keyword():
    """Regle 13.08 volet (a) : reserve a INFANTRY/BEASTS/SWARM. Un VEHICLE n'y a pas droit."""
    eng = _make_engine(_config([(30, 20), (32, 20)], [(80, 20)], ["VEHICLE"]))
    f = _flags(eng)
    assert f["cover"] == 0.0
    assert f["hidden"] == 0.0


def test_cover_without_obscuring_is_not_hidden():
    """Zone de terrain NON obscurante : couvert oui (13.08), hidden non (13.09 exige obscurant)."""
    eng = _make_engine(_config([(30, 20), (32, 20)], [(80, 20)], ["INFANTRY"]), obscuring=False)
    f = _flags(eng)
    assert f["cover"] == 1.0
    assert f["hidden"] == 0.0
    assert f["gtg"] == 0.0


def test_gone_to_ground_needs_solid_terrain():
    """13.5 : sans terrain Solid (dense) dans la zone, hidden reste vrai mais GtG non."""
    eng = _make_engine(_config([(30, 20), (32, 20)], [(80, 20)], ["INFANTRY"]), dense=False)
    f = _flags(eng)
    assert f["hidden"] == 1.0
    assert f["gtg"] == 0.0


def test_hidden_lost_after_shooting():
    """13.09 : l'unite qui a tire ce tour (ou au precedent) n'est plus hidden — ni GtG."""
    eng = _make_engine(_config([(30, 20), (32, 20)], [(80, 20)], ["INFANTRY"]))
    gs = eng.game_state
    gs.setdefault("units_shot", set()).add("1")
    f = _flags(eng)
    assert f["hidden"] == 0.0
    assert f["gtg"] == 0.0
    assert f["cover"] == 1.0, "le couvert 13.08 ne depend pas du tir"

    gs["units_shot"].discard("1")
    gs.setdefault("units_shot_previous_turn", set()).add("1")
    assert _flags(eng)["hidden"] == 0.0


def test_in_engagement_zone_flag():
    """Drapeau « engagee » : un ennemi au contact conditionne tir (10.04) et charge."""
    eng = _make_engine(_config([(30, 20), (32, 20)], [(33, 20)], ["INFANTRY"]))
    assert _flags(eng)["in_ez"] == 1.0
