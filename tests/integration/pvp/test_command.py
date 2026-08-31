"""T2b — phase command : pool, CP (08.02), battle-shock (08.03).

Règles assertées, lues dans :
  Documentation/40k_rules/08 Command phase.pdf
  Documentation/40k_rules/01 Core concepts.pdf (01.07 — battle-shock roll)

  - 08.02 : les DEUX joueurs gagnent 1 CP à chaque phase de commandement.
  - 08.03 : battle-shock roll = 2D6 vs LD ; résultat < LD → battle-shocked,
            résultat >= LD → succès (l'unité n'est PAS battle-shocked).

La phase de commandement elle-même — arrêt sur Oath (08.04), blocage opposable,
résolution par select_oath_target — est couverte dans test_invariants.py::TestStartState.

Hors couverture de ce fichier (inatteignable avec le roster d'intégration) :
  - reaction_window_active : requiert une unité portant la règle "reactive_move" ;
    aucune unité du roster d'intégration ne l'a.
  - select_rule_choice bloquant : requiert un choix de règle temporel (choice_timing_index)
    déclenché en partie ; le roster d'intégration ne contient aucune telle règle.
"""

from __future__ import annotations

import random

import pytest

from tests.integration.pvp._shared import ActionsExhausted, GameClient

pytestmark = pytest.mark.integration

# game_config.json : starting_command_points = 0
# 08.02 ajoute 1 CP par phase de commandement par joueur.
_STARTING_CP = 0
_CP_GAIN_PER_COMMAND_PHASE = 1


class TestCommandPool:
    """Pool de commandement et gain de CP (08.02)."""

    def test_command_activation_pool_is_empty_at_turn_1(self, game_unchecked):
        """t2b_pool_vide : le pool de command est vide au tour 1.

        command_build_activation_pool (command_handlers.py) est appelé après 08.03.
        Au tour 1, aucune unité du roster d'intégration n'a de capacité « in your
        Command phase » nécessitant une activation joueur explicite.
        """
        state = game_unchecked.state
        assert "command_activation_pool" in state, "command_activation_pool absent du game_state"
        assert state["command_activation_pool"] == [], (
            f"pool non vide au tour 1 : {state['command_activation_pool']}"
        )

    def test_both_players_have_cp_after_08_02(self, game_unchecked):
        """t2b_cp_gain_08_02 : après 08.02, les deux joueurs ont 1 CP (starting=0 + 1).

        Le game_state retourné par /start est déjà APRÈS 08.02 (arrêt sur l'Oath 08.04).
        PDF 08.02 : « Both players gain 1 Command Point (CP). »
        """
        cp = game_unchecked.state.get("command_points")
        assert cp is not None, "command_points absent du game_state"
        expected = _STARTING_CP + _CP_GAIN_PER_COMMAND_PHASE
        cp1 = int(cp.get(1, cp.get("1", -1)))
        cp2 = int(cp.get(2, cp.get("2", -1)))
        assert cp1 == expected, f"joueur 1 : {cp1} CP au lieu de {expected}"
        assert cp2 == expected, f"joueur 2 : {cp2} CP au lieu de {expected}"

    def test_cp_gain_repeats_at_turn_2(self, game):
        """t2b_cp_gain_tour_2 : chaque joueur accumule +1 CP par phase de commandement.

        On s'arrête au move de P2 (tour 1) : 2 phases command ont eu lieu
        (P1 command + P2 command au tour 1), donc expected = 0 + 2 × 1 = 2 CP chacun.
        PDF 08.02 : « Both players gain 1 CP » — les deux joueurs gagnent à chaque
        phase command, quelle que soit la couleur du joueur actif.
        """
        game.play_nominal(
            until=lambda c: int(c.state.get("current_player", 1)) == 2 and c.phase == "move"
        )
        cp = game.state["command_points"]
        expected = _STARTING_CP + 2 * _CP_GAIN_PER_COMMAND_PHASE
        cp1 = int(cp.get(1, cp.get("1", -1)))
        cp2 = int(cp.get(2, cp.get("2", -1)))
        assert cp1 == expected, f"joueur 1 : {cp1} CP au lieu de {expected} après 2 phases command"
        assert cp2 == expected, f"joueur 2 : {cp2} CP au lieu de {expected} après 2 phases command"

    def test_command_phase_leads_to_move(self, game_unchecked):
        """t2b_transition_move : une fois l'Oath joué, la phase bascule vers move.

        Vérifie que drain_to("move") trouve bien le pool de move non vide.
        La transition Oath→move est déjà assertée dans test_invariants.py ; ici on
        vérifie uniquement que le pool est alimenté, ce que TestStartState ne fait pas.
        """
        game_unchecked.drain_to("move")
        assert game_unchecked.phase == "move"
        assert game_unchecked.pool("move_activation_pool"), "pool move vide après transition"


