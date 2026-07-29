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
from tests._state_invariants import turn_state_invariants

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


def _move_gs(unit_hex=(0, 0), enemy_hex=(10, 0), objectives=None):
    ucol, urow = unit_hex
    ecol, erow = enemy_hex
    gs = {
        "current_player": ACTING,
        "units": [
            {"id": "1", "player": ACTING, "col": ucol, "row": urow},
            {"id": "e", "player": FOE, "col": ecol, "row": erow},
        ],
        "units_cache": {
            "1": {"col": ucol, "row": urow, "player": ACTING, "occupied_hexes": [(ucol, urow)]},
            "e": {"col": ecol, "row": erow, "player": FOE, "occupied_hexes": [(ecol, erow)]},
        },
    }
    if objectives is not None:
        gs["objectives"] = objectives
    return gs, {"id": "1", "player": ACTING, "col": ucol, "row": urow}


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
    assert _act(bot, [4, 9], {"phase": "deployment"}, active={"id": "1", "player": ACTING}) == 4
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
    assert _act(bot, [4, 5, 6], {"phase": "deployment", "episode_number": 1}, active={"id": "1", "player": ACTING}) == 6

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
    gs, unit = _move_gs(unit_hex=(0, 0), enemy_hex=(10, 0))
    # (2,0) plus loin de l'ennemi que (8,0) -> repli
    assert bot.select_movement_destination(unit, [(2, 0), (8, 0)], gs) == (2, 0)


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
        "units_cache": {},
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
    unit = {"id": "u0", "player": ACTING, "RNG_WEAPONS": [{"RNG": 6}]}
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
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    # Les ennemis sont en (5,1) et (6,1) ; l'objectif en (6,1) : le slot 1 le conteste.
    gs = _slot_gs(
        "shoot",
        {"e_far": _dmg(rng=9, cc=1), "e_on_obj": _dmg(rng=1, cc=1)},
        ["e_far", "e_on_obj"],
        objectives=[{"hexes": [{"col": 6, "row": 1}]}],
    )
    assert _act(bot, [SHOOT, SHOOT2, WAIT_ACTION], gs) == SHOOT2
    # Charge phase, unite SUR un objectif -> elle tient sa position.
    charge_gs = _slot_gs(
        "charge",
        {"e_far": _dmg(rng=9, cc=1)},
        ["e_far"],
        objectives=[{"hexes": [{"col": 1, "row": 1}]}],
    )
    assert _act(bot, [CHARGE, WAIT_ACTION], charge_gs) == WAIT_ACTION


def test_aggressive_smart_bot_movement_and_combat(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_move_geometry(monkeypatch)
    bot = AggressiveSmartBot(randomness=0.0)
    gs, unit = _move_gs(unit_hex=(0, 0), enemy_hex=(10, 0))
    # Pousse vers l'ennemi
    assert bot.select_movement_destination(unit, [(2, 0), (8, 0)], gs) == (8, 0)

    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, g: True)
    monkeypatch.setattr(eb, "get_hp_from_cache", lambda uid, gs_: 5)
    combat_gs = _slot_gs("charge", {"e0": _dmg(rng=1, cc=1)}, ["e0"])
    # Charge -> always charge
    assert _act(bot, [CHARGE, WAIT_ACTION], combat_gs) == CHARGE
    # Shoot with no targets -> wait
    shoot_gs = {**combat_gs, "phase": "shoot"}
    assert _act(bot, [CELL, WAIT_ACTION], shoot_gs) == WAIT_ACTION
    # Shoot with targets -> focus-fire de la cible designee par le critere (ici HP egaux et
    # mapping [e0, e1] : le slot 0 l'emporte au premier arrive a score egal).
    targets_gs = _slot_gs("shoot", {"e0": _dmg(rng=1, cc=1), "e1": _dmg(rng=1, cc=1)}, ["e0", "e1"])
    assert _act(bot, [SHOOT, SHOOT2, WAIT_ACTION], targets_gs) == SHOOT


def test_defensive_smart_bot_movement_and_no_charge(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_move_geometry(monkeypatch)
    bot = DefensiveSmartBot(randomness=0.0)
    gs, unit = _move_gs(unit_hex=(0, 0), enemy_hex=(10, 0))
    # Garde ses distances -> s'eloigne de l'ennemi
    assert bot.select_movement_destination(unit, [(2, 0), (8, 0)], gs) == (2, 0)

    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, g: True)
    combat_gs = _slot_gs("charge", {"e0": _dmg(rng=1, cc=1)}, ["e0"])
    # Charge -> never
    assert _act(bot, [CHARGE, WAIT_ACTION], combat_gs) == WAIT_ACTION


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
    monkeypatch.setattr(eb, "get_hp_from_cache", lambda uid, gs_: 5)
    base_gs = _slot_gs(
        "charge",
        {"e0": _dmg(rng=1, cc=1)},
        ["e0"],
        objectives=[{"hexes": [{"col": 50, "row": 50}]}],
    )
    base_gs["turn"] = 3
    # Aucun objectif tenu de part et d'autre -> posture « losing » -> charge
    assert _act(bot, [CHARGE, WAIT_ACTION], base_gs) == CHARGE


