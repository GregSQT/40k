"""Tests unitaires — ActionDecoder : normalize, validate_mask, convert_gym_action."""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pytest

from engine.action_decoder import ActionDecoder, ActionValidationError
from engine.phase_handlers.shared_utils import build_units_cache


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
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
    }


def _base_config() -> Dict[str, Any]:
    return {
        "game_rules": {"engagement_zone": 1, "max_base_size_hex": 35},
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }


def _build_gs(units: List[Dict[str, Any]], phase: str, current_player: int = 1) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
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
# convert_gym_action — move phase
# ─────────────────────────────────────────────────────────────────────────────

class TestConvertGymActionMove:
    def _make_gs(self) -> Dict[str, Any]:
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _build_gs(units, "move", current_player=1)
        gs["move_activation_pool"] = [1]
        gs["units_moved"] = set()
        gs["units_fled"] = set()
        return gs

    def test_wait_returns_skip(self):
        """conv_move_wait : action=11 (wait) → {action: skip}."""
        d = _make_decoder()
        result = d.convert_gym_action(11, self._make_gs())
        assert result["action"] == "skip"
        assert "unitId" in result

    def test_fight_action_invalid_in_move(self):
        """conv_move_fight_invalid : action=10 (fight) interdit en move → invalid."""
        d = _make_decoder()
        result = d.convert_gym_action(10, self._make_gs())
        assert result["action"] == "invalid"
        assert "forbidden_in_move_phase" in result.get("error", "")

    def test_invalid_action_has_unit_id(self):
        """conv_move_invalid_uid : action invalide contient unitId."""
        d = _make_decoder()
        result = d.convert_gym_action(10, self._make_gs())
        assert "unitId" in result


# ─────────────────────────────────────────────────────────────────────────────
# convert_gym_action — shoot phase
# ─────────────────────────────────────────────────────────────────────────────

