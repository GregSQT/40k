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

import os
import random

import pytest

from engine.phase_handlers.shared_utils import (
    MOVE_CELL_MAP_CACHE_KEY,
    build_rigid_plan,
    get_squad_move_budget,
    infer_squad_move_type,
    validate_move_plan,
)

_BANK = "config/agents/ArmageddonAgent/scenarios/training/"
#: Les DEUX terrains de la banque. L'objet de ce test — cellules atteignables, murs, érosion du
#: bloc — est entièrement GÉOMÉTRIQUE : un second terrain n'y est pas une répétition mais un
#: second jeu d'obstacles. Ils sont appariés aux graines plutôt que croisés avec elles (cf. la
#: paramétrisation du test) : le croisement doublerait un test déjà en 2 plateaux × 3 graines
#: × 400 steps, pour une redondance que la variété des trajectoires apporte déjà.
SCENARIO_MC1 = _BANK + "scenario_training_armageddon1.json"
SCENARIO_MC2 = _BANK + "scenario_training_armageddon2.json"
MAX_STEPS = 400


def _engine(seed, scenario):
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
        training_n_envs=1,  # UN environnement joue en serie (engine/episode_schedule.py)
    )
    eng.reset(seed=seed)
    return eng


def _live_map_squad(engine):
    """Escouade dont la carte de cellules est CONSTRUITE À CE STEP, ou None si aucune.

    `game_state[MOVE_CELL_MAP_CACHE_KEY]` n'est PAS l'état du masque courant : c'est un dépôt
    par escouade, purgé seulement à la fin d'une activation (`clear_squad_move_cell_map`).
    Depuis le choix d'activation (V11 §0.48 `L2`), la branche de choix y stocke la carte de la
    TÊTE du pool à chaque step de choix ; si l'agent désigne une AUTRE escouade, celle-ci bouge
    et la carte de la tête reste derrière, exacte au moment où elle a été construite et périmée
    ensuite. Mesuré (seed 1, board x5) : step 156 carte de 101 stockée à un step de choix, 104
    activée et déplacée sur le bloc de 101, step 160 la carte de 101 est encore là.

    Le moteur ne lit JAMAIS cette carte-là : le décodeur reconstruit celle de l'escouade traitée
    (le fingerprint de `build_squad_move_cell_map` voit le déplacement des autres), et le canal de
    coût de l'observation ne relit la carte que sous les mêmes gardes que celles reproduites ici.
    Parcourir tout le dépôt reviendrait donc à valider un masque que personne n'a produit.

    Gardes — les MÊMES que celles du décodeur et de l'observation, dans le même ordre :
      - décision d'agent en attente : le masque n'expose que les `CHOICE_i`, aucune carte n'est
        construite (c'est exactement l'état du step 160 ci-dessus) ;
      - escouade en réserves (20.01) : son activation de move est un ingress (20.04), pas un
        déplacement — aucune carte non plus.
    """
    from engine.agent_decision import read_pending_agent_decision
    from engine.phase_handlers.shared_utils import unit_is_in_strategic_reserves

    game_state = engine.game_state
    if read_pending_agent_decision(game_state) is not None:
        return None
    eligible = engine.action_decoder._get_eligible_units_for_current_phase(game_state)
    if not eligible:
        return None
    squad_id = str(eligible[0]["id"])
    if unit_is_in_strategic_reserves(game_state, squad_id):
        return None
    return squad_id


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


@pytest.fixture(params=["board/44x60x5", "board/44x60x1"])
def board(request):
    """Les DEUX résolutions du plateau — le x1 n'était pas couvert.

    ⚠️ Ce test n'attrape PAS la divergence de socle du x1 (socle non-rond → chemin multi-hex du
    pool, qui évalue l'engagement ennemi depuis les socles, quand `validate_move_plan` le lit dans
    le set dilaté `enemy_adjacent_hexes_player_N`) : vérifié par mutation, il reste vert avec le
    défaut. Les trajectoires sont aléatoires et n'atteignent pas la configuration de façon fiable
    — motif §0.11. C'est `test_socle_normalized_at_x1.py` qui la verrouille, en la construisant.
    Le paramétrage ci-dessous vaut pour le reste de l'invariant, pas pour ce cas précis.
    """
    previous = os.environ.get("W40K_BOARD_PATH")
    os.environ["W40K_BOARD_PATH"] = request.param
    try:
        yield request.param
    finally:
        if previous is None:
            os.environ.pop("W40K_BOARD_PATH", None)
        else:
            os.environ["W40K_BOARD_PATH"] = previous


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_every_masked_move_cell_is_executable(seed, board):
    eng = _engine(seed)
    rng = random.Random(seed)
    failures = []
    cells_checked = 0
    move_steps = 0

    for _ in range(MAX_STEPS):
        mask = eng.get_action_mask()
        gs = eng.game_state

        squad_id = _live_map_squad(eng) if gs.get("phase") == "move" else None
        if squad_id is not None:
            stored = (gs.get(MOVE_CELL_MAP_CACHE_KEY) or {}).get(squad_id)
            cell_map = stored.get("map") if isinstance(stored, dict) else stored
            if isinstance(cell_map, dict):
                move_steps += 1
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
        f"[{board}] {len(failures)}/{cells_checked} cellules offertes par le masque sont REFUSÉES par "
        f"validate_move_plan (incohérence masque/exécution, V11 T6-g/T6-h). "
        f"5 premières : {failures[:5]}"
    )
