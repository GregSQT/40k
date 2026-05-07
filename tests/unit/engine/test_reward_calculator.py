"""Tests unitaires — reward_calculator : wound_target, expected_damage, determine_winner."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.reward_calculator import RewardCalculator


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_calculator() -> RewardCalculator:
    """Instance minimale sans state_manager ni unit_registry."""
    return RewardCalculator(
        config={"quiet": True},
        rewards_config={},
        unit_registry=None,
        state_manager=None,
    )


def _cache_entry(player: int) -> Dict[str, Any]:
    return {"player": player, "col": 0, "row": 0, "HP_CUR": 1}


def _gs_with_cache(entries: Dict[str, Any]) -> Dict[str, Any]:
    return {"units_cache": entries}


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_wound_target
# ─────────────────────────────────────────────────────────────────────────────

class TestCalculateWoundTarget:
    def test_str_double_toughness_wounds_on_2(self):
        """wound_2plus : S≥2×T → wound 2+."""
        rc = _make_calculator()
        assert rc._calculate_wound_target(8, 4) == 2

    def test_str_exactly_double_toughness_wounds_on_2(self):
        """wound_2plus_eq : S==2×T exactement → wound 2+."""
        rc = _make_calculator()
        assert rc._calculate_wound_target(6, 3) == 2

    def test_str_greater_than_toughness_wounds_on_3(self):
        """wound_3plus : S>T mais S<2×T → wound 3+."""
        rc = _make_calculator()
        assert rc._calculate_wound_target(5, 4) == 3

    def test_str_equal_toughness_wounds_on_4(self):
        """wound_4plus : S==T → wound 4+."""
        rc = _make_calculator()
        assert rc._calculate_wound_target(4, 4) == 4

    def test_str_one_below_toughness_wounds_on_5(self):
        """wound_5plus : S<T et 2×S>T → wound 5+."""
        rc = _make_calculator()
        assert rc._calculate_wound_target(3, 4) == 5

    def test_str_half_toughness_wounds_on_6(self):
        """wound_6plus : 2×S==T → wound 6+."""
        rc = _make_calculator()
        assert rc._calculate_wound_target(2, 4) == 6

    def test_str_less_than_half_toughness_wounds_on_6(self):
        """wound_6plus_low : 2×S<T → wound 6+."""
        rc = _make_calculator()
        assert rc._calculate_wound_target(1, 4) == 6

    def test_symmetric_equal_strength_toughness(self):
        """wound_sym : S=T=6 → wound 4+."""
        rc = _make_calculator()
        assert rc._calculate_wound_target(6, 6) == 4


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_expected_damage
# ─────────────────────────────────────────────────────────────────────────────

class TestCalculateExpectedDamage:
    def test_zero_attacks_returns_zero(self):
        """exp_dmg_zero_attacks : 0 attaques → expected=0.0."""
        rc = _make_calculator()
        result = rc._calculate_expected_damage(0, 3, 4, 4, 0, 3, 7, 1.0)
        assert result == 0.0

    def test_normal_attack_positive(self):
        """exp_dmg_normal : attaque standard → expected > 0."""
        rc = _make_calculator()
        result = rc._calculate_expected_damage(3, 3, 4, 4, 0, 3, 7, 1.0)
        assert result > 0.0

    def test_impossible_save_maximizes_damage(self):
        """exp_dmg_no_save : save>6 → p_fail_save=1.0, calcul exact."""
        rc = _make_calculator()
        # p_hit = 4/6 (hit 3+), wound 4+ (S==T) → 3/6, no save → 1.0, dmg=1
        result = rc._calculate_expected_damage(6, 3, 4, 4, 0, 7, 7, 1.0)
        expected = 6 * (4 / 6) * (3 / 6) * 1.0 * 1.0
        assert abs(result - expected) < 1e-9

    def test_high_str_wound_on_2plus(self):
        """exp_dmg_2plus : S>=2×T → wound 2+, p_wound=5/6."""
        rc = _make_calculator()
        result = rc._calculate_expected_damage(6, 3, 8, 4, 0, 7, 7, 1.0)
        expected = 6 * (4 / 6) * (5 / 6) * 1.0 * 1.0
        assert abs(result - expected) < 1e-9

    def test_damage_multiplier_scales_linearly(self):
        """exp_dmg_scale : dmg×3 triple le résultat."""
        rc = _make_calculator()
        r1 = rc._calculate_expected_damage(6, 3, 4, 4, 0, 7, 7, 1.0)
        r3 = rc._calculate_expected_damage(6, 3, 4, 4, 0, 7, 7, 3.0)
        assert abs(r3 - 3 * r1) < 1e-9

    def test_ap_worsens_save_increases_damage(self):
        """exp_dmg_ap : AP négatif aggrave le save → plus de dégâts."""
        rc = _make_calculator()
        # AP=0 : armor 3+ reste 3+
        r_no_ap = rc._calculate_expected_damage(6, 3, 4, 4, 0, 3, 7, 1.0)
        # AP=-2 : armor 3+ devient 5+ (pire pour défenseur)
        r_with_ap = rc._calculate_expected_damage(6, 3, 4, 4, -2, 3, 7, 1.0)
        assert r_with_ap > r_no_ap

    def test_invul_better_than_armor_limits_damage(self):
        """exp_dmg_invul : invul 4+ meilleur qu'armor modifié 5+ → moins de dégâts."""
        rc = _make_calculator()
        # AP=-2 : armor 3+→5+, invul=4+ est meilleur (plus bas = meilleur pour défenseur)
        r_with_invul = rc._calculate_expected_damage(6, 3, 4, 4, -2, 3, 4, 1.0)
        r_no_invul = rc._calculate_expected_damage(6, 3, 4, 4, -2, 3, 7, 1.0)
        assert r_with_invul < r_no_invul

    def test_armor_worse_than_invul_invul_used(self):
        """exp_dmg_armor_worse : armor 6+ mais invul 3+ → invul 3+ utilisé."""
        rc = _make_calculator()
        # armor=4, AP=-2 → modified_armor=6. invul=3. best=3.
        # p_fail_save = (3-1)/6 = 2/6
        result = rc._calculate_expected_damage(6, 3, 4, 4, -2, 4, 3, 1.0)
        expected = 6 * (4 / 6) * (3 / 6) * (2 / 6) * 1.0
        assert abs(result - expected) < 1e-9

    def test_impossible_hit_returns_zero(self):
        """exp_dmg_no_hit : to_hit=7 → p_hit=0 → expected=0."""
        rc = _make_calculator()
        # p_hit = max(0, (7-7)/6) = 0
        result = rc._calculate_expected_damage(6, 7, 4, 4, 0, 7, 7, 1.0)
        assert result == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# _determine_winner (chemin legacy sans state_manager)
