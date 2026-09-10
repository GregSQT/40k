"""20.01 — l'étape Declare Battle Formations PRÉCÈDE le déploiement.

Le défaut corrigé, mesuré avant écriture sur `scenario_training_armageddon1.json` en déploiement
actif : le masque ouvrait `SQUAD_ACTION_WAIT` — « mets cette unité en réserves » — pendant le tour
de déploiement de chaque unité, donc au fil de l'alternance. Relevé brut ::

    step 1: deployer=2 mes_posees=0 ennemies_posees=1 WAIT_ouvert=True
    step 7: deployer=2 mes_posees=3 ennemies_posees=4 WAIT_ouvert=True

Le joueur 2 déclarait ses réserves en voyant QUATRE unités adverses déjà posées. La règle le lui
interdit : `Documentation/40k_rules/20 Strategic reserves.pdf`, 20.01 — « Before the battle, in the
Declare Battle Formations step, you can select one or more friendly units (excluding
FORTIFICATIONS) to place in strategic reserves. Instead of setting up these units on the
battlefield during deployment, place them to one side ». `25 Rules appendix.pdf` situe cette étape
avant Pre-battle Abilities, elle-même avant Begin the Battle : rien n'est encore posé.

Ce que ce fichier verrouille n'est donc PAS « la mise en réserves fonctionne » (c'est
`test_strategic_reserves_20.py`), mais le MOMENT où elle se décide, et ce qui en découle : le
plateau vide pendant les questions, l'absence de `SQUAD_ACTION_WAIT`, le refus des poses tant que
l'étape est ouverte, et la reprise du déploiement par le joueur 1.
"""
from __future__ import annotations

import sys

from pathlib import Path
from typing import Any, Dict, List

import pytest

import engine.macro_intents as mi
from engine.agent_decision import read_pending_agent_decision
from engine.phase_handlers.deployment_handlers import (
    RESERVES_DECLARATION_CLOSED_KEY,
    RESERVES_DECLARATION_QUEUE_KEY,
    build_reserves_declaration_queue,
    deployment_commit_plan,
    deployment_place_in_strategic_reserves,
    next_reserves_declaration_entry,
    reserves_declaration_step_has_started,
    reserves_declaration_step_is_open,
)
from tests.unit.engine._config_helpers import both_terrains

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# MÊME pin que `test_strategic_reserves_20.py`, et pour la même raison : rosters figés, aucune
# réserve pré-déclarée. Une variante à réserves consommerait le plafond de 50 % dès le reset et
# la file 20.01 n'aurait plus qu'une question à poser — ce fichier n'observerait presque rien.
SCENARIO = (
    PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent_x1" / "scenarios" / "training"
    / "reserves_20_fixture1.json"
)

_terrain = both_terrains(sys.modules[__name__])

CHOICE_DECLARE = mi.CHOICE_SLOTS.start          # CHOICE_0 — mettre en réserves
CHOICE_KEEP = mi.CHOICE_SLOTS.start + 1         # CHOICE_1 — garder pour le déploiement


@pytest.fixture(autouse=True)
def _pin_board(board_x5):
    pass


def _engine(seed: int = 0):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent_x1", training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent_x1", scenario_file=str(SCENARIO),
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    assert eng.training_config is not None
    sched = eng.training_config.get("deployment_mode_schedule")
    if isinstance(sched, dict):
        sched["enabled"] = False
    eng.reset(seed=seed)
    assert eng.game_state["phase"] == "deployment", (
        "ce fichier ne teste rien hors d'un déploiement ACTIF"
    )
    return eng


def _on_board_count(gs: Dict[str, Any]) -> int:
    """Unités RÉELLEMENT posées, les deux camps confondus (source `deployed_on_turn`)."""
    return sum(1 for u in gs["units"] if u["deployed_on_turn"] is not None)


