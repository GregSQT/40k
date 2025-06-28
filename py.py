# cleanup_project.py - Project Cleanup Implementation Script
import os
import json
import shutil
from pathlib import Path

class ProjectCleanup:
    def __init__(self, root_path="."):
        self.root_path = Path(root_path).resolve()
        self.config_dir = self.root_path / "config"
        self.deleted_files = []
        self.created_files = []
        self.errors = []

    def log_action(self, action, path, success=True):
        """Log cleanup actions."""
        status = "✅" if success else "❌"
        print(f"{status} {action}: {path}")
        if not success:
            self.errors.append(f"{action}: {path}")

    def delete_unnecessary_files(self):
        """Delete duplicate and unnecessary files."""
        files_to_delete = [
            "frontend/public/ai/scenario copy.json",
            "frontend/src/components/ReplayViewer.tsx.backup",
            "tsconfig.base.json",  # Only if not referenced
        ]
        
        print("🗑️  Deleting unnecessary files...")
        
        for file_path in files_to_delete:
            full_path = self.root_path / file_path
            if full_path.exists():
                try:
                    if full_path.is_file():
                        full_path.unlink()
                    else:
                        shutil.rmtree(full_path)
                    self.deleted_files.append(str(file_path))
                    self.log_action("DELETED", file_path)
                except Exception as e:
                    self.log_action(f"FAILED TO DELETE", f"{file_path} - {e}", False)
            else:
                print(f"⚠️  File not found: {file_path}")

    def create_board_config(self):
        """Create centralized board configuration."""
        board_config = {
            "default": {
                "cols": 24,
                "rows": 18,
                "hex_radius": 24,
                "margin": 32,
                "colors": {
                    "background": "0x002200",
                    "cell_even": "0x002200",
                    "cell_odd": "0x001a00",
                    "cell_border": "0x00ff00",
                    "player_0": "0x244488",
                    "player_1": "0x882222",
                    "hp_full": "0x36e36b",
                    "hp_damaged": "0x444444",
                    "highlight": "0x80ff80",
                    "current_unit": "0xffd700"
                }
            },
            "small": {
                "cols": 12,
                "rows": 9,
                "hex_radius": 20,
                "margin": 24,
                "colors": {
                    "background": "0x002200",
                    "cell_even": "0x002200",
                    "cell_odd": "0x001a00",
                    "cell_border": "0x00ff00",
                    "player_0": "0x244488",
                    "player_1": "0x882222",
                    "hp_full": "0x36e36b",
                    "hp_damaged": "0x444444",
                    "highlight": "0x80ff80",
                    "current_unit": "0xffd700"
                }
            },
            "large": {
                "cols": 36,
                "rows": 27,
                "hex_radius": 20,
                "margin": 40,
                "colors": {
                    "background": "0x002200",
                    "cell_even": "0x002200",
                    "cell_odd": "0x001a00",
                    "cell_border": "0x00ff00",
                    "player_0": "0x244488",
                    "player_1": "0x882222",
                    "hp_full": "0x36e36b",
                    "hp_damaged": "0x444444",
                    "highlight": "0x80ff80",
                    "current_unit": "0xffd700"
                }
            }
        }
        
        config_file = self.config_dir / "board_config.json"
        self.config_dir.mkdir(exist_ok=True)
        
        try:
            with open(config_file, 'w') as f:
                json.dump(board_config, f, indent=2)
            self.created_files.append(str(config_file))
            self.log_action("CREATED", "config/board_config.json")
        except Exception as e:
            self.log_action("FAILED TO CREATE", f"config/board_config.json - {e}", False)

    def create_unit_definitions(self):
        """Create unit definitions configuration."""
        unit_definitions = {
            "Intercessor": {
                "hp_max": 3,
                "move": 4,
                "ranged_range": 8,
                "ranged_damage": 2,
                "melee_damage": 1,
                "is_ranged": True,
                "is_melee": False,
                "cost": 100,
                "description": "Standard Space Marine with bolt rifle"
            },
            "AssaultIntercessor": {
                "hp_max": 4,
                "move": 6,
                "ranged_range": 4,
                "ranged_damage": 1,
                "melee_damage": 2,
                "is_ranged": False,
                "is_melee": True,
                "cost": 120,
                "description": "Close combat specialist Space Marine"
            },
            "Terminator": {
                "hp_max": 5,
                "move": 3,
                "ranged_range": 6,
                "ranged_damage": 3,
                "melee_damage": 3,
                "is_ranged": True,
                "is_melee": True,
                "cost": 200,
                "description": "Heavy armored elite unit"
            },
            "Scout": {
                "hp_max": 2,
                "move": 5,
                "ranged_range": 10,
                "ranged_damage": 1,
                "melee_damage": 1,
                "is_ranged": True,
                "is_melee": False,
                "cost": 80,
                "description": "Fast reconnaissance unit"
            }
        }
        
        config_file = self.config_dir / "unit_definitions.json"
        
        try:
            with open(config_file, 'w') as f:
                json.dump(unit_definitions, f, indent=2)
            self.created_files.append(str(config_file))
            self.log_action("CREATED", "config/unit_definitions.json")
        except Exception as e:
            self.log_action("FAILED TO CREATE", f"config/unit_definitions.json - {e}", False)

    def update_scenario_to_use_config(self):
        """Update scenario files to reference config instead of hardcoding."""
        # Update frontend/public/ai/scenario.json to remove hardcoded board
        scenario_file = self.root_path / "frontend" / "public" / "ai" / "scenario.json"
        
        if scenario_file.exists():
            try:
                with open(scenario_file, 'r') as f:
                    scenario = json.load(f)
                
                # Remove hardcoded board config, replace with reference
                updated_scenario = {
                    "board_config": "default",  # Reference to board config
                    "units": scenario.get("units", [])
                }
                
                with open(scenario_file, 'w') as f:
                    json.dump(updated_scenario, f, indent=2)
                
                self.log_action("UPDATED", "frontend/public/ai/scenario.json")
            except Exception as e:
                self.log_action("FAILED TO UPDATE", f"frontend/public/ai/scenario.json - {e}", False)

    def create_use_game_config_hook(self):
        """Create React hook for loading game configuration."""
        hook_content = '''// frontend/src/hooks/useGameConfig.ts
import { useState, useEffect } from 'react';

interface BoardConfig {
  cols: number;
  rows: number;
  hex_radius: number;
  margin: number;
  colors: Record<string, string>;
}

interface UnitDefinition {
  hp_max: number;
  move: number;
  ranged_range: number;
  ranged_damage: number;
  melee_damage: number;
  is_ranged: boolean;
  is_melee: boolean;
  cost: number;
  description?: string;
}

interface GameConfig {
  boardConfig: BoardConfig | null;
  unitDefinitions: Record<string, UnitDefinition>;
  loading: boolean;
  error: string | null;
}

export const useGameConfig = (boardConfigName: string = "default"): GameConfig => {
  const [boardConfig, setBoardConfig] = useState<BoardConfig | null>(null);
  const [unitDefinitions, setUnitDefinitions] = useState<Record<string, UnitDefinition>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadConfigs = async () => {
      try {
        setLoading(true);
        setError(null);
        
        // Load board config
        const boardResponse = await fetch(`/ai/config/board_config.json`);
        if (!boardResponse.ok) {
          throw new Error(`Failed to load board config: ${boardResponse.status}`);
        }
        const boardData = await boardResponse.json();
        
        if (!boardData[boardConfigName]) {
          throw new Error(`Board config '${boardConfigName}' not found`);
        }
        
        setBoardConfig(boardData[boardConfigName]);

        // Load unit definitions
        const unitResponse = await fetch('/ai/config/unit_definitions.json');
        if (!unitResponse.ok) {
          throw new Error(`Failed to load unit definitions: ${unitResponse.status}`);
        }
        const unitData = await unitResponse.json();
        setUnitDefinitions(unitData);

      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to load configuration';
        setError(errorMessage);
        console.error('Game config loading error:', err);
        
        // Set fallback defaults
        setBoardConfig({
          cols: 24,
          rows: 18,
          hex_radius: 24,
          margin: 32,
          colors: {
            background: "0x002200",
            player_0: "0x244488",
            player_1: "0x882222",
            highlight: "0x80ff80",
            current_unit: "0xffd700"
          }
        });
        
      } finally {
        setLoading(false);
      }
    };

    loadConfigs();
  }, [boardConfigName]);

  return { boardConfig, unitDefinitions, loading, error };
};

export default useGameConfig;
'''
        
        hooks_dir = self.root_path / "frontend" / "src" / "hooks"
        hooks_dir.mkdir(exist_ok=True)
        
        hook_file = hooks_dir / "useGameConfig.ts"
        
        try:
            with open(hook_file, 'w') as f:
                f.write(hook_content)
            self.created_files.append(str(hook_file))
            self.log_action("CREATED", "frontend/src/hooks/useGameConfig.ts")
        except Exception as e:
            self.log_action("FAILED TO CREATE", f"frontend/src/hooks/useGameConfig.ts - {e}", False)

    def copy_configs_to_public(self):
        """Copy config files to frontend/public/ai/config for web access."""
        public_config_dir = self.root_path / "frontend" / "public" / "ai" / "config"
        public_config_dir.mkdir(parents=True, exist_ok=True)
        
        configs_to_copy = [
            "board_config.json",
            "unit_definitions.json"
        ]
        
        for config_file in configs_to_copy:
            src = self.config_dir / config_file
            dest = public_config_dir / config_file
            
            if src.exists():
                try:
                    shutil.copy2(src, dest)
                    self.log_action("COPIED", f"config/{config_file} -> frontend/public/ai/config/{config_file}")
                except Exception as e:
                    self.log_action("FAILED TO COPY", f"{config_file} - {e}", False)

    def update_gitignore(self):
        """Update .gitignore to exclude config.local.json but include main configs."""
        gitignore_file = self.root_path / ".gitignore"
        
        if gitignore_file.exists():
            try:
                with open(gitignore_file, 'r') as f:
                    content = f.read()
                
                # Add config exclusions if not present
                additions = [
                    "# Local configuration overrides",
                    "config.local.json",
                    "frontend/public/ai/config.local.json"
                ]
                
                needs_update = False
                for addition in additions:
                    if addition not in content:
                        content += "\n" + addition
                        needs_update = True
                
                if needs_update:
                    with open(gitignore_file, 'w') as f:
                        f.write(content)
                    self.log_action("UPDATED", ".gitignore")
                    
            except Exception as e:
                self.log_action("FAILED TO UPDATE", f".gitignore - {e}", False)

    def run_cleanup(self):
        """Execute full project cleanup."""
        print("🧹 Starting Warhammer 40K Project Cleanup...")
        print("=" * 60)
        
        # Step 1: Delete unnecessary files
        self.delete_unnecessary_files()
        print()
        
        # Step 2: Create configuration files
        print("📁 Creating configuration files...")
        self.create_board_config()
        self.create_unit_definitions()
        print()
        
        # Step 3: Update existing files
        print("🔄 Updating existing files...")
        self.update_scenario_to_use_config()
        print()
        
        # Step 4: Create new components
        print("⚛️  Creating React components...")
        self.create_use_game_config_hook()
        print()
        
        # Step 5: Copy configs for web access
        print("🌐 Setting up web-accessible configs...")
        self.copy_configs_to_public()
        print()
        
        # Step 6: Update gitignore
        print("📝 Updating .gitignore...")
        self.update_gitignore()
        print()
        
        # Summary
        print("=" * 60)
        print("🎯 CLEANUP SUMMARY")
        print("=" * 60)
        print(f"✅ Files created: {len(self.created_files)}")
        for file in self.created_files:
            print(f"   📄 {file}")
        
        print(f"🗑️  Files deleted: {len(self.deleted_files)}")
        for file in self.deleted_files:
            print(f"   ❌ {file}")
        
        if self.errors:
            print(f"⚠️  Errors encountered: {len(self.errors)}")
            for error in self.errors:
                print(f"   🚨 {error}")
        
        print("=" * 60)
        print("🎉 Project cleanup completed!")
        print("\n📋 NEXT STEPS:")
        print("1. Update Board.tsx to use useGameConfig() hook")
        print("2. Update ReplayViewer.tsx to use same config")
        print("3. Test all components with new configuration")
        print("4. Update AI scripts to use config_loader consistently")

if __name__ == "__main__":
    cleanup = ProjectCleanup()
    cleanup.run_cleanup()