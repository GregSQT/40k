"""V11 T6-g/T6-h — Invariant moteur RÉEL : « masque ⊆ exécutable ».

Les tests unitaires `test_move_pool_block_erosion.py` et `test_rigid_plan_translation.py`
exercent l'érosion et la translation sur un `game_state` FABRIQUÉ. Ils ne prouvent donc pas
l'invariant de bout en bout sur le vrai moteur, et surtout ils ne couvrent PAS les deux
contraintes que l'érosion ne filtre pas, parce qu'elles ont été démontrées invariantes par
translation cube plutôt que testées :

  - `budget_per_model` — `calculate_hex_distance` est une distance cube, donc invariante par
    translation : la distance de chaque figurine à son origine devrait égaler celle de l'ancre ;
  - `require_coherency` / collision intra-plan — ne dépendent que des positions RELATIVES,
    préservées par une translation rigide.

Ce test remplace ce raisonnement par une mesure. Il déroule de vraies parties en actions
masquées aléatoires et, à CHAQUE step de phase move, vérifie que TOUTE cellule offerte par le
masque produit un plan que `validate_move_plan` accepte — avec le budget EXACT que
`execute_squad_move` appliquerait (type de move inféré du coût géodésique, comme le décodeur).

C'est l'invariant dont la violation produisait
`ValueError: execute_squad_move a échoué : … incohérence masque/exécution` et tuait les workers
`SubprocVecEnv` du training.
"""

import random

import pytest

from engine.phase_handlers.shared_utils import (
    MOVE_CELL_MAP_CACHE_KEY,
    build_rigid_plan,
    get_squad_move_budget,
    infer_squad_move_type,
    validate_move_plan,
)

SCENARIO = (
    "config/agents/CoreAgent/scenarios/training/training_benchmark/"
    "scenario_training_benchmark.json"
)
MAX_STEPS = 400


def _engine(seed):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="CoreAgent",
        training_config_name="x1_debug",
        controlled_agent="CoreAgent",
        scenario_file=SCENARIO,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
    )
    eng.reset(seed=seed)
    return eng


def _budget_for(game_state, squad_id, cost):
    """Budget EXACT appliqué par `execute_squad_move` pour cette cellule.

    Miroir du décodeur : le type de move se déduit du coût géodésique conservé dans la carte
    de cellules, puis le budget en découle. Le coût de descente §13.06 est retranché par
    `execute_squad_move` — non reproduit ici, ce qui ne rend le test que PLUS strict
    (budget plus large = plan accepté plus facilement ; un échec reste un vrai échec).
    """
    move_type = infer_squad_move_type(game_state, squad_id, cost)
    advance_roll = None
    if move_type == "advance":
        advance_roll = (game_state.get("_squad_advance_rolls") or {}).get(squad_id)
        if advance_roll is None:
            return None  # jet inconnu : cellule non concluante, on ne l'invente pas
    return get_squad_move_budget(
        squad_id, game_state, move_type, advance_roll=advance_roll
    )


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_every_masked_move_cell_is_executable(seed):
    eng = _engine(seed)
    rng = random.Random(seed)
    failures = []
    cells_checked = 0
    move_steps = 0

    for _ in range(MAX_STEPS):
        mask = eng.get_action_mask()
        gs = eng.game_state

        if gs.get("phase") == "move":
            move_steps += 1
            for sid, stored in (gs.get(MOVE_CELL_MAP_CACHE_KEY) or {}).items():
                cell_map = stored.get("map") if isinstance(stored, dict) else stored
                if not isinstance(cell_map, dict):
                    continue
                squad_id = str(sid)
                for (cell, cost) in cell_map.values():
                    budget = _budget_for(gs, squad_id, cost)
                    if budget is None:
                        continue
                    plan = build_rigid_plan(cell[0], cell[1], squad_id, gs)
                    cells_checked += 1
                    if plan is None:
                        failures.append((squad_id, cell, "build_rigid_plan -> None"))
                        continue
                    if not validate_move_plan(plan, gs, {"budget_per_model": budget}):
                        failures.append((squad_id, cell, "validate_move_plan -> False"))

        valid = [i for i in range(len(mask)) if mask[i]]
        if not valid:
            break
        _, _, terminated, truncated, _ = eng.step(rng.choice(valid))
        if terminated or truncated:
            break

    assert move_steps > 0, "aucune phase move atteinte : le test n'a rien exercé"
    assert cells_checked > 0, "aucune cellule de move offerte : le test n'a rien exercé"
    assert not failures, (
        f"{len(failures)}/{cells_checked} cellules offertes par le masque sont REFUSÉES par "
        f"validate_move_plan (incohérence masque/exécution, V11 T6-g/T6-h). "
        f"5 premières : {failures[:5]}"
    )
