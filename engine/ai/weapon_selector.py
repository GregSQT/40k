"""
Weapon Selector - AI weapon selection based on kill probability

Doc : Documentation/Reference/jeu/Weapon_rules.md (section "Weapon Selection").

Le cache `game_state["kill_probability_cache"]` est rempli EXCLUSIVEMENT a la demande : un
miss recalcule et stocke (cf. select_best_*_weapon / get_best_weapon_for_target). Aucune
entree absente ne vaut 0.0 et aucune cible n'est ignoree — un miss coute du CPU, jamais une
decision faussee. Les pre-calculs de phase et le rechauffage post-mouvement ont ete supprimes
le 2026-07-27 : aucun appelant depuis le passage au remplissage paresseux, et le second
portait un `game_state.get("perception_radius", 25)` dont la cle n'etait ecrite nulle part
(valeur figee a 25 POUCES, comparee a une distance en sub-hex).
"""

from typing import Dict, Any, Tuple, Optional
from shared.data_validation import require_key
from engine.combat_utils import expected_dice_value
from engine.phase_handlers.shared_utils import require_hp_from_cache


def calculate_kill_probability(unit: Dict[str, Any], weapon: Dict[str, Any], 
                                target: Dict[str, Any], game_state: Dict[str, Any]) -> float:
    """
    Calculate kill probability for a specific weapon against a target.
    Simple, standalone function - pas de dépendance complexe.
    
    architecture_moteur.md COMPLIANCE: No defaults - raise error if required data missing.
    """
    # Extraire stats de l'arme - NO DEFAULT, raise error si manquant
    hit_target = require_key(weapon, "ATK")
    strength = require_key(weapon, "STR")
    damage = expected_dice_value(require_key(weapon, "DMG"), "kill_prob_damage")
    num_attacks = expected_dice_value(require_key(weapon, "NB"), "kill_prob_nb")
    ap = require_key(weapon, "AP")
    
    # Calculs W40K standard
    p_hit = max(0.0, min(1.0, (7 - hit_target) / 6.0))
    
    # Wound probability - NO DEFAULT, raise error si T manquant
    toughness = require_key(target, "T")
    if strength >= toughness * 2:
        p_wound = 5/6
    elif strength > toughness:
        p_wound = 4/6
    elif strength == toughness:
        p_wound = 3/6
    else:
        p_wound = 2/6
    
    # Save probability
    # ARMOR_SAVE et INVUL_SAVE peuvent être optionnels (certaines unités n'ont pas d'invul save)
    # Utiliser .get() avec default raisonnable pour ces champs optionnels
    armor_save = target.get("ARMOR_SAVE", 7)  # Default 7 = pas de save
    invul_save = target.get("INVUL_SAVE", 7)  # Default 7 = pas d'invul save
    save_target = min(armor_save - ap, invul_save)
    p_fail_save = max(0.0, min(1.0, (save_target - 1) / 6.0))
    
    # Expected damage
    p_damage_per_attack = p_hit * p_wound * p_fail_save
    expected_damage = num_attacks * p_damage_per_attack * damage
    
    # Kill probability - Phase 2: HP from require_hp_from_cache (target must be alive)
    hp_cur = require_hp_from_cache(str(target["id"]), game_state)
    if expected_damage >= hp_cur:
        return 1.0
    return min(1.0, expected_damage / hp_cur)


def _get_cache_key(unit_id: str, weapon_index: int, target_id: str, hp_cur: int) -> Tuple[str, int, str, int]:
    """Generate cache key for kill probability."""
    return (unit_id, weapon_index, target_id, hp_cur)


def _get_kill_prob_from_cache(cache: Dict[Tuple[str, int, str, int], float],
                               unit_id: str, weapon_index: int, target_id: str, hp_cur: int) -> Optional[float]:
    """Get kill probability from cache if available."""
    cache_key = _get_cache_key(unit_id, weapon_index, target_id, hp_cur)
    return cache.get(cache_key)


def _store_kill_prob_in_cache(cache: Dict[Tuple[str, int, str, int], float],
                               unit_id: str, weapon_index: int, target_id: str, hp_cur: int, kill_prob: float):
    """Store kill probability in cache."""
    cache_key = _get_cache_key(unit_id, weapon_index, target_id, hp_cur)
    cache[cache_key] = kill_prob


def select_best_ranged_weapon(unit: Dict[str, Any], target: Dict[str, Any], 
                               game_state: Dict[str, Any]) -> int:
    """
    Select best ranged weapon for target based on kill probability.
    
    Args:
        unit: Attacking unit with RNG_WEAPONS
        target: Target unit
        game_state: Game state (for cache access)
        
    Returns:
        Index of best weapon, or -1 if no weapons available
        
    Raises:
        KeyError: If RNG_WEAPONS missing or empty
    """
    if "RNG_WEAPONS" not in unit:
        raise KeyError(f"Unit missing RNG_WEAPONS: {unit}")
    
    rng_weapons = unit["RNG_WEAPONS"]
    if not rng_weapons:
        return -1

    # Get or create cache (lazy init so phase_start stays fast; avoids ~2.9s step spike)
    if "kill_probability_cache" not in game_state:
        game_state["kill_probability_cache"] = {}
    cache = game_state["kill_probability_cache"]

    best_index = -1
    best_kill_prob = -1.0

    unit_id = str(unit["id"])
    target_id = str(target["id"])
    hp_cur = require_hp_from_cache(target_id, game_state)

    for weapon_index, weapon in enumerate(rng_weapons):
        combi_key = weapon.get("COMBI_WEAPON")
        if combi_key:
            combi_choice = unit.get("_combi_weapon_choice")
            if combi_choice and combi_key in combi_choice and combi_choice[combi_key] != weapon_index:
                continue
        # Check cache first
        cached_prob = _get_kill_prob_from_cache(cache, unit_id, weapon_index, target_id, hp_cur)
        
        if cached_prob is not None:
            kill_prob = cached_prob
        else:
            # Calculate kill probability
            kill_prob = calculate_kill_probability(unit, weapon, target, game_state)
            # Store in cache
            _store_kill_prob_in_cache(cache, unit_id, weapon_index, target_id, hp_cur, kill_prob)
        
        # Tie-breaking: index le plus bas en cas d'égalité
        if kill_prob > best_kill_prob or (kill_prob == best_kill_prob and best_index == -1):
            best_kill_prob = kill_prob
            best_index = weapon_index
    
    return best_index


