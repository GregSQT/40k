"""V11 §8.2 — LE verrou d'interface agent : chaque entier d'action → l'intention attendue.

Ce fichier est le contrat que la spec exigeait et qui n'avait jamais été écrit. Il existe pour une
raison précise : `test_action_space_mirror.py` compare les constantes ENTRE ELLES (macro_intents ↔
shared_utils) sans jamais appeler le décodeur. Un miroir cohérent ne prouve rien sur le ROUTAGE :
c'est exactement pourquoi un outil d'évaluation a pu servir au modèle un masque de l'ancien espace
d'actions (0-15) sans que quoi que ce soit ne se plaigne, et pourquoi le décodeur mort
`convert_gym_action` a survécu des mois derrière ~25 tests verts.

Chaque cas ci-dessous APPELLE `ActionDecoder.convert_squad_action` — le seul décodeur vivant — et
vérifie l'intention obtenue. Aucun cas ne se contente de comparer deux constantes.

Les états de jeu viennent d'un moteur RÉEL (`W40KEngine`), pas d'un dict fabriqué : un
`game_state` bricolé peut satisfaire un décodeur qui aurait cessé d'être branché sur le moteur.

Table verrouillée (entier → intention) :

| entier                                    | intention attendue                              |
|-------------------------------------------|-------------------------------------------------|
| `MOVE_CELL_BASE + cell` (cellule masquée) | `squad_normal_move` / `_advance` / `_fall_back` |
| `MOVE_CELL_BASE + MOVE_CELL_COUNT - 1`    | move (et surtout PAS `squad_wait`)              |
| `ACTION_WAIT`, hors phase command         | `squad_wait`                                    |
| `ACTION_WAIT`, en phase command           | `command_wait`                                  |
| `SHOOT_SLOT_BASE + k`                     | `squad_shoot`, `target_slot == k`               |
| `CHARGE_SLOT_BASE + k`                    | `squad_charge`, `target_slot == k`              |
| `FIGHT_SLOT_BASE + k`                     | `squad_fight`, `target_slot == k`               |
| `ACTION_FIGHT_NO_TARGET`                  | `squad_fight` SANS `target_slot`                |
| `BASE_ZONE_INTENT + 3*zone + intent`      | `zone_intent(zone, intent)`                     |
| `CHOICE_BASE + i`                         | `agent_decision`, `option_index == i`           |
| `DEPLOY_SLOT_BASE + s`, phase deployment  | `deploy_unit` sur l'hex de la stratégie `s`     |

Les gardes sont verrouillées au même titre que les routages : un zone intent hors command, une
action CHOICE sans décision en attente, un entier au-delà de l'espace et un entier hors
`DEPLOY_SLOTS` en déploiement DOIVENT lever — jamais se replier sur une intention plausible.

Les bornes sont testées explicitement (premier ET dernier slot de chaque famille, dernière
cellule de move, dernier zone intent contre le premier CHOICE) : c'est là qu'un décalage de base
d'une seule unité se cache.
"""

from __future__ import annotations

import copy
import random
from typing import Any, Dict, List, Tuple

import pytest

from engine.agent_decision import set_pending_agent_decision
from engine.macro_intents import (
    ACTION_FIGHT_NO_TARGET,
    ACTION_WAIT,
    BASE_ZONE_INTENT,
    CHARGE_SLOT_BASE,
    CHARGE_SLOT_COUNT,
    CHOICE_BASE,
    CHOICE_COUNT,
    DEPLOY_SLOT_BASE,
    DEPLOY_SLOT_COUNT,
    FIGHT_SLOT_BASE,
    FIGHT_SLOT_COUNT,
    MAX_OBJECTIVES,
    MOVE_CELL_BASE,
    MOVE_CELL_COUNT,
    SHOOT_SLOT_BASE,
    SHOOT_SLOT_COUNT,
)
from engine.phase_handlers.shared_utils import (
    MOVE_CELL_MAP_CACHE_KEY,
    store_squad_move_cell_map,
)

SCENARIO = "config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json"

#: Les trois seules intentions de mouvement d'escouade. Le TYPE n'est pas une dimension d'action
#: (§6.2) : il est inféré du coût géodésique de la cellule, donc le verrou porte sur la famille
#: + la destination, pas sur le type.
MOVE_ACTIONS = {"squad_normal_move", "squad_advance", "squad_fall_back"}


def _new_engine():
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    engine = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent",
        scenario_file=SCENARIO,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
    )
    engine.reset(seed=0)
    return engine


