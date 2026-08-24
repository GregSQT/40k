"""Sequence d attaque au TIR, BOUT-EN-BOUT sur le chemin VIF (05 Attack sequence).

Porte du code mort de tir (`shooting_handlers`, supprime en V11 §0.38) vers le chemin
partage gym/PvP : `build_manual_shoot_allocation` -> `_manual_roll_intent` ->
`attack_sequence.roll_attack_pool` -> `_resolve_one_manual_wound`.

Ce que ce fichier verrouille, et que le code mort ne prouvait pas : la sequence complete
telle que le moteur la joue reellement, jusqu aux PV retires a la cible.

Ordre des des (05, verrouille par la sequence explicite de chaque test) :
touche -> blessure -> sauvegarde. La sauvegarde n est tiree QUE si la blessure passe, et
les degats ne sont resolus QU a l allocation, sur la figurine choisie (05.03/05.04) : une
sequence de des trop longue ou trop courte fait ROUGIR le test (`_seq` verifie les deux).

Mode `gym_training_mode` : le defenseur est programmatique, l allocation se resout sans
prompt — c est le meme code que le PvP, sans l aller-retour frontend.
"""
import random

from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.shared_utils import build_manual_shoot_allocation
from tests._state_invariants import turn_state_invariants
from tests.unit.engine._state_builders import units_cache_entry as _uc


def _seq(monkeypatch, rolls):
    """Des scriptes : epuisement = erreur explicite. Le reste rendu deterministe (cover)."""
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee : le moteur a tire plus de des que prevu"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    return seq



def _game_state(*, bs=4, strength=4, ap=0, dmg=1, toughness=4, armor_save=4, hp=3,
                weapon_rules=None, target_keywords=("INFANTRY",)):
    """1 tireur (escouade '1') vs 1 cible (escouade '2'), 1 attaque resolue."""
    weapon = {"ATK": bs, "STR": strength, "AP": ap, "DMG": dmg, "NB": 1, "RNG": 24,
              "WEAPON_RULES": list(weapon_rules or []), "code": "test_plasma_gun", "display_name": "Plasma Gun"}
    attacker = {"id": "A1", "squad_id": "1", "player": 0, "T": 4, "SHOOT_LEFT": 1,
                "col": 0, "row": 0, "RNG_WEAPONS": [weapon]}
    target = {"id": "T1", "squad_id": "2", "player": 1, "T": toughness,
              "HP_CUR": hp, "HP_MAX": hp, "ARMOR_SAVE": armor_save, "INVUL_SAVE": 7,
              "role": None, "unitType": "Grunt", "points_per_hp": 5.0, "VALUE": 10.0,
              "col": 9, "row": 9}
    return {**turn_state_invariants(),
        "gym_training_mode": True,
        "turn": 1, "phase": "shoot",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": {"A1": attacker, "T1": target},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": 1}},
        "units_cache": {"1": _uc(0, 0, player=0), "2": _uc(9, 9, player=1)},
        "units": [{"id": "1", "player": 0}, {"id": "2", "player": 1}],
        "unit_by_id": {
            "1": {"id": "1", "UNIT_RULES": []},
            "2": {"id": "2", "UNIT_RULES": [],
                  "UNIT_KEYWORDS": [{"keywordId": k} for k in target_keywords]},
        },
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        "pending_squad_shoot_intents": {
            "1": [{"model_id": "A1", "target_unit_id": "2", "weapon_index": 0,
                   "n_attacks_resolved": 1, "target_squad_size_at_declaration": 1}]
        },
    }


def _records(gs):
    """Records de tir (shootDetails) concatenes depuis les logs emis."""
    out = []
    for log in gs["action_logs"]:
        out.extend(log.get("shootDetails", []) if isinstance(log, dict) else [])
    return out


def _hp(gs):
    return gs["models_cache"]["T1"]["HP_CUR"]


# ─────────────────────────────────────────────────────────────────────────────
# Issues de la sequence : les quatre sorties possibles d une attaque
# ─────────────────────────────────────────────────────────────────────────────

def test_touche_blesse_save_ratee_inflige_les_degats(monkeypatch):
    """BS4 / S4 vs T4 (blessure 4+) / Sv4+ : 4, 4, 2 -> save ratee -> DMG=2 PV retires."""
    seq = _seq(monkeypatch, [4, 4, 2])
    gs = _game_state(dmg=2, hp=3)

    build_manual_shoot_allocation(gs, "1")

    assert _hp(gs) == 1, "save ratee : les 2 degats doivent etre appliques"
    rec = _records(gs)[0]
    assert rec["hitResult"] == "HIT"
    assert rec["strengthResult"] == "SUCCESS"
    assert rec["saveSuccess"] is False
    assert rec["damageDealt"] == 2
    assert seq == [], "aucun de en trop : touche, blessure, sauvegarde"


