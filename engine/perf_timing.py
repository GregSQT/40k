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
  ``activation_prep_s`` (réinitialisations entre fin LoS et précheck ennemi : adjacence, CLOSE_QUARTERS, reset ``shot``, etc.) ;
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
- ``CHARGE_BUILD_POOL`` — ``charge_build_activation_pool`` : ``occupied_pos_s``, ``filter_only_s``
  (boucle d’éligibilité hors BFS), ``bfs_total_s`` (cumul des ``_has_valid_charge_target``, donc des
  lignes ``CHARGE_HAS_VALID_TARGET``), ``total_s``, compteurs ``units_total_n`` / ``units_own_n`` /
  ``bfs_calls_n``. Cet appel est **inclus** dans ``CHARGE_PHASE_START.pool_build_s``.
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
  ``charge_roll`` est en **pas de grille** (sous-hex) : sur plateau Boardx10, ``charge.charge_max_distance``
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
from typing import Any, Callable, Dict, Optional, TypeVar, cast

_PERF_ENV_TRUE = frozenset({"1", "true", "yes"})
_PERF_WRITE_ERROR_LOGGED = False
_PERF_PROFILE_WRITE_ERROR_LOGGED = False

# Handle de fichier perf ouvert en continu pour éviter open/flush/close à chaque ligne.
_PERF_FILE_HANDLE: Optional[Any] = None
_PERF_FILE_PATH: Optional[str] = None
_PERF_WRITE_COUNT: int = 0
_PERF_SIGTERM_INSTALLED: bool = False
# Flush tous les N writes. Défaut 500 (perf training). Surchargeable via env pour le debug
# interactif (ex. ``W40K_PERF_TIMING_FLUSH_EVERY=1`` → chaque ligne visible immédiatement).
try:
    _PERF_FLUSH_INTERVAL: int = max(1, int(os.environ.get("W40K_PERF_TIMING_FLUSH_EVERY", "500")))
except ValueError:
    _PERF_FLUSH_INTERVAL = 500

F = TypeVar("F", bound=Callable[..., Any])


def _get_perf_file_handle() -> Optional[Any]:
    """Retourne le handle ouvert vers le fichier perf, en l'ouvrant si nécessaire."""
    global _PERF_FILE_HANDLE, _PERF_FILE_PATH
    import atexit
    path = perf_timing_log_file_path()
    if _PERF_FILE_HANDLE is None or _PERF_FILE_PATH != path:
        if _PERF_FILE_HANDLE is not None:
            try:
                _PERF_FILE_HANDLE.flush()
                _PERF_FILE_HANDLE.close()
            except OSError:
                pass
            # Purge inconditionnelle : si l'`open` ci-dessous echoue, garder ici le handle FERME
            # ferait lever `ValueError: I/O operation on closed file` au prochain flush — une
            # exception que l'appelant ne rattrape pas (il ne filtre que `OSError`), donc un
            # echec d'ECRITURE DE LOG se transformerait en plantage moteur.
            _PERF_FILE_HANDLE = None
            _PERF_FILE_PATH = None
        _PERF_FILE_HANDLE = open(path, "a", encoding="utf-8", errors="replace", buffering=8192)
        _PERF_FILE_PATH = path
        atexit.register(_flush_perf_file)
        _install_sigterm_flush()
    return _PERF_FILE_HANDLE


def _install_sigterm_flush() -> None:
    """Flush du buffer perf sur SIGTERM, en plus de l'``atexit``.

    Les workers ``SubprocVecEnv`` sont demoniques : tues par SIGTERM, ils n'executent AUCUN
    ``atexit``, et avec un buffer de 8 Ko flushe toutes les 500 lignes chacun perdait sa queue
    de lignes — precisement ses derniers episodes, de facon invisible dans le rapport. Le
    handler flushe, restaure le comportement precedent et se renvoie le signal : la terminaison
    reste identique, seule la perte de donnees disparait.

    ``ai/train.py`` ferme desormais l'environnement en fin de run (``close_training_env``), donc
    la sortie NORMALE ne passe plus par ce chemin. Ce handler reste la borne des sorties
    ANORMALES — Ctrl-C sur le pere, `kill`, worker termine par le gestionnaire multiprocessing
    si une fermeture echoue — ou l'``atexit`` du fils ne s'executera jamais.
    """
    global _PERF_SIGTERM_INSTALLED
    if _PERF_SIGTERM_INSTALLED:
        return
    import signal
    try:
        previous = signal.getsignal(signal.SIGTERM)
    except ValueError:
        return  # pas le thread principal : la pose de handler y est interdite, atexit suffit

    def _handler(signum: int, frame: Any) -> None:
        _flush_perf_file_keep_open()
        signal.signal(signal.SIGTERM, previous if previous is not None else signal.SIG_DFL)
        os.kill(os.getpid(), signum)
        # Encore vivant : la disposition precedente etait SIG_IGN, ou c'etait un handler qui rend
        # la main. On repose le notre, sinon le prochain SIGTERM ne flusherait plus rien.
        signal.signal(signal.SIGTERM, _handler)

    try:
        signal.signal(signal.SIGTERM, _handler)
    except ValueError:
        return
    _PERF_SIGTERM_INSTALLED = True


