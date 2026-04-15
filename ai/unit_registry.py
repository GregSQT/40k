# ai/unit_registry.py
#!/usr/bin/env python3
"""
Dynamic Unit Registry System
Auto-discovers all units from TypeScript files and extracts faction-role combinations
Zero hardcoding - supports unlimited factions and units
"""

import os
import re
import json
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
import sys
from shared.data_validation import require_key, require_present

class UnitRegistry:
    """Dynamic unit discovery and faction-role management system."""
    CORE_AGENT_KEY = "CoreAgent"
    
    def __init__(self, project_root: str = None):
        if project_root is None:
            # Auto-detect project root from current file location
            self.project_root = Path(__file__).parent.parent
        else:
            self.project_root = Path(project_root)
            
        self.frontend_src = self.project_root / "frontend" / "src"
        self.roster_dir = self.frontend_src / "roster"
        
        # Core data structures
        self.units: Dict[str, Dict] = {}
        self.factions: Set[str] = set()
        self.roles: Set[str] = set()
        self.faction_role_combinations: Set[Tuple[str, str]] = set()
        self.faction_role_matrix: Dict[str, List[str]] = {}
        self._unit_rules = self._load_unit_rules()
        
        # Initialize the registry
        self._discover_all_units(verbose=False)
        self._build_faction_role_matrix()

    def _load_unit_rules(self) -> Dict[str, Dict]:
        """Load unit rules config for validation."""
        from config_loader import get_config_loader
        config_loader = get_config_loader()
        return config_loader.load_unit_rules_config()
    
    def _discover_all_units(self, verbose: bool = False):
        """Scan TypeScript files and extract all unit definitions dynamically."""
        if not self.roster_dir.exists():
            raise FileNotFoundError(f"Roster directory not found: {self.roster_dir}")
        
        unit_count = 0
        faction_units = {}
        
        # Scan all faction directories
        for faction_dir in self.roster_dir.iterdir():
            if faction_dir.is_dir() and not faction_dir.name.startswith('.'):
                faction_name = faction_dir.name
                faction_units[faction_name] = []
                
                # Scan TypeScript files in the units subfolder only
                units_dir = faction_dir / "units"
                if units_dir.exists():
                    for ts_file in units_dir.rglob("*.ts"):
                        if ts_file.name.startswith('index'):
                            continue  # Skip index files
                        
                        unit_data = self._parse_unit_file(ts_file, faction_name)
                        if unit_data:
                            self.units[unit_data['unit_type']] = unit_data
                            self.factions.add(unit_data['faction'])
                            self.roles.add(unit_data['role'])
                            self.faction_role_combinations.add((unit_data['faction'], unit_data['role']))
                            faction_units[faction_name].append(f"{unit_data['unit_type']} ({unit_data['role']})")
                            unit_count += 1
        
        # Streamlined single-line summary
        faction_summary = []
        for faction, units in faction_units.items():
            if units:
                faction_summary.append(f"{faction}({len(units)})")
        
        # print(f"🔍 Units discovered: {unit_count} total | {' | '.join(faction_summary)}")
        
        if verbose:
            print(f"🎯 Faction-Role combinations: {sorted(self.faction_role_combinations)}")
    
    def _parse_unit_file(self, ts_file: Path, faction_name: str) -> Dict:
        """Parse a TypeScript unit file and extract all unit data."""
        try:
            with open(ts_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Extract class name
            class_match = re.search(r'export class (\w+)', content)
            if not class_match:
                return None
            
            unit_type = class_match.group(1)
            
            # Extract base class to determine faction and role
            base_class_match = re.search(r'extends (\w+)', content)
            if not base_class_match:
                print(f"    ⚠️ No base class found for {unit_type}")
                return None
            
            base_class = base_class_match.group(1)
            faction, role = self._extract_faction_role_from_base_class(base_class, faction_name)
            
            # Extract all static properties dynamically
            unit_data = {
                'unit_type': unit_type,
                'faction': faction,
                'role': role,
                'base_class': base_class,
                'file_path': str(ts_file)
            }
            
            # Extract static numeric properties and weapons
            static_props = self._extract_static_properties(content, faction_name, ts_file)
            unit_data.update(static_props)
            
            # Validate essential properties
            required_props = ['HP_MAX', 'MOVE']
            for prop in required_props:
                if prop not in unit_data:
                    print(f"    ⚠️ Missing {prop} for {unit_type}")
                    return None
            
            # Validate at least one weapon type exists
            rng_weapons = require_key(unit_data, "RNG_WEAPONS")
            cc_weapons = require_key(unit_data, "CC_WEAPONS")
            if (not rng_weapons or len(rng_weapons) == 0) and (not cc_weapons or len(cc_weapons) == 0):
                print(f"    ⚠️ Unit {unit_type} must have at least RNG_WEAPONS or CC_WEAPONS")
                return None
            
            return unit_data
            
        except Exception as e:
            print(f"    ❌ Error parsing {ts_file}: {e}")
            return None
    
    def _extract_faction_role_from_base_class(self, base_class: str, faction_dir_name: str) -> Tuple[str, str]:
        """Extract faction and role from base class name."""
        # Handle different naming patterns
        if 'Melee' in base_class:
            role = 'Melee'
        elif 'Ranged' in base_class or 'Range' in base_class:
            # Support both legacy "...Ranged..." and current "...Range..." class naming.
            role = 'Ranged'
        elif 'Support' in base_class:
            role = 'Support'
        else:
            role = 'Unknown'
        
        # Extract faction from base class name
        # Handle both 4-part and 2-part base class naming patterns
        # 4-part: TroopRangeSwarm -> SpaceMarine
        # 2-part: SpaceMarineMeleeUnit -> SpaceMarine
        if base_class.startswith('SpaceMarine'):
            faction = 'SpaceMarine'
        elif base_class.startswith('Tyranid'):
            faction = 'Tyranid'
        else:
            # Legacy pattern matching for 2-part base classes
            faction_match = re.match(r'(\w+?)(Melee|Ranged|Support)Unit', base_class)
            if faction_match:
                faction = faction_match.group(1)
            else:
                # Use directory name when base class doesn't encode faction
                require_present(faction_dir_name, "faction_dir_name")
                if not faction_dir_name.strip():
                    raise ValueError("faction_dir_name must be a non-empty string")
                faction = faction_dir_name.title()
        
        return faction, role
    
    def _extract_static_properties(self, content: str, faction_name: str, ts_file: Path | None = None) -> Dict:
        """Extract all static properties from TypeScript class, including weapons."""
        properties = {}

        def _extract_top_level_object_bodies(block: str) -> List[str]:
            """Extract top-level object bodies from a JS/TS array literal body."""
            object_bodies: List[str] = []
            depth = 0
            object_start = -1
            in_string = False
            string_delimiter = ""
            escape_next = False
            for idx, ch in enumerate(block):
                if escape_next:
                    escape_next = False
                    continue
                if in_string:
                    if ch == "\\":
                        escape_next = True
                        continue
                    if ch == string_delimiter:
                        in_string = False
                    continue
                if ch in {"'", '"'}:
                    in_string = True
                    string_delimiter = ch
                    continue
                if ch == "{":
                    if depth == 0:
                        object_start = idx + 1
                    depth += 1
                    continue
                if ch == "}":
                    if depth <= 0:
                        raise ValueError("Unbalanced braces in UNIT_RULES declaration")
                    depth -= 1
                    if depth == 0:
                        object_bodies.append(block[object_start:idx])
                        object_start = -1
            if depth != 0:
                raise ValueError("Unbalanced braces in UNIT_RULES declaration")
            return object_bodies
        
        # Try to import get_weapons, but continue if it fails (standalone mode)
        try:
            from engine.weapons import get_weapons
            weapons_available = True
        except ImportError:
            weapons_available = False
        
        # Pattern 1: UNIT_RULES (optional)
        unit_rules_match = re.search(
            r'static\s+UNIT_RULES(?:\s*:\s*[^=]+)?\s*=\s*\[([\s\S]*?)\]\s*;',
            content,
            re.MULTILINE
        )
        if unit_rules_match:
            rules_block = unit_rules_match.group(1).strip()
            unit_rules = []
            if rules_block:
                rule_objects = _extract_top_level_object_bodies(rules_block)
                if not rule_objects:
                    raise ValueError("UNIT_RULES must contain objects with ruleId and displayName")
            else:
                rule_objects = []

            for rule_object in rule_objects:
                rule_id_match = re.search(r'ruleId\s*:\s*["\']([^"\']+)["\']', rule_object)
                display_name_match = re.search(r'displayName\s*:\s*["\']([^"\']+)["\']', rule_object)
                if not rule_id_match or not display_name_match:
                    raise ValueError("UNIT_RULES must contain objects with ruleId and displayName")

                rule_id = rule_id_match.group(1)
                display_name = display_name_match.group(1)
                if rule_id not in self._unit_rules:
                    raise KeyError(f"Unknown unit rule id '{rule_id}' (missing in config/unit_rules.json)")
                if not display_name or not display_name.strip():
                    raise ValueError(f"Unit rule '{rule_id}' missing displayName")

                grants_rule_ids_match = re.search(r'grants_rule_ids\s*:\s*\[([^\]]*)\]', rule_object)
                grants_rule_ids = []
                if grants_rule_ids_match:
                    grants_raw = grants_rule_ids_match.group(1).strip()
                    if grants_raw:
                        grants_rule_ids = re.findall(r'["\']([^"\']+)["\']', grants_raw)
                    for granted_rule_id in grants_rule_ids:
                        if granted_rule_id not in self._unit_rules:
                            raise KeyError(
                                f"Unknown granted unit rule id '{granted_rule_id}' "
                                f"(missing in config/unit_rules.json)"
                            )

                usage_match = re.search(r'usage\s*:\s*["\']([^"\']+)["\']', rule_object)
                usage_value = None
                if usage_match:
                    usage_value = usage_match.group(1).strip().lower()
                    if usage_value not in {"and", "or", "unique", "always"}:
                        raise ValueError(
                            f"Invalid usage '{usage_value}' in UNIT_RULES for '{rule_id}'. "
                            "Allowed values: and, or, unique, always"
                        )

                choice_timing_match = re.search(r'choice_timing\s*:\s*\{([\s\S]*?)\}', rule_object)
                choice_timing_value = None
                if choice_timing_match:
                    choice_timing_block = choice_timing_match.group(1)
                    trigger_match = re.search(r'trigger\s*:\s*["\']([^"\']+)["\']', choice_timing_block)
                    if not trigger_match:
                        raise ValueError(
                            f"UNIT_RULES choice_timing for '{rule_id}' must define trigger"
                        )
                    trigger_value = trigger_match.group(1).strip()
                    allowed_triggers = {
                        "on_deploy",
                        "turn_start",
                        "player_turn_start",
                        "phase_start",
                        "activation_start",
                    }
                    if trigger_value not in allowed_triggers:
                        raise ValueError(
                            f"Invalid choice_timing.trigger '{trigger_value}' for '{rule_id}'. "
                            f"Allowed values: {sorted(allowed_triggers)}"
                        )
                    choice_timing_value = {"trigger": trigger_value}

                    phase_match = re.search(r'phase\s*:\s*["\']([^"\']+)["\']', choice_timing_block)
                    if phase_match:
                        phase_value = phase_match.group(1).strip()
                        allowed_phases = {"command", "move", "shoot", "charge", "fight"}
                        if phase_value not in allowed_phases:
                            raise ValueError(
                                f"Invalid choice_timing.phase '{phase_value}' for '{rule_id}'. "
                                f"Allowed values: {sorted(allowed_phases)}"
                            )
                        choice_timing_value["phase"] = phase_value

                    active_player_scope_match = re.search(
                        r'active_player_scope\s*:\s*["\']([^"\']+)["\']', choice_timing_block
                    )
                    if active_player_scope_match:
                        active_player_scope_value = active_player_scope_match.group(1).strip()
                        allowed_active_player_scope = {"owner", "opponent", "both"}
                        if active_player_scope_value not in allowed_active_player_scope:
                            raise ValueError(
                                f"Invalid choice_timing.active_player_scope '{active_player_scope_value}' for '{rule_id}'. "
                                f"Allowed values: {sorted(allowed_active_player_scope)}"
                            )
                        choice_timing_value["active_player_scope"] = active_player_scope_value

                    if trigger_value in {"phase_start", "activation_start"} and "phase" not in choice_timing_value:
                        raise ValueError(
                            f"choice_timing.phase is required for trigger '{trigger_value}' in rule '{rule_id}'"
                        )
                    if trigger_value == "phase_start" and "active_player_scope" not in choice_timing_value:
                        raise ValueError(
                            f"choice_timing.active_player_scope is required for trigger '{trigger_value}' in rule '{rule_id}'"
                        )

                rule_args_match = re.search(r'rule_args\s*:\s*\{([\s\S]*?)\}', rule_object)
                rule_args_value = None
                if rule_args_match:
                    rule_args_block = rule_args_match.group(1)
                    parsed_rule_args = {}
                    for arg_match in re.finditer(
                        r'([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(-?\d+)',
                        rule_args_block,
                    ):
                        arg_key = arg_match.group(1)
                        arg_value = int(arg_match.group(2))
                        parsed_rule_args[arg_key] = arg_value
                    if not parsed_rule_args:
                        raise ValueError(
                            f"Invalid rule_args for '{rule_id}': expected at least one numeric key:value pair"
                        )
                    rule_args_value = parsed_rule_args

                unit_rule_entry = {
                    "ruleId": rule_id,
                    "displayName": display_name,
                    "grants_rule_ids": grants_rule_ids,
                }
                if usage_value is not None:
                    unit_rule_entry["usage"] = usage_value
                if choice_timing_value is not None:
                    unit_rule_entry["choice_timing"] = choice_timing_value
                if rule_args_value is not None:
                    unit_rule_entry["rule_args"] = rule_args_value
                unit_rules.append(unit_rule_entry)
            properties["UNIT_RULES"] = unit_rules
        else:
            properties["UNIT_RULES"] = []

        # Pattern 1b: UNIT_KEYWORDS (optional)
        unit_keywords_match = re.search(
            r'static\s+UNIT_KEYWORDS(?:\s*:\s*[^=]+)?\s*=\s*\[([\s\S]*?)\]\s*;',
            content,
            re.MULTILINE
        )
        if unit_keywords_match:
            keywords_block = unit_keywords_match.group(1).strip()
            unit_keywords = []
            if keywords_block:
                keyword_objects = re.findall(r'\{([\s\S]*?)\}', keywords_block)
            else:
                keyword_objects = []

            for keyword_object in keyword_objects:
                keyword_id_match = re.search(r'keywordId\s*:\s*["\']([^"\']+)["\']', keyword_object)
                if not keyword_id_match:
                    raise ValueError("UNIT_KEYWORDS must contain objects with keywordId")
                keyword_id = keyword_id_match.group(1)
                if not keyword_id or not keyword_id.strip():
                    raise ValueError("UNIT_KEYWORDS keywordId cannot be empty")
                unit_keywords.append({"keywordId": keyword_id})
            properties["UNIT_KEYWORDS"] = unit_keywords
        else:
            properties["UNIT_KEYWORDS"] = []

        # Pattern 2: Static properties simples (HP_MAX, MOVE, etc.)
        static_pattern = r'static\s+([A-Z_]+)\s*=\s*([^;]+);'
        matches = re.findall(static_pattern, content)
        
        for prop_name, prop_value in matches:
            # Skip RNG_WEAPONS/CC_WEAPONS, UNIT_RULES, UNIT_KEYWORDS (handled separately)
            if prop_name in ["RNG_WEAPONS", "CC_WEAPONS", "UNIT_RULES", "UNIT_KEYWORDS"]:
                continue
            
            # Clean up the value
            prop_value = prop_value.strip().strip('"\'')
            # Remove comments (everything after // or #)
            if '//' in prop_value:
                prop_value = prop_value.split('//')[0].strip()
            if '#' in prop_value:
                prop_value = prop_value.split('#')[0].strip()
            
            # Try to convert to appropriate type
            if prop_value.startswith('[') and prop_value.endswith(']'):
                try:
                    properties[prop_name] = json.loads(prop_value)
                except json.JSONDecodeError:
                    properties[prop_name] = prop_value
            elif prop_value.isdigit() or (prop_value.startswith('-') and prop_value[1:].isdigit()):
                properties[prop_name] = int(prop_value)
            elif prop_value.replace('.', '').isdigit():
                properties[prop_name] = float(prop_value)
            else:
                properties[prop_name] = prop_value
        
        # Pattern 3: RNG_WEAPON_CODES = ["code1", "code2"] ou [] (robuste)
        # Only process weapons if import succeeded
        if not weapons_available:
            raise ImportError("engine.weapons.get_weapons is required to load RNG_WEAPONS/CC_WEAPONS")
        
        rng_codes_match = re.search(
            r'static\s+RNG_WEAPON_CODES(?:\s*:\s*[^=]+)?\s*=\s*\[([^\]]*)\];',
            content,
            re.MULTILINE | re.DOTALL  # Support multi-lignes
        )
        if not rng_codes_match:
            raise ValueError("Unit definition missing required RNG_WEAPON_CODES (use [] if none)")
        codes_str = rng_codes_match.group(1).strip()
        if codes_str:
            # Gérer guillemets simples ET doubles
            codes = re.findall(r'["\']([^"\']+)["\']', codes_str)
        else:
            codes = []  # Array vide
        
        # Détection faction robuste avec faction_name (pas path)
        # faction_name est le nom du répertoire (ex: "spaceMarine" ou "tyranid")
        # Normalize faction name for armory parser (spaceMarine -> SpaceMarine)
        if faction_name.lower() in ['spacemarine', 'spacemarines']:
            faction = 'SpaceMarine'
        elif faction_name.lower() == 'tyranid':
            faction = 'Tyranid'
        else:
            faction = faction_name
        
        rng_codes = list(codes)
        properties["RNG_WEAPONS"] = get_weapons(faction, rng_codes)
        
        # Pattern 4: CC_WEAPON_CODES (même logique)
        cc_codes_match = re.search(
            r'static\s+CC_WEAPON_CODES(?:\s*:\s*[^=]+)?\s*=\s*\[([^\]]*)\];',
            content,
            re.MULTILINE | re.DOTALL
        )
        if not cc_codes_match:
            raise ValueError("Unit definition missing required CC_WEAPON_CODES (use [] if none)")
        codes_str = cc_codes_match.group(1).strip()
        if codes_str:
            codes = re.findall(r'["\']([^"\']+)["\']', codes_str)
        else:
            codes = []
        
        # Normalize faction name for armory parser (spaceMarine -> SpaceMarine)
        if faction_name.lower() in ['spacemarine', 'spacemarines']:
            faction = 'SpaceMarine'
        elif faction_name.lower() == 'tyranid':
            faction = 'Tyranid'
        else:
            faction = faction_name
        
        cc_codes = list(codes)
        properties["CC_WEAPONS"] = get_weapons(faction, cc_codes)

        # Endless Duty: override default weapon codes from evolution starter loadout config.
        if ts_file is not None and "endlessDuty" in str(ts_file):
            ed_override = self._resolve_endless_duty_starter_loadout(
                ts_file=ts_file,
                content=content,
                faction=faction,
                get_weapons_fn=get_weapons,
            )
            if ed_override is not None:
                override_rng_codes = require_key(ed_override, "rng_codes")
                override_cc_codes = require_key(ed_override, "cc_codes")
                properties["RNG_WEAPONS"] = get_weapons(faction, override_rng_codes)
                properties["CC_WEAPONS"] = get_weapons(faction, override_cc_codes)
                properties["VALUE"] = require_key(ed_override, "value")
        
        # Normalize output: both keys must exist (validated above)
        
        # Initialiser selectedWeaponIndex
        rng_weapons = require_key(properties, "RNG_WEAPONS")
        if rng_weapons:
            properties["selectedRngWeaponIndex"] = 0
        cc_weapons = require_key(properties, "CC_WEAPONS")
        if cc_weapons:
            properties["selectedCcWeaponIndex"] = 0
        
        return properties

    def _resolve_endless_duty_starter_loadout(
        self,
        ts_file: Path,
        content: str,
        faction: str,
        get_weapons_fn: Any,
    ) -> Dict[str, Any] | None:
        """Resolve ED starter loadout weapon codes from config/endless_duty/*.json."""
        if faction != "SpaceMarine":
            return None

        class_match = re.search(r'export class (\w+)', content)
        if not class_match:
            raise ValueError(f"Cannot parse class name for ED unit file: {ts_file}")
        class_name = class_match.group(1)

        starter_match = re.search(
            r'static\s+STARTER_LOADOUT_ID(?:\s*:\s*[^=]+)?\s*=\s*["\']([^"\']+)["\']\s*;',
            content,
        )
        if not starter_match:
            raise ValueError(f"ED unit class {class_name} is missing required static STARTER_LOADOUT_ID")
        starter_loadout_id = starter_match.group(1)

        def _extract_static_string(prop_name: str) -> str | None:
            match = re.search(
                rf'static\s+{prop_name}(?:\s*:\s*[^=]+)?\s*=\s*["\']([^"\']+)["\']\s*;',
                content,
            )
            return match.group(1) if match else None

        evolution_filename = _extract_static_string("EVOLUTION_FILE")
        profile_name = _extract_static_string("PROFILE_NAME")

        if evolution_filename is None:
            if class_name.startswith("Leader"):
                evolution_filename = "leader_evolution.json"
            elif class_name.startswith("Melee"):
                evolution_filename = "melee_evolution.json"
            elif class_name.startswith("Range"):
                evolution_filename = "range_evolution.json"
            else:
                raise ValueError(
                    f"Cannot infer EVOLUTION_FILE for ED class {class_name}. "
                    "Add static EVOLUTION_FILE."
                )

        if profile_name is None:
            for prefix in ("Leader", "Melee", "Range"):
                if class_name.startswith(prefix):
                    profile_name = class_name[len(prefix):]
                    break
            if profile_name is None:
                raise ValueError(
                    f"Cannot infer PROFILE_NAME for ED class {class_name}. "
                    "Add static PROFILE_NAME."
                )
            if profile_name.endswith("Ed"):
                profile_name = profile_name[:-2]
            if not profile_name:
                raise ValueError(f"Cannot derive ED profile name from class {class_name}")

        evolution_path = self.project_root / "config" / "endless_duty" / evolution_filename
        if not evolution_path.exists():
            raise FileNotFoundError(f"Missing ED evolution config: {evolution_path}")

        with open(evolution_path, "r", encoding="utf-8-sig") as f:
            evolution = json.load(f)

        loadouts = require_key(evolution, "loadouts")
        if not isinstance(loadouts, list):
            raise ValueError(f"{evolution_filename} field 'loadouts' must be a list")

        selected_loadout = None
        for loadout in loadouts:
            if not isinstance(loadout, dict):
                continue
            if str(loadout.get("id")) == starter_loadout_id:
                selected_loadout = loadout
                break
        if selected_loadout is None:
            raise KeyError(
                f"starter_loadout_id '{starter_loadout_id}' not found in {evolution_path}"
            )

        loadout_profile = require_key(selected_loadout, "profile")
        if str(loadout_profile) != profile_name:
            raise ValueError(
                f"ED starter profile mismatch for {class_name}: "
                f"class profile '{profile_name}' != loadout profile '{loadout_profile}'"
            )

        picks = require_key(selected_loadout, "picks")
        if not isinstance(picks, dict):
            raise ValueError(f"Loadout '{starter_loadout_id}' field 'picks' must be an object")

        catalog = require_key(evolution, "catalog")
        profile_catalog = require_key(catalog, profile_name)
        base_value = require_key(profile_catalog, "base")
        if not isinstance(base_value, (int, float)):
            raise ValueError(
                f"Catalog profile '{profile_name}' in {evolution_filename} must define numeric field 'base'"
            )
        rows = require_key(profile_catalog, "rows")
        packages = require_key(profile_catalog, "packages")
        if not isinstance(rows, list) or not isinstance(packages, list):
            raise ValueError(f"Catalog profile '{profile_name}' must define list fields rows/packages")

        ranged_codes: List[str] = []
        melee_codes: List[str] = []
        starter_total_cost = float(base_value)

        def _append_row_pick(slot_name: str, pick_id: str) -> None:
            nonlocal starter_total_cost
            row_match = None
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if str(row.get("slot")) == slot_name and str(row.get("pick")) == pick_id:
                    row_match = row
                    break
            if row_match is None:
                raise KeyError(
                    f"Loadout '{starter_loadout_id}' references unknown row pick "
                    f"slot='{slot_name}' pick='{pick_id}' for profile '{profile_name}'"
                )
            row_cost = require_key(row_match, "cost")
            if not isinstance(row_cost, (int, float)):
                raise ValueError(
                    f"Loadout row '{pick_id}' in profile '{profile_name}' must define numeric field 'cost'"
                )
            starter_total_cost += float(row_cost)
            includes = row_match.get("includes")
            target_list = ranged_codes if slot_name in ("ranged", "secondary") else melee_codes
            if includes is not None:
                if not isinstance(includes, list):
                    raise ValueError(
                        f"Loadout '{starter_loadout_id}' row '{pick_id}' has non-list includes"
                    )
                for weapon_code in includes:
                    target_list.append(str(weapon_code))
            else:
                target_list.append(pick_id)

        for slot_key in ("melee", "ranged", "secondary"):
            pick_val = picks.get(slot_key)
            if pick_val is None:
                continue
            if str(pick_val) == "none":
                continue
            _append_row_pick(slot_key, str(pick_val))

        package_id = picks.get("package")
        if package_id is not None:
            package_match = None
            for package in packages:
                if not isinstance(package, dict):
                    continue
                if str(package.get("id")) == str(package_id):
                    package_match = package
                    break
            if package_match is None:
                raise KeyError(
                    f"Loadout '{starter_loadout_id}' references unknown package '{package_id}' "
                    f"for profile '{profile_name}'"
                )
            package_cost = require_key(package_match, "cost")
            if not isinstance(package_cost, (int, float)):
                raise ValueError(
                    f"Package '{package_id}' in profile '{profile_name}' must define numeric field 'cost'"
                )
            starter_total_cost += float(package_cost)
            package_picks = require_key(package_match, "picks")
            if not isinstance(package_picks, list):
                raise ValueError(
                    f"Package '{package_id}' in profile '{profile_name}' must have list field 'picks'"
                )
            for package_pick in package_picks:
                if not isinstance(package_pick, dict):
                    continue
                pick_id = str(require_key(package_pick, "id"))
                pick_kind = str(require_key(package_pick, "kind"))
                if pick_kind != "weapon":
                    continue
                weapon_def = get_weapons_fn(faction, [pick_id])[0]
                if "RNG" in weapon_def:
                    ranged_codes.append(pick_id)
                else:
                    melee_codes.append(pick_id)

        return {
            "rng_codes": ranged_codes,
            "cc_codes": melee_codes,
            "value": int(starter_total_cost),
        }
    
    def _build_faction_role_matrix(self):
        """Build the faction-role matrix with custom agent mappings."""
        # Initialize faction containers
        for faction in self.factions:
            self.faction_role_matrix[faction] = []

        # Current project mode: single shared agent for all units.
        for unit_type, unit_data in self.units.items():
            agent_key = self.CORE_AGENT_KEY

            # Add to matrix
            if agent_key not in self.faction_role_matrix:
                self.faction_role_matrix[agent_key] = []

            self.faction_role_matrix[agent_key].append(unit_type)
    
    def _generate_advanced_agent_key(self, unit_type: str, unit_data: Dict) -> str:
        """Legacy helper kept for compatibility; single-agent mode always uses CoreAgent."""
        _ = unit_type, unit_data
        return self.CORE_AGENT_KEY
    
    def _determine_move_type(self, unit_type: str, unit_data: Dict) -> str:
        """Determine movement type based on unit characteristics."""
        # Check for vehicle keywords
        if any(keyword in unit_type.lower() for keyword in ['tank', 'predator', 'rhino', 'vehicle']):
            return "Vehicle"
        
        # Check for jump/fly keywords
        if any(keyword in unit_type.lower() for keyword in ['jump', 'fly', 'assault']):
            # For now, Assault units are still Infantry until we add actual jump pack units
            return "Infantry"
        
        # Check for bike keywords
        if any(keyword in unit_type.lower() for keyword in ['bike', 'speeder']):
            return "Bike"
        
        # Default to Infantry for current units
        return "Infantry"
    
    def _get_tanking_level(self, unit_type: str, unit_data: Dict) -> str:
        """Infer tanking level from defensive stats, no static class label dependency."""
        _ = unit_type
        hp_max = int(require_key(unit_data, "HP_MAX"))
        armor_save = int(require_key(unit_data, "ARMOR_SAVE"))
        if hp_max <= 1:
            return "Swarm"
        if hp_max <= 3 and armor_save >= 4:
            return "Troop"
        return "Elite"

    def _get_move_type(self, unit_type: str, unit_data: Dict) -> str:
        """Infer movement type from keywords/name, no static class label dependency."""
        _ = unit_data
        return self._determine_move_type(unit_type, {})
    
    def _get_attack_target(self, unit_type: str, unit_data: Dict, role: str) -> str:
        """Return generic dynamic target label; static target archetypes are deprecated."""
        _ = unit_type, unit_data
        return f"{role}Dynamic"
    
    def get_model_key(self, unit_type: str) -> str:
        """Get the model key for a given unit type (single-agent mode)."""
        if unit_type not in self.units:
            raise ValueError(f"Unknown unit type: {unit_type}")

        return self.CORE_AGENT_KEY
    
    def get_required_models(self) -> List[str]:
        """Get list of required model keys (single-agent mode)."""
        return [self.CORE_AGENT_KEY]
    
    def get_all_model_keys(self) -> List[str]:
        """Get all available model keys (alias for get_required_models)."""
        return self.get_required_models()
    
    def get_units_for_model(self, model_key: str) -> List[str]:
        """Get list of unit types that use a specific model."""
        return require_key(self.faction_role_matrix, model_key)
    
    def get_unit_data(self, unit_type: str) -> Dict:
        """Get complete data for a unit type."""
        if unit_type not in self.units:
            raise ValueError(f"Unknown unit type: {unit_type}")
        return self.units[unit_type].copy()
    
    def get_faction_units(self, faction: str) -> List[str]:
        """Get all unit types for a faction."""
        return [unit_type for unit_type, data in self.units.items() 
                if data['faction'] == faction]
    
    def get_role_units(self, role: str) -> List[str]:
        """Get all unit types for a role."""
        return [unit_type for unit_type, data in self.units.items() 
                if data['role'] == role]
    
    def save_registry_cache(self, cache_file: str = None):
        """Save discovered units to cache file for faster loading."""
        if cache_file is None:
            cache_file = self.project_root / "config" / "unit_registry_cache.json"
        
        cache_data = {
            "units": self.units,
            "factions": list(self.factions),
            "roles": list(self.roles),
            "faction_role_combinations": list(self.faction_role_combinations),
            "faction_role_matrix": self.faction_role_matrix
        }
        
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2, default=str)
        
        print(f"💾 Unit registry cached to: {cache_file}")
    
    def print_summary(self):
        """Print a summary of discovered units and required models."""
        print("\n" + "="*60)
        print("UNIT REGISTRY SUMMARY")
        print("="*60)
        
        print(f"\n📊 STATISTICS:")
        print(f"  • Total Units: {len(self.units)}")
        print(f"  • Factions: {len(self.factions)} ({', '.join(sorted(self.factions))})")
        print(f"  • Roles: {len(self.roles)} ({', '.join(sorted(self.roles))})")
        print(f"  • Required Models: {len(self.get_required_models())}")
        
        print(f"\n🤖 REQUIRED MODELS:")
        for model_key in sorted(self.get_required_models()):
            units = self.get_units_for_model(model_key)
            print(f"  • {model_key}: {len(units)} units ({', '.join(units)})")
        
        print(f"\n📋 ALL UNITS:")
        for faction in sorted(self.factions):
            faction_units = self.get_faction_units(faction)
            print(f"  {faction}: {len(faction_units)} units")
            for unit_type in sorted(faction_units):
                unit_data = self.units[unit_type]
                stats = f"HP:{require_key(unit_data, 'HP_MAX')} MOVE:{require_key(unit_data, 'MOVE')} RNG:{require_key(unit_data, 'RNG_RNG')}"
                print(f"    - {unit_type} ({unit_data['role']}) [{stats}]")


def main():
    """Test the unit registry system."""
    print("🧪 Testing Unit Registry System")
    
    try:
        registry = UnitRegistry()
        registry.print_summary()
        registry.save_registry_cache()
        
        print("\n✅ Unit Registry test completed successfully!")
        
    except Exception as e:
        print(f"❌ Unit Registry test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
