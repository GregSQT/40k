"""Tests pour engine/utils/expected_damage.py.

Cas concrets vérifiés analytiquement avec la formule 40K :
  NB × P(hit) × P(wound) × P(fail_save) × DMG

Hypothèses de calcul (attaque sans règle d'arme) :
  P(hit)       = P(f != 1 et f >= hit_target, sur D6) — un 6 non modifié est critique
  P(wound)     = P(f != 1 et f >= wound_target, sur D6)
  P(fail_save) = P(f == 1 ou f < save_threshold, sur D6)
"""

import pytest

from shared.data_validation import ConfigurationError
from engine.utils.expected_damage import expected_damage


def _weapon(atk: int, strength: int, ap: int, nb: int | str = 1, dmg: int | str = 1) -> dict:
    """Arme minimale sans règle d'arme."""
    return {
        "ATK": atk, "STR": strength, "AP": ap,
        "NB": nb, "DMG": dmg, "WEAPON_RULES": [], "code": "test_weapon",
    }


def _target(t: int, sv: int, invul: int = 7) -> dict:
    """Cible minimale — invul=7 = aucune invulnérable."""
    return {"T": t, "ARMOR_SAVE": sv, "INVUL_SAVE": invul}


# ---------------------------------------------------------------------------
# Test 1 : Bolter (S4, AP0, BS3+) contre Marine (T4, Sv3+)
# ---------------------------------------------------------------------------
# P(hit)       : f!=1 et f>=3 = {3,4,5} normal + {6} crit = 4/6
# P(wound|hit) : f!=1 et f>=4 = {4,5} normal + {6} crit = 3/6  (S==T → 4+)
# P(fail_save) : f==1 ou f<3  = {1,2}                   = 2/6
# NB=2, DMG=1
# ev_wound_once = (1/6)*(2/6) + (2/6)*(2/6)  = 6/36 = 1/6
# p_all_hit = (1/6 crit + 3/6 normal) = 4/6
# ev_per_atk  = (4/6)*(1/6)*1  = 4/36 = 1/9
# expected     = 2 * 1/9       = 2/9
def test_bolter_vs_marine():
    weapon = _weapon(atk=3, strength=4, ap=0, nb=2, dmg=1)
    target = _target(t=4, sv=3)
    result = expected_damage(weapon, target)
    assert result == pytest.approx(2 / 9, rel=1e-6)


# ---------------------------------------------------------------------------
# Test 2 : Fuseur (S8, AP-4, BS3+) contre Marine (T4, Sv3+)
# ---------------------------------------------------------------------------
# save_threshold = 3 - (-4) = 7  → P(fail_save) = 1.0 (aucune save possible)
# wound_target   = 2  (S >= 2T)
# P(wound|hit)   : f!=1 et f>=2 = {2,3,4,5} + {6} = 5/6
# p_all_hit = 4/6 (same BS3+)
# ev_wound_once  = (1/6)*1.0 + (4/6)*1.0 = 5/6
# ev_per_atk     = (4/6)*(5/6)*3.5 = (20/36)*3.5 = 70/36 = 35/18
# NB=1 → expected = 35/18
def test_fuseur_vs_marine_save_impossible():
    weapon = _weapon(atk=3, strength=8, ap=-4, nb=1, dmg="D6")
    target = _target(t=4, sv=3)
    result = expected_damage(weapon, target)
    assert result == pytest.approx(35 / 18, rel=1e-6)
    # Fuseur >> bolter (35/18 ≈ 1.94 vs 2/9 ≈ 0.22)
    bolter = expected_damage(_weapon(atk=3, strength=4, ap=0, nb=2, dmg=1), target)
    assert result > bolter


