"""UNIT_RULES x WEAPON_RULES sur le MEME jet, chemin VIF de tir (`_manual_roll_intent`).

PDF 01 Core, « Re-rolls » : « unless otherwise stated, you can never re-roll a dice more
than once ». Deux sources de relance peuvent viser le MEME de de blessure :
  - une ABILITE d unite  (`reroll_1_towound`, `reroll_towound_target_on_objective`, UNIT_RULES)
  - une REGLE D ARME     ([TWIN-LINKED] 24.38, WEAPON_RULES)
Le cumul est donc interdit, et c est cette interdiction que ce fichier verrouille : chaque
test declare une sequence de des EXACTE, et `_seq` echoue si le moteur en tire un de plus.

Chaque regle prise isolement est deja couverte sur le vif : les deux abilites par
test_reroll_towound_shoot.py, [TWIN-LINKED] au niveau du socle par
test_weapon_rules_attack_sequence.py, `closest_target_penetration` par
test_closest_target_penetration_shoot.py. Ce fichier remplace la version qui appelait le
code mort de tir (supprime en V11 §0.38) et qui ne faisait que les dupliquer.

Verrouille aussi la PORTEE de chaque regle : une abilite `to wound` ne doit toucher ni le
jet de touche ni celui de sauvegarde.
"""
import random

from engine.phase_handlers import shooting_handlers
from engine.game_state import initial_faction_ability_state
from tests.unit.engine._roll_helpers import roll_shoot_intent


# Une regle d unite qui ACCORDE un effet doit porter un `displayName` non vide : le moteur le
# lit pour nommer l abilite dans le combat log quand la relance a lieu (contrat de
# `get_source_unit_rule_display_name_for_effect`).
_INTERCESSION = {"ruleId": "reroll_1_towound", "displayName": "Targeted Intercession"}
_OBJECTIVE = {"ruleId": "reroll_towound_target_on_objective", "displayName": "Objective Mastery"}


def _seq(monkeypatch, rolls):
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee : le moteur a relance un de de trop"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    return seq


def _game_state(unit_rules, weapon_rules=(), *, target_col=9, target_row=9, armor_save=3):
    """1 tireur BS4 / S4 (blessure 4+ vs T4) + 1 cible ; objectif en (5,5)."""
    weapon = {"ATK": 4, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
              "WEAPON_RULES": list(weapon_rules), "code": "test_gun", "display_name": "Gun"}
    attacker = {"id": "A1", "squad_id": "1", "T": 4, "RNG_WEAPONS": [weapon]}
    # 14.02 : la presence sur objectif se juge PAR FIGURINE (models_cache + empreinte de socle),
    # pas sur l ancre d escouade. La figurine est posee sur l ancre : un seul jeu de coordonnees
    # ici, ce test ne discrimine pas les deux (cf. test_reroll_towound_shoot.py, qui le fait).
    target_model = {"id": "T1", "T": 4, "HP_CUR": 2, "HP_MAX": 2,
                    "ARMOR_SAVE": armor_save, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt",
                    "col": target_col, "row": target_row, "level": 0,
                    "BASE_SHAPE": "round", "BASE_SIZE": 1}
    game_state = {
        # Etat de depart des capacites de faction, par le constructeur canonique du moteur
        # (`w40k_core` l'appelle a l'init ET au reset). La resolution d'une attaque lit
        # `oath_target` / `waaagh_active` en `require_key` : un game_state litteral qui les
        # omet decrit une partie impossible.
        **initial_faction_ability_state(),
        "models_cache": {"A1": attacker, "T1": target_model},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "squad_cache": {"2": {"model_count_at_start": 1}},
        "units_cache": {"2": {"col": target_col, "row": target_row, "VALUE": 10.0, "player": 1,
                              "orientation": 0, "HP_CUR": 2, "HP_MAX": 2}},
        "unit_by_id": {"1": {"id": "1", "UNIT_RULES": list(unit_rules)},
                       "2": {"id": "2", "UNIT_RULES": []}},
        "objectives": [{"id": "o1", "hexes": [[5, 5]]}],
    }
    intent = {"model_id": "A1", "target_unit_id": "2", "weapon_index": 0, "n_attacks_resolved": 1}
    return game_state, intent


# ─────────────────────────────────────────────────────────────────────────────
# 01 Core « Re-rolls » : jamais deux relances sur le meme de
# ─────────────────────────────────────────────────────────────────────────────

