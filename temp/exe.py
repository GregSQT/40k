#!/usr/bin/env python3
"""
Warhammer 40k Project Cleanup and Reorganization Script
======================================================
This script will:
1. Complete the migration to frontend/src/ structure
2. Remove unnecessary files
3. Fix configuration files
4. Reorganize project structure
5. Create proper .gitignore
"""

import os
import json
import shutil
import sys
from pathlib import Path

class ProjectCleaner:
    def __init__(self, project_root="."):
        self.project_root = Path(project_root).resolve()
        self.backup_created = False
        
    def log(self, message, level="INFO"):
        """Simple logging function"""
        print(f"[{level}] {message}")
        
    def create_backup(self):
        """Create a backup of current state before making changes"""
        backup_dir = self.project_root / "backup_before_cleanup"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
            
        self.log("Creating backup of current project state...")
        
        # Backup important files and directories
        important_items = [
            "frontend/src",
            "ai",
            "src",  # Old structure
            "tsconfig.base.json",
            "frontend/tsconfig.json",
            "frontend/vite.config.ts",
            "frontend/package.json",
            "package.json",
            ".gitignore"
        ]
        
        backup_dir.mkdir(exist_ok=True)
        
        for item in important_items:
            src_path = self.project_root / item
            if src_path.exists():
                dest_path = backup_dir / item
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                
                if src_path.is_dir():
                    shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_path, dest_path)
                    
        self.backup_created = True
        self.log(f"Backup created at: {backup_dir}")
        
    def remove_unnecessary_files(self):
        """Remove files that shouldn't be in the repository"""
        files_to_remove = [
            "dist/frontend.tsbuildinfo",
            "frontend/README.md",  # Generic Vite template
            "frontend/src/vite-env.d.ts",  # Can be regenerated
            "backup.log",
            "Notes.txt",
            "Path.txt",
            "dist",  # Root dist folder (we'll use frontend/dist)
        ]
        
        self.log("Removing unnecessary files...")
        
        for file_path in files_to_remove:
            full_path = self.project_root / file_path
            if full_path.exists():
                if full_path.is_dir():
                    shutil.rmtree(full_path)
                    self.log(f"Removed directory: {file_path}")
                else:
                    full_path.unlink()
                    self.log(f"Removed file: {file_path}")
            else:
                self.log(f"File not found (already clean): {file_path}", "DEBUG")
                
    def migrate_remaining_src_files(self):
        """Complete migration from root /src to /frontend/src"""
        old_src = self.project_root / "src"
        new_src = self.project_root / "frontend" / "src"
        
        if not old_src.exists():
            self.log("No root /src directory found - migration already complete")
            return
            
        self.log("Completing migration from /src to /frontend/src...")
        
        # Ensure target directory exists
        new_src.mkdir(parents=True, exist_ok=True)
        
        # Move roster files if they exist in old location
        old_roster = old_src / "roster"
        new_roster = new_src / "roster"
        
        if old_roster.exists():
            if new_roster.exists():
                # Merge directories
                self.log("Merging roster directories...")
                for item in old_roster.rglob("*"):
                    if item.is_file():
                        relative_path = item.relative_to(old_roster)
                        dest_file = new_roster / relative_path
                        dest_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, dest_file)
                        self.log(f"Moved: {item} -> {dest_file}")
            else:
                # Move entire directory
                shutil.move(str(old_roster), str(new_roster))
                self.log(f"Moved entire roster directory to frontend/src/")
                
        # Move any other files from old src
        for item in old_src.rglob("*"):
            if item.is_file() and item.parent != old_roster:
                relative_path = item.relative_to(old_src)
                dest_file = new_src / relative_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest_file)
                self.log(f"Moved additional file: {item} -> {dest_file}")
                
        # Remove old src directory if empty or only contains moved items
        try:
            if old_src.exists():
                shutil.rmtree(old_src)
                self.log("Removed old /src directory")
        except OSError as e:
            self.log(f"Could not remove old /src directory: {e}", "WARN")
            
    def fix_typescript_configs(self):
        """Update TypeScript configuration files"""
        self.log("Updating TypeScript configuration files...")
        
        # Fix the ROOT tsconfig.json issue
        root_config_path = self.project_root / "tsconfig.json"
        if root_config_path.exists():
            self.log("Fixing root tsconfig.json that's causing the 'No inputs found' error...")
            
            # Create a proper root tsconfig that references the frontend
            root_config = {
                "files": [],
                "references": [
                    {"path": "./frontend"}
                ],
                "compilerOptions": {
                    "baseUrl": ".",
                    "paths": {
                        "@/*": ["frontend/src/*"],
                        "@roster/*": ["frontend/src/roster/*"],
                        "@data/*": ["frontend/src/data/*"],
                        "@components/*": ["frontend/src/components/*"],
                        "@pages/*": ["frontend/src/pages/*"],
                        "@types/*": ["frontend/src/types/*"],
                        "@hooks/*": ["frontend/src/hooks/*"],
                        "@services/*": ["frontend/src/services/*"],
                        "@constants/*": ["frontend/src/constants/*"],
                        "@utils/*": ["frontend/src/utils/*"],
                        "@ai/*": ["ai/*"]
                    }
                }
            }
            
            with open(root_config_path, 'w', encoding='utf-8') as f:
                json.dump(root_config, f, indent=2)
            self.log("Fixed root tsconfig.json - now uses project references")
        
        # Update tsconfig.base.json (keep for shared settings)
        base_config_path = self.project_root / "tsconfig.base.json"
        if base_config_path.exists():
            base_config = {
                "compilerOptions": {
                    "target": "ES2020",
                    "lib": ["dom", "dom.iterable", "ES6"],
                    "allowJs": True,
                    "skipLibCheck": True,
                    "esModuleInterop": True,
                    "allowSyntheticDefaultImports": True,
                    "strict": True,
                    "forceConsistentCasingInFileNames": True,
                    "noFallthroughCasesInSwitch": True,
                    "module": "ESNext",
                    "moduleResolution": "node",
                    "resolveJsonModule": True,
                    "isolatedModules": True,
                    "jsx": "react-jsx"
                }
            }
            
            with open(base_config_path, 'w', encoding='utf-8') as f:
                json.dump(base_config, f, indent=2)
            self.log("Updated tsconfig.base.json")
            
        # Update frontend/tsconfig.json
        frontend_config_path = self.project_root / "frontend" / "tsconfig.json"
        if frontend_config_path.exists():
            frontend_config = {
                "extends": "../tsconfig.base.json",
                "compilerOptions": {
                    "baseUrl": "src",
                    "paths": {
                        "@/*": ["*"],
                        "@roster/*": ["roster/*"],
                        "@data/*": ["data/*"],
                        "@components/*": ["components/*"],
                        "@pages/*": ["pages/*"],
                        "@types/*": ["types/*"],
                        "@hooks/*": ["hooks/*"],
                        "@services/*": ["services/*"],
                        "@constants/*": ["constants/*"],
                        "@utils/*": ["utils/*"],
                        "@ai/*": ["../ai/*"]
                    },
                    "composite": True,
                    "outDir": "dist",
                    "rootDir": "src",
                    "noEmit": False,
                    "tsBuildInfoFile": "dist/tsconfig.tsbuildinfo"
                },
                "include": [
                    "src/**/*"
                ],
                "exclude": [
                    "node_modules",
                    "dist"
                ]
            }
            
            with open(frontend_config_path, 'w', encoding='utf-8') as f:
                json.dump(frontend_config, f, indent=2)
            self.log("Updated frontend/tsconfig.json")
            
    def reorganize_development_tools(self):
        """Move development scripts to tools directory"""
        self.log("Reorganizing development tools...")
        
        tools_dir = self.project_root / "tools"
        tools_dir.mkdir(exist_ok=True)
        
        # Move save.py to tools
        save_py = self.project_root / "frontend" / "save.py"
        if save_py.exists():
            new_save_py = tools_dir / "backup_script.py"
            shutil.move(str(save_py), str(new_save_py))
            self.log("Moved frontend/save.py to tools/backup_script.py")
            
            # Update the backup script paths
            self.update_backup_script(new_save_py)
            
        # Move generate_scenario.py to tools if it exists
        gen_scenario = self.project_root / "generate_scenario.py"
        if gen_scenario.exists():
            shutil.move(str(gen_scenario), str(tools_dir / "generate_scenario.py"))
            self.log("Moved generate_scenario.py to tools/")
            
    def update_backup_script(self, script_path):
        """Update the backup script with correct file paths"""
        self.log("Updating backup script with corrected paths...")
        
        try:
            with open(script_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Update the files_to_copy list to remove old paths and duplicates
            new_files_list = '''files_to_copy = [
        # Root config files
        "package.json",
        "tsconfig.json", 
        "tsconfig.base.json",
        
        # Frontend files
        "frontend/tsconfig.json",
        "frontend/vite.config.ts",
        "frontend/package.json",
        
        # Frontend source
        "frontend/src/App.tsx",
        "frontend/src/routes.tsx", 
        "frontend/src/main.tsx",
        
        # AI integration
        "frontend/src/ai/ai.ts",
        
        # Pages
        "frontend/src/pages/HomePage.tsx",
        "frontend/src/pages/ReplayPage.tsx", 
        "frontend/src/pages/GamePage.tsx",
        
        # Components
        "frontend/src/components/Board.tsx",
        "frontend/src/components/UnitSelector.tsx",
        "frontend/src/components/ReplayViewer.tsx",
        "frontend/src/components/LoadReplayButton.tsx",
        
        # Data
        "frontend/src/data/Units.ts",
        "frontend/src/data/UnitFactory.ts",
        "frontend/src/data/Scenario.ts",
        
        # Roster (now in frontend/src)
        "frontend/src/roster/spaceMarine/SpaceMarineMeleeUnit.ts",
        "frontend/src/roster/spaceMarine/SpaceMarineRangedUnit.ts", 
        "frontend/src/roster/spaceMarine/Intercessor.ts",
        "frontend/src/roster/spaceMarine/AssaultIntercessor.ts",
        "frontend/src/roster/exportRewards.js",
        
        # AI backend
        "ai/agent.py",
        "ai/api.py", 
        "ai/evaluate.py",
        "ai/gym40k.py",
        "ai/model.py",
        "ai/env_registration.py",
        "ai/state.py",
        "ai/test.py",
        "ai/train.py", 
        "ai/utils.py",
        
        # Tools
        "tools/generate_scenario.py",
    ]'''
            
            # Replace the old files_to_copy list
            import re
            pattern = r'files_to_copy\s*=\s*\[.*?\]'
            content = re.sub(pattern, new_files_list, content, flags=re.DOTALL)
            
            with open(script_path, 'w', encoding='utf-8') as f:
                f.write(content)
                
            self.log("Updated backup script with correct file paths")
            
        except Exception as e:
            self.log(f"Could not update backup script: {e}", "WARN")
            
    def create_improved_gitignore(self):
        """Create a clean, comprehensive .gitignore"""
        self.log("Creating improved .gitignore...")
        
        gitignore_content = '''# Dependencies
node_modules/
*.pnp
.pnp.js

# Build outputs
dist/
build/
*.tsbuildinfo

# Development
.vscode/
.idea/
*.swp
*.swo
*~

# Logs
logs/
*.log
npm-debug.log*
yarn-debug.log*
yarn-error.log*
lerna-debug.log*
backup.log

# Runtime data
pids/
*.pid
*.seed
*.pid.lock

# Coverage directory used by tools like istanbul
coverage/
*.lcov

# nyc test coverage
.nyc_output

# Environment variables
.env
.env.local
.env.development.local
.env.test.local
.env.production.local

# OS generated files
.DS_Store
.DS_Store?
._*
.Spotlight-V100
.Trashes
ehthumbs.db
Thumbs.db

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
.venv/
ENV/
env.bak/
venv.bak/

# AI/ML
*.pkl
*.h5
*.hdf5
models/
checkpoints/

# Temporary files
*.tmp
*.temp
temp/
tmp/

# Backup files
backup_*/
versions/
*.bak

# Documentation builds
docs/_build/

# Local configuration
config.local.json
'''

        gitignore_path = self.project_root / ".gitignore"
        with open(gitignore_path, 'w', encoding='utf-8') as f:
            f.write(gitignore_content)
            
        self.log("Created improved .gitignore")
        
    def create_project_structure_doc(self):
        """Create documentation of the new project structure"""
        self.log("Creating project structure documentation...")
        
        docs_dir = self.project_root / "docs"
        docs_dir.mkdir(exist_ok=True)
        
        structure_doc = '''# Project Structure

## Overview
This is a Warhammer 40k tactical game with AI opponents, built with React/TypeScript frontend and Python AI backend.

## Directory Structure

```
wh40k-tactics/
├── frontend/                    # React/TypeScript frontend
│   ├── src/
│   │   ├── components/          # React components
│   │   ├── pages/              # Page components
│   │   ├── data/               # Game data & factories
│   │   ├── roster/             # Unit definitions
│   │   │   └── spaceMarine/    # Space Marine units
│   │   └── ai/                 # Frontend AI integration
│   ├── dist/                   # Frontend build output
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── ai/                         # Python AI backend
│   ├── agent.py               # AI agent implementation
│   ├── api.py                 # API endpoints
│   ├── gym40k.py             # Gymnasium environment
│   ├── model.py              # Neural network models
│   └── ...
├── tools/                      # Development tools
│   ├── backup_script.py       # Project backup utility
│   └── generate_scenario.py   # Scenario generation
├── docs/                       # Documentation
└── README.md
```

## Key Components

### Frontend (`/frontend/src/`)
- **components/**: Reusable React components (Board, UnitSelector, etc.)
- **pages/**: Main application pages (HomePage, GamePage, ReplayPage)
- **data/**: Game logic and data management
- **roster/**: Unit definitions and stats
- **ai/**: Frontend integration with AI backend

### AI Backend (`/ai/`)
- **agent.py**: Main AI agent logic
- **gym40k.py**: Gymnasium environment for training
- **api.py**: FastAPI endpoints for frontend communication
- **model.py**: Neural network architectures

### Development Tools (`/tools/`)
- **backup_script.py**: Project versioning and backup
- **generate_scenario.py**: Scenario generation utilities

## Build Commands

```bash
# Frontend development
cd frontend
npm run dev

# Frontend build
cd frontend
npm run build

# AI backend
cd ai
python api.py
```

## Path Aliases

TypeScript path aliases are configured for cleaner imports:

- `@/` → `frontend/src/`
- `@components/` → `frontend/src/components/`
- `@data/` → `frontend/src/data/`
- `@roster/` → `frontend/src/roster/`
- `@pages/` → `frontend/src/pages/`
- `@ai/` → `ai/`
'''

        with open(docs_dir / "project_structure.md", 'w', encoding='utf-8') as f:
            f.write(structure_doc)
            
        self.log("Created project structure documentation")
        
    def run_cleanup(self):
        """Run the complete cleanup process"""
        self.log("Starting Warhammer 40k project cleanup...")
        self.log(f"Working directory: {self.project_root}")
        
        try:
            # Step 1: Create backup
            self.create_backup()
            
            # Step 2: Remove unnecessary files
            self.remove_unnecessary_files()
            
            # Step 3: Complete migration
            self.migrate_remaining_src_files()
            
            # Step 4: Fix TypeScript configs
            self.fix_typescript_configs()
            
            # Step 5: Reorganize development tools
            self.reorganize_development_tools()
            
            # Step 6: Create improved .gitignore
            self.create_improved_gitignore()
            
            # Step 7: Create documentation
            self.create_project_structure_doc()
            
            self.log("✅ Project cleanup completed successfully!")
            self.log("\nNext steps:")
            self.log("1. Review the changes in your IDE")
            self.log("2. Test that the frontend builds: cd frontend && npm run build")
            self.log("3. Update any remaining import paths if needed")
            self.log("4. Remove the backup_before_cleanup/ directory when satisfied")
            
        except Exception as e:
            self.log(f"❌ Error during cleanup: {e}", "ERROR")
            if self.backup_created:
                self.log("Your original files are backed up in backup_before_cleanup/")
            raise

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Clean up and reorganize Warhammer 40k project")
    parser.add_argument("--project-root", default=".", help="Project root directory (default: current directory)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    
    args = parser.parse_args()
    
    if args.dry_run:
        print("DRY RUN MODE - No changes will be made")
        print("This would:")
        print("- Create backup of current state")
        print("- Remove unnecessary files (build artifacts, generic templates)")
        print("- Complete migration from /src to /frontend/src")
        print("- Fix TypeScript configuration files")
        print("- Move development tools to /tools directory")
        print("- Create clean .gitignore")
        print("- Generate project documentation")
        return
    
    # Confirm before proceeding
    print("This script will reorganize your Warhammer 40k project structure.")
    print("A backup will be created before making any changes.")
    response = input("Continue? (y/N): ")
    
    if response.lower() not in ['y', 'yes']:
        print("Cancelled.")
        return
        
    cleaner = ProjectCleaner(args.project_root)
    cleaner.run_cleanup()

if __name__ == "__main__":
    main()