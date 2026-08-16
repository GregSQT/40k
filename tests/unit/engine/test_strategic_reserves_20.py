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

import sys

from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
# Scénario à rosters PINNÉS, et sans réserves déclarées. Ces tests construisent eux-mêmes leurs
# réserves (`_force_into_reserves`, qui applique 20.02 et EXIGE une unité posée) : ils supposent
# donc que toutes les unités démarrent SUR LA TABLE.
#
# `scenario_training_armageddon1.json`, utilisé auparavant, tire son roster au sort
# (`agent_roster_ref: "training_random"`, glob du dossier). Le jour où une variante à réserves
# entre dans ce dossier, 16 tests de ce fichier tombent — mesuré au chantier 04c, qui les y a
# mis puis les a ressortis dans un sous-dossier `variants/` (le glob n'est pas récursif).
# Depuis l'activation des variantes (elles sont REVENUES dans `training/`, donc dans le tirage),
# ce pin n'est plus une précaution : il est ce qui tient ce fichier debout. Ne pas le repointer
# sur le scénario d'entraînement.
from tests.unit.engine._config_helpers import both_terrains

SCENARIO = (
    PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent" / "scenarios" / "training"
    / "reserves_20_fixture1.json"
)

# Ce fichier est REJOUÉ SUR LES DEUX TERRAINS : ce qu'il vérifie dépend des murs, des zones de
# déploiement ou des pièces d'objectif, et ces trois-là changent entièrement entre `terrain-mc1`
# et `terrain-mc2`. La fixture réécrit `SCENARIO` le temps de chaque test (cf. `both_terrains`).
_terrain = both_terrains(sys.modules[__name__])


UNDEPLOYED = (-1, -1)


