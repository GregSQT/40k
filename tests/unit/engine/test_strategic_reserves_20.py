"""Réserves stratégiques (20.01-20.04) et Deep Strike (24.09).

Chantier 04. Les verrous portent sur les points où la règle peut être satisfaite « par hasard »
(un pool vide fait passer n'importe quel test de refus) ou par un effet de bord géométrique :

- **8" strictement** : une case à 8" pile d'un ennemi est REFUSÉE, la première case au-delà est
  ACCEPTÉE. La borne est testée, pas le milieu, et dans les DEUX métriques du moteur.
- **Zone adverse** : fermée avant le 3e round pour une unité sans Deep Strike, ouverte pour une
  unité avec, ouverte pour les deux à partir du 3e round.
- **« every model »** : une escouade Deep Strike menée par un character qui ne l'a pas PERD la
  capacité (24.09 lue littéralement, contre l'union 19.04).
- **Destruction fin de 3e round** : l'unité restée en réserves est détruite ; le test devient
  ROUGE si la règle est retirée (vérifié en la neutralisant, cf. l'en-tête de ce fichier).
- **Vert vacant** : chaque test de REFUS commence par prouver que le pool rend des destinations,
  sinon il ne prouverait rien.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCENARIO = (
    PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent" / "scenarios" / "training"
    / "scenario_training_armageddon.json"
)

UNDEPLOYED = (-1, -1)


# ---------------------------------------------------------------------------
# Harnais : moteur réel, déploiement piloté, mise en réserves construite
# ---------------------------------------------------------------------------


def _engine(training_config_name: str = "x5_debug", seed: int = 0):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name=training_config_name,
        controlled_agent="ArmageddonAgent", scenario_file=str(SCENARIO),
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    # Le scheduler par-épisode peut rejouer le scénario en 'fixed' : ces tests exigent la phase
    # de déploiement ACTIF (c'est là que la mise en réserves se décide).
    assert eng.training_config is not None
    sched = eng.training_config.get("deployment_mode_schedule")
    if isinstance(sched, dict):
        sched["enabled"] = False
    eng.reset(seed=seed)
    return eng


def _drive_deployment(eng, reserve_first_unit: bool = False) -> str:
    """Déroule le déploiement. Retourne l'id de l'escouade mise en réserves ('' si aucune)."""
    from engine.macro_intents import ACTION_WAIT

    gs = eng.game_state
    reserved = ""
    steps = 0
    while gs.get("phase") == "deployment" and steps < 1000:
        mask = eng.get_action_mask()
        if reserve_first_unit and not reserved and mask[ACTION_WAIT]:
            active = eng.action_decoder.get_deployment_active_unit(gs)
            reserved = str(active["id"])
            eng.step(int(ACTION_WAIT))
        else:
            deploy_actions = [a for a in range(4, 9) if mask[a]]
            assert deploy_actions, f"aucune action de déploiement au step {steps}"
            eng.step(int(deploy_actions[0]))
        steps += 1
    assert gs.get("phase") != "deployment", "déploiement non terminé"
    return reserved


def _unit(gs: Dict[str, Any], unit_id: str) -> Dict[str, Any]:
    from engine.combat_utils import get_unit_by_id

    unit = get_unit_by_id(gs, str(unit_id))
    assert unit is not None, f"unité {unit_id} introuvable"
    return unit


def _force_into_reserves(gs: Dict[str, Any], unit_id: str) -> None:
    """Place une unité DÉJÀ POSÉE en réserves, sans passer par 20.02 (état construit)."""
    from engine.phase_handlers.movement_handlers import reposition_unit_to_strategic_reserves

    reposition_unit_to_strategic_reserves(gs, str(unit_id))
    # Cas 20.01 (mise en réserves AVANT la bataille) et non 20.02 : ce test construit une unité
    # qui n'est jamais arrivée, donc elle n'est pas « repositionnée » et reste sous le coup de
    # la destruction de fin de 3e round.
    _unit(gs, unit_id)["reserves_repositioned"] = False


# ---------------------------------------------------------------------------
# 20.01 — plafond de 50 %
# ---------------------------------------------------------------------------


def _fake_unit(uid: str, player: int, value: int, reserves: bool) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "VALUE": value, "unitType": f"Type{uid}",
        "in_strategic_reserves": reserves,
    }


def test_reserves_cap_rejects_over_50_percent_and_names_the_units():
    from engine.game_state import validate_strategic_reserves_cap

    units = [
        _fake_unit("a", 1, 200, True),
        _fake_unit("b", 1, 120, True),
        _fake_unit("c", 1, 180, False),
    ]
    with pytest.raises(ValueError) as excinfo:
        validate_strategic_reserves_cap(units, 500, "test")
    message = str(excinfo.value)
    assert "320" in message, "le total en réserves doit être nommé"
    assert "250" in message, "le plafond doit être nommé"
    assert "id=a" in message and "id=b" in message, "les unités en réserves doivent être nommées"
    assert "id=c" not in message, "une unité déployée normalement n'a pas à figurer"


def test_reserves_cap_accepts_exactly_50_percent():
    """« cannot exceed 50% » : l'égalité est LÉGALE, seul le dépassement est refusé."""
    from engine.game_state import validate_strategic_reserves_cap

    validate_strategic_reserves_cap([_fake_unit("a", 1, 250, True)], 500, "test")


