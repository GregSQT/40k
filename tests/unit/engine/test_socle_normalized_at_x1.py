"""Socle normalisé à `inches_to_subhex == 1` — invariant « pool de move ⊆ exécutable ».

À x1 une figurine tient dans UNE case : le socle est normalisé en `round`/1
(`game_state._scale_socle`). Sans cette normalisation, un socle non-rond garde une forme qui
n'a plus de sens géométrique à cette résolution, et l'unité bascule sur le chemin MULTI-HEX de
`movement_build_valid_destinations_pool` — lequel évalue l'engagement ennemi depuis les SOCLES,
alors que `validate_move_plan` le lit dans le set dilaté `enemy_adjacent_hexes_player_N`.

Les deux définitions ne coïncident pas : le masque offre des destinations que l'exécution refuse,
et le training meurt sur
`ValueError: execute_squad_move a échoué : … incohérence masque/exécution`.

`test_move_mask_is_executable.py` ne l'attrape pas : il déroule des parties aléatoires et
n'atteint pas la configuration (socle non-rond + ennemi à portée d'EZ) de façon fiable. D'où ce
test, qui la construit.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterator

import pytest

# Socles non-ronds présents dans les rosters d'entraînement (BASE_SIZE = paire).
NON_ROUND_UNITS = ("WarTrakk", "Carnifex", "LandSpeederOnslaughtGatlingCannon")

#: Faction d'Armée DÉCLARÉE du joueur 1 pour chacun de ces movers. 08.04 l'exige à chaque phase de
#: commandement et refuse de la déduire des unités présentes, or le mover CHANGE de faction à
#: chaque paramètre : une déclaration fixe serait fausse pour deux cas sur trois, et la garde
#: anti-coquille d'`army_faction` le dirait. Recopiée à la main depuis les datasheets, jamais lue
#: au registre : la lire ferait suivre la déclaration en silence le jour où une datasheet change
#: de faction, c'est-à-dire exactement la déduction que le moteur refuse.
_MOVER_FACTION = {
    "WarTrakk": "ORKS",
    "Carnifex": "TYRANIDS",
    "LandSpeederOnslaughtGatlingCannon": "ADEPTUS ASTARTES",
}


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


@pytest.fixture
def board_x5() -> Iterator[None]:
    previous = os.environ.get("W40K_BOARD_PATH")
    os.environ["W40K_BOARD_PATH"] = "board/44x60x5"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("W40K_BOARD_PATH", None)
        else:
            os.environ["W40K_BOARD_PATH"] = previous


def _engine(tmp_path, mover_type: str, mover: tuple, enemy: tuple):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    scenario: Dict[str, Any] = {
        "primary_objectives": ["objectives_control"],
        "board_ref": "44x60x5",
        "terrain_ref": "terrain-mc1.json",
        # Joueur 1 = le mover (faction variable, cf. `_MOVER_FACTION`), joueur 2 = Intercessor.
        "army_faction": {"1": _MOVER_FACTION[mover_type], "2": "ADEPTUS ASTARTES"},
        "units": [
            {"id": "1", "player": 1, "unit_type": mover_type, "col": mover[0], "row": mover[1]},
            {"id": "2", "player": 2, "unit_type": "Intercessor", "col": enemy[0], "row": enemy[1]},
        ],
    }
    path = tmp_path / "scenario_socle.json"
    path.write_text(json.dumps(scenario), encoding="utf-8")
    engine = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent", scenario_file=str(path),
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    engine.reset(seed=0)
    return engine


@pytest.mark.parametrize("mover_type", NON_ROUND_UNITS)
def test_socle_is_normalized_to_round_at_x1(board_x1, tmp_path, mover_type) -> None:
    engine = _engine(tmp_path, mover_type, (100, 150), (118, 150))
    mover = next(u for u in engine.game_state["units"] if str(u["id"]) == "1")
    assert mover["BASE_SHAPE"] == "round"
    assert mover["BASE_SIZE"] == 1
    # Une figurine = une case : c'est la propriété que la normalisation protège.
    entry = engine.game_state["units_cache"]["1"]
    assert len(entry["occupied_hexes"]) == 1


def test_socle_keeps_its_pair_at_x5(board_x5, tmp_path) -> None:
    """Contrôle de non-régression : à x5 la forme et la paire de la datasheet sont conservées."""
    from ai.unit_registry import UnitRegistry

    assert isinstance(UnitRegistry().get_unit_data("WarTrakk")["BASE_SIZE"], list)
    engine = _engine(tmp_path, "WarTrakk", (100, 150), (140, 150))
    mover = next(u for u in engine.game_state["units"] if str(u["id"]) == "1")
    assert mover["BASE_SHAPE"] == "oval"
    # 41 et 27 dixièmes de pouce × 5 / 10, arrondi bancaire : 20.5 -> 20, 13.5 -> 14.
    assert isinstance(mover["BASE_SIZE"], list) and mover["BASE_SIZE"] == [20, 14]


@pytest.mark.parametrize("mover_type", NON_ROUND_UNITS)
def test_no_pool_destination_lands_in_enemy_engagement_zone(board_x1, tmp_path, mover_type) -> None:
    """Invariant : AUCUNE destination du pool ne doit être refusée par `validate_move_plan`.

    L'ennemi est posé à portée de mouvement pour que sa zone d'engagement traverse le pool —
    sinon le test ne prouve rien.
    """
    from engine.phase_handlers.movement_handlers import movement_build_valid_destinations_pool
    from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes

    engine = _engine(tmp_path, mover_type, (100, 150), (118, 150))
    state = engine.game_state
    enemy_zone = build_enemy_adjacent_hexes(state, 1)
    assert enemy_zone, "zone d'engagement ennemie vide : le test n'exercerait rien"

    pool = movement_build_valid_destinations_pool(state, "1")
    assert pool, "pool de destinations vide : le test n'exercerait rien"

    overlap = sorted(set(pool) & set(enemy_zone))
    assert not overlap, (
        f"{len(overlap)}/{len(pool)} destinations offertes par le pool sont dans la zone "
        f"d'engagement ennemie, que `validate_move_plan` refuse "
        f"(incohérence masque/exécution). 5 premières : {overlap[:5]}"
    )
