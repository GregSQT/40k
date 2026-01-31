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
from typing import Dict, List, Set, Tuple
import sys
from shared.data_validation import require_key

class UnitRegistry:
    """Dynamic unit discovery and faction-role management system."""
    
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
        
        # Initialize the registry
        self._discover_all_units(verbose=False)
        self._build_faction_role_matrix()
    
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
                    for ts_file in units_dir.glob("*.ts"):
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
            static_props = self._extract_static_properties(content, faction_name)
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
        elif 'Ranged' in base_class:
            role = 'Ranged'
        elif 'Support' in base_class:
            role = 'Support'
        else:
            role = 'Unknown'
        
        # Extract faction from base class name
        # Handle both 4-part and 2-part base class naming patterns
        # 4-part: SpaceMarineInfantryTroopRangedSwarm -> SpaceMarine
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
                # Fallback to directory name
                faction = faction_dir_name.title()
        
        return faction, role
    
    def _extract_static_properties(self, content: str, faction_name: str) -> Dict:
        """Extract all static properties from TypeScript class, including weapons."""
        properties = {}
        
        # Try to import get_weapons, but continue if it fails (standalone mode)
        try:
            from engine.weapons import get_weapons
            weapons_available = True
        except ImportError:
            weapons_available = False
        
        # Pattern 1: Static properties simples (HP_MAX, MOVE, etc.)
        static_pattern = r'static\s+([A-Z_]+)\s*=\s*([^;]+);'
        matches = re.findall(static_pattern, content)
        
        for prop_name, prop_value in matches:
            # Skip RNG_WEAPONS and CC_WEAPONS - they are processed separately from RNG_WEAPON_CODES/CC_WEAPON_CODES
            if prop_name in ["RNG_WEAPONS", "CC_WEAPONS"]:
                continue
            
            # Clean up the value
            prop_value = prop_value.strip().strip('"\'')
            # Remove comments (everything after // or #)
            if '//' in prop_value:
                prop_value = prop_value.split('//')[0].strip()
            if '#' in prop_value:
                prop_value = prop_value.split('#')[0].strip()
            
            # Try to convert to appropriate type
            if prop_value.isdigit() or (prop_value.startswith('-') and prop_value[1:].isdigit()):
                properties[prop_name] = int(prop_value)
            elif prop_value.replace('.', '').isdigit():
                properties[prop_name] = float(prop_value)
            else:
                properties[prop_name] = prop_value
        
        # Pattern 2: RNG_WEAPON_CODES = ["code1", "code2"] ou [] (robuste)
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
        
        properties["RNG_WEAPONS"] = get_weapons(faction, codes)
        
        # Pattern 3: CC_WEAPON_CODES (même logique)
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
        
        properties["CC_WEAPONS"] = get_weapons(faction, codes)
        
        # Normalize output: both keys must exist (validated above)
        
        # Initialiser selectedWeaponIndex
        rng_weapons = require_key(properties, "RNG_WEAPONS")
        if rng_weapons:
            properties["selectedRngWeaponIndex"] = 0
        cc_weapons = require_key(properties, "CC_WEAPONS")
        if cc_weapons:
            properties["selectedCcWeaponIndex"] = 0
        
        return properties
    
    def _build_faction_role_matrix(self):
        """Build the faction-role matrix with custom agent mappings."""
        # Initialize faction containers
        for faction in self.factions:
            self.faction_role_matrix[faction] = []
        
        # Advanced 4-part agent mapping: Faction_MoveType_TankingLevel_AttackTypeTarget
        for unit_type, unit_data in self.units.items():
            faction = unit_data['faction']
            role = unit_data['role']
            
            # Generate 4-part agent key based on unit characteristics
            agent_key = self._generate_advanced_agent_key(unit_type, unit_data)
            
            # Add to matrix
            if agent_key not in self.faction_role_matrix:
                self.faction_role_matrix[agent_key] = []
            
            self.faction_role_matrix[agent_key].append(unit_type)
    
    def _generate_advanced_agent_key(self, unit_type: str, unit_data: Dict) -> str:
        """Generate 4-part agent key: Faction_MoveType_TankingLevel_AttackTypeTarget"""
        faction = unit_data['faction']
        role = unit_data['role']  # "Melee" or "Ranged"
        
        # Get all required properties - will raise errors if missing
        move_type = self._get_move_type(unit_type, unit_data)
        tanking_level = self._get_tanking_level(unit_type, unit_data)
        attack_target = self._get_attack_target(unit_type, unit_data, role)
        
        return f"{faction}_{move_type}_{tanking_level}_{attack_target}"
    
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
        """Get tanking level from unit data - must be explicitly defined in TypeScript."""
        if 'TANKING_LEVEL' not in unit_data:
            raise ValueError(f"Unit {unit_type} missing required TANKING_LEVEL property in TypeScript file")
        return unit_data['TANKING_LEVEL']

    def _get_move_type(self, unit_type: str, unit_data: Dict) -> str:
        """Get movement type from unit data - must be explicitly defined in TypeScript."""
        if 'MOVE_TYPE' not in unit_data:
            raise ValueError(f"Unit {unit_type} missing required MOVE_TYPE property in TypeScript file")
        return unit_data['MOVE_TYPE']
    
    def _get_attack_target(self, unit_type: str, unit_data: Dict, role: str) -> str:
        """Get attack type and target from unit data - must be explicitly defined in TypeScript."""
        if 'TARGET_TYPE' not in unit_data:
            raise ValueError(f"Unit {unit_type} missing required TARGET_TYPE property in TypeScript file")
        
        # Combine role (Melee/Ranged) with target type (Swarm/Troop/Elite)
        return f"{role}{unit_data['TARGET_TYPE']}"
    
    def get_model_key(self, unit_type: str) -> str:
        """Get the model key for a given unit type using 4-part advanced mapping."""
        if unit_type not in self.units:
            raise ValueError(f"Unknown unit type: {unit_type}")
        
        unit_data = self.units[unit_type]
        return self._generate_advanced_agent_key(unit_type, unit_data)
    
    def get_required_models(self) -> List[str]:
        """Get list of all required model keys using 4-part agent keys."""
        model_keys = set()
        for unit_type, unit_data in self.units.items():
            agent_key = self._generate_advanced_agent_key(unit_type, unit_data)
            model_keys.add(agent_key)
        return sorted(list(model_keys))
    
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
