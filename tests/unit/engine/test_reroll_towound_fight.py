"""JUMEAU MÊLÉE de `test_reroll_towound_shoot` : le NOM de l'ability qui a ouvert la relance.

Le tir consommait `woundRerollCause` et posait `woundAbility` sur le record ; la mêlée, elle,
ouvrait bien les mêmes relances (`reroll_1_towound`, `reroll_towound_target_on_objective`) mais
laissait la cause sur le record sans jamais la nommer. Conséquence : une relance de blessure en
mêlée n'apparaissait dans AUCUN log (ni `step.log`, ni le combat log), alors que la même relance
au tir y était nommée. Ces tests verrouillent la parité, `resolve_wound_reroll_ability` étant
désormais l'unique traducteur des deux chemins.
"""
import random

from engine.game_state import initial_faction_ability_state
from tests.unit.engine._roll_helpers import roll_fight_intent

# Une règle d'unité qui ACCORDE un effet doit porter un `displayName` non vide : c'est lui que
# le moteur affiche (contrat de `get_source_unit_rule_display_name_for_effect`).
_TARGETED_INTERCESSION = {"ruleId": "reroll_1_towound", "displayName": "Targeted Intercession"}
_ON_OBJECTIVE = {
    "ruleId": "reroll_towound_target_on_objective",
    "displayName": "Targeted Intercession",
}


def _seq(monkeypatch, rolls):
    """Dés SCRIPTÉS : épuisement = erreur explicite, dé en trop = séquence non vide en fin de test.

    C'est ce couple qui fait de la relance un fait OBSERVÉ : elle consomme un dé de plus.
    """
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee : le moteur a tire plus de des que prevu"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    return seq


def _fight_state(unit_rules, *, target_col=9, target_row=9):
    """Un attaquant ('1') au contact d'une cible ('2') ; objectif en (5,5)."""
    weapon = {"ATK": 1, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
              "WEAPON_RULES": [], "display_name": "Choppa"}
    attacker = {"id": "A1", "squad_id": "1", "player": 1, "T": 4, "CC_WEAPONS": [weapon]}
    target_model = {
        "id": "T1", "squad_id": "2", "player": 2, "T": 4, "HP_CUR": 2, "HP_MAX": 2,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt",
        "col": target_col, "row": target_row, "level": 0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1,
    }
    game_state = {
        # La résolution d'une attaque lit `oath_target` / `waaagh_active` en `require_key` : un
        # game_state littéral qui les omet décrit une partie impossible.
        **initial_faction_ability_state(),
        "models_cache": {"A1": attacker, "T1": target_model},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": 1}},
        "units_cache": {
            "1": {"col": 0, "row": 0, "VALUE": 10.0, "player": 1, "orientation": 0},
            "2": {"col": target_col, "row": target_row, "VALUE": 10.0, "player": 2,
                  "orientation": 0},
        },
        "unit_by_id": {
            "1": {"id": "1", "player": 1, "UNIT_RULES": unit_rules},
            "2": {"id": "2", "player": 2, "UNIT_RULES": []},
        },
        "objectives": [{"id": "o1", "hexes": [[5, 5]]}],
    }
    intent = {"model_id": "A1", "target_unit_id": "2", "weapon_index": 0, "n_attacks_resolved": 1}
    return game_state, intent


def test_la_relance_de_blessure_en_melee_est_nommee_sur_le_record(monkeypatch):
    """VERROU JUMEAU : `wound_1` -> `woundAbility`, comme au tir. Sans ça, la relance a bien
    lieu (le dé supplémentaire le prouve) mais aucun log ne peut dire qu'elle a joué."""
    seq = _seq(monkeypatch, [4, 1, 6, 2])  # touche, blessure=1 (echec), relance=6, sauvegarde
    gs, intent = _fight_state([_TARGETED_INTERCESSION])

    result = roll_fight_intent(gs, intent)

    rec = result["shot_records"][0]
    assert rec["strengthRoll"] == 6, "la relance a bien eu lieu"
    assert seq == [], "un de de plus consomme : c'est la relance, pas une deduction"
    assert "woundRerollCause" not in rec, "la cause est CONSOMMEE et remplacee par le nom"
    assert rec["woundAbility"] == "TARGETED INTERCESSION"