def test_touche_ratee_arrete_la_sequence(monkeypatch):
    """Un jet de touche sous le seuil (2 < 4) : aucun autre de, aucun degat."""
    seq = _seq(monkeypatch, [2])
    gs = _game_state()

    build_manual_shoot_allocation(gs, "1")

    assert _hp(gs) == 3
    rec = _records(gs)[0]
    assert rec["hitResult"] == "MISS"
    assert rec["attackRoll"] == 2
    assert seq == [], "ni blessure ni sauvegarde apres une touche ratee"


def test_blessure_ratee_arrete_la_sequence(monkeypatch):
    """S2 vs T4 -> blessure 6+ ; un 3 echoue : aucune sauvegarde tiree, aucun degat."""
    seq = _seq(monkeypatch, [4, 3])
    gs = _game_state(strength=2)

    build_manual_shoot_allocation(gs, "1")

    assert _hp(gs) == 3
    rec = _records(gs)[0]
    assert rec["hitResult"] == "HIT"
    assert rec["strengthResult"] == "FAILED"
    assert rec["strengthRoll"] == 3
    assert seq == [], "aucune sauvegarde tiree apres une blessure ratee"


def test_sauvegarde_reussie_annule_les_degats(monkeypatch):
    """Sv4+ et jet de 5 : la sauvegarde passe -> 0 degat malgre la blessure."""
    seq = _seq(monkeypatch, [4, 4, 5])
    gs = _game_state(dmg=2)

    build_manual_shoot_allocation(gs, "1")

    assert _hp(gs) == 3
    rec = _records(gs)[0]
    assert rec["strengthResult"] == "SUCCESS"
    assert rec["saveSuccess"] is True
    assert rec["damageDealt"] == 0
    assert seq == []


# ─────────────────────────────────────────────────────────────────────────────
# AP : la penetration degrade le seuil de sauvegarde
# ─────────────────────────────────────────────────────────────────────────────

def test_ap_degrade_le_seuil_de_sauvegarde(monkeypatch):
    """Sv4+ avec AP -1 -> seuil 5+ : un 4 qui aurait sauve devient un echec."""
    seq = _seq(monkeypatch, [4, 4, 4])
    gs = _game_state(ap=-1, armor_save=4, dmg=1)

    build_manual_shoot_allocation(gs, "1")

    assert _hp(gs) == 2, "save 4 < seuil 5 (AP-1) : degat applique"
    rec = _records(gs)[0]
    assert rec["saveTarget"] == 5
    assert rec["saveSuccess"] is False
    assert seq == []


def test_sans_ap_le_meme_jet_sauve(monkeypatch):
    """Contre-epreuve du test precedent : meme jet de 4, AP 0 -> seuil 4+, la save passe."""
    seq = _seq(monkeypatch, [4, 4, 4])
    gs = _game_state(ap=0, armor_save=4, dmg=1)

    build_manual_shoot_allocation(gs, "1")

    assert _hp(gs) == 3, "sans AP, le 4 atteint le seuil 4+ : aucun degat"
    rec = _records(gs)[0]
    assert rec["saveTarget"] == 4
    assert rec["saveSuccess"] is True
    assert seq == []


def test_invulnerable_ignore_l_ap(monkeypatch):
    """05.04 : la sauvegarde invulnerable ignore l AP. Sv6+/Inv4+ avec AP -3 -> seuil 4+."""
    seq = _seq(monkeypatch, [4, 4, 4])
    gs = _game_state(ap=-3, armor_save=6, dmg=1)
    gs["models_cache"]["T1"]["INVUL_SAVE"] = 4

    build_manual_shoot_allocation(gs, "1")

    assert _hp(gs) == 3, "l invulnerable 4+ n est pas degradee par l AP : le 4 sauve"
    assert _records(gs)[0]["saveTarget"] == 4
    assert seq == []


# ─────────────────────────────────────────────────────────────────────────────
# Contrat du record : ce que le log/frontend consomme
# ─────────────────────────────────────────────────────────────────────────────

def test_le_record_porte_les_trois_jets_et_leurs_seuils(monkeypatch):
    """Les valeurs de des ET les seuils atteints sont traces (source du combat log)."""
    _seq(monkeypatch, [5, 4, 2])
    gs = _game_state(bs=4, strength=4, armor_save=4, dmg=1)

    build_manual_shoot_allocation(gs, "1")

    rec = _records(gs)[0]
    assert (rec["attackRoll"], rec["hitTarget"]) == (5, 4)
    assert (rec["strengthRoll"], rec["woundTarget"]) == (4, 4)
    assert (rec["saveRoll"], rec["saveTarget"]) == (2, 4)


def test_le_nom_de_l_arme_est_publie_dans_le_log(monkeypatch):
    """Le combat log nomme l arme utilisee (display_name de l arme selectionnee)."""
    _seq(monkeypatch, [2])
    gs = _game_state()

    build_manual_shoot_allocation(gs, "1")

    messages = " ".join(l["message"] for l in gs["action_logs"] if "message" in l)
    assert "Plasma Gun" in messages, messages


