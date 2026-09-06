"""Verrou : en mode `auto`, le moteur pose pour LES DEUX CAMPS, pas seulement pour l'agent.

CE QUE CE FICHIER EMPÊCHE. La rampe `deployment_mode_schedule` tire une part d'épisodes en mode
`auto`, où le MOTEUR choisit les poses. Jusqu'au 2026-09-06 cette substitution était bornée au
joueur contrôlé : l'agent était posé au hasard pendant que son adversaire — bot à doctrine, ou
champion du pool jouant son réseau — se déployait avec sa propre politique. Le mode `auto` était
donc un HANDICAP unilatéral, et la courbe de contrôle `r_win_rate_deploy_auto` ne mesurait pas ce
qu'elle prétend : « ce que vaut l'agent depuis des positions qu'il n'a pas choisies ».

MESURE du défaut (run x1_long du 2026-09-06, ~64 000 épisodes) : 0.304 de win-rate en `auto`
contre 0.684 en `active`, avec un différentiel d'objectifs de -0.76 en `auto` contre +0.19 en
`active`. La référence du 2026-08-12, prise contre des bots à doctrine de pose fixe, donnait
0.866 / 0.646 avec les deux différentiels positifs — l'écart s'est creusé quand l'adversaire est
devenu un modèle entraîné, capable d'exploiter une pose adverse médiocre.

Le verrou porte sur QUI est consulté : en `auto`, la politique de pose de l'adversaire ne doit
jamais être interrogée ; en `active`, elle doit l'être — sinon une substitution trop large aurait
éteint sa doctrine partout, et le premier test resterait vert pour la mauvaise raison.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import numpy as np

from shared.data_validation import require_key

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
SCENARIO = os.path.join(
    PROJECT_ROOT,
    "config/agents/ArmageddonAgent_x1/scenarios/training/scenario_training_armageddon1.json",
)


class _PlacementSpyBot:
    """`RandomBot` qui COMPTE les poses qu'on lui demande — le reste est délégué tel quel."""

    def __init__(self) -> None:
        from ai.evaluation_bots import RandomBot

        self._inner = RandomBot()
        self.placement_calls: List[List[int]] = []

    randomness = 1.0

    def select_placement_action(self, valid_actions: List[int], game_state) -> int:
        self.placement_calls.append(list(valid_actions))
        return self._inner.select_placement_action(valid_actions, game_state)

    def select_action_with_state(
        self, valid_actions: List[int], game_state, active_unit: Dict[str, Any]
    ) -> int:
        return self._inner.select_action_with_state(valid_actions, game_state, active_unit)

    def select_movement_destination(self, *args: Any, **kwargs: Any) -> Any:
        return self._inner.select_movement_destination(*args, **kwargs)


def _make_wrapped_env(active_ratio: float, bot: Any):
    from sb3_contrib.common.wrappers import ActionMasker

    from ai.env_wrappers import BotControlledEnv
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
    assert engine.training_config is not None
    engine.training_config = dict(engine.training_config)
    # `training_only: False` — le scénario de test n'a pas à porter le contexte d'entraînement
    # pour que la rampe s'applique ; `active_ratio` fixe le mode de TOUS les épisodes du test.
    engine.training_config["deployment_mode_schedule"] = {
        "enabled": True,
        "training_only": False,
        "active_ratio_start": active_ratio,
        "active_ratio_end": active_ratio,
        "schedule": "linear",
        "freeze_after_progress": 1.0,
    }
    masked = ActionMasker(engine, lambda _env: engine.get_action_mask())
    return BotControlledEnv(masked, bot, UnitRegistry(), agent_seat_mode="p1", env_rank=0)


def _play_until_deployment_is_over(env, seed: int, max_steps: int = 80) -> int:
    """Joue jusqu'à la sortie de la phase de déploiement. Rend le nombre de steps joués."""
    rng = np.random.default_rng(seed)
    steps = 0
    terminated = truncated = False
    while not (terminated or truncated) and steps < max_steps:
        if str(require_key(env.engine.game_state, "phase")) != "deployment":
            break
        legal = np.flatnonzero(np.asarray(env.action_masks()))
        assert legal.size > 0, f"masque vide servi à la politique au step {steps}"
        _obs, _reward, terminated, truncated, _info = env.step(int(rng.choice(legal)))
        steps += 1
    return steps


