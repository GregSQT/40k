"""§4.3 — le gym doit alimenter le systeme AUTORITAIRE de l'Advance (`advance_rolls`).

Spec : Documentation/Implementation/A_faire/move_action_space_spatial_rework.md §4.3 / §7 T3.

Le bug d'origine : `commit_move` marque `units_advanced` mais n'ecrit JAMAIS `advance_rolls`.
`_advance_roll_for` trouvait donc l'escouade advancee mais sans jet -> renvoyait None -> tout
pool reconstruit ensuite repartait sur le budget NORMAL au lieu de M+jet, silencieusement.
Le gym ecrivait son jet dans `_squad_advance_rolls`, que personne d'autre ne lit.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import pytest

from engine.phase_handlers.movement_handlers import _advance_roll_for
from engine.phase_handlers.shared_utils import execute_squad_move, get_squad_move_budget
from engine.w40k_core import W40KEngine


def _weapon_cfg() -> Dict[str, Any]:
    return {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": [], "display_name": "Test Bolter"}


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


@pytest.fixture
def engine():
    obs_params = {"perception_radius": 25, "max_nearby_units": 10, "max_valid_targets": 5,
                  "obs_size": 108, "action_space_size": 1047}
    config = {
        "board": {"default": {"cols": 60, "rows": 60, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [], "objectives": [], "inches_to_subhex": 1}},
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
        "charge": {"charge_max_distance": 12},
        # Toggles de traversee requis par le pool BFS (valeurs reelles de config/game_config.json).
        # Le masque spatial passe par le pool -> cette section devient obligatoire, la ou les
        # anciens dry-runs directionnels ne la lisaient pas.
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [_unit_cfg(1, 1, 20, 20), _unit_cfg(2, 2, 50, 50)],
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=config)
    eng.reset()
    eng.game_state["phase"] = "move"
    return eng


def test_gym_advance_records_the_roll_in_the_authoritative_system(engine):
    """Apres un advance gym, `advance_rolls` porte le jet -> `_advance_roll_for` le retrouve."""
    gs = engine.game_state
    assert execute_squad_move("1", 24, 20, "advance", gs, advance_roll=4) is True

    assert "1" in gs["units_advanced"]
    assert gs["advance_rolls"]["1"] == 4
    assert _advance_roll_for("1", gs) == 4


def test_pool_budget_after_gym_advance_is_not_silently_the_normal_one(engine):
    """LE bug §4.3 : sans le jet fige, le budget retombait a M au lieu de M+jet, sans erreur."""
    gs = engine.game_state
    execute_squad_move("1", 24, 20, "advance", gs, advance_roll=5)

    roll = _advance_roll_for("1", gs)
    assert roll is not None, "escouade advancee sans jet -> le pool repartirait sur le budget normal"

    normal_budget = get_squad_move_budget("1", gs, "normal")
    advance_budget = get_squad_move_budget("1", gs, "advance", advance_roll=roll)
    assert advance_budget > normal_budget
    # MOVE 6 x ish 1 + jet 5 x ish 1 = 11
    assert advance_budget == 11


def test_normal_move_does_not_touch_advance_rolls(engine):
    """Non-regression : un move normal ne doit rien ecrire dans le systeme Advance."""
    gs = engine.game_state
    execute_squad_move("1", 24, 20, "normal", gs)
    assert "1" not in gs.get("units_advanced", set())
    assert "1" not in gs.get("advance_rolls", {})
    assert _advance_roll_for("1", gs) is None


def test_fall_back_does_not_touch_advance_rolls(engine):
    gs = engine.game_state
    execute_squad_move("1", 24, 20, "fall_back", gs)
    assert "1" not in gs.get("advance_rolls", {})
