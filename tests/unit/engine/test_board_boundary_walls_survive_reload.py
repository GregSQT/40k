"""Verrou : les demi-cases fantomes du bord bas survivent a un rechargement de scenario.

En offset odd-q, les colonnes IMPAIRES sont decalees d'une demi-ligne vers le bas : leur
case de derniere ligne deborde sous le plateau et n'existe pas. Le constructeur de
W40KEngine les ajoute donc a `game_state["wall_hexes"]` pour les rendre infranchissables.

Le defaut trouve (review du 2026-08-07, engine/w40k_core.py) : `_reload_scenario` REECRIVAIT
le set avec les seuls murs du scenario, ce qui les perdait. Ce n'est pas marginal —
`reset()` recharge le scenario des que le scheduler de deploiement rend un mode, et
`deployment_mode_schedule` est obligatoire dans tout profil de training : sur un run normal,
les murs de bord disparaissaient des le premier episode.

Consequences mesurables : `build_squad_move_cell_map`, `validate_move_plan` et la LoS lisent
tous `wall_hexes` — les escouades pouvaient etre deployees sur des cases inexistantes et s'y
deplacer, et les tirs les traversaient. Symetriquement `ai/analyzer.py` re-ajoute ces memes
cases pour auditer step.log : les deux cotes se contredisaient, ce qui est la preuve du bug.

La source unique est desormais `engine.hex_utils.phantom_bottom_hexes`.
"""

from __future__ import annotations

import os

from ai.unit_registry import UnitRegistry
from engine.hex_utils import is_phantom_bottom_hex, phantom_bottom_hexes
from engine.w40k_core import W40KEngine

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
TEMPLATE = os.path.join(
    PROJECT_ROOT,
    "config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json",
)


def _make_env() -> W40KEngine:
    return W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x5_new",
        controlled_agent="ArmageddonAgent",
        scenario_file=TEMPLATE,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,
    )


def _expected_phantoms(game_state: dict) -> frozenset[tuple[int, int]]:
    """Les demi-cases attendues, et la preuve que l'echantillon n'est pas vide (VERT VACANT)."""
    cols = int(game_state["board_cols"])
    rows = int(game_state["board_rows"])
    phantoms = phantom_bottom_hexes(cols, rows)
    assert phantoms, f"plateau {cols}x{rows} sans colonne impaire : ce test n'observerait rien"
    return phantoms


def test_phantom_bottom_hexes_are_walls_at_construction():
    """Point de depart : le constructeur les pose bien. Sans ca, la suite ne prouve rien."""
    env = _make_env()
    phantoms = _expected_phantoms(env.game_state)
    missing = phantoms - set(env.game_state["wall_hexes"])
    assert not missing, f"demi-cases absentes des l'init : {sorted(missing)[:5]}"


def test_phantom_bottom_hexes_survive_reload_scenario():
    """Appel DIRECT de `_reload_scenario` : le chemin exact ou le set etait ecrase."""
    env = _make_env()
    phantoms = _expected_phantoms(env.game_state)

    env._reload_scenario(TEMPLATE)

    missing = phantoms - set(env.game_state["wall_hexes"])
    assert not missing, (
        f"{len(missing)} demi-cases fantomes perdues par _reload_scenario "
        f"(ex. {sorted(missing)[:5]}) : les figurines peuvent s'y deplacer et les tirs "
        f"les traversent"
    )


def test_phantom_bottom_hexes_survive_a_reset_that_reloads():
    """Chemin de PRODUCTION : `reset()` qui declenche un rechargement.

    Le rechargement est FORCE par le desaccord `_scenario_loaded_for_controlled_player`
    (w40k_core.py, premiere condition de `should_reload_scenario`) plutot que laisse au
    scheduler de deploiement : un test doit construire la situation qu'il observe, pas
    esperer qu'une rampe de training la produise.
    """
    env = _make_env()
    env.reset()
    phantoms = _expected_phantoms(env.game_state)

    env._scenario_loaded_for_controlled_player = -1  # aucun joueur : force le rechargement
    env.reset()

    assert env._scenario_loaded_for_controlled_player != -1, (
        "le rechargement n'a pas eu lieu : ce test ne verifierait rien"
    )
    missing = phantoms - set(env.game_state["wall_hexes"])
    assert not missing, f"demi-cases perdues par reset() : {sorted(missing)[:5]}"


def test_is_phantom_bottom_hex_matches_the_set():
    """Le predicat O(1) et l'ensemble doivent decrire le MEME fait.

    Les deux existent parce que les chemins chauds ne peuvent pas allouer un set par appel
    (services/endless_duty_runtime.py). S'ils divergeaient, la source unique ne le serait plus.
    """
    cols, rows = 9, 7
    from_set = phantom_bottom_hexes(cols, rows)
    from_predicate = {
        (col, row)
        for col in range(cols)
        for row in range(rows)
        if is_phantom_bottom_hex(col, row, rows)
    }
    assert from_set == from_predicate == {(1, 6), (3, 6), (5, 6), (7, 6)}
