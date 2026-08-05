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
from pathlib import Path
import hashlib
import secrets
import copy
from functools import wraps
from contextlib import contextmanager
from threading import RLock
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Protocol, Tuple
from uuid import UUID
from flask import Flask, request, jsonify, send_file, Response, g
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
from engine.phase_handlers import movement_handlers, deployment_handlers
from engine.hex_utils import expand_wall_group_to_hex_list
from services.endless_duty_runtime import (
    ED_MODE_CODE,
    ED_SCENARIO_DEFAULT,
    commit_inter_wave_requisition,
    handle_endless_duty_post_action,
    initialize_endless_duty_state,
    is_endless_duty_mode,
)

# `initialize_auth_db()` s'exécute à l'import (bas de ce fichier) et ÉCRIT dans cette base.
# Importer le module suffit donc à la modifier — d'où la surcharge par variable
# d'environnement : elle permet aux tests de viser une base jetable, `config/users.db`
# étant un fichier protégé (cf. CLAUDE.md). Aucune valeur par défaut de repli en prod :
# sans la variable, c'est bien la base réelle qui est utilisée.
AUTH_DB_PATH = os.environ.get(
    "W40K_AUTH_DB_PATH", os.path.join(abs_parent, "config", "users.db")
)
PBKDF2_ITERATIONS = 200000

# Plateau JOUÉ pour chaque option de l'écran de test. `x1` et `x5_44x60` sont le MÊME plateau
# physique 44×60 à deux résolutions ; les entrées `x5` -> board/180x156 et `x10` -> board/360x312
# ont été retirées, ces dossiers n'existent pas (l'option était cassée à la sélection).
BOARD_PATH_MAP = {
    "x1": "board/44x60x1",
    "x5_44x60": "board/44x60x5",
}

# Dossier qui PORTE les scénarios de test. Il ne suit pas la résolution jouée : les scénarios
# sont écrits une seule fois, en subhex x5, et le moteur convertit leurs coordonnées (terrain,
# murs, positions) vers le plateau actif — cf. Documentation/Implémentation/Implémenté/V11_board_44x60x1.md.
TEST_SCENARIO_BOARD_MAP = {
    "x1": "board/44x60x5",
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
    # 2026-07-29 — la branche `isinstance(obj, ParsedWeaponRule)` a ete SUPPRIMEE ici.
    # Le perimetre de ce `default` est homogene : types STDLIB/NUMPY qu'orjson ne connait pas
    # (datetime, UUID, bytes, ndarray, set, Path, deque). `ParsedWeaponRule` y etait le SEUL type
    # metier — un cas particulier greffe, pas un contrat « cet encodeur sait serialiser le
    # domaine ». Le retirer restaure l'homogeneite au lieu de creer une asymetrie.
    # Il est de toute facon inatteignable : `ParsedWeaponRule` n'est construit qu'en
    # `engine/weapons/rules.py` (parse_weapon_rule), dont l'unique chemin de production
    # (`engine/weapons/parser.py`) jette le retour depuis la suppression de `_parsed_rules`.
    # Aucune instance ne survit donc dans le processus, donc aucune ne peut atteindre un payload.
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

    # 2026-07-29 — branche `isinstance(obj, ParsedWeaponRule)` SUPPRIMEE, meme raison que dans
    # `_orjson_default` : le type n'est plus constructible hors du parseur d'armurerie, qui jette
    # son resultat. Ce convertisseur ne traite plus que numpy + les conteneurs standards.

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
    # Combat log : delta d'events depuis la dernière row de timeline. Inutile sur chaque POST /action
    # (le front l'accumule en live via action_logs) ; le Game Log est reconstruit (champ top-level
    # game_log_history) seulement aux réponses de Load / rewind du replay.
    "log_delta",
    "wall_hexes",
    # Geometrie STATIQUE du plateau (160 Ko apres le passage au banc 44x60x1) : renvoyee a chaque
    # action alors que le front dessine le terrain depuis `useGameConfig` / `/api/config/board`.
    # `grep -rn terrain_areas frontend/src` : 0 hit.
    "terrain_areas",
    # Index miroir de `units` construit par le moteur (`unit_by_id`, ~97 Ko) : le front lit `units`,
    # jamais cet index. `grep -rn unit_by_id frontend/src` : 0 hit.
    "unit_by_id",
    # Distances de charge par ancre, dict à clés TUPLE. Le front en reçoit la forme aplatie
    # `result.charge_dest_distances` (charge_handlers.py:4322, useEngineAPI.ts:2797), jamais ce
    # dict : `grep -rn valid_charge_dest_distances frontend/src` → 0 hit.
    "valid_charge_dest_distances",
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
    # Sous-ensemble dérivé des ancres pour contour UI ; le front n’utilise pas ce champ (preview = pool + footprint_zone).
    "move_preview_border",
    # Moteur / RL / debug — pas consommés par l’UI web (réduit serialize + jsonify sur chaque POST /action).
    "last_compliance_data",
    "units_cache_prev",
    "console_logs",
    # Les caches moteur à préfixe `_` (`_move_model_field_cache`, `_charge_model_field_cache`,
    # `_wall_set_cache`, `_unit_los_pair_cache`, `_obs_*`…) ne sont PLUS listés ici : ils sont
    # couverts par la règle de préfixe de `_exclude_game_state_key_for_api_json`, qui les prend
    # tous, y compris ceux qui n'existent pas encore.
})


def _normalise_non_str_keys(game_state: Dict[str, Any]) -> None:
    """Convertit en ``str`` les clés des dicts de premier niveau qui n'en sont pas.

    POURQUOI. JSON n'a pas de clé entière : tout encodeur les convertit, et c'est déjà ce que le
    front reçoit — cette normalisation est iso-payload (les règles ci-dessous sont exactement celles
    de ``make_json_serializable``). Ce qui change, c'est QUI la fait. ``orjson`` REFUSE un dict à
    clé non-``str`` (``TypeError: Dict key must be str``) et son échec n'est pas local : il fait
    retomber la réponse ENTIÈRE sur le pré-parcours récursif Python. Mesure du 2026-07-30 : les
    seuls ``victory_points == {1: 0, 2: 0}`` envoyaient 61 réponses sur 61 dans ce repli, à 22-71 ms
    l'unité contre 1,2 ms pour orjson.

    POURQUOI UNE RÈGLE ET PAS UNE LISTE. La première version listait les clés connues
    (``victory_points``, ``value_at_start``, ``deployment_type_by_player``…). Cette liste a perdu
    la course en une revue : ``valid_move_destinations_pool_by_level`` (clés d'étage), puis
    ``valid_charge_dest_distances`` (clés tuple) sont nées hors d'elle, chacune remettant 100 % des
    réponses de sa phase dans le repli. Le mode de défaillance est silencieux — même JSON, 50x plus
    lent — donc rien ne le signale. La règle prend aussi celles qui n'existent pas encore.

    Coût : un ``isinstance`` par clé de premier niveau (~15 000, soit ~1 ms) contre les 22-71 ms du
    repli qu'elle évite. Premier niveau SEULEMENT : un dict imbriqué à clés exotiques doit être
    exclu du payload (cf. ``_GAME_STATE_EXCLUDE_KEYS``), pas aplati en silence.
    """
    for key, value in game_state.items():
        if not isinstance(value, dict) or all(isinstance(k, str) for k in value):
            continue
        game_state[key] = {
            (k if isinstance(k, str) else ",".join(str(x) for x in k) if isinstance(k, tuple) else str(k)): v
            for k, v in value.items()
        }

_UNITS_CACHE_FRONTEND_KEYS = ("col", "row", "level", "HP_CUR", "player", "orientation", "occupied_hexes_by_model", "orientation_by_model", "models_meta_by_model")

# Clés moteur internes par unité / par arme, non consommées par l'UI web (le grep frontend est vide).
# Filtrées de la réponse JSON (allège chaque POST /action : roster complet × armes), conservées côté moteur.
_UNIT_EXCLUDE_KEYS_FOR_API = frozenset({"_wdc_def_key", "_precheck_cache"})
# 2026-07-29 — ``_parsed_rules`` a été RETIRÉ de cette liste : le parseur d'armurerie ne l'écrit
# plus (cache du défunt ``WeaponRulesApplier``, sans lecteur). ``_wdc_off_key`` reste, lui : il est
# vif, écrit et relu par ``engine/weapon_damage_cache.py``.
_WEAPON_EXCLUDE_KEYS_FOR_API = frozenset({"_wdc_off_key"})


def _slim_weapon_for_api(weapon: Any) -> Any:
    """Copie d'une arme sans les clés moteur internes (``_wdc_off_key``)."""
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
    # Convention du moteur : un `_` initial marque une donnee INTERNE (cache, memo, contexte de
    # sous-phase). Regle de PREFIXE et non liste nominative, parce que la liste perdait la course :
    # chaque nouveau cache d'observation naissait hors d'elle et partait au navigateur en silence.
    # Mesure au 2026-07-30, apres 60 actions d'une partie pvp_test : 555 Ko sur 1,07 Mo de reponse
    # etaient des cles `_` (dont `_grid_static_hex_arrays` 195 Ko, `_shooter_los_models_cache`
    # 166 Ko, `_obs_objective_hex_arrays` 118 Ko), aucune lue par le front. Deux d'entre elles
    # portaient en plus des cles tuple/int, ce qui faisait echouer orjson sur la reponse ENTIERE.
    # `grep -rnE "[\"'\.]_[A-Za-z_]+" frontend/src` : aucune lecture d'une cle `_` du game_state.
    if key.startswith("_"):
        return True
    return False


def _buffer_log_delta(engine_instance, action_logs: List[Dict[str, Any]]) -> None:
    """Accumule les entrées de log de CETTE action dans ``game_state['log_delta']`` AVANT le vidage de
    ``action_logs``. Ce delta (events depuis la dernière row de timeline) est drainé dans
    ``meta['log_delta']`` à la prochaine capture de row (``make_row``) → chaque event stocké UNE fois.

    Chaque entrée reçoit le ``turn`` courant si elle n'en porte pas (ex. ``roll_info``), pour que le
    Game Log reconstruit affiche le bon numéro de tour par ligne. ``logSeq`` (posé par
    append_action_log) donne l'ordre chronologique."""
    if not action_logs:
        return
    gs = engine_instance.game_state
    pending = gs.setdefault("log_delta", [])
    turn = int(gs.get("turn", 1))
    for entry in action_logs:
        stamped = dict(entry)
        if not stamped.get("turn"):
            stamped["turn"] = turn
        pending.append(stamped)


def _reconstruct_game_log(party_name: Optional[str], up_to_key: Optional[tuple],
                          include_pending_from=None) -> List[Dict[str, Any]]:
    """Reconstruit le combat log d'une partie jusqu'à ``up_to_key`` (concat des ``meta['log_delta']``
    des rows de timeline). ``include_pending_from`` (un engine) ajoute en fin le delta courant non
    encore committé (``game_state['log_delta']``) — pour le retour live. Flush le writer async d'abord
    pour que les rows tout juste enfilées soient bien sur disque avant lecture."""
    if not party_name:
        log: List[Dict[str, Any]] = []
    else:
        _SAVE_STORE.flush()
        log = list(_SAVE_STORE.reconstruct_log(party_name, up_to_key))
    if include_pending_from is not None:
        pending = include_pending_from.game_state.get("log_delta")
        if isinstance(pending, list):
            log.extend(pending)
    return log


