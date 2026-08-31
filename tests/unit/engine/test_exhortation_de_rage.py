"""Exhortation de Rage (passe 4) — D6 à la sélection combat → D3 ou 3 BM sur ennemi engagé.

Invariants vérifiés :
- Unité sans règle → retourne None (pas de déclenchement)
- Aucun ennemi engagé → retourne None
- D6 <= 3 → retourne None
- D6 4-5 → payload waiting_for_agent_decision, décision posée, mw_count ∈ [1, 3]
- D6 == 6 → payload waiting, mw_count = 3 (fixe)

Verrou ROUGE/VERT documenté pour chaque invariant.
"""

import random
import pytest

import engine.phase_handlers.fight_handlers as fh
import engine.w40k_core as wcore


# ---------------------------------------------------------------------------
# Fixtures minimales
# ---------------------------------------------------------------------------

_EXHORT_RULE = {
    "ruleId": "mortal_wounds_on_fight_activation",
    "displayName": "Exhortation de Rage",
    "rule_args": {"mw_on_6": 3},
}


def _unit_with_rule():
    return {
        "id": "CHAP", "player": 1, "HP_CUR": 4,
        "UNIT_RULES": [_EXHORT_RULE],
        "keywords": ["INFANTRY", "CHARACTER", "FLY"],
    }


def _unit_without_rule():
    return {
        "id": "CHAP", "player": 1, "HP_CUR": 4,
        "UNIT_RULES": [],
        "keywords": ["INFANTRY", "CHARACTER", "FLY"],
    }


def _gs():
    chap_unit = {"player": 1, "HP_CUR": 4}
    return {
        "units_cache": {"CHAP": chap_unit},
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 1,
        "pending_agent_decision": None,
    }


class _FakeEngine:
    """Stub minimal de W40KEngine pour tester _check_and_trigger_exhortation_de_rage."""
    _check_and_trigger_exhortation_de_rage = wcore.W40KEngine._check_and_trigger_exhortation_de_rage
    _apply_exhortation_de_rage = wcore.W40KEngine._apply_exhortation_de_rage

    def __init__(self, gs):
        self.game_state = gs


# ---------------------------------------------------------------------------
# Unité sans règle → None
# ---------------------------------------------------------------------------

def test_sans_regle_retourne_none(monkeypatch):
    """ROUGE sans le fix : le code plante ou retourne un résultat inattendu."""
    monkeypatch.setattr(fh, "_fight_build_valid_target_pool", lambda gs, u: ["ENEMY"])
    engine = _FakeEngine(_gs())
    result = engine._check_and_trigger_exhortation_de_rage("CHAP", _unit_without_rule(), None)
    assert result is None, f"attendu None sans règle, got {result}"


# ---------------------------------------------------------------------------
# Aucun ennemi engagé → None
# ---------------------------------------------------------------------------

def test_pas_d_ennemis_engages_retourne_none(monkeypatch):
    """ROUGE sans le fix : IndexError ou résultat inattendu sur liste vide."""
    monkeypatch.setattr(fh, "_fight_build_valid_target_pool", lambda gs, u: [])
    engine = _FakeEngine(_gs())
    result = engine._check_and_trigger_exhortation_de_rage("CHAP", _unit_with_rule(), None)
    assert result is None, f"attendu None sans ennemis engagés, got {result}"


# ---------------------------------------------------------------------------
# D6 <= 3 → None (pas de déclenchement)
# ---------------------------------------------------------------------------

def test_d6_bas_retourne_none(monkeypatch):
    """ROUGE sans le fix : la décision est posée même sur D6 <= 3."""
    monkeypatch.setattr(fh, "_fight_build_valid_target_pool", lambda gs, u: ["ENEMY"])
    monkeypatch.setattr(random, "randint", lambda a, b: 3)  # D6 = 3 → seuil 4 non atteint
    engine = _FakeEngine(_gs())
    result = engine._check_and_trigger_exhortation_de_rage("CHAP", _unit_with_rule(), None)
    assert result is None, f"D6=3 ne doit pas déclencher l'exhortation, got {result}"


# ---------------------------------------------------------------------------
# D6 == 6 → mw_count = 3, décision posée
# ---------------------------------------------------------------------------

def test_d6_6_pose_decision_et_mw_count_3(monkeypatch):
    """ROUGE sans le fix : décision non posée ou mw_count != 3."""
    decisions_posed = []
    monkeypatch.setattr(fh, "_fight_build_valid_target_pool", lambda gs, u: ["ENEMY1", "ENEMY2"])
    monkeypatch.setattr(random, "randint", lambda a, b: 6)  # D6 = 6
    monkeypatch.setattr(
        wcore, "set_pending_agent_decision",
        lambda gs, **kw: decisions_posed.append(kw),
    )
    engine = _FakeEngine(_gs())
    result = engine._check_and_trigger_exhortation_de_rage("CHAP", _unit_with_rule(), None)

    assert result is not None, "D6=6 doit déclencher l'exhortation"
    ok, payload = result
    assert ok is True
    assert payload.get("waiting_for_agent_decision") is True
    assert payload.get("decision_type") == "mortal_wounds_target"
    assert len(decisions_posed) == 1, "set_pending_agent_decision doit être appelé une fois"
    assert decisions_posed[0].get("decision_type") == "mortal_wounds_target"

    # Vérifier le format des options : label, effect_ids vide, payload avec target_eid.
    opts = decisions_posed[0].get("options", [])
    assert len(opts) == 2, f"2 cibles → 2 options, got {len(opts)}"
    for opt in opts:
        assert "label" in opt and opt["label"], f"option sans label : {opt}"
        assert opt.get("effect_ids") == (), f"effect_ids doit être () : {opt}"
        assert "payload" in opt and "target_eid" in opt["payload"], f"payload manquant : {opt}"
        assert not opt.get("declines"), f"declines doit être False : {opt}"

    # mw_count = 3 stocké dans le pending
    pending = engine.game_state.get("_pending_exhortation_fight")
    assert pending is not None
    assert pending["mw_count"] == 3, f"mw_count doit être 3 sur D6=6, got {pending['mw_count']}"