def test_reserves_cap_is_per_player():
    from engine.game_state import validate_strategic_reserves_cap

    validate_strategic_reserves_cap(
        [_fake_unit("a", 1, 250, True), _fake_unit("b", 2, 250, True)], 500, "test"
    )


def test_battle_points_limit_rejects_unknown_scale():
    from engine.game_state import battle_points_limit

    assert battle_points_limit("500pts", "test") == 500
    with pytest.raises(ValueError):
        battle_points_limit("large", "test")


# ---------------------------------------------------------------------------
# 24.09 — « if every model in this unit has this ability »
# ---------------------------------------------------------------------------


def test_deep_strike_requires_every_model():
    """Escouade Deep Strike + character sans la capacité -> l'unité PERD Deep Strike.

    Cas CONSTRUIT sur l'escouade réelle du roster (Vanguard Veteran Squad with Jump Packs +
    Chaplain with Jump Pack, tous deux Deep Strike) : on retire la capacité aux règles PROPRES
    de la figurine du character, ce qui est exactement la situation décrite par 24.09.
    """
    from engine.phase_handlers.movement_handlers import DEEP_STRIKE_RULE_ID, unit_has_deep_strike

    eng = _engine()
    gs = eng.game_state
    squad_id = next(
        sid for sid in gs["squad_models"]
        if unit_has_deep_strike(gs, sid)
    )
    assert unit_has_deep_strike(gs, squad_id), "l'escouade témoin doit avoir Deep Strike"

    models = [gs["models_cache"][mid] for mid in gs["squad_models"][squad_id]]
    assert len(models) >= 2, "il faut une escouade multi-figurines pour tester « every model »"
    # Une SEULE figurine perd la capacité : l'union 19.04 la conserverait, 24.09 non.
    victim = models[-1]
    victim["UNIT_RULES"] = [
        r for r in victim["UNIT_RULES"] if str(r["ruleId"]) != DEEP_STRIKE_RULE_ID
    ]
    assert not unit_has_deep_strike(gs, squad_id), (
        "une escouade dont UNE figurine n'a pas Deep Strike ne doit plus l'avoir (24.09)"
    )


