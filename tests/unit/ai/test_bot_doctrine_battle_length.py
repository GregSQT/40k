"""La durée d'une bataille se LIT sur l'état, elle ne s'écrit pas en dur dans une doctrine.

`EndgameBot` bascule en mode « poussée » sur les derniers tours. Le seuil valait `PUSH_TURN = 3`,
déduit à la main de « la partie dure 5 tours » : sur un scénario plus court la bascule tombait
après la fin, sur un plus long elle transformait le style en Racer dès le premier tiers. La durée
vient désormais de `get_effective_turn_limit`, source unique de `game_rules.max_turns`.

Le même fichier verrouille le second défaut trouvé avec celui-là : `game_state.get("turn", 1)`,
un défaut posé pour éviter une `KeyError` (T1). Il faisait lire « avant la bascule » à un état sans
tour chez `EndgameBot`, et rendait le marqueur de tour CONSTANT chez `DecapitationBot` — qui gardait
alors la même cible focalisée toute la partie au lieu d'en changer à chaque tour.

⚠️ Le premier test est celui qui compte : il fixe que la bataille STANDARD n'a pas changé de
comportement. Une généralisation qui déplace le seuil sur 5 tours ne serait pas une correction,
ce serait un réglage déguisé — et tous les chiffres du panel seraient à rejouer.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from ai.bot_doctrines import DecapitationBot, EndgameBot


def _state(turn: int, max_turns: int = 5, **extra: Any) -> Dict[str, Any]:
    state: Dict[str, Any] = {
        "turn": turn,
        "config": {"game_rules": {"max_turns": max_turns}},
    }
    state.update(extra)
    return state


def test_the_standard_battle_still_pivots_on_turn_three() -> None:
    """LE verrou de non-régression : 5 tours ⇒ bascule au tour 3, comme l'ancien `PUSH_TURN = 3`.

    C'est le réglage mesuré le 2026-08-11 (0,025 → 0,562 sur le sous-tournoi). Le généraliser ne
    doit RIEN changer ici, sans quoi la correction serait un changement de doctrine déguisé.
    """
    bot = EndgameBot()

    assert [bot._pushing(_state(t)) for t in range(1, 6)] == [False, False, True, True, True]


def test_a_longer_battle_moves_the_pivot_instead_of_keeping_turn_three() -> None:
    """8 tours ⇒ bascule au tour 6, pas au tour 3.

    C'est LE test que la constante en dur ne peut pas passer : avec `PUSH_TURN = 3`, le bot
    poussait dès le tour 3 sur 8, soit les cinq huitièmes de la partie — il cessait d'être un
    style de tempo bas pour devenir un Racer tardif.
    """
    bot = EndgameBot()

    assert [bot._pushing(_state(t, 8)) for t in range(1, 9)] == [False] * 5 + [True] * 3


def test_a_battle_shorter_than_the_push_window_has_no_waiting_phase() -> None:
    """2 tours ⇒ il pousse d'emblée : il n'y a pas de fin de partie à attendre.

    Verrou du piège inverse : un seuil non borné vaudrait 0 ou un tour négatif, et avec
    `PUSH_TURN = 3` en dur le bot n'aurait JAMAIS poussé de la partie.
    """
    bot = EndgameBot()

    assert [bot._pushing(_state(t, 2)) for t in (1, 2)] == [True, True]


def test_an_endless_battle_raises_instead_of_inventing_a_pivot() -> None:
    """T1 : sans fin de partie, « jouer la fin de partie » n'a pas de sens — on lève."""
    bot = EndgameBot()

    with pytest.raises(ValueError, match="Endless Duty"):
        bot._pushing(_state(3, unlimited_turns=True))


def test_a_state_without_a_turn_raises_instead_of_reading_as_turn_one() -> None:
    """T1 : `game_state.get("turn", 1)` faisait lire « avant la bascule » à un état cassé."""
    bot = EndgameBot()

    with pytest.raises(Exception):
        bot._pushing({"config": {"game_rules": {"max_turns": 5}}})


def test_the_focus_marker_refuses_a_state_without_a_turn() -> None:
    """Jumeau du précédent chez `DecapitationBot`, et le plus coûteux des deux.

    Son marqueur de tour est `(episode, turn)` : avec un défaut à 1, il restait CONSTANT sur un
    état sans tour, donc le bot ne changeait jamais de cible focalisée — sa doctrine entière
    (« une escouade par tour, retirée entièrement ») s'annulait en silence.
    """
    with pytest.raises(Exception):
        DecapitationBot()._focus({"episode_number": 1})


def test_the_focus_marker_still_changes_between_turns() -> None:
    """VERT VACANT : vérifier que le marqueur BOUGE, pas seulement qu'il lève.

    Un test qui n'observe que les exceptions passerait sur un marqueur figé.
    """
    bot = DecapitationBot()
    bot._focus(_state(1, episode_number=7))
    first = bot._focus_turn
    bot._focus(_state(2, episode_number=7))

    assert first is not None and bot._focus_turn != first
