#!/usr/bin/env python3
"""
Mesures de latence optionnelles (wall-clock) pour diagnostiquer les ralentissements en jeu.

Activation :
  - variable d'environnement ``W40K_PERF_TIMING=1`` (ou ``true`` / ``yes``), ou
  - ``game_state["perf_timing"] is True`` (ex. scénario / init moteur).

Audit optionnel focus fire (comparaison pools) :
  - ``W40K_FOCUS_FIRE_POOL_AUDIT=1`` ou ``focus_fire_pool_audit`` dans ``game_state``,
  - ou tout audit perf si ``W40K_PERF_TIMING`` est déjà actif.

Sortie : fichier append-only ``<racine_projet>/perf_timing.log`` (une ligne par segment), sauf si
``W40K_PERF_TIMING_LOG`` est défini (chemin absolu ou relatif du fichier à utiliser).

Réponse HTTP (même activation ``W40K_PERF_TIMING`` ou ``game_state["perf_timing"]``) :
  - en-tête ``Server-Timing`` sur ``POST /api/game/action`` : ``engine``, ``serialize``, ``json_encode``,
    ``post_action_wall`` (durées en **millisecondes**) ;
  - en-tête ``X-W40k-Payload-Bytes`` : taille du corps JSON renvoyé.
  Le front peut les afficher en console si les traces client sont activées (``DEBUG_FIGHT_CLICK`` /
  ``DEBUG_ACTION_LOG``) ; l’onglet Network du navigateur les montre toujours pour cette requête.

Profilage par fonctions (cProfile), optionnel — **uniquement si** ``perf_timing`` est déjà actif :

- ``W40K_PERF_PROFILE=1`` (ou ``true`` / ``yes``), ou ``game_state["perf_profile"] is True`` ;
- sortie multi-lignes dans ``<racine_projet>/perf_timing_profile.log`` (override : ``W40K_PERF_PROFILE_LOG``) ;
- une ligne référence ``PERF_PROFILE_DUMP`` dans ``perf_timing.log`` pointe vers ce fichier.

Actuellement utilisé autour de ``movement_build_valid_destinations_pool`` (activation déplacement).

**Important :** seul le processus **Python** (API Flask, bots, tests moteur) écrit ce fichier — pas le
serveur frontend (Vite / ``npm run dev``). Si tu lances uniquement ``app``, aucun ``perf_timing.log``
n’apparaîtra à la racine du dépôt.

Lignes typiques (référence) :

- ``API_ACTION_REQUEST`` — entrée ``POST /api/game/action`` : ``phase_before``, ``action``, ``unitId`` (requête
  client avant routage ; à distinguer des ``EXECUTE_SEMANTIC_TOTAL`` internes, ex. ``skip`` lors d’un
  ``end_phase``).
- ``API_POST_ACTION`` — ``engine_s`` (``execute_semantic_action`` / handlers), ``serialize_game_state_s``
  (``make_json_serializable`` + sync HP + types joueurs), ``response_encode_s`` (``api_json_response`` :
  encodage JSON du corps, typiquement ``orjson.dumps`` avec repli), ``total_wall_s`` depuis le début du
  traitement POST, et ``payload_bytes`` (taille en octets du corps JSON renvoyé au client ; ``-1`` si
  la mesure n’est pas disponible). Ce dernier champ permet de corréler ``response_encode_s`` avec la
  taille effective de la réponse (diagnostic payload vs. coût d’encodage).
- ``API_PAYLOAD_BREAKDOWN`` — optionnel si ``W40K_PERF_PAYLOAD_BREAKDOWN=1`` : ``orjson_full_payload`` /
  ``orjson_game_state`` (même encodage que le corps HTTP, pas orjson pur si repli Flask), somme des
  tailles par clé de premier niveau, et clés ≥ 10 Ko (voir ``services.api_server._log_payload_breakdown``).
- ``SHOOT_ACTIVATION_START`` — une activation tir (``activate_unit`` → ``shooting_unit_activation_start``) :
  ``los_cache_s`` (``build_unit_los_cache``) ;
  ``activation_prep_s`` (réinitialisations entre fin LoS et précheck ennemi : adjacence, PISTOL, reset ``shot``, etc.) ;
  ``enemy_precheck_s`` (uniquement ``_build_weapon_availability_enemy_precheck``) ;
  ``weapon_avail_inner_s`` (uniquement le corps de ``weapon_availability_check`` avec ``_precheck`` déjà fourni) ;
  ``target_pool_s`` (``shooting_build_valid_target_pool``) ; ``tail_s`` (arme par défaut, JSON armes, etc.) ;
  ``total_s``, ``outcome`` (ex. ``success``, ``empty_pool_advance``, ``empty_pool_skip``), ``valid_targets_n``.
  La somme ``enemy_precheck_s`` + ``weapon_avail_inner_s`` correspond au coût « armes » avant le pool de cibles ;
  la ligne ``WEAPON_AVAILABILITY_CHECK`` ne mesure que l’intérieur de ``weapon_availability_check`` (donc proche de
  ``weapon_avail_inner_s`` quand le précheck est passé en amont, pas ``enemy_precheck_s``).
- ``SHOOT_PHASE_HANDLER`` — découpe ``_process_shooting_phase`` (``w40k_core``) : ``shooting_phase_start_s``
  (appel optionnel à ``shooting_phase_start`` si la phase n’était pas encore marquée initialisée),
  ``execute_action_s`` (``shooting_handlers.execute_action`` — inclut p.ex. ``activate_unit`` / tir / advance),
  ``phase_end_s`` (fusion ``shooting_phase_end`` si ``phase_complete``), ``total_handler_s``.
  Explique l’écart entre ``SHOOT_ACTIVATION_START`` et ``SEMANTIC_SEGMENTS`` / ``EXECUTE_SEMANTIC_TOTAL`` pour
  ``activate_unit`` quand ``shooting_phase_start`` a encore tourné sur la même requête.
- ``WEAPON_AVAILABILITY_CHECK`` — une ligne par appel à ``weapon_availability_check`` (perf activée) :
  ``precheck_build_s`` (construction ``_build_weapon_availability_enemy_precheck`` **à l’intérieur** de la fonction
  si le précheck n’est pas fourni par l’appelant), ``weapon_row_scan_s``, ``overhead_s``, ``total_s``.
  À l’activation tir, le précheck est souvent déjà construit dans ``enemy_precheck_s`` (voir ``SHOOT_ACTIVATION_START``) :
  alors ``precheck_build_s`` est nul ici mais le gros travail peut apparaître dans ``enemy_precheck_s``.
- ``END_PHASE`` — ``services/api_server._execute_end_phase_action`` : ``activate_semantic_s`` / ``skip_semantic_s``
  (sommes des ``execute_semantic_action`` activate / skip par unité), ``advance_phase_s``, ``unit_pairs``,
  ``outcome``, ``total_s``. Découpe le coût moteur d’un ``end_phase`` HTTP (plusieurs activations + ``advance_phase``).
- ``PERF_PROFILE_DUMP`` — dump cProfile (top fonctions) : ``label``, ``unit``, ``file``, ``chars`` (voir
  ``perf_timing_profile.log``).
- ``MOVE_POOL_BUILD`` — ``prep_s`` (caches occupation / EZ), ``bfs_s`` (exploration seule), ``post_bfs_s``
  (union empreintes + écriture état + masque), découpé en ``footprint_union_s`` (construction
  ``move_preview_footprint_zone`` + clés état jusqu’au sync) et ``mask_loops_s`` (uniquement
  ``compute_move_preview_mask_loops_world`` / ``_sync_move_preview_mask_loops``) ; ``total_s``, compteurs
  ``visited`` / ``valid``. ``anchors_n`` = taille de ``valid_move_destinations_pool`` (disques UI) ;
  ``footprint_hex_n`` = taille de ``move_preview_footprint_zone`` (union hex ; vol : ``na_fly``).
- ``CHARGE_PHASE_START`` — ``setup_until_adj_s``, ``enemy_adjacent_hexes_s``, ``pool_build_s``, ``total_s`` (début phase charge).
- ``CHARGE_BUILD_POOL`` — ``get_eligible_s``, ``eligible_count`` (construction du pool d’activation).
- ``CHARGE_HEX_LB_PRUNE`` — pré-filtre géométrique : pas de BFS si le primaire est trop loin de toute
  empreinte ennemie pour pouvoir engager en au plus ``bfs_max`` pas (grille hex ; désactivé pour
  engagement socle rond ↔ rond, métrique euclidienne).
- ``CHARGE_REVERSE_GOAL_BFS`` — chemin optimisé de l’éligibilité charge (``early_exit_if_valid``) :
  génère les ancres finales légales qui engagent un ennemi, puis cherche le primaire depuis ces buts
  dans le même graphe de placements légaux. ``outcome=hit|miss|no_goals``.
  ``pruned_start_lb_n`` = branches coupées car la distance hex restante vers le primaire dépasse déjà
  le budget BFS restant.
  ``goal_candidates_n`` = intersection entre zone ennemie et disque géométriquement atteignable depuis
  le primaire ; ``skipped_goal_start_lb_n`` = ancres de la zone ennemie écartées avant empreinte/placement
  car hors portée géométrique du primaire ; ``goal_build_s`` et ``reverse_bfs_s`` découpent le coût.
  ``goal_candidate_fp_s`` / ``goal_placement_s`` / ``goal_engagement_s`` détaillent la génération des
  buts, avec compteurs ``rejected_placement_n``, ``rejected_overlap_n``,
  ``rejected_engagement_prefilter_n``, ``rejected_no_engagement_n``. Ce chemin optimisé est désactivé
  si une paire round↔round est en jeu : le BFS historique reste plus rentable et conserve la métrique
  euclidienne exacte.
- ``CHARGE_DEST_BFS`` — ``bfs_loop_s``, ``total_s``, ``visited_n``, ``valid_dest_n``, ``cache_hit``,
  ``early_exit`` (1 = éligibilité uniquement, arrêt au premier hex valide), ``short_circuit`` (1 si arrêt anticipé).
  ``bfs_candidate_fp_s`` / ``bfs_placement_s`` / ``bfs_engagement_s`` détaillent le BFS historique,
  avec compteurs ``bfs_rejected_placement_n``, ``bfs_overlap_n``, ``bfs_no_engagement_n``,
  ``bfs_engagement_checks_n``.
  ``charge_roll`` est en **pas de grille** (sous-hex) : sur plateau Boardx10, ``game_rules.charge_max_distance``
  est déjà multiplié par ``inches_to_subhex`` (ex. 12\" → 120).
  ``fp=offset`` : empreinte par offsets pré-calculés (multi-hex ×10) ; ``fp=legacy`` : ``compute_candidate_footprint``.
- Logs verbeux ``[CHARGE DEBUG]`` (positions / occupation) : ``W40K_CHARGE_DEBUG=1`` ou
  ``game_state["charge_debug_positions"]``.
- ``CHARGE_HAS_VALID_TARGET`` — ``bfs_pool_s``, ``nested_loop_s``, ``reachable_n``, ``enemy_n`` (éligibilité).
- ``FIGHT_KILL_ATTACK_SEQUENCE`` — coup fatal (sauvegarde ratée → HP 0) : ``update_hp_s``,
  ``invalidate_target_cache_s``, ``remove_pools_and_rebuild_s``, ``invalidate_dead_unit_cache_s``,
  ``append_combat_log_s``, ``append_death_log_s``, ``engine_kill_path_s`` (somme moteur avant les
  deux append), ``total_to_logs_s`` (jusqu’après l’entrée ``death`` dans ``action_logs``). Permet de
  distinguer coût pools / caches IA vs écriture des logs.
- ``FIGHT_KILL_VALID_TARGET_POOL`` — après une mort, si ``ATTACK_LEFT`` > 0 : durée de
  ``_fight_build_valid_target_pool`` pour l’attaquant (``pool_s``, ``valid_targets_n``).
- ``FIGHT_CONSOLIDATION_PLAN`` — ``_fight_plan_consolidation_destinations`` (BFS / géométrie) :
  ``plan_s``, ``has_plan``, ``trigger`` (raison ou libellé explicite).
- ``FIGHT_CONSOLIDATION_FP_ZONE`` — ``_fight_compute_pile_in_footprint_zone`` (chemin UI humain) :
  ``fp_zone_s``, ``dest_n``, ``trigger``.
- ``FIGHT_CONSOLIDATION_BFS`` — ``_fight_bfs_reachable_anchors_consolidation`` : ``visited_n``,
  ``neighbor_eval_n``, ``compute_fp_s``, ``placement_valid_s``, ``total_s`` (isoler BFS vs filtre).
- ``FIGHT_CONSOLIDATION_ENEMY_ANCHOR_FILTER`` — boucle ``for anchor in visited`` branche ennemie :
  ``visited_n``, ``strict_closer_calls_n``, ``engagement_calls_n``, ``distance_pair_eval_n``,
  ``shell_build_s``, ``strict_eval_s``, ``engagement_eval_s``, ``distance_eval_s``, ``other_filter_s``,
  ``filter_s``, ``candidates_n``.
- ``FIGHT_CONSOLIDATION_OBJ_ANCHOR_FILTER`` — boucle ``for anchor in visited`` branche objectif :
  ``visited_n``, ``strict_closer_calls_n``, ``strict_eval_s``, ``other_filter_s``, ``filter_s``,
  ``start_d_obj`` (distance départ → marqueur). ``strict_eval_s`` mesure le coût du test
  « strictement plus proche » sur toutes les ancres (distance empreinte → palier marqueur).
"""

