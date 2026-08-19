"""[HAZARDOUS] 24.15 en MELEE, sur le chemin VIF (`build_manual_fight_allocation`).

PDF 24.15 (source de verite) : « Each time a unit is selected to shoot OR SELECTED TO FIGHT,
after that unit has resolved all of its attacks, make a number of hazard rolls (06.03) for
that unit equal to the number of [HAZARDOUS] weapons you selected in the Select Weapons step. »
PDF 06.03 : « roll one D6 : on a 1-2, that roll fails and that unit suffers 1 mortal wound, or
3 mortal wounds instead if each model in that unit is a MONSTER/VEHICLE model. »

Ce fichier portait auparavant des tests de TIR appeles sur le code mort de
`shooting_handlers` (supprime en V11 §0.38) : ils dupliquaient test_special_rules_e2e.py, ne
touchaient jamais la melee malgre leur nom, et surtout le mort implementait HAZARDOUS
CONTRE le PDF — un jet PAR ATTAQUE, declenche sur 1 seulement, sans blessure mortelle
appliquee. Le volet TIR est verrouille par test_hazardous.py ; ce fichier verrouille le
volet MELEE, que rien ne couvrait : `FIGHT_CTX.hazard_origin = "fight"` est le seul point
de cablage de la clause « or selected to fight ».

Sequence des des (1 attaque) : touche -> blessure -> sauvegarde, PUIS le(s) jet(s) de
hasard. `_seq` echoue si le moteur tire plus ou moins de des que la sequence declaree.
"""
import random

from engine.phase_handlers.fight_handlers import build_manual_fight_allocation
from tests._state_invariants import turn_state_invariants


def _seq(monkeypatch, rolls):
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee : le moteur a tire plus de des que prevu"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    return seq


def _kw(*names):
    return [{"keywordId": n} for n in names]


def _game_state(weapon_rules, *, attackers=1, attacker_keywords=("INFANTRY",), attacker_hp=3):
    """Escouade '1' (au contact de '2') avec une arme de melee par figurine."""
    weapon = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
              "WEAPON_RULES": list(weapon_rules), "display_name": "Eviscerator"}
    models = {}
    intents = []
    for i in range(attackers):
        mid = f"A{i}"
        models[mid] = {
            "id": mid, "squad_id": "1", "player": 0, "T": 4, "ATTACK_LEFT": 1,
            "HP_CUR": attacker_hp, "HP_MAX": attacker_hp, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
            "role": None, "unitType": "Fighter", "points_per_hp": 5.0, "VALUE": 10.0,
            "col": 0, "row": 0, "UNIT_KEYWORDS": _kw(*attacker_keywords),
            "CC_WEAPONS": [dict(weapon)],
        }
        intents.append({"model_id": mid, "target_unit_id": "2", "weapon_index": 0,
                        "n_attacks_resolved": 1, "target_squad_size_at_declaration": 1})
    models["T1"] = {"id": "T1", "squad_id": "2", "player": 1, "T": 4, "HP_CUR": 9, "HP_MAX": 9,
                    "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt",
                    "points_per_hp": 5.0, "VALUE": 10.0, "col": 1, "row": 0,
                    "UNIT_KEYWORDS": _kw("INFANTRY")}
    return {**turn_state_invariants(),
        "gym_training_mode": True,
        "turn": 1, "phase": "fight",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": models,
        "squad_models": {"1": [f"A{i}" for i in range(attackers)], "2": ["T1"]},
        "squad_cache": {"1": {"model_count_at_start": attackers},
                        "2": {"model_count_at_start": 1}},
        "units_cache": {"1": {"col": 0, "row": 0, "VALUE": 10.0, "player": 0},
                        "2": {"col": 1, "row": 0, "VALUE": 10.0, "player": 1}},
        "units": [{"id": "1", "player": 0, "UNIT_KEYWORDS": _kw(*attacker_keywords)},
                  {"id": "2", "player": 1, "UNIT_KEYWORDS": _kw("INFANTRY")}],
        "unit_by_id": {
            "1": {"id": "1", "player": 0, "UNIT_RULES": [], "UNIT_KEYWORDS": _kw(*attacker_keywords)},
            "2": {"id": "2", "player": 1, "UNIT_RULES": [], "UNIT_KEYWORDS": _kw("INFANTRY")},
        },
        "objectives": [],
        "pending_squad_fight_intents": {"1": intents},
    }


