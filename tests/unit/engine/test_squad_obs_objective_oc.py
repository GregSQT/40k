"""OC live (14.02 sur positions courantes) et statut secured (14.03) dans l'observation globale.

Les deux sémantiques sont complémentaires à objective_control_{i} (frontière 14.02) :
- objective_my_oc_{i} / objective_enemy_oc_{i} : somme live des OC sur la zone.
- objective_secured_mine_{i} / objective_secured_enemy_{i} : statut secured (14.03).
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.observation_entities import global_bin_index, global_cont_index
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 2, "RNG": 24,
        "WEAPON_RULES": [], "code": "test_weapon", "display_name": "Test Bolter",
    }


def _model(col: int, row: int) -> Dict[str, Any]:
    return {"col": col, "row": row, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 7}


def _unit_cfg(uid: int, player: int, col: int, row: int, n_models: int, oc: int) -> Dict[str, Any]:
    models = [_model(col + 2 * i, row) for i in range(n_models)]
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": n_models, "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": oc, "VALUE": 7 * n_models,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": models,
    }


def _config() -> Dict[str, Any]:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    return {
        "board": {
            "default": {
                "cols": 120, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
                "wall_hexes": [], "objectives": [], "inches_to_subhex": 1,
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
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        # Joueur 1 : 5 figurines OC=2 aux cols 10,12,14,16,18 row=20 → sur l'objectif 0.
        # Joueur 2 : 1 figurine OC=3 au col 30, row=20 → hors objectif 0 par défaut.
        "units": [
            _unit_cfg(1, 1, col=10, row=20, n_models=5, oc=2),
            _unit_cfg(2, 2, col=30, row=20, n_models=1, oc=3),
        ],
    }


# L'objectif 0 couvre exactement les 5 hexes où les figurines du joueur 1 sont posées.
_OBJ_HEXES_0: List[List[int]] = [[10 + 2 * i, 20] for i in range(5)]  # (10,20)..(18,20)
_OBJ_HEXES_1: List[List[int]] = [[30, 20]]  # hex de l'ennemi pour obj 1


@pytest.fixture
def engine():
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(_config()))
    eng.reset()
    # Injection d'objectifs directement dans le game_state (liste neuve → cache invalidé).
    eng.game_state["objectives"] = [
        {"id": 1, "hexes": _OBJ_HEXES_0},
        {"id": 2, "hexes": _OBJ_HEXES_1},
    ]
    eng.game_state["objective_controllers"] = {"1": None, "2": None}
    # secured_objectives déjà {} après reset
    return eng


def _obs(eng: W40KEngine, player: str = "1") -> Dict[str, Any]:
    return eng.obs_builder.build_squad_observation(eng.game_state, player)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_my_oc_live_on_objective(engine):
    """5 figurines OC=2 à moi sur l'objectif 0 → my_oc_0 = 10, enemy_oc_0 = 0."""
    obs = _obs(engine, "1")
    assert obs["global_cont"][global_cont_index("objective_my_oc_0")] == pytest.approx(10.0)
    assert obs["global_cont"][global_cont_index("objective_enemy_oc_0")] == pytest.approx(0.0)


def test_enemy_oc_live_on_objective(engine):
    """1 figurine OC=3 ennemie sur l'objectif 1 → enemy_oc_1 = 3, my_oc_1 = 0."""
    obs = _obs(engine, "1")
    assert obs["global_cont"][global_cont_index("objective_my_oc_1")] == pytest.approx(0.0)
    assert obs["global_cont"][global_cont_index("objective_enemy_oc_1")] == pytest.approx(3.0)


def test_battle_shocked_unit_contributes_zero(engine):
    """Unité battle-shocked → OC nul sur l'objectif (règle 01.07 / 02.02)."""
    # Réintroduction du défaut : retirer le battle_shocked → le test doit rougir.
    engine.game_state["units"][0]["battle_shocked"] = True
    obs = _obs(engine, "1")
    # Avec le fix (battle_shocked ignoré par sum_objective_control_oc_multi) : 0.
    assert obs["global_cont"][global_cont_index("objective_my_oc_0")] == pytest.approx(0.0)


def test_live_oc_changes_boundary_does_not(engine):
    """Pendant la phase de move, après un move sur l'objectif et AVANT la frontière.

    objective_my_oc_i CHANGE (live sur positions courantes), objective_control_i NE CHANGE PAS
    (frontière 14.02, relue d'objective_controllers).
    """
    # État initial : l'objectif n'est contrôlé par personne (frontière).
    engine.game_state["objective_controllers"] = {"1": None, "2": None}
    engine.game_state["phase"] = "move"

    obs_before = _obs(engine, "1")
    ctrl_before = float(obs_before["global_bin"][global_bin_index("objective_control_0")])
    oc_before = float(obs_before["global_cont"][global_cont_index("objective_my_oc_0")])

    # Simule un move : l'ennemi (OC=3) se déplace sur l'objectif 0.
    # On modifie le modèle directement puis on reconstruit les caches.
    from engine.phase_handlers.shared_utils import build_units_cache
    unit2 = engine.game_state["units"][1]
    unit2["col"] = 10
    unit2["row"] = 20
    unit2["models"] = [{"col": 10, "row": 20, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 7,
                        "level": 0, "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5}]
    build_units_cache(engine.game_state)

    obs_after = _obs(engine, "1")
    ctrl_after = float(obs_after["global_bin"][global_bin_index("objective_control_0")])
    oc_after = float(obs_after["global_cont"][global_cont_index("objective_my_oc_0")])

    # La frontière reste inchangée (0 = pas de contrôleur).
    assert ctrl_before == pytest.approx(0.0)
    assert ctrl_after == pytest.approx(0.0), "objective_control_i ne doit pas changer avant la frontière"
    # L'OC live reflète le nouvel état (ennemi OC=3 sur la zone).
    assert oc_before == pytest.approx(10.0), "OC live avant le move"
    assert float(obs_after["global_cont"][global_cont_index("objective_enemy_oc_0")]) == pytest.approx(3.0)


def test_secured_mine(engine):
    """secured_objectives[obj] = moi → objective_secured_mine_i = 1, enemy = 0."""
    engine.game_state["secured_objectives"] = {"1": 1}  # joueur 1 sécurise obj id=1
    obs = _obs(engine, "1")
    assert obs["global_bin"][global_bin_index("objective_secured_mine_0")] == pytest.approx(1.0)
    assert obs["global_bin"][global_bin_index("objective_secured_enemy_0")] == pytest.approx(0.0)


def test_secured_enemy(engine):
    """secured_objectives[obj] = ennemi → objective_secured_enemy_i = 1, mine = 0."""
    engine.game_state["secured_objectives"] = {"1": 2}  # joueur 2 sécurise obj id=1
    obs = _obs(engine, "1")
    assert obs["global_bin"][global_bin_index("objective_secured_mine_0")] == pytest.approx(0.0)
    assert obs["global_bin"][global_bin_index("objective_secured_enemy_0")] == pytest.approx(1.0)
