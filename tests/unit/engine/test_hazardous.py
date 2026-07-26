"""[HAZARDOUS] 24.15 — jets de hasard après que l'unité a résolu toutes ses attaques.

PDF 24.15 : « Each time a unit is selected to shoot or selected to fight, AFTER that unit has
resolved all of its attacks, make a number of hazard rolls (06.03) for that unit equal to the
number of [HAZARDOUS] weapons you selected in the Select Weapons step. »
PDF 06.03 : « roll one D6: on a 1-2, that roll fails and that unit suffers 1 mortal wound, or
3 mortal wounds instead if EACH model in that unit is a MONSTER/VEHICLE model. »

⚠ La spec suivie est le PDF, PAS `config/weapon_rules.json` (qui dit « on a 1 → 3 MW »,
faux sur les deux points). Arbitrage utilisateur 2026-07-26 : le PDF fait foi.

Concernées dans les rosters de training : `plasma_pistol_supercharge` (Vanguard Plasma),
`smite_focused_witchfire` (Librarian).

Tests BOUT-EN-BOUT via `build_manual_shoot_allocation` en `gym_training_mode` : verrouillent
le déclenchement (fin d'activation), le NOMBRE de jets (par arme, pas par figurine) et les
dégâts (mortal wounds sur le TIREUR).
"""
import random

import pytest

from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.shared_utils import build_manual_shoot_allocation, roll_hazard_for_unit


def _seq(monkeypatch, rolls):
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})


def _uc(col, row, *, player):
    return {"BASE_SHAPE": "round", "BASE_SIZE": 1, "col": col, "row": row,
            "occupied_hexes": set(), "VALUE": 10.0, "player": player}


def _kw(*names):
    return [{"keywordId": n} for n in names]


def _shooter_model(mid, weapon, *, keywords=("INFANTRY",)):
    return {"id": mid, "squad_id": "1", "player": 0, "T": 4, "SHOOT_LEFT": 1,
            "HP_CUR": 2, "HP_MAX": 2, "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "role": None,
            "unitType": "Shooter", "points_per_hp": 5.0, "VALUE": 10.0,
            "col": 0, "row": 0, "UNIT_KEYWORDS": _kw(*keywords), "RNG_WEAPONS": [weapon]}


def _game_state(weapon_rules, *, shooters=1, shooter_keywords=("INFANTRY",)):
    weapon = {"BS": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
              "WEAPON_RULES": list(weapon_rules), "display_name": "Plasma"}
    models = {}
    intents = []
    for i in range(shooters):
        mid = f"A{i}"
        models[mid] = _shooter_model(mid, dict(weapon), keywords=shooter_keywords)
        intents.append({"model_id": mid, "target_unit_id": "2", "weapon_index": 0,
                        "n_attacks_resolved": 1, "target_squad_size_at_declaration": 1})
    models["T1"] = {"id": "T1", "squad_id": "2", "player": 1, "T": 4, "HP_CUR": 9, "HP_MAX": 9,
                    "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt",
                    "points_per_hp": 5.0, "VALUE": 10.0, "col": 9, "row": 9,
                    "UNIT_KEYWORDS": _kw("INFANTRY")}
    return {
        "gym_training_mode": True,
        "turn": 1, "phase": "shoot",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": models,
        "squad_models": {"1": [f"A{i}" for i in range(shooters)], "2": ["T1"]},
        "squad_cache": {"1": {"model_count_at_start": shooters}, "2": {"model_count_at_start": 1}},
        "units_cache": {"1": _uc(0, 0, player=0), "2": _uc(9, 9, player=1)},
        "units": [{"id": "1", "player": 0, "UNIT_KEYWORDS": _kw(*shooter_keywords)},
                  {"id": "2", "player": 1, "UNIT_KEYWORDS": _kw("INFANTRY")}],
        "unit_by_id": {"1": {"id": "1", "UNIT_RULES": [], "UNIT_KEYWORDS": _kw(*shooter_keywords)},
                       "2": {"id": "2", "UNIT_RULES": [], "UNIT_KEYWORDS": _kw("INFANTRY")}},
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        "pending_squad_shoot_intents": {"1": intents},
    }


def test_hazardous_inflige_une_mw_au_tireur_sur_1_ou_2(monkeypatch):
    """24.15 + 06.03 : le jet de hasard rate (2) -> 1 MW sur le TIREUR."""
    _seq(monkeypatch, [4, 5, 1, 2])  # touche, blessure, save ratée, PUIS hasard = 2 (échec)
    gs = _game_state(["HAZARDOUS"])

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["A0"]["HP_CUR"] == 1, "le tireur doit subir 1 blessure mortelle"


