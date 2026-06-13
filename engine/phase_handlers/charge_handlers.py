#!/usr/bin/env python3
"""
charge_handlers.py - AI_TURN.md Charge Phase Implementation
Pure stateless functions implementing AI_TURN.md charge specification

References: AI_TURN.md Section ⚡ CHARGE PHASE LOGIC
ZERO TOLERANCE for state storage or wrapper patterns
"""

import os
import time
from collections import deque
from typing import Dict, List, Tuple, Set, Optional, Any, FrozenSet
from .generic_handlers import end_activation
from shared.data_validation import require_key, require_present
from engine.action_log_utils import append_action_log
from engine.hex_utils import hex_distance as _hex_distance
from engine.game_utils import add_console_log, safe_print, add_debug_file_log, _write_diagnostic_to_debug_log
from engine.combat_utils import (
    normalize_coordinates,
    get_unit_by_id,
    get_hex_neighbors,
    expected_dice_value,
    resolve_dice_value,
    calculate_hex_distance as _calculate_hex_distance,
)
from .shared_utils import (
    ACTION, WAIT, NO, ERROR, PASS, CHARGE,
    update_units_cache_position, translate_squad_to_destination, update_units_cache_hp, is_unit_alive, get_hp_from_cache, require_hp_from_cache,
    get_unit_position, require_unit_position,
    update_enemy_adjacent_caches_after_unit_move,
    unit_has_rule_effect as shared_unit_has_rule_effect,
    get_source_unit_rule_id_for_effect as shared_get_source_unit_rule_id_for_effect,
    get_source_unit_rule_display_name_for_effect as shared_get_source_unit_rule_display_name_for_effect,
    build_occupied_positions_set, compute_candidate_footprint, is_footprint_placement_valid,
    is_placement_valid_with_clearance, candidate_overlaps_any_unit,
)

CHARGE_IMPACT_TRIGGER_THRESHOLD = 4
CHARGE_IMPACT_MORTAL_WOUNDS = 1

# Incrémenter si la sémantique du BFS de fin de charge change (invalidation cache ``_charge_dest_bfs_cache``).
_CHARGE_DEST_BFS_CACHE_SCHEMA = 3
_unit_registry_singleton = None  # UnitRegistry reads static files — safe to share across all episodes


def _unit_has_rule(unit: Dict[str, Any], rule_id: str) -> bool:
    """Check if unit has a specific direct or granted rule effect by ruleId."""
    return shared_unit_has_rule_effect(unit, rule_id)


