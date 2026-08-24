"""Feel No Pain (24.12) — jets par HP perdu, moteur vif.

Regle : chaque fois qu un modele perdrait une blessure, jet D6 ; sur threshold+, la blessure
est ignoree. S applique apres la sauvegarde et apres DEVASTATING_WOUNDS (blessures mortelles).

Tests bout-en-bout via build_manual_shoot_allocation en gym_training_mode (auto-resolu) et
via allocate_mortal_wounds. RNG force par monkeypatch.

Verrou ROUGE verifie sur chaque invariant : le defaut (sans FNP) est restaure et le test
bascule rouge, puis l invariant est retabli.
"""
import random

import pytest

from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.shared_utils import (
    _get_feel_no_pain_threshold,
    _roll_feel_no_pain,
    allocate_mortal_wounds,
    build_manual_shoot_allocation,
)
from tests._state_invariants import turn_state_invariants


# ---------------------------------------------------------------------------
# Fixtures communes
# ---------------------------------------------------------------------------

_FNP_5_RULE = {
    "ruleId": "feel_no_pain",
    "displayName": "Feel No Pain 5+",
    "rule_args": {"threshold": 5},
}

_FNP_6_RULE = {
    "ruleId": "feel_no_pain",
    "displayName": "Feel No Pain 6+",
    "rule_args": {"threshold": 6},
}


def _seq(monkeypatch, rolls):
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee : le code a tire plus de des que prevu"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    return seq


def _game_state(target_unit_rules, *, dmg=1, hp=3, sv=2):
    """Tireur '1' (arme S4, AP0, DMGdmg) vs cible '2' (Sv sv+, T4, HPmax=hp). gym -> auto."""
    weapon = {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": dmg, "NB": 1,
        "WEAPON_RULES": [], "code": "test_gun", "display_name": "Gun",
    }
    attacker = {
        "id": "A1", "squad_id": "1", "player": 0, "T": 4,
        "SHOOT_LEFT": 1, "col": 0, "row": 0, "RNG_WEAPONS": [weapon],
    }
    target = {
        "id": "T1", "squad_id": "2", "player": 1, "T": 4,
        "HP_CUR": hp, "HP_MAX": hp, "ARMOR_SAVE": sv, "INVUL_SAVE": 7,
        "role": None, "unitType": "Grunt", "points_per_hp": 5.0, "VALUE": 10.0,
        "col": 9, "row": 9,
    }
    attacker_unit = {"id": "1", "player": 0, "UNIT_RULES": []}
    target_unit = {"id": "2", "player": 1, "UNIT_RULES": target_unit_rules}
    gs = {
        **turn_state_invariants(),
        "gym_training_mode": True,
        "turn": 1, "phase": "shoot",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": {"A1": attacker, "T1": target},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": 1}},
        "units_cache": {
            "1": {"BASE_SHAPE": "round", "BASE_SIZE": 1, "col": 0, "row": 0,
                  "VALUE": 10.0, "player": 0},
            "2": {"BASE_SHAPE": "round", "BASE_SIZE": 1, "col": 9, "row": 9,
                  "VALUE": 10.0, "player": 1},
        },
        "units": [attacker_unit, target_unit],
        "unit_by_id": {"1": attacker_unit, "2": target_unit},
        "objectives": [],
        "units_moved": set(), "units_advanced": set(),
        "pending_squad_shoot_intents": {
            "1": [{"model_id": "A1", "target_unit_id": "2",
                   "weapon_index": 0, "n_attacks_resolved": 1,
                   "target_squad_size_at_declaration": 1}],
        },
    }
    return gs


def _mw_game_state(target_unit_rules, *, hp=3):
    """État minimal pour allocate_mortal_wounds sur l unité '2' (1 figurine HP1)."""
    target = {
        "id": "T1", "squad_id": "2", "player": 1,
        "HP_CUR": 1, "HP_MAX": 1, "col": 5, "row": 5,
    }
    target_unit = {"id": "2", "player": 1, "UNIT_RULES": target_unit_rules}
    gs = {
        "models_cache": {"T1": target},
        "squad_models": {"2": ["T1"]},
        "squad_cache": {"2": {"model_count_at_start": 1}},
        "units_cache": {},
        "unit_by_id": {"2": target_unit},
        # Champs d infrastructure requis par destroy_model -> _touch_unit_los
        "_unit_move_version": 0,
        "los_cache": {},
        "hex_los_cache": {},
        "_los_pair_cache": {},
        # destroy_model émet un event "dead" via append_action_log → action_log_seq requis.
        "action_logs": [],
        "action_log_seq": 0,
    }
    return gs