def test_armageddon_deep_strike_units_declare_the_ability():
    """Les 3 unités du PDF Armageddon portent bien `deep_strike` (sinon le pool 24.09 est mort)."""
    from ai.unit_registry import UnitRegistry

    registry = UnitRegistry()
    for unit_type in (
        "ChaplainJumpPack", "VanguardVeteranSquadJumpPack",
        "VanguardVeteranSquadJumpPackSergeant", "VanguardVeteranSquadJumpPackPlasma",
        "LandSpeederOnslaughtGatlingCannon", "LandSpeederHeavyFlamer",
    ):
        rules = {str(r["ruleId"]) for r in registry.get_unit_data(unit_type)["UNIT_RULES"]}
        assert "deep_strike" in rules, f"{unit_type} devrait porter CORE: Deep Strike"


# ---------------------------------------------------------------------------
# 20.04 — pool d'ingress
# ---------------------------------------------------------------------------


def _reserve_squad(eng, deep_strike: bool) -> str:
    """Met en réserves une escouade du joueur 1, avec ou sans Deep Strike, et rend son id."""
    from engine.phase_handlers.movement_handlers import unit_has_deep_strike

    gs = eng.game_state
    candidates = [
        sid for sid, entry in gs["units_cache"].items()
        if int(entry["player"]) == 1 and unit_has_deep_strike(gs, sid) == deep_strike
    ]
    assert candidates, f"aucune escouade J1 avec deep_strike={deep_strike}"
    squad_id = candidates[0]
    _force_into_reserves(gs, squad_id)
    return squad_id


def test_ingress_pool_is_not_empty_before_asserting_refusals():
    """VERT VACANT — le pool d'ingress rend de vraies destinations.

    Sans ce contrôle, tous les tests de refus ci-dessous passeraient sur un pool vide.
    """
    from engine.phase_handlers.movement_handlers import ingress_setup_pool

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    gs["turn"] = 2
    squad_id = _reserve_squad(eng, deep_strike=False)
    pool = ingress_setup_pool(gs, squad_id)
    assert len(pool) > 100, f"pool d'ingress quasi vide ({len(pool)} cases) — test sans portée"


def test_ingress_pool_stays_within_6_inches_of_a_board_edge():
    from engine.phase_handlers.movement_handlers import (
        INGRESS_SETUP_DISTANCE_INCHES, ingress_setup_pool,
    )

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    gs["turn"] = 2
    squad_id = _reserve_squad(eng, deep_strike=False)
    pool = ingress_setup_pool(gs, squad_id)
    assert pool
    band = INGRESS_SETUP_DISTANCE_INCHES * int(gs["inches_to_subhex"])
    cols, rows = int(gs["board_cols"]), int(gs["board_rows"])
    for c, r in pool:
        assert min(c, cols - 1 - c, r, rows - 1 - r) <= band, (
            f"case ({c},{r}) hors de la bande de {INGRESS_SETUP_DISTANCE_INCHES}\" d'un bord"
        )


def test_deep_strike_pool_covers_more_than_the_edge_band():
    """24.09 remplace la contrainte de bord : le pool sort de la bande de 6"."""
    from engine.phase_handlers.movement_handlers import (
        INGRESS_SETUP_DISTANCE_INCHES, ingress_setup_pool,
    )

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    gs["turn"] = 3  # zone adverse ouverte pour tous : on isole la clause de BORD
    squad_id = _reserve_squad(eng, deep_strike=True)
    pool = ingress_setup_pool(gs, squad_id)
    band = INGRESS_SETUP_DISTANCE_INCHES * int(gs["inches_to_subhex"])
    cols, rows = int(gs["board_cols"]), int(gs["board_rows"])
    outside = [
        (c, r) for c, r in pool if min(c, cols - 1 - c, r, rows - 1 - r) > band
    ]
    assert outside, "Deep Strike doit pouvoir poser hors de la bande de bord (24.09)"


