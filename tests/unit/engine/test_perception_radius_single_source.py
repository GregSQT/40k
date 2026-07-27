"""Verrou : `perception_radius` a UNE seule source, scalee en sub-hex.

Contexte (2026-07-27). Trois lectures coexistaient :

| lieu | valeur reelle | statut |
|---|---|---|
| `observation_builder` sur `config["observation_params"]` | 25 x inches_to_subhex (sub-hex) | correcte |
| `w40k_core` sur `training_config["observation_params"]` | 25 (POUCES) | supprimee — jamais relue |
| `weapon_selector` `game_state.get("perception_radius", 25)` | 25, toujours | supprimee — code mort |

La cle `game_state["perception_radius"]` n'etait ecrite NULLE PART : le `.get(..., 25)` du
selecteur d'armes renvoyait donc toujours 25 (pouces) et le comparait a une distance hex en
sub-hex. La fonction porteuse (`recompute_cache_for_new_units_in_range`) n'etait elle-meme
jamais appelee — supprimee plutot que reparee.

Le piege structurel a verrouiller : la normalisation de `w40k_core` deep-copie
`config["observation_params"]` avant de scaler, ce qui DESOLIDARISE ce dict de
`training_config["observation_params"]`. Toute relecture de la valeur via `training_config`
renvoie donc des POUCES et passe inapercue (25 vs 125 sur un board x5).
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.observation_builder import ObservationBuilder
from engine.w40k_core import W40KEngine

from _config_helpers import build_game_rules


def _config(scale: int, *, obs_params_override: Dict[str, Any] | None = None) -> Dict[str, Any]:
    obs_params: Dict[str, Any] = {
        "perception_radius": 25,
        "max_nearby_units": 10,
        "max_valid_targets": 5,
        "obs_size": ObservationBuilder.PHASE2_OBS_SIZE,
    }
    if obs_params_override is not None:
        obs_params = obs_params_override
    return {
        "board": {
            "default": {
                "cols": 15,
                "rows": 13,
                "hex_radius": 1.0,
                "margin": 0.0,
                "wall_hexes": [],
                "inches_to_subhex": scale,
            }
        },
        "scenario_objectives": [{"id": "obj_1", "name": "Alpha", "hexes": [[5, 5]]}],
        "game_rules": build_game_rules(engagement_zone=1, max_base_size_hex=35),
        "pve_mode": False,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params},
        "units": [],
    }


class TestPerceptionRadiusScaling:
    @pytest.mark.parametrize("scale,expected", [(1, 25), (5, 125)])
    def test_radius_is_scaled_to_subhex(self, scale: int, expected: int):
        """25 pouces -> 25 x inches_to_subhex sub-hex, dans la source unique."""
        eng = W40KEngine(config=_config(scale))
        assert eng.config["observation_params"]["perception_radius"] == expected
        assert eng.obs_builder.perception_radius == expected

    def test_training_config_keeps_inches_and_engine_exposes_nothing(self):
        """Le deep-copy desolidarise training_config : il reste en POUCES.

        C'est precisement pourquoi le moteur ne doit PAS republier la valeur : un
        `self.perception_radius` alimente par `training_config` vaudrait 25 la ou
        l'observation utilise 125.
        """
        eng = W40KEngine(config=_config(5))
        tc = eng.training_config
        assert isinstance(tc, dict)
        assert tc["observation_params"]["perception_radius"] == 25
        assert eng.config["observation_params"] is not tc["observation_params"]
        for attr in ("perception_radius", "max_nearby_units", "max_valid_targets"):
            assert not hasattr(eng, attr), (
                f"W40KEngine.{attr} ressuscite une seconde source de verite non scalee"
            )

    def test_missing_perception_radius_raises(self):
        """Cle absente -> erreur explicite, aucun defaut de repli."""
        cfg = _config(5, obs_params_override={
            "max_nearby_units": 10,
            "max_valid_targets": 5,
            "obs_size": ObservationBuilder.PHASE2_OBS_SIZE,
        })
        with pytest.raises(KeyError, match="perception_radius"):
            W40KEngine(config=cfg)


class TestDetectionRangeStrict:
    def test_missing_detection_range_raises(self):
        """`detection_range` absent des game_rules -> ConfigurationError, pas de repli sur 15.

        Aligne `_attacker_model_can_reach_squad` sur `valid_target_pool_build`
        (shooting_handlers), qui lit deja la cle en `require_key`.
        """
        from engine.phase_handlers.shared_utils import _attacker_model_can_reach_squad
        from shared.data_validation import ConfigurationError

        game_state: Dict[str, Any] = {
            "config": {"game_rules": {}},
            "inches_to_subhex": 5,
            "models_cache": {"2_1": {"col": 5, "row": 5, "alive": True}},
            "squad_models": {"2": ["2_1"]},
            "units_cache": {"2": {"player": 2, "alive": True}},
            "units": [{"id": 2, "player": 2, "hidden": True}],
        }
        attacker_model = {"id": "1_1", "unit_id": 1, "col": 0, "row": 0}

        with pytest.raises(ConfigurationError, match="detection_range"):
            _attacker_model_can_reach_squad(game_state, attacker_model, 0, 0, "2", 120)