class TestForceBattleShock:
    """force_battle_shock (action test/debug) : mécaniques de battle-shock (08.03 / 01.07).

    PDF 08.03 : « The active player must now make one battle-shock roll (01.07)
    for each unit … ».
    PDF 01.07 : roll 2D6 (range 2–12) vs LD ; result < LD → battle-shocked.
    L'action force_battle_shock est hors séquence de jeu et fonctionne dans n'importe
    quelle phase — ce sont ses effets sur le state qui sont testés ici.
    """

    def test_force_battle_shock_returns_boolean_and_updates_state(self, game):
        """t2b_bs_flag : force_battle_shock renvoie battle_shocked bool et maj l'état."""
        unit_id = game.alive_ids()[0]
        body = game.act("force_battle_shock", unitId=unit_id)
        result = body["result"]
        assert "battle_shocked" in result, "battle_shocked absent de la réponse"
        assert isinstance(result["battle_shocked"], bool), (
            f"battle_shocked doit être bool, got {type(result['battle_shocked'])}"
        )
        unit = game.unit(unit_id)
        assert unit["battle_shocked"] == result["battle_shocked"], (
            "résultat de la réponse incohérent avec le game_state"
        )

    def test_force_battle_shock_is_consistent_across_units(self, game):
        """t2b_bs_coherence : le flag résultat ↔ state est cohérent sur plusieurs unités."""
        for unit_id in game.alive_ids()[:5]:
            body = game.act("force_battle_shock", unitId=unit_id)
            shocked_in_result = body["result"]["battle_shocked"]
            shocked_in_state = game.unit(unit_id)["battle_shocked"]
            assert shocked_in_result == shocked_in_state, (
                f"unité {unit_id} : résultat={shocked_in_result} != state={shocked_in_state}"
            )

    def test_force_battle_shock_unknown_unit_is_rejected(self, game):
        """t2b_bs_inconnu : id inconnu → refus métier HTTP 200 (pas de 500)."""
        accepted, body = game.try_act("force_battle_shock", unitId="999999")
        assert not accepted
        assert body["_status"] == 200, f"attendu HTTP 200, obtenu {body['_status']}"
        assert "error" in body["result"], f"champ error absent : {body['result']}"

    def test_force_battle_shock_without_unit_id_is_rejected(self, game):
        """t2b_bs_sans_id : appel sans unitId → refus explicite."""
        accepted, body = game.try_act("force_battle_shock")
        assert not accepted
        assert body["_status"] == 200
        assert "error" in body["result"]

    def test_roll_below_ld_causes_battle_shock(self, game, monkeypatch):
        """t2b_bs_ld_fail : 2D6 < LD (01.06) → l'unité est battle-shocked (01.07).

        PDF 01.06 : « if the result is equal to or greater than one or more of the Ld
        characteristics in that unit, that roll succeeds. Otherwise, that roll fails. »
        PDF 01.07 : « If that roll fails, that unit, and each model in it, is battle-shocked. »
        PDF 01.07 : « The Objective Control (OC) characteristic of all of its models is
        modified to '-' (02.02). »

        On force les deux dés à 1 (roll=2). Tout LD de roster est >= 6 (datasheets 40k),
        donc 2 < LD : l'unité DOIT être battle-shocked.
        """
        monkeypatch.setattr(random, "randint", lambda a, b: 1)
        unit_id = game.alive_ids()[0]
        body = game.act("force_battle_shock", unitId=unit_id)
        assert body["result"]["battle_shocked"] is True, (
            "roll=2 (1+1) < LD : attendu battle_shocked=True (01.07)"
        )
        assert game.unit(unit_id)["battle_shocked"] is True, (
            "le drapeau battle_shocked doit être True dans le game_state"
        )

    def test_roll_gte_ld_does_not_shock(self, game, monkeypatch):
        """t2b_bs_ld_pass : 2D6 >= LD (01.06) → l'unité n'est PAS battle-shocked (01.07).

        PDF 01.07 : « If that roll succeeds, that unit does not become battle-shocked. »

        On force les deux dés à 6 (roll=12). Tout LD de roster est <= 10 (datasheets 40k),
        donc 12 >= LD : l'unité ne DOIT PAS être battle-shocked.
        """
        monkeypatch.setattr(random, "randint", lambda a, b: 6)
        unit_id = game.alive_ids()[0]
        body = game.act("force_battle_shock", unitId=unit_id)
        assert body["result"]["battle_shocked"] is False, (
            "roll=12 (6+6) >= LD : attendu battle_shocked=False (01.07)"
        )
        assert game.unit(unit_id)["battle_shocked"] is False, (
            "le drapeau battle_shocked doit être False dans le game_state"
        )


