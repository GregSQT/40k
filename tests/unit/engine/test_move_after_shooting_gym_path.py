"""Fin de tir d'escouade du GYM par la fin d'activation de DATASHEET (décision du 2026-09-18).

Le chemin direct `squad_shoot` de `_process_squad_action`, le tir fractionné
`squad_shoot_split_target` et la fin par allocation (`_end_squad_shoot_activation`) terminaient
l'activation par le `end_activation` GÉNÉRIQUE : aucun effet de datasheet de fin de tir n'existait
pour le siège gym ni pour le bot PvE. Deux capacités du roster d'entraînement en dépendent :

- Purgation Run (Land Speeder, `Datasheets - Space Marines.pdf` p.8) : « after this unit has
  shot, it can make a normal move of up to D6". If it does, until the end of the turn, this unit
  is not eligible to declare a charge » — décision `move_after_shooting` (type déjà déclaré dans
  `AGENT_DECISION_TYPE_IDS`, aucune colonne d'obs ni slot d'action ajouté), réponse `CHOICE_k`,
  renoncement possible (candidat `declines`), verrou de charge par `units_cannot_charge` ;
- Indiscriminate Detonations (WarTrakk, `Datasheets - Orks.pdf` p.8) : « when this unit has
  resolved its attacks, select one enemy unit hit by one or more of those attacks. That enemy
  unit is suppressed » — `suppressed_squads`.

Ce que ces tests verrouillent : le CHEMIN (le gym atteint `_handle_shooting_end_activation`),
l'attente (l'escouade reste dans le pool jusqu'à `CHOICE_k`), les deux effets, et l'attribution de
la récompense — le tir est payé au step du tir (`squad_shoot` + `shoot_result`), le step
`CHOICE_k` ne paie rien de plus (« payer l'agent pour décider, pas pour bien décider »).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

from engine.agent_decision import read_pending_agent_decision
from engine.macro_intents import ACTIVATE_SLOT_BASE, SHOOT_SLOT_BASE, SHOOT_WEAPON_SEL_SLOT_BASE
from engine.observation_builder import ObservationBuilder
from engine.phase_handlers import charge_handlers, shooting_handlers
from engine.phase_handlers.shared_utils import get_ally_slot_mapping
from engine.reward_calculator import RewardCalculator
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

_MOVE_AFTER_SHOOTING_INCHES = 3
_MOVE_AFTER_SHOOTING_RULE = {
    "ruleId": "move_after_shooting",
    "displayName": "Purgation Run (test)",
    "rule_args": {"distance": _MOVE_AFTER_SHOOTING_INCHES},
}
_SUPPRESS_RULE = {
    "ruleId": "suppress_target_on_shooting",
    "displayName": "Indiscriminate Detonations (test)",
}


def _weapon(name: str, *, rng: int = 24, **over: Any) -> Dict[str, Any]:
    w = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": rng,
         "WEAPON_RULES": [], "code": name, "display_name": name}
    w.update(over)
    return w


def _unit_cfg(uid: int, player: int, positions: List[Tuple[int, int]], *,
              rng_weapons: List[Dict[str, Any]] | None = None,
              rules: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    weapons = rng_weapons if rng_weapons is not None else [_weapon("Gun")]
    specs = [{"col": c, "row": r, "HP_CUR": 2, "HP_MAX": 2, "VALUE": 10,
              "RNG_WEAPONS": weapons} for c, r in positions]
    return {
        "id": str(uid), "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 2 * len(specs), "HP_MAX": 2, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 7,
        "RNG_WEAPONS": weapons,
        "CC_WEAPONS": [{"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
                        "WEAPON_RULES": [], "code": "test_blade", "display_name": "Blade"}],
        "UNIT_RULES": list(rules or []),
        "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _engine(units: List[Dict[str, Any]], *, pve: bool = False) -> W40KEngine:
    """Moteur GYM en phase de tir, joueur 1 actif — le chemin que joue l'entraînement."""
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    cfg = {
        "board": {"default": {"cols": 120, "rows": 40, "hex_radius": 1.0, "margin": 0.0,
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
        "units": units,
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(cfg), gym_training_mode=not pve)
    eng.reset()
    if pve:
        # Posé APRÈS la construction : un moteur construit en `pve_mode` charge les modèles du
        # bot (`unit_registry` exigé), alors que ce fichier simule la politique. C'est cette clé
        # de `config` que lit `move_after_shooting_seat_is_model_driven`.
        eng.game_state["config"]["pve_mode"] = True
    eng.game_state["phase"] = "shoot"
    eng.game_state["current_player"] = 1
    shooting_handlers.shooting_phase_start(eng.game_state)
    return eng


def _reward_calculator(eng: W40KEngine) -> RewardCalculator:
    """Barème déterministe : récompense sur l'ESPÉRANCE de dégâts (S11), donc indépendante des
    dés — un tir à portée paie strictement plus que zéro, un step sans tir paie zéro."""
    rc = RewardCalculator(
        config={
            "quiet": True, "controlled_agent": "TestUnit", "controlled_player": 1,
            "game_rules": eng.game_state["config"]["game_rules"],
        },
        rewards_config={
            "TestUnit": {
                "squad_shaping": {
                    "hp_damage_weight": 1.0, "model_kill_bonus_factor": 1.0,
                    "squad_kill_bonus_factor": 1.0, "incoherent_weight": 0.0,
                    "reward_on_expectation": True,
                },
                "base_actions": {"ranged_attack": 0.0, "melee_attack": 0.0,
                                 "charge_success": 0.0, "charge_fail": 0.0, "wait": 0.0},
                "result_bonuses": {"kill_target": 0.0, "target_lowest_hp": 0.0},
                "target_type_bonuses": {},
                "situational_modifiers": {"win": 0, "lose": 0, "draw": 0},
                "objective_rewards": {"vp_margin_factor": 0.0, "on_objective_bonus": 0.0},
                "system_penalties": {"forbidden_action": 0.0, "invalid_action": 0.0,
                                     "system_response": 0.0, "generic_error": 0.0},
            }
        },
        unit_registry=None,
        state_manager=None,
    )
    # Les pénalités système sont relues sur disque par clé d'agent ; `TestUnit` n'a pas de
    # dossier — même court-circuit que `test_reward_calculator.py`.
    rc._get_system_penalties = lambda: {  # type: ignore[method-assign]
        "forbidden_action": 0.0, "invalid_action": 0.0, "system_response": 0.0, "generic_error": 0.0,
    }
    return rc


def _position(eng: W40KEngine, uid: str) -> Tuple[int, int]:
    unit = eng.game_state["unit_by_id"][uid]
    return (int(unit["col"]), int(unit["row"]))


def _shoot(eng: W40KEngine) -> Tuple[bool, Dict[str, Any]]:
    return eng._process_squad_action({
        "action": "squad_shoot", "squad_id": "1", "target_slot": 0, "shooting_type": "normal",
    })


# ── Purgation Run : le chemin direct du gym pose la décision ─────────────────────────────


def test_gym_squad_shoot_arms_the_decision_and_the_squad_waits_in_the_pool():
    """ROUGE avant le fix : `end_activation` générique, aucune décision, activation close."""
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rules=[_MOVE_AFTER_SHOOTING_RULE]),
        _unit_cfg(2, 2, [(20, 10)]),
    ])
    gs = eng.game_state

    success, result = _shoot(eng)

    assert success is True
    assert result["action"] == "squad_shoot"
    assert "shoot_result" in result, "le tir est résolu à ce step, son résultat doit y être"
    assert result["waiting_for_player"] is True
    assert "activation_ended" not in result
    decision = read_pending_agent_decision(gs)
    assert decision is not None and decision["type"] == "move_after_shooting"
    assert str(decision["unit_id"]) == "1"
    assert gs["shoot_activation_pool"] == ["1"], "l'escouade attend sa réponse dans le pool"
    assert gs["unit_by_id"]["1"]["_pending_move_after_shooting"] is True
    assert "1" not in gs["units_shot"]


