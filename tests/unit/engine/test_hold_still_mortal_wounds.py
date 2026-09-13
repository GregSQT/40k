"""Hold Still and Say Aargh — blessure critique avec 'urty Syringe → D6 BM EN PLUS.

Texte de la datasheet (Documentation/40k_rules/Armageddon/Datasheets - Orks.pdf, p4, PAINBOY) :
« When this model scores a critical wound with its 'urty syringe against a non-VEHICLE unit,
it ALSO inflicts D6 mortal wounds to that unit. »

CE QUE CE FICHIER REMPLACE. Sa version precedente verrouillait l'inverse : elle exigeait que le
record critique soit RETIRE de `pending_wounds` et que `counts["wounds"]` soit decremente, sur la
foi d'un commentaire de code qui citait « and the attack sequence ends » — une clause absente du
texte officiel, empruntee au wording de [DEVASTATING WOUNDS] 24.10. La blessure normale etait
donc perdue, et step.log rendait `Save [NOT ALLOCATED]` sur une attaque qui avait porte.

Invariants verrouilles ici :
- le crit RESTE dans `pending_wounds` et suit 05.03/05.04 (sauvegarde comprise) ;
- `counts["wounds"]` n'est pas touche ;
- un D6 est tire PAR crit et accumule dans `pending_mortal_wounds["dice"]` ;
- les blessures mortelles sont infligees APRES les degats normaux du lot (06.02) ;
- mauvaise arme / cible VEHICLE / pas de crit → aucune blessure mortelle.
"""

import random

import engine.phase_handlers.fight_handlers as fh
import engine.phase_handlers.shared_utils as su
import engine.phase_handlers.attack_sequence as aseq
from shared.data_validation import HAZARD_CONTEXT_HOLD_STILL


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


def _attacker_model():
    return {
        "squad_id": "PAIN", "player": 1,
        "T": 5, "col": 0, "row": 0, "level": 0, "HP_CUR": 3, "HP_MAX": 3,
        "ARMOR_SAVE": 5, "INVUL_SAVE": 7,
        "CC_WEAPONS": [_DOK_TOOLS, _URTY_SYRINGE],
        "UNIT_RULES": [_HOLD_STILL_RULE],
        "role": None,
    }


def _target_model(*, hp=2):
    return {
        "squad_id": "TGT", "player": 2,
        "T": 4, "col": 5, "row": 5, "level": 0, "HP_CUR": hp, "HP_MAX": hp,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 7,
        # Exige par `_resolve_one_manual_wound` (valeur detruite par point de vie perdu).
        "points_per_hp": 1.0, "VALUE": float(hp),
        "role": None, "UNIT_RULES": [],
    }


def _pain_unit():
    return {
        "id": "PAIN", "player": 1, "HP_CUR": 3, "HP_MAX": 3, "VALUE": 90.0,
        "UNIT_RULES": [], "keywords": [],
    }


def _target_unit(*, vehicle=False, hp=2):
    keywords = ["VEHICLE"] if vehicle else ["INFANTRY"]
    return {
        "id": "TGT", "player": 2, "HP_CUR": hp, "HP_MAX": hp, "VALUE": 10.0,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 7,
        "UNIT_RULES": [], "keywords": keywords,
    }


def _gs(*, vehicle=False, target_hp=2):
    attacker_model = _attacker_model()
    pain_unit = _pain_unit()
    tgt_unit = _target_unit(vehicle=vehicle, hp=target_hp)
    tgt_model = _target_model(hp=target_hp)
    return {
        "models_cache": {"PAIN#0": attacker_model, "TGT#0": tgt_model},
        "squad_models": {"PAIN": ["PAIN#0"], "TGT": ["TGT#0"]},
        "unit_by_id": {"PAIN": pain_unit, "TGT": tgt_unit},
        "units_cache": {
            "PAIN": {**pain_unit, "col": 0, "row": 0, "BASE_SHAPE": "round", "BASE_SIZE": 1},
            "TGT": {**tgt_unit, "col": 5, "row": 5, "BASE_SHAPE": "round", "BASE_SIZE": 1},
        },
        "squad_cache": {"PAIN": {"model_count_at_start": 1}, "TGT": {"model_count_at_start": 1}},
        "action_logs": [], "action_log_seq": 0, "turn": 1, "phase": "fight",
        "objectives": [],
        "waaagh_active_player": None,
        # Lu par `effective_invul_save` a la creation des groupes d'allocation (05.03), donc
        # atteint des que le lot est reellement resolu — ce que l'ancien harnais ne faisait pas.
        "waaagh_active": {},
        # Defenseur PROGRAMMATIQUE : le lot se resout sans rendre la main, ce qui est la
        # condition pour observer l'ordre degats normaux -> blessures mortelles en un appel.
        "player_types": {"0": "ai", "1": "ai", "2": "ai"},
        "_unit_move_version": 0,
        "config": {"game_rules": {"bonus_malus_cap": 0}},
    }


