"""17.03 SHOOTING AT ENGAGED MONSTERS AND VEHICLES.

PDF 17 Monsters and vehicles, 17.03 : « In your Shooting phase, enemy MONSTER/VEHICLE units that
are engaged can be selected as targets of ranged attacks. Each time a model makes a ranged
attack that targets such a unit, subtract 1 from the hit roll (excluding attacks made with
[CLOSE-QUARTERS] weapons by models in a unit engaged with the target). »
PDF 25 Rules appendix, FAQ : « When my unit shoots at an engaged MONSTER/VEHICLE unit, can
models in my unit target that unit with [BLAST] weapons? A: No. »

Avant le chantier « chaîne d'attaque 100 % » (2026-09-18), toute cible engagée avec un allié du
tireur était refusée (04.02 « Unengaged ») sans exception, et aucun -1 n'existait.
"""
import random
from typing import Any, Dict

import pytest

from engine.phase_handlers import shooting_handlers as sh
from engine.phase_handlers import shared_utils as su
from engine.phase_handlers.shooting_handlers import (
    engaged_monster_vehicle_target_malus,
    target_is_monster_or_vehicle_unit,
)
from tests._state_invariants import turn_state_invariants
from tests.unit.engine._roll_helpers import roll_shoot_intent
from tests.unit.engine._state_builders import units_cache_entry as _uc


def _kw(*names):
    return [{"keywordId": n} for n in names]


def _model(mid: str, squad: str, player: int, *, keywords, col: int) -> Dict[str, Any]:
    return {"id": mid, "squad_id": squad, "player": player, "T": 7, "HP_CUR": 9, "HP_MAX": 9,
            "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "role": None, "unitType": "Speeder", "SHOOT_LEFT": 1,
            "points_per_hp": 5.0, "VALUE": 10.0, "col": col, "row": 9,
            "UNIT_KEYWORDS": _kw(*keywords), "UNIT_RULES": [], "RNG_WEAPONS": [], "CC_WEAPONS": []}


