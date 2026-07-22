"""
analyzer_config.py - Static configuration loaded once at analyzer startup.

load_analyzer_config() reads all unit/weapon/rule data from disk and returns
an AnalyzerConfig that handlers can use as a read-only context.
"""

import os
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.data_validation import require_key


@dataclass
class AnalyzerConfig:
    unit_registry: Any
    config_loader: Any
    unit_weapons_cache: Dict[str, List]
    unit_attack_limits: Dict[str, Dict]
    unit_combi_by_weapon: Dict[str, Dict]
    unit_rules_by_type: Dict[str, Set[str]]
    unit_move_after_shooting_distance_by_type: Dict[str, int]
    unit_is_fly_by_type: Dict[str, bool]
    unit_choice_effect_to_source_rules: Dict[str, Dict[str, Set[str]]]
    display_rule_name_to_ids: Dict[str, Set[str]]
    rule_to_units: Dict[str, Set[str]]
    weapon_rule_to_weapons: Dict[str, Set[str]]
    resolve_rule_id: Callable  # closure over all_unit_rules_config
    inches_to_subhex: int
    # Cartes GLOBALES arme→NB/portée, agrégées sur TOUS les model-types du registre.
    # Une escouade V11 est hétérogène (ex. "Boyz" contient Warboss/PainBoy/Nob...) ; l'arme
    # loguée peut appartenir à un model-type du squad et non à l'entrée unit_type. La
    # résolution per-unit-type échoue alors → on retombe sur ces cartes globales. En cas de
    # même nom d'arme avec NB différents entre model-types, on retient le MAX (plafond).
    rng_nb_by_weapon_global: Dict[str, int]
    cc_nb_by_weapon_global: Dict[str, int]
    rapid_fire_by_weapon_global: Dict[str, int]
    weapon_range_global: Dict[str, int]
    weapon_is_pistol_global: Dict[str, bool]


