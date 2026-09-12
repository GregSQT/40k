"""Exhortation of Rage (passe 4) — cible choisie PUIS D6 → 0, D3 ou 3 BM sur l'ennemi engagé.

Datasheet (`Datasheets - Space Marines.pdf`, Chaplain with Jump Pack) : « you can select one
enemy unit it is engaged with and roll one D6, and on a result of: 4-5: That enemy unit suffers
D3 mortal wounds. 6: That enemy unit suffers 3 mortal wounds. »

Invariants vérifiés :
- Unité sans règle → retourne None (pas de déclenchement)
- Aucun ennemi engagé → retourne None
- ≥ 2 cibles → décision `mortal_wounds_target` posée SANS aucun jet (la cible précède le dé)
- Cible choisie, D6 1-3 → ligne `SUFFERS 0` avec le dé, aucune allocation, combat repris
- Cible choisie, D6 4-5 → D3 BM, ligne avec `Trigger:` ET `MW:`
- Cible choisie, D6 6 → 3 BM, ligne avec `Trigger:` sans `MW:`
- La ligne nomme la victime (`unitId`) et la source (`mortalWoundSourceId`), jamais `attackerId`

Verrou ROUGE/VERT documenté pour chaque invariant.
"""

import random
import pytest
from typing import Any

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


#: Deux cibles ENGAGÉES qui ne se ressemblent pas : ENEMY1 est intacte et bon marché, ENEMY2
#: porte une figurine à 1 PV sur 4 et vaut plus cher. C'est exactement l'arbitrage que 1 à 3
#: blessures mortelles posent — achever ou entamer —, et sans traits continus par candidat les
#: deux lignes d'observation sortaient identiques.
_MW_MODELS = {
    "e1a": {"player": 0, "HP_CUR": 2, "HP_MAX": 2, "VALUE": 10, "col": 5, "row": 5},
    "e1b": {"player": 0, "HP_CUR": 2, "HP_MAX": 2, "VALUE": 10, "col": 6, "row": 5},
    "e2a": {"player": 0, "HP_CUR": 1, "HP_MAX": 4, "VALUE": 30, "col": 7, "row": 5},
}


def _gs():
    chap_unit = {"player": 1, "HP_CUR": 4}
    # col/row sur chaque unite : la ligne `SUFFERS N Mortal Wounds` nomme la VICTIME et ses
    # coordonnees, comme toute ligne de blessures mortelles. `_fight_build_valid_target_pool`
    # ne rend que des unites du cache, donc une cible sans position est un etat que la
    # production ne produit pas — la fixture doit le refleter.
    return {
        "units_cache": {
            "CHAP": chap_unit,
            "ENEMY1": {"player": 0, "HP_CUR": 4, "col": 5, "row": 5},
            "ENEMY2": {"player": 0, "HP_CUR": 1, "col": 7, "row": 5},
            "ENEMY": {"player": 0, "HP_CUR": 4, "col": 5, "row": 5},
            "ONLY_ENEMY": {"player": 0, "HP_CUR": 4, "col": 5, "row": 5},
        },
        "models_cache": {k: dict(v) for k, v in _MW_MODELS.items()},
        "squad_models": {"ENEMY1": ["e1a", "e1b"], "ENEMY2": ["e2a"]},
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 1,
        "pending_agent_decision": None,
        # Defenseur PROGRAMMATIQUE (joueur 0 = les cibles) : attribution AUTO des blessures
        # mortelles. Le siege humain a son propre test (`test_defenseur_humain_…`).
        "player_types": {"0": "ai", "1": "ai"},
    }


class _FakeEngine:
    """Stub minimal de W40KEngine pour tester _check_and_trigger_exhortation_de_rage."""
    _check_and_trigger_exhortation_de_rage = wcore.W40KEngine._check_and_trigger_exhortation_de_rage
    _apply_exhortation_de_rage = wcore.W40KEngine._apply_exhortation_de_rage
    _continue_fight_after_exhortation = wcore.W40KEngine._continue_fight_after_exhortation
    _continue_squad_fight_after_selection: Any = wcore.W40KEngine._continue_squad_fight_after_selection
    _fight_v11_gym_settle = wcore.W40KEngine._fight_v11_gym_settle
    _mortal_wounds_target_metrics = wcore.W40KEngine._mortal_wounds_target_metrics

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
# ≥ 2 cibles → décision posée AVANT tout jet
# ---------------------------------------------------------------------------

