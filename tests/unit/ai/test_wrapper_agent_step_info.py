"""Tests — l'`info` rendu par les wrappers decrit l'action de l'AGENT, pas celle de l'adversaire.

CE QUI A ETE MANQUE. Un step gym enchaine plusieurs steps MOTEUR : l'action de l'agent, puis
ceux de l'adversaire jusqu'au retour de la main. Gym n'a qu'un `info` a rendre, et c'est
naturellement celui du DERNIER step moteur — donc celui de l'adversaire. `BotControlledEnv` ne
reportait que trois cles (`action`, `intent_value`, `is_controlled_action`) et `SelfPlayWrapper`
aucune. Les consommateurs lisent pourtant `phase`, `success` et `charge_succeeded` comme
decrivant l'agent, puisqu'elles cotoient `is_controlled_action` :

  * `obs/*_best_kill_probability` et ses voisines rangeaient l'echantillon sous la phase du BOT
    (une charge de l'agent comptee en `shoot` si le bot tirait ensuite) ;
  * `combat/c_charge_successes` comptait les charges reussies du BOT, sous le drapeau de l'agent.

Ces cles sont OPTIONNELLES par nature — le moteur ne les pose que quand elles s'appliquent —
donc leur absence porte autant d'information que leur valeur : le report doit les REMPLACER en
bloc, pas se contenter d'ecraser celles qui existent des deux cotes.

POURQUOI AUCUN TEST NE L'A VU : aucun n'exercait un step gym ou l'adversaire rejoue APRES
l'agent — le seul cas ou les deux infos different.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from ai.env_wrappers import AGENT_STEP_INFO_KEYS, BotControlledEnv, SelfPlayWrapper
from tests.unit.ai.test_env_wrappers import _DummyBot, _DummyEngine


class _ScriptedDecoder:
    """Decodeur dont le pool d'unites eligibles suit le joueur courant du moteur double.

    C'est `eligible_units[0]["player"]` qui decide a qui appartient le tour
    (`BotControlledEnv._decision_from_mask`) : scripter le joueur courant suffit donc a piloter
    l'enchainement agent -> adversaire -> agent.
    """

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def get_squad_action_mask_and_eligible_units(self, game_state):
        mask = [False] * 12
        mask[4] = True
        return mask, [{"id": "u1", "player": int(game_state["current_player"])}]

    def normalize_action_input(self, raw_action, phase, source, action_space_size):
        _ = (phase, source, action_space_size)
        return int(raw_action)

    def validate_action_against_mask(self, action_int, action_mask, phase, source, unit_id):
        _ = (action_int, action_mask, phase, source, unit_id)


class _ScriptedEngine(_DummyEngine):
    """Moteur double qui joue une SEQUENCE d'infos, un par step moteur.

    Chaque entree du script donne l'`info` rendu et le joueur courant APRES le step. Le dernier
    info du script est celui que gym rendrait sans report — c'est exactement ce que les tests
    doivent voir corrige.
    """

    def __init__(self, script: List[Dict[str, Any]]) -> None:
        super().__init__(decoder=None)
        self.action_decoder = _ScriptedDecoder(self)
        self._script = script
        self.steps_taken = 0
        self.game_state["current_player"] = 1
        # Phase de TIR : en phase move, le choix du bot passe par la carte de cellules memoisee
        # du vrai moteur, que ce double ne construit pas. Le tir suffit — ce qui est teste ici
        # est le report de l'info, pas le decodage d'une destination.
        self.game_state["phase"] = "shoot"

    def step_with_mask(self, action, mask_and_eligible=None) -> tuple:
        _ = (action, mask_and_eligible)
        if self.steps_taken >= len(self._script):
            raise AssertionError("le montage a joue plus de steps moteur que le script n'en prevoit")
        entry = self._script[self.steps_taken]
        self.steps_taken += 1
        self.game_state["current_player"] = int(entry["next_player"])
        obs, out_mask = self._step_observation()
        return obs, 0.0, False, False, dict(entry["info"]), out_mask

    def step(self, action) -> tuple:
        obs, reward, terminated, truncated, info, _mask = self.step_with_mask(action)
        return obs, reward, terminated, truncated, info


_AGENT_STEP_INFO = {
    "action": "charge",
    "is_controlled_action": True,
    "phase": "charge",
    "success": True,
    "charge_succeeded": True,
}

_OPPONENT_STEP_INFO = {
    "action": "shoot",
    "is_controlled_action": False,
    "phase": "shoot",
    "success": False,
}


def test_bot_controlled_env_returns_the_agent_step_info() -> None:
    """L'agent charge, le bot tire ensuite : l'info rendu doit decrire la CHARGE."""
    engine = _ScriptedEngine([
        {"info": _AGENT_STEP_INFO, "next_player": 2},      # action de l'agent
        {"info": _OPPONENT_STEP_INFO, "next_player": 1},   # le bot rejoue derriere
    ])
    wrapper = BotControlledEnv(engine, bot=_DummyBot(action=4), agent_seat_mode="p1")

    _obs, _reward, _terminated, _truncated, info = wrapper.step(4)

    assert engine.steps_taken == 2, "le montage doit faire rejouer l'adversaire APRES l'agent"
    assert info["phase"] == "charge", "la phase rendue est celle du bot, pas celle de l'agent"
    assert info["charge_succeeded"] is True
    assert info["success"] is True
    assert info["is_controlled_action"] is True
    assert info["action"] == "charge"


def test_bot_controlled_env_keeps_the_last_engine_state_keys() -> None:
    """Le report ne doit PAS ecraser ce qui decrit l'etat de SORTIE du step gym.

    `winner`, `episode`, `tactical_data` sont poses par le dernier step moteur et c'est bien lui
    qui fait foi : reporter l'info de l'agent en bloc les ferait disparaitre.
    """
    opponent_info = dict(_OPPONENT_STEP_INFO)
    opponent_info["tactical_data"] = {"marker": 1}
    engine = _ScriptedEngine([
        {"info": _AGENT_STEP_INFO, "next_player": 2},
        {"info": opponent_info, "next_player": 1},
    ])
    wrapper = BotControlledEnv(engine, bot=_DummyBot(action=4), agent_seat_mode="p1")

    _obs, _reward, _terminated, _truncated, info = wrapper.step(4)

    assert info["tactical_data"] == {"marker": 1}
    assert "tactical_data" not in AGENT_STEP_INFO_KEYS


def test_self_play_wrapper_returns_the_agent_step_info() -> None:
    """Meme regle cote self-play : P1 rejoue apres P0, l'info rendu decrit P0."""
    engine = _ScriptedEngine([
        {"info": _AGENT_STEP_INFO, "next_player": 2},      # action de P0 (l'agent)
        {"info": _OPPONENT_STEP_INFO, "next_player": 1},   # P1 (modele gele) rejoue derriere
    ])
    wrapper = SelfPlayWrapper(
        engine, frozen_model=None, update_frequency=100, allow_random_opponent=True
    )

    _obs, _reward, _terminated, _truncated, info = wrapper.step(4)

    assert engine.steps_taken == 2, "le montage doit faire rejouer P1 APRES P0"
    assert info["phase"] == "charge"
    assert info["charge_succeeded"] is True
    assert info["is_controlled_action"] is True


