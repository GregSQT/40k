"""Tests unitaires — ActionDecoder : normalize, validate_mask, masque legacy, hex de deploiement.

`convert_gym_action` (decodeur de l'ANCIEN espace d'actions) a ete supprime : le decodeur vivant
est `convert_squad_action`, verrouille par `test_agent_interface_contract.py`.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pytest

from engine.action_decoder import ActionDecoder, ActionValidationError
from engine.macro_intents import TOTAL_ACTION_SIZE
from engine.phase_handlers.shared_utils import build_units_cache
from tests._state_invariants import turn_state_invariants


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_decoder() -> ActionDecoder:
    return ActionDecoder(config={"observation_params": {"action_space_size": 31}})


def _unit(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": 3,
        "HP_MAX": 3,
        "VALUE": 50,
        "OC": 1,
        "T": 4,
        "ARMOR_SAVE": 3,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
    }


def _base_config() -> Dict[str, Any]:
    return {
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }


def _build_gs(units: List[Dict[str, Any]], phase: str, current_player: int = 1) -> Dict[str, Any]:
    gs: Dict[str, Any] = {**turn_state_invariants(),
        "phase": phase,
        "current_player": current_player,
        "board_cols": 25,
        "board_rows": 21,
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "config": _base_config(),
        "zone_intent_free_steps_remaining": 0,
        "objectives": [],
        "inches_to_subhex": 1,
        # Le moteur pose TOUJOURS ces compteurs au `reset` (V11 §0.46 axe A) et le decodeur
        # les lit en strict : une doublure qui les omet ne simule pas l'etat du moteur.
        ActionDecoder.DEPLOYMENT_CACHE_COUNTS_KEY: ActionDecoder.empty_deployment_cache_counts(),
    }
    build_units_cache(gs)
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# normalize_action_input
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeActionInput:
    def test_valid_int_returned(self):
        """norm_int : int valide retourné tel quel."""
        d = _make_decoder()
        assert d.normalize_action_input(5, "move", "gym", 13) == 5

    def test_zero_valid(self):
        """norm_zero : action=0 → valide."""
        d = _make_decoder()
        assert d.normalize_action_input(0, "move", "gym", 13) == 0

    def test_last_valid_action(self):
        """norm_boundary : action==size-1 → valide."""
        d = _make_decoder()
        assert d.normalize_action_input(12, "move", "gym", 13) == 12

    def test_numpy_int64_converted(self):
        """norm_numpy64 : numpy int64 converti en int."""
        d = _make_decoder()
        assert d.normalize_action_input(np.int64(3), "move", "gym", 13) == 3

    def test_numpy_int32_converted(self):
        """norm_numpy32 : numpy int32 converti en int."""
        d = _make_decoder()
        assert d.normalize_action_input(np.int32(7), "move", "gym", 13) == 7

    def test_numpy_array_scalar_converted(self):
        """norm_ndarray_1 : ndarray size=1 converti en int."""
        d = _make_decoder()
        assert d.normalize_action_input(np.array([4]), "move", "gym", 13) == 4

    def test_numpy_array_multielement_raises(self):
        """norm_ndarray_multi : ndarray size>1 → ActionValidationError invalid_shape."""
        d = _make_decoder()
        with pytest.raises(ActionValidationError) as exc:
            d.normalize_action_input(np.array([1, 2]), "move", "gym", 13)
        assert exc.value.code == "invalid_shape"

    def test_bool_raises(self):
        """norm_bool : bool → ActionValidationError invalid_type."""
        d = _make_decoder()
        with pytest.raises(ActionValidationError) as exc:
            d.normalize_action_input(True, "move", "gym", 13)
        assert exc.value.code == "invalid_type"

    def test_false_raises(self):
        """norm_false : False (bool) → ActionValidationError."""
        d = _make_decoder()
        with pytest.raises(ActionValidationError):
            d.normalize_action_input(False, "move", "gym", 13)

    def test_string_raises(self):
        """norm_str : str → ActionValidationError."""
        d = _make_decoder()
        with pytest.raises(ActionValidationError):
            d.normalize_action_input("5", "move", "gym", 13)

    def test_float_raises(self):
        """norm_float : float → ActionValidationError."""
        d = _make_decoder()
        with pytest.raises(ActionValidationError):
            d.normalize_action_input(3.0, "move", "gym", 13)

    def test_negative_raises_out_of_range(self):
        """norm_neg : action<0 → out_of_range."""
        d = _make_decoder()
        with pytest.raises(ActionValidationError) as exc:
            d.normalize_action_input(-1, "move", "gym", 13)
        assert exc.value.code == "out_of_range"

    def test_equal_size_raises_out_of_range(self):
        """norm_eq_size : action==size → out_of_range."""
        d = _make_decoder()
        with pytest.raises(ActionValidationError) as exc:
            d.normalize_action_input(13, "move", "gym", 13)
        assert exc.value.code == "out_of_range"

    def test_above_size_raises_out_of_range(self):
        """norm_above : action>size → out_of_range."""
        d = _make_decoder()
        with pytest.raises(ActionValidationError) as exc:
            d.normalize_action_input(99, "shoot", "gym", 13)
        assert exc.value.code == "out_of_range"


# ─────────────────────────────────────────────────────────────────────────────
# validate_action_against_mask
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateActionAgainstMask:
    def _mask(self, size: int, valid: List[int]) -> np.ndarray:
        m = np.zeros(size, dtype=bool)
        for i in valid:
            m[i] = True
        return m

    def test_valid_action_no_exception(self):
        """vmask_ok : action valide dans masque → pas d'exception."""
        d = _make_decoder()
        mask = self._mask(13, [0, 11])
        d.validate_action_against_mask(11, mask, "move", "gym")  # should not raise

    def test_masked_out_action_raises(self):
        """vmask_out : action masquée → masked_out."""
        d = _make_decoder()
        mask = self._mask(13, [11])
        with pytest.raises(ActionValidationError) as exc:
            d.validate_action_against_mask(10, mask, "fight", "gym")
        assert exc.value.code == "masked_out"

    def test_masked_out_includes_valid_actions_in_context(self):
        """vmask_ctx : contexte d'erreur contient valid_actions."""
        d = _make_decoder()
        mask = self._mask(13, [0, 11])
        with pytest.raises(ActionValidationError) as exc:
            d.validate_action_against_mask(5, mask, "move", "gym")
        assert 0 in exc.value.context["valid_actions"]
        assert 11 in exc.value.context["valid_actions"]

    def test_action_out_of_mask_length_raises(self):
        """vmask_oob : action>=len(mask) → out_of_range."""
        d = _make_decoder()
        mask = self._mask(5, [0, 1])
        with pytest.raises(ActionValidationError) as exc:
            d.validate_action_against_mask(10, mask, "move", "gym")
        assert exc.value.code == "out_of_range"

    def test_non_bool_mask_raises_type_error(self):
        """vmask_dtype : masque int → TypeError."""
        d = _make_decoder()
        mask = np.zeros(13, dtype=int)
        with pytest.raises(TypeError):
            d.validate_action_against_mask(0, mask, "move", "gym")

    def test_all_valid_mask_passes(self):
        """vmask_all : masque tout True → n'importe quelle action valide."""
        d = _make_decoder()
        mask = np.ones(13, dtype=bool)
        d.validate_action_against_mask(5, mask, "move", "gym")  # no raise

    def test_unit_id_in_context(self):
        """vmask_uid : unit_id passé → présent dans contexte d'erreur."""
        d = _make_decoder()
        mask = self._mask(13, [11])
        with pytest.raises(ActionValidationError) as exc:
            d.validate_action_against_mask(0, mask, "move", "gym", unit_id="unit_42")
        assert exc.value.context.get("unit_id") == "unit_42"


