#!/usr/bin/env python3
"""
engine/phase_handlers/shared_utils.py - Shared utility functions for phase handlers
Functions used across multiple phase handlers to avoid duplication.
"""

from typing import Dict, List, Tuple, Set, Optional, Any, Union, Callable, cast, TYPE_CHECKING
from dataclasses import dataclass
import copy
import inspect

if TYPE_CHECKING:
    from engine.hex_utils import Socle

from shared.data_validation import require_key
from engine.action_log_utils import append_action_log
from engine.combat_utils import (
    get_unit_coordinates,
    normalize_coordinates,
    calculate_hex_distance,
    get_hex_neighbors,
    expected_dice_value,
    resolve_dice_value,
    get_unit_by_id,
    set_unit_coordinates,
    DiceValue,
)

# end_activation / _handle_shooting_end_activation argument constants (AI_TURN.md)
ACTION = "ACTION"
WAIT = "WAIT"
NO = "NO"
PASS = "PASS"
ERROR = "ERROR"
MOVE = "MOVE"
SHOOTING = "SHOOTING"
CHARGE = "CHARGE"
FIGHT = "FIGHT"
FLED = "FLED"
ADVANCE = "ADVANCE"
NOT_REMOVED = "NOT_REMOVED"


@dataclass(frozen=True)
class ManualAllocCtx:
    """Parametrage du moteur d allocation manuelle des pertes (regles 05.03 / 05.04).

    Mutualise UNIQUEMENT la couche allocation des pertes (groupes, ordre, selection
    de figurine, save check, application des degats). La resolution des jets reste
    specifique a chaque phase (cf. Documentation/refactor_attack_shoot_fight1.md).
    """
    alloc_key: str            # cle game_state de l allocation pending
    declare_order_action: str # action des payloads de declaration d ordre
    manual_alloc_action: str  # action des payloads de choix de figurine
    phase_label: str          # champ "phase" des payloads et logs
    log_type: str             # champ "type" de l action_log
    log_verb: str             # verbe du message de log (ex. "SHOT")
    attacks_left_attr: str    # attribut figurine decremente par intent (SHOOT_LEFT / ATTACK_LEFT)
    intents_key: str          # cle game_state des intents (pending_squad_*_intents)
    # Tir : SHOOT_LEFT = 1 activation -> decrement de 1. Combat : ATTACK_LEFT = nombre
    # d attaques -> decrement du nombre d attaques de l intent (consomme tout).
    decrement_by_attacks: bool = False
    # Hooks d application des degats specifiques a la phase (None = comportement tir pur).
    # on_target_damaged(game_state, target_sid) : appele a chaque blessure infligee.
    # on_unit_destroyed(game_state, target_sid) : appele quand l unite cible est detruite.
    emit_unit_death_log: bool = False
    on_target_damaged: Optional[Callable[[Dict[str, Any], str], None]] = None
    on_unit_destroyed: Optional[Callable[[Dict[str, Any], str], None]] = None
    # Mode mortal wounds (hazard 06.03) : pas d arme, pas de save, degat fixe, log dedie.
    mortal: bool = False
    # Resolution d une blessure du pool (defaut tir : _resolve_one_manual_wound).
    resolve_wound_fn: Optional[Callable[..., None]] = None
    # Emission des logs en fin d allocation (defaut tir : _emit_squad_shoot_log par groupe).
    finalize_log_fn: Optional[Callable[..., None]] = None


SHOOT_CTX = ManualAllocCtx(
    alloc_key="pending_shoot_allocation",
    declare_order_action="squad_shoot_declare_order",
    manual_alloc_action="squad_shoot_manual_alloc",
    phase_label="shoot",
    log_type="shoot",
    log_verb="SHOT",
    attacks_left_attr="SHOOT_LEFT",
    intents_key="pending_squad_shoot_intents",
)


@dataclass(frozen=True)
class DeclareAttackCtx:
    """Parametrage du moteur de DECLARATION offensive (attribution manuelle des
    attaques tir/combat). Jumeau offensif de ManualAllocCtx.

    Mutualise l ossature commune de la declaration per-figurine / per-arme
    (validation, remplacement de cible, resolution NB une seule fois — fix F3).
    Les differences tir vs combat sont injectees : cle intents, attribut d arme
    selectionnee, liste d armes, et callbacks d eligibilite cible.
    """
    intents_key: str          # cle game_state des intents (pending_squad_*_intents)
    selected_weapon_attr: str # attribut figurine de l arme selectionnee (selectedRngWeaponIndex / selectedCcWeaponIndex)
    weapons_key: str          # cle figurine de la liste d armes (RNG_WEAPONS / CC_WEAPONS)
    phase_label: str          # tag debug resolve_dice_value + messages d erreur
    # can_target(game_state, attacker_model, attacker_squad_id, target_squad_id) -> bool
    can_target: Callable[[Dict[str, Any], Dict[str, Any], str, str], bool]
    # can_target_with_weapon(game_state, attacker_model, attacker_squad_id, target_squad_id, weapon_index) -> bool
    can_target_with_weapon: Callable[[Dict[str, Any], Dict[str, Any], str, str, int], bool]

ALLOWED_CHOICE_TIMING_TRIGGERS = {
    "on_deploy",
    "turn_start",
    "player_turn_start",
    "phase_start",
    "activation_start",
}
ALLOWED_CHOICE_TIMING_PHASES = {"command", "move", "shoot", "charge", "fight"}
ALLOWED_CHOICE_TIMING_ACTIVE_PLAYER_SCOPE = {"owner", "opponent", "both"}


def _validate_choice_timing_object(choice_timing: Dict[str, Any], context: str) -> None:
    """Validate one choice_timing object from UNIT_RULES."""
    trigger_value = require_key(choice_timing, "trigger")
    if not isinstance(trigger_value, str) or trigger_value not in ALLOWED_CHOICE_TIMING_TRIGGERS:
        raise ValueError(
            f"{context}: invalid choice_timing.trigger '{trigger_value}'. "
            f"Allowed values: {sorted(ALLOWED_CHOICE_TIMING_TRIGGERS)}"
        )

    if "phase" in choice_timing:
        phase_value = choice_timing["phase"]
        if not isinstance(phase_value, str) or phase_value not in ALLOWED_CHOICE_TIMING_PHASES:
            raise ValueError(
                f"{context}: invalid choice_timing.phase '{phase_value}'. "
                f"Allowed values: {sorted(ALLOWED_CHOICE_TIMING_PHASES)}"
            )
    elif trigger_value in {"phase_start", "activation_start"}:
        raise KeyError(f"{context}: choice_timing.phase is required for trigger '{trigger_value}'")

    if "active_player_scope" in choice_timing:
        active_player_scope_value = choice_timing["active_player_scope"]
        if (
            not isinstance(active_player_scope_value, str)
            or active_player_scope_value not in ALLOWED_CHOICE_TIMING_ACTIVE_PLAYER_SCOPE
        ):
            raise ValueError(
                f"{context}: invalid choice_timing.active_player_scope '{active_player_scope_value}'. "
                f"Allowed values: {sorted(ALLOWED_CHOICE_TIMING_ACTIVE_PLAYER_SCOPE)}"
            )
    elif trigger_value == "phase_start":
        raise KeyError(f"{context}: choice_timing.active_player_scope is required for trigger 'phase_start'")


def rebuild_choice_timing_index(game_state: Dict[str, Any]) -> None:
    """
    Rebuild choice timing index from currently deployed living units.

    Index structure:
    game_state["choice_timing_index"] = {
        "on_deploy": [entry, ...],
        "turn_start": [entry, ...],
        "player_turn_start": [entry, ...],
        "phase_start": [entry, ...],
        "activation_start": [entry, ...],
    }
    """
    units = require_key(game_state, "units")
    if not isinstance(units, list):
        raise TypeError(f"game_state['units'] must be a list, got {type(units).__name__}")

    choice_timing_index: Dict[str, List[Dict[str, Any]]] = {
        trigger: [] for trigger in ALLOWED_CHOICE_TIMING_TRIGGERS
    }
    for unit in units:
        unit_id = str(require_key(unit, "id"))
        unit_player_raw = require_key(unit, "player")
        try:
            unit_player = int(unit_player_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid player for unit {unit_id}: {unit_player_raw!r}") from exc

        # Only index deployed units (active deployment keeps undeployed units at -1,-1).
        unit_col, unit_row = get_unit_coordinates(unit)
        if unit_col < 0 or unit_row < 0:
            continue

        if not is_unit_alive(unit_id, game_state):
            continue

        unit_rules = require_key(unit, "UNIT_RULES")
        if not isinstance(unit_rules, list):
            raise TypeError(f"Unit {unit_id} UNIT_RULES must be list, got {type(unit_rules).__name__}")

        for rule in unit_rules:
            rule_id = require_key(rule, "ruleId")
            display_name = require_key(rule, "displayName")
            if not isinstance(display_name, str) or not display_name.strip():
                raise ValueError(f"Unit {unit_id} rule '{rule_id}' has invalid displayName")

            choice_timing = rule.get("choice_timing")
            if choice_timing is None:
                continue
            if not isinstance(choice_timing, dict):
                raise TypeError(
                    f"Unit {unit_id} rule '{rule_id}' choice_timing must be object, "
                    f"got {type(choice_timing).__name__}"
                )

            _validate_choice_timing_object(choice_timing, f"Unit {unit_id} rule '{rule_id}'")
            trigger_value = require_key(choice_timing, "trigger")

            grants_rule_ids = rule.get("grants_rule_ids")
            if grants_rule_ids is None:
                grants_rule_ids = []
            if not isinstance(grants_rule_ids, list):
                raise TypeError(
                    f"Unit {unit_id} rule '{rule_id}' grants_rule_ids must be list, "
                    f"got {type(grants_rule_ids).__name__}"
                )
            usage_value = rule.get("usage")
            if usage_value is not None:
                if not isinstance(usage_value, str) or usage_value not in {"and", "or", "unique", "always"}:
                    raise ValueError(
                        f"Unit {unit_id} rule '{rule_id}' has invalid usage '{usage_value}'"
                    )

            entry = {
                "unit_id": unit_id,
                "unit_player": unit_player,
                "rule_id": rule_id,
                "display_name": display_name.strip(),
                "grants_rule_ids": [str(rule_ref) for rule_ref in grants_rule_ids],
                "usage": usage_value,
                "choice_timing": dict(choice_timing),
            }
            choice_timing_index[trigger_value].append(entry)

    game_state["choice_timing_index"] = choice_timing_index


# =============================================================================
# UNITS_CACHE - Single source of truth for position, HP, player of living units
# =============================================================================

def _compute_unit_occupied_hexes(
    col: int, row: int, unit: Dict[str, Any],
    game_state: Optional[Dict[str, Any]] = None,
) -> Set[Tuple[int, int]]:
    """Compute occupied_hexes for a unit based on its BASE_SHAPE and BASE_SIZE.

    Multi-hex footprints are only computed on Board ×10 (engagement_zone > 1).
    On legacy boards (engagement_zone=1), all units occupy a single cell.
    """
    if game_state is None:
        return {(col, row)}
    ez = get_engagement_zone(game_state)
    if ez <= 1:
        return {(col, row)}
    base_shape = unit["BASE_SHAPE"]
    base_size = unit["BASE_SIZE"]
    if "orientation" in unit:
        orientation = int(require_key(unit, "orientation"))
    else:
        orientation = 0
    if base_size == 1:
        return {(col, row)}
    from engine.hex_utils import compute_occupied_hexes
    return compute_occupied_hexes(col, row, base_shape, base_size, orientation)


def build_occupied_positions_set(
    game_state: Dict[str, Any],
    exclude_unit_id: Optional[str] = None,
) -> Set[Tuple[int, int]]:
    """Build set of all cells occupied by living units (full footprints).

    Uses occupied_hexes from units_cache for multi-hex units.
    For single-hex units, equivalent to {(col, row)} per unit.

    Args:
        game_state: Game state with units_cache
        exclude_unit_id: Optional unit to exclude (e.g. the moving unit)

    Returns:
        Set of (col, row) cells occupied by other units
    """
    units_cache = require_key(game_state, "units_cache")
    occupied: Set[Tuple[int, int]] = set()
    for uid, entry in units_cache.items():
        if uid == exclude_unit_id:
            continue
        occ = entry.get("occupied_hexes")
        if occ:
            occupied.update(occ)
        else:
            occupied.add((require_key(entry, "col"), require_key(entry, "row")))
    return occupied


def build_enemy_occupied_positions_set(
    game_state: Dict[str, Any],
    *,
    current_player: int,
) -> Set[Tuple[int, int]]:
    """Cells occupied by opposing players' units (full footprints)."""
    units_cache = require_key(game_state, "units_cache")
    current_player_int = int(current_player)
    occupied: Set[Tuple[int, int]] = set()
    for uid, entry in units_cache.items():
        player_raw = require_key(entry, "player")
        if int(player_raw) == current_player_int:
            continue
        occ = entry.get("occupied_hexes")
        if occ:
            occupied.update(occ)
        else:
            occupied.add((require_key(entry, "col"), require_key(entry, "row")))
    return occupied


def compute_candidate_footprint(
    center_col: int, center_row: int,
    unit_or_stub: Dict[str, Any],
    game_state: Dict[str, Any],
) -> Set[Tuple[int, int]]:
    """Compute occupied_hexes for a unit placed at a candidate center position.

    For single-hex units or legacy boards (engagement_zone <= 1), returns {(center_col, center_row)}.
    For multi-hex units on x10 boards, computes the full round/oval/square footprint.

    Args:
        center_col, center_row: Candidate center position
        unit_or_stub: Dict with BASE_SHAPE and BASE_SIZE keys
        game_state: Game state (used to detect x10 mode via engagement_zone)

    Returns:
        Set of (col, row) cells forming the footprint
    """
    return _compute_unit_occupied_hexes(center_col, center_row, unit_or_stub, game_state)


def is_footprint_placement_valid(
    candidate_hexes: Set[Tuple[int, int]],
    game_state: Dict[str, Any],
    occupied_positions: Set[Tuple[int, int]],
    enemy_adjacent_hexes: Optional[Set[Tuple[int, int]]] = None,
) -> bool:
    """Check if all cells of a candidate footprint are valid for placement.

    Validates: within board bounds, not a wall, not occupied by another unit.
    Optionally checks that no cell falls within the enemy engagement zone.

    Args:
        candidate_hexes: Set of (col, row) for the candidate footprint
        game_state: With board_cols, board_rows, wall_hexes
        occupied_positions: Pre-computed set of occupied cells
        enemy_adjacent_hexes: If provided, also blocks cells in enemy engagement zone

    Returns:
        True if ALL cells pass every check
    """
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())
    # Bounds check (must iterate — no way to vectorize without numpy)
    for c, r in candidate_hexes:
        if c < 0 or r < 0 or c >= board_cols or r >= board_rows:
            return False
    # Set-intersection checks are implemented in C and much faster than Python loops
    if wall_hexes and (candidate_hexes & wall_hexes):
        return False
    if occupied_positions and (candidate_hexes & occupied_positions):
        return False
    if enemy_adjacent_hexes is not None and (candidate_hexes & enemy_adjacent_hexes):
        return False
    return True


def candidate_overlaps_any_unit(
    game_state: Dict[str, Any],
    candidate: "Socle",
    exclude_unit_id: Optional[str] = None,
) -> bool:
    """True si le socle ``candidate`` chevauche celui d'une autre unité vivante.

    Test unifié (``hex_utils.footprints_overlap``) : ronde↔ronde en clearance euclidien
    continu (exact), toute paire impliquant un non-rond en méthode empreinte. ``candidate.fp``
    doit être fourni dès que ``candidate`` ou un voisin est non rond. ``exclude_unit_id`` :
    l'unité en mouvement, exclue d'elle-même.

    Ne teste QUE le chevauchement entre unités — les bornes plateau et les murs restent à la
    charge de ``is_footprint_placement_valid`` (discret, inchangé).
    """
    from engine.hex_utils import Socle, footprints_overlap

    units_cache = require_key(game_state, "units_cache")
    for uid, entry in units_cache.items():
        if exclude_unit_id is not None and str(uid) == str(exclude_unit_id):
            continue
        e_col = require_key(entry, "col")
        e_row = require_key(entry, "row")
        occ = entry.get("occupied_hexes")
        e_fp = set(occ) if occ else {(e_col, e_row)}
        neighbor = Socle(
            shape=require_key(entry, "BASE_SHAPE"),
            base_size=require_key(entry, "BASE_SIZE"),
            col=e_col,
            row=e_row,
            fp=e_fp,
        )
        if footprints_overlap(candidate, neighbor):
            return True
    return False


def is_placement_valid_with_clearance(
    game_state: Dict[str, Any],
    candidate_fp: Set[Tuple[int, int]],
    *,
    shape: str,
    base_size: "int | list[int]",
    col: int,
    row: int,
    exclude_unit_id: Optional[str] = None,
    enemy_adjacent_hexes: Optional[Set[Tuple[int, int]]] = None,
) -> bool:
    """Placement légal = bornes + murs (discret, inchangé) ET aucun chevauchement de socle.

    Le volet bornes/murs reste ``is_footprint_placement_valid`` (avec ``occupied_positions``
    vide : le chevauchement n'est plus testé par cellules ici). Le chevauchement entre unités
    passe par ``candidate_overlaps_any_unit`` (clearance continu rond↔rond, méthode empreinte).
    Remplace 1:1 le couple ``build_occupied_positions_set`` + ``is_footprint_placement_valid``.
    """
    if not is_footprint_placement_valid(candidate_fp, game_state, set(), enemy_adjacent_hexes):
        return False
    from engine.hex_utils import Socle

    cand = Socle(shape=shape, base_size=base_size, col=col, row=row, fp=candidate_fp)
    if candidate_overlaps_any_unit(game_state, cand, exclude_unit_id=exclude_unit_id):
        return False
    return True


# Roles d allocation defensive (rule 05.04) : ordre de sacrifice croissant.
# base (None) < special_weapon < sergeant < support < leader. Les characters
# (support/leader) passent toujours apres les non-characters par cet ordre.
ROLE_TIER: Dict[str, int] = {"special_weapon": 1, "sergeant": 2, "support": 3, "leader": 4}


def _derive_model_role(unit_rules: List[Dict[str, Any]]) -> Optional[str]:
    """Role d allocation d une figurine, derive de ses UNIT_RULES.

    Retourne le ruleId de role ("special_weapon"/"sergeant"/"support"/"leader")
    ou None (figurine de base). Erreur explicite si plusieurs roles distincts
    (faute de donnees, pas un cas metier).
    """
    roles = {
        r["ruleId"] for r in unit_rules
        if isinstance(r, dict) and r.get("ruleId") in ROLE_TIER
    }
    if len(roles) > 1:
        raise ValueError(f"Figurine avec roles d allocation conflictuels: {sorted(roles)}")
    return next(iter(roles)) if roles else None


def _build_models_for_unit(
    unit: Dict[str, Any],
    unit_id: str,
    unit_col: int,
    unit_row: int,
    unit_hp_cur: int,
    unit_player: int,
    models_cache: Dict[str, Dict[str, Any]],
    squad_models: Dict[str, List[str]],
) -> None:
    """Build per-model entries for one squad (squad.md PR1 1b).

    For mono-figurine units (no explicit unit["models"] list), create exactly
    one model entry derived from the unit's own fields. For multi-figurine
    squads (unit["models"] declared), iterate and build one entry per fig.

    Maintains parallel structures models_cache (model_id -> dict) and
    squad_models (squad_id -> [model_id,...]) without touching units_cache.

    points_per_hp formula (homogeneous):
        VALUE / (model_count_at_start * HP_MAX)
    Mixed profiles (per spec, when models[] declares heterogeneous HP_MAX):
        VALUE / total_hp_pool, total_hp_pool = sum(HP_MAX_i for i in models)
    """
    hp_max = int(require_key(unit, "HP_MAX"))
    if hp_max <= 0:
        raise ValueError(f"Unit {unit_id} has invalid HP_MAX: {hp_max}")
    value = int(require_key(unit, "VALUE"))
    oc = int(require_key(unit, "OC"))
    t_stat = int(require_key(unit, "T"))
    armor_save = int(require_key(unit, "ARMOR_SAVE"))
    invul_save_raw = require_key(unit, "INVUL_SAVE")
    # Sentinel convention: INVUL_SAVE = 7 means "no invul save" (aligned with
    # observation_builder.py:1332 has_invul = invul_save < 7). Accept 0 in
    # legacy data and convert to 7.
    invul_save = int(invul_save_raw) if int(invul_save_raw) > 0 else 7
    shoot_left = int(require_key(unit, "SHOOT_LEFT"))
    attack_left = int(require_key(unit, "ATTACK_LEFT"))
    rng_weapons = require_key(unit, "RNG_WEAPONS")
    cc_weapons = require_key(unit, "CC_WEAPONS")
    selected_rng = unit.get("selectedRngWeaponIndex")
    selected_cc = unit.get("selectedCcWeaponIndex")

    explicit_models = unit.get("models")
    if isinstance(explicit_models, list) and len(explicit_models) > 0:
        # Multi-figurine squad with explicit positions.
        model_specs = explicit_models
    else:
        # Backward compat: single-figurine squad derived from unit fields.
        model_specs = [{"col": unit_col, "row": unit_row, "HP_CUR": unit_hp_cur}]

    model_count_at_start = len(model_specs)
    # points_per_hp — homogeneous case (all models share unit HP_MAX). For
    # mixed profiles (future), each spec carries its own HP_MAX and the formula
    # becomes VALUE / sum(HP_MAX_i).
    total_hp_pool = 0
    for spec in model_specs:
        spec_hp_max = int(spec.get("HP_MAX", hp_max))
        if spec_hp_max <= 0:
            raise ValueError(f"Squad {unit_id}: model spec has invalid HP_MAX={spec_hp_max}")
        total_hp_pool += spec_hp_max
    points_per_hp = float(value) / float(total_hp_pool) if total_hp_pool > 0 else 0.0

    model_ids: List[str] = []
    for idx, spec in enumerate(model_specs):
        model_id = f"{unit_id}#{idx}"
        model_ids.append(model_id)
        spec_col, spec_row = normalize_coordinates(
            int(require_key(spec, "col")), int(require_key(spec, "row"))
        )
        spec_hp_max = int(spec.get("HP_MAX", hp_max))
        spec_hp_cur = int(spec.get("HP_CUR", spec_hp_max))
        spec_role = _derive_model_role(cast(List[Dict[str, Any]], spec.get("UNIT_RULES", require_key(unit, "UNIT_RULES"))))
        models_cache[model_id] = {
            "squad_id": unit_id,
            "unitType": spec.get("unit_type") or unit.get("unitType"),
            "role": spec_role,
            "col": spec_col,
            "row": spec_row,
            "DISPLAY_NAME": spec.get("DISPLAY_NAME", unit.get("DISPLAY_NAME")),
            "ICON": spec.get("ICON", unit.get("ICON")),
            "ICON_SCALE": spec.get("ICON_SCALE", unit.get("ICON_SCALE")),
            "BASE_SHAPE": spec.get("BASE_SHAPE", unit.get("BASE_SHAPE")),
            "BASE_SIZE": spec.get("BASE_SIZE", unit.get("BASE_SIZE")),
            "HP_CUR": spec_hp_cur,
            "HP_MAX": spec_hp_max,
            "player": unit_player,
            "SHOOT_LEFT": shoot_left,
            "ATTACK_LEFT": attack_left,
            "OC": int(spec.get("OC", oc)),
            "points_per_hp": points_per_hp,
            "ARMOR_SAVE": int(spec.get("ARMOR_SAVE", armor_save)),
            "INVUL_SAVE": int(spec.get("INVUL_SAVE", invul_save)),
            "T": int(spec.get("T", t_stat)),
            "RNG_WEAPONS": copy.deepcopy(spec.get("RNG_WEAPONS", rng_weapons)),
            "CC_WEAPONS": copy.deepcopy(spec.get("CC_WEAPONS", cc_weapons)),
            "selectedRngWeaponIndex": spec.get("selectedRngWeaponIndex", selected_rng),
            "selectedCcWeaponIndex": spec.get("selectedCcWeaponIndex", selected_cc),
        }
    squad_models[unit_id] = model_ids


def build_units_cache(game_state: Dict[str, Any]) -> None:
    """
    Build units_cache from game_state["units"].

    Creates game_state["units_cache"]: Dict[str, Dict] mapping unit_id (str) to
    {"col": int, "row": int, "HP_CUR": int, "player": int, "BASE_SHAPE": str,
     "BASE_SIZE": int|list, "orientation": int, "occupied_hexes": Set[(col,row)]}
    for all units in game_state["units"].
    During gameplay, dead units are removed from cache (update_units_cache_hp calls remove_from_units_cache when HP <= 0).
    
    Also builds game_state["occupation_map"]: Dict[(col,row), unit_id] for cell→unit lookup.
    
    Called ONCE at reset() after units are initialized. Not called at phase start.
    
    Args:
        game_state: Game state with "units" list
        
    Returns:
        None (updates game_state["units_cache"] and game_state["occupation_map"])
    """
    if "units" not in game_state:
        raise KeyError("game_state must have 'units' field to build units_cache")

    units_cache: Dict[str, Dict[str, Any]] = {}
    occupation_map: Dict[Tuple[int, int], str] = {}
    models_cache: Dict[str, Dict[str, Any]] = {}
    squad_models: Dict[str, List[str]] = {}

    for unit in game_state["units"]:
        hp_cur_raw = require_key(unit, "HP_CUR")
        try:
            hp_cur = max(0, int(float(hp_cur_raw)))
        except (ValueError, TypeError):
            raise ValueError(f"Unit {unit.get('id')} has invalid HP_CUR: {hp_cur_raw!r}") from None

        unit_id = str(require_key(unit, "id"))
        col, row = get_unit_coordinates(unit)  # Already normalizes
        # Invariant multi-fig : l'ancre (col/row niveau-unité) DOIT coïncider avec
        # la position de la 1ère figurine (models[0]). Une donnée incohérente (ex.
        # typo de saisie sur le col/row d'unité) désynchronise l'ancre de l'empreinte
        # réelle et fausse silencieusement toute fonction lisant l'ancre. Erreur
        # explicite plutôt que correction silencieuse.
        _explicit_models = unit.get("models")
        if isinstance(_explicit_models, list) and len(_explicit_models) > 0:
            _m0_col, _m0_row = normalize_coordinates(
                int(require_key(_explicit_models[0], "col")),
                int(require_key(_explicit_models[0], "row")),
            )
            if (_m0_col, _m0_row) != (col, row):
                raise ValueError(
                    f"Unit {unit_id}: anchor col/row=({col},{row}) ne correspond pas à "
                    f"models[0]=({_m0_col},{_m0_row}). Corriger le col/row de l'unité dans "
                    f"le scénario (il doit égaler la position de la 1ère figurine)."
                )
        player_raw = require_key(unit, "player")
        try:
            player = int(player_raw)
        except (ValueError, TypeError):
            raise ValueError(f"Unit {unit_id} has invalid player: {player_raw!r}") from None

        base_shape = unit["BASE_SHAPE"]
        base_size = unit["BASE_SIZE"]
        if "orientation" in unit:
            orientation = int(require_key(unit, "orientation"))
        else:
            orientation = 0
        occupied = _compute_unit_occupied_hexes(col, row, unit, game_state)

        units_cache[unit_id] = {
            "col": col,
            "row": row,
            "HP_CUR": hp_cur,
            "player": player,
            # VALUE (points) : source de verite reward, requis par resolve_squad_shoot
            # / resolve_squad_fight. Present sur chaque unit (deja require_key dans
            # _build_models_for_unit).
            "VALUE": int(require_key(unit, "VALUE")),
            "BASE_SHAPE": base_shape,
            "BASE_SIZE": base_size,
            "orientation": orientation,
            "occupied_hexes": occupied,
            # PR4 4e-i : ajout dict parallele {model_id: (col, row)}.
            # Source de verite per-figurine pour le pipeline squad. Construit dans
            # la passe model_cache ci-dessous (apres _build_models_for_unit).
            # Initialise vide ici, rempli juste apres.
            "occupied_hexes_by_model": {},
        }

        for cell in occupied:
            occupation_map[cell] = unit_id

        # ====================================================================
        # MODEL-LEVEL CACHE (squad.md PR1 1b)
        # ====================================================================
        # Build models_cache + squad_models in parallel to units_cache.
        # Backward compat: if unit has no explicit "models" list, treat it as
        # a single-figurine squad (1 unit = 1 model).
        # Multi-figurine squads (future) declare unit["models"] = [{col,row,...},...].
        _build_models_for_unit(
            unit=unit,
            unit_id=unit_id,
            unit_col=col,
            unit_row=row,
            unit_hp_cur=hp_cur,
            unit_player=player,
            models_cache=models_cache,
            squad_models=squad_models,
        )
        # Fill occupied_hexes_by_model from models_cache (PR4 4e-i)
        units_cache[unit_id]["occupied_hexes_by_model"] = {
            mid: (int(models_cache[mid]["col"]), int(models_cache[mid]["row"]))
            for mid in squad_models.get(unit_id, [])  # get allowed
            if mid in models_cache
        }
        # Per-model visual meta (icône + échelle + forme/taille de base) : exposé
        # au frontend uniquement pour les escouades hétérogènes (au moins une
        # figurine dont le profil visuel diffère de l'unité parente, ex.
        # Sergeant / personnage attaché). Sinon le frontend retombe sur l'unité.
        unit_meta = {
            "DISPLAY_NAME": unit.get("DISPLAY_NAME"),
            "ICON": unit.get("ICON"),
            "ICON_SCALE": unit.get("ICON_SCALE"),
            "BASE_SHAPE": unit.get("BASE_SHAPE"),
            "BASE_SIZE": unit.get("BASE_SIZE"),
            # role de la figurine (leader/support/sergeant/special_weapon/None) :
            # exposé au frontend pour le tri d'affichage du menu de déploiement.
            "role": _derive_model_role(require_key(unit, "UNIT_RULES")),
        }
        models_meta = {
            mid: {
                "DISPLAY_NAME": models_cache[mid]["DISPLAY_NAME"],
                "ICON": models_cache[mid]["ICON"],
                "ICON_SCALE": models_cache[mid]["ICON_SCALE"],
                "BASE_SHAPE": models_cache[mid]["BASE_SHAPE"],
                "BASE_SIZE": models_cache[mid]["BASE_SIZE"],
                "role": models_cache[mid]["role"],
            }
            for mid in squad_models.get(unit_id, [])  # get allowed
            if mid in models_cache
        }
        if any(meta != unit_meta for meta in models_meta.values()):
            units_cache[unit_id]["models_meta_by_model"] = models_meta
        # F2 fix (audit) : pour multi-fig, recompute occupied_hexes = union des
        # footprints de toutes les figs. Pour mono-fig (1 fig au anchor),
        # occupied_hexes deja correct depuis _compute_unit_occupied_hexes(col,row,...).
        if len(squad_models.get(unit_id, [])) > 1:  # get allowed
            # game_state["units_cache"] pas encore set globalement, on patch via la variable locale
            game_state_view = dict(game_state)
            game_state_view["units_cache"] = units_cache
            game_state_view["models_cache"] = models_cache
            game_state_view["squad_models"] = squad_models
            game_state_view["occupation_map"] = occupation_map
            _recompute_squad_occupied_hexes(game_state_view, unit_id)

    game_state["units_cache"] = units_cache
    game_state["occupation_map"] = occupation_map
    game_state["models_cache"] = models_cache
    game_state["squad_models"] = squad_models

    # squad_cache: built APRES models_cache + squad_models (depend des deux).
    # model_count_at_start est capture maintenant et ne changera plus.
    squad_cache: Dict[str, Dict[str, Any]] = {}
    for squad_id in squad_models:
        entry = _compute_squad_cache_entry(game_state, squad_id)
        entry["model_count_at_start"] = entry["model_count"]
        squad_cache[squad_id] = entry
        # Mirror OC_TOTAL into units_cache (squad.md PR1 1d): observation_builder
        # et logique d'objectifs lisent l'OC agrege depuis units_cache.
        if squad_id in units_cache:
            units_cache[squad_id]["OC_TOTAL"] = entry["oc_total"]
    game_state["squad_cache"] = squad_cache

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    phase = game_state.get("phase", "?")
    add_debug_file_log(game_state, f"[UNITS_CACHE BUILD] E{episode} T{turn} {phase} units_cache built with {len(units_cache)} units, occupation_map={len(occupation_map)} cells")


def _update_occupation_map(
    game_state: Dict[str, Any],
    unit_id: str,
    old_entry: Optional[Dict[str, Any]],
    new_occupied: Optional[Set[Tuple[int, int]]],
) -> None:
    """Incrementally update game_state["occupation_map"] when a unit moves or dies.

    Removes old cells, adds new cells. Skips if occupation_map not yet built.
    """
    occ_map = game_state.get("occupation_map")
    if occ_map is None:
        return
    if old_entry is not None:
        for cell in old_entry.get("occupied_hexes", set()):
            if occ_map.get(cell) == unit_id:
                del occ_map[cell]
    if new_occupied is not None:
        for cell in new_occupied:
            occ_map[cell] = unit_id


def update_units_cache_unit(
    game_state: Dict[str, Any],
    unit_id: str,
    col: int,
    row: int,
    hp_cur: int,
    player: int
) -> None:
    """
    Update or insert a unit entry in units_cache.
    
    If hp_cur <= 0, removes the entry (unit dead; single source of truth).
    Coordinates are normalized before storage.
    
    Args:
        game_state: Game state with "units_cache"
        unit_id: Unit ID (str)
        col: Column coordinate
        row: Row coordinate
        hp_cur: Current HP (0 for dead)
        player: Player number (1 or 2)
        
    Returns:
        None (updates game_state["units_cache"])
    """
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist before updating (call build_units_cache at reset)")
    
    # Normalize coordinates
    norm_col, norm_row = normalize_coordinates(col, row)
    effective_hp = max(0, int(hp_cur))
    
    # Update or insert (if hp_cur <= 0, remove instead)
    if effective_hp <= 0:
        remove_from_units_cache(game_state, unit_id)
        return
    
    old_entry = game_state["units_cache"].get(unit_id)
    if old_entry is None:
        raise KeyError(f"Unit {unit_id} not found in units_cache — cannot update HP for unknown unit")
    base_shape = old_entry["BASE_SHAPE"]
    base_size = old_entry["BASE_SIZE"]
    if old_entry and "orientation" in old_entry:
        orient_val = int(require_key(old_entry, "orientation"))
    else:
        orient_val = 0
    unit_stub = {
        "BASE_SHAPE": base_shape,
        "BASE_SIZE": base_size,
        "orientation": orient_val,
    }
    new_occupied = _compute_unit_occupied_hexes(norm_col, norm_row, unit_stub, game_state)
    
    _update_occupation_map(game_state, unit_id, old_entry, new_occupied)
    
    game_state["units_cache"][unit_id] = {
        "col": norm_col,
        "row": norm_row,
        "HP_CUR": effective_hp,
        "player": player,
        "BASE_SHAPE": base_shape,
        "BASE_SIZE": base_size,
        "orientation": orient_val,
        "occupied_hexes": new_occupied,
    }


def _remove_unit_from_all_activation_pools(game_state: Dict[str, Any], unit_id_str: str) -> None:
    """
    Remove a unit from all activation pools (move, shoot, charge, fight).
    Called when unit dies so pools never contain dead units (single source of truth).
    """
    for pool_key in (
        "move_activation_pool",
        "shoot_activation_pool",
        "charge_activation_pool",
        "charging_activation_pool",
        "active_alternating_activation_pool",
        "non_active_alternating_activation_pool",
    ):
        if pool_key in game_state and game_state[pool_key] is not None:
            game_state[pool_key] = [uid for uid in game_state[pool_key] if str(uid) != unit_id_str]


