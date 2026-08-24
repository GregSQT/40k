"""V11 §0.48 élément `L2` / §9 P3-3 — l'AGENT choisit quelle escouade activer.

Avant `L2`, l'escouade activée était TOUJOURS `eligible_units[0]` : l'ordre d'activation, c'est-à-dire
la première décision de chaque phase, échappait entièrement à l'agent. Ce fichier verrouille ce que
`L2` met à la place, et rien d'autre.

**Ce qui est verrouillé ici, et pourquoi chaque verrou existe :**

| verrou | le défaut qu'il attrape |
|---|---|
| D1 côté allié | l'action `ACTIVATE_SLOT_i` et la ligne `allies_*[i]` désignent deux escouades |
| masque exclusif | une action de phase reste jouable alors que le choix n'est pas fait |
| le choix PORTE | l'agent désigne B, le moteur active quand même la tête du pool |
| pool à 1 | un step gym brûlé pour une décision à une seule option |
| auto-péremption | le marqueur survit à l'activation et rejoue le choix, ou le fige |
| slot fermé | le décodeur invente une escouade pour un slot que le masque n'ouvrait pas |

⚠️ Tout part d'un `W40KEngine.reset()` puis d'un moteur JOUÉ en actions masquées — aucun `game_state`
fabriqué à la main. C'est indispensable ici : `L2` porte sur des POOLS d'activation, et un pool
inventé prouverait le routage sans rien prouver sur ce que la production donne au décodeur.
"""

import copy
import random
from typing import Any, Dict, List, Optional, Tuple

import pytest

from tests.unit.engine._config_helpers import pin_active_deployment
from engine.macro_intents import (
    ACTIVATE_SLOT_BASE,
    ACTIVATE_SLOT_COUNT,
    COHERENCY_SLOT_BASE,
    COHERENCY_SLOT_COUNT,
    FIGHT_WEAPON_SLOT_BASE,
    FIGHT_WEAPON_SLOT_COUNT,
    SHOOT_WEAPON_SEL_SLOT_BASE,
    SHOOT_WEAPON_SEL_SLOT_COUNT,
    TOTAL_ACTION_SIZE,
    action_family,
)
from engine.observation_entities import K_ALLY_SLOTS, unit_cont_index
from engine.phase_handlers.shared_utils import SQUAD_ACTION_WAIT, get_ally_slot_mapping

SCENARIO = "config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon1.json"

#: Phases où le choix d'activation se pose. Doit rester le miroir de
#: `ActionDecoder.ACTIVATION_CHOICE_PHASES` — verrouillé ci-dessous.
CHOICE_PHASES = ("move", "shoot", "charge", "fight")

#: Borne d'exploration. Volontairement large : il faut atteindre une phase où le pool compte AU
#: MOINS DEUX escouades, ce qui n'arrive pas au premier pas.
DRIVE_STEPS = 400


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
    pin_active_deployment(engine)
    engine.reset(seed=0)
    return engine


def _drive_to_activation_choice(engine, *, max_steps: int = DRIVE_STEPS):
    """Joue le moteur jusqu'à un état où un CHOIX D'ACTIVATION est réellement posé.

    Rend `(game_state, mask, slots)` ou None. On ne fabrique rien : c'est le masque de production
    qui décide si le choix est posé, et `slots` est relu dans la source unique du décodeur.
    """
    rng = random.Random(0)
    for _ in range(max_steps):
        mask = engine.get_action_mask()
        game_state = engine.game_state
        valid = [i for i, v in enumerate(mask) if v]
        if not valid:
            _obs, _r, terminated, truncated, _info = engine.step(0)
            if terminated or truncated:
                return None
            continue
        slots = engine.action_decoder.activation_selection_slots(game_state)
        if slots is not None:
            return game_state, mask, slots
        _obs, _r, terminated, truncated, _info = engine.step(rng.choice(valid))
        if terminated or truncated:
            return None
    return None