# ─────────────────────────────────────────────────────────────────────────────

class TestDetermineWinner:
    def test_only_player1_wins(self):
        """winner_p1 : seul joueur 1 a des unités → winner=1."""
        rc = _make_calculator()
        cache = {"1": _cache_entry(1), "2": _cache_entry(1)}
        result = rc._determine_winner(_gs_with_cache(cache))
        assert result == 1

    def test_only_player2_wins(self):
        """winner_p2 : seul joueur 2 a des unités → winner=2."""
        rc = _make_calculator()
        cache = {"1": _cache_entry(2), "2": _cache_entry(2)}
        result = rc._determine_winner(_gs_with_cache(cache))
        assert result == 2

    def test_both_players_alive_returns_none(self):
        """winner_none : les deux joueurs ont des unités → None (partie en cours)."""
        rc = _make_calculator()
        cache = {"1": _cache_entry(1), "2": _cache_entry(2)}
        result = rc._determine_winner(_gs_with_cache(cache))
        assert result is None

    def test_empty_cache_returns_minus_one(self):
        """winner_draw : cache vide → -1 (égalité/élimination mutuelle)."""
        rc = _make_calculator()
        result = rc._determine_winner(_gs_with_cache({}))
        assert result == -1

    def test_multiple_units_same_player(self):
        """winner_multi : 3 unités joueur 1, 0 joueur 2 → winner=1."""
        rc = _make_calculator()
        cache = {"1": _cache_entry(1), "2": _cache_entry(1), "3": _cache_entry(1)}
        result = rc._determine_winner(_gs_with_cache(cache))
        assert result == 1

    def test_single_unit_player2_wins(self):
        """winner_single_p2 : 1 unité joueur 2 → winner=2."""
        rc = _make_calculator()
        cache = {"5": _cache_entry(2)}
        result = rc._determine_winner(_gs_with_cache(cache))
        assert result == 2