def _charge_is_ai_unit(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """IA gym / PvE joueur 2 : pilotée par le modèle, jamais de déclaration humaine de vol."""
    is_gym = bool(game_state.get("gym_training_mode", False))
    is_pve = bool(game_state.get("pve_mode", False)) or bool(game_state.get("is_pve_mode", False))
    return is_gym or (is_pve and int(require_key(unit, "player")) == 2)


def _charge_fly_declared(game_state: Dict[str, Any], unit_id: Any) -> bool:
    """True si le vol de charge (take to the skies) a été DÉCLARÉ pour cette unité ce tour."""
    return str(unit_id) in game_state.get("units_took_to_skies_charge", set())


def _charge_fly_active(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    unit_id: Any,
    *,
    for_eligibility: bool = False,
) -> bool:
    """Take to the skies en CHARGE (Règles 21.03) : la traversée FLY (murs + figurines + ignore
    vertical) est active si l'unité a le keyword fly ET :
    - IA (gym / PvE J2) → JAMAIS (comportement de charge IA inchangé, pas de régression training) ;
    - humain, ``for_eligibility`` → toujours (l'éligibilité est généreuse : la charge est proposée
      si une cible est atteignable par les airs, même avant déclaration) ;
    - humain, mouvement réel → seulement si le vol a été déclaré (``units_took_to_skies_charge``).
    Source unique partagée par les 4 BFS de charge et le pool d'éligibilité.
    """
    from .movement_handlers import _unit_has_keyword
    if not _unit_has_keyword(unit, "fly"):
        return False
    if _charge_is_ai_unit(game_state, unit):
        return False
    if for_eligibility:
        return True
    return _charge_fly_declared(game_state, unit_id)


def _charge_budget_subhex(game_state: Dict[str, Any], unit_id: Any, charge_roll_inches: int) -> int:
    """Budget de mouvement de charge en sous-hex = jet 2D6 (pouces) × ``inches_to_subhex``, moins
    2" (Règles 21.03) si le vol a été DÉCLARÉ pour cette unité. Source unique des 4 sites de calcul
    de distance de charge. Le malus ne s'applique qu'à la déclaration humaine (l'IA ne déclare pas)."""
    ish = int(game_state["inches_to_subhex"])
    budget = int(charge_roll_inches) * ish
    if _charge_fly_declared(game_state, unit_id):
        budget -= 2 * ish
    return max(0, budget)


def _get_source_unit_rule_id_for_effect(unit: Dict[str, Any], effect_rule_id: str) -> Optional[str]:
    """Return source UNIT_RULES.ruleId that grants/owns the effect; None if absent."""
    return shared_get_source_unit_rule_id_for_effect(unit, effect_rule_id)


def _get_source_unit_rule_display_name_for_effect(unit: Dict[str, Any], effect_rule_id: str) -> Optional[str]:
    """Return source UNIT_RULES.displayName for an effect rule; None if absent."""
    return shared_get_source_unit_rule_display_name_for_effect(unit, effect_rule_id)


def _charge_debug_positions_enabled(game_state: Dict[str, Any]) -> bool:
    """Verbose per-BFS charge position logging (expensive). Off unless env or flag set."""
    if game_state.get("charge_debug_positions"):
        return True
    return os.environ.get("W40K_CHARGE_DEBUG", "").lower() in ("1", "true", "yes")


FootprintOffsetPair = Optional[Tuple[Tuple[Tuple[int, int], ...], Tuple[Tuple[int, int], ...]]]


def _charge_prepare_footprint_offsets(
    unit: Dict[str, Any], game_state: Dict[str, Any]
) -> FootprintOffsetPair:
    """Pre-compute even/odd footprint offsets for Board×10 multi-hex (same idea as fly BFS).

    Returns None to fall back to ``compute_candidate_footprint`` (legacy boards, 1-hex, or error).
    Result is cached per unit for the phase (see ``charge_phase_start`` reset).
    """
    cache: Dict[str, FootprintOffsetPair] = game_state.setdefault("_charge_fp_offset_pair_cache", {})
    uid = str(unit["id"])
    if uid in cache:
        return cache[uid]

    from .shared_utils import get_engagement_zone

    ez = get_engagement_zone(game_state)
    bs = unit["BASE_SIZE"]
    if ez <= 1 or bs == 1:
        cache[uid] = None
        return None
    try:
        from engine.hex_utils import precompute_footprint_offsets

        shape = unit["BASE_SHAPE"]
        orient = int(require_key(unit, "orientation"))
        off_e, off_o = precompute_footprint_offsets(shape, bs, orient)
        out: FootprintOffsetPair = (off_e, off_o)
        cache[uid] = out
        return out
    except Exception:
        cache[uid] = None
        return None


def _candidate_footprint_charge(
    center_col: int,
    center_row: int,
    unit: Dict[str, Any],
    game_state: Dict[str, Any],
    offset_pair: FootprintOffsetPair,
) -> Set[Tuple[int, int]]:
    if offset_pair is not None:
        off_e, off_o = offset_pair
        offs = off_e if (center_col & 1) == 0 else off_o
        return {(center_col + dc, center_row + dr) for dc, dr in offs}
    return compute_candidate_footprint(center_col, center_row, unit, game_state)


def _charge_offsets_for_base(
    game_state: Dict[str, Any], shape: str, base_size: Any, orientation: int
) -> FootprintOffsetPair:
    """Offsets even/odd pour une base (shape/size/orient) DONNÉE — pas celle de l'unité.

    Permet une géométrie par-figurine (unités à bases hétérogènes : personnage attaché). Cache par
    base (réutilisé entre figs de même socle). ``None`` = mono-hex / legacy → fallback empreinte.
    """
    from .shared_utils import get_engagement_zone

    cache: Dict[Any, FootprintOffsetPair] = game_state.setdefault("_charge_fp_offset_by_base_cache", {})
    key = (shape, tuple(base_size) if isinstance(base_size, (list, tuple)) else base_size, int(orientation))
    if key in cache:
        return cache[key]
    ez = get_engagement_zone(game_state)
    if ez <= 1 or base_size == 1:
        cache[key] = None
        return None
    try:
        from engine.hex_utils import precompute_footprint_offsets
        off_e, off_o = precompute_footprint_offsets(shape, base_size, int(orientation))
        out: FootprintOffsetPair = (off_e, off_o)
    except Exception:
        out = None
    cache[key] = out
    return out


def _charge_model_footprint(
    game_state: Dict[str, Any], model_entry: Dict[str, Any], col: int, row: int
) -> Set[Tuple[int, int]]:
    """Empreinte d'une figurine à (col,row) selon SA propre base (``models_cache``)."""
    shape = model_entry["BASE_SHAPE"]
    bs = model_entry["BASE_SIZE"]
    orient = int(model_entry.get("orientation", 0))
    offs = _charge_offsets_for_base(game_state, shape, bs, orient)
    if offs is not None:
        off_e, off_o = offs
        o = off_e if (col & 1) == 0 else off_o
        return {(col + dc, row + dr) for dc, dr in o}
    return compute_candidate_footprint(
        col, row, {"BASE_SHAPE": shape, "BASE_SIZE": bs, "orientation": orient}, game_state
    )


def _charge_model_socle(
    game_state: Dict[str, Any], model_entry: Dict[str, Any], col: int, row: int
) -> Any:
    """``Socle`` d'une figurine selon sa propre base, pour les tests de chevauchement continu."""
    from engine.hex_utils import Socle

    fp = _charge_model_footprint(game_state, model_entry, col, row)
    return Socle(
        shape=model_entry["BASE_SHAPE"], base_size=model_entry["BASE_SIZE"],
        col=col, row=row, fp=fp,
    )


def _charge_synthetic_charger_cache_entry(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    anchor_col: int,
    anchor_row: int,
    candidate_fp: Set[Tuple[int, int]],
) -> Dict[str, Any]:
    """
    Entrée au format ``units_cache`` pour tester l'engagement en fin de charge,
    consommée par ``unit_entries_within_engagement_zone`` (même contrat que la phase fight).

    Construite en **copiant la vraie entrée ``units_cache``** du chargeur, puis en surchargeant la
    position (``col``/``row``/``occupied_hexes``). En héritant de l'entrée réelle, l'entrée synthétique
    reste alignée sur la forme attendue par ``spatial_relations`` quel que soit le champ requis
    (``orientation``, ``BASE_SHAPE``/``BASE_SIZE`` …) — c'est ce qui empêche un champ statique
    nouvellement requis de la casser silencieusement (cf. ``orientation`` exigé par
    ``_entry_is_multi_figure``).

    ``occupied_hexes_by_model`` est volontairement retiré : il est position-dépendant et ne peut pas
    être recalculé pour une ancre hypothétique. L'absence (KeyError explicite si un futur consommateur
    l'exige) est préférable à une valeur obsolète silencieusement fausse.
    """
    units_cache = require_key(game_state, "units_cache")
    base = dict(require_key(units_cache, str(require_key(unit, "id"))))
    base["col"] = int(anchor_col)
    base["row"] = int(anchor_row)
    base["occupied_hexes"] = set(candidate_fp)
    base.pop("occupied_hexes_by_model", None)
    return base


def _charge_footprint_union_for_anchors(
    game_state: Dict[str, Any],
    unit_id: str,
    anchor_positions: List[Tuple[int, int]],
) -> List[Tuple[int, int]]:
    """
    Union of all occupied hexes for each valid anchor — used for PvP violet preview.

    ``valid_destinations`` lists anchor cells only; the UI must show the full end footprint
    (around the declared target / engagement band), not a scatter of anchor dots near the charger.
    """
    unit = get_unit_by_id(game_state, unit_id)
    if not unit or not anchor_positions:
        return []
    fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
    seen: Set[Tuple[int, int]] = set()
    ordered: List[Tuple[int, int]] = []
    for ac, ar in anchor_positions:
        fp = _candidate_footprint_charge(int(ac), int(ar), unit, game_state, fp_pair)
        for h in fp:
            if h not in seen:
                seen.add(h)
                ordered.append(h)
    return ordered


def _resolve_charge_dest_to_anchor(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    valid_pool: List[Tuple[int, int]],
    dest_col: int,
    dest_row: int,
) -> Optional[Tuple[int, int]]:
    """Map a clicked hex (any cell of the end footprint) to the canonical anchor in ``valid_pool``.

    Ordre de résolution : (1) ancre exacte, (2) ancre dont l'empreinte couvre l'hex cliqué,
    (3) ancre la plus proche en distance hex (clic dans la zone violette hors empreinte exacte).
    """
    from engine.hex_utils import hex_distance

    if (dest_col, dest_row) in valid_pool:
        return (dest_col, dest_row)
    fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
    for ac, ar in valid_pool:
        fp = _candidate_footprint_charge(int(ac), int(ar), unit, game_state, fp_pair)
        if (dest_col, dest_row) in fp:
            return (int(ac), int(ar))
    best: Optional[Tuple[int, int]] = None
    best_d = 10**9
    for ac, ar in valid_pool:
        d = hex_distance(int(ac), int(ar), int(dest_col), int(dest_row))
        if d < best_d:
            best_d = d
            best = (int(ac), int(ar))
    return best


def _charge_base_diameter(unit: Dict[str, Any]) -> int:
    """Diamètre de l'empreinte en hexes (1 si BASE_SIZE absent ou invalide).

    BASE_SIZE peut être int (round/square) ou [major, minor] (oval).
    """
    bs = unit["BASE_SIZE"]
    if isinstance(bs, (list, tuple)) and len(bs) >= 1:
        try:
            return max(int(v) for v in bs)
        except (TypeError, ValueError):
            return 1
    if isinstance(bs, (list, tuple)):
        return 1
    try:
        return max(1, int(bs))
    except (TypeError, ValueError):
        return 1


def _charge_closest_charger_hex_to_target(
    charger_fp: Set[Tuple[int, int]],
    target_fp: Set[Tuple[int, int]],
) -> Tuple[Tuple[int, int], int]:
    """Renvoie (hex allié le plus proche de la cible, distance hex associée)."""
    from engine.hex_utils import hex_distance

    best_h: Optional[Tuple[int, int]] = None
    best_d = 10**9
    for hc, hr in charger_fp:
        for tc, tr in target_fp:
            d = hex_distance(int(hc), int(hr), int(tc), int(tr))
            if d < best_d:
                best_d = d
                best_h = (int(hc), int(hr))
    if best_h is None:
        # charger_fp vide — repli arbitraire
        return ((0, 0), 0)
    return (best_h, best_d)


def _compute_charge_preview_zone(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    target: Dict[str, Any],
    charge_roll: int,
) -> Tuple[Set[Tuple[int, int]], Tuple[int, int]]:
    """
    Zone violette cible-centrée (spec utilisateur) :

    - Hexes adjacents aux hex extérieurs de l'empreinte **cible** jusqu'à
      ``diamètre(empreinte chargeur) + engagement_zone`` pas (exclut l'empreinte cible).
    - Filtrée par la distance hex depuis **l'hex chargeur le plus proche de la cible**,
      qui doit rester ≤ ``charge_roll``.

    Renvoie ``(zone_hexes, closest_charger_hex_to_target)``.
    """
    from engine.hex_utils import dilate_hex_set_unbounded, hex_distance
    from .shared_utils import get_engagement_zone

    units_cache = require_key(game_state, "units_cache")
    uid = str(unit["id"])
    tid = str(target["id"])
    ue = units_cache.get(uid)
    te = units_cache.get(tid)
    if not ue or not te:
        return (set(), (0, 0))

    charger_fp = set(ue.get("occupied_hexes") or {(int(ue["col"]), int(ue["row"]))})
    target_fp = set(te.get("occupied_hexes") or {(int(te["col"]), int(te["row"]))})

    closest_ch, _ = _charge_closest_charger_hex_to_target(charger_fp, target_fp)

    engagement_zone = get_engagement_zone(game_state)
    diameter = _charge_base_diameter(unit)
    max_ring = max(1, diameter + engagement_zone)

    # Zone extérieure autour de la cible : [1 .. max_ring] hexes depuis la cible.
    outer_with_target = dilate_hex_set_unbounded(target_fp, max_ring)
    target_zone = outer_with_target - target_fp

    # Disque autour de l'hex chargeur le plus proche : distance ≤ charge_roll.
    if charge_roll <= 0:
        return (set(), closest_ch)
    charger_disk = dilate_hex_set_unbounded({closest_ch}, int(charge_roll))

    # Bornes plateau
    _bc = game_state.get("board_cols")
    _br = game_state.get("board_rows")
    board_cols = int(_bc) if isinstance(_bc, int) and not isinstance(_bc, bool) else 0
    board_rows = int(_br) if isinstance(_br, int) and not isinstance(_br, bool) else 0

    zone: Set[Tuple[int, int]] = set()
    for h in target_zone & charger_disk:
        c, r = int(h[0]), int(h[1])
        if board_cols > 0 and (c < 0 or c >= board_cols):
            continue
        if board_rows > 0 and (r < 0 or r >= board_rows):
            continue
        # Confirme la contrainte de portée charge (sécurité, dilate est exact).
        if hex_distance(closest_ch[0], closest_ch[1], c, r) > int(charge_roll):
            continue
        zone.add((c, r))
    return (zone, closest_ch)


def _build_charge_anchors_in_zone(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    target: Dict[str, Any],
    zone: Set[Tuple[int, int]],
    charge_roll: int,
) -> List[Tuple[int, int]]:
    """
    Ancres de placement valides dont :
    - le centre est dans la ``zone`` cible-centrée ;
    - l'empreinte ne chevauche pas la cible (``occupied_hexes``) ;
    - fin en zone d'engagement réelle vs la cible (``unit_entries_within_engagement_zone``, comme le BFS charge) ;
    - le placement est légal (``is_footprint_placement_valid``).
    """
    from engine.hex_utils import hex_distance
    from engine.spatial_relations import unit_entries_within_engagement_zone
    from .shared_utils import get_engagement_zone

    units_cache = require_key(game_state, "units_cache")
    te = units_cache.get(str(target["id"]))
    if not te:
        return []
    target_fp = set(te.get("occupied_hexes") or {(int(te["col"]), int(te["row"]))})
    engagement_zone = int(get_engagement_zone(game_state))

    unit_id_str = str(unit["id"])
    occupied_positions = build_occupied_positions_set(game_state, exclude_unit_id=unit_id_str)
    fp_pair = _charge_prepare_footprint_offsets(unit, game_state)

    charger_fp_now = set((units_cache.get(unit_id_str) or {}).get("occupied_hexes") or set())
    closest_ch, _ = _charge_closest_charger_hex_to_target(charger_fp_now, target_fp)

    anchors: List[Tuple[int, int]] = []
    for ac, ar in zone:
        # Re-confirme la portée depuis l'hex chargeur le plus proche.
        if hex_distance(closest_ch[0], closest_ch[1], int(ac), int(ar)) > int(charge_roll):
            continue
        candidate_fp = _candidate_footprint_charge(int(ac), int(ar), unit, game_state, fp_pair)
        if candidate_fp & target_fp:
            continue
        synth = _charge_synthetic_charger_cache_entry(game_state, unit, int(ac), int(ar), candidate_fp)
        if not unit_entries_within_engagement_zone(synth, te, engagement_zone):
            continue
        if not is_footprint_placement_valid(candidate_fp, game_state, occupied_positions):
            continue
        anchors.append((int(ac), int(ar)))
    return anchors


def _charge_anchor_is_socle_a_socle_with_target(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    target: Dict[str, Any],
    anchor_col: int,
    anchor_row: int,
) -> bool:
    """
    True si, à cette ancre, l'empreinte du chargeur touche celle de la cible (cases distinctes,
    au moins une paire de cases 1-voisines), sans chevauchement.

    Utilisé pour la règle produit : lorsqu'au moins une telle ancre est dans le pool déjà filtré
    (zone × BFS × autres contraintes), le pool est réduit à ces ancres uniquement.
    """
    from engine.hex_utils import min_distance_between_sets

    units_cache = require_key(game_state, "units_cache")
    te = units_cache.get(str(require_key(target, "id")))
    if not te:
        return False
    target_fp = set(te.get("occupied_hexes") or {(int(te["col"]), int(te["row"]))})
    fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
    candidate_fp = _candidate_footprint_charge(int(anchor_col), int(anchor_row), unit, game_state, fp_pair)
    if candidate_fp & target_fp:
        return False
    try:
        return min_distance_between_sets(candidate_fp, target_fp, max_distance=1) == 1
    except ValueError:
        return False


def _charge_anchor_within_1_of_target(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    target: Dict[str, Any],
    anchor_col: int,
    anchor_row: int,
) -> bool:
    """True si, à cette ancre, l'empreinte du chargeur finit à <= 1" (within_1_zone) de celle de la
    cible, sans chevauchement. Même définition que le palier ``within_1`` du plan par-figurine
    (``unit_entries_within_engagement_zone`` à ``within_1_zone``) — source unique du « <=1" ». """
    from engine.spatial_relations import unit_entries_within_engagement_zone

    units_cache = require_key(game_state, "units_cache")
    te = units_cache.get(str(require_key(target, "id")))
    if not te:
        return False
    within_1_zone = int(game_state["inches_to_subhex"])  # 1" en sous-hex
    target_fp = set(te.get("occupied_hexes") or {(int(te["col"]), int(te["row"]))})
    fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
    candidate_fp = _candidate_footprint_charge(int(anchor_col), int(anchor_row), unit, game_state, fp_pair)
    if candidate_fp & target_fp:
        return False
    synth = _charge_synthetic_charger_cache_entry(
        game_state, unit, int(anchor_col), int(anchor_row), candidate_fp
    )
    return unit_entries_within_engagement_zone(synth, te, within_1_zone)


def _charge_pool_must_socle_a_socle_if_possible(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    targets: Any,
    valid_pool: List[Tuple[int, int]],
) -> List[Tuple[int, int]]:
    """Applique la priorité 11.04 (WHILE MOVING) au pool mono-figurine. « au moins une » cible
    suffit (l'engagement de toutes est garanti par le pool). ``targets`` : cible unique (dict, legacy)
    ou liste de cibles déclarées (multi).

    Trois paliers, du plus serré au plus large (chacun « si possible ») :
      1. socle à socle (contact) avec >=1 cible → ne garder que ces ancres ;
      2. sinon, <=1" (within_1) d'>=1 cible → ne garder que ces ancres (puce « within 1" must do so ») ;
      3. sinon, tout le pool engageant (<= EZ).
    Sans le palier 2, le pool retombait directement sur « tout l'engagé (<=2") » dès que le contact
    était bloqué, laissant finir à 1"-2" alors qu'un placement <=1" était obligatoire.
    """
    target_list = [targets] if isinstance(targets, dict) else list(targets)
    touching: List[Tuple[int, int]] = []
    for ac, ar in valid_pool:
        if any(
            _charge_anchor_is_socle_a_socle_with_target(game_state, unit, t, int(ac), int(ar))
            for t in target_list
        ):
            touching.append((int(ac), int(ar)))
    if touching:
        return touching
    within_1: List[Tuple[int, int]] = []
    for ac, ar in valid_pool:
        if any(
            _charge_anchor_within_1_of_target(game_state, unit, t, int(ac), int(ar))
            for t in target_list
        ):
            within_1.append((int(ac), int(ar)))
    return within_1 if within_1 else list(valid_pool)


def _charge_bfs_max_distance(
    game_state: Dict[str, Any],
    unit_id: str,
    charge_roll: int,
    target_id: Optional[str] = None,
    target_ids: Optional[List[str]] = None,
) -> int:
    """
    Nombre maximum de pas d'ancre pour le BFS de charge.

    AI_TURN / charge_compliance : la distance utile se rapporte au contact avec la cible — sur
    plateau ×10, l'ancre ``col``/``row`` peut être du côté opposé à la cible alors qu'un hex de
    l'empreinte est déjà proche. On ajoute la distance hex (primaire → hex allié le plus proche
    de l'empreinte ennemie) au jet, pour que le pool et la zone violette s'étendent vers la cible.

    Multi-cibles (``target_ids``) : la borne se mesure vers la cible déclarée **la plus proche**
    (union des empreintes), borne permissive ; l'intersection ``eng==declared`` élague ensuite.
    """
    from engine.hex_utils import hex_distance

    rid = int(charge_roll)
    if target_ids:
        tids = [str(t) for t in target_ids]
    elif target_id:
        tids = [str(target_id)]
    else:
        return rid

    units_cache = require_key(game_state, "units_cache")
    uid = str(unit_id)
    ue = units_cache.get(uid)
    if not ue:
        return rid

    own_hexes = ue.get("occupied_hexes")
    if not own_hexes:
        own_hexes = {(int(ue["col"]), int(ue["row"]))}
    # Union des empreintes des cibles déclarées (la boucle ci-dessous garde la plus proche).
    enemy_fp: Set[Tuple[int, int]] = set()
    for tid in tids:
        te = units_cache.get(tid)
        if not te:
            continue
        tfp = te.get("occupied_hexes")
        if not tfp:
            tfp = {(int(te["col"]), int(te["row"]))}
        enemy_fp |= {(int(c), int(r)) for c, r in tfp}
    if not enemy_fp:
        return rid

    primary = (int(ue["col"]), int(ue["row"]))
    best_h: Optional[Tuple[int, int]] = None
    best_d = 10**9
    for hc, hr in own_hexes:
        for tc, tr in enemy_fp:
            d = hex_distance(int(hc), int(hr), int(tc), int(tr))
            if d < best_d:
                best_d = d
                best_h = (int(hc), int(hr))
    if best_h is None:
        return rid
    extra = hex_distance(primary[0], primary[1], best_h[0], best_h[1])
    return rid + extra


def _charge_skip_hex_lb_prune_round_round_engagement(
    unit: Dict[str, Any],
    indexed_enemy_engagement: List[Tuple[Any, Dict[str, Any]]],
) -> bool:
    """
    La prune hexagonale ci-dessous suppose une borne via ``hex_distance`` jusqu'aux cases
    d'empreinte. Les paires socle rond ↔ socle rond utilisent ``euclidean_edge_clearance``
    dans ``unit_entries_within_engagement_zone`` : ne pas prune dans ce cas (éviter faux négatif).
    """
    if unit["BASE_SHAPE"] != "round":
        return False
    return any(
        ee["BASE_SHAPE"] == "round"
        for _, ee in indexed_enemy_engagement
    )


def _charge_impossible_by_primary_to_enemy_hex_lower_bound(
    game_state: Dict[str, Any],
    *,
    unit_id_str: str,
    start_col: int,
    start_row: int,
    indexed_enemy_engagement: List[Tuple[Any, Dict[str, Any]]],
    bfs_max_distance: int,
) -> bool:
    """
    Retourne True si aucune fin de charge valide n'existe avec au plus ``bfs_max_distance``
    pas BFS depuis le primaire (borne géométrique sur grille hex, indépendante des obstacles).

    Idée : soit ``m`` la distance hex minimale du primaire à une case d'empreinte ennemie.
    Pour tout ancre ``h`` avec ``hex_distance(start, h) ≤ D``, par inégalité triangulaire
    ``hex_distance(h, e) ≥ hex_distance(start, e) − D`` pour toute case ennemie ``e``, donc
    ``min_e hex_distance(h, e) ≥ m − D``.

    Pour l'engagement on a ``min_{f∈F(h), e∈E} d(f,e) ≥ min_e d(h,e) − S_c`` avec ``S_c`` le
    rayon d'empreinte du chargeur depuis le primaire (max ``hex_distance(primaire, case)``).

    Si ``m − D > ez + S_c`` (strict), alors ``min_distance(F,E) > ez`` pour tout ``h`` dans la
    boule hex : impossible d'engager. Les obstacles ne peuvent qu'allonger les chemins, pas rapprocher.

    Cas round↔round : engagement euclidien — la prune est désactivée par l'appelant.
    """
    from engine.hex_utils import hex_distance

    from .shared_utils import get_engagement_zone

    if not indexed_enemy_engagement:
        return False

    ez = int(get_engagement_zone(game_state))
    units_cache = require_key(game_state, "units_cache")
    own = units_cache.get(unit_id_str)
    if not own:
        return False
    own_hexes_raw = own.get("occupied_hexes")
    if not own_hexes_raw:
        own_hexes_raw = {(int(own["col"]), int(own["row"]))}
    s_charger = 0
    for oc, orow in own_hexes_raw:
        dhc = hex_distance(int(start_col), int(start_row), int(oc), int(orow))
        if dhc > s_charger:
            s_charger = dhc

    m: Optional[int] = None
    for _, enemy_entry in indexed_enemy_engagement:
        ec = int(enemy_entry["col"])
        er = int(enemy_entry["row"])
        efp_raw = enemy_entry.get("occupied_hexes")
        if not efp_raw:
            efp_raw = {(ec, er)}
        for exc, exr in efp_raw:
            dse = hex_distance(int(start_col), int(start_row), int(exc), int(exr))
            if m is None or dse < m:
                m = dse

    if m is None:
        return False

    d_limit = int(bfs_max_distance)
    return m > d_limit + s_charger + ez


def _charge_primary_footprint_radius(
    game_state: Dict[str, Any],
    unit_id_str: str,
    start_col: int,
    start_row: int,
) -> int:
    """Distance hex maximale entre le primaire courant et une case de l'empreinte du chargeur."""
    from engine.hex_utils import hex_distance

    units_cache = require_key(game_state, "units_cache")
    own = units_cache.get(unit_id_str)
    if not own:
        raise KeyError(f"Unit {unit_id_str} missing from units_cache")
    own_hexes = own.get("occupied_hexes")
    if not own_hexes:
        own_hexes = {(int(own["col"]), int(own["row"]))}

    radius = 0
    for oc, orow in own_hexes:
        distance = hex_distance(int(start_col), int(start_row), int(oc), int(orow))
        if distance > radius:
            radius = distance
    return radius


def _charge_reverse_goal_bfs_for_eligibility(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    *,
    unit_id_str: str,
    start_pos: Tuple[int, int],
    indexed_enemy_engagement: List[Tuple[Any, Dict[str, Any]]],
    occupied_positions: Set[Tuple[int, int]],
    bfs_max_distance: int,
    fp_offset_pair: FootprintOffsetPair,
) -> List[Tuple[int, int]]:
    """
    Recherche d'éligibilité charge par BFS inversé, strictement réservée au cas
    ``early_exit_if_valid=True`` sans cible déclarée.

    Le BFS historique part du chargeur et teste chaque ancre atteignable jusqu'à rencontrer une
    ancre qui engage un ennemi. Ici on génère d'abord les ancres de fin qui satisfont déjà les
    contraintes de fin de charge (placement légal + engagement réel), puis on cherche si le primaire
    courant est atteignable depuis l'une d'elles dans le même graphe de placements légaux.

    Retourne :
    - ``None`` si le chemin optimisé n'est pas applicable ;
    - ``[]`` si aucune destination n'est atteignable ;
    - ``[goal]`` dès qu'une destination valide est prouvée atteignable.
    """
    from engine.hex_utils import dilate_hex_set, hex_distance
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled
    from engine.spatial_relations import unit_entries_within_engagement_zone

    from .shared_utils import get_engagement_zone

    _perf = perf_timing_enabled(game_state)
    _t0 = time.perf_counter() if _perf else None
    start_col, start_row = int(start_pos[0]), int(start_pos[1])
    board_cols = int(require_key(game_state, "board_cols"))
    board_rows = int(require_key(game_state, "board_rows"))
    engagement_zone = int(get_engagement_zone(game_state))
    charger_radius = _charge_primary_footprint_radius(
        game_state, unit_id_str, start_col, start_row
    )

    enemy_occupied: Set[Tuple[int, int]] = set()  # enemy centers (for sort center computation)
    for _, enemy_entry in indexed_enemy_engagement:
        ec = int(enemy_entry["col"])
        er = int(enemy_entry["row"])
        enemy_occupied.add((ec, er))

    if not enemy_occupied:
        return []

    goal_search_radius = engagement_zone + charger_radius
    _bfs_max = int(bfs_max_distance)
    # Build enemy_goal_zone per-enemy from center + effective radius instead of dilating all
    # footprint hexes together. Dilating full footprints at x5 scale (140 spread hexes, radius 8)
    # covers the entire 28K-hex board via BFS; per-center enumeration is O(N × π×eff_r²).
    enemy_goal_zone: Set[Tuple[int, int]] = set()
    for _, _gz_enemy in indexed_enemy_engagement:
        _gz_ec = int(require_key(_gz_enemy, "col"))
        _gz_er = int(require_key(_gz_enemy, "row"))
        _gz_fp = _gz_enemy.get("occupied_hexes")
        _gz_fp_r = (
            max(hex_distance(_gz_ec, _gz_er, int(_fc), int(_fr)) for _fc, _fr in _gz_fp)
            if _gz_fp else 0
        )
        _gz_eff_r = goal_search_radius + _gz_fp_r
        enemy_goal_zone |= dilate_hex_set({(_gz_ec, _gz_er)}, _gz_eff_r, board_cols, board_rows)
        enemy_goal_zone.add((_gz_ec, _gz_er))
    goal_zone = {
        h for h in enemy_goal_zone
        if hex_distance(h[0], h[1], start_col, start_row) <= _bfs_max
    }
    goal_candidates_n = len(goal_zone)
    skipped_goal_start_lb_n = 0
    _TRAINING_GOAL_CAP = 300
    if game_state.get("gym_training_mode") and goal_candidates_n > _TRAINING_GOAL_CAP:
        _ec_c = int(sum(c for c, _ in enemy_occupied) / len(enemy_occupied))
        _er_c = int(sum(r for _, r in enemy_occupied) / len(enemy_occupied))
        goal_zone = sorted(goal_zone, key=lambda h: hex_distance(h[0], h[1], _ec_c, _er_c))[:_TRAINING_GOAL_CAP]
        goal_candidates_n = _TRAINING_GOAL_CAP
    enemy_engagement_zones: Dict[Any, Set[Tuple[int, int]]] = {}
    for eid, enemy_entry in indexed_enemy_engagement:
        ec = int(enemy_entry["col"])
        er = int(enemy_entry["row"])
        enemy_fp = enemy_entry.get("occupied_hexes")
        if not enemy_fp:
            enemy_fp = {(ec, er)}
        enemy_engagement_zones[eid] = dilate_hex_set(
            {(int(fc), int(fr)) for fc, fr in enemy_fp},
            engagement_zone,
            board_cols,
            board_rows,
        )
    # Pre-filtre hex-distance pour round-vs-round : évite d'appeler unit_entries_within_engagement_zone
    # sur des candidates clairement hors portée euclidienne. Seuil conservatif par ennemi.
    _mover_bs = unit["BASE_SIZE"]
    _mover_r = max(1, (_mover_bs + 1) // 2)
    _rr_proximity: Dict[Any, int] = {}
    if unit["BASE_SHAPE"] == "round":
        for _eid, _ee in indexed_enemy_engagement:
            if _ee["BASE_SHAPE"] == "round":
                _e_bs = _ee["BASE_SIZE"]
                _e_bs_int = max(_e_bs) if isinstance(_e_bs, (list, tuple)) else int(_e_bs)
                _e_r = max(1, (_e_bs_int + 1) // 2)
                _rr_proximity[_eid] = engagement_zone + _mover_r + _e_r + 1

    goals: List[Tuple[int, int]] = []
    seen_goals: Set[Tuple[int, int]] = set()
    goal_candidate_fp_s = 0.0
    goal_placement_s = 0.0
    goal_engagement_s = 0.0
    rejected_placement_n = 0
    rejected_overlap_n = 0
    rejected_engagement_prefilter_n = 0
    rejected_no_engagement_n = 0

    for anchor_col, anchor_row in goal_zone:
        anchor = (int(anchor_col), int(anchor_row))
        if anchor == start_pos:
            continue
        _t_candidate_fp0 = time.perf_counter() if _perf else None
        candidate_fp = _candidate_footprint_charge(
            anchor[0], anchor[1], unit, game_state, fp_offset_pair
        )
        if _perf and _t_candidate_fp0 is not None:
            goal_candidate_fp_s += time.perf_counter() - _t_candidate_fp0
        _t_placement0 = time.perf_counter() if _perf else None
        if not is_footprint_placement_valid(candidate_fp, game_state, occupied_positions):
            if _perf and _t_placement0 is not None:
                goal_placement_s += time.perf_counter() - _t_placement0
            rejected_placement_n += 1
            continue
        if _perf and _t_placement0 is not None:
            goal_placement_s += time.perf_counter() - _t_placement0

        _t_engagement0 = time.perf_counter() if _perf else None
        synth = _charge_synthetic_charger_cache_entry(game_state, unit, anchor[0], anchor[1], candidate_fp)
        hex_overlaps_enemy = False
        engages_enemy = False
        for eid, enemy_entry in indexed_enemy_engagement:
            ec = int(enemy_entry["col"])
            er = int(enemy_entry["row"])
            enemy_fp = enemy_entry.get("occupied_hexes", {(ec, er)})
            if candidate_fp & enemy_fp:
                hex_overlaps_enemy = True
                break
            is_round_round_engagement = (
                unit["BASE_SHAPE"] == "round"
                and enemy_entry["BASE_SHAPE"] == "round"
            )
            if is_round_round_engagement and eid in _rr_proximity:
                if hex_distance(anchor[0], anchor[1], ec, er) > _rr_proximity[eid]:
                    rejected_engagement_prefilter_n += 1
                    continue
            if not is_round_round_engagement:
                enemy_engagement_zone = enemy_engagement_zones[eid]
                if not (candidate_fp & enemy_engagement_zone):
                    rejected_engagement_prefilter_n += 1
                    continue
            if unit_entries_within_engagement_zone(synth, enemy_entry, engagement_zone):
                engages_enemy = True
        if _perf and _t_engagement0 is not None:
            goal_engagement_s += time.perf_counter() - _t_engagement0
        if hex_overlaps_enemy:
            rejected_overlap_n += 1
        elif not engages_enemy:
            rejected_no_engagement_n += 1
        if engages_enemy and not hex_overlaps_enemy and anchor not in seen_goals:
            goals.append(anchor)
            seen_goals.add(anchor)

    _t_goals_done = time.perf_counter() if _perf else None
    if not goals:
        if _perf and _t0 is not None:
            append_perf_timing_line(
                f"CHARGE_REVERSE_GOAL_BFS episode={game_state.get('episode_number', '?')} "
                f"turn={game_state.get('turn', '?')} unit_id={unit_id_str} "
                f"goal_candidates_n={goal_candidates_n} goals_n=0 "
                f"skipped_goal_start_lb_n={skipped_goal_start_lb_n} "
                f"goal_build_s={(_t_goals_done - _t0) if _t_goals_done is not None else 0.0:.6f} "
                f"goal_candidate_fp_s={goal_candidate_fp_s:.6f} goal_placement_s={goal_placement_s:.6f} "
                f"goal_engagement_s={goal_engagement_s:.6f} "
                f"rejected_placement_n={rejected_placement_n} rejected_overlap_n={rejected_overlap_n} "
                f"rejected_engagement_prefilter_n={rejected_engagement_prefilter_n} "
                f"rejected_no_engagement_n={rejected_no_engagement_n} "
                f"reverse_bfs_s=0.000000 visited_n=0 outcome=no_goals "
                f"total_s={time.perf_counter() - _t0:.6f}"
            )
        return []

    visited: Set[Tuple[int, int]] = set(goals)
    queue = deque((goal, 0, goal) for goal in goals)
    pruned_by_start_lb = 0
    _t_reverse_bfs0 = time.perf_counter() if _perf else None

    while queue:
        current_pos, current_dist, origin_goal = queue.popleft()
        if current_dist >= int(bfs_max_distance):
            continue
        remaining_distance = int(bfs_max_distance) - int(current_dist)
        if hex_distance(current_pos[0], current_pos[1], start_col, start_row) > remaining_distance:
            pruned_by_start_lb += 1
            continue

        _rev_c, _rev_r = current_pos[0], current_pos[1]
        _rev_offsets = ((0, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0)) if (_rev_c & 1) else ((0, -1), (1, -1), (1, 0), (0, 1), (-1, 0), (-1, -1))
        for _dc, _dr in _rev_offsets:
            neighbor = (_rev_c + _dc, _rev_r + _dr)
            next_dist = current_dist + 1
            if neighbor == start_pos:
                if _perf and _t0 is not None:
                    append_perf_timing_line(
                        f"CHARGE_REVERSE_GOAL_BFS episode={game_state.get('episode_number', '?')} "
                        f"turn={game_state.get('turn', '?')} unit_id={unit_id_str} "
                        f"goal_candidates_n={goal_candidates_n} goals_n={len(goals)} "
                        f"skipped_goal_start_lb_n={skipped_goal_start_lb_n} "
                        f"visited_n={len(visited)} outcome=hit distance={next_dist} "
                        f"pruned_start_lb_n={pruned_by_start_lb} "
                        f"goal_build_s={(_t_goals_done - _t0) if _t_goals_done is not None else 0.0:.6f} "
                        f"goal_candidate_fp_s={goal_candidate_fp_s:.6f} goal_placement_s={goal_placement_s:.6f} "
                        f"goal_engagement_s={goal_engagement_s:.6f} "
                        f"rejected_placement_n={rejected_placement_n} rejected_overlap_n={rejected_overlap_n} "
                        f"rejected_engagement_prefilter_n={rejected_engagement_prefilter_n} "
                        f"rejected_no_engagement_n={rejected_no_engagement_n} "
                        f"reverse_bfs_s={(time.perf_counter() - _t_reverse_bfs0) if _t_reverse_bfs0 is not None else 0.0:.6f} "
                        f"total_s={time.perf_counter() - _t0:.6f}"
                    )
                return [origin_goal]
            if neighbor in visited:
                continue
            candidate_fp = _candidate_footprint_charge(
                neighbor[0], neighbor[1], unit, game_state, fp_offset_pair
            )
            if not is_footprint_placement_valid(candidate_fp, game_state, occupied_positions):
                continue
            visited.add(neighbor)
            queue.append((neighbor, next_dist, origin_goal))

    if _perf and _t0 is not None:
        append_perf_timing_line(
            f"CHARGE_REVERSE_GOAL_BFS episode={game_state.get('episode_number', '?')} "
            f"turn={game_state.get('turn', '?')} unit_id={unit_id_str} "
            f"goal_candidates_n={goal_candidates_n} goals_n={len(goals)} "
            f"skipped_goal_start_lb_n={skipped_goal_start_lb_n} "
            f"visited_n={len(visited)} outcome=miss pruned_start_lb_n={pruned_by_start_lb} "
            f"goal_build_s={(_t_goals_done - _t0) if _t_goals_done is not None else 0.0:.6f} "
            f"goal_candidate_fp_s={goal_candidate_fp_s:.6f} goal_placement_s={goal_placement_s:.6f} "
            f"goal_engagement_s={goal_engagement_s:.6f} "
            f"rejected_placement_n={rejected_placement_n} rejected_overlap_n={rejected_overlap_n} "
            f"rejected_engagement_prefilter_n={rejected_engagement_prefilter_n} "
            f"rejected_no_engagement_n={rejected_no_engagement_n} "
            f"reverse_bfs_s={(time.perf_counter() - _t_reverse_bfs0) if _t_reverse_bfs0 is not None else 0.0:.6f} "
            f"total_s={time.perf_counter() - _t0:.6f}"
        )
    return []


def charge_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Initialize charge phase and build activation pool
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    _perf = perf_timing_enabled(game_state)
    _ep = game_state.get("episode_number", "?")
    _turn = game_state.get("turn", "?")
    _t_total0 = time.perf_counter() if _perf else None

    # Set phase
    game_state["phase"] = "charge"

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    units_cache = require_key(game_state, "units_cache")
    add_debug_file_log(game_state, f"[PHASE START] E{episode} T{turn} charge units_cache={units_cache}")

    # Tracking sets are NOT cleared at charge phase start
    # They persist from movement phase (units_fled, units_moved, units_shot remain)

    # Clear charge preview state
    game_state["valid_charge_destinations_pool"] = []
    game_state["_charge_dest_bfs_cache"] = {}
    game_state["_charge_fp_offset_pair_cache"] = {}
    game_state["_has_valid_charge_cache"] = {}
    game_state["_charge_reach_disk_cache"] = {}
    game_state["preview_hexes"] = []
    game_state["active_charge_unit"] = None
    game_state["charge_roll_values"] = {}  # Store 2d6 rolls per unit
    game_state["charge_target_selections"] = {}  # Store target selections per unit
    game_state["pending_charge_targets"] = []  # Store targets for gym training target selection
    game_state["pending_charge_unit_id"] = None  # Store unit ID waiting for target selection

    _t_before_enemy_adj = time.perf_counter() if _perf else None

    # PERFORMANCE: Pre-compute enemy_adjacent_hexes once at phase start for current player
    # Cache will be reused throughout the phase for all units (invalidated after each charge)
    current_player = require_key(game_state, "current_player")
    from .shared_utils import build_enemy_adjacent_hexes
    build_enemy_adjacent_hexes(game_state, current_player)

    _t_after_enemy_adj = time.perf_counter() if _perf else None

    # Build activation pool
    charge_build_activation_pool(game_state)

    if _perf and _t_total0 is not None and _t_before_enemy_adj is not None and _t_after_enemy_adj is not None:
        _t_end = time.perf_counter()
        append_perf_timing_line(
            f"CHARGE_PHASE_START episode={_ep} turn={_turn} "
            f"setup_until_adj_s={_t_before_enemy_adj - _t_total0:.6f} "
            f"enemy_adjacent_hexes_s={_t_after_enemy_adj - _t_before_enemy_adj:.6f} "
            f"pool_build_s={_t_end - _t_after_enemy_adj:.6f} total_s={_t_end - _t_total0:.6f}"
        )

    # Console log (disabled in training mode for performance)
    add_console_log(game_state, "CHARGE POOL BUILT")

    # Check if phase complete immediately (no eligible units)
    pool_after_build = game_state["charge_activation_pool"]
    if not pool_after_build:
        return charge_phase_end(game_state)

    return {
        "phase_initialized": True,
        "eligible_units": len(pool_after_build),
        "phase_complete": False
    }


def charge_build_activation_pool(game_state: Dict[str, Any]) -> None:
    """
    Build charge activation pool with eligibility checks
    """
    # CRITICAL: Clear pool before rebuilding (defense in depth)
    game_state["charge_activation_pool"] = []
    eligible_units = get_eligible_units(game_state)
    game_state["charge_activation_pool"] = list(eligible_units)  # Ensure it's a new list, not a reference

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    add_debug_file_log(game_state, f"[POOL BUILD] E{episode} T{turn} charge charge_activation_pool={eligible_units}")

def get_eligible_units(game_state: Dict[str, Any]) -> List[str]:
    """
    AI_TURN.md charge eligibility decision tree implementation.

    Charge Eligibility Requirements:
    - Alive (in units_cache)
    - player === current_player
    - NOT in units_charged
    - NOT within engagement zone of any enemy (``_charge_unit_within_engagement_zone`` = contrat move)
    - NOT in units_fled
    - Has valid charge target (enemy within charge range via pathfinding)

    Returns list of unit IDs eligible for charge activation.
    Pure function - no internal state storage.
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled
    _perf = perf_timing_enabled(game_state)
    _ep = game_state.get("episode_number", "?")
    _turn = game_state.get("turn", "?")
    _t_total0 = time.perf_counter() if _perf else None

    eligible_units = []
    current_player = game_state["current_player"]
    units_cache = require_key(game_state, "units_cache")
    units_total_n = len(units_cache)

    _t_occ0 = time.perf_counter() if _perf else None
    full_occupied_positions = build_occupied_positions_set(game_state)
    _occupied_pos_s = (time.perf_counter() - _t_occ0) if (_perf and _t_occ0 is not None) else 0.0

    units_own_n = 0
    bfs_calls_n = 0
    bfs_cache_hits_n = 0
    _bfs_total_s = 0.0

    _t_loop0 = time.perf_counter() if _perf else None

    units_cannot_charge = require_key(game_state, "units_cannot_charge")
    units_advanced = require_key(game_state, "units_advanced")

    for unit_id, cache_entry in units_cache.items():
        unit = get_unit_by_id(game_state, unit_id)
        if not unit:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        unit_id_str = str(unit_id)

        # "unit.player === current_player?"
        if cache_entry["player"] != current_player:
            continue  # Wrong player
        units_own_n += 1

        # Engagement : aligné mouvement / preview charge (pas intersection empreinte × dilatation hex seule,
        # qui peut exclure à tort une unité posée au clearance légal bord-à-bord).
        if _charge_unit_within_engagement_zone(game_state, unit):
            continue  # Déjà en zone d'engagement, ne peut pas déclarer de charge

        # "NOT in units_fled?" unless the unit has a rule effect allowing charge after fleeing
        # CRITICAL: Normalize unit ID to string for consistent comparison (units_fled stores strings)
        if unit_id_str in game_state["units_fled"]:
            if not _unit_has_rule(unit, "charge_after_flee"):
                continue  # Fled units cannot charge without explicit rule effect

        # Post-shoot movement restriction: cannot charge until end of turn.
        if unit_id_str in units_cannot_charge:
            continue

        # ADVANCE_IMPLEMENTATION: Units that advanced cannot charge
        if unit_id_str in units_advanced:
            if not _unit_has_rule(unit, "charge_after_advance"):
                continue  # Advanced units cannot charge without rule

        # "Has valid charge target?"
        # Must have at least one enemy within charge range (via BFS pathfinding)
        bfs_calls_n += 1
        if "_has_valid_charge_cache" not in game_state:
            game_state["_has_valid_charge_cache"] = {}
        _hvt_cache = game_state["_has_valid_charge_cache"]
        _hvt_key = (unit_id_str, game_state["_unit_move_version"])
        if _hvt_key in _hvt_cache:
            bfs_cache_hits_n += 1
        _t_bfs0 = time.perf_counter() if _perf else None
        has_target = _has_valid_charge_target(game_state, unit, full_occupied_positions)
        if _perf and _t_bfs0 is not None:
            _bfs_total_s += time.perf_counter() - _t_bfs0
        if not has_target:
            continue  # No valid charge targets

        # Unit passes all conditions - add to pool
        eligible_units.append(unit_id_str)

    if _perf and _t_loop0 is not None and _t_total0 is not None:
        _loop_total_s = time.perf_counter() - _t_loop0
        _filter_only_s = _loop_total_s - _bfs_total_s
        _total_s = time.perf_counter() - _t_total0
        append_perf_timing_line(
            f"CHARGE_BUILD_POOL episode={_ep} turn={_turn} "
            f"occupied_pos_s={_occupied_pos_s:.6f} "
            f"filter_only_s={_filter_only_s:.6f} "
            f"bfs_total_s={_bfs_total_s:.6f} "
            f"total_s={_total_s:.6f} "
            f"units_total_n={units_total_n} "
            f"units_own_n={units_own_n} "
            f"bfs_calls_n={bfs_calls_n} "
            f"bfs_cache_hits_n={bfs_cache_hits_n} "
            f"eligible_count={len(eligible_units)}"
        )

    return eligible_units


def execute_action(game_state: Dict[str, Any], unit: Optional[Dict[str, Any]], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Charge phase handler action routing with complete autonomy
    """
    # Handler self-initialization on first action
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if "phase" not in game_state:
        game_state_phase = None
    else:
        game_state_phase = game_state["phase"]

    if "charge_activation_pool" not in game_state:
        charge_pool_exists = False
    else:
        charge_pool_exists = bool(game_state["charge_activation_pool"])

    if game_state_phase != "charge" or not charge_pool_exists:
        charge_phase_start(game_state)

    # Pool empty? -> Phase complete
    if not game_state["charge_activation_pool"]:
        return True, charge_phase_end(game_state)
    
    # Get unit from action (frontend specifies which unit to charge)
    # AI_TURN.md COMPLIANCE: Direct field access - no defaults
    if "action" not in action:
        raise KeyError(f"Action missing required 'action' field: {action}")
    if "unitId" not in action:
        action_type = action["action"]
        unit_id = None  # Allow None for gym training auto-selection
    else:
        action_type = action["action"]
        unit_id = action["unitId"]

    # For gym training or PvE AI, if no unitId specified, use first eligible unit
    if not unit_id:
        config_gym_mode = config["gym_training_mode"] if "gym_training_mode" in config else False
        state_gym_mode = game_state["gym_training_mode"] if "gym_training_mode" in game_state else False
        is_gym_training = config_gym_mode or state_gym_mode
        current_player = require_key(game_state, "current_player")
        is_pve_ai = config.get("pve_mode", False) and current_player == 2
        if not is_gym_training and not is_pve_ai:
            return False, {
                "error": "unit_id_required",
                "action": action_type,
                "message": "unitId is required for human-controlled charge activation"
            }
        if game_state["charge_activation_pool"]:
            unit_id = game_state["charge_activation_pool"][0]
        else:
            return True, charge_phase_end(game_state)

    if "debug_mode" in game_state and game_state["debug_mode"]:
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        active_charge_unit = game_state.get("active_charge_unit")
        pool_size = len(require_key(game_state, "charge_activation_pool"))
        add_debug_file_log(
            game_state,
            f"[CHARGE TRACE] E{episode} T{turn} execute_action action={action_type} "
            f"unit_id={unit_id} active_charge_unit={active_charge_unit} pool_size={pool_size}"
        )

    # Validate unit is eligible (keep for validation, remove only after successful action)
    if unit_id not in game_state["charge_activation_pool"]:
        return False, {"error": "unit_not_eligible", "unitId": unit_id, "action": action_type}

    # Get unit object for processing
    active_unit = get_unit_by_id(game_state, unit_id)
    if not active_unit:
        return False, {"error": "unit_not_found", "unitId": unit_id, "action": action_type}

    # Flag detection for consistent behavior
    # AI_TURN.md COMPLIANCE: Direct field access with explicit validation
    if "gym_training_mode" not in config:
        config_gym_mode = False  # Explicit: not in training mode if flag absent
    else:
        config_gym_mode = config["gym_training_mode"]

    if "gym_training_mode" not in game_state:
        state_gym_mode = False  # Explicit: not in training mode if flag absent
    else:
        state_gym_mode = game_state["gym_training_mode"]

    is_gym_training = config_gym_mode or state_gym_mode

    # Auto-activate unit if not already activated and preview not shown
    # AI_TURN.md COMPLIANCE: Direct field access with explicit check
    if "active_charge_unit" not in game_state:
        active_charge_unit_exists = False
    else:
        active_charge_unit_exists = bool(game_state["active_charge_unit"])

    # Refresh / désync : si le frontend a perdu son mode (reload de page) alors que CE chargeur est
    # déjà l'unité active côté backend, un left_click nu doit le RÉ-ACTIVER (reconstruit le preview
    # des cibles : reuse du jet roll-first + clignotement). N'affecte pas le commit, qui porte
    # toujours targetId(s)/destCol/plan.
    _act_cu = game_state.get("active_charge_unit")
    if (
        action_type == "left_click"
        and _act_cu is not None
        and str(_act_cu) == str(unit_id)
        and "targetId" not in action
        and "targetIds" not in action
        and "destCol" not in action
        and "plan" not in action
    ):
        return _handle_unit_activation(game_state, active_unit, config)

    if not active_charge_unit_exists and action_type in ["charge", "left_click"]:
        if is_gym_training:
            # AI_TURN.md COMPLIANCE: In gym training, ActionDecoder may construct complete charge action
            # Check if action already has targetId and destCol/destRow (complete charge action)
            if "targetId" in action and "destCol" in action and "destRow" in action:
                # Action already has target and destination - execute charge directly, no waiting needed
                # Just ensure unit is activated, then execute charge via destination selection handler
                charge_unit_activation_start(game_state, unit_id)
                # Roll 2d6 and build destinations for validation (needed for charge execution)
                execution_result = charge_unit_execution_loop(game_state, unit_id)
                # Execute charge directly via destination selection handler
                return charge_destination_selection_handler(game_state, unit_id, action)
            else:
                # No target/destination yet - activate unit to get targets (will auto-select and execute)
                return _handle_unit_activation(game_state, active_unit, config)
        else:
            # Human players: activate and return waiting_for_player
            return _handle_unit_activation(game_state, active_unit, config)

    if action_type == "activate_unit":
        return _handle_unit_activation(game_state, active_unit, config)

    elif action_type == "charge":
        # Route based on what's in the action:
        # - If targetId(s) but no destCol/destRow -> target selection (roll, build pool, preview)
        # - If destCol/destRow -> destination selection (execute charge)
        if ("targetIds" in action or "targetId" in action) and "destCol" not in action:
            # Target selection step (validation des cibles déclarées)
            return charge_target_selection_handler(game_state, unit_id, action)
        elif "destCol" in action and "destRow" in action:
            # Destination selection step
            return charge_destination_selection_handler(game_state, unit_id, action)
        else:
            return False, {"error": "invalid_charge_action", "action": action}

    elif action_type == "take_to_skies":
        # Règles 21.03 : (dé)clare le vol de charge de l'unité FLY active (-2" + traversée murs/figurines).
        return charge_set_fly_mode_handler(game_state, unit_id, action)

    elif action_type == "commit_charge_plan":
        # V11 PvP : commit du mouvement de charge par-figurine (plan 3 phases).
        return charge_commit_move_plan_handler(game_state, unit_id, action)

    elif action_type == "charge_plan_state":
        # V11 PvP (lecture pure) : phase courante + pools éligibles par fig pour le plan provisoire.
        prov: Dict[str, Tuple[int, int]] = {}
        for entry in (action.get("plan") or []):
            prov[str(entry[0])] = (int(entry[1]), int(entry[2]))
        sel = action.get("selected_model")
        state = charge_model_plan_state(
            game_state, unit_id, prov, selected_model=(str(sel) if sel is not None else None)
        )
        return True, {"action": "charge_plan_state", "unitId": unit_id, **state}

    elif action_type == "skip":
        # Fin de phase manuelle (API) : forfait charge sans WAIT ni journalisation « wait » par unité
        # (had_valid_destinations=False → end_activation PASS, pas d'entrée action_logs type wait, pas +step).
        if action.get("manual_end_phase"):
            success, result = _handle_skip_action(
                game_state, active_unit, had_valid_destinations=False
            )
            result["action"] = "skip"
            result["skip_reason"] = "manual_end_phase"
            return success, result
        # Ignore skip action if unit is not active in charge phase
        # This prevents skip actions from shooting phase being processed in charge phase
        active_charge_unit = game_state.get("active_charge_unit")
        if active_charge_unit != unit_id:
            pool_ids = [str(u) for u in require_key(game_state, "charge_activation_pool")]
            if str(unit_id) in pool_ids:
                # Unit in charge pool but not activated (e.g. API end_phase without activate_unit).
                # Match active-unit skip: had_valid_destinations=True (AI_TURN.md line 515 path).
                return _handle_skip_action(game_state, active_unit, had_valid_destinations=True)
            # CRITICAL: In gym training mode, skip must NOT trigger activation or movement.
            # Determine had_valid_destinations without executing charge logic.
            if is_gym_training:
                had_valid_destinations = _has_valid_charge_target(game_state, active_unit, None)
                return _handle_skip_action(game_state, active_unit, had_valid_destinations=had_valid_destinations)
            # PvE AI: treat skip as explicit wait to avoid infinite loop on non-active unit
            if "pve_mode" not in config:
                config_pve_mode = False
            else:
                config_pve_mode = config["pve_mode"]
            if not isinstance(config_pve_mode, bool):
                raise ValueError(f"pve_mode must be boolean (got {type(config_pve_mode).__name__})")
            current_player = require_key(game_state, "current_player")
            is_pve_ai = config_pve_mode and current_player == 2
            if is_pve_ai:
                had_valid_destinations = _has_valid_charge_target(game_state, active_unit, None)
                return _handle_skip_action(game_state, active_unit, had_valid_destinations=had_valid_destinations)
            # Unit not in charge pool and not active — ignore (e.g. stale action)
            return True, {"action": "no_effect", "unitId": unit_id, "reason": "unit_not_active_in_charge_phase"}
        # AI_TURN.md Line 515: Agent chooses wait (has valid destinations, chooses to skip)
        return _handle_skip_action(game_state, active_unit, had_valid_destinations=True)

    elif action_type == "left_click":
        return charge_click_handler(game_state, unit_id, action)

    elif action_type == "right_click":
        # AI_TURN.md Line 536: Human cancels (right-click on active unit)
        return _handle_skip_action(game_state, active_unit, had_valid_destinations=False)

    elif action_type == "invalid":
        # Handle invalid actions with training penalty
        if unit_id in game_state["charge_activation_pool"]:
            # Clear preview first
            charge_clear_preview(game_state)

            # Invalid action during charge phase
            result = end_activation(
                game_state, active_unit,
                ERROR,       # Arg1: Error logging (invalid action)
                1,           # Arg2: +1 step increment
                PASS,        # Arg3: No tracking
                CHARGE,      # Arg4: Remove from charge pool
                1            # Arg5: Error logging
            )
            result["invalid_action_penalty"] = True
            # CRITICAL: No default value - require explicit attempted_action
            attempted_action = action.get("attempted_action")
            if attempted_action is None:
                raise ValueError(f"Action missing 'attempted_action' field: {action}")
            result["attempted_action"] = attempted_action
            return True, result
        return False, {"error": "unit_not_eligible", "unitId": unit_id, "action": action_type}

    else:
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "charge"}


def _handle_unit_activation(game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Charge unit activation start + execution loop"""
    # Unit activation start
    charge_unit_activation_start(game_state, unit["id"])

    # Unit execution loop (automatic)
    execution_result = charge_unit_execution_loop(game_state, unit["id"])
    if "debug_mode" in game_state and game_state["debug_mode"]:
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        add_debug_file_log(
            game_state,
            f"[CHARGE TRACE] E{episode} T{turn} _handle_unit_activation unit_id={unit['id']} "
            f"execution_result_ok={execution_result[0] if isinstance(execution_result, tuple) else 'invalid'}"
        )

    # Clean flag detection
    # AI_TURN.md COMPLIANCE: Direct field access with explicit validation
    if "gym_training_mode" not in config:
        config_gym_mode = False  # Explicit: not in training mode if flag absent
    else:
        config_gym_mode = config["gym_training_mode"]

    if "gym_training_mode" not in game_state:
        state_gym_mode = False  # Explicit: not in training mode if flag absent
    else:
        state_gym_mode = game_state["gym_training_mode"]

    is_gym_training = config_gym_mode or state_gym_mode

    # Determine PvE AI context (non-gym) for auto charge execution
    if "pve_mode" not in config:
        config_pve_mode = False
    else:
        config_pve_mode = config["pve_mode"]
    if not isinstance(config_pve_mode, bool):
        raise ValueError(f"pve_mode must be boolean (got {type(config_pve_mode).__name__})")
    current_player = require_key(game_state, "current_player")
    is_pve_ai = config_pve_mode and current_player == 2

    # AI_TURN.md COMPLIANCE: In gym training, AI executes charge directly without waiting_for_player
    # PvE AI uses the same auto-execution path to avoid waiting for human input.
    if (is_gym_training or is_pve_ai) and isinstance(execution_result, tuple) and execution_result[0]:
        # AI_TURN.md COMPLIANCE: Direct field access
        if "waiting_for_player" not in execution_result[1]:
            waiting_for_player = False
        else:
            waiting_for_player = execution_result[1]["waiting_for_player"]

        if waiting_for_player:
            if "debug_mode" in game_state and game_state["debug_mode"]:
                episode = game_state.get("episode_number", "?")
                turn = game_state.get("turn", "?")
                add_debug_file_log(
                    game_state,
                    f"[CHARGE TRACE] E{episode} T{turn} _handle_unit_activation waiting_for_player=True "
                    f"unit_id={unit['id']} is_pve_ai={is_pve_ai} is_gym_training={is_gym_training}"
                )
            if "valid_targets" not in execution_result[1]:
                raise KeyError("Execution result missing required 'valid_targets' field")
            valid_targets = execution_result[1]["valid_targets"]

            if valid_targets:
                # AI_TURN.md: AI selects target automatically and executes charge directly
                # Do NOT return waiting_for_player=True - execute charge automatically
                if is_pve_ai:
                    selected_target = _ai_select_charge_target_pve(game_state, unit, valid_targets)
                else:
                    selected_target = valid_targets[0]
                if selected_target is None:
                    return _handle_skip_action(game_state, unit, had_valid_destinations=False)
                target_id = selected_target["id"]
                if game_state.get("debug_mode", False):
                    episode = game_state.get("episode_number", "?")
                    turn = game_state.get("turn", "?")
                    add_debug_file_log(
                        game_state,
                        f"[PVE CHARGE AUTO] E{episode} T{turn} unit_id={unit['id']} target_id={target_id}"
                    )
                
                # Execute target selection handler which will roll 2d6, build destinations, and execute charge
                # This follows AI_TURN.md: roll → select target → build destinations → select destination → execute
                from engine.phase_handlers.charge_handlers import charge_target_selection_handler
                target_action = {
                    "action": "charge",
                    "unitId": unit["id"],
                    "targetId": target_id
                }
                return charge_target_selection_handler(game_state, unit["id"], target_action)
            else:
                # No valid targets - auto skip
                return _handle_skip_action(game_state, unit, had_valid_destinations=False)

    # All non-gym players (humans AND PvE AI) get normal waiting_for_player response
    return execution_result


def _ai_select_charge_target_pve(game_state: Dict[str, Any], unit: Dict[str, Any], valid_targets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    PvE AI selects charge target using priority logic per AI_TURN.md.

    Priority order:
    1. Enemy closest to death (lowest HP_CUR)
    2. Highest threat (max of all weapons: STR × NB)
    """
    if not valid_targets:
        return None

    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Calculate threat from all weapons
    # Calculate priority score for each target
    def priority_score(t):
        # Priority 1: Lowest HP (higher priority = lower HP) (Phase 2: HP from cache)
        hp_cur = require_hp_from_cache(str(t["id"]), game_state)
        hp_priority = -hp_cur  # Negative so lower HP = higher score

        # Priority 2: Highest threat
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Calculate threat from all weapons
        melee_threat = 0.0
        if t.get("CC_WEAPONS"):
            # Calculate max threat from all melee weapons
            for weapon in t["CC_WEAPONS"]:
                threat = require_key(weapon, "STR") * expected_dice_value(require_key(weapon, "NB"), "charge_melee_nb")
                melee_threat = max(melee_threat, threat)
        
        ranged_threat = 0.0
        if t.get("RNG_WEAPONS"):
            # Calculate max threat from all ranged weapons
            for weapon in t["RNG_WEAPONS"]:
                threat = require_key(weapon, "STR") * expected_dice_value(require_key(weapon, "NB"), "charge_ranged_nb")
                ranged_threat = max(ranged_threat, threat)
        
        threat = max(melee_threat, ranged_threat)

        return (hp_priority, threat)

    # Select target with highest priority
    best_target = max(valid_targets, key=priority_score)
    return best_target


def _charge_obstacle_socles(game_state: Dict[str, Any], exclude_unit_id: str) -> List[Any]:
    """Socles des unités obstacles (``units_cache`` hors squad chargeur), construits UNE fois.

    Perf : évite de reconstruire les socles voisins à chaque cellule candidate dans les BFS de pool.
    """
    from engine.hex_utils import Socle

    units_cache = require_key(game_state, "units_cache")
    out: List[Any] = []
    for uid, entry in units_cache.items():
        if str(uid) == str(exclude_unit_id):
            continue
        occ = entry.get("occupied_hexes")
        col = int(entry["col"])
        row = int(entry["row"])
        fp = set(occ) if occ else {(col, row)}
        out.append(Socle(shape=entry["BASE_SHAPE"], base_size=entry["BASE_SIZE"], col=col, row=row, fp=fp))
    return out


def _charge_model_placement_overlaps(
    cand_socle: Any,
    obstacle_socles: List[Any],
    sibling_socles: List[Any],
    wall_hexes: Set[Tuple[int, int]],
) -> bool:
    """True si le placement final d'une figurine de charge chevauche un obstacle.

    Murs : discret (``cand_fp & wall_hexes``). Autres unités/ennemis (``obstacle_socles``,
    pré-construits) et coéquipières (``sibling_socles``) : clearance continu rond↔rond, fallback
    empreinte — via ``footprints_overlap``.
    """
    from engine.hex_utils import footprints_overlap

    if wall_hexes and (cand_socle.fp & wall_hexes):
        return True
    for o in obstacle_socles:
        if footprints_overlap(cand_socle, o):
            return True
    for sib in sibling_socles:
        if footprints_overlap(cand_socle, sib):
            return True
    return False


def charge_build_model_destinations_pool(
    game_state: Dict[str, Any],
    model_id: str,
    target_ids: List[str],
    charge_roll_subhex: int,
    provisional_plan: Optional[Dict[str, Tuple[int, int]]] = None,
) -> Dict[str, Any]:
    """Pool de destinations par-figurine pour le mouvement de charge (V11, move par-figurine).

    BFS d'UNE figurine du squad chargeur dans le budget = jet de charge (sous-hex), sans
    traverser murs ni figs (ennemies, alliées, coéquipières). ``provisional_plan``
    ({model_id: (col, row)}) remplace les positions des coéquipières déjà posées dans le plan UI
    (recompute temps réel). Contrairement au move, l'EZ ennemie n'est PAS interdite (une charge
    finit dans l'EZ des cibles déclarées).

    Chaque destination valide est classée selon 11.04 WHILE MOVING ; toute destination où la
    figurine engagerait un ennemi NON déclaré est exclue (AFTER MOVING : aucun non-cible) :
      - within_1 : la figurine finit à <= 1" d'au moins une cible déclarée
      - engaged  : la figurine finit engagée (<= EZ) d'au moins une cible déclarée
      - closer   : la figurine finit plus proche d'au moins une cible qu'à son départ (= pool légal de base)

    within_1 ⊆ engaged ⊆ closer. Retour : {"within_1", "engaged", "closer"} (listes de [col, row]).
    Lecture pure (aucune écriture permanente dans game_state).
    """
    from collections import deque
    from engine.hex_utils import min_distance_between_sets
    from engine.spatial_relations import unit_entries_within_engagement_zone
    from .shared_utils import get_engagement_zone

    models_cache = require_key(game_state, "models_cache")
    model = models_cache.get(str(model_id))
    if model is None:
        raise KeyError(f"charge_build_model_destinations_pool: model {model_id} not in models_cache")
    squad_id = str(model["squad_id"])
    unit = get_unit_by_id(game_state, squad_id)
    empty = {"within_1": [], "engaged": [], "closer": []}
    if not unit:
        return empty

    ez = int(get_engagement_zone(game_state))
    within_1_zone = int(game_state["inches_to_subhex"])  # 1" en sous-hex
    budget = int(charge_roll_subhex)

    board_cols = int(require_key(game_state, "board_cols"))
    board_rows = int(require_key(game_state, "board_rows"))
    wall_hexes = game_state.get("wall_hexes", set())
    player = int(model["player"])
    units_cache = require_key(game_state, "units_cache")

    # Cibles déclarées (entrées + empreintes) et ennemis NON déclarés (exclusion d'engagement).
    declared = {str(t) for t in target_ids}
    target_entries: List[Dict[str, Any]] = []
    target_fps: List[Set[Tuple[int, int]]] = []
    nontarget_entries: List[Dict[str, Any]] = []
    enemy_occupied: Set[Tuple[int, int]] = set()
    other_occupied: Set[Tuple[int, int]] = set()
    for eid, entry in units_cache.items():
        occ = entry.get("occupied_hexes")
        cells = set(occ) if occ else {(int(entry["col"]), int(entry["row"]))}
        if int(entry["player"]) != player:
            enemy_occupied |= cells
            if str(eid) in declared:
                target_entries.append(entry)
                target_fps.append(cells)
            else:
                nontarget_entries.append(entry)
        elif str(eid) != squad_id:
            other_occupied |= cells
    if not target_entries:
        return empty

    # Coéquipières : collision PAR-FIGURINE — chaque fig (et la fig mobile) utilise SA propre base
    # (models_cache), pas celle de l'unité (cf. personnage attaché à plus grande base). Le plan
    # provisoire override les figs déjà posées.
    sibling_socles: List[Any] = []
    squad_models = require_key(game_state, "squad_models")
    for mid in require_key(squad_models, squad_id):
        if str(mid) == str(model_id):
            continue
        sib = models_cache.get(str(mid))
        if sib is None:
            continue
        if provisional_plan and str(mid) in provisional_plan:
            pc, pr = provisional_plan[str(mid)]
        else:
            pc, pr = int(sib["col"]), int(sib["row"])
        sibling_socles.append(_charge_model_socle(game_state, sib, int(pc), int(pr)))

    # 03.01 : une figurine se déplace À TRAVERS les figs amies, mais PAS à travers les ennemies (ni
    # les murs). Chemin au sol = murs + ennemis seulement ; les amis (coéquipières + autres unités
    # amies) ne bloquent pas le passage.
    path_blocked = set(wall_hexes) | enemy_occupied
    # 03 « Ending a move » : le non-chevauchement final (murs + unités + coéquipières) est délégué à
    # _charge_model_placement_overlaps (clearance continu rond↔rond, fallback empreinte).
    # Take to the skies (21.03) : si le vol est actif, la traversée ignore tout ; seul le placement
    # final (``cand_fp & end_blocked``) reste interdit d'overlap. Sinon, traversée sol classique.
    fly_active = _charge_fly_active(game_state, unit, squad_id)
    traverse_blocked = set() if fly_active else path_blocked

    start_col, start_row = int(model["col"]), int(model["row"])
    start_fp = _charge_model_footprint(game_state, model, start_col, start_row)
    start_min = min(min_distance_between_sets(start_fp, tfp) for tfp in target_fps)

    # BFS centre-à-centre dans le budget : ne traverse ni mur ni fig ENNEMIE (amies traversables, vol = tout).
    visited: Set[Tuple[int, int]] = {(start_col, start_row)}
    reachable: List[Tuple[int, int]] = []
    queue: deque = deque([(start_col, start_row, 0)])
    while queue:
        c, r, d = queue.popleft()
        if d >= budget:
            continue
        for nc, nr in get_hex_neighbors(c, r):
            if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
                continue
            cell = (nc, nr)
            if cell in visited or cell in traverse_blocked:
                continue
            visited.add(cell)
            queue.append((nc, nr, d + 1))
            reachable.append(cell)

    within_1: List[List[int]] = []
    engaged: List[List[int]] = []
    closer: List[List[int]] = []
    obstacle_socles = _charge_obstacle_socles(game_state, squad_id)
    _walls = set(wall_hexes)
    for cc, rr in reachable:
        cand_socle = _charge_model_socle(game_state, model, cc, rr)
        cand_fp = cand_socle.fp
        if any(not (0 <= x < board_cols and 0 <= y < board_rows) for (x, y) in cand_fp):
            continue
        if _charge_model_placement_overlaps(cand_socle, obstacle_socles, sibling_socles, _walls):
            continue
        d_min = min(
            min_distance_between_sets(cand_fp, tfp, max_distance=start_min) for tfp in target_fps
        )
        if d_min >= start_min:
            continue  # WHILE MOVING : doit finir plus proche d'au moins une cible
        synth = _charge_synthetic_charger_cache_entry(game_state, unit, cc, rr, cand_fp)
        if any(unit_entries_within_engagement_zone(synth, ne, ez) for ne in nontarget_entries):
            continue  # AFTER MOVING : aucun engagement avec un ennemi non déclaré
        closer.append([cc, rr])
        if any(unit_entries_within_engagement_zone(synth, te, ez) for te in target_entries):
            engaged.append([cc, rr])
        if any(unit_entries_within_engagement_zone(synth, te, within_1_zone) for te in target_entries):
            within_1.append([cc, rr])

    return {"within_1": within_1, "engaged": engaged, "closer": closer}


def _charge_qualifying(
    reach_by_model: Dict[str, List[Tuple[int, int]]],
    start_min_by_model: Dict[str, int],
    other_origins_by_model: Dict[str, Set[Tuple[int, int]]],
    region_by_base: Dict[Any, Dict[Tuple[int, int], Dict[str, Any]]],
    base_of_model: Dict[str, Any],
    model_id: str,
    key: str,
) -> List[List[int]]:
    """Hexes de ``model_id`` qualifiant ``key`` (within_1 / engaged / closer) : reach ∩ region,
    plus proche que son départ, sans chevaucher une coéquipière encore à l'origine. Lit uniquement
    les structures du contexte mémoïsé (aucun calcul lourd) → utilisable sur cache hit."""
    out: List[List[int]] = []
    reach = reach_by_model.get(model_id)
    if not reach:
        return out
    start_min = start_min_by_model.get(model_id)
    if start_min is None:
        return out
    others = other_origins_by_model.get(model_id, set())
    reg_m = region_by_base.get(base_of_model.get(model_id), {})
    for h in reach:
        rg = reg_m.get(h)
        if rg is None:
            continue
        if rg["d_min"] >= start_min:
            continue
        if others and (rg["fp"] & others):
            continue
        if key == "within_1" and not rg["within_1"]:
            continue
        if key == "engaged" and not rg["engaged"]:
            continue
        out.append([h[0], h[1]])
    return out


def _compute_plan_context(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    unit_id: str,
    provisional_plan: Dict[str, Tuple[int, int]],
    target_ids: List[Any],
    roll_subhex: int,
    fly_active: bool,
    _perf: bool,
) -> Dict[str, Any]:
    """Calcul lourd PLAN-dépendant (indépendant de ``selected_model``) → mis en cache.

    Produit : reachability BFS par fig, champs de distance, classification ``region_by_base`` (le
    poste dominant ~92 %), phase courante, éligibilité, validation finale et satisfaction des cibles.
    Renvoie le ``ctx`` réutilisé tant que (plan, positions, roll, vol, cibles) ne changent pas.
    """
    from collections import deque
    from engine.spatial_relations import unit_entries_within_engagement_zone, _entry_is_multi_figure
    from .shared_utils import get_engagement_zone

    _acc_bfs = 0.0
    _acc_distfield = 0.0
    _acc_region = 0.0

    squad_models = require_key(game_state, "squad_models")
    models_cache = require_key(game_state, "models_cache")
    units_cache = require_key(game_state, "units_cache")
    alive = [m for m in require_key(squad_models, str(unit_id)) if m in models_cache]
    placed = {str(k) for k in provisional_plan}
    unplaced = [str(m) for m in alive if str(m) not in placed]

    ez = int(get_engagement_zone(game_state))
    within_1_zone = int(game_state["inches_to_subhex"])
    budget = int(roll_subhex)
    board_cols = int(require_key(game_state, "board_cols"))
    board_rows = int(require_key(game_state, "board_rows"))
    wall_hexes = game_state.get("wall_hexes", set())
    player = int(unit["player"])

    # Cibles déclarées (empreintes) + ennemis non déclarés (exclusion d'engagement) + occupation.
    declared = {str(t) for t in target_ids}
    target_entries: List[Dict[str, Any]] = []
    target_fps: List[Set[Tuple[int, int]]] = []
    nontarget_entries: List[Dict[str, Any]] = []
    enemy_occupied: Set[Tuple[int, int]] = set()
    other_occupied: Set[Tuple[int, int]] = set()
    for eid, entry in units_cache.items():
        occ = entry.get("occupied_hexes")
        cells = set(occ) if occ else {(int(entry["col"]), int(entry["row"]))}
        if int(entry["player"]) != player:
            enemy_occupied |= cells
            if str(eid) in declared:
                target_entries.append(entry)
                target_fps.append(cells)
            else:
                nontarget_entries.append(entry)
        elif str(eid) != str(unit_id):
            other_occupied |= cells

    # Coéquipières PAR-FIGURINE (chaque fig a sa base) : posées (plan) = bloquage stable ; non posées
    # = bloquage à l'origine (la fig mobile retire le sien dans _qualifying).
    placed_sibling_socles: List[Any] = []
    for _mid, (_pc, _pr) in provisional_plan.items():
        _sib = models_cache.get(str(_mid))
        if _sib is None:
            continue
        placed_sibling_socles.append(_charge_model_socle(game_state, _sib, int(_pc), int(_pr)))
    origin_fp: Dict[str, Set[Tuple[int, int]]] = {}
    for m in unplaced:
        sib = models_cache.get(str(m))
        origin_fp[m] = (
            _charge_model_footprint(game_state, sib, int(sib["col"]), int(sib["row"]))
            if sib else set()
        )
    # 03.01 : le déplacement traverse les figs AMIES, pas les ennemies ni les murs → chemin = murs +
    # ennemis seulement. Les coéquipières (posées ou à l'origine) ne bloquent que la position FINALE
    # (``cand_fp & blocked_static`` posées + check ``others`` origines dans ``_qualifying``).
    path_blocked = set(wall_hexes) | enemy_occupied
    # Take to the skies (21.03) : vol actif → la reachability BFS et le champ de distance ignorent
    # tout (traversée libre) ; le placement final (``cand_fp & blocked_static``, collision ``others``)
    # reste interdit d'overlap.
    fly_active = _charge_fly_active(game_state, unit, unit_id)

    def _bfs_reach(
        start_col: int, start_row: int, blocked: Set[Tuple[int, int]]
    ) -> Tuple[List[Tuple[int, int]], Dict[Tuple[int, int], int]]:
        """Retourne (reach, dist) : hexes atteignables dans le budget + distance de mouvement (profondeur
        BFS, sous-hex) par hex. Au sol = path (détours autour murs/figs) ; en vol = distance directe."""
        visited: Set[Tuple[int, int]] = {(start_col, start_row)}
        reach: List[Tuple[int, int]] = []
        dist: Dict[Tuple[int, int], int] = {(start_col, start_row): 0}
        queue: deque = deque([(start_col, start_row, 0)])
        while queue:
            c, r, d = queue.popleft()
            if d >= budget:
                continue
            for nc, nr in get_hex_neighbors(c, r):
                if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
                    continue
                cell = (nc, nr)
                if cell in visited or cell in blocked:
                    continue
                visited.add(cell)
                dist[cell] = d + 1
                queue.append((nc, nr, d + 1))
                reach.append(cell)
        return reach, dist

    # Marge (sous-hex) autour des unités où l'on lance le check d'engagement PRÉCIS : couvre l'écart
    # entre distance d'empreinte (hex) et clairance euclidienne (socles ronds). Au-delà = jamais engagé.
    _ENG_MARGIN = within_1_zone

    def _dist_field(seeds: Set[Tuple[int, int]], max_steps: int) -> Dict[Tuple[int, int], int]:
        """BFS multi-source : distance (hex) de chaque case à ``seeds``, bornée à ``max_steps`` (cases
        au-delà absentes). Ne traverse pas les murs. Sert à obtenir d_min en O(1) par hex (le calcul de
        distance par hex via min_distance_between_sets était le 2e poste de coût)."""
        dist: Dict[Tuple[int, int], int] = {}
        frontier: List[Tuple[int, int]] = []
        for s in seeds:
            if 0 <= s[0] < board_cols and 0 <= s[1] < board_rows:
                dist[s] = 0
                frontier.append(s)
        step = 0
        while frontier and step < max_steps:
            step += 1
            nxt: List[Tuple[int, int]] = []
            for (c, r) in frontier:
                for nc, nr in get_hex_neighbors(c, r):
                    if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
                        continue
                    cell = (nc, nr)
                    if cell in dist or (not fly_active and cell in wall_hexes):
                        continue
                    dist[cell] = step
                    nxt.append(cell)
            frontier = nxt
        return dist

    can_classify = bool(target_fps)
    # 1) Reachability BFS par fig (cheap) + champs de distance (cibles / non-cibles), calculés 1×.
    reach_by_model: Dict[str, List[Tuple[int, int]]] = {}
    dist_by_model: Dict[str, Dict[Tuple[int, int], int]] = {}
    start_min_by_model: Dict[str, int] = {}
    other_origins_by_model: Dict[str, Set[Tuple[int, int]]] = {}
    dist_tgt: Dict[Tuple[int, int], int] = {}
    dist_ntgt: Dict[Tuple[int, int], int] = {}
    INF = int(budget) + 1
    if can_classify:
        for m in unplaced:
            sib = models_cache.get(str(m))
            if sib is None:
                continue
            sc, sr = int(sib["col"]), int(sib["row"])
            other_origins = set()
            for m2 in unplaced:
                if m2 != m:
                    other_origins |= origin_fp[m2]
            other_origins_by_model[m] = other_origins
            _tb = time.perf_counter() if _perf else None
            reach_by_model[m], dist_by_model[m] = _bfs_reach(
                sc, sr, set() if fly_active else path_blocked
            )
            if _perf and _tb is not None:
                _acc_bfs += time.perf_counter() - _tb
        tgt_union: Set[Tuple[int, int]] = set()
        for tfp in target_fps:
            tgt_union |= tfp
        _td = time.perf_counter() if _perf else None
        dist_tgt = _dist_field(tgt_union, int(budget))
        if _perf and _td is not None:
            _acc_distfield += time.perf_counter() - _td
        for m in list(reach_by_model.keys()):
            sib = models_cache.get(str(m))
            sfp = _charge_model_footprint(game_state, sib, int(sib["col"]), int(sib["row"]))
            start_min_by_model[m] = min((dist_tgt.get(h, INF) for h in sfp), default=INF)
        if nontarget_entries:
            ntgt_union: Set[Tuple[int, int]] = set()
            for ne in nontarget_entries:
                occ = ne.get("occupied_hexes")
                ntgt_union |= set(occ) if occ else {(int(ne["col"]), int(ne["row"]))}
            _td2 = time.perf_counter() if _perf else None
            dist_ntgt = _dist_field(ntgt_union, ez + _ENG_MARGIN)
            if _perf and _td2 is not None:
                _acc_distfield += time.perf_counter() - _td2

    # 2) Classification PAR BASE (pas par figurine) : les figs de MÊME socle (ex. 9 terminators)
    #    classent les hexes à l'identique → on classe une seule fois par base distincte (1 pour une
    #    escouade homogène, 2 avec un personnage attaché). dist_tgt/dist_ntgt sont indépendants de la
    #    base (calculés 1×) ; seul le footprint candidat dépend de la base. Le filtre « plus proche que
    #    le départ » (per-modèle) est appliqué dans _qualifying ; ici on élague au cap global de la base.
    def _base_key(model_entry: Dict[str, Any]) -> Tuple[Any, Any, int]:
        bs = model_entry["BASE_SIZE"]
        return (
            model_entry["BASE_SHAPE"],
            tuple(bs) if isinstance(bs, (list, tuple)) else bs,
            int(model_entry.get("orientation", 0)),
        )

    base_of_model: Dict[str, Tuple[Any, Any, int]] = {}
    reach_by_base: Dict[Tuple[Any, Any, int], Tuple[Dict[str, Any], Set[Tuple[int, int]], int]] = {}
    for m in reach_by_model:
        m_model = models_cache.get(str(m))
        if m_model is None:
            continue
        bk = _base_key(m_model)
        base_of_model[m] = bk
        m_cap = start_min_by_model.get(m, INF)
        if bk not in reach_by_base:
            reach_by_base[bk] = (m_model, set(reach_by_model[m]), m_cap)
        else:
            rep, cells, cap = reach_by_base[bk]
            cells.update(reach_by_model[m])
            reach_by_base[bk] = (rep, cells, max(cap, m_cap))

    region_by_base: Dict[Tuple[Any, Any, int], Dict[Tuple[int, int], Dict[str, Any]]] = {}
    _tr = time.perf_counter() if _perf else None
    if can_classify:
        obstacle_socles = _charge_obstacle_socles(game_state, unit_id)
        _walls = set(wall_hexes)
        synth_base = dict(require_key(units_cache, str(require_key(unit, "id"))))
        synth_base.pop("occupied_hexes_by_model", None)
        synth_shape = synth_base["BASE_SHAPE"]

        # PERF : le test d'engagement précis (``unit_entries_within_engagement_zone``) coûte un
        # ``min_distance_between_sets`` en O(empreinte × empreinte) par cellule (poste dominant ~92 %).
        # Pour les ennemis qui passent par la **métrique d'empreinte** (multi-figurine ou base non-ronde),
        # ``min_distance_between_sets(cand_fp, enemy_fp) <= r`` ⟺ ``cand_fp ∩ dilate(enemy_fp, r) ≠ ∅``.
        # On précalcule donc le masque dilaté (set) par ennemi → test = intersection de set native.
        # Les ennemis **ronds simples** gardent le chemin euclidien per-cell (précis, inchangé).
        # Masques mis en cache par ``_unit_move_version`` (positions ennemies) → réutilisés entre voiles.
        def _dilate(seed_fp: Set[Tuple[int, int]], radius: int) -> Set[Tuple[int, int]]:
            seen: Set[Tuple[int, int]] = set(seed_fp)
            frontier: List[Tuple[int, int]] = list(seed_fp)
            for _ in range(int(radius)):
                nxt: List[Tuple[int, int]] = []
                for (c, r) in frontier:
                    for nc, nr in get_hex_neighbors(c, r):
                        cell = (nc, nr)
                        if cell not in seen:
                            seen.add(cell)
                            nxt.append(cell)
                frontier = nxt
            return seen

        _mv = game_state["_unit_move_version"]
        _mcache = game_state.get("_charge_engage_mask_cache")
        if _mcache is None or _mcache.get("version") != _mv:
            _mcache = {"version": _mv, "masks": {}}
            game_state["_charge_engage_mask_cache"] = _mcache
        _masks = _mcache["masks"]

        def _enemy_masks(enemy_fp: Set[Tuple[int, int]]) -> Dict[str, Set[Tuple[int, int]]]:
            k = frozenset(enemy_fp)
            m = _masks.get(k)
            if m is None:
                m = {"ez": _dilate(enemy_fp, ez), "w1": _dilate(enemy_fp, within_1_zone)}
                _masks[k] = m
            return m

        # Propriétés constantes par ennemi (forme, multi-figurine) + empreinte + masques.
        nontarget_fps = [
            set(ne["occupied_hexes"]) if ne.get("occupied_hexes") else {(int(ne["col"]), int(ne["row"]))}
            for ne in nontarget_entries
        ]
        tgt_shape = [te["BASE_SHAPE"] for te in target_entries]
        tgt_multi = [_entry_is_multi_figure(te) for te in target_entries]
        tgt_masks = [_enemy_masks(fp) for fp in target_fps]
        ntgt_shape = [ne["BASE_SHAPE"] for ne in nontarget_entries]
        ntgt_multi = [_entry_is_multi_figure(ne) for ne in nontarget_entries]
        ntgt_masks = [_enemy_masks(fp) for fp in nontarget_fps]

        def _eng(enemy_entry, e_shape, e_multi, mask, radius, cand_fp, cand_is_multi):
            # Chemin euclidien (rond simple ↔ rond simple) : on conserve la fonction partagée (précis).
            if radius > 1 and synth_shape == "round" and e_shape == "round" and not cand_is_multi and not e_multi:
                return unit_entries_within_engagement_zone(synth_base, enemy_entry, radius)
            # Chemin empreinte : intersection avec le masque dilaté (équivalent exact à min_distance ≤ r).
            return bool(cand_fp & mask)

        for bk, (rep_model, cells, cap_base) in reach_by_base.items():
            reg_b: Dict[Tuple[int, int], Dict[str, Any]] = {}
            for (cc, rr) in cells:
                cand_socle = _charge_model_socle(game_state, rep_model, cc, rr)
                cand_fp = cand_socle.fp
                if any(not (0 <= x < board_cols and 0 <= y < board_rows) for (x, y) in cand_fp):
                    continue
                d_min = min((dist_tgt.get(h, INF) for h in cand_fp), default=INF)
                # Élague au cap global de la base (aucune de ses figs ne peut finir aussi loin).
                # PERF : prune cheap (lookups dist_tgt) AVANT le check collision (cher) — une cellule
                # élaguée ici n'entre jamais dans region, donc son verdict collision est sans effet.
                if d_min >= cap_base:
                    continue
                if _charge_model_placement_overlaps(cand_socle, obstacle_socles, placed_sibling_socles, _walls):
                    continue
                d_ntgt = (
                    min((dist_ntgt.get(h, INF) for h in cand_fp), default=INF) if dist_ntgt else INF
                )
                near_ntgt = d_ntgt <= ez + _ENG_MARGIN
                near_tgt = d_min <= ez + _ENG_MARGIN
                near_w1 = d_min <= within_1_zone + _ENG_MARGIN
                cand_is_multi = False
                if near_ntgt or near_tgt or near_w1:
                    synth_base["col"] = cc
                    synth_base["row"] = rr
                    synth_base["occupied_hexes"] = cand_fp
                    cand_is_multi = _entry_is_multi_figure(synth_base)
                if near_ntgt and any(
                    _eng(ne, ntgt_shape[i], ntgt_multi[i], ntgt_masks[i]["ez"], ez, cand_fp, cand_is_multi)
                    for i, ne in enumerate(nontarget_entries)
                ):
                    continue
                engaged_f = (
                    near_tgt
                    and any(
                        _eng(te, tgt_shape[i], tgt_multi[i], tgt_masks[i]["ez"], ez, cand_fp, cand_is_multi)
                        for i, te in enumerate(target_entries)
                    )
                )
                within1_f = (
                    near_w1
                    and any(
                        _eng(te, tgt_shape[i], tgt_multi[i], tgt_masks[i]["w1"], within_1_zone, cand_fp, cand_is_multi)
                        for i, te in enumerate(target_entries)
                    )
                )
                reg_b[(cc, rr)] = {"fp": cand_fp, "d_min": d_min, "within_1": within1_f, "engaged": engaged_f}
            region_by_base[bk] = reg_b
    if _perf and _tr is not None:
        _acc_region += time.perf_counter() - _tr

    def _qual(m: str, k: str) -> List[List[int]]:
        return _charge_qualifying(
            reach_by_model, start_min_by_model, other_origins_by_model,
            region_by_base, base_of_model, m, k,
        )

    # Phase courante = la plus serrée réalisable par une fig non posée.
    has_within1 = any(_qual(m, "within_1") for m in reach_by_model)
    if has_within1:
        phase, key = 1, "within_1"
    elif any(_qual(m, "engaged") for m in reach_by_model):
        phase, key = 2, "engaged"
    else:
        phase, key = 3, "closer"

    eligible_models = [m for m in unplaced if _qual(m, key)]

    can_validate = False
    if not unplaced and alive:
        full_plan = [(str(m), int(provisional_plan[m][0]), int(provisional_plan[m][1])) for m in alive]
        can_validate = charge_preview_move_plan(game_state, str(unit_id), full_plan, target_ids)["can_validate"]

    # Satisfaction par cible (voile UI) : une cible-UNITÉ est ENGAGÉE dès qu'≥1 fig POSÉE est à
    # ≤EZ d'elle (03.04, engagement au niveau unité). violet = satisfaite, rouge = pas.
    placed_synths = []
    for _mid, (_c, _r) in provisional_plan.items():
        _sib = models_cache.get(str(_mid))
        if _sib is None:
            continue
        _fp = _charge_model_footprint(game_state, _sib, int(_c), int(_r))
        placed_synths.append(
            _charge_synthetic_charger_cache_entry(game_state, unit, int(_c), int(_r), _fp)
        )
    satisfied: List[str] = []
    unsatisfied: List[str] = []
    for tid in (str(t) for t in target_ids):
        tentry = units_cache.get(tid)
        if tentry is None:
            continue
        engaged_t = any(
            unit_entries_within_engagement_zone(synth, tentry, ez) for synth in placed_synths
        )
        (satisfied if engaged_t else unsatisfied).append(tid)

    return {
        "reach_by_model": reach_by_model,
        "dist_by_model": dist_by_model,
        "start_min_by_model": start_min_by_model,
        "other_origins_by_model": other_origins_by_model,
        "region_by_base": region_by_base,
        "base_of_model": base_of_model,
        "key": key,
        "phase": phase,
        "eligible_models": eligible_models,
        "unplaced": unplaced,
        "can_validate": can_validate,
        "satisfied": satisfied,
        "unsatisfied": unsatisfied,
        "_timings": {"bfs": _acc_bfs, "distfield": _acc_distfield, "region": _acc_region},
    }


def charge_model_plan_state(
    game_state: Dict[str, Any],
    unit_id: str,
    provisional_plan: Dict[str, Tuple[int, int]],
    selected_model: Optional[str] = None,
) -> Dict[str, Any]:
    """Orchestration UI du mouvement de charge par-figurine (V11, 3 phases 11.04). Lecture pure
    (hormis l'écriture du cache mémo).

    ``provisional_plan`` : {model_id: (col, row)} figs déjà posées dans le plan UI. Les figs
    absentes sont « non posées » (restent à leur position de départ, models_cache).

    Mémoïsation (le contexte lourd ``ctx`` est indépendant de ``selected_model``) : entre deux
    sélections de figurine sur le MÊME plan, on saute entièrement ``_compute_plan_context`` (BFS,
    champs de distance, classification ``region_by_base`` ~92 % du coût) et on ne recalcule que la
    partie sélection-dépendante (``pool`` / ``pool_distances`` / ``footprint_mask_loops``). La
    signature inclut ``_unit_move_version`` → toute pose/déplacement invalide le cache.

    Retour : {current_phase, eligible_models, pool, pool_distances, footprint_mask_loops, unplaced,
              can_validate, satisfied_targets, unsatisfied_targets}.
    """
    empty = {
        "current_phase": 3,
        "eligible_models": [],
        "pool": [],
        "pool_distances": [],
        "footprint_mask_loops": [],
        "unplaced": [],
        "can_validate": False,
        "satisfied_targets": [],
        "unsatisfied_targets": [],
    }
    unit = get_unit_by_id(game_state, str(unit_id))
    if not unit:
        return empty
    if "charge_target_selections" not in game_state or str(unit_id) not in game_state["charge_target_selections"]:
        return empty
    if "charge_roll_values" not in game_state or str(unit_id) not in game_state["charge_roll_values"]:
        return empty
    _stored = game_state["charge_target_selections"][str(unit_id)]
    target_ids = list(_stored) if isinstance(_stored, (list, tuple)) else [_stored]
    _charge_roll = game_state["charge_roll_values"][str(unit_id)]
    # Take to the skies (21.03) : -2" sur la distance max de charge si le vol est déclaré.
    roll_subhex = _charge_budget_subhex(game_state, unit_id, _charge_roll)
    # Take to the skies (21.03) : vol actif → BFS/champ de distance ignorent tout (traversée libre).
    fly_active = _charge_fly_active(game_state, unit, unit_id)

    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled
    _perf = perf_timing_enabled(game_state)
    _ep = game_state.get("episode_number", "?")
    _turn = game_state.get("turn", "?")
    _t0 = time.perf_counter() if _perf else None

    # Mémoïsation (Tâche 1) : signature capturant TOUT ce qui influe sur le ctx. ``_unit_move_version``
    # est incrémenté à chaque commit move/charge → invalidation auto au moindre déplacement. La sig est
    # comparée par égalité (pas de hash requis) ; en cas de doute on invalide plutôt que servir obsolète.
    sig = (
        str(unit_id),
        tuple(sorted(provisional_plan.items())),
        game_state["_unit_move_version"],
        bool(fly_active),
        _charge_roll,
        tuple(sorted(map(str, target_ids))),
    )
    _cache = game_state.get("_charge_plan_state_cache")
    if _cache is not None and _cache.get("sig") == sig:
        ctx = _cache["ctx"]
        _cache_hit = 1
    else:
        ctx = _compute_plan_context(
            game_state, unit, unit_id, provisional_plan, target_ids, roll_subhex, fly_active, _perf
        )
        game_state["_charge_plan_state_cache"] = {"sig": sig, "ctx": ctx}
        _cache_hit = 0

    reach_by_model = ctx["reach_by_model"]
    dist_by_model = ctx["dist_by_model"]
    start_min_by_model = ctx["start_min_by_model"]
    other_origins_by_model = ctx["other_origins_by_model"]
    region_by_base = ctx["region_by_base"]
    base_of_model = ctx["base_of_model"]
    key = ctx["key"]
    phase = ctx["phase"]
    eligible_models = ctx["eligible_models"]
    unplaced = ctx["unplaced"]
    can_validate = ctx["can_validate"]
    satisfied = ctx["satisfied"]
    unsatisfied = ctx["unsatisfied"]

    # Partie SÉLECTION-dépendante (cheap) : pool de la fig sélectionnée (zone violette).
    _tsel = time.perf_counter() if _perf else None
    pool: List[List[int]] = (
        _charge_qualifying(
            reach_by_model, start_min_by_model, other_origins_by_model,
            region_by_base, base_of_model, str(selected_model), key,
        )
        if selected_model is not None and str(selected_model) in reach_by_model
        else []
    )
    # Distance de mouvement (sous-hex) de la fig sélectionnée vers chaque ancre du pool : profondeur
    # BFS = path réel au sol (détours murs/figs), distance directe en vol. Source du tooltip charge
    # par-figurine (au lieu de la ligne droite qui sous-estime les détours).
    _sel_dist = (
        (dist_by_model[str(selected_model)] if str(selected_model) in dist_by_model else {})
        if selected_model is not None
        else {}
    )
    pool_distances: List[List[int]] = [
        [int(c), int(r), int(_sel_dist[(int(c), int(r))])]
        for (c, r) in pool
        if (int(c), int(r)) in _sel_dist
    ]

    # Empreinte lissée de la zone de landing (même rendu que le move per-fig) : union des empreintes
    # (region[ancre]["fp"]) des ancres du pool → boucles monde via le helper move. Calculé seulement
    # pour la fig sélectionnée (le pool n'existe que pour elle). Le front rend ces loops en polygone
    # lissé (Chaikin), au lieu de disques bruts festonnés.
    footprint_mask_loops: List[List[List[float]]] = []
    if pool:
        from engine.hex_union_boundary_polygon import compute_move_preview_mask_loops_world
        _sel_region = region_by_base.get(base_of_model.get(str(selected_model)), {}) if selected_model is not None else {}
        fp_zone: Set[Tuple[int, int]] = set()
        for _c, _r in pool:
            rg = _sel_region.get((int(_c), int(_r)))
            if rg is not None:
                fp_zone |= rg["fp"]
        loops = compute_move_preview_mask_loops_world(fp_zone, game_state)
        if loops:
            footprint_mask_loops = [[[float(x), float(y)] for (x, y) in loop] for loop in loops]

    if _perf and _t0 is not None:
        _total = time.perf_counter() - _t0
        _sel_s = (time.perf_counter() - _tsel) if _tsel is not None else 0.0
        _tmg = ctx.get("_timings", {})
        append_perf_timing_line(
            f"CHARGE_MODEL_PLAN_STATE episode={_ep} turn={_turn} unit_id={unit_id} "
            f"selected={selected_model} bfs_s={_tmg.get('bfs', 0.0):.6f} distfield_s={_tmg.get('distfield', 0.0):.6f} "
            f"region_s={_tmg.get('region', 0.0):.6f} sel_s={_sel_s:.6f} total_s={_total:.6f} "
            f"n_unplaced={len(unplaced)} n_bases={len(region_by_base)} phase={phase} cache_hit={_cache_hit}"
        )

    return {
        "current_phase": phase,
        "eligible_models": eligible_models,
        "pool": pool,
        "pool_distances": pool_distances,
        "footprint_mask_loops": footprint_mask_loops,
        "unplaced": unplaced,
        "can_validate": can_validate,
        "satisfied_targets": satisfied,
        "unsatisfied_targets": unsatisfied,
    }


def charge_unit_activation_start(game_state: Dict[str, Any], unit_id: str) -> None:
    """
    Charge unit activation initialization - NO ROLL YET.
    
    NEW RULE: At activation, unit can wait or choose a target.
    The charge roll is performed ONLY AFTER target selection.
    """
    game_state["valid_charge_destinations_pool"] = []
    game_state["preview_hexes"] = []
    game_state["active_charge_unit"] = unit_id
    # Do NOT roll 2d6 here - roll happens after target selection


def charge_build_valid_targets(game_state: Dict[str, Any], unit_id: str, max_distance: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Build list of valid charge targets for unit activation.

    Valid target criteria:
    - Enemy unit
    - Not already in **engagement** with the charger vs **that** target only
      (``unit_entries_within_engagement_zone`` — same contract as move / ``_charge_unit_within_engagement_zone`` ;
      not ``unit_fp & dilate_hex`` which wrongly dropped a legally close target).
    - At least one legal charge end anchor vs that target from BFS-reachable hexes within ``charge_max_distance``.

    Returns list of target dicts with unit info.
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled
    _perf = perf_timing_enabled(game_state)
    _ep = game_state.get("episode_number", "?")
    _turn = game_state.get("turn", "?")
    _t_bvt0 = time.perf_counter() if _perf else None

    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return []

    _bvt_cache = game_state.setdefault("_charge_build_valid_targets_cache", {})
    _move_version = game_state["_unit_move_version"]
    _bvt_key = (str(unit_id), _move_version, max_distance)
    if _bvt_key in _bvt_cache:
        if _perf and _t_bvt0 is not None:
            append_perf_timing_line(
                f"CHARGE_BUILD_VALID_TARGETS episode={_ep} turn={_turn} unit_id={unit_id} "
                f"bfs_s=0.000000 geom_loop_s=0.000000 total_s={time.perf_counter() - _t_bvt0:.6f} "
                f"n_reachable=0 n_enemies=0 n_valid={len(_bvt_cache[_bvt_key])} cache_hit=1"
            )
        return _bvt_cache[_bvt_key]

    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    CHARGE_MAX_DISTANCE = require_key(require_key(game_state["config"], "charge"), "charge_max_distance")
    effective_max = int(max_distance) if max_distance is not None else CHARGE_MAX_DISTANCE
    valid_targets = []

    # Build all hexes reachable via BFS within max charge distance (jet en roll-first, sinon 12").
    try:
        reachable_hexes = charge_build_valid_destinations_pool(game_state, unit_id, effective_max)
    except Exception as e:
        add_console_log(game_state, f"ERROR: BFS failed for unit {unit_id}: {str(e)}")
        return []

    if not reachable_hexes:
        _bvt_cache[_bvt_key] = []
        return []  # No reachable hexes

    _t_after_bfs = time.perf_counter() if _perf else None

    # Get all enemies - CRITICAL: is_unit_alive so dead units never enter pool
    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    enemies = [enemy_id for enemy_id, cache_entry in units_cache.items()
               if int(cache_entry["player"]) != unit_player]

    from engine.spatial_relations import unit_entries_within_engagement_zone
    from .shared_utils import get_engagement_zone, build_occupied_positions_set

    engagement_zone = int(get_engagement_zone(game_state))

    fp_offset_pair = _charge_prepare_footprint_offsets(unit, game_state)

    unit_id_str = str(unit["id"])
    unit_entry = require_key(units_cache, unit_id_str)
    occupied_positions = build_occupied_positions_set(game_state, exclude_unit_id=unit_id_str)

    enemy_index: List[Tuple[Any, Dict[str, Any], Set[Tuple[int, int]]]] = []
    for enemy_id in enemies:
        enemy_entry = units_cache.get(str(enemy_id))
        if enemy_entry is None:
            raise KeyError(f"Enemy {enemy_id} not in units_cache (dead or absent)")
        if unit_entries_within_engagement_zone(unit_entry, enemy_entry, engagement_zone):
            continue
        ec, er = int(enemy_entry["col"]), int(enemy_entry["row"])
        enemy_fp = enemy_entry.get("occupied_hexes", {(ec, er)})
        enemy_index.append((enemy_id, enemy_entry, enemy_fp))

    per_enemy_has_geom: Dict[Any, bool] = {eid: False for eid, _, _ in enemy_index}
    per_enemy_non_occ: Dict[Any, bool] = {eid: False for eid, _, _ in enemy_index}

    _t_geom0 = time.perf_counter() if _perf else None
    for dest_col, dest_row in reachable_hexes:
        candidate_fp = _candidate_footprint_charge(dest_col, dest_row, unit, game_state, fp_offset_pair)
        blocked_by_occupation = bool(candidate_fp & occupied_positions)
        synth = _charge_synthetic_charger_cache_entry(game_state, unit, dest_col, dest_row, candidate_fp)
        for enemy_id, enemy_entry, enemy_fp in enemy_index:
            if candidate_fp & enemy_fp:
                continue
            if unit_entries_within_engagement_zone(synth, enemy_entry, engagement_zone):
                per_enemy_has_geom[enemy_id] = True
                if not blocked_by_occupation:
                    per_enemy_non_occ[enemy_id] = True
    _t_geom1 = time.perf_counter() if _perf else None

    for enemy_id, enemy_entry, _enemy_fp in enemy_index:
        if per_enemy_has_geom.get(enemy_id) and per_enemy_non_occ.get(enemy_id):
            ec, er = int(enemy_entry["col"]), int(enemy_entry["row"])
            valid_targets.append({
                "id": enemy_id,
                "col": ec,
                "row": er,
                "HP_CUR": require_hp_from_cache(str(enemy_id), game_state),
                "player": enemy_entry["player"],
            })

    _bvt_cache[_bvt_key] = valid_targets

    # DEBUG LOG — charge target diagnostic
    _valid_ids = [str(t["id"]) for t in valid_targets]
    _excluded = []
    for eid, eentry, _ in enemy_index:
        if str(eid) not in _valid_ids:
            _excluded.append(
                f"unit_{eid}(col={eentry['col']},row={eentry['row']})"
                f" has_geom={per_enemy_has_geom.get(eid)} non_occ={per_enemy_non_occ.get(eid)}"
            )
    add_console_log(game_state, (
        f"[CHARGE_BVT] charger={unit_id} reachable={len(reachable_hexes)} "
        f"valid={_valid_ids} excluded={_excluded}"
    ))
    safe_print(game_state, (
        f"[CHARGE_BVT] charger={unit_id} reachable={len(reachable_hexes)} "
        f"valid={_valid_ids} excluded={_excluded}"
    ))

    if _perf and _t_bvt0 is not None and _t_after_bfs is not None and _t_geom0 is not None and _t_geom1 is not None:
        append_perf_timing_line(
            f"CHARGE_BUILD_VALID_TARGETS episode={_ep} turn={_turn} unit_id={unit_id} "
            f"bfs_s={_t_after_bfs - _t_bvt0:.6f} geom_loop_s={_t_geom1 - _t_geom0:.6f} "
            f"total_s={_t_geom1 - _t_bvt0:.6f} "
            f"n_reachable={len(reachable_hexes)} n_enemies={len(enemy_index)} n_valid={len(valid_targets)} cache_hit=0"
        )

    return valid_targets


def charge_unit_execution_loop(game_state: Dict[str, Any], unit_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Charge unit execution loop - build and return valid charge targets.
    
    NEW RULE: At activation, show all possible charge targets without rolling.
    The roll happens AFTER target selection.
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled
    _perf = perf_timing_enabled(game_state)
    _ep = game_state.get("episode_number", "?")
    _turn = game_state.get("turn", "?")
    _t_el0 = time.perf_counter() if _perf else None

    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id, "action": "charge"}

    # V11 RAW (PvP/PvE) : le jet 2D6 a lieu À L'ACTIVATION (11.02 étape 2), AVANT la
    # déclaration des cibles. Les cibles éligibles sont ensuite bornées par la distance
    # jetée (11.04 « within the maximum distance »). En gym (RL), on conserve le jet au
    # moment de la sélection pour ne pas changer le MDP de l'agent.
    is_gym = game_state.get("gym_training_mode", False)
    charge_roll = None
    max_distance_subhex = None
    if not is_gym:
        if unit_id in game_state["charge_roll_values"]:
            charge_roll = game_state["charge_roll_values"][unit_id]
        else:
            import random
            charge_roll = random.randint(1, 6) + random.randint(1, 6)
            game_state["charge_roll_values"][unit_id] = charge_roll
        # Take to the skies (21.03) : -2" sur la distance max si le vol est déclaré (borne les cibles éligibles).
        max_distance_subhex = _charge_budget_subhex(game_state, unit_id, charge_roll)

    # Build valid targets : bornées par la distance jetée en roll-first, sinon par charge_max_distance.
    _t_bvt0 = time.perf_counter() if _perf else None
    valid_targets = charge_build_valid_targets(game_state, unit_id, max_distance=max_distance_subhex)
    _t_bvt1 = time.perf_counter() if _perf else None
    if _perf and _t_el0 is not None and _t_bvt0 is not None and _t_bvt1 is not None:
        append_perf_timing_line(
            f"CHARGE_EXEC_LOOP episode={_ep} turn={_turn} unit_id={unit_id} "
            f"build_targets_s={_t_bvt1 - _t_bvt0:.6f} n_targets={len(valid_targets)}"
        )

    # Check if valid targets exist
    if not valid_targets:
        if charge_roll is not None:
            # V11 RAW (roll-first) : l'unité a DÉCLARÉ une charge en s'activant et le jet
            # n'atteint aucune cible → charge ÉCHOUÉE, unité consommée (pas un simple wait
            # qui la laisserait re-jeter). Badge d'échec côté UI (chemin charge_failed).
            if "current_turn" not in game_state:
                current_turn = 1
            else:
                current_turn = game_state["current_turn"]
            append_action_log(
                game_state,
                {
                    "type": "charge_fail",
                    "message": f"Unit {unit['id']} FAILED charge (Roll: {charge_roll} too short to reach any target)",
                    "turn": current_turn,
                    "phase": "charge",
                    "unitId": unit["id"],
                    "player": unit["player"],
                    "charge_roll": charge_roll,
                    "charge_failed": True,
                    "timestamp": "server_time",
                },
            )
            if unit_id in game_state["charge_roll_values"]:
                del game_state["charge_roll_values"][unit_id]
            charge_clear_preview(game_state)
            current_pos = require_unit_position(unit, game_state)
            result = end_activation(game_state, unit, PASS, 1, PASS, CHARGE, 0)
            result.update({
                "action": "charge_fail",
                "unitId": unit["id"],
                "charge_roll": charge_roll,
                "charge_failed": True,
                "charge_failed_reason": "roll_too_short",
                "start_pos": current_pos,
                "end_pos": current_pos,
                "activation_complete": True,
            })
            if not game_state["charge_activation_pool"]:
                result.update(charge_phase_end(game_state))
            return True, result
        # Gym (jet-après) : aucune cible atteignable = pass neutre (comportement inchangé).
        return _handle_skip_action(game_state, unit, had_valid_destinations=False)

    # Extract target IDs for blinking effect (PvP and PvE modes only)
    target_ids = [str(target["id"]) for target in valid_targets]
    
    # Check if PvP or PvE mode (not gym training)
    is_pve = game_state.get("pve_mode", False) or game_state.get("is_pve_mode", False)
    is_gym = game_state.get("gym_training_mode", False)
    should_blink = not is_gym  # Blink in PvP and PvE, not in gym training
    
    result = {
        "unit_activated": True,
        "unitId": unit_id,
        "charge_roll": charge_roll,  # V11 RAW : jet fait à l'activation (None en gym)
        "valid_targets": valid_targets,  # List of target dicts
        "waiting_for_player": True
    }
    if "debug_mode" in game_state and game_state["debug_mode"]:
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        add_debug_file_log(
            game_state,
            f"[CHARGE TRACE] E{episode} T{turn} charge_unit_execution_loop unit_id={unit_id} "
            f"valid_targets={len(valid_targets)} waiting_for_player=True"
        )
    
    # Add blinking effect for PvP and PvE modes
    if should_blink:
        result["blinking_units"] = target_ids
        result["start_blinking"] = True
    
    return True, result


def _attempt_charge_to_destination(game_state: Dict[str, Any], unit: Dict[str, Any], dest_col: int, dest_row: int, target_ids: List[str], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md charge execution with destination validation.

    Implements AI_TURN.md charge restrictions:
    - Must end adjacent to target enemy
    - Within charge_range (2d6 roll result)
    - Path must be reachable via BFS pathfinding
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled
    _perf = perf_timing_enabled(game_state)
    _ep = game_state.get("episode_number", "?")
    _turn = game_state.get("turn", "?")
    _t_atd0 = time.perf_counter() if _perf else None

    # CRITICAL: Check units_fled just before execution (may have changed during phase)
    # CRITICAL: Normalize unit ID to string for consistent comparison (units_fled stores strings)
    unit_id_str = str(unit["id"])
    if unit_id_str in require_key(game_state, "units_fled") and not _unit_has_rule(unit, "charge_after_flee"):
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        log_msg = f"[CHARGE ERROR] E{episode} T{turn} Unit {unit['id']} attempted to charge but has fled - REJECTED"
        add_console_log(game_state, log_msg)
        safe_print(game_state, log_msg)
        return False, {"error": "unit_has_fled", "unitId": unit["id"], "action": "charge"}

    # Post-shoot movement restriction: cannot charge until end of turn.
    if unit_id_str in require_key(game_state, "units_cannot_charge"):
        return False, {
            "error": "unit_cannot_charge_after_move_after_shooting",
            "unitId": unit["id"],
            "action": "charge",
        }

    # NOTE: Pool is already built in charge_destination_selection_handler() after roll.
    # Since system is sequential, no need to rebuild here. Only verify destination is in pool.
    unit_id = unit["id"]
    if unit_id not in game_state["charge_roll_values"]:
        raise KeyError(f"Unit {unit_id} missing charge_roll_values")
    charge_roll = game_state["charge_roll_values"][unit_id]

    # Check if destination is in the pool (built after roll in charge_destination_selection_handler)
    dest_tuple = (int(dest_col), int(dest_row))
    pool = require_key(game_state, "valid_charge_destinations_pool")
    if dest_tuple not in pool:
        return False, {"error": "destination_not_in_pool", "target": (dest_col, dest_row), "action": "charge"}

    # Validate destination per AI_TURN.md charge rules
    _t_valid0 = time.perf_counter() if _perf else None
    if not _is_valid_charge_destination(game_state, dest_col, dest_row, unit, target_ids, charge_roll, config):
        return False, {"error": "invalid_charge_destination", "target": (dest_col, dest_row), "action": "charge"}
    _t_valid1 = time.perf_counter() if _perf else None

    # Store original position
    orig_col, orig_row = require_unit_position(unit, game_state)

    # CRITICAL: Final occupation check IMMEDIATELY before position assignment
    # This prevents race conditions where multiple units select the same destination
    # before any of them have moved. Must check JUST before assignment, not earlier.
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    phase = game_state.get("phase", "charge")
    # CRITICAL: Normalize destination coordinates to int for consistent comparison
    dest_col_int, dest_row_int = normalize_coordinates(dest_col, dest_row)

    unit_id_str = str(unit["id"])
    _fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
    candidate_fp = _candidate_footprint_charge(dest_col_int, dest_row_int, unit, game_state, _fp_pair)
    _t_occ0 = time.perf_counter() if _perf else None
    _placement_ok = is_placement_valid_with_clearance(
        game_state, candidate_fp,
        shape=unit["BASE_SHAPE"], base_size=unit["BASE_SIZE"],
        col=dest_col_int, row=dest_row_int, exclude_unit_id=unit_id_str,
    )
    _t_occ1 = time.perf_counter() if _perf else None
    if not _placement_ok:
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        log_msg = f"[CHARGE COLLISION PREVENTED] E{episode} T{turn} {phase}: Unit {unit['id']} cannot charge to ({dest_col_int},{dest_row_int}) - footprint blocked"
        add_console_log(game_state, log_msg)
        safe_print(game_state, log_msg)
        return False, {
            "error": "charge_destination_occupied",
            "destination": (dest_col_int, dest_row_int)
        }

    # Execute charge - position assignment happens immediately after occupation check
    # CRITICAL: Log ALL position changes to detect unauthorized modifications
    # ALWAYS log, even if episode_number/turn/phase are missing (for debugging)
    log_message = f"[POSITION CHANGE] E{episode} T{turn} {phase} Unit {unit['id']}: ({orig_col},{orig_row})→({dest_col_int},{dest_row_int}) via CHARGE"
    add_console_log(game_state, log_message)
    safe_print(game_state, log_message)

    # CRITICAL: Normalize coordinates before assignment
    from engine.combat_utils import set_unit_coordinates
    set_unit_coordinates(unit, dest_col_int, dest_row_int)
    from engine.game_utils import conditional_debug_print
    conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: Setting col={dest_col_int} row={dest_row_int}")
    conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: col set to {unit['col']}")
    conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: row set to {unit['row']}")

    # Capture old footprint before cache update (for multi-hex adjacency delta)
    chg_uid_str = str(unit["id"])
    chg_old_entry = require_key(game_state, "units_cache").get(chg_uid_str)
    chg_old_occupied = chg_old_entry.get("occupied_hexes") if chg_old_entry else None

    # Update units_cache after position change.
    # Déplacement RIGIDE du squad (ancre + toutes les figs translatées + occupied_hexes_by_model
    # resync) — même sémantique que la phase move. update_units_cache_position seul ne bougeait que
    # l'ancre, laissant les figs multi-fig affichées à l'ancienne position (charge « sans effet visuel »).
    _t_upd0 = time.perf_counter() if _perf else None
    translate_squad_to_destination(game_state, chg_uid_str, dest_col_int, dest_row_int)
    _t_upd1 = time.perf_counter() if _perf else None

    chg_new_entry = require_key(game_state, "units_cache").get(chg_uid_str)
    chg_new_occupied = chg_new_entry.get("occupied_hexes") if chg_new_entry else None

    moved_unit_player = int(require_key(unit, "player"))
    _t_adj0 = time.perf_counter() if _perf else None
    update_enemy_adjacent_caches_after_unit_move(
        game_state,
        moved_unit_player=moved_unit_player,
        old_col=orig_col,
        old_row=orig_row,
        new_col=dest_col_int,
        new_row=dest_row_int,
        old_occupied=chg_old_occupied,
        new_occupied=chg_new_occupied,
    )
    _t_adj1 = time.perf_counter() if _perf else None

    # AI_TURN_SHOOTING_UPDATE.md: No need to invalidate los_cache here
    # The new architecture uses unit["los_cache"] which is built at unit activation in shooting phase
    # When a unit charges, los_cache doesn't exist yet (built at shooting activation)
    # Old code: _invalidate_los_cache_for_moved_unit(game_state, unit["id"]) - OBSOLETE

    # Mark as units_charged (NOT units_moved)
    game_state["units_charged"].add(unit["id"])

    # CRITICAL: Invalidate all destination pools after charge movement
    # Positions have changed, so all pools (move, charge, shoot) are now stale
    from .movement_handlers import _invalidate_all_destination_pools_after_movement
    _t_inv0 = time.perf_counter() if _perf else None
    _invalidate_all_destination_pools_after_movement(game_state)
    _t_inv1 = time.perf_counter() if _perf else None
    game_state["_unit_move_version"] += 1

    if _perf and _t_atd0 is not None and _t_valid0 is not None and _t_valid1 is not None and _t_occ0 is not None and _t_occ1 is not None and _t_upd0 is not None and _t_upd1 is not None and _t_adj0 is not None and _t_adj1 is not None and _t_inv0 is not None and _t_inv1 is not None:
        append_perf_timing_line(
            f"CHARGE_ATTEMPT_DEST episode={_ep} turn={_turn} unit_id={unit_id} "
            f"valid_dest_s={_t_valid1 - _t_valid0:.6f} "
            f"build_occ_s={_t_occ1 - _t_occ0:.6f} "
            f"update_cache_pos_s={_t_upd1 - _t_upd0:.6f} "
            f"update_adj_cache_s={_t_adj1 - _t_adj0:.6f} "
            f"invalidate_pools_s={_t_inv1 - _t_inv0:.6f} "
            f"total_s={_t_inv1 - _t_atd0:.6f}"
        )

    # Clear charge roll, target selection, and pending targets after use
    if "charge_roll_values" in game_state and unit_id in game_state["charge_roll_values"]:
        del game_state["charge_roll_values"][unit_id]
    if "charge_target_selections" in game_state and unit_id in game_state["charge_target_selections"]:
        del game_state["charge_target_selections"][unit_id]
    if "pending_charge_targets" in game_state:
        del game_state["pending_charge_targets"]
    if "pending_charge_unit_id" in game_state:
        del game_state["pending_charge_unit_id"]

    return True, {
        "action": "charge",
        "unitId": unit["id"],
        "targetId": target_ids[0],
        "targetIds": target_ids,
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col,
        "toRow": dest_row,
        "charge_roll": charge_roll
    }


def _is_valid_charge_destination(game_state: Dict[str, Any], col: int, row: int, unit: Dict[str, Any],
                                 target_ids: List[str], charge_roll: int, config: Dict[str, Any]) -> bool:
    """
    AI_TURN.md charge destination validation.

    Charge destination requirements:
    - Within board bounds
    - NOT a wall
    - NOT occupied by another unit
    - Adjacent to target enemy (distance <= melee_range from target) - GUARANTEED by pool
    - Reachable within charge_range (2d6 roll) via BFS pathfinding - GUARANTEED by pool

    NOTE: Pool already guarantees adjacency and reachability. This function only does defensive checks.
    """
    # CRITICAL: Convert coordinates to int for consistent comparison
    col_int, row_int = int(col), int(row)
    
    # Board bounds check
    if (col_int < 0 or row_int < 0 or
        col_int >= game_state["board_cols"] or
        row_int >= game_state["board_rows"]):
        return False

    # Wall collision check
    if (col_int, row_int) in game_state["wall_hexes"]:
        return False

    unit_id_str = str(unit["id"])
    occupied_positions = build_occupied_positions_set(game_state, exclude_unit_id=unit_id_str)
    _fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
    candidate_fp = _candidate_footprint_charge(col_int, row_int, unit, game_state, _fp_pair)
    if not is_footprint_placement_valid(candidate_fp, game_state, occupied_positions):
        return False

    # CRITICAL: Verify destination is in the valid pool
    # The pool guarantees: adjacent to enemy, not occupied, reachable with charge_roll
    if "valid_charge_destinations_pool" not in game_state:
        return False  # Pool not built - invalid destination
    
    valid_pool = game_state["valid_charge_destinations_pool"]
    if (col_int, row_int) not in valid_pool:
        return False  # Destination not in valid pool - not reachable with this charge_roll or not adjacent to enemy
    
    return True


def _has_valid_charge_target(game_state: Dict[str, Any], unit: Dict[str, Any],
                            full_occupied_positions: Optional[Set[Tuple[int, int]]] = None) -> bool:
    """
    Check if unit has at least one valid charge target.

    AI_TURN.md Line 495: "Enemies exist within charge_max_distance hexes?"
    AI_TURN.md Line 562: "Enemy units within charge_max_distance hexes (via pathfinding)"

    CRITICAL: Must use BFS pathfinding distance, not straight-line distance.
    Build reachable hexes within max charge distance and check if any enemy
    is adjacent to those hexes.
    
    NOTE: Target can be at distance 13 because charge of 12 can reach adjacent to target at 13.
    
    Args:
        full_occupied_positions: Optional pre-computed set of all unit positions (from get_eligible_units).
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    _perf = perf_timing_enabled(game_state)
    _ep = game_state.get("episode_number", "?")
    _turn = game_state.get("turn", "?")
    _uid = str(unit["id"])
    _t_hvt0 = time.perf_counter() if _perf else None

    # Cache: skip BFS if positions haven't changed since last call
    _hvt_cache = game_state.setdefault("_has_valid_charge_cache", {})
    _move_version = game_state["_unit_move_version"]
    _hvt_key = (_uid, _move_version)
    if _hvt_key in _hvt_cache:
        return _hvt_cache[_hvt_key]

    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    CHARGE_MAX_DISTANCE = require_key(require_key(game_state["config"], "charge"), "charge_max_distance")

    # Fast precheck: skip BFS if all enemies are beyond max reachable distance.
    # La distance de charge se mesure **bord à bord** (fig la plus proche → fig ennemie la plus proche),
    # PAS centre à centre : un gros socle (ex. Dreadnought) a son centre loin alors que son bord est à
    # portée. On borne donc par ``hex_distance(centres) - rayon_chargeur - rayon_ennemi`` via les rayons
    # d'empreinte (distance max ancre → case d'empreinte). Borne conservatrice : surestime le rayon côté
    # opposé, donc n'élargit le seuil que dans le bon sens → jamais de faux rejet.
    units_cache = require_key(game_state, "units_cache")
    _charger_entry = require_key(units_cache, str(unit["id"]))
    unit_col, unit_row = int(require_key(_charger_entry, "col")), int(require_key(_charger_entry, "row"))
    unit_player = int(unit["player"])
    _charger_occ = _charger_entry.get("occupied_hexes") or {(unit_col, unit_row)}
    _charger_radius = max(
        _hex_distance(unit_col, unit_row, int(_c), int(_r)) for _c, _r in _charger_occ
    )

    def _enemy_radius(_e: Dict[str, Any], _ec: int, _er: int) -> int:
        _occ = _e.get("occupied_hexes") or {(_ec, _er)}
        return max(_hex_distance(_ec, _er, int(_c), int(_r)) for _c, _r in _occ)

    _any_enemy_in_range = any(
        _hex_distance(unit_col, unit_row, _ec, _er)
        <= CHARGE_MAX_DISTANCE + 1 + _charger_radius + _enemy_radius(e, _ec, _er)
        for e in units_cache.values()
        if int(e["player"]) != unit_player
        for _ec, _er in (((int(e["col"]), int(e["row"])),))
    )
    if not _any_enemy_in_range:
        _hvt_cache[_hvt_key] = False
        return False

    try:
        # BFS with early exit: any hex in charge_build_valid_destinations_pool already satisfies
        # engagement + placement rules (same as the old nested loop).
        valid_any = charge_build_valid_destinations_pool(
            game_state, unit["id"], CHARGE_MAX_DISTANCE,
            full_occupied_positions=full_occupied_positions,
            early_exit_if_valid=True,
        )
    except Exception as e:
        import traceback
        _write_diagnostic_to_debug_log(f"[HVT BFS EXCEPTION] unit={_uid} error={e!r}\n{traceback.format_exc()}")
        add_console_log(game_state, f"ERROR: BFS failed for unit {unit['id']}: {str(e)}")
        if _perf and _t_hvt0 is not None:
            append_perf_timing_line(
                f"CHARGE_HAS_VALID_TARGET episode={_ep} turn={_turn} unit_id={_uid} "
                f"bfs_pool_s={time.perf_counter() - _t_hvt0:.6f} nested_loop_s=0.000000 "
                f"reachable_n=0 enemy_n=0 outcome=bfs_error"
            )
        return False

    _t_after_bfs_pool = time.perf_counter() if _perf else None

    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    enemy_n = sum(
        1 for _, enemy_entry in units_cache.items()
        if int(enemy_entry["player"]) != unit_player
    )

    outcome = "hit" if valid_any else "miss"
    if _perf and _t_hvt0 is not None and _t_after_bfs_pool is not None:
        append_perf_timing_line(
            f"CHARGE_HAS_VALID_TARGET episode={_ep} turn={_turn} unit_id={_uid} "
            f"bfs_pool_s={_t_after_bfs_pool - _t_hvt0:.6f} nested_loop_s=0.000000 "
            f"reachable_n={len(valid_any)} enemy_n={enemy_n} outcome={outcome}"
        )

    result = bool(valid_any)
    _hvt_cache[_hvt_key] = result
    return result


def _charge_unit_within_engagement_zone(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    True si l'unité est dans la **zone d'engagement** (≥1 ennemi), au sens ``spatial_relations`` :
    ``unit_within_engagement_zone_footprints`` — **pas** l'adjacence hex discrète (voir
    ``_is_hex_adjacent_to_enemy`` pour le voisinage à 6 côtés).

    Aligné sur la phase move (bord à bord / empreintes). Utilisé pour l'éligibilité charge
    et la revalidation au choix de cible.
    """
    from engine.spatial_relations import get_engagement_zone
    from engine.spatial_relations import unit_within_engagement_zone_footprints

    cc_range = get_engagement_zone(game_state)
    return unit_within_engagement_zone_footprints(
        game_state, unit, engagement_zone=cc_range, max_distance=cc_range
    )


def _is_hex_adjacent_to_enemy(game_state: Dict[str, Any], col: int, row: int, player: int,
                               enemy_adjacent_hexes: Optional[Set[Tuple[int, int]]] = None) -> bool:
    """
    AI_TURN.md adjacency restriction implementation.

    Check if hex position is adjacent to any enemy unit.

    CRITICAL FIX: Use proper hexagonal adjacency, not Chebyshev distance.
    Hexagonal grids require checking if enemy position is in the list of 6 neighbors.

    PERFORMANCE: If enemy_adjacent_hexes set is provided, uses O(1) set lookup
    instead of O(n) iteration through all units.
    """
    # PERFORMANCE: Use pre-computed set if available (5-10x speedup)
    if enemy_adjacent_hexes is not None:
        return (col, row) in enemy_adjacent_hexes

    # Calcul dynamique si aucun cache n'est fourni (comportement historique)
    hex_neighbors = set(get_hex_neighbors(col, row))

    units_cache = require_key(game_state, "units_cache")
    for enemy_id, enemy_entry in units_cache.items():
        if enemy_entry["player"] != player:
            enemy_pos = (enemy_entry["col"], enemy_entry["row"])
            # Check if enemy is in our 6 neighbors (true hex adjacency)
            if enemy_pos in hex_neighbors:
                return True
    return False


def _find_adjacent_enemy_at_destination(game_state: Dict[str, Any], col: int, row: int, player: int) -> Optional[str]:
    """
    Find an enemy unit adjacent to the given hex position.

    Used by gym training to auto-select charge target based on destination.
    Returns the ID of the first adjacent enemy, or None if no adjacent enemy.
    
    CRITICAL FIX: Also checks if enemy is ON the destination (distance == 0) and
    verifies that the destination is not occupied before returning target_id.
    """
    # First check if destination itself is occupied by an enemy (distance == 0)
    units_cache = require_key(game_state, "units_cache")
    for enemy_id, enemy_entry in units_cache.items():
        if enemy_entry["player"] != player:
            enemy_pos = (enemy_entry["col"], enemy_entry["row"])
            if enemy_pos == (col, row):
                # Enemy is ON the destination - this is invalid for charge
                return None
    
    # Then check neighbors (adjacent enemies, distance == 1)
    hex_neighbors = set(get_hex_neighbors(col, row))
    adjacent_enemies = []
    for enemy_id, enemy_entry in units_cache.items():
        if enemy_entry["player"] != player:
            enemy_pos = (enemy_entry["col"], enemy_entry["row"])
            if enemy_pos in hex_neighbors:
                adjacent_enemies.append(enemy_id)
    
    if adjacent_enemies:
        result_id = adjacent_enemies[0]
        return result_id
    else:
        return None


def charge_build_valid_destinations_pool(game_state: Dict[str, Any], unit_id: str, charge_roll: int,
                                        target_id: Optional[str] = None,
                                        full_occupied_positions: Optional[Set[Tuple[int, int]]] = None,
                                        early_exit_if_valid: bool = False,
                                        target_ids: Optional[List[str]] = None) -> List[Tuple[int, int]]:
    """
    Build valid charge destinations using BFS pathfinding.

    CRITICAL: Charge destinations must:
    - Be reachable within charge_roll distance (2d6) via BFS
    - Use a **legal footprint** at the end hex (``is_footprint_placement_valid``).
    - Finir en **zone d'engagement** vs la cible déclarée (si ``target_id``) ou vs **un** ennemi :
      pas de chevauchement d'empreinte ennemie, et ``unit_entries_within_engagement_zone``
      (même contrat que la phase fight / move pour rond↔rond et empreintes) doit être vrai
      avec au moins un ennemi indexé — **pas** seulement ``empreinte ∩ dilate(hex)``, qui pouvait
      accepter une fin de charge sans engagement réel au sens ``spatial_relations``.

    Unlike movement, charges CAN move through hexes adjacent to enemies.

    Args:
        target_id: Optional target unit ID. If provided, only hexes engaging **this** target count.
        full_occupied_positions: Optional pre-computed set of all unit positions. If provided, unit's position
            is excluded internally. Used by get_eligible_units for performance.
        early_exit_if_valid: If True, stop the BFS as soon as one valid charge end hex is found
            (used for eligibility checks only). Does not populate the max-roll BFS cache.
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    _perf = perf_timing_enabled(game_state)
    _ep = game_state.get("episode_number", "?")
    _turn = game_state.get("turn", "?")

    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return []

    # Take to the skies (21.03) : vol actif en charge → traversée murs + figs. En éligibilité
    # (early_exit) l'humain FLY est généreusement traité comme volant ; sinon, seulement si déclaré.
    # L'IA garde la charge sol (pas de régression training).
    _fly = _charge_fly_active(game_state, unit, unit_id, for_eligibility=early_exit_if_valid)

    units_cache = require_key(game_state, "units_cache")

    charge_range = charge_roll  # 2d6 result
    _t_func0 = time.perf_counter() if _perf else None
    # CRITICAL: Normalize coordinates to int for consistent tuple comparison
    start_col, start_row = require_unit_position(unit, game_state)
    start_pos = (start_col, start_row)

    # Cibles : ensemble déclaré (multi, V11) prioritaire, sinon cible unique (legacy), sinon tous.
    # En mode multi, ``enemies`` = TOUS les ennemis (pour détecter l'engagement d'un non-cible),
    # et ``_multi_declared`` sert au filtre final ``eng == declared``.
    _multi_declared: Optional[Set[str]] = None
    if target_ids:
        _multi_declared = set()
        for _t in target_ids:
            _tt = get_unit_by_id(game_state, _t)
            if not _tt or _tt["player"] == unit["player"] or not is_unit_alive(str(_tt["id"]), game_state):
                return []  # Cible déclarée invalide
            _multi_declared.add(str(_tt["id"]))
        unit_player = int(unit["player"]) if unit["player"] is not None else None
        enemies = [enemy_id for enemy_id, cache_entry in units_cache.items()
                   if int(cache_entry["player"]) != unit_player]
        if not enemies:
            return []  # No enemies to charge
    elif target_id:
        target = get_unit_by_id(game_state, target_id)
        if not target or target["player"] == unit["player"] or not is_unit_alive(str(target["id"]), game_state):
            return []  # Invalid target
        enemies = [target]
    else:
        # Get all enemy positions for adjacency checks (used during activation preview)
        unit_player = int(unit["player"]) if unit["player"] is not None else None
        enemies = [enemy_id for enemy_id, cache_entry in units_cache.items()
                   if int(cache_entry["player"]) != unit_player]
        if not enemies:
            return []  # No enemies to charge

    unit_id_str = str(unit["id"])
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    CHARGE_MAX_DISTANCE = require_key(require_key(game_state["config"], "charge"), "charge_max_distance")
    CHARGE_MAX_DISTANCE_SUBHEX = CHARGE_MAX_DISTANCE
    tid_arg: Optional[str] = str(target_id) if target_id is not None else None
    bfs_max_distance = _charge_bfs_max_distance(
        game_state, unit_id_str, int(charge_range), tid_arg,
        target_ids=sorted(_multi_declared) if _multi_declared else None,
    )
    cache = game_state.setdefault("_charge_dest_bfs_cache", {})
    cache_key = (
        unit_id_str,
        int(charge_range),
        target_id if target_id else None,
        bool(_fly),
        _CHARGE_DEST_BFS_CACHE_SCHEMA,
    )
    if (
        not early_exit_if_valid
        and charge_range == CHARGE_MAX_DISTANCE_SUBHEX
        and tid_arg is None
        and _multi_declared is None
        and cache_key in cache
    ):
        cached_list, _ = cache[cache_key]
        game_state["valid_charge_destinations_pool"] = cached_list
        if _perf and _t_func0 is not None:
            _t_done = time.perf_counter()
            append_perf_timing_line(
                f"CHARGE_DEST_BFS episode={_ep} turn={_turn} unit_id={unit_id} charge_roll={charge_range} "
                f"bfs_loop_s=0.000000 total_s={_t_done - _t_func0:.6f} "
                f"visited_n=0 valid_dest_n={len(cached_list)} cache_hit=1 early_exit=0 short_circuit=0"
            )
        return cached_list

    if full_occupied_positions is not None:
        # Remove moving unit's footprint from the pre-computed set
        units_cache_ref = require_key(game_state, "units_cache")
        own_entry = units_cache_ref.get(unit_id_str)
        own_hexes = own_entry.get("occupied_hexes", {start_pos}) if own_entry else {start_pos}
        occupied_positions = full_occupied_positions - own_hexes
    else:
        occupied_positions = build_occupied_positions_set(game_state, exclude_unit_id=unit_id_str)

    # Verbose debug: off unless W40K_CHARGE_DEBUG or game_state["charge_debug_positions"]
    if _charge_debug_positions_enabled(game_state) and "episode_number" in game_state and "turn" in game_state and "phase" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        phase = game_state.get("phase", "charge")
        def _hp_display(uid, gs):
            h = get_hp_from_cache(str(uid), gs)
            return h if h is not None else "dead"
        all_units_info = []
        for u_id, u_entry in units_cache.items():
            u_col, u_row = u_entry["col"], u_entry["row"]
            all_units_info.append(f"Unit {u_id} at ({int(u_col)},{int(u_row)}) HP={_hp_display(u_id, game_state)}")
        log_message = f"[CHARGE DEBUG] E{episode} T{turn} {phase} charge_build_valid_destinations Unit {unit_id}: occupied_positions={occupied_positions} all_units={all_units_info}"
        add_console_log(game_state, log_message)
        safe_print(game_state, log_message)

    fp_offset_pair = _charge_prepare_footprint_offsets(unit, game_state)
    _fp_tag = "offset" if fp_offset_pair is not None else "legacy"

    from engine.spatial_relations import unit_entries_within_engagement_zone
    from .shared_utils import get_engagement_zone

    engagement_zone = int(get_engagement_zone(game_state))

    indexed_enemy_engagement: List[Tuple[Any, Dict[str, Any]]] = []
    for enemy_ref in enemies:
        eid = enemy_ref["id"] if isinstance(enemy_ref, dict) else enemy_ref
        enemy_entry = units_cache.get(str(eid))
        if enemy_entry is None:
            raise KeyError(f"Enemy {eid} not in units_cache (dead or absent)")
        indexed_enemy_engagement.append((eid, enemy_entry))

    # Precompute per-enemy proximity thresholds: if the BFS anchor is beyond this distance
    # from all enemies, neither overlap nor engagement is possible — skip the expensive checks.
    _mover_bs = unit["BASE_SIZE"]
    _mover_r = max(1, (_mover_bs + 1) // 2)
    _charge_enemy_prox: List[Tuple[int, int, int]] = []
    for _, _ce in indexed_enemy_engagement:
        _ec = int(require_key(_ce, "col"))
        _er = int(require_key(_ce, "row"))
        _e_bs = _ce["BASE_SIZE"]
        _e_bs_int = max(_e_bs) if isinstance(_e_bs, (list, tuple)) else int(_e_bs)
        _e_r = max(1, (_e_bs_int + 1) // 2)
        _charge_enemy_prox.append((_ec, _er, engagement_zone + _mover_r + _e_r + 1))

    def _min_dist_to_enemy(start_c: int, start_r: int, ce: Dict[str, Any], pec: int, per: int) -> int:
        occ = ce.get("occupied_hexes") or {(pec, per)}
        return min(_calculate_hex_distance(start_c, start_r, int(mc), int(mr)) for mc, mr in occ)
    if _charge_enemy_prox and all(
        _min_dist_to_enemy(start_col, start_row, ce, pec, per) > bfs_max_distance + peth
        for (_, ce), (pec, per, peth) in zip(indexed_enemy_engagement, _charge_enemy_prox)
    ):
        game_state["valid_charge_destinations_pool"] = []
        if charge_range == CHARGE_MAX_DISTANCE_SUBHEX and not early_exit_if_valid and tid_arg is None:
            cache[cache_key] = ([], {})
        if _perf and _t_func0 is not None:
            _t_done_lb = time.perf_counter()
            append_perf_timing_line(
                f"CHARGE_PROX_LB_PRUNE episode={_ep} turn={_turn} unit_id={unit_id} "
                f"bfs_max={bfs_max_distance} charge_roll={charge_range}"
            )
            append_perf_timing_line(
                f"CHARGE_DEST_BFS episode={_ep} turn={_turn} unit_id={unit_id} charge_roll={charge_range} "
                f"bfs_max={bfs_max_distance} "
                f"bfs_loop_s=0.000000 total_s={_t_done_lb - _t_func0:.6f} "
                f"visited_n=0 valid_dest_n=0 cache_hit=0 "
                f"early_exit={1 if early_exit_if_valid else 0} short_circuit=0 fp={_fp_tag}"
            )
        return []

    if (
        not _fly
        and not _charge_skip_hex_lb_prune_round_round_engagement(unit, indexed_enemy_engagement)
        and _charge_impossible_by_primary_to_enemy_hex_lower_bound(
            game_state,
            unit_id_str=unit_id_str,
            start_col=start_col,
            start_row=start_row,
            indexed_enemy_engagement=indexed_enemy_engagement,
            bfs_max_distance=bfs_max_distance,
        )
    ):
        game_state["valid_charge_destinations_pool"] = []
        if charge_range == CHARGE_MAX_DISTANCE_SUBHEX and not early_exit_if_valid and tid_arg is None:
            cache[cache_key] = ([], {})
        if _perf and _t_func0 is not None:
            _t_done_lb = time.perf_counter()
            append_perf_timing_line(
                f"CHARGE_HEX_LB_PRUNE episode={_ep} turn={_turn} unit_id={unit_id} "
                f"bfs_max={bfs_max_distance} charge_roll={charge_range}"
            )
            append_perf_timing_line(
                f"CHARGE_DEST_BFS episode={_ep} turn={_turn} unit_id={unit_id} charge_roll={charge_range} "
                f"bfs_max={bfs_max_distance} "
                f"bfs_loop_s=0.000000 total_s={_t_done_lb - _t_func0:.6f} "
                f"visited_n=0 valid_dest_n=0 cache_hit=0 "
                f"early_exit={1 if early_exit_if_valid else 0} short_circuit=0 fp={_fp_tag}"
            )
        return []

    # NOTE: _charge_reverse_goal_bfs_for_eligibility is disabled for scaled boards (inches_to_subhex > 1)
    # because its intermediate footprint checks are too restrictive for large footprints — the forward BFS
    # single-hex traversal is correct and supports early_exit_if_valid natively.
    if not _fly and early_exit_if_valid and tid_arg is None and int(game_state.get("inches_to_subhex", 1)) <= 1:
        reverse_result = _charge_reverse_goal_bfs_for_eligibility(
            game_state,
            unit,
            unit_id_str=unit_id_str,
            start_pos=start_pos,
            indexed_enemy_engagement=indexed_enemy_engagement,
            occupied_positions=occupied_positions,
            bfs_max_distance=bfs_max_distance,
            fp_offset_pair=fp_offset_pair,
        )
        game_state["valid_charge_destinations_pool"] = reverse_result
        return reverse_result

    # BFS pathfinding to find all reachable anchor positions within bfs_max_distance (jet + offset ×10)
    visited = {start_pos: 0}
    queue = deque([(start_pos, 0)])
    valid_destinations = []
    # Track (distance, engaging_enemy_ids) per valid destination for target-selection fast path.
    # Only built when the result will be stored in cache (activation BFS, no specific target).
    _track_engages = ((tid_arg is None and charge_range == CHARGE_MAX_DISTANCE_SUBHEX and not early_exit_if_valid)
                      or _multi_declared is not None)
    pos_dist_engage: Dict[Tuple[int, int], Tuple[int, FrozenSet[str]]] = {} if _track_engages else {}

    # Precompute for O(1) bounds check before footprint computation
    _bfs_board_cols = int(require_key(game_state, "board_cols"))
    _bfs_board_rows = int(require_key(game_state, "board_rows"))
    _bfs_wall_hexes: Set[Tuple[int, int]] = game_state.get("wall_hexes", set())

    # Take to the skies (21.03) : la charge FLY traverse murs + figs → reachability = disque cube de
    # rayon ``bfs_max_distance`` (traversée libre, comme la phase move). Seuls le placement final
    # (empreinte dans le plateau, aucun overlap murs/figurines) et l'engagement classent les
    # destinations valides. Court-circuite le step-BFS sol et ses prunes (déjà sautées plus haut).
    if _fly:
        valid_destinations = []
        _R = int(bfs_max_distance)
        _sx = start_col
        _sz = start_row - ((start_col - (start_col & 1)) >> 1)
        _fly_short = False
        for _dx in range(-_R, _R + 1):
            if _fly_short:
                break
            _dy_lo = max(-_R, -_R - _dx)
            _dy_hi = min(_R, _R - _dx) + 1
            for _dy in range(_dy_lo, _dy_hi):
                nc = _sx + _dx
                nr = (_sz - _dx - _dy) + ((nc - (nc & 1)) >> 1)
                if nc < 0 or nr < 0 or nc >= _bfs_board_cols or nr >= _bfs_board_rows:
                    continue
                neighbor_pos = (nc, nr)
                if neighbor_pos == start_pos:
                    continue
                candidate_fp = _candidate_footprint_charge(nc, nr, unit, game_state, fp_offset_pair)
                if any(not (0 <= x < _bfs_board_cols and 0 <= y < _bfs_board_rows) for (x, y) in candidate_fp):
                    continue
                if (_bfs_wall_hexes and (candidate_fp & _bfs_wall_hexes)) or (
                    occupied_positions and (candidate_fp & occupied_positions)
                ):
                    continue
                synth = _charge_synthetic_charger_cache_entry(
                    game_state, unit, nc, nr, candidate_fp
                )
                is_adjacent_to_enemy = False
                hex_overlaps_enemy = False
                _cur_engaging: Optional[Set[str]] = set() if _track_engages else None
                for _eid, enemy_entry in indexed_enemy_engagement:
                    ec, er = int(enemy_entry["col"]), int(enemy_entry["row"])
                    enemy_fp = enemy_entry.get("occupied_hexes", {(ec, er)})
                    if candidate_fp & enemy_fp:
                        hex_overlaps_enemy = True
                        break
                    if unit_entries_within_engagement_zone(synth, enemy_entry, engagement_zone):
                        is_adjacent_to_enemy = True
                        if _cur_engaging is not None:
                            _cur_engaging.add(str(_eid))
                        if tid_arg:
                            break
                if is_adjacent_to_enemy and not hex_overlaps_enemy:
                    valid_destinations.append(neighbor_pos)
                    if _track_engages and _cur_engaging is not None:
                        pos_dist_engage[neighbor_pos] = (
                            _hex_distance(start_col, start_row, nc, nr), frozenset(_cur_engaging)
                        )
                    if early_exit_if_valid:
                        _fly_short = True
                        break
        if _multi_declared is not None:
            valid_destinations = [
                p for p in valid_destinations
                if pos_dist_engage.get(p, (0, frozenset()))[1] == _multi_declared
            ]
        game_state["valid_charge_destinations_pool"] = valid_destinations
        # Distance de mouvement par ancre (sous-hex) : ici disque vol → distance directe (le vol
        # traverse), cohérente avec l'affichage. Source unique pour le tooltip de charge.
        game_state["valid_charge_dest_distances"] = {
            p: pos_dist_engage[p][0] for p in valid_destinations if p in pos_dist_engage
        }
        if charge_range == CHARGE_MAX_DISTANCE_SUBHEX and not early_exit_if_valid and tid_arg is None and _multi_declared is None:
            cache[cache_key] = (list(valid_destinations), pos_dist_engage)
        return valid_destinations
    # Bounding box of footprint offsets for fast OOB detection (even/odd column variants)
    _fp_bbox_e: Optional[Tuple[int, int, int, int]] = None
    _fp_bbox_o: Optional[Tuple[int, int, int, int]] = None
    if fp_offset_pair is not None:
        off_e, off_o = fp_offset_pair
        if off_e:
            _fp_bbox_e = (
                min(dc for dc, dr in off_e), max(dc for dc, dr in off_e),
                min(dr for dc, dr in off_e), max(dr for dc, dr in off_e),
            )
        if off_o:
            _fp_bbox_o = (
                min(dc for dc, dr in off_o), max(dc for dc, dr in off_o),
                min(dr for dc, dr in off_o), max(dr for dc, dr in off_o),
            )

    # Precompute set of all hexes within proximity threshold of any enemy → O(1) lookup in BFS loop.
    # Use ALL occupied hexes (not just anchor) so multi-model squads are fully covered.
    from engine.hex_utils import dilate_hex_set_unbounded as _dilate_unbounded
    _near_enemy_set: Set[Tuple[int, int]] = set()
    for (_ene_id_prox, _ce_prox), (_pec, _per, _peth) in zip(indexed_enemy_engagement, _charge_enemy_prox):
        _ce_occ_all: Set[Tuple[int, int]] = _ce_prox.get("occupied_hexes") or {(_pec, _per)}
        _near_enemy_set.update(_dilate_unbounded({(int(c), int(r)) for c, r in _ce_occ_all}, _peth))

    # Opt 3 — neighbor offsets inlinés : évite get_hex_neighbors (normalize_coordinates + int() redondants).
    _BFS_OFF_EVEN = ((0, -1), (1, -1), (1, 0), (0, 1), (-1, 0), (-1, -1))
    _BFS_OFF_ODD  = ((0, -1), (1, 0),  (1, 1), (0, 1), (-1, 1), (-1, 0))

    # Opt 1 — prefiltre per-enemy : évite unit_entries_within_engagement_zone sur les hexes
    # clairement hors portée d'un ennemi spécifique. Use all occupied hexes (not just anchor)
    # so multi-model squads are fully covered (far-side models not missed).
    _bfs_is_mover_round = (unit["BASE_SHAPE"] == "round")
    _bfs_enemy_eng_zones: Dict[Any, Set[Tuple[int, int]]] = {}
    _bfs_rr_near_set: Dict[Any, Set[Tuple[int, int]]] = {}  # replaces _bfs_rr_prox for round-round
    for (_bfs_eid, _bfs_ee), (_bfs_pec, _bfs_per, _bfs_peth) in zip(indexed_enemy_engagement, _charge_enemy_prox):
        _bfs_ee_occ_all = _bfs_ee.get("occupied_hexes") or {(int(_bfs_pec), int(_bfs_per))}
        if _bfs_is_mover_round and _bfs_ee.get("BASE_SHAPE") == "round":
            # Round-round: proximity set from all model positions (not just anchor)
            _bfs_rr_near_set[_bfs_eid] = _dilate_unbounded(
                {(int(c), int(r)) for c, r in _bfs_ee_occ_all}, _bfs_peth
            )
        else:
            _bfs_enemy_eng_zones[_bfs_eid] = _dilate_unbounded(
                {(int(fc), int(fr)) for fc, fr in _bfs_ee_occ_all}, engagement_zone
            )

    _t_bfs0 = time.perf_counter() if _perf else None
    bfs_short_circuit = False
    bfs_candidate_fp_s = 0.0
    bfs_placement_s = 0.0
    bfs_engagement_s = 0.0
    bfs_rejected_placement_n = 0
    bfs_overlap_n = 0
    bfs_no_engagement_n = 0
    bfs_engagement_checks_n = 0
    while queue and not bfs_short_circuit:
        current_pos, current_dist = queue.popleft()
        current_col, current_row = current_pos

        if current_dist >= bfs_max_distance:
            continue

        for _dc, _dr in (_BFS_OFF_ODD if (current_col & 1) else _BFS_OFF_EVEN):
            neighbor_col_int = current_col + _dc
            neighbor_row_int = current_row + _dr
            neighbor_pos = (neighbor_col_int, neighbor_row_int)
            neighbor_dist = current_dist + 1

            if neighbor_pos in visited:
                continue

            # Proximity pre-filter first (O(1) set lookup): determines whether full footprint check is needed.
            _near_enemy = neighbor_pos in _near_enemy_set

            if not _near_enemy:
                # Traversal only: single-hex bounds+wall+occupied check, no footprint computation.
                if (neighbor_col_int < 0 or neighbor_col_int >= _bfs_board_cols or
                        neighbor_row_int < 0 or neighbor_row_int >= _bfs_board_rows or
                        (_bfs_wall_hexes and neighbor_pos in _bfs_wall_hexes) or
                        (occupied_positions and neighbor_pos in occupied_positions)):
                    visited[neighbor_pos] = neighbor_dist
                    bfs_rejected_placement_n += 1
                    continue
                visited[neighbor_pos] = neighbor_dist
                bfs_no_engagement_n += 1
                queue.append((neighbor_pos, neighbor_dist))
                continue

            # Near enemy: full footprint + placement + engagement check.
            # O(1) bounding-box check: skip footprint computation when anchor makes OOB certain
            _bbox = _fp_bbox_e if (neighbor_col_int & 1) == 0 else _fp_bbox_o
            if _bbox is not None:
                _min_dc, _max_dc, _min_dr, _max_dr = _bbox
                if (neighbor_col_int + _min_dc < 0 or
                        neighbor_col_int + _max_dc >= _bfs_board_cols or
                        neighbor_row_int + _min_dr < 0 or
                        neighbor_row_int + _max_dr >= _bfs_board_rows):
                    visited[neighbor_pos] = neighbor_dist
                    bfs_rejected_placement_n += 1
                    continue

            _t_candidate_fp0 = time.perf_counter() if _perf else None
            candidate_fp = _candidate_footprint_charge(
                neighbor_col_int, neighbor_row_int, unit, game_state, fp_offset_pair
            )
            if _perf and _t_candidate_fp0 is not None:
                bfs_candidate_fp_s += time.perf_counter() - _t_candidate_fp0

            _t_placement0 = time.perf_counter() if _perf else None
            if _bbox is not None:
                # Bbox pre-check already confirmed in-bounds: only check walls + occupied (C-level set ops)
                _placement_ok = not (
                    (_bfs_wall_hexes and (candidate_fp & _bfs_wall_hexes)) or
                    (occupied_positions and (candidate_fp & occupied_positions))
                )
            else:
                _placement_ok = is_footprint_placement_valid(candidate_fp, game_state, occupied_positions)
            if not _placement_ok:
                if _perf and _t_placement0 is not None:
                    bfs_placement_s += time.perf_counter() - _t_placement0
                bfs_rejected_placement_n += 1
                visited[neighbor_pos] = neighbor_dist  # prevent re-processing from other neighbors
                continue
            if _perf and _t_placement0 is not None:
                bfs_placement_s += time.perf_counter() - _t_placement0

            visited[neighbor_pos] = neighbor_dist

            is_adjacent_to_enemy = False
            hex_overlaps_enemy = False
            _cur_engaging: Optional[Set[str]] = set() if _track_engages else None
            _t_engagement0 = time.perf_counter() if _perf else None
            synth = _charge_synthetic_charger_cache_entry(
                game_state, unit, neighbor_col_int, neighbor_row_int, candidate_fp
            )
            for _eid, enemy_entry in indexed_enemy_engagement:
                ec, er = int(enemy_entry["col"]), int(enemy_entry["row"])
                enemy_fp = enemy_entry.get("occupied_hexes", {(ec, er)})
                if candidate_fp & enemy_fp:
                    hex_overlaps_enemy = True
                    break
                # Opt 1 — prefiltre per-enemy avant l'appel coûteux unit_entries_within_engagement_zone.
                _bfs_ee_is_rr = (_bfs_is_mover_round and enemy_entry["BASE_SHAPE"] == "round")
                if _bfs_ee_is_rr:
                    if _eid in _bfs_rr_near_set and neighbor_pos not in _bfs_rr_near_set[_eid]:
                        continue
                elif _eid in _bfs_enemy_eng_zones:
                    if not (candidate_fp & _bfs_enemy_eng_zones[_eid]):
                        continue
                bfs_engagement_checks_n += 1
                if unit_entries_within_engagement_zone(
                    synth, enemy_entry, engagement_zone
                ):
                    is_adjacent_to_enemy = True
                    if _cur_engaging is not None:
                        _cur_engaging.add(str(_eid))
                    if tid_arg:
                        break
            if _perf and _t_engagement0 is not None:
                bfs_engagement_s += time.perf_counter() - _t_engagement0

            if hex_overlaps_enemy:
                bfs_overlap_n += 1
            elif not is_adjacent_to_enemy:
                bfs_no_engagement_n += 1

            if is_adjacent_to_enemy and not hex_overlaps_enemy and neighbor_pos != start_pos:
                valid_destinations.append(neighbor_pos)
                if _track_engages and _cur_engaging is not None:
                    pos_dist_engage[neighbor_pos] = (neighbor_dist, frozenset(_cur_engaging))
                if early_exit_if_valid:
                    bfs_short_circuit = True
                    break

            queue.append((neighbor_pos, neighbor_dist))

    _t_bfs1 = time.perf_counter() if _perf else None

    # DEBUG LOG — BFS destinations diagnostic
    _dbg_near_sz = len(_near_enemy_set)
    add_console_log(game_state, (
        f"[CHARGE_BFS] unit={unit_id} bfs_max={bfs_max_distance} start=({start_col},{start_row}) "
        f"near_set_sz={_dbg_near_sz} visited={len(visited)} valid_dest={len(valid_destinations)} "
        f"enemies={[(str(eid), int(ce['col']), int(ce['row'])) for eid,ce in indexed_enemy_engagement]}"
    ))
    safe_print(game_state, (
        f"[CHARGE_BFS] unit={unit_id} bfs_max={bfs_max_distance} start=({start_col},{start_row}) "
        f"near_set_sz={_dbg_near_sz} visited={len(visited)} valid_dest={len(valid_destinations)}"
    ))

    # Multi-cibles V11 : ne garder que les ancres dont l'ensemble d'ennemis engagés est EXACTEMENT
    # l'ensemble déclaré → ``declared ⊆ eng`` (toutes les cibles) ET ``eng ⊆ declared`` (aucun non-cible).
    if _multi_declared is not None:
        valid_destinations = [
            p for p in valid_destinations
            if pos_dist_engage.get(p, (0, frozenset()))[1] == _multi_declared
        ]

    game_state["valid_charge_destinations_pool"] = valid_destinations
    # Distance de mouvement par ancre (sous-hex) : step-BFS sol → profondeur de chemin (respecte
    # murs + figs), exactement la distance réelle de la charge. Source unique pour le tooltip.
    game_state["valid_charge_dest_distances"] = {
        p: pos_dist_engage[p][0] for p in valid_destinations if p in pos_dist_engage
    }
    if charge_range == CHARGE_MAX_DISTANCE_SUBHEX and not early_exit_if_valid and tid_arg is None and _multi_declared is None:
        cache[cache_key] = (list(valid_destinations), pos_dist_engage)

    if _perf and _t_func0 is not None and _t_bfs0 is not None and _t_bfs1 is not None:
        _t_done = time.perf_counter()
        _ee = "1" if early_exit_if_valid else "0"
        _sc = "1" if bfs_short_circuit else "0"
        append_perf_timing_line(
            f"CHARGE_DEST_BFS episode={_ep} turn={_turn} unit_id={unit_id} charge_roll={charge_range} "
            f"bfs_max={bfs_max_distance} "
            f"bfs_loop_s={_t_bfs1 - _t_bfs0:.6f} total_s={_t_done - _t_func0:.6f} "
            f"bfs_candidate_fp_s={bfs_candidate_fp_s:.6f} bfs_placement_s={bfs_placement_s:.6f} "
            f"bfs_engagement_s={bfs_engagement_s:.6f} bfs_rejected_placement_n={bfs_rejected_placement_n} "
            f"bfs_overlap_n={bfs_overlap_n} bfs_no_engagement_n={bfs_no_engagement_n} "
            f"bfs_engagement_checks_n={bfs_engagement_checks_n} "
            f"visited_n={len(visited)} valid_dest_n={len(valid_destinations)} cache_hit=0 "
            f"early_exit={_ee} short_circuit={_sc} fp={_fp_tag}"
        )

    return valid_destinations




def _select_strategic_destination(
    strategy_id: int,
    valid_destinations: List[Tuple[int, int]],
    unit: Dict[str, Any],
    game_state: Dict[str, Any]
) -> Tuple[int, int]:
    """
    Select movement destination based on strategic heuristic.
    AI_TURN.md COMPLIANCE: Pure stateless function with direct field access.

    Args:
        strategy_id: 0=aggressive, 1=tactical, 2=defensive, 3=random
        valid_destinations: List of valid (col, row) tuples from BFS
        unit: Unit dict with position and stats
        game_state: Full game state for enemy detection

    Returns:
        Selected destination (col, row)
    """
    from engine.combat_utils import has_line_of_sight

    # Direct field access with validation
    if "units" not in game_state:
        raise KeyError("game_state missing required 'units' field")
    if "col" not in unit or "row" not in unit:
        raise KeyError(f"Unit missing required position fields: {unit}")
    if "player" not in unit:
        raise KeyError(f"Unit missing required 'player' field: {unit}")
    if "RNG_RNG" not in unit:
        raise KeyError(f"Unit missing required 'RNG_RNG' field: {unit}")

    # If no destinations, return current position
    if not valid_destinations:
        return require_unit_position(unit, game_state)

    # Get enemy units
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    enemy_units = [enemy_id for enemy_id, cache_entry in units_cache.items()
                   if int(cache_entry["player"]) != unit_player]

    # If no enemies, just pick first destination
    if not enemy_units:
        return valid_destinations[0]

    # Pre-build enemy positions from cache (avoids repeated require_unit_position calls)
    enemy_positions = {eid: (units_cache[str(eid)]["col"], units_cache[str(eid)]["row"]) for eid in enemy_units}

    # STRATEGY 0: AGGRESSIVE - Move closest to nearest enemy
    if strategy_id == 0:
        best_dest = valid_destinations[0]
        min_dist_to_enemy = float('inf')

        for dest in valid_destinations:
            # Find distance to nearest enemy from this destination
            for enemy_id in enemy_units:
                enemy_col, enemy_row = enemy_positions[enemy_id]
                dist = _calculate_hex_distance(dest[0], dest[1], enemy_col, enemy_row)
                if dist < min_dist_to_enemy:
                    min_dist_to_enemy = dist
                    best_dest = dest

        return best_dest

    # STRATEGY 1: TACTICAL - Move to position with most enemies in shooting range
    elif strategy_id == 1:
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
        from engine.utils.weapon_helpers import get_max_ranged_range
        weapon_range = get_max_ranged_range(unit)
        best_dest = valid_destinations[0]
        max_targets = 0

        for dest in valid_destinations:
            targets_in_range = 0
            for enemy_id in enemy_units:
                enemy_col, enemy_row = enemy_positions[enemy_id]
                dist = _calculate_hex_distance(dest[0], dest[1], enemy_col, enemy_row)
                if dist <= weapon_range:
                    # Check LoS (simplified - assumes LoS if in range for now)
                    targets_in_range += 1

            if targets_in_range > max_targets:
                max_targets = targets_in_range
                best_dest = dest

        return best_dest

    # STRATEGY 2: DEFENSIVE - Move farthest from all enemies
    elif strategy_id == 2:
        best_dest = valid_destinations[0]
        max_min_dist = 0

        for dest in valid_destinations:
            # Find distance to nearest enemy (we want to maximize this)
            min_dist_to_any_enemy = float('inf')
            for enemy_id in enemy_units:
                enemy_col, enemy_row = enemy_positions[enemy_id]
                dist = _calculate_hex_distance(dest[0], dest[1], enemy_col, enemy_row)
                if dist < min_dist_to_any_enemy:
                    min_dist_to_any_enemy = dist

            if min_dist_to_any_enemy > max_min_dist:
                max_min_dist = min_dist_to_any_enemy
                best_dest = dest

        return best_dest

    # STRATEGY 3: RANDOM - Pick random destination for exploration
    else:
        import random
        return random.choice(valid_destinations)


def charge_preview(valid_destinations: List[Tuple[int, int]]) -> Dict[str, Any]:
    """Generate preview data for violet hexes (charge destinations)"""
    return {
        "violet_hexes": valid_destinations,  # Changed from green_hexes to violet_hexes
        "show_preview": True
    }


def charge_clear_preview(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Clear charge preview"""
    game_state["preview_hexes"] = []
    game_state["valid_charge_destinations_pool"] = []
    # Clear active_charge_unit to allow next unit activation
    game_state["active_charge_unit"] = None
    return {
        "show_preview": False,
        "clear_hexes": True
    }


def charge_click_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Route charge click actions"""
    # AI_TURN.md COMPLIANCE: Direct field access
    if "clickTarget" not in action:
        click_target = "elsewhere"
    else:
        click_target = action["clickTarget"]

    if click_target == "destination_hex":
        return charge_destination_selection_handler(game_state, unit_id, action)
    elif click_target == "enemy" and "targetId" in action:
        # Click on enemy unit -> target selection (roll 2d6, build destinations)
        return charge_target_selection_handler(game_state, unit_id, action)
    elif click_target == "friendly_unit":
        return False, {"error": "unit_switch_not_implemented", "action": "charge"}
    elif click_target == "active_unit":
        # AI_TURN.md Line 1409: Left click on active_unit -> Charge postponed
        # Clear preview but keep unit in pool (different from skip which removes from pool)
        charge_clear_preview(game_state)
        # Clear charge roll and target selection if exists (postpone discards the roll)
        if "charge_roll_values" in game_state and unit_id in game_state["charge_roll_values"]:
            del game_state["charge_roll_values"][unit_id]
        if "charge_target_selections" in game_state and unit_id in game_state["charge_target_selections"]:
            del game_state["charge_target_selections"][unit_id]
        return True, {
            "action": "postpone",
            "unitId": unit_id,
            "charge_postponed": True
        }
    else:
        return True, {"action": "continue_selection"}

def charge_target_selection_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Handle charge target selection: roll 2d6, build pool, display preview.
    
    Flow:
    1. Agent chooses a target
    2. Roll 2d6
    3. Build pool of destinations for this target with the roll
    4. Display preview (violet hexes) for PvP/PvE modes
    5. Return waiting_for_player for destination selection
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled
    _perf = perf_timing_enabled(game_state)
    _ep = game_state.get("episode_number", "?")
    _turn = game_state.get("turn", "?")
    _t_tsel0 = time.perf_counter() if _perf else None

    # Multi-cibles V11 : ``targetIds`` (liste, validation par le clic « Charge ») prioritaire ;
    # ``targetId`` (cible unique) accepté pour rétro-compat (PvE/gym/legacy).
    if "targetIds" in action and action["targetIds"]:
        _raw_targets = list(action["targetIds"])
    elif "targetId" in action and action["targetId"] is not None:
        _raw_targets = [action["targetId"]]
    else:
        return False, {"error": "missing_target", "action": "charge"}
    target_ids = [str(t) for t in _raw_targets]
    target_id = target_ids[0]  # 1ère cible déclarée — sert aux messages/retours d'affichage

    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id, "action": "charge"}

    # Re-evaluate adjacency at execution time.
    # Charge pool is built earlier and board state may change before target selection.
    if _charge_unit_within_engagement_zone(game_state, unit):
        return _handle_skip_action(game_state, unit, had_valid_destinations=False)

    # V11 RAW (PvP/PvE) : réutiliser le jet 2D6 effectué à L'ACTIVATION
    # (charge_unit_execution_loop), conformément à 11.02 (jet avant déclaration des cibles).
    # En gym (RL), le jet a lieu ici comme avant pour ne pas changer le MDP de l'agent.
    # Résultat en POUCES (2..12) ; scalé en sous-hex via ``inches_to_subhex`` pour rester
    # homogène avec ``charge_max_distance``, ``engagement_zone`` et les footprints.
    is_gym = game_state.get("gym_training_mode", False)
    if not is_gym and unit_id in game_state["charge_roll_values"]:
        charge_roll = game_state["charge_roll_values"][unit_id]
    else:
        import random
        charge_roll = random.randint(1, 6) + random.randint(1, 6)
        game_state["charge_roll_values"][unit_id] = charge_roll
    _charge_scale = game_state["inches_to_subhex"]
    # Take to the skies (21.03) : -2" sur la distance max de charge si le vol est déclaré.
    charge_roll_subhex = _charge_budget_subhex(game_state, unit_id, charge_roll)
    # Store the declared target LIST for destination selection (V11 multi-cibles).
    if "charge_target_selections" not in game_state:
        game_state["charge_target_selections"] = {}
    game_state["charge_target_selections"][unit_id] = target_ids

    # Clear pending targets after selection
    if "pending_charge_targets" in game_state:
        del game_state["pending_charge_targets"]
    if "pending_charge_unit_id" in game_state:
        del game_state["pending_charge_unit_id"]

    # Pool multi-cibles : ancres atteignables dont l'empreinte engage EXACTEMENT l'ensemble déclaré
    # (toutes les cibles, aucun ennemi non-cible) — moteur 1a (``eng == declared``). Puis préférence
    # socle-à-socle avec ≥1 cible déclarée. La zone violette d'affichage vient de l'union des
    # empreintes finales légales (``_charge_footprint_union_for_anchors``), pas d'une zone théorique.
    _ref_c, _ref_r = require_unit_position(unit, game_state)
    charge_reference_hex: Tuple[int, int] = (int(_ref_c), int(_ref_r))
    target_entries: List[Dict[str, Any]] = []
    valid_pool: List[Tuple[int, int]] = []
    _targets_ok = True
    for _tid in target_ids:
        _te = get_unit_by_id(game_state, _tid)
        if not _te or _te["player"] == unit["player"] or not is_unit_alive(str(_te["id"]), game_state):
            _targets_ok = False
            break
        target_entries.append(_te)
    if _targets_ok and target_entries:
        _t_bfs0 = time.perf_counter() if _perf else None
        bfs_reachable = charge_build_valid_destinations_pool(
            game_state,
            str(unit_id),
            int(charge_roll_subhex),
            target_ids=target_ids,
        )
        _t_bfs1 = time.perf_counter() if _perf else None
        valid_pool = _charge_pool_must_socle_a_socle_if_possible(
            game_state, unit, target_entries, bfs_reachable
        )
        # Hex de référence = case du chargeur la plus proche de l'union des empreintes cibles.
        _uc = require_key(game_state, "units_cache")
        _ue = _uc.get(str(unit_id))
        if _ue:
            _charger_fp = set(_ue.get("occupied_hexes") or {(int(_ue["col"]), int(_ue["row"]))})
            _union_tfp: Set[Tuple[int, int]] = set()
            for _te in target_entries:
                _tc, _tr = int(_te["col"]), int(_te["row"])
                _te_cache = _uc.get(str(_te["id"])) or {}
                _union_tfp |= set(_te_cache.get("occupied_hexes") or {(_tc, _tr)})
            _closest_ch, _ = _charge_closest_charger_hex_to_target(_charger_fp, _union_tfp)
            charge_reference_hex = (int(_closest_ch[0]), int(_closest_ch[1]))
        if _perf and _t_tsel0 is not None and _t_bfs0 is not None and _t_bfs1 is not None:
            append_perf_timing_line(
                f"CHARGE_TARGET_SEL episode={_ep} turn={_turn} unit_id={unit_id} "
                f"n_targets={len(target_ids)} bfs_s={_t_bfs1 - _t_bfs0:.6f} "
                f"total_s={time.perf_counter() - _t_tsel0:.6f} pool_size={len(valid_pool)}"
            )
    game_state["valid_charge_destinations_pool"] = valid_pool
    if "debug_mode" in game_state and game_state["debug_mode"]:
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        add_debug_file_log(
            game_state,
            f"[CHARGE TRACE] E{episode} T{turn} charge_target_selection unit_id={unit_id} "
            f"target_id={target_id} charge_roll={charge_roll} valid_pool={len(valid_pool)}"
        )

    # Check if pool is empty (roll too low)
    if not valid_pool:
        # Charge roll too low - charge failed
        if "action_logs" not in game_state:
            game_state["action_logs"] = []
        
        if "current_turn" not in game_state:
            current_turn = 1
        else:
            current_turn = game_state["current_turn"]
        
        append_action_log(
            game_state,
            {
                "type": "charge_fail",
                "message": f"Unit {unit['id']} ({unit['col']}, {unit['row']}) FAILED charge to target {target_id} (Roll: {charge_roll} too low)",
                "turn": current_turn,
                "phase": "charge",
                "unitId": unit["id"],
                "player": unit["player"],
                "targetId": target_id,
                "charge_roll": charge_roll,
                "charge_failed": True,
                "timestamp": "server_time",
            },
        )

        # Clear charge roll after use
        if unit_id in game_state["charge_roll_values"]:
            del game_state["charge_roll_values"][unit_id]
        if "charge_target_selections" in game_state and unit_id in game_state["charge_target_selections"]:
            del game_state["charge_target_selections"][unit_id]
        
        # Clear preview
        charge_clear_preview(game_state)
        
        # End activation with failure
        result = end_activation(
            game_state, unit,
            PASS,          # Arg1: Pass logging (charge failed)
            1,             # Arg2: +1 step increment (action was attempted)
            PASS,          # Arg3: NO tracking (charge didn't happen)
            CHARGE,        # Arg4: Remove from charge_activation_pool
            0              # Arg5: No error logging
        )
        
        # CRITICAL: Add start_pos and end_pos for proper logging (unit didn't move, so both are current position)
        # For failed charges with roll too low, there's no destination, so end_pos equals start_pos
        current_pos = require_unit_position(unit, game_state)
        action_logs = game_state["action_logs"] if "action_logs" in game_state else []
        result.update({
            "action": "charge_fail",
            "unitId": unit["id"],
            "targetId": target_id,
            "charge_roll": charge_roll,
            "charge_failed": True,
            "charge_failed_reason": "roll_too_low",
            "start_pos": current_pos,  # Position actuelle (from) - unit didn't move
            "end_pos": current_pos,  # No destination (roll too low), so equals start_pos
            "activation_complete": True,
            "action_logs": action_logs
        })
        
        # Check if pool is now empty after removing this unit
        if not game_state["charge_activation_pool"]:
            phase_end_result = charge_phase_end(game_state)
            result.update(phase_end_result)
        
        return True, result

    # Pool is valid - display preview (violet hexes) for PvP/PvE modes
    # Check if PvP or PvE mode
    is_pve = game_state.get("pve_mode", False) or game_state.get("is_pve_mode", False)
    is_gym = game_state.get("gym_training_mode", False)
    
    if not is_gym:  # PvP or PvE mode
        # Generate preview with violet hexes (charge destinations)
        preview_data = charge_preview(valid_pool)
        game_state["preview_hexes"] = valid_pool
        # Violet = union des empreintes finales légales (murs, occupation, engagement).
        # ``display_zone_set`` sert uniquement à énumérer les ancres candidates ; l'UI ne doit
        # pas montrer des hex « théoriques » où le socle ne peut pas tenir.
        display_union = _charge_footprint_union_for_anchors(
            game_state, str(unit_id), valid_pool
        )
        display_hexes = [[int(c), int(r)] for (c, r) in display_union]

        # Distance de mouvement réelle par ancre (sous-hex), depuis le BFS de charge : profondeur de
        # chemin au sol (respecte murs/figs), distance directe en vol déclaré. Sert au tooltip pour
        # afficher la vraie distance de charge au lieu de la ligne droite (qui sous-estime les détours).
        _dist_map = (
            game_state["valid_charge_dest_distances"]
            if "valid_charge_dest_distances" in game_state
            else {}
        )
        charge_dest_distances = [
            [int(c), int(r), int(_dist_map[(c, r)])]
            for (c, r) in valid_pool
            if (c, r) in _dist_map
        ]

        # Human players: return waiting_for_player for destination selection
        return True, {
            "action": "charge_target_selected",
            "unitId": unit_id,
            "targetId": target_id,
            "targetIds": target_ids,
            "charge_roll": charge_roll,
            # Hex de référence pour la portée (empreinte chargeur la plus proche de la cible) —
            # l’UI doit l’utiliser pour la règle / tooltip ; ne pas le recalculer depuis units_cache.
            "charge_reference_hex": [charge_reference_hex[0], charge_reference_hex[1]],
            "valid_destinations": valid_pool,
            "charge_dest_distances": charge_dest_distances,
            "charge_preview_display_hexes": display_hexes,
            "preview_data": preview_data,
            "clear_blinking_gentle": True,  # Stop blinking when target is selected
            "waiting_for_player": True  # Wait for destination selection
        }
    else:
        # AI_TURN.md COMPLIANCE: In gym training, AI selects destination automatically and executes charge
        # AI_TURN.md lines 1393-1396: Select destination hex → Move unit → end_activation
        # No preview needed, auto-select first valid destination
        preview_data = {}
        game_state["preview_hexes"] = []
        
        # Select first valid destination (AI chooses best destination automatically)
        if valid_pool:
            dest_col, dest_row = valid_pool[0]
            # Execute charge directly with selected destination
            destination_action = {
                "action": "charge",
                "unitId": unit_id,
                "targetId": target_id,
                "destCol": dest_col,
                "destRow": dest_row
            }
            return charge_destination_selection_handler(game_state, unit_id, destination_action)
        else:
            # No valid destinations (should not happen after pool check, but defensive)
            return False, {"error": "no_valid_destinations_after_target_selection", "action": "charge"}


def _apply_charge_impact(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    target_id: Any,
    dest_col: int,
    dest_row: int,
    target_col: int,
    target_row: int,
    current_turn: int,
) -> None:
    """Applique la règle ``charge_impact`` (D6 → blessures mortelles) si l'unité la possède.

    Extrait de ``charge_destination_selection_handler`` pour être partagé avec le commit
    par-figurine (``charge_commit_move_plan_handler``) — comportement strictement identique.
    """
    if not _unit_has_rule(unit, "charge_impact"):
        return
    impact_ability_display_name = _get_source_unit_rule_display_name_for_effect(unit, "charge_impact")
    if impact_ability_display_name is None:
        unit_name = unit.get("DISPLAY_NAME") or unit.get("unitType") or "UNKNOWN"
        raise ValueError(
            f"Unit {unit['id']} ({unit_name}) triggered charge_impact without source rule displayName"
        )
    impact_roll = resolve_dice_value("D6", "charge_impact_roll")
    impact_hit_result = "FAIL"
    if impact_roll >= CHARGE_IMPACT_TRIGGER_THRESHOLD:
        impact_hit_result = "HIT"
        mortal_wounds = CHARGE_IMPACT_MORTAL_WOUNDS
        target_hp = require_hp_from_cache(str(target_id), game_state)
        new_target_hp = max(0, target_hp - mortal_wounds)
        update_units_cache_hp(game_state, str(target_id), new_target_hp)
    else:
        mortal_wounds = 0
    impact_message = (
        f"Unit {unit['id']}({dest_col},{dest_row}) IMPACTED [{impact_ability_display_name}] "
        f"Unit {target_id}({target_col},{target_row}) - "
        f"Hit:{CHARGE_IMPACT_TRIGGER_THRESHOLD}+:{impact_roll}({impact_hit_result})"
    )
    if impact_hit_result == "HIT":
        impact_message += f" Wound:AUTO Save:NONE[MW] Dmg:{mortal_wounds}HP"
    append_action_log(
        game_state,
        {
            "type": "charge_impact",
            "message": impact_message,
            "turn": current_turn,
            "phase": "charge",
            "unitId": unit["id"],
            "targetId": target_id,
            "player": unit["player"],
            "impact_roll": impact_roll,
            "impact_threshold": CHARGE_IMPACT_TRIGGER_THRESHOLD,
            "impact_hit_result": impact_hit_result,
            "mortal_wounds": mortal_wounds,
            "ability_display_name": impact_ability_display_name,
            "attackerCol": dest_col,
            "attackerRow": dest_row,
            "targetCol": target_col,
            "targetRow": target_row,
            "reward": 0.0,
            "timestamp": "server_time",
            "is_ai_action": unit["player"] == 1,
        },
    )
    add_console_log(game_state, impact_message)


def _charge_model_pos_is_closer(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    model_id: str,
    dest_c: int,
    dest_r: int,
    target_ids: List[str],
    roll_subhex: int,
    provisional_plan: Dict[str, Tuple[int, int]],
) -> bool:
    """Légalité d'UNE position (c,r) pour la fig ``model_id`` (membre "closer" du pool Slice E), sans
    construire le pool complet : BFS reachability avec early-exit sur ``dest`` + classification du
    seul hex final. Mêmes contraintes que ``charge_build_model_destinations_pool`` (budget, pas de
    traversée mur/fig, finit plus proche, n'engage aucun non-cible)."""
    from collections import deque
    from engine.hex_utils import min_distance_between_sets
    from engine.spatial_relations import unit_entries_within_engagement_zone
    from .shared_utils import get_engagement_zone

    models_cache = require_key(game_state, "models_cache")
    model = models_cache.get(str(model_id))
    if model is None:
        return False
    ez = int(get_engagement_zone(game_state))
    budget = int(roll_subhex)
    board_cols = int(require_key(game_state, "board_cols"))
    board_rows = int(require_key(game_state, "board_rows"))
    wall_hexes = game_state.get("wall_hexes", set())
    player = int(model["player"])
    squad_id = str(model["squad_id"])
    units_cache = require_key(game_state, "units_cache")

    declared = {str(t) for t in target_ids}
    target_fps: List[Set[Tuple[int, int]]] = []
    nontarget_entries: List[Dict[str, Any]] = []
    enemy_occupied: Set[Tuple[int, int]] = set()
    other_occupied: Set[Tuple[int, int]] = set()
    for eid, entry in units_cache.items():
        occ = entry.get("occupied_hexes")
        cells = set(occ) if occ else {(int(entry["col"]), int(entry["row"]))}
        if int(entry["player"]) != player:
            enemy_occupied |= cells
            if str(eid) in declared:
                target_fps.append(cells)
            else:
                nontarget_entries.append(entry)
        elif str(eid) != squad_id:
            other_occupied |= cells
    if not target_fps:
        return False

    # Géométrie PAR-FIGURINE : la fig mobile et chaque coéquipière utilisent LEUR propre base
    # (models_cache), pas celle de l'unité (cf. personnage attaché à plus grande base).
    sibling_socles: List[Any] = []
    squad_models = require_key(game_state, "squad_models")
    for mid in require_key(squad_models, squad_id):
        if str(mid) == str(model_id):
            continue
        sib = models_cache.get(str(mid))
        if sib is None:
            continue
        if provisional_plan and str(mid) in provisional_plan:
            pc, pr = provisional_plan[str(mid)]
        else:
            pc, pr = int(sib["col"]), int(sib["row"])
        sibling_socles.append(_charge_model_socle(game_state, sib, int(pc), int(pr)))
    # 03.01 : déplacement À TRAVERS les figs amies autorisé, PAS à travers les ennemies ni les murs.
    path_blocked = set(wall_hexes) | enemy_occupied
    # 03 « Ending a move » : non-chevauchement final délégué à _charge_model_placement_overlaps.
    # Take to the skies (21.03) : vol actif → traversée libre ; placement final reste interdit d'overlap.
    fly_active = _charge_fly_active(game_state, unit, squad_id)
    traverse_blocked = set() if fly_active else path_blocked

    start_col, start_row = int(model["col"]), int(model["row"])
    start_fp = _charge_model_footprint(game_state, model, start_col, start_row)
    start_min = min(min_distance_between_sets(start_fp, tfp) for tfp in target_fps)
    dest = (int(dest_c), int(dest_r))

    # Reachability BFS (centre-à-centre, traverse les amies, pas mur/ennemi sauf vol actif), early-exit dest.
    if dest != (start_col, start_row):
        visited: Set[Tuple[int, int]] = {(start_col, start_row)}
        queue: deque = deque([(start_col, start_row, 0)])
        found = False
        while queue and not found:
            c, r, d = queue.popleft()
            if d >= budget:
                continue
            for nc, nr in get_hex_neighbors(c, r):
                if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
                    continue
                cell = (nc, nr)
                if cell in visited or cell in traverse_blocked:
                    continue
                if cell == dest:
                    found = True
                    break
                visited.add(cell)
                queue.append((nc, nr, d + 1))
        if not found:
            return False

    cand_socle = _charge_model_socle(game_state, model, dest[0], dest[1])
    cand_fp = cand_socle.fp
    if any(not (0 <= x < board_cols and 0 <= y < board_rows) for (x, y) in cand_fp):
        return False
    obstacle_socles = _charge_obstacle_socles(game_state, squad_id)
    if _charge_model_placement_overlaps(cand_socle, obstacle_socles, sibling_socles, set(wall_hexes)):
        return False
    d_min = min(min_distance_between_sets(cand_fp, tfp, max_distance=start_min) for tfp in target_fps)
    if d_min >= start_min:
        return False
    synth = _charge_synthetic_charger_cache_entry(game_state, unit, dest[0], dest[1], cand_fp)
    if any(unit_entries_within_engagement_zone(synth, ne, ez) for ne in nontarget_entries):
        return False
    return True


def charge_preview_move_plan(
    game_state: Dict[str, Any], squad_id: str, plan: List[Tuple[str, int, int]], target_ids: List[str]
) -> Dict[str, Any]:
    """Dry-run d'un plan de charge par-figurine (11.04 WHILE/AFTER MOVING). Lecture pure.

    ``plan`` = liste de ``[model_id, col, row]`` couvrant TOUTES les figs vivantes. Source unique
    de vérité : la légalité par-fig réutilise ``charge_build_model_destinations_pool`` (mêmes
    contraintes que le cercle violet : budget = jet, pas de traversée, finit plus proche, n'engage
    aucun non-cible), avec les autres figs du plan en positions provisoires. On ajoute :
      - cohésion 03.03 (mêmes 2 puces que le move, empreinte-à-empreinte) ;
      - engaged_all : chaque cible déclarée est engagée par >=1 fig (AFTER MOVING).

    Retour : {per_model: {mid: bool}, can_validate, engaged_all, missing_targets}.
    """
    from engine.hex_utils import min_distance_between_sets
    from engine.spatial_relations import unit_entries_within_engagement_zone
    from .shared_utils import (
        get_engagement_zone,
        get_coherency_subhex,
        get_cohesion_max_subhex,
        get_min_neighbors,
    )

    unit = get_unit_by_id(game_state, str(squad_id))
    empty = {"per_model": {}, "can_validate": False, "engaged_all": False, "missing_targets": []}
    if not unit:
        return empty
    norm = [(str(m), int(c), int(r)) for m, c, r in plan]
    n = len(norm)
    if n == 0:
        return empty
    roll = game_state["charge_roll_values"].get(str(squad_id))
    if roll is None:
        return empty
    # Take to the skies (21.03) : -2" sur la distance max de charge si le vol est déclaré.
    roll_subhex = _charge_budget_subhex(game_state, squad_id, roll)

    # 1) Légalité per-fig = appartenance au pool Slice E (budget + traversée + closer + no-non-cible),
    #    les autres figs du plan servant de positions provisoires (collision intra-squad).
    pos_by_model = {mid: (c, r) for mid, c, r in norm}
    per_model: Dict[str, bool] = {}
    for mid, c, r in norm:
        prov = {m2: pos_by_model[m2] for m2 in pos_by_model if m2 != mid}
        # Check ciblé d'une seule position (BFS early-exit) au lieu de construire tout le pool.
        per_model[mid] = _charge_model_pos_is_closer(
            game_state, unit, mid, c, r, target_ids, roll_subhex, provisional_plan=prov
        )

    # 2) Cohésion (identique au move : 1re puce voisins < min, 2e puce une fig à > coh_max).
    #    Empreintes PAR-FIGURINE (chaque fig a sa base).
    _mc_cohesion = require_key(game_state, "models_cache")
    fps = [_charge_model_footprint(game_state, _mc_cohesion[str(mid)], c, r) for mid, c, r in norm]
    coh = get_coherency_subhex(game_state)
    coh_max = get_cohesion_max_subhex(game_state)
    min_nb = get_min_neighbors(game_state)
    neigh = [0] * n
    too_far = [False] * n
    for i in range(n):
        for j in range(i + 1, n):
            d = min_distance_between_sets(fps[i], fps[j], max_distance=coh_max)
            if d <= coh:
                neigh[i] += 1
                neigh[j] += 1
            if d > coh_max:
                too_far[i] = True
                too_far[j] = True
    if n > 1:
        for i, (mid, _c, _r) in enumerate(norm):
            if neigh[i] < min_nb or too_far[i]:
                per_model[mid] = False

    # 3) engaged_all : chaque cible déclarée est engagée par au moins une figurine.
    ez = int(get_engagement_zone(game_state))
    units_cache = require_key(game_state, "units_cache")
    missing: List[str] = []
    for tid in (str(t) for t in target_ids):
        tentry = units_cache.get(tid)
        if tentry is None:
            missing.append(tid)
            continue
        engaged = False
        for idx, (mid, c, r) in enumerate(norm):
            synth = _charge_synthetic_charger_cache_entry(game_state, unit, c, r, fps[idx])
            if unit_entries_within_engagement_zone(synth, tentry, ez):
                engaged = True
                break
        if not engaged:
            missing.append(tid)
    engaged_all = len(missing) == 0
    can_validate = bool(n > 0 and all(per_model.values()) and engaged_all)
    return {
        "per_model": per_model,
        "can_validate": can_validate,
        "engaged_all": engaged_all,
        "missing_targets": missing,
    }


def charge_set_fly_mode_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Take to the skies en CHARGE (Règles 21.03) : (dé)clare le vol de l'unité FLY active.

    Toggle : ajoute/retire l'escouade de ``units_took_to_skies_charge`` (set DÉDIÉ à la charge,
    distinct de la phase move). Effet lu par ``_charge_budget_subhex`` (-2") et ``_charge_fly_active``
    (traversée murs/figurines) : pools de cibles, BFS par-figurine et validation au commit. Réversible
    tant que la charge n'est pas commit. Déclaration par-déplacement, faite avant de bouger l'unité.

    Refresh état-complet selon l'étape : cibles déjà déclarées → recompute du plan par-figurine ;
    sinon → preview des cibles éligibles (re-bornées par la distance -2").
    """
    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id}
    from .movement_handlers import _unit_has_keyword
    if not _unit_has_keyword(unit, "fly"):
        return False, {"error": "unit_cannot_fly", "unitId": unit["id"]}

    tts = game_state.setdefault("units_took_to_skies_charge", set())
    uid = str(unit_id)
    if uid in tts:
        tts.discard(uid)
        declared = False
    else:
        tts.add(uid)
        declared = True

    # Cibles déjà déclarées → le toggle recompute le plan par-figurine au nouveau budget/traversée.
    if "charge_target_selections" in game_state and uid in game_state["charge_target_selections"]:
        prov: Dict[str, Tuple[int, int]] = {}
        for entry in (action.get("plan") or []):
            prov[str(entry[0])] = (int(entry[1]), int(entry[2]))
        sel = action.get("selected_model")
        state = charge_model_plan_state(
            game_state, unit_id, prov, selected_model=(str(sel) if sel is not None else None)
        )
        return True, {
            "action": "charge_fly_mode_set",
            "unitId": unit["id"],
            "took_to_skies": declared,
            **state,
        }

    # Sinon (avant sélection de cible) → re-borne les cibles éligibles au budget -2", SANS l'effet de
    # bord d'échec de ``charge_unit_execution_loop`` (qui consommerait l'unité si plus aucune cible
    # n'est atteignable). Le toggle reste réversible : zéro cible = liste vide, l'unité reste active.
    charge_roll = (
        game_state["charge_roll_values"] if "charge_roll_values" in game_state else {}
    ).get(unit_id)
    max_distance_subhex = (
        _charge_budget_subhex(game_state, unit_id, charge_roll) if charge_roll is not None else None
    )
    valid_targets = charge_build_valid_targets(game_state, unit_id, max_distance=max_distance_subhex)
    target_ids_blink = [str(t["id"]) for t in valid_targets]
    return True, {
        "action": "charge_fly_mode_set",
        "unitId": unit["id"],
        "took_to_skies": declared,
        "charge_roll": charge_roll,
        "valid_targets": valid_targets,
        "waiting_for_player": True,
        "blinking_units": target_ids_blink,
        "start_blinking": True,
    }


def charge_commit_move_plan_handler(
    game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """Commit d'un plan de charge par-figurine (V11 PvP). ``action["plan"]`` = ``[[mid,col,row],...]``
    couvrant toutes les figs vivantes. Valide la config finale (``charge_preview_move_plan``), pose les
    figs (``commit_move`` type ``charge`` → positions + ``units_charged``), applique ``charge_impact`` et
    clôt l'activation. Le jet et les cibles déclarées proviennent de l'état stocké (roll-first)."""
    if "plan" not in action:
        raise KeyError(f"commit_charge_plan action missing required 'plan' field: {action}")
    raw_plan = action["plan"]
    if not isinstance(raw_plan, list) or not raw_plan:
        return False, {"error": "empty_charge_plan", "unitId": unit_id}
    plan: List[Tuple[str, int, int]] = []
    for entry in raw_plan:
        if not (isinstance(entry, (list, tuple)) and len(entry) == 3):
            raise ValueError(
                f"commit_charge_plan: plan entry must be [model_id, col, row], got {entry!r}"
            )
        plan.append((str(entry[0]), int(entry[1]), int(entry[2])))

    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id, "action": "charge"}
    if "charge_target_selections" not in game_state or unit_id not in game_state["charge_target_selections"]:
        return False, {"error": "target_not_selected", "unit_id": unit_id, "action": "charge"}
    if "charge_roll_values" not in game_state or unit_id not in game_state["charge_roll_values"]:
        return False, {"error": "charge_roll_missing", "unit_id": unit_id, "action": "charge"}
    _stored = game_state["charge_target_selections"][unit_id]
    target_ids = list(_stored) if isinstance(_stored, (list, tuple)) else [_stored]
    target_id = target_ids[0]
    charge_roll = game_state["charge_roll_values"][unit_id]

    # Le plan doit couvrir exactement les figs vivantes de l'escouade.
    squad_models = require_key(game_state, "squad_models")
    models_cache = require_key(game_state, "models_cache")
    alive = {m for m in require_key(squad_models, str(unit_id)) if m in models_cache}
    plan_ids = {mid for mid, _, _ in plan}
    if plan_ids != alive:
        return False, {
            "error": "plan_models_mismatch",
            "unitId": unit_id,
            "expected": sorted(alive),
            "got": sorted(plan_ids),
        }

    preview = charge_preview_move_plan(game_state, str(unit_id), plan, target_ids)
    if not preview["can_validate"]:
        return False, {
            "error": "invalid_charge_plan",
            "unitId": unit_id,
            "per_model": preview["per_model"],
            "engaged_all": preview["engaged_all"],
            "missing_targets": preview["missing_targets"],
        }

    orig_col, orig_row = require_unit_position(unit, game_state)

    from .shared_utils import commit_move, set_unit_coordinates
    from .movement_handlers import _invalidate_all_destination_pools_after_movement

    commit_move(plan, game_state, "charge")  # pose per-modèle + units_charged.add

    entry = require_key(game_state, "units_cache").get(str(unit_id))
    if entry is not None:
        set_unit_coordinates(unit, int(entry["col"]), int(entry["row"]))
    dest_col, dest_row = require_unit_position(unit, game_state)

    _invalidate_all_destination_pools_after_movement(game_state)
    game_state["_unit_move_version"] += 1

    current_turn = game_state["current_turn"] if "current_turn" in game_state else 1
    target_col, target_row = require_unit_position(target_id, game_state)
    charge_message = (
        f"Unit {unit['id']} ({orig_col}, {orig_row}) CHARGED Units {target_ids} "
        f"from ({orig_col}, {orig_row}) to ({dest_col}, {dest_row}) [Roll:{charge_roll}]"
    )
    append_action_log(
        game_state,
        {
            "type": "charge",
            "message": charge_message,
            "turn": current_turn,
            "phase": "charge",
            "unitId": unit["id"],
            "player": unit["player"],
            "fromCol": orig_col,
            "fromRow": orig_row,
            "toCol": dest_col,
            "toRow": dest_row,
            "targetId": target_id,
            "charge_roll": charge_roll,
            "timestamp": "server_time",
            "is_ai_action": unit["player"] == 1,
        },
    )
    add_console_log(game_state, charge_message)

    _apply_charge_impact(game_state, unit, target_id, dest_col, dest_row, target_col, target_row, current_turn)

    if unit_id in game_state["charge_roll_values"]:
        del game_state["charge_roll_values"][unit_id]
    if "charge_target_selections" in game_state and unit_id in game_state["charge_target_selections"]:
        del game_state["charge_target_selections"][unit_id]
    if "pending_charge_targets" in game_state:
        del game_state["pending_charge_targets"]
    if "pending_charge_unit_id" in game_state:
        del game_state["pending_charge_unit_id"]

    charge_clear_preview(game_state)
    result = end_activation(game_state, unit, ACTION, 1, CHARGE, CHARGE, 0)
    result.update(
        {
            "action": "charge",
            "phase": "charge",
            "unitId": unit["id"],
            "targetId": target_id,
            "targetIds": target_ids,
            "fromCol": orig_col,
            "fromRow": orig_row,
            "toCol": dest_col,
            "toRow": dest_row,
            "charge_roll": charge_roll,
            "charge_succeeded": True,
            "activation_complete": True,
        }
    )
    if not game_state["charge_activation_pool"]:
        result.update(charge_phase_end(game_state))
    return True, result


def charge_destination_selection_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Handle charge destination selection and execute charge.

    This is called AFTER target selection and roll (charge_target_selection_handler).
    """
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if "destCol" not in action:
        raise KeyError(f"Action missing required 'destCol' field: {action}")
    if "destRow" not in action:
        raise KeyError(f"Action missing required 'destRow' field: {action}")

    dest_col = action["destCol"]
    dest_row = action["destRow"]

    if dest_col is None or dest_row is None:
        return False, {"error": "missing_destination", "action": "charge"}
    
    # CRITICAL FIX: Normalize destination coordinates to int to ensure type consistency
    # This prevents type mismatch bugs (int vs float vs string) in position comparison
    try:
        dest_col, dest_row = normalize_coordinates(dest_col, dest_row)
    except (ValueError, TypeError):
        return False, {"error": "invalid_destination_type", "destCol": dest_col, "destRow": dest_row, "action": "charge"}

    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id, "action": "charge"}

    # Get target_id and charge_roll from previous step
    if "charge_target_selections" not in game_state or unit_id not in game_state["charge_target_selections"]:
        return False, {"error": "target_not_selected", "unit_id": unit_id, "action": "charge"}
    if "charge_roll_values" not in game_state or unit_id not in game_state["charge_roll_values"]:
        return False, {"error": "charge_roll_missing", "unit_id": unit_id, "action": "charge"}
    
    _stored_targets = game_state["charge_target_selections"][unit_id]
    target_ids = list(_stored_targets) if isinstance(_stored_targets, (list, tuple)) else [_stored_targets]
    target_id = target_ids[0]  # 1ère cible déclarée — pour messages/retours d'affichage
    charge_roll = game_state["charge_roll_values"][unit_id]

    # Verify pool exists and destination is in it
    if "valid_charge_destinations_pool" not in game_state:
        return False, {"error": "destination_pool_not_built", "action": "charge"}
    
    valid_pool = game_state["valid_charge_destinations_pool"]

    resolved_anchor = _resolve_charge_dest_to_anchor(game_state, unit, valid_pool, dest_col, dest_row)
    if resolved_anchor is not None:
        dest_col, dest_row = resolved_anchor

    # Check if destination is in valid pool (reachable with this roll)
    if (dest_col, dest_row) not in valid_pool:
        # Charge roll too low - charge failed
        # Calculate distance for logging
        unit_col, unit_row = require_unit_position(unit, game_state)
        distance_to_dest = _calculate_hex_distance(unit_col, unit_row, dest_col, dest_row)
        
        # Log failure in action_logs
        if "action_logs" not in game_state:
            game_state["action_logs"] = []
        
        if "current_turn" not in game_state:
            current_turn = 1
        else:
            current_turn = game_state["current_turn"]
        
        append_action_log(
            game_state,
            {
                "type": "charge_fail",
                "message": f"Unit {unit['id']} ({unit['col']}, {unit['row']}) FAILED charge to target {target_id} (Roll: {charge_roll}, needed: {distance_to_dest}+)",
                "turn": current_turn,
                "phase": "charge",
                "unitId": unit["id"],
                "player": unit["player"],
                "targetId": target_id,
                "charge_roll": charge_roll,
                "charge_failed": True,
                "timestamp": "server_time",
            },
        )

        # Clear charge roll after use
        if unit_id in game_state["charge_roll_values"]:
            del game_state["charge_roll_values"][unit_id]

        # Clear preview
        charge_clear_preview(game_state)

        # End activation with failure
        result = end_activation(
            game_state, unit,
            PASS,          # Arg1: Pass logging (charge failed)
            1,             # Arg2: +1 step increment (action was attempted)
            PASS,          # Arg3: NO tracking (charge didn't happen)
            CHARGE,        # Arg4: Remove from charge_activation_pool
            0              # Arg5: No error logging
        )

        action_logs_val = game_state["action_logs"] if "action_logs" in game_state else []
        result.update({
            "action": "charge_fail",
            "unitId": unit["id"],
            "targetId": target_id,
            "charge_roll": charge_roll,
            "charge_failed": True,
            "charge_failed_reason": "roll_too_low",
            "start_pos": require_unit_position(unit, game_state),  # Position actuelle (from)
            "end_pos": (dest_col, dest_row),  # Destination prévue (to)
            "activation_complete": True,
            # CRITICAL: Include action_logs in result so they're sent to frontend
            "action_logs": action_logs_val
        })
        
        # Check if pool is now empty after removing this unit
        if not game_state["charge_activation_pool"]:
            phase_end_result = charge_phase_end(game_state)
            result.update(phase_end_result)
        
        return True, result

    # Charge roll is sufficient - execute charge
    # Execute charge using _attempt_charge_to_destination
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled
    _perf = perf_timing_enabled(game_state)
    _ep = game_state.get("episode_number", "?")
    _turn = game_state.get("turn", "?")
    _t_dsel0 = time.perf_counter() if _perf else None
    config = {}
    charge_success, charge_result = _attempt_charge_to_destination(game_state, unit, dest_col, dest_row, target_ids, config)

    if not charge_success:
        # CRITICAL FIX: When charge fails, FORCE action type to charge_fail and add missing fields for proper logging
        # This prevents charge_fail actions from being logged as successful charges
        charge_result["action"] = "charge_fail"
        charge_result.setdefault("unitId", unit["id"])
        charge_result.setdefault("targetId", target_id)  # May be None, but needed for logging
        charge_result.setdefault("charge_failed_reason", charge_result.get("error", "unknown_error"))
        # CRITICAL: Add start_pos and end_pos for proper logging
        if "start_pos" not in charge_result:
            charge_result["start_pos"] = require_unit_position(unit, game_state)  # Position actuelle (from) - unit didn't move
        if "end_pos" not in charge_result:
            charge_result["end_pos"] = (dest_col, dest_row)  # Destination prévue (to) - even though charge failed
        return False, charge_result

    # Extract charge info
    orig_col = charge_result.get("fromCol")
    orig_row = charge_result.get("fromRow")

    # Position already updated by _attempt_charge_to_destination
    # CRITICAL FIX: Normalize types before comparison to prevent false negatives
    unit_col_int, unit_row_int = require_unit_position(unit, game_state)
    if unit_col_int != dest_col or unit_row_int != dest_row:
        return False, {
            "error": "position_update_failed", 
            "action": "charge",
            "expected": (dest_col, dest_row),
            "actual": require_unit_position(unit, game_state),
            "toCol": dest_col,
            "toRow": dest_row,
            "fromCol": orig_col,
            "fromRow": orig_row,
            "unitId": unit["id"]
        }

    # Generate charge log
    if "action_logs" not in game_state:
        game_state["action_logs"] = []

    # Calculate reward (simpler than movement - just charge action)
    action_reward = 0.0
    action_name = "CHARGE"

    # AI_TURN.md COMPLIANCE: Direct field access with validation
    _t_rew0 = time.perf_counter() if _perf else None
    reward_configs = require_key(game_state, "reward_configs")
    global _unit_registry_singleton
    if _unit_registry_singleton is None:
        from ai.unit_registry import UnitRegistry
        _unit_registry_singleton = UnitRegistry()
    scenario_unit_type = require_key(unit, "unitType")
    reward_config_key = _unit_registry_singleton.get_model_key(scenario_unit_type)

    unit_reward_config = require_key(reward_configs, reward_config_key)

    # Base charge reward is required in rewards config
    base_actions = require_key(unit_reward_config, "base_actions")
    action_reward = require_key(base_actions, "charge_success")
    _t_rew1 = time.perf_counter() if _perf else None

    # AI_TURN.md COMPLIANCE: Direct field access for current_turn
    if "current_turn" not in game_state:
        current_turn = 1  # Explicit default for turn counter
    else:
        current_turn = game_state["current_turn"]

    target_col, target_row = require_unit_position(target_id, game_state)
    charge_rule_marker = ""
    charge_ability_display_name = None
    if str(unit["id"]) in require_key(game_state, "units_fled") and _unit_has_rule(unit, "charge_after_flee"):
        source_rule_display_name = _get_source_unit_rule_display_name_for_effect(unit, "charge_after_flee")
        if source_rule_display_name is None:
            raise ValueError(
                f"Unit {unit['id']} charged after flee without source unit rule"
            )
        charge_rule_marker = f" [{source_rule_display_name}]"
        charge_ability_display_name = source_rule_display_name
    elif str(unit["id"]) in require_key(game_state, "units_advanced") and _unit_has_rule(unit, "charge_after_advance"):
        source_rule_display_name = _get_source_unit_rule_display_name_for_effect(unit, "charge_after_advance")
        if source_rule_display_name is None:
            raise ValueError(
                f"Unit {unit['id']} charged after advance without source unit rule"
            )
        charge_rule_marker = f" [{source_rule_display_name}]"
        charge_ability_display_name = source_rule_display_name
    charge_message = (
        f"Unit {unit['id']} ({orig_col}, {orig_row}) CHARGED{charge_rule_marker} "
        f"Unit {target_id} ({target_col}, {target_row}) from ({orig_col}, {orig_row}) "
        f"to ({dest_col}, {dest_row}) [Roll:{charge_roll}]"
    )

    append_action_log(
        game_state,
        {
            "type": "charge",
            "message": charge_message,
            "turn": current_turn,
            "phase": "charge",
            "unitId": unit["id"],
            "player": unit["player"],
            "fromCol": orig_col,
            "fromRow": orig_row,
            "toCol": dest_col,
            "toRow": dest_row,
            "targetId": target_id,
            "charge_roll": charge_roll,
            "ability_display_name": charge_ability_display_name,
            "timestamp": "server_time",
            "action_name": action_name,
            "reward": round(action_reward, 2),
            "is_ai_action": unit["player"] == 1,
        },
    )
    add_console_log(game_state, charge_message)

    _apply_charge_impact(game_state, unit, target_id, dest_col, dest_row, target_col, target_row, current_turn)

    # Clear preview
    charge_clear_preview(game_state)

    # AI_TURN.md EXACT: end_activation(Arg1, Arg2, Arg3, Arg4, Arg5)
    _t_ea0 = time.perf_counter() if _perf else None
    result = end_activation(
        game_state, unit,
        ACTION,        # Arg1: Log action
        1,             # Arg2: +1 step
        CHARGE,        # Arg3: CHARGE tracking
        CHARGE,        # Arg4: Remove from charge_activation_pool
        0              # Arg5: No error logging
    )
    _t_ea1 = time.perf_counter() if _perf else None

    # Update result with charge details
    result.update({
        "action": "charge",
        "phase": "charge",  # For metrics tracking
        "unitId": unit["id"],
        "targetId": target_id,
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col,
        "toRow": dest_row,
        "charge_roll": charge_roll,
        "ability_display_name": charge_ability_display_name,
        "charge_succeeded": True,  # For metrics tracking - successful charge
        "activation_complete": True
    })

    # Check if pool is now empty after removing this unit
    _t_pe0 = time.perf_counter() if _perf else None
    if not game_state["charge_activation_pool"]:
        # Pool empty - phase complete
        phase_end_result = charge_phase_end(game_state)
        result.update(phase_end_result)
    _t_pe1 = time.perf_counter() if _perf else None

    if _perf and _t_dsel0 is not None and _t_rew0 is not None and _t_rew1 is not None and _t_ea0 is not None and _t_ea1 is not None and _t_pe0 is not None and _t_pe1 is not None:
        append_perf_timing_line(
            f"CHARGE_DEST_SEL episode={_ep} turn={_turn} unit_id={unit['id']} "
            f"reward_calc_s={_t_rew1 - _t_rew0:.6f} "
            f"end_activation_s={_t_ea1 - _t_ea0:.6f} "
            f"phase_end_s={_t_pe1 - _t_pe0:.6f} "
            f"total_s={_t_pe1 - _t_dsel0:.6f}"
        )

    return True, result


def _handle_skip_action(game_state: Dict[str, Any], unit: Dict[str, Any], had_valid_destinations: bool = True) -> Tuple[bool, Dict[str, Any]]:
    """
    Handle skip action during charge phase

    Two cases per AI_TURN.md:
    - Line 515: Valid destinations exist, agent chooses wait -> end_activation (WAIT, 1, PASS, CHARGE)
    - Line 518/536: No valid destinations OR cancel -> end_activation (PASS, 0, PASS, CHARGE)
    """
    # Clear charge roll, target selection, and pending targets if unit skips
    if "charge_roll_values" in game_state and unit["id"] in game_state["charge_roll_values"]:
        del game_state["charge_roll_values"][unit["id"]]
    if "charge_target_selections" in game_state and unit["id"] in game_state["charge_target_selections"]:
        del game_state["charge_target_selections"][unit["id"]]
    if "pending_charge_targets" in game_state:
        del game_state["pending_charge_targets"]
    if "pending_charge_unit_id" in game_state:
        del game_state["pending_charge_unit_id"]

    charge_clear_preview(game_state)

    # AI_TURN.md EXACT: Different parameters based on whether valid destinations existed
    if had_valid_destinations:
        # AI_TURN.md Line 515: Agent actively chose to wait (valid destinations available)
        result = end_activation(
            game_state, unit,
            WAIT,          # Arg1: Log wait action
            1,             # Arg2: +1 step increment (action was taken)
            PASS,          # Arg3: NO tracking (wait does not mark as charged)
            CHARGE,        # Arg4: Remove from charge_activation_pool
            0              # Arg5: No error logging
        )
    else:
        # AI_TURN.md Line 518/536/542: No valid destinations or cancel
        result = end_activation(
            game_state, unit,
            PASS,          # Arg1: Pass logging (no action taken)
            0,             # Arg2: NO step increment (no valid choice was made)
            PASS,          # Arg3: NO tracking (no charge happened)
            CHARGE,        # Arg4: Remove from charge_activation_pool
            0              # Arg5: No error logging
        )

    result.update({
        "action": "wait",
        "unitId": unit["id"],
        "activation_complete": True,
        "reset_mode": "select",
        "clear_selected_unit": True
    })

    # Check if pool is now empty after removing this unit
    if not game_state["charge_activation_pool"]:
        # Pool empty - phase complete
        phase_end_result = charge_phase_end(game_state)
        result.update(phase_end_result)

    return True, result


def charge_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Clean up and end charge phase"""
    charge_clear_preview(game_state)

    # Clear all charge rolls (phase complete)
    game_state["charge_roll_values"] = {}

    # Track phase completion reason
    if 'last_compliance_data' not in game_state:
        game_state['last_compliance_data'] = {}
    game_state['last_compliance_data']['phase_end_reason'] = 'eligibility'

    add_console_log(game_state, "CHARGE PHASE COMPLETE")

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    charge_pool = require_key(game_state, "charge_activation_pool")
    add_debug_file_log(game_state, f"[POOL PRE-TRANSITION] E{episode} T{turn} charge charge_activation_pool={charge_pool}")

    return {
        "phase_complete": True,
        "next_phase": "fight",
        "units_processed": len([uid for uid in require_key(game_state, "units_cache").keys() if uid in game_state["units_charged"]])
    }


