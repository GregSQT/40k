import pytest

import ai.reward_mapper as rmod
from ai.reward_mapper import RewardMapper


def _base_cfg() -> dict:
    return {
        "base_actions": {
            "ranged_attack": 1.0,
            "charge_success": 2.0,
            "melee_attack": 1.5,
            "advance": 0.2,
            "move_to_los": 0.3,
            "move_away": 0.1,
            "move_close": 0.25,
            "move_to_charge": 0.4,
        },
        "tactical_bonuses": {
            "advanced_closer": 0.1,
            "advanced_to_cover": 0.2,
            "gained_los_on_target": 0.2,
            "moved_to_cover": 0.15,
            "safe_from_charges": 0.1,
            "safe_from_ranged": 0.05,
        },
        "result_bonuses": {"kill_target": 3.0},
        "enemy_killed_no_overkill_r": 1.2,
        "enemy_killed_r": 0.5,
        "enemy_killed_no_overkill_m": 1.0,
        "enemy_killed_m": 0.4,
        "enemy_killed_lowests_hp_r": 1.5,
        "enemy_killed_lowests_hp_m": 1.1,
        "target_type_bonuses": {"vs_elite": 0.3, "vs_ranged": 0.2, "vs_melee": 0.1},
    }


def test_get_unit_threat_uses_max_of_ranged_and_melee(monkeypatch: pytest.MonkeyPatch) -> None:
    mapper = RewardMapper(_base_cfg())
    monkeypatch.setattr(rmod, "get_max_ranged_damage", lambda unit: 2.5)
    monkeypatch.setattr(rmod, "get_max_melee_damage", lambda unit: 4.0)
    assert mapper._get_unit_threat({"id": 1}) == 4.0


def test_get_target_hp_uses_cache_and_defaults_to_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    mapper = RewardMapper(_base_cfg())
    monkeypatch.setattr(rmod, "get_hp_from_cache", lambda uid, gs: 7)
    assert mapper._get_target_hp({"id": "T1"}, {}) == 7
    monkeypatch.setattr(rmod, "get_hp_from_cache", lambda uid, gs: None)
    assert mapper._get_target_hp({"id": "T1"}, {}) == 0


def test_parse_unit_type_accepts_phase_suffix_and_rejects_invalid() -> None:
    mapper = RewardMapper(_base_cfg())
    parsed = mapper._parse_unit_type("SpaceMarine_Infantry_Elite_RangedElite_phase2")
    assert parsed["faction"] == "SpaceMarine"
    assert parsed["attack_pref"] == "RangedElite"
    with pytest.raises(ValueError, match=r"Invalid unit type format"):
        mapper._parse_unit_type("bad_format")


def test_get_target_type_bonus_from_attack_preference() -> None:
    mapper = RewardMapper(_base_cfg())
    unit = {"unitType": "SpaceMarine_Infantry_Elite_RangedElite"}
    target = {"unitType": "Tyranid_Infantry_Elite_MeleeTroop"}
    # vs_elite + vs_ranged = 0.3 + 0.2
    assert abs(mapper._get_target_type_bonus(unit, target) - 0.5) < 1e-9


def test_get_unit_rewards_supports_direct_agent_section_and_exact_lookup() -> None:
    mapper_direct = RewardMapper(_base_cfg())
    assert mapper_direct._get_unit_rewards({"unitType": "Anything"})["base_actions"]["advance"] == 0.2

    cfg = {"Intercessor": _base_cfg()}
    mapper_lookup = RewardMapper(cfg)
    assert mapper_lookup._get_unit_rewards({"unitType": "Intercessor"})["base_actions"]["advance"] == 0.2
    with pytest.raises(ValueError, match=r"Unit type 'Unknown' not found"):
        mapper_lookup._get_unit_rewards({"unitType": "Unknown"})


def test_get_advance_reward_applies_bonuses_and_retreat_penalty() -> None:
    mapper = RewardMapper(_base_cfg())
    reward, action = mapper.get_advance_reward(
        {"unitType": "Intercessor"},
        (1, 1),
        (2, 2),
        {"moved_closer": True, "moved_to_cover": True, "moved_away": True},
    )
    # 0.2 + 0.1 + 0.2 - 0.05
    assert abs(reward - 0.45) < 1e-9
    assert action == "advance"


def test_get_movement_reward_ranged_and_melee_paths() -> None:
    mapper = RewardMapper(_base_cfg())
    ranged_reward, ranged_action = mapper.get_movement_reward(
        {"unitType": "Intercessor", "is_ranged": True},
        (1, 1),
        (2, 2),
        {"moved_to_optimal_range": True, "gained_los_on_priority_target": True},
    )
    assert abs(ranged_reward - 0.5) < 1e-9  # 0.3 + 0.2
    assert ranged_action == "move_to_los"

    melee_reward, melee_action = mapper.get_movement_reward(
        {"unitType": "Hormagaunt", "is_ranged": False},
        (1, 1),
        (2, 2),
        {"moved_to_charge_range": True},
    )
    assert melee_reward == 0.4
    assert melee_action == "move_to_charge"

    with pytest.raises(ValueError, match=r"No valid ranged unit movement context"):
        mapper.get_movement_reward({"unitType": "Intercessor", "is_ranged": True}, (1, 1), (2, 2), {})


