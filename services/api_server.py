#!/usr/bin/env python3
"""
services/api_server.py - HTTP API Server for W40K Engine
Connects AI_TURN.md compliant engine to frontend board visualization
"""

import json
import os
import sqlite3
import sys
import time
import traceback
import yaml
from pathlib import Path
import hashlib
import secrets
import copy
from functools import wraps
from threading import RLock
from datetime import date, datetime
from typing import Any, Dict, Optional, Tuple
from uuid import UUID
from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

# Add parent directory (project root) to path
parent_dir = os.path.join(os.path.dirname(__file__), '..')
abs_parent = os.path.abspath(parent_dir)
sys.path.insert(0, abs_parent)

# Add engine subdirectory to path
engine_dir = os.path.join(abs_parent, 'engine')
sys.path.insert(0, engine_dir)

from engine.w40k_core import W40KEngine
from main import load_config
from shared.data_validation import require_key
from engine.combat_utils import resolve_dice_value, set_unit_coordinates
from engine.phase_handlers.shared_utils import build_units_cache, rebuild_choice_timing_index, _is_character_role
from engine.phase_handlers import command_handlers, movement_handlers, deployment_handlers
from engine.hex_utils import expand_wall_group_to_hex_list
from services.endless_duty_runtime import (
    ED_MODE_CODE,
    ED_SCENARIO_DEFAULT,
    commit_inter_wave_requisition,
    handle_endless_duty_post_action,
    initialize_endless_duty_state,
    is_endless_duty_mode,
)

AUTH_DB_PATH = os.path.join(abs_parent, "config", "users.db")
PBKDF2_ITERATIONS = 200000

BOARD_PATH_MAP = {
    "x1": "board/25x21",
    "x5": "board/180x156",
    "x10": "board/360x312",
    "x5_44x60": "board/44x60x5",
}

# Sérialise toute section qui mute W40K_BOARD_PATH (état global processus) puis
# lit/charge le board. Évite la race entre GET /api/config/board et
# POST /api/game/start sur le serveur Flask multithread (cf. footprint « invalid hex »
# intermittent quand un thread lisait le board d'un autre).
_BOARD_ENV_LOCK = RLock()

try:
    import orjson as _orjson
except ImportError:
    _orjson = None

_ORJSON_OPTS = 0
if _orjson is not None:
    _ORJSON_OPTS = getattr(_orjson, "OPT_SERIALIZE_NUMPY", 0)


def _orjson_default(obj: Any) -> Any:
    """Types non natifs orjson — évite le pré-parcours récursif ``make_json_serializable`` sur tout l’état."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="replace")
    try:
        import numpy as np
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.generic):
            return obj.item()
    except ImportError:
        pass
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    try:
        from pathlib import Path
        if isinstance(obj, Path):
            return str(obj)
    except ImportError:
        pass
    try:
        from collections import deque
        if isinstance(obj, deque):
            return list(obj)
    except ImportError:
        pass
    try:
        from engine.weapons.rules import ParsedWeaponRule
        if isinstance(obj, ParsedWeaponRule):
            if obj.parameter is not None:
                return f"{obj.rule}:{obj.parameter}"
            return obj.rule
    except ImportError:
        pass
    if hasattr(obj, "__dict__") and not isinstance(obj, type):
        return obj.__dict__
    raise TypeError(f"Object of type {type(obj).__name__!r} is not JSON serializable")


def api_json_response(payload: Dict[str, Any]) -> Response:
    """Sérialise la charge en JSON. orjson en priorité ; repli ``make_json_serializable`` si type exotique dans l’état."""
    resp, _ = api_json_response_with_size(payload)
    return resp


def _api_json_body_length(obj: Any) -> int:
    """Longueur en octets du corps JSON produit par la même chaîne que :func:`api_json_response_with_size`.

    Inclut le repli ``jsonify`` si orjson échoue même après ``make_json_serializable`` (cas où
    ``_encoded_bytes_size`` renvoyait ``-1`` alors que ``payload_bytes`` était correct).
    """
    if _orjson is not None:
        try:
            body = _orjson.dumps(obj, default=_orjson_default, option=_ORJSON_OPTS)
            return len(body)
        except (TypeError, ValueError):
            safe = make_json_serializable(obj)
            try:
                body = _orjson.dumps(safe, default=_orjson_default, option=_ORJSON_OPTS)
                return len(body)
            except (TypeError, ValueError):
                resp = jsonify(safe)
                raw = resp.get_data(as_text=False)
                if raw:
                    return len(raw)
                return int(resp.calculate_content_length() or 0)
    resp = jsonify(make_json_serializable(obj))
    raw = resp.get_data(as_text=False)
    if raw:
        return len(raw)
    return int(resp.calculate_content_length() or 0)


def api_json_response_with_size(payload: Dict[str, Any]) -> Tuple[Response, int]:
    """Comme :func:`api_json_response`, mais renvoie aussi la taille en octets du corps encodé.

    Utilisé par les endpoints instrumentés ``perf_timing`` pour logger ``payload_bytes``
    sans ré-encoder ni copier le buffer (diagnostic de ``response_encode_s``).
    """
    if _orjson is not None:
        try:
            body = _orjson.dumps(payload, default=_orjson_default, option=_ORJSON_OPTS)
            return Response(body, mimetype="application/json; charset=utf-8"), len(body)
        except (TypeError, ValueError):
            safe = make_json_serializable(payload)
            try:
                body = _orjson.dumps(safe, default=_orjson_default, option=_ORJSON_OPTS)
                return Response(body, mimetype="application/json; charset=utf-8"), len(body)
            except (TypeError, ValueError):
                resp = jsonify(safe)
                raw = resp.get_data(as_text=False)
                n = len(raw) if raw else int(resp.calculate_content_length() or 0)
                return resp, n
    resp = jsonify(make_json_serializable(payload))
    raw = resp.get_data(as_text=False)
    n = len(raw) if raw else int(resp.calculate_content_length() or 0)
    return resp, n


def _payload_breakdown_enabled() -> bool:
    """Vrai si la variable d'environnement ``W40K_PERF_PAYLOAD_BREAKDOWN`` est positionnée.

    Diagnostic ponctuel : aucune activation par défaut, aucun effet si éteint.
    """
    raw = os.environ.get("W40K_PERF_PAYLOAD_BREAKDOWN", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _encoded_bytes_size(obj: Any) -> int:
    """Taille en octets du corps JSON — même chaîne que :func:`_api_json_body_length` / la réponse HTTP.

    Inclut le repli Flask ``jsonify`` lorsque orjson échoue (sinon le breakdown affichait ``-1`` alors que
    ``payload_bytes`` était correct). Utilisé uniquement pour le diagnostic perf.
    """
    try:
        return _api_json_body_length(obj)
    except Exception:
        return -1


_PAYLOAD_BREAKDOWN_MIN_BYTES = 10_000


def _log_payload_breakdown(payload: Dict[str, Any], action_name: Optional[str]) -> None:
    """Logue une ligne ``API_PAYLOAD_BREAKDOWN`` listant les clés ≥ 10 Ko.

    Activation via ``W40K_PERF_PAYLOAD_BREAKDOWN=1``. Ne modifie aucun état jeu.

    Inclut ``orjson_full_payload`` et ``orjson_game_state`` (tailles alignées sur ``payload_bytes``,
    y compris repli ``jsonify``) ; la somme ``sum_top_level_values`` reste un proxy (sous-arbres
    partagés, etc.).
    """
    try:
        from engine.perf_timing import append_perf_timing_line
        sizes: list[tuple[str, int]] = []
        for k, v in payload.items():
            if k == "game_state":
                continue  # détaillé ci-dessous
            sizes.append((f"top.{k}", _encoded_bytes_size(v)))
        gs = payload.get("game_state")
        full_pl = _encoded_bytes_size(payload) if isinstance(payload, dict) else -1
        full_gs = _encoded_bytes_size(gs) if isinstance(gs, dict) else -1
        if isinstance(gs, dict):
            for k, v in gs.items():
                sizes.append((f"game_state.{k}", _encoded_bytes_size(v)))
        sizes.sort(key=lambda kv: kv[1], reverse=True)
        total = sum(n for _, n in sizes if n > 0)
        n_neg = sum(1 for _, n in sizes if n < 0)
        big = [(k, n) for k, n in sizes if n >= _PAYLOAD_BREAKDOWN_MIN_BYTES]
        other = total - sum(n for _, n in big)
        parts = " ".join(f"{k}={n}" for k, n in big)
        append_perf_timing_line(
            f"API_PAYLOAD_BREAKDOWN action={action_name!r} orjson_full_payload={full_pl} "
            f"orjson_game_state={full_gs} sum_top_level_values={total} n_negative_sizes={n_neg} "
            f"other_below_{_PAYLOAD_BREAKDOWN_MIN_BYTES}b={other} count_big={len(big)} count_all={len(sizes)} "
            f"big={{{parts}}}"
        )
    except Exception as exc:
        try:
            from engine.perf_timing import append_perf_timing_line
            append_perf_timing_line(f"API_PAYLOAD_BREAKDOWN error={type(exc).__name__}:{exc}")
        except Exception:
            pass


def make_json_serializable(obj, _ancestors: Optional[frozenset] = None, _path: str = "root"):
    """Recursively convert non-JSON-serializable types to serializable ones.

    _ancestors / _path: diagnostic cycle detection — raises ValueError with the path
    when a circular reference is found (never silently hides it).
    """
    if _ancestors is None:
        _ancestors = frozenset()

    try:
        import numpy as np
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.generic):
            return obj.item()
    except ImportError:
        pass

    # Handle ParsedWeaponRule objects
    try:
        from engine.weapons.rules import ParsedWeaponRule
        if isinstance(obj, ParsedWeaponRule):
            if obj.parameter is not None:
                return f"{obj.rule}:{obj.parameter}"
            return obj.rule
    except ImportError:
        pass

    if isinstance(obj, (dict, list, set, frozenset)):
        oid = id(obj)
        if oid in _ancestors:
            raise ValueError(
                f"Circular reference detected at path '{_path}': "
                f"{type(obj).__name__} id={oid} already in ancestor chain"
            )
        _ancestors = _ancestors | {oid}

    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            # Convert non-string keys to strings (JSON only supports string keys)
            if isinstance(k, tuple):
                k = ",".join(str(x) for x in k)
            elif not isinstance(k, str):
                k = str(k)
            if isinstance(v, (str, int, float, bool, type(None))):
                result[k] = v
            else:
                result[k] = make_json_serializable(v, _ancestors, f"{_path}.{k}")
        return result
    elif isinstance(obj, (list, tuple)):
        if not obj or all(isinstance(x, (str, int, float, bool, type(None))) for x in obj):
            return list(obj)
        return [make_json_serializable(item, _ancestors, f"{_path}[{i}]") for i, item in enumerate(obj)]
    elif isinstance(obj, (set, frozenset)):
        return [make_json_serializable(item, _ancestors, f"{_path}{{}}") for item in obj]
    elif hasattr(obj, '__dict__'):
        # Handle objects with __dict__ (convert to dict)
        return make_json_serializable(obj.__dict__, _ancestors, f"{_path}.__dict__")
    else:
        return obj


_GAME_STATE_EXCLUDE_KEYS = frozenset({
    "los_topology", "pathfinding_topology", "wall_edge_topology",
    "wall_hexes",
    # Table statique moteur (config/weapon_damage_table.json) — le client web n’en a pas besoin ;
    # le moteur garde ``game_state["weapon_damage_table"]`` en mémoire pour les règles.
    "weapon_damage_table",
    # Copie complète ``game_config.json`` + board — ~1 Mo JSON ; le client charge déjà la config via
    # ``useGameConfig`` (``/config/game_config.json``, ``/api/config/board``). ``gameState.config`` n’est
    # qu’un repli optionnel (ex. ``engagement_zone`` dans BoardPvp) derrière ``gameConfig``.
    "config",
    "enemy_adjacent_hexes",
    "occupied_positions",
    "los_cache",
    "valid_advance_destinations_pool",
    # Charge pool: envoyé au client dans result.valid_destinations (sélection cible), pas ici — JSON trop lourd.
    "valid_charge_destinations_pool",
    "units_already_adjacent_to_enemy",
    "reward_state",
    "move_preview_candidates",
    "shoot_preview_candidates",
    "engagement_zone_cache",
    "occupation_map",
    "_cache_instance_id",
    "_charge_dest_bfs_cache",
    "_charge_fp_offset_pair_cache",
    # Cache du champ géodésique de charge par-figurine (Étape 5.A), même motif que le move ci-dessous :
    # dicts volumineux à clés tuples, jamais consommés par l'UI → exclusion obligatoire.
    "_charge_model_field_cache",
    # Cache du champ géodésique de move par-figurine (Étape 4.1) : dicts volumineux à clés tuples,
    # jamais consommés par l'UI (le front reçoit ``destinations``). Exclusion obligatoire, sinon
    # sérialisé dans chaque réponse → payload énorme + serialize lent.
    "_move_model_field_cache",
    # Sous-ensemble dérivé des ancres pour contour UI ; le front n’utilise pas ce champ (preview = pool + footprint_zone).
    "move_preview_border",
    # Moteur / RL / debug — pas consommés par l’UI web (réduit serialize + jsonify sur chaque POST /action).
    "last_compliance_data",
    "units_cache_prev",
    "_best_weapon_cache",
    "_last_raw_action_int",
    "_last_semantic_action",
    "_last_action_debug",
    "_choice_timing_fired_events",
    "_deployment_random_mix_forced_steps",
    "_wall_set_cache",
    "_obscuring_area_sets_cache",
    "_obscuring_hex_to_area_cache",
    "_unit_los_pair_cache",
    "_shooting_phase_initialized",
    "_fight_consolidation_ctx",
    "_fight_pile_in_ctx",
    "_tutorial_force_kill_this_shot",
    "_tutorial_force_miss_this_shot",
    "console_logs",
})


_UNITS_CACHE_FRONTEND_KEYS = ("col", "row", "level", "HP_CUR", "player", "orientation", "occupied_hexes_by_model", "models_meta_by_model")

# Clés moteur internes par unité / par arme, non consommées par l'UI web (le grep frontend est vide).
# Filtrées de la réponse JSON (allège chaque POST /action : roster complet × armes), conservées côté moteur.
_UNIT_EXCLUDE_KEYS_FOR_API = frozenset({"_wdc_def_key", "_precheck_cache"})
_WEAPON_EXCLUDE_KEYS_FOR_API = frozenset({"_wdc_off_key", "_parsed_rules"})


def _slim_weapon_for_api(weapon: Any) -> Any:
    """Copie d'une arme sans les clés moteur internes (``_wdc_off_key``, ``_parsed_rules``)."""
    if not isinstance(weapon, dict):
        return weapon
    return {k: v for k, v in weapon.items() if k not in _WEAPON_EXCLUDE_KEYS_FOR_API}


def _slim_unit_for_api(unit: Any) -> Any:
    """Copie d'une unité pour la réponse API.

    Retire les caches/clés moteur de l'unité (``_wdc_def_key``, ``_precheck_cache``) et des armes
    (``RNG_WEAPONS`` / ``CC_WEAPONS``, y compris par modèle dans ``models``). Copies superficielles
    ciblées : ne mute jamais l'unité du moteur (le moteur garde ``_precheck_cache`` / clés WDC).
    """
    if not isinstance(unit, dict):
        return unit
    out = {k: v for k, v in unit.items() if k not in _UNIT_EXCLUDE_KEYS_FOR_API}
    for wkey in ("RNG_WEAPONS", "CC_WEAPONS"):
        weapons = out.get(wkey)
        if isinstance(weapons, list):
            out[wkey] = [_slim_weapon_for_api(w) for w in weapons]
    models = out.get("models")
    if isinstance(models, list):
        new_models = []
        for m in models:
            if isinstance(m, dict):
                mm = dict(m)
                for wkey in ("RNG_WEAPONS", "CC_WEAPONS"):
                    mweapons = mm.get(wkey)
                    if isinstance(mweapons, list):
                        mm[wkey] = [_slim_weapon_for_api(w) for w in mweapons]
                new_models.append(mm)
            else:
                new_models.append(m)
        out["models"] = new_models
    return out

# Ne pas omettre les boucles masque sur la base du seul hash client si le contour est petit
# (évite un aller-retour inutile et reste tolérant aux clients sans cache).
_MASK_LOOPS_OMIT_MIN_TOTAL_COORDS = 128


def _extract_mask_loops_client_hash_from_request_data(data: Any) -> Optional[str]:
    """Hash renvoyé par le dernier JSON ``move_preview_footprint_mask_loops_hash`` (réponse API)."""
    if not isinstance(data, dict):
        return None
    h = data.get("move_preview_mask_loops_client_hash")
    if isinstance(h, str) and len(h) > 0:
        return h
    return None


def _count_mask_loop_coord_values(loops: Any) -> int:
    """Nombre total de coordonnées scalaires (x et y) dans toutes les boucles."""
    if not isinstance(loops, list):
        return 0
    n = 0
    for loop in loops:
        if not isinstance(loop, list) or len(loop) == 0:
            continue
        if isinstance(loop[0], (int, float)):
            n += len(loop)
        else:
            for pt in loop:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    n += 2
    return n


