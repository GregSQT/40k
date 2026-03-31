import pytest

import ai.evaluation_bots as eb
from ai.evaluation_bots import (
    DEPLOYMENT_ACTIONS,
    WAIT_ACTION,
    AggressiveSmartBot,
    AdaptiveBot,
    ControlBot,
    DefensiveBot,
    DefensiveSmartBot,
    GreedyBot,
    RandomBot,
    TacticalBot,
    _select_weighted_deployment_action,
)


def test_select_weighted_deployment_action_errors_and_antirepeat(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match=r"No deployment actions"):
        _select_weighted_deployment_action([0, 1], {4: 1.0}, None, 0, 2)

    with pytest.raises(KeyError, match=r"Missing deployment weight"):
        _select_weighted_deployment_action([4], {}, None, 0, 2)

    with pytest.raises(ValueError, match=r"Invalid deployment weights sum"):
        _select_weighted_deployment_action([4], {4: 0.0}, None, 0, 2)

    captured = {}

    def fake_choices(candidates, weights, k):
        captured["candidates"] = candidates
        return [candidates[0]]

    monkeypatch.setattr(eb.random, "choices", fake_choices)
    chosen = _select_weighted_deployment_action(
        valid_actions=[4, 5, 6],
        weights_by_action={4: 1.0, 5: 1.0, 6: 1.0},
        last_action=4,
        repeat_count=2,
        max_repeat=2,
    )
    assert chosen in [5, 6]
    assert 4 not in captured["candidates"]


def test_random_bot_phase_aware_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = RandomBot()
    monkeypatch.setattr(eb.random, "choice", lambda seq: seq[0])
    assert bot.select_action_with_state([4, 9], {"phase": "deployment"}) == 4
    assert bot.select_action_with_state([12, WAIT_ACTION], {"phase": "shoot"}) == 12
    assert bot.select_action_with_state([WAIT_ACTION, 3], {"phase": "move"}) == 3
    assert bot.select_action_with_state([], {"phase": "move"}) == WAIT_ACTION


def test_random_bot_destinations_and_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = RandomBot()
    monkeypatch.setattr(eb.random, "choice", lambda seq: seq[-1])
    assert bot.select_movement_destination({}, [(1, 1), (2, 2)]) == (2, 2)
    assert bot.select_shooting_target(["a", "b"]) == "b"
    assert bot.select_shooting_target([]) == ""


