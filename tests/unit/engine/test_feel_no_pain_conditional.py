"""Feel No Pain conditionnel (passe 3) — Psychic Hood et Unbreakable Resolve.

Invariants verifies :
- _get_feel_no_pain_vs_psychic_threshold : getter, types, bornes
- _get_feel_no_pain_near_objective_threshold : getter, types, bornes
- _collect_fnp_thresholds : PSYCHIC actif/inactif, near_objective actif/inactif
- _collect_fnp_thresholds_mortal : is_psychic flag
- _roll_fnp_sequential : sauvegardes sequentielles multi-seuils
- Integration shoot : arme PSYCHIC + Librarian FNP 4+ vs psychic
- Integration MW : near_objective + allocate_mortal_wounds

Verrou ROUGE/VERT documente pour chaque invariant.
"""

import random

import pytest

import engine.phase_handlers.shared_utils as su
from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.shared_utils import (
    _collect_fnp_thresholds,
    _collect_fnp_thresholds_mortal,
    _get_feel_no_pain_near_objective_threshold,
    _get_feel_no_pain_vs_psychic_threshold,
    _roll_fnp_sequential,
    allocate_mortal_wounds,
    build_manual_shoot_allocation,
)
from tests._state_invariants import turn_state_invariants


# ---------------------------------------------------------------------------
# Fixtures communes
# ---------------------------------------------------------------------------

_PSY_RULE_4 = {
    "ruleId": "feel_no_pain_vs_psychic",
    "displayName": "Psychic Hood (FNP 4+ vs PSYCHIC)",
    "rule_args": {"threshold": 4},
}

_OBJ_RULE_4 = {
    "ruleId": "feel_no_pain_near_objective",
    "displayName": "Unbreakable Resolve (FNP 4+ near obj)",
    "rule_args": {"threshold": 4},
}

_PSYCHIC_WEAPON = {
    "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
    "WEAPON_RULES": ["PSYCHIC"], "code": "smite", "display_name": "Smite",
}

_NORMAL_WEAPON = {
    "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
    "WEAPON_RULES": [], "code": "bolt_rifle", "display_name": "Bolt Rifle",
}


def _minimal_gs():
    """Game state minimal sans spatial : suffisant pour _collect_fnp_thresholds
    quand near_objective est absent ou monkeypatche."""
    return {
        "objectives": [],
        "units_cache": {},
        "inches_to_subhex": 5,
        "board_cols": 30,
        "board_rows": 22,
    }


def _unit(rules):
    return {"id": "U1", "UNIT_RULES": rules}


def _seq(monkeypatch, rolls):
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    return seq


def _shoot_gs(target_unit_rules, weapon):
    """Game state shoot minimal avec l'arme donnee."""
    attacker = {
        "id": "A1", "squad_id": "1", "player": 0, "T": 4,
        "SHOOT_LEFT": 1, "col": 0, "row": 0, "RNG_WEAPONS": [weapon],
    }
    target = {
        "id": "T1", "squad_id": "2", "player": 1, "T": 4,
        "HP_CUR": 1, "HP_MAX": 1, "ARMOR_SAVE": 2, "INVUL_SAVE": 7,
        "role": None, "unitType": "Grunt", "points_per_hp": 5.0, "VALUE": 10.0,
        "col": 9, "row": 9,
    }
    attacker_unit = {"id": "1", "player": 0, "UNIT_RULES": []}
    target_unit = {"id": "2", "player": 1, "UNIT_RULES": target_unit_rules}
    return {
        **turn_state_invariants(),
        "gym_training_mode": True,
        "turn": 1, "phase": "shoot",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": {"A1": attacker, "T1": target},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": 1}},
        "units_cache": {
            "1": {"BASE_SHAPE": "round", "BASE_SIZE": 1, "col": 0, "row": 0,
                  "VALUE": 10.0, "player": 0, "HP_CUR": 1},
            "2": {"BASE_SHAPE": "round", "BASE_SIZE": 1, "col": 9, "row": 9,
                  "VALUE": 10.0, "player": 1, "HP_CUR": 1},
        },
        "units": [attacker_unit, target_unit],
        "unit_by_id": {"1": attacker_unit, "2": target_unit},
        "objectives": [],
        "units_moved": set(), "units_advanced": set(),
        "config": {
            "game_rules": {
                "engagement_zone": 1,
                "engagement_zone_vertical": 5,
                "max_base_size_hex": 35,
                "detection_range": 18,
            },
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "pending_squad_shoot_intents": {
            "1": [{"model_id": "A1", "target_unit_id": "2",
                   "weapon_index": 0, "n_attacks_resolved": 1,
                   "target_squad_size_at_declaration": 1}],
        },
        "inches_to_subhex": 5,
        "board_cols": 30,
        "board_rows": 22,
    }


