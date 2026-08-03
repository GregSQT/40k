"""
Monotonic ``logSeq`` on ``game_state`` action log entries.

``action_log_seq`` increments on every append and is **not** reset when the API
clears ``action_logs`` after each response (entries are flushed to the client).
It resets with a new episode (``w40k_core`` reset).
"""

from typing import Any, Dict, Iterable, MutableMapping, Tuple


def format_models_segment(
    items: Iterable[Tuple[Any, int, int, float]], label: str = "MODELS"
) -> str:
    """
    Build the per-figurine log segment ``[MODELS: <mid>@(<col>,<row>,z<hauteur>) ...]``.

    ``items`` yields ``(model_id, col, row, floor_height_inches)``. The segment is appended
    to action messages so the analyzer can reconstruct per-figurine positions
    instead of reasoning on the squad anchor alone. Returns ``""`` when empty
    (nothing to append rather than an empty, misleading segment).

    ``z<hauteur>`` = hauteur du PLANCHER sous la figurine, en POUCES — la grandeur que compare
    le gate vertical de l'engagement 3D (§03.04 : 2" horizontal ET 5" vertical). C'est la
    HAUTEUR qui est journalisée, pas le niveau : la hauteur d'un ``level`` donné dépend de la
    POSITION (deux ruines peuvent avoir un étage 1 à des hauteurs différentes, cf.
    ``floor_height_at``) et le step.log ne porte aucun terrain — un consommateur ne pourrait
    donc pas la re-dériver depuis le seul niveau.

    ``label`` selects the wrapper : ``"MODELS"`` (défaut, unité qui agit, lu par
    l'analyzer) ou ``"TARGET_MODELS"`` (survivants de la cible post-pertes, consommé
    uniquement par le replay — le regex analyzer ``\\[MODELS:`` ne matche pas ``[TARGET_MODELS:``).
    """
    parts = [
        f"{mid}@({int(col)},{int(row)},z{float(height):g})" for mid, col, row, height in items
    ]
    if not parts:
        return ""
    return f"[{label}: " + " ".join(parts) + "]"


def format_shooter_models_segment(model_ids: Iterable[Any]) -> str:
    """Segment ``[SHOOTER_MODELS: <mid> <mid> ...]`` des figs ayant EFFECTIVEMENT tire/frappe.

    Sous-ensemble de ``[MODELS:]`` (positions par socle) restreint aux figs qui ont agi. Ids seuls
    (les positions sont deja portees par ``[MODELS:]``). Consomme uniquement par le replay pour
    restreindre le cercle vert et le cone LoS aux figs tireuses. ``""`` si vide (rien a emettre)."""
    parts = [str(m) for m in model_ids]
    if not parts:
        return ""
    return "[SHOOTER_MODELS: " + " ".join(parts) + "]"


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
