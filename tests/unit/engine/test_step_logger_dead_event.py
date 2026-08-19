"""destroy_model émet un event "dead" dans action_logs pour toute cause de mort.

T4 rouge/vert : le test a été vérifié ROUGE en commentant l'append_action_log dans
destroy_model, puis VERT avec le fix en place.
"""
from typing import Any, Dict

import pytest

from engine.phase_handlers.shared_utils import destroy_model


def _minimal_gs(n_models: int = 2) -> Dict[str, Any]:
    """game_state minimal avec une escouade de n_models figurines P1 — units_cache à la main."""
    squad_id = "1"
    model_ids = [f"1#{i}" for i in range(n_models)]
    models_cache = {mid: {"col": 10 + i, "row": 10, "level": 0,
                           "player": 1, "squad_id": squad_id, "HP_CUR": 1,
                           "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0}
                   for i, mid in enumerate(model_ids)}
    occupied = {mid: (10 + i, 10) for i, mid in enumerate(model_ids)}
    gs: Dict[str, Any] = {
        "models_cache": models_cache,
        "squad_models": {squad_id: list(model_ids)},
        "units_cache": {
            squad_id: {
                "col": 10, "row": 10, "player": 1, "HP_CUR": n_models,
                "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
                "occupied_hexes": set(occupied.values()),
                "occupied_hexes_by_model": dict(occupied),
                "floor_height_by_model": {mid: 0.0 for mid in model_ids},
                "level_by_model": {mid: 0 for mid in model_ids},
                "orientation_by_model": {mid: 0 for mid in model_ids},
            },
        },
        "los_pair_cache": {},
        "inches_to_subhex": 1,
        "board_cols": 44,
        "board_rows": 44,
        "wall_hexes": set(),
        "terrain_areas": [],
        "_unit_move_version": 0,
        "config": {
            "game_rules": {
                "engagement_zone": 1,
                "engagement_zone_vertical": 5.0,
                "max_base_size_hex": 6,
                "unit_model_cohesion_range": 2,
                "unit_global_cohesion_range": 9,
                "squad_min_neighbors": 1,
                "cohesion_distance_mode": "euclidean",
            },
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 2,
        "phase": "shoot",
    }
    return gs


@pytest.mark.parametrize("reason", [
    "combat",
    "hazard",
    "coherency_removal",
    "deployment_no_space",
    "strategic_reserves_timeout",
])
def test_destroy_model_emits_dead_event(reason: str) -> None:
    """destroy_model doit ajouter un event {"type": "dead"} dans action_logs, toute raison."""
    gs = _minimal_gs(n_models=2)
    model_id = "1#0"
    destroy_model(gs, model_id, reason=reason)

    dead_events = [e for e in gs["action_logs"] if e.get("type") == "dead"]
    assert dead_events, f"Aucun event 'dead' dans action_logs après destroy_model(reason={reason!r})"
    evt = dead_events[0]
    assert evt["model_id"] == model_id
    assert evt["unitId"] == "1"
    assert evt["reason"] == reason
    assert evt["turn"] == 2
    assert evt["phase"] == "shoot"
    assert "logSeq" in evt


def test_destroy_model_dead_event_increments_action_log_seq() -> None:
    """Chaque destroy_model incrémente action_log_seq — invariant de append_action_log."""
    gs = _minimal_gs(n_models=3)
    seq_before = gs["action_log_seq"]
    destroy_model(gs, "1#0", reason="combat")
    assert gs["action_log_seq"] == seq_before + 1
    destroy_model(gs, "1#1", reason="combat")
    assert gs["action_log_seq"] == seq_before + 2


def test_destroy_model_dead_event_appears_before_last_model_removal() -> None:
    """Même pour la dernière figurine (squad wipe), l'event dead est émis."""
    gs = _minimal_gs(n_models=1)
    destroy_model(gs, "1#0", reason="combat")
    dead_events = [e for e in gs["action_logs"] if e.get("type") == "dead"]
    assert dead_events, "L'event dead doit être émis même pour la dernière figurine (squad wipe)"
    assert dead_events[0]["model_id"] == "1#0"
