"""T5 — contacts par figurine : bord-à-bord brut → zone d'engagement (règle 03.04).

Refonte V11 (Documentation/Implementation/V11_audit_observation.md §9.2) : les deux drapeaux
par figurine (« au contact d'un ennemi », « au contact d'un allié lui-même au contact ») étaient
calculés par `calculate_hex_distance(...) == BASE_TO_BASE_SUBHEX`, c'est-à-dire une distance
d'ANCRE à ANCRE égale à 1 subhex. Ils passent à la primitive d'engagement du moteur
(`unit_entries_within_engagement_zone` sur des entrées synthétiques par figurine, exactement
comme `get_fighting_models`), qui mesure BORD À BORD et tient compte de la taille des socles.

Contre-épreuve intégrée : `test_large_bases_in_ez_are_seen` place deux figurines à grande base
dont les ANCRES sont à 2 subhex — donc invisibles pour l'ancien test `== 1` — mais dont les
socles se touchent : la règle 03.04 les déclare engagées, et le pool de combat du moteur
(`get_fighting_models`) les compte. L'ancien code sortait 0 là où le moteur disait « combat ».
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.shared_utils import get_fighting_models
from engine.w40k_core import W40KEngine

# Le bloc figurine ne porte plus que l'individuel : les 3 drapeaux d'engagement (le profil et le
# role sont au niveau TYPE, cf. layout build_squad_observation).
BIN_FIGHT_ELIGIBLE = 0
BIN_IN_ENEMY_EZ = 1
BIN_EZ_VIA_BUDDY = 2


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "display_name": "Test Bolter",
    }


def _unit_cfg(uid: int, player: int, positions: List[Tuple[int, int]], base_size: int) -> Dict[str, Any]:
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
        "BASE_SHAPE": "round", "BASE_SIZE": base_size, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _config(
    my_positions: List[Tuple[int, int]],
    enemy_positions: List[Tuple[int, int]],
    base_size: int = 1,
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
            _unit_cfg(1, 1, my_positions, base_size),
            _unit_cfg(2, 2, enemy_positions, base_size),
        ],
    }


def _make_engine(cfg: Dict[str, Any]) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=cfg)
    eng.reset()
    return eng


def _model_flags(engine, k_idx: int) -> Dict[str, float]:
    binv = engine.obs_builder.build_squad_observation(engine.game_state, "1")["vec_bin"]
    base = ObservationBuilder.squad_model_bin_base(k_idx)
    return {
        "fight": float(binv[base + BIN_FIGHT_ELIGIBLE]),
        "in_ez": float(binv[base + BIN_IN_ENEMY_EZ]),
        "buddy": float(binv[base + BIN_EZ_VIA_BUDDY]),
    }


def test_model_adjacent_to_enemy_is_in_ez():
    """Figurine 0 collée à l'ennemi : dans l'EZ ; figurine 1 (loin, isolée) : rien."""
    eng = _make_engine(_config([(30, 20), (50, 20)], [(31, 20)]))
    assert _model_flags(eng, 0)["in_ez"] == 1.0
    far = _model_flags(eng, 1)
    assert far["in_ez"] == 0.0 and far["buddy"] == 0.0


def test_buddy_relay_uses_engagement_zone():
    """Figurine 1 hors EZ ennemie mais dans l'EZ de sa copine engagée -> drapeau « copain »."""
    eng = _make_engine(_config([(30, 20), (29, 20)], [(31, 20)]))
    first = _model_flags(eng, 0)
    second = _model_flags(eng, 1)
    assert first["in_ez"] == 1.0
    assert second["in_ez"] == 0.0
    assert second["buddy"] == 1.0


def test_large_bases_in_ez_are_seen():
    """Contre-épreuve du bord-à-bord : ancres à 2 subhex, socles au contact.

    L'ancien test `calculate_hex_distance(ancre, ancre) == 1` renvoyait 0 ici ; la règle 03.04
    (bord à bord) et le pool de combat du moteur disent « engagée ».
    """
    eng = _make_engine(_config([(30, 20)], [(32, 20)], base_size=16))
    gs = eng.game_state
    from engine.combat_utils import calculate_hex_distance
    from engine.phase_handlers.shared_utils import BASE_TO_BASE_SUBHEX

    assert calculate_hex_distance(30, 20, 32, 20) != BASE_TO_BASE_SUBHEX, (
        "fixture invalide : les ancres doivent être HORS du test bord-à-bord brut"
    )
    assert "1#0" in set(get_fighting_models(gs, "1")), "fixture : le moteur doit voir l'engagement"
    assert _model_flags(eng, 0)["in_ez"] == 1.0


def test_flags_agree_with_engine_fight_pool():
    """Cohérence : toute figurine dans l'EZ ennemie est dans le pool de combat du moteur (12.04)."""
    eng = _make_engine(_config([(30, 20), (29, 20), (50, 20)], [(31, 20)]))
    gs = eng.game_state
    pool = set(get_fighting_models(gs, "1"))
    alive = [m for m in gs["squad_models"]["1"] if m in gs["models_cache"]]
    for k_idx, mid in enumerate(alive):
        flags = _model_flags(eng, k_idx)
        if flags["in_ez"] == 1.0:
            assert mid in pool, f"{mid} vu engagé par l'obs mais absent du pool moteur"
        assert flags["fight"] == (1.0 if mid in pool else 0.0)