class TestConvertGymActionShoot:
    def _make_gs(self) -> Dict[str, Any]:
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _build_gs(units, "shoot", current_player=1)
        # Enrich unit 1 with required shoot fields (in-place, same dict object)
        units[0]["valid_target_pool"] = []
        units[0]["_can_advance"] = False
        units[0]["_shoot_activation_started"] = False
        gs["shoot_activation_pool"] = ["1"]
        gs["active_shooting_unit"] = None
        gs["units_advanced"] = set()
        return gs

    def test_wait_returns_wait(self):
        """conv_shoot_wait : action=11 → {action: wait}."""
        d = _make_decoder()
        result = d.convert_gym_action(11, self._make_gs())
        assert result["action"] == "wait"
        assert result.get("unitId") is not None

    def test_invalid_fight_action_in_shoot(self):
        """conv_shoot_fight_invalid : action=10 interdit en shoot → invalid."""
        d = _make_decoder()
        result = d.convert_gym_action(10, self._make_gs())
        assert result["action"] == "invalid"

    def _make_gs_can_advance(self) -> Dict[str, Any]:
        """Game state with _can_advance=True for unit 1."""
        gs = self._make_gs()
        gs["units"][0]["_can_advance"] = True
        return gs

    def _make_advance_mask(self) -> np.ndarray:
        """Mask with advance slots 12-15 enabled (bypass real mask computation)."""
        mask = np.zeros(31, dtype=bool)
        mask[11] = True  # wait
        mask[12] = mask[13] = mask[14] = mask[15] = True
        return mask

    def test_advance_slot_12_returns_aggressive(self):
        """conv_shoot_adv12 : slot 12 → advance avec strategy 0 (aggressive)."""
        d = _make_decoder()
        gs = self._make_gs_can_advance()
        mask = self._make_advance_mask()
        eligible = [gs["units"][0]]
        result = d.convert_gym_action(12, gs, action_mask=mask, eligible_units=eligible)
        assert result["action"] == "advance"
        assert result["advance_strategy"] == 0

    def test_advance_slot_13_returns_objective(self):
        """conv_shoot_adv13 : slot 13 → advance avec strategy 3 (objective)."""
        d = _make_decoder()
        gs = self._make_gs_can_advance()
        mask = self._make_advance_mask()
        eligible = [gs["units"][0]]
        result = d.convert_gym_action(13, gs, action_mask=mask, eligible_units=eligible)
        assert result["action"] == "advance"
        assert result["advance_strategy"] == 3

    def test_advance_slot_14_returns_defensive(self):
        """conv_shoot_adv14 : slot 14 → advance avec strategy 2 (defensive)."""
        d = _make_decoder()
        gs = self._make_gs_can_advance()
        mask = self._make_advance_mask()
        eligible = [gs["units"][0]]
        result = d.convert_gym_action(14, gs, action_mask=mask, eligible_units=eligible)
        assert result["action"] == "advance"
        assert result["advance_strategy"] == 2

    def test_advance_slot_15_returns_tactical(self):
        """conv_shoot_adv15 : slot 15 → advance avec strategy 1 (tactical)."""
        d = _make_decoder()
        gs = self._make_gs_can_advance()
        mask = self._make_advance_mask()
        eligible = [gs["units"][0]]
        result = d.convert_gym_action(15, gs, action_mask=mask, eligible_units=eligible)
        assert result["action"] == "advance"
        assert result["advance_strategy"] == 1

    def test_advance_slots_all_masked_when_cannot_advance(self):
        """mask_shoot_no_adv : _can_advance=False → mask[12..15]=False."""
        d = _make_decoder()
        gs = self._make_gs()  # _can_advance=False
        mask = d.get_action_mask(gs)
        assert len(mask) == 31
        for slot in [12, 13, 14, 15]:
            assert bool(mask[slot]) is False, f"mask[{slot}] should be False when cannot advance"

    def test_advance_slots_all_masked_when_can_advance(self):
        """mask_shoot_adv : _can_advance=True + not advanced → mask[12..15]=True."""
        d = _make_decoder()
        gs = self._make_gs_can_advance()
        gs["shoot_activation_pool"] = ["1"]
        gs["active_shooting_unit"] = "1"
        mask = d.get_action_mask(gs)
        assert len(mask) == 31
        for slot in [12, 13, 14, 15]:
            assert bool(mask[slot]) is True, f"mask[{slot}] should be True when can advance"

    def test_advance_slots_masked_when_already_advanced(self):
        """mask_shoot_adv_done : unité déjà avancée → mask[12..15]=False."""
        d = _make_decoder()
        gs = self._make_gs_can_advance()
        gs["units_advanced"] = {"1"}
        gs["shoot_activation_pool"] = ["1"]
        gs["active_shooting_unit"] = "1"
        mask = d.get_action_mask(gs)
        for slot in [12, 13, 14, 15]:
            assert bool(mask[slot]) is False, f"mask[{slot}] should be False when already advanced"


# ─────────────────────────────────────────────────────────────────────────────
# convert_gym_action — fight phase
# ─────────────────────────────────────────────────────────────────────────────

class TestConvertGymActionFight:
    def _make_gs(self) -> Dict[str, Any]:
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]  # engagés (dist 1)
        gs = _build_gs(units, "fight", current_player=1)
        # État fight V11 : unité 1 engagée → éligible (machine de sélection).
        gs["fight_subphase"] = "fight"
        gs["fight_step"] = "remaining"
        gs["fight_selector"] = 1
        gs["engaged_at_fight_step_start"] = {"1": True, "2": True}
        gs["units_selected_to_fight"] = set()
        gs["units_charged"] = set()
        return gs

    def test_fight_action_10_returns_fight(self):
        """conv_fight_10 : action=10 en fight → {action: fight}."""
        d = _make_decoder()
        result = d.convert_gym_action(10, self._make_gs())
        assert result["action"] == "fight"
        assert "unitId" in result

    def test_fight_unit_id_is_first_eligible(self):
        """conv_fight_uid : unitId correspond à la première unité éligible."""
        d = _make_decoder()
        gs = self._make_gs()
        result = d.convert_gym_action(10, gs)
        assert str(result["unitId"]) == "1"

    def test_move_action_invalid_in_fight(self):
        """conv_fight_move_invalid : action=0 (move) interdit en fight → invalid."""
        d = _make_decoder()
        result = d.convert_gym_action(0, self._make_gs())
        assert result["action"] == "invalid"


