"""T6 — bloc ennemi : figurine la plus proche, distance de portée, VALUE, MOVE + défensif.

Refonte V11 (Documentation/Archives/chantiers/V11_audit_observation.md §9.2, §10 bloc D) :
- position mesurée depuis la figurine ennemie la PLUS PROCHE (l'ancre d'une escouade étalée peut
  être à l'opposé de la figurine qui menace) ;
- ➕ distance bord-à-bord escouade↔escouade, avec la MÊME mesure que le gate de portée du moteur
  (`_ranged_squad_edge_distance`), donc comparable aux portées d'armes ;
- ➕ VALUE vivante de la cible (somme par figurine) ;
- ➕ MOVE (anticiper sa menace après son mouvement) et profil défensif (HP_MAX/T/save/invul).

Contre-épreuve intégrée : `test_position_follows_nearest_model_not_anchor` place l'ancre ennemie
LOIN et une de ses figurines TOUT PRÈS — l'ancien encodage (ancre) donnait une direction et une
distance fausses de plusieurs dizaines de subhex.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.observation_entities import UNIT_CONT_SIZE, unit_bin_index, unit_cont_index
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

# Features d'unite lues par NOM (schema unifie ami/ennemi, engine/observation_entities.py)
E_SIZE = unit_cont_index("alive_models")
E_HP = unit_cont_index("hp_total")
E_VALUE = unit_cont_index("value_alive")
E_COL = unit_cont_index("col_rel")
E_ROW = unit_cont_index("row_rel")
E_DIST = unit_cont_index("edge_distance")
E_OC = unit_cont_index("oc_total")
E_MOVE = unit_cont_index("move")
E_HP_MAX = unit_cont_index("hp_max")
E_T = unit_cont_index("toughness")
E_SAVE = unit_cont_index("armor_save")
E_INVUL = unit_cont_index("invul_save")


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "code": "test_weapon", "display_name": "Test Bolter",
    }


def _unit_cfg(
    uid: int, player: int, positions: List[Tuple[int, int]], *,
    value: int = 10, oc: int = 2, move: int = 6, t: int = 4,
    save: int = 4, invul: int = 0, hp_max: int = 1,
) -> Dict[str, Any]:
    specs = [{"col": c, "row": r, "HP_CUR": hp_max, "HP_MAX": hp_max, "VALUE": value} for c, r in positions]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": hp_max * len(specs), "HP_MAX": hp_max, "MOVE": move, "T": t,
        "ARMOR_SAVE": save, "INVUL_SAVE": invul,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [_weapon_cfg()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "LD": 7, "OC": oc, "VALUE": value * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _config(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    obs_params = {
        "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET,
    }
    return {
        "board": {
            "default": {
                "cols": 200, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
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
        "units": units,
    }


def _make_engine(units: List[Dict[str, Any]]) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(_config(units)))
    eng.reset()
    return eng


def _slot(engine, slot_i: int = 0):
    return engine.obs_builder.build_squad_observation(engine.game_state, "1")["enemies_cont"][slot_i]


def test_position_follows_nearest_model_not_anchor():
    """L'ancre ennemie est loin, une de ses figurines est proche : c'est ELLE qui est décrite."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)]),
        # Ancre en (100,20) ; la 3e figurine est en (26,20), juste devant moi.
        _unit_cfg(2, 2, [(100, 20), (102, 20), (26, 20)]),
    ])
    slot = _slot(eng)
    # Position relative au centroide de mon escouade (20,20), dans la projection `_hex_center`
    # (V11 §0.32 T-I : une SEULE geometrie dans l'observation) -> la fig proche est a +6 colonnes,
    # de meme parite, donc a +6 x 1.5 en x et 0 en y.
    from engine.hex_utils import _hex_center

    ax, ay = _hex_center(20, 20)
    ex, ey = _hex_center(26, 20)
    assert slot[E_COL] == pytest.approx(ex - ax)
    assert slot[E_ROW] == pytest.approx(ey - ay)
    # Contre-epreuve : l'ancre (100,20) aurait donne +80 colonnes, soit +120 en projection.
    assert slot[E_COL] != pytest.approx(_hex_center(100, 20)[0] - ax)


def test_distance_matches_engine_range_gate():
    """La distance exposée est celle du gate de portée du moteur (bord à bord, socles)."""
    from engine.phase_handlers.shared_utils import _ranged_squad_edge_distance

    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)]),
        _unit_cfg(2, 2, [(40, 20), (60, 20)]),
    ])
    expected = _ranged_squad_edge_distance(eng.game_state, "1", "2")
    assert _slot(eng)[E_DIST] == pytest.approx(float(expected))


def test_enemy_raw_profile_is_exposed():
    """Taille, PV, VALUE, OC, MOVE et profil défensif de la cible sortent en valeurs brutes."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)]),
        _unit_cfg(2, 2, [(60, 20), (62, 20)], value=13, oc=3, move=10, t=9,
                  save=2, invul=5, hp_max=4),
    ])
    slot = _slot(eng)
    inches_to_subhex = int(eng.game_state["inches_to_subhex"])
    assert slot[E_SIZE] == pytest.approx(2.0)
    assert slot[E_HP] == pytest.approx(8.0)          # 2 figurines x 4 PV
    assert slot[E_VALUE] == pytest.approx(26.0)      # 2 figurines x 13 pts
    assert slot[E_OC] == pytest.approx(6.0)          # 2 figurines x OC 3
    assert slot[E_MOVE] == pytest.approx(10.0 * inches_to_subhex)
    assert slot[E_HP_MAX] == pytest.approx(4.0)
    assert slot[E_T] == pytest.approx(9.0)
    assert slot[E_SAVE] == pytest.approx(2.0)
    assert slot[E_INVUL] == pytest.approx(5.0)


def test_enemy_value_drops_with_losses():
    """VALUE vivante = somme PAR FIGURINE : elle décroît quand une figurine meurt."""
    from engine.phase_handlers.shared_utils import destroy_model

    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)]),
        _unit_cfg(2, 2, [(60, 20), (62, 20)], value=13),
    ])
    assert _slot(eng)[E_VALUE] == pytest.approx(26.0)
    destroy_model(eng.game_state, "2#1", reason="combat")
    assert _slot(eng)[E_VALUE] == pytest.approx(13.0)


def test_empty_slot_is_zero_padded():
    """Un slot sans ennemi vivant reste à zéro (le bit `present` porte seul l'information)."""
    eng = _make_engine([_unit_cfg(1, 1, [(20, 20)]), _unit_cfg(2, 2, [(60, 20)])])
    assert list(_slot(eng, 1)) == [0.0] * UNIT_CONT_SIZE
    binv = eng.obs_builder.build_squad_observation(eng.game_state, "1")["enemies_bin"][1]
    assert float(binv[unit_bin_index("present")]) == 0.0