def _drive(eng, *, declare_ids: set[str] | None = None) -> List[Dict[str, Any]]:
    """Déroule la phase de déploiement et rend la trace de chaque step.

    Chaque entrée porte ce dont les assertions ont besoin : le type de step (question 20.01 ou
    pose), l'unité concernée, et le nombre d'unités DÉJÀ sur la table AU MOMENT du step.
    """
    gs = eng.game_state
    declare_ids = declare_ids or set()
    trace: List[Dict[str, Any]] = []
    steps = 0
    while gs["phase"] == "deployment" and steps < 200:
        mask = eng.get_action_mask()
        pending = read_pending_agent_decision(gs)
        if pending is not None:
            assert str(pending["type"]) == "reserves_declaration", pending["type"]
            unit_id = str(pending["unit_id"])
            trace.append({
                "kind": "declaration",
                "unitId": unit_id,
                "player": int(pending["player"]),
                "on_board": _on_board_count(gs),
                "wait_open": bool(mask[mi.ACTION_WAIT]),
            })
            declare = unit_id in declare_ids
            eng.step(int(CHOICE_DECLARE if declare else CHOICE_KEEP))
        else:
            deploy_actions = [a for a in range(4, 9) if mask[a]]
            assert deploy_actions, f"aucune action de pose au step {steps}"
            trace.append({
                "kind": "placement",
                "player": int(gs["deployment_state"]["current_deployer"]),
                "on_board": _on_board_count(gs),
                "wait_open": bool(mask[mi.ACTION_WAIT]),
            })
            eng.step(int(deploy_actions[0]))
        steps += 1
    assert gs["phase"] != "deployment", f"déploiement non terminé après {steps} steps"
    return trace


# ===========================================================================
# L'INVARIANT — le plateau est VIDE tant qu'une déclaration est en attente
# ===========================================================================


def test_no_unit_is_on_the_battlefield_while_a_reserves_declaration_is_pending():
    """20.01 : la déclaration précède la mise en place, donc rien n'est encore posé.

    C'est LA mesure qui distinguait l'ancien comportement du nouveau. Avant, la même trace
    montrait des déclarations à `on_board` = 1, 2, 3 puis 4.
    """
    trace = _drive(_engine())

    declarations = [step for step in trace if step["kind"] == "declaration"]
    # VERT VACANT : sans question posée, l'assertion suivante est vraie pour rien.
    assert declarations, "aucune question 20.01 posée : le test ne prouve rien"

    late = [step for step in declarations if step["on_board"] != 0]
    assert not late, (
        "20.01 : déclaration posée alors que des unités sont déjà sur la table — "
        f"{[(s['unitId'], s['on_board']) for s in late]}"
    )


def test_every_declaration_precedes_every_placement():
    """L'étape est un BLOC : aucune question après la première pose, dans l'un ou l'autre camp.

    Distinct du test précédent, et pas une redite : « rien n'est posé » se mesure sur l'état,
    « les questions viennent d'abord » se mesure sur l'ORDRE des steps. Un moteur qui reposerait
    une question après une pose ratée — donc sans unité sur la table — passerait le premier test.
    """
    trace = _drive(_engine())
    kinds = [step["kind"] for step in trace]
    assert "declaration" in kinds and "placement" in kinds, (
        f"trace sans les deux familles de steps : {kinds}"
    )
    first_placement = kinds.index("placement")
    assert "declaration" not in kinds[first_placement:], (
        f"question 20.01 posée APRÈS le début du déploiement : {kinds}"
    )


def test_the_deployment_mask_never_opens_wait():
    """`SQUAD_ACTION_WAIT` ne met plus rien en réserves, donc il n'a plus rien à faire là.

    Le laisser ouvert serait un slot sans signification que le décodeur refuse
    (`convert_squad_action`, phase deployment) : l'agent y perdrait des steps sur une action que
    le moteur rejette.
    """
    trace = _drive(_engine())
    open_at = [step for step in trace if step["wait_open"]]
    assert not open_at, f"WAIT ouvert pendant le déploiement : {open_at}"


# ===========================================================================
# EFFETS DE LA RÉPONSE
# ===========================================================================


def test_declaring_removes_the_unit_from_the_deployment_pool():
    """`CHOICE_0` sort l'unité du pool à poser et la met en réserves — et elle seule."""
    eng = _engine()
    gs = eng.game_state
    eng.get_action_mask()  # c'est la construction du masque qui pose la question
    pending = read_pending_agent_decision(gs)
    assert pending is not None, "aucune question 20.01 au premier masque"
    unit_id = str(pending["unit_id"])
    player = int(pending["player"])

    eng.step(int(CHOICE_DECLARE))

    unit = gs["unit_by_id"][unit_id]
    assert unit["in_strategic_reserves"] is True
    assert unit["deployed_on_turn"] is None, "une réserve n'est PAS posée (20.03 : ingress move)"
    remaining = gs["deployment_state"]["deployable_units"][player]
    assert unit_id not in [str(uid) for uid in remaining], (
        "l'unité déclarée reste dans le pool à poser"
    )