def _intent(*, weapon_index=1, n_attacks=1):
    return {
        "model_id": "PAIN#0",
        "target_unit_id": "TGT",
        "weapon_index": weapon_index,
        "n_attacks_resolved": n_attacks,
        "target_squad_size_at_declaration": 1,
    }


def _rolled(records):
    """`rolled` factice : chaque record devient une blessure en attente (save_roll=1)."""
    pending = [
        {"save_roll": 1, "rec": rec, "devastating": bool(rec.get("devastating"))}
        for rec in records
    ]
    return {
        "shot_records": list(records),
        "pending_wounds": pending,
        "counts": {"attacks": len(records), "hits": len(records), "wounds": len(records)},
    }


def _crit_rolled():
    return _rolled([{"criticalWound": True, "devastating": False}])


def _noncrit_rolled():
    return _rolled([{"criticalWound": False, "devastating": False}])


def _crit_devastating_rolled():
    return _rolled([{"criticalWound": True, "devastating": True}])


def _multi_crit_rolled():
    return _rolled([
        {"criticalWound": True, "devastating": False},
        {"criticalWound": True, "devastating": False},
        {"criticalWound": False, "devastating": False},
    ])


def _patch_fight_harness(monkeypatch, fake_rolled):
    """Monkeypatche les fonctions complexes pour isoler la logique Hold Still."""
    monkeypatch.setattr(fh, "waaagh_melee_bonus", lambda *a, **kw: 0)
    monkeypatch.setattr(fh, "resolve_oath_effects", lambda *a, **kw: (False, 0, 4))
    monkeypatch.setattr(fh, "resolve_hit_roll_modifiers", lambda *a, **kw: (3, None, None))
    monkeypatch.setattr(fh, "resolve_melee_wound_bonus", lambda *a, **kw: (4, None))
    monkeypatch.setattr(aseq, "build_weapon_attack_profile", lambda *a, **kw: None)
    monkeypatch.setattr(aseq, "roll_attack_pool", lambda **kw: fake_rolled)
    monkeypatch.setattr(fh, "display_save_threshold_with_waaagh", lambda *a, **kw: (4, False))


# ---------------------------------------------------------------------------
# Le crit N'EST PAS consommé : « also », pas « the attack sequence ends »
# ---------------------------------------------------------------------------

def test_crit_reste_dans_pending_wounds(monkeypatch):
    """ROUGE avant le fix : le record critique était filtré hors de `pending_wounds`, donc
    jamais alloué — aucune sauvegarde, aucun dégât normal, `Save [NOT ALLOCATED]` au journal.
    La datasheet dit « also » : la blessure suit sa séquence."""
    _patch_fight_harness(monkeypatch, _crit_rolled())
    monkeypatch.setattr(random, "randint", lambda a, b: 6)

    result = fh._manual_roll_fight_intent(_gs(), _intent(), {})
    assert result is not None
    assert len(result["pending_wounds"]) == 1, (
        f"le crit doit rester alloué normalement, got {result['pending_wounds']}"
    )
    assert result["counts"]["wounds"] == 1, (
        f"counts['wounds'] ne doit pas être décrémenté, got {result['counts']['wounds']}"
    )


def test_crit_porte_son_d6(monkeypatch):
    """Le D6 est tiré AU CRIT — granularité du jet, pas de l'activation.

    `dice` est le seul porteur du jet : la clé jumelle `holdStillMW`, posée sur le record et
    lue par personne en production, a été retirée. Ce que le jet vaut se vérifie donc là où il
    voyage réellement, jusqu'à `mortalWoundDice` et au segment `MW:` du journal.
    """
    _patch_fight_harness(monkeypatch, _crit_rolled())
    monkeypatch.setattr(random, "randint", lambda a, b: 4)

    result = fh._manual_roll_fight_intent(_gs(), _intent(), {})
    assert result is not None
    assert result["pending_mortal_wounds"] == {
        "ability": HAZARD_CONTEXT_HOLD_STILL, "dice": [4],
    }


