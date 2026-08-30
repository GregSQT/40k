"""Hold Still and Say Aargh (passe 4) — blessure critique avec 'urty Syringe → D6 BM.

Invariants vérifiés :
- Crit wound avec urty_syringe vs non-VEHICLE → allocate_mortal_wounds appelé, record retiré de pending_wounds
- Crit devastating → pas consommé par Hold Still (double-dommage interdit)
- Wrong weapon → pas d'appel
- Target VEHICLE → pas d'appel

Verrou ROUGE/VERT documenté pour chaque invariant.
"""

import random
import pytest

import engine.phase_handlers.fight_handlers as fh
import engine.phase_handlers.shared_utils as su
import engine.phase_handlers.attack_sequence as aseq


# ---------------------------------------------------------------------------
# Arme et modèles minimaux
# ---------------------------------------------------------------------------

_URTY_SYRINGE = {
    "code": "urty_syringe", "display_name": "'urty Syringe",
    "NB": 1, "ATK": 3, "STR": 2, "AP": 0, "DMG": 1,
    "WEAPON_RULES": [],
}

_DOK_TOOLS = {
    "code": "dok_tools", "display_name": "Dok's Toolz",
    "NB": 1, "ATK": 4, "STR": 6, "AP": 1, "DMG": 2,
    "WEAPON_RULES": [],
}

_HOLD_STILL_RULE = {
    "ruleId": "mortal_wounds_on_critical_wound",
    "displayName": "Hold Still and Say Aargh",
    "rule_args": {"weapon": "urty_syringe", "mw_dice": "D6"},
}


def _attacker_model(*, weapon_index=0):
    return {
        "squad_id": "PAIN", "player": 1,
        "T": 5, "col": 0, "row": 0, "level": 0, "HP_CUR": 3,
        "ARMOR_SAVE": 5, "INVUL_SAVE": 7,
        "CC_WEAPONS": [_DOK_TOOLS, _URTY_SYRINGE],
        "UNIT_RULES": [_HOLD_STILL_RULE],
        "role": None,
    }


def _attacker_model_no_rule(*, weapon_index=0):
    return {
        "squad_id": "PAIN", "player": 1,
        "T": 5, "col": 0, "row": 0, "level": 0, "HP_CUR": 3,
        "ARMOR_SAVE": 5, "INVUL_SAVE": 7,
        "CC_WEAPONS": [_DOK_TOOLS, _URTY_SYRINGE],
        "UNIT_RULES": [],
        "role": None,
    }


def _target_model(*, vehicle=False):
    return {
        "squad_id": "TGT", "player": 2,
        "T": 4, "col": 5, "row": 5, "level": 0, "HP_CUR": 2,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 7,
        "role": None,
    }


def _pain_unit():
    return {
        "id": "PAIN", "player": 1, "HP_CUR": 3, "VALUE": 90.0,
        "UNIT_RULES": [], "keywords": [],
    }


def _target_unit(*, vehicle=False):
    keywords = ["VEHICLE"] if vehicle else ["INFANTRY"]
    return {
        "id": "TGT", "player": 2, "HP_CUR": 2, "VALUE": 10.0,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 7,
        "UNIT_RULES": [], "keywords": keywords,
    }


def _gs(*, vehicle=False, attacker_model=None):
    if attacker_model is None:
        attacker_model = _attacker_model()
    pain_unit = _pain_unit()
    tgt_unit = _target_unit(vehicle=vehicle)
    tgt_model = _target_model(vehicle=vehicle)
    return {
        "models_cache": {"PAIN#0": attacker_model, "TGT#0": tgt_model},
        "squad_models": {"PAIN": ["PAIN#0"], "TGT": ["TGT#0"]},
        "unit_by_id": {"PAIN": pain_unit, "TGT": tgt_unit},
        "units_cache": {"PAIN": pain_unit, "TGT": tgt_unit},
        "squad_cache": {"TGT": {"model_count_at_start": 1}},
        "action_logs": [], "action_log_seq": 0, "turn": 1,
        "objectives": [],
        "waaagh_active_player": None,
    }


def _intent(*, weapon_index=1, n_attacks=1):
    return {
        "model_id": "PAIN#0",
        "target_unit_id": "TGT",
        "weapon_index": weapon_index,
        "n_attacks_resolved": n_attacks,
        "target_squad_size_at_declaration": 1,
    }


def _crit_rolled():
    """rolled dict avec 1 blessure critique non-devastating pour urty_syringe."""
    rec = {"criticalWound": True, "devastating": False}
    pw = {"save_roll": 4, "rec": rec, "devastating": False}
    return {"shot_records": [rec], "pending_wounds": [pw], "counts": {"attacks": 1, "hits": 1, "wounds": 1}}


def _noncrit_rolled():
    """rolled dict sans blessure critique."""
    rec = {"criticalWound": False, "devastating": False}
    pw = {"save_roll": 4, "rec": rec, "devastating": False}
    return {"shot_records": [rec], "pending_wounds": [pw], "counts": {"attacks": 1, "hits": 1, "wounds": 1}}


def _crit_devastating_rolled():
    """rolled dict avec 1 blessure critique ET devastating (ne doit pas être consommé par Hold Still)."""
    rec = {"criticalWound": True, "devastating": True}
    pw = {"save_roll": 4, "rec": rec, "devastating": True}
    return {"shot_records": [rec], "pending_wounds": [pw], "counts": {"attacks": 1, "hits": 1, "wounds": 1}}