def test_declining_keeps_the_unit_in_the_deployment_pool():
    """`CHOICE_1` (`declines`) n'est PAS un non-événement : il retire la question, pas l'unité."""
    eng = _engine()
    gs = eng.game_state
    eng.get_action_mask()
    pending = read_pending_agent_decision(gs)
    assert pending is not None
    unit_id = str(pending["unit_id"])
    player = int(pending["player"])

    eng.step(int(CHOICE_KEEP))

    unit = gs["unit_by_id"][unit_id]
    assert unit["in_strategic_reserves"] is False
    remaining = [str(uid) for uid in gs["deployment_state"]["deployable_units"][player]]
    assert unit_id in remaining, "l'unité refusée doit rester à poser"
    # Et la question ne se repose pas : sans cela l'étape ne se terminerait jamais.
    queue = gs["deployment_state"][RESERVES_DECLARATION_QUEUE_KEY]
    assert unit_id not in [str(entry[1]) for entry in queue], (
        "la question 20.01 se reposerait indéfiniment sur la même unité"
    )


def test_the_first_deployer_takes_over_once_the_step_is_closed():
    """Les questions déplacent `current_deployer` ; la mise en place repart du joueur 1.

    Sans cette remise, l'ordre du déploiement dépendrait de la PARITÉ du nombre de questions
    posées — donc du roster, et non de la règle.
    """
    eng = _engine()
    gs = eng.game_state
    steps = 0
    while gs["phase"] == "deployment" and steps < 200:
        eng.get_action_mask()
        pending = read_pending_agent_decision(gs)
        if pending is None:
            break
        eng.step(int(CHOICE_KEEP))
        steps += 1

    assert gs["deployment_state"][RESERVES_DECLARATION_CLOSED_KEY] is True
    assert not reserves_declaration_step_is_open(gs)
    assert int(gs["deployment_state"]["current_deployer"]) == 1
    assert int(gs["current_player"]) == 1


def test_a_placement_is_refused_while_the_declaration_step_is_open():
    """Le refus vit dans le HANDLER, pas seulement dans le masque.

    Le masque protège le siège gym ; le siège humain (PvP) n'en construit aucun et entre par
    `deployment_commit_plan`. Un contrôle qui ne serait que dans le masque laisserait donc le
    joueur humain poser pendant l'étape de déclaration — exactement l'écart que ce chantier
    ferme.
    """
    eng = _engine()
    gs = eng.game_state
    assert reserves_declaration_step_is_open(gs), "étape déjà close : le test ne prouve rien"
    squad_id = str(gs["deployment_state"]["deployable_units"][1][0])

    ok, result = deployment_commit_plan(gs, {"unitId": squad_id, "plan": []})

    assert ok is False
    assert result["error"] == "reserves_declaration_still_open", result


# ===========================================================================
# LA FILE
# ===========================================================================


def test_the_queue_alternates_between_players():
    """L'ordre des questions est celui du déploiement — alterné, joueur 1 d'abord.

    Il est FIGÉ au reset : c'est ce qui empêche qu'il dépende d'un état que les déclarations
    elles-mêmes modifient.
    """
    queue = build_reserves_declaration_queue({1: ["a", "b", "c"], 2: ["x", "y"]})
    assert queue == [[1, "a"], [2, "x"], [1, "b"], [2, "y"], [1, "c"]]


def test_the_queue_is_built_before_any_placement():
    """Au reset, la file couvre TOUT le pool à poser et le plateau est vide.

    Bâtie plus tard, elle le serait sur un plateau déjà partiellement déployé — c'est-à-dire que
    l'ordre des questions dépendrait de poses que la règle situe après elles.
    """
    eng = _engine()
    gs = eng.game_state
    assert _on_board_count(gs) == 0, "des unités sont posées dès le reset"
    queue = gs["deployment_state"][RESERVES_DECLARATION_QUEUE_KEY]
    deployable = gs["deployment_state"]["deployable_units"]
    expected = {(p, str(uid)) for p in (1, 2) for uid in deployable[p]}
    assert {(int(p), str(uid)) for p, uid in queue} == expected


# ===========================================================================
# CLÔTURE DE PHASE — les deux sièges sortent du déploiement de la même façon
# ===========================================================================