@pytest.fixture(scope="module")
def deployment_state() -> Tuple[Any, Dict[str, Any]]:
    """Moteur juste après `reset` : phase deployment, pools de déploiement réels."""
    engine = _new_engine()
    assert engine.game_state["phase"] == "deployment", (
        "le scénario ne démarre plus en déploiement : ce fixture doit être revu"
    )
    return engine.action_decoder, engine.game_state


@pytest.fixture(scope="module")
def move_state() -> Tuple[Any, Dict[str, Any], str, int, Tuple[int, int]]:
    """Moteur amené en phase move par actions masquées : (decoder, gs, squad_id, cell, dest).

    La cellule rendue est une cellule RÉELLEMENT offerte par le masque, relue dans la carte que
    le masque a mémorisée — donc exactement ce que la production donnerait au décodeur.
    """
    engine = _new_engine()
    rng = random.Random(0)
    for _ in range(300):
        mask = engine.get_action_mask()
        game_state = engine.game_state
        if game_state["phase"] == "move":
            for squad_id, stored in (game_state.get(MOVE_CELL_MAP_CACHE_KEY) or {}).items():
                cell_map = stored["map"]
                if cell_map:
                    cell_idx = sorted(cell_map)[0]
                    return (
                        engine.action_decoder,
                        game_state,
                        str(squad_id),
                        cell_idx,
                        cell_map[cell_idx][0],
                    )
        valid = [i for i, v in enumerate(mask) if v]
        assert valid, f"aucune action valide en phase {game_state['phase']}"
        engine.step(rng.choice(valid))
    pytest.fail("phase move avec carte de cellules jamais atteinte en 300 steps")


@pytest.fixture
def phase_state(deployment_state):
    """Fabrique (decoder, gs, squad_id) sur une COPIE de l'état moteur, dans la phase demandée.

    Adossé au moteur juste après `reset` — donc à un état réel — mais SANS dépendre de la boucle
    de jeu : un décodeur cassé fait échouer le cas qu'il casse, pas la construction du fixture.
    C'est ce qui rend les cas ci-dessous attribuables un à un sous mutation.
    """

    def _make(phase: str):
        decoder, source = deployment_state
        game_state = copy.deepcopy(source)
        game_state["phase"] = phase
        squad_id = str(game_state["units"][0]["id"])
        return decoder, game_state, squad_id

    return _make


def _eligible(game_state: Dict[str, Any], squad_id: str) -> List[Dict[str, Any]]:
    """Pool d'une seule escouade — le décodeur ne lit que `eligible_units[0]["id"]`."""
    for unit in game_state["units"]:
        if str(unit["id"]) == squad_id:
            return [unit]
    raise KeyError(f"escouade {squad_id} absente de game_state['units']")


# ─────────────────────────────────────────────────────────────────────────────
# Cellules de move — `MOVE_CELL_BASE + cell_index`
# ─────────────────────────────────────────────────────────────────────────────


def test_move_cell_action_routes_to_that_cell(move_state):
    """Une cellule offerte par le masque décode en un move vers CETTE cellule."""
    decoder, game_state, squad_id, cell_idx, dest = move_state
    result = decoder.convert_squad_action(
        MOVE_CELL_BASE + cell_idx, game_state, eligible_units=_eligible(game_state, squad_id)
    )
    assert result["action"] in MOVE_ACTIONS, result
    assert result["squad_id"] == squad_id
    assert (result["destCol"], result["destRow"]) == dest


def test_last_move_cell_is_still_a_move_and_not_the_wait_action(move_state):
    """`MOVE_CELL_BASE + MOVE_CELL_COUNT - 1` est la DERNIÈRE cellule, pas `ACTION_WAIT`.

    Borne haute de la famille move : un décalage d'une unité entre le plan de cellules et
    `ACTION_WAIT` ferait décoder « fin d'activation » là où l'agent désignait une destination.
    """
    decoder, game_state, squad_id, _cell_idx, _dest = move_state
    game_state = copy.deepcopy(game_state)
    anchor_col = int(game_state["unit_by_id"][squad_id]["col"])
    anchor_row = int(game_state["unit_by_id"][squad_id]["row"])
    last_cell = MOVE_CELL_COUNT - 1
    store_squad_move_cell_map(
        game_state, squad_id, {last_cell: ((anchor_col, anchor_row), 0.0)}
    )
    result = decoder.convert_squad_action(
        MOVE_CELL_BASE + last_cell, game_state, eligible_units=_eligible(game_state, squad_id)
    )
    assert result["action"] in MOVE_ACTIONS, result
    assert (result["destCol"], result["destRow"]) == (anchor_col, anchor_row)


