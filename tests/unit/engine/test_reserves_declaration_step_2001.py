"""20.01 — l'étape Declare Battle Formations PRÉCÈDE le déploiement, et se déclare PAR CAMP.

Le défaut d'origine, mesuré sur `scenario_training_armageddon1.json` en déploiement actif : le
masque ouvrait `SQUAD_ACTION_WAIT` — « mets cette unité en réserves » — pendant le tour de
déploiement de chaque unité, donc au fil de l'alternance. Relevé brut ::

    step 1: deployer=2 mes_posees=0 ennemies_posees=1 WAIT_ouvert=True
    step 7: deployer=2 mes_posees=3 ennemies_posees=4 WAIT_ouvert=True

Le joueur 2 déclarait ses réserves en voyant QUATRE unités adverses déjà posées. La règle le lui
interdit : `Documentation/40k_rules/20 Strategic reserves.pdf`, 20.01 — « Before the battle, in the
Declare Battle Formations step, you can select one or more friendly units (excluding
FORTIFICATIONS) to place in strategic reserves. Instead of setting up these units on the
battlefield during deployment, place them to one side ». `25 Rules appendix.pdf` situe cette étape
avant Pre-battle Abilities, elle-même avant Begin the Battle : rien n'est encore posé.

La correction suivante a retiré l'ALTERNANCE escouade par escouade, qui n'avait aucune base dans le
texte : 20.01 dit « select one or more friendly units », donc un ENSEMBLE déclaré par un camp pour
toute son armée, sans ordre imposé. Le siège humain compose librement puis fige d'un clic ; le
siège piloté par le modèle reste interrogé escouade par escouade, faute pour PPO de savoir
exprimer « je compose puis je valide » — même espace d'action, même état final.

Ce que ce fichier verrouille n'est donc PAS « la mise en réserves fonctionne » (c'est
`test_strategic_reserves_20.py`), mais le MOMENT où elle se décide, la GRANULARITÉ par camp, et ce
qui en découle : le plateau vide pendant les déclarations, l'absence de `SQUAD_ACTION_WAIT`, le
refus des poses tant que l'étape est ouverte, le siège qui suit le camp déclarant, et la reprise du
déploiement par le joueur 1.
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
    RESERVES_DECLARATION_VALIDATED_KEY,
    arm_reserves_declaration_decision,
    current_reserves_declarer,
    deployment_cancel_strategic_reserves,
    deployment_commit_plan,
    deployment_place_in_strategic_reserves,
    deployment_validate_reserves_declaration,
    next_reserves_declaration_question,
    player_can_still_declare_reserves,
    reserves_cancellable_squads,
    reserves_declarable_squads,
    reserves_declaration_step_has_started,
    reserves_declaration_step_is_open,
    reset_reserves_declaration_state,
)
from tests.unit.engine._config_helpers import both_terrains

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# MÊME pin que `test_strategic_reserves_20.py`, et pour la même raison : rosters figés, aucune
# réserve pré-déclarée. Une variante à réserves consommerait le plafond de 50 % dès le reset et
# l'étape n'aurait presque plus rien à proposer — ce fichier n'observerait rien.
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

    Chaque entrée porte ce dont les assertions ont besoin : le type de step (déclaration 20.01 ou
    pose), l'unité concernée, le camp, et le nombre d'unités DÉJÀ sur la table AU MOMENT du step.
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


def _synthetic_state(units: List[Dict[str, Any]], points_limit: int) -> Dict[str, Any]:
    """État minimal pour exercer les prédicats 20.01 sans booter un épisode.

    Construit ENTIÈREMENT par le test — aucune graine, aucun ordre implicite, aucune config
    absente. C'est ce qui permet de mettre en scène un plafond exactement saturé, que les
    scénarios figés du dépôt ne produisent pas.
    """
    deployable: Dict[int, List[str]] = {1: [], 2: []}
    for unit in units:
        if not unit["in_strategic_reserves"]:
            deployable[int(unit["player"])].append(str(unit["id"]))
    gs: Dict[str, Any] = {
        "phase": "deployment",
        "points_limit": points_limit,
        "_reserves_placed": {
            player: sum(
                1
                for u in units
                if int(u["player"]) == player and u["in_strategic_reserves"]
            )
            for player in (1, 2)
        },
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "player_types": {"1": "human", "2": "human"},
        "deployment_state": {
            "current_deployer": 1,
            "deployable_units": deployable,
            "deployed_units": set(),
            "deployment_complete": False,
        },
    }
    reset_reserves_declaration_state(gs["deployment_state"])
    return gs


def _synthetic_unit(uid: str, player: int, value: int, *, in_reserves: bool = False):
    return {
        "id": uid,
        "player": player,
        "VALUE": value,
        "UNIT_KEYWORDS": [{"keywordId": "infantry"}],
        "deployed_on_turn": None,
        "in_strategic_reserves": in_reserves,
    }


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
    # VERT VACANT : sans déclaration posée, l'assertion suivante est vraie pour rien.
    assert declarations, "aucune déclaration 20.01 posée : le test ne prouve rien"

    late = [step for step in declarations if step["on_board"] != 0]
    assert not late, (
        "20.01 : déclaration posée alors que des unités sont déjà sur la table — "
        f"{[(s['unitId'], s['on_board']) for s in late]}"
    )


def test_every_declaration_precedes_every_placement():
    """L'étape est un BLOC : aucune déclaration après la première pose, dans l'un ou l'autre camp.

    Distinct du test précédent, et pas une redite : « rien n'est posé » se mesure sur l'état,
    « les déclarations viennent d'abord » se mesure sur l'ORDRE des steps. Un moteur qui reposerait
    une question après une pose ratée — donc sans unité sur la table — passerait le premier test.
    """
    trace = _drive(_engine())
    kinds = [step["kind"] for step in trace]
    assert "declaration" in kinds and "placement" in kinds, (
        f"trace sans les deux familles de steps : {kinds}"
    )
    first_placement = kinds.index("placement")
    assert "declaration" not in kinds[first_placement:], (
        f"déclaration 20.01 posée APRÈS le début du déploiement : {kinds}"
    )


def test_each_camp_declares_for_its_whole_army_before_the_other():
    """La granularité est le CAMP, pas l'escouade : les déclarations ne s'entrelacent plus.

    Remplace le verrou d'alternance de la version précédente, qui exigeait exactement l'inverse.
    20.01 déclare une formation de bataille — « select one or more friendly units » — et rien dans
    le texte ne fait alterner les camps escouade par escouade. La trace doit donc montrer au plus
    UN changement de camp sur toute l'étape.
    """
    trace = _drive(_engine())
    players = [step["player"] for step in trace if step["kind"] == "declaration"]
    assert players, "aucune déclaration : le test ne prouve rien"

    switches = sum(1 for a, b in zip(players, players[1:]) if a != b)
    assert switches <= 1, (
        f"les camps s'entrelacent pendant l'étape 20.01 ({switches} changements) : {players}"
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
# LE CAMP SANS ESCOUADE DÉCLARABLE — le crash de la première écriture
# ===========================================================================


def _saturated_camp_state() -> Dict[str, Any]:
    """Plafond 100 (50 % de 200), joueur 1 réduit à UNE escouade de 100 points DÉJÀ en réserves :
    plus rien de déclarable, une réserve annulable. C'est l'état d'un roster qui pré-déclare ses
    réserves (`strategic_reserves: true`, rosters d'entraînement) jusqu'au plafond."""
    gs = _synthetic_state(
        [
            _synthetic_unit("u1", 1, 100, in_reserves=True),
            _synthetic_unit("u2", 2, 50),
        ],
        points_limit=200,
    )
    # VERT VACANT : sans ces deux faits, le cas visé n'est pas celui qui est mis en scène.
    assert reserves_declarable_squads(gs, 1) == [], "le joueur 1 a encore de quoi déclarer"
    assert reserves_cancellable_squads(gs, 1) == ["u1"], "aucune réserve annulable à retenir"
    return gs


@pytest.mark.parametrize("seat", ["gym", "ai"])
def test_a_saturated_machine_camp_is_skipped_without_crashing(seat: str):
    """Un camp MACHINE dont le plafond est SATURÉ est passé : il n'ouvre pas une étape sans question.

    DÉFAUT MESURÉ à la relecture, avant qu'aucun test n'existe. Le prédicat d'ouverture retenait
    les réserves ANNULABLES sans regarder le siège. Il déclarait donc un camp piloté par le modèle
    interrogeable sans qu'aucune escouade ne puisse l'être, et `next_reserves_declaration_question`
    levait ::

        RuntimeError: next_reserves_declaration_question: joueur 1 declare interrogeable sans
        escouade interrogeable — `current_reserves_declarer` et `reserves_declarable_squads`
        ont diverge.

    Le siège du modèle n'a AUCUNE action d'annulation, donc ce camp ne pourrait jamais se refermer
    autrement. Les DEUX formes du siège machine sont jouées : l'entraînement gym, où `player_types`
    marque pourtant les deux camps « human », et le siège `ai` d'une partie servie par l'API.
    """
    gs = _saturated_camp_state()
    if seat == "gym":
        gs["gym_training_mode"] = True
    else:
        gs["player_types"]["1"] = "ai"

    assert player_can_still_declare_reserves(gs, 1) is False
    assert current_reserves_declarer(gs) == 2, (
        "le camp saturé reste déclarant : l'étape s'ouvre sans question à poser"
    )
    assert next_reserves_declaration_question(gs) == (2, "u2")
    # LE CHEMIN DE PRODUCTION : c'est le build de masque qui levait.
    assert arm_reserves_declaration_decision(gs) is not None


def test_a_saturated_human_camp_keeps_the_hand_until_it_validates():
    """JUMEAU HUMAIN : le même camp saturé reste déclarant, parce qu'il a encore un choix à défaire.

    20.01 dit « you can select one or more friendly units » — un ensemble que l'humain COMPOSE puis
    fige. Une version précédente fermait ce camp d'office (plus de question posable), et le joueur
    ne pouvait plus retirer de sa déclaration une réserve qu'un fichier de roster avait posée pour
    lui. Ici il annule, sa réserve redevient déclarable, et seul Validate passe la main.
    """
    gs = _saturated_camp_state()

    assert player_can_still_declare_reserves(gs, 1) is True
    assert current_reserves_declarer(gs) == 1, "le camp humain saturé a perdu la main sans valider"
    assert reserves_declaration_step_is_open(gs) is True

    ok, result = deployment_cancel_strategic_reserves(gs, {"unitId": "u1"})
    assert ok, result
    assert reserves_declarable_squads(gs, 1) == ["u1"], "la réserve annulée n'est pas redéclarable"
    assert current_reserves_declarer(gs) == 1

    ok, _ = deployment_validate_reserves_declaration(gs, {})
    assert ok
    assert current_reserves_declarer(gs) == 2
    assert next_reserves_declaration_question(gs) == (2, "u2")


def test_a_camp_with_nothing_at_all_does_not_hold_the_step_open():
    """Ni escouade déclarable ni réserve : le camp n'a aucun geste, l'étape ne l'attend pas.

    VERT VACANT du test ci-dessus : il prouve que le camp saturé est passé, pas que le prédicat
    sait passer un camp vide. Sans ce second cas, un prédicat qui rendrait TOUJOURS faux passerait
    le premier.
    """
    gs = _synthetic_state(
        [
            _synthetic_unit("u1", 1, 5000),  # au-delà du plafond : jamais déclarable
            _synthetic_unit("u2", 2, 50),
        ],
        points_limit=200,
    )
    assert reserves_declarable_squads(gs, 1) == []
    assert reserves_cancellable_squads(gs, 1) == []
    assert player_can_still_declare_reserves(gs, 1) is False
    assert current_reserves_declarer(gs) == 2


# ===========================================================================
# COMPOSITION LIBRE DU SIÈGE HUMAIN — réserver, annuler, valider
# ===========================================================================


def test_the_human_reserves_in_any_order_without_freezing_the_declaration():
    """L'humain réserve l'escouade qu'il veut, et sa déclaration reste ouverte.

    C'est le fond du changement : la version précédente n'acceptait une réponse que sur la TÊTE
    d'une file figée au reset et refusait tout le reste (`not_the_pending_reserves_declaration`),
    une contrainte d'ordre que 20.01 ne porte pas.
    """
    gs = _synthetic_state(
        [
            _synthetic_unit("a", 1, 30),
            _synthetic_unit("b", 1, 30),
            _synthetic_unit("c", 1, 30),
            _synthetic_unit("z", 2, 30),
        ],
        points_limit=200,
    )
    declarable = reserves_declarable_squads(gs, 1)
    assert declarable == ["a", "b", "c"], declarable

    # La DERNIÈRE du pool, pas la tête : c'est précisément ce que l'ancienne file refusait.
    ok, result = deployment_place_in_strategic_reserves(gs, {"unitId": "c"})
    assert ok, result
    assert gs["unit_by_id"]["c"]["in_strategic_reserves"] is True
    assert result["reserves_declaration_open"] is True
    assert current_reserves_declarer(gs) == 1, "la déclaration du camp s'est figée toute seule"


def test_a_reserve_can_be_cancelled_before_validation():
    """Annuler rend l'escouade au pool de pose ET les points au plafond.

    Sans le rendu des points, le joueur ne pourrait plus réserver ce qu'il vient d'annuler : le
    plafond croirait des points engagés qui ne le sont plus.
    """
    # Deux escouades bon marché : réserver la première laisse la seconde déclarable, donc le camp
    # reste déclarant. Avec des valeurs qui saturent le plafond, la main passerait à l'adversaire
    # et l'annulation serait refusée — c'est le comportement que verrouille
    # `test_reserving_the_last_declarable_squad_ends_the_declaration`, pas celui-ci.
    gs = _synthetic_state(
        [_synthetic_unit("a", 1, 30), _synthetic_unit("b", 1, 30), _synthetic_unit("z", 2, 30)],
        points_limit=200,
    )
    ok, _ = deployment_place_in_strategic_reserves(gs, {"unitId": "a"})
    assert ok
    assert reserves_declarable_squads(gs, 1) == ["b"]

    ok, result = deployment_cancel_strategic_reserves(gs, {"unitId": "a"})
    assert ok, result
    assert gs["unit_by_id"]["a"]["in_strategic_reserves"] is False
    assert "a" in gs["deployment_state"]["deployable_units"][1], "escouade non rendue au pool"
    assert result["reservesUsed"] == 0, "points non rendus au plafond"
    assert sorted(reserves_declarable_squads(gs, 1)) == ["a", "b"]


def test_reserves_placed_never_goes_below_zero_on_cancellation():
    """`_reserves_placed` ne passe jamais sous zéro : chaque annulation défait UNE mise comptée.

    Le compteur a DEUX sources — le reset compte les réserves pré-déclarées au roster, le commit
    ajoute celles de l'étape — et `withdraw_strategic_reserves` décrémente sans borne. Le chemin
    sous zéro est barré par construction, et c'est cela qui est verrouillé : (1) une réserve
    pré-déclarée au roster est COMPTÉE au reset, donc son annulation rend 0 et pas -1 ; (2) une
    annulation remet `in_strategic_reserves` à faux, donc `reserves_cancellable_squads` ne propose
    plus l'escouade et la seconde annulation est REFUSÉE avant tout décrément ; (3) réserver,
    annuler, réserver laisse le compteur à 1 — l'aller et le retour se compensent exactement.
    """
    # (1) — réserve posée par le roster : comptée au reset (`_synthetic_state` recopie ce compte).
    gs = _synthetic_state(
        [_synthetic_unit("r", 1, 30, in_reserves=True), _synthetic_unit("b", 1, 30),
         _synthetic_unit("z", 2, 30)],
        points_limit=200,
    )
    assert gs["_reserves_placed"][1] == 1, "la réserve du roster n'est pas comptée : rien à défaire"
    assert reserves_cancellable_squads(gs, 1) == ["r"]
    ok, result = deployment_cancel_strategic_reserves(gs, {"unitId": "r"})
    assert ok, result
    assert gs["_reserves_placed"][1] == 0

    # (2) — seconde annulation de la même escouade : refusée AVANT le décrément.
    assert reserves_cancellable_squads(gs, 1) == [], "l'escouade annulée reste annulable"
    ok, result = deployment_cancel_strategic_reserves(gs, {"unitId": "r"})
    assert not ok
    assert result["error"] == "unit_not_in_strategic_reserves", result
    assert gs["_reserves_placed"][1] == 0, "le compteur est passé sous sa borne"

    # (3) — aller-retour : réserver, annuler, réserver.
    assert deployment_place_in_strategic_reserves(gs, {"unitId": "b"})[0]
    assert gs["_reserves_placed"][1] == 1
    assert deployment_cancel_strategic_reserves(gs, {"unitId": "b"})[0]
    assert gs["_reserves_placed"][1] == 0
    assert deployment_place_in_strategic_reserves(gs, {"unitId": "b"})[0]
    assert gs["_reserves_placed"][1] == 1
    assert gs["_reserves_placed"][2] == 0, "le compteur de l'adversaire a bougé"


def test_validating_with_zero_reserves_is_legal_and_passes_the_hand():
    """« can select » : déclarer AUCUNE réserve est une déclaration, et c'est le cas majoritaire."""
    gs = _synthetic_state(
        [_synthetic_unit("a", 1, 30), _synthetic_unit("z", 2, 30)], points_limit=200
    )
    ok, result = deployment_validate_reserves_declaration(gs, {})
    assert ok, result
    assert all(not u["in_strategic_reserves"] for u in gs["units"])
    assert current_reserves_declarer(gs) == 2, "la main n'est pas passée au camp suivant"
    assert gs["deployment_state"]["current_deployer"] == 2
    assert gs["current_player"] == 2


def test_cancelling_is_refused_once_the_declaration_is_validated():
    """Une déclaration figée ne se reprend pas — sinon « valider » ne voudrait rien dire."""
    # `b` garde le camp déclarant après la mise en réserves de `a` : sans elle, la main passerait
    # à l'adversaire AVANT la validation et le refus observé ne viendrait pas de celle-ci.
    gs = _synthetic_state(
        [_synthetic_unit("a", 1, 30), _synthetic_unit("b", 1, 30), _synthetic_unit("z", 2, 30)],
        points_limit=200,
    )
    ok, _ = deployment_place_in_strategic_reserves(gs, {"unitId": "a"})
    assert ok
    assert current_reserves_declarer(gs) == 1, "le camp a déjà perdu la main : rien à valider"

    ok, _ = deployment_validate_reserves_declaration(gs, {})
    assert ok
    assert gs["deployment_state"][RESERVES_DECLARATION_VALIDATED_KEY][1] is True

    ok, result = deployment_cancel_strategic_reserves(gs, {"unitId": "a"})
    assert not ok
    # La validation a passé la main au camp adverse ; `a` n'est pas une de SES réserves, d'où ce
    # code plutôt qu'un refus de siège — les deux camps sont humains dans cet état synthétique.
    # Ce qui est verrouillé ici n'est pas le libellé du refus mais son EFFET : rien n'a bougé.
    assert result["error"] == "unit_not_in_strategic_reserves", result
    assert gs["unit_by_id"]["a"]["in_strategic_reserves"] is True
    assert "a" not in gs["deployment_state"]["deployable_units"][1]


def test_reserving_the_last_declarable_squad_keeps_a_human_camp_open():
    """Réserver sa dernière escouade déclarable ne fige RIEN : l'humain peut encore défaire ce choix.

    Une version précédente fermait le camp d'office dès qu'aucune question n'était plus posable —
    « contrepartie assumée » d'un prédicat qui ne regardait pas le siège. Le joueur perdait alors
    Cancel ET Validate sur son dernier geste, et le siège ne suivait même pas le déclarant : en PvE
    le tour IA était refusé (`not_ai_player_turn`), l'humain ne pouvait pas poser
    (`reserves_declaration_still_open`), partie figée en déploiement.
    """
    gs = _synthetic_state(
        [_synthetic_unit("a", 1, 30), _synthetic_unit("z", 2, 30)], points_limit=200
    )
    assert current_reserves_declarer(gs) == 1

    ok, _ = deployment_place_in_strategic_reserves(gs, {"unitId": "a"})
    assert ok
    assert reserves_declarable_squads(gs, 1) == [], "le camp a encore de quoi déclarer"

    assert current_reserves_declarer(gs) == 1, "le camp humain a perdu la main sans valider"
    assert gs["deployment_state"]["current_deployer"] == 1
    assert gs["current_player"] == 1

    ok, result = deployment_cancel_strategic_reserves(gs, {"unitId": "a"})
    assert ok, result
    assert reserves_declarable_squads(gs, 1) == ["a"]
    ok, _ = deployment_place_in_strategic_reserves(gs, {"unitId": "a"})
    assert ok

    ok, _ = deployment_validate_reserves_declaration(gs, {})
    assert ok
    assert current_reserves_declarer(gs) == 2
    assert gs["deployment_state"]["current_deployer"] == 2, "le siège n'a pas suivi le déclarant"
    assert gs["current_player"] == 2


def test_the_seat_follows_when_a_human_exhausts_its_declarables_in_pve():
    """JUMEAU PvE du test ci-dessus, sur le CHEMIN DE PRODUCTION : le tour IA doit pouvoir partir.

    P1 humain, P2 modèle. L'humain réserve jusqu'à épuisement : il GARDE la main (il n'a rien
    figé), donc le client ne déclenche aucun tour IA. À sa validation, le déclarant passe au
    modèle ET le siège suit ; sinon le client déclencherait un tour IA sur `current_player == 1`,
    `execute_ai_turn` le refuserait (`not_ai_player_turn`) pendant que `deploy_commit` refuse
    l'humain (`reserves_declaration_still_open`) — personne ne pourrait plus rien faire.

    `gym_training_mode` est retiré de l'état : c'est lui qui rend TOUT camp « machine »
    (`is_programmatic_owner`), et cet état-là est une partie servie par l'API, pas un entraînement.
    Passe par `eng.execute_ai_turn`, comme le client, et non par un build de masque : le masque
    recalerait le siège de lui-même et rendrait ce test vert quel que soit le code.
    """
    eng = _engine()
    gs = eng.game_state
    gs["gym_training_mode"] = False
    gs["player_types"]["2"] = "ai"
    eng.is_pve_mode = True
    assert current_reserves_declarer(gs) == 1

    declarable = reserves_declarable_squads(gs, 1)
    assert len(declarable) >= 2, "il faut au moins deux escouades pour réserver « la dernière »"
    # On réserve jusqu'à épuisement, sans Validate. Le plafond peut fermer avant la dernière : on
    # s'arrête dès que le camp n'a plus rien de déclarable, quelle qu'en soit la raison.
    guard = 0
    while reserves_declarable_squads(gs, 1) and guard < 20:
        target = reserves_declarable_squads(gs, 1)[0]
        ok, result = deployment_place_in_strategic_reserves(gs, {"unitId": target})
        assert ok, result
        guard += 1
    assert guard, "aucune réserve posée : le test n'observe pas le cas visé"
    assert current_reserves_declarer(gs) == 1, "le camp humain a perdu la main sans valider"
    assert gs["current_player"] == 1

    ok, result = deployment_validate_reserves_declaration(gs, {})
    assert ok, result
    assert current_reserves_declarer(gs) == 2, "le déclarant n'est pas passé au modèle"

    # LE CHEMIN DE PRODUCTION : le tour IA du client doit être ACCEPTÉ — c'est le siège qui le
    # permet, et lui seul.
    assert gs["current_player"] == 2, "le siège n'a pas suivi : le tour IA sera refusé"
    ai_ok, ai_result = eng.execute_ai_turn()
    assert ai_ok is True or ai_result.get("error") != "not_ai_player_turn", ai_result


def test_the_step_closes_once_both_camps_have_validated():
    """Deux validations ferment l'étape et rendent la main au premier déployeur."""
    gs = _synthetic_state(
        [_synthetic_unit("a", 1, 30), _synthetic_unit("z", 2, 30)], points_limit=200
    )
    assert reserves_declaration_step_is_open(gs) is True

    ok, _ = deployment_validate_reserves_declaration(gs, {})
    assert ok
    assert reserves_declaration_step_is_open(gs) is True, "l'étape ferme sur UNE seule validation"

    ok, _ = deployment_validate_reserves_declaration(gs, {})
    assert ok
    assert reserves_declaration_step_is_open(gs) is False
    assert gs["deployment_state"][RESERVES_DECLARATION_CLOSED_KEY] is True
    assert gs["deployment_state"]["current_deployer"] == 1
    assert gs["current_player"] == 1


def test_the_human_route_closes_the_phase_when_nothing_is_left_to_place():
    """Roster entièrement mis en réserves : la phase de déploiement se termine, elle ne se fige pas.

    Cas limite RÉEL de 20.01 — un roster dont la valeur tient sous le plafond de 50 % peut partir
    ENTIÈREMENT en réserves, et les deux pools sont alors vides.

    DÉFAUT MESURÉ : la sortie de phase n'existait pas sur la route humaine. Relevé brut sur cet
    état, deux camps entièrement réservés ::

        pools               : {1: [], 2: []}
        etape ouverte       : False
        etape CLOSE         : False
        deployment_complete : False
        phase               : deployment

    Le siège gym n'y tombait pas — son build de masque clôture à chaque tour —, donc aucun test
    passant par `eng.step` ne pouvait le voir. Celui-ci passe par la route HUMAINE, la seule qui
    ne construit aucun masque : chaque camp réserve tout puis VALIDE, et c'est la seconde
    validation qui doit sortir de la phase.
    """
    gs = _synthetic_state(
        [_synthetic_unit("a", 1, 30), _synthetic_unit("z", 2, 30)], points_limit=200
    )
    assert deployment_place_in_strategic_reserves(gs, {"unitId": "a"})[0]
    assert deployment_validate_reserves_declaration(gs, {})[0]
    assert current_reserves_declarer(gs) == 2
    assert deployment_place_in_strategic_reserves(gs, {"unitId": "z"})[0]
    ok, result = deployment_validate_reserves_declaration(gs, {})
    assert ok, result

    ds = gs["deployment_state"]
    # VERT VACANT : sans deux pools vides, la sortie de phase n'est pas ce qui est observé.
    assert not any(ds["deployable_units"][player] for player in (1, 2)), ds["deployable_units"]
    assert ds[RESERVES_DECLARATION_CLOSED_KEY] is True, "l'étape reste ouverte sans rien à déclarer"
    assert ds["deployment_complete"] is True, "la phase de déploiement ne se termine pas"
    assert result["phase_complete"] is True and result["next_phase"] == "command", result


def test_a_partial_declaration_does_not_close_the_phase():
    """VERT VACANT du test ci-dessus : tant qu'il reste à poser, aucune sortie de phase.

    Sans lui, un moteur qui terminerait la phase à CHAQUE mise en réserves passerait le précédent.
    """
    gs = _synthetic_state(
        [_synthetic_unit("a", 1, 30), _synthetic_unit("b", 1, 30), _synthetic_unit("z", 2, 30)],
        points_limit=200,
    )
    ok, result = deployment_place_in_strategic_reserves(gs, {"unitId": "a"})
    assert ok, result

    ds = gs["deployment_state"]
    assert ds["deployable_units"][1] == ["b"], "le pool du joueur 1 devrait rester non vide"
    assert ds["deployment_complete"] is False
    assert "phase_complete" not in result, result


def test_the_declaration_state_survives_a_json_round_trip():
    """Les deux tables par joueur se relisent après un passage par JSON — clés en CHAÎNES.

    C'est l'invariant pour lequel le format de save a été bumpé en TL09 : `deployment_state` est
    sérialisé puis restitué EN BLOC par `services/game_saves`, et JSON rend les clés entières en
    chaînes. Un lecteur qui n'accepterait que `[1]` lèverait sur un état restauré, après que le
    chargement a déjà écrasé la partie en cours — et un écrivain qui n'écrirait que `[1]`
    ajouterait une seconde entrée pour le même joueur, invisible au lecteur.
    """
    import json

    gs = _synthetic_state(
        [_synthetic_unit("a", 1, 30), _synthetic_unit("b", 1, 30), _synthetic_unit("z", 2, 30)],
        points_limit=200,
    )
    assert deployment_place_in_strategic_reserves(gs, {"unitId": "a"})[0]

    restored = json.loads(json.dumps({
        key: value
        for key, value in gs["deployment_state"].items()
        if key != "deployed_units"  # un set ne passe pas JSON ; hors sujet ici
    }))
    # VERT VACANT : sans clés devenues chaînes, le test ne met pas en scène le cas visé.
    assert "1" in restored[RESERVES_DECLARATION_VALIDATED_KEY], restored
    gs["deployment_state"].update(restored)

    assert reserves_declarable_squads(gs, 1) == ["b"], "les refus ne se relisent pas"
    assert current_reserves_declarer(gs) == 1

    ok, _ = deployment_validate_reserves_declaration(gs, {})
    assert ok
    table = gs["deployment_state"][RESERVES_DECLARATION_VALIDATED_KEY]
    assert table["1"] is True, "la validation a créé une entrée que le lecteur ne voit pas"
    assert 1 not in table, "seconde entrée entière pour le même joueur"
    assert current_reserves_declarer(gs) == 2


# ===========================================================================
# EFFETS DE LA RÉPONSE DU SIÈGE MODÈLE
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


def test_declining_keeps_the_unit_in_the_deployment_pool_and_is_not_reasked():
    """`CHOICE_1` (`declines`) n'est PAS un non-événement : il retire la QUESTION, pas l'unité.

    Sans l'inscription du refus, l'escouade resterait déclarable et la même question se reposerait
    indéfiniment — le piège du set de résolution de la déclaration de vol.
    """
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
    assert unit_id in [
        str(uid) for uid in gs["deployment_state"]["deployable_units"][player]
    ], "l'unité refusée a quitté le pool à poser"
    assert unit_id not in reserves_declarable_squads(gs, player), (
        "l'escouade refusée reste interrogeable : la question se reposera"
    )


def test_the_first_deployer_takes_over_once_the_step_is_closed():
    """L'étape déplace `current_deployer` sur le camp déclarant ; la pose repart du joueur 1."""
    eng = _engine()
    trace = _drive(eng)
    placements = [step for step in trace if step["kind"] == "placement"]
    assert placements, "aucune pose : le test ne prouve rien"
    assert placements[0]["player"] == 1, (
        f"la mise en place ne reprend pas par le joueur 1 : {placements[0]}"
    )


def test_a_placement_is_refused_while_the_declaration_step_is_open():
    """Le refus vit dans le HANDLER, pas seulement dans le masque.

    Poser une seule figurine avant la fin des déclarations donnerait au camp qui déclare encore une
    information que la règle lui refuse.
    """
    eng = _engine()
    gs = eng.game_state
    assert reserves_declaration_step_is_open(gs), "étape déjà close : rien à refuser"
    squad_id = str(gs["deployment_state"]["deployable_units"][1][0])

    ok, result = deployment_commit_plan(gs, {"unitId": squad_id, "plan": []})

    assert not ok
    assert result["error"] == "reserves_declaration_still_open", result


# ===========================================================================
# MARQUEUR « ÉTAPE COMMENCÉE » — verrou de `change_roster`
# ===========================================================================


def test_no_gesture_means_the_step_has_not_started():
    """Au reset, aucun geste n'a été posé : les listes sont encore remplaçables."""
    eng = _engine()
    assert reserves_declaration_step_has_started(eng.game_state["deployment_state"]) is False


@pytest.mark.parametrize("declare", [True, False])
def test_the_model_seat_marks_the_step_started(declare: bool):
    """Les DEUX candidats du modèle commencent l'étape — refuser est une réponse."""
    eng = _engine()
    gs = eng.game_state
    eng.get_action_mask()
    assert read_pending_agent_decision(gs) is not None

    eng.step(int(CHOICE_DECLARE if declare else CHOICE_KEEP))

    assert reserves_declaration_step_has_started(gs["deployment_state"]) is True


@pytest.mark.parametrize(
    "gesture", ["reserve", "cancel", "validate"]
)
def test_every_human_gesture_marks_the_step_started(gesture: str):
    """Les TROIS gestes humains commencent l'étape — y compris annuler.

    Une armée remplacée après une simple annulation réécrirait l'état de l'adversaire tout autant
    qu'après une mise en réserves. Un marqueur posé par un seul des trois ferait dépendre le verrou
    de `change_roster` du geste par lequel le joueur a commencé.
    """
    # `b` garde le camp déclarant après la mise en réserves de `a`, sans quoi le geste d'annulation
    # serait refusé pour une raison étrangère à ce que ce test observe.
    gs = _synthetic_state(
        [_synthetic_unit("a", 1, 30), _synthetic_unit("b", 1, 30), _synthetic_unit("z", 2, 30)],
        points_limit=200,
    )
    if gesture == "reserve":
        ok, _ = deployment_place_in_strategic_reserves(gs, {"unitId": "a"})
    elif gesture == "cancel":
        assert deployment_place_in_strategic_reserves(gs, {"unitId": "a"})[0]
        gs["deployment_state"]["reserves_declaration_started"] = False  # isole le geste testé
        ok, _ = deployment_cancel_strategic_reserves(gs, {"unitId": "a"})
    else:
        ok, _ = deployment_validate_reserves_declaration(gs, {})
    assert ok
    assert reserves_declaration_step_has_started(gs["deployment_state"]) is True


def test_an_ineligible_squad_does_not_start_the_step():
    """Une escouade qui ne PEUT pas partir en réserves n'est jamais proposée, et ne commence rien.

    Aucune réponse n'a été donnée pour elle : le verrou de `change_roster` doit rester ouvert.
    """
    gs = _synthetic_state(
        [_synthetic_unit("a", 1, 5000), _synthetic_unit("z", 2, 30)], points_limit=200
    )
    assert reserves_declarable_squads(gs, 1) == [], "l'escouade hors plafond reste proposée"
    assert current_reserves_declarer(gs) == 2
    assert reserves_declaration_step_has_started(gs["deployment_state"]) is False


# ===========================================================================
# LE SIÈGE SUIT LE CAMP DÉCLARANT — les deux routes
# ===========================================================================


def test_the_seat_moves_to_the_other_camp_when_a_human_validates():
    """Valider déplace le siège sur le camp suivant.

    Le siège ne bougeait que sur le chemin gym (`arm_reserves_declaration_decision`). Une partie
    servie par l'API restait donc sur le joueur 1 pendant toute l'étape : en PvE, la déclaration du
    bot était rendue au client alors que le déclencheur de tour IA (`BoardWithAPI`) lit
    `current_deployer` et qu'`execute_ai_turn` refuse hors `current_player == 2`.
    """
    eng = _engine()
    gs = eng.game_state
    assert current_reserves_declarer(gs) == 1, "le joueur 1 ne déclare pas en premier"

    ok, result = deployment_validate_reserves_declaration(gs, {})
    assert ok, result

    assert current_reserves_declarer(gs) == 2
    assert gs["deployment_state"]["current_deployer"] == 2
    assert gs["current_player"] == 2


def test_the_seat_follows_the_first_declarer_at_reset():
    """Le siège est POSÉ sur le premier camp déclarant dès le reset, même si ce n'est pas le 1.

    Un camp sans aucune escouade éligible n'a rien à déclarer : l'étape peut donc s'ouvrir sur le
    camp d'en face alors que le reset place le déployeur sur le joueur 1.
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
        assert current_reserves_declarer(gs) == 2, (
            "le premier déclarant n'est pas le joueur 2 : le test n'observe pas le cas visé"
        )
        assert gs["deployment_state"]["current_deployer"] == 2
        assert gs["current_player"] == 2


def test_the_human_route_refuses_a_declaration_owned_by_a_model_seat():
    """20.01 se déclare depuis SON siège : la route humaine refuse le camp du bot.

    « **you** can select one or more friendly units » (20.01) — la liste d'un camp est décidée par
    ce camp. En PvE le siège 2 est piloté par le modèle ; laisser la route humaine y répondre,
    c'est laisser l'adversaire choisir la liste du bot.

    VERT VACANT : la MÊME route, sur le camp humain, est acceptée juste avant — le refus ne vient
    donc pas d'une route cassée pour tout le monde.
    """
    eng = _engine()
    gs = eng.game_state
    gs["player_types"]["2"] = "ai"

    assert current_reserves_declarer(gs) == 1
    ok, result = deployment_validate_reserves_declaration(gs, {})
    assert ok, result

    assert current_reserves_declarer(gs) == 2, (
        "le camp du modèle ne déclare pas : le test n'observe pas le cas visé"
    )
    target = reserves_declarable_squads(gs, 2)[0]
    ok, result = deployment_place_in_strategic_reserves(gs, {"unitId": target})

    assert not ok
    assert result["error"] == "reserves_declaration_seat_is_not_human", result
    assert result["player"] == 2
    assert gs["unit_by_id"][target]["in_strategic_reserves"] is False


def test_the_seat_follows_the_next_camp_after_the_model_finishes():
    """JUMEAU du siège humain : la fin des réponses du MODÈLE déplace le siège de la même façon.

    Le chemin emprunté est celui de l'API — `_process_squad_action`, ce qu'appelle
    `execute_ai_turn` —, et non `eng.step` : le step gym reconstruit le masque avant de rendre la
    main, et ce build recale le siège de lui-même. Passer par lui rendrait ce test vert quel que
    soit le code, alors que le tour IA du client lit l'état SANS build de masque intermédiaire.

    Défaut mesuré avant écriture, sur cette fixture, en suivant le chemin de l'API ::

        modele repond Q2 -> True | current_player=2 current_deployer=2 | question due: (1, '2')
        tour IA 2 : masque arme joueur 1 unite 2 | current_player=1 current_deployer=1
        => unite 2 du joueur 1 in_strategic_reserves = True

    Le siège restait sur 2 après la réponse du bot, le client relançait un tour IA, le garde
    `current_player == 2` d'`execute_ai_turn` passait — il est lu AVANT le build de masque —, et
    c'est ce build qui armait la déclaration du JOUEUR 1 pour le modèle.
    """
    eng = _engine()
    gs = eng.game_state
    gs["player_types"]["2"] = "ai"
    # `execute_ai_turn` sort sur `not_pve_mode` avant tout le reste : sans ce drapeau, l'assertion
    # finale serait verte pour la mauvaise raison.
    eng.is_pve_mode = True

    ok, result = deployment_validate_reserves_declaration(gs, {})
    assert ok, result
    assert gs["current_player"] == 2, "le siège n'est pas passé au modèle : rien à observer"

    # Tour IA du client : le modèle répond à TOUTES ses escouades, une par build de masque.
    guard = 0
    while current_reserves_declarer(gs) == 2 and guard < 50:
        eng.get_action_mask()
        pending = read_pending_agent_decision(gs)
        assert pending is not None and int(pending["player"]) == 2, pending
        ok, result = eng._process_squad_action(
            {"action": "agent_decision", "option_index": 1}
        )
        assert ok, result
        guard += 1
    assert guard, "le modèle n'a répondu à rien : le test n'observe pas le cas visé"

    assert reserves_declaration_step_is_open(gs) is False, "l'étape reste ouverte"
    assert gs["deployment_state"]["current_deployer"] == 1
    assert gs["current_player"] == 1

    # LE CHEMIN DE PRODUCTION : le tour IA suivant du client doit être REFUSÉ. C'est ce refus, et
    # lui seul, qui empêche le modèle de jouer à la place de l'humain.
    ai_ok, ai_result = eng.execute_ai_turn()
    assert ai_ok is False and ai_result["error"] == "not_ai_player_turn", ai_result
