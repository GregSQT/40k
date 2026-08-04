"""CONTRAT de l'observation squad : tenseurs d'entites + separation continues/discretes.

Refonte V11 §9.5 (« Normalisation ») puis §0.30 T-D (tenseurs d'entites) : les valeurs continues
sont exposees en unites BRUTES, les valeurs discretes ne sont JAMAIS normalisees, et chaque
UNITE — la mienne, mes alliees, les ennemies — porte le MEME schema de features pour qu'un
encodeur PARTAGE puisse les traiter (engine/observation_entities.py).

Contre-epreuves integrees :
- `test_continuous_features_are_raw` echoue si une division fixe est reintroduite (les valeurs
  brutes attendues sont > 1.0, donc incompatibles avec les anciens /10 /30 satures) ;
- `test_declared_size_matches_the_sum_of_every_tensor` echoue si un bloc est ajoute sans mettre
  a jour `obs_size` ;
- `test_enemy_slot_count_mirrors_the_action_space` echoue si l'observation et l'espace d'action
  divergent sur le nombre de slots ennemis (c'est le desalignement D1) ;
- `test_unit_schema_is_shared_by_both_sides` echoue si un camp gagne une feature que l'autre
  n'a pas — l'encodeur partage n'aurait alors plus de sens ;
- `test_observation_space_matches_builder` echoue si l'espace d'obs de l'env diverge du layout.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import numpy as np
import pytest

from engine.observation_builder import ObservationBuilder
from engine.observation_entities import global_bin_index, unit_bin_index, unit_cont_index
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 2, "RNG": 24,
        "WEAPON_RULES": [], "display_name": "Test Bolter",
    }


def _model(col: int, row: int) -> Dict[str, Any]:
    return {"col": col, "row": row, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 7}


def _unit_cfg(uid: int, player: int, col: int, row: int, n_models: int, oc: int) -> Dict[str, Any]:
    """Escouade multi-figurines : n_models figurines alignees a partir de (col, row)."""
    models = [_model(col + 2 * i, row) for i in range(n_models)]
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": n_models, "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": oc, "VALUE": 7 * n_models,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": models,
    }


def _config() -> Dict[str, Any]:
    obs_params = {
        "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET,
    }
    return {
        "board": {
            "default": {
                "cols": 120, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
                "wall_hexes": [], "objectives": [], "inches_to_subhex": 1,
            }
        },
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            # Cohesion : memes valeurs que config/game_config.json (converties en subhex).
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
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        # Escouade active : 12 figurines, OC 2 chacune -> OC total 24 (> 10 : sature l'ancien /10).
        # Ennemi : 20 figurines, 20 PV (> 10 et > 30/2 : sature les anciens /10 et /30).
        "units": [
            _unit_cfg(1, 1, 10, 20, n_models=12, oc=2),
            _unit_cfg(2, 2, 60, 20, n_models=20, oc=1),
        ],
    }


@pytest.fixture
def engine():
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(_config()))
    eng.reset()
    return eng


def test_observation_keys_match_the_declared_shapes(engine):
    """Le builder emet EXACTEMENT les cles/formes de `squad_obs_shapes()` (source unique)."""
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    shapes = ObservationBuilder.squad_obs_shapes()
    assert set(obs) == set(shapes)
    for key, shape in shapes.items():
        assert obs[key].shape == shape, key
        assert obs[key].dtype == np.float32, key


def test_declared_size_matches_the_sum_of_every_tensor(engine):
    """`obs_size` (config d'agent) = somme des scalaires emis, grille exclue."""
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    total = sum(int(np.prod(v.shape)) for v in obs.values())
    assert total == ObservationBuilder.SQUAD_OBS_SIZE_TARGET


def test_enemy_slot_count_mirrors_the_action_space(engine):
    """Un slot d'observation ennemi <-> une action de tir. Deux valeurs = un desalignement D1."""
    from engine.phase_handlers.shared_utils import SQUAD_ACTION_SHOOT_SLOT_COUNT

    assert ObservationBuilder.K_ENEMY_SLOTS == SQUAD_ACTION_SHOOT_SLOT_COUNT


def test_unit_schema_is_shared_by_both_sides(engine):
    """Ami et ennemi portent le MEME schema : c'est ce qui rend l'encodeur partage legitime."""
    shapes = ObservationBuilder.squad_obs_shapes()
    for suffix in ("cont", "bin", "wpn_cont", "wpn_bin", "types_cont", "types_bin"):
        assert shapes[f"allies_{suffix}"][1:] == shapes[f"enemies_{suffix}"][1:], suffix


def test_continuous_features_are_raw(engine):
    """Contre-epreuve des normalisations manuelles : les valeurs depassent 1.0.

    Sous l'ancien code (OC/10 clampe, taille/10, PV/30 clampes), ces trois assertions
    rougissent : chaque valeur y valait exactement 1.0.
    """
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    mine = obs["allies_cont"][0]
    enemy = obs["enemies_cont"][0]

    assert mine[unit_cont_index("oc_total")] == pytest.approx(24.0)  # 12 figurines x OC 2
    assert enemy[unit_cont_index("alive_models")] == pytest.approx(20.0)
    assert enemy[unit_cont_index("hp_total")] == pytest.approx(20.0)


def test_binary_tensors_hold_only_discrete_semantics(engine):
    """Cles "_bin" : drapeaux 0/1, phase en ONE-HOT, controle d'objectif dans {-1,0,1}.

    La phase n'a plus d'exception a se faire pardonner : depuis V11 §0.32 T-J c'est un one-hot de
    6 bits, donc reellement discret (elle valait 0/.25/.5/.75/1 et devait etre exclue de la
    verification).
    """
    from engine.observation_entities import OBS_PHASE_IDS

    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    phase_bits = [
        float(obs["global_bin"][global_bin_index(f"phase_{phase}")]) for phase in OBS_PHASE_IDS
    ]
    assert sum(phase_bits) == 1.0, f"phase {phase_bits} n'est pas un one-hot"
    for key, value in obs.items():
        if not key.endswith("_bin"):
            continue
        for idx, v in enumerate(value.reshape(-1)):
            assert float(v) in {-1.0, 0.0, 1.0}, f"{key}[{idx}] = {v} n'est pas discret"


def test_absent_entities_are_zero_padded(engine):
    """Un slot vide est une ligne de ZEROS : le bit `present` porte seul l'information."""
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    present = unit_bin_index("present")
    for family in ("allies", "enemies"):
        for row in range(obs[f"{family}_bin"].shape[0]):
            if float(obs[f"{family}_bin"][row][present]) == 1.0:
                continue
            assert not obs[f"{family}_cont"][row].any(), (family, row)
            assert not obs[f"{family}_bin"][row].any(), (family, row)
            assert not obs[f"{family}_wpn_cont"][row].any(), (family, row)
            assert not obs[f"{family}_types_cont"][row].any(), (family, row)


def test_active_unit_is_row_zero_of_the_allies(engine):
    """Contrat : la ligne 0 des allies est l'unite OBSERVEE, et elle seule porte `is_active`."""
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    is_active = unit_bin_index("is_active")
    is_ally = unit_bin_index("is_ally")
    assert float(obs["allies_bin"][0][is_active]) == 1.0
    assert float(obs["allies_bin"][0][is_ally]) == 1.0
    assert not any(
        float(obs["allies_bin"][row][is_active]) for row in range(1, obs["allies_bin"].shape[0])
    )
    assert not obs["enemies_bin"][:, is_active].any()
    assert not obs["enemies_bin"][:, is_ally].any()


def test_observation_space_matches_builder(engine):
    """L'espace d'obs de l'env expose les memes cles/formes que le builder, grille comprise."""
    from engine.spatial_grid import GRID_CHANNELS, GRID_SIZE

    space = engine.observation_space
    shapes = ObservationBuilder.squad_obs_shapes()
    assert set(space.spaces) == set(shapes) | {"grid"}
    for key, shape in shapes.items():
        assert space.spaces[key].shape == shape, key
    assert space.spaces["grid"].shape == (GRID_CHANNELS, GRID_SIZE, GRID_SIZE)
    # Les continues brutes ne sont pas bornees a [0,1] : une borne 0..1 mentirait sur des PV
    # ou des subhex bruts et ferait echouer check_env des que la valeur depasse 1.
    assert not np.isfinite(space.spaces["allies_cont"].high).any()

    obs = engine._build_observation()
    assert set(obs) == set(shapes) | {"grid"}
    for key in obs:
        assert obs[key].shape == space.spaces[key].shape


def test_vec_norm_obs_keys_targets_only_the_global_block(engine):
    """VecNormalize ne normalise que "global_cont".

    Les tenseurs d'entites en sont EXCLUS : VecNormalize normalise element par element, donc
    chaque slot aurait ses propres statistiques et le meme encodeur partage verrait des echelles
    differentes selon le slot — ce qui annulerait le partage de poids (V11 §0.30 T-D). Ils sont
    normalises dans l'extracteur, par une statistique commune a tous les slots.
    """
    from ai.train import _vec_norm_obs_keys

    # `None` = obs Box (comportement historique « tout normaliser ») ; ce test porte sur une obs
    # Dict, donc l'ancrer explicitement plutot que d'indexer un Optional.
    norm_keys = _vec_norm_obs_keys(engine.observation_space)
    assert norm_keys is not None, "obs Dict attendue (None signifie une obs Box)"
    assert norm_keys == ["global_cont"]
    for key in ObservationBuilder.ENTITY_CONT_KEYS:
        assert key in engine.observation_space.spaces
        assert key not in norm_keys
