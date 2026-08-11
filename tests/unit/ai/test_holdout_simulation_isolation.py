"""Simuler un coup ne doit RIEN laisser derrière soi.

Le holdout d'évaluation essaie ses actions avant de choisir : il joue chaque coup sur un clone de
l'état, par le vrai `engine.step()`, puis rend le moteur intact. La première version ne restaurait
que `game_state`, et trois fuites en résultaient — toutes relevées par la review du 2026-08-11 :

1. **les compteurs** : `_episode_step_calls`, `episode_length_accumulator`,
   `episode_reward_accumulator` et `episode_tactical_data` avançaient à chaque coup simulé.
   Cinq à treize simulations par décision, donc un compteur de pas multiplié d'autant : le garde
   anti-runaway tronquait les épisodes du holdout en annonçant `episode_steps_limit`, et le mètre
   étalon rendait des parties coupées ;
2. **le journal** : un `step_logger` attaché recevait un `log_action` par coup SIMULÉ — des
   actions jamais jouées, écrites dans le fichier qui sert à analyser la partie ;
3. **le hasard** : chaque simulation consomme des jets de dés. Sans rembobinage, les cinq cibles
   d'un tir étaient comparées sur cinq tirages DIFFÉRENTS — l'argmax portait sur le bruit, pas sur
   la fonction de valeur — et l'évaluation cessait d'être reproductible à graine fixée.

Le test compare l'état COMPLET du moteur avant et après, pas une liste d'attributs choisie : une
liste diverge dès que le moteur gagne un compteur, et c'est précisément ce qui s'est produit.
"""
from __future__ import annotations

import copy
import random
from typing import Any, Dict

import numpy as np
import pytest

from ai.bot_holdout import LookaheadHoldoutBot


class _MutatingEngine:
    """Moteur minimal qui mute tout ce que le vrai mute pendant `step`."""

    def __init__(self) -> None:
        self.game_state: Dict[str, Any] = {"turn": 1, "units": [], "victory_points": {1: 0, 2: 0}}
        self._episode_step_calls = 0
        self.episode_length_accumulator = 0
        self.episode_reward_accumulator = 0.0
        self.episode_tactical_data = {"shots": []}
        self.step_logger = None
        self.steps_seen: list = []

    def step(self, action: int):
        self._episode_step_calls += 1
        self.episode_length_accumulator += 1
        self.episode_reward_accumulator += 1.5
        self.episode_tactical_data["shots"].append(action)
        self.steps_seen.append(action)
        if self.step_logger is not None:
            self.step_logger.calls.append(action)
        self.game_state["turn"] += 1          # mutation de l'état cloné
        random.random()                        # consomme le hasard, comme un jet de dés
        np.random.random()
        return None


class _RecordingLogger:
    def __init__(self) -> None:
        self.calls: list = []


def _snapshot(engine: _MutatingEngine) -> Dict[str, Any]:
    """Vue comparable de TOUT l'état du moteur, `game_state` compris.

    Copie PROFONDE : une copie superficielle partagerait la liste `shots` avec le moteur, donc
    l'instantané « avant » se ferait muter par la simulation et le test passerait toujours — un
    vert vacant de manuel.
    """
    return copy.deepcopy({
        "step_calls": engine._episode_step_calls,
        "length": engine.episode_length_accumulator,
        "reward": engine.episode_reward_accumulator,
        "tactical": engine.episode_tactical_data,
        "turn": engine.game_state["turn"],
        "logger": engine.step_logger,
    })


@pytest.fixture()
def bot_and_engine():
    bot = LookaheadHoldoutBot()
    engine = _MutatingEngine()
    bot.attach_engine(engine)
    return bot, engine


def test_a_simulated_move_leaves_the_engine_exactly_as_it_was(bot_and_engine) -> None:
    """LE verrou : l'état complet du moteur est identique avant et après."""
    bot, engine = bot_and_engine
    before = _snapshot(engine)

    with bot._simulation() as sim:
        sim.step(42)

    assert _snapshot(engine) == before