# ─────────────────────────────────────────────────────────────────────────────
# 05.01 / 05.04 : le 1 non modifie rate TOUJOURS, y compris quand le seuil vaut 1
#
# ⚠️ Ces deux tests n ont de contenu QUE si le seuil peut descendre a 1 : sur un seuil >= 2,
# un 1 echoue de toute facon par comparaison, et la clause « 1 non modifie » ne porte rien
# (contre-epreuve mutation : retirer le garde `== NATURAL_FAIL_ROLL` laisse le test VERT).
# Les deux seuils a 1 sont ATTEIGNABLES avec les donnees du projet, d ou les profils choisis.
# ─────────────────────────────────────────────────────────────────────────────

def test_un_1_non_modifie_rate_la_touche_meme_sur_un_seuil_de_1(monkeypatch):
    """05.01 sur BS 1+ — profil reel : deux armes des armories declarent `ATK: 1`.

    Sans la clause, 1 >= 1 toucherait. Contre-epreuve mutation : neutraliser
    `hit_roll == NATURAL_FAIL_ROLL` dans `roll_attack_pool` -> ce test rougit."""
    seq = _seq(monkeypatch, [1])
    gs = _game_state(bs=1)

    build_manual_shoot_allocation(gs, "1")

    assert _records(gs)[0]["hitResult"] == "MISS"
    assert seq == [], "aucun de de blessure : la touche a rate"


def test_une_sauvegarde_de_1_echoue_meme_sur_un_seuil_de_1(monkeypatch):
    """05.04 sur un seuil de sauvegarde de 1+ : le 1 echoue quand meme.

    Seuil 1 obtenu avec un AP **positif** sur une Sv 2+ (`save_threshold` : `armure - ap`).
    ⚠️ Ce profil n est pas theorique : `bone_cleaver` (tyranid/armory.ts) declare `AP: 1`,
    seule valeur d AP > 0 des armories — vraisemblablement un signe manquant, signale mais
    non corrige ici (une correction de datasheet demande une source, absente des PDF du
    projet qui ne portent que les regles de base). Contre-epreuve mutation : neutraliser
    `save_roll != 1` dans `_resolve_one_manual_wound` -> ce test rougit."""
    seq = _seq(monkeypatch, [4, 4, 1])
    gs = _game_state(ap=1, armor_save=2, dmg=1)

    build_manual_shoot_allocation(gs, "1")

    assert _records(gs)[0]["saveTarget"] == 1, "AP +1 sur Sv2+ -> seuil de sauvegarde 1"
    assert _hp(gs) == 2, "un 1 non modifie rate toujours la sauvegarde"
    assert _records(gs)[0]["saveSuccess"] is False
    assert seq == []


# ─────────────────────────────────────────────────────────────────────────────
# [ANTI-X Y+] 24.03 — CABLAGE au tir (le socle est verrouille par
# test_weapon_rules_attack_sequence.py, la melee par test_weapon_rules_fight.py ; le tir
# n etait couvert par RIEN avant V11 §0.38)
# ─────────────────────────────────────────────────────────────────────────────

def test_anti_keyword_abaisse_le_seuil_de_blessure_critique_au_tir(monkeypatch):
    """[ANTI-INFANTRY 5+] contre une cible INFANTRY : un 5 devient une blessure CRITIQUE,
    donc une blessure — alors que le seuil normal (S1 vs T10) est de 6+.

    C est le seul cas ou 05.02 est observable a travers le cablage de tir : `wound_threshold`
    plafonne a 6, donc sans [ANTI] un 6 passe deja par la voie normale et la clause critique
    ne porte rien."""
    seq = _seq(monkeypatch, [4, 5, 2])
    gs = _game_state(strength=1, toughness=10, weapon_rules=["ANTI_INFANTRY:5"],
                     target_keywords=("INFANTRY",))

    build_manual_shoot_allocation(gs, "1")

    rec = _records(gs)[0]
    assert rec["strengthResult"] == "SUCCESS", "5 >= seuil ANTI 5+ -> blessure critique"
    assert rec.get("criticalWound") is True
    assert _hp(gs) == 2
    assert seq == []


def test_anti_sans_le_keyword_sur_la_cible_ne_s_applique_pas_au_tir(monkeypatch):
    """Discrimination : meme arme, cible VEHICLE -> le 5 reste un echec face au seuil 6+."""
    seq = _seq(monkeypatch, [4, 5])
    gs = _game_state(strength=1, toughness=10, weapon_rules=["ANTI_INFANTRY:5"],
                     target_keywords=("VEHICLE",))

    build_manual_shoot_allocation(gs, "1")

    assert _records(gs)[0]["strengthResult"] == "FAILED"
    assert _hp(gs) == 3
    assert seq == [], "aucune sauvegarde tiree : la blessure a echoue"
