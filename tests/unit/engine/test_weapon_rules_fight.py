"""Regles d armes en MELEE — cablage de `_manual_roll_fight_intent` sur le socle commun.

Avant cette tranche, le roller de melee ne lisait AUCUNE regle d arme (zero occurrence de
WEAPON_RULES dans fight_handlers) : `relic_greataxe` et `thunder_hammer_terminator`
declarent pourtant [DEVASTATING WOUNDS], `eviscerator` [SUSTAINED HITS 1], `urty_syringe`
[ANTI-INFANTRY 1+]. Ces tests verrouillent le CABLAGE (appelant -> socle), pas le socle
lui-meme (couvert par test_weapon_rules_attack_sequence.py).
"""
import random

import pytest

from engine.phase_handlers.fight_handlers import _manual_roll_fight_intent


def _seq(monkeypatch, rolls):
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)


def _game_state(weapon_rules, *, target_keywords=()):
    weapon = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
              "WEAPON_RULES": list(weapon_rules), "display_name": "Axe"}
    attacker = {"id": "A1", "squad_id": "1", "player": 0, "T": 4, "CC_WEAPONS": [weapon]}
    target_model = {"id": "T1", "squad_id": "2", "player": 1, "T": 4, "HP_CUR": 2, "HP_MAX": 2,
                    "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt"}
    gs = {
        "models_cache": {"A1": attacker, "T1": target_model},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": 1}},
        "units_cache": {"1": {"VALUE": 10.0, "player": 0}, "2": {"VALUE": 10.0, "player": 1}},
        "unit_by_id": {
            "1": {"id": "1", "UNIT_RULES": [], "UNIT_KEYWORDS": []},
            "2": {"id": "2", "UNIT_RULES": [],
                  "UNIT_KEYWORDS": [{"keywordId": k} for k in target_keywords]},
        },
        "objectives": [],
    }
    intent = {"model_id": "A1", "target_unit_id": "2", "weapon_index": 0, "n_attacks_resolved": 1}
    return gs, intent


def test_devastating_wounds_actif_en_melee(monkeypatch):
    """24.10 : la blessure critique d une arme de melee produit bien une blessure mortelle."""
    _seq(monkeypatch, [4, 6, 4])  # touche 4, blessure 6 (critique), sauvegarde 4
    gs, intent = _game_state(["DEVASTATING_WOUNDS"])

    result = _manual_roll_fight_intent(gs, intent, {})

    assert result["pending_wounds"][0]["devastating"] is True


def test_sans_devastating_pas_de_mortelle_en_melee(monkeypatch):
    """Contre-epreuve : meme critique sans la regle -> blessure normale."""
    _seq(monkeypatch, [4, 6, 4])
    gs, intent = _game_state([])

    result = _manual_roll_fight_intent(gs, intent, {})

    assert result["pending_wounds"][0]["devastating"] is False


def test_sustained_hits_actif_en_melee(monkeypatch):
    """24.36 : touche critique + [SUSTAINED HITS 1] -> 2 touches pour 1 attaque."""
    _seq(monkeypatch, [6, 5, 4, 5, 4])
    gs, intent = _game_state(["SUSTAINED_HITS:1"])

    result = _manual_roll_fight_intent(gs, intent, {})

    assert result["counts"] == {"attacks": 1, "hits": 2, "wounds": 2}


def test_anti_keyword_actif_en_melee(monkeypatch):
    """24.03 : [ANTI-INFANTRY 4+] contre une cible INFANTRY -> un 4 est une blessure critique."""
    _seq(monkeypatch, [4, 4, 4])
    gs, intent = _game_state(["ANTI_INFANTRY:4", "DEVASTATING_WOUNDS"],
                             target_keywords=("INFANTRY",))

    result = _manual_roll_fight_intent(gs, intent, {})

    assert result["pending_wounds"][0]["devastating"] is True


def test_anti_keyword_absent_de_la_cible_en_melee(monkeypatch):
    """Discrimination : sans le keyword INFANTRY, le 4 reste une blessure normale."""
    _seq(monkeypatch, [4, 4, 4])
    gs, intent = _game_state(["ANTI_INFANTRY:4", "DEVASTATING_WOUNDS"],
                             target_keywords=("VEHICLE",))

    result = _manual_roll_fight_intent(gs, intent, {})

    assert result["pending_wounds"][0]["devastating"] is False


def test_un_non_modifie_rate_toujours_en_melee(monkeypatch):
    """05.01 : le 1 non modifie rate meme quand le seuil de touche est atteignable a 1."""
    _seq(monkeypatch, [1])
    gs, intent = _game_state([])
    gs["models_cache"]["A1"]["CC_WEAPONS"][0]["ATK"] = 1

    result = _manual_roll_fight_intent(gs, intent, {})

    assert result["counts"]["hits"] == 0