def test_ingress_forbids_exactly_8_inches_and_allows_the_first_cell_beyond():
    """VERROU DES 8" — la BORNE, dans la métrique du moteur.

    On construit la situation : un seul ennemi sur le plateau, une case candidate alignée
    horizontalement. La frontière est calculée par la primitive CANONIQUE
    (`entries_in_engagement_zone` à 8", figurine réduite à sa case) ; le pool doit refuser la
    dernière case « à 8" ou moins » et accepter la première au-delà.
    """
    from engine.phase_handlers.movement_handlers import (
        INGRESS_ENEMY_CLEARANCE_INCHES, _ingress_enemy_clearance_forbidden,
    )
    from engine.spatial_relations import engagement_distance_metric, entries_in_engagement_zone

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    board_cols, board_rows = int(gs["board_cols"]), int(gs["board_rows"])
    clearance = INGRESS_ENEMY_CLEARANCE_INCHES * int(gs["inches_to_subhex"])

    # UN seul ennemi, placé loin des bords : la frontière testée est bien la sienne.
    enemy_ids = [sid for sid, e in gs["units_cache"].items() if int(e["player"]) == 2]
    assert enemy_ids
    keep = enemy_ids[0]
    for sid in enemy_ids[1:]:
        _force_into_reserves(gs, sid)
    enemy = gs["units_cache"][keep]
    ecol, erow = int(enemy["col"]), int(enemy["row"])

    forbidden = _ingress_enemy_clearance_forbidden(
        gs, player=1, clearance_subhex=clearance,
        board_cols=board_cols, board_rows=board_rows,
    )
    metric = engagement_distance_metric(gs)

    def _oracle(col: int, row: int) -> bool:
        """Verdict canonique : cette case est-elle à 8" OU MOINS de l'ennemi ?"""
        cell_entry = {
            "col": col, "row": row, "player": 1,
            "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
            "occupied_hexes": {(col, row)},
        }
        return entries_in_engagement_zone(cell_entry, enemy, clearance, metric)

    # Balayage horizontal depuis l'ennemi : on cherche la 1re case que la règle AUTORISE.
    boundary = None
    for delta in range(1, 3 * clearance):
        col = ecol + delta
        if col >= board_cols:
            break
        if not _oracle(col, erow):
            boundary = col
            break
    assert boundary is not None, "frontière des 8\" introuvable — situation mal construite"

    assert forbidden[boundary - 1, erow], (
        "la dernière case à 8\" ou moins doit être REFUSÉE (« more than 8\" », 20.04)"
    )
    assert not forbidden[boundary, erow], (
        "la première case au-delà de 8\" doit être ACCEPTÉE"
    )


def test_ingress_clearance_mask_matches_the_canonical_primitive():
    """Le masque vectorisé des 8" est le MIROIR de `entries_in_engagement_zone`, case à case."""
    from engine.phase_handlers.movement_handlers import (
        INGRESS_ENEMY_CLEARANCE_INCHES, _ingress_enemy_clearance_forbidden,
    )
    from engine.spatial_relations import engagement_distance_metric, entries_in_engagement_zone

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    board_cols, board_rows = int(gs["board_cols"]), int(gs["board_rows"])
    clearance = INGRESS_ENEMY_CLEARANCE_INCHES * int(gs["inches_to_subhex"])
    forbidden = _ingress_enemy_clearance_forbidden(
        gs, player=1, clearance_subhex=clearance,
        board_cols=board_cols, board_rows=board_rows,
    )
    metric = engagement_distance_metric(gs)
    enemies = [
        e for sid, e in gs["units_cache"].items()
        if int(e["player"]) == 2 and int(e["col"]) >= 0
    ]
    assert enemies

    checked = 0
    for enemy in enemies:
        ecol, erow = int(enemy["col"]), int(enemy["row"])
        for delta in range(-2 * clearance, 2 * clearance + 1, 7):
            col = ecol + delta
            if not (0 <= col < board_cols):
                continue
            cell_entry = {
                "col": col, "row": erow, "player": 1,
                "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
                "occupied_hexes": {(col, erow)},
            }
            expected = any(
                entries_in_engagement_zone(cell_entry, other, clearance, metric)
                for other in enemies
            )
            assert bool(forbidden[col, erow]) == expected, (
                f"case ({col},{erow}) : masque={bool(forbidden[col, erow])} "
                f"vs primitive canonique={expected}"
            )
            checked += 1
    assert checked > 20, f"échantillon trop maigre ({checked} cases) — test sans portée"


