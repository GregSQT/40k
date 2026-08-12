#!/usr/bin/env python3
"""« Take to the skies » (21.03) est une DÉCISION D'AGENT — V11 §0.48 élément `L6`.

CE QUE CE FICHIER VERROUILLE, et pourquoi il existe séparément de
`test_fly_2103_conformity.py` : celui-là verrouille la RÈGLE (2", traversée, sets disjoints
move/charge) ; celui-ci verrouille le POINT DE CHOIX — que l'agent soit réellement interrogé, sur
le vrai chemin de production, et que le moteur ne tranche plus à sa place.

Le défaut fermé ici est nommé par §0.49 point 5 : une unité FLY pilotée par le modèle DÉCLARAIT
SYSTÉMATIQUEMENT (`took_to_the_skies` rendait `True` sans lire aucun état), et payait donc 2" à
chaque mouvement, y compris en terrain découvert où la traversée n'apporte rien.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from tests.unit.engine._config_helpers import build_move_rules
from engine.action_decoder import ActionDecoder
from engine.agent_decision import read_pending_agent_decision
from engine.macro_intents import (
    ACTIVATE_SLOT_BASE,
    ACTIVATE_SLOT_COUNT,
    CHOICE_BASE,
    CHOICE_COUNT,
    MOVE_CELLS,
    TOTAL_ACTION_SIZE,
)
from engine.observation_entities import MAX_DECISION_OPTIONS
from engine.observation_entities import (
    AGENT_DECISION_TYPE_IDS,
    AGENT_DECISION_TYPE_SLOTS,
    DECISION_CTX_BIN_FIELDS,
    DECISION_CTX_BIN_SIZE,
)
from engine.phase_handlers.movement_handlers import (
    apply_fly_declaration_decision,
    arm_fly_declaration_decision,
    fly_declaration_decision_is_due,
    took_to_the_skies,
)
from engine.phase_handlers.shared_utils import (
    build_enemy_adjacent_hexes,
    build_units_cache,
)
from tests._state_invariants import turn_state_invariants, unit_invariants


_START = (10, 20)
_ENEMY = (18, 20)


def _gs(
    *,
    phase: str = "move",
    fly: bool = True,
    gym: bool = True,
    pve: bool = False,
    move: int = 8,
) -> Dict[str, Any]:
    """`game_state` minimal : une escouade FLY d'une figurine, un ennemi hors de portée.

    Le siège est choisi par `gym` / `pve` — ce sont EXACTEMENT les deux drapeaux que lit
    `_unit_is_ai_controlled`, donc les deux seuls sièges à qui le point de choix s'ouvre.
    """
    keywords = [{"keywordId": "FLY"}] if fly else []
    flyer: Dict[str, Any] = {**unit_invariants(),
        "id": 1, "player": 1, "col": _START[0], "row": _START[1], "MOVE": move,
        "HP_CUR": 2, "HP_MAX": 2, "VALUE": 50, "OC": 1, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [], "CC_WEAPONS": [],
        "BASE_SIZE": 1, "BASE_SHAPE": "round", "MODEL_HEIGHT": 2.5,
        "UNIT_KEYWORDS": keywords, "UNIT_RULES": [],
    }
    enemy: Dict[str, Any] = {**unit_invariants(),
        "id": 2, "player": 2, "col": _ENEMY[0], "row": _ENEMY[1], "MOVE": 6,
        "HP_CUR": 2, "HP_MAX": 2, "VALUE": 50, "OC": 1, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [], "CC_WEAPONS": [],
        "BASE_SIZE": 1, "BASE_SHAPE": "round", "MODEL_HEIGHT": 2.5,
        "UNIT_KEYWORDS": [], "UNIT_RULES": [],
    }
    gs: Dict[str, Any] = {**turn_state_invariants(),
        "config": {
            "game_rules": {"engagement_zone": 1, "unit_model_cohesion_range": 2,
                           "unit_global_cohesion_range": 9,
                           "cohesion_distance_mode": "euclidean", "squad_min_neighbors": 1},
            "move": build_move_rules(),
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 44,
        "board_rows": 60,
        "current_player": 1,
        "phase": phase,
        "wall_hexes": set(),
        "units": [flyer, enemy],
        "unit_by_id": {"1": flyer, "2": enemy},
        "move_activation_pool": ["1"],
        "console_logs": [],
        "gym_training_mode": gym,
        "pve_mode": pve,
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, 1)
    build_enemy_adjacent_hexes(gs, 2)
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# 1. LE CONTRAT D'OBSERVATION N'A PAS BOUGÉ — c'est la condition d'entrée de `L6`
# ─────────────────────────────────────────────────────────────────────────────


def test_opening_the_type_consumes_a_reserve_and_leaves_obs_size_untouched():
    """`AGENT_DECISION_TYPE_SLOTS` est PRÉ-DIMENSIONNÉ (arbitrage 2 de §0.48) : déclarer un type
    de plus doit consommer une colonne RÉSERVÉE, jamais en ajouter une.

    Sans cette vérification, `L6` casserait le contrat d'observation qu'il est justement censé
    ne pas toucher — et le lot de ré-entraînement changerait de nature en silence.
    """
    assert "fly_declaration" in AGENT_DECISION_TYPE_IDS
    # 1 bit `decision_pending` + exactement SLOTS colonnes de type, réserves comprises.
    assert len(DECISION_CTX_BIN_FIELDS) == 1 + AGENT_DECISION_TYPE_SLOTS
    assert len(AGENT_DECISION_TYPE_IDS) <= AGENT_DECISION_TYPE_SLOTS
    # `obs_size` et l'espace d'action sont les deux contraintes NOMMÉES du chantier. La VALEUR
    # d'`obs_size` n'est PAS réaffirmée ici : elle est verrouillée à un seul endroit
    # (`test_deployment_observation_contract.test_squad_obs_size_target_matches_the_schema`), et
    # un autre chantier a le droit de la changer — le drapeau `declines` du bloc candidat de
    # décision l'a fait passer à 14615 le 2026-08-07. Ce que CE test doit prouver, c'est que
    # `L6` n'y contribue pour rien : ouvrir un type consomme une RÉSERVE, donc le bloc de
    # contexte garde sa taille (assertion ci-dessus). Recopier la valeur ici la ferait rougir à
    # chaque chantier voisin, pour un défaut qui n'est pas le sien.
    assert DECISION_CTX_BIN_SIZE == 1 + AGENT_DECISION_TYPE_SLOTS
    # ⚠️ MÊME RAISONNEMENT POUR L'ESPACE D'ACTION, et il manquait : la valeur `1127` était recopiée
    # ici, exactement le défaut que le commentaire ci-dessus décrit pour `obs_size`. `L2` l'a fait
    # passer à 1139 (12 slots d'activation) et ce cas a rougi pour un défaut qui n'est pas le sien.
    # Ce que `L6` doit prouver est qu'il n'y contribue PAS : ses deux candidats sont des
    # non-entités, donc des `CHOICE_0/1` déjà déclarés — aucun id nouveau. C'est ce qu'affirme la
    # ligne ci-dessous, sans dépendre de ce que les chantiers voisins ajoutent en queue.
    assert TOTAL_ACTION_SIZE == ACTIVATE_SLOT_BASE + ACTIVATE_SLOT_COUNT
    assert CHOICE_COUNT == MAX_DECISION_OPTIONS


# ─────────────────────────────────────────────────────────────────────────────
# 2. À QUI, ET QUAND, LA QUESTION EST POSÉE
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("phase", ["move", "charge"])
def test_a_flying_squad_piloted_by_the_model_is_asked_in_both_covered_phases(phase):
    """21.03 nomme « a normal, advance, fall-back OR CHARGE move » : le point de choix s'ouvre
    dans les DEUX phases, et pas seulement en mouvement (le jumeau oublié historique)."""
    gs = _gs(phase=phase)
    assert fly_declaration_decision_is_due(gs, "1") is True
    assert arm_fly_declaration_decision(gs, "1") is not None
    decision = read_pending_agent_decision(gs)
    assert decision is not None
    assert decision["type"] == "fly_declaration"
    assert decision["unit_id"] == "1"
    assert decision["player"] == 1
    # ORDRE CONTRACTUEL (§9.6) : 0 déclare, 1 renonce.
    assert [option["payload"]["declare"] for option in decision["options"]] == [True, False]


@pytest.mark.parametrize("phase", ["shoot", "fight", "command"])
def test_no_question_outside_the_moves_2103_covers(phase):
    """Un pile-in ou une consolidation ne sont pas des mouvements de 21.03 : rien à déclarer, et
    surtout aucun step gaspillé à poser une question sans objet."""
    gs = _gs(phase=phase)
    assert fly_declaration_decision_is_due(gs, "1") is False
    assert arm_fly_declaration_decision(gs, "1") is None
    assert read_pending_agent_decision(gs) is None


def test_no_question_without_the_fly_keyword():
    """Sans FLY, 21.03 ne s'applique pas : poser le choix offrirait une option illégale."""
    gs = _gs(fly=False)
    assert fly_declaration_decision_is_due(gs, "1") is False
    assert arm_fly_declaration_decision(gs, "1") is None