def test_a_key_absent_from_the_agent_step_does_not_survive_from_the_opponent() -> None:
    """L'agent TIRE (pas de `charge_succeeded`), le bot enchaine sur une charge reussie.

    Un simple `update` laisserait le `charge_succeeded=True` du bot en place, sous le
    `is_controlled_action=True` de l'agent — et la charge du bot serait comptee comme celle de
    l'agent, exactement la metrique que ce report existe pour corriger.
    """
    agent_shoots = {
        "action": "shoot",
        "is_controlled_action": True,
        "phase": "shoot",
        "success": True,
    }
    opponent_charges = {
        "action": "charge",
        "is_controlled_action": False,
        "phase": "charge",
        "success": True,
        "charge_succeeded": True,
    }
    engine = _ScriptedEngine([
        {"info": agent_shoots, "next_player": 2},
        {"info": opponent_charges, "next_player": 1},
    ])
    wrapper = BotControlledEnv(engine, bot=_DummyBot(action=4), agent_seat_mode="p1")

    _obs, _reward, _terminated, _truncated, info = wrapper.step(4)

    assert "charge_succeeded" not in info, (
        "la charge de l'adversaire ne doit pas survivre sous le drapeau de l'agent"
    )
    assert info["phase"] == "shoot"


def test_zone_intent_keys_travel_together_through_the_wrapper() -> None:
    """
    `intent_value` et `zone_control` decrivent LE MEME free step : le contrat de survie doit
    les porter ensemble.

    Ne transporter que `intent_value` casse de deux facons, et les deux sont silencieuses au
    niveau du wrapper :
      * le callback lit `zone_control` avec `require_key` -> KeyError, entrainement interrompu ;
      * si l'ADVERSAIRE a joue un zone-intent, son `zone_control` survivrait a cote de
        l'`intent_value` de l'agent, sous `is_controlled_action=True` — un couple hybride qui
        fausserait I(intent ; controle) sans jamais lever.
    """
    agent_zone_intent = {
        "action": "zone_intent",
        "is_controlled_action": True,
        "phase": "command",
        "success": True,
        "intent_value": 1,
        "zone_control": 1.0,
    }
    opponent_zone_intent = {
        "action": "zone_intent",
        "is_controlled_action": False,
        "phase": "command",
        "success": True,
        "intent_value": 2,
        "zone_control": -1.0,
    }
    engine = _ScriptedEngine([
        {"info": agent_zone_intent, "next_player": 2},
        {"info": opponent_zone_intent, "next_player": 1},
    ])
    wrapper = BotControlledEnv(engine, bot=_DummyBot(action=4), agent_seat_mode="p1")

    _obs, _reward, _terminated, _truncated, info = wrapper.step(4)

    assert info["intent_value"] == 1
    assert info["zone_control"] == 1.0, (
        "le zone_control de l'adversaire a survecu sous le drapeau de l'agent"
    )


def test_zone_control_does_not_survive_when_the_agent_played_no_zone_intent() -> None:
    """
    Cle OPTIONNELLE : l'agent tire, l'adversaire joue un zone-intent derriere. Aucune des deux
    cles zone-intent ne doit subsister — sinon le tracker compterait un free step fantome.
    """
    agent_shoots = {
        "action": "shoot",
        "is_controlled_action": True,
        "phase": "shoot",
        "success": True,
    }
    opponent_zone_intent = {
        "action": "zone_intent",
        "is_controlled_action": False,
        "phase": "command",
        "success": True,
        "intent_value": 0,
        "zone_control": -1.0,
    }
    engine = _ScriptedEngine([
        {"info": agent_shoots, "next_player": 2},
        {"info": opponent_zone_intent, "next_player": 1},
    ])
    wrapper = BotControlledEnv(engine, bot=_DummyBot(action=4), agent_seat_mode="p1")

    _obs, _reward, _terminated, _truncated, info = wrapper.step(4)

    assert info["action"] == "shoot"
    assert "zone_control" not in info
    assert "intent_value" not in info