def _weapon(rules=()) -> Dict[str, Any]:
    return {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": list(rules), "code": "gun", "display_name": "GUN"}


def _game_state(*, target_keywords=("VEHICLE",), weapon_rules=()):
    weapon = _weapon(weapon_rules)
    shooter = {**_model("A0", "1", 0, keywords=("INFANTRY",), col=0), "RNG_WEAPONS": [weapon]}
    t0 = _model("V0", "2", 1, keywords=target_keywords, col=9)
    units = [{"id": "1", "player": 0, "UNIT_KEYWORDS": _kw("INFANTRY"), "UNIT_RULES": []},
             {"id": "2", "player": 1, "UNIT_KEYWORDS": _kw(*target_keywords), "UNIT_RULES": []}]
    return {
        **turn_state_invariants(),
        "gym_training_mode": False,
        "player_types": {"0": "ai", "1": "ai"},
        "config": {"game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5}},
        "turn": 1, "phase": "shoot",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": {"A0": shooter, "V0": t0},
        "squad_models": {"1": ["A0"], "2": ["V0"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": 1}},
        "units_cache": {"1": _uc(0, 9, player=0), "2": _uc(9, 9, player=1)},
        "units": units,
        "unit_by_id": {u["id"]: u for u in units},
        "objectives": [], "units_moved": set(), "units_advanced": set(),
    }


def _intent():
    return {"model_id": "A0", "target_unit_id": "2", "weapon_index": 0,
            "n_attacks_resolved": 1, "target_squad_size_at_declaration": 1}


def _neutralise(monkeypatch, *, target_engaged: bool, shooter_engaged_with_target: bool):
    """Géométrie remplacée par des verdicts : l'engagement de la cible (avec n'importe qui) et
    l'engagement tireur↔cible sont les deux faits que 17.03 lit."""
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    monkeypatch.setattr(sh, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(sh, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    monkeypatch.setattr(
        sh, "_is_adjacent_to_enemy_within_cc_range",
        lambda gs, unit: target_engaged if str(unit["id"]) == "2" else shooter_engaged_with_target,
    )
    monkeypatch.setattr(su, "_squads_are_engaged", lambda gs, a, b: shooter_engaged_with_target)


# ------------------------------------------------------------ l unite est-elle MONSTER/VEHICLE ?

def test_unite_monster_vehicle_toutes_les_figurines_vivantes():
    gs = _game_state()
    assert target_is_monster_or_vehicle_unit(gs, "2") is True
    gs["models_cache"]["V1"] = _model("V1", "2", 1, keywords=("INFANTRY",), col=10)
    gs["squad_models"]["2"].append("V1")
    assert target_is_monster_or_vehicle_unit(gs, "2") is False, "un CHARACTER d infanterie attache : pas une unite VEHICLE"
    gs["squad_models"]["2"] = []
    assert target_is_monster_or_vehicle_unit(gs, "2") is False


# --------------------------------------------------------------- le -1 au jet de touche (17.03)

def test_malus_sur_vehicule_engage_hors_arme_de_corps_a_corps(monkeypatch):
    _neutralise(monkeypatch, target_engaged=True, shooter_engaged_with_target=False)
    gs = _game_state()
    assert engaged_monster_vehicle_target_malus(gs, "1", "2", _weapon()) is True
    result = roll_shoot_intent(gs, _intent())
    assert result["engaged_target_malus"] is True
    assert result["bs"] == 4 and result["bs_base"] == 3, "BS 3+ degrade a 4+"


def test_pas_de_malus_arme_close_quarters_depuis_une_unite_engagee_avec_la_cible(monkeypatch):
    _neutralise(monkeypatch, target_engaged=True, shooter_engaged_with_target=True)
    gs = _game_state(weapon_rules=("CLOSE_QUARTERS",))
    assert engaged_monster_vehicle_target_malus(gs, "1", "2", _weapon(("CLOSE_QUARTERS",))) is False
    result = roll_shoot_intent(gs, _intent())
    assert result["engaged_target_malus"] is False and result["bs"] == 3


def test_malus_arme_close_quarters_depuis_une_unite_non_engagee_avec_la_cible(monkeypatch):
    """L exclusion vaut pour « models in a unit engaged with the target » : un pistolet tire de
    loin sur un vehicule engage ailleurs subit le -1."""
    _neutralise(monkeypatch, target_engaged=True, shooter_engaged_with_target=False)
    gs = _game_state(weapon_rules=("CLOSE_QUARTERS",))
    assert engaged_monster_vehicle_target_malus(gs, "1", "2", _weapon(("CLOSE_QUARTERS",))) is True


def test_pas_de_malus_si_la_cible_n_est_pas_engagee_ou_pas_un_vehicule(monkeypatch):
    _neutralise(monkeypatch, target_engaged=False, shooter_engaged_with_target=False)
    assert engaged_monster_vehicle_target_malus(_game_state(), "1", "2", _weapon()) is False
    _neutralise(monkeypatch, target_engaged=True, shooter_engaged_with_target=False)
    gs = _game_state(target_keywords=("INFANTRY",))
    assert engaged_monster_vehicle_target_malus(gs, "1", "2", _weapon()) is False
    result = roll_shoot_intent(gs, _intent())
    assert result["engaged_target_malus"] is False and result["bs"] == 3


# ------------------------------------------- ciblage : engagee avec un allie, [BLAST] interdit

def test_un_vehicule_engage_avec_un_allie_reste_ciblable(monkeypatch):
    """`_friendly_engagement_blocks_ranged_shot` refusait toute cible engagee avec un allie du
    tireur (04.02 « Unengaged ») ; 17.03 en excepte les unites MONSTER/VEHICLE."""
    import engine.spatial_relations as spatial
    monkeypatch.setattr(spatial, "unit_entries_within_engagement_zone", lambda a, b, r, game_state=None: True)
    gs = _game_state()
    gs["units_cache"]["3"] = _uc(10, 9, player=0)  # un allie du tireur, engage avec la cible
    blocked = sh._friendly_engagement_blocks_ranged_shot(gs, "1", 0, gs["units_cache"]["2"], "2", False, gs["units_cache"])
    assert blocked is False
    gs_inf = _game_state(target_keywords=("INFANTRY",))
    gs_inf["units_cache"]["3"] = _uc(10, 9, player=0)
    blocked_inf = sh._friendly_engagement_blocks_ranged_shot(gs_inf, "1", 0, gs_inf["units_cache"]["2"], "2", False, gs_inf["units_cache"])
    assert blocked_inf is True, "une unite d infanterie engagee avec un allie reste interdite (04.02)"


def test_blast_ne_peut_pas_viser_un_vehicule_engage(monkeypatch):
    """FAQ p. 88 : [BLAST] ne cible pas une unite MONSTER/VEHICLE engagee, meme ciblable par 17.03."""
    _neutralise(monkeypatch, target_engaged=True, shooter_engaged_with_target=False)
    import engine.spatial_relations as spatial
    monkeypatch.setattr(spatial, "unit_entries_within_engagement_zone", lambda a, b, r, game_state=None: False)
    gs = _game_state()
    shooter_model = gs["models_cache"]["A0"]
    assert su._shoot_engagement_blocks_target(gs, "1", "2", False, shooter_model, True) is True
    assert su._shoot_engagement_blocks_target(gs, "1", "2", False, shooter_model, False) is False
