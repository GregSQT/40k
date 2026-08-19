"""T7b — partie complète et fuzzing par invariants (budget étendu).

Les tranches T2/T3 vérifient des scénarios CONNUS. Ici on couvre l'imprévu : une partie
entière jouée jusqu'à sa fin, puis des séquences d'actions tirées au hasard. Dans les deux
cas, ce sont les invariants transversaux (revalidés après CHAQUE action par la fixture
``game``) qui font le travail — ces tests ne cherchent pas un résultat, ils cherchent une
incohérence.

Reproductibilité : ``tests/conftest.py`` pose ``random.seed(12345)`` avant chaque test, et
le moteur tire tous ses dés sur ce ``random`` global. Le tirage des actions utilise son
propre ``random.Random(seed)`` pour ne pas déplacer la séquence de dés du moteur. Un échec
est donc rejouable à l'identique.

Budget étendu (T7b §fuzzing étendu) : ``TestFullGame`` est désormais paramétré sur 3 graines
de jets de dés → 3 trajectoires de partie distinctes. ``TestRandomWalk`` monte de 3 à 5
graines, borné à 200 actions (contre 120 précédemment).
"""

from __future__ import annotations

import copy
import random
from typing import Any, Dict, List, Tuple

import pytest

pytestmark = pytest.mark.integration

# Actions LÉGALES au sens du vocabulaire de la phase — le fuzzer les tire pour explorer
# des enchaînements que les tests scriptés ne produisent pas. Elles peuvent être refusées
# (c'est prévu) ; ce qui est vérifié, c'est qu'aucune ne casse un invariant.
EXPLORATORY_ACTIONS = {
    "move": ["activate_unit", "right_click", "wait", "advance", "preview_move_plan"],
    "shoot": ["squad_shoot_activate", "squad_shoot_los_overview", "squad_shoot_cancel"],
    "charge": ["activate_unit", "right_click", "charge_plan_state"],
}

# Actions ILLÉGALES. Le payload mêle ids valides et ids inexistants : depuis la correction
# de §0.6.1, un id inconnu est un refus métier ``unit_not_found`` comme un autre, il a donc
# sa place dans le fuzzing négatif.
ILLEGAL_ACTIONS = {
    "move": ["charge", "fight", "squad_shoot_activate", "commit_charge_plan"],
    "shoot": ["move", "advance", "commit_move_plan", "fight"],
    "charge": ["move", "advance", "squad_shoot_activate"],
}

# Phases dont le dispatch REFUSE explicitement un verbe hors vocabulaire. La phase fight
# en est absente à dessein : son dispatch renvoie success=True sans rien faire pour tout
# verbe d'une autre sous-phase (cf. FIGHT_SUBPHASE_EXIT dans conftest.py), un refus ne
# peut donc pas y être exigé.
STRICT_DISPATCH_PHASES = ("move", "shoot", "charge")

# Aucune anomalie tolérée : toute HTTP 500 est un échec. Il n'y a plus d'allowlist
# depuis la correction du cycle de vie des activations de tir (§0.6.2).


def _random_payload(client, rng: random.Random) -> Dict[str, Any]:
    """Cible plausible : une unité au hasard, parfois une destination au hasard."""
    payload: Dict[str, Any] = {}
    alive = client.alive_ids()
    if rng.random() < 0.1:
        # Id inexistant : refus métier attendu, jamais une 500 (§0.6.1).
        payload["unitId"] = f"999{rng.randrange(1000)}"
    elif alive:
        payload["unitId"] = rng.choice(alive)
    if rng.random() < 0.3:
        payload["destCol"] = rng.randrange(client.state["board_cols"])
        payload["destRow"] = rng.randrange(client.state["board_rows"])
    return payload


def _assert_full_game_coherence(game, die_seed: int) -> None:
    """Corps partagé : rejoue la partie depuis l'état courant et vérifie la cohérence globale.

    ``die_seed`` re-graine le moteur APRÈS la fixture : la partie a déjà démarré avec la graine
    autouse (12345) mais les jets de combat/charge qui suivent utilisent ``die_seed``, produisant
    ainsi des trajectoires distinctes pour chaque paramètre.
    """
    import random as _random
    _random.seed(die_seed)

    seen: List[Tuple[int, int, str]] = []

    def record(client) -> bool:
        marker = (int(client.state["turn"]), client.current_player, client.phase)
        if not seen or seen[-1] != marker:
            seen.append(marker)
        return bool(client.state.get("game_over"))

    actions = game.play_nominal(max_actions=1500, until=record)

    assert game.state["game_over"] is True, "la partie ne s'est pas terminée"
    assert actions > 50, f"partie suspecte (graine {die_seed}) : seulement {actions} actions"

    turns = [turn for turn, _player, _phase in seen]
    assert turns == sorted(turns), f"(graine {die_seed}) le numéro de tour a reculé : {turns}"
    max_turns = game.start_state["max_turns"]
    assert max(turns) <= max_turns, (
        f"(graine {die_seed}) tour {max(turns)} au-delà de max_turns={max_turns}"
    )
    assert min(turns) == 1

    phases_played = {phase for _turn, _player, phase in seen}
    assert {"move", "shoot", "charge", "fight"} <= phases_played, (
        f"(graine {die_seed}) phases jamais jouées : "
        f"{{'move','shoot','charge','fight'}} - {phases_played}"
    )
    players_per_turn: Dict[int, set] = {}
    for turn, player, _phase in seen:
        players_per_turn.setdefault(turn, set()).add(player)
    for turn, players in players_per_turn.items():
        if turn < max(turns):
            assert players == {1, 2}, (
                f"(graine {die_seed}) tour {turn} : joueurs actifs {players}"
            )

    victory_points = game.state["victory_points"]
    assert set(victory_points) == {"1", "2"}
    assert all(points >= 0 for points in victory_points.values())
    winner = game.state["winner"]
    if winner is not None:
        best = max(victory_points, key=lambda player: victory_points[player])
        assert str(winner) == best, (
            f"(graine {die_seed}) winner={winner} alors que les VP donnent {victory_points}"
        )


