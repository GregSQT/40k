"""Tests de contrat — registre `_once_claims` (engine.game_utils).

Ce registre porte toutes les étapes qui ne doivent se résoudre qu'UNE fois par
(tour, joueur) : scoring du primaire, récompense d'objectif, pénalité de coherency,
`cp_gain_on_objective`, événements de choix de règle.

CE QUE CES TESTS VERROUILLENT, et pourquoi ils existent : ces familles étaient auparavant
autant de clés de `game_state`, déclarées DEUX fois dans `w40k_core` (dict d'`__init__` ET
dict de `reset`). Oublier la déclaration côté RESET ne lève rien — la clé existe encore,
héritée de l'init — et comme les clés sont indexées sur le tour (∈ 1..5) elles se répètent
d'un épisode à l'autre : dès l'épisode 2 chaque étape se croit résolue et ne se déclenche
plus jamais, en silence, jusqu'à la fin du run. C'est arrivé pour de vrai à
`_choice_timing_fired_events` (16 décisions au 1er épisode, puis 2, puis 0). Le registre
unique remplace ces déclarations par un seul `pop` ; `test_reset_purges_all_claims` est ce
qui empêche ce `pop` de disparaître.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import numpy as np
import pytest

from engine.game_state import GameStateManager
from engine.game_utils import ONCE_CLAIMS_KEY, once_claim, once_claimed
from engine.observation_builder import ObservationBuilder
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config
from tests.unit.engine.test_game_state_contract import _minimal_config
from tests.unit.engine.test_objective_scoring import (
    _make_gs, _make_manager, _primary_objective, _unit,
)


# Les familles réellement réclamées en production, avec la forme EXACTE de leur clé.
# Trois formes différentes cohabitent — 2-uplet, 3-uplet (id d'objectif en tête) et chaîne
# pour les événements de choix — et le registre doit les porter sans les confondre.
_PRODUCTION_CLAIMS = [
    ("primary_objective_scored_turns", ("obj1", 1, 1)),
    ("objective_rewarded_turns", (1, 1)),
    ("coherency_penalized_turns", (1, 1)),
    ("cp_gain_on_objective_resolved", (1, 1)),
    ("_choice_timing_fired_events", "phase_start|1|fight|1|3|rule_x"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Sémantique du registre
# ─────────────────────────────────────────────────────────────────────────────

class TestOnceClaimsSemantics:

    def test_absent_registry_claims_nothing(self):
        """once_absent : un game_state vierge n'a rien réclamé (le registre naît à l'usage)."""
        gs: Dict[str, Any] = {}
        assert once_claimed(gs, "primary_objective_scored_turns", ("obj1", 1, 1)) is False
        assert ONCE_CLAIMS_KEY not in gs

    def test_claim_then_claimed(self):
        """once_claim : après réclamation, la même clé est vue comme réclamée."""
        gs: Dict[str, Any] = {}
        once_claim(gs, "objective_rewarded_turns", (1, 1))
        assert once_claimed(gs, "objective_rewarded_turns", (1, 1)) is True

    def test_other_key_same_family_not_claimed(self):
        """once_key : un autre (tour, joueur) de la MÊME famille reste libre."""
        gs: Dict[str, Any] = {}
        once_claim(gs, "objective_rewarded_turns", (1, 1))
        assert once_claimed(gs, "objective_rewarded_turns", (1, 2)) is False
        assert once_claimed(gs, "objective_rewarded_turns", (2, 1)) is False

    def test_families_are_isolated(self):
        """once_famille : réclamer dans une famille n'en réclame aucune autre.

        C'est l'invariant que le registre unique doit préserver par rapport aux quatre sets
        séparés : une seule clé de game_state, mais quatre espaces de noms disjoints.
        """
        gs: Dict[str, Any] = {}
        once_claim(gs, "coherency_penalized_turns", (1, 1))
        assert once_claimed(gs, "objective_rewarded_turns", (1, 1)) is False
        assert once_claimed(gs, "cp_gain_on_objective_resolved", (1, 1)) is False

    def test_claim_is_idempotent(self):
        """once_idem : réclamer deux fois ne change rien."""
        gs: Dict[str, Any] = {}
        once_claim(gs, "cp_gain_on_objective_resolved", (1, 1))
        once_claim(gs, "cp_gain_on_objective_resolved", (1, 1))
        assert gs[ONCE_CLAIMS_KEY]["cp_gain_on_objective_resolved"] == {(1, 1)}


# ─────────────────────────────────────────────────────────────────────────────
# Cycle de vie — purge au reset d'épisode
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def engine():
    """Moteur réel, non partagé : `reset()` mute game_state, un module-scope fausserait tout."""
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}), \
         patch.object(
             W40KEngine, "_build_observation",
             return_value=np.zeros(ObservationBuilder.SQUAD_OBS_SIZE_TARGET),
         ), \
         patch.object(
             W40KEngine, "_build_observation_and_mask",
             return_value=(np.zeros(ObservationBuilder.SQUAD_OBS_SIZE_TARGET), None),
         ):
        yield W40KEngine(config=build_engine_config(_minimal_config()))


class TestOnceClaimsLifecycle:

    def test_fresh_engine_has_no_claims(self, engine):
        """once_init : à la construction, aucune étape n'est réclamée."""
        for family, key in _PRODUCTION_CLAIMS:
            assert once_claimed(engine.game_state, family, key) is False

    def test_claims_survive_within_an_episode(self, engine):
        """once_intra : le registre ne se vide PAS en cours d'épisode.

        Contre-épreuve du test suivant : si le registre s'effaçait tout seul, la purge au
        reset serait invisible et son test toujours vert (vert vacant).
        """
        for family, key in _PRODUCTION_CLAIMS:
            once_claim(engine.game_state, family, key)
        for family, key in _PRODUCTION_CLAIMS:
            assert once_claimed(engine.game_state, family, key) is True

    def test_reset_purges_all_claims(self, engine):
        """once_reset : `reset()` efface TOUTES les familles — le verrou du `pop` de w40k_core.

        Les clés utilisées sont celles de la production (tour 1, joueur 1) : ce sont
        exactement celles que l'épisode suivant va réutiliser. Sans la purge, chacune des
        quatre étapes se croirait déjà résolue dès le tour 1 du nouvel épisode.
        """
        for family, key in _PRODUCTION_CLAIMS:
            once_claim(engine.game_state, family, key)

        engine.reset()

        assert engine.game_state.get(ONCE_CLAIMS_KEY) in (None, {})
        for family, key in _PRODUCTION_CLAIMS:
            assert once_claimed(engine.game_state, family, key) is False, (
                f"{family} a survecu au reset : l'etape ne se declenchera plus jamais"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Conséquence fonctionnelle — une famille purgée fait REJOUER l'étape
# ─────────────────────────────────────────────────────────────────────────────

class TestPurgeRestoresScoring:
    """Prouve que la purge n'est pas un détail d'état : sans elle, plus aucun VP.

    Le scoring du primaire est pris comme témoin des quatre familles — c'est celui dont la
    perte est la plus grave (plus de VP ⇒ plus de vainqueur).
    """

    @staticmethod
    def _score_turn(mgr: GameStateManager, gs: Dict[str, Any]) -> None:
        mgr.apply_primary_objective_scoring(gs, "command")

    def test_same_turn_scores_once(self):
        """once_dedup : deux passages sur le MÊME (objectif, tour, joueur) ne paient qu'une fois."""
        mgr = _make_manager()
        gs = _make_gs([_unit(1, 1, 5, 5)], turn=2, primary_objective=_primary_objective())

        self._score_turn(mgr, gs)
        first = gs["victory_points"][1]
        self._score_turn(mgr, gs)

        assert first > 0, "echantillon vide : le scoring n'a rien verse, le test n'observe rien"
        assert gs["victory_points"][1] == first

    def test_purged_registry_scores_again(self):
        """once_purge_rejoue : registre vidé → le même tour remarque, comme à l'épisode suivant.

        C'est ce que `test_reset_purges_all_claims` protège, exprimé en VP : la purge n'est
        pas cosmétique, elle est ce qui rend l'épisode 2 jouable.
        """
        mgr = _make_manager()
        gs = _make_gs([_unit(1, 1, 5, 5)], turn=2, primary_objective=_primary_objective())

        self._score_turn(mgr, gs)
        first = gs["victory_points"][1]
        assert first > 0

        # Ce que fait `W40KEngine.reset()`, réduit à sa seule ligne utile ici.
        gs.pop(ONCE_CLAIMS_KEY, None)
        gs["victory_points"] = {1: 0, 2: 0}
        self._score_turn(mgr, gs)

        assert gs["victory_points"][1] == first