def _mask_loops_stable_hash(loops: Any) -> Optional[str]:
    """Empreinte stable du contour (même géométrie → même digest) pour cache client / omission JSON."""
    if not isinstance(loops, list) or len(loops) == 0:
        return None
    parts: list[bytes] = []
    for loop in loops:
        if not isinstance(loop, list):
            continue
        flat: list[float] = []
        if len(loop) > 0 and isinstance(loop[0], (int, float)):
            for v in loop:
                if isinstance(v, (int, float)):
                    flat.append(float(v))
        else:
            for pt in loop:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    flat.append(float(pt[0]))
                    flat.append(float(pt[1]))
        if len(flat) < 6:
            continue
        s = ",".join(f"{x:.6f}" for x in flat)
        parts.append(s.encode("utf-8"))
    if not parts:
        return None
    digest = hashlib.sha256()
    for b in parts:
        digest.update(b)
        digest.update(b"|")
    return digest.hexdigest()


def _compact_mask_loops_for_api_json(loops: Any) -> list[list[float]]:
    """Format compact : une boucle = ``[x0,y0,x1,y1,...]`` (moins de crochets que ``[[[x,y],...]]``)."""
    out: list[list[float]] = []
    if not isinstance(loops, list):
        return out
    for loop in loops:
        if not isinstance(loop, list):
            continue
        flat: list[float] = []
        if len(loop) > 0 and isinstance(loop[0], (int, float)):
            for v in loop:
                if isinstance(v, (int, float)):
                    flat.append(float(v))
        else:
            for pt in loop:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    flat.append(float(pt[0]))
                    flat.append(float(pt[1]))
        if len(flat) >= 6:
            out.append(flat)
    return out


def _apply_move_preview_mask_loops_transport_to_gs(
    gs: Dict[str, Any],
    *,
    mask_loops_client_hash: Optional[str],
) -> None:
    """Remplace les boucles par un format compact ; peut omettre le tableau si le client renvoie le même hash."""
    raw = gs.get("move_preview_footprint_mask_loops")
    if raw in (None, [], ()):
        gs.pop("move_preview_footprint_mask_loops_hash", None)
        gs.pop("move_preview_footprint_mask_loops_unchanged", None)
        return
    h = _mask_loops_stable_hash(raw)
    if h is None:
        return
    gs["move_preview_footprint_mask_loops_hash"] = h
    coord_n = _count_mask_loop_coord_values(raw)
    if (
        mask_loops_client_hash is not None
        and mask_loops_client_hash == h
        and coord_n >= _MASK_LOOPS_OMIT_MIN_TOTAL_COORDS
    ):
        gs.pop("move_preview_footprint_mask_loops", None)
        gs["move_preview_footprint_mask_loops_unchanged"] = True
    else:
        gs["move_preview_footprint_mask_loops"] = _compact_mask_loops_for_api_json(raw)
        gs.pop("move_preview_footprint_mask_loops_unchanged", None)


def _exclude_game_state_key_for_api_json(key: str) -> bool:
    """Clés dérivées / caches par joueur — volumineuses, non consommées par le client web.

    Le moteur les conserve dans ``engine.game_state`` ; elles ne sont pas nécessaires au rendu
    plateau (voir absence de références dans ``frontend/src``). Préfixes pour couvrir tout
    ``enemy_adjacent_*_player_<id>`` (tests inclus, ex. joueur 0).
    """
    if key.startswith("enemy_adjacent_hexes_player_"):
        return True
    if key.startswith("enemy_adjacent_counts_player_"):
        return True
    return False


