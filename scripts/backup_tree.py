# scripts/complete_backup.py
"""
Complete WH40K Tactics RL Project Backup Script
Creates timestamped backups with full project structure
"""

import os
import shutil
import datetime
import json
import zipfile
from pathlib import Path
from typing import List, Dict, Any

###########################################################################################
### CONFIGURATION
###########################################################################################

class BackupConfig:
    def __init__(self, config_file: str = None):
        self.version = "v3_complete"
        
        # Try to load from config file first
        if config_file and os.path.exists(config_file):
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
            self.root = config.get("ROOT")
            self.dest_root = config.get("DEST_ROOT") 
            self.files_to_copy = config.get("files_to_copy", [])
        else:
            # Environment variables or defaults
            self.root = os.environ.get("PROJECT_ROOT", self._find_project_root())
            
            # Create timestamped backup directory in backup/ folder
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"backup_{timestamp}"
            self.dest_root = os.path.join(self.root, "backup", backup_name)
            
            # Complete file list based on updated project structure
            self.files_to_copy = self._get_complete_file_list()
    
    def _find_project_root(self) -> str:
        """Auto-detect project root by looking for key files"""
        current = Path(__file__).resolve().parent.parent  # Go up from scripts/
        key_files = ["config_loader.py", "tsconfig.json", "AI_INSTRUCTIONS.md"]
        
        for _ in range(3):  # Check up to 3 levels up
            if all((current / file).exists() for file in key_files):
                return str(current)
            current = current.parent
        
        # Fallback to current directory
        return os.getcwd()
    
    def _get_complete_file_list(self) -> List[str]:
        """Complete file list based on updated project structure"""
        return [
            # Root files
            "config_loader.py",
            "tsconfig.json", 
            ".gitignore",
            "AI_INSTRUCTIONS.md",
            "ps.ps1",

            # AI Backend files
            "ai/api.py",
            "ai/diagnose.py", 
            "ai/evaluate.py",
            "ai/generate_scenario.py",
            "ai/gym40k.py",
            "ai/reward_mapper.py",
            "ai/scenario.json",
            "ai/state.py",
            "ai/train.py",
            "ai/web_replay_logger.py",

            # Configuration files
            "config/config.json",
            "config/game_config.json",
            "config/training_config.json", 
            "config/rewards_config.json",
            "config/board_config.json",
            "config/scenario.json",
            "config/unit_definitions.json",
            "config/action_definitions.json",

            # Scripts
            "scripts/backup_script.py",
            "scripts/copy-configs.js",

            # Frontend package files
            "frontend/package.json",
            "frontend/tsconfig.json", 
            "frontend/vite.config.ts",
            "frontend/eslint.config.js",

            # Frontend public configs
            "frontend/public/config/config.json",
            "frontend/public/config/board_config.json",
            "frontend/public/config/game_config.json",
            "frontend/public/config/scenario.json",
            "frontend/public/config/unit_definitions.json",
            "frontend/public/config/action_definitions.json",

            # Frontend source - Core
            "frontend/src/App.tsx",
            "frontend/src/main.tsx", 
            "frontend/src/routes.tsx",

            # Frontend components
            "frontend/src/components/Board.tsx",
            "frontend/src/components/ErrorBoundary.tsx",
            "frontend/src/components/GameBoard.tsx", 
            "frontend/src/components/GameController.tsx",
            "frontend/src/components/GameStatus.tsx",
            "frontend/src/components/ReplayViewer.tsx",
            "frontend/src/components/ReplayBoard.tsx",
            "frontend/src/components/UnitSelector.tsx",

            # Frontend data
            "frontend/src/data/Units.ts",
            "frontend/src/data/UnitFactory.ts",
            "frontend/src/data/Scenario.ts",

            # Frontend hooks
            "frontend/src/hooks/useAIPlayer.ts",
            "frontend/src/hooks/useGameActions.ts", 
            "frontend/src/hooks/useGameConfig.ts",
            "frontend/src/hooks/useGameState.ts",
            "frontend/src/hooks/usePhaseTransition.ts",

            # Frontend pages
            "frontend/src/pages/HomePage.tsx",
            "frontend/src/pages/GamePage.tsx",
            "frontend/src/pages/ReplayPage.tsx",

            # Frontend roster
            "frontend/src/roster/spaceMarine/SpaceMarineRangedUnit.ts",
            "frontend/src/roster/spaceMarine/SpaceMarineMeleeUnit.ts", 
            "frontend/src/roster/spaceMarine/Intercessor.ts",
            "frontend/src/roster/spaceMarine/AssaultIntercessor.ts",

            # Frontend services
            "frontend/src/services/aiService.ts",

            # Frontend types (if they exist)
            "frontend/src/types/game.ts",

            # Frontend constants
            "frontend/src/constants/gameConfig.ts",

            # CSS files
            "frontend/src/App.css",
            "frontend/src/index.css",
        ]

###########################################################################################
### BACKUP FUNCTIONS  
###########################################################################################