# ─────────────────────────────────────────────────────────────────────────────
# convert_gym_action — charge phase
# ─────────────────────────────────────────────────────────────────────────────

class TestConvertGymActionCharge:
    def _make_gs(self) -> Dict[str, Any]:
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 15, 10)]
        gs = _build_gs(units, "charge", current_player=1)
        gs["charge_activation_pool"] = [1]
        gs["active_charge_unit"] = None
        gs["units_fled"] = set()
        gs["units_cannot_charge"] = set()
        return gs

    def test_charge_action_9_returns_charge(self):
        """conv_charge_9 : action=9 → {action: charge}."""
        d = _make_decoder()
        result = d.convert_gym_action(9, self._make_gs())
        assert result["action"] == "charge"
        assert "unitId" in result

    def test_wait_in_charge_returns_skip(self):
        """conv_charge_wait : action=11 → {action: skip}."""
        d = _make_decoder()
        result = d.convert_gym_action(11, self._make_gs())
        assert result["action"] == "skip"

    def test_fight_action_invalid_in_charge(self):
        """conv_charge_fight_invalid : action=10 (fight) interdit en charge → invalid."""
        d = _make_decoder()
        result = d.convert_gym_action(10, self._make_gs())
        assert result["action"] == "invalid"


# ─────────────────────────────────────────────────────────────────────────────
# convert_gym_action — phase inconnue / cas limites
# ─────────────────────────────────────────────────────────────────────────────

class TestConvertGymActionEdgeCases:

    def test_unknown_phase_returns_advance_phase_when_no_units(self):
        """conv_unknown_no_units : phase inconnue, pas d'unités → advance_phase."""
        units = [_unit(1, 1, 5, 10)]
        gs = _build_gs(units, "move")
        gs["phase"] = "command"  # phase sans pool
        d = _make_decoder()
        result = d.convert_gym_action(11, gs)
        # Pas d'unités éligibles en command → advance_phase
        assert result["action"] in ("advance_phase", "skip")

    def test_action_space_size_is_31(self):
        """conv_space_31 : l'espace d'action est de 31 (0-30) en Phase 2."""
        d = _make_decoder()
        assert d.total_action_size == 31
        assert d.normalize_action_input(30, "shoot", "gym", 31) == 30
        with pytest.raises(ActionValidationError, match="out_of_range"):
            d.normalize_action_input(31, "shoot", "gym", 31)

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
# get_action_mask — fight phase mask
# ─────────────────────────────────────────────────────────────────────────────

