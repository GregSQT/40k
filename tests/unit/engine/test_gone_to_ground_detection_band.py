"""13-5 Gone to Ground — la bande ]12" ; 15"] où le −3" de détection décide seul de l'éligibilité.

Règle lue (Documentation/40k_rules/13-5 gone to ground.jpg) : une figurine a « gone to ground »
quand elle est hidden, PAS entièrement visible pour le tireur à cause d'un terrain Solid
intervenant, et que son unité n'a pas tiré ce tour ni au précédent ; sa detection range est alors
réduite de 3" (15" → 12").

Trou de couverture fermé ici : aucun test ne référençait `hidden_enemy_out_of_detection` ni
`_model_footprint_not_fully_visible_due_to_solid` ; test_squad_obs_hidden_enemies.py ne teste que
22" et 10" (hors de la bande) ; tests/integration/pvp/test_shoot.py n'affirme que
detection_inches ∈ {12, 15}.

Fixture MICRO (inches_to_subhex 5, socle 16 → empreinte 169 hexes) : seul moyen d'obtenir « visible
mais pas entièrement » — avec un socle d'un hex, fully_visible ≡ can_see (cf. _micro_engine de
test_squad_obs_enemy_cover.py). La cible INFANTRY est entièrement dans une zone obscurante qui
contient un mur dense et n'a pas tiré ; un mur dense PARTIEL masque une partie de son socle. La
distance bord-à-bord est MESURÉE (`ranged_edge_distance`) et ASSERTÉE dans ]12" ; 15"].
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

from engine.w40k_core import W40KEngine
from engine.observation_builder import ObservationBuilder
from engine.observation_entities import unit_bin_index
from tests.unit.engine._config_helpers import build_engine_config, build_game_rules

BIN_HIDDEN = unit_bin_index("hidden")
BIN_LOS = unit_bin_index("los_can_see")
BIN_PRESENT = unit_bin_index("present")

_SUBHEX = 5
_SHOOTER = (10, 20)
#: Cible dans la bande : centres à 80 colonnes, socles de rayon ~7 hexes → bord-à-bord ≈ 66 subhex
#: (13,2"). Vérifié par assertion dans chaque test, jamais présumé.
_ENEMY_BAND = (90, 20)
#: Cible SOUS 12" : centres à 62 colonnes → bord-à-bord ≈ 48 subhex (9,6").
_ENEMY_NEAR = (72, 20)

#: Mur dense PARTIEL devant le socle de la cible (empreinte lignes ~13..27) : masque les lignes
#: 14..19 seulement → la cible reste visible, pas entièrement.
def _partial_wall(enemy_col: int) -> List[List[int]]:
    return [[c, r] for c in (enemy_col - 10, enemy_col - 9) for r in range(14, 20)]


def _area_around(enemy: Tuple[int, int]) -> Dict[str, Any]:
    """Zone DENSE (donc obscurante) englobant tout le socle de la cible ET son mur partiel (13.09 :
    la zone contient un terrain dense — drapeau `dense` dérivé des murs typés au chargement, posé
    ici à la main comme le mur ; 13.10 : la cible dedans reste visible depuis l'extérieur)."""
    c, r = enemy
    hexes = [[x, y] for x in range(c - 12, c + 10) for y in range(r - 10, r + 11)]
    poly = [[c - 12, r - 10], [c + 9, r - 10], [c + 9, r + 10], [c - 12, r + 10]]
    return {"id": "zone", "obscuring": True, "dense": True, "polygon_vertices": poly, "hexes": hexes}


#: Portée d'arme 24", écrite directement en SUBHEX : dans ce fixture (config inline, plateau
#: MICRO), `_get_inches_to_subhex` du loader vaut 1 et ne rescale pas les armes ; le fixture le
#: vérifie après reset pour ne jamais tester une portée fausse.
_WEAPON_RNG_SUBHEX = 24 * _SUBHEX


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": _WEAPON_RNG_SUBHEX,
        "WEAPON_RULES": [], "code": "test_weapon", "display_name": "Test Bolter", "shot": 0,
    }


