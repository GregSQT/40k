"""`SelfPlayWrapper` rend à P0 la SOMME des récompenses de tous les steps moteur du step gym.

Le moteur rend la récompense du joueur CONTRÔLÉ à chaque step, y compris ceux joués par
l'adversaire : pénalité défensive des tirs adverses, et depuis B6 le ledger de marge de VP
(`vp_margin_paid`), qui avance à chaque step où les VP bougent, quel que soit `current_player`.
`BotControlledEnv` accumule (`accumulate_reward=True`) ; `SelfPlayWrapper` ne gardait que le
step TERMINAL de P1 et jetait les autres — le ledger avançait, l'agent ne touchait rien, et la
somme téléscopique « 6 × marge finale » était fausse sur le chemin self-play pur
(`ai/train.py`, branche sans bots). Mesure avant correction, 4 parties aléatoires : vp_margin
perdu +180 / +270 / +120 / +180.

Trois montages : P1 joue AVANT l'action de P0 (reprise de main en début de step gym), P1 joue
APRÈS, et P1 termine la partie après — chaque step de P1 porte une récompense non nulle et
non terminale, qui doit se retrouver dans la récompense rendue.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ai.env_wrappers import SelfPlayWrapper
from tests.unit.ai.test_wrapper_agent_step_info import _ScriptedDecoder
from tests.unit.ai.test_env_wrappers import _DummyEngine


class _RewardScriptedEngine(_DummyEngine):
    """Moteur double : une entrée par step moteur → (récompense de P0, joueur suivant, fin)."""

    def __init__(self, script: List[Dict[str, Any]], first_player: int = 1) -> None:
        super().__init__(decoder=None)
        self.action_decoder = _ScriptedDecoder(self)
        self._script = script
        self.steps_taken = 0
        self.game_state["current_player"] = first_player
        self.game_state["phase"] = "shoot"

    def step_with_mask(self, action, mask_and_eligible=None) -> tuple:
        _ = (action, mask_and_eligible)
        if self.steps_taken >= len(self._script):
            raise AssertionError("le montage a joué plus de steps moteur que le script n'en prévoit")
        entry = self._script[self.steps_taken]
        self.steps_taken += 1
        self.game_state["current_player"] = int(entry["next_player"])
        obs, out_mask = self._step_observation()
        terminated = bool(entry.get("terminated", False))
        info: Dict[str, Any] = {"winner": entry.get("winner")} if terminated else {}
        return obs, float(entry["reward"]), terminated, False, info, out_mask


def _wrapper(engine: _RewardScriptedEngine) -> SelfPlayWrapper:
    return SelfPlayWrapper(engine, frozen_model=None, update_frequency=100, allow_random_opponent=True)


def test_les_recompenses_des_steps_de_p1_apres_p0_sont_additionnees() -> None:
    """P0 agit (+1), P1 rejoue deux fois (−6 puis −6, ledger de marge : deux VP cédés), la main
    revient à P0 : la récompense rendue vaut 1 − 12, pas 1.

    VERROU. Revenir à « seul le step terminal de P1 compte » rend 1.0 → ROUGE constaté.
    """
    engine = _RewardScriptedEngine([
        {"reward": 1.0, "next_player": 2},
        {"reward": -6.0, "next_player": 2},
        {"reward": -6.0, "next_player": 1},
    ])
    wrapper = _wrapper(engine)

    _obs, reward, terminated, _truncated, _info = wrapper.step(4)

    assert engine.steps_taken == 3, "le montage doit faire rejouer P1 deux fois APRÈS P0"
    assert not terminated
    assert reward == -11.0
    assert wrapper.episode_reward == -11.0


def test_les_recompenses_des_steps_de_p1_avant_p0_sont_additionnees() -> None:
    """La main est à P1 à l'entrée du step gym : P1 joue (−6), puis P0 agit (+2), P1 rejoue (+0).

    C'était le trou de la boucle « P1 before » : elle ne gardait la récompense que si P1
    TERMINAIT la partie. Ici P1 ne la termine pas et son −6 doit quand même être rendu.
    """
    engine = _RewardScriptedEngine([
        {"reward": -6.0, "next_player": 1},   # P1 joue avant P0
        {"reward": 2.0, "next_player": 2},    # action de P0
        {"reward": 0.0, "next_player": 1},    # P1 rejoue
    ], first_player=2)
    wrapper = _wrapper(engine)

    _obs, reward, _terminated, _truncated, _info = wrapper.step(4)

    assert engine.steps_taken == 3
    assert reward == -4.0
    assert wrapper.episode_reward == -4.0


def test_le_step_terminal_de_p1_reste_compte_avec_les_precedents() -> None:
    """P0 agit (+1), P1 joue un step non terminal (−6) puis termine la partie (−50) :
    la récompense rendue additionne les trois, et `winner` est lu sur le dernier info."""
    engine = _RewardScriptedEngine([
        {"reward": 1.0, "next_player": 2},
        {"reward": -6.0, "next_player": 2},
        {"reward": -50.0, "next_player": 2, "terminated": True, "winner": 2},
    ])
    wrapper = _wrapper(engine)

    _obs, reward, terminated, _truncated, info = wrapper.step(4)

    assert terminated
    assert reward == -55.0
    assert info["winner"] == 2
    assert wrapper.player2_wins == 1
