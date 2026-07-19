"""V11 T4 — Migration de banque de scénarios (script) + hygiène de la banque ArmageddonAgent.

Couvre :
- l'idempotence de la transformation `_migrate_scenario` (2e passage = même résultat) ;
- la normalisation des refs de roster « nom nu » héritées ;
- l'invariant statique sur les 61 scénarios migrés (zéro clé legacy, board_ref + terrain_ref) ;
- le chargement moteur + reset sur un échantillon couvrant chaque voie de déploiement
  (active / random / P1-P2 / benchmark / matchup) : >= 1 objectif, deployment_pools joueurs {1,2}.

Le balayage EXHAUSTIF des 61 (W40KEngine + reset) est fourni par
`scripts/sweep_scenario_bank_v11.py` (trop lourd pour la suite unitaire) ; ce test en couvre
l'invariant statique sur les 61 + un échantillon représentatif chargé de bout en bout.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCEN_ROOT = PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent" / "scenarios"
ACTIVE_DIRS = ["training", "holdout_regular", "holdout_hard"]
LEGACY_KEYS = ("objectives", "objectives_ref", "objective_hexes", "deployment_zone", "wall_ref")
# Décision utilisateur 2026-07-19 : `terrain-train-01/02/03` sont OBSOLÈTES, toute la banque
# (training + holdouts) tourne sur `terrain-mc1.json` jusqu'à nouvel ordre. Les terrains
# d'entraînement étaient les versions APLATIES de mc1 générées par `migrate_scenario_bank_v11.py`
# (Phase A « pas d'étages ») ; la banque porte donc désormais les 8 étages de mc1.
# ⚠️ Ce script de migration T4 cycle encore sur les 3 terrains plats : le RELANCER repointerait
# la banque dessus et casserait ce test — il est one-shot et déjà passé.
TRAIN_TERRAINS = {"terrain-mc1.json"}


def _load_migration_module():
    path = PROJECT_ROOT / "scripts" / "migrate_scenario_bank_v11.py"
    spec = importlib.util.spec_from_file_location("migrate_scenario_bank_v11", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Impossible de charger le module de migration depuis {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


MIG = _load_migration_module()


def _bank_scenarios() -> list[Path]:
    files: list[Path] = []
    for d in ACTIVE_DIRS:
        for f in sorted((SCEN_ROOT / d).rglob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict) and "agent_roster_ref" in data and "composition" not in data:
                files.append(f)
    return files


# ── Transformation : idempotence + strip legacy ─────────────────────────────────

def test_migrate_scenario_strips_legacy_and_adds_refs():
    src = {
        "deployment_zone": "hammer",
        "deployment_type": "active",
        "scale": "150pts",
        "agent_roster_ref": "training_random",
        "opponent_roster_ref": "training_random",
        "wall_ref": "random",
        "objectives_ref": "objectives-51.json",
        "primary_objectives": ["objectives_control"],
    }
    out = MIG._migrate_scenario(src, "terrain-train-01.json")
    assert not any(k in out for k in LEGACY_KEYS)
    assert out["board_ref"] == "44x60x5"
    assert out["terrain_ref"] == "terrain-train-01.json"
    assert out["deployment_type"] == "active"  # clé non-legacy préservée


def test_migrate_scenario_is_idempotent():
    src = {
        "deployment_zone": "hammer",
        "deployment_type": "random",
        "scale": "150pts",
        "agent_roster_ref": "training_random",
        "opponent_roster_ref": "training_random",
        "wall_ref": "walls-11.json",
        "objectives_ref": "objectives-51.json",
        "primary_objectives": ["objectives_control"],
    }
    once = MIG._migrate_scenario(src, "terrain-train-02.json")
    twice = MIG._migrate_scenario(once, "terrain-train-02.json")
    assert once == twice


def test_normalize_roster_ref_keeps_keyword_and_explicit():
    assert MIG._normalize_roster_ref("training_random", "agent", "150pts") == "training_random"
    assert (
        MIG._normalize_roster_ref("training/foo.json", "agent", "150pts") == "training/foo.json"
    )


def test_normalize_roster_ref_fixes_bare_benchmark_name():
    ref = MIG._normalize_roster_ref("agent_training_roster_benchmark_classic", "agent", "150pts")
    assert "/" in ref and ref.endswith(".json")


# ── Invariant statique sur les 61 scénarios migrés ──────────────────────────────

def test_bank_has_expected_count():
    # Banque ArmageddonAgent (2026-07-19) : 1 scenario training + 4 holdout_regular = les
    # 4 matchups SM/Ork. L'ancienne banque CoreAgent (61 scenarios) a ete retiree ; ce test
    # garde desormais la banque VIVANTE contre une perte accidentelle de scenario.
    assert len(_bank_scenarios()) == 5


@pytest.mark.parametrize("scen", _bank_scenarios(), ids=lambda p: str(p.relative_to(SCEN_ROOT)))
def test_bank_scenario_has_no_legacy_and_valid_refs(scen):
    data = json.loads(scen.read_text(encoding="utf-8-sig"))
    assert not any(k in data for k in LEGACY_KEYS), f"clé legacy dans {scen}"
    assert data.get("board_ref") == "44x60x5"
    assert data.get("terrain_ref") in TRAIN_TERRAINS


# ── Échantillon chargé de bout en bout (moteur + reset) ─────────────────────────

_SAMPLE = [
    "training/scenario_training_armageddon.json",   # training_random + opponent_roster_ref liste
    "holdout_regular/scenario_bot-01.json",         # roster explicite holdout, matchup SM vs SM
    "holdout_regular/scenario_bot-02.json",         # matchup mixte SM vs Ork
]


@pytest.mark.parametrize("rel", _SAMPLE)
def test_sample_scenario_loads_and_resets(rel):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    f = SCEN_ROOT / rel
    eng = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent",
        scenario_file=str(f),
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
    )
    eng.reset(seed=0)
    objectives = eng.game_state.get("objectives") or []
    assert len(objectives) >= 1, f"0 objectif résolu pour {rel}"
    pools = eng.config.get("deployment_pools")
    assert isinstance(pools, dict) and sorted(pools.keys()) == [1, 2]
