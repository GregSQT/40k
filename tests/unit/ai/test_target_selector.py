import pytest

import ai.target_selector as tsmod
from ai.target_selector import TargetSelector


def test_select_best_target_returns_empty_when_no_targets() -> None:
    selector = TargetSelector(tactical_weights={})
    assert selector.select_best_target({"id": 1}, [], {"units": []}) == ""


def test_select_best_target_skips_missing_units_and_uses_best_score(monkeypatch: pytest.MonkeyPatch) -> None:
    selector = TargetSelector(tactical_weights={})
    game_state = {"units": [{"id": "A"}, {"id": "B"}]}

    def fake_score(shooter, target, game_state):
        _ = shooter, game_state
        return {"A": 1.0, "B": 5.0}[target["id"]]

    monkeypatch.setattr(selector, "_calculate_tactical_score", fake_score)
    best = selector.select_best_target({"id": "S"}, ["X", "A", "B"], game_state)
    assert best == "B"


def test_get_unit_by_id_helper() -> None:
    game_state = {"units": [{"id": "U1"}, {"id": "U2"}]}
    assert TargetSelector._get_unit_by_id(game_state, "U2") == {"id": "U2"}
    assert TargetSelector._get_unit_by_id(game_state, "none") is None


def test_estimate_kill_probability_missing_required_fields_raises() -> None:
    selector = TargetSelector(tactical_weights={})
    with pytest.raises(KeyError, match=r"RNG_ATK"):
        selector._estimate_kill_probability({}, {"id": "T", "T": 4}, {})


def test_estimate_kill_probability_returns_one_for_dead_or_absent_target(monkeypatch: pytest.MonkeyPatch) -> None:
    selector = TargetSelector(tactical_weights={})
    monkeypatch.setattr(tsmod, "get_hp_from_cache", lambda unit_id, game_state: None)
    shooter = {"RNG_ATK": 3, "RNG_STR": 4, "RNG_NB": 2, "RNG_DMG": 1}
    target = {"id": "T1", "T": 4}
    assert selector._estimate_kill_probability(shooter, target, {}) == 1.0


def test_estimate_kill_probability_computes_fraction(monkeypatch: pytest.MonkeyPatch) -> None:
    selector = TargetSelector(tactical_weights={})
    monkeypatch.setattr(tsmod, "get_hp_from_cache", lambda unit_id, game_state: 10)
    monkeypatch.setattr(tsmod, "expected_dice_value", lambda expr, ctx: float(expr))
    shooter = {"RNG_ATK": 4, "RNG_STR": 5, "RNG_NB": 2, "RNG_DMG": 2}
    target = {"id": "T1", "T": 4}
    # p_hit=0.5, p_wound=4/6, expected_damage=2*0.5*(4/6)*2 = 1.333...
    prob = selector._estimate_kill_probability(shooter, target, {})
    assert 0.13 < prob < 0.14


def test_calculate_army_threat_returns_zero_without_friendlies(monkeypatch: pytest.MonkeyPatch) -> None:
    selector = TargetSelector(tactical_weights={})
    monkeypatch.setattr("engine.utils.weapon_helpers.get_max_ranged_range", lambda target: 24)
    monkeypatch.setattr(tsmod, "is_unit_alive", lambda uid, gs: False)
    monkeypatch.setattr(tsmod, "expected_dice_value", lambda expr, ctx: 1.0)
    game_state = {"current_player": 1, "units": [{"id": "F1", "player": 1}]}
    target = {"id": "T", "RNG_WEAPONS": [], "CC_WEAPONS": []}
    assert selector._calculate_army_threat(target, game_state) == 0.0


def test_calculate_army_threat_requires_friendly_value(monkeypatch: pytest.MonkeyPatch) -> None:
    selector = TargetSelector(tactical_weights={})
    monkeypatch.setattr("engine.utils.weapon_helpers.get_max_ranged_range", lambda target: 24)
    monkeypatch.setattr(tsmod, "is_unit_alive", lambda uid, gs: True)
    monkeypatch.setattr(tsmod, "expected_dice_value", lambda expr, ctx: 2.0)
    monkeypatch.setattr(tsmod, "require_unit_position", lambda unit, gs: (1, 1))
    monkeypatch.setattr(tsmod, "calculate_hex_distance", lambda a, b, c, d: 1)
    game_state = {"current_player": 1, "units": [{"id": "F1", "player": 1}]}
    target = {"id": "T", "RNG_WEAPONS": [{"DMG": "1"}], "CC_WEAPONS": []}
    with pytest.raises(KeyError, match=r"VALUE"):
        selector._calculate_army_threat(target, game_state)


def test_calculate_tactical_score_combines_components(monkeypatch: pytest.MonkeyPatch) -> None:
    selector = TargetSelector(
        tactical_weights={"kill_probability": 2.0, "threat_level": 1.5, "hp_ratio": 1.0, "army_threat": 1.2}
    )
    monkeypatch.setattr(selector, "_estimate_kill_probability", lambda shooter, target, gs: 0.5)
    monkeypatch.setattr(selector, "_calculate_army_threat", lambda target, gs: 0.25)
    monkeypatch.setattr(tsmod, "expected_dice_value", lambda expr, ctx: {"D3": 2.0, "D6": 3.5}[expr])
    monkeypatch.setattr(tsmod, "require_hp_from_cache", lambda uid, gs: 5)
    shooter = {"id": "S"}
    target = {"id": "T", "HP_MAX": 10, "RNG_WEAPONS": [{"DMG": "D3"}], "CC_WEAPONS": [{"DMG": "D6"}]}
    score = selector._calculate_tactical_score(shooter, target, {})
    # kill=1.0 + threat=(3.5/5)*1.5=1.05 + hp=(1-0.5)=0.5 + army=0.3 => 2.85
    assert abs(score - 2.85) < 1e-9
