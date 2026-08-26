"""Parité masque/commit de `squad_charge` — la cible de charge est une DIMENSION D'ACTION.

V11 §9 P3-2. Avant cette tranche, `charge` était une action NUE (un seul id) : le masque disait
« une charge est possible », et c'est le décodeur qui choisissait la cible, par
`get_best_enemy_score_for_unit` (damage_ratio). L'agent ne décidait donc rien — alors que 11.02
(« Declare Charge ») et 11.04 (« BEFORE MOVING: select one or more enemy units ») font de la
sélection de la cible un choix de JOUEUR.

Désormais un slot ennemi = une action de charge (`CHARGE_SLOT_BASE + i`), indexé sur le MÊME
mapping `get_enemy_slot_mapping` que le tir et la mêlée (invariant D1), et scoré par une tête
pointeur sur l'embedding de l'ennemi.

Les verrous, dans les DEUX sens :
- le masque n'ouvre un slot que si sa cible est DÉCLARABLE (`charge_check_eligibility`) — et il
  les ouvre TOUS, sans en manquer aucun ;
- le commit refuse tout slot dont la cible n'est pas déclarable, et tout slot vide. Aucun repli
  sur une heuristique : une divergence est une rupture, pas un cas à absorber.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pytest

from smoke_t5_bare import MELEE_SCENARIO  # noqa: E402

from engine.macro_intents import ACTION_WAIT, CHARGE_SLOT_BASE  # noqa: E402
from engine.phase_handlers.shared_utils import (  # noqa: E402
    build_squad_action_mask,
    charge_build_valid_plan,
    charge_check_eligibility,
    get_enemy_slot_mapping,
)
from shared.data_validation import require_key  # noqa: E402


def _engine(scenario_file: str, seed: int):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent", scenario_file=scenario_file,
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    eng.reset(seed=seed)
    return eng


@pytest.fixture()
def melee_scenario_file():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "melee.json"
        path.write_text(json.dumps(MELEE_SCENARIO))
        yield str(path)


def _push_far_away(gs, target_id: str) -> None:
    """Éloigne une escouade bien au-delà des 12" de charge, figurine par figurine.

    `charge_check_eligibility` mesure la figurine la plus proche (pas l'ancre) : déplacer la
    seule entrée `units_cache` laisserait les figurines en place et le prédicat inchangé.
    """
    for mid in gs["squad_models"][target_id]:
        gs["models_cache"][mid]["row"] = int(gs["models_cache"][mid]["row"]) + 400
    gs["units_cache"][target_id]["row"] = int(gs["units_cache"][target_id]["row"]) + 400
    gs["_unit_move_version"] = int(gs.get("_unit_move_version", 0)) + 1


def _charger(gs) -> Tuple[str, List[Optional[str]], List[int]]:
    """(squad_id, mapping de slots, slots déclarables) d'une escouade qui peut charger.

    Le scénario mêlée place un Carnifex à portée de charge d'un Termagant (le smoke T5 en fait
    déjà son critère `carnifex_charge`) : au moins une déclaration est donc possible. Aucune
    trouvée = la fixture ne teste plus rien, donc une ERREUR, pas un `None` à propager.
    """
    our_player = int(gs["current_player"])
    slot_map = get_enemy_slot_mapping(gs, our_player)
    for squad_id in gs["units_cache"]:
        if int(gs["units_cache"][squad_id]["player"]) != our_player:
            continue
        declarable = [
            i for i, esid in enumerate(slot_map)
            if esid is not None and charge_check_eligibility(gs, str(squad_id), [str(esid)])
        ]
        if declarable:
            return str(squad_id), slot_map, declarable
    raise AssertionError(
        "fixture invalide : aucune escouade du joueur actif n'a de cible de charge déclarable"
    )


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_charge_mask_offers_only_committable_actions(melee_scenario_file, seed):
    """Aucune action proposée par le masque ne doit faire échouer le commit.

    Marche aléatoire sur le VRAI chemin gym (masque -> step), donc en traversant la phase de
    charge à chaque tour : un slot ouvert dont la cible ne serait plus déclarable au commit
    lèverait ici.
    """
    eng = _engine(melee_scenario_file, seed)
    for i in range(400):
        if eng.game_state.get("game_over"):
            break
        mask = eng.get_action_mask()
        if not mask.any():
            break
        action = int(np.random.default_rng(seed * 991 + i).choice(np.flatnonzero(mask)))
        eng.step(action)


def test_mask_opens_exactly_the_targets_the_roll_can_reach(melee_scenario_file):
    """Les slots ouverts décrivent EXACTEMENT les cibles ATTEIGNABLES par le jet (11.02 + 11.04).

    Les deux moitiés comptent : un slot ouvert de trop ferait déclarer une charge que le jet ne
    peut pas conclure, un slot manquant rendrait une cible atteignable INCHARGEABLE sans que
    rien ne le signale.

    CE QUI A CHANGE LE 2026-08-11. La référence était `charge_check_eligibility` seule — les 12"
    de 11.02.1 — parce que le jet tombait APRÈS le choix de la cible. Depuis l'alignement sur la
    séquence 11.02, le jet a lieu à l'activation et 11.04 borne les cibles sélectionnables par
    lui : l'ensemble ouvert est donc un SOUS-ENSEMBLE des déclarables, celui que
    `charge_build_valid_plan` — l'oracle du commit — accepte pour ce jet.
    """
    eng = _engine(melee_scenario_file, seed=1)
    gs = eng.game_state
    gs["phase"] = "charge"
    squad_id, slot_map, declarable = _charger(gs)
    assert squad_id is not None, "le scénario mêlée offre au moins une charge déclarable"

    mask = build_squad_action_mask(gs, squad_id, enemy_slot_ids=slot_map)
    opened = [i for i in range(len(slot_map)) if mask[CHARGE_SLOT_BASE + i] == 1]

    charge_roll_values = require_key(gs, "charge_roll_values")
    assert squad_id in charge_roll_values, (
        "build_squad_action_mask doit peupler charge_roll_values pour l'escouade active"
    )
    roll = int(charge_roll_values[squad_id])
    reachable = [
        i for i, esid in enumerate(slot_map)
        if esid is not None
        and charge_build_valid_plan(gs, str(squad_id), [str(esid)], roll) is not None
    ]
    assert opened == reachable
    assert set(opened).issubset(set(declarable)), (
        "un slot ouvert sur une cible non déclarable (11.02.1) : le jet ne peut pas rendre "
        "légale une cible hors des 12\""
    )
    assert mask[ACTION_WAIT] == 1, "11.02 : la charge est OPTIONNELLE, WAIT reste ouvert"

    # CONTRE-ÉPREUVE : le filtre d'éligibilité MORD. Sans elle, un masque qui ouvrirait tout slot
    # non vide passerait le test ci-dessus dès que toutes les cibles mappées sont à portée — ce
    # qui est le cas du scénario au reset. On éloigne une cible au-delà des 12" (11.02) : son
    # slot DOIT se fermer, les autres rester ouverts.
    #
    # closed_slot doit venir de `opened` (slots réellement ouverts par le jet), pas de `declarable`
    # (déclarables ≠ atteignables avec ce jet) : un slot déclarable mais non ouvert serait déjà à
    # 0 avant le push — la preuve serait vacante.
    assert opened, "le scénario doit ouvrir au moins un slot pour la contre-épreuve"
    closed_slot = opened[0]
    target_id = str(slot_map[closed_slot])
    _push_far_away(gs, target_id)
    mask_after = build_squad_action_mask(gs, squad_id, enemy_slot_ids=slot_map)
    assert mask_after[CHARGE_SLOT_BASE + closed_slot] == 0, (
        "cible hors des 12\" : son slot de charge doit se fermer (11.02)"
    )
    # Le jet est caché (setdefault dans charge_roll_for_activation) : les slots restants ouverts
    # sont opened − {closed_slot}, pas declarable − {closed_slot}.
    assert [
        i for i in range(len(slot_map)) if mask_after[CHARGE_SLOT_BASE + i] == 1
    ] == [i for i in opened if i != closed_slot]


def test_commit_charges_the_target_of_the_slot_played(melee_scenario_file):
    """La cible commitée est CELLE que désigne le slot joué — plus le `damage_ratio` du décodeur.

    Contre-épreuve du choix : on joue le DERNIER slot déclarable, pas le premier. Si le moteur
    retombait sur une heuristique, la cible commitée ne suivrait pas le slot.
    """
    eng = _engine(melee_scenario_file, seed=1)
    gs = eng.game_state
    gs["phase"] = "charge"
    squad_id, slot_map, declarable = _charger(gs)
    assert squad_id is not None

    chosen_slot = declarable[-1]
    expected_target = str(slot_map[chosen_slot])
    ok, result = eng._process_squad_action(
        {"action": "squad_charge", "squad_id": squad_id, "target_slot": chosen_slot}
    )
    assert ok is True
    assert result["target_squad_id"] == expected_target
    # Le jet 2D6 (11.02 étape 2) est fait par le moteur, pas par l'agent : la charge peut
    # échouer. C'est un résultat légal — ce que le test verrouille est la CIBLE, pas l'issue.
    # Charge réussie → waiting_for_agent_decision/charge_placement ; échouée → squad_charge.
    assert result["action"] in ("squad_charge", "waiting_for_agent_decision")
    assert "charge_succeeded" in result


def test_decoder_maps_the_action_id_to_its_slot(melee_scenario_file):
    """`CHARGE_SLOT_BASE + i` -> `target_slot = i`, sans décalage ni choix du décodeur.

    C'est l'alignement critique de la tranche : un décalage d'un cran ferait charger l'escouade
    voisine de celle que la tête pointeur a évaluée, sans que rien ne lève.
    """
    eng = _engine(melee_scenario_file, seed=1)
    gs = eng.game_state
    gs["phase"] = "charge"
    squad_id, _slot_map, declarable = _charger(gs)
    assert squad_id is not None

    decoder = eng.action_decoder
    eligible = [u for u in gs["units"] if str(u["id"]) == squad_id]
    for slot_i in declarable:
        semantic = decoder.convert_squad_action(
            CHARGE_SLOT_BASE + slot_i, gs, eligible_units=eligible
        )
        assert semantic == {
            "action": "squad_charge", "squad_id": squad_id, "target_slot": slot_i
        }


def test_commit_refuses_a_non_declarable_slot(melee_scenario_file):
    """Un slot dont la cible n'est PAS déclarable est refusé — jamais absorbé par un repli.

    Sans cette garde, un slot pointant un ennemi à plus de 12" ferait déclarer une charge
    illégale (11.02) sans que rien ne lève.
    """
    eng = _engine(melee_scenario_file, seed=1)
    gs = eng.game_state
    gs["phase"] = "charge"
    squad_id, slot_map, declarable = _charger(gs)
    assert squad_id is not None

    bad_slots = [
        i for i, esid in enumerate(slot_map)
        if esid is not None and i not in declarable
    ]
    if not bad_slots:
        # Aucun ennemi mappé hors de portée : on en fabrique un en éloignant la cible du premier
        # slot déclarable au-delà des 12" (mesure figurine la plus proche, cf.
        # `charge_check_eligibility`).
        _push_far_away(gs, str(slot_map[declarable[0]]))
        bad_slots = [declarable[0]]

    with pytest.raises(ValueError, match="non declarable"):
        eng._process_squad_action(
            {"action": "squad_charge", "squad_id": squad_id, "target_slot": bad_slots[0]}
        )


def test_commit_refuses_an_empty_slot(melee_scenario_file):
    """Un slot VIDE (aucune escouade mappée) est refusé explicitement.

    Le mapping compte 20 slots pour ~6 escouades : la majorité est vide en permanence. Sans
    garde, `None` traverserait jusqu'à `charge_build_valid_plan`.
    """
    eng = _engine(melee_scenario_file, seed=1)
    gs = eng.game_state
    gs["phase"] = "charge"
    squad_id, slot_map, _declarable = _charger(gs)
    assert squad_id is not None
    empty_slots = [i for i, esid in enumerate(slot_map) if esid is None]
    assert empty_slots, "le mapping de 20 slots compte au moins un slot vide"

    with pytest.raises(ValueError, match="slot .* vide"):
        eng._process_squad_action(
            {"action": "squad_charge", "squad_id": squad_id, "target_slot": empty_slots[0]}
        )


def test_no_charge_slot_without_a_declarable_target(melee_scenario_file):
    """Sans cible déclarable, AUCUN slot n'est ouvert — il n'existe pas de « charge à vide ».

    Contrairement au combat (12.04/12.06, où une escouade sélectionnée sans cible résout un
    combat à vide), 11.02 conditionne la déclaration à la présence d'un ennemi à 12" : sans
    cible, l'unité ne déclare rien et seul WAIT reste.
    """
    eng = _engine(melee_scenario_file, seed=1)
    gs = eng.game_state
    gs["phase"] = "charge"
    our_player = int(gs["current_player"])
    squad_id = next(
        sid for sid in gs["units_cache"]
        if int(gs["units_cache"][sid]["player"]) == our_player
    )
    # Tous les ennemis disparaissent : plus aucune cible mappée.
    for sid in [s for s, e in list(gs["units_cache"].items()) if int(e["player"]) != our_player]:
        for mid in list(gs["squad_models"].get(sid, [])):
            gs["models_cache"].pop(mid, None)
        gs["units_cache"].pop(sid, None)

    slot_map = get_enemy_slot_mapping(gs, our_player)
    mask = build_squad_action_mask(gs, squad_id, enemy_slot_ids=slot_map)
    assert not any(mask[CHARGE_SLOT_BASE + i] for i in range(len(slot_map)))
    assert mask[ACTION_WAIT] == 1
