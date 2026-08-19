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