def test_un_d6_par_crit(monkeypatch):
    """Deux crits = deux D6 distincts ; la blessure normale n'en produit aucun."""
    _patch_fight_harness(monkeypatch, _multi_crit_rolled())
    _rolls = iter([3, 5])
    monkeypatch.setattr(random, "randint", lambda a, b: next(_rolls))

    result = fh._manual_roll_fight_intent(_gs(), _intent(), {})
    assert result is not None
    assert result["pending_mortal_wounds"]["dice"] == [3, 5]
    assert result["counts"]["wounds"] == 3, "les trois blessures restent des blessures"
    assert len(result["pending_wounds"]) == 3


def test_aucune_bm_appliquee_au_jet(monkeypatch):
    """06.02 : rien n'est infligé au moment du jet — l'application appartient au lot."""
    _patch_fight_harness(monkeypatch, _crit_rolled())
    monkeypatch.setattr(random, "randint", lambda a, b: 6)

    gs = _gs()
    fh._manual_roll_fight_intent(gs, _intent(), {})
    assert gs["models_cache"]["TGT#0"]["HP_CUR"] == 2, "aucun PV ne doit bouger au jet"
    assert gs["action_logs"] == [], f"aucune ligne au jet, got {gs['action_logs']}"


# ---------------------------------------------------------------------------
# Conditions de déclenchement
# ---------------------------------------------------------------------------

def test_sans_crit_pas_de_bm(monkeypatch):
    _patch_fight_harness(monkeypatch, _noncrit_rolled())
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    result = fh._manual_roll_fight_intent(_gs(), _intent(), {})
    assert result is not None
    assert result["pending_mortal_wounds"] is None


def test_mauvaise_arme_pas_de_bm(monkeypatch):
    """weapon_index=0 = dok_tools : la règle nomme 'urty syringe et elle seule."""
    _patch_fight_harness(monkeypatch, _crit_rolled())
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    result = fh._manual_roll_fight_intent(_gs(), _intent(weapon_index=0), {})
    assert result is not None
    assert result["pending_mortal_wounds"] is None


def test_target_vehicle_pas_de_bm(monkeypatch):
    """« against a non-VEHICLE unit »."""
    _patch_fight_harness(monkeypatch, _crit_rolled())
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    result = fh._manual_roll_fight_intent(_gs(vehicle=True), _intent(), {})
    assert result is not None
    assert result["pending_mortal_wounds"] is None


def test_crit_devastating_produit_aussi_ses_bm(monkeypatch):
    """La datasheet n'excepte aucun critical wound. Le record reste dans `pending_wounds` :
    [DEVASTATING WOUNDS] 24.10 y saute la sauvegarde, il ne supprime pas la blessure."""
    _patch_fight_harness(monkeypatch, _crit_devastating_rolled())
    monkeypatch.setattr(random, "randint", lambda a, b: 2)

    result = fh._manual_roll_fight_intent(_gs(), _intent(), {})
    assert result is not None
    assert result["pending_mortal_wounds"]["dice"] == [2]
    assert len(result["pending_wounds"]) == 1


# ---------------------------------------------------------------------------
# 06.02 — les dégâts normaux d'abord, les blessures mortelles ensuite
# ---------------------------------------------------------------------------

def _e2e_gs(target_hp):
    gs = _gs(target_hp=target_hp)
    gs["units"] = [
        {"id": "PAIN", "player": 1, "unitType": "Fighter"},
        {"id": "TGT", "player": 2, "unitType": "Grunt"},
    ]
    gs["pending_squad_fight_intents"] = {"PAIN": [_intent(n_attacks=1)]}
    return gs


def _patch_e2e(monkeypatch, rolled, order_sink):
    """Harnais d'allocation complète : trace l'ORDRE des deux façons d'infliger des dégâts."""
    _patch_fight_harness(monkeypatch, rolled)
    monkeypatch.setattr(
        su, "_emit_squad_shoot_log",
        lambda gs, g, ctx: su.append_action_log(
            gs, {"type": "combat", "phase": "fight", "message": "FIGHT_LOG_STUB"}),
    )
    _real_resolve = su._resolve_one_manual_wound

    def _traced_resolve(game_state, alloc, batch, ctx):
        order_sink.append("NORMAL")
        return _real_resolve(game_state, alloc, batch, ctx)

    def _traced_mw(game_state, squad_id, n_wounds, auto_resolve, sink, **kw):
        order_sink.append(f"MW:{n_wounds}")
        return 0

    monkeypatch.setattr(su, "_resolve_one_manual_wound", _traced_resolve)
    monkeypatch.setattr(su, "allocate_mortal_wounds", _traced_mw)