def test_the_human_seat_closes_the_phase_when_nothing_is_left_to_place():
    """Roster entièrement déclarable : la phase de déploiement se termine, elle ne se fige pas.

    Cas limite RÉEL, pas hypothétique : le plafond de 20.01 porte sur 50 % de la TAILLE DE
    BATAILLE, donc une armée qui vaut moins que ce plafond peut partir entièrement en réserves.
    Il ne reste alors plus rien à poser, et c'est le dernier `deploy_strategic_reserves` qui doit
    signaler la sortie de phase — comme le fait `deployment_commit_plan` dans le même état.

    Trouvé par la review : le siège gym s'en sortait par
    `W40KEngine._complete_deployment_if_nothing_to_place`, le siège humain restait bloqué avec
    deux pools vides et `deployment_complete` à False.
    """
    eng = _engine()
    gs = eng.game_state
    # Toute l'armée tient sous le plafond : c'est la CONDITION du cas, pas un contournement.
    for unit in gs["units"]:
        unit["VALUE"] = 1

    answered = 0
    last: Dict[str, Any] = {}
    while answered < 50:
        entry = next_reserves_declaration_entry(gs)
        if entry is None:
            break
        ok, last = deployment_place_in_strategic_reserves(
            gs, {"unitId": entry[1], "declare": True}
        )
        assert ok, last
        answered += 1

    assert answered > 0, "aucune déclaration jouée : le test ne prouve rien"
    for player in (1, 2):
        assert not gs["deployment_state"]["deployable_units"][player], (
            f"joueur {player} a encore des unités à poser : le cas testé n'est pas atteint"
        )
    assert gs["deployment_state"]["deployment_complete"] is True
    assert last["phase_complete"] is True
    assert last["next_phase"] == "command"


def test_a_partial_declaration_does_not_close_the_phase():
    """VERT VACANT du test ci-dessus : tant qu'il reste à poser, aucune sortie de phase.

    Sans ce pendant, un `phase_complete` posé inconditionnellement passerait le test précédent
    tout en terminant le déploiement dès la première déclaration.
    """
    eng = _engine()
    gs = eng.game_state
    entry = next_reserves_declaration_entry(gs)
    assert entry is not None

    ok, result = deployment_place_in_strategic_reserves(
        gs, {"unitId": entry[1], "declare": True}
    )

    assert ok
    assert "phase_complete" not in result
    assert gs["deployment_state"]["deployment_complete"] is False
    assert any(gs["deployment_state"]["deployable_units"][p] for p in (1, 2))


# ===========================================================================
# « L'ÉTAPE A COMMENCÉ » — le marqueur qui gèle les listes d'armée
# ===========================================================================


def test_no_answer_means_the_step_has_not_started():
    """Au reset, aucune réponse n'a été donnée : les listes sont encore modifiables.

    C'est l'état qui autorise `change_roster` (`services/api_server._execute_change_roster_action`).
    Un marqueur posé à True dès le reset fermerait le choix d'armée avant qu'il ait servi.
    """
    eng = _engine()
    assert reserves_declaration_step_has_started(eng.game_state["deployment_state"]) is False


@pytest.mark.parametrize("declare", [True, False])
def test_the_model_seat_marks_the_step_started(declare: bool):
    """Répondre — DANS LES DEUX SENS — commence l'étape pour le siège piloté par le modèle.

    « Garder pour le déploiement » est un candidat de la question, pas une absence de réponse :
    il consomme la question, donc il commence l'étape au même titre que la mise en réserves.
    """
    eng = _engine()
    gs = eng.game_state
    eng.get_action_mask()
    assert read_pending_agent_decision(gs) is not None, "aucune question posée"

    eng.step(int(CHOICE_DECLARE if declare else CHOICE_KEEP))

    assert reserves_declaration_step_has_started(gs["deployment_state"]) is True


@pytest.mark.parametrize("declare", [True, False])
def test_the_human_seat_marks_the_step_started(declare: bool):
    """JUMEAU du siège modèle : la même réponse par la route PvP marque le même état.

    Les deux sièges passent par `consume_reserves_declaration_entry` ; s'ils divergeaient, le
    verrou du changement d'armée dépendrait de qui joue.
    """
    eng = _engine()
    gs = eng.game_state
    entry = next_reserves_declaration_entry(gs)
    assert entry is not None

    ok, result = deployment_place_in_strategic_reserves(
        gs, {"unitId": entry[1], "declare": declare}
    )

    assert ok, result
    assert reserves_declaration_step_has_started(gs["deployment_state"]) is True