# ---------------------------------------------------------------------------
# Helpers unitaires
# ---------------------------------------------------------------------------

def test_get_fnp_threshold_absent():
    """Unité sans FNP -> None."""
    unit = {"id": "X", "UNIT_RULES": []}
    assert _get_feel_no_pain_threshold(unit) is None


def test_get_fnp_threshold_present():
    """FNP 5+ -> threshold == 5."""
    unit = {"id": "X", "UNIT_RULES": [_FNP_5_RULE]}
    assert _get_feel_no_pain_threshold(unit) == 5


def test_get_fnp_threshold_6():
    """FNP 6+ -> threshold == 6."""
    unit = {"id": "X", "UNIT_RULES": [_FNP_6_RULE]}
    assert _get_feel_no_pain_threshold(unit) == 6


def test_get_fnp_threshold_mauvais_type():
    """threshold non-int -> TypeError."""
    bad_rule = {"ruleId": "feel_no_pain", "displayName": "Bad FNP",
                "rule_args": {"threshold": "5"}}
    unit = {"id": "X", "UNIT_RULES": [bad_rule]}
    with pytest.raises(TypeError, match="threshold.*must be int"):
        _get_feel_no_pain_threshold(unit)


def test_get_fnp_threshold_hors_bornes():
    """threshold hors 2-6 -> ValueError."""
    bad_rule = {"ruleId": "feel_no_pain", "displayName": "Bad FNP",
                "rule_args": {"threshold": 1}}
    unit = {"id": "X", "UNIT_RULES": [bad_rule]}
    with pytest.raises(ValueError, match="threshold must be 2-6"):
        _get_feel_no_pain_threshold(unit)


def test_roll_fnp_tous_sauves(monkeypatch):
    """3 jets >= 5 : 0 blessures restantes."""
    monkeypatch.setattr(random, "randint", lambda a, b: 5)
    assert _roll_feel_no_pain(3, 5) == 0


def test_roll_fnp_aucun_sauve(monkeypatch):
    """3 jets < 5 : 3 blessures restantes."""
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    assert _roll_feel_no_pain(3, 5) == 3


def test_roll_fnp_partiel(monkeypatch):
    """Jets alternés 5 / 4 / 5 -> 1 blessure restante."""
    seq = [5, 4, 5]
    monkeypatch.setattr(random, "randint", lambda a, b: seq.pop(0))
    assert _roll_feel_no_pain(3, 5) == 1


# ---------------------------------------------------------------------------
# Tir : FNP sur dégâts normaux
# ---------------------------------------------------------------------------

def test_fnp_sauve_toute_la_blessure(monkeypatch):
    """FNP 5+ : jet 5 (>= 5) sauve la seule blessure -> 0 dégât, HP inchangé."""
    # hit=4, wound=4 (wth=4, S4 vs T4), save=1 (fail), FNP=5 (sauvée)
    seq = _seq(monkeypatch, [4, 4, 1, 5])
    gs = _game_state([_FNP_5_RULE], dmg=1, hp=3)

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["T1"]["HP_CUR"] == 3, "FNP 5 sauve la blessure"
    assert seq == [], "4 jets exacts attendus"


def test_fnp_echoue_inflige_la_blessure(monkeypatch):
    """FNP 5+ : jet 4 (< 5) échoue -> 1 dégât infligé."""
    seq = _seq(monkeypatch, [4, 4, 1, 4])
    gs = _game_state([_FNP_5_RULE], dmg=1, hp=3)

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["T1"]["HP_CUR"] == 2, "FNP 4 échoue -> 1 dégât"
    assert seq == []