def test_degats_normaux_avant_blessures_mortelles(monkeypatch):
    """06.02, « MORTAL WOUNDS AND NORMAL DAMAGE » : « resolve all of the normal damage first,
    then resolve all of the mortal wounds ».

    ROUGE avant le fix : `allocate_mortal_wounds` était appelé depuis le roller, donc AVANT
    même que les lots n'existent — la trace commençait par MW."""
    order: list = []
    _patch_e2e(monkeypatch, _multi_crit_rolled(), order)
    monkeypatch.setattr(random, "randint", lambda a, b: 1)

    fh.build_manual_fight_allocation(_e2e_gs(target_hp=9), "PAIN")

    assert order, "aucun dégât résolu : le harnais n'a pas atteint l'allocation"
    assert order[-1].startswith("MW:"), f"les BM doivent venir en dernier, got {order}"
    assert order.count("NORMAL") == 3, f"les 3 blessures normales doivent être résolues, got {order}"
    assert order[-1] == "MW:2", f"2 BM attendues (deux crits, D6=1 chacun), got {order[-1]}"


# ---------------------------------------------------------------------------
# DÉFENSEUR HUMAIN : les blessures mortelles se choisissent (06.02), lot mortel manuel
# ---------------------------------------------------------------------------

def _human_defender_gs():
    """Cible de TROIS figurines à 3 PV, défenseur HUMAIN (siège 2), attaquant machine.

    Trois blessures normales tuent exactement une figurine (3 × 1 PV) ; les blessures mortelles
    tombent ensuite sur deux survivantes INTACTES — c'est le seul état où 06.02 laisse un choix
    (« Otherwise … you must select one of those models »), une figurine entamée étant forcée.
    """
    gs = _e2e_gs(target_hp=3)
    for i in (1, 2):
        gs["models_cache"][f"TGT#{i}"] = {**_target_model(hp=3), "col": 5 + i, "row": 5}
        gs["squad_models"]["TGT"].append(f"TGT#{i}")
    gs["squad_cache"]["TGT"] = {"model_count_at_start": 3}
    gs["units_cache"]["TGT"]["HP_CUR"] = 9
    gs["player_types"] = {"0": "ai", "1": "ai", "2": "human"}
    return gs


def _drive_human_allocation(gs, first_result, choose):
    """Joue le défenseur humain : ordre des groupes tel quel, figurine par `choose(payload)`.

    Rend la trace des payloads reçus (action, damage_type, choix) et le résultat final."""
    trace = []
    result = first_result
    guard = 0
    while result.get("waiting_for_player") and guard < 20:
        guard += 1
        if result["action"] == fh.FIGHT_CTX.declare_order_action:
            req = result["order_request"]
            trace.append(("order", req.get("damage_type"), [g["group_id"] for g in req["groups"]]))
            result = su.apply_manual_shoot_declare_order(
                gs, [g["group_id"] for g in req["groups"]], fh.FIGHT_CTX
            )
        else:
            alloc = result["allocation"]
            picked = choose(alloc)
            trace.append(("alloc", alloc.get("damage_type"), [c["model_id"] for c in alloc["choices"]], picked))
            result = su.apply_manual_shoot_allocation(gs, picked, fh.FIGHT_CTX)
    return trace, result


