"""Verrouille l'invariant sans lequel la sonde de départ de zone ment.

Le défaut qui a motivé ces tests (2026-08-13) : le contrefactuel repartait de l'état des
générateurs d'APRÈS l'appel réel. Les bots tirent à chaque décision (`bot_eval_randomness` =
0.05), donc le contrefactuel voyait d'autres tirages et prenait la branche aléatoire quand
l'appel réel ne l'avait pas prise. Conséquence mesurée : `scorer`, dont `w_enemy` vaut DÉJÀ 0.0,
rendait 20,5 % de départs « retenus » par un contrefactuel qui ne changeait rien.

L'invariant testé est exactement celui que le témoin naturel constate en production :
**neutraliser un terme qui vaut déjà zéro doit rendre la MÊME décision.**
"""
from __future__ import annotations

import random
from types import SimpleNamespace
from typing import Any, List, Tuple

import numpy as np

from tests._chargeur_script import charger_script

_SCRIPT = charger_script("scripts/bot_zone_leave_probe.py")


class _BotTireur:
    """Bot factice dont la décision DÉPEND d'un tirage, comme les vrais (`randomness`).

    Sans cette dépendance le test serait vert quoi que fasse la sonde : c'est précisément le
    tirage qui rendait les deux appels divergents.
    """

    def __init__(self, poids: Tuple[float, ...]):
        self._poids = poids
        self.etat_mute = 0

    def movement_weights(self, unit: Any, game_state: Any) -> Tuple[float, ...]:
        return self._poids

    def select_movement_destination(
        self, unit: Any, valid_destinations: List[Tuple[int, int]], game_state: Any = None
    ) -> Tuple[int, int]:
        w = self.movement_weights(unit, game_state)
        # Écriture d'état, comme `DecapitationBot._enemy_anchors` écrit `_focus_target`.
        self.etat_mute += 1
        tirage = random.random()
        index = int(tirage * len(valid_destinations)) % len(valid_destinations)
        # Le poids d'indice 1 décale le choix : un contrefactuel qui le met à 0 change la
        # destination SI et seulement si ce poids n'était pas déjà nul.
        return valid_destinations[(index + int(w[1] * 2)) % len(valid_destinations)]


_DESTS = [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)]


def _rejoue(bot: Any, index: int) -> Tuple[int, int]:
    pre = (random.getstate(), np.random.get_state())
    reel = bot.select_movement_destination(None, _DESTS, {})
    contrefactuel = _SCRIPT._counterfactual_choice(
        bot, bot.select_movement_destination, bot.movement_weights,
        None, _DESTS, {}, index, pre,
    )
    return reel, contrefactuel


def test_neutraliser_un_terme_deja_nul_rend_la_meme_decision():
    """LE témoin : `scorer` a w_enemy = 0.0, sa case du tableau doit valoir 0,0 %."""
    bot = _BotTireur((1.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    ecarts = 0
    for graine in range(200):
        random.seed(graine)
        reel, contrefactuel = _rejoue(bot, index=1)
        ecarts += reel != contrefactuel
    assert ecarts == 0, (
        f"{ecarts}/200 décisions divergent alors que le terme neutralisé valait déjà 0 : les "
        "générateurs ne sont pas réalignés sur l'état d'AVANT l'appel réel."
    )


def test_neutraliser_un_terme_actif_change_bien_la_decision():
    """VERT VACANT : sans ce test, une sonde qui rendrait toujours la décision réelle passerait
    le test ci-dessus sans rien mesurer."""
    bot = _BotTireur((1.0, 1.5, 0.0, 0.0, 0.0, 0.0))
    ecarts = 0
    for graine in range(200):
        random.seed(graine)
        reel, contrefactuel = _rejoue(bot, index=1)
        ecarts += reel != contrefactuel
    assert ecarts == 200


def test_le_contrefactuel_ne_laisse_ni_poids_ni_etat_derriere():
    """Le contrefactuel doit être transparent : ni `movement_weights` remplacé, ni état muté."""
    bot = _BotTireur((1.0, 1.5, 0.0, 0.0, 0.0, 0.0))
    random.seed(7)
    poids_avant = bot.movement_weights(None, {})
    bot.select_movement_destination(None, _DESTS, {})
    etat_apres_appel_reel = bot.etat_mute
    pre = (random.getstate(), np.random.get_state())

    _SCRIPT._counterfactual_choice(
        bot, bot.select_movement_destination, bot.movement_weights,
        None, _DESTS, {}, 1, pre,
    )

    assert bot.movement_weights(None, {}) == poids_avant
    assert bot.etat_mute == etat_apres_appel_reel


def test_zone_index_classe_par_ancre():
    zones = [{(0, 0), (0, 1)}, {(5, 5)}]
    assert _SCRIPT.zone_index((0, 1), zones) == 0
    assert _SCRIPT.zone_index((5, 5), zones) == 1
    assert _SCRIPT.zone_index((9, 9), zones) is None