# ─────────────────────────────────────────────────────────────────────────────
# Attente — `ACTION_WAIT`
# ─────────────────────────────────────────────────────────────────────────────


def test_wait_action_ends_the_squad_activation(phase_state):
    """`ACTION_WAIT` hors command → `squad_wait` sur l'escouade active."""
    decoder, game_state, squad_id = phase_state("move")
    result = decoder.convert_squad_action(
        ACTION_WAIT, game_state, eligible_units=_eligible(game_state, squad_id)
    )
    assert result == {"action": "squad_wait", "squad_id": squad_id}


def test_wait_action_in_command_phase_is_the_command_pass(phase_state):
    """`ACTION_WAIT` en command → `command_wait` (aucune escouade sélectionnée)."""
    decoder, game_state, squad_id = phase_state("command")
    result = decoder.convert_squad_action(
        ACTION_WAIT, game_state, eligible_units=_eligible(game_state, squad_id)
    )
    assert result == {"action": "command_wait"}


# ─────────────────────────────────────────────────────────────────────────────
# Slots de cible — tir / charge / mêlée
#
# Premier ET dernier slot de chaque famille : les trois plages sont contiguës
# (1025-1044, 1045-1064, 1065-1084), donc un décalage d'une unité fait décoder « je tire sur le
# slot 19 » comme « je charge le slot 0 » — sans que rien ne lève.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("slot", [0, SHOOT_SLOT_COUNT - 1])
def test_shoot_slot_routes_to_that_target_slot(phase_state, slot):
    decoder, game_state, squad_id = phase_state("shoot")
    result = decoder.convert_squad_action(
        SHOOT_SLOT_BASE + slot, game_state, eligible_units=_eligible(game_state, squad_id)
    )
    assert result == {"action": "squad_shoot", "target_slot": slot, "squad_id": squad_id}


@pytest.mark.parametrize("slot", [0, CHARGE_SLOT_COUNT - 1])
def test_charge_slot_routes_to_that_target_slot(phase_state, slot):
    decoder, game_state, squad_id = phase_state("charge")
    result = decoder.convert_squad_action(
        CHARGE_SLOT_BASE + slot, game_state, eligible_units=_eligible(game_state, squad_id)
    )
    assert result == {"action": "squad_charge", "squad_id": squad_id, "target_slot": slot}


@pytest.mark.parametrize("slot", [0, FIGHT_SLOT_COUNT - 1])
def test_fight_slot_routes_to_that_target_slot(phase_state, slot):
    decoder, game_state, squad_id = phase_state("fight")
    result = decoder.convert_squad_action(
        FIGHT_SLOT_BASE + slot, game_state, eligible_units=_eligible(game_state, squad_id)
    )
    assert result == {"action": "squad_fight", "squad_id": squad_id, "target_slot": slot}


def test_fight_without_target_is_a_distinct_intent(phase_state):
    """`ACTION_FIGHT_NO_TARGET` → `squad_fight` SANS `target_slot` (12.04/12.06, combat à vide).

    Absence de `target_slot` = le moteur exige un pool 12.05 vide. Confondre cette action avec le
    dernier slot de mêlée ferait frapper une escouade que le masque n'avait pas autorisée.
    """
    decoder, game_state, squad_id = phase_state("fight")
    result = decoder.convert_squad_action(
        ACTION_FIGHT_NO_TARGET, game_state, eligible_units=_eligible(game_state, squad_id)
    )
    assert result == {"action": "squad_fight", "squad_id": squad_id}
    assert "target_slot" not in result


# ─────────────────────────────────────────────────────────────────────────────
# Zone intents et décisions agent — la frontière `CHOICE_BASE`
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "zone_idx, intent_value", [(0, 0), (0, 2), (1, 1), (MAX_OBJECTIVES - 1, 2)]
)
def test_zone_intent_routes_to_that_zone_and_intent(phase_state, zone_idx, intent_value):
    """`BASE_ZONE_INTENT + 3*zone + intent` → `zone_intent(zone, intent)`.

    Le dernier cas (`zone 4, intent 2`) est `CHOICE_BASE - 1` : la frontière avec les actions de
    choix. Il doit rester un zone intent.
    """
    decoder, game_state, squad_id = phase_state("command")
    result = decoder.convert_squad_action(
        BASE_ZONE_INTENT + zone_idx * 3 + intent_value,
        game_state,
        eligible_units=_eligible(game_state, squad_id),
    )
    assert result == {
        "action": "zone_intent",
        "zone_idx": zone_idx,
        "intent_value": intent_value,
    }