def _game_state_for_json(
    engine_instance,
    *,
    for_post_action: bool = False,
    mask_loops_client_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """Return game_state dict with internal/heavy fields excluded.

    Strips topology arrays, large sets (wall_hexes, occupied_positions,
    enemy_adjacent_hexes, los_cache), champs moteur inutiles au client, et
    ``move_preview_border`` (non consommé par l’UI ; la preview move repose sur
    ``valid_move_destinations_pool`` et ``move_preview_footprint_zone`` / span).
    Si ``move_preview_footprint_mask_loops`` est présent (contours monde), supprime
    ``move_preview_footprint_zone`` du JSON (évite des milliers de couples hex).
    Si ``valid_move_destinations_pool`` est non vide, supprime ``preview_hexes`` (alias du même pool).
    Trims units_cache to (col, row, HP_CUR, player, orientation).
    Exclut aussi caches internes, snapshots ``units_cache_prev``, ``last_compliance_data``,
    ``console_logs``, la table statique ``weapon_damage_table`` (moteur uniquement), la config
    complète ``config`` (déjà chargée côté client), et les caches d’adjacence par joueur
    ``enemy_adjacent_hexes_player_*`` / ``enemy_adjacent_counts_player_*``
    (voir ``_GAME_STATE_EXCLUDE_KEYS`` et ``_exclude_game_state_key_for_api_json``).

    Si ``for_post_action`` est True (réponses ``POST /api/game/action``, ``/api/game/ai-turn``) :
    omet ``objectives`` du JSON — le client conserve la liste issue du ``/start`` ou du premier état
    complet (voir ``mergeGameStatePreservingOmittedObjectives`` côté React). Les objectifs de
    scénario ne sont pas modifiés en cours de partie dans le moteur actuel.

    ``mask_loops_client_hash`` : hash renvoyé par le client (dernier ``move_preview_footprint_mask_loops_hash``).
    Si identique au contour courant et contour volumineux, les boucles sont omises du JSON et
    ``move_preview_footprint_mask_loops_unchanged`` vaut True (le client réutilise son cache).
    """
    # Rule 13.09: keep unit['hidden'] fresh in every phase (not just shooting), so the
    # hidden badge stays accurate as figs move. Cheap: only hideable units, footprint vs terrain.
    from engine.phase_handlers.shooting_handlers import compute_hidden_statuses
    compute_hidden_statuses(engine_instance.game_state)

    # Objective control (Rule 14.02): control is determined at the END of each phase and turn,
    # not continuously. Detect a phase/turn boundary by comparing to the last serialized state;
    # only when a boundary was just crossed do we (re)evaluate the persistent
    # ``objective_controllers`` (driven by game_config['objective_control_check']). At battle
    # start no boundary has yet been crossed → no objective is controlled (neutral), per 14.02.
    _oc_gs = engine_instance.game_state
    _oc_phase = _oc_gs.get("phase")
    _oc_turn = _oc_gs.get("turn")
    _oc_last_phase = getattr(engine_instance, "_oc_display_last_phase", None)
    _oc_last_turn = getattr(engine_instance, "_oc_display_last_turn", None)
    if _oc_last_phase is not None and (_oc_phase != _oc_last_phase or _oc_turn != _oc_last_turn):
        engine_instance.state_manager.run_objective_control_checkpoint(
            _oc_gs, _oc_last_phase, _oc_phase, turn_changed=(_oc_turn != _oc_last_turn)
        )
    engine_instance._oc_display_last_phase = _oc_phase
    engine_instance._oc_display_last_turn = _oc_turn

    had_engine_mask_loops = bool(engine_instance.game_state.get("move_preview_footprint_mask_loops"))
    gs = {
        k: v for k, v in engine_instance.game_state.items()
        if k not in _GAME_STATE_EXCLUDE_KEYS and not _exclude_game_state_key_for_api_json(k)
    }
    raw_cache = engine_instance.game_state.get("units_cache")
    if raw_cache is not None:
        models_cache = engine_instance.game_state.get("models_cache") or {}
        squad_models = engine_instance.game_state.get("squad_models") or {}
        trimmed_cache: Dict[str, Any] = {}
        for uid, entry in raw_cache.items():
            slim = {fk: entry[fk] for fk in _UNITS_CACHE_FRONTEND_KEYS if fk in entry}
            # PV live par figurine (source models_cache, maj par update_model_hp) +
            # flag character (role support/leader) : consommé par le rendu des barres HP.
            mids = squad_models.get(uid, [])
            if mids:
                slim["models_hp_by_model"] = {
                    mid: {
                        "HP_CUR": int(models_cache[mid]["HP_CUR"]),
                        "HP_MAX": int(models_cache[mid]["HP_MAX"]),
                        "is_character": _is_character_role(models_cache[mid].get("role")),
                    }
                    for mid in mids
                    if mid in models_cache
                }
                # Niveau vertical par figurine (étages) : requis pour le rendu mono-niveau
                # + ghost (une escouade peut être répartie sur plusieurs étages, §2.5).
                slim["level_by_model"] = {
                    mid: int(models_cache[mid]["level"])
                    for mid in mids
                    if mid in models_cache and "level" in models_cache[mid]
                }
            trimmed_cache[uid] = slim
        gs["units_cache"] = trimmed_cache
    raw_units = engine_instance.game_state.get("units")
    if isinstance(raw_units, list):
        gs["units"] = [_slim_unit_for_api(u) for u in raw_units]
    _apply_move_preview_mask_loops_transport_to_gs(gs, mask_loops_client_hash=mask_loops_client_hash)
    # Preview move : boucles masque monde — si présentes côté moteur, ne pas envoyer ``move_preview_footprint_zone``
    # (milliers de couples ; même silhouette via les polygones).
    if had_engine_mask_loops:
        gs.pop("move_preview_footprint_zone", None)
    # ``preview_hexes`` est un alias miroir de ``valid_move_destinations_pool`` côté moteur (phase move) :
    # ne pas dupliquer des milliers de couples dans le JSON (le client lit le pool en priorité).
    _pool = gs.get("valid_move_destinations_pool")
    if isinstance(_pool, list) and len(_pool) > 0:
        gs.pop("preview_hexes", None)
    if for_post_action:
        gs.pop("objectives", None)
    return gs


def _slim_execute_action_result_for_api(
    result: Any,
    action: Optional[Dict[str, Any]],
) -> Any:
    """Sur ``activate_unit`` (phase move, joueur humain), retire la duplication du pool dans ``result``.

    ``valid_move_destinations_pool`` / ``preview_hexes`` / masques sont déjà dans ``game_state`` ;
    le front lit le pool depuis ``game_state`` en priorité (voir ``useEngineAPI``). On conserve
    ``result`` inchangé pour l’entraînement (gym) où ``waiting_for_player`` est False.
    """
    if not isinstance(result, dict) or not isinstance(action, dict):
        return result
    if action.get("action") != "activate_unit":
        return result
    if not result.get("unit_activated") or result.get("waiting_for_player") is not True:
        return result
    return {k: v for k, v in result.items() if k not in {"valid_destinations", "preview_data"}}


def _sync_units_hp_from_cache(serializable_state: Dict[str, Any], game_state: Dict[str, Any]) -> None:
    """
    Ensure HP_CUR in serialized units reflects units_cache (single source of truth).
    
    Dead units are absent from units_cache and must appear with HP_CUR=0 in the response.
    """
    units_cache = require_key(game_state, "units_cache")
    units = require_key(serializable_state, "units")
    
    for unit in units:
        unit_id = str(require_key(unit, "id"))
        cache_entry = units_cache.get(unit_id)
        if cache_entry is None:
            unit["HP_CUR"] = 0
            continue
        unit["HP_CUR"] = require_key(cache_entry, "HP_CUR")


def _attach_shoot_visible_cells(serializable_state: Dict[str, Any], game_state: Dict[str, Any]) -> None:
    """Attache les cellules visibles par cible (règle 06.01/13.10) sur le tireur actif.

    Consommé par la preview frontend pour peindre les cases visibles des cibles ciblables
    par-dessus le cône WASM → cohérence blink↔visuel (une cible qui blinke a toujours ses
    cases peintes). Tireur de phase de tir fixe → calcul une fois par action, borné aux
    seules cibles valides (pas de scan plateau). Miroir du champ move-preview
    ``visible_cells_by_target``.
    """
    active_id = game_state.get("active_shooting_unit")
    if active_id is None:
        return
    active_id_str = str(active_id)
    from engine.phase_handlers.shooting_handlers import (
        build_visible_cells_by_target,
        _get_unit_by_id,
    )
    shooter = _get_unit_by_id(game_state, active_id_str)
    if shooter is None:
        return
    valid_targets = shooter.get("valid_target_pool")
    if not isinstance(valid_targets, list) or not valid_targets:
        return
    vis_by_target = build_visible_cells_by_target(game_state, shooter, valid_targets)
    for unit in require_key(serializable_state, "units"):
        if str(require_key(unit, "id")) == active_id_str:
            unit["visible_cells_by_target"] = vis_by_target
            break


def _build_player_types(is_ai_enabled: bool, mode_code: str) -> Dict[str, str]:
    """
    Build player type mapping for frontend orchestration.

    Player 1 is always human in current game modes.
    Player 2 is AI only for AI-enabled modes.
    """
    return {
        "1": "human",
        "2": "ai" if is_ai_enabled else "human",
    }


def _attach_player_types(serializable_state: Dict[str, Any], engine_instance: W40KEngine) -> None:
    """
    Ensure player_types is present in both engine.game_state and serialized response.
    """
    current_mode_code = getattr(engine_instance, "current_mode_code", None)
    if not isinstance(current_mode_code, str) or not current_mode_code:
        raise ValueError("engine.current_mode_code is required to derive player_types")
    if current_mode_code not in {"pvp", "pvp_test", "pve", "pve_test", ED_MODE_CODE}:
        raise ValueError(f"Unsupported current_mode_code for player_types: {current_mode_code}")
    # Strict mode gate: only PvE modes allow AI orchestration for player 2.
    is_ai_enabled = current_mode_code in {"pve", "pve_test", ED_MODE_CODE}
    player_types = _build_player_types(is_ai_enabled, current_mode_code)
    engine_instance.game_state["player_types"] = player_types
    engine_instance.game_state["current_mode_code"] = current_mode_code
    serializable_state["player_types"] = player_types
    serializable_state["current_mode_code"] = current_mode_code


def _get_auth_db_connection() -> sqlite3.Connection:
    """
    Return a sqlite connection configured for named column access.
    """
    os.makedirs(os.path.dirname(AUTH_DB_PATH), exist_ok=True)
    connection = sqlite3.connect(AUTH_DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _hash_password(password: str) -> str:
    """
    Hash password with PBKDF2-HMAC-SHA256.
    """
    if not isinstance(password, str) or not password:
        raise ValueError("password is required and must be a non-empty string")
    salt = secrets.token_bytes(16)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${derived_key.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    """
    Verify password against PBKDF2 hash format.
    """
    if not isinstance(password, str) or not password:
        return False
    if not isinstance(stored_hash, str) or not stored_hash:
        raise ValueError("stored_hash must be a non-empty string")

    parts = stored_hash.split("$")
    if len(parts) != 4:
        raise ValueError("Invalid password hash format in database")
    algorithm, iterations_str, salt_hex, hash_hex = parts
    if algorithm != "pbkdf2_sha256":
        raise ValueError(f"Unsupported password hash algorithm: {algorithm}")
    iterations = int(iterations_str)
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(hash_hex)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return secrets.compare_digest(candidate, expected)


def _extract_bearer_token() -> str:
    """
    Extract Bearer token from Authorization header.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise ValueError("Missing Authorization header")
    parts = auth_header.strip().split(" ")
    if len(parts) != 2 or parts[0] != "Bearer" or not parts[1]:
        raise ValueError("Invalid Authorization header format. Expected: Bearer <token>")
    return parts[1]


def _resolve_permissions_for_profile(connection: sqlite3.Connection, profile_id: int) -> Dict[str, Any]:
    """
    Resolve allowed game modes and options for a profile.
    """
    modes_rows = connection.execute(
        """
        SELECT gm.code
        FROM profile_game_modes pgm
        JOIN game_modes gm ON gm.id = pgm.game_mode_id
        WHERE pgm.profile_id = ?
        ORDER BY gm.code
        """,
        (profile_id,),
    ).fetchall()
    option_rows = connection.execute(
        """
        SELECT o.code, po.enabled
        FROM profile_options po
        JOIN options o ON o.id = po.option_id
        WHERE po.profile_id = ?
        ORDER BY o.code
        """,
        (profile_id,),
    ).fetchall()

    options_map: Dict[str, bool] = {}
    for row in option_rows:
        option_code = row["code"]
        options_map[option_code] = bool(row["enabled"])

    return {
        "game_modes": [row["code"] for row in modes_rows],
        "options": options_map,
    }


def _get_authenticated_user_or_response():
    """
    Validate bearer session token and return current user row.
    """
    try:
        token = _extract_bearer_token()
    except ValueError as auth_error:
        return None, (jsonify({"success": False, "error": str(auth_error)}), 401)

    connection = _get_auth_db_connection()
    try:
        row = connection.execute(
            """
            SELECT u.id AS user_id, u.login AS login, p.id AS profile_id, p.code AS profile_code,
                   COALESCE(u.tutorial_completed, 0) AS tutorial_completed
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            JOIN profiles p ON p.id = u.profile_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        return None, (jsonify({"success": False, "error": "Invalid or expired session"}), 401)
    return row, None


def _is_mode_allowed(mode: str, permissions: Dict[str, Any]) -> bool:
    """
    Check if requested mode is present in allowed game modes.
    """
    allowed_modes = require_key(permissions, "game_modes")
    if not isinstance(allowed_modes, list):
        raise TypeError("permissions.game_modes must be a list")
    if mode in allowed_modes:
        return True
    # Backward compatibility for stale permissions snapshots.
    if mode == "pvp_test" and "test" in allowed_modes:
        return True
    if mode == "pve_test" and "test" in allowed_modes:
        return True
    # Backward compatibility: if profile has PvE permission but not yet the ED row,
    # allow Endless Duty in the same capability family.
    if mode == ED_MODE_CODE and "pve" in allowed_modes:
        return True
    return False


def initialize_auth_db() -> None:
    """
    Create auth tables and seed default profile permissions.
    """
    connection = _get_auth_db_connection()
    try:
        cursor = connection.cursor()
        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                profile_id INTEGER NOT NULL REFERENCES profiles(id)
            );

            CREATE TABLE IF NOT EXISTS game_modes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS profile_game_modes (
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                game_mode_id INTEGER NOT NULL REFERENCES game_modes(id) ON DELETE CASCADE,
                UNIQUE(profile_id, game_mode_id)
            );

            CREATE TABLE IF NOT EXISTS profile_options (
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                option_id INTEGER NOT NULL REFERENCES options(id) ON DELETE CASCADE,
                enabled INTEGER NOT NULL,
                UNIQUE(profile_id, option_id)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL
            );
            """
        )
        # Migration: add tutorial_completed for first-login → tutorial flow
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN tutorial_completed INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Column already exists

        cursor.execute(
            "INSERT OR IGNORE INTO profiles (code, label) VALUES (?, ?)",
            ("base", "Joueur Base"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profiles (code, label) VALUES (?, ?)",
            ("admin", "Administrateur"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO game_modes (code, label) VALUES (?, ?)",
            ("pve", "Player vs Environment"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO game_modes (code, label) VALUES (?, ?)",
            ("pve_test", "Player vs Environment Test"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO game_modes (code, label) VALUES (?, ?)",
            ("pvp", "Player vs Player"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO game_modes (code, label) VALUES (?, ?)",
            ("pvp_test", "Player vs Player Test"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO game_modes (code, label) VALUES (?, ?)",
            ("tutorial", "Tutoriel"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO game_modes (code, label) VALUES (?, ?)",
            (ED_MODE_CODE, "Endless Duty"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO options (code, label) VALUES (?, ?)",
            ("show_advance_warning", "Afficher avertissement mode advance"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO options (code, label) VALUES (?, ?)",
            ("auto_weapon_selection", "Selection automatique d'arme"),
        )

        profile_row = cursor.execute(
            "SELECT id FROM profiles WHERE code = ?",
            ("base",),
        ).fetchone()
        if profile_row is None:
            raise RuntimeError("Failed to seed required profile 'base'")
        profile_id = profile_row["id"]
        admin_profile_row = cursor.execute(
            "SELECT id FROM profiles WHERE code = ?",
            ("admin",),
        ).fetchone()
        if admin_profile_row is None:
            raise RuntimeError("Failed to seed required profile 'admin'")
        admin_profile_id = admin_profile_row["id"]

        pve_row = cursor.execute(
            "SELECT id FROM game_modes WHERE code = ?",
            ("pve",),
        ).fetchone()
        pve_test_row = cursor.execute(
            "SELECT id FROM game_modes WHERE code = ?",
            ("pve_test",),
        ).fetchone()
        pvp_row = cursor.execute(
            "SELECT id FROM game_modes WHERE code = ?",
            ("pvp",),
        ).fetchone()
        pvp_test_row = cursor.execute(
            "SELECT id FROM game_modes WHERE code = ?",
            ("pvp_test",),
        ).fetchone()
        tutorial_row = cursor.execute(
            "SELECT id FROM game_modes WHERE code = ?",
            ("tutorial",),
        ).fetchone()
        endless_duty_row = cursor.execute(
            "SELECT id FROM game_modes WHERE code = ?",
            (ED_MODE_CODE,),
        ).fetchone()
        if (
            pve_row is None
            or pve_test_row is None
            or pvp_row is None
            or pvp_test_row is None
            or tutorial_row is None
            or endless_duty_row is None
        ):
            raise RuntimeError("Failed to seed required game modes")

        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (profile_id, pve_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (profile_id, pve_test_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (profile_id, pvp_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (profile_id, pvp_test_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (profile_id, tutorial_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (profile_id, endless_duty_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (admin_profile_id, pve_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (admin_profile_id, pve_test_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (admin_profile_id, pvp_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (admin_profile_id, pvp_test_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (admin_profile_id, tutorial_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (admin_profile_id, endless_duty_row["id"]),
        )

        warning_option_row = cursor.execute(
            "SELECT id FROM options WHERE code = ?",
            ("show_advance_warning",),
        ).fetchone()
        auto_weapon_row = cursor.execute(
            "SELECT id FROM options WHERE code = ?",
            ("auto_weapon_selection",),
        ).fetchone()
        if warning_option_row is None or auto_weapon_row is None:
            raise RuntimeError("Failed to seed required option definitions")

        cursor.execute(
            """
            INSERT OR REPLACE INTO profile_options (profile_id, option_id, enabled)
            VALUES (?, ?, 1)
            """,
            (profile_id, warning_option_row["id"]),
        )
        cursor.execute(
            """
            INSERT OR REPLACE INTO profile_options (profile_id, option_id, enabled)
            VALUES (?, ?, 1)
            """,
            (profile_id, auto_weapon_row["id"]),
        )
        cursor.execute(
            """
            INSERT OR REPLACE INTO profile_options (profile_id, option_id, enabled)
            VALUES (?, ?, 1)
            """,
            (admin_profile_id, warning_option_row["id"]),
        )
        cursor.execute(
            """
            INSERT OR REPLACE INTO profile_options (profile_id, option_id, enabled)
            VALUES (?, ?, 1)
            """,
            (admin_profile_id, auto_weapon_row["id"]),
        )

        connection.commit()
    finally:
        connection.close()

# Initialize Flask app
app = Flask(__name__)
CORS(
    app,
    expose_headers=["Server-Timing", "X-W40k-Payload-Bytes"],
)  # Server-Timing + taille payload (perf) lisibles en JS si W40K_PERF_TIMING=1


@app.errorhandler(Exception)
def handle_uncaught_exception(error: Exception):
    """Centralise toute exception non gérée : log du traceback complet côté
    serveur + réponse JSON explicite (type + message + traceback). Remplace les
    anciens `except Exception -> jsonify(str(e)), 500` qui masquaient la cause."""
    # Laisser passer les erreurs HTTP volontaires (abort(404), 405, etc.).
    if isinstance(error, HTTPException):
        return error
    tb = traceback.format_exc()
    print(f"🔥 UNCAUGHT EXCEPTION ({type(error).__name__}): {error}")
    print(tb)
    return jsonify({
        "success": False,
        "error": str(error),
        "error_type": type(error).__name__,
        "traceback": tb,
    }), 500


# Minimal Flask logging for debugging when needed
flask_request_logs = []

initialize_auth_db()

# Global engine instance
engine: Optional[W40KEngine] = None
_ENGINE_STATE_LOCK = RLock()


def with_engine_state_lock(fn):
    """Serialize engine/game_state access across concurrent HTTP requests."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with _ENGINE_STATE_LOCK:
            return fn(*args, **kwargs)

    return wrapper


def _perf_timing_boot_if_enabled() -> None:
    """Si W40K_PERF_TIMING=1, crée tout de suite une ligne dans perf_timing.log (vérif env + chemin)."""
    try:
        from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

        if perf_timing_enabled(None):
            append_perf_timing_line(
                f"PERF_TIMING_BOOT api_server_import pid={os.getpid()} cwd={os.getcwd()}"
            )
    except Exception as exc:
        print(f"[perf_timing] boot failed: {exc}", file=sys.stderr)


_perf_timing_boot_if_enabled()

def get_agents_from_scenario(scenario_file: str, unit_registry) -> set:
    """Extract unique agent keys from scenario units.
    
    Args:
        scenario_file: Path to scenario.json
        unit_registry: UnitRegistry instance for unit_type -> agent_key mapping
        
    Returns:
        Set of unique agent keys found in scenario
        
    Raises:
        FileNotFoundError: If scenario file doesn't exist
        ValueError: If scenario format invalid or unit type not found in registry
    """
    import json
    
    if not os.path.exists(scenario_file):
        raise FileNotFoundError(f"Scenario file not found: {scenario_file}")
    
    try:
        with open(scenario_file, 'r') as f:
            scenario_data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in scenario file: {e}")
    
    if not isinstance(scenario_data, dict) or "units" not in scenario_data:
        raise ValueError(f"Invalid scenario format: must have 'units' array")
    
    units = scenario_data["units"]
    if not units:
        raise ValueError("Scenario contains no units")
    
    agent_keys = set()
    for unit in units:
        if "unit_type" not in unit:
            raise ValueError(f"Unit missing 'unit_type' field: {unit}")
        
        unit_type = unit["unit_type"]
        try:
            agent_key = unit_registry.get_model_key(unit_type)
            agent_keys.add(agent_key)
        except ValueError as e:
            raise ValueError(
                f"Failed to determine agent for unit type '{unit_type}': {e}\n"
                f"Ensure unit is defined in frontend/src/roster/ with proper agent properties"
            )
    
    return agent_keys

def initialize_engine(scenario_file: Optional[str] = None):
    """Initialize the W40K engine for PvP mode with configurable scenario."""
    global engine
    original_cwd: Optional[str] = None
    try:
        # Change to project root directory for config loading
        original_cwd = os.getcwd()
        project_root = os.path.join(os.path.dirname(__file__), '..')
        os.chdir(os.path.abspath(project_root))
        
        # Define scenario file path for PvP mode (default if not provided)
        if scenario_file is None:
            from config_loader import get_config_loader as _gcl
            _cfg = _gcl().load_config("config", force_reload=False)
            board_path = _cfg.get("defaults", {}).get("test_board", "x5")
            scenario_file = os.path.join("config", BOARD_PATH_MAP[board_path], "scenario", "scenario_pvp.json")
        elif not isinstance(scenario_file, str):
            raise ValueError(f"scenario_file must be a string if provided (got {type(scenario_file).__name__})")

        # Verify scenario file exists - no fallback
        if not os.path.exists(scenario_file):
            raise FileNotFoundError(
                f"Game scenario file not found: {scenario_file}\n"
                f"This file is required for the API server.\n"
                f"Training scenarios are in config/agents/<agent>/scenarios/"
            )

        # Initialize unit registry
        from ai.unit_registry import UnitRegistry
        unit_registry = UnitRegistry()
        
        # Load agent-specific configs based on scenario units
        from config_loader import get_config_loader
        config_loader = get_config_loader()
        board_config = config_loader.get_board_config()
        game_config = config_loader.get_game_config()
        
        from engine.game_state import GameStateManager
        scenario_manager = GameStateManager({"board": board_config}, unit_registry)
        scenario_result = scenario_manager.load_units_from_scenario(scenario_file, unit_registry)
        scenario_units = require_key(scenario_result, "units")
        scenario_primary_objective_ids = scenario_result.get("primary_objectives")
        scenario_primary_objective_id = scenario_result.get("primary_objective")
        scenario_wall_hexes = scenario_result.get("wall_hexes")
        scenario_wall_ref = scenario_result.get("wall_ref")
        scenario_objectives = scenario_result.get("objectives")
        scenario_deployment_type = scenario_result.get("deployment_type")
        scenario_deployment_type_by_player = scenario_result.get("deployment_type_by_player")
        scenario_deployment_zone = scenario_result.get("deployment_zone")
        scenario_deployment_pools = scenario_result.get("deployment_pools")
        
        if scenario_primary_objective_ids is not None:
            if not isinstance(scenario_primary_objective_ids, list):
                raise TypeError("primary_objectives must be a list of objective IDs")
            if not scenario_primary_objective_ids:
                raise ValueError("primary_objectives list cannot be empty")
            primary_objective_config = [
                config_loader.load_primary_objective_config(obj_id)
                for obj_id in scenario_primary_objective_ids
            ]
        elif scenario_primary_objective_id is not None:
            primary_objective_config = config_loader.load_primary_objective_config(
                scenario_primary_objective_id
            )
        else:
            primary_objective_config = None
        
        config = {
            "board": board_config,
            "game_rules": require_key(game_config, "game_rules"),
            "objective_control_check": require_key(game_config, "objective_control_check"),
            "move": require_key(game_config, "move"),
            "charge": require_key(game_config, "charge"),
            "units": scenario_units,
            "primary_objective": primary_objective_config,
            "scenario_wall_hexes": scenario_wall_hexes,
            "scenario_wall_ref": scenario_wall_ref,
            "scenario_objectives": scenario_objectives,
            "scenario_terrain_areas": scenario_result.get("terrain_areas"),
            "deployment_type": scenario_deployment_type,
            "deployment_type_by_player": scenario_deployment_type_by_player,
            "deployment_zone": scenario_deployment_zone,
            "deployment_pools": scenario_deployment_pools,
            "tutorial_fight_no_death_unit_ids": scenario_result.get(
                "tutorial_fight_no_death_unit_ids"
            ),
        }
        
        # Determine which agents are in the scenario
        agent_keys = get_agents_from_scenario(scenario_file, unit_registry)
        if not agent_keys:
            raise ValueError("No agents found in scenario")
        
        print(f"DEBUG: Found {len(agent_keys)} unique agent(s) in scenario: {agent_keys}")
        
        # For PvP mode, we need configs for all agents
        # Load configs for each agent and merge them
        all_rewards_configs = {}
        all_training_configs = {}
        
        for agent_key in agent_keys:
            try:
                agent_rewards = config_loader.load_agent_rewards_config(agent_key)
                # Load entire config file (contains "default" and "debug" phases)
                agent_training_full = config_loader.load_agent_training_config(agent_key)

                # Store agent-specific configs
                all_rewards_configs[agent_key] = agent_rewards
                all_training_configs[agent_key] = agent_training_full  # Store full config for engine
                
                print(f"✅ Loaded configs for agent: {agent_key}")
            except FileNotFoundError as e:
                raise FileNotFoundError(
                    f"Missing config for agent '{agent_key}' found in scenario.\n{e}\n"
                    f"Create required files:\n"
                    f"  - config/agents/{agent_key}/{agent_key}_rewards_config.json\n"
                    f"  - config/agents/{agent_key}/{agent_key}_training_config.json"
                )
        
        # Use first agent's training config for observation params (all agents should match)
        first_agent = list(agent_keys)[0]
        training_config_default = config_loader.load_agent_training_config(first_agent, "x5_new")
        
        # Add configs to main config
        config["rewards_configs"] = all_rewards_configs  # Multi-agent support
        config["training_configs"] = all_training_configs  # Multi-agent support
        config["agent_keys"] = list(agent_keys)  # Track which agents are active
        config["controlled_agent"] = first_agent  # Required for reward mapping in handlers
        config["controlled_agent"] = first_agent  # Required for reward mapping in handlers
        
        # CRITICAL FIX: Add observation_params from training_config "default" phase
        obs_params = training_config_default.get("observation_params", {})
        
        # Validation stricte: obs_size DOIT être présent
        if "obs_size" not in obs_params:
            raise KeyError(
                f"training_config missing required 'obs_size' in observation_params. "
                f"Must be defined in training_config.json 'default' phase. "
                f"Config: {first_agent}"
            )
        
        config["observation_params"] = obs_params  # Inclut obs_size validé

        # Create engine with proper parameters
        engine = W40KEngine(
            config=config,
            rewards_config="default",
            training_config_name="x5_new",
            controlled_agent=first_agent,
            active_agents=None,
            scenario_file=scenario_file,
            unit_registry=unit_registry,
            quiet=True,
            debug_mode=os.environ.get('W40K_DEBUG', 'false').lower() == 'true'
        )
        
        # CRITICAL FIX: Add rewards_configs to game_state after engine creation
        engine.game_state["rewards_configs"] = all_rewards_configs
        engine.game_state["agent_keys"] = list(agent_keys)
        
        # Restore original working directory
        os.chdir(original_cwd)
        
        print("✅ W40K Engine initialized successfully (PvP mode)")
        return True
    except Exception:
        # Restore original working directory on error
        if original_cwd is not None:
            os.chdir(original_cwd)
        raise

def initialize_pve_engine(scenario_file: Optional[str] = None):
    """
    Backward-compatible wrapper kept for callers that still import this symbol.
    PvE initialization is handled by initialize_test_engine.
    """
    return initialize_test_engine(scenario_file=scenario_file)

def initialize_test_engine(scenario_file: Optional[str] = None, forced_agent_key: Optional[str] = None):
    """Initialize the W40K engine for PvE mode with configurable scenario."""
    global engine
    original_cwd: Optional[str] = None
    try:
        # Change to project root directory for config loading
        original_cwd = os.getcwd()
        project_root = os.path.join(os.path.dirname(__file__), '..')
        os.chdir(os.path.abspath(project_root))
        
        # Define scenario file path for PvE mode (default if not provided)
        if scenario_file is None:
            scenario_file = os.path.join("config", "scenario_pve.json")
        elif not isinstance(scenario_file, str):
            raise ValueError(f"scenario_file must be a string if provided (got {type(scenario_file).__name__})")

        # Verify scenario file exists - no fallback
        if not os.path.exists(scenario_file):
            raise FileNotFoundError(
                f"PvE scenario file not found: {scenario_file}\n"
                f"This file is required for PvE mode.\n"
                f"Create it from config/scenario_pve.json or another scenario."
            )

        # Initialize unit registry
        from ai.unit_registry import UnitRegistry
        unit_registry = UnitRegistry()
        
        from config_loader import get_config_loader
        config_loader = get_config_loader()
        board_config = config_loader.get_board_config()
        game_config = config_loader.get_game_config()
        
        from engine.game_state import GameStateManager
        scenario_manager = GameStateManager({"board": board_config}, unit_registry)
        scenario_result = scenario_manager.load_units_from_scenario(scenario_file, unit_registry)
        scenario_units = require_key(scenario_result, "units")
        scenario_primary_objective_ids = scenario_result.get("primary_objectives")
        scenario_primary_objective_id = scenario_result.get("primary_objective")
        scenario_wall_hexes = scenario_result.get("wall_hexes")
        scenario_wall_ref = scenario_result.get("wall_ref")
        scenario_objectives = scenario_result.get("objectives")
        scenario_deployment_type = scenario_result.get("deployment_type")
        scenario_deployment_type_by_player = scenario_result.get("deployment_type_by_player")
        scenario_deployment_zone = scenario_result.get("deployment_zone")
        scenario_deployment_pools = scenario_result.get("deployment_pools")
        
        if scenario_primary_objective_ids is not None:
            if not isinstance(scenario_primary_objective_ids, list):
                raise TypeError("primary_objectives must be a list of objective IDs")
            if not scenario_primary_objective_ids:
                raise ValueError("primary_objectives list cannot be empty")
            primary_objective_config = [
                config_loader.load_primary_objective_config(obj_id)
                for obj_id in scenario_primary_objective_ids
            ]
        elif scenario_primary_objective_id is not None:
            primary_objective_config = config_loader.load_primary_objective_config(
                scenario_primary_objective_id
            )
        else:
            primary_objective_config = None
        
        config = {
            "board": board_config,
            "game_rules": require_key(game_config, "game_rules"),
            "objective_control_check": require_key(game_config, "objective_control_check"),
            "move": require_key(game_config, "move"),
            "charge": require_key(game_config, "charge"),
            "units": scenario_units,
            "primary_objective": primary_objective_config,
            "scenario_wall_hexes": scenario_wall_hexes,
            "scenario_wall_ref": scenario_wall_ref,
            "scenario_objectives": scenario_objectives,
            "scenario_terrain_areas": scenario_result.get("terrain_areas"),
            "deployment_type": scenario_deployment_type,
            "deployment_type_by_player": scenario_deployment_type_by_player,
            "deployment_zone": scenario_deployment_zone,
            "deployment_pools": scenario_deployment_pools,
            "tutorial_fight_no_death_unit_ids": scenario_result.get(
                "tutorial_fight_no_death_unit_ids"
            ),
        }
        
        # Determine which agents are in the scenario
        agent_keys = get_agents_from_scenario(scenario_file, unit_registry)
        if not agent_keys:
            raise ValueError("No agents found in scenario")
        
        print(f"DEBUG: Found {len(agent_keys)} unique agent(s) in scenario: {agent_keys}")
        
        # For PvE mode, load configs for all agents by default.
        # In mono-agent mode, a forced agent key can provide shared configs
        # for every scenario agent key.
        all_rewards_configs = {}
        all_training_configs = {}

        if forced_agent_key is not None:
            if not isinstance(forced_agent_key, str) or not forced_agent_key.strip():
                raise ValueError(
                    "forced_agent_key must be a non-empty string when provided"
                )
            resolved_forced_agent_key = forced_agent_key.strip()
            print(
                f"DEBUG: PvE mono-agent mode enabled. "
                f"Using '{resolved_forced_agent_key}' configs for all scenario agents: {agent_keys}"
            )
            try:
                shared_rewards = config_loader.load_agent_rewards_config(resolved_forced_agent_key)
                shared_training_full = config_loader.load_agent_training_config(resolved_forced_agent_key)
                training_config_default = config_loader.load_agent_training_config(
                    resolved_forced_agent_key, "x5_new"
                )
            except FileNotFoundError as e:
                raise FileNotFoundError(
                    f"Missing config for forced mono-agent '{resolved_forced_agent_key}'.\n{e}\n"
                    f"Create required files:\n"
                    f"  - config/agents/{resolved_forced_agent_key}/{resolved_forced_agent_key}_rewards_config.json\n"
                    f"  - config/agents/{resolved_forced_agent_key}/{resolved_forced_agent_key}_training_config.json"
                )

            for agent_key in agent_keys:
                all_rewards_configs[agent_key] = shared_rewards
                all_training_configs[agent_key] = shared_training_full
            print(f"✅ Loaded shared configs from forced mono-agent: {resolved_forced_agent_key}")
            first_agent = resolved_forced_agent_key
        else:
            for agent_key in agent_keys:
                try:
                    agent_rewards = config_loader.load_agent_rewards_config(agent_key)
                    # Load entire config file (contains "default" and "debug" phases)
                    agent_training_full = config_loader.load_agent_training_config(agent_key)

                    # Store agent-specific configs
                    all_rewards_configs[agent_key] = agent_rewards
                    all_training_configs[agent_key] = agent_training_full  # Store full config for engine

                    print(f"✅ Loaded configs for agent: {agent_key}")
                except FileNotFoundError as e:
                    raise FileNotFoundError(
                        f"Missing config for agent '{agent_key}' found in scenario.\n{e}\n"
                        f"Create required files:\n"
                        f"  - config/agents/{agent_key}/{agent_key}_rewards_config.json\n"
                        f"  - config/agents/{agent_key}/{agent_key}_training_config.json"
                    )

            # Use first agent's training config for observation params
            first_agent = list(agent_keys)[0]
            training_config_default = config_loader.load_agent_training_config(first_agent, "x5_new")
        
        # PvE mode configuration
        config["pve_mode"] = True
        config["rewards_configs"] = all_rewards_configs  # Multi-agent support
        config["training_configs"] = all_training_configs  # Multi-agent support
        config["agent_keys"] = list(agent_keys)  # Track which agents are active
        config["controlled_agent"] = first_agent  # Required for reward mapping in handlers
        
        # CRITICAL FIX: Add observation_params from training_config "default" phase
        obs_params = training_config_default.get("observation_params", {})
        
        # Validation stricte: obs_size DOIT être présent
        if "obs_size" not in obs_params:
            raise KeyError(
                f"training_config missing required 'obs_size' in observation_params. "
                f"Must be defined in training_config.json 'default' phase. "
                f"Config: {first_agent}"
            )
        
        config["observation_params"] = obs_params  # Inclut obs_size validé
        
        engine = W40KEngine(
            config=config,
            rewards_config="default",
            training_config_name="x5_new",
            controlled_agent=first_agent,
            active_agents=None,
            scenario_file=scenario_file,
            unit_registry=unit_registry,
            quiet=True
        )
        
        # CRITICAL FIX: Add rewards_configs to game_state after engine creation
        engine.game_state["rewards_configs"] = all_rewards_configs
        engine.game_state["agent_keys"] = list(agent_keys)
        # Restore original working directory
        os.chdir(original_cwd)
        
        print("✅ W40K Engine initialized successfully (PvE mode)")
        return True
    except Exception:
        # Restore original working directory on error
        if original_cwd is not None:
            os.chdir(original_cwd)
        raise

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "engine_initialized": engine is not None
    })

