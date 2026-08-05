"""V11 §8.2 — LE verrou d'interface agent : chaque entier d'action → l'intention attendue.

Ce fichier est le contrat que la spec exigeait et qui n'avait jamais été écrit. Il existe pour une
raison précise : `test_action_space_mirror.py` compare les constantes ENTRE ELLES (macro_intents ↔
shared_utils) sans jamais appeler le décodeur. Un miroir cohérent ne prouve rien sur le ROUTAGE :
c'est exactement pourquoi un outil d'évaluation a pu servir au modèle un masque de l'ancien espace
d'actions (0-15) sans que quoi que ce soit ne se plaigne, et pourquoi le décodeur mort
`convert_gym_action` a survécu des mois derrière ~25 tests verts.

Chaque cas ci-dessous APPELLE `ActionDecoder.convert_squad_action` — le seul décodeur vivant — et
vérifie l'intention obtenue. Aucun cas ne se contente de comparer deux constantes.

**Provenance des états — exactement, sans promesse en trop.** Tout part de `W40KEngine.reset()`,
donc d'un `game_state` que le moteur a réellement construit ; aucun dict fabriqué à la main.
Deux régimes, et il faut savoir lequel on lit :

- `driven_state` — le moteur est JOUÉ en actions masquées jusqu'à la phase visée. L'état est
  intégralement cohérent (pools d'activation, carte de cellules mémorisée par le masque, jet
  d'Advance). C'est ce que la production donne au décodeur. Utilisé par les cas de mouvement et
  par la parité masque↔décodeur.
- `phase_state` — copie de l'état post-`reset` dont le champ `phase` est réécrit. C'est un
  raccourci ASSUMÉ, et il n'est légitime que parce que le décodeur, pour ces familles-là, ne lit
  **que** `eligible_units[0]["id"]` : les slots de tir/charge/mêlée ne consultent ni pool ni
  masque (§9 P3-1/P3-2 — la résolution slot → escouade appartient au moteur, la dupliquer ici
  réécrirait la règle). Réécrire `phase` ne peut donc pas fabriquer un routage qui n'existerait
  pas. Le prix de ce raccourci : ces cas ne prouvent rien sur la cohérence de l'état, seulement
  sur le routage — c'est la parité masque↔décodeur qui couvre l'autre moitié.

Dans les deux régimes, les réglages par-épisode dont ce fichier a besoin sont **épinglés sur
l'instance** (`_config_helpers.pin_active_deployment`), jamais lus depuis la config : voir la
docstring de ce helper pour la panne que cette précaution répare.

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
| `4..8` HORS déploiement                   | cellule de move — PAS `deploy_unit`             |

**La propriété qui couvre la classe entière** (`TestMaskDecoderParity`) : pour chaque phase
atteinte en jouant le moteur, **tout entier ouvert par le masque doit être décodable sans
lever**. C'est elle, et non l'énumération ci-dessus, qui attrape un masque périmé, une base
décalée ou une famille d'actions orpheline — sans qu'il faille avoir pensé au cas.

⚠️ La réciproque « tout entier FERMÉ par le masque doit lever au décodage » est **fausse par
construction, et c'est délibéré** : `convert_squad_action` ne consulte aucun masque pour les
familles à slot. `SHOOT_SLOT_BASE + 3` rend `{squad_shoot, target_slot: 3}` quelle que soit la
phase et quel que soit le masque — la vérification d'éligibilité appartient au moteur
(`squad_shoot` / `squad_charge` / `squad_fight` valident contre leurs pools 11.02 / 12.05), et la
dupliquer dans le décodeur réécrirait la règle à deux endroits. Le rejet d'une action hors masque
a donc lieu **une couche plus haut**, dans `validate_action_against_mask`, appelée par
`W40KEngine.step` et `pve_controller` avant tout décodage. C'est cette couche-là que
`test_action_outside_the_mask_is_rejected_before_decoding` verrouille — pas le décodeur.

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

from _config_helpers import assert_deployment_phase, pin_active_deployment
from engine.action_decoder import ActionValidationError
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
    OATH_SLOT_BASE,
    OATH_SLOT_COUNT,
    MOVE_CELL_BASE,
    MOVE_CELL_COUNT,
    SHOOT_SLOT_BASE,
    SHOOT_SLOT_COUNT,
    TOTAL_ACTION_SIZE,
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
    # Déploiement actif garanti + `deployment_random_mix` à l'arrêt. Lus PAR ÉPISODE, donc
    # l'épinglage doit précéder le `reset`. Le POURQUOI est dans `_config_helpers`.
    pin_active_deployment(engine)
    engine.reset(seed=0)
    return engine


@pytest.fixture(scope="module")
def deployment_state() -> Tuple[Any, Dict[str, Any]]:
    """Moteur juste après `reset` : phase deployment, pools de déploiement réels.

    Le déploiement est obtenu par le VRAI chemin moteur — le scheduler tire « active », le
    moteur ouvre une phase de déploiement et construit ses pools. Rien n'est fabriqué : ces cas
    décodent les identifiants 4-8 contre un `deployment_state` que le moteur a rempli lui-même.
    """
    engine = _new_engine()
    assert_deployment_phase(engine)
    return engine.action_decoder, engine.game_state


#: Nombre de pas de jeu joués pour explorer les phases. Volontairement borné : le CPU est
#: partagé, et les phases visées sont atteintes bien avant.
DRIVE_STEPS = 400

#: Phases dont la parité masque↔décodeur DOIT être mesurée. Si l'une cesse d'être atteinte, le
#: test de parité se viderait en silence — d'où la garde `test_parity_covers_the_real_phases`.
REQUIRED_PHASES = ("deployment", "command", "move", "shoot")


@pytest.fixture(scope="module")
def driven() -> Dict[str, Any]:
    """Joue le moteur en actions masquées et capture ce que la PRODUCTION donne au décodeur.

    Rend :
      - `by_phase[phase] = (game_state, mask)` — première occurrence de chaque phase, copiée ;
      - `move_pick` = (squad_id, cell_idx, dest) d'une cellule RÉELLEMENT offerte par le masque,
        relue dans la carte que le masque a mémorisée.

    Un seul moteur pour tout le fichier : la construction domine le coût.
    """
    engine = _new_engine()
    rng = random.Random(0)
    by_phase: Dict[str, Tuple[Dict[str, Any], Any]] = {}
    move_pick = None

    for _ in range(DRIVE_STEPS):
        if move_pick is not None and all(p in by_phase for p in REQUIRED_PHASES):
            break  # tout est capturé : ne pas jouer un pas de plus

        mask = engine.get_action_mask()
        game_state = engine.game_state
        phase = game_state["phase"]

        valid = [i for i, v in enumerate(mask) if v]
        if not valid:
            # Masque vide = auto-avance de phase (pools épuisés) : `W40KEngine.step` la déclenche
            # AVANT de lire l'action, qui est donc ignorée. C'est un état légal, pas une panne —
            # et il ne se capture pas : il n'ouvre aucune action à confronter au décodeur.
            _obs, _r, terminated, truncated, _info = engine.step(0)
            if terminated or truncated:
                break
            continue

        if phase not in by_phase:
            by_phase[phase] = (copy.deepcopy(game_state), mask.copy())

        if move_pick is None and phase == "move":
            for squad_id, stored in (game_state.get(MOVE_CELL_MAP_CACHE_KEY) or {}).items():
                cell_map = stored["map"]
                if cell_map:
                    cell_idx = sorted(cell_map)[0]
                    move_pick = (
                        copy.deepcopy(game_state),
                        str(squad_id),
                        cell_idx,
                        cell_map[cell_idx][0],
                    )
                    break

        _obs, _r, terminated, truncated, _info = engine.step(rng.choice(valid))
        if terminated or truncated:
            break

    assert move_pick is not None, "phase move avec carte de cellules jamais atteinte"
    return {"decoder": engine.action_decoder, "by_phase": by_phase, "move_pick": move_pick}


@pytest.fixture(scope="module")
def move_state(driven) -> Tuple[Any, Dict[str, Any], str, int, Tuple[int, int]]:
    """(decoder, gs, squad_id, cell_idx, dest) — état de phase move réellement joué."""
    game_state, squad_id, cell_idx, dest = driven["move_pick"]
    return driven["decoder"], game_state, squad_id, cell_idx, dest


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


def _anchor(game_state: Dict[str, Any], squad_id: str) -> Tuple[int, int]:
    """Ancre courante de l'escouade — `store_squad_move_cell_map` tamponne la carte dessus."""
    unit = game_state["unit_by_id"][squad_id]
    return int(unit["col"]), int(unit["row"])


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


