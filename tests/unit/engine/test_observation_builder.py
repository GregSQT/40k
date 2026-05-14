"""Tests unitaires — ObservationBuilder : wound_target, expected_damage, favorite_target."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.observation_builder import ObservationBuilder


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _make_builder() -> ObservationBuilder:
    """Instance minimale avec config obligatoire."""
    config = {
        "observation_params": {
            "perception_radius": 25,
            "max_nearby_units": 6,
            "max_valid_targets": 5,
            "obs_size": 357,
        }
    }
    return ObservationBuilder(config)


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_wound_target (même table que reward_calculator)
# ─────────────────────────────────────────────────────────────────────────────

class TestObsWoundTarget:
    def test_str_double_t_wounds_2plus(self):
        """obs_wound_2 : S>=2T → 2."""
        b = _make_builder()
        assert b._calculate_wound_target(8, 4) == 2

    def test_str_gt_t_wounds_3plus(self):
        """obs_wound_3 : S>T → 3."""
        b = _make_builder()
        assert b._calculate_wound_target(5, 4) == 3

    def test_str_eq_t_wounds_4plus(self):
        """obs_wound_4 : S==T → 4."""
        b = _make_builder()
        assert b._calculate_wound_target(4, 4) == 4

    def test_str_lt_half_t_wounds_6plus(self):
        """obs_wound_6 : S<T/2 → 6."""
        b = _make_builder()
        assert b._calculate_wound_target(1, 4) == 6

    def test_str_near_t_wounds_5plus(self):
        """obs_wound_5 : S<T mais 2S>T → 5."""
        b = _make_builder()
        assert b._calculate_wound_target(3, 4) == 5

    def test_equal_double_toughness_wounds_2(self):
        """obs_wound_2eq : S==2T exactement → 2."""
        b = _make_builder()
        assert b._calculate_wound_target(6, 3) == 2


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_expected_damage
# ─────────────────────────────────────────────────────────────────────────────

class TestObsExpectedDamage:
    def test_zero_attacks(self):
        """obs_exp_zero : 0 attaques → 0.0."""
        b = _make_builder()
        assert b._calculate_expected_damage(0, 3, 4, 4, 0, 3, 7, 1.0) == 0.0

    def test_positive_normal_case(self):
        """obs_exp_pos : cas standard → expected > 0."""
        b = _make_builder()
        assert b._calculate_expected_damage(4, 3, 4, 4, 0, 3, 7, 1.0) > 0.0

    def test_impossible_save_exact(self):
        """obs_exp_nosave : save>6 → p_fail_save=1.0, calcul exact."""
        b = _make_builder()
        # p_hit=4/6 (hit 3+), wound S==T → 4+ (p=3/6), no save, dmg=2
        result = b._calculate_expected_damage(6, 3, 4, 4, 0, 7, 7, 2.0)
        expected = 6 * (4 / 6) * (3 / 6) * 1.0 * 2.0
        assert abs(result - expected) < 1e-9

    def test_invul_better_than_armor_reduces_damage(self):
        """obs_exp_invul : invul meilleur que armor modifié → moins de dégâts."""
        b = _make_builder()
        r_invul = b._calculate_expected_damage(6, 3, 4, 4, -2, 3, 4, 1.0)
        r_no_invul = b._calculate_expected_damage(6, 3, 4, 4, -2, 3, 7, 1.0)
        assert r_invul < r_no_invul

    def test_ap_increases_damage(self):
        """obs_exp_ap : AP négatif → plus de dégâts."""
        b = _make_builder()
        r_no_ap = b._calculate_expected_damage(6, 3, 4, 4, 0, 3, 7, 1.0)
        r_ap = b._calculate_expected_damage(6, 3, 4, 4, -2, 3, 7, 1.0)
        assert r_ap > r_no_ap

    def test_damage_scales_linearly(self):
        """obs_exp_scale : dmg_per_wound×2 → résultat×2."""
        b = _make_builder()
        r1 = b._calculate_expected_damage(6, 3, 4, 4, 0, 7, 7, 1.0)
        r2 = b._calculate_expected_damage(6, 3, 4, 4, 0, 7, 7, 2.0)
        assert abs(r2 - 2 * r1) < 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_favorite_target (version observation_builder : basée sur les armes)
# ─────────────────────────────────────────────────────────────────────────────

def _weapon_profile(str_: int = 4, ap: int = 0, dmg: int = 1) -> Dict[str, Any]:
    return {"STR": str_, "AP": ap, "DMG": dmg, "ATK": 3, "NB": 1}


class TestObsFavoriteTarget:
    def _unit_no_weapons(self) -> Dict[str, Any]:
        return {"RNG_WEAPONS": [], "CC_WEAPONS": []}

    def _unit_with_rng(self, str_: int, ap: int = 0, dmg: int = 1) -> Dict[str, Any]:
        return {
            "RNG_WEAPONS": [_weapon_profile(str_=str_, ap=ap, dmg=dmg)],
            "CC_WEAPONS": [],
        }

    def test_no_weapons_returns_neutral(self):
        """obs_fav_none : aucune arme → 0.5 (neutre)."""
        b = _make_builder()
        assert b._calculate_favorite_target(self._unit_no_weapons()) == 0.5

    def test_strong_weapon_higher_than_weak(self):
        """obs_fav_str : arme STR élevée → score plus haut qu'arme faible."""
        b = _make_builder()
        score_strong = b._calculate_favorite_target(self._unit_with_rng(str_=10, ap=-3, dmg=3))
        score_weak = b._calculate_favorite_target(self._unit_with_rng(str_=1, ap=0, dmg=1))
        assert score_strong > score_weak

    def test_result_in_range_0_to_1(self):
        """obs_fav_range : score toujours dans [0,1]."""
        b = _make_builder()
        score = b._calculate_favorite_target(self._unit_with_rng(str_=8, ap=-2, dmg=2))
        assert 0.0 <= score <= 1.0

    def test_missing_rng_weapons_raises(self):
        """obs_fav_missing_rng : RNG_WEAPONS absent → KeyError/ConfigurationError."""
        b = _make_builder()
        with pytest.raises(Exception):  # ConfigurationError (subclass of Exception)
            b._calculate_favorite_target({})

    def test_cc_weapon_contributes_to_score(self):
        """obs_fav_cc : arme CC forte → score > 0."""
        b = _make_builder()
        unit = {"RNG_WEAPONS": [], "CC_WEAPONS": [_weapon_profile(str_=6, ap=-1, dmg=2)]}
        score = b._calculate_favorite_target(unit)
        assert score > 0.0

    def test_two_weapons_uses_best(self):
        """obs_fav_best : deux armes → score = meilleure arme."""
        b = _make_builder()
        unit = {
            "RNG_WEAPONS": [_weapon_profile(str_=2, ap=0, dmg=1)],
            "CC_WEAPONS": [_weapon_profile(str_=8, ap=-2, dmg=3)],
        }
        score_combined = b._calculate_favorite_target(unit)
        score_best_only = b._calculate_favorite_target({
            "RNG_WEAPONS": [_weapon_profile(str_=8, ap=-2, dmg=3)],
            "CC_WEAPONS": [],
        })
        assert abs(score_combined - score_best_only) < 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# ObservationBuilder __init__ validation
# ─────────────────────────────────────────────────────────────────────────────

class TestObsBuilderInit:
    def test_missing_observation_params_raises(self):
        """obs_init_missing : config sans observation_params → KeyError."""
        with pytest.raises(KeyError):
            ObservationBuilder(config={})

    def test_missing_obs_size_raises(self):
        """obs_init_no_size : observation_params sans obs_size → KeyError."""
        with pytest.raises(KeyError):
            ObservationBuilder(config={
                "observation_params": {
                    "perception_radius": 25,
                    "max_nearby_units": 6,
                    "max_valid_targets": 5,
                    # obs_size manquant
                }
            })

    def test_valid_config_initializes(self):
        """obs_init_ok : config minimale valide → instance créée."""
        b = _make_builder()
        assert b.obs_size == 357
        assert b.perception_radius == 25
        assert b.max_nearby_units == 6
