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
        self._discover_all_units()
        self._build_faction_role_matrix()
    
    def _discover_all_units(self):
        """Scan TypeScript files and extract all unit definitions dynamically."""
        print("🔍 Discovering units from TypeScript files...")
        
        if not self.roster_dir.exists():
            raise FileNotFoundError(f"Roster directory not found: {self.roster_dir}")
        
        unit_count = 0
        
        # Scan all faction directories
        for faction_dir in self.roster_dir.iterdir():
            if faction_dir.is_dir() and not faction_dir.name.startswith('.'):
                faction_name = faction_dir.name
                print(f"  📁 Scanning faction: {faction_name}")
                
                # Scan all TypeScript files in faction directory
                for ts_file in faction_dir.glob("*.ts"):
                    if ts_file.name.startswith('index') or 'Unit.ts' in ts_file.name:
                        continue  # Skip base classes and index files
                    
                    unit_data = self._parse_unit_file(ts_file, faction_name)
                    if unit_data:
                        self.units[unit_data['unit_type']] = unit_data
                        self.factions.add(unit_data['faction'])
                        self.roles.add(unit_data['role'])
                        self.faction_role_combinations.add((unit_data['faction'], unit_data['role']))
                        unit_count += 1
                        print(f"    ✅ {unit_data['unit_type']} ({unit_data['faction']} {unit_data['role']})")
        
        print(f"📊 Discovery complete: {unit_count} units, {len(self.factions)} factions, {len(self.roles)} roles")
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
            
            # Extract static numeric properties
            static_props = self._extract_static_properties(content)
            unit_data.update(static_props)
            
            # Validate essential properties
            required_props = ['HP_MAX', 'MOVE', 'RNG_RNG', 'RNG_DMG', 'CC_DMG']
            for prop in required_props:
                if prop not in unit_data:
                    print(f"    ⚠️ Missing {prop} for {unit_type}")
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
        # SpaceMarineMeleeUnit → SpaceMarine
        # TyranidRangedUnit → Tyranid
        faction_match = re.match(r'(\w+?)(Melee|Ranged|Support)Unit', base_class)
        if faction_match:
            faction = faction_match.group(1)
        else:
            # Fallback to directory name
            faction = faction_dir_name.title()
        
        return faction, role
    
    def _extract_static_properties(self, content: str) -> Dict:
        """Extract all static properties from TypeScript class."""
        properties = {}
        
        # Pattern to match static properties
        static_pattern = r'static\s+(\w+)\s*=\s*([^;]+);'
        matches = re.findall(static_pattern, content)
        
        for prop_name, prop_value in matches:
            # Clean up the value
            prop_value = prop_value.strip()
            
            # Try to convert to appropriate type
            if prop_value.startswith('"') or prop_value.startswith("'"):
                # String value
                properties[prop_name] = prop_value.strip('"\'')
            elif prop_value.isdigit():
                # Integer value
                properties[prop_name] = int(prop_value)
            elif re.match(r'^\d+\.\d+$', prop_value):
                # Float value
                properties[prop_name] = float(prop_value)
            elif prop_value.lower() in ['true', 'false']:
                # Boolean value
                properties[prop_name] = prop_value.lower() == 'true'
            else:
                # Keep as string
                properties[prop_name] = prop_value
        
        return properties
    
    def _build_faction_role_matrix(self):
        """Build the faction-role matrix for model creation."""
        for faction in self.factions:
            self.faction_role_matrix[faction] = []
            
        for unit_type, unit_data in self.units.items():
            faction = unit_data['faction']
            role = unit_data['role']
            faction_role_key = f"{faction}_{role}"
            
            if faction_role_key not in self.faction_role_matrix:
                self.faction_role_matrix[faction_role_key] = []
            
            self.faction_role_matrix[faction_role_key].append(unit_type)
    
    def get_model_key(self, unit_type: str) -> str:
        """Get the model key for a given unit type."""
        if unit_type not in self.units:
            raise ValueError(f"Unknown unit type: {unit_type}")
        
        unit_data = self.units[unit_type]
        return f"{unit_data['faction']}_{unit_data['role']}"
    
    def get_required_models(self) -> List[str]:
        """Get list of all required model keys."""
        return [f"{faction}_{role}" for faction, role in self.faction_role_combinations]
    
    def get_all_model_keys(self) -> List[str]:
        """Get all available model keys (alias for get_required_models)."""
        return self.get_required_models()
    
    def get_units_for_model(self, model_key: str) -> List[str]:
        """Get list of unit types that use a specific model."""
        return self.faction_role_matrix.get(model_key, [])
    
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
                stats = f"HP:{unit_data.get('HP_MAX', '?')} MOVE:{unit_data.get('MOVE', '?')} RNG:{unit_data.get('RNG_RNG', '?')}"
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