# ---------------------------------------------------------------------------
# Grot Orderly (Primitive F, chantier 06 passe 6) — returned_models_placement
# ---------------------------------------------------------------------------

_PVP_TEST_SCENARIO = "config/board/44x60x5/scenario/scenario_pvp_test.json"
# Unité 204 = escouade Boyz (Orks, player 1) qui inclut un PainBoy portant la règle
# `return_destroyed_models`.  L'escouade commence à 12 figurines.
_BOYZ_UNIT_ID = "204"


class TestGrotOrderly:
    """Panneau Grot Orderly : pending_agent_decision.type == returned_models_placement.

    Scénario pvp_test.json : Orks (p1, avec PainBoy dans unité 204) vs SM (p2).
    Flux minimal testé :
      1. Démarrage → phase MOVE tour 1 (Waaagh! résolu par drain_to).
      2. 2 Boyz de l'unité 204 détruits directement dans le game_state.
      3. Jeu avancé jusqu'à la phase command du tour 2 (p1).
      4. La décision returned_models_placement est posée.
      5. Chaque option_index disponible la résout et débloque la partie.

    Hors couverture (couverts en tests unitaires test_returned_models_placement.py) :
      - non-superposition des empreintes à x5 ;
      - correspondance intent → positions exactes.
    """

    @pytest.fixture
    def grot_game(self, api_isolated):
        """Partie pvp_test avec 2 Boyz de l'unité 204 détruits, prête au tour 2."""
        import services.api_server as api_server
        from engine.phase_handlers.shared_utils import destroy_model
        from services.api_server import app

        with app.test_client() as flask_client:
            client = GameClient(flask_client)
            # mode_code="pvp" + scenario_file explicite : même chemin d'init que "pvp",
            # toutes unités déjà placées, aucun déploiement requis.
            client.start(mode_code="pvp", scenario_file=_PVP_TEST_SCENARIO)
            # drain_to("move") résout waaagh_call tour 1 (option 0 = appeler le Waaagh!)
            # et place le curseur en phase MOVE, tour 1, player 1.
            client.drain_to("move")

            assert api_server.engine is not None
            gs = api_server.engine.game_state
            assert _BOYZ_UNIT_ID in gs["squad_models"], (
                f"unité {_BOYZ_UNIT_ID!r} absente de squad_models "
                "(scenario_pvp_test.json modifié ?)"
            )
            squad_mids = list(gs["squad_models"][_BOYZ_UNIT_ID])
            killed = 0
            for mid in squad_mids:
                if killed >= 2:
                    break
                m = gs["models_cache"].get(mid)
                if m is None or "attached_from" in m:
                    # Ne pas tuer les personnages attachés (PainBoy, Warboss) :
                    # détruire le PainBoy ferait perdre la règle return_destroyed_models
                    # à l'unité avant que la command phase ne la vérifie.
                    continue
                destroy_model(gs, mid, "combat")
                killed += 1

            assert killed == 2, (
                f"impossible de trouver 2 Boyz réguliers dans {_BOYZ_UNIT_ID} : "
                f"{killed} détruits"
            )
            # Re-synchronise client.state avec le game_state modifié directement.
            client.refresh()
            yield client

    def _advance_to_returned_models_decision(self, client) -> dict:
        """Joue toutes les actions nominales jusqu'à la décision returned_models_placement.

        Stopppe AVANT de la résoudre — play_nominal vérifie `until` AVANT d'exécuter
        l'action nominale suivante, donc la décision reste pendante à la sortie.
        """
        try:
            client.play_nominal(
                max_actions=600,
                until=lambda c: (
                    (c.state.get("pending_agent_decision") or {}).get("type")
                    == "returned_models_placement"
                ),
            )
        except ActionsExhausted as exc:
            raise AssertionError(
                "returned_models_placement non déclenchée (600 actions épuisées — "
                "cause probable : moteur a appliqué le placement automatiquement, "
                f"1 seule cellule distincte). phase={client.phase} player={client.current_player}"
            ) from exc
        return client.state["pending_agent_decision"]

    def test_decision_apparait_avec_player_et_options(self, grot_game):
        """Panel 'Returned models — player 1' : décision correctement structurée.

        Le front lit `pending_agent_decision.player` pour afficher le numéro de joueur
        (BoardWithAPI.tsx:4193) et `pending_agent_decision.options` pour les boutons.
        """
        decision = self._advance_to_returned_models_decision(grot_game)
        assert decision["player"] == 1, (
            f"attendu player=1 (Orks), obtenu {decision['player']}"
        )
        labels = [o["label"] for o in decision.get("options", [])]
        assert labels, f"pending_agent_decision ne contient aucune option : {decision}"
        # Les labels contractuels viennent de RETURNED_PLACEMENT_INTENTS.
        valid_intents = {"toward_enemy", "toward_objective", "away_from_enemy"}
        assert all(lbl in valid_intents for lbl in labels), (
            f"libellés hors contrat : {labels}"
        )

    @pytest.mark.parametrize("option_index", [0, 1, 2])
    def test_chaque_bouton_resout_la_decision(self, grot_game, option_index):
        """option_index 0/1/2 résout returned_models_placement et débloque la partie.

        Critère front : après le clic, pending_agent_decision.type ≠
        returned_models_placement, et la partie peut avancer en MOVE.
        """
        decision = self._advance_to_returned_models_decision(grot_game)
        options = decision.get("options", [])
        if option_index >= len(options):  # certaines géométries n'offrent pas les 3 intents
            pytest.skip(
                f"option_index={option_index} non offert dans ce contexte géométrique "
                f"({len(options)} options : {[o['label'] for o in options]})"
            )

        grot_game.act("agent_decision", option_index=option_index)

        new_decision = grot_game.state.get("pending_agent_decision")
        assert new_decision is None or new_decision.get("type") != "returned_models_placement", (
            f"returned_models_placement encore pendante après option_index={option_index} : "
            f"{new_decision}"
        )

        # La partie n'est pas bloquée : drain_to lève si la phase MOVE est inatteignable.
        grot_game.drain_to("move")
