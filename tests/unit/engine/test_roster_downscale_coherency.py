"""Réduction de roster x5 → x1 : la formation posée doit être COHÉRENTE (03.03).

`_downscale_fixed_unit` convertit les positions du roster (écrites en subhex x5) vers le plateau
actif. Cinq subhex d'écart deviennent une case, donc les figurines s'écrasent ; celles dont la case
est prise sont décalées vers la case libre la plus proche. Ce décalage était borné PAR FIGURINE
(`unit_model_cohesion_range`), ce qui ne garantit rien sur la FORMATION : deux sœurs peuvent
s'écarter de 2 hexes en sens opposés et finir à 4 ou 5 l'une de l'autre.

Mesuré : l'escouade sortait du chargement DÉJÀ incohérente (une figurine à 3 hexes de toutes ses
sœurs), et la phase de move refusait ensuite de la déplacer — `execute_squad_move` levait
« coherency du plan invalide (formation actuelle DEJA incoherente) » et le worker `SubprocVecEnv`
du training mourait. C'était le seul chemin de placement du moteur sans contrôle de cohérence
(déploiement, move, charge, pile-in et consolidation valident tous).

Ce test verrouille l'invariant à la SOURCE : après `reset`, aucune escouade n'est en violation.
"""

from __future__ import annotations

import os
from typing import Iterator, List

import pytest

SCENARIO = "config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json"


@pytest.fixture
def board_x1() -> Iterator[None]:
    previous = os.environ.get("W40K_BOARD_PATH")
    os.environ["W40K_BOARD_PATH"] = "board/44x60x1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("W40K_BOARD_PATH", None)
        else:
            os.environ["W40K_BOARD_PATH"] = previous


def _engine(seed: int):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent",
        scenario_file=SCENARIO,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
    )
    eng.reset(seed=seed)
    return eng


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_every_squad_is_coherent_right_after_reset(board_x1, seed: int) -> None:
    from engine.phase_handlers.shared_utils import validate_squad_coherency

    eng = _engine(seed)
    gs = eng.game_state
    multi = [
        sid for sid in gs["squad_models"]
        if sid in gs["units_cache"] and len(gs["squad_models"][sid]) > 1
    ]
    assert multi, "aucune escouade multi-figurine : le test n'exercerait rien"

    incoherent: List[str] = [sid for sid in multi if not validate_squad_coherency(gs, sid)]
    assert not incoherent, (
        "escouades incohérentes dès le chargement (le move refusera de les déplacer) : "
        + ", ".join(
            f"{sid} → "
            + str({
                m: (gs["models_cache"][m]["col"], gs["models_cache"][m]["row"])
                for m in gs["squad_models"][sid] if m in gs["models_cache"]
            })
            for sid in incoherent
        )
    )
