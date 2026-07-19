"""V11 T5 — Parité masque/commit du déploiement `active` (régression deadlock).

Rupture corrigée (2026-07-15) : `ActionDecoder._get_valid_deployment_hexes` (masque des
actions 4-8) testait le chevauchement inter-unités par CELLULES (`build_occupied_positions_set`),
alors que le commit `deployment_handlers.deploy_unit` le teste par CLEARANCE euclidien CONTINU
(`candidate_overlaps_any_unit`, plus strict rond↔rond). Résultat : le masque proposait des hexes
que le commit rejetait (`deploy_footprint_occupied`) → l'action restait dans le masque mais
échouait à chaque fois → deadlock (épisode tué au garde 1000 steps).

Le fix aligne le masque sur le commit (miroir strict, cf. règle projet « le déploiement copie la
phase move »). Deux verrous :
- **Parité** : chaque hex offert par le masque est accepté par le prédicat de chevauchement du
  commit (`_is_footprint_overlapping`).
- **Comportement anti-deadlock** : en forçant le clustering (même stratégie de déploiement à
  chaque unité), le déploiement se termine SANS jamais lever `deploy_footprint_occupied`.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BANK_DIR = PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent" / "scenarios" / "training"


def _load(scenario_file: str, seed: int = 0):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug", controlled_agent="ArmageddonAgent",
        scenario_file=scenario_file, unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    eng.reset(seed=seed)
    return eng


def _drive_deployment_clustered(eng, *, assert_parity: bool):
    """Déroule la phase de déploiement en choisissant SYSTÉMATIQUEMENT la plus petite action de
    déploiement disponible (même stratégie → clustering maximal, condition qui déclenchait le
    deadlock). Retourne le nombre d'hexes vérifiés en parité."""
    from engine.phase_handlers.deployment_handlers import _is_footprint_overlapping
    from engine.phase_handlers.shared_utils import compute_candidate_footprint

    gs = eng.game_state
    dec = eng.action_decoder
    checked = 0
    steps = 0
    while gs.get("phase") == "deployment" and steps < 1000:
        mask = eng.get_action_mask()
        assert mask.any(), f"masque vide en déploiement (step {steps})"
        deploy_actions = [a for a in range(4, 9) if mask[a]]
        assert deploy_actions, f"aucune action de déploiement dans le masque (step {steps})"

        if assert_parity:
            elig = dec._get_eligible_units_for_current_phase(gs)
            deployer = dec._get_current_deployer(gs)
            uid = str(elig[0]["id"])
            unit = next(u for u in gs["units"] if str(u["id"]) == uid)
            for action_int in deploy_actions:
                valid = dec._get_valid_deployment_hexes(gs, deployer, uid)
                dest = dec._select_deployment_hex_for_action(
                    action_int=action_int, unit_id=uid, game_state=gs,
                    current_deployer=deployer, valid_hexes=valid,
                )
                fp = compute_candidate_footprint(int(dest[0]), int(dest[1]), unit, gs)
                assert not _is_footprint_overlapping(
                    gs, fp, shape=unit["BASE_SHAPE"], base_size=unit["BASE_SIZE"],
                    col=int(dest[0]), row=int(dest[1]), exclude_unit_id=uid,
                ), (f"hex ({dest[0]},{dest[1]}) proposé par le masque (action {action_int}) "
                    f"mais rejeté par le commit — parité masque/commit rompue")
                checked += 1

        eng.step(int(deploy_actions[0]))
        ld = gs.get("last_action_debug") or {}
        err = ld.get("result_error") if isinstance(ld, dict) else None
        assert err != "deploy_footprint_occupied", (
            f"le masque a proposé un hex rejeté au commit (step {steps}) → deadlock déploiement")
        steps += 1

    assert gs.get("phase") != "deployment", "déploiement non terminé (deadlock)"
    return checked


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_active_deployment_completes_without_unplaceable_hex(seed):
    """Déploiement `active` en clustering forcé → se termine, zéro `deploy_footprint_occupied`."""
    eng = _load(str(BANK_DIR / "scenario_training_armageddon.json"), seed=seed)
    assert eng.game_state.get("phase") == "deployment", "le scénario doit démarrer en déploiement actif"
    _drive_deployment_clustered(eng, assert_parity=False)


def test_deployment_mask_mirrors_commit_overlap_predicate():
    """Chaque hex offert par le masque de déploiement est accepté par le prédicat du commit."""
    eng = _load(str(BANK_DIR / "scenario_training_armageddon.json"), seed=0)
    checked = _drive_deployment_clustered(eng, assert_parity=True)
    assert checked > 0, "aucun hex vérifié — le test n'a pas exercé la phase de déploiement"
