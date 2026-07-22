#!/usr/bin/env python3
"""Verrou du scénario SM vs Orks à placement manuel (scenario_fixed_brawl_sm_orks.json).

Prouve, sur le VRAI moteur (W40KEngine, chemin gym réel), que le MÊME fichier fonctionne dans les
deux modes pilotés par le seul champ `deployment_type` :
  - "fixed"  : AUCUNE phase de déploiement, les 36 figurines sont à leurs positions manuelles dès reset ;
  - "active" : phase de déploiement (positions du fichier ignorées, figurines à la sentinelle -1).

Lancement : python3 scripts/fixed_brawl_turn1_test.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.training_utils import setup_imports
from ai.unit_registry import UnitRegistry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = os.path.join(ROOT, "config/board/44x60x5/scenario/scenario_fixed_brawl_sm_orks.json")
# Deux chemins DISTINCTS : le loader mémoïse le JSON par chemin absolu (game_state ~L240),
# réutiliser un seul fichier ferait relire le cache du 1er mode au 2e.
TMP_FIXED = os.path.join(ROOT, "config/board/44x60x5/scenario/_probe_fixed.json")
TMP_ACTIVE = os.path.join(ROOT, "config/board/44x60x5/scenario/_probe_active.json")


def build_env(scenario_path, W40KEngine, ur):
    env = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x5_new",
        controlled_agent="ArmageddonAgent",
        scenario_file=scenario_path,
        unit_registry=ur,
        quiet=True,
        gym_training_mode=True,
    )
    env.reset(seed=7)
    return env


def main() -> int:
    W40KEngine, _ = setup_imports()
    ur = UnitRegistry()

    base = json.load(open(SCENARIO))
    n_models_expected = sum(len(u.get("models", [u])) for u in base["units"])

    # --- mode fixed : placement manuel, aucun déploiement ---
    fixed = dict(base)
    fixed["deployment_type"] = "fixed"
    json.dump(fixed, open(TMP_FIXED, "w"))
    env = build_env(TMP_FIXED, W40KEngine, ur)
    gs = env.game_state
    if gs["phase"] == "deployment":
        raise AssertionError("mode fixed : phase 'deployment' rencontrée — placement non figé")
    placed = [u for u in gs["units"] if u["col"] >= 0]
    if len(placed) != len(gs["units"]):
        raise AssertionError(
            f"mode fixed : {len(gs['units']) - len(placed)} unité(s) non placée(s) (sentinelle -1)"
        )
    n_models = sum(len(u.get("models", [u])) for u in gs["units"])
    print(f"✅ fixed  : phase initiale={gs['phase']!r}, {len(gs['units'])} unités / "
          f"{n_models} figurines placées (aucun déploiement)")

    # --- mode active : phase de déploiement, positions ignorées ---
    active = dict(base)
    active["deployment_type"] = "active"
    json.dump(active, open(TMP_ACTIVE, "w"))
    env = build_env(TMP_ACTIVE, W40KEngine, ur)
    gs = env.game_state
    if gs["phase"] != "deployment":
        raise AssertionError(f"mode active : phase attendue 'deployment', obtenue {gs['phase']!r}")
    sentinels = [u for u in gs["units"] if u["col"] < 0]
    if not sentinels:
        raise AssertionError("mode active : aucune unité en attente de déploiement (sentinelle -1)")
    print(f"✅ active : phase initiale={gs['phase']!r}, {len(sentinels)} unités en attente de déploiement")

    os.remove(TMP_FIXED)
    os.remove(TMP_ACTIVE)
    if n_models != n_models_expected:
        raise AssertionError(f"nombre de figurines incohérent : {n_models} != {n_models_expected}")
    print(f"\n✅ VERROU OK : même fichier, bascule fixed↔active par `deployment_type` "
          f"({n_models_expected} figurines).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
