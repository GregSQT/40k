"""
Monotonic ``logSeq`` on ``game_state`` action log entries.

``action_log_seq`` increments on every append and is **not** reset when the API
clears ``action_logs`` after each response (entries are flushed to the client).
It resets with a new episode (``w40k_core`` reset).
"""

from typing import Any, Dict, Iterable, MutableMapping, Tuple

from shared.data_validation import require_key


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


def models_segment_for_unit(
    game_state: MutableMapping[str, Any], unit_id: Any, label: str = "MODELS"
) -> str:
    """Segment ``[MODELS:]`` des positions per-figurine COURANTES, sans accès à self.

    Miroir de ``W40KEngine._models_segment_for_unit`` — même logique, sans dépendance à
    l'instance du moteur. Utilisé dans les handlers (shared_utils, movement_handlers…) pour
    pré-capturer le segment AU MOMENT de l'``append_action_log``, AVANT que les effets de
    l'action (hazardous, destroy_model) ne modifient ``occupied_hexes_by_model``.

    Sans pré-capture, ``_build_step_log_details`` lit le segment LIVE au flush — après que
    les effets ont eu lieu — et les figurines tuées en cours d'action disparaissent de
    ``[MODELS:]`` sans aucun événement intermédiaire visible.
    """
    if unit_id is None:
        return ""
    units_cache = game_state.get("units_cache")  # get allowed
    if not isinstance(units_cache, dict):
        return ""
    entry = units_cache.get(str(unit_id))  # get allowed
    if not isinstance(entry, dict):
        return ""
    by_model = entry.get("occupied_hexes_by_model")  # get allowed
    if not isinstance(by_model, dict) or not by_model:
        return ""
    # `floor_height_by_model` est absent en mode 2D (pas de terrain hauteur) — valeur métier
    # valide, pas une corruption. On retombe à 0.0 par socle (tout au ras du sol).
    floors = entry.get("floor_height_by_model") or {}
    return format_models_segment(
        ((mid, pos[0], pos[1], floors.get(mid, 0.0)) for mid, pos in by_model.items()),
        label=label,
    )


def format_agent_decision_message(
    unit_label: str,
    decision_type: str,
    option_index: int,
    option_label: str,
    declines: bool,
) -> str:
    """Libelle d'une DECISION D'AGENT resolue (V11 §9.3 P2) — UNE seule implementation.

    Deux consommateurs la partagent, et c'est la raison d'etre de cette fonction :
    ``W40KEngine._record_agent_decision_action_log`` la pose dans ``action_logs`` (Game Log du
    PvP) et ``StepLogger._format_replay_style_message`` la rend dans ``step.log`` (grammaire 8,
    lue par ``ai/analyzer_core``). Deux formateurs separes auraient diverge au premier ajustement,
    et l'analyzer ne lit QUE l'un des deux : la divergence serait passee inapercue.

    ``[DECLINED]`` marque le candidat qui PASSE (``declines``). Sans lui, deux lignes ne se
    distingueraient que par un index, dont le sens depend du type de decision.
    """
    message = (
        f"{unit_label} DECISION [{decision_type}] CHOICE_{int(option_index)} [{option_label}]"
    )
    if declines:
        message += " [DECLINED]"
    return message


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