# ─────────────────────────────────────────────────────────────────────────────
# CONTRATS MOTEUR DES HELPERS DE L'API
#
# Chaque helper declare ce qu'il lit REELLEMENT du moteur, pas `W40KEngine` par habitude.
# Une annotation plus large que le besoin ne protege rien : elle force les tests a
# `cast(W40KEngine, faux_moteur)`, et le cast ETEINT la verification au lieu de la faire.
# Les protocoles ci-dessous sont donc les seules dependances vraies, etablies par lecture
# de chaque corps et de sa chaine d'appel.
#
# Tous en `@property` (lecture seule) plutot qu'en attribut : un protocole a attribut est
# INVARIANT, ce qui rejetterait tout porteur dont l'attribut a un type plus precis, alors
# que ces helpers n'en font qu'une lecture. Le dict `game_state`, lui, reste mute en place
# (affectation de cle) — ce qu'une property autorise sans reserve.
# ─────────────────────────────────────────────────────────────────────────────


class _UnitDataSource(Protocol):
    """La SEULE chose que les deux constructeurs d'unites demandent a un registre.

    Verifie sur toute la chaine d'appel du format scenario, pas seulement en surface :
    `_fold_attached_characters` (game_state.py l.850, 858) et `_build_enhanced_unit`
    (l.1088) ne touchent au registre que par `get_unit_data`.
    """

    def get_unit_data(self, unit_type: str) -> Dict[str, Any]: ...


class _UnitRegistryHolder(Protocol):
    """Ce que `_build_units_from_army_config` et `_build_units_from_scenario_army` lisent
    REELLEMENT de leur moteur.

    Annoncer `W40KEngine` mentait : ni l'une ni l'autre ne touche `game_state`, un manager
    ou une methode du moteur — uniquement `unit_registry`. La version « format scenario »
    a l'air plus gourmande parce qu'elle passe par un `GameStateManager`, mais elle le
    CONSTRUIT elle-meme et lui passe le registre : le moteur appelant n'y entre pas. Un
    protocole COMMUN, donc, plutot que deux declarations paralleles qui divergeraient.

    Lecture seule (`@property`) et non `Optional[...]` en attribut mutable : un protocole a
    attribut est invariant, ce qui rejetterait tout porteur dont le registre a un type plus
    precis — alors que les deux fonctions n'en font qu'une lecture.
    """

    @property
    def unit_registry(self) -> Optional[_UnitDataSource]: ...


class _GameStateHolder(Protocol):
    """Porteur d'un `game_state`. Base commune aux trois contrats suivants."""

    @property
    def game_state(self) -> Dict[str, Any]: ...


class _ObjectiveControlRefresher(Protocol):
    """Ce que `_game_state_for_json` demande au `state_manager` : la frontiere 14.02, rien d'autre."""

    def refresh_objective_control_on_boundary(self, game_state: Dict[str, Any]) -> bool: ...


class _SerializableGameSource(_GameStateHolder, Protocol):
    """Ce que `_game_state_for_json` lit reellement : `game_state` + le refresh 14.02.

    Ce parametre n'avait AUCUNE annotation : implicitement `Any`, donc aucun faux moteur
    n'etait verifie (d'ou l'absence de `cast` cote test — un `Any` accepte tout). Le
    declarer ferme le trou sans rien exiger de plus que ce que le corps consomme.
    """

    @property
    def state_manager(self) -> _ObjectiveControlRefresher: ...


class _PlayerTypesSource(_GameStateHolder, Protocol):
    """Ce que `_attach_player_types` lit reellement : le mode courant + `game_state`.

    Un cran plus large que `_UnitRegistryHolder` (deux membres au lieu d'un), mais toujours
    tres loin d'un moteur : aucune methode appelee, aucun manager, aucun handler.
    `current_mode_code` est `Optional[str]` parce que le moteur l'initialise a None
    (w40k_core.py l.117) — le helper leve explicitement tant qu'il n'est pas renseigne.
    """

    @property
    def current_mode_code(self) -> Optional[str]: ...


class _EndPhaseEngine(_GameStateHolder, Protocol):
    """Ce que `_execute_end_phase_action` consomme : `game_state` + `execute_semantic_action`.

    Contrat le plus riche de la famille, car ce helper PILOTE le moteur (skip par unite puis
    `advance_phase`) au lieu de seulement le lire. Il reste malgre tout descriptible : une
    methode publique et un dict. Ni `state_manager`, ni handler, ni `unit_registry`, ni
    espace gym n'y entrent — ni directement, ni via `execute_semantic_action`, dont le
    helper ne consomme que le `Tuple[bool, Dict[str, Any]]` retourne.
    """

    def execute_semantic_action(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]: ...