def _mw_gs(target_unit_rules):
    target = {
        "id": "T1", "squad_id": "2", "player": 1,
        "HP_CUR": 1, "HP_MAX": 1, "col": 5, "row": 5,
    }
    target_unit = {"id": "2", "player": 1, "UNIT_RULES": target_unit_rules}
    return {
        "models_cache": {"T1": target},
        "squad_models": {"2": ["T1"]},
        "squad_cache": {"2": {"model_count_at_start": 1}},
        "units_cache": {},
        "unit_by_id": {"2": target_unit},
        "_unit_move_version": 0,
        "los_cache": {},
        "hex_los_cache": {},
        "_los_pair_cache": {},
        "action_logs": [],
        "action_log_seq": 0,
        "objectives": [],
        "inches_to_subhex": 5,
        "board_cols": 30,
        "board_rows": 22,
    }


# ---------------------------------------------------------------------------
# Getters : _get_feel_no_pain_vs_psychic_threshold
# ---------------------------------------------------------------------------

def test_fnp_vs_psychic_absent():
    """Unité sans feel_no_pain_vs_psychic -> None."""
    assert _get_feel_no_pain_vs_psychic_threshold(_unit([])) is None


def test_fnp_vs_psychic_present():
    """feel_no_pain_vs_psychic threshold 4 -> 4."""
    assert _get_feel_no_pain_vs_psychic_threshold(_unit([_PSY_RULE_4])) == 4


def test_fnp_vs_psychic_mauvais_type():
    """threshold non-int -> TypeError."""
    bad = {"ruleId": "feel_no_pain_vs_psychic", "displayName": "x",
           "rule_args": {"threshold": "4"}}
    with pytest.raises(TypeError, match="threshold.*must be int"):
        _get_feel_no_pain_vs_psychic_threshold(_unit([bad]))


def test_fnp_vs_psychic_hors_bornes():
    """threshold hors 2-6 -> ValueError."""
    bad = {"ruleId": "feel_no_pain_vs_psychic", "displayName": "x",
           "rule_args": {"threshold": 1}}
    with pytest.raises(ValueError, match="must be 2-6"):
        _get_feel_no_pain_vs_psychic_threshold(_unit([bad]))


# ---------------------------------------------------------------------------
# Getters : _get_feel_no_pain_near_objective_threshold
# ---------------------------------------------------------------------------

def test_fnp_near_objective_absent():
    """Unité sans feel_no_pain_near_objective -> None."""
    assert _get_feel_no_pain_near_objective_threshold(_unit([])) is None


def test_fnp_near_objective_present():
    """feel_no_pain_near_objective threshold 4 -> 4."""
    assert _get_feel_no_pain_near_objective_threshold(_unit([_OBJ_RULE_4])) == 4


def test_fnp_near_objective_hors_bornes():
    """threshold hors 2-6 -> ValueError."""
    bad = {"ruleId": "feel_no_pain_near_objective", "displayName": "x",
           "rule_args": {"threshold": 7}}
    with pytest.raises(ValueError, match="must be 2-6"):
        _get_feel_no_pain_near_objective_threshold(_unit([bad]))


# ---------------------------------------------------------------------------
# _collect_fnp_thresholds : PSYCHIC condition
# ---------------------------------------------------------------------------

def test_collect_fnp_psychic_weapon_ajoute_seuil(monkeypatch):
    """Arme PSYCHIC + rule feel_no_pain_vs_psychic -> seuil inclus."""
    monkeypatch.setattr(su, "_unit_is_near_objective_or_center", lambda gs, u: False)
    gs = _minimal_gs()
    unit = _unit([_PSY_RULE_4])
    result = _collect_fnp_thresholds(unit, gs, _PSYCHIC_WEAPON)
    assert 4 in result, "seuil PSYCHIC attendu avec arme PSYCHIC"


