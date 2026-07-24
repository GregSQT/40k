"""Rerolls to-wound au TIR dans le chemin VIF (_manual_roll_intent).

Comble l'asymetrie tir/fight (V11 §9.2 P1) : `reroll_1_towound` et
`reroll_towound_target_on_objective` etaient appliques en melee
(_manual_roll_fight_intent) mais PAS au tir. Ces tests passent par `_manual_roll_intent`
(vrai `get_unit_by_id` + vrai `is_unit_on_objective`) : ils verrouillent le CABLAGE, pas un
helper isole. Le RNG est rendu deterministe en monkeypatchant shared_utils.random.randint.

Mecanique de reroll (miroir fight, conforme 01 Core « Re-rolls ») : un de ne se re-roll
qu'une fois ; le second resultat est accepte tel quel.
"""
import random

from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.shared_utils import _manual_roll_intent


def _seq_randint(monkeypatch, rolls):
    """Force random.randint a rendre `rolls` dans l'ordre (_manual_roll_intent fait
    `import random` local -> on patche le module random lui-meme)."""
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee : le code a tire plus de des que prevu"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    # Le tir non-IGNORES_COVER consulte la LoS : on neutralise le cover (hors sujet ici).
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    return seq


def _game_state(unit_rules, target_col=9, target_row=9):
    """1 tireur (arme sans regle speciale) + 1 cible ; objectif en (5,5).
    target_col/row = (5,5) -> cible sur objectif, sinon hors objectif."""
    weapon = {"BS": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "WEAPON_RULES": [], "display_name": "Gun"}
    attacker = {"id": "A1", "squad_id": "1", "T": 4, "RNG_WEAPONS": [weapon]}
    attacker_unit = {"id": "1", "UNIT_RULES": unit_rules}
    target_model = {
        "id": "T1", "T": 4, "HP_CUR": 2, "HP_MAX": 2,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt",
    }
    target_unit = {"id": "2", "UNIT_RULES": []}
    game_state = {
        "models_cache": {"A1": attacker, "T1": target_model},
        "squad_models": {"2": ["T1"]},
        "squad_cache": {"2": {"model_count_at_start": 1}},
        "units_cache": {"2": {"col": target_col, "row": target_row, "VALUE": 10.0, "player": 1}},
        "unit_by_id": {"1": attacker_unit, "2": target_unit},
        "objectives": [{"hexes": [{"col": 5, "row": 5}]}],
    }
    intent = {"model_id": "A1", "target_unit_id": "2", "weapon_index": 0, "n_attacks_resolved": 1}
    return game_state, intent


def test_reroll_1_towound_rerolls_a_failed_1(monkeypatch):
    """reroll_1_towound : wound=1 (echec) -> reroll=6 (succes). wth=4 (S4 vs T4)."""
    seq = _seq_randint(monkeypatch, [4, 1, 6, 2])  # hit, wound=1, reroll=6, save
    gs, intent = _game_state([{"ruleId": "reroll_1_towound"}])

    result = _manual_roll_intent(gs, intent, {})

    assert result["counts"]["wounds"] == 1
    assert result["shot_records"][0]["strengthResult"] == "SUCCESS"
    assert result["shot_records"][0]["strengthRoll"] == 6
    assert seq == [], "save tire apres succes"


def test_no_rule_does_not_reroll(monkeypatch):
    """Sans reroll : wound=1 reste un echec (pas de reroll)."""
    seq = _seq_randint(monkeypatch, [4, 1])  # hit, wound=1 -> FAILED, pas de 3e de
    gs, intent = _game_state([])

    result = _manual_roll_intent(gs, intent, {})

    assert result["counts"]["wounds"] == 0
    assert result["shot_records"][0]["strengthResult"] == "FAILED"
    assert seq == [], "aucun de de reroll ni de save tire"


def test_reroll_1_towound_ignores_non_1_failure(monkeypatch):
    """reroll_1_towound ne reroll QUE le 1 : un echec a 3 (non-1) n'est pas rejoue."""
    seq = _seq_randint(monkeypatch, [4, 3])  # hit, wound=3 (<4, mais != 1) -> FAILED, pas de reroll
    gs, intent = _game_state([{"ruleId": "reroll_1_towound"}])

    result = _manual_roll_intent(gs, intent, {})

    assert result["counts"]["wounds"] == 0
    assert seq == []


def test_reroll_towound_on_objective_rerolls_any_failure(monkeypatch):
    """reroll_towound_target_on_objective : cible sur objectif -> reroll de TOUT echec (ici 3)."""
    seq = _seq_randint(monkeypatch, [4, 3, 5, 2])  # hit, wound=3 (echec), reroll=5 (succes), save
    gs, intent = _game_state([{"ruleId": "reroll_towound_target_on_objective"}], target_col=5, target_row=5)

    result = _manual_roll_intent(gs, intent, {})

    assert result["counts"]["wounds"] == 1
    assert result["shot_records"][0]["strengthRoll"] == 5
    assert seq == []


def test_reroll_towound_on_objective_inactive_off_objective(monkeypatch):
    """Meme regle, cible HORS objectif -> pas de reroll (discrimination on/off objectif)."""
    seq = _seq_randint(monkeypatch, [4, 3])  # hit, wound=3 -> FAILED, pas de reroll
    gs, intent = _game_state([{"ruleId": "reroll_towound_target_on_objective"}], target_col=9, target_row=9)

    result = _manual_roll_intent(gs, intent, {})

    assert result["counts"]["wounds"] == 0
    assert seq == []
