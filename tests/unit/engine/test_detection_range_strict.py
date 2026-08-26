"""Verrou : `detection_range` est lu en `require_key`, sans repli sur une valeur en dur.

Aligne `_attacker_model_can_reach_squad` sur `valid_target_pool_build` (shooting_handlers), qui
lit deja la cle strictement. Un repli sur 15 pouces aurait fait « voir » une unite cachee sur un
plateau ou la portee de detection reelle est autre — sans aucun signal.

Ce test vivait dans `test_perception_radius_single_source.py`, supprime le 2026-07-28 : son
sujet (`perception_radius` et sa mise a l'echelle) n'existe plus, ce parametre etant propre au
pipeline mono-figurine.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest


class TestDetectionRangeStrict:
    def test_missing_detection_range_raises(self):
        """`detection_range` absent des game_rules -> ConfigurationError, pas de repli sur 15."""
        from engine.phase_handlers.shared_utils import _attacker_model_can_reach_squad
        from shared.data_validation import ConfigurationError

        game_state: Dict[str, Any] = {
            "config": {"game_rules": {}},
            "inches_to_subhex": 5,
            "models_cache": {"2_1": {"col": 5, "row": 5, "alive": True}},
            "squad_models": {"2": ["2_1"]},
            "units_cache": {"2": {"player": 2, "alive": True}},
            "units": [{"id": 2, "player": 2, "hidden": True}],
            "unit_by_id": {"2": {"id": 2, "player": 2, "hidden": True}},
        }
        attacker_model = {"id": "1_1", "unit_id": 1, "col": 0, "row": 0}

        with pytest.raises(ConfigurationError, match="detection_range"):
            _attacker_model_can_reach_squad(game_state, attacker_model, 0, 0, "2", 120)
