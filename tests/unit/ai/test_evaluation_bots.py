import pytest

import ai.evaluation_bots as eb
from shared.data_validation import require_present
from engine import macro_intents as mi
from ai.evaluation_bots import (
    DEPLOYMENT_ACTIONS,
    WAIT_ACTION,
    AdaptiveBot,
    ControlBot,
    DefensiveBot,
    GreedyBot,
    RandomBot,
    TacticalBot,
    ValueTradeBot,
    _count_objectives_controlled,
    _select_weighted_deployment_action,
    _squad_on_objective,
)
from tests._state_invariants import turn_state_invariants, unit_invariants

# Espace d'action squad SPATIAL (macro_intents, refonte move_action_space_spatial_rework §6.2) :
#   0-1023 cellules de la grille egocentrique, 1024 wait, 1025-1029 shoot, 1030 charge, 1031 fight,
#   4-8 deploy. Le TYPE de move n'est plus une dimension d'action : le bot choisit une DESTINATION
#   (select_movement_destination), le wrapper la traduit en cellule (cf. env_wrappers). Il n'y a
#   donc plus de "direction de move" ni d'assertion de move via select_action_with_state.
CELL = mi.MOVE_CELL_BASE           # 0, une cellule quelconque (action non-shoot)
SHOOT = mi.SHOOT_SLOT_BASE         # 1025
SHOOT2 = mi.SHOOT_SLOT_BASE + 1    # 1026
# V11 §9 P3-2 : la charge est un SLOT ennemi (comme le tir et la melee), plus une action nue.
CHARGE = mi.CHARGE_SLOT_BASE       # 1045 — « charger le slot 0 »
FIGHT_SLOT0 = mi.FIGHT_SLOT_BASE     # 1046 — frapper le slot ennemi 0
FIGHT_EMPTY = mi.ACTION_FIGHT_NO_TARGET  # 1066 — combat a vide (12.04/12.06)


def _dmg(rng: float = 0.0, cc: float = 0.0) -> dict:
    """Tableaux d'armes (MULTIPLE_WEAPONS_IMPLEMENTATION.md) produisant les degats attendus voulus.

    Remplace les anciens champs RNG_DMG/CC_DMG, SUPPRIMES du contrat d'unite : les bots lisent
    desormais RNG_WEAPONS/CC_WEAPONS via get_max_ranged_damage / get_max_melee_damage (NB x DMG).
    NB=1 -> le degat attendu vaut exactement `rng` / `cc`. Liste vide -> 0.0.
    """
    return {
        "RNG_WEAPONS": [{"NB": 1, "DMG": rng}] if rng else [],
        "CC_WEAPONS": [{"NB": 1, "DMG": cc}] if cc else [],
    }


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


# ⚠️ Le moteur ne connait que les joueurs 1 et 2 : `current_player` hors {1,2} leve
# (fight_handlers `_normalize_current_player` et fin de phase de combat), et le wrapper pose
# `bot_player = 2 if controlled_player == 1 else 1`. Toute doublure joue donc 1 vs 2 : une
# doublure en 0/1 rendait indetectables les fautes de derivation du camp adverse (`3 - player`).
ACTING = 1
FOE = 2


def _act(bot, valid_actions, gs, active=None):
    """Appelle le bot comme le wrapper : l'escouade ACTIVEE est fournie, jamais devinee.

    `env_wrappers._get_bot_action` passe `eligible_units[0]`, la MEME escouade dont le masque
    a ete construit. Par defaut on prend la premiere unite de la doublure ; le cas ou le
    selecteur n'est pas le joueur courant passe `active` explicitement.
    """
    if active is None:
        active = gs["units"][0]
    return bot.select_action_with_state(valid_actions, gs, active)


def _objective(hexes, obj_id="o1") -> dict:
    """Objectif au format que le MOTEUR ecrit : `hexes` = liste de [col, row].

    (`StateManager._load_scenario` : `polygon_to_hex_list` sur les terrains "objective": true.)
    Les doublures en {"col": .., "row": ..} n'existent nulle part en production.
    """
    return {"id": obj_id, "name": obj_id, "hexes": [[int(c), int(r)] for c, r in hexes]}


def _move_gs(unit_hex=(0, 0), enemy_hex=(10, 0), objectives=None, models=None, controllers=None):
    """game_state minimal pour les decisions de deplacement.

    `models` : [(col, row, base_size)] des figurines de l'escouade activee — PAR FIGURINE, la
    seule lecture juste du controle d'objectif (14.02). Defaut : une figurine sur l'ancre.
    `controllers` : contenu de `objective_controllers`, l'etat que le moteur ecrit et que les
    bots RELISENT (ils ne recalculent aucun controle).
    """
    ucol, urow = unit_hex
    ecol, erow = enemy_hex
    models = models if models is not None else [(ucol, urow, 1)]
    models_cache = {
        f"m{i}": {
            "col": int(c), "row": int(r), "level": 0, "HP_CUR": 1,
            "BASE_SHAPE": "round", "BASE_SIZE": int(b),
        }
        for i, (c, r, b) in enumerate(models)
    }
    models_cache["me"] = {
        "col": ecol, "row": erow, "level": 0, "HP_CUR": 1,
        "BASE_SHAPE": "round", "BASE_SIZE": 1,
    }
    gs = {
        "current_player": ACTING,
        "turn": 1,
        "units": [
            {"id": "1", "player": ACTING, "col": ucol, "row": urow},
            {"id": "e", "player": FOE, "col": ecol, "row": erow},
        ],
        "units_cache": {
            "1": {"col": ucol, "row": urow, "player": ACTING, "orientation": 0,
                  "occupied_hexes": [(ucol, urow)]},
            "e": {"col": ecol, "row": erow, "player": FOE, "orientation": 0,
                  "occupied_hexes": [(ecol, erow)]},
        },
        "models_cache": models_cache,
        "squad_models": {"1": [k for k in models_cache if k != "me"], "e": ["me"]},
        "objective_controllers": dict(controllers) if controllers else {},
    }
    if objectives is not None:
        gs["objectives"] = objectives
    return gs, {"id": "1", "player": ACTING, "col": ucol, "row": urow}


def test_select_weighted_deployment_action_errors_and_antirepeat(monkeypatch: pytest.MonkeyPatch) -> None:
    # Le pool de mise en place est nettoye par l'appelant (`BotControlledEnv._open_placement_slots`) :
    # une action hors slots 4-8 ne peut plus arriver ici, et si elle y arrivait la table de poids
    # la refuserait — c'est le meme KeyError que pour un slot sans poids configure.
    with pytest.raises(KeyError, match=r"Missing deployment weight"):
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
    # Mise en place : appelee en direct par le wrapper, avec un pool deja nettoye (slots 4-8).
    assert bot.select_placement_action([4, 5], {"phase": "deployment"}) == 4
    assert _act(bot, [SHOOT, WAIT_ACTION], {"phase": "shoot"}, active={"id": "1", "player": ACTING}) == SHOOT
    # No shoot slot available in shoot phase -> WAIT
    assert _act(bot, [CELL, WAIT_ACTION], {"phase": "shoot"}, active={"id": "1", "player": ACTING}) == WAIT_ACTION


def test_random_bot_destinations_and_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = RandomBot()
    monkeypatch.setattr(eb.random, "choice", lambda seq: seq[-1])
    # Move spatial : le bot choisit une DESTINATION parmi le pool legal (ici aleatoire).
    assert bot.select_movement_destination({}, [(1, 1), (2, 2)]) == (2, 2)


