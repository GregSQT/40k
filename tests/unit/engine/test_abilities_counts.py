"""Tests — abilities_counts / abilities_exposure dans episode_tactical_data.

VERROUS :
1. EXISTENCE — après terminaison, tactical_data porte les deux clés.
2. NOMS DE CLÉS — toutes les 16 clés count et 16 clés exposure sont présentes.
3. FAMILLE A — une ligne reactive_move / charge_impact / move_after_shooting injectée
   incrémente le bon compteur.
4. CHARGE AVEC CAPACITÉ — ability_rule_effect sur un charge log incrémente
   charge_after_advance_agent.
5. FAMILLE B — un shoot log d'adversaire avec hitAbility incrémente hit_reroll_opp.
6. EXPOSITION — une unité dont UNIT_RULES contient reactive_move donne exposure=1.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple
from unittest.mock import patch

import numpy as np
import pytest

from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.shared_utils import SQUAD_ACTION_WAIT
from engine.reward_calculator import RewardCalculator
from engine.w40k_core import W40KEngine
from tests._state_invariants import charge_log_line
from tests.unit.engine._config_helpers import build_engine_config


# ──────────────────────────────────────────────────────────────────────────────
# Harnais — identique à test_episode_combat_counters
# ──────────────────────────────────────────────────────────────────────────────

def _weapon(rng: int, name: str) -> Dict[str, Any]:
    return {"ATK": 1, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": rng,
            "WEAPON_RULES": [], "code": name, "display_name": name}


def _unit(uid: int, player: int, col: int, row: int,
          unit_rules: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": f"TestUnit{uid}", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 5, "HP_MAX": 5, "MOVE": 1, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon(24, "Bolter")],
        "CC_WEAPONS": [_weapon(1, "Blade")],
        "UNIT_RULES": unit_rules if unit_rules is not None else [],
        "UNIT_KEYWORDS": [], "LD": 7, "OC": 1, "VALUE": 100,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
    }


def _config(units: List[Dict[str, Any]], controlled_player: int = 1) -> Dict[str, Any]:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    return {
        "board": {"default": {
            "cols": 15, "rows": 13, "hex_radius": 1.0, "margin": 0.0, "wall_hexes": [],
            "objectives": [{"id": "obj1", "name": "Alpha", "hexes": [[7, 6]]}],
            "inches_to_subhex": 1,
        }},
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            "max_turns": 5, "max_actions_per_model_per_turn": 7, "step_limit_margin": 1.5,
        },
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "charge": {"charge_max_distance": 1},  # empêche les vraies charges
        "pve_mode": False,
        "controlled_player": controlled_player,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params},
        "units": units,
    }


@pytest.fixture(autouse=True)
def _stub_rewards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 0.0)
    monkeypatch.setattr(
        W40KEngine, "_build_observation",
        lambda self, *_a, **_k: np.zeros(ObservationBuilder.SQUAD_OBS_SIZE_TARGET),
    )


def _build(config: Dict[str, Any]) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        engine = W40KEngine(config=build_engine_config(config), gym_training_mode=True, quiet=True)
    engine.reset()
    return engine


def _run_to_end(engine: W40KEngine, pick: Callable[[Any], int] | None = None) -> Dict[str, Any]:
    if pick is None:
        pick = lambda legal: legal[0]
    info: Dict[str, Any] = {}
    for _ in range(4000):
        mask = engine.get_action_mask()
        legal = np.flatnonzero(mask)
        action = int(pick(legal)) if legal.size else SQUAD_ACTION_WAIT
        _obs, _reward, terminated, truncated, info = engine.step(action)
        if terminated or truncated:
            break
    assert "tactical_data" in info, "épisode non terminé : pas de tactical_data"
    return info["tactical_data"]


_UNITS_FAR = [
    _unit(1, 1, 2, 6), _unit(2, 1, 2, 7),
    _unit(3, 2, 12, 6), _unit(4, 2, 12, 7),
]


# ──────────────────────────────────────────────────────────────────────────────
# 1. VERROU existence
# ──────────────────────────────────────────────────────────────────────────────

def test_abilities_keys_present_after_episode() -> None:
    """VERROU 1 : tactical_data porte abilities_counts et abilities_exposure après terminaison."""
    engine = _build(_config(_UNITS_FAR))
    tactical = _run_to_end(engine)
    assert "abilities_counts" in tactical
    assert "abilities_exposure" in tactical


# ──────────────────────────────────────────────────────────────────────────────
# 2. VERROU noms de clés
# ──────────────────────────────────────────────────────────────────────────────

_ABILITIES_KEYS = (
    "reactive_move", "charge_impact",
    "charge_after_advance", "charge_after_flee",
    "move_after_shooting",
    "hit_reroll", "wound_reroll", "oath_wound_bonus",
)
_EXPECTED_KEYS = {f"{k}_{s}" for k in _ABILITIES_KEYS for s in ("agent", "opp")}


def test_abilities_all_count_keys_present() -> None:
    """VERROU 2a : toutes les 16 clés count sont présentes (y compris à 0)."""
    engine = _build(_config(_UNITS_FAR))
    tactical = _run_to_end(engine)
    counts = tactical["abilities_counts"]
    for key in _EXPECTED_KEYS:
        assert key in counts, f"clé manquante : {key!r}"


def test_abilities_all_exposure_keys_present() -> None:
    """VERROU 2b : toutes les 16 clés exposure sont présentes."""
    engine = _build(_config(_UNITS_FAR))
    tactical = _run_to_end(engine)
    exposure = tactical["abilities_exposure"]
    for key in _EXPECTED_KEYS:
        assert key in exposure, f"clé exposure manquante : {key!r}"


# ──────────────────────────────────────────────────────────────────────────────
# 3. VERROU Famille A — reactive_move / charge_impact / move_after_shooting
# ──────────────────────────────────────────────────────────────────────────────

def test_famille_a_reactive_move_agent_counted() -> None:
    """Un log reactive_move du joueur contrôlé incrémente reactive_move_agent."""
    engine = _build(_config(_UNITS_FAR, controlled_player=1))
    engine.game_state["action_logs"].append({"type": "reactive_move", "player": 1})
    engine.game_state["action_logs"].append({"type": "reactive_move", "player": 1})
    tactical = _run_to_end(engine)
    assert tactical["abilities_counts"]["reactive_move_agent"] == 2
    assert tactical["abilities_counts"]["reactive_move_opp"] == 0


def test_famille_a_charge_impact_opp_counted() -> None:
    """Un log charge_impact de l'adversaire incrémente charge_impact_opp, pas _agent."""
    engine = _build(_config(_UNITS_FAR, controlled_player=1))
    engine.game_state["action_logs"].append({"type": "charge_impact", "player": 2})
    tactical = _run_to_end(engine)
    assert tactical["abilities_counts"]["charge_impact_opp"] == 1
    assert tactical["abilities_counts"]["charge_impact_agent"] == 0


