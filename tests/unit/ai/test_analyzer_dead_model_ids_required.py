"""T1 — dead_model_ids_episode est obligatoire quand alloc_model_id est fourni.

Régression verrouillée (2026-08-19). Sans l'assert, passer dead_model_ids_episode=None avec
alloc_model_id non-None faisait sauter la garde et incrémentait alloc_model_unknown à tort
pour tout socle DEAD-before-SHOOT — faux positif silencieux, aucun rapport d'erreur.
"""
from __future__ import annotations

import pytest

from ai.analyzer import _apply_damage_and_handle_death


def _stub_living(u: str) -> list:
    return []


def test_assert_si_alloc_model_id_sans_dead_model_ids_episode() -> None:
    """Passer alloc_model_id sans dead_model_ids_episode → AssertionError explicite."""
    unit_hp = {"1": 3}
    unit_models_alive = {"1": 1}
    unit_model_hp = {"1": {"1#0": 3}}
    stats: dict = {"state_resync": {"alloc_model_unknown": 0}, "wounded_enemies": {1: set(), 2: set()}}

    with pytest.raises(AssertionError, match="dead_model_ids_episode"):
        _apply_damage_and_handle_death(
            target_id="1",
            attacker_id="2",
            damage=1,
            player=1,
            turn=1,
            phase="SHOOT",
            line_number=1,
            current_episode_num=1,
            line_text="",
            dead_units_current_episode=set(),
            unit_hp=unit_hp,
            unit_models_alive=unit_models_alive,
            unit_model_hp=unit_model_hp,
            ordered_living_mids=_stub_living,
            unit_hp_squad_max={"1": 3},
            unit_types={"1": "Marine"},
            unit_positions={"1": (0, 0)},
            unit_deaths=[],
            unit_kill_context={},
            stats=stats,
            alloc_model_id="1#0",
            dead_model_ids_episode=None,
        )
