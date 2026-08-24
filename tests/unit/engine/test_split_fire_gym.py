"""Split-fire gym (P3-8) — tests d'invariants.

Invariants vérifiés :
- `shoot_weapon_eligible_target_slots` retourne les slots ennemis atteignables par une arme j,
  avec activation démarrée (weapon_qty_max non nul).
- `shoot_weapon_remaining_eligible_slots` retourne les autres groupes d'armes éligibles.
- Decode SHOOT_WEAPON_SEL_SLOT → action `squad_shoot_weapon_sel`.
- Decode SHOOT_SLOT avec pending_sw armé → action `squad_shoot_split_target`.
- Decode SHOOT_SLOT SANS pending_sw → action `squad_shoot` (pas de régression).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from engine.weapons import get_weapons

_GAME_RULES = json.loads(
    (Path(__file__).parents[3] / "config" / "game_config.json").read_text()
)["game_rules"]

from engine.phase_handlers.shared_utils import (
    build_units_cache,
    init_pending_intents,
    squad_shooting_unit_activation_start,
    squad_shooting_type_choose,
    shoot_weapon_eligible_target_slots,
    shoot_weapon_remaining_eligible_slots,
    SHOOTING_TYPE_NORMAL,
)
from tests._state_invariants import turn_state_invariants, unit_invariants


# ─── Armes réelles de l'armory (deux profils distincts) ───────────────────────
STORM = get_weapons("SpaceMarine", ["storm_bolter"])[0]           # portée moyenne
LASCANNON = get_weapons("SpaceMarine", ["ballistus_lascannon"])[0]  # longue portée


def _m(col: int, row: int, weapons: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Figurine minimale avec armes ranged."""
    return {
        "col": col, "row": row, "VALUE": 25,
        "RNG_WEAPONS": weapons,
        "selectedRngWeaponIndex": 0,
    }


def _unit(uid: int, player: int, col: int, row: int,
          models: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        **unit_invariants(),
        "id": uid, "player": player, "col": col, "row": row,
        "HP_CUR": 3, "HP_MAX": 3, "VALUE": 100, "OC": 1,
        "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
        "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round",
        "MOVE": 6, "UNIT_RULES": [],
        "RNG_WEAPONS": [m["RNG_WEAPONS"][0] for m in models if m["RNG_WEAPONS"]],
        "CC_WEAPONS": [],
        "selectedRngWeaponIndex": 0, "selectedCcWeaponIndex": 0,
        "models": models,
    }