def test_choosing_a_move_relocates_the_squad_and_forbids_its_charge():
    """Datasheet : « If it does, until the end of the turn, this unit is not eligible to declare
    a charge » — verrou `units_cannot_charge`, lu par l'éligibilité de charge."""
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rules=[_MOVE_AFTER_SHOOTING_RULE]),
        _unit_cfg(2, 2, [(20, 10)]),
    ])
    gs = eng.game_state
    _shoot(eng)
    before = _position(eng, "1")
    decision = read_pending_agent_decision(gs)
    assert decision is not None
    chosen = decision["options"][0]
    assert chosen["declines"] is False

    success, done = eng._handle_agent_decision_action({"option_index": 0})

    assert success is True
    assert done["activation_ended"] is True
    assert _position(eng, "1") == (chosen["payload"]["destCol"], chosen["payload"]["destRow"])
    assert _position(eng, "1") != before
    assert read_pending_agent_decision(gs) is None
    assert gs["shoot_activation_pool"] == []
    assert "1" in gs["units_shot"]
    assert "1" in gs["units_cannot_charge"]
    gs["phase"] = "charge"
    assert "1" not in charge_handlers.get_eligible_units(gs), (
        "après Purgation Run, l'escouade ne peut plus déclarer de charge ce tour"
    )