def test_greedy_bot_select_action_and_state(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = GreedyBot(randomness=0.0)
    monkeypatch.setattr(
        eb,
        "_select_weighted_deployment_action",
        lambda **kwargs: 6,
    )
    # La mise en place ne passe plus par `select_action_with_state` : le wrapper appelle
    # directement la politique de pose (cf. tests/unit/ai/test_bot_ingress_reserves.py).
    assert bot.select_placement_action([4, 5, 6], {"phase": "deployment", "episode_number": 1}) == 6

    # Sans slot de tir ouvert -> attendre.
    monkeypatch.setattr(eb, "get_hp_from_cache", lambda uid, gs_: 5)
    gs = _slot_gs("shoot", {"e0": _dmg(rng=1, cc=1)}, ["e0"])
    assert _act(bot, [CELL, WAIT_ACTION], gs) == WAIT_ACTION
    assert _act(bot, [SHOOT, WAIT_ACTION], gs) == SHOOT


def test_greedy_bot_shoots_and_charges_the_most_wounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Greedy : tir ET charge visent l'escouade la plus entamee, sur le slot du mapping."""
    bot = GreedyBot(randomness=0.0)
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    monkeypatch.setattr(eb, "get_hp_from_cache", lambda uid, gs_: 5 if uid == "e_full" else 2)

    gs = _slot_gs(
        "shoot", {"e_full": _dmg(rng=1, cc=1), "e_hurt": _dmg(rng=1, cc=1)}, ["e_full", "e_hurt"]
    )
    assert _act(bot, [SHOOT, SHOOT2, WAIT_ACTION], gs) == SHOOT2

    gs_charge = _slot_gs(
        "charge", {"e_full": _dmg(rng=1, cc=1), "e_hurt": _dmg(rng=1, cc=1)}, ["e_full", "e_hurt"]
    )
    assert _act(bot, [CHARGE, CHARGE_SLOT1, WAIT_ACTION], gs_charge) == CHARGE_SLOT1


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
    gs, unit = _move_gs(unit_hex=(5, 0), enemy_hex=(10, 0))
    # (2,0) plus loin de l'ennemi que (8,0) ET que la position courante (5,0) -> repli.
    # Sans objectif sur la table, seul le terme ennemi joue.
    assert bot.select_movement_destination(unit, [(2, 0), (8, 0)], gs) == (2, 0)
    # Rester sur place est une option scoree : aucune destination meilleure -> WAIT (l'ancre).
    assert bot.select_movement_destination(unit, [(6, 0), (8, 0)], gs) == (5, 0)


def test_defensive_bot_action_shoot_phase(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le defensif tire sur la PLUS MENACANTE — le meme critere qu'en melee, pas le 1er slot."""
    bot = DefensiveBot(randomness=0.0)
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    gs = _slot_gs(
        "shoot",
        {"e_weak": _dmg(rng=1, cc=1), "e_strong": _dmg(rng=7, cc=1)},
        ["e_weak", "e_strong"],
    )
    assert _act(bot, [SHOOT, SHOOT2, WAIT_ACTION], gs) == SHOOT2
    # Aucun slot de tir ouvert -> tenir sa position.
    assert _act(bot, [CELL, WAIT_ACTION], gs) == WAIT_ACTION


def test_tactical_bot_phase_action_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    """TacticalBot passe desormais par select_action_with_state : ses heuristiques de phase sont
    ATTEIGNABLES (le wrapper l'appelait jusqu'ici sans phase ni etat)."""
    bot = TacticalBot(randomness=0.0)
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    monkeypatch.setattr(eb, "get_hp_from_cache", lambda uid, gs_: 5)
    gs = _slot_gs("shoot", {"e0": _dmg(rng=1, cc=1)}, ["e0"])
    assert _act(bot, [], gs) == WAIT_ACTION
    assert _act(bot, [SHOOT, WAIT_ACTION], gs) == SHOOT
    # Sans cible eligible, il se declare « a vide » plutot que d'attendre (12.04).
    assert _act(bot, [FIGHT_EMPTY, WAIT_ACTION], {**gs, "phase": "fight"}) == FIGHT_EMPTY


def test_tactical_bot_shoot_scoring_prefers_killable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tuable ce tour > peu de PV > menace, applique au SLOT (ici le slot 1, non minimal)."""
    bot = TacticalBot(randomness=0.0)
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    monkeypatch.setattr(eb, "get_hp_from_cache", lambda uid, gs_: 6 if uid == "e_tanky" else 4)
    gs = _slot_gs(
        "shoot",
        {"e_tanky": _dmg(rng=9, cc=1), "e_killable": _dmg(rng=2, cc=1)},
        ["e_tanky", "e_killable"],
    )
    # L'attaquant fait 4 de degats attendus au tir : e_killable (4 PV) est tuable ce tour,
    # e_tanky (6 PV) ne l'est pas malgre sa menace tres superieure.
    attacker = {**gs["units"][0], **_dmg(rng=4, cc=1)}
    assert _act(bot, [SHOOT, SHOOT2, WAIT_ACTION], gs, active=attacker) == SHOOT2


def test_tactical_bot_find_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = TacticalBot(randomness=0.0)
    game_state = {
        "current_player": ACTING,
        "units": [
            {"id": "u0", "player": ACTING, "col": 1, "row": 1, **_dmg(rng=2, cc=1)},
            {"id": "e1", "player": FOE, "col": 4, "row": 1, **_dmg(rng=1, cc=3)},
            {"id": "e2", "player": FOE, "col": 9, "row": 1, **_dmg(rng=3, cc=1)},
        ],
        # `units_cache` etait VIDE ici : `is_unit_alive` etant double a True, l'etat construit
        # etait une desynchronisation `units` / `units_cache` que la production ne produit pas,
        # et la geometrie retombait sur le col/row de la DATASHEET. Le cache est desormais le
        # miroir de `units`, ce qu'il est dans le moteur.
        "units_cache": {
            "u0": {"col": 1, "row": 1, "player": ACTING, "occupied_hexes": {(1, 1)}},
            "e1": {"col": 4, "row": 1, "player": FOE, "occupied_hexes": {(4, 1)}},
            "e2": {"col": 9, "row": 1, "player": FOE, "occupied_hexes": {(9, 1)}},
        },
    }
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: uid in {"u0", "e1", "e2"})
    monkeypatch.setattr(eb, "calculate_hex_distance", lambda c1, r1, c2, r2: abs(c1 - c2) + abs(r1 - r2))
    active = game_state["units"][0]
    assert require_present(bot._find_nearest_enemy(active, game_state), "nearest_enemy")["id"] == "e1"


def test_tactical_bot_movement_position_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = TacticalBot(randomness=0.0)
    game_state = {
        "units": [
            {"id": "u0", "player": ACTING},
            {"id": "e1", "player": FOE, "col": 5, "row": 5, **_dmg(rng=1, cc=3)},
            {"id": "e2", "player": FOE, "col": 10, "row": 10, **_dmg(rng=3, cc=1)},
            {"id": "cible", "player": FOE, "col": 8, "row": 8, **_dmg(rng=1, cc=1)},
        ],
        # Cache VIDE auparavant : cf. `test_tactical_bot_find_helpers`. Meme correction.
        "units_cache": {
            "u0": {"col": 1, "row": 1, "player": ACTING, "occupied_hexes": {(1, 1)}},
            "e1": {"col": 5, "row": 5, "player": FOE, "occupied_hexes": {(5, 5)}},
            "e2": {"col": 10, "row": 10, "player": FOE, "occupied_hexes": {(10, 10)}},
            "cible": {"col": 8, "row": 8, "player": FOE, "occupied_hexes": {(8, 8)}},
        },
        # `inches_to_subhex` EST la résolution du moteur (`spatial_relations.geometry_is_hex`) : une
        # doublure qui l'omet hérite de celle du board ambiant, donc d'une géométrie multi-hex qui
        # exigerait un socle sur chaque unité. Board legacy ici (ez=1) → x1.
        "inches_to_subhex": 1,
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
    unit = {"id": "u0", "player": ACTING, "RNG_WEAPONS": [{"RNG": 6}]}
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: uid in {"e1", "e2"})
    monkeypatch.setattr(eb, "calculate_hex_distance", lambda c1, r1, c2, r2: abs(c1 - c2) + abs(r1 - r2))
    monkeypatch.setattr("engine.utils.weapon_helpers.get_max_ranged_range", lambda u: 6)

    safest = bot._find_safest_position(unit, [(1, 1), (2, 2), (8, 8)], game_state)
    assert safest == (1, 1) or safest == (2, 2) or safest == (8, 8)

    # La cible est une unite du jeu, comme celle que `_find_nearest_enemy` rend au vrai appelant —
    # plus un dict de coordonnees nues, que le moteur ne fabrique nulle part.
    best_off = bot._find_best_offensive_position(
        unit, [(1, 1), (4, 4), (7, 7)], game_state["units"][3], game_state
    )
    assert best_off in [(4, 4), (7, 7)]


def test_control_bot_movement_holds_and_seeks_objective(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_move_geometry(monkeypatch)
    bot = ControlBot(randomness=0.0)

    # Sur l'objectif -> tient sa position (renvoie l'ancre, que le wrapper traduit en WAIT).
    # « Tenir » est desormais une regle de SCORE (bonus de tenue), plus une clause exclusive.
    gs_on, unit_on = _move_gs(
        unit_hex=(5, 5), enemy_hex=(20, 20), objectives=[_objective([(5, 5)])]
    )
    assert bot.select_movement_destination(unit_on, [(6, 6), (4, 4)], gs_on) == (5, 5)

    # Hors objectif -> se rapproche du centre de l'objectif (10,10)
    gs_off, unit_off = _move_gs(
        unit_hex=(0, 0), enemy_hex=(20, 20), objectives=[_objective([(10, 10)])]
    )
    assert bot.select_movement_destination(unit_off, [(2, 2), (8, 8)], gs_off) == (8, 8)


def test_control_bot_non_move_phases(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = ControlBot(randomness=0.0)
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    # Les ennemis sont en (5,1) et (6,1) ; l'objectif en (6,1) : le slot 1 le conteste.
    gs = _slot_gs(
        "shoot",
        {"e_far": _dmg(rng=9, cc=1), "e_on_obj": _dmg(rng=1, cc=1)},
        ["e_far", "e_on_obj"],
        objectives=[_objective([(6, 1)])],
    )
    assert _act(bot, [SHOOT, SHOOT2, WAIT_ACTION], gs) == SHOOT2
    # Charge phase, unite SUR un objectif -> elle tient sa position.
    charge_gs = _slot_gs(
        "charge",
        {"e_far": _dmg(rng=9, cc=1)},
        ["e_far"],
        objectives=[_objective([(1, 1)])],
    )
    assert _act(bot, [CHARGE, WAIT_ACTION], charge_gs) == WAIT_ACTION


def test_adaptive_bot_movement_posture(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_move_geometry(monkeypatch)
    bot = AdaptiveBot(randomness=0.0)

    # Turn 1 (early) -> rush objectif : se rapproche du centre (10,10)
    gs_early, unit_early = _move_gs(
        unit_hex=(0, 0), enemy_hex=(20, 0), objectives=[_objective([(10, 10)])]
    )
    gs_early["turn"] = 1
    assert bot.select_movement_destination(unit_early, [(2, 2), (8, 8)], gs_early) == (8, 8)

    # Turn 3 losing (aucun objectif controle) -> agressif : pousse vers l'ennemi (10,0)
    gs_losing, unit_losing = _move_gs(
        unit_hex=(0, 0), enemy_hex=(10, 0), objectives=[_objective([(99, 99)])]
    )
    gs_losing["turn"] = 3
    assert bot.select_movement_destination(unit_losing, [(2, 0), (8, 0)], gs_losing) == (8, 0)


def test_adaptive_bot_charge_posture(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = AdaptiveBot(randomness=0.0)
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: True)
    monkeypatch.setattr(eb, "get_hp_from_cache", lambda uid, gs_: 5)
    base_gs = _slot_gs(
        "charge",
        {"e0": _dmg(rng=1, cc=1)},
        ["e0"],
        objectives=[_objective([(50, 50)])],
    )
    base_gs["turn"] = 3
    # Aucun objectif tenu de part et d'autre -> posture « losing » -> charge
    assert _act(bot, [CHARGE, WAIT_ACTION], base_gs) == CHARGE


# --- VERROUS de la refonte du panel : objectifs, tenue, lecture par-figurine -------------------
#
# Contexte mesure : la victoire se decide aux VP d'objectifs, et le win-rate de l'agent contre
# chaque bot suivait exactement le rapport de ce bot aux objectifs. Chaque test ci-dessous
# CONSTRUIT la situation qu'il observe et est ROUGE sur le comportement d'avant la refonte.


def test_squad_on_objective_counts_a_model_whose_footprint_covers_the_zone() -> None:
    """L'ANCRE d'escouade est ailleurs, une FIGURINE couvre la zone : l'escouade y est.

    C'est le defaut exact verrouille : l'ancien `_is_on_objective` comparait
    `get_unit_coordinates(unit)` (l'ancre, ici (0,0)) aux hexes d'objectif et rendait False.
    La figurine est en (14,10) avec un socle rond de 3 : son empreinte contient (15,10).
    """
    gs, unit = _move_gs(
        unit_hex=(0, 0),
        enemy_hex=(40, 40),
        objectives=[_objective([(15, 10)])],
        models=[(14, 10, 3)],
    )
    # La zone ne contient NI l'ancre, NI le centre de la figurine : seule l'empreinte la touche.
    assert (0, 0) != (15, 10) and (14, 10) != (15, 10)
    assert _squad_on_objective(unit, gs) is True

    # Meme figurine, socle de 1 : plus d'empreinte etendue -> plus de presence.
    gs_small, unit_small = _move_gs(
        unit_hex=(0, 0),
        enemy_hex=(40, 40),
        objectives=[_objective([(15, 10)])],
        models=[(14, 10, 1)],
    )
    assert _squad_on_objective(unit_small, gs_small) is False


def test_objectives_controlled_reads_engine_state_not_a_bot_recount() -> None:
    """Le comptage relit `objective_controllers` (14.02), il ne recompte pas des ancres amies.

    Rouge sur l'ancien code : une escouade amie POSEE sur la zone mais qui n'en a PAS le
    controle (OC adverse superieur) y comptait comme un objectif tenu.
    """
    gs, _unit = _move_gs(
        unit_hex=(5, 5),
        enemy_hex=(5, 6),
        objectives=[_objective([(5, 5)]), _objective([(9, 9)], obj_id="o2")],
        controllers={"o1": FOE, "o2": ACTING},
    )
    assert _count_objectives_controlled(gs, ACTING) == 1
    assert _count_objectives_controlled(gs, FOE) == 1


def test_defensive_bot_retreats_toward_its_objective_not_off_the_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sous pression, le defensif recule VERS son objectif, pas hors de la table.

    Ennemi en (10,0), objectif en (0,0), l'escouade en (5,0). Le repli pur
    (`_dest_away_from_enemies`, ancienne geometrie) choisissait (20,0) — l'hex le plus eloigne
    de l'ennemi, a l'oppose de la zone. Le score pondere (w_obj 0.7 / w_enn -0.5) prend (1,0).
    """
    _patch_move_geometry(monkeypatch)
    bot = DefensiveBot(randomness=0.0)
    gs, unit = _move_gs(unit_hex=(5, 0), enemy_hex=(10, 0), objectives=[_objective([(0, 0)])])

    # (20,0) est bien la destination du repli pur : c'est la plus eloignee de l'ennemi.
    assert max([(1, 0), (20, 0)], key=lambda d: abs(d[0] - 10)) == (20, 0)
    assert bot.select_movement_destination(unit, [(1, 0), (20, 0)], gs) == (1, 0)


def test_adaptive_bot_winning_holds_the_objective_instead_of_fleeing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Posture « winning » = TENIR. Elle declenchait `_dest_away_from_enemies` : le bot fuyait
    l'objectif qui le faisait gagner — d'autant plus souvent que le comptage devenait juste.

    L'escouade tient o1 (controle par ACTING dans l'etat moteur), l'ennemi est adjacent.
    """
    _patch_move_geometry(monkeypatch)
    bot = AdaptiveBot(randomness=0.0)
    gs, unit = _move_gs(
        unit_hex=(5, 5),
        enemy_hex=(7, 5),
        objectives=[_objective([(5, 5)])],
        controllers={"o1": ACTING},
    )
    gs["turn"] = 3
    assert bot._evaluate_posture(gs, ACTING, 3) == "winning"
    # (1,5) est la fuite (le plus loin de l'ennemi) ; (5,5) est la position tenue.
    assert bot.select_movement_destination(unit, [(1, 5), (6, 5)], gs) == (5, 5)


# --- V11 §0.3 : portage CC_DMG/RNG_DMG vers le systeme multi-armes -----------------------------
#
# `CC_DMG` / `RNG_DMG` ont ete SUPPRIMES par le refactor multi-armes (cf. reward_mapper :
# « Replaces old RNG_DMG/CC_DMG fields »). Aucun fichier d'unite ne les definit plus, mais 2 bots
# les lisaient encore via require_key -> ConfigurationError.
#
# Le critere de menace etait porte par le helper `_best_target_slot_by_threat`, dont l'unique
# appelant etait `DefensiveSmartBot` — bot depuis SUPPRIME. Le critere, lui, reste vivant chez
# `DefensiveBot`, qui l'exerce ici sur des unites au contrat ACTUEL (sans les champs supprimes).

def test_threat_focus_fire_without_legacy_damage_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Menace lue sur RNG_WEAPONS/CC_WEAPONS (les champs RNG_DMG/CC_DMG ont ete supprimes)."""
    gs = _slot_gs(
        "shoot",
        {"e_weak": _dmg(rng=1, cc=1), "e_strong": _dmg(rng=1, cc=6)},
        ["e_weak", "e_strong"],
    )
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    monkeypatch.setattr(eb, "get_hp_from_cache", lambda uid, gs_: 5)

    bot = DefensiveBot(randomness=0.0)
    # slot 1 = e_strong, la plus menacante (6 en melee vs 1 en tir pour e_weak).
    assert _act(bot, [SHOOT, SHOOT2, WAIT_ACTION], gs) == SHOOT2


def test_tactical_bot_charges_only_when_melee_beats_shooting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le SI de la charge porte sur l'ATTAQUANT (melee attendue > tir attendu) ; le QUI sur la
    cible (l'escouade de tir la plus dangereuse, `_score_silence_the_guns`)."""
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    bot = TacticalBot(randomness=0.0)
    gs = _slot_gs(
        "charge",
        {"e_melee": _dmg(rng=1, cc=9), "e_gunline": _dmg(rng=5, cc=1)},
        ["e_melee", "e_gunline"],
    )
    melee_attacker = {**gs["units"][0], **_dmg(rng=1, cc=4)}
    shooty_attacker = {**gs["units"][0], **_dmg(rng=6, cc=1)}

    # Attaquant de melee : il charge, et vise le canon (slot 1), pas la brute de melee.
    assert _act(bot, [CHARGE, CHARGE_SLOT1, WAIT_ACTION], gs, active=melee_attacker) == CHARGE_SLOT1
    # Attaquant de tir : charger n'est pas avantageux.
    assert _act(bot, [CHARGE, CHARGE_SLOT1, WAIT_ACTION], gs, active=shooty_attacker) == WAIT_ACTION


# --- Charge du defensif + cible frappee par CRITERE (jamais par ordre de tri) ------------------
#
# 1. `DefensiveBot` ne chargeait JAMAIS : sa branche terminale etait « si l'attente est
#    disponible, attendre », or le masque de la phase de charge arme WAIT INCONDITIONNELLEMENT.
# 2. En combat, `DefensiveBot` et `GreedyBot` tombaient sur `valid_actions[0]` — la liste triee
#    des bits du masque — donc frappaient le slot ennemi d'indice le plus BAS, par accident.
# Les cas ci-dessous placent volontairement la cible attendue sur un slot NON minimal : ils sont
# rouges sur l'ancien comportement.

CHARGE_SLOT1 = mi.CHARGE_SLOT_BASE + 1
FIGHT_SLOT1 = mi.FIGHT_SLOT_BASE + 1
K_ENEMY_SLOTS = len(mi.SHOOT_SLOTS)


def _cache_entry(unit: dict) -> dict:
    """Entree units_cache FIDELE au moteur : etat spatial/vital SEULEMENT.

    `build_units_cache` (engine/phase_handlers/shared_utils.py) ne recopie jamais RNG_WEAPONS /
    CC_WEAPONS dans le cache. Une doublure qui clonait l'unite entiere rendait les bots de menace
    verts en test et explosifs en training (« Required key 'RNG_WEAPONS' is missing »).
    """
    return {
        "col": unit["col"],
        "row": unit["row"],
        "player": unit["player"],
        "orientation": 0,
        "occupied_hexes": {(unit["col"], unit["row"])},
    }


def _model_entry(unit: dict) -> dict:
    """Figurine de `models_cache` : position PAR FIGURINE + socle, la source du controle (14.02)."""
    return {
        "col": unit["col"], "row": unit["row"], "level": 0, "HP_CUR": 1,
        "BASE_SHAPE": "round", "BASE_SIZE": 1,
    }


def _slot_gs(phase: str, enemies: dict, order: list, current_player=None, objectives=None) -> dict:
    """game_state minimal pour les selections par slot ennemi.

    `enemies` : {squad_id: champs d'armes} ; `order` : ids ranges PAR SLOT (mapping fige, donc
    deterministe : `get_enemy_slot_mapping` relit la cle deja presente sans reattribuer).
    `current_player` peut DIFFERER du joueur agissant : c'est le cas en phase de combat, ou la
    selection 12.04 alterne entre les camps (`fight_selector`).
    """
    if current_player is None:
        current_player = ACTING
    ours = {"id": "1", "player": ACTING, "col": 1, "row": 1, **_dmg(rng=2, cc=2)}
    units = [ours]
    units_cache = {"1": _cache_entry(ours)}
    models_cache = {"m_1": _model_entry(ours)}
    squad_models = {"1": ["m_1"]}
    for i, (eid, fields) in enumerate(enemies.items()):
        enemy = {"id": eid, "player": FOE, "col": 5 + i, "row": 1, **fields}
        units.append(enemy)
        units_cache[eid] = _cache_entry(enemy)
        models_cache[f"m_{eid}"] = _model_entry(enemy)
        squad_models[eid] = [f"m_{eid}"]
    gs = {**turn_state_invariants(),
        "phase": phase,
        # Etat que le moteur ecrit a chaque frontiere de phase (14.02) et que les bots RELISENT.
        "objective_controllers": {},
        "current_player": current_player,
        "turn": 1,
        "units": units,
        "units_cache": units_cache,
        "models_cache": models_cache,
        "squad_models": squad_models,
        "inches_to_subhex": 1,
        f"enemy_slot_mapping_p{ACTING}": list(order) + [None] * (K_ENEMY_SLOTS - len(order)),
    }
    if objectives is not None:
        gs["objectives"] = objectives
    return gs


def test_defensive_bot_counter_charges_melee_threat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Doctrine : le defensif charge l'escouade de MELEE la plus dangereuse plutot que de la
    subir (elle deviendrait Fights First, 12.04) ; il ignore les escouades de tir."""
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    bot = DefensiveBot(randomness=0.0)

    # Slot 0 = tireur (melee <= tir, ecarte) ; slot 1 = brute de melee -> charge du slot 1.
    gs = _slot_gs(
        "charge",
        {"e_shooty": _dmg(rng=6, cc=1), "e_melee": _dmg(rng=1, cc=5)},
        ["e_shooty", "e_melee"],
    )
    assert _act(bot, [CHARGE, CHARGE_SLOT1, WAIT_ACTION], gs) == CHARGE_SLOT1

    # Deux brutes : la plus dangereuse au corps a corps l'emporte, meme sur le slot le plus haut.
    gs2 = _slot_gs(
        "charge",
        {"e_small": _dmg(rng=1, cc=2), "e_big": _dmg(rng=1, cc=9)},
        ["e_small", "e_big"],
    )
    assert _act(bot, [CHARGE, CHARGE_SLOT1, WAIT_ACTION], gs2) == CHARGE_SLOT1

    # Uniquement des tireurs : le defensif tient sa ligne.
    gs3 = _slot_gs("charge", {"e_shooty": _dmg(rng=6, cc=1)}, ["e_shooty"])
    assert _act(bot, [CHARGE, WAIT_ACTION], gs3) == WAIT_ACTION


def test_defensive_bot_fights_highest_threat_not_lowest_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Combat : cible = la plus menacante, pas le slot d'indice le plus bas."""
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    bot = DefensiveBot(randomness=0.0)

    gs = _slot_gs(
        "fight",
        {"e_weak": _dmg(rng=1, cc=1), "e_strong": _dmg(rng=2, cc=8)},
        ["e_weak", "e_strong"],
    )
    assert _act(bot, [FIGHT_SLOT0, FIGHT_SLOT1], gs) == FIGHT_SLOT1

    # Aucun slot ouvert -> combat a vide (12.04/12.06), jamais une cible arbitraire.
    assert _act(bot, [FIGHT_EMPTY], gs) == FIGHT_EMPTY


def test_greedy_bot_fights_lowest_hp_not_lowest_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Combat : cible = la plus entamee (focus fire), pas le slot d'indice le plus bas."""
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    monkeypatch.setattr(eb, "get_hp_from_cache", lambda uid, gs_: 5 if uid == "e_full" else 2)
    bot = GreedyBot(randomness=0.0)

    gs = _slot_gs(
        "fight",
        {"e_full": _dmg(rng=1, cc=1), "e_hurt": _dmg(rng=1, cc=1)},
        ["e_full", "e_hurt"],
    )
    assert _act(bot, [FIGHT_SLOT0, FIGHT_SLOT1], gs) == FIGHT_SLOT1
    assert _act(bot, [FIGHT_EMPTY], gs) == FIGHT_EMPTY


def test_fight_target_follows_the_activated_squad_not_current_player(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SELECTEUR != JOUEUR COURANT (12.04).

    Le masque derive son joueur de l'escouade activee
    (`action_decoder` : `units_cache[eligible_units[0]["id"]]["player"]`), et la selection 12.04
    alterne entre les camps (`fight_handlers._fight_v11_register_selection` : `3 - selector`).
    Un bot qui deduirait le joueur de `current_player` lirait le mapping de SES PROPRES escouades.
    """
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    monkeypatch.setattr(eb, "get_hp_from_cache", lambda uid, gs_: 5 if uid == "e_weak" else 2)

    # L'escouade activee appartient a ACTING, mais c'est FOE qui est `current_player`.
    gs = _slot_gs(
        "fight",
        {"e_weak": _dmg(rng=1, cc=1), "e_strong": _dmg(rng=2, cc=8)},
        ["e_weak", "e_strong"],
        current_player=FOE,
    )
    assert gs["current_player"] != gs["units"][0]["player"]

    # Defensif -> la plus menacante ; greedy -> la plus entamee. Ici c'est e_strong (slot 1).
    assert _act(DefensiveBot(randomness=0.0), [FIGHT_SLOT0, FIGHT_SLOT1], gs) == FIGHT_SLOT1
    assert _act(GreedyBot(randomness=0.0), [FIGHT_SLOT0, FIGHT_SLOT1], gs) == FIGHT_SLOT1


def test_slot_mapping_divergence_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un slot ouvert par le masque sans escouade en face est une erreur, pas un repli."""
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    gs = _slot_gs("fight", {"e_weak": _dmg(rng=1, cc=1)}, ["e_weak"])
    with pytest.raises(RuntimeError, match=r"sans escouade ennemie"):
        _act(DefensiveBot(randomness=0.0), [FIGHT_SLOT0, FIGHT_SLOT1], gs)


# --- Tir des smart bots : le slot vise est celui du MAPPING, pas un index de pool de tir -------
#
# Defaut corrige : le focus-fire cherchait le meilleur index dans
# `active_unit["valid_target_pool"]` et s'en servait comme index de SLOT, alors que le masque
# indexe `get_enemy_slot_mapping`. Les cas ci-dessous donnent au pool l'ordre INVERSE du mapping :
# l'ancien code vise le slot 0 (donc la mauvaise escouade), le nouveau le slot 1.

def test_smart_bots_shoot_the_slot_designated_by_their_criterion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    monkeypatch.setattr(eb, "get_hp_from_cache", lambda uid, gs_: 5 if uid == "e_full" else 2)

    # Menace (DefensiveBot) : mapping [faible, forte] -> slot 1 ; pool inverse [forte, faible].
    gs_threat = _slot_gs(
        "shoot",
        {"e_weak": _dmg(rng=1, cc=1), "e_strong": _dmg(rng=2, cc=8)},
        ["e_weak", "e_strong"],
    )
    gs_threat["units"][0]["valid_target_pool"] = ["e_strong", "e_weak"]
    assert (
        _act(DefensiveBot(randomness=0.0), [SHOOT, SHOOT2, WAIT_ACTION], gs_threat)
        == SHOOT2
    )

    # HP (GreedyBot, AdaptiveBot) : mapping [pleine, entamee] -> slot 1 ; pool inverse.
    gs_hp = _slot_gs(
        "shoot",
        {"e_full": _dmg(rng=1, cc=1), "e_hurt": _dmg(rng=1, cc=1)},
        ["e_full", "e_hurt"],
    )
    gs_hp["units"][0]["valid_target_pool"] = ["e_hurt", "e_full"]
    assert (
        _act(GreedyBot(randomness=0.0), [SHOOT, SHOOT2, WAIT_ACTION], gs_hp)
        == SHOOT2
    )
    assert (
        _act(AdaptiveBot(randomness=0.0), [SHOOT, SHOOT2, WAIT_ACTION], gs_hp)
        == SHOOT2
    )


# --- ValueTradeBot : le DEPARTAGE (VALUE restante) joue enfin dans le panel -------------------
#
# `determine_winner_with_method` tranche les egalites de VP sur la VALUE totale restante
# ("value_tiebreaker"). Aucun bot ne jouait ce critere. Les cas ci-dessous CONSTRUISENT la
# situation qu'ils observent et placent la cible attendue sur un slot NON minimal.


def _value_enemy(value: int, rng: float = 1.0, cc: float = 1.0) -> dict:
    """Champs de datasheet d'une escouade ennemie : armes + VALUE (points d'escouade)."""
    return {**_dmg(rng=rng, cc=cc), "VALUE": value}


def _value_move_gs(
    *,
    unit_hex,
    enemy_hex,
    value,
    ally_value,
    rng,
    cc,
    models_start=1,
    models_alive=1,
    hp_cur=None,
    hp_max=1,
    objectives=None,
):
    """Etat de deplacement pour ValueTradeBot : VALUE/armes de l'escouade activee + UNE escouade
    amie (« haute VALUE » se mesure a la moyenne des AUTRES escouades vivantes).

    `squad_cache` est FOURNI parce que « entamee » se lit par la regle 08.03
    (`is_unit_at_half_strength`) : sur une escouade MULTI-FIGURINES elle compte les figurines
    vivantes (`models_start`/`models_alive`) et ne regarde pas les PV ; sur une escouade
    mono-figurine elle compare `units_cache["HP_CUR"]` (`hp_cur`) a `unit["HP_MAX"]` (`hp_max`).
    Les deux voies sont donc parametrables, et c'est le MOTEUR qui tranche dans les deux cas.
    """
    gs, unit = _move_gs(unit_hex=unit_hex, enemy_hex=enemy_hex, objectives=objectives)
    stats = {"HP_MAX": hp_max, "VALUE": value, **_dmg(rng=rng, cc=cc)}
    unit.update(stats)
    gs["units"][0].update(stats)
    gs["units_cache"]["1"]["HP_CUR"] = hp_max if hp_cur is None else hp_cur
    acol, arow = unit_hex
    gs["units"].append({**unit_invariants(),
        "id": "a", "player": ACTING, "col": acol, "row": arow,
        "HP_MAX": hp_max, "VALUE": ally_value, **_dmg(rng=1, cc=1),
    })
    gs["units_cache"]["a"] = {
        "col": acol, "row": arow, "player": ACTING, "orientation": 0,
        "occupied_hexes": [(acol, arow)], "HP_CUR": hp_max,
    }
    gs["squad_cache"] = {
        "1": {"model_count_at_start": models_start, "model_count": models_alive},
        "a": {"model_count_at_start": models_start, "model_count": models_start},
    }
    return gs, unit


def test_value_trade_and_greedy_diverge_on_expensive_versus_wounded_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CAS DISCRIMINANT : cible chere et couteuse a tuer VS cible entamee et bon marche.

    e_cheap : 20 points sur 2 PV restants -> 10.0 points par degat.
    e_valuable : 120 points sur 10 PV restants -> 12.0 points par degat.
    GreedyBot acheve la plus entamee (slot 0) ; ValueTradeBot prend la plus rentable au
    departage (slot 1). Les deux bots doivent DIVERGER, et aucun des deux ne peut tomber juste
    par l'ordre des slots (ils choisissent des slots opposes).
    """
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    monkeypatch.setattr(eb, "get_hp_from_cache", lambda uid, gs_: 2 if uid == "e_cheap" else 10)

    gs = _slot_gs(
        "shoot",
        {"e_cheap": _value_enemy(20), "e_valuable": _value_enemy(120)},
        ["e_cheap", "e_valuable"],
    )
    assert _act(GreedyBot(randomness=0.0), [SHOOT, SHOOT2, WAIT_ACTION], gs) == SHOOT
    assert _act(ValueTradeBot(randomness=0.0), [SHOOT, SHOOT2, WAIT_ACTION], gs) == SHOOT2

    # Meme critere en melee : le monstre (slot 1) plutot que les gretchins acheves (slot 0).
    gs_fight = _slot_gs(
        "fight",
        {"e_cheap": _value_enemy(20), "e_valuable": _value_enemy(120)},
        ["e_cheap", "e_valuable"],
    )
    assert _act(ValueTradeBot(randomness=0.0), [FIGHT_SLOT0, FIGHT_SLOT1], gs_fight) == FIGHT_SLOT1
    # Aucun slot ouvert -> combat a vide (12.04/12.06), jamais une cible arbitraire.
    assert _act(ValueTradeBot(randomness=0.0), [FIGHT_EMPTY], gs_fight) == FIGHT_EMPTY


def test_value_trade_bot_charges_only_when_melee_is_its_own_best_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L'engagement suit SON PROPRE profil, pas une portee fixee : melee > tir -> contact.

    Le QUI reste le critere de VALUE par degat : e_valuable (120 pts / 10 PV = 12.0) devant
    e_cheap (20 pts / 2 PV = 10.0), donc le slot 1.
    """
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    monkeypatch.setattr(eb, "get_hp_from_cache", lambda uid, gs_: 2 if uid == "e_cheap" else 10)
    bot = ValueTradeBot(randomness=0.0)

    gs = _slot_gs(
        "charge",
        {"e_cheap": _value_enemy(20), "e_valuable": _value_enemy(120)},
        ["e_cheap", "e_valuable"],
    )
    melee_attacker = {**gs["units"][0], **_dmg(rng=1, cc=4)}
    shooty_attacker = {**gs["units"][0], **_dmg(rng=6, cc=1)}

    assert _act(bot, [CHARGE, CHARGE_SLOT1, WAIT_ACTION], gs, active=melee_attacker) == CHARGE_SLOT1
    # Unite de tir : elle tient sa portee au lieu d'aller brader ses degats au contact.
    assert _act(bot, [CHARGE, CHARGE_SLOT1, WAIT_ACTION], gs, active=shooty_attacker) == WAIT_ACTION


def test_value_trade_bot_postures_follow_profile_and_wounded_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Postures : withdraw (piece chere entamee) PRIME sur engage (profil melee) et standoff."""
    _patch_move_geometry(monkeypatch)
    bot = ValueTradeBot(randomness=0.0)

    # Brute de melee saine (mono-figurine, PV pleins) -> contact.
    gs_engage, unit_engage = _value_move_gs(
        unit_hex=(5, 0), enemy_hex=(10, 0), hp_cur=10, hp_max=10,
        value=120, ally_value=20, rng=1, cc=5,
    )
    assert bot._posture(unit_engage, gs_engage) == "engage"

    # Meme unite de melee, meme VALUE, mais entamee (2/10 PV) et plus chere que son armee.
    gs_wd, unit_wd = _value_move_gs(
        unit_hex=(5, 0), enemy_hex=(10, 0), hp_cur=2, hp_max=10,
        value=120, ally_value=20, rng=1, cc=5,
    )
    assert bot._posture(unit_wd, gs_wd) == "withdraw"

    # Entamee mais BON MARCHE (l'alliee vaut plus) : rien a preserver, le profil reprend la main.
    gs_cheap, unit_cheap = _value_move_gs(
        unit_hex=(5, 0), enemy_hex=(10, 0), hp_cur=2, hp_max=10,
        value=20, ally_value=120, rng=1, cc=5,
    )
    assert bot._posture(unit_cheap, gs_cheap) == "engage"

    # Unite de tir saine -> elle tient sa portee.
    gs_standoff, unit_standoff = _value_move_gs(
        unit_hex=(5, 0), enemy_hex=(10, 0), hp_cur=10, hp_max=10,
        value=120, ally_value=20, rng=5, cc=1,
    )
    assert bot._posture(unit_standoff, gs_standoff) == "standoff"


def test_value_trade_bot_withdraw_triggers_on_a_multi_model_squad(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """08.03 sur une ESCOUADE, le cas reel : « entamee » se compte en FIGURINES, pas en PV.

    ROUGE sur le seuil naif `units_cache["HP_CUR"] < unit["HP_MAX"] * 0.5` : le HP_CUR d'escouade
    est la SOMME des PV des figurines vivantes et HP_MAX le PV d'UNE figurine. Dix Boyz a 1 PV
    reduits a 3 survivants donnent `3 < 0.5` -> faux, comme `10 < 0.5` a pleine escouade : la
    posture n'existait sur AUCUN roster multi-figurines, c'est-a-dire sur aucun roster reel.
    """
    _patch_move_geometry(monkeypatch)
    bot = ValueTradeBot(randomness=0.0)

    # 10 figurines a 1 PV, 3 vivantes : 3 <= 10/2 -> entamee (08.03). HP_CUR = 3, HP_MAX = 1.
    gs_wd, unit_wd = _value_move_gs(
        unit_hex=(5, 0), enemy_hex=(10, 0), models_start=10, models_alive=3,
        hp_cur=3, hp_max=1, value=120, ally_value=20, rng=1, cc=5,
    )
    assert gs_wd["units_cache"]["1"]["HP_CUR"] > gs_wd["units"][0]["HP_MAX"] * 0.5
    assert bot._posture(unit_wd, gs_wd) == "withdraw"
    assert bot.select_movement_destination(unit_wd, [(2, 0), (8, 0)], gs_wd) == (2, 0)

    # 6 survivantes sur 10 : au-dessus de la moitie -> pas entamee, le profil de melee prime.
    gs_ok, unit_ok = _value_move_gs(
        unit_hex=(5, 0), enemy_hex=(10, 0), models_start=10, models_alive=6,
        hp_cur=6, hp_max=1, value=120, ally_value=20, rng=1, cc=5,
    )
    assert bot._posture(unit_ok, gs_ok) == "engage"
    assert bot.select_movement_destination(unit_ok, [(2, 0), (8, 0)], gs_ok) == (8, 0)


def test_value_trade_bot_withdraws_the_wounded_expensive_squad(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La posture est BRANCHEE sur les poids : la brute de melee entamee et chere RECULE.

    Meme unite, meme profil de melee, meme ennemi en (10,0) : saine elle prend (8,0) (contact),
    entamee elle prend (2,0). Sans la posture « withdraw », les deux cas rendraient (8,0).
    """
    _patch_move_geometry(monkeypatch)
    bot = ValueTradeBot(randomness=0.0)

    gs_healthy, unit_healthy = _value_move_gs(
        unit_hex=(5, 0), enemy_hex=(10, 0), hp_cur=10, hp_max=10,
        value=120, ally_value=20, rng=1, cc=5,
    )
    assert bot.select_movement_destination(unit_healthy, [(2, 0), (8, 0)], gs_healthy) == (8, 0)

    gs_wounded, unit_wounded = _value_move_gs(
        unit_hex=(5, 0), enemy_hex=(10, 0), hp_cur=2, hp_max=10,
        value=120, ally_value=20, rng=1, cc=5,
    )
    assert bot.select_movement_destination(unit_wounded, [(2, 0), (8, 0)], gs_wounded) == (2, 0)


def test_tactical_bot_retreat_triggers_on_a_multi_model_squad(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JUMEAU du defaut precedent : le repli du blesse de TacticalBot etait INJOIGNABLE.

    `select_movement_destination` testait `HP_CUR < HP_MAX * 0.5`, somme des PV de l'escouade
    contre PV d'UNE figurine : `_find_safest_position` — et le terme d'objectif qu'on y a
    ajoute — etait du code mort sur tout roster multi-figurines. Ce test verrouille le passage
    a 08.03 ; il n'y en avait AUCUN sur cette methode (le seuil naif y restait vert).
    """
    _patch_move_geometry(monkeypatch)
    bot = TacticalBot(randomness=0.0)

    def _gs(models_alive: int):
        gs, unit = _value_move_gs(
            unit_hex=(5, 0), enemy_hex=(10, 0), models_start=10, models_alive=models_alive,
            hp_cur=models_alive, hp_max=1, value=120, ally_value=20, rng=0, cc=5,
        )
        # L'ennemi doit etre une MENACE DE MELEE : c'est la seule que `_find_safest_position` fuit.
        gs["units"][1].update(_dmg(rng=1, cc=5))
        return gs, unit

    # 3 survivantes sur 10 -> entamee (08.03) -> repli : la destination la plus loin de la menace.
    gs_hurt, unit_hurt = _gs(3)
    assert gs_hurt["units_cache"]["1"]["HP_CUR"] > gs_hurt["units"][0]["HP_MAX"] * 0.5
    assert bot.select_movement_destination(unit_hurt, [(2, 0), (8, 0)], gs_hurt) == (2, 0)

    # 6 survivantes sur 10 -> pas entamee -> position offensive : il se rapproche de la cible.
    gs_ok, unit_ok = _gs(6)
    assert bot.select_movement_destination(unit_ok, [(2, 0), (8, 0)], gs_ok) == (8, 0)


def test_tactical_bot_movement_ignores_w_enemy_on_both_live_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VERROU du `w_enemy` INERTE de `tactical` (V11 §0.55).

    Ce bot ne score pas ses destinations dans le plan (w_objective, w_enemy) des autres : sa
    geometrie ennemie lui est propre (portee de tir / fuite des menaces de melee) et
    `_select_destination`, seul consommateur de `w_enemy`, n'est atteint que dans la branche
    « plus aucun ennemi vivant » — ou le terme ennemi est vide par construction.

    Sans ce verrou, la valeur de `w_enemy` inscrite dans `config/bot_movement_weights.json`
    se lit comme un reglage : c'est ce qui a fait proposer un re-profilage `w_enemy 0.0 ->
    0.6` sans effet. Le fichier porte desormais cette raison ; ce test la rend fausse-able.
    """
    _patch_move_geometry(monkeypatch)

    def _gs(models_alive: int):
        gs, unit = _value_move_gs(
            unit_hex=(5, 0), enemy_hex=(10, 0), models_start=10, models_alive=models_alive,
            hp_cur=models_alive, hp_max=1, value=120, ally_value=20, rng=0, cc=5,
        )
        gs["units"][1].update(_dmg(rng=1, cc=5))
        return gs, unit

    destinations = [(2, 0), (8, 0)]
    for models_alive, expected in ((3, (2, 0)), (6, (8, 0))):
        chosen = set()
        for w_enemy in (-5.0, 0.0, 5.0):
            gs, unit = _gs(models_alive)
            bot = TacticalBot(randomness=0.0, movement_weights=(0.5, w_enemy))
            chosen.add(bot.select_movement_destination(unit, destinations, gs))
        # Une seule destination pour trois poids ennemis opposes : le parametre n'a aucune prise.
        assert chosen == {expected}, (
            f"w_enemy a change la destination de TacticalBot ({models_alive} figurines "
            f"vivantes) : {chosen}"
        )

    # Contre-controle — le vert ci-dessus ne doit PAS venir d'un pool de destinations que rien
    # ne peut departager : `w_objective`, lui, a bien prise sur ces memes candidates.
    gs_obj, unit_obj = _value_move_gs(
        unit_hex=(5, 0), enemy_hex=(10, 0), models_start=10, models_alive=3,
        hp_cur=3, hp_max=1, value=120, ally_value=20, rng=0, cc=5,
        objectives=[_objective([(8, 0)])],
    )
    gs_obj["units"][1].update(_dmg(rng=1, cc=5))
    assert TacticalBot(randomness=0.0, movement_weights=(0.0, 0.0)).select_movement_destination(
        unit_obj, destinations, gs_obj
    ) == (2, 0)
    assert TacticalBot(randomness=0.0, movement_weights=(50.0, 0.0)).select_movement_destination(
        unit_obj, destinations, gs_obj
    ) == (8, 0)


def test_value_trade_score_refuses_a_target_without_hp(monkeypatch: pytest.MonkeyPatch) -> None:
    """PV nuls dans units_cache = invariant rompu -> erreur explicite, jamais une division ni un
    score par defaut."""
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    monkeypatch.setattr(eb, "get_hp_from_cache", lambda uid, gs_: 0)
    gs = _slot_gs("shoot", {"e0": _value_enemy(120)}, ["e0"])
    with pytest.raises(RuntimeError, match=r"invariant est rompu"):
        _act(ValueTradeBot(randomness=0.0), [SHOOT, WAIT_ACTION], gs)

    monkeypatch.setattr(eb, "get_hp_from_cache", lambda uid, gs_: None)
    with pytest.raises(RuntimeError, match=r"absente du cache de HP"):
        _act(ValueTradeBot(randomness=0.0), [SHOOT, WAIT_ACTION], gs)


def test_smart_bot_shoot_slot_mapping_divergence_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slot de tir ouvert sans escouade en face : erreur explicite, pas un tir sur un autre."""
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    gs = _slot_gs("shoot", {"e_weak": _dmg(rng=1, cc=1)}, ["e_weak"])
    with pytest.raises(RuntimeError, match=r"sans escouade ennemie"):
        _act(GreedyBot(randomness=0.0), [SHOOT, SHOOT2], gs)


# ---------------------------------------------------------------------------
# HORS TABLE (reserves 20.01 / attente de deploiement) — chantier « tous les chemins hors table »
# ---------------------------------------------------------------------------

def _off_table_gs() -> dict:
    """Etat minimal ou UN ennemi est hors table et un autre est pose.

    Le `units_cache` est PEUPLE, contrairement aux autres montages de ce fichier qui le laissent
    vide : avec un cache vide, `entry.get("occupied_hexes", {ancre})` tombe sur son repli et le
    vrai chemin — celui que le moteur emprunte — n'est jamais exerce. Une unite hors table a une
    entree PRESENTE avec une empreinte VIDE ; c'est exactement ce que le repli ne rattrape pas.
    """
    return {
        "current_player": ACTING,
        "inches_to_subhex": 1,
        "units": [
            # `_dmg` pose RNG_WEAPONS (NB/DMG) ; `RNG` (la PORTEE) s'y ajoute apres, sinon
            # l'etalement de `_dmg` l'ecrase et `get_max_ranged_range` leve sur la cle manquante.
            {"id": "u0", "player": ACTING, "col": 1, "row": 1,
             **{**_dmg(rng=2, cc=1), "RNG_WEAPONS": [{"NB": 1, "DMG": 2, "RNG": 6}]}},
            {"id": "e_posee", "player": FOE, "col": 4, "row": 1, **_dmg(rng=1, cc=3)},
            {"id": "e_reserve", "player": FOE, "col": -1, "row": -1, **_dmg(rng=1, cc=3)},
        ],
        "units_cache": {
            "u0": {"col": 1, "row": 1, "player": ACTING, "occupied_hexes": {(1, 1)}},
            "e_posee": {"col": 4, "row": 1, "player": FOE, "occupied_hexes": {(4, 1)}},
            # HORS TABLE : entree presente, empreinte VIDE, sentinelle (-1,-1).
            "e_reserve": {"col": -1, "row": -1, "player": FOE, "occupied_hexes": set()},
        },
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


def test_bots_ignore_off_table_units_when_measuring_distance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Les 4 mesures de distance des bots doivent ECARTER une unite hors table.

    Une unite en reserves (20.01) ou pas encore posee est VIVANTE : le seul filtre de ces boucles
    etait `is_unit_alive`, qui la laisse donc passer. Son empreinte est VIDE, et les quatre
    methodes la passent directement a `min_distance_between_sets` -> « Cannot compute distance
    between empty sets ». C'est un CRASH, pas un verdict fausse.

    Le montage garde son temoin `e_posee` : sans lui, ecarter tout le monde rendrait ces methodes
    muettes et le test serait vert a vide.
    """
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs: True)

    gs = _off_table_gs()
    unit = gs["units"][0]

    # TacticalBot — trois des quatre sites.
    tac = TacticalBot(randomness=0.0)
    nearest = tac._find_nearest_enemy(unit, gs)
    assert nearest is not None and nearest["id"] == "e_posee", (
        f"_find_nearest_enemy a retenu {nearest and nearest['id']!r} : une unite hors table n'est "
        "a aucune distance, seule `e_posee` peut etre la plus proche"
    )
    assert tac._find_safest_position(unit, [(1, 1), (2, 2), (8, 8)], gs) in {(1, 1), (2, 2), (8, 8)}
    assert tac._find_best_offensive_position(
        unit, [(1, 1), (4, 4), (7, 7)], {"id": "e_posee", "col": 4, "row": 1}, gs
    ) in {(1, 1), (4, 4), (7, 7)}

    # DefensiveBot — le quatrieme site. `e_posee` est a 3 cases, dans les 12" : elle DOIT compter,
    # sinon un compteur a zero passerait le test sans rien mesurer.
    dfn = DefensiveBot(randomness=0.0)
    assert dfn._count_nearby_threats(unit, gs) == 1, (
        "la menace posee doit etre comptee (et elle seule) : un 0 signifierait que la methode "
        "n'a rien mesure, un 2 qu'elle a compte la reserve"
    )