def _make_gs(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        **turn_state_invariants(),
        "config": {
            "game_rules": {
                **_GAME_RULES,
                "engagement_zone": 1,
                "engagement_zone_vertical": 5,
                "max_base_size_hex": 35,
            },
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 40,
        "board_rows": 30,
        "current_player": 1,
        "phase": "shoot",
        "wall_hexes": set(),
        "terrain_areas": [],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "console_logs": [],
        "debug_logs": [],
        "inches_to_subhex": 1,
        "units_advanced": set(),
    }
    build_units_cache(gs)
    init_pending_intents(gs)
    return gs


# ─── Scénario : 1 attaquant (Storm + Lascannon), 2 ennemis en portée ──────────

def _split_fire_scenario():
    """Attaquant (squad 1) avec Storm+Lascannon, 2 ennemis (squads 2 et 3) en portée."""
    # Figurine porteuse de Storm Bolter (portée ~24" → grands nombres en subhex)
    m_storm = _m(5, 5, [STORM])
    # Figurine porteuse de Lascannon (portée ~48")
    m_las = _m(5, 6, [LASCANNON])

    atk = _unit(1, 1, 5, 5, [m_storm, m_las])
    # Mettre tous les profils sur l'unité pour que le cache les trouve
    atk["RNG_WEAPONS"] = [STORM, LASCANNON]

    # Ennemis proches (dans la portée du Storm et du Lascannon)
    enemy1 = _unit(2, 2, 5, 10, [_m(5, 10, [STORM])])
    enemy1["RNG_WEAPONS"] = [STORM]
    enemy2 = _unit(3, 2, 8, 10, [_m(8, 10, [STORM])])
    enemy2["RNG_WEAPONS"] = [STORM]

    return _make_gs([atk, enemy1, enemy2])


# ─── Tests des helpers (activation démarrée requise) ──────────────────────────

class TestShootWeaponHelpers:
    def _gs_with_activation(self):
        gs = _split_fire_scenario()
        squad_shooting_unit_activation_start(gs, "1")
        squad_shooting_type_choose(gs, "1", SHOOTING_TYPE_NORMAL)
        return gs

    def test_eligible_target_slots_returns_list(self):
        """shoot_weapon_eligible_target_slots retourne un tuple (code, [slots]) non vide."""
        from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

        gs = self._gs_with_activation()
        enemy_slots = get_enemy_slot_mapping(gs, 1)

        code, slots = shoot_weapon_eligible_target_slots(gs, "1", 0, enemy_slots)

        assert isinstance(code, str) and code  # code non vide
        assert isinstance(slots, list)
        # Au moins un ennemi doit être atteignable
        assert len(slots) > 0, (
            f"aucune cible pour l'arme slot 0 ({code!r}) — vérifier la portée et la position"
        )

    def test_eligible_target_slots_out_of_range_raises(self):
        """slot hors [0, K) → ValueError."""
        from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

        gs = self._gs_with_activation()
        enemy_slots = get_enemy_slot_mapping(gs, 1)

        with pytest.raises(ValueError, match="slot.*hors des profils"):
            shoot_weapon_eligible_target_slots(gs, "1", 999, enemy_slots)

    def test_remaining_slots_excludes_except_slot(self):
        """shoot_weapon_remaining_eligible_slots n'inclut pas le slot exclu."""
        from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

        gs = self._gs_with_activation()
        enemy_slots = get_enemy_slot_mapping(gs, 1)

        remaining = shoot_weapon_remaining_eligible_slots(gs, "1", enemy_slots, except_slot=0)

        # Le slot 0 ne doit pas être dans remaining
        assert 0 not in remaining, f"slot 0 présent dans remaining {remaining}"


# ─── Tests de routage decode ──────────────────────────────────────────────────

class TestSplitFireDecode:
    """Invariant de routage : SHOOT_WEAPON_SEL_SLOT → squad_shoot_weapon_sel."""

    def _minimal_gs_for_decode(self) -> Dict[str, Any]:
        """Game-state minimal pour convert_squad_action en phase shoot."""
        units = [
            _unit(1, 1, 5, 5, [_m(5, 5, [STORM])]),
            _unit(2, 2, 5, 15, [_m(5, 15, [STORM])]),
        ]
        for u in units:
            u["RNG_WEAPONS"] = [STORM]
        gs = _make_gs(units)
        gs["enemy_slot_mapping"] = {1: ["2", None, None, None, None, None, None, None, None, None,
                                         None, None, None, None, None, None, None, None, None, None]}
        # Activer le pool de tir
        gs["shoot_activation_pool"] = ["1"]
        gs["units_shot"] = set()
        return gs

    def _decoder(self) -> "ActionDecoder":
        from engine.action_decoder import ActionDecoder
        return ActionDecoder({"game_rules": _GAME_RULES})

    def test_shoot_weapon_sel_slot_decodes_to_squad_shoot_weapon_sel(self):
        """SHOOT_WEAPON_SEL_SLOT j → action 'squad_shoot_weapon_sel' avec weapon_slot j."""
        from engine.action_decoder import PENDING_SHOOT_WEAPON_SEL_KEY
        from engine.macro_intents import SHOOT_WEAPON_SEL_SLOT_BASE

        gs = self._minimal_gs_for_decode()
        gs["current_player"] = 1
        gs["phase"] = "shoot"

        eligible_units = [{"id": "1", "player": 1}]

        result = self._decoder().convert_squad_action(
            SHOOT_WEAPON_SEL_SLOT_BASE,  # slot 0 = premier groupe d'arme
            gs,
            eligible_units=eligible_units,
        )

        assert result["action"] == "squad_shoot_weapon_sel", (
            f"SHOOT_WEAPON_SEL_SLOT_BASE doit décoder en 'squad_shoot_weapon_sel', "
            f"reçu {result!r}"
        )
        assert result["weapon_slot"] == 0
        assert result["squad_id"] == "1"

    def test_shoot_slot_with_pending_sw_decodes_to_split_target(self):
        """SHOOT_SLOT avec pending_sw armé → action 'squad_shoot_split_target'."""
        from engine.action_decoder import PENDING_SHOOT_WEAPON_SEL_KEY
        from engine.phase_handlers.shared_utils import SQUAD_ACTION_SHOOT_SLOT_BASE

        gs = self._minimal_gs_for_decode()
        gs[PENDING_SHOOT_WEAPON_SEL_KEY] = {
            "squad_id": "1",
            "shooting_type": SHOOTING_TYPE_NORMAL,
            "pending_weapon": "storm_bolter",
            "assignments": {},
            "remaining_weapon_slots": {},
            "eligible_target_slots": [0],
        }
        gs["current_player"] = 1
        gs["phase"] = "shoot"

        eligible_units = [{"id": "1", "player": 1}]

        result = self._decoder().convert_squad_action(
            SQUAD_ACTION_SHOOT_SLOT_BASE,
            gs,
            eligible_units=eligible_units,
        )

        assert result["action"] == "squad_shoot_split_target", (
            f"SHOOT_SLOT avec pending_sw armé doit décoder en 'squad_shoot_split_target', "
            f"reçu {result!r}"
        )
        assert result["target_slot"] == 0

    def test_shoot_slot_without_pending_sw_decodes_to_squad_shoot(self):
        """SHOOT_SLOT sans pending_sw → action 'squad_shoot' (pas de régression)."""
        from engine.phase_handlers.shared_utils import SQUAD_ACTION_SHOOT_SLOT_BASE

        gs = self._minimal_gs_for_decode()
        # Simuler un type de tir pour que resolve_squad_shooting_type retourne quelque chose
        gs["squad_shooting_type_choice"] = {"1": SHOOTING_TYPE_NORMAL}
        gs["current_player"] = 1
        gs["phase"] = "shoot"

        eligible_units = [{"id": "1", "player": 1}]

        result = self._decoder().convert_squad_action(
            SQUAD_ACTION_SHOOT_SLOT_BASE,
            gs,
            eligible_units=eligible_units,
        )

        assert result["action"] == "squad_shoot", (
            f"SHOOT_SLOT sans pending_sw doit décoder en 'squad_shoot', reçu {result!r}"
        )


# ─── Test total_action_size (mise à jour 1379→1389) ──────────────────────────

def test_total_action_size_updated():
    """TOTAL_ACTION_SIZE doit tenir compte de SHOOT_WEAPON_SEL_SLOT_COUNT (10)."""
    from engine.macro_intents import (
        TOTAL_ACTION_SIZE, SHOOT_WEAPON_SEL_SLOT_BASE, SHOOT_WEAPON_SEL_SLOT_COUNT,
    )

    assert TOTAL_ACTION_SIZE == SHOOT_WEAPON_SEL_SLOT_BASE + SHOOT_WEAPON_SEL_SLOT_COUNT, (
        f"TOTAL_ACTION_SIZE ({TOTAL_ACTION_SIZE}) ≠ "
        f"SHOOT_WEAPON_SEL_SLOT_BASE ({SHOOT_WEAPON_SEL_SLOT_BASE}) + "
        f"SHOOT_WEAPON_SEL_SLOT_COUNT ({SHOOT_WEAPON_SEL_SLOT_COUNT})"
    )
    assert TOTAL_ACTION_SIZE == 1389, (
        f"TOTAL_ACTION_SIZE attendu 1389, reçu {TOTAL_ACTION_SIZE}"
    )