# ---------------------------------------------------------------------------
# D6 == 4 → mw_count = D3, décision posée
# ---------------------------------------------------------------------------

def test_d6_4_pose_decision_et_mw_count_d3(monkeypatch):
    """D6=4 → D3 MW (1-3) et décision posée (≥2 cibles : path normal)."""
    decisions_posed = []
    rolls = iter([4, 2])  # premier randint → D6=4, second → D3=2

    def _fake_randint(a, b):
        return next(rolls)

    monkeypatch.setattr(fh, "_fight_build_valid_target_pool", lambda gs, u: ["ENEMY1", "ENEMY2"])
    monkeypatch.setattr(random, "randint", _fake_randint)
    monkeypatch.setattr(
        wcore, "set_pending_agent_decision",
        lambda gs, **kw: decisions_posed.append(kw),
    )
    engine = _FakeEngine(_gs())
    result = engine._check_and_trigger_exhortation_de_rage("CHAP", _unit_with_rule(), None)

    assert result is not None, "D6=4 doit déclencher l'exhortation"
    pending = engine.game_state.get("_pending_exhortation_fight")
    assert pending is not None
    assert 1 <= pending["mw_count"] <= 3, f"mw_count D3 hors plage : {pending['mw_count']}"
    assert pending["mw_count"] == 2, f"D3 simulé à 2, got {pending['mw_count']}"
    assert len(decisions_posed) == 1


# ---------------------------------------------------------------------------
# Cible unique → application directe (pas de décision)
# ---------------------------------------------------------------------------

def test_single_target_auto_applique_sans_decision(monkeypatch):
    """D6=4, 1 seule cible : pas de set_pending_agent_decision, MW appliquées directement."""
    import engine.phase_handlers.shared_utils as su
    decisions_posed = []
    mw_applied = []
    continue_called = []
    rolls = iter([4, 2])  # D6=4, D3=2

    def _fake_randint(a, b):
        return next(rolls)

    def _fake_allocate(gs, target_eid, count, auto_resolve, details):
        mw_applied.append({"target": target_eid, "count": count})

    def _fake_continue(self_engine, squad_id, target_slot):
        continue_called.append(squad_id)
        return True, {"action": "squad_fight", "squad_id": squad_id}

    monkeypatch.setattr(fh, "_fight_build_valid_target_pool", lambda gs, u: ["ONLY_ENEMY"])
    monkeypatch.setattr(random, "randint", _fake_randint)
    monkeypatch.setattr(wcore, "set_pending_agent_decision",
                        lambda gs, **kw: decisions_posed.append(kw))
    monkeypatch.setattr(su, "allocate_mortal_wounds", _fake_allocate)

    engine = _FakeEngine(_gs())
    # _FakeEngine ne hérite pas de W40KEngine : poser le stub directement sur l'instance.
    engine._continue_squad_fight_after_selection = (
        lambda squad_id, target_slot: _fake_continue(engine, squad_id, target_slot)
    )
    result = engine._check_and_trigger_exhortation_de_rage("CHAP", _unit_with_rule(), None)

    assert len(decisions_posed) == 0, "cible unique : aucune décision ne doit être posée"
    assert len(mw_applied) == 1, "les BM doivent être appliquées"
    assert mw_applied[0]["target"] == "ONLY_ENEMY"
    assert mw_applied[0]["count"] == 2
    assert len(continue_called) == 1, "_continue_squad_fight_after_selection doit être appelé"
    assert result is not None
    ok, payload = result
    assert ok is True


# ---------------------------------------------------------------------------
# §24.08 Deadly Demise : l'attaquant détruit par cascade → pas de crash
# ---------------------------------------------------------------------------

def test_attaquant_detruit_par_deadly_demise_pas_de_crash(monkeypatch):
    """ROUGE sans le fix : KeyError 'Squad CHAP absent de units_cache'.

    Reproduit le crash d'entraînement : allocate_mortal_wounds sur la cible
    déclenche Deadly Demise (D6=6) qui détruit l'attaquant (squad_id=CHAP) avant
    que _continue_squad_fight_after_selection soit appelé.
    """
    import engine.phase_handlers.shared_utils as su

    settle_called = []

    def _fake_allocate_destroys_attacker(gs, target_eid, count, auto_resolve, details):
        # Simule la cascade Deadly Demise : retire l'attaquant de units_cache.
        gs["units_cache"].pop("CHAP", None)

    monkeypatch.setattr(su, "allocate_mortal_wounds", _fake_allocate_destroys_attacker)

    engine = _FakeEngine(_gs())
    engine._fight_v11_gym_settle = lambda: settle_called.append(True)

    # D6=4, cible unique → chemin auto (_apply_exhortation_de_rage direct).
    rolls = iter([4, 2])
    monkeypatch.setattr(random, "randint", lambda a, b: next(rolls))
    monkeypatch.setattr(fh, "_fight_build_valid_target_pool", lambda gs, u: ["ENEMY"])

    result = engine._check_and_trigger_exhortation_de_rage("CHAP", _unit_with_rule(), None)

    assert result is not None, "doit retourner un résultat, pas None"
    ok, payload = result
    assert ok is True
    assert payload.get("action") == "squad_fight"
    assert payload.get("squad_id") == "CHAP"
    assert payload.get("target_squad_id") is None
    assert len(settle_called) == 1, "_fight_v11_gym_settle doit être appelé une fois"
