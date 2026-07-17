import pytest

import ai.evaluation_bots as eb
from shared.data_validation import require_present
from engine import macro_intents as mi
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

# Espace d'action squad SPATIAL (macro_intents, refonte move_action_space_spatial_rework §6.2) :
#   0-1023 cellules de la grille egocentrique, 1024 wait, 1025-1029 shoot, 1030 charge, 1031 fight,
#   4-8 deploy. Le TYPE de move n'est plus une dimension d'action : le bot choisit une DESTINATION
#   (select_movement_destination), le wrapper la traduit en cellule (cf. env_wrappers). Il n'y a
#   donc plus de "direction de move" ni d'assertion de move via select_action_with_state.
CELL = mi.MOVE_CELL_BASE           # 0, une cellule quelconque (action non-shoot)
SHOOT = mi.SHOOT_SLOT_BASE         # 1025
SHOOT2 = mi.SHOOT_SLOT_BASE + 1    # 1026
CHARGE = mi.ACTION_CHARGE          # 1030
FIGHT = mi.ACTION_FIGHT            # 1031


def _patch_move_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Geometrie deterministe pour les tests de select_movement_destination : empreinte
    single-hex + distance de Manhattan entre les deux hexes representatifs."""
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: True)
    monkeypatch.setattr(eb, "compute_candidate_footprint", lambda c, r, u, gs: {(c, r)})
    monkeypatch.setattr(
        eb, "calculate_hex_distance", lambda c1, r1, c2, r2: abs(c1 - c2) + abs(r1 - r2)
    )

    def _manhattan(a, b, **kwargs):
        (ax, ay) = next(iter(a))
        (bx, by) = next(iter(b))
        return abs(ax - bx) + abs(ay - by)

    monkeypatch.setattr(eb, "min_distance_between_sets", _manhattan)


def _move_gs(unit_hex=(0, 0), enemy_hex=(10, 0), objectives=None):
    ucol, urow = unit_hex
    ecol, erow = enemy_hex
    gs = {
        "current_player": 0,
        "units": [
            {"id": "1", "player": 0, "col": ucol, "row": urow},
            {"id": "e", "player": 1, "col": ecol, "row": erow},
        ],
        "units_cache": {
            "1": {"col": ucol, "row": urow, "player": 0, "occupied_hexes": [(ucol, urow)]},
            "e": {"col": ecol, "row": erow, "player": 1, "occupied_hexes": [(ecol, erow)]},
        },
    }
    if objectives is not None:
        gs["objectives"] = objectives
    return gs, {"id": "1", "player": 0, "col": ucol, "row": urow}


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
    assert bot.select_action_with_state([SHOOT, WAIT_ACTION], {"phase": "shoot"}) == SHOOT
    # No shoot slot available in shoot phase -> WAIT
    assert bot.select_action_with_state([CELL, WAIT_ACTION], {"phase": "shoot"}) == WAIT_ACTION


def test_random_bot_destinations_and_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = RandomBot()
    monkeypatch.setattr(eb.random, "choice", lambda seq: seq[-1])
    # Move spatial : le bot choisit une DESTINATION parmi le pool legal (ici aleatoire).
    assert bot.select_movement_destination({}, [(1, 1), (2, 2)]) == (2, 2)
    assert bot.select_shooting_target(["a", "b"]) == "b"
    assert bot.select_shooting_target([]) == ""


def test_greedy_bot_select_action_and_state(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = GreedyBot(randomness=0.0)
    assert bot.select_action([SHOOT, CELL]) == SHOOT   # shoot prioritaire
    assert bot.select_action([]) == WAIT_ACTION

    monkeypatch.setattr(
        eb,
        "_select_weighted_deployment_action",
        lambda **kwargs: 6,
    )
    assert bot.select_action_with_state([4, 5, 6], {"phase": "deployment", "episode_number": 1}) == 6
    assert bot.select_action_with_state([SHOOT, WAIT_ACTION], {"phase": "shoot"}) == SHOOT


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


def test_greedy_bot_movement_pushes_toward_enemy(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_move_geometry(monkeypatch)
    bot = GreedyBot(randomness=0.0)
    gs, unit = _move_gs(unit_hex=(0, 0), enemy_hex=(10, 0))
    # (8,0) est plus proche de l'ennemi (10,0) que (2,0) -> poussee offensive
    assert bot.select_movement_destination(unit, [(2, 0), (8, 0)], gs) == (8, 0)
    # Aucune destination -> reste sur place (l'ancre, traduite en WAIT par le wrapper)
    assert bot.select_movement_destination(unit, [], gs) == (0, 0)


def test_defensive_bot_movement_keeps_distance(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_move_geometry(monkeypatch)
    bot = DefensiveBot(randomness=0.0)
    gs, unit = _move_gs(unit_hex=(0, 0), enemy_hex=(10, 0))
    # (2,0) plus loin de l'ennemi que (8,0) -> repli
    assert bot.select_movement_destination(unit, [(2, 0), (8, 0)], gs) == (2, 0)


def test_defensive_bot_action_shoot_phase(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = DefensiveBot(randomness=0.0)
    assert bot.select_action([SHOOT, WAIT_ACTION]) == SHOOT
    assert bot.select_action([WAIT_ACTION]) == WAIT_ACTION

    game_state = {
        "phase": "shoot",
        "current_player": 0,
        "units": [
            {"id": "1", "player": 0, "col": 1, "row": 1},
            {"id": "2", "player": 1, "col": 2, "row": 1},
        ],
        "units_cache": {},
        "inches_to_subhex": 1,
    }
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: uid in {"1", "2"})
    # shoot phase -> always shoots first target slot
    assert bot.select_action_with_state([SHOOT, SHOOT2, WAIT_ACTION], game_state) == SHOOT


def test_tactical_bot_phase_action_selection() -> None:
    bot = TacticalBot(randomness=0.0)
    assert bot.select_action([], phase="move") == WAIT_ACTION
    # Move stateless fallback : prefere agir (premiere action non-wait) plutot qu'attendre
    assert bot.select_action([CELL, WAIT_ACTION], phase="move") == CELL
    assert bot.select_action([SHOOT, WAIT_ACTION], phase="shoot") == SHOOT
    # No living active unit -> charge skipped -> WAIT
    assert bot.select_action([CHARGE, WAIT_ACTION], phase="charge", game_state={"current_player": 0, "units": []}) == WAIT_ACTION
    assert bot.select_action([FIGHT, WAIT_ACTION], phase="fight") == FIGHT


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
        "units_cache": {},
    }
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: uid in {"u0", "e1", "e2"})
    monkeypatch.setattr(eb, "calculate_hex_distance", lambda c1, r1, c2, r2: abs(c1 - c2) + abs(r1 - r2))
    active = require_present(bot._get_active_unit(game_state), "active_unit")
    assert active["id"] == "u0"
    assert require_present(bot._get_unit_by_id(game_state, "e2"), "unit_e2")["id"] == "e2"
    assert require_present(bot._find_nearest_enemy(active, game_state), "nearest_enemy")["id"] == "e1"


def test_tactical_bot_movement_position_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = TacticalBot(randomness=0.0)
    game_state = {
        "units": [
            {"id": "u0", "player": 0},
            {"id": "e1", "player": 1, "col": 5, "row": 5, "CC_DMG": 3, "RNG_DMG": 1},
            {"id": "e2", "player": 1, "col": 10, "row": 10, "CC_DMG": 1, "RNG_DMG": 3},
        ],
        "units_cache": {},
        "config": {
            "game_rules": {
                "engagement_zone": 1,
                "engagement_zone_vertical": 5,
                "max_base_size_hex": 35,
                "cover_ratio": 0.3,
                "avg_charge_roll": 7,
            },
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
    }
    unit = {"id": "u0", "player": 0, "RNG_WEAPONS": [{"RNG": 6}]}
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: uid in {"e1", "e2"})
    monkeypatch.setattr(eb, "calculate_hex_distance", lambda c1, r1, c2, r2: abs(c1 - c2) + abs(r1 - r2))
    monkeypatch.setattr("engine.utils.weapon_helpers.get_max_ranged_range", lambda u: 6)

    safest = bot._find_safest_position(unit, [(1, 1), (2, 2), (8, 8)], game_state)
    assert safest == (1, 1) or safest == (2, 2) or safest == (8, 8)

    best_off = bot._find_best_offensive_position(unit, [(1, 1), (4, 4), (7, 7)], {"col": 8, "row": 8}, game_state)
    assert best_off in [(4, 4), (7, 7)]


def test_control_bot_movement_holds_and_seeks_objective(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_move_geometry(monkeypatch)
    bot = ControlBot(randomness=0.0)

    # Sur l'objectif -> tient sa position (renvoie l'ancre, que le wrapper traduit en WAIT)
    gs_on, unit_on = _move_gs(unit_hex=(5, 5), enemy_hex=(20, 20), objectives=[{"hexes": [{"col": 5, "row": 5}]}])
    assert bot.select_movement_destination(unit_on, [(6, 6), (4, 4)], gs_on) == (5, 5)

    # Hors objectif -> se rapproche du centre de l'objectif (10,10)
    gs_off, unit_off = _move_gs(unit_hex=(0, 0), enemy_hex=(20, 20), objectives=[{"hexes": [{"col": 10, "row": 10}]}])
    assert bot.select_movement_destination(unit_off, [(2, 2), (8, 8)], gs_off) == (8, 8)


def test_control_bot_non_move_phases(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = ControlBot(randomness=0.0)
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: True)
    game_state = {
        "phase": "shoot",
        "current_player": 0,
        "units": [{"id": "1", "player": 0, "col": 5, "row": 5}],
        "objectives": [{"hexes": [{"col": 5, "row": 5}]}],
    }
    # Shoot phase -> shoot first target slot
    assert bot.select_action_with_state([SHOOT, SHOOT2, WAIT_ACTION], game_state) == SHOOT
    # Charge phase on objective -> WAIT
    charge_gs = {**game_state, "phase": "charge"}
    assert bot.select_action_with_state([CHARGE, WAIT_ACTION], charge_gs) == WAIT_ACTION


def test_aggressive_smart_bot_movement_and_combat(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_move_geometry(monkeypatch)
    bot = AggressiveSmartBot(randomness=0.0)
    gs, unit = _move_gs(unit_hex=(0, 0), enemy_hex=(10, 0))
    # Pousse vers l'ennemi
    assert bot.select_movement_destination(unit, [(2, 0), (8, 0)], gs) == (8, 0)

    combat_gs = {"phase": "charge", "current_player": 0, "units": [{"id": "1", "player": 0}]}
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, g: True)
    # Charge -> always charge
    assert bot.select_action_with_state([CHARGE, WAIT_ACTION], combat_gs) == CHARGE
    # Shoot with no targets -> wait
    shoot_gs = {**combat_gs, "phase": "shoot"}
    assert bot.select_action_with_state([CELL, WAIT_ACTION], shoot_gs) == WAIT_ACTION
    # Shoot with targets -> picks first target slot
    assert bot.select_action_with_state([SHOOT, SHOOT2, WAIT_ACTION], shoot_gs) == SHOOT


def test_defensive_smart_bot_movement_and_no_charge(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_move_geometry(monkeypatch)
    bot = DefensiveSmartBot(randomness=0.0)
    gs, unit = _move_gs(unit_hex=(0, 0), enemy_hex=(10, 0))
    # Garde ses distances -> s'eloigne de l'ennemi
    assert bot.select_movement_destination(unit, [(2, 0), (8, 0)], gs) == (2, 0)

    combat_gs = {"phase": "charge", "current_player": 0, "units": [{"id": "1", "player": 0}]}
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, g: True)
    # Charge -> never
    assert bot.select_action_with_state([CHARGE, WAIT_ACTION], combat_gs) == WAIT_ACTION


def test_adaptive_bot_movement_posture(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_move_geometry(monkeypatch)
    bot = AdaptiveBot(randomness=0.0)

    # Turn 1 (early) -> rush objectif : se rapproche du centre (10,10)
    gs_early, unit_early = _move_gs(unit_hex=(0, 0), enemy_hex=(20, 0), objectives=[{"hexes": [{"col": 10, "row": 10}]}])
    gs_early["turn"] = 1
    assert bot.select_movement_destination(unit_early, [(2, 2), (8, 8)], gs_early) == (8, 8)

    # Turn 3 losing (aucun objectif controle) -> agressif : pousse vers l'ennemi (10,0)
    gs_losing, unit_losing = _move_gs(unit_hex=(0, 0), enemy_hex=(10, 0), objectives=[{"hexes": [{"col": 99, "row": 99}]}])
    gs_losing["turn"] = 3
    assert bot.select_movement_destination(unit_losing, [(2, 0), (8, 0)], gs_losing) == (8, 0)

    # Turn 3 winning (controle l'objectif sous ses pieds) -> defensif : s'eloigne de l'ennemi
    gs_win, unit_win = _move_gs(unit_hex=(5, 5), enemy_hex=(10, 5), objectives=[{"hexes": [{"col": 5, "row": 5}]}])
    gs_win["turn"] = 3
    assert bot.select_movement_destination(unit_win, [(2, 5), (8, 5)], gs_win) == (2, 5)


def test_adaptive_bot_charge_posture(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = AdaptiveBot(randomness=0.0)
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: True)
    base_gs = {
        "phase": "charge",
        "current_player": 0,
        "turn": 3,
        "units": [{"id": "1", "player": 0, "col": 1, "row": 1}],
        "objectives": [{"hexes": [{"col": 5, "row": 5}]}],
        "units_cache": {"1": {"col": 1, "row": 1, "player": 0}},
    }
    # Losing charge -> charge
    assert bot.select_action_with_state([CHARGE, WAIT_ACTION], base_gs) == CHARGE
