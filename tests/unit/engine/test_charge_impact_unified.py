"""§charge_impact unifié (passe 4) — les blessures mortelles passent par la file 06.02.

Invariants vérifiés :
- impact_roll >= 4 (HIT) → 1 blessure mortelle mise en file pour la cible (`queue_mortal_wounds`),
  `chargeImpactDetails` présent sur la ligne émise et c'est LUI que la file complétera ;
- impact_roll < 4 (FAIL) → rien en file ;
- unité sans charge_impact → aucun log ni file.

Depuis le chantier « chaîne d'attaque 100 % » (2026-09-18) : l'impact n'attribue plus lui-même
(`allocate_mortal_wounds` AUTO même pour un défenseur humain) — il met en file, et
`drain_mortal_wound_queue` attribue en AUTO pour un propriétaire programmatique, par l'allocation
manuelle 06.02 pour un humain qui a un choix. Verrou ROUGE/VERT documenté pour chaque invariant.
"""

import pytest
import engine.phase_handlers.charge_handlers as ch
from engine.constants import MORTAL_WOUND_QUEUE_KEY
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
# HIT → une blessure mortelle en file pour la cible
# ---------------------------------------------------------------------------

def test_hit_met_une_blessure_mortelle_en_file(monkeypatch):
    """ROUGE sans le fix : _apply_charge_impact décrémentait HP directement (ou attribuait AUTO)."""
    monkeypatch.setattr(ch, "resolve_dice_value", lambda *a, **kw: 4)  # 4 >= seuil 4 → HIT
    gs = _gs()
    _apply_charge_impact(gs, _UNIT_WITH_IMPACT, "TGT", 1, 1, 5, 5, 1)
    queue = gs[MORTAL_WOUND_QUEUE_KEY]
    assert len(queue) == 1, f"une entrée en file attendue, got {queue}"
    assert (queue[0]["kind"], queue[0]["uid"], queue[0]["n_wounds"]) == ("victim", "TGT", 1)
    assert queue[0]["details_key"] == "chargeImpactDetails"


def test_hit_log_contient_charge_impact_details_et_la_file_le_partage(monkeypatch):
    """chargeImpactDetails doit apparaître dans l'entrée action_log, et l'entrée de file porte
    CETTE ligne (complétée par référence à l'attribution)."""
    monkeypatch.setattr(ch, "resolve_dice_value", lambda *a, **kw: 4)
    gs = _gs()
    _apply_charge_impact(gs, _UNIT_WITH_IMPACT, "TGT", 1, 1, 5, 5, 1)
    log = next(e for e in gs["action_logs"] if e.get("type") == "charge_impact")
    assert "chargeImpactDetails" in log, "chargeImpactDetails absent du log"
    assert gs[MORTAL_WOUND_QUEUE_KEY][0]["log_payload"] is log


# ---------------------------------------------------------------------------
# FAIL → rien en file
# ---------------------------------------------------------------------------

def test_miss_pas_d_allocation(monkeypatch):
    """ROUGE sans le fix : un décrément HP 0 est quand même déclenché (ou l'assert fail change)."""
    monkeypatch.setattr(ch, "resolve_dice_value", lambda *a, **kw: 3)  # 3 < 4 → FAIL
    gs = _gs()
    _apply_charge_impact(gs, _UNIT_WITH_IMPACT, "TGT", 1, 1, 5, 5, 1)
    assert MORTAL_WOUND_QUEUE_KEY not in gs, "un impact raté ne met rien en file"
    log = next(e for e in gs["action_logs"] if e.get("type") == "charge_impact")
    assert log["impact_hit_result"] == "FAIL"


# ---------------------------------------------------------------------------
# Sans règle → rien
# ---------------------------------------------------------------------------

def test_sans_regle_pas_de_log_ni_allocation(monkeypatch):
    """Unité sans charge_impact : aucun log émis et rien en file."""
    monkeypatch.setattr(ch, "resolve_dice_value", lambda *a, **kw: 6)
    gs = _gs()
    _apply_charge_impact(gs, _UNIT_WITHOUT_IMPACT, "TGT", 1, 1, 5, 5, 1)
    assert MORTAL_WOUND_QUEUE_KEY not in gs
    assert not any(e.get("type") == "charge_impact" for e in gs["action_logs"])
