"""Tests unitaires — L10 placement de charge comme décision d'agent.

Couvre :
- `charge_build_valid_plan(intent=k)` : les intentions produisent des plans valides.
- `arm_charge_placement_decision` : 5 options posées, options_cont 2D, pending stocké.
- `apply_charge_placement_decision` : plan retourné, pending consommé, errors explicites.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from engine.phase_handlers.charge_handlers import (
    CHARGE_PLACEMENT_INTENT_COUNT,
    CHARGE_PLACEMENT_PENDING_KEY,
    arm_charge_placement_decision,
    apply_charge_placement_decision,
)
from engine.phase_handlers.shared_utils import (
    build_units_cache,
    build_enemy_adjacent_hexes,
    charge_build_valid_plan,
)
from tests._state_invariants import turn_state_invariants, unit_invariants


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _unit(uid: str, player: int, col: int, row: int, **kwargs: Any) -> Dict[str, Any]:
    return {
        **unit_invariants(),
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": 3,
        "HP_MAX": 3,
        "VALUE": 100,
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
        **kwargs,
    }


def _config() -> Dict[str, Any]:
    return {
        "game_rules": {
            "engagement_zone": 1,
            "engagement_zone_vertical": 5,
            "max_base_size_hex": 35,
        },
        "charge": {"charge_max_distance": 12},
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        "move": {
            # La charge traverse toujours l'EZ ennemie (11.04) — sinon aucune charge ne peut
            # atteindre les cellules d'engagement, et tous les plans retournent None.
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
    }


def _make_gs(
    units: List[Dict[str, Any]],
    current_player: int = 1,
) -> Dict[str, Any]:
    """État minimal pour les tests de placement de charge.

    `build_units_cache` génère automatiquement `squad_models` et `models_cache`
    (clés auto : `<unit_id>#<index>`). Ne pas les pré-remplir avant l'appel.
    """
    gs: Dict[str, Any] = {
        **turn_state_invariants(),
        "config": _config(),
        "board_cols": 30,
        "board_rows": 25,
        "current_player": current_player,
        "phase": "charge",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_charged": set(),
        "units_cannot_charge": set(),
        "_unit_move_version": 0,
        "inches_to_subhex": 1,
        "_fly_declared_charge": {},
        "objectives": [],
        "pending_agent_decision": None,
    }
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, 1)
    build_enemy_adjacent_hexes(gs, 2)
    return gs


def _ctx(target: str = "tgt") -> Dict[str, Any]:
    return {
        "target_squad_id": target,
        "target_squad_ids": [target],
        "charge_from": None,
        "charge_target": None,
        "charge_is_pair": False,
        "charge_is_fly": False,
        "charge_ability": None,
        "charge_rule_marker": "",
        "charge_roll": 8,
        "charge_roll_initial": None,
        "unit_player": 1,
    }


# ─────────────────────────────────────────────────────────────────────────────
# charge_build_valid_plan — intent variants
# ─────────────────────────────────────────────────────────────────────────────

class TestChargeBuildValidPlanIntents:
    """Toutes les intentions 0–4 produisent des plans valides ou None sans crash."""

    def _gs(self) -> Dict[str, Any]:
        # Attaquant en (3,5), cible en (8,5) : distance 5, budget 8 → charge réussie.
        return _make_gs([_unit("att", 1, 3, 5), _unit("tgt", 2, 8, 5)])

    def test_intent0_returns_plan(self) -> None:
        """intent=0 (Serré) : plan valide (régression — comportement actuel intact)."""
        gs = self._gs()
        plan = charge_build_valid_plan(gs, "att", ["tgt"], charge_roll=10, intent=0)
        assert plan is not None, "intent=0 doit retourner un plan"

    def test_intent1_no_crash(self) -> None:
        """intent=1 (Objectif) : pas de crash, plan ou None."""
        gs = self._gs()
        plan = charge_build_valid_plan(gs, "att", ["tgt"], charge_roll=10, intent=1)
        # Pas d'objectifs dans ce scénario → replie sur intent=0 ; le résultat est plan ou None.
        assert plan is not None  # sans objectif, même que intent=0

    def test_intent2_no_crash(self) -> None:
        """intent=2 (Isolation) : pas de crash."""
        gs = self._gs()
        plan = charge_build_valid_plan(gs, "att", ["tgt"], charge_roll=10, intent=2)
        assert plan is not None

    def test_intent3_no_crash(self) -> None:
        """intent=3 (Pénétration) : pas de crash."""
        gs = self._gs()
        plan = charge_build_valid_plan(gs, "att", ["tgt"], charge_roll=10, intent=3)
        assert plan is not None

    def test_intent4_returns_plan(self) -> None:
        """intent=4 (Étalé) : plan valide retourné."""
        gs = self._gs()
        plan = charge_build_valid_plan(gs, "att", ["tgt"], charge_roll=10, intent=4)
        assert plan is not None, "intent=4 (Étalé) doit retourner un plan"

    def test_unknown_intent_no_crash(self) -> None:
        """Un intent hors [0-4] utilise la clé par défaut (Serré) sans erreur."""
        gs = self._gs()
        plan = charge_build_valid_plan(gs, "att", ["tgt"], charge_roll=10, intent=99)
        assert plan is not None


# ─────────────────────────────────────────────────────────────────────────────
# arm_charge_placement_decision
# ─────────────────────────────────────────────────────────────────────────────

class TestArmChargePlacementDecision:
    def _gs(self) -> Dict[str, Any]:
        return _make_gs([_unit("att", 1, 3, 5), _unit("tgt", 2, 8, 5)])

    def _plan_0(self, gs: Dict[str, Any]) -> List[Any]:
        plan = charge_build_valid_plan(gs, "att", ["tgt"], charge_roll=8)
        assert plan is not None, "le scénario de base doit produire un plan valide"
        return plan

    def test_sets_pending_agent_decision(self) -> None:
        """arm_charge_placement_decision pose pending_agent_decision dans game_state."""
        gs = self._gs()
        arm_charge_placement_decision(gs, "att", ["tgt"], 8, self._plan_0(gs), context=_ctx())
        assert gs.get("pending_agent_decision") is not None

    def test_decision_type_is_charge_placement(self) -> None:
        """La décision posée a le type 'charge_placement' (clé 'type' dans le dict)."""
        gs = self._gs()
        arm_charge_placement_decision(gs, "att", ["tgt"], 8, self._plan_0(gs), context=_ctx())
        assert gs["pending_agent_decision"]["type"] == "charge_placement"

    def test_exactly_5_options(self) -> None:
        """arm_charge_placement_decision pose exactement 5 options (CHARGE_PLACEMENT_INTENT_COUNT)."""
        gs = self._gs()
        arm_charge_placement_decision(gs, "att", ["tgt"], 8, self._plan_0(gs), context=_ctx())
        options = gs["pending_agent_decision"]["options"]
        assert len(options) == CHARGE_PLACEMENT_INTENT_COUNT == 5

    def test_options_cont_shape(self) -> None:
        """options_cont a la forme (5, 2) : 2 scalaires normalisés [0,1] par intention."""
        gs = self._gs()
        arm_charge_placement_decision(gs, "att", ["tgt"], 8, self._plan_0(gs), context=_ctx())
        opts_cont = gs["pending_agent_decision"].get("options_cont")
        assert opts_cont is not None, "options_cont doit être présent"
        assert len(opts_cont) == 5
        for row in opts_cont:
            assert len(row) == 2, f"chaque ligne doit avoir 2 scalaires, got {len(row)}"
            for v in row:
                assert 0.0 <= v <= 1.0, f"scalaire hors [0,1] : {v}"

    def test_pending_key_stored_with_5_plans(self) -> None:
        """_charge_placement_pending contient 5 plans (un par intention)."""
        gs = self._gs()
        arm_charge_placement_decision(gs, "att", ["tgt"], 8, self._plan_0(gs), context=_ctx())
        assert CHARGE_PLACEMENT_PENDING_KEY in gs
        pending = gs[CHARGE_PLACEMENT_PENDING_KEY]
        assert "plans" in pending
        assert len(pending["plans"]) == CHARGE_PLACEMENT_INTENT_COUNT

    def test_plan_0_is_passed_plan(self) -> None:
        """Le premier plan dans pending est exactement plan_0 fourni par l'appelant."""
        gs = self._gs()
        plan_0 = self._plan_0(gs)
        arm_charge_placement_decision(gs, "att", ["tgt"], 8, plan_0, context=_ctx())
        assert gs[CHARGE_PLACEMENT_PENDING_KEY]["plans"][0] is plan_0