def test_famille_a_move_after_shooting_counted() -> None:
    """Un log move_after_shooting du joueur contrôlé incrémente move_after_shooting_agent."""
    engine = _build(_config(_UNITS_FAR, controlled_player=1))
    engine.game_state["action_logs"].append({"type": "move_after_shooting", "player": 1})
    tactical = _run_to_end(engine)
    assert tactical["abilities_counts"]["move_after_shooting_agent"] == 1


# ──────────────────────────────────────────────────────────────────────────────
# 4. VERROU Famille A — charge avec ability_rule_effect
# ──────────────────────────────────────────────────────────────────────────────

def test_charge_after_advance_counted_on_ability_charge() -> None:
    """Une charge réussie avec ability_rule_effect='charge_after_advance' incrémente le compteur."""
    engine = _build(_config(_UNITS_FAR, controlled_player=1))
    engine.game_state["action_logs"].append(
        charge_log_line(1, "charge", ability_rule_effect="charge_after_advance")
    )
    tactical = _run_to_end(engine)
    assert tactical["abilities_counts"]["charge_after_advance_agent"] == 1
    assert tactical["abilities_counts"]["charge_after_flee_agent"] == 0


def test_charge_after_flee_opp_counted() -> None:
    """Une charge adverse avec ability_rule_effect='charge_after_flee' incrémente _opp."""
    engine = _build(_config(_UNITS_FAR, controlled_player=1))
    engine.game_state["action_logs"].append(
        charge_log_line(2, "charge", ability_rule_effect="charge_after_flee")
    )
    tactical = _run_to_end(engine)
    assert tactical["abilities_counts"]["charge_after_flee_opp"] == 1
    assert tactical["abilities_counts"]["charge_after_flee_agent"] == 0


