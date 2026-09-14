"""S11 sur le VRAI chemin d'entraînement — moteur, scénario, bot, actions légales tirées au hasard.

Ce que ce fichier prouve, et que les doublures de `test_shoot_attack_sequence.py` ne prouvaient
pas : le run S11 du 2026-09-14 10:29 est mort à sa première activation de tir sur
`Required key 'HP_MAX' is missing` — `_build_target_meta` lisait `units_cache[sid]["HP_MAX"]`,
présent dans les doublures et absent en production. Ici la partie est construite comme
`ai/train.py` la construit (`W40KEngine` + `ActionMasker` + `BotControlledEnv`), le bot et
l'agent jouent des actions légales tirées au hasard, et `RewardCalculator.calculate_reward` est
espionné sur le chemin réel : chaque activation de tir ou de mêlée (agent ET bot) y passe avec
son `shoot_result` / `fight_result` tel que le moteur l'a produit.

Deux verrous :
1. chaque résumé de combat porte `expected_damage_by_target` et des `targets_meta` complètes —
   sur des figurines réelles, et au moins une activation a une espérance strictement positive ;
2. avec `reward_on_expectation: true`, le terme `result_bonuses` du breakdown d'une activation
   offensive de l'agent est EXACTEMENT `_squad_combat_shaping` sur l'espérance, et diffère du
   calcul sur les événements réels sur au moins une activation.
"""
from __future__ import annotations

import copy
import os
from typing import Any, Dict, List

import numpy as np
import pytest

from shared.data_validation import require_key

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
SCENARIO = os.path.join(
    PROJECT_ROOT,
    "config/agents/ArmageddonAgent_x1/scenarios/training/scenario_training_armageddon1.json",
)
COMBAT_ACTIONS = ("squad_shoot", "squad_shoot_split_target", "squad_fight")


def _make_env(reward_on_expectation: bool):
    from sb3_contrib.common.wrappers import ActionMasker
    from ai.env_wrappers import BotControlledEnv
    from ai.evaluation_bots import RandomBot
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    engine = W40KEngine(
        rewards_config="ArmageddonAgent_x1",
        training_config_name="x1",
        controlled_agent="ArmageddonAgent_x1",
        scenario_file=SCENARIO,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,
    )
    # La clé S11 se pose sur une COPIE de la table chargée (le loader met la sienne en cache).
    rewards = copy.deepcopy(engine.reward_calculator.rewards_config)
    for agent_cfg in rewards.values():
        if isinstance(agent_cfg, dict) and "squad_shaping" in agent_cfg:
            agent_cfg["squad_shaping"]["reward_on_expectation"] = reward_on_expectation
    engine.reward_calculator.rewards_config = rewards
    masked = ActionMasker(engine, lambda _env: engine.get_action_mask())
    return BotControlledEnv(masked, RandomBot(), UnitRegistry(), agent_seat_mode="p1", env_rank=0)


def _play_and_spy(env, seed: int, max_steps: int) -> List[Dict[str, Any]]:
    """Actions légales au hasard ; espion sur `calculate_reward` (chemin réel du moteur)."""
    calc = env.engine.reward_calculator
    original = calc.calculate_reward
    captured: List[Dict[str, Any]] = []

    def spy(success: bool, result: Dict[str, Any], game_state: Dict[str, Any]) -> float:
        reward = original(success, result, game_state)
        action = result.get("action")  # get allowed : réponses système sans action
        res_key = "fight_result" if action == "squad_fight" else "shoot_result"
        # Un `squad_fight` intermédiaire (cible à choisir, allocation en attente) passe ici
        # sans résumé : seules les activations RÉSOLUES portent `fight_result` / `shoot_result`.
        if action in COMBAT_ACTIONS and isinstance(result.get(res_key), dict):  # get allowed
            captured.append({
                "action": action,
                "summary": copy.deepcopy(result[res_key]),
                "breakdown": copy.deepcopy(require_key(game_state, "last_reward_breakdown")),
                "acting_player": int(require_key(game_state["units_cache"].get(str(result.get("unitId")), {"player": -1}), "player"))
                if str(result.get("unitId")) in game_state["units_cache"] else -1,
                "reward": float(reward),
            })
        return reward

    calc.calculate_reward = spy  # type: ignore[method-assign]
    try:
        rng = np.random.default_rng(seed)
        env.reset(seed=seed)
        terminated = truncated = False
        steps = 0
        while not (terminated or truncated) and steps < max_steps:
            legal = np.flatnonzero(np.asarray(env.action_masks()))
            assert legal.size > 0
            _obs, _reward, terminated, truncated, _info = env.step(int(rng.choice(legal)))
            steps += 1
    finally:
        calc.calculate_reward = original  # type: ignore[method-assign]
    return captured