def test_kill_bonus_reward_requires_kill_and_applies_no_overkill(monkeypatch: pytest.MonkeyPatch) -> None:
    mapper = RewardMapper(_base_cfg())
    monkeypatch.setattr(mapper, "_get_target_hp", lambda target, game_state: 5)
    monkeypatch.setattr(mapper, "_get_current_phase", lambda: "shoot")
    monkeypatch.setattr(mapper, "_was_lowest_hp_target", lambda target, game_state: False)
    reward = mapper.get_kill_bonus_reward(
        {"unitType": "Intercessor"},
        {"id": "T1"},
        damage_dealt=5,
        game_state={},
    )
    # base 3.0 + (no_overkill_r - killed_r) = +0.7
    assert abs(reward - 3.7) < 1e-9
    with pytest.raises(ValueError, match=r"Target was not killed"):
        mapper.get_kill_bonus_reward({"unitType": "Intercessor"}, {"id": "T1"}, damage_dealt=1, game_state={})


def test_threat_and_hp_comparison_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    mapper = RewardMapper(_base_cfg())
    targets = [{"id": "A"}, {"id": "B"}, {"id": "C"}]
    threat_map = {"A": 3.0, "B": 3.0, "C": 1.0}
    hp_map = {"A": 5, "B": 3, "C": 8}
    monkeypatch.setattr(mapper, "_get_unit_threat", lambda t: threat_map[t["id"]])
    monkeypatch.setattr(mapper, "_get_target_hp", lambda t, gs: hp_map[t["id"]])

    assert mapper._is_highest_threat_in_range(targets[0], targets) is True
    assert mapper._is_highest_threat_adjacent(targets[2], targets) is False
    assert mapper._is_lowest_hp_high_threat(targets[1], targets, {}) is True
    assert mapper._is_lowest_hp_among_threats(targets[1], targets, {}) is True
    assert mapper._is_highest_hp_among_threats(targets[0], targets, {}) is True
    assert mapper._is_lowest_hp_among_adjacent_threats(targets[1], targets, {}) is True


def test_not_implemented_accessors_raise() -> None:
    mapper = RewardMapper(_base_cfg())
    with pytest.raises(NotImplementedError):
        mapper._get_max_melee_damage_vs_target({"id": "T"})
    with pytest.raises(NotImplementedError):
        mapper._get_current_phase()


def test_can_unit_kill_target_in_one_phase_handles_dead_and_missing_weapon(monkeypatch: pytest.MonkeyPatch) -> None:
    mapper = RewardMapper(_base_cfg())
    # Dead/absent target hp -> immediately killable
    monkeypatch.setattr(mapper, "_get_target_hp", lambda target, gs: 0)
    assert mapper._can_unit_kill_target_in_one_phase({"id": "u"}, {"id": "t"}, True, {}) is True

    # Alive target but no selected weapon -> not killable
    monkeypatch.setattr(mapper, "_get_target_hp", lambda target, gs: 5)
    monkeypatch.setattr(rmod, "get_selected_ranged_weapon", lambda unit: None)
    assert mapper._can_unit_kill_target_in_one_phase({"id": "u"}, {"id": "t"}, True, {}) is False


def test_shoot_charge_and_combat_priority_rewards(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _base_cfg()
    cfg.update(
        {
            "shoot_priority_1": 0.9,
            "shoot_priority_2": 0.6,
            "shoot_priority_3": 0.4,
            "charge_priority_1": 0.8,
            "charge_priority_2": 0.5,
            "charge_priority_3": 0.3,
            "attack_priority_1": 0.7,
            "attack_priority_2": 0.2,
        }
    )
    mapper = RewardMapper(cfg)
    unit = {"unitType": "Intercessor", "is_melee": True}
    target = {"id": "T1", "unitType": "Tyranid_Infantry_Elite_MeleeTroop"}
    all_targets = [target]

    monkeypatch.setattr(mapper, "_get_max_melee_damage_vs_target", lambda t: 2)
    monkeypatch.setattr(mapper, "_get_target_hp", lambda t, gs: 4)
    monkeypatch.setattr(mapper, "_is_highest_threat_in_range", lambda t, ts: True)
    monkeypatch.setattr(mapper, "_is_lowest_hp_high_threat", lambda t, ts, gs: False)
    monkeypatch.setattr(mapper, "_can_unit_kill_target_in_one_phase", lambda *args, **kwargs: True)
    monkeypatch.setattr(mapper, "_get_unit_threat", lambda u: 3.0)
    monkeypatch.setattr(rmod, "get_selected_melee_weapon", lambda u: {"NB": 1, "DMG": 1})
    monkeypatch.setattr(rmod, "expected_dice_value", lambda expr, ctx: float(expr))
    monkeypatch.setattr(mapper, "_is_lowest_hp_among_threats", lambda t, ts, gs: True)
    monkeypatch.setattr(mapper, "_is_highest_hp_among_threats", lambda t, ts, gs: True)
    monkeypatch.setattr(mapper, "_is_highest_threat_adjacent", lambda t, ts: True)
    monkeypatch.setattr(mapper, "_is_lowest_hp_among_adjacent_threats", lambda t, ts, gs: True)

    # Shooting priority 2 path (killable + highest threat)
    shoot_reward = mapper.get_shooting_priority_reward(
        unit, target, all_targets, can_melee_charge_target=False, game_state={}
    )
    assert abs(shoot_reward - 1.6) < 1e-9  # ranged_attack 1.0 + shoot_priority_2 0.6

    # Charge melee priority 1 path
    charge_reward = mapper.get_charge_priority_reward(unit, target, all_targets, {})
    assert abs(charge_reward - 2.8) < 1e-9  # charge_success 2.0 + charge_priority_1 0.8

    # Combat priority 1 path
    combat_reward = mapper.get_combat_priority_reward(unit, target, all_targets, {})
    assert abs(combat_reward - 2.2) < 1e-9  # melee_attack 1.5 + attack_priority_1 0.7