def test_abilite_et_twin_linked_ne_relancent_pas_deux_fois(monkeypatch):
    """`reroll_1_towound` + [TWIN-LINKED] sur la meme attaque : le 1 est relance UNE fois.

    La relance rend 3 (toujours un echec vs 4+) : si les deux sources se cumulaient, un
    troisieme de serait tire — `_seq` le detecterait (sequence epuisee)."""
    seq = _seq(monkeypatch, [4, 1, 3])  # touche, blessure=1, UNE relance -> 3 (echec)
    gs, intent = _game_state([_INTERCESSION], ["TWIN_LINKED"])

    result = roll_shoot_intent(gs, intent)

    assert result["counts"]["wounds"] == 0
    assert result["shot_records"][0]["strengthRoll"] == 3, "le resultat de la relance est final"
    assert seq == [], "une seule relance, et aucune sauvegarde (la blessure a echoue)"


def test_objectif_et_twin_linked_ne_relancent_pas_deux_fois(monkeypatch):
    """Idem avec `reroll_towound_target_on_objective` (cible sur objectif) + [TWIN-LINKED]."""
    seq = _seq(monkeypatch, [4, 2, 3])
    gs, intent = _game_state([_OBJECTIVE], ["TWIN_LINKED"],
                             target_col=5, target_row=5)

    result = roll_shoot_intent(gs, intent)

    assert result["counts"]["wounds"] == 0
    assert result["shot_records"][0]["strengthRoll"] == 3
    assert seq == []


def test_twin_linked_seul_est_bien_cable_au_tir(monkeypatch):
    """Cablage de [TWIN-LINKED] 24.38 cote TIR : un echec non-1 est relance, et un succes suit."""
    seq = _seq(monkeypatch, [4, 3, 5, 2])  # touche, blessure=3 (echec), relance=5 (succes), save
    gs, intent = _game_state([], ["TWIN_LINKED"])

    result = roll_shoot_intent(gs, intent)

    assert result["counts"]["wounds"] == 1
    assert result["shot_records"][0]["strengthRoll"] == 5
    assert seq == []


def test_twin_linked_ne_relance_pas_une_blessure_reussie(monkeypatch):
    """24.38 relance les ECHECS : un 4 qui passe n est pas rejoue pour chercher le critique."""
    seq = _seq(monkeypatch, [4, 4, 2])  # touche, blessure=4 (succes), sauvegarde
    gs, intent = _game_state([], ["TWIN_LINKED"])

    result = roll_shoot_intent(gs, intent)

    assert result["shot_records"][0]["strengthRoll"] == 4
    assert seq == []


# ─────────────────────────────────────────────────────────────────────────────
# Portee des abilites `to wound` : ni la touche, ni la sauvegarde
# ─────────────────────────────────────────────────────────────────────────────

def test_une_abilite_to_wound_ne_relance_pas_la_touche(monkeypatch):
    """`reroll_1_towound` porte sur le jet de BLESSURE : un 1 a la TOUCHE reste un echec."""
    seq = _seq(monkeypatch, [1])  # 05.01 : 1 non modifie = touche ratee, et aucune relance
    gs, intent = _game_state([{"ruleId": "reroll_1_towound"}])

    result = roll_shoot_intent(gs, intent)

    assert result["counts"]["hits"] == 0
    assert seq == [], "aucun de de relance sur le jet de touche"


def test_une_abilite_to_wound_ne_relance_pas_la_sauvegarde(monkeypatch):
    """Le 1 de la sauvegarde (jet de la CIBLE) n est pas relance par une abilite du tireur."""
    seq = _seq(monkeypatch, [4, 5, 1])  # touche, blessure, sauvegarde=1
    gs, intent = _game_state([{"ruleId": "reroll_1_towound"}])

    result = roll_shoot_intent(gs, intent)

    assert result["shot_records"][0]["saveRoll"] == 1
    assert seq == [], "aucun de de relance sur le jet de sauvegarde"


def test_une_abilite_hors_objectif_ne_relance_rien(monkeypatch):
    """Contre-epreuve : `reroll_towound_target_on_objective` sans [TWIN-LINKED] et cible hors
    objectif -> l echec reste un echec, aucun de supplementaire."""
    seq = _seq(monkeypatch, [4, 2])
    gs, intent = _game_state([{"ruleId": "reroll_towound_target_on_objective"}],
                             target_col=9, target_row=9)

    result = roll_shoot_intent(gs, intent)

    assert result["counts"]["wounds"] == 0
    assert seq == []
