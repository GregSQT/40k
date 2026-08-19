"""Verrou L13 — [HALF RANGE] dans step.log (24.25/24.30).

Vérifie que le tag [HALF RANGE] est émis sur la ligne de tir d'une arme portant
RAPID_FIRE ou MELTA lorsque la cible est à demi-portée, et absent sinon (arme hors
demi-portée ou arme sans ces règles).

Chaîne exercée intégralement :
  _manual_roll_intent (at_half_range)
  → _build_manual_allocation (atHalfRange)
  → _emit_squad_shoot_log (action_log atHalfRange)
  → _build_shot_details (at_half_range)
  → StepLogger.log_action → [HALF RANGE]

Cycle rouge→vert : commenter `shot_tags.append("[HALF RANGE]")` dans ai/step_logger.py
fait passer test_half_range_present_rapid_fire en rouge.
"""
from __future__ import annotations

import random
from typing import Any, Dict

import pytest

from engine.phase_handlers import shooting_handlers
from engine.phase_handlers import shared_utils as _su
from engine.phase_handlers.shared_utils import build_manual_shoot_allocation
from tests._state_invariants import turn_state_invariants

SHOOTER = (50, 50)
TARGET_NEAR = (80, 50)   # 30 subhexes < 60 (demi-portée 120/2) → HALF RANGE
TARGET_FAR = (160, 50)   # 110 subhexes > 60                    → PAS HALF RANGE
WEAPON_RNG = 120          # 24" × inches_to_subhex=5


def _uc(col: int, row: int, *, player: int, models: Dict | None = None, hp_cur: int = 9) -> Dict:
    entry: Dict[str, Any] = {
        "BASE_SHAPE": "round", "BASE_SIZE": 6, "col": col, "row": row,
        "occupied_hexes": set(), "VALUE": 10.0, "player": player, "HP_CUR": hp_cur,
    }
    if models:
        entry["occupied_hexes_by_model"] = dict(models)
        entry["floor_height_by_model"] = {mid: 0.0 for mid in models}
    return entry


