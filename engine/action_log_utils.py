"""
Monotonic ``logSeq`` on ``game_state`` action log entries.

``action_log_seq`` increments on every append and is **not** reset when the API
clears ``action_logs`` after each response (entries are flushed to the client).
It resets with a new episode (``w40k_core`` reset).
"""

from typing import Any, Dict, FrozenSet, Iterable, MutableMapping, Tuple

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


#: Types dont l'entree d'``action_logs`` a un CONSTRUCTEUR DEDIE, seul autorise a la produire.
#: ``append_action_log`` les REFUSE : l'entree ne peut plus etre ecrite ailleurs, quelle que soit
#: la syntaxe qui pose le type (litteral, ``entry["type"] = ...``, ``dict(type=...)``, valeur
#: calculee). La sonde statique de `tests/unit/engine/test_step_log_agent_decision.py` ne voit,
#: elle, que la forme LITTERALE — mesure : les trois autres formes lui rendaient 0 releve.
_TYPES_A_CONSTRUCTEUR_DEDIE: FrozenSet[str] = frozenset({"agent_decision"})


def _append_entry(
    game_state: MutableMapping[str, Any],
    entry: Dict[str, Any],
) -> None:
    """Ecriture NUE dans ``action_logs`` (``logSeq`` compris), SANS controle de producteur.

    Partagee par ``append_action_log`` et les constructeurs dedies : ceux-ci ne peuvent pas passer
    par ``append_action_log``, dont la garde refuse precisement leur type. UN seul corps, donc un
    seul compteur ``logSeq`` — le dupliquer aurait fait diverger la numerotation entre les deux
    chemins d'ecriture.

    ⚠️ REFERENCE INTERDITE hors de ce module : c'est le chemin qui contourne la garde. Verrouille
    par `test_step_log_agent_decision.py`, qui l'exige absent d'`engine/`, `ai/` et `services/`.

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


def append_action_log(
    game_state: MutableMapping[str, Any],
    entry: Dict[str, Any],
) -> None:
    """
    Append ``entry`` to ``game_state['action_logs']`` with the next ``logSeq``.

    Mutates ``entry`` in place (adds ``logSeq``) so callers that later update
    the same dict (e.g. shooting reward fields) keep updating the row in the list.

    ⚠️ REFUSE les types d'``_TYPES_A_CONSTRUCTEUR_DEDIE`` : leur entree porte des champs qu'un
    lecteur EXIGE (``StepLogger`` leve sur un ``agent_decision`` prive de ses quatre champs de
    decision) et une seconde entree BIEN formee ferait compter a l'analyzer un choix que l'agent
    n'a jamais joue. Le constructeur dedie est nomme dans le message d'erreur.

    Raises:
        ValueError: If ``entry`` carries a type that has a dedicated builder.
        KeyError: If ``action_log_seq`` is missing.
        TypeError: If ``action_logs`` is not a list or ``action_log_seq`` is not int.
    """
    type_declare = entry.get("type")  # get allowed : la plupart des entrees n'en portent pas
    if isinstance(type_declare, str) and type_declare in _TYPES_A_CONSTRUCTEUR_DEDIE:
        raise ValueError(
            f"append_action_log: le type '{type_declare}' a un constructeur dedie "
            f"(`append_{type_declare}_log`), seul autorise a produire son entree d'action_logs. "
            f"Construire l'entree a la main fait diverger le journal des decisions de ce que "
            f"l'agent a reellement joue."
        )
    _append_entry(game_state, entry)


def append_agent_decision_log(
    game_state: MutableMapping[str, Any],
    *,
    decision_type: str,
    player: int,
    unit_id: str,
    option_index: int,
    option_label: str,
    declines: bool,
) -> None:
    """CONSTRUCTEUR DEDIE de l'entree ``agent_decision`` — le seul, et il est ici.

    L'entree etait batie en clair dans ``W40KEngine._record_agent_decision_action_log``, et le
    site unique ne tenait alors que par une SONDE statique qui ne reconnait le type que sous sa
    forme LITTERALE. La construction vit desormais dans le module du goulot, et
    ``append_action_log`` refuse le type : aucune autre syntaxe ne peut plus produire l'entree. Ce
    qui reste a garder est un NOM de fonction — visible a l'import, alias compris — et non une
    forme de dictionnaire.

    ``turn`` et ``phase`` sont relus dans ``game_state`` plutot que recus en parametre : ce sont
    les memes valeurs pour tout producteur, et les passer aurait rendu possible une ligne datee
    d'un autre tour que celui ou la decision a ete jouee.

    AUCUN ``models_segment`` : « un releve de choix n'observe aucune position » est une propriete
    du TYPE (``W40KEngine._TYPES_SANS_SEGMENT_MODELS``), appliquee au point de traduction. La
    poser aussi ici en ferait un jumeau, et le verrou ne tiendrait que pour ce producteur-la.
    """
    _append_entry(
        game_state,
        {
            "type": "agent_decision",
            # MEME libelle que la ligne de `step.log`, par le MEME constructeur : le Game Log du
            # PvP et le journal d'entrainement disent le mot pour mot la meme chose.
            "message": format_agent_decision_message(
                f"Unit {unit_id}", decision_type, option_index, option_label, declines
            ),
            "unitId": unit_id,
            "player": int(player),
            "turn": require_key(game_state, "turn"),
            "phase": str(require_key(game_state, "phase")),
            "decision_type": decision_type,
            "decision_option_index": int(option_index),
            "decision_option_label": option_label,
            "decision_option_declines": bool(declines),
            "reward": 0.0,
        },
    )
