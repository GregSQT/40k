"""Feel No Pain conditionnel (passe 3) — Psychic Hood et Unbreakable Resolve.

Invariants verifies :
- _get_feel_no_pain_vs_psychic_threshold : getter, types, bornes
- _get_feel_no_pain_near_objective_threshold : getter, types, bornes
- _collect_fnp_thresholds : PSYCHIC actif/inactif, near_objective actif/inactif
- _collect_fnp_thresholds_mortal : is_psychic flag
- « Within range of an objective » = socle DANS l'aire de terrain (14.02), jamais une distance
  de 3" ; seul le centre est une distance (6")
- Portée FIGURINE d'Unbreakable Resolve (« While THIS MODEL … IT has Feel No Pain 4+ », 19.04
  première clause) : le seuil ne vaut que pour la figurine qui porte la règle, à SA position —
  jamais pour un Intercessor de l'escouade que l'Ancient mène (l'union 19.04 la porte pourtant)
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


def _minimal_gs(model_rules=()):
    """Game state minimal sans spatial : suffisant pour _collect_fnp_thresholds
    quand near_objective est absent ou monkeypatche. La figurine blessée `T1` porte
    `model_rules` en propre (règles de SA datasheet, ce que lit near_objective)."""
    return {
        "objectives": [],
        "units_cache": {},
        "models_cache": {"T1": {"squad_id": "U1", "UNIT_RULES": list(model_rules)}},
        "squad_models": {"U1": ["T1"]},
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
        "col": 9, "row": 9, "UNIT_RULES": target_unit_rules,
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
        "HP_CUR": 1, "HP_MAX": 1, "col": 5, "row": 5, "UNIT_RULES": target_unit_rules,
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
    monkeypatch.setattr(su, "_model_is_near_objective_or_center", lambda gs, mid: False)
    gs = _minimal_gs([_PSY_RULE_4])
    unit = _unit([_PSY_RULE_4])
    result = _collect_fnp_thresholds(unit, gs, _PSYCHIC_WEAPON, model_id="T1")
    assert 4 in result, "seuil PSYCHIC attendu avec arme PSYCHIC"


def test_collect_fnp_arme_normale_nactive_pas_seuil_psychic(monkeypatch):
    """Arme normale + rule feel_no_pain_vs_psychic -> seuil absent."""
    monkeypatch.setattr(su, "_model_is_near_objective_or_center", lambda gs, mid: False)
    gs = _minimal_gs([_PSY_RULE_4])
    unit = _unit([_PSY_RULE_4])
    result = _collect_fnp_thresholds(unit, gs, _NORMAL_WEAPON, model_id="T1")
    assert 4 not in result, "seuil PSYCHIC absent pour arme non-PSYCHIC"


def test_collect_fnp_near_objective_ajoute_seuil(monkeypatch):
    """Figurine porteuse près d'un objectif + rule feel_no_pain_near_objective -> seuil inclus."""
    monkeypatch.setattr(su, "_model_is_near_objective_or_center", lambda gs, mid: True)
    gs = _minimal_gs([_OBJ_RULE_4])
    unit = _unit([_OBJ_RULE_4])
    result = _collect_fnp_thresholds(unit, gs, _NORMAL_WEAPON, model_id="T1")
    assert 4 in result


def test_collect_fnp_loin_objectif_nactive_pas_seuil(monkeypatch):
    """Figurine porteuse loin des objectifs -> seuil near_objective absent."""
    monkeypatch.setattr(su, "_model_is_near_objective_or_center", lambda gs, mid: False)
    gs = _minimal_gs([_OBJ_RULE_4])
    unit = _unit([_OBJ_RULE_4])
    result = _collect_fnp_thresholds(unit, gs, _NORMAL_WEAPON, model_id="T1")
    assert 4 not in result


def test_collect_fnp_near_objective_figurine_sans_la_regle_pas_de_seuil(monkeypatch):
    """Unbreakable Resolve dans l'UNION de l'escouade (Ancient replié) mais pas sur la figurine
    blessée (Intercessor) -> aucun seuil, même à portée d'un objectif (19.04, 1re clause)."""
    monkeypatch.setattr(su, "_model_is_near_objective_or_center", lambda gs, mid: True)
    gs = _minimal_gs([])
    unit = _unit([_OBJ_RULE_4])
    result = _collect_fnp_thresholds(unit, gs, _NORMAL_WEAPON, model_id="T1")
    assert result == [], "l'Intercessor ne porte pas Unbreakable Resolve : aucun FNP"