def remove_from_units_cache(game_state: Dict[str, Any], unit_id: str) -> None:
    """
    Remove a unit from units_cache (e.g. when unit dies: HP_CUR -> 0).
    
    Dead = absent from cache (single source of truth). Call from update_units_cache_hp when HP <= 0.
    Also removes the unit from all activation pools so pools never contain dead units.
    No-op if unit_id is not in cache.
    
    Args:
        game_state: Game state with "units_cache"
        unit_id: Unit ID (str) to remove
        
    Returns:
        None (updates game_state["units_cache"] and activation pools)
    """
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist before removing (call build_units_cache at reset)")
    
    entry = game_state["units_cache"].get(unit_id)
    if entry is not None:
        removed_col = require_key(entry, "col")
        removed_row = require_key(entry, "row")
        removed_player = require_key(entry, "player")
        removed_col_int, removed_row_int = normalize_coordinates(removed_col, removed_row)
        removed_player_int = int(removed_player)

        _update_occupation_map(game_state, unit_id, entry, None)

        removed_occupied = entry.get("occupied_hexes")
        update_enemy_adjacent_caches_after_unit_removed(
            game_state,
            removed_unit_player=removed_player_int,
            old_col=removed_col_int,
            old_row=removed_row_int,
            old_occupied=removed_occupied,
        )

        from engine.game_utils import add_debug_file_log
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "?")
        add_debug_file_log(
            game_state,
            f"[UNITS_CACHE REMOVE] E{episode} T{turn} {phase} unit_id={unit_id} "
            f"pos=({entry.get('col')},{entry.get('row')}) HP_CUR={entry.get('HP_CUR')} player={entry.get('player')}"
        )
    game_state["units_cache"].pop(unit_id, None)
    _remove_unit_from_all_activation_pools(game_state, str(unit_id))


