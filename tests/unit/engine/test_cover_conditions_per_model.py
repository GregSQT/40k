"""Verrou : `compute_unit_los` expose la condition 13.08 remplie par CHAQUE figurine.

Le couvert 13.08 est un booléen d'UNITÉ (« if EVERY model in that unit meets one or more of the
following conditions »), et c'est lui — et lui seul — qui donne le -1 BS. Mais répliquer ce
booléen sur chaque figurine à l'affichage produit une lecture inversée : une escouade dont UNE
figurine est découverte perd le couvert, donc AUCUNE des figurines réellement plantées dans le
terrain n'affiche de badge.

`cover_conditions` porte le diagnostic par figurine qui manquait : "a" (dans un terrain area),
"b" (pas entièrement visible), "" (découverte — c'est elle qui annule le couvert de l'escouade).

Ces tests verrouillent les deux propriétés qui doivent tenir ENSEMBLE :
  - `cover` (résolution, -1 BS) reste tout-ou-rien et INCHANGÉ ;
  - `cover_conditions` distingue les figurines une à une.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.shooting_handlers import compute_unit_los
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

# Zone de terrain rectangulaire, colonnes 28..36 / lignes 18..22 (même géométrie que
# test_squad_obs_enemy_cover, pour que les deux fichiers parlent du même terrain).
_AREA_HEXES = [[c, r] for c in range(28, 37) for r in range(18, 23)]
_AREA_POLYGON = [[28, 18], [36, 18], [36, 22], [28, 22]]


def _terrain_area() -> Dict[str, Any]:
    """Zone NON obscurante : elle donne le couvert (13.08) sans bloquer la vue.

    Indispensable au scénario : avec une zone obscurante, les figurines dedans deviendraient
    partiellement visibles et rempliraient la condition (b), ce qui masquerait le fait qu'on
    teste bien la condition (a).
    """
    return {
        "id": "area1", "obscuring": False,
        "polygon_vertices": _AREA_POLYGON, "hexes": _AREA_HEXES,
    }


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 48,
        "WEAPON_RULES": [], "code": "test_weapon", "display_name": "Test Bolter",
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


def _config(mine: List[Tuple[int, int]], enemy: List[Tuple[int, int]]) -> Dict[str, Any]:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    return {
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "board": {"default": {
            "cols": 120, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
            "wall_hexes": [], "inches_to_subhex": 1,
        }},
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
        "units": [_unit_cfg(1, 1, mine), _unit_cfg(2, 2, enemy)],
    }


def _make_engine(cfg: Dict[str, Any], *, area: bool) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(cfg))
    eng.reset()
    gs = eng.game_state
    gs["terrain_areas"] = [_terrain_area()] if area else []
    gs["dense_wall_hexes"] = []
    for key in ("_dense_wall_set_cache", "_obs_solid_terrain_areas",
                "_obscuring_area_sets_cache", "_unit_los_pair_cache"):
        gs.pop(key, None)
    return eng


def _los(eng: W40KEngine) -> Dict[str, Any]:
    """LoS de l'unité 1 (tireur) vers l'unité 2 (cible), non mise en cache d'un test à l'autre."""
    gs = eng.game_state
    return compute_unit_los(gs, gs["unit_by_id"]["1"], gs["unit_by_id"]["2"])


def test_squad_fully_inside_terrain_has_cover_and_every_model_reports_condition_a():
    """Référence : les 5 figurines dans le terrain → couvert d'unité, et 5 conditions "a"."""
    enemy = [(32, 20), (33, 20), (34, 20), (35, 20), (36, 20)]
    los = _los(_make_engine(_config([(10, 20)], enemy), area=True))

    assert los["can_see"] is True, "cible non vue : géométrie du test cassée"
    assert los["cover"] is True, "13.08 : escouade entièrement en terrain doit avoir le couvert"
    assert los["cover_conditions"] == ["a"] * 5, (
        f"chaque figurine doit remplir (a), obtenu {los['cover_conditions']}"
    )


def test_one_exposed_model_removes_unit_cover_but_the_others_still_report_condition_a():
    """Le cas qui rendait l'affichage trompeur.

    4 figurines dans le terrain, 1 à découvert. 13.08 exige que CHAQUE figurine remplisse une
    condition → l'unité perd le couvert (pas de -1 BS). Mais les 4 figurines en terrain
    remplissent bien (a) individuellement : c'est ce que `cover_conditions` doit dire, et c'est
    ce qui permet à l'affichage de ne plus prétendre qu'elles sont toutes découvertes.

    La figurine découverte est placée AU MILIEU de l'escouade, et non en dernier : le booléen
    d'unité seul autoriserait à sortir de la boucle dès qu'elle est rencontrée, ce qui
    tronquerait la liste. Avec elle en dernière position, une telle sortie anticipée rendrait
    exactement la même liste et ce test ne verrouillerait rien.
    """
    enemy = [(33, 20), (34, 20), (44, 20), (35, 20), (36, 20)]
    los = _los(_make_engine(_config([(10, 20)], enemy), area=True))

    assert los["can_see"] is True, "cible non vue : géométrie du test cassée"
    assert los["cover"] is False, (
        "13.08 : une figurine découverte doit annuler le couvert de TOUTE l'escouade"
    )
    conditions = los["cover_conditions"]
    assert len(conditions) == 5, (
        f"une condition par figurine attendue (liste tronquée ?), obtenu {conditions}"
    )
    assert conditions == ["a", "a", "", "a", "a"], (
        "les 4 figurines en terrain doivent remplir (a) et la découverte aucune, "
        f"obtenu {conditions}"
    )


def test_squad_in_the_open_has_no_cover_and_no_model_reports_a_condition():
    """Aucun terrain : pas de couvert d'unité, et aucune figurine ne remplit de condition.

    Verrouille que `cover_conditions` ne fabrique pas de badge là où il n'y a rien à signaler.
    """
    enemy = [(40, 20), (41, 20), (42, 20)]
    los = _los(_make_engine(_config([(10, 20)], enemy), area=False))

    assert los["can_see"] is True, "cible non vue : géométrie du test cassée"
    assert los["cover"] is False, "couvert accordé sans aucun terrain"
    assert los["cover_conditions"] == ["", "", ""], (
        f"aucune condition ne doit être remplie à découvert, obtenu {los['cover_conditions']}"
    )