def _ancient_gs(col, row):
    """Ancient `T1` seul (socle 1 hexe, règle en propre) posé en (col,row) ; plateau 100x100
    (centre (50,50)), ish=5 (hérité de `_minimal_gs`), une aire d'objectif réduite à (10,10).
    L'entrée `units_cache` ne porte que l'orientation : c'est la seule clé que lit
    `iter_living_models_with_footprints`."""
    gs = _minimal_gs([_OBJ_RULE_4])
    gs["board_cols"], gs["board_rows"] = 100, 100
    gs["objectives"] = [{"id": "o1", "hexes": [[10, 10]]}]
    gs["units_cache"] = {"U1": {"orientation": 0}}
    gs["models_cache"] = {"T1": {"squad_id": "U1", "UNIT_RULES": [_OBJ_RULE_4], "HP_CUR": 1,
                                 "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
                                 "col": col, "row": row}}
    return gs


def test_collect_fnp_near_objective_position_de_la_figurine_pas_de_l_escouade():
    """Le prédicat de position est celui de la FIGURINE blessée : l'Ancient loin de tout objectif
    n'a pas de FNP même si l'escouade en touche un (l'Intercessor `T2` est DANS l'aire)."""
    gs = _ancient_gs(90, 90)   # Ancient loin de tout
    gs["models_cache"]["T2"] = {"squad_id": "U1", "UNIT_RULES": [], "HP_CUR": 1, "col": 10, "row": 10,
                                "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0}
    gs["squad_models"]["U1"].append("T2")
    unit = _unit([_OBJ_RULE_4])
    assert _collect_fnp_thresholds(unit, gs, _NORMAL_WEAPON, model_id="T1") == [], "Ancient loin : pas de FNP"
    assert _collect_fnp_thresholds(unit, gs, _NORMAL_WEAPON, model_id="T2") == [], "Intercessor : jamais"
    gs["models_cache"]["T1"]["col"], gs["models_cache"]["T1"]["row"] = 10, 10   # Ancient DANS l'aire de l'objectif
    assert _collect_fnp_thresholds(unit, gs, _NORMAL_WEAPON, model_id="T1") == [4], "Ancient à portée : FNP 4+"


def test_near_objective_exige_le_recouvrement_de_l_aire_pas_une_distance_de_3_pouces():
    """14.02 : « A model is within range of a terrain objective while it is within that terrain
    area ». Un Ancient à UN subhex hors de l'aire n'est pas à portée — le même état le dit
    hors objectif pour le contrôle (`unit_is_within_objective`). VERROU : remettre la lecture
    `min_distance ≤ 3"` rend le cas « 1 subhex hors de l'aire » vrai → rouge."""
    assert su._model_is_near_objective_or_center(_ancient_gs(10, 10), "T1") is True, "dans l'aire"
    assert su._model_is_near_objective_or_center(_ancient_gs(10, 11), "T1") is False, "1 subhex hors de l'aire"
    assert su._model_is_near_objective_or_center(_ancient_gs(10, 24), "T1") is False, "14 subhex (< 3\")"
    from engine.game_state import unit_is_within_objective
    assert unit_is_within_objective(_ancient_gs(10, 11), "U1") is False, "montage : même verdict que 14.02 contrôle"


def test_near_objective_le_centre_reste_une_distance_de_6_pouces():
    """« within 6" of the centre of the battlefield » est une DISTANCE : 30 subhex à ish=5.
    Plateau 100x100 → centre (50,50)."""
    assert su._model_is_near_objective_or_center(_ancient_gs(50, 50), "T1") is True, "sur le centre"
    assert su._model_is_near_objective_or_center(_ancient_gs(50, 80), "T1") is True, "à 30 subhex = 6\""
    assert su._model_is_near_objective_or_center(_ancient_gs(50, 81), "T1") is False, "à 31 subhex > 6\""


# ---------------------------------------------------------------------------
# _collect_fnp_thresholds_mortal : is_psychic flag
# ---------------------------------------------------------------------------

def test_collect_fnp_mortal_psychic_flag_actif(monkeypatch):
    """is_psychic=True + rule feel_no_pain_vs_psychic -> seuil inclus."""
    monkeypatch.setattr(su, "_model_is_near_objective_or_center", lambda gs, mid: False)
    gs = _minimal_gs([_PSY_RULE_4])
    unit = _unit([_PSY_RULE_4])
    result = _collect_fnp_thresholds_mortal(unit, gs, is_psychic=True, model_id="T1")
    assert 4 in result


def test_collect_fnp_mortal_psychic_flag_inactif(monkeypatch):
    """is_psychic=False + rule feel_no_pain_vs_psychic -> seuil absent."""
    monkeypatch.setattr(su, "_model_is_near_objective_or_center", lambda gs, mid: False)
    gs = _minimal_gs([_PSY_RULE_4])
    unit = _unit([_PSY_RULE_4])
    result = _collect_fnp_thresholds_mortal(unit, gs, is_psychic=False, model_id="T1")
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
    monkeypatch.setattr(su, "_model_is_near_objective_or_center", lambda gs, mid: True)
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    gs = _mw_gs([_OBJ_RULE_4])
    details: list = []
    applied = allocate_mortal_wounds(gs, "2", 1, auto_resolve=True, details_sink=details)
    assert applied == 0, "MW sauvee par FNP near_objective"
    assert len(details) == 1 and details[0].get("fnpSaved") is True


def test_mw_fnp_near_objective_echoue(monkeypatch):
    """FNP 4+ near_objective actif, jet 3 -> MW appliquee."""
    monkeypatch.setattr(su, "_model_is_near_objective_or_center", lambda gs, mid: True)
    monkeypatch.setattr(random, "randint", lambda a, b: 3)
    gs = _mw_gs([_OBJ_RULE_4])
    details: list = []
    applied = allocate_mortal_wounds(gs, "2", 1, auto_resolve=True, details_sink=details)
    assert applied == 1, "FNP rate -> MW appliquee"


def test_mw_fnp_near_objective_inactif(monkeypatch):
    """FNP near_objective inactif (loin) -> aucun jet FNP, MW appliquee meme avec jet 6."""
    monkeypatch.setattr(su, "_model_is_near_objective_or_center", lambda gs, mid: False)
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    gs = _mw_gs([_OBJ_RULE_4])
    details: list = []
    applied = allocate_mortal_wounds(gs, "2", 1, auto_resolve=True, details_sink=details)
    assert applied == 1, "FNP near_objective inactif : MW non bloquee"


def test_mw_seuils_calcules_une_fois_par_figurine_allouee(monkeypatch):
    """`allocate_mortal_wounds` : les seuils FNP sont ceux de la figurine ALLOUÉE, calculés une
    fois par figurine et non par blessure. Ancient `T1` (règle en propre, jet 6 → sauve tout)
    encaisse 3 MW : une seule collecte, 0 appliquée. VERROU : une collecte par blessure → 3."""
    monkeypatch.setattr(su, "_model_is_near_objective_or_center", lambda gs, mid: True)
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    calls: list = []
    real = su._collect_fnp_thresholds_mortal
    monkeypatch.setattr(
        su, "_collect_fnp_thresholds_mortal",
        lambda *a, **k: calls.append(k["model_id"]) or real(*a, **k),
    )
    gs = _mw_gs([_OBJ_RULE_4])
    applied = allocate_mortal_wounds(gs, "2", 3, auto_resolve=True, details_sink=[])
    assert applied == 0 and calls == ["T1"], f"une collecte pour 3 MW sur la même figurine, obtenu {calls}"


def test_mw_seuils_recalcules_quand_la_figurine_allouee_change(monkeypatch):
    """Ancient `T1` (FNP en propre, 1 PV) rate son jet et meurt à la 1re MW ; l'Intercessor `T2`
    (aucune règle) encaisse les 2 suivantes SANS jet : les seuils sont recollectés pour lui.
    VERROU : seuils figés sur la première figurine → `T2` jetterait un FNP 4+ et le jet 4 le sauverait."""
    monkeypatch.setattr(su, "_model_is_near_objective_or_center", lambda gs, mid: True)
    rolls = iter([3, 4, 4])   # T1 rate (3) ; si T2 jetait à tort, 4 sauverait
    monkeypatch.setattr(random, "randint", lambda a, b: next(rolls))
    calls: list = []
    real = su._collect_fnp_thresholds_mortal
    monkeypatch.setattr(
        su, "_collect_fnp_thresholds_mortal",
        lambda *a, **k: calls.append(k["model_id"]) or real(*a, **k),
    )
    gs = _mw_gs([_OBJ_RULE_4])
    gs["models_cache"]["T2"] = {"id": "T2", "squad_id": "2", "player": 1, "HP_CUR": 2, "HP_MAX": 2,
                                "col": 6, "row": 5, "UNIT_RULES": []}
    gs["squad_models"]["2"].append("T2")
    gs["squad_cache"]["2"]["model_count_at_start"] = 2
    details: list = []
    applied = allocate_mortal_wounds(gs, "2", 3, auto_resolve=True, details_sink=details)
    assert applied == 3, f"T1 rate, T2 sans FNP : 3 MW appliquées, obtenu {applied}"
    assert [d["modelId"] for d in details] == ["T1", "T2", "T2"]
    assert calls == ["T1", "T2"], f"une collecte par figurine allouée, obtenu {calls}"


# ---------------------------------------------------------------------------
# Chemin de production : Ancient replié inline dans des Intercessors (fold 19.04 réel)
# ---------------------------------------------------------------------------

def test_unbreakable_resolve_ancient_inline_ne_couvre_que_l_ancient():
    """Armée d'entraînement : l'Ancient est un modèle inline de l'escouade Intercessor. L'union
    19.04 porte feel_no_pain_near_objective ; seul l'Ancient, à portée d'un objectif, a le seuil."""
    from tests.unit.engine._config_helpers import load_engine_from_scenario
    scenario = {
        "board_ref": "44x60x5",
        "primary_objectives": ["objectives_control"],
        "wall_ref": "walls-none.json",
        "army_faction": {"1": "ADEPTUS ASTARTES", "2": "ORKS"},
        "uses_codex_detachment": {"1": True, "2": True},
        "units": [
            {
                "id": 1, "unit_type": "Intercessor", "player": 1, "col": 10, "row": 10,
                "models": [{"col": 10, "row": 10}, {"col": 11, "row": 10},
                           {"unit_type": "Ancient", "col": 40, "row": 40}],
            },
            {"id": 101, "unit_type": "Boyz", "player": 2, "col": 30, "row": 55},
        ],
    }
    engine = load_engine_from_scenario(scenario)
    gs = engine.game_state
    unit = gs["unit_by_id"]["1"]
    assert any(r["ruleId"] == "feel_no_pain_near_objective" for r in unit["UNIT_RULES"]), "union 19.04 attendue"
    mc = gs["models_cache"]
    ancient = next(m for m in gs["squad_models"]["1"] if mc[m].get("unitType") == "Ancient")
    intercessor = next(m for m in gs["squad_models"]["1"] if mc[m].get("unitType") != "Ancient")
    # Objectif à côté des Intercessors, loin de l'Ancient (et loin du centre pour tous).
    gs["objectives"] = [{"id": "o1", "hexes": [[10, 11]]}]
    assert _collect_fnp_thresholds(unit, gs, _NORMAL_WEAPON, model_id=intercessor) == []
    assert _collect_fnp_thresholds(unit, gs, _NORMAL_WEAPON, model_id=ancient) == []
    # Aire d'objectif SOUS l'Ancient : lui seul gagne FNP 4+.
    gs["objectives"] = [{"id": "o1", "hexes": [[40, 40]]}]
    assert _collect_fnp_thresholds(unit, gs, _NORMAL_WEAPON, model_id=intercessor) == []
    assert _collect_fnp_thresholds(unit, gs, _NORMAL_WEAPON, model_id=ancient) == [4]
    # Aire à UN subhex du socle de l'Ancient (40 mm à ish=5 : rows 37..43 en col 40), sans
    # recouvrement : pas « within range » (14.02), pas de FNP.
    gs["objectives"] = [{"id": "o1", "hexes": [[40, 44]]}]
    assert _collect_fnp_thresholds(unit, gs, _NORMAL_WEAPON, model_id=ancient) == []
