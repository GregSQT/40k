"""V11 §0.11 — La collision intra-plan doit tenir compte du NIVEAU (étage).

Bug corrigé ici : `explain_move_plan_rejection` agrégeait les cellules occupées par le plan
dans un `Set[Tuple[int, int]]` clé sur `(col, row)` SEULEMENT, alors que le contrôle des
cellules interdites juste au-dessus, lui, est per-niveau (`blocked_by_level[_target_level]`).
Deux figurines d'une même escouade superposées à des étages différents — configuration
LÉGALE, tout le prédicat d'occupation du moteur étant per-niveau (cf.
`build_move_blocked_cells_by_level`) — étaient donc rejetées comme « collision intra-plan ».

Conséquence en production : `build_rigid_plan` translate le bloc rigidement (même delta cube
pour toutes les figurines), donc deux figurines partagent `(col, row)` à l'arrivée si et
seulement si elles la partageaient au départ. Dès qu'une escouade se retrouvait superposée
sur deux étages, TOUS ses déplacements ultérieurs échouaient — et comme l'érosion du masque
(`erode_move_pool_by_squad_block`) ne teste PAS la collision (elle la suppose invariante par
translation, ce qui est vrai), le masque continuait d'offrir ces destinations. D'où
`ValueError: execute_squad_move a échoué : … incohérence masque/exécution`, qui a tué le
training ArmageddonAgent à l'épisode ~250 le 2026-07-20.

Pourquoi `test_move_mask_is_executable.py` ne l'a PAS attrapé alors qu'il mesure CET invariant
sur CE scénario : il ne vérifie l'invariant que sur les états atteints par exploration
aléatoire (seeds 0/1/2, 400 steps). La superposition inter-étages n'y survient jamais. Test
vert, cas jamais exercé — motif §0.4. Le test ci-dessous CONSTRUIT la configuration au lieu
de l'espérer.
"""

import pytest

from engine.phase_handlers.shared_utils import explain_move_plan_rejection

SCENARIO = "config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json"

# Contraintes neutralisées : on isole le SEUL prédicat de collision intra-plan.
_ISOLATE_COLLISION = {
    "budget_per_model": None,
    "require_coherency": False,
    "allow_collisions": True,
    "forbid_enemy_er": False,
}


def _deployed_engine():
    """Vrai moteur, déploiement joué — pas un `game_state` fabriqué."""
    import numpy as np

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
    eng.reset(seed=0)
    rng = np.random.default_rng(0)
    for _ in range(4000):
        if eng.game_state.get("phase") not in ("deploy", "deployment"):
            break
        mask = eng.get_action_mask()
        if not mask.any():
            break
        eng.step(int(rng.choice(np.flatnonzero(mask))))
    return eng


def _squad_with_two_deployed_models(game_state):
    models_cache = game_state["models_cache"]
    for squad_id, mids in game_state["squad_models"].items():
        alive = [
            m for m in mids
            if m in models_cache and int(models_cache[m]["col"]) >= 0
        ]
        if len(alive) >= 2:
            return str(squad_id), alive[:2]
    pytest.fail("aucune escouade déployée à 2+ figurines : le test n'a rien exercé")


def test_same_cell_on_different_levels_is_not_an_intra_plan_collision():
    """Deux figurines superposées à des ÉTAGES différents ne se heurtent pas."""
    eng = _deployed_engine()
    game_state = eng.game_state
    _squad, (mid_a, mid_b) = _squad_with_two_deployed_models(game_state)
    anchor = game_state["models_cache"][mid_a]
    col, row = int(anchor["col"]), int(anchor["row"])

    # 4e élément = niveau VISÉ (cf. `_target_level`).
    plan = [(mid_a, col, row, 0), (mid_b, col, row, 1)]
    rejection = explain_move_plan_rejection(plan, game_state, _ISOLATE_COLLISION)

    # La cellule peut être refusée pour une AUTRE raison (pas de plancher à l'étage 1, mur…) :
    # on n'exige donc pas l'acceptation, seulement que ce ne soit PAS une collision.
    assert rejection is None or "collision intra-plan" not in rejection, (
        f"deux figurines à des niveaux différents sur ({col},{row}) sont comptées comme une "
        f"collision alors que le niveau fait partie de l'identité d'une position : {rejection}"
    )


def test_same_cell_on_same_level_is_still_an_intra_plan_collision():
    """Non-régression : une VRAIE superposition au même étage reste refusée."""
    eng = _deployed_engine()
    game_state = eng.game_state
    _squad, (mid_a, mid_b) = _squad_with_two_deployed_models(game_state)
    anchor = game_state["models_cache"][mid_a]
    col, row = int(anchor["col"]), int(anchor["row"])

    plan = [(mid_a, col, row, 0), (mid_b, col, row, 0)]
    rejection = explain_move_plan_rejection(plan, game_state, _ISOLATE_COLLISION)

    assert rejection is not None and "collision intra-plan" in rejection, (
        f"deux figurines sur la MÊME cellule au MÊME niveau doivent être refusées, "
        f"rejet obtenu : {rejection!r}"
    )
