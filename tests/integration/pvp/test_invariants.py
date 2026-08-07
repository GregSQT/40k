"""T2 — invariants transversaux du flux PvP.

Le socle : si un de ces tests échoue, aucune assertion de règle plus fine n'a de sens.
"""

from __future__ import annotations

import copy

import pytest

from tests.integration.pvp.invariants import assert_state_invariants

pytestmark = pytest.mark.integration


class TestStartState:
    def test_start_serves_a_coherent_state(self, game_unchecked):
        """t2_start_invariants : l'état initial satisfait tous les invariants."""
        assert_state_invariants(game_unchecked.state, "start")

    def test_start_is_command_phase_stopped_on_the_oath_designation(self, game_unchecked):
        """t2_start_command : la partie démarre en phase command, ARRÊTÉE sur l'Oath (08.04).

        Ce n'était pas le contrat jusqu'au chantier des capacités de faction : la phase de
        commandement enchaînait sur le mouvement et ``/start`` rendait ``move``. Elle s'arrête
        désormais sur une décision de joueur, et le camp 1 de la fixture est ADEPTUS ASTARTES —
        la désignation d'Oath n'est pas optionnelle (« select one unit from your opponent's
        army »), donc l'arrêt est certain, pas dépendant d'un tirage.
        """
        state = game_unchecked.state
        assert state["phase"] == "command"
        assert int(state["current_player"]) == 1
        assert int(state["turn"]) == 1
        assert int(state["pending_oath_selection"]) == 1, (
            "la phase de commandement n'est pas arretee sur la designation d'Oath"
        )

    def test_start_refuses_any_action_until_the_oath_is_designated(self, game_unchecked):
        """t2_start_arret_opposable : l'arrêt de 08.04 refuse tout le reste, `advance_phase` inclus.

        Sans ce refus, un `advance_phase` terminait la phase avec la désignation encore posée :
        elle était purgée à l'ouverture de la command phase suivante et le joueur perdait ses
        relances de touche pour tout le tour, sans message.
        """
        accepted, body = game_unchecked.try_act("advance_phase")
        assert not accepted
        assert body["result"]["error"] == "faction_decision_pending"
        assert game_unchecked.state["phase"] == "command"
        assert int(game_unchecked.state["pending_oath_selection"]) == 1

        # Le bouton « fin de phase » est sous la main du joueur pendant cet arrêt, et la phase de
        # commandement n'était pas dans la table de pools de `_execute_end_phase_action` : le clic
        # LEVAIT, donc HTTP 500 sur une action de jeu ordinaire. Refus métier attendu, en 200.
        accepted, body = game_unchecked.try_act("end_phase", player=1)
        assert body["_status"] == 200, f"end_phase a levé au lieu de refuser : HTTP {body['_status']}"
        assert not accepted
        assert body["result"]["details"]["error"] == "faction_decision_pending"
        assert game_unchecked.state["phase"] == "command"
        assert int(game_unchecked.state["pending_oath_selection"]) == 1

    def test_start_lands_in_move_once_the_oath_is_played(self, game_unchecked):
        """t2_start_move : la désignation jouée, la phase de mouvement DÉMARRE.

        Pas « rend un `phase_complete` » : la phase doit avoir effectivement basculé et le pool de
        move être construit. Les deux routes de décision sortent du moteur AVANT la boucle de
        cascade — le seul endroit où une transition s'exécute — donc le `next_phase: move` rendu
        au client a décrit pendant un temps une transition qui n'avait pas eu lieu. Le PvP n'a
        AUCUN verbe de sortie de la phase de commandement : la partie restait bloquée là.
        """
        target = game_unchecked.alive_ids(2)[0]
        body = game_unchecked.act("select_oath_target", unitId=target)
        assert body["result"]["next_phase"] == "move"
        assert game_unchecked.state["pending_oath_selection"] is None
        assert game_unchecked.state["oath_target"]["1"] == target
        assert game_unchecked.phase == "move", (
            "la phase annonce le mouvement sans y basculer : la partie reste en commandement"
        )
        assert game_unchecked.pool("move_activation_pool"), "phase de mouvement sans pool"

    def test_start_has_units_of_both_players(self, game_unchecked):
        """t2_start_deux_joueurs : les deux camps ont des unités vivantes."""
        assert game_unchecked.alive_ids(1), "aucune unité vivante pour le joueur 1"
        assert game_unchecked.alive_ids(2), "aucune unité vivante pour le joueur 2"