@app.route('/api/auth/register', methods=['POST'])
def register_user():
    """Create a user account with base profile."""
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"success": False, "error": "JSON body is required"}), 400

    login = data.get("login")
    password = data.get("password")
    if not isinstance(login, str) or not login.strip():
        return jsonify({"success": False, "error": "login is required and must be a non-empty string"}), 400
    if not isinstance(password, str) or not password:
        return jsonify({"success": False, "error": "password is required and must be a non-empty string"}), 400

    normalized_login = login.strip()
    connection = _get_auth_db_connection()
    try:
        existing_user = connection.execute(
            "SELECT id FROM users WHERE login = ?",
            (normalized_login,),
        ).fetchone()
        if existing_user is not None:
            return jsonify({"success": False, "error": "login already exists"}), 409

        base_profile = connection.execute(
            "SELECT id, code FROM profiles WHERE code = ?",
            ("base",),
        ).fetchone()
        if base_profile is None:
            raise RuntimeError("Profile 'base' is missing from auth database")

        password_hash = _hash_password(password)
        cursor = connection.execute(
            "INSERT INTO users (login, password_hash, profile_id) VALUES (?, ?, ?)",
            (normalized_login, password_hash, base_profile["id"]),
        )
        connection.commit()
        return jsonify(
            {
                "success": True,
                "user_id": cursor.lastrowid,
                "login": normalized_login,
                "profile": base_profile["code"],
            }
        ), 201
    finally:
        connection.close()


@app.route('/api/auth/login', methods=['POST'])
def login_user():
    """Authenticate user and return access token with permissions."""
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"success": False, "error": "JSON body is required"}), 400

    login = data.get("login")
    password = data.get("password")
    if not isinstance(login, str) or not login.strip():
        return jsonify({"success": False, "error": "login is required and must be a non-empty string"}), 400
    if not isinstance(password, str) or not password:
        return jsonify({"success": False, "error": "password is required and must be a non-empty string"}), 400

    normalized_login = login.strip()
    connection = _get_auth_db_connection()
    try:
        user_row = connection.execute(
            """
            SELECT u.id AS user_id, u.login, u.password_hash, p.id AS profile_id, p.code AS profile_code,
                   COALESCE(u.tutorial_completed, 0) AS tutorial_completed
            FROM users u
            JOIN profiles p ON p.id = u.profile_id
            WHERE u.login = ?
            """,
            (normalized_login,),
        ).fetchone()
        if user_row is None:
            return jsonify({"success": False, "error": "Invalid credentials"}), 401

        if not _verify_password(password, user_row["password_hash"]):
            return jsonify({"success": False, "error": "Invalid credentials"}), 401

        access_token = secrets.token_urlsafe(48)
        connection.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            (access_token, user_row["user_id"], str(int(time.time()))),
        )
        permissions = _resolve_permissions_for_profile(connection, user_row["profile_id"])
        connection.commit()

        tutorial_completed = bool(dict(user_row).get("tutorial_completed", 0))
        return jsonify(
            {
                "success": True,
                "access_token": access_token,
                "user": {
                    "id": user_row["user_id"],
                    "login": user_row["login"],
                    "profile": user_row["profile_code"],
                },
                "permissions": permissions,
                "default_redirect_mode": "tutorial" if not tutorial_completed else "pve",
                "tutorial_completed": tutorial_completed,
            }
        )
    finally:
        connection.close()


@app.route('/api/auth/tutorial-complete', methods=['POST'])
def tutorial_complete():
    """Mark the current user's tutorial as completed (called when user finishes or skips tutorial)."""
    user_row, error_response = _get_authenticated_user_or_response()
    if error_response is not None:
        return error_response
    if user_row is None:
        return jsonify({"success": False, "error": "authentication failed"}), 401

    connection = _get_auth_db_connection()
    try:
        connection.execute(
            "UPDATE users SET tutorial_completed = 1 WHERE id = ?",
            (user_row["user_id"],),
        )
        connection.commit()
    finally:
        connection.close()

    return jsonify({"success": True, "tutorial_completed": True})


@app.route('/api/auth/me', methods=['GET'])
def current_user():
    """Return current user session and permissions."""
    user_row, error_response = _get_authenticated_user_or_response()
    if error_response is not None:
        return error_response
    if user_row is None:
        return jsonify({"success": False, "error": "authentication failed"}), 401

    connection = _get_auth_db_connection()
    try:
        permissions = _resolve_permissions_for_profile(connection, user_row["profile_id"])
    finally:
        connection.close()

    tutorial_completed = bool(dict(user_row).get("tutorial_completed", 0))
    return jsonify(
        {
            "success": True,
            "user": {
                "id": user_row["user_id"],
                "login": user_row["login"],
                "profile": user_row["profile_code"],
            },
            "permissions": permissions,
            "default_redirect_mode": "tutorial" if not tutorial_completed else "pve",
            "tutorial_completed": tutorial_completed,
        }
    )


@app.route('/api/debug/engine-test', methods=['GET'])
def test_engine():
    """Test engine initialization directly."""
    # Test config loading
    original_cwd = os.getcwd()
    project_root = os.path.join(os.path.dirname(__file__), '..')
    os.chdir(os.path.abspath(project_root))

    from main import load_config
    config = load_config()

    os.chdir(original_cwd)

    return jsonify({
        "success": True,
        "config_loaded": True,
        "units_count": len(config.get("units", [])),
        "board_config": bool(config.get("board"))
    })

