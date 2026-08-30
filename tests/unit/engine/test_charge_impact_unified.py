"""§charge_impact unifié (passe 4) — allocate_mortal_wounds remplace le décrément direct HP.

Invariants vérifiés :
- impact_roll >= 4 (HIT) → allocate_mortal_wounds appelé avec 1 MW, chargeImpactDetails présent
- impact_roll < 4 (FAIL) → allocate_mortal_wounds non appelé
- unité sans charge_impact → aucun log ni allocation

Verrou ROUGE/VERT documenté pour chaque invariant.
"""

import pytest
import engine.phase_handlers.charge_handlers as ch
from engine.phase_handlers.charge_handlers import _apply_charge_impact


_UNIT_WITH_IMPACT = {
    "id": "ORK_TRUCK#0",
    "player": 1,
    "squad_id": "ORK_TRUCK",
    "UNIT_RULES": [{"ruleId": "charge_impact", "displayName": "Impact Hits"}],
}

_UNIT_WITHOUT_IMPACT = {
    "id": "BOYZ#0",
    "player": 1,
    "squad_id": "BOYZ",
    "UNIT_RULES": [],
}


def _gs():
    return {"action_logs": [], "action_log_seq": 0, "turn": 1}


# ---------------------------------------------------------------------------
# HIT → allocate_mortal_wounds appelé
# ---------------------------------------------------------------------------

def test_hit_appelle_allocate_mortal_wounds(monkeypatch):
    """ROUGE sans le fix : _apply_charge_impact décrémente HP directement, pas via allocate_mortal_wounds."""
    calls = []
    monkeypatch.setattr(ch, "resolve_dice_value", lambda *a, **kw: 4)  # 4 >= seuil 4 → HIT
    monkeypatch.setattr(ch, "allocate_mortal_wounds",
                        lambda gs, uid, n, auto, sink: calls.append((uid, n)))
    gs = _gs()
    _apply_charge_impact(gs, _UNIT_WITH_IMPACT, "TGT", 1, 1, 5, 5, 1)
    assert len(calls) == 1, f"allocate_mortal_wounds doit être appelé 1 fois, got {calls}"
    assert calls[0] == ("TGT", 1), f"mauvais uid/n : {calls[0]}"


def test_hit_log_contient_charge_impact_details(monkeypatch):
    """chargeImpactDetails doit apparaître dans l'entrée action_log (pattern details-sink)."""
    monkeypatch.setattr(ch, "resolve_dice_value", lambda *a, **kw: 4)
    monkeypatch.setattr(ch, "allocate_mortal_wounds", lambda gs, uid, n, auto, sink: None)
    gs = _gs()
    _apply_charge_impact(gs, _UNIT_WITH_IMPACT, "TGT", 1, 1, 5, 5, 1)
    log = next(e for e in gs["action_logs"] if e.get("type") == "charge_impact")
    assert "chargeImpactDetails" in log, "chargeImpactDetails absent du log"


# ---------------------------------------------------------------------------
# FAIL → pas d'allocation
# ---------------------------------------------------------------------------

def test_miss_pas_d_allocation(monkeypatch):
    """ROUGE sans le fix : un décrément HP 0 est quand même déclenché (ou l'assert fail change)."""
    calls = []
    monkeypatch.setattr(ch, "resolve_dice_value", lambda *a, **kw: 3)  # 3 < 4 → FAIL
    monkeypatch.setattr(ch, "allocate_mortal_wounds",
                        lambda gs, uid, n, auto, sink: calls.append((uid, n)))
    gs = _gs()
    _apply_charge_impact(gs, _UNIT_WITH_IMPACT, "TGT", 1, 1, 5, 5, 1)
    assert not calls, "pas d'allocation sur un échec de charge_impact"


# ---------------------------------------------------------------------------
# Sans règle → pas d'effet
# ---------------------------------------------------------------------------

def test_sans_regle_pas_de_log_ni_allocation(monkeypatch):
    """Unité sans charge_impact : aucun log émis et aucune allocation."""
    calls = []
    monkeypatch.setattr(ch, "allocate_mortal_wounds",
                        lambda gs, uid, n, auto, sink: calls.append(n))
    gs = _gs()
    _apply_charge_impact(gs, _UNIT_WITHOUT_IMPACT, "TGT", 1, 1, 5, 5, 1)
    assert not calls
    assert not gs["action_logs"], "aucun log charge_impact sans la règle"