def _flush_perf_file() -> None:
    """Flush + fermeture du handle perf à l'exit du processus."""
    global _PERF_FILE_HANDLE
    if _PERF_FILE_HANDLE is not None:
        try:
            _PERF_FILE_HANDLE.flush()
            _PERF_FILE_HANDLE.close()
        except (OSError, ValueError):
            pass
        _PERF_FILE_HANDLE = None


def _flush_perf_file_keep_open() -> None:
    """Flush SANS fermer : utilisable depuis un handler de signal.

    Fermer ici serait un piege : si la disposition SIGTERM precedente est ``SIG_IGN`` (ou un
    handler Python qui rend la main), le processus SURVIT au signal et reprend son ecriture sur
    un fichier ferme — ``ValueError``, que l'appelant ne rattrape pas.
    """
    if _PERF_FILE_HANDLE is not None:
        try:
            _PERF_FILE_HANDLE.flush()
        except (OSError, ValueError, RuntimeError):
            # RuntimeError : le signal est tombe a l'interieur d'un `write`, le tampon est deja
            # verrouille (« reentrant call inside BufferedWriter »). Laisser filer tuerait le
            # worker au lieu de le terminer ; la ligne en cours est perdue, pas le processus.
            pass


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
        pass
    elif game_state is not None and game_state.get("perf_timing") is True:
        pass
    else:
        return False
    # Distinguer ABSENTE de POSEE-VIDE. Absente = option non demandee : 1 (tout capturer) est le
    # comportement voulu, pas un repli. Posee vide, c'est une substitution shell ratee
    # (`W40K_PERF_TIMING_MIN_EPISODE=$MIN_EP` avec MIN_EP non defini) : elle change la fenetre de
    # mesure en silence, exactement ce que le rejet ci-dessous existe pour empecher. Le cas
    # "posee vide" n'arrive donc jamais sur un run normal, ou la variable est simplement absente.
    min_ep_env = os.environ.get("W40K_PERF_TIMING_MIN_EPISODE")
    min_ep_raw = "1" if min_ep_env is None else min_ep_env.strip()
    if not min_ep_raw.isdigit():
        # Pas de repli sur 1 : une valeur mal saisie (`-1`, `1e3`, faute de frappe) changerait
        # silencieusement la base de mesure — on croirait comparer deux runs sur la meme fenetre
        # d'episodes alors que l'un capture tout depuis le premier.
        raise ValueError(
            f"W40K_PERF_TIMING_MIN_EPISODE={min_ep_raw!r} invalide : entier positif attendu."
        )
    min_ep = int(min_ep_raw)
    if game_state is not None and game_state.get("episode_number", 1) < min_ep:
        return False
    return True


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


def perf_field(value: Any) -> str:
    """Rend une valeur pour un champ ``cle=valeur`` du log, sans espace.

    Les lignes sont parsees par ``split()`` puis ``split("=", 1)`` : une valeur contenant un
    espace casse le decoupage et decale les champs. ``BASE_SIZE`` est scalaire pour un socle
    simple mais peut etre une liste (socle rectangulaire), auquel cas ``str([20, 30])`` produit
    ``base=[20, 30]`` -> tokens ``base=[20,`` et ``30]``, donc un champ illisible.

    Suppression des espaces uniquement : la valeur reste fidele (``[20,30]``), aucune troncature
    ni substitution qui masquerait ce que le moteur a reellement manipule.
    """
    return str(value).replace(" ", "")


