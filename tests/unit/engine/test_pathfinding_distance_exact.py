"""Tests — distance de pathfinding EXACTE (obs + reward).

Verrouille trois défauts corrigés ensemble dans `calculate_pathfinding_distance` :

1. la profondeur BFS venait d'un littéral `50` interprété comme des SUBHEX, alors que
   `game_rules.max_search_distance` (50 POUCES) est déjà converti en subhex par w40k_core ;
2. un plafond de nœuds (`max_open_nodes = 2000`) tronquait le parcours au milieu et
   renvoyait « injoignable » pour des cibles atteignables ;
3. le cache de distances n'était purgé nulle part, alors que `game_state` survit d'un
   épisode à l'autre et que les murs, eux, changent.

Les trois alimentaient l'observation (danger, cibles de charge) et le reward.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import numpy as np
import pytest

from shared.data_validation import ConfigurationError
from engine.combat_utils import calculate_pathfinding_distance
from engine.hex_utils import hex_distance
from engine.observation_builder import ObservationBuilder
from engine.w40k_core import W40KEngine


def _game_state(max_search_distance: Any = 250, cols: int = 100, rows: int = 100) -> Dict[str, Any]:
    """`game_state` nu suffisant pour la fonction : murs, bornes, et la config scalée."""
    game_rules: Dict[str, Any] = {}
    if max_search_distance is not None:
        game_rules["max_search_distance"] = max_search_distance
    return {
        "wall_hexes": set(),
        "board_cols": cols,
        "board_rows": rows,
        "config": {"game_rules": game_rules},
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Profondeur = config scalée, pas un littéral
# ─────────────────────────────────────────────────────────────────────────────

def test_depth_comes_from_scaled_config() -> None:
    """À x5, `max_search_distance` vaut 250 subhex : une cible à 60 garde sa vraie distance.

    L'ancien littéral `50` la déclarait injoignable (51) alors qu'elle est à portée de
    charge (MOVE + charge_max ≈ 120 subhex sur board x5).
    """
    game_state = _game_state(max_search_distance=250)
    assert calculate_pathfinding_distance(0, 0, 60, 0, game_state) == hex_distance(0, 0, 60, 0)


def test_depth_bound_is_respected() -> None:
    """Au-delà de la profondeur configurée, le contrat reste `max_search_distance + 1`."""
    game_state = _game_state(max_search_distance=10)
    assert calculate_pathfinding_distance(0, 0, 60, 0, game_state) == 11


def test_missing_max_search_distance_raises() -> None:
    """Clé absente = erreur explicite, jamais un défaut silencieux."""
    game_state = _game_state(max_search_distance=None)
    with pytest.raises(ConfigurationError):
        calculate_pathfinding_distance(0, 0, 5, 0, game_state)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Aucune troncature par budget de nœuds
# ─────────────────────────────────────────────────────────────────────────────

def test_no_node_budget_truncation() -> None:
    """Une cible au-delà de l'ancien plafond de 2000 nœuds garde sa distance réelle.

    Le BFS étend ~3·d² nœuds pour atteindre la distance d : à d ≈ 26 l'ancien plafond
    était épuisé et TOUT ce qui était plus loin valait « injoignable », quelle que soit
    la géométrie.
    """
    game_state = _game_state(max_search_distance=250)
    for target_col in (30, 45, 60):
        assert calculate_pathfinding_distance(
            0, 0, target_col, 0, game_state
        ) == hex_distance(0, 0, target_col, 0)


def test_walls_still_force_detour() -> None:
    """Exactitude ne veut pas dire murs ignorés : le détour reste plus long que la ligne droite."""
    game_state = _game_state(max_search_distance=250, cols=25, rows=21)
    game_state["wall_hexes"] = {(2, 0), (2, 1), (3, 0)}
    detour = calculate_pathfinding_distance(0, 0, 5, 0, game_state)
    assert detour > hex_distance(0, 0, 5, 0)


def test_target_on_wall_is_unreachable() -> None:
    game_state = _game_state(max_search_distance=250, cols=25, rows=21)
    game_state["wall_hexes"] = {(5, 0)}
    assert calculate_pathfinding_distance(0, 0, 5, 0, game_state) == 251


# ─────────────────────────────────────────────────────────────────────────────
# 3. Cache de champs : une entrée par source, purgé au reset
# ─────────────────────────────────────────────────────────────────────────────

def test_field_cache_is_keyed_by_source_not_by_pair() -> None:
    game_state = _game_state(max_search_distance=250, cols=25, rows=21)
    for target in ((5, 0), (10, 3), (24, 20)):
        calculate_pathfinding_distance(0, 0, target[0], target[1], game_state)
    assert list(game_state["_pathfinding_field_cache"]) == [(0, 0, 250)]

    calculate_pathfinding_distance(4, 4, 5, 0, game_state)
    assert list(game_state["_pathfinding_field_cache"]) == [(0, 0, 250), (4, 4, 250)]


def test_reverse_query_reuses_the_same_field() -> None:
    """d(a,b) == d(b,a) : interroger le sens inverse ne doit pas construire un second champ."""
    game_state = _game_state(max_search_distance=250, cols=25, rows=21)
    game_state["wall_hexes"] = {(2, 0), (2, 1), (3, 0)}
    forward = calculate_pathfinding_distance(0, 0, 10, 7, game_state)
    backward = calculate_pathfinding_distance(10, 7, 0, 0, game_state)
    assert backward == forward
    assert list(game_state["_pathfinding_field_cache"]) == [(0, 0, 250)]


def test_many_sources_one_target_builds_one_field() -> None:
    """Motif du bot PvE : N destinations candidates comparées à UN ennemi fixe.

    Sans la lecture symétrique, chaque candidat déclencherait son propre parcours complet —
    soit un BFS plein plateau par hex du pool de mouvement.
    """
    game_state = _game_state(max_search_distance=250, cols=25, rows=21)
    target = (20, 15)
    calculate_pathfinding_distance(target[0], target[1], 0, 0, game_state)
    for col in range(10):
        for row in range(10):
            calculate_pathfinding_distance(col, row, target[0], target[1], game_state)
    assert list(game_state["_pathfinding_field_cache"]) == [(20, 15, 250)]


def test_get_pathfinding_field_reads_like_the_scalar_call() -> None:
    from engine.combat_utils import get_pathfinding_field

    game_state = _game_state(max_search_distance=250, cols=25, rows=21)
    game_state["wall_hexes"] = {(2, 0), (2, 1), (3, 0)}
    field = get_pathfinding_field(game_state, 0, 0)
    for col, row in ((5, 0), (10, 7), (24, 20)):
        assert int(field[row * 25 + col]) == calculate_pathfinding_distance(
            0, 0, col, row, game_state
        )


def _minimal_engine_config() -> Dict[str, Any]:
    obs_params = {
        "perception_radius": 25,
        "max_nearby_units": 10,
        "max_valid_targets": 5,
        "obs_size": ObservationBuilder.PHASE2_OBS_SIZE,
    }
    weapon = {
        "ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "display_name": "Test Bolter",
    }

    def _unit(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
        return {
            "id": uid, "player": player, "col": col, "row": row,
            "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
            "HP_CUR": 3, "HP_MAX": 3, "MOVE": 6, "T": 4,
            "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
            "RNG_WEAPONS": [weapon], "CC_WEAPONS": [],
            "UNIT_RULES": [], "UNIT_KEYWORDS": [],
            "LD": 7, "OC": 1, "VALUE": 100, "ICON": "test",
            "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
            "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        }

    return {
        "board": {
            "default": {
                "cols": 15, "rows": 13, "hex_radius": 1.0, "margin": 0.0,
                "wall_hexes": [],
                "objectives": [{"id": "obj1", "name": "Alpha", "hexes": [[5, 5]]}],
                "inches_to_subhex": 1,
            }
        },
        "game_rules": {
            "engagement_zone": 1,
            "engagement_zone_vertical": 5,
            "max_base_size_hex": 35,
            "max_search_distance": 50,
            "max_turns": 3,
            "max_actions_per_model_per_turn": 7,
            "step_limit_margin": 1.5,
        },
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "charge": {"charge_max_distance": 12},
        "pve_mode": False,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params},
        "units": [_unit(1, 1, 3, 3), _unit(2, 2, 10, 10)],
    }


def test_field_cache_purged_on_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le champ est calculé sur les murs de l'épisode : il ne doit pas survivre au reset.

    `game_state` est le MÊME objet d'un épisode à l'autre et les murs changent
    (train_wall_ref_weights) : un champ survivant servirait les distances d'un autre plateau.
    """
    monkeypatch.setattr(
        W40KEngine, "_build_observation",
        lambda self: np.zeros(ObservationBuilder.PHASE2_OBS_SIZE),
    )
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        engine = W40KEngine(config=_minimal_engine_config())

    engine.reset()
    calculate_pathfinding_distance(3, 3, 10, 10, engine.game_state)
    assert engine.game_state["_pathfinding_field_cache"]

    engine.reset()
    assert "_pathfinding_field_cache" not in engine.game_state