def test_a_human_seat_is_never_asked_it_has_the_ui_toggle():
    """Le PvP humain déclare par `movement_set_fly_mode_handler` (toggle réversible). Lui poser
    une `pending_agent_decision` arrêterait le moteur sur un overlay qui n'existe pas côté front,
    donc sur une partie qui ne repart jamais."""
    gs = _gs(gym=False, pve=False)
    assert fly_declaration_decision_is_due(gs, "1") is False
    assert arm_fly_declaration_decision(gs, "1") is None


def test_the_pve_ai_seat_is_asked_it_answers_with_the_same_policy_as_the_gym():
    """Joueur 2 en PvE : piloté par le modèle via `pve_controller`, qui joue par le MÊME masque
    que l'entraînement. Il doit donc être interrogé comme lui — sinon la constante moteur
    supprimée en gym survivrait en PvE."""
    gs = _gs(gym=False, pve=True)
    gs["unit_by_id"]["1"]["player"] = 2
    gs["units"][0]["player"] = 2
    gs["current_player"] = 2
    assert fly_declaration_decision_is_due(gs, "1") is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. LES DEUX RÉPONSES, ET LE FAIT QUE LA QUESTION NE SE REPOSE PAS
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("declared", [True, False])
def test_applying_a_candidate_writes_the_declaration_and_clears_the_decision(declared):
    gs = _gs()
    arm_fly_declaration_decision(gs, "1")
    apply_fly_declaration_decision(gs, "1", declared)

    assert read_pending_agent_decision(gs) is None, "décision jouée mais non effacée : le moteur reste arrêté"
    assert took_to_the_skies(gs, gs["unit_by_id"]["1"], "1", charge=False) is declared
    assert ("1" in gs["units_took_to_skies"]) is declared