def test_hazardous_reussi_ne_blesse_pas(monkeypatch):
    """06.03 : un 3 réussit -> aucune blessure mortelle (discrimination du seuil 1-2)."""
    _seq(monkeypatch, [4, 5, 1, 3])
    gs = _game_state(["HAZARDOUS"])

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["A0"]["HP_CUR"] == 2


def test_sans_hazardous_aucun_jet(monkeypatch):
    """Contre-épreuve : sans la règle, aucun dé de hasard n'est consommé (séquence épuisée
    si un jet supplémentaire était tiré)."""
    _seq(monkeypatch, [4, 5, 1])
    gs = _game_state([])

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["A0"]["HP_CUR"] == 2


def test_un_jet_par_arme_hazardous_pas_par_figurine(monkeypatch):
    """24.15 : DEUX tireurs = deux armes HAZARDOUS sélectionnées -> DEUX jets.
    (Le Desperate Escape 09.07, lui, jette par figurine : ici c'est bien par arme.)"""
    _seq(monkeypatch, [4, 5, 1,   4, 5, 1,   1, 1])  # 2 tirs, puis 2 hasards ratés
    gs = _game_state(["HAZARDOUS"], shooters=2)
    for mid in ("A0", "A1"):  # 3 PV : les MW ne tuent pas, on mesure le TOTAL de dégâts
        gs["models_cache"][mid]["HP_CUR"] = 3
        gs["models_cache"][mid]["HP_MAX"] = 3

    build_manual_shoot_allocation(gs, "1")

    total = gs["models_cache"]["A0"]["HP_CUR"] + gs["models_cache"]["A1"]["HP_CUR"]
    assert total == 4, "2 armes HAZARDOUS = 2 jets ratés -> 2 MW (6 PV - 2)"


def test_trois_mw_si_toutes_les_figurines_sont_vehicules(monkeypatch):
    """06.03 : 3 MW au lieu d'1 si CHAQUE figurine de l'unité est MONSTER/VEHICLE."""
    _seq(monkeypatch, [4, 5, 1, 1])
    gs = _game_state(["HAZARDOUS"], shooter_keywords=("VEHICLE",))
    gs["models_cache"]["A0"]["HP_CUR"] = 9
    gs["models_cache"]["A0"]["HP_MAX"] = 9

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["A0"]["HP_CUR"] == 6, "véhicule : 3 MW"


def test_le_log_est_publie_avant_le_choix_des_pertes(monkeypatch):
    """Le combat log doit montrer le jet de hasard AVANT que le joueur ne désigne ses pertes.

    Vérifié sur le chemin MANUEL (défenseur humain) : au moment où le moteur rend la main
    (`waiting_for_player`), la ligne `[HAZARD]` est DÉJÀ dans `action_logs` — et elle n'y est
    qu'une seule fois (elle est complétée en place, jamais ré-émise)."""
    from engine.phase_handlers.shared_utils import roll_hazard_for_unit

    gs = _game_state(["HAZARDOUS"], shooters=2)
    gs["gym_training_mode"] = False
    gs["player_types"] = {"0": "human", "1": "human"}
    for mid in ("A0", "A1"):
        gs["models_cache"][mid].update({"HP_CUR": 3, "HP_MAX": 3})
    monkeypatch.setattr(random, "randint", lambda a, b: 1)  # jet raté

    roll_hazard_for_unit("1", gs, False, n_rolls=1, context_label="Hazardous")

    hazard_logs = [l for l in gs["action_logs"] if l.get("type") == "hazard"]
    assert len(hazard_logs) == 1, "la ligne hazard doit être publiée une seule fois"
    assert "[HAZARD]" in hazard_logs[0]["message"]
    assert "pending_hazard_allocation" in gs, "le joueur doit encore avoir à choisir ses pertes"


def test_une_seule_figurine_vehicule_ne_suffit_pas(monkeypatch):
    """06.03 dit « EACH model » : une escouade mixte infanterie/véhicule reste à 1 MW.
    (Sans le test par-figurine, l'union des keywords 19.03 aurait donné 3 MW à tort.)"""
    gs = _game_state(["HAZARDOUS"], shooters=2)
    gs["models_cache"]["A0"]["UNIT_KEYWORDS"] = _kw("VEHICLE")
    gs["models_cache"]["A1"]["UNIT_KEYWORDS"] = _kw("INFANTRY")
    gs["units"][0]["UNIT_KEYWORDS"] = _kw("VEHICLE", "INFANTRY")  # union 19.03
    monkeypatch.setattr(random, "randint", lambda a, b: 1)  # tous les jets échouent

    wounds = roll_hazard_for_unit("1", gs, True, n_rolls=1, context_label="Hazardous")

    assert wounds == 1, "escouade mixte : 1 MW, pas 3"