def test_deux_cibles_posent_la_decision_sans_aucun_jet(monkeypatch):
    """ROUGE avant le fix : le D6 était jeté d'abord, et la décision ne se posait que sur 4+ —
    l'agent choisissait sa cible en connaissant déjà le nombre de blessures. La datasheet dit
    « select one enemy unit … and roll one D6 » : le dé ne sort pas avant que la cible soit
    choisie, donc AUCUN `randint` ici."""
    decisions_posed = []
    monkeypatch.setattr(fh, "_fight_build_valid_target_pool", lambda gs, u: ["ENEMY1", "ENEMY2"])

    def _no_roll(a, b):
        raise AssertionError("aucun dé ne doit être jeté avant le choix de la cible")

    monkeypatch.setattr(random, "randint", _no_roll)
    monkeypatch.setattr(
        wcore, "set_pending_agent_decision",
        lambda gs, **kw: decisions_posed.append(kw),
    )
    engine = _FakeEngine(_gs())
    result = engine._check_and_trigger_exhortation_de_rage("CHAP", _unit_with_rule(), None)

    assert result is not None, "deux cibles engagées : la décision doit être posée"
    ok, payload = result
    assert ok is True
    assert payload.get("waiting_for_agent_decision") is True
    assert payload.get("decision_type") == "mortal_wounds_target"
    assert "mw_count" not in payload and "exhortation_d6_roll" not in payload, payload
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

    # Le pending ne porte QUE ce que la reprise a besoin de savoir : le dé n'existe pas encore.
    pending = engine.game_state.get("_pending_exhortation_fight")
    assert pending == {"squad_id": "CHAP", "target_slot": None, "regime": "gym"}, pending


# ---------------------------------------------------------------------------
# Cible choisie → le jet, sa ligne, et la reprise du combat
# ---------------------------------------------------------------------------

def _apply_with_rolls(monkeypatch, rolls, *, target="ONLY_ENEMY"):
    """Joue `_apply_exhortation_de_rage` sur `target` avec la suite de dés `rolls` (D6 puis
    D3 éventuel). Rend (payload, ligne d'action_log, blessures allouées, reprises)."""
    import engine.phase_handlers.shared_utils as su
    mw_applied = []
    continue_called = []
    it = iter(rolls)

    def _fake_randint(a, b):
        return next(it)

    def _fake_allocate(gs, target_eid, count, auto_resolve, details):
        mw_applied.append({"target": target_eid, "count": count})
        # Comme la vraie allocation : un record par blessure, sur la figurine allouée.
        details.extend({"modelId": "e1a", "col": 5, "row": 5, "died": False} for _ in range(count))

    monkeypatch.setattr(random, "randint", _fake_randint)
    monkeypatch.setattr(su, "allocate_mortal_wounds", _fake_allocate)
    engine = _FakeEngine(_gs())
    engine._continue_squad_fight_after_selection = (
        lambda squad_id, target_slot, **_kw: (
            continue_called.append(squad_id) or (True, {"action": "squad_fight", "squad_id": squad_id})
        )
    )
    result = engine._apply_exhortation_de_rage("CHAP", target, None, auto=True)
    logs = [e for e in engine.game_state["action_logs"] if e["type"] == "mortal_wounds_ability"]
    assert len(logs) == 1, f"une ligne par jet, got {len(logs)}"
    return result, logs[0], mw_applied, continue_called


def test_jet_rate_laisse_sa_ligne_sans_allocation(monkeypatch):
    """ROUGE avant le fix : un D6 ≤ 3 ne laissait AUCUNE trace — ni ligne, ni dé. Le jet a eu
    lieu, la règle a été exercée : la ligne porte 0 blessure et le dé qui l'explique."""
    result, log, mw_applied, continue_called = _apply_with_rolls(monkeypatch, [3])
    assert result is not None and result[0] is True
    assert mw_applied == [], "D6=3 : aucune blessure à allouer"
    assert continue_called == ["CHAP"], "le combat reprend après un jet raté"
    assert log["hazardousMortalWounds"] == 0
    assert log["abilityTriggerRoll"] == 3
    assert "mortalWoundDice" not in log, log
    assert "SUFFERS 0 Mortal Wounds [EXHORTATION DE RAGE] Trigger:3 [FROM:CHAP]" in log["message"], log["message"]


def test_jet_4_5_donne_d3_blessures_avec_les_deux_des(monkeypatch):
    """D6=4 puis D3=2 : deux blessures, et la ligne porte le dé de seuil ET le dé de compte —
    séparés, parce que l'un se compare à 4+ et l'autre se somme."""
    result, log, mw_applied, continue_called = _apply_with_rolls(monkeypatch, [4, 2])
    assert mw_applied == [{"target": "ONLY_ENEMY", "count": 2}]
    assert continue_called == ["CHAP"]
    assert log["hazardousMortalWounds"] == 2
    assert log["abilityTriggerRoll"] == 4
    assert log["mortalWoundDice"] == [2]
    assert "SUFFERS 2 Mortal Wounds [EXHORTATION DE RAGE] Trigger:4 MW:2 [FROM:CHAP]" in log["message"], log["message"]


