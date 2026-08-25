"""Gardes résiduelles unit_by_id — verrou ROUGE→VERT par site (39 conversions).

Chaque test vérifie qu'un id issu d'une source interne (units_cache, pool, paramètre)
provoque ConfigurationError lorsqu'absent de unit_by_id, au lieu d'une exception
ad-hoc (KeyError/ValueError) ou d'un repli silencieux.

Tous les tests sont ROUGE si les require_unit_by_id sont remplacés par
  `get_unit_by_id(...)` + `if _unit is None: raise KeyError(...)`
et VERTS avec la correction.
"""
import pytest
from shared.data_validation import ConfigurationError


# ---------------------------------------------------------------------------
# Helpers communs
# ---------------------------------------------------------------------------

def _base_gs(**overrides) -> dict:
    gs = {
        "models_cache": {},
        "squad_models": {},
        "units_cache": {},
        "unit_by_id": {},
        "units": [],
        "action_logs": [],
        "action_log_seq": 0,
        "_unit_move_version": 0,
        "los_cache": {},
        "hex_los_cache": {},
        "_los_pair_cache": {},
        "config": {"game_rules": {"engagement_zone": 2}},
        "phase": "move",
        "gym_training_mode": True,
        "inches_to_subhex": 5,
        "board_cols": 30,
        "board_rows": 30,
    }
    gs.update(overrides)
    return gs


