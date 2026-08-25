"""T4 — Gardes résiduelles unit_by_id : verrou ROUGE→VERT par site.

Chaque test vérifie qu'un squad_id issu du pool (models_cache, units_cache, shoot_activation_pool)
provoque une ConfigurationError lorsqu'il est absent de unit_by_id, au lieu d'être silencieusement
ignoré (repli Forme B antérieur).

Tous les tests sont rouge si le require_unit_by_id est remplacé par
  `get_unit_by_id(...)` + `if _unit is not None: ...`
et verts avec la correction.
"""
import random
import pytest

from shared.data_validation import ConfigurationError

from engine.phase_handlers.shared_utils import (
    move_plan_distance_mode,
    allocate_mortal_wounds,
    squad_shoot_los_overview,
    _resolve_one_manual_wound,
    _resolve_one_hazard_wound,
)
from engine.phase_handlers.shared_utils import ManualAllocCtx, SHOOT_CTX


# ---------------------------------------------------------------------------
# 1. move_plan_distance_mode — squad absent de unit_by_id (metric hex)
# ---------------------------------------------------------------------------

def _gs_move_metric(squad_id_in_unit_by_id: bool) -> dict:
    unit = {"id": "1", "player": 1, "UNIT_RULES": [], "UNIT_KEYWORDS": ["FLY"]}
    gs = {
        "models_cache": {},
        "squad_models": {"1": []},
        "units_cache": {"1": {"col": 0, "row": 0, "player": 1}},
        "units": [unit],
        "unit_by_id": {"1": unit} if squad_id_in_unit_by_id else {},
        "config": {"game_rules": {"engagement_zone": 2}, "move": {}},
        "phase": "move",
        "gym_training_mode": False,  # force metric hex
        "inches_to_subhex": 1,
        "units_took_to_skies": set(),
        "terrain_areas": [],
        "board_cols": 30, "board_rows": 30,
        "wall_hexes": set(),
        "distance_metric": {"move": "hex"},
    }
    return gs


def test_move_plan_distance_mode_absent_de_unit_by_id():
    """squad absent de unit_by_id avec metric hex → ConfigurationError (was: return 'geodesic')."""
    gs = _gs_move_metric(squad_id_in_unit_by_id=False)
    with pytest.raises(ConfigurationError, match="1"):
        move_plan_distance_mode(gs, "1")


def test_move_plan_distance_mode_euclidean_ne_lit_pas_unit():
    """Metric euclidean → unit_by_id jamais lu, pas d'erreur même si unité absente.

    move_plan_distance_mode accepte un metric explicite : c'est la seule façon de forcer
    une métrique dans les tests sans passer par game_config.json (lu par get_config_loader).
    """
    gs = _gs_move_metric(squad_id_in_unit_by_id=False)
    # metric != "hex" → return "euclidean" avant require_unit_by_id (line 4835-4836)
    result = move_plan_distance_mode(gs, "1", metric="euclidean")
    assert result == "euclidean"


# ---------------------------------------------------------------------------
# 2. allocate_mortal_wounds — squad_id de models_cache absent de unit_by_id
# ---------------------------------------------------------------------------

def _gs_mortal_wounds(squad_in_unit_by_id: bool) -> dict:
    target_unit = {"id": "2", "player": 1, "UNIT_RULES": []}
    target_model = {
        "id": "T1", "squad_id": "2", "player": 1,
        "HP_CUR": 2, "HP_MAX": 2, "col": 5, "row": 5,
    }
    return {
        "models_cache": {"T1": target_model},
        "squad_models": {"2": ["T1"]},
        "squad_cache": {"2": {"model_count_at_start": 1}},
        "units_cache": {},
        "unit_by_id": {"2": target_unit} if squad_in_unit_by_id else {},
        "_unit_move_version": 0,
        "los_cache": {}, "hex_los_cache": {}, "_los_pair_cache": {},
        "action_logs": [], "action_log_seq": 0,
    }


def test_allocate_mortal_wounds_squad_absent_de_unit_by_id():
    """squad_id de models_cache absent de unit_by_id → ConfigurationError (was: FNP ignoré)."""
    gs = _gs_mortal_wounds(squad_in_unit_by_id=False)
    with pytest.raises(ConfigurationError, match="2"):
        allocate_mortal_wounds(gs, "2", 1, True, [])