def test_declining_keeps_the_position_and_the_charge():
    """« it CAN make a normal move » : renoncer est un choix de la règle, l'escouade reste sur
    place et garde sa charge."""
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rules=[_MOVE_AFTER_SHOOTING_RULE]),
        _unit_cfg(2, 2, [(20, 10)]),
    ])
    gs = eng.game_state
    _shoot(eng)
    before = _position(eng, "1")
    decision = read_pending_agent_decision(gs)
    assert decision is not None
    decline_index = len(decision["options"]) - 1
    assert decision["options"][decline_index]["declines"] is True

    success, done = eng._handle_agent_decision_action({"option_index": decline_index})

    assert success is True
    assert done["activation_ended"] is True
    assert _position(eng, "1") == before
    assert "1" not in gs["units_cannot_charge"]
    assert gs["shoot_activation_pool"] == []
    assert "1" in gs["units_shot"]
    gs["phase"] = "charge"
    assert "1" in charge_handlers.get_eligible_units(gs)


def test_the_shot_is_paid_at_the_shot_step_and_the_choice_pays_nothing():
    """Attribution : le step `squad_shoot` porte `shoot_result` et paie le tir ; le step
    `CHOICE_k` (résultat `shoot` sans tir) ne paie rien — décider n'est pas récompensé."""
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rules=[_MOVE_AFTER_SHOOTING_RULE]),
        _unit_cfg(2, 2, [(20, 10)]),
    ])
    gs = eng.game_state
    rc = _reward_calculator(eng)

    _success, shot = _shoot(eng)
    shot_reward = rc.calculate_reward(True, shot, gs)
    assert shot_reward > 0.0, "un tir à portée doit payer son espérance de dégâts à CE step"

    _success, choice = eng._handle_agent_decision_action({"option_index": 0})
    choice_reward = rc.calculate_reward(True, choice, gs)
    assert choice_reward == 0.0, choice


def test_a_squad_without_the_rule_ends_its_activation_as_before():
    """Contrôle : sans porteur, le chemin direct clôt l'activation au step du tir."""
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)]),
        _unit_cfg(2, 2, [(20, 10)]),
    ])
    gs = eng.game_state

    success, result = _shoot(eng)

    assert success is True
    assert result["action"] == "squad_shoot"
    assert result["activation_ended"] is True
    assert read_pending_agent_decision(gs) is None
    assert gs["shoot_activation_pool"] == []
    assert "1" in gs["units_shot"]


# ── Indiscriminate Detonations : la suppression atteint le gym ───────────────────────────