@pytest.mark.parametrize("seed", [11, 23])
def test_le_moteur_porte_l_esperance_sur_de_vraies_figurines(seed: int) -> None:
    env = _make_env(reward_on_expectation=True)
    captured = _play_and_spy(env, seed=seed, max_steps=500)
    assert captured, "aucune activation de tir/mêlée capturée : le test ne prouve rien"
    with_targets = [c["summary"] for c in captured if c["summary"]["expected_damage_by_target"]]
    assert with_targets, "aucune activation avec cible : le test ne prouve rien"
    for s in with_targets:
        for sid, exp in s["expected_damage_by_target"].items():
            assert exp >= 0.0
            meta = require_key(s["targets_meta"], sid)
            for key in ("alive_count", "hp_max", "hp_before", "points_per_hp_mean", "model_value_mean", "player"):
                assert key in meta, f"targets_meta[{sid}] sans {key}"
            assert meta["hp_max"] > 0 and meta["alive_count"] > 0 and meta["points_per_hp_mean"] > 0
    assert any(v > 0.0 for s in with_targets for v in s["expected_damage_by_target"].values()), (
        "aucune espérance strictement positive : aucune arme à portée sur 500 pas, suspect"
    )


def test_la_recompense_du_tir_est_l_esperance_pas_le_jet() -> None:
    """Clé à true : `result_bonuses` de chaque activation de l'AGENT vaut la formule sur
    l'espérance (à la pénalité défensive près, qui n'entre pas dans ce terme) ; la formule sur les
    événements réels en diffère sur au moins une activation."""
    from engine.reward_calculator import RewardCalculator

    env = _make_env(reward_on_expectation=True)
    controlled = int(require_key(env.engine.reward_calculator.config, "controlled_player"))
    shaping_on = require_key(require_key(env.engine.reward_calculator.rewards_config, "ArmageddonAgent_x1"), "squad_shaping")
    shaping_off = {**shaping_on, "reward_on_expectation": False}
    captured = _play_and_spy(env, seed=7, max_steps=500)
    agent_offensives = [
        c for c in captured
        if c["acting_player"] == controlled and c["summary"]["expected_damage_by_target"]
    ]
    assert agent_offensives, "aucune activation offensive de l'agent avec cible : le test ne prouve rien"

    calc = RewardCalculator(config={"quiet": True}, rewards_config={}, unit_registry=None, state_manager=None)
    n_differ = 0
    for c in agent_offensives:
        s = c["summary"]
        on = calc._squad_combat_shaping(s, lambda p: p != controlled, shaping_on)
        off = calc._squad_combat_shaping(s, lambda p: p != controlled, shaping_off)
        bonus = float(c["breakdown"]["result_bonuses"])
        # squad_fight ajoute `_fight_lowest_hp_wipe_bonus` au même terme : seul le tir est exact.
        if c["action"] != "squad_fight":
            assert bonus == pytest.approx(on), f"{c['action']} : result_bonuses {bonus} ≠ espérance {on}"
        if abs(on - off) > 1e-9:
            n_differ += 1
    assert n_differ > 0, "espérance et jet identiques sur toutes les activations de l'agent : suspect"


def test_somme_vp_margin_egal_facteur_fois_marge_finale() -> None:
    """La somme des versements vp_margin sur toute la partie = factor × marge finale.

    Propriété télescopique (B6) : chaque appel à _calculate_vp_margin_reward verse
    factor × Δ(marge − filigrane). La somme = factor × (marge_finale − 0) puisque
    vp_margin_paid démarre à 0 au reset. Vérifiée sur un VRAI run moteur (deux joueurs,
    toutes transitions), pas sur des fixtures isolées.

    VERROU. Un filtre current_player réintroduit dans _calculate_vp_margin_reward ferait
    rater la moitié des deltas (ceux du tour adverse) et romprait l'égalité.
    """
    from config_loader import get_config_loader

    env = _make_env(reward_on_expectation=True)
    controlled = int(require_key(env.engine.reward_calculator.config, "controlled_player"))
    opp = 2 if controlled == 1 else 1
    cfg = get_config_loader().load_agent_rewards_config("ArmageddonAgent_x1")["ArmageddonAgent_x1"]
    factor = float(cfg["objective_rewards"]["vp_margin_factor"])

    calc = env.engine.reward_calculator
    original_cr = calc.calculate_reward
    vp_margin_total = 0.0
    last_vp: Dict[Any, float] = {}

    def spy(success, result, game_state):
        nonlocal vp_margin_total, last_vp
        reward = original_cr(success, result, game_state)
        bd = game_state.get("last_reward_breakdown", {})
        vp_margin_total += float(bd.get("vp_margin", 0.0))
        last_vp = {k: float(v) for k, v in game_state.get("victory_points", {}).items()}
        return reward

    calc.calculate_reward = spy  # type: ignore[method-assign]
    try:
        rng = np.random.default_rng(42)
        env.reset(seed=42)
        terminated = truncated = False
        while not (terminated or truncated):
            legal = np.flatnonzero(np.asarray(env.action_masks()))
            assert legal.size > 0
            _, _, terminated, truncated, _ = env.step(int(rng.choice(legal)))
    finally:
        calc.calculate_reward = original_cr  # type: ignore[method-assign]

    assert last_vp, "aucune transition de reward capturée : le test ne prouve rien"
    final_margin = last_vp.get(controlled, 0.0) - last_vp.get(opp, 0.0)
    expected = factor * final_margin

    assert vp_margin_total == pytest.approx(expected, abs=0.01), (
        f"somme vp_margin {vp_margin_total:.4f} ≠ factor×marge_finale {expected:.4f} "
        f"(VP moi={last_vp.get(controlled)}, lui={last_vp.get(opp)}, marge={final_margin:.1f})"
    )