def test_greedy_bot_select_action_and_state(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = GreedyBot(randomness=0.0)
    assert bot.select_action([4, 0]) == 4
    assert bot.select_action([0]) == 0
    assert bot.select_action([]) == WAIT_ACTION

    monkeypatch.setattr(
        eb,
        "_select_weighted_deployment_action",
        lambda **kwargs: 6,
    )
    assert bot.select_action_with_state([4, 5, 6], {"phase": "deployment", "episode_number": 1}) == 6
    assert bot.select_action_with_state([12, WAIT_ACTION], {"phase": "shoot"}) == 12
    assert bot.select_action_with_state([0, WAIT_ACTION], {"phase": "move"}) == 0


def test_greedy_bot_target_selection_uses_low_hp(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = GreedyBot(randomness=0.0)
    game_state = {
        "units": [
            {"id": "1", "player": 0},
            {"id": "2", "player": 1},
            {"id": "3", "player": 1},
        ]
    }
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: uid in {"2", "3"})
    monkeypatch.setattr(eb, "get_hp_from_cache", lambda uid, gs: 5 if uid == "2" else 2)
    assert bot.select_shooting_target(["2", "3"], game_state) == "3"


def test_defensive_bot_action_and_threat_count(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = DefensiveBot(randomness=0.0)
    assert bot.select_action([4, WAIT_ACTION]) == 4
    assert bot.select_action([WAIT_ACTION]) == WAIT_ACTION

    game_state = {
        "phase": "move",
        "current_player": 0,
        "units": [
            {"id": "1", "player": 0, "col": 1, "row": 1},
            {"id": "2", "player": 1, "col": 2, "row": 1},
            {"id": "3", "player": 1, "col": 20, "row": 20},
        ],
    }
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: uid in {"1", "2", "3"})
    monkeypatch.setattr(eb, "calculate_hex_distance", lambda c1, r1, c2, r2: 3 if c2 == 2 else 30)
    # nearby_threats=1 -> move phase uses action 2 (defensive) when available
    assert bot.select_action_with_state([0, 2, WAIT_ACTION], game_state) == 2
    # no defensive action -> WAIT
    assert bot.select_action_with_state([0, WAIT_ACTION], game_state) == WAIT_ACTION

    # shoot phase -> always shoots first target
    shoot_gs = {**game_state, "phase": "shoot"}
    assert bot.select_action_with_state([4, 5, WAIT_ACTION], shoot_gs) == 4


def test_tactical_bot_phase_action_selection() -> None:
    bot = TacticalBot(randomness=0.0)
    assert bot.select_action([], phase="move") == 7
    assert bot.select_action([0, 7], phase="move") == 0
    assert bot.select_action([4, 7], phase="shoot") == 4
    assert bot.select_action([5, 7], phase="charge", game_state={"current_player": 0, "units": []}) == 7
    assert bot.select_action([6, 7], phase="fight") == 6


def test_tactical_bot_select_shooting_target_scoring(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = TacticalBot(randomness=0.0)
    game_state = {
        "current_player": 0,
        "units": [
            {"id": "u0", "player": 0, "RNG_DMG": 4, "CC_DMG": 1},
            {"id": "e1", "player": 1, "RNG_DMG": 2, "CC_DMG": 1},
            {"id": "e2", "player": 1, "RNG_DMG": 1, "CC_DMG": 1},
        ],
    }
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: uid in {"u0", "e1", "e2"})
    monkeypatch.setattr(eb, "get_hp_from_cache", lambda uid, gs: {"u0": 5, "e1": 4, "e2": 6}[uid])
    # e1 is killable (hp<=4), should be favored heavily
    assert bot.select_shooting_target(["e1", "e2"], game_state) == "e1"


def test_tactical_bot_find_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = TacticalBot(randomness=0.0)
    game_state = {
        "current_player": 0,
        "units": [
            {"id": "u0", "player": 0, "col": 1, "row": 1, "CC_DMG": 1, "RNG_DMG": 2},
            {"id": "e1", "player": 1, "col": 4, "row": 1, "CC_DMG": 3, "RNG_DMG": 1},
            {"id": "e2", "player": 1, "col": 9, "row": 1, "CC_DMG": 1, "RNG_DMG": 3},
        ],
    }
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: uid in {"u0", "e1", "e2"})
    monkeypatch.setattr(eb, "calculate_hex_distance", lambda c1, r1, c2, r2: abs(c1 - c2) + abs(r1 - r2))
    active = bot._get_active_unit(game_state)
    assert active["id"] == "u0"
    assert bot._get_unit_by_id(game_state, "e2")["id"] == "e2"
    assert bot._find_nearest_enemy(active, game_state)["id"] == "e1"


def test_tactical_bot_movement_position_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = TacticalBot(randomness=0.0)
    game_state = {
        "units": [
            {"id": "u0", "player": 0},
            {"id": "e1", "player": 1, "col": 5, "row": 5, "CC_DMG": 3, "RNG_DMG": 1},
            {"id": "e2", "player": 1, "col": 10, "row": 10, "CC_DMG": 1, "RNG_DMG": 3},
        ]
    }
    unit = {"id": "u0", "player": 0, "RNG_WEAPONS": [{"RNG": 6}]}
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: uid in {"e1", "e2"})
    monkeypatch.setattr(eb, "calculate_hex_distance", lambda c1, r1, c2, r2: abs(c1 - c2) + abs(r1 - r2))
    monkeypatch.setattr("engine.utils.weapon_helpers.get_max_ranged_range", lambda u: 6)

    safest = bot._find_safest_position(unit, [(1, 1), (2, 2), (8, 8)], game_state)
    assert safest == (1, 1) or safest == (2, 2) or safest == (8, 8)

    best_off = bot._find_best_offensive_position(unit, [(1, 1), (4, 4), (7, 7)], {"col": 8, "row": 8}, game_state)
    assert best_off in [(4, 4), (7, 7)]