def test_the_counters_do_not_drift_over_many_simulations(bot_and_engine) -> None:
    """Une décision simule autant de coups qu'il y a d'actions légales ; c'est l'accumulation qui
    faisait tronquer les épisodes, pas une simulation isolée."""
    bot, engine = bot_and_engine

    for action in range(13):
        with bot._simulation() as sim:
            sim.step(action)

    assert engine._episode_step_calls == 0
    assert engine.episode_length_accumulator == 0
    assert engine.episode_reward_accumulator == 0.0
    assert engine.episode_tactical_data == {"shots": []}


def test_the_journal_never_sees_a_simulated_action(bot_and_engine) -> None:
    """Un coup essayé n'est pas un coup joué : il n'a rien à faire dans `step.log`."""
    bot, engine = bot_and_engine
    logger = _RecordingLogger()
    engine.step_logger = logger

    with bot._simulation() as sim:
        sim.step(7)

    assert logger.calls == [], "le journal a enregistré une action jamais jouée"
    assert engine.step_logger is logger, "le journal doit être rendu au moteur"


def test_every_candidate_of_one_decision_faces_the_same_draw(bot_and_engine) -> None:
    """Deux candidates d'UNE decision doivent tirer les memes des, sinon l'argmax designe le coup
    le plus chanceux et non le meilleur."""
    bot, engine = bot_and_engine

    draws = []
    for action in (1, 2, 3):
        with bot._simulation() as sim:
            sim.step(action)
            draws.append(random.random())

    assert len(set(draws)) == 1, f"tirages differents entre candidates : {draws}"


def test_two_successive_decisions_do_not_reuse_the_same_draw(bot_and_engine) -> None:
    """Sinon le holdout jugerait toute la partie sur un seul jet de des fige."""
    bot, engine = bot_and_engine

    first_decision = []
    bot._simulation_draw += 1
    with bot._simulation() as sim:
        sim.step(1)
        first_decision.append(random.random())

    bot._simulation_draw += 1
    with bot._simulation() as sim:
        sim.step(1)
        first_decision.append(random.random())

    assert first_decision[0] != first_decision[1]


def test_the_game_dice_are_untouched_so_the_bot_is_no_oracle(bot_and_engine) -> None:
    """LE test que la version precedente ne faisait pas.

    ⚠️ L'ancien test resemait avant CHAQUE simulation, donc ses deux moities etaient symetriques
    et il passait meme sans aucune restauration — un vert vacant, releve par la review du
    2026-08-11. Pire : la restauration qu'il croyait verifier RENDAIT le hasard a son etat
    d'avant, si bien que le vrai coup rejouait exactement la sequence de la simulation gagnante.
    Le bot choisissait donc en connaissant le resultat reel des des : un oracle, qui fausse le
    metre etalon.

    Ce test verrouille le contrat juste : apres simulation, la partie tire ce qu'elle aurait tire
    SANS simulation — ni le meme tirage (oracle), ni un tirage decale (sequence perturbee).
    """
    bot, engine = bot_and_engine

    random.seed(99)
    np.random.seed(99)
    expected = [random.random() for _ in range(3)]

    random.seed(99)
    np.random.seed(99)
    for action in (1, 2, 3):
        with bot._simulation() as sim:
            sim.step(action)
    actual = [random.random() for _ in range(3)]

    assert actual == expected, (
        "le hasard de la partie a ete altere par les simulations : soit le bot rejoue les des "
        "de sa simulation (oracle), soit il decale la sequence"
    )