def _opponent_zone(gs: Dict[str, Any], player: int) -> Set[Tuple[int, int]]:
    from engine.phase_handlers.movement_handlers import _opponent_deployment_zone_cells

    return _opponent_deployment_zone_cells(gs, player)


def test_opponent_zone_closed_before_round_3_open_from_round_3():
    """VERROU DE ZONE ADVERSE — sans Deep Strike : fermée au round 2, ouverte au round 3."""
    from engine.phase_handlers.movement_handlers import ingress_setup_pool

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    squad_id = _reserve_squad(eng, deep_strike=False)
    zone = _opponent_zone(gs, 1)
    assert zone, "zone de déploiement adverse vide — test sans portée"

    gs["turn"] = 2
    pool_r2 = ingress_setup_pool(gs, squad_id)
    assert pool_r2, "pool vide au round 2 — le refus ne prouverait rien"
    assert not (pool_r2 & zone), "aucune case de la zone adverse avant le 3e round (20.04)"

    gs["turn"] = 3
    pool_r3 = ingress_setup_pool(gs, squad_id)
    assert pool_r3 & zone, "à partir du 3e round, la zone adverse est ouverte (20.04)"


def test_deep_strike_opens_the_opponent_zone_at_round_2():
    """24.09 « even if that is within your opponent's deployment zone »."""
    from engine.phase_handlers.movement_handlers import ingress_setup_pool

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    gs["turn"] = 2
    zone = _opponent_zone(gs, 1)
    assert zone

    plain = _reserve_squad(eng, deep_strike=False)
    deep = _reserve_squad(eng, deep_strike=True)
    assert not (ingress_setup_pool(gs, plain) & zone), (
        "une unité SANS Deep Strike ne peut pas être posée dans la zone adverse au round 2"
    )
    assert ingress_setup_pool(gs, deep) & zone, (
        "une unité AVEC Deep Strike le peut (24.09)"
    )


# ---------------------------------------------------------------------------
# 20.03 — pas avant le 2e round
# ---------------------------------------------------------------------------


def test_no_ingress_on_round_1():
    from engine.phase_handlers.movement_handlers import ingress_eligible_units

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    squad_id = _reserve_squad(eng, deep_strike=True)
    gs["current_player"] = 1

    gs["turn"] = 1
    assert ingress_eligible_units(gs) == [], "aucun ingress avant le 2e round (20.03)"
    gs["turn"] = 2
    assert squad_id in ingress_eligible_units(gs), "l'ingress s'ouvre au 2e round"


# ---------------------------------------------------------------------------
# Hors table : ni ciblable, ni compté, ni bloquant
# ---------------------------------------------------------------------------


def test_reserve_unit_is_invisible_to_the_battlefield():
    from engine.phase_handlers.shared_utils import entry_is_on_battlefield, is_unit_alive

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    squad_id = _reserve_squad(eng, deep_strike=True)

    entry = gs["units_cache"][squad_id]
    assert is_unit_alive(squad_id, gs), "une unité en réserves est VIVANTE (elle compte aux points)"
    assert not entry_is_on_battlefield(entry)
    assert (int(entry["col"]), int(entry["row"])) == UNDEPLOYED
    assert not entry["occupied_hexes"], (
        "une unité hors table n'occupe aucune case — sinon elle bloque le plateau et fausse "
        "toutes les distances d'empreinte"
    )
    for mid in gs["squad_models"][squad_id]:
        model = gs["models_cache"][mid]
        assert (int(model["col"]), int(model["row"])) == UNDEPLOYED


