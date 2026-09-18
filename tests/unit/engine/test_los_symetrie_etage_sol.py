"""06.01 / 13.11 — la LoS est une ligne entre deux points : symétrique, y compris étage ↔ sol.

Règles lues : 06.01 (« draw an imaginary straight line […] from any part of that model to any part
of the model being observed ») ; 13.11 Solid (LoS bloquée par les ouvertures ≤ 3" du sol, tracée
normalement au-dessus) et son illustration « Units A and C are visible to each other » (A au sol
dehors, C à l'étage) : le mur d'une ruine, franchissable pour la figurine à l'étage, l'est dans les
DEUX sens pour la paire.

Défaut verrouillé : `_walls_around_occupied_floor` n'était appelé que pour les figurines TIREUSES.
S à l'étage voyait T au sol par-dessus son mur, mais T ne voyait pas S : le mur bloquait le tracé
T→S. Le wall_set effectif d'une paire = murs du plateau − murs de l'étage de la figurine tireuse
− murs de l'étage de la figurine cible.

Géométrie (120x80, 1 subhex/pouce, socle 1 hex) : ruine R = colonnes 28..34, lignes 15..25, floor
level 1 (height 3") sur les mêmes hexes, mur dense colonne 34 lignes 15..25 ; S (31,20) level 1 ;
T (50,20) au sol. Une AUTRE ruine R2 (colonnes 40..42, lignes 15..25, mur colonne 41) sert de
contre-épreuve : ses murs ne sont l'étage de personne et bloquent S dans les deux sens.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

from engine.w40k_core import W40KEngine
from engine.observation_builder import ObservationBuilder
from tests.unit.engine._config_helpers import build_engine_config, build_game_rules

_R_HEXES = [[c, r] for c in range(28, 35) for r in range(15, 26)]
_R_POLY = [[28, 15], [34, 15], [34, 25], [28, 25]]
_R_WALL = [[34, r] for r in range(15, 26)]

_R2_HEXES = [[c, r] for c in range(40, 43) for r in range(15, 26)]
_R2_POLY = [[40, 15], [42, 15], [42, 25], [40, 25]]
_R2_WALL = [[41, r] for r in range(15, 26)]

_S = (31, 20)
_T = (50, 20)


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


def _ruin(area_id: str, hexes: List[List[int]], poly: List[List[int]]) -> Dict[str, Any]:
    return {
        "id": area_id, "obscuring": False, "polygon_vertices": poly, "hexes": hexes,
        "floors": [{"level": 1, "height_inches": 3.0, "polygon_vertices": poly, "hexes": hexes}],
    }


def make_engine(
    *,
    s_level: int,
    s_positions: Optional[List[Tuple[int, int]]] = None,
    other_ruin: bool = False,
    s_levels: Optional[List[int]] = None,
) -> W40KEngine:
    """Unité 1 = S (joueur 1), unité 2 = T (joueur 2). ``s_levels`` : niveau par figurine de S
    (défaut : ``s_level`` pour toutes)."""
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    s_positions = s_positions or [_S]
    wall = list(_R_WALL) + (list(_R2_WALL) if other_ruin else [])
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
        "units": [_unit_cfg(1, 1, s_positions), _unit_cfg(2, 2, [_T])],
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(cfg))
    eng.reset()
    gs = eng.game_state
    gs["terrain_areas"] = [_ruin("R", _R_HEXES, _R_POLY)]
    if other_ruin:
        gs["terrain_areas"].append(_ruin("R2", _R2_HEXES, _R2_POLY))
    gs["wall_hexes"] = wall
    gs["dense_wall_hexes"] = wall
    levels = s_levels or [s_level] * len(s_positions)
    for mid, lvl in zip(gs["squad_models"]["1"], levels):
        gs["models_cache"][mid]["level"] = lvl
    gs["unit_by_id"]["1"]["level"] = max(levels)
    for key in (
        "_unit_los_pair_cache", "_obscuring_area_sets_cache", "_obscuring_hex_to_area_cache",
        "_wall_set_cache", "_dense_wall_set_cache", "_shooter_los_models_cache",
        "_elevated_ignored_walls_cache",
    ):
        gs.pop(key, None)
    return eng


def can_see(eng: W40KEngine, shooter_id: str, target_id: str) -> bool:
    from engine.phase_handlers.shooting_handlers import compute_unit_los
    gs = eng.game_state
    return bool(compute_unit_los(gs, gs["unit_by_id"][shooter_id], gs["unit_by_id"][target_id])["can_see"])


def model_can_reach(eng: W40KEngine, shooter_id: str, target_id: str) -> bool:
    """Chemin PAR FIGURINE de `declare_attack_model` (shared_utils._attacker_model_can_reach_squad)."""
    from engine.phase_handlers.shared_utils import _attacker_model_can_reach_squad
    gs = eng.game_state
    mid = gs["squad_models"][shooter_id][0]
    m = gs["models_cache"][mid]
    return bool(_attacker_model_can_reach_squad(
        gs, m, int(m["col"]), int(m["row"]), target_id, 48, require_visibility=True,
    ))


def test_fixture_s_a_l_etage_voit_t_au_sol():
    eng = make_engine(s_level=1)
    assert can_see(eng, "1", "2") is True, "fixture : S à l'étage doit voir par-dessus son mur"


def test_t_au_sol_voit_s_a_l_etage_symetrie():
    """13.11 illustration « A and C are visible to each other » : le mur de l'étage de S ne bloque
    pas la ligne T→S. Avant le correctif : True dans un sens, False dans l'autre."""
    eng = make_engine(s_level=1)
    assert can_see(eng, "2", "1") is True, "LoS à sens unique : T ne voit pas S à l'étage"
    assert can_see(eng, "2", "1") == can_see(eng, "1", "2")


def test_chemin_par_figurine_est_symetrique_aussi():
    """`_attacker_model_can_reach_squad` (declare_attack_model) trace la même paire : même
    symétrie, sinon le pool d'unité accepterait une cible que la figurine refuserait de tirer."""
    eng = make_engine(s_level=1)
    assert model_can_reach(eng, "1", "2") is True
    assert model_can_reach(eng, "2", "1") is True, "chemin par figurine : T ne voit pas S à l'étage"


def test_mutation_les_deux_au_sol_le_mur_bloque_dans_les_deux_sens():
    eng = make_engine(s_level=0)
    assert can_see(eng, "1", "2") is False
    assert can_see(eng, "2", "1") is False
    assert model_can_reach(eng, "2", "1") is False


def test_les_murs_d_une_autre_ruine_bloquent_toujours_s():
    """Seuls les murs de l'étage OCCUPÉ par une figurine de la paire sont retirés : R2 (colonne 41)
    n'est l'étage de personne → S et T restent invisibles l'un à l'autre."""
    eng = make_engine(s_level=1, other_ruin=True)
    assert can_see(eng, "1", "2") is False
    assert can_see(eng, "2", "1") is False