def test_jet_6_donne_trois_blessures_sans_de_de_compte(monkeypatch):
    """D6=6 : 3 blessures FIXES — aucun D3 n'est jeté, donc aucun `MW:` sur la ligne."""
    result, log, mw_applied, _ = _apply_with_rolls(monkeypatch, [6])
    assert mw_applied == [{"target": "ONLY_ENEMY", "count": 3}]
    assert log["hazardousMortalWounds"] == 3
    assert log["abilityTriggerRoll"] == 6
    assert "mortalWoundDice" not in log, log
    assert "Trigger:6 [FROM:CHAP]" in log["message"], log["message"]


def test_la_ligne_nomme_la_victime_et_la_source_comme_hold_still(monkeypatch):
    """ROUGE avant le fix : la ligne posait AUSSI `attackerId`, que `useGameLog` (front) préfère
    à `unitId` — les deux producteurs de `mortal_wounds_ability` divergeaient d'une clé. La
    victime est l'unité de la ligne, la source vit dans `mortalWoundSourceId`, comme Hold Still."""
    _, log, _, _ = _apply_with_rolls(monkeypatch, [5, 1])
    assert log["unitId"] == "ONLY_ENEMY"
    assert log["mortalWoundSourceId"] == "CHAP"
    assert "attackerId" not in log, log
    assert log["player"] == 0, "le camp de la ligne est celui de la VICTIME"


def test_la_ligne_step_log_porte_trigger_puis_mw(monkeypatch):
    """CHEMIN DE PRODUCTION du journal : `_build_step_log_details` traduit les clés du moteur et
    le formateur écrit `Trigger:` puis `MW:` avant `[FROM:]`."""
    from ai.step_logger import StepLogger
    _, log, _, _ = _apply_with_rolls(monkeypatch, [5, 3])
    eng = wcore.W40KEngine.__new__(wcore.W40KEngine)
    eng.game_state = {}
    details = eng._build_step_log_details(log, pre_action_turn=1)
    assert details["ability_trigger_roll"] == 5
    assert details["mortal_wound_dice"] == [3]
    logger = StepLogger(output_file="/dev/null", enabled=False, buffer_size=1)
    msg = logger._format_replay_style_message("ONLY_ENEMY", "hazardous", details)
    assert msg == (
        "Unit ONLY_ENEMY(5,5) SUFFERS 3 Mortal Wounds [EXHORTATION DE RAGE] Trigger:5 MW:3 "
        "[FROM:CHAP] [ALLOC_MODEL: e1a]"
    ), msg


def test_single_target_auto_applique_sans_decision(monkeypatch):
    """1 seule cible : pas de set_pending_agent_decision, jet immédiat, MW appliquées."""
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
        lambda squad_id, target_slot, **_kw: _fake_continue(engine, squad_id, target_slot)
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


# ---------------------------------------------------------------------------
# Candidats DISCERNABLES (les blessures mortelles se choisissent une cible)
# ---------------------------------------------------------------------------

def test_candidats_mw_portent_des_traits_distincts(monkeypatch):
    """Deux cibles engagées -> deux lignes continues DIFFÉRENTES.

    ROUGE avant le câblage de `decision_options_cont` : les candidats ne portaient que
    `effect_ids=()` et `declines=False`, donc des lignes d'observation identiques — la tête
    pointeur les scorait à égalité et le choix était un tirage au sort.
    """
    from engine.observation_entities import decision_option_cont_index

    posed = []
    monkeypatch.setattr(fh, "_fight_build_valid_target_pool", lambda gs, u: ["ENEMY1", "ENEMY2"])
    monkeypatch.setattr(wcore, "set_pending_agent_decision", lambda gs, **kw: posed.append(kw))
    engine = _FakeEngine(_gs())
    engine._check_and_trigger_exhortation_de_rage("CHAP", _unit_with_rule(), None)

    cont = posed[0].get("options_cont")
    assert cont is not None, "les candidats MW doivent porter des traits continus"
    assert len(cont) == 2
    assert cont[0] != cont[1], f"deux cibles indiscernables : {cont}"

    hp_i = decision_option_cont_index("target_wounded_hp_norm")
    val_i = decision_option_cont_index("target_value_norm")
    # ENEMY1 : aucune figurine entamée -> 1.0 ; ENEMY2 : 1 PV sur 4 -> 0.25.
    assert cont[0][hp_i] == pytest.approx(1.0)
    assert cont[1][hp_i] == pytest.approx(0.25)
    # VALUE vivante : 20 pour ENEMY1, 30 pour ENEMY2 -> la plus chère vaut 1.0.
    assert cont[0][val_i] == pytest.approx(20.0 / 30.0)
    assert cont[1][val_i] == pytest.approx(1.0)