def test_refusing_leaves_a_trace_otherwise_the_question_loops_forever():
    """LE PIÈGE de ce chantier : « je ne déclare pas » laisse le set de déclaration VIDE — donc
    indiscernable de « la question n'a pas été posée » si on ne trace que la déclaration.

    Sans le set de résolution, le masque reposerait le choix à CHAQUE construction, l'escouade ne
    jouerait jamais son mouvement, et l'épisode tournerait en rond sans qu'aucune erreur ne lève.
    """
    gs = _gs()
    arm_fly_declaration_decision(gs, "1")
    apply_fly_declaration_decision(gs, "1", False)

    assert gs["units_took_to_skies"] == set()
    assert fly_declaration_decision_is_due(gs, "1") is False
    assert arm_fly_declaration_decision(gs, "1") is None


def test_the_two_phases_are_asked_separately():
    """Déclaration PAR MOUVEMENT : répondre pour le move ne répond pas pour la charge."""
    gs = _gs(phase="move")
    arm_fly_declaration_decision(gs, "1")
    apply_fly_declaration_decision(gs, "1", True)

    gs["phase"] = "charge"
    assert fly_declaration_decision_is_due(gs, "1") is True
    arm_fly_declaration_decision(gs, "1")
    apply_fly_declaration_decision(gs, "1", False)
    assert gs["units_took_to_skies"] == {"1"}
    assert gs["units_took_to_skies_charge"] == set()