def get_unit_from_cache(unit_id: str, game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Get unit entry from units_cache.
    
    Args:
        unit_id: Unit ID (str)
        game_state: Game state with "units_cache"
        
    Returns:
        Dict with {"col", "row", "HP_CUR", "player"} if unit is in cache, None otherwise.
        Dead units are removed from cache (absent).
    """
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist (call build_units_cache at reset)")
    
    return game_state["units_cache"].get(unit_id)


def is_unit_alive(unit_id: str, game_state: Dict[str, Any]) -> bool:
    """
    Check if a unit is alive (present in units_cache).
    
    units_cache contains ONLY living units; dead units are removed at end of action.
    
    Args:
        unit_id: Unit ID (str)
        game_state: Game state with "units_cache"
        
    Returns:
        True if unit is in cache, False otherwise
    """
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist (call build_units_cache at reset)")
    
    return game_state["units_cache"].get(unit_id) is not None


def _get_unit_position_from_cache(unit_id: str, game_state: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """
    Internal: get unit position from units_cache by unit_id.
    Use get_unit_position() for the public API.
    """
    entry = get_unit_from_cache(unit_id, game_state)
    if entry is None:
        return None
    return (entry["col"], entry["row"])


def get_unit_position(
    unit_or_id: Union[str, int, Dict[str, Any]], game_state: Dict[str, Any]
) -> Optional[Tuple[int, int]]:
    """
    Get current position of a unit from units_cache (single source of truth).
    Use this for any game logic that needs unit position when game_state is available.

    Args:
        unit_or_id: Unit ID (str or int) or unit dict (must have "id").
        game_state: Game state with "units_cache".

    Returns:
        (col, row) if unit is in cache, None if unit not in cache (e.g. dead/removed).

    Raises:
        ValueError: If unit_or_id is a dict without "id" (e.g. units_cache entry passed by mistake).
    """
    if isinstance(unit_or_id, dict):
        if "id" not in unit_or_id:
            raise ValueError(
                "get_unit_position received a dict without 'id' (possibly a units_cache entry). "
                "Pass a unit dict with 'id' or a unit ID (str/int)."
            )
        unit_id = str(require_key(unit_or_id, "id"))
    else:
        unit_id = str(unit_or_id)
    return _get_unit_position_from_cache(unit_id, game_state)


def require_unit_position(
    unit_or_id: Union[str, int, Dict[str, Any]], game_state: Dict[str, Any]
) -> Tuple[int, int]:
    """
    Get current position of a unit from units_cache; raises if unit not in cache.
    Use when the unit is required to be present (e.g. shooter, active unit).

    Returns:
        (col, row)

    Raises:
        ValueError: If unit not in units_cache (dead/absent).
    """
    pos = get_unit_position(unit_or_id, game_state)
    if pos is None:
        uid = str(unit_or_id.get("id", unit_or_id)) if isinstance(unit_or_id, dict) else str(unit_or_id)
        raise ValueError(f"Unit {uid} not in units_cache (dead or absent); cannot read position")
    return pos


def update_units_cache_position(game_state: Dict[str, Any], unit_id: str, col: int, row: int) -> None:
    """
    Update only the position of a unit in units_cache.
    
    Convenience function for use after set_unit_coordinates.
    Retrieves HP_CUR and player from existing entry.
    
    Args:
        game_state: Game state with "units_cache"
        unit_id: Unit ID (str)
        col: New column coordinate
        row: New row coordinate
        
    Returns:
        None (updates game_state["units_cache"])
    """
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist (call build_units_cache at reset)")
    
    entry = game_state["units_cache"].get(unit_id)
    if entry is None:
        return
    
    old_col = entry.get("col")
    old_row = entry.get("row")

    norm_col, norm_row = normalize_coordinates(col, row)
    
    if "orientation" in entry:
        orient_val = int(require_key(entry, "orientation"))
    else:
        orient_val = 0
    unit_stub = {
        "BASE_SHAPE": entry["BASE_SHAPE"],
        "BASE_SIZE": entry["BASE_SIZE"],
        "orientation": orient_val,
    }
    new_occupied = _compute_unit_occupied_hexes(norm_col, norm_row, unit_stub, game_state)
    _update_occupation_map(game_state, unit_id, entry, new_occupied)
    
    entry["col"] = norm_col
    entry["row"] = norm_row
    entry["occupied_hexes"] = new_occupied

    if game_state.get("debug_mode", False):
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "?")
        caller = inspect.stack()[1].function
        from engine.game_utils import add_debug_file_log
        add_debug_file_log(
            game_state,
            f"[UNITS_CACHE POSITION_UPDATE] E{episode} T{turn} {phase} unit_id={unit_id} "
            f"old=({old_col},{old_row}) new=({norm_col},{norm_row}) caller={caller}"
        )


def get_hp_from_cache(unit_id: str, game_state: Dict[str, Any]) -> Optional[int]:
    """
    Get current HP of a unit from units_cache (Phase 2: single source of truth for HP_CUR).
    
    units_cache contains ONLY living units; dead units are removed. Returns None if unit not in cache.
    
    Returns:
        HP value if unit is in cache, None if unit not in cache (dead or absent).
    """
    entry = get_unit_from_cache(str(unit_id), game_state)
    if entry is None:
        return None
    return require_key(entry, "HP_CUR")


def require_hp_from_cache(unit_id: str, game_state: Dict[str, Any]) -> int:
    """
    Return current HP for a unit that must be alive (in units_cache).
    Raises ValueError if unit is dead or absent.
    """
    hp = get_hp_from_cache(str(unit_id), game_state)
    if hp is None:
        raise ValueError(f"Unit {unit_id} not in units_cache (dead or absent); cannot read HP_CUR")
    return hp


def update_units_cache_hp(game_state: Dict[str, Any], unit_id: str, new_hp_cur: int) -> None:
    """
    Single write path for HP_CUR during gameplay: updates units_cache only (Phase 2).
    
    Use this as the ONLY write path for HP_CUR during gameplay (shooting, fight).
    At reset, HP_CUR is initialised from definitions; build_units_cache reads from units.
    
    units_cache contains ONLY living units. If new_hp_cur <= 0, unit is removed from cache
    immediately (end of action).
    
    Args:
        game_state: Game state with "units_cache"
        unit_id: Unit ID (str)
        new_hp_cur: New HP value (will be clamped to >= 0)
        
    Returns:
        None (updates game_state["units_cache"] only)
    """
    require_key(game_state, "units_cache")
    
    effective_hp = max(0, int(new_hp_cur))
    unit_id_str = str(unit_id)
    
    entry = game_state["units_cache"].get(unit_id_str)
    if entry is None:
        return
    game_state.pop("_cached_best_enemy_score", None)
    game_state.pop("_cached_best_enemy_global", None)
    if effective_hp <= 0:
        from engine.game_utils import add_debug_file_log
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "?")
        add_debug_file_log(
            game_state,
            f"[UNITS_CACHE HP_UPDATE] E{episode} T{turn} {phase} unit_id={unit_id_str} "
            f"old_hp={entry.get('HP_CUR')} new_hp={effective_hp} -> REMOVE"
        )
        remove_from_units_cache(game_state, unit_id_str)
    else:
        from engine.game_utils import add_debug_file_log
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "?")
        add_debug_file_log(
            game_state,
            f"[UNITS_CACHE HP_UPDATE] E{episode} T{turn} {phase} unit_id={unit_id_str} "
            f"old_hp={entry.get('HP_CUR')} new_hp={effective_hp}"
        )
        entry["HP_CUR"] = effective_hp


def check_if_melee_can_charge(target: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
    """Check if any friendly melee unit can charge this target."""
    current_player = game_state["current_player"]
    
    units_cache = require_key(game_state, "units_cache")
    unit_by_id = {str(u["id"]): u for u in game_state["units"]}
    for unit_id, entry in units_cache.items():
        unit = unit_by_id.get(str(unit_id))
        if not unit:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        if entry["player"] == current_player:
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Check if unit has melee weapons
            from engine.utils.weapon_helpers import get_selected_melee_weapon
            has_melee = False
            if unit.get("CC_WEAPONS") and len(unit["CC_WEAPONS"]) > 0:
                melee_weapon = get_selected_melee_weapon(unit)
                if melee_weapon and expected_dice_value(require_key(melee_weapon, "DMG"), "melee_charge_dmg") > 0:
                    has_melee = True
            if has_melee:  # Has melee capability
                unit_pos = get_unit_position(unit, game_state)
                target_pos = get_unit_position(target, game_state)
                if unit_pos is None or target_pos is None:
                    continue
                # Estimate charge range (unit move + average 2d6)
                distance = calculate_hex_distance(*unit_pos, *target_pos)
                if "MOVE" not in unit:
                    raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
                config = require_key(game_state, "config")
                game_rules = require_key(config, "game_rules")
                avg_charge_roll = require_key(game_rules, "avg_charge_roll")
                max_charge = unit["MOVE"] + avg_charge_roll
                if distance <= max_charge:
                    return True
    
    return False


def calculate_target_priority_score(unit: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> float:
    """Calculate target priority score using AI_GAME_OVERVIEW.md logic.
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers instead of RNG_DMG/CC_DMG
    """
    
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use max DMG from all weapons
    from engine.utils.weapon_helpers import get_selected_ranged_weapon, get_selected_melee_weapon
    
    # Calculate max threat from target's weapons
    target_rng_weapon = get_selected_ranged_weapon(target)
    target_cc_weapon = get_selected_melee_weapon(target)
    target_rng_dmg = expected_dice_value(require_key(target_rng_weapon, "DMG"), "target_rng_dmg") if target_rng_weapon else 0
    target_cc_dmg = expected_dice_value(require_key(target_cc_weapon, "DMG"), "target_cc_dmg") if target_cc_weapon else 0
    # Also check all weapons for max threat
    if target.get("RNG_WEAPONS"):
        target_rng_dmg = max(
            target_rng_dmg,
            max(expected_dice_value(require_key(w, "DMG"), "target_rng_dmg_pool") for w in target["RNG_WEAPONS"])
        )
    if target.get("CC_WEAPONS"):
        target_cc_dmg = max(
            target_cc_dmg,
            max(expected_dice_value(require_key(w, "DMG"), "target_cc_dmg_pool") for w in target["CC_WEAPONS"])
        )
    
    threat_level = max(target_rng_dmg, target_cc_dmg)
    
    # Phase 2: HP from cache only
    target_hp = require_hp_from_cache(str(target["id"]), game_state)
    
    # Calculate if unit can kill target in 1 phase (use selected weapon or first weapon)
    unit_rng_weapon = get_selected_ranged_weapon(unit)
    if not unit_rng_weapon and unit.get("RNG_WEAPONS"):
        unit_rng_weapon = unit["RNG_WEAPONS"][0]
    unit_rng_dmg = expected_dice_value(require_key(unit_rng_weapon, "DMG"), "unit_rng_dmg") if unit_rng_weapon else 0
    can_kill_1_phase = target_hp <= unit_rng_dmg
    
    # Priority 1: High threat that melee can charge but won't kill (score: 1000)
    if threat_level >= 3:  # High threat threshold
        melee_can_charge = check_if_melee_can_charge(target, game_state)
        if melee_can_charge and target_hp > 2:  # Won't die to melee in 1 phase
            return 1000 + threat_level
    
    # Priority 2: High threat that can be killed in 1 shooting phase (score: 800) 
    if can_kill_1_phase and threat_level >= 3:
        return 800 + threat_level
    
    # Priority 3: High threat, lowest HP that can be killed (score: 600)
    if can_kill_1_phase and threat_level >= 2:
        return 600 + threat_level + (10 - target_hp)  # Prefer lower HP
    
    # Default: threat level only
    return threat_level


def enrich_unit_for_reward_mapper(unit: Dict[str, Any], game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich unit data for reward mapper compatibility (matches engine format).
    Unit must be alive (in units_cache). For dead targets use a stub with cur_hp=0 from caller.
    """
    if not unit:
        return {}
    
    # Direct field access with validation
    if "agent_mapping" not in game_state:
        agent_mapping = {}
    else:
        agent_mapping = game_state["agent_mapping"]
    
    unit_id_key = str(require_key(unit, "id"))
    if unit_id_key in agent_mapping:
        controlled_agent = agent_mapping[unit_id_key]
    elif "unitType" in unit:
        controlled_agent = unit["unitType"]
    elif "unit_type" in unit:
        controlled_agent = unit["unit_type"]
    else:
        controlled_agent = "default"
    
    enriched = unit.copy()
    
    # Phase 2: HP from cache only; unit must be alive (in cache)
    cur_hp = require_hp_from_cache(unit_id_key, game_state)
    
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers instead of CC_DMG/RNG_DMG
    from engine.utils.weapon_helpers import get_selected_ranged_weapon, get_selected_melee_weapon
    
    # Get max DMG from weapons
    unit_rng_weapon = get_selected_ranged_weapon(unit)
    unit_cc_weapon = get_selected_melee_weapon(unit)
    rng_dmg = expected_dice_value(require_key(unit_rng_weapon, "DMG"), "enrich_rng_dmg") if unit_rng_weapon else 0
    cc_dmg = expected_dice_value(require_key(unit_cc_weapon, "DMG"), "enrich_cc_dmg") if unit_cc_weapon else 0
    # Also check all weapons for max DMG
    if unit.get("RNG_WEAPONS"):
        rng_dmg = max(
            rng_dmg,
            max(expected_dice_value(require_key(w, "DMG"), "enrich_rng_dmg_pool") for w in unit["RNG_WEAPONS"])
        )
    if unit.get("CC_WEAPONS"):
        cc_dmg = max(
            cc_dmg,
            max(expected_dice_value(require_key(w, "DMG"), "enrich_cc_dmg_pool") for w in unit["CC_WEAPONS"])
        )
    
    enriched.update({
        "controlled_agent": controlled_agent,
        "unitType": controlled_agent,  # Use controlled_agent as unitType
        "name": unit["name"] if "name" in unit else f"Unit_{unit['id']}",
        "cc_dmg": cc_dmg,
        "rng_dmg": rng_dmg,
        "CUR_HP": cur_hp
    })
    
    return enriched


def get_engagement_zone(game_state: Dict[str, Any]) -> int:
    """Read engagement_zone from game_rules config.

    Returns 1 for legacy boards (adjacency), 10 for Board ×10 (§9.0).
    """
    from engine.spatial_relations import get_engagement_zone as _get_engagement_zone

    return _get_engagement_zone(game_state)


def get_max_base_size_hex(game_state: Dict[str, Any]) -> int:
    """Plafond (diamètre hex) pour borner les empreintes ennemies dans les filtres spatiaux.

    Utilisé par la prune conservatrice des ennemis en déplacement (ez > 1) : au-delà de ce
    diamètre, on tronque la contribution « rayon d'empreinte » pour rester sûr sans exploser
    la fenêtre si des données unité sont aberrantes.
    """
    config = game_state.get("config") or {}
    game_rules = config.get("game_rules") or {}
    return int(game_rules.get("max_base_size_hex", 35))


def build_enemy_adjacent_hexes(game_state: Dict[str, Any], player: int) -> Set[Tuple[int, int]]:
    """Pre-compute all hexes within engagement_zone of enemy units.

    Returns a set of (col, row) that are in the engagement zone of at least one enemy.
    For legacy boards (engagement_zone=1): equivalent to adjacent hexes.
    For Board ×10 (engagement_zone=10): dilated multi-hex zone (§9.0).

    Calculates once per phase and stores in game_state cache.
    Call this function at phase start, then use game_state[f"enemy_adjacent_hexes_player_{player}"] directly.

    Uses units_cache as source of truth for living enemy positions and occupied_hexes.

    Args:
        game_state: Game state with units_cache
        player: The player checking adjacency (enemies are units with different player)

    Returns:
        Set of hex coordinates in the engagement zone of any living enemy unit
    """
    enemy_adjacent_counts, enemy_adjacent_hexes = _compute_enemy_adjacent_cache_for_player_from_units_cache(
        game_state, int(player)
    )

    cache_key = f"enemy_adjacent_hexes_player_{player}"
    counts_key = f"enemy_adjacent_counts_player_{player}"
    game_state[cache_key] = enemy_adjacent_hexes
    game_state[counts_key] = enemy_adjacent_counts
    
    return enemy_adjacent_hexes


def _compute_enemy_adjacent_cache_for_player_from_units_cache(
    game_state: Dict[str, Any], player: int
) -> Tuple[Dict[Tuple[int, int], int], Set[Tuple[int, int]]]:
    """Compute per-player engagement-zone counters and set from current units_cache.

    For each enemy unit, dilates its occupied_hexes by the engagement zone distance
    (get_engagement_zone = engagement_zone inches × inches_to_subhex), cohérent avec
    l'éligibilité fight/pile-in et le blocage mouvement. NB: avant, ce cache dilatait de
    inches_to_subhex (1") en supposant engagement_zone == 1" ; faux dès engagement_zone ≠ 1".
    """
    units_cache = require_key(game_state, "units_cache")
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    ez_dilation = int(get_engagement_zone(game_state))
    player_int = int(player)

    all_enemy_occupied: Set[Tuple[int, int]] = set()
    per_unit_occupied: list = []

    for entry in units_cache.values():
        hp_cur = require_key(entry, "HP_CUR")
        if hp_cur <= 0:
            continue
        entry_player_raw = require_key(entry, "player")
        try:
            entry_player = int(entry_player_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid player value in units_cache entry: {entry_player_raw!r}") from exc
        if entry_player == player_int:
            continue

        by_model = entry.get("occupied_hexes_by_model")
        if by_model:
            unit_cells = set(by_model.values())
        else:
            unit_cells = {(int(require_key(entry, "col")), int(require_key(entry, "row")))}
        all_enemy_occupied.update(unit_cells)
        per_unit_occupied.append(unit_cells)

    from engine.hex_utils import dilate_hex_set
    zone_hexes = dilate_hex_set(all_enemy_occupied, ez_dilation, board_cols, board_rows)

    counts: Dict[Tuple[int, int], int] = {h: 1 for h in zone_hexes}

    return counts, zone_hexes


def _compute_enemy_adjacent_hexes_from_units_cache(
    game_state: Dict[str, Any], player: int
) -> Set[Tuple[int, int]]:
    """Compute engagement-zone hexes directly from current units_cache snapshot."""
    _, zone_hexes = _compute_enemy_adjacent_cache_for_player_from_units_cache(
        game_state, player
    )
    return zone_hexes


def _get_players_present_from_units_cache(game_state: Dict[str, Any]) -> Set[int]:
    """Return all player ids currently present in units_cache."""
    units_cache = require_key(game_state, "units_cache")
    players_present: Set[int] = set()
    for cache_entry in units_cache.values():
        player_raw = require_key(cache_entry, "player")
        try:
            player_int = int(player_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid player value in units_cache: {player_raw!r}"
            ) from exc
        players_present.add(player_int)
    return players_present


def _bounded_neighbors(
    col: int, row: int, board_cols: int, board_rows: int
) -> List[Tuple[int, int]]:
    """Get in-bounds hex neighbors."""
    neighbors: List[Tuple[int, int]] = []
    for n_col, n_row in get_hex_neighbors(col, row):
        if n_col < 0 or n_row < 0 or n_col >= board_cols or n_row >= board_rows:
            continue
        neighbors.append((n_col, n_row))
    return neighbors


def _footprint_external_neighbors(
    occupied_hexes: Set[Tuple[int, int]],
    board_cols: int,
    board_rows: int,
) -> List[Tuple[int, int]]:
    """Return all in-bounds hexes adjacent to a footprint but not part of it."""
    neighbor_set: Set[Tuple[int, int]] = set()
    for hx_col, hx_row in occupied_hexes:
        for n_col, n_row in get_hex_neighbors(hx_col, hx_row):
            if n_col < 0 or n_row < 0 or n_col >= board_cols or n_row >= board_rows:
                continue
            if (n_col, n_row) not in occupied_hexes:
                neighbor_set.add((n_col, n_row))
    return list(neighbor_set)


def _build_enemy_adjacent_structures_from_units_cache(
    game_state: Dict[str, Any],
    players_present: Set[int],
) -> Tuple[Dict[int, Dict[Tuple[int, int], int]], Dict[int, Set[Tuple[int, int]]]]:
    """
    Build per-player enemy-adjacent counters and sets from current units_cache snapshot.
    Uses dilate_hex_set with engagement_zone for consistency with build_enemy_adjacent_hexes.
    """
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    units_cache = require_key(game_state, "units_cache")
    # engagement zone réelle (engagement_zone inches × inches_to_subhex), PAS inches_to_subhex seul
    # (= 1") : sinon move/tir détectent l'engagement à 1" et le fight à 2" (incohérent).
    ez_dilation = int(get_engagement_zone(game_state))
    from engine.hex_utils import dilate_hex_set

    counters_by_player: Dict[int, Dict[Tuple[int, int], int]] = {
        player_int: {} for player_int in players_present
    }
    sets_by_player: Dict[int, Set[Tuple[int, int]]] = {
        player_int: set() for player_int in players_present
    }

    for cache_entry in units_cache.values():
        hp_cur = require_key(cache_entry, "HP_CUR")
        if hp_cur <= 0:
            continue
        unit_player_raw = require_key(cache_entry, "player")
        try:
            unit_player_int = int(unit_player_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid player value in units_cache entry: {unit_player_raw!r}"
            ) from exc
        by_model = cache_entry.get("occupied_hexes_by_model")
        if by_model:
            unit_cells = set(by_model.values())
        else:
            unit_cells = {(int(require_key(cache_entry, "col")), int(require_key(cache_entry, "row")))}
        unit_zone = dilate_hex_set(unit_cells, ez_dilation, board_cols, board_rows)
        for perspective_player in players_present:
            if perspective_player == unit_player_int:
                continue
            player_counters = counters_by_player[perspective_player]
            player_set = sets_by_player[perspective_player]
            for h in unit_zone:
                if h in player_counters:
                    player_counters[h] = player_counters[h] + 1
                else:
                    player_counters[h] = 1
                player_set.add(h)

    return counters_by_player, sets_by_player


def _apply_enemy_adjacent_delta_for_moved_unit(
    counters_by_player: Dict[int, Dict[Tuple[int, int], int]],
    sets_by_player: Dict[int, Set[Tuple[int, int]]],
    players_present: Set[int],
    moved_unit_player: int,
    old_occupied: Set[Tuple[int, int]],
    new_occupied: Set[Tuple[int, int]],
    board_cols: int,
    board_rows: int,
    engagement_zone: int = 1,
    game_state: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Apply incremental enemy-adjacent cache update after one unit position change.
    Supports multi-hex footprints via old_occupied / new_occupied sets.
    Uses dilate_hex_set with engagement_zone to match the full-recompute path.
    """
    from engine.hex_utils import dilate_hex_set
    old_zone = dilate_hex_set(old_occupied, engagement_zone, board_cols, board_rows)
    new_zone = dilate_hex_set(new_occupied, engagement_zone, board_cols, board_rows)

    for perspective_player in players_present:
        if perspective_player == moved_unit_player:
            continue

        player_counters = require_key(counters_by_player, perspective_player)
        player_set = require_key(sets_by_player, perspective_player)

        for h in old_zone:
            if h not in player_counters:
                if game_state is not None and game_state.get("debug_mode", False):
                    from engine.game_utils import add_debug_file_log
                    units_cache = game_state.get("units_cache", {})  # get allowed
                    unit_positions = {
                        uid: (e.get("col"), e.get("row"), e.get("player"), e.get("occupied_hexes"))
                        for uid, e in units_cache.items()
                    }
                    counter_snapshot = {
                        str(k): v for k, v in player_counters.items() if k in old_zone
                    }
                    add_debug_file_log(game_state, (
                        f"[DELTA_MISSING_HEX] missing={h} perspective_player={perspective_player} "
                        f"moved_unit_player={moved_unit_player} ez={engagement_zone} "
                        f"old_occupied={sorted(old_occupied)} new_occupied={sorted(new_occupied)} "
                        f"old_zone={sorted(old_zone)} "
                        f"counter_for_old_zone={counter_snapshot} "
                        f"counter_total_keys={len(player_counters)} "
                        f"unit_positions={unit_positions}"
                    ))
                raise KeyError(
                    f"Delta update missing old zone hex {h} for player {perspective_player}"
                )
            current_count = player_counters[h]
            if current_count <= 0:
                raise ValueError(
                    f"Invalid non-positive adjacency count for {h} "
                    f"(player={perspective_player}, count={current_count})"
                )
            if current_count == 1:
                del player_counters[h]
                player_set.discard(h)
            else:
                player_counters[h] = current_count - 1

        for h in new_zone:
            if h in player_counters:
                player_counters[h] = player_counters[h] + 1
            else:
                player_counters[h] = 1
            player_set.add(h)


def _unit_has_rule_effect(unit: Dict[str, Any], rule_id: str) -> bool:
    """
    Check if unit has rule_id directly or through grants_rule_ids.
    """
    unit_rules = require_key(unit, "UNIT_RULES")
    target_effect_rule_id = _resolve_effect_rule_id_to_technical(rule_id)
    for rule in unit_rules:
        resolved_effect_ids = _resolve_unit_rule_entry_effect_rule_ids(rule)
        if target_effect_rule_id in resolved_effect_ids:
            return True
    return False


def _get_source_unit_rule_display_name_for_effect(unit: Dict[str, Any], effect_rule_id: str) -> Optional[str]:
    """
    Return source UNIT_RULES.displayName that grants/owns the effect; None if absent.
    """
    source_rule_id = get_source_unit_rule_id_for_effect(unit, effect_rule_id)
    if source_rule_id is None:
        return None

    unit_rules = require_key(unit, "UNIT_RULES")
    registry = _get_unit_rules_registry()
    target_effect_rule_id = _resolve_effect_rule_id_to_technical(effect_rule_id)
    for rule in unit_rules:
        direct_rule_id = require_key(rule, "ruleId")
        if direct_rule_id != source_rule_id:
            continue
        usage_value = rule.get("usage")
        if usage_value is not None:
            if not isinstance(usage_value, str):
                raise ValueError(f"Unit rule '{source_rule_id}' has invalid usage: {usage_value!r}")
            normalized_usage = usage_value.strip().lower()
        else:
            normalized_usage = None
        if normalized_usage in {"or", "unique"}:
            selected_granted_rule_id = rule.get("_selected_granted_rule_id")
            if selected_granted_rule_id is None:
                raise ValueError(
                    f"Unit {require_key(unit, 'id')} rule '{source_rule_id}' requires "
                    "_selected_granted_rule_id for usage 'or/unique'"
                )
            if not isinstance(selected_granted_rule_id, str) or not selected_granted_rule_id.strip():
                raise ValueError(
                    f"Unit {require_key(unit, 'id')} rule '{source_rule_id}' has invalid "
                    f"_selected_granted_rule_id: {selected_granted_rule_id!r}"
                )
            selected_rule_id = selected_granted_rule_id.strip()
            if selected_rule_id not in registry:
                raise KeyError(
                    f"Unknown selected granted rule id '{selected_rule_id}' in config/unit_rules.json"
                )
            selected_rule_config = registry[selected_rule_id]
            selected_rule_name = selected_rule_config.get("name")
            if not isinstance(selected_rule_name, str) or not selected_rule_name.strip():
                raise ValueError(
                    f"Rule '{selected_rule_id}' must define non-empty 'name' for selected rule display"
                )
            selected_technical_rule_id = _resolve_effect_rule_id_to_technical(selected_rule_id)
            if selected_technical_rule_id != target_effect_rule_id:
                raise ValueError(
                    f"Selected rule '{selected_rule_id}' resolves to '{selected_technical_rule_id}', "
                    f"but requested effect is '{target_effect_rule_id}'"
                )
            return selected_rule_name.strip().upper()
        display_name = require_key(rule, "displayName")
        if not isinstance(display_name, str) or not display_name.strip():
            unit_id = require_key(unit, "id")
            unit_name = unit.get("DISPLAY_NAME") or unit.get("unitType") or "UNKNOWN"
            raise ValueError(
                f"Unit {unit_id} ({unit_name}) has rule '{source_rule_id}' missing non-empty displayName"
            )
        return display_name.strip().upper()
    raise KeyError(f"Rule '{source_rule_id}' missing from UNIT_RULES for unit {require_key(unit, 'id')}")


_unit_rules_registry_cache: Optional[Dict[str, Dict[str, Any]]] = None


def _get_unit_rules_registry() -> Dict[str, Dict[str, Any]]:
    """Load and cache rule registry from config/unit_rules.json."""
    global _unit_rules_registry_cache
    if _unit_rules_registry_cache is not None:
        return _unit_rules_registry_cache
    from config_loader import get_config_loader
    registry = get_config_loader().load_unit_rules_config()
    _unit_rules_registry_cache = registry
    return registry


def _resolve_effect_rule_id_to_technical(rule_id: str, visited: Optional[Set[str]] = None) -> str:
    """Resolve a rule id to technical effect id by following optional alias chain."""
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise ValueError(f"rule_id must be a non-empty string, got {rule_id!r}")
    normalized_rule_id = rule_id.strip()
    registry = _get_unit_rules_registry()
    if normalized_rule_id not in registry:
        raise KeyError(f"Unknown rule id '{normalized_rule_id}' in config/unit_rules.json")

    if visited is None:
        visited = set()
    if normalized_rule_id in visited:
        raise ValueError(f"Rule alias cycle detected while resolving '{normalized_rule_id}'")
    visited.add(normalized_rule_id)

    rule_config = registry[normalized_rule_id]
    alias_value = rule_config.get("alias")
    if alias_value is None:
        return normalized_rule_id
    if not isinstance(alias_value, str) or not alias_value.strip():
        raise ValueError(
            f"Rule '{normalized_rule_id}' has invalid alias in config/unit_rules.json: {alias_value!r}"
        )
    return _resolve_effect_rule_id_to_technical(alias_value.strip(), visited)


def _resolve_unit_rule_entry_effect_rule_ids(rule_entry: Dict[str, Any]) -> Set[str]:
    """Resolve direct and granted rule ids from one UNIT_RULES entry to technical effect ids."""
    direct_rule_id = require_key(rule_entry, "ruleId")
    if not isinstance(direct_rule_id, str) or not direct_rule_id.strip():
        raise ValueError(f"UNIT_RULES.ruleId must be non-empty string, got {direct_rule_id!r}")

    resolved_rule_ids: Set[str] = {_resolve_effect_rule_id_to_technical(direct_rule_id)}
    usage_value = rule_entry.get("usage")
    if usage_value is not None:
        if not isinstance(usage_value, str):
            raise ValueError(f"UNIT_RULES usage must be string, got {usage_value!r}")
        usage_value = usage_value.strip().lower()
    if usage_value not in {None, "and", "or", "unique", "always"}:
        raise ValueError(f"Invalid UNIT_RULES usage value: {usage_value!r}")
    granted_rule_ids = rule_entry.get("grants_rule_ids")
    if granted_rule_ids is None:
        return resolved_rule_ids
    if not isinstance(granted_rule_ids, list):
        raise ValueError(
            f"UNIT_RULES entry for '{direct_rule_id}' has invalid grants_rule_ids type: "
            f"{type(granted_rule_ids).__name__}"
        )
    # always/and: all granted rules are active
    if usage_value in {None, "and", "always"}:
        for granted_rule_id in granted_rule_ids:
            if not isinstance(granted_rule_id, str) or not granted_rule_id.strip():
                raise ValueError(
                    f"UNIT_RULES entry for '{direct_rule_id}' has invalid granted rule id: {granted_rule_id!r}"
                )
            resolved_rule_ids.add(_resolve_effect_rule_id_to_technical(granted_rule_id))
        return resolved_rule_ids

    # or/unique: only selected grant is active
    selected_granted_rule_id = rule_entry.get("_selected_granted_rule_id")
    if selected_granted_rule_id is None:
        return resolved_rule_ids
    if not isinstance(selected_granted_rule_id, str) or not selected_granted_rule_id.strip():
        raise ValueError(
            f"UNIT_RULES entry for '{direct_rule_id}' has invalid _selected_granted_rule_id: "
            f"{selected_granted_rule_id!r}"
        )
    if selected_granted_rule_id not in granted_rule_ids:
        raise ValueError(
            f"UNIT_RULES entry for '{direct_rule_id}' has selected rule "
            f"'{selected_granted_rule_id}' not present in grants_rule_ids"
        )
    selected_technical_rule_id = _resolve_effect_rule_id_to_technical(selected_granted_rule_id)
    resolved_rule_ids.add(selected_technical_rule_id)
    return resolved_rule_ids

def get_source_unit_rule_id_for_effect(unit: Dict[str, Any], effect_rule_id: str) -> Optional[str]:
    """Return source UNIT_RULES.ruleId for a technical effect rule."""
    unit_rules = require_key(unit, "UNIT_RULES")
    target_effect_rule_id = _resolve_effect_rule_id_to_technical(effect_rule_id)
    for rule in unit_rules:
        source_rule_id = require_key(rule, "ruleId")
        resolved_effect_ids = _resolve_unit_rule_entry_effect_rule_ids(rule)
        if target_effect_rule_id in resolved_effect_ids:
            return source_rule_id
    return None


def unit_has_rule_effect(unit: Dict[str, Any], rule_id: str) -> bool:
    """Public helper for effect check with display->technical rule mapping."""
    return _unit_has_rule_effect(unit, rule_id)


def get_source_unit_rule_display_name_for_effect(
    unit: Dict[str, Any], effect_rule_id: str
) -> Optional[str]:
    """Public helper returning source display name for a technical effect rule."""
    return _get_source_unit_rule_display_name_for_effect(unit, effect_rule_id)
    return None


def _build_reactive_move_destinations_pool(
    game_state: Dict[str, Any],
    reactive_unit: Dict[str, Any],
    move_range: int,
    enemy_adjacent_hexes_override: Optional[Set[Tuple[int, int]]] = None,
) -> List[Tuple[int, int]]:
    """
    Build legal reactive move destinations using BFS with movement restrictions.
    """
    if move_range <= 0:
        raise ValueError(f"reactive_move move_range must be > 0, got {move_range}")
    start_col, start_row = require_unit_position(reactive_unit, game_state)
    start_pos = (start_col, start_row)

    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = require_key(game_state, "wall_hexes")

    reactive_player_raw = require_key(reactive_unit, "player")
    try:
        reactive_player = int(reactive_player_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Reactive unit {require_key(reactive_unit, 'id')} has invalid player: {reactive_player_raw!r}"
        ) from exc

    if enemy_adjacent_hexes_override is not None:
        enemy_adjacent_hexes = enemy_adjacent_hexes_override
    else:
        # Use phase cache by default.
        cache_key = f"enemy_adjacent_hexes_player_{reactive_player}"
        if cache_key not in game_state:
            raise KeyError(
                f"Missing required adjacency cache '{cache_key}'. "
                "Cache must be initialized at phase start."
            )
        enemy_adjacent_hexes = require_key(game_state, cache_key)
        if not isinstance(enemy_adjacent_hexes, set):
            raise ValueError(
                f"Invalid adjacency cache type for '{cache_key}': "
                f"{type(enemy_adjacent_hexes).__name__}"
            )

    # Build occupied positions from units_cache (all living units except the moving one).
    units_cache = require_key(game_state, "units_cache")
    reactive_unit_id = str(require_key(reactive_unit, "id"))
    occupied_positions: Set[Tuple[int, int]] = set()
    for unit_id, entry in units_cache.items():
        if str(unit_id) == reactive_unit_id:
            continue
        entry_col = require_key(entry, "col")
        entry_row = require_key(entry, "row")
        occupied_positions.add((entry_col, entry_row))

    wall_set: Set[Tuple[int, int]] = set()
    for wall_hex in wall_hexes:
        if isinstance(wall_hex, (tuple, list)) and len(wall_hex) == 2:
            wall_col, wall_row = normalize_coordinates(wall_hex[0], wall_hex[1])
            wall_set.add((wall_col, wall_row))
        else:
            raise ValueError(f"Invalid wall hex entry: {wall_hex!r}")

    visited: Set[Tuple[int, int]] = {start_pos}
    queue: List[Tuple[Tuple[int, int], int]] = [(start_pos, 0)]
    valid_destinations: List[Tuple[int, int]] = []

    while queue:
        (cur_col, cur_row), cur_dist = queue.pop(0)
        if cur_dist >= move_range:
            continue

        for neighbor_col, neighbor_row in get_hex_neighbors(cur_col, cur_row):
            neighbor = (neighbor_col, neighbor_row)
            if neighbor in visited:
                continue
            if neighbor_col < 0 or neighbor_row < 0 or neighbor_col >= board_cols or neighbor_row >= board_rows:
                continue
            if neighbor in wall_set:
                continue
            if neighbor in occupied_positions:
                continue
            if neighbor in enemy_adjacent_hexes:
                continue

            visited.add(neighbor)
            valid_destinations.append(neighbor)
            queue.append((neighbor, cur_dist + 1))

    # Deterministic destination order.
    valid_destinations.sort(key=lambda pos: (int(pos[0]), int(pos[1])))
    return valid_destinations


def _select_reactive_unit_order(
    game_state: Dict[str, Any], eligible_units: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Order eligible reactive units according to configured reactive mode.
    """
    mode_raw = require_key(game_state, "reactive_mode")
    if mode_raw not in {"micro", "macro"}:
        raise ValueError(f"Unsupported reactive_mode: {mode_raw!r}")

    if mode_raw == "micro":
        return sorted(eligible_units, key=lambda unit: str(require_key(unit, "id")))

    macro_order_raw = game_state.get("reactive_macro_order_current_window")
    if macro_order_raw is None:
        raise ValueError("ValueError[reactive_move.invalid_macro_order]: missing reactive_macro_order_current_window")
    if not isinstance(macro_order_raw, list):
        raise ValueError(
            "ValueError[reactive_move.invalid_macro_order]: "
            f"reactive_macro_order_current_window must be list, got {type(macro_order_raw).__name__}"
        )
    macro_order = [str(unit_id) for unit_id in macro_order_raw]
    if len(macro_order) == 0:
        raise ValueError("ValueError[reactive_move.invalid_macro_order]: macro order cannot be empty")

    eligible_by_id = {str(require_key(unit, "id")): unit for unit in eligible_units}
    ordered: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for unit_id in macro_order:
        if unit_id in eligible_by_id and unit_id not in seen:
            ordered.append(eligible_by_id[unit_id])
            seen.add(unit_id)
        elif unit_id not in eligible_by_id:
            raise ValueError(
                "ValueError[reactive_move.invalid_macro_order]: "
                f"unit_id={unit_id} not eligible in current reaction window"
            )

    return ordered


def _select_reactive_destination(
    valid_destinations: List[Tuple[int, int]], moved_to_col: int, moved_to_row: int
) -> Tuple[int, int]:
    """
    Deterministic destination policy: closest to moved enemy unit, tie-break by coordinates.
    """
    if not valid_destinations:
        raise ValueError("Cannot select reactive destination from empty pool")
    return min(
        valid_destinations,
        key=lambda pos: (calculate_hex_distance(pos[0], pos[1], moved_to_col, moved_to_row), pos[0], pos[1]),
    )


def _resolve_reactive_decision(
    game_state: Dict[str, Any],
    reactive_unit_id: str,
    valid_destinations: List[Tuple[int, int]],
    moved_to_col: int,
    moved_to_row: int,
) -> Tuple[str, Optional[Tuple[int, int]]]:
    """
    Resolve reactive decision for one unit.

    Returns:
        ("decline", None) or ("move", (col, row))
    """
    decision_mode = require_key(game_state, "reactive_decision_mode")
    if decision_mode not in {"auto", "state"}:
        raise ValueError(f"Unsupported reactive_decision_mode: {decision_mode!r}")

    if decision_mode == "auto":
        return "move", _select_reactive_destination(valid_destinations, moved_to_col, moved_to_row)

    payload = require_key(game_state, "reactive_decision_payload")
    if not isinstance(payload, dict):
        raise ValueError(
            f"reactive_decision_payload must be dict when decision_mode='state', got {type(payload).__name__}"
        )

    decision_entry = payload.get(reactive_unit_id)
    if decision_entry is None:
        raise ValueError(
            "ValueError[reactive_move.missing_decision]: "
            f"reactive_unit_id={reactive_unit_id} has no decision in reactive_decision_payload"
        )
    if not isinstance(decision_entry, dict):
        raise ValueError(
            "ValueError[reactive_move.invalid_decision_payload]: "
            f"reactive_unit_id={reactive_unit_id} decision must be dict, got {type(decision_entry).__name__}"
        )

    action = require_key(decision_entry, "action")
    if action == "decline_reactive_move":
        # Consume decision entry once used in this window.
        del payload[reactive_unit_id]
        return "decline", None
    if action != "reactive_move":
        raise ValueError(
            "ValueError[reactive_move.invalid_decision_action]: "
            f"reactive_unit_id={reactive_unit_id} action={action!r}"
        )

    destination = require_key(decision_entry, "destination")
    if isinstance(destination, dict):
        if "col" not in destination or "row" not in destination:
            raise KeyError(
                "ValueError[reactive_move.invalid_destination_payload]: "
                f"reactive_unit_id={reactive_unit_id} destination dict must have col/row"
            )
        dest_col, dest_row = normalize_coordinates(destination["col"], destination["row"])
    elif isinstance(destination, (tuple, list)) and len(destination) == 2:
        dest_col, dest_row = normalize_coordinates(destination[0], destination[1])
    else:
        raise ValueError(
            "ValueError[reactive_move.invalid_destination_payload]: "
            f"reactive_unit_id={reactive_unit_id} destination must be [col,row] or {{col,row}}, got {destination!r}"
        )

    selected_dest = (dest_col, dest_row)
    if selected_dest not in valid_destinations:
        raise ValueError(
            "ValueError[reactive_move.invalid_destination]: "
            f"reactive_unit_id={reactive_unit_id} destination={selected_dest} pool_size={len(valid_destinations)}"
        )

    del payload[reactive_unit_id]
    return "move", selected_dest


def refresh_all_positional_caches_after_reactive_move(
    game_state: Dict[str, Any],
    enemy_adjacent_counts_override: Optional[Dict[int, Dict[Tuple[int, int], int]]] = None,
    enemy_adjacent_sets_override: Optional[Dict[int, Set[Tuple[int, int]]]] = None,
    *,
    reactive_move_old_col: Optional[int] = None,
    reactive_move_old_row: Optional[int] = None,
    reactive_move_new_col: Optional[int] = None,
    reactive_move_new_row: Optional[int] = None,
) -> None:
    """
    Centralized cache refresh after any applied reactive move.
    """
    # Invalidate global LoS caches.
    game_state["los_cache"] = {}
    # _hex_los_state_cache: NOT invalidated on reactive move (terrain-static, see
    # _invalidate_los_cache_for_moved_unit for rationale).
    # hex_los_cache: selective invalidation maintained (footprint-dependent).
    if "hex_los_cache" in game_state:
        positions_to_invalidate: List[Tuple[int, int]] = []
        if reactive_move_old_col is not None and reactive_move_old_row is not None:
            positions_to_invalidate.append(normalize_coordinates(reactive_move_old_col, reactive_move_old_row))
        if reactive_move_new_col is not None and reactive_move_new_row is not None:
            positions_to_invalidate.append(normalize_coordinates(reactive_move_new_col, reactive_move_new_row))
        if positions_to_invalidate:
            keys_to_remove = [k for k in game_state["hex_los_cache"].keys()
                              if k[0] in positions_to_invalidate or k[1] in positions_to_invalidate]
            for k in keys_to_remove:
                del game_state["hex_los_cache"][k]
        else:
            game_state["hex_los_cache"] = {}

    # Invalidate all destination/target pools via movement helper.
    from .movement_handlers import _invalidate_all_destination_pools_after_movement
    _invalidate_all_destination_pools_after_movement(game_state)

    # Invalidate unit-local LoS caches.
    for unit in require_key(game_state, "units"):
        if "los_cache" in unit:
            unit["los_cache"] = {}

    players_present = _get_players_present_from_units_cache(game_state)
    if enemy_adjacent_sets_override is not None:
        if enemy_adjacent_counts_override is None:
            raise KeyError(
                "enemy_adjacent_counts_override is required when enemy_adjacent_sets_override is provided"
            )
        for player_int in players_present:
            if player_int not in enemy_adjacent_counts_override:
                raise KeyError(
                    f"Missing adjacency counts override for player {player_int} during reactive cache refresh"
                )
            if player_int not in enemy_adjacent_sets_override:
                raise KeyError(
                    f"Missing adjacency override for player {player_int} during reactive cache refresh"
                )
            override_counts = require_key(enemy_adjacent_counts_override, player_int)
            override_set = require_key(enemy_adjacent_sets_override, player_int)
            if not isinstance(override_counts, dict):
                raise TypeError(
                    f"Adjacency counts override for player {player_int} must be dict, got {type(override_counts).__name__}"
                )
            if not isinstance(override_set, set):
                raise TypeError(
                    f"Adjacency override for player {player_int} must be set, got {type(override_set).__name__}"
                )
            game_state[f"enemy_adjacent_counts_player_{player_int}"] = dict(override_counts)
            game_state[f"enemy_adjacent_hexes_player_{player_int}"] = set(override_set)
        return

    # Direct recompute path for external callers: recompute from units_cache snapshot.
    for player_int in players_present:
        counts, hexes = _compute_enemy_adjacent_cache_for_player_from_units_cache(game_state, player_int)
        game_state[f"enemy_adjacent_counts_player_{player_int}"] = counts
        game_state[f"enemy_adjacent_hexes_player_{player_int}"] = hexes


def update_enemy_adjacent_caches_after_unit_move(
    game_state: Dict[str, Any],
    moved_unit_player: int,
    old_col: int,
    old_row: int,
    new_col: int,
    new_row: int,
    old_occupied: Optional[Set[Tuple[int, int]]] = None,
    new_occupied: Optional[Set[Tuple[int, int]]] = None,
) -> None:
    """
    Update enemy adjacency caches after one unit movement.
    Only recomputes caches for players who see the moved unit as an enemy.
    When player X moves, only OTHER players' caches change (they see player X as enemy).
    Player X's own cache is unaffected (their enemies didn't move).
    """
    if old_col == new_col and old_row == new_row:
        return

    moved_player_int = int(moved_unit_player)
    players_present = _get_players_present_from_units_cache(game_state)
    if moved_player_int not in players_present:
        raise KeyError(
            f"Moved unit player {moved_unit_player} not present in units_cache players {sorted(players_present)}"
        )

    for player_int in players_present:
        if player_int == moved_player_int:
            continue
        counts, hexes = _compute_enemy_adjacent_cache_for_player_from_units_cache(game_state, player_int)
        game_state[f"enemy_adjacent_counts_player_{player_int}"] = counts
        game_state[f"enemy_adjacent_hexes_player_{player_int}"] = hexes


def update_enemy_adjacent_caches_after_unit_removed(
    game_state: Dict[str, Any],
    removed_unit_player: int,
    old_col: int,
    old_row: int,
    old_occupied: Optional[Set[Tuple[int, int]]] = None,
) -> None:
    """
    Update enemy adjacency caches after one unit removal from units_cache.
    Only recomputes caches for players who saw the removed unit as an enemy.
    Unit is already removed from units_cache before this call.
    """
    removed_player_int = int(removed_unit_player)
    players_present = _get_players_present_from_units_cache(game_state)
    players_present.add(removed_player_int)

    for player_int in players_present:
        if player_int == removed_player_int:
            continue
        counts, hexes = _compute_enemy_adjacent_cache_for_player_from_units_cache(game_state, player_int)
        game_state[f"enemy_adjacent_counts_player_{player_int}"] = counts
        game_state[f"enemy_adjacent_hexes_player_{player_int}"] = hexes


def maybe_resolve_reactive_move(
    game_state: Dict[str, Any],
    moved_unit_id: str,
    from_col: int,
    from_row: int,
    to_col: int,
    to_row: int,
    move_kind: str,
    move_cause: str,
) -> Dict[str, Any]:
    """
    Resolve reactive_move window after an enemy unit has ended movement.
    """
    # Validate event payload.
    moved_unit_id_str = str(moved_unit_id)
    from_col_int, from_row_int = normalize_coordinates(from_col, from_row)
    to_col_int, to_row_int = normalize_coordinates(to_col, to_row)
    if move_kind not in {"move", "advance", "flee", "reposition_normal"}:
        raise ValueError(f"Unsupported move_kind for reactive_move: {move_kind}")
    if move_cause not in {"normal", "reactive_move"}:
        raise ValueError(f"Unsupported move_cause for reactive_move: {move_cause}")

    if move_cause == "reactive_move":
        return {"reactive_moves_applied": 0, "reactive_moves_declined": 0, "triggered": False}

    if require_key(game_state, "reaction_window_active"):
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "?")
        current_player = game_state.get("current_player", "?")
        raise RuntimeError(
            "RuntimeError[reactive_move.reentrance]: "
            f"episode={episode} turn={turn} phase={phase} current_player={current_player} "
            f"moved_unit_id={moved_unit_id_str} move_cause={move_cause} reaction_window_active=True"
        )

    moved_unit = get_unit_by_id(game_state, moved_unit_id_str)
    if moved_unit is None:
        raise KeyError(f"Moved unit not found for reactive_move: {moved_unit_id_str}")
    moved_player = require_key(moved_unit, "player")

    units_cache = require_key(game_state, "units_cache")

    # Build reaction candidates.
    reacted_set = require_key(game_state, "units_reacted_this_enemy_turn")
    if not isinstance(reacted_set, set):
        raise ValueError(
            f"units_reacted_this_enemy_turn must be set, got {type(reacted_set).__name__}"
        )

    eligible_units: List[Dict[str, Any]] = []
    for unit_id in units_cache.keys():
        unit = get_unit_by_id(game_state, unit_id)
        if unit is None:
            raise KeyError(f"Unit {unit_id} present in units_cache but missing from game_state['units']")

        unit_id_str = str(require_key(unit, "id"))
        if not is_unit_alive(unit_id_str, game_state):
            continue

        unit_player = require_key(unit, "player")
        if int(unit_player) == int(moved_player):
            continue
        if unit_id_str in reacted_set:
            continue
        if not _unit_has_rule_effect(unit, "reactive_move"):
            continue

        unit_col, unit_row = require_unit_position(unit, game_state)
        if calculate_hex_distance(unit_col, unit_row, to_col_int, to_row_int) > 9:
            continue

        eligible_units.append(unit)

    if not eligible_units:
        return {"reactive_moves_applied": 0, "reactive_moves_declined": 0, "triggered": False}

    ordered_units = _select_reactive_unit_order(game_state, eligible_units)
    if not ordered_units:
        return {"reactive_moves_applied": 0, "reactive_moves_declined": 0, "triggered": False}

    # Build adjacency structures only when at least one non-reacted unit is eligible.
    players_present = _get_players_present_from_units_cache(game_state)
    reactive_adjacent_counts_by_player, reactive_adjacent_sets_by_player = (
        _build_enemy_adjacent_structures_from_units_cache(game_state, players_present)
    )
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")

    game_state["reaction_window_active"] = True
    game_state["last_move_event_id"] = int(require_key(game_state, "last_move_event_id")) + 1
    applied_count = 0
    declined_count = 0
    try:
        for reactive_unit in ordered_units:
            reactive_unit_id = str(require_key(reactive_unit, "id"))
            reactive_player_raw = require_key(reactive_unit, "player")
            try:
                reactive_player_int = int(reactive_player_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Reactive unit {reactive_unit_id} has invalid player: {reactive_player_raw!r}"
                ) from exc
            if reactive_player_int not in reactive_adjacent_sets_by_player:
                raise KeyError(
                    f"Missing reactive adjacency snapshot for player {reactive_player_int}"
                )

            # Each reacting unit gets its own D6 range roll.
            move_range = resolve_dice_value("D6", "reactive_move_distance")
            valid_destinations = _build_reactive_move_destinations_pool(
                game_state,
                reactive_unit,
                move_range,
                enemy_adjacent_hexes_override=reactive_adjacent_sets_by_player[reactive_player_int],
            )
            if not valid_destinations:
                continue

            decision_action, selected_dest = _resolve_reactive_decision(
                game_state,
                reactive_unit_id,
                valid_destinations,
                to_col_int,
                to_row_int,
            )
            if decision_action == "decline":
                declined_count += 1
                if "action_logs" not in game_state:
                    game_state["action_logs"] = []
                append_action_log(
                    game_state,
                    {
                        "type": "reactive_move_declined",
                        "unitId": reactive_unit_id,
                        "triggered_by_unit_id": moved_unit_id_str,
                        "trigger_move_kind": move_kind,
                        "trigger_move_cause": move_cause,
                        "range_roll": move_range,
                        "event_fromCol": from_col_int,
                        "event_fromRow": from_row_int,
                        "event_toCol": to_col_int,
                        "event_toRow": to_row_int,
                    },
                )
                continue

            if selected_dest is None:
                raise ValueError(
                    f"Reactive move decision returned action={decision_action!r} without destination for unit {reactive_unit_id}"
                )
            dest_col, dest_row = selected_dest

            orig_col, orig_row = require_unit_position(reactive_unit, game_state)
            set_unit_coordinates(reactive_unit, dest_col, dest_row)
            update_units_cache_position(game_state, reactive_unit_id, dest_col, dest_row)
            reacted_set.add(reactive_unit_id)
            game_state["last_move_cause"] = "reactive_move"
            ability_display_name = _get_source_unit_rule_display_name_for_effect(
                reactive_unit, "reactive_move"
            )
            if ability_display_name is None:
                unit_name = reactive_unit.get("DISPLAY_NAME") or reactive_unit.get("unitType") or "UNKNOWN"
                raise ValueError(
                    f"Unit {reactive_unit_id} ({unit_name}) triggered reactive_move without source rule displayName"
                )
            _apply_enemy_adjacent_delta_for_moved_unit(
                counters_by_player=reactive_adjacent_counts_by_player,
                sets_by_player=reactive_adjacent_sets_by_player,
                players_present=players_present,
                moved_unit_player=reactive_player_int,
                old_occupied={(orig_col, orig_row)},
                new_occupied={(dest_col, dest_row)},
                board_cols=board_cols,
                board_rows=board_rows,
                game_state=game_state,
            )

            # Keep action logs explicit for post-mortem analysis.
            if "action_logs" not in game_state:
                game_state["action_logs"] = []
            append_action_log(
                game_state,
                {
                    "type": "reactive_move",
                    "message": (
                        f"Unit {reactive_unit_id}({dest_col},{dest_row}) REACTIVE MOVED [{ability_display_name}] "
                        f"from ({orig_col},{orig_row}) to ({dest_col},{dest_row}) [Roll: {move_range}] "
                        f"- trigger: Unit {moved_unit_id_str}->({to_col_int},{to_row_int})"
                    ),
                    "unitId": reactive_unit_id,
                    "player": require_key(reactive_unit, "player"),
                    "ability_display_name": ability_display_name,
                    "triggered_by_unit_id": moved_unit_id_str,
                    "trigger_move_kind": move_kind,
                    "trigger_move_cause": move_cause,
                    "fromCol": orig_col,
                    "fromRow": orig_row,
                    "toCol": dest_col,
                    "toRow": dest_row,
                    "range_roll": move_range,
                    "event_fromCol": from_col_int,
                    "event_fromRow": from_row_int,
                    "event_toCol": to_col_int,
                    "event_toRow": to_row_int,
                },
            )

            refresh_all_positional_caches_after_reactive_move(
                game_state,
                enemy_adjacent_counts_override=reactive_adjacent_counts_by_player,
                enemy_adjacent_sets_override=reactive_adjacent_sets_by_player,
                reactive_move_old_col=orig_col,
                reactive_move_old_row=orig_row,
                reactive_move_new_col=dest_col,
                reactive_move_new_row=dest_row,
            )
            applied_count += 1
    finally:
        game_state["reaction_window_active"] = False

    return {
        "reactive_moves_applied": applied_count,
        "reactive_moves_declined": declined_count,
        "triggered": applied_count > 0 or declined_count > 0,
    }


# ============================================================================
# DISTANCE PRIMITIVES — Engagement Range, Base-to-Base, Coherency
# ============================================================================
# Reference: Documentation/TODO/squad.md §"Definition des distances en hex-grid"
# Toutes les distances sont en subhexes. `inches_to_subhex` est l echelle du
# scenario (x5: 5 subhexes par pouce, x10: 10 subhexes par pouce).

BASE_TO_BASE_SUBHEX = 1


def get_coherency_subhex(game_state: Dict[str, Any]) -> int:
    """Unit Coherency, 1re puce (03.03) : distance fig-a-voisin (officiel 2" horizontal).
    Lue depuis game_rules.unit_model_cohesion_range, DEJA convertie en subhexes par
    w40k_core (pre-scale ×inches_to_subhex a l'init) : on la retourne telle quelle."""
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    return int(require_key(game_rules, "unit_model_cohesion_range"))


def get_cohesion_max_subhex(game_state: Dict[str, Any]) -> int:
    """Unit Coherency, 2e puce (03.03) : ecart max fig-a-fig (officiel 9" horizontal).
    Lue depuis game_rules.unit_global_cohesion_range, DEJA convertie en subhexes par
    w40k_core (pre-scale ×inches_to_subhex a l'init) : on la retourne telle quelle."""
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    return int(require_key(game_rules, "unit_global_cohesion_range"))


def get_min_neighbors(game_state: Dict[str, Any]) -> int:
    """Voisins min a <= unit_model_cohesion_range exiges par fig (03.03, 1re puce).
    Officiel 10e : 1 quelle que soit la taille de l'escouade."""
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    return int(require_key(game_rules, "squad_min_neighbors"))


def coherency_violation_flags(
    models: List[Dict[str, Any]], game_state: Dict[str, Any]
) -> List[bool]:
    """SOURCE UNIQUE de la coherency par-figurine (03.03). flags[i] = True si la fig i viole la
    coherency (1re puce : < min_neighbors voisin a <= model ; 2e puce : etalement). Partagee par
    le commit (_positions_in_coherency) ET le voile rouge per_model des handlers move/charge/fight.

    Chaque fig : dict col/row/BASE_SHAPE/BASE_SIZE/orientation. Mode lu dans
    game_rules.cohesion_distance_mode :
      - 'euclidean' : distance euclidienne centre-a-centre (geometrie de rendu) — coincide avec le
        visuel (halos). 2" bord-a-bord, etalement = cercle de rayon 9"/2 sur le barycentre.
      - 'footprint' : distance hex empreinte-a-empreinte (min_distance_between_sets) ; etalement =
        aucune paire > 9".
    Unite <= 1 fig : jamais en violation.
    """
    n = len(models)
    if n <= 1:
        return [False] * n
    coh = get_coherency_subhex(game_state)
    coh_max = get_cohesion_max_subhex(game_state)
    min_neighbors = get_min_neighbors(game_state)
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    mode = require_key(game_rules, "cohesion_distance_mode")
    if mode == "euclidean":
        return _coherency_flags_euclidean(models, coh, coh_max, min_neighbors)
    if mode == "footprint":
        return _coherency_flags_footprint(models, game_state, coh, coh_max, min_neighbors)
    raise ValueError(
        f"Invalid game_rules.cohesion_distance_mode: {mode!r} (expected 'euclidean' or 'footprint')"
    )


def _positions_in_coherency(
    models: List[Dict[str, Any]], game_state: Dict[str, Any]
) -> bool:
    """Coherency d'ensemble (03.03) : True si AUCUNE fig n'est en violation. Delegue a
    coherency_violation_flags (source unique). Unite <= 1 fig : coherente d'office."""
    return not any(coherency_violation_flags(models, game_state))


def _coherency_flags_euclidean(
    models: List[Dict[str, Any]], coh: int, coh_max: int, min_neighbors: int
) -> List[bool]:
    """Flags par-fig en distance EUCLIDIENNE centre-a-centre, reproduisant la geometrie de rendu
    (hexCenter, hex_radius=1) pour coincider avec les halos a l'ecran.
      - 1re puce : >= min_neighbors voisin bord-a-bord (<= coh, soit 2" entre bords de base).
      - 2e puce  : chaque fig dans le cercle de rayon coh_max/2 centre sur le barycentre (<= 9").
    """
    from math import hypot
    sqrt3 = 3.0 ** 0.5
    n = len(models)

    def cart(m: Dict[str, Any]) -> Tuple[float, float]:
        c, r = int(m["col"]), int(m["row"])
        return (c * 1.5, r * sqrt3 + (c % 2) * sqrt3 / 2.0)

    def base_radius(m: Dict[str, Any]) -> float:
        s = int(m["BASE_SIZE"])
        return s * 1.5 / 2.0 if s > 1 else 0.7

    pts = [cart(m) for m in models]
    radii = [base_radius(m) for m in models]
    model_range = coh * sqrt3              # 2" en unites de rendu (hex_radius=1)
    global_radius = coh_max * sqrt3 / 2.0  # cercle d'etalement (Ø = 9")
    # Centre du cercle = milieu des 2 figs les plus eloignees (diametre d'etalement), pas le barycentre.
    bx, by = pts[0]
    max_d2 = -1.0
    for i in range(n):
        for j in range(i + 1, n):
            dx = pts[i][0] - pts[j][0]
            dy = pts[i][1] - pts[j][1]
            d2 = dx * dx + dy * dy
            if d2 > max_d2:
                max_d2 = d2
                bx = (pts[i][0] + pts[j][0]) / 2.0
                by = (pts[i][1] + pts[j][1]) / 2.0
    # 1re puce : CONNEXITE. Graphe d'adjacence (paires a <= model bord-a-bord), puis composantes
    # connexes. L'unite doit former une seule chaine : les figs hors du composant majoritaire sont
    # en violation (rupture de chaine), meme si chacune a un voisin dans son sous-groupe.
    adj = [[False] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) - radii[i] - radii[j]
            if d <= model_range:
                adj[i][j] = adj[j][i] = True
    comp = [-1] * n
    num_comp = 0
    for s in range(n):
        if comp[s] != -1:
            continue
        stack = [s]
        comp[s] = num_comp
        while stack:
            k = stack.pop()
            for nb in range(n):
                if adj[k][nb] and comp[nb] == -1:
                    comp[nb] = num_comp
                    stack.append(nb)
        num_comp += 1
    comp_size: Dict[int, int] = {}
    for c in comp:
        comp_size[c] = comp_size.get(c, 0) + 1
    flags = [False] * n
    for i in range(n):
        # 1re puce : composant minoritaire (rupture de chaine) = violation.
        if comp_size[comp[i]] * 2 <= n:
            flags[i] = True
            continue
        # 2e puce : hors du cercle d'etalement — mesure depuis le bord de base (hex le plus proche).
        if hypot(pts[i][0] - bx, pts[i][1] - by) - radii[i] > global_radius:
            flags[i] = True
    return flags


def _coherency_flags_footprint(
    models: List[Dict[str, Any]],
    game_state: Dict[str, Any],
    coh: int,
    coh_max: int,
    min_neighbors: int,
) -> List[bool]:
    """Flags par-fig en distance HEX empreinte-a-empreinte (« closest part of base », 01.04) via
    min_distance_between_sets. 2e puce : au moins une autre fig a > coh_max."""
    from engine.hex_utils import min_distance_between_sets
    n = len(models)
    footprints = [
        _compute_unit_occupied_hexes(int(m["col"]), int(m["row"]), m, game_state)
        for m in models
    ]
    neighbor_count = [0] * n
    too_far = [False] * n
    for i in range(n):
        for j in range(i + 1, n):
            d = min_distance_between_sets(footprints[i], footprints[j], max_distance=coh_max)
            if d <= coh:
                neighbor_count[i] += 1
                neighbor_count[j] += 1
            if d > coh_max:
                too_far[i] = True
                too_far[j] = True
    return [neighbor_count[i] < min_neighbors or too_far[i] for i in range(n)]


def is_base_to_base(col_a: int, row_a: int, col_b: int, row_b: int) -> bool:
    """B2B: hexes directement adjacents (distance hex == 1).
    Strictement plus contraignant que l Engagement Range."""
    return calculate_hex_distance(col_a, row_a, col_b, row_b) == BASE_TO_BASE_SUBHEX


# ============================================================================
# MODEL-LEVEL HELPERS (squad.md PR1 1b)
# ============================================================================
# Source de verite par-figurine = models_cache[model_id]. Source de verite
# agregee par-escouade = units_cache[squad_id]. Toute mutation par-figurine
# DOIT passer par ces helpers pour garder les deux caches synchronises.


def is_model_alive(model_id: str, game_state: Dict[str, Any]) -> bool:
    """True si la figurine est presente dans models_cache."""
    require_key(game_state, "models_cache")
    return model_id in game_state["models_cache"]


# ----------------------------------------------------------------------------
# squad_cache: agregats par escouade (PR1 1c)
# ----------------------------------------------------------------------------


def _compute_squad_cache_entry(
    game_state: Dict[str, Any], squad_id: str
) -> Dict[str, Any]:
    """Recompute complet d'une entree squad_cache depuis models_cache.

    Centroide = moyenne des positions des figurines vivantes.
    is_coherent = booleen recompute via validate_squad_coherency.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    model_ids = squad_models.get(squad_id, [])  # get allowed
    alive = [models_cache[m] for m in model_ids if m in models_cache]
    n = len(alive)
    if n == 0:
        return {
            "is_coherent": True,  # escouade morte: pas de violation
            "model_count": 0,
            "model_count_at_start": 0,
            "oc_total": 0,
            "centroid_col": 0.0,
            "centroid_row": 0.0,
        }
    centroid_col = sum(int(m["col"]) for m in alive) / float(n)
    centroid_row = sum(int(m["row"]) for m in alive) / float(n)
    oc_total = sum(int(m["OC"]) for m in alive)
    is_coherent = validate_squad_coherency(game_state, squad_id)
    return {
        "is_coherent": is_coherent,
        "model_count": n,
        "model_count_at_start": 0,  # remplace par caller a l'init; preserve sinon
        "oc_total": oc_total,
        "centroid_col": centroid_col,
        "centroid_row": centroid_row,
    }


def _recompute_squad_cache(game_state: Dict[str, Any], squad_id: str) -> None:
    """Recalcule squad_cache[squad_id] tout en preservant model_count_at_start.

    A appeler depuis destroy_model et update_model_position (les deux seuls
    points d'ecriture de presence/position).
    Mirror OC_TOTAL vers units_cache si l escouade est vivante.
    """
    squad_cache = game_state.get("squad_cache")
    if squad_cache is None:
        return  # pas encore initialise (ex: avant build_units_cache)
    new_entry = _compute_squad_cache_entry(game_state, squad_id)
    old_entry = squad_cache.get(squad_id)
    if old_entry is not None and "model_count_at_start" in old_entry:
        new_entry["model_count_at_start"] = old_entry["model_count_at_start"]
    squad_cache[squad_id] = new_entry
    # Mirror OC_TOTAL → units_cache (cf. spec §"Contrat units_cache").
    units_entry = game_state.get("units_cache", {}).get(squad_id)  # get allowed
    if units_entry is not None:
        units_entry["OC_TOTAL"] = new_entry["oc_total"]


def validate_squad_coherency(game_state: Dict[str, Any], squad_id: str) -> bool:
    """Recalcul independant de la coherency d'une escouade.

    Ne lit PAS squad_cache["is_coherent"] — recompute depuis models_cache.

    Regles officielles (03.03), distance horizontale uniquement (moteur 2D) :
      - <= 1 fig : coherente d'office.
      - chaque fig : >= squad_min_neighbors voisin(s) a <= unit_model_cohesion_range,
        ET aucune fig a > unit_global_cohesion_range.
    Logique deleguee a _positions_in_coherency (source unique partagee avec le plan).
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    model_ids = squad_models.get(squad_id, [])  # get allowed
    alive = [models_cache[m] for m in model_ids if m in models_cache]
    return _positions_in_coherency(alive, game_state)


def _recompute_squad_occupied_hexes(game_state: Dict[str, Any], squad_id: str) -> None:
    """Recalcule occupied_hexes (union des footprints de toutes les figs vivantes)
    ET occupied_hexes_by_model (map model_id -> position courante de la figurine),
    depuis models_cache.

    Fix F2 (audit) : occupied_hexes doit couvrir TOUTES les figs du squad, pas
    seulement le footprint de l'ancre. Sinon collisions inter-squads ignorent
    les figs non-ancres.

    occupied_hexes_by_model est la source de vérité par-modèle consommée par le
    frontend. Doit rester synchronisée avec models_cache à chaque mutation de
    position (move, charge, advance, pile-in).

    Egalement met a jour occupation_map (reverse lookup cell -> unit_id).
    Idempotent. Pas d'effet si squad_id absent du units_cache.
    """
    units_cache = game_state.get("units_cache", {})  # get allowed
    entry = units_cache.get(squad_id)
    if entry is None:
        return
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    base_shape = entry["BASE_SHAPE"]
    base_size = entry["BASE_SIZE"]
    orientation = int(entry.get("orientation", 0))  # get allowed
    unit_stub = {
        "BASE_SHAPE": base_shape,
        "BASE_SIZE": base_size,
        "orientation": orientation,
    }
    old_occupied = entry.get("occupied_hexes", set())
    new_occupied: Set[Tuple[int, int]] = set()
    new_by_model: Dict[str, Tuple[int, int]] = {}
    for mid in squad_models.get(squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is None:
            continue
        m_col = int(m["col"])
        m_row = int(m["row"])
        new_by_model[mid] = (m_col, m_row)
        fp = _compute_unit_occupied_hexes(m_col, m_row, unit_stub, game_state)
        new_occupied.update(fp)
    entry["occupied_hexes"] = new_occupied
    entry["occupied_hexes_by_model"] = new_by_model
    # Sync occupation_map (retire cellules disparues, ajoute nouvelles)
    occ_map = game_state.get("occupation_map")
    if occ_map is not None:
        for cell in old_occupied:
            if cell not in new_occupied and occ_map.get(cell) == squad_id:
                del occ_map[cell]
        for cell in new_occupied:
            occ_map[cell] = squad_id


def translate_squad_to_destination(
    game_state: Dict[str, Any], squad_id: str, dest_col: int, dest_row: int
) -> None:
    """Déplacement rigide d'une escouade : translate toutes les figurines vivantes
    par le delta (dest - ancien_ancre), puis resync caches.

    Sémantique : "l'escouade entière bouge vers (dest_col, dest_row)". Préserve
    la formation relative entre figurines. À utiliser pour les actions de
    mouvement (move standard, charge, advance, pile-in, move_after_shooting).

    À NE PAS confondre avec update_units_cache_position seul, qui ne met à jour
    que l'ancre — utilisé après une mort de figurine pour resync l'ancre sans
    toucher aux figs survivantes.
    """
    units_cache = game_state.get("units_cache", {})  # get allowed
    entry = units_cache.get(squad_id)
    if entry is None:
        return
    norm_dest_col, norm_dest_row = normalize_coordinates(int(dest_col), int(dest_row))
    old_col = int(entry.get("col", norm_dest_col))
    old_row = int(entry.get("row", norm_dest_row))
    delta_col = norm_dest_col - old_col
    delta_row = norm_dest_row - old_row
    if delta_col != 0 or delta_row != 0:
        models_cache = require_key(game_state, "models_cache")
        squad_models = require_key(game_state, "squad_models")
        for mid in squad_models.get(squad_id, []):  # get allowed
            m = models_cache.get(mid)
            if m is None:
                continue
            if int(m.get("HP_CUR", 0)) <= 0:  # get allowed
                continue
            m["col"] = int(m["col"]) + delta_col
            m["row"] = int(m["row"]) + delta_row
    # Update anchor first (sets entry.col/row, entry.occupied_hexes = anchor footprint).
    update_units_cache_position(game_state, squad_id, norm_dest_col, norm_dest_row)
    # Then override occupied_hexes (union de toutes les figs) + occupied_hexes_by_model
    # depuis models_cache déplacés. Ordre important : ce 2e appel écrase ce qui doit l'être.
    _recompute_squad_occupied_hexes(game_state, squad_id)


def _recompute_squad_hp_total(game_state: Dict[str, Any], squad_id: str) -> int:
    """Somme des HP_CUR des figurines vivantes d'une escouade.

    Lit models_cache via squad_models pour eviter O(N_total) scan.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    model_ids = squad_models.get(squad_id, [])  # get allowed
    total = 0
    for mid in model_ids:
        m = models_cache.get(mid)
        if m is not None:
            total += int(m["HP_CUR"])
    return total


def _recompute_squad_anchor(game_state: Dict[str, Any], squad_id: str) -> Optional[Tuple[int, int]]:
    """Position de l ancre = figurine vivante de plus petit index.

    Retourne (col, row) ou None si toutes les figurines sont mortes.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    for mid in squad_models.get(squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is not None:
            return (int(m["col"]), int(m["row"]))
    return None


def update_model_position(
    game_state: Dict[str, Any], model_id: str, col: int, row: int
) -> None:
    """Met a jour la position d une figurine et propage a units_cache si ancre.

    Pour les escouades mono-figurine, met aussi a jour units_cache directement.
    Pour les multi-figurines (futures tranches), n update units_cache que si la
    figurine est l ancre courante (index minimum vivant).
    """
    require_key(game_state, "models_cache")
    model = game_state["models_cache"].get(model_id)
    if model is None:
        raise KeyError(f"update_model_position: model {model_id} not in models_cache (dead/absent)")
    norm_col, norm_row = normalize_coordinates(int(col), int(row))
    model["col"] = norm_col
    model["row"] = norm_row

    squad_id = str(model["squad_id"])
    # PR4 4e-i : sync occupied_hexes_by_model
    units_entry_oh = game_state.get("units_cache", {}).get(squad_id)  # get allowed
    if units_entry_oh is not None:
        oh_by_model = units_entry_oh.setdefault("occupied_hexes_by_model", {})
        oh_by_model[model_id] = (norm_col, norm_row)
    # F2 fix (audit) : recalcule occupied_hexes pour refleter TOUTES les figs
    _recompute_squad_occupied_hexes(game_state, squad_id)
    anchor = _recompute_squad_anchor(game_state, squad_id)
    if anchor is not None:
        anchor_col, anchor_row = anchor
        # Propage uniquement si l ancre a vraiment bouge — evite recompute
        # inutile pour les figurines non-ancres.
        units_entry = game_state.get("units_cache", {}).get(squad_id)  # get allowed
        if units_entry is not None and (
            int(units_entry.get("col", -1)) != anchor_col
            or int(units_entry.get("row", -1)) != anchor_row
        ):
            update_units_cache_position(game_state, squad_id, anchor_col, anchor_row)
    _recompute_squad_cache(game_state, squad_id)


def update_model_hp(game_state: Dict[str, Any], model_id: str, new_hp_cur: int) -> None:
    """Update HP d une figurine et propage le total a units_cache.

    Si HP <= 0 : appelle destroy_model (reason='combat').
    Sinon : met a jour models_cache + units_cache HP_CUR (somme du squad).
    """
    require_key(game_state, "models_cache")
    model = game_state["models_cache"].get(model_id)
    if model is None:
        raise KeyError(f"update_model_hp: model {model_id} not in models_cache (dead/absent)")
    effective_hp = max(0, int(new_hp_cur))
    if effective_hp <= 0:
        destroy_model(game_state, model_id, reason="combat")
        return
    model["HP_CUR"] = effective_hp
    squad_id = str(model["squad_id"])
    squad_total = _recompute_squad_hp_total(game_state, squad_id)
    units_entry = game_state.get("units_cache", {}).get(squad_id)  # get allowed
    if units_entry is not None:
        units_entry["HP_CUR"] = squad_total


def destroy_model(game_state: Dict[str, Any], model_id: str, reason: str) -> None:
    """Retire une figurine du jeu et cascade les mises a jour.

    reason ∈ {"combat", "coherency_removal", "deployment_no_space"}

    Etapes (ordre critique) :
      1. Retire l entree de models_cache.
      2. Retire model_id de squad_models[squad_id].
      3. Recalcule l ancre de l escouade si la figurine detruite etait l ancre,
         et propage la nouvelle position a units_cache.
      4. Met a jour units_cache["HP_CUR"] = somme des HP des figurines vivantes.
      5. Si derniere figurine du squad : appelle remove_from_units_cache.

    Le scoring/reward (reason=="combat") et le retrait reglementaire
    (reason=="coherency_removal") sont distingues pour PR3+ — pour PR1 1b on
    enregistre simplement reason dans le debug log.
    """
    require_key(game_state, "models_cache")
    require_key(game_state, "squad_models")
    valid_reasons = ("combat", "coherency_removal", "deployment_no_space", "hazard")
    if reason not in valid_reasons:
        raise ValueError(f"destroy_model: invalid reason {reason!r}, expected one of {valid_reasons}")

    model = game_state["models_cache"].get(model_id)
    if model is None:
        raise KeyError(f"destroy_model: model {model_id} not in models_cache (already dead?)")

    squad_id = str(model["squad_id"])
    old_col = int(model["col"])
    old_row = int(model["row"])

    # 1. Retire du models_cache.
    del game_state["models_cache"][model_id]
    # 2. Retire de squad_models (preserve l ordre des autres figurines).
    squad_list = game_state["squad_models"].get(squad_id)
    if squad_list is not None and model_id in squad_list:
        squad_list.remove(model_id)
    # PR4 4e-i : sync occupied_hexes_by_model (retire entree fig morte)
    units_entry_oh = game_state.get("units_cache", {}).get(squad_id)  # get allowed
    if units_entry_oh is not None:
        oh_by_model = units_entry_oh.get("occupied_hexes_by_model")
        if oh_by_model is not None:
            oh_by_model.pop(model_id, None)
    # F2 fix (audit) : recalcule occupied_hexes apres retrait de la fig
    _recompute_squad_occupied_hexes(game_state, squad_id)

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    phase = game_state.get("phase", "?")
    add_debug_file_log(
        game_state,
        f"[MODEL DESTROY] E{episode} T{turn} {phase} model_id={model_id} squad={squad_id} "
        f"pos=({old_col},{old_row}) reason={reason}"
    )

    # 3/4/5. Cascade vers units_cache.
    units_entry = game_state.get("units_cache", {}).get(squad_id)  # get allowed
    if units_entry is None:
        return  # squad deja absent du units_cache (cas degenere)

    squad_total = _recompute_squad_hp_total(game_state, squad_id)
    if squad_total <= 0 or not game_state["squad_models"].get(squad_id):
        # Derniere figurine : retirer l escouade du units_cache + squad_cache.
        remove_from_units_cache(game_state, squad_id)
        squad_cache_local = game_state.get("squad_cache")
        if squad_cache_local is not None:
            squad_cache_local.pop(squad_id, None)
        return

    # Recalcule ancre si necessaire.
    anchor = _recompute_squad_anchor(game_state, squad_id)
    if anchor is not None:
        anchor_col, anchor_row = anchor
        if int(units_entry.get("col", -1)) != anchor_col or int(units_entry.get("row", -1)) != anchor_row:
            update_units_cache_position(game_state, squad_id, anchor_col, anchor_row)

    units_entry["HP_CUR"] = squad_total
    _recompute_squad_cache(game_state, squad_id)


# ============================================================================
# MULTI-MODEL MOVEMENT PLAN (squad.md PR2 2a)
# ============================================================================
# Pipeline mutualise pour Normal/Advance/Fall Back (et plus tard Charge/Pile In/
# Consolidation). Transaction atomique : dry-run complet → validation → commit
# en une passe. Aucune ecriture cache avant validation.


DEFAULT_MOVE_CONSTRAINTS: Dict[str, Any] = {
    "budget_per_model": None,    # None = pas de check budget
    "forbid_enemy_er": True,
    "require_coherency": True,
    "allow_walls": False,
    "allow_collisions": False,
}


def build_rigid_plan(
    anchor_dest_col: int,
    anchor_dest_row: int,
    squad_id: str,
    game_state: Dict[str, Any],
) -> Optional[List[Tuple[str, int, int]]]:
    """Translation rigide depuis l'ancre — Normal/Advance/Fall Back.

    L ancre = figurine vivante de plus petit index (cf. _recompute_squad_anchor).
    Toutes les figurines suivent le meme vecteur (dx, dy) = anchor_dest - anchor_origin.

    Returns list[(model_id, new_col, new_row)] ou None si squad sans figurine vivante.
    AUCUNE validation ici — voir validate_move_plan.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    mids = squad_models.get(squad_id, [])  # get allowed
    alive_mids = [m for m in mids if m in models_cache]
    if not alive_mids:
        return None
    anchor_id = alive_mids[0]
    anchor_origin_col = int(models_cache[anchor_id]["col"])
    anchor_origin_row = int(models_cache[anchor_id]["row"])
    dest_col, dest_row = normalize_coordinates(int(anchor_dest_col), int(anchor_dest_row))
    dx = dest_col - anchor_origin_col
    dy = dest_row - anchor_origin_row
    plan: List[Tuple[str, int, int]] = []
    for mid in alive_mids:
        m = models_cache[mid]
        new_col, new_row = normalize_coordinates(int(m["col"]) + dx, int(m["row"]) + dy)
        plan.append((mid, new_col, new_row))
    return plan


def _validate_plan_coherency(
    plan_positions: Dict[str, Tuple[int, int]], game_state: Dict[str, Any]
) -> bool:
    """Verifie la coherency d un plan (positions hypothetiques, sans toucher caches).

    Empreinte de chaque fig recalculee a sa position hypothetique (base/orientation
    lues dans models_cache). Memes regles que validate_squad_coherency (deleguees a
    _positions_in_coherency).
    """
    models_cache = require_key(game_state, "models_cache")
    models = [
        {**models_cache[mid], "col": int(col), "row": int(row)}
        for mid, (col, row) in plan_positions.items()
    ]
    return _positions_in_coherency(models, game_state)


def validate_move_plan(
    plan: List[Tuple[str, int, int]],
    game_state: Dict[str, Any],
    constraints: Optional[Dict[str, Any]] = None,
) -> bool:
    """Verifie un plan multi-figurines en dry-run (aucune ecriture cache).

    Constraints (dict, defaut DEFAULT_MOVE_CONSTRAINTS) :
      - budget_per_model: int|None — distance hex max depuis position d origine
      - forbid_enemy_er: bool — interdit cellule dans ER d un ennemi
      - require_coherency: bool — coherency sur le plan final
      - allow_walls: bool — autorise traverser/finir sur un mur
      - allow_collisions: bool — autorise overlap avec autres escouades

    Validation atomique : un seul echec → False. Aucune ecriture.
    """
    c = dict(DEFAULT_MOVE_CONSTRAINTS)
    if constraints:
        c.update(constraints)
    if not plan:
        return False

    models_cache = require_key(game_state, "models_cache")
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())

    first_model = models_cache.get(plan[0][0])
    if first_model is None:
        return False
    squad_id = str(first_model["squad_id"])
    player = int(first_model["player"])

    enemy_er_zone: Optional[Set[Tuple[int, int]]] = None
    if c["forbid_enemy_er"]:
        cache_key = f"enemy_adjacent_hexes_player_{player}"
        enemy_er_zone = require_key(game_state, cache_key)

    # Cellules occupees par les AUTRES escouades (collisions interdites).
    other_occupied: Set[Tuple[int, int]] = set()
    if not c["allow_collisions"]:
        units_cache = game_state.get("units_cache", {})  # get allowed
        for sid, entry in units_cache.items():
            if str(sid) == squad_id:
                continue
            occ = entry.get("occupied_hexes")
            if occ:
                for cell in occ:
                    other_occupied.add((int(cell[0]), int(cell[1])))

    # Budget per-model depuis position d origine actuelle.
    origin_positions: Dict[str, Tuple[int, int]] = {}
    if c["budget_per_model"] is not None:
        for mid, _, _ in plan:
            m = models_cache.get(mid)
            if m is None:
                return False
            origin_positions[mid] = (int(m["col"]), int(m["row"]))

    new_cells: Set[Tuple[int, int]] = set()
    for mid, nc, nr in plan:
        if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
            return False
        cell = (nc, nr)
        if not c["allow_walls"] and wall_hexes and cell in wall_hexes:
            return False
        if not c["allow_collisions"] and cell in other_occupied:
            return False
        if c["forbid_enemy_er"] and enemy_er_zone and cell in enemy_er_zone:
            return False
        if cell in new_cells:
            return False  # collision intra-plan (deux figs sur meme hex)
        new_cells.add(cell)
        if c["budget_per_model"] is not None:
            o_col, o_row = origin_positions[mid]
            if calculate_hex_distance(o_col, o_row, nc, nr) > int(c["budget_per_model"]):
                return False

    if c["require_coherency"]:
        plan_positions = {mid: (nc, nr) for mid, nc, nr in plan}
        if not _validate_plan_coherency(plan_positions, game_state):
            return False

    return True


def apply_snap_corrections(
    plan: List[Tuple[str, int, int]],
    game_state: Dict[str, Any],
    radius: int = 2,
    constraints: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, int, int]]:
    """Pour chaque figurine invalide individuellement, cherche un hex valide proche.

    Snap par-figurine sur contraintes locales (bounds, walls, collisions, enemy_er) —
    pas de garantie de coherency globale (responsabilite UX pour ajustement manuel).
    Ordre : par index de figurine dans le plan (deterministe).

    Recherche : anneaux concentriques de distance hex 1..radius autour de la destination
    invalide. Premier hex valide retenu (ordre balayage col puis row).

    Si aucun hex valide trouve dans le rayon, la figurine garde sa destination originale
    (l UX affichera le voile rouge).
    """
    c = dict(DEFAULT_MOVE_CONSTRAINTS)
    if constraints:
        c.update(constraints)
    c_individual = dict(c)
    c_individual["require_coherency"] = False

    corrected: List[Tuple[str, int, int]] = []
    for mid, nc, nr in plan:
        if validate_move_plan([(mid, nc, nr)], game_state, c_individual):
            corrected.append((mid, nc, nr))
            continue
        found_cell: Optional[Tuple[int, int]] = None
        for r in range(1, int(radius) + 1):
            for d_col in range(-r, r + 1):
                for d_row in range(-r, r + 1):
                    if max(abs(d_col), abs(d_row)) != r:
                        continue
                    cand_col, cand_row = nc + d_col, nr + d_row
                    if validate_move_plan([(mid, cand_col, cand_row)], game_state, c_individual):
                        found_cell = (cand_col, cand_row)
                        break
                if found_cell is not None:
                    break
            if found_cell is not None:
                break
        if found_cell is not None:
            corrected.append((mid, found_cell[0], found_cell[1]))
        else:
            corrected.append((mid, nc, nr))
    return corrected


def roll_hazard_for_unit(unit_id: str, game_state: Dict[str, Any], auto_resolve: bool) -> int:
    """Hazard roll pour une unité (règle 06.03) — avant un Desperate Escape fall-back.

    Tire 1D6 par figurine vivante simultanément.
    Sur 1-2 : 1 mortal wound (ou 3 si toute l'unité est MONSTER ou VEHICLE).
    Les MW sont attribuées via la séquence 06.02 (``allocate_mortal_wounds``) :
    ``auto_resolve`` est propagé (IA/gym = choix déterministe ; humain = prompt étape 3).
    Retourne le total de mortal wounds rollés (avant arrêt éventuel si l'unité meurt).
    """
    import random
    squad_models = require_key(game_state, "squad_models")
    models_cache = require_key(game_state, "models_cache")
    unit_id_str = str(unit_id)
    if unit_id_str not in squad_models:
        raise KeyError(f"roll_hazard_for_unit: unit {unit_id} not in squad_models")
    alive_count = sum(1 for mid in squad_models[unit_id_str] if mid in models_cache)
    if alive_count == 0:
        return 0
    units = require_key(game_state, "units")
    try:
        unit = next(u for u in units if str(u.get("id")) == str(unit_id))
    except StopIteration:
        raise KeyError(f"roll_hazard_for_unit: unit {unit_id} not found in game_state['units']")
    # UNIT_KEYWORDS = liste d'objets {"keywordId": "..."} (cf. game_state). Pattern canonique.
    keyword_ids = {
        str(require_key(kw, "keywordId")).strip().lower()
        for kw in require_key(unit, "UNIT_KEYWORDS")
    }
    wounds_per_fail = 3 if ("monster" in keyword_ids or "vehicle" in keyword_ids) else 1
    rolls = [random.randint(1, 6) for _ in range(alive_count)]
    fails = sum(1 for r in rolls if r <= 2)
    total_wounds = fails * wounds_per_fail
    col = int(unit.get("col", -1))
    row = int(unit.get("row", -1))
    msg = (
        f"Unit {unit_id}({col},{row}) [HAZARD] roll (Desperate Escape): {alive_count} rolls "
        f"- {fails} fail(s) - {total_wounds} mortal wound(s)"
    )
    # Détails par-figurine (06.02) : remplis pendant l'attribution, comme shootDetails au tir.
    # La ligne de log est émise À LA FIN de l'allocation (calquée sur le tir), pas au roll :
    # on diffère le payload dans game_state["hazard_pending_log"] tant que l'allocation court.
    details: List[Dict[str, Any]] = []
    log_payload = {
        "type": "hazard",
        "message": msg,
        "turn": require_key(game_state, "turn"),
        "phase": require_key(game_state, "phase"),
        "unitId": int(unit_id),
        "player": int(unit.get("player", -1)),
        "result": f"{total_wounds} MW",
        "hazardDetails": details,
    }
    if total_wounds <= 0:
        append_action_log(game_state, log_payload)  # rien à allouer : émission immédiate
        return total_wounds
    if auto_resolve:
        # IA / gym : attribution 06.02 deterministe, sans prompt. Retrait figurine par
        # figurine via destroy_model (PAS l'agregat units_cache qui ne retirait rien en multi-fig).
        game_state["hazard_pending_log"] = log_payload
        allocate_mortal_wounds(game_state, str(unit_id), total_wounds, auto_resolve, details)
        _finalize_hazard_log(game_state)  # auto : termine sans clic → emission immediate
        return total_wounds
    # Defenseur humain : allocation manuelle des pertes (groupes 05.03 + declaration d'ordre +
    # choix de figurine), calquee sur le tir. log_payload est emis a la FIN de l'allocation,
    # complete de ses hazardDetails (cf. build_manual_hazard_allocation).
    build_manual_hazard_allocation(game_state, str(unit_id), total_wounds, log_payload)
    return total_wounds


def _finalize_hazard_log(game_state: Dict[str, Any]) -> None:
    """Émet la ligne de log hazard différée, une fois l'attribution des MW terminée
    (calquée sur le tir : la ligne n'apparaît qu'avec ses détails complets). No-op si
    aucun payload en attente."""
    payload = game_state.pop("hazard_pending_log", None)
    if payload is not None:
        append_action_log(game_state, payload)


def select_eligible_models(game_state: Dict[str, Any], squad_id: str) -> List[str]:
    """Figurines éligibles à recevoir le prochain mortal wound (séquence 06.02).

    Ordre 40k « Select Model » — première catégorie non vide :
      1. non-CHARACTER déjà blessée (HP_CUR < HP_MAX) ;
      2. sinon non-CHARACTER (toutes) ;
      3. sinon CHARACTER déjà blessée ;
      4. sinon CHARACTER (toutes).

    Retourne les model_ids de cette catégorie. Le choix du joueur n'existe que si
    ``len(...) >= 2`` (figs également éligibles) ; ``len == 1`` = figurine forcée.
    Liste vide = unité sans figurine vivante (détruite).
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    sid = str(squad_id)
    if sid not in squad_models:
        raise KeyError(f"select_eligible_models: unit {squad_id} not in squad_models")
    alive = [m for m in squad_models[sid] if m in models_cache]
    non_char = [m for m in alive if not _is_character_role(models_cache[m].get("role"))]
    char = [m for m in alive if _is_character_role(models_cache[m].get("role"))]

    def wounded(mids: List[str]) -> List[str]:
        return [m for m in mids
                if int(models_cache[m]["HP_CUR"]) < int(models_cache[m]["HP_MAX"])]

    for group in (wounded(non_char), non_char, wounded(char), char):
        if group:
            return list(group)
    return []


def allocate_mortal_wounds(
    game_state: Dict[str, Any], squad_id: str, n_wounds: int, auto_resolve: bool,
    details_sink: List[Dict[str, Any]],
) -> int:
    """Attribue ``n_wounds`` mortal wounds à une unité (séquence 06.02), une par une, en
    mode AUTO uniquement (IA / gym). Le défenseur humain passe par
    ``build_manual_hazard_allocation`` (allocation manuelle des pertes calquée sur le tir).

    - ``auto_resolve=True`` : choix déterministe ``eligibles[0]`` quand plusieurs figs sont
      également éligibles.
    - ``auto_resolve=False`` : non supporté ici → erreur explicite (root cause : appeler
      ``build_manual_hazard_allocation``).

    Chaque MW retire 1 HP à la figurine choisie ; la figurine n'est retirée du jeu
    (``destroy_model`` reason='hazard') qu'à ``HP_CUR == 0``. On s'arrête si l'unité
    est détruite avant d'avoir attribué toutes les MW (06.02 : « until … destroyed »).

    ``details_sink`` reçoit 1 record ``{modelId, col, row, died}`` par MW appliquée
    (col/row capturés AVANT destroy) — alimente ``hazardDetails`` du log, comme le tir.

    Retourne le nombre de mortal wounds réellement attribués.
    """
    models_cache = require_key(game_state, "models_cache")
    sid = str(squad_id)
    remaining = int(n_wounds)
    applied = 0
    while remaining > 0:
        eligibles = select_eligible_models(game_state, sid)
        if not eligibles:
            break  # unité détruite : plus rien à blesser
        if not auto_resolve:
            raise ValueError(
                "allocate_mortal_wounds: chemin humain non supporté ici "
                "(utiliser build_manual_hazard_allocation pour le défenseur humain)"
            )
        target = eligibles[0]
        new_hp = int(models_cache[target]["HP_CUR"]) - 1
        col = models_cache[target].get("col")  # get allowed
        row = models_cache[target].get("row")  # get allowed
        if new_hp <= 0:
            destroy_model(game_state, target, reason="hazard")
            died = True
        else:
            update_model_hp(game_state, target, new_hp)
            died = False
        details_sink.append({"modelId": str(target), "col": col, "row": row, "died": died})
        applied += 1
        remaining -= 1
    return applied


def is_unit_at_half_strength(unit_id: str, game_state: Dict[str, Any]) -> bool:
    """Vérifie si une unité est à la half-strength (règle 08.03).

    - Multi-modèles (model_count_at_start > 1) : alive <= initial / 2
    - Mono-modèle  (model_count_at_start == 1) : HP_CUR <= HP_MAX / 2
    """
    squad_cache = require_key(game_state, "squad_cache")
    entry = squad_cache.get(str(unit_id))
    if entry is None:
        raise KeyError(f"is_unit_at_half_strength: unit {unit_id} not in squad_cache")
    count_start = int(entry["model_count_at_start"])
    count_now = int(entry["model_count"])
    if count_start > 1:
        return count_now <= count_start / 2
    # Mono-modèle : check HP. HP_CUR vient de units_cache (source de vérité vivante,
    # mise à jour à chaque dégât) ; HP_MAX est immuable et lu sur l'unité.
    units_cache = require_key(game_state, "units_cache")
    cache_entry = units_cache.get(str(unit_id))
    if cache_entry is None:
        raise KeyError(f"is_unit_at_half_strength: unit {unit_id} not in units_cache")
    units = require_key(game_state, "units")
    try:
        unit = next(u for u in units if str(u.get("id")) == str(unit_id))
    except StopIteration:
        raise KeyError(f"is_unit_at_half_strength: unit {unit_id} not found in game_state['units']")
    hp_cur = int(require_key(cache_entry, "HP_CUR"))
    hp_max = int(require_key(unit, "HP_MAX"))
    return hp_cur <= hp_max / 2


def roll_battle_shock(unit_id: str, game_state: Dict[str, Any]) -> bool:
    """Battle-shock roll pour une unité (règle 01.07).

    Tire 2D6 et compare au LD de l'unité.
    Si résultat >= LD : succès, l'unité n'est PAS battle-shocked.
    Si résultat < LD  : échec, l'unité devient battle-shocked.

    Retourne True si l'unité est désormais battle-shocked, False sinon.
    """
    import random
    units = require_key(game_state, "units")
    try:
        unit = next(u for u in units if str(u.get("id")) == str(unit_id))
    except StopIteration:
        raise KeyError(f"roll_battle_shock: unit {unit_id} not found in game_state['units']")
    ld = int(require_key(unit, "LD"))
    roll = random.randint(1, 6) + random.randint(1, 6)
    battle_shocked = roll < ld
    unit["battle_shocked"] = battle_shocked

    col = int(unit.get("col", -1))
    row = int(unit.get("row", -1))
    result_str = "FAIL" if battle_shocked else "SUCCESS"
    msg = f"Unit {unit_id}({col},{row}) did a BATTLE-SHOCK test. Ld: {ld}+ - Roll: {roll} - {result_str}"
    append_action_log(game_state, {
        "type": "battle_shock",
        "message": msg,
        "turn": require_key(game_state, "turn"),
        "phase": "command",
        "unitId": int(unit_id),
        "player": int(unit.get("player", -1)),
        "result": result_str,
    })

    return battle_shocked


def desperate_escape_pre_move(
    squad_id: str, game_state: Dict[str, Any], was_engaged: bool, auto_resolve: bool
) -> Tuple[bool, bool, int]:
    """Desperate Escape (09.07) — phase AVANT le mouvement.

    Une unité engagée ET battle-shocked qui fait un Fall Back doit faire un Desperate Escape :
    un hazard roll (06.03) par figurine est résolu AVANT de bouger. ``auto_resolve`` pilote
    l'attribution 06.02 (IA/gym déterministe ; humain → prompt étape 3).

    Retourne ``(is_desperate, is_alive, hazard_wounds)`` :
    - ``is_desperate`` : True si l'unité fait un Desperate Escape (engagée + battle-shocked).
    - ``is_alive`` : False si le hazard a détruit l'unité (le move ne doit alors PAS avoir lieu).
    - ``hazard_wounds`` : total de mortal wounds infligés par le hazard (0 si non-desperate).
    """
    unit = get_unit_by_id(game_state, str(squad_id))
    if unit is None:
        raise KeyError(f"desperate_escape_pre_move: unit {squad_id} not found")
    is_desperate = bool(was_engaged) and bool(unit.get("battle_shocked", False))
    if not is_desperate:
        return False, True, 0
    hazard_wounds = roll_hazard_for_unit(str(squad_id), game_state, auto_resolve)
    return True, is_unit_alive(str(squad_id), game_state), hazard_wounds


def desperate_escape_post_move(squad_id: str, game_state: Dict[str, Any]) -> None:
    """Desperate Escape (09.07) — phase APRÈS le mouvement.

    Si l'unité n'est PAS battle-shocked, elle doit faire un battle-shock roll (01.07). No-op tant
    que le Desperate Escape n'est déclenché que pour des unités déjà battle-shocked (cf. 09.07 :
    Ordered Retreat pour non-shocked, Desperate Escape sinon)."""
    unit = get_unit_by_id(game_state, str(squad_id))
    if unit is not None and not unit.get("battle_shocked", False):
        roll_battle_shock(str(squad_id), game_state)


def roll_advance_for_squad(squad_id: str, game_state: Dict[str, Any]) -> int:
    """Roll 1D6 partage par l escouade pour un Advance move.

    Stocke le resultat dans game_state["current_advance_roll"] pour les logs/replay,
    sera efface apres commit_move (responsabilite du caller).
    """
    import random
    roll = random.randint(1, 6)
    game_state["current_advance_roll"] = int(roll)
    return int(roll)


def get_squad_move_budget(
    squad_id: str,
    game_state: Dict[str, Any],
    move_type: str,
    advance_roll: Optional[int] = None,
) -> int:
    """Budget de deplacement par figurine (en subhexes) pour une escouade.

    - "normal" / "fall_back" → MOVE
    - "advance" → MOVE + advance_roll (caller doit fournir advance_roll)
    - "charge" / "pile_in" / "consolidation" → contraintes specifiques (PR2 2c / PR3)
      Pour pile_in/consolidation: 3 inches en subhexes.
      Pour charge: la valeur est charge_roll 2D6, caller la fournit via advance_roll
      (le parametre est polysemique : budget D6 partage par l escouade).

    MOVE est deja en subhexes dans le moteur (cf. game_state.py:118
    `"MOVE": config["MOVE"] * scale`).
    """
    valid_types = ("normal", "advance", "fall_back", "charge", "pile_in", "consolidation")
    if move_type not in valid_types:
        raise ValueError(f"get_squad_move_budget: invalid move_type {move_type!r}")
    if move_type in ("pile_in", "consolidation"):
        ish = int(require_key(game_state, "inches_to_subhex"))
        return 3 * ish
    units = game_state.get("units", [])  # get allowed
    unit = next((u for u in units if str(u.get("id")) == str(squad_id)), None)  # get allowed
    if unit is None:
        raise KeyError(f"get_squad_move_budget: squad {squad_id} not in game_state['units']")
    move_stat = int(require_key(unit, "MOVE"))
    # Take to the skies (Règles 21.03) : si l'escouade a déclaré le vol ce tour, retrancher 2"
    # de la distance max du move (normal/advance/fall_back). Le malus est en subhexes comme MOVE.
    tts_penalty = 0
    if str(squad_id) in game_state.get("units_took_to_skies", set()):
        ish = int(require_key(game_state, "inches_to_subhex"))
        tts_penalty = 2 * ish
    if move_type == "advance":
        if advance_roll is None:
            raise ValueError("get_squad_move_budget: advance_roll required for move_type='advance'")
        # advance_roll est en POUCES (1D6) → convertir en subhexes comme MOVE.
        ish = int(require_key(game_state, "inches_to_subhex"))
        return max(0, move_stat + int(advance_roll) * ish - tts_penalty)
    if move_type == "charge":
        if advance_roll is None:
            raise ValueError("get_squad_move_budget: charge_roll (passed via advance_roll) required for move_type='charge'")
        # F5 fix (audit) : charge_roll est en POUCES (2D6), convertir en subhexes
        # pour rester coherent avec les autres move_types qui retournent subhexes.
        ish = int(require_key(game_state, "inches_to_subhex"))
        return int(advance_roll) * ish
    return max(0, move_stat - tts_penalty)  # normal, fall_back


def execute_squad_move(
    squad_id: str,
    anchor_dest_col: int,
    anchor_dest_row: int,
    move_type: str,
    game_state: Dict[str, Any],
    advance_roll: Optional[int] = None,
    extra_constraints: Optional[Dict[str, Any]] = None,
) -> bool:
    """Pipeline complet pour Normal/Advance/Fall Back: roll → plan → validate → commit.

    Pour move_type="advance" : si advance_roll est None, le helper roll lui-meme.
    Pour fall_back : aucun roll. Pour normal : aucun roll.

    Retourne True si le move a ete commit, False si la validation a echoue
    (aucune ecriture dans ce cas — transaction atomique).
    """
    if move_type == "advance" and advance_roll is None:
        advance_roll = roll_advance_for_squad(squad_id, game_state)
    plan = build_rigid_plan(anchor_dest_col, anchor_dest_row, squad_id, game_state)
    if plan is None:
        return False
    budget = get_squad_move_budget(squad_id, game_state, move_type, advance_roll=advance_roll)
    constraints: Dict[str, Any] = {"budget_per_model": budget}
    if extra_constraints:
        constraints.update(extra_constraints)
    if not validate_move_plan(plan, game_state, constraints):
        return False
    commit_move(plan, game_state, move_type)
    # Nettoyage du roll partage apres commit reussi (cf. spec).
    if move_type == "advance":
        game_state.pop("current_advance_roll", None)
    return True


# ============================================================================
# CHARGE PLAN (squad.md PR2 2c)
# ============================================================================


def _enemy_squad_ids(game_state: Dict[str, Any], player: int) -> List[str]:
    """Liste des squad_id ennemis vivants (player != donne)."""
    out: List[str] = []
    for sid, entry in game_state.get("units_cache", {}).items():  # get allowed
        try:
            if int(entry.get("player", -1)) != int(player):
                out.append(str(sid))
        except (TypeError, ValueError):
            continue
    return out


def _squad_model_positions(game_state: Dict[str, Any], squad_id: str) -> List[Tuple[int, int]]:
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    out: List[Tuple[int, int]] = []
    for mid in squad_models.get(squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is not None:
            out.append((int(m["col"]), int(m["row"])))
    return out


def _synth_model_entry(
    game_state: Dict[str, Any],
    squad_id: str,
    model_entry: Dict[str, Any],
    col: int,
    row: int,
) -> Dict[str, Any]:
    """Entree units_cache synthetique pour UNE figurine placee en (col,row).

    SOURCE UNIQUE de l engagement par-figurine (charge, fight, pile-in, conso) :
    la geometrie de base provient du MODELE (``model_entry``), pas du squad — seul
    choix correct pour une unite a bases mixtes (perso attache a plus grande base).
    Le ``player`` est herite du squad (le modele ne le porte pas forcement). Entree
    complete (orientation incluse) pour rester valide quelle que soit la branche de
    ``unit_entries_within_engagement_zone``."""
    from engine.hex_utils import compute_occupied_hexes
    squad_entry = game_state.get("units_cache", {}).get(str(squad_id), {})  # get allowed
    shape = require_key(model_entry, "BASE_SHAPE")
    size = require_key(model_entry, "BASE_SIZE")
    orient = int(model_entry.get("orientation", 0))  # get allowed
    fp = compute_occupied_hexes(int(col), int(row), shape, size, orient)
    return {
        "id": f"_synth_{squad_id}",
        "player": int(squad_entry.get("player", -1)),  # get allowed
        "col": int(col),
        "row": int(row),
        "occupied_hexes": set(fp),
        "BASE_SHAPE": shape,
        "BASE_SIZE": size,
        "orientation": orient,
    }


CHARGE_THRESHOLD_INCHES = 12


def charge_check_eligibility(
    game_state: Dict[str, Any],
    squad_id: str,
    target_squad_ids: List[str],
) -> bool:
    """Verifie l eligibilite a charger (Regles officielles Charge Phase).

    - Au moins une figurine vivante du squad est a <= 12" d au moins une figurine
      ennemie (mesure figurine la plus proche, pas ancre).
    - Interdit si le squad est dans `units_advanced` ou `units_fled` ce tour.
    - Interdit si une figurine du squad est deja dans l ER d un ennemi (locked).
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    if not target_squad_ids:
        return False
    if str(squad_id) in game_state.get("units_advanced", set()):
        return False
    if str(squad_id) in game_state.get("units_fled", set()):
        return False
    our_positions = _squad_model_positions(game_state, squad_id)
    if not our_positions:
        return False
    ish = int(require_key(game_state, "inches_to_subhex"))
    threshold_12 = CHARGE_THRESHOLD_INCHES * ish

    # Position ennemies (tous)
    enemy_positions: List[Tuple[int, int]] = []
    for tsid in target_squad_ids:
        enemy_positions.extend(_squad_model_positions(game_state, str(tsid)))
    if not enemy_positions:
        return False
    # 12" check (portee de charge, mesure figurine la plus proche — distance centre,
    # independante de l engagement_zone)
    in_range = False
    for oc, orow in our_positions:
        for ec, er in enemy_positions:
            if calculate_hex_distance(oc, orow, ec, er) <= threshold_12:
                in_range = True
                break
        if in_range:
            break
    if not in_range:
        return False
    # Locked check : interdit si deja dans l ER (bord-a-bord) d un ennemi quelconque.
    if _squad_is_in_enemy_er(game_state, str(squad_id)):
        return False
    return True


def _hex_legal_for_charge(
    col: int,
    row: int,
    game_state: Dict[str, Any],
    squad_id: str,
    model_entry: Dict[str, Any],
    target_squad_ids: List[str],
) -> bool:
    """Cellule valide pour le placement d une figurine en cours de charge :
       - dans le plateau
       - pas un mur
       - pas occupee par une autre escouade (cible OU non) — collision physique
       - pas dans l ER d une escouade ennemie NON-cible (regle officielle)
    """
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())
    if col < 0 or row < 0 or col >= board_cols or row >= board_rows:
        return False
    cell = (col, row)
    if wall_hexes and cell in wall_hexes:
        return False
    # Collision : autres escouades (sauf nous-meme)
    units_cache = game_state.get("units_cache", {})  # get allowed
    for sid, entry in units_cache.items():
        if str(sid) == str(squad_id):
            continue
        occ = entry.get("occupied_hexes")
        if occ and cell in occ:
            return False
    # ER des escouades non-cibles (bord-a-bord) : la figurine candidate ne doit pas
    # finir dans l ER d un ennemi NON-cible.
    from engine.spatial_relations import unit_entries_within_engagement_zone
    our_player = int(units_cache.get(str(squad_id), {}).get("player", -1))  # get allowed
    ez = get_engagement_zone(game_state)
    synth = _synth_model_entry(game_state, str(squad_id), model_entry, col, row)
    targets = {str(t) for t in target_squad_ids}
    for esid in _enemy_squad_ids(game_state, our_player):
        if esid in targets:
            continue
        enemy_entry = units_cache.get(esid)
        if enemy_entry is None:
            continue
        if unit_entries_within_engagement_zone(synth, enemy_entry, ez):
            return False
    return True


def charge_build_valid_plan(
    game_state: Dict[str, Any],
    squad_id: str,
    target_squad_ids: List[str],
    charge_roll: int,
) -> Optional[List[Tuple[str, int, int]]]:
    """Plan de charge multi-figurines (transaction atomique, aucune ecriture cache).

    Ordre de traitement : par index de figurine croissant.
    Pour chaque fig :
      (a) priorite : B2B avec un modele ennemi cible (hex hexagonalement adjacent)
      (b) sinon : se rapproche du cible le plus proche, hors ER des non-cibles
    Validation finale : TOUTES les figs finissent dans l ER d au moins un modele cible
    (regle officielle : charge legale exige ER apres deplacement). Coherency verifiee
    sur le plan final.

    Retourne le plan ou None si invalide (atomic : aucune fig deplacee).
    Le caller appelle commit_move(plan, gs, 'charge') sur succes.
    """
    if charge_roll <= 0:
        return None
    if not charge_check_eligibility(game_state, squad_id, target_squad_ids):
        return None
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    units_cache = game_state.get("units_cache", {})  # get allowed
    mids = [m for m in squad_models.get(squad_id, []) if m in models_cache]  # get allowed
    if not mids:
        return None

    ish = int(require_key(game_state, "inches_to_subhex"))
    budget = int(charge_roll) * ish

    # Toutes les positions de figurines cibles
    target_positions: List[Tuple[int, int]] = []
    for tsid in target_squad_ids:
        target_positions.extend(_squad_model_positions(game_state, str(tsid)))
    if not target_positions:
        return None

    plan: List[Tuple[str, int, int]] = []
    occupied_after: Set[Tuple[int, int]] = set()  # cellules deja reservees par ce plan

    for mid in mids:
        m = models_cache[mid]
        orig_col, orig_row = int(m["col"]), int(m["row"])

        # (a) Tentative B2B : voisins immediats de chaque modele cible
        b2b_candidates: List[Tuple[int, int, int]] = []  # (dist_from_orig, col, row)
        for tc, tr in target_positions:
            for nc, nr in get_hex_neighbors(tc, tr):
                if (nc, nr) in occupied_after:
                    continue
                d_orig = calculate_hex_distance(orig_col, orig_row, nc, nr)
                if d_orig > budget:
                    continue
                if not _hex_legal_for_charge(nc, nr, game_state, squad_id, m, target_squad_ids):
                    continue
                b2b_candidates.append((d_orig, nc, nr))
        picked: Optional[Tuple[int, int]] = None
        if b2b_candidates:
            b2b_candidates.sort()  # plus proche d origine d abord
            _, pc, pr = b2b_candidates[0]
            picked = (pc, pr)
        else:
            # (b) Pas de B2B atteignable : avancer vers la cible la plus proche
            nearest_target = min(
                target_positions,
                key=lambda tp: calculate_hex_distance(orig_col, orig_row, tp[0], tp[1]),
            )
            tc, tr = nearest_target
            orig_dist_to_tgt = calculate_hex_distance(orig_col, orig_row, tc, tr)
            best_cand: Optional[Tuple[int, int, int]] = None  # (dist_to_target, col, row)
            for d in range(1, budget + 1):
                for d_col in range(-d, d + 1):
                    for d_row in range(-d, d + 1):
                        if max(abs(d_col), abs(d_row)) != d:
                            continue
                        nc = orig_col + d_col
                        nr = orig_row + d_row
                        if (nc, nr) in occupied_after:
                            continue
                        if not _hex_legal_for_charge(nc, nr, game_state, squad_id, m, target_squad_ids):
                            continue
                        cand_d = calculate_hex_distance(nc, nr, tc, tr)
                        if cand_d >= orig_dist_to_tgt:
                            continue  # doit etre strictement plus proche
                        if best_cand is None or cand_d < best_cand[0]:
                            best_cand = (cand_d, nc, nr)
                if best_cand is not None:
                    break  # premier anneau utile retenu
            if best_cand is not None:
                _, pc, pr = best_cand
                picked = (pc, pr)
        if picked is None:
            return None  # cette fig ne peut bouger legalement → charge echouee
        plan.append((mid, picked[0], picked[1]))
        occupied_after.add(picked)

    # Validation finale : chaque fig finit dans l ER (bord-a-bord) d au moins un
    # modele cible (regle officielle : charge legale exige ER apres deplacement).
    from engine.spatial_relations import unit_entries_within_engagement_zone
    ez = get_engagement_zone(game_state)
    target_entries = [
        te for te in (units_cache.get(str(t)) for t in target_squad_ids) if te is not None
    ]
    for mid, nc, nr in plan:
        synth = _synth_model_entry(game_state, str(squad_id), models_cache[mid], nc, nr)
        if not any(unit_entries_within_engagement_zone(synth, te, ez) for te in target_entries):
            return None

    # Coherency finale
    plan_positions = {mid: (nc, nr) for mid, nc, nr in plan}
    if not _validate_plan_coherency(plan_positions, game_state):
        return None

    return plan


def commit_move(
    plan: List[Tuple[str, int, int]],
    game_state: Dict[str, Any],
    move_type: str,
) -> None:
    """Applique le plan complet en une passe et positionne les flags post-move.

    Pre-condition: plan validé via validate_move_plan (ce helper ne re-valide pas).
    Flags:
        "advance"   → units_advanced.add(squad_id)
        "fall_back" → units_fled.add(squad_id)
        "normal"/"charge"/"pile_in"/"consolidation" → aucun flag
    """
    valid_types = ("normal", "advance", "fall_back", "charge", "pile_in", "consolidation")
    if move_type not in valid_types:
        raise ValueError(
            f"commit_move: invalid move_type {move_type!r}, expected one of {valid_types}"
        )
    if not plan:
        return
    models_cache = require_key(game_state, "models_cache")
    first = models_cache.get(plan[0][0])
    if first is None:
        raise KeyError(f"commit_move: anchor model {plan[0][0]} not in models_cache")
    squad_id = str(first["squad_id"])
    for mid, nc, nr in plan:
        update_model_position(game_state, mid, nc, nr)
    if move_type == "advance":
        game_state.setdefault("units_advanced", set()).add(squad_id)
    elif move_type == "fall_back":
        game_state.setdefault("units_fled", set()).add(squad_id)
    elif move_type == "charge":
        game_state.setdefault("units_charged", set()).add(squad_id)


# ============================================================================
# PENDING INTENTS — SHOOT / FIGHT (squad.md PR3 3a)
# ============================================================================
# Structures de declaration-puis-resolution pour le tir et la melee multi-figs.
# Lifecycle :
#   - Cree lors de l activation de tir/fight (squad_shooting_unit_activation_start /
#     squad_fight_unit_activation_start).
#   - Nettoye par end_activation (responsabilite du caller) — assertion en debug
#     si pending existe deja au debut d une nouvelle activation.
#   - Jamais persiste entre deux activations.


def init_pending_intents(game_state: Dict[str, Any]) -> None:
    """Initialise les dicts pending si absents. Idempotent (safe re-call)."""
    game_state.setdefault("pending_squad_shoot_intents", {})
    game_state.setdefault("pending_squad_fight_intents", {})


def assert_no_pending_shoot_intent(game_state: Dict[str, Any], squad_id: str) -> None:
    """Leve si pending_squad_shoot_intents[squad_id] existe deja.

    A appeler au debut de squad_shooting_unit_activation_start : un pending
    persistant signale un bug (activation precedente non nettoyee).
    """
    init_pending_intents(game_state)
    if squad_id in game_state["pending_squad_shoot_intents"]:
        raise RuntimeError(
            f"pending_squad_shoot_intents[{squad_id!r}] already exists at activation start — "
            f"previous activation was not cleaned by end_activation"
        )


def assert_no_pending_fight_intent(game_state: Dict[str, Any], squad_id: str) -> None:
    """Leve si pending_squad_fight_intents[squad_id] existe deja."""
    init_pending_intents(game_state)
    if squad_id in game_state["pending_squad_fight_intents"]:
        raise RuntimeError(
            f"pending_squad_fight_intents[{squad_id!r}] already exists at activation start"
        )


def clear_pending_shoot_intent(game_state: Dict[str, Any], squad_id: str) -> None:
    """Supprime le pending d une escouade (succes OU annulation d activation)."""
    init_pending_intents(game_state)
    game_state["pending_squad_shoot_intents"].pop(squad_id, None)


def clear_pending_fight_intent(game_state: Dict[str, Any], squad_id: str) -> None:
    """Supprime le pending d une escouade (succes OU annulation d activation)."""
    init_pending_intents(game_state)
    game_state["pending_squad_fight_intents"].pop(squad_id, None)


# ============================================================================
# SQUAD SHOOTING — declaration / lock (squad.md PR3 3b)
# ============================================================================
# Pipeline parallele: ces fonctions s invoquent independamment du shoot flow
# existant. Le decoder mono-fig est preserve. Branchement RL en PR4.


def squad_shooting_unit_activation_start(
    game_state: Dict[str, Any], squad_id: str
) -> None:
    """Initialise l activation tir d une escouade.

    - Verifie pas de pending leftover (bug detection).
    - Initialise pending_squad_shoot_intents[squad_id] = [].
    - Reset SHOOT_LEFT par fig selon l arme RNG selectionnee (NB).
    """
    assert_no_pending_shoot_intent(game_state, squad_id)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    for mid in squad_models.get(squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is None:
            continue
        weapons = m.get("RNG_WEAPONS", [])  # get allowed
        sel = m.get("selectedRngWeaponIndex")
        if weapons and sel is not None and 0 <= int(sel) < len(weapons):
            w = weapons[int(sel)]
            if isinstance(w, dict) and "NB" in w:
                m["SHOOT_LEFT"] = resolve_dice_value(w["NB"], f"squad_shoot_init_{mid}")
            else:
                m["SHOOT_LEFT"] = 0
        else:
            m["SHOOT_LEFT"] = 0
    game_state["pending_squad_shoot_intents"][squad_id] = []


def _attacker_model_can_reach_squad(
    game_state: Dict[str, Any],
    ac: int,
    ar: int,
    target_squad_id: str,
    range_subhex: int,
) -> bool:
    """Eligibilite LoS per-fig, alignee sur le chemin non-squad (empreinte + ratio).

    Pour CHAQUE figurine cible vivante : si son centre est a portee (<= range_subhex)
    ET si son empreinte est visible depuis (ac, ar) au sens du ratio de couverture
    (_compute_target_visibility_from_hexes : ratio >= los_visibility_min_ratio), la
    cible est atteignable. Renvoie True des qu'une figurine satisfait les deux.

    Difference voulue avec le non-squad : origine = centre de la figurine tireuse
    (per-fig) et empreinte evaluee PAR figurine cible (pas l'union de l'escouade) —
    sinon une grosse base partiellement masquee par un mur etait grisee a tort car
    seul son centre etait teste. Reutilise la primitive de ratio (seuils 0.05/0.95)
    et son cache _hex_los_state_cache. Sur board ×1 (base_size 1), l'empreinte se
    reduit au centre : comportement identique a l'ancien test.
    """
    # Obscuring-aware LoS (single source of truth): the firing model (single hex at ac,ar) must see
    # at least los_visibility_min_ratio of a target model's footprint, with dense walls AND obscuring
    # terrain blocking (rule 13.10). Routed through the same primitive as the non-squad path so the
    # squad target pool can never include a target the model cannot actually see.
    from engine.phase_handlers.shooting_handlers import _compute_visibility_with_obscuring
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    min_ratio = float(game_rules.get("los_visibility_min_ratio", 0.0))
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    units_cache = require_key(game_state, "units_cache")
    base_unit = units_cache.get(str(target_squad_id))
    if base_unit is None:
        return False
    # Rule 13.09: hidden unit only targetable within detection range (15").
    _units = require_key(game_state, "units")
    try:
        _target_unit = next(u for u in _units if str(u.get("id")) == str(target_squad_id))
    except StopIteration:
        _target_unit = None
    target_squad_id_str = str(target_squad_id)
    if target_squad_id_str not in squad_models:
        raise KeyError(f"_attacker_model_can_reach_squad: unit {target_squad_id} not in squad_models")
    target_mids = squad_models[target_squad_id_str]
    if _target_unit and bool(_target_unit.get("hidden")):
        detection_range_subhex = (
            float(game_rules.get("detection_range", 15))
            * int(require_key(game_state, "inches_to_subhex"))
        )
        _any_within = any(
            calculate_hex_distance(ac, ar, int(tm["col"]), int(tm["row"])) <= detection_range_subhex
            for mid in target_mids
            if (tm := models_cache.get(mid)) is not None
        )
        if not _any_within:
            return False
    shooter_anchor = (ac, ar)
    shooter_hexes = [shooter_anchor]
    for mid in target_mids:
        tm = models_cache.get(mid)
        if tm is None:
            continue
        tc = int(tm["col"])
        tr = int(tm["row"])
        if calculate_hex_distance(ac, ar, tc, tr) > range_subhex:
            continue
        footprint = list(_compute_unit_occupied_hexes(tc, tr, base_unit, game_state))
        visible, total, _ = _compute_visibility_with_obscuring(
            game_state, shooter_anchor, shooter_hexes, (tc, tr), footprint
        )
        if total > 0 and (visible / total) >= min_ratio:
            return True
    return False


def _model_can_shoot_target(
    game_state: Dict[str, Any], attacker_model: Dict[str, Any], target_squad_id: str
) -> bool:
    """Eligibilite d une figurine attaquante a tirer sur une escouade cible.

    Per-fig (squad.md §"LOS cache — strategie avec escouades") : la cible est
    eligible si AU MOINS UNE figurine cible est a la fois a portee de l arme
    selectionnee ET visible (LoS murs) depuis la position de la figurine
    attaquante. La LoS est testee figurine -> figurine cible, pas ancre -> ancre.

    Conditions :
      - attaquant a SHOOT_LEFT > 0
      - arme RNG selectionnee existe avec RNG > 0
      - au moins un modele cible dans le rayon RNG (subhexes) ET avec LoS depuis l attaquant
    """
    if int(attacker_model.get("SHOOT_LEFT", 0)) <= 0:  # get allowed
        return False
    weapons = attacker_model.get("RNG_WEAPONS", [])  # get allowed
    sel = attacker_model.get("selectedRngWeaponIndex")
    if not weapons or sel is None or not (0 <= int(sel) < len(weapons)):
        return False
    weapon = weapons[int(sel)]
    if not isinstance(weapon, dict) or "RNG" not in weapon:
        return False
    # weapon["RNG"] est DEJA en subhexes (conv. existant code, cf. shooting_handlers.py:726)
    range_subhex = int(weapon["RNG"])
    if range_subhex <= 0:
        return False
    # Import lazy : shooting_handlers importe shared_utils (eviter le cycle).
    ac = int(attacker_model["col"])
    ar = int(attacker_model["row"])
    return _attacker_model_can_reach_squad(game_state, ac, ar, target_squad_id, range_subhex)


def squad_declare_shoot(
    game_state: Dict[str, Any],
    attacker_squad_id: str,
    priority_target_squad_id: str,
    eligible_target_slots: List[str],
) -> List[Dict[str, Any]]:
    """Construit les declarations de tir pour une escouade (per-fig).

    Logique de selection par fig (par index croissant) :
      1. Si la fig peut tirer sur la cible prioritaire → declare sur la cible prioritaire.
      2. Sinon, prend le premier slot (par ordre `eligible_target_slots`) ou la fig
         peut tirer.
      3. Sinon, fig ne tire pas (pas d entree dans intents).

    Capture `target_squad_size_at_declaration` (taille de l escouade cible au
    moment de la declaration) — utilise pour BLAST bonus en resolution.

    Returns la liste des intents (aussi stockee dans pending_squad_shoot_intents).

    PR3 3b : pas de TTK residual (defere a PR3 3c ou PR4 — sans TTK, plusieurs
    figs peuvent overkill une meme cible). Spec : overkill = signal implicite
    (attaques perdues), pas de penalite explicite.
    """
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    if attacker_squad_id not in game_state["pending_squad_shoot_intents"]:
        raise RuntimeError(
            f"squad_declare_shoot called before squad_shooting_unit_activation_start "
            f"for squad {attacker_squad_id!r}"
        )

    intents: List[Dict[str, Any]] = game_state["pending_squad_shoot_intents"][attacker_squad_id]

    def _target_size(target_sid: str) -> int:
        return sum(
            1 for mid in squad_models.get(target_sid, []) if mid in models_cache  # get allowed
        )

    for mid in squad_models.get(attacker_squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is None:
            continue
        chosen_target: Optional[str] = None
        if _model_can_shoot_target(game_state, m, priority_target_squad_id):
            chosen_target = priority_target_squad_id
        else:
            for slot_sid in eligible_target_slots:
                if slot_sid == priority_target_squad_id:
                    continue
                if _model_can_shoot_target(game_state, m, slot_sid):
                    chosen_target = slot_sid
                    break
        if chosen_target is None:
            continue  # fig bloquee, ne tire pas
        sel = m.get("selectedRngWeaponIndex")
        weapon_idx = int(sel) if sel is not None else 0
        # F3 fix (audit) : resoudre NB UNE SEULE FOIS a la declaration, stocker
        # dans l intent. Sinon le double-roll de_resolve_squad_shoot decouple le
        # nombre d attaques effectif de SHOOT_LEFT pour les armes a NB variable (D3/D6).
        weapons = m.get("RNG_WEAPONS", [])  # get allowed
        n_attacks_resolved = 0
        if 0 <= weapon_idx < len(weapons):
            w = weapons[weapon_idx]
            if isinstance(w, dict) and "NB" in w:
                try:
                    n_attacks_resolved = int(resolve_dice_value(w["NB"], f"squad_declare_shoot_NB_{mid}"))
                except Exception:
                    n_attacks_resolved = int(w["NB"]) if isinstance(w["NB"], (int, float)) else 1
        intents.append({
            "model_id": mid,
            "weapon_index": weapon_idx,
            "target_unit_id": chosen_target,
            "target_squad_size_at_declaration": _target_size(chosen_target),
            "n_attacks_resolved": n_attacks_resolved,
        })
    return intents


def _resolve_intent_nb(
    weapons: List[Any], weapon_idx: int, roll_label: str
) -> int:
    """Resout le NB d une arme UNE SEULE FOIS a la declaration (fix audit F3).

    Retourne 0 si l index est hors limites ou l arme n a pas de NB. Le label sert
    uniquement de tag debug a resolve_dice_value (aucun impact sur le RNG).
    """
    if not (0 <= weapon_idx < len(weapons)):
        return 0
    w = weapons[weapon_idx]
    if not (isinstance(w, dict) and "NB" in w):
        return 0
    try:
        return int(resolve_dice_value(w["NB"], roll_label))
    except Exception:
        return int(w["NB"]) if isinstance(w["NB"], (int, float)) else 1


def declare_attack_model(
    game_state: Dict[str, Any],
    ctx: DeclareAttackCtx,
    attacker_squad_id: str,
    attacker_model_id: str,
    target_squad_id: str,
) -> Dict[str, Any]:
    """Declaration MANUELLE d UNE figurine (flux PvP humain), tir OU combat.

    Moteur generique parametre par ctx (cf. DeclareAttackCtx). Le joueur assigne
    explicitement la cible d UNE figurine. Re-appeler pour une figurine deja
    declaree avec la MEME arme REMPLACE sa cible (split fire : cle (model, arme)).

    Validation stricte (pas de valeur par défaut) :
      - activation demarree (pending initialise),
      - figurine appartient a l escouade attaquante et vivante,
      - escouade cible vivante,
      - la figurine peut viser la cible (ctx.can_target).

    Returns l intent cree (pour feedback frontend).
    """
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    if attacker_squad_id not in game_state[ctx.intents_key]:
        raise RuntimeError(
            f"declare_attack_model ({ctx.phase_label}) called before activation start "
            f"for squad {attacker_squad_id!r}"
        )
    if attacker_model_id not in squad_models.get(attacker_squad_id, []):  # get allowed
        raise ValueError(
            f"Model {attacker_model_id!r} not in squad {attacker_squad_id!r}"
        )
    m = models_cache.get(attacker_model_id)
    if m is None:
        raise ValueError(f"Model {attacker_model_id!r} not alive (absent de models_cache)")
    if target_squad_id not in squad_models or not any(
        mid in models_cache for mid in squad_models.get(target_squad_id, [])  # get allowed
    ):
        raise ValueError(f"Target squad {target_squad_id!r} not alive")
    if not ctx.can_target(game_state, m, attacker_squad_id, target_squad_id):
        raise ValueError(
            f"Model {attacker_model_id!r} cannot attack target {target_squad_id!r} "
            f"({ctx.phase_label}: hors portee/engagement ou pas de LoS)"
        )

    sel = m.get(ctx.selected_weapon_attr)
    weapon_idx = int(sel) if sel is not None else 0

    intents: List[Dict[str, Any]] = game_state[ctx.intents_key][attacker_squad_id]
    # Remplace la declaration existante de cette figurine POUR CETTE ARME (split fire :
    # une fig peut tirer plusieurs de ses armes sur des cibles differentes -> cle (model, arme)).
    intents[:] = [
        i for i in intents
        if not (i.get("model_id") == attacker_model_id and int(i.get("weapon_index", -1)) == weapon_idx)
    ]
    weapons = m.get(ctx.weapons_key, [])  # get allowed
    n_attacks_resolved = _resolve_intent_nb(
        weapons, weapon_idx, f"{ctx.phase_label}_declare_model_NB_{attacker_model_id}"
    )
    target_size = sum(
        1 for mid in squad_models.get(target_squad_id, []) if mid in models_cache  # get allowed
    )
    intent = {
        "model_id": attacker_model_id,
        "weapon_index": weapon_idx,
        "target_unit_id": target_squad_id,
        "target_squad_size_at_declaration": target_size,
        "n_attacks_resolved": n_attacks_resolved,
    }
    intents.append(intent)
    return intent


def declare_attack_weapon(
    game_state: Dict[str, Any],
    ctx: DeclareAttackCtx,
    attacker_squad_id: str,
    weapon_index: int,
    target_squad_id: str,
) -> List[Dict[str, Any]]:
    """Assigne l arme `weapon_index` (niveau escouade) a la cible, tir OU combat.

    Moteur generique parametre par ctx. Pour CHAQUE figurine vivante de l escouade
    qui possede cette arme et peut viser la cible (ctx.can_target_with_weapon), cree
    un intent (model_id, weapon_index) -> T. Re-appeler avec la meme arme REMPLACE
    la cible (retire d abord tous les intents de cette arme, toutes figs confondues).

    Validation stricte (pas de valeur par defaut) :
      - activation demarree (pending initialise),
      - escouade cible vivante,
      - au moins une figurine peut viser l arme sur la cible (sinon ValueError).

    Returns la liste des intents crees pour cette arme.
    """
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    if attacker_squad_id not in game_state[ctx.intents_key]:
        raise RuntimeError(
            f"declare_attack_weapon ({ctx.phase_label}) called before activation start "
            f"for squad {attacker_squad_id!r}"
        )
    if target_squad_id not in squad_models or not any(
        mid in models_cache for mid in squad_models.get(target_squad_id, [])  # get allowed
    ):
        raise ValueError(f"Target squad {target_squad_id!r} not alive")

    intents: List[Dict[str, Any]] = game_state[ctx.intents_key][attacker_squad_id]
    widx = int(weapon_index)
    # Remplace toute declaration existante de CETTE arme (changement de cible).
    intents[:] = [i for i in intents if int(i.get("weapon_index", -1)) != widx]
    target_size = sum(
        1 for mid in squad_models.get(target_squad_id, []) if mid in models_cache  # get allowed
    )
    created: List[Dict[str, Any]] = []
    for mid in squad_models.get(attacker_squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is None:
            continue
        if not ctx.can_target_with_weapon(game_state, m, attacker_squad_id, target_squad_id, widx):
            continue
        weapons = m.get(ctx.weapons_key, [])  # get allowed
        n_attacks_resolved = _resolve_intent_nb(
            weapons, widx, f"{ctx.phase_label}_declare_weapon_NB_{mid}_{widx}"
        )
        intent = {
            "model_id": mid,
            "weapon_index": widx,
            "target_unit_id": target_squad_id,
            "target_squad_size_at_declaration": target_size,
            "n_attacks_resolved": n_attacks_resolved,
        }
        intents.append(intent)
        created.append(intent)
    if not created:
        # [ENG-DIAG TEMP] diagnostic divergence engagement front/back (fight). A RETIRER.
        try:
            from engine.spatial_relations import get_engagement_zone
            from engine.hex_utils import min_distance_between_sets
            _uc = require_key(game_state, "units_cache")
            _tgt = _uc.get(str(target_squad_id), {})
            _tgt_fp = _tgt.get("occupied_hexes") or {(_tgt.get("col"), _tgt.get("row"))}
            _ez = get_engagement_zone(game_state)
            _atk_pos = {
                mid: (models_cache[mid].get("col"), models_cache[mid].get("row"))
                for mid in squad_models.get(attacker_squad_id, []) if mid in models_cache
            }
            _dist = {
                mid: min_distance_between_sets({pos}, _tgt_fp)
                for mid, pos in _atk_pos.items()
            }
            print(
                f"[ENG-DIAG TEMP] phase={ctx.phase_label} atk={attacker_squad_id} tgt={target_squad_id} "
                f"widx={widx} ez={_ez} atk_pos={_atk_pos} tgt_occ_hexes={sorted(_tgt_fp)} "
                f"min_dist_par_fig={_dist}",
                flush=True,
            )
        except Exception as _e:  # diagnostic seulement, ne doit pas masquer l'erreur reelle
            print(f"[ENG-DIAG TEMP] echec collecte diag: {_e!r}", flush=True)
        raise ValueError(
            f"Aucune figurine de {attacker_squad_id!r} ne peut viser l arme {widx} "
            f"sur {target_squad_id!r} ({ctx.phase_label}: hors portee/engagement ou pas de LoS)"
        )
    return created


def squad_declare_shoot_model(
    game_state: Dict[str, Any],
    attacker_squad_id: str,
    attacker_model_id: str,
    target_squad_id: str,
) -> Dict[str, Any]:
    """Declaration MANUELLE d une seule figurine au TIR (flux PvP humain).

    Wrapper fin de declare_attack_model via SHOOT_DECLARE_CTX (portee + LoS).
    """
    return declare_attack_model(
        game_state, SHOOT_DECLARE_CTX, attacker_squad_id, attacker_model_id, target_squad_id
    )


def squad_model_valid_targets(
    game_state: Dict[str, Any], attacker_squad_id: str, attacker_model_id: str
) -> List[str]:
    """Liste des escouades ennemies qu UNE figurine peut cibler (portee + LoS).

    Reutilise _model_can_shoot_target (meme eligibilite que squad_declare_shoot_model).
    Sert a alimenter le HP blink frontend pour la fig selectionnee (cibles valides
    clignotent, les autres sont grisees) — meme mecanisme que l activation legacy.

    Returns une liste de squad_id ennemis (str), vide si la fig ne peut rien viser.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    m = models_cache.get(attacker_model_id)
    if m is None:
        raise ValueError(f"Model {attacker_model_id!r} not alive (absent de models_cache)")
    attacker_player = int(m["player"])
    valid: List[str] = []
    for sid, mids in squad_models.items():
        if sid == attacker_squad_id:
            continue
        first = next((mid for mid in mids if mid in models_cache), None)
        if first is None:
            continue  # escouade morte
        if int(models_cache[first]["player"]) == attacker_player:
            continue  # allie
        if _model_can_shoot_target(game_state, m, sid):
            valid.append(sid)
    return valid


def squad_shoot_los_overview(
    game_state: Dict[str, Any], attacker_squad_id: str
) -> Dict[str, Any]:
    """Agrege les cibles tirables de TOUTE l escouade (double-click frontend).

    Pour chaque fig vivante de l escouade, reutilise squad_model_valid_targets
    (meme eligibilite que le blink mono-fig : arme selectionnee + LoS + portee),
    puis compte par ennemi le nombre N de figs qui peuvent le cibler. Read-only :
    n ecrit rien dans game_state.

    Returns:
        valid_targets    : union des squad_id ennemis vises par >= 1 fig
        count_by_unit_id : {squad_id ennemi: N figs qui peuvent le cibler}
        squad_alive_count: M = nb de figs vivantes de l escouade attaquante
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    mids = squad_models.get(attacker_squad_id)
    if mids is None:
        raise ValueError(f"Squad {attacker_squad_id!r} absent de squad_models")
    alive = [mid for mid in mids if mid in models_cache]
    count: Dict[str, int] = {}
    for mid in alive:
        for sid in squad_model_valid_targets(game_state, attacker_squad_id, mid):
            if sid not in count:
                count[sid] = 0
            count[sid] += 1
    return {
        "valid_targets": list(count.keys()),
        "count_by_unit_id": count,
        "squad_alive_count": len(alive),
    }


def squad_undeclare_shoot_model(
    game_state: Dict[str, Any], attacker_squad_id: str, attacker_model_id: str
) -> bool:
    """Retire la declaration d une figurine (flux PvP humain : le joueur deselectionne).

    Returns True si une declaration a ete retiree, False sinon.
    """
    init_pending_intents(game_state)
    intents = game_state["pending_squad_shoot_intents"].get(attacker_squad_id)
    if not intents:
        return False
    before = len(intents)
    intents[:] = [i for i in intents if i.get("model_id") != attacker_model_id]
    return len(intents) < before


# ============================================================================
# SQUAD SHOOTING — assignation PAR ARME (split fire PvP humain)
# ============================================================================
# Le flux par-figurine ci-dessus assigne 1 cible par figurine (arme selectionnee).
# Le flux par-arme ci-dessous assigne l ARME au niveau de l ESCOUADE : choisir
# l arme W dans le menu puis cliquer une cible T => toutes les figs portant W
# tirent W sur T. Intents indexes par (model_id, weapon_index) : une fig peut
# donc tirer plusieurs de ses armes sur des cibles differentes (split fire).
# Marche pour mono ET multi-figurine (mono = squad d 1 modele).


def _model_can_shoot_target_with_weapon(
    game_state: Dict[str, Any],
    attacker_model: Dict[str, Any],
    target_squad_id: str,
    weapon_index: int,
) -> bool:
    """Eligibilite per-arme : la fig peut tirer l arme `weapon_index` sur la cible.

    Contrairement a _model_can_shoot_target (arme selectionnee + SHOOT_LEFT > 0),
    teste une arme PRECISE (portee + LoS) sans gater sur SHOOT_LEFT : en 10e une
    figurine tire CHACUNE de ses armes une fois (split fire), SHOOT_LEFT etant le
    NB d une seule arme et donc inadapte comme garde multi-armes.
    """
    weapons = attacker_model.get("RNG_WEAPONS", [])  # get allowed
    if not (0 <= int(weapon_index) < len(weapons)):
        return False
    weapon = weapons[int(weapon_index)]
    if not isinstance(weapon, dict) or "RNG" not in weapon:
        return False
    # weapon["RNG"] est DEJA en subhexes (cf. _model_can_shoot_target).
    range_subhex = int(weapon["RNG"])
    if range_subhex <= 0:
        return False
    ac = int(attacker_model["col"])
    ar = int(attacker_model["row"])
    return _attacker_model_can_reach_squad(game_state, ac, ar, target_squad_id, range_subhex)


# Contexte de declaration TIR : portee + LoS. Defini ici car il reference les deux
# callbacks d eligibilite ci-dessus (_model_can_shoot_target / _with_weapon).
SHOOT_DECLARE_CTX = DeclareAttackCtx(
    intents_key="pending_squad_shoot_intents",
    selected_weapon_attr="selectedRngWeaponIndex",
    weapons_key="RNG_WEAPONS",
    phase_label="shoot",
    # Le tir n a pas besoin du squad_id attaquant (validite = portee + LoS depuis la fig).
    can_target=lambda gs, m, _sq, tsid: _model_can_shoot_target(gs, m, tsid),
    can_target_with_weapon=lambda gs, m, _sq, tsid, widx: _model_can_shoot_target_with_weapon(
        gs, m, tsid, widx
    ),
)


def squad_declare_shoot_weapon(
    game_state: Dict[str, Any],
    attacker_squad_id: str,
    weapon_index: int,
    target_squad_id: str,
) -> List[Dict[str, Any]]:
    """Assigne l arme `weapon_index` (niveau escouade) a la cible, au TIR.

    Wrapper fin de declare_attack_weapon via SHOOT_DECLARE_CTX (portee + LoS).
    """
    return declare_attack_weapon(
        game_state, SHOOT_DECLARE_CTX, attacker_squad_id, weapon_index, target_squad_id
    )


def squad_undeclare_shoot_weapon(
    game_state: Dict[str, Any], attacker_squad_id: str, weapon_index: int
) -> bool:
    """Retire toutes les declarations de l arme `weapon_index`. Returns True si retire."""
    init_pending_intents(game_state)
    intents = game_state["pending_squad_shoot_intents"].get(attacker_squad_id)
    if not intents:
        return False
    widx = int(weapon_index)
    before = len(intents)
    intents[:] = [i for i in intents if int(i.get("weapon_index", -1)) != widx]
    return len(intents) < before


def squad_weapon_valid_targets(
    game_state: Dict[str, Any], attacker_squad_id: str, weapon_index: int
) -> List[str]:
    """Escouades ennemies qu AU MOINS UNE figurine peut viser avec l arme `weapon_index`.

    Reutilise _model_can_shoot_target_with_weapon (meme eligibilite que la
    declaration par-arme). Alimente le HP blink frontend pour l arme active.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    attacker_player: Optional[int] = None
    for mid in squad_models.get(attacker_squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is not None:
            attacker_player = int(m["player"])
            break
    if attacker_player is None:
        return []
    valid: List[str] = []
    for sid, mids in squad_models.items():
        if sid == attacker_squad_id:
            continue
        first = next((mid for mid in mids if mid in models_cache), None)
        if first is None:
            continue  # escouade morte
        if int(models_cache[first]["player"]) == attacker_player:
            continue  # allie
        if any(
            _model_can_shoot_target_with_weapon(game_state, models_cache[amid], sid, weapon_index)
            for amid in squad_models.get(attacker_squad_id, [])  # get allowed
            if amid in models_cache
        ):
            valid.append(sid)
    return valid


def squad_lock_shoot(game_state: Dict[str, Any], squad_id: str) -> List[Dict[str, Any]]:
    """Verrouille les declarations (lecture seule jusqu a resolution).

    PR3 3b : pas de flag explicite — la convention est que toute modification de
    pending_squad_shoot_intents[squad_id] apres ce call est un bug. La resolution
    (PR3 3c) lit ce dict et le nettoie via clear_pending_shoot_intent en fin.
    Retourne la liste verrouillee pour usage immediat par la resolution.
    """
    init_pending_intents(game_state)
    return list(game_state["pending_squad_shoot_intents"].get(squad_id, []))  # get allowed


# ============================================================================
# SQUAD SHOOTING — resolution (squad.md PR3 3c)
# ============================================================================
# Hit → Wound → Save → Damage. Allocation prioritaire. Damage excess perdu.
# BLAST bonus selon taille cible a la declaration. Fig morte mid-resolution
# (attaquante : ses attaques restantes annulees ; cible : voir allocation).


def wound_threshold(strength: int, toughness: int) -> int:
    """Seuil 1D6 pour blesser selon table W40K 10e :
       S >= 2T : 2+
       S > T (et pas >= 2T) : 3+
       S == T : 4+
       S < T (et pas <= T/2) : 5+
       S <= T/2 : 6+
    """
    s = int(strength); t = int(toughness)
    if s >= 2 * t:
        return 2
    if 2 * s <= t:
        return 6
    if s > t:
        return 3
    if s == t:
        return 4
    return 5


def save_threshold(armor_save: int, invul_save: int, ap: int) -> int:
    """Meilleur des deux sauvegardes (Sv degrade par AP vs Invul ignore AP).

    Convention W40K (alignee shooting_handlers.py:6873) : AP est NEGATIF (ex: -1, -2).
    AP -1 sur Sv 3+ → effective = 3 - (-1) = 4 (save degradee a 4+).
    invul_save == 7 = pas d invul (sentinel).
    """
    effective_armor = int(armor_save) - int(ap)
    inv = int(invul_save)
    if inv < 7 and inv < effective_armor:
        return inv
    return effective_armor


def _has_blast_keyword(weapon: Dict[str, Any]) -> bool:
    kws = weapon.get("KEYWORDS") or weapon.get("keywords") or []
    if isinstance(kws, list):
        return any(str(k).upper() == "BLAST" for k in kws)
    if isinstance(kws, str):
        return "BLAST" in kws.upper()
    return False


def _precompute_nearest_enemy_dist(
    game_state: Dict[str, Any], target_squad_id: str
) -> Dict[str, int]:
    """Distance (hex) de chaque fig vivante du squad cible a l ennemi le plus proche.

    Positions fixes pendant la resolution d une salve -> calcule une fois, reutilise
    a chaque allocation (cf. `_allocate_damage_to_squad`).
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive = [m for m in squad_models.get(target_squad_id, []) if m in models_cache]  # get allowed
    if not alive:
        return {}
    defender_player = int(models_cache[alive[0]]["player"])
    enemy_pos = [
        (int(e["col"]), int(e["row"]))
        for e in models_cache.values()
        if int(e["player"]) != defender_player
    ]
    dist: Dict[str, int] = {}
    for mid in alive:
        e = models_cache[mid]
        c, r = int(e["col"]), int(e["row"])
        dist[mid] = min(
            (calculate_hex_distance(c, r, ec, er) for ec, er in enemy_pos),
            default=0,
        )
    return dist


def _select_allocation_model(
    game_state: Dict[str, Any], target_squad_id: str, alive: List[str],
    dist_cache: Optional[Dict[str, int]] = None,
) -> str:
    """Choisit la figurine du squad cible qui encaisse la prochaine attaque.

    Point unique de variation de l allocation defensive :
      - A3 branchera ici le choix du joueur humain (defenseur) ;
      - l etape B y branchera la decision de l agent RL.

    Cascade actuelle (decider non-humain, heuristique A2b) :
      1. (regle) figurine deja blessee (HP_CUR < HP_MAX) en priorite ;
      2. tier de role croissant (base < special_weapon < sergeant < support < leader) ;
      3. la plus proche d un ennemi (`dist_cache`) ;
      4. ordre d index (tie-break deterministe).
    """
    models_cache = require_key(game_state, "models_cache")
    # 1. Regle : finir une figurine deja entamee avant d en exposer une neuve.
    for mid in alive:
        e = models_cache[mid]
        if int(e["HP_CUR"]) < int(e["HP_MAX"]):
            return mid
    # 2. Heuristique defensive sur les figurines pleines : tier de role croissant
    #    (base < special_weapon < sergeant < support < leader), puis proximite
    #    ennemi, puis index. L ordre du tier met les characters en dernier.
    if dist_cache is None:
        dist_cache = _precompute_nearest_enemy_dist(game_state, target_squad_id)

    def _key(item: tuple) -> tuple:
        idx, mid = item
        e = models_cache[mid]
        _role = e.get("role")
        tier = ROLE_TIER[_role] if _role in ROLE_TIER else 0
        return (tier, dist_cache[mid], idx)

    return min(enumerate(alive), key=_key)[1]


def _allocate_damage_to_squad(
    game_state: Dict[str, Any], target_squad_id: str, damage: int,
    dist_cache: Optional[Dict[str, int]] = None,
) -> Optional[Dict[str, Any]]:
    """Applique `damage` HP a une figurine vivante du squad selon allocation prioritaire.

    Selection de la figurine deleguee a `_select_allocation_model` (point unique de
    variation : heuristique aujourd hui ; choix humain en A3 ; agent RL en B).
    `dist_cache` (optionnel) = distances pre-calculees fig->ennemi le plus proche,
    evite de les recalculer a chaque allocation d une meme salve.
    Damage excess (> HP_CUR du modele) perdu — pas de carry-over.
    Si le modele est tue → destroy_model(reason='combat').
    Sinon → update_model_hp.

    Returns {model_id, damage_dealt, destroyed} ou None si pas de cible vivante.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive = [m for m in squad_models.get(target_squad_id, []) if m in models_cache]  # get allowed
    if not alive:
        return None
    target_mid = _select_allocation_model(game_state, target_squad_id, alive, dist_cache)
    m = models_cache[target_mid]
    hp_before = int(m["HP_CUR"])
    target_points_per_hp = float(require_key(m, "points_per_hp"))
    target_player = int(require_key(m, "player"))
    target_unit_type = m.get("unitType")
    target_col = m.get("col")
    target_row = m.get("row")
    damage_dealt = min(int(damage), hp_before)
    new_hp = hp_before - damage_dealt
    destroyed = False
    if new_hp <= 0:
        destroy_model(game_state, target_mid, reason="combat")
        destroyed = True
    else:
        update_model_hp(game_state, target_mid, new_hp)
    return {
        "model_id": target_mid, "damage_dealt": damage_dealt, "destroyed": destroyed,
        "points_per_hp": target_points_per_hp, "target_player": target_player,
        "unitType": target_unit_type,
        "col": target_col,
        "row": target_row,
    }


def _emit_squad_shoot_log(game_state: Dict[str, Any], g: Dict[str, Any], ctx: ManualAllocCtx) -> None:
    """Emet 1 action_log de tir pour un groupe (arme, cible).

    Partage entre l allocation auto (resolve_squad_shoot) et l allocation manuelle
    (defenseur humain) : meme format de log, damage/kills refletant l allocation
    effective. Ne consomme pas de RNG.
    """
    weapon_name_g = g["weapon_name"]
    target_sid_g = g["target_sid"]
    attacker_squad_id_str = g["attacker_squad_id"]
    sq_uc = game_state.get("units_cache", {}).get(attacker_squad_id_str, {})  # get allowed
    tgt_uc = game_state.get("units_cache", {}).get(target_sid_g, {})  # get allowed
    tgt_unit = next((u for u in game_state["units"] if str(u["id"]) == target_sid_g), None)
    tgt_unit_type_g = tgt_unit.get("unitType") if tgt_unit else None
    ac = int(sq_uc.get("col", 0))  # get allowed
    ar = int(sq_uc.get("row", 0))  # get allowed
    tc = int(tgt_uc.get("col", 0))  # get allowed
    tr = int(tgt_uc.get("row", 0))  # get allowed
    weapon_suffix = f" [{weapon_name_g}]" if weapon_name_g else ""
    # Cover (13.08, ranged-only) : si la cible avait le couvert, afficher la degradation
    # du seuil de touche (ex 3+->4+) + token [COVER] (tooltip regle cote frontend).
    # Absent au combat -> branche standard.
    if g.get("cover"):
        hit_part = f"Hit:{g['bs_base']}+->{g['bs']}+[COVER]"
    else:
        hit_part = f"Hit:{g['bs']}+"
    attack_log = (
        f"Shots:{g['attacks']} - "
        f"{hit_part} Wound:{g['display_wth']}+ Save:{g['display_save_th']}+ - "
        f"HP lost:{g['damage']} Killed:{g['kills']}"
    )
    msg = (
        f"Unit {attacker_squad_id_str}({ac},{ar}) {ctx.log_verb}"
        f" at Unit {target_sid_g}({tc},{tr}){weapon_suffix}"
        f" - {attack_log}"
    )
    append_action_log(game_state, {
        "type": ctx.log_type,
        "message": msg,
        "turn": game_state.get("turn", 0),  # get allowed
        "phase": ctx.phase_label,
        "shooterId": attacker_squad_id_str,
        "targetId": target_sid_g,
        "weaponName": weapon_name_g if weapon_name_g else None,
        "targetUnitType": tgt_unit_type_g,
        "player": g["player"],
        "shooterCol": ac,
        "shooterRow": ar,
        "targetCol": tc,
        "targetRow": tr,
        "damage": g["damage"],
        "target_died": g["kills"] > 0,
        "timestamp": "server_time",
        "is_ai_action": g["player"] == 1,
        "shootDetails": [{"shotNumber": i + 1, **s} for i, s in enumerate(g["shots"])],
    })


def _roll_squad_shot_sequence(
    n_attacks: int, bs: int, wth: int, save_th: int,
    dmg_raw: Any, attacker_mid: str,
) -> Dict[str, Any]:
    """Resout les jets (hit/wound/save/dmg) de `n_attacks` attaques contre une cible
    homogene aux seuils figes (bs, wth, save_th).

    Brique RNG partagee entre l allocation auto (resolve_squad_shoot) et l allocation
    manuelle (defenseur humain). Ordre de tirage : hit -> wound -> save -> dmg par
    attaque, identique a l implementation inline d origine (iso-RNG).

    Ne mute aucun etat de jeu : retourne les records d affichage + le pool de degats
    a allouer. L allocation (mutation des figurines) est faite par l appelant.

    Returns {
      "shot_records": [...],            # 1 record par attaque (pour shootDetails)
      "pending_damages": [{dmg, rec}],  # saves rates avec degats > 0, dans l ordre
      "counts": {attacks, hits, wounds, failed_saves},
    }
    """
    import random
    shot_records: List[Dict[str, Any]] = []
    pending_damages: List[Dict[str, Any]] = []
    attacks = 0
    hits = 0
    wounds = 0
    failed_saves = 0
    for _ in range(n_attacks):
        attacks += 1
        # 1. Hit roll
        hit_roll = random.randint(1, 6)
        if hit_roll == 1 or hit_roll < bs:
            shot_records.append({"attackRoll": hit_roll, "hitResult": "MISS", "hitTarget": bs})
            continue
        hits += 1
        # 2. Wound roll
        wound_roll = random.randint(1, 6)
        if wound_roll == 1 or wound_roll < wth:
            shot_records.append({"attackRoll": hit_roll, "hitResult": "HIT", "hitTarget": bs, "strengthRoll": wound_roll, "strengthResult": "FAILED", "woundTarget": wth})
            continue
        wounds += 1
        # 3. Save roll
        save_roll = random.randint(1, 6)
        if save_roll != 1 and save_roll >= save_th:
            shot_records.append({"attackRoll": hit_roll, "hitResult": "HIT", "hitTarget": bs, "strengthRoll": wound_roll, "strengthResult": "SUCCESS", "woundTarget": wth, "saveRoll": save_roll, "saveTarget": save_th, "saveSuccess": True, "damageDealt": 0})
            continue  # save reussi
        failed_saves += 1
        # 4. Damage roll (applique a l allocation)
        try:
            dmg = resolve_dice_value(cast(DiceValue, dmg_raw), f"squad_shoot_dmg_{attacker_mid}")
        except Exception:
            dmg = int(dmg_raw) if isinstance(dmg_raw, (int, float)) else 1
        # Record cree dans l ordre ; damageDealt/targetDied completes a l allocation (mutation).
        rec = {"attackRoll": hit_roll, "hitResult": "HIT", "hitTarget": bs, "strengthRoll": wound_roll, "strengthResult": "SUCCESS", "woundTarget": wth, "saveRoll": save_roll, "saveTarget": save_th, "saveSuccess": False, "damageDealt": 0}
        shot_records.append(rec)
        if dmg <= 0:
            continue
        pending_damages.append({"dmg": dmg, "rec": rec})
    return {
        "shot_records": shot_records,
        "pending_damages": pending_damages,
        "counts": {"attacks": attacks, "hits": hits, "wounds": wounds, "failed_saves": failed_saves},
    }


def _cover_worsened_bs(
    game_state: Dict[str, Any], attacker: Dict[str, Any], target_sid: str, bs: int,
) -> Tuple[int, bool]:
    """Applique le Benefit of Cover (regle 13.08) au seuil de touche d un tir.

    Cover = ranged-only, niveau UNITE tout-ou-rien : « worsen the BS characteristic of
    that attack by 1 ». Source autoritative : compute_unit_los(tireur, cible)["cover"]
    (pair-cache par _unit_move_version) = exactement la valeur affichee au frontend
    (los_cover_cache derive du meme calcul). Clamp a 6 : un 6 non-modifie touche toujours
    (CRITICAL HIT, 05.01), donc un BS6+ sous cover reste touche-sur-6.

    Retourne (bs_effectif, cover). Aucun repli : si une unite est introuvable c est
    un bug -> erreur explicite.
    """
    from engine.phase_handlers.shooting_handlers import compute_unit_los, _get_unit_by_id
    shooter_sid = str(require_key(attacker, "squad_id"))
    shooter_unit = _get_unit_by_id(game_state, shooter_sid)
    target_unit = _get_unit_by_id(game_state, str(target_sid))
    if shooter_unit is None:
        raise ValueError(f"Cover: tireur {shooter_sid!r} introuvable (unit_by_id)")
    if target_unit is None:
        raise ValueError(f"Cover: cible {target_sid!r} introuvable (unit_by_id)")
    cover = bool(compute_unit_los(game_state, shooter_unit, target_unit)["cover"])
    if not cover:
        return bs, False
    return min(bs + 1, 6), True


def _resolve_shoot_intent_pass1(
    game_state: Dict[str, Any], intent: Dict[str, Any],
    targets_meta: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Setup + jets (PASSE 1) d un intent de tir, sans allouer les degats.

    Partage entre l allocation auto (resolve_squad_shoot) et l allocation manuelle
    (defenseur humain) : selection arme, n_attacks (+BLAST), seuils figes sur la 1ere
    fig vivante, puis jets via _roll_squad_shot_sequence (ordre RNG inchange).

    Peuple `targets_meta` (effet de bord partage, au meme moment que l original :
    apres validation de la cible, avant la selection d arme). Retourne None si l intent
    est a ignorer (fig attaquante morte, cible wipe, arme invalide, n_attacks<=0).

    Returns {attacker_mid, attacker, target_sid, weapon_name, bs, display_wth,
             display_save_th, shot_records, pending_damages, counts} ou None.
    """
    models_cache = require_key(game_state, "models_cache")
    attacker_mid = intent["model_id"]
    attacker = models_cache.get(attacker_mid)
    if attacker is None:
        return None  # fig morte mid-resolution
    target_sid = str(intent["target_unit_id"])
    if target_sid not in game_state.get("squad_models", {}):  # get allowed
        return None  # cible deja wipe
    if target_sid not in targets_meta:
        _tgt_uc = require_key(game_state, "units_cache")[target_sid]
        _tgt_sc = require_key(game_state, "squad_cache")[target_sid]
        targets_meta[target_sid] = {
            "value": float(require_key(_tgt_uc, "VALUE")),
            "model_count_at_start": int(require_key(_tgt_sc, "model_count_at_start")),
            "player": int(require_key(_tgt_uc, "player")),
        }
    weapon_index = int(intent.get("weapon_index", 0))  # get allowed
    weapons = attacker.get("RNG_WEAPONS", [])  # get allowed
    if not (0 <= weapon_index < len(weapons)):
        return None
    weapon = weapons[weapon_index]
    if not isinstance(weapon, dict):
        return None
    # F3 fix (audit) : lire n_attacks_resolved depuis l intent (resolu a la
    # declaration). Re-roll de NB si absent (compat legacy intents).
    if "n_attacks_resolved" in intent:
        n_attacks = int(intent["n_attacks_resolved"])
    else:
        nb_raw = weapon.get("NB", 1)
        try:
            n_attacks = resolve_dice_value(nb_raw, f"squad_shoot_attacks_{attacker_mid}")
        except Exception:
            n_attacks = int(nb_raw) if isinstance(nb_raw, (int, float)) else 1
    if _has_blast_keyword(weapon):
        tgt_size = int(intent.get("target_squad_size_at_declaration", 0))  # get allowed
        n_attacks += tgt_size // 5
    if n_attacks <= 0:
        return None
    # Convention moteur (cf. shooting_handlers.py:3010-3011, 6683, 6748) :
    # weapon["ATK"] = seuil hit (BS/WS), weapon["STR"] = force, weapon["AP"] = AP modifier
    bs_base = int(weapon.get("ATK", weapon.get("BS", 4)))
    bs, cover = _cover_worsened_bs(game_state, attacker, target_sid, bs_base)
    strength = int(weapon.get("STR", weapon.get("S", attacker.get("T", 4))))
    ap = int(weapon.get("AP", 0))  # get allowed
    dmg_raw = weapon.get("DMG", 1)
    wound_th_lookup: Dict[int, int] = {}  # cache wound threshold by T

    # Pré-calcul des seuils pour l'affichage (Hit/Wound/Save)
    _pre_alive = [m for m in game_state["squad_models"].get(target_sid, []) if m in models_cache]  # get allowed
    display_wth = 0
    display_save_th = 0
    if _pre_alive:
        _pre_tgt = models_cache[_pre_alive[0]]
        display_wth = wound_threshold(strength, int(_pre_tgt["T"]))
        display_save_th = save_threshold(int(_pre_tgt["ARMOR_SAVE"]), int(_pre_tgt.get("INVUL_SAVE", 7)), ap)

    # Seuils figes sur la 1ere fig vivante au debut de la salve (homogene : invariant
    # par fig ; hetereogene/persos = etape ulterieure avec groupes d allocation).
    _alive0 = [m for m in game_state["squad_models"].get(target_sid, []) if m in models_cache]  # get allowed
    wth = 0
    save_th = 0
    if _alive0 and attacker_mid in models_cache:
        first_alive = models_cache[_alive0[0]]
        t_target = int(first_alive["T"])
        wth = wound_th_lookup.get(t_target)
        if wth is None:
            wth = wound_threshold(strength, t_target)
            wound_th_lookup[t_target] = wth
        sv = int(first_alive["ARMOR_SAVE"])
        invul = int(first_alive.get("INVUL_SAVE", 7))
        save_th = save_threshold(sv, invul, ap)
        n_attacks_pass1 = int(n_attacks)
    else:
        n_attacks_pass1 = 0  # cible deja wipe (ou attaquant absent) -> aucun tir resolu

    # PASSE 1 (jets) : brique RNG partagee (cf. _roll_squad_shot_sequence).
    _roll = _roll_squad_shot_sequence(n_attacks_pass1, bs, wth, save_th, dmg_raw, attacker_mid)
    weapon_name = weapon.get("display_name", weapon.get("NAME", weapon.get("name", "")))
    return {
        "attacker_mid": attacker_mid,
        "attacker": attacker,
        "target_sid": target_sid,
        "weapon_name": weapon_name,
        "bs": bs,
        "bs_base": bs_base,
        "cover": cover,
        "display_wth": display_wth,
        "display_save_th": display_save_th,
        "shot_records": _roll["shot_records"],
        "pending_damages": _roll["pending_damages"],
        "counts": _roll["counts"],
    }


def resolve_squad_shoot(
    game_state: Dict[str, Any], attacker_squad_id: str
) -> Dict[str, Any]:
    """Resout toutes les declarations de pending_squad_shoot_intents[attacker_squad_id].

    Sequence par attaque :
      1. Hit roll (1D6 vs BS de l attaquant)
      2. Wound roll (table S vs T)
      3. Save roll (best of Sv+AP vs Invul)
      4. Damage : allocation prioritaire, excess perdu

    BLAST bonus : si l arme a keyword BLAST, +1 attaque par tranche de 5 figs
    dans la taille cible AU MOMENT DE LA DECLARATION (capture dans l intent).

    Fig attaquante morte mid-resolution : ses attaques restantes (et celles
    declarees mais non encore resolues) sont annulees — l intent est skip si
    le modele attaquant n existe plus dans models_cache.
    Fig cible morte mid-resolution : pas de carry-over, allocation_prioritaire
    sur prochaine vivante de la cible.

    Nettoie pending_squad_shoot_intents[attacker_squad_id] en fin (succes OU echec).

    Returns un summary dict pour log/debug.
    """
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    intents = list(game_state["pending_squad_shoot_intents"].get(attacker_squad_id, []))  # get allowed
    summary: Dict[str, Any] = {
        "attacks_made": 0,
        "hits": 0,
        "wounds": 0,
        "failed_saves": 0,
        "damage_total": 0,
        "models_killed": 0,
        "events": [],
    }
    targets_meta: Dict[str, Dict[str, Any]] = {}
    # Accumulation par (weapon_name, target_sid) pour émettre 1 log par arme par escouade
    weapon_groups: Dict[tuple, Dict[str, Any]] = {}
    # Cache distances fig->ennemi par cible (A2a) : positions fixes pendant la salve.
    dist_cache_by_target: Dict[str, Dict[str, int]] = {}
    for intent in intents:
        p1 = _resolve_shoot_intent_pass1(game_state, intent, targets_meta)
        if p1 is None:
            continue
        attacker_mid = p1["attacker_mid"]
        attacker = p1["attacker"]
        target_sid = p1["target_sid"]
        intent_shot_records = p1["shot_records"]
        pending_damages = p1["pending_damages"]
        _counts = p1["counts"]
        summary["attacks_made"] += _counts["attacks"]
        summary["hits"] += _counts["hits"]
        summary["wounds"] += _counts["wounds"]
        summary["failed_saves"] += _counts["failed_saves"]
        intent_attacks = _counts["attacks"]
        intent_damage = 0
        intent_kills = 0
        killed_model_ids: List[str] = []

        # PASSE 2 (application) : alloue chaque paquet de degats fig par fig (deterministe,
        # aucun RNG). Excess perdu par figurine ; tirs restants perdus si cible wipe.
        # Distances fig->ennemi pre-calculees une fois par cible (positions fixes ici).
        _dist_cache = None
        if pending_damages:
            if target_sid not in dist_cache_by_target:
                dist_cache_by_target[target_sid] = _precompute_nearest_enemy_dist(game_state, target_sid)
            _dist_cache = dist_cache_by_target[target_sid]
        for pd in pending_damages:
            target_alive = [m for m in game_state["squad_models"].get(target_sid, []) if m in models_cache]  # get allowed
            if not target_alive:
                break  # overkill : tirs restants sans cible -> perdus
            res = _allocate_damage_to_squad(game_state, target_sid, pd["dmg"], _dist_cache)
            if res is None:
                break
            summary["damage_total"] += int(res["damage_dealt"])
            intent_damage += int(res["damage_dealt"])
            if res["destroyed"]:
                summary["models_killed"] += 1
                intent_kills += 1
                killed_model_ids.append(str(res["model_id"]))
            summary["events"].append({
                "attacker": attacker_mid, "target": res["model_id"],
                "target_squad_id": target_sid,
                "target_player": int(res["target_player"]),
                "points_per_hp": float(res["points_per_hp"]),
                "damage": int(res["damage_dealt"]), "destroyed": bool(res["destroyed"]),
            })
            pd["rec"]["damageDealt"] = int(res["damage_dealt"])
            pd["rec"]["targetDied"] = bool(res["destroyed"])
            pd["rec"]["targetUnitType"] = res.get("unitType")
            pd["rec"]["targetCol"] = res.get("col")
            pd["rec"]["targetRow"] = res.get("row")
        # Overkill reel : si l escouade cible est ENTIEREMENT detruite par cette salve,
        # les tirs au-dela du dernier kill n avaient plus de cible -> marques wasted.
        # (Si une figurine survit, aucun tir n est wasted : tout a ete tire sur la cible.)
        target_still_alive = [m for m in game_state["squad_models"].get(target_sid, []) if m in models_cache]  # get allowed
        if not target_still_alive:
            last_kill_pos = -1
            for _i, _r in enumerate(intent_shot_records):
                if _r.get("targetDied"):
                    last_kill_pos = _i
            for _r in intent_shot_records[last_kill_pos + 1:]:
                _r["wasted"] = True
        # Apres toutes les attaques de cet intent, decrement SHOOT_LEFT du modele attaquant
        if attacker_mid in models_cache:
            sl = int(models_cache[attacker_mid].get("SHOOT_LEFT", 0))  # get allowed
            models_cache[attacker_mid]["SHOOT_LEFT"] = max(0, sl - 1)

        # Accumulation par groupe (weapon, target) — log émis après la boucle
        if intent_attacks > 0:
            weapon_name = p1["weapon_name"]
            group_key = (weapon_name, target_sid)
            if group_key not in weapon_groups:
                weapon_groups[group_key] = {
                    "attacker_squad_id": str(attacker.get("squad_id", attacker_mid)),
                    "weapon_name": weapon_name,
                    "target_sid": target_sid,
                    "bs": p1["bs"],
                    "bs_base": p1["bs_base"],
                    "cover": p1["cover"],
                    "display_wth": p1["display_wth"],
                    "display_save_th": p1["display_save_th"],
                    "player": int(attacker.get("player", 0)),  # get allowed
                    "attacks": 0,
                    "damage": 0,
                    "kills": 0,
                    "killed_model_ids": [],
                    "shots": [],
                }
            g = weapon_groups[group_key]
            g["attacks"] += intent_attacks
            g["damage"] += intent_damage
            g["kills"] += intent_kills
            g["killed_model_ids"].extend(killed_model_ids)
            g["shots"].extend(intent_shot_records)

    # Emit 1 log par groupe (weapon, target) pour toute l'escouade
    for g in weapon_groups.values():
        _emit_squad_shoot_log(game_state, g, SHOOT_CTX)

    # Meta cibles + escouades wipe (pour reward shaping proportionnel)
    summary["targets_meta"] = targets_meta
    summary["squads_wiped"] = [
        sid for sid in targets_meta
        if not [m for m in game_state["squad_models"].get(sid, []) if m in models_cache]  # get allowed
    ]
    # Nettoyage atomique
    clear_pending_shoot_intent(game_state, attacker_squad_id)
    return summary


# ============================================================================
# SQUAD SHOOT — allocation MANUELLE des pertes (defenseur humain) — 100% regles
# ============================================================================
# Resolveur INDEPENDANT du chemin auto (resolve_squad_shoot reste inchange, iso-RNG
# de l IA preserve). Conforme aux regles 40k 05.03 / 05.04 :
#   - jet de blessure vs T MAJORITAIRE de la cible (la plus haute si egalite) ;
#   - sauvegarde comparee au seuil de la fig REELLEMENT allouee (Sv/InSv + AP arme),
#     donc le save_roll est tire en amont mais COMPARE a l allocation ;
#   - degats tires UNIQUEMENT si la save echoue, appliques a la fig allouee ;
#   - groupes d allocation (1 par CHARACTER, 1 par triplet W/Sv/InSv) + ordre declare
#     par le defenseur ; CHARACTER inattaquable tant qu un non-CHARACTER vit.
# Consequence assumee : la sequence de tirages differe de resolve_squad_shoot (saves
# non pre-decidees, degats differes) -> plus d egalite manuel==auto, meme en homogene.


def _is_character_role(role: Optional[str]) -> bool:
    """CHARACTER au sens allocation 40k = role support/leader (cf. ROLE_TIER)."""
    return role in ("support", "leader")


def _target_majority_toughness(game_state: Dict[str, Any], target_sid: str) -> int:
    """T majoritaire des figs vivantes de la cible (la plus haute en cas d egalite).

    Regle 40k : le jet de blessure utilise la Endurance de la majorite des figurines
    de l unite ciblee. Leve si la cible n a aucune figurine vivante."""
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive = [m for m in squad_models.get(target_sid, []) if m in models_cache]  # get allowed
    if not alive:
        raise ValueError(f"Cible {target_sid} sans figurine vivante pour T majoritaire")
    counts: Dict[int, int] = {}
    for m in alive:
        t = int(models_cache[m]["T"])
        if t not in counts:
            counts[t] = 0
        counts[t] += 1
    max_count = max(counts.values())
    return max(t for t, c in counts.items() if c == max_count)


def _build_alloc_groups(game_state: Dict[str, Any], target_sid: str) -> List[Dict[str, Any]]:
    """Groupes d allocation 40k (05.03) : 1 par CHARACTER, 1 par triplet (W,Sv,InSv)
    pour le reste. Non-characters d abord (ordre de decouverte), puis characters.
    group_id = index de creation (stable)."""
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive = [m for m in squad_models.get(target_sid, []) if m in models_cache]  # get allowed
    non_char: Dict[tuple, List[str]] = {}
    non_char_order: List[tuple] = []
    char_models: List[str] = []
    for m in alive:
        e = models_cache[m]
        if _is_character_role(e.get("role")):
            char_models.append(m)
            continue
        key = (int(e["HP_MAX"]), int(e["ARMOR_SAVE"]), int(e.get("INVUL_SAVE", 7)))
        if key not in non_char:
            non_char[key] = []
            non_char_order.append(key)
        non_char[key].append(m)
    groups: List[Dict[str, Any]] = []
    for key in non_char_order:
        w, sv, insv = key
        mids = list(non_char[key])
        # Representant = une fig de role de base (role None) si possible, sinon la 1ere :
        # evite d identifier le groupe par un sergent/variant (ex. PackLeader).
        rep = next((m for m in mids if not models_cache[m].get("role")), mids[0])  # get allowed
        groups.append({
            "group_id": len(groups), "is_character": False, "role": None,
            "unit_type": models_cache[rep].get("unitType"),  # get allowed
            "W": w, "Sv": sv, "InSv": insv, "model_ids": mids,
        })
    for m in char_models:
        e = models_cache[m]
        groups.append({
            "group_id": len(groups), "is_character": True, "role": e.get("role"),
            "unit_type": e.get("unitType"),  # get allowed
            "W": int(e["HP_MAX"]), "Sv": int(e["ARMOR_SAVE"]), "InSv": int(e.get("INVUL_SAVE", 7)),
            "model_ids": [m],
        })
    return groups


def _group_alive(game_state: Dict[str, Any], g: Dict[str, Any]) -> bool:
    """True si au moins une figurine du groupe est vivante."""
    models_cache = require_key(game_state, "models_cache")
    return any(m in models_cache for m in g["model_ids"])


def _current_live_group(game_state: Dict[str, Any], batch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Groupe courant (ordre declare) du lot, en sautant les groupes vides. MUTE
    current_group_index (avance). Retourne None si tous les groupes sont morts."""
    groups_by_id = {g["group_id"]: g for g in batch["alloc_groups"]}
    order = batch["declared_order"]
    while batch["current_group_index"] < len(order):
        g = groups_by_id[order[batch["current_group_index"]]]
        if _group_alive(game_state, g):
            return g
        batch["current_group_index"] += 1
    return None


def _declare_order_payload(
    game_state: Dict[str, Any], batch: Dict[str, Any], live_groups: List[Dict[str, Any]],
    ctx: ManualAllocCtx,
) -> Dict[str, Any]:
    """Payload waiting : le defenseur doit declarer l ordre des groupes du lot (>=2 groupes)."""
    models_cache = require_key(game_state, "models_cache")

    def _wounded_in(g: Dict[str, Any]) -> bool:
        return any(
            m in models_cache and int(models_cache[m]["HP_CUR"]) < int(models_cache[m]["HP_MAX"])
            for m in g["model_ids"]
        )

    groups = [{
        "group_id": g["group_id"], "is_character": g["is_character"], "role": g["role"],
        "unit_type": g.get("unit_type"),
        "W": g["W"], "Sv": g["Sv"], "InSv": g["InSv"],
        "model_ids": [m for m in g["model_ids"] if m in models_cache],
        "has_wounded": _wounded_in(g),
    } for g in live_groups]
    alloc = require_key(game_state, ctx.alloc_key)
    attacker_unit_id = str(alloc["attacker_squad_id"])
    order_request: Dict[str, Any] = {
        "attacker_unit_id": attacker_unit_id,
        "target_unit_id": batch["target_sid"],
        "defender_player": batch["defender_player"],
        "wounds_to_save": len(batch["pool"]),
        "groups": groups,
    }
    if ctx.mortal:
        # Mortal wounds (hazard) : pas d arme, pas de save (armure ET invul ignorees, 10e).
        order_request["damage_type"] = "mortal"
    else:
        wg = alloc["weapon_groups"][batch["weapon_group_idx"]]
        order_request["weapon_name"] = wg["weapon_name"]
        order_request["weapon_names"] = wg.get("weapon_names", [wg["weapon_name"]])
        order_request["weapon_ap"] = int(wg["ap"])
        order_request["weapon_damage"] = wg["dmg_raw"]
    return {
        "action": ctx.declare_order_action,
        "waiting_for_player": True,
        "phase": ctx.phase_label,
        "order_request": order_request,
    }


def _manual_roll_intent(
    game_state: Dict[str, Any], intent: Dict[str, Any],
    targets_meta: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Jets d un intent pour le chemin MANUEL conforme (independant de l auto).

    Tire hit -> wound (vs T majoritaire) -> save_roll BRUT par blessure. Ne compare
    PAS la save et ne tire PAS les degats (resolus a l allocation, par fig choisie).
    Retourne None si l intent est a ignorer. N utilise PAS _roll_squad_shot_sequence
    (chemin auto inchange)."""
    import random
    models_cache = require_key(game_state, "models_cache")
    attacker_mid = intent["model_id"]
    attacker = models_cache.get(attacker_mid)  # get allowed
    if attacker is None:
        return None
    target_sid = str(intent["target_unit_id"])
    if target_sid not in game_state.get("squad_models", {}):  # get allowed
        return None
    if target_sid not in targets_meta:
        _tgt_uc = require_key(game_state, "units_cache")[target_sid]
        _tgt_sc = require_key(game_state, "squad_cache")[target_sid]
        targets_meta[target_sid] = {
            "value": float(require_key(_tgt_uc, "VALUE")),
            "model_count_at_start": int(require_key(_tgt_sc, "model_count_at_start")),
            "player": int(require_key(_tgt_uc, "player")),
        }
    weapon_index = int(intent.get("weapon_index", 0))  # get allowed
    weapons = attacker.get("RNG_WEAPONS", [])  # get allowed
    if not (0 <= weapon_index < len(weapons)):
        return None
    weapon = weapons[weapon_index]
    if not isinstance(weapon, dict):
        return None
    if "n_attacks_resolved" in intent:
        n_attacks = int(intent["n_attacks_resolved"])
    else:
        nb_raw = weapon.get("NB", 1)  # get allowed
        try:
            n_attacks = resolve_dice_value(nb_raw, f"squad_shoot_attacks_{attacker_mid}")
        except Exception:
            n_attacks = int(nb_raw) if isinstance(nb_raw, (int, float)) else 1
    if _has_blast_keyword(weapon):
        tgt_size = int(intent.get("target_squad_size_at_declaration", 0))  # get allowed
        n_attacks += tgt_size // 5
    if n_attacks <= 0:
        return None
    bs_base = int(weapon.get("ATK", weapon.get("BS", 4)))  # get allowed
    bs, cover = _cover_worsened_bs(game_state, attacker, target_sid, bs_base)
    strength = int(weapon.get("STR", weapon.get("S", attacker.get("T", 4))))  # get allowed
    ap = int(weapon.get("AP", 0))  # get allowed
    dmg_raw = weapon.get("DMG", 1)  # get allowed
    alive0 = [m for m in game_state["squad_models"].get(target_sid, []) if m in models_cache]  # get allowed
    if not alive0:
        return None
    # Conforme : seuil de blessure vs T MAJORITAIRE (depend de l arme via strength).
    wth = wound_threshold(strength, _target_majority_toughness(game_state, target_sid))
    first_alive = models_cache[alive0[0]]
    display_wth = wth
    display_save_th = save_threshold(int(first_alive["ARMOR_SAVE"]), int(first_alive.get("INVUL_SAVE", 7)), ap)
    weapon_name = weapon.get("display_name", weapon.get("NAME", weapon.get("name", "")))  # get allowed
    shot_records: List[Dict[str, Any]] = []
    pending_wounds: List[Dict[str, Any]] = []
    attacks = hits = wounds = 0
    for _ in range(int(n_attacks)):
        attacks += 1
        hit_roll = random.randint(1, 6)
        if hit_roll == 1 or hit_roll < bs:
            shot_records.append({"attackRoll": hit_roll, "hitResult": "MISS", "hitTarget": bs})
            continue
        hits += 1
        wound_roll = random.randint(1, 6)
        if wound_roll == 1 or wound_roll < wth:
            shot_records.append({"attackRoll": hit_roll, "hitResult": "HIT", "hitTarget": bs, "strengthRoll": wound_roll, "strengthResult": "FAILED", "woundTarget": wth})
            continue
        wounds += 1
        # save_roll tire ici (ordre RNG stable) mais COMPARE a l allocation (seuil de
        # la fig choisie). saveTarget/saveSuccess/damageDealt completes a l allocation.
        save_roll = random.randint(1, 6)
        rec = {"attackRoll": hit_roll, "hitResult": "HIT", "hitTarget": bs, "strengthRoll": wound_roll, "strengthResult": "SUCCESS", "woundTarget": wth, "saveRoll": save_roll, "damageDealt": 0}
        shot_records.append(rec)
        pending_wounds.append({"save_roll": save_roll, "rec": rec})
    return {
        "attacker_mid": attacker_mid, "attacker": attacker, "target_sid": target_sid,
        "weapon_name": weapon_name, "bs": bs, "bs_base": bs_base, "cover": cover, "ap": ap, "dmg_raw": dmg_raw,
        "display_wth": display_wth, "display_save_th": display_save_th,
        "shot_records": shot_records, "pending_wounds": pending_wounds,
        "counts": {"attacks": attacks, "hits": hits, "wounds": wounds},
    }


def _manual_waiting_payload(
    game_state: Dict[str, Any], batch: Dict[str, Any], alive_group: List[str],
    ctx: ManualAllocCtx,
) -> Dict[str, Any]:
    """Payload rendu au frontend quand le defenseur doit choisir une figurine.

    `alive_group` = figurines vivantes choisissables du GROUPE COURANT uniquement
    (toutes pleines : une fig blessee du groupe serait forcee, cf. _manual_allocation_step).
    Les figs hors groupe courant ne sont pas choisissables (frontend : grisees)."""
    models_cache = require_key(game_state, "models_cache")
    choices = [
        {
            "model_id": mid,
            "col": models_cache[mid].get("col"),  # get allowed
            "row": models_cache[mid].get("row"),  # get allowed
            "HP_CUR": int(models_cache[mid]["HP_CUR"]),
            "HP_MAX": int(models_cache[mid]["HP_MAX"]),
        }
        for mid in alive_group
    ]
    attacker_unit_id = str(require_key(game_state, ctx.alloc_key)["attacker_squad_id"])
    order = batch["declared_order"]
    cur_gid = (
        order[batch["current_group_index"]]
        if order is not None and batch["current_group_index"] < len(order)
        else None
    )
    return {
        "action": ctx.manual_alloc_action,
        "waiting_for_player": True,
        "phase": ctx.phase_label,
        "allocation": {
            "attacker_unit_id": attacker_unit_id,
            "target_unit_id": batch["target_sid"],
            "defender_player": batch["defender_player"],
            "choices": choices,
            "current_group_id": cur_gid,
            "wounds_remaining": len(batch["pool"]) - batch["pool_index"],
        },
    }


def _resolve_one_manual_wound(game_state: Dict[str, Any], alloc: Dict[str, Any], batch: Dict[str, Any], ctx: ManualAllocCtx) -> None:
    """Resout la prochaine blessure du pool du lot sur batch["current_model_id"] (conforme).

    AP et degats proviennent du profil d arme du lot (batch["weapon_group_idx"]). Compare
    le save_roll (pre-tire) au seuil de la fig allouee (Sv/InSv + AP arme). Save reussie ->
    aucun degat. Save echouee -> tire les degats et les applique (excess perdu par fig ;
    destroy_model si HP<=0 sinon update_model_hp). Complete le shot_record
    (saveTarget/saveSuccess/damageDealt). Remet current_model_id a None si la fig meurt
    (declenche un nouveau choix)."""
    models_cache = require_key(game_state, "models_cache")
    summary = alloc["summary"]
    cur = batch["current_model_id"]
    pw = batch["pool"][batch["pool_index"]]
    m = models_cache[cur]
    g = alloc["weapon_groups"][batch["weapon_group_idx"]]
    ap = int(g["ap"])
    dmg_raw = g["dmg_raw"]
    rec = pw["rec"]
    save_th = save_threshold(int(m["ARMOR_SAVE"]), int(m.get("INVUL_SAVE", 7)), ap)
    save_roll = int(pw["save_roll"])
    rec["saveTarget"] = save_th
    # Save reussie : roll != 1 et >= seuil. Aucun degat.
    if save_roll != 1 and save_roll >= save_th:
        rec["saveSuccess"] = True
        rec["damageDealt"] = 0
        batch["pool_index"] += 1
        return
    rec["saveSuccess"] = False
    summary["failed_saves"] += 1
    # Degats tires UNIQUEMENT maintenant (save echouee).
    try:
        dmg = resolve_dice_value(cast(DiceValue, dmg_raw), f"squad_shoot_dmg_{pw['attacker_mid']}")
    except Exception:
        dmg = int(dmg_raw) if isinstance(dmg_raw, (int, float)) else 1
    if dmg <= 0:
        rec["damageDealt"] = 0
        rec["targetDied"] = False
        batch["pool_index"] += 1
        return
    hp_before = int(m["HP_CUR"])
    dmg_dealt = min(int(dmg), hp_before)
    new_hp = hp_before - dmg_dealt
    destroyed = new_hp <= 0
    points_per_hp = float(require_key(m, "points_per_hp"))
    target_player = int(require_key(m, "player"))
    unit_type = m.get("unitType")  # get allowed
    col = m.get("col")  # get allowed
    row = m.get("row")  # get allowed
    g["damage"] += dmg_dealt
    summary["damage_total"] += dmg_dealt
    rec["damageDealt"] = dmg_dealt
    rec["targetDied"] = destroyed
    rec["targetUnitType"] = unit_type
    rec["targetCol"] = col
    rec["targetRow"] = row
    if destroyed:
        destroy_model(game_state, cur, reason="combat")
        g["kills"] += 1
        g["killed_model_ids"].append(str(cur))
        summary["models_killed"] += 1
    else:
        update_model_hp(game_state, cur, new_hp)
    # Hooks d application specifiques a la phase (fight : invalidations de cache + pools).
    # destroy_model/update_model_hp resynchronisent deja units_cache (somme des figs).
    if ctx.on_target_damaged is not None:
        ctx.on_target_damaged(game_state, batch["target_sid"])
    if destroyed and ctx.on_unit_destroyed is not None:
        squad_models = require_key(game_state, "squad_models")
        if not [mm for mm in squad_models.get(batch["target_sid"], []) if mm in models_cache]:  # get allowed
            ctx.on_unit_destroyed(game_state, batch["target_sid"])
    summary["events"].append({
        "attacker": pw["attacker_mid"], "target": cur,
        "target_squad_id": batch["target_sid"],
        "target_player": target_player, "points_per_hp": points_per_hp,
        "damage": dmg_dealt, "destroyed": destroyed,
    })
    batch["pool_index"] += 1
    if destroyed:
        batch["current_model_id"] = None


def _mark_manual_overkill_wasted(batch: Dict[str, Any]) -> None:
    """Cible entierement detruite avec des paquets non alloues : tirs restants perdus."""
    for pd in batch["pool"][batch["pool_index"]:]:
        pd["rec"]["wasted"] = True
    batch["pool_index"] = len(batch["pool"])


def _finalize_manual_allocation(game_state: Dict[str, Any], ctx: ManualAllocCtx) -> Dict[str, Any]:
    """Emet les logs (apres allocation complete) + nettoie l etat. Retourne le summary."""
    alloc = require_key(game_state, ctx.alloc_key)
    models_cache = require_key(game_state, "models_cache")
    summary = alloc["summary"]
    if ctx.finalize_log_fn is not None:
        ctx.finalize_log_fn(game_state, alloc, ctx)
    else:
        for g in alloc["weapon_groups"]:
            _emit_squad_shoot_log(game_state, g, ctx)
    targets_meta = summary.get("targets_meta", {})  # get allowed
    summary["squads_wiped"] = [
        sid for sid in targets_meta
        if not [m for m in game_state["squad_models"].get(sid, []) if m in models_cache]  # get allowed
    ]
    # Log de mort separe (type:"death") quand l unite cible est entierement detruite.
    # Le manuel tir ne l emet pas ; le combat oui (parite avec le chemin auto fight, §I).
    if ctx.emit_unit_death_log:
        for sid in summary["squads_wiped"]:
            tgt_unit = next((u for u in game_state["units"] if str(u["id"]) == str(sid)), None)
            append_action_log(game_state, {
                "type": "death",
                "message": f"Unit {sid} was DESTROYED",
                "turn": game_state.get("turn", 0),  # get allowed
                "phase": ctx.phase_label,
                "targetId": str(sid),
                "unitId": str(sid),
                "player": int(tgt_unit["player"]) if tgt_unit is not None else 0,
                "timestamp": "server_time",
            })
    del game_state[ctx.alloc_key]
    return {
        "action": ctx.manual_alloc_action,
        "waiting_for_player": False,
        "done": True,
        "shoot_result": summary,
    }


def _manual_allocation_step(game_state: Dict[str, Any], ctx: ManualAllocCtx) -> Dict[str, Any]:
    """Machine a etats : avance jusqu au prochain point de decision.

    Resout LOT PAR LOT (cible x profil d arme, regle 04.03). Pour chaque lot :
    1) cree les groupes d allocation (05.03) sur l etat COURANT de la cible (les blessures
       infligees par les lots precedents sont donc prises en compte) ;
    2) exige la declaration de l ordre des groupes (>=2 groupes vivants) ;
    3) resout les blessures du lot (pool deja trie save croissant, 05.04) groupe par groupe :
       une fig blessee est forcee, sinon waiting (choix libre dans le groupe courant).
    Passe au lot suivant quand son pool est epuise ou la cible entierement detruite.
    Termine par _finalize_manual_allocation."""
    alloc = require_key(game_state, ctx.alloc_key)
    models_cache = require_key(game_state, "models_cache")
    while alloc["current_batch_index"] < len(alloc["batches"]):
        batch = alloc["batches"][alloc["current_batch_index"]]
        # 1. Creation des groupes d allocation au debut du lot (etat courant de la cible).
        if batch["alloc_groups"] is None:
            batch["alloc_groups"] = _build_alloc_groups(game_state, batch["target_sid"])
        # 2. Declaration de l ordre des groupes du lot si necessaire (apres les jets).
        if batch["declared_order"] is None:
            live_groups = [g for g in batch["alloc_groups"] if _group_alive(game_state, g)]
            if len(live_groups) >= 2:
                return _declare_order_payload(game_state, batch, live_groups, ctx)
            batch["declared_order"] = [g["group_id"] for g in live_groups]  # ordre implicite
            batch["current_group_index"] = 0
        # 3. Allocation groupe par groupe (du lot).
        advanced_batch = False
        while True:
            if batch["pool_index"] >= len(batch["pool"]):
                alloc["current_batch_index"] += 1
                advanced_batch = True
                break
            grp = _current_live_group(game_state, batch)
            if grp is None:
                _mark_manual_overkill_wasted(batch)  # cible wipe : tirs restants perdus
                alloc["current_batch_index"] += 1
                advanced_batch = True
                break
            alive_grp = [m for m in grp["model_ids"] if m in models_cache]
            cur = batch["current_model_id"]
            if cur is None or cur not in models_cache or cur not in alive_grp:
                wounded = [
                    m for m in alive_grp
                    if int(models_cache[m]["HP_CUR"]) < int(models_cache[m]["HP_MAX"])
                ]
                if wounded:
                    batch["current_model_id"] = wounded[0]  # regle : finir une fig entamee
                else:
                    return _manual_waiting_payload(game_state, batch, alive_grp, ctx)  # choix libre
            (ctx.resolve_wound_fn or _resolve_one_manual_wound)(game_state, alloc, batch, ctx)
        if not advanced_batch:
            break
    return _finalize_manual_allocation(game_state, ctx)


def _build_manual_allocation(
    game_state: Dict[str, Any], attacker_squad_id: str, ctx: ManualAllocCtx,
    roll_intent_fn: Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Any]], Optional[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Moteur generique d allocation manuelle des pertes (tir ET combat).

    Resout les jets (hit/wound/save_roll) de tous les intents via `roll_intent_fn`
    (specifique a la phase), puis DIFFERE save+degats a l allocation. Persiste
    game_state[ctx.alloc_key] sous forme de LOTS (cible x profil d arme, regle 04.03),
    chacun resolu independamment (groupes + ordre + save croissant 05.04). Decremente
    ctx.attacks_left_attr par intent, nettoie les pending intents (ctx.intents_key), rend
    la main au defenseur (declaration d ordre puis choix de figs) ou termine directement."""
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    intents = list(game_state[ctx.intents_key].get(attacker_squad_id, []))  # get allowed
    summary: Dict[str, Any] = {
        "attacks_made": 0, "hits": 0, "wounds": 0, "failed_saves": 0,
        "damage_total": 0, "models_killed": 0, "events": [],
    }
    targets_meta: Dict[str, Dict[str, Any]] = {}
    weapon_groups: List[Dict[str, Any]] = []
    group_index_by_key: Dict[tuple, int] = {}
    batch_pool_by_gidx: Dict[int, List[Dict[str, Any]]] = {}

    for intent in intents:
        r = roll_intent_fn(game_state, intent, targets_meta)
        if r is None:
            continue
        attacker_mid = r["attacker_mid"]
        attacker = r["attacker"]
        target_sid = r["target_sid"]
        counts = r["counts"]
        summary["attacks_made"] += counts["attacks"]
        summary["hits"] += counts["hits"]
        summary["wounds"] += counts["wounds"]

        weapon_name = r["weapon_name"]
        # Regle 04.03 : les armes de PROFIL identique sur une meme cible se resolvent
        # ensemble (1 seul lot d allocation). La cle de groupe est donc le profil (et non
        # le nom) ; les noms distincts sont accumules pour l affichage (fenetre + log).
        gkey = (r["bs"], r["ap"], r["dmg_raw"], r["display_wth"], r["display_save_th"], target_sid)
        if gkey not in group_index_by_key:
            group_index_by_key[gkey] = len(weapon_groups)
            _grp = {
                "attacker_squad_id": str(attacker.get("squad_id", attacker_mid)),
                "weapon_name": weapon_name, "weapon_names": [weapon_name], "target_sid": target_sid,
                "bs": r["bs"], "ap": r["ap"], "dmg_raw": r["dmg_raw"],
                "display_wth": r["display_wth"], "display_save_th": r["display_save_th"],
                "player": int(attacker.get("player", 0)),  # get allowed
                "attacks": 0, "damage": 0, "kills": 0, "killed_model_ids": [], "shots": [],
            }
            # Cover (regle 13.08) : ranged-only -> present uniquement sur le chemin tir
            # (le chemin combat partage cette fonction mais ne fournit pas ces cles).
            if "cover" in r:
                _grp["bs_base"] = r["bs_base"]
                _grp["cover"] = r["cover"]
            weapon_groups.append(_grp)
        gidx = group_index_by_key[gkey]
        g = weapon_groups[gidx]
        if weapon_name not in g["weapon_names"]:
            g["weapon_names"].append(weapon_name)
            g["weapon_name"] = " / ".join(g["weapon_names"])
        g["attacks"] += counts["attacks"]
        g["shots"].extend(r["shot_records"])

        # Blessures accumulees PAR PROFIL d arme (gidx) : chaque profil = un lot resolu
        # independamment (regle 04.03). Triees save croissant a la construction du lot.
        if gidx not in batch_pool_by_gidx:
            batch_pool_by_gidx[gidx] = []
        for pw in r["pending_wounds"]:
            batch_pool_by_gidx[gidx].append({
                "save_roll": pw["save_roll"],
                "rec": pw["rec"], "attacker_mid": attacker_mid,
            })

        # decrement attacks_left (tir : 1 par intent ; combat : nb d attaques de l intent)
        if attacker_mid in models_cache:
            al = int(models_cache[attacker_mid].get(ctx.attacks_left_attr, 0))  # get allowed
            dec = int(counts["attacks"]) if ctx.decrement_by_attacks else 1
            models_cache[attacker_mid][ctx.attacks_left_attr] = max(0, al - dec)

    # Construction des lots (cible x profil d arme, regle 04.03) : tous les profils d une
    # meme cible sont resolus consecutivement (ordre de premiere apparition), avant la
    # cible suivante. Un lot par profil ayant au moins une blessure a resoudre.
    target_order: List[str] = []
    for g in weapon_groups:
        if g["target_sid"] not in target_order:
            target_order.append(g["target_sid"])
    batches: List[Dict[str, Any]] = []
    for tsid in target_order:
        for gidx, g in enumerate(weapon_groups):
            if g["target_sid"] != tsid:
                continue
            pool = batch_pool_by_gidx.get(gidx, [])  # get allowed
            if not pool:
                continue  # ce profil n a inflige aucune blessure -> aucun lot a resoudre
            # Regle 05.04 (INFLICT DAMAGE) : du save_roll le plus bas au plus haut (tri
            # stable, l ordre d attaque departage les egalites). Determine l ordre de
            # tirage des degats des armes a degats variables (conforme, voulu).
            pool_sorted = sorted(pool, key=lambda pw: pw["save_roll"])
            batches.append({
                "target_sid": tsid,
                "weapon_group_idx": gidx,
                "defender_player": int(targets_meta[tsid]["player"]),
                "alloc_groups": None,  # cree au debut du lot (etat courant de la cible)
                "declared_order": None, "current_group_index": 0,
                "current_model_id": None, "pool": pool_sorted, "pool_index": 0,
            })

    summary["targets_meta"] = targets_meta
    game_state[ctx.alloc_key] = {
        "attacker_squad_id": str(attacker_squad_id),
        "weapon_groups": weapon_groups,
        "batches": batches,
        "current_batch_index": 0,
        "summary": summary,
    }
    init_pending_intents(game_state)
    game_state[ctx.intents_key].pop(str(attacker_squad_id), None)
    return _manual_allocation_step(game_state, ctx)


def build_manual_shoot_allocation(game_state: Dict[str, Any], attacker_squad_id: str) -> Dict[str, Any]:
    """Allocation manuelle des pertes au TIR (defenseur humain). Cf. _build_manual_allocation."""
    return _build_manual_allocation(game_state, attacker_squad_id, SHOOT_CTX, _manual_roll_intent)


def _resolve_one_hazard_wound(
    game_state: Dict[str, Any], alloc: Dict[str, Any], batch: Dict[str, Any], ctx: ManualAllocCtx
) -> None:
    """Resout 1 mortal wound (hazard 06.03) sur batch["current_model_id"].

    Mortal wound : AUCUNE sauvegarde (armure ET invulnerable ignorees, 10e) et 1 point de
    degat. destroy_model (reason='hazard') si HP<=0, sinon update_model_hp. Remplit
    ``alloc["hazard_details"]`` (forme {modelId,col,row,died}) pour le log differe. Remet
    current_model_id a None si la fig meurt (declenche un nouveau choix)."""
    models_cache = require_key(game_state, "models_cache")
    summary = alloc["summary"]
    cur = batch["current_model_id"]
    m = models_cache[cur]
    col = m.get("col")  # get allowed
    row = m.get("row")  # get allowed
    hp_before = int(m["HP_CUR"])
    new_hp = hp_before - 1
    destroyed = new_hp <= 0
    summary["failed_saves"] += 1
    summary["damage_total"] += 1
    if destroyed:
        destroy_model(game_state, cur, reason="hazard")
        summary["models_killed"] += 1
    else:
        update_model_hp(game_state, cur, new_hp)
    alloc["hazard_details"].append(
        {"modelId": str(cur), "col": col, "row": row, "died": destroyed}
    )
    batch["pool_index"] += 1
    if destroyed:
        batch["current_model_id"] = None


def _finalize_hazard_alloc_log(
    game_state: Dict[str, Any], alloc: Dict[str, Any], ctx: ManualAllocCtx
) -> None:
    """Emet la ligne de log hazard differee, completee de ses hazardDetails, en fin
    d allocation manuelle (calquee sur le tir : log emis avec ses details complets)."""
    payload = alloc["hazard_log_payload"]
    payload["hazardDetails"] = alloc["hazard_details"]
    append_action_log(game_state, payload)


HAZARD_CTX = ManualAllocCtx(
    alloc_key="pending_hazard_allocation",
    declare_order_action="squad_hazard_declare_order",
    manual_alloc_action="squad_hazard_manual_alloc",
    phase_label="move",
    log_type="hazard",
    log_verb="HAZARD",
    attacks_left_attr="",  # non utilise (pas d intents/armes)
    intents_key="",         # non utilise (pas d intents/armes)
    mortal=True,
    resolve_wound_fn=_resolve_one_hazard_wound,
    finalize_log_fn=_finalize_hazard_alloc_log,
)


def build_manual_hazard_allocation(
    game_state: Dict[str, Any], squad_id: str, n_wounds: int, log_payload: Dict[str, Any]
) -> Dict[str, Any]:
    """Allocation manuelle des mortal wounds d un Desperate Escape (hazard 06.03), defenseur
    humain. Reutilise la couche allocation des pertes du tir (groupes 05.03, declaration
    d ordre, choix de figurine, regle 06.02) mais SANS save et a degat fixe (cf. HAZARD_CTX).

    Construit l etat d allocation (un seul lot ; la "cible" = l unite elle-meme ; pool de
    n_wounds), persiste ``log_payload`` pour emission differee a la fin, puis rend la main au
    joueur (declaration d ordre ou choix de fig) ou termine directement (figs forcees)."""
    sid = str(squad_id)
    units_cache = require_key(game_state, "units_cache")
    uc = require_key(units_cache, sid)
    defender_player = int(require_key(uc, "player"))
    summary: Dict[str, Any] = {
        "attacks_made": 0, "hits": 0, "wounds": int(n_wounds), "failed_saves": 0,
        "damage_total": 0, "models_killed": 0, "events": [],
        "targets_meta": {sid: {"player": defender_player}},
    }
    batch = {
        "target_sid": sid,
        "weapon_group_idx": None,
        "defender_player": defender_player,
        "alloc_groups": None,
        "declared_order": None, "current_group_index": 0,
        "current_model_id": None,
        # Items minimaux : "rec" present pour _mark_manual_overkill_wasted (overkill MW perdues).
        "pool": [{"rec": {}} for _ in range(int(n_wounds))], "pool_index": 0,
    }
    game_state[HAZARD_CTX.alloc_key] = {
        "attacker_squad_id": sid,
        "weapon_groups": [],
        "batches": [batch],
        "current_batch_index": 0,
        "summary": summary,
        "hazard_details": [],
        "hazard_log_payload": log_payload,
    }
    return _manual_allocation_step(game_state, HAZARD_CTX)


def apply_manual_shoot_declare_order(game_state: Dict[str, Any], order: List[Any], ctx: ManualAllocCtx) -> Dict[str, Any]:
    """Enregistre l ordre des groupes declare par le defenseur (apres les jets) puis avance.

    Valide (erreur explicite, KeyError si invalide) : permutation des groupes vivants ;
    aucun CHARACTER avant un non-CHARACTER ; groupe non-CHARACTER blesse avant non-CHARACTER
    sain ; CHARACTER blesse avant CHARACTER sain."""
    alloc = require_key(game_state, ctx.alloc_key)
    models_cache = require_key(game_state, "models_cache")
    bi = alloc["current_batch_index"]
    if bi >= len(alloc["batches"]):
        raise ValueError("aucun lot courant pour declarer l ordre des groupes")
    batch = alloc["batches"][bi]
    if batch["declared_order"] is not None:
        raise ValueError("ordre des groupes deja declare pour ce lot")
    groups_by_id = {g["group_id"]: g for g in batch["alloc_groups"]}
    live_ids = [g["group_id"] for g in batch["alloc_groups"] if _group_alive(game_state, g)]
    order_int = [int(x) for x in order]
    if sorted(order_int) != sorted(live_ids):
        raise ValueError(f"ordre {order_int} n est pas une permutation des groupes vivants {live_ids}")

    def _is_char(gid: int) -> bool:
        return bool(groups_by_id[gid]["is_character"])

    def _wounded(gid: int) -> bool:
        return any(
            m in models_cache and int(models_cache[m]["HP_CUR"]) < int(models_cache[m]["HP_MAX"])
            for m in groups_by_id[gid]["model_ids"]
        )

    seen_char = False
    for gid in order_int:
        if _is_char(gid):
            seen_char = True
        elif seen_char:
            raise ValueError("un non-CHARACTER ne peut pas etre place apres un CHARACTER")
    seen_nonchar_healthy = False
    for gid in order_int:
        if _is_char(gid):
            continue
        if _wounded(gid):
            if seen_nonchar_healthy:
                raise ValueError("un groupe non-CHARACTER blesse doit preceder les groupes sains")
        else:
            seen_nonchar_healthy = True
    seen_char_healthy = False
    for gid in order_int:
        if not _is_char(gid):
            continue
        if _wounded(gid):
            if seen_char_healthy:
                raise ValueError("un CHARACTER blesse doit preceder un CHARACTER sain")
        else:
            seen_char_healthy = True

    batch["declared_order"] = order_int
    batch["current_group_index"] = 0
    return _manual_allocation_step(game_state, ctx)


def apply_manual_shoot_allocation(game_state: Dict[str, Any], chosen_model_id: str, ctx: ManualAllocCtx) -> Dict[str, Any]:
    """Enregistre le choix du defenseur (figurine qui encaisse) puis avance l allocation.

    Valide que chosen_model_id est une figurine vivante du GROUPE COURANT, et qu une
    figurine blessee du groupe n est pas contournee (regle 05.04). Retourne le payload
    du point de decision suivant (waiting) ou le summary final (done)."""
    alloc = require_key(game_state, ctx.alloc_key)
    models_cache = require_key(game_state, "models_cache")
    bi = alloc["current_batch_index"]
    if bi >= len(alloc["batches"]):
        return _finalize_manual_allocation(game_state, ctx)
    batch = alloc["batches"][bi]
    order = batch["declared_order"]
    if order is None:
        raise ValueError("ordre des groupes non declare avant l allocation")
    if batch["current_group_index"] >= len(order):
        raise ValueError("aucun groupe courant pour l allocation")
    gid = order[batch["current_group_index"]]
    grp = next(g for g in batch["alloc_groups"] if g["group_id"] == gid)
    alive_grp = [m for m in grp["model_ids"] if m in models_cache]
    if chosen_model_id not in alive_grp:
        raise ValueError(
            f"chosen_model_id {chosen_model_id!r} n est pas une figurine vivante du groupe "
            f"courant {gid} (alive={alive_grp})"
        )
    wounded = [
        m for m in alive_grp
        if int(models_cache[m]["HP_CUR"]) < int(models_cache[m]["HP_MAX"])
    ]
    if wounded and chosen_model_id not in wounded:
        raise ValueError(
            f"must allocate to a wounded model first (regle 05.04): wounded={wounded}"
        )
    batch["current_model_id"] = chosen_model_id
    return _manual_allocation_step(game_state, ctx)


def manual_allocation_waiting_payload(game_state: Dict[str, Any], ctx: ManualAllocCtx) -> Dict[str, Any]:
    """Reconstruit (read-only) le payload waiting courant d une allocation manuelle en
    cours (declaration d ordre OU choix de fig). Utilise par le garde-fou pour re-signaler
    l attente sans muter l etat. Suppose qu une allocation est pending (sinon leve)."""
    alloc = require_key(game_state, ctx.alloc_key)
    models_cache = require_key(game_state, "models_cache")
    batch = alloc["batches"][alloc["current_batch_index"]]
    if batch["declared_order"] is None:
        live_groups = [g for g in batch["alloc_groups"] if _group_alive(game_state, g)]
        if len(live_groups) >= 2:
            return _declare_order_payload(game_state, batch, live_groups, ctx)
    order = batch["declared_order"]
    grp = None
    if order is not None and batch["current_group_index"] < len(order):
        gid = order[batch["current_group_index"]]
        grp = next((g for g in batch["alloc_groups"] if g["group_id"] == gid), None)
    alive_grp = [m for m in (grp["model_ids"] if grp else []) if m in models_cache]
    return _manual_waiting_payload(game_state, batch, alive_grp, ctx)


# ============================================================================
# SQUAD FIGHT — activation start + ordering (squad.md PR3 3d)
# ============================================================================


def squad_fight_unit_activation_start(
    game_state: Dict[str, Any], squad_id: str
) -> None:
    """Initialise l activation fight d une escouade.

    - Verifie pas de pending leftover (bug detection).
    - Initialise pending_squad_fight_intents[squad_id] = [].
    - Reset ATTACK_LEFT par fig selon l arme CC actuellement selectionnee (NB).

    Auto-selection d arme : NON ici — reportee au moment de la declaration de
    cible (la formule expected damage P(hit)*P(wound)*P(failed_save)*D requiert
    de connaitre T et Sv de la cible, cf. spec §"Auto-selection de l arme").
    Si la fig change d arme en declaration, ATTACK_LEFT sera recalcule a ce
    moment-la (responsabilite du caller de declaration).
    """
    assert_no_pending_fight_intent(game_state, squad_id)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    for mid in squad_models.get(squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is None:
            continue
        weapons = m.get("CC_WEAPONS", [])  # get allowed
        sel = m.get("selectedCcWeaponIndex")
        if weapons and sel is not None and 0 <= int(sel) < len(weapons):
            w = weapons[int(sel)]
            if isinstance(w, dict) and "NB" in w:
                m["ATTACK_LEFT"] = resolve_dice_value(w["NB"], f"squad_fight_init_{mid}")
            else:
                m["ATTACK_LEFT"] = 0
        else:
            m["ATTACK_LEFT"] = 0
    game_state["pending_squad_fight_intents"][squad_id] = []


def _squad_is_in_fight(game_state: Dict[str, Any], squad_id: str) -> bool:
    """Une escouade est eligible au combat si :
       - elle a charge ce tour (squad_id dans units_charged), OU
       - au moins une figurine est dans l ER d une unite ennemie.
    """
    if squad_id in game_state.get("units_charged", set()):
        return True
    # ER bord-a-bord : au moins une figurine dans l ER d une unite ennemie.
    return _squad_is_in_enemy_er(game_state, str(squad_id))


def squad_fight_activation_order(
    game_state: Dict[str, Any], active_player: int
) -> List[Tuple[str, str]]:
    """Construit l ordre d activation des escouades en Fight phase.

    Regle officielle (cf. spec §"Ordre d activation") :
      - Step 1 (Fights First) : escouades dans `units_charged` ou avec ability
        Fights First. Alternance : non-active player d abord, puis active.
      - Step 2 (Remaining Combats) : autres escouades eligibles. Meme alternance.
      - Chaque escouade s active une seule fois par phase.

    Returns liste ordonnee de tuples (squad_id, step) ou step ∈ {"fights_first", "remaining"}.

    PR3 3d : ne lit que les structures squad-level (units_charged, units_cache).
    Pour Fights First ability (regles speciales), `units_cache[sid].get("fights_first")`
    bool optionnel — defaut False.
    """
    units_charged = game_state.get("units_charged", set())
    units_cache = game_state.get("units_cache", {})  # get allowed
    eligible: Dict[str, str] = {}
    for sid, entry in units_cache.items():
        if not _squad_is_in_fight(game_state, str(sid)):
            continue
        ff = bool(entry.get("fights_first", False))
        if str(sid) in units_charged or ff:
            eligible[str(sid)] = "fights_first"
        else:
            eligible[str(sid)] = "remaining"

    def _player_of(sid: str) -> int:
        return int(units_cache.get(sid, {}).get("player", -1))  # get allowed

    def _alternate(squads_in_step: List[str], step_name: str) -> List[Tuple[str, str]]:
        # Tri non-active d abord, puis active. A egalite : ordre d'id (deterministe).
        non_active = sorted(s for s in squads_in_step if _player_of(s) != int(active_player))
        active = sorted(s for s in squads_in_step if _player_of(s) == int(active_player))
        out: List[Tuple[str, str]] = []
        # Alternance stricte non-active → active → non-active...
        i_na, i_ac = 0, 0
        turn_non_active = True
        while i_na < len(non_active) or i_ac < len(active):
            if turn_non_active and i_na < len(non_active):
                out.append((non_active[i_na], step_name)); i_na += 1
            elif not turn_non_active and i_ac < len(active):
                out.append((active[i_ac], step_name)); i_ac += 1
            elif i_na < len(non_active):
                out.append((non_active[i_na], step_name)); i_na += 1
            elif i_ac < len(active):
                out.append((active[i_ac], step_name)); i_ac += 1
            turn_non_active = not turn_non_active
        return out

    ff_squads = [s for s, st in eligible.items() if st == "fights_first"]
    rem_squads = [s for s, st in eligible.items() if st == "remaining"]
    return _alternate(ff_squads, "fights_first") + _alternate(rem_squads, "remaining")


# ============================================================================
# SQUAD FIGHT — Pile In + buddy rule (squad.md PR3 3e)
# ============================================================================


def fight_pile_in_plan(
    game_state: Dict[str, Any], squad_id: str
) -> Optional[List[Tuple[str, int, int]]]:
    """Plan Pile In multi-figurines (transaction atomique, aucune ecriture cache).

    Regle officielle (spec §"Pile In") :
    Chaque figurine non-B2B avec un ennemi peut se deplacer jusqu a 3" pour
    (a) finir B2B avec un ennemi si possible (OBLIGATOIRE si conditions remplies),
    (b) sinon minimiser la distance au plus proche ennemi.
    Apres placement, l escouade doit etre en coherency ET au moins une figurine
    doit etre dans l ER d une unite ennemie.

    Algorithme :
      - Ordre par index figurine.
      - Chaque fig deja en B2B (regle officielle) reste sur place.
      - Sinon : cherche dans le disque de rayon 3" l hex (i) B2B avec ennemi
        (priorite) ou (ii) plus proche d un ennemi qu avant.
      - A egalite : hex de plus petit index dans get_hex_neighbors.
      - Validation finale : coherency + ER.
      - Si validation echoue : retourne None (transaction atomique).

    Returns liste de (model_id, col, row) ou None.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    mids = [m for m in squad_models.get(squad_id, []) if m in models_cache]  # get allowed
    if not mids:
        return None

    units_cache = game_state.get("units_cache", {})  # get allowed
    our_entry = units_cache.get(squad_id)
    if our_entry is None:
        return None
    our_player = int(our_entry.get("player", -1))

    # Positions ennemies (tous les modeles)
    enemy_positions: List[Tuple[int, int]] = []
    for esid in _enemy_squad_ids(game_state, our_player):
        enemy_positions.extend(_squad_model_positions(game_state, esid))
    if not enemy_positions:
        return None

    ish = int(require_key(game_state, "inches_to_subhex"))
    pile_in_budget = 3 * ish  # 3" en subhexes
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())

    occupied_after: Set[Tuple[int, int]] = set()
    plan: List[Tuple[str, int, int]] = []

    def _is_b2b_with_enemy(col: int, row: int) -> bool:
        for ec, er in enemy_positions:
            if calculate_hex_distance(col, row, ec, er) == BASE_TO_BASE_SUBHEX:
                return True
        return False

    def _cell_legal(col: int, row: int) -> bool:
        # B3 cleanup (audit) : parametre exclude supprime (jamais utilise)
        if col < 0 or row < 0 or col >= board_cols or row >= board_rows:
            return False
        cell = (col, row)
        if wall_hexes and cell in wall_hexes:
            return False
        if cell in occupied_after:
            return False
        # Pas de collision avec autres escouades (sauf notre cellule d origine).
        for sid, entry in units_cache.items():
            if str(sid) == squad_id:
                continue
            occ = entry.get("occupied_hexes")
            if occ and cell in occ:
                return False
        return True

    for mid in mids:
        m = models_cache[mid]
        orig_col, orig_row = int(m["col"]), int(m["row"])
        # Deja B2B : reste sur place
        if _is_b2b_with_enemy(orig_col, orig_row):
            plan.append((mid, orig_col, orig_row))
            occupied_after.add((orig_col, orig_row))
            continue
        # Cherche (a) B2B candidate
        b2b_cands: List[Tuple[int, int, int]] = []  # (dist_from_orig, col, row)
        for ec, er in enemy_positions:
            for nc, nr in get_hex_neighbors(ec, er):
                if not _cell_legal(nc, nr):
                    continue
                d = calculate_hex_distance(orig_col, orig_row, nc, nr)
                if d > pile_in_budget:
                    continue
                b2b_cands.append((d, nc, nr))
        picked: Optional[Tuple[int, int]] = None
        if b2b_cands:
            b2b_cands.sort()  # plus proche d origine d abord
            _, pc, pr = b2b_cands[0]
            picked = (pc, pr)
        else:
            # (b) Plus proche d un ennemi
            nearest = min(
                enemy_positions,
                key=lambda ep: calculate_hex_distance(orig_col, orig_row, ep[0], ep[1]),
            )
            tc, tr = nearest
            orig_dist = calculate_hex_distance(orig_col, orig_row, tc, tr)
            best: Optional[Tuple[int, int, int]] = None  # (dist_to_target, col, row)
            for d in range(1, pile_in_budget + 1):
                for d_col in range(-d, d + 1):
                    for d_row in range(-d, d + 1):
                        if max(abs(d_col), abs(d_row)) != d:
                            continue
                        nc, nr = orig_col + d_col, orig_row + d_row
                        if not _cell_legal(nc, nr):
                            continue
                        cand_d = calculate_hex_distance(nc, nr, tc, tr)
                        if cand_d >= orig_dist:
                            continue
                        if best is None or cand_d < best[0]:
                            best = (cand_d, nc, nr)
                if best is not None:
                    break
            if best is not None:
                _, pc, pr = best
                picked = (pc, pr)
        # Si pas de move utile : reste sur place (regle officielle : Pile In optionnel
        # par-figurine ; seule l obligation B2B contraint).
        if picked is None:
            picked = (orig_col, orig_row)
        plan.append((mid, picked[0], picked[1]))
        occupied_after.add(picked)

    # Validation finale
    plan_positions = {mid: (c, r) for mid, c, r in plan}
    if not _validate_plan_coherency(plan_positions, game_state):
        return None
    # Au moins une figurine doit finir dans l ER (bord-a-bord) d une unite ennemie.
    from engine.spatial_relations import unit_entries_within_engagement_zone
    ez = get_engagement_zone(game_state)
    enemy_entries = [
        e for e in (units_cache.get(esid) for esid in _enemy_squad_ids(game_state, our_player))
        if e is not None
    ]
    in_er = False
    for mid, c, r in plan:
        synth = _synth_model_entry(game_state, str(squad_id), models_cache[mid], c, r)
        if any(unit_entries_within_engagement_zone(synth, ee, ez) for ee in enemy_entries):
            in_er = True
            break
    if not in_er:
        return None
    return plan


def get_fighting_models(game_state: Dict[str, Any], squad_id: str) -> List[str]:
    """Retourne les model_ids d une escouade autorises a frapper en melee.

    Regle officielle (spec §"Quelles figurines peuvent frapper — buddy rule") :
      Une fig peut attaquer si :
        (1) elle est dans l ER d une unite ennemie, OU
        (2) elle est en B2B avec une figurine ALLIEE de SON propre squad qui est
            elle-meme en B2B avec un modele ennemi.
      La condition (2) n est PAS transitive (1 niveau de buddy max).

    Ordre de retour : par index figurine (deterministe).
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    mids = [m for m in squad_models.get(squad_id, []) if m in models_cache]  # get allowed
    if not mids:
        return []
    units_cache = game_state.get("units_cache", {})  # get allowed
    our_player = int(units_cache.get(squad_id, {}).get("player", -1))  # get allowed
    from engine.spatial_relations import unit_entries_within_engagement_zone
    ez = get_engagement_zone(game_state)
    enemy_positions: List[Tuple[int, int]] = []
    enemy_entries: List[Dict[str, Any]] = []
    for esid in _enemy_squad_ids(game_state, our_player):
        enemy_positions.extend(_squad_model_positions(game_state, esid))
        ee = units_cache.get(esid)
        if ee is not None:
            enemy_entries.append(ee)
    if not enemy_positions:
        return []

    # Pre-calcule : pour chaque fig, est-elle en ER (bord-a-bord) d un ennemi ? + position
    positions: Dict[str, Tuple[int, int]] = {}
    in_er: Dict[str, bool] = {}
    b2b_enemy: Dict[str, bool] = {}
    for mid in mids:
        m = models_cache[mid]
        pos = (int(m["col"]), int(m["row"]))
        positions[mid] = pos
        synth = _synth_model_entry(game_state, str(squad_id), m, pos[0], pos[1])
        in_er[mid] = any(
            unit_entries_within_engagement_zone(synth, ee, ez) for ee in enemy_entries
        )
        b2b_enemy[mid] = any(
            calculate_hex_distance(pos[0], pos[1], ec, er) == BASE_TO_BASE_SUBHEX
            for ec, er in enemy_positions
        )

    # Condition (1) : in ER.
    # Condition (2) : B2B avec un allie du meme squad qui est B2B avec un ennemi.
    out: List[str] = []
    for mid in mids:
        if in_er[mid]:
            out.append(mid)
            continue
        my_pos = positions[mid]
        relayed = False
        for other_mid in mids:
            if other_mid == mid:
                continue
            if not b2b_enemy.get(other_mid, False):
                continue
            other_pos = positions[other_mid]
            if calculate_hex_distance(my_pos[0], my_pos[1], other_pos[0], other_pos[1]) == BASE_TO_BASE_SUBHEX:
                relayed = True
                break
        if relayed:
            out.append(mid)
    return out


# ============================================================================
# SQUAD FIGHT — declaration + resolution + consolidation (squad.md PR3 3f)
# ============================================================================


def _auto_select_cc_weapon_for_fig(
    attacker: Dict[str, Any], target_t: int, target_sv: int, target_invul: int
) -> int:
    """Choisit l index de l arme CC maximisant l expected damage P(hit)*P(wound)*P(failed_save)*D.

    Tie-break : index d arme le plus bas. Si pas d arme : retourne 0 (no-op).
    """
    weapons = attacker.get("CC_WEAPONS", [])  # get allowed
    if not weapons:
        return 0
    best_idx = 0
    best_score = -1.0
    for idx, w in enumerate(weapons):
        if not isinstance(w, dict):
            continue
        ws = int(w.get("ATK", w.get("WS", 4)))  # WS via ATK convention
        s = int(w.get("STR", w.get("S", 4)))
        ap = int(w.get("AP", 0))  # get allowed
        dmg_raw = w.get("DMG", 1)
        try:
            dmg = float(expected_dice_value(dmg_raw, f"auto_select_cc_dmg"))
        except Exception:
            dmg = float(dmg_raw) if isinstance(dmg_raw, (int, float)) else 1.0
        # P(hit) : roll >= ws, et 1 always fail
        p_hit = max(0.0, (7 - ws) / 6.0) if ws <= 6 else 0.0
        wth = wound_threshold(s, target_t)
        p_wound = max(0.0, (7 - wth) / 6.0)
        save_th = save_threshold(target_sv, target_invul, ap)
        if save_th >= 7:
            p_failed_save = 1.0
        else:
            p_failed_save = max(0.0, (save_th - 1) / 6.0)
        score = p_hit * p_wound * p_failed_save * dmg
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx


def squad_declare_fight(
    game_state: Dict[str, Any],
    attacker_squad_id: str,
    target_squad_id: str,
) -> List[Dict[str, Any]]:
    """Construit les declarations de combat pour une escouade (per-fig).

    PR3 3f MVP : auto-cible = target_squad_id passe par le caller (l agent a deja
    choisi). Auto-selection d arme CC par fig selon expected damage vs T/Sv cible.

    Eligibilite per fig = `get_fighting_models` (in ER OR buddy rule).

    Returns la liste d intents (aussi stockee dans pending_squad_fight_intents).
    """
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    if attacker_squad_id not in game_state["pending_squad_fight_intents"]:
        raise RuntimeError(
            f"squad_declare_fight called before squad_fight_unit_activation_start "
            f"for squad {attacker_squad_id!r}"
        )
    # Target info pour auto-select
    target_alive = [
        m for m in squad_models.get(target_squad_id, []) if m in models_cache  # get allowed
    ]
    if not target_alive:
        return []  # cible deja wipe
    t_sample = models_cache[target_alive[0]]
    target_t = int(t_sample.get("T", 4))
    target_sv = int(t_sample.get("ARMOR_SAVE", 7))
    target_invul = int(t_sample.get("INVUL_SAVE", 7))

    fighting = get_fighting_models(game_state, attacker_squad_id)
    intents: List[Dict[str, Any]] = game_state["pending_squad_fight_intents"][attacker_squad_id]
    for mid in fighting:
        m = models_cache.get(mid)
        if m is None:
            continue
        chosen_idx = _auto_select_cc_weapon_for_fig(m, target_t, target_sv, target_invul)
        m["selectedCcWeaponIndex"] = chosen_idx
        # F3 fix (audit) : resoudre NB UNE SEULE FOIS, stocker dans intent.
        weapons = m.get("CC_WEAPONS", [])  # get allowed
        n_attacks_resolved = 0
        if 0 <= chosen_idx < len(weapons):
            w = weapons[chosen_idx]
            if isinstance(w, dict) and "NB" in w:
                try:
                    n_attacks_resolved = int(resolve_dice_value(w["NB"], f"squad_declare_fight_NB_{mid}"))
                except Exception:
                    n_attacks_resolved = int(w["NB"]) if isinstance(w["NB"], (int, float)) else 1
                m["ATTACK_LEFT"] = n_attacks_resolved
        intents.append({
            "model_id": mid,
            "weapon_index": chosen_idx,
            "target_unit_id": target_squad_id,
            "n_attacks_resolved": n_attacks_resolved,
        })
    return intents


def resolve_squad_fight(
    game_state: Dict[str, Any], attacker_squad_id: str
) -> Dict[str, Any]:
    """Resolution melee (Hit→Wound→Save→Damage). Meme structure que resolve_squad_shoot.

    Differences :
      - Lit CC_WEAPONS au lieu de RNG_WEAPONS.
      - Pas de BLAST en melee.
      - Decremente ATTACK_LEFT au lieu de SHOOT_LEFT.
    """
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    intents = list(game_state["pending_squad_fight_intents"].get(attacker_squad_id, []))  # get allowed
    summary: Dict[str, Any] = {
        "attacks_made": 0, "hits": 0, "wounds": 0,
        "failed_saves": 0, "damage_total": 0, "models_killed": 0, "events": [],
    }
    targets_meta: Dict[str, Dict[str, Any]] = {}
    import random
    for intent in intents:
        attacker_mid = intent["model_id"]
        attacker = models_cache.get(attacker_mid)
        if attacker is None:
            continue
        target_sid = str(intent["target_unit_id"])
        if target_sid not in game_state.get("squad_models", {}):  # get allowed
            continue
        if target_sid not in targets_meta:
            _tgt_uc = require_key(game_state, "units_cache")[target_sid]
            _tgt_sc = require_key(game_state, "squad_cache")[target_sid]
            targets_meta[target_sid] = {
                "value": float(require_key(_tgt_uc, "VALUE")),
                "model_count_at_start": int(require_key(_tgt_sc, "model_count_at_start")),
                "player": int(require_key(_tgt_uc, "player")),
            }
        weapon_index = int(intent.get("weapon_index", 0))  # get allowed
        weapons = attacker.get("CC_WEAPONS", [])  # get allowed
        if not (0 <= weapon_index < len(weapons)):
            continue
        weapon = weapons[weapon_index]
        if not isinstance(weapon, dict):
            continue
        # F3 fix (audit) : lire n_attacks_resolved depuis l intent.
        if "n_attacks_resolved" in intent:
            n_attacks = int(intent["n_attacks_resolved"])
        else:
            nb_raw = weapon.get("NB", 1)
            try:
                n_attacks = resolve_dice_value(nb_raw, f"squad_fight_attacks_{attacker_mid}")
            except Exception:
                n_attacks = int(nb_raw) if isinstance(nb_raw, (int, float)) else 1
        if n_attacks <= 0:
            continue
        ws = int(weapon.get("ATK", weapon.get("WS", 4)))
        strength = int(weapon.get("STR", weapon.get("S", attacker.get("T", 4))))
        ap = int(weapon.get("AP", 0))  # get allowed
        dmg_raw = weapon.get("DMG", 1)
        wound_th_lookup: Dict[int, int] = {}
        for _ in range(int(n_attacks)):
            if attacker_mid not in models_cache:
                break
            target_alive = [m for m in game_state["squad_models"].get(target_sid, []) if m in models_cache]  # get allowed
            if not target_alive:
                break
            summary["attacks_made"] += 1
            hit_roll = random.randint(1, 6)
            if hit_roll == 1 or hit_roll < ws:
                continue
            summary["hits"] += 1
            first_alive = models_cache[target_alive[0]]
            t_target = int(first_alive["T"])
            wth = wound_th_lookup.get(t_target)
            if wth is None:
                wth = wound_threshold(strength, t_target); wound_th_lookup[t_target] = wth
            wound_roll = random.randint(1, 6)
            if wound_roll == 1 or wound_roll < wth:
                continue
            summary["wounds"] += 1
            sv = int(first_alive["ARMOR_SAVE"])
            invul = int(first_alive.get("INVUL_SAVE", 7))
            save_th = save_threshold(sv, invul, ap)
            save_roll = random.randint(1, 6)
            if save_roll != 1 and save_roll >= save_th:
                continue
            summary["failed_saves"] += 1
            try:
                dmg = resolve_dice_value(cast(DiceValue, dmg_raw), f"squad_fight_dmg_{attacker_mid}")
            except Exception:
                dmg = int(dmg_raw) if isinstance(dmg_raw, (int, float)) else 1
            if dmg <= 0:
                continue
            res = _allocate_damage_to_squad(game_state, target_sid, dmg)
            if res is None:
                break
            summary["damage_total"] += int(res["damage_dealt"])
            if res["destroyed"]:
                summary["models_killed"] += 1
            summary["events"].append({
                "attacker": attacker_mid, "target": res["model_id"],
                "target_squad_id": target_sid,
                "target_player": int(res["target_player"]),
                "points_per_hp": float(res["points_per_hp"]),
                "damage": int(res["damage_dealt"]), "destroyed": bool(res["destroyed"]),
            })
        if attacker_mid in models_cache:
            al = int(models_cache[attacker_mid].get("ATTACK_LEFT", 0))  # get allowed
            models_cache[attacker_mid]["ATTACK_LEFT"] = max(0, al - int(n_attacks))
    summary["targets_meta"] = targets_meta
    summary["squads_wiped"] = [
        sid for sid in targets_meta
        if not [m for m in game_state["squad_models"].get(sid, []) if m in models_cache]  # get allowed
    ]
    clear_pending_fight_intent(game_state, attacker_squad_id)
    return summary


def squad_consolidate_plan(
    game_state: Dict[str, Any], squad_id: str
) -> Optional[List[Tuple[str, int, int]]]:
    """Plan Consolidation (apres melee, 3" max par fig).

    Regle officielle (spec §"Consolidation") — OR condition :
      (1) Si possible : finir dans l ER d une unite ennemie ET en coherency.
          Chaque fig doit finir plus proche de l ennemi le plus proche, B2B si possible.
      (2) Sinon : chaque fig peut se deplacer vers l objectif le plus proche, a
          condition que le deplacement mette l escouade a portee de cet objectif
          ET en coherency.
      (3) Sinon : pas de Consolidation.

    PR3 3f MVP : implementation de (1) uniquement (mouvement vers ennemi le plus proche).
    Option (2) "vers objectif" defere a PR3+ (necessite acces aux objectifs en
    game_state + concept "a portee d objectif").

    Retourne plan ou None si impossible. Atomic.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    mids = [m for m in squad_models.get(squad_id, []) if m in models_cache]  # get allowed
    if not mids:
        return None
    units_cache = game_state.get("units_cache", {})  # get allowed
    our_entry = units_cache.get(squad_id)
    if our_entry is None:
        return None
    our_player = int(our_entry.get("player", -1))
    enemy_positions: List[Tuple[int, int]] = []
    enemy_entries: List[Dict[str, Any]] = []
    for esid in _enemy_squad_ids(game_state, our_player):
        enemy_positions.extend(_squad_model_positions(game_state, esid))
        ee = units_cache.get(esid)
        if ee is not None:
            enemy_entries.append(ee)
    if not enemy_positions:
        return None  # plus d ennemi → consolidation (2) seulement, deferree

    ish = int(require_key(game_state, "inches_to_subhex"))
    budget = 3 * ish
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())

    occupied_after: Set[Tuple[int, int]] = set()
    plan: List[Tuple[str, int, int]] = []

    def _cell_legal(c, r):
        if c < 0 or r < 0 or c >= board_cols or r >= board_rows: return False
        if wall_hexes and (c, r) in wall_hexes: return False
        if (c, r) in occupied_after: return False
        for sid, entry in units_cache.items():
            if str(sid) == squad_id: continue
            occ = entry.get("occupied_hexes")
            if occ and (c, r) in occ: return False
        return True

    for mid in mids:
        m = models_cache[mid]
        oc, orow = int(m["col"]), int(m["row"])
        nearest = min(enemy_positions, key=lambda ep: calculate_hex_distance(oc, orow, ep[0], ep[1]))
        tc, tr = nearest
        orig_dist = calculate_hex_distance(oc, orow, tc, tr)
        # B2B preference
        b2b_cands: List[Tuple[int, int, int]] = []
        for ec, er in enemy_positions:
            for nc, nr in get_hex_neighbors(ec, er):
                if not _cell_legal(nc, nr): continue
                d = calculate_hex_distance(oc, orow, nc, nr)
                if d > budget: continue
                b2b_cands.append((d, nc, nr))
        picked: Optional[Tuple[int, int]] = None
        if b2b_cands:
            b2b_cands.sort()
            _, pc, pr = b2b_cands[0]
            picked = (pc, pr)
        else:
            best: Optional[Tuple[int, int, int]] = None
            for d in range(1, budget + 1):
                for d_col in range(-d, d + 1):
                    for d_row in range(-d, d + 1):
                        if max(abs(d_col), abs(d_row)) != d: continue
                        nc, nr = oc + d_col, orow + d_row
                        if not _cell_legal(nc, nr): continue
                        cd = calculate_hex_distance(nc, nr, tc, tr)
                        if cd >= orig_dist: continue
                        if best is None or cd < best[0]:
                            best = (cd, nc, nr)
                if best is not None: break
            if best is not None:
                _, pc, pr = best
                picked = (pc, pr)
        if picked is None:
            picked = (oc, orow)
        plan.append((mid, picked[0], picked[1]))
        occupied_after.add(picked)

    # Validation finale : coherency + ER (au moins 1 fig)
    plan_positions = {mid: (c, r) for mid, c, r in plan}
    if not _validate_plan_coherency(plan_positions, game_state):
        return None
    from engine.spatial_relations import unit_entries_within_engagement_zone
    ez = get_engagement_zone(game_state)
    in_er = any(
        any(
            unit_entries_within_engagement_zone(
                _synth_model_entry(game_state, str(squad_id), models_cache[mid], c, r), ee, ez
            )
            for ee in enemy_entries
        )
        for mid, c, r in plan
    )
    if not in_er:
        return None
    return plan


# ============================================================================
# END-OF-TURN COHERENCY REMOVAL (squad.md PR3 3g)
# ============================================================================


# ============================================================================
# SQUAD ACTION MASK (squad.md PR4 4b — pipeline parallele decoder)
# ============================================================================
# 16 micro-actions :
#   0-5  : Normal move direction D (cf. get_hex_neighbors, parity-aware)
#   6    : Advance (direction depuis macro_intent)
#   7    : Fall Back (direction auto)
#   8    : wait / end activation
#   9-13 : shoot slots 0-4
#   14   : charge (vers cible macro_intent)
#   15   : fight (Pile In + declare + resolve + Consolidation)
#
# Returns np-compatible list[int] de longueur 16, valeurs ∈ {0, 1}.


SQUAD_ACTION_SIZE = 26
SQUAD_ACTION_MOVE_DIR_BASE = 0
SQUAD_ACTION_MOVE_DIR_COUNT = 6
# PR4 4e-v_a : Advance et Fall Back ont chacun 6 directions (agent decide, aucune valeur par défaut)
SQUAD_ACTION_ADVANCE_DIR_BASE = 6
SQUAD_ACTION_ADVANCE_DIR_COUNT = 6
SQUAD_ACTION_FALL_BACK_DIR_BASE = 12
SQUAD_ACTION_FALL_BACK_DIR_COUNT = 6
SQUAD_ACTION_WAIT = 18
SQUAD_ACTION_SHOOT_SLOT_BASE = 19
SQUAD_ACTION_SHOOT_SLOT_COUNT = 5
SQUAD_ACTION_CHARGE = 24
SQUAD_ACTION_FIGHT = 25


def _squad_is_in_enemy_er(game_state: Dict[str, Any], squad_id: str) -> bool:
    """True si AU MOINS UNE figurine du squad est dans l ER (bord-a-bord) d une fig ennemie.

    Delegue a la primitive canonique d engagement (unit_within_engagement_zone_footprints :
    empreintes multi-fig + socles ronds euclidien), exactement comme les handlers
    shoot/fight/charge unit-level. Remplace l ancienne mesure centre-a-centre qui
    sous-detectait l engagement pour des bases ecartees (regle 03.04 : 2" entre figurines)."""
    from engine.spatial_relations import unit_within_engagement_zone_footprints
    units_cache = game_state.get("units_cache", {})  # get allowed
    entry = units_cache.get(str(squad_id))
    if entry is None:
        return False
    ez = get_engagement_zone(game_state)
    stub = {"id": str(squad_id), "player": int(entry.get("player", -1))}
    return unit_within_engagement_zone_footprints(game_state, stub, ez, max_distance=ez)


def _squad_direction_move_legal(
    game_state: Dict[str, Any],
    squad_id: str,
    direction_idx: int,
    move_type: str,
    advance_roll: Optional[int] = None,
) -> bool:
    """Dry-run : verifie qu un mouvement de l ancre dans la direction `direction_idx`
    produit un plan rigide valide.

    direction_idx : 0..5, index dans get_hex_neighbors (parity-aware).
    move_type : "normal" / "advance" / "fall_back".
    advance_roll : pour move_type="advance", D6 roll partage (caller doit fournir).

    Aucune ecriture cache. Returns True si le plan rigide est valide
    (bounds + walls + collisions + ER ennemi + budget + coherency).
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive_mids = [m for m in squad_models.get(squad_id, []) if m in models_cache]  # get allowed
    if not alive_mids:
        return False
    anchor = models_cache[alive_mids[0]]
    anchor_col, anchor_row = int(anchor["col"]), int(anchor["row"])
    neighbors = get_hex_neighbors(anchor_col, anchor_row)
    if not (0 <= direction_idx < len(neighbors)):
        return False
    dest_col, dest_row = neighbors[direction_idx]
    plan = build_rigid_plan(dest_col, dest_row, squad_id, game_state)
    if plan is None:
        return False
    budget = get_squad_move_budget(squad_id, game_state, move_type, advance_roll=advance_roll)
    constraints = {"budget_per_model": budget}
    return validate_move_plan(plan, game_state, constraints)


def build_squad_action_mask(
    game_state: Dict[str, Any],
    squad_id: str,
    enemy_slot_ids: Optional[List[Optional[str]]] = None,
    advance_roll: Optional[int] = None,
) -> List[int]:
    """Construit le masque 26 actions pour une escouade active (PR4 4e-v_a).

    Decision utilisateur : agent decide direction Advance/Fall Back. Per-direction
    dry-run validation : chaque direction est mask=1 SEULEMENT si le plan rigide
    correspondant est valide (aucune valeur par défaut).

    Phase courante lue depuis game_state['phase']. Si squad absent/mort, mask all-zero.

    enemy_slot_ids : mapping slot 0..4 → squad_id ennemi (ou None). Defaut : 1ers 5
    enemy squads tries par str(sid) (PR4 4a coherence ; PR4 4d stable mapping disponible
    via get_enemy_slot_mapping).

    advance_roll : pour le mask des actions Advance (6-11), caller doit fournir le
    roll D6 partage. Si None, mask Advance fully a 0 (impossible de savoir le budget).
    """
    mask = [0] * SQUAD_ACTION_SIZE
    units_cache = game_state.get("units_cache", {})  # get allowed
    if squad_id not in units_cache:
        return mask
    entry = units_cache[squad_id]
    our_player = int(entry.get("player", -1))
    phase = str(game_state.get("phase", "")).lower()
    in_er = _squad_is_in_enemy_er(game_state, squad_id)
    has_advanced = squad_id in game_state.get("units_advanced", set())
    has_fled = squad_id in game_state.get("units_fled", set())
    has_moved = squad_id in game_state.get("units_moved", set())
    has_shot = squad_id in game_state.get("units_shot", set())
    has_fought = squad_id in game_state.get("units_fought", set())

    if enemy_slot_ids is None:
        enemy_sorted = sorted(
            (sid for sid, e in units_cache.items() if int(e["player"]) != our_player),
            key=lambda s: str(s),
        )
        enemy_slot_ids = list(enemy_sorted[:SQUAD_ACTION_SHOOT_SLOT_COUNT]) + [None] * max(
            0, SQUAD_ACTION_SHOOT_SLOT_COUNT - len(enemy_sorted)
        )

    # --- Move phase: directions Normal (0-5), Advance (6-11), Fall Back (12-17) ---
    if phase == "move":
        if not has_moved:
            # Normal move : interdit si in ER (locked). Per-direction dry-run.
            if not in_er:
                for d in range(SQUAD_ACTION_MOVE_DIR_COUNT):
                    if _squad_direction_move_legal(game_state, squad_id, d, "normal"):
                        mask[SQUAD_ACTION_MOVE_DIR_BASE + d] = 1
                # Advance : per-direction validation avec roll partage.
                # Si advance_roll=None : impossible d evaluer le budget, mask 0.
                if advance_roll is not None and not has_advanced and not has_fled:
                    for d in range(SQUAD_ACTION_ADVANCE_DIR_COUNT):
                        if _squad_direction_move_legal(
                            game_state, squad_id, d, "advance", advance_roll=advance_roll
                        ):
                            mask[SQUAD_ACTION_ADVANCE_DIR_BASE + d] = 1
            # Fall Back : uniquement si in ER ennemi. Per-direction dry-run.
            if in_er and not has_advanced and not has_fled:
                for d in range(SQUAD_ACTION_FALL_BACK_DIR_COUNT):
                    if _squad_direction_move_legal(game_state, squad_id, d, "fall_back"):
                        mask[SQUAD_ACTION_FALL_BACK_DIR_BASE + d] = 1
        mask[SQUAD_ACTION_WAIT] = 1

    # --- Shoot phase: shoot slots 19-23 ---
    elif phase == "shoot":
        can_shoot = not has_fled and not has_advanced and not has_shot and not in_er
        if can_shoot:
            for slot_i, esid in enumerate(enemy_slot_ids):
                if esid is None or esid not in units_cache:
                    continue
                # Ennemi verrouille par un allie (bord-a-bord) => pas ciblable au tir.
                from engine.spatial_relations import unit_entries_within_engagement_zone
                ez = get_engagement_zone(game_state)
                enemy_entry = units_cache.get(esid)
                locked_by_ally = False
                if enemy_entry is not None:
                    for sid, e in units_cache.items():
                        if int(e["player"]) != our_player or str(sid) == squad_id:
                            continue
                        if unit_entries_within_engagement_zone(enemy_entry, e, ez):
                            locked_by_ally = True
                            break
                if locked_by_ally:
                    continue
                models_cache = game_state.get("models_cache", {})  # get allowed
                can_any_hit = False
                for mid in game_state.get("squad_models", {}).get(squad_id, []):  # get allowed
                    m = models_cache.get(mid)
                    if m is None:
                        continue
                    if _model_can_shoot_target(game_state, m, esid):
                        can_any_hit = True
                        break
                if can_any_hit:
                    mask[SQUAD_ACTION_SHOOT_SLOT_BASE + slot_i] = 1
        mask[SQUAD_ACTION_WAIT] = 1

    # --- Charge phase: action 24 ---
    elif phase == "charge":
        any_charge_possible = False
        for esid in enemy_slot_ids:
            if esid is None:
                continue
            if charge_check_eligibility(game_state, squad_id, [esid]):
                any_charge_possible = True
                break
        if any_charge_possible:
            mask[SQUAD_ACTION_CHARGE] = 1
        mask[SQUAD_ACTION_WAIT] = 1

    # --- Fight phase: action 25 ---
    elif phase == "fight":
        eligible = _squad_is_in_fight(game_state, squad_id)
        if eligible and not has_fought:
            mask[SQUAD_ACTION_FIGHT] = 1
        if not eligible:
            mask[SQUAD_ACTION_WAIT] = 1

    # --- Other phases (command/deployment) ---
    else:
        mask[SQUAD_ACTION_WAIT] = 1

    return mask


# ============================================================================
# STABLE ENEMY SLOT MAPPING (squad.md PR4 4d)
# ============================================================================
# Mapping fixe a l init de partie : top-5 escouades ennemies par menace
# (HP_total * OC_total). Tie-break = ordre d index (deterministe).
# Apres init, le mapping NE CHANGE JAMAIS. Si une escouade slot meurt, son
# slot reste vide (masque=0). La 6eme escouade n est PAS promue.


def init_enemy_slot_mapping(game_state: Dict[str, Any], our_player: int) -> None:
    """Construit le mapping stable a l init de partie. Idempotent.

    Cle stockee : game_state[f"enemy_slot_mapping_p{our_player}"] = [sid_or_None, ...]
    Liste de 5 entrees, chaque slot = squad_id ennemi ou None si moins de 5 ennemis.

    A appeler UNE SEULE FOIS au debut de partie. Si la cle existe deja → no-op
    (preserve mapping initial même si squad meurt).
    """
    cache_key = f"enemy_slot_mapping_p{int(our_player)}"
    if cache_key in game_state:
        return
    units_cache = game_state.get("units_cache", {})  # get allowed
    squad_models = game_state.get("squad_models", {})  # get allowed
    models_cache = game_state.get("models_cache", {})  # get allowed
    # Calcule (squad_id, threat) pour chaque ennemi vivant a l init
    candidates: List[Tuple[str, float, int]] = []  # (sid, threat, idx)
    enemy_sorted = sorted(
        (sid for sid, e in units_cache.items() if int(e["player"]) != int(our_player)),
        key=lambda s: str(s),
    )
    for idx, sid in enumerate(enemy_sorted):
        entry = units_cache[sid]
        hp_total = int(entry.get("HP_CUR", 0))  # get allowed
        # OC_total : prefer cache value, calcul de secours
        oc_total = int(entry.get("OC_TOTAL", 0))  # get allowed
        if oc_total == 0:
            for mid in squad_models.get(sid, []):  # get allowed
                m = models_cache.get(mid)
                if m is not None:
                    oc_total += int(m.get("OC", 0))  # get allowed
        threat = float(hp_total) * float(oc_total)
        candidates.append((str(sid), threat, idx))
    # Tri : menace decroissante, tie-break index croissant (ordre creation)
    candidates.sort(key=lambda t: (-t[1], t[2]))
    slot_count = SQUAD_ACTION_SHOOT_SLOT_COUNT
    mapping: List[Optional[str]] = [None] * slot_count
    for slot_i in range(min(slot_count, len(candidates))):
        mapping[slot_i] = candidates[slot_i][0]
    game_state[cache_key] = mapping


def get_enemy_slot_mapping(
    game_state: Dict[str, Any], our_player: int
) -> List[Optional[str]]:
    """Retourne le mapping fige. Si squad d un slot est mort, retourne None pour ce slot.

    Si le mapping n a jamais ete initialise, le construit (init lazy).
    """
    cache_key = f"enemy_slot_mapping_p{int(our_player)}"
    if cache_key not in game_state:
        init_enemy_slot_mapping(game_state, our_player)
    raw = game_state.get(cache_key, [None] * SQUAD_ACTION_SHOOT_SLOT_COUNT)
    units_cache = game_state.get("units_cache", {})  # get allowed
    return [sid if (sid is not None and sid in units_cache) else None for sid in raw]


def end_of_turn_coherency_removal(
    game_state: Dict[str, Any], squad_id: str
) -> List[str]:
    """Retrait deterministe des figurines hors coherency (MVP PR3).

    Boucle :
      - Si squad coherent OU model_count <= 1 → stop.
      - Sinon : retire la figurine la plus eloignee du centroide geometrique.
        Tie-break : index croissant. Utilise destroy_model(reason='coherency_removal').
      - Recalcule coherency apres chaque retrait.

    Returns liste des model_ids retires (ordre de retrait).

    Note : la fig retiree par 'coherency_removal' ne genere ni reward kill ni perte
    d OC pour le combat (cf. spec §"Cascade de mise a jour" — reason discrimine).
    """
    removed: List[str] = []
    while True:
        models_cache = game_state.get("models_cache", {})  # get allowed
        squad_models = game_state.get("squad_models", {}).get(squad_id, [])  # get allowed
        alive = [m for m in squad_models if m in models_cache]
        if len(alive) <= 1:
            break
        if validate_squad_coherency(game_state, squad_id):
            break
        # Calcule centroide
        positions = [(int(models_cache[m]["col"]), int(models_cache[m]["row"])) for m in alive]
        cx = sum(p[0] for p in positions) / float(len(positions))
        cy = sum(p[1] for p in positions) / float(len(positions))
        # B1 cleanup (audit) : pre-calcule l index pour O(1) lookup vs alive.index O(n)
        index_of = {mid: i for i, mid in enumerate(alive)}
        # Fig la plus eloignee (distance euclidienne carree, evite sqrt)
        def _sq_dist(mid: str) -> float:
            m = models_cache[mid]
            dx = int(m["col"]) - cx
            dy = int(m["row"]) - cy
            return dx * dx + dy * dy
        # Sort by (-dist, index) — distance max d abord, puis index croissant pour tie-break
        sorted_alive = sorted(alive, key=lambda mid: (-_sq_dist(mid), index_of[mid]))
        target_mid = sorted_alive[0]
        destroy_model(game_state, target_mid, reason="coherency_removal")
        removed.append(target_mid)
    return removed