def _hp(gs, mid):
    return gs["models_cache"][mid]["HP_CUR"]


def test_hazardous_est_jete_aussi_quand_l_unite_combat(monkeypatch):
    """24.15 clause « or selected to fight » : le jet de hasard rate (2) coute 1 MW au combattant."""
    seq = _seq(monkeypatch, [4, 5, 1, 2])  # touche, blessure, sauvegarde ratee, PUIS hasard = 2
    gs = _game_state(["HAZARDOUS"])

    build_manual_fight_allocation(gs, "1")

    assert _hp(gs, "A0") == 2, "hasard rate en melee : 1 blessure mortelle sur le combattant"
    assert _hp(gs, "T1") == 8, "l attaque elle-meme a bien inflige son degat"
    assert seq == [], "un seul jet de hasard pour une seule arme HAZARDOUS"


def test_hazardous_reussi_ne_coute_rien_en_melee(monkeypatch):
    """06.03 : un 3 reussit -> aucune blessure mortelle (discrimination du seuil 1-2)."""
    seq = _seq(monkeypatch, [4, 5, 1, 3])
    gs = _game_state(["HAZARDOUS"])

    build_manual_fight_allocation(gs, "1")

    assert _hp(gs, "A0") == 3
    assert seq == []


def test_sans_hazardous_aucun_jet_en_melee(monkeypatch):
    """Contre-epreuve fonctionnelle : sans la regle, aucun de de hasard n est tire."""
    seq = _seq(monkeypatch, [4, 5, 1])
    gs = _game_state([])

    build_manual_fight_allocation(gs, "1")

    assert _hp(gs, "A0") == 3
    assert seq == [], "aucun de supplementaire : la sequence s arrete a la sauvegarde"


def test_un_jet_par_arme_hazardous_pas_par_figurine_en_melee(monkeypatch):
    """24.15 : deux combattants = deux armes HAZARDOUS selectionnees -> DEUX jets."""
    seq = _seq(monkeypatch, [4, 5, 1,  4, 5, 1,  1, 1])  # 2 attaques, puis 2 hasards rates
    gs = _game_state(["HAZARDOUS"], attackers=2)

    build_manual_fight_allocation(gs, "1")

    assert _hp(gs, "A0") + _hp(gs, "A1") == 4, "2 armes HAZARDOUS = 2 MW (6 PV - 2)"
    assert seq == []


def test_trois_mw_si_toutes_les_figurines_sont_vehicules_en_melee(monkeypatch):
    """06.03 : 3 MW au lieu d 1 si CHAQUE figurine de l unite est MONSTER/VEHICLE."""
    _seq(monkeypatch, [4, 5, 1, 1])
    gs = _game_state(["HAZARDOUS"], attacker_keywords=("VEHICLE",), attacker_hp=9)

    build_manual_fight_allocation(gs, "1")

    assert _hp(gs, "A0") == 6, "vehicule : 3 MW"


def test_hazardous_et_devastating_sur_la_meme_arme(monkeypatch):
    """Interaction : la blessure critique saute la sauvegarde ET le hasard est jete apres.

    Les deux effets sont independants — l un porte sur la cible, l autre sur le porteur."""
    # 3 des : la sauvegarde n est pas faite sur un critique DEVASTATING (24.10).
    seq = _seq(monkeypatch, [4, 6, 1])  # touche, blessure CRITIQUE, hasard rate
    gs = _game_state(["HAZARDOUS", "DEVASTATING_WOUNDS"])

    build_manual_fight_allocation(gs, "1")

    assert _hp(gs, "T1") == 8, "critique DEVASTATING : degat inflige malgre la save 6"
    assert _hp(gs, "A0") == 2, "hasard rate : 1 MW sur le porteur de l arme"
    assert seq == []
