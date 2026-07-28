"""Tests unitaires — ObservationBuilder : validation de la config d'observation.

Les blocs qui verrouillaient `_calculate_wound_target`, `_calculate_expected_damage` et
`_calculate_favorite_target` ont été retirés avec le pipeline mono-figurine 359-d : ces
méthodes n'existent plus. La table de blessure vive est celle des handlers
(`shooting_handlers._calculate_wound_target`), déjà couverte par ses propres tests.
"""

from __future__ import annotations

import pytest

from engine.observation_builder import ObservationBuilder


def _make_builder() -> ObservationBuilder:
    """Instance minimale avec config obligatoire."""
    config = {
        "observation_params": {
            "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET,
        }
    }
    return ObservationBuilder(config)


# ─────────────────────────────────────────────────────────────────────────────
# ObservationBuilder __init__ validation
# ─────────────────────────────────────────────────────────────────────────────

class TestObsBuilderInit:
    def test_missing_observation_params_raises(self):
        """obs_init_missing : config sans observation_params → KeyError."""
        with pytest.raises(KeyError):
            ObservationBuilder(config={})

    def test_missing_obs_size_raises(self):
        """obs_init_no_size : observation_params non vide mais sans obs_size → KeyError.

        Le dict doit être NON VIDE : un dict vide échouerait sur le contrôle précédent
        (`observation_params` absent) et ne prouverait pas que `obs_size` est exigé.
        """
        with pytest.raises(KeyError, match="obs_size"):
            ObservationBuilder(config={"observation_params": {"unused": 1}})

    def test_valid_config_initializes(self):
        """obs_init_ok : config minimale valide → instance créée.

        `obs_size` est le SEUL paramètre d'observation restant : les anciens
        `perception_radius` / `max_nearby_units` / `max_valid_targets` ne servaient qu'au
        pipeline mono-figurine et ont été supprimés avec lui.
        """
        b = _make_builder()
        assert b.obs_size == ObservationBuilder.SQUAD_OBS_SIZE_TARGET
