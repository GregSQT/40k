"""PvE : la décision du bot passe par le contrat SQUAD, le même que l'entraînement.

Avant cette migration, `make_ai_decision` construisait une observation mono-figurine (359-d)
et un masque legacy par unité, puis décodait avec `convert_gym_action`. Avec les configs
réelles (`obs_size = SQUAD_OBS_SIZE_TARGET`), le premier appel levait `RuntimeError` : le mode
PvE était en panne. Et même s'il avait tourné, il aurait servi à la politique un espace
d'observation et un vocabulaire d'action qui ne sont PAS ceux sur lesquels elle a été entraînée.

Ce que ces tests verrouillent :
  1. l'observation servie au modèle est le Dict squad (tenseurs d'entités + grille) ;
  2. le masque a la taille de l'espace d'action squad, et vient du décodeur squad ;
  3. la sémantique rendue est celle de `convert_squad_action` (squad_id, pas unitId forcé) ;
  4. une action hors masque lève au lieu de se replier sur une action « sûre ».
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import numpy as np
import pytest

from engine.observation_builder import ObservationBuilder
from engine.pve_controller import PvEController
from engine.spatial_grid import GRID_CHANNELS, GRID_SIZE
from engine.w40k_core import W40KEngine


def _weapon_cfg() -> Dict[str, Any]:
    return {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": [], "display_name": "Test Bolter"}


def _unit_cfg(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 3, "HP_MAX": 3, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": 1, "VALUE": 100,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
    }


class _RecordingModel:
    """Modèle factice : mémorise ce qu'on lui sert et joue une action imposée."""

    def __init__(self, action: int) -> None:
        self.action = action
        self.seen_obs: Any = None
        self.seen_mask: Any = None

    def predict(self, obs, action_masks=None, deterministic=True):
        self.seen_obs = obs
        self.seen_mask = action_masks
        return np.array([self.action]), None


@pytest.fixture
def engine():
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    config = {
        "board": {"default": {"cols": 60, "rows": 60, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [], "objectives": [], "inches_to_subhex": 1}},
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5,
                       "max_base_size_hex": 35, "max_turns": 3},
        "charge": {"charge_max_distance": 12},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [_unit_cfg(1, 1, 20, 20), _unit_cfg(2, 2, 50, 50)],
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=config)
    eng.reset()
    eng.game_state["phase"] = "move"
    return eng


def _controller_with(model: _RecordingModel, engine) -> PvEController:
    ctrl = PvEController(config={"quiet": True, "controlled_agent": "TestAgent"})
    ctrl.micro_models = {"TestUnit": model}
    ctrl.micro_model_paths = {"TestUnit": "stub.zip"}
    ctrl.micro_model_vec_stats = {"stub.zip": None}  # modèle sans VecNormalize : obs brutes
    ctrl.unit_registry = type("_Reg", (), {"get_model_key": staticmethod(lambda t: "TestUnit")})()
    return ctrl


def _first_allowed_move_action(engine) -> int:
    mask, _ = engine.action_decoder.get_squad_action_mask_and_eligible_units(engine.game_state)
    allowed = [i for i, v in enumerate(mask) if v]
    assert allowed, "aucune action jouable : le scénario de test ne prouverait rien"
    return allowed[0]


def test_model_is_served_the_squad_dict_observation(engine):
    """L'obs passée au modèle est le Dict squad complet, grille comprise."""
    model = _RecordingModel(_first_allowed_move_action(engine))
    ctrl = _controller_with(model, engine)

    ctrl.make_ai_decision(engine.game_state, engine)

    assert isinstance(model.seen_obs, dict), "obs mono-figurine servie à une politique squad"
    assert "grid" in model.seen_obs
    assert model.seen_obs["grid"].shape == (GRID_CHANNELS, GRID_SIZE, GRID_SIZE)
    for key, shape in ObservationBuilder.squad_obs_shapes().items():
        assert model.seen_obs[key].shape == shape


def test_mask_is_the_squad_action_space(engine):
    """Le masque servi est celui du décodeur squad, à la taille de son espace d'action."""
    model = _RecordingModel(_first_allowed_move_action(engine))
    ctrl = _controller_with(model, engine)

    ctrl.make_ai_decision(engine.game_state, engine)

    expected, _ = engine.action_decoder.get_squad_action_mask_and_eligible_units(engine.game_state)
    assert len(model.seen_mask) == engine.action_decoder.total_action_size
    assert np.array_equal(np.asarray(model.seen_mask, dtype=bool), np.asarray(expected, dtype=bool))


def test_semantic_action_uses_the_squad_vocabulary(engine):
    """La sémantique rendue est celle de `convert_squad_action`, sans réécriture d'unitId."""
    action_int = _first_allowed_move_action(engine)
    model = _RecordingModel(action_int)
    ctrl = _controller_with(model, engine)

    semantic = ctrl.make_ai_decision(engine.game_state, engine)

    expected = engine.action_decoder.convert_squad_action(action_int, engine.game_state)
    assert semantic == expected
    assert semantic["action"].startswith("squad_"), semantic
    assert "squad_id" in semantic
    assert "unitId" not in semantic, "forcer unitId écrasait la cible des actions sans unité"


def test_action_outside_the_mask_raises(engine):
    """Action interdite → erreur explicite, jamais un repli sur une action « sûre »."""
    mask, _ = engine.action_decoder.get_squad_action_mask_and_eligible_units(engine.game_state)
    forbidden = next(i for i, v in enumerate(mask) if not v)
    ctrl = _controller_with(_RecordingModel(forbidden), engine)

    with pytest.raises(RuntimeError, match="validation failed"):
        ctrl.make_ai_decision(engine.game_state, engine)


def test_decision_is_executable_by_the_squad_dispatcher(engine):
    """Boucle complète : la sémantique décidée doit s'exécuter, sinon le tour PvE échoue.

    C'est le lien que la version précédente cassait : `execute_ai_turn` passait la décision à
    `_process_semantic_action`, qui ne connaît pas le vocabulaire squad.
    """
    action_int = _first_allowed_move_action(engine)
    ctrl = _controller_with(_RecordingModel(action_int), engine)

    semantic = ctrl.make_ai_decision(engine.game_state, engine)
    success, result = engine._process_squad_action(semantic)

    assert success is True, result
    assert isinstance(result, dict)


def test_rule_choice_scoring_uses_the_canonical_squad_observation(engine):
    """Le scoring d'option de règle passe par l'obs canonique, jamais par une obs reconstruite.

    La grille égocentrique relit la carte de cellules posée par le masque (§0.32 T-K) : elle
    n'existe que pour l'escouade ACTIVE. Construire l'obs d'une autre escouade lève — c'est le
    garde-fou qui empêche l'observation de diverger du masque.
    """
    from engine.observation_builder import ObservationBuilder as _OB

    engine.action_decoder.get_squad_action_mask_and_eligible_units(engine.game_state)
    with pytest.raises(ValueError, match="carte de cellules"):
        _OB.build_squad_grid(engine.obs_builder, engine.game_state, "2")

    obs = engine._build_observation()
    assert isinstance(obs, dict) and "grid" in obs
    assert obs["grid"].shape == (GRID_CHANNELS, GRID_SIZE, GRID_SIZE)
