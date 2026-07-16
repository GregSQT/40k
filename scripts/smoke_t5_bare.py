#!/usr/bin/env python3
"""V11 T5 — Smoke moteur nu (gym, sans wrapper) : critères de sortie T5.

Deux volets, tout en `gym_training_mode=True`, actions masquées aléatoires (`W40KEngine` seul) :

  (A) BOUCLE COMPLÈTE / INVARIANT R7 — sur ≥3 scénarios d'entraînement `active` × plusieurs
      seeds : chaque épisode se termine (`game_over`), zéro masque vide sans terminaison
      (`get_action_mask()` complète la phase fight à pools vides). Vérifie aussi l'absence de
      deadlock de déploiement (fix parité masque/commit).

  (B) MÊLÉE GARANTIE + CARNIFEX EN CHARGE — scénario fixe minimal (écrit en tmp) avec une paire
      pré-engagée (ScreamerKiller vs Termagant) → pertes en mêlée réelles via FIGHT_CTX, et un
      Carnifex (socle ovale, BASE_SIZE liste) à portée de charge → éligibilité charge sans
      TypeError (R6).

Usage : `python3 scripts/smoke_t5_bare.py`  (PYTHONPATH=. si lancé hors venv projet).
Sortie : rapport + code retour non nul si un critère échoue. Aucune modif de fichier de config.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

BANK_DIR = PROJECT_ROOT / "config" / "agents" / "CoreAgent" / "scenarios" / "training"
TRAINING_SCENARIOS = ["scenario_training_bot-01.json", "scenario_training_bot-02.json",
                      "scenario_training_bot-03.json"]
SEEDS = (1, 2, 3)

MELEE_SCENARIO = {
    "primary_objectives": ["objectives_control"],
    "board_ref": "44x60x5",
    "terrain_ref": "terrain-train-01.json",
    "deployment_type": "fixed",
    "units": [
        {"id": "1", "player": 1, "unit_type": "ScreamerKiller", "col": 60, "row": 200},
        {"id": "2", "player": 2, "unit_type": "Termagant", "col": 60, "row": 214},
        {"id": "3", "player": 1, "unit_type": "Carnifex", "col": 60, "row": 250},
        {"id": "4", "player": 2, "unit_type": "Termagant", "col": 60, "row": 272},
    ],
}


def log(m: str) -> None:
    print(m, flush=True)


def _make_engine(scenario_path: str, seed: int):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="CoreAgent", training_config_name="x1_debug", controlled_agent="CoreAgent",
        scenario_file=scenario_path, unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    eng.reset(seed=seed)
    return eng


def _p2_alive_models(gs) -> int:
    from engine.phase_handlers.shared_utils import is_model_alive

    sm = gs["squad_models"]
    by_id = {str(u["id"]): int(u["player"]) for u in gs["units"]}
    return sum(1 for uid, mids in sm.items() if by_id.get(str(uid)) == 2
               for mid in mids if is_model_alive(mid, gs))


def _run(scenario_path: str, seed: int, *, track_melee: bool = False):
    eng = _make_engine(scenario_path, seed)
    gs = eng.game_state
    dec = eng.action_decoder
    empty_mask = False
    melee_kills = 0
    carnifex_charge = False
    terminated = False
    steps = 0
    while steps < 4000:
        if gs.get("game_over"):
            terminated = True
            break
        if track_melee and gs.get("phase") == "charge":
            if any(str(u["id"]) == "3" for u in dec._get_eligible_units_for_current_phase(gs)):
                carnifex_charge = True
        mask = eng.get_action_mask()
        if gs.get("game_over"):
            terminated = True
            break
        if not mask.any():
            empty_mask = True
            break
        before = _p2_alive_models(gs) if track_melee else 0
        phase_before = gs.get("phase")
        a = int(np.random.default_rng(seed * 99991 + steps).choice(np.flatnonzero(mask)))
        _o, _r, term, trunc, _i = eng.step(a)
        steps += 1
        if track_melee and phase_before == "fight":
            melee_kills += max(0, before - _p2_alive_models(gs))
        if term or trunc:
            terminated = True
            break
    return {"terminated": terminated, "empty_mask": empty_mask, "steps": steps,
            "turn": gs.get("turn"), "winner": gs.get("winner"),
            "melee_kills": melee_kills, "carnifex_charge": carnifex_charge}


def volet_a() -> bool:
    log("=== (A) Boucle complète / invariant R7 — scénarios active ===")
    ok = True
    for scen in TRAINING_SCENARIOS:
        path = str(BANK_DIR / scen)
        for seed in SEEDS:
            r = _run(path, seed)
            status = "OK" if (r["terminated"] and not r["empty_mask"]) else "ÉCHEC"
            if status != "OK":
                ok = False
            log(f"  {scen} seed={seed}: {status} terminated={r['terminated']} "
                f"empty_mask={r['empty_mask']} steps={r['steps']} turn={r['turn']}")
    return ok


def volet_b() -> bool:
    log("=== (B) Mêlée garantie (FIGHT_CTX) + Carnifex en charge (R6) ===")
    with tempfile.TemporaryDirectory() as td:
        scen_path = Path(td) / "scen_melee.json"
        scen_path.write_text(json.dumps(MELEE_SCENARIO), encoding="utf-8")
        total_kills = 0
        carn_any = False
        all_term = True
        for seed in (1, 2, 3, 4, 5):
            r = _run(str(scen_path), seed, track_melee=True)
            if not r["terminated"] or r["empty_mask"]:
                all_term = False
            total_kills += r["melee_kills"]
            carn_any = carn_any or r["carnifex_charge"]
            log(f"  seed={seed}: terminated={r['terminated']} empty_mask={r['empty_mask']} "
                f"melee_kills={r['melee_kills']} carnifex_charge={r['carnifex_charge']}")
        ok = all_term and total_kills > 0 and carn_any
        log(f"  -> terminate_all={all_term} melee_kills_total={total_kills} carnifex_charge_any={carn_any}")
        return ok


def main() -> int:
    a = volet_a()
    b = volet_b()
    log("")
    log(f"RÉSULTAT T5 : (A) invariant/terminaison={'OK' if a else 'ÉCHEC'} | "
        f"(B) mêlée+Carnifex={'OK' if b else 'ÉCHEC'}")
    return 0 if (a and b) else 1


if __name__ == "__main__":
    sys.exit(main())