# ─────────────────────────────────────────────────────────────────────────────
# apply_charge_placement_decision
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyChargePlacementDecision:
    def _gs_armed(self) -> Dict[str, Any]:
        gs = _make_gs([_unit("att", 1, 3, 5), _unit("tgt", 2, 8, 5)])
        plan_0 = charge_build_valid_plan(gs, "att", ["tgt"], charge_roll=8)
        assert plan_0 is not None
        arm_charge_placement_decision(gs, "att", ["tgt"], 8, plan_0, context=_ctx())
        return gs

    def test_returns_plan_for_choice_0(self) -> None:
        """plan_index=0 retourne le plan 0 (Serré) non vide."""
        gs = self._gs_armed()
        plan, ctx = apply_charge_placement_decision(gs, "att", plan_index=0)
        assert isinstance(plan, list)
        assert len(plan) > 0

    def test_returns_context(self) -> None:
        """apply retourne le contexte passé à arm."""
        gs = self._gs_armed()
        plan, ctx = apply_charge_placement_decision(gs, "att", plan_index=0)
        assert ctx["target_squad_id"] == "tgt"
        assert ctx["charge_roll"] == 8

    def test_pending_key_removed_after_apply(self) -> None:
        """_charge_placement_pending est retiré après apply."""
        gs = self._gs_armed()
        assert CHARGE_PLACEMENT_PENDING_KEY in gs
        apply_charge_placement_decision(gs, "att", plan_index=0)
        assert CHARGE_PLACEMENT_PENDING_KEY not in gs

    def test_pending_agent_decision_consumed(self) -> None:
        """pending_agent_decision est None après apply."""
        gs = self._gs_armed()
        apply_charge_placement_decision(gs, "att", plan_index=0)
        assert gs.get("pending_agent_decision") is None

    def test_plan_index_negative_raises_value_error(self) -> None:
        """plan_index négatif → ValueError explicite (T1 : pas de silent fallback)."""
        gs = self._gs_armed()
        with pytest.raises(ValueError, match="plan_index"):
            apply_charge_placement_decision(gs, "att", plan_index=-1)

    def test_plan_index_oob_raises_value_error(self) -> None:
        """plan_index >= 5 → ValueError explicite."""
        gs = self._gs_armed()
        # On consomme avec 0 pour ne pas avoir de plan_index=-1 qui lève.
        # Puis on réarme pour le second test.
        gs2 = _make_gs([_unit("att", 1, 3, 5), _unit("tgt", 2, 8, 5)])
        plan_0 = charge_build_valid_plan(gs2, "att", ["tgt"], charge_roll=8)
        assert plan_0 is not None
        arm_charge_placement_decision(gs2, "att", ["tgt"], 8, plan_0, context=_ctx())
        with pytest.raises(ValueError, match="plan_index"):
            apply_charge_placement_decision(gs2, "att", plan_index=CHARGE_PLACEMENT_INTENT_COUNT)

    def test_absent_pending_raises_runtime_error(self) -> None:
        """apply sans arm préalable → RuntimeError explicite (T1 : donnée obligatoire absente)."""
        gs = _make_gs([_unit("att", 1, 3, 5), _unit("tgt", 2, 8, 5)])
        with pytest.raises(RuntimeError, match="absent"):
            apply_charge_placement_decision(gs, "att", plan_index=0)

    def test_returns_plan_for_choice_4(self) -> None:
        """plan_index=4 retourne le plan Étalé non vide."""
        gs = self._gs_armed()
        plan, ctx = apply_charge_placement_decision(gs, "att", plan_index=4)
        assert isinstance(plan, list)
        assert len(plan) > 0