def test_the_question_is_reposed_next_turn():
    """21.03 s'applique « each time a FLYING unit is selected to make a [...] move » : la réponse
    du tour précédent ne vaut pas pour le suivant. Les deux sets de résolution ont donc le MÊME
    cycle de vie que les déclarations — remis à zéro par 08.01 (`command_step_start_of_phase`)."""
    from engine.phase_handlers.command_handlers import command_step_start_of_phase

    gs = _gs()
    arm_fly_declaration_decision(gs, "1")
    apply_fly_declaration_decision(gs, "1", True)
    assert fly_declaration_decision_is_due(gs, "1") is False

    command_step_start_of_phase(gs)
    assert gs["units_took_to_skies"] == set()
    assert gs["units_fly_declaration_resolved"] == set()
    assert gs["units_fly_declaration_resolved_charge"] == set()
    # 08.01 pose la phase `command` : on revient au mouvement pour interroger le prédicat, qui
    # est gardé par la phase (une escouade n'est pas interrogée en phase de commandement).
    gs["phase"] = "move"
    assert fly_declaration_decision_is_due(gs, "1") is True


# ─────────────────────────────────────────────────────────────────────────────
# 4. LE VRAI CHEMIN — le masque du gym, pas une reconstruction
# ─────────────────────────────────────────────────────────────────────────────


def _open_actions(mask) -> List[int]:
    return [i for i, opened in enumerate(mask) if bool(opened)]


def test_the_mask_arms_the_choice_before_building_the_pool_and_opens_only_it():
    """LE POINT CRITIQUE du chantier. La déclaration change le budget ET la traversée, donc le
    POOL : le choix doit être posé AVANT sa construction, là où le moteur tranchait.

    Le masque devient EXCLUSIF (comme pour le Waaagh!) : `CHOICE_0`/`CHOICE_1` et rien d'autre,
    pool d'unités éligibles vide — le moteur rend la main, l'activation reprendra après.
    """
    decoder = ActionDecoder({})
    gs = _gs()

    mask, eligible = decoder.get_squad_action_mask_and_eligible_units(gs)
    assert _open_actions(mask) == [CHOICE_BASE, CHOICE_BASE + 1]
    assert eligible == []
    assert read_pending_agent_decision(gs) is not None


def test_rebuilding_the_mask_does_not_stack_a_second_decision():
    """Le masque est reconstruit plusieurs fois par step (wrapper, observation,
    `W40K_MASK_VERIFY=2`). L'armement doit être IDEMPOTENT : `set_pending_agent_decision` LÈVE si
    une décision est déjà en attente, un armement non gardé ferait donc tomber le run."""
    decoder = ActionDecoder({})
    gs = _gs()

    first, _ = decoder.get_squad_action_mask_and_eligible_units(gs)
    second, _ = decoder.get_squad_action_mask_and_eligible_units(gs)
    assert _open_actions(first) == _open_actions(second)


@pytest.mark.parametrize("declared", [True, False])
def test_after_the_answer_the_mask_serves_the_move_pool_of_that_answer(declared):
    """Le choix RÉPONDU, l'activation reprend : le masque rouvre les cellules de mouvement, et
    c'est le pool de la déclaration choisie qu'il sert (`squad_move_pool_budget_subhex` lit la
    déclaration). Sans cette reprise, l'escouade serait bloquée sur son propre choix.
    """
    from engine.phase_handlers.movement_handlers import squad_move_pool_budget_subhex

    decoder = ActionDecoder({})
    gs = _gs(move=8)
    decoder.get_squad_action_mask_and_eligible_units(gs)
    apply_fly_declaration_decision(gs, "1", declared)

    mask, eligible = decoder.get_squad_action_mask_and_eligible_units(gs)
    assert [str(unit["id"]) for unit in eligible] == ["1"]
    assert any(action in MOVE_CELLS for action in _open_actions(mask)), (
        "aucune cellule de mouvement ouverte après la réponse — l'escouade reste bloquée"
    )
    assert squad_move_pool_budget_subhex(gs, "1") == (8 - 2 if declared else 8)


