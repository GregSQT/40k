"""
Weapon Helper Functions

MULTIPLE_WEAPONS_IMPLEMENTATION.md: Helper functions for accessing weapon data
"""

from typing import Any, Dict, FrozenSet, List, Optional, Tuple
from shared.data_validation import require_key
from engine.combat_utils import expected_dice_value


def ranged_weapons(entity: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Profils d'armes de TIR portes par une unite OU une figurine (`RNG_WEAPONS`).

    LISTE VIDE = l'entite n'a pas d'arme de tir. C'est un CAS METIER REEL, et il est ecrit
    dans la donnee : 21 des 179 datasheets des rosters declarent `RNG_WEAPONS: []`
    (Genestealer, Hormagaunt, Assault Terminator... les unites de melee pure).

    CLE ABSENTE = entite mal construite. Tous les constructeurs posent la cle
    inconditionnellement : `create_unit` et `_build_enhanced_unit` (moteur),
    `_build_models_for_unit` (figurines du models_cache), `_build_units_from_army_config`
    (API) et le spawn Endless Duty. Une entite sans la cle n'est donc pas une unite sans
    arme : c'est un dictionnaire incomplet.

    L'ancien `entity.get("RNG_WEAPONS", [])` dissemine dans les gestionnaires de phase
    CONFONDAIT les deux : une figurine incomplete se comportait exactement comme un
    Genestealer. Cet accesseur les separe — et il porte la justification UNE fois, au lieu
    de la recopier a une trentaine de sites d'appel.

    Meme doctrine que `get_max_ranged_range` / `get_max_ranged_damage` de ce module, qui
    exigent deja la cle et traitent la liste vide comme un etat valide.
    """
    weapons = require_key(entity, "RNG_WEAPONS")
    if not isinstance(weapons, list):
        raise TypeError(
            f"RNG_WEAPONS must be a list, got {type(weapons).__name__} "
            f"for entity {entity.get('id', '?')}"
        )
    return weapons


def melee_weapons(entity: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Profils d'armes de MELEE portes par une unite OU une figurine (`CC_WEAPONS`).

    Jumeau exact de `ranged_weapons` : liste vide = pas d'arme de melee (cas metier reel,
    1 datasheet sur 179 : Mucolid) ; cle absente = entite mal construite.
    """
    weapons = require_key(entity, "CC_WEAPONS")
    if not isinstance(weapons, list):
        raise TypeError(
            f"CC_WEAPONS must be a list, got {type(weapons).__name__} "
            f"for entity {entity.get('id', '?')}"
        )
    return weapons


def _iter_weapon_rules(weapon: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Regles declarees par l'arme, NORMALISEES : `[(NOM_MAJUSCULE, parametre_brut), ...]`.

    PRIMITIVE UNIQUE de lecture de `WEAPON_RULES`, consommee par les trois accesseurs publics
    ci-dessous. Elle a d'abord existe en trois copies (une par accesseur), et la derive avait
    commence : deux faisaient `split(":", 1)`, la troisieme `partition(":")`. Elles coincidaient,
    rien ne le garantissait. Or `weapon_has_rule` et `weapon_rule_signature` DOIVENT repondre sur
    la meme normalisation : le premier ouvre l'application d'une regle, la seconde decide si deux
    armes font des attaques identiques (04.03). Une divergence entre les deux, c'est le defaut de
    lot d'allocation que ce module vient de corriger, rejoue a l'envers.

    Parametre rendu BRUT (non converti) : seul `weapon_rule_parameter` sait qu'il attend un entier
    et sait quoi lever si ce n'en est pas un. Chaine vide = regle sans parametre.

    Aucun repli masquant : `WEAPON_RULES` est exige (require_key), doit etre une liste, et toute
    entree non-chaine leve. La forme objet `ParsedWeaponRule` a ete supprimee le 2026-07-29 (type
    non constructible hors du parseur d'armurerie, qui jette son resultat).
    """
    rules = require_key(weapon, "WEAPON_RULES")
    if not isinstance(rules, list):
        raise TypeError(
            f"WEAPON_RULES must be a list, got {type(rules).__name__} "
            f"for weapon {weapon.get('display_name', weapon.get('NAME'))}"
        )
    out: List[Tuple[str, str]] = []
    for entry in rules:
        if not isinstance(entry, str):
            raise TypeError(
                f"Unsupported WEAPON_RULES entry type: {type(entry).__name__} ({entry!r})"
            )
        name, _, param = entry.partition(":")
        out.append((name.strip().upper(), param.strip()))
    return out


def weapon_has_rule(weapon: Dict[str, Any], rule_id: str) -> bool:
    """True si l'arme declare la regle `rule_id` dans WEAPON_RULES.

    Gere les deux formes d'entree : chaine 'NAME' et chaine parametree 'NAME:param'.
    Comparaison insensible a la casse. Normalisation deleguee a `_iter_weapon_rules`.
    """
    target = rule_id.strip().upper()
    return any(name == target for name, _ in _iter_weapon_rules(weapon))


def weapon_rule_signature(weapon: Dict[str, Any]) -> FrozenSet[str]:
    """Ensemble NORMALISE des regles declarees par l'arme, parametre compris.

    Sert la clause « **and which are affected by the same applicable abilities and rules** » de
    l'encadre IDENTICAL ATTACKS de 04.03 : deux armes ne font des attaques identiques que si
    elles partagent BS/WS, S, AP, D **et** leurs regles. Sans cette moitie-la, le lot
    d'allocation fusionnait des armes aux regles differentes (Shoota RAPID_FIRE:1, Kombi Shoota
    aucune, Kustom Shoota RAPID_FIRE:2) : le log ne pouvait plus porter qu'une seule valeur de
    `[RAPID FIRE:X]` pour trois armes, d'ou 898 faux « marker value mismatch » cote analyzer.

    Le PARAMETRE fait partie de la signature : RAPID_FIRE:1 et RAPID_FIRE:2 ne sont pas la meme
    regle appliquee. RNG et NB (A), eux, n'y sont PAS — 04.03 ne les liste pas parmi les
    caracteristiques d'identite, et les y mettre separerait des lots que la regle fusionne.
    """
    return frozenset(
        f"{name}:{param}" if param else name for name, param in _iter_weapon_rules(weapon)
    )


def weapon_rule_parameter(weapon: Dict[str, Any], rule_id: str) -> Optional[int]:
    """Valeur entiere du parametre d'une regle d'arme parametree (ex: RAPID_FIRE:X).

    Retourne None si l'arme ne declare PAS `rule_id`. Leve (aucun repli masquant) si la regle est
    presente mais son parametre est absent ou non entier. Miroir de l'extraction de
    `ai/analyzer_config.py` (RAPID_FIRE), mutualisee ici pour le chemin de resolution.
    """
    target = rule_id.strip().upper()
    for name, param in _iter_weapon_rules(weapon):
        if name != target:
            continue
        if not param:
            raise ValueError(f"Weapon rule {rule_id!r} present but missing parameter")
        try:
            return int(param)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid parameter for weapon rule {rule_id!r}: {param!r}") from exc
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
