"""Verrou : l'observation porte la portée effective (subhexes) de l'arme de tir la plus longue
de l'unité observatrice, pour chaque slot ennemi (V11 §9.5 P4 reliquat).

La valeur est la MÊME pour tous les slots ennemis d'un même step (propriété de l'observatrice,
pas de la cible), mais exposée par slot pour que la tête pointeur puisse la comparer directement
à `edge_distance` sans croiser des parties différentes de l'observation.

Propriétés verrouillées :
- `effective_range` vaut max(RNG) × inches_to_subhex sur les armes de tir de l'observatrice.
- Elle est à 0 pour tous les slots ALLIÉS (grandeur de paire ennemie uniquement).
- Elle suit bien `inches_to_subhex` : une résolution ×5 donne 5× la valeur ×1.
- Une unité corps-à-corps pure expose 0 pour tous ses ennemis.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

from engine.observation_builder import ObservationBuilder
from engine.observation_entities import unit_cont_index
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

CONT_EFFECTIVE_RANGE = unit_cont_index("effective_range")
CONT_EDGE_DIST = unit_cont_index("edge_distance")


def _weapon(rng: int) -> Dict[str, Any]:
    return {
        "ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": rng,
        "WEAPON_RULES": [], "display_name": f"Weapon RNG{rng}",
    }


def _melee_weapon() -> Dict[str, Any]:
    return {
        "ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
        "WEAPON_RULES": [], "display_name": "Melee",
    }


def _unit_cfg(
    uid: int, player: int, positions: List[Tuple[int, int]],
    *, rng_weapons: List[Dict[str, Any]], cc_weapons: List[Dict[str, Any]],
) -> Dict[str, Any]:
    specs = [{"col": c, "row": r, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10} for c, r in positions]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(specs), "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": rng_weapons, "CC_WEAPONS": cc_weapons,
        "UNIT_RULES": [], "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _config(
    mine_pos: List[Tuple[int, int]], enemy_pos: List[Tuple[int, int]],
    *, inches_to_subhex: int = 1,
    rng_weapons_mine: List[Dict[str, Any]] | None = None,
    cc_weapons_mine: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    if rng_weapons_mine is None:
        rng_weapons_mine = [_weapon(24)]
    if cc_weapons_mine is None:
        cc_weapons_mine = [_melee_weapon()]
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    return {
        "board": {"default": {
            "cols": 120, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
            "wall_hexes": [], "inches_to_subhex": inches_to_subhex,
        }},
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            "unit_model_cohesion_range": 2, "unit_global_cohesion_range": 9,
            "squad_min_neighbors": 1, "cohesion_distance_mode": "euclidean",
        },
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
        "units": [
            _unit_cfg(1, 1, mine_pos, rng_weapons=rng_weapons_mine, cc_weapons=cc_weapons_mine),
            _unit_cfg(2, 2, enemy_pos, rng_weapons=[_weapon(12)], cc_weapons=[_melee_weapon()]),
        ],
    }


def _make_engine(cfg: Dict[str, Any]) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(cfg))
    eng.reset()
    return eng


def _obs(engine: W40KEngine) -> Dict[str, Any]:
    return engine.obs_builder.build_squad_observation(engine.game_state, "1")


def _first_enemy_cont(engine: W40KEngine):
    """Vecteur continu du premier slot ennemi présent."""
    from engine.observation_entities import unit_bin_index
    BIN_PRESENT = unit_bin_index("present")
    ob = _obs(engine)
    ec = ob["enemies_cont"]
    eb = ob["enemies_bin"]
    row = next(i for i in range(ObservationBuilder.K_ENEMY_SLOTS) if eb[i][BIN_PRESENT] == 1.0)
    return ec[row]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_effective_range_equals_max_rng_times_ish():
    """Valeur nominale : arme de portée 24" à ×1 → 24 subhex."""
    eng = _make_engine(_config([(10, 20)], [(30, 20)], inches_to_subhex=1))
    ec = _first_enemy_cont(eng)
    assert ec[CONT_EFFECTIVE_RANGE] == 24.0, (
        f"effective_range attendu 24.0, obtenu {ec[CONT_EFFECTIVE_RANGE]}"
    )


