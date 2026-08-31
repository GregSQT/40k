"""Cap sur le total des modificateurs de jet de touche et de blessure (bonus_malus_cap).

Sémantique : 0 = pas de cap (comportement 10e). N > 0 : le total net des modificateurs
est clampé à [-N, N] avant ajustement du seuil de touche ; le total des bonus de blessure
(Oath + Litany) est clampé à N avant ajustement du seuil de blessure.

CE QUE CES TESTS VERROUILLENT :

- cap=1, S4 vs T5 (seuil 4+) + Oath + Litany → seuil 3+ (pas 2+)
- cap=0, même cas → seuil 2+ (comportement actuel, inchangé)
- cap=1, touche : bonus=1 + malus=1 → net=0 → seuil inchangé (compensation)
- cap=1, touche : bonus=1, malus=0 → net=1 clampé à 1 → identique à sans cap (cap non actif)
"""
import random
from typing import Any, Dict

import pytest

from engine.game_state import initial_faction_ability_state
from tests.unit.engine._roll_helpers import roll_fight_intent, roll_shoot_intent
from tests.unit.engine._state_builders import units_cache_entry as _uc

_MIGHT_IS_RIGHT = {"ruleId": "hit_roll_bonus_fight", "displayName": "Might Is Right"}
_LITANY_OF_HATE = {"ruleId": "wound_roll_bonus_fight", "displayName": "Litany of Hate"}


def _fixed(monkeypatch, value: int) -> None:
    monkeypatch.setattr(random, "randint", lambda a, b: value)


def _seq(monkeypatch, rolls):
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    return seq