def test_zone_intent_outside_command_phase_raises(phase_state):
    """Hors command, un zone intent LÈVE — pas de repli silencieux sur une action de phase."""
    decoder, game_state, squad_id = phase_state("move")
    with pytest.raises(ValueError, match="zone_intent"):
        decoder.convert_squad_action(
            BASE_ZONE_INTENT, game_state, eligible_units=_eligible(game_state, squad_id)
        )


@pytest.mark.parametrize("option_index", [0, 1])
def test_choice_action_routes_to_that_option(phase_state, option_index):
    """`CHOICE_BASE + i` → `agent_decision` sur le candidat `i` de la décision en attente.

    `CHOICE_BASE` est aussi la borne haute des zone intents : un décalage ferait appliquer le
    candidat i-1 (ou une intention de zone) là où l'agent désignait le candidat i.
    """
    decoder, game_state, squad_id = phase_state("fight")
    set_pending_agent_decision(
        game_state,
        decision_type="rule_choice",
        player=1,
        unit_id=squad_id,
        options=[
            {"label": "A", "effect_ids": ("reroll_1_tohit_fight",), "payload": {"x": 0}},
            {"label": "B", "effect_ids": ("reroll_1_save_fight",), "payload": {"x": 1}},
        ],
    )
    result = decoder.convert_squad_action(
        CHOICE_BASE + option_index,
        game_state,
        eligible_units=_eligible(game_state, squad_id),
    )
    assert result == {"action": "agent_decision", "option_index": option_index}


def test_choice_action_without_pending_decision_raises(phase_state):
    """Une action CHOICE sans décision en attente LÈVE — le masque ne l'aurait pas autorisée."""
    decoder, game_state, squad_id = phase_state("fight")
    with pytest.raises(ValueError, match="sans decision en attente"):
        decoder.convert_squad_action(
            CHOICE_BASE, game_state, eligible_units=_eligible(game_state, squad_id)
        )


def test_choice_slot_count_matches_the_action_space_tail(phase_state):
    """Le dernier `CHOICE` est la DERNIÈRE action de l'espace : au-delà, le décodeur lève."""
    decoder, game_state, squad_id = phase_state("fight")
    with pytest.raises(ValueError, match="non gérée"):
        decoder.convert_squad_action(
            CHOICE_BASE + CHOICE_COUNT,
            game_state,
            eligible_units=_eligible(game_state, squad_id),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Slots de déploiement — `DEPLOY_SLOT_BASE + s`
#
# Ces entiers (4-8) sont AUSSI des cellules de move : c'est la phase qui désambiguïse. Le verrou
# porte donc sur les deux lectures — move ci-dessus, déploiement ici.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("slot", list(range(DEPLOY_SLOT_COUNT)))
def test_deploy_slot_routes_to_the_hex_of_that_strategy(deployment_state, slot):
    """`DEPLOY_SLOT_BASE + s` → l'hex que la stratégie `s` choisit, pas celui d'une voisine.

    La référence est `_select_deployment_hex_for_action`, à qui le décodeur DOIT transmettre
    l'entier reçu tel quel : un décalage d'une unité déploierait sur le flanc d'à côté, dans un
    hex parfaitement valide — donc totalement silencieux.
    """
    decoder, game_state = deployment_state
    result = decoder.convert_squad_action(DEPLOY_SLOT_BASE + slot, game_state)
    assert result["action"] == "deploy_unit"
    deployer = decoder._get_current_deployer(game_state)
    valid_hexes = decoder._get_valid_deployment_hexes(
        game_state, deployer, str(result["unitId"])
    )
    assert (result["destCol"], result["destRow"]) in valid_hexes
    assert (result["destCol"], result["destRow"]) == decoder._select_deployment_hex_for_action(
        action_int=DEPLOY_SLOT_BASE + slot,
        unit_id=str(result["unitId"]),
        game_state=game_state,
        current_deployer=deployer,
        valid_hexes=valid_hexes,
    )


def test_action_outside_the_deployment_slots_raises_in_deployment(deployment_state):
    """En déploiement, un entier hors `DEPLOY_SLOTS` LÈVE — aucune interprétation de repli."""
    decoder, game_state = deployment_state
    with pytest.raises(ValueError, match="invalide en phase deployment"):
        decoder.convert_squad_action(DEPLOY_SLOT_BASE + DEPLOY_SLOT_COUNT, game_state)
