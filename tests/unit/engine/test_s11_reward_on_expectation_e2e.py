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


def _make_env(reward_on_expectation: bool, agent_seat_mode: str = "p1"):
    """`agent_seat_mode` : "p1" ou "p2" — le siège de l'agent (BotControlledEnv le tire du mode)."""
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
    return BotControlledEnv(
        masked, RandomBot(), UnitRegistry(), agent_seat_mode=agent_seat_mode, env_rank=0
    )


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


@pytest.mark.parametrize("agent_seat_mode", ["p1", "p2"])
@pytest.mark.parametrize("seed", [42, 7])
def test_somme_vp_margin_egal_facteur_fois_marge_finale(agent_seat_mode: str, seed: int) -> None:
    """La somme des versements vp_margin sur toute la partie = factor × marge finale, DEUX sièges.

    Propriété télescopique (B6) : chaque appel à `_calculate_vp_margin_reward` verse
    factor × Δ(marge − filigrane). La somme = factor × (marge_finale − 0) puisque
    `vp_margin_paid` démarre à 0 au reset. Vérifiée sur un VRAI run moteur (deux joueurs,
    toutes transitions), pas sur des fixtures isolées.

    Trois verrous :
    (a) des VP ont été marqués — sans cela l'égalité 0 == 0 ne prouverait rien (vert vacant) ;
    (b) somme des versements == factor × marge finale ;
    (c) en siège p2, le marquage du SECOND joueur au round 5 tombe en fin de phase FIGHT
        (`config/primary_objective/Objectives_Control.json`, `timing.round5_second_player_phase`)
        et termine la partie : ce versement doit être vu sur le step terminal (turn 5, phase
        fight, game_over), c'est-à-dire par le step de la dernière action de l'agent, dont la
        cascade de phases franchit la frontière. La porte « pool vide → advance_phase » de
        `W40KEngine.step_with_mask`, autre chemin possible pour ce même versement, n'est PAS
        atteinte par ces graines : elle a son propre verrou,
        `test_terminal_info_all_paths.py::test_pool_empty_gate_pays_the_ledger_and_the_outcome`.

    Mutation rouge mesurée (2026-09-14) : filtre `current_player` réintroduit dans
    `_calculate_vp_margin_reward` → (b) rouge en siège p1 pour les deux graines — le dernier
    versement de la partie est celui de l'adversaire (round 5, phase fight) et il n'est jamais
    rattrapé. En siège p2 le même filtre ne fait que RETARDER les deltas adverses jusqu'au tour
    de l'agent, dont le versement est le dernier : la somme reste juste, c'est le verrou
    unitaire `test_objective_turn_reward.py::test_delta_adverse_verse_sans_filtre_current_player`
    qui le détecte par step.

    DÉPENDANCE À LA GRAINE, assumée et visible : le jeu est aléatoire des deux côtés (l'agent
    par `default_rng(seed)`, RandomBot par le module `random`, semé ici avec la même graine).
    Une graine qui donnerait une partie sans VP ou finie avant le round 5 rendrait (a) ou (c)
    ROUGE, jamais silencieusement vert — c'est le rôle de ces deux assertions. Les graines 42 et
    7 atteignent le round 5 avec des VP dans les deux sièges (mesuré le 2026-09-14).
    """
    import random

    from config_loader import get_config_loader

    env = _make_env(reward_on_expectation=True, agent_seat_mode=agent_seat_mode)
    cfg = get_config_loader().load_agent_rewards_config("ArmageddonAgent_x1")["ArmageddonAgent_x1"]
    factor = float(cfg["objective_rewards"]["vp_margin_factor"])

    calc = env.engine.reward_calculator
    original_cr = calc.calculate_reward
    vp_margin_total = 0.0
    last_vp: Dict[Any, float] = {}
    # Un triplet (turn, phase, game_over) par versement NON NUL, dans l'ordre du moteur.
    versements: List[tuple[int, str, bool]] = []

    def spy(success, result, game_state):
        nonlocal vp_margin_total, last_vp
        reward = original_cr(success, result, game_state)
        delta = float(require_key(require_key(game_state, "last_reward_breakdown"), "vp_margin"))
        vp_margin_total += delta
        if delta != 0.0:
            versements.append((
                int(require_key(game_state, "turn")),
                str(require_key(game_state, "phase")),
                bool(require_key(game_state, "game_over")),
            ))
        last_vp = {k: float(v) for k, v in require_key(game_state, "victory_points").items()}
        return reward

    calc.calculate_reward = spy  # type: ignore[method-assign]
    try:
        random.seed(seed)
        rng = np.random.default_rng(seed)
        env.reset(seed=seed)
        terminated = truncated = False
        while not (terminated or truncated):
            legal = np.flatnonzero(np.asarray(env.action_masks()))
            assert legal.size > 0
            _, _, terminated, truncated, _ = env.step(int(rng.choice(legal)))
    finally:
        calc.calculate_reward = original_cr  # type: ignore[method-assign]

    # Le siège est tiré par BotControlledEnv AU RESET (`agent_seat_mode`), pas à la construction.
    controlled = int(require_key(env.engine.reward_calculator.config, "controlled_player"))
    assert controlled == (1 if agent_seat_mode == "p1" else 2)
    opp = 2 if controlled == 1 else 1
    assert last_vp, "aucune transition de reward capturée : le test ne prouve rien"
    my_vp = last_vp[controlled]
    opp_vp = last_vp[opp]
    # (a) vert non vacant
    assert my_vp + opp_vp > 0, (
        f"partie sans VP (siège {agent_seat_mode}, graine {seed}) : l'égalité ne prouve rien"
    )
    # (b) télescopage
    final_margin = my_vp - opp_vp
    expected = factor * final_margin
    assert vp_margin_total == pytest.approx(expected, abs=0.01), (
        f"somme vp_margin {vp_margin_total:.4f} ≠ factor×marge_finale {expected:.4f} "
        f"(VP moi={my_vp}, lui={opp_vp}, marge={final_margin:.1f}, versements={versements})"
    )
    # (c) le marquage du second joueur en fin de round 5 est versé sur le step terminal
    gs = env.engine.game_state
    assert require_key(gs, "turn_limit_reached"), (
        f"partie finie avant le round 5 (siège {agent_seat_mode}, graine {seed}) : "
        f"le marquage du second joueur n'est pas exercé, changer de graine"
    )
    if agent_seat_mode == "p2":
        assert (5, "fight", True) in versements, (
            f"aucun versement vu sur le step terminal du round 5 en phase fight : {versements}"
        )