def _unit_cfg(uid: int, player: int, pos: Tuple[int, int]) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": pos[0], "row": pos[1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 1, "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [_weapon_cfg()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "LD": 7, "OC": 2, "VALUE": 10,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 16, "MODEL_HEIGHT": 2.5,
        "models": [{"col": pos[0], "row": pos[1], "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10}],
    }


def _make_engine(enemy: Tuple[int, int], *, wall: bool) -> W40KEngine:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    walls = _partial_wall(enemy[0]) if wall else []
    cfg = {
        "board": {"default": {
            "cols": 120, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
            "wall_hexes": walls, "inches_to_subhex": _SUBHEX,
        }},
        # Vraies règles (detection_range = 15) + neutralisations de test.
        "game_rules": build_game_rules(
            engagement_zone=1, engagement_zone_vertical=5, max_base_size_hex=35,
            unit_model_cohesion_range=2, unit_global_cohesion_range=9,
            squad_min_neighbors=1, cohesion_distance_mode="euclidean",
        ),
        "charge": {"charge_max_distance": 12},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "scenario_objectives": [],
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [_unit_cfg(1, 1, _SHOOTER), _unit_cfg(2, 2, enemy)],
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(cfg))
    eng.reset()
    gs = eng.game_state
    assert gs["unit_by_id"]["1"]["RNG_WEAPONS"][0]["RNG"] == _WEAPON_RNG_SUBHEX, (
        "fixture : la portée d'arme a été rescalée, la bande ]12\" ; 15\"] ne serait plus à portée"
    )
    gs["terrain_areas"] = [_area_around(enemy)]
    gs["wall_hexes"] = walls
    gs["dense_wall_hexes"] = walls
    for key in (
        "_unit_los_pair_cache", "_obscuring_area_sets_cache", "_obscuring_hex_to_area_cache",
        "_wall_set_cache", "_dense_wall_set_cache", "_shooter_los_models_cache",
        "_elevated_ignored_walls_cache",
    ):
        gs.pop(key, None)
    return eng


def _edge_inches(eng: W40KEngine) -> float:
    from engine.combat_utils import ranged_edge_distance, socle_from_cache_entry
    from engine.phase_handlers.shooting_handlers import _ranged_distance_metric
    gs = eng.game_state
    d = ranged_edge_distance(
        socle_from_cache_entry(gs["units_cache"]["1"]), socle_from_cache_entry(gs["units_cache"]["2"]),
        _ranged_distance_metric(gs), max_distance=_WEAPON_RNG_SUBHEX,
    )
    return d / _SUBHEX


def _pool(eng: W40KEngine) -> List[str]:
    from engine.phase_handlers.shooting_handlers import (
        build_unit_los_cache, compute_hidden_statuses, valid_target_pool_build,
    )
    from engine.game_utils import require_unit_by_id
    gs = eng.game_state
    compute_hidden_statuses(gs)
    build_unit_los_cache(gs, "1")
    return valid_target_pool_build(gs, require_unit_by_id(gs, "1"), 0, 0, 0)


def _enemy_flags(eng: W40KEngine) -> Dict[str, float]:
    obs = eng.obs_builder.build_squad_observation(eng.game_state, "1")
    slots = [i for i, r in enumerate(obs["enemies_bin"]) if float(r[BIN_PRESENT]) == 1.0]
    assert len(slots) == 1
    row = obs["enemies_bin"][slots[0]]
    return {"hidden": float(row[BIN_HIDDEN]), "los": float(row[BIN_LOS])}


def _assert_band(eng: W40KEngine) -> None:
    d = _edge_inches(eng)
    assert 12.0 < d <= 15.0, f"fixture : distance bord-à-bord {d}\" hors de la bande ]12 ; 15]"


def test_gone_to_ground_dans_la_bande_sort_du_pool():
    """Hidden + mur Solid partiel + ]12" ; 15"] → detection 12" < distance → hors du pool,
    et l'observation le dit (`los_can_see = 0`) alors que la LoS géométrique existe."""
    from engine.phase_handlers.shooting_handlers import compute_unit_los
    eng = _make_engine(_ENEMY_BAND, wall=True)
    _assert_band(eng)
    gs = eng.game_state
    los = compute_unit_los(gs, gs["unit_by_id"]["1"], gs["unit_by_id"]["2"])
    assert los["can_see"] is True and los["fully_visible"] is False, (
        "fixture : la cible doit être visible mais PAS entièrement (mur partiel)"
    )
    assert "2" not in _pool(eng), "gone to ground : detection 12\" < distance, la cible doit sortir du pool"
    f = _enemy_flags(eng)
    assert f["hidden"] == 1.0
    assert f["los"] == 0.0


def test_meme_geometrie_sans_mur_reste_dans_le_pool():
    """Contre-épreuve : sans Solid intervenant, pas de GtG → detection 15" ≥ distance → ciblable."""
    eng = _make_engine(_ENEMY_BAND, wall=False)
    _assert_band(eng)
    assert "2" in _pool(eng)
    f = _enemy_flags(eng)
    assert f["hidden"] == 1.0, "fixture : la cible doit rester hidden (zone obscurante + dense)"
    assert f["los"] == 1.0


def test_sous_12_pouces_le_mur_ne_change_rien():
    """≤ 12" : même gone to ground, la cible est dans la detection réduite → ciblable."""
    eng = _make_engine(_ENEMY_NEAR, wall=True)
    d = _edge_inches(eng)
    assert d <= 12.0, f"fixture : distance {d}\" doit être ≤ 12\""
    assert "2" in _pool(eng)
    assert _enemy_flags(eng)["los"] == 1.0