def _game_state(weapon_rules: list, *, target: tuple) -> Dict:
    weapon = {"ATK": 1, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": WEAPON_RNG,
              "WEAPON_RULES": list(weapon_rules), "display_name": "Test Bolt Rifle"}
    attacker = {"id": "1#0", "squad_id": "1", "player": 0, "T": 4, "SHOOT_LEFT": 1,
                "ATTACK_LEFT": 1, "col": SHOOTER[0], "row": SHOOTER[1],
                "RNG_WEAPONS": [weapon], "CC_WEAPONS": []}
    models_cache: Dict[str, Any] = {
        "1#0": attacker,
        "101#0": {
            "id": "101#0", "squad_id": "101", "player": 1, "T": 4,
            "HP_CUR": 2, "HP_MAX": 2, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
            "role": None, "unitType": "AssaultIntercessor",
            "points_per_hp": 5.0, "VALUE": 10.0,
            "col": target[0], "row": target[1],
            "RNG_WEAPONS": [], "CC_WEAPONS": [],
        },
    }
    intent = {"model_id": "1#0", "target_unit_id": "101", "weapon_index": 0,
              "n_attacks_resolved": 1, "target_squad_size_at_declaration": 1}
    return {
        **turn_state_invariants(),
        "gym_training_mode": True,
        "turn": 1, "phase": "shoot",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": models_cache,
        "squad_models": {"1": ["1#0"], "101": ["101#0"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "101": {"model_count_at_start": 1}},
        "units_cache": {
            "1": _uc(*SHOOTER, player=0, models={"1#0": SHOOTER}),
            "101": _uc(*target, player=1, models={"101#0": target}, hp_cur=2),
        },
        "units": [{"id": "1", "player": 0, "unitType": "TestUnit"},
                  {"id": "101", "player": 1, "unitType": "AssaultIntercessor"}],
        "unit_by_id": {
            "1": {"id": "1", "UNIT_RULES": [], "deployed_on_turn": 0, "player": 0},
            "101": {"id": "101", "UNIT_RULES": [], "deployed_on_turn": 0, "player": 1,
                    "unit_keywords": []},
        },
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        "inches_to_subhex": 5,
        "moved_distance_by_model": {"1#0": 0.0},
        "board_cols": 200, "board_rows": 100,
        "config": {"game_rules": {"engagement_zone": 5}},
        "no_gym_allocation_model": True,
        "pending_squad_shoot_intents": {"1": [intent]},
    }


def _log_line(tmp_path, monkeypatch, weapon_rules: list, *, target: tuple) -> str:
    """Exécute le moteur et renvoie la première ligne step.log du tir produit."""
    from ai.step_logger import StepLogger
    from engine.w40k_core import W40KEngine

    seq = [3, 3, 4]  # touche (2+), blesse (3+), sauvegarde ratée

    def _fake(a: int, b: int) -> int:
        return seq.pop(0) if seq else 1

    monkeypatch.setattr(random, "randint", _fake)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los",
                        lambda gs, s, t: {"cover": False, "can_see": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    monkeypatch.setattr(shooting_handlers, "_is_adjacent_to_enemy_within_cc_range",
                        lambda gs, u: False)
    monkeypatch.setattr(_su, "_squad_is_in_enemy_er", lambda _gs, sid: False)
    monkeypatch.setattr(_su, "_squads_are_engaged", lambda _gs, a, b: False)

    gs = _game_state(weapon_rules, target=target)
    build_manual_shoot_allocation(gs, "1")

    shoot_logs = [l for l in gs["action_logs"] if l.get("type") == "shoot"]
    assert shoot_logs, "le moteur n'a émis aucun log de tir"
    raw_log = shoot_logs[0]

    shots = raw_log.get("shootDetails", [])
    assert shots, "shootDetails vide dans le log de tir"

    class _Bridge:
        def __init__(self) -> None:
            self.game_state = gs
            self._SHOT_RECORD_FIELD_MAP = W40KEngine._SHOT_RECORD_FIELD_MAP
            self._build_shot_details = W40KEngine._build_shot_details.__get__(self)
            self._models_segment_for_unit = W40KEngine._models_segment_for_unit.__get__(self)

    bridge = _Bridge()
    out = tmp_path / "half_range.log"
    logger = StepLogger(output_file=str(out), enabled=True, buffer_size=1)
    logger.episode_number = 1
    for shot in shots:
        logger.log_action(
            unit_id=raw_log["shooterId"], action_type="shoot", phase="shoot",
            player=1, success=True, step_increment=True,
            action_details=bridge._build_shot_details(raw_log, shot, 1, None),
        )
    logger._flush_buffer()
    lines = [l for l in out.read_text().splitlines() if " SHOOT : " in l]
    assert len(lines) == len(shots), (
        f"StepLogger n'a pas produit une ligne par jet ({len(lines)}/{len(shots)}) — "
        "un champ requis manque probablement dans le mapping"
    )
    return lines[0]


def test_half_range_present_rapid_fire(tmp_path, monkeypatch):
    """RAPID_FIRE:1 et cible à demi-portée → [HALF RANGE] dans la ligne step.log."""
    line = _log_line(tmp_path, monkeypatch, ["RAPID_FIRE:1"], target=TARGET_NEAR)
    assert "[HALF RANGE]" in line, f"[HALF RANGE] absent : {line!r}"


def test_half_range_absent_rapid_fire_far(tmp_path, monkeypatch):
    """RAPID_FIRE:1 mais cible hors demi-portée → [HALF RANGE] absent."""
    line = _log_line(tmp_path, monkeypatch, ["RAPID_FIRE:1"], target=TARGET_FAR)
    assert "[HALF RANGE]" not in line, f"[HALF RANGE] présent à tort : {line!r}"


def test_half_range_absent_no_rule(tmp_path, monkeypatch):
    """Arme sans RAPID_FIRE ni MELTA → [HALF RANGE] jamais émis, même à demi-portée."""
    line = _log_line(tmp_path, monkeypatch, [], target=TARGET_NEAR)
    assert "[HALF RANGE]" not in line, f"[HALF RANGE] présent à tort : {line!r}"
