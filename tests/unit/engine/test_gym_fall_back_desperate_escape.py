"""Verrou findings 1&2 — Desperate Escape dans le chemin gym fall_back.

Le chemin gym `squad_fall_back` passait par `execute_squad_move` sans appeler
`desperate_escape_pre_move`, donc `_flee_mode` n'était jamais posé : step.log émettait
toujours [ORDERED RETREAT] même pour une unité battle-shocked + engagée, et les jets
hazard (06.03) n'étaient pas résolus.

Chaîne exercée :
  _process_squad_action(squad_fall_back)
  → si battle_shocked + engagée → desperate_escape_pre_move(auto_resolve=True)
  → game_state["_flee_mode"] = "desperate_escape"
  → action_log["fleeMode"] = "desperate_escape"

Cycle rouge→vert : supprimer le bloc d'injection `if move_type == "fall_back":`
dans la branche `squad_normal_move / squad_advance / squad_fall_back` de
`_process_squad_action` fait passer `test_gym_fall_back_battleshocked_sets_desperate_escape`
en rouge.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.shared_utils import MOVE_CELL_MAP_CACHE_KEY
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


def _engine_engaged() -> W40KEngine:
    """Moteur avec unités en engagement range (col 20/21, même row)."""
    return _make_engine(_base_config([
        _unit_cfg(1, 1, 20, 20),  # J1 — sera battle-shocked
        _unit_cfg(2, 2, 21, 20),  # J2 — adjacent (ER 1 hex)
    ]))


def _unit_cfg_3models(uid: int, player: int) -> Dict[str, Any]:
    """Escouade de 3 figurines en formation pont : A(20,20) — B(22,20) — C(24,20).

    Coh = 2 subhexes (ISH=1). A et B sont à 2 hexes, B et C aussi. Si B (pont) meurt,
    A et C sont à 4 hexes → incoherents.
    """
    base = _unit_cfg(uid, player, 20, 20)
    base["HP_CUR"] = 3
    base["HP_MAX"] = 3
    base["VALUE"] = 300
    base["models"] = [
        {"col": 20, "row": 20, "VALUE": 100},  # 1#0 — ancre A
        {"col": 22, "row": 20, "VALUE": 100},  # 1#1 — pont B
        {"col": 24, "row": 20, "VALUE": 100},  # 1#2 — queue C
    ]
    return base


def _engine_bridge_formation() -> W40KEngine:
    """Moteur : escouade 1 en formation pont (3 fig), ennemi (25,20) adjacent à C."""
    return _make_engine(_base_config([
        _unit_cfg_3models(1, 1),       # J1 — 3 figs en pont
        _unit_cfg(2, 2, 25, 20),       # J2 — adjacent à C (24,20), déclenche l'ER
    ]))


def _engine_battle_shocked() -> tuple:
    """Moteur prêt pour un fall_back avec unité 1 battle-shocked et engagée."""
    eng = _engine_engaged()
    gs = eng.game_state
    gs["phase"] = "move"
    gs["move_activation_pool"] = ["1"]
    unit1 = next(u for u in gs["units"] if str(u["id"]) == "1")
    unit1["battle_shocked"] = True
    return eng, gs


def test_gym_fall_back_battleshocked_sets_desperate_escape() -> None:
    """fall_back avec battle_shocked + engagée → fleeMode=desperate_escape dans action_log."""
    eng, gs = _engine_battle_shocked()

    # Destination de fall_back : case (18, 20) — loin de l'ennemi en (21,20).
    before = len(gs.get("action_logs", []))
    ok, result = eng._process_squad_action(
        {"action": "squad_fall_back", "squad_id": "1", "destCol": 18, "destRow": 20}
    )

    assert ok, f"squad_fall_back a échoué : {result}"

    move_logs = [
        e for e in gs["action_logs"][before:]
        if e.get("type") == "move"
    ]
    assert len(move_logs) == 1, (
        f"attendu 1 action_log move, obtenu {len(move_logs)}: {gs['action_logs'][before:]}"
    )
    assert move_logs[0]["fleeMode"] == "desperate_escape", (
        f"fleeMode attendu 'desperate_escape', obtenu {move_logs[0].get('fleeMode')!r}"
    )


def test_gym_desperate_escape_died_clears_game_state_keys() -> None:
    """Hazard détruit l'unité → _flee_mode et _desperate_escape_rolls absents du game_state.

    Régression : l'ancien chemin retournait sans purger ces clés ; le prochain fall_back
    dans le même épisode héritait de _flee_mode="desperate_escape" même pour une unité
    non-battle-shocked.
    """
    eng, gs = _engine_battle_shocked()

    # Simuler desperate_escape_pre_move qui pose les clés PUIS retourne is_alive=False.
    def _fake_pre_move(
        squad_id: str, game_state: Dict[str, Any], was_engaged: bool, auto_resolve: bool
    ) -> tuple:
        game_state["_flee_mode"] = "desperate_escape"
        game_state["_desperate_escape_rolls"] = [1, 2]
        return True, False, 2  # is_desperate, is_alive=False, wounds

    with patch(
        "engine.phase_handlers.shared_utils.desperate_escape_pre_move",
        side_effect=_fake_pre_move,
    ):
        ok, result = eng._process_squad_action(
            {"action": "squad_fall_back", "squad_id": "1", "destCol": 18, "destRow": 20}
        )

    assert ok, f"desperate_escape_died a échoué : {result}"
    assert result.get("action") == "desperate_escape_died"
    assert "_flee_mode" not in gs, (
        f"_flee_mode stale dans game_state : {gs['_flee_mode']!r}"
    )
    assert "_desperate_escape_rolls" not in gs, (
        "_desperate_escape_rolls stale dans game_state"
    )


def test_gym_fall_back_not_battleshocked_keeps_ordered_retreat() -> None:
    """fall_back sans battle_shock → fleeMode=ordered_retreat (comportement normal préservé)."""
    eng = _engine_engaged()
    gs = eng.game_state

    gs["phase"] = "move"
    gs["move_activation_pool"] = ["1"]

    unit1 = next(u for u in gs["units"] if str(u["id"]) == "1")
    unit1["battle_shocked"] = False

    before = len(gs.get("action_logs", []))
    ok, result = eng._process_squad_action(
        {"action": "squad_fall_back", "squad_id": "1", "destCol": 18, "destRow": 20}
    )

    assert ok, f"squad_fall_back a échoué : {result}"

    move_logs = [
        e for e in gs["action_logs"][before:]
        if e.get("type") == "move"
    ]
    assert len(move_logs) == 1
    assert move_logs[0]["fleeMode"] == "ordered_retreat", (
        f"fleeMode attendu 'ordered_retreat', obtenu {move_logs[0].get('fleeMode')!r}"
    )


def test_gym_desperate_escape_bridge_death_coherency_relaxed() -> None:
    """Mort du pont en Desperate Escape → formation incohérente → execute_squad_move doit réussir.

    Scénario : escouade 3 figs A(20,20)–B(22,20)–C(24,20), ennemi en (25,20).
    Coh = 2 subhexes (ISH=1). B est le seul lien A–C (chacun à 2", limite de coh).
    Le mock simule un Desperate Escape qui tue B : A et C restent vivants, à 4 hexes l'un
    de l'autre → incoherents.

    Sans le fix (extra_constraints=_move_constraints absent de execute_squad_move) :
    validate_move_plan avec require_coherency=True rejette le plan → ValueError.

    Avec le fix : 03.03 enforce la coh en FIN de phase (end_of_turn_regain_coherency_all_squads,
    déjà câblé) ; le move lui-même ne doit pas l'exiger pour un Desperate Escape.

    Cycle rouge→vert : supprimer `extra_constraints=_move_constraints` dans l'appel
    execute_squad_move de w40k_core._process_semantic_action déclenche un ValueError
    « incohérence masque/exécution / require_coherency ».
    """
    eng = _engine_bridge_formation()
    gs = eng.game_state

    gs["phase"] = "move"
    gs["move_activation_pool"] = ["1"]
    unit1 = next(u for u in gs["units"] if str(u["id"]) == "1")
    unit1["battle_shocked"] = True

    bridge_mid = "1#1"

    def _kill_bridge(
        squad_id: str, game_state: Dict[str, Any], was_engaged: bool, auto_resolve: bool
    ) -> tuple:
        """Simule la mort de B (pont) par le Desperate Escape."""
        game_state["models_cache"].pop(bridge_mid, None)
        game_state["squad_models"]["1"] = [
            m for m in game_state["squad_models"].get("1", []) if m != bridge_mid
        ]
        game_state["_flee_mode"] = "desperate_escape"
        return True, True, 1  # is_desperate, is_alive (A et C survivent), wounds

    # Destination ancre : A(20,20) → (16,20) ; C(24,20) → (20,20). Budget 6 ≥ 4. Pas en ER ennemi.
    with patch(
        "engine.phase_handlers.shared_utils.desperate_escape_pre_move",
        side_effect=_kill_bridge,
    ):
        ok, result = eng._process_squad_action(
            {"action": "squad_fall_back", "squad_id": "1", "destCol": 16, "destRow": 20}
        )

    assert ok, (
        f"squad_fall_back post-mort-du-pont a échoué (incohérence masque/exécution non corrigée) : {result}"
    )
    assert result.get("action") != "desperate_escape_died", (
        "A et C survivent → l'action ne doit pas être desperate_escape_died"
    )


def test_gym_fall_back_anchor_shifted_skips_move() -> None:
    """Desperate Escape tue une figurine d'ancre → pool périmé → activation_complete sans move.

    Scenario reproduisant le crash bot_ranking :
    - Unité multi-modèles battle-shocked + engagée (squad 1 en (20,20)).
    - desperate_escape_pre_move tue la figurine d'ancre : units_cache passe à (20,22).
    - La destination choisie par le masque (18,20) n'est plus atteignable depuis (20,22)
      (elle était dans le pool bâti depuis (20,20)).
    - Attendu : fall_back_anchor_shifted est retourné, pas de ValueError.
    """
    eng, gs = _engine_battle_shocked()

    def _fake_pre_move(
        squad_id: str, game_state: Dict[str, Any], was_engaged: bool, auto_resolve: bool
    ) -> tuple:
        # Simuler la mort de la figurine d'ancre : units_cache se décale.
        # units_cache est keyé par str → utiliser squad_id directement (déjà str).
        game_state["_flee_mode"] = "desperate_escape"
        game_state["_desperate_escape_rolls"] = [1]
        uc = game_state["units_cache"]
        entry = dict(uc[squad_id])
        entry["row"] = 22  # ancre passe de (20,20) à (20,22)
        uc[squad_id] = entry
        return True, True, 1  # is_desperate=True, is_alive=True, 1 wound

    # Pré-seeder une entrée pour simuler un masque déjà calculé pour cette escouade.
    gs.setdefault(MOVE_CELL_MAP_CACHE_KEY, {})["1"] = {"map": {}, "anchor": (20, 20), "phase": "move"}

    with patch(
        "engine.phase_handlers.shared_utils.desperate_escape_pre_move",
        side_effect=_fake_pre_move,
    ):
        ok, result = eng._process_squad_action(
            {"action": "squad_fall_back", "squad_id": "1", "destCol": 18, "destRow": 20}
        )

    assert ok, f"fall_back_anchor_shifted a échoué : {result}"
    assert result.get("action") == "fall_back_anchor_shifted", (
        f"action attendue 'fall_back_anchor_shifted', obtenu {result.get('action')!r}"
    )
    assert result.get("activation_complete") is True
    assert "_flee_mode" not in gs, f"_flee_mode stale : {gs.get('_flee_mode')!r}"
    assert "_desperate_escape_rolls" not in gs, "_desperate_escape_rolls stale"
    assert "1" not in gs[MOVE_CELL_MAP_CACHE_KEY], "cell map stale après fall_back_anchor_shifted"

    # L'ACTIVATION EST-ELLE RÉELLEMENT CLOSE ? `activation_complete` ci-dessus n'a AUCUN lecteur
    # dans engine/ai/services : l'assertion précédente était VACANTE. Seul `end_activation` retire
    # du `move_activation_pool` (generic_handlers ~L170), et ce pool est la SEULE source de
    # `_raw_eligible_units_for_current_phase` en phase move. Sans retrait, l'escouade était
    # réactivée dans la MÊME phase (2e mouvement, interdit par 09.04) — et comme les pertes de
    # Desperate Escape peuvent avoir rompu sa coherency, chacune de ses destinations levait
    # « execute_squad_move a échoué … (formation actuelle DEJA incoherente) ».
    assert "1" not in gs["move_activation_pool"], (
        "escouade toujours dans move_activation_pool après fall_back_anchor_shifted : "
        f"{gs['move_activation_pool']} — elle sera réactivée dans la même phase de move"
    )
    assert "1" in gs["units_moved"], (
        "activation non comptabilisée : units_moved="
        f"{gs['units_moved']}"
    )
    # PAS de `units_fled` : aucun fall back n'a eu lieu (le move a été sauté), donc l'unité ne
    # doit pas porter les interdits 09.07 (pas de tir ni de charge après une retraite).
    assert "1" not in gs.get("units_fled", set()), (
        "units_fled posé alors qu'aucun fall back n'a été exécuté : "
        f"{gs.get('units_fled')}"
    )