@pytest.fixture(scope="module")
def choice_point():
    """Premier point de choix d'activation atteint par le VRAI chemin moteur."""
    engine = _new_engine()
    found = _drive_to_activation_choice(engine)
    assert found is not None, (
        "aucun choix d'activation atteint en "
        f"{DRIVE_STEPS} pas — le verrou entier serait VERT SANS RIEN REGARDER"
    )
    game_state, mask, slots = found
    return {
        "engine": engine,
        "decoder": engine.action_decoder,
        "game_state": game_state,
        "mask": mask,
        "slots": slots,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Invariant D1, côté allié
# ─────────────────────────────────────────────────────────────────────────────


def test_activate_slot_count_equals_the_ally_tensor_rows():
    """Le nombre de slots d'activation est celui des lignes alliées — pas une valeur parallèle."""
    from engine.observation_builder import ObservationBuilder

    assert ACTIVATE_SLOT_COUNT == K_ALLY_SLOTS
    assert ObservationBuilder.squad_obs_shapes()["allies_cont"][0] == ACTIVATE_SLOT_COUNT
    assert ACTIVATE_SLOT_BASE + ACTIVATE_SLOT_COUNT == FIGHT_WEAPON_SLOT_BASE
    assert FIGHT_WEAPON_SLOT_BASE + FIGHT_WEAPON_SLOT_COUNT == COHERENCY_SLOT_BASE
    assert COHERENCY_SLOT_BASE + COHERENCY_SLOT_COUNT == SHOOT_WEAPON_SEL_SLOT_BASE
    assert SHOOT_WEAPON_SEL_SLOT_BASE + SHOOT_WEAPON_SEL_SLOT_COUNT == TOTAL_ACTION_SIZE


def test_choice_phases_mirror_the_decoder(choice_point):
    """La liste de phases du test EST celle du décodeur — sinon le fichier teste autre chose."""
    assert tuple(choice_point["decoder"].ACTIVATION_CHOICE_PHASES) == CHOICE_PHASES


def test_action_slot_i_designates_the_squad_observed_on_ally_row_i(choice_point):
    """D1, CÔTÉ ALLIÉ — le cœur du fichier.

    L'observation est construite pour l'ancre `eligible_units[0]`, exactement comme en production
    (`W40KEngine._build_observation_and_mask`). On vérifie que la ligne `i` du tenseur allié décrit
    l'escouade que `ACTIVATE_SLOT_BASE + i` activerait.

    L'identité est établie sur des grandeurs de l'escouade RELUES DANS `game_state` — jamais
    ré-encodées ici : ré-implémenter l'encodeur ferait passer le test même si l'ordre divergeait.
    Une garde vérifie d'abord que ces grandeurs distinguent réellement les escouades du mapping,
    sinon le verrou serait VERT VACANT (il comparerait des lignes indiscernables).
    """
    engine = choice_point["engine"]
    game_state = choice_point["game_state"]
    decoder = choice_point["decoder"]

    eligible = decoder._get_eligible_units_for_current_phase(game_state)
    anchor_id = str(eligible[0]["id"])
    our_player = int(game_state["units_cache"][anchor_id]["player"])
    mapping = get_ally_slot_mapping(game_state, our_player, anchor_id)

    obs = engine.obs_builder.build_squad_observation(game_state, anchor_id)
    allies_cont = obs["allies_cont"]
    i_alive = unit_cont_index("alive_models")
    i_hp = unit_cont_index("hp_total")

    def signature(sid: str) -> Tuple[float, float]:
        entry = game_state["units_cache"][sid]
        alive = sum(
            1
            for mid in game_state["squad_models"][sid]
            if int(game_state["models_cache"][mid]["HP_CUR"]) > 0
        )
        return float(alive), float(entry["HP_CUR"])

    present = [(row, sid) for row, sid in enumerate(mapping) if sid is not None]
    assert len(present) >= 2, "mapping à moins de 2 escouades : rien à distinguer"

    # GARDE ANTI-VERT-VACANT : si deux escouades partagent la même signature, l'égalité
    # ligne↔escouade ci-dessous passerait même sur un mapping permuté.
    signatures = [signature(sid) for _row, sid in present]
    assert len(set(signatures)) == len(signatures), (
        "les escouades du mapping ne sont pas distinguables par (effectif, PV) : "
        f"{signatures} — ce test ne prouverait rien"
    )

    for row, sid in present:
        expected_alive, expected_hp = signature(sid)
        assert float(allies_cont[row][i_alive]) == expected_alive, (
            f"ligne alliée {row} : effectif {allies_cont[row][i_alive]} au lieu de "
            f"{expected_alive} — la ligne ne décrit pas l'escouade {sid} que "
            f"ACTIVATE_SLOT_{row} activerait (invariant D1 rompu)"
        )
        assert float(allies_cont[row][i_hp]) == expected_hp

    # Les slots OUVERTS sont un sous-ensemble du mapping, au même index.
    for action_int, sid in choice_point["slots"].items():
        assert mapping[action_int - ACTIVATE_SLOT_BASE] == sid


def test_row_zero_is_the_observation_anchor(choice_point):
    """La ligne 0 est l'ancre de l'observation — pas « une escouade quelconque du joueur ».

    C'est ce qui autorise le masque à rendre `eligible_units` au lieu de `[]` : l'ancre du mapping
    et l'ancre de l'observation doivent être la MÊME escouade.
    """
    decoder = choice_point["decoder"]
    game_state = choice_point["game_state"]
    eligible = decoder._get_eligible_units_for_current_phase(game_state)
    anchor_id = str(eligible[0]["id"])
    our_player = int(game_state["units_cache"][anchor_id]["player"])
    assert get_ally_slot_mapping(game_state, our_player, anchor_id)[0] == anchor_id
    # Le slot 0 est donc TOUJOURS ouvert : le masque d'activation n'est jamais tout-faux.
    assert ACTIVATE_SLOT_BASE in choice_point["slots"]


# ─────────────────────────────────────────────────────────────────────────────
# Exclusivité du masque
# ─────────────────────────────────────────────────────────────────────────────


def test_the_mask_opens_activation_slots_and_nothing_else(choice_point):
    """Tant que le choix n'est pas joué, AUCUNE action de phase n'est ouverte.

    Sans cette exclusivité, l'agent pourrait faire agir la tête du pool sans jamais choisir : le
    choix deviendrait facultatif, donc mort — c'est exactement l'état d'avant `L2`.
    """
    mask = choice_point["mask"]
    opened = {i for i, v in enumerate(mask) if v}
    assert opened, "masque vide au point de choix"
    assert opened == set(choice_point["slots"]), (
        f"le masque ouvre {sorted(opened - set(choice_point['slots']))} hors des slots "
        "d'activation — l'exclusivité est rompue"
    )
    for action_int in opened:
        assert action_family(action_int, choice_point["game_state"]["phase"]) == "activate_slot"


def test_every_opened_slot_is_decodable(choice_point):
    """Parité masque↔décodeur sur la nouvelle famille : tout entier ouvert doit se décoder."""
    decoder = choice_point["decoder"]
    game_state = choice_point["game_state"]
    for action_int, expected_sid in choice_point["slots"].items():
        semantic = decoder.convert_squad_action(action_int, game_state)
        assert semantic == {"action": "select_activation", "unitId": expected_sid}


def test_a_closed_slot_is_refused_never_reinterpreted(choice_point):
    """Un slot d'activation fermé LÈVE — il n'invente pas d'escouade.

    Le décodeur relit la source unique du masque ; s'il recalculait le mapping pour son compte, un
    slot fermé rendrait quand même une escouade et l'agent activerait quelqu'un que le masque
    n'avait pas proposé.
    """
    decoder = choice_point["decoder"]
    game_state = choice_point["game_state"]
    closed = [
        ACTIVATE_SLOT_BASE + i
        for i in range(ACTIVATE_SLOT_COUNT)
        if ACTIVATE_SLOT_BASE + i not in choice_point["slots"]
    ]
    assert closed, "tous les slots sont ouverts : ce cas ne regarde rien"
    with pytest.raises(ValueError, match="FERME"):
        decoder.convert_squad_action(closed[0], game_state)


# ─────────────────────────────────────────────────────────────────────────────
# Le choix PORTE — le verrou qui prouve que `L2` fait quelque chose
# ─────────────────────────────────────────────────────────────────────────────


def test_choosing_a_non_head_squad_activates_that_squad():
    """Désigner une escouade qui N'EST PAS la tête du pool la fait passer en tête.

    C'est LE verrou de `L2` : sans lui, tout le reste peut être vert alors que le moteur continue
    d'activer `eligible_units[0]` et que le choix de l'agent est ignoré.
    """
    engine = _new_engine()
    found = _drive_to_activation_choice(engine)
    assert found is not None
    game_state, _mask, slots = found
    decoder = engine.action_decoder

    head_id = str(decoder._get_eligible_units_for_current_phase(game_state)[0]["id"])
    others = sorted(a for a, sid in slots.items() if sid != head_id)
    assert others, (
        "un seul candidat ouvert : impossible de prouver que le choix change quoi que ce soit"
    )
    target_action = others[0]
    target_id = slots[target_action]
    assert target_id != head_id

    _obs, _reward, _term, _trunc, _info = engine.step(target_action)

    after = decoder._get_eligible_units_for_current_phase(engine.game_state)
    assert str(after[0]["id"]) == target_id, (
        f"l'agent a désigné {target_id} mais le pool présente {after[0]['id']} en tête — "
        "le choix n'a aucun effet"
    )
    # Et le pool n'a PERDU personne au passage : on réordonne, on ne filtre pas.
    assert {str(u["id"]) for u in after} == {
        str(u["id"]) for u in decoder._raw_eligible_units_for_current_phase(engine.game_state)
    }


def test_the_choice_costs_no_reward():
    """Choisir ne rapporte rien : l'effet se mesure dans l'activation qui suit.

    Une prime au choix pousserait l'agent vers les décisions plutôt que vers leurs effets — même
    doctrine que `agent_decision` (`engine/reward_calculator.py`).
    """
    engine = _new_engine()
    found = _drive_to_activation_choice(engine)
    assert found is not None
    _game_state, _mask, slots = found
    _obs, reward, _term, _trunc, _info = engine.step(sorted(slots)[0])
    assert reward == 0.0


def test_the_advance_roll_is_not_revealed_before_the_squad_is_selected():
    """09.03 — le jet d'Advance se fait quand l'unité est SÉLECTIONNÉE, pas avant.

    Le masque prépare la carte de cellules de l'ancre dès le step de choix (la grille égocentrique
    de l'observation la relit, sans repli). Si cette préparation tirait le jet d'Advance, elle le
    MONTRERAIT à l'agent — via les cellules Advance de la grille — avant qu'il ne décide qui
    activer, et pour la seule ancre du pool. Le jet ne doit donc apparaître qu'après le choix.
    """
    engine = _new_engine()
    found = None
    rng = random.Random(0)
    for _ in range(DRIVE_STEPS):
        mask = engine.get_action_mask()
        valid = [i for i, v in enumerate(mask) if v]
        if not valid:
            _o, _r, term, trunc, _i = engine.step(0)
            if term or trunc:
                break
            continue
        slots = engine.action_decoder.activation_selection_slots(engine.game_state)
        if slots is not None and engine.game_state["phase"] == "move":
            found = slots
            break
        _o, _r, term, trunc, _i = engine.step(rng.choice(valid))
        if term or trunc:
            break
    assert found is not None, "aucun choix d'activation atteint EN PHASE MOVE"

    rolls_before = dict(engine.game_state.get("_squad_advance_rolls") or {})
    head_id = str(engine.action_decoder._get_eligible_units_for_current_phase(engine.game_state)[0]["id"])
    assert head_id not in rolls_before, (
        f"le jet d'Advance de {head_id} est déjà tiré au step de CHOIX : il est révélé à l'agent "
        "avant la sélection (09.03)"
    )

    # Après le choix, l'escouade DÉSIGNÉE est sélectionnée : son jet est tiré, et lui seul.
    chosen_action = sorted(found)[0]
    chosen_id = found[chosen_action]
    engine.step(chosen_action)
    engine.get_action_mask()
    rolls_after = engine.game_state.get("_squad_advance_rolls") or {}
    assert chosen_id in rolls_after, (
        f"le jet d'Advance de l'escouade choisie {chosen_id} n'a pas été tiré après sa sélection"
    )


def _put_marker(decoder, game_state, squad_id: str) -> None:
    """Pose le marqueur EXACTEMENT comme `_handle_select_activation_action` — portée comprise."""
    game_state[decoder.ACTIVATION_CHOSEN_KEY] = {
        "squad_id": str(squad_id),
        "scope": decoder.activation_choice_scope(game_state),
    }


def test_a_single_open_slot_poses_no_choice_even_when_the_pool_holds_two(choice_point):
    """La garde porte sur les SLOTS OUVERTS, pas sur la taille du pool.

    Les deux comptes diffèrent : une escouade en réserves stratégiques est éligible en phase de
    mouvement (ingress 20.04) mais n'a pas de ligne alliée, donc pas de slot. Un pool de deux dont
    l'une est en réserves n'ouvrait alors qu'UNE action — un step gym brûlé pour aucune
    information, et l'escouade en réserves inadressable. Garder `len(eligible_units) < 2`
    laisserait ce cas passer.
    """
    decoder = choice_point["decoder"]
    game_state = copy.deepcopy(choice_point["game_state"])
    eligible = decoder._get_eligible_units_for_current_phase(game_state)
    assert len(eligible) >= 2
    assert decoder.activation_selection_slots(game_state, eligible) is not None
    assert decoder.activation_selection_slots(game_state, eligible[:1]) is None
    assert decoder.activation_selection_slots(game_state, []) is None

    # Pool de DEUX dont la seconde n'a aucune ligne alliée : un seul slot ouvert, donc pas de choix.
    # L'intruse est une escouade ADVERSE — comme une escouade en réserves, elle est absente de
    # `get_ally_slot_mapping`, ce qui reproduit exactement la forme du défaut sans dépendre d'un
    # état de réserves qu'il faudrait fabriquer.
    anchor_player = int(game_state["units_cache"][str(eligible[0]["id"])]["player"])
    foreign = next(
        u for u in game_state["units"]
        if int(game_state["units_cache"][str(u["id"])]["player"]) != anchor_player
    )
    slots = decoder.activation_selection_slots(game_state, [eligible[0], foreign])
    assert slots is None, (
        f"un choix a été posé avec un seul slot adressable : {slots}"
    )


def test_the_marker_expires_when_the_squad_leaves_the_pool(choice_point):
    """Le marqueur meurt quand l'escouade sort du pool — fin d'activation, mort."""
    decoder = choice_point["decoder"]
    game_state = copy.deepcopy(choice_point["game_state"])
    eligible = decoder._get_eligible_units_for_current_phase(game_state)
    chosen_id = str(eligible[-1]["id"])

    _put_marker(decoder, game_state, chosen_id)
    # Tant que l'escouade est dans le pool : plus aucun choix posé, et elle est en tête.
    assert decoder.activation_selection_slots(game_state) is None
    assert str(decoder._get_eligible_units_for_current_phase(game_state)[0]["id"]) == chosen_id

    # Hors du pool, le marqueur ne vaut plus rien et le choix est REPOSÉ — sans effacement.
    survivors = [u for u in eligible if str(u["id"]) != chosen_id]
    assert decoder.activation_selection_slots(game_state, survivors) is not None


def test_the_marker_does_not_survive_a_phase_change(choice_point):
    """Un marqueur de la phase move ne doit PAS supprimer le choix de la phase de tir.

    Les pools sont PAR PHASE : une escouade qui a fini de bouger est toujours dans le pool de tir.
    « Sortir du pool » ne périme donc pas le marqueur au changement de phase — c'est sa PORTÉE
    (tour, phase, joueur) qui le fait. Sans elle, mesuré : 9 des 20 premières activations à
    pool ≥ 2 se faisaient sans qu'aucun choix ne soit proposé, forcées sur l'escouade précédente.

    ⚠️ Ce cas construit un VRAI changement de phase. La version précédente de ce fichier ne
    simulait que la sortie du pool et restait verte sur le défaut.
    """
    decoder = choice_point["decoder"]
    game_state = copy.deepcopy(choice_point["game_state"])
    eligible = decoder._get_eligible_units_for_current_phase(game_state)
    chosen_id = str(eligible[-1]["id"])
    _put_marker(decoder, game_state, chosen_id)
    assert decoder.activation_selection_slots(game_state) is None  # honoré dans SA phase

    for other_phase in (p for p in CHOICE_PHASES if p != game_state["phase"]):
        moved = copy.deepcopy(game_state)
        moved["phase"] = other_phase
        assert decoder.current_activation_choice(moved) is None, (
            f"le marqueur de la phase {game_state['phase']} est encore honoré en {other_phase}"
        )

    # Même phase, TOUR suivant : le pool est reconstruit, le marqueur ne doit pas ressusciter.
    next_turn = copy.deepcopy(game_state)
    next_turn["turn"] = int(next_turn["turn"]) + 1
    assert decoder.current_activation_choice(next_turn) is None

    # Même phase, même tour, JOUEUR suivant.
    other_player = copy.deepcopy(game_state)
    other_player["current_player"] = 3 - int(other_player["current_player"])
    assert decoder.current_activation_choice(other_player) is None


def test_the_marker_does_not_survive_reset():
    """Un état d'ÉPISODE qui survit à l'épisode redevient valide par coïncidence.

    La portée du marqueur est (tour, phase, joueur) : au `reset` suivant le tour repart à 1, donc
    un marqueur laissé en place redeviendrait honoré et supprimerait le premier choix de sa phase,
    en silence. `reset()` doit donc le purger explicitement.
    """
    engine = _new_engine()
    found = _drive_to_activation_choice(engine)
    assert found is not None
    _gs, _mask, slots = found
    engine.step(sorted(slots)[0])
    assert engine.game_state.get(engine.action_decoder.ACTIVATION_CHOSEN_KEY) is not None

    engine.reset(seed=1)
    assert engine.game_state.get(engine.action_decoder.ACTIVATION_CHOSEN_KEY) is None, (
        "le marqueur d'activation a survécu au reset : il supprimera un choix de l'épisode suivant"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TRAIN/SERVE — le choix de tir doit être le MÊME quand le joueur est piloté par l'IA
#
# `active_shooting_unit` était épinglé sur la tête du pool à la CONSTRUCTION de celui-ci, donc
# avant tout choix : le pool se réduisait à une escouade (`_raw_eligible_units_for_current_phase`)
# et la décision `ACTIVATE_SLOT` disparaissait. Or `player_types[...] == "ai"` n'est vrai qu'en
# PvE : en entraînement les deux joueurs sont "human", l'épinglage n'arrivait jamais et le choix
# était bien posé. L'agent était donc entraîné à choisir qui tire et privé de ce choix au service.
# Cette clé n'était en outre JAMAIS libérée sur le chemin d'activation de l'agent, si bien que la
# 2e activation de tir de l'IA levait `active_shooting_unit X is not in shoot_activation_pool`.
# Les deux cas ci-dessous verrouillent le contrat qui remplace tout ça : la clé désigne une
# activation de tir EN COURS, et l'activation de l'agent étant ATOMIQUE, elle n'est jamais posée
# sur ce chemin — donc jamais périmée, et le pool reste entier devant le choix.
# ─────────────────────────────────────────────────────────────────────────────


def _drive_and_record_shooting(engine, *, max_steps: int = DRIVE_STEPS):
    """Joue le moteur et relève, à chaque pas de phase de tir, ce que le DÉCODEUR voit.

    Rien n'est fabriqué : c'est l'état de production, lu juste avant que le masque ne soit
    consommé. Une exception moteur n'est pas rattrapée — c'était précisément le symptôme
    (`ValueError` avalé par `execute_ai_turn` en PvE).
    """
    rng = random.Random(0)
    records = []
    for _ in range(max_steps):
        game_state = engine.game_state
        if game_state["phase"] == "shoot":
            decoder = engine.action_decoder
            # Appelé pour son EFFET : c'est ce contrôle qui lève sur une clé périmée. Sa valeur
            # n'est pas relevée — les deux cas ci-dessous s'appuient sur le pool, pas sur elle.
            decoder._raw_eligible_units_for_current_phase(game_state)
            records.append(
                {
                    "turn": int(game_state["turn"]),
                    "player": int(game_state["current_player"]),
                    "pool": [str(uid) for uid in game_state["shoot_activation_pool"]],
                    "active": game_state.get("active_shooting_unit"),
                    "has_choice": decoder.activation_selection_slots(game_state) is not None,
                }
            )
        mask = engine.get_action_mask()
        valid = [i for i, v in enumerate(mask) if v]
        _o, _r, term, trunc, _i = engine.step(rng.choice(valid) if valid else 0)
        if term or trunc:
            break
    return records


#: Joueur piloté par le modèle en PvE. `_build_player_types` (api_server) rend
#: `{"1": "human", "2": "ai"}` : c'est le joueur 2, et lui seul, qui déclenchait l'épinglage.
AI_PLAYER = 2


@pytest.fixture(scope="module")
def shooting_records_in_pve_mode():
    """UN seul pilotage partagé par les cas PvE — miroir de la fixture `choice_point`.

    La table `player_types` est celle que `_build_player_types` monte réellement en PvE
    (`{"1": "human", "2": "ai"}`), pas un `ai/ai` de convenance : c'est le joueur 2 seul qui
    déclenchait l'épinglage, et le poser des deux côtés effacerait la seule asymétrie qui compte.
    `pve_mode` est levé comme le fait `/api/game/new`, pour que les gardes qui le lisent voient
    la même configuration qu'au service.

    Ce que ce montage NE couvre pas, et que seule une session navigateur couvre : l'inférence de
    la politique (`pve_controller`, qui exige un modèle chargé) et la sérialisation API. Le défaut
    corrigé était dans le moteur, en aval de la politique — c'est ce moteur-là qui est piloté ici,
    par le même `_process_squad_action` qu'appelle `execute_ai_turn`.

    Les cas posent plusieurs questions sur la MÊME trajectoire ; la rejouer coûtait un drive de
    400 pas (~28 s) par cas pour un relevé identique au bit près. La liste est lue seule.
    """
    engine = _new_engine()
    engine.game_state["player_types"] = {"1": "human", "2": "ai"}
    engine.is_pve_mode = True
    engine.config["pve_mode"] = True
    records = _drive_and_record_shooting(engine)
    ai_records = [r for r in records if r["player"] == AI_PLAYER]
    assert ai_records, (
        f"aucune phase de tir du joueur {AI_PLAYER} (le seul piloté par l'IA) atteinte — les cas "
        "PvE seraient VERTS SANS RIEN REGARDER, ou verts sur les seules phases du joueur humain"
    )
    return records


def test_the_shooting_choice_is_posed_when_the_player_is_ai(shooting_records_in_pve_mode):
    """Le choix d'activation de tir existe AUSSI pour le joueur piloté par l'IA (PvE).

    C'est le contrat train/serve : la phase de tir du joueur `"ai"` doit poser exactement les
    mêmes décisions qu'en entraînement. Le verrou porte sur les deux moitiés du défaut d'origine :
    le pool brut n'est jamais réduit à une escouade par la clé, et un choix EST réellement posé.

    Toutes les assertions sont bornées au joueur `"ai"` — sur l'ensemble des relevés elles
    passeraient sur les seules phases du joueur humain, qui n'ont jamais été touchées.
    """
    ai_records = [r for r in shooting_records_in_pve_mode if r["player"] == AI_PLAYER]
    pinned = [r for r in ai_records if r["active"] is not None]
    assert not pinned, (
        "le décodeur voit `active_shooting_unit` posée hors d'une activation en cours "
        f"({pinned[0]}) : le pool est réduit à cette escouade et le choix disparaît"
    )
    with_pool = [r for r in ai_records if len(r["pool"]) >= 2]
    assert with_pool, (
        f"aucune phase de tir à pool ≥ 2 pour le joueur {AI_PLAYER} — l'assertion suivante serait "
        "VERTE SANS RIEN REGARDER"
    )
    assert any(r["has_choice"] for r in with_pool), (
        f"aucun choix d'activation posé pour le joueur {AI_PLAYER} alors que son pool comptait au "
        "moins deux escouades : la divergence train/serve est de retour"
    )


def test_the_end_of_a_shooting_activation_never_designates_the_next_one():
    """`_handle_shooting_end_activation` n'écrit JAMAIS `active_shooting_unit`, même joueur `"ai"`.

    C'est le JUMEAU de l'épinglage au montage du pool : il reposait `pool[0]` après chaque fin
    d'activation, sous le même prédicat. Le pilotage aléatoire ne l'atteint pas — c'est le chemin
    par-unité (`execute_action`), vivant pour le flux PvP humain (advance, move-after-shooting)
    mais que l'agent n'emprunte pas, et dont le prédicat était toujours faux en PvP humain. Ce
    cas l'atteint donc en l'APPELANT, sur un état de production piloté jusqu'à une phase de tir à
    pool ≥ 2 — pas sur un `game_state` fabriqué. Sans lui, la suppression du jumeau ne reposerait
    que sur l'identité de motif.
    """
    from engine.phase_handlers.shared_utils import PASS, SHOOTING
    from engine.phase_handlers.shooting_handlers import _handle_shooting_end_activation

    engine = _new_engine()
    rng = random.Random(0)
    reached = None
    for _ in range(DRIVE_STEPS):
        game_state = engine.game_state
        if game_state["phase"] == "shoot" and len(game_state["shoot_activation_pool"]) >= 2:
            reached = game_state
            break
        mask = engine.get_action_mask()
        valid = [i for i, v in enumerate(mask) if v]
        _o, _r, term, trunc, _i = engine.step(rng.choice(valid) if valid else 0)
        if term or trunc:
            break

    assert reached is not None, (
        "aucune phase de tir à pool ≥ 2 atteinte — ce cas serait VERT SANS RIEN REGARDER"
    )
    # Bascule en "ai" : c'est la SEULE condition sous laquelle l'ancien épinglage écrivait.
    reached["player_types"] = {"1": "ai", "2": "ai"}
    pool_before = [str(uid) for uid in reached["shoot_activation_pool"]]
    unit = engine.action_decoder._raw_eligible_units_for_current_phase(reached)[0]

    _handle_shooting_end_activation(reached, unit, PASS, 1, PASS, SHOOTING, 1, action_type="skip")

    assert len(reached["shoot_activation_pool"]) == len(pool_before) - 1, (
        "l'activation n'a pas réellement pris fin — le cas n'observe pas ce qu'il annonce"
    )
    assert "active_shooting_unit" not in reached, (
        "la fin d'activation a désigné l'escouade suivante "
        f"({reached['active_shooting_unit']!r}) : le choix `ACTIVATE_SLOT` de l'agent est préempté "
        "sur le chemin par-unité, exactement comme il l'était au montage du pool"
    )


def test_the_ai_chains_several_shooting_activations_in_one_phase(shooting_records_in_pve_mode):
    """L'IA enchaîne plusieurs activations dans une même phase de tir, en configuration PvE.

    Ce que ce cas attrape : une `active_shooting_unit` PÉRIMÉE. Elle était épinglée sur la tête du
    pool au montage de celui-ci et jamais libérée sur le chemin de l'agent ; à la 2e activation
    elle ne désignait plus une escouade du pool et `_raw_eligible_units_for_current_phase` levait
    `active_shooting_unit X is not in shoot_activation_pool`. En PvE ce `ValueError` était avalé
    par `execute_ai_turn`, donc le symptôme visible était « l'IA ne tire qu'une escouade par
    phase ».

    Le premier garde-fou est donc l'exception NON rattrapée dans `_drive_and_record_shooting`.
    L'assertion ci-dessous en est le second : elle compte les escouades réellement SORTIES du pool
    dans une même phase, et non des tailles de pool distinctes — une taille change au moindre
    `end_activation`, y compris sur un WAIT, et rendrait ce cas vert sans qu'aucune activation ne
    se soit enchaînée.
    """
    # Borné au joueur `"ai"` : c'est le seul dont l'épinglage périmait la clé. Compté sur tous les
    # joueurs, ce cas passerait sur les phases du joueur humain, jamais touchées par le défaut.
    records = [r for r in shooting_records_in_pve_mode if r["player"] == AI_PLAYER]
    # Une phase de tir = (tour, joueur). Son pool ne fait que DÉCROÎTRE (rien ne s'y ajoute en
    # cours de phase), donc les escouades sorties = premier relevé moins le dernier ; chaque
    # sortie est une activation menée à son terme.
    bounds: Dict[Tuple[int, int], List[set]] = {}
    for record in records:
        key = (record["turn"], record["player"])
        pool = set(record["pool"])
        bounds.setdefault(key, [pool, pool])[1] = pool
    departed = {key: first - last for key, (first, last) in bounds.items()}
    chained = {key: sorted(gone) for key, gone in departed.items() if len(gone) >= 2}
    assert chained, (
        "aucune phase de tir n'a enchaîné deux activations en mode 'ai' : `active_shooting_unit` "
        "reste périmée après la première, et le décodeur lève à la suivante "
        f"(escouades sorties du pool, par phase : { {k: sorted(v) for k, v in departed.items()} })"
    )


# ─────────────────────────────────────────────────────────────────────────────
# ORDRE DES SORTIES DU MASQUE — deux RÈGLES, pas une préférence de rédaction
#
# `L2` a inséré sa sortie au milieu de celles de `L6` (déclaration de vol 21.03) et de l'ingress
# (20.04). L'ordre relatif des trois porte deux règles de jeu, et un simple déplacement les casse
# sans que rien ne lève. Les deux cas ci-dessous les verrouillent.
# ─────────────────────────────────────────────────────────────────────────────


def _fly_gs(**kwargs):
    """État minimal à escouade FLY — réutilise le constructeur du contrat 21.03.

    Importé plutôt que recopié : un second constructeur divergerait du premier au premier champ
    ajouté, et ces cas ne prouveraient plus rien sur le vrai prédicat de 21.03.
    """
    from tests.unit.engine.test_fly_declaration_decision import _gs

    return _gs(**kwargs)


def test_a_squad_in_strategic_reserves_is_never_asked_to_declare_flight():
    """20.04 vs 21.03 — l'ingress move n'est PAS un des mouvements que 21.03 couvre.

    21.03 ouvre « take to the skies » quand une unité FLYING est sélectionnée pour un mouvement
    Normal / Advance / Fall Back / Charge. Une escouade en RÉSERVES fait une MISE EN PLACE : elle
    n'est pas sur le champ de bataille, elle n'exécute aucun de ces quatre mouvements.

    Le défaut que ce cas ferme : `arm_fly_declaration_decision` documente explicitement que
    l'appelant garantit cette précondition et ne la revérifie pas
    (`movement_handlers._fly_declaration_due_unit`). En déplaçant la sortie d'ingress SOUS
    l'appel, `L2` a cassé cette garantie — l'escouade en réserves se voyait poser la question, et
    la déclaration s'écrit pour la PHASE (`declared_key`/`resolved_key`) : elle aurait payé les
    -2" sur un mouvement qu'elle ne fait pas.
    """
    from engine.action_decoder import ActionDecoder
    from engine.agent_decision import read_pending_agent_decision

    game_state = _fly_gs(phase="move")
    # L'escouade FLY passe en réserves stratégiques : elle reste dans le pool de mouvement
    # (20.04 lui donne un ingress move), mais elle n'est pas sur la table. Le drapeau lu par
    # `unit_is_in_strategic_reserves` est `in_strategic_reserves` — c'est LUI que le masque
    # consulte, pas `deployed_on_turn`.
    game_state["unit_by_id"]["1"]["in_strategic_reserves"] = True
    # Zones de pose : `ingress_slot_candidates` en a besoin pour la clause « aucune figurine dans
    # la zone adverse avant le 3e round » (20.04) et LÈVE si elles manquent, sans repli.
    game_state["deployment_pools"] = {
        1: [(c, 5) for c in range(8, 14)],
        2: [(c, 55) for c in range(8, 14)],
    }
    # Le scoring des slots d'ingress note les candidats par distance aux objectifs et LÈVE s'il
    # n'y en a aucun : la liste doit être non vide, pas seulement présente.
    game_state["objectives"] = [{"id": "obj1", "center": (22, 30), "hexes": [(22, 30)]}]
    game_state["terrain_areas"] = []

    decoder = ActionDecoder(game_state["config"])
    mask, eligible = decoder.get_squad_action_mask_and_eligible_units(game_state)

    assert read_pending_agent_decision(game_state) is None, (
        "une escouade en réserves s'est vu poser la déclaration de vol 21.03 : son ingress move "
        "(20.04) n'est pas un des mouvements que la règle couvre"
    )
    # Et elle a bien reçu le masque d'INGRESS, pas un masque de décision.
    assert [u["id"] for u in eligible] == [1]
    assert bool(mask[SQUAD_ACTION_WAIT]), "le masque d'ingress doit ouvrir WAIT (renoncer)"


def test_the_flight_declaration_is_asked_after_the_activation_choice_not_before():
    """21.03 est posée à l'escouade DÉSIGNÉE, jamais à la tête du pool.

    La déclaration s'écrit pour la phase et `resolved_key` interdit de la reposer. La poser avant
    le choix d'activation l'engagerait pour la tête du pool ; si l'agent active ensuite une AUTRE
    escouade, la première reste avec un vol déclaré — donc -2" et traversée — pour un mouvement
    qu'elle n'a pas encore été sélectionnée pour faire.
    """
    from engine.action_decoder import ActionDecoder
    from engine.agent_decision import read_pending_agent_decision

    game_state = _fly_gs(phase="move")
    # Deuxième escouade FLY du même joueur, pour que le pool en compte DEUX et que le choix
    # d'activation se pose réellement. Sans elle, ce cas ne regarderait rien.
    second = copy.deepcopy(game_state["unit_by_id"]["1"])
    second["id"] = 3
    second["col"] = game_state["unit_by_id"]["1"]["col"] + 4
    game_state["units"].append(second)
    game_state["unit_by_id"]["3"] = second
    game_state["move_activation_pool"] = ["1", "3"]
    from engine.phase_handlers.shared_utils import build_units_cache

    build_units_cache(game_state)

    decoder = ActionDecoder(game_state["config"])
    slots = decoder.activation_selection_slots(game_state)
    assert slots is not None and len(slots) >= 2, (
        f"pas de choix d'activation posé (slots={slots}) : ce cas ne regarde rien"
    )

    decoder.get_squad_action_mask_and_eligible_units(game_state)
    assert read_pending_agent_decision(game_state) is None, (
        "la déclaration de vol a été posée AVANT que l'agent ait choisi qui activer : elle "
        "engage la tête du pool pour un mouvement qu'elle ne fera peut-être pas"
    )


def test_the_engine_refuses_a_squad_the_mask_did_not_open(choice_point):
    """Le moteur revérifie la légalité — il ne fait pas confiance au `unitId` reçu.

    Même exigence que pour Oath : l'action arrive aussi de l'API PvP, pas seulement du décodeur.
    """
    engine = _new_engine()
    found = _drive_to_activation_choice(engine)
    assert found is not None
    _game_state, _mask, slots = found
    opened = set(slots.values())
    intruder = next(
        str(u["id"])
        for u in engine.game_state["units"]
        if str(u["id"]) not in opened
    )
    ok, result = engine._process_squad_action(
        {"action": "select_activation", "unitId": intruder}
    )
    assert ok is False
    assert result["error"] == "activation_choice_not_open"
