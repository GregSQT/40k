"""V11 T5 — Boucle complète moteur nu (gym) : terminaison, invariant masque, mêlée, Carnifex.

Couvre les critères de sortie T5 sur le MOTEUR NU (gym_training_mode, sans wrapper) :
- **Invariant R7** : à chaque step, `mask.any() or game_over` — jamais de masque vide sans
  terminaison (ce qui ferait exploser MaskablePPO). `get_action_mask()` complète la phase fight
  quand ses pools sont vides.
- **Terminaison** : l'épisode se termine (turn limit atteint, `game_over=True`).
- **Pertes en mêlée (FIGHT_CTX)** : une paire pré-engagée résout le combat en auto (défenseur
  non-humain → allocation auto) et inflige des pertes réelles (chemin FIGHT_CTX de R4/T1).
- **Carnifex en phase charge (R6)** : une unité à socle ovale (`BASE_SIZE` liste) est éligible en
  charge sans `TypeError` (fix R6).

Scénario fixe minimal (écrit en tmp) : ScreamerKiller(P1) pré-engagé avec Termagant(P2) ;
Carnifex(P1) non engagé à portée de charge d'un Termagant(P2). Positions vérifiées hors murs sur
terrain-train-01.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_SCENARIO = {
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


def _make_engine(scenario_path: str, seed: int):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug", controlled_agent="ArmageddonAgent",
        scenario_file=scenario_path, unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    eng.reset(seed=seed)
    return eng


def _p2_alive_models(gs) -> int:
    from engine.phase_handlers.shared_utils import is_model_alive

    sm = gs["squad_models"]
    by_id = {str(u["id"]): int(u["player"]) for u in gs["units"]}
    return sum(
        1
        for uid, mids in sm.items()
        if by_id.get(str(uid)) == 2
        for mid in mids
        if is_model_alive(mid, gs)
    )


@pytest.fixture(scope="module")
def scenario_file(tmp_path_factory):
    p = tmp_path_factory.mktemp("t5") / "scen_melee.json"
    p.write_text(json.dumps(_SCENARIO), encoding="utf-8")
    return str(p)


def _run_episode(scenario_file, seed):
    eng = _make_engine(scenario_file, seed)
    gs = eng.game_state
    dec = eng.action_decoder
    melee_kills = 0
    carnifex_charge_eligible = False
    terminated = False
    steps = 0
    while steps < 3000:
        if gs.get("game_over"):
            terminated = True
            break
        if gs.get("phase") == "charge":
            elig = dec._get_eligible_units_for_current_phase(gs)
            if any(str(u["id"]) == "3" for u in elig):
                carnifex_charge_eligible = True
        mask = eng.get_action_mask()
        # Invariant R7 : jamais de masque vide sans terminaison.
        assert mask.any() or gs.get("game_over"), (
            f"masque vide sans game_over (phase={gs.get('phase')} turn={gs.get('turn')} "
            f"player={gs.get('current_player')})")
        if gs.get("game_over"):
            terminated = True
            break
        before = _p2_alive_models(gs)
        phase_before = gs.get("phase")
        a = int(np.random.default_rng(seed * 99991 + steps).choice(np.flatnonzero(mask)))
        _obs, _rew, term, trunc, _info = eng.step(a)
        steps += 1
        if phase_before == "fight":
            melee_kills += max(0, before - _p2_alive_models(gs))
        if term or trunc:
            terminated = True
            break
    return terminated, melee_kills, carnifex_charge_eligible


def test_bare_loop_terminates_no_empty_mask(scenario_file):
    """Chaque épisode se termine et respecte l'invariant `mask.any() or game_over` (R7)."""
    for seed in (1, 2, 3):
        terminated, _kills, _carn = _run_episode(scenario_file, seed)
        assert terminated, f"épisode seed={seed} non terminé"


def test_bare_loop_melee_losses_via_fight_ctx(scenario_file):
    """La paire pré-engagée inflige des pertes en mêlée (chemin FIGHT_CTX auto en gym)."""
    total_kills = sum(_run_episode(scenario_file, s)[1] for s in (1, 2, 3))
    assert total_kills > 0, "aucune perte en mêlée — le chemin FIGHT_CTX n'a pas résolu de blessure"


def test_bare_loop_carnifex_charge_eligible_no_r6_crash(scenario_file):
    """Un Carnifex (socle ovale, BASE_SIZE liste) est éligible en phase charge sans TypeError R6."""
    carn_any = any(_run_episode(scenario_file, s)[2] for s in (1, 2, 3))
    assert carn_any, "le Carnifex n'a jamais été vu éligible en phase charge (chemin R6 non exercé)"