def create_backup(config: BackupConfig) -> Dict[str, Any]:
    """Create complete project backup"""
    
    print(f"🔄 Starting complete backup...")
    print(f"📁 Source: {config.root}")
    print(f"📁 Destination: {config.dest_root}")
    
    # Create backup directory
    os.makedirs(config.dest_root, exist_ok=True)
    
    # Track results
    results = {
        "timestamp": datetime.datetime.now().isoformat(),
        "source_root": config.root,
        "backup_root": config.dest_root,
        "files_copied": [],
        "files_failed": [],
        "directories_created": [],
        "total_size": 0
    }
    
    # Copy files
    for file_rel in config.files_to_copy:
        src = os.path.join(config.root, file_rel)
        dest = os.path.join(config.dest_root, file_rel)
        dest_dir = os.path.dirname(dest)
        
        if not os.path.exists(src):
            print(f"⚠️  Source missing: {file_rel}")
            results["files_failed"].append({
                "file": file_rel,
                "reason": "source_not_found", 
                "src": src
            })
            continue
            
        # Create destination directory
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)
            if dest_dir not in results["directories_created"]:
                results["directories_created"].append(dest_dir)
        
        try:
            # Copy file
            shutil.copy2(src, dest)
            file_size = os.path.getsize(dest)
            results["total_size"] += file_size
            results["files_copied"].append({
                "file": file_rel,
                "size": file_size,
                "src": src,
                "dest": dest
            })
            print(f"✅ Copied: {file_rel}")
            
        except Exception as e:
            print(f"❌ Failed: {file_rel} - {e}")
            results["files_failed"].append({
                "file": file_rel, 
                "reason": str(e),
                "src": src,
                "dest": dest
            })
    
    return results

def create_backup_metadata(results: Dict[str, Any], dest_root: str) -> str:
    """Create backup metadata file"""
    metadata_file = os.path.join(dest_root, "backup_metadata.json")
    
    # Add summary
    results["summary"] = {
        "total_files_attempted": len(results["files_copied"]) + len(results["files_failed"]),
        "files_copied_count": len(results["files_copied"]), 
        "files_failed_count": len(results["files_failed"]),
        "directories_created_count": len(results["directories_created"]),
        "total_size_mb": round(results["total_size"] / (1024 * 1024), 2),
        "success_rate": round(len(results["files_copied"]) / max(1, len(results["files_copied"]) + len(results["files_failed"])) * 100, 1)
    }
    
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    return metadata_file

def create_zip_archive(backup_dir: str) -> str:
    """Create zip archive of backup preserving exact file structure"""
    # Extract timestamp from backup directory name
    backup_name = os.path.basename(backup_dir)  # e.g., "backup_20250712_143022"
    zip_path = f"{backup_dir}.zip"  # e.g., "backup/backup_20250712_143022.zip"
    
    print(f"📦 Creating zip archive: {zip_path}")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipf:
        backup_path = Path(backup_dir)
        
        for file_path in backup_path.rglob('*'):
            if file_path.is_file():
                # Preserve exact file structure in zip (relative to backup directory)
                arc_path = file_path.relative_to(backup_path)
                zipf.write(file_path, arc_path)
                
    zip_size = os.path.getsize(zip_path)
    print(f"✅ Zip created: {zip_path} ({round(zip_size / (1024 * 1024), 2)} MB)")
    
    return zip_path

def cleanup_uncompressed_backup(backup_dir: str, keep_compressed: bool = True):
    """Optionally remove uncompressed backup after zipping"""
    if keep_compressed:
        print(f"📁 Keeping uncompressed backup: {backup_dir}")
        return
        
    try:
        shutil.rmtree(backup_dir)
        print(f"🗑️  Removed uncompressed backup: {backup_dir}")
    except Exception as e:
        print(f"⚠️  Failed to remove uncompressed backup: {e}")

###########################################################################################
### MAIN EXECUTION
###########################################################################################

def main():
    """Main backup execution"""
    try:
        # Initialize configuration
        config_file = os.path.join(os.path.dirname(__file__), "backup_config.json")
        config = BackupConfig(config_file if os.path.exists(config_file) else None)
        
        print("=" * 80)
        print("🚀 WH40K Tactics RL - Complete Project Backup")
        print("=" * 80)
        
        # Create backup
        results = create_backup(config)
        
        # Create metadata
        metadata_file = create_backup_metadata(results, config.dest_root)
        print(f"📋 Metadata saved: {metadata_file}")
        
        # Create zip archive
        zip_path = create_zip_archive(config.dest_root)
        
        # Optionally cleanup (keep both by default for safety)
        # cleanup_uncompressed_backup(config.dest_root, keep_compressed=True)
        
        # Print summary
        print("\n" + "=" * 80)
        print("📊 BACKUP SUMMARY")
        print("=" * 80)
        summary = results["summary"]
        print(f"✅ Files copied: {summary['files_copied_count']}")
        print(f"❌ Files failed: {summary['files_failed_count']}")
        print(f"📁 Directories created: {summary['directories_created_count']}")
        print(f"💾 Total size: {summary['total_size_mb']} MB")
        print(f"📈 Success rate: {summary['success_rate']}%")
        print(f"📦 Zip archive: {zip_path}")
        print(f"📋 Metadata: {metadata_file}")
        
        if summary['files_failed_count'] > 0:
            print(f"\n⚠️  {summary['files_failed_count']} files failed to copy:")
            for failed in results["files_failed"]:
                print(f"   - {failed['file']}: {failed['reason']}")
        
        print(f"\n🎯 Backup completed successfully!")
        print(f"📁 Backup location: {config.dest_root}")
        print(f"📦 Zip archive: {zip_path}")
        
        return zip_path
        
    except Exception as e:
        print(f"\n❌ Backup failed: {e}")
        raise

if __name__ == "__main__":
    main()