def test_first_move_cell_is_a_move_and_not_a_deployment_slot(move_state):
    """`MOVE_CELL_BASE + 0` — borne BASSE de la famille move, et début de la zone 4-8 ambiguë."""
    decoder, game_state, squad_id, _cell_idx, _dest = move_state
    game_state = copy.deepcopy(game_state)
    anchor = _anchor(game_state, squad_id)
    store_squad_move_cell_map(game_state, squad_id, {0: (anchor, 0.0)})
    result = decoder.convert_squad_action(
        MOVE_CELL_BASE, game_state, eligible_units=_eligible(game_state, squad_id)
    )
    assert result["action"] in MOVE_ACTIONS, result
    assert (result["destCol"], result["destRow"]) == anchor


# ─────────────────────────────────────────────────────────────────────────────
# Le chevauchement 4-8 — l'ambiguïté la plus dangereuse de l'espace d'actions
#
# Les identifiants `DEPLOY_SLOT_BASE..DEPLOY_SLOT_BASE + 4` (4-8) sont AUSSI des cellules de
# move : `MOVE_CELL_BASE` vaut 0. Rien dans l'entier ne dit lequel des deux il désigne — SEULE
# la phase tranche (cf. §0.44, qui documente le coût de ce partage côté policy). Un jour où la
# garde de phase du décodeur se déplacerait, l'agent déploierait en croyant se déplacer.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("slot", list(range(DEPLOY_SLOT_COUNT)))
def test_deploy_slot_ids_decode_as_move_cells_outside_deployment(move_state, slot):
    """Hors déploiement, `4..8` sont des CELLULES DE MOVE — jamais `deploy_unit`."""
    decoder, game_state, squad_id, _cell_idx, _dest = move_state
    game_state = copy.deepcopy(game_state)
    anchor = _anchor(game_state, squad_id)
    action_int = DEPLOY_SLOT_BASE + slot
    store_squad_move_cell_map(game_state, squad_id, {action_int - MOVE_CELL_BASE: (anchor, 0.0)})
    result = decoder.convert_squad_action(
        action_int, game_state, eligible_units=_eligible(game_state, squad_id)
    )
    assert result["action"] in MOVE_ACTIONS, result
    assert result["action"] != "deploy_unit"
    assert (result["destCol"], result["destRow"]) == anchor


