#!/usr/bin/env python3
"""
Mesures de latence optionnelles (wall-clock) pour diagnostiquer les ralentissements en jeu.

Activation :
  - variable d'environnement ``W40K_PERF_TIMING=1`` (ou ``true`` / ``yes``), ou
  - ``game_state["perf_timing"] is True`` (ex. scénario / init moteur).

Audit optionnel focus fire (comparaison pools) :
  - ``W40K_FOCUS_FIRE_POOL_AUDIT=1`` ou ``focus_fire_pool_audit`` dans ``game_state``,
  - ou tout audit perf si ``W40K_PERF_TIMING`` est déjà actif.

Sortie : fichier append-only ``<racine_projet>/perf_timing.log`` (une ligne par segment).

Lignes typiques (référence) :

- ``API_ACTION_REQUEST`` — entrée ``POST /api/game/action`` : ``phase_before``, ``action``, ``unitId`` (requête
  client avant routage ; à distinguer des ``EXECUTE_SEMANTIC_TOTAL`` internes, ex. ``skip`` lors d’un
  ``end_phase``).
- ``API_POST_ACTION`` — ``engine_s`` (``execute_semantic_action`` / handlers), ``serialize_game_state_s``
  (``make_json_serializable`` + sync HP + types joueurs), ``jsonify_response_s`` (construction de la
  réponse Flask + sérialisation du corps), ``total_wall_s`` depuis le début du traitement POST.
- ``MOVE_POOL_BUILD`` — ``prep_s`` (caches occupation / EZ), ``bfs_s`` (exploration), pour le sol
  multi-hex ``footprint_zone_border_s`` (union empreintes + bordure), ``total_s``, compteurs
  ``visited`` / ``valid``.
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
from typing import Any, Dict, Optional

_PERF_ENV_TRUE = frozenset({"1", "true", "yes"})


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
    Écrit une ligne dans perf_timing.log sous la racine du dépôt (append, flush).

    Les erreurs d'écriture sont ignorées (diagnostic uniquement, comme debug.log).
    """
    try:
        import os as _os

        here = _os.path.abspath(__file__)
        engine_dir = _os.path.dirname(here)
        project_root = _os.path.dirname(engine_dir)
        path = _os.path.join(project_root, "perf_timing.log")
        with open(path, "a", encoding="utf-8", errors="replace") as f:
            f.write(message + "\n")
            f.flush()
    except OSError:
        pass