# --- V11 §0.3 : portage CC_DMG/RNG_DMG vers le systeme multi-armes -----------------------------
#
# `CC_DMG` / `RNG_DMG` ont ete SUPPRIMES par le refactor multi-armes (cf. reward_mapper :
# « Replaces old RNG_DMG/CC_DMG fields »). Aucun fichier d'unite ne les definit plus, mais 2 bots
# les lisaient encore via require_key -> ConfigurationError.
#
# ⚠️ Correction de l'attribution portee en §0.3 du doc V11 : le site « ControlBot ligne 674 » est
# en fait dans le helper module `_best_target_slot_by_threat`, dont l'UNIQUE appelant est
# `DefensiveSmartBot` (verifie par grep). `DefensiveSmartBot` n'est PAS dans `bot_training.ratios`
# (random/greedy/defensive/control/aggressive_smart/adaptive) : l'exposition est l'EVALUATION,
# pas le training. Ces tests exercent les deux bots concernes sur des unites au contrat ACTUEL
# (sans les champs supprimes) : ils sont rouges sur le code d'avant le portage.

def test_threat_focus_fire_without_legacy_damage_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Menace lue sur RNG_WEAPONS/CC_WEAPONS (les champs RNG_DMG/CC_DMG ont ete supprimes)."""
    gs = _slot_gs(
        "shoot",
        {"e_weak": _dmg(rng=1, cc=1), "e_strong": _dmg(rng=1, cc=6)},
        ["e_weak", "e_strong"],
    )
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    monkeypatch.setattr(eb, "get_hp_from_cache", lambda uid, gs_: 5)

    bot = DefensiveSmartBot(randomness=0.0)
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
    units_cache = {"1": dict(ours)}
    for i, (eid, fields) in enumerate(enemies.items()):
        enemy = {"id": eid, "player": FOE, "col": 5 + i, "row": 1, **fields}
        units.append(enemy)
        units_cache[eid] = dict(enemy)
    gs = {**turn_state_invariants(),
        "phase": phase,
        "current_player": current_player,
        "turn": 1,
        "units": units,
        "units_cache": units_cache,
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

    # Menace (DefensiveSmartBot) : mapping [faible, forte] -> slot 1 ; pool inverse [forte, faible].
    gs_threat = _slot_gs(
        "shoot",
        {"e_weak": _dmg(rng=1, cc=1), "e_strong": _dmg(rng=2, cc=8)},
        ["e_weak", "e_strong"],
    )
    gs_threat["units"][0]["valid_target_pool"] = ["e_strong", "e_weak"]
    assert (
        _act(DefensiveSmartBot(randomness=0.0), 
            [SHOOT, SHOOT2, WAIT_ACTION], gs_threat
        )
        == SHOOT2
    )

    # HP (AggressiveSmartBot, AdaptiveBot) : mapping [pleine, entamee] -> slot 1 ; pool inverse.
    gs_hp = _slot_gs(
        "shoot",
        {"e_full": _dmg(rng=1, cc=1), "e_hurt": _dmg(rng=1, cc=1)},
        ["e_full", "e_hurt"],
    )
    gs_hp["units"][0]["valid_target_pool"] = ["e_hurt", "e_full"]
    assert (
        _act(AggressiveSmartBot(randomness=0.0), 
            [SHOOT, SHOOT2, WAIT_ACTION], gs_hp
        )
        == SHOOT2
    )
    assert (
        _act(AdaptiveBot(randomness=0.0), [SHOOT, SHOOT2, WAIT_ACTION], gs_hp)
        == SHOOT2
    )


def test_smart_bot_shoot_slot_mapping_divergence_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slot de tir ouvert sans escouade en face : erreur explicite, pas un tir sur un autre."""
    monkeypatch.setattr(eb, "is_unit_alive", lambda uid, gs_: True)
    gs = _slot_gs("shoot", {"e_weak": _dmg(rng=1, cc=1)}, ["e_weak"])
    with pytest.raises(RuntimeError, match=r"sans escouade ennemie"):
        _act(AggressiveSmartBot(randomness=0.0), [SHOOT, SHOOT2], gs)