def append_perf_timing_line(message: str) -> None:
    """
    Écrit une ligne dans le fichier perf (voir ``perf_timing_log_file_path``), via handle bufferisé.

    En cas d'échec d'écriture, un message est envoyé une fois sur stderr (pour ne pas masquer
    un mauvais cwd, permissions, ou moteur chargé depuis un autre répertoire).
    """
    global _PERF_WRITE_ERROR_LOGGED, _PERF_WRITE_COUNT
    try:
        fh = _get_perf_file_handle()
        if fh is None:
            return
        # `pid` est ajoute ici, au point de passage unique de toutes les lignes perf : en
        # entrainement vectorise (SubprocVecEnv), N processus appendent dans le MEME fichier et
        # `episode_number` est un compteur PAR PROCESSUS. Sans pid, l'agregation confond les
        # episodes 5 de six processus en un seul et sous-compte l'echantillon d'un facteur N.
        # os.getpid() est relu a chaque ligne, jamais mis en cache : un cache serait herite tel
        # quel par un fork et etiquetterait les lignes du fils avec le pid du pere.
        fh.write(f"{message} pid={os.getpid()}\n")
        _PERF_WRITE_COUNT += 1
        if _PERF_WRITE_COUNT % _PERF_FLUSH_INTERVAL == 0:
            fh.flush()
    except OSError as exc:
        if not _PERF_WRITE_ERROR_LOGGED:
            _PERF_WRITE_ERROR_LOGGED = True
            path = perf_timing_log_file_path()
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
    def wrapper(game_state: Dict[str, Any], unit_id: str, *args: Any, **kwargs: Any) -> Any:
        if not perf_profile_enabled(game_state):
            return fn(game_state, unit_id, *args, **kwargs)
        import cProfile

        pr = cProfile.Profile()
        pr.enable()
        try:
            return fn(game_state, unit_id, *args, **kwargs)
        finally:
            pr.disable()
            append_cprofile_dump(pr, fn.__name__, unit_id=str(unit_id))

    # `cast` justifie : `functools.wraps` conserve la signature de `fn` a l'execution, mais le
    # systeme de types ne sait pas exprimer « le wrapper a exactement le type F de l'entree » —
    # il voit un `_Wrapped[...]`. Lacune connue du typage des decorateurs generiques, pas un
    # defaut du code : le decorateur ne change ni les arguments ni la valeur de retour.
    return cast(F, wrapper)


