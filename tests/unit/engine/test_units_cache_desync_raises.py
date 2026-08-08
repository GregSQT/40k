"""Desynchronisation `units` / `units_cache` : la geometrie LEVE au lieu d'inventer une empreinte.

Ce que ce fichier verrouille (tranche T1 de
`Documentation/Implémentation/Implémenté/replis_units_cache_2026-08-05.md`, « Forme A ») : sept lectures de
`units_cache` repondaient a l'absence par `entry_footprint(x) if x else {(col, row)}`, c'est-a-dire
en mesurant l'unite sur son ANCRE SEULE. Rien ne crashait ; l'adjacence de melee, la zone
d'engagement du move et la ligne de vue de tir rendaient simplement un verdict calcule sur une
geometrie qui n'est pas la vraie.

L'etat est BATI a la main : une desynchronisation ne se produit par definition sur aucune
trajectoire saine, donc aucune graine ne l'obtient. Chaque cas retire l'entree de `units_cache`
tout en gardant l'unite vivante cote appelant — exactement la panne que le repli masquait.

Le message est assert avec le NOM DU SITE : un `KeyError` nu prouverait seulement qu'une cle
manque quelque part, pas que la ligne visee est celle atteinte.

PORTEE BORNEE — un huitieme site n'est PAS ici. Dans `_is_valid_shooting_target`, la lecture de la
CIBLE est precedee de `is_unit_alive(target_id)` (shooting_handlers.py:2292), qui traite l'absence
du cache comme « morte » et rend False. C'est un refus METIER legitime, et il rend le `raise` de la
cible statiquement inatteignable : la preuve y est statique, pas testable.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

ACTING = 1
FOE = 2


def _entry(col: int, row: int, player: int) -> Dict[str, Any]:
    return {
        "col": col,
        "row": row,
        "player": player,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 1,
        "orientation": 0,
        "occupied_hexes": {(col, row)},
    }


@pytest.fixture
def gs() -> Dict[str, Any]:
    return {
        "inches_to_subhex": 1,
        "units_cache": {
            "mover": _entry(5, 5, ACTING),
            "ennemi_pose": _entry(6, 5, FOE),
        },
        # EZ pre-dilatee lue par `move_anchor_violates_engagement_clearance` en geometrie hex :
        # les voisins de l'ennemi en (6,5). (5,5) en fait partie, donc le mover y est engage.
        "enemy_adjacent_hexes_player_1": {(5, 5), (7, 5), (6, 4), (6, 6), (5, 4), (5, 6)},
        "config": {
            "game_rules": {
                "engagement_zone": 1,
                "engagement_zone_vertical": 5,
                "max_base_size_hex": 35,
                "pile_in_target_range": 3,
            },
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
    }


def _mover() -> Dict[str, Any]:
    return {"id": "mover", "player": ACTING}


def test_fight_hex_adjacency_raises_on_a_desynced_cache(gs: Dict[str, Any]) -> None:
    """`_fight_unit_is_hex_adjacent_to_enemy_footprint` : le repli rendait « colle » depuis l'ancre."""
    from engine.phase_handlers.fight_handlers import (
        _fight_unit_is_hex_adjacent_to_enemy_footprint,
    )

    # Temoin : cache intact, la sonde MESURE (l'ennemi en (6,5) touche le mover en (5,5)).
    assert _fight_unit_is_hex_adjacent_to_enemy_footprint(gs, _mover()) is True

    del gs["units_cache"]["mover"]
    with pytest.raises(KeyError, match="_fight_unit_is_hex_adjacent_to_enemy_footprint"):
        _fight_unit_is_hex_adjacent_to_enemy_footprint(gs, _mover())


def test_fight_closest_enemy_snapshot_raises_on_a_desynced_cache(gs: Dict[str, Any]) -> None:
    """`_fight_pile_in_closest_enemy_snapshot` : le repli faussait d_min ET la liste des plus proches."""
    from engine.phase_handlers.fight_handlers import (
        _fight_pile_in_closest_enemy_snapshot,
    )

    d_min, ids = _fight_pile_in_closest_enemy_snapshot(gs, _mover())
    assert (d_min, ids) == (1, ["ennemi_pose"])

    del gs["units_cache"]["mover"]
    with pytest.raises(KeyError, match="_fight_pile_in_closest_enemy_snapshot"):
        _fight_pile_in_closest_enemy_snapshot(gs, _mover())