@app.route('/api/game/start', methods=['POST'])
@with_engine_state_lock
def start_game():
    """Start a new game session with optional PvE mode."""
    global engine
    
    auth_user, auth_error = _get_authenticated_user_or_response()
    if auth_error is not None:
        return auth_error
    if auth_user is None:
        return jsonify({"success": False, "error": "authentication failed"}), 401

    # Check for PvE mode in request
    data = request.get_json() or {}
    if "pve_mode" in data and not isinstance(data["pve_mode"], bool):
        raise ValueError(f"pve_mode must be boolean (got {type(data['pve_mode']).__name__})")
    if "mode_code" in data and data["mode_code"] is not None and not isinstance(data["mode_code"], str):
        raise ValueError(f"mode_code must be string or null (got {type(data['mode_code']).__name__})")
    if "scenario_file" in data and data["scenario_file"] is not None and not isinstance(data["scenario_file"], str):
        raise ValueError(f"scenario_file must be string or null (got {type(data['scenario_file']).__name__})")
    if "board_path" in data and data["board_path"] is not None and data["board_path"] not in BOARD_PATH_MAP:
        raise ValueError(f"board_path must be one of {sorted(BOARD_PATH_MAP)} (got {data['board_path']!r})")
    pve_mode = data.get('pve_mode', False)
    mode_code = data.get('mode_code', None)
    scenario_file = data.get('scenario_file', None)
    board_path = data.get('board_path', None)

    requested_mode = "pvp"
    if mode_code is not None:
        allowed_mode_codes = {"pvp", "pve", "pvp_test", "pve_test", ED_MODE_CODE}
        if mode_code not in allowed_mode_codes:
            raise ValueError(f"Unsupported mode_code '{mode_code}'. Allowed values: {sorted(allowed_mode_codes)}")
        requested_mode = mode_code
    elif pve_mode:
        requested_mode = "pve"

    connection = _get_auth_db_connection()
    try:
        permissions = _resolve_permissions_for_profile(connection, auth_user["profile_id"])
    finally:
        connection.close()

    if not _is_mode_allowed(requested_mode, permissions):
        return jsonify(
            {
                "success": False,
                "error": (
                    f"Mode '{requested_mode}' is not allowed for profile "
                    f"'{auth_user['profile_code']}'"
                ),
            }
        ), 403
        
    # CRITICAL: Always reinitialize engine based on requested mode to prevent mode contamination
    # Lock: l'init lit le board via W40K_BOARD_PATH (état global) ; exclusion mutuelle
    # avec GET /api/config/board pour qu'un thread ne lise pas le board d'un autre.
    with _BOARD_ENV_LOCK:
        if requested_mode == "pvp_test":
            print("DEBUG: Initializing engine for PvP Test mode")
            if board_path is None:
                from config_loader import get_config_loader as _gcl
                _cfg = _gcl().load_config("config", force_reload=False)
                board_path = _cfg.get("defaults", {}).get("test_board", "x5")
            scenario_file = os.path.join("config", BOARD_PATH_MAP[board_path], "scenario", "scenario_pvp_test.json")
            _prev_board = os.environ.get("W40K_BOARD_PATH")
            os.environ["W40K_BOARD_PATH"] = BOARD_PATH_MAP[board_path]
            try:
                initialize_engine(scenario_file=scenario_file)
            finally:
                if _prev_board is not None:
                    os.environ["W40K_BOARD_PATH"] = _prev_board
                elif "W40K_BOARD_PATH" in os.environ:
                    del os.environ["W40K_BOARD_PATH"]
        elif requested_mode == "pvp":
            print("DEBUG: Initializing engine for PvP mode")
            initialize_engine(scenario_file=scenario_file)
        elif requested_mode == "pve":
            print("DEBUG: Initializing engine for PvE mode (copied from Test mode)")
            initialize_test_engine(
                scenario_file=scenario_file,
                forced_agent_key="CoreAgent",
            )
        elif requested_mode == "pve_test":
            print("DEBUG: Initializing engine for PvE Test mode")
            if board_path is None:
                from config_loader import get_config_loader as _gcl
                _cfg = _gcl().load_config("config", force_reload=False)
                board_path = _cfg.get("defaults", {}).get("test_board", "x5")
            scenario_file = os.path.join("config", BOARD_PATH_MAP[board_path], "scenario", "scenario_pve_test.json")
            _prev_board = os.environ.get("W40K_BOARD_PATH")
            os.environ["W40K_BOARD_PATH"] = BOARD_PATH_MAP[board_path]
            try:
                initialize_test_engine(
                    scenario_file=scenario_file,
                    forced_agent_key="CoreAgent",
                )
            finally:
                if _prev_board is not None:
                    os.environ["W40K_BOARD_PATH"] = _prev_board
                elif "W40K_BOARD_PATH" in os.environ:
                    del os.environ["W40K_BOARD_PATH"]
        elif requested_mode == ED_MODE_CODE:
            print("DEBUG: Initializing engine for Endless Duty mode")
            if scenario_file is None:
                scenario_file = ED_SCENARIO_DEFAULT
            initialize_test_engine(
                scenario_file=scenario_file,
                forced_agent_key="CoreAgent",
            )
        else:
            print("DEBUG: Initializing engine for PvP mode")
            initialize_engine(scenario_file=scenario_file)

    assert engine is not None

    # HTTP session: requested_mode is the source of truth for PvE vs PvP (aligns engine with client).
    if requested_mode in ("pve", "pve_test", ED_MODE_CODE):
        engine.is_pve_mode = True
        engine.config["pve_mode"] = True
    elif requested_mode in ("pvp", "pvp_test"):
        engine.is_pve_mode = False
        engine.config["pve_mode"] = False
    else:
        raise ValueError(f"Unhandled requested_mode: {requested_mode!r}")

    engine.current_mode_code = requested_mode
    engine.game_state["current_mode_code"] = requested_mode
        
    print("DEBUG: About to call engine.reset()")
    # Reset the engine for new game
    try:
        obs, info = engine.reset()
    except Exception as reset_error:
        print(f"CRITICAL ERROR in engine.reset(): {reset_error}")
        print(f"ERROR TYPE: {type(reset_error).__name__}")
        import traceback
        print(f"FULL TRACEBACK:\n{traceback.format_exc()}")
        raise
    print("DEBUG: engine.reset() completed successfully")

    if requested_mode == ED_MODE_CODE:
        project_root = Path(abs_parent)
        assert scenario_file is not None
        initialize_endless_duty_state(
            engine_instance=engine,
            project_root=project_root,
            scenario_file=scenario_file,
        )
        # Endless Duty spawns tyranids after reset; reload micro models now that player-2 units exist.
        if bool(getattr(engine, "is_pve_mode", False)):
            engine.pve_controller.load_ai_model_for_pve(engine.game_state, engine)

    # Tutoriel : conserver les positions des unités P1 depuis l’état précédent (ex. Intercessor après 1-25)
    preserve_p1 = data.get("preserve_p1_positions_from")
    if isinstance(preserve_p1, dict) and preserve_p1.get("units"):
        prev_units = preserve_p1["units"]
        p1_positions = {}
        for u in prev_units:
            if int(u.get("player", 0)) != 1:
                continue
            uid = u.get("id")
            if uid is None:
                continue
            col, row = u.get("col"), u.get("row")
            if col is not None and row is not None:
                p1_positions[str(uid)] = (col, row)
        if p1_positions:
            for unit in engine.game_state["units"]:
                if int(unit.get("player", 0)) != 1:
                    continue
                uid_str = str(unit["id"])
                if uid_str in p1_positions:
                    set_unit_coordinates(unit, p1_positions[uid_str][0], p1_positions[uid_str][1])
            build_units_cache(engine.game_state)
            rebuild_choice_timing_index(engine.game_state)
            uc = engine.game_state["units_cache"]
            engine.game_state["units_cache_prev"] = {
                uid: {"col": d["col"], "row": d["row"], "HP_CUR": d["HP_CUR"], "player": d["player"]}
                for uid, d in uc.items()
            }

        # Tutoriel 1-25→2 : avancer au début du T1 de P2 (fin du T1 de P1 simulée)
        # Les Hormagaunts bougeront pendant la phase move du T1 de P2
        # Déploiement selon les positions du scenario (ex. scenario_etape2.json)
        gs = engine.game_state
        scenario_file = data.get("scenario_file")
        p2_positions_from_scenario = {}
        if isinstance(scenario_file, str) and scenario_file.strip():
            scenario_path = os.path.join(abs_parent, scenario_file.strip())
            if os.path.exists(scenario_path):
                try:
                    with open(scenario_path, "r", encoding="utf-8") as f:
                        scenario_data = json.load(f)
                    for u in scenario_data.get("units", []):
                        if int(u.get("player", 0)) != 2:
                            continue
                        uid = u.get("id")
                        if uid is None:
                            continue
                        col, row = u.get("col"), u.get("row")
                        if col is not None and row is not None:
                            p2_positions_from_scenario[str(uid)] = (int(col), int(row))
                except (json.JSONDecodeError, OSError):
                    pass
        while gs.get("phase") == "deployment":
            dep_state = gs.get("deployment_state")
            if not dep_state:
                break
            deployer = int(dep_state.get("current_deployer", 2))
            deployable = dep_state.get("deployable_units", {})
            pool_ids = deployable.get(deployer, deployable.get(str(deployer), []))
            if not pool_ids:
                break
            unit_id = str(pool_ids[0])
            dest = None
            if unit_id in p2_positions_from_scenario:
                dest = p2_positions_from_scenario[unit_id]
            if dest is None:
                pools = dep_state.get("deployment_pools", {})
                hex_pool = pools.get(deployer, pools.get(str(deployer), []))
                if not hex_pool:
                    break
                occupied = {(int(u.get("col", -2)), int(u.get("row", -2))) for u in gs.get("units", [])
                            if u.get("col") is not None and u.get("row") is not None}
                for h in hex_pool:
                    if isinstance(h, (list, tuple)) and len(h) >= 2:
                        c, r = int(h[0]), int(h[1])
                    elif isinstance(h, dict) and "col" in h and "row" in h:
                        c, r = int(h["col"]), int(h["row"])
                    else:
                        continue
                    if (c, r) not in occupied:
                        dest = (c, r)
                        break
            if dest is None:
                break
            action = {"action": "deploy_unit", "unitId": unit_id, "destCol": dest[0], "destRow": dest[1]}
            ok, res = deployment_handlers.execute_deployment_action(gs, action)
            if not ok:
                break
            if res.get("phase_complete"):
                command_handlers.command_phase_start(gs)
                movement_handlers.movement_phase_start(gs)
                break
        gs["current_player"] = 2
        gs["turn"] = 1
        command_handlers.command_phase_start(gs)
        movement_handlers.movement_phase_start(gs)

    # Convert game state to JSON-serializable format
    serializable_state = _game_state_for_json(engine)
    _sync_units_hp_from_cache(serializable_state, engine.game_state)
    _attach_player_types(serializable_state, engine)

    # Add max_turns from game config
    from config_loader import get_config_loader
    config = get_config_loader()
    serializable_state["max_turns"] = config.get_max_turns()

    # Add mode flags to response
    serializable_state["pve_mode"] = getattr(engine, 'is_pve_mode', False)

    mode_labels = {
        "pvp": "PvP",
        "pvp_test": "PvP Test",
        "pve_test": "PvE Test",
        "pve": "PvE",
        ED_MODE_CODE: "Endless Duty",
    }
    mode_label = mode_labels.get(requested_mode)
    if mode_label is None:
        raise ValueError(f"Unsupported requested_mode '{requested_mode}'")
    return api_json_response({
        "success": True,
        "game_state": serializable_state,
        "message": f"Game started successfully ({mode_label} mode)",
    })

@app.route('/api/game/action', methods=['POST'])
@with_engine_state_lock
def execute_action():
    """Execute a semantic action in the game."""
    global engine
    
    if not engine:
        return jsonify({"success": False, "error": "Engine not initialized"}), 400
    if "units_cache" not in engine.game_state:
        return jsonify({
            "success": False,
            "error": "Game not started: units_cache is missing. Call /api/game/start successfully before /api/game/action.",
            "error_code": "game_not_started_call_start_first",
        }), 400
    
    data = request.json
    if not data:
        return jsonify({"success": False, "error": "No JSON data provided"}), 400
    mask_loops_client_hash = _extract_mask_loops_client_hash_from_request_data(data)

    # Option debug (menu) : mode pool de tir. True = pool exact (test cible+LoS au build),
    # False = transition rapide (cible résolue à l'activation). Posé avant traitement pour
    # être pris en compte dès la transition move→shoot déclenchée par cette action.
    if "shoot_pool_require_los" in data:
        engine.game_state["shoot_pool_require_los_target"] = bool(data["shoot_pool_require_los"])

    # Convert frontend hex click to engine semantic action format
    if "col" in data and "row" in data and "selectedUnitId" in data:
        action = {
            "action": "move",
            "unitId": str(data["selectedUnitId"]),
            "destCol": data["col"],
            "destRow": data["row"]
        }
    else:
        action = data  # Pass through already formatted actions
        
    if not action:
        return jsonify({"success": False, "error": "No action provided"}), 400

    success = None
    result = None
    endless_mode_active = is_endless_duty_mode(engine)
    if endless_mode_active:
        ed_state = require_key(engine.game_state, "endless_duty_state")
        inter_wave_pending = bool(require_key(ed_state, "inter_wave_pending"))
        action_name = action.get("action")
        if action_name == "endless_duty_status":
            serializable_state = _game_state_for_json(
                engine,
                for_post_action=True,
                mask_loops_client_hash=mask_loops_client_hash,
            )
            _sync_units_hp_from_cache(serializable_state, engine.game_state)
            _attach_player_types(serializable_state, engine)
            return api_json_response(
                {
                    "success": True,
                    "result": {"action": "endless_duty_status"},
                    "game_state": serializable_state,
                    "endless_duty_state": require_key(engine.game_state, "endless_duty_state"),
                }
            )
        if action_name == "endless_duty_commit":
            success, result = commit_inter_wave_requisition(engine, action)
        else:
            if inter_wave_pending:
                return jsonify(
                    {
                        "success": False,
                        "error": "inter_wave_pending_commit_required",
                        "hint": "Use action=endless_duty_commit before continuing combat",
                    }
                ), 400
            # Read-only preview remains allowed during combat phase.
            success = None
            result = None

    # Read-only: BFS des hexes atteignables pour UNE figurine (move par-figurine).
    if action.get("action") == "move_model_destinations":
        model_id = action.get("model_id")
        if model_id is None:
            return jsonify({
                "success": False,
                "error": "move_model_destinations requires model_id",
            }), 400
        from engine.phase_handlers import movement_handlers as _mh_model
        _raw_plan = action.get("provisional_plan")
        _provisional_plan: Optional[Dict[str, Tuple[int, ...]]] = None
        if isinstance(_raw_plan, dict):
            # (col,row) ou (col,row,level) : le niveau par sœur évite qu'une fig d'étage soit
            # re-dérivée au sol et bloque une fig au sol (superposition inter-étage), comme le déploiement.
            _provisional_plan = {
                str(k): tuple(int(x) for x in v)
                for k, v in _raw_plan.items()
                if isinstance(v, (list, tuple)) and len(v) in (2, 3)
            }
        # Étages : niveau de VUE courant (optionnel, défaut 0 = sol) → pool niveau-conscient.
        _mv_level_raw = action.get("level")
        _mv_level = int(_mv_level_raw) if _mv_level_raw is not None else 0
        _model_pool = _mh_model.movement_build_model_destinations_pool(
            engine.game_state, str(model_id), provisional_plan=_provisional_plan, level=_mv_level
        )
        return api_json_response({
            "success": True,
            "result": {
                "action": "move_model_destinations",
                "model_id": str(model_id),
                "destinations": [[int(c), int(r)] for c, r in _model_pool["destinations"]],
                "footprint_mask_loops": _compact_mask_loops_for_api_json(
                    _model_pool["footprint_mask_loops"]
                ),
            },
        })

    # Read-only: pools de déplacement de TOUTES les figs NON POSÉES d'une escouade, en un seul appel
    # (tranche 2 move-preview persistant). Évite N round-trips move_model_destinations. Chaque pool est
    # calculé avec le même provisional_plan (figs déjà posées bloquent les autres).
    if action.get("action") == "move_squad_unplaced_destinations":
        squad_id = action.get("unitId")
        if squad_id is None:
            return jsonify({
                "success": False,
                "error": "move_squad_unplaced_destinations requires unitId",
            }), 400
        from engine.phase_handlers import movement_handlers as _mh_squad
        _raw_plan_sq = action.get("provisional_plan")
        _provisional_plan_sq: Optional[Dict[str, Tuple[int, ...]]] = None
        if isinstance(_raw_plan_sq, dict):
            # (col,row) ou (col,row,level) : niveau par sœur (superposition inter-étage), cf. déploiement.
            _provisional_plan_sq = {
                str(k): tuple(int(x) for x in v)
                for k, v in _raw_plan_sq.items()
                if isinstance(v, (list, tuple)) and len(v) in (2, 3)
            }
        # Étages : niveau de VUE courant (optionnel, défaut 0 = sol) → pools niveau-conscients.
        _sq_level_raw = action.get("level")
        _sq_level = int(_sq_level_raw) if _sq_level_raw is not None else 0
        _placed_ids = set(_provisional_plan_sq.keys()) if _provisional_plan_sq else set()
        _squad_models = require_key(engine.game_state, "squad_models")
        _models_cache = require_key(engine.game_state, "models_cache")
        _squad_mids = _squad_models.get(str(squad_id))
        if _squad_mids is None:
            return jsonify({
                "success": False,
                "error": f"move_squad_unplaced_destinations: unknown squad {squad_id}",
            }), 400
        from engine.perf_timing import append_perf_timing_line, perf_timing_enabled
        _sq_pt = perf_timing_enabled(engine.game_state)
        _sq_t0 = time.perf_counter() if _sq_pt else None
        _pools: Dict[str, list] = {}
        for _mid in _squad_mids:
            _mid_str = str(_mid)
            if _mid_str in _placed_ids:
                continue
            if _mid_str not in _models_cache:
                continue  # fig morte
            _pool = _mh_squad.movement_build_model_destinations_pool(
                engine.game_state, _mid_str, provisional_plan=_provisional_plan_sq, level=_sq_level
            )
            _pools[_mid_str] = [[int(c), int(r)] for c, r in _pool["destinations"]]
        if _sq_pt and _sq_t0 is not None:
            append_perf_timing_line(
                f"SQUAD_UNPLACED_POOLS unit={squad_id} models_computed={len(_pools)} "
                f"placed={len(_placed_ids)} total_s={time.perf_counter() - _sq_t0:.6f}"
            )
        return api_json_response({
            "success": True,
            "result": {
                "action": "move_squad_unplaced_destinations",
                "unitId": str(squad_id),
                "pools": _pools,
            },
        })

    # Read-only: pool des ancres valides pour UNE figurine en déploiement (per-fig, zone filtrée).
    if action.get("action") == "deploy_model_destinations":
        model_id = action.get("model_id")
        if model_id is None:
            return jsonify({
                "success": False,
                "error": "deploy_model_destinations requires model_id",
            }), 400
        from engine.phase_handlers import deployment_handlers as _dh_model
        _raw_plan_dep = action.get("provisional_plan")
        _provisional_plan_dep: Optional[Dict[str, Tuple[int, ...]]] = None
        if isinstance(_raw_plan_dep, dict):
            # (col,row) ou (col,row,level) : le niveau par sœur évite qu'une fig d'étage soit
            # re-dérivée au sol et bloque une fig au sol (collision inter-étage).
            _provisional_plan_dep = {
                str(k): (tuple(int(x) for x in v))
                for k, v in _raw_plan_dep.items()
                if isinstance(v, (list, tuple)) and len(v) in (2, 3)
            }
        # Étages : niveau de VUE courant (optionnel, défaut 0 = sol) → pool niveau-conscient.
        _dep_level_raw = action.get("level")
        _dep_level = int(_dep_level_raw) if _dep_level_raw is not None else 0
        _dep_pool = _dh_model.deployment_build_model_destinations_pool(
            engine.game_state, str(model_id), provisional_plan=_provisional_plan_dep,
            level=_dep_level,
        )
        return api_json_response({
            "success": True,
            "result": {
                "action": "deploy_model_destinations",
                "model_id": str(model_id),
                "destinations": [[int(c), int(r)] for c, r in _dep_pool["destinations"]],
            },
        })

    # Read-only: pool des ancres où le BLOC garde toutes ses empreintes dans la zone (suivi squad).
    if action.get("action") == "deploy_squad_destinations":
        _raw_squad_plan = action.get("plan")
        if not isinstance(_raw_squad_plan, list):
            return jsonify({
                "success": False,
                "error": "deploy_squad_destinations requires plan",
            }), 400
        from engine.phase_handlers import deployment_handlers as _dh_squad
        # Pool de suivi squad = translation rigide HORIZONTALE : on ne garde que (mid, col, row).
        # Tolère les entrées 3 (sol) ou 4 (avec niveau) — le niveau n'intervient pas ici, mais on
        # ne DROPPE pas silencieusement une entrée à 4 éléments (sinon empreinte combinée tronquée).
        _squad_plan = [
            (str(e[0]), int(e[1]), int(e[2]))
            for e in _raw_squad_plan
            if isinstance(e, (list, tuple)) and len(e) in (3, 4)
        ]
        _squad_pool = _dh_squad.deployment_build_squad_destinations_pool(
            engine.game_state, _squad_plan
        )
        return api_json_response({
            "success": True,
            "result": {
                "action": "deploy_squad_destinations",
                "destinations": [[int(c), int(r)] for c, r in _squad_pool["destinations"]],
            },
        })

    # Read-only: dry-run d'un plan provisoire par-figurine (rouge/vert + cohesion + can_validate).
    if action.get("action") == "preview_move_plan":
        squad_id = action.get("unitId")
        plan = action.get("plan")
        if squad_id is None or not isinstance(plan, list):
            return jsonify({
                "success": False,
                "error": "preview_move_plan requires unitId and plan (list of [model_id, col, row])",
            }), 400
        # Préserver le niveau (étages) : entrée 3 (sol/niveau courant) ou 4 (avec niveau) — ne PAS
        # tronquer à 3, sinon le preview d'un move à l'étage perdrait le niveau ciblé.
        parsed_plan = [
            (str(e[0]), int(e[1]), int(e[2])) + ((int(e[3]),) if len(e) >= 4 else ())
            for e in plan
        ]
        from engine.phase_handlers import movement_handlers as _mh_plan
        preview = _mh_plan.movement_preview_move_plan(
            engine.game_state, str(squad_id), parsed_plan
        )
        return api_json_response({
            "success": True,
            "result": {
                "action": "preview_move_plan",
                "unitId": str(squad_id),
                **preview,
            },
        })

    # Read-only: génération de formation compacte de déploiement (drop initial d'escouade).
    if action.get("action") == "deploy_generate_formation":
        from engine.phase_handlers import deployment_handlers as _dh_gen
        ok, res = _dh_gen.deployment_generate_formation_action(engine.game_state, action)
        return api_json_response({"success": bool(ok), "result": res})

    # Read-only: dry-run d'un plan de déploiement par-figurine (rouge/vert + cohésion).
    if action.get("action") == "deploy_preview":
        from engine.phase_handlers import deployment_handlers as _dh_prev
        ok, res = _dh_prev.deployment_preview_action(engine.game_state, action)
        return api_json_response({"success": bool(ok), "result": res})

    # Read-only preview: valid shoot targets from hypothetical position (move/advance phase preview)
    if action.get("action") == "preview_shoot_from_position":
        unit_id = action.get("unitId")
        dest_col = action.get("destCol")
        dest_row = action.get("destRow")
        advance_position = action.get("advancePosition") is True
        include_los_cells = action.get("includeLosCells") is not False
        if unit_id is None or dest_col is None or dest_row is None:
            return jsonify({
                "success": False,
                "error": "preview_shoot_from_position requires unitId, destCol, destRow",
            }), 400
        from engine.phase_handlers.shooting_handlers import preview_shoot_valid_targets_from_position
        preview_payload = preview_shoot_valid_targets_from_position(
            engine.game_state, str(unit_id), int(dest_col), int(dest_row),
            advance_position=advance_position,
            include_los_cells=include_los_cells,
        )
        valid_targets = preview_payload["valid_targets"]
        return jsonify({
            "success": True,
            "result": {
                "blinking_units": valid_targets,
                "start_blinking": len(valid_targets) > 0,
                "los_preview_attack_cells": preview_payload["los_preview_attack_cells"],
                "los_preview_cover_cells": preview_payload["los_preview_cover_cells"],
                "los_preview_ratio_by_hex": preview_payload["los_preview_ratio_by_hex"],
                "cover_by_unit_id": preview_payload["cover_by_unit_id"],
                "hidden_too_far_by_unit_id": preview_payload["hidden_too_far_by_unit_id"],
                "visible_cells_by_target": preview_payload["visible_cells_by_target"],
            },
        })

    if action.get("action") == "preview_hidden_from_position":
        unit_id = action.get("unitId")
        dest_col = action.get("destCol")
        dest_row = action.get("destRow")
        orientation = action.get("orientation")
        if unit_id is None or dest_col is None or dest_row is None:
            return jsonify({
                "success": False,
                "error": "preview_hidden_from_position requires unitId, destCol, destRow",
            }), 400
        from engine.phase_handlers.shooting_handlers import preview_hidden_models_from_position
        hidden_payload = preview_hidden_models_from_position(
            engine.game_state, str(unit_id), int(dest_col), int(dest_row),
            orientation=None if orientation is None else int(orientation),
        )
        return jsonify({"success": True, "result": hidden_payload})

    if action.get("action") == "preview_hidden_from_model_positions":
        unit_id = action.get("unitId")
        model_positions = action.get("modelPositions")
        orientation = action.get("orientation")
        if unit_id is None or not isinstance(model_positions, dict):
            return jsonify({
                "success": False,
                "error": "preview_hidden_from_model_positions requires unitId, modelPositions(dict)",
            }), 400
        from engine.phase_handlers.shooting_handlers import preview_hidden_models_from_model_positions
        hidden_payload = preview_hidden_models_from_model_positions(
            engine.game_state, str(unit_id), model_positions,
            orientation=None if orientation is None else int(orientation),
        )
        return jsonify({"success": True, "result": hidden_payload})

    # Route ALL actions through engine consistently
    if success is None:
        from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

        _api_perf = perf_timing_enabled(engine.game_state)
        _api_t0 = time.perf_counter() if _api_perf else None
        if action.get("action") == "end_phase":
            success, result = _execute_end_phase_action(engine, action)
        elif action.get("action") == "change_roster":
            success, result = _execute_change_roster_action(engine, action)
        else:
            success, result = engine.execute_semantic_action(action)
        _api_t1 = time.perf_counter() if _api_perf else None
    else:
        _api_perf = False
        _api_t0 = None
        _api_t1 = None

    if success and endless_mode_active and action.get("action") != "endless_duty_status":
        ed_post = handle_endless_duty_post_action(engine)
        if isinstance(result, dict):
            result["endless_duty"] = ed_post

    # Convert game state to JSON-serializable format
    _ser_t0 = time.perf_counter() if _api_perf else None
    serializable_state = _game_state_for_json(
        engine,
        for_post_action=True,
        mask_loops_client_hash=mask_loops_client_hash,
    )
    _sync_units_hp_from_cache(serializable_state, engine.game_state)
    _attach_player_types(serializable_state, engine)
    _attach_shoot_visible_cells(serializable_state, engine.game_state)
    _ser_t1 = time.perf_counter() if _api_perf else None

    # WEAPON_SELECTION: Copy available_weapons from result to active unit in game_state
    # AI_TURN.md: After advance, _shooting_unit_execution_loop returns available_weapons
    # Use active_shooting_unit from game_state (not shooterId from result which doesn't exist)
    if result and isinstance(result, dict) and "available_weapons" in result:
        active_unit_id = engine.game_state.get("active_shooting_unit")
        if active_unit_id and "units" in serializable_state:
            for unit in serializable_state["units"]:
                if str(unit.get("id")) == str(active_unit_id):
                    unit["available_weapons"] = result["available_weapons"]
                    break
    # Extract and send detailed action logs to frontend
    action_logs = serializable_state.get("action_logs", [])
    # CRITICAL: Always clear logs after each AI turn to prevent accumulation
    engine.game_state["action_logs"] = []
    serializable_state["action_logs"] = []

    _j0 = time.perf_counter() if _api_perf else None
    _response_payload = {
        "success": success,
        "result": _slim_execute_action_result_for_api(result, action),
        "game_state": serializable_state,
        "action_logs": action_logs,
        "endless_duty_state": (
            require_key(engine.game_state, "endless_duty_state")
            if endless_mode_active
            else None
        ),
        "message": "Action executed successfully" if success else "Action failed",
    }
    if _api_perf:
        resp, _payload_bytes = api_json_response_with_size(_response_payload)
    else:
        _payload_bytes = None
        resp = api_json_response(_response_payload)
    _j1 = time.perf_counter() if _api_perf else None
    if _payload_breakdown_enabled():
        _log_payload_breakdown(
            _response_payload,
            action.get("action") if isinstance(action, dict) else None,
        )
    if _api_perf and _api_t0 is not None and _api_t1 is not None and _ser_t0 is not None and _ser_t1 is not None and _j0 is not None and _j1 is not None:
        from engine.perf_timing import append_perf_timing_line

        gs = engine.game_state
        ep = gs.get("episode_number", "?")
        trn = gs.get("turn", "?")
        ph = gs.get("phase", "?")
        act = action.get("action") if isinstance(action, dict) else None
        append_perf_timing_line(
            f"API_POST_ACTION episode={ep} turn={trn} phase={ph} action={act!r} "
            f"engine_s={_api_t1 - _api_t0:.6f} serialize_game_state_s={_ser_t1 - _ser_t0:.6f} "
            f"response_encode_s={_j1 - _j0:.6f} total_wall_s={_j1 - _api_t0:.6f} "
            f"payload_bytes={_payload_bytes if _payload_bytes is not None else -1}"
        )
        # Découpe visible dans l’onglet Network (Timing) et lisible en JS si CORS expose_headers.
        engine_ms = (_api_t1 - _api_t0) * 1000.0
        ser_ms = (_ser_t1 - _ser_t0) * 1000.0
        enc_ms = (_j1 - _j0) * 1000.0
        total_ms = (_j1 - _api_t0) * 1000.0
        pb = _payload_bytes if _payload_bytes is not None else -1
        resp.headers["Server-Timing"] = (
            f"engine;dur={engine_ms:.3f}, "
            f"serialize;dur={ser_ms:.3f}, "
            f"json_encode;dur={enc_ms:.3f}, "
            f"post_action_wall;dur={total_ms:.3f}"
        )
        resp.headers["X-W40k-Payload-Bytes"] = str(int(pb))

    return resp


