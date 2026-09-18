"""13.10 — l'exclusion des obscuring areas se calcule PAR FIGURINE tireuse, jamais par escouade.

Règle lue (Documentation/40k_rules/13 Terrain.pdf, 13.10) : « If every line of sight drawn between
two models crosses one or more obscuring terrain areas (excluding obscuring terrain areas that one
or both of those MODELS are within), those two models are not visible to each other. » L'exclusion
est une propriété de la PAIRE (figurine tireuse, figurine cible) : une figurine hors de l'area X ne
voit pas à travers X, même si une camarade de son escouade est dedans.

Défaut verrouillé : `_compute_unit_los_uncached` / `_unit_can_see_any` excluaient les areas de
l'UNION des empreintes de l'escouade (`shooter_hexes_all`), puis partageaient cette exclusion entre
toutes les figurines tireuses dans `_target_model_visible_cells`. Escouade {A dans X, B hors X},
cible T hors X derrière un mur pour A : A seule → False (mur), B seule → False (X bloque), mais
{A, B} → True — B « empruntait » l'exclusion de A.

Géométrie (plateau 120x80, 1 subhex par pouce, socle 1 hex) :
- area obscurante X = colonnes 28..42, lignes 15..30 ;
- mur dense en colonne 40, lignes 18..22 (dans X) ;
- A (30,20) DANS X, B (10,40) HORS X, cible T (50,20) hors X.
La ligne A→T (ligne 20) frappe le mur ; la ligne B→T traverse X (colonnes 28..42, lignes ~24..31)
sans toucher le mur. La contre-épreuve retire le mur : A voit alors T à travers sa propre area.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

from engine.w40k_core import W40KEngine
from engine.observation_builder import ObservationBuilder
from tests.unit.engine._config_helpers import build_engine_config, build_game_rules

_AREA_HEXES = [[c, r] for c in range(28, 43) for r in range(15, 31)]
_AREA_POLYGON = [[28, 15], [42, 15], [42, 30], [28, 30]]
_WALL = [[40, r] for r in range(18, 23)]

_A = (30, 20)   # dans X
_B = (10, 40)   # hors X
_T = (50, 20)   # cible, hors X


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 48,
        "WEAPON_RULES": [], "code": "test_weapon", "display_name": "Test Bolter", "shot": 0,
    }


def _unit_cfg(uid: int, player: int, positions: List[Tuple[int, int]]) -> Dict[str, Any]:
    specs = [{"col": c, "row": r, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10} for c, r in positions]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(specs), "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [_weapon_cfg()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _make_engine(shooter_positions: List[Tuple[int, int]], wall: List[List[int]]) -> W40KEngine:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    cfg = {
        "board": {"default": {
            "cols": 120, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
            "wall_hexes": wall, "inches_to_subhex": 1,
        }},
        "game_rules": build_game_rules(
            engagement_zone=1, engagement_zone_vertical=5, max_base_size_hex=35,
            unit_model_cohesion_range=2, unit_global_cohesion_range=40,
            squad_min_neighbors=1, cohesion_distance_mode="euclidean",
        ),
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
        "units": [_unit_cfg(1, 1, shooter_positions), _unit_cfg(2, 2, [_T])],
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(cfg))
    eng.reset()
    gs = eng.game_state
    gs["terrain_areas"] = [{
        "id": "X", "obscuring": True, "polygon_vertices": _AREA_POLYGON, "hexes": _AREA_HEXES,
    }]
    gs["wall_hexes"] = wall
    gs["dense_wall_hexes"] = wall
    for key in (
        "_unit_los_pair_cache", "_obscuring_area_sets_cache", "_obscuring_hex_to_area_cache",
        "_wall_set_cache", "_dense_wall_set_cache", "_shooter_los_models_cache",
        "_elevated_ignored_walls_cache",
    ):
        gs.pop(key, None)
    return eng


def _can_see(eng: W40KEngine) -> bool:
    from engine.phase_handlers.shooting_handlers import compute_unit_los
    gs = eng.game_state
    return bool(compute_unit_los(gs, gs["unit_by_id"]["1"], gs["unit_by_id"]["2"])["can_see"])


def _can_see_any(eng: W40KEngine) -> bool:
    """Chemin d'ÉLIGIBILITÉ (pool de tir), jumeau allégé de compute_unit_los."""
    from engine.phase_handlers.shooting_handlers import _unit_can_see_any
    gs = eng.game_state
    return bool(_unit_can_see_any(gs, gs["unit_by_id"]["1"], gs["unit_by_id"]["2"]))


def test_a_seule_est_bloquee_par_le_mur():
    eng = _make_engine([_A], _WALL)
    assert _can_see(eng) is False
    assert _can_see_any(eng) is False


def test_b_seule_est_bloquee_par_l_area_x():
    eng = _make_engine([_B], _WALL)
    assert _can_see(eng) is False
    assert _can_see_any(eng) is False


def test_escouade_a_b_ne_voit_pas_plus_que_ses_figurines():
    """13.10 : l'exclusion d'une paire ne dépend que de SES deux figurines. Aucune des deux ne
    voit T → l'escouade ne voit pas T. Avant le correctif, B héritait de l'exclusion de A."""
    eng = _make_engine([_A, _B], _WALL)
    assert _can_see(eng) is False, "B voit à travers X grâce à A : exclusion calculée par escouade"
    assert _can_see_any(eng) is False, "éligibilité : même défaut sur _unit_can_see_any"


def test_contre_epreuve_sans_mur_l_escouade_voit_par_a():
    """Mur retiré : A, DANS X, voit T à travers sa propre area (exclusion légitime de 13.10).
    Prouve que la géométrie n'est pas bloquée pour une autre raison."""
    eng = _make_engine([_A, _B], [])
    assert _can_see(eng) is True
    assert _can_see_any(eng) is True
    # Et B seule reste bloquée par X même sans mur : c'est bien l'area qui la bloque.
    assert _can_see(_make_engine([_B], [])) is False