def load_analyzer_config() -> AnalyzerConfig:
    """Load all static unit/weapon/rule config from disk. Called once per parse run."""
    from ai.unit_registry import UnitRegistry
    from config_loader import get_config_loader
    from ai.analyzer import max_dice_value

    unit_registry = UnitRegistry()
    config_loader = get_config_loader()
    all_unit_rules_config = config_loader.load_unit_rules_config()
    inches_to_subhex: int = int(config_loader.get_board_config()["default"]["inches_to_subhex"])

    def resolve_effect_rule_id_to_technical(
        rule_id: str, visited: Optional[Set[str]] = None
    ) -> str:
        if not isinstance(rule_id, str) or not rule_id.strip():
            raise ValueError(f"Invalid rule id for analyzer resolution: {rule_id!r}")
        normalized_rule_id = rule_id.strip()
        if normalized_rule_id not in all_unit_rules_config:
            raise KeyError(
                f"Unknown rule id '{normalized_rule_id}' while resolving unit rules in analyzer"
            )
        if visited is None:
            visited = set()
        if normalized_rule_id in visited:
            raise ValueError(
                f"Rule alias cycle detected in config/unit_rules.json for '{normalized_rule_id}'"
            )
        visited.add(normalized_rule_id)
        rule_config = all_unit_rules_config[normalized_rule_id]
        alias = rule_config.get("alias")
        if alias is None:
            return normalized_rule_id
        if not isinstance(alias, str) or not alias.strip():
            raise ValueError(
                f"Rule '{normalized_rule_id}' has invalid alias in config/unit_rules.json: {alias!r}"
            )
        return resolve_effect_rule_id_to_technical(alias.strip(), visited)

    unit_weapons_cache: Dict[str, List] = {}
    unit_attack_limits: Dict[str, Dict] = {}
    unit_combi_by_weapon: Dict[str, Dict] = {}
    unit_rules_by_type: Dict[str, Set[str]] = {}
    unit_move_after_shooting_distance_by_type: Dict[str, int] = {}
    unit_is_fly_by_type: Dict[str, bool] = {}
    unit_choice_effect_to_source_rules: Dict[str, Dict[str, Set[str]]] = {}
    display_rule_name_to_ids: Dict[str, Set[str]] = {}

    for display_rule_id, rule_cfg in all_unit_rules_config.items():
        rule_name_raw = rule_cfg.get("name")
        if not isinstance(rule_name_raw, str) or not rule_name_raw.strip():
            continue
        normalized_rule_name = rule_name_raw.strip().upper()
        if normalized_rule_name not in display_rule_name_to_ids:
            display_rule_name_to_ids[normalized_rule_name] = set()
        display_rule_name_to_ids[normalized_rule_name].add(display_rule_id)

    for unit_type, unit_data in unit_registry.units.items():
        rng_weapons = require_key(unit_data, "RNG_WEAPONS")
        cc_weapons = require_key(unit_data, "CC_WEAPONS")
        unit_keywords = require_key(unit_data, "UNIT_KEYWORDS")
        unit_is_fly_by_type[unit_type] = any(
            str(require_key(keyword_entry, "keywordId")).strip().lower() == "fly"
            for keyword_entry in unit_keywords
        )
        rng_nb_by_weapon: Dict[str, int] = {}
        rapid_fire_by_weapon: Dict[str, int] = {}
        combi_by_weapon: Dict[str, str] = {}
        for weapon in rng_weapons:
            if isinstance(weapon, dict):
                weapon_name = require_key(weapon, "display_name")
                rng_nb_by_weapon[weapon_name] = max_dice_value(
                    require_key(weapon, "NB"),
                    "analyzer_rng_nb",
                )
                weapon_rules = require_key(weapon, "WEAPON_RULES")
                rapid_fire_value = 0
                for rule in weapon_rules:
                    if isinstance(rule, str) and rule.upper().startswith("RAPID_FIRE:"):
                        _, rf_raw = rule.split(":", 1)
                        try:
                            rapid_fire_value = int(rf_raw)
                        except (TypeError, ValueError) as exc:
                            raise ValueError(
                                f"Invalid RAPID_FIRE rule for {unit_type}/{weapon_name}: {rule}"
                            ) from exc
                        if rapid_fire_value <= 0:
                            raise ValueError(
                                f"RAPID_FIRE value must be > 0 for {unit_type}/{weapon_name}: {rapid_fire_value}"
                            )
                    elif hasattr(rule, "rule") and getattr(rule, "rule", None) == "RAPID_FIRE":
                        rf_raw = getattr(rule, "parameter", None)
                        if rf_raw is None:
                            raise ValueError(
                                f"RAPID_FIRE rule missing parameter for {unit_type}/{weapon_name}"
                            )
                        try:
                            rapid_fire_value = int(rf_raw)
                        except (TypeError, ValueError) as exc:
                            raise ValueError(
                                f"Invalid RAPID_FIRE parameter for {unit_type}/{weapon_name}: {rf_raw}"
                            ) from exc
                        if rapid_fire_value <= 0:
                            raise ValueError(
                                f"RAPID_FIRE value must be > 0 for {unit_type}/{weapon_name}: {rapid_fire_value}"
                            )
                rapid_fire_by_weapon[weapon_name] = rapid_fire_value
                combi_key = weapon.get("COMBI_WEAPON")
                if combi_key is not None:
                    combi_by_weapon[weapon_name] = combi_key
        cc_nb_by_weapon: Dict[str, int] = {}
        for weapon in cc_weapons:
            if isinstance(weapon, dict):
                weapon_name = require_key(weapon, "display_name")
                cc_nb_by_weapon[weapon_name] = max_dice_value(
                    require_key(weapon, "NB"),
                    "analyzer_cc_nb",
                )
        unit_attack_limits[unit_type] = {
            "rng_nb_by_weapon": rng_nb_by_weapon,
            "cc_nb_by_weapon": cc_nb_by_weapon,
            "rapid_fire_by_weapon": rapid_fire_by_weapon,
        }
        weapons_info: List[Dict] = []
        for weapon in rng_weapons:
            if isinstance(weapon, dict):
                weapon_rules = require_key(weapon, "WEAPON_RULES")
                weapons_info.append(
                    {
                        "name": require_key(weapon, "display_name"),
                        "range": require_key(weapon, "RNG") * inches_to_subhex,
                        "rules": weapon_rules,
                        "is_pistol": "PISTOL" in weapon_rules,
                    }
                )
        unit_weapons_cache[unit_type] = weapons_info
        unit_combi_by_weapon[unit_type] = combi_by_weapon
        unit_rules = require_key(unit_data, "UNIT_RULES")
        expanded_rule_ids: Set[str] = set()
        choice_effect_to_source_rules_for_unit: Dict[str, Set[str]] = {}
        for rule in unit_rules:
            direct_rule_id = require_key(rule, "ruleId")
            direct_rule_technical = resolve_effect_rule_id_to_technical(direct_rule_id)
            expanded_rule_ids.add(direct_rule_technical)
            if "grants_rule_ids" in rule:
                granted_rule_ids = rule["grants_rule_ids"]
            else:
                granted_rule_ids = []
            if not isinstance(granted_rule_ids, list):
                raise TypeError(
                    f"UNIT_RULES entry for '{direct_rule_id}' has invalid grants_rule_ids type: "
                    f"{type(granted_rule_ids).__name__}"
                )
            for granted_rule_id in granted_rule_ids:
                granted_rule_technical = resolve_effect_rule_id_to_technical(
                    str(granted_rule_id)
                )
                expanded_rule_ids.add(granted_rule_technical)
                if granted_rule_technical not in choice_effect_to_source_rules_for_unit:
                    choice_effect_to_source_rules_for_unit[granted_rule_technical] = set()
                choice_effect_to_source_rules_for_unit[granted_rule_technical].add(
                    direct_rule_id
                )
            rule_effect_ids = {
                direct_rule_technical,
                *[
                    resolve_effect_rule_id_to_technical(str(rid))
                    for rid in granted_rule_ids
                ],
            }
            if "move_after_shooting" in rule_effect_ids:
                rule_args = rule.get("rule_args")
                if not isinstance(rule_args, dict):
                    raise ValueError(
                        f"Unit '{unit_type}' rule '{direct_rule_id}' must define rule_args for move_after_shooting"
                    )
                if "distance" not in rule_args:
                    raise ValueError(
                        f"Unit '{unit_type}' rule '{direct_rule_id}' missing rule_args.distance for move_after_shooting"
                    )
                move_after_shooting_distance = rule_args["distance"]
                if not isinstance(move_after_shooting_distance, int):
                    raise TypeError(
                        f"Unit '{unit_type}' rule '{direct_rule_id}' rule_args.distance must be int, "
                        f"got {type(move_after_shooting_distance).__name__}"
                    )
                if move_after_shooting_distance <= 0:
                    raise ValueError(
                        f"Unit '{unit_type}' rule '{direct_rule_id}' rule_args.distance must be > 0, "
                        f"got {move_after_shooting_distance}"
                    )
                existing_distance = unit_move_after_shooting_distance_by_type.get(unit_type)
                if existing_distance is not None and existing_distance != move_after_shooting_distance:
                    raise ValueError(
                        f"Unit '{unit_type}' has conflicting move_after_shooting distances: "
                        f"{existing_distance} vs {move_after_shooting_distance}"
                    )
                unit_move_after_shooting_distance_by_type[unit_type] = move_after_shooting_distance * inches_to_subhex
        unit_rules_by_type[unit_type] = expanded_rule_ids
        unit_choice_effect_to_source_rules[unit_type] = choice_effect_to_source_rules_for_unit

    rule_to_units: Dict[str, Set[str]] = {}
    for ut, rules in unit_rules_by_type.items():
        for rid in rules:
            rule_to_units.setdefault(rid, set()).add(ut)

    weapon_rule_to_weapons: Dict[str, Set[str]] = {}
    for unit_type, weapons_list in unit_weapons_cache.items():
        for winfo in weapons_list:
            wname = require_key(winfo, "name")
            rules_list = require_key(winfo, "rules")
            weapon_key = f"{wname} ({unit_type})"
            for r in rules_list:
                rule_base = str(r).split(":")[0] if ":" in str(r) else str(r)
                weapon_rule_to_weapons.setdefault(rule_base, set()).add(weapon_key)

    # Cartes globales arme→NB/portée (agrégation MAX sur tous les model-types).
    rng_nb_by_weapon_global: Dict[str, int] = {}
    cc_nb_by_weapon_global: Dict[str, int] = {}
    rapid_fire_by_weapon_global: Dict[str, int] = {}
    weapon_range_global: Dict[str, int] = {}
    weapon_is_pistol_global: Dict[str, bool] = {}
    for _ut, _limits in unit_attack_limits.items():
        for _wname, _nb in _limits["rng_nb_by_weapon"].items():
            rng_nb_by_weapon_global[_wname] = max(rng_nb_by_weapon_global.get(_wname, 0), _nb)
        for _wname, _rf in _limits["rapid_fire_by_weapon"].items():
            rapid_fire_by_weapon_global[_wname] = max(rapid_fire_by_weapon_global.get(_wname, 0), _rf)
        for _wname, _nb in _limits["cc_nb_by_weapon"].items():
            cc_nb_by_weapon_global[_wname] = max(cc_nb_by_weapon_global.get(_wname, 0), _nb)
    for _ut, _winfos in unit_weapons_cache.items():
        for _winfo in _winfos:
            _wname = _winfo["name"]
            weapon_range_global[_wname] = max(weapon_range_global.get(_wname, 0), _winfo["range"])
            weapon_is_pistol_global[_wname] = weapon_is_pistol_global.get(_wname, False) or _winfo["is_pistol"]

    return AnalyzerConfig(
        unit_registry=unit_registry,
        config_loader=config_loader,
        unit_weapons_cache=unit_weapons_cache,
        unit_attack_limits=unit_attack_limits,
        unit_combi_by_weapon=unit_combi_by_weapon,
        unit_rules_by_type=unit_rules_by_type,
        unit_move_after_shooting_distance_by_type=unit_move_after_shooting_distance_by_type,
        unit_is_fly_by_type=unit_is_fly_by_type,
        unit_choice_effect_to_source_rules=unit_choice_effect_to_source_rules,
        display_rule_name_to_ids=display_rule_name_to_ids,
        rule_to_units=rule_to_units,
        weapon_rule_to_weapons=weapon_rule_to_weapons,
        resolve_rule_id=resolve_effect_rule_id_to_technical,
        inches_to_subhex=inches_to_subhex,
        rng_nb_by_weapon_global=rng_nb_by_weapon_global,
        cc_nb_by_weapon_global=cc_nb_by_weapon_global,
        rapid_fire_by_weapon_global=rapid_fire_by_weapon_global,
        weapon_range_global=weapon_range_global,
        weapon_is_pistol_global=weapon_is_pistol_global,
    )