def _get_activation_pool_key_for_phase(phase: str) -> str:
    """Return activation pool key for a phase supporting manual end_phase."""
    if phase == "move":
        return "move_activation_pool"
    if phase == "shoot":
        return "shoot_activation_pool"
    if phase == "charge":
        return "charge_activation_pool"
    raise ValueError(f"end_phase is not supported for phase '{phase}'")


def _execute_end_phase_action(engine_instance: W40KEngine, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    End current phase by applying WAIT/SKIP end_activation to all remaining units in pool.
    Supports move/shoot/charge phases. For fight, delegates to advance_phase.
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    game_state = require_key(engine_instance.__dict__, "game_state")
    current_phase = require_key(game_state, "phase")
    current_player = require_key(game_state, "current_player")

    if "player" not in action:
        raise KeyError("end_phase action missing required 'player' field")
    requested_player = int(action["player"])
    if int(current_player) != requested_player:
        return False, {
            "error": "wrong_player_end_phase",
            "current_player": int(current_player),
            "requested_player": requested_player,
            "phase": current_phase,
        }

    if current_phase == "fight":
        return engine_instance.execute_semantic_action({"action": "advance_phase", "from": "fight"})

    pool_key = _get_activation_pool_key_for_phase(current_phase)

    _perf = perf_timing_enabled(game_state)
    _t_ep0 = time.perf_counter() if _perf else None
    _sum_skip_s = 0.0
    _unit_pairs = 0

    # Process all units currently eligible in this phase.
    loop_count = 0
    max_loops = 300
    last_result: Dict[str, Any] = {"action": "end_phase", "phase": current_phase}

    while True:
        loop_count += 1
        if loop_count > max_loops:
            raise RuntimeError(f"end_phase loop exceeded safety limit for phase '{current_phase}'")

        if require_key(game_state, "phase") != current_phase:
            if _perf and _t_ep0 is not None:
                ep = game_state.get("episode_number", "?")
                trn = game_state.get("turn", "?")
                _dt = time.perf_counter() - _t_ep0
                append_perf_timing_line(
                    f"END_PHASE episode={ep} turn={trn} start_phase={current_phase} outcome=phase_changed_early "
                    f"unit_pairs={_unit_pairs} activate_semantic_s=0.000000 skip_semantic_s={_sum_skip_s:.6f} "
                    f"advance_phase_s=0.000000 total_s={_dt:.6f}"
                )
            return True, last_result

        activation_pool = require_key(game_state, pool_key)
        if not activation_pool:
            break

        unit_id = str(activation_pool[0])
        # Ne pas appeler ``activate_unit`` avant ``skip`` : ``skip`` retire l'unité de la pool via
        # ``end_activation`` sans les coûts d'activation (BFS move, construction de cibles tir, etc.).
        # Charge : ``execute_action`` traite un ``skip`` pour une unité dans ``charge_activation_pool``
        # sans activation préalable (voir charge_handlers).
        _ts0 = time.perf_counter() if _perf else None
        skip_success, skip_result = engine_instance.execute_semantic_action(
            {
                "action": "skip",
                "unitId": unit_id,
                # Tir : sans ce flag, ``skip`` peut suivre la logique ``wait`` → move_after_shooting + BFS.
                # Charge : sans ce flag, ``skip`` utilise ``WAIT`` dans ``end_activation`` (logs + step) par unité.
                "manual_end_phase": True,
            }
        )
        if _perf and _ts0 is not None:
            _sum_skip_s += time.perf_counter() - _ts0
        _unit_pairs += 1
        if not skip_success:
            if _perf and _t_ep0 is not None:
                ep = game_state.get("episode_number", "?")
                trn = game_state.get("turn", "?")
                _dt = time.perf_counter() - _t_ep0
                append_perf_timing_line(
                    f"END_PHASE episode={ep} turn={trn} start_phase={current_phase} outcome=skip_failed "
                    f"unit_pairs={_unit_pairs} activate_semantic_s=0.000000 skip_semantic_s={_sum_skip_s:.6f} "
                    f"advance_phase_s=0.000000 total_s={_dt:.6f}"
                )
            return False, {
                "error": "end_phase_skip_failed",
                "phase": current_phase,
                "unitId": unit_id,
                "details": skip_result,
            }
        last_result = skip_result if isinstance(skip_result, dict) else last_result

        if require_key(game_state, "phase") != current_phase:
            if _perf and _t_ep0 is not None:
                ep = game_state.get("episode_number", "?")
                trn = game_state.get("turn", "?")
                _dt = time.perf_counter() - _t_ep0
                append_perf_timing_line(
                    f"END_PHASE episode={ep} turn={trn} start_phase={current_phase} outcome=phase_changed_after_skip "
                    f"unit_pairs={_unit_pairs} activate_semantic_s=0.000000 skip_semantic_s={_sum_skip_s:.6f} "
                    f"advance_phase_s=0.000000 total_s={_dt:.6f}"
                )
            return True, last_result

    # If pool is empty but phase did not transition yet, trigger explicit phase advance.
    _t_adv0 = time.perf_counter() if _perf else None
    advance_success, advance_result = engine_instance.execute_semantic_action(
        {
            "action": "advance_phase",
            "from": current_phase,
            "reason": "manual_end_phase",
            "manual_end_phase": True,
        }
    )
    _adv_s = (time.perf_counter() - _t_adv0) if _perf and _t_adv0 is not None else 0.0
    if not advance_success:
        if _perf and _t_ep0 is not None:
            ep = game_state.get("episode_number", "?")
            trn = game_state.get("turn", "?")
            _dt = time.perf_counter() - _t_ep0
            append_perf_timing_line(
                f"END_PHASE episode={ep} turn={trn} start_phase={current_phase} outcome=advance_failed "
                f"unit_pairs={_unit_pairs} activate_semantic_s=0.000000 skip_semantic_s={_sum_skip_s:.6f} "
                f"advance_phase_s={_adv_s:.6f} total_s={_dt:.6f}"
            )
        return False, {
            "error": "end_phase_advance_failed",
            "phase": current_phase,
            "details": advance_result,
        }
    if _perf and _t_ep0 is not None:
        ep = game_state.get("episode_number", "?")
        trn = game_state.get("turn", "?")
        _dt = time.perf_counter() - _t_ep0
        append_perf_timing_line(
            f"END_PHASE episode={ep} turn={trn} start_phase={current_phase} outcome=success "
            f"unit_pairs={_unit_pairs} activate_semantic_s=0.000000 skip_semantic_s={_sum_skip_s:.6f} "
            f"advance_phase_s={_adv_s:.6f} total_s={_dt:.6f}"
        )
    if isinstance(advance_result, dict):
        advance_result["action"] = "end_phase"
    return True, advance_result


def _load_army_file(army_file: str) -> Dict[str, Any]:
    """Load and validate one army config from config/armies."""
    if not army_file or not isinstance(army_file, str):
        raise ValueError("army_file must be a non-empty string")
    if "/" in army_file or "\\" in army_file:
        raise ValueError(f"army_file must be a filename only, got: {army_file}")
    if not army_file.endswith(".json"):
        raise ValueError(f"army_file must end with .json, got: {army_file}")

    armies_dir = os.path.join(abs_parent, "config", "armies")
    army_path = os.path.join(armies_dir, army_file)
    if not os.path.exists(army_path):
        raise FileNotFoundError(f"Army file not found: {army_file}")

    with open(army_path, "r", encoding="utf-8") as f:
        army_cfg = json.load(f)

    require_key(army_cfg, "faction")
    display_name = require_key(army_cfg, "display_name")
    if not isinstance(display_name, str) or not display_name.strip():
        raise ValueError(f"Army file {army_file} display_name must be a non-empty string")
    require_key(army_cfg, "description")
    units = require_key(army_cfg, "units")
    if not isinstance(units, list) or not units:
        raise ValueError(f"Army file {army_file} must contain a non-empty units array")
    for idx, unit in enumerate(units):
        if not isinstance(unit, dict):
            raise TypeError(f"Army file {army_file} units[{idx}] must be an object")
        unit_type = require_key(unit, "unit_type")
        if not isinstance(unit_type, str) or not unit_type.strip():
            raise ValueError(f"Army file {army_file} units[{idx}].unit_type must be a non-empty string")
        # "count" : format army (effectif). Optionnel ici pour accepter aussi le
        # format scénario (units positionnées avec "models"/"col"/"row"). Validé
        # seulement s'il est présent. La construction reste count-based pour l'instant.
        if "count" in unit:
            count = unit["count"]
            if not isinstance(count, int) or count <= 0:
                raise ValueError(f"Army file {army_file} units[{idx}].count must be a positive integer")
    return army_cfg


def _load_faction_display_name_map() -> Dict[str, str]:
    """Load faction_id -> display_name mapping from config/factions.json."""
    factions_path = os.path.join(abs_parent, "config", "factions.json")
    if not os.path.exists(factions_path):
        raise FileNotFoundError(f"Factions file not found: {factions_path}")
    with open(factions_path, "r", encoding="utf-8") as factions_file:
        factions_cfg = json.load(factions_file)
    if not isinstance(factions_cfg, dict) or not factions_cfg:
        raise ValueError("config/factions.json must be a non-empty object")

    faction_display_name_map: Dict[str, str] = {}
    for faction_id, faction_entry in factions_cfg.items():
        if not isinstance(faction_id, str) or not faction_id.strip():
            raise ValueError(f"Invalid faction id in config/factions.json: {faction_id!r}")
        if not isinstance(faction_entry, dict):
            raise TypeError(
                f"Faction '{faction_id}' in config/factions.json must be an object, "
                f"got {type(faction_entry).__name__}"
            )
        display_name = require_key(faction_entry, "display_name")
        if not isinstance(display_name, str) or not display_name.strip():
            raise ValueError(
                f"Faction '{faction_id}' display_name must be a non-empty string"
            )
        faction_display_name_map[faction_id.strip()] = display_name.strip()
    return faction_display_name_map


def _list_armies() -> list[Dict[str, Any]]:
    """Return metadata for all army files in config/armies."""
    armies_dir = os.path.join(abs_parent, "config", "armies")
    if not os.path.isdir(armies_dir):
        raise FileNotFoundError(f"Armies directory not found: {armies_dir}")

    faction_display_name_map = _load_faction_display_name_map()
    army_files = sorted([name for name in os.listdir(armies_dir) if name.endswith(".json")])
    armies: list[Dict[str, Any]] = []
    for army_file in army_files:
        army_cfg = _load_army_file(army_file)
        faction_id = require_key(army_cfg, "faction")
        if not isinstance(faction_id, str) or not faction_id.strip():
            raise ValueError(f"Army file {army_file} faction must be a non-empty string")
        normalized_faction_id = faction_id.strip()
        if normalized_faction_id not in faction_display_name_map:
            raise KeyError(
                f"Faction '{normalized_faction_id}' from army file {army_file} "
                "is missing in config/factions.json"
            )
        armies.append(
            {
                "file": army_file,
                "name": army_file[:-5],
                "display_name": require_key(army_cfg, "display_name"),
                "faction": normalized_faction_id,
                "faction_display_name": faction_display_name_map[normalized_faction_id],
                "description": require_key(army_cfg, "description"),
            }
        )
    return armies


def _build_units_from_army_config(
    army_cfg: Dict[str, Any],
    player: int,
    next_unit_id: int,
    engine_instance: W40KEngine,
) -> Tuple[list[Dict[str, Any]], int]:
    """Build full engine units for one player from army config."""
    if not hasattr(engine_instance, "unit_registry") or engine_instance.unit_registry is None:
        raise ValueError("engine.unit_registry is required to build units from army config")

    built_units: list[Dict[str, Any]] = []
    units = require_key(army_cfg, "units")
    for unit_def in units:
        unit_type = require_key(unit_def, "unit_type")
        count = require_key(unit_def, "count")
        unit_data = engine_instance.unit_registry.get_unit_data(unit_type)
        for _ in range(count):
            unit_id_str = str(next_unit_id)
            next_unit_id += 1
            rng_weapons = copy.deepcopy(require_key(unit_data, "RNG_WEAPONS"))
            cc_weapons = copy.deepcopy(require_key(unit_data, "CC_WEAPONS"))
            selected_rng_weapon_index = 0 if rng_weapons else None
            selected_cc_weapon_index = 0 if cc_weapons else None
            shoot_left = 0
            if rng_weapons and selected_rng_weapon_index is not None:
                selected_weapon = rng_weapons[selected_rng_weapon_index]
                shoot_left = resolve_dice_value(require_key(selected_weapon, "NB"), "api_roster_change_shoot_left")
            attack_left = 0
            if cc_weapons and selected_cc_weapon_index is not None:
                selected_weapon = cc_weapons[selected_cc_weapon_index]
                attack_left = resolve_dice_value(require_key(selected_weapon, "NB"), "api_roster_change_attack_left")

            built_units.append(
                {
                    "id": unit_id_str,
                    "player": player,
                    "unitType": unit_type,
                    "DISPLAY_NAME": require_key(unit_data, "DISPLAY_NAME"),
                    "col": -1,
                    "row": -1,
                    "HP_CUR": require_key(unit_data, "HP_MAX"),
                    "HP_MAX": require_key(unit_data, "HP_MAX"),
                    "MOVE": require_key(unit_data, "MOVE"),
                    "T": require_key(unit_data, "T"),
                    "ARMOR_SAVE": require_key(unit_data, "ARMOR_SAVE"),
                    "INVUL_SAVE": require_key(unit_data, "INVUL_SAVE"),
                    "RNG_WEAPONS": rng_weapons,
                    "CC_WEAPONS": cc_weapons,
                    "selectedRngWeaponIndex": selected_rng_weapon_index,
                    "selectedCcWeaponIndex": selected_cc_weapon_index,
                    "LD": require_key(unit_data, "LD"),
                    "OC": require_key(unit_data, "OC"),
                    "VALUE": require_key(unit_data, "VALUE"),
                    "ICON": require_key(unit_data, "ICON"),
                    "ICON_SCALE": require_key(unit_data, "ICON_SCALE"),
                    "ILLUSTRATION_RATIO": require_key(unit_data, "ILLUSTRATION_RATIO"),
                    "UNIT_RULES": copy.deepcopy(require_key(unit_data, "UNIT_RULES")),
                    "UNIT_KEYWORDS": copy.deepcopy(require_key(unit_data, "UNIT_KEYWORDS")),
                    "SHOOT_LEFT": shoot_left,
                    "ATTACK_LEFT": attack_left,
                }
            )
    return built_units, next_unit_id


def _build_units_from_scenario_army(
    engine_instance: W40KEngine,
    army_cfg: Dict[str, Any],
    player: int,
    next_unit_id: int,
) -> Tuple[list[Dict[str, Any]], int]:
    """Build full engine units for one player from a SCENARIO-format army file
    (units positionnées avec ``models`` / ``attached_squad``).

    Réutilise les briques du moteur (``_fold_attached_characters`` +
    ``_build_enhanced_unit``) : même normalisation des ``models`` et même fusion des
    characters attachés qu'au chargement d'une partie — aucune logique dupliquée.
    Déploiement actif : positions sentinelles ``-1,-1`` (le joueur place ensuite).
    Les unités sont réaffectées au joueur cible et renumérotées (l'appelant compacte).
    """
    if not hasattr(engine_instance, "unit_registry") or engine_instance.unit_registry is None:
        raise ValueError("engine.unit_registry is required to build units from scenario army")
    from engine.game_state import GameStateManager
    from config_loader import get_config_loader

    reg = engine_instance.unit_registry
    manager = GameStateManager(
        {"board": get_config_loader().get_board_config(), "controlled_player": int(player)},
        reg,
    )
    basic_units = manager._fold_attached_characters(copy.deepcopy(require_key(army_cfg, "units")))
    built_units: list[Dict[str, Any]] = []
    for unit_def in basic_units:
        unit_type = require_key(unit_def, "unit_type")
        full_unit_data = reg.get_unit_data(unit_type)
        enhanced = manager._build_enhanced_unit(
            unit_def, full_unit_data, unit_type, int(player), "active", -1, -1, reg
        )
        enhanced["id"] = str(next_unit_id)
        next_unit_id += 1
        built_units.append(enhanced)
    return built_units, next_unit_id


def _execute_change_roster_action(engine_instance: W40KEngine, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Replace active deployer's undeployed roster with selected army file."""
    game_state = require_key(engine_instance.__dict__, "game_state")
    if require_key(game_state, "phase") != "deployment":
        return False, {"error": "change_roster_only_in_deployment", "phase": game_state.get("phase")}
    if require_key(game_state, "deployment_type") != "active":
        return False, {"error": "change_roster_requires_active_deployment"}
    deployment_state = require_key(game_state, "deployment_state")
    current_deployer = int(require_key(deployment_state, "current_deployer"))
    target_deployer = current_deployer

    requested_player = action.get("player")
    if requested_player is not None:
        current_mode_code = getattr(engine_instance, "current_mode_code", None)
        allowed_multi_player_roster_modes = {"pvp_test", "pvp", "pve", "pve_test"}
        player_types = game_state.get("player_types")
        legacy_human_vs_human_setup = (
            isinstance(player_types, dict)
            and player_types.get("1") == "human"
            and player_types.get("2") == "human"
        )
        if current_mode_code not in allowed_multi_player_roster_modes and not legacy_human_vs_human_setup:
            return False, {"error": "change_roster_player_only_in_setup_modes"}
        target_deployer = int(requested_player)
        if target_deployer not in (1, 2):
            raise ValueError(f"Invalid player for change_roster: {requested_player}")

    # Enforce: change roster only before active player deploys first unit.
    deployable_units = require_key(deployment_state, "deployable_units")
    deployed_units = require_key(deployment_state, "deployed_units")
    deployable_for_player = deployable_units.get(target_deployer, deployable_units.get(str(target_deployer)))
    if deployable_for_player is None:
        raise KeyError(f"deployable_units missing player {target_deployer}")
    deployed_set = {str(uid) for uid in deployed_units}
    current_player_units = [u for u in require_key(game_state, "units") if int(require_key(u, "player")) == target_deployer]
    current_player_unit_ids = {str(require_key(unit, "id")) for unit in current_player_units}
    if current_player_unit_ids & deployed_set:
        return False, {"error": "change_roster_locked_after_first_deploy", "current_deployer": target_deployer}

    army_file = require_key(action, "army_file")
    army_cfg = _load_army_file(army_file)

    all_unit_ids = [int(str(require_key(unit, "id"))) for unit in require_key(game_state, "units")]
    next_unit_id = (max(all_unit_ids) + 1) if all_unit_ids else 1
    # Deux formats supportés : army (unit_type + count, unités mono-fig) et scénario
    # (units positionnées avec models/attached_squad, squads multi-fig). Détection par
    # absence de "count" sur toutes les units.
    army_units = require_key(army_cfg, "units")
    is_scenario_format = all("count" not in u for u in army_units)
    if is_scenario_format:
        new_units, _ = _build_units_from_scenario_army(engine_instance, army_cfg, target_deployer, next_unit_id)
    else:
        new_units, _ = _build_units_from_army_config(army_cfg, target_deployer, next_unit_id, engine_instance)

    # Replace only current deployer's units, then compact IDs to prevent unbounded growth.
    other_units = [u for u in require_key(game_state, "units") if int(require_key(u, "player")) != target_deployer]
    combined_units = other_units + new_units
    id_remap: Dict[str, str] = {}
    for idx, unit in enumerate(combined_units, start=1):
        old_id = str(require_key(unit, "id"))
        new_id = str(idx)
        id_remap[old_id] = new_id
        unit["id"] = new_id
    game_state["units"] = combined_units
    game_state["unit_by_id"] = {str(u["id"]): u for u in combined_units}

    # Rebuild reward config mappings using engine centralized logic.
    # This preserves mono-agent CoreAgent behavior by mapping all model keys
    # to controlled_agent rewards in single-policy mode.
    reward_configs = engine_instance._build_reward_configs_for_current_units()
    game_state["reward_configs"] = reward_configs
    game_state["rewards_configs"] = reward_configs

    # Keep deployment state coherent after replacement and ID compaction.
    old_deployed_after_replace = {uid for uid in deployed_set if uid not in current_player_unit_ids}
    new_deployed_set = {id_remap[uid] for uid in old_deployed_after_replace if uid in id_remap}
    deployment_state["deployed_units"] = new_deployed_set

    rebuilt_deployable_units: Dict[int, list[str]] = {1: [], 2: []}
    for unit in combined_units:
        unit_id = str(require_key(unit, "id"))
        unit_player = int(require_key(unit, "player"))
        if unit_id not in new_deployed_set:
            rebuilt_deployable_units[unit_player].append(unit_id)
    deployment_state["deployable_units"] = rebuilt_deployable_units

    deployment_state["current_deployer"] = current_deployer
    game_state["current_player"] = current_deployer

    # Rebuild cache from updated units list.
    build_units_cache(game_state)
    rebuild_choice_timing_index(game_state)
    units_cache = require_key(game_state, "units_cache")
    game_state["units_cache_prev"] = {
        uid: {
            "col": require_key(entry, "col"),
            "row": require_key(entry, "row"),
            "HP_CUR": require_key(entry, "HP_CUR"),
            "player": require_key(entry, "player"),
        }
        for uid, entry in units_cache.items()
    }

    # If AI player roster changed, reload micro models so PvE AI can act with new unit types.
    ai_enabled = bool(getattr(engine_instance, "is_pve_mode", False))
    if ai_enabled and target_deployer == 2:
        engine_instance.pve_controller.load_ai_model_for_pve(game_state, engine_instance)

    updated_unit_ids = [
        str(require_key(unit, "id"))
        for unit in combined_units
        if int(require_key(unit, "player")) == target_deployer
    ]
    return True, {
        "action": "change_roster",
        "army_file": army_file,
        "army_name": army_file[:-5],
        "current_deployer": current_deployer,
        "updated_player": target_deployer,
        "updated_unit_ids": updated_unit_ids,
    }


@app.route('/api/armies', methods=['GET'])
def list_armies():
    """List selectable armies from config/armies."""
    return jsonify({"success": True, "armies": _list_armies()})

@app.route('/api/game/state', methods=['GET'])
@with_engine_state_lock
def get_game_state():
    """Get current game state."""
    global engine
    
    if not engine:
        return jsonify({"success": False, "error": "Engine not initialized"}), 400
    
    # Convert game state to JSON-serializable format
    serializable_state = _game_state_for_json(engine)
    _sync_units_hp_from_cache(serializable_state, engine.game_state)
    _attach_player_types(serializable_state, engine)
    
    return api_json_response({
        "success": True,
        "game_state": serializable_state,
    })

@app.route('/api/game/reset', methods=['POST'])
@with_engine_state_lock
def reset_game():
    """Reset the current game."""
    global engine
    
    if not engine:
        return jsonify({"success": False, "error": "Engine not initialized"}), 400
    
    obs, info = engine.reset()
    serializable_state = _game_state_for_json(engine)
    _sync_units_hp_from_cache(serializable_state, engine.game_state)
    _attach_player_types(serializable_state, engine)

    return api_json_response({
        "success": True,
        "game_state": serializable_state,
        "message": "Game reset successfully",
    })

@app.route('/api/config/tutorial/steps', methods=['GET'])
def get_tutorial_steps():
    """Serve tutorial steps from tutorial_scenario.yaml (single source of truth)."""
    project_root = Path(__file__).resolve().parent.parent
    path = project_root / "config" / "tutorial" / "tutorial_scenario.yaml"
    if not path.exists():
        return jsonify({"success": False, "error": "tutorial_scenario.yaml not found"}), 404

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or "steps" not in data or not isinstance(data["steps"], list):
        return jsonify({
            "success": False,
            "error": "tutorial_scenario.yaml must be an object with a steps[] array"
        }), 500

    return jsonify({"steps": data["steps"]})


@app.route('/api/config/defaults', methods=['GET'])
def get_config_defaults():
    """Expose config.json defaults section to the frontend."""
    from config_loader import get_config_loader
    config_loader = get_config_loader()
    config = config_loader.load_config("config", force_reload=False)
    return jsonify({"success": True, "defaults": require_key(config, "defaults")})


@app.route('/api/config/board', methods=['GET'])
def get_board_config():
    """Get board configuration for frontend.
    Loads board_config.json from config/board/{paths.board}/, then walls and objectives
    from the same directory (walls/walls-XX.json, objectives/objectives-XX.json).
    Accepts optional query param board_path (x1|x5|x10) to override the default board.
    """
    try:
        from config_loader import get_config_loader
        config_loader = get_config_loader()
        board_path_param = request.args.get("board_path")
        if board_path_param is not None and board_path_param not in BOARD_PATH_MAP:
            raise ValueError(f"board_path must be one of {sorted(BOARD_PATH_MAP)} (got {board_path_param!r})")
        if board_path_param is not None:
            with _BOARD_ENV_LOCK:
                prev = os.environ.get("W40K_BOARD_PATH")
                os.environ["W40K_BOARD_PATH"] = BOARD_PATH_MAP[board_path_param]
                try:
                    board_data = config_loader.get_board_config()
                finally:
                    if prev is not None:
                        os.environ["W40K_BOARD_PATH"] = prev
                    elif "W40K_BOARD_PATH" in os.environ:
                        del os.environ["W40K_BOARD_PATH"]
        else:
            board_data = config_loader.get_board_config()
        board_spec = board_data["default"]
        config_json = config_loader.load_config("config", force_reload=False)
        if board_path_param:
            board_subdir = BOARD_PATH_MAP[board_path_param]
        else:
            board_subdir = require_key(require_key(config_json, "paths"), "board")
        if not board_subdir:
            raise ValueError("config.json: 'paths.board' must be a non-empty value")

        project_root = Path(__file__).resolve().parent.parent
        board_dir = project_root / "config" / board_subdir
        wall_ref = board_spec.get("wall_ref")
        terrain_ref = board_spec.get("terrain_ref")

        scenario_file_raw = request.args.get("scenario_file")
        scenario_data = None
        if scenario_file_raw is not None and not isinstance(scenario_file_raw, str):
            raise ValueError("scenario_file query param must be a string when provided")
        scenario_file = scenario_file_raw.strip() if isinstance(scenario_file_raw, str) else None
        if scenario_file:
            if not scenario_file.endswith(".json"):
                raise ValueError("scenario_file must reference a .json file")
            normalized = scenario_file.replace("\\", "/").strip()
            if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
                raise ValueError(f"Unsafe scenario_file path: {scenario_file}")
            scenario_path = (project_root / normalized).resolve()
            config_root = (project_root / "config").resolve()
            if config_root not in scenario_path.parents:
                raise ValueError(f"scenario_file must be under config/: {scenario_file}")
            if not scenario_path.exists():
                raise FileNotFoundError(f"Scenario file not found: {scenario_file}")
            with open(scenario_path, "r", encoding="utf-8-sig") as f:
                scenario_data = json.load(f)
            if not isinstance(scenario_data, dict):
                raise ValueError("scenario_file JSON must be an object")

            has_wall_hexes = "wall_hexes" in scenario_data
            has_wall_ref = "wall_ref" in scenario_data
            if has_wall_hexes and has_wall_ref:
                raise ValueError("scenario cannot define both wall_hexes and wall_ref")
            if has_wall_ref:
                wall_ref_raw = scenario_data.get("wall_ref")
                if not isinstance(wall_ref_raw, str) or not wall_ref_raw.strip():
                    raise ValueError("scenario wall_ref must be a non-empty string")
                wall_ref_candidate = wall_ref_raw.strip()
                if "/" in wall_ref_candidate or "\\" in wall_ref_candidate:
                    raise ValueError("scenario wall_ref must be filename only")
                wall_ref = wall_ref_candidate

            # Objectifs legacy (objectives / objectives_ref) supprimés : erreur explicite.
            for legacy_key in ("objectives", "objectives_ref", "objective_hexes"):
                if legacy_key in scenario_data:
                    raise ValueError(
                        f"scenario uses removed objective key '{legacy_key}'; "
                        f"objectives are sourced from terrain areas flagged \"objective\": true"
                    )

            if "terrain_ref" in scenario_data:
                terrain_ref_raw = scenario_data.get("terrain_ref")
                if not isinstance(terrain_ref_raw, str) or not terrain_ref_raw.strip():
                    raise ValueError("scenario terrain_ref must be a non-empty string")
                terrain_ref_candidate = terrain_ref_raw.strip()
                if "/" in terrain_ref_candidate or "\\" in terrain_ref_candidate:
                    raise ValueError("scenario terrain_ref must be filename only")
                terrain_ref = terrain_ref_candidate

        wall_hexes: list = []
        wall_segments_raw: list[dict] = []
        if scenario_file and isinstance(scenario_data, dict) and "wall_hexes" in scenario_data:
            scenario_wall_hexes = scenario_data.get("wall_hexes")
            if not isinstance(scenario_wall_hexes, list):
                raise ValueError("scenario wall_hexes must be a list")
            wall_hexes = scenario_wall_hexes
        elif wall_ref and wall_ref.endswith(".json"):
            wall_path = board_dir / "walls" / wall_ref
            if not wall_path.exists():
                raise FileNotFoundError(f"Referenced wall file not found: {wall_path}")
            with open(wall_path, "r", encoding="utf-8-sig") as f:
                wall_data = json.load(f)
            if "walls" in wall_data:
                wall_hexes = []
                for gi, g in enumerate(wall_data.get("walls", [])):
                    if not isinstance(g, dict):
                        raise ValueError(f"wall group {gi} must be an object")
                    hint = f"{wall_path} walls[{gi}]"
                    has_segments = bool(g.get("segments"))
                    if has_segments:
                        for seg in g["segments"]:
                            if isinstance(seg, list) and len(seg) == 2:
                                a, b = seg[0], seg[1]
                                wall_segments_raw.append({
                                    "start": {"col": int(a[0]), "row": int(a[1])},
                                    "end": {"col": int(b[0]), "row": int(b[1])},
                                })
                    from engine.hex_utils import expand_wall_group_to_hex_list as _expand
                    wall_hexes.extend(_expand(g, path_hint=hint))
            elif "wall_hexes" in wall_data:
                wall_hexes = wall_data["wall_hexes"]
            else:
                raise ValueError(f"Wall file {wall_path} must contain 'walls' or 'wall_hexes'")

        from engine.hex_utils import expand_objectives_to_hex_list as _expand_objectives
        board_cols = int(require_key(board_spec, "cols"))
        board_rows = int(require_key(board_spec, "rows"))

        merged = dict(board_spec)
        merged["wall_hexes"] = wall_hexes
        if wall_segments_raw:
            merged["walls"] = wall_segments_raw
        def _zone_entry(o: dict) -> dict:
            entry: dict = {"id": str(o["id"]), "name": str(o.get("name", o["id"])), "hexes": o["hexes"]}
            if "shape" in o:
                entry["shape"] = o["shape"]
            if "vertices" in o:
                entry["vertices"] = o["vertices"]
            if "top_left" in o:
                entry["top_left"] = o["top_left"]
            if "bottom_right" in o:
                entry["bottom_right"] = o["bottom_right"]
            if "objective" in o:
                entry["objective"] = o["objective"]
            if "obscuring" in o:
                entry["obscuring"] = o["obscuring"]
            # Étages (format B) : exposés au front avec chaque plancher rasterisé (empreinte + hexes).
            if isinstance(o.get("floors"), list) and o["floors"]:
                from engine.hex_utils import polygon_to_hex_list as _p2h
                floors_out = []
                for _f in o["floors"]:
                    _poly = [[int(v[0]), int(v[1])] for v in _f["vertices"]]
                    floors_out.append({
                        "level": int(_f["level"]),
                        "height_inches": float(_f["height_inches"]),
                        "vertices": _poly,
                        "hexes": _p2h(_poly, board_cols, board_rows),
                    })
                entry["floors"] = floors_out
            return entry
        # Objectifs = terrains "objective": true (source unique). Rempli après chargement terrain.
        merged["objective_zones"] = []

        # Terrain décoratif (ruines) : shapes dessinées en périmètre, NON bloquantes
        # (jamais expandées dans wall_hexes). Canal distinct des murs et des objectifs.
        terrain_zones: list = []
        terrain_icons: list = []
        deployment_zones_cfg: list = []
        if terrain_ref and terrain_ref.endswith(".json"):
            terrain_path = board_dir / "terrain" / terrain_ref
            if not terrain_path.exists():
                raise FileNotFoundError(f"Referenced terrain file not found: {terrain_path}")
            with open(terrain_path, "r", encoding="utf-8-sig") as f:
                terrain_data = json.load(f)
            if "terrain" not in terrain_data:
                raise ValueError(f"Terrain file {terrain_path} must contain 'terrain'")
            terrain_features = _expand_objectives(
                terrain_data["terrain"],
                cols=board_cols,
                rows=board_rows,
                path_hint=f"board terrain ({board_subdir})",
            )
            terrain_zones = [_zone_entry(t) for t in terrain_features]
            # Source UNIQUE des objectifs côté rendu : terrains flaggés "objective": true.
            merged["objective_zones"] = [z for z in terrain_zones if z.get("objective")]
            terrain_icons = terrain_data.get("icons", [])
            deployment_zones_cfg = terrain_data.get("deployment_zones", [])
            for gi, g in enumerate(terrain_data.get("walls", [])):
                if not isinstance(g, dict):
                    continue
                for seg in g.get("segments", []):
                    if isinstance(seg, list) and len(seg) == 2:
                        a, b = seg[0], seg[1]
                        wall_segments_raw.append({
                            "start": {"col": int(a[0]), "row": int(a[1])},
                            "end":   {"col": int(b[0]), "row": int(b[1])},
                            "type":  g.get("type", "dense"),
                        })
                wall_hexes.extend(expand_wall_group_to_hex_list(g, path_hint=f"board terrain ({board_subdir}) walls[{gi}]"))
            merged["wall_hexes"] = wall_hexes
            if wall_segments_raw:
                merged["walls"] = wall_segments_raw
        merged["terrain_zones"] = terrain_zones
        merged["terrain_icons"] = terrain_icons
        merged["deployment_zones"] = deployment_zones_cfg
        return jsonify({"success": True, "config": merged})
    except FileNotFoundError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 404

@app.route('/api/debug/actions', methods=['GET'])
def get_available_actions():
    """Get list of available semantic actions for debugging."""
    return jsonify({
        "success": True,
        "actions": {
            "move": {
                "description": "Move a unit to specific destination",
                "format": {
                    "action": "move",
                    "unitId": "unit_id_string",
                    "destCol": "integer",
                    "destRow": "integer"
                },
                "example": {
                    "action": "move",
                    "unitId": "player1_unit1",
                    "destCol": 5,
                    "destRow": 3
                }
            },
            "skip": {
                "description": "Skip current unit's activation",
                "format": {
                    "action": "skip",
                    "unitId": "unit_id_string"
                },
                "example": {
                    "action": "skip",
                    "unitId": "player0_unit1"
                }
            }
        }
    })

@app.route('/api/game/ai-turn', methods=['POST'])
def execute_ai_turn():
    """Execute AI turn - pure HTTP wrapper."""
    global engine
    
    if not engine:
        return jsonify({"success": False, "error": "Engine not initialized"}), 400
    
    endless_mode_active = is_endless_duty_mode(engine)
    if endless_mode_active:
        ed_state = require_key(engine.game_state, "endless_duty_state")
        if bool(require_key(ed_state, "inter_wave_pending")):
            serializable_state = _game_state_for_json(engine, for_post_action=True)
            _sync_units_hp_from_cache(serializable_state, engine.game_state)
            _attach_player_types(serializable_state, engine)
            return api_json_response(
                {
                    "success": True,
                    "result": {"action": "ai_turn_skipped", "reason": "inter_wave_pending"},
                    "game_state": serializable_state,
                    "action_logs": [],
                    "endless_duty_state": ed_state,
                }
            )

    # Debug: Check engine state before AI turn (conditional on debug mode)
    debug_mode = os.environ.get('W40K_DEBUG', 'false').lower() == 'true'
        
    if debug_mode:
        print(f"DEBUG AI_TURN: AI model loaded = {hasattr(engine.pve_controller, 'ai_model') and engine.pve_controller.ai_model is not None}")
        
    success, result = engine.execute_ai_turn()
        
    if debug_mode:
        print(f"DEBUG AI_TURN: execute_ai_turn returned success={success}, result={result}")
        print(f"DEBUG AI_TURN: current_phase={engine.game_state.get('phase')}, current_player={engine.game_state.get('current_player')}")
        if engine.game_state.get('phase') == 'shoot':
            print(f"DEBUG AI_TURN: shoot_activation_pool={engine.game_state.get('shoot_activation_pool', [])}")
        print(f"DEBUG AI_TURN: shoot_activation_pool={engine.game_state.get('shoot_activation_pool', [])}")
        
    if not success:
        error_type = result.get("error", "unknown_error")
        if error_type == "not_pve_mode":
            print(f"❌ [API] execute_ai_turn failed: error_type={error_type}, result={result}")
            return jsonify({"success": False, "error": result}), 400
        if error_type == "not_ai_player_turn":
            print(f"ℹ️ [API] execute_ai_turn skipped: error_type={error_type}, result={result}")
            serializable_state = _game_state_for_json(engine, for_post_action=True)
            _sync_units_hp_from_cache(serializable_state, engine.game_state)
            _attach_player_types(serializable_state, engine)
            action_logs = serializable_state.get("action_logs", [])
            engine.game_state["action_logs"] = []
            serializable_state["action_logs"] = []
            return api_json_response({
                "success": True,
                "result": {
                    "action": "ai_turn_skipped",
                    "reason": "not_ai_player_turn",
                    "details": result,
                },
                "game_state": serializable_state,
                "action_logs": action_logs,
                "endless_duty_state": (
                    require_key(engine.game_state, "endless_duty_state")
                    if endless_mode_active
                    else None
                ),
            })
        if error_type == "game_over":
            print(f"ℹ️ [API] execute_ai_turn skipped: error_type={error_type}, result={result}")
            serializable_state = _game_state_for_json(engine, for_post_action=True)
            _sync_units_hp_from_cache(serializable_state, engine.game_state)
            _attach_player_types(serializable_state, engine)
            action_logs = serializable_state.get("action_logs", [])
            engine.game_state["action_logs"] = []
            serializable_state["action_logs"] = []
            return api_json_response({
                "success": True,
                "result": {
                    "action": "ai_turn_skipped",
                    "reason": "game_over",
                    "details": result,
                },
                "game_state": serializable_state,
                "action_logs": action_logs,
                "endless_duty_state": (
                    require_key(engine.game_state, "endless_duty_state")
                    if endless_mode_active
                    else None
                ),
            })
        else:
            print(f"❌ [API] execute_ai_turn failed: error_type={error_type}, result={result}")
            return jsonify({"success": False, "error": result}), 500

    if endless_mode_active:
        ed_post = handle_endless_duty_post_action(engine)
        if isinstance(result, dict):
            result["endless_duty"] = ed_post

    # Convert game state to JSON-serializable format
    serializable_state = _game_state_for_json(engine, for_post_action=True)
    _sync_units_hp_from_cache(serializable_state, engine.game_state)
    _attach_player_types(serializable_state, engine)
        
    # Extract action logs for this specific AI action
    action_logs = serializable_state.get("action_logs", [])
        
    # CRITICAL: Always clear logs after extracting to prevent accumulation
    engine.game_state["action_logs"] = []
    serializable_state["action_logs"] = []
        
    return api_json_response({
        "success": True,
        "result": result,
        "game_state": serializable_state,
        "action_logs": action_logs,
        "endless_duty_state": (
            require_key(engine.game_state, "endless_duty_state")
            if endless_mode_active
            else None
        ),
    })

@app.route('/api/replay/parse', methods=['POST'])
def parse_replay_log():
    """
    Parse train_step.log into replay format.

    Request body:
        {
            "log_path": "train_step.log"  // Optional, defaults to "train_step.log"
        }

    Returns:
        {
            "total_episodes": N,
            "episodes": [...]
        }
    """
    from services.replay_parser import parse_log_file

    data = request.get_json() or {}
    log_path = data.get('log_path', 'train_step.log')

    # Security: Only allow logs in current directory or subdirectories
    if '..' in log_path or log_path.startswith('/'):
        return jsonify({"error": "Invalid log path"}), 400

    if not os.path.exists(log_path):
        return jsonify({"error": f"Log file not found: {log_path}"}), 404

    replay_data = parse_log_file(log_path)
    return jsonify(replay_data)


@app.route('/api/replay/default', methods=['GET'])
def get_default_replay_log():
    """
    Get the default step.log file content for auto-loading in replay mode.

    Returns:
        Raw text content of step.log
    """
    # Look in project root (one directory up from services/)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_path = os.path.join(project_root, 'step.log')

    if not os.path.exists(log_path):
        return jsonify({"error": "step.log not found"}), 404

    with open(log_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Return as plain text for frontend parsing
    from flask import Response
    return Response(content, mimetype='text/plain')

@app.route('/api/replay/file/<filename>', methods=['GET'])
def get_replay_log_file(filename):
    """
    Get a specific replay log file content by filename.

    Args:
        filename: Name of the log file (e.g., "train_step.log")

    Returns:
        Raw text content of the log file
    """
    # Security: Only allow .log files, no path traversal
    if not filename.endswith('.log'):
        return jsonify({"error": "Only .log files are allowed"}), 400

    if '..' in filename or '/' in filename or '\\' in filename:
        return jsonify({"error": "Invalid filename"}), 400

    # Look in project root (one directory up from services/)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_path = os.path.join(project_root, filename)

    if not os.path.exists(log_path):
        return jsonify({"error": f"Log file not found: {filename}"}), 404

    with open(log_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Return as plain text for frontend parsing
    from flask import Response
    return Response(content, mimetype='text/plain')


@app.route('/api/replay/list', methods=['GET'])
def list_replay_logs():
    """
    List available replay log files.

    Returns:
        {
            "logs": [
                {"name": "train_step.log", "size": 12345, "modified": "2025-01-14"},
                ...
            ]
        }
    """
    logs = []

    # Look in project root (one directory up from services/)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Check for train_step.log in project root
    train_step_path = os.path.join(project_root, 'train_step.log')
    if os.path.exists(train_step_path):
        stats = os.stat(train_step_path)
        logs.append({
            'name': 'train_step.log',
            'size': stats.st_size,
            'modified': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stats.st_mtime))
        })

    # Check for other .log files in project root
    for filename in os.listdir(project_root):
        if filename.endswith('.log') and filename != 'train_step.log':
            file_path = os.path.join(project_root, filename)
            if os.path.isfile(file_path):
                stats = os.stat(file_path)
                logs.append({
                    'name': filename,
                    'size': stats.st_size,
                    'modified': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stats.st_mtime))
                })

    return jsonify({'logs': logs})