@pytest.fixture(autouse=True)
def _pin_board(board_x5):
    pass


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
    # Les DEUX sens sont essayés, et c'est nécessaire : la position de l'ennemi dépend du terrain,
    # et sur une carte où il est proche du bord droit le balayage sortait du plateau avant
    # d'atteindre la frontière — le test échouait alors sur « situation mal construite » sans que
    # la règle des 8" soit en cause. Elle est symétrique, le sens n'a aucune importance pour elle.
    boundary = None
    direction = 0
    for step in (1, -1):
        for delta in range(1, 3 * clearance):
            col = ecol + step * delta
            if col < 0 or col >= board_cols:
                break
            if not _oracle(col, erow):
                boundary = col
                direction = step
                break
        if boundary is not None:
            break
    assert boundary is not None, "frontière des 8\" introuvable — situation mal construite"

    # `boundary - direction` = la case juste AVANT la frontière, du côté de l'ennemi, quel que
    # soit le sens de balayage retenu.
    assert forbidden[boundary - direction, erow], (
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
# Les trois clauses de 20.03/20.04 sont des PARAMÈTRES PAR UNITÉ
# ---------------------------------------------------------------------------


def test_reserves_parameters_default_to_the_generic_rule():
    from engine.phase_handlers.movement_handlers import (
        INGRESS_ENEMY_CLEARANCE_INCHES, INGRESS_FIRST_BATTLE_ROUND,
        INGRESS_SETUP_DISTANCE_INCHES, RESERVES_ARRIVAL_ROUND_FIELD,
        RESERVES_EDGE_DISTANCE_FIELD, RESERVES_ENEMY_CLEARANCE_FIELD,
    )

    eng = _engine()
    gs = eng.game_state
    for unit in gs["units"]:
        assert unit[RESERVES_ARRIVAL_ROUND_FIELD] == INGRESS_FIRST_BATTLE_ROUND
        assert unit[RESERVES_EDGE_DISTANCE_FIELD] == INGRESS_SETUP_DISTANCE_INCHES
        assert unit[RESERVES_ENEMY_CLEARANCE_FIELD] == INGRESS_ENEMY_CLEARANCE_INCHES


def test_granted_arrival_round_opens_the_ingress_earlier():
    """20.03 « unless otherwise stated » : une capacité fait arriver l'unité au 1er round."""
    from engine.phase_handlers.movement_handlers import (
        ingress_eligible_units, set_reserves_arrival_round,
    )

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    squad_id = _reserve_squad(eng, deep_strike=True)
    gs["current_player"] = 1
    gs["turn"] = 1

    assert ingress_eligible_units(gs) == [], "porte fermée au round 1 par défaut (20.03)"
    set_reserves_arrival_round(gs, squad_id, 1)
    assert squad_id in ingress_eligible_units(gs), (
        "une capacité doit pouvoir ouvrir l'arrivée au 1er round, sur CETTE unité"
    )
    # La porte reste fermée pour les AUTRES unités en réserve : le paramètre est par unité.
    other = _reserve_squad(eng, deep_strike=False)
    assert other not in ingress_eligible_units(gs)


def test_set_reserves_arrival_round_rejects_round_zero():
    from engine.phase_handlers.movement_handlers import set_reserves_arrival_round

    eng = _engine()
    gs = eng.game_state
    squad_id = next(iter(gs["units_cache"]))
    with pytest.raises(ValueError):
        set_reserves_arrival_round(gs, squad_id, 0)


def test_granted_clearance_changes_the_pool_boundary():
    """20.04 : la distance aux ennemis est un paramètre (Da Jump pose « more than 9\" away »)."""
    from engine.phase_handlers.movement_handlers import (
        ingress_setup_pool, set_reserves_setup_distances,
    )

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    gs["turn"] = 2
    squad_id = _reserve_squad(eng, deep_strike=True)

    pool_8 = ingress_setup_pool(gs, squad_id)
    assert pool_8, "pool vide — test sans portée"
    set_reserves_setup_distances(
        gs, squad_id, edge_distance_inches=None, enemy_clearance_inches=9,
    )
    pool_9 = ingress_setup_pool(gs, squad_id)
    assert pool_9 < pool_8, (
        "exiger plus de 9\" au lieu de plus de 8\" doit RÉTRÉCIR strictement l'aire légale"
    )


def test_granted_edge_distance_widens_or_lifts_the_band():
    from engine.phase_handlers.movement_handlers import (
        ingress_setup_pool, set_reserves_setup_distances,
    )

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    gs["turn"] = 3  # zone adverse ouverte pour tous : on isole la clause de BORD
    squad_id = _reserve_squad(eng, deep_strike=False)

    pool_6 = ingress_setup_pool(gs, squad_id)
    set_reserves_setup_distances(
        gs, squad_id, edge_distance_inches=9, enemy_clearance_inches=8,
    )
    pool_9 = ingress_setup_pool(gs, squad_id)
    assert pool_6 < pool_9, "une bande de 9\" doit contenir strictement celle de 6\""

    set_reserves_setup_distances(
        gs, squad_id, edge_distance_inches=None, enemy_clearance_inches=8,
    )
    pool_anywhere = ingress_setup_pool(gs, squad_id)
    assert pool_9 < pool_anywhere, "`None` = « anywhere on the battlefield », donc tout le plateau"


def test_pool_signature_is_shared_between_units_of_same_parameters():
    """Deux unités de même signature ont EXACTEMENT le même pool.

    C'est l'invariant sur lequel repose le partage du calcul entre toutes les réserves d'un
    joueur : le pool ne dépend pas de l'unité au-delà de son triplet de paramètres.
    """
    from engine.phase_handlers.movement_handlers import (
        ingress_pool_signature, ingress_setup_pool, set_reserves_setup_distances,
    )

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    gs["turn"] = 2
    from engine.phase_handlers.movement_handlers import unit_has_deep_strike

    a = _reserve_squad(eng, deep_strike=False)
    # La 2e escouade doit elle aussi être SANS Deep Strike : la capacité force la bande de bord
    # à `None` et rendrait les deux signatures différentes par construction.
    b = next(
        sid for sid, e in gs["units_cache"].items()
        if int(e["player"]) == 1 and sid != a and not unit_has_deep_strike(gs, sid)
    )
    _force_into_reserves(gs, b)
    # État CONSTRUIT : on impose la même signature aux deux (sans Deep Strike ni l'une ni
    # l'autre, mêmes distances). Sans ça le test dépendrait du roster tiré.
    for sid in (a, b):
        set_reserves_setup_distances(gs, sid, edge_distance_inches=6, enemy_clearance_inches=8)
    assert ingress_pool_signature(gs, a) == ingress_pool_signature(gs, b), (
        "signatures construites identiques — sinon le test ne vérifie rien"
    )
    assert ingress_setup_pool(gs, a) == ingress_setup_pool(gs, b), (
        "même signature -> même pool ; sinon le partage du calcul est faux"
    )


def test_deep_strike_lifts_the_edge_band_in_the_signature():
    from engine.phase_handlers.movement_handlers import ingress_pool_signature

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    gs["turn"] = 2
    deep = _reserve_squad(eng, deep_strike=True)
    plain = _reserve_squad(eng, deep_strike=False)

    edge_deep, _clr_deep, zone_deep = ingress_pool_signature(gs, deep)
    edge_plain, _clr_plain, zone_plain = ingress_pool_signature(gs, plain)
    assert edge_deep is None, "24.09 lève la contrainte de bord"
    assert edge_plain is not None
    assert zone_deep is True, "24.09 ouvre aussi la zone adverse"
    assert zone_plain is False, "fermée avant le 3e round sans Deep Strike"


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


def test_ingress_ends_the_activation():
    """VERROU — après l'arrivée, l'escouade SORT du pool d'activation de la phase.

    Le pool n'est pas reconstruit après chaque action : une arrivée qui ne terminerait pas
    l'activation laisserait l'escouade sélectionnable une seconde fois dans la MÊME phase (donc
    un mouvement en plus, contre 20.04 AFTER MOVING) et empêcherait la phase de se terminer par
    épuisement du pool.
    """
    from engine.phase_handlers.movement_handlers import execute_action, ingress_setup_pool

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    gs["turn"] = 2
    gs["current_player"] = 1
    gs["phase"] = "move"
    squad_id = _reserve_squad(eng, deep_strike=False)
    from engine.phase_handlers.movement_handlers import movement_build_activation_pool

    movement_build_activation_pool(gs)
    assert squad_id in gs["move_activation_pool"], "l'escouade en réserves doit être activable"

    candidates = eng.action_decoder.ingress_slot_candidates(gs, squad_id)
    assert candidates, "aucun candidat d'ingress — test sans portée"
    col, row = candidates[sorted(candidates)[0]]["hex"]
    ok, _res = execute_action(
        gs, _unit(gs, squad_id),
        {"action": "ingress_move", "unitId": squad_id, "destCol": col, "destRow": row},
        gs["config"],
    )
    assert ok
    assert squad_id not in gs["move_activation_pool"], (
        "l'escouade arrivée de réserves doit être retirée du pool d'activation"
    )
    assert (int(gs["units_cache"][squad_id]["col"]), int(gs["units_cache"][squad_id]["row"])) != UNDEPLOYED


def test_ingress_clears_the_preview_but_keeps_the_enemy_keyed_memo():
    """L'arrivée efface l'APERÇU, et ne jette PAS les aires d'ingress mémoïsées.

    Deux contrats distincts, souvent confondus :
    - l'aperçu (jusqu'à 2 286 points de contour) doit disparaître, sinon il reste publié dans
      l'état et resérialisé dans chaque réponse suivante ;
    - le mémo des aires d'arrivée, lui, est indexé sur les positions ENNEMIES. L'unité qui vient
      d'être posée est AMIE : elle ne peut pas le périmer. Le vider coûtait 49 ms de recalcul
      après chaque mouvement, mesuré, pour une entrée qui restait valable.
    """
    from engine.phase_handlers.movement_handlers import (
        INGRESS_POOL_CACHE_KEY, execute_action, movement_build_activation_pool,
        set_ingress_preview_loops,
    )

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    gs["turn"] = 2
    gs["current_player"] = 1
    gs["phase"] = "move"
    squad_id = _reserve_squad(eng, deep_strike=False)
    movement_build_activation_pool(gs)

    set_ingress_preview_loops(gs, squad_id)
    assert gs["move_preview_footprint_mask_loops"], "aperçu non publié — test sans portée"
    assert gs.get(INGRESS_POOL_CACHE_KEY), "mémo de pool vide — test sans portée"

    candidates = eng.action_decoder.ingress_slot_candidates(gs, squad_id)
    col, row = candidates[sorted(candidates)[0]]["hex"]
    ok, _res = execute_action(
        gs, _unit(gs, squad_id),
        {"action": "ingress_move", "unitId": squad_id, "destCol": col, "destRow": row},
        gs["config"],
    )
    assert ok
    assert not gs["move_preview_footprint_mask_loops"], (
        "la bande d'arrivée doit être effacée après la pose"
    )
    assert gs[INGRESS_POOL_CACHE_KEY], (
        "une pose AMIE ne périme aucune aire d'arrivée : la clé du mémo ne porte que les "
        "positions ennemies. Le vider ici était du recalcul pur."
    )
    # Et le mémo reste SERVABLE : la même unité, dans le même état, retrouve son pool sans
    # recalcul (sinon la clé porterait quelque chose que la pose a changé).
    from engine.phase_handlers.movement_handlers import ingress_setup_pool
    from engine.phase_handlers.shared_utils import unit_is_in_strategic_reserves

    other = next(
        (sid for sid in gs["units_cache"] if unit_is_in_strategic_reserves(gs, sid)), None
    )
    if other is not None:
        before_len = len(gs[INGRESS_POOL_CACHE_KEY])
        ingress_setup_pool(gs, other)
        assert len(gs[INGRESS_POOL_CACHE_KEY]) == before_len, (
            "le pool d'une autre réserve devait être servi par le mémo, pas recalculé"
        )


def test_ingress_refreshes_the_enemy_adjacency_caches():
    """VERROU — l'unité qui ARRIVE entre dans le cache d'adjacence de l'adversaire.

    Ces caches sont bâtis une seule fois, à l'ouverture de la phase de mouvement : ils disent à
    chaque joueur où il n'a PAS le droit de finir son déplacement. Une arrivée survenue APRÈS
    cette construction les laissait ignorer l'unité posée, et un mouvement réactif adverse (9",
    déclenché pendant ma propre phase) pouvait se poser dans sa zone d'engagement.
    """
    from engine.phase_handlers.movement_handlers import (
        execute_action, movement_build_activation_pool,
    )
    from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    gs["turn"] = 2
    gs["current_player"] = 1
    gs["phase"] = "move"
    squad_id = _reserve_squad(eng, deep_strike=False)
    movement_build_activation_pool(gs)
    # Caches construits AVANT l'arrivée, comme le fait `movement_phase_start`.
    build_enemy_adjacent_hexes(gs, 2)
    before = set(gs["enemy_adjacent_hexes_player_2"])

    candidates = eng.action_decoder.ingress_slot_candidates(gs, squad_id)
    col, row = candidates[sorted(candidates)[0]]["hex"]
    ok, _res = execute_action(
        gs, _unit(gs, squad_id),
        {"action": "ingress_move", "unitId": squad_id, "destCol": col, "destRow": row},
        gs["config"],
    )
    assert ok
    after = set(gs["enemy_adjacent_hexes_player_2"])
    occupied = set(gs["units_cache"][squad_id]["occupied_hexes"])
    assert occupied, "l'escouade posée doit occuper des cases — test sans portée"
    assert after != before, (
        "le cache d'adjacence de l'adversaire doit changer quand une unité arrive sur le plateau"
    )
    assert after & occupied or after - before, (
        "les cases rendues adjacentes par l'arrivante doivent y figurer"
    )


def test_bounding_radius_encloses_a_square_base():
    """Le rayon englobant doit ENGLOBER : pour un carré, le point extrême est un COIN.

    Ce rayon sert de garde de broad-phase à la clearance de mise en place (20.04) : sous-estimé,
    il écarte sans les tester des cases pourtant à 8" ou moins d'un socle carré.
    """
    import math as _math

    from engine.hex_utils import (
        Socle, _hex_center, _socle_edge_primitives, bounding_radius_norm,
    )

    side = 6
    radius = bounding_radius_norm("square", side)
    socle = Socle(shape="square", base_size=side, col=0, row=0, fp={(0, 0)})
    center_x, center_y = _hex_center(0, 0)
    # Une primitive polygonale est `("p", [sommets], cx, cy, r_circonscrit)` — seuls les deux
    # premiers champs sont lus ici, et l'indexation les isole sans dépendre de la longueur du
    # tuple (un déballage `kind, payload` cassait au jour où le rayon circonscrit y a été ajouté).
    farthest = 0.0
    for primitive in _socle_edge_primitives(socle):
        if primitive[0] != "p":
            continue
        for px, py in primitive[1]:
            farthest = max(farthest, _math.hypot(px - center_x, py - center_y))
    assert farthest > 0.0, "aucun sommet lu — test sans portée"
    assert radius + 1e-9 >= farthest, (
        f"rayon englobant {radius:.3f} < point le plus éloigné du socle {farthest:.3f}"
    )
    # Et il reste SERRÉ : un rayon délirant passerait le test ci-dessus sans rien garantir.
    assert radius <= farthest * 1.01


def test_roster_declared_reserve_survives_unit_construction():
    """VERROU — `create_unit` ne doit pas effacer une réserve déclarée par le roster.

    `initialize_units` reconstruit CHAQUE unité enrichie via `create_unit` : une lecture du seul
    champ brut `strategic_reserves` (absent de l'unité enrichie) remettait silencieusement
    `in_strategic_reserves` à False, et l'unité repartait se déployer normalement.
    """
    from engine.game_state import GameStateManager

    eng = _engine()
    gs = eng.game_state
    source = dict(gs["units"][0])
    source["in_strategic_reserves"] = True
    source["col"], source["row"] = -1, -1

    rebuilt = GameStateManager(gs["config"]).create_unit(source)
    assert rebuilt["in_strategic_reserves"] is True, (
        "la mise en réserve déclarée doit survivre à la reconstruction de l'unité"
    )
    assert rebuilt["deployed_on_turn"] is None


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
    assert squad_id in [str(u["id"]) for u in destroyed]
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
    assert squad_id not in [str(u["id"]) for u in destroyed]
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


# ---------------------------------------------------------------------------
# 20.01 — la phase de TIR ignore les unités hors table (chantier 04c)
# ---------------------------------------------------------------------------
#
# `test_reserve_unit_is_not_a_shooting_target` ci-dessus couvre le cache de LoS. Il ne couvre
# PAS `weapon_availability_check`, qui a sa propre énumération d'ennemis et son propre choix
# d'arme — et c'est là que vivaient les deux trous corrigés au chantier 04c.
#
# ⚠️ PORTÉE EXACTE DE CES DEUX TESTS, à ne pas surestimer : ce sont des tests de NON-RÉGRESSION
# du démarrage de phase en présence d'une unité hors table, PAS des verrous. Vérifié en retirant
# chaque filtre : ils restent VERTS. Raison mesurée : le crash exige que le tireur soit à PORTÉE
# D'ARME du fantôme en (-1,-1), or la zone de déploiement de ce scénario en est à 271-278 subhex
# pour des portées de 120-240. Dans l'épisode qui plantait réellement, le tireur était à ~153.
#
# Le VERROU, lui, est tests/unit/engine/test_off_table_geometry.py (2026-08-05) : il CONSTRUIT la
# géométrie (tireur amené au coin du plateau, donc fantôme à portée) au lieu de l'espérer d'une
# graine. Il couvre aussi la famille ENGAGEMENT, qui ne crashe jamais et rendait un verdict FAUX.


def test_shooting_phase_start_runs_with_a_reserve_enemy():
    """Le démarrage de phase de tir traverse une unité ENNEMIE hors table sans lever.

    Elle est VIVANTE mais sans empreinte : `_is_valid_shooting_target` finissait par appeler
    `min_distance_between_sets` sur un ensemble VIDE (« Cannot compute distance between empty
    sets »), à la première phase de tir de tout épisode où une réserve subsiste.
    """
    from engine.phase_handlers.shooting_handlers import shooting_phase_start

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    shooter_player = int(gs["current_player"])
    enemy_player = 2 if shooter_player == 1 else 1
    # POSÉE : une unité déjà hors table ne prouverait rien (vert vacant).
    target = next(
        sid for sid, e in gs["units_cache"].items()
        if int(e["player"]) == enemy_player and entry_is_on_battlefield_for(gs, sid)
    )
    _force_into_reserves(gs, target)
    # CONSTRUIT : `shooting_phase_start` ne fait le choix d'arme COMPLET (donc le précheck
    # d'ennemis) que si l'unité est adjacente ou a fait un advance — sinon il prend la première
    # arme portée sans regarder personne. Sans cette ligne le test resterait vert avec le défaut.
    for sid, entry in gs["units_cache"].items():
        if int(entry["player"]) == shooter_player:
            gs.setdefault("units_advanced", set()).add(str(sid))

    shooting_phase_start(gs)  # ne doit pas lever

    assert not entry_is_on_battlefield_for(gs, target)


def test_shooting_phase_start_runs_with_a_reserve_shooter():
    """Symétrique : une unité en réserves du joueur COURANT ne choisit pas d'arme.

    Le choix d'arme mesure des distances aux ennemis depuis l'empreinte du TIREUR. Ce cas se
    produit dès que l'agent exerce la décision 20.01 sur sa propre liste, ce qui est légal — le
    masque de déploiement lui ouvre `SQUAD_ACTION_WAIT` pour ça.
    """
    from engine.phase_handlers.shooting_handlers import shooting_phase_start

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    shooter_player = int(gs["current_player"])
    shooter = next(
        sid for sid, e in gs["units_cache"].items()
        if int(e["player"]) == shooter_player and entry_is_on_battlefield_for(gs, sid)
    )
    _force_into_reserves(gs, shooter)
    # CONSTRUIT, même raison que ci-dessus : c'est le choix d'arme complet qui lit l'empreinte
    # du TIREUR, et il n'est atteint qu'après un advance ou au contact.
    gs.setdefault("units_advanced", set()).add(str(shooter))

    shooting_phase_start(gs)  # ne doit pas lever

    assert not entry_is_on_battlefield_for(gs, shooter)


def entry_is_on_battlefield_for(gs: Dict[str, Any], unit_id: str) -> bool:
    from engine.phase_handlers.shared_utils import entry_is_on_battlefield

    return entry_is_on_battlefield(gs["units_cache"][str(unit_id)])


# ---------------------------------------------------------------------------
# Portes de PHASE de l'interface PvP (chantier 04b)
#
# L'UI n'offre le dépôt qu'au déploiement et le retrait qu'au mouvement. Un bouton masqué n'est
# PAS une règle : ces verrous vérifient que le moteur ferme aussi, par le chemin exact que le
# client emprunte (`execute_semantic_action`).
#
# Les assertions portent sur l'EFFET, pas sur le booléen de retour : la phase de commandement
# renvoie `True` pour n'importe quelle action (`command_handlers.execute_action` se contente de
# terminer la phase). Un test qui lirait ce booléen croirait à un dépôt qui n'a pas eu lieu.
# ---------------------------------------------------------------------------


def test_strategic_reserves_deposit_is_refused_outside_the_deployment_phase():
    """20.01 — « instead of setting up » : hors déploiement, il n'y a plus rien à remplacer."""
    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    squad_id = next(sid for sid, e in gs["units_cache"].items() if int(e["player"]) == 1)

    def _rearm_deployment() -> None:
        gs["phase"] = "deployment"
        gs["current_player"] = 1
        gs["deployment_state"]["deployment_complete"] = False
        gs["deployment_state"]["current_deployer"] = 1
        gs["deployment_state"]["deployable_units"][1] = [squad_id]
        _unit(gs, squad_id)["deployed_on_turn"] = None
        _unit(gs, squad_id)["in_strategic_reserves"] = False

    # VERT VACANT : le dépôt ABOUTIT dans sa phase. Sans ce contrôle, les refus ci-dessous
    # passeraient même si l'action n'existait pas du tout.
    _rearm_deployment()
    eng.execute_semantic_action({"action": "deploy_strategic_reserves", "unitId": squad_id})
    assert _unit(gs, squad_id)["in_strategic_reserves"] is True, (
        "le dépôt doit aboutir DANS la phase de déploiement"
    )

    for phase in ("command", "move", "shoot", "charge", "fight"):
        _rearm_deployment()
        gs["phase"] = phase
        eng.execute_semantic_action({"action": "deploy_strategic_reserves", "unitId": squad_id})
        assert _unit(gs, squad_id)["in_strategic_reserves"] is False, (
            f"20.01 : une unité a été mise en réserves depuis la phase {phase}"
        )


def test_ingress_move_is_refused_outside_the_movement_phase():
    """20.04 — « in your Movement phase » : l'arrivée n'existe que là."""
    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    gs["turn"] = 2
    gs["current_player"] = 1
    squad_id = _reserve_squad(eng, deep_strike=False)

    candidates = eng.action_decoder.ingress_slot_candidates(gs, squad_id)
    assert candidates, "aucun candidat d'ingress — test sans portée (VERT VACANT)"
    slot = candidates[sorted(candidates)[0]]
    dest_col, dest_row = int(slot["hex"][0]), int(slot["hex"][1])
    ingress = {
        "action": "ingress_move", "unitId": squad_id,
        "destCol": dest_col, "destRow": dest_row,
    }

    for phase in ("command", "shoot", "charge", "fight"):
        gs["phase"] = phase
        eng.execute_semantic_action(dict(ingress))
        assert _unit(gs, squad_id)["deployed_on_turn"] is None, (
            f"20.04 : l'escouade a été POSÉE depuis la phase {phase}"
        )
        assert _unit(gs, squad_id)["in_strategic_reserves"] is True

    # Contrôle inverse, MÊME action et MÊME destination : elle aboutit en phase de mouvement.
    from engine.phase_handlers.movement_handlers import movement_phase_start

    gs["phase"] = "move"
    gs["current_player"] = 1
    # Les phases traversées ci-dessus ont pu faire avancer le round (cascade de fin de phase) :
    # on le repose à 2 pour que l'arrivée reste comparable à celles des autres tests.
    gs["turn"] = 2
    movement_phase_start(gs)
    ok_move, res_move = eng.execute_semantic_action(dict(ingress))
    assert ok_move, f"l'arrivée doit aboutir en phase de mouvement (retour : {res_move})"
    assert _unit(gs, squad_id)["in_strategic_reserves"] is False
    assert _unit(gs, squad_id)["deployed_on_turn"] == 2


def test_ingress_preview_loops_leave_the_shared_preview_channel_untouched():
    """Le CALCUL des contours d'arrivée n'écrit pas dans le canal d'aperçu du mouvement.

    `set_ingress_preview_loops` PUBLIE la bande dans ``move_preview_footprint_mask_loops`` ;
    `ingress_preview_loops` la RETOURNE sans rien écrire. L'API sert l'aperçu d'arrivée en lecture
    pure (aucune resérialisation de l'état), elle doit donc emprunter la seconde : une bande
    laissée dans le canal repartirait dans toutes les réponses suivantes et le client la peindrait
    comme un aperçu de mouvement — y compris après que le joueur a annulé son arrivée.
    """
    from engine.phase_handlers.movement_handlers import ingress_preview_loops

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    gs["turn"] = 2
    gs["current_player"] = 1
    squad_id = _reserve_squad(eng, deep_strike=False)

    # Aperçu de MOUVEMENT déjà affiché : c'est lui qui doit survivre intact.
    sentinel = [[1.0, 2.0, 3.0, 4.0, 5.0, 6.0]]
    gs["move_preview_footprint_mask_loops"] = sentinel

    loops = ingress_preview_loops(gs, squad_id)
    assert loops, "VERT VACANT : le calcul doit rendre de vrais contours"
    assert gs["move_preview_footprint_mask_loops"] is sentinel, (
        "la bande d'arrivée a écrasé l'aperçu de mouvement du joueur"
    )

    # Et quand AUCUN aperçu n'était affiché, la clé doit rester absente : la réintroduire
    # rallumerait le calque de contour côté client.
    #
    # Le mémo est VIDÉ avant ce second appel. Sans cette purge, `ingress_preview_loops` sort sur
    # `cache_key in loops_cache` et n'exécute AUCUNE ligne du corps : l'assertion qui suit ne
    # pourrait pas échouer, même en remettant la publication dans la fonction — vert vacant.
    from engine.phase_handlers.movement_handlers import INGRESS_LOOPS_CACHE_KEY

    del gs["move_preview_footprint_mask_loops"]
    gs.pop(INGRESS_LOOPS_CACHE_KEY, None)
    ingress_preview_loops(gs, squad_id)
    assert "move_preview_footprint_mask_loops" not in gs, (
        "la bande d'arrivée est restée dans le canal d'aperçu partagé"
    )


def test_ingress_preview_loops_memo_drops_unreachable_entries():
    """Le mémo des CONTOURS ne garde que l'empreinte ennemie COURANTE.

    Les trois mémos d'ingress vivent dans le game_state et ne sont volontairement pas vidés après
    chaque mouvement (`_invalidate_all_destination_pools_after_movement` : leur clé porte les
    positions ennemies, donc un mouvement AMI ne les périme pas). Celui des contours ne se purgeait
    pas du tout et accumulait un jeu de contours par configuration ennemie traversée dans la partie.

    Il se purge par EMPREINTE et non par une borne de taille comme ses deux frères : à 0,99 s le
    recalcul, un `clear()` en bloc jetterait aussi les entrées encore atteignables — dont celles
    que `precompute_ingress_pools` vient d'écrire sous l'empreinte courante.
    """
    from engine.phase_handlers.movement_handlers import (
        INGRESS_LOOPS_CACHE_KEY,
        ingress_preview_loops,
    )

    eng, gs, squad_id = _ingress_ready_engine()
    enemy = next(e for e in gs["units_cache"].values() if int(e["player"]) == 2)
    enemy.pop("occupied_hexes_by_model", None)  # mono-fig : l'ancre porte l'empreinte

    fingerprints = set()
    for _step in range(16):
        # Chaque itération DÉPLACE l'ennemi → nouvelle empreinte → nouvelle clé de mémo.
        enemy["col"] = int(enemy["col"]) + 1
        assert ingress_preview_loops(gs, squad_id), "VERT VACANT : aucun contour calculé"
        keys = list(gs[INGRESS_LOOPS_CACHE_KEY].keys())
        fingerprints.update(k[2] for k in keys)
        assert len(keys) == 1, (
            f"une entrée d'une empreinte ennemie périmée est restée : {len(keys)} entrées"
        )

    assert len(fingerprints) == 16, (
        "la fixture n'a pas changé l'empreinte à chaque tour — le test ne prouve rien"
    )


def test_ingress_preview_loops_memo_keeps_the_entries_of_the_current_fingerprint():
    """…et il ne jette PAS les entrées encore atteignables : deux signatures sous une même
    empreinte coexistent. C'est ce que le réchauffage (`precompute_ingress_pools`) écrit, et ce
    qu'un `clear()` par borne de taille aurait pu effacer avant le premier clic du joueur."""
    from engine.phase_handlers.movement_handlers import (
        INGRESS_LOOPS_CACHE_KEY,
        ingress_pool_signature,
        ingress_preview_loops,
    )

    eng, gs, squad_id = _ingress_ready_engine()
    other_id = _reserve_squad(eng, deep_strike=True)
    assert ingress_pool_signature(gs, squad_id) != ingress_pool_signature(gs, other_id), (
        "les deux escouades partagent leur signature : le test ne prouve rien"
    )
    ingress_preview_loops(gs, squad_id)
    ingress_preview_loops(gs, other_id)
    assert len(gs[INGRESS_LOOPS_CACHE_KEY]) == 2, (
        "la seconde signature a évincé la première alors que l'empreinte n'a pas changé"
    )


# ---------------------------------------------------------------------------
# 20.04 — l'arrivée s'ÉDITE comme un déploiement (plan par-figurine, puis commit)
# ---------------------------------------------------------------------------


def _ingress_ready_engine():
    """Moteur avec une escouade J1 en réserves, au tour 2, phase de mouvement du J1."""
    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    gs["turn"] = 2
    gs["current_player"] = 1
    gs["phase"] = "move"
    squad_id = _reserve_squad(eng, deep_strike=False)
    return eng, gs, squad_id


def test_placement_pool_of_a_reserve_squad_is_its_arrival_area_not_the_deployment_zone():
    """LE point unique : les primitives de placement voient l'aire 20.04 pour une réserve.

    Sans cela, le plan que le joueur édite serait contraint par la zone de DÉPLOIEMENT, qui n'a
    aucun rapport avec l'aire d'arrivée — l'écran proposerait des cases que le commit refuse.
    """
    from engine.phase_handlers.deployment_handlers import placement_pool_for_squad
    from engine.phase_handlers.movement_handlers import ingress_setup_pool

    eng, gs, squad_id = _ingress_ready_engine()
    pool = placement_pool_for_squad(gs, squad_id)
    assert pool is not None, "une escouade EN RÉSERVES n'est pas posée dans la zone de déploiement"
    assert set(pool) == set(ingress_setup_pool(gs, squad_id))

    # Une escouade SUR LA TABLE garde la zone de déploiement (None = pas de substitution).
    on_table = [
        sid for sid in gs["units_cache"]
        if sid != squad_id and _unit(gs, sid)["deployed_on_turn"] is not None
    ]
    assert on_table, "aucune escouade posée — test sans portée"
    assert placement_pool_for_squad(gs, on_table[0]) is None


def test_ingress_formation_and_preview_are_confined_to_the_arrival_area():
    """`deploy_generate_formation` + `deploy_preview` sur une réserve : bornés par l'aire 20.04."""
    from engine.phase_handlers.deployment_handlers import (
        deployment_generate_formation_action,
        deployment_preview_action,
    )
    from engine.phase_handlers.movement_handlers import ingress_setup_pool

    eng, gs, squad_id = _ingress_ready_engine()
    pool = ingress_setup_pool(gs, squad_id)
    assert len(pool) > 100, "aire d'arrivée quasi vide — test sans portée"
    anchor = sorted(pool)[len(pool) // 2]

    ok, res = deployment_generate_formation_action(
        gs, {"unitId": squad_id, "destCol": anchor[0], "destRow": anchor[1]}
    )
    assert ok, res
    plan = res["plan"]
    assert plan, "formation vide"
    for _mid, col, row, _lv in plan:
        assert (int(col), int(row)) in pool, (
            f"figurine placée en ({col},{row}), hors de l'aire d'arrivée 20.04"
        )

    ok, prev = deployment_preview_action(gs, {"unitId": squad_id, "plan": plan})
    assert ok and prev["can_validate"], prev

    # Le MÊME plan poussé d'une case hors aire doit être refusé par le preview : c'est ce que le
    # joueur verra en rouge s'il pousse une figurine trop loin.
    outside = next(
        (c, r)
        for c in range(int(gs["board_cols"]))
        for r in range(int(gs["board_rows"]))
        if (c, r) not in pool
    )
    moved = [list(plan[0]) ] + [list(e) for e in plan[1:]]
    moved[0][1], moved[0][2] = outside[0], outside[1]
    ok, prev_bad = deployment_preview_action(gs, {"unitId": squad_id, "plan": moved})
    assert ok
    assert not prev_bad["can_validate"], "une figurine hors aire d'arrivée doit passer au rouge"


def test_ingress_commit_applies_the_edited_plan_and_ends_the_activation():
    """VERROU de bout en bout : le plan ÉDITÉ par le joueur arrive, verrou 20.04 compris.

    C'est le jumeau de `test_ingress_places_every_model_and_locks_further_moves` pour le siège
    humain : mêmes conséquences (posée, plus en réserves, verrouillée, hors du pool d'activation)
    mais à partir d'un plan fourni par le client, pas d'une ancre.
    """
    from engine.phase_handlers.deployment_handlers import deployment_generate_formation_action
    from engine.phase_handlers.movement_handlers import (
        execute_action, ingress_setup_pool, unit_ingress_move_locked,
    )

    eng, gs, squad_id = _ingress_ready_engine()
    pool = ingress_setup_pool(gs, squad_id)
    anchor = sorted(pool)[len(pool) // 2]
    ok, res = deployment_generate_formation_action(
        gs, {"unitId": squad_id, "destCol": anchor[0], "destRow": anchor[1]}
    )
    assert ok, res
    plan = res["plan"]

    unit = _unit(gs, squad_id)
    gs.setdefault("move_activation_pool", []).append(squad_id)
    ok, out = execute_action(
        gs, unit, {"action": "ingress_commit", "unitId": squad_id, "plan": plan}, eng.config
    )
    assert ok, out

    assert unit["in_strategic_reserves"] is False
    assert unit["deployed_on_turn"] == 2
    for mid in gs["squad_models"][squad_id]:
        model = gs["models_cache"][mid]
        assert (int(model["col"]), int(model["row"])) != UNDEPLOYED
        assert (int(model["col"]), int(model["row"])) in pool
    assert unit_ingress_move_locked(gs, squad_id), "verrou 20.04 absent après un commit édité"
    assert squad_id not in gs["move_activation_pool"], (
        "l'activation n'est pas terminée : l'escouade pourrait rebouger le même tour"
    )


def test_ingress_commit_refuses_a_plan_that_leaves_the_arrival_area():
    """Le client n'est pas cru sur parole : le plan est revalidé contre l'aire du tour."""
    from engine.phase_handlers.deployment_handlers import deployment_generate_formation_action
    from engine.phase_handlers.movement_handlers import execute_action, ingress_setup_pool

    eng, gs, squad_id = _ingress_ready_engine()
    pool = ingress_setup_pool(gs, squad_id)
    anchor = sorted(pool)[len(pool) // 2]
    ok, res = deployment_generate_formation_action(
        gs, {"unitId": squad_id, "destCol": anchor[0], "destRow": anchor[1]}
    )
    assert ok, res
    plan = [list(e) for e in res["plan"]]
    outside = next(
        (c, r)
        for c in range(int(gs["board_cols"]))
        for r in range(int(gs["board_rows"]))
        if (c, r) not in pool
    )
    plan[0][1], plan[0][2] = outside[0], outside[1]

    unit = _unit(gs, squad_id)
    ok, out = execute_action(
        gs, unit, {"action": "ingress_commit", "unitId": squad_id, "plan": plan}, eng.config
    )
    assert not ok, "un plan hors aire d'arrivée doit être REFUSÉ, pas appliqué"
    assert unit["in_strategic_reserves"] is True, "l'escouade reste en réserves après un refus"


def test_squad_destinations_erosion_matches_the_naive_definition():
    """L'érosion vectorisée du pool de suivi de bloc rend EXACTEMENT le test case-par-case.

    Oracle indépendant, écrit ici en toutes lettres : « une ancre est retenue si et seulement si
    l'ancre translatée de chaque offset du bloc appartient au pool ». La version de production
    calcule la même chose par décalages de grille — c'est une accélération (2,3 s → moins de 0,1 s
    sur l'aire d'arrivée d'une unité Deep Strike), donc elle doit rendre le MÊME ensemble, pas un
    ensemble « proche ». Vérifié sur les deux aires réelles : zone de déploiement ET aire 20.04,
    parce que c'est la MÊME fonction qui sert aux deux.
    """
    from engine.hex_utils import offset_to_cube
    from engine.phase_handlers.deployment_handlers import (
        _deploy_pool_set, _model_footprint, deployment_build_squad_destinations_pool,
        placement_pool_for_squad,
    )

    def naive(gs, pool_set, plan):
        models_cache = gs["models_cache"]
        combined = set()
        for mid, c, r in plan:
            m = models_cache.get(str(mid))
            if m is not None:
                combined.update(_model_footprint(gs, m, int(c), int(r)))
        rx, ry, rz = offset_to_cube(int(plan[0][1]), int(plan[0][2]))
        offsets = [
            tuple(a - b for a, b in zip(offset_to_cube(int(cc), int(rr)), (rx, ry, rz)))
            for cc, rr in combined
        ]
        pool_cube = {offset_to_cube(int(c), int(r)) for c, r in pool_set}
        out = set()
        for cc, rr in pool_set:
            bx, by, bz = offset_to_cube(int(cc), int(rr))
            if all((bx + ox, by + oy, bz + oz) in pool_cube for ox, oy, oz in offsets):
                out.add((int(cc), int(rr)))
        return out

    # (1) Zone de DÉPLOIEMENT — le siège historique de cette fonction.
    eng = _engine()
    gs = eng.game_state
    _du = gs["deployment_state"]["deployable_units"]
    pending = _du.get(1, _du.get("1"))
    squad_id = str(pending[0])
    mids = gs["squad_models"][squad_id]
    zone = sorted(_deploy_pool_set(gs, 1))
    assert len(zone) > 1000, "zone de déploiement trop petite — test sans portée"
    anchor = zone[len(zone) // 2]
    plan = [(m, anchor[0] + i, anchor[1]) for i, m in enumerate(mids)]
    got = {tuple(d) for d in deployment_build_squad_destinations_pool(gs, plan)["destinations"]}
    assert got, "VERT VACANT : aucune ancre retenue, l'égalité ne prouverait rien"
    assert got == naive(gs, set(zone), plan)

    # (2) Aire d'ARRIVÉE 20.04 (Deep Strike : la plus grande, celle qui a motivé l'accélération).
    eng2 = _engine()
    _drive_deployment(eng2)
    gs2 = eng2.game_state
    gs2["turn"] = 3
    gs2["current_player"] = 1
    gs2["phase"] = "move"
    sid2 = _reserve_squad(eng2, deep_strike=True)
    arrival_area = placement_pool_for_squad(gs2, sid2)
    assert arrival_area is not None, "escouade en réserves : l'aire d'arrivée 20.04 doit exister"
    area = sorted(arrival_area)
    assert len(area) > 10000, "aire d'arrivée trop petite — test sans portée"
    a2 = area[len(area) // 2]
    mids2 = gs2["squad_models"][sid2]
    plan2 = [(m, a2[0] + i, a2[1]) for i, m in enumerate(mids2)]
    got2 = {tuple(d) for d in deployment_build_squad_destinations_pool(gs2, plan2)["destinations"]}
    assert got2, "VERT VACANT : aucune ancre retenue sur l'aire d'arrivée"
    assert got2 == naive(gs2, set(area), plan2)


# ---------------------------------------------------------------------------
# JOURNALISATION (step.log) — trou réparé le 2026-08-12
# ---------------------------------------------------------------------------


def test_timeout_destruction_emits_an_action_log_entry():
    """VERROU : supprimer l'`append_action_log` de `destroy_unarrived_strategic_reserves` rend
    ce test ROUGE. Sans ce log, step.log ne porte aucune trace de la mort et l'analyzer ignore
    des escouades entières dans ses ratios d'attrition."""
    from engine.w40k_core import destroy_unarrived_strategic_reserves

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    gs["action_logs"] = []
    gs["action_log_seq"] = 0
    squad_id = _reserve_squad(eng, deep_strike=True)
    gs["turn"] = 3

    destroy_unarrived_strategic_reserves(gs)

    entries = [e for e in gs["action_logs"] if e.get("type") == "strategic_reserves_timeout"]
    assert len(entries) == 1, "la destruction 20.04 doit produire UNE entree d'action_log par escouade"
    e = entries[0]
    assert e["unitId"] == squad_id
    assert e["player"] in (1, 2)
    assert e["turn"] == 3
    assert isinstance(e["removed_models"], list) and len(e["removed_models"]) > 0


def test_timeout_no_log_when_no_unit_qualifies():
    """Aucune escouade en réserves non repositionnée → aucune entrée."""
    from engine.w40k_core import destroy_unarrived_strategic_reserves

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    gs["action_logs"] = []
    gs["action_log_seq"] = 0
    gs["turn"] = 3

    destroy_unarrived_strategic_reserves(gs)

    assert not any(
        e.get("type") == "strategic_reserves_timeout" for e in gs["action_logs"]
    ), "sans unité en réserves, aucun log ne doit être émis"
