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

**Important :** seul le processus **Python** (API Flask, bots, tests moteur) écrit ce fichier — pas le
serveur frontend (Vite / ``npm run dev``). Si tu lances uniquement ``app``, aucun ``perf_timing.log``
n’apparaîtra à la racine du dépôt.

Lignes typiques (référence) :

- ``API_ACTION_REQUEST`` — entrée ``POST /api/game/action`` : ``phase_before``, ``action``, ``unitId`` (requête
  client avant routage ; à distinguer des ``EXECUTE_SEMANTIC_TOTAL`` internes, ex. ``skip`` lors d’un
  ``end_phase``).
- ``API_POST_ACTION`` — ``engine_s`` (``execute_semantic_action`` / handlers), ``serialize_game_state_s``
  (``make_json_serializable`` + sync HP + types joueurs), ``jsonify_response_s`` (construction de la
  réponse Flask + sérialisation du corps), ``total_wall_s`` depuis le début du traitement POST.
- ``SHOOT_ACTIVATION_START`` — une activation tir (``activate_unit`` → ``shooting_unit_activation_start``) :
  ``los_cache_s`` (``build_unit_los_cache``), ``weapon_avail_s`` (``weapon_availability_check``),
  ``target_pool_s`` (``shooting_build_valid_target_pool``), ``tail_s`` (arme par défaut, JSON armes, etc.),
  ``total_s``, ``outcome`` (ex. ``success``, ``empty_pool_advance``, ``empty_pool_skip``), ``valid_targets_n``.
- ``SHOOT_PHASE_HANDLER`` — découpe ``_process_shooting_phase`` (``w40k_core``) : ``shooting_phase_start_s``
  (appel optionnel à ``shooting_phase_start`` si la phase n’était pas encore marquée initialisée),
  ``execute_action_s`` (``shooting_handlers.execute_action`` — inclut p.ex. ``activate_unit`` / tir / advance),
  ``phase_end_s`` (fusion ``shooting_phase_end`` si ``phase_complete``), ``total_handler_s``.
  Explique l’écart entre ``SHOOT_ACTIVATION_START`` et ``SEMANTIC_SEGMENTS`` / ``EXECUTE_SEMANTIC_TOTAL`` pour
  ``activate_unit`` quand ``shooting_phase_start`` a encore tourné sur la même requête.
- ``MOVE_POOL_BUILD`` — ``prep_s`` (caches occupation / EZ), ``bfs_s`` (exploration), pour le sol
  multi-hex ``footprint_zone_border_s`` (union empreintes + bordure), ``total_s``, compteurs
  ``visited`` / ``valid``. ``anchors_n`` = taille de ``valid_move_destinations_pool`` (disques UI) ;
  ``footprint_hex_n`` = taille de ``move_preview_footprint_zone`` (union hex ; vol : ``na_fly``).
- ``CHARGE_PHASE_START`` — ``setup_until_adj_s``, ``enemy_adjacent_hexes_s``, ``pool_build_s``, ``total_s`` (début phase charge).
- ``CHARGE_BUILD_POOL`` — ``get_eligible_s``, ``eligible_count`` (construction du pool d’activation).
- ``CHARGE_DEST_BFS`` — ``bfs_loop_s``, ``total_s``, ``visited_n``, ``valid_dest_n``, ``cache_hit``,
  ``early_exit`` (1 = éligibilité uniquement, arrêt au premier hex valide), ``short_circuit`` (1 si arrêt anticipé).
  ``charge_roll`` est en **pas de grille** (sous-hex) : sur plateau Boardx10, ``game_rules.charge_max_distance``
  est déjà multiplié par ``inches_to_subhex`` (ex. 12\" → 120).
  ``fp=offset`` : empreinte par offsets pré-calculés (multi-hex ×10) ; ``fp=legacy`` : ``compute_candidate_footprint``.
- Logs verbeux ``[CHARGE DEBUG]`` (positions / occupation) : ``W40K_CHARGE_DEBUG=1`` ou
  ``game_state["charge_debug_positions"]``.
- ``CHARGE_HAS_VALID_TARGET`` — ``bfs_pool_s``, ``nested_loop_s``, ``reachable_n``, ``enemy_n`` (éligibilité).
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

_PERF_ENV_TRUE = frozenset({"1", "true", "yes"})
_PERF_WRITE_ERROR_LOGGED = False


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