# ---------------------------------------------------------------------------
# Test 3 : InSv 4+ meilleure que la sauvegarde armure modifiée (Sv3+, AP-3)
# ---------------------------------------------------------------------------
# Sans invul : effective=3-(-3)=6 → p_fail_save=5/6
# Avec InSv 4+: save_threshold=min(6,4)=4 → p_fail_save=3/6
# La cible avec InSv reçoit moins de dégâts.
def test_invul_save_better_than_modified_armor():
    weapon = _weapon(atk=3, strength=4, ap=-3, nb=1, dmg=1)
    target_no_invul = _target(t=4, sv=3, invul=7)
    target_invul_4 = _target(t=4, sv=3, invul=4)

    ev_no_invul = expected_damage(weapon, target_no_invul)
    ev_with_invul = expected_damage(weapon, target_invul_4)

    # Avec InSv 4+ → moins de dégâts attendus
    assert ev_with_invul < ev_no_invul

    # Valeurs exactes :
    # Sans invul  : ev_wound=(1/6+2/6)*(5/6)=3/6*5/6=15/36  ; ev_atk=(4/6)*(15/36)=60/216=5/18
    # Avec InSv4+ : ev_wound=(1/6+2/6)*(3/6)=3/6*3/6=9/36   ; ev_atk=(4/6)*(9/36)=36/216=1/6
    assert ev_no_invul == pytest.approx(5 / 18, rel=1e-6)
    assert ev_with_invul == pytest.approx(1 / 6, rel=1e-6)


# ---------------------------------------------------------------------------
# T1 : champs obligatoires absents → KeyError (pas de fallback)
# ---------------------------------------------------------------------------
def test_missing_atk_raises():
    weapon = {"STR": 4, "AP": 0, "NB": 1, "DMG": 1, "WEAPON_RULES": []}
    with pytest.raises(ConfigurationError):
        expected_damage(weapon, _target(t=4, sv=3))


def test_missing_target_t_raises():
    weapon = _weapon(atk=3, strength=4, ap=0)
    target = {"ARMOR_SAVE": 3, "INVUL_SAVE": 7}
    with pytest.raises(ConfigurationError):
        expected_damage(weapon, target)


def test_missing_invul_save_raises():
    weapon = _weapon(atk=3, strength=4, ap=0)
    target = {"T": 4, "ARMOR_SAVE": 3}
    with pytest.raises(ConfigurationError):
        expected_damage(weapon, target)


# ---------------------------------------------------------------------------
# Sanité : meilleur BS → plus de dégâts (toutes choses égales)
# ---------------------------------------------------------------------------
def test_better_bs_deals_more_damage():
    target = _target(t=4, sv=3)
    ev_bs3 = expected_damage(_weapon(atk=3, strength=4, ap=0, nb=1, dmg=1), target)
    ev_bs2 = expected_damage(_weapon(atk=2, strength=4, ap=0, nb=1, dmg=1), target)
    assert ev_bs2 > ev_bs3


# ---------------------------------------------------------------------------
# Intégration : _can_unit_kill_target_in_one_phase utilise expected_damage
# via la vraie probabilité et non NB×DMG brut
# ---------------------------------------------------------------------------
def test_can_kill_uses_probabilistic_damage(monkeypatch: pytest.MonkeyPatch) -> None:
    """expected_damage (≈ 35/18 ≈ 1.94) remplace le proxy NB×DMG=3.5.

    Trois cas sur le même fuseur :
    - target_hp=2 > 1.94 → False (ne peut pas tuer)
    - target_hp=1 ≤ 1.94 → True  (peut tuer)
    - target_hp=35/18 = expected_damage → True (frontière exacte, prouve ≤ pas <)
    """
    import ai.reward_mapper as rmod
    from ai.reward_mapper import RewardMapper

    mapper = RewardMapper({})

    weapon = _weapon(atk=3, strength=8, ap=-4, nb=1, dmg="D6")
    target = _target(t=4, sv=3)
    target["id"] = "t1"

    unit = {
        "RNG_WEAPONS": [weapon],
        "selectedRngWeaponIndex": 0,
        "CC_WEAPONS": [],
        "selectedCcWeaponIndex": 0,
    }

    def can_kill() -> bool:
        return mapper._can_unit_kill_target_in_one_phase(unit, target, is_ranged=True, game_state={})

    hp = 2
    monkeypatch.setattr(rmod, "get_hp_from_cache", lambda uid, gs: hp)

    assert can_kill() is False  # expected_damage ≈ 1.94 < 2
    hp = 1
    assert can_kill() is True   # 1 ≤ 1.94
    hp = expected_damage(weapon, target)  # frontière exacte (virgule flottante réelle)
    assert can_kill() is True   # max_damage ≤ max_damage (sémantique ≤, pas <)
