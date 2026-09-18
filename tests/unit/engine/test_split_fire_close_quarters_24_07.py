"""Split-fire gym (P3-8) sous [CLOSE-QUARTERS] 24.07 : le verrou est PAR FIGURINE, pas par unité.

24.07 (PDF 24) : « for each model in that unit (excluding MONSTER/VEHICLE models), you can only
select one of the following to make attacks with: one or more of its [CLOSE-QUARTERS] weapons ;
one or more of its other ranged weapons. » Le moteur l'impose PAR FIGURINE à la déclaration
(`_declare_qty_candidates`, chantier « chaîne d'attaque 100 % », 2026-09-18), et le chemin de
l'agent déclare chaque ligne (arme, cible) dès le choix de la cible puis relit le masque sur l'état
déclaré (`filter_remaining_weapon_slots`, suite 146).

Le jumeau `test_split_fire_gym.py::test_split_fire_24_07_first_family_closes_the_other_slot`
verrouille la fermeture de l'AUTRE famille quand toutes les figurines ont tiré la première. Ici,
le cas complémentaire : une figurine n'a QUE le pistolet, l'autre QUE le fusil — la ligne
pistolet ne ferme rien pour la seconde (24.07 se lit figurine par figurine), le slot fusil reste
ouvert, la seconde ligne est déclarée sur l'état déclaré et l'activation résout les deux lots.
Un verrou par UNITÉ (l'ancien grisage du menu PvP) rendrait ce test rouge en fermant le fusil.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from engine.macro_intents import SHOOT_SLOT_BASE, SHOOT_WEAPON_SEL_SLOT_BASE
from engine.observation_builder import ObservationBuilder
from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.shared_utils import (
    clear_pending_shoot_intent,
    get_enemy_slot_mapping,
    shoot_weapon_remaining_eligible_slots,
    squad_shooting_unit_activation_start,
)
from engine.reward_calculator import RewardCalculator
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

PENDING_KEY = "pending_shoot_weapon_split"


def _rng(code: str, rules: List[str]) -> Dict[str, Any]:
    return {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": list(rules), "code": code, "display_name": code}


def _cc() -> Dict[str, Any]:
    return {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
            "WEAPON_RULES": [], "code": "cq_blade", "display_name": "Blade"}


def _cfg_unit(uid: int, player: int, positions: List[Tuple[int, int]],
              weapons_per_model: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    specs = [
        {"col": c, "row": r, "HP_CUR": 2, "HP_MAX": 2, "VALUE": 10,
         "RNG_WEAPONS": weapons, "CC_WEAPONS": [_cc()]}
        for (c, r), weapons in zip(positions, weapons_per_model)
    ]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 2 * len(specs), "HP_MAX": 2, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [w for group in weapons_per_model for w in group],
        "CC_WEAPONS": [_cc()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


BOLTER = _rng("cq_bolter", [])
PISTOL = _rng("cq_pistol", ["CLOSE_QUARTERS"])


def _engine(weapons_per_model: List[List[Dict[str, Any]]]):
    """Moteur en phase de tir : la tireuse « 1 » (joueur 1) face à un ennemi « 2 » à portée."""
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    positions = [(10 + i, 20) for i in range(len(weapons_per_model))]
    cfg = {
        "board": {"default": {"cols": 80, "rows": 40, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [], "inches_to_subhex": 1}},
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5,
                       "max_base_size_hex": 35, "unit_model_cohesion_range": 2,
                       "unit_global_cohesion_range": 9, "squad_min_neighbors": 1,
                       "cohesion_distance_mode": "euclidean"},
        "charge": {"charge_max_distance": 12},
        "move": {"can_move_through_enemy_engagement_zone": True,
                 "can_move_through_enemy_model": False,
                 "can_move_through_friendly_model": True},
        "pve_mode": False, "scenario_objectives": [], "controlled_player": 1,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [
            _cfg_unit(1, 1, positions, weapons_per_model),
            _cfg_unit(2, 2, [(20, 20)], [[BOLTER]]),
        ],
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        engine = W40KEngine(config=build_engine_config(cfg), gym_training_mode=True, quiet=True)
    engine.reset()
    engine.game_state["phase"] = "shoot"
    engine.game_state["current_player"] = 1
    shooting_handlers.shooting_phase_start(engine.game_state)
    return engine


@pytest.fixture(autouse=True)
def _no_reward(monkeypatch):
    monkeypatch.setattr(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 0.0)


def _open_weapon_slots(engine) -> List[int]:
    mask, _pool = engine.action_decoder.get_squad_action_mask_and_eligible_units(engine.game_state)
    return [i for i, opened in enumerate(mask) if opened and i >= SHOOT_WEAPON_SEL_SLOT_BASE]


def _activate_and_arm(engine, weapon_code: str) -> Dict[str, Any]:
    """Active la tireuse puis arme le slot dont le code est `weapon_code` ; rend le pending."""
    gs = engine.game_state
    # Une seule escouade alliée : aucun choix d'activation (L2), le masque ouvre directement les
    # slots d'arme de la tireuse.
    opened = _open_weapon_slots(engine)
    assert len(opened) == 2, f"les deux familles doivent être ouvertes à l'activation : {opened}"
    # Slot ↔ code : la même table que le commit (`shoot_weapon_remaining_eligible_slots`), lue
    # AVANT toute déclaration, hors activation de tir (elle n'est démarrée qu'au premier commit).
    squad_shooting_unit_activation_start(gs, "1")
    slot_to_code = shoot_weapon_remaining_eligible_slots(
        gs, "1", get_enemy_slot_mapping(gs, 1), except_slot=-1
    )
    clear_pending_shoot_intent(gs, "1")
    (slot_j,) = [j for j, code in slot_to_code.items() if code == weapon_code]
    engine.step_with_mask(int(SHOOT_WEAPON_SEL_SLOT_BASE + slot_j))
    pending = gs[PENDING_KEY]
    assert pending["pending_weapon"] == weapon_code, pending
    return pending


def _target_action(engine) -> int:
    pending = engine.game_state[PENDING_KEY]
    return int(SHOOT_SLOT_BASE + pending["eligible_target_slots"][0])


def _declared_codes(engine) -> List[str]:
    gs = engine.game_state
    codes = []
    for intent in gs["pending_squad_shoot_intents"].get("1", []):
        model = gs["models_cache"][intent["model_id"]]
        codes.append(model["RNG_WEAPONS"][intent["weapon_index"]]["code"])
    return sorted(codes)


def _shoot_logs(engine) -> List[Tuple[str, int]]:
    """(arme, nombre d'attaques) de chaque ligne de tir de la tireuse « 1 », dans l'ordre."""
    return [
        (str(log["weaponName"]), len(log["shootDetails"]))
        for log in engine.game_state["action_logs"]
        if log.get("type") == "shoot" and str(log.get("shooterId")) == "1"
    ]


def test_the_family_lock_is_per_model_not_per_unit():
    """Une figurine avec le seul pistolet, une autre avec le seul bolter : après la ligne pistolet,
    le slot bolter reste ouvert pour la SECONDE figurine (24.07 est par figurine), et la seconde
    ligne est déclarée sur l'état déclaré — deux intents, une résolution."""
    engine = _engine([[PISTOL], [BOLTER]])
    _activate_and_arm(engine, "cq_pistol")
    engine.step_with_mask(_target_action(engine))
    pending = engine.game_state.get(PENDING_KEY)
    assert pending is not None and pending["pending_weapon"] is None, pending
    assert list(pending["remaining_weapon_slots"].values()) == ["cq_bolter"], pending
    assert _declared_codes(engine) == ["cq_pistol"], "la ligne pistolet est déclarée dès le choix de la cible"
    (slot_action,) = _open_weapon_slots(engine)
    engine.step_with_mask(int(slot_action))
    assert engine.game_state[PENDING_KEY]["pending_weapon"] == "cq_bolter"
    assert _declared_codes(engine) == ["cq_pistol"]
    engine.step_with_mask(_target_action(engine))
    assert PENDING_KEY not in engine.game_state
    assert sorted(_shoot_logs(engine)) == [("cq_bolter", 1), ("cq_pistol", 1)]
