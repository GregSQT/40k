#!/usr/bin/env python3
"""
engine/phase_handlers/shared_utils.py - Shared utility functions for phase handlers
Functions used across multiple phase handlers to avoid duplication.
"""

from typing import AbstractSet, Dict, Iterator, List, Tuple, Set, Optional, Any, Union, Callable, Sequence, Mapping, cast, TYPE_CHECKING
from dataclasses import dataclass
import copy
import inspect
import time

if TYPE_CHECKING:
    from engine.hex_utils import Socle
    from engine.phase_handlers.attack_sequence import WeaponAttackProfile

from shared.data_validation import ConfigurationError, require_key, HAZARD_CONTEXT_DESPERATE_ESCAPE
from engine.utils.weapon_helpers import (
    melee_weapons,
    ranged_weapons,
    weapon_has_rule,
    weapon_rule_signature,
)

# --- Type de plan de mouvement (source unique) ---------------------------------
# Une entrée positionne UNE figurine : (model_id, col, row, level) OU
# (model_id, col, row, level, orientation). Le 4e élément (niveau/étage de destination) est
# OBLIGATOIRE et non nul-able — un plan muet est refusé à la frontière de décodage
# (``parse_model_plan``), jamais complété par un niveau inventé. Le 5e (orientation socle 0..11)
# reste optionnel ; None = « orientation inchangée ».
# Paramètres typés en ``Sequence`` (covariant) pour accepter indifféremment les listes de
# 4- ou 5-uplets produites par les phases move/charge/fight.
MovePlanEntry = Union[
    Tuple[str, int, int, int],
    Tuple[str, int, int, int, Optional[int]],
]
MovePlan = Sequence[MovePlanEntry]


from engine.action_log_utils import append_action_log, models_segment_for_unit
# `spatial_grid` ne depend que de `hex_utils` -> import direct sans cycle (il importe
# `get_squad_move_budget` en local dans sa seule fonction qui en a besoin).
from engine.spatial_grid import GRID_CELL_COUNT
# `observation_entities` est une FEUILLE (aucun import moteur) : l'importer au niveau module ne
# cree pas de cycle. `K_ALLY_SLOTS` y vit parce que l'espace d'action en derive (V11 §0.48 L2).
from engine.observation_entities import K_ALLY_SLOTS, MAX_DECISION_OPTIONS, K_WEAPONS_MELEE, K_WEAPONS_RANGED
from engine.agent_decision import set_pending_agent_decision
# Primitives « hors table » : définies dans la couche BASSE (`spatial_relations` ne dépend que de
# `hex_utils`) parce que les primitives de MESURE en dépendent elles-mêmes. Ré-exportées ici, où
# une trentaine d'appelants importent déjà `entry_is_on_battlefield` — même symbole, pas un jumeau.
from engine.spatial_relations import (  # noqa: F401  (ré-export)
    enemy_entries_on_battlefield,
    entries_on_battlefield,
    entry_footprint,
    entry_is_on_battlefield,
    require_entry_on_battlefield,
    unit_entries_within_engagement_zone,
)
from engine.combat_utils import (
    get_unit_coordinates,
    normalize_coordinates,
    calculate_hex_distance,
    get_hex_neighbors,
    expected_dice_value,
    resolve_dice_value,
    get_unit_by_id,
    require_unit_by_id,
    set_unit_coordinates,
)
# Bascule UNIQUE de la résolution (`inches_to_subhex <= 1` → géométrie hex). Import de MODULE :
# `_compute_unit_occupied_hexes` la consulte dans des boucles chaudes (empreintes, masques), et un
# import local y coûterait un lookup `sys.modules` par appel. `spatial_relations` n'importe rien de
# ce module au niveau global → aucun cycle.
from engine.spatial_relations import geometry_is_hex
from engine.mask_verification import verify_memoised_move_cell_map

# end_activation / _handle_shooting_end_activation argument constants (tour_de_jeu.md)
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


def plan_entry_level(entry: Sequence[Any]) -> int:
    """Étage VISÉ par la figurine — 4e élément, TOUJOURS présent (frontière de décodage).

    Le déduire du ``models_cache`` validerait un move vers l'étage contre l'occupation du sol.
    """
    return int(entry[3])


def plan_entry_orientation(entry: Sequence[Any]) -> Optional[int]:
    """Orientation de socle VISÉE — 5e élément, OPTIONNEL (``None`` = inchangée).

    SOURCE UNIQUE de la lecture du 5e élément : le pool par-figurine, la validation du plan et
    le commit doivent lire la MÊME orientation provisoire (un passage étroit ne s'ouvre que
    dans une orientation, sur socle non rond), et une entrée à 4 éléments reste légitime.
    """
    return int(entry[4]) if len(entry) >= 5 and entry[4] is not None else None


def plan_entry_model_orientation(entry: Sequence[Any], model: Dict[str, Any]) -> int:
    """Orientation EFFECTIVE d'une figurine pour ce plan — 5e élément, sinon celle du cache.

    SOURCE UNIQUE de la RÉSOLUTION du ``None`` rendu par `plan_entry_orientation`. Le pool, la
    validation, la mesure du trajet et le commit doivent tous trancher « orientation visée ou
    orientation courante » de la MÊME façon : quatre copies de cette règle, c'est le motif de
    divergence de miroir habituel — un socle non rond validé pivoté puis mesuré non pivoté.
    ``models_cache`` pose toujours ``orientation`` (`build_models_cache`), donc son absence est
    un cache corrompu et lève.
    """
    _ori = plan_entry_orientation(entry)
    return _ori if _ori is not None else int(require_key(model, "orientation"))


def plan_entry_model(entry: Sequence[Any], model: Dict[str, Any]) -> Dict[str, Any]:
    """La figurine telle que ce plan la VISE : même entrée de cache, orientation résolue.

    Forme attendue par tout ce qui reconstruit une empreinte orientée (champ any-angle,
    empreinte de cohérence). Copie superficielle : le cache n'est jamais muté par une lecture.
    """
    return {**model, "orientation": plan_entry_model_orientation(entry, model)}


@dataclass(frozen=True)
class ManualAllocCtx:
    """Parametrage du moteur d allocation manuelle des pertes (regles 05.03 / 05.04).

    Mutualise UNIQUEMENT la couche allocation des pertes (groupes, ordre, selection
    de figurine, save check, application des degats). La resolution des jets reste
    specifique a chaque phase (cf. Documentation/Reference/moteur/allocation_attaques.md).
    """
    alloc_key: str            # cle game_state de l allocation pending
    declare_order_action: str # action des payloads de declaration d ordre
    manual_alloc_action: str  # action des payloads de choix de figurine
    phase_label: str          # champ "phase" des payloads et logs
    log_type: str             # champ "type" de l action_log
    log_verb: str             # verbe du message de log (ex. "SHOT")
    attacks_left_attr: str    # attribut figurine decremente par intent (SHOOT_LEFT / ATTACK_LEFT)
    intents_key: str          # cle game_state des intents (pending_squad_*_intents)
    # Cle figurine des armes de la phase (RNG_WEAPONS / CC_WEAPONS) : sert au comptage des
    # armes [HAZARDOUS] selectionnees (24.15). Vide pour le mode mortal (hazard : pas d arme).
    weapons_key: str = ""
    # Origine des jets de hasard declenches en fin d activation ([HAZARDOUS] 24.15) : sert a
    # la reprise du flux apres allocation manuelle des blessures mortelles (w40k_core).
    hazard_origin: str = ""
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
    # Decideur auto (defenseur non-humain) : si fourni et renvoie True pour la cible du lot,
    # le moteur tranche lui-meme l ordre des groupes (05.04) et le choix de figurine au lieu
    # de rendre la main (headless). None = toujours manuel (comportement tir historique).
    auto_decider: Optional[Callable[[Dict[str, Any], str], bool]] = None


def is_programmatic_owner(game_state: Dict[str, Any], player: Any) -> bool:
    """SOURCE UNIQUE du predicat "ce joueur est pilote par la machine (auto-resolution
    d allocation/resolution, sans rendre la main a un humain)".

    True en training gym (`gym_training_mode` : self-play, player_types = human/human mais
    aucun humain reel) ; sinon comportement historique player_types == 'ai' (PvP/PvE).
    Aucun repli silencieux : player_types manquant hors gym = bug -> erreur explicite.

    ⚠️ N est branche QUE sur les decisions d ALLOCATION/resolution (05.03/05.04, hazard
    manuel), jamais sur le CHOIX de l escouade a activer (cf. R4). Ce choix appartient a l agent
    depuis V11 §0.48 L2 (`ACTIVATE_SLOT`) ; les auto-activations qui le precedaient — dont
    `active_shooting_unit` epingle sur la tete du pool — sont supprimees depuis le 2026-08-08."""
    if game_state.get("gym_training_mode"):
        return True
    player_types = require_key(game_state, "player_types")
    p = str(player)
    if p not in player_types:
        raise KeyError(f"is_programmatic_owner: player {p!r} absent de player_types")
    return player_types[p] == "ai"


def is_programmatic_defender(game_state: Dict[str, Any], target_sid: str) -> bool:
    """Le defenseur de la cible est-il pilote par la machine ? Resout le proprietaire de
    la cible puis delegue a is_programmatic_owner (source unique). Cible manquante = bug."""
    units_cache = require_key(game_state, "units_cache")
    sid = str(target_sid)
    if sid not in units_cache:
        raise KeyError(f"is_programmatic_defender: cible {sid!r} absente de units_cache")
    player = require_key(units_cache[sid], "player")
    return is_programmatic_owner(game_state, player)


def _target_defender_is_ai(game_state: Dict[str, Any], target_sid: str) -> bool:
    """Decideur auto generique du moteur d allocation tir (SHOOT_CTX). Delegue a la source
    unique is_programmatic_defender."""
    return is_programmatic_defender(game_state, target_sid)


SHOOT_CTX = ManualAllocCtx(
    alloc_key="pending_shoot_allocation",
    declare_order_action="squad_shoot_declare_order",
    manual_alloc_action="squad_shoot_manual_alloc",
    phase_label="shoot",
    log_type="shoot",
    log_verb="SHOT",
    attacks_left_attr="SHOOT_LEFT",
    intents_key="pending_squad_shoot_intents",
    weapons_key="RNG_WEAPONS",
    hazard_origin="shoot",
    auto_decider=_target_defender_is_ai,
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

def socle_orientation(socle: Mapping[str, Any]) -> int:
    """Orientation (0..N-1) d'un socle — CONVENTION UNIQUE, absente = 0 (face nord).

    Ce n'est pas un défaut anti-erreur : l'orientation est un champ OPTIONNEL de la datasheet
    (une escouade sans pivot n'en porte pas), et 0 en est la valeur métier. Ce qui compte est que
    l'empreinte (`_compute_unit_occupied_hexes`) et le volet mur du placement
    (`wall_blocked_anchors`) la lisent EXACTEMENT pareil : deux conventions donneraient deux
    géométries pour le même socle, ce que ce chantier existe pour supprimer.
    """
    if "orientation" in socle:
        return int(require_key(socle, "orientation"))
    return 0


def _compute_unit_occupied_hexes(
    col: int, row: int, unit: Dict[str, Any],
    game_state: Optional[Dict[str, Any]] = None,
) -> Set[Tuple[int, int]]:
    """Compute occupied_hexes for a unit based on its BASE_SHAPE and BASE_SIZE.

    Empreinte multi-hex uniquement au-dessus de ``inches_to_subhex == 1``. À x1, UNE figurine tient
    dans UNE case quelle que soit la taille de son socle — c'est la définition de cette résolution
    (``game_state._scale_socle`` y normalise déjà le socle en ``round``/1) et le point de bascule
    unique ``spatial_relations.geometry_is_hex`` en est le seul juge.

    ⚠️ La garde était ``ez <= 1``, un PROXY de « board x1 » devenu faux le 2026-06-03 quand
    ``game_rules.engagement_zone`` est passé de 1" à 2" (à x1, ``ez = 2``). Elle ne se déclenchait
    plus, et seule la clause ``base_size == 1`` la remplaçait — par chance, la normalisation du
    socle la rend vraie à x1.
    """
    # HORS TABLE (sentinelle (-1,-1)) : aucune empreinte. Une unité en attente de déploiement ou
    # en réserves stratégiques (20.01) n'occupe aucune case — lui laisser l'empreinte fictive de
    # la sentinelle la faisait déborder sur le coin (0,0) du plateau (socle multi-hex), donc
    # bloquer une case réelle et polluer l'occupation, les zones d'engagement et les distances
    # d'empreinte pendant toute la bataille. `occupied_hexes` vide est la traduction directe de
    # « pas sur le champ de bataille » (cf. `entry_is_on_battlefield`).
    if col < 0 or row < 0:
        return set()
    if game_state is None:
        return {(col, row)}
    if geometry_is_hex(game_state):
        return {(col, row)}
    base_shape = unit["BASE_SHAPE"]
    base_size = unit["BASE_SIZE"]
    orientation = socle_orientation(unit)
    if base_size == 1:
        return {(col, row)}
    from engine.hex_utils import compute_occupied_hexes
    return compute_occupied_hexes(col, row, base_shape, base_size, orientation)


def _occupied_hexes_at_level(
    game_state: Dict[str, Any], level: int, skip: "Any",
) -> Set[Tuple[int, int]]:
    """Empreintes par-figurine des unités vivantes situées AU NIVEAU ``level`` (étages).

    ``skip(uid, entry) -> bool`` filtre les unités (exclusion / camp). Source par-figurine
    (``models_cache`` + niveau) car ``occupied_hexes`` du units_cache est l'union tous niveaux.
    """
    units_cache = require_key(game_state, "units_cache")
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    occupied: Set[Tuple[int, int]] = set()
    for uid, entry in entries_on_battlefield(units_cache):
        if skip(uid, entry):
            continue
        for mid in squad_models.get(str(uid), []):  # get allowed
            m = models_cache.get(mid)
            if m is None or int(require_key(m, "level")) != level:
                continue
            occupied |= compute_candidate_footprint(int(m["col"]), int(m["row"]), m, game_state)
    return occupied


def build_occupied_positions_set(
    game_state: Dict[str, Any],
    exclude_unit_id: Optional[str] = None,
    level: Optional[int] = None,
) -> Set[Tuple[int, int]]:
    """Build set of all cells occupied by living units (full footprints).

    Uses occupied_hexes from units_cache for multi-hex units.
    For single-hex units, equivalent to {(col, row)} per unit.

    Args:
        game_state: Game state with units_cache
        exclude_unit_id: Optional unit to exclude (e.g. the moving unit)
        level: None = toutes figs confondues (comportement historique). Un entier restreint
            aux figurines de ce niveau (mouvement vertical : deux figs à des étages différents
            ne se gênent pas — murs verticaux prolongés gérés séparément, cf. verticalite.md).

    Returns:
        Set of (col, row) cells occupied by other units
    """
    if level is not None:
        return _occupied_hexes_at_level(
            game_state, level, skip=lambda uid, entry: uid == exclude_unit_id
        )
    units_cache = require_key(game_state, "units_cache")
    occupied: Set[Tuple[int, int]] = set()
    for _uid, entry in entries_on_battlefield(units_cache, exclude_id=exclude_unit_id):
        occupied.update(entry_footprint(entry))
    return occupied


def build_enemy_occupied_positions_set(
    game_state: Dict[str, Any],
    *,
    current_player: int,
    level: Optional[int] = None,
) -> Set[Tuple[int, int]]:
    """Cells occupied by opposing players' units (full footprints).

    ``level`` : None = tous niveaux (historique) ; un entier restreint au niveau donné.
    """
    current_player_int = int(current_player)
    if level is not None:
        return _occupied_hexes_at_level(
            game_state, level,
            skip=lambda uid, entry: int(require_key(entry, "player")) == current_player_int,
        )
    units_cache = require_key(game_state, "units_cache")
    occupied: Set[Tuple[int, int]] = set()
    for _uid, entry in enemy_entries_on_battlefield(units_cache, current_player_int):
        occupied.update(entry_footprint(entry))
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


def wall_blocked_anchors(
    game_state: Dict[str, Any], socle: Mapping[str, Any]
) -> AbstractSet[Tuple[int, int]]:
    """Ancres où le socle chevaucherait un MUR — source unique du volet « mur » du placement.

    Mémoïsé par ``(forme, taille, orientation)`` dans ``game_state``. Les murs sont STATIQUES
    pendant une partie (même doctrine que ``_move_spatial_cache``, qui les exclut de son
    fingerprint pour cette raison) ; ils ne changent qu'à la ROTATION DE SCÉNARIO, où
    ``w40k_core`` jette ce cache avec les autres dérivés statiques (jumeau de ``_wall_set_cache``).
    L'orientation est normalisée à 0 pour un socle rond : un disque n'en a pas, et six entrées
    identiques coûteraient six dilatations pour un seul ensemble.
    """
    from engine.hex_utils import base_size_cache_key, socle_blocked_anchor_cells
    from engine.spatial_relations import geometry_is_hex

    # x1 (`geometry_is_hex`) : une figurine tient dans UNE case par définition de la résolution, et
    # rien n'y mesure de distance continue — ni le pool, ni la traversée. Il n'y a donc AUCUN écart
    # à corriger, et dilater un « disque » de rayon 0,75 y interdirait tous les voisins d'un mur.
    if geometry_is_hex(game_state):
        return game_state.get("wall_hexes", set())  # get allowed (carte sans mur)

    shape = str(require_key(socle, "BASE_SHAPE"))
    base = require_key(socle, "BASE_SIZE")
    orient = 0 if shape == "round" else socle_orientation(socle)
    key = (shape, base_size_cache_key(base), orient)
    cache: Dict[Any, Set[Tuple[int, int]]] = game_state.setdefault("_socle_wall_blocked_cache", {})
    hit = cache.get(key)  # get allowed (mémoïsation)
    if hit is None:
        hit = socle_blocked_anchor_cells(
            game_state.get("wall_hexes", set()), shape, base, orient,  # get allowed (carte sans mur)
            int(require_key(game_state, "board_cols")), int(require_key(game_state, "board_rows")),
        )
        cache[key] = hit
    return hit


def is_footprint_placement_valid(
    candidate_hexes: Set[Tuple[int, int]],
    game_state: Dict[str, Any],
    occupied_positions: Set[Tuple[int, int]],
    enemy_adjacent_hexes: Optional[Set[Tuple[int, int]]] = None,
    *,
    anchor: Tuple[int, int],
    socle: Mapping[str, Any],
) -> bool:
    """Check if all cells of a candidate footprint are valid for placement.

    Validates: within board bounds, not a wall, not occupied by another unit.
    Optionally checks that no cell falls within the enemy engagement zone.

    ``anchor``/``socle`` sont OBLIGATOIRES et nommés : le volet « mur » ne se mesure plus sur
    l'empreinte hex (un mur y comptait pour son CENTRE) mais sur la géométrie d'hexagone, la
    même que la traversée — cf. ``hex_utils.socle_blocked_anchor_cells``. Les rendre optionnels
    laisserait un site retomber en silence sur l'ancien critère, qui produit des positions d'où
    aucun mouvement n'est possible ; ils sont donc requis, et l'oubli est une erreur de typage.

    Args:
        candidate_hexes: Set of (col, row) for the candidate footprint
        game_state: With board_cols, board_rows, wall_hexes
        occupied_positions: Pre-computed set of occupied cells
        enemy_adjacent_hexes: If provided, also blocks cells in enemy engagement zone
        anchor: (col, row) de l'ancre dont ``candidate_hexes`` est l'empreinte
        socle: mapping portant BASE_SHAPE / BASE_SIZE (+ orientation pour les socles non ronds)

    Returns:
        True if ALL cells pass every check
    """
    if not candidate_hexes:
        return False
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    # Bounds check (must iterate — no way to vectorize without numpy)
    for c, r in candidate_hexes:
        if c < 0 or r < 0 or c >= board_cols or r >= board_rows:
            return False
    if anchor in wall_blocked_anchors(game_state, socle):
        return False
    # Set-intersection checks are implemented in C and much faster than Python loops
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
    for _uid, entry in entries_on_battlefield(units_cache, exclude_id=exclude_unit_id):
        e_col = require_key(entry, "col")
        e_row = require_key(entry, "row")
        e_fp = set(entry_footprint(entry))
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
    orientation: int,
    exclude_unit_id: Optional[str] = None,
    enemy_adjacent_hexes: Optional[Set[Tuple[int, int]]] = None,
) -> bool:
    """Placement légal = bornes + murs ET aucun chevauchement de socle.

    Le volet bornes/murs reste ``is_footprint_placement_valid`` (avec ``occupied_positions``
    vide : le chevauchement n'est plus testé par cellules ici). Le chevauchement entre unités
    passe par ``candidate_overlaps_any_unit`` (clearance continu rond↔rond, méthode empreinte).
    Remplace 1:1 le couple ``build_occupied_positions_set`` + ``is_footprint_placement_valid``.
    """
    if not is_footprint_placement_valid(
        candidate_fp, game_state, set(), enemy_adjacent_hexes,
        anchor=(int(col), int(row)),
        socle={"BASE_SHAPE": shape, "BASE_SIZE": base_size, "orientation": int(orientation)},
    ):
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


def strip_role_rules(unit_rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Regles d unite privees des marqueurs de ROLE (cf. ROLE_TIER).

    Les roles sont des marqueurs PAR FIGURINE (ordre d allocation 05.03/05.04, T bodyguard
    19.02) : ils ne doivent JAMAIS remonter au niveau escouade par l union 19.04, sinon
    `_derive_model_role` verrait "leader" sur toutes les figurines de base du squad.
    """
    return [
        r for r in unit_rules
        if not (isinstance(r, dict) and r.get("ruleId") in ROLE_TIER)
    ]


def compute_unit_rules_in_effect(
    own_rules: List[Dict[str, Any]],
    attached_rule_groups: Dict[str, List[Dict[str, Any]]],
    *,
    native_alive: bool,
    alive_attached_sources: Set[str],
) -> List[Dict[str, Any]]:
    """Regles d unite EN VIGUEUR sur une unite (potentiellement attachee) — regle 19.04.

    PDF 19.04 « Abilities in attached units » : les regles qui affectent une unite (ou ses
    figurines) s appliquent a CHAQUE figurine de l unite attachee, jusqu a ce que leur source
    soit detruite. Le tableau du PDF donne deux sources ici :
      - « Bodyguard unit » -> jusqu a la mort de la DERNIERE figurine du bodyguard ;
      - « Leader/support unit » -> jusqu a la mort de la DERNIERE figurine de CE leader/support
        (note du PDF : le leader garde ses propres regles meme si son bodyguard est detruit).

    `own_rules` = bloc bodyguard (regles de l unit_type de l escouade + regles propres de ses
    figurines natives), immuable, calcule au build. `attached_rule_groups` = {id de l unite
    character repliee -> ses regles}, immuable lui aussi. Ce qui varie est le VIVANT :
    `native_alive` et `alive_attached_sources`.

    Union ordonnee, dedupliquee sur ruleId : bodyguard d abord (l ordre de declaration reste
    celui du datasheet de l escouade), puis les groupes attaches dans l ordre du fold.
    """
    in_effect: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    def _add(rules: List[Dict[str, Any]]) -> None:
        for rule in rules:
            rule_id = str(require_key(rule, "ruleId"))
            if rule_id in seen:
                continue
            seen.add(rule_id)
            in_effect.append(copy.deepcopy(rule))

    if native_alive:
        _add(own_rules)
    for source_id, rules in attached_rule_groups.items():
        if str(source_id) in alive_attached_sources:
            _add(rules)
    return in_effect


def _attack_allocation_in_progress(game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Allocation d ATTAQUE en cours (tir ou combat), ou None.

    Sert la fenetre 19.04 « until the attacking unit has resolved all of its attacks ». Le
    pending_hazard_allocation en est exclu a dessein : une blessure mortelle HAZARDOUS n est pas
    une attaque (24.15 / 06.03), le PDF ne lui accorde donc aucun sursis.
    """
    for key in ("pending_shoot_allocation", "pending_fight_allocation"):
        alloc = game_state.get(key)  # get allowed (l allocation n existe que pendant l activation)
        if alloc is not None:
            return alloc
    return None


def _rule_sources_in_grace(game_state: Dict[str, Any], unit_id: str) -> Tuple[bool, Set[str]]:
    """Sources de regles de `unit_id` mortes SOUS L ATTAQUE en cours (19.04, derniere clause).

    « If that last model was destroyed as the result of an attack, the ability it was conferring
    upon the attached unit applies until the attacking unit has resolved all of its attacks. »

    La fenetre est portee par l allocation elle-meme : elle disparait avec elle
    (`_finalize_manual_allocation`), donc aucun etat en sursis ne peut survivre a l activation.
    Retourne (bloc bodyguard en sursis, ids des leaders/supports en sursis).
    """
    alloc = _attack_allocation_in_progress(game_state)
    if alloc is None:
        return False, set()
    native = False
    sources: Set[str] = set()
    for entry in alloc.get("rule_sources_in_grace", []):  # get allowed (absent tant qu aucune mort)
        if str(entry["squad_id"]) != str(unit_id):
            continue
        if entry["attached_from"] is None:
            native = True
        else:
            sources.add(str(entry["attached_from"]))
    return native, sources


def recompute_unit_rules_in_effect(game_state: Dict[str, Any], unit_id: str) -> None:
    """Reevalue `unit["UNIT_RULES"]` (19.04) depuis les figurines VIVANTES de l escouade.

    Appelee a chaque mort de figurine (`destroy_model`). Sans objet — et sans effet — pour une
    unite qui ne porte aucun character replie ET dont aucune figurine n a de regle propre :
    `_UNIT_RULES_IN_EFFECT_OWN` vaut alors exactement les regles du datasheet.

    Les unites construites hors du builder (fixtures de test synthetiques) n ont pas les cles
    de provenance : rien a recalculer, leur `UNIT_RULES` est deja la verite.
    """
    # `unit_by_id` existe dans tout game_state reel (construit au reset). Son absence signale
    # un game_state « moteur nu » — les fixtures spatiales de `destroy_model` ne modelisent que
    # models_cache/squad_models — ou il n y a par definition aucune unite a recalculer. Ce n est
    # pas un etat degrade rattrape en silence : c est un etat qui ne porte pas d unites.
    units_index = game_state.get("unit_by_id")  # get allowed (cf. ci-dessus)
    if units_index is None:
        return
    unit = units_index.get(str(unit_id))
    if unit is None:
        return
    if "_UNIT_RULES_OWN" not in unit:
        return
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive = [
        models_cache[mid] for mid in squad_models.get(str(unit_id), [])  # get allowed
        if mid in models_cache
    ]
    native_alive = any("attached_from" not in m for m in alive)
    alive_sources = {
        str(m["attached_from"]) for m in alive if "attached_from" in m
    }
    # Derniere clause de 19.04 : une source tuee PAR UNE ATTAQUE confere encore sa regle
    # jusqu a la fin des attaques de l unite attaquante.
    grace_native, grace_sources = _rule_sources_in_grace(game_state, str(unit_id))
    unit["UNIT_RULES"] = compute_unit_rules_in_effect(
        require_key(unit, "_UNIT_RULES_OWN"),
        require_key(unit, "_ATTACHED_RULE_GROUPS"),
        native_alive=native_alive or grace_native,
        alive_attached_sources=alive_sources | grace_sources,
    )


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
    """Build per-model entries for one squad (squad_multi_figurines.md PR1 1b).

    For mono-figurine units (no explicit unit["models"] list), create exactly
    one model entry derived from the unit's own fields. For multi-figurine
    squads (unit["models"] declared), iterate and build one entry per fig.

    Maintains parallel structures models_cache (model_id -> dict) and
    squad_models (squad_id -> [model_id,...]) without touching units_cache.

    points_per_hp est calcule PAR FIGURINE :
        points_per_hp_i = VALUE_i / HP_MAX_i
    ou VALUE_i = spec["VALUE"] (valeur de CETTE figurine, posee par
    _build_enhanced_unit) et JAMAIS unit["VALUE"], qui porte la valeur de
    l'ESCOUADE. Une escouade heterogene en points (Boyz : 9 x 7 + Nob 12)
    donne donc des points_per_hp differents d'une figurine a l'autre.
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

    # Niveau vertical de l'unité (ancre). Chaque figurine hérite du niveau de l'unité
    # sauf override explicite spec["level"] (escouade répartie sur plusieurs étages, §2.5).
    # 'level' optionnel = sol (0), aligné sur create_unit (game_state.py, level défaut 0),
    # défaut métier « scénarios sans étages »). Pas un masquage d'erreur : la validation (int >= 0)
    # est faite en amont par _validate_level dans create_unit ; ici on lit une unité déjà construite.
    unit_level = int(unit.get("level", 0))  # get allowed (champ optionnel, défaut sol)

    explicit_models = unit.get("models")
    if isinstance(explicit_models, list) and len(explicit_models) > 0:
        # Multi-figurine squad with explicit positions.
        model_specs = explicit_models
    else:
        # Backward compat: single-figurine squad derived from unit fields.
        # Mono-figurine : la figurine vaut ce que vaut l'unite (identite posee par
        # _build_enhanced_unit, game_state.py:967, pour les unites a models[] explicite).
        model_specs = [{"col": unit_col, "row": unit_row, "HP_CUR": unit_hp_cur, "level": unit_level, "VALUE": value}]

    model_count_at_start = len(model_specs)

    model_ids: List[str] = []
    for idx, spec in enumerate(model_specs):
        model_id = f"{unit_id}#{idx}"
        model_ids.append(model_id)
        spec_col, spec_row = normalize_coordinates(
            int(require_key(spec, "col")), int(require_key(spec, "row"))
        )
        spec_hp_max = int(spec.get("HP_MAX", hp_max))
        if spec_hp_max <= 0:
            raise ValueError(f"Squad {unit_id}: model spec has invalid HP_MAX={spec_hp_max}")
        spec_hp_cur = int(spec.get("HP_CUR", spec_hp_max))
        # VALUE PAR FIGURINE — jamais unit["VALUE"] (valeur d'escouade). Absence = erreur.
        spec_value = int(require_key(spec, "VALUE"))
        points_per_hp = float(spec_value) / float(spec_hp_max)
        # Orientation 0..5 : spec > unité > 0 (face nord). null explicite (scénario) → 0.
        _spec_orientation_raw = spec.get("orientation", unit.get("orientation", 0))  # get allowed (champ optionnel, défaut 0 = face nord)
        _spec_orientation = int(_spec_orientation_raw) if _spec_orientation_raw is not None else 0
        spec_role = _derive_model_role(cast(List[Dict[str, Any]], spec.get("UNIT_RULES", require_key(unit, "UNIT_RULES"))))
        models_cache[model_id] = {
            "squad_id": unit_id,
            "unitType": spec.get("unit_type") or unit.get("unitType"),
            "role": spec_role,
            "col": spec_col,
            "row": spec_row,
            "level": int(spec.get("level", unit_level)),
            "DISPLAY_NAME": spec.get("DISPLAY_NAME", unit.get("DISPLAY_NAME")),
            "ICON": spec.get("ICON", unit.get("ICON")),
            "ICON_SCALE": spec.get("ICON_SCALE", unit.get("ICON_SCALE")),
            "BASE_SHAPE": spec.get("BASE_SHAPE", unit.get("BASE_SHAPE")),
            "BASE_SIZE": spec.get("BASE_SIZE", unit.get("BASE_SIZE")),
            # HAUTEUR PAR FIGURINE (§03.04) : l'engagement est 2" horizontal ET 5" vertical, et
            # l'intervalle vertical [plancher, plancher + MODEL_HEIGHT] se mesure sur la FIGURINE,
            # exactement comme son socle deux lignes plus haut. Un personnage attache portait la
            # hauteur de l'escouade qui l'heberge : socle par figurine, hauteur au bloc, soit une
            # moitie de la regle par figurine et l'autre au bloc.
            # Propagation SANS invention, meme convention que `LD` / `UNIT_KEYWORDS` ci-dessous :
            # la cle n'est posee que si la donnee existe (toute unite de roster la porte, cf.
            # create_unit / _build_enhanced_unit) ; son absence LEVE chez le consommateur qui en a
            # besoin (`_vertical_classes`), jamais ici — une hauteur inventee est une mesure fausse.
            **(
                {"MODEL_HEIGHT": float(spec["MODEL_HEIGHT"])} if "MODEL_HEIGHT" in spec
                else {"MODEL_HEIGHT": float(unit["MODEL_HEIGHT"])} if "MODEL_HEIGHT" in unit
                else {}
            ),
            # Orientation PAR FIGURINE (0..5, pas de 60°). Source de vérité du footprint
            # oriente par-fig (pivot molette en move). Défaut métier : héritée de l'unité
            # (spec surchargeable dans le scénario) — pas un fallback anti-erreur.
            "orientation": _spec_orientation,
            "HP_CUR": spec_hp_cur,
            "HP_MAX": spec_hp_max,
            "player": unit_player,
            "SHOOT_LEFT": shoot_left,
            "ATTACK_LEFT": attack_left,
            "OC": int(spec.get("OC", oc)),
            # LD PAR FIGURINE (01.06) : « one or more of the Ld characteristics IN THAT UNIT ».
            # Une unite attachee porte plusieurs profils de Ld, la caracteristique se lit donc sur
            # la FIGURINE — comme OC/T/ARMOR_SAVE juste au-dessus — et le seuil de l'unite s'en
            # deduit (`unit_effective_leadership`), il ne se stocke nulle part.
            # Propagation SANS invention, meme convention que `UNIT_KEYWORDS` plus bas : la cle
            # n'est posee que si la donnee existe (toute unite de roster porte `LD`), et son
            # absence LEVE chez le consommateur qui en a besoin, jamais ici.
            **(
                {"LD": int(spec["LD"])} if "LD" in spec
                else {"LD": int(unit["LD"])} if "LD" in unit
                else {}
            ),
            "VALUE": spec_value,
            "points_per_hp": points_per_hp,
            "ARMOR_SAVE": int(spec.get("ARMOR_SAVE", armor_save)),
            "INVUL_SAVE": int(spec.get("INVUL_SAVE", invul_save)),
            "T": int(spec.get("T", t_stat)),
            # Keywords PROPRES de la figurine (19.03) : `unit["UNIT_KEYWORDS"]` porte l'UNION
            # des composants de l'escouade ; les regles « each model » (06.03) doivent lire la
            # figurine. Une figurine sans override est de l'unit_type de l'escouade — pour une
            # escouade homogene, union == keywords propres. Propagation SANS invention : la cle
            # n'est posee que si la donnee existe (toute unite de roster la porte, cf.
            # create_unit / _build_enhanced_unit) ; son absence est signalee par une erreur
            # explicite chez le consommateur qui en a besoin (ex. roll_hazard_for_unit, 06.03).
            **(
                {"UNIT_KEYWORDS": copy.deepcopy(spec["UNIT_KEYWORDS"])}
                if "UNIT_KEYWORDS" in spec
                else {"UNIT_KEYWORDS": copy.deepcopy(unit["UNIT_KEYWORDS"])}
                if "UNIT_KEYWORDS" in unit
                else {}
            ),
            # Règles PROPRES de la figurine — jumeau exact de UNIT_KEYWORDS ci-dessus, et pour
            # la même raison : `unit["UNIT_RULES"]` porte l'UNION en vigueur de l'escouade
            # (19.04), alors que les règles « if EVERY model in this unit has this ability »
            # (Deep Strike 24.09) doivent interroger CHAQUE figurine. Sans ça, une escouade
            # menée par un character sans la capacité l'aurait héritée de l'union.
            **(
                {"UNIT_RULES": copy.deepcopy(spec["UNIT_RULES"])}
                if "UNIT_RULES" in spec
                else {"UNIT_RULES": copy.deepcopy(unit["_UNIT_RULES_OWN"])}
                if "_UNIT_RULES_OWN" in unit
                else {"UNIT_RULES": copy.deepcopy(unit["UNIT_RULES"])}
                if "UNIT_RULES" in unit
                else {}
            ),
            # DEFAUT CONSERVE, et ce n'en est pas un : motif d'OVERRIDE par figurine. La
            # valeur de repli n'est pas une liste vide mais l'armement de L'UNITE — une
            # figurine qui ne surcharge pas ses armes herite de celles de son escouade.
            # C'est ce que le scenario exprime en ne declarant la cle que pour les figurines
            # atypiques (sergent, porteur d'arme speciale). Rien n'est masque : la valeur
            # heritee, elle, vient de `require_key(unit, ...)` en amont.
            "RNG_WEAPONS": copy.deepcopy(spec.get("RNG_WEAPONS", rng_weapons)),
            "CC_WEAPONS": copy.deepcopy(spec.get("CC_WEAPONS", cc_weapons)),
            "selectedRngWeaponIndex": spec.get("selectedRngWeaponIndex", selected_rng),
            "selectedCcWeaponIndex": spec.get("selectedCcWeaponIndex", selected_cc),
            # Provenance 19.04 : id de l unite character repliee dans ce squad par
            # `_fold_attached_characters`. Absente = figurine NATIVE du bodyguard. C est ce qui
            # permet a `recompute_unit_rules_in_effect` de savoir quelle source de regle meurt.
            **({"attached_from": str(spec["attached_from"])} if "attached_from" in spec else {}),
        }
    squad_models[unit_id] = model_ids


def _visual_meta(source: Dict[str, Any], role: Any) -> Dict[str, Any]:
    """Profil visuel exposé au frontend, lu indifféremment d'une unité ou d'une entrée de
    ``models_cache`` (mêmes noms de clés). DÉFINITION UNIQUE : ``build_units_cache`` compare
    la meta d'unité à celle de chaque figurine pour détecter l'hétérogénéité — deux littéraux
    divergents rendraient toutes les escouades hétérogènes sans lever la moindre erreur.

    ``role`` est passé à part : dérivé des UNIT_RULES côté unité, déjà calculé côté figurine.
    ``unit_type`` alimente l'initiale affichée à défaut d'illustration (une figurine hétérogène
    — personnage attaché, sergent — ne doit pas hériter de l'initiale de l'escouade).
    """
    return {
        "DISPLAY_NAME": source.get("DISPLAY_NAME"),
        "unit_type": source.get("unitType"),
        "ICON": source.get("ICON"),
        "ICON_SCALE": source.get("ICON_SCALE"),
        "BASE_SHAPE": source.get("BASE_SHAPE"),
        "BASE_SIZE": source.get("BASE_SIZE"),
        "role": role,
    }


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

    # Le cache des profils d'armes de l'observation (ObservationBuilder._encode_entity_weapons)
    # est indexé par (escouade, figurines vivantes). Le game_state étant MUTÉ d'un épisode à
    # l'autre et jamais recréé, une entrée survivrait à la rotation de rosters : mêmes ids,
    # armes différentes. Il tombe donc ici, avec les caches qu'il accompagne.
    from engine.observation_entities import WEAPON_PROFILE_CACHE_KEY

    game_state.pop(WEAPON_PROFILE_CACHE_KEY, None)
    game_state.pop("_entity_types_cache", None)  # item 1.7 — invalidé à la rotation de rosters

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
            # Niveau vertical de l'ancre (étages, format B). 0 = sol (défaut métier),
            # 'level' optionnel aligné sur create_unit (get + défaut sol). occupied_hexes/
            # occupation_map restent 2D à ce stade : la gestion des collisions par niveau
            # relève du chantier occupation & placement.
            "level": int(unit.get("level", 0)),  # get allowed (champ optionnel, défaut sol)
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
        # MODEL-LEVEL CACHE (squad_multi_figurines.md PR1 1b)
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
        # Niveau (étages) par-figurine, exposé au frontend (rendu + init plan de move).
        units_cache[unit_id]["level_by_model"] = {
            mid: int(require_key(models_cache[mid], "level"))
            for mid in squad_models.get(unit_id, [])  # get allowed
            if mid in models_cache
        }
        # Hauteur (pouces) du plancher sous chaque figurine — fondation de l'engagement 3D
        # (borne basse de l'intervalle vertical [plancher, plancher+MODEL_HEIGHT], verticalite.md §4/chantier 4).
        # Sol = 0.0 ; étage = height_inches du floor sous la fig (résolu par position). Aucun consommateur
        # encore (backend-only) → no-op tant que tout est au niveau 0.
        from engine.terrain_utils import floor_height_at
        _terrain_areas = game_state.get("terrain_areas", [])  # get allowed (board sans terrain)
        units_cache[unit_id]["floor_height_by_model"] = {
            mid: floor_height_at(
                _terrain_areas,
                int(models_cache[mid]["col"]),
                int(models_cache[mid]["row"]),
                int(require_key(models_cache[mid], "level")),
            )
            for mid in squad_models.get(unit_id, [])  # get allowed
            if mid in models_cache
        }
        # MODEL_HEIGHT (pouces) = borne HAUTE de l'intervalle vertical [plancher, plancher+MODEL_HEIGHT]
        # de l'engagement 3D (§01.04 « partie la plus proche »). EXIGÉ, plus optionnel : depuis que
        # toute la phase de combat passe `vertical_zone_inches`, une entrée sans cette clé ne
        # « dégénère » plus en 2D — elle fait lever `_vertical_classes` au premier test d'engagement.
        # L'invariant s'établit donc ici, à l'écriture unique, et pas aux dizaines de lectures.
        units_cache[unit_id]["MODEL_HEIGHT"] = float(require_key(unit, "MODEL_HEIGHT"))
        # §24.08 DEADLY DEMISE — valeur X (int ou str dé) lue depuis UNIT_RULES.rule_args.value.
        # Clée présente uniquement si la règle est déclarée ; absente = mécanisme inactif dans destroy_model.
        _dd_val = _get_deadly_demise_value(unit)
        if _dd_val is not None:
            units_cache[unit_id]["deadly_demise"] = _dd_val
        # Per-model visual meta (icône + échelle + forme/taille de base) : exposé
        # au frontend uniquement pour les escouades hétérogènes (au moins une
        # figurine dont le profil visuel diffère de l'unité parente, ex.
        # Sergeant / personnage attaché). Sinon le frontend retombe sur l'unité.
        unit_meta = _visual_meta(unit, _derive_model_role(require_key(unit, "UNIT_RULES")))
        models_meta = {
            mid: _visual_meta(models_cache[mid], models_cache[mid]["role"])
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
        # Mirror OC_TOTAL into units_cache (squad_multi_figurines.md PR1 1d): observation_builder
        # et logique d'objectifs lisent l'OC agrege depuis units_cache.
        if squad_id in units_cache:
            units_cache[squad_id]["OC_TOTAL"] = entry["oc_total"]
    game_state["squad_cache"] = squad_cache

    # VALUE totale de depart PAR JOUEUR, capturee ici et jamais recalculee : les figurines
    # detruites disparaissent de models_cache, donc la valeur initiale n est plus derivable
    # ensuite. Sert la feature « VALUE cumulee / valeur de depart » de l observation (force
    # d usure, V11 §9.8) — meme motif que model_count_at_start ci-dessus.
    # EFFECTIF de depart par joueur, meme photo, meme boucle : les figurines detruites
    # disparaissent de models_cache ET de squad_models (destroy_model), et squad_cache perd
    # les escouades aneanties — le compte de depart n'est donc derivable NULLE PART ensuite.
    # Il sert de denominateur aux ratios d'attrition (02_combat/c_ et d_). Pose ici, a cote de
    # value_at_start, pour que les deux references de depart soient prises au meme instant :
    # capturees a deux endroits, une reconstruction de cache pourrait n'en bouger qu'une.
    value_at_start: Dict[int, int] = {}
    model_count_at_start_by_player: Dict[int, int] = {}
    for model in models_cache.values():
        p = int(require_key(model, "player"))
        value_at_start[p] = value_at_start.get(p, 0) + int(require_key(model, "VALUE"))
        model_count_at_start_by_player[p] = model_count_at_start_by_player.get(p, 0) + 1  # get allowed : accumulateur, 0 = 1re figurine du joueur
    game_state["value_at_start"] = value_at_start
    game_state["model_count_at_start_by_player"] = model_count_at_start_by_player

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


def _remove_unit_from_all_activation_pools(game_state: Dict[str, Any], unit_id_str: str) -> None:
    """
    Remove a unit from all activation pools (move, shoot, charge, fight).
    Called when unit dies so pools never contain dead units (single source of truth).
    """
    for pool_key in (
        "move_activation_pool",
        "shoot_activation_pool",
        "charge_activation_pool",
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


def require_unit_from_cache(unit_id: str, game_state: Dict[str, Any], what: str) -> Dict[str, Any]:
    """Jumeau BRUYANT de ``get_unit_from_cache`` : l'absence LÈVE au lieu de rendre ``None``.

    À appeler quand l'appelant a DÉJÀ établi que l'unité est vivante (``get_unit_by_id`` +
    ``is_unit_alive``, ou une cible déclarée validée en amont). Dans ce cas l'absence n'est pas
    l'encodage de la mort — c'est une désynchronisation ``units`` / ``units_cache``, et y répondre
    par une valeur de repli produit un verdict géométrique INVENTÉ sans jamais crasher.

    ``what`` nomme le site appelant : c'est ce qui rend la panne localisable, et c'est la raison
    pour laquelle ce helper existe plutôt que dix ``raise`` recopiés à la main (types d'exception
    et libellés divergents, impossibles à attraper ou à tester uniformément).

    NE contrôle PAS le placement : une unité en réserves (20.01) EST dans ``units_cache`` avec la
    sentinelle ``(-1,-1)``. « Exister » et « être sur la table » sont deux contrats distincts —
    le second est ``require_entry_on_battlefield`` (``engine/spatial_relations.py``).
    """
    entry = get_unit_from_cache(unit_id, game_state)
    if not entry:
        raise KeyError(f"{what}: unit {unit_id} missing from units_cache")
    return entry


def is_unit_alive(unit_id: str, game_state: Dict[str, Any]) -> bool:
    """
    Check if a unit is alive (present in units_cache).
    
    units_cache contains ONLY living units; dead units are removed at end of action.

    CONTRAT, sur lequel s'appuient les appelants qui lisent le cache juste après : un `True`
    PROUVE la présence dans ``units_cache`` — c'est la définition même de ce prédicat. Un site
    qui a passé cette garde peut donc utiliser ``require_unit_from_cache`` sans repli ; son
    ``raise`` y est statiquement inatteignable tant que cette garde le précède, et c'est
    l'intention (il reste comme invariant, pour le jour où l'ordre changera).
    
    Args:
        unit_id: Unit ID (str)
        game_state: Game state with "units_cache"
        
    Returns:
        True if unit is in cache, False otherwise
    """
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist (call build_units_cache at reset)")
    
    return game_state["units_cache"].get(unit_id) is not None


def model_is_on_board(model: Dict[str, Any]) -> bool:
    """La figurine décrite par cette entrée de ``models_cache`` est-elle sur le champ de bataille ?

    Jumeau modèle de ``entry_is_on_battlefield`` (escouades). Sentinelle ``(-1,-1)`` : coordonnées
    négatives ↔ figurine hors table (réserves stratégiques, attente de déploiement).
    """
    return model.get("col", -1) >= 0


def unit_is_in_strategic_reserves(game_state: Dict[str, Any], unit_id: str) -> bool:
    """L'unité est-elle EN RÉSERVES (20.01) ? Vraie tant qu'elle n'a pas fait d'ingress move.

    `in_strategic_reserves` est remis à False par la mise en place (20.04) : le drapeau décrit
    l'état courant, pas l'origine de l'unité.
    """
    unit = require_unit_by_id(game_state, str(unit_id))
    # get allowed : une unité construite hors du chargeur (fixture moteur nu) ne porte pas le
    # champ ; elle n'a par construction jamais été déclarée en réserves. Ce n'est pas un repli
    # anti-erreur — le chargeur, lui, pose TOUJOURS le champ (`_build_enhanced_unit`).
    return bool(unit.get("in_strategic_reserves", False))


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


def is_unit_on_objective(unit: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
    """Regle 14.02 : l unite est-elle a portee d un objectif ? Lecture PAR FIGURINE.

    Helper generique de position (tir ET fight) : le reroll_towound_target_on_objective
    s applique aux deux phases.

    ⚠️ Cette fonction comparait l ANCRE d escouade a un hexe d objectif par egalite stricte —
    ni la bonne granularite (14.02 juge FIGURINE par figurine), ni la bonne geometrie (le
    controle d objectif du meme moteur compte l EMPREINTE DE SOCLE). Implementation unique
    desormais : `game_state.unit_is_within_objective`. Import local : `engine.game_state`
    importe ce module, l import de tete creerait un cycle (meme motif que
    `unit_can_occupy_upper_floor`, importe localement par 4 handlers).
    """
    from engine.game_state import unit_is_within_objective

    return unit_is_within_objective(game_state, unit)


# ============================================================================
# LoS invalidation choke-point (a′) — ligne_de_vue.md §4.1bis (D1–D4)
# ============================================================================
# _touch_unit_los est LE point unique d'invalidation LoS, déclenché par toute écriture de
# position (update_model_position per-figurine + update_units_cache_position anchre).
#   - pair-cache (_unit_los_pair_cache) : dict pur {(s,t): result}, invalidé ciblé (D3)
#   - los_cache + hex_los_cache : délégués à _invalidate_los_cache_for_moved_unit
#   - _unit_move_version : bump centralisé (sert _target_pool_cache / _los_cache_version /
#     enemy_pos_hash — D3)
# Batch (D1) : commit_move encadre ses N écritures pour n'émettre qu'UNE invalidation par unité
# + UN bump. Réentrant : seul l'ouvreur externe committe.


def _invalidate_pair_cache_for_unit(game_state: Dict[str, Any], unit_id: str) -> None:
    """Supprime du pair-cache LoS toutes les entrées où unit_id est tireur ou cible."""
    holder = game_state.get("_unit_los_pair_cache")
    if not holder:
        return
    uid = str(unit_id)
    for key in [k for k in holder if str(k[0]) == uid or str(k[1]) == uid]:
        del holder[key]


def _apply_los_invalidation(
    game_state: Dict[str, Any],
    unit_id: str,
    old_col: Optional[int],
    old_row: Optional[int],
) -> None:
    """Invalidation LoS immédiate (hors batch) : los_cache + hex_los_cache + pair-cache + bump."""
    from engine.phase_handlers.shooting_handlers import _invalidate_los_cache_for_moved_unit
    _invalidate_los_cache_for_moved_unit(game_state, unit_id, old_col=old_col, old_row=old_row)
    _invalidate_pair_cache_for_unit(game_state, unit_id)
    # Item 1.8 — invalider l'empreinte EZ mémoïsée dans l'entrée de l'unité touchée.
    uc = game_state.get("units_cache")
    if uc is not None:
        _ez_entry = uc.get(str(unit_id))
        if _ez_entry is not None:
            _ez_entry.pop("_ez_fp", None)
    game_state["_unit_move_version"] += 1


def _touch_unit_los(
    game_state: Dict[str, Any],
    unit_id: str,
    old_col: Optional[int] = None,
    old_row: Optional[int] = None,
) -> None:
    """Choke-point unique : à appeler après toute écriture de position d'une unité.

    Hors batch : invalide immédiatement (los_cache + hex_los_cache + pair-cache) + bump version.
    En batch : accumule l'unité (1re old_pos conservée) ; l'invalidation groupée a lieu à la
    fermeture (_los_end_batch)."""
    uid = str(unit_id)
    batch = game_state.get("_los_batch")
    if batch is not None:
        if uid not in batch:
            batch[uid] = (old_col, old_row)
        return
    _apply_los_invalidation(game_state, uid, old_col, old_row)


def _los_begin_batch(game_state: Dict[str, Any]) -> bool:
    """Ouvre un batch d'invalidation LoS. Retourne True si CE caller en est propriétaire
    (batch réentrant : un batch déjà ouvert n'est pas rouvert → seul l'ouvreur externe committe)."""
    if game_state.get("_los_batch") is None:
        game_state["_los_batch"] = {}
        return True
    return False


def _los_end_batch(game_state: Dict[str, Any], owned: bool) -> None:
    """Ferme le batch : une invalidation ciblée par unité touchée + un seul bump global."""
    if not owned:
        return
    batch = game_state.pop("_los_batch", None)
    if not batch:
        return
    from engine.phase_handlers.shooting_handlers import _invalidate_los_cache_for_moved_unit
    for uid, (oc, orow) in batch.items():
        _invalidate_los_cache_for_moved_unit(game_state, uid, old_col=oc, old_row=orow)
        _invalidate_pair_cache_for_unit(game_state, uid)
    game_state["_unit_move_version"] += 1


def assert_los_pair_cache_consistent(game_state: Dict[str, Any]) -> int:
    """Garde-fou debug (§6) : compare le pair-cache (valeur servie par compute_unit_los) au recalcul
    source de vérité (_compute_unit_los_uncached), pour toutes les paires inter-camps. Zéro divergence
    tolérée. Retourne le nb de paires vérifiées.

    Itère ``unit_by_id`` (dicts porteurs d'``id``, tels que passés à compute_unit_los en jeu réel) —
    PAS ``units_cache`` (dont les entrées ont ``id=None`` → cache bypassé)."""
    from engine.phase_handlers.shooting_handlers import compute_unit_los, _compute_unit_los_uncached
    units = require_key(game_state, "unit_by_id")
    live = require_key(game_state, "units_cache")
    checked = 0
    for s in units.values():
        for t in units.values():
            if s.get("id") is None or t.get("id") is None:
                continue
            if s["player"] == t["player"]:
                continue
            # Ignore les unités absentes du units_cache (mortes / dernière figurine retirée) :
            # non résolvables, hors périmètre LoS.
            if str(s["id"]) not in live or str(t["id"]) not in live:
                continue
            cached = compute_unit_los(game_state, s, t)
            fresh = _compute_unit_los_uncached(game_state, s, t)
            checked += 1
            if cached != fresh:
                raise AssertionError(
                    f"LoS pair-cache stale: ({s['id']}->{t['id']}) "
                    f"ver={game_state['_unit_move_version']} cached={cached} fresh={fresh}"
                )
    return checked


def update_units_cache_position(game_state: Dict[str, Any], unit_id: str, col: int, row: int) -> None:
    """
    Update only the position of a unit in units_cache.
    
    Convenience function for use after set_unit_coordinates.
    Retrieves HP_CUR and player from existing entry.

    Les coordonnees sont prises TELLES QUELLES : tous les appelants (moteur de mouvement,
    resync d'ancre d'escouade, previews de tir) fournissent deja des `int`, et l'entree du
    cache est lue plus loin comme un `int`. Normaliser ici rendrait le cache tolerant a des
    coordonnees mal typees au lieu de les faire echouer chez l'appelant qui les fabrique.

    Args:
        game_state: Game state with "units_cache"
        unit_id: Unit ID (str) — cle exacte de units_cache, aucune conversion
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

    if "orientation" in entry:
        orient_val = int(require_key(entry, "orientation"))
    else:
        orient_val = 0
    unit_stub = {
        "BASE_SHAPE": entry["BASE_SHAPE"],
        "BASE_SIZE": entry["BASE_SIZE"],
        "orientation": orient_val,
    }
    # MULTI-FIGURINE : `occupied_hexes` est l'union des socles VIVANTS, jamais l'empreinte de la
    # seule ancre — c'est `_recompute_squad_occupied_hexes` qui la produit, et lui seul. La
    # décision se prend AVANT d'écrire : poser l'empreinte d'ancre pour l'écraser ensuite ferait
    # exister, le temps de trois instructions, exactement l'état faux que cette fonction doit
    # empêcher, et ferait payer un calcul d'empreinte plus deux passes de `occupation_map`
    # pour rien.
    #
    # ⚠️ DÉFAUT MESURÉ le 2026-08-12 (run x1 instrumenté, E4 T5). `destroy_model` recalcule bien
    # l'union après un retrait, PUIS recalcule l'ancre — et quand c'est l'ANCRE qui tombe
    # (figurine d'index minimum), il appelle cette fonction, qui écrasait l'union. L'escouade
    # 102, 11 socles étalés de (0,35) à (7,38), se retrouvait avec `occupied_hexes == {(1,38)}`.
    # Or c'est CE champ que `build_enemy_adjacent_hexes` dilate pour produire la zone
    # d'engagement que `validate_move_plan` oppose aux déplacements : la zone se réduisait à
    # l'ancre, et l'unité 3 a fini son move NORMAL à 1 subhex de 102#7 — engagée, ce que 09.05
    # interdit — sans qu'aucun contrôle ne bronche. 2 violations sur ~1 300 moves ; 0 sur 2 259
    # après correction. Même champ, mêmes conséquences pour la LoS et le ciblage, qui le lisent.
    #
    # `update_model_position` enchaînait la même inversion (recompute puis ancre) ; poser la
    # correction ICI la ferme pour les deux, et pour tout futur appelant.
    squad_models = require_key(game_state, "squad_models")
    model_ids = squad_models.get(unit_id)
    if not isinstance(model_ids, (list, tuple)):
        model_ids = None

    entry["col"] = col
    entry["row"] = row
    if model_ids is not None and len(model_ids) > 1:
        # `_recompute` fait lui-même le diff de `occupation_map` à partir de l'empreinte
        # PRÉCÉDENTE encore présente dans l'entrée : ne pas la réécrire ici lui laisse la vraie
        # union à retirer, au lieu de cases d'ancre transitoires posées pour être reprises.
        _recompute_squad_occupied_hexes(game_state, unit_id)
    else:
        new_occupied = _compute_unit_occupied_hexes(col, row, unit_stub, game_state)
        _update_occupation_map(game_state, unit_id, entry, new_occupied)
        entry["occupied_hexes"] = new_occupied

    # Mono-figurine : la fig unique EST à l'ancre → resync sa position (occupied_hexes_by_model
    # + models_cache) pour rester cohérent après un déplacement d'ancre. Sans ça, model_centers
    # (lu par socle_from_cache_entry pour la distance bord-à-bord) resterait à l'ancienne
    # position (ex. tireur déplacé virtuellement en preview → cibles hors portée vues à tort).
    # Multi-figurine : ne PAS toucher les figs survivantes (sémantique « resync ancre seule » ;
    # les déplacements rigides passent par translate_squad_to_destination / _recompute).
    if model_ids is not None:
        if len(model_ids) == 1:
            mid = model_ids[0]
            entry["occupied_hexes_by_model"] = {mid: (col, row)}
            models_cache = game_state.get("models_cache")
            if isinstance(models_cache, dict) and mid in models_cache:
                models_cache[mid]["col"] = col
                models_cache[mid]["row"] = row
                # La HAUTEUR suit la position au même titre que l'empreinte : les deux cartes
                # par-figurine sont lues ENSEMBLE par l'engagement 3D (`_vertical_classes`), et
                # n'en resyncer qu'une laissait la figurine mesurée à l'altitude de son ANCIENNE
                # case. Écrites sans condition, comme `occupied_hexes_by_model` juste au-dessus :
                # une carte présente et l'autre absente est précisément la désynchronisation que
                # le journal per-figurine refuse désormais (cf. `_models_segment_for_unit`).
                #
                # Niveau STOCKÉ + `floor_height_at`, EXACTEMENT comme
                # `_recompute_squad_occupied_hexes` : ces deux fonctions écrivent la même carte
                # et doivent appliquer la même règle. Y résoudre le niveau par confinement
                # d'empreinte écrasait la hauteur correcte que `_recompute` venait de poser une
                # ligne plus haut (`update_model_position` enchaîne les deux) — une figurine
                # explicitement committée à l'étage retombait à 0,0.
                from engine.terrain_utils import floor_height_at
                _lvl = int(models_cache[mid].get("level", 0))  # get allowed (champ optionnel)
                entry["floor_height_by_model"] = {
                    mid: floor_height_at(
                        game_state.get("terrain_areas", []),  # get allowed (board sans terrain)
                        col, row, _lvl,
                    )
                }
                entry["level_by_model"] = {mid: _lvl}

    if game_state.get("debug_mode", False):
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "?")
        caller = inspect.stack()[1].function
        from engine.game_utils import add_debug_file_log
        add_debug_file_log(
            game_state,
            f"[UNITS_CACHE POSITION_UPDATE] E{episode} T{turn} {phase} unit_id={unit_id} "
            f"old=({old_col},{old_row}) new=({col},{row}) caller={caller}"
        )

    # Choke-point LoS (a′) : toute écriture d'ancre invalide les caches LoS de l'unité.
    # Couvre translate_squad_to_destination, reactive move, move_after_shooting, deployment.
    _touch_unit_los(game_state, unit_id, old_col, old_row)


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
    # V11 §0.46 (commit 2d6bd2a8) — ce chemin invalidait ici « _cached_best_enemy_score » et
    # « _cached_best_enemy_global » (les PV changent, donc le damage_ratio change). Ce n'est PAS
    # une invalidation oubliee : les deux cles n'ont plus ni ecrivain ni lecteur depuis que les
    # heuristiques de menace de macro_intents (get_best_enemy_global / get_best_enemy_score /
    # get_best_enemy_score_for_unit) ont ete supprimees — la cible est une dimension d'action
    # (§9 P3-1/P3-2). Attention : « _best_weapon_cache » est un AUTRE cache, toujours vif
    # (weapon_damage_cache -> w40k_core, observation_builder), et il ne depend pas des PV : il
    # est bati une fois par reset d'episode et n'a rien a faire ici.
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
    # La cible doit être POSÉE : une escouade hors table ne peut pas être chargée (20.01) — c'est
    # un refus de règle, il reste un `return False`.
    # L'ABSENCE, elle, n'en est pas un : l'unique appelant (`calculate_target_priority_score`) a
    # déjà appelé `require_hp_from_cache` sur cette même cible dix lignes plus haut, donc elle est
    # dans le cache. Les fusionner rendait « pas chargeable » sur une désynchronisation.
    target_entry = require_unit_from_cache(
        str(require_key(target, "id")), game_state, "check_if_melee_can_charge"
    )
    if not entry_is_on_battlefield(target_entry):
        return False
    for unit_id, entry in entries_on_battlefield(units_cache):
        unit = unit_by_id.get(str(unit_id))
        if not unit:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        if entry["player"] == current_player:
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Check if unit has melee weapons
            from engine.utils.weapon_helpers import get_selected_melee_weapon
            has_melee = False
            if melee_weapons(unit):
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
    if ranged_weapons(target):
        target_rng_dmg = max(
            target_rng_dmg,
            max(expected_dice_value(require_key(w, "DMG"), "target_rng_dmg_pool") for w in target["RNG_WEAPONS"])
        )
    if melee_weapons(target):
        target_cc_dmg = max(
            target_cc_dmg,
            max(expected_dice_value(require_key(w, "DMG"), "target_cc_dmg_pool") for w in target["CC_WEAPONS"])
        )
    
    threat_level = max(target_rng_dmg, target_cc_dmg)
    
    # Phase 2: HP from cache only
    target_hp = require_hp_from_cache(str(target["id"]), game_state)
    
    # Calculate if unit can kill target in 1 phase (use selected weapon or first weapon)
    unit_rng_weapon = get_selected_ranged_weapon(unit)
    if not unit_rng_weapon and ranged_weapons(unit):
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
    if ranged_weapons(unit):
        rng_dmg = max(
            rng_dmg,
            max(expected_dice_value(require_key(w, "DMG"), "enrich_rng_dmg_pool") for w in unit["RNG_WEAPONS"])
        )
    if melee_weapons(unit):
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

    Utilisé par la prune conservatrice des ennemis : au-delà de ce diamètre, on tronque la
    contribution « rayon d'empreinte » pour rester sûr sans exploser la fenêtre si des données
    unité sont aberrantes. DEUX lecteurs, de portées différentes :
    ``observation_builder._engagement_relevant_entries`` à chaque construction d'observation,
    sans aucune garde, et ``movement_handlers._enemy_items_within_move_engagement_horizon``
    seulement sous ``ez > 1``. Ne pas réduire ce seuil au seul chemin du déplacement.

    Aucun défaut caché, exactement comme ``get_engagement_zone`` (même section ``game_rules``,
    même fichier) : un état sans ``config``/``game_rules``/``max_base_size_hex`` est malformé,
    pas un cas à replier sur une constante. Ce seuil est en DIAMÈTRE HEX et n'est PAS scalé par
    ``inches_to_subhex`` (absent de la liste de conversion de ``w40k_core``) : un littéral en
    dur n'aurait donc même pas le même sens d'un plateau à l'autre.
    """
    config = require_key(game_state, "config")
    game_rules = require_key(config, "game_rules")
    return int(require_key(game_rules, "max_base_size_hex"))


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

    for _uid, entry in enemy_entries_on_battlefield(units_cache, player_int):
        hp_cur = require_key(entry, "HP_CUR")
        if hp_cur <= 0:
            continue

        # EZ mesurée depuis le SOCLE (03.04 « engagement range » + 01.04 « closest part of the
        # model's base ») : dilater l'empreinte COMPLETE des figurines vivantes, pas l'ancre unique.
        # Dilater la seule ancre sous-estime la zone dès qu'un socle couvre plusieurs hexes.
        unit_cells = set(require_key(entry, "occupied_hexes"))
        all_enemy_occupied.update(unit_cells)
        per_unit_occupied.append(unit_cells)

    from engine.hex_utils import dilate_hex_set
    zone_hexes = dilate_hex_set(all_enemy_occupied, ez_dilation, board_cols, board_rows)

    counts: Dict[Tuple[int, int], int] = {h: 1 for h in zone_hexes}

    return counts, zone_hexes


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


def _build_enemy_adjacent_hexes_all_players(game_state: Dict[str, Any]) -> None:
    """Call build_enemy_adjacent_hexes for every player present in units_cache."""
    for player in _get_players_present_from_units_cache(game_state):
        build_enemy_adjacent_hexes(game_state, player)


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

    # Hors table écarté ICI et pas plus bas : l'entrée hors table porte un
    # `occupied_hexes_by_model` PEUPLÉ de `(-1,-1)` (mesuré), donc la branche `by_model` ci-dessous
    # dilatait une vraie zone d'engagement autour de l'origine du plateau. Un ennemi en réserves
    # verrouillait ainsi le coin (0,0) pour l'adversaire.
    for _uid, cache_entry in entries_on_battlefield(units_cache):
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


def _get_unit_rule_arg(
    unit: Dict[str, Any],
    effect_rule_id: str,
    arg_key: str,
    accepted_types: tuple,
) -> Optional[Any]:
    """Extraire rule_args[arg_key] depuis l'entrée UNIT_RULES portant effect_rule_id.

    Retourne None si l'effet est absent de l'unité.
    Lève ValueError si rule_args est manquant ou si arg_key est absent.
    Lève TypeError si le type de la valeur n'est pas dans accepted_types.
    """
    source_rule_id = get_source_unit_rule_id_for_effect(unit, effect_rule_id)
    if source_rule_id is None:
        return None
    unit_id = require_key(unit, "id")
    unit_rules = require_key(unit, "UNIT_RULES")
    for rule_entry in unit_rules:
        if str(require_key(rule_entry, "ruleId")) != source_rule_id:
            continue
        rule_args = rule_entry.get("rule_args")
        if not isinstance(rule_args, dict):
            raise ValueError(
                f"Rule '{source_rule_id}' on unit {unit_id} "
                f"must define rule_args for {effect_rule_id}"
            )
        if arg_key not in rule_args:
            raise ValueError(
                f"Rule '{source_rule_id}' argument '{arg_key}' is missing "
                f"for unit {unit_id}"
            )
        raw = rule_args[arg_key]
        if not isinstance(raw, accepted_types):
            type_names = "/".join(t.__name__ for t in accepted_types)
            raise TypeError(
                f"Rule '{source_rule_id}' argument '{arg_key}' must be {type_names}, "
                f"got {type(raw).__name__} for unit {unit_id}"
            )
        return raw
    raise ValueError(
        f"Source rule '{source_rule_id}' not found in UNIT_RULES "
        f"for unit {unit_id}"
    )


def _get_fnp_threshold_for_rule(unit: Dict[str, Any], rule_id: str, label: str) -> Optional[int]:
    """Lit et valide le seuil FNP d'une règle donnée (24.12). Lève si mal configurée."""
    raw = _get_unit_rule_arg(unit, rule_id, "threshold", (int,))
    if raw is None:
        return None
    if not 2 <= raw <= 6:
        raise ValueError(
            f"{label} threshold must be 2-6, got {raw} "
            f"for unit {require_key(unit, 'id')}"
        )
    return raw


def _get_feel_no_pain_threshold(unit: Dict[str, Any]) -> Optional[int]:
    """Retourne le seuil X du Feel No Pain X+ de l'unité, ou None si absente (24.12)."""
    return _get_fnp_threshold_for_rule(unit, "feel_no_pain", "Feel No Pain")


def _get_feel_no_pain_vs_psychic_threshold(unit: Dict[str, Any]) -> Optional[int]:
    """Retourne le seuil FNP vs attaques PSYCHIC (Psychic Hood), ou None (24.12)."""
    return _get_fnp_threshold_for_rule(unit, "feel_no_pain_vs_psychic", "FNP vs psychic")


def _get_feel_no_pain_near_objective_threshold(unit: Dict[str, Any]) -> Optional[int]:
    """Retourne le seuil FNP near objective (Unbreakable Resolve), ou None (24.12)."""
    return _get_fnp_threshold_for_rule(unit, "feel_no_pain_near_objective", "FNP near objective")


def _unit_is_near_objective_or_center(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """True si l'unité est à portée d'un objectif (3") ou à 6" du centre (Unbreakable Resolve).

    Condition positionnelle de feel_no_pain_near_objective (24.12).
    """
    # Lazy import pour eviter le cycle shared_utils ← fight_handlers ← shared_utils.
    from engine.phase_handlers.fight_handlers import _fight_v11_objectives_within_range  # noqa: PLC0415
    if _fight_v11_objectives_within_range(game_state, unit, 3):
        return True
    ish = int(require_key(game_state, "inches_to_subhex"))
    center_range = 6 * ish
    board_cols = int(require_key(game_state, "board_cols"))
    board_rows = int(require_key(game_state, "board_rows"))
    center_col = board_cols // 2
    center_row = board_rows // 2
    units_cache = require_key(game_state, "units_cache")
    uid = str(require_key(unit, "id"))
    entry = units_cache.get(uid)
    if entry is None or not entry_is_on_battlefield(entry):
        return False
    from engine.hex_utils import min_distance_between_sets  # noqa: PLC0415
    ufp = entry_footprint(entry)
    return min_distance_between_sets(ufp, {(center_col, center_row)}, max_distance=center_range) <= center_range


def _collect_fnp_thresholds(
    unit: Dict[str, Any], game_state: Dict[str, Any], weapon: Dict[str, Any]
) -> List[int]:
    """Seuils FNP applicables à une blessure normale (tir/mêlée), dans l'ordre de tentative.

    Générique d'abord, puis conditionnel PSYCHIC si l'arme porte le mot-clé, puis conditionnel
    near_objective si l'unité est à portée d'un objectif ou du centre (24.12).
    """
    return _collect_fnp_thresholds_mortal(
        unit, game_state, is_psychic=weapon_has_rule(weapon, "PSYCHIC")
    )


def _collect_fnp_thresholds_mortal(
    unit: Dict[str, Any], game_state: Dict[str, Any], *, is_psychic: bool = False
) -> List[int]:
    """Seuils FNP applicables à une blessure mortelle, dans l'ordre de tentative.

    is_psychic=True si la source est une attaque ou capacité PSYCHIC (ex. Da Jump).
    """
    thresholds: List[int] = []
    th = _get_feel_no_pain_threshold(unit)
    if th is not None:
        thresholds.append(th)
    th_psy = _get_feel_no_pain_vs_psychic_threshold(unit)
    if th_psy is not None and is_psychic:
        thresholds.append(th_psy)
    th_obj = _get_feel_no_pain_near_objective_threshold(unit)
    if th_obj is not None and _unit_is_near_objective_or_center(game_state, unit):
        thresholds.append(th_obj)
    return thresholds


def _roll_fnp_sequential(n_wounds: int, thresholds: List[int]) -> int:
    """Retourne les blessures non sauvées après jets FNP séquentiels (24.12).

    Pour chaque blessure, on tente chaque seuil en ordre : dès qu'un jet >= seuil, la
    blessure est ignorée. Utilisé quand plusieurs FNP (génériques ou conditionnels) s'appliquent.
    """
    import random
    remaining = 0
    for _ in range(n_wounds):
        saved = any(random.randint(1, 6) >= th for th in thresholds)
        if not saved:
            remaining += 1
    return remaining


def _get_deadly_demise_value(unit: Dict[str, Any]) -> Optional[Any]:
    """Retourne la valeur X de Deadly Demise (int ou expression dé comme 'D3'), ou None.

    Lue depuis UNIT_RULES[i].rule_args.value (24.08). Lève si la règle est présente
    mais mal configurée — aucun repli silencieux.
    """
    return _get_unit_rule_arg(unit, "deadly_demise", "value", (int, str))


#: Rayon de declenchement de `reactive_move`, EN POUCES (cf. config/unit_rules.json).
_REACTIVE_TRIGGER_RANGE_INCHES = 9

#: Sentinelle pour `_charge_plan_cache` — distingue un cache miss de None (plan invalide).
_CBVP_MISS: object = object()


def _build_reactive_move_destinations_pool(
    game_state: Dict[str, Any],
    reactive_unit: Dict[str, Any],
    move_range_inches: int,
    enemy_adjacent_hexes_override: Optional[Set[Tuple[int, int]]] = None,
) -> List[Tuple[int, int]]:
    """
    Build legal reactive move destinations using BFS with movement restrictions.

    ``move_range_inches`` est le D6 de la capacité, EN POUCES : le BFS ci-dessous compte des pas
    de GRILLE, donc le budget doit être converti (× ``inches_to_subhex``) comme partout ailleurs
    — budget de move, jet d'advance, jet de charge (`_charge_budget_subhex`). Sans conversion un
    « D6 pouces » plafonnait à 6 CASES : 1,2" à x5, 0,6" à x10, autrement dit une capacité quasi
    inopérante dès qu'on quitte le board x1.
    """
    if move_range_inches <= 0:
        raise ValueError(f"reactive_move move_range must be > 0, got {move_range_inches}")
    move_range = int(move_range_inches) * int(require_key(game_state, "inches_to_subhex"))
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
    for _unit_id, entry in entries_on_battlefield(units_cache, exclude_id=reactive_unit_id):
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

    # Le BFS ci-dessus ne valide que la case d'ANCRE. Or un mouvement d'unité déplace TOUTES
    # ses figurines (03.01) : sans ce filtre, les figurines non-ancres atterrissent sur des
    # coordonnées jamais vérifiées — dans un mur, dans l'empreinte d'une autre escouade, ou
    # hors plateau — et la conversion du budget en subhex multiplie ce vecteur par 5 ou 10.
    # On ne garde donc que les destinations dont le PLAN RIGIDE est constructible et valide,
    # par la primitive commune à tous les mouvements d'escouade. C'est ce filtre qui autorise
    # l'appelant à translater le bloc au lieu de ne bouger que l'ancre.
    squad_id = str(require_key(reactive_unit, "id"))
    # `require_coherency` DESACTIVE : la translation est rigide → la formation préserve son état
    # de cohérence (invariant par translation). Le cas "formation déjà incohérente" est rejeté
    # EN AMONT par maybe_resolve_reactive_move avant d'appeler cette fonction (03.01), avec log
    # `reactive_move_declined reason=formation_incoherente`. Ici, la formation d'arrivée est donc
    # garantie cohérente si la formation de départ l'est — le re-vérifier serait inutile.
    constraints = {
        **DEFAULT_MOVE_CONSTRAINTS,
        "budget_per_model": move_range,
        "require_coherency": False,
    }
    validated: List[Tuple[int, int]] = []
    for dest in valid_destinations:
        plan = build_rigid_plan(int(dest[0]), int(dest[1]), squad_id, game_state)
        if plan is not None and validate_move_plan(plan, game_state, constraints):
            validated.append(dest)

    # Deterministic destination order.
    validated.sort(key=lambda pos: (int(pos[0]), int(pos[1])))
    return validated


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
    ordered = [eligible_by_id[uid] for uid in dict.fromkeys(macro_order) if uid in eligible_by_id]
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

    moved_unit = require_unit_by_id(game_state, moved_unit_id_str)
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
        unit = require_unit_by_id(game_state, unit_id)

        unit_id_str = str(require_key(unit, "id"))
        if not is_unit_alive(unit_id_str, game_state):
            continue

        unit_player = require_key(unit, "player")
        if int(unit_player) == int(moved_player):
            continue
        # HORS TABLE (réserves 20.01 / attente de déploiement) : elle ne réagit à rien. Sans
        # cette garde, sa sentinelle (-1,-1) tombe à moins de 9" du coin du plateau et un
        # déplacement adverse dans cette zone déclencherait un mouvement réactif depuis le néant.
        if not entry_is_on_battlefield(units_cache[unit_id]):
            continue
        if unit_id_str in reacted_set:
            continue
        if not _unit_has_rule_effect(unit, "reactive_move"):
            continue

        unit_col, unit_row = require_unit_position(unit, game_state)
        # Rayon de DECLENCHEMENT de la capacite : 9 POUCES (config/unit_rules.json,
        # `reactive_move` : « after an enemy unit ends a move ... within 9" of this unit »).
        # JUMEAU du budget converti plus bas : compare a une distance de GRILLE, il valait
        # 9 cases — 1,8" a x5, 0,9" a x10, soit moins que la zone d'engagement : la capacite ne
        # se declenchait quasiment plus des qu'on quittait le board x1.
        _trigger_radius = _REACTIVE_TRIGGER_RANGE_INCHES * int(require_key(game_state, "inches_to_subhex"))
        if calculate_hex_distance(unit_col, unit_row, to_col_int, to_row_int) > _trigger_radius:
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

    # Publier l'instantané d'adjacence sous les clés que le reste du moteur lit au démarrage
    # d'une phase : `validate_move_plan` en dépend (`enemy_adjacent_hexes_player_N`), et sans
    # elles le pool réactif ne pouvait valider QUE la case d'ancre. C'est le même instantané que
    # celui passé en override au pool et que `refresh_all_positional_caches_after_reactive_move`
    # réécrit après chaque déplacement — pas une seconde vérité.
    for _p_int, _p_set in reactive_adjacent_sets_by_player.items():
        game_state[f"enemy_adjacent_hexes_player_{_p_int}"] = set(_p_set)
    for _p_int, _p_counts in reactive_adjacent_counts_by_player.items():
        game_state[f"enemy_adjacent_counts_player_{_p_int}"] = dict(_p_counts)

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

            # 03.01 ENDING A MOVE : une escouade hors cohérence ne peut pas faire ce mouvement.
            # Même règle que build_squad_move_cell_map (pool vide si formation incohérente).
            if not validate_squad_coherency(game_state, reactive_unit_id):
                declined_count += 1
                append_action_log(
                    game_state,
                    {
                        "type": "reactive_move_declined",
                        "unitId": reactive_unit_id,
                        "reason": "formation_incoherente",
                        "triggered_by_unit_id": moved_unit_id_str,
                        "trigger_move_kind": move_kind,
                        "trigger_move_cause": move_cause,
                        "event_fromCol": from_col_int,
                        "event_fromRow": from_row_int,
                        "event_toCol": to_col_int,
                        "event_toRow": to_row_int,
                    },
                )
                continue

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
            # Mouvement d'unité (03.01) : toutes les figurines suivent. La destination a été
            # retenue par le pool PARCE QUE son plan rigide est valide pour chaque figurine —
            # `update_units_cache_position` seul ne resynchronise que les escouades
            # mono-figurine et laissait les socles des autres sur place.
            # Empreinte AVANT la translation : le delta d'adjacence ci-dessous doit porter sur
            # les cases reellement liberees et occupees par le BLOC, pas sur la seule ancre.
            _old_occupied = set(
                require_key(game_state["units_cache"][reactive_unit_id], "occupied_hexes")
            )
            set_unit_coordinates(reactive_unit, dest_col, dest_row)
            translate_squad_to_destination(game_state, reactive_unit_id, dest_col, dest_row)
            _new_occupied = set(
                require_key(game_state["units_cache"][reactive_unit_id], "occupied_hexes")
            )
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
                # Empreintes du BLOC, et zone d'engagement REELLE : passer l'ancre seule et
                # laisser `engagement_zone` a son defaut de 1 ecrivait un cache faux des que
                # l'escouade avait plusieurs figurines ou que la resolution depassait x1 — cache
                # ensuite consomme par le pool reactif suivant, le masque de move et
                # l'eligibilite au tir.
                old_occupied=_old_occupied,
                new_occupied=_new_occupied,
                board_cols=board_cols,
                board_rows=board_rows,
                engagement_zone=get_engagement_zone(game_state),
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
# Reference: Documentation/Reference/moteur/squad_multi_figurines.md §"Definition des distances en hex-grid"
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

    ⚠️ RESOLUTION : le mode configure vaut pour les boards ou une figurine occupe PLUSIEURS cases
    (x5 et au-dela), ou « bord a bord » a un sens geometrique. A `inches_to_subhex <= 1` une figurine
    tient dans UNE case quelle que soit la taille de son socle : la coherency s'y mesure de CENTRE
    D'HEX a centre d'hex, soit le mode 'footprint' (empreintes mono-cellule). MEME point de bascule
    que move / charge / EZ / tir : `spatial_relations.geometry_is_hex`, dont le SEUL critere est
    `inches_to_subhex`. Le mode euclidien a x1 mesurait une geometrie continue sur une grille
    d'entiers et y tolerait un voisin jusqu'a ~3,2 hexes (2" x sqrt(3), MOINS deux rayons de socle),
    la ou la regle a cette resolution est 2 cases.
    """
    n = len(models)
    if n <= 1:
        return [False] * n
    coh = get_coherency_subhex(game_state)
    coh_max = get_cohesion_max_subhex(game_state)
    min_neighbors = get_min_neighbors(game_state)
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    mode = require_key(game_rules, "cohesion_distance_mode")
    if geometry_is_hex(game_state):
        mode = "footprint"
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


def _coherency_verdict(
    neighbor: List[List[bool]], too_far: List[bool], min_neighbors: int
) -> List[bool]:
    """VERDICT UNIQUE de la coherency 03.03, commun aux deux metriques.

    Entrees deja mesurees par la metrique appelante :
      - ``neighbor[i][j]`` : les figs i et j sont a <= ``coh`` bord-a-bord (2") ;
      - ``too_far[i]``     : la fig i a AU MOINS une soeur a plus de ``coh_max`` (9").

    Regles appliquees :
      - 1re puce — « within 2" of at least one other model » (03.03), precisee par la FAQ :
        l'escouade doit former UNE SEULE CHAINE. On calcule donc les composantes connexes du graphe
        des voisins et on met en violation les figs du composant MINORITAIRE. `min_neighbors`
        (`game_rules.squad_min_neighbors`) reste applique en plus : degre minimal exige par fig.
        A 1, il est implique par la connexite (une fig isolee est un composant de taille 1).
      - 2e puce — « within 9" of EVERY other model » (03.03) : critere PAR PAIRES. Ce n'est PAS un
        cercle d'etalement ; l'ancienne version en dessinait un, centre sur la paire la plus
        eloignee, ce qui rendait le verdict dependant de la position absolue de l'escouade (plusieurs
        paires a distance maximale exactement egale, departagees par le bruit flottant) et cassait
        l'invariance par translation dont dependent `erode_move_pool_by_squad_block` et
        `explain_move_plan_rejection`.

    Le 5" VERTICAL des deux puces n'est pas mesure (coherency 2D) — a cabler avec le chantier etages.
    """
    n = len(neighbor)
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
                if neighbor[k][nb] and comp[nb] == -1:
                    comp[nb] = num_comp
                    stack.append(nb)
        num_comp += 1
    comp_size: Dict[int, int] = {}
    for c in comp:
        comp_size[c] = comp_size.get(c, 0) + 1  # fallback allowed — compteur d'accumulation (0 = valeur initiale, pas un masquage)
    flags = [False] * n
    for i in range(n):
        if comp_size[comp[i]] * 2 <= n:
            flags[i] = True
            continue
        if sum(1 for j in range(n) if j != i and neighbor[i][j]) < min_neighbors:
            flags[i] = True
            continue
        if too_far[i]:
            flags[i] = True
    return flags


def _coherency_flags_euclidean(
    models: List[Dict[str, Any]], coh: int, coh_max: int, min_neighbors: int
) -> List[bool]:
    """Distances bord-a-bord EUCLIDIENNES (geometrie de rendu, hexCenter, hex_radius=1) puis
    `_coherency_verdict` — le verdict est partage avec le mode 'footprint', seule la mesure change."""
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
    model_range = coh * sqrt3      # 2" en unites de rendu (hex_radius=1)
    global_range = coh_max * sqrt3  # ecart max fig-a-fig (9"), bord a bord
    neighbor = [[False] * n for _ in range(n)]
    too_far = [False] * n
    for i in range(n):
        for j in range(i + 1, n):
            d = hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) - radii[i] - radii[j]
            if d <= model_range:
                neighbor[i][j] = neighbor[j][i] = True
            if d > global_range:
                too_far[i] = too_far[j] = True
    return _coherency_verdict(neighbor, too_far, min_neighbors)


def _coherency_flags_footprint(
    models: List[Dict[str, Any]],
    game_state: Dict[str, Any],
    coh: int,
    coh_max: int,
    min_neighbors: int,
) -> List[bool]:
    """Distances HEX empreinte-a-empreinte (« closest part of base », 01.04) via
    ``min_distance_between_sets``, puis `_coherency_verdict` — MEME verdict que le mode euclidien
    (connexite + paires), seule la mesure change. A x1 les empreintes sont mono-cellule, donc c'est
    la distance hex de centre a centre.

    ⚠️ Ce mode n'appliquait PAS la connexite (juste « >= min_neighbors voisin ») : deux paquets
    disjoints y passaient, alors que la FAQ exige UNE SEULE CHAINE. Les deux modes divergeaient donc
    sur la 1re puce, et les copies inline de charge/fight (supprimees) reproduisaient la version
    permissive — d'ou des formations acceptees par un pile-in puis refusees par le move."""
    from engine.hex_utils import min_distance_between_sets
    n = len(models)
    footprints = [
        _compute_unit_occupied_hexes(int(m["col"]), int(m["row"]), m, game_state)
        for m in models
    ]
    neighbor = [[False] * n for _ in range(n)]
    too_far = [False] * n
    for i in range(n):
        for j in range(i + 1, n):
            d = min_distance_between_sets(footprints[i], footprints[j], max_distance=coh_max)
            if d <= coh:
                neighbor[i][j] = neighbor[j][i] = True
            if d > coh_max:
                too_far[i] = True
                too_far[j] = True
    return _coherency_verdict(neighbor, too_far, min_neighbors)


def is_base_to_base(col_a: int, row_a: int, col_b: int, row_b: int) -> bool:
    """B2B: hexes directement adjacents (distance hex == 1).
    Strictement plus contraignant que l Engagement Range."""
    return calculate_hex_distance(col_a, row_a, col_b, row_b) == BASE_TO_BASE_SUBHEX


# ============================================================================
# MODEL-LEVEL HELPERS (squad_multi_figurines.md PR1 1b)
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
    alive = [
        entry for m in model_ids
        if (entry := models_cache.get(m)) is not None and model_is_on_board(entry)
    ]
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
    # Absence = escouade DÉTRUITE, et il n'y a alors rien à recalculer : `remove_model_from_squad`
    # et `update_units_cache_hp` retirent l'escouade du cache sans purger `models_cache`, donc le
    # retrait d'une figurine d'une escouade déjà morte atteint réellement ce chemin. C'est un cas
    # métier, pas un repli — à la différence du cache ABSENT, qui ne l'est pas.
    units_cache = require_key(game_state, "units_cache")
    entry = units_cache.get(squad_id)  # get allowed (escouade détruite = rien à recalculer)
    if entry is None:
        return
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    base_shape = entry["BASE_SHAPE"]
    base_size = entry["BASE_SIZE"]
    unit_orientation = int(entry.get("orientation", 0))  # get allowed
    old_occupied = entry.get("occupied_hexes", set())
    new_occupied: Set[Tuple[int, int]] = set()
    new_by_model: Dict[str, Tuple[int, int]] = {}
    # Niveau (étages) par-figurine : publié vers le frontend (rendu + init du plan de move par-fig).
    # Sans ça une fig à l'étage remonte au niveau d'ancre → traitée au sol → superposition cassée.
    new_level_by_model: Dict[str, int] = {}
    # Hauteur (pouces) du plancher sous chaque fig — fondation engagement 3D (cf. build_units_cache).
    new_floor_height_by_model: Dict[str, float] = {}
    # Orientation (0..5) par figurine : source de vérité du footprint orienté, publiée au frontend
    # (rendu du socle orienté + init du plan de move par-fig / pivot molette).
    new_orientation_by_model: Dict[str, int] = {}
    from engine.terrain_utils import floor_height_at
    _terrain_areas = game_state.get("terrain_areas", [])  # get allowed (board sans terrain)
    for mid in squad_models.get(squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is None:
            raise ConfigurationError(
                f"_recompute_squad_occupied_hexes: mid {mid!r} in squad_models[{squad_id!r}] but absent from models_cache — data desync"
            )
        m_col = int(m["col"])
        m_row = int(m["row"])
        m_orient = int(m.get("orientation", unit_orientation))  # get allowed (défaut = orient unité)
        # Le niveau STOCKÉ fait foi : ce resync recopie l'état, il ne le rejuge pas. Le
        # re-résoudre ici rétrograderait un étage explicitement committé par
        # `update_model_position` — `resolve_model_floor_level` exige que l'EMPREINTE tienne
        # entièrement sur le plancher, un critère plus strict que celui de la pose. C'est aux
        # fonctions de MOUVEMENT de résoudre le niveau d'arrivée (cf. `commit_move` et
        # `translate_squad_to_destination`), pas au resync de cache.
        m_level = int(require_key(m, "level"))
        new_by_model[mid] = (m_col, m_row)
        new_level_by_model[mid] = m_level
        new_floor_height_by_model[mid] = floor_height_at(_terrain_areas, m_col, m_row, m_level)
        new_orientation_by_model[mid] = m_orient
        # Empreinte PAR FIGURINE : orientation propre à la fig (défaut = orient unité pour
        # les états antérieurs sans clé). Base = celle de l'unité (bases mixtes hors scope).
        m_stub = {
            "BASE_SHAPE": base_shape,
            "BASE_SIZE": base_size,
            "orientation": m_orient,
        }
        fp = _compute_unit_occupied_hexes(m_col, m_row, m_stub, game_state)
        new_occupied.update(fp)
    entry["occupied_hexes"] = new_occupied
    entry["occupied_hexes_by_model"] = new_by_model
    entry["level_by_model"] = new_level_by_model
    entry["floor_height_by_model"] = new_floor_height_by_model
    entry["orientation_by_model"] = new_orientation_by_model
    # item 1.8 : _ez_fp dépend de occupied_hexes_by_model — purger ici couvre les cas
    # où un modèle non-ancre bouge (la seule écriture de occupied_hexes_by_model hors
    # _touch_unit_los).
    entry.pop("_ez_fp", None)
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

    La translation est appliquée en coordonnées CUBE, MIROIR EXACT de
    ``build_rigid_plan`` (le plan validé en amont) : en offset odd-q, un delta de
    colonne impair change la parité de chaque figurine et déforme le bloc (V11 T6-h).
    Toute divergence entre les deux ferait committer une formation differente de
    celle que ``validate_move_plan`` a acceptée.
    """
    from engine.hex_utils import offset_to_cube, cube_to_offset

    units_cache = game_state.get("units_cache", {})  # get allowed
    entry = units_cache.get(squad_id)
    if entry is None:
        return
    norm_dest_col, norm_dest_row = normalize_coordinates(int(dest_col), int(dest_row))
    old_col = int(entry.get("col", norm_dest_col))
    old_row = int(entry.get("row", norm_dest_row))
    if (norm_dest_col, norm_dest_row) != (old_col, old_row):
        ox, oy, oz = offset_to_cube(old_col, old_row)
        nx, ny, nz = offset_to_cube(norm_dest_col, norm_dest_row)
        dcx, dcy, dcz = nx - ox, ny - oy, nz - oz
        models_cache = require_key(game_state, "models_cache")
        squad_models = require_key(game_state, "squad_models")
        for mid in squad_models.get(squad_id, []):  # get allowed
            m = models_cache.get(mid)
            if m is None:
                continue
            if int(m.get("HP_CUR", 0)) <= 0:  # get allowed
                continue
            mx, my, mz = offset_to_cube(int(m["col"]), int(m["row"]))
            new_col, new_row = cube_to_offset(mx + dcx, my + dcy, mz + dcz)
            m["col"] = int(new_col)
            m["row"] = int(new_row)
            # Niveau d'ARRIVÉE résolu (§13.06), miroir du chemin par plan (`commit_move` →
            # `resolve_model_floor_level`). Une translation rigide peut sortir une figurine de
            # l'empreinte de son plancher : la laisser marquée à l'étage faisait ensuite lever
            # `floor_height_at` au resync, en plein commit et sur un état déjà à moitié muté.
            m["level"] = resolve_model_effective_level(
                game_state, m, int(new_col), int(new_row), int(require_key(m, "level"))
            )
    # Ancre d'abord (écrit entry.col/row ; l'empreinte, elle, y est déjà rétablie en union des
    # socles vivants — cf. la correction posée dans `update_units_cache_position`).
    update_units_cache_position(game_state, squad_id, norm_dest_col, norm_dest_row)
    # Puis les cartes par-figurine, POUR LA SEULE ESCOUADE MONO-FIGURINE. Au-dessus d'une
    # figurine, `update_units_cache_position` vient d'appeler `_recompute_squad_occupied_hexes`
    # lui-même : le refaire ici réécrivait à l'identique les cinq mêmes champs et la même
    # `occupation_map` (mesuré : +3,7 µs à 5 figurines, +7,5 µs à 11, soit ~27 % du coût de
    # cette fonction, à chaque move / charge / pile-in / consolidation).
    # La branche mono, elle, n'écrit ni `orientation_by_model` ni les cartes de niveau au-delà
    # de son unique mid : sans cet appel, un socle non rond pivoté était rendu par le front à
    # son ANCIENNE orientation (`orientation_by_model` a CE seul producteur).
    if len(require_key(game_state, "squad_models").get(squad_id, ())) <= 1:  # get allowed
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
    game_state: Dict[str, Any], model_id: str, col: int, row: int,
    level: Optional[int] = None, orientation: Optional[int] = None,
) -> None:
    """Met a jour la position d une figurine et propage a units_cache si ancre.

    Pour les escouades mono-figurine, met aussi a jour units_cache directement.
    Pour les multi-figurines (futures tranches), n update units_cache que si la
    figurine est l ancre courante (index minimum vivant).

    ``level`` (étages) : si fourni, écrit ``model["level"]``. None = ne touche PAS
    le niveau (déplacement horizontal pur). Le niveau de l'ancre est ensuite
    resynchronisé sur ``units_cache[squad]["level"]`` (invariant unité = ancre).

    ``orientation`` (pivot socle oval/carré, 0..5) : si fourni, écrit
    ``model["orientation"]`` AVANT le recalcul d'empreinte (le footprint oriente
    par-fig en depend). None = ne touche PAS l'orientation.
    """
    require_key(game_state, "models_cache")
    model = game_state["models_cache"].get(model_id)
    if model is None:
        raise KeyError(f"update_model_position: model {model_id} not in models_cache (dead/absent)")
    norm_col, norm_row = normalize_coordinates(int(col), int(row))

    # ─── TOUTES LES VALIDATIONS, AVANT LA MOINDRE ÉCRITURE ───────────────────────────────
    # Un refus doit laisser la figurine EXACTEMENT où elle était. Ces contrôles vivaient après
    # l'écriture de `col`/`row` : le garde §13.06 levait donc en laissant la figurine déplacée
    # sous son ANCIEN niveau d'étage — précisément l'état corrompu qu'il existe pour empêcher,
    # et le `game_state` PvP survit à la requête en 500, donc toutes les suivantes levaient à
    # leur tour. Le contrôle d'orientation avait le même défaut, sur `col`/`row` ET `level`.
    if level is not None:
        if isinstance(level, bool) or not isinstance(level, int) or level < 0:
            raise ValueError(f"update_model_position: level must be an int >= 0, got {level!r}")
    if orientation is not None:
        from engine.hex_utils import ORIENTATION_STEP_COUNT
        if (
            isinstance(orientation, bool)
            or not isinstance(orientation, int)
            or not (0 <= orientation < ORIENTATION_STEP_COUNT)
        ):
            raise ValueError(
                f"update_model_position: orientation must be an int in 0..{ORIENTATION_STEP_COUNT - 1}, got {orientation!r}"
            )
    # GARDE §13.06 : un niveau ÉCRIT est un niveau RÉSOLU. Une figurine marquée à l'étage dont
    # l'empreinte ne tient pas entièrement sur un plancher est un état corrompu — `floor_height_at`
    # lève ensuite, très loin de l'écriture fautive (500 du 2026-08-11 : le client perdait TOUT
    # son calque de LoS). Les écrivains passent par `place_model_at_effective_level`, qui résout ;
    # ce garde est là pour que le PROCHAIN écrivain casse ici, à la ligne fautive, au lieu de
    # produire l'état corrompu. Coût nul au sol : `resolve_model_floor_level` sort immédiatement
    # sous `level < 1`, et tout le jeu au sol passe donc par ce raccourci.
    # Mesuré sur la position VISÉE et l'orientation VISÉE, pas sur celles du cache : c'est l'état
    # que cet appel produirait, et rien n'est encore écrit à cet instant.
    if level is not None and level >= 1:
        _guard_orientation = (
            int(require_key(model, "orientation")) if orientation is None else int(orientation)
        )
        if resolve_model_effective_level(
            game_state, model, norm_col, norm_row, level, _guard_orientation
        ) != level:
            raise ValueError(
                f"update_model_position: niveau {level} NON RÉSOLU pour la figurine {model_id} "
                f"en ({norm_col},{norm_row}) orientation {_guard_orientation} — son empreinte ne "
                f"tient pas sur un plancher de ce niveau (§13.06). Utiliser "
                f"place_model_at_effective_level, qui résout le niveau avant d'écrire."
            )

    # ─── ÉCRITURES ───────────────────────────────────────────────────────────────────────
    model["col"] = norm_col
    model["row"] = norm_row
    if level is not None:
        model["level"] = level
    if orientation is not None:
        model["orientation"] = orientation

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
    # Sync du niveau de l'ancre (fig vivante d'index min) vers units_cache[squad]["level"] :
    # invariant "niveau de l'unité = niveau de l'ancre", cohérent avec la sync col/row ci-dessus.
    units_entry_lvl = game_state.get("units_cache", {}).get(squad_id)  # get allowed
    if units_entry_lvl is not None:
        for mid in game_state.get("squad_models", {}).get(squad_id, []):  # get allowed
            anchor_model = game_state["models_cache"].get(mid)
            if anchor_model is not None:
                units_entry_lvl["level"] = int(require_key(anchor_model, "level"))
                break
    _recompute_squad_cache(game_state, squad_id)
    # Choke-point LoS (a′) : écriture per-figurine → invalide les paires du squad, même si
    # l'ancre n'a pas bougé (pile-in par-figurine). En batch (commit_move), dédup avec l'appel
    # déjà émis par update_units_cache_position ci-dessus (1re old_pos conservée).
    _ue_los = require_key(game_state, "units_cache").get(squad_id)
    if _ue_los is not None:
        _touch_unit_los(game_state, squad_id, _ue_los.get("col"), _ue_los.get("row"))


def resolve_model_effective_level(
    game_state: Dict[str, Any],
    model: Dict[str, Any],
    col: int,
    row: int,
    requested_level: int,
    orientation: Optional[int] = None,
) -> int:
    """Niveau EFFECTIF (§13.06) d'une figurine posée en ``(col, row)`` — SOURCE UNIQUE.

    ``requested_level`` est un HINT (le niveau de la VUE au moment du drop) : la figurine n'est
    réellement à cet étage que si son empreinte tient ENTIÈREMENT sur un plancher de ce niveau,
    sinon elle est au SOL. Cette dérivation était réécrite à l'identique par chaque écrivain et
    chaque aperçu de plan — déploiement (×3), mouvement (×2), aperçu de tir — chacun relisant à
    la main ``BASE_SHAPE`` / ``BASE_SIZE`` / ``orientation`` / ``terrain_areas``. C'est ce
    recopiage qui a produit le 500 « figurine marquée à l'étage mais hors empreinte de plancher »
    du 2026-08-11 : l'aperçu de tir était le seul des six à ne pas résoudre.

    ``orientation`` = orientation VISÉE par le plan, ``None`` = celle de la figurine. Même
    résolution que `plan_entry_model_orientation` (l'orientation décide de la forme de
    l'empreinte, donc si le socle tient sur le plancher) : ``models_cache`` pose toujours
    ``orientation``, son absence est un cache corrompu et lève.
    """
    from engine.terrain_utils import resolve_model_floor_level

    return resolve_model_floor_level(
        int(col),
        int(row),
        require_key(model, "BASE_SHAPE"),
        require_key(model, "BASE_SIZE"),
        int(require_key(model, "orientation")) if orientation is None else int(orientation),
        int(requested_level),
        require_key(game_state, "terrain_areas"),
    )


def place_model_at_effective_level(
    game_state: Dict[str, Any],
    model_id: str,
    col: int,
    row: int,
    level: int,
    orientation: Optional[int] = None,
) -> int:
    """Pose une figurine d'un plan : résout le niveau (§13.06) PUIS écrit. Renvoie le niveau écrit.

    L'unique manière correcte d'écrire la position d'une figurine issue d'un PLAN (déploiement,
    move, aperçu) : le niveau porté par le plan n'est qu'un hint de vue, jamais un fait.
    Enchaîner `resolve_model_effective_level` puis `update_model_position` à la main — ce que
    faisait chaque écrivain — laisse l'invariant « le niveau écrit est un niveau résolu » tenir
    par la discipline de l'appelant ; ici il tient par construction.

    ``orientation`` (0..5) = orientation visée : elle sert d'abord à résoudre le niveau (elle
    oriente l'empreinte), puis elle est ÉCRITE. ``None`` = orientation inchangée, et la
    résolution utilise alors celle déjà portée par la figurine.

    ⚠️ Ne pas confondre avec `update_model_position(level=...)`, qui écrit le niveau tel quel :
    celui-ci n'est légitime que pour un niveau DÉJÀ résolu (cf. son garde) ou une écriture sans
    niveau (retrait hors table).
    """
    model = require_key(game_state, "models_cache").get(str(model_id))  # get allowed
    if model is None:
        raise KeyError(
            f"place_model_at_effective_level: model {model_id} not in models_cache (dead/absent)"
        )
    effective_level = resolve_model_effective_level(
        game_state, model, int(col), int(row), int(level), orientation
    )
    update_model_position(
        game_state, model_id, int(col), int(row),
        level=effective_level,
        orientation=None if orientation is None else int(orientation),
    )
    return effective_level


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


def _apply_deadly_demise(
    game_state: Dict[str, Any], squad_id: str,
    dead_col: int, dead_row: int, deadly_demise_value: Any,
) -> None:
    """Declenche la regle Deadly Demise §24.08 pour un modele venant d etre detruit.

    Jet D6 UNIQUE par modele detruit. Sur 6 : chaque unite a ≤6" subit X blessures
    mortelles (X = deadly_demise_value, int ou expression de de comme « D3 »). Si X est
    aleatoire, jet SEPARE par unite (PDF : « roll separately for each unit within 6" »).
    Resolution APRES l emergency disembark (PDF §24.08 exemple). Tag [DEADLY DEMISE].
    """
    import random
    import math
    d6_roll = random.randint(1, 6)
    turn = game_state["turn"]
    phase = game_state.get("phase", "")

    if d6_roll < 6:
        # Jet raté : un seul log "no effect", aucun jet de dé supplémentaire.
        append_action_log(game_state, {
            "type": "deadly_demise",
            "unitId": str(squad_id),
            "sourceUnitId": str(squad_id),
            "d6Roll": d6_roll,
            "deadlyDemiseWounds": 0,
            "turn": turn,
            "phase": phase,
            "player": -1,
            "deadlyDemiseDetails": [],
        })
        return

    units_cache = require_key(game_state, "units_cache")
    ish = int(require_key(game_state, "inches_to_subhex"))
    radius = 6 * ish
    _is_hex = geometry_is_hex(game_state)

    def _dist(u_col: int, u_row: int) -> float:
        if _is_hex:
            return float(calculate_hex_distance(dead_col, dead_row, u_col, u_row))
        return math.sqrt((dead_col - u_col) ** 2 + (dead_row - u_row) ** 2)

    # Toutes les unites (y compris l unite source si elle a encore des figs) dans les 6".
    for uid, uentry in list(units_cache.items()):
        u_col = int(uentry.get("col", -1))
        u_row = int(uentry.get("row", -1))
        if u_col < 0 or u_row < 0:
            continue
        if _dist(u_col, u_row) > radius:
            continue
        # X peut etre aleatoire : resolu SEPAREMENT par unite.
        x_wounds = int(resolve_dice_value(deadly_demise_value, f"deadly_demise_{squad_id}_{uid}"))
        _dd_details: List[Dict[str, Any]] = []
        append_action_log(game_state, {
            "type": "deadly_demise",
            "unitId": str(uid),
            "sourceUnitId": str(squad_id),
            "d6Roll": d6_roll,
            "deadlyDemiseWounds": x_wounds,
            "col": u_col,
            "row": u_row,
            "turn": turn,
            "phase": phase,
            "player": int(uentry.get("player", -1)),
            "deadlyDemiseDetails": _dd_details,
        })
        if x_wounds > 0:
            allocate_mortal_wounds(game_state, str(uid), x_wounds, True, _dd_details)


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
    valid_reasons = (
        "combat", "coherency_removal", "deployment_no_space", "hazard",
        # 20.04 — « At the end of the third battle round … all strategic reserves units that
        # have not made one or more ingress moves are destroyed. » Règle de jeu, pas erreur.
        "strategic_reserves_timeout",
    )
    if reason not in valid_reasons:
        raise ValueError(f"destroy_model: invalid reason {reason!r}, expected one of {valid_reasons}")

    model = game_state["models_cache"].get(model_id)
    if model is None:
        raise KeyError(f"destroy_model: model {model_id} not in models_cache (already dead?)")

    squad_id = str(model["squad_id"])
    old_col = int(model["col"])
    old_row = int(model["row"])
    # §24.08 DEADLY DEMISE : lire la valeur de la capacite AVANT suppression (units_cache peut
    # disparaitre si c est la derniere figurine). La cle est posee par le chantier 06 sur chaque
    # unite concernee ; absente sur les unites ordinaires = regle inactive, aucun jet.
    _deadly_demise_val = (game_state["units_cache"].get(squad_id) or {}).get("deadly_demise")

    # 1. Retire du models_cache.
    del game_state["models_cache"][model_id]
    # 2. Retire de squad_models (preserve l ordre des autres figurines).
    squad_list = game_state["squad_models"].get(squad_id)
    if squad_list is not None and model_id in squad_list:
        squad_list.remove(model_id)
    # F2 fix (audit) : recalcule occupied_hexes apres retrait de la fig
    _recompute_squad_occupied_hexes(game_state, squad_id)
    # Choke-point LoS (constat 5) : la mort d'une figurine réduit le footprint du squad →
    # invalider ses paires. Id-based, valable même si l'ancre ne bouge pas / squad supprimé.
    _touch_unit_los(game_state, squad_id, old_col, old_row)
    # Regle 19.04 : la mort d une figurine peut eteindre une SOURCE de regle d unite — le
    # dernier bodyguard (les regles du datasheet de l escouade tombent, le leader survivant
    # garde les siennes) ou la derniere figurine d un leader/support (sa regle quitte l unite).
    # Recalcul ici, apres le retrait de models_cache/squad_models et AVANT les `return`
    # anticipes plus bas : le vivant est deja a jour, et une unite entierement detruite doit
    # elle aussi voir ses regles s eteindre.
    if reason == "combat":
        # Tuee PAR UNE ATTAQUE : la source garde son effet jusqu a la fin des attaques de
        # l unite attaquante (19.04, derniere clause). La fenetre vit DANS l allocation en
        # cours, donc elle se referme d elle-meme a `_finalize_manual_allocation` — pas d etat
        # en sursis capable de survivre a l activation.
        _grace_alloc = _attack_allocation_in_progress(game_state)
        if _grace_alloc is not None:
            _grace_alloc.setdefault("rule_sources_in_grace", []).append({
                "squad_id": squad_id,
                "attached_from": (
                    str(model["attached_from"]) if "attached_from" in model else None
                ),
            })
    recompute_unit_rules_in_effect(game_state, squad_id)

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    phase = game_state.get("phase", "?")
    add_debug_file_log(
        game_state,
        f"[MODEL DESTROY] E{episode} T{turn} {phase} model_id={model_id} squad={squad_id} "
        f"pos=({old_col},{old_row}) reason={reason}"
    )
    # Événement explicite dans action_logs → step.log, pour TOUTES les causes de mort.
    # Sans cet événement, une figurine peut disparaître de [MODELS:] d'une action SUIVANTE
    # sans aucun signal intermédiaire visible (root cause : [MODELS:] est lu LIVE au flush,
    # après que les effets ont modifié occupied_hexes_by_model). L'event "dead" permet à
    # l'analyzer et à l'utilisateur de tracer chaque mort par modèle+raison explicitement.
    _uc_player = (game_state.get("units_cache") or {}).get(squad_id, {}).get("player")  # get allowed
    append_action_log(game_state, {
        "type": "dead",
        "model_id": model_id,
        "unitId": squad_id,
        "reason": reason,
        "turn": turn,
        "phase": phase,
        "player": _uc_player,
        "col": old_col,
        "row": old_row,
    })

    # §24.08 DEADLY DEMISE — APRES l emergency disembark (PDF §24.08 exemple), AVANT la cascade
    # qui retire l escouade. La position (old_col, old_row) est celle du modele juste detruit.
    if _deadly_demise_val is not None:
        _apply_deadly_demise(game_state, squad_id, old_col, old_row, _deadly_demise_val)

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
# MULTI-MODEL MOVEMENT PLAN (squad_multi_figurines.md PR2 2a)
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


def _move_spatial_cache(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Cache par-etat des ensembles spatiaux du move (cellules interdites, transit, champs
    geodesiques), partage par les DEUX cotes de l'invariant « masque ⊆ executable ».

    Motif : `explain_move_plan_rejection` reconstruit ces ensembles a CHAQUE cellule candidate,
    alors qu'ils ne dependent que de l'etat, pas de la destination. Mesure sur
    `test_move_mask_is_executable` (4 212 validations) : 352 s de BFS geodesique + 49 s de
    construction d'ensembles, pour quelques dizaines de valeurs distinctes.

    La CLE est un FINGERPRINT LU de l'etat reel — jamais un compteur de version. Un compteur a
    deja cause une regression masque⊆executable (§0.18) : un chemin d'ecriture de position ne
    le bumpe pas, si bien qu'un cache perime etait servi. Le fingerprint capture tout ce dont
    ces ensembles dependent :
      - position ET niveau de CHAQUE figurine vivante (occupation amie/ennemie, transit) ;
      - phase (le cache `enemy_adjacent` est par-phase) ;
      - contenu des zones d'engagement ennemies (elles derivent des positions, mais le chemin
        d'override reactif les reecrit hors de ce derive — on les lit donc directement) ;
      - drapeau `battle_shocked` de chaque escouade : l'exemption Desperate Escape (09.07) retire
        les figurines ennemies du transit, et ce drapeau bascule SANS qu'une figurine bouge
        (`force_battle_shock`, test de commandement 01.07). Sans lui, le transit memoise restait
        celui d'avant le test pendant que le pool par-figurine, lui, recalcule — soit exactement
        la divergence masque/execution que ce cache existe pour ne pas creer.
    Les murs et les toggles de traversee sont statiques : hors fingerprint.

    Tout changement de fingerprint jette le cache entier — il ne grossit donc pas au fil de la
    partie. Les ensembles sont renvoyes PAR REFERENCE : ne pas les muter (meme contrat qu'avant).
    """
    models_cache = require_key(game_state, "models_cache")
    ez_fp = tuple(
        (_k, hash(frozenset(_v)))
        for _k, _v in sorted(game_state.items())
        if isinstance(_k, str) and _k.startswith("enemy_adjacent_hexes_player_")
    )
    fp = (
        str(game_state.get("phase", "")),  # get allowed (phase absente = etat non initialise)
        hash(tuple(sorted(
            # ORIENTATION incluse : elle change l'EMPREINTE d'un socle non rond sans changer son
            # ancre. Un commit qui ne fait que pivoter (`update_model_position(..., orientation=)`
            # à col/row inchangés) laissait donc ce fingerprint identique — et, pire,
            # `update_enemy_adjacent_caches_after_unit_move` sort tôt sur `old == new`, donc
            # `ez_fp` ne bougeait pas non plus. Tous les ensembles mémoïsés ici (cellules
            # interdites, transit, masque EZ) servaient alors l'empreinte D'AVANT le pivot.
            (str(_mid), int(_m["col"]), int(_m["row"]), int(_m.get("level", 0)),  # get allowed
             int(_m.get("orientation", 0)))  # get allowed (socle rond non orienté)
            for _mid, _m in models_cache.items()
        ))),
        ez_fp,
        # `get` : l'absence du drapeau n'est PAS masquee ici — le seul lecteur du transit
        # (`build_move_transit_blocked`) le lit en `require_key` et leve. Un fingerprint qui
        # leverait rendrait tout le cache tributaire d'unites hors perimetre du move.
        # Seul l'ENSEMBLE des unites shockees discrimine le transit : un frozenset s'en tient a
        # celles-la (vide au cas courant) la ou un tuple trie payait un tri de toutes les unites
        # a chaque entree du cache — plusieurs dizaines de fois par preview.
        hash(frozenset(
            str(_u.get("id", ""))  # get allowed
            for _u in game_state.get("units", [])  # get allowed (etat non initialise = pas d'unite)
            if _u.get("battle_shocked", False)  # get allowed
        )),
    )
    holder = game_state.get("_move_spatial_cache")  # get allowed (absent au 1er appel)
    if holder is None or holder["fp"] != fp:
        holder = {"fp": fp, "blocked": {}, "transit": {}, "geo": {}, "eucl": {}}
        game_state["_move_spatial_cache"] = holder
    return holder


#: Identite hachable d'une GEOMETRIE DE SOCLE : (forme, taille normalisee, orientation).
#: `base_size_cache_key` est indispensable — un socle oval porte une LISTE, non hachable.
#: Cle de regroupement des figurines partout ou les cellules interdites dependent du socle pose
#: (`move_enemy_ez_forbidden_cells` et ses deux consommateurs).
MoveGeomKey = Tuple[str, Any, int]


def move_geom_key(entry: Dict[str, Any]) -> MoveGeomKey:
    """Cle de geometrie de socle d'une entree `models_cache`/`units_cache`. UN seul constructeur.

    Le triplet etait re-epele a la main partout ou il sert (regroupement des figurines de
    l'erosion, comparaison de socle, cles de cache) : un 4e composant devait alors etre ajoute
    dans autant d'endroits, et un oubli confondait silencieusement deux geometries distinctes.
    `orientation` absent = 0 (socle rond, non oriente).
    """
    from engine.hex_utils import base_size_cache_key
    return (
        str(require_key(entry, "BASE_SHAPE")),
        base_size_cache_key(require_key(entry, "BASE_SIZE")),
        int(entry.get("orientation", 0)),  # get allowed (socle rond non oriente)
    )


def move_enemy_ez_forbidden_cells(
    game_state: Dict[str, Any],
    player: int,
    base_shape: str,
    base_size: Any,
    orientation: int,
) -> Set[Tuple[int, int]]:
    """Cellules d'ANCRE interdites à UNE figurine par la zone d'engagement ennemie (03.04).

    « Ancre » = la case où l'on pose la figurine ; l'empreinte de son socle est DÉJÀ prise en
    compte dans le résultat. Le set dépend donc de la GÉOMÉTRIE DU SOCLE, pas seulement du camp :
    deux figurines de socles différents n'ont pas les mêmes cases interdites face aux mêmes
    ennemis. C'est ce que le prédicat précédent ignorait (cf. ci-dessous).

    Même sémantique que ``move_anchor_violates_engagement_clearance``, la primitive que le POOL
    d'ancre interroge déjà — d'où la métrique résolue ici plutôt que supposée :
      - ``hex``       : ancre interdite ssi une case de l'empreinte tombe dans le set pré-dilaté
        ``enemy_adjacent_hexes_player_N`` (branche ``metric == "hex"`` de la primitive) ;
      - ``euclidean`` : ``_compute_mover_ez_forbidden_mask``, écart bord-à-bord continu, mesuré
        PAR FIGURINE ennemie (``occupied_hexes_by_model``), qui est la SOURCE UNIQUE du masque
        d'engagement du pool PvP comme du pool IA vectorisé.

    ⚠️ DÉFAUT CORRIGÉ ICI (09.05/09.06/09.07, « AFTER MOVING: your unit must be unengaged »).
    ``build_move_blocked_cells_by_level`` testait la cellule d'ancre de chaque figurine contre le
    set hex dilaté brut, ce qui rate deux choses à la fois : le socle du MOVER (rayon non compté)
    et la métrique réelle du plateau (euclidienne dès ×5). Le pool d'ancre, lui, filtre bien en
    euclidien — mais pour UNE base posée à l'ancre candidate, donc les SŒURS du bloc rigide
    n'étaient contrôlées que par le set hex. Mesuré (E3 T3, journal du 2026-08-09) : l'escouade
    105 finit un move NORMAL avec ``105#5`` et ``105#6`` dans l'EZ de l'unité 1, et le moteur se
    contredit dans le même tour — la validation du move accepte, puis
    ``fight_v11_is_pile_in_eligible`` rend l'escouade éligible au pile-in par la seule branche
    « It is engaged » (12.03), sans charge déclarée.

    Le masque et l'exécution lisent tous deux ce set (via ``build_move_blocked_cells_by_level``) :
    ils ne peuvent pas diverger. Mémoïsé par ``_move_spatial_cache`` (même contrat de
    non-mutation : lecture pure, ne pas muter le set rendu).

    NON couvert, ici comme dans le prédicat remplacé : le gate VERTICAL de l'engagement 3D
    (03.04, 5"). Les deux formes sont 2D — le set hex dilaté l'était déjà — donc ce correctif ne
    change rien à cette dimension. À étages, l'EZ du move reste plus restrictive que celle du
    combat (``entries_in_engagement_zone``, elle, applique le gate) : écart préexistant, sans
    effet tant que le move de l'IA ne monte pas.
    """
    from engine.hex_utils import base_size_cache_key, precompute_footprint_offsets
    from engine.spatial_relations import engagement_distance_metric

    _cache = _move_spatial_cache(game_state).setdefault("ez", {})
    _ck = (int(player), str(base_shape), base_size_cache_key(base_size), int(orientation))
    _hit = _cache.get(_ck)
    if _hit is not None:
        return _hit

    metric = engagement_distance_metric(game_state)
    board_cols = int(require_key(game_state, "board_cols"))
    board_rows = int(require_key(game_state, "board_rows"))
    off_even, off_odd = precompute_footprint_offsets(base_shape, base_size, int(orientation))
    forbidden: Set[Tuple[int, int]] = set()

    if metric == "hex":
        # Ancre interdite ssi SON EMPREINTE touche le set dilaté : on remonte des cases interdites
        # vers les ancres qui les couvrent (offsets soustraits), en respectant la parité de colonne
        # dont dépend l'empreinte odd-q.
        enemy_er = require_key(game_state, f"enemy_adjacent_hexes_player_{int(player)}")
        for offs, want_even in ((off_even, True), (off_odd, False)):
            for dc, dr in offs:
                for ec, er in enemy_er:
                    ac, ar = int(ec) - int(dc), int(er) - int(dr)
                    if ((ac & 1) == 0) != want_even:
                        continue
                    if 0 <= ac < board_cols and 0 <= ar < board_rows:
                        forbidden.add((ac, ar))
    elif metric == "euclidean":
        import numpy as np
        from engine.phase_handlers.movement_handlers import _compute_mover_ez_forbidden_mask
        units_cache = require_key(game_state, "units_cache")
        # Liste ennemie EXPLICITE : `_compute_mover_ez_forbidden_mask(enemy_items=None)` rend un
        # masque VIDE en euclidien (`enemy_items if ... else []`) — un no-op silencieux, pas une
        # erreur. Ne jamais lui laisser dériver la liste.
        enemy_items = list(enemy_entries_on_battlefield(units_cache, int(player)))
        mover = {
            "id": f"_ez_probe_p{int(player)}",
            "BASE_SHAPE": base_shape,
            "BASE_SIZE": base_size,
            "orientation": int(orientation),
        }
        mask = _compute_mover_ez_forbidden_mask(
            game_state, mover, enemy_items, int(get_engagement_zone(game_state)),
            board_cols, board_rows,
        )
        forbidden = {(int(c), int(r)) for c, r in np.argwhere(mask)}
    else:
        raise ValueError(f"Invalid engagement metric {metric!r}, expected 'hex' or 'euclidean'")

    _cache[_ck] = forbidden
    return forbidden


def build_move_blocked_cells_by_level(
    game_state: Dict[str, Any],
    squad_id: str,
    player: int,
    levels: "Any",
    constraints: Dict[str, Any],
    base_shape: str,
    base_size: Any,
    orientation: int,
) -> Dict[int, List[Tuple[str, Set[Tuple[int, int]]]]]:
    """SOURCE UNIQUE du predicat de cellule d'un move — cellules INTERDITES, par niveau.

    Consommee par les DEUX cotes de l'invariant « masque ⊆ executable » :
      - `validate_move_plan`, qui teste chaque figurine d'un plan deja construit ;
      - `erode_move_pool_by_squad_block`, qui erode le pool d'ancre par le bloc AVANT que
        le masque ne soit publie.
    Les deux DOIVENT lire le meme predicat : le dupliquer rouvrirait la classe de bug
    « masque/execution » (decision de design n°2 — « Interdit de dupliquer le check »).

    Contraintes couvertes (toutes des proprietes de CELLULE, donc erodables) :
      - `allow_collisions=False` : cellules occupees par les AUTRES escouades AU MEME NIVEAU
        (deux figs a des etages differents ne se chevauchent pas) ;
      - `allow_walls=False` : murs (verticaux, prolonges a tous les niveaux) ;
      - `forbid_enemy_er=True` : zone d'engagement ennemie, via `move_enemy_ez_forbidden_cells`.
    NON couvertes ici car elles ne sont PAS des proprietes de cellule : `budget_per_model`
    (distance depuis l'origine de CHAQUE figurine) et `require_coherency` (positions
    relatives) — cf. `erode_move_pool_by_squad_block` pour pourquoi elles n'ont pas besoin
    de l'etre. Les bornes du plateau ne sont pas non plus ici : chaque appelant les teste
    avant l'appartenance (pas de set a materialiser pour tout le plateau).

    Retourne, par niveau, la LISTE des sets interdits — jamais leur union : une cellule est
    interdite ssi elle appartient a l'un d'eux. Ne PAS fusionner ici. L'union coute une copie
    de `wall_hexes` (~1100 cellules) a chaque appel, ce qui est du pur gaspillage pour
    `validate_move_plan`, appele avec quelques figurines (mesure : +6% par appel). Le consommateur qui balaye des
    milliers de candidates (`erode_move_pool_by_squad_block`) peut, lui, materialiser l'union
    une fois s'il y trouve son compte — c'est SON arbitrage, pas celui du helper.

    Les sets sont renvoyes PAR REFERENCE (lecture pure) : ne pas les muter. Le resultat est
    memoise par `_move_spatial_cache` (meme contrat de non-mutation, etendu aux listes).

    `base_shape` / `base_size` / `orientation` : GEOMETRIE DU SOCLE des figurines concernees.
    Elle entre ici parce que l'EZ ennemie depend du socle qu'on pose (cf.
    `move_enemy_ez_forbidden_cells`) — murs et occupation, eux, n'en dependent pas. Un appelant
    dont l'escouade porte plusieurs geometries (personnage attache a socle plus grand) DOIT
    appeler une fois par geometrie : passer celle de l'ancre pour tout le monde rendrait a une
    figurine les cases interdites d'une AUTRE, ce qui est exactement la classe de bug corrigee.
    """
    _levels_key = tuple(sorted(int(_lv) for _lv in levels))
    _cache = _move_spatial_cache(game_state)["blocked"]
    from engine.hex_utils import base_size_cache_key
    _ck = (
        str(squad_id), int(player), _levels_key,
        bool(constraints["allow_walls"]),
        bool(constraints["forbid_enemy_er"]),
        bool(constraints["allow_collisions"]),
        str(base_shape), base_size_cache_key(base_size), int(orientation),
    )
    _hit = _cache.get(_ck)
    if _hit is not None:
        return _hit

    # Murs : ancres où le SOCLE chevauche un mur, jamais `wall_hexes` brut. Ces sets sont testés
    # sur l'ANCRE de chaque figurine (cf. `validate_move_plan`) et l'EZ ennemie, juste en dessous,
    # est déjà socle-consciente pour cette raison exacte. Le mur était le DERNIER terme mesuré
    # comme une cellule nue, donc le seul à pouvoir accepter une ancre que la traversée refuse.
    wall_anchors = wall_blocked_anchors(
        game_state,
        {"BASE_SHAPE": base_shape, "BASE_SIZE": base_size, "orientation": int(orientation)},
    )
    static_blocked: List[Tuple[str, Set[Tuple[int, int]]]] = []
    if not constraints["allow_walls"] and wall_anchors:
        static_blocked.append(("mur", cast(Set[Tuple[int, int]], wall_anchors)))
    if constraints["forbid_enemy_er"]:
        enemy_er = move_enemy_ez_forbidden_cells(
            game_state, int(player), base_shape, base_size, int(orientation)
        )
        if enemy_er:
            static_blocked.append(("ER ennemie", enemy_er))

    out: Dict[int, List[Tuple[str, Set[Tuple[int, int]]]]] = {}
    for lv in _levels_key:
        blocked = list(static_blocked)
        if not constraints["allow_collisions"]:
            blocked.append((
                "occupation d'une autre escouade",
                build_occupied_positions_set(game_state, exclude_unit_id=squad_id, level=int(lv)),
            ))
        out[int(lv)] = blocked
    _cache[_ck] = out
    return out


def squad_traverses_models_17_01(
    game_state: Dict[str, Any], squad_id: str, model: Optional[Dict[str, Any]] = None
) -> bool:
    """17.01 s applique-t-il au deplacement en cours de ce mobile ?

    « Each time you make a normal or advance move with a unit, MONSTER/VEHICLE models in that
    unit can be moved through friendly and enemy models (excluding other MONSTER/VEHICLE
    models). » Trois conditions, et les trois sont dans la regle :

    - PHASE DE MOUVEMENT. Le pile-in et la consolidation (12.03) sont des deplacements de la
      phase de combat : 17.01 ne les couvre pas. Meme garde de phase, et pour la meme raison,
      que l exemption Desperate Escape ci-dessous.
    - MOBILE NON ENGAGE. Dans la phase de mouvement, une escouade engagee ne peut faire QUE un
      fall-back (09.05/09.06 exigent `unengaged` pour le move normal et l advance), et le
      fall-back n est ni l un ni l autre — il a sa propre traversee, Desperate Escape.
    - FIGURINE MONSTER/VEHICLE, lue sur ses keywords PROPRES (`_model_is_monster_or_vehicle`,
      la meme primitive que le hazard 06.03) : l union 19.03 ferait passer une escouade
      d infanterie pour MONSTER des qu un character MONSTER y est attache.

    ``model`` fourni (pools par-figurine) : verdict EXACT, la regle etant par figurine. Absent
    (pools d ancre, qui ne connaissent que l escouade) : verdict d escouade, et une escouade
    MIXTE LEVE au lieu de rendre un pool faux. Aucune ne peut l etre aujourd hui — l attachement
    19.01 est reserve aux unites portant la regle `leader`, qu aucune M/V du registre ne porte —
    et c est exactement la garde que porte le jumeau analyzer (`monster_or_vehicle_by_unit`).
    """
    if str(game_state.get("phase", "")) != "move":  # get allowed (phase absente = non initialisé)
        return False
    if _squad_is_in_enemy_er(game_state, str(squad_id)):
        return False
    if model is not None:
        return _model_is_monster_or_vehicle(model)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    statuses = {
        _model_is_monster_or_vehicle(m)
        for m in (
            models_cache.get(mid)  # get allowed (figurine morte = retiree du cache)
            for mid in squad_models.get(str(squad_id), [])  # get allowed (contrat du masque)
        )
        if m is not None
    }
    if len(statuses) > 1:
        raise ValueError(
            f"Escouade {squad_id!r} : ses figurines melangent des datasheets MONSTER/VEHICLE et "
            "non-MONSTER/VEHICLE. L exemption de traversee 17.01 se lit par figurine ; un pool "
            "d ancre ne peut plus rendre un verdict pour toute l escouade."
        )
    return statuses == {True}


def build_move_traversal_blocked(
    game_state: Dict[str, Any],
    squad_id: str,
    player: int,
    level: int,
    model: Optional[Dict[str, Any]] = None,
) -> Tuple[Set[Tuple[int, int]], Set[Tuple[int, int]]]:
    """``(cellules ENNEMIES, cellules AMIES)`` qui bloquent le TRANSIT de ce mobile.

    SOURCE UNIQUE de la question « cette figurine bloque-t-elle le passage ? ». Elle etait
    ecrite SEPT fois — six dans `movement_handlers` (pool NumPy, pool d ancre euclidien, pool
    par-figurine, BFS par-figurine, descente et montee d etage) et une ici — toutes sous la
    meme forme `if not (desperate_escape or thru_enemy): obstacles |= enemy_occupied`. Trois
    regles y cohabitaient deja (toggles de config, Desperate Escape 09.07, niveau) ; 17.01 en
    faisait une quatrieme, donc sept occasions de diverger. Un site oublie ne se voit pas : il
    produit un masque plus large que l executable, et l ecart ne remonte qu au gym, loin de sa
    cause.

    Ce que la fonction NE fait PAS : le placement. 17.01 autorise a TRAVERSER, pas a s arreter
    sur une figurine — la destination reste filtree par `build_move_blocked_cells_by_level` et
    `is_footprint_placement_valid`, qui ne changent pas. Les murs non plus n en font pas partie :
    ils bloquent TOUJOURS, aucun appelant n a de raison de les rendre optionnels.

    Lecture pure. Resultat memoise par `_move_spatial_cache` (renvoye par reference).
    """
    _cache = _move_spatial_cache(game_state).setdefault("traversal", {})
    _ck = (str(squad_id), int(player), int(level), None if model is None else str(model.get("id")))  # get allowed
    _hit = _cache.get(_ck)
    if _hit is not None:
        return _hit

    from engine.phase_handlers.movement_handlers import _get_move_traversal_rules

    _thru_ez, thru_enemy, thru_friendly = _get_move_traversal_rules(game_state)
    # Desperate Escape : cf. `build_move_transit_blocked` pour la garde de phase.
    desperate_escape = (
        str(game_state.get("phase", "")) == "move"  # get allowed (phase absente = non initialisé)
        and squad_is_battle_shocked_in_enemy_er(game_state, str(squad_id))
    )
    mv_traversal = squad_traverses_models_17_01(game_state, str(squad_id), model)

    enemy_all = build_enemy_occupied_positions_set(
        game_state, current_player=int(player), level=int(level)
    )
    if desperate_escape or thru_enemy:
        enemy_blocked: Set[Tuple[int, int]] = set()
    elif mv_traversal:
        # « excluding other MONSTER/VEHICLE models » : l exemption s arrete la, et seulement la.
        enemy_blocked = _monster_or_vehicle_occupied_positions(
            game_state, level=int(level), keep=lambda p: p != int(player)
        )
    else:
        enemy_blocked = enemy_all

    if thru_friendly:
        friendly_blocked: Set[Tuple[int, int]] = set()
    else:
        friendly_all = build_occupied_positions_set(
            game_state, exclude_unit_id=str(squad_id), level=int(level)
        ) - enemy_all
        if mv_traversal:
            friendly_blocked = _monster_or_vehicle_occupied_positions(
                game_state, level=int(level), keep=lambda p: p == int(player),
                exclude_unit_id=str(squad_id),
            ) - enemy_all
        else:
            friendly_blocked = friendly_all

    _cache[_ck] = (enemy_blocked, friendly_blocked)
    return _cache[_ck]


def _monster_or_vehicle_occupied_positions(
    game_state: Dict[str, Any],
    *,
    level: int,
    keep: "Any",
    exclude_unit_id: Optional[str] = None,
) -> Set[Tuple[int, int]]:
    """Empreintes des seules FIGURINES MONSTER/VEHICLE, au niveau donne, cote(s) retenu(s).

    Filtre par FIGURINE et non par escouade : 17.01 exclut « other MONSTER/VEHICLE models »,
    pas « les unites qui en contiennent ». ``keep(player) -> bool`` choisit le camp.
    """
    units_cache = require_key(game_state, "units_cache")
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    occupied: Set[Tuple[int, int]] = set()
    for uid, entry in entries_on_battlefield(units_cache):
        if exclude_unit_id is not None and str(uid) == str(exclude_unit_id):
            continue
        if not keep(int(require_key(entry, "player"))):
            continue
        for mid in squad_models.get(str(uid), []):  # get allowed
            m = models_cache.get(mid)  # get allowed (figurine morte = retiree du cache)
            if m is None or int(require_key(m, "level")) != int(level):
                continue
            if not _model_is_monster_or_vehicle(m):
                continue
            occupied |= compute_candidate_footprint(int(m["col"]), int(m["row"]), m, game_state)
    return occupied


def build_move_transit_blocked(
    game_state: Dict[str, Any], squad_id: str, player: int, level: int
) -> Set[Tuple[int, int]]:
    """Cellules INFRANCHISSABLES EN TRANSIT pour le BFS géodésique par-figurine du move sol.

    Miroir EXACT des obstacles de pas du pool d'ancre sol
    (``movement_build_valid_destinations_pool``, chemin ``is_single_hex`` hex) : murs TOUJOURS,
    puis figs ennemies / amies / bande d'EZ ennemie selon les toggles ``config["move"]``
    (``_get_move_traversal_rules``) et l'exemption Desperate Escape (09.07). Défauts du jeu :
    ennemis bloquent, amies traversables, bande d'EZ traversable — donc en pratique
    ``murs ∪ ennemis``, et ``murs`` seuls pour une escouade battle-shocked qui fuit.

    C'est la définition de trajet légal (règle 03, distance de CHEMIN) partagée par les DEUX
    côtés de l'invariant « masque ⊆ exécutable » sur le budget : l'érosion du pool
    (``erode_move_pool_by_squad_block``) et la validation d'un plan (``explain_move_plan_
    rejection``). Les dupliquer rouvrirait la classe de bug masque/exécution.

    La destination (occupation, EZ) n'est PAS filtrée ici : elle l'est par
    ``build_move_blocked_cells_by_level``. Ce set ne borne QUE l'atteignabilité du chemin.
    Lecture pure. Résultat mémoïsé par ``_move_spatial_cache`` (renvoyé par référence).
    """
    from engine.phase_handlers.movement_handlers import _get_move_traversal_rules

    _cache = _move_spatial_cache(game_state)["transit"]
    _ck = (str(squad_id), int(player), int(level))
    _hit = _cache.get(_ck)
    if _hit is not None:
        return _hit

    thru_ez, _thru_enemy, _thru_friendly = _get_move_traversal_rules(game_state)
    # Les figurines bloquantes viennent de `build_move_traversal_blocked` — toggles de config,
    # Desperate Escape (09.07) et exemption M/V (17.01) y sont appliqués UNE fois, pour les sept
    # sites qui posaient la question chacun de leur côté.
    _enemy_blocked, _friendly_blocked = build_move_traversal_blocked(
        game_state, str(squad_id), int(player), int(level)
    )
    transit: Set[Tuple[int, int]] = set(game_state.get("wall_hexes", set()))  # get allowed
    transit |= _enemy_blocked
    transit |= _friendly_blocked
    # La bande d'EZ, elle, reste ici : elle ne dépend d'aucune figurine bloquante mais du cache
    # d'adjacence ennemie, et 17.01 ne la concerne pas — traverser une figurine n'autorise pas à
    # traverser une zone d'engagement.
    desperate_escape = (
        str(game_state.get("phase", "")) == "move"  # get allowed (phase absente = non initialisé)
        and squad_is_battle_shocked_in_enemy_er(game_state, str(squad_id))
    )
    if not (desperate_escape or thru_ez):
        transit |= require_key(game_state, f"enemy_adjacent_hexes_player_{int(player)}")
    _cache[_ck] = transit
    return transit


def geodesic_move_reach(
    start_col: int,
    start_row: int,
    budget: int,
    transit_blocked: Set[Tuple[int, int]],
    board_cols: int,
    board_rows: int,
) -> Dict[Tuple[int, int], int]:
    """Champ géodésique HEX (distance de CHEMIN en pas) depuis ``(start_col, start_row)``,
    borné à ``budget`` pas, ``transit_blocked`` (murs + obstacles de traversée) infranchissable.

    BFS centre-à-centre, ``get_hex_neighbors`` (parity-aware) — même voisinage et même
    traitement des murs que le pool d'ancre réactif (``if neighbor in blocked: continue``).
    Retourne ``{(col, row): distance}`` pour toute cellule atteignable en ``<= budget`` pas
    (la case de départ y figure à distance 0). Une cellule absente = injoignable dans le budget.
    Lecture pure.
    """
    from collections import deque

    start = (int(start_col), int(start_row))
    field: Dict[Tuple[int, int], int] = {start: 0}
    if budget <= 0:
        return field
    queue: "deque[Tuple[Tuple[int, int], int]]" = deque([(start, 0)])
    while queue:
        (cc, cr), cd = queue.popleft()
        if cd >= budget:
            continue
        nd = cd + 1
        for nc, nr in get_hex_neighbors(cc, cr):
            if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
                continue
            nb = (nc, nr)
            if nb in field:
                continue
            if nb in transit_blocked:
                continue
            field[nb] = nd
            queue.append((nb, nd))
    return field


# Le squad move rigide du gym atterrit TOUJOURS au SOL : en `read_only` le pool d'ancre
# retourne avant son bloc multi-niveaux (`movement_build_valid_destinations_pool`), donc toutes ses
# destinations sont des cases de niveau 0, et le coût vertical d'une figurine partant d'un étage est
# facturé au budget par `squad_descent_penalty_subhex` (§13.06). Les consommateurs du plan (pool,
# érosion, validation, mesure, commit) doivent donc raisonner sur CE niveau, pas sur le niveau
# d'ORIGINE des figurines. Sans cela (§0.34) : la figurine descendue restait marquée à l'étage
# (`floor_height_at` lève « hors empreinte de plancher ») et sa destination était testée contre
# l'occupation d'un AUTRE étage que celui où elle atterrit.
SQUAD_RIGID_MOVE_DESTINATION_LEVEL = 0


# --- Frontière de décodage des plans par-figurine (source unique) --------------
# Un plan est une liste d'entrées `[model_id, col, row, level(, orientation)]`. Le niveau est
# OBLIGATOIRE sur toute entrée PRÉSENTE : un plan muet est REFUSÉ, jamais complété. Historique :
# chaque destinataire inventait son propre niveau par défaut (0 pour le commit de charge, le niveau
# de VUE pour pile-in/consolidation, le niveau committé pour le move, None dans shared_utils) — une
# escouade à cheval sur deux étages devenait invalidable et restait bloquée dans le pool de pile-in.
# Une figurine ABSENTE du plan reste légitime (elle n'a pas bougé) : c'est le moteur qui la complète
# avec sa position ET son étage COURANTS, en aval, pas ce décodeur.
_PLAN_LEVEL_REQUIRED_MSG = (
    "un plan par-figurine porte TOUJOURS son étage : entrée attendue "
    "[model_id, col, row, level], niveau non nul-able. Aucun niveau n'est inventé (§13.06)"
)


def _parse_plan_entry(
    entry: Any, action_name: str, max_len: int
) -> Tuple[str, int, int, int, Optional[int]]:
    """Décode UNE entrée de plan en 5-uplet interne ``(mid, col, row, level, orientation|None)``."""
    if not isinstance(entry, (list, tuple)):
        raise ValueError(f"{action_name}: entrée de plan invalide {entry!r} — {_PLAN_LEVEL_REQUIRED_MSG}")
    seq = cast("Sequence[Any]", entry)
    if not (4 <= len(seq) <= max_len):
        raise ValueError(f"{action_name}: entrée de plan {entry!r} — {_PLAN_LEVEL_REQUIRED_MSG}")
    if seq[3] is None:
        raise ValueError(f"{action_name}: étage None dans {entry!r} — {_PLAN_LEVEL_REQUIRED_MSG}")
    level = int(seq[3])
    if level < 0:
        raise ValueError(f"{action_name}: étage négatif dans {entry!r} (level >= 0 requis)")
    return (str(seq[0]), int(seq[1]), int(seq[2]), level, plan_entry_orientation(seq))


def parse_model_plan(raw_plan: Any, *, action_name: str) -> List[Tuple[str, int, int, int]]:
    """Décode un plan par-figurine en 4-uplets stricts ``(model_id, col, row, level)``.

    Frontière UNIQUE : toute action porteuse d'un plan passe par ici (ou par
    ``parse_model_plan_with_orientation``), et les consommateurs en aval lisent ``entry[3]``
    sans condition. Lève sur toute entrée sans étage — cf. ``_PLAN_LEVEL_REQUIRED_MSG``.
    """
    if not isinstance(raw_plan, list):
        raise ValueError(f"{action_name}: plan doit être une liste, reçu {raw_plan!r}")
    return [
        (mid, col, row, level)
        for mid, col, row, level, _ori in (
            _parse_plan_entry(e, action_name, 4) for e in cast("List[Any]", raw_plan)
        )
    ]


def parse_model_plan_as_map(
    raw_plan: Any, *, action_name: str
) -> Dict[str, Tuple[int, int, int]]:
    """``parse_model_plan`` rendu sous forme de carte ``{model_id: (col, row, level)}``.

    Forme attendue par les aperçus par-figurine (plan provisoire du front : charge, pile-in,
    consolidation), qui indexent par figurine et non par position dans la liste.
    """
    return {mid: (col, row, level) for mid, col, row, level in parse_model_plan(raw_plan, action_name=action_name)}


def parse_model_plan_with_orientation(
    raw_plan: Any, *, action_name: str
) -> List[Tuple[str, int, int, int, Optional[int]]]:
    """Idem ``parse_model_plan``, avec l'orientation socle optionnelle en 5e élément.

    L'orientation reste OPTIONNELLE (``None`` = orientation inchangée) : contrairement au niveau,
    elle ne conditionne aucune éligibilité verticale — seul le move la porte (pivot molette).
    """
    if not isinstance(raw_plan, list):
        raise ValueError(f"{action_name}: plan doit être une liste, reçu {raw_plan!r}")
    from engine.hex_utils import ORIENTATION_STEP_COUNT

    parsed = [_parse_plan_entry(e, action_name, 5) for e in cast("List[Any]", raw_plan)]
    for mid, _c, _r, _lv, ori in parsed:
        if ori is not None and not (0 <= ori < ORIENTATION_STEP_COUNT):
            raise ValueError(
                f"{action_name}: orientation de {mid} hors 0..{ORIENTATION_STEP_COUNT - 1} ({ori})"
            )
    return parsed


def build_rigid_plan(
    anchor_dest_col: int,
    anchor_dest_row: int,
    squad_id: str,
    game_state: Dict[str, Any],
) -> Optional[List[Tuple[str, int, int, int]]]:
    """Translation rigide depuis l'ancre — Normal/Advance/Fall Back.

    L ancre = figurine vivante de plus petit index (cf. _recompute_squad_anchor).
    Toutes les figurines suivent le meme vecteur de translation, appliqué en coordonnees
    CUBE (miroir de deployment_build_squad_destinations_pool) : en offset odd-q, une
    translation a dx impair change la parite de colonne de chaque figurine et DEFORME le
    bloc (deux figs a distance 2 se retrouvent a distance 1).

    Returns list[(model_id, new_col, new_row, niveau_sol)] ou None si squad sans figurine vivante.
    Le 4e element est TOUJOURS `SQUAD_RIGID_MOVE_DESTINATION_LEVEL` : ce move atterrit au sol (cf.
    la constante). L'omettre laissait `commit_move` conserver le niveau d'origine (« absence = garder
    le niveau courant ») et une figurine partie d'un etage restait marquee a l'etage hors de toute
    empreinte de plancher (§0.34).
    AUCUNE validation ici — voir validate_move_plan.
    """
    from engine.hex_utils import offset_to_cube, cube_to_offset

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
    ax, ay, az = offset_to_cube(anchor_origin_col, anchor_origin_row)
    bx, by, bz = offset_to_cube(dest_col, dest_row)
    dcx, dcy, dcz = bx - ax, by - ay, bz - az
    plan: List[Tuple[str, int, int, int]] = []
    for mid in alive_mids:
        m = models_cache[mid]
        mx, my, mz = offset_to_cube(int(m["col"]), int(m["row"]))
        new_col, new_row = cube_to_offset(mx + dcx, my + dcy, mz + dcz)
        plan.append((mid, int(new_col), int(new_row), SQUAD_RIGID_MOVE_DESTINATION_LEVEL))
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


def move_plan_distance_mode(
    game_state: Dict[str, Any], squad_id: str, metric: Optional[str] = None
) -> str:
    """GÉOMÉTRIE de la distance de move d'une escouade — `geodesic` | `cube` | `euclidean`.

    Source UNIQUE, partagée par la validation d'un plan (`explain_move_plan_rejection`) et par la
    comptabilisation de la distance parcourue (`move_plan_path_distances`). Ce ne sont pas des
    replis : ce sont trois géométries différentes, et les deux côtés DOIVENT mesurer la même.

      - `euclidean` — métrique euclidienne (PvP) : le trajet légal est any-angle (champ
        `_euclidean_move_field_for_model`), il contourne murs et figurines comme le géodésique.
      - `cube` — métrique hex + FLY actif (Take to the skies 21.03) : la traversée ignore murs et
        figurines, donc le trajet légal EST la ligne d'hexes, et sa longueur est la distance cube.
      - `geodesic` — métrique hex au sol : le trajet contourne murs et figurines → BFS.

    ⚠️ `cube` et `euclidean` ne sont PAS interchangeables (§0.34). Un pas d'hexagone vaut `1,5` en
    unités `_hex_center` vers l'est mais `sqrt(3) ≈ 1,732` vers le sud : convertir un budget en
    PAS vers un budget euclidien par `× 1,5` sous-estime de 15 % un trajet en colonne, et une
    destination validée à `distance cube <= budget` ressortait « injoignable » de la mesure
    euclidienne (`_euclidean_path_distance`).
    """
    from engine.phase_handlers.movement_handlers import (
        _fly_traversal_active,
        _move_distance_metric,
    )

    # `metric` explicite = le sélecteur de la phase qui pose la question. La CHARGE a le sien
    # (`_charge_distance_metric`, clés `distance_metric["charge"|"charge_gym"]`) et il est
    # INDÉPENDANT de celui du move dans `game_config.json` : quatre clés, quatre valeurs
    # possibles. Les lui imposer ici bornerait le plan de charge avec une géométrie pendant que
    # son pool et sa preview en utilisent une autre — exactement la rupture « masque ⊆
    # exécutable » que ce fichier passe son temps à empêcher. Défaut = métrique du move.
    _metric = _move_distance_metric(game_state) if metric is None else metric
    # Métrique AVANT l'unité (cf. érosion) : euclidien / non-hex → pas de lecture d'unité.
    if _metric != "hex":
        return "euclidean"
    _unit_obj = require_unit_by_id(game_state, str(squad_id))
    if _fly_traversal_active(game_state, _unit_obj, str(squad_id)):
        return "cube"
    return "geodesic"


# Bornes SUPÉRIEURES du budget d'un move, par type, en POUCES. Elles ne servent qu'à borner
# l'exploration du BFS géodésique quand le budget exact n'est pas reconstructible depuis
# `commit_move` (le jet d'Advance/de charge n'y est pas transmis). Borner PLUS LARGE ne change
# AUCUNE distance : la distance géodésique est une propriété du graphe, le budget ne limite que
# l'étendue explorée. C'est donc une optimisation de calcul, pas une approximation de règle.
MAX_ADVANCE_ROLL_INCHES_BOUND = 6   # 1D6

# Types de move de la PHASE DE MOUVEMENT — les seuls dont la distance parcourue est comptabilisée
# (cf. commit_move : les autres relèvent d'une autre géométrie).
MOVE_PHASE_MOVE_TYPES = ("normal", "advance", "fall_back")


def _move_distance_field_bound(
    game_state: Dict[str, Any], squad_id: str, move_type: str
) -> int:
    """Borne (subhex) pour le champ géodésique servant à MESURER la distance parcourue."""
    if move_type not in MOVE_PHASE_MOVE_TYPES:
        raise ValueError(
            f"_move_distance_field_bound: move_type {move_type!r} hors phase de mouvement — "
            f"sa distance se mesure avec une autre geometrie (cf. commit_move)"
        )
    # normal / fall_back : le budget EXACT est reconstructible -> même clé de mémoïsation que
    # la validation qui vient de tourner (cache chaud, aucun BFS supplémentaire).
    base = get_squad_move_budget(str(squad_id), game_state, "normal")
    if move_type == "advance":
        inches = int(require_key(game_state, "inches_to_subhex"))
        return base + MAX_ADVANCE_ROLL_INCHES_BOUND * inches
    return base


def geodesic_field_for_origin(
    game_state: Dict[str, Any],
    squad_id: str,
    player: int,
    origin: Tuple[int, int],
    level: int,
    budget: int,
) -> Dict[Tuple[int, int], int]:
    """Champ geodesique (cases -> cout en pas) atteignable depuis UNE origine, memoise dans l'etat.

    SOURCE UNIQUE des trois consommateurs du champ de trajet : la VALIDATION d'un plan
    (`explain_move_plan_rejection`), la MESURE de la distance parcourue (`move_plan_path_distances`)
    et la BORNE de la charge / du pile-in (`model_reach_predicate`). Les trois doivent voir
    exactement le meme atteignable — c'est l'invariant qui interdit qu'un plan valide ressorte
    « injoignable » de sa propre mesure (§0.34).

    Cet invariant tient a la FORME DE LA CLE de memoisation, qui a longtemps ete recopiee a la main
    aux trois endroits. Y ajouter une composante (les toggles de traversee, la semantique de niveau)
    a un seul site servait silencieusement aux deux autres un champ calcule pour un autre contexte.
    La cle vit donc ici, une fois.

    ``level`` est le niveau du TRAJET (niveau CIBLE du plan, pas celui d'origine) : une figurine qui
    descend chemine parmi les obstacles du sol.

    LE BUDGET N'EST PAS DANS LA CLE, et c'est deliberé : le champ rend `{cellule: cout en pas}`,
    donc un champ calcule pour 12 repond exactement pour tout budget <= 12 — il suffit de comparer
    le cout. Avec le budget dans la cle, l'observation (qui interroge toujours `CHARGE_MAX_ROLL`)
    et le commit (qui interroge le jet reel) calculaient DEUX BFS par figurine au lieu d'un.
    Mesure : 373 -> 261 us par figurine.

    CONTRAT DE L'APPELANT : le champ peut porter des cellules AU-DELA de son budget. Comparer
    `field.get(cell) <= budget`, jamais tester la seule appartenance.
    """
    o_col, o_row = int(origin[0]), int(origin[1])
    budget = int(budget)
    fields = _move_spatial_cache(game_state)["geo"]
    fkey = (str(squad_id), int(player), o_col, o_row, int(level))
    cached = fields.get(fkey)
    if cached is not None and cached[0] >= budget:
        return cached[1]
    field = geodesic_move_reach(
        o_col, o_row, budget,
        build_move_transit_blocked(game_state, str(squad_id), int(player), int(level)),
        int(require_key(game_state, "board_cols")),
        int(require_key(game_state, "board_rows")),
    )
    fields[fkey] = (budget, field)
    return field


def _euclidean_move_field_for_model(
    game_state: Dict[str, Any],
    squad_id: str,
    player: int,
    model: Dict[str, Any],
    level: int,
    bound: int,
) -> Dict[Tuple[int, int], float]:
    """Champ ANY-ANGLE (metrique euclidienne) atteignable par une figurine dans `bound`.

    SOURCE UNIQUE du champ euclidien par-figurine, partagee par la MESURE de la distance
    parcourue (`_euclidean_path_distance`) et par la BORNE de la charge / du pile-in
    (`model_reach_predicate`). Les deux doivent voir exactement le meme atteignable : une
    destination bornee par un champ et mesuree par un autre rouvrirait l'ecart validation/mesure.

    Socle rond -> clairance continue ; socle non-rond -> obstacles dilates par l'empreinte
    ORIENTEE. Obstacles = definition partagee du trajet legal (`build_move_transit_blocked`).
    FLY declare (21.03) traverse murs et figurines : le champ n'a alors aucun obstacle, ce qui
    redonne exactement la ligne droite — pas besoin d'un cas particulier.
    """
    from engine.hex_utils import (
        ENGAGEMENT_NORM_HEX_WIDTH, base_size_cache_key, precompute_footprint_offsets,
    )
    from engine.phase_handlers.geodesic_move import _euclidean_move_field
    from engine.phase_handlers.movement_handlers import _fly_traversal_active

    start = (int(model["col"]), int(model["row"]))
    # Memoise dans l'etat, comme son jumeau geodesique (`geodesic_field_for_origin`) : sans cela
    # `charge_build_valid_plan` — appele par `observation_builder` une fois par escouade ennemie a
    # chaque construction d'observation en phase de charge — reconstruisait un Dijkstra any-angle
    # par figurine et par appel. Meme fingerprint d'etat, donc meme fraicheur.
    _cache = _move_spatial_cache(game_state)["eucl"]
    base_shape = str(require_key(model, "BASE_SHAPE"))
    base_size = require_key(model, "BASE_SIZE")
    # Un socle ROND n'a pas d'empreinte orientee : `_euclidean_move_field` le traite en clairance
    # continue et JETTE les offsets (cf. sa docstring). Garder l'orientation dans la cle ferait
    # reconstruire un Dijkstra any-angle complet — des centaines de ms sur un budget de move — a
    # chaque cran de pivot molette, pour un champ bit a bit identique. Meme idiome que le pool
    # (`movement_build_model_destinations_pool`), qui saute deja `precompute_footprint_offsets`.
    _is_round = base_shape == "round"
    orientation = 0 if _is_round else int(model.get("orientation", 0))  # get allowed (defaut face nord, cf. pool)
    _ckey = (
        str(squad_id), int(player), start, int(level), int(bound), base_shape,
        # Socle oval -> BASE_SIZE est une liste, donc non hachable : `base_size_cache_key` est la
        # source unique de cette normalisation (cf. sa docstring).
        base_size_cache_key(base_size),
        orientation,
    )
    _hit = _cache.get(_ckey)
    if _hit is not None:
        return _hit
    unit = get_unit_by_id(game_state, str(squad_id))
    obstacles: Set[Tuple[int, int]] = set()
    if not (unit is not None and _fly_traversal_active(game_state, unit, str(squad_id))):
        obstacles = set(build_move_transit_blocked(game_state, str(squad_id), int(player), int(level)))
    obstacles.discard(start)
    off_even: Tuple[Tuple[int, int], ...] = ()
    off_odd: Tuple[Tuple[int, int], ...] = ()
    if not _is_round:
        off_even, off_odd = precompute_footprint_offsets(base_shape, base_size, orientation)
    field = _euclidean_move_field(
        start, base_shape, base_size, off_even, off_odd, obstacles,
        int(require_key(game_state, "board_cols")),
        int(require_key(game_state, "board_rows")),
        float(bound) * ENGAGEMENT_NORM_HEX_WIDTH,
    )
    _cache[_ckey] = field
    return field


def model_reach_predicate(
    game_state: Dict[str, Any],
    squad_id: str,
    player: int,
    model: Dict[str, Any],
    budget: int,
    level: int,
    metric: Optional[str] = None,
) -> Callable[[int, int], bool]:
    """« Cette figurine peut-elle ATTEINDRE cette cellule dans son budget ? » — par le CHEMIN.

    SOURCE UNIQUE de la portee par-figurine pour les mouvements qui n'ont pas de pool BFS :
    la charge (11.04) et le pile-in / la consolidation (12.03 / 12.08). Les trois disent
    « **Your unit moves as described in Moving (03)** » : la borne est donc la meme que celle du
    move normal — un trajet legal qui contourne murs et figurines — et non une distance a vol
    d'oiseau.

    C'ETAIT LE DEFAUT. `charge_build_valid_plan` et `_assign_cells_toward_enemies` retenaient
    une cellule sur `calculate_hex_distance(origine, cellule) <= budget` et ne validaient que la
    case d'ARRIVEE (plateau, murs, autres escouades). Le trajet n'etait jamais regarde : une
    escouade traversait une ligne de murs pendant sa charge, ou une consolidation passait au
    travers d'une figurine ennemie. Mesure sur un run de 600 episodes : 43 charges et 28
    consolidations au-dela du budget reel, dont E301 ou six socles franchissent la muraille de
    la colonne 33 avec un jet de 8 pour des trajets legaux de 8 a 13.

    Meme machinerie que `explain_move_plan_rejection`, volontairement : memes obstacles de
    transit (`build_move_transit_blocked`), meme champ geodesique memoise dans l'etat
    (`_move_spatial_cache`), meme exclusion. Dupliquer la regle ici la ferait diverger.

    LES TROIS GEOMETRIES sont traitees, via la source unique `move_plan_distance_mode` — comme
    la validation du move. UNE SEULE rend la ligne droite exacte : `cube`, c'est-a-dire la
    traversee FLY declaree (21.03), ou le trajet legal EST la ligne d'hexes. Ce n'est donc pas
    un repli, c'est la geometrie de la regle.

    `euclidean` (metrique PvP / PvE) doit passer par le champ ANY-ANGLE et non par la ligne
    droite. Le move s'accordait autrefois cette ligne droite — « deja borne par le pool
    par-figurine » — et c'etait FAUX pour lui aussi : le pool n'est construit que pour la figurine
    SELECTIONNEE, jamais pour les soeurs translatees par le move d'escouade rigide. Le move passe
    donc lui aussi par ce predicat ; la charge et le pile-in, eux, n'ont jamais eu de pool du tout.
    S'en tenir a la ligne droite laissait les murs traversables dans tout le PvE, et faisait lever
    `_euclidean_path_distance` au commit sur un plan deja accepte par l'UI.

    `level` = niveau du TRAJET, c'est-a-dire le niveau CIBLE, jamais celui d'origine : une
    figurine qui descend chemine parmi les obstacles de l'etage d'ARRIVEE (§0.34). C'est une
    contrainte de la signature, pas de l'appelant — les trois sites la respectent.
    """
    o_col, o_row = int(model["col"]), int(model["row"])
    budget = int(budget)
    mode = move_plan_distance_mode(game_state, str(squad_id), metric)

    if mode == "cube":
        def _straight(nc: int, nr: int) -> bool:
            return calculate_hex_distance(o_col, o_row, nc, nr) <= budget
        return _straight

    if mode == "euclidean":
        eucl = _euclidean_move_field_for_model(
            game_state, str(squad_id), int(player), model, int(level), budget
        )

        def _by_any_angle(nc: int, nr: int) -> bool:
            return (nc, nr) in eucl
        return _by_any_angle

    reachable = geodesic_field_for_origin(
        game_state, str(squad_id), int(player), (o_col, o_row), int(level), budget
    )

    def _by_path(nc: int, nr: int) -> bool:
        # `<= budget`, pas une appartenance : le champ memoise peut avoir ete calcule pour un
        # budget PLUS LARGE (cf. `geodesic_field_for_origin`).
        _d = reachable.get((nc, nr))
        return _d is not None and _d <= budget

    return _by_path


def _euclidean_path_distance(
    game_state: Dict[str, Any],
    squad_id: str,
    player: int,
    model: Dict[str, Any],
    dest: Tuple[int, int],
    level: int,
    bound: int,
) -> float:
    """Distance de chemin ANY-ANGLE (métrique euclidienne) parcourue par une figurine.

    Même primitive que le pool de destinations par-figurine (`_euclidean_move_field`) : socle
    rond -> clairance continue, socle non-rond -> obstacles dilatés par l'empreinte orientée.
    Les obstacles de traversée sont ceux de la définition PARTAGÉE du trajet légal
    (`build_move_transit_blocked`).

    FLY (21.03) traverse murs et figurines : le champ n'a alors aucun obstacle, ce qui redonne
    exactement la ligne droite — pas besoin d'un cas particulier.
    """
    from engine.hex_utils import ENGAGEMENT_NORM_HEX_WIDTH

    start = (int(model["col"]), int(model["row"]))
    if start == (int(dest[0]), int(dest[1])):
        return 0.0
    field = _euclidean_move_field_for_model(
        game_state, str(squad_id), int(player), model, int(level), int(bound)
    )
    reached = field.get((int(dest[0]), int(dest[1])))
    if reached is None:
        raise RuntimeError(
            f"_euclidean_path_distance: destination {dest} injoignable en chemin <= {bound} "
            f"depuis {start} alors que le plan a ete valide. Incoherence validation/mesure."
        )
    return float(reached) / ENGAGEMENT_NORM_HEX_WIDTH


def move_plan_path_distances(
    plan: MovePlan,
    game_state: Dict[str, Any],
    move_type: str,
) -> Dict[str, float]:
    """Distance réellement PARCOURUE par chaque figurine d'un plan, avant application.

    À appeler AVANT `commit_move` (les origines sont lues dans `models_cache`). La mesure suit
    exactement la métrique du move (`move_plan_distance_mode`) : distance de CHEMIN quand
    le trajet doit contourner murs et figurines, distance à vol d'oiseau quand la géométrie la
    rend exacte. Une destination injoignable dans la borne explorée est une INCOHÉRENCE (le
    plan a été validé juste avant) : erreur explicite, jamais une distance inventée.
    """
    if not plan:
        return {}
    models_cache = require_key(game_state, "models_cache")
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    first = models_cache.get(plan[0][0])
    if first is None:
        raise KeyError(f"move_plan_path_distances: figurine {plan[0][0]} absente de models_cache")
    squad_id = str(first["squad_id"])
    player = int(first["player"])
    _mode = move_plan_distance_mode(game_state, squad_id)
    bound = _move_distance_field_bound(game_state, squad_id, move_type)

    distances: Dict[str, float] = {}
    for entry in plan:
        mid = str(entry[0])
        model = models_cache.get(mid)
        if model is None:
            raise KeyError(f"move_plan_path_distances: figurine {mid} absente de models_cache")
        o_col, o_row = int(model["col"]), int(model["row"])
        n_col, n_row = int(entry[1]), int(entry[2])
        # Niveau du TRAJET = niveau CIBLE du plan (4e élément), miroir exact de la validation
        # (`explain_move_plan_rejection`) : mesurer le chemin d'une figurine qui descend parmi les
        # obstacles de son étage de DÉPART mesurerait une autre grandeur que celle validée (§0.34).
        _path_level = int(entry[3])
        if _mode == "cube":
            # Métrique hex + FLY (21.03) : la traversée ignore murs et figurines, donc le trajet
            # EST la ligne d'hexes et sa longueur est la distance cube — EXACTEMENT la grandeur
            # que `explain_move_plan_rejection` vient de borner (`calculate_hex_distance`). La
            # mesurer avec le champ euclidien mesurerait une AUTRE grandeur : un pas vers le sud
            # vaut `sqrt(3)` unités `_hex_center` contre `1,5` vers l'est, si bien qu'un plan
            # validé ressortait « injoignable » de sa propre mesure (§0.34).
            distances[mid] = float(calculate_hex_distance(o_col, o_row, n_col, n_row))
            continue
        if _mode == "euclidean":
            # Métrique EUCLIDIENNE (PvP) : le trajet contourne les obstacles — on mesure donc
            # avec la MEME primitive any-angle que le pool par-figurine
            # (`_euclidean_move_field`), sans quoi un contournement de mur serait sous-compte et
            # [HEAVY] 24.16 deviendrait LAXISTE en PvP.
            # Orientation VISÉE par le plan, miroir exact de la validation
            # (`explain_move_plan_rejection`) : la mesure tourne AVANT `update_model_position`,
            # donc `models_cache` porte encore l'ANCIENNE orientation. Sur socle non rond
            # (oval : LandSpeeder, WarTrakk) le champ dilate les obstacles par l'empreinte
            # orientée, et le goulot que le pivot vient d'ouvrir se refermerait ici : le plan
            # validé ressortirait « injoignable » de sa propre mesure.
            distances[mid] = _euclidean_path_distance(
                game_state, squad_id, player, plan_entry_model(entry, model),
                (n_col, n_row), _path_level, bound,
            )
            continue
        field = geodesic_field_for_origin(
            game_state, squad_id, player, (o_col, o_row), _path_level, bound
        )
        path = field.get((n_col, n_row))
        if path is None or path > bound:
            raise RuntimeError(
                f"move_plan_path_distances: figurine {mid} — destination ({n_col},{n_row}) "
                f"injoignable en chemin <= {bound} depuis ({o_col},{o_row}) alors que le plan "
                f"a ete valide. Incoherence validation/mesure."
            )
        distances[mid] = float(path)
    return distances


def validate_move_plan(
    plan: MovePlan,
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
    return explain_move_plan_rejection(plan, game_state, constraints) is None


def explain_move_plan_rejection(
    plan: MovePlan,
    game_state: Dict[str, Any],
    constraints: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """SOURCE UNIQUE de la validation d un plan de move : None = valide, sinon la RAISON.

    `validate_move_plan` n'est que le predicat booleen construit dessus — il n'y a donc qu'une
    seule implementation du check. Cette forme existe parce qu'une violation de l'invariant
    « masque ⊆ executable » est fatale (w40k_core leve) : une erreur qui ne nomme PAS la
    contrainte violee oblige a re-deviner la cause a chaque occurrence.
    """
    c = dict(DEFAULT_MOVE_CONSTRAINTS)
    if constraints:
        c.update(constraints)
    if not plan:
        return "plan vide"

    models_cache = require_key(game_state, "models_cache")
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())

    first_model = models_cache.get(plan[0][0])
    if first_model is None:
        return f"figurine {plan[0][0]} absente de models_cache"
    squad_id = str(first_model["squad_id"])
    player = int(first_model["player"])

    # SOURCE UNIQUE du predicat de cellule, partagee avec l'erosion du pool de move
    # (`erode_move_pool_by_squad_block`) : dupliquer ce check rouvrirait la classe de bug
    # « masque/execution » que l'erosion elimine (decision de design n°2).
    # PAR GEOMETRIE DE SOCLE : l'EZ ennemie depend du socle pose (cf.
    # `move_enemy_ez_forbidden_cells`). Une escouade a socles mixtes (personnage attache) a donc
    # plusieurs jeux de cellules interdites, et chaque figurine doit etre testee contre LE SIEN.
    # Memo local : une seule construction par geometrie presente dans le plan.
    _plan_levels = {plan_entry_level(entry) for entry in plan}
    _blocked_by_geom: Dict[Any, Dict[int, List[Tuple[str, Set[Tuple[int, int]]]]]] = {}

    def _blocked_for(_shape: Any, _size: Any, _orient: int):
        _gk = move_geom_key(
            {"BASE_SHAPE": _shape, "BASE_SIZE": _size, "orientation": int(_orient)}
        )
        _hit = _blocked_by_geom.get(_gk)
        if _hit is None:
            _hit = build_move_blocked_cells_by_level(
                game_state, squad_id, player, _plan_levels, c, _shape, _size, int(_orient)
            )
            _blocked_by_geom[_gk] = _hit
        return _hit

    # Budget en distance de TRAJET (règle 03) : le trajet contourne murs et figurines, donc la
    # distance à vol d'oiseau le sous-estime. La borne est `model_reach_predicate`, SOURCE UNIQUE
    # des trois géométries (cube FLY 21.03 / euclidienne PvP / géodésique sol) — la même que la
    # charge (11.04) et le pile-in (12.03) interrogent déjà, et le même champ mémoïsé (au niveau
    # de l'ÉTAT, `_move_spatial_cache`) que la MESURE au commit (`move_plan_path_distances`).
    # Le raccourci `calculate_hex_distance <= budget` qui vivait ici bornait le PvP par la ligne
    # droite : cf. la docstring de `model_reach_predicate` pour le défaut corrigé.
    plan_models: Dict[str, Dict[str, Any]] = {}
    if c["budget_per_model"] is not None:
        for entry in plan:
            mid = entry[0]
            m = models_cache.get(mid)
            if m is None:
                return f"figurine {mid} absente de models_cache"
            plan_models[mid] = m

    # Clé (niveau, col, row) : le NIVEAU fait partie de l'identité d'une position — meme
    # regle que le contrôle de cellule interdite juste en dessous, qui est deja per-niveau.
    # Clefer sur (col,row) seul rejetait comme « collision » deux figurines legalement
    # superposees a des etages differents ; `build_rigid_plan` translatant le bloc
    # rigidement, la superposition d'origine se reportait sur CHAQUE destination et toute la
    # suite des moves de l'escouade devenait injouable (incoherence masque/execution).
    new_cells: Set[Tuple[int, int, int]] = set()
    for entry in plan:
        mid, nc, nr = entry[0], int(entry[1]), int(entry[2])
        if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
            return f"figurine {mid} hors plateau en ({nc},{nr})"
        cell = (nc, nr)
        level = plan_entry_level(entry)
        _m_geo = models_cache.get(mid)
        if _m_geo is None:
            return f"figurine {mid} absente de models_cache"
        # Orientation VISEE par le plan (pivot molette non committe) — la meme que celle avec
        # laquelle le pool a offert la case, cf. le budget plus bas.
        _blocked_lv = _blocked_for(
            require_key(_m_geo, "BASE_SHAPE"),
            require_key(_m_geo, "BASE_SIZE"),
            plan_entry_model_orientation(entry, _m_geo),
        )
        for label, blocked_set in _blocked_lv[level]:
            if cell in blocked_set:
                return (
                    f"figurine {mid} en ({nc},{nr}) niveau {level} "
                    f"sur cellule interdite : {label}"
                )
        occupied = (level, nc, nr)
        if occupied in new_cells:
            return (
                f"collision intra-plan : deux figurines en ({nc},{nr}) "
                f"niveau {level} (dont {mid})"
            )
        new_cells.add(occupied)
        if c["budget_per_model"] is not None:
            budget = int(c["budget_per_model"])
            # Orientation VISÉE par le plan (pivot molette non committé) : en métrique euclidienne
            # le champ any-angle dilate les obstacles par l'empreinte ORIENTÉE, et c'est cette
            # orientation-là que le pool par-figurine a utilisée pour offrir la case
            # (`movement_build_model_destinations_pool`, `mover_orient`). Lire celle de
            # `models_cache` refuserait en voile rouge la case que le pool vient d'offrir à un socle
            # pivoté — sur socle non rond, un passage étroit ne s'ouvre QUE dans une orientation.
            _model = plan_entry_model(entry, plan_models[mid])
            # Transit du niveau CIBLE, pas du niveau d'origine : une figurine qui descend
            # (squad move rigide, destination sol) chemine parmi les obstacles du SOL, et
            # c'est ce meme niveau que le pool d'ancre du masque a utilise. Origine == cible
            # dans tous les autres cas, donc aucun changement ailleurs (§0.34).
            if not model_reach_predicate(
                game_state, squad_id, player, _model, budget, level
            )(nc, nr):
                o_col, o_row = int(_model["col"]), int(_model["row"])
                _sl = calculate_hex_distance(o_col, o_row, nc, nr)
                return (
                    f"figurine {mid} hors budget : ({nc},{nr}) injoignable en trajet "
                    f"<= {budget} depuis ({o_col},{o_row}) "
                    f"(distance a vol d'oiseau {_sl}, geometrie "
                    f"{move_plan_distance_mode(game_state, squad_id)}, "
                    f"trajet legal contournant murs/figs > budget)"
                )

    if c["require_coherency"]:
        plan_positions = {entry[0]: (int(entry[1]), int(entry[2])) for entry in plan}
        if not _validate_plan_coherency(plan_positions, game_state):
            # La coherency ne depend que des positions RELATIVES, preservees par la translation
            # cube : si le plan est incoherent, la formation ACTUELLE l'est deja. On le dit, car
            # la cause n'est alors pas la destination mais l'etat de l'escouade (pertes).
            current = {
                mid: (int(models_cache[mid]["col"]), int(models_cache[mid]["row"]))
                for mid in plan_positions
                if mid in models_cache
            }
            origin_coherent = _validate_plan_coherency(current, game_state)
            # Positions PAR FIGURINE, avec le flag de coherency avant/apres translation. Sans
            # elles, « plan incoherent / formation actuelle coherente » est un message
            # AUTO-CONTRADICTOIRE : la coherency ne depend que des positions relatives, que la
            # translation cube preserve (verifie sur tout le board, negatifs inclus). Une
            # occurrence sans les positions n'est donc pas diagnosticable — elle oblige a
            # relancer des heures d'entrainement pour esperer la revoir.
            ordered = [mid for mid in plan_positions if mid in models_cache]
            cur_flags = coherency_violation_flags(
                [dict(models_cache[mid]) for mid in ordered], game_state
            )
            new_flags = coherency_violation_flags(
                [
                    {
                        **models_cache[mid],
                        "col": plan_positions[mid][0],
                        "row": plan_positions[mid][1],
                    }
                    for mid in ordered
                ],
                game_state,
            )
            detail = " ; ".join(
                f"{mid} ({models_cache[mid]['col']},{models_cache[mid]['row']})"
                f"->({plan_positions[mid][0]},{plan_positions[mid][1]})"
                f" base={models_cache[mid]['BASE_SIZE']}"
                f" lvl={models_cache[mid]['level']}"
                f" coh={'X' if cur_flags[i] else '.'}{'X' if new_flags[i] else '.'}"
                for i, mid in enumerate(ordered)
            )
            return (
                "coherency du plan invalide "
                f"(formation actuelle {'coherente' if origin_coherent else 'DEJA incoherente'})"
                f" — {len(ordered)} figurines"
                f" [id (col,row)actuel->(col,row)planifie base lvl coh=avant/apres] : {detail}"
            )

    return None


def roll_hazard_for_unit(
    unit_id: str, game_state: Dict[str, Any], auto_resolve: bool,
    *, n_rolls: Optional[int] = None, context_label: str = HAZARD_CONTEXT_DESPERATE_ESCAPE,
) -> int:
    """Hazard rolls pour une unité (règle 06.03) — Desperate Escape (09.07) ou [HAZARDOUS] (24.15).

    06.03 : 1D6 par jet, simultanément. Sur 1-2 : 1 mortal wound, ou 3 si CHAQUE figurine de
    l'unité est MONSTER/VEHICLE. Les MW sont attribuées via la séquence 06.02
    (``allocate_mortal_wounds``) : ``auto_resolve`` est propagé (IA/gym = choix déterministe ;
    humain = prompt étape 3).

    ``n_rolls`` : nombre de jets. Défaut (None) = une par figurine vivante — c'est la règle du
    Desperate Escape 09.07 (« each model must take a test »). [HAZARDOUS] 24.15 en impose un
    autre : un jet PAR ARME hazardous sélectionnée, indépendant du nombre de figurines.
    ``context_label`` : origine du jet, pour la ligne de log.

    Retourne le total de mortal wounds rollés (avant arrêt éventuel si l'unité meurt).
    """
    import random
    squad_models = require_key(game_state, "squad_models")
    models_cache = require_key(game_state, "models_cache")
    unit_id_str = str(unit_id)
    if unit_id_str not in squad_models:
        raise KeyError(f"roll_hazard_for_unit: unit {unit_id} not in squad_models")
    alive_models = [mid for mid in squad_models[unit_id_str] if mid in models_cache]
    if not alive_models:
        return 0
    roll_count = len(alive_models) if n_rolls is None else int(n_rolls)
    if roll_count <= 0:
        return 0
    units = require_key(game_state, "units")
    try:
        unit = next(u for u in units if str(u.get("id")) == str(unit_id))
    except StopIteration:
        raise KeyError(f"roll_hazard_for_unit: unit {unit_id} not found in game_state['units']")
    # 06.03 : « 3 mortal wounds instead if EACH model in that unit is a MONSTER/VEHICLE model. »
    # Test PAR FIGURINE (models_cache porte les keywords propres, cf. 19.03) : une escouade
    # d'infanterie menée par un character MONSTER ne doit pas hériter du seuil à 3.
    # UNIT_KEYWORDS = liste d'objets {"keywordId": "..."} (cf. game_state). Pattern canonique.
    def _is_monster_or_vehicle(model: Dict[str, Any]) -> bool:
        ids = {
            str(require_key(kw, "keywordId")).strip().lower()
            for kw in require_key(model, "UNIT_KEYWORDS")
        }
        return "monster" in ids or "vehicle" in ids

    wounds_per_fail = 3 if all(_is_monster_or_vehicle(models_cache[mid]) for mid in alive_models) else 1
    rolls = [random.randint(1, 6) for _ in range(roll_count)]
    # L11 — stocker les jets pour le formateur step.log (desperate_escape_pre_move les lit).
    if context_label == HAZARD_CONTEXT_DESPERATE_ESCAPE:
        game_state["_desperate_escape_rolls"] = list(rolls)
    fails = sum(1 for r in rolls if r <= 2)
    total_wounds = fails * wounds_per_fail
    col = int(unit.get("col", -1))
    row = int(unit.get("row", -1))
    _ut_seg = f" {unit['unitType']}" if unit.get("unitType") else ""
    msg = (
        f"Unit {unit_id}{_ut_seg}({col},{row}) [HAZARD] roll ({context_label}): {roll_count} rolls "
        f"- {fails} fail(s) - {total_wounds} mortal wound(s)"
    )
    # Détails par-figurine (06.02) : remplis pendant l'attribution, comme shootDetails au tir.
    # ⚠ La ligne de log est émise IMMÉDIATEMENT, au jet — AVANT que le joueur ne choisisse ses
    # pertes. Sinon le joueur doit désigner des figurines sans savoir combien de blessures
    # mortelles il encaisse ni d'où elles viennent. `append_action_log` mute l'entrée en place
    # et conserve la référence : les `hazardDetails` viennent compléter CETTE ligne pendant
    # l'attribution, sans en créer une seconde.
    details: List[Dict[str, Any]] = []
    log_payload = {
        "type": "hazard",
        "message": msg,
        "turn": require_key(game_state, "turn"),
        "phase": require_key(game_state, "phase"),
        "unitId": int(unit_id),
        "player": int(unit.get("player", -1)),
        # POSITION DE L'UNITÉ — sans elle, la ligne n'atteignait JAMAIS step.log. Le formateur
        # du StepLogger exige `unit_with_coords` pour une action `hazardous`, et
        # `_build_step_log_details` ne le construit qu'à partir de `toCol/toRow` ou de
        # `col/row` : ce payload n'avait ni l'un ni l'autre, donc le formateur levait et
        # `log_action` avalait l'exception (« ⚠️ Step logging error »). Mesuré sur un run de
        # 12 épisodes : ZÉRO ligne `HAZARD` dans le journal, pour un type pourtant présent dans
        # `_STEP_LOG_TYPE_MAP`. Les coordonnées étaient déjà calculées deux lignes plus haut
        # pour le `message` — elles n'étaient simplement pas exposées en champs structurés.
        "col": col,
        "row": row,
        # Nombre de blessures mortelles, en CHAMP et pas seulement dans `result` (« 3 MW ») :
        # le formateur l'exige (`require_key(details, "hazardous_mortal_wounds")`) et personne
        # ne le lui fournissait — second verrou qui faisait tomber la ligne, apres l'absence de
        # coordonnees. Re-parser « 3 MW » cote lecteur serait une troisieme definition du meme
        # nombre.
        "hazardousMortalWounds": int(total_wounds),
        "result": f"{total_wounds} MW",
        "hazardDetails": details,
        # Origine du jet : "Hazardous" (24.15 arme) ou "Desperate Escape" (09.07 fall-back).
        # Propagé jusqu'au step.log pour distinguer les deux cas : le formateur émet
        # [HAZARDOUS] pour 24.15 et [DESPERATE ESCAPE] pour 09.07, ce qui permet à l'analyzer
        # de ne vérifier l'armurerie que pour les vrais jets d'arme HAZARDOUS.
        "hazardContext": context_label,
    }
    # L15 — 24.15 HAZARDOUS : nombre d'armes sélectionnées (= roll_count pour ce contexte)
    # et jets individuels, absents pour Desperate Escape où roll_count = nombre de figurines.
    if context_label != HAZARD_CONTEXT_DESPERATE_ESCAPE:
        log_payload["hazardousWeaponCount"] = roll_count
        log_payload["hazardousDiceRolls"] = list(rolls)
    # Émission AVANT toute attribution : le jet et son résultat sont visibles dans le combat log
    # au moment où le joueur doit choisir les pertes (cf. commentaire ci-dessus).
    append_action_log(game_state, log_payload)
    if total_wounds <= 0:
        return total_wounds
    if auto_resolve:
        # IA / gym : attribution 06.02 deterministe, sans prompt. Retrait figurine par
        # figurine via destroy_model (PAS l'agregat units_cache qui ne retirait rien en multi-fig).
        allocate_mortal_wounds(game_state, str(unit_id), total_wounds, auto_resolve, details)
        return total_wounds
    # Defenseur humain : allocation manuelle des pertes (groupes 05.03 + declaration d'ordre +
    # choix de figurine), calquee sur le tir. La ligne de log est DEJA affichee ; l allocation
    # ne fait que la completer de ses hazardDetails (cf. build_manual_hazard_allocation).
    build_manual_hazard_allocation(game_state, str(unit_id), total_wounds, log_payload)
    return total_wounds


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
    *,
    is_psychic: bool = False,
) -> int:
    """Attribue ``n_wounds`` mortal wounds à une unité (séquence 06.02), une par une, en
    mode AUTO uniquement (IA / gym). Le défenseur humain passe par
    ``build_manual_hazard_allocation`` (allocation manuelle des pertes calquée sur le tir).

    - ``auto_resolve=True`` : choix déterministe ``eligibles[0]`` quand plusieurs figs sont
      également éligibles.
    - ``auto_resolve=False`` : non supporté ici → erreur explicite (root cause : appeler
      ``build_manual_hazard_allocation``).
    - ``is_psychic`` : True si les MW proviennent d'une source PSYCHIC (ex. Da Jump),
      ce qui active feel_no_pain_vs_psychic si l'unité cible en dispose.

    Chaque MW retire 1 HP à la figurine choisie ; la figurine n'est retirée du jeu
    (``destroy_model`` reason='hazard') qu'à ``HP_CUR == 0``. On s'arrête si l'unité
    est détruite avant d'avoir attribué toutes les MW (06.02 : « until … destroyed »).

    ``details_sink`` reçoit 1 record ``{modelId, col, row, died}`` par MW traitée
    (col/row capturés AVANT destroy, ``fnpSaved=True`` si sauvée par FNP) — alimente
    ``hazardDetails`` du log, comme le tir.

    Retourne le nombre de mortal wounds réellement attribués.
    """
    models_cache = require_key(game_state, "models_cache")
    sid = str(squad_id)
    remaining = int(n_wounds)
    applied = 0
    # FNP thresholds constants pour toute l'allocation : la règle et la position de l'escouade
    # ne changent pas entre blessures mortelles successives.
    _fnp_unit = require_unit_by_id(game_state, sid)
    _fnp_ths = _collect_fnp_thresholds_mortal(_fnp_unit, game_state, is_psychic=is_psychic)
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
        col = int(require_key(models_cache[target], "col"))
        row = int(require_key(models_cache[target], "row"))
        # Feel No Pain (24.12) : jet D6 par blessure mortelle avant application.
        if _fnp_ths and _roll_fnp_sequential(1, _fnp_ths) == 0:
            # L12 — FNP mortal wounds : journaliser la sauvegarde dans details_sink.
            details_sink.append({"modelId": str(target), "col": col, "row": row, "died": False, "fnpSaved": True})
            remaining -= 1
            continue
        new_hp = int(models_cache[target]["HP_CUR"]) - 1
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


def _strength_measure(unit_id: str, game_state: Dict[str, Any]) -> Tuple[int, int]:
    """``(restant, depart)`` — la grandeur sur laquelle se jugent les seuils d'effectif (25).

    L'appendice 25 en definit DEUX, selon la force de depart, et c'est la seule difference entre
    les trois predicats ci-dessous :
      - force de depart >= 2 : ce sont des FIGURINES (restantes vs force de depart) ;
      - force de depart == 1 : ce sont des POINTS DE VIE (W restants vs W du profil), parce
        qu'une unite d'une figurine ne peut pas perdre de figurine sans etre detruite.

    La force de depart est ``squad_cache[unit]["model_count_at_start"]``, photographiee par
    ``build_units_cache`` APRES le repli 19.04 (`_fold_attached_characters`) : un Captain attache
    a 5 Intercessors est deja une figurine de l'escouade a cet instant, donc la force de depart
    vaut 6 — l'exemple litteral du PDF 25.
    """
    squad_cache = require_key(game_state, "squad_cache")
    entry = squad_cache.get(str(unit_id))
    if entry is None:
        raise KeyError(f"_strength_measure: unit {unit_id} not in squad_cache")
    count_start = int(require_key(entry, "model_count_at_start"))
    if count_start <= 0:
        raise ValueError(
            f"_strength_measure: unit {unit_id} a une force de depart de {count_start} : "
            f"une escouade sans figurine au debut de la bataille est un etat corrompu."
        )
    if count_start > 1:
        return int(require_key(entry, "model_count")), count_start
    # Mono-figurine : la mesure est en PV. HP_CUR vient de units_cache (source de vérité vivante,
    # mise à jour à chaque dégât) ; HP_MAX est immuable et lu sur l'unité.
    units_cache = require_key(game_state, "units_cache")
    cache_entry = units_cache.get(str(unit_id))
    if cache_entry is None:
        raise KeyError(f"_strength_measure: unit {unit_id} not in units_cache")
    units = require_key(game_state, "units")
    try:
        unit = next(u for u in units if str(u.get("id")) == str(unit_id))
    except StopIteration:
        raise KeyError(f"_strength_measure: unit {unit_id} not found in game_state['units']")
    return int(require_key(cache_entry, "HP_CUR")), int(require_key(unit, "HP_MAX"))


def is_unit_below_starting_strength(unit_id: str, game_state: Dict[str, Any]) -> bool:
    """Appendice 25 : l'unite a-t-elle perdu quoi que ce soit depuis le debut de la bataille ?

    ⚠️ SANS APPELANT DANS LE MOTEUR, et c'est delibere (decision du 2026-08-04) : aucune regle
    implementee ne dit encore « while this unit is below its starting strength » — ce sont des
    capacites de datasheet (chantier 06) qui la consommeront. Elle est gardee parce que les TROIS
    seuils de l'appendice 25 se lisent ensemble : en detacher un invite a le reimplementer a cote
    plus tard, ce qui est le motif du jumeau divergent. Verifiee par un test qui construit l'etat
    (`test_command_points_and_battle_shock.py`), pas seulement importee — mais elle n'est, pour
    l'instant, verifiee que contre elle-meme.
    """
    remaining, start = _strength_measure(unit_id, game_state)
    return remaining < start


def is_unit_at_half_strength(unit_id: str, game_state: Dict[str, Any]) -> bool:
    """Appendice 25 : l'unite est-elle EXACTEMENT a demi-effectif ?

    ⚠️ « If a model's W characteristic or a unit's starting strength cannot be evenly divided in
    half, that model or unit CANNOT be at half-strength (but can be below half-strength). » Une
    force de depart IMPAIRE rend donc ce predicat definitivement faux — une escouade de 5 n'est
    JAMAIS a demi-effectif, quel que soit son etat. C'est ce que `start % 2` verrouille, et c'est
    exactement ce qu'une implementation en `<=` sur une division entiere raterait.
    """
    remaining, start = _strength_measure(unit_id, game_state)
    if start % 2 != 0:
        return False
    return remaining == start // 2


def is_unit_below_half_strength(unit_id: str, game_state: Dict[str, Any]) -> bool:
    """Appendice 25 : l'unite est-elle SOUS le demi-effectif ?

    Aucune clause de parite ici, et c'est le pendant de celle de `is_unit_at_half_strength` : une
    escouade de 5 reduite a 2 est sous le demi-effectif (2 < 2.5) sans jamais y avoir ete.
    """
    remaining, start = _strength_measure(unit_id, game_state)
    return remaining * 2 < start


def is_unit_at_or_below_half_strength(unit_id: str, game_state: Dict[str, Any]) -> bool:
    """Condition d'effectif de l'etape 08.03 : « at, or below, half-strength ».

    Union EXPLICITE des deux predicats de l'appendice 25, et pas un `<=` maison : avec la clause
    de parite, « a demi-effectif » et « sous le demi-effectif » ne sont pas deux moities d'un
    meme test, et les ecrire separement est ce qui rend chacun verifiable.
    """
    return is_unit_at_half_strength(unit_id, game_state) or is_unit_below_half_strength(
        unit_id, game_state
    )


def unit_effective_leadership(unit_id: str, game_state: Dict[str, Any]) -> int:
    """Seuil de Ld d'une unite pour un jet de commandement (01.06). Le PLUS BAS de ses figurines.

    « if the result is equal to or greater than ONE OR MORE of the Ld characteristics in that
    unit, that roll succeeds » : reussir contre l'un des Ld suffit, donc l'unite teste contre le
    seuil le plus facile — le Ld numeriquement le plus BAS (les datasheets ecrivent `6+`, `7+`).
    Un Warboss (`LD 6+`) attache a des Boyz (`LD 7+`) fait tester l'unite a 6+.

    Lu sur les figurines VIVANTES (`models_cache`, d'ou les morts sont retires) : quand le
    character tombe, l'unite reperd son Ld — meme extinction par source que les regles 19.04.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    model_ids = squad_models.get(str(unit_id))
    if model_ids is None:
        raise KeyError(f"unit_effective_leadership: unit {unit_id} not in squad_models")
    living = [mid for mid in model_ids if mid in models_cache]
    if not living:
        raise ValueError(
            f"unit_effective_leadership: unit {unit_id} n'a plus aucune figurine vivante — "
            f"une unite detruite ne fait aucun jet de commandement."
        )
    # `LD` absent = la figurine n'a pas de caracteristique de commandement, ce qui n'existe pas
    # sur une datasheet : erreur explicite, jamais un seuil de repli qui ferait rater ou reussir
    # le jet en silence.
    return min(int(require_key(models_cache[mid], "LD")) for mid in living)


def roll_battle_shock(unit_id: str, game_state: Dict[str, Any]) -> bool:
    """Battle-shock roll pour une unité (règle 01.07).

    Tire 2D6 et compare au MEILLEUR Ld de l'unité (01.06, `unit_effective_leadership`).
    Si résultat >= LD : succès, l'unité n'est PAS battle-shocked.
    Si résultat < LD  : échec, l'unité devient battle-shocked.

    L'écriture est INCONDITIONNELLE, et c'est la clause de sortie de 08.03 : « if a unit was
    battle-shocked at the start of this step and its battle-shock roll during this step succeeds,
    it is no longer battle-shocked » — un succès remet donc le drapeau à False.

    Retourne True si l'unité est désormais battle-shocked, False sinon.
    """
    import random
    units = require_key(game_state, "units")
    try:
        unit = next(u for u in units if str(u.get("id")) == str(unit_id))
    except StopIteration:
        raise KeyError(f"roll_battle_shock: unit {unit_id} not found in game_state['units']")
    ld = unit_effective_leadership(str(unit_id), game_state)
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
        # Champs lus par _build_step_log_details pour le formateur StepLogger (L1) :
        "col": col,
        "row": row,
        "ld": ld,
        "roll": roll,
        "battle_shocked": battle_shocked,
    })
    # Trace debug ECRITE ICI, et pas chez l'appelant : `command_step_battle_shock` la produisait
    # en recalculant `unit_effective_leadership` juste pour la remplir — un second balayage de
    # `models_cache` par unite choquee et par phase de commandement, alors que le seuil est deja
    # sous la main a cet endroit. Tous les declencheurs de 01.07 la produisent desormais.
    from engine.game_utils import add_debug_file_log

    add_debug_file_log(
        game_state,
        f"[BATTLE-SHOCK] E{game_state.get('episode_number', '?')} "
        f"T{game_state.get('turn', '?')} unit={unit_id} shocked={battle_shocked} ld={ld}"
    )

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
    unit = require_unit_by_id(game_state, str(squad_id))
    is_desperate = bool(was_engaged) and bool(require_key(unit, "battle_shocked"))
    if not is_desperate:
        return False, True, 0
    # L11 — mode enregistré pour le formateur step.log (consommé à l'émission action_log flee).
    game_state["_flee_mode"] = "desperate_escape"
    hazard_wounds = roll_hazard_for_unit(str(squad_id), game_state, auto_resolve)
    return True, is_unit_alive(str(squad_id), game_state), hazard_wounds


def desperate_escape_post_move(squad_id: str, game_state: Dict[str, Any]) -> None:
    """Desperate Escape (09.07) — phase APRÈS le mouvement.

    Si l'unité n'est PAS battle-shocked, elle doit faire un battle-shock roll (01.07). No-op tant
    que le Desperate Escape n'est déclenché que pour des unités déjà battle-shocked (cf. 09.07 :
    Ordered Retreat pour non-shocked, Desperate Escape sinon)."""
    unit = require_unit_by_id(game_state, str(squad_id))
    if not require_key(unit, "battle_shocked"):
        roll_battle_shock(str(squad_id), game_state)


def clear_desperate_escape_state(game_state: Dict[str, Any]) -> None:
    """Purge les clés transitoires posées par desperate_escape_pre_move (chemins de mort)."""
    game_state.pop("_flee_mode", None)
    game_state.pop("_desperate_escape_rolls", None)


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
    # Take to the skies (Règles 21.03) : si l'escouade a déclaré le vol pour ce move, retrancher 2"
    # de la distance max (normal/advance/fall_back). Le malus est en subhexes comme MOVE.
    # SOURCE UNIQUE de la déclaration (`took_to_the_skies`) : le malus et la traversée
    # (`_fly_traversal_active`) DOIVENT sortir du même prédicat, sinon on rejoue le défaut
    # d'origine — une unité qui traverse murs et figurines sans payer les 2".
    # MÊME garde de phase que la traversée (`take_to_the_skies_applies_to_phase`) : 21.03 retranche
    # 2" « while resolving THAT move ». Hors de la phase de mouvement, aucun move normal/advance/
    # fall-back n'est résolu et la question est purement hypothétique — `grid_half_extent_subhex`
    # l'appelle à chaque phase pour l'échelle de la grille égocentrique. Sans la garde, cette
    # échelle serait amputée de 2" en tir, charge et combat, où aucune traversée n'est active.
    from engine.phase_handlers.movement_handlers import (
        take_to_the_skies_applies_to_phase,
        took_to_the_skies,
    )

    tts_penalty = 0
    if take_to_the_skies_applies_to_phase(game_state, charge=False) and took_to_the_skies(
        game_state, unit, str(squad_id), charge=False
    ):
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


def resolve_squad_move_constraints(
    squad_id: str,
    game_state: Dict[str, Any],
    move_type: str,
    advance_roll: Optional[int] = None,
    extra_constraints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """SOURCE UNIQUE des contraintes qu'un squad move applique — budget inclus.

    Extraite d'`execute_squad_move` pour que le DIAGNOSTIC d'une violation de l'invariant
    « masque ⊆ executable » (w40k_core) evalue exactement les memes contraintes que
    l'execution : les recalculer a la main a l'endroit de l'erreur produirait un diagnostic
    qui peut mentir.
    """
    budget = get_squad_move_budget(squad_id, game_state, move_type, advance_roll=advance_roll)
    # Squad move rigide : retrancher le coût de descente de la fig la plus haute (§13.06), miroir du
    # pool PvP. No-op tant que l'unité est au sol (l'IA directionnelle 2D ne monte pas) ou vole.
    from engine.phase_handlers.movement_handlers import squad_descent_penalty_subhex
    budget = max(0, budget - squad_descent_penalty_subhex(game_state, squad_id))
    constraints: Dict[str, Any] = {"budget_per_model": budget}
    if extra_constraints:
        constraints.update(extra_constraints)
    return constraints


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
    constraints = resolve_squad_move_constraints(
        squad_id, game_state, move_type, advance_roll, extra_constraints
    )
    if not validate_move_plan(plan, game_state, constraints):
        return False
    commit_move(plan, game_state, move_type)
    if move_type == "advance":
        assert advance_roll is not None  # advance => roll tire ci-dessus (ligne move_type/None)
        # §4.3 — fige le jet dans `advance_rolls`, le systeme AUTORITAIRE (miroir du writer PvP
        # movement_handlers.py:801-809). `commit_move` ne marque QUE `units_advanced` : sans cette
        # ligne, `_advance_roll_for` trouvait l'escouade advancee mais sans jet, renvoyait None,
        # et tout pool reconstruit ensuite pour elle repartait silencieusement sur le budget
        # NORMAL au lieu de M+jet. Le gym ecrivait son jet dans `_squad_advance_rolls`, que
        # personne d'autre ne lit.
        # `execute_squad_move` n'a qu'un appelant (chemin gym, w40k_core) -> zero impact PvP.
        game_state.setdefault("advance_rolls", {})[str(squad_id)] = int(advance_roll)
        # Nettoyage du roll partage apres commit reussi (cf. spec).
        game_state.pop("current_advance_roll", None)
    return True


# ============================================================================
# CHARGE PLAN (squad_multi_figurines.md PR2 2c)
# ============================================================================


def _enemy_squad_ids(game_state: Dict[str, Any], player: int) -> List[str]:
    """Liste des squad_id ennemis POSÉS sur la table (player != donne).

    Les appelants mesurent une géométrie sur ces ids (zone d'engagement bord-à-bord dans
    ``_cell_is_free_for_model``) : une escouade hors table n'en a aucune, et la primitive EZ lève
    désormais plutôt que d'inventer un verdict. Le filtre est donc ici, à l'énumération.
    """
    units_cache = require_key(game_state, "units_cache")
    return [sid for sid, _entry in enemy_entries_on_battlefield(units_cache, int(player))]


def _squad_model_positions(game_state: Dict[str, Any], squad_id: str) -> List[Tuple[int, int]]:
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    out: List[Tuple[int, int]] = []
    for mid in squad_models.get(squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is not None:
            out.append((int(m["col"]), int(m["row"])))
    return out


def _model_height_of(model_entry: Mapping[str, Any], squad_entry: Mapping[str, Any]) -> float:
    """Hauteur (pouces) d une FIGURINE — source unique de l heritage escouade→figurine.

    Borne haute de l intervalle vertical [plancher, plancher + MODEL_HEIGHT] : elle sert
    l engagement 3D (§03.04, 5\" vertical), la LoS 3D du tir et la clairance sous les etages
    (§13.06). Elle se lit sur la figurine quand elle la porte (`build_models_cache` la propage
    comme le socle) et sur l escouade sinon.

    L heritage n est PAS un repli anti-erreur : une escouade homogene ne stocke pas N fois la meme
    hauteur, exactement comme pour `BASE_SHAPE`/`BASE_SIZE`. L absence des DEUX leve (`require_key`)
    — une hauteur inventee est une mesure fausse, silencieuse.

    `model_entry` doit etre une entree de `models_cache`, reconnaissable a sa cle `squad_id` : une
    ligne d escouade y porterait la hauteur du BLOC, et la mesure serait fausse sans que rien ne le
    dise. C est le defaut qui avait ete corrige sur onze sites de clairance ; le controle vit ici,
    avec l heritage, plutot que devant une seule des portes qui l utilisent.
    """
    if "squad_id" not in model_entry:
        raise ValueError(
            "_model_height_of: `model_entry` doit etre une FIGURINE (entree de `models_cache`, "
            "reconnaissable a sa cle `squad_id`). Une ligne d escouade y ramenerait la hauteur du "
            f"BLOC. Recu les cles : {sorted(model_entry)[:8]}"
        )
    if "MODEL_HEIGHT" in model_entry:
        return float(model_entry["MODEL_HEIGHT"])
    return float(require_key(squad_entry, "MODEL_HEIGHT"))


def _synth_model_entry(
    game_state: Dict[str, Any],
    squad_id: str,
    model_entry: Dict[str, Any],
    col: int,
    row: int,
    level: Optional[int] = None,
) -> Dict[str, Any]:
    """Entree units_cache synthetique pour UNE figurine placee en (col,row).

    SOURCE UNIQUE de l engagement par-figurine (charge, fight, pile-in, conso) :
    la geometrie de base provient du MODELE (``model_entry``), pas du squad — seul
    choix correct pour une unite a bases mixtes (perso attache a plus grande base).
    Le ``player`` est herite du squad (le modele ne le porte pas forcement). Entree
    complete (orientation incluse) pour rester valide quelle que soit la branche de
    ``unit_entries_within_engagement_zone``.

    ``level`` (defaut ``None``) — engagement 3D (chantier 4). ``None`` → entree 2D
    **inchangee** (byte-identique). Un entier = niveau de la figurine placee : on pose
    alors les donnees verticales (fig unique a (col,row), hauteur = plancher du niveau ;
    ``MODEL_HEIGHT`` = borne haute de l intervalle vertical).

    ``MODEL_HEIGHT`` se lit sur la FIGURINE quand elle la porte (`build_models_cache` la
    propage comme le socle), sinon sur l escouade. Ce n est pas un repli anti-erreur mais
    la MEME heritage metier que le socle : une escouade homogene ne stocke pas N fois la
    meme hauteur. La lire au bloc pour un personnage attache mesurait son engagement 3D
    (§03.04, 5\" vertical) avec l intervalle vertical d une autre figurine."""
    from engine.hex_utils import compute_occupied_hexes
    squad_entry = game_state.get("units_cache", {}).get(str(squad_id), {})  # get allowed
    shape = require_key(model_entry, "BASE_SHAPE")
    size = require_key(model_entry, "BASE_SIZE")
    orient = int(model_entry.get("orientation", 0))  # get allowed
    fp = compute_occupied_hexes(int(col), int(row), shape, size, orient)
    synth: Dict[str, Any] = {
        "id": f"_synth_{squad_id}",
        "player": int(squad_entry.get("player", -1)),  # get allowed
        "col": int(col),
        "row": int(row),
        "occupied_hexes": set(fp),
        "BASE_SHAPE": shape,
        "BASE_SIZE": size,
        "orientation": orient,
    }
    if level is not None:
        from engine.terrain_utils import resolved_floor_height_at
        anchor = (int(col), int(row))
        synth["occupied_hexes_by_model"] = {"_synth_model": anchor}
        # Niveau DEMANDÉ → hauteur résolue (§13.06) : une position candidate hors plancher est au
        # sol. Cf. `resolved_floor_height_at` — les chemins de lecture seule ne doivent pas lever.
        synth["floor_height_by_model"] = {
            "_synth_model": resolved_floor_height_at(
                game_state.get("terrain_areas", []),  # get allowed (board sans terrain)
                int(col), int(row), shape, size, orient, int(level),
            )
        }
        synth["MODEL_HEIGHT"] = _model_height_of(model_entry, squad_entry)
    return synth


CHARGE_THRESHOLD_INCHES = 12
#: Jet de charge MAXIMAL (11.02 etape 2 : « rolling 2D6 »). Numeriquement egal au seuil de
#: declaration ci-dessus, mais c'est une COINCIDENCE de regles, pas la meme grandeur : l'un borne
#: la portee de declaration, l'autre le resultat d'un de. Les confondre en une seule constante
#: ferait suivre en silence l'un a l'autre si l'un des deux changeait.
CHARGE_MAX_ROLL = 12


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
    # HORS TABLE, cote CIBLE comme cote SUJET. 11.02 conditionne la declaration a « within 12" » :
    # une unite pas encore posee, ou en reserves (20.01), n'est a AUCUNE distance.
    #
    # Sans ce controle, `_squad_model_positions` rend ses figurines a la sentinelle (-1,-1), et le
    # test des 12" ci-dessous — une distance de grille brute — repond VRAI pour tout chargeur assez
    # proche de l'origine du plateau. Cette fonction est la source UNIQUE que le masque ET le
    # commit `squad_charge` interrogent (cf. la construction des slots de charge dans
    # `build_squad_action_mask`) : le masque ouvrait donc un slot que `charge_build_valid_plan`
    # refuse ensuite, l'agent depensait son activation en `charge_fail`. C'est la divergence
    # masque/execution, pas une simple mesure fausse.
    units_cache = require_key(game_state, "units_cache")
    subject_entry = units_cache.get(str(squad_id))  # get allowed (escouade retiree = morte)
    if subject_entry is None or not entry_is_on_battlefield(subject_entry):
        return False
    for tsid in target_squad_ids:
        target_entry = units_cache.get(str(tsid))  # get allowed (idem)
        if target_entry is None or not entry_is_on_battlefield(target_entry):
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
    non_target_enemy_entries: List[Dict[str, Any]],
    occupied_by_others: Set[Tuple[int, int]],
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
    # Collision : autres escouades (sauf nous-meme). `occupied_by_others` est l'UNION des
    # empreintes, un PARAMÈTRE construit une fois par l'appelant — même raison que
    # `non_target_enemy_entries` ci-dessous : la réénumérer par cellule reconstruisait
    # l'empreinte de chaque escouade du plateau pour répondre « occupée ? ». Strictement
    # équivalent : `cell ∈ union(empreintes)` ⟺ `∃ empreinte, cell ∈ empreinte`.
    if cell in occupied_by_others:
        return False
    # ER des escouades non-cibles (bord-a-bord) : la figurine candidate ne doit pas
    # finir dans l ER d un ennemi NON-cible.
    # ``non_target_enemy_entries`` est un PARAMÈTRE, pas une énumération locale : cette fonction
    # est appelée par CELLULE dans le BFS de charge (jusqu'à ~14 641 itérations par anneau, cf. le
    # commentaire de `charge_build_valid_plan`), et la liste des ennemis non-ciblés est invariante
    # sur tout le plan — `units_cache` n'est pas muté entre le début du plan et la fin des BFS.
    # La construire ici, c'était un balayage COMPLET de `units_cache` (`_enemy_squad_ids`) plus un
    # lookup par ennemi, à chaque cellule testée. L'appelant la résout une fois.
    from engine.spatial_relations import unit_entries_within_engagement_zone
    ez = get_engagement_zone(game_state)
    synth = _synth_model_entry(game_state, str(squad_id), model_entry, col, row)
    for enemy_entry in non_target_enemy_entries:
        # `memoise=False` : `synth` porte une CELLULE CANDIDATE du BFS de charge, pas une
        # position occupée. Une clé neuve par cellule testée, jamais redemandée — cf. le
        # commentaire de `move_anchor_violates_engagement_clearance`.
        if unit_entries_within_engagement_zone(synth, enemy_entry, ez, game_state=game_state, memoise=False):
            return False
    return True


def _hex_cells_within_radius(col: int, row: int, radius: int) -> Iterator[Tuple[int, int]]:
    """Cellules a distance hexagonale <= ``radius`` de (col,row).

    Le carre ``|d_col| <= radius`` et ``|d_row| <= radius`` contient le disque en entier,
    parite de colonne comprise : la conversion offset -> cube decale bien la ligne d'environ
    ``d_col / 2``, mais la troisieme coordonnee cube (``|dx + dz| <= radius``) reprend
    exactement ce que ce decalage semblait ajouter. Verifie par force brute sur les deux
    parites dans `test_charge_plan_engagement_range.py` — une borne trop etroite amputerait
    le disque et refuserait des charges en silence.
    """
    if radius < 0:
        return
    for d_col in range(-radius, radius + 1):
        for d_row in range(-radius, radius + 1):
            nc, nr = col + d_col, row + d_row
            if calculate_hex_distance(col, row, nc, nr) <= radius:
                yield (nc, nr)


def _build_multi_source_dist_field(
    sources: List[Tuple[int, int]],
    board_cols: int,
    board_rows: int,
    target_cells: Optional[Set[Tuple[int, int]]] = None,
) -> Dict[Tuple[int, int], int]:
    """Champ de distance multi-source sur grille hex sans obstacle.

    Equivalent exact de min(calculate_hex_distance(c, r, oc, or_) for oc, or_ in sources)
    pour tout (c, r) du plateau : sur une grille sans obstacle la longueur du plus court
    chemin hex (BFS) est egale a la distance cube en ligne droite.
    Cout : O(board_cols * board_rows) au lieu de O(len(sources) * nb_candidats).

    target_cells : si fourni, le BFS s'arrete des que toutes ces cellules ont ete reglees —
    les distances restant correctes pour les cellules deja visitees.
    """
    from collections import deque
    dist: Dict[Tuple[int, int], int] = {}
    q: deque = deque()
    for pos in sources:
        if pos not in dist:
            dist[pos] = 0
            q.append(pos)
    remaining: Optional[int] = (
        sum(1 for c in target_cells if c not in dist)
        if target_cells is not None else None
    )
    while q:
        if remaining == 0:
            break
        cc, cr = q.popleft()
        nd = dist[(cc, cr)] + 1
        for nc, nr in get_hex_neighbors(cc, cr):
            if 0 <= nc < board_cols and 0 <= nr < board_rows and (nc, nr) not in dist:
                dist[(nc, nr)] = nd
                q.append((nc, nr))
                if remaining is not None and (nc, nr) in target_cells:  # type: ignore[operator]
                    remaining -= 1
    return dist


def _model_footprint_radius(
    game_state: Dict[str, Any], squad_id: str, model_entry: Dict[str, Any], col: int, row: int
) -> int:
    """Rayon hexagonal de l'empreinte d'une figurine posee en (col,row) (centre -> bord)."""
    synth = _synth_model_entry(game_state, squad_id, model_entry, col, row)
    fp = synth["occupied_hexes"]
    if not fp:
        return 0
    return max(calculate_hex_distance(col, row, fc, fr) for fc, fr in fp)


def charge_target_within_max_distance(
    charger_entry: Dict[str, Any],
    target_entry: Dict[str, Any],
    max_distance: int,
) -> bool:
    """11.04 BEFORE MOVING : la cible est-elle DANS LA DISTANCE MAXIMALE du chargeur ?

    « Select one or more enemy units that are within 12" of your unit AND WITHIN THE MAXIMUM
    DISTANCE of your unit » — la distance maximale etant le jet (11.04 MAXIMUM DISTANCE), moins
    2" si le vol est declare (21.03 « subtract 2" from the maximum distance »). SOURCE UNIQUE de
    cette borne : le pool gym (`charge_build_valid_plan`), l'offre PvP
    (`charge_build_valid_targets`), la declaration PvP et la validation du plan la lisent ici.

    C'est une question de PORTEE, pas d'engagement : mesure bord-a-bord par `ranged_in_range`,
    la primitive du tir, et NON `unit_entries_within_engagement_zone`. Les deux rendent le meme
    verdict horizontal (le facteur 1,5 de la norme est le meme des deux cotes), mais la primitive
    d'engagement ajoute le gate VERTICAL de 03.04 (5") : une cible a 3 subhex a l'aplomb d'un
    plancher haut serait sortie de la portee de charge au nom d'une regle qui ne parle que
    d'engagement. Le vertical, pour la charge, se paie sur le TRAJET (13.06, cf. le budget de
    `charge_build_valid_plan`), il ne rétrécit pas la portee de declaration.

    Metrique resolue par `engagement_distance_metric()` SANS `game_state` : cette fonction
    n'a pas `game_state` en parametre — c'est une mesure de PORTEE (11.04), pas d'ENGAGEMENT
    (03.04), elle utilise `ranged_in_range` et non `unit_entries_within_engagement_zone`.
    Les call-sites EZ (charge_build_valid_plan, charge_build_valid_targets) resolvent via
    `game_state=` depuis le chantier fix-engagement-zone-metric-game-state.

    HORS TABLE = pas une cible (11.02 « on the battlefield ») : reserves 20.01 ou unite pas encore
    posee ne sont a AUCUNE distance, et leurs figurines portent la sentinelle (-1,-1) — les
    mesurer rendrait une distance inventee.
    """
    from engine.combat_utils import ranged_in_range, socle_from_cache_entry
    from engine.spatial_relations import engagement_distance_metric, entry_is_on_battlefield

    if not entry_is_on_battlefield(charger_entry) or not entry_is_on_battlefield(target_entry):
        return False
    return ranged_in_range(
        socle_from_cache_entry(charger_entry),
        socle_from_cache_entry(target_entry),
        int(max_distance),
        engagement_distance_metric(),
    )


def charge_target_edge_distance_subhex(
    charger_entry: Dict[str, Any],
    target_entry: Dict[str, Any],
    max_distance: int,
) -> Optional[int]:
    """Distance 11.04 chargeur→cible, en subhex — la VALEUR du gate juste au-dessus.

    Mesure de journalisation, pas de decision : c'est la grandeur que 11.04 compare au jet
    (« within the maximum distance of your unit »), donc la seule directement comparable a un
    2D6. Meme primitive, meme metrique et meme granularite que
    `charge_target_within_max_distance` — par FIGURINE, `socle_from_cache_entry` construisant
    le socle sur `model_centers`. Une deuxieme facon de mesurer la meme charge serait la
    divergence que le selecteur unique existe pour empecher.

    `max_distance` est un ELAGAGE, pas un arrondi : `ranged_edge_distance` rend une valeur
    EXACTE tant qu'elle lui est inferieure ou egale, et une valeur simplement superieure
    au-dela. Il est OBLIGATOIRE — sans lui, le contour complet des socles est parcouru par
    couple (chargeur, ennemi) a CHAQUE activation de charge, sur le chemin chaud de
    l'entrainement, pour une courbe de telemetrie. Le gate jumeau juste au-dessus passe un cap
    exactement pour cette raison.

    Au-dela du cap → None, et c'est correct pour la mesure : le cap utile est
    `charge_max_distance` (11.02 « within 12\" »), donc un ennemi plus loin n'est a AUCUNE
    distance de declaration. Rendre la valeur elaguee ferait entrer un nombre faux dans une
    moyenne.

    Ce qu'elle ne dit PAS : le trajet reel. 11.04 exige aussi un plan legal dans le budget, et
    un mur peut rendre une cible proche inatteignable. Aucune mesure unique ne couvre les deux ;
    la distance de trajet n'existe ici que bornee par le jet (`_compute_plan_context`) ou par
    ancre (pool BFS), donc tronquee ou divergente de l'oracle par-figurine.

    Hors table (20.01, ou pas encore posee) → None, jamais un nombre : la sentinelle (-1,-1)
    de ces figurines rendrait une distance inventee.
    """
    from engine.combat_utils import ranged_edge_distance, socle_from_cache_entry
    from engine.spatial_relations import engagement_distance_metric, entry_is_on_battlefield

    if not entry_is_on_battlefield(charger_entry) or not entry_is_on_battlefield(target_entry):
        return None
    distance = ranged_edge_distance(
        socle_from_cache_entry(charger_entry),
        socle_from_cache_entry(target_entry),
        engagement_distance_metric(),
        max_distance=int(max_distance),
    )
    return None if distance > int(max_distance) else int(round(distance))


def charge_build_valid_plan(
    game_state: Dict[str, Any],
    squad_id: str,
    target_squad_ids: List[str],
    charge_roll: int,
    intent: int = 0,
) -> Optional[List[Tuple[str, int, int, int]]]:
    """Plan de charge multi-figurines (transaction atomique, aucune ecriture cache).

    Ordre de traitement : par index de figurine croissant.
    Pour chaque fig :
      (a) priorite : finir ENGAGEE avec une cible (11.04 WHILE MOVING « each model that can
          end its move engaged with one or more charge targets must do so »)
      (b) sinon : se rapprocher de la cible la plus proche, hors ER des non-cibles
    Validation finale : l'UNITE est engagee avec CHACUNE des cibles declarees (11.04 AFTER
    MOVING « your unit must be engaged with all of the charge targets » ; 03.04 : une unite
    est engagee des qu'UNE de ses figurines est dans l'ER d'une figurine ennemie). Coherency
    verifiee sur le plan final (03.01 ENDING A MOVE).

    ZONE D'ENGAGEMENT, PAS ADJACENCE (2026-08-01) : les destinations « au contact » etaient
    cherchees parmi les VOISINS HEXAGONAUX du centre d'une figurine cible. A l'echelle x1 ou
    un hex valait un socle, cela coincidait avec l'ER ; a l'echelle x5 un voisin est a 0,2"
    quand l'ER en vaut 2 (03.04) — le plan exigeait donc ~1,8" de mouvement de plus que la
    regle, socles compris, et AUCUNE charge n'aboutissait (mesure sur le modele du 2026-08-01 :
    0 reussite sur 23 declarations ; 11 des 12 charges d'escouades mono-figurine avaient
    pourtant une destination legale dans le budget). Les candidats sont desormais filtres par
    `unit_entries_within_engagement_zone`, la primitive que la validation finale utilise deja.
    Le surensemble enumere est borne par l'inegalite triangulaire hexagonale
    (`ez + rayon socle chargeant + rayon socle cible`), jamais par une reimplementation de l'ER.

    NIVEAU ET DESCENTE (§0.34, facettes reproduites sur la charge) : une charge est un move
    (11.04 EFFECT « moves as described in Moving (03) ») — la distance verticale descendue
    s'ajoute donc au jet (13.06 Moving Vertically), meme deduction conservatrice que le squad
    move rigide (`squad_descent_penalty_subhex`, max de la fig la plus haute). Et le plan PORTE
    le niveau d'arrivee (sol, `SQUAD_RIGID_MOVE_DESTINATION_LEVEL`) : sans lui, `commit_move`
    garde le niveau courant et une fig partie d'un etage restait marquee a l'etage sur une case
    sans plancher -> `floor_height_at` levait a la mise a jour du cache.

    Retourne le plan (4-uplets ``(mid, col, row, level)``) ou None si invalide (atomic :
    aucune fig deplacee). Le caller appelle commit_move(plan, gs, 'charge') sur succes.
    """
    if charge_roll <= 0:
        return None
    # Item 1.5 — per-state cache (masque + obs appellent la même fonction dans le même état).
    # Clé : (charger, targets, roll, intent, version) — la version garantit l'invalidation à
    # toute mutation de position/mort via _touch_unit_los. `intent` est requis : arm_charge_
    # placement_decision appelle la fonction avec intent=0..4 dans le même état de jeu, sans
    # bump de _unit_move_version entre les appels — sans lui toutes les variantes retournent
    # le plan intent=0 et L10 charge placement est silencieusement non-fonctionnel.
    # Pas de guard _los_batch : charge_build_valid_plan n'est jamais appelée pendant un batch.
    _cbvp_version = game_state["_unit_move_version"]
    _cbvp_key = (str(squad_id), tuple(str(t) for t in target_squad_ids), int(charge_roll), int(intent), _cbvp_version)
    _cbvp_cache = game_state.setdefault("_charge_plan_cache", {})
    _cbvp_hit = _cbvp_cache.get(_cbvp_key, _CBVP_MISS)
    if _cbvp_hit is not _CBVP_MISS:
        return _cbvp_hit
    if not charge_check_eligibility(game_state, squad_id, target_squad_ids):
        _cbvp_cache[_cbvp_key] = None
        return None
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    # `require_key` et non un `.get(..., {})` : `charge_check_eligibility`, appelée juste au-dessus,
    # exige déjà la clé — le repli était mort, et il aurait vidé l'union de collision construite
    # plus bas, donc rendu TOUTE cellule libre sans le moindre bruit.
    units_cache = require_key(game_state, "units_cache")
    mids = [m for m in squad_models.get(squad_id, []) if m in models_cache]  # get allowed
    if not mids:
        _cbvp_cache[_cbvp_key] = None
        return None

    from engine.phase_handlers.charge_handlers import _charge_budget_subhex
    from engine.phase_handlers.movement_handlers import squad_descent_penalty_subhex

    # Budget = jet 2D6 en subhex MOINS 2" si le vol est déclaré (21.03). Le calcul passe par
    # `_charge_budget_subhex`, source unique des budgets de charge : recalculer `roll × ish` en
    # ligne ici laissait le chemin d'exécution de l'agent (`squad_charge`) ignorer le malus, alors
    # que `squad_descent_penalty_subhex` lui accordait déjà l'ignore vertical du vol — soit
    # exactement le défaut « traversée gratuite », rejoué en phase de charge.
    # `max_distance` (11.04 MAXIMUM DISTANCE = le jet, moins 2" si le vol est declare) et `budget`
    # (ce que la figurine peut PARCOURIR) sont deux quantites distinctes : la descente 13.06 se
    # paie sur le trajet, elle ne rapetisse pas la portee de declaration des cibles.
    max_distance = _charge_budget_subhex(game_state, squad_id, int(charge_roll))
    budget = max(0, max_distance - squad_descent_penalty_subhex(game_state, squad_id))
    if budget <= 0:
        _cbvp_cache[_cbvp_key] = None
        return None

    # Toutes les positions de figurines cibles
    target_positions: List[Tuple[int, int]] = []
    for tsid in target_squad_ids:
        target_positions.extend(_squad_model_positions(game_state, str(tsid)))
    if not target_positions:
        _cbvp_cache[_cbvp_key] = None
        return None

    from engine.spatial_relations import unit_entries_within_engagement_zone
    ez = get_engagement_zone(game_state)
    # Résolu UNE fois pour tout le plan et passé à `_hex_legal_for_charge`, qui est appelée par
    # cellule dans les deux BFS ci-dessous. `charge_check_eligibility` a déjà prouvé l'escouade
    # présente dans le cache.
    _charger_entry = require_unit_from_cache(str(squad_id), game_state, "charge_build_valid_plan")
    _charger_player = int(require_key(_charger_entry, "player"))
    # `charge_check_eligibility` (appelée en tête) a DÉJÀ refusé toute cible absente du cache ET
    # toute cible hors table. Le filtre + le contrôle de longueur qui suivaient étaient donc morts,
    # et ils rangeaient une désynchronisation sous le même « plan invalide » que la destruction —
    # le piège §2 du lot charge (un refus de règle qui avale une erreur d'état).
    target_entries_by_id: List[Tuple[str, Dict[str, Any]]] = [
        (str(t), require_unit_from_cache(str(t), game_state, "charge_build_valid_plan/target"))
        for t in target_squad_ids
    ]
    # HORS TABLE — meme verdict que « detruite », pour la meme raison : la cible n'est pas sur le
    # champ de bataille (reserves 20.01, ou pas encore posee), donc 11.01 « within 12" » ne peut
    # pas etre satisfait et aucune figurine ne peut finir en ER avec elle. Le plan est invalide,
    # il n'est pas « vide » : c'est ce qu'appelle `_encode_unit_entity` pour dire a l'agent si une
    # charge est possible sur cet ennemi, et la reponse est non.
    if any(not entry_is_on_battlefield(te) for _tid, te in target_entries_by_id):
        return None
    # 11.04 BEFORE MOVING : « select one or more enemy units that are within 12" of your unit AND
    # WITHIN THE MAXIMUM DISTANCE of your unit ». Cette condition MANQUAIT : seule la seconde
    # moitie de la regle etait implementee (« existe-t-il une destination dans le budget d'ou l'on
    # finit engage ? »). Comme finir engage veut dire « a ez », le moteur acceptait toute cible a
    # jet + ez, soit une portee de charge DOUBLEE (mesure : jet de 2, cible a ~4" bord-a-bord,
    # plan valide). Corollaire de l'encart FAILED CHARGES du PDF 11 — « a result of 2 (a double 1)
    # is never sufficient, as a unit cannot be within engagement range (2") when it attempts a
    # charge » — qui n'etait donc pas vrai ici.
    #
    # Mesure bord-a-bord (`charge_target_within_max_distance`) et non `calculate_hex_distance`
    # centre-a-centre : c'est ce qui rend le raisonnement du PDF exact. Pas engage <=> hors de
    # `ez` bord-a-bord <=> hors de la portee d'un jet de 2 (= ez). Avec deux metriques
    # differentes, les deux bornes ne se recouperaient plus.
    if any(
        not charge_target_within_max_distance(_charger_entry, te, max_distance)
        for _tid, te in target_entries_by_id
    ):
        return None
    target_entries = [te for _tid, te in target_entries_by_id]

    # Résolus APRÈS les refus ci-dessus : ces deux constructions balayent tout `units_cache`, et
    # ce chemin est chaud (l'observation interroge la fonction pour chaque cible candidate).
    # Ennemis NON-ciblés, résolus une seule fois pour tout le plan : `_hex_legal_for_charge` les
    # réénumérait à chaque cellule de BFS. `_enemy_squad_ids` n'énumère que des ids lus dans
    # `units_cache`, donc une absence est une désynchronisation (d'où le `require`), pas un
    # ennemi disparu.
    # Union des cases occupées par les AUTRES escouades, résolue une seule fois : invariante sur
    # tout le plan (`units_cache` n'est pas muté entre ici et la fin des BFS ; les cellules
    # réservées par le plan en cours sont suivies à part, par `occupied_after`).
    _occupied_by_others = build_occupied_positions_set(game_state, exclude_unit_id=str(squad_id))
    _declared_targets = {str(t) for t in target_squad_ids}
    _non_target_enemies = [
        require_unit_from_cache(esid, game_state, "charge_build_valid_plan/enemy")
        for esid in _enemy_squad_ids(game_state, _charger_player)
        if esid not in _declared_targets
    ]

    # Positions pré-calculées pour le tri par intention (L10 placement de charge).
    _intent_obj_positions: List[Tuple[int, int]] = []
    if intent == 1:
        from engine.game_state import objective_hex_zones  # cycle : cf. imports paresseux ci-dessus
        _intent_obj_positions = [h for _, zone in objective_hex_zones(game_state) for h in zone]
    _intent_nontgt_positions: List[Tuple[int, int]] = []
    if intent == 2:
        for _nte in _non_target_enemies:
            for _fc, _fr in _nte.get("occupied_hexes", []):  # get allowed
                _intent_nontgt_positions.append((int(_fc), int(_fr)))

    # Portee d'engagement en distance CENTRE-A-CENTRE : borne superieure par inegalite
    # triangulaire hexagonale (ez borde-a-bord + les deux demi-socles). Surensemble : chaque
    # cellule retenue est ensuite validee par `unit_entries_within_engagement_zone`.
    self_radius = max(
        _model_footprint_radius(
            game_state, str(squad_id), models_cache[mid],
            int(models_cache[mid]["col"]), int(models_cache[mid]["row"]),
        )
        for mid in mids
    )
    target_radius = 0
    for _tid, te in target_entries_by_id:
        # `require_key` et non un defaut vide : une entree-cache sans empreinte donnerait un
        # rayon nul, donc un surensemble de cellules trop etroit, donc des charges refusees
        # sans que rien ne le signale — exactement le mode de panne qu'on vient de fermer.
        for fc, fr in require_key(te, "occupied_hexes"):
            d_to_model = min(
                calculate_hex_distance(fc, fr, tc, tr) for tc, tr in target_positions
            )
            if d_to_model > target_radius:
                target_radius = d_to_model
    # +1 : la forme d'une empreinte depend de la parite de sa colonne, le rayon mesure a la
    # position d'origine peut valoir un subhex de moins a la destination.
    engage_reach = ez + self_radius + target_radius + 1

    # Sortie O(1) : si meme la figurine la plus proche ne peut pas approcher a portee
    # d'engagement avec tout son budget, aucune fig n'engagera et la validation finale
    # echouerait. Evite d'enumerer le disque d'engagement pour une cible hors d'atteinte
    # (chemin chaud : l'observation interroge cette fonction pour chaque cible candidate).
    closest_gap = min(
        calculate_hex_distance(int(models_cache[mid]["col"]), int(models_cache[mid]["row"]), tc, tr)
        for mid in mids
        for tc, tr in target_positions
    )
    if closest_gap - engage_reach > budget:
        _cbvp_cache[_cbvp_key] = None
        return None

    # Cellules d'ou l'engagement est GEOMETRIQUEMENT possible (surensemble, cf. ci-dessus).
    # Construit avant le BFS : sert de borne d'arret (target_cells) pour limiter le BFS
    # aux cellules effectivement consultees par _engaged_sort_key (~500-900 hex a x5
    # au lieu de ~1800 = tout le plateau).
    engage_zone_cells: Set[Tuple[int, int]] = set()
    for tc, tr in target_positions:
        engage_zone_cells.update(_hex_cells_within_radius(tc, tr, engage_reach))

    # Champ de distance pré-calculé : BFS multi-source sans obstacle = distance cube exacte.
    # Remplace le min(calculate_hex_distance(...) for oc, or_ in sources) appelé par
    # _engaged_sort_key pour CHAQUE cellule candidate — O(board) au lieu de O(sources×cands).
    # Placé APRÈS la sortie O(1) : inutile de parcourir le plateau si la cible est hors d'atteinte.
    # intent==1 et intent==2 sont mutuellement exclusifs : un seul champ est jamais non-vide.
    _intent_positions: List[Tuple[int, int]] = (
        _intent_obj_positions if intent == 1 else
        _intent_nontgt_positions if intent == 2 else
        []
    )
    _dist_field: Dict[Tuple[int, int], int] = {}
    if _intent_positions:
        _board_cols: int = int(require_key(game_state, "board_cols"))
        _board_rows: int = int(require_key(game_state, "board_rows"))
        _dist_field = _build_multi_source_dist_field(
            _intent_positions, _board_cols, _board_rows, target_cells=engage_zone_cells
        )

    plan: List[Tuple[str, int, int, int]] = []
    occupied_after: Set[Tuple[int, int]] = set()  # cellules deja reservees par ce plan

    # Sélecteur de métrique de la CHARGE, pas celui du move : cf. `move_plan_distance_mode`.
    from engine.phase_handlers.charge_handlers import _charge_distance_metric
    _charge_metric = _charge_distance_metric(game_state)

    def _formation_gap(col: int, row: int) -> int:
        """Ecart a la derniere figurine deja placee — departage les candidats a egalite.

        Sans ce critere, deux destinations aussi bonnes (meme distance a la cible, meme trajet)
        sont departagees par l'ordre de balayage, qui privilegie un coin de l'anneau : les
        figurines partent en eventail et la coherency (03.03) rejette le plan complet.
        """
        if not plan:
            return 0
        _prev_mid, prev_col, prev_row, _prev_lvl = plan[-1]
        return calculate_hex_distance(prev_col, prev_row, col, row)

    def _engaged_sort_key(nc: int, nr: int, d_orig: int, gap: int) -> tuple:
        """Clé de tri pour les candidats d'engagement, paramétrée par l'intention L10."""
        if intent == 1:  # Objectif : priorité à la cellule la plus proche d'un objectif
            return (_dist_field.get((nc, nr), 0), d_orig, gap, nc, nr)
        if intent == 2:  # Isolation : priorité aux cellules les plus loin des ennemis non-ciblés
            return (-_dist_field.get((nc, nr), 0), gap, nc, nr)
        if intent == 3:  # Pénétration : figurine avance au maximum du budget
            return (-d_orig, gap, nc, nr)
        if intent == 4:  # Étalé : formation la plus dispersée
            return (-gap, d_orig, nc, nr)
        return (d_orig, gap, nc, nr)  # intent == 0 (Serré, comportement actuel)

    for mid in mids:
        m = models_cache[mid]
        orig_col, orig_row = int(m["col"]), int(m["row"])
        orig_dist_to_tgt = min(
            calculate_hex_distance(orig_col, orig_row, tc, tr) for tc, tr in target_positions
        )
        # 11.04 EFFECT « Your unit moves as described in Moving (03) » : la borne du charge move
        # est un TRAJET legal, pas une distance a vol d'oiseau. Le niveau du trajet est celui
        # d'arrivee du plan (SOL), miroir exact du squad move rigide. Ce predicat BORNE DEJA par
        # le budget dans ses trois geometries — il remplace donc, et ne double pas, le
        # `calculate_hex_distance(origine, cellule) <= budget` qui filtrait les candidats.
        _reachable = model_reach_predicate(
            game_state, str(squad_id), _charger_player, m, budget,
            SQUAD_RIGID_MOVE_DESTINATION_LEVEL, metric=_charge_metric,
        )

        # (a) Tentative d'ENGAGEMENT (03.04 : ER = 2", bord-a-bord — pas la cellule voisine
        #     du centre ennemi). 11.04 impose de finir plus pres d'une cible, donc une
        #     destination engageante mais qui eloigne n'est pas retenue.
        # Chaque entrée : (clé de tri selon l'intention L10, nc, nr)
        engaged_candidates: List[Tuple[tuple, int, int]] = []
        for nc, nr in engage_zone_cells:
            if (nc, nr) in occupied_after:
                continue
            if not _reachable(nc, nr):
                continue
            d_orig = calculate_hex_distance(orig_col, orig_row, nc, nr)
            if min(calculate_hex_distance(nc, nr, tc, tr) for tc, tr in target_positions) >= orig_dist_to_tgt:
                continue
            if not _hex_legal_for_charge(
                nc, nr, game_state, squad_id, m, _non_target_enemies, _occupied_by_others
            ):
                continue
            synth = _synth_model_entry(game_state, str(squad_id), m, nc, nr)
            # `memoise=False` : même cellule candidate de BFS que ci-dessus.
            if not any(
                unit_entries_within_engagement_zone(synth, te, ez, game_state=game_state, memoise=False)
                for te in target_entries
            ):
                continue
            engaged_candidates.append(
                (_engaged_sort_key(nc, nr, d_orig, _formation_gap(nc, nr)), nc, nr)
            )
        picked: Optional[Tuple[int, int]] = None
        if engaged_candidates:
            engaged_candidates.sort()
            _, pc, pr = engaged_candidates[0]
            picked = (pc, pr)
        else:
            # (b) Engagement hors d'atteinte : avancer vers la cible la plus proche
            nearest_target = min(
                target_positions,
                key=lambda tp: calculate_hex_distance(orig_col, orig_row, tp[0], tp[1]),
            )
            tc, tr = nearest_target
            # (dist_to_target, ecart a la fig precedente, col, row)
            best_cand: Optional[Tuple[int, int, int, int]] = None
            # Anneaux DECROISSANTS depuis le budget : la figurine qui ne peut pas engager doit
            # suivre le reste de l'escouade, pas avancer d'un seul subhex. Avec l'ordre croissant
            # (etat anterieur au 2026-08-01), elle s'arretait au premier anneau utile pendant que
            # ses camarades bondissaient au contact — la coherency finale (03.03) rejetait alors
            # le plan, et AUCUNE escouade de plus d'une figurine ne pouvait charger.
            for d in range(budget, 0, -1):
                # PERIMETRE du carre, pas son interieur : les colonnes de bord balayent toutes
                # les lignes, les autres seulement les deux extremes. Balayer le carre plein et
                # jeter l'interieur (`max(abs(...)) != d`) coute (2d+1)^2 iterations pour 8d
                # cellules utiles — invisible tant qu'on partait de d=1 et qu'on sortait au
                # premier anneau, ruineux depuis qu'on part du budget (a x5, un jet de 12 fait
                # d=60, soit 14 641 iterations par anneau au lieu de 480).
                for d_col in range(-d, d + 1):
                    row_values = range(-d, d + 1) if abs(d_col) == d else (-d, d)
                    for d_row in row_values:
                        nc = orig_col + d_col
                        nr = orig_row + d_row
                        if (nc, nr) in occupied_after:
                            continue
                        # L'anneau parcouru est CARRE en coordonnees offset ; la borne de charge,
                        # elle, est un TRAJET legal (11.04 MAXIMUM DISTANCE = le jet). Sans ce
                        # controle, un pas diagonal sortait du budget — et une charge traversait
                        # un mur.
                        if not _reachable(nc, nr):
                            continue
                        if not _hex_legal_for_charge(
                            nc, nr, game_state, squad_id, m, _non_target_enemies,
                            _occupied_by_others,
                        ):
                            continue
                        cand_d = calculate_hex_distance(nc, nr, tc, tr)
                        if cand_d >= orig_dist_to_tgt:
                            continue  # doit etre strictement plus proche
                        cand = (cand_d, _formation_gap(nc, nr), nc, nr)
                        if best_cand is None or cand < best_cand:
                            best_cand = cand
                if best_cand is not None:
                    break  # premier anneau utile retenu
            if best_cand is not None:
                _cd, _gap, pc, pr = best_cand
                picked = (pc, pr)
        if picked is None:
            _cbvp_cache[_cbvp_key] = None
            return None  # cette fig ne peut bouger legalement → charge echouee
        # Niveau d'arrivee SOL, comme le plan rigide de move : le moteur ne monte jamais, et
        # « pas de niveau » signifierait pour commit_move « garder le niveau courant » (etage).
        plan.append((mid, picked[0], picked[1], SQUAD_RIGID_MOVE_DESTINATION_LEVEL))
        occupied_after.add(picked)

    # Validation finale (11.04 AFTER MOVING) : l'UNITE doit etre engagee avec CHACUNE des
    # cibles declarees. 03.04 : l'unite est engagee des qu'UNE de ses figurines est dans l'ER
    # d'une figurine ennemie — exiger que TOUTES le soient (etat anterieur au 2026-08-01)
    # interdisait toute charge d'escouade nombreuse, aucune formation ne mettant douze socles
    # au contact du meme ennemi.
    engaged_targets: Set[str] = set()
    for mid, nc, nr, _lvl in plan:
        synth = _synth_model_entry(game_state, str(squad_id), models_cache[mid], nc, nr)
        for tid, te in target_entries_by_id:
            if tid in engaged_targets:
                continue
            if unit_entries_within_engagement_zone(synth, te, ez, game_state=game_state):
                engaged_targets.add(tid)
    if len(engaged_targets) != len(target_entries_by_id):
        _cbvp_cache[_cbvp_key] = None
        return None

    # Coherency finale
    plan_positions = {mid: (nc, nr) for mid, nc, nr, _lvl in plan}
    if not _validate_plan_coherency(plan_positions, game_state):
        _cbvp_cache[_cbvp_key] = None
        return None

    _cbvp_cache[_cbvp_key] = plan
    return plan


def commit_move(
    plan: MovePlan,
    game_state: Dict[str, Any],
    move_type: str,
) -> None:
    """Applique le plan complet en une passe et positionne les flags post-move.

    Pre-condition: plan validé via validate_move_plan (ce helper ne re-valide pas).

    Entrées de plan : ``(mid, col, row, level)`` (étages) ou ``(mid, col, row, level, orientation)``
    (pivot socle par-fig). Le 4ᵉ élément est OBLIGATOIRE (`plan_entry_level`, frontière de
    décodage) et porte le niveau DEMANDÉ — un hint, pas un fait : `place_model_at_effective_level`
    le résout (§13.06) avant d'écrire, donc une figurine dont l'empreinte ne tient pas sur le
    plancher visé est posée au SOL. Cette résolution vivait chez le seul appelant `commit_move_plan`
    (mouvement) ; les six autres — charge, pile-in, consolidation, gym, plan rigide — écrivaient le
    niveau brut. Le 5ᵉ élément (0..5) fixe l'orientation ; absent/None = orientation inchangée,
    et c'est alors celle déjà portée par la figurine qui oriente l'empreinte.
    Flags:
        "advance"   → units_advanced.add(squad_id)
        "fall_back" → units_fled.add(squad_id)
        "normal"/"charge"/"pile_in"/"overrun_pile_in"/"consolidation" → aucun flag
    """
    valid_types = ("normal", "advance", "fall_back", "charge", "pile_in", "overrun_pile_in", "consolidation")
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
    # Distance PARCOURUE par figurine, mesurée AVANT d'appliquer les positions (les origines
    # sont lues dans models_cache). Sert la clause 3 de [HEAVY] 24.16 (« aucune figurine n a
    # bougé de plus de 3" ce tour ») ET l'observation de l'agent (V11 §9.2.5) — une seule
    # donnée, deux consommateurs.
    #
    # PÉRIMÈTRE : les moves de la PHASE DE MOUVEMENT uniquement. Ce n'est pas une omission :
    #  - pour [HEAVY], c'est EXACT — l'ordre des phases (PDF 07.02 : Commande, Mouvement, Tir,
    #    Charge, Combat) garantit qu'au moment du tir, seuls des moves de phase de mouvement ont
    #    pu avoir lieu dans ce tour ;
    #  - charge / pile-in / consolidation se mesurent avec une AUTRE géométrie (champ euclidien
    #    any-angle par-figurine, `_euclidean_move_field`), pas avec le champ hex géodésique du
    #    move. Les compter ici avec la mauvaise métrique produirait un chiffre faux ; les
    #    compter à vol d'oiseau SOUS-estimerait le trajet, donc rendrait [HEAVY] laxiste.
    if move_type in MOVE_PHASE_MOVE_TYPES:
        _distances = move_plan_path_distances(plan, game_state, move_type)
        _moved_by_model = game_state.setdefault("moved_distance_by_model", {})
        for _mid, _dist in _distances.items():
            _moved_by_model[_mid] = _moved_by_model.get(_mid, 0.0) + _dist
    # Choke-point LoS (D1) : un seul batch pour tout le plan → 1 invalidation ciblée par unité
    # + 1 bump, émis par _touch_unit_los depuis update_model_position / update_units_cache_position.
    _los_owned = _los_begin_batch(game_state)
    try:
        for entry in plan:
            mid, nc, nr = str(entry[0]), int(entry[1]), int(entry[2])
            place_model_at_effective_level(
                game_state, mid, nc, nr,
                plan_entry_level(entry), orientation=plan_entry_orientation(entry),
            )
        if move_type == "advance":
            game_state.setdefault("units_advanced", set()).add(squad_id)
        elif move_type == "fall_back":
            game_state.setdefault("units_fled", set()).add(squad_id)
        elif move_type == "charge":
            game_state.setdefault("units_charged", set()).add(squad_id)
    finally:
        _los_end_batch(game_state, _los_owned)


# ============================================================================
# PENDING INTENTS — SHOOT / FIGHT (squad_multi_figurines.md PR3 3a)
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
# SQUAD SHOOTING — declaration / lock (squad_multi_figurines.md PR3 3b)
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
        weapons = ranged_weapons(m)
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
    attacker_model: Dict[str, Any],
    ac: int,
    ar: int,
    target_squad_id: str,
    range_subhex: int,
    only_target_mids: Optional[Set[str]] = None,
    require_visibility: bool = True,
) -> bool:
    """Eligibilite portee + LoS per-fig, alignee sur le chemin canonique (valid_target_pool_build).

    Pour CHAQUE figurine cible vivante : si son socle est a portee bord-a-bord
    (<= range_subhex) ET si >= 1 cellule de son empreinte est visible depuis
    l'empreinte du socle tireur (regle 06.01, visibilite binaire par modele — pas de
    seuil de ratio), la cible est atteignable. Renvoie True des qu'une figurine satisfait
    les deux.

    Alignement (regles 01.04 + 06.01) : origine = empreinte COMPLETE du socle de la
    figurine tireuse (pas son seul centre) et distance mesuree bord-a-bord socle↔socle
    via ``ranged_edge_distance`` (pas centre-a-centre). Sans cet alignement, une grosse
    base dont le centre est masque par un terrain (mais dont un bord voit la cible) etait
    grisee a tort en phase de tir alors que le move-preview l'affichait ciblable. Empreinte
    evaluee PAR figurine cible (pas l'union de l'escouade). Board ×1 (base_size 1) :
    socle = 1 hex → distance et LoS identiques a l'ancien test centre.

    ``require_visibility=False`` — tir INDIRECT 10.07 : « [INDIRECT FIRE] weapons in your unit can
    target units that are NOT VISIBLE to the attacking model ». Seule la VISIBILITE tombe ; la
    PORTEE reste exigee, et c est tout ce que la regle retire. Deux gates disparaissent alors, et
    les deux sont des gates de visibilite :
      - le trace de ligne de vue lui-meme (06.01 / 13.10 obscurcissant) ;
      - la detection d une unite « hidden » 13.09, qui n est PAS une regle de portee mais une
        restriction de visibilite (« it can only be VISIBLE to enemy models that are within its
        detection range »). Une regle qui n exige plus la visibilite ne peut pas buter dessus.
    Le contournement ne s applique JAMAIS a [PRECISION] 24.28, dont l appelant garde le defaut :
    24.28 exige un CHARACTER « VISIBLE to one or more of the attacking models », et c est une
    exigence propre a cette regle-la, pas la ligne de vue du tir.
    """
    # Obscuring-aware LoS (single source of truth): the firing model (single hex at ac,ar) must see
    # >= 1 cell of a target model's footprint (rule 06.01, binary), with dense walls AND obscuring
    # terrain blocking (rule 13.10). Routed through the same primitive as the non-squad path so the
    # squad target pool can never include a target the model cannot actually see.
    from engine.phase_handlers.shooting_handlers import _compute_visibility_with_obscuring
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    units_cache = require_key(game_state, "units_cache")
    # Dix lignes plus bas, la MÊME condition sur `squad_models` LÈVE (`not in squad_models`).
    # Ici elle rendait « cible inatteignable » : le motif §2 du lot charge, un site bruyant et son
    # jumeau muet dans la même fonction. Les appelants (`_model_can_shoot_target`, lui-même appelé
    # par `declare_attack_model`) ont déjà prouvé la cible vivante.
    base_unit = require_unit_from_cache(
        str(target_squad_id), game_state, "_attacker_model_can_reach_squad"
    )
    # Rule 13.09: hidden unit only targetable within detection range (15").
    _target_unit = get_unit_by_id(game_state, str(target_squad_id))
    target_squad_id_str = str(target_squad_id)
    if target_squad_id_str not in squad_models:
        raise KeyError(f"_attacker_model_can_reach_squad: unit {target_squad_id} not in squad_models")
    target_mids = squad_models[target_squad_id_str]
    # Restriction a un sous-ensemble de figurines cibles ([PRECISION] 24.28 : « one or more
    # CHARACTER models VISIBLE to one or more of the attacking models »). None = escouade entiere.
    if only_target_mids is not None:
        target_mids = [m for m in target_mids if m in only_target_mids]
    # Rule 13.09 + 13.5 (Gone to Ground) : detection évaluée PAR FIGURINE dans la boucle ci-dessous.
    target_hidden = bool(_target_unit.get("hidden")) if _target_unit else False
    base_detection_subhex = (
        float(require_key(game_rules, "detection_range"))
        * int(require_key(game_state, "inches_to_subhex"))
    ) if target_hidden else 0.0
    detection_penalty = 3 * int(require_key(game_state, "inches_to_subhex"))
    from engine.phase_handlers.shooting_handlers import (
        _get_dense_wall_set, _model_footprint_not_fully_visible_due_to_solid,
        _walls_around_occupied_floor,
    )
    dense_wall_set = _get_dense_wall_set(game_state) if target_hidden else set()
    shooter_anchor = (ac, ar)
    # Portee + LoS alignees sur valid_target_pool_build : origine = empreinte COMPLETE du
    # socle tireur (regle 06.01) et distance bord-a-bord socle↔socle (regle 01.04), pas
    # centre-a-centre. Board ×1 (base_size 1) → socle = 1 hex, comportement centre inchange.
    from engine.hex_utils import Socle
    from engine.combat_utils import ranged_edge_distance
    from engine.phase_handlers.shooting_handlers import _ranged_distance_metric
    metric = _ranged_distance_metric(game_state)
    shooter_hexes = list(_compute_unit_occupied_hexes(ac, ar, attacker_model, game_state))
    ignored_wall_hexes = _walls_around_occupied_floor(game_state, attacker_model, shooter_hexes)
    shooter_socle = Socle(
        attacker_model["BASE_SHAPE"], attacker_model["BASE_SIZE"], ac, ar,
        set(shooter_hexes), [(ac, ar)],
    )
    # LoS 3D plancher-occulteur : sommet vertical + dalle occultante du tireur, hoistés (constants
    # sur toutes les cibles). Actif dès qu'un côté est à l'étage (level >= 1) ; sol↔sol → occluders
    # vides → tracé 2D inchangé (non-régression). MODEL_HEIGHT requis sur toute vraie unité roster ;
    # fetch seulement si le tireur est à l'étage (fetch paresseux sinon, quand une CIBLE élevée
    # active la 3D — le tireur reste alors au sol : z = 0 + MODEL_HEIGHT, sans dalle).
    from engine.phase_handlers.shooting_handlers import _fig_z_and_occluder
    shooter_level = int(attacker_model.get("level", 0))  # get allowed (champ optionnel, défaut sol)
    shooter_squad_id = str(require_key(attacker_model, "squad_id"))
    shooter_z: Optional[float] = None
    shooter_occ = None
    # Hauteur de la FIGURINE qui tire, pas de son escouade — même raison que son socle deux lignes
    # plus haut (`attacker_model`), et même convention que `_synth_model_entry` : la figurine quand
    # elle la porte (`build_models_cache` la propage), l'escouade sinon. Un personnage attaché plus
    # haut voyait par-dessus un occulteur à la taille de la troupe qu'il accompagne, ou l'inverse.
    if shooter_level >= 1:
        _s_mh = float(_model_height_of(attacker_model, units_cache[shooter_squad_id]))
        shooter_z, shooter_occ = _fig_z_and_occluder(
            game_state, shooter_level, shooter_hexes, _s_mh
        )
    for mid in target_mids:
        tm = models_cache.get(mid)
        if tm is None:
            continue
        if not model_is_on_board(tm):
            continue  # modèle hors-board (réserves stratégiques) — non ciblable
        tc = int(tm["col"])
        tr = int(tm["row"])
        target_level = int(tm.get("level", 0))  # get allowed (champ optionnel, défaut sol)
        footprint = list(_compute_unit_occupied_hexes(tc, tr, tm, game_state))
        target_socle = Socle(
            tm["BASE_SHAPE"], tm["BASE_SIZE"], tc, tr,
            set(footprint), [(tc, tr)],
        )
        edge = ranged_edge_distance(
            shooter_socle, target_socle, metric, max_distance=range_subhex
        )
        if edge > range_subhex:
            continue
        if target_hidden and require_visibility:
            # Cette figurine ne rend la cible atteignable que si elle est dans SA detection range :
            # base, ou base−3" si elle est "gone to ground" (masquée par un terrain Solid intervenant
            # pour ce tireur, rule 13.5). Le test LoS dense n'est fait que dans la bande utile.
            eff_detection = base_detection_subhex
            if base_detection_subhex - detection_penalty < edge <= base_detection_subhex:
                if dense_wall_set and _model_footprint_not_fully_visible_due_to_solid(
                    game_state, shooter_anchor, shooter_hexes, footprint, dense_wall_set,
                    ignored_wall_hexes,
                ):
                    eff_detection = base_detection_subhex - detection_penalty
            if edge > eff_detection:
                continue
        # 10.07 : la portee suffit, la cible n a pas a etre visible. On sort AVANT le trace —
        # ne pas le calculer pour jeter son resultat est aussi ce qui garde le cout de la regle
        # nul sur le chemin de ciblage.
        if not require_visibility:
            return True
        # LoS 3D : dalles occultantes du tireur et/ou de cette cible + sommets verticaux (pouces).
        # Actif seulement si un côté est à l'étage ; sinon floor_occ=None → tracé 2D inchangé.
        floor_occ = None
        z_start = None
        z_end = None
        if shooter_level >= 1 or target_level >= 1:
            if shooter_z is None:
                # Tireur au sol, cible élevée : z tireur = 0 (sol) + MODEL_HEIGHT, sans dalle.
                shooter_z = float(
                    _model_height_of(attacker_model, units_cache[shooter_squad_id])
                )
            z_start = shooter_z
            # Hauteur de la figurine VISÉE (jumeau du tireur ci-dessus) : `tm` porte la sienne.
            _t_mh = float(_model_height_of(tm, base_unit))
            z_end, target_occ = _fig_z_and_occluder(
                game_state, target_level, footprint, _t_mh
            )
            floor_occ = [o for o in (shooter_occ, target_occ) if o is not None] or None
        visible, total, _ = _compute_visibility_with_obscuring(
            game_state, shooter_anchor, shooter_hexes, (tc, tr), footprint,
            ignored_wall_hexes=ignored_wall_hexes,
            floor_occluders=floor_occ, z_start=z_start, z_end=z_end,
        )
        if visible > 0:
            return True
    return False


def _shoot_engagement_blocks_target(
    game_state: Dict[str, Any],
    attacker_squad_id: str,
    target_squad_id: str,
    weapon_is_close_quarters: bool,
    shooter_model: Dict[str, Any],
    weapon_is_blast: bool,
) -> bool:
    """Regles de ciblage tir 40K manquantes au chemin per-figurine (portee+LoS seuls).

    Replique EXACTEMENT _is_valid_shooting_target (chemin legacy/RL) :
      - 04.02 : la cible doit etre Unengaged -> interdit si elle est dans l'EZ
        d'une unite alliee au tireur (_friendly_engagement_blocks_ranged_shot).
      - 10.06 : si le tireur est engage, il ne peut tirer qu'avec une arme CLOSE_QUARTERS,
        et seulement sur l'unite avec laquelle il est engage.
    Returns True si le tir est INTERDIT par ces regles.
    """
    from engine.phase_handlers.shooting_handlers import (
        _friendly_engagement_blocks_ranged_shot,
        _is_adjacent_to_enemy_within_cc_range,
    )
    from engine.spatial_relations import (
        get_engagement_zone,
        unit_entries_within_engagement_zone,
    )

    units_cache = require_key(game_state, "units_cache")
    sid = str(attacker_squad_id)
    tid = str(target_squad_id)
    # Cette fonction rend « le tir est INTERDIT » : le `return False` de repli AUTORISAIT donc le
    # tir sur une désynchronisation, en sautant les contrôles 04.02 et 10.06.
    shooter_entry = require_unit_from_cache(
        sid, game_state, "_shoot_engagement_blocks_target/shooter"
    )
    target_entry = require_unit_from_cache(
        tid, game_state, "_shoot_engagement_blocks_target/target"
    )

    ez = get_engagement_zone(game_state)
    enemy_adjacent_to_shooter = unit_entries_within_engagement_zone(
        shooter_entry, target_entry, ez, game_state=game_state
    )
    shooter_unit = require_unit_by_id(game_state, sid)
    shooter_is_engaged = _is_adjacent_to_enemy_within_cc_range(game_state, shooter_unit)

    # 10.06 « WHILE SHOOTING », deux volets selon la figurine :
    #  - Non-MONSTER/Non-VEHICLE : « you can only select [CLOSE-QUARTERS] weapons and you can
    #    only select enemy units that are engaged with your unit as targets » ;
    #  - MONSTER/VEHICLE : peut selectionner n importe quelle arme (au prix d un -1 au jet de
    #    touche, applique a la RESOLUTION), MAIS « if that attack is made with a [BLAST] weapon,
    #    it still cannot target a unit your unit is engaged with ».
    if shooter_is_engaged:
        if _model_is_monster_or_vehicle(shooter_model):
            if weapon_is_blast and enemy_adjacent_to_shooter:
                return True
        else:
            if not weapon_is_close_quarters:
                return True
            if not enemy_adjacent_to_shooter:
                return True
    elif enemy_adjacent_to_shooter and not weapon_is_close_quarters:
        return True

    # 04.02 : cible engagee avec une unite alliee au tireur -> Unengaged viole.
    shooter_player_int = int(shooter_entry["player"])
    if _friendly_engagement_blocks_ranged_shot(
        game_state,
        sid,
        shooter_player_int,
        target_entry,
        tid,
        enemy_adjacent_to_shooter,
        units_cache,
    ):
        return True
    return False


def _advance_blocks_weapon(
    game_state: Dict[str, Any], squad_id: str, weapon: Dict[str, Any]
) -> bool:
    """10.05 : apres un advance, une arme non-[ASSAULT] ne peut PAS etre selectionnee.

    « ASSAULT SHOOTING 10.05 — WHILE SHOOTING: You can only select [ASSAULT] weapons to
    make attacks with. » Le tir normal (10.04) exige de son cote « did not make an advance
    move this turn » : une unite qui a avance ne dispose donc d aucun autre type de tir.

    Meme critere que le chemin mono-figurine (weapon_availability_check) et que le masque
    gym (shooting_type_allows_weapon sous SHOOTING_TYPE_ASSAULT), via la meme fonction
    feuille : l exception `shoot_after_advance` (regle d unite) reste honoree.

    Volet ADVANCE seulement, a dessein : le volet arme de 10.06 est deja porte par
    `_shoot_engagement_blocks_target` (appele juste apres, avec les restrictions de CIBLE
    qui vont avec), et 10.04 ne restreint aucune arme. Verifier ici le type de tir complet
    dupliquerait 10.06 au lieu de le partager.
    """
    if squad_id not in game_state.get("units_advanced", set()):
        return False
    from engine.phase_handlers.shooting_handlers import (
        _can_unit_shoot_after_advance_with_weapon,
    )
    unit = require_unit_by_id(game_state, squad_id)
    return not _can_unit_shoot_after_advance_with_weapon(unit, weapon)


def _model_can_shoot_target(
    game_state: Dict[str, Any], attacker_model: Dict[str, Any], target_squad_id: str
) -> bool:
    """Eligibilite d une figurine attaquante a tirer sur une escouade cible.

    Per-fig (squad_multi_figurines.md §"LOS cache — strategie avec escouades") : la cible est
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
    weapons = ranged_weapons(attacker_model)
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
    if _advance_blocks_weapon(game_state, str(attacker_model["squad_id"]), weapon):
        return False

    ac = int(attacker_model["col"])
    ar = int(attacker_model["row"])
    # 10.07 : sous tir indirect, une arme [INDIRECT FIRE] cible sans ligne de vue. Le predicat
    # est PARESSEUX (declaration d arme testee avant le type de tir), donc gratuit pour les 229
    # autres profils de l armurerie.
    if not _attacker_model_can_reach_squad(
        game_state, attacker_model, ac, ar, target_squad_id, range_subhex,
        require_visibility=not indirect_shooting_applies(
            game_state, str(attacker_model["squad_id"]), weapon
        ),
    ):
        return False
    if _shoot_engagement_blocks_target(
        game_state,
        str(attacker_model["squad_id"]),
        target_squad_id,
        weapon_has_rule(weapon, "CLOSE_QUARTERS"),
        attacker_model,
        weapon_has_rule(weapon, "BLAST"),
    ):
        return False
    return True


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

    # Primitive F (chantier 06, passe 6) — suppress_target_on_shooting (Indiscriminate Detonations) :
    # stocker la cible prioritaire sur l unite attaquante pour l appliquer a la fin du tir.
    attacker_unit = require_unit_by_id(game_state, str(attacker_squad_id))
    attacker_unit["_last_shoot_target_id"] = str(priority_target_squad_id)

    def _target_size(target_sid: str) -> int:
        return sum(
            1 for mid in squad_models.get(target_sid, []) if mid in models_cache  # get allowed
        )

    # 10.04-10.06 : type de tir applicable. Il commande QUELLES armes sont selectionnables
    # (volet « WHILE SHOOTING ») — cf. resolve_squad_shooting_type.
    shooting_type = resolve_squad_shooting_type(game_state, attacker_squad_id)
    if shooting_type is None:
        return intents

    def _target_for_weapon(model: Dict[str, Any], widx: int) -> Optional[str]:
        """04.02 : chaque ARME choisit SA cible. Les portees different d une arme a l autre,
        donc la cible prioritaire du slot d action peut etre hors d atteinte de l une et pas
        de l autre — d ou une resolution par arme et non par figurine."""
        if _model_can_shoot_target_with_weapon(game_state, model, priority_target_squad_id, widx):
            return priority_target_squad_id
        for slot_sid in eligible_target_slots:
            if slot_sid == priority_target_squad_id:
                continue
            if _model_can_shoot_target_with_weapon(game_state, model, slot_sid, widx):
                return slot_sid
        return None

    for mid in squad_models.get(attacker_squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is None:
            continue
        weapons = ranged_weapons(m)
        # 04.01 « You can select ONE OR MORE ranged weapons that model has » : on declare
        # TOUTES les armes utilisables, pas la seule `selectedRngWeaponIndex` (qui vaut 0
        # pendant toute la partie en gym — ce champ n est ecrit que par le flux PvP manuel).
        usable: List[Tuple[int, str]] = []
        for widx in squad_model_shootable_weapon_indices(
            game_state, attacker_squad_id, m, shooting_type
        ):
            target = _target_for_weapon(m, widx)
            if target is not None:
                usable.append((widx, target))
        if not usable:
            continue  # fig bloquee, ne tire pas

        # 24.07 (SIDEARMS, PDF 04) : hors MONSTER/VEHICLE, une figurine choisit SOIT ses armes
        # [CLOSE-QUARTERS], SOIT ses autres armes de tir — jamais les deux. Defaut retenu : la
        # famille qui place le PLUS d armes sur une cible ; a egalite, les armes principales
        # (non-[CLOSE-QUARTERS]), le pistolet etant une arme de secours. Ce defaut n est PAS
        # l optimum en toute circonstance (cf. [HAZARDOUS] : chaque arme declaree = un jet de
        # risque) — c est precisement pourquoi ce choix est un candidat P3, mesurable une fois
        # ce defaut correct (V11_entity_encoder_pointer.md §5.3).
        if not _model_is_monster_or_vehicle(m):
        
            cq = [(i, t) for i, t in usable if weapon_has_rule(weapons[i], "CLOSE_QUARTERS")]
            other = [(i, t) for i, t in usable if (i, t) not in cq]
            if cq and other:
                usable = cq if len(cq) > len(other) else other

        for widx, target in usable:
            # F3 fix (audit) : resoudre NB UNE SEULE FOIS a la declaration, stocke dans l intent.
            # Sinon le double-roll de _resolve_squad_shoot decouple le nombre d attaques effectif
            # pour les armes a NB variable (D3/D6).
            intents.append({
                "model_id": mid,
                "weapon_index": widx,
                "target_unit_id": target,
                "target_squad_size_at_declaration": _target_size(target),
                "n_attacks_resolved": _resolve_intent_nb(
                    weapons, widx, f"squad_declare_shoot_NB_{mid}_{widx}"
                ),
            })
    return intents


def _resolve_intent_nb(
    weapons: List[Any], weapon_idx: int, roll_label: str
) -> int:
    """Resout le NB d une arme UNE SEULE FOIS a la declaration (fix audit F3).

    Le label sert de tag debug a resolve_dice_value (aucun impact sur le RNG) ET nomme la
    figurine + l arme dans les erreurs ci-dessous.

    Aucun repli silencieux, a aucun des trois etages : tous les appelants derivent
    `weapon_idx` de la liste `weapons` elle-meme (enumerate / index selectionne deja
    valide par le controle d eligibilite), et les 428 profils d armes des rosters portent
    tous `NB`. Un index hors limites, un profil qui n est pas un dict ou un `NB` absent
    sont donc des defauts de construction de l intent — les anciens `return 0` les
    transformaient en « declaration a 0 attaque », c est-a-dire une activation qui ne
    resout rien, sans le moindre signal.
    """
    if not (0 <= weapon_idx < len(weapons)):
        raise IndexError(
            f"{roll_label}: index d arme {weapon_idx} hors limites "
            f"({len(weapons)} arme(s) sur la figurine)"
        )
    w = weapons[weapon_idx]
    if not isinstance(w, dict):
        raise TypeError(
            f"{roll_label}: l arme {weapon_idx} n est pas un profil d arme "
            f"(recu {type(w).__name__}: {w!r})"
        )
    return int(resolve_dice_value(require_key(w, "NB"), roll_label))


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
        raise ValueError(
            f"Aucune figurine de {attacker_squad_id!r} ne peut viser l arme {widx} "
            f"sur {target_squad_id!r} ({ctx.phase_label}: hors portee/engagement ou pas de LoS)"
        )
    return created


def _intent_weapon_code(
    models_cache: Dict[str, Any], intent: Dict[str, Any], weapons_key: str
) -> Optional[str]:
    """Code de l arme referencee par un intent, via l index LOCAL de la figurine."""
    m = models_cache.get(str(intent.get("model_id")))
    if m is None:
        return None
    weapons = m.get(weapons_key, [])  # get allowed
    widx = int(intent.get("weapon_index", -1))
    if 0 <= widx < len(weapons) and isinstance(weapons[widx], dict):
        return weapons[widx].get("code")
    return None


def _declare_qty_candidates(
    game_state: Dict[str, Any], ctx: DeclareAttackCtx,
    attacker_squad_id: str, weapon_code: str, target_squad_id: str,
    only_model_id: Optional[str] = None,
) -> tuple:
    """(`remaining`, `candidates` tries) pour une declaration quantifiee (code, cible).

    - `remaining` : declarations de l escouade PRIVEES de la ligne (weapon_code, cible)
      — semantique SET : editer une ligne libere d abord ses propres figurines.
    - `candidates` : [(dist, model_id, local_idx)] tries (plus proche puis id) des figs
      portant `weapon_code`, dont l arme physique est libre vis-a-vis de `remaining`
      (_weapon_group_key), eligibles a la cible (ctx.can_target_with_weapon).

    `only_model_id` (optionnel) : restreint la ligne a CETTE figurine — le SET ne libere
    que ses intents de (code, cible) et les candidats se limitent a elle (menu par-fig).

    Brique partagee entre declare_attack_weapon_qty, weapon_qty_max (borne du champ count)
    et — a terme — la melee. Ne mute PAS game_state."""
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    current = game_state[ctx.intents_key][attacker_squad_id]
    remaining = [
        i for i in current
        if not (str(i.get("target_unit_id")) == str(target_squad_id)
                and _intent_weapon_code(models_cache, i, ctx.weapons_key) == weapon_code
                and (only_model_id is None or str(i["model_id"]) == str(only_model_id)))
    ]
    consumed: Dict[str, set] = {}
    for i in remaining:
        mid = str(i["model_id"]); m = models_cache.get(mid)
        if m is None:
            continue
        w = m.get(ctx.weapons_key, [])  # get allowed
        consumed.setdefault(mid, set()).add(_weapon_group_key(w, int(i["weapon_index"])))

    from engine.hex_utils import min_distance_between_sets
    tgt_uc = require_key(game_state, "units_cache")[str(target_squad_id)]
    tgt_fp = entry_footprint(tgt_uc)

    candidates: List[tuple] = []
    for mid in squad_models.get(attacker_squad_id, []):  # get allowed
        if only_model_id is not None and str(mid) != str(only_model_id):
            continue
        m = models_cache.get(mid)
        if m is None:
            continue
        weapons = m.get(ctx.weapons_key, [])  # get allowed
        local_idx = next(
            (k for k, w in enumerate(weapons)
             if isinstance(w, dict) and w.get("code") == weapon_code),
            None,
        )
        if local_idx is None:
            continue
        if _weapon_group_key(weapons, local_idx) in consumed.get(str(mid), set()):
            continue
        if not ctx.can_target_with_weapon(game_state, m, attacker_squad_id, target_squad_id, local_idx):
            continue
        dist = min_distance_between_sets({(int(m["col"]), int(m["row"]))}, tgt_fp)
        candidates.append((dist, str(mid), local_idx))
    candidates.sort(key=lambda c: (c[0], c[1]))  # deterministe : plus proche, puis model_id
    return remaining, candidates


def declare_attack_weapon_qty(
    game_state: Dict[str, Any], ctx: DeclareAttackCtx,
    attacker_squad_id: str, weapon_code: str, count: int, target_squad_id: str,
    only_model_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Attribue `count` attaques de l arme `weapon_code` (identite stable) sur la cible.

    Successeur par IDENTITE + QUANTITE de declare_attack_weapon (index escouade unique,
    incorrect en escouade heterogene). Moteur generique parametre par ctx : reutilisable
    au tir ET en melee.

    Semantique SET (idempotente) par couple (weapon_code, cible) : retire d abord toute
    declaration existante de ce couple puis en (re)cree `count`. Editer le nombre d une
    "ligne" d attribution = re-appeler avec le nouveau count.

    Selection : parmi les figurines portant `weapon_code` dont l arme physique est encore
    LIBRE (profils exclusifs regroupes par _weapon_group_key) et pouvant viser la cible
    (ctx.can_target_with_weapon), les `count` plus proches (tri deterministe dist puis id).
    1 intent par-figurine avec l index LOCAL. Erreur explicite si count > figs eligibles
    (aucune troncature silencieuse). Validation AVANT toute mutation."""
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    if attacker_squad_id not in game_state[ctx.intents_key]:
        raise RuntimeError(
            f"declare_attack_weapon_qty ({ctx.phase_label}) called before activation start "
            f"for squad {attacker_squad_id!r}"
        )
    if int(count) <= 0:
        raise ValueError(f"count doit etre > 0, recu {count} ({ctx.phase_label})")
    if target_squad_id not in squad_models or not any(
        mid in models_cache for mid in squad_models.get(target_squad_id, [])  # get allowed
    ):
        raise ValueError(f"Target squad {target_squad_id!r} not alive ({ctx.phase_label})")

    remaining, candidates = _declare_qty_candidates(
        game_state, ctx, attacker_squad_id, weapon_code, target_squad_id, only_model_id
    )
    if len(candidates) < int(count):
        raise ValueError(
            f"count={count} > figurines eligibles ({len(candidates)}) pour arme "
            f"'{weapon_code}' sur {target_squad_id!r} ({ctx.phase_label})"
        )
    current: List[Dict[str, Any]] = game_state[ctx.intents_key][attacker_squad_id]
    target_size = sum(
        1 for mid in squad_models.get(target_squad_id, []) if mid in models_cache  # get allowed
    )
    created: List[Dict[str, Any]] = []
    for _dist, mid, local_idx in candidates[:int(count)]:
        weapons = models_cache[mid][ctx.weapons_key]
        created.append({
            "model_id": mid,
            "weapon_index": local_idx,
            "target_unit_id": target_squad_id,
            "target_squad_size_at_declaration": target_size,
            "n_attacks_resolved": _resolve_intent_nb(
                weapons, local_idx, f"{ctx.phase_label}_qty_NB_{mid}_{local_idx}"),
        })
    current[:] = remaining + created  # commit APRES validation (pas de mutation si erreur)
    return created


def weapon_qty_max(
    game_state: Dict[str, Any], ctx: DeclareAttackCtx,
    attacker_squad_id: str, weapon_code: str, target_squad_id: str,
    only_model_id: Optional[str] = None,
) -> int:
    """Nombre de figurines pouvant tirer/frapper `weapon_code` sur la cible.

    Borne du champ count d une ligne d attribution. La ligne (code, cible) editee compte
    ses PROPRES figurines comme libres (semantique SET). Retourne 0 si activation non
    demarree ou cible non vivante. Ne mute pas game_state."""
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    if attacker_squad_id not in game_state[ctx.intents_key]:
        return 0
    if target_squad_id not in squad_models or not any(
        mid in models_cache for mid in squad_models.get(target_squad_id, [])  # get allowed
    ):
        return 0
    _remaining, candidates = _declare_qty_candidates(
        game_state, ctx, attacker_squad_id, weapon_code, target_squad_id, only_model_id
    )
    return len(candidates)


def undeclare_attack_weapon_qty(
    game_state: Dict[str, Any], ctx: DeclareAttackCtx,
    attacker_squad_id: str, weapon_code: str, target_squad_id: str,
    only_model_id: Optional[str] = None,
) -> int:
    """Retire la ligne (weapon_code, cible) — bouton "-" d une ligne d attribution.

    `only_model_id` (optionnel) : ne retire que les intents de CETTE figurine (menu par-fig).
    Returns le nombre d intents retires. Generique (tir OU melee via ctx)."""
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    intents = game_state[ctx.intents_key].get(attacker_squad_id)  # get allowed
    if not intents:
        return 0
    before = len(intents)
    intents[:] = [
        i for i in intents
        if not (str(i.get("target_unit_id")) == str(target_squad_id)
                and _intent_weapon_code(models_cache, i, ctx.weapons_key) == weapon_code
                and (only_model_id is None or str(i["model_id"]) == str(only_model_id)))
    ]
    return before - len(intents)


def eligible_models_for_weapon(
    game_state: Dict[str, Any], ctx: DeclareAttackCtx,
    attacker_squad_id: str, weapon_code: str, target_squad_id: str,
) -> List[Dict[str, Any]]:
    """Figurines pouvant tirer/frapper `weapon_code` sur la cible (voile vert).

    `models` = candidats de _declare_qty_candidates (portant l arme, groupe libre, portee+LoS),
    la ligne (code, cible) comptant ses propres figs comme disponibles. `assigned` marque
    celles deja declarees sur (code, cible). Read-only, generique ctx."""
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    if attacker_squad_id not in game_state[ctx.intents_key]:
        return []
    if target_squad_id not in squad_models or not any(
        mid in models_cache for mid in squad_models.get(target_squad_id, [])  # get allowed
    ):
        return []
    _remaining, candidates = _declare_qty_candidates(
        game_state, ctx, attacker_squad_id, weapon_code, target_squad_id
    )
    assigned = {
        str(i["model_id"])
        for i in game_state[ctx.intents_key][attacker_squad_id]
        if str(i.get("target_unit_id")) == str(target_squad_id)
        and _intent_weapon_code(models_cache, i, ctx.weapons_key) == weapon_code
    }
    return [{"model_id": mid, "assigned": mid in assigned} for (_d, mid, _idx) in candidates]


def models_weapons_for_squad(
    game_state: Dict[str, Any], ctx: DeclareAttackCtx, attacker_squad_id: str
) -> List[Dict[str, Any]]:
    """Par figurine vivante : les codes de ses armes (indépendant de toute cible).

    Sert au surlignage arme<->fig (encart jaune) dès qu'on clique une fig, même sans cible."""
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    out: List[Dict[str, Any]] = []
    for mid in squad_models.get(attacker_squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is None:
            continue
        weapons = m.get(ctx.weapons_key, [])  # get allowed
        codes = [w["code"] for w in weapons if isinstance(w, dict) and w.get("code")]
        out.append({"model_id": str(mid), "weapon_codes": codes})
    return out


def models_status_for_target(
    game_state: Dict[str, Any], ctx: DeclareAttackCtx,
    attacker_squad_id: str, target_squad_id: str,
) -> List[Dict[str, Any]]:
    """Par figurine vivante de l escouade : peut-elle encore tirer/frapper la cible + ses armes.

    - `can_shoot` (VERT si vrai, GRIS sinon) : ∃ arme physique LIBRE (groupe non deja engage
      par une declaration de cette fig) portee par la fig et pouvant viser la cible (portee+LoS).
    - `weapon_codes` : codes des armes portees (pour le surlignage croise arme <-> fig).
    Read-only, generique ctx."""
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    if attacker_squad_id not in game_state[ctx.intents_key]:
        return []
    intents = game_state[ctx.intents_key][attacker_squad_id]
    consumed_by_model: Dict[str, set] = {}
    for i in intents:
        mid = str(i["model_id"]); m = models_cache.get(mid)
        if m is None:
            continue
        w = m.get(ctx.weapons_key, [])  # get allowed
        consumed_by_model.setdefault(mid, set()).add(_weapon_group_key(w, int(i["weapon_index"])))
    alive_target = target_squad_id in squad_models and any(
        mid in models_cache for mid in squad_models.get(target_squad_id, [])  # get allowed
    )
    result: List[Dict[str, Any]] = []
    for mid in squad_models.get(attacker_squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is None:
            continue
        weapons = m.get(ctx.weapons_key, [])  # get allowed
        codes = [w["code"] for w in weapons if isinstance(w, dict) and w.get("code")]
        # exhausted (GRIS) : toutes les armes physiques de la fig sont deja attribuees.
        all_groups = {
            _weapon_group_key(weapons, idx) for idx, wp in enumerate(weapons) if isinstance(wp, dict)
        }
        consumed = consumed_by_model.get(str(mid), set())
        exhausted = len(all_groups) > 0 and all_groups <= consumed
        # can_shoot (VERT) : au moins une arme physique LIBRE peut viser la cible active.
        can = False
        if alive_target and not exhausted:
            for idx, wp in enumerate(weapons):
                if not isinstance(wp, dict):
                    continue
                if _weapon_group_key(weapons, idx) in consumed:
                    continue  # arme physique deja engagee par cette fig
                if ctx.can_target_with_weapon(game_state, m, attacker_squad_id, target_squad_id, idx):
                    can = True
                    break
        result.append(
            {"model_id": str(mid), "can_shoot": can, "exhausted": exhausted, "weapon_codes": codes}
        )
    return result


def toggle_attack_model_weapon(
    game_state: Dict[str, Any], ctx: DeclareAttackCtx,
    attacker_squad_id: str, model_id: str, weapon_code: str, target_squad_id: str,
) -> str:
    """Toggle l intent d UNE figurine precise pour (code, cible) — clic sur fig verte.

    Retire si deja declaree (re-clic), sinon ajoute (si eligible + groupe libre).
    Returns 'added' ou 'removed'. Generique ctx."""
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    if attacker_squad_id not in game_state[ctx.intents_key]:
        raise RuntimeError(
            f"toggle_attack_model_weapon ({ctx.phase_label}) called before activation start "
            f"for squad {attacker_squad_id!r}"
        )
    m = models_cache.get(str(model_id))
    if m is None:
        raise ValueError(f"Model {model_id!r} absent de models_cache ({ctx.phase_label})")
    weapons = m.get(ctx.weapons_key, [])  # get allowed
    local_idx = next(
        (k for k, w in enumerate(weapons) if isinstance(w, dict) and w.get("code") == weapon_code),
        None,
    )
    if local_idx is None:
        raise ValueError(f"Model {model_id!r} ne porte pas l arme {weapon_code!r}")
    intents: List[Dict[str, Any]] = game_state[ctx.intents_key][attacker_squad_id]
    existing = [
        i for i in intents
        if str(i["model_id"]) == str(model_id)
        and str(i.get("target_unit_id")) == str(target_squad_id)
        and int(i["weapon_index"]) == local_idx
    ]
    if existing:
        intents[:] = [i for i in intents if i not in existing]
        return "removed"
    _remaining, candidates = _declare_qty_candidates(
        game_state, ctx, attacker_squad_id, weapon_code, target_squad_id
    )
    if str(model_id) not in {mid for (_d, mid, _i) in candidates}:
        raise ValueError(
            f"Fig {model_id!r} non eligible pour {weapon_code!r} sur {target_squad_id!r} "
            f"(hors portee/LoS ou arme physique deja engagee)"
        )
    target_size = sum(
        1 for mid in squad_models.get(target_squad_id, []) if mid in models_cache  # get allowed
    )
    intents.append({
        "model_id": str(model_id),
        "weapon_index": local_idx,
        "target_unit_id": target_squad_id,
        "target_squad_size_at_declaration": target_size,
        "n_attacks_resolved": _resolve_intent_nb(
            weapons, local_idx, f"{ctx.phase_label}_toggle_NB_{model_id}_{local_idx}"),
    })
    return "added"


def squad_declare_shoot_model(
    game_state: Dict[str, Any],
    attacker_squad_id: str,
    attacker_model_id: str,
    target_squad_id: str,
) -> Dict[str, Any]:
    """Declaration MANUELLE d une seule figurine au TIR (flux PvP humain).

    Wrapper fin de declare_attack_model via SHOOT_DECLARE_CTX (portee + LoS).
    """
    # Primitive F (chantier 06) — suppress_target_on_shooting : enregistrer la cible principale
    # (première déclarée) pour _handle_shooting_end_activation. Miroir du gym (squad_declare_shoot).
    require_unit_by_id(game_state, str(attacker_squad_id)).setdefault(
        "_last_shoot_target_id", str(target_squad_id)
    )
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
    weapons = ranged_weapons(m)
    valid: List[str] = []
    for sid, mids in squad_models.items():
        if sid == attacker_squad_id:
            continue
        first = next((mid for mid in mids if mid in models_cache), None)
        if first is None:
            continue  # escouade morte
        if int(models_cache[first]["player"]) == attacker_player:
            continue  # allie
        # Cible valide si AU MOINS UNE arme de la fig peut la viser (portee + LoS +
        # engagement/Close-quarters) — et non la seule arme selectionnee : sinon une unite engagee
        # avec pistolet ne verrait pas sa cible engagee (arme selectionnee non-Close-quarters).
        if any(
            _model_can_shoot_target_with_weapon(game_state, m, sid, idx)
            for idx in range(len(weapons))
            if isinstance(weapons[idx], dict)
        ):
            valid.append(sid)
    return valid


def _weapon_range_subhex(weapon: Any) -> int:
    """Portee (subhex) d une arme, 0 si absente/invalide (arme non tirable)."""
    if not isinstance(weapon, dict) or "RNG" not in weapon:
        return 0
    try:
        return int(weapon["RNG"])
    except (TypeError, ValueError):
        return 0


def _weapon_group_key(weapons: List[Any], widx: int) -> str:
    """Cle de l arme PHYSIQUE d un profil (regroupe les profils exclusifs).

    Deux profils d une meme arme (ex. Cyclone Frag/Krak) partagent leur ``COMBI_WEAPON`` :
    en tirer un consomme l arme entiere. Sans ``COMBI_WEAPON``, chaque index est une arme
    distincte (split fire possible).
    """
    wp = weapons[widx]
    key = wp.get("COMBI_WEAPON") if isinstance(wp, dict) else None
    return str(key) if key else f"__solo_{widx}"


def squad_shoot_los_overview(
    game_state: Dict[str, Any], attacker_squad_id: str
) -> Dict[str, Any]:
    """Agrege les cibles tirables de TOUTE l escouade (double-click frontend).

    Ne compte QUE les figs encore "libres" : une fig reste libre tant qu il lui
    reste au moins UNE arme non declaree (pending_squad_shoot_intents). Une fig dont
    toutes les armes ont ete affectees sort du decompte ET de la visibilite (blink).
    Pour chaque fig libre, une cible est vue si >= 1 de ses armes libres peut l atteindre
    (portee + LoS, per-arme). Read-only : n ecrit rien dans game_state.

    Returns:
        valid_targets    : union des squad_id ennemis vises par >= 1 fig LIBRE
        count_by_unit_id : {squad_id ennemi: N figs LIBRES qui peuvent le cibler}
        squad_alive_count: nb de figs vivantes de l escouade attaquante
        squad_free_count : M = nb de figs LIBRES (denominateur du compteur N/M)
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    mids = squad_models.get(attacker_squad_id)
    if mids is None:
        raise ValueError(f"Squad {attacker_squad_id!r} absent de squad_models")
    alive = [mid for mid in mids if mid in models_cache]

    # Armes deja declarees par figurine : {model_id: {weapon_index, ...}}.
    intents = game_state.get("pending_squad_shoot_intents", {}).get(attacker_squad_id, [])  # get allowed
    declared_by_model: Dict[str, set] = {}
    for it in intents:
        declared_by_model.setdefault(str(it["model_id"]), set()).add(int(it["weapon_index"]))

    attacker_player = int(models_cache[alive[0]]["player"]) if alive else None
    enemy_sids = _enemy_squad_ids(game_state, attacker_player) if attacker_player is not None else []

    # Type de tir applicable (10.04 / 10.05 / 10.06) : c est lui qui dit quelles armes sont
    # SELECTIONNABLES, donc lesquelles peuvent servir d arme de test ci-dessous. Meme
    # autorite que le masque gym (resolve_squad_shooting_type + shooting_type_allows_weapon) :
    # cette fonction ne redecide rien, sinon elle diverge — c est ce qui se produisait avec
    # son ancien test « engagee => un Close-quarters », qui ignorait 10.05 (une escouade ayant
    # avance aurait teste son arme la plus longue, non-[ASSAULT], et n aurait vu AUCUNE cible)
    # et le volet MONSTER/VEHICLE de 10.06 (« you can select any of that model s ranged
    # weapons »), qui privait de cibles un vehicule engage sans arme Close-quarters.
    shooter_unit = require_unit_by_id(game_state, attacker_squad_id)
    shooting_type = resolve_squad_shooting_type(game_state, attacker_squad_id)
    if shooting_type is None:
        return {
            "valid_targets": [],
            "count_by_unit_id": {},
            "squad_alive_count": len(alive),
            "squad_free_count": 0,
        }

    count: Dict[str, int] = {}
    free_count = 0
    for mid in alive:
        m = models_cache[mid]
        weapons = ranged_weapons(m)
        declared_w = declared_by_model.get(mid, set())  # get allowed
        # Une arme est consommee des qu UN de ses profils exclusifs (COMBI_WEAPON) est
        # declare : on groupe donc par arme physique, pas par profil.
        consumed_groups = {_weapon_group_key(weapons, w) for w in declared_w}
        free_weapons = [
            w for w in range(len(weapons))
            if _weapon_group_key(weapons, w) not in consumed_groups
        ]
        if not free_weapons:
            continue  # fig entierement affectee → hors blink et hors decompte
        free_count += 1
        # Arme de test = la plus longue portee parmi les armes libres SELECTIONNABLES sous le
        # type de tir applicable. La LoS (raycasting) ne depend pas de l arme et `reach` est
        # monotone en portee : un seul test par ennemi suffit, avec l arme la plus permissive
        # du cas. Aucune arme selectionnable → la figurine ne vise rien.
        selectable = [
            w for w in free_weapons
            if shooting_type_allows_weapon(shooting_type, shooter_unit, m, weapons[w])
        ]
        if not selectable:
            continue
        test_widx = max(selectable, key=lambda w: _weapon_range_subhex(weapons[w]))
        for sid in enemy_sids:
            if _model_can_shoot_target_with_weapon(game_state, m, sid, test_widx):
                count[sid] = count.get(sid, 0) + 1  # get allowed
    return {
        "valid_targets": list(count.keys()),
        "count_by_unit_id": count,
        "squad_alive_count": len(alive),
        "squad_free_count": free_count,
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


# ============================================================================
# TYPES DE TIR (10.04 / 10.05 / 10.06) — chemin SQUAD/GYM
# ============================================================================
# Le gate de tir du masque squad se resumait a
# `not has_fled and not has_advanced and not has_shot and not in_er`, SANS aucune exception
# d arme : le tir d assaut et le tir a bout portant n existaient donc pas pour l agent, alors
# que le chemin PvP/mono les connait (`_can_shoot`, shooting_handlers). Motif §9.1 — une regle
# vive sur un chemin, absente de l autre. Detail : V11_entity_encoder_pointer.md §1.2.

SHOOTING_TYPE_NORMAL = "normal"
SHOOTING_TYPE_ASSAULT = "assault"
SHOOTING_TYPE_CLOSE_QUARTERS = "close_quarters"
#: 10.07 — le QUATRIEME type, et le premier qui n exclut pas les autres (cf.
#: `eligible_squad_shooting_types`).
SHOOTING_TYPE_INDIRECT = "indirect"


def _model_is_monster_or_vehicle(model: Dict[str, Any]) -> bool:
    """Keywords MONSTER/VEHICLE de la FIGURINE (pas de l unite).

    Meme convention que le hazard roll 06.03 : le test « each model » se lit sur les keywords
    PROPRES de la figurine, sinon l union 19.03 ferait passer toute une escouade d infanterie
    pour MONSTER des qu un character MONSTER y est attache.
    """
    keywords = model.get("UNIT_KEYWORDS", [])  # get allowed (figurine sans keywords = ni l un ni l autre)
    if not isinstance(keywords, list):
        raise TypeError(
            f"UNIT_KEYWORDS must be a list for model {model.get('id')}, "
            f"got {type(keywords).__name__}"
        )
    for entry in keywords:
        kid = entry.get("keywordId") if isinstance(entry, dict) else entry  # get allowed
        if str(kid).strip().upper() in ("MONSTER", "VEHICLE"):
            return True
    return False


def _squads_are_engaged(
    game_state: Dict[str, Any], squad_id: str, other_squad_id: str
) -> bool:
    """Ces deux escouades sont-elles engagees l une avec l autre (03.04) ?

    Meme primitive que le ciblage 10.06 (`_shoot_engagement_blocks_target`) : zone
    d engagement sur les entrees de cache, pas une distance ad hoc.
    """
    from engine.spatial_relations import (
        get_engagement_zone,
        unit_entries_within_engagement_zone,
    )

    # L'unique appelant (`_manual_roll_intent`) a écarté la cible détruite (`squad_models`) et lit
    # déjà `units_cache[target_sid]` sans repli dix lignes plus haut. Un `False` ici effaçait en
    # silence le malus 10.06 [CLOSE-QUARTERS] — donc rendait le tir PLUS facile.
    a = require_unit_from_cache(str(squad_id), game_state, "_squads_are_engaged/a")
    b = require_unit_from_cache(str(other_squad_id), game_state, "_squads_are_engaged/b")
    return unit_entries_within_engagement_zone(a, b, get_engagement_zone(game_state), game_state=game_state)


#: Cle d etat du TYPE DE TIR CHOISI par activation (10.02, etape 2 : « Select one shooting type
#: that unit is eligible to make »). `{squad_id -> type}`, pose a l activation et lu par
#: `resolve_squad_shooting_type`.
#:
#: POURQUOI UN ETAT, et pas un parametre passe de proche en proche : le type vaut pour
#: l ACTIVATION entiere, et il est lu bien apres l action — a la declaration de cible, a la
#: resolution de chaque intent, a l emission du log. Le faire voyager en argument obligerait
#: chacun de ces sites a le recevoir, et le premier qui l oublierait retomberait silencieusement
#: sur la derivation. L etat est efface par `squad_shooting_type_clear`, appele la ou
#: `units_shot` se vide.
SQUAD_SHOOTING_TYPE_CHOICE_KEY = "squad_shooting_type_choice"


def squad_shooting_type_choose(
    game_state: Dict[str, Any], squad_id: str, shooting_type: str
) -> None:
    """Enregistre le type de tir CHOISI pour cette activation (10.02).

    Le choix est VALIDE contre l ensemble eligible : 10.02 dit « select one shooting type that
    unit IS ELIGIBLE TO MAKE ». Un type non eligible n est pas un cas metier a ignorer en
    silence — c est un masque d action casse ou un appelant PvP qui propose ce qu il ne devrait
    pas, et le laisser passer ferait resoudre une activation sous des regles qu elle n a pas le
    droit d appliquer. Erreur explicite (T1).
    """
    eligibles = eligible_squad_shooting_types(game_state, squad_id)
    if shooting_type not in eligibles:
        raise ValueError(
            f"squad_shooting_type_choose: type {shooting_type!r} non eligible pour l escouade "
            f"{squad_id} (eligibles : {list(eligibles)}) — 10.02 exige un type ELIGIBLE"
        )
    game_state.setdefault(SQUAD_SHOOTING_TYPE_CHOICE_KEY, {})[str(squad_id)] = shooting_type


def squad_shooting_type_clear(game_state: Dict[str, Any], squad_id: str) -> None:
    """Retire le choix de cette escouade — l activation est finie, le type ne vaut plus.

    Sans cet effacement, le choix survivrait au tour et une activation ULTERIEURE hériterait
    d un type qu elle n a pas choisi. C est le meme cycle de vie que `units_shot`, et il est
    appele au meme endroit.
    """
    choices = game_state.get(SQUAD_SHOOTING_TYPE_CHOICE_KEY)  # get allowed (aucun choix encore)
    if isinstance(choices, dict):
        choices.pop(str(squad_id), None)


def _squad_can_shoot_target_under_type(
    game_state: Dict[str, Any], squad_id: str, target_sid: str, shooting_type: str
) -> bool:
    """Une figurine de l escouade peut-elle atteindre `target_sid` SOUS ce type de tir ?

    Le type change deux choses : les armes SELECTIONNABLES (`shooting_type_allows_weapon`) et,
    pour 10.07, l exigence de ligne de vue. Il faut donc l imposer pendant le test, et non
    laisser `_model_can_shoot_target_with_weapon` re-deriver le type courant — celui de
    l activation, qui n est pas encore celui qu on evalue.

    Le choix est POSE puis RETIRE autour du test : `resolve_squad_shooting_type` le lit, et c est
    la seule voie par laquelle le type se propage jusqu au gate de ciblage. Restaure dans un
    `finally` — une exception laisserait sinon l escouade avec un type choisi qu aucune action
    n a demande, et l activation suivante en heriterait.
    """
    choices = game_state.setdefault(SQUAD_SHOOTING_TYPE_CHOICE_KEY, {})
    sid = str(squad_id)
    precedent = choices.get(sid)  # get allowed (aucun choix en cours)
    choices[sid] = shooting_type
    try:
        models_cache = require_key(game_state, "models_cache")
        squad_models = require_key(game_state, "squad_models")
        for mid in squad_models.get(sid, []):  # get allowed
            model = models_cache.get(mid)  # get allowed (figurine morte)
            if model is None:
                continue
            for widx in squad_model_shootable_weapon_indices(
                game_state, sid, model, shooting_type
            ):
                if _model_can_shoot_target_with_weapon(game_state, model, target_sid, widx):
                    return True
        return False
    finally:
        if precedent is None:
            choices.pop(sid, None)
        else:
            choices[sid] = precedent


def eligible_squad_shooting_types(
    game_state: Dict[str, Any], squad_id: str
) -> Tuple[str, ...]:
    """TOUS les types de tir que cette escouade est eligible a jouer (10.02, etape 2).

    10.02 : « Select ONE shooting type that unit is eligible to make ». Le choix appartient au
    JOUEUR — c est pour cela que cette fonction rend un ensemble, la ou
    `resolve_squad_shooting_type` rend le type RETENU.

    ⚠️ POURQUOI DEUX FONCTIONS, et pourquoi cet ensemble n existait pas avant. Les trois premiers
    types s excluent deux a deux : 10.05 exige un advance, 10.06 exige d etre engage, 10.04 exige
    ni l un ni l autre. L eligibilite se REDUISAIT donc a une derivation, et le docstring de
    `resolve_squad_shooting_type` le disait explicitement. **10.07 casse cet invariant** : sa
    condition (« unengaged and did not make an advance move this turn ») est EXACTEMENT celle de
    10.04. Une unite unengaged, qui n a pas avance et qui porte une arme [INDIRECT FIRE] est
    eligible aux DEUX, et rien dans l etat ne dit lequel elle joue : il faut le lui demander.

    Ordre STABLE et signifiant : le type par defaut d abord (celui que rend
    `resolve_squad_shooting_type`), les alternatives ensuite. Un ensemble non ordonne rendrait le
    masque d action dependant de l ordre d iteration d un set — donc le comportement de l agent
    non reproductible d une execution a l autre.

    Rend un tuple VIDE si l escouade ne peut pas tirer du tout ; c est le meme etat que le `None`
    de `resolve_squad_shooting_type`, et les deux se lisent au meme endroit pour cette raison.
    """
    default = _derive_squad_shooting_type(game_state, str(squad_id))
    if default is None:
        return ()
    types = [default]
    # 10.07 : mEme condition d eligibilite que 10.04 (donc `default` vaut deja NORMAL quand elle
    # est remplie), plus au moins une arme [INDIRECT FIRE]. On ne re-teste PAS « unengaged et pas
    # d advance » : `default == SHOOTING_TYPE_NORMAL` l atteste deja, et le re-deriver ici
    # creerait une seconde definition de la condition, a reconcilier au premier desaccord.
    if default == SHOOTING_TYPE_NORMAL and _squad_has_indirect_fire_weapon(game_state, squad_id):
        types.append(SHOOTING_TYPE_INDIRECT)
    return tuple(types)


def _squad_has_indirect_fire_weapon(game_state: Dict[str, Any], squad_id: str) -> bool:
    """10.07, deuxieme clause d eligibilite : « Has one or more [INDIRECT FIRE] weapons ».

    Compte sur les figurines VIVANTES seulement — une arme portee par une figurine detruite ne
    rend plus l unite eligible. Meme convention que `_any_weapon` de
    `resolve_squad_shooting_type`, y compris le filtre metier `RNG > 0`.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    for mid in squad_models.get(str(squad_id), []):  # get allowed (escouade inconnue = vide)
        model = models_cache.get(mid)  # get allowed (figurine morte = retiree du cache)
        if model is None:
            continue
        for weapon in ranged_weapons(model):
            if not isinstance(weapon, dict) or int(require_key(weapon, "RNG")) <= 0:
                continue
            if weapon_has_rule(weapon, "INDIRECT_FIRE"):
                return True
    return False


def resolve_squad_shooting_type(
    game_state: Dict[str, Any], squad_id: str
) -> Optional[str]:
    """Type de tir applicable a cette escouade, ou None si elle ne peut pas tirer.

    Source de verite : PDF 10 Shooting phase.
      - **10.04 normal**        : unengaged ET pas d advance ce tour.
      - **10.05 assault**       : unengaged ET a fait un advance ce tour ET >=1 arme [ASSAULT].
      - **10.06 close-quarters**: ENGAGEE ET pas d advance ce tour ET (>=1 arme
        [CLOSE_QUARTERS] OU au moins une figurine MONSTER/VEHICLE).

    Les regles d UNITE du projet elargissent 10.05 (`shoot_after_advance`) et le repli
    (`shoot_after_flee`) — memes predicats que le chemin mono, pour que les deux chemins ne
    divergent pas.

    Ordre des tests = ordre des conditions du PDF.

    ⚠️ CE QUE CETTE FONCTION REND, DEPUIS LE 2026-08-16 : le type RETENU, et non « le seul type
    applicable ». La version precedente affirmait ici qu un seul type peut s appliquer, les
    conditions « engaged / unengaged » et « advance / pas d advance » etant exclusives. C etait
    vrai des TROIS types implementes alors, et faux en general : 10.07 (tir indirect) partage
    EXACTEMENT la condition d eligibilite de 10.04, donc les deux coexistent. L ensemble des
    types jouables se lit desormais dans `eligible_squad_shooting_types` ; celle-ci rend le
    DEFAUT, c est-a-dire le type joue tant que le joueur n en choisit pas un autre (10.02).

    Le defaut reste 10.04 normal quand 10.07 est aussi eligible, et ce n est pas arbitraire :
    contre une cible VISIBLE, le tir normal domine strictement l indirect — celui-ci octroie le
    couvert a la cible, interdit les relances de touche et impose un plancher d echec, sans
    aucune contrepartie. L indirect ne se choisit que pour atteindre une cible invisible, donc
    jamais par defaut.
    """
    sid = str(squad_id)
    # Une activation DEPENSEE n a plus de type, choix compris. Ce garde precede volontairement la
    # lecture du choix : `squad_shooting_type_clear` efface a la fin de l activation, et si cet
    # effacement venait a manquer, rendre le choix perime ici ressusciterait une activation deja
    # jouee — un repli silencieux, exactement ce que T1 interdit.
    if sid in game_state.get("units_shot", set()):  # get allowed (absent = personne n a tire)
        return None
    # 10.02 : si un type a ete CHOISI pour cette activation, c est lui, SANS re-derivation. Il a
    # deja ete valide contre l ensemble eligible a la pose (`squad_shooting_type_choose`) ; le
    # revalider ici ferait une seconde definition de l eligibilite, a reconcilier au premier
    # desaccord.
    chosen = game_state.get(SQUAD_SHOOTING_TYPE_CHOICE_KEY, {}).get(sid)  # get allowed
    if chosen is not None:
        return chosen
    return _derive_squad_shooting_type(game_state, sid)


def _derive_squad_shooting_type(game_state: Dict[str, Any], sid: str) -> Optional[str]:
    """Type de tir par DEFAUT — celui d une activation qui n a rien choisi (10.02).

    Extrait de `resolve_squad_shooting_type` pour casser une circularite : `eligible_squad_
    shooting_types` doit enumerer ce que l escouade PEUT jouer, ce qui ne depend pas de ce
    qu elle a deja choisi. Sans cette separation, poser un choix aurait retreci l ensemble
    eligible au choix lui-meme, et un second appel a `squad_shooting_type_choose` — le
    changement d avis d un joueur PvP — aurait ete refuse par sa propre validation.
    """
    unit = require_unit_by_id(game_state, sid)
    from engine.phase_handlers.shooting_handlers import (
        _can_unit_shoot_after_advance_with_weapon,
        _unit_has_rule,
    )

    if sid in game_state.get("units_shot", set()):  # get allowed
        return None
    if sid in game_state.get("units_fled", set()) and not _unit_has_rule(  # get allowed
        unit, "shoot_after_flee"
    ):
        return None

    has_advanced = sid in game_state.get("units_advanced", set())  # get allowed
    engaged = _squad_is_in_enemy_er(game_state, sid)

    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive = [models_cache[m] for m in squad_models.get(sid, []) if m in models_cache]  # get allowed
    if not alive:
        return None

    def _any_weapon(predicate) -> bool:
        return any(
            predicate(w)
            for m in alive
            for w in ranged_weapons(m)
            # `RNG > 0` reste un filtre METIER (arme de tir utilisable) ; la portee elle-meme
            # est requise : les 243 profils de RNG_WEAPONS la portent.
            if isinstance(w, dict) and int(require_key(w, "RNG")) > 0
        )

    if engaged:
        if has_advanced:
            return None  # 10.06 exige « did not make an advance move this turn »
        if _any_weapon(lambda w: weapon_has_rule(w, "CLOSE_QUARTERS")) or any(
            _model_is_monster_or_vehicle(m) for m in alive
        ):
            return SHOOTING_TYPE_CLOSE_QUARTERS
        return None
    if has_advanced:
        if _any_weapon(lambda w: _can_unit_shoot_after_advance_with_weapon(unit, w)):
            return SHOOTING_TYPE_ASSAULT
        return None
    return SHOOTING_TYPE_NORMAL


def shooting_type_allows_weapon(
    shooting_type: str,
    unit: Dict[str, Any],
    model: Dict[str, Any],
    weapon: Dict[str, Any],
) -> bool:
    """L arme est-elle SELECTIONNABLE sous ce type de tir (volet « WHILE SHOOTING ») ?

    - 10.04 normal        : toutes les armes de tir.
    - 10.05 assault       : « You can only select [ASSAULT] weapons » (+ la regle d unite
      `shoot_after_advance` du projet, meme predicat que le chemin mono).
    - 10.06 close-quarters: « Non-MONSTER/Non-VEHICLE Models: you can only select
      [CLOSE-QUARTERS] weapons ». Une figurine MONSTER/VEHICLE, elle, peut selectionner
      n importe quelle arme — au prix d un -1 au jet de touche (applique a la resolution).
    """
    from engine.phase_handlers.shooting_handlers import _can_unit_shoot_after_advance_with_weapon

    if shooting_type == SHOOTING_TYPE_NORMAL:
        return True
    if shooting_type == SHOOTING_TYPE_ASSAULT:
        return _can_unit_shoot_after_advance_with_weapon(unit, weapon)
    if shooting_type == SHOOTING_TYPE_CLOSE_QUARTERS:
        if _model_is_monster_or_vehicle(model):
            return True
        return weapon_has_rule(weapon, "CLOSE_QUARTERS")
    if shooting_type == SHOOTING_TYPE_INDIRECT:
        # 10.07 ne restreint PAS la selection d armes — c est le seul type de tir dans ce cas, et
        # l encadre du PDF le dit sans ambiguite : « its [INDIRECT FIRE] weapons can launch
        # punishing barrages on targets that are not visible, but don t forget that its OTHER
        # WEAPONS CAN STILL TARGET OTHER VISIBLE TARGETS ». Les penalites de 10.07 (plancher
        # d echec, couvert octroye, pas de relance) ne portent que sur les attaques des armes
        # [INDIRECT FIRE] elles-memes, jamais sur celles de leurs voisines — elles s appliquent
        # donc a la RESOLUTION, pas ici.
        return True
    raise ValueError(f"shooting_type inconnu : {shooting_type!r}")


def squad_model_shootable_weapon_indices(
    game_state: Dict[str, Any],
    squad_id: str,
    model: Dict[str, Any],
    shooting_type: str,
) -> List[int]:
    """Index des armes de tir que CETTE figurine peut selectionner sous ce type de tir."""
    unit = require_unit_by_id(game_state, str(squad_id))
    out: List[int] = []
    for idx, weapon in enumerate(ranged_weapons(model)):
        # Idem : le filtre porte sur la VALEUR de portee, jamais sur son absence.
        if not isinstance(weapon, dict) or int(require_key(weapon, "RNG")) <= 0:
            continue
        if shooting_type_allows_weapon(shooting_type, unit, model, weapon):
            out.append(idx)
    return out


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
    weapons = ranged_weapons(attacker_model)
    if not (0 <= int(weapon_index) < len(weapons)):
        return False
    weapon = weapons[int(weapon_index)]
    if not isinstance(weapon, dict) or "RNG" not in weapon:
        return False
    # weapon["RNG"] est DEJA en subhexes (cf. _model_can_shoot_target).
    range_subhex = int(weapon["RNG"])
    if range_subhex <= 0:
        return False
    if _advance_blocks_weapon(game_state, str(attacker_model["squad_id"]), weapon):
        return False

    ac = int(attacker_model["col"])
    ar = int(attacker_model["row"])
    # 10.07 : sous tir indirect, une arme [INDIRECT FIRE] cible sans ligne de vue. Le predicat
    # est PARESSEUX (declaration d arme testee avant le type de tir), donc gratuit pour les 229
    # autres profils de l armurerie.
    if not _attacker_model_can_reach_squad(
        game_state, attacker_model, ac, ar, target_squad_id, range_subhex,
        require_visibility=not indirect_shooting_applies(
            game_state, str(attacker_model["squad_id"]), weapon
        ),
    ):
        return False
    if _shoot_engagement_blocks_target(
        game_state,
        str(attacker_model["squad_id"]),
        target_squad_id,
        weapon_has_rule(weapon, "CLOSE_QUARTERS"),
        attacker_model,
        weapon_has_rule(weapon, "BLAST"),
    ):
        return False
    return True


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
    require_unit_by_id(game_state, str(attacker_squad_id)).setdefault(
        "_last_shoot_target_id", str(target_squad_id)
    )
    return declare_attack_weapon(
        game_state, SHOOT_DECLARE_CTX, attacker_squad_id, weapon_index, target_squad_id
    )


def squad_declare_shoot_weapon_qty(
    game_state: Dict[str, Any], attacker_squad_id: str,
    weapon_code: str, count: int, target_squad_id: str,
    only_model_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Assigne `count` tirs de l arme `weapon_code` (identite) a la cible.

    `only_model_id` (optionnel) : attribution restreinte a CETTE figurine (menu par-fig).
    Wrapper fin de declare_attack_weapon_qty via SHOOT_DECLARE_CTX (portee + LoS).
    """
    require_unit_by_id(game_state, str(attacker_squad_id)).setdefault(
        "_last_shoot_target_id", str(target_squad_id)
    )
    return declare_attack_weapon_qty(
        game_state, SHOOT_DECLARE_CTX, attacker_squad_id, weapon_code, count, target_squad_id,
        only_model_id,
    )


def squad_shoot_weapon_qty_max(
    game_state: Dict[str, Any], attacker_squad_id: str, weapon_code: str, target_squad_id: str,
    only_model_id: Optional[str] = None,
) -> int:
    """Borne du champ count au TIR — figs pouvant tirer `weapon_code` sur la cible."""
    return weapon_qty_max(game_state, SHOOT_DECLARE_CTX, attacker_squad_id, weapon_code, target_squad_id, only_model_id)


def squad_undeclare_shoot_weapon_qty(
    game_state: Dict[str, Any], attacker_squad_id: str, weapon_code: str, target_squad_id: str,
    only_model_id: Optional[str] = None,
) -> int:
    """Retire la ligne (weapon_code, cible) au TIR — bouton "-"."""
    return undeclare_attack_weapon_qty(game_state, SHOOT_DECLARE_CTX, attacker_squad_id, weapon_code, target_squad_id, only_model_id)


def shoot_weapon_eligible_target_slots(
    game_state: Dict[str, Any],
    squad_id: str,
    weapon_slot: int,
    enemy_slot_ids: List[Optional[str]],
) -> Tuple[str, List[int]]:
    """Code de l'arme au slot j et indices des slots ennemis éligibles (P3-8 split-fire).

    ⚠️ `squad_shooting_unit_activation_start` DOIT avoir été appelé avant : `weapon_qty_max`
    retourne 0 hors activation. Miroir de `fight_weapon_eligible_slots` côté tir.

    Retourne `(weapon_code, [slot_i pour toute cible éligible])`.
    """
    from engine.observation_weapon_profiles import collect_weapon_profiles
    from engine.observation_entities import K_WEAPONS_RANGED as _K

    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive_models = [
        models_cache[mid]
        for mid in squad_models.get(squad_id, [])  # get allowed
        if mid in models_cache
    ]
    profiles = collect_weapon_profiles(alive_models, "RNG_WEAPONS")
    if weapon_slot >= min(len(profiles), _K):
        raise ValueError(
            f"shoot_weapon_eligible_target_slots: slot {weapon_slot} hors des profils "
            f"({len(profiles)} profils, K={_K}) pour {squad_id!r}"
        )
    weapon_code = require_key(profiles[weapon_slot][0], "code")
    _uc = require_key(game_state, "units_cache")
    elig: List[int] = [
        slot_i for slot_i, tsid in enumerate(enemy_slot_ids)
        if tsid is not None
        and tsid in _uc and entry_is_on_battlefield(_uc[tsid])
        and squad_shoot_weapon_qty_max(game_state, squad_id, weapon_code, tsid) > 0
    ]
    return weapon_code, elig


def shoot_weapon_remaining_eligible_slots(
    game_state: Dict[str, Any],
    squad_id: str,
    enemy_slot_ids: List[Optional[str]],
    except_slot: int,
) -> Dict[int, str]:
    """Slots d'armes RNG éligibles pour le split-fire, en excluant `except_slot` (P3-8).

    ⚠️ `squad_shooting_unit_activation_start` DOIT avoir été appelé avant.
    Retourne `{slot_j: weapon_code}` pour chaque slot j ≠ `except_slot` dont ≥1 ennemi
    est atteignable. Miroir de `fight_weapon_eligible_slots` pour les autres groupes d'arme.
    """
    from engine.observation_weapon_profiles import collect_weapon_profiles
    from engine.observation_entities import K_WEAPONS_RANGED as _K

    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive_models = [
        models_cache[mid]
        for mid in squad_models.get(squad_id, [])  # get allowed
        if mid in models_cache
    ]
    profiles = collect_weapon_profiles(alive_models, "RNG_WEAPONS")
    # COMBI_WEAPON du slot exclu : ses armes-sœurs partagent l'arme physique → exclues aussi.
    _except_combi: Optional[str] = None
    if 0 <= except_slot < len(profiles):
        _ewp = profiles[except_slot][0]
        _except_combi = (_ewp.get("COMBI_WEAPON") if isinstance(_ewp, dict) else None)
    _uc = require_key(game_state, "units_cache")
    on_table = [
        tsid for tsid in enemy_slot_ids
        if tsid is not None and tsid in _uc and entry_is_on_battlefield(_uc[tsid])
    ]
    result: Dict[int, str] = {}
    for slot_j, (weapon, _) in enumerate(profiles[:_K]):
        if slot_j == except_slot:
            continue
        if _except_combi is not None:
            _combi_j = weapon.get("COMBI_WEAPON") if isinstance(weapon, dict) else None
            if _combi_j == _except_combi:
                continue
        code = require_key(weapon, "code")
        if any(
            squad_shoot_weapon_qty_max(game_state, squad_id, code, tsid) > 0
            for tsid in on_table
        ):
            result[slot_j] = code
    return result


def purge_combi_siblings_from_remaining(
    game_state: Dict[str, Any],
    squad_id: str,
    selected_slot: int,
    remaining: Dict[int, str],
) -> None:
    """Retire de `remaining` tous les slots partageant le COMBI_WEAPON du slot sélectionné.

    Appelé chaque fois qu'un slot est retiré de remaining_weapon_slots (appels 2+ à
    squad_shoot_weapon_sel), pour garantir qu'un seul profil par arme physique est déclarable.
    Mute `remaining` en place.
    """
    from engine.observation_weapon_profiles import collect_weapon_profiles
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive_models = [
        models_cache[mid]
        for mid in squad_models.get(squad_id, [])  # get allowed
        if mid in models_cache
    ]
    profiles = collect_weapon_profiles(alive_models, "RNG_WEAPONS")
    if not (0 <= selected_slot < len(profiles)):
        raise IndexError(
            f"purge_combi_siblings_from_remaining: selected_slot={selected_slot} hors range"
            f" (profiles len={len(profiles)}) pour squad {squad_id!r}"
        )
    sel_wp = profiles[selected_slot][0]
    sel_combi = sel_wp.get("COMBI_WEAPON") if isinstance(sel_wp, dict) else None
    if sel_combi is None:
        return
    to_purge = [
        slot_j for slot_j, (wpn, _) in enumerate(profiles)
        if slot_j in remaining
        and (wpn.get("COMBI_WEAPON") if isinstance(wpn, dict) else None) == sel_combi
    ]
    for slot_j in to_purge:
        del remaining[slot_j]


def squad_shoot_weapons_for_target(
    game_state: Dict[str, Any], attacker_squad_id: str, target_squad_id: str,
    only_model_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Menu cible-d abord au TIR — armes pouvant viser la cible avec (m, x). Cf. weapons_for_target."""
    return weapons_for_target(game_state, SHOOT_DECLARE_CTX, attacker_squad_id, target_squad_id, only_model_id)


def squad_shoot_eligible_models(
    game_state: Dict[str, Any], attacker_squad_id: str, weapon_code: str, target_squad_id: str
) -> List[Dict[str, Any]]:
    """Voile vert au TIR — figs pouvant tirer `weapon_code` sur la cible (+ assigned)."""
    return eligible_models_for_weapon(game_state, SHOOT_DECLARE_CTX, attacker_squad_id, weapon_code, target_squad_id)


def squad_shoot_toggle_model_weapon(
    game_state: Dict[str, Any], attacker_squad_id: str, model_id: str, weapon_code: str, target_squad_id: str
) -> str:
    """Clic sur fig verte au TIR — toggle l attribution de cette fig pour (code, cible)."""
    return toggle_attack_model_weapon(game_state, SHOOT_DECLARE_CTX, attacker_squad_id, model_id, weapon_code, target_squad_id)


def squad_shoot_models_status(
    game_state: Dict[str, Any], attacker_squad_id: str, target_squad_id: str
) -> List[Dict[str, Any]]:
    """Voiles vert/gris au TIR — état de chaque fig vis-à-vis de la cible (+ ses armes)."""
    return models_status_for_target(game_state, SHOOT_DECLARE_CTX, attacker_squad_id, target_squad_id)


def squad_shoot_models_weapons(
    game_state: Dict[str, Any], attacker_squad_id: str
) -> List[Dict[str, Any]]:
    """Armes par figurine au TIR (indépendant de la cible) — pour l'encart jaune au clic-fig."""
    return models_weapons_for_squad(game_state, SHOOT_DECLARE_CTX, attacker_squad_id)


def _union_weapons(
    game_state: Dict[str, Any], weapons_key: str, squad_id: str
) -> List[Dict[str, Any]]:
    """Union DISTINCTE (par `code`) des armes `weapons_key` portees par les figurines.

    Chaque entree = un profil selectionnable (Storm Bolter, Cyclone Frag/Krak, arme de
    perso attache...) — `unit[weapons_key]` ne porte que l arme du type d escouade de base
    et masquerait les armes par-figurine. Copie superficielle avec `shot` par defaut a 0
    (attendu par weapon_availability_check ; l usage reel est suivi via les intents). Ordre
    stable = premiere occurrence. Echoue si une arme n a pas de `code` (invariant identite)."""
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    seen: set = set()
    ordered: List[Dict[str, Any]] = []
    for mid in squad_models.get(squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is None:
            continue
        for w in m.get(weapons_key, []):  # get allowed
            if not isinstance(w, dict):
                continue
            code = w.get("code")
            if code is None:
                raise ValueError(
                    f"Squad {squad_id} model {mid}: arme '{w.get('display_name')}' sans 'code' "
                    f"— identite requise pour le menu union / declaration quantifiee"
                )
            if code in seen:
                continue
            seen.add(code)
            # Type/nom de la figurine porteuse : distingue deux profils homonymes aux
            # stats differentes (ex. Storm Bolter BS3+ Terminator vs BS2+ Captain).
            ordered.append({
                **w,
                "shot": w.get("shot", 0),  # fallback allowed — defaut metier (profil menu neuf, usage suivi via intents)
                "carrier_type": m.get("unitType"),  # get allowed
                "carrier_name": m.get("DISPLAY_NAME"),  # get allowed
            })
    return ordered


def squad_union_weapons(
    game_state: Dict[str, Any], squad_id: str
) -> List[Dict[str, Any]]:
    """Union des armes RNG par-figurine (source du menu tir). Cf. _union_weapons."""
    return _union_weapons(game_state, "RNG_WEAPONS", squad_id)


def squad_shoot_menu_weapons(
    game_state: Dict[str, Any], attacker_squad_id: str
) -> List[Dict[str, Any]]:
    """Profils de l escouade pour le menu tir, avec `can_use` correct (par-figurine).

    - usable = AU MOINS une figurine portant le profil peut tirer sur AU MOINS un ennemi
      (portee + LoS + engagement, calcule par-fig — pas depuis l ancre escouade). Le pistolet
      est donc utilisable engage OU non (arme de tir normale + exception 10.06).
    - Exclusion 10.06 au niveau unite : si un Close-quarters est deja declare, les non-Close-quarters ne sont
      plus selectionnables ; si un non-Close-quarters est declare, les Close-quarters ne le sont plus."""
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    init_pending_intents(game_state)

    # Type d arme deja engage par l unite (Close-quarters vs non-Close-quarters) — via les declarations.
    intents = game_state["pending_squad_shoot_intents"].get(attacker_squad_id, [])  # get allowed
    declared_close_quarters = False
    declared_non_close_quarters = False
    for it in intents:
        m = models_cache.get(str(it["model_id"]))
        if m is None:
            continue
        ws = ranged_weapons(m)
        wi = int(it["weapon_index"])
        if 0 <= wi < len(ws) and isinstance(ws[wi], dict):
            if weapon_has_rule(ws[wi], "CLOSE_QUARTERS"):
                declared_close_quarters = True
            else:
                declared_non_close_quarters = True

    mids = squad_models.get(attacker_squad_id, [])  # get allowed
    player = int(models_cache[mids[0]]["player"]) if mids and mids[0] in models_cache else None
    enemy_sids = _enemy_squad_ids(game_state, player) if player is not None else []

    result: List[Dict[str, Any]] = []
    for idx, w in enumerate(_union_weapons(game_state, "RNG_WEAPONS", attacker_squad_id)):
        code = w["code"]
        is_close_quarters = weapon_has_rule(w, "CLOSE_QUARTERS")
        usable = False
        for mid in mids:
            m = models_cache.get(mid)
            if m is None:
                continue
            weapons = ranged_weapons(m)
            local_idx = next(
                (i for i, ww in enumerate(weapons) if isinstance(ww, dict) and ww.get("code") == code),
                None,
            )
            if local_idx is None:
                continue
            if any(
                _model_can_shoot_target_with_weapon(game_state, m, sid, local_idx)
                for sid in enemy_sids
            ):
                usable = True
                break
        # Exclusion Close-quarters / non-Close-quarters au niveau unite (10.06).
        if declared_close_quarters and not is_close_quarters:
            usable = False
        if declared_non_close_quarters and is_close_quarters:
            usable = False
        result.append({"index": idx, "weapon": w, "can_use": usable, "reason": None})
    return result


def weapons_for_target(
    game_state: Dict[str, Any], ctx: DeclareAttackCtx,
    attacker_squad_id: str, target_squad_id: str,
    only_model_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Armes de l escouade pouvant viser la cible, pour le menu CIBLE-D ABORD.

    Ne retient que les profils dont AU MOINS une figurine peut atteindre la cible.
    Chaque entree : `code`, `weapon` (affichage nom/rules/portee), `m` (borne du champ
    count = weapon_qty_max), `x` (nb deja attribue au couple (code, cible)).
    `only_model_id` (optionnel) : m et x restreints a CETTE figurine (menu par-fig).
    Generique ctx (tir OU melee). Read-only."""
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    if attacker_squad_id not in game_state[ctx.intents_key]:
        return []
    if target_squad_id not in squad_models or not any(
        mid in models_cache for mid in squad_models.get(target_squad_id, [])  # get allowed
    ):
        return []
    intents = game_state[ctx.intents_key][attacker_squad_id]
    result: List[Dict[str, Any]] = []
    for w in _union_weapons(game_state, ctx.weapons_key, attacker_squad_id):
        code = w["code"]
        m = weapon_qty_max(game_state, ctx, attacker_squad_id, code, target_squad_id, only_model_id)
        if m <= 0:
            continue
        x = sum(
            1 for i in intents
            if str(i.get("target_unit_id")) == str(target_squad_id)
            and _intent_weapon_code(models_cache, i, ctx.weapons_key) == code
            and (only_model_id is None or str(i["model_id"]) == str(only_model_id))
        )
        result.append({"code": code, "weapon": w, "m": m, "x": x})
    return result


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
# SQUAD SHOOTING — resolution (squad_multi_figurines.md PR3 3c)
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


def display_save_threshold_with_waaagh(
    game_state: Dict[str, Any],
    target_unit: Dict[str, Any],
    first_alive: Dict[str, Any],
    ap: int,
) -> Tuple[int, bool]:
    """Seuil de sauvegarde AFFICHE dans la ligne de synthese, et « le Waaagh! l a ameliore ».

    SOURCE UNIQUE des deux rollers manuels (`_manual_roll_intent` au tir,
    `_manual_roll_fight_intent` en melee) : la sauvegarde invulnerable 5+ octroyee par le
    Waaagh! (08.04) s oppose a TOUTES les attaques, donc les deux phases doivent afficher le
    meme seuil ET poser le token sur le meme critere.

    Le seuil affiche doit dire ce que la resolution appliquera (`_resolve_one_manual_wound`) :
    il part de l invulnerable EFFECTIVE, pas de celle de la datasheet. Le drapeau, lui, compare
    les SEUILS et non les invulnerables : une figurine deja mieux servie par son armure (3+
    contre AP 0) ou par une invulnerable 4+ ne gagne rien, et annoncer le Waaagh! sur un `Save:`
    inchange dirait une amelioration qui n a pas eu lieu.
    """
    from engine.game_state import effective_invul_save  # import paresseux : cycle, cf. plus haut

    armor = int(first_alive["ARMOR_SAVE"])
    base_invul = int(require_key(first_alive, "INVUL_SAVE"))
    effective_invul = effective_invul_save(game_state, target_unit, base_invul)
    display_save_th = save_threshold(armor, effective_invul, ap)
    return display_save_th, display_save_th < save_threshold(armor, base_invul, ap)


def _blast_extra_dice_per_five(weapon: Dict[str, Any]) -> Optional[int]:
    """[BLAST] 24.05 : nombre de des additionnels par tranche de 5 figurines cibles.

    « add one additional attack dice for every five models that were in the target unit in
    the Select Targets step (rounding down) » ; la forme [BLAST X] en ajoute X par tranche.
    Retourne None si l arme n est pas [BLAST].

    ⚠ Correction de conformite : cette fonction lisait `weapon["KEYWORDS"]`, un champ qui
    n existe sur AUCUNE arme des armories (les regles vivent dans `WEAPON_RULES`) — BLAST
    n etait donc jamais applique, ni en gym ni en PvP.
    """
    from engine.utils.weapon_helpers import weapon_rule_parameter_or
    return weapon_rule_parameter_or(weapon, "BLAST", 1)


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
    units_cache = require_key(game_state, "units_cache")
    if target_squad_id in units_cache:
        defender_player = int(require_key(units_cache[target_squad_id], "player"))
    else:
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
        tier = ROLE_TIER[_role] if _role is not None else 0
        return (tier, dist_cache[mid], idx)

    return min(enumerate(alive), key=_key)[1]


def _arm_allocation_model_decision(
    game_state: Dict[str, Any],
    target_squad_id: str,
    alive_grp: List[str],
    ctx: "ManualAllocCtx",
) -> Dict[str, Any]:
    """Pose une décision d'agent pour le choix de la figurine réceptrice (05.04, §9.4 pt 4).

    Appelé depuis `_manual_allocation_step` quand `gym_training_mode` est vrai et que
    tous les modèles du groupe courant sont sains (les blessés sont forcés avant, règle 05.04).
    Les traits continus `role_tier_norm` et `dist_enemy_norm` distinguent les candidats qui
    auraient autrement des vecteurs binaires identiques (aucun effet accordable).
    """
    models_cache = require_key(game_state, "models_cache")
    dist_cache = _precompute_nearest_enemy_dist(game_state, target_squad_id)
    board_cols = int(require_key(game_state, "board_cols"))
    board_rows = int(require_key(game_state, "board_rows"))
    max_dist = max(1, board_cols + board_rows)

    units_cache = require_key(game_state, "units_cache")
    if target_squad_id not in units_cache:
        raise KeyError(
            f"_arm_allocation_model_decision: escouade cible {target_squad_id!r} "
            "absente de units_cache"
        )
    defender_player = int(require_key(units_cache[target_squad_id], "player"))

    # Cap à MAX_DECISION_OPTIONS : _validate_options lève si > 6 candidats. On garde les
    # figurines les plus sacrifiables (tier croissant, proximité ennemi croissante) pour
    # maximiser la diversité utile dans les traits continus présentés à l'agent.
    if len(alive_grp) > MAX_DECISION_OPTIONS:
        def _sort_key(mid: str) -> tuple:
            r = models_cache[mid].get("role")
            return (ROLE_TIER[r] if r is not None else 0, dist_cache[mid])
        alive_grp = sorted(alive_grp, key=_sort_key)[:MAX_DECISION_OPTIONS]

    options: List[Dict[str, Any]] = []
    options_cont: List[List[float]] = []
    for mid in alive_grp:
        e = models_cache[mid]
        _role = e.get("role")
        tier = ROLE_TIER[_role] if _role is not None else 0
        d = dist_cache[mid]
        options.append({
            "label": str(e.get("modelId", mid)),
            "effect_ids": (),
            "declines": False,
            "payload": {"model_id": mid, "alloc_ctx_key": ctx.alloc_key},
        })
        options_cont.append([tier / 4.0, d / max_dist])

    return set_pending_agent_decision(
        game_state,
        decision_type="allocation_model",
        player=defender_player,
        unit_id=target_squad_id,
        options=options,
        options_cont=options_cont,
    )


# Segments de la ligne de synthese d une attaque, dans l ordre d emission. Chaque regle d arme
# est accrochee au segment qu elle MODIFIE : c est la seule accroche qui reste lisible quand
# plusieurs regles jouent ensemble (une liste de tokens en fin de ligne ne dirait pas laquelle
# explique le seuil, laquelle explique le nombre de des).
RULE_TOKEN_SEGMENTS: Tuple[str, ...] = ("shots", "hit", "wound", "save", "damage")

#: Libelles de token des regles qui AJOUTENT des des au pool d attaques. Nommes plutot
#: qu ecrits en litteral parce qu ils sont la CLE de `additive_rules_applied` : ils lient les
#: producteurs (`_manual_roll_intent` ici, `_manual_roll_fight_intent` en melee) a l afficheur,
#: et une orthographe qui derive rendrait un token muet sans que rien ne leve.
RULE_LABEL_RAPID_FIRE: str = "RAPID FIRE"
RULE_LABEL_BLAST: str = "BLAST"
RULE_LABEL_CLEAVE: str = "CLEAVE"

#: Ordre d affichage sur `Shots:` des trois regles ci-dessus. Elles partagent une propriete que
#: n a aucune autre regle du log : leur effet se compte PAR FIGURINE (chaque porteuse ajoute les
#: siens), alors que le token vit sur le GROUPE. C est pour elles seules que le groupe doit
#: collecter quelque chose par figurine plutot que lire un profil constant.
ADDITIVE_RULE_ORDER: Tuple[str, ...] = (
    RULE_LABEL_RAPID_FIRE, RULE_LABEL_BLAST, RULE_LABEL_CLEAVE,
)


def psychic_rule_applies(weapon: Dict[str, Any], *, cover: bool) -> bool:
    """[PSYCHIC] 24.29 a-t-elle NEUTRALISE quelque chose sur ce groupe d attaques ?

    La regle ignore les modificateurs subis par l attaque ; le seul modificateur que ce moteur
    applique a une attaque est la degradation de seuil du couvert 13.08. Sans couvert, la regle
    n a donc rien neutralise, et l annoncer ferait croire a un effet.

    Predicat EXTRAIT parce qu il a deux lecteurs — le Game Log PvP (`weapon_rule_log_tokens`)
    et `step.log` (`_emit_squad_shoot_log`) — et que c est le seul des sept tokens du lot dont
    la condition ne se reduit pas a `weapon_has_rule`. Deux copies auraient diverge au premier
    changement de 13.08, et le journal aurait dit d un cote ce qu il tait de l autre.
    """
    return bool(cover) and weapon_has_rule(weapon, "PSYCHIC")


def weapon_rule_log_tokens(
    profile: "WeaponAttackProfile",
    *,
    weapon: Dict[str, Any],
    additive_rules_applied: Mapping[str, int],
    dmg_bonus: int,
    cover: bool,
    heavy_applied: bool,
    precision_applied: bool,
    wound_target: int,
    save_threshold: int,
    devastating_fired: bool = False,
) -> Dict[str, List[str]]:
    """Tokens `[REGLE]` d un GROUPE d attaques (04.03), ranges par segment de la ligne de log.

    SOCLE UNIQUE, a deux titres : tir ET melee (les deux chemins d emission l appellent, aucun
    ne construit de token chez lui — c est le motif d echec n°1 du depot), et TOUTES les regles
    d arme de la ligne, y compris [HEAVY] 24.16 et les des additionnels de [BLAST] 24.05 /
    [CLEAVE] 24.06. Seul [COVER] 13.08 reste pose par l appelant : ce n est pas une regle d arme.

    Appele UNE fois par groupe, a l emission (`_emit_squad_shoot_log`), et non par intent : les
    valeurs dont il depend sont toutes portees par le groupe, ou elles ont deja ete rendues
    constantes (`gkey`) ou reunies (`additive_rules_applied`).

    Regle d emission : un token n apparait que si la regle a EFFECTIVEMENT joue, pas si l arme
    la declare. D ou les etats APPLIQUES en parametres (`additive_rules_applied`, `dmg_bonus`,
    `heavy_applied`) plutot que les parametres declares : une arme [RAPID FIRE 2] hors
    demi-portee n ajoute rien, elle ne doit rien dire.

    UNE SEULE GRAMMAIRE, sans exception : dans `[REGLE:n]`, `n` est TOUJOURS le parametre X que
    l ARME DECLARE, jamais le nombre de des que la regle a ajoutes. Un shoota [RAPID FIRE 1] tire
    par 10 figurines a demi-portee ecrit `Shots:30 [RAPID FIRE:1]` — 1, pas 10. C est la valeur
    que le joueur lit sur sa datasheet, donc la seule qui se recoupe avec la source ; le total,
    lui, reste deductible du `Shots:` voisin, qui le compte deja. Regle posee le 2026-08-10 :
    `[RAPID FIRE:10]` en face d une datasheet qui dit 1 se lisait comme un defaut du moteur.
    `step.log` portait deja le X declare par TIR — les deux logs disent enfin la meme chose.

    Deux exceptions ASSUMEES, et pour la meme raison — leur effet n est pas mesurable a
    posteriori sur ce groupe :
      - [IGNORES COVER] 24.18 : le couvert n est meme pas calcule (court-circuit de
        `_cover_worsened_bs`), donc « la cible aurait-elle eu le couvert ? » est inconnu. Le
        token dit ce qui est vrai et verifiable : cette attaque ignore le couvert.
      - [EXTRA ATTACKS] 24.11 : l arme est resolue EN PLUS des autres, son effet est l existence
        meme du groupe.

    `profile` est le `WeaponAttackProfile` construit par le roller : les regles de la boucle
    touche/blessure ne sont PAS re-resolues ici, elles sont lues la ou elles ont ete decidees
    (notamment `anti_keyword`, dont le choix d instance releve de 24.02).

    `additive_rules_applied` est `libelle de token -> X declare`, constant sur le groupe : les
    deux X qui dependent de la FIGURINE ([RAPID FIRE] a demi-portee, [CLEAVE] mono-cible) sont
    dans `gkey`, donc deux figurines qui en different ne sont jamais dans le meme groupe — c est
    ce qu exige 04.03 (« affected by the same applicable abilities and rules »). Il est POSE PAR
    LE PRODUCTEUR, qui a deja le X en main : le relire ici sur `weapon` creerait une seconde
    derivation du meme fait, a reconcilier au premier desaccord.
    """
    # Import local : `attack_sequence` n a aucun cycle avec ce module, mais il n est charge que
    # par les chemins d attaque — l importer au niveau module le mettrait sur le chemin de tous
    # les autres consommateurs de `shared_utils`.
    from engine.phase_handlers.attack_sequence import lethal_hits_auto_wound_is_better

    tokens: Dict[str, List[str]] = {segment: [] for segment in RULE_TOKEN_SEGMENTS}

    for rule_label in ADDITIVE_RULE_ORDER:
        if rule_label in additive_rules_applied:
            tokens["shots"].append(f"[{rule_label}:{additive_rules_applied[rule_label]}]")
    if weapon_has_rule(weapon, "EXTRA_ATTACKS"):
        tokens["shots"].append("[EXTRA ATTACKS]")

    if heavy_applied:
        tokens["hit"].append("[HEAVY]")

    if profile.torrent:
        tokens["hit"].append("[TORRENT]")
    if profile.sustained_hits:
        tokens["hit"].append(f"[SUSTAINED HITS:{profile.sustained_hits}]")
    if weapon_has_rule(weapon, "IGNORES_COVER"):
        tokens["hit"].append("[IGNORES COVER]")
    # [PSYCHIC] 24.29 : cf. `psychic_rule_applies` — MEME predicat que `step.log`, un seul site.
    if psychic_rule_applies(weapon, cover=cover):
        tokens["hit"].append("[PSYCHIC]")

    if profile.anti_keyword is not None:
        # Seuil AFFICHE = le Y+ que l ARME DECLARE (`anti_threshold`), pas le `crit_wound_on`
        # que le moteur en a tire. La regle d une seule grammaire enoncee ci-dessus ne souffre
        # pas d exception, et celle-ci en etait une : afficher `crit_wound_on`, c est nommer le
        # seuil avec le chiffre que le moteur a calcule, donc rendre invérifiable le seul
        # recoupement qui vaille (le token contre la datasheet). Les deux valeurs coincident
        # pour tout Y+ jouable (2..6) ; sur une armurerie fautive (Y=7) elles divergent, et
        # c est exactement le cas que le journal doit exposer plutot que lisser.
        tokens["wound"].append(
            f"[ANTI-{profile.anti_keyword}:{profile.anti_threshold}+]"
        )
    # [LETHAL HITS] 24.23 dit « you CAN choose for that attack to automatically wound » : le
    # moteur tranche par esperance de degats, et il DECLINE l auto-blessure quand elle est
    # perdante (typiquement une arme [LETHAL HITS] + [DEVASTATING WOUNDS], ou l auto-blessure
    # interdirait la blessure critique). Le choix ne depend que du profil et des deux seuils —
    # tous constants sur le groupe — donc il est le meme pour toutes les attaques du groupe.
    # MEME predicat que `roll_attack_pool` : sans lui, la ligne de synthese annoncait une regle
    # qu aucun detail par tir ne confirmait jamais.
    if profile.lethal_hits and lethal_hits_auto_wound_is_better(
        profile, int(wound_target), int(save_threshold)
    ):
        tokens["wound"].append("[LETHAL HITS]")
    if profile.twin_linked:
        tokens["wound"].append("[TWIN-LINKED]")

    if profile.devastating and devastating_fired:
        tokens["save"].append("[DEVASTATING WOUNDS]")

    if dmg_bonus > 0:
        tokens["damage"].append(f"[MELTA:{dmg_bonus}]")
    # [PRECISION] 24.28 : `precision_applied` — pose a l Allocation Order step — et non la
    # declaration de l arme. Contre une cible sans CHARACTER visible, la regle n a impose aucun
    # groupe : elle n a rien fait, elle ne dit rien.
    if precision_applied:
        tokens["damage"].append("[PRECISION]")

    return tokens


def _segment_with_tokens(segment: str, tokens: Sequence[str]) -> str:
    """Accole les tokens de regle a un segment de la ligne de synthese (`Shots:12 [BLAST:2]`)."""
    return segment if not tokens else f"{segment} {' '.join(tokens)}"


def _emit_squad_shoot_log(game_state: Dict[str, Any], g: Dict[str, Any], ctx: ManualAllocCtx) -> None:
    """Emet 1 action_log de tir pour un groupe (arme, cible).

    Partage entre l allocation auto (resolve_squad_shoot) et l allocation manuelle
    (defenseur humain) : meme format de log, damage/kills refletant l allocation
    effective. Ne consomme pas de RNG.
    """
    weapon_name_g = g["weapon_name"]
    target_sid_g = g["target_sid"]
    attacker_squad_id_str = g["attacker_squad_id"]
    tgt_unit = next((u for u in game_state["units"] if str(u["id"]) == target_sid_g), None)
    tgt_unit_type_g = tgt_unit.get("unitType") if tgt_unit else None
    atk_unit = next((u for u in game_state["units"] if str(u["id"]) == attacker_squad_id_str), None)
    atk_unit_type_g = atk_unit.get("unitType") if atk_unit else None
    # Positions ATTAQUANT et CIBLE = ancres capturées à la création du groupe, au moment où
    # l'attaque est déclarée. Ne PAS relire units_cache ici : l'émission est différée en fin
    # d'allocation, après le retrait d'une éventuelle escouade détruite → l'ancien
    # `tgt_uc.get("col", 0)` rendait (0,0), et son jumeau attaquant
    # `game_state.get("units_cache", {}).get(sid, {}).get("col", 0)` faisait de même — (0,0)
    # est une case RÉELLE du plateau, donc une position d'analyse fausse et indétectable
    # dans step.log (que l'analyzer lit et que le replay rejoue).
    ac = int(require_key(g, "attacker_col"))
    ar = int(require_key(g, "attacker_row"))
    tc = int(require_key(g, "target_col"))
    tr = int(require_key(g, "target_row"))
    weapon_suffix = f" [{weapon_name_g}]" if weapon_name_g else ""
    # Cover (13.08, ranged-only) : si la cible avait le couvert, afficher la degradation
    # du seuil de touche (ex 3+->4+) + token [COVER] (tooltip regle cote frontend).
    # Absent au combat -> branche standard.
    _cover = bool(g.get("cover"))  # get allowed : absent au combat (regle ranged-only)
    hit_part = f"Hit:{g['bs_base']}+->{g['bs']}+" if _cover else f"Hit:{g['bs']}+"
    # Oath of Moment (08.04) dans la ligne de synthese. `RR` = relance, accolee au seuil et POSEE
    # AVANT les tokens de regle, pour que ceux-ci restent en fin de segment — c'est cette
    # position que le parser de replay et le rendu du log supposent tous deux.
    # Le `Wound:` est deja le seuil NET (le +1 est applique en amont par abaissement du seuil) :
    # le token dit seulement d ou vient l amelioration.
    from engine.game_state import OATH_ABILITY_DISPLAY_NAME, WAAAGH_ABILITY_DISPLAY_NAME

    _oath_token = f"[{OATH_ABILITY_DISPLAY_NAME.upper()}]"
    # Waaagh! (08.04) : MEME grammaire de token que celui d Oath, donc meme bulle d aide cote
    # frontend (entree `waaagh` de `config/unit_rules.json`, retrouvee par normalisation du
    # libelle). Trois effets, trois segments : le nombre d attaques (+1 A), le seuil de blessure
    # (+1 F) et le seuil de sauvegarde (invulnerable 5+ octroyee a la CIBLE). Les valeurs
    # affichees sont deja NETTES : sans ce token, rien ne dit d ou vient l ecart.
    _waaagh_token = f"[{WAAAGH_ABILITY_DISPLAY_NAME.upper()}]"
    _waaagh_melee = require_key(g, "waaagh_melee_bonus")
    if require_key(g, "oath_hit_reroll"):
        hit_part = f"{hit_part}RR {_oath_token}"
    # [COVER] 13.08 : pose ici et non dans `weapon_rule_log_tokens` — ce n est pas une regle
    # d ARME (aucune entree dans weapon_rules.json), c est une propriete de la cible. [HEAVY],
    # lui, EST une regle d arme : il passe par le socle, comme les douze autres.
    if _cover:
        hit_part = f"{hit_part} [COVER]"
    # 10.06, volet MONSTER/VEHICLE : « unless that attack is made with a [CLOSE-QUARTERS] weapon
    # AND targets a unit your unit is engaged with, subtract 1 from the hit roll ». Pose ici et
    # non dans le socle, pour la MEME raison que [COVER] : c est une regle de PHASE (10.06), pas
    # une regle d arme — elle n a pas d entree dans weapon_rules.json.
    if require_key(g, "point_blank_malus"):
        hit_part = f"{hit_part} [POINT-BLANK]"
    # Tokens de REGLES D ARME du groupe, ranges par segment. Construits ICI, une seule fois par
    # groupe : toutes leurs sources sont portees par `g` (les rollers ne les fabriquent plus par
    # intent, ou 9 dicts sur 10 finissaient jetes).
    _rule_tokens = weapon_rule_log_tokens(
        require_key(g, "attack_profile"),
        weapon=require_key(g, "weapon"),
        additive_rules_applied=require_key(g, "additive_rules_applied"),
        dmg_bonus=int(require_key(g, "dmg_bonus")),
        cover=_cover,
        heavy_applied=bool(require_key(g, "heavy_applied")),
        precision_applied=bool(require_key(g, "precision_applied")),
        # Les deux seuils PASSES au socle de resolution (`roll_attack_pool`) pour ce groupe :
        # [LETHAL HITS] s en sert pour rejouer le meme arbitrage que lui.
        wound_target=int(require_key(g, "display_wth")),
        save_threshold=int(require_key(g, "display_save_th")),
        # [DEVASTATING WOUNDS] 24.10 : le token ne suit pas la DECLARATION de la regle mais
        # son ACTIVATION — au moins une blessure critique dans le groupe. `devastating=True`
        # est pose sur le record seulement quand la branche devastatrice s est executee
        # (attack_sequence.py), donc cette garde est exacte.
        devastating_fired=any(s.get("devastating") for s in require_key(g, "shots")),
    )
    hit_part = _segment_with_tokens(hit_part, _rule_tokens["hit"])
    wound_part = f"Wound:{g['display_wth']}+"
    if require_key(g, "oath_wound_bonus"):
        wound_part = f"{wound_part} {_oath_token}"
    # +1 Force : le seuil de blessure affiche est deja celui de la Force augmentee.
    if _waaagh_melee:
        wound_part = f"{wound_part} {_waaagh_token}"
    wound_part = _segment_with_tokens(wound_part, _rule_tokens["wound"])
    # +1 Attaque : le compte d attaques du groupe inclut deja l attaque supplementaire.
    shots_part = f"Shots:{g['attacks']}"
    if _waaagh_melee:
        shots_part = f"{shots_part} {_waaagh_token}"
    shots_part = _segment_with_tokens(shots_part, _rule_tokens["shots"])
    save_part = f"Save:{g['display_save_th']}+"
    # Invulnerable 5+ de la CIBLE : posee sur le segment de sauvegarde, cote defenseur, et non
    # sur les deux precedents qui parlent de l attaquant.
    if require_key(g, "waaagh_target_invul"):
        save_part = f"{save_part} {_waaagh_token}"
    save_part = _segment_with_tokens(save_part, _rule_tokens["save"])
    # Segment des degats : [MELTA:X] (bonus de D) et [PRECISION] (qui encaisse). Les tokens
    # arrivent en FIN de ligne, apres `Killed:` — position qu aucun consommateur n analyse
    # (l analyzer et le replay lisent `step.log`, pas ce message).
    damage_part = _segment_with_tokens(
        f"HP lost:{g['damage']} Killed:{g['kills']}", _rule_tokens["damage"]
    )
    attack_log = f"{shots_part} - {hit_part} {wound_part} {save_part} - {damage_part}"
    # Label toujours enrichi : type + coords. Le frontend masque type et/ou coords
    # selon les 2 options du Game Log (regex sur "Unit <id> <type> (col,row)").
    atk_type_seg = f" {atk_unit_type_g}" if atk_unit_type_g else ""
    tgt_type_seg = f" {tgt_unit_type_g}" if tgt_unit_type_g else ""
    msg = (
        f"Unit {attacker_squad_id_str}{atk_type_seg} ({ac},{ar}) {ctx.log_verb}"
        f" at Unit {target_sid_g}{tgt_type_seg} ({tc},{tr}){weapon_suffix}"
        f" - {attack_log}"
    )
    # Pré-capture AVANT effets hazardous/destroy_model (cf. commentaire plus bas sur
    # "models_segment"). ConfigurationError (floor_height_by_model absent = corruption cache)
    # remonte : lâcher le segment ferait disparaître la couche per-figurine ENTIÈRE (cf.
    # w40k_core._models_segment_for_unit). Un journal muet vaut moins qu'une erreur visible.
    _pre_captured_models_seg = models_segment_for_unit(game_state, attacker_squad_id_str)
    append_action_log(game_state, {
        "type": ctx.log_type,
        "message": msg,
        "turn": game_state.get("turn", 0),  # get allowed
        "phase": ctx.phase_label,
        "shooterId": attacker_squad_id_str,
        # `shooter_mids` est pose a la creation de CHAQUE groupe d'armes (voir plus bas dans ce
        # fichier, initialisation a []) et lu partout ailleurs en acces direct : un `.get` avec
        # defaut masquait ici une absence qui ne peut pas survenir, et aurait rendu un log de
        # tir sans tireur au lieu de lever.
        "shooterModels": list(require_key(g, "shooter_mids")),
        # L14 — [FIGHTS FIRST] 24.13 / 11.04 : True si l'attaquant a charge ce tour (melee
        # seulement). Inligne `is_fights_first` pour eviter l'import circulaire shared_utils
        # ← fight_handlers. `units_charged` est garanti present en phase de combat.
        "fightsFirst": (
            atk_unit is not None
            and str(require_key(atk_unit, "id")) in {str(uid) for uid in game_state.get("units_charged", [])}
        ) if ctx.log_type == "combat" else None,
        "targetId": target_sid_g,
        "weaponName": weapon_name_g if weapon_name_g else None,
        "targetUnitType": tgt_unit_type_g,
        "player": g["player"],
        "shooterCol": ac,
        "shooterRow": ar,
        "targetCol": tc,
        "targetRow": tr,
        # Effectif de la cible AU SELECT TARGETS STEP (avant toute perte de l'activation).
        # Porté dans step.log comme [TARGET_DECL:N] pour les contrôles §1.2/§1.4 de l'analyzer.
        "targetAliveCount": int(require_key(g, "targetAliveCount")),
        "damage": g["damage"],
        "target_died": g["kills"] > 0,
        "timestamp": "server_time",
        "is_ai_action": g["player"] == 1,
        # Regles d armes en clair (pas seulement noyees dans `message`) : le step.log et le
        # replay en tirent `Hit 4(4+->3+) [HEAVY]` et `[RAPID FIRE:X]`, et les controles de
        # `ai/analyzer_phases/shoot_handler.py` les cherchent par regex. Sans ces cles, la
        # ligne ne peut pas les porter et les controles restent muets. Cf. V11 §0hist.38.
        # `bs_base` n existe QUE sur le chemin tir (pose avec `cover`) : en melee il n y a ni
        # couvert ni [HEAVY], son absence est un etat metier valide, pas une erreur a masquer.
        "bs": g["bs"],
        "bsBase": g["bs_base"] if "bs_base" in g else None,
        "heavyApplied": bool(g["heavy_applied"]),
        # §22.05 PLUNGING FIRE : absent en melee (False par construction via get).
        "plungingFireApplied": bool(g.get("plunging_fire_applied", False)),
        "cover": bool(g["cover"]) if "cover" in g else False,
        # L26 — 10.06 volet MONSTER/VEHICLE : -1 au jet de touche hors arme CQ engagée.
        # Drapeau toujours présent dans le groupe (False en mêlée par construction).
        "pointBlankMalus": bool(g.get("point_blank_malus", False)),
        # [RAPID FIRE] 24.30 : X APPLIQUE, lu dans `additive_rules_applied` — le seul porteur du
        # fait (cf. `gkey`). L'absence de cle vaut 0, comme pour les deux autres regles
        # additives : la melee n'ecrit jamais cette entree, [RAPID FIRE] n'y existe pas.
        "rapidFireApplied": int(
            require_key(g, "additive_rules_applied").get(RULE_LABEL_RAPID_FIRE, 0)
        ),
        # [BLAST] 24.05 (tir) et [CLEAVE X] 24.06 (melee) : les deux AUTRES regles additives,
        # meme source, meme regime que `rapidFireApplied` — X DECLARE par l arme, 0 quand la
        # regle n a pas joue (cible de moins de 5 figurines, ou attaques d une meme arme
        # reparties sur plusieurs cibles pour [CLEAVE]). Elles etaient rendues dans la ligne de
        # synthese et ABSENTES de `step.log`, donc invisibles de l analyzer, dont le plafond
        # d attaques restait au seul NB. Mesure du 2026-08-11 : les 24 « Attacks over CC_NB » du
        # run sont les 19 activations ou [CLEAVE] avait ajoute ses des — 24 faux positifs sur 24.
        # UN SEUL site pour les deux regles : cet emetteur sert le tir ET la melee.
        "blastApplied": int(
            require_key(g, "additive_rules_applied").get(RULE_LABEL_BLAST, 0)
        ),
        "cleaveApplied": int(
            require_key(g, "additive_rules_applied").get(RULE_LABEL_CLEAVE, 0)
        ),
        # [MELTA X] 24.25 : X APPLIQUE (0 hors demi-portee), meme regime que `rapidFireApplied`.
        # Le token `[MELTA:X]` existait deja dans la ligne de synthese ci-dessus, mais elle n a
        # AUCUN consommateur automatique — l analyzer et le replay lisent `step.log`, qui ne le
        # portait pas. Resultat mesure le 2026-08-11 : 708 tirs de Multi-Melta dans le journal et
        # une paire (MELTA, Multi-Melta) rendue « NOT USED » par le rapport. `dmg_bonus` n a
        # qu une source, [MELTA] (la melee le fixe a 0), donc la valeur est le X de l arme.
        "meltaApplied": int(require_key(g, "dmg_bonus")),
        # L13 — [HALF RANGE] : cible a demi-portee pour une arme RAPID_FIRE ou MELTA. Absent
        # en melee (`g` issu de _manual_roll_fight_intent ne porte pas `atHalfRange`) : get
        # avec defaut False est le comportement correct — la melee ne connait pas la demi-portee.
        "atHalfRange": bool(g.get("atHalfRange", False)),
        # [PRECISION] 24.28 : JUMEAU de [MELTA] jusque dans son histoire — appliquee par le
        # moteur (posee a l Allocation Order step), rendue dans la ligne de synthese, absente du
        # journal que lisent l analyzer et le replay. Le drapeau dit que la regle a IMPOSE un
        # groupe d allocation, pas que l arme la declare : contre une cible sans CHARACTER
        # visible elle n a rien fait, et elle ne doit rien dire.
        "precisionApplied": bool(require_key(g, "precision_applied")),
        # ── Les regles d arme du GROUPE que `step.log` ne portait pas ────────────────────
        # Elles etaient rendues dans la ligne de synthese ci-dessus (Game Log PvP) et ABSENTES
        # du journal que lisent l analyzer et le replay : aucun controle de conformite ne
        # pouvait donc exister pour elles, et leur compteur d usage serait reste a zero pour
        # toujours. Meme regime que les cinq cles precedentes — un FAIT brut par cle, le
        # formatage (`[TOKEN]`) vit dans `ai/step_logger.py`, jamais ici.
        #
        # [IGNORES COVER] 24.18 et [EXTRA ATTACKS] 24.11 sont posees sur la DECLARATION de
        # l arme, et c est assume : leur effet n est pas mesurable a posteriori sur ce groupe
        # (le couvert n est meme pas calcule pour la premiere — court-circuit de
        # `_cover_worsened_bs` ; l effet de la seconde est l existence meme du groupe). MEME
        # regle d emission que le socle de tokens, qui nomme ces deux exceptions.
        "ignoresCoverApplied": weapon_has_rule(require_key(g, "weapon"), "IGNORES_COVER"),
        "extraAttacksApplied": weapon_has_rule(require_key(g, "weapon"), "EXTRA_ATTACKS"),
        # [PSYCHIC] 24.29 : predicat PARTAGE avec le socle de tokens, jamais recopie.
        "psychicApplied": psychic_rule_applies(require_key(g, "weapon"), cover=_cover),
        # [ASSAULT] 24.04 / [CLOSE-QUARTERS] 24.07 : poses a la CREATION du groupe
        # (etat vive) et relus ici, comme tous les drapeaux constants du groupe.
        # Meme regime que `precisionApplied` : on lit le fait pose, on ne re-derive pas.
        "assaultApplied": bool(require_key(g, "assault_applied")),
        "closeQuartersApplied": bool(require_key(g, "close_quarters_applied")),
        # [INDIRECT FIRE] 10.07 : plancher d echec (6 ou 4) pose a la CREATION du groupe,
        # None si la regle ne joue pas. Le pont `_build_shot_details` le transporte vers les
        # details par-jet, et le StepLogger l ecrit `[INDIRECT FIRE:X+]` sur le segment Hit.
        "indirectFireFailBelow": require_key(g, "indirect_fire_fail_below"),
        # [ANTI-X Y+] 24.03 : l instance RETENUE par 24.02 (keyword) et son seuil DECLARE. Le
        # seuil est celui de la datasheet, pas le `crit_wound_on` que le moteur en tire : c est
        # la seule forme sous laquelle un lecteur peut recouper le journal avec l armurerie
        # (cf. `WeaponAttackProfile.anti_threshold`). Les deux cles valent None ensemble quand
        # l arme ne porte pas la regle, ou quand la cible n a aucun des keywords vises.
        "antiKeyword": require_key(g, "attack_profile").anti_keyword,
        "antiThreshold": require_key(g, "attack_profile").anti_threshold,
        "shootDetails": [{"shotNumber": i + 1, **s} for i, s in enumerate(g["shots"])],
        # L10 — type de tir EXPLICITE (10.02) : normal / assault / close_quarters / indirect.
        # Lu depuis squad_shooting_type_choice ; "normal" par défaut pour le combat (ctx.log_type
        # == "combat") qui ne passe pas par squad_shooting_type_choose.
        "shootType": (
            game_state.get(SQUAD_SHOOTING_TYPE_CHOICE_KEY, {}).get(attacker_squad_id_str, "normal")  # get allowed (aucun choix encore)
            if ctx.log_type == "shoot"
            else None
        ),
        # Pré-capture du segment [MODELS:] AVANT que les effets de l'action (hazardous,
        # destroy_model) ne modifient occupied_hexes_by_model. Sans pré-capture,
        # _build_shot_details lirait le segment LIVE au flush — après que les figurines tuées
        # en cours d'activation ont déjà disparu du cache. Pré-capturé ici, ce segment reflète
        # l'état du tireur au moment où il tire, pas l'état post-mort.
        "models_segment": _pre_captured_models_seg,
    })


def _cover_worsened_bs(
    game_state: Dict[str, Any], attacker: Dict[str, Any], target_sid: str, bs: int,
    weapon: Dict[str, Any],
) -> Tuple[int, bool]:
    """Applique le Benefit of Cover (regle 13.08) au seuil de touche d un tir.

    Cover = ranged-only, niveau UNITE tout-ou-rien : « worsen the BS characteristic of
    that attack by 1 ». Source autoritative : compute_unit_los(tireur, cible)["cover"]
    = exactement la valeur affichee au frontend (los_cover_cache derive du meme calcul) et
    celle observee par l agent (bit `cover_vs_observer` des slots ennemis). Son pair-cache est
    un dict pur invalide de façon CIBLEE par le choke-point `_touch_unit_los` — PAS un jet
    global sur `_unit_move_version`, comme cette ligne l affirmait a tort jusqu au 2026-07-27.
    Clamp a 6 : un 6 non-modifie touche toujours
    (CRITICAL HIT, 05.01), donc un BS6+ sous cover reste touche-sur-6.

    IGNORES COVER (24.18) : si l arme tire avec une regle [IGNORES COVER], la cible
    « cannot have the benefit of cover against that attack ». Court-circuit en tete :
    aucun malus, et le calcul de LoS est evite.

    Retourne (bs_effectif, cover). Aucun repli : si une unite est introuvable c est
    un bug -> erreur explicite.
    """
    if weapon_has_rule(weapon, "IGNORES_COVER"):
        return bs, False
    from engine.phase_handlers.shooting_handlers import compute_unit_los
    shooter_sid = str(require_key(attacker, "squad_id"))
    shooter_unit = require_unit_by_id(game_state, shooter_sid)
    target_unit = require_unit_by_id(game_state, str(target_sid))
    cover = bool(compute_unit_los(game_state, shooter_unit, target_unit)["cover"])
    if not cover:
        return bs, False
    # [PSYCHIC] 24.29 : « you can ignore any or all modifiers to that attack's BS or WS
    # characteristic and any or all modifiers to the hit roll. » Le choix appartient au joueur
    # (« any or all ») : on ignore les modificateurs DEFAVORABLES et on garde les favorables —
    # ici, le malus de couvert est ignore, tandis que le bonus [HEAVY] applique par l appelant
    # est conserve. La cible garde le BENEFICE du couvert (flag rendu tel quel) : 24.29 neutralise
    # le modificateur, il ne supprime pas le couvert (contrairement a [IGNORES COVER] 24.18).
    if weapon_has_rule(weapon, "PSYCHIC"):
        return bs, True
    return min(bs + 1, 6), True


def _is_character_role(role: Optional[str]) -> bool:
    """CHARACTER au sens allocation 40k = role support/leader (cf. ROLE_TIER)."""
    return role in ("support", "leader")


def _target_highest_bodyguard_toughness(game_state: Dict[str, Any], target_sid: str) -> int:
    """T utilisee pour le jet de blessure contre l unite cible (regle 19.02).

    Regle V11 (19.02 Attacking attached units) : si l unite contient une ou plusieurs
    figurines bodyguard, utiliser la PLUS HAUTE T des bodyguards (jamais celle du
    leader/support, meme si l attaque lui est ensuite allouee). Si l unite ne contient
    que des figurines leader/support, utiliser la plus haute T de celles-ci.
    Bodyguard = figurine non-CHARACTER au sens allocation (cf. _is_character_role).
    Leve si la cible n a aucune figurine vivante.

    Primitive F (chantier 06, passe 6) : `toughness_bonus_while_waaagh` — +N T pendant le
    Waaagh! actif pour le joueur de l unite cible. BannerNob confere ce bonus a TOUTE l unite
    via 19.04 ; la fonction l applique ici, point unique pour tir ET melee (jumeau couvert).
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive = [m for m in squad_models.get(target_sid, []) if m in models_cache]  # get allowed
    if not alive:
        raise ValueError(f"Cible {target_sid} sans figurine vivante pour T (19.02)")
    bodyguard = [m for m in alive if not _is_character_role(models_cache[m].get("role"))]
    pool = bodyguard if bodyguard else alive
    base_t = max(int(models_cache[m]["T"]) for m in pool)
    # toughness_bonus_while_waaagh (19.04 : le bonus est dans UNIT_RULES de l unite apres fold)
    target_unit = require_unit_by_id(game_state, str(target_sid))
    bonus_args = _get_unit_rule_arg(target_unit, "toughness_bonus_while_waaagh", "toughness_bonus", (int,))
    if bonus_args is not None:
        from engine.game_state import waaagh_applies_to_unit  # cycle : cf. plus haut
        if waaagh_applies_to_unit(game_state, target_unit):
            return base_t + int(bonus_args)
    return base_t


def _build_alloc_groups(game_state: Dict[str, Any], target_sid: str) -> List[Dict[str, Any]]:
    """Groupes d allocation 40k (05.03) : 1 par CHARACTER, 1 par triplet (W,Sv,InSv)
    pour le reste. Non-characters d abord (ordre de decouverte), puis characters.
    group_id = index de creation (stable)."""
    from engine.game_state import effective_invul_save  # import paresseux : cycle, cf. plus haut

    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive = [m for m in squad_models.get(target_sid, []) if m in models_cache]  # get allowed
    # Waaagh! (chantier 03) : `InSv` affiche au defenseur DOIT etre celui que
    # `_resolve_one_manual_wound` comparera. Les afficher differents ferait choisir une
    # allocation sur une sauvegarde qui n existe pas.
    _target_unit = require_unit_by_id(game_state, str(target_sid))

    def _insv(entry: Dict[str, Any]) -> int:
        raw = int(require_key(entry, "INVUL_SAVE"))
        return effective_invul_save(game_state, _target_unit, raw)

    non_char: Dict[tuple, List[str]] = {}
    non_char_order: List[tuple] = []
    char_models: List[str] = []
    for m in alive:
        e = models_cache[m]
        if _is_character_role(e.get("role")):
            char_models.append(m)
            continue
        # `INVUL_SAVE` est TOUJOURS porte par la figurine : « pas de sauvegarde invulnerable »
        # s ecrit 7 DANS LA DONNEE (179/179 datasheets), ce n est pas un defaut de lecture.
        key = (int(e["HP_MAX"]), int(e["ARMOR_SAVE"]), _insv(e))
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
            "W": int(e["HP_MAX"]), "Sv": int(e["ARMOR_SAVE"]),
            "InSv": _insv(e),
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


def _ranged_squad_edge_distance(
    game_state: Dict[str, Any], attacker_sid: str, target_sid: str,
    *, metric: Optional[str] = None, attacker_socle: Any = None,
) -> float:
    """Distance de portee bord-a-bord (subhexes) entre deux escouades via le selecteur
    `ranged` — socles d escouade (centres par-figurine), meme convention que le gate de portee
    du moteur. Mutualise par closest_target_penetration et RAPID_FIRE (tir vif).

    `metric` / `attacker_socle` : precalculables et injectables pour une boucle (ex: CTP mesure
    vers tout un pool) — evite de relire la config et de reconstruire le socle attaquant a
    chaque cible. Aucun repli masquant : units_cache et les entrees requises sont exigees.
    """
    from engine.combat_utils import ranged_edge_distance, socle_from_cache_entry
    uc = require_key(game_state, "units_cache")
    if metric is None:
        from engine.phase_handlers.shooting_handlers import _ranged_distance_metric
        metric = _ranged_distance_metric(game_state)
    if attacker_socle is None:
        attacker_socle = socle_from_cache_entry(uc[str(attacker_sid)])
    tgt = str(target_sid)
    if tgt not in uc:
        raise KeyError(f"_ranged_squad_edge_distance: unit {tgt} absente de units_cache")
    return ranged_edge_distance(attacker_socle, socle_from_cache_entry(uc[tgt]), metric)


def unit_can_reroll_charge(game_state: Dict[str, Any], unit_id: str) -> bool:
    """L unite porte-t-elle `reroll_charge` (config/unit_rules.json) ?

    « When this unit makes a charge, it can reroll the charge roll. » Regle d UNITE (pas
    d arme). Le chantier 05 l a purgee de TOUS les rosters : « Unstoppable Valour » etait un
    placeholder INVENTE, absent des 17 datasheets Armageddon. Plus aucune datasheet du jeu ne
    l accorde aujourd hui — ce qui ne rend pas ce code mort : de vraies datasheets 40K portent
    cette relance, et celle qui entrera au roster la declarera.

    Sur une unite ATTACHEE, la regle du leader vaut pour toute l unite (19.04, implemente le
    2026-07-27, cf. index_v11.md §9.2.8) : `_unit_has_rule_effect` lit les UNIT_RULES de
    l ESCOUADE, qui sont l union EN VIGUEUR de ses sources vivantes — recalculee a chaque mort
    par `recompute_unit_rules_in_effect`. Un Captain attache confere donc bien son reroll_charge
    a l escouade, et le lui retire en mourant.
    """
    unit = require_unit_by_id(game_state, str(unit_id))
    return _unit_has_rule_effect(unit, "reroll_charge")


def roll_charge_distance(
    game_state: Dict[str, Any], unit_id: str, *, previous_roll: Optional[int] = None,
) -> int:
    """Jet de charge 2D6 (11.02), avec `reroll_charge` si l unite le porte.

    `previous_roll` : jet deja effectue a relancer (None = premier jet). Un jet ne se relance
    qu une fois (PDF 01 Core, Re-rolls) — c est l appelant qui garantit l unicite en ne
    rappelant cette fonction avec `previous_roll` qu une seule fois.

    Aucun choix implicite ici : la DECISION de relancer appartient a l appelant, qui seul sait
    si le jet suffit (cf. `squad_charge` : relance si aucun plan n atteint la cible).

    `charge_roll_bonus` (Primitive A, chantier 06) est ajoute ICI et nulle part ailleurs : c est
    le SEUL producteur de jet de charge du moteur, donc le seul endroit ou les deux chemins (gym
    et PvP/roll-first) et la relance passent tous. Le poser chez un appelant en oublierait
    forcement un — et une relance qui perdrait le +1 serait pire qu un bonus absent. Aucun
    plafond : `+1 to charge rolls` n en a pas, un 2D6+1 va de 3 a 13.
    """
    import random
    del previous_roll  # signature explicite : le jet precedent est jete, jamais combine
    return (
        random.randint(1, 6)
        + random.randint(1, 6)
        + unit_charge_roll_bonus(game_state, str(unit_id))
    )


def _unit_was_set_up_this_turn(game_state: Dict[str, Any], squad_id: str) -> bool:
    """L unite a-t-elle ete mise en place sur le champ de bataille CE TOUR (clause 2 de 24.16) ?

    Source unique : `deployed_on_turn` (pose par le commit de deploiement). Conventions :
    0 = mise en place PRE-BATAILLE (phase de deploiement, ou positions fixees par le scenario) ;
    N > 0 = arrivee de reserve au tour N ; None = pas encore sur le board.

    Une unite non deployee ne tire pas : `None` ne peut pas etre « posee ce tour » -> False.
    Champ EXIGE (toute unite passe par create_unit / _build_enhanced_unit) : son absence est un
    bug de construction d unite, pas un cas metier -> erreur explicite.
    """
    unit = require_unit_by_id(game_state, str(squad_id))
    deployed_on_turn = require_key(unit, "deployed_on_turn")
    if deployed_on_turn is None:
        return False
    return int(deployed_on_turn) == int(require_key(game_state, "turn"))


#: 10.07 — planchers d echec du jet de touche NON MODIFIE. « An unmodified hit roll of 1-5 fails,
#: unless your unit remained stationary this turn AND the target is visible to one or more
#: friendly units, in which case an unmodified hit roll of 1-3 fails instead. »
#: Ce sont des PLANCHERS, pas des seuils : ils se composent avec la CT par un `max` (cf.
#: `attack_sequence._evaluate_roll`). 6 = « seul un 6 touche » ; 4 = « 1-3 echouent, puis la CT
#: s applique normalement » — un BS 5+ touche donc toujours sur 5+, jamais sur 4+.
INDIRECT_FAIL_BELOW = 6
INDIRECT_FAIL_BELOW_SPOTTED = 4

HEAVY_MOVED_THRESHOLD_INCHES = 3  # 24.16 clause 3 : « moved more than 3" this turn »


def _squad_remained_stationary(game_state: Dict[str, Any], squad_id: str) -> bool:
    """L escouade est-elle restee IMMOBILE ce tour (clause du plancher 4+ de 10.07) ?

    ⚠️ « Remained stationary » est PLUS FORT que « n a pas fait d advance », qui conditionne
    l eligibilite au tir indirect. Une unite qui a fait un mouvement normal de 1" est eligible a
    10.07 mais n a PAS droit au plancher de 4+. Confondre les deux donnerait le meilleur seuil a
    une unite qui s est repositionnee — le piege est nomme dans la spec du chantier.

    MEME source que la clause 3 de [HEAVY] (`moved_distance_by_model`, distance de CHEMIN
    accumulee par `commit_move`), pour que deux regles qui parlent du meme fait ne puissent pas
    en avoir deux mesures. Seuil zero strict : tout deplacement enregistre ferme le 4+.
    """
    models_cache = require_key(game_state, "models_cache")
    moved = require_key(game_state, "moved_distance_by_model")
    squad_models = require_key(game_state, "squad_models")
    for mid in squad_models.get(str(squad_id), []):  # get allowed (escouade morte = aucune fig)
        if mid not in models_cache:
            continue  # figurine detruite : elle ne tire plus, sa distance ne compte pas
        if float(moved.get(mid, 0.0)) > 0.0:  # get allowed (absente = n a pas bouge)
            return False
    return True


def _target_visible_to_a_friendly_unit(
    game_state: Dict[str, Any], shooter_squad_id: str, target_sid: str
) -> bool:
    """La cible est-elle visible d au moins UNE unite amie (clause « spotter » de 10.07) ?

    01.02 : « Friendly units and models are those in your army » — SANS exclusion de l unite
    active. L unite qui tire compte donc comme son propre spotter, et c est teste en premier :
    c est le cas le plus frequent et il evite de balayer l armee.

    Cout : `compute_unit_los` est memoise PAR PAIRE dans un cache persistant, invalide de facon
    ciblee par `_touch_unit_los` a chaque mouvement ou perte de figurine. Les paires
    (unite amie, cible) sont deja chaudes — c est le balayage d eligibilite au tir qui les
    remplit a chaque step. Ce predicat coute donc une dizaine de lectures de dict, pas un calcul
    de ligne de vue.
    """
    from engine.phase_handlers.shooting_handlers import compute_unit_los

    target_unit = require_unit_by_id(game_state, str(target_sid))
    shooter_unit = require_unit_by_id(game_state, str(shooter_squad_id))
    shooter_player = shooter_unit.get("player")  # get allowed
    ordered = [shooter_unit] + [
        u for u in require_key(game_state, "units")
        if u.get("player") == shooter_player  # get allowed
        and str(u.get("id")) != str(shooter_squad_id)  # get allowed
    ]
    for unit in ordered:
        if not is_unit_alive(str(require_key(unit, "id")), game_state):
            continue
        if compute_unit_los(game_state, unit, target_unit)["can_see"]:
            return True
    return False


def indirect_shooting_applies(
    game_state: Dict[str, Any], shooter_squad_id: str, weapon: Dict[str, Any]
) -> bool:
    """Les effets de 10.07 portent-ils sur une attaque de CETTE arme, par CETTE escouade ?

    Deux conditions, toutes deux necessaires : l unite resout un tir INDIRECT (le type est choisi
    a l activation, 10.02) ET l attaque est faite avec une arme [INDIRECT FIRE]. La seconde est ce
    qui distingue 10.07 des autres types de tir : ses effets ne portent QUE sur les armes
    indirectes, jamais sur leurs voisines — l encadre du PDF 10 le dit (« its other weapons can
    still target other visible targets »).

    ORDRE DES DEUX GARDES : la declaration d arme d abord, le type de tir ensuite. Ce n est pas
    cosmetique — `resolve_squad_shooting_type` balaie les figurines vivantes et leurs armes, et
    il exige `config.game_rules.engagement_zone`. Le tester d abord le ferait payer a CHAQUE
    attaque et a CHAQUE test de ciblage du jeu, pour une regle que deux armes du depot portent.

    Predicat PARTAGE par les deux faces de la regle — le ciblage (qui cesse d exiger la ligne de
    vue) et la resolution (plancher, couvert, relances). Deux copies auraient diverge, et le
    ciblage aurait alors ouvert des cibles que la resolution aurait traitees en tir ordinaire.
    """
    if not weapon_has_rule(weapon, "INDIRECT_FIRE"):
        return False
    return resolve_squad_shooting_type(
        game_state, str(shooter_squad_id)
    ) == SHOOTING_TYPE_INDIRECT


def indirect_fire_fail_below(
    game_state: Dict[str, Any],
    shooter_squad_id: str,
    target_sid: str,
    weapon: Dict[str, Any],
) -> Optional[int]:
    """Plancher d echec impose par 10.07 a CETTE attaque, ou None si la regle ne joue pas.

    Deux conditions, toutes deux necessaires : l unite resout un tir INDIRECT (le type est choisi
    a l activation, 10.02) ET l attaque est faite avec une arme [INDIRECT FIRE]. La seconde est ce
    qui distingue 10.07 des autres types de tir : ses penalites ne portent QUE sur les armes
    indirectes, jamais sur leurs voisines — l encadre du PDF 10 le dit (« its other weapons can
    still target other visible targets »).

    Rendre `None` plutot que 2 (le plancher naturel) est deliberatif : l appelant doit pouvoir
    distinguer « 10.07 n a pas joue » de « 10.07 a joue et impose le plancher ordinaire », ne
    serait-ce que pour le journal.
    """
    if not indirect_shooting_applies(game_state, shooter_squad_id, weapon):
        return None
    spotted = _squad_remained_stationary(game_state, shooter_squad_id) and (
        _target_visible_to_a_friendly_unit(game_state, shooter_squad_id, target_sid)
    )
    return INDIRECT_FAIL_BELOW_SPOTTED if spotted else INDIRECT_FAIL_BELOW


def _unit_moved_more_than_heavy_threshold(game_state: Dict[str, Any], squad_id: str) -> bool:
    """Une figurine de l escouade a-t-elle parcouru PLUS de 3" ce tour (clause 3 de 24.16) ?

    Source unique : `moved_distance_by_model`, accumule par `commit_move` en distance de CHEMIN
    (geodesique). Un dict vide signifie « aucun deplacement enregistre ce tour » — ce n est pas
    un repli masquant : le dict est REMIS A ZERO au debut du tour, exactement comme
    `units_moved`, et une figurine absente n a pas bouge.

    Comparaison STRICTE (« more than 3\" ») : un deplacement de 3" pile conserve le bonus.
    """
    models_cache = require_key(game_state, "models_cache")
    moved = require_key(game_state, "moved_distance_by_model")
    threshold = HEAVY_MOVED_THRESHOLD_INCHES * int(require_key(game_state, "inches_to_subhex"))
    squad_models = require_key(game_state, "squad_models")
    for mid in squad_models.get(str(squad_id), []):  # get allowed (escouade morte = aucune fig)
        if mid not in models_cache:
            continue  # figurine detruite : elle ne tire plus, sa distance ne compte pas
        if float(moved.get(mid, 0.0)) > threshold:  # get allowed (absente = n a pas bouge)
            return True
    return False


def _heavy_unit_is_engaged(game_state: Dict[str, Any], squad_id: str) -> bool:
    """L unite est-elle ENGAGEE (clause 1 de [HEAVY] 24.16) ?

    Meme predicat que le gate de tir 10.06 (`_is_adjacent_to_enemy_within_cc_range`) : une
    seule definition d « engage » dans le moteur. Unite introuvable = bug -> erreur explicite.
    """
    from engine.phase_handlers.shooting_handlers import _is_adjacent_to_enemy_within_cc_range
    unit = require_unit_by_id(game_state, str(squad_id))
    return bool(_is_adjacent_to_enemy_within_cc_range(game_state, unit))


def _target_within_half_range(
    game_state: Dict[str, Any], attacker_sid: str, target_sid: str, weapon: Dict[str, Any],
) -> bool:
    """Cible a DEMI-PORTEE de l arme, au sens « in the Select Targets step ».

    Mutualise par [RAPID FIRE] 24.30 et [MELTA] 24.25 — deux regles qui posent exactement la
    meme question. Demi-portee = RNG/2 (RNG deja en subhexes) ; distance escouade->escouade
    par le selecteur `ranged` (meme convention que le gate de portee du moteur). Les positions
    sont figees pendant la resolution : mesurer ici == mesurer au Select Targets step.
    RNG est EXIGE (une arme portant ces regles est une arme de tir) : aucun repli.
    """
    rng = int(require_key(weapon, "RNG"))
    if rng <= 0:
        return False
    return _ranged_squad_edge_distance(game_state, attacker_sid, target_sid) <= rng / 2.0


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
    if not is_unit_alive(target_sid, game_state):
        return None
    if target_sid not in targets_meta:
        _tgt_uc = require_key(game_state, "units_cache")[target_sid]
        _tgt_sc = require_key(game_state, "squad_cache")[target_sid]
        targets_meta[target_sid] = {
            "value": float(require_key(_tgt_uc, "VALUE")),
            "model_count_at_start": int(require_key(_tgt_sc, "model_count_at_start")),
            "player": int(require_key(_tgt_uc, "player")),
            "hp_before": int(require_key(_tgt_uc, "HP_CUR")),
        }
    weapon_index = int(intent.get("weapon_index", 0))  # get allowed
    weapons = ranged_weapons(attacker)
    if not (0 <= weapon_index < len(weapons)):
        return None
    weapon = weapons[weapon_index]
    if not isinstance(weapon, dict):
        return None
    if "n_attacks_resolved" in intent:
        n_attacks = int(intent["n_attacks_resolved"])
    else:
        # Aucun repli silencieux : NB absent ou non resoluble = donnee d arme invalide, elle
        # doit lever (l ancien defaut 1 + try/except la remplacait par 1 attaque en silence).
        n_attacks = resolve_dice_value(
            require_key(weapon, "NB"), f"squad_shoot_attacks_{attacker_mid}"
        )
    # [BLAST] 24.05 : des additionnels selon la taille de la cible AU SELECT TARGETS STEP
    # (d ou la taille capturee a la declaration, et non la taille courante).
    _blast_x = _blast_extra_dice_per_five(weapon)
    _blast_extra_dice = 0
    if _blast_x is not None:
        tgt_size = int(intent.get("target_squad_size_at_declaration", 0))  # get allowed
        # Des REELLEMENT ajoutes : 0 sur une cible de moins de 5 figurines, donc c est ce nombre
        # qui decide si la regle a JOUE — et donc si son token s affiche. La VALEUR du token, elle,
        # est le X declare (`_blast_x`), cf. `weapon_rule_log_tokens`.
        _blast_extra_dice = _blast_x * (tgt_size // 5)
        n_attacks += _blast_extra_dice
    # RAPID_FIRE X (config/weapon_rules.json ; PDF 24.30) : « Increase this weapon's Attacks
    # by X when target unit is within half range. » Ajoute X des a la constitution du pool
    # d attaques (comme BLAST), avant tout jet. Demi-portee = RNG/2 (RNG deja en subhexes).
    # Distance mesuree escouade->escouade via le selecteur `ranged` — meme convention que le
    # gate de portee du moteur (socle d escouade incluant les centres par-figurine) et que CTP.
    # Positions figees pendant la resolution => mesurer ici == « Select Targets step ».
    from engine.utils.weapon_helpers import weapon_rule_parameter
    _rf_x = weapon_rule_parameter(weapon, "RAPID_FIRE")
    # L13 [HALF RANGE] 24.25/24.30 : verdict de demi-portee mutualisé — RAPID_FIRE et MELTA
    # posent exactement la meme question avec le meme helper. Calculé UNE SEULE FOIS ici pour
    # eviter l appel double (l ancien code mesurait la distance deux fois). Si l arme porte
    # l une ou l autre regle (ou les deux), la distance est mesuree ici et reutilisee plus bas.
    _melta_x = weapon_rule_parameter(weapon, "MELTA")
    _at_half_range: bool = (
        (_rf_x is not None or _melta_x is not None)
        and _target_within_half_range(game_state, str(attacker["squad_id"]), target_sid, weapon)
    )
    # Valeur EFFECTIVEMENT appliquee (0 si l arme ne porte pas la regle ou si la cible est
    # hors demi-portee) : le log de tir en tire le token `[RAPID FIRE:X]`, dont l analyzer se
    # sert pour lever le PLAFOND de tirs de l escouade (NB de base -> NB + X). Sans lui, toute
    # activation RAPID FIRE produisait de faux « shots over RNG_NB ». Cf. V11 §0hist.38.
    # BOOLEEN, pas une copie du X : le X est deja porte par `_rf_x`, et un second porteur devrait
    # rester egal au premier sans que rien ne l'impose. Ce qu'on doit savoir ici, c'est « la
    # regle a-t-elle ajoute des des », exactement comme `_blast_extra_dice` cote [BLAST].
    _rapid_fire_applied = False
    if _rf_x is not None and _at_half_range:
        n_attacks += _rf_x
        _rapid_fire_applied = True
    if n_attacks <= 0:
        return None
    # Caracteristique de tir (BS) : la clef de l armory est `ATK` (243/243 profils de tir la
    # portent) — `BS` etait une orthographe fossile, et le defaut `4` transformait une arme
    # sans caracteristique en arme moyenne PLAUSIBLE, donc indetectable a l oeil.
    bs_base = int(require_key(weapon, "ATK"))
    # 10.07 : la regle joue-t-elle sur CETTE attaque, et avec quel plancher d echec ? Resolu ICI
    # parce que ses trois effets se posent a trois endroits differents de la suite — le couvert
    # juste en dessous, le plancher et l interdiction de relance a l appel du socle de resolution.
    # L helper est PARESSEUX : il sort sur la declaration d arme avant de resoudre le type de tir.
    _indirect_fail_below = indirect_fire_fail_below(
        game_state, str(attacker["squad_id"]), str(target_sid), weapon
    )
    bs, cover = _cover_worsened_bs(game_state, attacker, target_sid, bs_base, weapon)
    # 10.07 : « The target HAS the benefit of cover against that attack (13.08) ». Le couvert est
    # OCTROYE, pas calcule : la cible l a quelle que soit la geometrie, et 13.08 le traduit dans
    # ce moteur par une degradation de 1 du seuil de touche (plafond 6, cf. `_cover_worsened_bs`).
    #
    # ⚠️ [IGNORES COVER] 24.18 PRIME, et le PDF le dit lui-meme : « the target cannot have the
    # benefit of cover against that attack (13.08), INCLUDING FROM RULES THAT GIVE a model or unit
    # the benefit of cover ». 10.07 est exactement une telle regle. On lit donc le verdict de
    # `_cover_worsened_bs` — qui court-circuite deja sur 24.18 en rendant `cover=False` — plutot
    # que d ecraser le couvert sans condition. Aucune arme du depot ne porte les deux regles
    # aujourd hui ; la precedence est cablee pour que la premiere qui les portera soit juste.
    if _indirect_fail_below is not None and not cover and not weapon_has_rule(
        weapon, "IGNORES_COVER"
    ):
        bs = min(6, bs + 1)
        cover = True
    # [HEAVY] 24.16 (PDF, source de verite) : « In your Shooting phase, each time an attack is
    # made with a [HEAVY] weapon, add 1 to the hit roll if ALL of the following apply to the
    # attacking unit : that unit is UNENGAGED ; that unit was NOT SET UP on the battlefield this
    # turn ; NO MODEL in that unit has MOVED MORE THAN 3" this turn. »
    # +1 au jet de touche = seuil BS ameliore de 1, plancher 2 (un 1 non modifie rate toujours,
    # 05.01). Les trois clauses, dans l ordre du PDF :
    #  (1) unengaged           -> teste, meme predicat que le gate de tir 10.06 ;
    #  (2) pas pose ce tour    -> teste sur `deployed_on_turn` (pose par le commit de deploiement,
    #      source unique partagee avec la feature d observation deploiement/reserve) : 0 =
    #      pre-bataille, N = arrivee de reserve au tour N. Aujourd hui aucune arrivee en cours de
    #      bataille n existe (reserves 20 non modelisees) donc la clause est toujours satisfaite,
    #      mais elle est CABLEE : le jour ou les reserves arrivent, HEAVY sera juste sans retouche ;
    #  (3) aucune fig > 3"     -> teste sur la DISTANCE REELLE parcourue ce tour, accumulee par
    #      figurine par `commit_move` (`moved_distance_by_model`, distance de CHEMIN geodesique :
    #      contourner un mur coute plus cher que l ecart depart<->arrivee). C est la clause EXACTE
    #      du PDF : une escouade qui s est repositionnee de 2" garde son bonus, ce que la borne
    #      conservatrice d avant (« aucune figurine n a bouge ») lui refusait a tort.
    # Trace d affichage : le bonus a-t-il ETE APPLIQUE (pas « l arme declare HEAVY ») ? Le log
    # de tir en tire le token [HEAVY], comme [COVER] pour le couvert.
    _heavy_applied = False
    if weapon_has_rule(weapon, "HEAVY"):
        _heavy_sid = str(attacker["squad_id"])
        if (
            not _unit_moved_more_than_heavy_threshold(game_state, _heavy_sid)
            and not _heavy_unit_is_engaged(game_state, _heavy_sid)
            and not _unit_was_set_up_this_turn(game_state, _heavy_sid)
        ):
            bs = max(2, bs - 1)
            _heavy_applied = True
    # §22.05 PLUNGING FIRE : +1 BS si la cible contient ≥1 modele au sol ET
    #   (a) le tireur est sur une section ≥ plunging_fire_height pouces OU
    #   (b) le tireur a le keyword TOWERING et la cible est a ≤12".
    # Semantique PAR MODELE ATTAQUANT ("Each time a model makes a ranged attack").
    # Exception §23.03 AIRCRAFT hors perimetre (aucun AIRCRAFT dans le moteur).
    _plunging_fire_applied = False
    # floor_height_by_model vit dans units_cache (pas unit_by_id) ; absent en 2D => tout au sol.
    _pf_uc = game_state.get("units_cache") or {}
    _pf_tgt_uc = _pf_uc.get(str(target_sid))
    if _pf_tgt_uc is not None:
        _pf_tgt_floors = _pf_tgt_uc.get("floor_height_by_model")  # get allowed : absent en 2D
        # Cible contient >=1 figurine au sol : floor_height == 0.0 ; en 2D tout modele est au sol.
        _pf_any_tgt_ground = (
            any(float(h) == 0.0 for h in _pf_tgt_floors.values())
            if _pf_tgt_floors else True
        )
        if _pf_any_tgt_ground:
            _pf_atk_sid = str(require_key(attacker, "squad_id"))
            _pf_atk_uc = _pf_uc.get(_pf_atk_sid)
            _pf_atk_floors = (_pf_atk_uc or {}).get("floor_height_by_model")  # get allowed
            _pf_atk_h = float(_pf_atk_floors.get(attacker_mid, 0.0)) if _pf_atk_floors else 0.0
            if _pf_atk_h > 0.0:
                # (a) tireur a une hauteur plancher connue (3D) : court-circuit si 0 (jamais >=
                # plunging_fire_height qui est toujours > 0). require_key exige la config reelle.
                _pf_threshold = float(
                    require_key(require_key(require_key(game_state, "config"), "game_rules"), "plunging_fire_height")
                )
                if _pf_atk_h >= _pf_threshold:
                    bs = max(2, bs - 1)
                    _plunging_fire_applied = True
            if not _plunging_fire_applied:
                # (b) TOWERING : lazy import pour eviter le cycle (attack_sequence n importe pas shared_utils)
                # Keywords dans unit_by_id, pas dans units_cache.
                from engine.phase_handlers.attack_sequence import unit_keywords_upper as _kw_upper
                _pf_atk_unit = require_unit_by_id(game_state, _pf_atk_sid)
                if "TOWERING" in _kw_upper(_pf_atk_unit):
                    _pf_ish = int(require_key(game_state, "inches_to_subhex"))
                    _pf_dist = _ranged_squad_edge_distance(game_state, _pf_atk_sid, str(target_sid))
                    if _pf_dist <= 12 * _pf_ish:
                        bs = max(2, bs - 1)
                        _plunging_fire_applied = True
    # 04.03 IDENTICAL ATTACKS : signature NORMALISEE des regles de l arme. Calculee ICI et non a
    # la construction du dict de retour, parce que les trois blocs 10.05 / 10.06 ci-dessous la
    # lisent : deux accesseurs distincts sur les memes regles peuvent diverger, un seul non.
    _weapon_rules = weapon_rule_signature(weapon)
    _atk_sid = str(require_key(attacker, "squad_id"))
    # [ASSAULT] 24.04 (10.05) et [CLOSE-QUARTERS] 24.07 (10.06) sont des regles d ELIGIBILITE :
    # elles decident sous quel REGIME l escouade tire, et l autorite de ce verdict est
    # `resolve_squad_shooting_type` — c est elle qui porte les clauses que l arme ne dit pas
    # (a deja tire, a fui sans `shoot_after_flee`, et pour 10.06 « did not make an advance move
    # this turn »). Redériver ces conditions a cote de l autorite ne peut que la contredire :
    # les tokens du journal enregistrent donc SA decision, jamais une seconde mesure.
    #
    # Resolue PARESSEUSEMENT : le portier teste l engagement de l escouade, donc parcourt les
    # ennemis. Son verdict n est lu que si l arme declare l une des deux regles, ou si la
    # figurine est MONSTER/VEHICLE (volet malus 10.06 ci-dessous) — sinon aucun des trois blocs
    # ne peut etre vrai.
    _shooting_type: Optional[str] = None
    if (
        "ASSAULT" in _weapon_rules
        or "CLOSE_QUARTERS" in _weapon_rules
        or _model_is_monster_or_vehicle(attacker)
    ):
        _shooting_type = resolve_squad_shooting_type(game_state, _atk_sid)
    # L autorite dit que l escouade tire sous 10.05 ; l arme dit si c est ELLE qui porte la
    # regle. Les deux moities sont necessaires : sous `shoot_after_advance` (regle d UNITE du
    # projet) une arme sans [ASSAULT] devient selectionnable, et le token nommerait alors une
    # regle d arme qui n a pas joue.
    _assault_applied = (
        _shooting_type == SHOOTING_TYPE_ASSAULT and "ASSAULT" in _weapon_rules
    )
    # 10.06 : « you can only select [CLOSE-QUARTERS] weapons, and can only target units your
    # unit is engaged with ». L engagement se mesure donc AVEC LA CIBLE (`_squads_are_engaged`,
    # meme primitive que le ciblage et que le volet malus juste dessous), pas « avec un ennemi
    # quelconque » — deux grandeurs que le meme nom a deja fait confondre.
    _cq_applied = (
        _shooting_type == SHOOTING_TYPE_CLOSE_QUARTERS
        and "CLOSE_QUARTERS" in _weapon_rules
        and _squads_are_engaged(game_state, _atk_sid, str(target_sid))
    )
    # [10.06] tir a bout portant, volet MONSTER/VEHICLE : « Each time a MONSTER/VEHICLE model in
    # your unit makes an attack: unless that attack is made with a [CLOSE-QUARTERS] weapon AND
    # targets a unit your unit is engaged with, subtract 1 from the hit roll. » -1 au jet =
    # seuil BS degrade de 1 (plafond 6 : un 6 non modifie touche toujours, 05.01). Le volet
    # « non-MONSTER/VEHICLE » (armes et cibles restreintes) est applique en amont, au ciblage
    # (_shoot_engagement_blocks_target) et a la selection d armes (shooting_type_allows_weapon).
    _cq_malus_applied = False
    if _model_is_monster_or_vehicle(attacker):
        if _shooting_type == SHOOTING_TYPE_CLOSE_QUARTERS:
            _cq_engaged_target = _squads_are_engaged(game_state, _atk_sid, str(target_sid))
            if not ("CLOSE_QUARTERS" in _weapon_rules and _cq_engaged_target):
                bs = min(6, bs + 1)
                _cq_malus_applied = True
    # Force et penetration de l ARME : `STR`/`AP` sont portes par les 428 profils des rosters.
    # L ancien enchainement retombait sur `S` (fossile) puis sur la ENDURANCE DE L ATTAQUANT
    # (une caracteristique de figurine, sans rapport) puis sur 4 ; `AP` retombait sur 0, soit
    # « arme sans penetration » — deux valeurs de jeu parfaitement plausibles.
    strength = int(require_key(weapon, "STR"))
    ap = int(require_key(weapon, "AP"))
    # Aucun repli silencieux : DMG absent = donnee d arme invalide (require_key leve), la
    # valeur elle-meme est resolue a l application des degats (_resolve_one_manual_wound).
    dmg_raw = require_key(weapon, "DMG")
    # [MELTA X] 24.25 : « if the target unit was within half range of that weapon in the Select
    # Targets step, until the attacking unit's attacks have been resolved, add X to that
    # weapon's D characteristic. » Le bonus porte sur la CARACTERISTIQUE (D6+2, pas 2 degats
    # forfaitaires) : il est donc transporte jusqu a la resolution des degats et ajoute APRES
    # le tirage du de de degats (_resolve_one_manual_wound). Meme mesure de demi-portee que
    # RAPID FIRE (helper commun).
    dmg_bonus = 0
    # _melta_x et _at_half_range sont calculés en tête de fonction (avec _rf_x) — une seule
    # mesure de distance pour les deux règles.
    if _melta_x is not None and _at_half_range:
        dmg_bonus = int(_melta_x)
    alive0 = [m for m in game_state["squad_models"].get(target_sid, []) if m in models_cache]  # get allowed
    if not alive0:
        return None
    # Attaquant (escouade) resolu ICI : sert closest_target_penetration (ci-dessous) ET les
    # rerolls to-wound (plus bas). Constant pour l intent.
    attacker_unit = require_unit_by_id(game_state, str(attacker["squad_id"]))
    # Primitive B (chantier 06) — Bloc A : weapon_profile_scaling_by_model_count.
    # +S et +D par tranche de per_count figurines (Waaagh! Energy, WeirdBoy 'Eadbanger).
    # Doit preceder `wth = wound_threshold(strength, ...)` — la modification de Force doit
    # etre prise en compte dans le seuil de blessure. La modification de D (dmg_bonus) est
    # reportee au Bloc B (apres target_unit) pour etre disponible au meme endroit que les
    # autres bonus de D.
    from engine.phase_handlers.attack_sequence import _unit_get_primitive_b_rule_args as _pB_get_args
    _waaagh_energy_args = _pB_get_args(attacker_unit, "weapon_profile_scaling_by_model_count")
    _we_n_scalings = 0
    if _waaagh_energy_args is not None and weapon.get("code") == _waaagh_energy_args.get("weapon_code"):  # get allowed
        _we_per_count = int(_waaagh_energy_args.get("per_count", 5))  # get allowed
        _we_str_bonus = int(_waaagh_energy_args.get("str_bonus", 0))  # get allowed
        _we_squad_id = str(require_key(attacker_unit, "id"))
        _we_model_count = require_key(game_state, "squad_cache").get(_we_squad_id, {}).get("model_count", 0)
        _we_n_scalings = _we_model_count // _we_per_count
        if _we_n_scalings > 0:
            strength += _we_n_scalings * _we_str_bonus
    # Primitive A cote touche (chantier 06) : au TIR seul le MALUS de suppression peut jouer
    # (« While a unit is suppressed, it has -1 to hit rolls » ne restreint aucune phase) ; le +1
    # de Might Is Right est explicitement melee. Applique APRES couvert / [HEAVY] / 10.06 /
    # PLUNGING FIRE, qui ont deja borne `bs` chacun de leur cote : c est le meme seuil, et
    # `resolve_hit_roll_modifiers` re-applique le clamp 2..6 sur le total.
    bs, _hit_bonus_ability, _hit_malus_ability = resolve_hit_roll_modifiers(
        game_state, attacker_unit, bs, is_melee=False
    )
    # closest_target_penetration (regle projet unit_rules.json) : +1 de penetration (AP-1,
    # convention AP negatif cf. save_threshold) quand l unite tire sur la cible ELIGIBLE la
    # plus proche. Seule implementation depuis la suppression du code mort de tir (V11 §0.38).
    # La distance se mesure au niveau ESCOUADE (attacker["squad_id"]) : « closest eligible
    # unit » est une determination d unite (01.04, bord-a-bord via le selecteur `ranged`), pas
    # par figurine — attacker est ici une FIGURINE (models_cache), d ou le squad_id explicite.
    if _unit_has_rule_effect(attacker_unit, "closest_target_penetration"):
        from engine.phase_handlers.shooting_handlers import (
            shooting_build_valid_target_pool,
            _ranged_distance_metric,
        )
        from engine.combat_utils import socle_from_cache_entry
        _ctp_attacker_sid = str(attacker["squad_id"])
        _ctp_pool = shooting_build_valid_target_pool(game_state, _ctp_attacker_sid)
        if _ctp_pool:
            # metric + socle attaquant precalcules UNE fois puis injectes : la mesure vers chaque
            # cible du pool ne relit ni la config ni ne reconstruit le socle attaquant.
            _ctp_metric = _ranged_distance_metric(game_state)
            _ctp_attacker_socle = socle_from_cache_entry(require_key(game_state, "units_cache")[_ctp_attacker_sid])
            _closest = min(_ctp_pool, key=lambda uid: _ranged_squad_edge_distance(
                game_state, _ctp_attacker_sid, uid, metric=_ctp_metric, attacker_socle=_ctp_attacker_socle))
            if _closest == target_sid:
                ap = ap - 1
    # Conforme 19.02 : seuil de blessure vs plus haute T bodyguard (depend de l arme via strength).
    wth = wound_threshold(strength, _target_highest_bodyguard_toughness(game_state, target_sid))
    target_unit = require_unit_by_id(game_state, str(target_sid))
    # Oath of Moment (chantier 03) : MEME helper que la melee, plancher compris.
    _base_wth_shoot = wth
    _is_oath_target, _oath_wound_bonus, wth = resolve_oath_effects(
        game_state, attacker_unit, target_sid, wth
    )
    if _oath_wound_bonus:
        _cap_wound = _bonus_malus_cap(game_state)
        if _cap_wound and _oath_wound_bonus > _cap_wound:
            wth = max(2, _base_wth_shoot - _cap_wound)
    first_alive = models_cache[alive0[0]]
    display_wth = wth
    # Seuil affiche + Waaagh! de la CIBLE : helper partage avec la melee. Le +1 F / +1 A, lui,
    # ne touche QUE les armes de melee (08.04) : il n a pas de jumeau au tir.
    display_save_th, _waaagh_target_invul = display_save_threshold_with_waaagh(
        game_state, target_unit, first_alive, ap
    )
    weapon_name = weapon.get("display_name", weapon.get("NAME", weapon.get("name", "")))  # get allowed
    # Rerolls to-wound au TIR (abilities UNITE, constantes pour l intent) — miroir exact du
    # fight (_manual_roll_fight_intent) : reroll_1_towound = reroll d un dé de blessure = 1 ;
    # reroll_towound_target_on_objective = reroll de tout échec si la cible est sur objectif.
    reroll_wound1 = _unit_has_rule_effect(attacker_unit, "reroll_1_towound")
    reroll_wound_obj = (
        _unit_has_rule_effect(attacker_unit, "reroll_towound_target_on_objective")
        and is_unit_on_objective(target_unit, game_state)
    )
    _weapon_precision = weapon_has_rule(weapon, "PRECISION")
    # Sequence d attaque commune tir/melee (05.01/05.02 + regles d armes 24) : socle unique
    # `attack_sequence.roll_attack_pool`. Y vivent touches/blessures CRITIQUES, [TORRENT],
    # [SUSTAINED HITS], [LETHAL HITS], [TWIN-LINKED], [ANTI-X] et [DEVASTATING WOUNDS].
    # Restent ici (specifiques au tir) : pool d attaques (BLAST/RAPID FIRE), seuil de touche
    # (couvert/HEAVY/PSYCHIC), AP effectif (closest_target_penetration) et l allocation.
    from engine.phase_handlers.attack_sequence import (
        RerollProfile, build_weapon_attack_profile, roll_attack_pool,
        unit_keywords_upper as _kw_upper_b,
    )
    # Primitive B (chantier 06) — Bloc B : bonus d attaques de tir et D scaling.
    # target_unit est disponible ici (resolu plus haut) — on peut lire ses keywords.
    _target_kws_b = _kw_upper_b(target_unit)
    _target_is_non_mv = _target_kws_b.isdisjoint({"MONSTER", "VEHICLE"})
    # weapon_attacks_bonus_vs_keyword : +N A si cible hors excluded_keywords (Dakkablitz)
    _dakkablitz_args = _pB_get_args(attacker_unit, "weapon_attacks_bonus_vs_keyword")
    if _dakkablitz_args is not None:
        _dk_weapon_code = _dakkablitz_args.get("weapon_code")  # get allowed
        _dk_excl = _dakkablitz_args.get("excluded_keywords", [])  # get allowed
        _dk_target_ok = all(
            kw.strip().upper().replace(" ", "_").replace("-", "_") not in _target_kws_b
            for kw in _dk_excl
        )
        if weapon.get("code") == _dk_weapon_code and _dk_target_ok:  # get allowed
            n_attacks += int(require_key(_dakkablitz_args, "attacks_bonus"))
    # weapon_attacks_bonus_vs_designated_target : +N A vs cible designee (Hail of Bolts).
    # Dans ce moteur la cible de l intent EST la cible designee — pas de designation separee.
    _hob_args = _pB_get_args(attacker_unit, "weapon_attacks_bonus_vs_designated_target")
    if _hob_args is not None and weapon.get("code") == _hob_args.get("weapon_code"):  # get allowed
        n_attacks += int(require_key(_hob_args, "attacks_bonus"))
    # grant_weapon_rule_vs_designated_target : [BLAST 1] hors MONSTER/VEHICLE (Overlapping Detonations).
    # [BLAST 1] = 1 de par tranche de 5 figurines dans la cible.
    _od_args = _pB_get_args(attacker_unit, "grant_weapon_rule_vs_designated_target")
    if (_od_args is not None
            and weapon.get("code") == _od_args.get("weapon_code")  # get allowed
            and _target_is_non_mv):
        _od_tgt_size = int(require_key(intent, "target_squad_size_at_declaration"))
        n_attacks += _od_tgt_size // 5
    # Waaagh! Energy +D : les scalings _we_n_scalings et _waaagh_energy_args sont du Bloc A.
    if _we_n_scalings > 0 and _waaagh_energy_args is not None:
        _we_dmg_bonus_per = int(_waaagh_energy_args.get("dmg_bonus", 0))  # get allowed
        dmg_bonus += _we_n_scalings * _we_dmg_bonus_per
    _attack_profile = build_weapon_attack_profile(
        weapon, target_unit,
        attacker_unit=attacker_unit,
        game_state=game_state,
        is_melee=False,
    )
    rolled = roll_attack_pool(
        n_attacks=int(n_attacks),
        hit_target=bs,
        wound_target=wth,
        save_threshold_value=display_save_th,
        profile=_attack_profile,
        rerolls=RerollProfile(
            # Oath of Moment : « You can re-roll the Hit roll » contre la cible designee.
            # JUMEAU du site de melee — c est le motif d echec n°1 du depot : une relance
            # cablee au tir seulement ferait de la mitraille orke un cas particulier silencieux.
            # « You can re-roll the Hit roll » : INCONDITIONNELLE des que la cible est la bonne
            # — ni le detachement ni les sous-factions ne la touchent, contrairement au +1 Wound.
            # 10.07 : « You cannot re-roll hit rolls » — l interdiction est ABSOLUE et prime sur
            # la capacite, d ou le `and not`. Elle ne touche QUE la touche : les relances de
            # blessure ci-dessous (capacites d unite, [TWIN-LINKED]) restent ouvertes, la regle
            # n en parle pas.
            hit_any_fail=_is_oath_target and _indirect_fail_below is None,
            wound_1=reroll_wound1,
            wound_any_fail=reroll_wound_obj,
        ),
        roll_d6=lambda: random.randint(1, 6),
        # 10.07 : plancher d echec sur le de NON MODIFIE. `None` -> le socle garde le plancher
        # naturel de 05.01 (seul le 1 echoue), donc aucune attaque ordinaire ne change.
        **({} if _indirect_fail_below is None else {"hit_fail_below": _indirect_fail_below}),
    )
    # Noms des ABILITES qui ont ouvert chaque relance. Le socle rend la CAUSE, les deux
    # `resolve_*_reroll_ability` la traduisent — memes helpers que la melee, pour que les deux
    # chemins ne puissent pas diverger. Resolution memoisee sur l intent, et PARESSEUSE : on ne
    # lit le nom d affichage que si une relance a REELLEMENT eu lieu
    # (`get_source_unit_rule_display_name_for_effect` exige un `displayName` non vide sur la
    # regle source — inutile de l exiger d une unite dont aucune relance n a joue).
    stamp_reroll_abilities(
        rolled["shot_records"], attacker_unit,
        reroll_1_towound=reroll_wound1,
        reroll_towound_on_objective=reroll_wound_obj,
    )
    # +1 au jet de blessure d Oath. Meme helper que la melee (cf. `stamp_wound_bonus_ability`).
    stamp_wound_bonus_ability(rolled["shot_records"], _oath_wound_bonus)
    # Primitive A (chantier 06) : au tir, seul le malus de suppression peut avoir joue — le
    # bonus de melee est None par construction (`is_melee=False`) et le +1 de blessure n a pas
    # de jumeau au tir. Les trois arguments sont passes explicitement pour que le site de tir et
    # celui de melee restent lisibles l un a cote de l autre.
    stamp_roll_modifier_abilities(
        rolled["shot_records"],
        hit_bonus=_hit_bonus_ability,
        hit_malus=_hit_malus_ability,
        wound_bonus=None,
    )

    return {
        "attacker_mid": attacker_mid, "attacker": attacker, "target_sid": target_sid,
        "weapon_name": weapon_name, "bs": bs, "bs_base": bs_base, "cover": cover, "ap": ap,
        "dmg_raw": dmg_raw, "dmg_bonus": dmg_bonus,
        # L13 — demi-portee verifiee pour les armes RAPID_FIRE et/ou MELTA. Transporte jusqu au
        # journal via `atHalfRange` du groupe puis `[HALF RANGE]` dans step.log. False pour
        # toute arme sans ces deux regles (meme si la cible est physiquement a demi-portee).
        "at_half_range": _at_half_range,
        # [PRECISION] 24.28 (tir) : la visibilite de la figurine CHARACTER se teste a la portee
        # de l arme, avec la meme primitive que le gate de tir. RNG n est exige que si l arme
        # porte la regle (seul cas ou la valeur est lue).
        "heavy_applied": _heavy_applied,
        # §22.05 PLUNGING FIRE : tireur en hauteur (>=3") ou TOWERING a <=12" — +1 BS applique.
        "plunging_fire_applied": _plunging_fire_applied,
        # 04.03 IDENTICAL ATTACKS, seconde moitie de la definition : « affected by the same
        # applicable abilities and rules ». Entre dans la cle de groupe.
        "weapon_rules": _weapon_rules,
        # [ASSAULT] 24.04 / [CLOSE-QUARTERS] 24.07 : verdict du portier 10.05/10.06 pour CETTE
        # arme et CETTE cible. Pose ICI, au seul endroit qui connait la cible et ou l autorite
        # est deja consultee — le groupe le RELIT, comme `heavy_applied` et `point_blank_malus`.
        "assault_applied": _assault_applied,
        "close_quarters_applied": _cq_applied,
        # 10.07 tir indirect : plancher d echec (6 ou 4) quand la regle joue sur cette attaque,
        # None sinon. Le groupe le RELIT, exactement comme `assault_applied` ci-dessus.
        "indirect_fire_fail_below": _indirect_fail_below,
        # Tokens de regles d arme de la ligne de log. Constants sur le groupe par CONSTRUCTION :
        # chacune de leurs sources est dans `gkey` (signature de regles, `dmg_bonus`, le X
        # applique de [RAPID FIRE], cible — donc la taille declaree qui pilote [BLAST] et les
        # keywords qui pilotent [ANTI]) ou dans `bs` (couvert, qui conditionne [PSYCHIC]).
        # Arme et regles resolues vs CETTE cible : le groupe les garde par REFERENCE et le log
        # en tire ses tokens a l emission (`weapon_rule_log_tokens`), une fois pour le groupe.
        "weapon": weapon,
        "attack_profile": _attack_profile,
        # 10.06, volet MONSTER/VEHICLE : -1 au jet de touche. Ce drapeau etait calcule et
        # JAMAIS lu — il ne restait donc plus qu un seul modificateur du seuil affiche sans
        # cause visible, alors que [HEAVY] et [COVER] avaient la leur.
        "point_blank_malus": _cq_malus_applied,
        # Regles additives ayant JOUE pour CETTE figurine, et leur X DECLARE : [BLAST] 24.05 (une
        # tranche de 5 par porteuse) et [RAPID FIRE] 24.30 (X par porteuse a demi-portee). C est
        # ce X que le token affiche (cf. `weapon_rule_log_tokens`) ; le nombre de des ajoutes,
        # lui, est deja compte dans `attacks`. Les deux X sont deja resolus ici — les transporter
        # evite a l afficheur de les re-deriver de son cote.
        "additive_rules_applied": {
            label: x
            for label, x, applied in (
                (RULE_LABEL_BLAST, _blast_x, _blast_extra_dice > 0),
                (RULE_LABEL_RAPID_FIRE, _rf_x, _rapid_fire_applied),
            )
            if applied and x is not None
        },
        "precision": _weapon_precision,
        "precision_range": int(require_key(weapon, "RNG")) if _weapon_precision else None,
        "display_wth": display_wth, "display_save_th": display_save_th,
        # Oath of Moment dans la LIGNE DE SYNTHESE (`Hit:3+RR [OATH OF MOMENT] Wound:3+ [...]`) :
        # les deux effets sont constants sur un groupe (meme attaquant, meme cible), et le detail
        # par tir ne suffit pas — la relance peut n avoir joue sur aucune attaque du groupe alors
        # que la capacite, elle, etait bien en vigueur. JUMEAU du roller de melee.
        "oath_hit_reroll": bool(_is_oath_target),
        # BOOLEEN : la magnitude du +1 est consommee en amont (`wth - _oath_wound_bonus`),
        # le log ne demande que « est-ce que ca a joue ». Jumeau exact de `oath_hit_reroll`.
        "oath_wound_bonus": bool(_oath_wound_bonus),
        # Waaagh! : le +1 Force / +1 Attaque ne porte QUE sur les armes de melee (08.04), donc
        # toujours faux ici. La cle est ECRITE et non omise : la construction de groupe l exige
        # (`require_key`), et un producteur qui l oublierait leverait au lieu de retomber en
        # silence sur « pas de Waaagh! » — c est le tir qui doit affirmer que la regle ne
        # s applique pas, pas le lecteur qui le devine.
        "waaagh_melee_bonus": False,
        # Waaagh! de la CIBLE, lui, joue aussi au tir : la sauvegarde invulnerable 5+ octroyee
        # s oppose a toutes les attaques, pas seulement a la melee.
        "waaagh_target_invul": _waaagh_target_invul,
        "shot_records": rolled["shot_records"], "pending_wounds": rolled["pending_wounds"],
        "counts": rolled["counts"],
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
    # FIGURINE ALLOUEE (05 Attack sequence, « Allocate Attack ») — ecrite ICI, avant les trois
    # retours anticipes ci-dessous (save reussie, D nul, Feel No Pain), parce que l allocation a
    # eu lieu dans TOUS ces cas : c est le fait, les degats n en sont que la consequence.
    #
    # Sans elle, le journal disait qu une escouade perd des PV sans jamais dire QUI les perd, et
    # l analyzer devinait — avec un tri (non-CHARACTER puis ordre du segment) qui ignore la
    # cascade reelle de `_select_allocation_model` (blessee d abord, tier de role, proximite).
    # Mesure du 2026-08-12 sur 600 episodes : 200 PV par socle faux sur 173 129 compares aux
    # instantanes `T{n} STATE:`, et 2 342 fenetres ou l escouade entiere retombait sur son ancre.
    rec["targetModelId"] = str(cur)
    # L4 — AP de l arme et Sv de base de la figurine : permettent au formateur StepLogger
    # d ecrire `Save R(<base>+ AP<n> → <eff>+)` au lieu de `Save R(<eff>+)`, debloquant le
    # controle de seuil de sauvegarde par l analyzer (05.04, 06.02, 24.18).
    rec["weaponAp"] = ap
    rec["allocModelArmor"] = int(m["ARMOR_SAVE"])
    from engine.game_state import effective_invul_save  # import paresseux : cycle, cf. plus haut

    # Waaagh! (chantier 03) : « models from your army with this ability have a 5+ invulnerable
    # save ». C est ICI que la sauvegarde est reellement comparee — le seuil d affichage calcule
    # au jet ne decide de rien. Le proprietaire de la FIGURINE allouee est l autorite : c est lui
    # dont le Waaagh! peut etre actif, pas l attaquant.
    _def_unit = require_unit_by_id(game_state, str(require_key(m, "squad_id")))
    _invul = int(require_key(m, "INVUL_SAVE"))
    _invul = effective_invul_save(game_state, _def_unit, _invul)
    save_th = save_threshold(int(m["ARMOR_SAVE"]), _invul, ap)
    rec["saveTarget"] = save_th
    # DEVASTATING_WOUNDS (weapon_rules.json) : « No saving throw can be made against a critical
    # wound. » Le flag est pose au jet (blessure critique = 6 non modifie). On SAUTE la
    # comparaison de save : la blessure echoue d office, degats appliques comme une save ratee.
    _devastating = bool(pw.get("devastating"))
    if not _devastating:
        # Le de n existe QUE hors DEVASTATING : sur un critique, la sauvegarde n a pas ete
        # faite (24.10), donc `pw["save_roll"]` vaut None — le lire serait une erreur.
        save_roll = int(require_key(pw, "save_roll"))
        # Save reussie : roll != 1 et >= seuil. Aucun degat.
        if save_roll != 1 and save_roll >= save_th:
            rec["saveSuccess"] = True
            rec["damageDealt"] = 0
            batch["pool_index"] += 1
            return
    rec["saveSuccess"] = False
    if _devastating:
        # DEVASTATING_WOUNDS (24.10) : blessure critique -> blessure MORTELLE. Aucune save
        # (armure ET invulnerable). Tag explicite pour le log/display et un futur hook Feel
        # No Pain (point d accroche unique). Degats = D appliques a UNE figurine (excess perdu
        # ci-dessous, comme « max one model per critical wound »).
        rec["saveSkipped"] = True
        # Motif de saut : consomme par le formateur du StepLogger (`Save [DEVASTATING WOUNDS]`),
        # que l analyzer ET le replay cherchent par regex. Sans cette cle, les deux sont aveugles.
        rec["saveSkipReason"] = "DEVASTATING_WOUNDS"
        rec["mortalWound"] = True
    summary["failed_saves"] += 1
    # Degats tires UNIQUEMENT maintenant (save echouee).
    # Aucun repli silencieux : une valeur de DMG non resoluble est une donnee d arme invalide,
    # elle doit lever (l ancien try/except la remplacait par 1 en silence, et avalait au passage
    # le KeyError d un lot d attaques mal forme). Le tag nomme la figurine attaquante.
    dmg = resolve_dice_value(dmg_raw, f"squad_shoot_dmg_{require_key(pw, 'attacker_mid')}")
    # [MELTA X] 24.25 : X s ajoute a la caracteristique D -> apres le tirage du de de degats
    # (D6+2, jamais 2 forfaitaire). 0 pour toute arme sans MELTA ou hors demi-portee.
    dmg += int(require_key(g, "dmg_bonus"))
    if dmg <= 0:
        rec["damageDealt"] = 0
        rec["targetDied"] = False
        batch["pool_index"] += 1
        return
    hp_before = int(m["HP_CUR"])
    dmg_dealt = min(int(dmg), hp_before)
    # Feel No Pain (24.12) : jet D6 par HP perdu ; sur threshold+, la blessure est ignorée.
    # Inclut les variantes conditionnelles (PSYCHIC, near_objective) via _collect_fnp_thresholds.
    _def_squad_fnp = require_unit_by_id(game_state, str(batch["target_sid"]))
    _fnp_ths = _collect_fnp_thresholds(_def_squad_fnp, game_state, require_key(g, "weapon"))
    if _fnp_ths:
        _fnp_attempts = dmg_dealt
        dmg_dealt = _roll_fnp_sequential(dmg_dealt, _fnp_ths)
        # L12 — jets FNP dans step.log (24.12) : saves/seuil+/tentatives.
        rec["fnpSaves"] = _fnp_attempts - dmg_dealt
        rec["fnpAttempts"] = _fnp_attempts
        rec["fnpThreshold"] = _fnp_ths[0]
    if dmg_dealt <= 0:
        rec["damageDealt"] = 0
        rec["targetDied"] = False
        batch["pool_index"] += 1
        return
    new_hp = hp_before - dmg_dealt
    destroyed = new_hp <= 0
    points_per_hp = float(require_key(m, "points_per_hp"))
    # Valeur de CETTE figurine (pas la moyenne d'escouade) : le reward de kill la lit
    # pour recompenser le ciblage des figurines cheres (Nob, sergent, perso attache).
    model_value = float(require_key(m, "VALUE"))
    target_player = int(require_key(m, "player"))
    unit_type = m.get("unitType")  # get allowed
    # Position de la figurine TOUCHEE, capturee AVANT une eventuelle destruction : elle part
    # dans `shootDetails` du log (step.log + replay). Toute figurine du models_cache porte
    # col/row (construits par `_build_models_for_unit` avec require_key) : l ancien `.get`
    # rendait un `None` silencieux dans la donnee d analyse au lieu de lever.
    col = int(require_key(m, "col"))
    row = int(require_key(m, "row"))
    g["damage"] += dmg_dealt
    summary["damage_total"] += dmg_dealt
    rec["damageDealt"] = dmg_dealt
    rec["targetDied"] = destroyed
    # VALUE de la figurine VISEE par cette attaque (pas la valeur d'escouade), capturee ici
    # parce qu'elle n'est plus lisible apres coup : `destroy_model` retire la figurine du
    # models_cache. C'est la seule voie pour ventiler la valeur detruite par phase cote
    # metriques — `summary["events"]` porte la meme donnee mais ne remonte jamais jusqu'a
    # `step()` dans le pipeline squad V11.
    rec["targetValue"] = model_value
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
        "damage": dmg_dealt, "destroyed": destroyed, "model_value": model_value,
    })
    batch["pool_index"] += 1
    if destroyed:
        batch["current_model_id"] = None


def _mark_manual_overkill_wasted(batch: Dict[str, Any]) -> None:
    """Cible entierement detruite avec des paquets non alloues : tirs restants perdus."""
    for pd in batch["pool"][batch["pool_index"]:]:
        pd["rec"]["wasted"] = True
    batch["pool_index"] = len(batch["pool"])


def _auto_declared_order(
    game_state: Dict[str, Any], live_groups: List[Dict[str, Any]]
) -> List[int]:
    """Ordre d allocation automatique (defenseur non-humain), conforme 05.04 :
       1. groupes non-CHARACTER avec une figurine blessee ;
       2. groupes non-CHARACTER sains ;
       3. groupes CHARACTER blesses ;
       4. groupes CHARACTER sains.
    Sous-ordre deterministe par group_id. Reproduit l intention defensive de
    _select_allocation_model (characters exposes en dernier, blesses finis d abord)."""
    models_cache = require_key(game_state, "models_cache")

    def _wounded(g: Dict[str, Any]) -> bool:
        return any(
            m in models_cache and int(models_cache[m]["HP_CUR"]) < int(models_cache[m]["HP_MAX"])
            for m in g["model_ids"]
        )

    def _rank(g: Dict[str, Any]) -> tuple:
        # character en dernier ; a categorie egale, blesse avant sain ; puis group_id.
        return (bool(g["is_character"]), not _wounded(g), int(g["group_id"]))

    return [g["group_id"] for g in sorted(live_groups, key=_rank)]


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
    attacker_squad_id = str(alloc["attacker_squad_id"])
    batches = alloc["batches"]
    primary_target_sid = str(batches[0]["target_sid"]) if batches else None
    hazardous_count = int(alloc["hazardous_weapon_count"]) if "hazardous_weapon_count" in alloc else 0
    # 19.04, derniere clause : « the ability it was conferring applies until the attacking unit
    # has resolved all of its attacks ». On y est. Les squads dont une source de regle est morte
    # sous cette attaque sont recalcules APRES la suppression de l allocation — c est elle qui
    # portait le sursis, donc le recalcul voit enfin la source eteinte.
    _grace_squads = {
        str(entry["squad_id"])
        for entry in alloc.get("rule_sources_in_grace", [])  # get allowed (absent si aucune mort)
    }
    del game_state[ctx.alloc_key]
    for _sid in _grace_squads:
        recompute_unit_rules_in_effect(game_state, _sid)
    result = {
        "action": ctx.manual_alloc_action,
        "waiting_for_player": False,
        "done": True,
        "shoot_result": summary,
        "attacker_squad_id": attacker_squad_id,
        "primary_target_sid": primary_target_sid,
    }
    # [HAZARDOUS] 24.15 : « Each time a unit is selected to shoot or selected to fight, AFTER
    # THAT UNIT HAS RESOLVED ALL OF ITS ATTACKS, make a number of hazard rolls (06.03) for that
    # unit equal to the number of [HAZARDOUS] weapons you selected in the Select Weapons step. »
    # C est exactement ce point : l allocation de l activation vient de se terminer.
    # Le porteur des blessures mortelles est le TIREUR/COMBATTANT lui-meme.
    if hazardous_count > 0 and ctx.hazard_origin:
        auto = is_programmatic_owner(
            game_state, require_key(require_key(game_state, "units_cache")[attacker_squad_id], "player")
        ) if attacker_squad_id in require_key(game_state, "units_cache") else True
        game_state["hazard_origin"] = ctx.hazard_origin
        roll_hazard_for_unit(
            attacker_squad_id, game_state, auto,
            n_rolls=hazardous_count, context_label="Hazardous",
        )
        if not auto and "pending_hazard_allocation" in game_state:
            # Joueur humain : l attribution des MW est un point de decision (05.03/06.02).
            # La main lui est rendue ; la reprise post-allocation lit `hazard_origin`.
            return manual_allocation_waiting_payload(game_state, HAZARD_CTX)
        game_state.pop("hazard_origin", None)
    return result


def _apply_precision_allocation_override(
    game_state: Dict[str, Any], alloc: Dict[str, Any], batch: Dict[str, Any],
) -> None:
    """[PRECISION] 24.28 — au debut de l Allocation Order step (05.03).

    « While resolving attacks made with one or more [PRECISION] weapons, at the start of the
    Allocation Order step, if the target unit contains one or more CHARACTER models VISIBLE to
    one or more of the attacking models, the active player CAN select one allocation group that
    contains one of those visible CHARACTER models. If they do, until those attacks are resolved,
    or until that CHARACTER group is destroyed, that CHARACTER group is the current allocation
    group. »

    Arbitrage du « can » : l attaquant designe TOUJOURS le groupe CHARACTER visible le plus
    couteux (VALUE). Sans cela la regle serait inerte — c est son unique effet — et le choix est
    strictement favorable a l attaquant. Candidat a une decision agent (Phase A' P3).

    L ordre declare par le DEFENSEUR est conserve : seul le groupe COURANT change (le groupe
    CHARACTER passe en tete). Le reste de l ordre suit inchange.
    """
    group = alloc["weapon_groups"][batch["weapon_group_idx"]] if batch["weapon_group_idx"] is not None else None
    if group is None or not group.get("precision"):  # get allowed (groupes hazard : pas d arme)
        return
    models_cache = require_key(game_state, "models_cache")
    char_groups = [
        g for g in batch["alloc_groups"]
        if g["is_character"] and _group_alive(game_state, g)
    ]
    if not char_groups:
        return
    visible = [g for g in char_groups if _precision_group_is_visible(game_state, group, g)]
    if not visible:
        return
    chosen = max(
        visible,
        key=lambda g: max(float(require_key(models_cache[m], "VALUE"))
                          for m in g["model_ids"] if m in models_cache),
    )
    order = list(batch["declared_order"])
    if chosen["group_id"] in order:
        order.remove(chosen["group_id"])
    batch["declared_order"] = [chosen["group_id"]] + order
    batch["current_group_index"] = 0
    batch["current_model_id"] = None
    # La regle a REELLEMENT joue : c est ici, et nulle part ailleurs, qu on le sait. Les trois
    # `return` ci-dessus sont autant de cas ou l arme declare [PRECISION] sans qu aucun groupe
    # CHARACTER visible n existe — le log ne doit alors pas la nommer. Le drapeau est pose sur le
    # GROUPE (et non sur le batch) parce que c est le groupe que l emission du log lit.
    group["precision_applied"] = True


def _precision_group_is_visible(
    game_state: Dict[str, Any], weapon_group: Dict[str, Any], char_group: Dict[str, Any],
) -> bool:
    """Une figurine CHARACTER du groupe est-elle visible par une figurine attaquante (24.28) ?

    Melee (`precision_range` absent) : les figurines sont au contact, la visibilite est acquise
    (06.01 — aucun terrain ne peut s interposer a distance d engagement).
    Tir : meme primitive que le gate de tir (`_attacker_model_can_reach_squad`, per-figurine,
    footprint complet, obscuring-aware), restreinte aux figurines CHARACTER du groupe.
    """
    rng = weapon_group["precision_range"]
    if rng is None:
        return True
    models_cache = require_key(game_state, "models_cache")
    char_mids = {m for m in char_group["model_ids"] if m in models_cache}
    if not char_mids:
        return False
    for mid in weapon_group["shooter_mids"]:
        shooter = models_cache.get(mid)  # get allowed (figurine morte depuis la declaration)
        if shooter is None:
            continue
        if _attacker_model_can_reach_squad(
            game_state, shooter, int(shooter["col"]), int(shooter["row"]),
            str(weapon_group["target_sid"]), int(rng), only_target_mids=char_mids,
        ):
            return True
    return False


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
                if ctx.auto_decider is not None and ctx.auto_decider(game_state, batch["target_sid"]):
                    batch["declared_order"] = _auto_declared_order(game_state, live_groups)
                    batch["current_group_index"] = 0
                else:
                    return _declare_order_payload(game_state, batch, live_groups, ctx)
            else:
                batch["declared_order"] = [g["group_id"] for g in live_groups]  # ordre implicite
                batch["current_group_index"] = 0
        # 2bis. [PRECISION] 24.28 : l attaquant peut imposer un groupe CHARACTER visible comme
        # groupe courant, une seule fois par lot (l override est idempotent : il ne s applique
        # qu au moment ou l ordre vient d etre fixe).
        if not batch.get("precision_applied"):  # get allowed (cle posee a la 1re application)
            batch["precision_applied"] = True
            _apply_precision_allocation_override(game_state, alloc, batch)
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
                elif ctx.auto_decider is not None and ctx.auto_decider(game_state, batch["target_sid"]):
                    # get allowed : absent = False ; ≥2 candidats requis par le mécanisme décision
                    # En bot-eval (BotControlledEnv), `controlled_player` identifie l'agent entraîné.
                    # La décision n'est armée que si le défenseur EST cet agent — pas quand c'est
                    # le bot. En self-play (pas de BotControlledEnv), controlled_player est absent :
                    # on arme pour les deux sides (comportement P3-4 original).
                    _def_player = str(require_key(
                        require_key(game_state, "units_cache")[str(batch["target_sid"])], "player"))
                    _controlled = game_state.get("controlled_player")
                    _is_agent_defending = (
                        _controlled is None or int(_def_player) == int(_controlled)
                    )
                    if (game_state.get("gym_training_mode") and _is_agent_defending
                            and len(alive_grp) >= 2
                            and not game_state.get("no_gym_allocation_model")):
                        _arm_allocation_model_decision(
                            game_state, batch["target_sid"], alive_grp, ctx)
                        return {"waiting_for_player": True, "action": "allocation_model_pending"}
                    batch["current_model_id"] = _select_allocation_model(
                        game_state, batch["target_sid"], alive_grp)
                else:
                    return _manual_waiting_payload(game_state, batch, alive_grp, ctx)  # choix libre
            (ctx.resolve_wound_fn or _resolve_one_manual_wound)(game_state, alloc, batch, ctx)
        if not advanced_batch:
            break
    return _finalize_manual_allocation(game_state, ctx)


def _count_selected_hazardous_weapons(
    game_state: Dict[str, Any], ctx: ManualAllocCtx, intents: List[Dict[str, Any]],
) -> int:
    """Nombre d armes [HAZARDOUS] 24.15 selectionnees par l escouade (Select Weapons, 04.01).

    Une arme selectionnee = un couple (figurine, index d arme) DISTINCT : deux figurines
    portant chacune un pistolet a plasma surcharge font deux jets, mais une meme arme
    declaree sur deux cibles n en fait qu un (24.02 : les instances ne se cumulent pas).
    """
    models_cache = require_key(game_state, "models_cache")
    selected = set()
    for intent in intents:
        mid = str(require_key(intent, "model_id"))
        widx = int(require_key(intent, "weapon_index"))
        model = models_cache.get(mid)  # get allowed (figurine detruite en cours de resolution)
        if model is None:
            continue
        weapons = model.get(ctx.weapons_key, [])  # get allowed (figurine sans arme de ce type)
        if not (0 <= widx < len(weapons)) or not isinstance(weapons[widx], dict):
            continue
        if weapon_has_rule(weapons[widx], "HAZARDOUS"):
            selected.add((mid, widx))
    # Primitive B (chantier 06) : HAZARDOUS conditionnel via weapon_profile_scaling_by_model_count
    # (Waaagh! Energy, WeirdBoy 'Eadbanger a 10+ figurines dans l unite).
    from engine.phase_handlers.attack_sequence import _unit_get_primitive_b_rule_args as _pB_hz
    conditional_hazardous: set = set()
    unit_by_id = require_key(game_state, "unit_by_id")
    squad_cache_hz = require_key(game_state, "squad_cache")
    _hz_args_cache: Dict[str, Optional[Dict[str, Any]]] = {}
    for intent in intents:
        mid = str(require_key(intent, "model_id"))
        widx = int(require_key(intent, "weapon_index"))
        if (mid, widx) in selected:
            continue  # deja compte comme HAZARDOUS permanent
        model = models_cache.get(mid)  # get allowed
        if model is None:
            continue
        weapons_c = model.get(ctx.weapons_key, [])  # get allowed
        if not (0 <= widx < len(weapons_c)) or not isinstance(weapons_c[widx], dict):
            continue
        squad_id_c = str(model.get("squad_id", ""))  # get allowed
        if squad_id_c not in _hz_args_cache:
            unit_c = unit_by_id.get(squad_id_c)  # get allowed
            _hz_args_cache[squad_id_c] = _pB_hz(unit_c, "weapon_profile_scaling_by_model_count") if unit_c is not None else None
        args_c = _hz_args_cache[squad_id_c]
        if args_c is None or weapons_c[widx].get("code") != args_c.get("weapon_code"):  # get allowed
            continue
        threshold_c = int(args_c.get("hazardous_threshold", 99))  # get allowed
        alive_c = squad_cache_hz.get(squad_id_c, {}).get("model_count", 0)
        if alive_c >= threshold_c:
            conditional_hazardous.add((mid, widx))
    return len(selected) + len(conditional_hazardous)


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
        # [MELTA] 24.25 : le bonus de D fait partie du PROFIL (une meme arme a demi-portee et
        # hors demi-portee ne se resout pas dans le meme lot) -> il entre dans la cle de groupe.
        # 04.03 IDENTICAL ATTACKS, encadre : « Identical attacks are those that have the same
        # BS/WS, S, AP and D characteristics, AND WHICH ARE AFFECTED BY THE SAME APPLICABLE
        # ABILITIES AND RULES. » La cle ne portait que la premiere moitie (S est represente par
        # `display_wth`, seuil de blessure contre CETTE cible). Trois armes de meme profil brut
        # mais de regles differentes — Shoota RAPID_FIRE:1, Kombi Shoota aucune, Kustom Shoota
        # RAPID_FIRE:2 — tombaient donc dans un lot unique, qui ne peut porter qu'UNE valeur de
        # `[RAPID FIRE:X]` dans le log : 898 faux « marker value mismatch » cote analyzer, et un
        # nom d'arme composite « A / B / C » qui melangeait des attaques non identiques.
        # RNG et NB n'entrent PAS dans la cle : 04.03 ne les compte pas parmi les
        # caracteristiques d'identite.
        #
        # Les X APPLIQUES des regles additives y entrent EN PLUS de la signature declaree, parce
        # que 04.03 dit « APPLICABLE abilities and rules » : deux figurines de la meme escouade
        # portant la MEME arme n'y sont pas forcement soumises pareil. La signature declaree ne
        # les separe pas ; la valeur appliquee si. Deux cas le montrent :
        #   - [RAPID FIRE] 24.30 : « within half range » — l'une est a demi-portee, l'autre non ;
        #   - [CLEAVE] 24.06 : « if you only selected one target for ALL of that weapon's
        #     attacks » — l'une repartit ses attaques sur deux cibles, l'autre non.
        # Les autres regles conditionnelles sont deja representees : [HEAVY] et [COVER] par `bs`,
        # [MELTA] par `dmg_bonus`.
        #
        # Le dict ENTIER entre dans la cle, jamais une enumeration de labels : une 4e regle
        # additive ajoutee au producteur y entrerait alors sans que rien ne leve, et deux
        # figurines de X differents fusionneraient — le token `[REGLE:X]` redevenant ambigu, en
        # silence. [BLAST] 24.05 y entre donc aussi, gratuitement : son X ne depend que de la
        # taille DECLAREE de la cible, et `target_sid` est deja dans la cle, donc il ne
        # sur-decoupe rien.
        #
        # C'est aussi ce qui rend ces X reellement constants sur le groupe — donc les tokens
        # `[REGLE:X]` du log non ambigus, et le dict de groupe posable a la creation plutot
        # qu'accumule. Lus dans `additive_rules_applied`, seul porteur du fait « cette regle
        # additive a joue, avec ce X » : un seul champ, trois lecteurs (cette cle, les tokens, et
        # `rapidFireApplied` du step.log). L'absence de cle vaut 0, et `require_key` garantit
        # qu'un producteur muet leve au lieu de valoir 0.
        _additive = require_key(r, "additive_rules_applied")
        gkey = (r["bs"], r["ap"], r["dmg_raw"], require_key(r, "dmg_bonus"),
                r["display_wth"], r["display_save_th"], require_key(r, "weapon_rules"),
                tuple(sorted(_additive.items())),
                target_sid)
        if gkey not in group_index_by_key:
            group_index_by_key[gkey] = len(weapon_groups)
            # Position de l'ancre cible CAPTURÉE ICI (cible vivante : aucune figurine n'est
            # retirée avant l'allocation) pour le log de fin de groupe. Sans ça, l'émission
            # différée relit units_cache après un éventuel retrait de l'escouade détruite et
            # tombait sur (0,0) (fallback anti-erreur supprimé).
            _tgt_uc_live = require_key(require_key(game_state, "units_cache"), target_sid)
            # JUMEAU de la capture ci-dessus, pour l ATTAQUANT : meme emission differee, donc
            # meme exigence. `_emit_squad_shoot_log` relisait units_cache et retombait sur
            # (0,0) — une case reelle du plateau — pour une escouade absente. Le squad_id est
            # requis (toute figurine du models_cache le porte) : sans lui, la cle de lecture
            # elle-meme etait devinee a partir de l id de figurine.
            _atk_sid = str(require_key(attacker, "squad_id"))
            _atk_uc_live = require_key(require_key(game_state, "units_cache"), _atk_sid)
            _grp = {
                "attacker_squad_id": _atk_sid,
                "attacker_col": int(require_key(_atk_uc_live, "col")),
                "attacker_row": int(require_key(_atk_uc_live, "row")),
                "weapon_name": weapon_name, "weapon_names": [weapon_name], "target_sid": target_sid,
                "target_col": int(require_key(_tgt_uc_live, "col")),
                "target_row": int(require_key(_tgt_uc_live, "row")),
                "bs": r["bs"], "ap": r["ap"], "dmg_raw": r["dmg_raw"],
                "dmg_bonus": require_key(r, "dmg_bonus"),
                # [PRECISION] 24.28 : porte par le PROFIL d arme du lot (l override d allocation
                # s applique lot par lot). `precision_range` = portee de l arme pour le test de
                # visibilite au tir ; None en melee (visibilite acquise au contact).
                # [HEAVY] 24.16 : affiche dans le log de tir. Propriete de l UNITE et du TOUR
                # (constante sur toute l activation), donc jamais ambigue au sein d un groupe ;
                # `bs` est de toute facon deja dans la cle de groupe.
                "heavy_applied": bool(r["heavy_applied"]) if "heavy_applied" in r else False,
                # §22.05 PLUNGING FIRE : modele attaquant en hauteur ou TOWERING — +1 BS applique.
                # Constant sur le groupe (meme figurine attaquante dans la cle via bs).
                "plunging_fire_applied": bool(r.get("plunging_fire_applied", False)),
                # Arme + regles resolues vs la cible, gardees par REFERENCE : le log construit
                # ses tokens a l emission (`weapon_rule_log_tokens`), une fois par groupe. Les
                # deux sont constants sur le groupe — la signature de regles et la cible sont
                # dans `gkey`, et le profil ne depend que de ces deux-la.
                "weapon": require_key(r, "weapon"),
                "attack_profile": require_key(r, "attack_profile"),
                # 10.06 MONSTER/VEHICLE : propriete de la FIGURINE attaquante et de la cible,
                # toutes deux figees pour l activation — constante sur le groupe comme `bs`,
                # dont elle explique justement une part.
                "point_blank_malus": bool(require_key(r, "point_blank_malus")),
                # Regles additives ayant joue ([RAPID FIRE]/[BLAST]/[CLEAVE]) -> leur X declare.
                # Constant sur le groupe par CONSTRUCTION comme tous ses voisins : les deux X qui
                # dependent de la figurine sont dans `gkey`, celui de [BLAST] ne depend que de la
                # cible, elle aussi dans `gkey`. Copie et non reference : le dict de l'intent ne
                # doit pas devenir mutable a travers le groupe.
                "additive_rules_applied": dict(_additive),
                # L13 — demi-portee verifiee independamment du bonus applique (permet de
                # detecter un [RAPID FIRE] ou [MELTA] manque quand la cible etait a demi-portee).
                # Absent du record melee (_manual_roll_fight_intent) : get avec defaut False.
                "atHalfRange": bool(r.get("at_half_range", False)),
                "precision": require_key(r, "precision"),
                "precision_range": require_key(r, "precision_range"),
                # [PRECISION] 24.28 : l arme la DECLARE (`precision`) ; savoir si elle a JOUE
                # demande d attendre l Allocation Order step, ou `_apply_precision_allocation_override`
                # pose ce drapeau s il a effectivement impose un groupe CHARACTER. Le log lit
                # celui-ci, jamais la declaration.
                "precision_applied": False,
                "display_wth": r["display_wth"], "display_save_th": r["display_save_th"],
                # Constants sur le groupe : meme attaquant, meme cible (tous deux dans `gkey`).
                "oath_hit_reroll": bool(require_key(r, "oath_hit_reroll")),
                "oath_wound_bonus": bool(require_key(r, "oath_wound_bonus")),
                # Waaagh! (08.04) : constants sur le groupe pour la MEME raison que les deux
                # drapeaux d Oath ci-dessus — le bonus de melee depend de l attaquant, la
                # sauvegarde octroyee de la cible, et les deux sont dans `gkey`.
                "waaagh_melee_bonus": bool(require_key(r, "waaagh_melee_bonus")),
                "waaagh_target_invul": bool(require_key(r, "waaagh_target_invul")),
                # Joueur proprietaire du tireur : toute figurine du models_cache le porte.
                # Le defaut `0` en faisait un log attribue au joueur 0 (et `is_ai_action`
                # calcule dessus), sans qu aucun consommateur puisse le distinguer d un vrai.
                "player": int(require_key(attacker, "player")),
                "attacks": 0, "damage": 0, "kills": 0, "killed_model_ids": [], "shots": [],
                # Figs de l escouade ayant EFFECTIVEMENT tire dans ce groupe (arme/cible). Source de
                # verite du cercle vert + cone LoS par-fig cote replay : c est le model_id resolu par
                # roll_intent_fn (attacker_mid), pas un match par nom d arme.
                "shooter_mids": [],
                # [ASSAULT] 24.04 (10.05) / [CLOSE-QUARTERS] 24.07 (10.06) : verdict du portier
                # RELU depuis l intent, comme `point_blank_malus` juste au-dessus. Il est
                # constant sur le groupe — le type de tir est une propriete de l ESCOUADE et du
                # TOUR, et l arme comme la cible sont deja dans `gkey`.
                "assault_applied": bool(require_key(r, "assault_applied")),
                "close_quarters_applied": bool(require_key(r, "close_quarters_applied")),
                "indirect_fire_fail_below": require_key(r, "indirect_fire_fail_below"),
                # Effectif de la CIBLE au Select Targets step : capturé sur le premier intent du
                # groupe (valeur constante — même cible, même activation). Loggé dans step.log via
                # [TARGET_DECL:N] pour que l'analyzer juge §1.2/§1.4 sans reconstruire cet état.
                "targetAliveCount": int(require_key(intent, "target_squad_size_at_declaration")),
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
        if attacker_mid not in g["shooter_mids"]:
            g["shooter_mids"].append(attacker_mid)

        # Blessures accumulees PAR PROFIL d arme (gidx) : chaque profil = un lot resolu
        # independamment (regle 04.03). Triees save croissant a la construction du lot.
        if gidx not in batch_pool_by_gidx:
            batch_pool_by_gidx[gidx] = []
        for pw in r["pending_wounds"]:
            batch_pool_by_gidx[gidx].append({
                "save_roll": pw["save_roll"],
                "rec": pw["rec"], "attacker_mid": attacker_mid,
                # DEVASTATING_WOUNDS : propage le flag crit-sans-save jusqu a l allocation.
                "devastating": bool(pw.get("devastating")),
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
            # stable, l ordre d attaque departage les egalites). DEVASTATING_WOUNDS (24.10) :
            # les blessures MORTELLES (crit sans save) sont infligees « after resolving any
            # normal damage » -> triees en fin de lot (cle devastating False<True) tout en
            # gardant l ordre save croissant a l interieur de chaque categorie.
            pool_sorted = sorted(pool, key=lambda pw: (bool(pw.get("devastating")), pw.get("save_roll") or 0))
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
        # [HAZARDOUS] 24.15 : « make a number of hazard rolls equal to the number of
        # [HAZARDOUS] weapons you SELECTED IN THE SELECT WEAPONS STEP ». Le compte se fait
        # donc ICI, sur les intents declares (avant qu ils ne soient purges), et sert au
        # declenchement de fin d activation (_finalize_manual_allocation).
        "hazardous_weapon_count": _count_selected_hazardous_weapons(game_state, ctx, intents),
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
    # Meme regle que le tir : position capturee AVANT destroy, mais REQUISE (elle alimente
    # `hazardDetails` du log, donc l analyse et le replay).
    col = int(require_key(m, "col"))
    row = int(require_key(m, "row"))
    # Feel No Pain (24.12) : MW = blessure sans sauvegarde, mais FNP reste applicable.
    # Inclut feel_no_pain_near_objective ; PSYCHIC non pertinent (blessures auto-infligées
    # par [HAZARDOUS] — pas des attaques ennemies).
    _fnp_unit = require_unit_by_id(game_state, str(require_key(m, "squad_id")))
    _fnp_ths = _collect_fnp_thresholds_mortal(_fnp_unit, game_state, is_psychic=False)
    if _fnp_ths and _roll_fnp_sequential(1, _fnp_ths) == 0:
        # L12 — FNP mortal wounds : journaliser la sauvegarde.
        alloc["hazard_details"].append({"modelId": str(cur), "col": col, "row": row, "died": False, "fnpSaved": True})
        batch["pool_index"] += 1
        return
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
    """Complete la ligne de log hazard DEJA emise avec ses details par-figurine.

    La ligne est publiee au JET (roll_hazard_for_unit), avant que le joueur ne choisisse ses
    pertes : `append_action_log` a mute le payload en place et l a laisse dans `action_logs`,
    donc ecrire ici dans le meme dict met a jour la ligne existante — il ne faut SURTOUT PAS
    la re-emettre (elle apparaitrait deux fois)."""
    payload = alloc["hazard_log_payload"]
    payload["hazardDetails"] = alloc["hazard_details"]


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
# SQUAD FIGHT — activation start + ordering (squad_multi_figurines.md PR3 3d)
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
        weapons = melee_weapons(m)
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


def squad_fight_restart_activation(game_state: Dict[str, Any], squad_id: str) -> None:
    """Ouvre une activation fight en ECRASANT une declaration precedente non resolue.

    Reservee aux chemins de resolution directe (clic sur une cible), qui redeclarent
    TOUTES les figurines eligibles contre cette cible : ils REMPLACENT donc ce que le
    flux manuel par-figurine avait declare, ils ne s y ajoutent pas. Sans cette
    liberation explicite, squad_fight_unit_activation_start leve
    assert_no_pending_fight_intent — la sentinelle a raison, c est l appelant qui doit
    dire qu il repart de zero. Jumeau du cancel implicite de squad_shoot_activate.
    """
    clear_pending_fight_intent(game_state, squad_id)
    squad_fight_unit_activation_start(game_state, squad_id)


# ============================================================================
# SQUAD FIGHT — Pile In + éligibilité par figurine (04.02)
# ============================================================================


def model_in_base_contact(
    game_state: Dict[str, Any], model_id: str, model_entry: Dict[str, Any]
) -> bool:
    """True si la figurine est en base-contact (socles collés) avec >= 1 figurine ennemie.

    Règle 12.03 / 12.08 WHILE MOVING : « Models in base-contact with one or more enemy models
    cannot be moved. » SOURCE UNIQUE du PvP et du gym : le pile-in du gym gardait sa propre
    géométrie (centre-à-centre, `== BASE_TO_BASE_SUBHEX`), donc deux verdicts opposés sur la
    même règle selon le chemin.

    LE SEUIL DE CONTACT DÉPEND DE LA MÉTRIQUE, et c'est la règle, pas un contournement :
    - `euclidean` (x5, x10) : les socles occupent plusieurs cases, « bord à bord » a un sens
      continu -> contact = écart <= 0, donc zone d'engagement **0** ;
    - `hex` (x1, cf. `geometry_is_hex`) : une figurine tient dans UNE case et `_scale_socle`
      normalise tous les socles en `round`/1. Deux socles se touchent donc quand leurs cases sont
      ADJACENTES -> zone d'engagement **`BASE_TO_BASE_SUBHEX`** (1).

    Un seuil unique ne peut pas servir les deux. Mesuré : à x1, deux `round`/1 adjacents ont un
    écart euclidien de 0,2321 et une distance d'empreinte de 1 — « zone 0 » y répond donc
    TOUJOURS non, et la règle 12.03 ne s'appliquerait plus du tout sur le plateau
    d'entraînement. Symétriquement, en euclidien la zone 1 vaut 1,5 unité, bien au-delà du
    contact.

    Le reste passe par la primitive : géométrie horizontale ET gate vertical §03.04 (appliqué dès
    que les deux entrées portent leurs cartes verticales), sans une ligne de géométrie ici.
    """
    from engine.spatial_relations import (
        engagement_distance_metric, unit_entries_within_engagement_zone,
    )

    units_cache = require_key(game_state, "units_cache")
    squad_id = str(require_key(model_entry, "squad_id"))
    player = int(require_key(model_entry, "player"))
    metric = engagement_distance_metric(game_state)
    contact_zone = BASE_TO_BASE_SUBHEX if metric == "hex" else 0

    subject = _synth_model_entry(
        game_state, squad_id, model_entry,
        int(model_entry["col"]), int(model_entry["row"]),
        level=int(require_key(model_entry, "level")),
    )
    # Hauteur COMMITTÉE, pas re-résolue. `_synth_model_entry` passe par
    # `resolved_floor_height_at`, dont le critère (empreinte ENTIÈREMENT sur le plancher) est plus
    # STRICT que celui de la pose — cf. `_recompute_squad_occupied_hexes`, « le niveau STOCKÉ fait
    # foi : ce resync recopie l'état, il ne le rejuge pas ». Une figurine committée à l'étage avec
    # un socle qui déborde serait donc mesurée au SOL et manquerait le contact d'un ennemi de son
    # propre étage. Pour une figurine DÉJÀ POSÉE, la carte du cache est la vérité.
    squad_entry = units_cache.get(str(squad_id))  # get allowed (escouade retirée = morte)
    _committed = (squad_entry or {}).get("floor_height_by_model")  # get allowed (entrées 2D)
    if _committed is not None and str(model_id) in _committed:
        subject["floor_height_by_model"] = {
            key: float(_committed[str(model_id)]) for key in subject["floor_height_by_model"]
        }

    for _enemy_id, enemy_entry in enemy_entries_on_battlefield(
        units_cache, player, exclude_id=squad_id
    ):
        if unit_entries_within_engagement_zone(
            subject, enemy_entry, contact_zone, metric=metric
        ):
            return True
    return False

def _assign_cells_toward_enemies(
    game_state: Dict[str, Any],
    squad_id: str,
    mids: List[str],
    enemy_positions: List[Tuple[int, int]],
    budget: int,
) -> Dict[str, Tuple[int, int]]:
    """Affectation figurine -> cellule pour un move vers l'ennemi (pile-in 12.03 / conso 12.08).

    SOURCE UNIQUE des deux : les deux regles portent la MEME obligation — « Models in
    base-contact with one or more enemy models cannot be moved » et « Each model that is moved
    must end its move closer to the closest [target], and **engaged with it if possible** »
    (12.03 WHILE MOVING ; 12.08 WHILE MOVING, modes Ongoing et Engaging). Dupliquer
    l'algorithme rouvrirait la classe de bug §0.18, qui existait deja en double exemplaire.

    L'immobilite des figurines au contact est appliquee inconditionnellement : elle est **sans
    objet** en mode Engaging (unite non engagee => aucune figurine au contact), donc correcte
    dans les deux cas sans avoir a connaitre le mode.

    Retour : {model_id: (col, row)} pour TOUTES les figurines de ``mids``. Aucune ecriture.
    """
    models_cache = require_key(game_state, "models_cache")
    # `require_key` et non un `.get(..., {})` : la fonction indexe `units_cache[str(squad_id)]`
    # plus bas, donc une absence lève de toute façon — mais elle aurait d'abord vidé l'union de
    # collision ci-dessous, rendant TOUTE cellule libre le temps du calcul.
    units_cache = require_key(game_state, "units_cache")
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())
    pile_in_budget = int(budget)

    origins: Dict[str, Tuple[int, int]] = {
        mid: (int(models_cache[mid]["col"]), int(models_cache[mid]["row"])) for mid in mids
    }

    # JUMEAU de `charge_build_valid_plan` : union des empreintes des AUTRES escouades, résolue une
    # fois. `_cell_base_legal` est appelée par cellule dans les deux balayages ci-dessous et le
    # cache n'est pas muté entre-temps (« Aucune ecriture », cf. docstring) ; la réénumérer par
    # cellule reconstruisait l'empreinte de chaque escouade du plateau pour dire « occupée ? ».
    occupied_by_others = build_occupied_positions_set(game_state, exclude_unit_id=str(squad_id))

    def _cell_base_legal(col: int, row: int) -> bool:
        """Legalite INDEPENDANTE du plan : plateau, murs, autres escouades."""
        if col < 0 or row < 0 or col >= board_cols or row >= board_rows:
            return False
        cell = (col, row)
        if wall_hexes and cell in wall_hexes:
            return False
        return cell not in occupied_by_others

    # 1. 12.03 WHILE MOVING : « Models in base-contact with one or more enemy models cannot be
    #    moved ». Ces figurines restent, et leur cellule est definitivement occupee.
    #    MEME predicat que le PvP (`model_in_base_contact`) : il mesurait ici centre-a-centre
    #    (`== BASE_TO_BASE_SUBHEX`, 1 case) alors que le contact se mesure BORD a bord. Mesure :
    #    deux socles au contact ont leurs centres a 2 subhex (BASE_SIZE 3) ou 4 (BASE_SIZE 6) —
    #    `== 1` etait donc IMPOSSIBLE des qu'un socle depasse une case, et `immobile` restait
    #    toujours vide sur le chemin gym. La regle ne s'y appliquait jamais, alors que le PvP
    #    figeait bien la figurine : deux verdicts opposes sur la meme regle.
    immobile = [mid for mid in mids if model_in_base_contact(game_state, mid, models_cache[mid])]
    movers = [mid for mid in mids if mid not in set(immobile)]
    static_cells = {origins[mid] for mid in immobile}

    # 12.03 / 12.08 EFFECT « Your unit moves as described in Moving (03) » : meme borne de TRAJET
    # que le move et la charge. Sans elle, une consolidation « de 3 pouces » traversait une
    # figurine ennemie ou un mur — 28 occurrences mesurees sur un run de 600 episodes.
    # Construit pour les SEULES figurines qui l'interrogent : 12.03 WHILE MOVING immobilise celles
    # deja au contact, et c'est le cas NORMAL d'un pile-in. En metrique euclidienne chaque predicat
    # coute un champ any-angle.
    _pile_player = int(require_key(units_cache[str(squad_id)], "player"))
    _reach_by_mid: Dict[str, Callable[[int, int], bool]] = {
        mid: model_reach_predicate(
            game_state, str(squad_id), _pile_player, models_cache[mid], pile_in_budget,
            int(require_key(models_cache[mid], "level")),
        )
        for mid in movers
    }

    # 2. Cellules bord-a-bord atteignables (legalite hors-plan uniquement).
    b2b_cells: Set[Tuple[int, int]] = set()
    for ec, er in enemy_positions:
        for nc, nr in get_hex_neighbors(ec, er):
            if _cell_base_legal(nc, nr):
                b2b_cells.add((nc, nr))

    # 3. Couplage maximum figurine -> cellule B2B (12.03 « engaged with it if possible » +
    #    « maximise the number of models that are engaged »). Une cellule qui est l'origine
    #    d'une camarade n'est utilisable QUE si cette camarade la quitte : on part du cas le
    #    plus contraint (aucune origine disponible) et on libere, par point fixe, les origines
    #    des figurines dont le couplage confirme le depart. `blocked` decroit strictement a
    #    chaque tour -> convergence ; et a chaque iteration le resultat est deja sans collision.
    blocked: Set[Tuple[int, int]] = {origins[mid] for mid in mids}
    matching: Dict[str, Tuple[int, int]] = {}
    while True:
        candidates = {
            mid: sorted(
                cell for cell in b2b_cells
                if cell not in blocked and _reach_by_mid[mid](cell[0], cell[1])
            )
            for mid in movers
        }
        matching = _max_b2b_matching(candidates)
        freed = {origins[mid] for mid in matching}
        if not freed - static_cells or blocked - freed == blocked:
            break
        blocked = (blocked - freed) | static_cells

    # 4. Assemblage. Les origines des figurines NON couplees restent occupees : le pile-in est
    #    optionnel (encart 12 : « you don't have to pile in »), elles peuvent rester sur place.
    chosen: Dict[str, Tuple[int, int]] = {mid: origins[mid] for mid in immobile}
    chosen.update(matching)
    taken: Set[Tuple[int, int]] = set(static_cells) | set(matching.values())
    unmatched = [mid for mid in movers if mid not in matching]
    taken |= {origins[mid] for mid in unmatched}

    for mid in unmatched:
        oc, orow = origins[mid]
        # (b) A defaut de B2B : finir strictement plus proche du plus proche ennemi.
        nearest = min(
            enemy_positions,
            key=lambda ep: calculate_hex_distance(oc, orow, ep[0], ep[1]),
        )
        tc, tr = nearest
        orig_dist = calculate_hex_distance(oc, orow, tc, tr)
        best: Optional[Tuple[int, int, int]] = None  # (dist_to_target, col, row)
        for d in range(1, pile_in_budget + 1):
            for d_col in range(-d, d + 1):
                for d_row in range(-d, d + 1):
                    if max(abs(d_col), abs(d_row)) != d:
                        continue
                    nc, nr = oc + d_col, orow + d_row
                    if not _cell_base_legal(nc, nr) or (nc, nr) in taken:
                        continue
                    if not _reach_by_mid[mid](nc, nr):
                        continue
                    cand_d = calculate_hex_distance(nc, nr, tc, tr)
                    if cand_d >= orig_dist:
                        continue
                    if best is None or cand_d < best[0]:
                        best = (cand_d, nc, nr)
            if best is not None:
                break
        if best is None:
            chosen[mid] = (oc, orow)  # reste sur place : sa cellule est deja dans `taken`
        else:
            taken.discard((oc, orow))  # elle part : son origine redevient libre
            chosen[mid] = (best[1], best[2])
            taken.add(chosen[mid])

    return chosen


def _max_b2b_matching(
    candidates: Dict[str, List[Tuple[int, int]]]
) -> Dict[str, Tuple[int, int]]:
    """Couplage maximum figurine -> cellule bord-a-bord (algorithme de Kuhn).

    12.03 WHILE MOVING impose « engaged with it **if possible** » a chaque figurine deplacee,
    et l'encart du meme PDF donne l'intention : « units will pile in to **maximise** the number
    of models that are engaged ». Un parcours glouton dans l'ordre des index ne maximise pas :
    la 1re figurine prend la cellule dont la 2e avait un besoin exclusif. Le couplage maximum
    est la formulation exacte de cette obligation, et il est **independant de l'ordre**.

    ``candidates`` : {model_id: [cellules B2B legales et atteignables]}.
    Retour : {model_id: cellule} pour les figurines couplees (les autres n'ont pas de B2B
    possible dans ce couplage maximum).
    """
    match_cell: Dict[Tuple[int, int], str] = {}

    def _augment(mid: str, visited: Set[Tuple[int, int]]) -> bool:
        for cell in candidates[mid]:
            if cell in visited:
                continue
            visited.add(cell)
            holder = match_cell.get(cell)
            if holder is None or _augment(holder, visited):
                match_cell[cell] = mid
                return True
        return False

    for mid in candidates:
        _augment(mid, set())
    return {mid: cell for cell, mid in match_cell.items()}


def fight_pile_in_plan(
    game_state: Dict[str, Any], squad_id: str
) -> Optional[List[Tuple[str, int, int, int]]]:
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

    # ⚠️ NE PAS justifier ce `require` par « `mids` non vide donc l'escouade est dans le cache » :
    # c'est FAUX. `update_units_cache_hp` retire une escouade dont les PV tombent à 0 SANS purger
    # `models_cache` (asymétrie déjà documentée dans `_recompute_squad_occupied_hexes`), donc
    # `mids` peut être non vide sur une escouade absente du cache.
    # Le vrai contrat est chez l'APPELANT : `_gym_commit_fight_move` passe des ids issus de
    # `fight_v11_grouped_next` → `_fight_v11_grouped_step_eligible`, qui filtre sur
    # `is_unit_alive` (= présence dans `units_cache`). Un `return None` répondait « pas de pile-in
    # possible » — un refus de règle — à une désynchronisation ; et `player=-1` faisait de TOUTES
    # les escouades des ennemies.
    our_entry = require_unit_from_cache(squad_id, game_state, "fight_pile_in_plan")

    # 12.03 BEFORE MOVING : cibles imposées si engagée (tous les ennemis engagés avec l'unité),
    # heuristique gym si non engagée (tous les ennemis à ≤ pile_in_target_range).
    from engine.phase_handlers.fight_handlers import (
        _fight_units_engaged_with,
        pile_in_targets_within_range,
    )
    # `player` requis par `unit_within_engagement_zone_footprints` (via `_fight_v11_engaged_now`).
    unit_ref: Dict[str, Any] = {"id": squad_id, "player": int(require_key(our_entry, "player"))}
    # 12.03 : engagée → cibles = unités engagées (pile_in_targets_within_range inutile) ;
    # non engagée → cibles = unités à ≤ pile_in_target_range.  Deux appels distincts évitent
    # le double pile_in_targets_within_range (engagé : appel gaspillé ; non engagé : double scan).
    engaged = _fight_units_engaged_with(game_state, unit_ref)
    if engaged:
        target_ids: List[str] = engaged
    else:
        within_ids = pile_in_targets_within_range(game_state, unit_ref)
        if not within_ids:
            return None
        target_ids = within_ids
    enemy_positions: List[Tuple[int, int]] = []
    for esid in target_ids:
        enemy_positions.extend(_squad_model_positions(game_state, esid))
    if not enemy_positions:
        return None

    ish = int(require_key(game_state, "inches_to_subhex"))
    pile_in_budget = 3 * ish  # 3" en subhexes
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())

    chosen = _assign_cells_toward_enemies(
        game_state, squad_id, mids, enemy_positions, pile_in_budget
    )
    # `_assign_cells_toward_enemies` est HORIZONTAL : chaque fig reste à son étage, que le plan
    # PORTE (toute entrée de plan porte le sien).
    plan: List[Tuple[str, int, int, int]] = [
        (mid, chosen[mid][0], chosen[mid][1], int(require_key(models_cache[mid], "level")))
        for mid in mids
    ]

    # Validation finale
    plan_positions = {mid: (c, r) for mid, c, r, _lv in plan}
    if not _validate_plan_coherency(plan_positions, game_state):
        return None
    # Au moins une figurine doit finir dans l ER (bord-a-bord) d une unite ennemie.
    from engine.spatial_relations import unit_entries_within_engagement_zone
    ez = get_engagement_zone(game_state)
    # ER contre les cibles 12.03 uniquement : un enemi hors cibles ne valide pas le pile-in.
    enemy_entries = [
        require_unit_from_cache(esid, game_state, "fight_pile_in_plan/enemy")
        for esid in target_ids
    ]
    in_er = False
    for mid, c, r, _lv in plan:
        synth = _synth_model_entry(game_state, str(squad_id), models_cache[mid], c, r, level=_lv)
        if any(
            unit_entries_within_engagement_zone(synth, ee, ez, game_state=game_state)
            for ee in enemy_entries
        ):
            in_er = True
            break
    if not in_er:
        return None
    return plan


def _fight_overrun_pile_in_plan(
    game_state: Dict[str, Any], squad_id: str
) -> Optional[List[Tuple[str, int, int, int]]]:
    """Plan pile-in additionnel overrun 12.06 (par-figurine, atomique).

    Variante de fight_pile_in_plan pour les unités NON engagées au moment de leur
    sélection : les cibles sont restreintes aux ennemis à ≤ pile_in_target_range (5")
    conformément à 12.03 BEFORE MOVING (cas non engagé). L'unité DOIT finir engagée.

    Returns List[(model_id, col, row, level)] ou None.
    """
    from engine.phase_handlers.fight_handlers import pile_in_targets_within_range
    from engine.game_utils import get_unit_by_id

    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    mids = [m for m in squad_models.get(squad_id, []) if m in models_cache]  # get allowed
    if not mids:
        return None

    our_unit = require_unit_by_id(game_state, squad_id)

    # Cibles restreintes à ≤ 5" (12.03 BEFORE MOVING, unité non engagée).
    within_ids = pile_in_targets_within_range(game_state, our_unit)
    if not within_ids:
        return None

    enemy_positions: List[Tuple[int, int]] = []
    for esid in within_ids:
        enemy_positions.extend(_squad_model_positions(game_state, esid))
    if not enemy_positions:
        return None

    ish = int(require_key(game_state, "inches_to_subhex"))
    chosen = _assign_cells_toward_enemies(
        game_state, squad_id, mids, enemy_positions, 3 * ish
    )
    plan: List[Tuple[str, int, int, int]] = [
        (mid, chosen[mid][0], chosen[mid][1], int(require_key(models_cache[mid], "level")))
        for mid in mids
    ]

    plan_positions = {mid: (c, r) for mid, c, r, _lv in plan}
    if not _validate_plan_coherency(plan_positions, game_state):
        return None
    from engine.spatial_relations import unit_entries_within_engagement_zone
    ez = get_engagement_zone(game_state)
    within_entries = [
        require_unit_from_cache(esid, game_state, "_fight_overrun_pile_in_plan/enemy")
        for esid in within_ids
    ]
    in_er = any(
        any(
            unit_entries_within_engagement_zone(
                _synth_model_entry(game_state, str(squad_id), models_cache[mid], c, r, level=lv),
                ee, ez, game_state=game_state,
            )
            for ee in within_entries
        )
        for mid, c, r, lv in plan
    )
    if not in_er:
        return None
    return plan


def get_fighting_models(
    game_state: Dict[str, Any],
    squad_id: str,
    target_squad_id: Optional[str] = None,
) -> List[str]:
    """Retourne les model_ids d'une escouade autorisés à frapper en mêlée.

    Règle 04.02 SELECT TARGETS, WHILE FIGHTING : « Each target must be **engaged with the model
    that has that weapon**. » Et 03.04 ENGAGEMENT définit « engagé » : à ≤ 2" horizontalement ET
    ≤ 5" verticalement d'une figurine ennemie. Une figurine engagée frappe, une autre non — il n'y
    a pas d'autre condition.

    ``target_squad_id`` PORTE LA MOITIÉ « with the model » DE 04.02, et n'est pas un confort :
    - **fourni** → l'engagement est testé contre CETTE escouade seule. C'est ce que la déclaration
      de combat exige : une escouade coincée entre deux ennemis A et B qui déclare B ne doit pas
      faire frapper B par ses figurines qui ne touchent que A. Sans ce paramètre, la liste était
      « engagée avec n'importe qui » et le chemin gym accordait des attaques que le jumeau PvP
      (``fight_handlers._model_can_fight_target``, cible-conscient) refuse.
    - **None** → engagement contre n'importe quelle escouade ennemie. Sémantique DIFFÉRENTE et
      légitime : c'est celle de l'observation (`fight_eligible` / `n_fight_eligible`, « cette
      figurine est-elle au combat ? »), qui se calcule avant tout choix de cible. Le compte
      par-cible y existe séparément (`n_models_engaging`, par entité ennemie).

    LA CLAUSE « BUDDY » A ÉTÉ SUPPRIMÉE (2026-08-04). Elle accordait le droit de frapper à une
    figurine NON engagée mais au contact d'une alliée de son escouade qui, elle, touchait un
    ennemi (relais d'un cran, non transitif). Elle venait d'une édition antérieure de 40K, pas de
    ce corpus : `base-contact` n'apparaît dans les 25 PDF que dans la phase de combat, et
    uniquement pour dire qu'une figurine au contact NE BOUGE PAS au pile-in (12.03 / 12.08 WHILE
    MOVING). Aucun texte n'accorde de relais d'attaque.

    Elle était en prime mesurée dans une autre géométrie que la condition d'engagement : distance
    de CENTRE à centre en cases (`== BASE_TO_BASE_SUBHEX`, soit 1 case) là où l'engagement se
    mesure BORD à bord par la primitive. À x5 cette case vaut 0,2" — moins qu'un socle — donc la
    clause ne pouvait se déclencher que sur des positions physiquement impossibles.

    Ordre de retour : par index de figurine (déterministe).
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    mids = [m for m in squad_models.get(squad_id, []) if m in models_cache]  # get allowed
    if not mids:
        return []
    # Contrat chez l'APPELANT, pas dans `mids` (cf. `fight_pile_in_plan`) : l'unique appelant
    # (`observation_builder`, encodage de l'escouade active) ne passe ici qu'un `active_squad_id`
    # dont il a déjà lu l'entrée-cache pour tester `on_battlefield`.
    # `player=-1` en aurait fait un camp inexistant, donc TOUTES les escouades ennemies, donc une
    # liste de combattants calculée sur la mauvaise géométrie — et `enemy_sids` aurait ensuite
    # fait lever le contrôle de cible désignée.
    our_player = int(require_key(
        require_unit_from_cache(squad_id, game_state, "get_fighting_models"), "player"
    ))
    from engine.spatial_relations import unit_entries_within_engagement_zone
    ez = get_engagement_zone(game_state)
    enemy_sids: List[str] = list(_enemy_squad_ids(game_state, our_player))
    if target_squad_id is not None:
        # Cible désignée : elle DOIT être ennemie. Une cible amie ou inconnue est une erreur
        # d'appelant, pas une liste vide à interpréter comme « personne ne peut frapper ».
        if str(target_squad_id) not in enemy_sids:
            raise ValueError(
                f"get_fighting_models: target_squad_id {target_squad_id!r} n'est pas une escouade "
                f"ennemie de {squad_id!r} (joueur {our_player})"
            )
        enemy_sids = [str(target_squad_id)]
    # `enemy_sids` sort de `_enemy_squad_ids` (ou d'une cible déjà validée ennemie juste au-dessus) :
    # ils sont tous dans le cache. Le filtre était mort et aurait vidé la liste des combattants.
    enemy_entries = [
        require_unit_from_cache(esid, game_state, "get_fighting_models/enemy")
        for esid in enemy_sids
    ]
    if not enemy_entries:
        return []

    # Le gate vertical §03.04 n'est pas demandé : la primitive l'applique dès que les deux
    # entrées portent leurs cartes verticales (cf. `entries_in_engagement_zone`).
    out: List[str] = []
    for mid in mids:
        m = models_cache[mid]
        synth = _synth_model_entry(
            game_state, str(squad_id), m, int(m["col"]), int(m["row"]),
            level=int(require_key(m, "level")),
        )
        if any(unit_entries_within_engagement_zone(synth, ee, ez, game_state=game_state) for ee in enemy_entries):
            out.append(mid)
    return out

# ============================================================================
# SQUAD FIGHT — declaration + resolution + consolidation (squad_multi_figurines.md PR3 3f)
# ============================================================================


def _extra_attacks_weapon_indices(attacker: Dict[str, Any]) -> List[int]:
    """Indices des armes de melee [EXTRA ATTACKS] 24.11 de la figurine (ordre stable)."""
    weapons = melee_weapons(attacker)
    return [
        idx for idx, w in enumerate(weapons)
        if isinstance(w, dict) and weapon_has_rule(w, "EXTRA_ATTACKS")
    ]


def _select_fight_weapon_indices_for_fig(
    attacker: Dict[str, Any], target_t: int, target_sv: int, target_invul: int,
    target_unit: Optional[Dict[str, Any]] = None,
    *,
    melee_bonus: int = 0,
    hit_bonus: int = 0,
    hit_malus: int = 0,
    cap: int = 0,
    attacker_unit: Optional[Dict[str, Any]] = None,
    game_state: Optional[Dict[str, Any]] = None,
    finest_hour_active: bool = False,
) -> List[int]:
    """Armes de melee SELECTIONNEES par une figurine (Select Weapons step, 04.01).

    [EXTRA ATTACKS] 24.11 : « for each of those models, you must select ALL of that model's
    [EXTRA ATTACKS] weapons, AND one of that model's other melee weapons, if possible. »
    -> la figurine attaque avec toutes ses armes EXTRA ATTACKS EN PLUS de sa meilleure autre
    arme. Sans arme [EXTRA ATTACKS], on retrouve exactement le comportement anterieur : une
    seule arme, choisie par esperance de degats.

    Retourne les indices dans l ordre : arme principale d abord (elle porte
    `selectedCcWeaponIndex`), puis les armes EXTRA ATTACKS. Liste vide si la figurine n a
    aucune arme de melee.
    """
    weapons = melee_weapons(attacker)
    if not weapons:
        return []
    extra = _extra_attacks_weapon_indices(attacker)
    # « one of that model's OTHER melee weapons » : le choix principal exclut les armes
    # EXTRA ATTACKS (elles sont deja toutes selectionnees).
    main = _auto_select_cc_weapon_for_fig(
        attacker, target_t, target_sv, target_invul, target_unit,
        excluded_indices=frozenset(extra),
        melee_bonus=melee_bonus, hit_bonus=hit_bonus, hit_malus=hit_malus, cap=cap,
        attacker_unit=attacker_unit, game_state=game_state,
        finest_hour_active=finest_hour_active,
    )
    # « if possible » : une figurine qui n a QUE des armes EXTRA ATTACKS n en ajoute pas d autre.
    return ([main] if main is not None else []) + extra


def _auto_select_cc_weapon_for_fig(
    attacker: Dict[str, Any], target_t: int, target_sv: int, target_invul: int,
    target_unit: Optional[Dict[str, Any]] = None,
    excluded_indices: frozenset = frozenset(),
    *,
    melee_bonus: int = 0,
    hit_bonus: int = 0,
    hit_malus: int = 0,
    cap: int = 0,
    attacker_unit: Optional[Dict[str, Any]] = None,
    game_state: Optional[Dict[str, Any]] = None,
    finest_hour_active: bool = False,
) -> Optional[int]:
    """Choisit l arme de melee maximisant l esperance de degats, REGLES D ARME COMPRISES.

    ⚠️ Cette heuristique avait ete rendue FAUSSE par P1 (2026-07-26) : elle notait les armes sur
    leurs seules caracteristiques brutes, donc ignorait [ANTI-X], [DEVASTATING WOUNDS],
    [SUSTAINED HITS], [LETHAL HITS] et [TWIN-LINKED] — toutes vives dans le moteur. Une arme
    [ANTI-INFANTRY 1+] n etait jamais preferee contre de l infanterie. Elle passe desormais par
    `attack_sequence.expected_damage_per_attack`, c est-a-dire par le MEME modele que la boucle
    de resolution : une seule definition de l esperance de degats, aucune divergence possible.

    `target_unit` fournit les KEYWORDS de la cible, sans lesquels [ANTI-X] est ininterpretable
    (24.03, union 19.03). `excluded_indices` : armes hors du choix (cf. [EXTRA ATTACKS] 24.11,
    deja selectionnees). Tie-break : index d arme le plus bas. None si aucune arme.
    """
    from engine.phase_handlers.attack_sequence import (
        build_weapon_attack_profile,
        expected_damage_per_attack,
    )

    weapons = melee_weapons(attacker)
    if not weapons:
        return None
    best_idx: Optional[int] = None
    best_score = -1.0
    for idx, w in enumerate(weapons):
        if not isinstance(w, dict) or idx in excluded_indices:
            continue
        # Caracteristiques de l arme de melee : `ATK` (convention projet pour la CC), `STR`,
        # `AP` sont portes par les 185 profils de melee des rosters. Les orthographes `WS`/`S`
        # n existent nulle part dans la donnee, et les defauts 4/4/0 etaient des valeurs de jeu
        # plausibles : une arme mal formee marquait un score credible au lieu de lever.
        ws = int(require_key(w, "ATK"))
        # `melee_bonus` = +1 S / +1 A du Waaagh! (0 hors Waaagh!). Applique aux MEMES
        # caracteristiques que la resolution (`_manual_roll_fight_intent`) : Force et nombre
        # d attaques.
        #
        # `ATK` est le seuil de touche dans la convention du projet, et il BOUGE depuis la
        # Primitive A (chantier 06) : Might Is Right l abaisse, la suppression le degrade, avec
        # un clamp 2..6 qui rapproche deux armes de seuils voisins. Le score doit donc porter le
        # seuil que le moteur APPLIQUERA — meme raison que le `melee_bonus` ci-dessus, et meme
        # clamp que la resolution (`apply_hit_roll_modifiers`), jamais une copie.
        s = int(require_key(w, "STR")) + int(melee_bonus)
        ap = int(require_key(w, "AP"))
        # Aucun repli silencieux : une valeur de DMG non resoluble est une donnee d arme
        # invalide, elle doit lever (l ancien try/except la remplacait par 1.0 en silence).
        dmg = float(expected_dice_value(require_key(w, "DMG"), "auto_select_cc_dmg"))
        n_attacks = float(expected_dice_value(require_key(w, "NB"), "auto_select_cc_nb")) + int(melee_bonus)
        profile = build_weapon_attack_profile(
            w, target_unit, attacker_unit=attacker_unit, game_state=game_state, is_melee=True,
            finest_hour_active=finest_hour_active,
        )
        score = n_attacks * expected_damage_per_attack(
            profile,
            hit_target=apply_hit_roll_modifiers(ws, hit_bonus, hit_malus, cap=cap),
            wound_target=wound_threshold(s, target_t),
            save_threshold_value=save_threshold(target_sv, target_invul, ap),
            damage=dmg,
        )
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

    Eligibilite per fig = `get_fighting_models(..., target_squad_id)` : 04.02 exige que la cible
    soit engagee avec LA FIGURINE qui porte l arme, pas avec l escouade. Une escouade coincee
    entre deux ennemis ne fait donc pas frapper la cible declaree par ses figurines qui ne
    touchent que l autre.

    Returns la liste d intents (aussi stockee dans pending_squad_fight_intents).
    """
    from engine.phase_handlers.attack_sequence import _unit_get_primitive_b_rule_args
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
    # Caracteristiques defensives de la cible, lues sur une figurine REELLE du models_cache :
    # les 179 datasheets portent T / ARMOR_SAVE / INVUL_SAVE. Les defauts 4/7/7 decrivaient
    # une figurine moyenne sans sauvegarde — plausible, donc invisible en cas de donnee absente.
    from engine.game_state import effective_invul_save, waaagh_melee_bonus  # cycle : cf. plus haut

    target_unit_for_select = require_unit_by_id(game_state, str(target_squad_id))
    target_t = int(require_key(t_sample, "T"))
    target_sv = int(require_key(t_sample, "ARMOR_SAVE"))
    # Waaagh! de la CIBLE : elle peut avoir une invulnerable 5+ absente de sa datasheet. Le
    # choix d arme se fait donc contre la sauvegarde REELLE — sinon l heuristique prefererait
    # une arme a forte penetration contre une invulnerable que l AP n entame pas.
    target_invul = int(require_key(t_sample, "INVUL_SAVE"))
    target_invul = effective_invul_save(game_state, target_unit_for_select, target_invul)
    # Waaagh! de l ATTAQUANT : +1 S et +1 A sur TOUTES ses armes de melee. Le bonus entre dans le
    # SCORE, pas seulement dans la resolution : `expected_damage_per_attack` doit modeliser
    # l arme telle qu elle sera jouee, sinon le choix d arme est fait sur des caracteristiques
    # que le moteur n appliquera pas (§9.2.3 : une seule definition de l esperance de degats).
    attacker_unit_for_select = require_unit_by_id(game_state, str(attacker_squad_id))
    melee_bonus = waaagh_melee_bonus(game_state, attacker_unit_for_select)
    # Primitive A cote touche : MEMES termes que la resolution, resolus UNE fois pour toute
    # l escouade (ils sont constants sur l activation) et appliques par arme dans le score.
    _hit_bonus, _hit_malus, _, _ = hit_roll_modifier_terms(
        game_state, attacker_unit_for_select, is_melee=True
    )
    _hit_cap = _bonus_malus_cap(game_state)

    fighting = get_fighting_models(game_state, attacker_squad_id, target_squad_id)
    intents: List[Dict[str, Any]] = game_state["pending_squad_fight_intents"][attacker_squad_id]
    _attacker_sq_id_str = str(attacker_squad_id)
    # Lookup squad-level : constant sur toute la boucle, calculé une seule fois.
    _sq_fh_available = (
        _attacker_sq_id_str not in game_state.get("finest_hour_used", set())
        or _attacker_sq_id_str in game_state.get("finest_hour_active_this_phase", set())
    )
    for mid in fighting:
        m = models_cache.get(mid)
        if m is None:
            continue
        # once_per_battle_melee_buff : si l'abilité n'a pas encore été consommée cette partie
        # (pas dans finest_hour_used) OU est déjà active cette phase (finest_hour_active_this_phase),
        # le scoring arme doit inclure DEVASTATING WOUNDS — identique au chemin de résolution.
        _fig_finest_hour_active = (
            _unit_get_primitive_b_rule_args(m, "once_per_battle_melee_buff") is not None
            and _sq_fh_available
        )
        # Select Weapons step (04.01) : arme principale + TOUTES les armes [EXTRA ATTACKS]
        # (24.11). Un intent par arme selectionnee -> une figurine peut produire 2 intents.
        selected_indices = _select_fight_weapon_indices_for_fig(
            m, target_t, target_sv, target_invul, target_unit_for_select,
            melee_bonus=melee_bonus, hit_bonus=_hit_bonus, hit_malus=_hit_malus, cap=_hit_cap,
            attacker_unit=attacker_unit_for_select, game_state=game_state,
            finest_hour_active=_fig_finest_hour_active,
        )
        if not selected_indices:
            continue
        m["selectedCcWeaponIndex"] = selected_indices[0]
        weapons = melee_weapons(m)
        total_attacks = 0
        for chosen_idx in selected_indices:
            # F3 fix (audit) : resoudre NB UNE SEULE FOIS, stocker dans intent.
            n_attacks_resolved = 0
            if 0 <= chosen_idx < len(weapons):
                w = weapons[chosen_idx]
                if isinstance(w, dict) and "NB" in w:
                    # Aucun repli silencieux : une valeur de NB non resoluble est une donnee
                    # d arme invalide, elle doit lever (l ancien try/except la remplacait par 1).
                    n_attacks_resolved = int(
                        resolve_dice_value(w["NB"], f"squad_declare_fight_NB_{mid}")
                    )
            total_attacks += n_attacks_resolved
            intents.append({
                "model_id": mid,
                "weapon_index": chosen_idx,
                "target_unit_id": target_squad_id,
                "n_attacks_resolved": n_attacks_resolved,
                # Taille de la cible au Select Targets step — exigee par [CLEAVE] 24.06 (des
                # additionnels par tranche de 5 figurines), jumeau melee de [BLAST] 24.05.
                # Meme cle que les declarations de tir et que le chemin PvP par arme.
                "target_squad_size_at_declaration": len(target_alive),
            })
        # ATTACK_LEFT = total des attaques declarees par la figurine (l allocation le decremente
        # intent par intent : avec [EXTRA ATTACKS] il en faut la somme, sinon il tombe a 0 avant
        # d avoir resolu la seconde arme).
        if total_attacks > 0:
            m["ATTACK_LEFT"] = total_attacks
    return intents


def squad_consolidate_plan(
    game_state: Dict[str, Any], squad_id: str
) -> Optional[List[Tuple[str, int, int, int]]]:
    """Plan Consolidation (12.08, 3" max par fig) — cascade obligatoire ongoing→engaging→objective.

    Regle officielle (PDF 12.08) — mode impose par la situation, pas choisi :
      (1) Ongoing  : l unite est engagee → chaque fig se deplace vers les ennemis engages.
      (2) Engaging : 1+ ennemi a ≤ consolidation_trigger_range (3") → vers ces ennemis.
      (3) Objective: 1+ objectif a ≤3" → chaque fig vers la zone de cet objectif.
      (4) None     : aucune branche → pas de Consolidation.

    Validations finales (coherency toujours ; ER pour (1)/(2) ; zone pour (3)).
    Retourne plan ou None si impossible. Atomic.
    """
    from engine.phase_handlers.fight_handlers import (
        fight_v11_consolidation_mode,
        _fight_units_engaged_with,
        _fight_v11_consolidation_engaging_candidates,
        _fight_v11_consolidation_objective_candidates,
        _fight_v11_consolidation_objective_zone,
    )

    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    mids = [m for m in squad_models.get(squad_id, []) if m in models_cache]  # get allowed
    if not mids:
        return None
    # Même contrat que `fight_pile_in_plan`, appelant compris (jumeau pile-in / consolidation) :
    # l'id vient de `fight_v11_grouped_next`, filtré sur `is_unit_alive`.
    our_entry = require_unit_from_cache(squad_id, game_state, "squad_consolidate_plan")
    # `player` requis par `unit_within_engagement_zone_footprints` (via `fight_v11_consolidation_mode`).
    unit_ref: Dict[str, Any] = {"id": squad_id, "player": int(require_key(our_entry, "player"))}
    mode = fight_v11_consolidation_mode(game_state, unit_ref)
    if mode is None:
        return None

    ish = int(require_key(game_state, "inches_to_subhex"))
    budget = 3 * ish

    if mode == "objective":
        # Heuristique gym : premier objectif dans la liste (déjà filtré à ≤3" par la cascade).
        cands = _fight_v11_consolidation_objective_candidates(game_state, unit_ref)
        if not cands:
            return None
        obj_zone: Set[Tuple[int, int]] = _fight_v11_consolidation_objective_zone(game_state, cands[0])
        if not obj_zone:
            return None
        # 12.08 Objective WHILE MOVING : chaque fig doit atterrir DANS la zone (empreinte ∩ zone)
        # si possible, sinon strictement plus proche. `_assign_cells_toward_enemies` produit des
        # cellules B2B (ADJACENTES aux hexes de zone), pas DANS la zone — utiliser à la place une
        # affectation gloutonne directe vers les hexes de zone.
        our_player = int(require_key(our_entry, "player"))
        occupied_by_others = build_occupied_positions_set(game_state, exclude_unit_id=str(squad_id))
        origins: Dict[str, Tuple[int, int]] = {
            mid: (int(models_cache[mid]["col"]), int(models_cache[mid]["row"])) for mid in mids
        }
        taken_obj: Set[Tuple[int, int]] = set(origins.values())
        chosen_obj: Dict[str, Tuple[int, int]] = {}
        for mid in mids:
            oc, or_ = origins[mid]
            if (oc, or_) in obj_zone:
                chosen_obj[mid] = (oc, or_)  # déjà dans la zone → reste sur place
                continue
            reach = model_reach_predicate(
                game_state, str(squad_id), our_player, models_cache[mid], budget,
                int(require_key(models_cache[mid], "level")),
            )
            best_zh: Optional[Tuple[int, int]] = None
            for zh in sorted(obj_zone, key=lambda h: calculate_hex_distance(oc, or_, h[0], h[1])):
                if (zh in taken_obj and zh != (oc, or_)) or zh in occupied_by_others:
                    continue
                if reach(zh[0], zh[1]):
                    best_zh = zh
                    break
            if best_zh is not None:
                taken_obj.discard((oc, or_))
                taken_obj.add(best_zh)
                chosen_obj[mid] = best_zh
            else:
                chosen_obj[mid] = (oc, or_)  # pas de zone hex atteignable → reste sur place
        plan: List[Tuple[str, int, int, int]] = [
            (mid, chosen_obj[mid][0], chosen_obj[mid][1], int(require_key(models_cache[mid], "level")))
            for mid in mids
        ]
        plan_positions = {mid: (c, r) for mid, c, r, _lv in plan}
        if not _validate_plan_coherency(plan_positions, game_state):
            return None
        # 12.08 Objective : au moins 1 fig dans la zone de controle de l objectif apres le move.
        if not any((c, r) in obj_zone for _, c, r, _ in plan):
            return None
        return plan

    # Ongoing ou Engaging : mouvement vers les ennemis cibles.
    # SOURCE UNIQUE partagee avec le pile-in : 12.08 WHILE MOVING (Ongoing/Engaging) porte la
    # meme obligation que 12.03 — immobilite au contact + « engaged with it if possible ».
    if mode == "ongoing":
        target_ids: List[str] = _fight_units_engaged_with(game_state, unit_ref)
    else:  # engaging
        target_ids = _fight_v11_consolidation_engaging_candidates(game_state, unit_ref)
    if not target_ids:
        return None

    enemy_positions: List[Tuple[int, int]] = []
    enemy_entries: List[Dict[str, Any]] = []
    for esid in target_ids:
        enemy_positions.extend(_squad_model_positions(game_state, esid))
        enemy_entries.append(
            require_unit_from_cache(esid, game_state, "squad_consolidate_plan/enemy")
        )
    if not enemy_positions:
        return None

    # `_assign_cells_toward_enemies` est HORIZONTAL : chaque fig reste à son étage, que le plan
    # PORTE (toute entrée de plan porte le sien).
    chosen = _assign_cells_toward_enemies(game_state, squad_id, mids, enemy_positions, budget)
    plan = [
        (mid, chosen[mid][0], chosen[mid][1], int(require_key(models_cache[mid], "level")))
        for mid in mids
    ]

    # Validation finale : coherency + ER (au moins 1 fig dans la zone d engagement des cibles).
    plan_positions = {mid: (c, r) for mid, c, r, _lv in plan}
    if not _validate_plan_coherency(plan_positions, game_state):
        return None
    from engine.spatial_relations import unit_entries_within_engagement_zone
    ez = get_engagement_zone(game_state)
    in_er = any(
        any(
            unit_entries_within_engagement_zone(
                _synth_model_entry(
                    game_state, str(squad_id), models_cache[mid], c, r, level=lv
                ),
                ee, ez, game_state=game_state,
            )
            for ee in enemy_entries
        )
        for mid, c, r, lv in plan
    )
    if not in_er:
        return None
    return plan


# ============================================================================
# END-OF-TURN COHERENCY REMOVAL (squad_multi_figurines.md PR3 3g)
# ============================================================================


# ============================================================================
# SQUAD ACTION MASK (squad_multi_figurines.md PR4 4b — pipeline parallele decoder)
# ============================================================================
# 16 micro-actions :
#   0-5  : Normal move direction D (cf. get_hex_neighbors, parity-aware)
#   6    : Advance (direction depuis macro_intent)
#   7    : Fall Back (direction auto)
#   8    : wait / end activation
#   9-28 : shoot slots 0-19 (V11 T-E : 5 -> 20 slots)
#   14   : charge (vers cible macro_intent)
#   15   : fight (Pile In + declare + resolve + Consolidation)
#
# Returns np-compatible list[int] de longueur 16, valeurs ∈ {0, 1}.


# Refonte spatiale du move (move_action_space_spatial_rework.md §6.2) : une action de mouvement
# ne designe plus une DIRECTION (l'ancien 0-5, qui envoyait l'escouade sur l'hex adjacent et lui
# faisait consommer 1/25e de son budget — root cause §3) mais une CELLULE de la grille
# egocentrique. Le TYPE de move n'est PAS une dimension d'action : il est infere du cout
# geodesique de la cellule (§6.2), ce qui elimine le combo illegal type x cellule que
# MaskablePPO ne saurait pas masquer (il masque chaque dimension independamment, §6.1 option D).
SQUAD_ACTION_MOVE_CELL_BASE = 0
SQUAD_ACTION_MOVE_CELL_COUNT = GRID_CELL_COUNT  # 32x32 = 1024
SQUAD_ACTION_WAIT = SQUAD_ACTION_MOVE_CELL_BASE + SQUAD_ACTION_MOVE_CELL_COUNT  # 1024
SQUAD_ACTION_SHOOT_SLOT_BASE = SQUAD_ACTION_WAIT + 1  # 1025
# V11 §0.30 T-E : 5 -> 20. Mesure : 9 resets sur 10 comptent au moins 6 escouades ennemies,
# donc a 5 slots au moins une escouade etait invisible ET intirable toute la partie (§1.1).
# 20 couvre tres largement le pire cas mesure, et le depassement est desormais LOGUE. Ce
# dimensionnement n'est possible que parce que la tete pointeur (ai/pointer_policy.py) produit
# les logits de tir par produit scalaire sur les embeddings : un slot de plus coute ZERO
# parametre, la ou le format plat en coutait ~226 k (§1.8, mesure).
SQUAD_ACTION_SHOOT_SLOT_COUNT = 20
# V11 §9 P3-2 : la CIBLE DE CHARGE (11.02 « Declare Charge » / 11.04 « BEFORE MOVING: select
# one or more enemy units ») devient une dimension d'action, sur le MEME mapping de slots
# ennemis que le tir et la melee. Avant, `charge` etait une action SANS cible et le decodeur
# tranchait par `get_best_enemy_score_for_unit` (damage_ratio) : l'agent declarait « je charge »
# sans jamais dire QUI, et le masque ne portait qu'un bit « une charge est possible ».
SQUAD_ACTION_CHARGE_SLOT_BASE = SQUAD_ACTION_SHOOT_SLOT_BASE + SQUAD_ACTION_SHOOT_SLOT_COUNT  # 1045
SQUAD_ACTION_CHARGE_SLOT_COUNT = SQUAD_ACTION_SHOOT_SLOT_COUNT  # 20 -> 1045-1064  (cible unique, D1)
# V11 §9 P3 L9 — CHARGE MULTI-CIBLES : C(K_e, 2) paires de cibles, tete DENSE (pas D1).
# Un slot est ouvert ssi les deux cibles individuelles sont chacune declarables.
SQUAD_ACTION_CHARGE_PAIR_SLOT_BASE = SQUAD_ACTION_CHARGE_SLOT_BASE + SQUAD_ACTION_CHARGE_SLOT_COUNT  # 1065
SQUAD_ACTION_CHARGE_PAIR_SLOT_COUNT = (
    SQUAD_ACTION_CHARGE_SLOT_COUNT * (SQUAD_ACTION_CHARGE_SLOT_COUNT - 1) // 2
)  # 190 = C(20,2)
# V11 §9 P3-1 : la CIBLE DE MELEE (12.05) devient une dimension d'action, indexee sur le MEME
# mapping de slots ennemis que le tir (`get_enemy_slot_mapping`). Avant, `squad_fight` etait une
# action sans cible et le moteur tranchait par l'heuristique `_ai_select_fight_target` : l'agent
# ne choisissait rien, et le pool 12.05 n'apparaissait nulle part dans le masque.
# Le compte est DERIVE de celui du tir : un slot = une ligne du tenseur ennemi (invariant D1).
SQUAD_ACTION_FIGHT_SLOT_BASE = (
    SQUAD_ACTION_CHARGE_PAIR_SLOT_BASE + SQUAD_ACTION_CHARGE_PAIR_SLOT_COUNT
)  # 1255
SQUAD_ACTION_FIGHT_SLOT_COUNT = SQUAD_ACTION_SHOOT_SLOT_COUNT  # 20 -> 1065-1084
# Combat « a vide » (12.04/12.06) : selectionne pour combattre sans cible eligible. Etat legal.
SQUAD_ACTION_FIGHT_NO_TARGET = SQUAD_ACTION_FIGHT_SLOT_BASE + SQUAD_ACTION_FIGHT_SLOT_COUNT  # 1275
# 10.02 / 10.07 : le TYPE DE TIR est un choix du joueur (« Select one shooting type that unit is
# eligible to make »), et le tir indirect est le premier type qui n exclut pas le tir normal —
# une meme escouade peut jouer l un ou l autre dans le MEME etat. Il lui faut donc sa propre
# dimension d action : sans elle, l agent ne pourrait exprimer que le defaut, et une regle vive
# cote moteur resterait morte cote IA.
#
# UN SLOT PAR CIBLE, sur le MEME mapping d ennemis que le tir ordinaire (`get_enemy_slot_mapping`)
# — l action dit « tirer INDIRECT sur la cible N ». Le decoupage par cible et non par bit de mode
# est ce qui garde la decision ATOMIQUE : un bit de mode separe demanderait deux actions pour une
# activation, donc un etat intermediaire entre les deux et un masque qui en depend.
#
# Place en FIN d espace d action, apres `FIGHT_NO_TARGET` : les indices existants ne bougent pas.
# Le retrain est de toute facon impose par le changement de dimension (decision utilisateur du
# 2026-08-16), mais garder les indices stables laisse comparables les journaux et les replays
# d avant. Cout en parametres : ZERO — la tete pointeur produit les logits par produit scalaire
# sur les embeddings ennemis, comme pour les 20 slots de tir (cf. leur commentaire).
SQUAD_ACTION_SHOOT_INDIRECT_SLOT_BASE = SQUAD_ACTION_FIGHT_NO_TARGET + 1  # 1086
SQUAD_ACTION_SHOOT_INDIRECT_SLOT_COUNT = SQUAD_ACTION_SHOOT_SLOT_COUNT  # 20 -> 1086-1105
SQUAD_ACTION_SIZE = (
    SQUAD_ACTION_SHOOT_INDIRECT_SLOT_BASE + SQUAD_ACTION_SHOOT_INDIRECT_SLOT_COUNT
)  # 1106
# Chantier 01 : la CIBLE D'OATH OF MOMENT est une dimension d'action, sur le MEME mapping de
# slots ennemis que le tir, la charge et la melee (`get_enemy_slot_mapping`, invariant D1). Le
# compte est DERIVE de celui du tir, exactement comme les deux precedents.
#
# ⚠️ Ces ids ne sont PAS dans `SQUAD_ACTION_SIZE` : ce compteur borne les seules actions que
# `build_squad_action_mask` produit (les micro-actions d'une activation d'escouade), et Oath se
# declare au debut du tour, pas pendant une activation. Ils vivent dans l'action space COMPLET
# (`macro_intents.TOTAL_ACTION_SIZE`), comme les zone intents et les CHOICE_i — le miroir est
# verrouille par `tests/unit/engine/test_action_space_mirror.py`.
SQUAD_ACTION_OATH_SLOT_COUNT = SQUAD_ACTION_SHOOT_SLOT_COUNT  # 20
# V11 §0.48 element L2 : le CHOIX DE L'ESCOUADE A ACTIVER est une dimension d'action, sur le
# mapping de slots ALLIES (`get_ally_slot_mapping`, invariant D1 cote allie). Le compte est DERIVE
# de `K_ALLY_SLOTS` — le nombre de lignes du tenseur allie — comme les slots ennemis derivent du
# compte de slots de tir.
#
# ⚠️ Meme reserve que pour Oath : ces ids ne sont PAS dans `SQUAD_ACTION_SIZE`. Le choix d'activer
# precede l'activation, il n'est donc pas une micro-action d'activation et `build_squad_action_mask`
# ne le produit jamais. Miroir verrouille par `tests/unit/engine/test_action_space_mirror.py`.
SQUAD_ACTION_ACTIVATE_SLOT_COUNT = K_ALLY_SLOTS  # 12
# V11 §0.69 — arme CC par slot d'obs melee. Même réserve que Oath et Activate : hors
# SQUAD_ACTION_SIZE, il ne s'agit pas d'une micro-action d'activation d'escouade.
# Source unique : observation_entities.K_WEAPONS_MELEE. Miroir verrouillé par
# tests/unit/engine/test_action_space_mirror.py.
SQUAD_ACTION_FIGHT_WEAPON_SLOT_COUNT = K_WEAPONS_MELEE  # 10 — armes CC
# P3-8 — sélection de groupe d'arme de TIR (split-fire gym). Même réserve que les trois
# précédents : hors SQUAD_ACTION_SIZE, pas une micro-action d'activation d'escouade ordinaire.
# Source unique : observation_entities.K_WEAPONS_RANGED. Miroir verrouillé par
# tests/unit/engine/test_action_space_mirror.py.
SQUAD_ACTION_SHOOT_WEAPON_SEL_SLOT_COUNT = K_WEAPONS_RANGED  # 10 — groupes d'armes RNG


def _squad_is_in_enemy_er(game_state: Dict[str, Any], squad_id: str) -> bool:
    """True si AU MOINS UNE figurine du squad est dans l ER (bord-a-bord) d une fig ennemie.

    Delegue a la primitive canonique d engagement (unit_within_engagement_zone_footprints :
    empreintes multi-fig + socles ronds euclidien), exactement comme les handlers
    shoot/fight/charge unit-level. Remplace l ancienne mesure centre-a-centre qui
    sous-detectait l engagement pour des bases ecartees (regle 03.04 : 2" entre figurines)."""
    from engine.spatial_relations import unit_within_engagement_zone_footprints
    # Cache absent = moteur non initialisé (erreur) -> require_key. Squad absent = mort ou pas
    # déployé : LÉGITIME ici, ce prédicat est celui du MASQUE de move, dont le contrat est
    # « squad absent/mort -> mask all-zero » (miroir exact de `build_squad_move_cell_map`).
    units_cache = require_key(game_state, "units_cache")
    entry = units_cache.get(str(squad_id))  # get allowed (contrat du masque : absent -> non engagé)
    if entry is None:
        return False
    ez = get_engagement_zone(game_state)
    stub = {"id": str(squad_id), "player": int(require_key(entry, "player"))}
    return unit_within_engagement_zone_footprints(game_state, stub, ez, max_distance=ez)


def squad_is_battle_shocked_in_enemy_er(game_state: Dict[str, Any], squad_id: str) -> bool:
    """Escouade battle-shocked ET engagée : les deux conditions d'un Desperate Escape (09.07).

    SOURCE UNIQUE du prédicat, partagée par le pool par-figurine
    (``movement_build_model_destinations_pool``) et par la borne de trajet de la validation
    (``build_move_transit_blocked``) — les deux côtés de l'invariant « masque ⊆ exécutable ».
    Le dupliquer rouvrirait la classe de bug masque/exécution que ces deux fonctions ferment.

    NE contient PAS la garde de phase : 09.07 ne parle que du fall-back move, mais tous les
    appelants ne sont pas dans la même position pour le savoir. C'est à l'appelant qui borne
    aussi le pile-in/consolidation (12.03) de la poser.
    """
    unit = require_unit_by_id(game_state, str(squad_id))
    return (
        bool(require_key(unit, "battle_shocked"))
        and _squad_is_in_enemy_er(game_state, str(squad_id))
    )


def squad_advance_or_fall_back_allowed(game_state: Dict[str, Any], squad_id: str) -> bool:
    """Une escouade qui a deja Advance ou Fall Back ce tour ne peut plus en refaire un.

    Regle unique, appelee par le masque ET par le decoder (qui decide s'il transmet le jet
    d'Advance au constructeur du pool). L'ecrire aux deux endroits — ce qu'a fait la 1re version
    de la refonte — cree deux verites qui peuvent deriver : le decoder batirait un pool au budget
    Advance que le masque refuserait ensuite, ou l'inverse.
    """
    sid = str(squad_id)
    return (
        sid not in game_state.get("units_advanced", set())  # get allowed
        and sid not in game_state.get("units_fled", set())  # get allowed
    )


def squad_normal_move_frontier_subhex(game_state: Dict[str, Any], squad_id: str) -> int:
    """Budget de move NORMAL réellement EXÉCUTABLE (subhex) = la frontière normal/advance.

    SOURCE UNIQUE de cette frontière, partagée par les quatre consommateurs qui doivent la voir
    identique : le masque (`build_squad_action_mask`), le décodeur (`infer_squad_move_type`),
    l'érosion du pool (`erode_move_pool_by_squad_block`) et le canal de coût de l'observation
    (`normalize_move_costs`).

    `get_squad_move_budget(..., "normal")` seul NE SUFFIT PAS : le squad move rigide atterrit au
    sol, donc `resolve_squad_move_constraints` retranche le coût de descente §13.06 (et le pool
    l'a lui aussi déjà retranché de son budget de construction). Classer une cellule avec `M`
    alors que l'exécution la valide avec `M - descente` produit une bande morte `(M - d, M]` de
    cellules classées `normal` mais INEXÉCUTABLES en normal → `incohérence masque/exécution`
    (§0.34). Elles relèvent d'un Advance, et c'est ce que cette frontière dit.

    Rendu à `max(0, ...)` par `resolve_squad_move_constraints` : une descente qui dépasse M donne
    une frontière nulle — toute destination exige alors un Advance, ce qui est exact.
    """
    from engine.phase_handlers.movement_handlers import squad_descent_penalty_subhex

    return max(
        0,
        get_squad_move_budget(str(squad_id), game_state, "normal")
        - squad_descent_penalty_subhex(game_state, str(squad_id)),
    )


def classify_squad_move_type(
    in_enemy_er: bool, normal_budget: int, geodesic_cost: float
) -> str:
    """LA regle d'inference du type de move (spec §6.2), sous forme PURE.

    - escouade engagee -> `fall_back` (Normal exige d'etre unengaged, 09.05 ; Normal et Fall Back
      s'excluent donc mutuellement — aucun choix a faire).
    - cout <= M        -> `normal`
    - cout > M         -> `advance`  (09.06 : distance max = M + jet)

    `normal_budget` = le budget normal EXÉCUTABLE (`squad_normal_move_frontier_subhex`), coût de
    descente §13.06 déduit — la MEME grandeur que celle que l'exécution valide. Passer `M` brut
    rouvre la bande morte de §0.34.

    Le cout est la distance de CHEMIN (regle 03), pas la distance a vol d'oiseau : une cellule
    proche mais atteignable seulement en contournant un mur peut exiger un Advance.

    Pourquoi deduire plutot que laisser l'agent choisir : avec un type en dimension d'action
    separee, MaskablePPO masquerait type et cellule INDEPENDAMMENT -> le combo `normal` + cellule
    au-dela de M serait illegal mais non masque (le defaut qui fait rejeter l'option D en §6.1).
    Perte nulle : un Advance vers une cellule atteignable en Normal est strictement domine (il
    coute le tir non-ASSAULT et la charge sans rien apporter).

    Forme pure VOULUE : `in_enemy_er` et `normal_budget` sont des invariants de l'escouade, pas de
    la cellule. Le masque les resout UNE fois puis classe ses ~1000 cellules ; les resoudre par
    cellule coutait 1,16 ms pour 270 cellules (48% du masque), via un scan de `units` et un calcul
    d'empreintes d'engagement a chaque appel. La regle reste ecrite une seule fois : `infer_squad_
    move_type` n'est qu'un resolveur de contexte au-dessus d'elle.
    """
    if in_enemy_er:
        return "fall_back"
    if geodesic_cost <= normal_budget:
        return "normal"
    return "advance"


def infer_squad_move_type(
    game_state: Dict[str, Any], squad_id: str, geodesic_cost: float
) -> str:
    """`classify_squad_move_type` avec resolution du contexte depuis `game_state`.

    A n'utiliser que pour UNE cellule (decoder). En boucle, resoudre le contexte une fois et
    appeler `classify_squad_move_type` directement.
    """
    return classify_squad_move_type(
        _squad_is_in_enemy_er(game_state, squad_id),
        squad_normal_move_frontier_subhex(game_state, squad_id),
        geodesic_cost,
    )


MOVE_CELL_MAP_CACHE_KEY = "_squad_move_cell_maps"


def store_squad_move_cell_map(
    game_state: Dict[str, Any],
    squad_id: str,
    cell_map: Dict[int, Tuple[Tuple[int, int], float]],
) -> None:
    """Memoise la carte de cellules construite au MASQUE, pour que le decoder rejoue la meme.

    Motif : le decoder doit executer EXACTEMENT la cellule que le masque a autorisee. La
    reconstruire couterait un 2e BFS par step (~6,4 ms sur board x5) et, surtout, rouvrirait la
    divergence masque/execution si l'etat avait bouge entre les deux. Meme motif que
    `_squad_advance_rolls` (jet tire au masque, relu au decodage).

    La carte est TAMPONNEE par (ancre, phase) : une carte periemee est un mismatch
    masque/execution silencieux, donc `read_squad_move_cell_map` leve au lieu de l'utiliser.
    """
    anchor = require_unit_position(squad_id, game_state)
    game_state.setdefault(MOVE_CELL_MAP_CACHE_KEY, {})[str(squad_id)] = {
        "anchor": anchor,
        "phase": str(game_state.get("phase", "")),
        "map": cell_map,
    }


def read_squad_move_cell_map(
    game_state: Dict[str, Any], squad_id: str
) -> Dict[int, Tuple[Tuple[int, int], float]]:
    """Relit la carte memoisee par le masque. Leve si absente ou perimee.

    Aucun repli : reconstruire ici masquerait une rupture du contrat « masque avant decodage »
    et pourrait executer une cellule que le masque n'avait pas autorisee.

    Le tampon (ancre, phase) ci-dessous est PARTIEL : il ne voit que le deplacement du mover et
    le changement de phase. Sous ``W40K_MASK_VERIFY=1``, la carte est en plus RECALCULEE et
    comparee (cf. `engine.mask_verification`), ce qui couvre les evolutions d'etat que ce tampon
    laisse passer. Desarme, ce controle ne coute rien.
    """
    entry = game_state.get(MOVE_CELL_MAP_CACHE_KEY, {}).get(str(squad_id))  # get allowed
    if entry is None:
        raise ValueError(
            f"read_squad_move_cell_map: aucune carte de cellules pour squad {squad_id} — "
            f"get_squad_action_mask_and_eligible_units doit etre appele avant le decodage"
        )
    anchor = require_unit_position(squad_id, game_state)
    phase = str(game_state.get("phase", ""))
    if entry["anchor"] != anchor or entry["phase"] != phase:
        raise ValueError(
            f"read_squad_move_cell_map: carte perimee pour squad {squad_id} — construite en "
            f"phase {entry['phase']!r} depuis l'ancre {entry['anchor']}, relue en phase {phase!r} "
            f"depuis {anchor}. Executer cette carte designerait d'autres hexes que ceux masques."
        )
    verify_memoised_move_cell_map(game_state, str(squad_id), entry["map"])
    return entry["map"]


def clear_squad_move_cell_map(game_state: Dict[str, Any], squad_id: str) -> None:
    """Oublie la carte d'une escouade (fin d'activation). Miroir du pop de `_squad_advance_rolls`."""
    game_state.get(MOVE_CELL_MAP_CACHE_KEY, {}).pop(str(squad_id), None)  # get allowed


def _mono_model_matches_pool_socle(
    game_state: Dict[str, Any], squad_id: str, alive_mids: "List[str]"
) -> bool:
    """Le survivant unique porte-t-il le socle avec lequel le pool d'ancre a été construit ?

    Le pool lit la géométrie dans ``units_cache[squad]`` (déclaration d'ESCOUADE) ; la validation
    lit celle de la FIGURINE. Tant que les deux coïncident — le cas de toute escouade homogène —
    l'érosion est un no-op pour une mono-figurine et peut être sautée. Dès qu'elles diffèrent, la
    sauter offre des cellules que l'exécution refuse (cf. l'appelant).
    """
    if not alive_mids:
        return True
    entry = require_key(game_state, "units_cache").get(str(squad_id))  # get allowed : hors table
    if entry is None:
        return True
    m = require_key(game_state, "models_cache")[alive_mids[0]]
    return move_geom_key(entry) == move_geom_key(m)


def erode_move_pool_by_squad_block(
    game_state: Dict[str, Any],
    squad_id: str,
    costs: Dict[Tuple[int, int], float],
    constraints: Optional[Dict[str, Any]] = None,
    move_budget: Optional[int] = None,
) -> Dict[Tuple[int, int], float]:
    """V11 T6-g — Retire du pool de move les ancres dont le BLOC translaté est illégal.

    ``movement_build_valid_destinations_pool`` raisonne sur l'ANCRE de l'escouade, mais
    l'exécution passe par ``build_rigid_plan``, qui translate TOUTES les figurines du même
    vecteur. Une ancre parfaitement légale peut donc poser une sœur sur un mur ou sur une
    autre escouade — ``validate_move_plan`` rejette alors une destination que le masque
    avait offerte (« incohérence masque/exécution »).

    Érosion morphologique : le bloc est réduit à ses offsets CUBE relatifs à l'ancre
    (invariants par translation rigide depuis le fix T6-h), et une ancre candidate n'est
    conservée que si CHAQUE figurine atterrit sur une cellule acceptable. Les offsets sont
    groupés par NIVEAU : une figurine ne collisionne qu'avec les figs d'un autre squad au
    même étage — miroir exact de ``validate_move_plan``.

    Prédicat de cellule : le MÊME que ``validate_move_plan``, lu depuis le helper partagé
    ``build_move_blocked_cells_by_level`` (murs, occupation des autres escouades par niveau,
    ER ennemie) — aucune duplication, les deux côtés de l'invariant « masque ⊆ exécutable »
    ne peuvent pas diverger. ``constraints`` doit refléter celles que l'exécution appliquera
    (défaut ``DEFAULT_MOVE_CONSTRAINTS``, ce que passe ``execute_squad_move`` sans
    ``extra_constraints``) : les fournir plus permissives ici sur-filtrerait le masque.

    ``budget_per_model`` (distance de CHEMIN, règle 03) est AUSSI érodé ici, au sol. La distance
    à vol d'oiseau (cube) est bien invariante par translation, mais PAS le trajet légal : une
    figurine partant derrière un mur doit le contourner et peut dépasser son budget là où l'ancre
    (dégagée) tient — c'était le bug « trajet légal > budget ». On borne donc chaque figurine par
    un BFS géodésique depuis SON origine (``geodesic_move_reach`` sur ``build_move_transit_
    blocked``, le MÊME prédicat de transit que ``explain_move_plan_rejection``), au budget que
    l'exécution appliquera à la candidate (M pour normal/fall_back, M + jet pour advance, déduit du
    coût d'ancre via ``classify_squad_move_type``). En métrique EUCLIDIENNE (PvP/bot PvE) le champ
    est le champ any-angle par-figurine, exactement celui que la validation interroge. Seule
    exclusion rendant le cube exact (érosion de budget inactive) : FLY actif (21.03, traversée
    libre). ``require_coherency`` / collision intra-plan sont INVARIANTS par translation
    rigide (positions RELATIVES préservées). Pour la collision intra-plan, l'invariance suffit :
    le pool d'ancre la garantit. Pour la coherency, NON — l'invariance se retourne. Depuis une
    formation déjà hors coherency, la translation la préserve, donc ``validate_move_plan``
    refuse TOUTES les candidates. Cette érosion-ci ne juge que des CELLULES (une propriété
    par-figurine) ; la coherency est une propriété de la FORMATION ENTIÈRE, et c'est
    ``build_squad_move_cell_map``, seul appelant de production, qui la court-circuite en
    rendant un pool vide (voir son commentaire « Formation d'ORIGINE déjà hors coherency »).

    ``move_budget`` : budget (subhex) auquel le pool a été construit — À PASSER par
    ``build_squad_move_cell_map`` pour que l'érosion de budget connaisse le régime réel
    (normal/advance/fall_back). Au masque le jet d'Advance n'est PAS encore dans
    ``_squad_advance_rolls`` (le décodeur l'y stocke à l'exécution) : le re-dériver via
    ``_advance_roll_for`` raterait l'Advance et laisserait passer les cellules advance
    (bug masque/exécution). À ``None`` (appel autonome), on retombe sur ``_advance_roll_for``.

    Lecture pure. Retourne un nouveau dict (sous-ensemble de ``costs``).
    """
    from engine.hex_utils import offset_to_cube, cube_to_offset

    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive_mids = [m for m in squad_models.get(squad_id, []) if m in models_cache]  # get allowed
    if len(alive_mids) <= 1 and _mono_model_matches_pool_socle(game_state, squad_id, alive_mids):
        # Mono-figurine : l'ancre EST le bloc (offset nul), et son coût de pool borne déjà son
        # trajet par le budget que l'exécution appliquera — depuis §0.34 la frontière
        # normal/advance du masque est le budget EXÉCUTABLE (`squad_normal_move_frontier_subhex`,
        # descente §13.06 déduite), la même que celle de `resolve_squad_move_constraints`. Cette
        # égalité est la CONDITION de ce court-circuit : tant qu'elle tient, l'érosion est un
        # no-op ici (test `test_mono_model_squad_descending_is_executable`). Quand elle était
        # fausse, ce `return` laissait passer la bande morte et le gym crashait.
        #
        # SECONDE CONDITION, ajoutée le 2026-08-10 : le socle du survivant doit être celui avec
        # lequel le POOL a été construit. Le pool d'ancre lit la géométrie de l'ESCOUADE
        # (`units_cache`), la validation celle de la FIGURINE depuis que l'EZ s'y mesure
        # par-figurine. Une escouade réduite à son personnage attaché (socle plus grand) rend les
        # deux différents : mesuré sur `scenario_training_armageddon2`, l'escouade 101 réduite à
        # `101#5` (round/8 contre round/6 déclaré) offrait 10 cellules que `validate_move_plan`
        # refuse en « ER ennemie » — l'invariant masque ⊆ exécutable, qui fait LEVER le gym.
        return costs

    anchor = models_cache[alive_mids[0]]
    ax, ay, az = offset_to_cube(int(anchor["col"]), int(anchor["row"]))
    # Offsets groupes par (niveau, GEOMETRIE DE SOCLE) : les cellules interdites dependent du
    # socle pose des lors que l'EZ ennemie est mesuree bord-a-bord (cf.
    # `move_enemy_ez_forbidden_cells`). Grouper par le seul niveau testerait le personnage
    # attache (socle 8) contre les cases interdites d'un Intercessor (socle 6) — miroir exact du
    # regroupement de `explain_move_plan_rejection`, sans quoi masque et execution divergent.
    offsets_by_level_geom: Dict[Tuple[int, MoveGeomKey], List[Tuple[int, int, int]]] = {}
    geom_of_key: Dict[MoveGeomKey, Tuple[str, Any, int]] = {}
    # (origine_col, origine_row, niveau, offset_cube) par figurine — pour l'érosion par budget
    # géodésique (chaque figurine part de SON origine, pas de l'ancre).
    models_geo: List[Tuple[str, int, int, int, Tuple[int, int, int]]] = []
    for mid in alive_mids:
        m = models_cache[mid]
        mx, my, mz = offset_to_cube(int(m["col"]), int(m["row"]))
        off = (mx - ax, my - ay, mz - az)
        # Niveau d'ARRIVÉE (sol) et non d'origine : c'est là que la figurine atterrit, donc c'est
        # cette occupation-là qui la bloque et ce transit-là qu'elle emprunte — miroir de
        # `build_rigid_plan` / `validate_move_plan` / du pool d'ancre (§0.34). Identique au niveau
        # d'origine pour toute escouade déjà au sol, c'est-à-dire partout ailleurs.
        lvl = SQUAD_RIGID_MOVE_DESTINATION_LEVEL
        _shape = require_key(m, "BASE_SHAPE")
        _size = require_key(m, "BASE_SIZE")
        # Orientation COURANTE de la figurine : le bloc est translate rigidement, aucun pivot
        # n'est en cours ici (le pivot molette est un chemin de preview, pas d'erosion).
        _orient = int(m.get("orientation", 0))  # get allowed (socle rond non oriente)
        _gk = move_geom_key(m)
        geom_of_key[_gk] = (_shape, _size, _orient)
        offsets_by_level_geom.setdefault((lvl, _gk), []).append(off)
        models_geo.append((str(mid), int(m["col"]), int(m["row"]), lvl, off))

    board_cols = int(require_key(game_state, "board_cols"))
    board_rows = int(require_key(game_state, "board_rows"))
    player = int(require_key(anchor, "player"))

    # Cellules interdites par NIVEAU — MEME predicat que `validate_move_plan`, via le helper
    # partage (pas de duplication : cf. sa docstring). Pre-agregees -> un seul test
    # d'appartenance par figurine et par candidate.
    c = dict(DEFAULT_MOVE_CONSTRAINTS)
    if constraints:
        c.update(constraints)
    # Ici — et SEULEMENT ici — l'union vaut sa copie : elle est payee une fois par (niveau,
    # geometrie) puis amortie sur |pool| x |figurines| tests (~2800 x 20). Cf. la docstring du
    # helper : c'est l'arbitrage du consommateur, `validate_move_plan` fait l'inverse.
    blocked_by_level_geom: Dict[Tuple[int, MoveGeomKey], Set[Tuple[int, int]]] = {}
    for _gk, (_shape, _size, _orient) in geom_of_key.items():
        _levels_for_geom = {lv for (lv, gk) in offsets_by_level_geom if gk == _gk}
        _sets_by_level = build_move_blocked_cells_by_level(
            game_state, squad_id, player, _levels_for_geom, c, _shape, _size, _orient
        )
        for lv, sets in _sets_by_level.items():
            merged: Set[Tuple[int, int]] = set()
            for _label, s in sets:
                merged |= s
            blocked_by_level_geom[(lv, _gk)] = merged

    # ── Budget en distance de CHEMIN par-figurine (bug « trajet légal > budget ») ──
    # Le pool borne le TRAJET de l'ANCRE (chemin, contournant murs) ; l'exécution translate tout
    # le bloc du même vecteur cube. La distance à vol d'oiseau (cube) est invariante par cette
    # translation, mais PAS le trajet légal : une sœur partant derrière un mur doit le contourner
    # et peut dépasser son budget là où l'ancre (dégagée) tient. On érode donc les ancres où une
    # figurine non-FLY dépasserait son budget de chemin. Prédicat EXACT (mêmes champs que
    # ``explain_move_plan_rejection``) → toute cellule conservée passe la validation à
    # l'exécution : invariant « masque ⊆ exécutable », ZÉRO crash, ZÉRO sur-érosion.
    #
    # LES DEUX MÉTRIQUES sont érodées, parce que les deux sont validées : `geodesic` par le champ
    # hex, `euclidean` par le champ any-angle par-figurine. L'exclusion euclidienne qui vivait ici
    # (« traité comme cube-exact ») était le pendant du raccourci ligne droite que
    # `explain_move_plan_rejection` s'accordait alors : la validation bornant désormais le TRAJET
    # dans les trois géométries, garder l'exclusion ferait offrir au masque des ancres que
    # `execute_squad_move` rejette (« incohérence masque/exécution », ValueError en plein run).
    # Seule reste l'exclusion FLY (21.03) : la traversée ignore murs et figurines, donc le trajet
    # EST la ligne droite, invariante par la translation cube du bloc.
    #
    # Coût : un champ par figurine RÉELLEMENT proche d'un obstacle de transit (gate) en hex — une
    # figurine sans mur/ennemi dans son rayon de budget a chemin == cube, déjà borné par le pool
    # d'ancre. Le gate NE S'APPLIQUE PAS en euclidien : il raisonne en pas centre-à-centre, alors
    # que le champ any-angle dilate les obstacles de la CLAIRANCE DE SOCLE — un obstacle hors bbox
    # d'un rayon de socle interdit quand même le passage. En euclidien le champ est donc payé pour
    # chaque figurine (une fois par fingerprint d'état, cf. le cache de `build_squad_move_cell_map`).
    _geo_budget = False
    _field_by_origin: Dict[Tuple[str, int, int, int], Mapping[Tuple[int, int], float]] = {}
    _geo_models: List[Tuple[str, int, int, int, Tuple[int, int, int]]] = []
    _classifier_normal = 0
    _normal_exec = 0
    _advance_exec: Optional[int] = None
    _in_er = False
    from engine.hex_utils import ENGAGEMENT_NORM_HEX_WIDTH
    from engine.phase_handlers.movement_handlers import (
        _fly_traversal_active,
        _advance_roll_for,
        squad_descent_penalty_subhex,
    )
    # Géométrie du trajet — SOURCE UNIQUE partagée avec la validation et la mesure.
    _mode = move_plan_distance_mode(game_state, str(squad_id))
    _unit_obj = require_unit_by_id(game_state, str(squad_id))
    # `cube` == métrique hex + FLY déclaré ; en euclidien le mode ne porte pas le FLY (le champ
    # any-angle le traite en interne), on interroge donc le prédicat, qui est la même source.
    _fly_active = _mode == "cube" or _fly_traversal_active(game_state, _unit_obj, str(squad_id))
    # Unité de distance des champs : pas centre-à-centre en hex, unités `_hex_center` en euclidien.
    _dist_scale = ENGAGEMENT_NORM_HEX_WIDTH if _mode == "euclidean" else 1.0
    if not _fly_active:
        _geo_budget = True
        _descent = squad_descent_penalty_subhex(game_state, str(squad_id))
        _classifier_normal = get_squad_move_budget(str(squad_id), game_state, "normal")
        # SOURCE UNIQUE de la frontière normal/advance (§0.34) — jamais recalculée en ligne ici,
        # sinon une évolution de la pénalité ferait diverger l'érosion du masque en silence.
        _normal_exec = squad_normal_move_frontier_subhex(game_state, str(squad_id))
        _in_er = _squad_is_in_enemy_er(game_state, str(squad_id))
        # Budget de construction du pool = source de vérité du régime (normal/advance/fall_back).
        # CRUCIAL : au masque, le jet d'Advance est passé en PARAMÈTRE à `build_squad_move_cell_map`
        # mais n'est PAS encore dans `_squad_advance_rolls` (le décodeur l'y stocke seulement à
        # l'exécution). Re-dériver via `_advance_roll_for` renverrait donc None et raterait le
        # régime Advance → l'érosion utiliserait l'extent normal et laisserait passer les cellules
        # advance (bug masque/exécution). On prend donc le budget que le POOL a réellement utilisé.
        if move_budget is not None:
            _pool_budget = int(move_budget)
        else:
            # Appel autonome (hors masque gym) : re-dérive comme le pool par défaut.
            _adv_roll = _advance_roll_for(str(squad_id), game_state)
            if _in_er:
                _pool_budget = get_squad_move_budget(str(squad_id), game_state, "fall_back")
            elif _adv_roll is not None:
                _pool_budget = get_squad_move_budget(
                    str(squad_id), game_state, "advance", advance_roll=_adv_roll
                )
            else:
                _pool_budget = _classifier_normal
        # Régime Advance ssi le pool a été construit à un budget > M (le jet a élargi le disque).
        if (not _in_er) and _pool_budget > _classifier_normal:
            _advance_exec = max(0, _pool_budget - _descent)
        _extent = _advance_exec if _advance_exec is not None else _normal_exec
        # Transit sol par niveau (murs + ennemis/amies/EZ selon toggles) — même prédicat de chemin
        # que `explain_move_plan_rejection`. Champ géodésique par ORIGINE de figurine, borné à
        # l'extent (budget max), réutilisé pour toutes les candidates.
        _transit_by_level: Dict[int, Set[Tuple[int, int]]] = {}
        for (_mid_g, _oc, _or_, lvl, _off) in models_geo:
            if lvl not in _transit_by_level:
                _transit_by_level[lvl] = build_move_transit_blocked(
                    game_state, str(squad_id), player, lvl
                )
        # Gate (HEX seulement, cf. l'en-tête) : une figurine dont aucun obstacle de transit n'est
        # à <= extent (bbox) a chemin == cube partout dans son budget → borne déjà assurée par le
        # pool. Seules les figurines au contact d'un obstacle exigent un BFS. ``_local_transit`` =
        # transit filtré à la bbox du bloc, calculé une fois (test de proximité en O(|local|)).
        _local_transit_by_level: Dict[int, List[Tuple[int, int]]] = {}
        if models_geo and _mode != "euclidean":
            _bmin_c = min(oc for _m, oc, _r, _l, _o in models_geo) - _extent
            _bmax_c = max(oc for _m, oc, _r, _l, _o in models_geo) + _extent
            _bmin_r = min(orow for _m, _c, orow, _l, _o in models_geo) - _extent
            _bmax_r = max(orow for _m, _c, orow, _l, _o in models_geo) + _extent
            for lvl, tset in _transit_by_level.items():
                _local_transit_by_level[lvl] = [
                    (tc, tr) for (tc, tr) in tset
                    if _bmin_r <= tr <= _bmax_r and _bmin_c <= tc <= _bmax_c
                ]
        for (mid_g, ocol, orow, lvl, off) in models_geo:
            # Le court-circuit cube n'est valide que si le budget d'exécution égale le budget
            # classifieur (sinon M - descente < M et le cube n'est plus garanti par le pool).
            if _descent == 0 and _mode != "euclidean":
                _local = _local_transit_by_level.get(lvl, ())
                if not any(
                    abs(tc - ocol) <= _extent and abs(tr - orow) <= _extent
                    for (tc, tr) in _local
                ):
                    continue  # cube-safe : aucun BFS
            _geo_models.append((mid_g, ocol, orow, lvl, off))
            # Clé PAR FIGURINE en euclidien : le champ any-angle dépend du socle (forme, taille,
            # orientation), pas seulement de l'origine. Deux figurines superposables en hex ne le
            # sont pas là — un Captain (base 8) ne passe pas où passe un Intercessor (base 6).
            _fkey = (mid_g if _mode == "euclidean" else "", ocol, orow, lvl)
            if _fkey not in _field_by_origin:
                if _mode == "euclidean":
                    _field_by_origin[_fkey] = _euclidean_move_field_for_model(
                        game_state, str(squad_id), player, models_cache[mid_g], lvl, _extent
                    )
                else:
                    # Champ hex conservé TEL QUEL (coûts entiers) : `Mapping[..., float]` est
                    # covariant, donc pas de dict recopié sur le chemin chaud du masque gym.
                    _field_by_origin[_fkey] = geodesic_move_reach(
                        ocol, orow, _extent, _transit_by_level[lvl], board_cols, board_rows
                    )
        if not _geo_models:
            _geo_budget = False  # aucune figurine à contraindre → pool d'ancre déjà exact

    kept: Dict[Tuple[int, int], float] = {}
    for (cc, rr), cost in costs.items():
        bx, by, bz = offset_to_cube(int(cc), int(rr))
        ok = True
        for (lv, _gk), offs in offsets_by_level_geom.items():
            blocked = blocked_by_level_geom[(lv, _gk)]
            for (ox, oy, oz) in offs:
                ncol, nrow = cube_to_offset(bx + ox, by + oy, bz + oz)
                if not (0 <= ncol < board_cols and 0 <= nrow < board_rows):
                    ok = False
                    break
                if (ncol, nrow) in blocked:
                    ok = False
                    break
            if not ok:
                break
        if ok and _geo_budget:
            # Budget effectif de CETTE candidate = celui que l'exécution appliquera, déduit du type
            # de move (classify_squad_move_type sur le coût d'ancre) : normal/fall_back → M,
            # advance → M + jet. Chaque figurine contrainte doit atteindre sa destination translatée
            # dans ce budget en distance de CHEMIN (sinon `validate_move_plan` lèverait à l'exécution).
            # La frontière est `_normal_exec` (= M - descente §13.06), PAS `_classifier_normal` :
            # c'est celle du masque et du décodeur (`squad_normal_move_frontier_subhex`). Comparer
            # à M classait `normal` des cellules de la bande `(M - d, M]` puis les érodait comme
            # hors budget — elles relèvent d'un Advance et sont désormais gardées (§0.34).
            if _in_er or cost <= _normal_exec:
                _exec_b = _normal_exec
            else:
                _exec_b = _advance_exec if _advance_exec is not None else _normal_exec
            # `_dist_scale` porte l'unité du champ : 1 pas en hex, `ENGAGEMENT_NORM_HEX_WIDTH`
            # unités `_hex_center` par subhex en euclidien — comparer sans lui rendrait l'érosion
            # euclidienne 1,5x trop stricte (et le masque plus pauvre que l'exécutable).
            _exec_d = _exec_b * _dist_scale
            for (mid_g, ocol, orow, lvl, (ox, oy, oz)) in _geo_models:
                ncol, nrow = cube_to_offset(bx + ox, by + oy, bz + oz)
                _fk = (mid_g if _mode == "euclidean" else "", ocol, orow, lvl)
                _d = _field_by_origin[_fk].get((ncol, nrow))
                if _d is None or _d > _exec_d:
                    ok = False
                    break
        if ok:
            kept[(cc, rr)] = cost
    return kept


def build_squad_move_cell_map(
    game_state: Dict[str, Any], squad_id: str, advance_roll: Optional[int]
) -> Dict[int, Tuple[Tuple[int, int], float]]:
    """Cellules de move jouables -> {cell_index: ((col,row), cout_geodesique)}.

    SOURCE UNIQUE du masque (T2) ET du decodage (T3) : les deux lisent ce meme dict, donc une
    cellule masquee=1 a toujours une destination executable, et l'inverse. C'est ce qui supprime
    la classe de bugs « mask/execution mismatch ».

    Un SEUL BFS suffit (spec §7 T2) :
      - engagee   -> pool au budget Fall Back (= M). Normal est interdit (09.05 unengaged), donc
                     Normal et Fall Back ne coexistent jamais : rien a fusionner.
      - unengagee -> pool au budget ADVANCE (M + jet). Le pool Normal y est INCLUS (budget
                     superieur) ; c'est le cout geodesique conserve qui separe ensuite les deux
                     regimes (cf. `infer_squad_move_type`). Verifie par test : classer le pool
                     Advance par cout <= M reproduit exactement le pool construit au budget M.

    `advance_roll` : jet pre-tire par le caller (§10.4 — divergence de timing vs 09.06 enterinee).
    A None, le budget Advance est inconnu : le pool est construit au budget NORMAL, donc aucune
    cellule Advance n'existe. C'est exactement la semantique de l'ancien masque directionnel
    (« Si None, mask Advance fully a 0 »), pas une valeur par defaut masquant une erreur.
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled
    from engine.phase_handlers.movement_handlers import movement_build_valid_destinations_pool
    from engine.spatial_grid import grid_half_extent_subhex, project_pool_to_grid

    _perf = perf_timing_enabled(game_state)
    _t0 = time.perf_counter() if _perf else None

    # `units_cache` absent = moteur non initialise (erreur), pas un cas metier -> require_key.
    # En revanche un squad ABSENT du cache est legitime (mort/pas deploye) -> aucune cellule,
    # miroir du contrat de `build_squad_action_mask` (« squad absent/mort -> mask all-zero »).
    units_cache = require_key(game_state, "units_cache")
    entry = units_cache.get(squad_id)
    if entry is None:
        return {}

    # Mémoïsation intra-step (2-slots par escouade, items 1.1+1.2 perf_entrainement).
    # Structure : _cache[squad_id] = [[cheap_key, fp_key, result], ...]  — max 2 slots.
    # DEUX niveaux de clé pour séparer le coût sur hit du coût sur miss :
    #
    # 1. CHEAP KEY (O(1)) : (_unit_move_version, advance_roll, phase, bshock, tts_bool).
    #    Capturée sur le chemin NORMAL. N'est plus un court-circuit de lecture (§0.18) : stockée
    #    pour mise à jour du slot sur hit fp_key uniquement.
    #
    # 2. FP KEY (O(unités + figs)) : fingerprint géométrique complet. Conservé comme défense en
    #    profondeur : si la cheap key est fausse (batch, mutation directe, bshock/tts non capturé
    #    par le compteur), la clé géométrique détecte quand même le miss. Une version pure sur
    #    compteur sans fp_key = retour à la régression §0.18.
    #
    # 2 SLOTS : couvre l'alternance budget normal (advance_roll=None) / budget advance
    # (advance_roll=X) sur la même escouade sans double BFS.
    _unit_obj_fp = require_unit_by_id(game_state, squad_id)
    _bshock = bool(require_key(_unit_obj_fp, "battle_shocked"))
    _phase_str = str(game_state.get("phase", ""))  # get allowed
    from engine.phase_handlers.movement_handlers import (
        take_to_the_skies_applies_to_phase as _tts_phase_fp,
        took_to_the_skies as _tts_fp,
    )
    _tts_bool = bool(
        _tts_phase_fp(game_state, charge=False)
        and _tts_fp(game_state, _unit_obj_fp, str(squad_id), charge=False)
    )
    _cheap_key = (
        game_state["_unit_move_version"],
        advance_roll,
        _phase_str,
        _bshock,
        _tts_bool,
    )
    _cache = game_state.setdefault("_squad_move_pool_cache", {})
    _slots = _cache.get(str(squad_id))
    _in_batch = game_state.get("_los_batch") is not None

    # Fingerprint géométrique complet — TOUJOURS calculé, même sur un hit cheap_key.
    # Deux raisons :
    # (a) INVALIDATION : une occupation change sans bumper _unit_move_version (batch LoS,
    #     mutation directe) → la cheap_key ne voit rien mais la fp_key détecte le miss.
    # (b) MESURE PERF : `fp_s > 0` est exigé sur un hit par les tests (le coût du fingerprint
    #     EST la raison d'être du marqueur — distinguer hit-fp de hit-BFS).
    # La cheap_key reste stockée pour mettre à jour le slot après un hit fp_key, mais elle
    # n'est plus un court-circuit : c'est la fp_key qui décide du hit ou du miss.
    _mc_fp = require_key(game_state, "models_cache")
    _sm_fp = require_key(game_state, "squad_models")
    _units_fp = tuple(sorted(
        (
            str(_sid), int(_e["col"]), int(_e["row"]),
            tuple(sorted((int(_c), int(_r)) for _c, _r in _e["occupied_hexes"]))
            if _e.get("occupied_hexes") else (),  # get allowed (single-hex -> ancre seule)
        )
        for _sid, _e in units_cache.items()
    ))
    _block_fp = tuple(sorted(
        (str(_mid), int(_m["col"]), int(_m["row"]), int(_m.get("level", 0)))  # get allowed
        for _mid in _sm_fp.get(str(squad_id), [])  # get allowed
        if (_m := _mc_fp.get(str(_mid))) is not None
    ))
    _fp_key = (
        advance_roll,
        _tts_bool,
        _phase_str,
        _bshock,
        hash(_units_fp),
        hash(_block_fp),
    )
    _fp_s = (time.perf_counter() - _t0) if _t0 is not None else 0.0

    if _slots is not None:
        for _s in _slots:
            if _s[1] == _fp_key:
                _s[0] = _cheap_key  # met à jour la cheap key pour le prochain appel
                if _perf and _t0 is not None:
                    append_perf_timing_line(
                        f"SQUAD_MOVE_CELL_MAP episode={game_state.get('episode_number', '?')} "
                        f"turn={game_state.get('turn', '?')} squad={squad_id} cache_hit=1 "
                        f"fp_s={_fp_s:.6f} pool_s=0.000000 erode_s=0.000000 project_s=0.000000 "
                        f"total_s={time.perf_counter() - _t0:.6f} cells_n={len(_s[2])}"
                    )
                return _s[2]

    if _squad_is_in_enemy_er(game_state, squad_id):
        budget = get_squad_move_budget(squad_id, game_state, "fall_back")
    elif advance_roll is None:
        budget = get_squad_move_budget(squad_id, game_state, "normal")
    else:
        budget = get_squad_move_budget(squad_id, game_state, "advance", advance_roll=advance_roll)

    # Pas de garde `budget <= 0` ici : un budget nul est un etat legitime (`max(0, MOVE - malus)`,
    # Take to the skies 21.03) et le pool le traite deja — il renvoie simplement zero destination,
    # donc zero cellule jouable. Ajouter une garde reviendrait a court-circuiter le moteur.
    # Formation d'ORIGINE deja hors coherency -> AUCUNE destination n'est jouable, pool VIDE.
    # `erode_move_pool_by_squad_block` documente `require_coherency` comme « deja garanti par le
    # pool d'ancre », parce qu'il est invariant par translation rigide. L'invariance est vraie
    # (`test_coherency_translation_invariance`) mais elle SE RETOURNE : depuis une formation deja
    # incoherente, la translation preserve l'incoherence, donc `validate_move_plan` refuse CHAQUE
    # candidate. Le masque offrait alors tout le pool a une escouade dont aucun mouvement n'est
    # executable -> `execute_squad_move a echoue ... (formation actuelle DEJA incoherente)` :
    # l'invariant « masque ⊆ executable », qui fait LEVER le gym en plein run.
    # Pool vide = LA REGLE, pas un repli. 03.01 ENDING A MOVE : une unite qui ne peut pas finir
    # en coherency « cannot make that move », ses figurines reviennent a leur position de depart
    # et elle reste stationnaire (09.04). Ce n'est pas un gel definitif : 03.03 REGAINING
    # COHERENCY retire des figurines en fin de tour jusqu'au retour en coherency.
    # Ni masque vide ni impasse : `build_squad_action_mask` pose `mask[SQUAD_ACTION_WAIT] = 1`
    # INCONDITIONNELLEMENT en phase move.
    # Place ICI et pas dans l'erosion : la coherency est une propriete de la FORMATION ENTIERE,
    # quand l'erosion ne juge que des CELLULES. Avant le pool BFS -> aussi un cout evite.
    _alive_fp = [
        _m for _mid in _sm_fp.get(str(squad_id), [])  # get allowed
        if (_m := _mc_fp.get(str(_mid))) is not None
    ]
    if not _positions_in_coherency(_alive_fp, game_state):
        _new_slot = [_cheap_key, _fp_key, {}]
        _cache[str(squad_id)] = [_new_slot] + [s for s in (_slots or []) if s[1] != _fp_key][:1]
        return {}

    costs: Dict[Tuple[int, int], float] = {}
    # `destination_level` : le squad move rigide atterrit au SOL (cf.
    # `SQUAD_RIGID_MOVE_DESTINATION_LEVEL`) — la légalité des cellules doit donc être évaluée
    # au niveau 0, celui que `validate_move_plan` appliquera, et non à l'étage de départ (§0.34).
    _t_pool = time.perf_counter() if _perf else None
    movement_build_valid_destinations_pool(
        game_state, squad_id, read_only=True, move_budget_override=budget, out_costs=costs,
        destination_level=SQUAD_RIGID_MOVE_DESTINATION_LEVEL,
    )
    _pool_s = (time.perf_counter() - _t_pool) if _t_pool is not None else 0.0

    # T6-g : le pool ci-dessus ne valide que l'ANCRE ; l'execution translate tout le BLOC.
    # Erosion par l'empreinte combinee AVANT projection -> toute cellule masquee=1 est
    # executable par `build_rigid_plan` + `validate_move_plan`. On passe `budget` (le budget
    # EXACT auquel le pool a ete construit) : l'erosion du budget de chemin par-figurine en depend,
    # et le jet d'Advance n'est pas encore dans `_squad_advance_rolls` au masque (cf. erode).
    _t_erode = time.perf_counter() if _perf else None
    costs = erode_move_pool_by_squad_block(game_state, squad_id, costs, move_budget=budget)
    _erode_s = (time.perf_counter() - _t_erode) if _t_erode is not None else 0.0

    # Ancre = units_cache, la MEME source que `require_unit_position` d'ou part le pool : grille et
    # pool sont donc concentriques.
    _t_proj = time.perf_counter() if _perf else None
    anchor_col, anchor_row = int(entry["col"]), int(entry["row"])
    half_extent = grid_half_extent_subhex(game_state, squad_id)
    result = project_pool_to_grid(costs, anchor_col, anchor_row, half_extent)
    _project_s = (time.perf_counter() - _t_proj) if _t_proj is not None else 0.0
    _new_slot = [_cheap_key, _fp_key, result]
    _cache[str(squad_id)] = [_new_slot] + [s for s in (_slots or []) if s[1] != _fp_key][:1]
    if _perf and _t0 is not None:
        append_perf_timing_line(
            f"SQUAD_MOVE_CELL_MAP episode={game_state.get('episode_number', '?')} "
            f"turn={game_state.get('turn', '?')} squad={squad_id} cache_hit=0 "
            f"fp_s={_fp_s:.6f} pool_s={_pool_s:.6f} erode_s={_erode_s:.6f} "
            f"project_s={_project_s:.6f} total_s={time.perf_counter() - _t0:.6f} "
            f"cells_n={len(result)}"
        )
    return result


def _target_locked_by_ally(
    units_cache: Dict[str, Any],
    enemy_entry: Dict[str, Any],
    squad_id: str,
    our_player: int,
    ez: int,
    game_state: Dict[str, Any],
) -> bool:
    """True si l ennemi est en zone d engagement d au moins un allie du tireur (10.09).

    Predique partage par les boucles de masque tir normal (10.04/10.05/10.06) et indirect (10.07).
    """
    for _sid, e in entries_on_battlefield(units_cache, exclude_id=squad_id):
        if int(e["player"]) != our_player:
            continue
        if unit_entries_within_engagement_zone(enemy_entry, e, ez, game_state=game_state):
            return True
    return False


def shoot_weapon_sel_open_slots(
    game_state: Dict[str, Any],
    squad_id: str,
    enemy_slot_ids: List[Optional[str]],
) -> List[int]:
    """Indices absolus des slots SHOOT_WEAPON_SEL à ouvrir (P3-8, split-fire gym).

    Hors SQUAD_ACTION_SIZE : à appeler depuis le masque COMPLET (TOTAL_ACTION_SIZE), jamais
    depuis build_squad_action_mask dont le buffer ne couvre que les indices 0..SQUAD_ACTION_SIZE-1.
    Retourne [] si aucun type de tir n'est applicable ou si l'escouade est absente.
    """
    shooting_type = resolve_squad_shooting_type(game_state, squad_id)
    if shooting_type is None:
        return []
    from engine.macro_intents import SHOOT_WEAPON_SEL_SLOT_BASE
    from engine.observation_weapon_profiles import collect_weapon_profiles, profile_identity
    units_cache = require_key(game_state, "units_cache")
    entry = units_cache.get(squad_id)
    if entry is None:
        return []
    our_player = int(require_key(entry, "player"))
    # Item 1.4 : réutiliser alive + elig_targets calculés par build_squad_action_mask quand
    # les deux sont appelés dans le même état (chemin action_decoder standard).
    _pass = game_state.get("_shoot_pass_cache")
    if _pass is not None and _pass[0] == squad_id:
        alive, elig_targets = _pass[1], _pass[2]
    else:
        ez = get_engagement_zone(game_state)
        mc = game_state.get("models_cache", {})  # get allowed
        alive = [
            mc[mid]
            for mid in game_state.get("squad_models", {}).get(squad_id, [])  # get allowed
            if mid in mc
        ]
        elig_targets = [
            esid for esid in enemy_slot_ids
            if esid is not None
            and esid in units_cache
            and entry_is_on_battlefield(units_cache[esid])
            and not _target_locked_by_ally(
                units_cache, units_cache[esid], squad_id, our_player, ez, game_state
            )
        ]
    profiles = collect_weapon_profiles(alive, "RNG_WEAPONS")
    opened_combi: set = set()
    open_indices: List[int] = []
    for slot_j, (wpn, _) in enumerate(profiles[:SQUAD_ACTION_SHOOT_WEAPON_SEL_SLOT_COUNT]):
        combi = wpn.get("COMBI_WEAPON") if isinstance(wpn, dict) else None
        if combi is not None and combi in opened_combi:
            continue
        pkey = profile_identity(wpn)
        if any(
            _model_can_shoot_target_with_weapon(game_state, m, esid, widx)
            for m in alive
            for widx, w in enumerate(ranged_weapons(m))
            if profile_identity(w) == pkey
            for esid in elig_targets
        ):
            open_indices.append(SHOOT_WEAPON_SEL_SLOT_BASE + slot_j)
            if combi is not None:
                opened_combi.add(combi)
    return open_indices


def build_squad_action_mask(
    game_state: Dict[str, Any],
    squad_id: str,
    enemy_slot_ids: Optional[List[Optional[str]]] = None,
    advance_roll: Optional[int] = None,
    move_cell_map: Optional[Dict[int, Tuple[Tuple[int, int], float]]] = None,
) -> List[int]:
    """Construit le masque `SQUAD_ACTION_SIZE` (1047) pour une escouade active.

    Phase move : les actions 0..1023 designent une CELLULE de la grille egocentrique, pas une
    direction (refonte spatiale, cf. `build_squad_move_cell_map`). Une cellule est mask=1 ssi
    elle porte une destination du pool BFS — le pool reste la seule autorite des regles.

    Phase courante lue depuis game_state['phase']. Si squad absent/mort, mask all-zero.

    enemy_slot_ids : mapping slot 0..4 → squad_id ennemi (ou None). Defaut : 1ers 5
    enemy squads tries par str(sid) (PR4 4a coherence ; PR4 4d stable mapping disponible
    via get_enemy_slot_mapping).

    advance_roll : jet D6 pre-tire, partage avec le decoder. A None, le pool est construit au
    budget normal, donc aucune cellule Advance n'existe (semantique de l'ancien masque
    directionnel : « Si None, mask Advance fully a 0 »).

    move_cell_map : carte deja construite par l'appelant (le decoder la construit une fois puis la
    memoise pour le decodage, cf. `store_squad_move_cell_map`). A None, elle est construite ici —
    ce qui evite un 2e BFS quand l'appelant l'a deja, sans obliger les appelants isoles (tests,
    outils) a la fabriquer.
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    _perf = perf_timing_enabled(game_state)
    _t0 = time.perf_counter() if _perf else None
    _cell_map_s = 0.0

    def _log_mask(outcome: str) -> None:
        if not _perf or _t0 is None:
            return
        append_perf_timing_line(
            f"SQUAD_ACTION_MASK episode={game_state.get('episode_number', '?')} "
            f"turn={game_state.get('turn', '?')} squad={squad_id} "
            f"phase={str(game_state.get('phase', '')).lower()} outcome={outcome} "
            f"cell_map_s={_cell_map_s:.6f} total_s={time.perf_counter() - _t0:.6f} "
            f"ones_n={sum(mask)}"
        )

    mask = [0] * SQUAD_ACTION_SIZE
    # Cache absent = moteur non initialisé -> require_key. Squad absent = mort ou pas déployé :
    # c'est le CONTRAT du masque (« absent/mort -> all-zero »), il reste.
    units_cache = require_key(game_state, "units_cache")
    if squad_id not in units_cache:
        _log_mask("squad_absent")
        return mask
    entry = units_cache[squad_id]
    our_player = int(require_key(entry, "player"))
    phase = str(game_state.get("phase", "")).lower()
    in_er = _squad_is_in_enemy_er(game_state, squad_id)
    has_advanced = squad_id in game_state.get("units_advanced", set())
    has_fled = squad_id in game_state.get("units_fled", set())
    has_moved = squad_id in game_state.get("units_moved", set())

    if enemy_slot_ids is None:
        enemy_sorted = sorted(
            (sid for sid, e in units_cache.items() if int(e["player"]) != our_player),
            key=lambda s: str(s),
        )
        enemy_slot_ids = list(enemy_sorted[:SQUAD_ACTION_SHOOT_SLOT_COUNT]) + [None] * max(
            0, SQUAD_ACTION_SHOOT_SLOT_COUNT - len(enemy_sorted)
        )

    # --- Move phase: cellules de la grille egocentrique (0..1023) ---
    # Remplace les 18 dry-runs directionnels (3 types x 6 directions), qui n'exploraient que les
    # 6 hexes ADJACENTS a l'ancre : l'escouade ne pouvait avancer que d'1 subhex par phase, soit
    # 1/25e de son budget sur un board x5 (root cause §3). Un seul BFS au budget Advance, projete
    # sur la grille, expose desormais TOUT le disque atteignable.
    if phase == "move":
        if not has_moved:
            # Miroir EXACT des gardes de l'ancien masque directionnel : `has_advanced`/`has_fled`
            # fermaient Advance et Fall Back, mais PAS le Normal. Regle partagee avec le decoder.
            advance_or_fall_back_allowed = squad_advance_or_fall_back_allowed(game_state, squad_id)
            _t_cm = time.perf_counter() if _perf else None
            cell_map = (
                move_cell_map
                if move_cell_map is not None
                else build_squad_move_cell_map(
                    game_state, squad_id, advance_roll if advance_or_fall_back_allowed else None
                )
            )
            if _t_cm is not None:
                _cell_map_s = time.perf_counter() - _t_cm
            # Invariants de l'escouade resolus UNE fois : les reresoudre par cellule coutait 48%
            # du masque (scan de `units` + empreintes d'engagement a chaque appel).
            # Frontiere = budget normal EXECUTABLE (descente §13.06 deduite), la meme grandeur que
            # `resolve_squad_move_constraints` valide a l'execution (§0.34).
            normal_budget = squad_normal_move_frontier_subhex(game_state, squad_id)
            for cell_idx, (_dest, cost) in cell_map.items():
                # Type classe par `classify_squad_move_type`, la MEME regle que le decoder (T3)
                # appliquera pour executer la cellule. La rejouer en ligne ici (`cost >
                # normal_budget`) creerait une 2e implementation, donc un risque de divergence
                # masque/execution — precisement ce que cette refonte supprime.
                if classify_squad_move_type(in_er, normal_budget, cost) != "normal":
                    # `fall_back` (escouade engagee) et `advance` sont fermes par has_advanced /
                    # has_fled ; le Normal, lui, ne l'est pas (miroir exact du masque directionnel).
                    if not advance_or_fall_back_allowed:
                        continue
                mask[SQUAD_ACTION_MOVE_CELL_BASE + cell_idx] = 1
        mask[SQUAD_ACTION_WAIT] = 1

    # --- Shoot phase: shoot slots 19-23 ---
    elif phase == "shoot":
        # 10.04 / 10.05 / 10.06 : le type de tir applicable REMPLACE l ancien
        # `not has_advanced and not in_er`, qui fermait le tir sans regarder les armes et
        # supprimait donc deux types de tir entiers pour l agent (cf. resolve_squad_shooting_type).
        shooting_type = resolve_squad_shooting_type(game_state, squad_id)
        ez = get_engagement_zone(game_state)
        # Item 1.4 : pré-calculer alive + elig une seule fois ; shoot_weapon_sel_open_slots
        # (appelé juste après dans action_decoder) lit le même résultat via _shoot_pass_cache.
        _shoot_mc = game_state.get("models_cache", {})  # get allowed
        _shoot_alive = [
            m for mid in game_state.get("squad_models", {}).get(squad_id, [])  # get allowed
            if (m := _shoot_mc.get(mid)) is not None
        ]
        # `esid not in units_cache` vient d'être écarté juste au-dessus (slot d'ennemi
        # mort = contrat du masque) : l'entrée existe, les deux `is not None` qui
        # suivaient étaient morts — et le second aurait sauté le contrôle « verrouillé
        # par un allié », donc ouvert un slot de tir interdit.
        _shoot_elig: List[Tuple[int, str]] = [
            (slot_i, esid)
            for slot_i, esid in enumerate(enemy_slot_ids)
            if esid is not None
            and esid in units_cache
            # Ennemi hors table (réserves 20.01) : intirable
            and entry_is_on_battlefield(units_cache[esid])
            and not _target_locked_by_ally(
                units_cache, units_cache[esid], squad_id, our_player, ez, game_state
            )
        ]
        # Stocker pour que shoot_weapon_sel_open_slots évite de recalculer alive + elig.
        game_state["_shoot_pass_cache"] = (squad_id, _shoot_alive, [esid for _, esid in _shoot_elig])
        if shooting_type is not None:
            for slot_i, esid in _shoot_elig:
                can_any_hit = False
                for m in _shoot_alive:
                    # Toute arme SELECTIONNABLE sous ce type de tir suffit — pas seulement
                    # `selectedRngWeaponIndex`, qui vaut 0 pour toute la partie en gym et
                    # rendait le masque aveugle aux autres armes de la figurine.
                    for widx in squad_model_shootable_weapon_indices(
                        game_state, squad_id, m, shooting_type
                    ):
                        if _model_can_shoot_target_with_weapon(game_state, m, esid, widx):
                            can_any_hit = True
                            break
                    if can_any_hit:
                        break
                if can_any_hit:
                    mask[SQUAD_ACTION_SHOOT_SLOT_BASE + slot_i] = 1
        # 10.02 / 10.07 : le tir INDIRECT est un SECOND type jouable dans le meme etat, pas une
        # variante du premier. Son masque est donc calcule a part, avec le type indirect en
        # vigueur — c est lui qui ouvre le ciblage sans ligne de vue, et c est tout l interet du
        # choix. Le calculer avec `shooting_type` (le defaut) aurait rendu les deux blocs
        # identiques, donc l action indirecte inutile.
        if SHOOTING_TYPE_INDIRECT in eligible_squad_shooting_types(game_state, squad_id):
            for slot_i, esid in _shoot_elig:
                if _squad_can_shoot_target_under_type(
                    game_state, squad_id, esid, SHOOTING_TYPE_INDIRECT
                ):
                    mask[SQUAD_ACTION_SHOOT_INDIRECT_SLOT_BASE + slot_i] = 1
        mask[SQUAD_ACTION_WAIT] = 1

    # --- Charge phase: un slot par cible de charge declarable (11.02) ---
    elif phase == "charge":
        # V11 §9 P3-2 — CIBLE : un slot est ouvert ssi la cible qu'il designe est declarable
        # (`charge_check_eligibility`, la MEME fonction que le commit `squad_charge` re-verifie).
        # Le masque dit donc « qui je peux charger », la ou il ne disait que « je peux charger ».
        # Aucune action « charge sans cible » : 11.02 conditionne la declaration a la presence
        # d'au moins un ennemi a 12" — sans cible, l'unite ne declare rien et seul WAIT reste.
        #
        # Pas de garde de troncature ici, contrairement a la melee : la melee confronte DEUX
        # sources (le pool 12.05 et le mapping de slots), donc une cible legale peut n'avoir
        # aucun slot. Ici la seule source des candidats EST le mapping — une escouade ennemie
        # sans slot est deja loguee par `_refresh_enemy_slot_mapping`, en amont et une seule fois.
        # 11.02.2 puis 11.04 — LE JET D'ABORD, LES CIBLES ENSUITE. L'activation d'une escouade en
        # phase de charge vaut declaration (11.02.1) : le 2D6 est jete ici, une fois, et les slots
        # ne s'ouvrent que sur les cibles que CE jet permet d'atteindre. Le commit relit la meme
        # valeur memorisee, donc masque et execution ne peuvent pas diverger.
        #
        # Ce qui a change le 2026-08-11 : le jet avait lieu APRES le choix de la cible et le
        # masque ouvrait tout ce qui etait a 12", si bien que l'agent declarait a l'aveugle.
        # Mesure sur le step.log du meme jour (494 charges) : 41 % des declarations visaient une
        # cible a 9" ou plus, quand un 2D6 n'atteint 9 que 27,8 % du temps ; mediane des ratees
        # a 9", des reussies a 5". Le chemin PvP/PvE, lui, etait deja conforme.
        from engine.phase_handlers.charge_handlers import (
            charge_roll_for_activation, charge_target_is_reachable,
        )

        _charge_roll = charge_roll_for_activation(game_state, squad_id)
        _reachable_slots: list = []
        for slot_i, esid in enumerate(enemy_slot_ids[:SQUAD_ACTION_CHARGE_SLOT_COUNT]):
            if esid is None or esid not in units_cache:
                continue
            # UN SEUL oracle, celui du commit (`charge_build_valid_plan`) : il porte a la fois
            # l'eligibilite 11.02.1 (les 12" en ligne directe, qu'il teste en tete) et
            # l'atteignabilite 11.04 par le jet. Pre-tester `charge_check_eligibility` ici
            # doublerait l'appel pour toute cible declarable sans changer un seul verdict.
            if charge_target_is_reachable(game_state, squad_id, str(esid), _charge_roll):
                mask[SQUAD_ACTION_CHARGE_SLOT_BASE + slot_i] = 1
                _reachable_slots.append(slot_i)
        # Slots de paires : ouverts ssi les deux cibles individuelles sont chacune declarables.
        # Parite masque/commit : le commit verifiable l'atteignabilite de chaque cible ; ici on
        # n'ouvre que les paires dont les deux membres passent deja le meme oracle. Une paire
        # geometriquement impossible (les deux cibles exigent des positions incompatibles) sera
        # rejetee au commit avec charge_fail, comme un jet insuffisant — c'est le bon comportement.
        if len(_reachable_slots) >= 2:
            from engine.macro_intents import charge_pair_encode
            for _ii in range(len(_reachable_slots)):
                for _jj in range(_ii + 1, len(_reachable_slots)):
                    _pi = charge_pair_encode(_reachable_slots[_ii], _reachable_slots[_jj])
                    mask[SQUAD_ACTION_CHARGE_PAIR_SLOT_BASE + _pi] = 1
        # 11.02.3 « if you still want to » : renoncer apres le jet est un choix legal, et c'est
        # le seul qui reste quand le jet n'atteint rien.
        mask[SQUAD_ACTION_WAIT] = 1

    # --- Fight phase: un slot par cible de melee eligible (12.05), ou « combat a vide » ---
    elif phase == "fight":
        # Parite masque/commit : le bit FIGHT reflete EXACTEMENT le pool de selection 12.04
        # (`fight_v11_current_pool`), la MEME source que le commit (`_process_squad_action` ->
        # squad_fight, qui verifie `squad_id in fight_v11_current_pool` sous garde
        # `fight_subphase == "fight"`). `_squad_is_in_fight` etait une 3e copie divergente de la
        # regle d eligibilite (engaged-now + charge, SANS le snapshot `engaged_at_fight_step_start`
        # de 12.04) : une unite engagee au debut de l etape mais desengagee par la mort de son
        # ennemi restait dans le pool tout en se voyant masquer FIGHT -> seul WAIT, qui ne clot pas
        # son eligibilite -> boucle infinie. Le pool est la source unique. Le snapshot n existe que
        # pendant la sous-phase FIGHT (poppe en fin d etape) et `fight_v11_current_pool` le lit via
        # require_key : d ou la garde de sous-phase, comme le commit l exige — pas de `.get()` de
        # contournement.
        from engine.phase_handlers.fight_handlers import (
            _fight_build_valid_target_pool,
            _fight_v11_engaged_now,
            fight_v11_current_pool,
        )
        if (
            game_state.get("fight_subphase") == "fight"
            and squad_id in fight_v11_current_pool(game_state)
        ):
            # V11 §9 P3-1 — CIBLE : le pool 12.05 (`_fight_build_valid_target_pool`) est la MEME
            # source que le commit (`_process_squad_action` -> squad_fight), qui refuse une cible
            # hors pool. Un slot est ouvert ssi l'escouade qu'il designe y figure : le masque dit
            # donc exactement « qui je peux frapper », la ou il ne disait que « je peux frapper ».
            unit = require_unit_by_id(game_state, squad_id)
            fight_targets = set(str(t) for t in _fight_build_valid_target_pool(game_state, unit))
            opened = 0
            for slot_i, esid in enumerate(enemy_slot_ids[:SQUAD_ACTION_FIGHT_SLOT_COUNT]):
                if esid is not None and str(esid) in fight_targets:
                    mask[SQUAD_ACTION_FIGHT_SLOT_BASE + slot_i] = 1
                    opened += 1
            if opened == 0:
                # Pool vide sur la position actuelle. En overrun 12.06 (a charge, non engagee),
                # le commit execute d abord une pile-in avant de tester le pool — le masque doit
                # reflechir l etat POST-pile-in pour rester en parite masque/commit.
                if not fight_targets and not _fight_v11_engaged_now(game_state, unit):
                    ov_plan = _fight_overrun_pile_in_plan(game_state, squad_id)
                    if ov_plan is not None:
                        from engine.spatial_relations import (
                            get_engagement_zone as _gez,
                            unit_entries_within_engagement_zone as _uiez,
                        )
                        models_cache = game_state.get("models_cache", {})  # get allowed
                        ez = _gez(game_state)
                        for slot_i, esid in enumerate(enemy_slot_ids[:SQUAD_ACTION_FIGHT_SLOT_COUNT]):
                            if esid is None:
                                continue
                            target_entry = units_cache.get(str(esid))
                            if target_entry is None or not entry_is_on_battlefield(target_entry):
                                continue
                            if any(
                                _uiez(
                                    _synth_model_entry(
                                        game_state, squad_id, models_cache[mid], c, r, level=lv
                                    ),
                                    target_entry, ez,
                                )
                                for mid, c, r, lv in ov_plan
                                if mid in models_cache
                            ):
                                mask[SQUAD_ACTION_FIGHT_SLOT_BASE + slot_i] = 1
                                opened += 1
                if opened == 0:
                    if fight_targets:
                        # Slots tous occupes par des ennemis hors EZ : meme infra que le elif
                        # ci-dessous (cibles legales mais infrappables faute de slot). Ne pas
                        # ouvrir FIGHT_NO_TARGET — le commit trouverait des cibles et crasherait.
                        from engine.game_utils import add_debug_file_log
                        add_debug_file_log(
                            game_state,
                            f"[SLOTS] escouade {squad_id} : {len(fight_targets)} cibles de melee "
                            f"12.05 mais 0 slot ennemi mappe — cible(s) infrappable(s).",
                        )
                    else:
                        # Aucune cible meme apres pile-in overrun : combat a vide (12.04/12.06).
                        # L'escouade DOIT pouvoir se declarer, sans quoi elle resterait eligible
                        # sans action et la sous-phase ne se draine jamais.
                        mask[SQUAD_ACTION_FIGHT_NO_TARGET] = 1
            elif opened < len(fight_targets):
                # Une cible legale sans slot serait INFRAPPABLE : troncature silencieuse interdite.
                from engine.game_utils import add_debug_file_log

                add_debug_file_log(
                    game_state,
                    f"[SLOTS] escouade {squad_id} : {len(fight_targets)} cibles de melee 12.05 "
                    f"pour {opened} slot(s) ennemi(s) mappe(s) — cible(s) infrappable(s).",
                )
        else:
            mask[SQUAD_ACTION_WAIT] = 1

    # --- Other phases (command/deployment) ---
    else:
        mask[SQUAD_ACTION_WAIT] = 1

    _log_mask("built")
    return mask


# ============================================================================
# ENEMY SLOT MAPPING (squad_multi_figurines.md PR4 4d ; V11 §0.30 T-E)
# ============================================================================
# Un slot = une action de tir (`SQUAD_ACTION_SHOOT_SLOT_BASE + i`) ET la ligne `i` du tenseur
# ennemi de l'observation : les deux DOIVENT decrire la meme escouade (invariant D1).
#
# ⚠️ HISTORIQUE — le defaut que cette section corrige (V11_entity_encoder_pointer.md §1.1) :
# le mapping etait fige a 5 slots a l'init et n'etait JAMAIS recalcule. Mesure sur les rosters
# reels : 9 resets sur 10 comptent au moins 6 escouades d'un cote, si bien qu'une escouade
# ennemie etait ABSENTE de l'observation et IMPOSSIBLE a prendre pour cible pendant toute la
# partie ; et quand une escouade mappee mourait, son slot restait vide DEFINITIVEMENT au lieu
# d'etre rendu a celle qui n'en avait pas. Plafond silencieux, jamais logue.
#
# Depuis T-E : K = SQUAD_ACTION_SHOOT_SLOT_COUNT (20, au-dessus du maximum mesure), les slots
# LIBERES sont reattribues, et tout depassement est LOGUE. La tete pointeur (ai/pointer_policy)
# rend le nombre de slots gratuit en parametres : c'est ce qui permet de le dimensionner sur le
# pire cas au lieu de le rogner.
#
# STABILITE : le slot d'une escouade VIVANTE deja mappee ne change jamais. C'est ce dont
# l'invariant D1 a besoin — l'agent ne doit pas voir « slot 2 » designer deux escouades
# differentes d'un step a l'autre sans raison. Une reattribution n'a lieu que sur un slot
# LIBRE (jamais attribue, ou libere par une escouade morte).


def _enemy_threat_order(
    game_state: Dict[str, Any], sids: List[str]
) -> List[str]:
    """Trie des escouades par menace DECROISSANTE (HP total x OC total), tie-break deterministe.

    Le tie-break est l'ordre d'identifiant (et non l'ordre d'iteration d'un dict) : deux etats
    identiques donnent le meme mapping, condition d'un apprentissage reproductible.
    """
    units_cache = game_state.get("units_cache", {})  # get allowed
    squad_models = game_state.get("squad_models", {})  # get allowed
    models_cache = game_state.get("models_cache", {})  # get allowed
    scored: List[Tuple[str, float, int]] = []
    for idx, sid in enumerate(sorted(sids, key=str)):
        entry = units_cache[sid]
        hp_total = int(entry.get("HP_CUR", 0))  # get allowed
        oc_total = int(entry.get("OC_TOTAL", 0))  # get allowed
        if oc_total == 0:
            for mid in squad_models.get(sid, []):  # get allowed
                m = models_cache.get(mid)
                if m is not None:
                    oc_total += int(m.get("OC", 0))  # get allowed
        scored.append((str(sid), float(hp_total) * float(oc_total), idx))
    scored.sort(key=lambda t: (-t[1], t[2]))
    return [sid for sid, _threat, _idx in scored]


def init_enemy_slot_mapping(game_state: Dict[str, Any], our_player: int) -> None:
    """Construit le mapping a l init de partie. Idempotent.

    Cle stockee : game_state[f"enemy_slot_mapping_p{our_player}"] = [sid_or_None, ...] de
    longueur SQUAD_ACTION_SHOOT_SLOT_COUNT. Les slots sont attribues par menace decroissante.
    """
    cache_key = f"enemy_slot_mapping_p{int(our_player)}"
    if cache_key in game_state:
        return
    game_state[cache_key] = [None] * SQUAD_ACTION_SHOOT_SLOT_COUNT
    _refresh_enemy_slot_mapping(game_state, our_player)


def _refresh_enemy_slot_mapping(game_state: Dict[str, Any], our_player: int) -> None:
    """Libere les slots des escouades mortes et donne un slot a celles qui n'en ont pas.

    Deux proprietes, non negociables :
    - une escouade VIVANTE deja mappee GARDE son slot (stabilite de l'invariant D1) ;
    - une escouade vivante SANS slot en recoit un des qu'un slot est libre, par menace
      decroissante. Sans cela, elle reste invisible et intirable pour toute la partie (§1.1).

    Un depassement de K est LOGUE, jamais silencieux (§11).
    """
    cache_key = f"enemy_slot_mapping_p{int(our_player)}"
    mapping: List[Optional[str]] = game_state[cache_key]
    units_cache = game_state.get("units_cache", {})  # get allowed
    # Escouade morte (absente de units_cache) ou hors table (sentinelle -1/-1) : slot libéré.
    for slot_i, sid in enumerate(mapping):
        if sid is not None and (
            sid not in units_cache or not entry_is_on_battlefield(units_cache[sid])
        ):
            mapping[slot_i] = None
    mapped = {sid for sid in mapping if sid is not None}
    unmapped = [
        str(sid)
        for sid, e in units_cache.items()
        if int(e["player"]) != int(our_player)
        and str(sid) not in mapped
        and entry_is_on_battlefield(e)
    ]
    if not unmapped:
        return
    free_slots = [i for i, sid in enumerate(mapping) if sid is None]
    for slot_i, sid in zip(free_slots, _enemy_threat_order(game_state, unmapped)):
        mapping[slot_i] = sid
    overflow = len(unmapped) - len(free_slots)
    if overflow > 0:
        from engine.game_utils import add_debug_file_log

        add_debug_file_log(
            game_state,
            f"[SLOTS] joueur {int(our_player)} : {len(mapped) + len(unmapped)} escouades "
            f"ennemies pour {SQUAD_ACTION_SHOOT_SLOT_COUNT} slots — {overflow} escouade(s) "
            f"sans slot : invisibles dans l'observation et intirables.",
        )


def get_enemy_slot_mapping(
    game_state: Dict[str, Any], our_player: int
) -> List[Optional[str]]:
    """Mapping courant slot -> escouade ennemie. Source UNIQUE du masque, de l'obs et du decoder.

    Init lazy au premier appel, puis rafraichi : les slots des escouades mortes sont rendus, et
    toute escouade vivante sans slot en recoit un (cf. `_refresh_enemy_slot_mapping`).
    """
    cache_key = f"enemy_slot_mapping_p{int(our_player)}"
    if cache_key not in game_state:
        init_enemy_slot_mapping(game_state, our_player)
    else:
        _refresh_enemy_slot_mapping(game_state, our_player)
    units_cache = game_state.get("units_cache", {})  # get allowed
    raw = game_state[cache_key]
    return [sid if (sid is not None and sid in units_cache) else None for sid in raw]


def deployed_friendly_squad_ids(game_state: Dict[str, Any], our_player: int) -> List[str]:
    """Escouades de `our_player` PRESENTES sur le champ de bataille, triees par identifiant.

    SOURCE UNIQUE du peuplement des lignes alliees de l'observation ET du mapping de slots
    d'activation (`get_ally_slot_mapping`). Deux derivations du meme predicat divergeraient en
    silence — c'est le motif JUMEAU du depot.

    Le filtre « sur le champ de bataille » (`entry_is_on_battlefield`, jumelle exacte de
    `deployed_on_turn is not None` cote unite) n'est pas un confort :
    03.04 definit l'engagement range comme une aire DU CHAMP DE BATAILLE, et toutes les unites
    non posees partagent la sentinelle (-1,-1). Sans lui, leurs empreintes se recouvrent et la
    primitive d'engagement les declare mutuellement engagees (mesure §0.40 point 5 : `engaged=1`,
    `n_in_enemy_ez=6` sur une escouade absente de la table).
    """
    units_cache = require_key(game_state, "units_cache")
    player_int = int(our_player)
    result: List[str] = []
    for sid, entry in units_cache.items():
        if int(require_key(entry, "player")) != player_int:
            continue
        if not entry_is_on_battlefield(entry):
            continue
        result.append(str(sid))
    result.sort(key=str)
    return result


def get_ally_slot_mapping(
    game_state: Dict[str, Any], our_player: int, active_squad_id: str
) -> List[Optional[str]]:
    """Mapping slot -> escouade ALLIEE. Source UNIQUE de l'obs, du masque et du decodeur.

    Jumeau de `get_enemy_slot_mapping`, et pour la meme raison : depuis V11 §0.48 element L2,
    l'action `ACTIVATE_SLOT_i` designe l'escouade a activer, donc la ligne `i` du tenseur
    ALLIE. Les desolidariser ferait pointer l'action et l'observation sur deux escouades
    differentes sans que rien ne leve — invariant D1, cote allie.

    LIGNE 0 = l'escouade ACTIVE. C'est un contrat de l'observation, pas une convention de tri :
    l'encodeur lit ce slot comme « moi ». Le mapping ne peut donc pas etre un cache persistant
    comme celui des ennemis — il DEPEND de l'escouade active, et se recalcule a chaque appel.

    Rangs 1..K-1 : les autres escouades presentes, par identifiant. L'ordre par IDENTIFIANT (et
    non par ordre du pool d'activation) est ce qui rend le slot STABLE d'un step a l'autre a
    active constante : un pool se vide au fil des activations, donc s'en servir ferait permuter
    les slots sans qu'aucune escouade n'ait bouge. Ce que D1 demande, c'est UN ordre partage et
    deterministe ; la stabilite tranche entre les candidats.

    Une escouade PAS ENCORE POSEE (reserves strategiques 20.01/20.04) n'a pas de slot : elle
    n'a pas de ligne d'observation (cf. `deployed_friendly_squad_ids`), et un slot d'action sans
    ligne observee serait un choix a l'aveugle. Elle reste activable quand elle devient la tete
    du pool, qui occupe le slot 0 quoi qu'il arrive.
    """
    active_sid = str(active_squad_id)
    others = [sid for sid in deployed_friendly_squad_ids(game_state, our_player) if sid != active_sid]
    if len(others) > K_ALLY_SLOTS - 1:
        from engine.game_utils import add_debug_file_log

        add_debug_file_log(
            game_state,
            f"[SLOTS] joueur {int(our_player)} : {len(others) + 1} escouades alliees pour "
            f"{K_ALLY_SLOTS} slots — les dernieres ne sont ni observees ni activables.",
        )
    slots: List[Optional[str]] = [active_sid]
    slots.extend(others[: K_ALLY_SLOTS - 1])
    slots.extend([None] * (K_ALLY_SLOTS - len(slots)))
    return slots


def _coherency_seat_is_muet(game_state: Dict[str, Any], player: int) -> bool:
    """Siege muet = ni agent gym ni joueur humain : tranche automatiquement sans designaton.

    Gym : les DEUX sieges repondent par le masque → jamais muet.
    PvP : player_types["n"] == "human" pour les deux → jamais muet.
    PvE bot : player_types["2"] == "ai" → muet (bot tranché par critere géométrique).
    """
    if bool(game_state.get("gym_training_mode", False)):
        return False
    player_types = require_key(game_state, "player_types")
    return player_types.get(str(player)) == "ai"


def _squad_owner_player(game_state: Dict[str, Any], squad_id: str) -> int:
    """Joueur proprietaire d'une escouade, lu dans units_cache (source canonique)."""
    entry = game_state.get("units_cache", {}).get(str(squad_id))  # get allowed
    if entry is None:
        raise KeyError(f"_squad_owner_player: {squad_id} absent de units_cache")
    return int(require_key(entry, "player"))


def arm_next_coherency_pending(game_state: Dict[str, Any]) -> bool:
    """Arme la prochaine escouade de la queue coherency, ou purge si vide.

    Verifie que l'escouade suivante est encore incoherente avant d'armer (une escouade
    coherente sans retrait est ignoree). Retourne True si un pending a ete arme.
    """
    queue: List[str] = game_state.get("pending_coherency_removal_queue", [])  # get allowed
    while queue:
        squad_id = queue.pop(0)
        if not validate_squad_coherency(game_state, squad_id):
            alive = _coherency_alive(game_state, squad_id)
            if len(alive) > 1:
                game_state["pending_coherency_removal"] = {"squad_id": squad_id}
                return True
    game_state.pop("pending_coherency_removal_queue", None)
    game_state.pop("pending_coherency_removal", None)
    return False


def _coherency_alive(game_state: Dict[str, Any], squad_id: str) -> List[str]:
    """Figurines vivantes d'une escouade, dans l'ordre de _squad_models_for_observation."""
    from engine.observation_builder import ObservationBuilder
    models_cache = game_state.get("models_cache", {})  # get allowed
    squad_models_list = game_state.get("squad_models", {}).get(squad_id, [])  # get allowed
    alive = [m for m in squad_models_list if m in models_cache]
    if not alive:
        return []
    # Ordre IDENTIQUE a l'observation pour que COHERENCY_SLOT_BASE + i designe la ligne i.
    unit = require_unit_by_id(game_state, squad_id)
    squad_defence: tuple = (
        int(require_key(unit, "HP_MAX")),
        int(require_key(unit, "T")),
        int(unit.get("ARMOR_SAVE", 7)),  # get allowed
        int(unit.get("INVUL_SAVE", 7)),  # get allowed
    )
    return ObservationBuilder._squad_models_for_observation(alive, models_cache, squad_defence)


def end_of_turn_regain_coherency_all_squads(
    game_state: Dict[str, Any],
) -> Dict[str, List[str]]:
    """Etape End of Turn — REGAINING COHERENCY (03.03), sur TOUTES les escouades.

    « In the End of Turn step of each player's turn, if one or more units on the battlefield
    are not in coherency, those units' controlling players must remove models from them, one at
    a time, until they are in coherency again. Models removed in this way are destroyed, but
    they do not trigger rules that apply when a model is destroyed. »

    Les DEUX joueurs sont traites : la regle vise « units on the battlefield », pas les seules
    unites du joueur dont le tour s'acheve.

    Sièges muets (bot PvE, cf. `_coherency_seat_is_muet`) : tranchés par le critère géométrique
    existant (figurine la plus éloignée du centroïde). Retrait immédiat, sans attente.
    Sièges actifs du joueur COURANT (agent gym, joueur humain PvP) : l'escouade est ajoutée à
    la queue `pending_coherency_removal_queue`. `arm_next_coherency_pending` arme le premier
    pending. Sièges actifs de l'ADVERSAIRE : résolus géométriquement, car le flux courant
    n'a pas de mécanisme pour céder la main à l'adversaire en milieu de progression de phase.
    Les retraits auto sont retournés pour journalisation immédiate (fight_handlers) ; les
    retraits manuels sont journalisés un par un lors de la résolution.

    Retourne {squad_id: [model_ids retires]} pour les escouades résolues AUTOMATIQUEMENT.
    """
    squad_models = require_key(game_state, "squad_models")
    current_player = int(require_key(game_state, "current_player"))
    removed_by_squad: Dict[str, List[str]] = {}
    queue: List[str] = []
    # Snapshot trie : `destroy_model` mute `squad_models`/`models_cache` sous l'iteration, et
    # l'ordre doit etre deterministe (rejouabilite des episodes / replays).
    for squad_id in sorted(squad_models.keys()):
        if validate_squad_coherency(game_state, squad_id):
            continue
        alive = [m for m in squad_models[squad_id] if m in game_state.get("models_cache", {})]  # get allowed
        if len(alive) <= 1:
            continue
        try:
            owner = _squad_owner_player(game_state, squad_id)
        except KeyError:
            continue  # escouade hors table (réserves) — pas encore sur le champ
        if _coherency_seat_is_muet(game_state, owner) or owner != current_player:
            removed = end_of_turn_coherency_removal(game_state, squad_id)
            if removed:
                removed_by_squad[squad_id] = removed
        else:
            queue.append(squad_id)
    if queue:
        game_state["pending_coherency_removal_queue"] = queue
        arm_next_coherency_pending(game_state)
    return removed_by_squad


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


def resolve_hit_reroll_ability(
    attacker_unit: Optional[Dict[str, Any]], cause: Optional[str]
) -> Optional[str]:
    """Nom d AFFICHAGE de la capacite qui a ouvert une relance de TOUCHE, ou None.

    JUMEAU du bloc `woundAbility` des deux rollers, extrait en fonction parce qu il a deux
    appelants (tir et melee) : le laisser inline aurait produit deux copies, et c est
    exactement ainsi que le tir et la melee divergent dans ce depot.

    Deux causes possibles, rendues par `attack_sequence.roll_attack_pool` :
      - `hit_1`        : capacite de DATASHEET (`reroll_1_tohit_fight`) -> nom de la regle SOURCE ;
      - `hit_any_fail` : Oath of Moment, capacite de FACTION -> aucune regle d unite a
        interroger, d ou la constante `OATH_ABILITY_DISPLAY_NAME`.

    Sans ce nom, `step.log` n affiche rien : le log dirait que la relance etait POSSIBLE,
    jamais qu elle a EU LIEU — et l analyzer ne peut pas compter l usage d une capacite qu il
    ne voit pas.
    """
    from engine.game_state import OATH_ABILITY_DISPLAY_NAME

    if not cause or attacker_unit is None:
        return None
    if cause == "hit_any_fail":
        return OATH_ABILITY_DISPLAY_NAME
    if cause == "hit_1":
        return get_source_unit_rule_display_name_for_effect(
            attacker_unit, "reroll_1_tohit_fight"
        )
    raise ValueError(
        f"resolve_hit_reroll_ability: cause de relance de touche inconnue {cause!r}. "
        f"Toute cause produite par `roll_attack_pool` doit etre nommee ici, sinon la relance "
        f"disparait du log."
    )


def resolve_wound_reroll_ability(
    attacker_unit: Optional[Dict[str, Any]],
    cause: Optional[str],
    *,
    reroll_1_towound: bool,
    reroll_towound_on_objective: bool,
) -> Optional[str]:
    """Nom d AFFICHAGE de la capacite qui a ouvert une relance de BLESSURE, ou None.

    MIROIR EXACT de `resolve_hit_reroll_ability`, et extrait pour la meme raison : deux
    appelants (tir et melee). Le bloc vivait inline dans le seul roller de TIR — la melee
    consommait bien `hitRerollCause` mais laissait `woundRerollCause` sur le record, si bien
    qu une relance de blessure en melee n atteignait aucun log. C est le motif d echec n°1 du
    depot, exactement celui que cette extraction empeche de reapparaitre.

    Trois causes possibles, rendues par `attack_sequence.roll_attack_pool` :
      - `wound_1`         : capacite d unite `reroll_1_towound` -> nom de la regle SOURCE ;
      - `wound_any_fail`  : capacite d unite `reroll_towound_target_on_objective` -> idem ;
      - `twin_linked`     : regle d ARME 24.38, deja identifiee par ailleurs -> aucun nom.

    Les deux booleens disent laquelle des deux capacites d unite etait OUVERTE sur cet intent :
    la cause seule ne suffit pas a nommer l effet source.
    """
    if not cause or attacker_unit is None:
        return None
    if cause == "twin_linked":
        return None
    if cause == "wound_1":
        return (
            get_source_unit_rule_display_name_for_effect(attacker_unit, "reroll_1_towound")
            if reroll_1_towound else None
        )
    if cause == "wound_any_fail":
        return (
            get_source_unit_rule_display_name_for_effect(
                attacker_unit, "reroll_towound_target_on_objective"
            )
            if reroll_towound_on_objective else None
        )
    raise ValueError(
        f"resolve_wound_reroll_ability: cause de relance de blessure inconnue {cause!r}. "
        f"Toute cause produite par `roll_attack_pool` doit etre nommee ici, sinon la relance "
        f"disparait du log."
    )


def resolve_oath_effects(
    game_state: Dict[str, Any],
    attacker_unit: Optional[Dict[str, Any]],
    target_sid: Any,
    wound_target: int,
) -> Tuple[bool, int, int]:
    """Les deux effets d Oath sur un intent : `(cible_designee, bonus_blessure, seuil_ajuste)`.

    UNE seule interrogation de `unit_is_oath_target_of` : la relance de touche et le +1 Wound
    posent la MEME question (« cette attaque vise ma cible d Oath ? »), et elle etait evaluee
    deux fois par intent avec les memes arguments. Le +1 Wound y ajoute seulement la clause de
    detachement, portee par `oath_wound_roll_bonus`.

    Le +1 est modelise en ABAISSANT le seuil, comme le couvert modelise son -1 BS en relevant
    le seuil de touche. C est exactement equivalent : la blessure CRITIQUE reste sur un 6 NON
    MODIFIE (`profile.crit_wound_on`, teste sur le de brut) et le 1 non modifie echoue toujours
    (05.02) — les deux sont testes sur le de, pas sur le seuil. PLANCHER A 2 : aucun
    modificateur ne fait reussir un 1.

    Extrait pour la raison qui vaut pour tout ce voisinage : ce prelude vivait a l identique
    dans les deux rollers, plancher compris. Un plancher corrige d un seul cote est exactement
    la panne que ce depot produit le plus souvent.
    """
    # Import PARESSEUX obligatoire : `engine.game_state` importe ce module au niveau module,
    # l importer en tete creerait un cycle (cf. `_manual_roll_intent`).
    from engine.game_state import oath_wound_roll_bonus, unit_is_oath_target_of

    is_oath_target = attacker_unit is not None and unit_is_oath_target_of(
        game_state, attacker_unit, str(target_sid)
    )
    wound_bonus = (
        oath_wound_roll_bonus(game_state, attacker_unit, str(target_sid))
        if is_oath_target and attacker_unit is not None else 0
    )
    adjusted = max(2, wound_target - wound_bonus) if wound_bonus else wound_target
    return is_oath_target, wound_bonus, adjusted


#: Nom d affichage du malus de suppression (Indiscriminate Detonations, chantier 06).
#:
#: CONSTANTE et non `displayName` de roster, parce qu il n y a AUCUNE datasheet a interroger :
#: `hit_roll_malus_suppressed` n est portee par aucune unite — elle est l EFFET du statut
#: `suppressed`, pose sur la VICTIME par l attaquant. Chercher un nom de source sur l unite qui
#: subit le malus ne rendrait jamais rien.
SUPPRESSED_MALUS_DISPLAY_NAME = "Suppressed"


def unit_is_suppressed(game_state: Dict[str, Any], unit_id: Any) -> bool:
    """L unite est-elle SUPPRIMEE (statut chantier 06) ?

    Source unique : `game_state["suppressed_squads"]` — `squad_id -> joueur qui a supprime`. Le
    joueur y est stocke parce que la duree lui appartient (« until the start of YOUR next
    Command phase », Indiscriminate Detonations) : la purge est faite par joueur au debut de SA
    phase de commande (`command_handlers.command_step_start_of_phase`), pas avec les sets de
    tour, qui la couperaient en deux.

    Absente = AUCUNE escouade supprimee, et c'est un etat metier valide, pas une donnee
    manquante : meme regime que `units_fought` / `units_advanced`, les autres tables de suivi de
    ce moteur. `reset` la cree aux deux sites d'initialisation, donc la production ne repose
    jamais sur ce defaut.
    """
    return str(unit_id) in game_state.get("suppressed_squads", {})  # get allowed


def resolve_hit_roll_modifiers(
    game_state: Dict[str, Any],
    attacker_unit: Optional[Dict[str, Any]],
    hit_target: int,
    *,
    is_melee: bool,
) -> Tuple[int, Optional[str], Optional[str]]:
    """Primitive A cote TOUCHE : `(seuil ajuste, nom du bonus, nom du malus)`.

    `clamp(base - bonus + malus, 2, 6)`, exactement comme le prescrit la conception (§5). Le
    modificateur porte sur le SEUIL et jamais sur le de : le 1 non modifie echoue toujours et le
    6 non modifie reste critique (05.01), les deux etant testes sur le de brut par
    `attack_sequence._evaluate_roll`. C est la MEME modelisation que le couvert 13.08 et que le
    +1 de blessure d Oath — trois modificateurs, une seule mecanique.

    Deux effets, un seul site, et c est le point : ils s appliquent au tir COMME a la melee pour
    le malus (« While a unit is suppressed, it has -1 to hit rolls », sans restriction de phase),
    a la melee SEULE pour le bonus (« This unit's melee weapons have +1 to hit rolls »). Les
    ecrire dans chacun des deux rollers ferait exactement le jumeau divergent que ce depot paie
    le plus cher.

    Les noms rendus sont ceux du JOURNAL : ils ne sont resolus que si le modificateur a REELLEMENT
    joue, et le `displayName` du bonus vient de la datasheet source (Might Is Right), jamais d une
    constante recopiee.
    """
    bonus, malus, bonus_name, malus_name = hit_roll_modifier_terms(
        game_state, attacker_unit, is_melee=is_melee
    )
    if not bonus and not malus:
        return hit_target, None, None
    cap = _bonus_malus_cap(game_state)
    return apply_hit_roll_modifiers(hit_target, bonus, malus, cap=cap), bonus_name, malus_name


def hit_roll_modifier_terms(
    game_state: Dict[str, Any],
    attacker_unit: Optional[Dict[str, Any]],
    *,
    is_melee: bool,
) -> Tuple[int, int, Optional[str], Optional[str]]:
    """`(bonus, malus, nom du bonus, nom du malus)` de la Primitive A pour CETTE unite.

    Separe du calcul de seuil parce que les termes sont CONSTANTS sur une activation alors que
    le seuil, lui, se recalcule par arme : l heuristique de choix d arme de melee
    (`_auto_select_cc_weapon_for_fig`) doit noter chaque arme sur le seuil que le moteur
    APPLIQUERA, et les resoudre dans sa boucle relirait les regles d unite a chaque profil.
    """
    bonus_name: Optional[str] = None
    malus_name: Optional[str] = None
    bonus = 0
    malus = 0
    if (
        is_melee
        and attacker_unit is not None
        and _unit_has_rule_effect(attacker_unit, "hit_roll_bonus_fight")
    ):
        bonus = 1
        bonus_name = _get_source_unit_rule_display_name_for_effect(
            attacker_unit, "hit_roll_bonus_fight"
        )
    if attacker_unit is not None and unit_is_suppressed(
        game_state, require_key(attacker_unit, "id")
    ):
        malus = 1
        malus_name = SUPPRESSED_MALUS_DISPLAY_NAME
    return bonus, malus, bonus_name, malus_name


def _bonus_malus_cap(game_state: Dict[str, Any]) -> int:
    """Cap sur le total net des modificateurs de jet, lu dans game_rules (0 = pas de cap)."""
    return int(require_key(require_key(require_key(game_state, "config"), "game_rules"), "bonus_malus_cap"))


def apply_hit_roll_modifiers(hit_target: int, bonus: int, malus: int, *, cap: int = 0) -> int:
    """`clamp(base - net, 2, 6)` avec `net = clamp(bonus - malus, -cap, cap)` si cap > 0.

    Deux lecteurs : la resolution (via `resolve_hit_roll_modifiers`) et l heuristique de choix
    d arme. Recopier la formule chez le second, c est laisser le score diverger du seuil
    reellement joue le jour ou une borne bouge — exactement ce que le `melee_bonus` du Waaagh! a
    deja corrige pour la Force et le nombre d attaques.
    """
    net = bonus - malus
    if cap:
        net = max(-cap, min(cap, net))
    return max(2, min(6, hit_target - net))


def resolve_melee_wound_bonus(
    attacker_unit: Optional[Dict[str, Any]], wound_target: int
) -> Tuple[int, Optional[str]]:
    """Primitive A cote BLESSURE (melee) : `(seuil ajuste, nom du bonus)`. Plancher 2 (05.02).

    JUMEAU de `resolve_oath_effects` pour l autre source de +1 au jet de blessure, et les deux se
    CUMULENT : une escouade menee par un Chaplain qui frappe la cible d un Oath descend de deux
    crans, chacun plafonne par le meme plancher. « This unit's melee weapons have +1 to wound
    rolls » ne parle que de la melee : aucun jumeau au tir, et le site de tir ne l appelle pas.
    """
    if attacker_unit is None or not _unit_has_rule_effect(
        attacker_unit, "wound_roll_bonus_fight"
    ):
        return wound_target, None
    return (
        max(2, wound_target - 1),
        _get_source_unit_rule_display_name_for_effect(
            attacker_unit, "wound_roll_bonus_fight"
        ),
    )


def unit_charge_roll_bonus(game_state: Dict[str, Any], unit_id: str) -> int:
    """Primitive A cote CHARGE : `+1` si l unite porte `charge_roll_bonus`, sinon `0`.

    « This unit has +1 to charge rolls » (Somethin' to Prove, Bigboss). JUMEAU de
    `unit_can_reroll_charge` : meme registre, meme lecture 19.04 (les `UNIT_RULES` de
    l ESCOUADE sont l union en vigueur de ses sources VIVANTES, recalculee a chaque mort), donc
    un Bigboss attache confere bien son bonus a toute l escouade et le lui retire en mourant.
    """
    unit = require_unit_by_id(game_state, str(unit_id))
    return 1 if _unit_has_rule_effect(unit, "charge_roll_bonus") else 0


def stamp_reroll_abilities(
    shot_records: List[Dict[str, Any]],
    attacker_unit: Optional[Dict[str, Any]],
    *,
    reroll_1_towound: bool,
    reroll_towound_on_objective: bool,
) -> None:
    """Traduit les CAUSES de relance en noms d ABILITE sur chaque record. En place.

    `roll_attack_pool` rend une cause (`hit_1`, `wound_any_fail`, `twin_linked`…) ; les logs
    veulent le nom d affichage de la regle qui l a ouverte. Les causes sont CONSOMMEES ici
    (`pop`) : elles ne doivent pas atteindre les consommateurs, qui n en feraient rien.

    Resolution MEMOISEE sur l intent et PARESSEUSE : le nom d affichage n est lu que si une
    relance a REELLEMENT eu lieu (`get_source_unit_rule_display_name_for_effect` exige un
    `displayName` non vide sur la regle source — inutile de l exiger d une unite dont aucune
    relance n a joue).

    Ce bloc vivait a l identique dans les deux rollers, aux noms de variables locales pres, et
    il avait DEJA diverge : la melee posait `wound_1` / `wound_any_fail` dans le roller mais ne
    consommait jamais la cause, si bien qu une relance de blessure en melee n atteignait aucun
    log pendant que le tir la nommait. Les deux `resolve_*_reroll_ability` avaient ete extraits
    pour cela ; la boucle qui les appelle etait restee dupliquee.
    """
    hit_ability_by_cause: Dict[str, Optional[str]] = {}
    wound_ability_by_cause: Dict[str, Optional[str]] = {}
    for record in shot_records:
        hit_cause = record.pop("hitRerollCause", None)  # get allowed : absente = pas de relance
        if hit_cause:
            if hit_cause not in hit_ability_by_cause:
                hit_ability_by_cause[hit_cause] = resolve_hit_reroll_ability(
                    attacker_unit, hit_cause
                )
            hit_ability = hit_ability_by_cause[hit_cause]
            if hit_ability:
                record["hitAbility"] = str(hit_ability)
        wound_cause = record.pop("woundRerollCause", None)  # get allowed : idem
        if not wound_cause:
            continue
        if wound_cause == "twin_linked":
            # [TWIN-LINKED] 24.38 : la relance vient de l ARME, pas d une capacite d unite —
            # `resolve_wound_reroll_ability` rend donc None, et le jet relance s affichait
            # « 2->5 » sans que rien ne dise ce qui l avait ouvert (alors qu une relance de
            # capacite, elle, est nommee). Champ DISTINCT de `woundAbility`, qui est par
            # contrat le nom d une capacite d unite.
            record["woundRerollRule"] = "TWIN-LINKED"
            continue
        if wound_cause not in wound_ability_by_cause:
            wound_ability_by_cause[wound_cause] = resolve_wound_reroll_ability(
                attacker_unit, wound_cause,
                reroll_1_towound=reroll_1_towound,
                reroll_towound_on_objective=reroll_towound_on_objective,
            )
        wound_ability = wound_ability_by_cause[wound_cause]
        if wound_ability:
            record["woundAbility"] = str(wound_ability)


def stamp_wound_bonus_ability(
    shot_records: List[Dict[str, Any]], oath_wound_bonus: int
) -> None:
    """Pose `woundBonusAbility` sur les records qui ont JETE un de de blessure. En place.

    Le +1 au jet de blessure d Oath est un MODIFICATEUR, pas une relance : il n a donc aucune
    cause dans `roll_attack_pool`, et sans ce marqueur le seuil affiche est meilleur sans que
    rien ne dise pourquoi. Champ distinct de `woundAbility` (relance) : les deux peuvent jouer
    sur la meme attaque.

    `oath_wound_bonus` n est ici qu un DRAPEAU : la magnitude est consommee par les appelants
    avant l appel (`wth = max(2, wth - _oath_wound_bonus)`), et le champ jumeau stocke sur
    l intent est un `bool`. Zero ou absent = rien a poser.

    SEULEMENT les attaques qui ont jete un de de blessure : une touche ratee n en jette aucun,
    et [LETHAL HITS] 24.23 blesse automatiquement (`strengthRoll` a None). Attribuer un +1 a un
    de jamais lance ferait dire au log « Wound None(4+) [OATH OF MOMENT] » — le modificateur n a
    modifie que ce qui a ete jete. Verrouille des DEUX cotes (tir et melee).
    """
    if not oath_wound_bonus:
        return
    # Import PARESSEUX obligatoire : `engine.game_state` importe ce module au niveau module,
    # l importer en tete creerait un cycle (cf. `_manual_roll_intent`).
    from engine.game_state import OATH_ABILITY_DISPLAY_NAME

    for record in shot_records:
        if record.get("strengthRoll") is None:  # get allowed : cle absente = touche ratee
            continue
        record["woundBonusAbility"] = OATH_ABILITY_DISPLAY_NAME


def stamp_roll_modifier_abilities(
    shot_records: List[Dict[str, Any]],
    *,
    hit_bonus: Optional[str],
    hit_malus: Optional[str],
    wound_bonus: Optional[str],
) -> None:
    """Pose les MODIFICATEURS de jet de la Primitive A sur chaque record. En place.

    TROIS champs distincts et non un seul : les trois peuvent jouer sur la MEME attaque (une
    escouade menee par un Chaplain, supprimee par un Wartrakk, frappe en melee), et un champ
    unique perdrait alors deux causes sur trois.

    POSE SUR TOUS LES RECORDS, y compris ceux sans de. Ces modificateurs sont des proprietes de
    l ACTIVATION — une regle d unite en vigueur, constante d un bout a l autre de la ligne —
    exactement comme `waaaghMelee`, et le formateur les rend en TAGS DE LIGNE, hors de tout
    segment de jet. C est aussi ce qui les distingue de `woundBonusAbility` juste au-dessus, qui
    decrit UN de et se tait quand ce de n a pas ete lance.

    ⚠️ LE TAG DE LIGNE N EST PAS DECORATIF, c est le seul rendu correct disponible : cote replay,
    `abilityTokensForRoll` (`frontend/src/utils/replayParser.ts`) ne retient QU UNE capacite par
    segment de jet. Un second token accole au segment `Hit` y ecraserait silencieusement le nom
    de la relance de touche.
    """
    for record in shot_records:
        if hit_bonus:
            record["hitRollBonusAbility"] = str(hit_bonus)
        if hit_malus:
            record["hitRollMalusAbility"] = str(hit_malus)
        if wound_bonus:
            record["woundRollBonusAbility"] = str(wound_bonus)