from __future__ import annotations

import functools
import io
import os
import sys
from typing import Any, Callable, Dict, Optional, TypeVar

_PERF_ENV_TRUE = frozenset({"1", "true", "yes"})
_PERF_WRITE_ERROR_LOGGED = False
_PERF_PROFILE_WRITE_ERROR_LOGGED = False

F = TypeVar("F", bound=Callable[..., Any])


def perf_timing_log_file_path() -> str:
    """
    Chemin du fichier de log perf (append).

    Priorité :
    1. ``W40K_PERF_TIMING_LOG`` si défini (non vide) — chemin relatif au cwd ou absolu ;
    2. sinon ``<racine_projet>/perf_timing.log`` (parent du dossier ``engine/`` où se trouve ce module).
    """
    override = os.environ.get("W40K_PERF_TIMING_LOG", "").strip()
    if override:
        return os.path.abspath(override)
    here = os.path.abspath(__file__)
    engine_dir = os.path.dirname(here)
    project_root = os.path.dirname(engine_dir)
    return os.path.join(project_root, "perf_timing.log")


def perf_timing_enabled(game_state: Optional[Dict[str, Any]]) -> bool:
    """Retourne True si les logs de performance sont activés."""
    raw = os.environ.get("W40K_PERF_TIMING", "")
    if isinstance(raw, str) and raw.strip().lower() in _PERF_ENV_TRUE:
        return True
    if game_state is not None and game_state.get("perf_timing") is True:
        return True
    return False


