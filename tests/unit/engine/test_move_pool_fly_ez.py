"""Pool de move FLY — l'EZ de destination doit être la MÊME que celle de l'exécution.

Le chemin FLY mono-hex de ``movement_build_valid_destinations_pool`` (celui du board x1, où une
figurine tient dans une case) doit lire ``enemy_adjacent_hexes_player_N`` — l'ensemble hex que
``validate_move_plan`` / ``erode_move_pool_by_squad_block`` consultent. Sans ça, le masque offre des
destinations que l'exécution refuse : ``execute_squad_move`` lève « incohérence masque/exécution » et
les workers ``SubprocVecEnv`` du training meurent dessus.

Ce chemin avait DEUX défauts cumulés, tous deux couverts par ce test :
  1. il évaluait l'engagement avec la métrique EUCLIDIENNE (`_movement_engagement_violates`) face à
     une exécution hex — deux définitions d'une même règle ;
  2. il ne l'évaluait que dans une fenêtre de prune dilatée depuis la seule ANCRE de chaque escouade
     ennemie. Une escouade étalée (Boyz, Termagants) a des figurines à plusieurs hexes de son ancre :
     les cases voisines de CES figurines tombaient hors fenêtre et étaient acceptées SANS aucun test
     d'engagement (régression `6f495de1` « gain de perfs », 2026-05-19 ; le jumeau
     `_enemy_items_within_move_engagement_horizon` a reçu le correctif par-figurine le 2026-06-03,
     celui-ci a été oublié).

La géométrie de ce test place l'ancre ennemie HORS de portée du mover et sa dernière figurine À
portée : c'est la configuration que ni `test_move_mask_is_executable` (parties aléatoires) ni
`test_socle_normalized_at_x1` n'atteignent.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.movement_handlers import movement_build_valid_destinations_pool
from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config


def _weapon_cfg() -> Dict[str, Any]:
    return {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": [], "display_name": "Test Bolter"}


def _unit_cfg(
    uid: int, player: int, col: int, row: int, *,
    move: int = 6, fly: bool = False, models: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 1, "HP_MAX": 1, "MOVE": move, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [],
        "UNIT_RULES": [], "LD": 7, "OC": 1, "VALUE": 100,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "UNIT_KEYWORDS": [{"keywordId": "fly"}] if fly else [],
    }
    if models is not None:
        cfg["models"] = models
    return cfg


# Escouade ennemie ÉTALÉE, ancre au LOIN : l'ancre (48,25) est hors de portée du mover, mais sa
# dernière figurine (40,25) est à sa portée. 8 hexes séparent les deux — plus que toute fenêtre
# dilatée depuis l'ancre (l'ancienne valait ez + rayon_mover + rayon_ennemi + 1 = 5 hexes). C'est
# donc la géométrie qui distingue « EZ lue depuis l'escouade entière » de « depuis son ancre ».
_ENEMY_ANCHOR = (48, 25)
_ENEMY_MODELS = [{"col": 48 - 2 * i, "row": 25, "HP_CUR": 1, "level": 0, "VALUE": 20}
                 for i in range(5)]


def _make_engine() -> W40KEngine:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    config = {
        "board": {"default": {"cols": 60, "rows": 60, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [], "objectives": [], "inches_to_subhex": 1}},
        # engagement_zone = 2 : la valeur réelle de config/game_config.json (2 pouces, règle 03.04).
        "game_rules": {
            "engagement_zone": 2, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            # Cohérence d'escouade : valeurs réelles de config/game_config.json (l'escouade
            # ennemie est multi-figurine, le moteur les exige).
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
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [
            _unit_cfg(1, 1, 30, 25, move=14, fly=True),
            _unit_cfg(2, 2, _ENEMY_ANCHOR[0], _ENEMY_ANCHOR[1], models=_ENEMY_MODELS),
        ],
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(config))
    eng.reset()
    eng.game_state["phase"] = "move"
    eng.game_state["gym_training_mode"] = True
    # 21.03 : la traversée est la contrepartie d'une DÉCLARATION, y compris pour le siège piloté
    # par le modèle depuis `L6` (`fly_declaration`). On la pose donc explicitement, sans quoi le
    # pool emprunterait le chemin AU SOL et le test n'exercerait pas ce qu'il annonce.
    eng.game_state["units_took_to_skies"] = {"1"}
    build_enemy_adjacent_hexes(eng.game_state, 1)
    build_enemy_adjacent_hexes(eng.game_state, 2)
    return eng


@pytest.fixture
def engine() -> W40KEngine:
    return _make_engine()


def test_enemy_zone_covers_every_model(engine: W40KEngine) -> None:
    """Garde-fou du test : la zone d'engagement lue par l'exécution couvre bien TOUTES les
    figurines ennemies, pas seulement l'ancre — sinon le test suivant ne prouverait rien."""
    zone = engine.game_state["enemy_adjacent_hexes_player_1"]
    far_model = (_ENEMY_MODELS[-1]["col"], _ENEMY_MODELS[-1]["row"])
    # `dilate_hex_set` exclut les cellules SOURCES (elles relèvent de l'occupation) : on teste
    # donc la couronne de la figurine la plus éloignée de l'ancre.
    assert (far_model[0] - 2, far_model[1]) in zone
    assert (far_model[0], far_model[1] + 2) in zone


def test_fly_pool_never_lands_in_the_zone_of_a_non_anchor_model(engine: W40KEngine) -> None:
    """Invariant « masque ⊆ exécutable » : aucune destination du pool FLY dans l'EZ ennemie."""
    gs = engine.game_state
    from engine.phase_handlers.movement_handlers import _fly_traversal_active

    unit = next(u for u in gs["units"] if str(u["id"]) == "1")
    assert _fly_traversal_active(gs, unit, "1"), "le chemin FLY n'est pas actif : test inopérant"

    pool = movement_build_valid_destinations_pool(gs, "1", read_only=True)
    assert pool, "pool vide : le test n'exercerait rien"

    zone = gs["enemy_adjacent_hexes_player_1"]
    assert set(pool) & set(zone) == set(), (
        "destinations offertes par le pool alors qu'elles sont dans la zone d'engagement "
        f"ennemie (refusées par validate_move_plan) : {sorted(set(pool) & set(zone))[:5]}"
    )
