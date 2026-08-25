"""Forme C unit_by_id : le ``continue`` silencieux est remplacé par require_unit_by_id.

Ce que ces tests verrouillent (tranche T1 de replis_unit_by_id) :

- ``compute_hidden_statuses`` : itère ``units_cache.keys()`` — une clé absente de
  ``unit_by_id`` est une désynchronisation d'index, pas une unité morte légitime.
- ``build_visible_cells_by_target`` : itère ``valid_targets`` — un id absent de
  ``unit_by_id`` est une désynchronisation, la cible ne doit pas disparaître en silence.
- ``_enqueue_rule_choice_candidates`` (W40KEngine) : ``unit_id`` vient de la config
  ``choice_timing_index`` ; un id absent de ``unit_by_id`` signale une config invalide.

Chaque test construit le désync à la main (units_cache / valid_targets / config ont l'id,
unit_by_id ne l'a pas) et prouve que ConfigurationError est levée plutôt que silencée.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from shared.data_validation import ConfigurationError


# ---------------------------------------------------------------------------
# compute_hidden_statuses
# ---------------------------------------------------------------------------

def _gs_hidden(*, unit_by_id: Dict[str, Any], units_cache: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "unit_by_id": unit_by_id,
        "units_cache": units_cache,
        "terrain_areas": {},
        "units_shot": set(),
        "units_shot_previous_turn": set(),
    }


def test_compute_hidden_statuses_desync_raises() -> None:
    """units_cache a 'u1' mais unit_by_id ne l'a pas → ConfigurationError."""
    from engine.phase_handlers.shooting_handlers import compute_hidden_statuses

    gs = _gs_hidden(
        unit_by_id={},  # vide — désync
        units_cache={"u1": {"occupied_hexes_by_model": {}, "player": 1}},
    )
    with pytest.raises(ConfigurationError):
        compute_hidden_statuses(gs)


def test_compute_hidden_statuses_sync_ok() -> None:
    """Quand unit_by_id et units_cache sont cohérents, aucune exception."""
    from engine.phase_handlers.shooting_handlers import compute_hidden_statuses

    unit = {
        "id": "u1",
        "player": 1,
        "hideable": False,
        "occupied_hexes_by_model": {},
    }
    gs = _gs_hidden(
        unit_by_id={"u1": unit},
        units_cache={"u1": {"occupied_hexes_by_model": {}, "player": 1}},
    )
    gs["units"] = [unit]
    compute_hidden_statuses(gs)  # ne lève pas


# ---------------------------------------------------------------------------
# build_visible_cells_by_target
# ---------------------------------------------------------------------------

def _minimal_shooter(uid: str, player: int) -> Dict[str, Any]:
    return {
        "id": uid, "player": player,
        "col": 0, "row": 0,
        "BASE_SIZE": 1, "BASE_SHAPE": "round",
        "squad_models": [],
    }


def test_build_visible_cells_desync_raises() -> None:
    """valid_targets contient un id absent de unit_by_id → ConfigurationError."""
    from engine.phase_handlers.shooting_handlers import build_visible_cells_by_target

    shooter = _minimal_shooter("shooter", 1)
    gs: Dict[str, Any] = {
        "unit_by_id": {},  # vide — désync
        "units_cache": {},
        "inches_to_subhex": 1,
        "config": {"game_rules": {"board_cols": 10, "board_rows": 10}},
    }
    with pytest.raises(ConfigurationError):
        build_visible_cells_by_target(gs, shooter, valid_targets=["target_missing"])


# ---------------------------------------------------------------------------
# _enqueue_rule_choice_candidates (W40KEngine method)
# ---------------------------------------------------------------------------

class _StubEngine:
    """Stub minimal qui expose les attributs/méthodes attendus par _enqueue_rule_choice_candidates."""

    def __init__(self, game_state: Dict[str, Any]) -> None:
        self.game_state = game_state

    def _initialize_rule_choice_runtime_state(self) -> None:
        from engine.agent_decision import initialize_agent_decision_state
        initialize_agent_decision_state(self.game_state)
        if "pending_rule_choice_queue" not in self.game_state:
            self.game_state["pending_rule_choice_queue"] = []
        if "active_rule_choice_prompt" not in self.game_state:
            self.game_state["active_rule_choice_prompt"] = None

    def _get_unit_rule_registry(self) -> Dict[str, Any]:
        return {}


def _gs_enqueue(unit_by_id: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "unit_by_id": unit_by_id,
        "units_cache": {},
        "turn": 1,
        "current_player": 1,
        "pending_rule_choice_queue": [],
        # Un entry qui passe tous les continues jusqu'au require_unit_by_id :
        # - trigger=phase_start, event_phase=fight → required_phase="fight" doit matcher
        # - unit_player=1, owner_event_player=1 → active_player_scope="owner" passe
        "choice_timing_index": {
            "phase_start": [
                {
                    "unit_id": "u_bad",
                    "rule_id": "some_rule",
                    "usage": "or",
                    "unit_player": 1,
                    "choice_timing": {
                        "phase": "fight",
                        "active_player_scope": "owner",
                    },
                    "grants_rule_ids": [],
                }
            ]
        },
    }


def test_enqueue_rule_choice_desync_raises() -> None:
    """unit_id de la config absent de unit_by_id → ConfigurationError."""
    from engine.w40k_core import W40KEngine

    gs = _gs_enqueue(unit_by_id={})  # u_bad absent
    stub = _StubEngine(gs)

    with pytest.raises(ConfigurationError):
        W40KEngine._enqueue_rule_choice_candidates(
            stub,  # type: ignore[arg-type]
            trigger="phase_start",
            event_phase="fight",
            event_player=1,
        )


def test_enqueue_rule_choice_sync_skips_dead() -> None:
    """Quand l'unité est dans unit_by_id mais morte (pas dans units_cache),
    la règle est écartée sans exception — is_unit_alive retourne False."""
    from engine.w40k_core import W40KEngine

    unit = {"id": "u_good", "player": 1, "UNIT_RULES": []}
    gs = _gs_enqueue(unit_by_id={"u_good": unit})
    # units_cache vide → is_unit_alive retourne False → loop continue sans lever
    gs["choice_timing_index"]["phase_start"][0]["unit_id"] = "u_good"
    stub = _StubEngine(gs)

    # Ne doit pas lever
    W40KEngine._enqueue_rule_choice_candidates(
        stub,  # type: ignore[arg-type]
        trigger="phase_start",
        event_phase="fight",
        event_player=1,
    )
    assert gs["pending_rule_choice_queue"] == []
