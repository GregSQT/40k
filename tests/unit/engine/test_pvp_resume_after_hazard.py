"""Verrou — _resume_after_hazard (chemin PvP) repose le pool depuis la NOUVELLE ancre.

Chemin exercé :
  _handle_hazard_confirm
  → desperate_escape_pre_move  (mocké : tue 1#0, ancre passe de (20,20) à (22,20))
  → _resume_after_hazard
  → movement_build_valid_destinations_pool  (espionné : capture l'ancre lue depuis units_cache)

Invariant vérifié : le pool Fall Back est construit depuis la position POST-hazard de l'ancre
(22,20), pas depuis l'état d'avant les pertes (20,20).

Cycle rouge→vert : si le mock ne met PAS à jour units_cache (ancre reste à (20,20)), la
position capturée vaut (20,20) et l'assertion échoue. Identique au cas-miroir du chemin gym
(test_gym_fall_back_anchor_shifted_skips_move) où le check `_anchor_before_de != _anchor_after_de`
évite le move depuis un pool périmé — ici le pool EST re-publié (l'unité survit et le joueur
choisit sa destination) mais doit partir de la nouvelle ancre.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import engine.phase_handlers.movement_handlers as _mh_mod

from engine.observation_builder import ObservationBuilder
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

_OBS_SIZE = ObservationBuilder.SQUAD_OBS_SIZE_TARGET


def _weapon_cfg() -> Dict[str, Any]:
    return {"ATK": 1, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 0,
            "WEAPON_RULES": [], "display_name": "Test CC"}


def _unit_cfg(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 5, "HP_MAX": 5, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [], "CC_WEAPONS": [_weapon_cfg()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": 1, "VALUE": 100,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
    }


def _unit_cfg_2models(uid: int, player: int) -> Dict[str, Any]:
    """Escouade 2 figs : 1#0 à (20,20) (ancre, tuée par hazard), 1#1 à (22,20) (nouvelle ancre).

    MOVE=6, donc depuis (22,20) le BFS atteint un large éventail de cellules.
    Depuis (20,20) le pool aurait été différent — la distinction est mesurée par l'espion.
    """
    base = _unit_cfg(uid, player, 20, 20)
    base["HP_CUR"] = 2
    base["HP_MAX"] = 2
    base["VALUE"] = 200
    base["models"] = [
        {"col": 20, "row": 20, "VALUE": 100},  # 1#0 — ancre (meurt dans le mock)
        {"col": 22, "row": 20, "VALUE": 100},  # 1#1 — nouvelle ancre post-hazard
    ]
    return base


def _base_config(units: list) -> dict:
    obs_params = {"obs_size": _OBS_SIZE}
    return {
        "board": {"default": {"cols": 60, "rows": 60, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [], "objectives": [], "inches_to_subhex": 1}},
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5,
                       "max_base_size_hex": 35, "max_turns": 5},
        "charge": {"charge_max_distance": 12},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "controlled_player": 1,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": units,
    }


def _make_engine(config: dict) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(config), gym_training_mode=True)
    eng.reset()
    return eng


def _engine_2models() -> W40KEngine:
    """Moteur : escouade 2 figs (1#0 à (20,20), 1#1 à (22,20)), ennemi en (21,20).

    L'ennemi à (21,20) est adjacent à 1#0 → _squad_is_in_enemy_er retourne True AVANT le mock.
    Après le mock, 1#0 est mort et la nouvelle ancre est 1#1 à (22,20).
    """
    return _make_engine(_base_config([
        _unit_cfg_2models(1, 1),       # J1 — 2 figs
        _unit_cfg(2, 2, 21, 20),       # J2 — adjacent à 1#0, déclenche l'ER
    ]))


def test_pvp_resume_after_hazard_pool_rebuilt_from_new_anchor() -> None:
    """_resume_after_hazard repose le pool Fall Back depuis la NOUVELLE ancre post-hazard.

    Scénario :
    - Escouade 1 : 2 figs, 1#0 à (20,20), 1#1 à (22,20). Ennemie à (21,20) → ER.
    - Hazard tue 1#0 → units_cache["1"] passe à (22,20) (mock).
    - _resume_after_hazard appelle movement_build_valid_destinations_pool.
    - L'espion capture la position lue depuis units_cache au moment de l'appel.
    - Attendu : (22, 20). Si le pool était construit depuis l'ancre d'avant-hazard, (20, 20).
    """
    eng = _engine_2models()
    gs = eng.game_state

    gs["phase"] = "move"
    gs["current_player"] = 1
    gs.setdefault("enemy_adjacent_hexes_player_1", set())

    unit1 = next(u for u in gs["units"] if str(u["id"]) == "1")
    unit1["battle_shocked"] = True

    _real_pool = _mh_mod.movement_build_valid_destinations_pool
    captured_anchor: List[Tuple[int, int]] = []

    def _spy_pool(game_state: Dict[str, Any], unit_id: str, **kwargs: Any) -> Any:
        entry = game_state.get("units_cache", {}).get(str(unit_id))
        if entry:
            captured_anchor.append((int(entry["col"]), int(entry["row"])))
        return _real_pool(game_state, unit_id, **kwargs)

    def _mock_desperate_escape(
        squad_id: str, game_state: Dict[str, Any], was_engaged: bool, auto_resolve: bool
    ) -> tuple:
        """Simule la mort de 1#0 par hazard; la nouvelle ancre est 1#1 à (22,20)."""
        game_state["models_cache"].pop("1#0", None)
        sm = game_state.get("squad_models", {})
        if "1" in sm:
            sm["1"] = [m for m in sm["1"] if m != "1#0"]
        uc = game_state["units_cache"]
        uc["1"] = {**uc["1"], "col": 22, "row": 20}
        game_state["_flee_mode"] = "desperate_escape"
        return True, True, 1  # is_desperate, is_alive, wounds

    with patch(
        "engine.phase_handlers.shared_utils.desperate_escape_pre_move",
        side_effect=_mock_desperate_escape,
    ), patch.object(_mh_mod, "movement_build_valid_destinations_pool", side_effect=_spy_pool):
        ok, result = eng._handle_hazard_confirm({"unitId": "1"})

    assert ok, f"_handle_hazard_confirm a échoué : {result}"

    assert result.get("waiting_for_player") is True, (
        "unité vivante post-hazard → waiting_for_player=True attendu (Fall Back preview)"
    )
    assert result.get("would_flee") is True, (
        "résultat doit porter would_flee=True (Desperate Escape, unité vivante)"
    )
    assert result.get("fall_back_resume") is True, (
        "fall_back_resume=True attendu pour que le front entre en perModelMove sans clic"
    )

    assert len(captured_anchor) >= 1, (
        "movement_build_valid_destinations_pool n'a pas été appelé dans _resume_after_hazard"
    )
    assert captured_anchor[0] == (22, 20), (
        f"pool construit depuis {captured_anchor[0]!r} au lieu de (22, 20) — "
        "units_cache n'a pas été relu après les pertes hazard. "
        "Cycle rouge : si le mock ne met pas à jour units_cache, la position vaut (20, 20)."
    )

    valid_dests = result.get("valid_destinations", [])
    assert valid_dests, (
        "valid_destinations vide : BFS depuis la nouvelle ancre (22,20) n'a trouvé "
        "aucune destination — pool mal construit ou budget nul"
    )