# ─────────────────────────────────────────────────────────────────────────────
# 5. LE MOTEUR ROUTE VRAIMENT L'ACTION — « testé mais jamais appelé » (§0bis)
# ─────────────────────────────────────────────────────────────────────────────

_ARMAGEDDON_TRAINING_SCENARIO = (
    "config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon1.json"
)


@pytest.mark.parametrize("option_index, expected", [(0, True), (1, False)])
def test_the_engine_routes_the_choice_action_to_the_declaration(option_index, expected):
    """`CHOICE_i` doit ATTEINDRE l'application, sur un vrai `W40KEngine` — pas sur un helper
    appelé à la main. Le motif récurrent du dépôt est exactement l'inverse : une plomberie
    complète et testée que le chemin de production n'emprunte jamais.

    Deux frontières franchies ici : `convert_squad_action` (entier -> sémantique) puis
    `_process_squad_action` (sémantique -> moteur, branche `fly_declaration`). Un type déclaré
    dans `AGENT_DECISION_TYPE_IDS` mais non branché lève `NotImplementedError` — cette assertion
    est donc aussi le verrou de cette garde.
    """
    from ai.unit_registry import UnitRegistry
    from engine.phase_handlers.movement_handlers import _unit_has_keyword
    from engine.w40k_core import W40KEngine

    engine = W40KEngine(
        rewards_config="default",
        training_config_name="x1",
        controlled_agent="ArmageddonAgent",
        active_agents=None,
        scenario_file=_ARMAGEDDON_TRAINING_SCENARIO,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,
    )
    flyer_id = None
    for _ in range(25):
        engine.reset()
        flyer_id = next(
            (
                str(unit["id"]) for unit in engine.game_state["units"]
                if _unit_has_keyword(unit, "fly")
            ),
            None,
        )
        if flyer_id is not None:
            break
    assert flyer_id is not None, "SONDE MUETTE : aucune unité volante en 25 tirages de roster"

    gs = engine.game_state
    gs["phase"] = "move"
    assert arm_fly_declaration_decision(gs, flyer_id) is not None

    semantic = engine.action_decoder.convert_squad_action(CHOICE_BASE + option_index, gs)
    assert semantic == {"action": "agent_decision", "option_index": option_index}
    success, result = engine._process_squad_action(semantic)

    assert success is True
    assert result["decision_type"] == "fly_declaration"
    assert result["unitId"] == flyer_id
    assert result["tookToSkies"] is expected
    assert read_pending_agent_decision(gs) is None
    assert (flyer_id in gs["units_took_to_skies"]) is expected
    assert fly_declaration_decision_is_due(gs, flyer_id) is False


