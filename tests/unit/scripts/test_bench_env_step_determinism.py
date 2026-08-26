"""Déterminisme de scripts/bench_env_step.py — deux runs à graine identique doivent être identiques.

INVARIANTS VÉRIFIÉS
--------------------
1. Séquence de scénarios identique : random.choice(scenario_files) produit la même suite même
   si l'état de random entre les deux runs a été pollué (simule deux lancements de processus).
2. Nombre de resets identique : même durée d'épisodes ⟹ même nombre de parties complètes.
3. Médiane ms/step dans les 5% : la variabilité OS résiduelle ne dépasse pas 5% entre runs.

POURQUOI CE TEST
----------------
Sans graine, trois exécutions consécutives donnaient 70 / 83 / 112 s de wall (dispersion de
60%). La cause : random.choice(scenario_files) dans W40KEngine.reset() et random.choice(actions)
dans les bots utilisent le module random global non ensemencé. _seed_randomness() fixe l'état
avant le bench réel ; ce test vérifie que le verrou tient même si random est pollué entre les
deux appels (ce qui simule deux processus distincts avec des états initiaux différents).

NOTE DE PERFORMANCE
-------------------
Chaque _bench_run construit un moteur complet et exécute ~200 steps avec des bots réels.
Durée attendue : ~10-20 s par run, ~30-40 s au total.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from tests._chargeur_script import charger_script


@pytest.fixture(scope="module")
def bench():
    return charger_script("scripts/bench_env_step.py")


def test_determinism_scenario_sequence_and_median(bench) -> None:
    """Deux runs à seed=42 restent identiques même avec pollution de random entre les appels.

    La pollution (random.seed(999) + 200 random.random()) simule un état de module
    random différent, tel que l'aurait un second processus lancé indépendamment.
    Si _seed_randomness() est appelé au début de _bench_run, la pollution est effacée
    et les deux runs produisent la même séquence de scénarios.
    """
    N_STEPS = 200  # assez pour déclencher ≥1 reset (épisodes ~80-150 steps)
    SEED = 42

    scenarios1, n_resets1, median1 = bench._bench_run(seed=SEED, n_steps=N_STEPS)

    # Polluer l'état de random pour simuler un second lancement de processus
    random.seed(999)
    for _ in range(200):
        random.random()

    scenarios2, n_resets2, median2 = bench._bench_run(seed=SEED, n_steps=N_STEPS)

    assert scenarios1 == scenarios2, (
        f"Séquences de scénarios divergent entre les deux runs :\n"
        f"  run 1 : {scenarios1}\n"
        f"  run 2 : {scenarios2}\n"
        "_seed_randomness() doit rétablir l'état avant le bench pour neutraliser la pollution."
    )

    assert n_resets1 == n_resets2, (
        f"Nombre de resets différent : run1={n_resets1}, run2={n_resets2}. "
        "Les épisodes doivent avoir la même durée à graine identique."
    )

    # Médiane : tolérance 5% pour la jitter OS résiduelle
    max_median = max(median1, median2)
    if max_median > 0:
        relative_diff = abs(median1 - median2) / max_median
        assert relative_diff < 0.05, (
            f"Médiane ms/step trop variable : run1={median1:.2f} ms, run2={median2:.2f} ms, "
            f"écart={relative_diff:.1%} > 5%. "
            "Un écart aussi large indique une différence de chemin d'exécution, pas de jitter OS."
        )
