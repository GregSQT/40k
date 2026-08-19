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

from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest

import services.api_server as api_server
from services.api_server import app
from tests.integration.pvp.conftest import GameClient, _TEST_AUTH_USER, _TEST_PERMISSIONS
from tests.integration.pvp.invariants import assert_state_invariants

pytestmark = pytest.mark.integration

DEPLOY_SCENARIO = "config/board/44x60x5/scenario/scenario_pvp.json"


# ─────────────────────────────────────────────────────────────────────────────
# Fixture dédiée au déploiement
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def deploy_game(monkeypatch):
    """Partie scenario_pvp.json en phase de déploiement, invariants armés.

    Scénario distinct de INTEGRATION_SCENARIO : scenario_pvp.json a deployment_type=active
    (unités posées à -1,-1), tandis que scenario_pvp_integration.json n'a pas de phase
    de déploiement. Les deux fixtures coexistent sans interférence.
    """
    monkeypatch.setattr(api_server, "_get_authenticated_user_or_response", lambda: (_TEST_AUTH_USER, None))
    monkeypatch.setattr(api_server, "_resolve_permissions_for_profile", lambda _conn, _pid: _TEST_PERMISSIONS)

    import sqlite3
    from contextlib import contextmanager as _ctx

    @_ctx
    def _in_memory_write_cursor(immediate: bool = False):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        try:
            yield connection.cursor()
        finally:
            connection.close()

    monkeypatch.setattr(api_server, "auth_db_write_cursor", _in_memory_write_cursor)
    monkeypatch.setattr(api_server, "_SNAPSHOT_PERSIST_ENABLED", False)
    monkeypatch.setattr(api_server, "_AUTOSAVE_ENABLED", False)

    with app.test_client() as flask_client:
        # check=None : en phase de déploiement les unités non encore posées ont
        # col=-1, row=-1 (sentinel offboard), ce qui violerait l'invariant de position.
        client = GameClient(flask_client, check=None)
        client.start(scenario_file=DEPLOY_SCENARIO)
        yield client

    api_server.engine = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _dep_state(client: GameClient) -> Dict[str, Any]:
    return client.state["deployment_state"]


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
        unit_id = _deployable_for(deploy_game, player)[0]
        models = deploy_game.models_of(unit_id)
        if len(models) < 2:
            pytest.skip("unité mono-figurine, pas de sœur à poser")
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
        assert [taken[0], taken[1], taken[2]] in free
        assert [taken[0], taken[1], taken[2]] not in blocked, (
            f"la case {taken[:2]} occupée par la sœur {first} reste proposée à {second}"
        )


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
