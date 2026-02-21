#!/usr/bin/env python3
"""
Targeted regression tests for ActionDecoder validation and deployment scoring.
Run with: python -m unittest scripts.test_action_decoder_validation
"""

import unittest
import numpy as np

from engine.action_decoder import ActionDecoder, ActionValidationError


class TestActionDecoderValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.decoder = ActionDecoder(config={})

    def test_normalize_accepts_int_and_numpy_scalar(self) -> None:
        self.assertEqual(
            self.decoder.normalize_action_input(4, "deployment", "test", 13),
            4,
        )
        self.assertEqual(
            self.decoder.normalize_action_input(np.int64(7), "shoot", "test", 13),
            7,
        )

    def test_normalize_rejects_invalid_type(self) -> None:
        with self.assertRaises(ActionValidationError):
            self.decoder.normalize_action_input("4", "deployment", "test", 13)
        with self.assertRaises(ActionValidationError):
            self.decoder.normalize_action_input(True, "deployment", "test", 13)
        with self.assertRaises(ActionValidationError):
            self.decoder.normalize_action_input(np.array([1, 2]), "deployment", "test", 13)

    def test_validate_action_against_mask(self) -> None:
        mask = np.zeros(13, dtype=bool)
        mask[4] = True
        self.decoder.validate_action_against_mask(4, mask, "deployment", "test", "1")
        with self.assertRaises(ActionValidationError):
            self.decoder.validate_action_against_mask(5, mask, "deployment", "test", "1")


class TestDeploymentScoring(unittest.TestCase):
    def setUp(self) -> None:
        self.decoder = ActionDecoder(config={})
        self.game_state = {
            "phase": "deployment",
            "wall_hexes": [],
            "objectives": [{"hexes": [(12, 10)]}],
            "deployment_state": {
                "current_deployer": 1,
                "deployment_pools": {
                    1: [(0, 13), (4, 13), (8, 13), (16, 13), (24, 13)],
                    2: [(0, 0), (4, 0), (8, 0), (16, 0), (24, 0)],
                },
                "deployable_units": {1: ["1"], 2: ["2"]},
                "deployed_units": set(),
            },
            "units": [
                {"id": "1", "player": 1, "col": -1, "row": -1, "HP_CUR": 1},
                {"id": "2", "player": 2, "col": -1, "row": -1, "HP_CUR": 1},
            ],
            "units_cache": {
                "1": {"col": -1, "row": -1, "HP_CUR": 1, "player": 1},
                "2": {"col": -1, "row": -1, "HP_CUR": 1, "player": 2},
            },
        }

    def test_left_and_right_flank_actions_diverge(self) -> None:
        valid_hexes = self.decoder._get_valid_deployment_hexes(self.game_state, 1)
        left_hex = self.decoder._select_deployment_hex_for_action(7, "1", self.game_state, 1, valid_hexes)
        right_hex = self.decoder._select_deployment_hex_for_action(8, "1", self.game_state, 1, valid_hexes)
        self.assertLess(left_hex[0], right_hex[0])


if __name__ == "__main__":
    unittest.main()
