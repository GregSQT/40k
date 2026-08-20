"""[BLAST] 24.05 (tir) et [CLEAVE X] 24.06 (melee) — des additionnels par 5 figurines cibles.

BLAST : « add one additional attack dice for every five models that were in the target unit in
the Select Targets step (rounding down) » ; [BLAST X] en ajoute X par tranche.

CLEAVE : identique, EN MELEE, avec une clause supplementaire — « if you only selected one
target for all of that weapon's attacks ».

⚠ Regression corrigee par cette tranche : `_has_blast_keyword` testait `weapon["KEYWORDS"]`,
champ absent de TOUTES les armes des armories (les regles vivent dans `WEAPON_RULES`) — BLAST
n etait donc jamais applique. Le 1er test echoue sous l ancien code.
"""
import random

import pytest
from shared.data_validation import ConfigurationError

from engine.phase_handlers import shooting_handlers
from engine.game_state import initial_faction_ability_state
from tests.unit.engine._roll_helpers import roll_fight_intent, roll_shoot_intent


def _neutralise(monkeypatch):
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    monkeypatch.setattr(shooting_handlers, "_ranged_distance_metric", lambda *args, **kwargs: "euclidean")


def _uc(col, row, *, player=1):
    return {"BASE_SHAPE": "round", "BASE_SIZE": 1, "col": col, "row": row,
            "occupied_hexes": {(col, row)}, "VALUE": 10.0, "player": player}


# ------------------------------------------------------------------------------ BLAST (tir)

def _shoot_state(weapon_rules, *, target_size):
    weapon = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
              "WEAPON_RULES": list(weapon_rules), "display_name": "Launcher"}
    attacker = {"id": "A1", "squad_id": "1", "T": 4, "player": 0, "RNG_WEAPONS": [weapon]}
    gs = {
        # Etat de depart des capacites de faction, par le constructeur canonique du moteur
        # (`w40k_core` l'appelle a l'init ET au reset). La resolution d'une attaque lit
        # `oath_target` / `waaagh_active` en `require_key` : un game_state litteral qui les
        # omet decrit une partie impossible.
        **initial_faction_ability_state(),
        "models_cache": {"A1": attacker, "T1": {"id": "T1", "T": 4, "HP_CUR": 2, "HP_MAX": 2,
                                                "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "role": None,
                                                "unitType": "Grunt", "player": 1}},
        "squad_models": {"2": ["T1"]},
        "squad_cache": {"2": {"model_count_at_start": target_size}},
        "units_cache": {"1": _uc(0, 0, player=0), "2": _uc(0, 5)},
        "unit_by_id": {"1": {"id": "1", "UNIT_RULES": []}, "2": {"id": "2", "UNIT_RULES": []}},
        "objectives": [], "units_moved": set(), "units_advanced": set(),
    }
    intent = {"model_id": "A1", "target_unit_id": "2", "weapon_index": 0,
              "n_attacks_resolved": 1, "target_squad_size_at_declaration": target_size}
    return gs, intent


def test_blast_ajoute_un_de_par_cinq_figurines(monkeypatch):
    """24.05 : cible de 11 figurines -> +2 des (11 // 5), soit 3 attaques."""
    _neutralise(monkeypatch)
    gs, intent = _shoot_state(["BLAST"], target_size=11)
    assert roll_shoot_intent(gs, intent)["counts"]["attacks"] == 3


def test_blast_arrondi_inferieur(monkeypatch):
    """24.05 : cible de 4 figurines -> aucun de additionnel."""
    _neutralise(monkeypatch)
    gs, intent = _shoot_state(["BLAST"], target_size=4)
    assert roll_shoot_intent(gs, intent)["counts"]["attacks"] == 1


def test_blast_parametre_multiplie(monkeypatch):
    """[BLAST 2] : 2 des par tranche de 5 -> cible de 12 -> 1 + 2*2 = 5 attaques."""
    _neutralise(monkeypatch)
    gs, intent = _shoot_state(["BLAST:2"], target_size=12)
    assert roll_shoot_intent(gs, intent)["counts"]["attacks"] == 5


def test_sans_blast_pas_de_de_additionnel(monkeypatch):
    """Contre-epreuve : meme cible de 11 figurines, arme nue -> 1 attaque."""
    _neutralise(monkeypatch)
    gs, intent = _shoot_state([], target_size=11)
    assert roll_shoot_intent(gs, intent)["counts"]["attacks"] == 1


# --------------------------------------------------------------------------- CLEAVE (melee)

def _fight_state(weapon_rules, *, target_size, extra_intents=()):
    weapon = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
              "WEAPON_RULES": list(weapon_rules), "display_name": "Choppa"}
    attacker = {"id": "A1", "squad_id": "1", "player": 0, "T": 4, "CC_WEAPONS": [weapon]}
    target_model = {"id": "T1", "squad_id": "2", "player": 1, "T": 4, "HP_CUR": 2, "HP_MAX": 2,
                    "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt"}
    intent = {"model_id": "A1", "target_unit_id": "2", "weapon_index": 0,
              "n_attacks_resolved": 1, "target_squad_size_at_declaration": target_size}
    gs = {
        **initial_faction_ability_state(),
        "models_cache": {"A1": attacker, "T1": target_model},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": target_size}},
        "units_cache": {"1": {"VALUE": 10.0, "player": 0}, "2": {"VALUE": 10.0, "player": 1}},
        "unit_by_id": {"1": {"id": "1", "UNIT_RULES": [], "UNIT_KEYWORDS": []},
                       "2": {"id": "2", "UNIT_RULES": [], "UNIT_KEYWORDS": []}},
        "objectives": [],
        "pending_squad_fight_intents": {"1": [intent, *extra_intents]},
    }
    return gs, intent


def test_cleave_ajoute_x_des_par_cinq_figurines(monkeypatch):
    """24.06 : [CLEAVE 1] contre 16 figurines -> +3 des (16 // 5), soit 4 attaques."""
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    gs, intent = _fight_state(["CLEAVE:1"], target_size=16)
    assert roll_fight_intent(gs, intent)["counts"]["attacks"] == 4


def test_cleave_inactif_si_plusieurs_cibles(monkeypatch):
    """24.06 : la meme arme repartie sur DEUX unites ne beneficie pas de CLEAVE."""
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    autre_cible = {"model_id": "A1", "target_unit_id": "3", "weapon_index": 0,
                   "n_attacks_resolved": 1, "target_squad_size_at_declaration": 16}
    gs, intent = _fight_state(["CLEAVE:1"], target_size=16, extra_intents=(autre_cible,))
    assert roll_fight_intent(gs, intent)["counts"]["attacks"] == 1


def test_sans_cleave_pas_de_de_additionnel(monkeypatch):
    """Contre-epreuve : arme nue contre 16 figurines -> 1 attaque."""
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    gs, intent = _fight_state([], target_size=16)
    assert roll_fight_intent(gs, intent)["counts"]["attacks"] == 1


def test_cleave_exige_la_taille_a_la_declaration(monkeypatch):
    """Aucun repli masquant : une arme CLEAVE sans taille capturee est une erreur explicite."""
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    gs, intent = _fight_state(["CLEAVE:1"], target_size=16)
    del intent["target_squad_size_at_declaration"]
    with pytest.raises(ConfigurationError):
        roll_fight_intent(gs, intent)
