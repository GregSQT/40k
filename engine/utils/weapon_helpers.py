"""
Weapon Helper Functions

MULTIPLE_WEAPONS_IMPLEMENTATION.md: Helper functions for accessing weapon data
"""

from typing import Dict, Optional, Any
from shared.data_validation import require_key
from engine.combat_utils import expected_dice_value


def weapon_has_rule(weapon: Dict[str, Any], rule_id: str) -> bool:
    """True si l'arme declare la regle `rule_id` dans WEAPON_RULES.

    Gere les deux formes d'entree : chaine 'NAME' et chaine parametree 'NAME:param'.
    Comparaison insensible a la casse. Aucun repli masquant : WEAPON_RULES est
    exige (require_key) et doit etre une liste, sinon erreur explicite.

    2026-07-29 — la branche `hasattr(entry, "rule")` (forme objet `ParsedWeaponRule`) a ete
    SUPPRIMEE : ce type n'est plus constructible hors du parseur d'armurerie, qui jette son
    resultat, et `WEAPON_RULES` ne contient que des chaines partout. Note : `hasattr` etait un
    test de FORME, pas de type — il aurait attrape n'importe quel objet portant un attribut
    `.rule`. Une telle entree tombe desormais dans le `raise TypeError` ci-dessous, c'est-a-dire
    une erreur explicite plutot qu'un traitement silencieux d'une donnee inattendue.
    """
    rules = require_key(weapon, "WEAPON_RULES")
    if not isinstance(rules, list):
        raise TypeError(
            f"WEAPON_RULES must be a list, got {type(rules).__name__} "
            f"for weapon {weapon.get('display_name', weapon.get('NAME'))}"
        )
    target = rule_id.strip().upper()
    for entry in rules:
        if isinstance(entry, str):
            name = entry.split(":", 1)[0]
        else:
            raise TypeError(
                f"Unsupported WEAPON_RULES entry type: {type(entry).__name__} ({entry!r})"
            )
        if str(name).strip().upper() == target:
            return True
    return False


def weapon_rule_parameter(weapon: Dict[str, Any], rule_id: str) -> Optional[int]:
    """Valeur entiere du parametre d'une regle d'arme parametree (ex: RAPID_FIRE:X).

    Forme unique : chaine 'NAME:param'. Comparaison du nom insensible a la casse.
    Retourne None si l'arme ne declare PAS `rule_id`. Leve (aucun repli masquant) si la
    regle est presente mais son parametre est absent ou non entier. Miroir de l'extraction
    de `ai/analyzer_config.py` (RAPID_FIRE), mutualisee ici pour le chemin de resolution.

    2026-07-29 — la branche objet `ParsedWeaponRule` a ete SUPPRIMEE, meme raison que dans
    `weapon_has_rule` : type non constructible hors du parseur, qui jette son resultat. Toute
    entree non-chaine leve desormais explicitement.
    """
    rules = require_key(weapon, "WEAPON_RULES")
    if not isinstance(rules, list):
        raise TypeError(
            f"WEAPON_RULES must be a list, got {type(rules).__name__} "
            f"for weapon {weapon.get('display_name', weapon.get('NAME'))}"
        )
    target = rule_id.strip().upper()
    for entry in rules:
        if isinstance(entry, str):
            if entry.split(":", 1)[0].strip().upper() != target:
                continue
            if ":" not in entry:
                raise ValueError(f"Weapon rule {rule_id!r} present but missing parameter: {entry!r}")
            raw: Any = entry.split(":", 1)[1]
        else:
            raise TypeError(
                f"Unsupported WEAPON_RULES entry type: {type(entry).__name__} ({entry!r})"
            )
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid parameter for weapon rule {rule_id!r}: {raw!r}") from exc
    return None


def weapon_rule_parameter_or(weapon: Dict[str, Any], rule_id: str, default: int) -> Optional[int]:
    """Parametre d'une regle d'arme dont le parametre est OPTIONNEL par les regles.

    Cas vise : [BLAST] 24.05 et [CLEAVE] 24.06, ou la forme nue ([BLAST]) vaut « 1 dé
    additionnel par tranche de 5 figurines » et la forme parametree ([BLAST 2]) vaut X.
    `default` est donc une valeur METIER definie par le PDF, pas un repli anti-erreur.

    Retourne None si l'arme ne declare PAS la regle.
    """
    if not weapon_has_rule(weapon, rule_id):
        return None
    try:
        value = weapon_rule_parameter(weapon, rule_id)
    except ValueError:
        return default
    return default if value is None else value


def get_selected_ranged_weapon(unit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Get currently selected ranged weapon."""
    if "RNG_WEAPONS" not in unit:
        raise KeyError(f"Unit missing RNG_WEAPONS: {unit}")
    rng_weapons = require_key(unit, "RNG_WEAPONS")
    if not rng_weapons:
        return None
    idx = require_key(unit, "selectedRngWeaponIndex")
    if idx < 0 or idx >= len(rng_weapons):
        raise IndexError(f"Invalid selectedRngWeaponIndex {idx} for unit {unit['id']}")
    return rng_weapons[idx]


def get_selected_melee_weapon(unit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Get currently selected melee weapon."""
    if "CC_WEAPONS" not in unit:
        raise KeyError(f"Unit missing CC_WEAPONS: {unit}")
    cc_weapons = require_key(unit, "CC_WEAPONS")
    if not cc_weapons:
        return None
    idx = require_key(unit, "selectedCcWeaponIndex")
    if idx < 0 or idx >= len(cc_weapons):
        raise IndexError(f"Invalid selectedCcWeaponIndex {idx} for unit {unit['id']}")
    return cc_weapons[idx]


def get_max_ranged_range(unit: Dict[str, Any]) -> int:
    """Get maximum range of all ranged weapons."""
    rng_weapons = require_key(unit, "RNG_WEAPONS")
    if not rng_weapons:
        return 0
    return max(require_key(w, "RNG") for w in rng_weapons)


def get_max_ranged_damage(unit: Dict[str, Any]) -> float:
    """
    Get maximum possible damage from ranged weapons (NB * DMG).
    Returns 0.0 if unit has no ranged weapons.
    
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Helper for threat calculations.
    """
    rng_weapons = require_key(unit, "RNG_WEAPONS")
    if not rng_weapons:
        return 0.0
    return max((expected_dice_value(require_key(w, "NB"), "max_ranged_nb") *
                expected_dice_value(require_key(w, "DMG"), "max_ranged_dmg"))
               for w in rng_weapons)


def get_max_melee_damage(unit: Dict[str, Any]) -> float:
    """
    Get maximum possible damage from melee weapons (NB * DMG).
    Returns 0.0 if unit has no melee weapons.
    
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Helper for threat calculations.
    """
    cc_weapons = require_key(unit, "CC_WEAPONS")
    if not cc_weapons:
        return 0.0
    return max((expected_dice_value(require_key(w, "NB"), "max_melee_nb") *
                expected_dice_value(require_key(w, "DMG"), "max_melee_dmg"))
               for w in cc_weapons)