def test_the_observation_describes_the_squad_the_choice_is_about():
    """L'observation servie AVEC le masque de la décision doit décrire l'escouade CONCERNÉE.

    Cas propre à `L6` : la décision est armée PAR la construction du masque, à l'intérieur de
    `_build_observation_and_mask` — le contrôle d'entrée de cette fonction ne l'avait donc pas
    vue, et le pool d'éligibles qu'elle reçoit est alors VIDE. Sans la branche dédiée,
    l'observateur retombait sur « la première escouade vivante du joueur courant » : l'agent
    aurait décrit une escouade et déclaré le vol pour une autre (§0.40 point 1).

    Le moteur est CONDUIT jusqu'à ce moment (aucun état posé à la main : un `game_state` bricolé
    n'aurait prouvé que lui-même), et on observe l'ARGUMENT réellement passé au constructeur
    d'observation — c'est le squad_id qui est en cause, et lui seul.
    """
    import numpy as np

    from ai.unit_registry import UnitRegistry
    from engine.observation_builder import ObservationBuilder
    from engine.w40k_core import W40KEngine

    engine = W40KEngine(
        rewards_config="default",
        training_config_name="x1",
        controlled_agent="ArmageddonAgent",
        active_agents=None,
        scenario_file=_ARMAGEDDON_TRAINING_SCENARIO,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,
    )
    engine.reset()

    real_build = ObservationBuilder.build_squad_observation
    observed: List[str] = []

    def _spy(self, game_state, squad_id):
        observed.append(str(squad_id))
        return real_build(self, game_state, squad_id)

    decision = None
    with patch.object(ObservationBuilder, "build_squad_observation", _spy):
        for _ in range(400):
            decision = read_pending_agent_decision(engine.game_state)
            if decision is not None and decision["type"] == "fly_declaration":
                break
            mask = engine.get_action_mask()
            legal = [i for i, opened in enumerate(np.asarray(mask, dtype=bool)) if opened]
            assert legal, f"masque vide en phase {engine.game_state['phase']}"
            # Premier coup légal : on ne cherche pas à bien jouer, seulement à atteindre le
            # premier point de choix de vol que la partie produit d'elle-même.
            _obs, _r, terminated, truncated, _info = engine.step(legal[0])
            assert not (terminated or truncated), "épisode terminé avant toute unité volante"

    assert decision is not None and decision["type"] == "fly_declaration", (
        "SONDE MUETTE : aucune déclaration de vol atteinte en 400 steps"
    )
    assert observed, "SONDE MUETTE : aucune observation construite"
    assert observed[-1] == str(decision["unit_id"]), (
        f"dernière observation construite pour {observed[-1]}, alors que la décision en attente "
        f"porte sur {decision['unit_id']}"
    )


def test_the_owner_check_actually_bites_it_reads_the_state_not_the_decision():
    """LE POINT de l'audit du 2026-08-07 : ce contrôle-là doit pouvoir SE DÉCLENCHER.

    Tel qu'il était écrit, l'unique appelant du gym relisait le propriétaire DANS la décision
    avant de le repasser au vérificateur : le contrôle comparait la décision à elle-même et ne
    pouvait jamais refuser quoi que ce soit, tout en ayant l'apparence d'une garde (« vert
    vacant », cf. T4). Il lit désormais `current_player`, source INDÉPENDANTE.

    Ce qu'il attrape : une décision qui a survécu au tour de son propriétaire. Seul son siège
    peut y répondre ; appliquée pendant le tour adverse, elle écrirait la déclaration de vol
    d'un joueur pendant que l'autre joue.
    """
    gs = _gs()
    arm_fly_declaration_decision(gs, "1")
    assert int(gs["current_player"]) == 1, "pré-condition : la décision appartient au joueur 1"

    gs["current_player"] = 2
    with pytest.raises(RuntimeError, match="appartient au joueur 1, pas a 2"):
        apply_fly_declaration_decision(gs, "1", True)

    # Rien n'a été écrit, et la décision SURVIT : un refus n'est pas une résolution.
    assert gs["units_took_to_skies"] == set()
    assert read_pending_agent_decision(gs) is not None

    # Témoin actif : rendue au bon tour, la même décision passe.
    gs["current_player"] = 1
    apply_fly_declaration_decision(gs, "1", True)
    assert gs["units_took_to_skies"] == {"1"}


def test_the_enemy_is_never_asked_during_your_turn():
    """21.03 confie la déclaration au « ACTIVE player ».

    Contrepartie EXACTE du contrôle d'`apply_fly_declaration_decision` : si l'armement pouvait
    interroger l'adversaire, la réponse serait ensuite REFUSÉE par le vérificateur de
    propriétaire, et le moteur resterait arrêté sur une décision que personne ne peut résoudre —
    masque réduit aux `CHOICE_i`, partie bloquée. Les deux bouts doivent donc s'accorder par
    construction, pas par la bonne conduite du pool d'activation.
    """
    gs = _gs()
    gs["unit_by_id"]["1"]["player"] = 2
    gs["units"][0]["player"] = 2
    assert int(gs["current_player"]) == 1

    assert fly_declaration_decision_is_due(gs, "1") is False
    assert arm_fly_declaration_decision(gs, "1") is None
    assert read_pending_agent_decision(gs) is None

    # Témoin actif : à SON tour, la même escouade est bien interrogée.
    gs["current_player"] = 2
    assert fly_declaration_decision_is_due(gs, "1") is True
