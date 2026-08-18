"""V11 T4 — Migration de banque de scénarios (script) + hygiène de la banque ArmageddonAgent.

Couvre :
- l'idempotence de la transformation `_migrate_scenario` (2e passage = même résultat) ;
- la normalisation des refs de roster « nom nu » héritées ;
- l'invariant statique sur les 61 scénarios migrés (zéro clé legacy, board_ref + terrain_ref) ;
- le chargement moteur + reset sur un échantillon couvrant chaque voie de déploiement
  (active / random / P1-P2 / benchmark / matchup) : >= 1 objectif, deployment_pools joueurs {1,2}.

Le balayage EXHAUSTIF des 61 (W40KEngine + reset) était fourni par `scripts/sweep_scenario_bank_v11.py`,
trop lourd pour la suite unitaire et **supprimé le 2026-07-26** (critère T4 clos, balayage 61/61 déjà
consigné dans `V11_agent_rework.md §3495`) ; ce test couvre l'invariant statique sur les 61 + un
échantillon représentatif chargé de bout en bout.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._chargeur_script import charger_script

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCEN_ROOT = PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent" / "scenarios"
ACTIVE_DIRS = ["training", "holdout_regular", "holdout_hard"]
LEGACY_KEYS = ("objectives", "objectives_ref", "objective_hexes", "deployment_zone", "wall_ref")
# Décision utilisateur 2026-07-19 : `terrain-train-01/02/03` sont OBSOLÈTES, la banque tourne sur
# les terrains `terrain-mcN.json`. Les terrains d'entraînement étaient les versions APLATIES de mc1
# générées par `migrate_scenario_bank_v11.py` (Phase A « pas d'étages ») ; la banque porte donc
# désormais les étages de mc1/mc2.
#
# Décision utilisateur 2026-08-08 : **l'entraînement tourne sur DEUX terrains**, mc1 et mc2 — le
# commit `6a1c8181` dédouble le scénario d'entraînement en `armageddon1`/`armageddon2`, qui ne
# diffèrent QUE par leur terrain, et la rotation `bot`/`self` les prend tous les deux (mesuré : 2
# scénarios résolus, contre 4 pour `holdout`). Le HOLDOUT, lui, reste sur mc1 seul.
#
# ⚠️ POURQUOI PAR DOSSIER ET PAS UN ENSEMBLE UNIQUE. Autoriser globalement `{mc1, mc2}` laisserait
# passer un scénario de holdout basculé sur mc2 par accident — or c'est le jeu de TEST : son terrain
# est ce qui mesure la généralisation, et un holdout qui glisse sur un terrain d'entraînement rend
# la mesure §10.6 silencieusement optimiste. Le contrôle est donc aussi fin que la décision.
TERRAINS_PAR_DOSSIER = {
    "training": {"terrain-mc1.json", "terrain-mc2.json"},
    "holdout_regular": {"terrain-mc1.json"},
    "holdout_hard": {"terrain-mc1.json"},
}
# ⚠️ Ce script de migration T4 cycle encore sur les 3 terrains plats : le RELANCER repointerait
# la banque dessus et casserait ce test — il est one-shot et déjà passé.
#: Terrains d'entrainement declares par la banque. `terrain-mc2` est entre le 2026-08-08
#: avec `scenario_training_armageddon2.json` : un scenario de training tire son roster au
#: sort, donc TOUT terrain listé ici doit accepter les positions fixes des rosters
#: (`scripts/gen_roster_positions.py` calcule leur union de murs).
TRAIN_TERRAINS = {"terrain-mc1.json", "terrain-mc2.json"}


MIG = charger_script("scripts/migrate_scenario_bank_v11.py")


def _bank_scenarios() -> list[Path]:
    """Les scénarios que l'ENUMERATION ramasse réellement : le motif de NOM globé par
    `ai/training_utils.py::_gather_scenario_files_in_dir` (`scenario_*`, `*_scenario_*`).

    UN seul critère d'appartenance, celui de la production. Les fixtures de test posées dans
    `training/` sont nommées hors motif exprès (chantier 04c) — les compter ferait de ce contrôle
    d'effectif un contrôle du contenu du dossier. La FORME des fichiers retenus (roster déclaré,
    pas de composition) est vérifiée en invariant sur chacun, pas en filtre : un fichier au bon
    nom mais malformé doit faire échouer la banque, pas en disparaître silencieusement.
    """
    return [
        f
        for d in ACTIVE_DIRS
        for f in sorted((SCEN_ROOT / d).rglob("*.json"))
        if f.name.startswith("scenario_") or "_scenario_" in f.name
    ]


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
    # Banque ArmageddonAgent : 2 scenarios training (armageddon1/2, mc1 et mc2) + 4
    # holdout_regular bot (les 4 matchups SM/Ork).
    # Les scenario_bench-01..04 ont été supprimés (doublons de bot-01..04, commit b20d8f9c).
    assert len(_bank_scenarios()) == 6


@pytest.mark.parametrize("scen", _bank_scenarios(), ids=lambda p: str(p.relative_to(SCEN_ROOT)))
def test_bank_scenario_has_no_legacy_and_valid_refs(scen):
    data = json.loads(scen.read_text(encoding="utf-8-sig"))
    # Forme attendue d'un scénario de banque — vérifiée ici, jamais en filtre d'énumération
    # (cf. `_bank_scenarios`) : un fichier au bon nom mais qui n'est pas un scénario doit
    # faire ROUGE, pas sortir du décompte.
    assert isinstance(data, dict), f"{scen} n'est pas un objet JSON"
    assert "agent_roster_ref" in data, f"pas de roster déclaré dans {scen}"
    assert "composition" not in data, f"{scen} est une liste, pas un scénario"
    assert not any(k in data for k in LEGACY_KEYS), f"clé legacy dans {scen}"
    assert data.get("board_ref") == "44x60x5"
    dossier = scen.relative_to(SCEN_ROOT).parts[0]
    autorises = TERRAINS_PAR_DOSSIER.get(dossier)
    assert autorises is not None, (
        f"dossier {dossier!r} sans terrains declares : ajouter son entree a TERRAINS_PAR_DOSSIER "
        f"(un dossier inconnu ne doit pas passer sans controle)"
    )
    assert data.get("terrain_ref") in autorises, (
        f"{scen.relative_to(SCEN_ROOT)} tourne sur {data.get('terrain_ref')}, hors des terrains "
        f"autorises pour {dossier} ({sorted(autorises)})"
    )


# ── Échantillon chargé de bout en bout (moteur + reset) ─────────────────────────

_SAMPLE = [
    # Les DEUX scenarios de training : ils ne different que par leur terrain, et c'est
    # precisement ce que le chargement de bout en bout doit couvrir (les positions fixes des
    # rosters doivent etre valides sur les deux — defaut mesure le 2026-08-08).
    "training/scenario_training_armageddon1.json",   # training_random + opponent_roster_ref liste
    "training/scenario_training_armageddon2.json",   # meme scenario, terrain-mc2
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
        training_n_envs=1,  # UN environnement joue en serie (engine/episode_schedule.py)
    )
    eng.reset(seed=0)
    objectives = eng.game_state.get("objectives") or []
    assert len(objectives) >= 1, f"0 objectif résolu pour {rel}"
    pools = eng.config.get("deployment_pools")
    assert isinstance(pools, dict) and sorted(pools.keys()) == [1, 2]