def test_defenseur_humain_choisit_la_figurine_qui_encaisse_les_bm(monkeypatch):
    """ROUGE avant le fix : à la fermeture du lot, `allocate_mortal_wounds(…, True, …)` prenait
    `eligibles[0]` d'office, même pour un défenseur humain — alors que Desperate Escape et
    [HAZARDOUS] lui laissaient le choix. 06.02 : « its controlling player must resolve the
    following sequence … you must select one of those models ».

    Ici : 3 blessures normales (clic TGT#0, puis forcées sur la figurine entamée) tuent TGT#0 ;
    puis un LOT MORTEL de 2 BM (deux crits, D6=1 chacun) rend la main avec `damage_type:
    mortal` et deux candidates intactes ; le défenseur clique TGT#2, la seconde BM y est forcée
    (figurine entamée). TGT#1 reste intacte : le choix a été respecté.
    """
    gs = _human_defender_gs()
    _patch_fight_harness(monkeypatch, _multi_crit_rolled())
    monkeypatch.setattr(
        su, "_emit_squad_shoot_log",
        lambda g_s, g, ctx: su.append_action_log(
            g_s, {"type": "combat", "phase": "fight", "message": "FIGHT_LOG_STUB"}),
    )
    # La mort d'une figurine recalcule les caches d'escouade (OC, empreinte…) que ce fixture
    # minimal ne porte pas : on ne garde de `destroy_model` que le retrait du cache, ce qui est
    # tout ce que la couche d'allocation observe (`_group_alive`, candidats vivants).
    monkeypatch.setattr(
        su, "destroy_model",
        lambda g_s, mid, reason=None: g_s["models_cache"].pop(mid, None),
    )
    monkeypatch.setattr(random, "randint", lambda a, b: 1)
    auto_calls: list = []
    monkeypatch.setattr(
        su, "allocate_mortal_wounds",
        lambda *a, **kw: auto_calls.append(a) or 0,
    )

    first = fh.build_manual_fight_allocation(gs, "PAIN")
    assert first.get("waiting_for_player"), "défenseur humain : la main doit lui être rendue"

    def _choose(alloc):
        choices = [c["model_id"] for c in alloc["choices"]]
        if alloc.get("damage_type") == "mortal":
            assert choices == ["TGT#1", "TGT#2"], f"deux survivantes intactes attendues, got {choices}"
            return "TGT#2"
        return "TGT#0"

    trace, final = _drive_human_allocation(gs, first, _choose)

    assert final.get("done") is True, final
    assert auto_calls == [], "le régime AUTO ne doit pas s'appliquer à un défenseur humain"
    mortal_payloads = [t for t in trace if t[1] == "mortal"]
    assert mortal_payloads, f"aucun payload mortel rendu au défenseur : {trace}"
    # Les BM viennent APRÈS toutes les blessures normales (06.02).
    first_mortal = trace.index(mortal_payloads[0])
    assert all(t[1] != "mortal" for t in trace[:first_mortal]) and first_mortal > 0, trace
    # Effets : TGT#0 morte des dégâts normaux, TGT#2 choisie (2 BM), TGT#1 intacte.
    assert "TGT#0" not in gs["models_cache"], "TGT#0 aurait dû mourir des 3 blessures normales"
    assert gs["models_cache"]["TGT#1"]["HP_CUR"] == 3, "TGT#1 n'a pas été choisie"
    assert gs["models_cache"]["TGT#2"]["HP_CUR"] == 1, "TGT#2 devait encaisser les 2 BM"
    # La ligne SUFFERS déjà émise porte les deux records d'attribution, sur TGT#2.
    mw_logs = [e for e in gs["action_logs"] if e["type"] == "mortal_wounds_ability"]
    assert len(mw_logs) == 1, mw_logs
    assert [d["modelId"] for d in mw_logs[0]["hazardDetails"]] == ["TGT#2", "TGT#2"]
    assert mw_logs[0]["hazardousMortalWounds"] == 2
    assert final["shoot_result"]["damage_total"] == 5, final["shoot_result"]


def test_defenseur_machine_garde_le_regime_auto(monkeypatch):
    """VERT VACANT du test ci-dessus : avec un défenseur programmatique, aucun lot mortel n'est
    inséré et `allocate_mortal_wounds` reste l'attributaire — le régime d'entraînement ne bouge
    pas."""
    gs = _human_defender_gs()
    gs["player_types"]["2"] = "ai"
    _patch_fight_harness(monkeypatch, _multi_crit_rolled())
    monkeypatch.setattr(
        su, "destroy_model",
        lambda g_s, mid, reason=None: g_s["models_cache"].pop(mid, None),
    )
    monkeypatch.setattr(
        su, "_emit_squad_shoot_log",
        lambda g_s, g, ctx: su.append_action_log(
            g_s, {"type": "combat", "phase": "fight", "message": "FIGHT_LOG_STUB"}),
    )
    monkeypatch.setattr(random, "randint", lambda a, b: 1)
    auto_calls: list = []
    monkeypatch.setattr(
        su, "allocate_mortal_wounds",
        lambda g_s, sid, n, auto, sink, **kw: auto_calls.append((sid, n, auto)) or 0,
    )
    result = fh.build_manual_fight_allocation(gs, "PAIN")
    assert result.get("done") is True, result
    assert auto_calls == [("TGT", 2, True)], auto_calls


