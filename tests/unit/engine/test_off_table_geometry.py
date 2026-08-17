"""Unités HORS TABLE — aucun chemin géométrique ne les mesure (20.01, `entry_is_on_battlefield`).

Une unité hors table (réserves stratégiques 20.01, ou attente de déploiement actif) est VIVANTE,
présente dans ``units_cache``, à la sentinelle ``(-1,-1)``, avec ``occupied_hexes`` VIDE mais
``occupied_hexes_by_model`` PEUPLÉ de ``(-1,-1)`` par figurine. Deux familles de défauts en
découlaient :

- **DISTANCE** : l'empreinte vide atteint ``min_distance_between_sets`` → « Cannot compute distance
  between empty sets ». Bruyant.
- **ENGAGEMENT** : la carte par-figurine peuplée fait passer la mesure par le chemin 3D, qui rend
  un verdict à la position ``(-1,-1)``. MESURÉ le 2026-08-05 à x1/hex (EZ = 2) : le fantôme
  ressortait ENGAGÉ avec toute unité réelle en ``(0,0)``. Aucun crash, verdict FAUX — plus
  dangereux que la première.

Ce fichier verrouille les DEUX, plus le contrat des primitives :

- ``entry_footprint`` et ``entries_in_engagement_zone`` LÈVENT sur une entrée hors table (une
  mesure n'a pas de réponse juste pour une unité sans position) ;
- ``unit_within_engagement_zone_footprints`` rend ``False`` (le prédicat « est-elle engagée ? »,
  lui, a une réponse de RÈGLE) ;
- ``enemy_entries_on_battlefield`` / ``entries_on_battlefield`` les écartent, et c'est ce qui
  protège les ~130 sites de mesure du moteur.

⚠️ PIÈGE GÉOMÉTRIQUE (vert vacant). La sentinelle ``(-1,-1)`` est à ~274 subhex de la zone de
déploiement de la fixture, donc hors de toute portée d'arme (120-240) : un test qui met une unité
en réserves SANS RIEN D'AUTRE reste VERT avec le défaut, parce que le fantôme n'est jamais mesuré.
Les tests de ce fichier CONSTRUISENT donc la géométrie : un tireur réel amené au contact de
l'origine du plateau, là où le fantôme est réellement à portée.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Set, Tuple

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCENARIO = (
    PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent" / "scenarios" / "training"
    / "reserves_20_fixture1.json"
)


# ---------------------------------------------------------------------------
# Entrées-cache construites à la main : le contrat des primitives, sans moteur
# ---------------------------------------------------------------------------


def _entry(col: int, row: int, player: int, *, model_ids: Tuple[str, ...] = ("m0",)) -> Dict[str, Any]:
    """Entrée ``units_cache`` FIDÈLE à ce que produit le moteur, y compris hors table.

    Hors table, le moteur écrit `occupied_hexes` VIDE mais `occupied_hexes_by_model` et
    `floor_height_by_model` PEUPLÉS de la sentinelle — c'est ce qui envoyait la mesure sur le
    chemin 3D. Un stub qui les laisserait vides ne reproduirait pas le défaut.
    """
    on_table = col >= 0
    occupied: Set[Tuple[int, int]] = {(col, row)} if on_table else set()
    return {
        "id": f"u{player}",
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": 10,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 2.5,
        "occupied_hexes": occupied,
        "occupied_hexes_by_model": {mid: (col, row) for mid in model_ids},
        "floor_height_by_model": {mid: 0.0 for mid in model_ids},
    }


def test_entry_footprint_refuses_an_off_table_entry():
    from engine.spatial_relations import entry_footprint

    with pytest.raises(ValueError, match="HORS TABLE"):
        entry_footprint(_entry(-1, -1, player=2))


def test_entry_footprint_still_returns_the_footprint_on_table():
    """Vert vacant : la primitive doit RENDRE quelque chose sur une entrée normale."""
    from engine.spatial_relations import entry_footprint

    assert entry_footprint(_entry(4, 7, player=1)) == {(4, 7)}


def test_pairwise_engagement_refuses_to_measure_the_ghost():
    """Le cœur du défaut ENGAGEMENT : sans ce refus, la paire rendait True.

    C'est le verrou de la mesure : ``(-1,-1)`` est à distance hex 1 de ``(0,0)``, donc sous une
    EZ de 2 le chemin 3D concluait « engagées ». Retirer ``require_entry_on_battlefield`` de
    ``entries_in_engagement_zone`` rend ce test ROUGE (il retourne True au lieu de lever).
    """
    from engine.spatial_relations import entries_in_engagement_zone

    ghost = _entry(-1, -1, player=2)
    real = _entry(0, 0, player=1)
    for first, second in ((ghost, real), (real, ghost), (ghost, _entry(-1, -1, player=1))):
        with pytest.raises(ValueError, match="HORS TABLE"):
            entries_in_engagement_zone(first, second, engagement_zone=2, metric="hex")


def test_pairwise_engagement_still_measures_two_real_units():
    """Vert vacant : la même paire, posée, doit rendre un verdict — et le BON."""
    from engine.spatial_relations import entries_in_engagement_zone

    a = _entry(0, 0, player=1)
    assert entries_in_engagement_zone(a, _entry(0, 1, player=2), 2, "hex") is True
    assert entries_in_engagement_zone(a, _entry(20, 20, player=2), 2, "hex") is False


def test_enumerators_drop_the_off_table_entries():
    from engine.spatial_relations import enemy_entries_on_battlefield, entries_on_battlefield

    cache = {
        "1": _entry(3, 3, player=1),
        "2": _entry(-1, -1, player=1),
        "101": _entry(5, 5, player=2),
        "102": _entry(-1, -1, player=2),
    }
    assert [uid for uid, _e in entries_on_battlefield(cache)] == ["1", "101"]
    assert [uid for uid, _e in enemy_entries_on_battlefield(cache, 1)] == ["101"]
    assert [uid for uid, _e in entries_on_battlefield(cache, exclude_id="1")] == ["101"]


# ---------------------------------------------------------------------------
# Moteur réel : la géométrie est CONSTRUITE pour que le fantôme soit à portée
# ---------------------------------------------------------------------------


def _engine(seed: int = 0):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent", scenario_file=str(SCENARIO),
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    assert eng.training_config is not None
    sched = eng.training_config.get("deployment_mode_schedule")
    if isinstance(sched, dict):
        sched["enabled"] = False
    eng.reset(seed=seed)
    return eng


def _drive_deployment(eng) -> None:
    gs = eng.game_state
    steps = 0
    while gs.get("phase") == "deployment" and steps < 1000:
        mask = eng.get_action_mask()
        deploy_actions = [a for a in range(4, 9) if mask[a]]
        assert deploy_actions, f"aucune action de déploiement au step {steps}"
        eng.step(int(deploy_actions[0]))
        steps += 1
    assert gs.get("phase") != "deployment", "déploiement non terminé"


def _on_table(gs: Dict[str, Any], unit_id: str) -> bool:
    from engine.phase_handlers.shared_utils import entry_is_on_battlefield

    return entry_is_on_battlefield(gs["units_cache"][str(unit_id)])


def _reserve(gs: Dict[str, Any], unit_id: str) -> None:
    from engine.combat_utils import get_unit_by_id
    from engine.phase_handlers.movement_handlers import reposition_unit_to_strategic_reserves

    reposition_unit_to_strategic_reserves(gs, str(unit_id))
    unit = get_unit_by_id(gs, str(unit_id))
    assert unit is not None
    unit["reserves_repositioned"] = False


def _park_next_to_the_origin(gs: Dict[str, Any], unit_id: str) -> None:
    """Amène une escouade RÉELLE au coin ``(0,0)`` du plateau — là où vit le fantôme.

    C'est la construction qui rend les tests ci-dessous non vacants : à sa position de
    déploiement, l'unité est à ~274 subhex de ``(-1,-1)``, donc hors de toute portée d'arme et
    hors EZ. Le défaut ne se manifeste QUE dans ce voisinage.
    """
    from engine.phase_handlers.shared_utils import translate_squad_to_destination

    translate_squad_to_destination(gs, str(unit_id), 1, 1)
    entry = gs["units_cache"][str(unit_id)]
    assert (int(entry["col"]), int(entry["row"])) == (1, 1), "la translation n'a pas eu lieu"


def _a_squad_of(gs: Dict[str, Any], player: int) -> str:
    return next(
        sid for sid, e in gs["units_cache"].items()
        if int(e["player"]) == player and _on_table(gs, sid)
    )


def test_a_reserve_next_to_the_origin_is_not_engaged_with_a_real_unit():
    """Famille ENGAGEMENT, par le chemin de PRODUCTION, géométrie construite.

    Le prédicat d'engagement est interrogé sur TOUTES les unités vivantes (snapshot 12.04,
    observation) : il doit rendre False pour la réserve, et l'unité réelle voisine de l'origine
    ne doit pas se croire engagée avec elle. Sans la correction, les deux ressortaient engagées.
    """
    from engine.spatial_relations import (
        get_engagement_zone,
        unit_within_engagement_zone_footprints,
    )
    from engine.combat_utils import get_unit_by_id

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    player = int(gs["current_player"])
    enemy_player = 2 if player == 1 else 1

    ghost = _a_squad_of(gs, enemy_player)
    neighbour = _a_squad_of(gs, player)
    _reserve(gs, ghost)
    _park_next_to_the_origin(gs, neighbour)

    ez = get_engagement_zone(gs)
    ghost_unit = get_unit_by_id(gs, ghost)
    neighbour_unit = get_unit_by_id(gs, neighbour)
    assert ghost_unit is not None and neighbour_unit is not None

    assert not _on_table(gs, ghost), "la réserve doit être hors table (sinon test vacant)"
    assert unit_within_engagement_zone_footprints(
        gs, ghost_unit, ez, max_distance=ez
    ) is False
    assert unit_within_engagement_zone_footprints(
        gs, neighbour_unit, ez, max_distance=ez
    ) is False


def test_a_reserve_within_weapon_range_of_the_shooter_is_no_target_and_no_crash():
    """Famille DISTANCE, par le chemin de PRODUCTION, géométrie construite.

    Le tireur est amené au coin du plateau pour que la sentinelle ``(-1,-1)`` tombe DANS sa
    portée d'arme — c'est là que l'empreinte VIDE de la réserve atteignait
    ``min_distance_between_sets``. Le pool doit se construire sans lever, et sans contenir le
    fantôme.
    """
    from engine.combat_utils import get_unit_by_id
    from engine.phase_handlers.shooting_handlers import (
        build_unit_los_cache,
        shooting_phase_start,
        valid_target_pool_build,
    )

    eng = _engine()
    _drive_deployment(eng)
    gs = eng.game_state
    shooter_player = int(gs["current_player"])
    enemy_player = 2 if shooter_player == 1 else 1

    ghost = _a_squad_of(gs, enemy_player)
    shooter = _a_squad_of(gs, shooter_player)
    _reserve(gs, ghost)
    _park_next_to_the_origin(gs, shooter)
    # CONSTRUIT : sans advance ni contact, `shooting_phase_start` prend la première arme portée
    # sans regarder personne — le précheck d'ennemis ne serait jamais atteint (vert vacant).
    gs.setdefault("units_advanced", set()).add(str(shooter))

    shooting_phase_start(gs)  # ne doit pas lever

    shooter_unit = get_unit_by_id(gs, shooter)
    assert shooter_unit is not None
    build_unit_los_cache(gs, str(shooter))
    assert str(ghost) not in (shooter_unit.get("los_cache") or {}), (
        "une unité hors table n'a pas de ligne de vue : elle ne doit pas entrer dans le cache LoS"
    )

    # (weapon_rule, advance_status, adjacent_status) = (1, 1, 0) : règles d'armes actives et
    # tireur ayant fait un advance — le contexte construit ci-dessus, celui qui atteint le
    # précheck d'ennemis. C'est là que l'empreinte vide de la réserve était mesurée.
    pool = valid_target_pool_build(gs, shooter_unit, 1, 1, 0)
    assert str(ghost) not in {str(t) for t in pool}, (
        "une unité en réserves (20.01) ne peut pas être ciblée au tir"
    )
    assert not _on_table(gs, ghost)