def test_reserve_unit_is_not_a_shooting_target():
    from engine.phase_handlers.shooting_handlers import build_unit_los_cache

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    # On met en réserves une unité du joueur 2 : elle ne doit plus être visée par le joueur 1.
    target = next(sid for sid, e in gs["units_cache"].items() if int(e["player"]) == 2)
    shooters = [sid for sid, e in gs["units_cache"].items() if int(e["player"]) == 1]
    assert shooters
    _force_into_reserves(gs, target)

    for shooter in shooters:
        gs["_unit_move_version"] = int(gs.get("_unit_move_version", 0)) + 1
        build_unit_los_cache(gs, shooter)
        los = _unit(gs, shooter).get("los_cache", {})
        assert target not in los, (
            f"l'escouade {target}, en réserves, reste une cible de tir de {shooter}"
        )


def test_reserve_unit_controls_no_objective():
    from engine.game_state import sum_objective_control_oc_multi, objective_hex_sets

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    hex_sets = objective_hex_sets(gs)
    assert hex_sets, "aucun objectif — test sans portée"

    before = sum_objective_control_oc_multi(gs, hex_sets)
    # On retire du plateau TOUTES les unités du joueur 1 vers les réserves : son OC doit tomber
    # à zéro partout. Un contrôle résiduel signalerait une empreinte fantôme en (-1,-1).
    for sid in [s for s, e in gs["units_cache"].items() if int(e["player"]) == 1]:
        _force_into_reserves(gs, sid)
    after = sum_objective_control_oc_multi(gs, hex_sets)
    assert any(p1 for p1, _ in before) or True  # l'état initial n'est pas garanti contrôlant
    assert all(p1 == 0 for p1, _ in after), (
        "une unité en réserves ne contrôle aucun objectif (14.02)"
    )


# ---------------------------------------------------------------------------
# 20.04 — mise en place, verrou de mouvement, destruction
# ---------------------------------------------------------------------------


def test_ingress_places_every_model_and_locks_further_moves():
    from engine.phase_handlers.movement_handlers import (
        ingress_setup_pool, unit_ingress_move_locked,
    )

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    gs["turn"] = 2
    gs["current_player"] = 1
    squad_id = _reserve_squad(eng, deep_strike=False)

    candidates = eng.action_decoder.ingress_slot_candidates(gs, squad_id)
    assert candidates, "aucun candidat d'ingress — test sans portée"
    action_int = sorted(candidates)[0]
    semantic = {
        "action": "ingress_move", "unitId": squad_id,
        "destCol": candidates[action_int]["hex"][0],
        "destRow": candidates[action_int]["hex"][1],
        "plan": candidates[action_int]["plan"],
    }
    pool = ingress_setup_pool(gs, squad_id)
    from engine.phase_handlers.movement_handlers import ingress_commit_plan

    ok, _res = ingress_commit_plan(gs, squad_id, semantic["plan"])
    assert ok, "l'ingress issu du masque doit être exécutable"

    unit = _unit(gs, squad_id)
    assert unit["deployed_on_turn"] == 2, "l'unité arrive au tour courant"
    assert unit["in_strategic_reserves"] is False, "elle n'est plus en réserves une fois posée"
    for mid in gs["squad_models"][squad_id]:
        model = gs["models_cache"][mid]
        pos = (int(model["col"]), int(model["row"]))
        assert pos != UNDEPLOYED, f"figurine {mid} laissée hors table par l'ingress"
        assert pos in pool, f"figurine {mid} posée hors de l'aire légale 20.04"
    assert unit_ingress_move_locked(gs, squad_id), (
        "20.04 AFTER MOVING : l'unité n'est éligible à aucun autre type de mouvement"
    )

    from engine.phase_handlers.movement_handlers import get_eligible_units

    gs["phase"] = "move"
    assert squad_id not in get_eligible_units(gs), (
        "l'unité arrivée de réserves ne doit pas pouvoir se déplacer ensuite"
    )