def test_charge_fail_with_ability_not_counted() -> None:
    """Un ÉCHEC de charge avec ability_rule_effect ne compte pas — la capacité n'a rien permis."""
    engine = _build(_config(_UNITS_FAR, controlled_player=1))
    engine.game_state["action_logs"].append(
        charge_log_line(1, "charge_fail", ability_rule_effect="charge_after_advance")
    )
    tactical = _run_to_end(engine)
    assert tactical["abilities_counts"]["charge_after_advance_agent"] == 0


def test_normal_charge_no_ability_not_counted() -> None:
    """Une charge normale (sans ability_rule_effect) ne comptabilise aucune capacité."""
    engine = _build(_config(_UNITS_FAR, controlled_player=1))
    engine.game_state["action_logs"].append(charge_log_line(1, "charge"))
    tactical = _run_to_end(engine)
    assert tactical["abilities_counts"]["charge_after_advance_agent"] == 0
    assert tactical["abilities_counts"]["charge_after_flee_agent"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# 5. VERROU Famille B — relances via shootDetails
# ──────────────────────────────────────────────────────────────────────────────

def _shoot_log_opp(
    shoot_details: List[Dict[str, Any]],
    controlled_player: int = 1,
) -> Dict[str, Any]:
    """Shoot log d'adversaire minimal pour la Famille B (pas de turn/shooterId nécessaires)."""
    opp = 2 if controlled_player == 1 else 1
    return {
        "type": "shoot",
        "player": opp,
        "damage": 0,
        "shootDetails": shoot_details,
    }


def test_hit_reroll_opp_counted_via_shootdetails() -> None:
    """hitAbility dans shootDetails d'un log adversaire incrémente hit_reroll_opp."""
    engine = _build(_config(_UNITS_FAR, controlled_player=1))
    engine.game_state["action_logs"].append(
        _shoot_log_opp([{"hitAbility": "Lethal Hits"}, {"hitAbility": "Lethal Hits"}])
    )
    tactical = _run_to_end(engine)
    assert tactical["abilities_counts"]["hit_reroll_opp"] == 2
    assert tactical["abilities_counts"]["hit_reroll_agent"] == 0


def test_wound_reroll_opp_counted_via_shootdetails() -> None:
    """woundAbility dans shootDetails incrémente wound_reroll_opp."""
    engine = _build(_config(_UNITS_FAR, controlled_player=1))
    engine.game_state["action_logs"].append(
        _shoot_log_opp([{"woundAbility": "Sustained Hits"}])
    )
    tactical = _run_to_end(engine)
    assert tactical["abilities_counts"]["wound_reroll_opp"] == 1


def test_oath_wound_bonus_opp_counted_and_exposure_proxy() -> None:
    """woundBonusAbility incrémente oath_wound_bonus_opp ET set exposure via proxy."""
    engine = _build(_config(_UNITS_FAR, controlled_player=1))
    engine.game_state["action_logs"].append(
        _shoot_log_opp([{"woundBonusAbility": "Oath of Moment"}])
    )
    tactical = _run_to_end(engine)
    assert tactical["abilities_counts"]["oath_wound_bonus_opp"] == 1
    # Exposure proxy : au moins un tir avec le bonus → exposé
    assert tactical["abilities_exposure"]["oath_wound_bonus_opp"] == 1


def test_no_ability_in_shootdetails_no_count() -> None:
    """Un tir sans aucune ability dans shootDetails ne lève aucun compteur abilities/."""
    engine = _build(_config(_UNITS_FAR, controlled_player=1))
    engine.game_state["action_logs"].append(
        _shoot_log_opp([{}, {}])
    )
    tactical = _run_to_end(engine)
    assert tactical["abilities_counts"]["hit_reroll_opp"] == 0
    assert tactical["abilities_counts"]["wound_reroll_opp"] == 0
    assert tactical["abilities_counts"]["oath_wound_bonus_opp"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# 6. VERROU exposition — unit_has_rule_effect sur les unités du roster
# ──────────────────────────────────────────────────────────────────────────────

def _rule_entry(rule_id: str) -> Dict[str, Any]:
    """Entrée UNIT_RULES minimale valide (ruleId + displayName requis par rebuild_choice_timing_index)."""
    return {"ruleId": rule_id, "displayName": rule_id}


def test_exposure_one_when_controlled_unit_has_reactive_move() -> None:
    """Une unité alliée avec UNIT_RULES reactive_move → reactive_move_agent_exposure = 1."""
    units = [
        _unit(1, 1, 2, 6, unit_rules=[_rule_entry("reactive_move")]),
        _unit(2, 2, 12, 6),
    ]
    engine = _build(_config(units, controlled_player=1))
    tactical = _run_to_end(engine)
    assert tactical["abilities_exposure"]["reactive_move_agent"] == 1
    assert tactical["abilities_exposure"]["reactive_move_opp"] == 0


def test_exposure_zero_when_no_unit_has_the_rule() -> None:
    """Sans unité portant reactive_move, l'exposition reste 0."""
    engine = _build(_config(_UNITS_FAR, controlled_player=1))
    tactical = _run_to_end(engine)
    assert tactical["abilities_exposure"]["reactive_move_agent"] == 0


def test_exposure_opp_when_enemy_unit_has_rule() -> None:
    """Une unité ennemie avec charge_impact → charge_impact_opp_exposure = 1, pas _agent."""
    units = [
        _unit(1, 1, 2, 6),
        _unit(2, 2, 12, 6, unit_rules=[_rule_entry("charge_impact")]),
    ]
    engine = _build(_config(units, controlled_player=1))
    tactical = _run_to_end(engine)
    assert tactical["abilities_exposure"]["charge_impact_opp"] == 1
    assert tactical["abilities_exposure"]["charge_impact_agent"] == 0


def test_oath_wound_bonus_exposure_zero_when_no_shots() -> None:
    """Sans shot avec woundBonusAbility, oath_wound_bonus_exposure reste 0 (proxy = compteur)."""
    engine = _build(_config(_UNITS_FAR, controlled_player=1))
    tactical = _run_to_end(engine)
    assert tactical["abilities_exposure"]["oath_wound_bonus_agent"] == 0
    assert tactical["abilities_exposure"]["oath_wound_bonus_opp"] == 0


def test_hit_reroll_agent_exposure_proxy_via_count() -> None:
    """hitAbility dans shoot log agent → hit_reroll_agent_exposure=1 via proxy count (Oath, pas reroll_1_tohit_fight)."""
    engine = _build(_config(_UNITS_FAR, controlled_player=1))
    engine.game_state["action_logs"].append({
        "type": "shoot",
        "player": 1,
        "damage": 0,
        "turn": 1,
        "shooterId": "1",
        "shootDetails": [{"hitAbility": "Oath of Moment", "hitResult": "MISS"}],
    })
    tactical = _run_to_end(engine)
    assert tactical["abilities_counts"]["hit_reroll_agent"] == 1
    assert tactical["abilities_exposure"]["hit_reroll_agent"] == 1


def test_hit_reroll_opp_exposure_proxy_via_count() -> None:
    """hitAbility dans shoot log opp → hit_reroll_opp_exposure=1 via proxy count."""
    engine = _build(_config(_UNITS_FAR, controlled_player=1))
    engine.game_state["action_logs"].append(
        _shoot_log_opp([{"hitAbility": "Oath of Moment"}])
    )
    tactical = _run_to_end(engine)
    assert tactical["abilities_counts"]["hit_reroll_opp"] == 1
    assert tactical["abilities_exposure"]["hit_reroll_opp"] == 1
