"""Regression — PvE move-phase freeze.

Root cause : `end_activation` pose `phase_complete=True` quand le pool se vide, mais ne
pose JAMAIS `next_phase`. La cascade de `_process_squad_action` exige `next_phase` pour
s'exécuter ; sans lui la phase reste bloquée à « move » avec un pool vide.

Côté frontend : `executeAITurn` sort de la boucle sur `activation_ended + phase_complete`
(ligne 9529) et `shouldTriggerAI` ne se réarme pas (pool vide → `hasEligibleAIUnits=false`).
L'auto-advance de `_build_observation_and_mask` n'est donc jamais appelé.

Fix : dériver `next_phase` depuis `current_phase` juste AVANT la cascade, dans
`_process_squad_action`, quand `phase_complete=True` mais `next_phase` absent.

Ce test vérifie l'invariant : après que le dernier AI squad a agi (squad_wait) en phase
de move, `game_state["phase"]` est "shoot" — la cascade a bien tourné.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.w40k_core import W40KEngine
from engine.phase_handlers.shared_utils import build_units_cache, build_enemy_adjacent_hexes
from tests._state_invariants import turn_state_invariants, unit_invariants
from tests.unit.engine._config_helpers import build_game_rules, build_move_rules


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _base_config() -> Dict[str, Any]:
    return {
        "game_rules": build_game_rules(engagement_zone=1, max_base_size_hex=35, cover_ratio=0.0),
        "move": build_move_rules(),
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }


def _unit(uid: int, player: int, col: int, row: int, has_ranged: bool = False) -> Dict[str, Any]:
    weapons = [{"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "RNG": 24, "NB": 1,
                "WEAPON_RULES": [], "display_name": "Bolter"}] if has_ranged else []
    return {**unit_invariants(),
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": 3,
        "HP_MAX": 3,
        "VALUE": 100,
        "OC": 1,
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
        "T": 4,
        "ARMOR_SAVE": 4,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": weapons,
        "CC_WEAPONS": [],
    }


def _make_move_gs(units: List[Dict[str, Any]], ai_pool_ids: List[str]) -> Dict[str, Any]:
    """Game-state minimal : phase move, `ai_pool_ids` = seules unités encore dans le pool."""
    gs: Dict[str, Any] = {**turn_state_invariants(),
        "config": _base_config(),
        "board_cols": 25,
        "board_rows": 21,
        "current_player": 2,
        "phase": "move",
        "wall_hexes": set(),
        "terrain_areas": [],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "console_logs": [],
        "debug_logs": [],
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 1,
        "units_moved": set(),
        "units_advanced": set(),
        "units_fled": set(),
        "units_shot": set(),
        "move_activation_pool": list(ai_pool_ids),
        "shoot_activation_pool": [],
        "charge_activation_pool": [],
        "hex_los_cache": {},
        "_unit_move_version": 0,
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, 2)
    return gs


def _engine(gs: Dict[str, Any]) -> W40KEngine:
    """Instance W40KEngine minimale : seul `_process_squad_action` est exercé."""
    eng = object.__new__(W40KEngine)
    eng.game_state = gs
    eng.config = gs["config"]
    eng.gym_training_mode = False
    eng.step_logger = None
    eng._movement_phase_initialized = False
    eng._shooting_phase_initialized = False
    eng.STEP_LOG_DRAINED_KEY = W40KEngine.STEP_LOG_DRAINED_KEY
    # Neutralise les méthodes hors scope du test.
    eng._check_game_over = lambda: False  # type: ignore[method-assign]
    eng._emit_next_rule_choice_prompt_if_needed = lambda: None  # type: ignore[method-assign]
    eng._get_unit_by_id = lambda uid: gs["unit_by_id"].get(str(uid))  # type: ignore[method-assign]
    return eng


# ─────────────────────────────────────────────────────────────────────────────
# Test
# ─────────────────────────────────────────────────────────────────────────────

def test_last_ai_squad_wait_in_move_triggers_shoot_phase():
    """Invariant clé : squad_wait sur le dernier AI squad du pool move → cascade → phase=shoot.

    Avant le fix : `end_activation` pose `phase_complete=True` sans `next_phase` → cascade
    s'arrête → phase reste « move » → PvE freezé.
    Après le fix : `next_phase="shoot"` dérivé → `shooting_phase_start` appelé → phase="shoot".
    """
    # P1 (humain) au loin, P2 (IA) avec arme de tir → éligible au shoot pool après la cascade.
    units = [_unit(1, 1, 3, 3, has_ranged=True), _unit(2, 2, 15, 15, has_ranged=True)]
    gs = _make_move_gs(units, ai_pool_ids=["2"])  # "2" est le seul AI squad restant
    eng = _engine(gs)

    # ROUGE attendu SANS le fix : phase resterait "move"
    success, result = eng._process_squad_action({"action": "squad_wait", "squad_id": "2"})

    assert success is True
    # Le pool est vidé.
    assert gs["move_activation_pool"] == []
    # La cascade a dérivé next_phase et l'a encodé dans le résultat.
    assert result.get("next_phase") == "shoot", (
        f"next_phase absent ou incorrect : {result}. "
        "Sans ce champ la cascade ne tourne pas → PvE freeze."
    )
    # La cascade a effectivement avancé la phase (shooting_phase_start appelé).
    assert gs["phase"] == "shoot", (
        f"Phase reste '{gs['phase']}' au lieu de 'shoot' : la cascade n'a pas tourné."
    )


def test_advance_phase_from_command_triggers_move_phase():
    """Invariant : advance_phase with from=command → next_phase=move in result and gs["phase"].

    La map hardcodée de _process_squad_action incluait command→move mais next_phase_map.get()
    ne couvrait pas les phases hors ordre (ex. fight). Le remplacement par get_phase_order()
    doit produire next_phase="move" pour from="command" (command n'est pas dans la phase_order
    ["move","shoot","charge","fight"] → idx=-1 → fallback "move").
    """
    units = [_unit(1, 1, 3, 3, has_ranged=True), _unit(2, 2, 15, 15, has_ranged=True)]
    gs = _make_move_gs(units, ai_pool_ids=[])
    gs["phase"] = "command"

    eng = _engine(gs)

    success, result = eng._process_squad_action({"action": "advance_phase", "from": "command"})

    assert success is True
    assert result.get("next_phase") == "move", (
        f"next_phase attendu 'move', obtenu : {result}"
    )
    assert gs["phase"] == "move", (
        f"Phase reste '{gs['phase']}' au lieu de 'move' : la cascade command→move n'a pas tourné."
    )
