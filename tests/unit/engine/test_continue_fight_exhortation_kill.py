"""Invariants : cible tuée par Exhortation de Rage + inconsistance units_cache/squad_models.

1. _continue_squad_fight_after_selection : pool vide + target_slot fourni → combat à vide,
   pas de ValueError.
2. _manual_roll_fight_intent / _manual_roll_intent : target absent de units_cache → None,
   pas de crash à _build_manual_allocation:11216 ou shared_utils:10120.

Verrous ROUGE/VERT : tests écrits AVANT le fix, rouges avec l'ancienne logique.
"""

import pytest
import engine.phase_handlers.fight_handlers as fh
import engine.phase_handlers.shared_utils as su
import engine.phase_handlers.generic_handlers as gh
import engine.w40k_core as wcore
from engine.phase_handlers.fight_handlers import _manual_roll_fight_intent
from engine.phase_handlers.shared_utils import _manual_roll_intent


# ---------------------------------------------------------------------------
# Setup minimal
# ---------------------------------------------------------------------------

_SQUAD_ID = "CHAP"
_DEAD_ENEMY = "ENEMY"


def _gs():
    return {
        "units_cache": {_SQUAD_ID: {"player": 1}},
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 1,
        "pending_agent_decision": None,
        "models_cache": {},
        "squad_models": {_SQUAD_ID: []},
    }


class _FakeEngine:
    _continue_squad_fight_after_selection = wcore.W40KEngine._continue_squad_fight_after_selection
    _fight_v11_gym_settle = lambda self: None

    def __init__(self, gs):
        self.game_state = gs


# ---------------------------------------------------------------------------
# Invariant : cible tuée par Exhortation → combat à vide, pas de crash
# ---------------------------------------------------------------------------

def test_exhortation_kill_target_no_crash(monkeypatch):
    """ROUGE sans le fix : raise ValueError quand pool vide et target_slot fourni.

    Chemin production : escouade détruite → units_cache purgée →
    get_enemy_slot_mapping retourne [None] pour ce slot.
    """
    monkeypatch.setattr(fh, "_fight_v11_engaged_now", lambda gs, u: True)
    monkeypatch.setattr(fh, "_fight_build_valid_target_pool", lambda gs, u: [])
    # Production : slot 0 map None car l'escouade est purgée de units_cache
    monkeypatch.setattr(su, "get_enemy_slot_mapping", lambda gs, player: [None])
    monkeypatch.setattr(su, "squad_fight_restart_activation", lambda gs, sid: None)
    monkeypatch.setattr(
        fh, "build_manual_fight_allocation",
        lambda gs, sid: {"done": True, "waiting_for_player": False, "shoot_result": {}},
    )
    monkeypatch.setattr(
        gh, "end_activation",
        lambda gs, unit, *args, **kw: {"some": "result"},
    )
    monkeypatch.setattr(wcore, "require_unit_by_id", lambda gs, uid: {"id": uid, "player": 1})

    engine = _FakeEngine(_gs())
    # target_slot=0 pointe sur DEAD_ENEMY ; pool vide car tué par Exhortation
    ok, result = engine._continue_squad_fight_after_selection(_SQUAD_ID, target_slot=0)
    assert ok is True
    assert result.get("action") == "squad_fight"
    assert result.get("target_squad_id") is None, (
        "cible tuée → combat à vide, target_squad_id doit être None"
    )


# ---------------------------------------------------------------------------
# Invariant : target absent de units_cache → intent ignoré (pas de crash)
# ---------------------------------------------------------------------------

def test_manual_roll_fight_intent_returns_none_when_target_absent_from_units_cache():
    """ROUGE sans le fix : crash à shared_utils:11216 (units_cache[target_sid] absent).

    Inconsistance : squad_models['3'] non vide + models_cache vivant,
    mais units_cache['3'] absent (purgé sans destroy_model complet).
    Attendu : return None (cible considérée morte, intent ignoré).
    """
    gs = {
        "models_cache": {
            "atk#0": {"squad_id": "CHAP", "player": 1, "col": 0, "row": 0, "HP_CUR": 2},
            "tgt#0": {"squad_id": "3",    "player": 2, "col": 1, "row": 0, "HP_CUR": 1},
        },
        "squad_models": {"CHAP": ["atk#0"], "3": ["tgt#0"]},
        "units_cache": {"CHAP": {"player": 1}},  # "3" absent — inconsistance
        "unit_by_id": {
            "CHAP": {"id": "CHAP", "player": 1, "UNIT_RULES": []},
            "3":    {"id": "3",    "player": 2, "UNIT_RULES": []},
        },
        "squad_cache": {"3": {"model_count_at_start": 1}},
    }
    intent = {"model_id": "atk#0", "target_unit_id": "3", "n_attacks_resolved": 1, "weapon_index": 0}
    result = _manual_roll_fight_intent(gs, intent, {})
    assert result is None, "cible absente de units_cache → intent ignoré, pas de crash"


def test_manual_roll_intent_returns_none_when_target_absent_from_units_cache():
    """Jumeau tir : ROUGE sans le fix → crash à shared_utils:10120 (units_cache[target_sid] absent)."""
    gs = {
        "models_cache": {
            "atk#0": {"squad_id": "CHAP", "player": 1, "col": 0, "row": 0, "HP_CUR": 2,
                      "RNG_WEAPONS": [{"ATK": 1, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
                                       "WEAPON_RULES": [], "code": "gun", "display_name": "Gun"}]},
        },
        "squad_models": {"CHAP": ["atk#0"], "3": []},
        "units_cache": {"CHAP": {"player": 1}},  # "3" absent — inconsistance
        "unit_by_id": {
            "CHAP": {"id": "CHAP", "player": 1, "UNIT_RULES": []},
            "3":    {"id": "3",    "player": 2, "UNIT_RULES": []},
        },
        "squad_cache": {"3": {"model_count_at_start": 1}},
        # faction ability state minimal
        "oath_target": None, "waaagh_active": False, "waaagh_declared": False,
        "finest_hour_active_this_phase": set(), "finest_hour_used": set(),
        "suppression_active": False, "bonus_malus_cap": None,
    }
    intent = {"model_id": "atk#0", "target_unit_id": "3", "n_attacks_resolved": 1, "weapon_index": 0}
    result = _manual_roll_intent(gs, intent, {})
    assert result is None, "cible absente de units_cache → intent ignoré (jumeau tir)"
