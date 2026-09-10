"""Verrou du scénario SM vs Orks à placement manuel (scenario_fixed_brawl_sm_orks.json).

Prouve, sur le VRAI moteur (W40KEngine, chemin gym réel), que le MÊME fichier fonctionne dans les
deux modes pilotés par le seul champ `deployment_type` :
  - "fixed"  : AUCUNE phase de déploiement, les 36 figurines sont à leurs positions manuelles dès reset ;
  - "active" : phase de déploiement (positions du fichier ignorées, figurines à la sentinelle -1).

Rapatrié de `scripts/fixed_brawl_deploy_modes_test.py` (2026-07-26) : ce fichier vivait hors de
`tests/` et son nom `*_test.py` ne correspondait pas à `python_files = test_*.py`, donc il n'était
jamais collecté par la suite.
"""

from __future__ import annotations

import json
import os

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCENARIO = os.path.join(PROJECT_ROOT, "config/board/44x60x5/scenario/scenario_fixed_brawl_sm_orks.json")


@pytest.fixture(scope="module")
def base_scenario():
    with open(SCENARIO, encoding="utf-8") as fh:
        return json.load(fh)


def _write_probe(tmp_path_factory, base, deployment_type: str) -> str:
    """Écrit une copie du scénario avec `deployment_type` forcé.

    Deux chemins DISTINCTS par mode : le loader mémoïse le JSON par chemin absolu (game_state
    ~L240), réutiliser un seul fichier ferait relire le cache du 1er mode au 2e.
    """
    probe = dict(base)
    probe["deployment_type"] = deployment_type
    path = tmp_path_factory.mktemp(f"brawl_{deployment_type}") / f"_probe_{deployment_type}.json"
    path.write_text(json.dumps(probe), encoding="utf-8")
    return str(path)


def _build_env(scenario_path: str):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    env = W40KEngine(
        rewards_config="ArmageddonAgent_x1",
        training_config_name="x1",
        controlled_agent="ArmageddonAgent_x1",
        scenario_file=scenario_path,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
    )
    env.reset(seed=7)
    return env


def _n_models(units) -> int:
    return sum(len(u.get("models", [u])) for u in units)  # get allowed (unité mono-figurine)


def test_fixed_mode_places_every_model_without_deployment_phase(tmp_path_factory, base_scenario):
    """`deployment_type: fixed` → aucune phase 'deployment', toutes les unités placées."""
    env = _build_env(_write_probe(tmp_path_factory, base_scenario, "fixed"))
    gs = env.game_state

    assert gs["phase"] != "deployment", "mode fixed : phase 'deployment' rencontrée — placement non figé"
    unplaced = [u for u in gs["units"] if u["col"] < 0]
    assert not unplaced, f"mode fixed : {len(unplaced)} unité(s) à la sentinelle -1"
    assert _n_models(gs["units"]) == _n_models(base_scenario["units"]), (
        "nombre de figurines incohérent entre le fichier et l'état moteur"
    )


def test_active_mode_runs_deployment_phase(tmp_path_factory, base_scenario):
    """`deployment_type: active` → phase 'deployment', positions du fichier ignorées (sentinelle)."""
    env = _build_env(_write_probe(tmp_path_factory, base_scenario, "active"))
    gs = env.game_state

    assert gs["phase"] == "deployment", f"mode active : phase attendue 'deployment', obtenue {gs['phase']!r}"
    assert any(u["col"] < 0 for u in gs["units"]), (
        "mode active : aucune unité en attente de déploiement (sentinelle -1)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Surcharge PAR JOUEUR : `deployment_type_P1` / `deployment_type_P2`
#
# CE QUI A ETE MANQUE. L'ouverture de la phase teste le mode PAR JOUEUR
# (`any(effective_deployment_type_by_player[p] == "active")`), mais la synchronisation du joueur
# courant testait `deployment_type`, le mode GLOBAL. Un scenario qui ne declare que
# `deployment_type_P2: "active"` laisse ce champ a "fixed" : la phase de deploiement s'ouvrait
# bien, le deployeur etait le joueur 2, et `current_player` restait a 1 — le masque de
# deploiement etait donc construit pour un joueur qui n'a rien a poser.
# ─────────────────────────────────────────────────────────────────────────────

def _write_per_player_probe(tmp_path_factory, base, **overrides) -> str:
    """Copie du scenario avec des surcharges de mode PAR JOUEUR (sans `deployment_type` global)."""
    probe = dict(base)
    probe.pop("deployment_type", None)
    probe.update(overrides)
    label = "_".join(f"{k}{v}" for k, v in sorted(overrides.items()))
    path = tmp_path_factory.mktemp(f"brawl_{label}") / f"_probe_{label}.json"
    path.write_text(json.dumps(probe), encoding="utf-8")
    return str(path)


def test_only_p2_active_makes_p2_the_current_player(tmp_path_factory, base_scenario):
    """Seul P2 en `active` → phase 'deployment' ET c'est P2 qui joue."""
    env = _build_env(_write_per_player_probe(tmp_path_factory, base_scenario, deployment_type_P2="active"))
    gs = env.game_state

    # Premisses : le mode GLOBAL n'est pas "active", et la phase s'ouvre quand meme.
    assert gs["deployment_type"] != "active", (
        "premisse cassee : le scenario declare un mode global 'active', le test ne vise plus la surcharge"
    )
    assert gs["phase"] == "deployment", f"phase attendue 'deployment', obtenue {gs['phase']!r}"
    assert gs["deployment_state"]["current_deployer"] == 2, (
        "premisse cassee : P2 n'est pas le deployeur, le test ne verifie pas la synchronisation"
    )

    assert gs["current_player"] == 2, (
        "le joueur courant ne suit pas le deployeur : le masque de deploiement serait construit "
        "pour le joueur 1, qui n'a rien a poser"
    )


def test_only_p1_active_keeps_p1_as_current_player(tmp_path_factory, base_scenario):
    """Jumeau : seul P1 en `active` → le deployeur reste P1, et le joueur courant aussi."""
    env = _build_env(_write_per_player_probe(tmp_path_factory, base_scenario, deployment_type_P1="active"))
    gs = env.game_state

    assert gs["phase"] == "deployment"
    assert gs["deployment_state"]["current_deployer"] == 1
    assert gs["current_player"] == 1