def test_effective_range_scales_with_ish():
    """À ×5, la portée 24" = 120 subhexes (valeur déjà scalée par _build_enhanced_unit)."""
    # create_unit ne scale pas les armes ; on passe RNG=120 pré-scalé pour simuler le chemin
    # production (_build_enhanced_unit: w["RNG"] = 24 * 5 = 120 avant que l'obs soit construite).
    eng = _make_engine(_config(
        [(10, 20)], [(40, 20)], inches_to_subhex=5,
        rng_weapons_mine=[_weapon(120)],
    ))
    ec = _first_enemy_cont(eng)
    assert ec[CONT_EFFECTIVE_RANGE] == 120.0, (
        f"effective_range attendu 120.0 (24×5 pré-scalé), obtenu {ec[CONT_EFFECTIVE_RANGE]}"
    )


def test_effective_range_is_the_maximum_over_all_ranged_weapons():
    """Plusieurs armes : la plus longue portée est retenue."""
    weapons = [_weapon(12), _weapon(24), _weapon(18)]
    eng = _make_engine(_config([(10, 20)], [(30, 20)], rng_weapons_mine=weapons))
    ec = _first_enemy_cont(eng)
    assert ec[CONT_EFFECTIVE_RANGE] == 24.0, (
        f"effective_range attendu 24.0 (max parmi 12/24/18), obtenu {ec[CONT_EFFECTIVE_RANGE]}"
    )


def test_effective_range_is_zero_for_melee_only_unit():
    """Unité sans arme de tir : effective_range = 0 pour tous ses ennemis."""
    eng = _make_engine(_config(
        [(10, 20)], [(20, 20)],
        rng_weapons_mine=[],
        cc_weapons_mine=[_melee_weapon()],
    ))
    ec = _first_enemy_cont(eng)
    assert ec[CONT_EFFECTIVE_RANGE] == 0.0, (
        f"effective_range doit valoir 0 pour une unité corps-à-corps, obtenu {ec[CONT_EFFECTIVE_RANGE]}"
    )


def test_effective_range_is_zero_for_ally_slots():
    """Grandeur de PAIRE (observatrice → ennemi) : doit valoir 0 pour tous les alliés."""
    eng = _make_engine(_config([(10, 20)], [(30, 20)]))
    ob = _obs(eng)
    ac = ob["allies_cont"]
    for row in range(ObservationBuilder.K_ALLY_SLOTS):
        assert ac[row][CONT_EFFECTIVE_RANGE] == 0.0, (
            f"allies[{row}] : effective_range non nul ({ac[row][CONT_EFFECTIVE_RANGE]})"
        )


def test_effective_range_is_same_for_all_present_enemy_slots():
    """Propriété de l'observatrice : effective_range est identique pour tous les ennemis présents."""
    from engine.observation_entities import unit_bin_index
    BIN_PRESENT = unit_bin_index("present")

    cfg = _config([(10, 20), (11, 20)], [(30, 20), (31, 20)])
    cfg["units"].append(
        _unit_cfg(3, 2, [(50, 20)], rng_weapons=[_weapon(6)], cc_weapons=[_melee_weapon()])
    )
    eng = _make_engine(cfg)
    ob = _obs(eng)
    ec = ob["enemies_cont"]
    eb = ob["enemies_bin"]

    values = [
        ec[i][CONT_EFFECTIVE_RANGE]
        for i in range(ObservationBuilder.K_ENEMY_SLOTS)
        if eb[i][BIN_PRESENT] == 1.0
    ]
    assert len(values) >= 2, "au moins 2 slots ennemis présents requis pour ce test"
    assert all(v == values[0] for v in values), (
        f"effective_range diffère selon le slot ennemi : {values}"
    )