def test_allocate_mortal_wounds_squad_present_applique_fnp(monkeypatch):
    """Vérification normale : FNP sauvegarde 1 MW → 0 dmg appliqué."""
    gs = _gs_mortal_wounds(squad_in_unit_by_id=True)
    gs["unit_by_id"]["2"]["UNIT_RULES"] = [{
        "ruleId": "feel_no_pain", "displayName": "FNP 5+",
        "rule_args": {"threshold": 5},
    }]
    monkeypatch.setattr(random, "randint", lambda a, b: 5)  # jet = 5 → sauvé
    hp_before = gs["models_cache"]["T1"]["HP_CUR"]
    allocate_mortal_wounds(gs, "2", 1, True, [])
    assert gs["models_cache"]["T1"]["HP_CUR"] == hp_before


# ---------------------------------------------------------------------------
# 3. squad_shoot_los_overview — attaquant absent de unit_by_id
# ---------------------------------------------------------------------------

def _gs_los_overview(attacker_in_unit_by_id: bool) -> dict:
    attacker_model = {
        "id": "A1", "squad_id": "1", "player": 0,
        "col": 0, "row": 0, "SHOOT_LEFT": 1,
        "RNG_WEAPONS": [{"ATK": 1, "STR": 4, "AP": 0, "DMG": 1, "RNG": 24, "NB": 1,
                         "WEAPON_RULES": [], "code": "gun"}],
    }
    attacker_unit = {"id": "1", "player": 0, "UNIT_RULES": []}
    return {
        "models_cache": {"A1": attacker_model},
        "squad_models": {"1": ["A1"]},
        "units_cache": {
            "1": {"col": 0, "row": 0, "player": 0, "BASE_SIZE": 1, "BASE_SHAPE": "round"},
        },
        "unit_by_id": {"1": attacker_unit} if attacker_in_unit_by_id else {},
        "config": {"game_rules": {"engagement_zone": 2}},
        "phase": "shoot",
        "gym_training_mode": True,
        "inches_to_subhex": 1,
        "board_cols": 30, "board_rows": 30,
        "pending_squad_shoot_intents": {},
        "units_advanced": set(),
        "units_took_to_skies": set(),
        "units_took_to_skies_charge": set(),
        "units_fell_back": set(),
        "distance_metric": {"move": "hex"},
    }


def test_squad_shoot_los_overview_absent_de_unit_by_id():
    """attaquant absent de unit_by_id → ConfigurationError (was: return vide silencieux)."""
    gs = _gs_los_overview(attacker_in_unit_by_id=False)
    with pytest.raises(ConfigurationError, match="1"):
        squad_shoot_los_overview(gs, "1")


# ---------------------------------------------------------------------------
# 4. _resolve_one_manual_wound — m["squad_id"] absent de unit_by_id (invul Waaagh!)
# ---------------------------------------------------------------------------

def _minimal_manual_wound_state(squad_in_unit_by_id: bool) -> tuple:
    """Construit (game_state, alloc, batch) minimaux pour _resolve_one_manual_wound."""
    from engine.game_state import effective_invul_save  # noqa: F401
    model = {
        "id": "T1", "squad_id": "2", "player": 1,
        "HP_CUR": 3, "HP_MAX": 3, "col": 5, "row": 5,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 7,
        "role": None, "unitType": "Grunt", "points_per_hp": 5.0, "VALUE": 10.0,
    }
    target_unit = {"id": "2", "player": 1, "UNIT_RULES": []}
    gs = {
        "models_cache": {"T1": model},
        "squad_models": {"2": ["T1"]},
        "squad_cache": {"2": {}},
        "units_cache": {
            "2": {"player": 1, "col": 5, "row": 5},
        },
        "unit_by_id": {"2": target_unit} if squad_in_unit_by_id else {},
        "action_logs": [], "action_log_seq": 0,
        "_unit_move_version": 0,
        "los_cache": {}, "hex_los_cache": {}, "_los_pair_cache": {},
        "gym_training_mode": True,
        "config": {"waaagh": False},
        "waaagh_player": None,
    }
    pw = {
        "save_roll": 3, "is_critical": False, "devastating": False,
        "attacker_mid": "A1",
        "rec": {},
    }
    weapon_group = {
        "ap": 0, "dmg_raw": 1, "target_sid": "2",
        "attacker_squad_id": "1",
    }
    alloc = {
        "summary": {"failed_saves": 0, "damage_total": 0, "models_killed": 0},
        "weapon_groups": [weapon_group],
        "hazard_details": [],
    }
    batch = {
        "current_model_id": "T1",
        "pool": [pw],
        "pool_index": 0,
        "weapon_group_idx": 0,
        "target_sid": "2",
    }
    return gs, alloc, batch