def test_auto_mode_never_asks_the_opponent_for_a_pose():
    """En `auto`, la doctrine de pose de l'adversaire n'est jamais consultée.

    Le test vérifie que le cas a bien eu lieu (`_deployment_auto_steps > 0` et des figurines
    posées des DEUX côtés) : sans ça, un déploiement qui ne se serait pas joué rendrait
    l'assertion principale vraie sans rien prouver.
    """
    spy = _PlacementSpyBot()
    env = _make_wrapped_env(0.0, spy)
    env.reset(seed=11)
    gs = env.engine.game_state
    assert gs["deployment_mode_schedule_mode"] == "auto", "le mode 'auto' n'a pas été produit"

    _play_until_deployment_is_over(env, seed=3)

    auto_steps = gs.get("_deployment_auto_steps", 0)
    assert auto_steps > 0, (
        "le moteur n'a posé AUCUNE figurine : le déploiement ne s'est pas joué et l'assertion "
        "principale serait vraie pour la mauvaise raison"
    )
    assert spy.placement_calls == [], (
        f"l'adversaire a été interrogé {len(spy.placement_calls)} fois pour une pose alors que "
        "l'épisode est en mode 'auto' : le moteur doit poser pour LES DEUX camps, sinon l'agent "
        "est seul handicapé et r_win_rate_deploy_auto mesure ce handicap, pas son adaptabilité"
    )


def test_active_mode_still_asks_the_opponent_for_its_pose():
    """Symétrique obligatoire : en `active`, la doctrine de pose de l'adversaire reste consultée.

    Une substitution trop large éteindrait la politique de placement des bots sur TOUS les
    épisodes — y compris les 85 % joués en `active` — et le test ci-dessus resterait vert.
    """
    spy = _PlacementSpyBot()
    env = _make_wrapped_env(1.0, spy)
    env.reset(seed=11)
    gs = env.engine.game_state
    assert gs["deployment_mode_schedule_mode"] == "active"

    _play_until_deployment_is_over(env, seed=3)

    assert spy.placement_calls, (
        "en mode 'active' l'adversaire n'a jamais choisi de pose : la substitution du mode 'auto' "
        "déborde sur les épisodes où chaque camp doit se déployer lui-même"
    )
    from engine.macro_intents import DEPLOY_STRATEGY_SLOTS

    for offered in spy.placement_calls:
        assert offered, "pool de poses vide proposé au bot"
        assert all(a in DEPLOY_STRATEGY_SLOTS for a in offered), (
            f"pool de poses hors slots de stratégie {list(DEPLOY_STRATEGY_SLOTS)} : {offered}. "
            "ACTION_WAIT au déploiement met l'unité en RÉSERVES (20.01), ce n'est pas une pose"
        )


def test_auto_mode_deploys_both_armies_on_the_board():
    """Les deux camps arrivent réellement sur la table, chacun avec ses propres tirages.

    `test_auto_mode_never_asks_the_opponent_for_a_pose` prouve que personne n'a demandé sa pose à
    l'adversaire ; il ne prouve pas que l'adversaire a été posé. Sans cette vérification, un
    moteur qui se contenterait de ne PAS déployer le camp adverse passerait le premier test.
    """
    spy = _PlacementSpyBot()
    env = _make_wrapped_env(0.0, spy)
    env.reset(seed=11)
    gs = env.engine.game_state
    assert gs["deployment_mode_schedule_mode"] == "auto"

    _play_until_deployment_is_over(env, seed=3)

    on_board = {1: 0, 2: 0}
    for unit in require_key(gs, "units"):
        player = int(require_key(unit, "player"))
        if unit.get("col") is not None and unit.get("row") is not None:
            on_board[player] += 1
    assert on_board[1] > 0 and on_board[2] > 0, (
        f"un camp n'a aucune figurine posée après le déploiement 'auto' : {on_board}"
    )
