"""
Monotonic ``logSeq`` on ``game_state`` action log entries.

``action_log_seq`` increments on every append and is **not** reset when the API
clears ``action_logs`` after each response (entries are flushed to the client).
It resets with a new episode (``w40k_core`` reset).
"""

from typing import Any, Dict, MutableMapping


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