# ─────────────────────────────────────────────────────────────────────────────
# normalize_action_input — cas limites et taille d'action space
# ─────────────────────────────────────────────────────────────────────────────

class TestActionSpaceSizeAndEdgeCases:

    def test_action_space_size_is_derived_from_the_engine_not_the_config(self):
        """La taille de l'action space vient du plan d'actions du moteur, pas de la config.

        Remplace `conv_space_31`, qui verifiait que le decodeur OBEISSAIT au
        `observation_params.action_space_size` de la config. C'etait une 2e source de verite pour
        un fait que le moteur determine seul : elle ne pouvait qu'avoir tort (une config perimee se
        manifestait par un `IndexError` opaque au fond du masque). La cle n'est plus lue.
        """
        d = _make_decoder()  # config volontairement porteuse d'un action_space_size=31 obsolete
        assert d.total_action_size == TOTAL_ACTION_SIZE
        assert d.normalize_action_input(
            TOTAL_ACTION_SIZE - 1, "shoot", "gym", TOTAL_ACTION_SIZE
        ) == TOTAL_ACTION_SIZE - 1
        with pytest.raises(ActionValidationError, match="out_of_range"):
            d.normalize_action_input(TOTAL_ACTION_SIZE, "shoot", "gym", TOTAL_ACTION_SIZE)

    def test_action_minus_one_raises(self):
        """conv_neg_action : action=-1 → out_of_range."""
        d = _make_decoder()
        with pytest.raises(ActionValidationError, match="out_of_range"):
            d.normalize_action_input(-1, "move", "gym", 13)

    def test_float_action_raises(self):
        """conv_float_action : float → invalid_type."""
        d = _make_decoder()
        with pytest.raises(ActionValidationError, match="invalid_type"):
            d.normalize_action_input(3.0, "move", "gym", 13)

    def test_none_action_raises(self):
        """conv_none_action : None → invalid_type."""
        d = _make_decoder()
        with pytest.raises(ActionValidationError):
            d.normalize_action_input(None, "move", "gym", 13)

    def test_string_action_raises(self):
        """conv_str_action : '5' → invalid_type."""
        d = _make_decoder()
        with pytest.raises(ActionValidationError, match="invalid_type"):
            d.normalize_action_input("5", "move", "gym", 13)