def test_an_unaskable_entry_dropped_from_the_queue_does_not_start_the_step():
    """Une question qui ne sera JAMAIS posée n'est pas une réponse.

    `next_reserves_declaration_entry` ampute la file des unités qui ne peuvent pas aller en
    réserves (ici : plafond de 50 % nul, donc plus aucune unité éligible). Déduire « l'étape a
    commencé » de la longueur de la file confondrait cette amputation avec une réponse, et
    refuserait un changement d'armée que rien n'interdit.
    """
    eng = _engine()
    gs = eng.game_state
    assert gs["deployment_state"][RESERVES_DECLARATION_QUEUE_KEY], "file vide : rien à amputer"
    # Plafond nul : plus aucune unité ne peut partir en réserves, la file se vide sans réponse.
    gs["points_limit"] = 0

    assert next_reserves_declaration_entry(gs) is None
    assert not gs["deployment_state"][RESERVES_DECLARATION_QUEUE_KEY], (
        "la file n'a pas été amputée : le test n'observe pas le cas visé"
    )
    assert reserves_declaration_step_has_started(gs["deployment_state"]) is False


# ===========================================================================
# LE SIÈGE SUIT LA QUESTION — 20.01 se répond depuis le camp interrogé
# ===========================================================================


def test_the_seat_follows_the_next_question_after_a_human_answer():
    """Répondre déplace le siège sur le camp de la question SUIVANTE.

    La file alterne les deux camps ; le siège, lui, ne bougeait que sur le chemin gym
    (`arm_reserves_declaration_decision`). Une partie servie par l'API restait donc sur le joueur
    1 pendant toute l'étape : en PvE, la question du bot était rendue au client alors que le
    déclencheur de tour IA (`BoardWithAPI`) lit `current_deployer` et qu'`execute_ai_turn` refuse
    hors `current_player == 2`. Personne n'aurait pu y répondre depuis le bon siège.
    """
    from engine.phase_handlers.deployment_handlers import (
        deployment_place_in_strategic_reserves,
    )

    eng = _engine()
    gs = eng.game_state
    first = next_reserves_declaration_entry(gs)
    assert first is not None

    ok, result = deployment_place_in_strategic_reserves(
        gs, {"unitId": first[1], "declare": False}
    )
    assert ok, result

    second = next_reserves_declaration_entry(gs)
    assert second is not None, "file épuisée : le test n'observe pas le déplacement du siège"
    assert second[0] != first[0], (
        "les deux questions portent sur le même camp : la file n'alterne pas, le test ne "
        "distingue pas un siège qui suit d'un siège figé"
    )
    assert gs["deployment_state"]["current_deployer"] == second[0]
    assert gs["current_player"] == second[0]


def test_the_seat_follows_the_first_question_at_reset():
    """Le siège est POSÉ sur la première question dès le reset, même si ce n'est pas le joueur 1.

    Les entrées inéligibles (FORTIFICATION, plafond de 50 %) sont retirées de la file sans
    réponse : l'étape peut donc s'ouvrir sur le camp d'en face alors que le reset place le
    déployeur sur le joueur 1. Ici, plus aucune unité du joueur 1 n'est déclarable, la première
    question est celle du joueur 2, et c'est là que le siège doit être.
    """
    from unittest.mock import patch

    import engine.phase_handlers.deployment_handlers as dh
    from engine.game_utils import get_unit_by_id

    eng = _engine()
    real_predicate = dh.unit_can_be_placed_in_strategic_reserves

    def _only_player_two(game_state: Dict[str, Any], unit_id: str) -> bool:
        unit = get_unit_by_id(game_state, str(unit_id))
        assert unit is not None
        if int(unit["player"]) == 1:
            return False
        return bool(real_predicate(game_state, unit_id))

    with patch.object(dh, "unit_can_be_placed_in_strategic_reserves", _only_player_two):
        eng.reset(seed=0)
        gs = eng.game_state
        entry = next_reserves_declaration_entry(gs)
        assert entry is not None and entry[0] == 2, (
            "la première question n'est pas celle du joueur 2 : le test n'observe pas le cas visé"
        )
        assert gs["deployment_state"]["current_deployer"] == 2
        assert gs["current_player"] == 2


