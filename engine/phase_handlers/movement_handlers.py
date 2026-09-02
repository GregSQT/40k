#!/usr/bin/env python3
"""
movement_handlers.py - tour_de_jeu.md Movement Phase Implementation
Pure stateless functions implementing tour_de_jeu.md movement specification

References: tour_de_jeu.md Section 🏃 MOVEMENT PHASE LOGIC
ZERO TOLERANCE for state storage or wrapper patterns
"""

from typing import (
    AbstractSet, Dict, FrozenSet, List, NamedTuple, Tuple, Set, Optional, Any, Sequence, cast
)
import math
import numpy as np
from collections import deque, OrderedDict
from functools import lru_cache
from .generic_handlers import end_activation, _log_with_context
from shared.data_validation import require_key
from engine.action_log_utils import append_action_log
from engine.combat_utils import (
    calculate_hex_distance,
    normalize_coordinates,
    set_unit_coordinates,
    get_unit_by_id,
    require_unit_by_id,
    get_hex_neighbors,
)
from .shared_utils import (
    ACTION, WAIT, NO, PASS, ERROR, MOVE, FLED,
    enemy_entries_on_battlefield, entries_on_battlefield, entry_footprint,
    build_enemy_adjacent_hexes, update_units_cache_position, translate_squad_to_destination,
    get_unit_position, require_unit_position, require_unit_from_cache,
    update_enemy_adjacent_caches_after_unit_move,
    maybe_resolve_reactive_move,
    build_occupied_positions_set,
    build_enemy_occupied_positions_set,
    compute_candidate_footprint,
    is_footprint_placement_valid, is_placement_valid_with_clearance, wall_blocked_anchors,
    socle_orientation,
    get_engagement_zone,
    get_squad_move_budget, validate_move_plan, _validate_plan_coherency, commit_move,
    get_coherency_subhex, get_cohesion_max_subhex, get_min_neighbors,
    coherency_violation_flags,
    _compute_unit_occupied_hexes, _squad_is_in_enemy_er, squad_is_battle_shocked_in_enemy_er,
    roll_advance_for_squad, unit_is_in_strategic_reserves,
    MovePlan, parse_model_plan_with_orientation, plan_entry_level, plan_entry_model_orientation,
    resolve_model_effective_level,
)
from engine.hex_utils import (
    _hex_center,
    _SEG_TOL,
    ENGAGEMENT_NORM_HEX_WIDTH,
    engagement_minimum_clearance_norm,
    euclidean_edge_clearance_round_round,
    dilate_by_kernel,
    min_distance_between_sets,
    ORIENTATION_STEP_COUNT,
    spread_by_kernel,
    require_base_size,
    require_scalar_base_size,
    round_base_radius_norm,
    socle_is_single_hex,
)
from engine.phase_handlers.geodesic_move import _euclidean_move_field, reachable_multilevel_field
# Bascule UNIQUE de la résolution (`inches_to_subhex <= 1` → géométrie hex). Alias court : ce
# module la lit dans des boucles chaudes (pool d'ancre, éligibilité), pas seulement en préambule.
from engine.spatial_relations import geometry_is_hex as _geometry_is_hex
from engine.hex_union_boundary_polygon import (
    compute_move_preview_mask_loops_world,
    _board_hex_radius_margin,
)
from engine.perf_timing import profile_move_pool_build

# Cache LRU (footprint ∪ géométrie plateau) — même sortie que ``compute_move_preview_mask_loops_world``.
_MASK_LOOP_CACHE_MAX = 64
_mask_loop_cache: "OrderedDict[Tuple[frozenset, float, float], Optional[List[List[Tuple[float, float]]]]]" = OrderedDict()


def _validate_move_orientation(raw_orientation: Any) -> int:
    """Validate a move orientation step from semantic action payload."""
    if isinstance(raw_orientation, bool) or not isinstance(raw_orientation, int):
        raise ValueError(
            f"Move orientation must be an integer in 0..{ORIENTATION_STEP_COUNT - 1}, got {raw_orientation!r}"
        )
    if raw_orientation < 0 or raw_orientation >= ORIENTATION_STEP_COUNT:
        raise ValueError(
            f"Move orientation must be in 0..{ORIENTATION_STEP_COUNT - 1}, got {raw_orientation!r}"
        )
    return raw_orientation


def _sync_move_preview_mask_loops(
    game_state: Dict[str, Any], footprint_zone: Set[Tuple[int, int]]
) -> None:
    """Polygone(s) masque pour le client — évite d’envoyer des milliers de (col,row) en JSON."""
    hr, margin = _board_hex_radius_margin(game_state)
    cache_key = (frozenset(footprint_zone), float(hr), float(margin))
    if cache_key in _mask_loop_cache:
        game_state["move_preview_footprint_mask_loops"] = _mask_loop_cache[cache_key]
        _mask_loop_cache.move_to_end(cache_key)
        return

    loops = compute_move_preview_mask_loops_world(footprint_zone, game_state)
    game_state["move_preview_footprint_mask_loops"] = loops

    _mask_loop_cache[cache_key] = loops
    _mask_loop_cache.move_to_end(cache_key)
    while len(_mask_loop_cache) > _MASK_LOOP_CACHE_MAX:
        _mask_loop_cache.popitem(last=False)

def _move_preview_footprint_span(unit: Dict[str, Any]) -> int:
    """Dimension max d’empreinte (hexes) — rayon des disques UI.

    Le jumeau de `charge_handlers` auquel ce calcul s'alignait était mort et a été supprimé le
    2026-08-05 : cette fonction est désormais la seule implémentation.
    """
    bs = unit["BASE_SIZE"]
    if isinstance(bs, (list, tuple)):
        if not bs:
            raise ValueError(f"BASE_SIZE liste vide pour l'unité {unit.get('id', '?')!r}")
        try:
            return max(int(v) for v in bs)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"BASE_SIZE liste contient des valeurs non-entières : {bs!r}"
            ) from exc
    try:
        return max(1, int(bs))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"BASE_SIZE scalaire invalide : {bs!r}") from exc