def test_collect_fnp_arme_normale_nactive_pas_seuil_psychic(monkeypatch):
    """Arme normale + rule feel_no_pain_vs_psychic -> seuil absent."""
    monkeypatch.setattr(su, "_unit_is_near_objective_or_center", lambda gs, u: False)
    gs = _minimal_gs()
    unit = _unit([_PSY_RULE_4])
    result = _collect_fnp_thresholds(unit, gs, _NORMAL_WEAPON)
    assert 4 not in result, "seuil PSYCHIC absent pour arme non-PSYCHIC"


def test_collect_fnp_near_objective_ajoute_seuil(monkeypatch):
    """Unité près d'un objectif + rule feel_no_pain_near_objective -> seuil inclus."""
    monkeypatch.setattr(su, "_unit_is_near_objective_or_center", lambda gs, u: True)
    gs = _minimal_gs()
    unit = _unit([_OBJ_RULE_4])
    result = _collect_fnp_thresholds(unit, gs, _NORMAL_WEAPON)
    assert 4 in result


def test_collect_fnp_loin_objectif_nactive_pas_seuil(monkeypatch):
    """Unité loin des objectifs -> seuil near_objective absent."""
    monkeypatch.setattr(su, "_unit_is_near_objective_or_center", lambda gs, u: False)
    gs = _minimal_gs()
    unit = _unit([_OBJ_RULE_4])
    result = _collect_fnp_thresholds(unit, gs, _NORMAL_WEAPON)
    assert 4 not in result


# ---------------------------------------------------------------------------
# _collect_fnp_thresholds_mortal : is_psychic flag
# ---------------------------------------------------------------------------

def test_collect_fnp_mortal_psychic_flag_actif(monkeypatch):
    """is_psychic=True + rule feel_no_pain_vs_psychic -> seuil inclus."""
    monkeypatch.setattr(su, "_unit_is_near_objective_or_center", lambda gs, u: False)
    gs = _minimal_gs()
    unit = _unit([_PSY_RULE_4])
    result = _collect_fnp_thresholds_mortal(unit, gs, is_psychic=True)
    assert 4 in result


def test_collect_fnp_mortal_psychic_flag_inactif(monkeypatch):
    """is_psychic=False + rule feel_no_pain_vs_psychic -> seuil absent."""
    monkeypatch.setattr(su, "_unit_is_near_objective_or_center", lambda gs, u: False)
    gs = _minimal_gs()
    unit = _unit([_PSY_RULE_4])
    result = _collect_fnp_thresholds_mortal(unit, gs, is_psychic=False)
    assert 4 not in result


# ---------------------------------------------------------------------------
# _roll_fnp_sequential
# ---------------------------------------------------------------------------

def test_roll_fnp_sequential_sauve_un_seul_seuil(monkeypatch):
    """Jet 5, seuil [5] -> 0 blessure restante."""
    monkeypatch.setattr(random, "randint", lambda a, b: 5)
    assert _roll_fnp_sequential(1, [5]) == 0


def test_roll_fnp_sequential_echoue_un_seul_seuil(monkeypatch):
    """Jet 4, seuil [5] -> 1 blessure restante."""
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    assert _roll_fnp_sequential(1, [5]) == 1


def test_roll_fnp_sequential_deux_seuils_premier_sauve(monkeypatch):
    """Jet 4, seuils [4, 6] : premier seuil 4 sauve -> 0 blessure restante."""
    seq = [4]

    def fake(a, b):
        return seq.pop(0) if seq else 1

    monkeypatch.setattr(random, "randint", fake)
    assert _roll_fnp_sequential(1, [4, 6]) == 0


def test_roll_fnp_sequential_deux_seuils_deuxieme_sauve(monkeypatch):
    """Jets 3 puis 5, seuils [4, 5] : premier echoue, deuxieme sauve -> 0 blessure."""
    seq = [3, 5]

    def fake(a, b):
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    assert _roll_fnp_sequential(1, [4, 5]) == 0


def test_roll_fnp_sequential_deux_seuils_les_deux_echouent(monkeypatch):
    """Jets 3 puis 2, seuils [4, 5] : aucun ne sauve -> 1 blessure restante."""
    seq = [3, 2]

    def fake(a, b):
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    assert _roll_fnp_sequential(1, [4, 5]) == 1