if __name__ == "__main__":
    import json
    import sys
    from collections import defaultdict

    if len(sys.argv) < 2:
        print("Usage: python3 engine/perf_timing.py <log> [log_after]")
        sys.exit(1)

    # `ADVANCE_TIMING` a ete retire : aucun emetteur dans le moteur (`grep -r ADVANCE_TIMING`
    # ne rend que ce fichier), la ligne etait donc sautee en silence a chaque rapport.
    #
    # 4e colonne = PARENT ; 5e = PORTEE de l'inclusion. Chaque lien a ete etabli en comptant les
    # SITES D'APPEL de la fonction emettrice, pas en lisant un seul chemin — c'est la ou une
    # premiere version s'est trompee : elle declarait « inclus » ce qui ne l'est qu'une fois sur
    # trois, et le rapport invitait alors a retrancher d'une mere un cout qui n'y etait pas.
    #
    # "total"   : la fonction emettrice n'a qu'UN site d'appel, situe dans le timer de la mere.
    #   CHARGE_BUILD_POOL  : `charge_build_activation_pool` — 1 site (charge_handlers.py:1054),
    #     dans `CHARGE_PHASE_START.pool_build_s`.
    #   MOVE_COMMIT_TIMING : `_attempt_movement_to_destination` — 1 site
    #     (movement_handlers.py:4230), dans `MOVE_DEST_TIMING.attempt_s`.
    #
    # "partiel" : la fonction emettrice a PLUSIEURS sites d'appel, dont un seul dans la mere. Le
    #   temps affiche n'est donc que partiellement compris dans elle, et la difference n'est pas
    #   calculable depuis le log.
    #   WEAPON_AVAILABILITY_CHECK : `weapon_availability_check` — 5 sites (shooting_handlers.py
    #     858, 1504, 2481, 2672, 4651), seul 2481 est dans
    #     `SHOOT_ACTIVATION_START.weapon_avail_inner_s`.
    #     Symptome qui l'a revele : `perf_timing_bench_x1.log` contient 2323 lignes
    #     WEAPON_AVAILABILITY_CHECK et ZERO SHOOT_ACTIVATION_START.
    #   CHARGE_HAS_VALID_TARGET : `_has_valid_charge_target` — 3 sites (charge_handlers.py 1175,
    #     1412, 1424), seul 1175 est dans `CHARGE_BUILD_POOL.bfs_total_s`.
    #   CHARGE_REVERSE_GOAL_BFS / CHARGE_DEST_BFS : `charge_build_valid_destinations_pool` —
    #     3 sites (charge_handlers.py 2740, 3295, 4181), seul 3295 est dans
    #     `_has_valid_charge_target`.
    #
    # Un parent `None` signifie « imbrication non etablie », pas « racine prouvee ».
    #
    # Sans cet arbre, deux defauts symetriques : additionner les lignes compte deux fois le temps
    # imbrique, et un cout DEPLACE d'un evenement note vers un evenement non note se lit comme un
    # gain. D'ou l'ajout des quatre evenements intermediaires, qui etaient mesures mais absents.
    ROWS = [
        ("MOVE_DEST_TIMING",        "total_s",    [("attempt_s", "attempt")],                          None, None),
        ("MOVE_COMMIT_TIMING",      "total_s",    [("los_cache_s", "los"), ("adj_cache_s", "adj")],     "MOVE_DEST_TIMING", "total"),
        ("MOVE_POOL_BUILD",         "total_s",    [("bfs_s", "bfs")],                                   None, None),
        ("SHOOT_ACTIVATION_START",  "total_s",    [("los_cache_s", "los")],                             None, None),
        ("WEAPON_AVAILABILITY_CHECK", "total_s",  [("weapon_row_scan_s", "scan")],                      "SHOOT_ACTIVATION_START", "partiel"),
        ("CASCADE_LOOP_TOTAL",      "duration_s", [],                                                   None, None),
        ("CHARGE_PHASE_START",      "total_s",    [("pool_build_s", "pool")],                           None, None),
        ("CHARGE_BUILD_POOL",       "total_s",    [("bfs_total_s", "bfs"), ("filter_only_s", "filtre")], "CHARGE_PHASE_START", "total"),
        ("CHARGE_HAS_VALID_TARGET", "bfs_pool_s", [],                                                   "CHARGE_BUILD_POOL", "partiel"),
        ("CHARGE_REVERSE_GOAL_BFS", "total_s",    [("goal_build_s", "goal"), ("reverse_bfs_s", "bfs")], "CHARGE_HAS_VALID_TARGET", "partiel"),
        ("CHARGE_DEST_BFS",         "total_s",    [("bfs_loop_s", "bfs"), ("bfs_engagement_s", "eng")], "CHARGE_HAS_VALID_TARGET", "partiel"),
    ]

    def _row_label(event: str, present: Any) -> str:
        """Libelle indente selon les ancetres REELLEMENT presents dans le rapport.

        Indenter selon l'arbre theorique afficherait une ligne sous une mere absente du log —
        elle paraitrait alors comprise dans la ligne qui la precede, qui n'a rien a voir. On ne
        compte donc que les ancetres presents.

        Le glyphe distingue les deux portees : `└` inclusion TOTALE (retranchable de la mere),
        `≈` inclusion PARTIELLE (une part seulement, non calculable depuis le log).
        """
        parents = {e: (p, c) for e, _, _, p, c in ROWS}
        depth = 0
        current = parents.get(event, (None, None))[0]
        while current is not None:
            if current in present:
                depth += 1
            current = parents.get(current, (None, None))[0]
        if not depth:
            return event
        glyph = "└ " if parents.get(event, (None, None))[1] == "total" else "≈ "
        return "  " * depth + glyph + event

    def _orphan_note(event: str, present: Any) -> str:
        """Signale une mere declaree mais absente du rapport.

        Rendu en FIN de ligne, jamais dans le libelle : insere dans la colonne des noms, le
        marqueur decalait toute la ligne et cassait l'alignement de la colonne ms/ep — la seule
        que le lecteur est cense parcourir verticalement.
        """
        parents = {e: p for e, _, _, p, _c in ROWS}
        direct = parents.get(event)
        return f"   (⊂ {direct}, absent du rapport)" if direct is not None and direct not in present else ""

    def _parse_log(path: str) -> Dict[str, list]:
        ev: Dict[str, list] = defaultdict(list)
        with open(path) as fh:
            for line in fh:
                parts = line.strip().split()
                if not parts:
                    continue
                fields: Dict[str, Any] = {}
                for part in parts[1:]:
                    if "=" in part:
                        k, v = part.split("=", 1)
                        try:
                            fields[k] = float(v)
                        except ValueError:
                            fields[k] = v.strip("'\"")
                ev[parts[0]].append(fields)
        return ev

    def _stats(records: list, field: str):
        vals = [r[field] for r in records if field in r and isinstance(r[field], float)]
        if not vals:
            return 0, 0.0, 0.0
        return len(vals), sum(vals) / len(vals), sum(vals)

    def _fmt(s: float) -> str:
        if s >= 1.0:
            return f"{s:.1f}s"
        if s >= 0.001:
            return f"{s * 1000:.2f}ms"
        return f"{s * 1_000_000:.1f}µs"

    def _build_scores(events: Dict[str, list]) -> Dict[str, Any]:
        scores: Dict[str, Any] = {}
        total_s = 0.0
        total_calls = 0
        # Un episode est identifie par (pid, episode_number) : en vectorise, chaque processus a
        # son propre compteur d'episodes et tous ecrivent dans le meme fichier. Dedupliquer sur
        # le seul numero fusionnerait les episodes homonymes de N processus.
        keyed = [(int(r["pid"]) if isinstance(r.get("pid"), float) else None, int(r["episode"]))
                 for recs in events.values() for r in recs
                 if isinstance(r.get("episode"), float)]
        untagged = sum(1 for pid, _ in keyed if pid is None)
        undated_records = 0
        # Le DERNIER episode de chaque processus est TRONQUE : le run s'arrete au milieu, ses
        # lignes ne couvrent qu'une fraction de partie. Le garder compterait 1 episode entier au
        # denominateur pour une fraction de temps au numerateur, et tirerait ms/ep vers le bas
        # (~3 % sur un echantillon de 17 episodes — trois fois le seuil de significativite).
        # Ecarte des DEUX cotes du ratio, jamais d'un seul.
        #
        # PRIX ASSUME, car le log ne dit pas si un episode s'est termine : l'exclusion est
        # inconditionnelle, donc elle coute UN episode par processus (48 a n_envs=48), et un run
        # qui s'arrete pile sur une frontiere d'episode perd un episode complet. C'est un cout
        # d'echantillon, pas un biais — l'alternative (garder des fractions de partie) en est un.
        # Les deux cas limites sont annonces : le compte des ecartes, et le cas ou il ne reste
        # plus rien (1 episode par worker) ou la colonne ms/ep disparait au lieu de mentir.
        last_by_pid: Dict[Optional[int], int] = {}
        for pid, ep in keyed:
            if pid not in last_by_pid or ep > last_by_pid[pid]:
                last_by_pid[pid] = ep
        truncated = {(pid, ep) for pid, ep in last_by_pid.items()}

        def _complete(record: Dict[str, Any]) -> bool:
            if not isinstance(record.get("episode"), float):
                return False  # ligne non datee : inattribuable a un episode, donc hors ratio
            pid = int(record["pid"]) if isinstance(record.get("pid"), float) else None
            return (pid, int(record["episode"])) not in truncated

        retained = {(pid, ep) for pid, ep in keyed} - truncated
        eps = sorted({ep for _, ep in retained})
        pids = sorted({pid for pid, _ in keyed if pid is not None})
        # 0 si aucune ligne n'est datee d'un episode : pas de repli sur 1, qui presenterait le
        # total du log comme le cout d'UN episode et inviterait a une comparaison inter-runs.
        n_episodes = len(retained)
        # DEUX causes distinctes a n_episodes == 0, que l'affichage ne doit pas confondre :
        # soit aucune ligne n'est datee (rien a filtrer, les sommes brutes restent lisibles),
        # soit chaque processus n'a qu'UN episode et c'est son dernier — donc tronque. Dans ce
        # second cas les lignes existent et sont datees, mais aucune ne decrit un episode
        # complet : afficher un ms/ep reviendrait a comparer des fractions de partie.
        all_truncated = bool(keyed) and not retained
        for event, total_field, sub_fields, _parent, _scope in ROWS:
            if event not in events:
                continue
            # Le filtre ne s'applique qu'aux lignes datees. Sans ligne datee il n'y a pas
            # d'episode a ecarter : garder les enregistrements bruts n'annule aucun rejet.
            #
            # Et si AUCUN episode complet ne subsiste (banc court ou episodes <= n_envs, chaque
            # worker n'en ayant joue qu'un), on ne filtre pas non plus : filtrer viderait le
            # rapport ENTIER — zero ligne, `__total_s` a 0, et le mode diff etiquetant
            # « absent » des evenements pourtant presents dans le log. L'exclusion n'existe que
            # pour rendre ms/ep non biaise ; sans aucun ms/ep a produire, elle n'a plus d'objet,
            # et les sommes brutes restent la seule chose lisible. L'en-tete le dit.
            filtrer = bool(keyed) and not all_truncated
            recs = [r for r in events[event] if _complete(r)] if filtrer else events[event]
            # Certains emetteurs ecrivent `episode=?` quand `episode_number` manque du
            # game_state (shooting_handlers.py:724, combat_utils, pve_controller). Ces lignes
            # ne sont attribuables a aucun episode : elles sortent du ratio ms/ep, mais leur
            # DISPARITION du rapport serait un mensonge par omission — un evenement entier
            # pouvait s'evaporer. On les compte, et on garde la ligne visible sans ms/ep.
            # Compter UNIQUEMENT les lignes reellement non datees : `len(brut) - len(filtre)`
            # y melangeait les lignes d'episodes tronques, deja comptees ailleurs, et le
            # message annoncait des `episode=?` qui n'existaient pas.
            undated_records += sum(
                1 for r in events[event] if not isinstance(r.get("episode"), float)
            )
            sans_episode = False
            if not recs:
                # Repli reserve aux lignes REELLEMENT non datees. Y faire tomber aussi les
                # lignes d'episodes tronques les reintroduirait dans calls/avg/sum alors que
                # toutes les autres lignes du rapport les excluent — population differente
                # d'une ligne a l'autre — et l'etiquette `episode=?` accuserait un emetteur
                # qui n'a rien fait de mal. Un evenement entierement contenu dans des episodes
                # ecartes disparait donc, exactement comme la part ecartee des autres lignes ;
                # l'en-tete annonce deja le nombre d'episodes exclus.
                non_datees = [r for r in events[event]
                              if not isinstance(r.get("episode"), float)]
                if not non_datees:
                    continue
                recs = non_datees
                sans_episode = True
            n, avg, s = _stats(recs, total_field)
            if n == 0:
                continue
            total_s += s
            total_calls += n
            # sum_s au microseconde : arrondi a 2 decimales, il quantifiait par pas de 10 ms et
            # affichait `sum=0.0µs` pour un total reel de ~384 µs (CHARGE_DEST_BFS).
            entry: Dict[str, Any] = {"calls": n, "avg_s": round(avg, 6), "sum_s": round(s, 6)}
            # Cout de CET evenement par episode : c'est le chiffre a comparer entre deux runs.
            # Il est immunise contre les deux pieges de la moyenne ms/appel — une optimisation
            # qui SUPPRIME des appels fait monter le ms/appel alors que le temps reel baisse, et
            # un volume d'episodes different rend les sommes incomparables. Par evenement et non
            # en total, parce que les timers de ROWS sont IMBRIQUES (CHARGE_PHASE_START contient
            # le pool de charge, qui contient CHARGE_REVERSE_GOAL_BFS) : les additionner compte
            # deux fois le temps imbrique et affiche un gain double sur le BFS interne.
            if n_episodes and not sans_episode:
                entry["ms_per_episode"] = round(s / n_episodes * 1000, 6)
            if sans_episode:
                entry["no_episode_field"] = True
            for f, lbl in sub_fields:
                _, sub_avg, _ = _stats(recs, f)
                if sub_avg > 0:
                    entry[f"avg_{lbl}_s"] = round(sub_avg, 6)
            scores[event] = entry
        scores["__total_s"] = round(total_s, 6)
        scores["__total_calls"] = total_calls
        scores["__score_ms"] = round(total_s / total_calls * 1000, 4) if total_calls else 0.0
        scores["__n_episodes"] = n_episodes
        scores["__episodes"] = eps
        scores["__n_processes"] = len(pids)
        scores["__untagged_records"] = untagged
        scores["__undated_records"] = undated_records
        # Compte reel, y compris quand TOUS les episodes sont ecartes : le forcer a 0 dans ce
        # cas supprimait le seul signal disant qu'une exclusion avait eu lieu.
        scores["__truncated_episodes"] = len(truncated)
        scores["__all_episodes_truncated"] = all_truncated
        return scores

    def _print_scores(scores: Dict[str, Any], label: str) -> None:
        eps = scores["__episodes"]
        n_ep = scores["__n_episodes"]
        n_proc = scores["__n_processes"]
        untagged = scores["__untagged_records"]
        print(f"\n{'=' * 72}")
        print(f"PERF TIMING — {label}   (n={n_ep} épisodes sur {n_proc} processus, "
              f"numéros vus: {eps if eps else '?'})")
        if untagged:
            print(f"⚠️  {untagged} enregistrements sans champ pid (log antérieur à l'étiquetage "
                  f"par processus) : n est sous-estimé si le run était vectorisé.")
        if scores["__all_episodes_truncated"]:
            print(f"⚠️  les {scores['__truncated_episodes']} épisode(s) du log sont tous le "
                  f"DERNIER de leur processus, donc tronqués par l'arrêt du run : aucun épisode "
                  f"complet, colonne ms/ep indisponible. Relancer avec plus d'épisodes.")
        elif not n_ep:
            print("⚠️  aucune ligne datée d'un épisode : la colonne ms/ep est indisponible, "
                  "seules les sommes brutes sont affichées.")
        elif scores["__undated_records"]:
            print(f"ℹ️  {scores['__undated_records']} ligne(s) sans épisode exploitable "
                  f"(`episode=?`) exclues du ms/ep ; {scores['__truncated_episodes']} "
                  f"épisode(s) écarté(s) car dernier de leur processus (tronqué).")
        elif scores["__truncated_episodes"]:
            print(f"ℹ️  {scores['__truncated_episodes']} épisode(s) écarté(s) : le dernier de "
                  f"chaque processus est tronqué par l'arrêt du run (fraction de temps, "
                  f"épisode entier au dénominateur).")
        print(f"{'=' * 72}\n")
        for event, _, sub_fields, parent, _scope in ROWS:
            if event not in scores:
                continue
            e = scores[event]
            subs = "  ".join(
                f"{lbl}={_fmt(e[f'avg_{lbl}_s'])}/call"
                for _, lbl in sub_fields
                if f"avg_{lbl}_s" in e
            )
            # Indentation = imbrication : une ligne fille est DEJA comprise dans sa mere. Rendre
            # l'arbre visible est ce qui empeche de sommer la colonne, et ce qui montre qu'un
            # cout parti d'une ligne vers une autre n'a pas disparu.
            name = _row_label(event, scores)
            # Largeur du vide = largeur exacte de la valeur formatee ("%8.2f ms/ep" = 14) :
            # a 15, toute ligne sans ms/ep decalait d'un caractere TOUTES les colonnes suivantes.
            per_ep = (f"{e['ms_per_episode']:>8.2f} ms/ep" if "ms_per_episode" in e
                      else " " * len(f"{0.0:>8.2f} ms/ep"))
            print(f"{name:<52} {per_ep}  calls={e['calls']:<6} avg={_fmt(e['avg_s']):<10} "
                  f"sum={_fmt(e['sum_s']):<10}  {subs}{_orphan_note(event, scores)}")
        print(f"\n{'─' * 72}")
        print("À COMPARER ENTRE RUNS : la colonne ms/ep, ligne par ligne. Ne jamais additionner.")
        print("  └ = intégralement compris dans la mère (retranchable).")
        print("  ≈ = PARTIELLEMENT compris : la fonction est aussi appelée hors de la mère, et la")
        print("      part incluse n'est pas calculable depuis le log. Ne rien retrancher.")
        print("Lire l'arbre entier : un coût qui quitte une ligne pour une autre n'est pas un gain.")
        print(f"SCORE (indicatif) : {scores['__score_ms']:.4f} ms/call  "
              f"(somme brute {_fmt(scores['__total_s'])}, imbrications comprises, "
              f"sur {scores['__total_calls']} appels)")
        print(f"{'=' * 72}\n")

    def _print_diff(before: Dict[str, Any], after: Dict[str, Any], lbl_b: str, lbl_a: str) -> None:
        # Le verdict porte sur ms/ep, jamais sur avg/call : une deduplication qui supprime 40 %
        # des appels FAIT MONTER le ms/appel restant (les appels bon marche disparaissent en
        # premier) et s'afficherait en rouge alors que le run est plus rapide. Le ms/ep, lui,
        # ramene tout au meme denominateur physique : un episode joue.
        both_have_ep = bool(before["__n_episodes"]) and bool(after["__n_episodes"])
        print(f"\n{'=' * 72}")
        print(f"DIFF {'ms/épisode' if both_have_ep else 'avg/call (DÉGRADÉ)'}  "
              f"avant={lbl_b}  après={lbl_a}")
        print(f"{'=' * 72}\n")
        if not both_have_ep:
            print("⚠️  Un des deux logs n'a aucune ligne datée d'un épisode : le verdict retombe")
            print("    sur avg/call, qui MONTE quand des appels sont supprimés. À interpréter")
            print("    avec le nombre d'appels sous les yeux, pas comme un verdict de vitesse.\n")
        field = "ms_per_episode" if both_have_ep else "avg_s"
        unit = "/ep" if both_have_ep else "/call"
        print(f"{'':52} {'avant' + unit:>11}  {'après' + unit:>11}  {'%':>7}  "
              f"{'appels av→ap':>14}")
        print(f"{'─' * 72}")
        present = set(before) | set(after)
        for event, _, _, _parent, _scope in ROWS:
            name = _row_label(event, present)
            b_entry = before.get(event)
            a_entry = after.get(event)
            if b_entry is None and a_entry is None:
                continue
            if b_entry is None or a_entry is None:
                # L'EVENEMENT lui-meme manque d'un cote.
                tag = "(absent avant)" if b_entry is None else "(absent après)"
                print(f"{name:<52} {tag:>23}{_orphan_note(event, present)}")
                continue
            b = b_entry.get(field)
            a = a_entry.get(field)
            if b is None or a is None:
                # L'evenement est present des DEUX cotes, mais son ms/ep est indisponible (toutes
                # ses lignes sont `episode=?`, ou toutes tronquees). Le sauter le faisait
                # disparaitre du diff alors que le rapport a un log l'affiche — un evenement
                # entier qu'on croit inexistant. On le montre, sans verdict.
                cote = "avant" if b is None else ("après" if a is None else "les deux")
                if b is None and a is None:
                    cote = "les deux"
                print(f"{name:<52} {'ms/ep indisponible (' + cote + ')':>23}  "
                      f"{b_entry['calls']}→{a_entry['calls']}{_orphan_note(event, present)}")
                continue
            fmt = (lambda v: f"{v:.2f}ms") if both_have_ep else _fmt
            calls = f"{b_entry['calls']}→{a_entry['calls']}" if b_entry and a_entry else ""
            if not b:
                # Partir de zero n'a pas de pourcentage. `+0.0%` avec un marqueur neutre
                # affichait un cout APPARU comme un non-evenement.
                verdict, arrow0 = ("nouveau", "❌") if a else ("  =", "  ")
                print(f"{name:<52} {fmt(b):>11}  {fmt(a):>11}  {verdict:>7}  {arrow0}  "
                      f"{calls:>14}{_orphan_note(event, present)}")
                continue
            pct = (a - b) / b * 100
            arrow = "✅" if pct < -5 else ("❌" if pct > 5 else "  ")
            print(f"{name:<52} {fmt(b):>11}  {fmt(a):>11}  {pct:>+6.1f}%  {arrow}  {calls:>14}"
                  f"{_orphan_note(event, present)}")
        print(f"{'─' * 72}")
        print(f"  Épisodes retenus : {before['__n_episodes']} avant, {after['__n_episodes']} après")
        print(f"  Pas de ligne TOTAL : les timers de ROWS sont imbriqués, les additionner")
        print(f"  compterait deux fois le temps interne. Chaque ligne se lit seule.\n")

    if len(sys.argv) == 2:
        logfile = sys.argv[1]
        ev = _parse_log(logfile)
        sc = _build_scores(ev)
        _print_scores(sc, logfile)
        score_path = logfile + ".score.json"
        with open(score_path, "w") as jf:
            json.dump(sc, jf, indent=2)
        print(f"Score sauvegardé → {score_path}\n")
    else:
        ev_b = _parse_log(sys.argv[1])
        ev_a = _parse_log(sys.argv[2])
        sc_b = _build_scores(ev_b)
        sc_a = _build_scores(ev_a)
        _print_scores(sc_b, sys.argv[1])
        _print_scores(sc_a, sys.argv[2])
        _print_diff(sc_b, sc_a, sys.argv[1], sys.argv[2])