# ─────────────────────────────────────────────────────────────────────────────
# Sélection d'hex de déploiement (actions tactiques 4-8)
#
# Rapatrié de `scripts/test_action_decoder_validation.py` (2026-07-26) : ce fichier vivait hors de
# `tests/`, donc n'était jamais collecté. Ses 3 autres cas (normalize int/numpy, rejet de type,
# validate_against_mask) étaient déjà couverts ci-dessus ; seule la divergence flanc gauche/droit
# ne l'était pas.
# ─────────────────────────────────────────────────────────────────────────────

class TestDeploymentHexSelection:
    @staticmethod
    def _make_gs() -> Dict[str, Any]:
        # Unités à la sentinelle (-1) : rien n'est encore déployé.
        units = [_unit(1, 1, -1, -1), _unit(2, 2, -1, -1)]
        for u in units:
            # Le plan de déploiement lit les mots-clés (INFANTRY = formation compacte au sol).
            u["UNIT_KEYWORDS"] = ["INFANTRY"]
        gs = _build_gs(units, "deployment")
        gs["objectives"] = [{"hexes": [(12, 10)]}]
        gs["terrain_areas"] = []  # aucun terrain : seule la géométrie du pool décide du flanc
        gs["deployment_state"] = {
            "current_deployer": 1,
            "deployment_pools": {
                1: [(0, 13), (4, 13), (8, 13), (16, 13), (24, 13)],
                2: [(0, 0), (4, 0), (8, 0), (16, 0), (24, 0)],
            },
            "deployable_units": {1: ["1"], 2: ["2"]},
            "deployed_units": set(),
        }
        return gs

    def test_left_and_right_flank_actions_diverge(self):
        """flancs : action 7 (flanc gauche) choisit un hex de colonne < action 8 (flanc droit)."""
        d = _make_decoder()
        gs = self._make_gs()
        valid_hexes = d._get_valid_deployment_hexes(gs, 1, "1")
        left_hex = d._select_deployment_hex_for_action(7, "1", gs, 1, valid_hexes)
        right_hex = d._select_deployment_hex_for_action(8, "1", gs, 1, valid_hexes)
        assert left_hex[0] < right_hex[0]
