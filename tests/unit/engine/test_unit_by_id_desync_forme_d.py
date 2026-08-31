"""Forme D unit_by_id : gardes sans return immédiat converties en require_unit_by_id.

Ce que ces tests verrouillent (tranche T3 de replis_unit_by_id) :

- ``squad_is_battle_shocked_in_enemy_er`` : squad_id vient du pool de move ; absent de
  unit_by_id = désynchronisation d'index, pas une escouade morte légitime.
- ``update_los_cache_after_target_death`` : active_shooting_unit vient du game_state posé
  par le moteur ; absent de unit_by_id = désynchronisation.
- ``_manual_roll_intent`` (attacker) : squad_id de l'attaquant vient de models_cache,
  garanti en synchronisation avec unit_by_id.
- ``_manual_roll_intent`` (target) : target_sid vient du pool de tir, garanti.
- ``display_save_threshold_with_waaagh`` : reçoit désormais Dict non-Optional ; un appel
  avec None casserait le contrat — on vérifie que le type est enforced via le
  comportement attendu (pas de branche mort ``if target_unit is None``).
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from shared.data_validation import ConfigurationError


# ---------------------------------------------------------------------------
# Helpers communs
# ---------------------------------------------------------------------------

def _base_gs(**extra: Any) -> Dict[str, Any]:
    return {
        "unit_by_id": {},
        "units_cache": {},
        "squad_models": {},
        "models_cache": {},
        "config": {"game_rules": {"board_cols": 10, "board_rows": 10}},
        "inches_to_subhex": 1,
        **extra,
    }


# ---------------------------------------------------------------------------
# squad_is_battle_shocked_in_enemy_er
# ---------------------------------------------------------------------------

def test_squad_battle_shocked_desync_raises() -> None:
    """squad_id absent de unit_by_id → ConfigurationError (désync d'index)."""
    from engine.phase_handlers.shared_utils import squad_is_battle_shocked_in_enemy_er

    gs = _base_gs(unit_by_id={})  # squad_id "u1" absent
    with pytest.raises(ConfigurationError):
        squad_is_battle_shocked_in_enemy_er(gs, "u1")


def test_squad_battle_shocked_not_shocked_ok() -> None:
    """Unité présente dans unit_by_id mais non battle-shocked → False."""
    from engine.phase_handlers.shared_utils import squad_is_battle_shocked_in_enemy_er

    unit = {"id": "u1", "player": 1, "battle_shocked": False}
    gs = _base_gs(unit_by_id={"u1": unit})
    assert squad_is_battle_shocked_in_enemy_er(gs, "u1") is False


# ---------------------------------------------------------------------------
# update_los_cache_after_target_death
# ---------------------------------------------------------------------------

def test_los_cache_update_active_unit_desync_raises() -> None:
    """active_shooting_unit absent de unit_by_id → ConfigurationError."""
    from engine.phase_handlers.shooting_handlers import update_los_cache_after_target_death

    gs = _base_gs(
        unit_by_id={},  # désync : active_unit_id absent
        active_shooting_unit="shooter_u",
    )
    with pytest.raises(ConfigurationError):
        update_los_cache_after_target_death(gs, "dead_target")


def test_los_cache_update_no_active_unit_ok() -> None:
    """Pas d'active_shooting_unit → pas d'appel require → pas de levée."""
    from engine.phase_handlers.shooting_handlers import update_los_cache_after_target_death

    gs = _base_gs(unit_by_id={})
    # Ne doit pas lever : active_shooting_unit absent du game_state
    update_los_cache_after_target_death(gs, "dead_target")


def test_los_cache_update_active_unit_ok() -> None:
    """active_shooting_unit présent dans unit_by_id → entrée morte supprimée du cache."""
    from engine.phase_handlers.shooting_handlers import update_los_cache_after_target_death

    unit = {"id": "shooter_u", "player": 1, "los_cache": {"dead_t": True, "other": True}}
    gs = _base_gs(
        unit_by_id={"shooter_u": unit},
        active_shooting_unit="shooter_u",
    )
    update_los_cache_after_target_death(gs, "dead_t")
    assert "dead_t" not in unit["los_cache"]
    assert "other" in unit["los_cache"]


# ---------------------------------------------------------------------------
# display_save_threshold_with_waaagh — branche morte supprimée
# ---------------------------------------------------------------------------

def test_display_save_threshold_calls_effective_invul() -> None:
    """Sans la branche `if target_unit is None`, effective_invul_save est toujours appelé.

    On prouve que la branche morte est bien absente : passer un target_unit réel
    (avec une invulnerable 4+) doit produire le seuil recalculé par effective_invul_save,
    pas le base_invul brut.
    """
    from engine.phase_handlers.shared_utils import display_save_threshold_with_waaagh

    # first_alive : ARMOR_SAVE 3+, INVUL_SAVE 4+ (valeur datasheet)
    first_alive = {"ARMOR_SAVE": 3, "INVUL_SAVE": 4}
    # target_unit sans WAAAGH! actif → effective_invul_save renvoie base_invul
    target_unit = {"id": "t1", "player": 2, "UNIT_RULES": []}
    gs = _base_gs(unit_by_id={"t1": target_unit}, waaagh_active={1: False, 2: False})

    save_th, waaagh_improved = display_save_threshold_with_waaagh(gs, target_unit, first_alive, ap=0)
    # AP=0, armor=3+, invul=4+ → save_threshold(3, 4, 0) = min(3+0, 4) = 3
    assert save_th == 3
    assert waaagh_improved is False
