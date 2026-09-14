"""Tests — l'`info` rendu par les wrappers decrit l'action de l'AGENT, pas celle de l'adversaire.

CE QUI A ETE MANQUE. Un step gym enchaine plusieurs steps MOTEUR : l'action de l'agent, puis
ceux de l'adversaire jusqu'au retour de la main. Gym n'a qu'un `info` a rendre, et c'est
naturellement celui du DERNIER step moteur — donc celui de l'adversaire. `BotControlledEnv` ne
reportait que trois cles (`action`, `intent_value`, `is_controlled_action`) et `SelfPlayWrapper`
aucune. Les consommateurs lisent pourtant `phase`, `success` et `charge_succeeded` comme
decrivant l'agent, puisqu'elles cotoient `is_controlled_action` :

  * `obs/*_best_kill_probability` et ses voisines rangeaient l'echantillon sous la phase du BOT
    (une charge de l'agent comptee en `shoot` si le bot tirait ensuite) — ces courbes ont depuis
    ete SUPPRIMEES (elles lisaient le vecteur plat mono-figurine, cf. `ai/training_callbacks.py`) ;
  * `combat/c_charge_successes` comptait les charges reussies du BOT, sous le drapeau de l'agent
    — depuis comptee cote moteur sur `action_logs`.

Les deux consommateurs d'origine sont donc partis, mais le report reste la GARANTIE que `phase`,
`success` et `charge_succeeded` decrivent bien l'agent : sans lui, le prochain lecteur retomberait
dans le meme trou sans le savoir.

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

    def activation_selection_slots(self, game_state, eligible_units=None):
        """Aucun choix d'activation en attente (V11 §0.48 `L2`) — pool scripté à une unité."""
        _ = (game_state, eligible_units)
        return None

    def normalize_action_input(self, raw_action, phase, source, action_space_size):
        _ = (phase, source, action_space_size)
        return int(raw_action)

    def validate_action_against_mask(self, action_int, action_mask, phase, source, unit_id):
        _ = (action_int, action_mask, phase, source, unit_id)


class _ScriptedEngine(_DummyEngine):
    """Moteur double qui joue une SEQUENCE d'entrees, une par step moteur.

    Chaque entree du script donne le joueur courant APRES le step (`next_player`, obligatoire)
    et, au choix : l'`info` rendu (le dernier du script est celui que gym rendrait sans report —
    c'est exactement ce que les tests doivent voir corrige), la recompense de P0 (`reward`,
    0.0 sinon), et la fin de partie (`terminated` + `winner`).
    """

    def __init__(self, script: List[Dict[str, Any]], first_player: int = 1) -> None:
        super().__init__(decoder=None)
        self.action_decoder = _ScriptedDecoder(self)
        self._script = script
        self.steps_taken = 0
        self.game_state["current_player"] = first_player
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
        terminated = bool(entry.get("terminated", False))
        info: Dict[str, Any] = dict(entry.get("info", {}))
        if terminated:
            info["winner"] = entry["winner"]
        return obs, float(entry.get("reward", 0.0)), terminated, False, info, out_mask

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


# Les deux tests des cles `intent_value` / `zone_control` vivaient ici. Ils sont partis le
# 2026-09-09 avec les intentions de zone : plus aucun step ne pose ces cles, et l'invariant
# qu'ils partageaient — une cle optionnelle posee par l'ADVERSAIRE ne survit pas sous le
# drapeau de l'agent — reste verrouille juste au-dessus par
# `test_a_key_absent_from_the_agent_step_does_not_survive_from_the_opponent`, sur
# `charge_succeeded`.