def test_control_bot_holds_objective(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = ControlBot(randomness=0.0)
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: True)

    game_state = {
        "phase": "move",
        "current_player": 0,
        "units": [{"id": "1", "player": 0, "col": 5, "row": 5}],
        "objectives": [{"hexes": [{"col": 5, "row": 5}]}],
    }
    # On objective -> WAIT
    assert bot.select_action_with_state([0, 1, 2, 3, WAIT_ACTION], game_state) == WAIT_ACTION

    # Off objective -> action 3 (objective strategy)
    game_state_off = {**game_state, "objectives": [{"hexes": [{"col": 10, "row": 10}]}]}
    assert bot.select_action_with_state([0, 1, 2, 3, WAIT_ACTION], game_state_off) == 3

    # Shoot phase -> shoot first target
    shoot_gs = {**game_state, "phase": "shoot"}
    assert bot.select_action_with_state([4, 5, WAIT_ACTION], shoot_gs) == 4

    # Charge phase on objective -> WAIT
    charge_gs = {**game_state, "phase": "charge"}
    assert bot.select_action_with_state([9, WAIT_ACTION], charge_gs) == WAIT_ACTION


def test_aggressive_smart_bot_advance_and_charge(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = AggressiveSmartBot(randomness=0.0)
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: True)
    gs = {"phase": "move", "current_player": 0, "units": [{"id": "1", "player": 0}]}

    # Move -> aggressive (0)
    assert bot.select_action_with_state([0, 1, 2, WAIT_ACTION], gs) == 0

    # Shoot with no targets -> advance (12)
    shoot_gs = {**gs, "phase": "shoot"}
    assert bot.select_action_with_state([12, WAIT_ACTION], shoot_gs) == 12

    # Shoot with targets -> picks first target slot
    assert bot.select_action_with_state([4, 5, WAIT_ACTION], shoot_gs) == 4

    # Charge -> always charge
    charge_gs = {**gs, "phase": "charge"}
    assert bot.select_action_with_state([9, WAIT_ACTION], charge_gs) == 9


def test_defensive_smart_bot_never_charges(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = DefensiveSmartBot(randomness=0.0)
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: True)
    gs = {"phase": "move", "current_player": 0, "units": [{"id": "1", "player": 0}]}

    # Move -> defensive (2)
    assert bot.select_action_with_state([0, 1, 2, WAIT_ACTION], gs) == 2

    # Charge -> never
    charge_gs = {**gs, "phase": "charge"}
    assert bot.select_action_with_state([9, WAIT_ACTION], charge_gs) == WAIT_ACTION

    # Shoot with no targets -> no advance, just wait
    shoot_gs = {**gs, "phase": "shoot"}
    assert bot.select_action_with_state([12, WAIT_ACTION], shoot_gs) == WAIT_ACTION


def test_adaptive_bot_posture(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = AdaptiveBot(randomness=0.0)
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: True)

    base_gs = {
        "phase": "move",
        "current_player": 0,
        "units": [{"id": "1", "player": 0, "col": 1, "row": 1}],
        "objectives": [{"hexes": [{"col": 5, "row": 5}]}],
        "units_cache": {
            "1": {"col": 1, "row": 1, "player": 0},
        },
    }

    # Turn 1 (early) -> objective rush (action 3)
    gs_early = {**base_gs, "turn": 1}
    assert bot.select_action_with_state([0, 1, 2, 3, WAIT_ACTION], gs_early) == 3

    # Turn 3 losing (no objectives) -> aggressive (action 0)
    gs_late_losing = {**base_gs, "turn": 3}
    assert bot.select_action_with_state([0, 1, 2, 3, WAIT_ACTION], gs_late_losing) == 0

    # Turn 3 winning (on objective) -> defensive (action 2)
    gs_winning = {
        **base_gs, "turn": 3,
        "units": [{"id": "1", "player": 0, "col": 5, "row": 5}],
        "units_cache": {"1": {"col": 5, "row": 5, "player": 0}},
    }
    assert bot.select_action_with_state([0, 1, 2, 3, WAIT_ACTION], gs_winning) == 2

    # Losing charge -> charge
    charge_gs = {**base_gs, "turn": 3, "phase": "charge"}
    assert bot.select_action_with_state([9, WAIT_ACTION], charge_gs) == 9
