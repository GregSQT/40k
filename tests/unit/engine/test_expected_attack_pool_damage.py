"""`expected_attack_pool_damage` — espérance EXACTE de `roll_attack_pool` + sauvegarde (S11).

Deux verrous :
1. Sans relance ni plancher, elle vaut `n_attacks × expected_damage_per_attack` (la définition
   déjà publiée pour le choix de profil), sur une grille de seuils et de règles d'arme.
2. AVEC relances (touche, blessure, sauvegarde), plancher 10.07, [SUSTAINED], [LETHAL],
   [DEVASTATING], [TWIN-LINKED] : Monte-Carlo contre `roll_attack_pool` lui-même, suivi de la
   comparaison de sauvegarde telle que l'allocation la fait (1 naturel échoue, sinon ≥ seuil).
   C'est la preuve que l'espérance modélise le roller RÉEL, pas une formule voisine.
"""
from __future__ import annotations

import random
from typing import Dict

import pytest

from engine.phase_handlers.attack_sequence import (
    NATURAL_FAIL_ROLL,
    RerollProfile,
    WeaponAttackProfile,
    expected_attack_pool_damage,
    expected_damage_per_attack,
    roll_attack_pool,
)


def _realized_damage(rolled: Dict, save_threshold_value: int) -> int:
    """Blessures non sauvées d'un pool, comparaison identique à `_resolve_one_manual_wound`."""
    unsaved = 0
    for pw in rolled["pending_wounds"]:
        if pw["devastating"]:
            unsaved += 1
            continue
        save_roll = int(pw["save_roll"])
        if save_roll != NATURAL_FAIL_ROLL and save_roll >= save_threshold_value:
            continue
        unsaved += 1
    return unsaved


_PROFILES = {
    "plain": WeaponAttackProfile(),
    "sustained_2": WeaponAttackProfile(sustained_hits=2),
    "lethal": WeaponAttackProfile(lethal_hits=True),
    "devastating_anti5": WeaponAttackProfile(devastating=True, crit_wound_on=5),
    "twin": WeaponAttackProfile(twin_linked=True),
    "torrent_sustained": WeaponAttackProfile(torrent=True, sustained_hits=1),
    "crit_hit_5_lethal_dev": WeaponAttackProfile(crit_hit_on=5, lethal_hits=True, devastating=True),
}


@pytest.mark.parametrize("profile_name", sorted(_PROFILES))
@pytest.mark.parametrize("hit_target,wound_target,save_threshold_value", [
    (3, 4, 5), (2, 2, 7), (6, 6, 2), (4, 3, 4),
])
def test_sans_relance_egale_expected_damage_per_attack(
    profile_name: str, hit_target: int, wound_target: int, save_threshold_value: int
) -> None:
    profile = _PROFILES[profile_name]
    per_attack = expected_damage_per_attack(
        profile, hit_target=hit_target, wound_target=wound_target,
        save_threshold_value=save_threshold_value, damage=1.0,
    )
    pool = expected_attack_pool_damage(
        n_attacks=7.5, hit_target=hit_target, wound_target=wound_target,
        save_threshold_value=save_threshold_value, profile=profile,
        rerolls=RerollProfile(), damage=1.0,
    )
    assert pool == pytest.approx(7.5 * per_attack, abs=1e-12)


_MC_CASES = [
    # (profil, seuils, relances, plancher)
    ("plain", (3, 4, 5), RerollProfile(hit_any_fail=True), 2),
    ("plain", (4, 3, 4), RerollProfile(hit_1=True, wound_1=True, save_1=True), 2),
    ("sustained_2", (3, 3, 3), RerollProfile(wound_any_fail=True), 2),
    ("lethal", (2, 5, 6), RerollProfile(hit_any_fail=True, wound_1=True), 2),
    ("devastating_anti5", (4, 4, 2), RerollProfile(hit_1=True), 2),
    ("twin", (3, 5, 4), RerollProfile(wound_1=True), 2),
    ("torrent_sustained", (3, 4, 5), RerollProfile(wound_any_fail=True, save_1=True), 2),
    ("crit_hit_5_lethal_dev", (3, 4, 3), RerollProfile(hit_any_fail=True), 2),
    # 10.07 : plancher 4 (1-3 ratent), BS 2+ — seul le critique passe sous le plancher.
    ("plain", (2, 4, 5), RerollProfile(), 4),
    ("sustained_2", (2, 3, 4), RerollProfile(hit_1=True, save_1=True), 6),
]


@pytest.mark.parametrize("profile_name,thresholds,rerolls,fail_below", _MC_CASES)
def test_monte_carlo_contre_roll_attack_pool(
    profile_name: str, thresholds, rerolls: RerollProfile, fail_below: int
) -> None:
    """Sur 40 000 attaques, la moyenne réalisée doit tomber à ±0,015 de l'espérance
    (écart-type de la moyenne ≤ 0,004 pour un dégât par blessure de 1 et ≤ 3 hits par attaque)."""
    profile = _PROFILES[profile_name]
    hit_target, wound_target, save_threshold_value = thresholds
    rng = random.Random(20260914)
    n_attacks = 40_000
    rolled = roll_attack_pool(
        n_attacks=n_attacks, hit_target=hit_target, wound_target=wound_target,
        save_threshold_value=save_threshold_value, profile=profile, rerolls=rerolls,
        roll_d6=lambda: rng.randint(1, 6), hit_fail_below=fail_below,
    )
    realized = _realized_damage(rolled, save_threshold_value) / n_attacks
    expected = expected_attack_pool_damage(
        n_attacks=1.0, hit_target=hit_target, wound_target=wound_target,
        save_threshold_value=save_threshold_value, profile=profile, rerolls=rerolls,
        damage=1.0, hit_fail_below=fail_below,
    )
    assert expected > 0.0, "cas dégénéré : l'espérance nulle ne teste rien"
    assert realized == pytest.approx(expected, abs=0.015), (
        f"{profile_name} {thresholds} {rerolls} plancher {fail_below} : "
        f"réalisé {realized:.4f} vs espérance {expected:.4f}"
    )


def test_le_degat_et_le_nombre_d_attaques_sont_des_facteurs() -> None:
    def _expected(n_attacks: float, damage: float) -> float:
        return expected_attack_pool_damage(
            n_attacks=n_attacks, hit_target=3, wound_target=4, save_threshold_value=5,
            profile=_PROFILES["sustained_2"], rerolls=RerollProfile(hit_any_fail=True),
            damage=damage,
        )

    base = _expected(n_attacks=1.0, damage=1.0)
    assert _expected(n_attacks=3.5, damage=2.25) == pytest.approx(3.5 * 2.25 * base)
