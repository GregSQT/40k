"""P3-0 — ce qui rend DISCERNABLES les figurines candidates au retrait de cohérence (03.03).

`COHERENCY_SLOT_i` désigne la LIGNE `i` de `self_models_*`, et `pointer_policy._point` la score
par un produit scalaire nu sur son seul embedding, **sans biais de slot**. Le rôle d'allocation
n'existait qu'AGRÉGÉ PAR TYPE (bloc `*_types_*`) et les PV courants n'étaient plus observés par
figurine depuis §9.4 : deux figurines de valeur très différente sortaient donc des scores égaux,
et le tri de `_squad_models_for_observation` — qui place pourtant les rôles en tête — n'y changeait
rien, aucune tête ne lisant l'index de slot.

MESURÉ le 2026-09-09 (16 épisodes gym du pool `training`, 8 points d'arrêt de cohérence) :
67 paires de figurines de valeur différente sur 67 portaient une ligne `self_models_bin`
IDENTIQUE, et l'observation d'une escouade avec et sans `pending_coherency_removal` armé était
strictement identique (écart 0.0 sur toutes les clés).

Ce fichier verrouille les trois canaux côté MOTEUR. Qu'ils atteignent le réseau est verrouillé
à part, dans `tests/unit/ai/test_self_model_value_encoding.py`.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.observation_entities import (
    global_bin_index,
    self_model_bin_index,
    self_model_cont_index,
)
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

SM_HP_RATIO = self_model_cont_index("hp_ratio")
SM_WOUNDED = self_model_bin_index("wounded")
SM_PRESENT = self_model_bin_index("present")
SM_ROLE_LEADER = self_model_bin_index("role_leader")
SM_ROLE_BITS = [
    self_model_bin_index(f"role_{role}") for role in ObservationBuilder.SQUAD_MODEL_ROLES
]
G_PENDING = global_bin_index("coherency_removal_pending")


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "code": "test_weapon", "display_name": "Test Bolter",
    }


def _unit_cfg(uid: int, player: int, col: int, row: int, specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": sum(int(s["HP_MAX"]) for s in specs), "HP_MAX": 2, "MOVE": 6, "T": 5,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 4,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [_weapon_cfg()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": 2,
        "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _base_model(col: int, row: int) -> Dict[str, Any]:
    return {"col": col, "row": row, "HP_CUR": 2, "HP_MAX": 2, "VALUE": 10}


def _leader_model(col: int, row: int) -> Dict[str, Any]:
    """Personnage attaché (règle 19) : le rôle vient de ses UNIT_RULES, comme en production."""
    return {
        "col": col, "row": row, "HP_CUR": 2, "HP_MAX": 2, "VALUE": 10,
        "UNIT_RULES": [{"ruleId": "leader"}],
    }


def _config(squad_specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
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
            _unit_cfg(1, 1, 10, 20, squad_specs),
            _unit_cfg(2, 2, 60, 20, [_base_model(60, 20), _base_model(62, 20)]),
        ],
    }


def _engine(squad_specs: List[Dict[str, Any]]) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(_config(squad_specs)))
    eng.reset()
    return eng


@pytest.fixture
def engine() -> W40KEngine:
    """Escouade « 1 » : un personnage attaché (leader) et deux figurines de base."""
    return _engine([_leader_model(10, 20), _base_model(12, 20), _base_model(14, 20)])


def _rows(eng: W40KEngine, squad_id: str = "1"):
    obs = eng.obs_builder.build_squad_observation(eng.game_state, squad_id)
    return obs, obs["self_models_cont"], obs["self_models_bin"]


def _present(sm_bin) -> List[int]:
    return [k for k in range(len(sm_bin)) if sm_bin[k][SM_PRESENT] == 1.0]


def test_role_one_hot_marks_the_attached_character(engine):
    """Une seule ligne porte `role_leader` ; les figurines de base n'ont AUCUN bit de rôle."""
    _obs, _cont, sm_bin = _rows(engine)
    present = _present(sm_bin)
    assert len(present) == 3

    leaders = [k for k in present if sm_bin[k][SM_ROLE_LEADER] == 1.0]
    assert leaders == [0], (
        "le personnage attaché doit occuper la ligne 0 (tri de _squad_models_for_observation) "
        "et être le SEUL à porter role_leader"
    )
    for k in present:
        if k in leaders:
            continue
        assert not any(sm_bin[k][b] for b in SM_ROLE_BITS), (
            f"ligne {k} : une figurine de base ne porte aucun bit de rôle"
        )


def test_models_of_different_value_no_longer_share_a_row(engine):
    """Le DÉFAUT : hors position, la ligne du personnage était celle d'une figurine de base.

    C'est la mesure de terrain rejouée sur une fixture — 67 paires sur 67 y étaient identiques.
    """
    _obs, _cont, sm_bin = _rows(engine)
    leader, base = 0, 1
    assert list(sm_bin[leader]) != list(sm_bin[base]), (
        "deux figurines de valeur différente doivent avoir des lignes distinctes hors position "
        "— sinon la tête pointeur COHERENCY leur donne le même score"
    )


def test_wounded_model_carries_its_own_hp(engine):
    """`hp_ratio` et `wounded` sont PAR FIGURINE : entamer l'une ne bouge que sa ligne."""
    gs = engine.game_state
    _obs, cont, sm_bin = _rows(engine)
    for k in _present(sm_bin):
        assert cont[k][SM_HP_RATIO] == pytest.approx(1.0)
        assert sm_bin[k][SM_WOUNDED] == 0.0

    # La figurine de base de la ligne 1 tombe à 1 PV sur 2.
    alive = ObservationBuilder._squad_models_for_observation(
        list(gs["squad_models"]["1"]), gs["models_cache"], (2, 5, 3, 4)
    )
    gs["models_cache"][alive[1]]["HP_CUR"] = 1

    _obs, cont, sm_bin = _rows(engine)
    assert cont[1][SM_HP_RATIO] == pytest.approx(0.5)
    assert sm_bin[1][SM_WOUNDED] == 1.0
    for k in _present(sm_bin):
        if k == 1:
            continue
        assert cont[k][SM_HP_RATIO] == pytest.approx(1.0)
        assert sm_bin[k][SM_WOUNDED] == 0.0


def test_padding_rows_keep_a_null_hp_ratio(engine):
    """Un slot vide reste ENTIÈREMENT nul : `hp_ratio` n'invente pas une figurine intacte."""
    _obs, cont, sm_bin = _rows(engine)
    for k in range(len(sm_bin)):
        if sm_bin[k][SM_PRESENT] == 1.0:
            continue
        assert cont[k][SM_HP_RATIO] == 0.0, (
            f"slot {k} : un slot de padding à hp_ratio=1.0 serait une figurine inventée, "
            "comptée par EntityRunningNorm comme une valeur observée"
        )


def test_coherency_pending_bit_follows_the_observed_squad(engine):
    """Le bit global dit « CETTE escouade doit désigner un retrait », pas « il y en a un »."""
    gs = engine.game_state
    obs, _cont, _bin = _rows(engine)
    assert obs["global_bin"][G_PENDING] == 0.0

    gs["pending_coherency_removal"] = {"squad_id": "1"}
    obs_pending, _c, _b = _rows(engine)
    assert obs_pending["global_bin"][G_PENDING] == 1.0

    # Retrait armé sur une AUTRE escouade : l'observation de « 1 » ne doit pas le porter.
    gs["pending_coherency_removal"] = {"squad_id": "2"}
    obs_other, _c, _b = _rows(engine)
    assert obs_other["global_bin"][G_PENDING] == 0.0
