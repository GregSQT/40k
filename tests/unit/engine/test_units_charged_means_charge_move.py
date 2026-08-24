"""`units_charged` = « a FAIT un charge move » (11.04 / 12.03 / 12.04), rien d'autre.

11.04 place le grant de Fights First sous **AFTER MOVING** du charge move ; 12.03 (pile-in) et
12.04 (eligibilite au combat) disent « made a charge move this turn ». Une charge RATEE et un WAIT
en phase de charge n'en font aucun.

Le chemin gym marquait les deux, via `end_activation(..., Arg3=CHARGE, ...)` :
`w40k_core` branche `squad_charge` (plan None) et table `phase_tracking` de `squad_wait`. Les
SEULS consommateurs de `units_charged` sont ces regles (`is_fights_first`,
`_fight_v11_charged_this_turn`) : l'escouade gagnait Fights First et passait devant les vrais
chargeurs. Mesure sur un run de 600 episodes : 60 lignes FIGHT sur 60 emises avant le premier vrai
chargeur appartenaient a une escouade ayant fini son activation de charge SANS charger.

Le jumeau PvP (`charge_handlers` ~L2929) passait deja PASS — c'etait une divergence gym.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.fight_handlers import is_fights_first
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config


def _weapon_cfg() -> Dict[str, Any]:
    return {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": [], "display_name": "Test Bolter"}


def _cc_weapon_cfg() -> Dict[str, Any]:
    return {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 2,
            "WEAPON_RULES": [], "display_name": "Test Blade"}


def _unit_cfg(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 3, "HP_MAX": 3, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [_cc_weapon_cfg()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": 1, "VALUE": 100,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
    }


@pytest.fixture
def engine() -> W40KEngine:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    config = {
        "board": {"default": {"cols": 60, "rows": 60, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [], "objectives": [], "inches_to_subhex": 1}},
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5,
                       "max_base_size_hex": 35, "max_turns": 5},
        "charge": {"charge_max_distance": 12},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "controlled_player": 1,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        # 6 cases d'ecart : la cible est declarable (< 12") mais un jet de 2 ne l'atteint pas.
        "units": [_unit_cfg(1, 1, 20, 20), _unit_cfg(2, 2, 26, 20)],
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(config), gym_training_mode=True)
    eng.reset()
    eng.game_state["phase"] = "charge"
    eng.game_state["charge_activation_pool"] = ["1"]
    return eng


def _charged(eng: W40KEngine) -> List[str]:
    return sorted(eng.game_state["units_charged"])


def test_failed_charge_does_not_grant_fights_first(engine: W40KEngine) -> None:
    """Jet insuffisant -> aucun charge move -> ni `units_charged`, ni Fights First (11.04)."""
    gs = engine.game_state
    # 11 encart FAILED CHARGES : « a result of 2 (a double 1) is never sufficient ». Le jet est
    # IMPOSE, pas espere d'une graine : le test doit CONSTRUIRE la situation qu'il observe.
    with patch("engine.phase_handlers.shared_utils.roll_charge_distance", return_value=2):
        ok, result = engine._process_squad_action(
            {"action": "squad_charge", "squad_id": "1", "target_slot": 0}
        )
    assert ok is True
    # `{**result, **phase_init_result}` dans la cascade préserve `charge_succeeded: False` de la
    # charge initiale — vérifier directement, puis vérifier l'invariant via action_logs.
    assert result["charge_succeeded"] is False
    charge_fail_log = next(
        (l for l in gs["action_logs"] if l.get("type") == "charge_fail"), None
    )
    assert charge_fail_log is not None, f"Expected charge_fail in action_logs: {gs['action_logs']}"

    assert _charged(engine) == []
    assert is_fights_first(gs["unit_by_id"]["1"], gs) is False
    # Le retrait du pool d'activation reste assure par Arg4 : pas de re-charge dans la phase.
    assert "1" not in gs["charge_activation_pool"]


def test_wait_in_charge_phase_does_not_grant_fights_first(engine: W40KEngine) -> None:
    """Renoncer a charger n'est pas charger (11.02 étape 3 « does not make a charge move »)."""
    gs = engine.game_state
    ok, _ = engine._process_squad_action({"action": "squad_wait", "squad_id": "1"})
    assert ok is True

    assert _charged(engine) == []
    assert is_fights_first(gs["unit_by_id"]["1"], gs) is False
    assert "1" not in gs["charge_activation_pool"]


def test_successful_charge_still_grants_fights_first(engine: W40KEngine) -> None:
    """Contrôle anti-vert-vacant : le marquage EXISTE toujours quand la charge aboutit."""
    gs = engine.game_state
    with patch("engine.phase_handlers.shared_utils.roll_charge_distance", return_value=12):
        ok, result = engine._process_squad_action(
            {"action": "squad_charge", "squad_id": "1", "target_slot": 0}
        )
    assert ok is True
    assert result["charge_succeeded"] is True, result
    # Charge réussie → placement demandé ; commit_move (et units_charged) est différé après CHOICE_k.
    assert result["action"] == "waiting_for_agent_decision"
    assert result.get("decision_type") == "charge_placement"

    ok2, _ = engine._process_squad_action({"action": "agent_decision", "option_index": 0})
    assert ok2 is True

    assert _charged(engine) == ["1"]
    assert is_fights_first(gs["unit_by_id"]["1"], gs) is True