def test_fnp_partiel_dmg3(monkeypatch):
    """FNP 5+ sur DMG=3 : jets [5, 4, 5] -> 1 blessure restante sur 3."""
    # hit=4, wound=4, save=1, FNP_1=5 (saved), FNP_2=4 (fail), FNP_3=5 (saved)
    seq = _seq(monkeypatch, [4, 4, 1, 5, 4, 5])
    gs = _game_state([_FNP_5_RULE], dmg=3, hp=5)

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["T1"]["HP_CUR"] == 4, "1 HP perdu sur 3 dégâts bruts"
    assert seq == []


def test_sans_fnp_3_degats_appliques(monkeypatch):
    """Verrou rouge : sans FNP, les 3 dégâts sont intégralement appliqués."""
    seq = _seq(monkeypatch, [4, 4, 1])  # hit, wound, save — pas de jets FNP
    gs = _game_state([], dmg=3, hp=5)

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["T1"]["HP_CUR"] == 2, "sans FNP : 3 dégâts -> HP 5->2"
    assert seq == [], "3 jets exacts (pas de jet FNP)"


def test_fnp_6plus_plus_permissif(monkeypatch):
    """FNP 6+ : jet 5 (< 6) échoue -> 1 dégât ; jet 6 (>= 6) sauve."""
    # FNP 6+ : seul un 6 sauve -> jet 5 ne sauve pas
    seq = _seq(monkeypatch, [4, 4, 1, 5])
    gs = _game_state([_FNP_6_RULE], dmg=1, hp=3)

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["T1"]["HP_CUR"] == 2, "FNP 6+ : jet 5 n épargne pas"
    assert seq == []


def test_save_reussie_pas_de_jet_fnp(monkeypatch):
    """Save réussie -> aucun dégât, aucun jet FNP (séquence de 3 jets seulement)."""
    # hit=4, wound=4, save=2 (réussit sur Sv2+) -> arrêt, 0 jet FNP
    seq = _seq(monkeypatch, [4, 4, 2])
    gs = _game_state([_FNP_5_RULE], dmg=1, hp=3, sv=2)

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["T1"]["HP_CUR"] == 3, "save réussie -> HP inchangé"
    assert seq == [], "3 jets : pas de FNP si save réussit"


# ---------------------------------------------------------------------------
# Blessures mortelles : allocate_mortal_wounds
# ---------------------------------------------------------------------------

def test_fnp_sauve_blessure_mortelle(monkeypatch):
    """FNP 5+ sur 1 MW : jet 5 -> blessure ignorée, figurine intacte."""
    monkeypatch.setattr(random, "randint", lambda a, b: 5)
    gs = _mw_game_state([_FNP_5_RULE])
    details: list = []

    applied = allocate_mortal_wounds(gs, "2", 1, auto_resolve=True, details_sink=details)

    assert applied == 0, "MW sauvée par FNP : rien d appliqué"
    assert gs["models_cache"]["T1"]["HP_CUR"] == 1, "figurine intacte"
    assert details == [], "aucun record (MW sauvée avant consommation)"


def test_fnp_echoue_applique_blessure_mortelle(monkeypatch):
    """FNP 5+ sur 1 MW : jet 4 -> blessure appliquée, figurine détruite (HP1)."""
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    gs = _mw_game_state([_FNP_5_RULE])
    details: list = []

    applied = allocate_mortal_wounds(gs, "2", 1, auto_resolve=True, details_sink=details)

    assert applied == 1, "MW non sauvée : 1 appliquée"
    assert "T1" not in gs["models_cache"], "figurine HP1 détruite"
    assert len(details) == 1 and details[0]["died"] is True


def test_sans_fnp_mw_appliquee_directement(monkeypatch):
    """Verrou rouge : sans FNP, la MW est appliquée sans jet."""
    rolled = []
    original = random.randint

    def track(a, b):
        rolled.append(b)
        return 4  # valeur quelconque

    monkeypatch.setattr(random, "randint", track)
    gs = _mw_game_state([])  # aucune règle FNP
    details: list = []

    applied = allocate_mortal_wounds(gs, "2", 1, auto_resolve=True, details_sink=details)

    assert applied == 1, "MW appliquée directement sans FNP"
    assert rolled == [], "aucun jet lancé sans FNP"