def _game_state_for_json(
    engine_instance: _SerializableGameSource,
    *,
    for_post_action: bool = False,
    mask_loops_client_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """Return game_state dict with internal/heavy fields excluded.

    Strips large sets (wall_hexes, occupied_positions,
    enemy_adjacent_hexes, los_cache), champs moteur inutiles au client, et
    ``move_preview_border`` (non consommé par l’UI ; la preview move repose sur
    ``valid_move_destinations_pool`` et ``move_preview_footprint_zone`` / span).
    Si ``move_preview_footprint_mask_loops`` est présent (contours monde), supprime
    ``move_preview_footprint_zone`` du JSON (évite des milliers de couples hex).
    Si ``valid_move_destinations_pool`` est non vide, supprime ``preview_hexes`` (alias du même pool).
    Trims units_cache to (col, row, HP_CUR, player, orientation).
    Exclut aussi snapshots ``units_cache_prev``, ``last_compliance_data``, ``console_logs``, la
    table statique ``weapon_damage_table`` (moteur uniquement), la config complète ``config``
    (déjà chargée côté client), la géométrie statique ``terrain_areas`` (le front la lit via
    ``/api/config/board``), l'index miroir ``unit_by_id``, les caches d’adjacence par joueur
    ``enemy_adjacent_hexes_player_*`` / ``enemy_adjacent_counts_player_*``, et TOUTE clé à préfixe
    ``_`` — caches et mémos moteur, par convention jamais consommés par l'UI
    (voir ``_GAME_STATE_EXCLUDE_KEYS`` et ``_exclude_game_state_key_for_api_json``).

    Normalise enfin en ``str`` les clés non-``str`` des dicts de premier niveau
    (``_normalise_non_str_keys``) : iso-payload, mais c'est ce qui rend la réponse encodable par
    ``orjson`` au lieu de retomber sur le pré-parcours récursif ``make_json_serializable``.

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

    # Objective control (Rule 14.02) : détermine à la FIN de chaque phase/tour, pas en continu.
    # Détection de frontière + checkpoint = `refresh_objective_control_on_boundary` (moteur),
    # partagée avec le chemin gym : une seule implémentation pour PvP et entraînement.
    engine_instance.state_manager.refresh_objective_control_on_boundary(engine_instance.game_state)

    had_engine_mask_loops = bool(engine_instance.game_state.get("move_preview_footprint_mask_loops"))
    gs = {
        k: v for k, v in engine_instance.game_state.items()
        if k not in _GAME_STATE_EXCLUDE_KEYS and not _exclude_game_state_key_for_api_json(k)
    }
    _normalise_non_str_keys(gs)
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
    # Réserves stratégiques (20.01) : points engagés / plafond, PAR JOUEUR. Calculé par le
    # moteur et transmis tel quel — le client ne doit pas refaire le plafond de 50 %, sous peine
    # d'afficher un ratio qui n'est pas celui qui décide de l'acceptation d'un dépôt.
    gs["strategic_reserves"] = _strategic_reserves_summary(engine_instance.game_state)
    if for_post_action:
        gs.pop("objectives", None)
    return gs


def _maybe_precompute_ingress_pools(engine_instance: Any) -> None:
    """Réchauffe l'aire d'arrivée des réserves du joueur actif, si la phase s'y prête.

    Sans objet hors phase de mouvement et sans réserve éligible : `precompute_ingress_pools`
    n'itère alors sur rien. Sur un état déjà réchauffé, tout est servi par les mémos (pool et
    contours), donc l'appeler à chaque action ne coûte que quelques millisecondes.

    Aucune exception avalée : si le réchauffage lève, c'est que l'état est incohérent et la même
    erreur reviendrait au clic du joueur — la masquer ne ferait que la déplacer.
    """
    gs = engine_instance.game_state
    if gs.get("phase") != "move":  # get allowed (état non initialisé)
        return
    from engine.phase_handlers.movement_handlers import precompute_ingress_pools

    precompute_ingress_pools(gs)


def _strategic_reserves_summary(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """``{player: {used_points, cap_points, placeable_unit_ids}, "last_round": n}`` — 20.01/20.04.

    Aucune arithmétique ici : les grandeurs viennent de `strategic_reserves_usage`, LE calcul qui
    décide aussi de l'acceptation d'un dépôt. Les refaire dans la couche API ferait afficher un
    ratio qui n'est pas celui qui refuse le dépôt — le défaut même que le passage par le serveur
    cherche à éviter côté client.

    Deux grandeurs de plus, pour la MÊME raison — l'UI PvP ne doit rejouer aucune règle en TS :

      - ``placeable_unit_ids`` : les unités que `deployment_place_in_strategic_reserves` accepte
        RÉELLEMENT en l'état, c'est-à-dire l'intersection de ses deux préconditions (être encore à
        poser, et passer `unit_can_be_placed_in_strategic_reserves` — plafond ET FORTIFICATION).
        Le client ne propose le dépôt que pour ces ids ; il n'a ni le plafond restant ni les
        mots-clés à réinterpréter.
      - ``last_round`` : le round au bout duquel les réserves non arrivées sont détruites (20.04),
        lu sur la constante moteur. Le popup d'avertissement du client s'y accroche au lieu de
        coder « 3 » en dur.
    """
    if "points_limit" not in game_state:  # état non initialisé (pas de partie en cours)
        return {}
    from engine.phase_handlers.deployment_handlers import (
        _get_deployable_remaining,
        strategic_reserves_usage,
        unit_can_be_placed_in_strategic_reserves,
    )
    from engine.phase_handlers.movement_handlers import STRATEGIC_RESERVES_LAST_ROUND

    # Hors phase de déploiement il n'y a plus rien à mettre en réserves : `deployment_state` peut
    # être absent (moteur nu, partie chargée en cours) et la liste est alors vide, ce qui est la
    # vérité — pas un repli masquant. Quand il est là, c'est `_get_deployable_remaining` qui lit,
    # avec sa résolution de clé int-ou-str : la convention de clés de `deployable_units` n'a pas à
    # être réaffirmée ici (5e copie) pour diverger le jour où elle sera normalisée.
    deployment_state = game_state.get("deployment_state")  # get allowed (phase déjà terminée)
    summary: Dict[str, Any] = {"last_round": int(STRATEGIC_RESERVES_LAST_ROUND)}
    for player in (1, 2):
        used, cap = strategic_reserves_usage(game_state, player)
        pending = (
            _get_deployable_remaining(deployment_state, player)
            if isinstance(deployment_state, dict)
            else []
        )
        summary[str(player)] = {
            "used_points": used,
            "cap_points": cap,
            "placeable_unit_ids": [
                str(uid)
                for uid in pending
                if unit_can_be_placed_in_strategic_reserves(game_state, str(uid))
            ],
        }
    return summary


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


def _serialize_captured_view(engine_instance, captured_state: Dict[str, Any]) -> Dict[str, Any]:
    """Sérialise un état capturé (save-point) SANS muter la partie vivante (aperçu view) :
    swap temporaire de game_state, comme le mode 'view' des snapshots."""
    from services.game_snapshots import rebuild_game_state
    rebuilt = rebuild_game_state(engine_instance, captured_state)
    live_gs = engine_instance.game_state
    try:
        engine_instance.game_state = rebuilt
        serializable = _game_state_for_json(engine_instance)
        _sync_units_hp_from_cache(serializable, engine_instance.game_state)
        _attach_player_types(serializable, engine_instance)
    finally:
        engine_instance.game_state = live_gs
    return serializable


def _attach_player_types(serializable_state: Dict[str, Any], engine_instance: _PlayerTypesSource) -> None:
    """
    Ensure player_types is present in both engine.game_state and serialized response.

    Lecture directe et non `getattr(..., None)` : le protocole GARANTIT l'attribut, donc le
    defaut None n'aurait plus servi qu'a transformer un porteur invalide en `ValueError`
    trompeuse au lieu de l'`AttributeError` qui nomme le vrai probleme.
    """
    current_mode_code = engine_instance.current_mode_code
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
    """Connexion neuve, à fermer par l'appelant. Réservée aux ÉCRITURES.

    Le répertoire est créé par `initialize_auth_db()` au démarrage, pas ici : depuis la
    fermeture globale de l'API, l'accès à cette base a lieu à CHAQUE requête, où le
    `makedirs` ne pouvait plus rien faire.

    Les écritures gardent une connexion propre : partagée, un échec en cours d'écriture
    laisserait une transaction pendante sur la connexion des autres requêtes.
    """
    connection = sqlite3.connect(AUTH_DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


_auth_read_connection: Optional[sqlite3.Connection] = None
_auth_read_connection_path: Optional[str] = None
_AUTH_READ_LOCK = RLock()


@contextmanager
def auth_db_read_cursor():
    """Connexion de LECTURE partagée par TOUT le process, sérialisée par un verrou.

    La porte interroge cette base à chaque requête (session, puis permissions quand une
    partie tourne). Mesuré : ~189 µs par requête pour connexion + résolution des
    permissions, contre ~19 µs sur une connexion déjà ouverte — l'essentiel du coût est
    l'ouverture et l'analyse du schéma à froid, payées jusqu'à 40 fois par seconde sur les
    prévisualisations au survol.

    Partagée par PROCESS et non par thread : le serveur de dev Werkzeug est en HTTP/1.0
    sans keep-alive, donc `ThreadingMixIn` crée un thread PAR REQUÊTE. Un `threading.local`
    y serait vide à chaque fois et n'économiserait rien — l'optimisation n'existerait que
    dans les tests, qui tournent dans un seul thread.

    `check_same_thread=False` est donc obligatoire, et le verrou est ce qui rend l'usage
    concurrent sûr : toute lecture se fait à l'intérieur du `with`. Réservée aux lectures —
    les écritures gardent une connexion propre (cf. `_get_auth_db_connection`), pour qu'un
    échec ne laisse pas de transaction pendante sur la connexion commune.

    Rouverte si `AUTH_DB_PATH` change : les tests le réaffectent, une connexion mémorisée
    pointerait sinon sur la base précédente.
    """
    global _auth_read_connection, _auth_read_connection_path
    with _AUTH_READ_LOCK:
        if _auth_read_connection is None or _auth_read_connection_path != AUTH_DB_PATH:
            if _auth_read_connection is not None:
                _auth_read_connection.close()
            _auth_read_connection = sqlite3.connect(AUTH_DB_PATH, check_same_thread=False)
            _auth_read_connection.row_factory = sqlite3.Row
            _auth_read_connection_path = AUTH_DB_PATH
        yield _auth_read_connection


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

    with auth_db_read_cursor() as connection:
        row = connection.execute(
            """
            SELECT u.id AS user_id, u.login AS login, p.id AS profile_id, p.code AS profile_code
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            JOIN profiles p ON p.id = u.profile_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()

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
    # `dirname` est vide si AUTH_DB_PATH est un simple nom de fichier (surcharge par
    # variable d'environnement) : `makedirs("")` lèverait FileNotFoundError à l'import.
    auth_db_dir = os.path.dirname(AUTH_DB_PATH)
    if auth_db_dir:
        os.makedirs(auth_db_dir, exist_ok=True)
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
        endless_duty_row = cursor.execute(
            "SELECT id FROM game_modes WHERE code = ?",
            (ED_MODE_CODE,),
        ).fetchone()
        if (
            pve_row is None
            or pve_test_row is None
            or pvp_row is None
            or pvp_test_row is None
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
import logging
logging.getLogger('werkzeug').setLevel(logging.WARNING)
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

# Snapshots temporels (rewind / playback par phase) — mode PvP / PvP test uniquement.
from services.game_snapshots import GameSnapshotStore
_SNAPSHOT_STORE = GameSnapshotStore()
# Persistance disque des snapshots (option gameplay du menu). False = mémoire seule.
_SNAPSHOT_PERSIST_ENABLED = False

# Saves manuelles (un fichier plat par save) sous logs/pvp_saves/.
from services.game_saves import SaveStore, progress_key_from_gs, progress_key_from_meta
# Répertoire de persistance (snapshots + saves), configurable via le menu. Défaut : logs/.
_PERSIST_DIR = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')), "logs")
_SAVE_STORE = SaveStore(os.path.join(_PERSIST_DIR, "pvp_saves"))
# Arrêt propre du process : écrit les dernières rows de timeline encore en file d'attente.
import atexit
atexit.register(_SAVE_STORE.flush)
# Le répertoire doit être explicitement choisi avant toute save (manuelle ou auto).
_PERSIST_DIR_SET = False
# Sauvegarde automatique : off par défaut ; granularité "phase" ou "turn".
_AUTOSAVE_ENABLED = False
_AUTOSAVE_GRANULARITY = "phase"
_AUTOSAVE_LAST_KEY: Optional[Tuple[int, int]] = None
# Timeline par action : (turn, phase, unit_activation_count) de la dernière row capturée.
# Sert à ne capturer une row QUE sur progression réelle (pas sur les clics sans effet).
_TIMELINE_LAST_KEY: Optional[Tuple[int, str, int]] = None


def _reset_timeline_last(engine_instance) -> None:
    """Aligne le tracker sur l'état courant (après start/reset/Load/Resume) pour repartir proprement."""
    global _TIMELINE_LAST_KEY
    gs = engine_instance.game_state
    _TIMELINE_LAST_KEY = (int(gs["turn"]), str(gs["phase"]), int(gs.get("unit_activation_count", 0)))


def _timeline_capture(engine_instance) -> None:
    """Capture une row de timeline (append async) à chaque PROGRESSION réelle (activation d'unité /
    changement de phase / de tour). Gated : uniquement si enregistrement activé + répertoire défini +
    partie courante. La copie de l'état est synchrone (sous le lock engine) ; l'écriture est async."""
    global _TIMELINE_LAST_KEY
    if getattr(engine_instance, "current_mode_code", None) not in ("pvp", "pvp_test"):
        return
    if not (_SNAPSHOT_PERSIST_ENABLED and _PERSIST_DIR_SET):
        return
    party = _SAVE_STORE.current_party()
    if not party:
        return
    gs = engine_instance.game_state
    key = (int(gs["turn"]), str(gs["phase"]), int(gs.get("unit_activation_count", 0)))
    prev = _TIMELINE_LAST_KEY
    if key == prev:
        return  # pas de progression → pas de row
    # Sans autosave, toute progression est une simple row "action" (playback ⏮⏭ complet mais rien dans
    # le menu Select) ; les points "turn"/"phase" visibles ne naissent que si l'autosave est active.
    if not _AUTOSAVE_ENABLED:
        kind = "action"
    elif prev is None or key[0] != prev[0]:
        kind = "turn"
    elif key[1] != prev[1]:
        kind = "phase"
    else:
        kind = "action"
    _TIMELINE_LAST_KEY = key
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    _SAVE_STORE.enqueue_row(party, _SAVE_STORE.make_row(engine_instance, ts, kind))


def _maybe_autosave(engine_instance, point_ts: str) -> None:
    """Ajoute un save-point auto à la partie courante selon la granularité (dedup au tour)."""
    global _AUTOSAVE_LAST_KEY
    gs = engine_instance.game_state
    key = (int(gs["turn"]), int(gs["current_player"]))
    if _AUTOSAVE_GRANULARITY == "turn" and key == _AUTOSAVE_LAST_KEY:
        return
    _AUTOSAVE_LAST_KEY = key
    kind = "auto_turn" if _AUTOSAVE_GRANULARITY == "turn" else "auto_phase"
    _SAVE_STORE.add_point(engine_instance, point_ts, "", kind)


def _capture_and_autosave(engine_instance, initial: bool = False) -> None:
    """Point unique de capture PvP : snapshot de début de phase (si nouvelle) + persistance + auto-save.

    ``initial=True`` (start/reset) → nouvelle PARTIE avec son save-point de départ ; sinon save-point
    auto ajouté à la partie courante."""
    global _AUTOSAVE_LAST_KEY
    if getattr(engine_instance, "current_mode_code", None) not in ("pvp", "pvp_test"):
        return
    if not _SNAPSHOT_STORE.maybe_capture(engine_instance):
        return
    if _SNAPSHOT_PERSIST_ENABLED:
        _persist_snapshots_to_disk()
    # Un répertoire défini suffit pour l'ancre game_start ; les points de phase/tour dépendent du toggle.
    if not _PERSIST_DIR_SET:
        return
    from datetime import datetime
    now = datetime.now()
    if initial:
        # Ancre "game_start" créée à chaque démarrage/reset dès qu'un répertoire est défini,
        # indépendamment de la sauvegarde automatique → toujours un point de début de partie.
        gs = engine_instance.game_state
        _AUTOSAVE_LAST_KEY = (int(gs["turn"]), int(gs["current_player"]))
        _SAVE_STORE.start_party(
            engine_instance, now.strftime("%Y%m%d_%H-%M"), now.strftime("%Y%m%d-%H%M%S")
        )
        # Autosave actif → la partie est visible dès le start : on promeut le working immédiatement.
        # Autosave inactif → il reste caché jusqu'à la 1re save manuelle (promotion différée).
        if _AUTOSAVE_ENABLED:
            _SAVE_STORE.promote()
        _reset_timeline_last(engine_instance)
    # Les rows de progression (turn/phase/action) sont posées par _timeline_capture après chaque
    # action ; l'ancien auto-save par phase est superséd é par la timeline unifiée.


# --- Persistance côté serveur de la config des saves (survit au redémarrage de l'api) ----------

def _save_config_path() -> str:
    """Fichier de config des saves (chemin fixe, indépendant du répertoire choisi)."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    return os.path.join(root, "logs", "save_config.json")


def _persist_save_config() -> None:
    import json
    path = _save_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "persist_enabled": _SNAPSHOT_PERSIST_ENABLED,
            "directory": _PERSIST_DIR,
            "dir_set": _PERSIST_DIR_SET,
            "autosave_enabled": _AUTOSAVE_ENABLED,
            "granularity": _AUTOSAVE_GRANULARITY,
        }, f, ensure_ascii=False)


def _load_save_config() -> None:
    """Recharge la config des saves au démarrage de l'api (avant tout /game/start)."""
    global _SNAPSHOT_PERSIST_ENABLED, _PERSIST_DIR, _PERSIST_DIR_SET
    global _AUTOSAVE_ENABLED, _AUTOSAVE_GRANULARITY
    import json
    path = _save_config_path()
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        print(f"[save_config] fichier illisible, config par défaut: {e}")
        return
    _SNAPSHOT_PERSIST_ENABLED = bool(cfg.get("persist_enabled", False))
    _PERSIST_DIR = str(cfg.get("directory", _PERSIST_DIR))
    _PERSIST_DIR_SET = bool(cfg.get("dir_set", False))
    _AUTOSAVE_ENABLED = bool(cfg.get("autosave_enabled", False))
    gran = str(cfg.get("granularity", "phase"))
    _AUTOSAVE_GRANULARITY = gran if gran in ("phase", "turn") else "phase"
    _SAVE_STORE.set_directory(os.path.join(_PERSIST_DIR, "pvp_saves"))


_load_save_config()


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

def _configured_agent_key() -> str:
    """Identité de l'agent unique depuis config/config.json (defaults.agent_key).

    Même source de vérité que ``UnitRegistry.AGENT_KEY`` : les modes de test (PvE/pve_test/ED)
    qui forcent un agent lisent cette clé au lieu de la hardcoder. No fallback : clé absente ->
    ConfigurationError (jamais un agent en dur qui pourrait ne plus exister, cf. retrait CoreAgent).
    """
    from config_loader import get_config_loader
    cfg = get_config_loader().load_config("config", force_reload=False)
    return require_key(require_key(cfg, "defaults"), "agent_key")


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

def _build_scenario_engine_config(scenario_file: str):
    """`(config, unit_registry, config_loader, agent_keys)` pour construire le moteur.

    POINT UNIQUE de traduction « résultat du loader → config d'entrée du moteur ». PvP
    (`initialize_engine`) et PvE (`initialize_test_engine`) en avaient chacun une copie
    byte-identique de 68 lignes : les 10 extractions de `scenario_result`, la résolution des
    objectifs primaires, et le dict lui-même. C'est le motif qui a fait perdre `points_limit` et
    `roster_info` en chemin — pas parce qu'ils étaient difficiles à transmettre, mais parce que
    les transmettre demandait de le faire deux fois. Ce qui diverge légitimement entre les deux
    appelants (message d'absence de fichier, configs d'agents, `forced_agent_key`) reste chez eux.
    """
    from ai.unit_registry import UnitRegistry
    from config_loader import get_config_loader, require_engine_game_config_sections
    from engine.game_state import GameStateManager

    unit_registry = UnitRegistry()
    config_loader = get_config_loader()
    board_config = config_loader.get_board_config()
    game_config = config_loader.get_game_config()

    scenario_manager = GameStateManager({"board": board_config}, unit_registry)
    scenario_result = scenario_manager.load_units_from_scenario(scenario_file, unit_registry)
    scenario_primary_objective_ids = scenario_result.get("primary_objectives")
    scenario_primary_objective_id = scenario_result.get("primary_objective")

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
        **require_engine_game_config_sections(game_config),
        "units": require_key(scenario_result, "units"),
        "primary_objective": primary_objective_config,
        "scenario_wall_hexes": scenario_result.get("wall_hexes"),
        "scenario_dense_wall_hexes": scenario_result.get("dense_wall_hexes"),
        "scenario_objectives": scenario_result.get("objectives"),
        "scenario_terrain_areas": scenario_result.get("terrain_areas"),
        # Taille de bataille (20.01) et rosters : PRODUITS par le loader ci-dessus, donc ils se
        # transmettent comme les autres champs de scénario. Les omettre faisait rendre cap=0 à
        # `strategic_reserves_usage` — aucune mise en réserve possible en partie, même quand le
        # scénario déclare sa `scale`. Aujourd'hui ce sont les scénarios d'agents (chemin
        # PvE/test) qui la déclarent ; aucun `scenario_pvp*.json` n'en a encore, et pour ceux-là
        # `None` reste la valeur juste : règle invérifiable, donc fermée.
        "points_limit": scenario_result.get("points_limit"),
        "roster_info": scenario_result.get("roster_info"),
        "deployment_type": scenario_result.get("deployment_type"),
        "deployment_type_by_player": scenario_result.get("deployment_type_by_player"),
        "deployment_zone": scenario_result.get("deployment_zone"),
        "deployment_pools": scenario_result.get("deployment_pools"),
    }

    agent_keys = get_agents_from_scenario(scenario_file, unit_registry)
    if not agent_keys:
        raise ValueError("No agents found in scenario")
    return config, unit_registry, config_loader, agent_keys


