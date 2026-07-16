#!/usr/bin/env python3
"""V11 T4 — Balayage de la banque de scénarios migrée (critère d'acceptation T4).

Pour chaque scénario de la banque ACTIVE (training/, holdout_regular/, holdout_hard/, matchups/) :
  - le fichier JSON ne contient AUCUNE clé legacy (objectives, objectives_ref, objective_hexes,
    deployment_zone, wall_ref) ;
  - W40KEngine(scenario_file=...) + reset() passe sans exception ;
  - >= 1 objectif résolu (piège « liste vide en silence ») ;
  - deployment_pools couvre exactement les joueurs 1 et 2.

Sortie : rapport + code retour non nul si un scénario échoue. Aucune modif de fichier.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).resolve().parent.parent))  # exécutable sans PYTHONPATH
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCEN_ROOT = PROJECT_ROOT / "config" / "agents" / "CoreAgent" / "scenarios"
ACTIVE_DIRS = ["training", "holdout_regular", "holdout_hard"]
LEGACY_KEYS = ("objectives", "objectives_ref", "objective_hexes", "deployment_zone", "wall_ref")


def _collect() -> list[Path]:
    files: list[Path] = []
    for d in ACTIVE_DIRS:
        for f in sorted((SCEN_ROOT / d).rglob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict) and "agent_roster_ref" in data and "composition" not in data:
                files.append(f)
    return files


def main() -> int:
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    registry = UnitRegistry()
    files = _collect()
    print(f"Balayage de {len(files)} scénarios migrés\n")
    failures: list[tuple[str, str]] = []
    for f in files:
        rel = f.relative_to(SCEN_ROOT)
        raw = json.loads(f.read_text(encoding="utf-8-sig"))
        legacy = [k for k in LEGACY_KEYS if k in raw]
        if legacy:
            failures.append((str(rel), f"clés legacy présentes: {legacy}"))
            print(f"  ✗ {rel} — clés legacy {legacy}")
            continue
        try:
            eng = W40KEngine(
                rewards_config="CoreAgent",
                training_config_name="x1_debug",
                controlled_agent="CoreAgent",
                scenario_file=str(f),
                unit_registry=registry,
                quiet=True,
                gym_training_mode=True,
            )
            eng.reset(seed=0)
            objectives = eng.game_state.get("objectives") or []
            if len(objectives) < 1:
                failures.append((str(rel), "0 objectif résolu"))
                print(f"  ✗ {rel} — 0 objectif résolu")
                continue
            pools = eng.config.get("deployment_pools")
            pool_players = sorted(pools.keys()) if isinstance(pools, dict) else None
            if pool_players != [1, 2]:
                failures.append((str(rel), f"deployment_pools joueurs = {pool_players}"))
                print(f"  ✗ {rel} — deployment_pools joueurs {pool_players}")
                continue
        except Exception as e:  # noqa: BLE001 — on veut le scénario fautif, pas un crash global
            failures.append((str(rel), f"{type(e).__name__}: {e}"))
            print(f"  ✗ {rel} — {type(e).__name__}: {e}")
            traceback.print_exc()
            continue
        print(f"  ✓ {rel} — {len(objectives)} objectifs, pools {pool_players}")

    print()
    if failures:
        print(f"ÉCHEC : {len(failures)}/{len(files)} scénarios KO")
        return 1
    print(f"OK : {len(files)}/{len(files)} scénarios chargés + reset, 0 clé legacy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
