#!/usr/bin/env python3
"""V11 T4 — Migration one-shot de la banque de scénarios CoreAgent + génération des terrains
d'entraînement plats.

Idempotent : un 2e passage ne produit aucun diff (mêmes terrains régénérés, mêmes scénarios).

Ce que fait le script :
  1. Génère des terrains d'ENTRAÎNEMENT PLATS (Phase A : pas d'étages) sous
     config/board/44x60x5/terrain/ à partir de terrain-mc1.json (géométrie éprouvée) :
     - retire les `floors` de chaque area (aplatissement) ;
     - conserve les 5 objectifs (`"objective": true`) et les 2 zones de déploiement (id "1"/"2") ;
     - produit 3 variantes (walls/obscuring différents) pour la variété LoS/couvert.
     Validation : chaque terrain a >= 1 objectif et exactement les zones joueurs 1 et 2.
  2. Migre les scénarios de la banque ACTIVE (training/, holdout_regular/, holdout_hard/,
     matchups/) vers le contrat moteur actuel :
     - supprime les clés legacy (objectives, objectives_ref, objective_hexes,
       deployment_zone, wall_ref) ;
     - ajoute `board_ref: "44x60x5"` et `terrain_ref` (cyclé sur les 3 terrains, déterministe) ;
     - conserve deployment_type(_P1/_P2), scale, refs de roster, seeds, primary_objectives.
  3. Statue `training_save/` : ARCHIVÉ sous scenarios/_archive_pre_v11/ (backup pré-V11, exclu
     du tirage). Idempotent (skip si déjà déplacé).

Aucune règle de jeu modifiée. Aucun fichier protégé touché (users.db, models/*.zip).
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOARD_REF = "44x60x5"
BOARD_DIR = PROJECT_ROOT / "config" / "board" / BOARD_REF
TERRAIN_DIR = BOARD_DIR / "terrain"
BASE_TERRAIN = TERRAIN_DIR / "terrain-mc1.json"
SCEN_ROOT = PROJECT_ROOT / "config" / "agents" / "CoreAgent" / "scenarios"
ARCHIVE_DIR = SCEN_ROOT / "_archive_pre_v11"

TRAIN_TERRAINS = ["terrain-train-01.json", "terrain-train-02.json", "terrain-train-03.json"]

LEGACY_KEYS = ("objectives", "objectives_ref", "objective_hexes", "deployment_zone", "wall_ref")

# Dossiers de la banque ACTIVE à migrer (relatifs à SCEN_ROOT). training_save exclu (archivé).
ACTIVE_DIRS = ["training", "holdout_regular", "holdout_hard"]


def _json_dump(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _flatten_area(area: dict) -> dict:
    a = dict(area)
    a.pop("floors", None)  # Phase A : terrains plats (pas d'élévation)
    return a


def build_training_terrains() -> None:
    base = json.loads(BASE_TERRAIN.read_text(encoding="utf-8-sig"))
    areas = base["terrain"]
    walls = base["walls"]
    dep_zones = base["deployment_zones"]
    icons = base.get("icons", [])

    obj_areas = [a for a in areas if a.get("objective")]
    non_obj = [a for a in areas if not a.get("objective")]

    # 3 variantes : objectifs constants, obscuring/walls variés (variété LoS/couvert).
    variants = {
        TRAIN_TERRAINS[0]: (areas, walls),
        TRAIN_TERRAINS[1]: (obj_areas + non_obj[0::2], walls[0::2]),
        TRAIN_TERRAINS[2]: (obj_areas + non_obj[1::2], walls[1::2]),
    }

    for name, (sel_areas, sel_walls) in variants.items():
        flat_areas = [_flatten_area(a) for a in sel_areas]
        terrain = {
            "terrain_id": name[: -len(".json")],
            "terrain": flat_areas,
            "walls": sel_walls,
            "icons": icons,
            "deployment_zones": dep_zones,
        }
        # Validations dures (pas de fallback) : >=1 objectif, zones exactement {1,2}, aucun floors.
        n_obj = sum(1 for a in flat_areas if a.get("objective"))
        if n_obj < 1:
            raise ValueError(f"{name}: terrain d'entraînement sans objectif (>=1 requis)")
        zone_ids = sorted(str(z.get("id")) for z in dep_zones)
        if zone_ids != ["1", "2"]:
            raise ValueError(f"{name}: deployment_zones doivent être exactement 1 et 2, got {zone_ids}")
        if any("floors" in a for a in flat_areas):
            raise ValueError(f"{name}: un area conserve 'floors' (terrain non plat)")
        _json_dump(TERRAIN_DIR / name, terrain)
        print(f"  terrain écrit : {name} ({len(flat_areas)} areas, {n_obj} objectifs, {len(sel_walls)} murs)")


ROSTER_BASES = {
    "agent": PROJECT_ROOT / "config" / "agents" / "CoreAgent" / "rosters",
    "opponent": PROJECT_ROOT / "config" / "agents" / "_p2_rosters",
}


def _normalize_roster_ref(value, kind: str, scale: str):
    """Répare les refs de roster « nom nu » (sans '<split>/') héritées (ex: benchmark).

    - keyword 'training_random' ou liste → inchangé (formes valides gérées par le moteur) ;
    - ref déjà explicite ('<split>/...') → inchangée ;
    - nom nu → recherché sous config/.../<scale>/ et réécrit en '<split>/<sous-chemin>.json'.
      Introuvable → inchangé (le moteur lèvera une erreur explicite, pas de fallback masquant).
    """
    if not isinstance(value, str) or value == "training_random" or "/" in value:
        return value
    base = ROSTER_BASES[kind] / scale
    if not base.is_dir():
        return value
    stem = value[:-5] if value.endswith(".json") else value
    matches = sorted(base.rglob(f"{stem}.json"))
    if not matches:
        return value
    rel = matches[0].relative_to(base)
    return str(rel).replace("\\", "/")


def _is_scenario(data) -> bool:
    return (
        isinstance(data, dict)
        and "agent_roster_ref" in data
        and any(k in data for k in ("deployment_type", "deployment_type_P1", "deployment_type_P2"))
        and "composition" not in data
    )


def _migrate_scenario(data: dict, terrain_ref: str) -> dict:
    out = {k: v for k, v in data.items() if k not in LEGACY_KEYS}
    scale = out.get("scale", "150pts")
    if "agent_roster_ref" in out:
        out["agent_roster_ref"] = _normalize_roster_ref(out["agent_roster_ref"], "agent", scale)
    if "opponent_roster_ref" in out:
        out["opponent_roster_ref"] = _normalize_roster_ref(out["opponent_roster_ref"], "opponent", scale)
    out["board_ref"] = BOARD_REF
    out["terrain_ref"] = terrain_ref
    return out


def archive_training_save() -> None:
    src = SCEN_ROOT / "training_save"
    if not src.exists():
        print("  training_save déjà archivé (skip)")
        return
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dst = ARCHIVE_DIR / "training_save"
    if dst.exists():
        raise FileExistsError(f"Archive déjà présente : {dst} (état incohérent, intervention manuelle)")
    shutil.move(str(src), str(dst))
    print(f"  training_save/ -> {dst.relative_to(SCEN_ROOT)} (archivé)")


def migrate_bank() -> int:
    files: list[Path] = []
    for d in ACTIVE_DIRS:
        files.extend(sorted((SCEN_ROOT / d).rglob("*.json")))
    scen_files = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON invalide : {f}: {e}")
        if _is_scenario(data):
            scen_files.append((f, data))
    scen_files.sort(key=lambda t: str(t[0].relative_to(SCEN_ROOT)))
    n = 0
    for idx, (f, data) in enumerate(scen_files):
        terrain_ref = TRAIN_TERRAINS[idx % len(TRAIN_TERRAINS)]
        migrated = _migrate_scenario(data, terrain_ref)
        _json_dump(f, migrated)
        n += 1
    print(f"  {n} scénarios migrés (board_ref + terrain_ref, clés legacy supprimées)")
    return n


def main() -> int:
    if not BASE_TERRAIN.exists():
        raise FileNotFoundError(f"Terrain de base absent : {BASE_TERRAIN}")
    print("[1/3] Génération des terrains d'entraînement plats")
    build_training_terrains()
    print("[2/3] Archivage de training_save/")
    archive_training_save()
    print("[3/3] Migration de la banque active")
    migrate_bank()
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