def select_best_melee_weapon(unit: Dict[str, Any], target: Dict[str, Any], 
                              game_state: Dict[str, Any]) -> int:
    """
    Select best melee weapon for target based on kill probability.
    
    Args:
        unit: Attacking unit with CC_WEAPONS
        target: Target unit
        game_state: Game state (for cache access)
        
    Returns:
        Index of best weapon, or -1 if no weapons available
        
    Raises:
        KeyError: If CC_WEAPONS missing or empty
    """
    if "CC_WEAPONS" not in unit:
        raise KeyError(f"Unit missing CC_WEAPONS: {unit}")
    
    cc_weapons = unit["CC_WEAPONS"]
    if not cc_weapons:
        return -1

    # Get or create cache (lazy init)
    if "kill_probability_cache" not in game_state:
        game_state["kill_probability_cache"] = {}
    cache = game_state["kill_probability_cache"]

    best_index = -1
    best_kill_prob = -1.0

    unit_id = str(unit["id"])
    target_id = str(target["id"])
    hp_cur = require_hp_from_cache(target_id, game_state)
    
    for weapon_index, weapon in enumerate(cc_weapons):
        # Check cache first
        cached_prob = _get_kill_prob_from_cache(cache, unit_id, weapon_index, target_id, hp_cur)
        
        if cached_prob is not None:
            kill_prob = cached_prob
        else:
            # Calculate kill probability
            kill_prob = calculate_kill_probability(unit, weapon, target, game_state)
            # Store in cache
            _store_kill_prob_in_cache(cache, unit_id, weapon_index, target_id, hp_cur, kill_prob)
        
        # Tie-breaking: index le plus bas en cas d'égalité
        if kill_prob > best_kill_prob or (kill_prob == best_kill_prob and best_index == -1):
            best_kill_prob = kill_prob
            best_index = weapon_index
    
    return best_index


def get_best_weapon_for_target(unit: Dict[str, Any], target: Dict[str, Any], 
                                game_state: Dict[str, Any], is_ranged: bool) -> Tuple[int, float]:
    """
    Get best weapon for target and its kill probability.
    Used for observation space.
    
    Args:
        unit: Attacking unit
        target: Target unit
        game_state: Game state (for cache access)
        is_ranged: True for ranged weapons, False for melee
        
    Returns:
        Tuple of (weapon_index, kill_probability)
        Returns (-1, 0.0) if no weapons available
    """
    if is_ranged:
        weapon_index = select_best_ranged_weapon(unit, target, game_state)
    else:
        weapon_index = select_best_melee_weapon(unit, target, game_state)
    
    if weapon_index < 0:
        return (-1, 0.0)

    # Get or create cache (lazy init)
    if "kill_probability_cache" not in game_state:
        game_state["kill_probability_cache"] = {}
    cache = game_state["kill_probability_cache"]
    unit_id = str(unit["id"])
    target_id = str(target["id"])
    hp_cur = require_hp_from_cache(target_id, game_state)
    
    if is_ranged:
        weapons = require_key(unit, "RNG_WEAPONS")
    else:
        weapons = require_key(unit, "CC_WEAPONS")
    
    if weapon_index >= len(weapons):
        return (-1, 0.0)
    
    weapon = weapons[weapon_index]
    
    # Check cache first
    cached_prob = _get_kill_prob_from_cache(cache, unit_id, weapon_index, target_id, hp_cur)
    if cached_prob is not None:
        return (weapon_index, cached_prob)
    
    # Calculate if not in cache
    kill_prob = calculate_kill_probability(unit, weapon, target, game_state)
    _store_kill_prob_in_cache(cache, unit_id, weapon_index, target_id, hp_cur, kill_prob)
    
    return (weapon_index, kill_prob)


def invalidate_cache_for_target(cache: Dict[Tuple[str, int, str, int], float], target_id: str):
    """
    Invalidate all cache entries for a specific target.

    Appelants reels : `_fight_on_target_damaged` (fight_handlers) uniquement. La phase de tir
    n'invalide pas — inutile pour la correction : la cle de cache embarque `hp_cur`, donc une
    entree perimee n'est jamais relue apres une blessure. C'est du menage memoire, pas un
    correctif. Cf. Documentation/Reference/jeu/Weapon_rules.md (cache rempli a la demande, jamais pre-calcule).

    Args:
        cache: Kill probability cache
        target_id: ID of target unit (as string)
    """
    keys_to_remove = [key for key in cache.keys() if key[2] == target_id]
    for key in keys_to_remove:
        del cache[key]


def invalidate_cache_for_unit(cache: Dict[Tuple[str, int, str, int], float], unit_id: str):
    """
    Invalidate all cache entries for a specific unit (unit died, can't attack anymore).

    Appelant reel : `_fight_on_unit_destroyed` (fight_handlers) uniquement.

    Args:
        cache: Kill probability cache
        unit_id: ID of unit (as string)
    """
    keys_to_remove = [key for key in cache.keys() if key[0] == unit_id]
    for key in keys_to_remove:
        del cache[key]