def _fake_batch():
    """Lot minimal portant une dette de blessures mortelles, tel que le construit
    `_build_manual_allocation`."""
    return {
        "target_sid": "TGT",
        "pending_mortal_wounds": {"ability": HAZARD_CONTEXT_HOLD_STILL, "dice": [6]},
    }


def _fake_alloc():
    return {"attacker_squad_id": "PAIN", "summary": {"damage_total": 0, "models_killed": 0}}


def test_bm_appliquees_une_seule_fois(monkeypatch):
    """Idempotence : la fermeture du lot consomme la dette, une reprise ne la rejoue pas.

    Le défenseur humain rend la main plusieurs fois au cours d'un même lot ; sans cette
    remise à None, chaque reprise infligerait à nouveau les mêmes blessures mortelles."""
    calls: list = []
    monkeypatch.setattr(
        su, "allocate_mortal_wounds",
        lambda gs, sid, n, auto, sink, **kw: calls.append((sid, n)) or 0,
    )

    gs, alloc, batch = _gs(), _fake_alloc(), _fake_batch()
    su._apply_batch_mortal_wounds(gs, alloc, batch, fh.FIGHT_CTX)
    su._apply_batch_mortal_wounds(gs, alloc, batch, fh.FIGHT_CTX)

    assert calls == [("TGT", 6)], f"une seule application attendue, got {calls}"
    assert len([e for e in gs["action_logs"] if e["type"] == "mortal_wounds_ability"]) == 1


def test_ligne_step_log_des_blessures_mortelles(monkeypatch):
    """Sans ligne dédiée, les D6 BM n'apparaissaient NULLE PART dans le journal : le type
    `hold_still_mortal_wounds` n'était dans aucune entrée de `_STEP_LOG_TYPE_MAP`."""
    order: list = []
    _patch_e2e(monkeypatch, _crit_rolled(), order)
    monkeypatch.setattr(random, "randint", lambda a, b: 5)

    gs = _e2e_gs(target_hp=9)
    fh.build_manual_fight_allocation(gs, "PAIN")

    mw_logs = [e for e in gs["action_logs"] if e["type"] == "mortal_wounds_ability"]
    assert len(mw_logs) == 1, f"une ligne de blessures mortelles attendue, got {gs['action_logs']}"
    entry = mw_logs[0]
    assert entry["hazardousMortalWounds"] == 5
    assert entry["mortalWoundDice"] == [5]
    # Meme grammaire que la ligne step.log : `MW:` gouverne par `mortalWoundDice`, sans `Trigger:`.
    assert "SUFFERS 5 Mortal Wounds [HOLD STILL AND SAY AARGH] MW:5 [FROM:PAIN]" in entry["message"], entry["message"]
    assert entry["hazardContext"] == HAZARD_CONTEXT_HOLD_STILL
    assert entry["unitId"] == "TGT", "la ligne SUFFERS nomme la VICTIME"
    assert entry["mortalWoundSourceId"] == "PAIN", "la source doit être créditée"


def test_cible_detruite_aucune_ligne(monkeypatch):
    """Cible morte des dégâts normaux : rien à infliger (06.02, « until … that unit is
    destroyed »), donc rien à journaliser."""
    calls: list = []
    monkeypatch.setattr(
        su, "allocate_mortal_wounds",
        lambda gs, sid, n, auto, sink, **kw: calls.append((sid, n)) or 0,
    )

    gs = _gs()
    # `destroy_model` retire l'escouade de `units_cache` a sa derniere figurine : c'est cet
    # etat-la, et lui seul, que `is_unit_alive` observe.
    gs["models_cache"].pop("TGT#0")
    gs["squad_models"]["TGT"] = []
    gs["units_cache"].pop("TGT")

    su._apply_batch_mortal_wounds(gs, _fake_alloc(), _fake_batch(), fh.FIGHT_CTX)

    assert not calls, f"aucune blessure mortelle à infliger, got {calls}"
    assert not [e for e in gs["action_logs"] if e["type"] == "mortal_wounds_ability"]