def _default_board_scenario_path(scenario_name: str) -> str:
    """Chemin du scénario `scenario_name` dans le dossier de board par défaut.

    UN seul endroit résout « quel dossier de board porte les scénarios » : PvP et PvE partaient
    du même besoin et n'en avaient pas la même réponse — le PvE pointait encore la copie
    `config/scenario_pve.json` d'avant la migration des scénarios sous
    `config/board/<board>/scenario/`, restée au format à clé `objectives` et donc refusée par le
    loader. Le mode PvE ne démarrait plus.
    """
    from config_loader import get_config_loader as _gcl

    _cfg = _gcl().load_config("config", force_reload=False)
    # Pas de littéral de repli : "x5" ne désigne plus aucune entrée des deux tables.
    board_path = require_key(require_key(_cfg, "defaults"), "test_board")
    if board_path not in TEST_SCENARIO_BOARD_MAP:
        raise ValueError(
            f"config.json defaults.test_board = {board_path!r} : attendu l'un de "
            f"{sorted(TEST_SCENARIO_BOARD_MAP)}"
        )
    return os.path.join("config", TEST_SCENARIO_BOARD_MAP[board_path], "scenario", scenario_name)


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
            scenario_file = _default_board_scenario_path("scenario_pvp.json")
        elif not isinstance(scenario_file, str):
            raise ValueError(f"scenario_file must be a string if provided (got {type(scenario_file).__name__})")

        # Verify scenario file exists - no fallback
        if not os.path.exists(scenario_file):
            raise FileNotFoundError(
                f"Game scenario file not found: {scenario_file}\n"
                f"This file is required for the API server.\n"
                f"Training scenarios are in config/agents/<agent>/scenarios/"
            )

        config, unit_registry, config_loader, agent_keys = _build_scenario_engine_config(
            scenario_file
        )
        
        
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
            scenario_file = _default_board_scenario_path("scenario_pve.json")
        elif not isinstance(scenario_file, str):
            raise ValueError(f"scenario_file must be a string if provided (got {type(scenario_file).__name__})")

        # Verify scenario file exists - no fallback
        if not os.path.exists(scenario_file):
            raise FileNotFoundError(
                f"PvE scenario file not found: {scenario_file}\n"
                f"This file is required for PvE mode.\n"
                f"Create it in config/board/<board>/scenario/ (le loader y résout wall_ref/terrain_ref)."
            )

        config, unit_registry, config_loader, agent_keys = _build_scenario_engine_config(
            scenario_file
        )
        
        
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

# Routes accessibles SANS session valide. Tout le reste est fermé par le `before_request`
# ci-dessous : une route nouvelle ou oubliée est donc fermée par défaut, jamais ouverte.
# Il n'existe aucune route de création de compte (F12) : les comptes sont créés en SQL.
_PUBLIC_ENDPOINTS: set[str] = set()


def public_endpoint(view_func):
    """Marque une vue comme accessible sans session.

    L'exemption est déclarée SUR la route elle-même, pas dans une liste distante : une
    route renommée emporte son exemption avec elle. Une liste de chemins en dur se
    périmerait en silence, et pour `/api/auth/login` la panne serait un verrouillage
    total (plus personne ne peut se connecter), pas une simple fuite.
    """
    _PUBLIC_ENDPOINTS.add(view_func.__name__)
    return view_func


# Vues qui CHANGENT le mode de la partie en cours : le contrôle RBAC de la porte porte sur
# le mode courant, il bloquerait donc à tort une bascule légitime vers un mode autorisé.
# Elles valident elles-mêmes le mode DEMANDÉ (cf. `_is_mode_allowed` dans `start_game`).
_MODE_CHANGING_ENDPOINTS: set[str] = set()


def changes_game_mode(view_func):
    """Exempte une vue du contrôle RBAC sur le mode courant — elle doit valider le sien."""
    _MODE_CHANGING_ENDPOINTS.add(view_func.__name__)
    return view_func


# Vues qui n'agissent pas sur la partie en cours (catalogues, config, replays, identité) :
# leur appliquer le RBAC de mode renverrait 403 à un testeur `pve` pendant toute la séquence
# de démarrage du front dès qu'une partie `pvp` traîne dans le process. Le mode reste
# contrôlé PAR DÉFAUT : une route non listée ici l'est, y compris une route nouvelle.
_MODE_AGNOSTIC_ENDPOINTS: set[str] = set()


def mode_agnostic(view_func):
    """Marque une vue comme n'agissant pas sur la partie en cours (pas de RBAC de mode)."""
    _MODE_AGNOSTIC_ENDPOINTS.add(view_func.__name__)
    return view_func


def _current_game_mode() -> Optional[str]:
    """Mode de la partie en cours, `None` si aucune partie n'est démarrée."""
    if engine is None:
        return None
    mode_code = getattr(engine, "current_mode_code", None)
    return mode_code if isinstance(mode_code, str) and mode_code else None


def _captured_mode(captured_state: Dict[str, Any]) -> Optional[str]:
    """Mode de jeu d'un état CAPTURÉ (`capture_live_state`), pour les routes de chargement.

    Un état capturé est une enveloppe `{"game_state": ..., "engine_attrs": ...}` : lire
    `current_mode_code` à sa racine rend toujours `None`, donc un refus systématique.
    `restore_snapshot` n'a pas ce besoin — `build_game_state()` lui rend un game_state plat.
    """
    game_state = captured_state.get("game_state")
    if not isinstance(game_state, dict):
        return None
    mode = game_state.get("current_mode_code")
    return mode if isinstance(mode, str) and mode else None


def _forbidden_mode_response(mode: Optional[str]):
    """403 si le profil de l'utilisateur courant n'a pas droit à `mode`, sinon `None`.

    À appeler par toute vue qui REMPLACE le mode de la partie (chargement d'une sauvegarde,
    restauration d'un snapshot) : la porte juge le mode COURANT, elle ne peut rien dire du
    mode qu'on s'apprête à charger. Sans ce contrôle, un profil `pve` en partie `pve`
    charge une partie `pvp` sans que personne ne valide le mode cible.

    Doit être appelée AVANT la mutation de l'engine — refuser après coup laisserait l'état
    interdit en place.

    Un mode absent ou vide est REFUSÉ, jamais laissé passer : un état sans mode ne peut pas
    être autorisé par défaut, ce serait exactement le contournement que ce contrôle vise.
    """
    if not isinstance(mode, str) or not mode:
        return jsonify({
            "success": False,
            "error": "Game state has no 'current_mode_code': cannot authorize access",
        }), 403
    with auth_db_read_cursor() as connection:
        permissions = _resolve_permissions_for_profile(connection, g.auth_user["profile_id"])
    if _is_mode_allowed(mode, permissions):
        return None
    return jsonify({
        "success": False,
        "error": f"Profile is not allowed to play mode '{mode}'",
    }), 403


@app.before_request
def require_authenticated_session():
    """Ferme toute l'API par défaut : seules les vues `@public_endpoint` sont ouvertes.

    Le filtrage porte sur `request.endpoint` (nom de la vue résolue par le routeur) et non
    sur `request.path` : l'exemption suit ainsi la vue, et changer l'URL d'une route ne
    peut pas laisser derrière elle une entrée de liste blanche périmée — silencieuse dans
    le cas d'une route protégée, mais synonyme de verrouillage total pour `login`.

    Une URL qui ne correspond à aucune route a `endpoint` à `None` : elle reçoit donc 401
    plutôt que 404, ce qui évite au passage de révéler quelles routes existent.

    Les préflights CORS (`OPTIONS`) sont laissés passer : le navigateur les émet sans
    header `Authorization`, les bloquer casserait tout appel cross-origin côté front.

    Le RBAC (modes de jeu autorisés par profil) est appliqué ICI et non sur chaque route
    de jeu : le vérifier au seul démarrage de partie laissait un utilisateur agir sur une
    partie déjà lancée dont son profil interdit le mode.
    """
    if request.method == "OPTIONS":
        return None
    if request.endpoint in _PUBLIC_ENDPOINTS:
        return None

    user_row, error_response = _get_authenticated_user_or_response()
    if error_response is not None:
        return error_response
    if user_row is None:
        # Contrat du helper : jamais (None, None). Une violation doit être bruyante — la
        # laisser passer authentifierait une requête sans utilisateur.
        raise RuntimeError("_get_authenticated_user_or_response returned no user and no error")
    # Évite aux vues un second aller-retour SQLite pour le même token (cf. `g.auth_user`).
    g.auth_user = user_row

    if request.endpoint in _MODE_CHANGING_ENDPOINTS or request.endpoint in _MODE_AGNOSTIC_ENDPOINTS:
        return None

    # Lecture sous le verrou moteur : `start_game` remplace `engine` puis pose son
    # `current_mode_code` en deux temps. Lire hors verrou peut tomber dans cette fenêtre,
    # y voir un mode absent, et donc ouvrir la porte à une requête d'un profil non autorisé
    # sur la partie en train de démarrer. Le verrou est réentrant : la vue le reprendra.
    with _ENGINE_STATE_LOCK:
        if engine is None:
            # AUCUN moteur : il n'y a rien sur quoi agir, donc aucun mode à contrôler.
            # C'est le seul cas où l'absence de mode est légitime.
            return None
        current_mode = _current_game_mode()
    # Un moteur EXISTE mais sans mode : c'est l'état produit par `initialize_engine()` au
    # démarrage (moteur PvP complet, `current_mode_code` posé seulement par `start_game`),
    # et la fenêtre de ré-initialisation. Confondre ce cas avec « pas de partie » ouvrait la
    # porte à tout profil sur ce moteur. `_forbidden_mode_response` refuse un mode absent.
    return _forbidden_mode_response(current_mode)


