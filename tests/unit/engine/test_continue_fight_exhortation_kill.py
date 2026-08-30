"""_continue_squad_fight_after_selection — invariant : cible tuée par Exhortation de Rage.

Si Exhortation détruit la seule cible avant le combat (pool vide, target_slot fourni),
la fonction doit retourner un combat à vide sans lever ValueError.

Verrou ROUGE/VERT : test écrit AVANT le fix, rouge avec l'ancienne logique.
"""

import pytest
import engine.phase_handlers.fight_handlers as fh
import engine.phase_handlers.shared_utils as su
import engine.phase_handlers.generic_handlers as gh
import engine.w40k_core as wcore


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