def test_la_relance_sur_objectif_en_melee_est_nommee_aussi(monkeypatch):
    """La SECONDE capacité d'unité (`wound_any_fail`) passe par le même traducteur."""
    seq = _seq(monkeypatch, [4, 3, 5, 2])  # touche, blessure=3 (echec), relance=5, sauvegarde
    gs, intent = _fight_state([_ON_OBJECTIVE], target_col=5, target_row=5)

    result = roll_fight_intent(gs, intent)

    rec = result["shot_records"][0]
    assert rec["strengthRoll"] == 5
    assert seq == []
    assert rec["woundAbility"] == "TARGETED INTERCESSION"


def test_sans_relance_aucun_nom_n_est_pose(monkeypatch):
    """Discrimination : sans capacité, le 1 reste un échec et le record ne porte aucun nom."""
    seq = _seq(monkeypatch, [4, 1])  # touche, blessure=1 -> ECHEC, aucun de de relance
    gs, intent = _fight_state([])

    result = roll_fight_intent(gs, intent)

    rec = result["shot_records"][0]
    assert rec["strengthResult"] == "FAILED"
    assert seq == []
    assert "woundAbility" not in rec


def test_verrou_les_causes_inconnues_levent_au_lieu_de_disparaitre():
    """Le `raise` final de `resolve_wound_reroll_ability` est le mecanisme qui rend BRUYANT
    l'ajout d'une cause de relance dans `roll_attack_pool`.

    Sans lui, une nouvelle cause rendrait `None` et la relance disparaitrait des DEUX logs en
    silence — exactement la panne que ce fichier verrouille. La branche n'etait exercee nulle
    part : la supprimer ne rougissait rien.
    """
    import pytest

    from engine.phase_handlers.shared_utils import resolve_wound_reroll_ability

    unit = {"UNIT_RULES": [_TARGETED_INTERCESSION]}

    with pytest.raises(ValueError, match="cause de relance de blessure inconnue"):
        resolve_wound_reroll_ability(
            unit, "wound_on_a_tuesday",
            reroll_1_towound=True, reroll_towound_on_objective=True,
        )

    # `twin_linked` est une regle d'ARME : elle est nommee ailleurs, pas ici. C'est la SEULE
    # cause connue qui rend None, et la distinguer d'une cause inconnue est tout l'objet du raise.
    assert resolve_wound_reroll_ability(
        unit, "twin_linked", reroll_1_towound=True, reroll_towound_on_objective=True,
    ) is None


def test_verrou_la_melee_annonce_oath_a_la_ligne_de_synthese(monkeypatch):
    """JUMEAU du tir : la melee doit produire les deux drapeaux de la ligne de synthese.

    `_emit_squad_shoot_log` est PARTAGE par le tir et la melee et les lit en `require_key`. Le
    tir est verrouille (`test_faction_abilities`), la melee ne l'etait pas : si son roller
    cessait de les poser, la ligne de synthese de melee perdait `RR [OATH OF MOMENT]` — ou
    levait un KeyError — sans qu'aucun test ne le voie.
    """
    from engine.game_state import set_oath_target
    from tests.unit.engine.test_faction_abilities import ASTARTES, ORKS, _fight_state

    _seq(monkeypatch, [4, 4, 6])
    gs, intent = _fight_state(attacker_faction=ASTARTES, defender_faction=ORKS)
    sans_oath = roll_fight_intent(gs, intent)
    assert sans_oath["oath_hit_reroll"] is False
    assert sans_oath["oath_wound_bonus"] is False

    _seq(monkeypatch, [4, 4, 6])
    gs, intent = _fight_state(attacker_faction=ASTARTES, defender_faction=ORKS)
    set_oath_target(gs, 1, "2")
    avec_oath = roll_fight_intent(gs, intent)
    assert avec_oath["oath_hit_reroll"] is True
    assert avec_oath["oath_wound_bonus"] is True