def _hex_radius_upper_for_engagement_prune(base_span: int) -> int:
    """Majorant (grille hex) du rayon empreinte depuis l’ancre — borne conservatrice pour la prune."""
    s = max(1, int(base_span))
    return max(1, (s + 1) // 2)


# ── PIERRE TOMBALE — heuristique de destination de l'ancien espace d'actions (2026-07-29) ─────
# Ont vécu ici :
#   `_select_strategic_destination`     4 stratégies (0 = agressif, 1 = tactique, 2 = défensif,
#                                       3 = objectif) qui CHOISISSAIENT la destination à la place
#                                       de l'agent, pour les actions de move 0-3 de l'espace 0-15
#   `_build_objective_distance_cache`   son cache de distances aux objectifs, sans autre client
#
# POURQUOI elles étaient mortes : la refonte spatiale du move (§6.2) a fait de la DESTINATION une
# dimension d'action (1024 cellules de la grille égocentrique). L'agent désigne désormais la
# cellule ; plus rien n'a à la deviner pour lui. Leur unique appelant était `convert_gym_action`,
# décodeur de l'ancien espace, supprimé le même jour (cf. `engine/action_decoder.py`).
#
# ⚠️ NE PAS confondre avec `charge_handlers._select_strategic_destination` : jumeau de nom, autre
# fichier, autre cycle de vie.
# ──────────────────────────────────────────────────────────────────────────────────────────────


def _enemy_items_within_move_engagement_horizon(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    unit_id_str: str,
    mover_player_int: int,
    start_col: int,
    start_row: int,
    move_range: int,
    units_cache: Dict[str, Any],
) -> List[Tuple[Any, Any]]:
    """Ennemis susceptibles d’interagir avec un déplacement depuis ``(start_col, start_row)``.

    Borne conservatrice (distance hex entre **ancres**) :
    ``MOVE + r_m + r_e + engagement_zone + 1``, avec ``r_*`` dérivés du diamètre d’empreinte
    (rayons pris sur les socles RÉELS, sans plafond). Toute destination légale est à ≤ ``MOVE`` pas
    de l’ancre de départ (inégalité triangulaire sur la métrique hex) ; on ajoute les rayons
    car l’engagement teste bord à bord / cellules, pas seulement l’écart entre ancres. Le ``+1``
    couvre l’arrondi hex ↔ espace continu (_hex_center). Exclure au-delà pourrait omettre un
    ennemi encore pertinent → liste sur-approximée, résultat identique à un scan complet.
    """
    ez = get_engagement_zone(game_state)
    mover_r = _hex_radius_upper_for_engagement_prune(_move_preview_footprint_span(unit))
    m = int(move_range)
    horizon_without_enemy_r = m + mover_r + int(ez) + 1

    out: List[Tuple[Any, Any]] = []
    for eid, ce in enemy_entries_on_battlefield(units_cache, mover_player_int, exclude_id=unit_id_str):
        # SPAN RÉEL, sans plafond. `min(span, max_base_size_hex)` RÉTRÉCISSAIT l'horizon : un
        # WarTrakk à x10 (span 41, plafond 35) donnait un rayon de 18 au lieu de 21, donc un
        # ennemi pertinent élagué, une ancre offerte par le masque et refusée par la validation
        # (qui, elle, voit tous les ennemis). Cette prune ne peut se tromper que dans le sens
        # SUR-approximé — c'est ce que sa docstring promet, et un plafond par le HAUT le
        # contredit. Le plafond garde son rôle ailleurs (fenêtres d'observation), pas ici : une
        # donnée aberrante coûterait une fenêtre plus large, jamais un verdict faux.
        e_span = _move_preview_footprint_span(ce)
        e_r = _hex_radius_upper_for_engagement_prune(e_span)
        h = horizon_without_enemy_r + e_r
        # Distance à la figurine la PLUS PROCHE du squad (pas seulement l'ancre) : une escouade
        # multi-fig s'étend bien au-delà de son ancre (ex. 20 Termagants sur ~24 hex), donc un
        # filtre basé sur l'ancre seule omettrait un squad dont une fig est pourtant à portée.
        by_model = ce.get("occupied_hexes_by_model")
        if by_model:
            positions: Any = by_model.values()
        else:
            positions = ((int(require_key(ce, "col")), int(require_key(ce, "row"))),)
        if any(
            calculate_hex_distance(start_col, start_row, int(pc), int(pr)) <= h
            for pc, pr in positions
        ):
            out.append((eid, ce))
    return out


def _unit_has_keyword(unit: Dict[str, Any], keyword_id: str) -> bool:
    """
    Return True if UNIT_KEYWORDS contains keyword_id.

    UNIT_KEYWORDS entries must be objects with a `keywordId` field.

    Comparaison INSENSIBLE À LA CASSE (et aux espaces de bord), comme TOUS les autres lecteurs
    de `keywordId` du moteur (`game_state.py` FLOOR_CAPABLE/HIDEABLE, `shared_utils` compute_hideable,
    `attack_sequence` ANTI-X, `analyzer_config`, et le front `BoardWithAPI`). Le corpus de rosters
    est mixte : `keywordId: "fly"` (16 fichiers) ET `keywordId: "FLY"` (6 fichiers). Une égalité
    stricte perdait SILENCIEUSEMENT le keyword des 6 seconds — dont cinq types du roster
    d'entraînement d'ArmageddonAgent. La convention de lecture est donc normalisée ici aussi :
    c'est la lecture qui portait l'exception, pas la donnée.
    """
    unit_keywords = unit.get("UNIT_KEYWORDS")
    if unit_keywords is None:
        return False
    if not isinstance(unit_keywords, list):
        raise ValueError(
            f"UNIT_KEYWORDS must be a list for unit {unit.get('id')}, got {type(unit_keywords).__name__}"
        )
    for keyword_entry in unit_keywords:
        if not isinstance(keyword_entry, dict):
            raise ValueError(
                f"UNIT_KEYWORDS entries must be objects for unit {unit.get('id')}: {keyword_entry!r}"
            )
        # Même traitement que l'entrée non-objet ci-dessus : une entrée sans `keywordId` (ou nul)
        # est une donnée cassée, pas un keyword absent. L'avaler en silence ferait répondre
        # « cette unité ne vole pas » à une question à laquelle la donnée ne permet pas de
        # répondre. C'est aussi ce que font les autres lecteurs (`require_key` dans
        # `shared_utils.compute_hideable`, `game_state.py`) et le chargeur `ai/unit_registry.py`.
        if keyword_entry.get("keywordId") is None:
            raise ValueError(
                f"UNIT_KEYWORDS entries must carry a non-null keywordId for unit "
                f"{unit.get('id')}: {keyword_entry!r}"
            )
        keyword_value = keyword_entry["keywordId"]
        if str(keyword_value).strip().lower() == str(keyword_id).strip().lower():
            return True
    return False


def _unit_is_ai_controlled(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """L'unité est-elle pilotée par le modèle (gym d'entraînement, ou joueur 2 en PvE) ?

    Aucune déclaration humaine ne peut lui parvenir : c'est un point de choix d'agent
    (``arm_fly_declaration_decision``) qui lui demande sa déclaration 21.03, là où un humain
    utilise le toggle ``movement_set_fly_mode_handler`` / ``charge_set_fly_mode_handler``.

    Privée : un seul appelant, ``_fly_declaration_due_unit``, dans ce module.
    """
    is_gym = bool(game_state.get("gym_training_mode", False))
    is_pve = bool(game_state.get("pve_mode", False)) or bool(game_state.get("is_pve_mode", False))
    return is_gym or (is_pve and int(require_key(unit, "player")) == 2)


class _FlyPhase(NamedTuple):
    """Ce qu'une phase résolvant un mouvement de 21.03 met en jeu — champs NOMMÉS, jamais un
    tuple positionnel : les deux clés sont des `str`, les permuter ne casserait rien et écrirait
    la déclaration de move dans le set de la charge, en silence.

    - ``is_charge`` : le mouvement en cours est-il celui de la phase de charge ?
    - ``declared_key`` : set des escouades AYANT déclaré le vol pour ce mouvement.
    - ``resolved_key`` : set de celles à qui la question a DÉJÀ été posée (voir ⚠️ ci-dessous).
    """

    is_charge: bool
    declared_key: str
    resolved_key: str


#: Phase moteur → `_FlyPhase`.
#: 21.03 énumère EXACTEMENT les mouvements couverts : « a normal, advance, fall-back or charge
#: move ». Un pile-in ou une consolidation (12) n'y figurent pas et ne peuvent donc pas prendre les
#: airs — d'où l'absence volontaire de clé pour ces phases (et non une valeur par défaut permissive).
#:
#: Table réellement CONSOMMÉE des trois côtés : le drapeau `charge` par `_fly_traversal_active`
#: (qui en déduit le mouvement de la phase en cours), le set de déclaration par
#: `took_to_the_skies`, le set de résolution par `arm_fly_declaration_decision`.
#: La corriger a donc un effet — c'est la seule description du couplage phase / mouvement / sets.
#:
#: ⚠️ DEUX sets et non un : « ne pas déclarer » est un choix, et il laisse le set de déclaration
#: VIDE — indiscernable de « la question n'a pas encore été posée ». Sans le second set, le point
#: de choix se reposerait à chaque construction de masque et l'escouade ne pourrait plus jamais
#: bouger. Les quatre sont remis à zéro par `fly_declaration_reset_state`, qui les DÉRIVE de cette
#: table : ajouter une phase ici suffit, aucun site de reset à mettre à jour à la main.
_TAKE_TO_THE_SKIES_BY_PHASE: Dict[str, _FlyPhase] = {
    # normal / advance / fall-back
    "move": _FlyPhase(False, "units_took_to_skies", "units_fly_declaration_resolved"),
    "charge": _FlyPhase(True, "units_took_to_skies_charge", "units_fly_declaration_resolved_charge"),
}


def _fly_phase_entry(game_state: Dict[str, Any]) -> Optional[_FlyPhase]:
    """Entrée de `_TAKE_TO_THE_SKIES_BY_PHASE` pour la phase EN COURS, ou None hors 21.03.

    Lecture unique de la table depuis l'état : les 4 sites qui en dépendent posaient la même
    expression, chacun avec son propre déballage.
    """
    return _TAKE_TO_THE_SKIES_BY_PHASE.get(str(game_state.get("phase", "")))  # get allowed


def fly_declaration_reset_state() -> Dict[str, Any]:
    """Les sets 21.03 remis à zéro en début de tour, DÉRIVÉS de la table (jamais réénumérés).

    La question « prends-tu les airs ? » vaut pour le mouvement du tour : elle se repose au tour
    suivant. Les oublier gèlerait la déclaration du tour 1 pour toute la partie (une escouade ne
    serait plus jamais interrogée) — et l'oubli est SILENCIEUX, d'où la dérivation : les deux
    sites de reset (`command_step_start_of_turn`, `W40KEngine.reset`) suivent la table sans
    la recopier.
    """
    return {
        key: set()
        for entry in _TAKE_TO_THE_SKIES_BY_PHASE.values()
        for key in (entry.declared_key, entry.resolved_key)
    }


def take_to_the_skies_applies_to_phase(game_state: Dict[str, Any], *, charge: bool) -> bool:
    """La déclaration 21.03 concerne-t-elle le mouvement que la phase en cours résout ?

    GARDE COMMUNE au malus de -2" (`get_squad_move_budget`) et à la traversée
    (`_fly_traversal_active`). Sans elle du côté du budget, le budget de move d'une unité volante
    resterait amputé de 2" en phases de tir, de charge et de combat — où aucun move normal n'est
    résolu et où aucune traversée n'est active. L'échelle de la grille égocentrique
    (`grid_half_extent_subhex`, appelée à chaque phase) en dépend directement.
    """
    entry = _fly_phase_entry(game_state)
    return entry is not None and entry.is_charge is charge


def took_to_the_skies(
    game_state: Dict[str, Any], unit: Dict[str, Any], unit_id: str, *, charge: bool
) -> bool:
    """21.03 — l'unité a-t-elle déclaré « take to the skies » pour le mouvement EN COURS ?

    C'est la SOURCE UNIQUE de la déclaration : le malus de -2" sur la distance maximale et la
    traversée (murs, figurines, terrain, distance verticale) en découlent tous les deux. Les
    dissocier laisserait rejouer le défaut d'origine — une traversée gratuite.

    - Sans le keyword FLY : jamais.
    - Sinon : uniquement si la déclaration a été POSÉE pour ce mouvement, dans le set propre au
      type de mouvement. UN seul chemin de lecture pour tous les sièges — l'humain y écrit par le
      toggle (``movement_set_fly_mode_handler`` / ``charge_set_fly_mode_handler``), le siège
      piloté par le modèle par le point de choix ``arm_fly_declaration_decision``, résolu par
      ``apply_fly_declaration_decision``.

    ⚠️ HISTORIQUE — CE QUI A DISPARU ICI (V11 §0.48 élément `L6`). Jusqu'au chantier `L6`, une
    unité pilotée par le modèle rendait `True` INCONDITIONNELLEMENT : le canal d'observation et
    l'action de choix n'existaient pas, et §0.49 point 5 avait tranché « déclarer toujours »
    plutôt que de rendre le mot-clé FLY inerte. Le coût était permanent et parfois pur —
    -2" à CHAQUE mouvement (soit -16,7 % pour les jump packs MOVE 12", -14,3 % pour les Land
    Speeders MOVE 14", et -28,6 % sur l'espérance du jet de charge), y compris en terrain
    découvert où la traversée n'apporte rien. C'est fini : la déclaration est redevenue ce que
    21.03 en fait, un choix du joueur actif, par mouvement.

    La déclaration reste lue à l'identique par le masque, l'observation et l'exécution : elle
    est écrite AVANT que le pool ne soit construit (le moteur rend la main sur le point de choix),
    jamais après.
    """
    if not _unit_has_keyword(unit, "fly"):
        return False
    entry = _TAKE_TO_THE_SKIES_BY_PHASE["charge" if charge else "move"]
    return unit_id in game_state.get(entry.declared_key, set())


def _fly_traversal_active(game_state: Dict[str, Any], unit: Dict[str, Any], unit_id: str) -> bool:
    """Take to the skies (Règles 21.03) : la traversée FLY (murs/figurines/terrain + ignore de la
    distance verticale) est active si et seulement si le vol a été DÉCLARÉ pour le mouvement en
    cours — la traversée est la contrepartie des 2" retranchés, jamais un acquis du keyword.

    La phase désigne le mouvement en cours, donc le set de déclaration à lire. Hors des mouvements
    énumérés par 21.03 (move / charge), la règle ne s'applique pas : pas de traversée.

    Source unique partagée par le pool d'ancre, le reachable par-figurine, le coût de descente et
    le log de move.
    """
    entry = _fly_phase_entry(game_state)
    if entry is None:
        return False
    return took_to_the_skies(game_state, unit, unit_id, charge=entry.is_charge)


def _fly_declaration_due_unit(
    game_state: Dict[str, Any], squad_id: str
) -> Optional[Dict[str, Any]]:
    """L'escouade si la déclaration 21.03 lui est encore DUE pour le mouvement en cours, sinon None.

    Rend l'UNITÉ et pas un booléen : l'armement en a besoin juste après (joueur propriétaire), et
    la résoudre deux fois posait deux `get_unit_by_id` et deux messages d'erreur jumeaux à garder
    synchrones, sur le chemin de construction du masque.

    Quatre conditions, toutes nécessaires :
      1. la phase résout un mouvement que 21.03 couvre (`_TAKE_TO_THE_SKIES_BY_PHASE`) ;
      2. l'escouade a le mot-clé FLY — sinon il n'y a rien à déclarer ;
      3. elle est pilotée par le modèle : un humain déclare par le toggle de l'UI, et lui poser
         une `pending_agent_decision` arrêterait le PvP sur un overlay qui n'existe pas ;
      4. elle appartient au joueur DONT C'EST LE TOUR. 21.03 confie la déclaration au « active
         player » : poser la question à l'adversaire lui ferait déclarer un vol hors de son tour,
         et `apply_fly_declaration_decision` refuserait ensuite la réponse (il vérifie le
         propriétaire contre `current_player`) — le moteur resterait arrêté sur une décision que
         personne ne peut résoudre. En production le pool d'activation est déjà celui du joueur
         courant ; cette condition est ce qui rend l'invariant vrai PAR CONSTRUCTION plutôt que
         par la bonne conduite des appelants ;
      5. la question ne lui a pas DÉJÀ été posée pour ce mouvement. Sans cette 5e condition, un
         « je ne déclare pas » (qui laisse le set de déclaration vide) serait indiscernable d'une
         question jamais posée : le point de choix se reposerait à chaque construction de masque
         et l'escouade ne bougerait jamais.
    """
    entry = _fly_phase_entry(game_state)
    if entry is None:
        return None
    unit = get_unit_by_id(game_state, str(squad_id))
    if unit is None:
        raise KeyError(f"_fly_declaration_due_unit: escouade {squad_id} introuvable")
    if not _unit_has_keyword(unit, "fly"):
        return None
    if not _unit_is_ai_controlled(game_state, unit):
        return None
    if int(require_key(unit, "player")) != int(require_key(game_state, "current_player")):
        return None
    if str(squad_id) in game_state.get(entry.resolved_key, set()):  # get allowed : absent = jamais posée
        return None
    return unit


def fly_declaration_decision_is_due(game_state: Dict[str, Any], squad_id: str) -> bool:
    """21.03 — cette escouade doit-elle encore DÉCLARER (ou non) son vol pour le mouvement en cours ?

    Lecture PUBLIQUE et SANS effet de bord de la condition d'armement. Elle partage son corps
    avec `arm_fly_declaration_decision` (`_fly_declaration_due_unit`) mais n'est pas ce que
    l'armement appelle : lui a besoin de l'unité, pas d'un booléen. Les deux ne peuvent donc pas
    diverger, et c'est le seul point qui compte ici.

    ⚠️ Aucun appelant de PRODUCTION à ce jour — ses consommateurs sont les tests, qui doivent
    pouvoir observer « la question est-elle due ? » sans la poser. Écrit pour que personne ne la
    supprime en la croyant morte, ni ne la prenne pour le chemin du masque.
    """
    return _fly_declaration_due_unit(game_state, squad_id) is not None


def arm_fly_declaration_decision(
    game_state: Dict[str, Any], squad_id: str
) -> Optional[Dict[str, Any]]:
    """Pose le point de choix « take to the skies » (21.03) de `squad_id`, s'il est dû.

    Rend la décision POSÉE, ou None si elle n'était pas due — l'appelant qui en reçoit une doit
    rendre la main au décideur (masque exclusivement `CHOICE_*`), exactement comme 08.04 le fait
    pour le Waaagh! (`command_step_command_abilities`). Rendre la décision plutôt qu'un booléen
    évite à l'appelant de relire l'état pour la retrouver, et supprime l'incohérence
    « True sans décision posée » qu'il devait sinon garder.

    ORDRE CONTRACTUEL des candidats (§9.6), et c'est lui qui porte le sens puisqu'aucun des deux
    n'accorde d'effet de datasheet : `CHOICE_0` = déclarer le vol (traversée des murs, des
    figurines et du dénivelé, contre -2" sur la distance), `CHOICE_1` = ne pas déclarer.

    L'appelant garantit que le mouvement en cours EST celui de la phase : une escouade en réserves
    fait une mise en place (20.04 « ingress move »), pas un des quatre mouvements que 21.03
    énumère, et le masque la traite avant d'arriver ici.
    """
    unit = _fly_declaration_due_unit(game_state, squad_id)
    if unit is None:
        return None
    from engine.agent_decision import set_pending_agent_decision

    return set_pending_agent_decision(
        game_state,
        decision_type="fly_declaration",
        player=int(require_key(unit, "player")),
        unit_id=str(squad_id),
        options=[
            # `effect_ids` vide des DEUX côtés : « take to the skies » n'est accordé par aucune
            # datasheet (c'est le mot-clé FLY qui l'ouvre, 21.03 qui en fixe le prix), donc il
            # n'appartient pas au registre des accordables. C'est `declines` — et non l'index,
            # qui n'est écrit dans AUCUN scalaire d'observation — qui distingue les deux lignes :
            # sans lui elles sortiraient identiques et l'agent ne pourrait pas apprendre à
            # choisir (cf. `DECISION_OPTION_BIN_FIELDS`, défaut mesuré sur `waaagh_call`).
            {
                "label": "Take to the skies",
                "effect_ids": (),
                "declines": False,
                "payload": {"declare": True},
            },
            {
                "label": "Stay grounded",
                "effect_ids": (),
                "declines": True,
                "payload": {"declare": False},
            },
        ],
    )


def apply_fly_declaration_decision(
    game_state: Dict[str, Any], squad_id: str, declared: bool
) -> None:
    """Applique le candidat choisi pour `fly_declaration`, et EFFACE la décision.

    Écrivain unique du couple (set de déclaration, set de résolution) pour les sièges pilotés par
    le modèle — pendant exact d'`apply_waaagh_call_decision`, dont il partage le préambule
    (`consume_pending_agent_decision` : vérifie le type et le propriétaire, puis efface).

    « Ne pas déclarer » n'est PAS un non-événement : c'est le second candidat, et il doit laisser
    une trace (le set de résolution), sans quoi la question se reposerait indéfiniment.

    LES DEUX IDENTIFIANTS PASSÉS AU VÉRIFICATEUR N'ONT PAS LE MÊME STATUT, et c'est voulu :
      - `player` est lu dans l'ÉTAT (`current_player`), donc INDÉPENDANT de la décision : ce
        contrôle-là mord. Il refuse une décision qui a survécu au tour de son propriétaire —
        seul son siège peut y répondre (mesuré : 31 décisions sur 3 épisodes, aucune dont le
        joueur diffère de `current_player`) ;
      - `unit_id` est l'escouade SUR LAQUELLE on écrit ; il n'existe aucune autre source pour
        elle, donc l'unique appelant du gym le lit forcément dans la décision et le contrôle y
        est une identité. Il n'est pas retiré pour autant : il est la seule barrière contre un
        futur appelant qui appliquerait la déclaration à une AUTRE escouade que celle interrogée.
    """
    from engine.agent_decision import consume_pending_agent_decision

    entry = _fly_phase_entry(game_state)
    if entry is None:
        raise RuntimeError(
            f"apply_fly_declaration_decision: la phase '{game_state.get('phase')}' ne resout aucun "
            "des mouvements que 21.03 couvre — la decision a survecu a sa phase."
        )
    consume_pending_agent_decision(
        game_state,
        decision_type="fly_declaration",
        player=int(require_key(game_state, "current_player")),
        unit_id=str(squad_id),
    )
    game_state.setdefault(entry.resolved_key, set()).add(str(squad_id))
    if declared:
        game_state.setdefault(entry.declared_key, set()).add(str(squad_id))


def squad_move_pool_budget_subhex(game_state: Dict[str, Any], squad_id: str) -> int:
    """Budget (subhex) du mouvement que cette escouade s'apprête RÉELLEMENT à faire.

    SOURCE UNIQUE de la borne des destinations : régime Advance si un jet a été tiré pour elle,
    sinon normal/fall-back — et dans les deux cas le malus Take to the skies (-2", 21.03) que
    `get_squad_move_budget` applique.

    Extraite de `movement_build_valid_destinations_pool` pour que l'ÉLIGIBILITÉ (`get_eligible_units`)
    borne sa recherche exactement comme le pool : bornée sur la caractéristique `MOVE` brute, elle
    déclarait éligible une unité volante dont toutes les destinations légales tombent dans la bande
    `(M - 2", M]` — donc avec un pool vide. C'est la classe d'incohérence masque/exécution que
    §0.34 pourchasse.
    """
    _adv_roll = _advance_roll_for(str(squad_id), game_state)
    if _adv_roll is not None:
        return get_squad_move_budget(str(squad_id), game_state, "advance", advance_roll=_adv_roll)
    return get_squad_move_budget(str(squad_id), game_state, "normal")


def squad_descent_penalty_subhex(game_state: Dict[str, Any], squad_id: str) -> int:
    """Coût de descente (§13.06) à retrancher du budget d'un squad move RIGIDE (destination sol).

    En squad move la destination est toujours le sol : une figurine partant d'un étage (niveau >= 1)
    doit descendre. On pénalise TOUTE l'escouade du coût de descente de la figurine la plus haute
    (max des hauteurs) — le move rigide gardant un delta unique, le pire cas dicte la limite commune,
    afin qu'aucune fig ne gagne la distance verticale gratuitement.

    Retourne 0 si :
    - l'unité vole (``_fly_traversal_active`` : FLY + take-to-the-skies déclaré, §21.03) → pas de coût
      vertical, aligné sur ``ignore_vertical_cost`` du champ multi-niveaux ;
    - aucune figurine vivante n'est en hauteur (niveau >= 1) → no-op (cas courant tout-au-sol).

    Unité : subhexes (comme le budget MOVE). Coût = hauteur absolue du niveau × inches_to_subhex,
    arrondi au subhex supérieur (conservateur : ne jamais sous-facturer la descente).
    """
    unit = require_unit_by_id(game_state, squad_id)
    if _fly_traversal_active(game_state, unit, squad_id):
        return 0
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    inches_to_subhex = int(require_key(game_state, "inches_to_subhex"))
    terrain_areas = game_state.get("terrain_areas", [])  # get allowed (peut être vide)
    # Hauteur ABSOLUE (pouces) par niveau — même source que _multilevel_floor_destinations.
    height_inches_by_level: Dict[int, float] = {0: 0.0}
    for a in terrain_areas:
        for fl in a.get("floors", []):  # get allowed
            lv = int(fl["level"])
            hi = float(fl["height_inches"])
            if lv in height_inches_by_level and abs(height_inches_by_level[lv] - hi) > 1e-6:
                raise ValueError(
                    f"squad_descent_penalty_subhex: niveau {lv} avec hauteurs incohérentes "
                    f"({height_inches_by_level[lv]} vs {hi})"
                )
            height_inches_by_level[lv] = hi
    max_cost = 0
    for mid in squad_models.get(squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is None:
            continue
        if int(m.get("HP_CUR", 0)) <= 0:  # get allowed
            continue
        lv = int(require_key(m, "level"))
        if lv <= 0:
            continue
        if lv not in height_inches_by_level:
            raise KeyError(f"squad_descent_penalty_subhex: fig {mid} niveau {lv} sans hauteur terrain")
        cost = int(math.ceil(height_inches_by_level[lv] * inches_to_subhex))
        if cost > max_cost:
            max_cost = cost
    return max_cost


def _movement_engagement_violates(
    game_state: Dict[str, Any],
    mover: Dict[str, Any],
    center_col: int,
    center_row: int,
    candidate_fp: Set[Tuple[int, int]],
    units_cache: Dict[str, Any],
    enemy_adjacent_hexes: Optional[Set[Tuple[int, int]]] = None,
    *,
    enemy_cache_items: Optional[List[Tuple[Any, Any]]] = None,
    engagement_zone_ez: Optional[int] = None,
) -> bool:
    """True si le placement est interdit par la zone autour des ennemis.

    Plateau ×10 (``engagement_zone`` > 1) : pour deux socles **ronds**, écart
    bord à bord euclidien (repère ``_hex_center``) ≥ ``engagement_zone`` × pas
    horizontal — aligné preview combat / ``hexFootprint.ts``. Autres formes :
    repli sur ``min_distance_between_sets`` (comportement historique).
    Legacy (``engagement_zone`` ≤ 1) : toute case de l'empreinte dans
    ``enemy_adjacent_hexes`` (dilatation hex).
    """
    if engagement_zone_ez is not None:
        ez = engagement_zone_ez
    else:
        ez = get_engagement_zone(game_state)
    from engine.spatial_relations import move_anchor_violates_engagement_clearance

    return move_anchor_violates_engagement_clearance(
        game_state,
        mover,
        center_col,
        center_row,
        candidate_fp,
        units_cache,
        enemy_adjacent_hexes,
        enemy_cache_items=enemy_cache_items,
        engagement_zone_ez=ez,
    )


def _invalidate_all_destination_pools_after_movement(game_state: Dict[str, Any]) -> None:
    """
    Invalidate all destination pools after any unit movement.
    
    After a unit moves, all destination pools become stale because:
    - Occupied positions have changed
    - Enemy adjacent hexes have changed
    - Friendly adjacent hexes have changed (for future use)
    
    This function clears:
    - valid_move_destinations_pool (for all units)
    - valid_charge_destinations_pool (for all units)
    - valid_target_pool (for all units in shoot phase)
    - _target_pool_cache (global cache in shooting_handlers)
    
    Called after every movement in move, shoot (advance), and charge phases.
    """
    # Clear movement destination pools
    if "valid_move_destinations_pool" in game_state:
        game_state["valid_move_destinations_pool"] = []
    if "move_preview_footprint_zone" in game_state:
        game_state["move_preview_footprint_zone"] = set()
    if "move_preview_border" in game_state:
        game_state["move_preview_border"] = []
    if "move_preview_footprint_mask_loops" in game_state:
        game_state["move_preview_footprint_mask_loops"] = None
    # Les mémos d'ingress (20.04) ne sont PAS vidés ici, et c'est délibéré : leur clé porte les
    # positions ENNEMIES, or cette fonction est appelée après chaque mouvement — y compris AMI,
    # qui ne peut pas les périmer. Les vider obligeait à repayer 49 ms de recalcul après chaque
    # commit (mesuré), pour une entrée qui restait valable. Leur croissance est contenue par leurs
    # producteurs : borne `_INGRESS_POOL_CACHE_MAX` pour `_ingress_pool_with_key` (pool) et
    # `_ingress_clearance_mask_cached` (masque des 8"), purge des empreintes devenues
    # inatteignables pour `ingress_preview_loops` (contours, trop chers à jeter en bloc).

    # Clear charge destination pools
    if "valid_charge_destinations_pool" in game_state:
        game_state["valid_charge_destinations_pool"] = []
    if "_charge_dest_bfs_cache" in game_state:
        game_state["_charge_dest_bfs_cache"] = {}
    # Champ géodésique de move par-figurine (Étape 4.1) : vidé au phase start et après chaque
    # commit réel. Les poses provisoires du move-preview N'appellent PAS cette fonction → le champ
    # (indépendant des sœurs quand thru_friendly) survit aux poses et n'est calculé qu'une fois.
    if "_move_model_field_cache" in game_state:
        game_state["_move_model_field_cache"] = {}
    if "_charge_closest_hex_cache" in game_state:
        game_state["_charge_closest_hex_cache"] = {}
    if "_has_valid_charge_cache" in game_state:
        game_state["_has_valid_charge_cache"] = {}

    # Clear target pools for all units (shoot phase)
    for unit in require_key(game_state, "units"):
        if "valid_target_pool" in unit:
            unit["valid_target_pool"] = []
    
    # Clear global target pool cache (shooting_handlers)
    from .shooting_handlers import _target_pool_cache
    _target_pool_cache.clear()

    # Enemy adjacency caches are updated incrementally at movement execution time.
    

def _log_movement_debug(game_state: Dict[str, Any], function_name: str, unit_id: str, message: str) -> None:
    """Helper to keep debug logging calls stable (no-op)."""
    return


def movement_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI_MOVE.md: Initialize movement phase and build activation pool
    """
    # Sous W40K_MASK_VERIFY=1 : aucun jet d'Advance ne doit avoir survecu a la phase move
    # precedente (regle 09.06). Avant de poser la phase, sinon le controle s'auto-justifie.
    from engine.mask_verification import verify_advance_rolls_cycle

    verify_advance_rolls_cycle(game_state)

    # Set phase
    from engine.game_utils import enter_phase
    enter_phase(game_state, "move")

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    units_cache = require_key(game_state, "units_cache")
    add_debug_file_log(game_state, f"[PHASE START] E{episode} T{turn} move units_cache={units_cache}")

    # « At the START of your Movement phase » — avant toute activation, donc avant les pools.
    movement_step_cp_gain_on_objective(game_state)


    # Pre-compute enemy_adjacent_hexes once at phase start for all players present.
    # Reactive movement may query adjacency from the opposing player's perspective.
    players_present = set()
    for cache_entry in units_cache.values():
        player_raw = require_key(cache_entry, "player")
        try:
            player_int = int(player_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid player value in units_cache at movement_phase_start: {player_raw!r}"
            ) from exc
        players_present.add(player_int)
    for player_int in players_present:
        build_enemy_adjacent_hexes(game_state, player_int)

    # Invalidate all destination pools at the START of the phase
    # This ensures pools are clean and don't contain stale data from previous phases
    _invalidate_all_destination_pools_after_movement(game_state)
    
    # Build activation pool
    movement_build_activation_pool(game_state)
    
    # Console log
    from engine.game_utils import add_console_log
    add_console_log(game_state, "MOVEMENT POOL BUILT")
    
    # Check if phase complete immediately (no eligible units)
    if not game_state["move_activation_pool"]:
        return movement_phase_end(game_state)
    
    return {
        "phase_initialized": True,
        "eligible_units": len(game_state["move_activation_pool"]),
        "phase_complete": False
    }


def movement_step_cp_gain_on_objective(game_state: Dict[str, Any]) -> int:
    """`cp_gain_on_objective` (Thievin' Scavengers) — début de la phase de mouvement.

    « For each objective you control that has one or more friendly NON-BATTLE-SHOCKED units with
    this ability within range of it, roll one D6. If one or more of those rolls is a 4+, you gain
    1CP. »

    ⚠️ UN dé par objectif, mais UN SEUL CP au total : le gain est global, pas cumulatif par
    objectif. C'est le piège de lecture de la capacité — « if one or more of those rolls is a 4+ »
    porte sur l'ENSEMBLE des jets.

    UNE SEULE FOIS par phase de mouvement, garanti par le marqueur `(tour, joueur)` —
    `movement_phase_start` n'est PAS idempotente vis-à-vis d'une capacité qui lance des dés, et
    `execute_action` la ré-invoque quand elle voit un pool vide. Tant que la fonction ne faisait
    que reconstruire des caches, la relancer était sans effet ; avec un gain de CP, ce serait un
    second jet et un CP en trop. Même motif de garde que `primary_objective_scored_turns`.

    Retourne le nombre de dés lancés (0 = aucun objectif éligible ou étape déjà résolue), pour le
    log et les tests.
    """
    import random

    from engine.game_state import (
        gain_command_points, objective_hex_zones, unit_is_within_objective,
    )
    from engine.game_utils import add_debug_file_log, once_claim, once_claimed
    from .shared_utils import is_unit_alive, unit_has_rule_effect

    current_player = int(require_key(game_state, "current_player"))

    units = require_key(game_state, "units")
    # Porteurs vivants, non battle-shocked, du joueur actif. Calculé UNE fois : la liste ne
    # dépend pas de l'objectif, seule l'appartenance à la zone en dépend.
    # Ordre des filtres = du plus discriminant au plus cher : la capacite d'abord (presque
    # aucune unite la porte), le statut ensuite.
    carriers = [
        unit for unit in units
        if int(require_key(unit, "player")) == current_player
        and unit_has_rule_effect(unit, "cp_gain_on_objective")
        and not require_key(unit, "battle_shocked")
        and is_unit_alive(str(require_key(unit, "id")), game_state)
    ]
    # Aucun porteur vivant : la capacite n'existe pas dans cette partie, il n'y a rien a lire.
    # C'est aussi ce qui evite d'exiger l'etat de controle d'objectif d'un roster qui n'a
    # aucune unite concernee.
    if not carriers:
        return 0

    # 14.02 : « you control » se lit sur le contrôle DÉTERMINÉ à la fin de la phase précédente —
    # ici la fin de la phase de commandement. Ce checkpoint tourne en fin de `step` moteur, donc
    # APRÈS le début de la phase de mouvement du même step : MESURÉ, `objective_controllers`
    # valait `{}` aux deux phases de mouvement du tour 1, et la capacité n'y jouait JAMAIS —
    # « code testé mais jamais atteint ». On force donc la frontière à être soldée avant de lire.
    # `refresh_objective_control_on_boundary` est idempotente (elle mémorise la dernière
    # frontière vue) et ne fait que recalculer les contrôleurs : aucun VP n'est marqué ici.
    from engine.game_state import GameStateManager

    GameStateManager(require_key(game_state, "config")).refresh_objective_control_on_boundary(
        game_state
    )
    # Etape deja resolue ce (tour, joueur) ? Verifie APRES le filtre des porteurs : sans porteur
    # il n'y a rien a resoudre, donc rien a memoriser — et un etat de jeu sans cette capacite n'a
    # pas a porter le marqueur.
    # RESERVE AVANT D'AGIR, contrairement aux trois autres familles de `_once_claims` qui
    # marquent apres l'effet : l'etape lance des des, la rejouer donnerait un CP en trop.
    marker = (int(require_key(game_state, "turn")), current_player)
    if once_claimed(game_state, "cp_gain_on_objective_resolved", marker):
        return 0
    once_claim(game_state, "cp_gain_on_objective_resolved", marker)

    controllers = require_key(game_state, "objective_controllers")
    rolls: List[int] = []
    for objective_id, zone in objective_hex_zones(game_state):
        # `.get` : un objectif jamais évalué par le checkpoint 14.02 n'a PAS de contrôleur, et
        # « pas de contrôleur » est un état de jeu valide (début de bataille), pas une donnée
        # manquante. Même lecture que `get_objective_control_for_player` (macro_intents).
        if controllers.get(str(objective_id)) != current_player:
            continue
        if not any(
            unit_is_within_objective(game_state, unit, zones=[zone]) for unit in carriers
        ):
            continue
        rolls.append(random.randint(1, 6))

    if not rolls:
        return 0
    if any(roll >= 4 for roll in rolls):
        gain_command_points(game_state, current_player, 1, "cp_gain_on_objective")
    add_debug_file_log(
        game_state,
        f"[CP GAIN ON OBJECTIVE] E{game_state.get('episode_number', '?')} "
        f"T{game_state.get('turn', '?')} player={current_player} rolls={rolls}"
    )
    return len(rolls)


def movement_build_activation_pool(game_state: Dict[str, Any]) -> None:
    """
    AI_MOVE.md: Build activation pool with eligibility checks
    """
    current_player = require_key(game_state, "current_player")
    # Clear pool before rebuilding (defense in depth)
    game_state["move_activation_pool"] = []
    eligible_units = get_eligible_units(game_state)
    # 20.03/20.04 — les escouades EN RÉSERVES sont activables en phase de mouvement pour y faire
    # leur ingress move. Elles ne sont pas dans `get_eligible_units` (qui n'énumère que les
    # unités présentes sur le plateau) : leur éligibilité a ses propres conditions (être en
    # réserves, round >= 2). Ajoutées en FIN de pool, l'ordre des unités déjà posées est
    # inchangé.
    eligible_units = eligible_units + [
        uid for uid in ingress_eligible_units(game_state) if uid not in eligible_units
    ]
    game_state["move_activation_pool"] = eligible_units

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    add_debug_file_log(game_state, f"[POOL BUILD] E{episode} T{turn} move move_activation_pool={eligible_units}")
    
    # Log pool build result
    _log_with_context(game_state, "MOVE DEBUG", f"movement_build_activation_pool: pool_size={len(eligible_units)} units={eligible_units}")


def get_eligible_units(game_state: Dict[str, Any]) -> List[str]:
    """
    tour_de_jeu.md movement eligibility decision tree implementation.

    Returns list of unit IDs eligible for movement activation.
    Pure function - no internal state storage.
    """
    eligible_units = []
    current_player = game_state["current_player"]

    units_cache = require_key(game_state, "units_cache")

    if game_state.get("sandbox_free_move"):
        from engine.phase_handlers.shared_utils import entry_is_on_battlefield
        return [
            uid for uid, entry in units_cache.items()
            if entry["player"] == current_player
            and int(entry.get("HP_CUR", 0)) > 0
            and entry_is_on_battlefield(entry)
        ]

    ez_elig = get_engagement_zone(game_state)
    from engine.phase_handlers.shared_utils import entry_is_on_battlefield

    for unit_id, cache_entry in units_cache.items():
        # "unit.player === current_player?"
        if cache_entry["player"] != current_player:
            continue  # Wrong player (Skip, no log)

        # HORS TABLE (réserves 20.01, ou attente de déploiement) : aucun déplacement possible —
        # l'unité n'a pas de position d'où partir. Son arrivée passe par l'ingress move (20.04),
        # dont l'éligibilité est construite par `ingress_eligible_units`.
        if not entry_is_on_battlefield(cache_entry):
            continue

        # 20.04 AFTER MOVING — l'escouade arrivée de réserves n'est éligible à AUCUN autre type
        # de mouvement jusqu'au début de la phase de charge.
        if unit_ingress_move_locked(game_state, str(unit_id)):
            continue

        # Check if unit has at least one legal destination.
        # FLY units can ignore path blockers (walls/units) while moving, so eligibility
        # must not be limited to adjacent traversable hexes.
        unit_obj = get_unit_by_id(game_state, unit_id)
        if unit_obj is None:
            raise ValueError(f"Unit {unit_id} not found in game_state while building move eligibility")
        has_fly_keyword = _unit_has_keyword(unit_obj, "fly")

        # Normalize MOVE to int for range checks (validation de la donnée de datasheet)
        move_range_raw = require_key(unit_obj, "MOVE")
        try:
            move_stat = int(move_range_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid MOVE value for unit {unit_id}: {move_range_raw!r}") from exc
        if move_stat <= 0:
            continue

        # Borne de la recherche d'éligibilité = budget du move, PAS la caractéristique brute.
        # `MOVE` et le budget diffèrent dès que l'unité prend les airs (-2", 21.03) : borner sur
        # `MOVE` déclarerait éligible une unité volante dont la seule destination légale est dans
        # la bande `(M - 2", M]`, que le pool refusera ensuite — masque ⊄ exécutable (§0.34).
        #
        # Le coût de DESCENTE (§13.06) n'entre PAS ici, et c'est délibéré : le pool le retranche
        # parce qu'il construit un régime DÉJÀ CHOISI, alors que l'éligibilité précède le choix.
        # L'Advance se déclarant APRÈS activation, et l'activation exigeant d'être dans
        # `move_activation_pool`, retrancher la descente ici supprimerait ce mouvement légal pour
        # toute la phase (verrou :
        # `test_a_squad_whose_descent_eats_its_normal_budget_stays_eligible_for_advance`).
        move_range = squad_move_pool_budget_subhex(game_state, str(unit_id))
        if move_range <= 0:
            continue

        # Unité ENGAGÉE (régime fin ez>1) : son seul déplacement légal est un Fall Back, qui
        # AUTORISE le passage dans l'EZ. L'heuristique "voisin immédiat hors EZ" ci-dessous
        # l'exclurait à tort (elle démarre DANS l'EZ). On délègue au builder de pool (BFS
        # fall-back rules-exact) en lecture seule : éligible ssi au moins une destination légale
        # (arrivée hors EZ de tous les ennemis, atteignable en M, empreinte valide) existe.
        if ez_elig > 1 and _squad_is_in_enemy_er(game_state, unit_id):
            if movement_build_valid_destinations_pool(game_state, unit_id, read_only=True):
                eligible_units.append(unit_id)
            continue

        # This ensures the unit can actually move
        unit_col, unit_row = require_unit_position(unit_id, game_state)
        
        occupied_positions = build_occupied_positions_set(game_state, exclude_unit_id=unit_id)
        current_player = require_key(game_state, "current_player")
        if current_player is None:
            raise KeyError("game_state missing required 'current_player' field")
        cache_key = f"enemy_adjacent_hexes_player_{current_player}"
        if cache_key not in game_state:
            raise KeyError(f"enemy_adjacent_hexes cache missing for player {current_player} - build_enemy_adjacent_hexes() must be called at phase start")
        enemy_adjacent_hexes = game_state[cache_key]

        has_valid_adjacent_hex = False
        if has_fly_keyword:
            board_cols = require_key(game_state, "board_cols")
            board_rows = require_key(game_state, "board_rows")
            fly_visited: Set[Tuple[int, int]] = {(unit_col, unit_row)}
            fly_q = deque([((unit_col, unit_row), 0)])
            while fly_q and not has_valid_adjacent_hex:
                fc, fd = fly_q.popleft()
                if fd >= move_range:
                    continue
                for nb in get_hex_neighbors(fc[0], fc[1]):
                    if nb in fly_visited:
                        continue
                    fly_visited.add(nb)
                    nc, nr = nb
                    if nc < 0 or nc >= board_cols or nr < 0 or nr >= board_rows:
                        continue
                    fly_q.append((nb, fd + 1))
                    candidate_fp = compute_candidate_footprint(nc, nr, unit_obj, game_state)
                    base_ok = is_footprint_placement_valid(
                        candidate_fp,
                        game_state,
                        occupied_positions,
                        enemy_adjacent_hexes,
                        anchor=(nc, nr),
                        socle=unit_obj,
                    )
                    if base_ok and (
                        _geometry_is_hex(game_state)
                        or not _movement_engagement_violates(
                            game_state,
                            unit_obj,
                            nc,
                            nr,
                            candidate_fp,
                            units_cache,
                            enemy_adjacent_hexes,
                            engagement_zone_ez=ez_elig,
                        )
                    ):
                        has_valid_adjacent_hex = True
                        break
        else:
            neighbors = get_hex_neighbors(unit_col, unit_row)
            for neighbor_pos in neighbors:
                neighbor_col, neighbor_row = neighbor_pos
                candidate_fp = compute_candidate_footprint(neighbor_col, neighbor_row, unit_obj, game_state)
                base_ok = is_footprint_placement_valid(
                    candidate_fp,
                    game_state,
                    occupied_positions,
                    enemy_adjacent_hexes,
                    anchor=(neighbor_col, neighbor_row),
                    socle=unit_obj,
                )
                if base_ok and (
                    _geometry_is_hex(game_state)
                    or not _movement_engagement_violates(
                        game_state,
                        unit_obj,
                        neighbor_col,
                        neighbor_row,
                        candidate_fp,
                        units_cache,
                        enemy_adjacent_hexes,
                        engagement_zone_ez=ez_elig,
                    )
                ):
                    has_valid_adjacent_hex = True
                    break

        if not has_valid_adjacent_hex:
            continue  # Unit cannot move (no valid adjacent hex)

        # Unit passes all conditions
        eligible_units.append(unit_id)

    # Log eligible units result
    _log_with_context(game_state, "MOVE DEBUG", f"get_eligible_units: eligible={eligible_units} count={len(eligible_units)}")

    return eligible_units


def execute_action(game_state: Dict[str, Any], unit: Optional[Dict[str, Any]], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_MOVE.md: Handler action routing with complete autonomy
    """
    if game_state.get("pending_shooting_phase_init"):
        return False, {
            "error": "pending_shooting_phase_init",
            "hint": "Movement phase ended; call semantic action advance_phase with from=move to start shooting.",
        }

    # Handler self-initialization on first action
    if "phase" not in game_state:
        game_state_phase = None
    else:
        game_state_phase = game_state["phase"]
    
    if "move_activation_pool" not in game_state:
        move_pool_exists = False
    else:
        move_pool_exists = bool(game_state["move_activation_pool"])
    
    if game_state_phase != "move" or not move_pool_exists:
        movement_phase_start(game_state)
    
    # Pool empty? -> Phase complete
    if not game_state["move_activation_pool"]:
        return True, movement_phase_end(game_state)
    
    # Get unit from action (frontend specifies which unit to move)
    if "action" not in action:
        raise KeyError(f"Action missing required 'action' field: {action}")
    if "unitId" not in action:
        action_type = action["action"]
        unit_id = None  # Allow None for gym training auto-selection
    else:
        action_type = action["action"]
        unit_id = action["unitId"]
        
    # For gym training, if no unitId specified, use first eligible unit
    if not unit_id:
        if game_state["move_activation_pool"]:
            unit_id = game_state["move_activation_pool"][0]
        else:
            return True, movement_phase_end(game_state)
    
    # Validate unit is eligible (keep for validation, remove only after successful action)
    if unit_id not in game_state["move_activation_pool"]:
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    
    # Get unit object for processing
    active_unit = require_unit_by_id(game_state, unit_id)
    # Log action routing
    _log_movement_debug(game_state, "execute_action", str(unit_id), f"action={action_type}")
    
    # Auto-activate unit if not already activated and preview not shown. Le split gym qui vivait
    # ici est SUPPRIMÉ : `convert_squad_action` n'émet ni `move` ni `left_click`, donc ses deux
    # branches (activation silencieuse avec destination, diagnostic `[MOVE DIAGNOSTIC]` sans)
    # étaient inatteignables et démentaient le garde de `_handle_unit_activation`.
    if not game_state.get("active_movement_unit") and action_type in ["move", "left_click"]:
        # Human players: activate but don't return, continue to normal flow
        _handle_unit_activation(game_state, active_unit, config)

    if action_type == "activate_unit":
        return _handle_unit_activation(game_state, active_unit, config)

    elif action_type == "move":
        # Execute movement directly (destination déjà dans l'action, cf. le clic PvP)
        return movement_destination_selection_handler(game_state, unit_id, action)

    elif action_type == "advance":
        # V11 : bascule l'activation move en mode Advance (jet D6 + budget M+jet). Commit via commit_move_plan.
        return movement_set_advance_mode_handler(game_state, unit_id, action)

    elif action_type == "take_to_skies":
        # Règles 21.03 : (dé)clare le vol de l'escouade FLY active (-2" + traversée murs/figurines).
        return movement_set_fly_mode_handler(game_state, unit_id, action)

    elif action_type == "commit_move_plan":
        # Validate (= bouton Validate) + commit d'un plan provisoire par-figurine.
        return movement_commit_move_plan_handler(game_state, unit_id, action)

    elif action_type == "ingress_move":
        # 20.04 — arrivée de réserves. Routée ICI, comme tout autre type de mouvement, et non
        # depuis l'API : c'est ce qui lui donne sa FIN D'ACTIVATION. Sans elle, l'escouade
        # resterait dans `move_activation_pool` (le pool n'est pas reconstruit après chaque
        # action), donc réactivable pour un second mouvement le même tour, et la phase ne
        # pourrait plus se terminer par épuisement du pool.
        return _handle_ingress_move_action(game_state, active_unit, action)

    elif action_type == "ingress_commit":
        # 20.04 — même arrivée, mais avec le plan par-figurine ÉDITÉ par le joueur (jumeau de
        # `commit_move_plan` pour la mise en place). Routée ici pour la même raison que
        # `ingress_move` : c'est ce qui lui donne sa fin d'activation.
        return _handle_ingress_commit_action(game_state, active_unit, action)

    elif action_type == "skip":
        # Engine determined unit has no valid actions (e.g. no valid destinations)
        return _handle_skip_action(game_state, active_unit, had_valid_destinations=False)

    elif action_type == "wait":
        # V11 : Stationary humain — terminer l'activation sans bouger (log WAIT).
        return _handle_skip_action(game_state, active_unit, had_valid_destinations=True)
    
    elif action_type == "left_click":
        return movement_click_handler(game_state, unit_id, action)
    
    elif action_type == "right_click":
        if game_state.get("active_movement_unit") is not None:
            return _handle_movement_postpone(game_state, active_unit)
        return _handle_skip_action(game_state, active_unit)
    
    elif action_type == "invalid":
        # Handle invalid actions with training penalty
        # tour_de_jeu.md EXACT: end_activation(ERROR, 0, PASS, MOVE, 1, 1)
        if unit_id in game_state["move_activation_pool"]:
            # Clear preview first
            movement_clear_preview(game_state)
            
            # tour_de_jeu.md EXACT: Invalid actions [shoot, charge, attack] → end_activation(ERROR, 0, PASS, MOVE, 1, 1)
            result = end_activation(
                game_state, active_unit,
                ERROR,       # Arg1: ERROR (not SKIP)
                0,             # Arg2: No step increment (error doesn't count as action)
                PASS,        # Arg3: PASS tracking
                MOVE,        # Arg4: Remove from move pool
                1              # Arg5: Error logging enabled
            )
            result["invalid_action_penalty"] = True
            # No default value - require explicit attempted_action
            attempted_action = action.get("attempted_action")
            if attempted_action is None:
                raise ValueError(f"Action missing 'attempted_action' field: {action}")
            result["attempted_action"] = attempted_action
            return True, result
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    
    else:
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "move"}


def movement_set_advance_mode_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """V11 : déclare l'Advance de l'escouade active (Règles 09.06).

    Lance 1D6 (figé), ajoute l'escouade à ``units_advanced`` et mémorise le jet dans
    ``advance_rolls`` — source unique persistante lue par ``_advance_roll_for`` (budget M+jet
    des pools, commit ``move_type='advance'``, blocage tir/charge). L'Advance survit donc aux
    cancel/ré-activations jusqu'à la phase de commandement suivante. Le déplacement reste piloté
    par le flow squad par-figurine (bloc + placements fins, commit_move_plan).
    """
    unit = require_unit_by_id(game_state, unit_id)
    # 09.03 / 09.06 : une escouade engagée (dans l'Engagement Range d'un ennemi) ne peut pas
    # avancer — elle doit tomber en retraite (Fall Back). Refuser ici plutôt que de le détecter
    # après le fait, c'est le même garde que pour le move normal (09.03, ligne ~1361).
    if _squad_is_in_enemy_er(game_state, str(unit_id)):
        return False, {"error": "unit_engaged", "unitId": unit["id"]}
    # Advance = engagement irréversible : marque l'escouade ``units_advanced`` (bloque tir/charge)
    # et fige son jet dans ``advance_rolls``. Jet figé : un squad déjà advancé réutilise son jet
    # (pas de re-roll), donc le mode survit aux cancel/ré-activations jusqu'à la fin de la phase.
    rolls = game_state.setdefault("advance_rolls", {})
    existing = rolls.get(str(unit_id))
    if existing is not None:
        roll = int(existing)
        game_state["current_advance_roll"] = roll
    else:
        roll = int(roll_advance_for_squad(str(unit_id), game_state))
        rolls[str(unit_id)] = roll
    game_state.setdefault("units_advanced", set()).add(str(unit_id))
    # Reconstruit le pool d'ancre au budget gonflé : le preview rigide (movePreview)
    # s'étend, et le front le re-synchronise depuis game_state. Volontairement hors du
    # result (sinon le flow advancePreview V10 se déclencherait côté front).
    pool = movement_build_valid_destinations_pool(game_state, unit_id)
    return True, {
        "action": "advance_mode_set",
        "unitId": unit["id"],
        "advance_roll": roll,
        "valid_destinations": pool,
        "waiting_for_player": True,
    }


def movement_set_fly_mode_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Take to the skies (Règles 21.03) : (dé)clare le vol de l'escouade FLY active.

    Toggle : ajoute/retire l'escouade de ``units_took_to_skies``. Effet (lu par les pools et le
    commit via ``get_squad_move_budget`` + ``movement_build_valid_destinations_pool``) :
    -2" sur la distance max du move ET traversée des murs/figurines pendant ce déplacement.
    Déclaration faite avant de bouger l'unité ; réversible tant que le move n'est pas commit.
    """
    unit = require_unit_by_id(game_state, unit_id)
    if not _unit_has_keyword(unit, "fly"):
        return False, {"error": "unit_cannot_fly", "unitId": unit["id"]}

    tts = game_state.setdefault("units_took_to_skies", set())
    uid = unit_id
    if uid in tts:
        tts.discard(uid)
        declared = False
    else:
        tts.add(uid)
        declared = True
    # Rebuild le pool au nouveau budget/traversée ; le front re-synchronise depuis game_state.
    pool = movement_build_valid_destinations_pool(game_state, unit_id)
    # Réponse état-complète comme l'activation : le front re-dérive engagement (would_flee) et
    # mode Advance (advance_roll) à partir de la réponse ; les omettre les réinitialiserait.
    return True, {
        "action": "fly_mode_set",
        "unitId": unit["id"],
        "took_to_skies": declared,
        "valid_destinations": pool,
        "waiting_for_player": True,
        "would_flee": bool(_squad_is_in_enemy_er(game_state, str(unit_id))),
        "advance_roll": _advance_roll_for(str(unit_id), game_state),
    }


def _handle_unit_activation(game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """AI_MOVE.md: Unit activation start + execution loop — chemin PvP UNIQUEMENT.

    Le gym ne passe pas par ici : `convert_squad_action` n'émet que des verbes squad, résolus par
    `execute_semantic_action` sans jamais traverser `_process_movement_phase`. La branche gym qui
    vivait ici était morte, et fausse — erreur explicite plutôt que résultat faux, comme le jumeau
    tir (`shooting_handlers.execute_action`, « squad path expected »). Ce que sa présence coûtait
    est verrouillé par `tests/unit/engine/test_move_execution.py::TestGymNeverActivatesThroughThisHandler`.

    Portée du garde : ce handler seul. `execute_action` reste atteignable en gym par `ingress_move`
    (`w40k_core.py`, arrivée de réserves 20.04) — le hisser au routage casserait ce chemin.
    """
    if config.get("gym_training_mode", False) or game_state.get("gym_training_mode", False):
        raise RuntimeError(
            f"_handle_unit_activation reached in gym training — squad path expected. "
            f"unit_id={unit['id']} episode={game_state.get('episode_number')} "
            f"turn={game_state.get('turn')}"
        )

    # Unit activation start
    movement_unit_activation_start(game_state, unit["id"])

    # Unit execution loop (automatic)
    # All non-gym players (humans AND PvE AI) get normal waiting_for_player response
    return movement_unit_execution_loop(game_state, unit["id"])


def movement_unit_activation_start(game_state: Dict[str, Any], unit_id: str) -> None:
    """AI_MOVE.md: Unit activation initialization"""
    game_state["valid_move_destinations_pool"] = []
    game_state["move_preview_footprint_zone"] = set()
    game_state["move_preview_border"] = []
    game_state["preview_hexes"] = []
    game_state["move_preview_footprint_span"] = None
    game_state["active_movement_unit"] = unit_id
    # Le mode Advance d'une escouade vit dans ``units_advanced``/``advance_rolls`` (persistant
    # tout le tour) : rien à nettoyer ici, la ré-activation retrouve le budget M+jet figé.


def movement_unit_execution_loop(game_state: Dict[str, Any], unit_id: str) -> Tuple[bool, Dict[str, Any]]:
    """AI_MOVE.md: Single movement execution (no loop like shooting).

    Appelant UNIQUE : `_handle_unit_activation`, donc chemin PvP seul (cf. son garde).
    """
    unit = require_unit_by_id(game_state, unit_id)
    # Reuse pool if already built (e.g., from execute_action validation)
    # Only rebuild if pool is empty or doesn't exist
    if not game_state.get("valid_move_destinations_pool"):
        movement_build_valid_destinations_pool(game_state, unit_id)
    
    # Check if valid destinations exist
    if not game_state["valid_move_destinations_pool"]:
        # No valid moves - tour_de_jeu.md EXACT: end_activation(NO, 0, PASS, MOVE, 1, 1)
        # Skip = engine-determined "no valid actions", skip_reason for step logger
        movement_clear_preview(game_state)
        result = end_activation(
            game_state, unit,
            NO,         # Arg1: NO (no action taken)
            0,            # Arg2: No step increment (no action)
            PASS,       # Arg3: PASS tracking
            MOVE,       # Arg4: Remove from move_activation_pool
            1             # Arg5: Error logging enabled
        )
        result.update({
            "action": "skip",
            "skip_reason": "no_valid_move_destinations",
            "unitId": unit["id"],
            "activation_complete": True
        })
        return True, result
    
    # Generate preview
    preview_data = movement_preview(game_state["valid_move_destinations_pool"])
    game_state["preview_hexes"] = game_state["valid_move_destinations_pool"]
    
    # Desperate Escape (09.07) : escouade engagée ET battle-shocked → on SUSPEND le move.
    # Pas de preview ; le front affiche un popup d'avertissement, et sa validation déclenche
    # l'action hazard_confirm (hazard 06.03 + attribution 06.02 AVANT de bouger). Une escouade
    # engagée mais saine = Ordered Retreat (aucun hazard) → flux normal ci-dessous.
    engaged_de = _squad_is_in_enemy_er(game_state, str(unit_id))
    shocked_de = bool(require_key(unit, "battle_shocked"))
    if engaged_de and shocked_de:
        # Desperate Escape : résolution SÉQUENTIELLE. Tant que le hazard n'est pas roulé/
        # attribué, l'unité ne doit PAS être en cours de déplacement côté front : aucun pool
        # vert, aucun ghost. movement_clear_preview met aussi active_movement_unit=None, et on
        # le laisse ainsi (les handlers hazard n'en dépendent pas : confirm via action.unitId,
        # allocate via pending_hazard_allocation). _resume_after_hazard re-posera l'unité active
        # + le pool Fall Back une fois les MW attribuées → le flux move normal reprend.
        movement_clear_preview(game_state)
        return True, {
            "action": "requires_hazard",
            "unitId": unit_id,
            "requires_hazard": True,
            "waiting_for_player": True,
        }
    # Human players: return waiting_for_player for destination selection
    return True, {
        "unit_activated": True,
        "unitId": unit_id,  # ADDED: Required for reward calculation
        "valid_destinations": game_state["valid_move_destinations_pool"],
        "preview_data": preview_data,
        "waiting_for_player": True,
        # V11 : engagement de l'escouade dès l'activation (positions PRE-move). Pilote l'UI
        # des modes de deplacement (engagee => Fall-back/Stationary ; non engagee => Move/Advance).
        "would_flee": bool(_squad_is_in_enemy_er(game_state, str(unit_id))),
        # V11 : jet d'Advance figé si l'escouade a déjà advancé ce tour (sinon None) — restaure
        # le badge + l'état « advancé » du bouton à la ré-activation après un cancel.
        "advance_roll": _advance_roll_for(str(unit_id), game_state),
    }


def _attempt_movement_to_destination(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    dest_col: int,
    dest_row: int,
    config: Dict[str, Any],
    orientation: Optional[int] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    tour_de_jeu.md movement execution with destination validation.

    Implements tour_de_jeu.md movement restrictions and flee detection.
    
    Note: Pool is already built in movement_unit_execution_loop() just after activation.
    Since system is sequential, pool is already built and validated.
    However, we still verify critical restrictions here as a safety check.
    """
    # Normalize coordinates to int - raises error if invalid
    dest_col_int, dest_row_int = normalize_coordinates(dest_col, dest_row)

    # Store original position
    orig_col, orig_row = require_unit_position(unit, game_state)

    # Flee detection: was adjacent to enemy before move
    was_adjacent = _squad_is_in_enemy_er(game_state, str(unit["id"]))

    # Final footprint-aware occupation check IMMEDIATELY before position assignment.
    # Prevents race conditions from reactive moves between pool build and commit.
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    phase = game_state.get("phase", "move")

    import time as _mct
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled
    _mct_pt = perf_timing_enabled(game_state)
    _mct0 = _mct.perf_counter() if _mct_pt else None

    unit_id_str = str(unit["id"])
    footprint_unit = unit
    if orientation is not None:
        footprint_unit = {
            "BASE_SHAPE": unit["BASE_SHAPE"],
            "BASE_SIZE": unit["BASE_SIZE"],
            "orientation": orientation,
        }
    candidate_fp = compute_candidate_footprint(dest_col_int, dest_row_int, footprint_unit, game_state)
    _mct1 = _mct.perf_counter() if _mct_pt else None
    if not is_placement_valid_with_clearance(
        game_state, candidate_fp,
        shape=footprint_unit["BASE_SHAPE"], base_size=footprint_unit["BASE_SIZE"],
        col=dest_col_int, row=dest_row_int, orientation=socle_orientation(footprint_unit),
        exclude_unit_id=unit_id_str,
    ):
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        log_msg = f"[MOVE COLLISION PREVENTED] E{episode} T{turn} {phase}: Unit {unit['id']} cannot move to ({dest_col_int},{dest_row_int}) - footprint blocked"
        from engine.game_utils import add_console_log, safe_print
        add_console_log(game_state, log_msg)
        safe_print(game_state, log_msg)
        return False, {
            "error": "destination_occupied",
            "destination": (dest_col_int, dest_row_int)
        }

    # Re-validate against enemy engagement zone at commit time (euclidien bord à bord ×10).
    units_cache = require_key(game_state, "units_cache")
    _mct2_pre = _mct.perf_counter() if _mct_pt else None
    if _movement_engagement_violates(
        game_state,
        unit,
        dest_col_int,
        dest_row_int,
        candidate_fp,
        units_cache,
        None,
    ):
        blocking_eid: Optional[str] = None
        ez_blk = get_engagement_zone(game_state)
        mover_player_int = int(require_key(unit, "player"))
        mover_id_str = str(require_key(unit, "id"))
        if ez_blk >= 1:
            for eid, cache_entry in enemy_entries_on_battlefield(
                units_cache, mover_player_int, exclude_id=mover_id_str
            ):
                enemy_fp = entry_footprint(cache_entry)
                if min_distance_between_sets(candidate_fp, enemy_fp, max_distance=ez_blk) <= ez_blk:
                    blocking_eid = str(eid)
                    break
        return False, {
            "error": "destination_adjacent_to_enemy",
            "enemy_id": blocking_eid,
            "destination": (dest_col_int, dest_row_int),
        }

    _mct2 = _mct.perf_counter() if _mct_pt else None

    # Execute movement - position assignment
    # Log ALL position changes to detect unauthorized modifications
    # ALWAYS log, even if episode_number/turn/phase are missing (for debugging)
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    log_message = f"[POSITION CHANGE] E{episode} T{turn} {phase} Unit {unit['id']}: ({orig_col},{orig_row})→({dest_col_int},{dest_row_int}) via MOVE"
    from engine.game_utils import add_console_log
    from engine.game_utils import safe_print
    add_console_log(game_state, log_message)
    safe_print(game_state, log_message)
    
    # Log BEFORE each assignment to catch any modification
    from engine.game_utils import conditional_debug_print
    conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: Setting col={dest_col_int} row={dest_row_int}")
    # Assign normalized int coordinates using set_unit_coordinates
    set_unit_coordinates(unit, dest_col_int, dest_row_int)
    conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: row set to {unit['row']}")

    # Capture old footprint before cache update (for multi-hex adjacency delta)
    unit_id_str_cache = str(unit["id"])
    old_cache_entry = require_key(game_state, "units_cache").get(unit_id_str_cache)
    old_occupied = old_cache_entry.get("occupied_hexes") if old_cache_entry else None

    if orientation is not None:
        unit["orientation"] = orientation
        cache_entry = require_key(game_state, "units_cache").get(unit_id_str_cache)
        if cache_entry is None:
            raise KeyError(f"units_cache missing moved unit {unit_id_str_cache}")
        cache_entry["orientation"] = orientation
        # Move rigide d'unité = orientation COMMUNE → propager à CHAQUE figurine : le footprint
        # persistant est recalculé par-fig (_recompute_squad_occupied_hexes lit model["orientation"]),
        # sans ça le pivot de l'unité serait ignoré par l'empreinte réelle.
        _mc_ori = require_key(game_state, "models_cache")
        for _mid in require_key(game_state, "squad_models").get(unit_id_str_cache, []):  # get allowed
            _m_ori = _mc_ori.get(_mid)
            if _m_ori is not None:
                _m_ori["orientation"] = orientation

    # Squad move rigide = destination TOUJOURS au sol. Resynchroniser level=0 sur toutes les figs
    # vivantes AVANT la translation : translate_squad_to_destination → _recompute_squad_occupied_hexes
    # appelle floor_height_at(level), qui lèverait ValueError si une fig partie de l'étage restait
    # marquée level>=1 alors que sa case translatée n'appartient plus à l'empreinte de l'étage (13.06).
    _mc_lvl = require_key(game_state, "models_cache")
    _sq_lvl = require_key(game_state, "squad_models")
    for _mid in _sq_lvl.get(unit_id_str_cache, []):  # get allowed
        _m = _mc_lvl.get(_mid)
        if _m is None or int(_m.get("HP_CUR", 0)) <= 0:  # get allowed
            continue
        _m["level"] = 0
    _uc_lvl = require_key(game_state, "units_cache").get(unit_id_str_cache)
    if _uc_lvl is not None:
        _uc_lvl["level"] = 0
    unit["level"] = 0

    # Update units_cache after position change.
    # Use translate_squad_to_destination for rigid squad movement: anchor + all
    # surviving models translate by the same delta, occupied_hexes_by_model is
    # resync'd from updated models_cache. This is the move-action semantic.
    translate_squad_to_destination(game_state, unit_id_str_cache, dest_col_int, dest_row_int)

    # Retrieve new footprint from updated cache
    new_cache_entry = require_key(game_state, "units_cache").get(unit_id_str_cache)
    new_occupied = new_cache_entry.get("occupied_hexes") if new_cache_entry else None

    _mct3 = _mct.perf_counter() if _mct_pt else None

    # Keep enemy adjacency caches synchronized incrementally with the move.
    moved_unit_player = int(require_key(unit, "player"))
    update_enemy_adjacent_caches_after_unit_move(
        game_state,
        moved_unit_player=moved_unit_player,
        old_col=orig_col,
        old_row=orig_row,
        new_col=dest_col_int,
        new_row=dest_row_int,
        old_occupied=old_occupied,
        new_occupied=new_occupied,
    )

    _mct4 = _mct.perf_counter() if _mct_pt else None

    # Apply tour_de_jeu.md tracking
    # Normalize unit ID to string for consistent storage (units_fled stores strings)
    unit_id_str = str(unit["id"])
    game_state["units_moved"].add(unit_id_str)
    # Source unique du marquage de fuite (partagée avec le commit par-figurine PvP).
    # units_fled est un sous-ensemble de units_moved.
    flee_action = finalize_flee_marking(game_state, unit_id_str, was_adjacent)

    # LoS : invalidation ciblée + bump désormais centralisés dans translate_squad_to_destination
    # → update_units_cache_position → _touch_unit_los (choke-point a′). Plus de bump manuel ici.

    _mct5 = _mct.perf_counter() if _mct_pt else None
    if _mct_pt and _mct0 is not None and _mct1 is not None and _mct2_pre is not None and _mct2 is not None and _mct3 is not None and _mct4 is not None and _mct5 is not None:
        append_perf_timing_line(
            f"MOVE_COMMIT_TIMING episode={episode} turn={turn} unitId={unit_id_str!r} phase={phase} "
            f"occ_build_s={_mct1 - _mct0:.6f} eng_check_s={_mct2 - _mct2_pre:.6f} "
            f"pos_update_s={_mct3 - _mct2:.6f} adj_cache_s={_mct4 - _mct3:.6f} "
            f"los_cache_s={_mct5 - _mct4:.6f} total_s={_mct5 - _mct0:.6f}"
        )

    # Pools are invalidated at the START of the phase, not after each movement
    # This prevents invalidating the "moved" tracking of units that just moved

    # Log successful movement
    action_type = flee_action.upper()
    _log_movement_debug(game_state, "attempt_movement", str(unit["id"]), f"({orig_col},{orig_row})→({dest_col_int},{dest_row_int}) SUCCESS {action_type}")

    # Use normalized coordinates (dest_col_int, dest_row_int) in result
    # NOT dest_col/dest_row which might not be normalized
    return True, {
        "action": flee_action,
        "unitId": unit["id"],
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col_int,  # Use normalized coordinates
        "toRow": dest_row_int    # Use normalized coordinates
    }


def _is_in_enemy_engagement_zone(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    tour_de_jeu.md flee detection logic.

    Check if unit is adjacent to enemy for flee marking.

    Uses proper hexagonal distance, not Chebyshev distance.
    For CC_RNG=1 (typical), this means checking if enemy is in 6 neighbors.
    For CC_RNG>1, use hex distance calculation.
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Melee range is always 1.
    """
    unit_id_str = str(unit["id"])
    units_cache = require_key(game_state, "units_cache")
    unit_entry = require_unit_from_cache(
        unit_id_str, game_state, "_is_in_enemy_engagement_zone"
    )
    unit_col, unit_row = int(unit_entry["col"]), int(unit_entry["row"])
    unit_fp = entry_footprint(unit_entry)

    cache_key = f"enemy_adjacent_hexes_player_{int(require_key(unit, 'player'))}"
    enemy_adj = game_state.get(cache_key)

    result = _movement_engagement_violates(
        game_state,
        unit,
        unit_col,
        unit_row,
        unit_fp,
        units_cache,
        enemy_adj if isinstance(enemy_adj, set) else None,
    )
    
    # Log adjacency check result
    _log_movement_debug(game_state, "is_adjacent_to_enemy", str(unit["id"]), f"ADJACENT" if result else "NOT_ADJACENT")

    return result


def finalize_flee_marking(game_state: Dict[str, Any], squad_id: str, was_engaged: bool) -> str:
    """Source unique du marquage de fuite, partagée par les deux chemins de commit move :
    le move rigide à l'ancre (``_attempt_movement_to_destination``) et le commit du plan
    par-figurine PvP (``movement_commit_move_plan_handler``).

    ``was_engaged`` est détecté en amont sur les positions PRÉ-déplacement via
    ``_squad_is_in_enemy_er`` (≥ 1 figurine de l'escouade dans l'Engagement Range d'une
    figurine ennemie — règle 09.07, toutes figs). Si vrai, l'escouade est ajoutée à
    ``units_fled``. À appeler APRÈS un déplacement réussi.

    Retourne le libellé d'action : "flee" si fuite, sinon "move".
    """
    squad_id_str = str(squad_id)
    if was_engaged:
        game_state["units_fled"].add(squad_id_str)
    return "flee" if was_engaged else "move"


#: Pas VERTICAL entre deux lignes dans le repère `_hex_center` (flat-top, hex_radius=1).
_HEX_ROW_STEP = math.sqrt(3.0)


@lru_cache(maxsize=8)
def _hex_center_grids(board_cols: int, board_rows: int) -> Tuple["np.ndarray", "np.ndarray"]:
    """Centres euclidiens (repère ``_hex_center``) de toutes les cases.

    ``grid_x`` est ``(cols, 1)`` : l'abscisse ne dépend que de la colonne, la matérialiser en
    ``(cols, rows)`` était 528 Ko de float64 recopiés pour rien. ``grid_y``, lui, reste
    ``(cols, rows)`` : l'ordonnée dépend de la PARITÉ de colonne (décalage d'une demi-ligne une
    colonne sur deux), donc il n'est pas séparable. Les deux se combinent par broadcast dans une
    même tranche ``[c0:c1, r0:r1]``.

    Source UNIQUE du plongement case -> monde de ce module, qui en portait trois copies.
    Mémoïsé : les deux tableaux pèsent 528 Ko pour 220×300 et ne dépendent que des dimensions
    du plateau, qui ne changent jamais en cours de run. Les appelants lisent uniquement
    (tranches en lecture seule) — aucune mutation possible.
    """
    cols = np.arange(board_cols, dtype=np.float64)[:, None]
    rows = np.arange(board_rows, dtype=np.float64)[None, :]
    grid_x = cols * 1.5 + 1.5 / 2.0
    grid_y = rows * _HEX_ROW_STEP + ((cols.astype(np.int64) & 1) * _HEX_ROW_STEP) / 2.0 + _HEX_ROW_STEP / 2.0
    grid_x.flags.writeable = False
    grid_y.flags.writeable = False
    return grid_x, grid_y


def _stamp_disc_into(
    dst: "np.ndarray", grid_x: "np.ndarray", grid_y: "np.ndarray",
    source_col: int, source_row: int, reach: float, board_cols: int, board_rows: int,
) -> Tuple[int, int, int, int]:
    """Marque ``True`` toute case dont le CENTRE est à ``reach`` ou moins de ``(source_col,
    source_row)``, et rend la fenêtre ``(c0, c1, r0, r1)`` réellement touchée.

    Bornée en bbox par source : le disque ne balaye jamais le plateau entier. Rendre la fenêtre
    évite à l'appelant de rebalayer le plateau pour retrouver ce qui vient d'être marqué.
    """
    if reach <= 0:
        return (0, 0, 0, 0)
    ex = source_col * 1.5 + 1.5 / 2.0
    ey = source_row * _HEX_ROW_STEP + ((source_col & 1) * _HEX_ROW_STEP) / 2.0 + _HEX_ROW_STEP / 2.0
    dcol = int(reach / 1.5) + 1
    drow = int(reach / _HEX_ROW_STEP) + 1
    c0, c1 = max(0, source_col - dcol), min(board_cols, source_col + dcol + 1)
    r0, r1 = max(0, source_row - drow), min(board_rows, source_row + drow + 1)
    if c0 >= c1 or r0 >= r1:
        return (0, 0, 0, 0)
    dx = grid_x[c0:c1] - ex           # (c1-c0, 1)
    dy = grid_y[c0:c1, r0:r1] - ey    # (c1-c0, r1-r0)
    dst[c0:c1, r0:r1] |= (dx * dx + dy * dy) <= (reach * reach + 1e-9)
    return (c0, c1, r0, r1)


#: Demi-largeur de l'anneau d'AMBIGUÏTÉ NUMÉRIQUE autour du seuil d'engagement, en unités
#: ``_hex_center``. ``_ez_offset_kernels`` mesure la clairance d'un couple de socles placé à une
#: ORIGINE canonique, l'exécution la mesure aux coordonnées réelles du plateau : les deux calculs
#: sont algébriquement identiques, pas bit-à-bit (les contours sont construits à partir de
#: ``_hex_center``, dont les ordonnées passent par ``√3 × row``). Toute case dont la clairance
#: tombe dans ``seuil ± EPS`` est donc RE-MESURÉE à sa position réelle par
#: ``_resolve_ez_ties_exactly``, jamais tranchée depuis le noyau.
#:
#: Écart MESURÉ entre les deux calculs : 2,49e-13 au pire sur 277 248 comparaisons (six formes
#: de socle croisées, quatre orientations, deux parités, trois coins du plateau) — EPS garde donc
#: un facteur 4e6 de réserve, et reste treize ordres SOUS la plus petite distance que le jeu
#: distingue (1 subhex = 1,5). Le balayage est rejoué par
#: `test_move_ez_non_round_bases.py::test_the_tie_band_bounds_the_kernel_error`. L'élargir ne peut
#: pas fausser un verdict — elle n'agrandit que l'ensemble re-mesuré exactement, au prix de
#: quelques microsecondes ; la réduire sous le bruit, si.
EZ_KERNEL_TIE_EPS_NORM = 1e-6


def _hashable_base_size(base_size: Any) -> Any:
    """Clé de mémo d'une taille de socle : ``[20, 14]`` n'est pas hachable, ``(20, 14)`` l'est."""
    return tuple(base_size) if isinstance(base_size, list) else base_size


#: Un noyau coûte ~40 ms à construire et ~7 Ko à garder : la borne doit couvrir TOUS les couples
#: réellement joués, sinon l'éviction en repaie un à chaque masque. Le compte est
#: ``|géométries mover| × |géométries ennemi| × 2 parités``, et l'ORIENTATION multiplie chaque
#: côté par 6 — quatre tailles de socle de chaque côté suffisent donc à en demander ~1 150.
#: 4 096 laisse la marge, pour ~28 Mo au pire ; c'est de la géométrie pure, jamais de l'état.
@lru_cache(maxsize=4096)
def _ez_offset_kernels(
    mover_shape: str,
    mover_bs: Any,
    mover_orient: int,
    enemy_shape: str,
    enemy_bs: Any,
    enemy_orient: int,
    ez_norm: float,
    enemy_col_is_even: bool,
) -> Tuple["np.ndarray", "np.ndarray", int, int]:
    """Noyau des offsets ``(dcol, drow)`` qu'UNE figurine ennemie interdit — somme de Minkowski.

    POURQUOI UN NOYAU SUFFIT. ``euclidean_edge_distance`` ne lit que forme, taille, orientation
    et CENTRE des deux socles (vérifié : ``fp=None`` ne change rien à son résultat). Or le centre
    vient de ``_hex_center``, affine en ``(col, row)`` à une exception près : l'ordonnée est
    décalée d'une demi-ligne une colonne sur deux. L'écart entre les deux centres ne dépend donc
    que de ``(dcol, drow)`` et de la PARITÉ de la colonne ennemie — pas de la position absolue.
    À couple de géométries fixé, l'ensemble des ancres interdites est donc le MÊME motif
    translaté : on le calcule une fois, puis on l'estampe autour de chaque figurine ennemie
    exactement comme ``_stamp_disc_into`` estampe un disque.

    Ce qui remplace : la version précédente encadrait le contour par la distance entre centres de
    cellules et payait le contour sur toute une FRANGE de trois cases de large, soit
    ``|frange| × |ennemis|`` mesures par masque. Ici le contour n'est mesuré que
    ``|géométries| × 2`` fois pour toute la partie, et le masque ne fait plus que des ``|=``.

    Retourne ``(sure, tie, dcol_max, drow_max)`` : ``sure`` = offsets interdits sans discussion
    (clairance ``<= seuil - EPS``), ``tie`` = offsets dont la clairance est à moins de ``EPS`` du
    seuil, que l'appelant doit re-mesurer à la position réelle (cf. ``EZ_KERNEL_TIE_EPS_NORM``).
    Les deux tableaux sont indexés ``[dcol + dcol_max, drow + drow_max]``.

    BORNE DU NOYAU. La clairance bord-à-bord vaut au moins ``écart des centres - r_mover -
    r_ennemi`` (chaque contour tient dans son disque circonscrit), donc aucune ancre dont le
    centre est à plus de ``seuil + r_mover + r_ennemi`` ne peut être interdite. Les demi-largeurs
    en dérivent, arrondies vers le haut : la première case exclue est au moins à 1,5 unité
    au-delà de la borne, très loin de ``EPS``.
    """
    from engine.hex_utils import (
        Socle, _oval_local_outline, _square_local_outline,
        _batch_poly_poly_dist, _batch_circle_poly_dist, _batch_poly_circle_dist,
    )

    mover_size = list(mover_bs) if isinstance(mover_bs, tuple) else mover_bs
    enemy_size = list(enemy_bs) if isinstance(enemy_bs, tuple) else enemy_bs
    # Origine canonique : seule la PARITÉ de la colonne ennemie compte (cf. docstring).
    origin_col, origin_row = (100 if enemy_col_is_even else 101), 100
    mover_radius = Socle(
        shape=mover_shape, base_size=mover_size, col=0, row=0, fp=None,
        orientation=mover_orient,
    ).bounding_radius()
    enemy_radius = Socle(
        shape=enemy_shape, base_size=enemy_size, col=origin_col, row=origin_row,
        fp=None, orientation=enemy_orient,
    ).bounding_radius()
    reach = ez_norm + mover_radius + enemy_radius
    dcol_max = int(reach / 1.5) + 1
    drow_max = int(reach / _HEX_ROW_STEP) + 1

    EPS = EZ_KERNEL_TIE_EPS_NORM
    W = 2 * dcol_max + 1
    H = 2 * drow_max + 1

    # ── Distances centre-à-centre vectorisées ─────────────────────────────────────────────
    sqrt3 = _HEX_ROW_STEP
    dcol_int = np.arange(-dcol_max, dcol_max + 1, dtype=np.int64)   # (W,)
    drow_f   = np.arange(-drow_max, drow_max + 1, dtype=np.float64) # (H,)
    dx_1d = dcol_int.astype(np.float64) * 1.5
    parity_sign = 1.0 if enemy_col_is_even else -1.0
    parity_cor  = (dcol_int & 1).astype(np.float64) * parity_sign * (sqrt3 / 2.0)
    dy_2d = drow_f[np.newaxis, :] * sqrt3 + parity_cor[:, np.newaxis]  # (W, H)
    center_dist = np.hypot(dx_1d[:, np.newaxis], dy_2d)                 # (W, H)

    # ── Élagage par disques circonscrits ─────────────────────────────────────────────────
    lower          = center_dist - mover_radius - enemy_radius  # (W, H)
    candidate_mask = lower <= ez_norm + EPS                     # (W, H)

    sure = np.zeros((W, H), dtype=bool)
    tie  = np.zeros((W, H), dtype=bool)
    nz_i, nz_j = np.nonzero(candidate_mask)
    N = len(nz_i)
    if N == 0:
        return sure, tie, dcol_max, drow_max

    # ── Centres absolus des candidats ────────────────────────────────────────────────────
    cx_enemy, cy_enemy = _hex_center(origin_col, origin_row)
    cx_cand = cx_enemy + dx_1d[nz_i]          # (N,)
    cy_cand = cy_enemy + dy_2d[nz_i, nz_j]   # (N,)

    # ── Contours géométriques (polygone relatif ou rayon) ────────────────────────────────
    mover_rel: "np.ndarray | None"
    r_mover: "float | None" = None
    if mover_shape == "oval":
        mover_rel = np.array(_oval_local_outline(mover_size[0], mover_size[1], mover_orient))
    elif mover_shape == "square":
        ms: float = mover_size[0] if isinstance(mover_size, list) else mover_size
        mover_rel = np.array(_square_local_outline(ms, mover_orient))
    else:
        mover_rel = None  # round
        r_mover = round_base_radius_norm(
            mover_size if not isinstance(mover_size, list) else mover_size[0]
        )

    enemy_abs: "np.ndarray | None"
    r_enemy: "float | None" = None
    if enemy_shape == "oval":
        enemy_rel = np.array(_oval_local_outline(enemy_size[0], enemy_size[1], enemy_orient))
        enemy_abs = enemy_rel + np.array([cx_enemy, cy_enemy])
    elif enemy_shape == "square":
        es: float = enemy_size[0] if isinstance(enemy_size, list) else enemy_size
        enemy_rel = np.array(_square_local_outline(es, enemy_orient))
        enemy_abs = enemy_rel + np.array([cx_enemy, cy_enemy])
    else:
        enemy_abs = None  # round
        r_enemy = round_base_radius_norm(
            enemy_size if not isinstance(enemy_size, list) else enemy_size[0]
        )

    # ── Dispatch vectorisé ───────────────────────────────────────────────────────────────
    if mover_rel is None and enemy_abs is None:
        # round × round
        assert r_mover is not None and r_enemy is not None
        gaps = np.sqrt((cx_cand - cx_enemy) ** 2 + (cy_cand - cy_enemy) ** 2) - r_mover - r_enemy
    elif mover_rel is None:
        # round mover × poly enemy
        assert r_mover is not None and enemy_abs is not None
        gaps = _batch_circle_poly_dist(r_mover, enemy_abs, cx_cand, cy_cand)
    elif enemy_abs is None:
        # poly mover × round enemy
        assert r_enemy is not None
        gaps = _batch_poly_circle_dist(mover_rel, r_enemy, cx_enemy, cy_enemy, cx_cand, cy_cand)
    else:
        # poly × poly
        gaps = _batch_poly_poly_dist(mover_rel, enemy_abs, cx_cand, cy_cand)

    sure[nz_i, nz_j] = gaps <= ez_norm - EPS
    tie[nz_i, nz_j]  = (gaps > ez_norm - EPS) & (gaps <= ez_norm + EPS)
    return sure, tie, dcol_max, drow_max


def _stamp_kernel_into(
    dst: "np.ndarray", kernel: "np.ndarray", dcol_max: int, drow_max: int,
    source_col: int, source_row: int, board_cols: int, board_rows: int,
) -> None:
    """``OR`` du noyau ``_ez_offset_kernels`` centré sur ``(source_col, source_row)``, clippé au plateau."""
    c0, c1 = source_col - dcol_max, source_col + dcol_max + 1
    r0, r1 = source_row - drow_max, source_row + drow_max + 1
    k_c0, k_r0 = max(0, -c0), max(0, -r0)
    k_c1 = kernel.shape[0] - max(0, c1 - board_cols)
    k_r1 = kernel.shape[1] - max(0, r1 - board_rows)
    if k_c0 >= k_c1 or k_r0 >= k_r1:
        return
    dst[max(0, c0):min(board_cols, c1), max(0, r0):min(board_rows, r1)] |= kernel[
        k_c0:k_c1, k_r0:k_r1
    ]


def _resolve_ez_ties_exactly(
    eng_bad: "np.ndarray",
    mover_shape: str,
    mover_bs: Any,
    mover_orient: int,
    tie_sites: List[Tuple[int, int, "np.ndarray", int, int, str, Any, int]],
    ez_norm: float,
    board_cols: int,
    board_rows: int,
) -> None:
    """Tranche EN PLACE les ancres que le noyau a laissées ambiguës, à leur position RÉELLE.

    Une case est ambiguë PAR RAPPORT À UNE FIGURINE ennemie précise, celle dont le noyau l'a
    signalée : on ne la re-mesure donc que contre CELLE-LÀ, jamais contre toute la liste ennemie.
    Le calcul est mot pour mot celui que ``entries_in_engagement_zone`` fait au commit du move,
    aux MÊMES coordonnées — c'est ce qui interdit au masque et à l'exécution de se répondre
    différemment sur une égalité flottante.

    ``fp=None`` : la clairance EUCLIDIENNE ne lit PAS l'empreinte — elle passe par
    `_socle_edge_primitives` (contours) et `_socle_bounding_circles`, qui ne dépendent que de
    forme/taille/orientation/centre. Vérifié plutôt que déduit d'une docstring : écart maximal nul
    entre socles avec et sans empreinte sur 2 300 configurations (oval/carré/rond, trois
    orientations). Construire les 187 cases d'un socle oval par ancre testée était le poste de
    coût dominant de la passe exacte, pour un résultat inchangé.
    """
    from engine.hex_utils import Socle, euclidean_edge_distance

    for ec, er, tie, dcol_max, drow_max, e_shape, e_bs, e_orient in tie_sites:
        enemy_socle = Socle(
            shape=e_shape, base_size=e_bs, col=ec, row=er, fp=None, orientation=e_orient,
        )
        for i, j in zip(*np.nonzero(tie)):
            col, row = ec + int(i) - dcol_max, er + int(j) - drow_max
            if not (0 <= col < board_cols and 0 <= row < board_rows) or eng_bad[col, row]:
                continue
            mover_socle = Socle(
                shape=mover_shape, base_size=mover_bs, col=col, row=row, fp=None,
                orientation=mover_orient,
            )
            if euclidean_edge_distance(mover_socle, enemy_socle, max_distance=ez_norm) <= ez_norm:
                eng_bad[col, row] = True


def _euclidean_mover_ez_forbidden_mask(
    unit: Dict[str, Any],
    enemy_items: Optional[List[Tuple[Any, Any]]],
    ez: int,
    board_cols: int,
    board_rows: int,
) -> "np.ndarray":
    """Masque EZ euclidien (Étape 7.2) — miroir vectorisé de ``entries_in_engagement_zone(euclidean)``.

    ``eng_bad[c, r]`` ⇔ placer l'ANCRE du mover en ``(c, r)`` met son socle à un écart bord-à-bord
    euclidien ≤ ``engagement_minimum_clearance_norm(ez)`` (= ez × 1,5) d'un socle ennemi.
    Sémantique identique à ``euclidean_edge_distance`` DANS LES DEUX CAS : paire ronde↔ronde =
    clearance continu exact (centre + rayon), vectorisé par disque NumPy borné en bbox ; paire
    impliquant un socle NON ROND = contours continus eux aussi, estampés par NOYAU DE MINKOWSKI
    (``_ez_offset_kernels``), une seule mesure de contour par couple de géométries pour toute la
    partie. Les rares égalités flottantes que le noyau ne peut pas trancher sont re-mesurées à
    leur position réelle (``_resolve_ez_ties_exactly``).
    """
    from engine.hex_utils import (
        engagement_minimum_clearance_norm,
        round_base_radius_norm,
    )

    ez_norm = engagement_minimum_clearance_norm(ez)
    eng_bad = np.zeros((board_cols, board_rows), dtype=bool)
    enemy_list = enemy_items if enemy_items is not None else []
    if not enemy_list or ez_norm <= 0:
        return eng_bad

    # Grille des centres de cellules (repère _hex_center) et tampon de disque : source UNIQUE,
    # partagée avec le masque de clearance des réserves (20.04), qui mesure la même chose à une
    # autre distance. Ce bloc en était une copie littérale.
    grid_x, grid_y = _hex_center_grids(board_cols, board_rows)

    def _stamp_disc(dst: "np.ndarray", sc: int, sr: int, reach: float) -> None:
        _stamp_disc_into(dst, grid_x, grid_y, sc, sr, reach, board_cols, board_rows)

    # Le mover passe par la MÊME garde que les ennemis dix lignes plus bas : sa taille de
    # socle est lue selon la forme déclarée, jamais affirmée par un cast.
    mover_shape = require_key(unit, "BASE_SHAPE")
    mover_bs = require_base_size(
        mover_shape, require_key(unit, "BASE_SIZE"), f"units_cache mover {unit.get('id', '?')}"
    )
    mover_round = mover_shape == "round"
    r_m = round_base_radius_norm(
        require_scalar_base_size(mover_shape, mover_bs, "engagement mask mover")
    ) if mover_round else 0.0

    # Dispatch identique à euclidean_edge_distance : round↔round (les DEUX ronds) = clearance
    # continu exact (centre + rayons), un disque par figurine ennemie ; toute paire impliquant un
    # non-rond = contours continus, estampés par NOYAU (cf. `_ez_offset_kernels`). Dans les deux
    # cas le motif ne dépend que du couple de géométries : il est calculé une fois puis translaté.
    mover_orient = int(require_key(unit, "orientation")) if "orientation" in unit else 0
    mover_bs_key = _hashable_base_size(mover_bs)
    tie_sites: List[Tuple[int, int, "np.ndarray", int, int, str, Any, int]] = []
    for _, ce in enemy_list:
        e_shape = require_key(ce, "BASE_SHAPE")
        e_bs = require_base_size(
            e_shape, require_key(ce, "BASE_SIZE"), f"units_cache enemy {ce.get('id', '?')}"
        )
        by_model = ce.get("occupied_hexes_by_model")
        model_positions = list(by_model.values()) if by_model else [
            (int(require_key(ce, "col")), int(require_key(ce, "row")))
        ]
        if mover_round and e_shape == "round":
            r_e = round_base_radius_norm(
                require_scalar_base_size(e_shape, e_bs, "engagement mask enemy")
            )
            for ec, er in model_positions:
                _stamp_disc(eng_bad, int(ec), int(er), ez_norm + r_m + r_e)
            continue
        # ── Paire impliquant un socle NON ROND ────────────────────────────────────────────────
        # Le prédicat de la règle est `euclidean_edge_distance` (contours continus), et il est
        # appliqué TEL QUEL ici : pas d'approximation par centres de cellules, qui sous-estimait
        # l'EZ d'environ une case et laissait un WarTrakk (socle oval 20×14) finir son move
        # engagé, 09.05 violé, pendant que le masque disait « libre » (témoin E8 du 2026-08-09).
        e_orient = int(require_key(ce, "orientation"))
        e_bs_key = _hashable_base_size(e_bs)
        for ec, er in model_positions:
            ec, er = int(ec), int(er)
            sure, tie, dcol_max, drow_max = _ez_offset_kernels(
                mover_shape, mover_bs_key, mover_orient,
                e_shape, e_bs_key, e_orient, ez_norm, (ec & 1) == 0,
            )
            _stamp_kernel_into(eng_bad, sure, dcol_max, drow_max, ec, er, board_cols, board_rows)
            if tie.any():
                tie_sites.append((ec, er, tie, dcol_max, drow_max, e_shape, e_bs, e_orient))

    if tie_sites:
        # Égalités flottantes : le noyau les a signalées sans les trancher. On les re-mesure à
        # leur position réelle — là où l'exécution les mesurera aussi — APRÈS la boucle, pour
        # sauter celles qu'une autre figurine ennemie a déjà rendues interdites.
        _resolve_ez_ties_exactly(
            eng_bad, mover_shape, mover_bs, mover_orient, tie_sites, ez_norm,
            board_cols, board_rows,
        )

    return eng_bad


def _compute_mover_ez_forbidden_mask(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    enemy_items: Optional[List[Tuple[Any, Any]]],
    ez: int,
    board_cols: int,
    board_rows: int,
) -> "np.ndarray":
    """Masque ``(board_cols, board_rows)`` des ancres dont le placement du mover viole l'EZ ennemie.

    Source UNIQUE de la géométrie d'engagement (Board ×N, ``ez > 1``), partagée par le path IA
    vectorisé (``_build_multi_hex_vectorized``) et le path PvP par-figurine
    (``movement_build_model_destinations_pool`` / voile rouge). Garantit IA == PvP.

    Sémantique (identique à ``move_anchor_violates_engagement_clearance``) :
      - Paire **mover rond ↔ ennemi rond** : écart bord à bord euclidien (centres ``_hex_center``)
        ≥ ``engagement_minimum_clearance_norm(ez)``.
      - Sinon (mover non-rond ou ennemi non-rond) : MÊME clearance continue, mesurée sur les
        contours (``euclidean_edge_distance``) et non plus sur les centres de cellules — ces
        derniers ne servent qu'à borner la frange à évaluer exactement. C'est ce qui aligne ce
        masque sur ``entries_in_engagement_zone``, le prédicat de la phase de combat.

    ``eng_bad[c, r] == True`` ⇔ placer l'ANCRE du mover en ``(c, r)`` viole l'EZ (empreinte du
    mover déjà prise en compte). À tester au niveau ancre, ne PAS re-dilater par l'empreinte.

    Métrique (Étape 7) : ``engagement:"euclidean"`` → disque euclidien vectorisé
    (``_euclidean_mover_ez_forbidden_mask``) ; ``"hex"`` (défaut) → dilatation hex ci-dessous.
    """
    from engine.spatial_relations import engagement_distance_metric
    if engagement_distance_metric(game_state) == "euclidean":
        # MÉMOÏSÉ PAR ÉTAT. Le masque ne dépend que des positions ennemies et de la géométrie du
        # socle posé — jamais de l'unité qui le demande. Or il est reconstruit par CHAQUE
        # consommateur : les trois chemins de pool, plus la validation et l'érosion. Deux unités
        # de la même datasheet, dans le même état, en recalculaient deux exemplaires identiques.
        #
        # La clé est le FINGERPRINT D'ÉTAT partagé (`_move_spatial_cache`), pas un compteur de
        # version : un compteur a déjà causé une régression masque⊆exécutable (§0.18) parce
        # qu'un chemin d'écriture de position ne le bumpait pas. Le fingerprint capture les
        # positions ET les zones d'engagement, donc tout ce dont ce masque dépend.
        from engine.phase_handlers.shared_utils import _move_spatial_cache, move_geom_key
        _cache = _move_spatial_cache(game_state).setdefault("ez_mask", {})
        _key = (
            move_geom_key(unit),
            int(ez), int(board_cols), int(board_rows),
            # Identité de la LISTE ennemie fournie : les appelants passent des sous-ensembles
            # élagués (`_enemy_items_within_move_engagement_horizon`). Deux élagages différents
            # au même état ne rendent PAS le même masque — les confondre offrirait des cases
            # interdites.
            None if enemy_items is None else tuple(sorted(str(_u) for _u, _ in enemy_items)),
        )
        _hit = _cache.get(_key)
        if _hit is None:
            _hit = _euclidean_mover_ez_forbidden_mask(
                unit, enemy_items, ez, board_cols, board_rows
            )
            # NON INSCRIPTIBLE : rendu par référence, donc une mutation par un appelant
            # corromprait le masque de tous les autres. Les quatre consommateurs actuels sont en
            # lecture (`~mask`, `|`, `np.where`, `np.argwhere`) ; le drapeau fait LEVER le
            # cinquième au lieu de le laisser fausser des destinations en silence.
            _hit.flags.writeable = False
            _cache[_key] = _hit
        return _hit

    from engine.hex_utils import (
        engagement_minimum_clearance_norm,
        round_base_radius_norm,
        _hex_center,
        precompute_footprint_offsets,
    )

    mover_shape = unit["BASE_SHAPE"]
    mover_bs_i = unit["BASE_SIZE"]
    if "orientation" in unit:
        mover_orient = int(require_key(unit, "orientation"))
    else:
        mover_orient = 0
    off_even, off_odd = precompute_footprint_offsets(mover_shape, mover_bs_i, mover_orient)
    off_even_arr = np.asarray(off_even, dtype=np.int64).reshape(-1, 2)
    off_odd_arr = np.asarray(off_odd, dtype=np.int64).reshape(-1, 2)

    col_is_even = (np.arange(board_cols, dtype=np.int64) & 1) == 0
    col_parity_mask = np.broadcast_to(
        col_is_even[:, None], (board_cols, board_rows)
    ).copy()

    # Dilatation / propagation plein-board : ce chemin (masque EZ `ez > 1`) n'a pas de bbox de
    # sortie connue a priori, d'où l'absence de `bbox=`. Les deux closures qui vivaient ici sont
    # devenues les fonctions module `hex_utils.dilate_by_kernel` / `spread_by_kernel`.
    def _dilate(src: "np.ndarray", kernel: "np.ndarray") -> "np.ndarray":
        return dilate_by_kernel(src, kernel, board_cols, board_rows)

    def _spread(src: "np.ndarray", kernel: "np.ndarray") -> "np.ndarray":
        return spread_by_kernel(src, kernel, board_cols, board_rows)

    nb_even = np.asarray(
        [(0, -1), (1, -1), (1, 0), (0, 1), (-1, 0), (-1, -1)], dtype=np.int64
    )
    nb_odd = np.asarray(
        [(0, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0)], dtype=np.int64
    )

    # Métrique d'engagement unifiée : empreinte hex uniquement (jamais euclidien).
    eng_bad = np.zeros((board_cols, board_rows), dtype=bool)
    enemy_list = enemy_items if enemy_items is not None else []

    hex_mixed_mask = np.zeros((board_cols, board_rows), dtype=bool)
    has_hex_mixed = False
    for _, ce in enemy_list:
        e_shape = require_key(ce, "BASE_SHAPE")
        e_bs = require_base_size(
            e_shape,
            require_key(ce, "BASE_SIZE"),
            f"units_cache enemy {ce.get('id', '?')}",
        )
        by_model = ce.get("occupied_hexes_by_model")
        model_positions = list(by_model.values()) if by_model else [
            (int(require_key(ce, "col")), int(require_key(ce, "row")))
        ]
        e_orient = int(require_key(ce, "orientation"))
        e_off_even, e_off_odd = precompute_footprint_offsets(e_shape, e_bs, e_orient)
        for e_col, e_row in model_positions:
            e_off = e_off_even if (e_col & 1) == 0 else e_off_odd
            for dc, dr in e_off:
                fc = e_col + int(dc)
                fr = e_row + int(dr)
                if 0 <= fc < board_cols and 0 <= fr < board_rows:
                    hex_mixed_mask[fc, fr] = True
        has_hex_mixed = True

    if has_hex_mixed:
        # Dilatation hex (cube-distance) de rayon ``ez`` par propagation itérative par parité,
        # puis dilatation par l'empreinte du mover → ``min_distance_between_sets ≤ ez``.
        dilated = hex_mixed_mask.copy()
        for _ in range(int(ez)):
            even_src = dilated & col_parity_mask
            odd_src = dilated & ~col_parity_mask
            nxt = dilated | _spread(even_src, nb_even) | _spread(odd_src, nb_odd)
            if np.array_equal(nxt, dilated):
                break
            dilated = nxt
        eng_bad_even_mix = _dilate(dilated, off_even_arr)
        eng_bad_odd_mix = _dilate(dilated, off_odd_arr)
        eng_bad |= np.where(col_parity_mask, eng_bad_even_mix, eng_bad_odd_mix)

    return eng_bad


def _ground_move_bbox_window(
    start_col: int,
    start_row: int,
    move_range: int,
    off_even_arr: "np.ndarray",
    off_odd_arr: "np.ndarray",
    board_cols: int,
    board_rows: int,
) -> Tuple[int, int, int, int]:
    """Fenêtre bbox englobant ``reach`` ∪ empreintes du chemin GROUND (L_bbox, §0.22).

    Le BFS ground fait des pas de voisinage dans ``{-1,0,1}²`` → ``reach ⊆ start ± move_range``
    en col ET row ; les empreintes s'étendent de ``±max|offset|``. Retourne
    ``(c_lo, c_hi, r_lo, r_hi)`` (bornes de slice demi-ouvertes) clampé au plateau. Hors de cette
    fenêtre, aucune valeur de dilatation n'est jamais **lue** (cf. docstring de
    ``_build_multi_hex_vectorized``), donc y borner les slices est exact.
    """
    import numpy as np

    max_dc = 0
    max_dr = 0
    if off_even_arr.size:
        max_dc = int(np.abs(off_even_arr[:, 0]).max())
        max_dr = int(np.abs(off_even_arr[:, 1]).max())
    if off_odd_arr.size:
        max_dc = max(max_dc, int(np.abs(off_odd_arr[:, 0]).max()))
        max_dr = max(max_dr, int(np.abs(off_odd_arr[:, 1]).max()))
    pad_c = int(move_range) + max_dc
    pad_r = int(move_range) + max_dr
    return (
        max(0, start_col - pad_c),
        min(board_cols, start_col + pad_c + 1),
        max(0, start_row - pad_r),
        min(board_rows, start_row + pad_r + 1),
    )


def _build_multi_hex_vectorized(
    *,
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    start_col: int,
    start_row: int,
    move_range: int,
    off_even: Tuple[Tuple[int, int], ...],
    off_odd: Tuple[Tuple[int, int], ...],
    board_cols: int,
    board_rows: int,
    walls_set: Set[Tuple[int, int]],
    enemy_transit_blocked: Set[Tuple[int, int]],
    friendly_transit_blocked: Set[Tuple[int, int]],
    occupied_set: Set[Tuple[int, int]],
    enemy_adjacent_hexes: Set[Tuple[int, int]],
    enemy_items: Optional[List[Tuple[Any, Any]]],
    ez: int,
    thru_ez: bool,
    fly: bool = False,
    out_costs: Optional[Dict[Tuple[int, int], float]] = None,
    _bbox_window: bool = True,
) -> Tuple[List[Tuple[int, int]], Set[Tuple[int, int]], int]:
    """BFS/disk multi-hex vectorisé NumPy (``ground`` et ``fly``). Gère toutes les formes de socles.

    Retourne ``(valid_destinations, footprint_zone, visited_count)``.

    ``_bbox_window`` (optionnel, L_bbox — accélération §0.22) : fenêtre toutes les dilatations
    slice-OR (``_dilate_by_kernel`` / ``_spread_by_kernel``) sur la bbox
    ``start ± (move_range + max|offset|)`` du **chemin ground** (``not fly``). C'est une
    optimisation de **surface pure** : le BFS ground fait des pas de voisinage dans ``{-1,0,1}²``,
    donc ``reach ⊆ start ± move_range`` en col ET row, et ``bad_dest`` / ``bad_traverse`` /
    ``eng_bad`` / footprint ne sont jamais **lus** hors de cette bbox. Fenêtrer les slices y produit
    un pool, une footprint zone et des ``out_costs`` **strictement identiques** au plein-board.
    ``fly`` (disque, étendue row jusqu'à ~1,5×move_range) est **exclu** : bbox laissée à ``None``.
    ``_bbox_window=False`` restaure le plein-board (garde-fou du test A/B fenêtré == plein-board).

    ``out_costs`` (optionnel, refonte spatiale §7 T2) : si fourni, rempli avec
    ``{(col, row): coût géodésique en SUBHEX (float)}`` pour chaque destination valide. Le coût est
    la distance de **chemin** (règle 03 : la distance d'un move est celle du chemin parcouru), et
    non la distance à vol d'oiseau : c'est lui qui détermine le type de move côté gym
    (coût ≤ M → normal, coût > M → advance). Paramètre **purement additif** : quand il vaut
    ``None``, cette fonction se comporte exactement comme avant (chemin PvP inchangé).

    Invariants de sémantique (équivalence stricte avec le BFS Python hex orig.) :

    - **Bounds + walls + traversée** : l'empreinte doit tenir dans le plateau et ne chevaucher
      aucun mur. Les figs ennemies (``thru_enemy``), amies (``thru_friendly``) et la bande d'EZ
      (``thru_ez``) ne bloquent la traversée que si le toggle config correspondant est ``False``.
    - **Engagement zone** (toujours exclue de la **destination**, ``valid_mask & ~eng_bad``) :
        * ``ez <= 1`` : ``enemy_adjacent_hexes`` déjà pré-dilaté par ``build_enemy_adjacent_hexes``.
          Une ancre viole l'engagement ssi une cellule de son empreinte est dans cet ensemble.
        * ``ez > 1`` (Board ×10) :
          - Paire **mover rond ↔ ennemi rond** : écart bord à bord euclidien (centres
            ``_hex_center``) ≥ ``engagement_minimum_clearance_norm(ez)``.
          - Sinon (mover non-rond ou ennemi non-rond) : clearance continue sur les CONTOURS,
            les centres de cellules ne servant qu'à borner la frange évaluée exactement (cf.
            ``_compute_mover_ez_forbidden_mask``).
    - **Destinations** : traversable ET empreinte ne chevauchant aucune cellule d'``occupied_set``.
    - **Start** : l'ancre de départ est toujours atteinte mais exclue des destinations.
    - **Footprint zone** : union des empreintes (empreinte de départ + empreinte de chaque
      destination), identique à l'union calculée côté BFS Python.
    """
    import numpy as np

    # Champ de coût géodésique en SUBHEX, renseigné par chacune des branches ci-dessous (aucune
    # n'a besoin d'un recalcul : elles produisent toutes déjà une distance, il suffit de la
    # convertir dans l'unité commune).
    _dist_arr: Optional["np.ndarray"] = None

    off_even_arr = np.asarray(off_even, dtype=np.int64).reshape(-1, 2)
    off_odd_arr = np.asarray(off_odd, dtype=np.int64).reshape(-1, 2)

    col_is_even = (np.arange(board_cols, dtype=np.int64) & 1) == 0
    col_parity_mask = np.broadcast_to(
        col_is_even[:, None], (board_cols, board_rows)
    ).copy()

    # L_bbox (§0.22) — fenêtre de la sortie utile pour le chemin ground. `None` ⇒ plein-board
    # (fly, ou A/B `_bbox_window=False`).
    _bbox: Optional[Tuple[int, int, int, int]] = None
    if _bbox_window and not fly:
        _bbox = _ground_move_bbox_window(
            start_col, start_row, move_range,
            off_even_arr, off_odd_arr, board_cols, board_rows,
        )

    # Dilatation / propagation FENÊTRÉES sur la bbox du move (L_bbox, §0.22). Les deux closures
    # qui portaient ici leur propre calcul de bornes sont devenues `hex_utils.dilate_by_kernel` /
    # `spread_by_kernel` ; il ne reste que le passage de la fenêtre, que le chemin `fly` laisse à
    # `None` (disque, étendue row ~1,5x move_range) et que l'A/B `_bbox_window=False` neutralise.
    def _dilate_by_kernel(
        src: "np.ndarray",
        kernel: "np.ndarray",
        bbox: Optional[Tuple[int, int, int, int]] = None,
    ) -> "np.ndarray":
        return dilate_by_kernel(src, kernel, board_cols, board_rows, bbox=bbox)

    def _spread_by_kernel(
        src: "np.ndarray",
        kernel: "np.ndarray",
        bbox: Optional[Tuple[int, int, int, int]] = None,
    ) -> "np.ndarray":
        return spread_by_kernel(src, kernel, board_cols, board_rows, bbox=bbox)

    def _mask_from_cells(cells: Set[Tuple[int, int]]) -> "np.ndarray":
        m = np.zeros((board_cols, board_rows), dtype=bool)
        if not cells:
            return m
        cs = np.fromiter((c for c, _ in cells), dtype=np.int64, count=len(cells))
        rs = np.fromiter((r for _, r in cells), dtype=np.int64, count=len(cells))
        in_b = (cs >= 0) & (cs < board_cols) & (rs >= 0) & (rs < board_rows)
        m[cs[in_b], rs[in_b]] = True
        return m

    # Murs : PAS ici. Ce sont des ancres interdites au SOCLE (`wall_blocked_anchors`), déjà
    # socle-conscientes ; les dilater par l'empreinte mesurerait le mur comme un POINT, soit
    # strictement plus laxiste que le commit (`is_placement_valid_with_clearance`) — le masque
    # offrirait alors des destinations que l'exécution refuse. Retranchées après la dilatation.
    obstacles_dest_any = occupied_set
    obstacles_dest_mask = _mask_from_cells(obstacles_dest_any)
    _wall_anchor_mask = _mask_from_cells(set(wall_blocked_anchors(game_state, unit)))
    obstacles_traverse_mask: np.ndarray = obstacles_dest_mask
    if not fly:
        # Murs toujours bloquants ; les figurines bloquantes viennent de
        # `build_move_traversal_blocked` (toggles, Desperate Escape 09.07, exemption M/V 17.01).
        obstacles_traverse = set(walls_set) | enemy_transit_blocked | friendly_transit_blocked
        obstacles_traverse_mask = _mask_from_cells(obstacles_traverse)

    def _bounds_bad_parity(offsets_arr: "np.ndarray") -> "np.ndarray":
        min_dc = int(offsets_arr[:, 0].min())
        max_dc = int(offsets_arr[:, 0].max())
        min_dr = int(offsets_arr[:, 1].min())
        max_dr = int(offsets_arr[:, 1].max())
        bad = np.ones((board_cols, board_rows), dtype=bool)
        c_lo = max(0, -min_dc)
        c_hi = min(board_cols, board_cols - max_dc)
        r_lo = max(0, -min_dr)
        r_hi = min(board_rows, board_rows - max_dr)
        if c_lo < c_hi and r_lo < r_hi:
            bad[c_lo:c_hi, r_lo:r_hi] = False
        return bad

    def _placement_bad(obstacles_mask: "np.ndarray") -> "np.ndarray":
        hit_even = _dilate_by_kernel(obstacles_mask, off_even_arr, _bbox)
        hit_odd = _dilate_by_kernel(obstacles_mask, off_odd_arr, _bbox)
        hit = np.where(col_parity_mask, hit_even, hit_odd)
        bounds_bad_even = _bounds_bad_parity(off_even_arr)
        bounds_bad_odd = _bounds_bad_parity(off_odd_arr)
        bounds_bad = np.where(col_parity_mask, bounds_bad_even, bounds_bad_odd)
        return hit | bounds_bad

    bad_dest = _placement_bad(obstacles_dest_mask) | _wall_anchor_mask
    bad_traverse: np.ndarray = bad_dest
    if not fly:
        # Traversée : les murs restent des CELLULES dilatées par l'empreinte (le socle ne
        # traverse pas un mur), c'est la géométrie du transit et elle ne change pas.
        bad_traverse = _placement_bad(obstacles_traverse_mask)

    if ez > 1:
        # Géométrie d'engagement : source unique partagée avec le path PvP (garantit IA == PvP).
        eng_bad = _compute_mover_ez_forbidden_mask(
            game_state, unit, enemy_items, ez, board_cols, board_rows
        )
    elif ez == 1 and enemy_adjacent_hexes:
        enemy_adj_mask = _mask_from_cells(enemy_adjacent_hexes)
        eng_bad_even = _dilate_by_kernel(enemy_adj_mask, off_even_arr, _bbox)
        eng_bad_odd = _dilate_by_kernel(enemy_adj_mask, off_odd_arr, _bbox)
        eng_bad = np.where(col_parity_mask, eng_bad_even, eng_bad_odd)
    else:
        eng_bad = np.zeros((board_cols, board_rows), dtype=bool)

    if fly:
        # FLY: reachable = disque (aucun obstacle de traversée : FLY ignore murs/figs, Règles 21.03).
        if _move_distance_metric(game_state) == "euclidean":
            # Disque euclidien CENTRE-À-CENTRE (règle 03.01), budget × 1.5 — IDENTIQUE au model pool
            # par-fig (geodesic_field sans obstacle) → preview escouade == commit. Repère _hex_center
            # (hex_width = 1.5, hex_height = √3), sans arrondi.
            _hw = ENGAGEMENT_NORM_HEX_WIDTH
            _hh = 3.0 ** 0.5
            _cols_i = np.arange(board_cols, dtype=np.int64)[:, None]
            _cx = _cols_i.astype(np.float64) * _hw + _hw / 2.0
            _cy = (
                np.arange(board_rows, dtype=np.float64)[None, :] * _hh
                + (_cols_i & 1).astype(np.float64) * (_hh / 2.0)
                + _hh / 2.0
            )
            _sx = start_col * _hw + _hw / 2.0
            _sy = start_row * _hh + (start_col & 1) * (_hh / 2.0) + _hh / 2.0
            _dist = np.hypot(_cx - _sx, _cy - _sy)
            reach = _dist <= (move_range * _hw + _SEG_TOL)
            if out_costs is not None:
                # `_dist` est en unités `_hex_center` ; le budget y vaut move_range × 1.5.
                # Ramené en subhex (unité commune de `out_costs`) par la même conversion.
                # Sous garde : sans `out_costs` (chemin PvP) cette division allouerait un tableau
                # board_cols×board_rows pour rien.
                _dist_arr = _dist / ENGAGEMENT_NORM_HEX_WIDTH
        else:
            # hex (gym / move_gym) : disque cube-distance (comportement historique).
            cols_arr = np.arange(board_cols, dtype=np.int64)[:, None]
            rows_arr = np.arange(board_rows, dtype=np.int64)[None, :]
            x_c = cols_arr
            z_c = rows_arr - (cols_arr - (cols_arr & 1)) // 2
            y_c = -x_c - z_c
            sx_c = np.int64(start_col)
            sz_c = np.int64(start_row) - (np.int64(start_col) - (np.int64(start_col) & 1)) // 2
            sy_c = -sx_c - sz_c
            cube_d = np.maximum(np.abs(x_c - sx_c), np.maximum(np.abs(y_c - sy_c), np.abs(z_c - sz_c)))
            reach = cube_d <= np.int64(move_range)
            if out_costs is not None:
                # FLY ignore murs/figurines en traversée (21.03) : la distance de chemin EST la
                # cube-distance, déjà calculée ici. Sous garde : `astype` copie tout le plateau.
                _dist_arr = cube_d.astype(np.float64)
        valid_mask = reach & ~bad_dest & ~eng_bad
    else:
        # EZ traversable selon toggle ; toujours exclue de la destination (unengaged 09.05).
        traverse_bad = bad_traverse if thru_ez else (bad_traverse | eng_bad)

        # Deque BFS : visite uniquement les ancres accessibles — O(reachable) au lieu de
        # O(move_range × board_cols × board_rows) pour le wavefront NumPy.
        # Sémantique identique : même ensemble d'ancres atteignables en ≤ move_range pas.
        # traverse_bad (précomputé par _placement_bad) converti en bytearray F-order pour
        # lookup O(1) cohérent avec l'index nc + nr * board_cols du BFS single-hex.
        _tb_flat = bytearray(traverse_bad.ravel(order='F').astype(np.uint8))

        reach = np.zeros((board_cols, board_rows), dtype=bool)
        reach[start_col, start_row] = True

        _vis_bfs = bytearray(board_cols * board_rows)
        _vis_bfs[start_col + start_row * board_cols] = 1

        # Coût géodésique (§7 T2) : le BFS le calcule déjà (`cd`) mais le jetait. Aretes de poids
        # 1 + file FIFO -> la 1re visite d'une case EST sa distance de chemin minimale.
        _dist_arr = np.full((board_cols, board_rows), -1.0, dtype=np.float64) if out_costs is not None else None
        if _dist_arr is not None:
            _dist_arr[start_col, start_row] = 0.0

        _nb_even_t = ((0, -1), (1, -1), (1, 0), (0, 1), (-1, 0), (-1, -1))
        _nb_odd_t  = ((0, -1), (1, 0),  (1, 1), (0, 1), (-1, 1), (-1, 0))

        _bfs_queue = deque([(start_col, start_row, 0)])
        while _bfs_queue:
            cc, cr, cd = _bfs_queue.popleft()
            if cd >= move_range:
                continue
            nd = cd + 1
            nb_t = _nb_even_t if (cc & 1) == 0 else _nb_odd_t
            for dc, dr in nb_t:
                nc = cc + dc
                nr = cr + dr
                if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
                    continue
                _vidx = nc + nr * board_cols
                if _vis_bfs[_vidx]:
                    continue
                if _tb_flat[_vidx]:
                    continue
                _vis_bfs[_vidx] = 1
                reach[nc, nr] = True
                if _dist_arr is not None:
                    _dist_arr[nc, nr] = nd
                _bfs_queue.append((nc, nr, nd))

        valid_mask = reach & ~bad_dest & ~eng_bad
    valid_mask[start_col, start_row] = False

    valid_coords_cols, valid_coords_rows = np.where(valid_mask)
    valid_destinations: List[Tuple[int, int]] = [
        (int(c), int(r)) for c, r in zip(valid_coords_cols, valid_coords_rows)
    ]

    if out_costs is not None:
        assert _dist_arr is not None  # construit sous la meme garde `out_costs is not None`
        _costs_flat = _dist_arr[valid_coords_cols, valid_coords_rows]
        for _c, _r, _d in zip(valid_coords_cols, valid_coords_rows, _costs_flat):
            out_costs[(int(_c), int(_r))] = float(_d)

    fpz_even_mask = valid_mask & col_parity_mask
    fpz_odd_mask = valid_mask & ~col_parity_mask
    footprint_zone_mask = _spread_by_kernel(fpz_even_mask, off_even_arr, _bbox) | _spread_by_kernel(
        fpz_odd_mask, off_odd_arr, _bbox
    )
    start_offsets = off_even_arr if (start_col & 1) == 0 else off_odd_arr
    for dc, dr in start_offsets:
        fc = start_col + int(dc)
        fr = start_row + int(dr)
        if 0 <= fc < board_cols and 0 <= fr < board_rows:
            footprint_zone_mask[fc, fr] = True

    fpz_cols, fpz_rows = np.where(footprint_zone_mask)
    footprint_zone: Set[Tuple[int, int]] = {
        (int(c), int(r)) for c, r in zip(fpz_cols, fpz_rows)
    }

    visited_count = int(reach.sum())
    return valid_destinations, footprint_zone, visited_count


def _advance_roll_for(squad_id: str, game_state: Dict[str, Any]) -> Optional[int]:
    """Jet d'Advance de cette escouade pour le tour, sinon None.

    Source unique du « mode Advance » (Règles 09.06) : une escouade qui a déclaré Advance
    est dans ``units_advanced`` (persistant jusqu'à la phase de commandement suivante) et son
    jet est mémorisé dans ``advance_rolls`` (squad_id → jet). Tant qu'elle y est, les pools
    de destinations utilisent un budget M+jet, le mode survit aux cancel/ré-activations, et
    elle ne peut ni tirer ni charger. Le jet est figé (pas de re-roll).
    """
    if str(squad_id) not in game_state.get("units_advanced", set()):
        return None
    roll = game_state["advance_rolls"].get(str(squad_id))
    return int(roll) if roll is not None else None


def _get_move_traversal_rules(game_state: Dict[str, Any]) -> Tuple[bool, bool, bool]:
    """Lit les 3 toggles de traversée depuis ``config["move"]`` (Règles 03.01).

    Retourne ``(thru_ez, thru_enemy, thru_friendly)`` :
      - ``can_move_through_enemy_engagement_zone`` : traverser la bande d'EZ ennemie.
      - ``can_move_through_enemy_model`` : traverser une figurine ennemie.
      - ``can_move_through_friendly_model`` : traverser une figurine amie.

    Ces toggles ne concernent QUE la traversée (pathfinding). Finir son move sur une case
    occupée ou dans l'EZ ennemie reste toujours interdit (occupation 03.01 / unengaged 09.05),
    indépendamment de ces valeurs. Pas de défaut : clé manquante = erreur explicite.
    """
    config = require_key(game_state, "config")
    move_rules = require_key(config, "move")
    return (
        bool(require_key(move_rules, "can_move_through_enemy_engagement_zone")),
        bool(require_key(move_rules, "can_move_through_enemy_model")),
        bool(require_key(move_rules, "can_move_through_friendly_model")),
    )


def _mono_hex_bfs_shortcut(game_state: Dict[str, Any], base_size: Any, metric: str) -> bool:
    """Le pool de move peut-il prendre le raccourci BFS hexagonal (sans empreinte) ?

    SOURCE UNIQUE de ce choix de ROUTE, pour les DEUX branches de
    ``movement_build_valid_destinations_pool`` (sol et FLY 21.03). Elles l'ont chacune écrit à la
    main, et la branche FLY a été oubliée lors du passage à `_geometry_is_hex` : le raccourci y
    décidait sur le socle SEUL, si bien qu'un volant mono-hex mesurait son disque en cube-distance
    au milieu d'une partie euclidienne. Les 200 lignes qui séparent les deux gardes rendent l'oubli
    invisible — d'où un seul corps plutôt qu'une convention à tenir.

    DEUX conditions, et la métrique d'abord parce que c'est elle qui gouverne :
    - ``metric == "hex"`` : le raccourci compte 1 par pas d'hexagone. En euclidean, la règle 03 se
      mesure en longueur réelle, donc tout socle passe par le chemin continu (empreinte), même
      quand cette empreinte tient dans une case.
    - socle mono-hex : géométrie hex (x1, cf. `_geometry_is_hex`) ou socle de taille 1. Ce n'est
      PAS `hex_utils.socle_is_single_hex`, plus conservateur (il refuse `square`/1) et aveugle à la
      résolution : les deux prédicats ne répondent pas à la même question, celui-là dit « son
      empreinte est-elle son ancre ? ».
    """
    return metric == "hex" and (_geometry_is_hex(game_state) or base_size == 1)


def _move_distance_metric(game_state: Dict[str, Any]) -> str:
    """Métrique de distance du MOVE (``hex``|``euclidean``) — sélecteur unique.

    Contexte : PvP/replay lisent ``distance_metric["move"]`` ; le training gym lit
    ``distance_metric["move_gym"]`` (le paramètre unique qui bascule le training, défaut
    ``hex`` pour la perf). Aucun défaut caché : section/clé/valeur invalide → erreur explicite.

    En gym, une PHASE de training peut imposer sa métrique (``gym_distance_metric``, cf.
    ``combat_utils.gym_distance_metric_override``) : c'est ce qui permet de courir le gros d'un
    curriculum en ``hex`` puis de recalibrer la fin en ``euclidean`` par ``--append``. La clé de
    config reste lue et validée avant l'override — une valeur invalide doit lever même quand la
    phase impose autre chose, sinon une config cassée resterait invisible tant qu'un réglage la
    recouvre. Hors gym (PvP/replay), l'override est ignoré : il ne décrit qu'un entraînement.

    Le corps VIT dans ``combat_utils.resolve_gym_split_metric``, partagé avec
    ``_charge_distance_metric`` : les deux sélecteurs étaient identiques à la clé près et tenus en
    phase à la main (11.04 — la charge EST un move, leurs métriques ne peuvent pas diverger).
    """
    from engine.combat_utils import resolve_gym_split_metric

    return resolve_gym_split_metric("move", game_state)


def _filter_ground_anchors_vectorized(
    field_cells: List[Tuple[int, int]],
    off_even: Tuple[Tuple[int, int], ...],
    off_odd: Tuple[Tuple[int, int], ...],
    board_cols: int,
    board_rows: int,
    start_pos: Tuple[int, int],
    start_col: int,
    start_row: int,
    anchor_blocked: Set[Tuple[int, int]],
    dest_blocked_fp: Set[Tuple[int, int]],
    walls: Set[Tuple[int, int]],
) -> Tuple[List[Tuple[int, int]], Set[Tuple[int, int]]]:
    """Version NumPy du filtre de destination + union d'empreinte de ``_euclidean_ground_anchor_multihex``.

    Équivalence STRICTE avec la boucle Python d'origine (prouvée par test randomisé) :
    une ancre du champ est une destination valide ssi elle n'est ni ``start_pos`` ni dans
    ``anchor_blocked`` (EZ ennemie ET ancres où le socle chevauche un mur — deux ensembles déjà
    socle-conscients, qui ne doivent donc PAS être re-dilatés par l'empreinte), que toute son
    empreinte (offsets selon parité de colonne) tient dans le
    plateau, et qu'aucune cellule d'empreinte n'est dans ``dest_blocked_fp``. ``footprint_zone`` =
    union des empreintes des destinations valides + empreinte de départ (ajoutée telle quelle, même
    hors plateau, comme l'original), moins ``walls``. L'ordre de ``valid_destinations`` suit l'ordre
    d'itération du champ (préservé).
    """
    import numpy as np

    off_even_arr = np.asarray(off_even, dtype=np.int64).reshape(-1, 2)
    off_odd_arr = np.asarray(off_odd, dtype=np.int64).reshape(-1, 2)

    if field_cells:
        anchors = np.asarray(field_cells, dtype=np.int64).reshape(-1, 2)
    else:
        anchors = np.empty((0, 2), dtype=np.int64)
    n = anchors.shape[0]

    blk = np.zeros((board_cols, board_rows), dtype=bool)
    if dest_blocked_fp:
        bc = np.fromiter((c for c, _ in dest_blocked_fp), dtype=np.int64, count=len(dest_blocked_fp))
        br = np.fromiter((r for _, r in dest_blocked_fp), dtype=np.int64, count=len(dest_blocked_fp))
        ib = (bc >= 0) & (bc < board_cols) & (br >= 0) & (br < board_rows)
        blk[bc[ib], br[ib]] = True

    valid = np.zeros(n, dtype=bool)
    even = ((anchors[:, 0] & 1) == 0) if n else np.zeros(0, dtype=bool)
    for is_even, offarr in ((True, off_even_arr), (False, off_odd_arr)):
        idx = np.nonzero(even if is_even else ~even)[0]
        if idx.size == 0:
            continue
        a = anchors[idx]
        fc = a[:, 0:1] + offarr[:, 0][None, :]
        fr = a[:, 1:2] + offarr[:, 1][None, :]
        inb = (fc >= 0) & (fc < board_cols) & (fr >= 0) & (fr < board_rows)
        inb_all = inb.all(axis=1)
        fcc = np.clip(fc, 0, board_cols - 1)
        frc = np.clip(fr, 0, board_rows - 1)
        blocked_any = (blk[fcc, frc] & inb).any(axis=1)
        valid[idx[inb_all & ~blocked_any]] = True

    # Exclusion start_pos + anchor_blocked (AVANT ajout d'empreinte, comme le ``continue`` d'origine).
    # Appartenance ensembliste exacte (pas d'encodage : injectivité non garantie si une ancre a un
    # centre hors plateau — cas permis par la référence, l'empreinte pouvant rester dans le plateau).
    excl = set(anchor_blocked)
    excl.add(start_pos)
    if n:
        excl_mask = np.fromiter(
            ((int(c), int(r)) in excl for c, r in anchors), dtype=bool, count=n
        )
        valid &= ~excl_mask

    valid_destinations = [(int(c), int(r)) for c, r in anchors[valid]]

    # footprint_zone : empreintes des destinations valides (toutes dans le plateau car inb_all),
    # union via np.unique sur encodage c*board_rows+r.
    footprint_zone: Set[Tuple[int, int]] = set()
    va = anchors[valid]
    if va.shape[0]:
        veven = (va[:, 0] & 1) == 0
        enc_parts: List["np.ndarray"] = []
        for is_even, offarr in ((True, off_even_arr), (False, off_odd_arr)):
            vv = va[veven if is_even else ~veven]
            if vv.shape[0] == 0:
                continue
            fc = (vv[:, 0:1] + offarr[:, 0][None, :]).reshape(-1)
            fr = (vv[:, 1:2] + offarr[:, 1][None, :]).reshape(-1)
            enc_parts.append(fc * np.int64(board_rows) + fr)
        if enc_parts:
            for e in np.unique(np.concatenate(enc_parts)):
                footprint_zone.add((int(e // board_rows), int(e % board_rows)))

    # Empreinte de départ ajoutée telle quelle (même hors plateau, comme l'original), puis retrait murs.
    s_offs = off_even if (start_col & 1) == 0 else off_odd
    for _dc, _dr in s_offs:
        footprint_zone.add((start_col + _dc, start_row + _dr))
    footprint_zone -= walls
    return valid_destinations, footprint_zone


def _euclidean_ground_anchor_multihex(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    start_col: int,
    start_row: int,
    start_pos: Tuple[int, int],
    move_range: int,
    base_shape: str,
    base_size: Any,
    off_even: Tuple[Tuple[int, int], ...],
    off_odd: Tuple[Tuple[int, int], ...],
    board_cols: int,
    board_rows: int,
    walls: Set[Tuple[int, int]],
    occupied: Set[Tuple[int, int]],
    enemy_transit_blocked: Set[Tuple[int, int]],
    friendly_transit_blocked: Set[Tuple[int, int]],
    enemy_adjacent_hexes: Set[Tuple[int, int]],
    enemy_items: Optional[List[Tuple[Any, Any]]],
    ez: int,
    thru_ez: bool,
) -> Tuple[List[Tuple[int, int]], Set[Tuple[int, int]], int, Dict[Tuple[int, int], float], Set[Tuple[int, int]]]:
    """Pool d'ancre GROUND euclidien multi-hex (preview escouade), miroir du model pool par-fig.

    Champ géodésique du centre de l'ancre (round: clearance continue ; non-round: empreinte
    discrète), puis filtre de destination sur l'empreinte COMPLÈTE (murs/occupé/EZ), identique
    au model pool → preview == commit. L'EZ suit les deux régimes existants :
    ``ez > 1`` testée sur l'ancre (le masque intègre déjà l'empreinte du mover) ;
    ``ez <= 1`` (legacy) dilatée par l'empreinte via ``enemy_adjacent_hexes``.
    """
    import numpy as np
    _wall_anchors_pool = wall_blocked_anchors(game_state, unit)
    if ez > 1:
        _ez_mask = _compute_mover_ez_forbidden_mask(
            game_state, unit, enemy_items, ez, board_cols, board_rows
        )
        _ec, _er = np.where(_ez_mask)
        ez_forbidden: Set[Tuple[int, int]] = {(int(c), int(r)) for c, r in zip(_ec, _er)}
        # Murs retirés de `dest_blocked_fp` : ancres interdites au SOCLE, testées sur l'ancre
        # comme l'EZ. Les laisser ici les mesurerait comme des POINTS dilatés par l'empreinte,
        # soit plus laxiste que le commit — masque ⊄ exécutable.
        dest_blocked_fp = occupied                   # EZ + murs testés sur l'ancre (ci-dessous)
        ez_anchor_check = ez_forbidden | _wall_anchors_pool
    else:
        ez_forbidden = enemy_adjacent_hexes
        dest_blocked_fp = occupied | enemy_adjacent_hexes  # EZ dilatée par l'empreinte
        ez_anchor_check = set(_wall_anchors_pool)

    obstacles_tr: Set[Tuple[int, int]] = set(walls)
    obstacles_tr |= enemy_transit_blocked
    obstacles_tr |= friendly_transit_blocked
    if not thru_ez:
        obstacles_tr |= ez_forbidden
    obstacles_tr.discard(start_pos)

    field = _euclidean_move_field(
        start_pos, base_shape, base_size, off_even, off_odd,
        obstacles_tr, board_cols, board_rows, move_range * ENGAGEMENT_NORM_HEX_WIDTH,
    )

    # Filtre destination + union d'empreinte vectorisé NumPy (équivalence stricte avec l'ancienne
    # boucle Python, prouvée par ``_filter_ground_anchors_vectorized`` : test randomisé 5000 cas).
    valid_destinations, footprint_zone = _filter_ground_anchors_vectorized(
        list(field), off_even, off_odd, board_cols, board_rows,
        start_pos, start_col, start_row, ez_anchor_check, dest_blocked_fp, walls,
    )
    # ``field`` (dict cellule→distance-norme) et ``obstacles_tr`` renvoyés pour réutilisation par le
    # champ multi-niveaux : ce sont exactement le champ sol et les obstacles de traversée du move
    # principal (règle 03.01), ce qui évite de recalculer tout le champ sol dans reachable_multilevel_field.
    return valid_destinations, footprint_zone, len(field), field, obstacles_tr


def _multilevel_floor_destinations(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    start_pos: Tuple[int, int],
    move_range: float,
    ground_obstacles: Set[Tuple[int, int]],
    base_shape: str,
    base_size: Any,
    off_even: Tuple[Tuple[int, int], ...],
    off_odd: Tuple[Tuple[int, int], ...],
    fly_active: bool,
    precomputed_ground_field: Optional[Dict[Tuple[int, int], float]] = None,
    precomputed_ground_obstacles: Optional[Set[Tuple[int, int]]] = None,
) -> Dict[int, List[Tuple[int, int]]]:
    """Destinations de move sur les ÉTAGES (niveaux >= 1), via ``reachable_multilevel_field``.

    Adaptateur du chantier 3c (step 1) : connecte le champ multi-niveaux (validé) à la sémantique
    réelle du move — budget (``move_range`` subhex → norme), floors du terrain, obstacles par niveau
    (2b), flags mot-clé (§2.2), et validation de fin de move sur étage (13.06). Le niveau 0 (sol) N'EST
    PAS produit ici : il reste la liste 2D existante (source unique inchangée) — on n'utilise que les
    cellules de niveau >= 1 du champ.

    Retour : ``{level>=1: [(col,row), ...]}`` (niveaux sans destination omis). ``{}`` si aucun étage
    déclaré (garantie no-op / non-régression) ou si l'unité ne peut pas finir en hauteur (§13.06).

    Limitations documentées (V1) : hauteur GLOBALE par niveau (lève si incohérente entre ruines).
    L'EZ ennemie à la destination est filtrée EN AVAL par l'appelant, avec le même contrat 2D que le
    sol (mirror move phase) ; le gate vertical 5" (03.04) reste un manque transverse sol+étages, non
    modélisé ici (chantier engagement 3D dédié).
    """
    from engine.terrain_utils import (
        floor_hexes_at_level, floor_levels_present, floor_polys_at_level, footprint_within_floor,
    )
    from engine.game_state import unit_can_occupy_upper_floor

    terrain_areas = game_state.get("terrain_areas", [])  # get allowed (peut être vide)
    present = floor_levels_present(terrain_areas)
    if not present:
        return {}  # aucun étage → no-op (non-régression du mouvement 2D)
    if not unit_can_occupy_upper_floor(require_key(unit, "UNIT_KEYWORDS")):
        return {}  # unité incapable de finir en hauteur (§13.06) → reste au sol

    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    walls = game_state.get("wall_hexes", set())  # get allowed
    inches_to_subhex = int(require_key(game_state, "inches_to_subhex"))
    unit_id_str = str(require_key(unit, "id"))

    floor_hexes_by_level = {lv: floor_hexes_at_level(terrain_areas, lv) for lv in present}
    # Base ronde : polygones d'étage précalculés une fois par niveau (confinement euclidien du bord).
    base_shape_round = base_shape == "round"
    floor_polys_by_level = (
        {lv: floor_polys_at_level(terrain_areas, lv) for lv in present} if base_shape_round else {}
    )
    height_by_level: Dict[int, float] = {0: 0.0}
    for a in terrain_areas:
        for fl in a.get("floors", []):  # get allowed (aire sans étage)
            lv = int(fl["level"])
            hn = float(fl["height_inches"]) * inches_to_subhex * ENGAGEMENT_NORM_HEX_WIDTH
            if lv in height_by_level and abs(height_by_level[lv] - hn) > 1e-6:
                raise ValueError(
                    f"_multilevel_floor_destinations: niveau {lv} avec hauteurs incohérentes entre "
                    f"ruines ({height_by_level[lv]:.3f} vs {hn:.3f}) — hauteur globale par niveau non supportée"
                )
            height_by_level[lv] = hn

    # PRÉ-CHECK de portée (perf) : borne basse pour finir sur un étage L = distance directe
    # (murs ignorés) start→cellule + montée height[L]. Si AUCUN étage n'a une cellule dans le
    # budget, aucune destination d'étage possible → retour immédiat SANS lancer de champ (évite le
    # coût du pathfinding pour la majorité des unités, loin de toute ruine).
    from engine.hex_utils import _hex_center as _hc
    _budget_norm = move_range * ENGAGEMENT_NORM_HEX_WIDTH
    _sx, _sy = _hc(start_pos[0], start_pos[1])
    _reachable_any = False
    for _lv, _fh in floor_hexes_by_level.items():
        _vc = height_by_level[_lv]
        for _c, _r in _fh:
            _hx, _hy = _hc(_c, _r)
            if math.hypot(_hx - _sx, _hy - _sy) + _vc <= _budget_norm + 1e-6:
                _reachable_any = True
                break
        if _reachable_any:
            break
    if not _reachable_any:
        return {}

    from engine.hex_utils import get_neighbors as _neighbors
    walls_set = set(walls)
    # Niveau 0 : si le champ sol du move principal est fourni (chemin euclidien multi-hex), on réutilise
    # SES obstacles de traversée (règle 03.01 : murs + ennemis, ami/EZ traversables selon config) au lieu
    # de ``ground_obstacles`` (qui durcit en bloquant les alliés). Garantit la cohérence avec le champ
    # pré-calculé injecté dans ``reachable_multilevel_field`` (mêmes obstacles → même champ sol).
    _reuse_ground = precomputed_ground_field is not None and precomputed_ground_obstacles is not None
    _level0_obstacles = (
        precomputed_ground_obstacles
        if _reuse_ground and precomputed_ground_obstacles is not None
        else set(ground_obstacles)
    )
    obstacles_by_level: Dict[int, Set[Tuple[int, int]]] = {0: _level0_obstacles}
    occupied_by_level: Dict[int, Set[Tuple[int, int]]] = {}
    for lv, fh in floor_hexes_by_level.items():
        figs_lv = build_occupied_positions_set(game_state, exclude_unit_id=unit_id_str, level=lv)
        occupied_by_level[lv] = figs_lv
        # Anneau : voisins HORS-étage des cellules d'étage → confine le champ à l'empreinte sans
        # matérialiser tout le plateau. PERF : O(périmètre) au lieu de O(board_cols×board_rows) — sur
        # un board 220×300 le complément faisait indexer 66 000 obstacles par relance de geodesic_field.
        ring = {nb for cell in fh for nb in _neighbors(cell[0], cell[1]) if nb not in fh}
        obstacles_by_level[lv] = ring | walls_set | figs_lv

    field = reachable_multilevel_field(
        start_pos, 0, base_shape, base_size, off_even, off_odd,
        board_cols, board_rows, obstacles_by_level, floor_hexes_by_level, height_by_level,
        move_range * ENGAGEMENT_NORM_HEX_WIDTH, allow_vertical=True, ignore_vertical_cost=fly_active,
        precomputed_start_field=(precomputed_ground_field if _reuse_ground else None),
    )

    # Mots-clés (13.06) déjà vérifiés en tête (unit_can_occupy_upper_floor) et floors non vides
    # (``present``) → la seule condition variable par cellule est l'empreinte-sur-plancher. On appelle
    # directement ``footprint_within_floor`` avec ``floor_hexes_by_level[lv]`` (déjà calculé) au lieu de
    # ``validate_floor_placement`` (qui reconstruit ``floor_hexes_at_level`` + re-teste le mot-clé À CHAQUE
    # cellule). Résultat identique ; l'occupation du niveau reste testée séparément ci-dessous.
    _orientation = int(require_key(unit, "orientation")) if "orientation" in unit else 0
    result: Dict[int, List[Tuple[int, int]]] = {lv: [] for lv in present}
    for (c, r, lv), _d in field.items():
        if lv == 0:
            continue  # le sol reste la liste 2D existante (source unique)
        if (c, r) in walls or (c, r) in occupied_by_level.get(lv, set()):
            continue  # destination jamais sur mur ni sur case occupée du niveau (03.01)
        if footprint_within_floor(
            c, r, base_shape, base_size, _orientation, floor_hexes_by_level[lv],
            floor_polys_by_level.get(lv) if base_shape_round else None,
        ):
            result[lv].append((c, r))
    return {lv: cells for lv, cells in result.items() if cells}


@profile_move_pool_build
def movement_build_valid_destinations_pool(
    game_state: Dict[str, Any],
    unit_id: str,
    read_only: bool = False,
    *,
    move_budget_override: Optional[int] = None,
    out_costs: Optional[Dict[Tuple[int, int], float]] = None,
    destination_level: Optional[int] = None,
) -> List[Tuple[int, int]]:
    """
    Build valid movement destinations using BFS pathfinding.

    ``read_only=True`` : calcule et RENVOIE la liste des destinations sans écrire le moindre
    état preview dans ``game_state`` (pool / footprint_zone / span / border / mask_loops). Utilisé
    par ``get_eligible_units`` comme oracle fall-back (source unique = ce builder, zéro divergence).

    Paramètres de la refonte spatiale (§7 T2/T3, §10.5) — **purement additifs** : quand les deux
    valent ``None``, le comportement est strictement celui d'avant. Le PvP ne les passe jamais.

    ``destination_level`` : niveau auquel la légalité des cellules (occupation amie/ennemie) est
    évaluée. ``None`` = niveau de l'unité (PvP/preview : elle reste à son étage). Le squad move
    rigide du gym passe ``0`` : ses destinations sont TOUJOURS au sol (ce chemin ``read_only``
    retourne avant le bloc multi-niveaux), et le coût vertical est facturé par le malus de descente
    ci-dessous. Sans ce paramètre, une escouade partie d'un étage voyait son pool filtré par
    l'occupation de SON étage alors que la validation d'exécution la teste au sol — deux grandeurs
    différentes des deux côtés de l'invariant « masque ⊆ exécutable » (§0.34).

    ``move_budget_override`` : force le budget (subhex) au lieu de le dériver de
    ``_advance_roll_for``. Nécessaire au gym : le masque a besoin du pool au budget **Advance**
    alors que l'escouade n'a PAS encore déclaré Advance (elle n'est donc pas dans
    ``units_advanced``, et le builder retomberait sur le budget normal). Un seul BFS au budget
    Advance suffit, puisque le pool Normal y est inclus (§7 T2).

    ``out_costs`` : rempli avec ``{(col, row): coût géodésique en subhex}``. C'est ce coût
    (distance de **chemin**, règle 03 — pas la distance à vol d'oiseau) qui détermine le type de
    move côté gym : ``coût <= M`` → normal, ``coût > M`` → advance (§6.2).

    Uses BFS to find REACHABLE hexes, not just hexes within distance.
    This prevents movement through walls (tour_de_jeu.md compliance).

    Pre-computes enemy adjacent hexes and occupied positions once at BFS start for O(1) lookups.

    Ground (non-Fly): la traversée suit les toggles ``config["move"]`` (``_get_move_traversal_rules``) :
    figs ennemies (``can_move_through_enemy_model``), amies (``can_move_through_friendly_model``)
    et bande d'EZ (``can_move_through_enemy_engagement_zone``) ne bloquent le pas du BFS que si
    le toggle est ``False``. La destination, elle, ne peut JAMAIS finir sur une case occupée
    (03.01) ni dans l'EZ ennemie (unengaged, 09.05), quels que soient les toggles.

    Fly: exploration ignores walls and occupation along the path; walls, occupation and engagement
    are enforced on the destination footprint only (see fly branch below).
    """
    from engine.perf_timing import append_perf_timing_line, perf_field, perf_timing_enabled

    _pt = perf_timing_enabled(game_state)
    import time as _perf_clock

    _m0 = _perf_clock.perf_counter() if _pt else None

    unit = require_unit_by_id(game_state, unit_id)
    if move_budget_override is not None:
        # Chemin gym uniquement (§7 T2) : budget imposé par l'appelant.
        # `0` est ACCEPTÉ : `get_squad_move_budget` renvoie `max(0, MOVE - malus)` (Take to the
        # skies 21.03), donc un budget nul est un état de jeu légitime, et le BFS le traite déjà
        # sans erreur (`if cd >= move_range: continue` → pool vide). Lever ici serait incohérent
        # avec le chemin sans override, qui pour ce même budget renvoie simplement un pool vide.
        # Seul un budget NÉGATIF est impossible à produire par le moteur → erreur explicite.
        if int(move_budget_override) < 0:
            raise ValueError(
                f"movement_build_valid_destinations_pool: move_budget_override négatif "
                f"({move_budget_override}) pour unit {unit_id} — le moteur ne produit jamais "
                f"un budget < 0 (get_squad_move_budget borne à max(0, ...))"
            )
        move_range = int(move_budget_override)
    else:
        move_range = squad_move_pool_budget_subhex(game_state, str(unit_id))
    # Normalize coordinates to int - raises error if invalid
    start_col, start_row = require_unit_position(unit, game_state)
    start_pos = (start_col, start_row)

    # Use cached enemy_adjacent_hexes from phase start
    # Cache is built once per phase in movement_phase_start()/shooting_phase_start()/charge_phase_start()
    # This reduces O(n) per hex check to O(1) set lookup
    current_player = require_key(game_state, "current_player")
    if current_player is None:
        raise KeyError("game_state missing required 'current_player' field")
    
    # Cache must exist (no fallback) - raise error if missing
    cache_key = f"enemy_adjacent_hexes_player_{current_player}"
    if cache_key not in game_state:
            raise KeyError(f"enemy_adjacent_hexes cache missing for player {current_player} - build_enemy_adjacent_hexes() must be called at phase start")
    enemy_adjacent_hexes = game_state[cache_key]

    unit_id_str = str(unit["id"])
    # Collision niveau-consciente : les figs d'un AUTRE niveau que le mover ne bloquent pas (étages
    # différents ne se chevauchent pas). Niveau du mover = niveau de l'unité (ancre). Tout au niveau 0
    # aujourd'hui → filtre par 0 == comportement historique (zéro régression).
    _mover_level = (
        int(destination_level) if destination_level is not None
        else int(unit.get("level", 0))  # get allowed
    )
    occupied_positions = build_occupied_positions_set(
        game_state, exclude_unit_id=unit_id_str, level=_mover_level
    )
    current_player_int = int(current_player)
    enemy_occupied = build_enemy_occupied_positions_set(
        game_state, current_player=current_player_int, level=_mover_level
    )
    # Figurines qui bloquent le TRANSIT de ce mobile : toggles de config, Desperate Escape
    # (09.07) et exemption M/V (17.01) résolus en un seul endroit, partagé avec la validation
    # (`build_move_transit_blocked`) — les deux côtés de l'invariant « masque ⊆ exécutable ».
    # `enemy_occupied` reste, lui, l'occupation ennemie BRUTE : elle sert au filtre de
    # DESTINATION, que 17.01 ne touche pas (traverser n'est pas s'arrêter dessus).
    from .shared_utils import build_move_traversal_blocked
    _enemy_blocked, _friendly_blocked = build_move_traversal_blocked(
        game_state, unit_id_str, current_player_int, _mover_level
    )
    units_cache = require_key(game_state, "units_cache")
    ez = get_engagement_zone(game_state)
    # Seul `thru_ez` reste lu ici : les deux autres toggles sont appliqués par
    # `build_move_traversal_blocked`, avec Desperate Escape et 17.01, en un seul endroit.
    _thru_ez, _, _ = _get_move_traversal_rules(game_state)
    _mover_player_int = int(require_key(unit, "player"))
    # ez > 1 : une seule liste d’ennemis pour ``_movement_engagement_violates`` (évite O(units)×BFS).
    _enemy_items_for_engagement_ez: Optional[List[Tuple[Any, Any]]] = None
    if ez > 1:
        _enemy_items_for_engagement_ez = _enemy_items_within_move_engagement_horizon(
            game_state,
            unit,
            unit_id_str,
            _mover_player_int,
            start_col,
            start_row,
            int(move_range),
            units_cache,
        )

    if game_state.get("debug_mode", False) and "episode_number" in game_state and "turn" in game_state:
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        total_units = len(units_cache)
        from engine.game_utils import add_console_log, safe_print
        log_msg = f"[OCCUPIED_POSITIONS] E{episode} T{turn} Unit {unit['id']}: total={total_units}, occupied_cells={len(occupied_positions)}"
        add_console_log(game_state, log_msg)
        safe_print(game_state, log_msg)

    # Generic cache-coherence diagnostics (debug mode only):
    # compare precomputed enemy adjacency cache vs. fresh reconstruction from units_cache.
    if game_state.get("debug_mode", False):
        expected_enemy_adjacent_hexes: Set[Tuple[int, int]] = set()
        board_cols = require_key(game_state, "board_cols")
        board_rows = require_key(game_state, "board_rows")
        current_player_int = int(current_player)
        for enemy_id, enemy_entry in enemy_entries_on_battlefield(units_cache, current_player_int):
            enemy_hp = require_key(enemy_entry, "HP_CUR")
            if enemy_hp <= 0:
                continue
            enemy_col, enemy_row = enemy_entry["col"], enemy_entry["row"]
            for neighbor_col, neighbor_row in get_hex_neighbors(enemy_col, enemy_row):
                if (
                    neighbor_col < 0
                    or neighbor_row < 0
                    or neighbor_col >= board_cols
                    or neighbor_row >= board_rows
                ):
                    continue
                expected_enemy_adjacent_hexes.add((neighbor_col, neighbor_row))

        cache_missing = expected_enemy_adjacent_hexes - enemy_adjacent_hexes
        cache_extra = enemy_adjacent_hexes - expected_enemy_adjacent_hexes
        if cache_missing or cache_extra:
            # TEMPORARY LOG: diagnostic for stale enemy adjacency cache investigation.
            from engine.game_utils import add_debug_file_log
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            max_examples = 8
            missing_examples = sorted(cache_missing)[:max_examples]
            extra_examples = sorted(cache_extra)[:max_examples]
            add_debug_file_log(
                game_state,
                f"[TEMPORARY LOG][MOVE CACHE MISMATCH] E{episode} T{turn} Unit {unit_id}: "
                f"player={current_player_int} "
                f"cached={len(enemy_adjacent_hexes)} expected={len(expected_enemy_adjacent_hexes)} "
                f"missing={len(cache_missing)} extra={len(cache_extra)} "
                f"missing_examples={missing_examples} extra_examples={extra_examples}",
            )

    _m_prep_end = _perf_clock.perf_counter() if _pt else None

    # Take to the skies (Règles 21.03) : une unité FLY ne traverse murs/figurines QUE si le vol est
    # déclaré pour le mouvement en cours. Qui déclare : le joueur humain via le handler dédié ;
    # le siège piloté par le modèle via le point de choix `fly_declaration` (V11 §0.48 `L6`),
    # posé avant la construction de ce pool. Logique partagée via _fly_traversal_active.
    _fly_active = _fly_traversal_active(game_state, unit, unit_id)

    # Métrique du move résolue UNE fois ICI : trois sites de cette fonction la relisaient — les deux
    # gardes de route (`_mono_hex_bfs_shortcut`, sol et FLY) et le choix de géométrie du chemin
    # empreinte —, jusqu'à deux fois sur un même appel. `game_state` n'est pas muté entre-temps,
    # donc c'était la même valeur, et le sélecteur repasse par le config-loader à chaque appel
    # (mesuré : 2,3 µs à x5). `_build_multi_hex_vectorized` la résout encore pour son propre compte :
    # il a d'autres appelants, ce n'est pas une relecture de CE choix de route.
    _metric_move = _move_distance_metric(game_state)

    # Squad move rigide (destination sol) : si des figs partent de l'étage, retrancher le coût de
    # descente de la plus haute (§13.06) à TOUT le squad. No-op si fly actif ou tout au sol. Si le
    # budget ne couvre pas la descente, CE régime est impossible → pool vide (aucune destination) ;
    # l'escouade reste éligible et peut encore déclarer un Advance, dont le budget plus large
    # repassera ici (cf. `get_eligible_units`, qui ne retranche donc PAS la descente).
    _descent_pen = squad_descent_penalty_subhex(game_state, unit_id)
    if _descent_pen > 0:
        if _descent_pen >= move_range:
            if read_only:
                return []
            game_state["valid_move_destinations_pool"] = []
            game_state["valid_move_destinations_pool_by_level"] = {0: []}
            game_state["move_preview_footprint_span"] = _move_preview_footprint_span(unit)
            game_state["move_preview_footprint_zone"] = set()
            game_state["move_preview_border"] = []
            if not game_state.get("gym_training_mode"):
                _sync_move_preview_mask_loops(game_state, set())
            return []
        move_range = move_range - _descent_pen

    # FLY units: BFS ignoring walls/occupation for traversal.
    # Only destination validation checks walls, occupation and engagement zone.
    # This replaces the O(cols×rows) scan with O(reachable) BFS.
    if _fly_active:
        board_cols = require_key(game_state, "board_cols")
        board_rows = require_key(game_state, "board_rows")
        fly_visited_n = 0
        valid_destinations: List[Tuple[int, int]] = []
        fly_rejected_footprint = 0

        _fly_bcols = board_cols
        _fly_brows = board_rows
        _fly_walls = game_state.get("wall_hexes", set())
        _fly_occupied = occupied_positions

        # ROUTE : raccourci BFS (disque cube-distance, sans empreinte) ou disque continu de
        # `_build_multi_hex_vectorized`. Prédicat partagé avec la branche sol — cf.
        # `_mono_hex_bfs_shortcut`, qui porte les deux conditions et ce que leur oubli a coûté.
        _fly_base_size = unit["BASE_SIZE"]
        _fly_single_hex_bfs = _mono_hex_bfs_shortcut(game_state, _fly_base_size, _metric_move)

        _fly_off_even: Tuple[Tuple[int, int], ...] = ()
        _fly_off_odd: Tuple[Tuple[int, int], ...] = ()
        if not _fly_single_hex_bfs:
            from engine.hex_utils import precompute_footprint_offsets
            _fly_shape = unit["BASE_SHAPE"]
            if "orientation" in unit:
                _fly_orient = int(require_key(unit, "orientation"))
            else:
                _fly_orient = 0
            _fly_off_even, _fly_off_odd = precompute_footprint_offsets(
                _fly_shape, _fly_base_size, _fly_orient
            )

        # Multi-hex FLY: vectorized NumPy path (cube-distance disk + destination filter).
        if not _fly_single_hex_bfs:
            _m_bfs_start = _perf_clock.perf_counter() if _pt else None
            valid_destinations, _fly_fp_zone_vec, fly_visited_n = _build_multi_hex_vectorized(
                fly=True,
                out_costs=out_costs,
                game_state=game_state,
                unit=unit,
                start_col=start_col,
                start_row=start_row,
                move_range=move_range,
                off_even=_fly_off_even,
                off_odd=_fly_off_odd,
                board_cols=board_cols,
                board_rows=board_rows,
                walls_set=_fly_walls,
                # FLY déclaré (21.03) : rien ne bloque le transit, ni murs ni figurines.
                enemy_transit_blocked=set(),
                friendly_transit_blocked=set(),
                occupied_set=occupied_positions,
                enemy_adjacent_hexes=enemy_adjacent_hexes,
                enemy_items=_enemy_items_for_engagement_ez,
                ez=ez,
                thru_ez=_thru_ez,
            )
            _m_bfs_end = _perf_clock.perf_counter() if _pt else None
            if read_only:
                return valid_destinations
            game_state["valid_move_destinations_pool"] = valid_destinations
            game_state["move_preview_footprint_span"] = _move_preview_footprint_span(unit)
            if game_state.get("gym_training_mode"):
                _fly_fp_zone: Set[Tuple[int, int]] = set()
            else:
                _fly_fp_zone = _fly_fp_zone_vec
            game_state["move_preview_footprint_zone"] = _fly_fp_zone
            game_state["move_preview_border"] = []
            _m_fly_before_sync = _perf_clock.perf_counter() if _pt else None
            if not game_state.get("gym_training_mode"):
                _sync_move_preview_mask_loops(game_state, _fly_fp_zone)
            _m_fly_done = _perf_clock.perf_counter() if _pt else None
            if _pt and _m0 is not None and _m_prep_end is not None and _m_bfs_start is not None and _m_bfs_end is not None and _m_fly_before_sync is not None and _m_fly_done is not None:
                _post_bfs = _m_fly_done - _m_bfs_end
                _fu = _m_fly_before_sync - _m_bfs_end
                _ml = _m_fly_done - _m_fly_before_sync
                append_perf_timing_line(
                    f"MOVE_POOL_BUILD unit={unit_id} fly=True prep_s={_m_prep_end - _m0:.6f} "
                    f"bfs_s={_m_bfs_end - _m_bfs_start:.6f} post_bfs_s={_post_bfs:.6f} "
                    f"footprint_union_s={_fu:.6f} mask_loops_s={_ml:.6f} "
                    f"total_s={_m_fly_done - _m0:.6f} visited={fly_visited_n} valid={len(valid_destinations)} "
                    f"anchors_n={len(valid_destinations)} footprint_hex_n={len(_fly_fp_zone)} "
                    f"MOVE={move_range}"
                )
            _log_movement_debug(game_state, "build_valid_destinations", str(unit_id), f"valid_destinations count={len(valid_destinations)} [FLY vectorized]")
            if game_state.get("debug_mode", False):
                from engine.game_utils import add_debug_file_log
                episode = game_state.get("episode_number", "?")
                turn = game_state.get("turn", "?")
                add_debug_file_log(
                    game_state,
                    f"[MOVE POOL SUMMARY] E{episode} T{turn} Unit {unit_id} [FLY vectorized]: "
                    f"start=({start_col},{start_row}) move_range={move_range} "
                    f"visited={fly_visited_n} valid={len(valid_destinations)} "
                    f"reject_footprint=0",
                )
            return valid_destinations

        # ── EZ de destination, chemin FLY mono-hex : la MÊME source que l'exécution ────────────
        # ⚠️ ROOT CAUSE CORRIGÉE (deux fois de suite au même endroit, d'où ce commentaire long).
        # Ce chemin est celui d'un socle mono-hex, c'est-à-dire `inches_to_subhex == 1` : à cette
        # résolution une figurine tient dans UNE case et la géométrie du jeu est HEXAGONALE
        # (`game_state._scale_socle` normalise le socle en `round`/1 précisément pour ça). L'EZ y
        # est donc l'ensemble hex `enemy_adjacent_hexes_player_N` — exactement ce que lisent
        # `validate_move_plan` / `erode_move_pool_by_squad_block`, et ce que font déjà les DEUX
        # autres branches mono-hex de cette fonction (BFS sol, champ euclidien).
        #
        # L'ancien code appelait ici `_movement_engagement_violates` (métrique `engagement`, donc
        # EUCLIDIENNE) sous une fenêtre de PRUNE dilatée depuis la seule ANCRE ennemie. Deux
        # défauts cumulés :
        #   1. hors fenêtre, l'engagement n'était PAS testé — une escouade ennemie étalée (Boyz,
        #      Termagants) a des figurines à plusieurs hexes de son ancre, et les cases voisines de
        #      CES figurines passaient sans contrôle (régression introduite par `6f495de1`
        #      « gain de perfs », 2026-05-19 ; le jumeau
        #      `_enemy_items_within_move_engagement_horizon` a reçu le correctif par-figurine le
        #      2026-06-03, celui-ci a été oublié) ;
        #   2. même prune corrigée, le prédicat restait euclidien face à une exécution hex — deux
        #      définitions d'une même règle, donc un invariant « masque ⊆ exécutable » qui ne tenait
        #      que par la taille des socles du moment.
        # Le masque offrait donc des destinations inexécutables et le training mourait sur
        # « incohérence masque/exécution ». Lire `_enemy_adj` supprime les deux défauts d'un coup,
        # rend la prune inutile (une appartenance à un set est déjà O(1)) et aligne FLY sur le sol.
        #
        # x5 et au-delà : les socles y sont multi-hex, donc ce chemin n'est pas emprunté — la
        # branche vectorisée conserve la géométrie euclidienne (`_compute_mover_ez_forbidden_mask`).

        _m_bfs_start = _perf_clock.perf_counter() if _pt else None
        _sx = start_col
        _sz = start_row - ((start_col - (start_col & 1)) >> 1)
        for _dx in range(-move_range, move_range + 1):
            _dy_lo = max(-move_range, -move_range - _dx)
            _dy_hi = min(move_range, move_range - _dx) + 1
            for _dy in range(_dy_lo, _dy_hi):
                nc = _sx + _dx
                nr = (_sz - _dx - _dy) + ((nc - (nc & 1)) >> 1)
                if nc < 0 or nr < 0 or nc >= _fly_bcols or nr >= _fly_brows:
                    continue
                nb = (nc, nr)
                if nb == start_pos:
                    continue
                fly_visited_n += 1
                # FLY ignore murs/figurines en traversée (21.03) : la distance de chemin EST la
                # cube-distance, que cette boucle énumère déjà via (_dx, _dy).
                _fly_cost = float(max(abs(_dx), abs(_dy), abs(_dx + _dy)))
                # Destination jamais sur une case occupée (03.01) ni dans l'EZ ennemie (unengaged
                # 09.05) — `_enemy_adj` : MÊME ensemble que l'exécution, cf. le bloc ci-dessus.
                if nb in _fly_walls or nb in _fly_occupied or nb in enemy_adjacent_hexes:
                    fly_rejected_footprint += 1
                else:
                    valid_destinations.append(nb)
                    if out_costs is not None:
                        out_costs[nb] = _fly_cost
        _m_bfs_end = _perf_clock.perf_counter() if _pt else None
        if read_only:
            return valid_destinations
        game_state["valid_move_destinations_pool"] = valid_destinations
        game_state["move_preview_footprint_span"] = _move_preview_footprint_span(unit)
        if game_state.get("gym_training_mode"):
            _fly_fp_zone: Set[Tuple[int, int]] = set()
        else:
            # Le raccourci mono-hex est ACQUIS ici : le chemin vectorisé (`not _fly_single_hex_bfs`)
            # a rendu la main plus haut, dans les deux régimes `read_only`. L'empreinte vaut donc
            # l'ancre. Un `else` reconstruisait la zone par offsets d'empreinte pour un cas qui
            # n'atteint jamais ce point — il posait en repli une branche que rien n'exécute.
            _fly_fp_zone = set(valid_destinations)
            _fly_fp_zone.add(start_pos)
        game_state["move_preview_footprint_zone"] = _fly_fp_zone
        # Non sérialisé (exclu API) ; la preview repose sur footprint_zone / mask_loops.
        game_state["move_preview_border"] = []
        _m_fly_before_sync = _perf_clock.perf_counter() if _pt else None
        if not game_state.get("gym_training_mode"):
            _sync_move_preview_mask_loops(game_state, _fly_fp_zone)
        _m_fly_done = _perf_clock.perf_counter() if _pt else None
        if _pt and _m0 is not None and _m_prep_end is not None and _m_bfs_start is not None and _m_bfs_end is not None and _m_fly_before_sync is not None and _m_fly_done is not None:
            _post_bfs = _m_fly_done - _m_bfs_end
            _fu = _m_fly_before_sync - _m_bfs_end
            _ml = _m_fly_done - _m_fly_before_sync
            append_perf_timing_line(
                f"MOVE_POOL_BUILD unit={unit_id} fly=True prep_s={_m_prep_end - _m0:.6f} "
                f"bfs_s={_m_bfs_end - _m_bfs_start:.6f} post_bfs_s={_post_bfs:.6f} "
                f"footprint_union_s={_fu:.6f} mask_loops_s={_ml:.6f} "
                f"total_s={_m_fly_done - _m0:.6f} visited={fly_visited_n} valid={len(valid_destinations)} "
                f"anchors_n={len(valid_destinations)} footprint_hex_n={len(_fly_fp_zone)} "
                f"MOVE={move_range}"
            )
        _log_movement_debug(game_state, "build_valid_destinations", str(unit_id), f"valid_destinations count={len(valid_destinations)} [FLY BFS]")
        if game_state.get("debug_mode", False):
            from engine.game_utils import add_debug_file_log
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            add_debug_file_log(
                game_state,
                f"[MOVE POOL SUMMARY] E{episode} T{turn} Unit {unit_id} [FLY BFS]: "
                f"start=({start_col},{start_row}) move_range={move_range} "
                f"visited={fly_visited_n} valid={len(valid_destinations)} "
                f"reject_footprint={fly_rejected_footprint}",
            )
        return valid_destinations

    # Pre-extract constants for the BFS hot loop (avoid repeated dict lookups)
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes_set = game_state.get("wall_hexes", set())
    base_size = unit["BASE_SIZE"]
    # ROUTE prise plus bas, et SEULE chose que les trois sites post-BFS doivent tester (bornage
    # rigide, `footprint_zone`, log de perf) : eux dépendent de `_off_even/_off_odd` et du
    # `footprint_zone` que seul le chemin empreinte remplit, pas de la taille du socle. Prédicat
    # partagé avec la branche FLY — cf. `_mono_hex_bfs_shortcut`.
    _single_hex_bfs = _mono_hex_bfs_shortcut(game_state, base_size, _metric_move)

    # ── PIERRE TOMBALE — « Étape 4.1 », champ géodésique euclidien du socle MONO-HEX (2026-08-12) ─
    # Une branche `geodesic_field` SANS empreinte vivait ici, gardée par
    # `_move_distance_metric(...) == "euclidean" and <socle mono-hex>`. Elle était INATTEIGNABLE :
    #   - `combat_utils.resolve_gym_split_metric` force la métrique `hex` dès `geometry_is_hex`
    #     (inches_to_subhex <= 1), donc « mono-hex par la résolution » implique « mesuré en hex » ;
    #   - au-dessus, `game_state._scale_socle` rend BASE_SIZE >= 5 à x5 et >= 10 à x10 (le plus
    #     petit socle des rosters vaut 10), alors que la garde exigeait une taille <= 1.
    # Mesuré le 2026-08-12 : instrumentée, elle n'a été atteinte par AUCUN test du dépôt hors une
    # fixture écrite exprès. C'était un SECOND modèle de la règle 03 en continu, à côté de
    # `_euclidean_ground_anchor_multihex` qui applique la même clearance (rayon du socle) et sert
    # déjà le pool PAR-FIGURINE — deux modèles à tenir en phase, et une divergence
    # escouade/figurine sur les socles non ronds pour seul écart.
    # Elle n'est pas remplacée : c'est `_single_hex_bfs` ci-dessus qui envoie désormais le mono-hex
    # euclidien sur le chemin continu, au prix d'une empreinte d'un seul hex à précalculer.
    # ─────────────────────────────────────────────────────────────────────────────────────────────

    # Grille dense O(1) : même sémantique que ``dict`` (case visitée ou non pour ce BFS).
    _n_cells = board_cols * board_rows
    _vis = bytearray(_n_cells)
    _vis[start_col + start_row * board_cols] = 1
    visited_n = 1
    queue = deque([(start_pos, 0)])
    valid_destinations: List[Tuple[int, int]] = []
    blocked_enemy_adjacent_count = 0
    footprint_zone: Set[Tuple[int, int]] = set()
    _off_even: Tuple[Tuple[int, int], ...] = ()
    _off_odd: Tuple[Tuple[int, int], ...] = ()

    _occupied = occupied_positions
    _enemy_occ = enemy_occupied
    _walls = wall_hexes_set
    _enemy_adj = enemy_adjacent_hexes
    _bcols = board_cols
    _brows = board_rows

    # Figurines bloquant le transit : résolues UNE fois par `build_move_traversal_blocked`
    # (toggles, Desperate Escape 09.07, exemption M/V 17.01). La destination, elle, exclut
    # toujours l'occupation et l'EZ — 17.01 autorise à traverser, pas à s'arrêter dessus.
    _check_ez = not _thru_ez
    _models_blocked = _enemy_blocked | _friendly_blocked

    # Champ sol + obstacles de traversée réutilisables par le multi-niveaux (chemin euclidien
    # multi-hex uniquement). None sur les autres chemins → _multilevel_floor_destinations recalcule
    # son propre champ sol (comportement inchangé).
    _ground_field: Optional[Dict[Tuple[int, int], float]] = None
    _ground_obstacles_tr: Optional[Set[Tuple[int, int]]] = None

    _m_bfs_start = _perf_clock.perf_counter() if _pt else None
    if _single_hex_bfs:
        while queue:
            (cc, cr), cd = queue.popleft()
            if cd >= move_range:
                continue
            nd = cd + 1
            parity = cc & 1
            if parity == 0:
                nb_list = (
                    (cc, cr - 1), (cc + 1, cr - 1), (cc + 1, cr),
                    (cc, cr + 1), (cc - 1, cr), (cc - 1, cr - 1),
                )
            else:
                nb_list = (
                    (cc, cr - 1), (cc + 1, cr), (cc + 1, cr + 1),
                    (cc, cr + 1), (cc - 1, cr + 1), (cc - 1, cr),
                )
            for nb in nb_list:
                nc, nr = nb
                if nc < 0 or nr < 0 or nc >= _bcols or nr >= _brows:
                    continue
                _vidx = nc + nr * board_cols
                if _vis[_vidx]:
                    continue
                if nb in _walls:
                    continue
                if nb in _models_blocked:
                    continue
                if _check_ez and nb in _enemy_adj:
                    blocked_enemy_adjacent_count += 1
                    continue
                _vis[_vidx] = 1
                visited_n += 1
                queue.append((nb, nd))
                # Traversal selon toggles ; la destination ne peut jamais finir sur une case
                # occupée (03.01) ni dans l'EZ ennemie (unengaged, 09.05).
                if nb != start_pos and nb not in _occupied and nb not in _enemy_adj:
                    valid_destinations.append(nb)
                    if out_costs is not None:
                        # `nd` = distance de chemin en hex = en subhex (arêtes de poids 1 + file
                        # FIFO -> 1re visite = distance minimale). Déjà calculée par ce BFS,
                        # simplement retenue (§7 T2).
                        out_costs[nb] = float(nd)
    else:
        # Multi-hex units: pre-compute footprint offsets ONCE, then translate
        from engine.hex_utils import precompute_footprint_offsets
        base_shape = unit["BASE_SHAPE"]
        if "orientation" in unit:
            orientation = int(require_key(unit, "orientation"))
        else:
            orientation = 0
        _off_even, _off_odd = precompute_footprint_offsets(base_shape, base_size, orientation)

        if _metric_move == "euclidean":
            # Ground multi-hex euclidien (preview escouade) — miroir du model pool par-fig
            # (round: clearance continue ; non-round: empreinte discrète). Le gym (move_gym=hex)
            # garde le chemin vectorisé hex ci-dessous.
            valid_destinations, footprint_zone, visited_n, _ground_field, _ground_obstacles_tr = _euclidean_ground_anchor_multihex(
                game_state, unit, start_col, start_row, start_pos, move_range,
                base_shape, base_size, _off_even, _off_odd,
                _bcols, _brows, _walls, _occupied, _enemy_blocked, _friendly_blocked, _enemy_adj,
                _enemy_items_for_engagement_ez, ez, _thru_ez,
            )
            if out_costs is not None:
                # `_ground_field` = {cellule: distance-norme}, le champ géodésique du move (déjà
                # renvoyé par la fonction pour le multi-niveaux) -> conversion en subhex.
                for _dest in valid_destinations:
                    out_costs[_dest] = _ground_field[_dest] / ENGAGEMENT_NORM_HEX_WIDTH
        else:
            # Chemin unique vectorisé NumPy, sémantiquement équivalent au BFS Python hexagonal.
            # Gère toutes les formes de socles (mover et ennemis) et toutes les valeurs de ``ez``.
            valid_destinations, footprint_zone, visited_n = _build_multi_hex_vectorized(
                game_state=game_state,
                unit=unit,
                start_col=start_col,
                start_row=start_row,
                move_range=move_range,
                off_even=_off_even,
                off_odd=_off_odd,
                board_cols=_bcols,
                board_rows=_brows,
                walls_set=_walls,
                enemy_transit_blocked=_enemy_blocked,
                friendly_transit_blocked=_friendly_blocked,
                occupied_set=_occupied,
                enemy_adjacent_hexes=_enemy_adj,
                enemy_items=_enemy_items_for_engagement_ez,
                ez=ez,
                thru_ez=_thru_ez,
                out_costs=out_costs,
            )

    _m_bfs_end = _perf_clock.perf_counter() if _pt else None

    # Bornage rigide d'escouade : une ancre n'est valide que si TOUTES les figs vivantes
    # restent dans le plateau après translation rigide (delta = dest_ancre - ancre_origine).
    # Borne les CENTRES des figs (même définition de "hors board" que validate_move_plan).
    # N'affecte PAS footprint_zone (calculé séparément côté multi-hex) → la zone reste
    # complète, donc inZone ne rétrécit pas et le ghost PvP ne blink pas au bord.
    if not _single_hex_bfs:
        # Escouade absente = désynchronisation : le repli `None` SAUTAIT le bornage rigide, donc
        # acceptait des ancres qui sortent une figurine du plateau.
        _sq_entry = require_unit_from_cache(
            unit_id_str, game_state, "movement_build_valid_destinations_pool"
        )
        _by_model = _sq_entry.get("occupied_hexes_by_model")  # get allowed (mono-fig : absent)
        if _by_model:
            _fc = [int(c) for c, _ in _by_model.values()]
            _fr = [int(r) for _, r in _by_model.values()]
            _min_fc, _max_fc = min(_fc), max(_fc)
            _min_fr, _max_fr = min(_fr), max(_fr)
            # Enveloppe d'empreinte (socle multi-hex) sur les DEUX parités : garantit qu'aucune
            # cellule de l'empreinte d'aucune fig ne déborde, quelle que soit la parité de la
            # colonne de destination (qui peut flipper avec delta_col).
            _foff_c = [int(c) for c, _ in _off_even] + [int(c) for c, _ in _off_odd]
            _foff_r = [int(r) for _, r in _off_even] + [int(r) for _, r in _off_odd]
            _fc_off_min, _fc_off_max = min(_foff_c), max(_foff_c)
            _fr_off_min, _fr_off_max = min(_foff_r), max(_foff_r)
            _lo_c = start_col - _min_fc - _fc_off_min
            _hi_c = start_col + (board_cols - 1) - _max_fc - _fc_off_max
            _lo_r = start_row - _min_fr - _fr_off_min
            _hi_r = start_row + (board_rows - 1) - _max_fr - _fr_off_max
            valid_destinations = [
                (c, r)
                for (c, r) in valid_destinations
                if _lo_c <= c <= _hi_c and _lo_r <= r <= _hi_r
            ]

    if out_costs is not None:
        # Les branches remplissent `out_costs` pendant le BFS, donc AVANT le bornage rigide
        # ci-dessus. Sans cette resynchronisation, `out_costs` porterait des destinations
        # retirées du pool : le masque spatial les rendrait jouables et le decoder y enverrait
        # l'escouade. Le pool reste la seule autorité — les coûts s'y alignent.
        _kept = set(valid_destinations)
        for _stale in [k for k in out_costs if k not in _kept]:
            del out_costs[_stale]

    if read_only:
        # Sortie anticipée : aucune écriture d'état, donc pas de post-BFS (empreinte, étages,
        # mask loops) à mesurer. Le log doit malgré tout être émis ICI — c'est le chemin du
        # masque spatial V11 (`build_squad_move_cell_map`), et sans cette ligne le pool de
        # move reste invisible dans perf_timing.log alors qu'il est construit à chaque masque.
        if _pt and _m0 is not None and _m_prep_end is not None and _m_bfs_start is not None and _m_bfs_end is not None:
            _fp_n = len(_off_even) if not _single_hex_bfs else 1
            _ro_end = _perf_clock.perf_counter()
            # `post_bfs_s` couvre le bornage rigide de l'enveloppe d'empreinte + la resync
            # `out_costs` : sans lui, prep+bfs ne recouvrent pas total et le reliquat (qui scale
            # avec la taille du pool sur socle multi-hex) resterait invisible.
            # `out_costs` distingue les deux appelants read_only : True = masque spatial V11
            # (`build_squad_move_cell_map`), False = test d'eligibilite (resultat jete).
            append_perf_timing_line(
                f"MOVE_POOL_BUILD episode={game_state.get('episode_number', '?')} "
                f"turn={game_state.get('turn', '?')} unit={unit_id} fly=False read_only=True "
                f"out_costs={out_costs is not None} "
                f"single_hex_bfs={_single_hex_bfs} prep_s={_m_prep_end - _m0:.6f} "
                f"bfs_s={_m_bfs_end - _m_bfs_start:.6f} "
                f"post_bfs_s={_ro_end - _m_bfs_end:.6f} "
                f"total_s={_ro_end - _m0:.6f} visited={visited_n} "
                f"valid={len(valid_destinations)} anchors_n={len(valid_destinations)} "
                f"MOVE={move_range} base={perf_field(base_size)} fp={_fp_n}"
            )
        return valid_destinations

    game_state["valid_move_destinations_pool"] = valid_destinations
    # --- Multi-niveaux (étages, chantier 3c step 1 — cible forme B : dict par niveau) ---
    # Le sol (niveau 0) reste EXACTEMENT la liste 2D ci-dessus (source unique inchangée). On ajoute
    # les destinations d'étage (niveaux >= 1) dans un dict séparé. ``valid_move_destinations_pool``
    # (liste) sert de MIROIR TRANSITOIRE = pool[0] → le front actuel ne change pas tant qu'il n'est pas
    # migré vers le dict ``_by_level``. Sans étage déclaré, l'adaptateur renvoie {} (no-op, zéro régression).
    # (Chemin FLY : retourne plus haut ; ``_fly_active`` est donc False ici. Fly+étages = étape ultérieure.)
    _m_floor_start = _perf_clock.perf_counter() if _pt else None
    _floor_dest = _multilevel_floor_destinations(
        game_state, unit, start_pos, move_range,
        (set(wall_hexes_set) | occupied_positions) - {start_pos},
        unit["BASE_SHAPE"], base_size, _off_even, _off_odd, _fly_active,
        precomputed_ground_field=_ground_field,
        precomputed_ground_obstacles=_ground_obstacles_tr,
    )
    # EZ ennemie à la destination sur étage : MÊME contrat que le sol (mirror move phase, 09.05).
    # Sans ce filtre, une case d'étage dans l'EZ d'un ennemi n'était jamais rejetée (l'adaptateur
    # ne testait que murs / occupation-niveau / empreinte-sur-plancher). On réutilise à l'identique
    # les objets d'engagement du sol (`ez`, `units_cache`, `enemy_adjacent_hexes`,
    # `_enemy_items_for_engagement_ez`) → aucune divergence de géométrie avec le niveau 0.
    if _floor_dest:
        _floor_dest = {
            lv: cells
            for lv, cells in (
                (
                    lv,
                    [
                        (c, r)
                        for (c, r) in cells
                        if not _movement_engagement_violates(
                            game_state,
                            unit,
                            c,
                            r,
                            compute_candidate_footprint(c, r, unit, game_state),
                            units_cache,
                            enemy_adjacent_hexes,
                            enemy_cache_items=_enemy_items_for_engagement_ez,
                            engagement_zone_ez=ez,
                        )
                    ],
                )
                for lv, cells in _floor_dest.items()
            )
            if cells
        }
    _m_floor_end = _perf_clock.perf_counter() if _pt else None
    _pool_by_level: Dict[int, List[Tuple[int, int]]] = {0: valid_destinations}
    _pool_by_level.update(_floor_dest)
    game_state["valid_move_destinations_pool_by_level"] = _pool_by_level
    game_state["move_preview_footprint_span"] = _move_preview_footprint_span(unit)

    if _single_hex_bfs:
        footprint_zone = set(valid_destinations)
        footprint_zone.add(start_pos)

    game_state["move_preview_footprint_zone"] = footprint_zone
    game_state["move_preview_border"] = []
    _m_ground_before_sync = _perf_clock.perf_counter() if _pt else None
    if not game_state.get("gym_training_mode"):
        _sync_move_preview_mask_loops(game_state, footprint_zone)
    _m_ground_done = _perf_clock.perf_counter() if _pt else None
    if _pt and _m0 is not None and _m_prep_end is not None and _m_bfs_start is not None and _m_bfs_end is not None and _m_ground_before_sync is not None and _m_ground_done is not None:
        _fp_n = len(_off_even) if not _single_hex_bfs else 1
        _post_bfs = _m_ground_done - _m_bfs_end
        _fu = _m_ground_before_sync - _m_bfs_end
        _ml = _m_ground_done - _m_ground_before_sync
        _mlf = (_m_floor_end - _m_floor_start) if (_m_floor_start is not None and _m_floor_end is not None) else 0.0
        append_perf_timing_line(
            f"MOVE_POOL_BUILD unit={unit_id} fly=False single_hex_bfs={_single_hex_bfs} prep_s={_m_prep_end - _m0:.6f} "
            f"bfs_s={_m_bfs_end - _m_bfs_start:.6f} post_bfs_s={_post_bfs:.6f} "
            f"footprint_union_s={_fu:.6f} multilevel_floor_s={_mlf:.6f} mask_loops_s={_ml:.6f} "
            f"total_s={_m_ground_done - _m0:.6f} visited={visited_n} valid={len(valid_destinations)} "
            f"anchors_n={len(valid_destinations)} footprint_hex_n={len(footprint_zone)} "
            f"MOVE={move_range} base={perf_field(base_size)} fp={_fp_n}"
        )

    _log_movement_debug(game_state, "build_valid_destinations", str(unit_id), f"valid_destinations count={len(valid_destinations)}")
    if game_state.get("debug_mode", False):
        from engine.game_utils import add_debug_file_log
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        add_debug_file_log(
            game_state,
            f"[TEMPORARY LOG][MOVE POOL SUMMARY] E{episode} T{turn} Unit {unit_id}: "
            f"start=({start_col},{start_row}) move_range={move_range} "
            f"visited={visited_n} valid={len(valid_destinations)} "
            f"blocked_enemy_adjacent={blocked_enemy_adjacent_count}",
        )

    return valid_destinations


def _model_multilevel_reachable_cells(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    squad_id: str,
    model: Dict[str, Any],
    start_pos: Tuple[int, int],
    budget: int,
    target_levels: Set[int],
    ground_obstacles: Set[Tuple[int, int]],
    terrain_areas: List[Dict[str, Any]],
    start_level: int = 0,
) -> Dict[int, List[Tuple[int, int]]]:
    """Cases réellement atteignables par la figurine avec le coût de montée/descente §13.06, pour
    CHAQUE niveau de ``target_levels`` (0 = sol/descente inclus). Vue « cellules » de
    ``_model_multilevel_reachable_field`` (source unique), qui porte aussi le COÛT de chaque case.
    Retour : ``{level: [(col, row), ...]}`` (couche vide si aucune case atteignable)."""
    return {
        lv: list(cells)
        for lv, cells in _model_multilevel_reachable_field(
            game_state, unit, squad_id, model, start_pos, budget, target_levels,
            ground_obstacles, terrain_areas, start_level=start_level,
        ).items()
    }


def _model_multilevel_reachable_field(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    squad_id: str,
    model: Dict[str, Any],
    start_pos: Tuple[int, int],
    budget: int,
    target_levels: Set[int],
    ground_obstacles: Set[Tuple[int, int]],
    terrain_areas: List[Dict[str, Any]],
    start_level: int = 0,
) -> Dict[int, Dict[Tuple[int, int], int]]:
    """Cases atteignables AVEC LEUR COÛT, avec le coût de montée/descente §13.06, pour CHAQUE niveau
    de ``target_levels`` (0 = sol/descente inclus). Le champ géodésique multi-niveaux
    (``reachable_multilevel_field``) est construit **une seule fois** depuis ``(start_pos, start_level)``
    puis toutes les couches demandées en sont extraites → source unique, coût vertical facturé
    identiquement en montée ET en descente. Empreinte entière sur le plancher (niveau >= 1), hors mur
    et hors figurine de ce niveau.

    Le coût est rendu en SOUS-HEXES (le champ le calcule en unités-norme), pour être directement
    comparable au nombre de pas d'un BFS de sol — les deux servent le même départage « déplacement
    minimal » côté auto-placement, qui serait faussé par deux échelles différentes.

    ``start_level`` : niveau EFFECTIF de départ du mover (0 = sol). Une fig déjà en hauteur qui finit
    au sol paie la descente ; qui reste sur son étage ne repaie pas de montée (§13.06).
    À n'appeler que pour une unité capable de finir en hauteur, métrique euclidienne, hors FLY.
    """
    from engine.terrain_utils import (
        floor_hexes_at_level, floor_levels_present, validate_floor_placement,
    )
    from engine.hex_utils import get_neighbors, precompute_footprint_offsets
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    walls = set(game_state.get("wall_hexes", set()))  # get allowed
    inches_to_subhex = int(require_key(game_state, "inches_to_subhex"))

    present = floor_levels_present(terrain_areas)
    floor_hexes_by_level = {lv: floor_hexes_at_level(terrain_areas, lv) for lv in present}
    height_by_level: Dict[int, float] = {0: 0.0}
    for a in terrain_areas:
        for fl in a.get("floors", []):  # get allowed
            lv = int(fl["level"])
            hn = float(fl["height_inches"]) * inches_to_subhex * ENGAGEMENT_NORM_HEX_WIDTH
            if lv in height_by_level and abs(height_by_level[lv] - hn) > 1e-6:
                raise ValueError(
                    f"_model_climb_reachable_floor_cells: niveau {lv} avec hauteurs incohérentes entre "
                    f"ruines ({height_by_level[lv]:.3f} vs {hn:.3f}) — hauteur globale par niveau non supportée"
                )
            height_by_level[lv] = hn

    obstacles_by_level: Dict[int, Set[Tuple[int, int]]] = {0: set(ground_obstacles)}
    occupied_by_level: Dict[int, Set[Tuple[int, int]]] = {}
    for lv, fh in floor_hexes_by_level.items():
        figs = build_occupied_positions_set(game_state, exclude_unit_id=squad_id, level=lv)
        occupied_by_level[lv] = figs
        ring = {nb for cell in fh for nb in get_neighbors(cell[0], cell[1]) if nb not in fh}
        obstacles_by_level[lv] = ring | walls | figs

    shape = require_key(model, "BASE_SHAPE")
    base = require_key(model, "BASE_SIZE")
    # Orientation de LA FIGURINE, comme les deux lignes au-dessus lisent SON socle. Lire celle de
    # l'escouade mesurait l'empreinte d'un socle non rond dans une autre orientation que la sienne
    # dès qu'un pivot par-figurine avait eu lieu — `update_model_position` écrit
    # `model["orientation"]` et ne resynchronise jamais celle de l'escouade.
    orientation = int(require_key(model, "orientation"))
    if shape == "round":
        off_even: Tuple[Tuple[int, int], ...] = ()
        off_odd: Tuple[Tuple[int, int], ...] = ()
    else:
        off_even, off_odd = precompute_footprint_offsets(shape, base, orientation)

    field = reachable_multilevel_field(
        start_pos, start_level, shape, base, off_even, off_odd,
        board_cols, board_rows, obstacles_by_level, floor_hexes_by_level, height_by_level,
        budget * ENGAGEMENT_NORM_HEX_WIDTH, allow_vertical=True, ignore_vertical_cost=False,
    )

    stub = {
        "id": squad_id,
        "UNIT_KEYWORDS": require_key(unit, "UNIT_KEYWORDS"),
        "BASE_SHAPE": shape,
        "BASE_SIZE": base,
        "orientation": orientation,
    }
    out: Dict[int, Dict[Tuple[int, int], int]] = {lv: {} for lv in target_levels}
    for (c, r, lv), _d in field.items():
        if lv not in out or (c, r) == start_pos:
            continue
        if (c, r) in walls or (c, r) in occupied_by_level.get(lv, set()):
            continue
        ok, _ = validate_floor_placement(stub, c, r, lv, terrain_areas)
        if ok:
            out[lv][(c, r)] = int(round(_d / ENGAGEMENT_NORM_HEX_WIDTH))
    return out


def _model_climb_reachable_floor_cells(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    squad_id: str,
    model: Dict[str, Any],
    start_pos: Tuple[int, int],
    budget: int,
    view_level: int,
    ground_obstacles: Set[Tuple[int, int]],
    terrain_areas: List[Dict[str, Any]],
    start_level: int = 0,
) -> List[Tuple[int, int]]:
    """Cases de l'étage ``view_level`` atteignables (coût §13.06). Fin wrapper sur
    ``_model_multilevel_reachable_cells`` (source unique du coût vertical) pour une seule couche —
    conserve la signature attendue par la phase fight (pile-in) et le miroir charge.
    """
    return _model_multilevel_reachable_cells(
        game_state, unit, squad_id, model, start_pos, budget, {view_level},
        ground_obstacles, terrain_areas, start_level=start_level,
    ).get(view_level, [])  # get allowed (niveau inatteignable = aucune case)


def movement_build_model_destinations_pool(
    game_state: Dict[str, Any],
    model_id: str,
    provisional_plan: Optional[Dict[str, Tuple[int, ...]]] = None,
    level: int = 0,
    orientation: Optional[int] = None,
) -> Dict[str, Any]:
    """BFS des hexes atteignables pour UNE figurine (move par-figurine, squad_multi_figurines.md).

    provisional_plan : {model_id: (col, row)} positions provisoires des figs
    déjà déplacées dans le plan. Si fourni, remplace models_cache pour les
    sibling figures (évite que les hexes originaux restent bloqués).

    Move normal : budget = MOVE de l'escouade (subhexes). Origine = position
    courante de la figurine dans models_cache (= position de debut de phase, car
    les moves par-figurine ne sont pas committes avant Validate).

    Sol (non-Fly) : ne traverse jamais un mur ; les figs ennemies, amies et la bande
    d'engagement ennemie ne bloquent la traversee que selon les toggles config["move"]
    (_get_move_traversal_rules). Desperate Escape (09.07) traverse les figs ennemies.
    Fly : traversal libre, seule la destination est validee.

    Destination retenue selon les memes regles que validate_move_plan (1 fig,
    sans coherency) : dans le plateau, hors mur, hors collision avec une AUTRE
    escouade, hors zone d'engagement ennemie. Les overlaps avec une coequipiere
    sont geres par preview_move_plan sur le plan complet. Lecture pure.

    Retourne {"destinations": [...], "footprint_mask_loops": [...]}.
    """
    models_cache = require_key(game_state, "models_cache")
    model = models_cache.get(str(model_id))
    if model is None:
        raise KeyError(
            f"movement_build_model_destinations_pool: model {model_id} not in models_cache"
        )

    if game_state.get("sandbox_free_move"):
        board_cols = require_key(game_state, "board_cols")
        board_rows = require_key(game_state, "board_rows")
        terrain_areas = game_state.get("terrain_areas", [])
        from engine.terrain_utils import floor_hexes_at_level, floor_levels_present
        return {
            "destinations": (
                [[c, r, 0] for c in range(board_cols) for r in range(board_rows)]
                + [
                    [c, r, lv]
                    for lv in floor_levels_present(terrain_areas)
                    for c, r in floor_hexes_at_level(terrain_areas, lv)
                ]
            ),
            "footprint_mask_loops": [],
        }

    squad_id = str(model["squad_id"])
    unit = require_unit_by_id(game_state, squad_id)

    # Orientation du MOVER pour l'empreinte du pool : override (pivot molette EN COURS, non committé,
    # transmis par l'UI) si fourni, sinon l'orientation committée de la figurine. Sans ça le pool
    # (EZ ennemie 2", collisions) serait calculé sur l'orientation d'origine → une case « valide »
    # deviendrait illégale une fois le socle pivoté.
    # Repli sur l'orientation d'ESCOUADE retiré : `models_cache` pose TOUJOURS `orientation`
    # (`_build_models_for_unit`), donc il ne se déclenchait jamais — et le jour où il l'aurait
    # fait, il aurait rendu l'orientation d'un bloc pour une figurine pivotée à part.
    mover_orient = int(orientation) if orientation is not None else int(require_key(model, "orientation"))

    _adv_roll = _advance_roll_for(squad_id, game_state)
    if _adv_roll is not None:
        budget = get_squad_move_budget(squad_id, game_state, "advance", advance_roll=_adv_roll)
    else:
        budget = get_squad_move_budget(squad_id, game_state, "normal")
    start_col = int(model["col"])
    start_row = int(model["row"])
    start_pos = (start_col, start_row)

    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())

    player = int(model["player"])
    cache_key = f"enemy_adjacent_hexes_player_{player}"
    enemy_adjacent_hexes = require_key(game_state, cache_key)
    # --- Occupation PAR NIVEAU (étages) : sol (0) + niveau de VUE (si >=1). Deux figs à des étages
    # différents ne se gênent pas ; murs = verticaux prolongés (bloquent la destination à TOUS niveaux).
    # Tout au niveau 0 aujourd'hui → identique au comportement 2D historique (non-régression). ---
    view_level = int(level or 0)
    terrain_areas = require_key(game_state, "terrain_areas")
    # Clairance verticale (§13.06 maison) : hexes de sol infranchissables par ce modèle (trop haut pour
    # passer sous un étage bas). Injecté dans les obstacles AU SOL uniquement (jamais dans wall_hexes
    # partagé : ces hexes SONT le plancher de l'étage, praticable en surface). Vide si assez petit / FLY.
    from engine.terrain_utils import low_clearance_ground_hexes
    # Hauteur de LA FIGURINE qui bouge, pas de son escouade : c'est elle qui passe — ou non — sous
    # le plancher bas, comme c'est son socle qui décide du reste du pool. La primitive EXIGE la
    # figurine (elle refuse une entrée d'escouade), l'héritage lui appartient.
    _low_clear = low_clearance_ground_hexes(terrain_areas, model, unit)
    from engine.terrain_utils import floor_hexes_at_level
    floor_hexes_view: AbstractSet[Tuple[int, int]] = (
        floor_hexes_at_level(terrain_areas, view_level) if view_level >= 1 else set()
    )
    # Niveau EFFECTIF de DÉPART du mover (§13.06) — dérivé de son niveau COMMITTÉ (models_cache),
    # jamais de la vue courante : la facturation de la descente doit être indépendante de l'affichage.
    start_level_eff = resolve_model_effective_level(
        game_state, model, start_col, start_row,
        int(model.get("level", 0)), mover_orient,  # get allowed ; orient EN COURS du mover
    )
    _levels_of_interest: Set[int] = {0} | ({view_level} if view_level >= 1 else set())

    # Ennemis au niveau de VUE (traversal + EZ ancre). Le mover se déplace au niveau de vue.
    enemy_occupied = build_enemy_occupied_positions_set(
        game_state, current_player=player, level=view_level
    )

    # Autres escouades, par niveau (empreinte par-figurine à ce niveau).
    other_occ_by_level: Dict[int, Set[Tuple[int, int]]] = {
        lv: build_occupied_positions_set(game_state, exclude_unit_id=squad_id, level=lv)
        for lv in _levels_of_interest
    }

    # Sœurs (même squad) par niveau EFFECTIF : niveau demandé = 3e élément du plan provisoire si présent
    # (sinon niveau committé), effectif dérivé par l'empreinte sur le plancher (resolve_model_floor_level).
    # provisional_plan override positions/niveaux des figs déjà déplacées dans le plan UI.
    _models_cache = require_key(game_state, "models_cache")
    _squad_models = game_state.get("squad_models", {})  # get allowed
    same_squad_occ_by_level: Dict[int, Set[Tuple[int, int]]] = {}
    sibling_states: List[Tuple[Dict[str, Any], int, int, int]] = []  # (model, col, row, eff_level)
    for mid in _squad_models.get(squad_id, []):  # get allowed
        if str(mid) == str(model_id):  # get allowed
            continue
        sibling = _models_cache.get(str(mid))
        if sibling is None:
            continue
        if provisional_plan and str(mid) in provisional_plan:
            _pv = provisional_plan[str(mid)]
            sc, sr = int(_pv[0]), int(_pv[1])
            sib_req = int(_pv[2]) if len(_pv) >= 3 else int(sibling.get("level", 0))  # get allowed
        else:
            sc, sr = int(sibling["col"]), int(sibling["row"])
            sib_req = int(sibling.get("level", 0))  # get allowed
        sib_eff = resolve_model_effective_level(game_state, sibling, sc, sr, sib_req)
        same_squad_occ_by_level.setdefault(sib_eff, set()).update(
            # Socle de LA SŒUR, pas de l'escouade — les trois lignes au-dessus lisent déjà le
            # sien pour résoudre son niveau. Avec la géométrie d'escouade, un personnage attaché
            # à socle plus grand était SOUS-empreinté : le pool par-figurine offrait des cases
            # qui chevauchent réellement la sœur, que le voile rouge refuse ensuite.
            _compute_unit_occupied_hexes(sc, sr, sibling, game_state)
        )
        sibling_states.append((sibling, sc, sr, sib_eff))

    # Occupation totale (autres squads + sœurs) par niveau — filtre de destination par niveau EFFECTIF.
    fig_occ_by_level: Dict[int, Set[Tuple[int, int]]] = {}
    for lv in _levels_of_interest | set(same_squad_occ_by_level.keys()):
        fig_occ_by_level[lv] = other_occ_by_level.get(lv, set()) | same_squad_occ_by_level.get(lv, set())

    # Obstacles de TRAVERSAL (figs au niveau de vue) : une fig d'un autre étage ne barre pas le chemin.
    other_occupied = other_occ_by_level.get(view_level, set())
    same_squad_occupied = same_squad_occ_by_level.get(view_level, set())

    # Take to the skies (Règles 21.03) : traversée FLY active seulement si le vol est déclaré pour le
    # mouvement en cours — sinon BFS sol. Vaut pour les DEUX mouvements que 21.03 couvre ici, le move
    # et la charge : `_fly_traversal_active` lit le set de déclarations de la phase courante, et rien
    # d'autre, pour tous les sièges (V11 §0.48 `L6`).
    # Pilote le reachable par-figurine ET, via lui, la validation au commit.
    has_fly = _fly_traversal_active(game_state, unit, squad_id)

    # Desperate Escape : unité battle-shocked tentant un fall-back depuis l'ER ennemie.
    # Les figurines peuvent traverser les positions ennemies (règle 09.07). MÊME prédicat que la
    # borne de trajet de la validation (`build_move_transit_blocked`) : ce pool en est le miroir.
    desperate_escape = squad_is_battle_shocked_in_enemy_er(game_state, squad_id)

    # Zone d'engagement ennemie au niveau ANCRE.
    # ez > 1 (Board ×N) : géométrie euclidienne par-mover, source unique partagée avec le path IA
    #   (``_compute_mover_ez_forbidden_mask``) → garantit IA == PvP. L'empreinte du mover est déjà
    #   prise en compte dans le masque, donc l'EZ se teste sur l'ancre et N'EST PAS re-dilatée par
    #   l'empreinte plus bas (``dest_blocked`` ne contient que la géométrie).
    # ez <= 1 (legacy) : dilatation hex pré-calculée (``enemy_adjacent_hexes``), traitée comme la
    #   géométrie (dilatée par l'empreinte dans le filtre multi-hex) — comportement inchangé.
    # Socle de LA FIGURINE — UNE seule lecture pour tous les usages du pool (masque EZ, champ
    # euclidien, clearance de dépôt). Ils DOIVENT voir le même socle, et trois extractions
    # séparées ne l'imposaient pas : c'est précisément l'invariant que le socle par-figurine
    # vient de rétablir face à la validation.
    _mm_shape = require_key(model, "BASE_SHAPE")
    _mm_base = require_key(model, "BASE_SIZE")
    # Ancres où le SOCLE DE CETTE FIGURINE chevauche un mur — même géométrie d'hexagone que la
    # traversée (cf. `socle_blocked_anchor_cells`). Remplace le test par cellules d'empreinte, qui
    # mesurait le mur comme un point et offrait des destinations d'où aucun mouvement n'est possible.
    _wall_anchors = wall_blocked_anchors(
        game_state,
        {"BASE_SHAPE": _mm_shape, "BASE_SIZE": _mm_base, "orientation": mover_orient},
    )
    ez = get_engagement_zone(game_state)
    # `thru_friendly` reste lu ici pour le terme des SŒURS et la mise en cache du champ ;
    # `thru_enemy` est appliqué par `build_move_traversal_blocked`.
    thru_ez, _, thru_friendly = _get_move_traversal_rules(game_state)
    if ez > 1:
        import numpy as np
        units_cache = require_key(game_state, "units_cache")
        # Socle de LA FIGURINE et orientation VISÉE (pivot molette en cours), pas ceux de
        # l'escouade. Passer `unit` calculait l'EZ sur l'orientation COMMITTÉE et sur le socle
        # d'ESCOUADE pendant que `explain_move_plan_rejection` la calcule, depuis le 2026-08-09,
        # sur ceux du PLAN : le pool offrait alors une case que la validation refuse en « ER
        # ennemie » (masque ⊄ exécutable) dès qu'un socle est pivoté ou qu'un personnage
        # attaché porte un socle plus grand que sa datasheet d'escouade.
        _ez_mover = {
            "id": require_key(unit, "id"),
            "BASE_SHAPE": _mm_shape,
            "BASE_SIZE": _mm_base,
            "orientation": mover_orient,
        }
        # …ET la PRUNE des ennemis avec le MÊME socle. Elle borne l'horizon par le rayon du
        # mover : le calculer sur l'escouade alors que le masque mesure la figurine élaguait des
        # ennemis encore pertinents (Boyz 13 → rayon 7, Warboss attaché 20 → rayon 10 : deux
        # cases de trop, que le `+1` de l'horizon ne couvre pas). Le masque n'interdisait alors
        # pas leurs ancres, et la validation — liste ennemie COMPLÈTE — refusait la case. Les
        # deux doivent voir le même socle, sinon la prune rouvre l'incohérence que le socle
        # par-figurine vient de fermer.
        _enemy_items_ez = _enemy_items_within_move_engagement_horizon(
            game_state, _ez_mover, squad_id, player, start_col, start_row,
            int(budget), units_cache,
        )
        _ez_mask = _compute_mover_ez_forbidden_mask(
            game_state, _ez_mover, _enemy_items_ez, ez, board_cols, board_rows
        )
        _ez_cols, _ez_rows = np.where(_ez_mask)
        ez_anchor_forbidden: Set[Tuple[int, int]] = {
            (int(c), int(r)) for c, r in zip(_ez_cols, _ez_rows)
        }
        dest_blocked = _wall_anchors  # figs filtrées par niveau EFFECTIF au post-traitement (superposition inter-étage)
    else:
        ez_anchor_forbidden = enemy_adjacent_hexes
        dest_blocked = _wall_anchors  # idem : occupation des figs traitée par niveau plus bas

    # Figurines bloquant le TRANSIT de CETTE figurine — toggles, Desperate Escape (09.07) et
    # exemption M/V (17.01) résolus par `build_move_traversal_blocked`. Ce site connaît le
    # `model`, donc 17.01 s'y lit PAR FIGURINE, comme la règle l'écrit. La destination
    # (dest_blocked + ez_anchor_forbidden) reste inchangée : jamais sur une case occupée, jamais
    # dans l'EZ ennemie — traverser n'est pas s'arrêter dessus.
    from .shared_utils import build_move_traversal_blocked
    _enemy_blocked, _friendly_blocked = build_move_traversal_blocked(
        game_state, squad_id, player, view_level, model
    )
    # Les SŒURS s'ajoutent au terme ami : elles ne sont pas dans l'occupation « autres escouades »
    # et leur position peut venir du plan provisoire. 17.01 ne les rend pas traversables pour
    # autant — une escouade M/V n'est composée que de figurines M/V, que l'exemption exclut.
    _friendly_traverse = _friendly_blocked | (
        (same_squad_occupied - enemy_occupied) if not thru_friendly else frozenset()
    )

    # Étape 4.1 — miroir par-figurine (PvP interactif) : champ géodésique euclidien du CENTRE de
    # l'ancre (règle 03.01), toutes formes. Rond → clearance continue = rayon socle (option A) ;
    # non-rond → empreinte discrète orientée (cf. _euclidean_move_field). L'empreinte multi-hex est
    # expansée + re-filtrée séparément plus bas. Mêmes obstacles de traversée que le BFS hex.
    # FLY (Règles 21.03) : euclidien aussi, mais champ SANS obstacle (ignore murs/figs) → le champ
    # géodésique dégénère en disque euclidien centre-à-centre (ligne droite, règle 03.01).
    _mm_use_euclidean = _move_distance_metric(game_state) == "euclidean"
    # Instrumentation perf (coût nul si W40K_PERF_TIMING désactivé) — cf. MODEL_POOL_BUILD au return.
    from engine.perf_timing import perf_timing_enabled
    import time as _mm_clock
    _mm_pt = perf_timing_enabled(game_state)
    _mm_t0 = _mm_clock.perf_counter() if _mm_pt else None
    _mm_field_s = 0.0
    _mm_cache_hit = False
    _mm_cells_n = 0
    _mm_obstacles_n = 0
    if _mm_use_euclidean:
        # Cache du CHAMP (sans les filtres de destination) : valide tant que les obstacles ne
        # changent pas. Les sœurs ne sont des obstacles que si NON thru_friendly → cache seulement
        # sûr quand thru_friendly (sinon le champ dépend du plan provisoire, recalcul obligatoire).
        # FLY : le champ n'a aucun obstacle → indépendant du plan provisoire → toujours cacheable.
        _mm_can_cache = thru_friendly or has_fly
        _mm_cache: Dict[Tuple[str, int, int, int, int, int, bool], Dict[Tuple[int, int], float]] = game_state.setdefault(
            "_move_model_field_cache", {}
        )
        # La clé énumère TOUT ce dont le champ dépend. `mover_orient` : l'empreinte, donc les cases
        # atteignables. `view_level` : `enemy_occupied` est construit à ce niveau (cf. plus haut) et
        # entre dans les obstacles tant que `can_move_through_enemy_model` est faux — et le niveau
        # est un paramètre PAR REQUÊTE de l'UI, que rien n'invalide entre deux previews sans commit
        # (verrou : `tests/unit/engine/test_move_model_field_cache_key.py`). `has_fly` : redondant
        # aujourd'hui (le -2" de 21.03 est déjà dans `budget`), gardé pour ne pas faire reposer la
        # clé sur une valeur de règle lue ailleurs — coût nul, `has_fly` ne peut pas scinder une
        # entrée. L'invalidation, elle, N'EST PAS dans la clé : ce cache dépend du vidage explicite
        # de `_invalidate_all_destination_pools_after_movement`, là où le jumeau charge porte
        # `_unit_move_version` et se périme tout seul.
        _mm_key = (
            str(model_id), start_col, start_row, int(budget), mover_orient, view_level, has_fly,
        )
        _mm_field = _mm_cache.get(_mm_key) if _mm_can_cache else None
        _mm_cache_hit = _mm_field is not None
        if _mm_field is None:
            if has_fly:
                # FLY ignore murs/figurines en traversée → aucun obstacle. Les filtres de
                # destination (occupé / EZ ennemie) restent appliqués plus bas, comme le BFS hex.
                _mm_obstacles: Set[Tuple[int, int]] = set()
            else:
                _mm_obstacles = set(wall_hexes) | _low_clear
                _mm_obstacles |= _enemy_blocked
                _mm_obstacles |= _friendly_traverse
                if not (desperate_escape or thru_ez):
                    _mm_obstacles |= ez_anchor_forbidden
            _mm_obstacles.discard(start_pos)  # on est déjà sur la case de départ
            _mm_obstacles_n = len(_mm_obstacles)
            if _mm_shape == "round":
                _mm_off_even_f: Tuple[Tuple[int, int], ...] = ()
                _mm_off_odd_f: Tuple[Tuple[int, int], ...] = ()
            else:
                from engine.hex_utils import precompute_footprint_offsets
                _mm_off_even_f, _mm_off_odd_f = precompute_footprint_offsets(
                    _mm_shape, _mm_base, mover_orient,  # orient EN COURS du mover
                )
            _mm_fb = _mm_clock.perf_counter() if _mm_pt else None
            _mm_field = _euclidean_move_field(
                start_pos, _mm_shape, _mm_base, _mm_off_even_f, _mm_off_odd_f,
                _mm_obstacles, board_cols, board_rows, budget * ENGAGEMENT_NORM_HEX_WIDTH,
            )
            if _mm_pt and _mm_fb is not None:
                _mm_field_s = _mm_clock.perf_counter() - _mm_fb
            # Écriture sous la MÊME condition que la lecture : un champ calculé avec les sœurs en
            # obstacles (non cacheable) n'a rien à faire dans le cache, même si aucune lecture ne
            # peut l'atteindre à budget égal aujourd'hui.
            if _mm_can_cache:
                _mm_cache[_mm_key] = _mm_field
        _mm_cells_n = len(_mm_field)
        # Filtres de destination appliqués À CHAQUE appel (dépendent du plan provisoire via
        # dest_blocked=same_squad) : jamais sur case occupée/mur ni dans l'EZ — identique au BFS hex.
        reachable: List[Tuple[int, int]] = [
            cell
            for cell in _mm_field
            if cell != start_pos and cell not in dest_blocked and cell not in ez_anchor_forbidden
        ]
    else:
        visited: Set[Tuple[int, int]] = {start_pos}
        reachable = []
        queue: deque = deque([(start_col, start_row, 0)])
        while queue:
            c, r, d = queue.popleft()
            if d >= budget:
                continue
            for nc, nr in get_hex_neighbors(c, r):
                if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
                    continue
                cell = (nc, nr)
                if cell in visited:
                    continue
                if not has_fly:
                    if cell in wall_hexes:
                        continue
                    if cell in _enemy_blocked or cell in _friendly_traverse:
                        continue
                    if not (desperate_escape or thru_ez) and cell in ez_anchor_forbidden:
                        continue
                visited.add(cell)
                queue.append((nc, nr, d + 1))
                # Validite destination : murs + toutes figs occupant la cellule + engagement ennemi
                # (ez_anchor_forbidden = EZ au niveau ancre).
                if cell in dest_blocked or cell in ez_anchor_forbidden:
                    continue
                reachable.append(cell)

    # Empreinte du mover (offsets pré-calculés) : sert au filtre destination par niveau ET à la zone.
    # Socle de LA FIGURINE, comme le champ géodésique, le masque EZ, les sœurs et
    # `validate_move_plan`. C'était le DERNIER site de cette fonction à lire celui de
    # l'ESCOUADE : un personnage attaché à socle plus grand (Warboss 20 dans des Boyz 13) voyait
    # son empreinte sous-évaluée pour les bornes, les murs, l'occupation et le niveau de
    # plancher — donc des destinations offertes que la validation refuse.
    base_size = require_key(model, "BASE_SIZE")
    base_shape = require_key(model, "BASE_SHAPE")
    orientation = mover_orient  # orient EN COURS du mover (pivot molette non committé)
    is_single_hex = socle_is_single_hex(base_shape, base_size)
    if is_single_hex:
        _off_even: Tuple[Tuple[int, int], ...] = ((0, 0),)
        _off_odd: Tuple[Tuple[int, int], ...] = ((0, 0),)
    else:
        from engine.hex_utils import precompute_footprint_offsets
        _off_even, _off_odd = precompute_footprint_offsets(base_shape, base_size, orientation)

    def _mover_cells(ac: int, ar: int) -> List[Tuple[int, int]]:
        offs = _off_even if (ac & 1) == 0 else _off_odd
        return [(ac + dc, ar + dr) for dc, dr in offs]

    def _eff_level(cells: List[Tuple[int, int]]) -> int:
        # Niveau EFFECTIF de la candidate : étage vue si l'empreinte tient ENTIÈREMENT sur le plancher
        # (13.06, même dérivation que resolve_model_floor_level), sinon sol (0).
        if view_level >= 1 and floor_hexes_view and all(c in floor_hexes_view for c in cells):
            return view_level
        return 0

    # Filtre destination PAR NIVEAU EFFECTIF : empreinte dans le plateau, hors murs (tous niveaux),
    # hors occupation des figs DE CE NIVEAU. Une fig d'un autre étage ne bloque pas (superposition).
    # Le BFS ne borne que le hex central → l'empreinte complète est revérifiée ici.
    _reachable_lvl: List[Tuple[int, int]] = []
    eff_by_dest: Dict[Tuple[int, int], int] = {}
    for ac, ar in reachable:
        cells = _mover_cells(ac, ar)
        if any(not (0 <= c < board_cols and 0 <= r < board_rows) for c, r in cells):
            continue
        if (ac, ar) in _wall_anchors:
            continue
        eff = _eff_level(cells)
        if any(c in fig_occ_by_level.get(eff, set()) for c in cells):
            continue
        _reachable_lvl.append((ac, ar))
        eff_by_dest[(ac, ar)] = eff
    reachable = _reachable_lvl

    # --- Multi-niveaux (§13.06) : correction des placements EN HAUTEUR ---------------------------------
    # Le champ planaire ci-dessus tague « étage » (eff == view_level) toute case dont l'empreinte tient
    # sur le plancher, MAIS sans coût de montée et sans vérifier la capacité mot-clé. On corrige :
    #   - unité NON-montante → ces cases sont RETIRÉES (le preview s'arrête au bord de l'empreinte) ;
    #   - unité montante     → elles sont REMPLACÉES par le sous-ensemble réellement atteignable avec le
    #     coût de montée/descente (champ géodésique multi-niveaux, source unique reachable_multilevel_field).
    # Les cases au SOL (eff 0) sont conservées telles quelles SI le mover part du sol. Si le mover part
    # d'un ÉTAGE (start_level_eff >= 1), le champ planaire sol est FAUX (descente gratuite) : le sol est
    # alors re-dérivé du champ multi-niveaux (descente facturée, §13.06) — indépendant de la vue.
    # FLY et métrique hex : hors périmètre (fly+étages différé, floors euclidiens) → inchangé.
    _floor_start = start_level_eff >= 1
    if _mm_use_euclidean and not has_fly and ((view_level >= 1 and floor_hexes_view) or _floor_start):
        from engine.game_state import unit_can_occupy_upper_floor
        _can_climb = unit_can_occupy_upper_floor(require_key(unit, "UNIT_KEYWORDS"))
        if _floor_start and not _can_climb:
            # Incohérent : une fig posée en hauteur est forcément montante (13.06). Erreur explicite.
            raise ValueError(
                f"movement_build_model_destinations_pool: model {model_id} committé à level "
                f"{start_level_eff} sans mot-clé INFANTRY/BEASTS/SWARM/FLY/MONSTER (13.06)"
            )
        _floor_dests: List[Tuple[int, int]] = []
        if _floor_start:
            # Mover DÉJÀ en hauteur : sol (descente) ET étage courant sortent du MÊME champ multi-niveaux
            # (construit une fois), seedé au niveau EFFECTIF réel du mover → coût de descente §13.06 facturé.
            _ground_obs = set(wall_hexes) | _low_clear
            _ground_obs |= _enemy_blocked
            _ground_obs |= _friendly_traverse
            if not (desperate_escape or thru_ez):
                _ground_obs |= ez_anchor_forbidden
            _ground_obs.discard(start_pos)
            _targets: Set[int] = {0} | ({view_level} if view_level >= 1 else set())
            _by_level = _model_multilevel_reachable_cells(
                game_state, unit, squad_id, model, start_pos, budget, _targets,
                _ground_obs, terrain_areas, start_level=start_level_eff,
            )
            _ground_dests = _by_level.get(0, [])  # get allowed (niveau inatteignable = aucune case)
            _floor_dests = _by_level.get(view_level, []) if view_level >= 1 else []  # get allowed (niveau inatteignable = aucune case)
        else:
            # Mover au SOL, vue étage : comportement HISTORIQUE (sol libre planaire + montée facturée).
            # Sol : le BORD d'étage est géré par la clairance HEX (``_low_clear``), pas un test euclidien.
            _ground_dests = [_d for _d in reachable if eff_by_dest[_d] == 0]
            if _can_climb:
                _ground_obs = set(wall_hexes) | _low_clear
                _ground_obs |= _enemy_blocked
                _ground_obs |= _friendly_traverse
                if not (desperate_escape or thru_ez):
                    _ground_obs |= ez_anchor_forbidden
                _ground_obs.discard(start_pos)
                _floor_dests = _model_climb_reachable_floor_cells(
                    game_state, unit, squad_id, model, start_pos, budget, view_level,
                    _ground_obs, terrain_areas,
                )
        # EZ ennemie à la DESTINATION (sol ET étage) : jamais finir dans l'EZ (09.05) — mirror move phase.
        _ground_dests = [_d for _d in _ground_dests if _d not in ez_anchor_forbidden]
        _floor_dests = [_d for _d in _floor_dests if _d not in ez_anchor_forbidden]
        reachable = _ground_dests + _floor_dests
        _floor_set = set(_floor_dests)
        eff_by_dest = {_d: (view_level if _d in _floor_set else 0) for _d in reachable}

    # Empêche le DÉPÔT sur un chevauchement de socle avec une coéquipière AU MÊME NIVEAU EFFECTIF
    # (au lieu de le détecter après coup via le voile rouge). Clearance euclidienne par base RÉELLE —
    # même primitive (footprints_overlap) que movement_preview_move_plan → pool et voile cohérents.
    # Tangence (gap≈0) tolérée. Sœurs d'un autre étage : pas de gêne.
    from engine.hex_utils import Socle, footprints_overlap
    _mover_orient = mover_orient  # orient EN COURS du mover (socle testé à chaque destination)
    sibling_socles_by_level: Dict[int, List[Socle]] = {}
    for _sib, _sc, _sr, _sib_eff in sibling_states:
        _s_shape = require_key(_sib, "BASE_SHAPE")
        _s_base = require_key(_sib, "BASE_SIZE")
        # Empreinte du SIBLING : SON orientation propre, pas celle du mover ni celle de l'escouade.
        # Le repli sur l'orientation d'unité qui vivait ici ne se déclenchait jamais
        # (`models_cache` pose toujours `orientation`) et aurait rendu celle du bloc.
        _s_orient = int(require_key(_sib, "orientation"))
        _s_fp = None if _s_shape == "round" else compute_candidate_footprint(
            _sc, _sr,
            {"BASE_SHAPE": _s_shape, "BASE_SIZE": _s_base, "orientation": _s_orient},
            game_state,
        )
        sibling_socles_by_level.setdefault(_sib_eff, []).append(
            Socle(shape=_s_shape, base_size=_s_base, col=_sc, row=_sr, fp=_s_fp)
        )
    if sibling_socles_by_level:
        _intra_filtered: List[Tuple[int, int]] = []
        for _dc, _dr in reachable:
            _same_level = sibling_socles_by_level.get(eff_by_dest[(_dc, _dr)], [])
            if not _same_level:
                _intra_filtered.append((_dc, _dr))
                continue
            _m_fp = None if _mm_shape == "round" else compute_candidate_footprint(
                _dc, _dr,
                {"BASE_SHAPE": _mm_shape, "BASE_SIZE": _mm_base, "orientation": _mover_orient},
                game_state,
            )
            _m_socle = Socle(shape=_mm_shape, base_size=_mm_base, col=_dc, row=_dr, fp=_m_fp)
            if not any(footprints_overlap(_m_socle, _s) for _s in _same_level):
                _intra_filtered.append((_dc, _dr))
        reachable = _intra_filtered

    # Footprint zone per-fig : destinations (déjà validées) ∪ start, expandées selon BASE_SIZE.
    if is_single_hex:
        footprint_zone: Set[Tuple[int, int]] = set(reachable)
        footprint_zone.add(start_pos)
    else:
        footprint_zone = set()
        for ac, ar in reachable:
            offs = _off_even if (ac & 1) == 0 else _off_odd
            for dc, dr in offs:
                footprint_zone.add((ac + dc, ar + dr))
        s_offs = _off_even if (start_col & 1) == 0 else _off_odd
        for dc, dr in s_offs:
            footprint_zone.add((start_col + dc, start_row + dr))
        # Fix visuel : l'expansion du start peut déborder sur des murs adjacents.
        footprint_zone -= wall_hexes

    # Calcul mask loops sans ecriture permanente dans game_state.
    _prev_loops = game_state.get("move_preview_footprint_mask_loops")
    _sync_move_preview_mask_loops(game_state, footprint_zone)
    mask_loops = game_state.get("move_preview_footprint_mask_loops", [])  # get allowed
    game_state["move_preview_footprint_mask_loops"] = _prev_loops  # get allowed

    if _mm_pt and _mm_t0 is not None:
        from engine.perf_timing import append_perf_timing_line, perf_field
        append_perf_timing_line(
            f"MODEL_POOL_BUILD model={model_id} metric={'euclidean' if _mm_use_euclidean else 'hex'} "
            f"cache_hit={_mm_cache_hit} field_build_s={_mm_field_s:.6f} total_s={_mm_clock.perf_counter() - _mm_t0:.6f} "
            f"field_cells={_mm_cells_n} reachable={len(reachable)} obstacles={_mm_obstacles_n} "
            f"base={perf_field(_mm_base)} budget={budget} fly={has_fly}"
        )

    # Chaque destination porte son niveau EFFECTIF (0 = sol, view_level = étage) → le front pose la fig
    # au bon niveau au lieu de forcer la vue courante (§13.06 : sol et étage sont des placements distincts).
    destinations_with_level = [[c, r, eff_by_dest[(c, r)]] for (c, r) in reachable]
    return {"destinations": destinations_with_level, "footprint_mask_loops": mask_loops}


def movement_preview_move_plan(
    game_state: Dict[str, Any], squad_id: str, plan: MovePlan
) -> Dict[str, Any]:
    """Dry-run d'un plan provisoire par-figurine (move normal). Aucune ecriture.

    ``plan`` doit contenir TOUTES les figurines vivantes de l'escouade (sinon le
    test de cohesion est fausse).

    Voile rouge d'une fig = elle est sur un hex INTERDIT (mur, EZ ennemie, overlap
    avec une autre escouade ou une coequipiere, hors budget) OU hors COHESION 2"
    (moins du nb requis de voisins dans la distance de cohesion). En single-fig move
    le pool empeche deja les hex interdits → seul le cas cohesion survient ; en drop
    d'escouade rigide une fig peut tomber sur un hex interdit → voile rouge.

    Retourne :
      - per_model: {model_id: bool} — True = fig valide (placement legal ET cohesion).
        False => voile rouge cote UI.
      - coherency_ok: bool — cohesion respectee sur l'ensemble du plan.
      - can_validate: bool — toutes les figs valides (placement + cohesion).
    """
    _adv_roll = _advance_roll_for(str(squad_id), game_state)
    if _adv_roll is not None:
        budget = get_squad_move_budget(str(squad_id), game_state, "advance", advance_roll=_adv_roll)
    else:
        budget = get_squad_move_budget(str(squad_id), game_state, "normal")
    # L'EZ ennemie est vérifiée par ``validate_move_plan`` lui-même, dans les DEUX métriques et
    # par géométrie de socle (``move_enemy_ez_forbidden_cells``). Le cas spécial qui vivait ici —
    # désactiver ``forbid_enemy_er`` sous ``ez > 1`` puis refaire le test en euclidien — existait
    # parce que le prédicat de ``validate_move_plan`` était alors le set hex centre-à-centre,
    # faux dès qu'un socle couvre plusieurs cases. Il est devenu le bon : le contourner ici
    # rétablirait deux définitions de la même règle, ce que ce correctif supprime.
    c_individual = {"budget_per_model": budget, "require_coherency": False}
    # Normalisation niveau (étages) : entrée 3-uplet ou 4-uplet ; niveau absent (None) = « garder le
    # niveau courant » de la figurine (models_cache). ``norm`` = liste de (mid, col, row, level_EFFECTIF).
    # Niveau EFFECTIF (13.06) : le niveau demandé (vue) n'est retenu que si l'empreinte tient ENTIÈREMENT
    # sur le plancher ; sinon la fig est au SOL (0). PAS de voile rouge pour un débordement partiel : on
    # la ramène simplement au niveau 0 (cohérent avec le pool de destinations et le déploiement).
    _mc_norm = require_key(game_state, "models_cache")
    # Entrées NORMALISÉES : niveau EFFECTIF (13.06) et orientation RÉSOLUE (5ᵉ champ du plan si
    # le pivot molette est en cours, sinon celle de la fig). Une seule liste, pas de listes
    # parallèles ré-jointes par indice : c'est la forme qu'attendent le footprint orienté
    # par-fig, `resolve_model_floor_level` et `validate_move_plan` en aval.
    norm: List[Tuple[str, int, int, int, int]] = []
    for e in plan:
        _mid = str(e[0])
        _m_norm = _mc_norm[_mid]
        _ori = plan_entry_model_orientation(e, _m_norm)
        _lvl_eff = resolve_model_effective_level(
            game_state, _m_norm, int(e[1]), int(e[2]), plan_entry_level(e), _ori
        )
        norm.append((_mid, int(e[1]), int(e[2]), _lvl_eff, _ori))

    # Cohesion 03.03 par fig : deleguee a coherency_violation_flags (source UNIQUE partagee avec le
    # commit), qui respecte game_rules.cohesion_distance_mode (euclidean | footprint).
    n = len(norm)

    # Calcul des empreintes par fig
    from engine.hex_utils import precompute_footprint_offsets as _pfo
    # Prédicat PARTAGÉ avec le pool (`movement_build_model_destinations_pool`) : sans le garde de
    # forme, un socle oval passait pour mono-hex et `fp_wall` / `fp_other` / `fp_intra` / l'EZ ne
    # regardaient que son ancre — un socle de 23 hexes se validait par-dessus une escouade amie.
    # Empreinte PAR FIGURINE — SOCLE compris, pas seulement l'orientation. Ces empreintes sont
    # le SEUL test au niveau socle du voile rouge (`fp_wall` / `fp_other` / `fp_intra`) :
    # `build_move_blocked_cells_by_level` teste la cellule d'ANCRE. Les construire au socle
    # d'ESCOUADE sous-évaluait donc un personnage attaché à socle plus grand, et un commit
    # pouvait poser son socle par-dessus un mur ou une autre escouade.
    footprints: List[Set[Tuple[int, int]]] = []
    for _mid_fp, col, row, _lv_fp, ori in norm:
        _m_fp = _mc_norm[_mid_fp]
        _fp_shape = require_key(_m_fp, "BASE_SHAPE")
        _fp_size = require_key(_m_fp, "BASE_SIZE")
        if socle_is_single_hex(_fp_shape, _fp_size):
            footprints.append({(col, row)})
            continue
        # ``_pfo`` est mémoïsé par (shape, size, orient) → pas de surcoût.
        _off_even, _off_odd = _pfo(_fp_shape, _fp_size, ori)
        offs = _off_even if (col & 1) == 0 else _off_odd
        footprints.append({(col + dc, row + dr) for dc, dr in offs})

    _mc_coh = require_key(game_state, "models_cache")
    cohesion_models = [
        {**_mc_coh[str(mid)], "col": nc, "row": nr} for mid, nc, nr, _lv, _o in norm
    ]
    cohesion_red = coherency_violation_flags(cohesion_models, game_state)

    # Occupation des autres escouades PAR NIVEAU (figs à des étages différents ne se gênent pas ;
    # murs verticaux prolongés gérés par wall_hexes, cf. verticalite.md). Calcul unique par niveau du plan.
    other_occ_by_level: Dict[int, Set[Tuple[int, int]]] = {
        lv: build_occupied_positions_set(game_state, exclude_unit_id=str(squad_id), level=lv)
        for lv in {lv for _, _, _, lv, _o in norm}
    }

    # Collision intra-escouade : clearance EUCLIDIENNE par-figurine (≠ intersection de
    # footprints hex, qui sous-estime le disque et laisse passer un chevauchement de socle
    # ~16% à 5 sous-hex d'écart). Socle construit avec la base RÉELLE de chaque fig
    # (models_cache) → un Captain (base 8) parmi des Intercessors (base 6) n'est plus
    # sous-estimé. Tangence (gap≈0) tolérée, superposition stricte interdite.
    from engine.hex_utils import Socle, footprints_overlap
    _models_cache_intra = require_key(game_state, "models_cache")
    intra_socles: List["Socle"] = []
    for (mid, nc, nr, _lv, _ori_fig), fp_par in zip(norm, footprints):
        m = require_key(_models_cache_intra, str(mid))
        m_shape = require_key(m, "BASE_SHAPE")
        m_base = require_key(m, "BASE_SIZE")
        # `fp_par` EST déjà l'empreinte de cette figurine (socle + orientation) : la branche de
        # recalcul qui vivait ici n'existait que parce que `footprints` était construit au socle
        # d'ESCOUADE et ne convenait qu'aux figurines de même socle.
        m_fp = fp_par
        intra_socles.append(
            Socle(shape=m_shape, base_size=m_base, col=int(nc), row=int(nr), fp=m_fp, orientation=_ori_fig)
        )

    per_model: Dict[str, bool] = {}
    for idx, (mid, nc, nr, lv, _ori_v) in enumerate(norm):
        # L'entrée normalisée part TELLE QUELLE, orientation comprise : la validation borne le
        # trajet par le champ any-angle, dont les obstacles sont dilatés par l'empreinte ORIENTÉE.
        # La laisser tomber ici faisait valider le socle à son orientation COMMITTÉE pendant que le
        # pool l'offrait à son orientation pivotée — voile rouge sur une case parfaitement légale.
        base_valid = validate_move_plan([norm[idx]], game_state, c_individual)
        fp = footprints[idx]
        # Mur : géométrie d'hexagone sur l'ANCRE, comme le pool et la traversée. Le test par
        # cellules d'empreinte qui vivait ici mesurait le mur comme un point : plus laxiste que
        # le pool, il ne pouvait plus contredire une destination offerte, mais il laissait passer
        # un socle chevauchant réellement un mur (jumeau exact de `_wall_anchors` du pool).
        _m_veil = _mc_norm[str(mid)]
        fp_wall = (nc, nr) in wall_blocked_anchors(
            game_state,
            {
                "BASE_SHAPE": require_key(_m_veil, "BASE_SHAPE"),
                "BASE_SIZE": require_key(_m_veil, "BASE_SIZE"),
                "orientation": _ori_v,
            },
        )
        _other_lv = other_occ_by_level.get(lv, set())
        fp_other = bool(_other_lv and fp & _other_lv)
        # Collision intra-escouade uniquement entre figs AU MÊME NIVEAU (étages différents = pas de gêne).
        fp_intra = any(
            footprints_overlap(intra_socles[idx], intra_socles[j])
            for j in range(n)
            if j != idx and norm[j][3] == lv
        )
        # Niveau (étages) : plus de voile rouge « débordement » — ``lv`` est déjà le niveau EFFECTIF
        # (resolve_model_floor_level ci-dessus a ramené au sol toute fig dont l'empreinte déborde du
        # plancher). Une fig « en partie sur l'étage » est donc simplement traitée au niveau 0.
        # EZ ennemie : plus de test séparé ici. ``base_valid`` la couvre désormais dans les deux
        # métriques, avec la géométrie de socle de LA FIGURINE (models_cache) et non celle de
        # l'escouade — un personnage attaché à socle plus grand était mesuré à la mauvaise taille.
        per_model[str(mid)] = bool(
            base_valid and not fp_wall and not fp_other and not fp_intra
            and not cohesion_red[idx]
        )

    coherency_ok = not any(cohesion_red)
    all_valid = len(per_model) > 0 and all(per_model.values())
    # would_flee : l escouade est-elle actuellement engagee (positions PRE-move) ? Si oui,
    # tout commit sera un Fall Back => badge fui sur le ghost de preview. Independant du plan
    # (meme primitive bord-a-bord que le commit, cf was_engaged dans le handler de commit).
    would_flee = _squad_is_in_enemy_er(game_state, str(squad_id))
    return {
        "per_model": per_model,
        "coherency_ok": coherency_ok,
        "can_validate": bool(all_valid),
        "would_flee": bool(would_flee),
    }


def movement_commit_move_plan_handler(
    game_state: Dict[str, Any], squad_id: str, action: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """Valide (= bouton Validate) puis commit un plan provisoire par-figurine.

    ``action["plan"]`` : liste de ``[model_id, col, row, level(, orientation)]``, DOIT couvrir
    toutes les figurines vivantes de l'escouade (sinon la cohesion est fausse). Move
    normal ou fall_back selon engagement de l'escouade au moment du commit.

    Note brique 1 : aucun reactive move n'est declenche ici (move par-figurine) —
    a ajouter dans une tranche ulterieure si necessaire.
    """
    if "plan" not in action:
        raise KeyError(f"commit_move_plan action missing required 'plan' field: {action}")
    raw_plan = action["plan"]
    if not isinstance(raw_plan, list) or not raw_plan:
        return False, {"error": "empty_move_plan", "unitId": squad_id}
    # Entrées 4 (niveau de destination OBLIGATOIRE) ou 5 (avec orientation socle par-fig).
    # L'orientation None = orientation inchangée ; le niveau, lui, n'est JAMAIS inventé (frontière).
    plan = parse_model_plan_with_orientation(raw_plan, action_name="commit_move_plan")

    squad_models = require_key(game_state, "squad_models")
    models_cache = require_key(game_state, "models_cache")
    alive = {m for m in squad_models.get(str(squad_id), []) if m in models_cache}  # get allowed
    plan_ids = {mid for mid, *_ in plan}  # get allowed
    if plan_ids != alive:
        return False, {
            "error": "plan_models_mismatch",
            "unitId": squad_id,
            "expected": sorted(alive),
            "got": sorted(plan_ids),
        }

    # Validation = MEME regle que le voile rouge du preview (placement par-fig +
    # cohesion par composantes connexes). Coherent avec ce que l'UI affiche.
    preview = movement_preview_move_plan(game_state, str(squad_id), plan)
    if not preview["can_validate"]:
        return False, {
            "error": "invalid_move_plan",
            "unitId": squad_id,
            "per_model": preview["per_model"],
            "coherency_ok": preview["coherency_ok"],
        }

    # Desperate Escape (09.07) : le hazard est désormais résolu à l'ACTIVATION (action
    # hazard_confirm), plus au commit. Ici on commit un Fall Back déjà autorisé.
    was_engaged = _squad_is_in_enemy_er(game_state, str(squad_id))

    _adv_roll = _advance_roll_for(str(squad_id), game_state)
    if _adv_roll is not None and not was_engaged:
        move_type = "advance"
    else:
        # Si un ennemi a réagi après la déclaration d'avance (mouvement réactif), l'unité
        # est désormais engagée au moment du commit : l'avance est invalide, on commit en
        # fall_back pour respecter 09.03 et éviter "ADVANCED from adjacent hex" dans l'analyzer.
        move_type = "fall_back" if was_engaged else "normal"

    # Snapshot par-figurine + ancre AVANT le commit, pour le log de mouvement
    # (moveDetails : depart -> arrivee de chaque figurine, expand/collapse cote GameLog).
    _uc_before = game_state.get("units_cache", {}).get(str(squad_id))  # get allowed
    if _uc_before is None:  # get allowed
        raise KeyError(f"units_cache missing squad {squad_id} before move commit")
    orig_anchor_col = int(_uc_before["col"])
    orig_anchor_row = int(_uc_before["row"])
    models_before = {
        mid: (int(models_cache[mid]["col"]), int(models_cache[mid]["row"]))
        for mid in alive
    }

    # Le niveau EFFECTIF (13.06) est désormais résolu par `commit_move` lui-même, pour TOUS ses
    # appelants (move, charge, pile-in, consolidation, gym) et non plus par pré-résolution du plan
    # ici : c'est le même invariant, mais tenu par construction au lieu de la discipline de chacun.
    commit_move(plan, game_state, move_type)

    unit = require_unit_by_id(game_state, squad_id)
    # Sync ancre de la liste units sur l'ancre recalculee dans units_cache
    # (commit_move ne touche que models_cache/units_cache).
    entry = game_state.get("units_cache", {}).get(str(squad_id))  # get allowed
    if entry is not None:  # get allowed
        set_unit_coordinates(unit, int(entry["col"]), int(entry["row"]))
        # Sync niveau de l'ancre (étages) vers la liste units (API), miroir de la sync col/row.
        unit["level"] = int(require_key(entry, "level"))

    # Log de mouvement par-figurine (modele de la charge, sans roll sauf advance).
    # Ligne unite = message ancre ; detail expand/collapse = moveDetails par figurine.
    dest_anchor_col, dest_anchor_row = require_unit_position(unit, game_state)
    move_details = []
    for mid, nc, nr, _lv, _ori in plan:
        _fc, _fr = models_before[mid]
        move_details.append(
            {
                "modelId": mid,
                "fromCol": _fc,
                "fromRow": _fr,
                "toCol": int(nc),
                "toRow": int(nr),
            }
        )
    _ut_seg = f" {unit['unitType']}" if unit.get("unitType") else ""
    # 21.03 « take to the skies » : la traversée (murs, figurines, terrain) est DÉCLARÉE, pas
    # acquise par le keyword FLY. Le pipeline squad — le chemin de production — ne transmettait
    # pas ce drapeau, alors que le chemin mono le faisait : aucun `[FLY]` n'apparaissait dans
    # step.log, et l'analyzer pathfindait les escouades volantes comme de l'infanterie
    # (faux « move path blocked » sur un vol par-dessus un mur).
    _is_fly_move = _fly_traversal_active(game_state, unit, str(unit["id"]))
    _fly_seg = " [FLY]" if _is_fly_move else ""
    if move_type == "advance":
        action_name = "ADVANCED"
        was_flee = False
        movement_message = (
            f"Unit {unit['id']}{_ut_seg} ADVANCED{_fly_seg} from ({orig_anchor_col},{orig_anchor_row}) "
            f"to ({dest_anchor_col},{dest_anchor_row}) [Advance:{_adv_roll}]"
        )
    elif move_type == "fall_back":
        action_name = "FLED"
        was_flee = True
        movement_message = (
            f"Unit {unit['id']}{_ut_seg} FLED{_fly_seg} from ({orig_anchor_col},{orig_anchor_row}) "
            f"to ({dest_anchor_col},{dest_anchor_row})"
        )
    else:
        action_name = "MOVE"
        was_flee = False
        movement_message = (
            f"Unit {unit['id']}{_ut_seg} MOVED{_fly_seg} from ({orig_anchor_col},{orig_anchor_row}) "
            f"to ({dest_anchor_col},{dest_anchor_row})"
        )
    append_action_log(
        game_state,
        {
            "type": "move",
            "message": movement_message,
            "turn": require_key(game_state, "turn"),
            "phase": "move",
            "unitId": unit["id"],
            "player": unit["player"],
            "fromCol": orig_anchor_col,
            "fromRow": orig_anchor_row,
            "toCol": dest_anchor_col,
            "toRow": dest_anchor_row,
            "was_flee": was_flee,
            "timestamp": "server_time",
            "action_name": action_name,
            "reward": 0.0,
            "is_ai_action": unit["player"] == 2,
            "is_fly_move": _is_fly_move,
            "moveDetails": move_details,
        },
    )

    _invalidate_all_destination_pools_after_movement(game_state)
    movement_clear_preview(game_state)

    # Source unique du marquage de fuite (partagée avec le move rigide à l'ancre) :
    # marque units_fled + libellé "flee" si l'escouade était engagée avant le commit.
    flee_action = finalize_flee_marking(game_state, str(squad_id), was_engaged)

    result = end_activation(game_state, unit, ACTION, 1, MOVE, MOVE, 1)
    result.update(
        {
            "action": flee_action,
            "unitId": unit["id"],
            "activation_complete": True,
            "waiting_for_player": False,
            "reset_mode": "select",
            "clear_selected_unit": True,
        }
    )

    if game_state.get("sandbox_free_move"):
        pool = game_state.setdefault("move_activation_pool", [])
        squad_id_str = str(squad_id)
        if squad_id_str not in pool:
            pool.append(squad_id_str)
        game_state.setdefault("units_moved", set()).discard(squad_id_str)
        game_state.setdefault("units_fled", set()).discard(squad_id_str)
        game_state.setdefault("units_advanced", set()).discard(squad_id_str)
        game_state.setdefault("advance_rolls", {}).pop(squad_id_str, None)
        result["action"] = "move"
        game_state["unit_activation_count"] = max(0, game_state.get("unit_activation_count", 0) - 1)

    return True, result


def movement_preview(valid_destinations: List[Tuple[int, int]]) -> Dict[str, Any]:
    """AI_MOVE.md: Generate preview data for green hexes"""
    return {
        "green_hexes": valid_destinations,
        "show_preview": True
    }


def movement_clear_preview(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """AI_MOVE.md: Clear movement preview"""
    game_state["preview_hexes"] = []
    game_state["valid_move_destinations_pool"] = []
    game_state["move_preview_footprint_zone"] = set()
    game_state["move_preview_border"] = []
    game_state["move_preview_footprint_mask_loops"] = None
    game_state["move_preview_footprint_span"] = None
    game_state["active_movement_unit"] = None
    return {
        "show_preview": False,
        "clear_hexes": True
    }


def _handle_movement_postpone(
    game_state: Dict[str, Any], unit: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """
    Quitter la sélection de destination (preview + active_movement_unit) sans retirer l'unité du
    ``move_activation_pool`` — aligné sur le report tir (``postpone`` / ``activation_ended: false``).
    """
    am = game_state.get("active_movement_unit")
    if am is None or am == "":
        return True, {"action": "no_effect", "activation_ended": False}
    if str(unit["id"]) != str(am):
        return False, {
            "error": "postpone_movement_wrong_unit",
            "expected_active_movement_unit": am,
            "unitId": unit["id"],
        }
    movement_clear_preview(game_state)
    return True, {
        "action": "postpone",
        "unitId": unit["id"],
        "activation_ended": False,
        "reset_mode": "select",
        "clear_selected_unit": True,
    }


def movement_click_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """AI_MOVE.md: Route click actions"""
    if "clickTarget" not in action:
        click_target = "elsewhere"  # Default behavior for missing field
    else:
        click_target = action["clickTarget"]
    
    if click_target == "destination_hex":
        return movement_destination_selection_handler(game_state, unit_id, action)
    elif click_target == "friendly_unit":
        return False, {"error": "unit_switch_not_implemented"}
    elif click_target == "active_unit":
        unit_click = require_unit_by_id(game_state, unit_id)
        return _handle_movement_postpone(game_state, unit_click)
    else:
        # Clic ailleurs : report uniquement si une activation move attend une destination
        if game_state.get("active_movement_unit") is None:
            return True, {"action": "continue_selection"}
        unit_click = require_unit_by_id(game_state, unit_id)
        return _handle_movement_postpone(game_state, unit_click)

def movement_destination_selection_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """AI_MOVE.md: Handle destination selection and execute movement"""
    # Direct field access with validation
    if "destCol" not in action:
        raise KeyError(f"Action missing required 'destCol' field: {action}")
    if "destRow" not in action:
        raise KeyError(f"Action missing required 'destRow' field: {action}")
    dest_col = action["destCol"]
    dest_row = action["destRow"]

    if dest_col is None or dest_row is None:
        return False, {"error": "missing_destination"}

    # Normalize coordinates to int - raises error if invalid
    dest_col, dest_row = normalize_coordinates(dest_col, dest_row)
    orientation = None
    if "orientation" in action:
        orientation = _validate_move_orientation(action["orientation"])

    # Pool is already built during activation - no need to rebuild here
    # System is sequential, so pool is still valid
    if "valid_move_destinations_pool" not in game_state:
        raise KeyError("game_state missing required 'valid_move_destinations_pool' field")
    valid_pool = game_state["valid_move_destinations_pool"]

    # Validate destination in valid pool
    if (dest_col, dest_row) not in valid_pool:
        # Destination not reachable via BFS pathfinding
        _log_movement_debug(game_state, "destination_selection", str(unit_id), f"destination ({dest_col},{dest_row}) NOT_IN_POOL pool_size={len(valid_pool)}")
        return False, {"error": "invalid_destination", "destination": (dest_col, dest_row)}

    unit = require_unit_by_id(game_state, unit_id)
    # Desperate Escape (09.07) : le hazard roll (06.03) est désormais résolu à l'ACTIVATION
    # (action hazard_confirm), AVANT le preview — plus ici au commit. Ce chemin commit un
    # Fall Back déjà autorisé.

    # Destination validation is already done in movement_build_valid_destinations_pool()
    # (BFS + zone ennemie euclidienne bord à bord sur plateau ×10). Le pool doit rester
    # aligné avec _attempt_movement_to_destination (revalidation stricte au commit).

    # Use _attempt_movement_to_destination() to validate occupation
    # This function checks if destination is occupied, validates enemy adjacency, etc.
    config = {}  # Empty config for now
    import time as _mds_t
    from engine.perf_timing import append_perf_timing_line as _mds_log, perf_timing_enabled as _mds_pte
    _mds_pt = _mds_pte(game_state)
    _mds_t0 = _mds_t.perf_counter() if _mds_pt else None
    move_success, move_result = _attempt_movement_to_destination(
        game_state,
        unit,
        dest_col,
        dest_row,
        config,
        orientation=orientation,
    )
    _mds_t1 = _mds_t.perf_counter() if _mds_pt else None

    if not move_success:
        # Move was blocked (occupied hex, adjacent to enemy, etc.)
        error_type = move_result.get('error', 'unknown')
        _log_movement_debug(game_state, "destination_selection", str(unit_id), f"destination ({dest_col},{dest_row}) BLOCKED error={error_type}")
        
        # If destination is invalid (adjacent to enemy or occupied), remove it from pool
        # to prevent infinite loops where agent keeps trying invalid destinations
        if error_type in ("destination_adjacent_to_enemy", "destination_occupied") and "valid_move_destinations_pool" in game_state:
            invalid_dest = (dest_col, dest_row)
            if invalid_dest in game_state["valid_move_destinations_pool"]:
                game_state["valid_move_destinations_pool"].remove(invalid_dest)
                # Also update pending_movement_destinations if it exists
                if "pending_movement_destinations" in game_state and invalid_dest in game_state["pending_movement_destinations"]:
                    game_state["pending_movement_destinations"].remove(invalid_dest)

                # If pool is now empty, force skip this unit to prevent infinite loop
                if not game_state["valid_move_destinations_pool"]:
                    _log_movement_debug(game_state, "destination_selection", str(unit_id), "ALL destinations invalid - forcing skip to prevent infinite loop")
                    return _handle_skip_action(game_state, unit, had_valid_destinations=False)
        
        return False, move_result

    # V11 : Advance déjà marqué dans units_advanced au clic (movement_set_advance_mode_handler) ;
    # il persiste tout le tour, rien à faire ici (ce chemin ne passe pas par commit_move).

    # Extract movement info from result
    # Log successful destination selection
    _log_movement_debug(game_state, "destination_selection", str(unit_id), f"destination ({dest_col},{dest_row}) SELECTED")
    was_adjacent = (move_result.get("action") == "flee")
    # Use fromCol/fromRow from move_result (set by _attempt_movement_to_destination before movement)
    # These are the original coordinates BEFORE the movement
    orig_col = move_result.get("fromCol")
    orig_row = move_result.get("fromRow")
    if orig_col is None or orig_row is None:
        raise ValueError(f"move_result missing fromCol/fromRow: move_result keys={list(move_result.keys())}")

    # Position has already been updated by _attempt_movement_to_destination()
    # Validate it actually changed
    unit_col, unit_row = require_unit_position(unit, game_state)
    if unit_col != dest_col or unit_row != dest_row:
        return False, {"error": "position_update_failed"}

    # Reset level=0 des figs du squad (move rigide au sol) : désormais fait AVANT la translation
    # dans _attempt_movement_to_destination (sinon floor_height_at crashait sur une fig encore
    # marquée à l'étage mais déplacée hors empreinte). Rien à refaire ici.

    # DEBUG: Log exact values before using unit coordinates
    from engine.game_utils import add_console_log, safe_print
    episode = game_state.get('episode_number', '?')
    turn = game_state.get('turn', '?')
    debug_msg = f"[MOVEMENT DEBUG] E{episode} T{turn} Unit {unit_id}: dest_col={dest_col} dest_row={dest_row} unit_col={unit['col']} unit_row={unit['row']} move_result_toCol={move_result.get('toCol')} move_result_toRow={move_result.get('toRow')}"
    add_console_log(game_state, debug_msg)
    safe_print(game_state, debug_msg)
    
    # Invalidate all destination pools after movement
    # Positions have changed, so all pools (move, charge, shoot) are now stale
    _invalidate_all_destination_pools_after_movement(game_state)
    _mds_t2 = _mds_t.perf_counter() if _mds_pt else None

    move_kind = "flee" if was_adjacent else "move"
    reactive_result = maybe_resolve_reactive_move(
        game_state=game_state,
        moved_unit_id=str(unit["id"]),
        from_col=orig_col,
        from_row=orig_row,
        to_col=dest_col,
        to_row=dest_row,
        move_kind=move_kind,
        move_cause="normal",
    )
    _mds_t3 = _mds_t.perf_counter() if _mds_pt else None
    if _mds_pt and _mds_t0 is not None and _mds_t1 is not None and _mds_t2 is not None and _mds_t3 is not None:
        _mds_log(
            f"MOVE_DEST_TIMING episode={episode} turn={turn} unitId={unit_id!r} "
            f"attempt_s={_mds_t1 - _mds_t0:.6f} pool_invalidate_s={_mds_t2 - _mds_t1:.6f} "
            f"reactive_s={_mds_t3 - _mds_t2:.6f} total_s={_mds_t3 - _mds_t0:.6f}"
        )

    # Generate movement log per requested format
    if "action_logs" not in game_state:
        game_state["action_logs"] = []
    
    # Calculate reward for this action (movement rewards are disabled)
    action_reward = 0.0
    action_name = "FLEE" if was_adjacent else "MOVE"
    
    is_fly_move = _fly_traversal_active(game_state, unit, unit_id)
    _ut_seg = f" {unit['unitType']}" if unit.get("unitType") else ""
    if was_adjacent:
        if is_fly_move:
            movement_message = (
                f"Unit {unit['id']}{_ut_seg} FLED [FLY] from ({orig_col},{orig_row}) to ({dest_col},{dest_row})"
            )
        else:
            movement_message = (
                f"Unit {unit['id']}{_ut_seg} FLED from ({orig_col},{orig_row}) to ({dest_col},{dest_row})"
            )
    else:
        movement_message = (
            f"Unit {unit['id']}{_ut_seg} MOVED [FLY] from ({orig_col},{orig_row}) to ({dest_col},{dest_row})"
            if is_fly_move
            else f"Unit {unit['id']}{_ut_seg} MOVED from ({orig_col},{orig_row}) to ({dest_col},{dest_row})"
        )

    append_action_log(
        game_state,
        {
        "type": "move",
        "message": movement_message,
        "turn": require_key(game_state, "turn"),
        "phase": "move",
        "unitId": unit["id"],
        "player": unit["player"],
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col,
        "toRow": dest_row,
        "was_flee": was_adjacent,
        "timestamp": "server_time",
        "action_name": action_name,  # NEW: For debug display
        "reward": round(action_reward, 2),  # NEW: Calculated reward
        "is_ai_action": unit["player"] == 2,  # FIXED: PvE AI is player 2 (was P0/P1, now P1/P2)
        "is_fly_move": is_fly_move,
        },
    )

    # Clear preview
    movement_clear_preview(game_state)

    # End activation with position data for reward calculation
    # tour_de_jeu.md EXACT: end_activation(Arg1, Arg2, Arg3, Arg4, Arg5)
    action_type = FLED if was_adjacent else MOVE
    result = end_activation(
        game_state, unit,
        ACTION,      # Arg1: Log the action (movement already logged)
        1,             # Arg2: +1 step increment
        action_type,   # Arg3: MOVE or FLED tracking
        MOVE,        # Arg4: Remove from move_activation_pool
        1              # Arg5: No error logging
    )

    # Add position data for reward calculation
    # Detect same-position moves (unit didn't actually move)
    actually_moved = (orig_col != dest_col) or (orig_row != dest_row)
    
    if not actually_moved:
        # Unit stayed in same position - treat as wait, not move
        action_name = "wait"
    elif was_adjacent:
        action_name = "flee"
    else:
        action_name = "move"
    
    # Use unit coordinates AFTER movement - SINGLE SOURCE OF TRUTH
    # NOT move_result.get("toCol")/toRow which comes from action["destCol"]/destRow
    # NOT action["destCol"]/destRow which might be incorrect
    # The unit's position is the ONLY reliable source after movement execution
    result_to_col, result_to_row = require_unit_position(unit, game_state)
    
    # DEBUG: Log exact values being used for result
    from engine.game_utils import add_console_log, safe_print
    episode = game_state.get('episode_number', '?')
    turn = game_state.get('turn', '?')
    debug_msg = f"[MOVEMENT DEBUG] E{episode} T{turn} Unit {unit_id}: Using result_to_col={result_to_col} result_to_row={result_to_row} (unit_col={unit['col']} unit_row={unit['row']} move_result_toCol={move_result.get('toCol')} move_result_toRow={move_result.get('toRow')}) for logging"
    add_console_log(game_state, debug_msg)
    safe_print(game_state, debug_msg)
    
    result.update({
        "action": action_name,
        "unitId": unit["id"],
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": result_to_col,  # Use unit coordinates after movement - SINGLE SOURCE OF TRUTH
        "toRow": result_to_row,  # Use unit coordinates after movement - SINGLE SOURCE OF TRUTH
        "reactive_moves_applied": reactive_result["reactive_moves_applied"],
        "reactive_moves_declined": reactive_result["reactive_moves_declined"],
        "is_fly_move": is_fly_move,
        "activation_complete": True,
        "waiting_for_player": False,  # Movement is complete, no waiting needed
        "reset_mode": "select",
        "clear_selected_unit": True
    })
    
    return True, result


def _handle_skip_action(game_state: Dict[str, Any], unit: Dict[str, Any], had_valid_destinations: bool = True) -> Tuple[bool, Dict[str, Any]]:
    """AI_MOVE.md: Handle skip (no valid dests) or wait (agent chooses to pass).

    had_valid_destinations: True = agent chose to pass (wait). False = no valid destinations (skip).
    """
    # REMOVED: Duplicate logging - tour_de_jeu.md end_activation handles ALL logging
    # tour_de_jeu.md PRINCIPLE: end_activation is SINGLE SOURCE for action logging

    movement_clear_preview(game_state)

    if had_valid_destinations:
        # tour_de_jeu.md EXACT: end_activation(WAIT, 1, PASS, MOVE, 1, 1)
        result = end_activation(
            game_state, unit,
            WAIT,        # Arg1: Log wait action (SINGLE SOURCE)
            1,             # Arg2: +1 step increment
            PASS,        # Arg3: PASS tracking (not MOVE)
            MOVE,        # Arg4: Remove from move_activation_pool
            1              # Arg5: Error logging enabled
        )
        result.update({
            "action": "wait",  # Agent chose to pass
            "unitId": unit["id"],
            "activation_complete": True,
            "reset_mode": "select",
            "clear_selected_unit": True
        })
    else:
        # tour_de_jeu.md EXACT: end_activation(NO, 0, PASS, MOVE, 1, 1) - no step (unit could not act)
        result = end_activation(
            game_state, unit,
            NO,         # Arg1: NO (no action taken)
            0,            # Arg2: No step increment
            PASS,       # Arg3: PASS tracking
            MOVE,       # Arg4: Remove from move_activation_pool
            1             # Arg5: Error logging enabled
        )
        result.update({
            "action": "skip",
            "skip_reason": "no_valid_move_destinations",
            "unitId": unit["id"],
            "activation_complete": True,
            "reset_mode": "select",
            "clear_selected_unit": True
        })
        # L24 — producteur skip : le formateur existait déjà dans StepLogger, mais aucune entrée
        # n'était poussée dans action_logs, donc la ligne n'atteignait jamais step.log.
        unit_col, unit_row = require_unit_position(unit, game_state)
        append_action_log(
            game_state,
            {
                "type": "skip",
                "turn": game_state["turn"],
                "phase": game_state["phase"],
                "unitId": unit["id"],
                "player": require_key(unit, "player"),
                "col": unit_col,
                "row": unit_row,
                "skipReason": "no_valid_move_destinations",
            },
        )

    return True, result


# ============================================================================
# RÉSERVES STRATÉGIQUES — INGRESS MOVE (20.03 / 20.04) ET DEEP STRIKE (24.09)
# ============================================================================
# L'ingress move est une MISE EN PLACE (« EFFECT: Your unit is set up as described in Set Up
# (03.02) »), pas un déplacement : il n'a ni origine, ni chemin, ni budget. Il ne passe donc PAS
# par `movement_build_valid_destinations_pool` (BFS géodésique depuis une position que l'unité
# n'a pas) mais par la MÊME chaîne de placement que le déploiement — formation compacte, preview
# par-figurine, commit — à laquelle on substitue l'aire légale (`pool_override`). Tout le reste
# de la validité de placement (bornes, murs, empreintes des autres unités, cohésion 03.03,
# étages 13.06) est donc partagé, jamais réimplémenté.

# ── Les trois grandeurs de 20.03/20.04 sont des PARAMÈTRES PAR UNITÉ ────────────────────────
# Le texte des trois clauses commence par « Unless otherwise stated » ou est explicitement
# remplacé par des capacités : le round d'arrivée (Logan Grimnar fait arriver une unité au 1er
# round), la distance au bord (« wholly within 9" of a battlefield edge » chez certaines) et la
# distance aux ennemis (Da Jump pose « more than 9" away »). Les valeurs ci-dessous ne sont donc
# que les DÉFAUTS de la règle générique ; l'unité porte les siennes, qu'une autre unité peut lui
# accorder (`set_reserves_arrival_round` / `set_reserves_setup_distances`).

#: 20.04 « SET-UP DISTANCE: 6" » — bande le long des bords de plateau. `None` sur une unité =
#: aucune contrainte de bord, « anywhere on the battlefield » (Deep Strike 24.09, Da Jump).
INGRESS_SETUP_DISTANCE_INCHES = 6
#: 20.04 « more than 8" horizontally from all enemy units ». STRICTEMENT plus de 8" : une
#: destination à 8" pile est REFUSÉE.
INGRESS_ENEMY_CLEARANCE_INCHES = 8
#: 20.03 « Unless otherwise stated, they can only do so from the second battle round onwards. »
INGRESS_FIRST_BATTLE_ROUND = 2
#: 20.04 « Before the Third Battle Round: no models can be set up within your opponent's
#: deployment zone. » -> à partir du 3e round, la zone adverse est ouverte. La clause tombe aussi
#: pour toute unité posée « anywhere on the battlefield » (distance de bord nulle) : c'est la
#: même phrase qui lève les deux (« even if that is within your opponent's deployment zone »).
INGRESS_OPPONENT_ZONE_OPEN_ROUND = 3
#: 20.04 « At the end of the third battle round … are destroyed ».
STRATEGIC_RESERVES_LAST_ROUND = 3
#: Identifiant de la capacité Deep Strike (24.09) dans `config/unit_rules.json`.
DEEP_STRIKE_RULE_ID = "deep_strike"

#: Champs d'unité portant les trois paramètres. Posés par les DEUX constructeurs d'unité
#: (`create_unit`, `_build_enhanced_unit`) ; absents d'une fixture moteur nu, auquel cas les
#: défauts de la règle générique s'appliquent (cf. `_reserves_param`).
RESERVES_ARRIVAL_ROUND_FIELD = "reserves_arrival_round"
RESERVES_EDGE_DISTANCE_FIELD = "reserves_edge_distance_inches"
RESERVES_ENEMY_CLEARANCE_FIELD = "reserves_enemy_clearance_inches"


def _reserves_param(unit: Dict[str, Any], field: str, default: Any) -> Any:
    """Valeur d'un paramètre de réserve porté par l'unité, ou le défaut de la règle générique.

    `get` et non `require_key` : une unité construite hors des chargeurs (fixture moteur nu,
    test de géométrie) ne porte pas ces champs, et la règle générique EST sa valeur. Ce n'est pas
    un repli masquant une erreur — les deux constructeurs réels les posent toujours
    (`_default_reserves_parameters`, game_state.py).
    """
    return unit.get(field, default)


def set_reserves_arrival_round(
    game_state: Dict[str, Any], unit_id: str, battle_round: int
) -> None:
    """20.03 « unless otherwise stated » — impose à CETTE unité son round d'arrivée.

    Point d'entrée des capacités qui font arriver une unité plus tôt (Logan Grimnar : une unité,
    au 1er round, une fois par partie). Le « une fois par partie » appartient à l'unité qui
    ACCORDE, pas à celle qui reçoit : ce site ne compte rien.
    """
    unit = get_unit_by_id(game_state, str(unit_id))
    if unit is None:
        raise KeyError(f"set_reserves_arrival_round: unité {unit_id} introuvable")
    battle_round = int(battle_round)
    if battle_round < 1:
        raise ValueError(
            f"set_reserves_arrival_round: round {battle_round} invalide — le premier round de "
            f"bataille est 1"
        )
    unit[RESERVES_ARRIVAL_ROUND_FIELD] = battle_round


def set_reserves_setup_distances(
    game_state: Dict[str, Any],
    unit_id: str,
    *,
    edge_distance_inches: Optional[int],
    enemy_clearance_inches: int,
) -> None:
    """20.04 — impose à CETTE unité ses deux distances de mise en place.

    ``edge_distance_inches`` : bande de bord en pouces, ou ``None`` pour « anywhere on the
    battlefield » (ce que disent Deep Strike 24.09 et Da Jump). ``enemy_clearance_inches`` : la
    distance dont l'unité doit être à PLUS (8" par défaut, 9" pour Da Jump).
    """
    unit = get_unit_by_id(game_state, str(unit_id))
    if unit is None:
        raise KeyError(f"set_reserves_setup_distances: unité {unit_id} introuvable")
    if edge_distance_inches is not None:
        edge_distance_inches = int(edge_distance_inches)
        if edge_distance_inches < 0:
            raise ValueError(
                f"set_reserves_setup_distances: distance de bord négative "
                f"({edge_distance_inches})"
            )
    enemy_clearance_inches = int(enemy_clearance_inches)
    if enemy_clearance_inches < 0:
        raise ValueError(
            f"set_reserves_setup_distances: distance aux ennemis négative "
            f"({enemy_clearance_inches})"
        )
    unit[RESERVES_EDGE_DISTANCE_FIELD] = edge_distance_inches
    unit[RESERVES_ENEMY_CLEARANCE_FIELD] = enemy_clearance_inches


def ingress_pool_signature(game_state: Dict[str, Any], squad_id: str) -> Tuple[Any, int, bool]:
    """Ce dont le pool d'ingress dépend, POUR CETTE UNITÉ : ``(bande de bord, clearance, zone
    adverse ouverte)``.

    Le pool ne dépend PAS de l'unité au-delà de ce triplet : la case candidate y est traitée
    comme un point, le socle réel n'intervenant qu'à la pose (voile par-figurine). Deux unités
    de même signature partagent donc EXACTEMENT le même pool — c'est ce qui permet de ne le
    calculer qu'une fois par phase pour toutes les réserves d'un joueur.

    ``bande de bord`` à ``None`` = « anywhere on the battlefield ».
    """
    unit = get_unit_by_id(game_state, str(squad_id))
    if unit is None:
        raise KeyError(f"ingress_pool_signature: unité {squad_id} introuvable")
    edge = _reserves_param(unit, RESERVES_EDGE_DISTANCE_FIELD, INGRESS_SETUP_DISTANCE_INCHES)
    # 24.09 : la capacité LÈVE la contrainte de bord (« anywhere on the battlefield »). Elle
    # s'ajoute au paramètre porté par l'unité au lieu de le remplacer — une unité qui a Deep
    # Strike ET une bande accordée par une autre règle est posée n'importe où, jamais dans la
    # plus restrictive des deux.
    if unit_has_deep_strike(game_state, str(squad_id)):
        edge = None
    clearance = int(
        _reserves_param(unit, RESERVES_ENEMY_CLEARANCE_FIELD, INGRESS_ENEMY_CLEARANCE_INCHES)
    )
    # Zone adverse : fermée avant le 3e round, SAUF pour une unité posée n'importe où — c'est la
    # même phrase de 24.09 qui lève les deux clauses.
    opponent_zone_open = (
        edge is None
        or int(require_key(game_state, "turn")) >= INGRESS_OPPONENT_ZONE_OPEN_ROUND
    )
    return (edge, clearance, opponent_zone_open)


def unit_has_deep_strike(game_state: Dict[str, Any], squad_id: str) -> bool:
    """24.09 — « if EVERY MODEL in this unit has this ability ».

    Test PAR FIGURINE VIVANTE sur les règles PROPRES de chaque figurine
    (`models_cache[mid]["UNIT_RULES"]`, jumeau du test par-figurine de 06.03 sur les keywords),
    et surtout PAS sur `unit["UNIT_RULES"]` : celui-ci est l'UNION en vigueur (19.04), dans
    laquelle un seul porteur suffirait à accorder la capacité à toute l'escouade. Une escouade
    Deep Strike menée par un character qui ne l'a pas PERD donc Deep Strike, ce qui est
    exactement ce que dit la règle.

    Une escouade sans figurine vivante n'a pas la capacité (et n'a rien à poser).
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive = [models_cache[mid] for mid in squad_models.get(str(squad_id), []) if mid in models_cache]  # get allowed
    if not alive:
        return False
    for model in alive:
        rule_ids = {
            str(require_key(rule, "ruleId")) for rule in require_key(model, "UNIT_RULES")
        }
        if DEEP_STRIKE_RULE_ID not in rule_ids:
            return False
    return True


def _ingress_edge_band_cells(
    board_cols: int, board_rows: int, distance_subhex: int
) -> "np.ndarray":
    """Masque ``(board_cols, board_rows)`` des cases à ``distance_subhex`` ou moins d'un BORD.

    Les indices de colonne/ligne du plateau SONT des sous-hexes sur les deux axes (un board
    « 44x60 » à `inches_to_subhex=5` fait 220x300 cases) : la distance à un bord se lit donc
    directement en indices, sans conversion supplémentaire.
    """
    band = np.zeros((board_cols, board_rows), dtype=bool)
    if distance_subhex < 0:
        raise ValueError(f"_ingress_edge_band_cells: distance négative ({distance_subhex})")
    cols = np.arange(board_cols, dtype=np.int64)[:, None]
    rows = np.arange(board_rows, dtype=np.int64)[None, :]
    dist_to_edge = np.minimum(
        np.minimum(cols, board_cols - 1 - cols),
        np.minimum(rows, board_rows - 1 - rows),
    )
    band |= dist_to_edge <= distance_subhex
    return band


def _ingress_enemy_entries(
    game_state: Dict[str, Any], player: int
) -> List[Dict[str, Any]]:
    """Entrées-cache des unités ENNEMIES de ``player`` présentes sur le champ de bataille.

    Une unité hors table (réserves 20.01, attente de déploiement) n'impose aucune distance :
    elle n'a ni position ni empreinte. Ce filtre est le même pour les trois consommateurs — les
    deux métriques du masque de clearance et l'empreinte de mémoïsation — qui l'écrivaient
    chacun de leur côté.
    """
    from engine.phase_handlers.shared_utils import entry_is_on_battlefield

    return [
        entry
        for entry in require_key(game_state, "units_cache").values()
        if int(require_key(entry, "player")) != int(player) and entry_is_on_battlefield(entry)
    ]


def _ingress_enemy_model_positions(entry: Dict[str, Any]) -> List[Tuple[int, int]]:
    """Positions PAR FIGURINE d'une entrée-cache (ancre seule pour une unité mono-figurine)."""
    by_model = entry.get("occupied_hexes_by_model")  # get allowed (mono-fig -> ancre)
    if by_model:
        return [(int(c), int(r)) for c, r in by_model.values()]
    return [(int(require_key(entry, "col")), int(require_key(entry, "row")))]


def _ingress_enemy_clearance_forbidden_hex(
    game_state: Dict[str, Any], player: int, clearance_subhex: int,
    board_cols: int, board_rows: int,
) -> "np.ndarray":
    """Volet MÉTRIQUE HEX de `_ingress_enemy_clearance_forbidden` (cf. sa docstring).

    ``min_distance_between_sets({case}, empreinte_ennemie) <= clearance`` pour toute case, soit
    la dilatation hex des empreintes ennemies par le rayon de clearance — c'est exactement le
    contrat de ``dilate_hex_set`` (dont la docstring établit l'équivalence avec
    ``min_distance_between_sets``), à ceci près qu'elle EXCLUT la distance 0 : d'où l'union avec
    les cases sources.
    """
    from engine.hex_utils import dilate_hex_set

    forbidden = np.zeros((board_cols, board_rows), dtype=bool)
    sources: Set[Tuple[int, int]] = set()
    for entry in _ingress_enemy_entries(game_state, player):
        sources.update(
            (int(c), int(r)) for c, r in require_key(entry, "occupied_hexes")
        )
    if not sources:
        return forbidden
    for c, r in sources | dilate_hex_set(sources, int(clearance_subhex), board_cols, board_rows):
        if 0 <= c < board_cols and 0 <= r < board_rows:
            forbidden[c, r] = True
    return forbidden


def _ingress_enemy_clearance_forbidden(
    game_state: Dict[str, Any], player: int, clearance_subhex: int,
    board_cols: int, board_rows: int,
) -> "np.ndarray":
    """Masque des cases interdites par « more than 8" horizontally from all enemy units » (20.04).

    ``forbidden[c, r]`` ⇔ une figurine posée en ``(c, r)`` serait à 8" OU MOINS, bord à bord et
    HORIZONTALEMENT, d'au moins une unité ennemie présente sur le plateau. La règle exige
    STRICTEMENT plus de 8" : l'égalité est donc interdite, comme pour la zone d'engagement
    (``<= ez``) dont ceci est le jumeau à une autre distance.

    MÊME MÉTRIQUE que le reste du moteur (``engagement_distance_metric``) :
      - ``hex`` : distance d'empreinte à empreinte en cases (``min_distance_between_sets``), la
        case candidate valant une empreinte d'une case ;
      - ``euclidean`` : distance du CENTRE de la case au BORD du socle ennemi (rayon inclus pour
        un socle rond, cases d'empreinte sinon).
    C'est la sémantique de `entries_in_engagement_zone` — la primitive canonique — pour une
    figurine réduite à sa case ; ce masque en est le miroir vectorisé, verrouillé par test
    d'équivalence. Le verdict est HORIZONTAL par construction (aucun gate vertical), comme
    l'exige le texte de 20.04.

    L'aire interdite est appliquée CASE PAR CASE : le contrôle `empreinte ⊆ pool` de la mise en
    place (03.02) la propage ensuite à toutes les cases de chaque figurine, donc au socle entier.
    """
    from engine.hex_utils import engagement_minimum_clearance_norm, round_base_radius_norm
    from engine.spatial_relations import engagement_distance_metric

    forbidden = np.zeros((board_cols, board_rows), dtype=bool)
    clearance_norm = engagement_minimum_clearance_norm(clearance_subhex)
    if clearance_norm <= 0:
        return forbidden
    if engagement_distance_metric(game_state) == "hex":
        return _ingress_enemy_clearance_forbidden_hex(
            game_state, player, clearance_subhex, board_cols, board_rows
        )

    grid_x, grid_y = _hex_center_grids(board_cols, board_rows)

    def _stamp_into(dst: "np.ndarray", sc: int, sr: int, reach: float) -> Tuple[int, int, int, int]:
        """Tamponne un disque et rend la FENÊTRE touchée — les appelants la réutilisent au lieu
        de rebalayer le plateau entier."""
        return _stamp_disc_into(dst, grid_x, grid_y, sc, sr, reach, board_cols, board_rows)

    for entry in _ingress_enemy_entries(game_state, player):
        e_shape = require_key(entry, "BASE_SHAPE")
        e_bs = require_base_size(
            e_shape, require_key(entry, "BASE_SIZE"), f"units_cache enemy {entry!r}"
        )
        positions = _ingress_enemy_model_positions(entry)
        if e_shape == "round":
            # Paire ronde↔ronde : écart bord à bord = distance des centres MOINS les deux rayons
            # (`euclidean_edge_distance`). Le socle de la figurine candidate est celui d'UNE CASE
            # — même convention que la géométrie du moteur à cette résolution (`_scale_socle`
            # normalise un socle en `round`/1 quand une figurine tient dans une case). L'omettre
            # rendrait le masque plus LAXISTE que la primitive canonique d'une demi-case.
            reach = (
                clearance_norm
                + round_base_radius_norm(
                    require_scalar_base_size(e_shape, e_bs, "ingress clearance enemy")
                )
                + round_base_radius_norm(1)
            )
            for ec, er in positions:
                _stamp_into(forbidden, int(ec), int(er), reach)
        else:
            # Socle NON ROND (oval/carré) : `euclidean_edge_distance` ne mesure alors PAS de
            # centre de cellule à centre de cellule — elle mesure entre les CONTOURS géométriques
            # réels (`_socle_edge_primitives`). Une approximation par cellules laisserait donc
            # dans le pool des cases que la primitive canonique juge à 8" ou moins, et rien ne
            # les rattraperait à la pose. On fait ici exactement ce que fait la primitive, mais
            # seulement sur la BANDE utile : un disque conservateur (clearance + rayon englobant
            # + rayon d'une case) borne les candidates, puis chacune est tranchée exactement.
            from engine.hex_utils import Socle, bounding_radius_norm, euclidean_edge_distance

            e_orient = int(require_key(entry, "orientation"))
            cell_radius = round_base_radius_norm(1)
            gate = clearance_norm + bounding_radius_norm(e_shape, e_bs) + cell_radius
            for ec, er in positions:
                enemy_socle = Socle(
                    shape=e_shape, base_size=e_bs, col=int(ec), row=int(er),
                    fp=compute_candidate_footprint(
                        int(ec), int(er),
                        {"BASE_SHAPE": e_shape, "BASE_SIZE": e_bs, "orientation": e_orient},
                        game_state,
                    ),
                )
                near = np.zeros((board_cols, board_rows), dtype=bool)
                c0, c1, r0, r1 = _stamp_into(near, int(ec), int(er), gate)
                # Balayage borné à la FENÊTRE du disque de garde, pas au plateau : le test exact
                # ci-dessous est du Python (~15 µs l'appel), et `np.nonzero` sur les 66 000 cases
                # coûtait à lui seul 6x le scan local.
                for cc, rr in zip(*np.nonzero(near[c0:c1, r0:r1])):
                    cc, rr = c0 + int(cc), r0 + int(rr)
                    if forbidden[cc, rr]:
                        continue
                    candidate = Socle(shape="round", base_size=1, col=cc, row=rr, fp=None)
                    # Pas de `max_distance` ici, et ce n'est pas un oubli : le `gate` ci-dessus
                    # EST déjà ce minorant (clearance + rayon englobant ennemi + rayon d'une
                    # case), et il a servi à borner les candidates. L'élagage interne ne pourrait
                    # donc écarter aucune case que le tampon n'ait déjà exclue — le passer serait
                    # payer deux fois la même borne.
                    if euclidean_edge_distance(candidate, enemy_socle) <= clearance_norm:
                        forbidden[cc, rr] = True
    return forbidden


def _opponent_deployment_zone_cells(game_state: Dict[str, Any], player: int) -> Set[Tuple[int, int]]:
    """Cases de la zone de déploiement ADVERSE (20.04, clause « before the Third Battle Round »).

    Lue dans ``game_state["deployment_pools"]``, la MÊME collection que celle où le déploiement
    pose les unités. Son absence est une erreur explicite : un scénario qui déclare des réserves
    sans zones de déploiement rend la clause invérifiable, et l'ignorer autoriserait un placement
    illégal en silence.

    Les zones sont publiées par le reset QUEL QUE SOIT le mode de mise en place. Cette fonction
    lisait auparavant ``deployment_state``, qui n'existe qu'en mode `active` : en mode `fixed`,
    une unité en réserves 20.01 rendait la clause — et le reset entier — impossible à évaluer.
    """
    from engine.phase_handlers.deployment_handlers import _get_deployment_pool

    deployment_pools = game_state.get("deployment_pools")  # get allowed (scénario sans zones)
    if deployment_pools is None:
        raise KeyError(
            "ingress move (20.04) : aucune zone de déploiement ('deployment_pools') dans le "
            "game_state — la clause « aucune figurine dans la zone de déploiement adverse avant "
            "le 3e round » ne peut pas être vérifiée."
        )
    opponent = 2 if int(player) == 1 else 1
    # `_get_deployment_pool` porte déjà la convention de clé (int ou str) et son erreur
    # explicite : la recopier ici en aurait fait la 4e version dans le dépôt.
    return {(int(c), int(r)) for c, r in _get_deployment_pool(deployment_pools, opponent)}


#: Mémos d'ingress, PARTAGÉS entre toutes les unités de même signature (cf.
#: `ingress_pool_signature`). Vivent dans le game_state : ils sont propres à une partie.
INGRESS_POOL_CACHE_KEY = "_ingress_setup_pool_cache"
#: Contours (monde) du pool — c'est le poste COÛTEUX (0,99 s contre 0,04 s pour le pool).
INGRESS_LOOPS_CACHE_KEY = "_ingress_preview_loops_cache"
#: Masque des 8", indexé sur (joueur, distance, positions ennemies) : indépendant de la signature.
INGRESS_CLEARANCE_CACHE_KEY = "_ingress_clearance_mask_cache"
#: Borne du POOL et du MASQUE. Une partie ne traverse jamais des dizaines de configurations
#: ennemies entre deux invalidations ; au-delà on repart de zéro plutôt que de laisser le dict
#: enfler. Le mémo des CONTOURS ne l'emploie pas : vider en bloc un poste à 0,99 s l'entrée
#: coûterait plus que la mémoire épargnée (cf. `ingress_preview_loops`).
_INGRESS_POOL_CACHE_MAX = 8


def _ingress_enemy_positions_fingerprint(
    game_state: Dict[str, Any], player: int
) -> Tuple[Any, ...]:
    """Empreinte des positions ENNEMIES — la seule chose, hors signature, dont le pool dépend.

    Ni le plateau (statique) ni les positions AMIES n'entrent dans le pool : une escouade amie
    qui se déplace pendant ma phase de mouvement ne change aucune des trois clauses de 20.04.
    Les ennemis, eux, PEUVENT bouger pendant ma phase — un porteur de `reactive_move` réagit à
    9" de mon déplacement — et les 8" se déplacent avec lui. Les mettre dans la clé est donc la
    seule façon de ne pas servir un pool périmé.
    """
    return tuple(sorted(
        tuple(sorted(_ingress_enemy_model_positions(entry)))
        for entry in _ingress_enemy_entries(game_state, player)
    ))


def ingress_preview_loops(game_state: Dict[str, Any], squad_id: str) -> Optional[List[Any]]:
    """Contours (monde) de l'aire d'arrivée de ``squad_id``. Calcul PUR, mémoïsé, sans écriture.

    Mémo propre, indexé sur la MÊME clé que le pool ``(joueur, signature, positions ennemies)``.
    Passer par l'LRU partagé de `_sync_move_preview_mask_loops` reviendrait à l'indexer sur un
    `frozenset` de 57 538 tuples : construire cette clé coûte des millisecondes à chaque lecture,
    et l'entrée épingle ~9 Mo au-delà de la vie de la partie, dans un cache de module de 64
    entrées que rien ne vide — au risque d'y évincer les contours du MOUVEMENT, son usage
    d'origine. Ici la clé est un triplet déjà calculé.
    """
    player, cache_key, pool = _ingress_pool_with_key(game_state, str(squad_id))
    loops_cache = game_state.setdefault(INGRESS_LOOPS_CACHE_KEY, {})
    if cache_key in loops_cache:
        return loops_cache[cache_key]
    loops = compute_move_preview_mask_loops_world(pool, game_state)
    # Mémo purgé PAR EMPREINTE, pas par une borne de taille comme ses deux frères. Rien ne le vidait,
    # et la partie accumulait un jeu de contours par configuration ennemie traversée. La borne des
    # frères serait ici le mauvais outil : le contour est le poste le plus CHER à recalculer (0,99 s
    # contre 0,04 s pour le pool) et le plus LÉGER en mémoire, et un `clear()` en bloc tomberait au
    # milieu de `precompute_ingress_pools`, qui réchauffe N signatures sous une empreinte CONSTANTE —
    # il effacerait des entrées insérées quelques microsecondes plus tôt, dont le seul but est
    # d'éviter les 0,99 s au premier clic. On ne jette donc que ce qui est devenu INATTEIGNABLE :
    # `cache_key[2]` est l'empreinte ennemie, une entrée d'une autre empreinte ne peut plus être lue.
    loops_cache = {k: v for k, v in loops_cache.items() if k[2] == cache_key[2]}
    loops_cache[cache_key] = loops
    game_state[INGRESS_LOOPS_CACHE_KEY] = loops_cache
    return loops


def set_ingress_preview_loops(game_state: Dict[str, Any], squad_id: str) -> None:
    """PUBLIE l'aire d'arrivée de ``squad_id`` dans le canal d'aperçu du client.

    MÊME canal que l'aperçu de mouvement (``move_preview_footprint_mask_loops``) : le client sait
    déjà le rendre en polygone, et c'est ce qui évite de lui envoyer des dizaines de milliers de
    couples (col,row) — 57 538 cases en Deep Strike, rendues en 1 contour de 2 286 points.
    Le CALCUL, lui, est dans `ingress_preview_loops` : le réchauffage peut ainsi remplir le mémo
    sans toucher à l'état affiché, au lieu d'écrire puis restaurer l'aperçu du joueur.
    """
    game_state["move_preview_footprint_mask_loops"] = ingress_preview_loops(
        game_state, str(squad_id)
    )


def precompute_ingress_pools(game_state: Dict[str, Any]) -> int:
    """Calcule d'avance l'aire d'arrivée ET SON CONTOUR pour toutes les réserves du JOUEUR
    ACTIF. Rend le nombre de SIGNATURES calculées (pas d'unités : les unités de même signature
    les partagent).

    Aucun paramètre de joueur : `ingress_eligible_units` lit `current_player` — en accepter un
    laissait croire qu'on peut réchauffer les réserves d'un autre joueur, ce que cette fonction
    ne fait pas.

    À appeler à l'ouverture de la phase de mouvement CÔTÉ PvP, où un humain va cliquer et où
    payer le calcul au clic se verrait. La répartition mesurée (board x5, Deep Strike) est
    contre-intuitive et c'est elle qui dicte cette fonction : le POOL coûte 0,04 s, son CONTOUR
    0,99 s. Ne réchauffer que le pool ne servirait donc quasiment à rien — les deux mémos sont
    remplis ici.

    À NE PAS appeler en entraînement : la grande majorité des phases de mouvement n'a aucune
    unité en réserve, et le masque construit déjà, paresseusement, ce dont il a besoin.
    """
    signatures: Set[Any] = set()
    for squad_id in ingress_eligible_units(game_state):
        signature = ingress_pool_signature(game_state, squad_id)
        if signature in signatures:
            continue
        signatures.add(signature)
        # `ingress_preview_loops` et non `set_...` : le réchauffage remplit les mémos SANS
        # toucher à l'aperçu affiché. L'ancienne version écrivait puis restaurait le canal du
        # joueur — une exception au milieu lui laissait la bande d'une autre escouade.
        ingress_preview_loops(game_state, squad_id)
    return len(signatures)


def ingress_setup_pool(game_state: Dict[str, Any], squad_id: str) -> FrozenSet[Tuple[int, int]]:
    """Aire légale de mise en place d'un ingress move (20.04), Deep Strike compris (24.09).

    Composition, dans l'ordre du texte de la règle :
      1. « wholly within 6" of one or more battlefield edges » — bande de bord.
         **Deep Strike (24.09) remplace cette clause** : « it can be set up ANYWHERE on the
         battlefield », donc tout le plateau. Les 8" sont, eux, CONSERVÉS.
      2. « more than 8" horizontally from all enemy units » — dans les deux cas.
      3. « Before the Third Battle Round: no models can be set up within your opponent's
         deployment zone » — **levée par Deep Strike** (« even if that is within your
         opponent's deployment zone ») et levée pour tous à partir du 3e round.

    Les murs, les autres unités et la cohésion ne sont PAS filtrés ici : ils le sont par la
    chaîne de mise en place commune (`deployment_preview_plan`), exactement comme pour la zone
    de déploiement. Retourne l'ensemble des cases, éventuellement vide (aucune destination
    légale = pas d'ingress possible ce tour-ci, ce qui est un état de jeu normal).

    MÉMOÏSÉ par ``(joueur, signature, positions ennemies)`` : deux unités de même signature
    partagent le calcul (le pool ne dépend pas de l'unité au-delà de sa signature), et une
    seconde lecture dans le même état est gratuite. La clé porte les positions ennemies parce
    qu'elles PEUVENT changer pendant la phase (`reactive_move`) — voir
    `_ingress_enemy_positions_fingerprint`.
    """
    return _ingress_pool_with_key(game_state, str(squad_id))[2]


def _ingress_pool_with_key(
    game_state: Dict[str, Any], squad_id: str
) -> Tuple[int, Tuple[Any, ...], FrozenSet[Tuple[int, int]]]:
    """``(joueur, clé de mémo, pool)`` — le pool de `ingress_setup_pool` et sa clé, d'un coup.

    Les consommateurs qui mémoïsent AUTRE CHOSE sur le même état (les contours) réutilisent
    ainsi la clé au lieu d'en fabriquer une seconde.
    """
    units_cache = require_key(game_state, "units_cache")
    entry = require_key(units_cache, str(squad_id))
    player = int(require_key(entry, "player"))
    board_cols = int(require_key(game_state, "board_cols"))
    board_rows = int(require_key(game_state, "board_rows"))
    inches_to_subhex = int(require_key(game_state, "inches_to_subhex"))
    # Les trois clauses sont paramétrées PAR UNITÉ (cf. `ingress_pool_signature`) : Deep Strike
    # et les capacités qui déplacent les seuils passent toutes par là, aucune n'est codée ici.
    signature = ingress_pool_signature(game_state, str(squad_id))
    edge_distance, clearance, opponent_zone_open = signature
    fingerprint = _ingress_enemy_positions_fingerprint(game_state, player)
    cache_key = (player, signature, fingerprint)
    cache = game_state.setdefault(INGRESS_POOL_CACHE_KEY, {})
    hit = cache.get(cache_key)  # get allowed (1er calcul de cette signature)
    if hit is not None:
        return (player, cache_key, hit)

    if edge_distance is None:
        allowed = np.ones((board_cols, board_rows), dtype=bool)
    else:
        allowed = _ingress_edge_band_cells(
            board_cols, board_rows, int(edge_distance) * inches_to_subhex
        )
    # Le masque des 8" ne dépend PAS de la signature (ni de la bande de bord, ni de l'ouverture
    # de zone) : il a son propre mémo, sinon un roster mêlant Deep Strike et unités normales le
    # recalculait une fois par signature — 18 ms à chaque fois sur le roster réel.
    allowed = allowed & ~_ingress_clearance_mask_cached(
        game_state, player, clearance * inches_to_subhex, fingerprint, board_cols, board_rows,
    )
    cells = {(int(c), int(r)) for c, r in zip(*np.nonzero(allowed))}
    if not opponent_zone_open:
        cells -= _opponent_deployment_zone_cells(game_state, player)
    # `frozenset` : le pool est LU par la chaîne de mise en place, qui recopie défensivement tout
    # ensemble qu'on lui passe (`_deploy_pool_set`). Trois recopies de 57 538 tuples par action
    # d'ingress, mesurées à 36,6 ms sur 53 ms — un frozenset y est passé tel quel.
    pool = frozenset(cells)
    # Mémo BORNÉ : sa clé porte les positions ennemies, donc une entrée périmée est déjà
    # inaccessible ; la borne n'est là que pour que le dict ne grossisse pas d'une entrée par
    # configuration ennemie traversée dans la partie.
    if len(cache) >= _INGRESS_POOL_CACHE_MAX:
        cache.clear()
    cache[cache_key] = pool
    return (player, cache_key, pool)


def _ingress_clearance_mask_cached(
    game_state: Dict[str, Any], player: int, clearance_subhex: int,
    fingerprint: Tuple[Any, ...], board_cols: int, board_rows: int,
) -> "np.ndarray":
    """`_ingress_enemy_clearance_forbidden` mémoïsé sur ce dont il dépend RÉELLEMENT :
    ``(joueur, distance, positions ennemies)`` — ni la bande de bord ni la zone adverse."""
    cache = game_state.setdefault(INGRESS_CLEARANCE_CACHE_KEY, {})
    key = (int(player), int(clearance_subhex), fingerprint)
    hit = cache.get(key)  # get allowed (1er calcul de cette distance)
    if hit is not None:
        return hit
    mask = _ingress_enemy_clearance_forbidden(
        game_state, player, clearance_subhex, board_cols, board_rows
    )
    if len(cache) >= _INGRESS_POOL_CACHE_MAX:
        cache.clear()
    cache[key] = mask
    return mask


def ingress_eligible_units(game_state: Dict[str, Any]) -> List[str]:
    """Escouades du joueur actif éligibles à un ingress move CE TOUR-CI (20.03 + 20.04).

    « ELIGIBLE IF: Your unit is in strategic reserves » (20.04), « they can only do so from the
    second battle round onwards » (20.03). Le round d'arrivée est lu PAR UNITÉ : une capacité
    peut le ramener au 1er round (`set_reserves_arrival_round`), et la porte ne peut alors pas
    rester fermée par une constante globale. L'existence d'une destination légale n'est PAS
    testée ici : c'est le masque qui la vérifie (il n'ouvre un slot que s'il a un candidat
    validé), exactement comme pour le déploiement.
    """
    turn = int(require_key(game_state, "turn"))
    current_player = int(require_key(game_state, "current_player"))
    units_cache = require_key(game_state, "units_cache")
    eligible: List[str] = []
    for unit_id, entry in units_cache.items():
        if int(require_key(entry, "player")) != current_player:
            continue
        if not unit_is_in_strategic_reserves(game_state, str(unit_id)):
            continue
        unit = get_unit_by_id(game_state, str(unit_id))
        if unit is None:
            raise KeyError(f"ingress_eligible_units: unité {unit_id} absente de game_state")
        if turn < int(
            _reserves_param(unit, RESERVES_ARRIVAL_ROUND_FIELD, INGRESS_FIRST_BATTLE_ROUND)
        ):
            continue
        eligible.append(str(unit_id))
    return eligible


def ingress_commit_plan(
    game_state: Dict[str, Any], squad_id: str, plan: List[Tuple[str, int, int, int]],
) -> Tuple[bool, Dict[str, Any]]:
    """Exécute l'ingress move : pose l'escouade selon ``plan`` (03.02) et applique l'APRÈS 20.04.

    Le plan est revalidé contre l'aire légale du tour (`ingress_setup_pool`) par la chaîne de
    mise en place commune — un plan mémoïsé au masque et devenu illégal est donc refusé, pas
    appliqué.
    """
    from engine.phase_handlers.deployment_handlers import _apply_deploy_plan

    pool = ingress_setup_pool(game_state, str(squad_id))
    ok, err = _apply_deploy_plan(
        game_state,
        {"unitId": str(squad_id), "plan": [[mid, c, r, lv] for mid, c, r, lv in plan]},
        pool_override=pool,
        check_current_deployer=False,
    )
    if not ok:
        return False, err

    mark_unit_ingressed(game_state, str(squad_id))
    from engine.game_utils import add_console_log
    add_console_log(game_state, f"INGRESS MOVE: unit {squad_id} arrives from strategic reserves")
    return True, {
        "action": "ingress_move",
        "unitId": str(squad_id),
        "col": int(plan[0][1]),
        "row": int(plan[0][2]),
    }


def reposition_unit_to_strategic_reserves(game_state: Dict[str, Any], squad_id: str) -> None:
    """20.02 — RETIRE l'unité du champ de bataille et la replace en réserves stratégiques.

    Primitive des règles qui repositionnent une unité pendant la bataille (Da Jump, chantier 06).
    Les trois clauses de 20.02 sont satisfaites ici, et deux d'entre elles le sont en NE FAISANT
    RIEN — ce qui est précisément le piège, puisqu'un retrait « propre » aurait consisté à
    nettoyer l'état de l'unité :

      1. « If used in the Movement phase, such rules can be used on units that have already
         moved that phase. » -> aucune garde sur ``units_moved`` : l'appelant n'a pas à
         vérifier que l'unité n'a pas bougé.
      2. « A repositioned unit that is set up in the same turn in which it made an advance,
         fall-back or disembark move HAS STILL MADE that move that turn. » -> ``units_advanced``,
         ``units_fled`` et ``units_moved`` sont laissés INTACTS. Les effacer rendrait à l'unité
         le droit de tirer ou de charger après un Advance, en la faisant passer par les réserves.
      3. « Any rules that are affecting such units for a specified duration or under specified
         circumstances continue to affect them while that duration and/or those circumstances
         apply. » -> ``battle_shocked`` (durée : jusqu'à la prochaine phase de commandement) est
         conservé ; il tombera à son échéance normale. Les effets de CIRCONSTANCE (auras) ne
         sont, eux, portés par aucun état persistant : ils sont réévalués par distance à chaque
         lecture, donc ils cessent d'eux-mêmes hors table et se réappliquent à l'arrivée si
         l'unité est de nouveau à portée — exactement l'exemple du PDF.

    L'unité est EXEMPTÉE de la destruction de fin de 3e round (`reserves_repositioned`).
    """
    from engine.phase_handlers.shared_utils import update_model_position

    unit = get_unit_by_id(game_state, str(squad_id))
    if unit is None:
        raise KeyError(f"reposition_unit_to_strategic_reserves: unité {squad_id} introuvable")
    if require_key(unit, "deployed_on_turn") is None:
        raise ValueError(
            f"reposition_unit_to_strategic_reserves: l'unité {squad_id} n'est pas sur le champ "
            f"de bataille — 20.02 ne s'applique qu'à une unité qu'on en RETIRE"
        )
    squad_models = require_key(game_state, "squad_models")
    models_cache = require_key(game_state, "models_cache")
    for model_id in squad_models.get(str(squad_id), []):  # get allowed
        if model_id in models_cache:
            update_model_position(game_state, model_id, -1, -1)
    set_unit_coordinates(unit, -1, -1)
    unit["deployed_on_turn"] = None
    unit["in_strategic_reserves"] = True
    unit["reserves_repositioned"] = True
    from engine.game_utils import add_console_log
    add_console_log(
        game_state,
        f"REPOSITIONED (20.02): unit {squad_id} removed from the battlefield into reserves",
    )


def _handle_ingress_move_action(
    game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """Action `ingress_move` (20.04) du flux PvP : construit le plan, pose, termine l'activation.

    Le plan est construit par la MÊME fonction que le décodeur gym
    (`build_validated_deployment_plan` contraint au pool d'ingress) : les deux sièges posent donc
    l'escouade exactement pareil. La fin d'activation est celle de tout mouvement — l'escouade
    sort du pool d'activation, ce qui l'empêche de bouger une seconde fois et permet à la phase
    de se terminer par épuisement.
    """
    from engine.phase_handlers.deployment_handlers import build_validated_deployment_plan

    squad_id = str(require_key(unit, "id"))
    if not unit_is_in_strategic_reserves(game_state, squad_id):
        return False, {"error": "unit_not_in_strategic_reserves", "unitId": squad_id}
    if squad_id not in ingress_eligible_units(game_state):
        return False, {"error": "ingress_not_available_this_round", "unitId": squad_id}
    dest_col = int(require_key(action, "destCol"))
    dest_row = int(require_key(action, "destRow"))
    pool = ingress_setup_pool(game_state, squad_id)
    plan = build_validated_deployment_plan(game_state, squad_id, dest_col, dest_row, pool)
    if plan is None:
        return False, {
            "error": "no_legal_formation_for_ingress",
            "unitId": squad_id, "destCol": dest_col, "destRow": dest_row,
        }
    return _finalize_ingress(game_state, unit, squad_id, plan)


def _handle_ingress_commit_action(
    game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """Action `ingress_commit` (20.04) : pose l'escouade selon le plan ÉDITÉ par le joueur.

    Jumeau de `deploy_commit` pour l'arrivée. `ingress_move` construit la formation lui-même à
    partir d'une seule ancre — c'est ce qu'il faut au masque de l'agent, qui n'a qu'une case à
    proposer. Le joueur humain, lui, place ses figurines une à une dans l'aire d'arrivée comme il
    le fait au déploiement, et envoie le plan obtenu ; `ingress_commit_plan` le revalide contre
    l'aire du tour, donc rien n'est cru sur parole.
    """
    squad_id = str(require_key(unit, "id"))
    if not unit_is_in_strategic_reserves(game_state, squad_id):
        return False, {"error": "unit_not_in_strategic_reserves", "unitId": squad_id}
    if squad_id not in ingress_eligible_units(game_state):
        return False, {"error": "ingress_not_available_this_round", "unitId": squad_id}
    from engine.phase_handlers.shared_utils import parse_model_plan

    plan = [
        (mid, col, row, level)
        for mid, col, row, level in parse_model_plan(
            require_key(action, "plan"), action_name="ingress_commit"
        )
    ]
    return _finalize_ingress(game_state, unit, squad_id, plan)


def _finalize_ingress(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    squad_id: str,
    plan: List[Tuple[str, int, int, int]],
) -> Tuple[bool, Dict[str, Any]]:
    """Pose + journal + invalidation des pools + fin d'activation, pour les DEUX arrivées.

    Tronc commun de `ingress_move` (ancre seule) et `ingress_commit` (plan édité) : ce qui suit
    la pose ne dépend pas de la façon dont le plan a été obtenu, et l'avoir écrit deux fois est
    exactement ce qui a déjà produit ici une arrivée sans fin d'activation.
    """
    ok, result = ingress_commit_plan(game_state, squad_id, plan)
    if not ok:
        return False, result
    # ARRIVÉE COMPTÉE POUR LES DEUX CAMPS (le filtre sur le joueur contrôlé rendait celle du bot
    # invisible), et marquée en (joueur, escouade, TOUR) : c'est ce tour-là qui distingue, plus
    # bas, une offre d'arrivée SAISIE d'une offre DÉCLINÉE.
    _ingress_player = int(require_key(unit, "player"))
    require_key(game_state, "_reserves_deployed")[_ingress_player] += 1
    require_key(game_state, "_ingress_arrived").add(
        (_ingress_player, str(squad_id), int(require_key(game_state, "turn")))
    )
    # Journal d'action : écrit ICI, donc pour les DEUX sièges. Il vivait dans la branche gym de
    # `w40k_core`, ce qui laissait une arrivée PvP invisible au replay et à l'analyzer — une
    # unité y apparaissait sur le plateau sans qu'aucune ligne ne l'explique.
    _ing_col, _ing_row = require_unit_position(squad_id, game_state)
    append_action_log(
        game_state,
        {
            "type": "deploy_unit",
            "message": (
                f"Unit {squad_id} INGRESS from strategic reserves to ({_ing_col},{_ing_row})"
            ),
            "turn": require_key(game_state, "turn"),
            "phase": "move",
            "unitId": squad_id,
            "player": require_key(unit, "player"),
            # (-1,-1) = convention « pas sur le plateau » de l'en-tête d'épisode, exigée par le
            # formateur `deploy_unit` (start_pos ET end_pos).
            "fromCol": -1,
            "fromRow": -1,
            "toCol": _ing_col,
            "toRow": _ing_row,
            "timestamp": "server_time",
            "reward": 0.0,
        },
    )
    # Jumeau de `movement_commit_move_plan_handler` : une mise en place change l'occupation du
    # plateau, donc les pools de destination (BFS de move, de charge) sont périmés, et l'aperçu
    # affiché — ici la bande d'arrivée, jusqu'à 2 286 points — doit être effacé, sans quoi il
    # resterait sérialisé dans chaque réponse suivante.
    #
    # ⚠️ Les aires d'ingress des AUTRES réserves, elles, ne sont PAS périmées par cette pose :
    # leur clé ne porte que les positions ENNEMIES (`_ingress_enemy_positions_fingerprint`), et
    # l'unité qui vient d'arriver est amie. Leur mémo est bien vidé par l'appel ci-dessous, mais
    # c'est de l'hygiène mémoire, pas une correction — le confondre avec une invalidation
    # nécessaire ferait croire à un couplage qui n'existe pas.
    movement_clear_preview(game_state)
    _invalidate_all_destination_pools_after_movement(game_state)
    end_result = end_activation(game_state, unit, ACTION, 1, MOVE, MOVE, 1)
    return True, {**end_result, **result}


def mark_unit_ingressed(game_state: Dict[str, Any], squad_id: str) -> None:
    """20.04 AFTER MOVING — « until the start of the next Charge phase, your unit is not eligible
    to make any other type of move ».

    Le marqueur vit dans ``units_ingressed_no_move`` (jumeau de ``units_moved`` / ``units_fled``)
    et est purgé au DÉBUT de la phase de charge (`clear_ingress_move_lock`), pas à la fin de la
    phase de mouvement : c'est la durée que dit la règle. L'escouade est en outre ajoutée à
    ``units_moved`` — elle a été activée ce tour-ci, comme après un déplacement.
    """
    squad_id_str = str(squad_id)
    game_state.setdefault("units_ingressed_no_move", set()).add(squad_id_str)
    game_state.setdefault("units_moved", set()).add(squad_id_str)


def unit_ingress_move_locked(game_state: Dict[str, Any], squad_id: str) -> bool:
    """L'escouade est-elle sous le verrou « aucun autre type de mouvement » de 20.04 ?"""
    return str(squad_id) in game_state.get("units_ingressed_no_move", set())  # get allowed


def clear_ingress_move_lock(game_state: Dict[str, Any]) -> None:
    """Lève le verrou 20.04 au DÉBUT de la phase de charge (« until the start of the next Charge
    phase »). Appelé par `charge_phase_start`, pour les DEUX camps : le verrou d'une unité posée
    au tour du joueur A tombe à la phase de charge suivante, qui est la sienne."""
    game_state["units_ingressed_no_move"] = set()


def movement_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """AI_MOVE.md: Clean up and end movement phase"""
    movement_clear_preview(game_state)
    
    # Track phase completion reason (tour_de_jeu.md compliance)
    if 'last_compliance_data' not in game_state:
        game_state['last_compliance_data'] = {}
    game_state['last_compliance_data']['phase_end_reason'] = 'eligibility'
    
    from engine.game_utils import add_console_log
    add_console_log(game_state, "MOVEMENT PHASE COMPLETE")

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    move_pool = require_key(game_state, "move_activation_pool")
    add_debug_file_log(game_state, f"[POOL PRE-TRANSITION] E{episode} T{turn} move move_activation_pool={move_pool}")
    
    return {
        "phase_complete": True,
        "next_phase": "shoot",
        "units_processed": len([uid for uid in require_key(game_state, "units_cache").keys() if uid in game_state["units_moved"]])
    }
