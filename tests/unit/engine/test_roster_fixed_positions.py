"""Verrou : positions top/bottom dans les rosters, chemin roster réel (rotation aléatoire SM/Orks).

Pilote le VRAI W40KEngine sur le template de training `scenario_training_armageddon.json`
(agent_roster_ref=training_random, opponent_roster_ref=[SM,Orks], siège aléatoire) et vérifie :
  - mode 'fixed'  : AUCUN déploiement, toutes les unités placées, joueur 1 en bande HAUTE (top),
    joueur 2 en bande BASSE (bottom) — quel que soit le roster tiré et le siège ;
  - mode 'active' : phase de déploiement, unités en sentinelle (positions ignorées).

Le mode est imposé via le scheduler `deployment_mode_schedule` injecté après construction.

Rapatrié de `scripts/roster_fixed_positions_test.py` (2026-07-26) : ce fichier vivait hors de
`tests/` et son nom `*_test.py` ne correspondait pas à `python_files = test_*.py`, donc il n'était
jamais collecté par la suite.
"""

from __future__ import annotations

import os

from engine.phase_handlers.shared_utils import validate_squad_coherency

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TEMPLATE = os.path.join(
    PROJECT_ROOT, "config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json"
)
MIDLINE = 150  # séparation top/bottom du board 220x300


def _make_env(active_ratio: float):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    env = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x5_new",
        controlled_agent="ArmageddonAgent",
        scenario_file=TEMPLATE,
        unit_registry=UnitRegistry(),
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


def test_fixed_mode_places_players_in_their_own_band():
    """Mode 'fixed' : 8 épisodes, aucun déploiement, P1 en bande haute / P2 en bande basse."""
    env = _make_env(0.0)
    placed_total = 0
    for _ep in range(8):
        env.reset(seed=None)
        gs = env.game_state
        assert gs["deployment_mode_schedule_mode"] == "fixed", "scheduler n'a pas produit 'fixed' à ratio 0.0"
        assert gs["phase"] != "deployment", "mode fixed : phase 'deployment' rencontrée"

        for u in gs["units"]:
            models = u.get("models", [u])  # get allowed (unité mono-figurine)
            for m in models:
                assert m["col"] >= 0, f"mode fixed : figurine non placée (unité {u['id']})"
                placed_total += 1
                side_ok = (m["row"] < MIDLINE) if int(u["player"]) == 1 else (m["row"] >= MIDLINE)
                assert side_ok, (
                    f"joueur {u['player']} figurine hors de sa bande (row={m['row']}, "
                    f"midline={MIDLINE}) — convention P1=top / P2=bottom violée"
                )
            # Cohérence d'escouade via la SOURCE DE VÉRITÉ moteur (03.03) — pas de réimplémentation :
            # validate_squad_coherency lit models_cache et applique game_rules (voisins, bord-à-bord,
            # étalement 9"). Une formation non conforme au départ échouerait ici.
            if len(models) >= 2:
                assert validate_squad_coherency(gs, str(u["id"])), (
                    f"unité {u['id']} ({u['unitType']}) démarre NON-COHÉRENTE "
                    f"(validate_squad_coherency, règle moteur 03.03)"
                )

    assert placed_total > 0, "aucune figurine inspectée — test sans valeur"


def test_active_mode_keeps_units_at_sentinel():
    """Mode 'active' : 3 épisodes, phase 'deployment', positions du roster ignorées."""
    env = _make_env(1.0)
    for _ep in range(3):
        env.reset(seed=None)
        gs = env.game_state
        assert gs["deployment_mode_schedule_mode"] == "active", "scheduler n'a pas produit 'active' à ratio 1.0"
        assert gs["phase"] == "deployment", f"mode active : phase attendue 'deployment', obtenue {gs['phase']!r}"
        assert any(u["col"] < 0 for u in gs["units"]), "mode active : aucune unité en sentinelle"