def test_the_same_id_means_two_different_things_in_the_two_phases(move_state, deployment_state):
    """Le MÊME entier rend deux intentions distinctes selon la phase — c'est le contrat.

    Si ce test devenait vert avec une seule et même intention des deux côtés, c'est que la
    désambiguïsation par la phase aurait disparu.
    """
    decoder, move_gs, squad_id, _cell_idx, _dest = move_state
    move_gs = copy.deepcopy(move_gs)
    anchor = _anchor(move_gs, squad_id)
    store_squad_move_cell_map(move_gs, squad_id, {DEPLOY_SLOT_BASE: (anchor, 0.0)})
    as_move = decoder.convert_squad_action(
        DEPLOY_SLOT_BASE, move_gs, eligible_units=_eligible(move_gs, squad_id)
    )

    deploy_decoder, deploy_gs = deployment_state
    as_deploy = deploy_decoder.convert_squad_action(DEPLOY_SLOT_BASE, deploy_gs)

    assert as_move["action"] in MOVE_ACTIONS
    assert as_deploy["action"] == "deploy_unit"
    assert as_move["action"] != as_deploy["action"]


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


@pytest.mark.parametrize("option_index", [0, 1, CHOICE_COUNT - 1])
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
        # CHOICE_COUNT candidats : c'est le seul montage qui rend le DERNIER `CHOICE_i`
        # atteignable, donc qui teste la borne haute de l'espace d'actions.
        options=[
            {
                "label": f"option {i}",
                "effect_ids": ("reroll_1_tohit_fight",) if i % 2 == 0 else ("reroll_1_save_fight",),
                "payload": {"x": i},
            }
            for i in range(CHOICE_COUNT)
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
    """Ce qui suit le dernier `CHOICE` est le bloc d'Oath, et rien d'autre.

    Le test affirmait auparavant que `CHOICE_BASE + CHOICE_COUNT` était HORS de l'espace : c'était
    vrai avant que le chantier 01 ne déclare `OATH_SLOTS`, et cela restait vert par accident —
    ces ids tombaient dans la branche « action non gérée ». Ils ont désormais un décodage propre
    (chantier 03), donc le contrat à verrouiller est celui-ci : l'id juste après les `CHOICE` est
    le premier slot d'Oath, et la VRAIE queue de l'espace est `TOTAL_ACTION_SIZE`.
    """
    decoder, game_state, squad_id = phase_state("fight")
    assert CHOICE_BASE + CHOICE_COUNT == OATH_SLOT_BASE
    assert OATH_SLOT_BASE + OATH_SLOT_COUNT == TOTAL_ACTION_SIZE
    # Hors d'une désignation d'Oath en attente, le slot LÈVE — le masque ne l'ouvre pas.
    with pytest.raises(ValueError, match="sans designation"):
        decoder.convert_squad_action(
            OATH_SLOT_BASE,
            game_state,
            eligible_units=_eligible(game_state, squad_id),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Slots de déploiement — `DEPLOY_SLOT_BASE + s`
#
# La lecture « cellule de move » des mêmes entiers est testée plus haut
# (`test_deploy_slot_ids_decode_as_move_cells_outside_deployment`).
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


# ─────────────────────────────────────────────────────────────────────────────
# PARITÉ MASQUE ↔ DÉCODEUR — la propriété qui couvre la classe entière
#
# Les cas ci-dessus énumèrent des familles ; celui-ci n'énumère rien. Il prend le masque que la
# PRODUCTION construit, à chaque phase réellement atteinte, et exige que TOUT entier qu'il ouvre
# soit décodable. C'est la propriété que le défaut d'origine violait : un masque de l'ancien
# espace, servi à un modèle qui parlait le nouveau, ouvrait des entiers que le décodeur vivant
# n'aurait pas su router — et rien ne levait, parce que personne ne confrontait les deux.
#
# Elle attrape aussi ce qu'aucune énumération ne verrait venir : une base décalée, une famille
# d'actions ajoutée au masque sans branche de décodage, un masque qui déborde l'espace.
# ─────────────────────────────────────────────────────────────────────────────


class TestMaskDecoderParity:
    def test_parity_covers_the_real_phases(self, driven):
        """Garde anti-vacuité : sans elle, la parité passerait sur zéro phase sans rien dire."""
        missing = [p for p in REQUIRED_PHASES if p not in driven["by_phase"]]
        assert not missing, (
            f"phases jamais atteintes en {DRIVE_STEPS} pas : {missing} — la parité ne les "
            f"mesure donc pas. Corriger le pilotage, pas la liste."
        )
        # Largeur, pas seulement présence : un masque réduit à « wait » dans chaque phase
        # satisferait la ligne ci-dessus tout en ne confrontant plus rien. Mesuré à 166 actions
        # le 2026-07-29 (144 en move, 16 en command, 5 en deployment, 1 en shoot) — un ORDRE DE
        # GRANDEUR, pas un contrat : il dépend du plateau et de la trajectoire tirée. Le seuil
        # est délibérément bas pour ne verrouiller que l'effondrement.
        total_open = sum(int(mask.sum()) for _gs, mask in driven["by_phase"].values())
        assert total_open >= 50, (
            f"seulement {total_open} actions ouvertes au total : la parité est devenue "
            f"quasi vide et ne prouve plus grand-chose."
        )

    @pytest.mark.parametrize("phase", REQUIRED_PHASES)
    def test_every_masked_action_is_decodable(self, driven, phase):
        """Tout entier OUVERT par le masque se décode sans lever, dans la phase où il est ouvert."""
        decoder = driven["decoder"]
        game_state, mask = driven["by_phase"][phase]
        game_state = copy.deepcopy(game_state)

        assert len(mask) == TOTAL_ACTION_SIZE, (
            f"masque de longueur {len(mask)} pour un espace de {TOTAL_ACTION_SIZE} actions"
        )
        open_actions = [int(i) for i, v in enumerate(mask) if v]
        assert open_actions, f"masque vide en phase {phase}"

        failures = []
        for action_int in open_actions:
            try:
                intent = decoder.convert_squad_action(action_int, game_state)
            except Exception as exc:  # noqa: BLE001 — on rapporte, on ne masque pas
                failures.append(f"{action_int} → {type(exc).__name__}: {exc}")
                continue
            if not isinstance(intent, dict) or "action" not in intent:
                failures.append(f"{action_int} → intention sans clé 'action' : {intent!r}")

        assert not failures, (
            f"phase {phase} : {len(failures)}/{len(open_actions)} actions OUVERTES par le masque "
            f"sont indécodables — le masque et le décodeur ne parlent pas le même espace.\n"
            + "\n".join(failures[:10])
        )

    def test_action_outside_the_mask_is_rejected_before_decoding(self, driven):
        """La réciproque vit UNE COUCHE PLUS HAUT — et c'est délibéré.

        `convert_squad_action` ne consulte aucun masque pour les familles à slot : la
        vérification d'éligibilité appartient au moteur (§9 P3-1/P3-2), la dupliquer dans le
        décodeur réécrirait la règle à deux endroits. Le rejet d'une action hors masque est donc
        fait par `validate_action_against_mask`, que `W40KEngine.step` et `pve_controller`
        appellent AVANT tout décodage. C'est cette garde-là qu'on verrouille ici : sans elle,
        « tout entier ouvert est décodable » laisserait passer n'importe quel entier fermé.
        """
        decoder = driven["decoder"]
        game_state, mask = driven["by_phase"]["move"]
        closed = [int(i) for i, v in enumerate(mask) if not v]
        assert closed, "masque entièrement ouvert : le cas testé n'existe pas"

        with pytest.raises(ActionValidationError) as exc:
            decoder.validate_action_against_mask(
                closed[0], mask, game_state["phase"], "test_parity"
            )
        assert exc.value.code == "masked_out"