def _unit(squad_id: str, player: int = 1) -> dict:
    return {"id": squad_id, "player": player, "UNIT_RULES": [], "battle_shocked": False,
            "deployed_on_turn": 0, "HP_MAX": 10, "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7}


def _cache_entry(player: int = 1) -> dict:
    return {"col": 5, "row": 5, "player": player, "BASE_SIZE": 1, "BASE_SHAPE": "round"}


# ---------------------------------------------------------------------------
# 1. shared_utils.unit_can_reroll_charge
# ---------------------------------------------------------------------------

def test_unit_can_reroll_charge_absent_unit_by_id():
    """unit_id absent de unit_by_id → ConfigurationError (was: KeyError)."""
    from engine.phase_handlers.shared_utils import unit_can_reroll_charge
    gs = _base_gs(unit_by_id={})
    with pytest.raises(ConfigurationError, match="u1"):
        unit_can_reroll_charge(gs, "u1")


# ---------------------------------------------------------------------------
# 2. shared_utils._unit_was_set_up_this_turn
# ---------------------------------------------------------------------------

def test_unit_was_set_up_this_turn_absent_unit_by_id():
    """squad_id absent de unit_by_id → ConfigurationError (was: KeyError)."""
    from engine.phase_handlers.shared_utils import _unit_was_set_up_this_turn
    gs = _base_gs(unit_by_id={}, turn=1)
    with pytest.raises(ConfigurationError, match="u1"):
        _unit_was_set_up_this_turn(gs, "u1")


def test_unit_was_set_up_this_turn_present_none_returns_false():
    """deployed_on_turn=None → False (pas de conversion, champ de l'unité)."""
    from engine.phase_handlers.shared_utils import _unit_was_set_up_this_turn
    u = _unit("u1")
    u["deployed_on_turn"] = None
    gs = _base_gs(unit_by_id={"u1": u}, turn=1)
    assert _unit_was_set_up_this_turn(gs, "u1") is False


# ---------------------------------------------------------------------------
# 3. shared_utils._heavy_unit_is_engaged
# ---------------------------------------------------------------------------

def test_heavy_unit_is_engaged_absent_unit_by_id():
    """squad_id absent de unit_by_id → ConfigurationError (was: KeyError)."""
    from engine.phase_handlers.shared_utils import _heavy_unit_is_engaged
    gs = _base_gs(unit_by_id={}, units_cache={})
    with pytest.raises(ConfigurationError, match="u1"):
        _heavy_unit_is_engaged(gs, "u1")


# ---------------------------------------------------------------------------
# 4. shared_utils.desperate_escape_pre_move
# ---------------------------------------------------------------------------

def test_desperate_escape_pre_move_absent_unit_by_id():
    """squad_id absent de unit_by_id → ConfigurationError (was: KeyError)."""
    from engine.phase_handlers.shared_utils import desperate_escape_pre_move
    gs = _base_gs(unit_by_id={})
    with pytest.raises(ConfigurationError, match="u1"):
        desperate_escape_pre_move("u1", gs, was_engaged=True, auto_resolve=True)


# ---------------------------------------------------------------------------
# 5. shared_utils.desperate_escape_post_move
# ---------------------------------------------------------------------------

def test_desperate_escape_post_move_absent_unit_by_id():
    """squad_id absent de unit_by_id → ConfigurationError (was: KeyError)."""
    from engine.phase_handlers.shared_utils import desperate_escape_post_move
    gs = _base_gs(unit_by_id={})
    with pytest.raises(ConfigurationError, match="u1"):
        desperate_escape_post_move("u1", gs)


# ---------------------------------------------------------------------------
# 6. shared_utils._coherency_alive
# ---------------------------------------------------------------------------

def test_coherency_alive_absent_unit_by_id():
    """squad_id absent de unit_by_id → ConfigurationError (was: KeyError)."""
    from engine.phase_handlers.shared_utils import _coherency_alive
    m = {"id": "m1", "squad_id": "u1", "col": 0, "row": 0, "level": 0}
    gs = _base_gs(
        models_cache={"m1": m},
        squad_models={"u1": ["m1"]},
        unit_by_id={},
    )
    with pytest.raises(ConfigurationError, match="u1"):
        _coherency_alive(gs, "u1")


def test_coherency_alive_no_mids_returns_empty():
    """Escouade sans figurine vivante → [] sans toucher unit_by_id."""
    from engine.phase_handlers.shared_utils import _coherency_alive
    gs = _base_gs(models_cache={}, squad_models={"u1": []}, unit_by_id={})
    assert _coherency_alive(gs, "u1") == []


# ---------------------------------------------------------------------------
# 7. shared_utils.maybe_resolve_reactive_move — moved_unit absent
# ---------------------------------------------------------------------------

def test_reactive_move_moved_unit_absent_unit_by_id():
    """moved_unit_id absent de unit_by_id → ConfigurationError (was: KeyError)."""
    from engine.phase_handlers.shared_utils import maybe_resolve_reactive_move
    gs = _base_gs(
        unit_by_id={},
        units_cache={},
        reaction_window_active=False,
        units_reacted_this_enemy_turn=set(),
    )
    with pytest.raises(ConfigurationError, match="mover"):
        maybe_resolve_reactive_move(gs, "mover", 0, 0, 1, 0, "move", "normal")


# ---------------------------------------------------------------------------
# 8. shared_utils._fight_overrun_pile_in_plan — squad absent
# ---------------------------------------------------------------------------

def test_fight_overrun_pile_in_plan_absent_unit_by_id():
    """squad_id absent de unit_by_id (avec figurine vivante) → ConfigurationError (was: KeyError)."""
    from engine.phase_handlers.shared_utils import _fight_overrun_pile_in_plan
    m = {"id": "m1", "squad_id": "u1", "col": 0, "row": 0, "level": 0,
         "BASE_SIZE": 1, "BASE_SHAPE": "round", "player": 1}
    gs = _base_gs(
        models_cache={"m1": m},
        squad_models={"u1": ["m1"]},
        units_cache={"u1": _cache_entry()},
        unit_by_id={},
    )
    with pytest.raises(ConfigurationError, match="u1"):
        _fight_overrun_pile_in_plan(gs, "u1")


# ---------------------------------------------------------------------------
# 9. shooting_handlers — phase start (unit de units_cache absent de unit_by_id)
# ---------------------------------------------------------------------------

def test_shooting_phase_start_unit_absent_unit_by_id():
    """Unit présente dans units_cache mais absente de unit_by_id → ConfigurationError."""
    from engine.phase_handlers.shooting_handlers import shooting_phase_start
    gs = _base_gs(
        phase="move",
        current_player=1,
        units_cache={"u1": _cache_entry(player=1)},
        unit_by_id={},  # u1 absent
        squad_models={"u1": []},
        models_cache={},
        turn=1,
        episode_number=1,
        units_shot=set(),
        units_cannot_shoot=set(),
    )
    with pytest.raises(ConfigurationError, match="u1"):
        shooting_phase_start(gs)


# ---------------------------------------------------------------------------
# 10. shooting_handlers — _shoot_preview_valid_targets (enemy absent)
# ---------------------------------------------------------------------------

def test_build_weapon_availability_enemy_precheck_absent_unit_by_id():
    """enemy_id de enemy_entries_on_battlefield absent de unit_by_id → ConfigurationError."""
    from engine.phase_handlers.shooting_handlers import _build_weapon_availability_enemy_precheck
    attacker = _unit("a1", player=0)
    attacker["UNIT_KEYWORDS"] = []
    weapon = {"ATK": 1, "STR": 4, "AP": 0, "DMG": 1, "RNG": 24, "NB": 1,
              "WEAPON_RULES": [], "code": "gun"}

    def _ce(col, row, player):
        return {"col": col, "row": row, "player": player,
                "BASE_SIZE": 1, "BASE_SHAPE": "round", "deployed_on_turn": 0,
                "occupied_hexes": [(col, row)]}

    gs = _base_gs(
        phase="shoot",
        current_player=0,
        models_cache={},
        squad_models={"a1": [], "e1": []},
        units_cache={"a1": _ce(0, 0, 0), "e1": _ce(5, 5, 1)},
        unit_by_id={"a1": attacker},  # e1 absent
        inches_to_subhex=5,
        gym_training_mode=True,
        terrain_areas=[],
        wall_hexes=set(),
        units_took_to_skies=set(),
        distance_metric={"move": "hex"},
    )
    with pytest.raises(ConfigurationError, match="e1"):
        _build_weapon_availability_enemy_precheck(gs, attacker, [weapon])


# ---------------------------------------------------------------------------
# 11. observation_builder.squad_grid_anchor — squad absent
# ---------------------------------------------------------------------------

def test_squad_grid_anchor_absent_unit_by_id():
    """active_squad_id absent de unit_by_id (mais présent dans units_cache) → ConfigurationError."""
    from engine.observation_builder import ObservationBuilder
    u = _unit("u1")
    u["deployed_on_turn"] = 0  # sur la table
    gs = _base_gs(
        units_cache={"u1": _cache_entry()},
        unit_by_id={},  # absent
    )
    obs = ObservationBuilder.__new__(ObservationBuilder)
    with pytest.raises(ConfigurationError, match="u1"):
        obs.squad_grid_anchor(gs, "u1")


# ---------------------------------------------------------------------------
# 12. observation_builder.build_squad_observation — squad absent
# ---------------------------------------------------------------------------

def test_build_squad_observation_absent_unit_by_id():
    """squad_id dans units_cache mais absent de unit_by_id → ConfigurationError."""
    from engine.observation_builder import ObservationBuilder
    m = {"id": "m1", "squad_id": "u1", "player": 1, "col": 5, "row": 5, "level": 0,
         "BASE_SIZE": 1, "BASE_SHAPE": "round"}
    gs = _base_gs(
        models_cache={"m1": m},
        squad_models={"u1": ["m1"]},
        units_cache={"u1": _cache_entry()},
        squad_cache={"u1": {"OC": 1, "model_count_at_start": 1}},
        unit_by_id={},  # absent
        phase="shoot",
    )
    obs = ObservationBuilder.__new__(ObservationBuilder)
    with pytest.raises(ConfigurationError, match="u1"):
        obs.build_squad_observation(gs, "u1")


# ---------------------------------------------------------------------------
# 13. action_decoder._get_valid_deployment_hexes — unit absent
# ---------------------------------------------------------------------------

def test_get_valid_deployment_hexes_absent_unit_by_id():
    """unit_id absent de unit_by_id → ConfigurationError (was: KeyError)."""
    from engine.action_decoder import ActionDecoder
    gs = _base_gs(
        unit_by_id={},
        phase="deployment",
        units_cache={"u1": _cache_entry()},
    )
    dec = ActionDecoder.__new__(ActionDecoder)
    with pytest.raises(ConfigurationError, match="u1"):
        dec._get_valid_deployment_hexes(gs, 1, "u1")


# ---------------------------------------------------------------------------
# 14. charge_handlers._charge_budget_subhex — unit=None + unit_id absent
# ---------------------------------------------------------------------------

def test_charge_budget_subhex_absent_unit_by_id():
    """unit=None et unit_id absent de unit_by_id → ConfigurationError (was: KeyError)."""
    from engine.phase_handlers.charge_handlers import _charge_budget_subhex
    gs = _base_gs(
        unit_by_id={},
        inches_to_subhex=5,
        units_took_to_skies_charge=set(),
    )
    with pytest.raises(ConfigurationError, match="u1"):
        _charge_budget_subhex(gs, "u1", 9, unit=None)


# ---------------------------------------------------------------------------
# 15. charge_handlers.charge_roll_for_activation_pool — unit_id de units_cache absent
# ---------------------------------------------------------------------------

def test_get_eligible_units_absent_unit_by_id():
    """unit_id de units_cache absent de unit_by_id → ConfigurationError (was: KeyError)."""
    from engine.phase_handlers.charge_handlers import get_eligible_units
    cache_entry = _cache_entry(player=1)
    cache_entry["deployed_on_turn"] = 0  # sur la table
    gs = _base_gs(
        unit_by_id={},
        units_cache={"u1": cache_entry},
        current_player=1,
        phase="charge",
        units_cannot_charge=set(),
        units_advanced=set(),
        gym_training_mode=True,
        inches_to_subhex=5,
        wall_hexes=set(),
        board_cols=30,
        board_rows=30,
        terrain_areas=[],
        config={"game_rules": {"engagement_zone": 2}, "charge": {"charge_max_distance": 12}},
        distance_metric={"move": "hex"},
        units_took_to_skies_charge=set(),
    )
    with pytest.raises(ConfigurationError, match="u1"):
        get_eligible_units(gs)