def test_gym_squad_shoot_suppresses_the_target(monkeypatch):
    """ROUGE avant le fix : `suppressed_squads` restait vide sur le chemin gym. Dés épinglés à 6 :
    depuis le 2026-09-18 seule une escouade TOUCHÉE peut être supprimée."""
    import random

    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rules=[_SUPPRESS_RULE]),
        _unit_cfg(2, 2, [(20, 10)]),
    ])
    gs = eng.game_state

    success, result = _shoot(eng)

    assert success is True
    assert result["activation_ended"] is True
    assert gs["suppressed_squads"] == {"2": 1}


def test_split_fire_end_also_suppresses_the_target(monkeypatch):
    """Le tir fractionné (`squad_shoot_split_target`, deux armes → deux cibles) termine par la
    même fin de datasheet. Dés à 6 : les DEUX cibles sont touchées, donc la fin d'activation pose
    la décision `suppress_target` (2026-09-18 — le moteur ne choisit plus la première déclarée) ;
    l'agent joue le candidat de l'escouade 3, qui est supprimée et l'activation se clôt.
    D 1 sur le lascannon : une escouade DÉTRUITE par le tir n'est plus une candidate."""
    import random

    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    bolter = _weapon("bolter", rng=24)
    lascannon = _weapon("lascannon", rng=48, STR=12, AP=-3, DMG=1)
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rng_weapons=[bolter, lascannon], rules=[_SUPPRESS_RULE]),
        _unit_cfg(2, 2, [(20, 10)]),
        _unit_cfg(3, 2, [(30, 10)]),
    ])
    gs = eng.game_state
    with patch.object(RewardCalculator, "calculate_reward", return_value=0.0):
        # Arme 1 → cible du slot 1 (escouade 3), arme 2 → cible du slot 0 (escouade 2) : la
        # première déclarée est l'escouade 3. La résolution du second couple vide le pool et la
        # cascade avance la phase — l'activation est close par construction.
        for target_slot in (1, 0):
            mask, _pool = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)
            weapon_actions = [
                i for i, opened in enumerate(mask)
                if opened and i >= SHOOT_WEAPON_SEL_SLOT_BASE
            ]
            assert weapon_actions, "aucun SHOOT_WEAPON_SEL ouvert"
            eng.step_with_mask(int(weapon_actions[0]))
            pending = gs["pending_shoot_weapon_split"]
            assert target_slot in pending["eligible_target_slots"]
            _obs, _r, _t, _tr, info, _m = eng.step_with_mask(int(SHOOT_SLOT_BASE + target_slot))
            assert info["action"] == "squad_shoot_split_target", info
        assert gs.get("pending_shoot_weapon_split") is None
        decision = read_pending_agent_decision(gs)
        assert decision is not None and decision["type"] == "suppress_target", decision
        assert gs["suppressed_squads"] == {}, "rien n'est supprimé avant la réponse"
        targets = [o["payload"]["target_eid"] for o in decision["options"]]
        assert sorted(targets) == ["2", "3"]
        from engine.macro_intents import CHOICE_BASE
        eng.step_with_mask(int(CHOICE_BASE + targets.index("3")))
    assert read_pending_agent_decision(gs) is None
    assert gs["phase"] != "shoot" or "1" not in gs.get("shoot_activation_pool", ["1"])
    assert gs["suppressed_squads"] == {"3": 1}


