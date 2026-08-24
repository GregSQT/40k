"""
Espérance de dégâts contextualisée : NB × P(toucher) × P(blesser) × P(échec_sv) × DMG.

Utilisée par reward_mapper.py quand l'attaquant ET la cible sont connus.
Là où seul l'attaquant est connu, le proxy NB×DMG de weapon_helpers reste utilisé.
"""

from typing import Any, Dict

from shared.data_validation import require_key
from engine.combat_utils import expected_dice_value
from engine.phase_handlers.attack_sequence import (
    build_weapon_attack_profile,
    expected_damage_per_attack,
)
from engine.phase_handlers.shared_utils import wound_threshold, save_threshold


def expected_damage(
    attacker_unit: Dict[str, Any],
    weapon: Dict[str, Any],
    target_unit: Dict[str, Any],
) -> float:
    """NB × E[dégâts/attaque] avec probabilités réelles de toucher, blesser, rater la save.

    Champs requis :
      weapon      — ATK (BS ou WS selon phase), STR, AP, NB, DMG, WEAPON_RULES
      target_unit — T, ARMOR_SAVE, INVUL_SAVE (7 = aucune invul)

    V1 : règles agissant sur le POOL ([BLAST], [RAPID FIRE], [CLEAVE], [EXTRA ATTACKS])
    non intégrées — elles multiplient le nombre d'attaques, pas la valeur par attaque.
    L'appelant peut les appliquer en multipliant le résultat par le facteur de pool.
    """
    nb = float(expected_dice_value(require_key(weapon, "NB"), "expected_damage_nb"))
    dmg = float(expected_dice_value(require_key(weapon, "DMG"), "expected_damage_dmg"))
    hit_target = int(require_key(weapon, "ATK"))
    strength = int(require_key(weapon, "STR"))
    ap = int(require_key(weapon, "AP"))
    toughness = int(require_key(target_unit, "T"))
    armor_sv = int(require_key(target_unit, "ARMOR_SAVE"))
    invul_sv = int(require_key(target_unit, "INVUL_SAVE"))

    profile = build_weapon_attack_profile(weapon, target_unit)
    ev_per_attack = expected_damage_per_attack(
        profile,
        hit_target=hit_target,
        wound_target=wound_threshold(strength, toughness),
        save_threshold_value=save_threshold(armor_sv, invul_sv, ap),
        damage=dmg,
    )
    return nb * ev_per_attack