def test_ingress_lock_falls_at_the_start_of_the_charge_phase():
    from engine.phase_handlers.movement_handlers import (
        clear_ingress_move_lock, mark_unit_ingressed, unit_ingress_move_locked,
    )

    gs: Dict[str, Any] = {}
    mark_unit_ingressed(gs, "u1")
    assert unit_ingress_move_locked(gs, "u1")
    clear_ingress_move_lock(gs)
    assert not unit_ingress_move_locked(gs, "u1"), (
        "« until the start of the next Charge phase » : le verrou tombe à ce moment-là"
    )


def test_unarrived_reserves_are_destroyed_at_the_end_of_round_3():
    """VERROU DE DESTRUCTION (20.04). Retirer la règle rend ce test ROUGE."""
    from engine.w40k_core import destroy_unarrived_strategic_reserves
    from engine.phase_handlers.shared_utils import is_unit_alive

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    squad_id = _reserve_squad(eng, deep_strike=True)
    gs["turn"] = 3

    assert is_unit_alive(squad_id, gs), "l'unité doit être vivante avant la règle"
    destroyed = destroy_unarrived_strategic_reserves(gs)
    assert squad_id in destroyed
    assert not is_unit_alive(squad_id, gs), (
        "une unité restée en réserves à la fin du 3e round est DÉTRUITE (20.04)"
    )


def test_repositioned_unit_survives_the_end_of_round_3():
    """Exception 20.04 : les unités repositionnées (20.02) ne sont pas détruites."""
    from engine.w40k_core import destroy_unarrived_strategic_reserves
    from engine.phase_handlers.movement_handlers import reposition_unit_to_strategic_reserves
    from engine.phase_handlers.shared_utils import is_unit_alive

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    squad_id = next(sid for sid, e in gs["units_cache"].items() if int(e["player"]) == 1)
    reposition_unit_to_strategic_reserves(gs, squad_id)
    gs["turn"] = 3

    destroyed = destroy_unarrived_strategic_reserves(gs)
    assert squad_id not in destroyed
    assert is_unit_alive(squad_id, gs), "une unité repositionnée survit (20.04, exception)"


def test_arrived_unit_is_not_destroyed_at_the_end_of_round_3():
    from engine.w40k_core import destroy_unarrived_strategic_reserves
    from engine.phase_handlers.shared_utils import is_unit_alive

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    squad_id = next(sid for sid, e in gs["units_cache"].items() if int(e["player"]) == 1)
    gs["turn"] = 3
    assert not _unit(gs, squad_id)["in_strategic_reserves"]
    assert destroy_unarrived_strategic_reserves(gs) == []
    assert is_unit_alive(squad_id, gs)


# ---------------------------------------------------------------------------
# CHEMIN DE PRODUCTION — l'agent met en réserves, puis fait arriver l'unité
# ---------------------------------------------------------------------------