def _fight_state(
    unit_rules,
    *,
    ws: int = 4,
    strength: int = 4,
    toughness: int = 4,
    cap: int = 0,
    with_oath: bool = False,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    weapon = {
        "ATK": ws, "STR": strength, "AP": 0, "DMG": 1, "NB": 1,
        "WEAPON_RULES": [], "code": "test_choppa", "display_name": "Choppa",
    }
    attacker = {"id": "A1", "squad_id": "1", "player": 1, "T": 4, "CC_WEAPONS": [weapon]}
    target_model = {
        "id": "T1", "squad_id": "2", "player": 2, "T": toughness, "HP_CUR": 2, "HP_MAX": 2,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt",
        "col": 9, "row": 9, "level": 0, "BASE_SHAPE": "round", "BASE_SIZE": 1,
    }
    config: Dict[str, Any] = {
        "game_rules": {"bonus_malus_cap": cap},
        "uses_codex_detachment": {"1": True, "2": True},
        "army_faction": {"1": "ADEPTUS ASTARTES", "2": "ORKS"},
    }
    gs: Dict[str, Any] = {
        **initial_faction_ability_state(),
        "models_cache": {"A1": attacker, "T1": target_model},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": 1}},
        "units_cache": {
            "1": {"col": 0, "row": 0, "VALUE": 10.0, "player": 1, "orientation": 0, "HP_CUR": 1, "HP_MAX": 1},
            "2": {"col": 9, "row": 9, "VALUE": 10.0, "player": 2, "orientation": 0, "HP_CUR": 2, "HP_MAX": 2},
        },
        "unit_by_id": {
            "1": {"id": "1", "player": 1, "UNIT_RULES": unit_rules,
                  "FACTION_KEYWORDS": [{"keywordId": "ADEPTUS ASTARTES"}]},
            "2": {"id": "2", "player": 2, "UNIT_RULES": []},
        },
        "units": [],
        "objectives": [{"id": "o1", "hexes": [[5, 5]]}],
        "suppressed_squads": {},
        "config": config,
    }
    if with_oath:
        gs["oath_target"] = {1: "2", 2: None}
        gs["units"] = [gs["unit_by_id"]["1"], gs["unit_by_id"]["2"]]
    intent = {"model_id": "A1", "target_unit_id": "2", "weapon_index": 0, "n_attacks_resolved": 1}
    return gs, intent


# ---------------------------------------------------------------------------
# Seuil de blessure — Oath + Litany avec cap
# ---------------------------------------------------------------------------


def test_cap1_oath_litany_s4_t5_limite_a_un_cran(monkeypatch):
    """Cap=1 : S4 vs T5 (seuil 5+) + Oath + Litany = total +2 clampé à +1 → seuil 4+.

    Sans cap, le cumul descend à 3+ ; avec cap=1, seul un cran est accordé.
    """
    _seq(monkeypatch, [4, 4, 2])  # touche, blessure=4, sauvegarde
    gs, intent = _fight_state(
        [_LITANY_OF_HATE], strength=4, toughness=5, cap=1, with_oath=True
    )

    rec = roll_fight_intent(gs, intent)["shot_records"][0]

    assert rec["woundTarget"] == 4, (
        "S4 vs T5 = 5+ ; Oath+Litany = +2 clampé à +1 par cap=1 → 4+, pas 3+"
    )
    assert rec["strengthResult"] in ("WOUND", "SUCCESS"), "un 4 blesse sur 4+"


def test_cap0_oath_litany_s4_t5_cumul_complet(monkeypatch):
    """Cap=0 (pas de cap) : S4 vs T5 + Oath + Litany = total +2 → seuil 3+ (comportement 10e)."""
    _seq(monkeypatch, [4, 3, 2])  # touche, blessure=3, sauvegarde
    gs, intent = _fight_state(
        [_LITANY_OF_HATE], strength=4, toughness=5, cap=0, with_oath=True
    )

    rec = roll_fight_intent(gs, intent)["shot_records"][0]

    assert rec["woundTarget"] == 3, "sans cap, Oath+Litany cumulés descendent de deux crans : 5+→3+"


def test_cap1_litany_seule_s4_t5_inchange(monkeypatch):
    """Cap=1 : Litany seule sur S4 vs T5 = +1 ≤ cap → seuil 4+ (5+-1) comme sans cap."""
    _seq(monkeypatch, [4, 4, 2])
    gs, intent = _fight_state([_LITANY_OF_HATE], strength=4, toughness=5, cap=1)

    rec = roll_fight_intent(gs, intent)["shot_records"][0]

    assert rec["woundTarget"] == 4, "Litany seule (+1) ne dépasse pas cap=1 → 4+ préservé"


# ---------------------------------------------------------------------------
# Seuil de touche — cap sur net bonus - malus
# ---------------------------------------------------------------------------


def test_cap1_bonus_et_malus_egaux_net_zero(monkeypatch):
    """Cap=1 : bonus=1 et malus=1 → net=0 clampé dans [-1,1] = 0 → seuil inchangé."""
    from engine.phase_handlers.shared_utils import apply_hit_roll_modifiers

    # WS 4, bonus=1, malus=1 : sans cap net=-1+1=0 → seuil 4 ; cap=1 idem
    assert apply_hit_roll_modifiers(4, 1, 1, cap=1) == 4


def test_cap1_bonus1_malus0_seuil_abaisse(monkeypatch):
    """Cap=1 : bonus=1, malus=0 → net=1 clampé à 1 → seuil abaissé de 1."""
    from engine.phase_handlers.shared_utils import apply_hit_roll_modifiers

    assert apply_hit_roll_modifiers(4, 1, 0, cap=1) == 3


def test_cap0_identique_a_sans_cap(monkeypatch):
    """cap=0 = pas de cap : comportement identique à l'appel sans paramètre cap."""
    from engine.phase_handlers.shared_utils import apply_hit_roll_modifiers

    for bonus, malus, base in [(1, 0, 4), (0, 1, 4), (1, 1, 4), (2, 0, 5)]:
        assert apply_hit_roll_modifiers(base, bonus, malus, cap=0) == \
               apply_hit_roll_modifiers(base, bonus, malus)
