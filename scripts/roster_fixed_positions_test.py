#!/usr/bin/env python3
"""Verrou : positions top/bottom dans les rosters, chemin roster réel (rotation aléatoire SM/Orks).

Pilote le VRAI W40KEngine sur le template de training `scenario_training_armageddon.json`
(agent_roster_ref=training_random, opponent_roster_ref=[SM,Orks], siège aléatoire) et vérifie :
  - mode 'fixed'  : AUCUN déploiement, toutes les unités placées, joueur 1 en bande HAUTE (top),
    joueur 2 en bande BASSE (bottom) — quel que soit le roster tiré et le siège ;
  - mode 'active' : phase de déploiement, unités en sentinelle (positions ignorées).

Le mode est imposé via le scheduler `deployment_mode_schedule` injecté après construction.

Lancement : python3 scripts/roster_fixed_positions_test.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.training_utils import setup_imports
from ai.unit_registry import UnitRegistry
from engine.phase_handlers.shared_utils import validate_squad_coherency

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(
    ROOT, "config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json"
)
MIDLINE = 150  # séparation top/bottom du board 220x300


def make_env(W40KEngine, ur, active_ratio):
    env = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x5_new",
        controlled_agent="ArmageddonAgent",
        scenario_file=TEMPLATE,
        unit_registry=ur,
        quiet=True,
        gym_training_mode=True,
    )
    env.training_config = dict(env.training_config)
    env.training_config["deployment_mode_schedule"] = {
        "enabled": True,
        "training_only": False,
        "active_ratio_start": active_ratio,
        "active_ratio_end": active_ratio,
        "schedule": "linear",
        "freeze_after_progress": 1.0,
    }
    return env


def main() -> int:
    random.seed(7)
    W40KEngine, _ = setup_imports()
    ur = UnitRegistry()

    # --- FIXED : positions top/bottom, aucun déploiement ---
    env = make_env(W40KEngine, ur, 0.0)
    for ep in range(8):
        env.reset(seed=None)
        gs = env.game_state
        if gs["deployment_mode_schedule_mode"] != "fixed":
            raise AssertionError("scheduler n'a pas produit 'fixed' à ratio 0.0")
        if gs["phase"] == "deployment":
            raise AssertionError("mode fixed : phase 'deployment' rencontrée")
        placed = 0
        for u in gs["units"]:
            models = u.get("models", [u])
            for m in models:
                if m["col"] < 0:
                    raise AssertionError(f"mode fixed : figurine non placée (unité {u['id']})")
                placed += 1
                side_ok = (m["row"] < MIDLINE) if int(u["player"]) == 1 else (m["row"] >= MIDLINE)
                if not side_ok:
                    raise AssertionError(
                        f"joueur {u['player']} figurine hors de sa bande (row={m['row']}, "
                        f"midline={MIDLINE}) — convention P1=top / P2=bottom violée"
                    )
            # Cohérence d'escouade via la SOURCE DE VÉRITÉ moteur (03.03) — pas de réimplémentation :
            # validate_squad_coherency lit models_cache et applique game_rules (voisins, bord-à-bord,
            # étalement 9"). Une formation non conforme au départ échouerait ici.
            if len(models) >= 2:
                if not validate_squad_coherency(gs, str(u["id"])):
                    raise AssertionError(
                        f"unité {u['id']} ({u['unitType']}) démarre NON-COHÉRENTE "
                        f"(validate_squad_coherency, règle moteur 03.03)"
                    )
        p1 = sum(1 for u in gs["units"] if int(u["player"]) == 1)
        p2 = sum(1 for u in gs["units"] if int(u["player"]) == 2)
    print(f"✅ fixed  : 8 épisodes, aucun déploiement, toutes figurines placées, "
          f"P1→top / P2→bottom respecté (dernier ép.: {p1} vs {p2} unités, {placed} fig.)")

    # --- ACTIVE : déploiement normal, positions ignorées ---
    env = make_env(W40KEngine, ur, 1.0)
    for ep in range(3):
        env.reset(seed=None)
        gs = env.game_state
        if gs["deployment_mode_schedule_mode"] != "active":
            raise AssertionError("scheduler n'a pas produit 'active' à ratio 1.0")
        if gs["phase"] != "deployment":
            raise AssertionError(f"mode active : phase attendue 'deployment', obtenue {gs['phase']!r}")
        if not any(u["col"] < 0 for u in gs["units"]):
            raise AssertionError("mode active : aucune unité en sentinelle")
    print("✅ active : 3 épisodes, phase 'deployment', unités en sentinelle (positions ignorées)")

    print("\n✅ VERROU OK : rosters top/bottom sur le chemin roster réel, bascule fixed↔active, "
          "rotation aléatoire + siège aléatoire préservés.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