@app.route('/', methods=['GET'])
def serve_frontend():
    """Serve frontend instructions."""
    return jsonify({
        "message": "W40K Engine API Server",
        "frontend_url": "http://localhost:5175",
        "api_endpoints": {
            "health": "/api/health",
            "auth_register": "/api/auth/register",
            "auth_login": "/api/auth/login",
            "auth_me": "/api/auth/me",
            "start_game": "/api/game/start",
            "execute_action": "/api/game/action",
            "ai_turn": "/api/game/ai-turn",
            "get_state": "/api/game/state",
            "reset_game": "/api/game/reset",
            "board_config": "/api/config/board",
            "debug_actions": "/api/debug/actions",
            "replay_parse": "/api/replay/parse",
            "replay_default": "/api/replay/default",
            "replay_list": "/api/replay/list"
        },
        "instructions": [
            "1. Start frontend: cd frontend && npm run dev",
            "2. API server runs on http://localhost:5001",
            "3. Frontend runs on http://localhost:5175",
            "4. POST /api/game/start with pve_mode:true for AI",
            "5. POST /api/game/action with semantic actions",
            "6. POST /api/game/ai-turn to execute AI Player 2 turn"
        ]
    })

if __name__ == '__main__':
    print("🚀 Starting W40K Engine API Server...")
    print("📡 Server will run on http://localhost:5001")
    print("🎮 Frontend should connect to this API")
    print("✨ Use AI_TURN.md compliant semantic actions")
    
    # Initialize engine on startup
    if initialize_engine():
        print("⚡ Ready to serve the board!")
    else:
        print("⚠️  Engine initialization failed - will retry on first request")
    
    app.run(host='0.0.0.0', port=5001, debug=True)