class TestInvariantsUnderActions:
    def test_invariants_hold_while_draining_the_move_phase(self, game):
        """t2_drain_move : les invariants tiennent après chaque skip jusqu'à la fin de move.

        La fixture ``game`` revalide tout le jeu d'invariants après CHAQUE action ; ce
        test n'a donc qu'à dérouler la phase et vérifier qu'elle se termine.
        """
        actions = 0
        while game.phase == "move" and game.pool("move_activation_pool"):
            game.act("skip", unitId=game.pool("move_activation_pool")[0])
            actions += 1
            assert actions < 200, "la phase move ne se vide pas (boucle)"
        assert actions > 0, "le pool de move était vide au démarrage"
        assert not game.pool("move_activation_pool")

    def test_advance_phase_reports_pool_empty_then_shoot(self, game):
        """t2_transition_move_shoot : pool vidé → advance_phase → phase shoot.

        Miroir exact du front : il n'y a pas de transition automatique, c'est le client
        qui envoie ``advance_phase`` quand le pool est vide.
        """
        while game.phase == "move" and game.pool("move_activation_pool"):
            game.act("skip", unitId=game.pool("move_activation_pool")[0])
        body = game.act("advance_phase")
        result = body["result"]
        assert result["phase_complete"] is True
        assert result["reason"] == "pool_empty"
        assert game.phase == "shoot"


class TestRejectedActionsAreInert:
    """Toute action refusée doit laisser le state STRICTEMENT inchangé.

    Contrat de refus relevé dans le code (``execute_action``, api_server.py:2368) :
    HTTP 200, ``success: false``, le motif machine dans ``result.error``
    (``unit_not_eligible``, ``invalid_destination``, ``invalid_action_for_phase``…).
    """

    def _assert_inert(self, game, action: str, expected_error: str, **payload) -> None:
        # Toujours comparer deux états lus par /api/game/state : la route /start enrichit
        # sa réponse de champs qui lui sont propres (max_turns, pve_mode), une comparaison
        # croisée entre les deux sources signalerait des différences qui n'en sont pas.
        before = copy.deepcopy(game.refresh())
        accepted, body = game.try_act(action, **payload)
        assert not accepted, f"action {action!r} acceptée à tort : {body.get('result')}"
        assert body["_status"] == 200, (
            f"action {action!r} : refus attendu en HTTP 200, obtenu {body['_status']} "
            f"— {str(body.get('error'))[:200]}"
        )
        assert body["result"]["error"] == expected_error, (
            f"action {action!r} : motif de refus {body['result'].get('error')!r} "
            f"au lieu de {expected_error!r}"
        )
        after = game.refresh()
        differences = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        assert not differences, f"action refusée {action!r} : champs modifiés {differences}"

    def test_activating_an_enemy_unit_is_rejected(self, game):
        """t2_rejet_unite_ennemie : activer une unité adverse ne change rien."""
        enemy_id = game.alive_ids(game.enemy_player())[0]
        self._assert_inert(game, "activate_unit", "unit_not_eligible", unitId=enemy_id)

    def test_unknown_action_is_rejected(self, game):
        """t2_rejet_action_inconnue : un verbe hors vocabulaire est refusé proprement."""
        self._assert_inert(game, "action_qui_nexiste_pas", "invalid_action_for_phase")

    def test_moving_outside_the_board_is_rejected(self, game):
        """t2_rejet_hors_board : une destination hors board est refusée."""
        unit_id = game.pool("move_activation_pool")[0]
        game.act("activate_unit", unitId=unit_id)
        self._assert_inert(game, "move", "invalid_destination", unitId=unit_id, destCol=-5, destRow=-5)

    def test_move_without_activation_auto_activates_then_rejects_destination(self, game):
        """t2_move_sans_activation : l'auto-activation a lieu, la destination invalide est refusée.

        Contrat délibéré du moteur (movement_handlers.py:819-841) : pour un joueur humain,
        un ``move`` sur une unité non activée l'active d'abord, puis traite la destination.
        Le refus laisse donc l'unité activée avec son preview — ce n'est pas une mutation
        parasite. Ce qui doit rester vrai : l'unité n'a NI bougé NI quitté le pool.
        """
        unit_id = game.pool("move_activation_pool")[0]
        before = game.unit(unit_id)
        origin = (before["col"], before["row"])

        accepted, body = game.try_act("move", unitId=unit_id, destCol=origin[0], destRow=origin[1])

        assert not accepted
        assert body["result"]["error"] == "invalid_destination"
        assert str(game.state["active_movement_unit"]) == unit_id, "l'auto-activation n'a pas eu lieu"
        after = game.unit(unit_id)
        assert (after["col"], after["row"]) == origin, "l'unité a bougé malgré le refus"
        assert unit_id in game.pool("move_activation_pool"), "l'unité a quitté le pool sur un refus"
        assert unit_id not in [str(u) for u in game.state["units_moved"]]

    def test_unknown_unit_id_is_a_clean_business_refusal(self, game):
        """t2_rejet_id_inconnu : un id d'unité inexistant est refusé, pas planté.

        Le pré-traitement de ``_process_semantic_action`` récupère l'unité avant l'action
        (il servait alors à logger sa position, avant que le bloc step_logger de cette
        méthode — inatteignable — ne soit supprimé) ; il levait ``KeyError`` sur un id inconnu,
        donnant une HTTP 500 là où toute la logique de jeu répond ``unit_not_found`` en
        200 (movement_handlers.py:797, shooting_handlers.py:5429…). Une saisie invalide du
        client est un refus métier ordinaire, avec le même contrat que les autres.
        """
        self._assert_inert(game, "activate_unit", "unit_not_found", unitId="999999")