class TestGetActionMaskFight:

    def test_fight_mask_has_action10_when_units_eligible(self):
        """mask_fight_10 : unité éligible en fight → mask[10]=True."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 15, 10)]
        gs = _build_gs(units, "fight", current_player=1)
        # État fight V11 : unité 1 a chargé → éligible.
        gs["fight_subphase"] = "fight"
        gs["fight_step"] = "remaining"
        gs["fight_selector"] = 1
        gs["engaged_at_fight_step_start"] = {}
        gs["units_selected_to_fight"] = set()
        gs["units_charged"] = {"1"}
        d = _make_decoder()
        mask = d.get_action_mask(gs)
        assert bool(mask[10]) is True

    def test_fight_mask_all_false_when_no_units(self):
        """mask_fight_empty : pas d'unités éligibles → tous False."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 15, 10)]
        gs = _build_gs(units, "fight", current_player=1)
        gs["fight_subphase"] = "alternating"
        gs["charging_activation_pool"] = []
        gs["active_alternating_activation_pool"] = []
        gs["non_active_alternating_activation_pool"] = []  # vide
        d = _make_decoder()
        mask = d.get_action_mask(gs)
        assert not any(mask)

    def test_move_mask_enables_directions_and_wait(self):
        """mask_move : phase move → mask[0-3]=True, mask[11]=True."""
        units = [_unit(1, 1, 5, 10)]
        gs = _build_gs(units, "move")
        gs["move_activation_pool"] = [1]
        d = _make_decoder()
        mask = d.get_action_mask(gs)
        for i in range(4):
            assert bool(mask[i]) is True
        assert bool(mask[11]) is True

    def test_charge_mask_enables_9_and_wait(self):
        """mask_charge : phase charge → mask[9]=True, mask[11]=True."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 15, 10)]
        gs = _build_gs(units, "charge")
        gs["charge_activation_pool"] = [1]
        gs["active_charge_unit"] = None
        gs["units_fled"] = set()
        gs["units_cannot_charge"] = set()
        d = _make_decoder()
        mask = d.get_action_mask(gs)
        assert bool(mask[9]) is True
        assert bool(mask[11]) is True


# ─────────────────────────────────────────────────────────────────────────────
# convert_gym_action — fight phase, sous-phases alternating
# ─────────────────────────────────────────────────────────────────────────────

class TestConvertGymActionFightAlternating:
    """Fight sous-phases alternating/alternating_non_active/alternating_active."""

    def _make_gs(self, subphase: str, pool: List[int]) -> Dict[str, Any]:
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 15, 10)]
        gs = _build_gs(units, "fight", current_player=1)
        # V11 : sous-phase fight unique ; les unités du pool sont rendues éligibles (chargées).
        # Le paramètre `subphase` (legacy V10) est ignoré.
        gs["fight_subphase"] = "fight"
        gs["fight_step"] = "remaining"
        gs["fight_selector"] = 1
        gs["engaged_at_fight_step_start"] = {}
        gs["units_selected_to_fight"] = set()
        gs["units_charged"] = {str(u) for u in pool}
        return gs

    def test_subphase_alternating_action10_returns_fight(self):
        """alt_fight : fight_subphase='alternating', action=10 → {action: fight}."""
        d = _make_decoder()
        gs = self._make_gs("alternating", [1])
        result = d.convert_gym_action(10, gs)
        assert result["action"] == "fight"
        assert "unitId" in result

    def test_subphase_alternating_non_active_action10_returns_fight(self):
        """alt_non_active_fight : fight_subphase='alternating_non_active', action=10 → {action: fight}."""
        d = _make_decoder()
        gs = self._make_gs("alternating_non_active", [1])
        result = d.convert_gym_action(10, gs)
        assert result["action"] == "fight"
        assert str(result["unitId"]) == "1"

    def test_subphase_alternating_active_action10_returns_fight(self):
        """alt_active_fight : fight_subphase='alternating_active', action=10 → {action: fight}."""
        d = _make_decoder()
        gs = self._make_gs("alternating_active", [1])
        gs["active_alternating_activation_pool"] = [1]
        result = d.convert_gym_action(10, gs)
        assert result["action"] == "fight"

    def test_subphase_alternating_empty_pool_advance_phase(self):
        """alt_empty : pool vide en fight alternating → advance_phase."""
        d = _make_decoder()
        gs = self._make_gs("alternating", [])  # pool vide
        result = d.convert_gym_action(10, gs)
        assert result["action"] == "advance_phase"

    def test_subphase_alternating_dead_unit_not_eligible(self):
        """alt_dead : unité morte dans le pool → filtrée → advance_phase."""
        d = _make_decoder()
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 15, 10)]
        units[0]["HP_CUR"] = 0  # unité 1 est morte
        gs = _build_gs(units, "fight", current_player=1)
        gs["fight_subphase"] = "alternating"
        gs["charging_activation_pool"] = []
        gs["active_alternating_activation_pool"] = []
        gs["non_active_alternating_activation_pool"] = [1]  # uid 1 dans le pool, mais HP=0
        # Mettre à jour units_cache HP à 0
        from engine.phase_handlers.shared_utils import update_units_cache_hp
        update_units_cache_hp(gs, "1", 0)
        result = d.convert_gym_action(10, gs)
        # L'unité morte est filtrée → pool vide → advance_phase
        assert result["action"] == "advance_phase"
