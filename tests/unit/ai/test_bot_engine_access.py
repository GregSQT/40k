"""Le moteur n'est remis qu'aux bots qui le DECLARENT — et la declaration doit etre honoree.

Un bot ne recoit d'ordinaire qu'une photo de la partie (`game_state`) : il ne peut rien simuler.
Le holdout d'evaluation (`ai/bot_holdout.LookaheadHoldoutBot`) doit, lui, essayer ses coups avant
de choisir, donc atteindre le moteur qui les joue.

POURQUOI UNE DECLARATION EXPLICITE ET PAS UN `hasattr`
    Le repli mou a deja coute une campagne entiere dans ce module : `_get_bot_action` testait
    `hasattr(bot, "select_action_with_state")`, et `TacticalBot`, faute de l'avoir, a joue la
    branche « phase inconnue » pendant TOUTE une evaluation sans que rien ne le signale. Un bot
    qui a besoin du moteur le dit par un attribut de CLASSE ; s'il le dit sans exposer
    `attach_engine`, on leve.

TROIS VOIES D'ARRIVEE, et il faut les trois : `bot=`, `bots=[...]` (l'adversaire est retire au
hasard a chaque episode) et `scripted_action_for_agent_side` (bot injecte au vol par le classement
bot-contre-bot). Une voie oubliee ne casse rien a la construction : elle produit un bot prive de
moteur qui levera au milieu d'une partie, ou pire, un metre etalon silencieusement degrade.
"""
from __future__ import annotations

import pytest

from ai.env_wrappers import BotControlledEnv
from tests.unit.ai.test_env_wrappers import _DummyBot, _DummyEngine


class _EngineHungryBot(_DummyBot):
    """Bot qui declare avoir besoin du moteur et l'accepte."""

    NEEDS_ENGINE = True

    def __init__(self) -> None:
        super().__init__()
        self.engine = None

    def attach_engine(self, engine) -> None:
        self.engine = engine


class _LiarBot(_DummyBot):
    """Bot qui reclame le moteur sans offrir par ou le recevoir."""

    NEEDS_ENGINE = True


def test_a_bot_that_declares_nothing_never_sees_the_engine() -> None:
    """Les six bots geles n'ont pas l'attribut : leur construction ne change pas d'une ligne."""
    plain = _DummyBot()
    wrapper = BotControlledEnv(_DummyEngine(), bot=plain)

    assert not hasattr(plain, "engine")
    assert wrapper.bot is plain


def test_a_declaring_bot_receives_the_engine_at_construction() -> None:
    bot = _EngineHungryBot()
    wrapper = BotControlledEnv(_DummyEngine(), bot=bot)

    assert bot.engine is wrapper.engine


def test_every_bot_of_a_pool_receives_it_not_only_the_first() -> None:
    """Avec `bots=[...]`, l'adversaire est retire au hasard a CHAQUE episode.

    N'attacher qu'a `self.bot` laisserait les autres sans moteur : la partie leverait au premier
    episode qui tire l'un d'eux, c'est-a-dire pas au premier.
    """
    pool = [_EngineHungryBot(), _EngineHungryBot(), _EngineHungryBot()]
    wrapper = BotControlledEnv(_DummyEngine(), bots=pool)

    assert [b.engine for b in pool] == [wrapper.engine] * 3


def test_a_bot_injected_at_play_time_receives_it_too() -> None:
    """`scripted_action_for_agent_side` fait jouer un bot que la construction n'a jamais vu —
    c'est la voie du classement bot-contre-bot (`scripts/bot_ranking.py`)."""
    late = _EngineHungryBot()
    wrapper = BotControlledEnv(_DummyEngine(), bot=_DummyBot())

    wrapper._attach_engine_if_needed(late)

    assert late.engine is wrapper.engine


def test_an_unhonoured_declaration_raises_instead_of_passing_silently() -> None:
    """T1 : declarer `NEEDS_ENGINE` sans `attach_engine` est une incoherence, pas un cas a absorber.

    Sans cette levee, le bot serait construit sans moteur et ne le decouvrirait qu'en pleine
    partie — ou, s'il avait un repli, jouerait un metre etalon degrade sans que personne ne le voie.
    """
    with pytest.raises(TypeError, match="attach_engine"):
        BotControlledEnv(_DummyEngine(), bot=_LiarBot())


def test_the_holdout_really_declares_it() -> None:
    """Contre-epreuve sur le CODE DE PRODUCTION : tous les tests ci-dessus portent sur des
    doublures ; celui-ci verifie que le bot qui en depend porte bien la declaration."""
    from ai.bot_holdout import LookaheadHoldoutBot

    assert LookaheadHoldoutBot.NEEDS_ENGINE is True
    assert callable(LookaheadHoldoutBot.attach_engine)
