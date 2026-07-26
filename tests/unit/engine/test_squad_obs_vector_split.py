"""T1 — l'observation squad est scindee en "vec_cont" (continues BRUTES) / "vec_bin" (discretes).

Refonte V11 (Documentation/Implementation/V11_audit_observation.md §9.5 « Normalisation ») :
les valeurs continues sont exposees en unites brutes et normalisees par VecNormalize
(norm_obs_keys=["vec_cont"]), les valeurs discretes (drapeaux, phase, controle d'objectif) ne
sont JAMAIS normalisees. Les divisions manuelles (/5 /10 /20 /30 /100, clamps a 1.0) sont
retirees : elles saturaient (une escouade de 20 figurines valait 1.0 comme une de 10) et
constituaient une seconde normalisation non ré-estimable.

Contre-epreuves integrees :
- `test_continuous_features_are_raw` echoue si une division fixe est reintroduite (les valeurs
  brutes attendues sont > 1.0, donc incompatibles avec les anciens /10 /30 satures) ;
- `test_layout_sizes_match_constants` echoue si un bloc est ajoute sans mettre a jour les
  constantes de taille (le builder leve alors RuntimeError) ;
- `test_observation_space_matches_builder` echoue si l'espace d'obs de l'env diverge du layout.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import numpy as np
import pytest

from engine.observation_builder import ObservationBuilder
from engine.w40k_core import W40KEngine


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
        "perception_radius": 25, "max_nearby_units": 10, "max_valid_targets": 5,
        "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET, "action_space_size": 1047,
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
        eng = W40KEngine(config=_config())
    eng.reset()
    return eng


def test_observation_has_two_vectors(engine):
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    assert set(obs) == {"vec_cont", "vec_bin"}
    assert obs["vec_cont"].dtype == np.float32 and obs["vec_bin"].dtype == np.float32


def test_layout_sizes_match_constants(engine):
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    assert obs["vec_cont"].shape == (ObservationBuilder.SQUAD_OBS_CONT_SIZE,)
    assert obs["vec_bin"].shape == (ObservationBuilder.SQUAD_OBS_BIN_SIZE,)
    assert (
        ObservationBuilder.SQUAD_OBS_CONT_SIZE + ObservationBuilder.SQUAD_OBS_BIN_SIZE
        == ObservationBuilder.SQUAD_OBS_SIZE_TARGET
    )


def test_continuous_features_are_raw(engine):
    """Contre-epreuve des normalisations manuelles : les valeurs depassent 1.0.

    Sous l'ancien code (OC/10 clampe, taille/10, PV/30 clampes), ces trois assertions
    rougissent : chaque valeur y valait exactement 1.0.
    """
    gs = engine.game_state
    obs = engine.obs_builder.build_squad_observation(gs, "1")
    cont = obs["vec_cont"]

    assert cont[3] == pytest.approx(24.0)  # OC total brut (12 figurines x OC 2)

    e_base = ObservationBuilder.squad_enemy_cont_base(0)
    assert cont[e_base + 0] == pytest.approx(20.0)  # taille d'escouade brute
    assert cont[e_base + 1] == pytest.approx(20.0)  # PV totaux bruts


def test_binary_vector_holds_only_discrete_semantics(engine):
    """vec_bin : drapeaux 0/1, phase dans {0,.25,.5,.75,1}, controle d'objectif dans {-1,0,1}."""
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    binv = obs["vec_bin"]
    allowed_phase = {0.0, 0.25, 0.5, 0.75, 1.0}
    assert float(binv[1]) in allowed_phase
    for i, v in enumerate(binv):
        if i == 1:
            continue
        assert float(v) in {-1.0, 0.0, 1.0}, f"vec_bin[{i}] = {v} n'est pas discret"


def test_enemy_slot_offsets_are_contiguous_and_in_range(engine):
    """Les accesseurs d'offset couvrent exactement les vecteurs (pas de trou, pas de debordement)."""
    n = ObservationBuilder.SQUAD_N_ENEMY_SLOTS
    last_cont = ObservationBuilder.squad_enemy_cont_base(n - 1) + ObservationBuilder.SQUAD_PER_ENEMY_SLOT_CONT
    last_bin = ObservationBuilder.squad_enemy_bin_base(n - 1) + ObservationBuilder.SQUAD_PER_ENEMY_SLOT_BIN
    assert last_cont == ObservationBuilder.SQUAD_OBS_CONT_SIZE
    assert last_bin == ObservationBuilder.SQUAD_OBS_BIN_SIZE


def test_observation_space_matches_builder(engine):
    """L'espace d'obs de l'env expose les memes cles/tailles que le builder, grille comprise."""
    from engine.spatial_grid import GRID_CHANNELS, GRID_SIZE

    space = engine.observation_space
    assert set(space.spaces) == {"vec_cont", "vec_bin", "grid"}
    assert space.spaces["vec_cont"].shape == (ObservationBuilder.SQUAD_OBS_CONT_SIZE,)
    assert space.spaces["vec_bin"].shape == (ObservationBuilder.SQUAD_OBS_BIN_SIZE,)
    assert space.spaces["grid"].shape == (GRID_CHANNELS, GRID_SIZE, GRID_SIZE)
    # Les continues brutes ne sont pas bornees a [0,1] : une borne 0..1 mentirait sur des PV
    # ou des subhex bruts et ferait echouer check_env des que la valeur depasse 1.
    assert not np.isfinite(space.spaces["vec_cont"].high).any()

    obs = engine._build_observation()
    assert set(obs) == {"vec_cont", "vec_bin", "grid"}
    for key in ("vec_cont", "vec_bin", "grid"):
        assert obs[key].shape == space.spaces[key].shape


def test_vec_norm_obs_keys_targets_only_continuous(engine):
    """VecNormalize ne normalise que "vec_cont" (drapeaux et grille restent bruts)."""
    from ai.train import _vec_norm_obs_keys

    assert _vec_norm_obs_keys(engine.observation_space) == ["vec_cont"]