class TestFullGame:
    def test_a_whole_game_stays_coherent_until_game_over(self, game):
        """t7b_partie_complete : partie jouée jusqu'à la fin, invariants après chaque action.

        Couvre ce qu'aucun test de phase ne voit : l'alternance des joueurs, l'incrément
        des tours, la fin de partie et le décompte final. Graine par défaut : 12345 (autouse).
        """
        _assert_full_game_coherence(game, die_seed=12345)

    @pytest.mark.parametrize("die_seed", [11111, 22222])
    def test_full_game_with_alternate_die_seeds(self, game, die_seed):
        """t7b_budget : deux trajectoires supplémentaires (jets de dés différents).

        La fixture démarre la partie avec la graine autouse, mais les jets de combat/charge
        qui suivent utilisent ``die_seed`` → résultats de combats distincts, parties distinctes.
        """
        _assert_full_game_coherence(game, die_seed=die_seed)


class TestRandomWalk:
    @pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
    def test_random_legal_actions_never_break_an_invariant(self, game, seed):
        """t7b_marche_aleatoire : actions tirées au hasard, invariants tenus à chaque pas.

        Deux tiers d'actions nominales (pour que la partie progresse et traverse les
        phases), un tiers d'actions exploratoires du vocabulaire de la phase courante.
        Budget étendu : 5 graines (contre 3), 200 actions par marche (contre 120).
        """
        rng = random.Random(seed)
        journal: List[Tuple[str, Dict[str, Any]]] = []

        for _ in range(200):
            if game.state.get("game_over"):
                break
            exploratory = EXPLORATORY_ACTIONS.get(game.phase)
            if exploratory and rng.random() < 0.34:
                action = rng.choice(exploratory)
                payload = _random_payload(game, rng)
            else:
                action, payload = game.nominal_action()
            journal.append((action, payload))
            # try_act ne lève pas sur un refus : un refus est un résultat acceptable ici,
            # c'est la revalidation des invariants (dans le client) qui juge.
            _accepted, body = game.try_act(action, **payload)
            assert body["_status"] != 500, (
                f"HTTP 500 sur {action!r} (seed={seed}) — "
                f"{str(body.get('error'))[:300]}\njournal : {journal[-8:]}"
            )

        assert journal, "aucune action jouée"


class TestNegativeFuzzing:
    @pytest.mark.parametrize("seed", [11, 12, 13])
    def test_illegal_actions_are_refused_without_side_effect(self, game, seed):
        """t7b_fuzzing_negatif : une action illégale ne passe jamais et ne change rien.

        Budget étendu : 3 graines (contre 2), 60 itérations (contre 40).
        """
        rng = random.Random(seed)
        checked = 0

        for _ in range(60):
            phase = game.phase
            if phase not in STRICT_DISPATCH_PHASES:
                nominal, nominal_payload = game.nominal_action()
                game.act(nominal, **nominal_payload)
                continue

            before = copy.deepcopy(game.refresh())
            action = rng.choice(ILLEGAL_ACTIONS[phase])
            payload = _random_payload(game, rng)
            accepted, body = game.try_act(action, **payload)

            assert body["_status"] != 500, (
                f"HTTP 500 sur l'action illégale {action!r} en phase {phase} "
                f"(seed={seed}) — {str(body.get('error'))[:300]}"
            )
            assert not accepted, f"action illégale {action!r} acceptée en phase {phase}"
            assert body["result"]["error"], f"refus de {action!r} sans motif"
            after = game.refresh()
            differences = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
            assert not differences, (
                f"l'action illégale {action!r} en phase {phase} a modifié : {differences}"
            )
            checked += 1

            # Faire avancer la partie pour varier les contextes de refus.
            nominal, nominal_payload = game.nominal_action()
            game.act(nominal, **nominal_payload)

        assert checked >= 10, f"seulement {checked} actions illégales éprouvées"