def _patch_fight_harness(monkeypatch, fake_rolled):
    """Monkeypatche les fonctions complexes pour isoler la logique Hold Still."""
    monkeypatch.setattr(fh, "waaagh_melee_bonus", lambda *a, **kw: 0)
    monkeypatch.setattr(fh, "resolve_oath_effects", lambda *a, **kw: (False, 0, 4))
    monkeypatch.setattr(fh, "resolve_hit_roll_modifiers", lambda *a, **kw: (3, None, None))
    monkeypatch.setattr(fh, "resolve_melee_wound_bonus", lambda *a, **kw: (4, None))
    monkeypatch.setattr(aseq, "build_weapon_attack_profile", lambda *a, **kw: None)
    monkeypatch.setattr(aseq, "roll_attack_pool", lambda **kw: fake_rolled)
    # display_save_threshold_with_waaagh lit first_alive["ARMOR_SAVE"] / ["INVUL_SAVE"]
    monkeypatch.setattr(fh, "display_save_threshold_with_waaagh", lambda *a, **kw: (4, False))


# ---------------------------------------------------------------------------
# Crit urty_syringe vs non-VEHICLE → Hold Still déclenché
# ---------------------------------------------------------------------------

def test_crit_urty_syringe_appelle_allocate_mw(monkeypatch):
    """ROUGE sans le fix : allocate_mortal_wounds n'est pas appelé (chemin manquant)."""
    from engine.phase_handlers import fight_handlers as _fh
    alloc_calls = []
    _patch_fight_harness(monkeypatch, _crit_rolled())
    monkeypatch.setattr(su, "allocate_mortal_wounds",
                        lambda gs, uid, n, auto, sink: alloc_calls.append((uid, n)))
    monkeypatch.setattr(random, "randint", lambda a, b: 6)  # D6 = 6 MW

    gs = _gs()
    result = _fh._manual_roll_fight_intent(gs, _intent(weapon_index=1), {})
    assert result is not None
    assert len(alloc_calls) == 1, f"Hold Still doit appeler allocate_mortal_wounds, got {alloc_calls}"
    assert alloc_calls[0] == ("TGT", 6), f"6 MW attendus (D6=6), got {alloc_calls[0]}"


def test_crit_urty_syringe_retire_record_de_pending_wounds(monkeypatch):
    """Le record critique doit être retiré de pending_wounds (fin de séquence, sans double-dommage)."""
    from engine.phase_handlers import fight_handlers as _fh
    _patch_fight_harness(monkeypatch, _crit_rolled())
    monkeypatch.setattr(su, "allocate_mortal_wounds", lambda *a, **kw: None)
    monkeypatch.setattr(random, "randint", lambda a, b: 6)

    gs = _gs()
    result = _fh._manual_roll_fight_intent(gs, _intent(weapon_index=1), {})
    assert result is not None
    # pending_wounds filtré → vide car le seul record était le critique consommé
    assert result["pending_wounds"] == [], f"pending_wounds doit être vide, got {result['pending_wounds']}"


def test_crit_devastating_non_consomme_par_hold_still(monkeypatch):
    """Un crit DEVASTATING ne doit pas être consommé par Hold Still."""
    from engine.phase_handlers import fight_handlers as _fh
    alloc_calls = []
    _patch_fight_harness(monkeypatch, _crit_devastating_rolled())
    monkeypatch.setattr(su, "allocate_mortal_wounds",
                        lambda gs, uid, n, auto, sink: alloc_calls.append((uid, n)))
    monkeypatch.setattr(random, "randint", lambda a, b: 6)

    gs = _gs()
    result = _fh._manual_roll_fight_intent(gs, _intent(weapon_index=1), {})
    assert result is not None
    assert not alloc_calls, "Hold Still ne doit pas consommer un crit devastating"
    # Le record doit rester dans pending_wounds
    assert len(result["pending_wounds"]) == 1, "le crit devastating doit rester dans pending_wounds"


# ---------------------------------------------------------------------------
# Mauvaise arme → pas de Hold Still
# ---------------------------------------------------------------------------

def test_mauvaise_arme_pas_de_hold_still(monkeypatch):
    """weapon_index=0 = dok_tools, pas urty_syringe → aucun MW."""
    from engine.phase_handlers import fight_handlers as _fh
    alloc_calls = []
    _patch_fight_harness(monkeypatch, _crit_rolled())
    monkeypatch.setattr(su, "allocate_mortal_wounds",
                        lambda gs, uid, n, auto, sink: alloc_calls.append((uid, n)))
    monkeypatch.setattr(random, "randint", lambda a, b: 6)

    gs = _gs()
    result = _fh._manual_roll_fight_intent(gs, _intent(weapon_index=0), {})
    assert result is not None
    assert not alloc_calls, "Hold Still ne doit pas se déclencher avec dok_tools"


# ---------------------------------------------------------------------------
# Target VEHICLE → pas de Hold Still
# ---------------------------------------------------------------------------

def test_target_vehicle_pas_de_hold_still(monkeypatch):
    """VEHICLE keyword → Hold Still ne s'applique pas."""
    from engine.phase_handlers import fight_handlers as _fh
    alloc_calls = []
    _patch_fight_harness(monkeypatch, _crit_rolled())
    monkeypatch.setattr(su, "allocate_mortal_wounds",
                        lambda gs, uid, n, auto, sink: alloc_calls.append((uid, n)))
    monkeypatch.setattr(random, "randint", lambda a, b: 6)

    gs = _gs(vehicle=True)
    result = _fh._manual_roll_fight_intent(gs, _intent(weapon_index=1), {})
    assert result is not None
    assert not alloc_calls, "Hold Still ne doit pas se déclencher vs VEHICLE"