def perf_profile_log_file_path() -> str:
    """
    Fichier append pour les sorties cProfile (blocs multi-lignes).

    Priorité :
    1. ``W40K_PERF_PROFILE_LOG`` si défini (non vide) ;
    2. sinon ``<racine_projet>/perf_timing_profile.log``.
    """
    override = os.environ.get("W40K_PERF_PROFILE_LOG", "").strip()
    if override:
        return os.path.abspath(override)
    here = os.path.abspath(__file__)
    engine_dir = os.path.dirname(here)
    project_root = os.path.dirname(engine_dir)
    return os.path.join(project_root, "perf_timing_profile.log")


def perf_profile_enabled(game_state: Optional[Dict[str, Any]]) -> bool:
    """
    Profilage cProfile : uniquement lorsque ``perf_timing`` est actif, plus
    ``W40K_PERF_PROFILE=1`` ou ``game_state['perf_profile'] is True``.
    """
    if not perf_timing_enabled(game_state):
        return False
    raw = os.environ.get("W40K_PERF_PROFILE", "")
    if isinstance(raw, str) and raw.strip().lower() in _PERF_ENV_TRUE:
        return True
    if game_state is not None and game_state.get("perf_profile") is True:
        return True
    return False


def focus_fire_pool_audit_enabled(game_state: Optional[Dict[str, Any]]) -> bool:
    """
    Audit léger : compare shooting_build_valid_target_pool vs unit['valid_target_pool']
    pour le bonus focus fire (écrit une ligne SHOOT_FOCUS_FIRE_POOL_AUDIT dans perf_timing.log).

    Activation : perf_timing déjà actif, ou ``W40K_FOCUS_FIRE_POOL_AUDIT=1``,
    ou ``game_state['focus_fire_pool_audit'] is True``.
    """
    if perf_timing_enabled(game_state):
        return True
    raw = os.environ.get("W40K_FOCUS_FIRE_POOL_AUDIT", "")
    if isinstance(raw, str) and raw.strip().lower() in _PERF_ENV_TRUE:
        return True
    if game_state is not None and game_state.get("focus_fire_pool_audit") is True:
        return True
    return False