@app.route('/api/health', methods=['GET'])
@public_endpoint
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "engine_initialized": engine is not None
    })

# Pas de route de création de compte (F12, décision « fermeture pure ») : les comptes sont
# créés en SQL dans `config/users.db`. La laisser derrière l'authentification ne suffirait
# pas — n'importe quel testeur au profil `base` pourrait alors créer des comptes en masse.
# Un jeton d'invitation à usage unique reste l'évolution prévue si le nombre de testeurs
# grandit ; c'est à ce moment-là que la route réapparaîtra, avec sa validation propre.


@app.route('/api/auth/login', methods=['POST'])
@public_endpoint
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
            SELECT u.id AS user_id, u.login, u.password_hash, p.id AS profile_id, p.code AS profile_code
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
                "default_redirect_mode": "pve",
            }
        )
    finally:
        connection.close()


@app.route('/api/auth/me', methods=['GET'])
@mode_agnostic
def current_user():
    """Return current user session and permissions."""
    # Session déjà validée par `require_authenticated_session` : la revalider ouvrirait une
    # seconde connexion SQLite et rejouerait la même jointure pour le même token.
    user_row = g.auth_user

    with auth_db_read_cursor() as connection:
        permissions = _resolve_permissions_for_profile(connection, user_row["profile_id"])

    return jsonify(
        {
            "success": True,
            "user": {
                "id": user_row["user_id"],
                "login": user_row["login"],
                "profile": user_row["profile_code"],
            },
            "permissions": permissions,
            "default_redirect_mode": "pve",
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
@changes_game_mode
@with_engine_state_lock
def start_game():
    """Start a new game session with optional PvE mode."""
    global engine
    
    # Session déjà validée par `require_authenticated_session` (cf. /api/auth/me).
    auth_user = g.auth_user

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

    with auth_db_read_cursor() as connection:
        permissions = _resolve_permissions_for_profile(connection, auth_user["profile_id"])

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
            if board_path is None:
                from config_loader import get_config_loader as _gcl
                _cfg = _gcl().load_config("config", force_reload=False)
                # Pas de littéral de repli : "x5" ne désignait plus aucune entrée depuis le
                # retrait des options mortes, un défaut aurait donc levé un KeyError plus loin.
                board_path = require_key(require_key(_cfg, "defaults"), "test_board")
                if board_path not in BOARD_PATH_MAP:
                    raise ValueError(
                        f"config.json defaults.test_board = {board_path!r} : attendu l'un de "
                        f"{sorted(BOARD_PATH_MAP)}"
                    )
            scenario_file = os.path.join("config", TEST_SCENARIO_BOARD_MAP[board_path], "scenario", "scenario_pvp_test.json")
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
            initialize_engine(scenario_file=scenario_file)
        elif requested_mode == "pve":
            # Le `scenario_file` du client est TRANSMIS, comme en "pvp" : l'écraser rendait 200
            # sur une partie qui n'est pas celle demandée, donc un board client désynchronisé et
            # muet. Sans clé, `initialize_test_engine` résout le défaut du dossier de board ; un
            # chemin hérité pointant la copie racine supprimée échoue explicitement.
            initialize_test_engine(
                scenario_file=scenario_file,
                forced_agent_key=_configured_agent_key(),
            )
        elif requested_mode == "pve_test":
            if board_path is None:
                from config_loader import get_config_loader as _gcl
                _cfg = _gcl().load_config("config", force_reload=False)
                # Pas de littéral de repli : "x5" ne désignait plus aucune entrée depuis le
                # retrait des options mortes, un défaut aurait donc levé un KeyError plus loin.
                board_path = require_key(require_key(_cfg, "defaults"), "test_board")
                if board_path not in BOARD_PATH_MAP:
                    raise ValueError(
                        f"config.json defaults.test_board = {board_path!r} : attendu l'un de "
                        f"{sorted(BOARD_PATH_MAP)}"
                    )
            scenario_file = os.path.join("config", TEST_SCENARIO_BOARD_MAP[board_path], "scenario", "scenario_pve_test.json")
            _prev_board = os.environ.get("W40K_BOARD_PATH")
            os.environ["W40K_BOARD_PATH"] = BOARD_PATH_MAP[board_path]
            try:
                initialize_test_engine(
                    scenario_file=scenario_file,
                    forced_agent_key=_configured_agent_key(),
                )
            finally:
                if _prev_board is not None:
                    os.environ["W40K_BOARD_PATH"] = _prev_board
                elif "W40K_BOARD_PATH" in os.environ:
                    del os.environ["W40K_BOARD_PATH"]
        elif requested_mode == ED_MODE_CODE:
            if scenario_file is None:
                scenario_file = ED_SCENARIO_DEFAULT
            initialize_test_engine(
                scenario_file=scenario_file,
                forced_agent_key=_configured_agent_key(),
            )
        else:
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
        
    # Reset the engine for new game
    try:
        obs, info = engine.reset()
    except Exception as reset_error:
        print(f"CRITICAL ERROR in engine.reset(): {reset_error}")
        print(f"ERROR TYPE: {type(reset_error).__name__}")
        import traceback
        print(f"FULL TRACEBACK:\n{traceback.format_exc()}")
        raise

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
                pools = gs.get("deployment_pools", {})
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
                # `engine.start_command_phase()` et pas le handler nu : 08.04 peut poser une
                # decision de capacite de faction, et seul le moteur sait qui pilote le siege.
                # Le retour est RESPECTE — enchainer sur le mouvement perdrait la decision.
                if engine.start_command_phase().get("phase_complete"):  # get allowed
                    movement_handlers.movement_phase_start(gs)
                break
        gs["current_player"] = 2
        gs["turn"] = 1
        if engine.start_command_phase().get("phase_complete"):  # get allowed
            movement_handlers.movement_phase_start(gs)

    # Snapshots temporels : réinitialiser l'historique et capturer + auto-sauver l'état de départ (PvP).
    _SNAPSHOT_STORE.reset()
    _capture_and_autosave(engine, initial=True)

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

    # TEST (phase charge) : override manuel de la distance de charge (remplace le jet 2D6).
    # None/<=0 → pas d'override (jet normal). Posé avant traitement pour être pris en compte
    # dès l'activation de charge déclenchée par cette action.
    if "charge_roll_override" in data:
        _cro = data["charge_roll_override"]
        if _cro is None:
            engine.game_state["charge_roll_override"] = None
        else:
            _cro_i = int(_cro)
            engine.game_state["charge_roll_override"] = _cro_i if _cro_i > 0 else None

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
        # Orientation EN COURS du socle (pivot molette non committé, optionnel) → empreinte du pool
        # calculée à l'orientation réelle (EZ ennemie 2" / collisions honorées pendant le preview).
        _mv_orient_raw = action.get("orientation")
        _mv_orient = int(_mv_orient_raw) if _mv_orient_raw is not None else None
        _model_pool = _mh_model.movement_build_model_destinations_pool(
            engine.game_state, str(model_id), provisional_plan=_provisional_plan,
            level=_mv_level, orientation=_mv_orient,
        )
        return api_json_response({
            "success": True,
            "result": {
                "action": "move_model_destinations",
                "model_id": str(model_id),
                "destinations": [[int(c), int(r), int(lv)] for c, r, lv in _model_pool["destinations"]],
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
            _pools[_mid_str] = [[int(c), int(r)] for c, r, _lv in _pool["destinations"]]
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
                "destinations": [[int(c), int(r), int(lv)] for c, r, lv in _dep_pool["destinations"]],
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
        from engine.phase_handlers.shared_utils import parse_model_plan
        # Pool de suivi squad = translation rigide HORIZONTALE : le niveau n'entre pas dans le
        # calcul (la zone de déploiement est 2D), mais il est EXIGÉ comme partout ailleurs — un
        # plan muet est refusé à la frontière, jamais silencieusement filtré (le filtre `len(e) in
        # (3, 4)` faisait disparaître une entrée malformée au lieu de la signaler).
        _squad_plan = [
            (mid, col, row)
            for mid, col, row, _lv in parse_model_plan(
                _raw_squad_plan, action_name="deploy_squad_destinations"
            )
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
        # Le niveau (étages) est OBLIGATOIRE : sans lui le preview d'un move à l'étage mesurerait
        # un autre niveau que le commit. L'orientation reste en 5e position, `None` si non fournie
        # — c'est exactement ce que `movement_preview_move_plan` attend.
        from engine.phase_handlers.shared_utils import parse_model_plan_with_orientation
        parsed_plan = parse_model_plan_with_orientation(plan, action_name="preview_move_plan")
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

    # ── RÉSERVES STRATÉGIQUES (20.01 / 20.04) ────────────────────────────────────────────────
    # `deploy_strategic_reserves` (20.01) et `ingress_move` (20.04) MUTENT l'état : elles ne sont
    # PAS traitées ici mais routées par `engine.execute_semantic_action` comme toute autre action
    # de jeu (dispatchers `execute_deployment_action` et `movement_handlers.execute_action`).
    # C'est ce qui leur donne la fin d'activation, la journalisation, la capture de rewind et la
    # resérialisation de l'état — tout ce qu'un retour anticipé depuis ce point leur retirerait.
    # Seul l'APERÇU, en lecture pure, est servi ici (jumeau de `deploy_preview`).

    # Read-only : aire d'arrivée d'une unité en réserves, rendue EN CONTOUR DANS LA RÉPONSE — le
    # client la dessine comme l'aperçu de mouvement, en polygone, au lieu de recevoir des dizaines
    # de milliers de couples (col,row). Elle n'est PAS publiée dans le canal d'aperçu partagé du
    # game_state : voir le choix de `ingress_preview_loops` plus bas.
    if action.get("action") == "ingress_preview":
        unit_id = action.get("unitId")
        if unit_id is None:
            return jsonify({"success": False, "error": "ingress_preview requires unitId"}), 400
        from engine.phase_handlers import movement_handlers as _mh_ing
        if not _mh_ing.unit_is_in_strategic_reserves(engine.game_state, str(unit_id)):
            return jsonify({
                "success": False,
                "error": f"unit {unit_id} is not in strategic reserves",
            }), 400
        eligible = _mh_ing.ingress_eligible_units(engine.game_state)
        if str(unit_id) not in eligible:
            # 20.03 : pas encore son round d'arrivée. État de jeu normal, pas une erreur serveur.
            return api_json_response({
                "success": True,
                "result": {
                    "action": "ingress_preview", "unitId": str(unit_id),
                    "eligible": False, "cells": 0,
                    "reason": "not_yet_arriving",
                },
            })
        # `ingress_preview_loops` et NON `set_ingress_preview_loops` : le second publie la bande
        # dans ``move_preview_footprint_mask_loops``, le canal d'aperçu du MOUVEMENT. Or cette
        # action est en lecture pure — elle ne resérialise pas l'état, donc rien n'effacerait la
        # bande ensuite et elle repartirait dans toutes les réponses suivantes. Le calcul, lui,
        # est pur et mémoïsé. C'est le choix que `precompute_ingress_pools` documente déjà.
        _ingress_loops = _compact_mask_loops_for_api_json(
            _mh_ing.ingress_preview_loops(engine.game_state, str(unit_id))
        )
        _pool_n = len(_mh_ing.ingress_setup_pool(engine.game_state, str(unit_id)))
        return api_json_response({
            "success": True,
            "result": {
                "action": "ingress_preview", "unitId": str(unit_id),
                "eligible": True, "cells": _pool_n,
                # Les contours sont RENDUS DANS LA RÉPONSE, comme `deploy_model_destinations`
                # rend les siens : une action en lecture pure ne resérialise pas l'état, donc
                # les publier seulement dans le game_state obligerait le client à refaire un
                # aller-retour pour dessiner ce qu'il vient de demander.
                "footprint_mask_loops": _ingress_loops,
                # Pool vide = aucune arrivée légale (les ennemis couvrent la bande). Le client
                # doit le DIRE au joueur, sinon le clic suivant ne fera rien.
                "reason": None if _pool_n else "no_legal_arrival",
            },
        })

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
                "hidden_detection_info_by_unit_id": preview_payload["hidden_detection_info_by_unit_id"],
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

    # Snapshots temporels (rewind) + timeline par action : capturés après chaque action réussie (PvP).
    if success:
        # Empiler les events de log de CETTE action dans log_delta AVANT la capture de row. La row de
        # fin d'activation draine log_delta ; si on empile après, elle ne contient pas l'action courante
        # et ses events glissent dans la row suivante (visibles seulement au pas de flèche suivant),
        # typiquement une unité multi-armes dont les derniers tirs manquent au 1er clic.
        _buffer_log_delta(engine, engine.game_state.get("action_logs", []))
        _capture_and_autosave(engine)
        _timeline_capture(engine)

    # Réserves (20.04) : réchauffer l'aire d'arrivée AVANT que le joueur ne clique. Mesuré sur
    # board x5 : 2,3 s pour les deux signatures d'un roster (pool + contours), puis 9 ms par
    # sélection. Payer ça au clic se verrait ; le payer ici le noie dans le tour adverse.
    # CÔTÉ API SEULEMENT : en entraînement, la plupart des phases de mouvement n'ont aucune
    # réserve et le masque construit déjà, paresseusement, ce dont il a besoin.
    _maybe_precompute_ingress_pools(engine)

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
    # Extract and send detailed action logs to frontend (log_delta déjà empilé avant la capture de row)
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


def _execute_end_phase_action(engine_instance: _EndPhaseEngine, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    End current phase by applying WAIT/SKIP end_activation to all remaining units in pool.
    Supports move/shoot/charge phases. For fight, delegates to advance_phase.

    `engine_instance.game_state` et non `require_key(engine_instance.__dict__, "game_state")` :
    `game_state` est un simple attribut d'instance du moteur (w40k_core.py l.435), il n'existe
    aucune property ni `__getattr__` a contourner (verifie dans engine/ et services/). Passer
    par `__dict__` ne faisait donc que rendre le dict `Any` — et une boucle qui pilote la fin
    de phase sur un `Any` n'est verifiee nulle part. La reference reste capturee UNE fois : la
    boucle relit ce meme dict apres chaque `skip`, exactement comme avant.
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    game_state = engine_instance.game_state
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
    engine_instance: _UnitRegistryHolder,
) -> Tuple[list[Dict[str, Any]], int]:
    """Build full engine units for one player from army config."""
    if engine_instance.unit_registry is None:
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
                    "MODEL_HEIGHT": float(require_key(unit_data, "MODEL_HEIGHT")),
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
                    # Battle-shock state (regle 01.07) — meme contrat que create_unit /
                    # _build_enhanced_unit : le champ existe des la construction (le controle
                    # d objectif 14.02 le lit sans defaut).
                    "battle_shocked": False,
                }
            )
    return built_units, next_unit_id


def _build_units_from_scenario_army(
    engine_instance: _UnitRegistryHolder,
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

    Même exigence que sa soeur ``_build_units_from_army_config``, d'où le protocole
    commun : le ``GameStateManager`` utilisé ici est CONSTRUIT sur place, et les deux
    briques moteur recoivent le registre en argument explicite. Rien du moteur appelant
    n'est lu en dehors de ``unit_registry``.
    """
    if engine_instance.unit_registry is None:
        raise ValueError("engine.unit_registry is required to build units from scenario army")
    from engine.game_state import GameStateManager
    from config_loader import get_config_loader

    reg = engine_instance.unit_registry
    manager = GameStateManager(
        {"board": get_config_loader().get_board_config(), "controlled_player": int(player)},
        reg,
    )
    basic_units = manager._fold_attached_characters(
        copy.deepcopy(require_key(army_cfg, "units")), reg
    )
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
    # This preserves mono-agent (single-policy) behavior by mapping all model keys
    # to controlled_agent rewards.
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
@mode_agnostic
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
        # Retour au live (sortie de visionnage) : Game Log complet réel = deltas committés + delta en cours.
        "game_log_history": _reconstruct_game_log(
            _SAVE_STORE.current_party(), None, include_pending_from=engine
        ),
    })

@app.route('/api/game/reset', methods=['POST'])
@with_engine_state_lock
def reset_game():
    """Reset the current game."""
    global engine
    
    if not engine:
        return jsonify({"success": False, "error": "Engine not initialized"}), 400
    
    obs, info = engine.reset()
    _SNAPSHOT_STORE.reset()
    _capture_and_autosave(engine, initial=True)
    serializable_state = _game_state_for_json(engine)
    _sync_units_hp_from_cache(serializable_state, engine.game_state)
    _attach_player_types(serializable_state, engine)

    return api_json_response({
        "success": True,
        "game_state": serializable_state,
        "message": "Game reset successfully",
    })

def _snapshot_persist_path() -> str:
    """Fichier de persistance des snapshots (pickle) dans le répertoire de persistance configuré."""
    return os.path.join(_PERSIST_DIR, "pvp_snapshots.pkl")


def _persist_snapshots_to_disk() -> None:
    import pickle
    path = _snapshot_persist_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(_SNAPSHOT_STORE, f)


def _load_snapshots_from_disk() -> bool:
    import pickle
    path = _snapshot_persist_path()
    if not os.path.exists(path):
        return False
    with open(path, "rb") as f:
        loaded = pickle.load(f)
    if not isinstance(loaded, GameSnapshotStore):
        raise TypeError(f"Fichier snapshot invalide: {type(loaded).__name__}")
    _SNAPSHOT_STORE._snaps = loaded._snaps
    return True


@app.route('/api/game/snapshots', methods=['GET'])
@with_engine_state_lock
def list_snapshots():
    """Liste les snapshots capturés (métadonnées : turn, player, phase, score)."""
    return api_json_response({
        "success": True,
        "snapshots": _SNAPSHOT_STORE.list_meta(),
        "persist_enabled": _SNAPSHOT_PERSIST_ENABLED,
    })


@app.route('/api/game/snapshot/restore', methods=['POST'])
@changes_game_mode
@with_engine_state_lock
def restore_snapshot():
    """Restaure un snapshot. mode='resume' remplace l'état vivant et purge l'historique postérieur ;
    mode='view' renvoie l'état sérialisé sans toucher la partie en cours (lecture seule)."""
    global engine
    if not engine:
        return jsonify({"success": False, "error": "Engine not initialized"}), 400
    data = request.json
    if not data:
        return jsonify({"success": False, "error": "No JSON data provided"}), 400
    turn = int(require_key(data, "turn"))
    player = int(require_key(data, "player"))
    phase = str(require_key(data, "phase"))
    mode = str(require_key(data, "mode"))
    if mode not in ("resume", "view"):
        return jsonify({"success": False, "error": f"mode must be 'resume' or 'view' (got {mode!r})"}), 400
    if not _SNAPSHOT_STORE.has(turn, player, phase):
        return jsonify({"success": False, "error": f"snapshot introuvable: turn={turn} player={player} phase={phase}"}), 404

    # État reconstruit UNE fois, avant la bifurcation view/resume : `view` renvoie l'état
    # complet du snapshot, il doit passer le même contrôle de mode que `resume`. Avec la
    # persistance disque, les snapshots peuvent provenir d'une autre partie, donc d'un
    # autre mode que celui en cours.
    rebuilt = _SNAPSHOT_STORE.build_game_state(engine, turn, player, phase)
    forbidden = _forbidden_mode_response(rebuilt.get("current_mode_code"))
    if forbidden is not None:
        return forbidden

    if mode == "view":
        # Sérialise le snapshot sans muter la partie vivante : swap temporaire de game_state.
        live_gs = engine.game_state
        try:
            engine.game_state = rebuilt
            serializable_state = _game_state_for_json(engine)
            _sync_units_hp_from_cache(serializable_state, engine.game_state)
            _attach_player_types(serializable_state, engine)
        finally:
            engine.game_state = live_gs
        return api_json_response({
            "success": True, "mode": "view", "game_state": serializable_state,
            # Log du point rembobiné (rewind ⏮⏭) : deltas de la timeline jusqu'à cette phase.
            "game_log_history": _reconstruct_game_log(
                _SAVE_STORE.current_party(), progress_key_from_gs(rebuilt)
            ),
        })

    # Divergence : save-points du fichier courant postérieurs au point rembobiné → fork/écrasement.
    # Clé de progression calculée sur l'état déjà reconstruit plus haut, sans commit.
    gate = _resume_divergence_gate(
        _SAVE_STORE.current_party(), progress_key_from_gs(rebuilt), data
    )
    if gate is not None:
        return gate

    # resume : remplace l'état vivant + purge postérieur
    _SNAPSHOT_STORE.apply_resume(engine, turn, player, phase)
    _reset_timeline_last(engine)
    if _SNAPSHOT_PERSIST_ENABLED:
        _persist_snapshots_to_disk()
    serializable_state = _game_state_for_json(engine)
    _sync_units_hp_from_cache(serializable_state, engine.game_state)
    _attach_player_types(serializable_state, engine)
    return api_json_response({
        "success": True, "mode": "resume", "game_state": serializable_state,
        # Log du point rembobiné (commit) : deltas de la timeline jusqu'à l'état restauré.
        "game_log_history": _reconstruct_game_log(
            _SAVE_STORE.current_party(), progress_key_from_gs(engine.game_state)
        ),
    })


@app.route('/api/game/snapshot/persist', methods=['POST'])
@with_engine_state_lock
def set_snapshot_persist():
    """Active/désactive la persistance disque des snapshots, et — optionnellement — définit le
    répertoire de persistance (snapshots + saves)."""
    global _SNAPSHOT_PERSIST_ENABLED, _PERSIST_DIR, _PERSIST_DIR_SET
    data = request.json
    if not data or "enabled" not in data:
        return jsonify({"success": False, "error": "missing 'enabled'"}), 400
    directory = data.get("directory")
    if directory:
        directory = str(directory)
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as e:
            return jsonify({"success": False, "error": f"répertoire invalide: {e}"}), 400
        _PERSIST_DIR = directory
        _SAVE_STORE.set_directory(os.path.join(directory, "pvp_saves"))
        _PERSIST_DIR_SET = True
    _SNAPSHOT_PERSIST_ENABLED = bool(data["enabled"])
    if _SNAPSHOT_PERSIST_ENABLED:
        _persist_snapshots_to_disk()
    _persist_save_config()
    return api_json_response({
        "success": True,
        "persist_enabled": _SNAPSHOT_PERSIST_ENABLED,
        "directory": _PERSIST_DIR,
    })


@app.route('/api/game/pick-directory', methods=['POST'])
def pick_directory():
    """Ouvre un dialogue de dossier Windows (via powershell/WSL interop) et renvoie le chemin WSL choisi.

    Pas de lock engine : le dialogue est bloquant côté utilisateur, on ne veut pas geler la partie."""
    import shutil
    import subprocess
    if not shutil.which("powershell.exe"):
        return jsonify({"success": False, "error": "Sélecteur natif indisponible (powershell.exe introuvable — pas sous WSL ?)"}), 400
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$f.Description = 'Repertoire de sauvegarde (snapshots + saves)'; "
        "$f.ShowNewFolderButton = $true; "
        "$o = New-Object System.Windows.Forms.Form; $o.TopMost = $true; "
        "if ($f.ShowDialog($o) -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.SelectedPath }"
    )
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", ps],
            capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Sélection annulée (délai dépassé)"}), 408
    win_path = out.stdout.strip()
    if not win_path:
        return api_json_response({"success": True, "path": None})  # annulé par l'utilisateur
    conv = subprocess.run(["wslpath", "-u", win_path], capture_output=True, text=True)
    wsl_path = conv.stdout.strip()
    if conv.returncode != 0 or not wsl_path:
        return jsonify({"success": False, "error": f"conversion du chemin échouée: {win_path!r}"}), 400
    return api_json_response({"success": True, "path": wsl_path, "windows_path": win_path})


@app.route('/api/game/save', methods=['POST'])
@with_engine_state_lock
def create_save():
    """Ajoute un save-point manuel à la partie courante. Retourne la meta créée."""
    global engine
    if not engine:
        return jsonify({"success": False, "error": "Engine not initialized"}), 400
    if not _PERSIST_DIR_SET:
        return jsonify({"success": False, "error": "Répertoire de sauvegarde non défini"}), 400
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    note = str((request.json or {}).get("note", "")) if request.is_json else ""
    meta = _SAVE_STORE.add_point(engine, timestamp, note, "manual")
    return api_json_response({"success": True, "save": meta})


@app.route('/api/game/saves', methods=['GET'])
@with_engine_state_lock
def list_saves():
    """Save-points de la PARTIE COURANTE (pour Select) : rows « grosses » (hors action)."""
    return api_json_response({"success": True, "saves": _SAVE_STORE.list_points()})


@app.route('/api/game/timeline', methods=['GET'])
@with_engine_state_lock
def list_timeline():
    """TOUTES les rows de la partie courante (playback ⏮▶⏭) + état de l'enregistrement.
    ``recording_enabled`` = l'enregistrement de la timeline est actif (sinon pas de rewind → popup)."""
    _SAVE_STORE.flush()  # rows en attente écrites avant de lister (liste à jour)
    return api_json_response({
        "success": True,
        "rows": _SAVE_STORE.list_all_rows(),
        "recording_enabled": bool(_SNAPSHOT_PERSIST_ENABLED and _PERSIST_DIR_SET),
    })


def _resume_divergence_gate(party_name, resume_key, data):
    """Gère la divergence au Resume : si la partie contient des save-points postérieurs au point de
    reprise, exige une décision du joueur (fork/écrasement).
    - Retourne None → pas de divergence (ou décision appliquée) : poursuivre le commit du resume.
    - Retourne une réponse Flask → interrompre (popup à afficher, ou erreur de paramètre)."""
    # Draine les rows de timeline en attente AVANT toute lecture/troncature, pour ne pas ré-appender
    # après coup une row périmée (postérieure au point de reprise).
    _SAVE_STORE.flush()
    if not party_name or not _SAVE_STORE.has_posterior_points(party_name, resume_key):
        return None
    fork = data.get("fork")
    if fork is None:
        # Pas encore de décision : le front doit afficher le popup, aucun commit/mutation ici.
        return api_json_response({"success": True, "needs_decision": True, "has_posterior": True})
    if fork == "overwrite":
        _SAVE_STORE.truncate_after(party_name, resume_key)
        return None
    if fork == "fork":
        # Nom optionnel : le store le rend unique / génère un défaut → jamais d'erreur de doublon.
        _SAVE_STORE.fork_backup(party_name, resume_key, str(data.get("backup_name") or ""))
        return None
    return jsonify({"success": False, "error": f"fork must be 'fork' or 'overwrite' (got {fork!r})"}), 400


@app.route('/api/game/save/load', methods=['POST'])
@changes_game_mode
@with_engine_state_lock
def load_save():
    """Restaure un save-point de la partie courante (Select) : remplace l'état vivant, repart de ce point."""
    global engine
    if not engine:
        return jsonify({"success": False, "error": "Engine not initialized"}), 400
    data = request.json
    if not data:
        return jsonify({"success": False, "error": "No JSON data provided"}), 400
    point_id = str(require_key(data, "id"))
    mode = str(data.get("mode", "resume"))
    # Row lue UNE fois, avant la bifurcation view/resume : `view` renvoie l'état complet du
    # save-point, il doit donc passer le même contrôle de mode que `resume`.
    save_row = _SAVE_STORE.point(point_id)
    forbidden = _forbidden_mode_response(_captured_mode(save_row["state"]))
    if forbidden is not None:
        return forbidden
    resume_key = progress_key_from_meta(save_row["meta"])
    if mode == "view":
        serializable_state = _serialize_captured_view(engine, save_row["state"])
        return api_json_response({
            "success": True, "game_state": serializable_state, "save": save_row["meta"],
            "mode": "view",
            # Log jusqu'à ce save-point (Select) : deltas de la timeline courante jusqu'à ce point.
            "game_log_history": _reconstruct_game_log(
                _SAVE_STORE.current_party(), resume_key
            ),
        })
    # Divergence : save-points postérieurs à ce point dans la partie courante → fork/écrasement.
    gate = _resume_divergence_gate(_SAVE_STORE.current_party(), resume_key, data)
    if gate is not None:
        return gate
    meta = _SAVE_STORE.restore_point(engine, point_id, row=save_row)
    _reset_timeline_last(engine)
    # Commit : nouvelle timeline de rewind à partir du point chargé (capture la phase courante).
    _SNAPSHOT_STORE.reset()
    _SNAPSHOT_STORE.maybe_capture(engine)
    if _SNAPSHOT_PERSIST_ENABLED:
        _persist_snapshots_to_disk()
    serializable_state = _game_state_for_json(engine)
    _sync_units_hp_from_cache(serializable_state, engine.game_state)
    _attach_player_types(serializable_state, engine)
    return api_json_response({
        "success": True, "game_state": serializable_state, "save": meta, "mode": "resume",
        # Log jusqu'au point chargé (commit) : deltas de la timeline courante jusqu'à ce point.
        "game_log_history": _reconstruct_game_log(_SAVE_STORE.current_party(), resume_key),
    })


@app.route('/api/game/parties', methods=['GET'])
@with_engine_state_lock
def list_parties():
    """Liste des parties sauvegardées (pour Load)."""
    return api_json_response({"success": True, "parties": _SAVE_STORE.list_parties()})


@app.route('/api/game/party/load', methods=['POST'])
@changes_game_mode
@with_engine_state_lock
def load_party():
    """Charge une partie sauvegardée à son game start ; elle devient la partie courante."""
    global engine
    if not engine:
        return jsonify({"success": False, "error": "Engine not initialized"}), 400
    data = request.json
    if not data:
        return jsonify({"success": False, "error": "No JSON data provided"}), 400
    name = str(require_key(data, "name"))
    mode = str(data.get("mode", "resume"))
    # Ligne lue UNE fois, avant la bifurcation view/resume : `view` renvoie l'état complet
    # et fixe la partie courante, il doit donc être soumis au même contrôle de mode que
    # `resume` — et cette lecture sert ensuite les deux branches.
    start_point = _SAVE_STORE.party_start_point(name)
    forbidden = _forbidden_mode_response(_captured_mode(start_point["state"]))
    if forbidden is not None:
        return forbidden
    if mode == "view":
        # Aperçu : la partie devient le contexte de navigation (Select liste SES points), sans commit.
        _SAVE_STORE.set_current(name)
        serializable_state = _serialize_captured_view(engine, start_point["state"])
        return api_json_response({
            "success": True, "game_state": serializable_state, "save": start_point["meta"],
            "mode": "view",
            # Log au game_start de la partie chargée (delta de la row game_start, souvent vide).
            "game_log_history": _reconstruct_game_log(
                name, progress_key_from_meta(start_point["meta"])
            ),
        })
    # Divergence : save-points postérieurs au game_start dans cette partie → fork/écrasement.
    gate = _resume_divergence_gate(
        name, progress_key_from_meta(start_point["meta"]), data
    )
    if gate is not None:
        return gate
    meta = _SAVE_STORE.load_party_start(engine, name)
    _reset_timeline_last(engine)
    # Commit : nouvelle timeline de rewind à partir du game start chargé (capture la phase courante).
    _SNAPSHOT_STORE.reset()
    _SNAPSHOT_STORE.maybe_capture(engine)
    if _SNAPSHOT_PERSIST_ENABLED:
        _persist_snapshots_to_disk()
    serializable_state = _game_state_for_json(engine)
    _sync_units_hp_from_cache(serializable_state, engine.game_state)
    _attach_player_types(serializable_state, engine)
    return api_json_response({
        "success": True, "game_state": serializable_state, "save": meta, "mode": "resume",
        # Log au game_start (commit de la partie chargée) : delta de la row game_start, souvent vide.
        "game_log_history": _reconstruct_game_log(
            name, _SAVE_STORE.party_start_progress_key(name)
        ),
    })


@app.route('/api/game/save-config', methods=['GET'])
def get_save_config():
    """Config des saves côté serveur (source de vérité unique, lue par le front au montage)."""
    return api_json_response({
        "success": True,
        "persist_enabled": _SNAPSHOT_PERSIST_ENABLED,
        "directory": _PERSIST_DIR,
        "dir_set": _PERSIST_DIR_SET,
        "autosave_enabled": _AUTOSAVE_ENABLED,
        "granularity": _AUTOSAVE_GRANULARITY,
    })


@app.route('/api/game/autosave', methods=['POST'])
@with_engine_state_lock
def set_autosave():
    """Active/désactive la sauvegarde auto et sa granularité ('phase' ou 'turn')."""
    global _AUTOSAVE_ENABLED, _AUTOSAVE_GRANULARITY, _AUTOSAVE_LAST_KEY
    data = request.json or {}
    was_enabled = _AUTOSAVE_ENABLED
    _AUTOSAVE_ENABLED = bool(data.get("enabled", False))
    gran = str(data.get("granularity", "phase"))
    if gran not in ("phase", "turn"):
        return jsonify({"success": False, "error": f"granularity must be 'phase' or 'turn' (got {gran!r})"}), 400
    _AUTOSAVE_GRANULARITY = gran
    _AUTOSAVE_LAST_KEY = None
    _persist_save_config()
    # Transition off→on avec une partie PvP en cours : sauver immédiatement l'état courant.
    # Couvre le cas où la config arrive APRÈS start_game (pas de doublon : si elle était déjà on
    # au start_game, ce n'est pas une transition ici).
    if (
        _AUTOSAVE_ENABLED
        and not was_enabled
        and _PERSIST_DIR_SET
        and engine is not None
        and getattr(engine, "current_mode_code", None) in ("pvp", "pvp_test")
        and isinstance(getattr(engine, "game_state", None), dict)
        and "turn" in engine.game_state
    ):
        from datetime import datetime
        now = datetime.now()
        if _SAVE_STORE.current_party() is None:
            _SAVE_STORE.start_party(
                engine, now.strftime("%Y%m%d_%H-%M"), now.strftime("%Y%m%d-%H%M%S")
            )
            _SAVE_STORE.promote()  # autosave activé → partie rendue visible immédiatement
        else:
            _SAVE_STORE.promote()  # rend le working visible même si le dédup autosave saute le point
            _maybe_autosave(engine, now.strftime("%Y%m%d-%H%M%S"))
    return api_json_response({
        "success": True,
        "enabled": _AUTOSAVE_ENABLED,
        "granularity": _AUTOSAVE_GRANULARITY,
    })


@app.route('/api/game/saves/delete', methods=['POST'])
@with_engine_state_lock
def delete_saves():
    """Supprime toutes les saves manuelles/auto (fichiers de logs/pvp_saves/)."""
    deleted = _SAVE_STORE.delete_all()
    return api_json_response({"success": True, "deleted": deleted})


@app.route('/api/config/defaults', methods=['GET'])
@mode_agnostic
def get_config_defaults():
    """Expose config.json defaults section to the frontend."""
    from config_loader import get_config_loader
    config_loader = get_config_loader()
    config = config_loader.load_config("config", force_reload=False)
    return jsonify({"success": True, "defaults": require_key(config, "defaults")})


@app.route('/api/config/board', methods=['GET'])
@mode_agnostic
def get_board_config():
    """Get board configuration for frontend.
    Loads board_config.json from config/board/{paths.board}/, then walls and objectives
    from the same directory (walls/walls-XX.json, objectives/objectives-XX.json).

    Deux façons, exclusives, de désigner un autre plateau que celui de `paths.board` :
      - `board_path` (`x1` | `x5_44x60`) : surnom d'écran, utilisé par les modes de test ;
      - `inches_to_subhex` (1 | 5 | 10) : la RÉSOLUTION elle-même. C'est ce que porte le journal
        de partie, donc ce que le replay possède sans avoir à traduire quoi que ce soit — et le
        seul des deux qui couvre le plateau x10.
    """
    try:
        from config_loader import BOARD_DIR_BY_INCHES_TO_SUBHEX, get_config_loader
        config_loader = get_config_loader()
        # Dossier du plateau JOUÉ quand la requête l'impose ; None = celui de `config.json`.
        requested_board_subdir: Optional[str] = None
        board_path_param = request.args.get("board_path")
        if board_path_param is not None:
            if board_path_param not in BOARD_PATH_MAP:
                raise ValueError(
                    f"board_path must be one of {sorted(BOARD_PATH_MAP)} (got {board_path_param!r})"
                )
            requested_board_subdir = BOARD_PATH_MAP[board_path_param]
        inches_to_subhex_param = request.args.get("inches_to_subhex")
        if inches_to_subhex_param is not None:
            if board_path_param is not None:
                raise ValueError("board_path and inches_to_subhex are mutually exclusive")
            try:
                requested_ish = int(inches_to_subhex_param)
            except ValueError:
                raise ValueError(
                    f"inches_to_subhex must be an integer (got {inches_to_subhex_param!r})"
                )
            if requested_ish not in BOARD_DIR_BY_INCHES_TO_SUBHEX:
                raise ValueError(
                    f"inches_to_subhex must be one of "
                    f"{sorted(BOARD_DIR_BY_INCHES_TO_SUBHEX)} (got {requested_ish})"
                )
            requested_board_subdir = BOARD_DIR_BY_INCHES_TO_SUBHEX[requested_ish]
        if requested_board_subdir is not None:
            with _BOARD_ENV_LOCK:
                prev = os.environ.get("W40K_BOARD_PATH")
                os.environ["W40K_BOARD_PATH"] = requested_board_subdir
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
        if requested_board_subdir is not None:
            board_subdir = requested_board_subdir
        else:
            board_subdir = require_key(require_key(config_json, "paths"), "board")
        if not board_subdir:
            raise ValueError("config.json: 'paths.board' must be a non-empty value")

        project_root = Path(__file__).resolve().parent.parent
        board_dir = project_root / "config" / board_subdir
        wall_ref = board_spec.get("wall_ref")
        terrain_ref = board_spec.get("terrain_ref")
        # NOTE: le scénario est lu AVANT la résolution du dossier de données — c'est lui qui
        # déclare, via `board_ref`, le plateau où vivent murs et terrain (cf. bloc suivant).
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

        # Le plateau JOUÉ peut être plus grossier que celui qui PORTE les murs et le terrain
        # (option x1 = plateau 44×60 à 1 hex = 1 pouce, données écrites en x5). Les fichiers sont
        # alors lus dans leur dossier d'origine et convertis, comme le fait le moteur — sans quoi
        # le rendu chercherait un dossier `walls/` inexistant sous le plateau réduit.
        #
        # Ce dossier est DÉCLARÉ PAR LE SCÉNARIO — `board_ref`, sinon le `config/board/<plateau>/`
        # qui le contient — - selon la règle de `GameStateManager._resolve_board_dir`. Il était
        # déduit du seul `board_path` via une table codée en dur qui imposait `44x60x5` comme
        # source à TOUT scénario : le premier scénario écrit en `44x60x1` aurait vu son terrain lu
        # ailleurs, puis réduit ×5 en silence.
        board_data_dir = board_dir
        board_data_ratio = 1
        if scenario_file and isinstance(scenario_data, dict) and "board_ref" in scenario_data:
            board_ref_raw = scenario_data["board_ref"]
            if not isinstance(board_ref_raw, str) or not board_ref_raw.strip():
                raise ValueError(
                    f"scenario '{scenario_file}' has invalid 'board_ref': {board_ref_raw!r}"
                )
            board_ref_name = board_ref_raw.strip().replace("\\", "/")
            if board_ref_name.startswith("/") or "/" in board_ref_name or ".." in board_ref_name:
                raise ValueError(
                    f"scenario '{scenario_file}' has unsafe 'board_ref' (board name only): "
                    f"{board_ref_raw!r}"
                )
            board_data_dir = project_root / "config" / "board" / board_ref_name
            if not board_data_dir.is_dir():
                raise FileNotFoundError(
                    f"scenario '{scenario_file}' board_ref '{board_ref_name}' -> board directory "
                    f"not found: {board_data_dir}"
                )
        elif scenario_file:
            scenario_parent = (project_root / scenario_file).resolve().parent
            if scenario_parent.name == "scenario":
                board_data_dir = scenario_parent.parent

        if board_data_dir != board_dir:
            data_board_path = board_data_dir / "board_config.json"
            if not data_board_path.exists():
                raise FileNotFoundError(f"Board config not found: {data_board_path}")
            with open(data_board_path, "r", encoding="utf-8-sig") as f:
                data_board_spec = json.load(f)["default"]
            played_ish = int(require_key(board_spec, "inches_to_subhex"))
            data_ish = int(require_key(data_board_spec, "inches_to_subhex"))
            if played_ish <= 0 or data_ish % played_ish != 0:
                raise ValueError(
                    f"données du plateau en subhex x{data_ish} ({board_data_dir.name}), plateau "
                    f"joué en x{played_ish} — rapport non entier"
                )
            board_data_ratio = data_ish // played_ish
            # Même contrôle que le moteur (`_board_ref_downscale_ratio`) : sans lui, un `board_ref`
            # pointant un AUTRE plateau physique déplacerait murs et terrain en silence.
            played_dims = (
                int(require_key(board_spec, "cols")), int(require_key(board_spec, "rows"))
            )
            data_dims = (
                int(require_key(data_board_spec, "cols")) // board_data_ratio,
                int(require_key(data_board_spec, "rows")) // board_data_ratio,
            )
            if data_dims != played_dims:
                raise ValueError(
                    f"'{board_data_dir.name}' réduit de x{board_data_ratio} donne "
                    f"{data_dims[0]}x{data_dims[1]}, pas {played_dims[0]}x{played_dims[1]} — "
                    f"ce n'est pas le même plateau physique"
                )

        wall_hexes: list = []
        wall_segments_raw: list[dict] = []
        if scenario_file and isinstance(scenario_data, dict) and "wall_hexes" in scenario_data:
            scenario_wall_hexes = scenario_data.get("wall_hexes")
            if not isinstance(scenario_wall_hexes, list):
                raise ValueError("scenario wall_hexes must be a list")
            wall_hexes = scenario_wall_hexes
            if board_data_ratio != 1:
                from engine.game_state import GameStateManager as _GSM
                wall_hexes = _GSM._downscale_terrain_data(
                    {"walls": [{"hexes": wall_hexes}]}, board_data_ratio)["walls"][0]["hexes"]
        elif wall_ref and wall_ref.endswith(".json"):
            wall_path = board_data_dir / "walls" / wall_ref
            if not wall_path.exists():
                raise FileNotFoundError(f"Referenced wall file not found: {wall_path}")
            with open(wall_path, "r", encoding="utf-8-sig") as f:
                wall_data = json.load(f)
            if board_data_ratio != 1 and "walls" in wall_data:
                from engine.game_state import GameStateManager as _GSM
                wall_data = {**wall_data, "walls": _GSM._downscale_terrain_data(
                    {"walls": wall_data["walls"]}, board_data_ratio)["walls"]}
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
                if board_data_ratio != 1:
                    from engine.game_state import GameStateManager as _GSM
                    wall_hexes = _GSM._downscale_terrain_data(
                        {"walls": [{"hexes": wall_hexes}]}, board_data_ratio)["walls"][0]["hexes"]
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
            terrain_path = board_data_dir / "terrain" / terrain_ref
            if not terrain_path.exists():
                raise FileNotFoundError(f"Referenced terrain file not found: {terrain_path}")
            with open(terrain_path, "r", encoding="utf-8-sig") as f:
                terrain_data = json.load(f)
            if board_data_ratio != 1:
                from engine.game_state import GameStateManager as _GSM
                terrain_data = _GSM._downscale_terrain_data(terrain_data, board_data_ratio)
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
            _buffer_log_delta(engine, action_logs)  # delta du combat log pour la reconstruction du replay
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
            _buffer_log_delta(engine, action_logs)  # delta du combat log pour la reconstruction du replay
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
    _buffer_log_delta(engine, action_logs)  # delta du combat log pour la reconstruction du replay

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
@mode_agnostic
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

    # Type vérifié avant tout usage : `{"log_path": null}` produirait sinon une
    # AttributeError, donc un 500 avec traceback là où le reste du filtre renvoie 400.
    if not isinstance(log_path, str) or not log_path:
        return jsonify({"error": "log_path must be a non-empty string"}), 400

    # Sécurité : filtre aligné sur /api/replay/file/<filename> — un simple nom de fichier
    # `.log` à la racine du projet, aucun séparateur ni `..` toléré (F14).
    if not log_path.endswith('.log'):
        return jsonify({"error": "Only .log files are allowed"}), 400

    if '..' in log_path or '/' in log_path or '\\' in log_path:
        return jsonify({"error": "Invalid log path"}), 400

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    resolved_log_path = os.path.join(project_root, log_path)

    if not os.path.exists(resolved_log_path):
        return jsonify({"error": f"Log file not found: {log_path}"}), 404

    replay_data = parse_log_file(resolved_log_path)
    return jsonify(replay_data)


@app.route('/api/replay/default', methods=['GET'])
@mode_agnostic
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
@mode_agnostic
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
@mode_agnostic
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
@public_endpoint
def serve_frontend():
    """Racine publique — volontairement muette.

    Elle publiait le catalogue des routes et la topologie de déploiement, ce qui annulait
    l'intérêt de renvoyer 401 plutôt que 404 sur les URL inconnues : la liste était offerte
    à tout visiteur non authentifié. Le catalogue vit dans le README, pas sur un port
    exposé.
    """
    return jsonify({"message": "W40K Engine API Server"})

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
    
    # debug=False : coupe le reloader Werkzeug (restarts en boucle sous WSL2 qui
    # réinitialisaient le moteur en pleine partie) ; les erreurs sortent déjà en JSON.
    app.run(host='127.0.0.1', port=5001, debug=False)