def test_the_human_route_refuses_a_question_asked_to_a_model_seat():
    """20.01 se déclare depuis SON siège : la route humaine refuse la question du bot.

    « **you** can select one or more friendly units » (20.01) — la liste d'un camp est décidée par
    ce camp. En PvE le siège 2 est piloté par le modèle et répond par
    `apply_reserves_declaration_decision` ; laisser la route humaine y répondre, c'est laisser
    l'adversaire choisir la liste du bot.

    VERT VACANT : la MÊME route, sur la question du siège humain, est acceptée juste avant — le
    refus ne vient donc pas d'une route cassée pour tout le monde.
    """
    from engine.phase_handlers.deployment_handlers import (
        deployment_place_in_strategic_reserves,
    )

    eng = _engine()
    gs = eng.game_state
    gs["player_types"]["2"] = "ai"

    human_entry = next_reserves_declaration_entry(gs)
    assert human_entry is not None and human_entry[0] == 1
    ok, result = deployment_place_in_strategic_reserves(
        gs, {"unitId": human_entry[1], "declare": False}
    )
    assert ok, result

    model_entry = next_reserves_declaration_entry(gs)
    assert model_entry is not None and model_entry[0] == 2, (
        "aucune question pour le siège modèle : le test n'observe pas le cas visé"
    )
    ok, result = deployment_place_in_strategic_reserves(
        gs, {"unitId": model_entry[1], "declare": True}
    )

    assert not ok
    assert result["error"] == "reserves_declaration_seat_is_not_human", result
    assert result["player"] == 2
    # La question n'a pas été consommée : elle attend toujours son siège.
    assert next_reserves_declaration_entry(gs) == model_entry


def test_the_seat_follows_the_next_question_after_a_model_answer():
    """JUMEAU du siège humain : la réponse du MODÈLE déplace le siège de la même façon.

    Le chemin emprunté ici est celui de l'API — `_process_squad_action`, ce qu'appelle
    `execute_ai_turn` —, et non `eng.step` : le step gym reconstruit le masque avant de rendre la
    main, et ce build recale le siège de lui-même. Passer par lui rendrait ce test vert quel que
    soit le code, alors que le tour IA du client, lui, lit l'état SANS build de masque
    intermédiaire.

    Défaut mesuré avant écriture, sur cette fixture, en suivant le chemin de l'API ::

        modele repond Q2 -> True | current_player=2 current_deployer=2 | question due: (1, '2')
        tour IA 2 : masque arme joueur 1 unite 2 | current_player=1 current_deployer=1
        => unite 2 du joueur 1 in_strategic_reserves = True

    Le siège restait sur 2 après la réponse du bot, le client relançait un tour IA, le garde
    `current_player == 2` d'`execute_ai_turn` passait — il est lu AVANT le build de masque —, et
    c'est ce build qui armait la question du JOUEUR 1 pour le modèle. Le modèle déclarait les
    réserves de l'humain.
    """
    eng = _engine()
    gs = eng.game_state
    gs["player_types"]["2"] = "ai"
    # `execute_ai_turn` sort sur `not_pve_mode` avant tout le reste : sans ce drapeau, l'assertion
    # finale serait verte pour la mauvaise raison.
    eng.is_pve_mode = True

    first = next_reserves_declaration_entry(gs)
    assert first is not None and first[0] == 1, (
        "la première question n'est pas celle du joueur 1 : l'enchaînement visé n'est pas observé"
    )
    ok, result = deployment_place_in_strategic_reserves(
        gs, {"unitId": first[1], "declare": False}
    )
    assert ok, result
    assert gs["current_player"] == 2, "le siège n'est pas passé au modèle : rien à observer"

    # Tour IA du client : c'est la construction du masque qui arme la question du bot.
    eng.get_action_mask()
    pending = read_pending_agent_decision(gs)
    assert pending is not None and int(pending["player"]) == 2, pending

    ok, result = eng._process_squad_action({"action": "agent_decision", "option_index": 1})
    assert ok, result

    third = next_reserves_declaration_entry(gs)
    assert third is not None and third[0] == 1, (
        "la question suivante n'appartient pas au joueur 1 : le test ne distingue pas un siège "
        "qui suit d'un siège figé sur le répondant"
    )
    assert gs["deployment_state"]["current_deployer"] == 1
    assert gs["current_player"] == 1

    # LE CHEMIN DE PRODUCTION : le tour IA suivant du client doit être REFUSÉ. C'est ce refus, et
    # lui seul, qui empêche le modèle de répondre à la question de l'humain.
    ai_ok, ai_result = eng.execute_ai_turn()
    assert ai_ok is False and ai_result["error"] == "not_ai_player_turn", ai_result