def append_perf_timing_line(message: str) -> None:
    """
    Écrit une ligne dans le fichier perf (voir ``perf_timing_log_file_path``), append + flush.

    En cas d'échec d'écriture, un message est envoyé une fois sur stderr (pour ne pas masquer
    un mauvais cwd, permissions, ou moteur chargé depuis un autre répertoire).
    """
    global _PERF_WRITE_ERROR_LOGGED
    path = perf_timing_log_file_path()
    try:
        with open(path, "a", encoding="utf-8", errors="replace") as f:
            f.write(message + "\n")
            f.flush()
    except OSError as exc:
        if not _PERF_WRITE_ERROR_LOGGED:
            _PERF_WRITE_ERROR_LOGGED = True
            print(
                f"[perf_timing] impossible d'écrire dans {path!r}: {exc} "
                f"(cwd={os.getcwd()!r}, définir W40K_PERF_TIMING_LOG si besoin)",
                file=sys.stderr,
            )


def append_perf_profile_block(header_line: str, body: str) -> None:
    """
    Écrit un bloc (en-tête + corps pstats) dans le fichier profil, append + flush.
    """
    global _PERF_PROFILE_WRITE_ERROR_LOGGED
    path = perf_profile_log_file_path()
    try:
        with open(path, "a", encoding="utf-8", errors="replace") as f:
            f.write(header_line.rstrip() + "\n")
            f.write(body)
            if not body.endswith("\n"):
                f.write("\n")
            f.write("=== END PERF_PROFILE ===\n")
            f.flush()
    except OSError as exc:
        if not _PERF_PROFILE_WRITE_ERROR_LOGGED:
            _PERF_PROFILE_WRITE_ERROR_LOGGED = True
            print(
                f"[perf_timing] impossible d'écrire le profil dans {path!r}: {exc} "
                f"(cwd={os.getcwd()!r}, définir W40K_PERF_PROFILE_LOG si besoin)",
                file=sys.stderr,
            )


