"""T3a — phase de déploiement : alternance, destinations, formation, commit, transition.

Règles 40k relatives au déploiement (core rules, pas de PDF dédié dans Documentation/40k_rules/) :
  - Le joueur 1 déploie en premier, puis alternance après chaque unité déployée.
  - Toute figurine posée doit appartenir à la zone de déploiement du joueur.
  - Après que tous les déployeurs ont posé toutes leurs unités : transition vers command.

Scénario utilisé : scenario_pvp.json (4 unités = 2 par joueur, deployment_type=active).
L'armée est ADEPTUS ASTARTES pour les deux camps : l'Oath of Moment (08.04) se déclenchera
après la transition vers command — géré automatiquement par pending_faction_decision().

Flux PvP par escouade : deploy_generate_formation (plan par-figurine) + deploy_commit.
Le flux legacy deploy_unit (ancre unique, sans plan) est hors couverture : utilisé par
le bot (BotControlledEnv), pas exposé au joueur humain côté front.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

import pytest

import services.api_server as api_server
from services.api_server import app
from tests.integration.pvp._shared import GameClient, _TEST_AUTH_USER, _TEST_PERMISSIONS
from tests.integration.pvp.invariants import assert_state_invariants

pytestmark = pytest.mark.integration

DEPLOY_SCENARIO = "config/board/44x60x5/scenario/scenario_pvp.json"


# ─────────────────────────────────────────────────────────────────────────────
# Fixture dédiée au déploiement
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def deploy_game(api_isolated):
    """Partie scenario_pvp.json en phase de déploiement, invariants armés.

    Scénario distinct de INTEGRATION_SCENARIO : scenario_pvp.json a deployment_type=active
    (unités posées à -1,-1), tandis que scenario_pvp_integration.json n'a pas de phase
    de déploiement. Les deux fixtures coexistent sans interférence.
    """
    with app.test_client() as flask_client:
        # check=None : en phase de déploiement les unités non encore posées ont
        # col=-1, row=-1 (sentinel offboard), ce qui violerait l'invariant de position.
        client = GameClient(flask_client, check=None)
        client.start(scenario_file=DEPLOY_SCENARIO)
        # 20.01 — l'étape Declare Battle Formations précède la mise en place et bloque
        # `deploy_commit` tant qu'elle est ouverte. Ce fichier couvre la MISE EN PLACE (alternance,
        # zone, formation, transition) : les questions sont donc réglées ici en déclinant, comme
        # avant ce chantier où aucune unité ne partait en réserves. L'étape elle-même est couverte
        # par `TestDeclareBattleFormations` plus bas.
        _settle_reserves_declarations(client)
        yield client


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _dep_state(client: GameClient) -> Dict[str, Any]:
    return client.state["deployment_state"]


def _reserves_declaration(client: GameClient) -> Dict[str, Any]:
    """20.01 — le résumé de l'étape Declare Battle Formations publié par l'API.

    Trois lectures : `declaring_player` (le camp qui compose, ou ``None`` étape close),
    `declarable` (ses escouades encore proposables) et `cancellable` (celles qu'il peut retirer).
    """
    return client.state.get("strategic_reserves", {})


def _declaring_player(client: GameClient) -> Optional[int]:
    player = _reserves_declaration(client).get("declaring_player")
    return None if player is None else int(player)


def _settle_reserves_declarations(client: GameClient, limit: int = 4) -> int:
    """Valide la déclaration de chaque camp SANS rien réserver. Rend le nombre de validations.

    L'étape Declare Battle Formations PRÉCÈDE la mise en place : tant qu'un camp déclare,
    `deploy_commit` est refusé (`reserves_declaration_still_open`). Le siège humain fige sa
    déclaration par `validate_reserves_declaration` — valider sans avoir rien réservé est légal
    (« can select »), et c'est le cas majoritaire.
    """
    validated = 0
    while validated < limit:
        if _declaring_player(client) is None:
            return validated
        client.act("validate_reserves_declaration")
        validated += 1
    raise AssertionError(f"étape 20.01 non close après {limit} validations")


def _current_deployer(client: GameClient) -> int:
    return int(_dep_state(client)["current_deployer"])


def _deployable_for(client: GameClient, player: int) -> List[str]:
    dep = _dep_state(client)["deployable_units"]
    raw = dep.get(player, dep.get(str(player), []))
    return [str(uid) for uid in raw]


def _deployment_zone(client: GameClient, player: int) -> Set[Tuple[int, int]]:
    """Ensemble des cellules légales pour le joueur (lu depuis deployment_pools)."""
    pools = client.state.get("deployment_pools", {})
    raw = pools.get(player, pools.get(str(player), []))
    return {(int(c), int(r)) for c, r in raw}


def _median_cell(cells: Set[Tuple[int, int]]) -> Tuple[int, int]:
    """Cellule médiane d'un ensemble — tend à tomber au centre de la zone."""
    sorted_cells = sorted(cells)
    return sorted_cells[len(sorted_cells) // 2]


def _first_multimodel_unit(client: GameClient, player: int) -> Optional[str]:
    """Première unité de `player` avec >= 2 figurines (None si aucune)."""
    return next(
        (u for u in _deployable_for(client, player) if len(client.models_of(u)) >= 2),
        None,
    )


def _generate_and_commit(client: GameClient, unit_id: str, player: int) -> Dict[str, Any]:
    """Génère une formation compacte et la committe pour une unité.

    Flux front : deploy_generate_formation → plan → deploy_commit.
    Le centre est la cellule médiane de la zone pour éviter le débordement.
    """
    center_col, center_row = _median_cell(_deployment_zone(client, player))
    gen_body = client.act(
        "deploy_generate_formation",
        unitId=unit_id,
        destCol=center_col,
        destRow=center_row,
    )
    plan = gen_body["result"]["plan"]
    return client.act("deploy_commit", unitId=unit_id, plan=plan)


def _deploy_all(client: GameClient) -> None:
    """Déploie toutes les unités restantes par formation automatique."""
    while client.phase == "deployment":
        ds = _dep_state(client)
        if ds.get("deployment_complete", False):
            break
        deployer = int(ds["current_deployer"])
        deployable = _deployable_for(client, deployer)
        if not deployable:
            break
        _generate_and_commit(client, deployable[0], deployer)


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDeploymentPhaseState:
    """État initial de la phase de déploiement."""

    def test_phase_is_deployment_on_start(self, deploy_game):
        """t3a_phase : le scénario pvp démarre en phase de déploiement."""
        assert deploy_game.phase == "deployment"

    def test_player_1_deploys_first(self, deploy_game):
        """t3a_deployer_p1 : le joueur 1 est le premier déployeur."""
        assert _current_deployer(deploy_game) == 1

    def test_each_player_has_2_deployable_units(self, deploy_game):
        """t3a_deployable_count : 2 unités déployables par joueur (scénario pvp.json)."""
        p1_units = _deployable_for(deploy_game, 1)
        p2_units = _deployable_for(deploy_game, 2)
        assert len(p1_units) == 2, f"joueur 1 : {len(p1_units)} unités au lieu de 2"
        assert len(p2_units) == 2, f"joueur 2 : {len(p2_units)} unités au lieu de 2"

    def test_all_deployable_units_are_offboard(self, deploy_game):
        """t3a_hors_table : toutes les unités à déployer commencent à la sentinelle (-1,-1).

        w40k_core.py force col=-1, row=-1 sur chaque unité de type « active » à l'init
        de la partie — c'est l'invariant qui identifie « pas encore sur le plateau ».
        """
        for player in (1, 2):
            for uid in _deployable_for(deploy_game, player):
                unit = deploy_game.unit(uid)
                assert unit["col"] == -1 and unit["row"] == -1, (
                    f"unité {uid} (joueur {player}) : col={unit['col']}, row={unit['row']} "
                    f"au lieu de -1,-1"
                )

    def test_deployment_pools_are_non_empty_for_both_players(self, deploy_game):
        """t3a_pools_non_vides : chaque joueur a des cellules disponibles dans sa zone."""
        zone1 = _deployment_zone(deploy_game, 1)
        zone2 = _deployment_zone(deploy_game, 2)
        assert zone1, "zone de déploiement vide pour le joueur 1"
        assert zone2, "zone de déploiement vide pour le joueur 2"
        # Les deux zones sont disjointes : un joueur ne peut pas se déployer dans la zone adverse.
        assert zone1.isdisjoint(zone2), "zones de déploiement P1 et P2 se chevauchent"


class TestDeployModelDestinations:
    """deploy_model_destinations : pool de cases légales par figurine."""

    def test_destinations_are_in_deployment_zone(self, deploy_game):
        """t3a_destinations_zone : toutes les destinations ⊆ zone de déploiement du joueur.

        La zone est lue dans deployment_pools[player] et le pool BFS de déploiement
        en est un sous-ensemble (contrainte « footprint dans la zone »).
        """
        player = _current_deployer(deploy_game)
        unit_id = _deployable_for(deploy_game, player)[0]
        model_id = deploy_game.models_of(unit_id)[0]
        zone = _deployment_zone(deploy_game, player)

        body = deploy_game.act("deploy_model_destinations", model_id=model_id)
        destinations = body["result"]["destinations"]
        assert destinations, f"pool vide pour la figurine {model_id}"
        for col, row, _level in destinations:
            assert (int(col), int(row)) in zone, (
                f"destination ({col}, {row}) hors zone de déploiement du joueur {player}"
            )

    def test_sister_already_placed_blocks_her_cell(self, deploy_game):
        """t3a_plan_provisoire : une sœur posée dans le plan retire sa case du pool des suivantes.

        Miroir exact du test move (test_move.py::test_sisters_already_placed_block_the_pool),
        appliqué à la zone de déploiement au lieu d'un budget de mouvement.
        """
        player = _current_deployer(deploy_game)
        unit_id = _first_multimodel_unit(deploy_game, player)
        if unit_id is None:
            pytest.skip("aucune unité multi-figurine disponible pour ce joueur")
        models = deploy_game.models_of(unit_id)
        first, second = models[0], models[1]

        # Destinations sans plan provisoire.
        free = deploy_game.act("deploy_model_destinations", model_id=second)["result"]["destinations"]
        # Poser la première figurine dans une case du pool de la seconde.
        taken = next((d for d in free), None)
        assert taken is not None
        # Avec le plan provisoire.
        blocked = deploy_game.act(
            "deploy_model_destinations",
            model_id=second,
            provisional_plan={first: [taken[0], taken[1], taken[2]]},
        )["result"]["destinations"]
        assert [taken[0], taken[1], taken[2]] not in blocked, (
            f"la case {taken[:2]} occupée par la sœur {first} reste proposée à {second}"
        )


class TestDeploySquadDestinations:
    """deploy_squad_destinations : ancres légales pour le bloc entier (translation rigide)."""

    def test_squad_destinations_subset_of_zone(self, deploy_game):
        """t3a_squad_dest_zone : toutes les ancres renvoyées gardent le bloc dans la zone.

        Flux : génère une formation provisoire (deploy_generate_formation), puis demande
        deploy_squad_destinations avec ce plan. Chaque ancre candidate [col, row] doit
        appartenir à la zone de déploiement — par construction de l'érosion BFS.
        """
        player = _current_deployer(deploy_game)
        unit_id = _first_multimodel_unit(deploy_game, player)
        if unit_id is None:
            pytest.skip("aucune unité multi-figurine disponible pour ce joueur")
        zone = _deployment_zone(deploy_game, player)

        center_col, center_row = _median_cell(zone)
        plan = deploy_game.act(
            "deploy_generate_formation",
            unitId=unit_id,
            destCol=center_col,
            destRow=center_row,
        )["result"]["plan"]
        assert plan, "deploy_generate_formation n'a rien renvoyé"

        body = deploy_game.act("deploy_squad_destinations", plan=plan)
        destinations = body["result"]["destinations"]
        assert destinations, "deploy_squad_destinations a renvoyé un pool vide"
        for col, row in destinations:
            assert (int(col), int(row)) in zone, (
                f"ancre ({col}, {row}) hors zone de déploiement du joueur {player}"
            )

    def test_squad_destinations_requires_plan(self, deploy_game):
        """t3a_squad_dest_plan_requis : appel sans plan → refus HTTP 400."""
        accepted, body = deploy_game.try_act("deploy_squad_destinations")
        assert not accepted
        assert body.get("_status") == 400


class TestDeployGenerateFormation:
    """deploy_generate_formation : plan complet par-figurine."""

    def test_formation_covers_all_models(self, deploy_game):
        """t3a_formation_complete : le plan couvre TOUTES les figurines de l'unité."""
        player = _current_deployer(deploy_game)
        unit_id = _deployable_for(deploy_game, player)[0]
        models = deploy_game.models_of(unit_id)

        center_col, center_row = _median_cell(_deployment_zone(deploy_game, player))
        body = deploy_game.act(
            "deploy_generate_formation",
            unitId=unit_id,
            destCol=center_col,
            destRow=center_row,
        )
        result = body["result"]
        assert "plan" in result
        plan_model_ids = [str(entry[0]) for entry in result["plan"]]
        assert sorted(plan_model_ids) == sorted(models), (
            f"plan {plan_model_ids} ne couvre pas toutes les figurines {models}"
        )

    def test_formation_is_valid_and_in_zone(self, deploy_game):
        """t3a_formation_valide : la formation générée est validable et dans la zone.

        deploy_generate_formation renvoie can_validate=True si toutes les positions
        sont légales. Un centre au milieu de la zone doit produire un plan valide.
        """
        player = _current_deployer(deploy_game)
        unit_id = _deployable_for(deploy_game, player)[0]
        zone = _deployment_zone(deploy_game, player)

        center_col, center_row = _median_cell(zone)
        body = deploy_game.act(
            "deploy_generate_formation",
            unitId=unit_id,
            destCol=center_col,
            destRow=center_row,
        )
        result = body["result"]
        assert result.get("can_validate") is True, (
            f"formation non valide au centre de la zone : {result}"
        )
        for entry in result["plan"]:
            _model_id, col, row, _level = entry
            assert (int(col), int(row)) in zone, (
                f"figurine {_model_id} posée hors zone à ({col}, {row})"
            )

    def test_formation_wrong_player_is_rejected(self, deploy_game):
        """t3a_formation_mauvais_deployer : P2 ne peut pas générer une formation pendant le tour de P1."""
        # P1 déploie en premier.
        p2_unit_id = _deployable_for(deploy_game, 2)[0]
        center_col, center_row = _median_cell(_deployment_zone(deploy_game, 2))
        accepted, body = deploy_game.try_act(
            "deploy_generate_formation",
            unitId=p2_unit_id,
            destCol=center_col,
            destRow=center_row,
        )
        assert not accepted
        assert body["result"]["error"] == "unit_not_current_deployer"


class TestDeployCommit:
    """deploy_commit : placement effectif + alternance des déployeurs."""

    def test_commit_places_unit_in_zone(self, deploy_game):
        """t3a_commit_positions : après commit, toutes les figurines sont dans la zone."""
        player = _current_deployer(deploy_game)
        unit_id = _deployable_for(deploy_game, player)[0]
        zone = _deployment_zone(deploy_game, player)

        _generate_and_commit(deploy_game, unit_id, player)

        for model_id in deploy_game.models_of(unit_id):
            model = deploy_game.state["models_cache"][model_id]
            assert (int(model["col"]), int(model["row"])) in zone, (
                f"figurine {model_id} posée hors zone à ({model['col']}, {model['row']})"
            )

    def test_commit_removes_unit_from_deployable(self, deploy_game):
        """t3a_commit_retire : l'unité quitte deployable_units après commit."""
        player = _current_deployer(deploy_game)
        unit_id = _deployable_for(deploy_game, player)[0]
        assert unit_id in _deployable_for(deploy_game, player)

        _generate_and_commit(deploy_game, unit_id, player)

        remaining = _deployable_for(deploy_game, player)
        assert unit_id not in remaining, f"unité {unit_id} encore dans deployable après commit"

    def test_commit_alternates_deployer(self, deploy_game):
        """t3a_alternance : après P1, c'est P2 qui déploie (alternance 1→2→1→2)."""
        assert _current_deployer(deploy_game) == 1
        unit_id = _deployable_for(deploy_game, 1)[0]
        _generate_and_commit(deploy_game, unit_id, 1)

        assert _current_deployer(deploy_game) == 2, (
            "après le premier deploy de P1, P2 n'est pas le déployeur courant"
        )

    def test_commit_wrong_player_unit_is_rejected(self, deploy_game):
        """t3a_commit_mauvais_deployer : committer une unité adverse → unit_not_deployable."""
        # P1 est le déployeur courant. Essayer de committer une unité P2.
        p2_unit_id = _deployable_for(deploy_game, 2)[0]
        models = deploy_game.models_of(p2_unit_id)
        # Un plan quelconque : le refus intervient avant la validation géométrique.
        fake_plan = [[m, 0, 0, 0] for m in models]
        accepted, body = deploy_game.try_act(
            "deploy_commit", unitId=p2_unit_id, plan=fake_plan
        )
        assert not accepted
        assert body["result"]["error"] == "unit_not_deployable", (
            f"motif de refus inattendu : {body['result']}"
        )

    def test_full_deployment_sequence_alternates_correctly(self, deploy_game):
        """t3a_sequence_alternance : la séquence complète alterne P1→P2→P1→P2.

        4 unités au total : P1 déploie d'abord, puis P2, puis P1, puis P2.
        """
        expected_sequence = [1, 2, 1, 2]
        actual_sequence: List[int] = []

        while deploy_game.phase == "deployment":
            ds = _dep_state(deploy_game)
            if ds.get("deployment_complete", False):
                break
            deployer = int(ds["current_deployer"])
            actual_sequence.append(deployer)
            unit_id = _deployable_for(deploy_game, deployer)[0]
            _generate_and_commit(deploy_game, unit_id, deployer)

        assert actual_sequence == expected_sequence, (
            f"séquence de déploiement {actual_sequence} au lieu de {expected_sequence}"
        )


class TestDeployTransition:
    """Transition déploiement → command → move."""

    def test_full_deployment_transitions_to_move(self, deploy_game):
        """t3a_transition_move : une fois tous déployés, la partie atteint la phase move.

        Le cascade après le dernier deploy_commit déclenche : command phase → Oath (géré
        par pending_faction_decision) → move. Le pool de move doit être non vide.
        """
        _deploy_all(deploy_game)
        deploy_game.play_nominal(until=lambda c: c.phase == "move")
        assert deploy_game.phase == "move"
        assert deploy_game.pool("move_activation_pool"), "pool move vide après transition"

    def test_full_deployment_both_players_placed(self, deploy_game):
        """t3a_deploiement_complet : après tous les commits, deployment_complete est True."""
        _deploy_all(deploy_game)
        # Après le dernier commit, le cascade enclenche la phase command
        # et deployment_complete est mis à True.
        ds = _dep_state(deploy_game)
        assert ds.get("deployment_complete", False) is True, (
            "deployment_complete non mis à True après tous les déploiements"
        )

    def test_change_roster_rejected_outside_deployment(self, game):
        """t3a_change_roster_hors_phase : change_roster est rejeté hors de la phase de déploiement.

        La fixture game est en phase move ; la règle est donc vérifiée dans un état de
        production normal.
        """
        accepted, body = game.try_act("change_roster", player=1)
        assert not accepted
        assert body["result"]["error"] == "change_roster_only_in_deployment"


# ─────────────────────────────────────────────────────────────────────────────
# 20.01 — Declare Battle Formations, côté siège HUMAIN
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def declaration_game(api_isolated):
    """Partie `scenario_pvp.json` ARRÊTÉE sur la première question 20.01.

    Distincte de `deploy_game`, qui règle l'étape pour couvrir la mise en place : ici c'est
    l'étape elle-même qui est sous test, elle ne peut donc pas être consommée par la fixture.
    """
    with app.test_client() as flask_client:
        client = GameClient(flask_client, check=None)
        client.start(scenario_file=DEPLOY_SCENARIO)
        yield client


class TestDeclareBattleFormations:
    """20.01 — la déclaration précède la mise en place, y compris pour le joueur humain."""

    def test_a_camp_is_declaring_before_any_placement(self, declaration_game):
        """L'API publie le camp déclarant et ses escouades proposables ; rien n'est sur la table."""
        summary = _reserves_declaration(declaration_game)
        assert summary.get("declaring_player") == 1, (
            "aucun camp déclarant publié : le bandeau PvP resterait inerte"
        )
        assert summary.get("declarable"), (
            "le camp déclarant n'a aucune escouade proposable : les boutons Reserve seraient morts"
        )
        assert summary.get("cancellable") == [], "rien n'est en réserves au départ de l'étape"
        on_board = [
            u for u in declaration_game.state["units"] if u["deployed_on_turn"] is not None
        ]
        assert not on_board, (
            f"20.01 : {[u['id'] for u in on_board]} déjà posées alors qu'une déclaration est due"
        )

    def test_placement_is_refused_while_the_step_is_open(self, declaration_game):
        """`deploy_commit` refusé tant que l'étape est ouverte — le refus vient du MOTEUR.

        Le front ne fait que ne pas proposer le geste ; c'est ce refus-là qui rend la règle vraie
        même pour un client qui l'ignorerait.
        """
        player = _current_deployer(declaration_game)
        unit_id = _deployable_for(declaration_game, player)[0]
        center_col, center_row = _median_cell(_deployment_zone(declaration_game, player))
        gen_body = declaration_game.act(
            "deploy_generate_formation",
            unitId=unit_id,
            destCol=center_col,
            destRow=center_row,
        )
        plan = gen_body["result"]["plan"]

        accepted, body = declaration_game.try_act("deploy_commit", unitId=unit_id, plan=plan)

        assert not accepted
        assert body["result"]["error"] == "reserves_declaration_still_open", body["result"]

    def test_reserving_holds_the_unit_off_table_in_any_order(self, declaration_game):
        """`deploy_strategic_reserves` met l'escouade en réserves et la sort du pool — la DERNIÈRE
        du pool, pas la première : 20.01 n'impose aucun ordre, et l'ancienne file refusait tout
        ce qui n'était pas sa tête."""
        player = _declaring_player(declaration_game)
        assert player == 1
        declarable = _reserves_declaration(declaration_game)["declarable"]
        assert len(declarable) >= 2, "il faut deux escouades pour choisir « pas la première »"
        unit_id = str(declarable[-1])

        declaration_game.act("deploy_strategic_reserves", unitId=unit_id)

        unit = next(u for u in declaration_game.state["units"] if str(u["id"]) == unit_id)
        assert unit["in_strategic_reserves"] is True
        assert unit["deployed_on_turn"] is None
        assert unit_id not in _deployable_for(declaration_game, player)
        assert unit_id in _reserves_declaration(declaration_game)["cancellable"]
        # Le camp n'a PAS fini : il reste déclarant tant qu'il n'a pas validé.
        assert _declaring_player(declaration_game) == player

    def test_cancelling_returns_the_unit_to_the_pool(self, declaration_game):
        """`cancel_strategic_reserves` défait une mise en réserves avant validation."""
        player = _declaring_player(declaration_game)
        assert player is not None, "aucun camp déclarant : le test n'a rien à annuler"
        unit_id = str(_reserves_declaration(declaration_game)["declarable"][0])
        declaration_game.act("deploy_strategic_reserves", unitId=unit_id)
        assert unit_id in _reserves_declaration(declaration_game)["cancellable"]

        declaration_game.act("cancel_strategic_reserves", unitId=unit_id)

        unit = next(u for u in declaration_game.state["units"] if str(u["id"]) == unit_id)
        assert unit["in_strategic_reserves"] is False
        assert unit_id in _deployable_for(declaration_game, player)
        assert unit_id in _reserves_declaration(declaration_game)["declarable"]

    def test_validating_passes_the_hand_and_two_validations_close_the_step(
        self, declaration_game
    ):
        """Valider fige le camp et passe la main ; la seconde validation ferme l'étape."""
        assert _declaring_player(declaration_game) == 1

        declaration_game.act("validate_reserves_declaration")

        assert _declaring_player(declaration_game) == 2, "la main n'est pas passée au joueur 2"
        assert int(_dep_state(declaration_game)["current_deployer"]) == 2
        assert int(declaration_game.state["current_player"]) == 2

        declaration_game.act("validate_reserves_declaration")

        assert _declaring_player(declaration_game) is None, "l'étape reste ouverte"
        assert int(_dep_state(declaration_game)["current_deployer"]) == 1, (
            "la mise en place ne repart pas du joueur 1"
        )

    def test_change_roster_rebuilds_the_declaration_lists(self, declaration_game):
        """`change_roster` remplace les unités ET compacte leurs ids : les listes doivent suivre.

        Le changement de roster est NOMINAL tant qu'aucun geste 20.01 n'a été posé — le premier le
        refuse désormais (`test_change_roster_is_refused_once_a_declaration_has_been_answered`),
        et c'est ce test-ci qui prouve que ce refus n'est pas devenu inconditionnel.

        Un état laissé tel qu'au reset garderait des ids qui n'existent plus :
        `_strategic_reserves_summary` tourne à chaque sérialisation d'état et levait
        `unit_can_be_placed_in_strategic_reserves: unit ... introuvable`.
        """
        # Roster de TAILLE DIFFÉRENTE de celui du scénario : c'est le décalage de la compaction
        # d'ids qui fait diverger les listes, pas le remplacement en lui-même.
        declaration_game.act(
            "change_roster", player=1, army_file="armageddon_space_marines.json"
        )

        summary = _reserves_declaration(declaration_game)
        known_ids = {str(u["id"]) for u in declaration_game.state["units"]}
        owner_by_id = {
            str(u["id"]): int(u["player"]) for u in declaration_game.state["units"]
        }
        player = summary["declaring_player"]
        assert player == 1, summary
        unknown = [uid for uid in summary["declarable"] if str(uid) not in known_ids]
        assert not unknown, f"les listes 20.01 nomment des unités inexistantes : {unknown}"
        mismatched = [uid for uid in summary["declarable"] if owner_by_id[str(uid)] != player]
        assert not mismatched, (
            f"les listes 20.01 attribuent des unités au mauvais joueur : {mismatched}"
        )
        # VERT VACANT : une liste VIDE passerait les deux contrôles ci-dessus.
        assert summary["declarable"], "aucune escouade déclarable après changement de roster"

    def test_change_roster_leaves_the_seat_on_the_rebuilt_declarer(self, declaration_game):
        """Le camp déclarant peut changer au remplacement : le siège doit le suivre.

        `change_roster` restaure le déployeur d'avant le remplacement, mais l'étape est rebâtie sur
        un autre roster — et un camp sans aucune escouade éligible (FORTIFICATION, plafond de 50 %)
        n'a rien à déclarer. Le premier déclarant peut donc passer au camp d'en face, et le siège
        resté en arrière rendrait la déclaration d'un joueur depuis celui d'en face — en PvE, sans
        qu'aucun tour IA ne parte.

        INSTRUMENT : l'éligibilité du joueur 1 est fermée pendant le remplacement, ce qui fait du
        joueur 2 le premier déclarant. Sans lui les deux camps sont symétriques dans cette fixture,
        le joueur 1 reste premier, et le test ne distinguerait pas un siège qui suit d'un siège figé.
        """
        from unittest.mock import patch

        import engine.phase_handlers.deployment_handlers as dh

        real_predicate = dh.unit_can_be_placed_in_strategic_reserves

        def _only_player_two(game_state, unit_id):
            unit = game_state["unit_by_id"][str(unit_id)]
            if int(unit["player"]) == 1:
                return False
            return bool(real_predicate(game_state, unit_id))

        with patch.object(dh, "unit_can_be_placed_in_strategic_reserves", _only_player_two):
            declaration_game.act(
                "change_roster", player=1, army_file="armageddon_space_marines.json"
            )
            declarer = _declaring_player(declaration_game)

        assert declarer == 2, (
            "le premier déclarant n'est pas passé au joueur 2 : le test n'observe pas le cas visé"
        )
        assert int(_dep_state(declaration_game)["current_deployer"]) == 2
        assert int(declaration_game.state["current_player"]) == 2

    def test_change_roster_is_refused_once_a_declaration_has_been_answered(
        self, declaration_game
    ):
        """20.01 se déclare sur des listes ARRÊTÉES : la première réponse gèle les deux rosters.

        Le verrou est GLOBAL, pas par joueur. Sans lui, mesuré sur ce scénario : le joueur 2
        déclare une escouade en réserves, le joueur 1 change d'armée, et l'escouade du joueur 2
        revient dans `deployable_units` tout en gardant `in_strategic_reserves` — « instead of
        setting up these units on the battlefield » (20.01) violé, et la question 20.01 reposée à
        un joueur qui y avait déjà répondu.

        VERT VACANT : un refus inconditionnel passerait ce test mais mettrait
        `test_change_roster_rebuilds_the_declaration_lists` au rouge — c'est lui qui prouve que le
        changement d'armée reste possible AVANT tout geste.
        """
        answering_player = _declaring_player(declaration_game)
        assert answering_player is not None, "aucun camp déclarant : le test n'a rien à poser"
        unit_id = str(_reserves_declaration(declaration_game)["declarable"][0])
        declaration_game.act("deploy_strategic_reserves", unitId=unit_id)

        for player in (1, 2):
            accepted, body = declaration_game.try_act(
                "change_roster", player=player, army_file="armageddon_space_marines.json"
            )
            assert not accepted, (
                f"joueur {player} a pu changer d'armée après une réponse du joueur "
                f"{answering_player}"
            )
            assert (
                body["result"]["error"] == "change_roster_locked_after_reserves_declaration"
            ), body["result"]

    def test_the_step_closes_and_deployment_resumes_with_player_one(self, declaration_game):
        """Une fois les deux camps validés, la mise en place reprend, joueur 1 d'abord."""
        validated = _settle_reserves_declarations(declaration_game)
        assert validated == 2, f"deux validations attendues, {validated} faites"
        assert _declaring_player(declaration_game) is None
        assert _current_deployer(declaration_game) == 1
        # VERT VACANT : l'étape close doit RÉELLEMENT rouvrir la pose, pas seulement se taire.
        player = 1
        unit_id = _deployable_for(declaration_game, player)[0]
        _generate_and_commit(declaration_game, unit_id, player)
        unit = next(u for u in declaration_game.state["units"] if str(u["id"]) == unit_id)
        assert unit["deployed_on_turn"] is not None
