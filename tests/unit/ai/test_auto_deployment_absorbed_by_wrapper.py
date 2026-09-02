"""Verrou : en mode `auto`, AUCUNE transition de déploiement du joueur contrôlé ne remonte à SB3.

CE QUE CE FICHIER EMPÊCHE. La rampe `deployment_mode_schedule` tire une part d'épisodes en mode
`auto` : le MOTEUR y choisit les poses du joueur-agent. Tant que ces steps traversaient
`W40KEngine.step` avec l'action de la politique, SB3 rangeait dans son rollout l'action
ÉCHANTILLONNÉE et son log_prob alors que la transition observée venait d'une AUTRE action — PPO
calculait son ratio sur une action jamais exécutée. ~10 steps de déploiement par épisode, sur la
part `auto` de la rampe (0.7 des épisodes en début de run).

La correction absorbe ces steps dans `BotControlledEnv._ensure_actionable_controlled_turn`, là où
les tours du bot et les `WAIT` forcés sont déjà joués sans être remontés. Le verrou porte donc sur
ce que l'APPRENANT voit, pas sur ce que le moteur fait : après `reset()` et après chaque `step()`,
un état rendu à la politique ne doit jamais être un déploiement du joueur contrôlé.

L'ancien mode `fixed` ne produisait aucune transition de déploiement : la régression est née avec
`auto` (2026-08-08), elle n'est pas préexistante.
"""

from __future__ import annotations

import os

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


def _make_engine(active_ratio: float):
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
    # `training_only: False` — le scénario de test n'a pas à porter le contexte d'entraînement pour
    # que la rampe s'applique ; `active_ratio` fixe le mode de TOUS les épisodes du test.
    engine.training_config["deployment_mode_schedule"] = {
        "enabled": True,
        "training_only": False,
        "active_ratio_start": active_ratio,
        "active_ratio_end": active_ratio,
        "schedule": "linear",
        "freeze_after_progress": 1.0,
    }
    return engine


def _make_wrapped_env(active_ratio: float):
    from sb3_contrib.common.wrappers import ActionMasker

    from ai.env_wrappers import BotControlledEnv
    from ai.evaluation_bots import RandomBot
    from ai.unit_registry import UnitRegistry

    engine = _make_engine(active_ratio)
    masked = ActionMasker(engine, lambda _env: engine.get_action_mask())
    return BotControlledEnv(
        masked,
        RandomBot(),
        UnitRegistry(),
        agent_seat_mode="p1",
        env_rank=0,
    )


def _assert_learner_state_is_not_a_controlled_deployment(env, where: str) -> None:
    gs = env.engine.game_state
    phase = str(require_key(gs, "phase"))
    if phase != "deployment":
        return
    # Le masque servi à PPO est celui de cet état : si le moteur y possède la pose, la transition
    # que SB3 va enregistrer n'est pas celle qu'il croit avoir choisie.
    mask = env.action_masks()
    owns_the_pose = env.engine._should_auto_deploy_for_agent(np.asarray(mask))
    assert not owns_the_pose, (
        f"{where} : l'apprenant reçoit un état de DÉPLOIEMENT dont le moteur choisit la pose "
        f"(mode={gs['deployment_mode_schedule_mode']!r}, current_player={gs['current_player']}, "
        f"controlled_player={env.controlled_player}). SB3 va ranger l'action échantillonnée et son "
        "log_prob pour une transition produite par une autre action."
    )


def test_auto_deployment_never_reaches_the_learner():
    """Un épisode complet en `auto` : rien de ce que l'apprenant voit n'est un déploiement à lui.

    Le test CONSTRUIT le cas (`active_ratio` 0.0 → tous les épisodes en `auto`) et vérifie qu'il
    a bien eu lieu : sans `_deployment_auto_steps > 0`, le moteur n'aurait rien posé et
    l'assertion principale serait vraie sans rien prouver (vert vacant).
    """
    env = _make_wrapped_env(0.0)
    env.reset(seed=11)
    gs = env.engine.game_state
    assert gs["deployment_mode_schedule_mode"] == "auto", "le mode 'auto' n'a pas été produit"
    _assert_learner_state_is_not_a_controlled_deployment(env, "après reset")

    rng = np.random.default_rng(3)
    steps = 0
    terminated = truncated = False
    while not (terminated or truncated) and steps < 60:
        legal = np.flatnonzero(np.asarray(env.action_masks()))
        assert legal.size > 0, f"masque vide servi à la politique au step {steps}"
        _obs, _reward, terminated, truncated, _info = env.step(int(rng.choice(legal)))
        steps += 1
        if not (terminated or truncated):
            _assert_learner_state_is_not_a_controlled_deployment(env, f"après step {steps}")

    assert steps > 0, "aucun step joué — test sans valeur"
    auto_steps = gs.get("_deployment_auto_steps", 0)
    assert auto_steps > 0, (
        "le moteur n'a posé AUCUNE figurine en mode 'auto' : l'absorption n'a rien absorbé et "
        "l'assertion principale est vraie pour la mauvaise raison"
    )


def test_active_mode_still_hands_deployment_to_the_policy():
    """Symétrique obligatoire : en `active`, le déploiement est la décision de l'agent.

    Une absorption trop large éteindrait la compétence que la rampe existe pour enseigner, et le
    test ci-dessus resterait vert.
    """
    env = _make_wrapped_env(1.0)
    env.reset(seed=11)
    gs = env.engine.game_state
    assert gs["deployment_mode_schedule_mode"] == "active"
    assert str(gs["phase"]) == "deployment", (
        "mode 'active' : la politique doit recevoir la main EN phase de déploiement"
    )
    assert int(gs["current_player"]) == env.controlled_player
    assert env.engine.auto_deployment_action(np.asarray(env.action_masks())) is None, (
        "le moteur s'approprie une pose alors que l'épisode est en mode 'active'"
    )


def test_the_armed_pose_is_the_one_executed():
    """`auto_deployment_action` arme la pose : `step` la rejoue, il n'en tire pas une seconde.

    Sans ce contrat, l'action rendue à l'appelant ne serait pas celle qui produit la transition —
    le défaut corrigé, déplacé d'un cran.
    """
    from engine.macro_intents import open_placement_slots

    engine = _make_engine(0.0)
    engine.reset(seed=5)
    gs = engine.game_state
    assert gs["deployment_mode_schedule_mode"] == "auto"
    assert str(gs["phase"]) == "deployment"

    mask = np.asarray(engine.get_action_mask())
    armed = engine.auto_deployment_action(mask)
    assert armed is not None, "état de déploiement `auto` : le moteur doit posséder la pose"
    assert armed in open_placement_slots([int(i) for i in np.flatnonzero(mask)]), (
        "la pose armée n'est pas un slot de POSE : ACTION_WAIT met l'unité en réserves (20.01)"
    )

    engine.auto_deployment_action(mask)  # ré-arme : la pose précédente est périmée
    other = next(
        (a for a in open_placement_slots([int(i) for i in np.flatnonzero(mask)])
         if a != engine._auto_deployment_pending_action),
        None,
    )
    if other is not None:
        with pytest.raises(RuntimeError, match="pose armée"):
            engine.step(int(other))