def append_cprofile_dump(
    profiler: Any,
    label: str,
    *,
    unit_id: Optional[str] = None,
    print_stats: int = 40,
) -> None:
    """
    Sérialise ``pstats`` (tri cumulatif, top ``print_stats`` lignes) et journalise.

    Ajoute une ligne ``PERF_PROFILE_DUMP`` dans ``perf_timing.log`` pour corrélation.
    """
    import pstats

    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream).sort_stats(pstats.SortKey.CUMULATIVE)
    stats.print_stats(print_stats)
    text = stream.getvalue()
    uid = unit_id if unit_id is not None else ""
    header = f"=== PERF_PROFILE label={label!r} unit={uid!r} ==="
    append_perf_profile_block(header, text)
    prof_path = perf_profile_log_file_path()
    append_perf_timing_line(
        f"PERF_PROFILE_DUMP label={label!r} unit={uid!r} file={prof_path!r} chars={len(text)}"
    )


def profile_move_pool_build(fn: F) -> F:
    """
    Décorateur : exécute ``movement_build_valid_destinations_pool`` sous cProfile si
    ``perf_profile_enabled`` ; sinon coût nul (pas de profiler).
    """

    @functools.wraps(fn)
    def wrapper(game_state: Dict[str, Any], unit_id: str) -> Any:
        if not perf_profile_enabled(game_state):
            return fn(game_state, unit_id)
        import cProfile

        pr = cProfile.Profile()
        pr.enable()
        try:
            return fn(game_state, unit_id)
        finally:
            pr.disable()
            append_cprofile_dump(pr, fn.__name__, unit_id=str(unit_id))

    return wrapper  # type: ignore[return-value]
