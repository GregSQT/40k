#!/usr/bin/env python3
"""
TypeScript Fixes + Project Cleanup Script
=========================================
This script will:
1. Fix all TypeScript compilation errors
2. Clean up and reorganize the project structure
3. Update configuration files
"""

import os
import json
import shutil
import sys
import re
from pathlib import Path

class TypeScriptFixer:
    def __init__(self, project_root="."):
        self.project_root = Path(project_root).resolve()
        self.frontend_src = self.project_root / "frontend" / "src"
        
    def log(self, message, level="INFO"):
        """Simple logging function"""
        print(f"[{level}] {message}")
        
    def create_backup(self):
        """Create a backup before making changes"""
        backup_dir = self.project_root / "backup_before_fixes"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
            
        self.log("Creating backup...")
        backup_dir.mkdir()
        
        # Backup the entire frontend/src directory
        if (self.project_root / "frontend" / "src").exists():
            shutil.copytree(
                self.project_root / "frontend" / "src",
                backup_dir / "frontend_src"
            )
        
        self.log(f"Backup created at: {backup_dir}")
        
    def fix_ai_ts(self):
        """Fix ai.ts parameter type error"""
        ai_file = self.frontend_src / "ai" / "ai.ts"
        if not ai_file.exists():
            self.log("ai.ts not found, skipping...", "WARN")
            return
            
        self.log("Fixing ai.ts...")
        
        content = '''// frontend/src/ai/ai.ts

interface GameState {
  units: Array<{
    id: number;
    player: number;
    col: number;
    row: number;
    CUR_HP: number;
    MOVE: number;
    RNG_RNG: number;
    RNG_DMG: number;
    CC_DMG: number;
  }>;
}

export async function fetchAiAction(gameState: GameState) {
  console.log("[AI] Sending gameState to backend:", gameState);
  const response = await fetch("http://localhost:8000/ai/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ state: { units: gameState.units } })
  });
  const result = await response.json();
  console.log("[AI] Got result from backend:", result);
  return result;
}
'''
        
        with open(ai_file, 'w', encoding='utf-8') as f:
            f.write(content)
        self.log("Fixed ai.ts parameter type")
        
    def fix_board_tsx(self):
        """Fix Board.tsx app.view type error"""
        board_file = self.frontend_src / "components" / "Board.tsx"
        if not board_file.exists():
            self.log("Board.tsx not found, skipping...", "WARN")
            return
            
        self.log("Fixing Board.tsx...")
        
        with open(board_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Fix the app.view type issue by adding proper type checking
        old_pattern = r'app\.view\.addEventListener\("contextmenu"'
        new_pattern = r'(app.view as HTMLCanvasElement).addEventListener("contextmenu"'
        
        if old_pattern in content:
            content = re.sub(
                r'app\.view\.addEventListener\("contextmenu"',
                r'(app.view as HTMLCanvasElement).addEventListener("contextmenu"',
                content
            )
            
            with open(board_file, 'w', encoding='utf-8') as f:
                f.write(content)
            self.log("Fixed Board.tsx app.view type issue")
        else:
            self.log("Board.tsx app.view pattern not found", "WARN")
            
    def fix_gameboard_tsx(self):
        """Fix GameBoard.tsx type mismatches"""
        gameboard_file = self.frontend_src / "components" / "GameBoard.tsx"
        if not gameboard_file.exists():
            self.log("GameBoard.tsx not found, skipping...", "WARN")
            return
            
        self.log("Fixing GameBoard.tsx...")
        
        # Replace the file with a corrected version
        content = '''// src/components/GameBoard.tsx
import React from 'react';
import Board from './Board';
import { Unit, GameState, MovePreview, AttackPreview, UnitId } from '../types/game';

interface GameBoardProps {
  units: Unit[];
  selectedUnitId: UnitId | null;
  phase: GameState['phase'];
  mode: GameState['mode'];
  movePreview: MovePreview | null;
  attackPreview: AttackPreview | null;
  currentPlayer: GameState['currentPlayer'];
  unitsMoved: UnitId[];
  unitsCharged: UnitId[];
  unitsAttacked: UnitId[];
  onSelectUnit: (id: UnitId | null) => void;
  onStartMovePreview: (unitId: UnitId, col: number, row: number) => void;
  onStartAttackPreview: (unitId: UnitId, col: number, row: number) => void;
  onConfirmMove: () => void;
  onCancelMove: () => void;
  onShoot: (shooterId: UnitId, targetId: UnitId) => void;
  onCombatAttack: (attackerId: UnitId, targetId: UnitId | null) => void;
  onCharge: (chargerId: UnitId, targetId: UnitId) => void;
  onMoveCharger: (chargerId: UnitId, destCol: number, destRow: number) => void;
  onCancelCharge: () => void;
  onValidateCharge: (chargerId: UnitId) => void;
}

export const GameBoard: React.FC<GameBoardProps> = (props) => {
  // Type-safe wrapper for Board component
  // Convert string/number IDs to proper number type for Board component
  
  const handleSelectUnit = (id: number | string | null) => {
    if (typeof id === 'string') {
      const numId = parseInt(id, 10);
      props.onSelectUnit(isNaN(numId) ? null : numId);
    } else {
      props.onSelectUnit(id);
    }
  };
  
  const handleStartMovePreview = (unitId: number | string, col: number | string, row: number | string) => {
    const numUnitId = typeof unitId === 'string' ? parseInt(unitId, 10) : unitId;
    const numCol = typeof col === 'string' ? parseInt(col, 10) : col;
    const numRow = typeof row === 'string' ? parseInt(row, 10) : row;
    
    if (!isNaN(numUnitId) && !isNaN(numCol) && !isNaN(numRow)) {
      props.onStartMovePreview(numUnitId, numCol, numRow);
    }
  };
  
  return (
    <div className="game-board">
      <Board
        units={props.units}
        selectedUnitId={props.selectedUnitId}
        phase={props.phase}
        mode={props.mode}
        movePreview={props.movePreview}
        attackPreview={props.attackPreview}
        currentPlayer={props.currentPlayer}
        unitsMoved={props.unitsMoved}
        unitsCharged={props.unitsCharged}
        unitsAttacked={props.unitsAttacked}
        onSelectUnit={handleSelectUnit}
        onStartMovePreview={handleStartMovePreview}
        onStartAttackPreview={props.onStartAttackPreview}
        onConfirmMove={props.onConfirmMove}
        onCancelMove={props.onCancelMove}
        onShoot={props.onShoot}
        onCombatAttack={props.onCombatAttack}
        onCharge={props.onCharge}
        onMoveCharger={props.onMoveCharger}
        onCancelCharge={props.onCancelCharge}
        onValidateCharge={props.onValidateCharge}
      />
    </div>
  );
};
'''
        
        with open(gameboard_file, 'w', encoding='utf-8') as f:
            f.write(content)
        self.log("Fixed GameBoard.tsx type mismatches")
        
    def fix_unitfactory_ts(self):
        """Fix UnitFactory.ts import.meta.glob error"""
        unitfactory_file = self.frontend_src / "data" / "UnitFactory.ts"
        if not unitfactory_file.exists():
            self.log("UnitFactory.ts not found, skipping...", "WARN")
            return
            
        self.log("Fixing UnitFactory.ts...")
        
        # Create a simpler version without import.meta.glob
        content = '''// frontend/src/data/UnitFactory.ts

// Direct imports instead of dynamic glob
import { Intercessor } from '../roster/spaceMarine/Intercessor';
import { AssaultIntercessor } from '../roster/spaceMarine/AssaultIntercessor';
import { SpaceMarineMeleeUnit } from '../roster/spaceMarine/SpaceMarineMeleeUnit';
import { SpaceMarineRangedUnit } from '../roster/spaceMarine/SpaceMarineRangedUnit';

export type UnitType = 
  | "Intercessor" 
  | "AssaultIntercessor" 
  | "SpaceMarineMeleeUnit" 
  | "SpaceMarineRangedUnit";

export interface Unit {
  id: number;
  name: string;
  type: UnitType;
  player: 0 | 1;
  col: number;
  row: number;
  color: number;
  MOVE: number;
  HP_MAX: number;
  RNG_RNG: number;
  RNG_DMG: number;
  CC_DMG: number;
  ICON: string;
  CUR_HP?: number;
}

// Unit class registry
const unitClassMap: Record<UnitType, any> = {
  "Intercessor": Intercessor,
  "AssaultIntercessor": AssaultIntercessor,
  "SpaceMarineMeleeUnit": SpaceMarineMeleeUnit,
  "SpaceMarineRangedUnit": SpaceMarineRangedUnit,
};

export function createUnit(params: {
  id: number;
  name: string;
  type: UnitType;
  player: 0 | 1;
  col: number;
  row: number;
  color: number;
}): Unit {
  const UnitClass = unitClassMap[params.type];
  
  if (!UnitClass) {
    throw new Error(`Unknown unit type: ${params.type}`);
  }
  
  return {
    ...params,
    MOVE: UnitClass.MOVE || 6,
    HP_MAX: UnitClass.HP_MAX || 4,
    RNG_RNG: UnitClass.RNG_RNG || 4,
    RNG_DMG: UnitClass.RNG_DMG || 1,
    CC_DMG: UnitClass.CC_DMG || 1,
    ICON: UnitClass.ICON || "default",
    CUR_HP: UnitClass.HP_MAX || 4,
  };
}
'''
        
        with open(unitfactory_file, 'w', encoding='utf-8') as f:
            f.write(content)
        self.log("Fixed UnitFactory.ts import.meta.glob issue")
        
    def create_missing_types(self):
        """Create missing type definitions"""
        types_dir = self.frontend_src / "types"
        types_dir.mkdir(exist_ok=True)
        
        # Create game types if missing
        game_types_file = types_dir / "game.ts"
        if not game_types_file.exists():
            self.log("Creating missing game types...")
            
            content = '''// src/types/game.ts

export type PlayerId = 0 | 1;
export type UnitId = number;

export type GamePhase = "move" | "shoot" | "charge" | "combat";
export type GameMode = "select" | "movePreview" | "attackPreview" | "chargePreview";

export interface Position {
  col: number;
  row: number;
}

export interface Unit {
  id: UnitId;
  name: string;
  type: string;
  player: PlayerId;
  col: number;
  row: number;
  color: number;
  MOVE: number;
  HP_MAX: number;
  RNG_RNG: number;
  RNG_DMG: number;
  CC_DMG: number;
  ICON: string;
  CUR_HP: number;
}

export interface GameState {
  phase: GamePhase;
  mode: GameMode;
  currentPlayer: PlayerId;
  units: Unit[];
  selectedUnitId: UnitId | null;
  unitsMoved: UnitId[];
  unitsCharged: UnitId[];
  unitsAttacked: UnitId[];
}

export interface MovePreview {
  unitId: UnitId;
  destCol: number;
  destRow: number;
}

export interface AttackPreview {
  unitId: UnitId;
  col: number;
  row: number;
}

export interface AIGameState {
  units: Unit[];
}

export interface AIAction {
  action: "move" | "moveAwayToRngRng" | "shoot" | "charge" | "attack" | "skip";
  unitId: UnitId;
  destCol?: number;
  destRow?: number;
  targetId?: UnitId;
}

export interface GameActions {
  selectUnit: (id: UnitId | null) => void;
  startMovePreview: (unitId: UnitId, col: number, row: number) => void;
  startAttackPreview: (unitId: UnitId, col: number, row: number) => void;
  confirmMove: () => void;
  cancelMove: () => void;
  shoot: (shooterId: UnitId, targetId: UnitId) => void;
  combatAttack: (attackerId: UnitId, targetId: UnitId | null) => void;
  charge: (chargerId: UnitId, targetId: UnitId) => void;
  moveCharger: (chargerId: UnitId, destCol: number, destRow: number) => void;
  cancelCharge: () => void;
  validateCharge: (chargerId: UnitId) => void;
}
'''
            
            with open(game_types_file, 'w', encoding='utf-8') as f:
                f.write(content)
            self.log("Created game types")
        
        # Update types index
        types_index_file = types_dir / "index.ts"
        if not types_index_file.exists():
            content = '''// src/types/index.ts
export type {
  PlayerId,
  UnitId,
  GamePhase,
  GameMode,
  Position,
  Unit,
  GameState,
  MovePreview,
  AttackPreview,
  AIGameState,
  AIAction,
  GameActions,
} from './game';

export type ComponentProps<T = Record<string, unknown>> = T & {
  className?: string;
  children?: React.ReactNode;
};
'''
            
            with open(types_index_file, 'w', encoding='utf-8') as f:
                f.write(content)
            self.log("Created types index")
            
    def add_vite_env_types(self):
        """Add proper vite-env.d.ts with import.meta.glob support"""
        vite_env_file = self.frontend_src / "vite-env.d.ts"
        
        content = '''/// <reference types="vite/client" />

// Extend ImportMeta interface to include glob
interface ImportMeta {
  glob: <T = any>(
    pattern: string,
    options?: {
      eager?: boolean;
      import?: string;
      query?: string;
      as?: string;
    }
  ) => Record<string, T>;
}
'''
        
        with open(vite_env_file, 'w', encoding='utf-8') as f:
            f.write(content)
        self.log("Added proper vite-env.d.ts")
        
    def run_typescript_fixes(self):
        """Run all TypeScript fixes"""
        self.log("Starting TypeScript fixes...")
        
        # Create backup
        self.create_backup()
        
        # Apply fixes
        self.fix_ai_ts()
        self.fix_board_tsx()
        self.fix_gameboard_tsx()
        self.fix_unitfactory_ts()
        self.create_missing_types()
        self.add_vite_env_types()
        
        self.log("✅ TypeScript fixes completed!")
        
    def run_project_cleanup(self):
        """Run the project cleanup after TypeScript fixes"""
        self.log("Starting project cleanup...")
        
        # Remove unnecessary files
        files_to_remove = [
            "dist/frontend.tsbuildinfo",
            "frontend/README.md", 
            "backup.log",
            "Notes.txt",
            "Path.txt",
            "dist"  # Root dist folder
        ]
        
        for file_path in files_to_remove:
            full_path = self.project_root / file_path
            if full_path.exists():
                if full_path.is_dir():
                    shutil.rmtree(full_path)
                    self.log(f"Removed directory: {file_path}")
                else:
                    full_path.unlink()
                    self.log(f"Removed file: {file_path}")
                    
        # Move development tools
        tools_dir = self.project_root / "tools"
        tools_dir.mkdir(exist_ok=True)
        
        save_py = self.project_root / "frontend" / "save.py"
        if save_py.exists():
            shutil.move(str(save_py), str(tools_dir / "backup_script.py"))
            self.log("Moved save.py to tools/backup_script.py")
            
        # Update TypeScript configs
        self.update_typescript_configs()
        
        # Create improved .gitignore
        self.create_gitignore()
        
        self.log("✅ Project cleanup completed!")
        
    def update_typescript_configs(self):
        """Update TypeScript configuration files"""
        self.log("Updating TypeScript configs...")
        
        # Update tsconfig.base.json
        base_config = {
            "compilerOptions": {
                "baseUrl": ".",
                "paths": {
                    "@/*": ["frontend/src/*"],
                    "@roster/*": ["frontend/src/roster/*"],
                    "@data/*": ["frontend/src/data/*"],
                    "@components/*": ["frontend/src/components/*"],
                    "@pages/*": ["frontend/src/pages/*"],
                    "@types/*": ["frontend/src/types/*"],
                    "@ai/*": ["ai/*"]
                }
            }
        }
        
        with open(self.project_root / "tsconfig.base.json", 'w') as f:
            json.dump(base_config, f, indent=2)
            
        # Update frontend/tsconfig.json
        frontend_config = {
            "extends": "../tsconfig.base.json",
            "compilerOptions": {
                "baseUrl": ".",
                "paths": {
                    "@/*": ["src/*"],
                    "@roster/*": ["src/roster/*"],
                    "@data/*": ["src/data/*"],
                    "@components/*": ["src/components/*"],
                    "@pages/*": ["src/pages/*"],
                    "@types/*": ["src/types/*"],
                    "@ai/*": ["../ai/*"]
                },
                "composite": True,
                "outDir": "dist",
                "rootDir": "src",
                "module": "ESNext",
                "moduleResolution": "node",
                "strict": True,
                "esModuleInterop": True,
                "target": "ES2020",
                "jsx": "react-jsx",
                "skipLibCheck": True,
                "allowSyntheticDefaultImports": True,
                "resolveJsonModule": True,
                "forceConsistentCasingInFileNames": True,
                "tsBuildInfoFile": "dist/frontend.tsbuildinfo"
            },
            "include": ["src/**/*"]
        }
        
        with open(self.project_root / "frontend" / "tsconfig.json", 'w') as f:
            json.dump(frontend_config, f, indent=2)
            
        self.log("Updated TypeScript configs")
        
    def create_gitignore(self):
        """Create a clean .gitignore"""
        content = '''# Dependencies
node_modules/

# Build outputs
dist/
build/
*.tsbuildinfo

# Development
.vscode/
.idea/

# Logs
*.log
backup.log

# Environment variables
.env*

# OS files
.DS_Store
Thumbs.db

# Python
__pycache__/
*.py[cod]
.venv/

# Backups
backup_*/
versions/
'''
        
        with open(self.project_root / ".gitignore", 'w') as f:
            f.write(content)
        self.log("Created clean .gitignore")

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Fix TypeScript errors and clean up project")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    parser.add_argument("--fixes-only", action="store_true", help="Only fix TypeScript errors")
    
    args = parser.parse_args()
    
    fixer = TypeScriptFixer(args.project_root)
    
    print("This script will fix TypeScript compilation errors and clean up your project.")
    response = input("Continue? (y/N): ")
    
    if response.lower() not in ['y', 'yes']:
        print("Cancelled.")
        return
    
    try:
        # Always run TypeScript fixes
        fixer.run_typescript_fixes()
        
        # Run cleanup unless fixes-only is specified
        if not args.fixes_only:
            fixer.run_project_cleanup()
            
        print("\n✅ All fixes completed successfully!")
        print("\nNext steps:")
        print("1. Test the build: cd frontend && npm run build")
        print("2. Review changes in your IDE")
        print("3. Remove backup_before_fixes/ when satisfied")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("Check backup_before_fixes/ to restore if needed")
        raise

if __name__ == "__main__":
    main()