# ---------------------------------------------------------------------------
# Integration shoot : arme PSYCHIC + FNP vs psychic
# ---------------------------------------------------------------------------

def test_shoot_fnp_vs_psychic_sauve(monkeypatch):
    """Arme PSYCHIC, Sv2+, jets : tous ratent la save (1), FNP 4+ reussit (4).
    Cible HP1 : survit."""
    # Save 2+ : jet 1 -> rate. FNP 4+ : jet 4 -> sauve.
    _seq(monkeypatch, [
        3,  # touche (hit) : 3 >= 3+ -> touche
        4,  # blesse (wound) : 4 vs T4 S4 -> 4+ -> 4 >= 4 -> blesse
        1,  # save 2+ : jet 1 -> rate (alloc dmg)
        4,  # FNP 4+ : jet 4 -> sauve
    ])
    gs = _shoot_gs([_PSY_RULE_4], _PSYCHIC_WEAPON)
    results = build_manual_shoot_allocation(gs, "1")
    # Si FNP sauve, HP reste a 1
    assert gs["models_cache"]["T1"]["HP_CUR"] == 1, "FNP 4+ vs PSYCHIC doit sauver la blessure"


def test_shoot_fnp_vs_psychic_echoue(monkeypatch):
    """Arme PSYCHIC, Sv2+, FNP 4+ rate -> figurine detruite (retiree du cache)."""
    _seq(monkeypatch, [
        3,  # touche
        4,  # blesse
        1,  # save rate
        3,  # FNP 4+ rate (3 < 4)
    ])
    gs = _shoot_gs([_PSY_RULE_4], _PSYCHIC_WEAPON)
    build_manual_shoot_allocation(gs, "1")
    assert gs["models_cache"].get("T1") is None, "FNP rate -> figurine detruite"


def test_shoot_fnp_vs_psychic_inactif_arme_normale(monkeypatch):
    """Arme normale : FNP vs PSYCHIC ne s active pas -> figurine detruite sans jet FNP."""
    # Save 2+ rate, pas de FNP -> blessure appliquee directement, 3 jets suffisent
    _seq(monkeypatch, [
        3,  # touche
        4,  # blesse
        1,  # save rate -> dmg immediat
    ])
    gs = _shoot_gs([_PSY_RULE_4], _NORMAL_WEAPON)
    build_manual_shoot_allocation(gs, "1")
    assert gs["models_cache"].get("T1") is None, "FNP vs PSYCHIC inactif : figurine detruite"


# ---------------------------------------------------------------------------
# Integration MW : near_objective + allocate_mortal_wounds
# ---------------------------------------------------------------------------

def test_mw_fnp_near_objective_sauve(monkeypatch):
    """FNP 4+ near_objective actif, jet 4 -> MW sauvee, fnpSaved=True dans details."""
    monkeypatch.setattr(su, "_unit_is_near_objective_or_center", lambda gs, u: True)
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    gs = _mw_gs([_OBJ_RULE_4])
    details: list = []
    applied = allocate_mortal_wounds(gs, "2", 1, auto_resolve=True, details_sink=details)
    assert applied == 0, "MW sauvee par FNP near_objective"
    assert len(details) == 1 and details[0].get("fnpSaved") is True


def test_mw_fnp_near_objective_echoue(monkeypatch):
    """FNP 4+ near_objective actif, jet 3 -> MW appliquee."""
    monkeypatch.setattr(su, "_unit_is_near_objective_or_center", lambda gs, u: True)
    monkeypatch.setattr(random, "randint", lambda a, b: 3)
    gs = _mw_gs([_OBJ_RULE_4])
    details: list = []
    applied = allocate_mortal_wounds(gs, "2", 1, auto_resolve=True, details_sink=details)
    assert applied == 1, "FNP rate -> MW appliquee"


def test_mw_fnp_near_objective_inactif(monkeypatch):
    """FNP near_objective inactif (loin) -> aucun jet FNP, MW appliquee meme avec jet 6."""
    monkeypatch.setattr(su, "_unit_is_near_objective_or_center", lambda gs, u: False)
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    gs = _mw_gs([_OBJ_RULE_4])
    details: list = []
    applied = allocate_mortal_wounds(gs, "2", 1, auto_resolve=True, details_sink=details)
    assert applied == 1, "FNP near_objective inactif : MW non bloquee"
