"""V11 §9.2.5 — distance parcourue par figurine (géodésique) + état de mise en place.

Deux données ajoutées, chacune avec DEUX consommateurs — c'est ce qui justifie qu'elles vivent
dans le moteur et pas dans l'observation :

1. `moved_distance_by_model` : distance de CHEMIN parcourue ce tour, accumulée par
   `commit_move`. Sert (a) la clause 3 de [HEAVY] 24.16 (« no model … has moved more than 3"
   this turn »), rendue EXACTE par cette donnée, et (b) l'observation (savoir combien de budget
   on a consommé conditionne advance / charge / move-after-shooting).
   ⚠️ Le point non trivial : la distance est GÉODÉSIQUE. Contourner un mur coûte plus cher que
   l'écart départ↔arrivée — mesurer à vol d'oiseau sous-estimerait le trajet et rendrait [HEAVY]
   LAXISTE (bonus accordé à une unité qui a réellement parcouru plus de 3").

2. `deployed_on_turn` : déjà posé par le moteur (clause 2 de 24.16) ; l'observation en dérive
   un one-hot 3 états + le bit « posée CE tour ».
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.observation_entities import unit_bin_index, unit_cont_index
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

CONT_MOVED_MAX = unit_cont_index("moved_max")
CONT_MOVED_SUM = unit_cont_index("moved_sum")
BIN_NOT_ON_BOARD = unit_bin_index("deploy_not_on_board")
BIN_PRE_BATTLE = unit_bin_index("deploy_pre_battle")
BIN_ARRIVED_IN_BATTLE = unit_bin_index("deploy_in_battle")
BIN_SET_UP_THIS_TURN = unit_bin_index("deployed_this_turn")


def _unit_cfg(uid: int, player: int, positions: List[Tuple[int, int]], *, move: int = 6) -> Dict[str, Any]:
    specs = [{"col": c, "row": r, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10} for c, r in positions]
    weapon = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
              "WEAPON_RULES": [], "display_name": "Gun"}
    melee = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
             "WEAPON_RULES": [], "display_name": "Blade"}
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(specs), "HP_MAX": 1, "MOVE": move, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [weapon], "CC_WEAPONS": [melee],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _config(units: List[Dict[str, Any]], walls: List[Tuple[int, int]]) -> Dict[str, Any]:
    obs_params = {
        "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET,
    }
    return {
        "board": {"default": {"cols": 60, "rows": 40, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [list(w) for w in walls], "inches_to_subhex": 1}},
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            "unit_model_cohesion_range": 2, "unit_global_cohesion_range": 9,
            "squad_min_neighbors": 1, "cohesion_distance_mode": "euclidean",
        },
        "charge": {"charge_max_distance": 12},
        "move": {"can_move_through_enemy_engagement_zone": True,
                 "can_move_through_enemy_model": False,
                 "can_move_through_friendly_model": True},
        "pve_mode": False,
        "scenario_objectives": [],
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": units,
    }


def _make_engine(units: List[Dict[str, Any]], walls: List[Tuple[int, int]] | None = None) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(_config(units, walls or [])))
    eng.reset()
    return eng


# ------------------------------------------------------- accumulation moteur


def _straight(a: Tuple[int, int], b: Tuple[int, int]) -> float:
    """Oracle INDÉPENDANT : distance de chemin sans obstacle, en pas d'hexagone.

    Cette doublure tourne à `inches_to_subhex == 1`, où la géométrie du jeu est HEXAGONALE
    (`spatial_relations.geometry_is_hex` — une figurine tient dans une case, donc aucune mesure
    continue n'y a de sens). Le moteur y mesure le move en pas d'hexagone, métrique gym ou non :
    l'oracle est donc la distance cube, pas la distance euclidienne centre-à-centre.

    ⚠️ L'oracle ÉTAIT euclidien (`_hex_center` + `math.dist`), ce qui décrivait la métrique
    `distance_metric["move"]` d'un board x5. À x1 les deux ne coïncident que sur un déplacement
    en colonnes de parité constante — deux des tests de ce fichier passaient par cette
    coïncidence, et deux autres échouaient sur le zig-zag de parité (3 colonnes = 3 pas hex,
    mais 3,055 subhex euclidiens).
    """
    from engine.combat_utils import calculate_hex_distance

    return float(calculate_hex_distance(a[0], a[1], b[0], b[1]))


def test_commit_move_records_straight_line_distance_without_obstacle():
    """Sans obstacle, la distance de chemin égale la distance à vol d'oiseau."""
    from engine.phase_handlers.shared_utils import commit_move

    eng = _make_engine([_unit_cfg(1, 1, [(10, 10)]), _unit_cfg(2, 2, [(50, 30)])])
    commit_move([("1#0", 14, 10, 0)], eng.game_state, "normal")
    assert eng.game_state["moved_distance_by_model"]["1#0"] == pytest.approx(
        _straight((10, 10), (14, 10)), rel=1e-4
    )


def test_commit_move_records_hex_path_distance_in_gym_metric():
    """Clé gym (`move_gym`) : la distance est le BFS géodésique en pas — entier.

    À x1 la métrique PvP est hex elle aussi (bascule de résolution) : ce test ne distingue donc
    plus les deux clés, il vérifie que le chemin gym passe bien par le même compteur.
    """
    from engine.phase_handlers.shared_utils import commit_move

    eng = _make_engine([_unit_cfg(1, 1, [(10, 10)]), _unit_cfg(2, 2, [(50, 30)])])
    eng.game_state["gym_training_mode"] = True
    commit_move([("1#0", 14, 10, 0)], eng.game_state, "normal")
    assert eng.game_state["moved_distance_by_model"]["1#0"] == pytest.approx(4.0)


def test_commit_move_records_the_PATH_not_the_crow_flight():
    """Un mur sur le trajet : le chemin réel est plus long que l'écart départ↔arrivée.

    C'est LE point qui rend la clause 3 de [HEAVY] juste : mesurer à vol d'oiseau accorderait
    le bonus à une unité qui a effectivement parcouru plus de 3".
    """
    from engine.phase_handlers.shared_utils import commit_move

    # Mur vertical entre (10,10) et (12,10), assez long pour imposer un large detour.
    walls = [(11, r) for r in range(0, 25)]
    eng = _make_engine([_unit_cfg(1, 1, [(10, 10)], move=60), _unit_cfg(2, 2, [(50, 30)])], walls)
    commit_move([("1#0", 12, 10, 0)], eng.game_state, "normal")

    travelled = eng.game_state["moved_distance_by_model"]["1#0"]
    crow = _straight((10, 10), (12, 10))
    assert travelled > crow * 1.5, (
        f"distance mesuree {travelled} ~ vol d'oiseau {crow} : le contournement du mur "
        f"n'est pas compte -> [HEAVY] 24.16 deviendrait laxiste"
    )


def test_distances_accumulate_over_several_moves_in_a_turn():
    """Une escouade peut bouger plusieurs fois : les distances s'ADDITIONNENT."""
    from engine.phase_handlers.shared_utils import commit_move

    eng = _make_engine([_unit_cfg(1, 1, [(10, 10)], move=30), _unit_cfg(2, 2, [(50, 30)])])
    commit_move([("1#0", 13, 10, 0)], eng.game_state, "normal")
    commit_move([("1#0", 16, 10, 0)], eng.game_state, "normal")
    expected = _straight((10, 10), (13, 10)) + _straight((13, 10), (16, 10))
    assert eng.game_state["moved_distance_by_model"]["1#0"] == pytest.approx(expected, rel=1e-4)


def test_distances_reset_at_the_start_of_a_player_turn():
    """Même cycle de vie que `units_moved` : « ce tour » se remet à zéro au tour suivant."""
    from engine.phase_handlers.shared_utils import commit_move
    from engine.phase_handlers.command_handlers import command_phase_start

    eng = _make_engine([_unit_cfg(1, 1, [(10, 10)]), _unit_cfg(2, 2, [(50, 30)])])
    commit_move([("1#0", 13, 10, 0)], eng.game_state, "normal")
    assert eng.game_state["moved_distance_by_model"]
    command_phase_start(eng.game_state)
    assert eng.game_state["moved_distance_by_model"] == {}
    assert eng.game_state["units_moved"] == set()


def test_fight_phase_moves_are_not_counted_and_that_is_deliberate():
    """pile-in / consolidation relèvent d'une AUTRE géométrie (euclidienne any-angle).

    Les compter avec la métrique hex donnerait un chiffre faux ; à vol d'oiseau, un chiffre
    sous-estimé donc LAXISTE pour [HEAVY]. L'ordre des phases (PDF 07.02 : Mouvement, Tir,
    Charge, Combat) garantit qu'aucun de ces moves ne précède le tir dans le même tour.
    """
    from engine.phase_handlers.shared_utils import commit_move

    eng = _make_engine([_unit_cfg(1, 1, [(10, 10)]), _unit_cfg(2, 2, [(50, 30)])])
    commit_move([("1#0", 12, 10, 0)], eng.game_state, "pile_in")
    assert eng.game_state["moved_distance_by_model"] == {}


# ------------------------------------------------------- observation


def _obs(eng: W40KEngine) -> Dict[str, Any]:
    return eng.obs_builder.build_squad_observation(eng.game_state, "1")


def test_observation_exposes_max_and_sum_of_travelled_distance():
    """Le max porte la clause de règle, la somme dit si toute l'escouade a bougé."""
    from engine.phase_handlers.shared_utils import commit_move

    eng = _make_engine([
        _unit_cfg(1, 1, [(10, 10), (10, 12)], move=30),
        _unit_cfg(2, 2, [(50, 30)]),
    ])
    commit_move([("1#0", 14, 10, 0)], eng.game_state, "normal")
    commit_move([("1#1", 11, 12, 0)], eng.game_state, "normal")
    d0 = _straight((10, 10), (14, 10))
    d1 = _straight((10, 12), (11, 12))
    assert d0 > d1
    cont = _obs(eng)["allies_cont"][0]
    assert cont[CONT_MOVED_MAX] == pytest.approx(d0, rel=1e-4)
    assert cont[CONT_MOVED_SUM] == pytest.approx(d0 + d1, rel=1e-4)


def test_observation_deploy_state_is_pre_battle_by_default():
    """Unité posée avant la bataille : one-hot « pré-bataille », pas « posée ce tour »."""
    eng = _make_engine([_unit_cfg(1, 1, [(10, 10)]), _unit_cfg(2, 2, [(50, 30)])])
    binv = _obs(eng)["allies_bin"][0]
    assert binv[BIN_NOT_ON_BOARD] == pytest.approx(0.0)
    assert binv[BIN_PRE_BATTLE] == pytest.approx(1.0)
    assert binv[BIN_ARRIVED_IN_BATTLE] == pytest.approx(0.0)
    assert binv[BIN_SET_UP_THIS_TURN] == pytest.approx(0.0)


def test_observation_deploy_state_marks_an_arrival_this_turn():
    """Arrivée de réserve au tour courant : « en cours de bataille » ET « posée ce tour »."""
    from engine.game_utils import get_unit_by_id

    eng = _make_engine([_unit_cfg(1, 1, [(10, 10)]), _unit_cfg(2, 2, [(50, 30)])])
    eng.game_state["turn"] = 3
    unit = get_unit_by_id(eng.game_state, "1")
    assert unit is not None, "unite 1 absente du game_state"
    unit["deployed_on_turn"] = 3
    binv = _obs(eng)["allies_bin"][0]
    assert binv[BIN_PRE_BATTLE] == pytest.approx(0.0)
    assert binv[BIN_ARRIVED_IN_BATTLE] == pytest.approx(1.0)
    assert binv[BIN_SET_UP_THIS_TURN] == pytest.approx(1.0)


def test_observation_deploy_state_distinguishes_a_previous_turn_arrival():
    """Discrimination : arrivée au tour PRÉCÉDENT -> plus « posée ce tour » (24.16 clause 2)."""
    from engine.game_utils import get_unit_by_id

    eng = _make_engine([_unit_cfg(1, 1, [(10, 10)]), _unit_cfg(2, 2, [(50, 30)])])
    eng.game_state["turn"] = 3
    unit = get_unit_by_id(eng.game_state, "1")
    assert unit is not None, "unite 1 absente du game_state"
    unit["deployed_on_turn"] = 2
    binv = _obs(eng)["allies_bin"][0]
    assert binv[BIN_ARRIVED_IN_BATTLE] == pytest.approx(1.0)
    assert binv[BIN_SET_UP_THIS_TURN] == pytest.approx(0.0)