def test_the_clone_absorbs_the_mutations_instead_of_the_real_state(bot_and_engine) -> None:
    """La simulation doit bien SE PASSER — un test d'isolation qui passerait parce que rien ne
    s'exécute serait un vert vacant (le défaut symétrique, déjà vécu sur ce dépôt)."""
    bot, engine = bot_and_engine
    real_state = engine.game_state

    with bot._simulation() as sim:
        sim.step(3)
        # `sim` EST le moteur : il est prêté, pas cloné. Ce qui est cloné, c'est son `game_state`.
        assert sim is engine
        assert sim.game_state["turn"] == 2, "le coup n'a pas été joué sur le clone"
        assert sim.game_state is not real_state, "le coup a été joué sur l'état RÉEL"

    assert engine.game_state is real_state
    assert engine.game_state["turn"] == 1
    assert engine.steps_seen == [3], "le vrai moteur doit avoir exécuté le coup, sur le clone"


def test_the_simulation_draw_is_not_the_one_the_game_will_play(bot_and_engine) -> None:
    """L'ORACLE, teste directement — les deux tests ci-dessus ne le distinguent pas.

    Sauvegarder puis restaurer le hasard suffit a laisser la partie tirer ce qu'elle aurait tire
    (test precedent, vert dans les deux cas). Mais si la simulation consomme LA MEME sequence que
    celle rendue ensuite a la partie, alors le bot a vu a l'avance le resultat reel des des : il
    choisit l'arme qui tue AVEC CE TIRAGE, pas celle qui tue en esperance. C'est ce que faisait la
    version « sauvegarde/restaure » simple, et c'est ce que ce test interdit.
    """
    bot, engine = bot_and_engine
    random.seed(4242)
    np.random.seed(4242)

    simulated: list = []
    with bot._simulation() as sim:
        sim.step(1)
        simulated.append(random.random())

    played = random.random()

    assert simulated[0] != played, (
        "la simulation a tire exactement ce que la partie va tirer : le holdout est un oracle"
    )


class _PositionalEngine(_MutatingEngine):
    """Moteur dont le controle d'objectif depend de la POSITION, comme le vrai."""

    def __init__(self) -> None:
        super().__init__()
        self.game_state.update({
            "units": [{"id": "1", "player": 1, "VALUE": 100.0},
                      {"id": "9", "player": 2, "VALUE": 100.0}],
            "units_cache": {"1": {}, "9": {}},
            "position": 0,
            # Perime a dessein : le moteur ne le rafraichit qu'aux frontieres de phase.
            "objective_controllers": {1: None},
        })

        class _StateManager:
            @staticmethod
            def calculate_objective_control(gs):
                # Le joueur 1 controle la zone s'il est arrive dessus (position 2).
                return {1: {"controller": 1 if gs["position"] == 2 else None}}

        self.state_manager = _StateManager()

    def step(self, action: int):
        super().step(action)
        self.game_state["position"] = action


def test_two_destinations_do_not_score_the_same(monkeypatch: pytest.MonkeyPatch) -> None:
    """LE verrou du finding principal : la valeur doit VOIR le deplacement.

    ⚠️ La premiere version lisait `objective_controllers`, que le moteur ne rafraichit qu'aux
    frontieres de phase et de tour. Toutes les destinations d'une phase de mouvement rendaient
    donc la meme valeur, la baseline « ne pas bouger » l'emportait par `>` strict, et le holdout
    ne se deplacait JAMAIS — le pre-tri geometrique et `MOVE_SHORTLIST` ne servaient a rien.
    Mesure de la review : `[-20.0, -20.0, -20.0]` pour trois destinations differentes.
    """
    import ai.bot_holdout as holdout

    monkeypatch.setattr(holdout, "is_unit_alive", lambda sid, gs: True)

    bot = LookaheadHoldoutBot()
    engine = _PositionalEngine()
    bot.attach_engine(engine)

    values = [bot._value_after(action, engine.game_state, 1) for action in (1, 2, 3)]

    assert len(set(values)) > 1, f"toutes les destinations valent pareil : {values}"
    assert values[1] > values[0], "la destination qui prend la zone doit valoir davantage"
