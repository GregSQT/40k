"""
Monotonic ``logSeq`` on ``game_state`` action log entries.

``action_log_seq`` increments on every append and is **not** reset when the API
clears ``action_logs`` after each response (entries are flushed to the client).
It resets with a new episode (``w40k_core`` reset).
"""

from typing import Any, Dict, Iterable, MutableMapping, Tuple


def format_models_segment(items: Iterable[Tuple[Any, int, int]]) -> str:
    """
    Build the per-figurine log segment ``[MODELS: <mid>@(<col>,<row>) ...]``.

    ``items`` yields ``(model_id, col, row)`` triples. The segment is appended
    to action messages so the analyzer can reconstruct per-figurine positions
    instead of reasoning on the squad anchor alone. Returns ``""`` when empty
    (nothing to append rather than an empty, misleading segment).
    """
    parts = [f"{mid}@({int(col)},{int(row)})" for mid, col, row in items]
    if not parts:
        return ""
    return "[MODELS: " + " ".join(parts) + "]"


def models_segment_from_move_details(move_details: Iterable[Dict[str, Any]]) -> str:
    """Per-figurine segment from a move's ``moveDetails`` (destination positions)."""
    return format_models_segment(
        (d["modelId"], d["toCol"], d["toRow"]) for d in move_details
    )


def models_segment_from_cache(game_state: MutableMapping[str, Any], unit_id: Any) -> str:
    """
    Per-figurine segment from the authoritative current positions
    (``units_cache[unit_id]['occupied_hexes_by_model']``). Used by non-move
    actions (shoot/fight) where figurines keep their current positions.

    Raises:
        KeyError: if ``units_cache`` / the unit / ``occupied_hexes_by_model`` is
        missing — no silent fallback, the caller must have a valid cache.
    """
    units_cache = game_state["units_cache"]
    by_model = units_cache[unit_id]["occupied_hexes_by_model"]
    return format_models_segment(
        (mid, pos[0], pos[1]) for mid, pos in by_model.items()
    )


def append_action_log(
    game_state: MutableMapping[str, Any],
    entry: Dict[str, Any],
) -> None:
    """
    Append ``entry`` to ``game_state['action_logs']`` with the next ``logSeq``.

    Mutates ``entry`` in place (adds ``logSeq``) so callers that later update
    the same dict (e.g. shooting reward fields) keep updating the row in the list.

    Raises:
        KeyError: If ``action_log_seq`` is missing.
        TypeError: If ``action_logs`` is not a list or ``action_log_seq`` is not int.
    """
    if "action_logs" not in game_state:
        game_state["action_logs"] = []
    logs = game_state["action_logs"]
    if not isinstance(logs, list):
        raise TypeError(
            f"game_state['action_logs'] must be a list, got {type(logs).__name__}"
        )
    seq_val = game_state.get("action_log_seq")
    if seq_val is None:
        raise KeyError("game_state missing required 'action_log_seq' (initialize in w40k_core)")
    if not isinstance(seq_val, int):
        raise TypeError(
            f"game_state['action_log_seq'] must be int, got {type(seq_val).__name__}"
        )
    next_seq = seq_val + 1
    game_state["action_log_seq"] = next_seq
    entry["logSeq"] = next_seq
    logs.append(entry)
