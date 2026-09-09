"""`i_play_first` dit le SIÈGE de l'observateur, et jamais qui a la main.

Le drapeau vaut 1 pour le joueur qui OUVRE le battle round — P1, `w40k_core` posant
``current_player: 1`` à l'init et ``_fight_end_progression_v10`` n'incrémentant ``turn`` qu'après
le tour de P2. Il répond à « l'adversaire rejoue-t-il APRÈS moi dans ce round ? », question dont
dépend la valeur du round 5 : le primaire se marque à la command phase pour le premier joueur et
à la fight phase pour le second (``round5_second_player_phase``).

Ce que ces tests verrouillent, et qu'aucune assertion de valeur seule n'attraperait : la
CONFUSION avec ``is_my_turn``, le drapeau voisin. Les deux valent 1 pour l'observateur P1 pendant
son propre tour ; ils ne se séparent qu'au tour adverse et pour l'observateur P2. Un câblage sur
``current_player`` au lieu de l'observateur — l'erreur naturelle, les deux entiers étant
interchangeables la moitié du temps — sort donc une observation fausse sans qu'un test de valeur
sur le seul tour de P1 ne bouge.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.observation_entities import global_bin_index
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

#: Escouade observée -> siège attendu. L'unité 1 appartient à P1, l'unité 2 à P2.
OBSERVER_TO_SEAT = {"1": 1.0, "2": 0.0}


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "code": "test_weapon", "display_name": "Test Bolter",
    }


def _unit_cfg(uid: int, player: int, positions: List[Tuple[int, int]]) -> Dict[str, Any]:
    specs = [{"col": c, "row": r, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10} for c, r in positions]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(specs), "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [_weapon_cfg()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _config() -> Dict[str, Any]:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    return {
        "board": {
            "default": {
                "cols": 120, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
                "wall_hexes": [], "inches_to_subhex": 1,
            }
        },
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            "unit_model_cohesion_range": 2, "unit_global_cohesion_range": 9,
            "squad_min_neighbors": 1, "cohesion_distance_mode": "euclidean",
        },
        "charge": {"charge_max_distance": 12},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "scenario_objectives": [],
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [
            _unit_cfg(1, 1, [(30, 20), (32, 20)]),
            _unit_cfg(2, 2, [(80, 20)]),
        ],
    }


@pytest.fixture
def engine() -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(_config()))
    eng.reset()
    return eng


def _flags(engine: W40KEngine, squad_id: str) -> Dict[str, float]:
    """Les deux drapeaux de tour, lus SUR-LE-CHAMP.

    L'observation vit dans un buffer scratch réutilisé d'un appel à l'autre : garder le tableau
    et le relire après une seconde construction comparerait une observation avec elle-même.
    """
    g_bin = engine.obs_builder.build_squad_observation(engine.game_state, squad_id)["global_bin"]
    return {
        "i_play_first": float(g_bin[global_bin_index("i_play_first")]),
        "is_my_turn": float(g_bin[global_bin_index("is_my_turn")]),
    }


@pytest.mark.parametrize("observer,expected", sorted(OBSERVER_TO_SEAT.items()))
def test_seat_bit_names_the_observer_not_the_active_player(
    engine: W40KEngine, observer: str, expected: float
) -> None:
    """obs_seat_value : 1 pour l'escouade de P1, 0 pour celle de P2, au tour de P1."""
    assert engine.game_state["current_player"] == 1, "fixture : le round s'ouvre sur P1"

    assert _flags(engine, observer)["i_play_first"] == expected


@pytest.mark.parametrize("observer,expected", sorted(OBSERVER_TO_SEAT.items()))
def test_seat_bit_holds_on_both_player_turns_of_the_same_round(
    engine: W40KEngine, observer: str, expected: float
) -> None:
    """obs_seat_stable : le siège ne change pas quand la main passe à l'adversaire.

    C'est le cas d'usage : au round 5, l'observateur doit savoir s'il a déjà marqué son primaire
    (premier joueur) ou s'il le marquera après sa phase de combat (second). Le drapeau doit donc
    valoir la même chose aux DEUX tours d'un même battle round.
    """
    engine.game_state["turn"] = 5

    for current_player in (1, 2):
        engine.game_state["current_player"] = current_player
        assert _flags(engine, observer)["i_play_first"] == expected, (
            f"siège de l'escouade {observer} altéré par current_player={current_player}"
        )


def test_seat_bit_is_not_a_copy_of_is_my_turn(engine: W40KEngine) -> None:
    """obs_seat_distinct : les deux drapeaux divergent au tour du second joueur.

    Sans cette assertion, `i_play_first` câblé par erreur sur `current_player == active_player`
    (donc `is_my_turn` en double) resterait vert partout ailleurs.
    """
    engine.game_state["current_player"] = 2

    p1_flags = _flags(engine, "1")
    p2_flags = _flags(engine, "2")

    assert p1_flags == {"i_play_first": 1.0, "is_my_turn": 0.0}
    assert p2_flags == {"i_play_first": 0.0, "is_my_turn": 1.0}
