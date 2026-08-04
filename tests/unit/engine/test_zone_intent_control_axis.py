"""
Verrou de l'axe conditionnel des metriques zone-intent : `info["zone_control"]`.

POURQUOI CE FICHIER EXISTE, ALORS QUE LE CALCUL EST DEJA TESTE AILLEURS.

`00_critical/o_intent_mutual_info` mesure I(intent ; controle de l'objectif). Si le moteur ne
publiait pas `zone_control`, ou s'il publiait une CONSTANTE, la mutual information vaudrait 0
bit en permanence — et 0 bit est exactement le diagnostic recherche ("la tete zone-intent
ignore l'etat du plateau"). Une metrique dont la valeur degeneree coincide avec sa conclusion
est un vert vacant : elle confirmerait le soupcon sans jamais l'avoir mesure.

Ce fichier joue donc le VRAI `step()` et exige que l'axe prenne plus d'une valeur.
Le premier jet de ce test a d'ailleurs observe 0.0 sur 68 free steps consecutifs : c'etait le
stub `_build_observation` du harnais voisin qui neutralisait le rafraichissement 14.02
(`refresh_objective_control_on_boundary`, porte par `_build_observation_and_mask`). D'ou
l'absence de tout stub d'observation ici — la deriver casserait silencieusement le controle.
"""

from __future__ import annotations

import collections
from typing import Dict, List
from unittest.mock import patch

import numpy as np

from engine.macro_intents import is_zone_intent_action
from engine.phase_handlers.shared_utils import SQUAD_ACTION_WAIT
from engine.reward_calculator import RewardCalculator
from engine.w40k_core import W40KEngine

# Harnais partage avec le fichier voisin (meme repertoire, donc importable) : un plateau a
# trois objectifs avec des figurines POSEES dessus au deploiement.
from test_objective_held_samples import _config
from tests.unit.engine._config_helpers import build_engine_config


def _engine() -> W40KEngine:
    """Moteur reel. Seules les RECOMPENSES sont neutralisees, jamais l'observation."""
    with patch.object(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 0.0), \
         patch.object(RewardCalculator, "settle_zone_intent_declaration", lambda self, *a, **kw: 0.0), \
         patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        engine = W40KEngine(config=build_engine_config(_config(1)), gym_training_mode=True, quiet=True)
        engine.reset()
        return engine


def _play_holding_position(engine: W40KEngine, max_steps: int = 2000) -> List[Dict[str, object]]:
    """
    Joue les free steps zone-intent et ATTEND sur tout le reste.

    Immobilite volontaire : sur actions aleatoires les figurines quittent les objectifs et le
    controle retombe a None partout — l'axe resterait plat sans qu'aucun defaut n'existe.
    """
    infos: List[Dict[str, object]] = []
    with patch.object(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 0.0), \
         patch.object(RewardCalculator, "settle_zone_intent_declaration", lambda self, *a, **kw: 0.0):
        for _ in range(max_steps):
            mask = engine.get_action_mask()
            legal = [int(a) for a in np.flatnonzero(mask)]
            zone_actions = [a for a in legal if is_zone_intent_action(a)]
            if zone_actions:
                action = zone_actions[0]
            elif mask[SQUAD_ACTION_WAIT]:
                action = SQUAD_ACTION_WAIT
            else:
                action = legal[0] if legal else SQUAD_ACTION_WAIT
            _obs, _reward, terminated, truncated, info = engine.step(int(action))
            if info.get("action") == "zone_intent":
                infos.append(info)
            if terminated or truncated:
                break
    return infos


def test_engine_publishes_zone_control_on_every_free_step() -> None:
    infos = _play_holding_position(_engine())

    assert infos, "aucun free step zone-intent joue : le test ne mesurerait rien"
    for info in infos:
        assert "zone_control" in info, (
            "le callback lit cette cle avec require_key : son absence rend la metrique muette"
        )
        assert info["zone_control"] in (-1.0, 0.0, 1.0)
        assert "intent_value" in info


def test_control_axis_is_not_degenerate_on_the_production_path() -> None:
    """
    L'axe doit VARIER. Une seule valeur observee => mutual information structurellement nulle,
    donc une metrique qui ne peut plus distinguer "rien appris" de "rien mesure".
    """
    infos = _play_holding_position(_engine())
    distribution = collections.Counter(info["zone_control"] for info in infos)

    assert sum(distribution.values()) >= 10, f"echantillon trop maigre: {dict(distribution)}"
    assert len(distribution) >= 2, (
        f"zone_control constant sur le chemin de production: {dict(distribution)}"
    )
    # 14.02 : aucune frontiere de phase franchie au tour 1 => aucun objectif controle, puis le
    # controle acquis au deploiement est conserve tant que personne ne bouge.
    assert distribution[0.0] > 0, "le tour 1 doit voir des objectifs non controles"
    assert distribution[1.0] > 0, "le controle acquis doit finir par etre vu par un free step"