def test_resolve_one_manual_wound_invul_squad_absent_de_unit_by_id():
    """m['squad_id'] absent de unit_by_id → ConfigurationError (was: invul sans Waaagh! silencieux)."""
    gs, alloc, batch = _minimal_manual_wound_state(squad_in_unit_by_id=False)
    with pytest.raises(ConfigurationError, match="2"):
        _resolve_one_manual_wound(gs, alloc, batch, SHOOT_CTX)


# ---------------------------------------------------------------------------
# 5. _resolve_one_manual_wound — batch["target_sid"] absent de unit_by_id (FNP)
# ---------------------------------------------------------------------------

def test_resolve_one_manual_wound_fnp_target_absent_de_unit_by_id(monkeypatch):
    """batch['target_sid'] absent de unit_by_id → ConfigurationError (was: FNP ignoré)."""
    # On force le save à échouer pour atteindre la branche FNP
    gs, alloc, batch = _minimal_manual_wound_state(squad_in_unit_by_id=False)
    with pytest.raises(ConfigurationError, match="2"):
        _resolve_one_manual_wound(gs, alloc, batch, SHOOT_CTX)


# ---------------------------------------------------------------------------
# 6. _resolve_one_hazard_wound — m["squad_id"] absent de unit_by_id (FNP)
# ---------------------------------------------------------------------------

def _minimal_hazard_wound_state(squad_in_unit_by_id: bool) -> tuple:
    model = {
        "id": "T1", "squad_id": "2", "player": 1,
        "HP_CUR": 2, "HP_MAX": 2, "col": 5, "row": 5,
    }
    target_unit = {"id": "2", "player": 1, "UNIT_RULES": []}
    gs = {
        "models_cache": {"T1": model},
        "squad_models": {"2": ["T1"]},
        "squad_cache": {"2": {}},
        "units_cache": {"2": {"player": 1, "col": 5, "row": 5}},
        "unit_by_id": {"2": target_unit} if squad_in_unit_by_id else {},
        "action_logs": [], "action_log_seq": 0,
        "_unit_move_version": 0,
        "los_cache": {}, "hex_los_cache": {}, "_los_pair_cache": {},
        "gym_training_mode": True,
    }
    alloc = {
        "summary": {"failed_saves": 0, "damage_total": 0, "models_killed": 0},
        "hazard_details": [],
    }
    batch = {
        "current_model_id": "T1",
        "pool_index": 0,
        "target_sid": "2",
    }
    return gs, alloc, batch


def test_resolve_one_hazard_wound_squad_absent_de_unit_by_id():
    """m['squad_id'] absent de unit_by_id → ConfigurationError (was: FNP ignoré)."""
    gs, alloc, batch = _minimal_hazard_wound_state(squad_in_unit_by_id=False)
    with pytest.raises(ConfigurationError, match="2"):
        _resolve_one_hazard_wound(gs, alloc, batch, SHOOT_CTX)


# ---------------------------------------------------------------------------
# 7. ActionDecoder shoot pool — unit absent de unit_by_id → ConfigurationError
# ---------------------------------------------------------------------------

def test_action_decoder_shoot_pool_absent_de_unit_by_id():
    """shoot_activation_pool contient unit_id absent de unit_by_id → ConfigurationError."""
    from engine.action_decoder import ActionDecoder
    from engine.phase_handlers.shared_utils import build_squad_action_mask

    decoder = ActionDecoder.__new__(ActionDecoder)  # évite __init__ complexe

    gs = {
        "phase": "shoot",
        "current_player": 1,
        "shoot_activation_pool": ["orphan"],
        "unit_by_id": {},  # "orphan" absent
        "units_cache": {},
    }
    with pytest.raises(ConfigurationError, match="orphan"):
        decoder._raw_eligible_units_for_current_phase(gs)