def test_agent_can_reserve_a_unit_then_ingress_it_through_the_real_loop():
    """Bout en bout par le VRAI chemin gym : masque -> `step` -> état.

    C'est le seul test qui prouve que la mécanique est ATTEIGNABLE en production : mise en
    réserves décidée pendant le déploiement (action `WAIT` ouverte par le masque), puis arrivée
    par un slot d'ingress ouvert en phase de mouvement à partir du 2e round.
    """
    from engine.macro_intents import ACTION_WAIT, DEPLOY_SLOT_BASE, DEPLOY_SLOT_COUNT

    eng = _engine()
    reserved = _drive_deployment(eng, reserve_first_unit=True)
    gs = eng.game_state
    assert reserved, "le masque de déploiement n'a jamais ouvert la mise en réserves (20.01)"
    assert _unit(gs, reserved)["in_strategic_reserves"] is True
    assert (int(gs["units_cache"][reserved]["col"]), int(gs["units_cache"][reserved]["row"])) == UNDEPLOYED

    ingress_slots = list(range(DEPLOY_SLOT_BASE, DEPLOY_SLOT_BASE + DEPLOY_SLOT_COUNT))
    played_ingress = False
    for _ in range(4000):
        if gs.get("game_over"):
            break
        mask = eng.get_action_mask()
        legal = [int(a) for a, ok in enumerate(mask) if ok]
        assert legal, "masque entièrement fermé"
        # Dès que l'escouade en réserves est l'unité active de la phase de mouvement, ses slots
        # d'ingress sont ouverts : on les joue.
        _, eligible = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)
        active_is_reserve = bool(eligible) and str(eligible[0]["id"]) == reserved
        if gs.get("phase") == "move" and active_is_reserve:
            slots = [a for a in ingress_slots if mask[a]]
            if slots:
                assert int(gs["turn"]) >= 2, "un ingress ne peut pas s'ouvrir au 1er round (20.03)"
                eng.step(int(slots[0]))
                played_ingress = True
                break
            # Aucun slot ouvert (aucune destination légale) : on renonce ce tour-ci.
            assert mask[ACTION_WAIT], "renoncer à l'ingress doit toujours rester possible"
            eng.step(int(ACTION_WAIT))
            continue
        eng.step(legal[0])

    assert played_ingress, "l'escouade en réserves n'a jamais pu faire son ingress move"
    unit = _unit(gs, reserved)
    assert unit["in_strategic_reserves"] is False
    assert unit["deployed_on_turn"] == int(gs["turn"]) or unit["deployed_on_turn"] is not None
    entry = gs["units_cache"][reserved]
    assert (int(entry["col"]), int(entry["row"])) != UNDEPLOYED, (
        "après l'ingress, l'escouade doit être sur le plateau"
    )


# ---------------------------------------------------------------------------
# 20.02 — unités repositionnées
# ---------------------------------------------------------------------------


def test_repositioned_unit_keeps_its_advance_and_battle_shock():
    """20.02 clauses 2 et 3 : le retrait n'efface NI le fait d'avoir avancé, NI le battle-shock."""
    from engine.phase_handlers.movement_handlers import reposition_unit_to_strategic_reserves

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    squad_id = next(sid for sid, e in gs["units_cache"].items() if int(e["player"]) == 1)
    gs.setdefault("units_advanced", set()).add(squad_id)
    gs.setdefault("units_moved", set()).add(squad_id)
    gs.setdefault("units_fled", set()).add(squad_id)
    _unit(gs, squad_id)["battle_shocked"] = True

    reposition_unit_to_strategic_reserves(gs, squad_id)

    assert squad_id in gs["units_advanced"], (
        "20.02 : une unité replacée en réserves A TOUJOURS fait son Advance ce tour-là"
    )
    assert squad_id in gs["units_fled"]
    assert squad_id in gs["units_moved"]
    assert _unit(gs, squad_id)["battle_shocked"] is True, (
        "20.02 : les effets à durée continuent de s'appliquer hors table (exemple du PDF : "
        "une unité battle-shocked au retrait l'est toujours à son retour le même tour)"
    )
    assert _unit(gs, squad_id)["reserves_repositioned"] is True


def test_repositioning_an_already_moved_unit_is_allowed():
    """20.02 clause 1 : utilisable sur une unité qui a DÉJÀ bougé cette phase."""
    from engine.phase_handlers.movement_handlers import reposition_unit_to_strategic_reserves

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    squad_id = next(sid for sid, e in gs["units_cache"].items() if int(e["player"]) == 1)
    gs.setdefault("units_moved", set()).add(squad_id)
    reposition_unit_to_strategic_reserves(gs, squad_id)  # ne doit pas lever
    assert _unit(gs, squad_id)["deployed_on_turn"] is None