def test_movement_engagement_zone_raises_on_a_desynced_cache(gs: Dict[str, Any]) -> None:
    """`_is_in_enemy_engagement_zone` : le repli decidait la FUITE sur une empreinte inventee."""
    from engine.phase_handlers.movement_handlers import _is_in_enemy_engagement_zone

    assert _is_in_enemy_engagement_zone(gs, _mover()) is True

    del gs["units_cache"]["mover"]
    with pytest.raises(KeyError, match="_is_in_enemy_engagement_zone"):
        _is_in_enemy_engagement_zone(gs, _mover())


def test_shooting_firable_target_raises_on_a_desynced_cache(gs: Dict[str, Any]) -> None:
    """`_unit_has_firable_target` : le repli mesurait la portee depuis l'ancre du tireur."""
    from engine.phase_handlers.shooting_handlers import _unit_has_firable_target

    del gs["units_cache"]["mover"]
    with pytest.raises(KeyError, match="_unit_has_firable_target"):
        _unit_has_firable_target(gs, _mover(), False, 12)


def test_shooting_valid_target_raises_on_a_desynced_shooter(gs: Dict[str, Any]) -> None:
    """`_is_valid_shooting_target` (volet TIREUR) : le repli mesurait portee et LoS depuis l'ancre.

    La CIBLE est vivante : sans cela `is_unit_alive` rendrait False avant la lecture, et le test
    passerait sans rien atteindre.
    """
    from engine.phase_handlers.shooting_handlers import _is_valid_shooting_target

    shooter = _mover()
    target = {"id": "ennemi_pose", "player": FOE}
    del gs["units_cache"]["mover"]
    with pytest.raises(KeyError, match="_is_valid_shooting_target/shooter"):
        _is_valid_shooting_target(gs, shooter, target)


# --- Jumeau hors des quatre modules de phase : les heuristiques de bots ------------------------
# `ai/evaluation_bots.py` portait SIX fois le meme motif, hors de l'inventaire du document (qui
# n'a balaye que les modules de phase). Deux de ces six sites sont atteignables : les quatre
# autres sont precedes d'un `is_unit_alive`, qui rend l'absence du cache impossible a atteindre.


def _bot_gs() -> Dict[str, Any]:
    return {
        "inches_to_subhex": 1,
        "units": [
            {"id": "mover", "player": ACTING, "CC_WEAPONS": [], "RNG_WEAPONS": []},
            {"id": "ennemi_pose", "player": FOE, "CC_WEAPONS": [], "RNG_WEAPONS": []},
        ],
        "units_cache": {"ennemi_pose": _entry(6, 5, FOE)},
    }


def test_defensive_bot_threat_count_raises_on_a_desynced_cache() -> None:
    """`DefensiveBot._count_nearby_threats` : le repli comptait les menaces depuis la DATASHEET."""
    from ai.evaluation_bots import DefensiveBot

    with pytest.raises(KeyError, match="_count_nearby_threats"):
        DefensiveBot(randomness=0.0)._count_nearby_threats(
            {"id": "mover", "player": ACTING, "col": 5, "row": 5}, _bot_gs()
        )


def test_tactical_bot_nearest_enemy_raises_on_a_desynced_cache() -> None:
    """`TacticalBot._find_nearest_enemy` : idem, et le choix de destination en decoulait."""
    from ai.evaluation_bots import TacticalBot

    with pytest.raises(KeyError, match="_find_nearest_enemy"):
        TacticalBot(randomness=0.0)._find_nearest_enemy(
            {"id": "mover", "player": ACTING, "col": 5, "row": 5}, _bot_gs()
        )


# --- T2 / T3 : formes B, C et D ----------------------------------------------------------------
# Mêmes contrats, mêmes preuves : ces sites répondaient à l'absence par un VERDICT DE RÈGLE
# (« pas engagé », « pas ciblable », « pas de plan ») au lieu de lever. Ne sont testés ici que les
# sites ATTEIGNABLES ; ceux que garde un `is_unit_alive` / `require_unit_position` / une validation
# d'éligibilité amont ont une preuve statique, consignée dans le document du chantier.


def test_squads_are_engaged_raises_on_a_desynced_cache(gs: Dict[str, Any]) -> None:
    """`_squads_are_engaged` : un False effaçait le malus 10.06 [CLOSE-QUARTERS]."""
    from engine.phase_handlers.shared_utils import _squads_are_engaged

    assert _squads_are_engaged(gs, "mover", "ennemi_pose") is True
    del gs["units_cache"]["mover"]
    with pytest.raises(KeyError, match="_squads_are_engaged/a"):
        _squads_are_engaged(gs, "mover", "ennemi_pose")


