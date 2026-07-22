"""analyzer_perfig.py — couche per-figurine de l'analyzer (V11).

Le step logger émet, en fin de chaque ligne d'action et avant [SUCCESS]/[FAILED],
un segment `[MODELS: <mid>@(<col>,<row>) ...]` listant les socles VIVANTS de
l'unité qui agit (les socles morts disparaissent). `<mid>` = `<unit_id>#<index>`.

Ce module :
  - parse ce segment (parse_models_segment) ;
  - reconstruit des empreintes de socle (footprints) via les helpers moteur
    (engine.hex_utils.compute_occupied_hexes / min_distance_between_sets), garantissant
    la parité géométrique avec le jeu ;
  - fournit les primitives per-socle utilisées par les handlers pour remplacer les
    contrôles ancre-à-ancre (portée, adjacence de combat, distance de move).

Aucun fallback masquant une erreur : si une donnée requise manque, on lève.
"""

import re
from typing import Dict, List, Optional, Set, Tuple

from engine.hex_utils import compute_occupied_hexes, min_distance_between_sets

# `<mid>@(<col>,<row>)` — mid = token sans espace contenant '#'
_MODELS_RE = re.compile(r'\[MODELS:\s*([^\]]+)\]')
_TOKEN_RE = re.compile(r'(\S+?#\S*?)@\((-?\d+),\s*(-?\d+)\)')

# Base par défaut si un socle n'a pas de base connue : round diamètre 1 (1 hex).
# Utilisé uniquement quand aucune ligne "Starting position ... base=" n'a été vue
# (logs de test synthétiques) — jamais pour masquer une erreur métier.
_DEFAULT_BASE: Tuple[str, object] = ("round", 1)

_fp_cache: Dict[Tuple[int, int, str, object], frozenset] = {}


def parse_base_token(token: str) -> Tuple[str, object]:
    """Parse un token `base=round/6` ou `base=oval/[20, 14]` → (shape, size)."""
    if not token.startswith("base="):
        raise ValueError(f"Base token invalide: {token!r}")
    body = token[len("base="):]
    shape, _, size_str = body.partition("/")
    if not shape or not size_str:
        raise ValueError(f"Base token invalide: {token!r}")
    if size_str.startswith("["):
        nums = [int(n) for n in re.findall(r'-?\d+', size_str)]
        if len(nums) != 2:
            raise ValueError(f"Base oval attend [major, minor]: {token!r}")
        return (shape, nums)
    return (shape, int(size_str))


def parse_models_segment(text: str) -> Optional[Dict[str, Dict[str, Tuple[int, int]]]]:
    """Extrait le segment [MODELS:] → {unit_id: {mid: (col,row)}}.

    unit_id = préfixe de mid avant '#'. Retourne None si aucun segment (ligne
    sans suffixe per-figurine, p.ex. logs anciens/synthétiques).
    """
    m = _MODELS_RE.search(text)
    if not m:
        return None
    result: Dict[str, Dict[str, Tuple[int, int]]] = {}
    for tok in _TOKEN_RE.finditer(m.group(1)):
        mid = tok.group(1)
        col = int(tok.group(2))
        row = int(tok.group(3))
        unit_id = mid.split('#', 1)[0]
        result.setdefault(unit_id, {})[mid] = (col, row)
    if not result:
        raise ValueError(f"Segment [MODELS:] présent mais vide/illisible: {m.group(1)[:120]}")
    return result


def _model_footprint(col: int, row: int, base: Tuple[str, object]) -> frozenset:
    shape, size = base
    key = (col, row, shape, size if isinstance(size, int) else tuple(size))
    cached = _fp_cache.get(key)
    if cached is not None:
        return cached
    fp = frozenset(compute_occupied_hexes(col, row, shape, size, 0))
    _fp_cache[key] = fp
    return fp


def _unit_base(unit_base: Dict[str, Tuple[str, object]], unit_id: str) -> Tuple[str, object]:
    return unit_base.get(unit_id, _DEFAULT_BASE)


def squad_footprint(
    models: Dict[str, Tuple[int, int]],
    base: Tuple[str, object],
) -> Set[Tuple[int, int]]:
    """Union des empreintes de tous les socles vivants d'une escouade."""
    fp: Set[Tuple[int, int]] = set()
    for (col, row) in models.values():
        fp |= _model_footprint(col, row, base)
    return fp


def squads_min_edge_distance(
    models_a: Dict[str, Tuple[int, int]],
    base_a: Tuple[str, object],
    models_b: Dict[str, Tuple[int, int]],
    base_b: Tuple[str, object],
    max_distance: int = 0,
) -> int:
    """Distance bord-à-bord minimale (subhexes) entre le socle le plus proche de A et
    celui de B — parité moteur (min_distance_between_sets sur empreintes)."""
    fp_a = squad_footprint(models_a, base_a)
    fp_b = squad_footprint(models_b, base_b)
    if not fp_a or not fp_b:
        raise ValueError("squads_min_edge_distance: empreinte vide (escouade sans socle vivant)")
    return min_distance_between_sets(fp_a, fp_b, max_distance=max_distance)


def resolve_weapon_value(
    weapon_name: str,
    per_unit_map: Dict[str, int],
    global_map: Dict[str, int],
) -> Optional[int]:
    """Résout le NB (ou une autre valeur entière) d'une arme loguée au niveau escouade.

    Ordre : (1) carte per-unit-type ; (2) si le nom est un profil composite « A / B »
    (armes de profil identique fusionnées par le moteur, cf. shared_utils
    _build_multi_hex... " / ".join), on résout CHAQUE composante et on retient le MAX
    (plafond générique — voir Class B) ; (3) carte globale tous model-types.
    Retourne None si irrésolu (vraie donnée manquante — on laisse l'erreur remonter).
    """
    name = weapon_name.strip()
    if name in per_unit_map:
        return per_unit_map[name]
    if " / " in name:
        vals = []
        for part in name.split(" / "):
            part = part.strip()
            v = per_unit_map.get(part)
            if v is None:
                v = global_map.get(part)
            if v is not None:
                vals.append(v)
        if vals:
            return max(vals)
        return None
    if name in global_map:
        return global_map[name]
    return None


def models_for_unit(
    positions_by_model: Dict[str, Dict[str, Tuple[int, int]]],
    unit_id: str,
) -> Optional[Dict[str, Tuple[int, int]]]:
    """Socles vivants connus pour unit_id, ou None si jamais vu en per-figurine."""
    m = positions_by_model.get(unit_id)
    if not m:
        return None
    return m