def test_the_suppress_choice_pays_nothing_through_the_real_reward(monkeypatch):
    """Le step `CHOICE_k` de `suppress_target` traverse le VRAI barème et paie zéro.

    ROUGE avant le fix (2026-09-18) : la réponse était renommée `squad_shoot` sans `shoot_result`,
    et `RewardCalculator` levait `ConfigurationError` (`require_key`) sur le chemin gym — les
    autres tests de ce fichier neutralisent `calculate_reward`, ils ne pouvaient pas le voir.
    Même contrat que `move_after_shooting` : le tir est payé au step du tir, décider ne paie rien."""
    import random

    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    bolter = _weapon("bolter", rng=24)
    lascannon = _weapon("lascannon", rng=48, STR=12, AP=-3, DMG=1)
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rng_weapons=[bolter, lascannon], rules=[_SUPPRESS_RULE]),
        _unit_cfg(2, 2, [(20, 10)]),
        _unit_cfg(3, 2, [(30, 10)]),
    ])
    gs = eng.game_state
    rc = _reward_calculator(eng)
    shot_rewards: List[float] = []
    for target_slot in (1, 0):
        mask, _pool = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)
        weapon_actions = [
            i for i, opened in enumerate(mask) if opened and i >= SHOOT_WEAPON_SEL_SLOT_BASE
        ]
        assert weapon_actions, "aucun SHOOT_WEAPON_SEL ouvert"
        eng._process_squad_action(eng.action_decoder.convert_squad_action(int(weapon_actions[0]), gs, _pool))
        _success, shot = eng._process_squad_action(
            eng.action_decoder.convert_squad_action(int(SHOOT_SLOT_BASE + target_slot), gs)
        )
        shot_rewards.append(rc.calculate_reward(True, shot, gs))
    assert any(r > 0.0 for r in shot_rewards), "un tir à portée doit payer son espérance"
    decision = read_pending_agent_decision(gs)
    assert decision is not None and decision["type"] == "suppress_target", decision

    _success, choice = eng._handle_agent_decision_action({"option_index": 0})

    assert rc.calculate_reward(True, choice, gs) == 0.0
    assert choice["action"] == "shoot", choice
    assert "shoot_result" not in choice
    assert choice["decision_type"] == "suppress_target"
    assert choice["activation_ended"] is True
    assert read_pending_agent_decision(gs) is None
    assert gs["suppressed_squads"] == {decision["options"][0]["payload"]["target_eid"]: 1}


# ── Bot PvE : la décision est répondue dans la MÊME requête, par la politique ────────────


def test_pve_bot_answers_its_own_decision_in_the_same_request():
    """Le bot PvE (joueur 2 sous `pve_mode`) n'a aucun canal `CHOICE_k` : la réponse vient de sa
    politique (`pve_controller.make_ai_decision`) avant que la requête ne rende la main. Ici la
    politique est simulée par le candidat 0 (« Pression ») ; ce qui est vérifié est le CÂBLAGE —
    aucune décision ne survit à la requête, l'escouade a bougé et son activation est close."""
    eng = _engine([
        _unit_cfg(1, 2, [(10, 10)], rules=[_MOVE_AFTER_SHOOTING_RULE]),
        _unit_cfg(2, 1, [(20, 10)]),
    ], pve=True)
    gs = eng.game_state
    gs["current_player"] = 2
    gs["player_types"] = {"1": "human", "2": "ai"}
    shooting_handlers.shooting_phase_start(gs)
    before = _position(eng, "1")

    class _Policy:
        calls: List[Dict[str, Any]] = []

        def is_ready_for_decision(self) -> bool:
            return True

        def make_ai_decision(self, game_state: Dict[str, Any], engine: Any) -> Dict[str, Any]:
            decision = read_pending_agent_decision(game_state)
            assert decision is not None and decision["type"] == "move_after_shooting"
            self.calls.append(dict(decision))
            return {"action": "agent_decision", "option_index": 0}

    eng.pve_controller = _Policy()  # type: ignore[assignment]  # politique simulée
    success, result = _shoot(eng)

    assert success is True
    assert len(_Policy.calls) == 1, "la politique doit être interrogée une fois, dans la requête"
    assert read_pending_agent_decision(gs) is None
    assert _position(eng, "1") != before
    assert "1" in gs["units_cannot_charge"]
    assert gs["shoot_activation_pool"] == []
    # Le payload rendu au client reflète l'état FINAL : plus d'attente, activation close, tir
    # conservé. La boucle IA du front sort sur `waiting_for_player` sans savoir répondre.
    assert result["action"] == "squad_shoot"
    assert "shoot_result" in result
    assert result["waiting_for_player"] is False
    assert result["activation_ended"] is True
    assert (result["toCol"], result["toRow"]) == _position(eng, "1")
    # Dernier tireur du pool : la fin d'activation de la réponse porte `phase_complete`, et la
    # cascade de `_process_squad_action` avance la phase comme pour un tir sans décision.
    assert result["phase_complete"] is True
    assert gs["phase"] != "shoot"