def test_model_can_fight_target_raises_on_a_desynced_cache(gs: Dict[str, Any]) -> None:
    """`_model_can_fight_target` : un False sortait sous « hors portee/engagement »."""
    from engine.phase_handlers.fight_handlers import _model_can_fight_target

    del gs["units_cache"]["ennemi_pose"]
    with pytest.raises(KeyError, match="_model_can_fight_target"):
        _model_can_fight_target(
            gs, {"col": 5, "row": 5, "level": 0}, "mover", "ennemi_pose"
        )


def test_closest_tier_ids_raises_on_a_desynced_cache(gs: Dict[str, Any]) -> None:
    """`_fight_pile_in_closest_tier_ids` : les DEUX sites (unité, puis cible déclarée)."""
    from engine.phase_handlers.fight_handlers import _fight_pile_in_closest_tier_ids

    assert _fight_pile_in_closest_tier_ids(gs, _mover(), ["ennemi_pose"]) == ["ennemi_pose"]

    with pytest.raises(KeyError, match="_fight_pile_in_closest_tier_ids/target"):
        _fight_pile_in_closest_tier_ids(gs, _mover(), ["fantome"])

    del gs["units_cache"]["mover"]
    with pytest.raises(KeyError, match="_fight_pile_in_closest_tier_ids"):
        _fight_pile_in_closest_tier_ids(gs, _mover(), ["ennemi_pose"])


def test_pile_in_destinations_raises_on_a_desynced_target(gs: Dict[str, Any]) -> None:
    """`pile_in_move_destinations_12_03` : une cible déclarée disparaissait du palier WHILE."""
    from engine.phase_handlers.fight_handlers import pile_in_move_destinations_12_03

    # L'ennemi POSÉ est au contact : la garde « figurines collées » sort avant la mesure. On
    # l'éloigne pour que la fonction atteigne réellement la boucle de cibles.
    gs["units_cache"]["ennemi_pose"] = _entry(9, 5, FOE)
    with pytest.raises(KeyError, match="pile_in_move_destinations_12_03/target"):
        pile_in_move_destinations_12_03(gs, _mover(), ["fantome"])


def test_strictly_closer_raises_on_a_desynced_tier(gs: Dict[str, Any]) -> None:
    """`_fight_pile_in_new_fp_strictly_closer_to_closest_tier` : sauter une empreinte relâchait
    la contrainte WHILE 12.03."""
    from engine.phase_handlers.fight_handlers import (
        _fight_pile_in_new_fp_strictly_closer_to_closest_tier,
    )

    with pytest.raises(KeyError, match="_fight_pile_in_new_fp_strictly_closer"):
        _fight_pile_in_new_fp_strictly_closer_to_closest_tier(
            gs, {(5, 5)}, 3, ["fantome"]
        )


def test_ai_pile_in_destination_raises_on_a_desynced_tier(gs: Dict[str, Any]) -> None:
    """`_ai_select_pile_in_destination` : une cible du palier disparaissait du tri."""
    from engine.phase_handlers.fight_handlers import _ai_select_pile_in_destination

    with pytest.raises(KeyError, match="_ai_select_pile_in_destination"):
        _ai_select_pile_in_destination(gs, _mover(), [(6, 6)], 2, ["fantome"])


def test_shoot_engagement_blocks_target_raises_on_a_desynced_cache(gs: Dict[str, Any]) -> None:
    """`_shoot_engagement_blocks_target` rend « le tir est INTERDIT » : son repli AUTORISAIT le
    tir en sautant les contrôles 04.02 et 10.06."""
    from engine.phase_handlers.shared_utils import _shoot_engagement_blocks_target

    with pytest.raises(KeyError, match="_shoot_engagement_blocks_target/target"):
        _shoot_engagement_blocks_target(
            gs, "mover", "fantome", False, {"col": 5, "row": 5}, False
        )


def test_check_if_melee_can_charge_raises_on_a_desynced_cache(gs: Dict[str, Any]) -> None:
    """`check_if_melee_can_charge` : l'absence était fondue dans le refus « hors table » (20.01)."""
    from engine.phase_handlers.shared_utils import check_if_melee_can_charge

    gs["current_player"] = ACTING
    gs["units"] = [{"id": "mover", "player": ACTING}, {"id": "ennemi_pose", "player": FOE}]
    with pytest.raises(KeyError, match="check_if_melee_can_charge"):
        check_if_melee_can_charge({"id": "fantome"}, gs)
