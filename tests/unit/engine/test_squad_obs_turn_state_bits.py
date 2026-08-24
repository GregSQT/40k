"""Les 5 bits d'état de tour de l'observation d'escouade ↔ les clés du game_state.

``moved``, ``shot``, ``fought``, ``advanced``, ``fled`` sont émis par
``observation_builder`` depuis ``units_moved``, ``units_shot``, ``units_fought``,
``units_advanced``, ``units_fled`` — cinq ``.get(..., set())`` consécutifs. Aucun test ne les
allumait : un mapping bit↔clé permuté (``fought`` lisant ``units_shot``, par exemple) sortait
une observation fausse sans qu'une seule assertion bouge, et l'agent apprenait dessus.

Chaque test n'allume QU'UNE clé et exige que le bit correspondant soit le seul à 1 — c'est la
permutation qui est verrouillée, pas seulement la valeur.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.observation_entities import unit_bin_index
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

#: bit d'observation → clé de game_state qui doit l'allumer.
BIT_TO_KEY = {
    "moved": "units_moved",
    "shot": "units_shot",
    "fought": "units_fought",
    "advanced": "units_advanced",
    "fled": "units_fled",
}


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
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


def _config() -> Dict[str, Any]:
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
            _unit_cfg(1, 1, [(30, 20), (32, 20)]),
            _unit_cfg(2, 2, [(80, 20)]),
        ],
    }


@pytest.fixture
def engine() -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(_config()))
    eng.reset()
    return eng


def _bits(engine: W40KEngine) -> Dict[str, float]:
    # Ligne 0 des allies = l'unité ACTIVE (contrat de l'observation entité, V11 §0.30 T-D).
    binv = engine.obs_builder.build_squad_observation(engine.game_state, "1")["allies_bin"][0]
    return {bit: float(binv[unit_bin_index(bit)]) for bit in BIT_TO_KEY}


def test_all_turn_state_bits_off_after_reset(engine: W40KEngine) -> None:
    """obs_bits_reset : sortie de reset(), aucune des 5 clés n'est peuplée → aucun bit allumé."""
    assert _bits(engine) == {bit: 0.0 for bit in BIT_TO_KEY}


@pytest.mark.parametrize("bit,key", sorted(BIT_TO_KEY.items()))
def test_each_key_lights_only_its_own_bit(engine: W40KEngine, bit: str, key: str) -> None:
    """obs_bits_mapping : une clé peuplée allume SON bit, et lui seul.

    Le « lui seul » est ce qui attrape une permutation du mapping : sans lui, deux bits qui
    lisent la même clé restent indétectables.
    """
    engine.game_state[key].add("1")

    bits = _bits(engine)

    assert bits[bit] == 1.0, f"{key} peuplé mais le bit '{bit}' est éteint"
    allumes_a_tort = sorted(b for b, v in bits.items() if v == 1.0 and b != bit)
    assert allumes_a_tort == [], f"{key} allume aussi {allumes_a_tort}"


def test_bits_are_per_squad_not_global(engine: W40KEngine) -> None:
    """obs_bits_scope : peupler la clé pour l'ennemi n'allume pas le bit de l'unité active."""
    engine.game_state["units_fought"].add("2")

    assert _bits(engine)["fought"] == 0.0
