# scripts/backup_block.py
"""
WH40K Tactics RL Project Backup Script - Clean filenames without path prefixes
Creates timestamped backups with clean file names and repository documentation
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

# Try to load config.json (if it exists)
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    ROOT = config.get("ROOT")
    DEST_ROOT = config.get("DEST_ROOT")
    files_to_copy = config.get("files_to_copy")
else:
    # Find project root automatically
    def find_project_root():
        current = Path(__file__).resolve().parent.parent  # Go up from scripts/
        key_files = ["config_loader.py", "tsconfig.json", "AI_INSTRUCTIONS.md"]
        
        for _ in range(3):  # Check up to 3 levels up
            if all((current / file).exists() for file in key_files):
                return str(current)
            current = current.parent
        
        return os.getcwd()  # Fallback

    ROOT = os.environ.get("PROJECT_ROOT", find_project_root())
    
    # Create timestamped backup directory in backup/ folder
    #timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    #backup_name = f"backup_{timestamp}"
    backup_name = f"backup"
    DEST_ROOT = os.path.join(ROOT, "backup", backup_name)
    
    # Complete file list for flat structure backup
    files_to_copy = [
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
        "frontend/src/App.css",
        "frontend/src/index.css",

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
    ]

###########################################################################################
### BACKUP FUNCTIONS  
###########################################################################################

def create_flat_backup() -> Dict[str, Any]:
    """Create backup with flat file structure"""
    
    print(f"🔄 Starting backup with flat structure...")
    print(f"📁 Source: {ROOT}")
    print(f"📁 Destination: {DEST_ROOT}")
    
    # Create backup directory
    os.makedirs(DEST_ROOT, exist_ok=True)
    
    # Track results
    results = {
        "timestamp": datetime.datetime.now().isoformat(),
        "source_root": ROOT,
        "backup_root": DEST_ROOT,
        "files_copied": [],
        "files_failed": [],
        "total_size": 0,
        "file_mapping": {}  # Track original path -> backup filename mapping
    }
    
    # Copy files with flat structure
    for file_rel in files_to_copy:
        src = os.path.join(ROOT, file_rel)
        
        if not os.path.exists(src):
            print(f"⚠️  Source missing: {file_rel}")
            results["files_failed"].append({
                "file": file_rel,
                "reason": "source_not_found", 
                "src": src
            })
            continue
        
        # Create clean filename by taking only the actual filename (no path prefixes)
        backup_filename = os.path.basename(file_rel)
        
        # Handle potential filename conflicts by adding incremental numbers
        original_backup_filename = backup_filename
        counter = 1
        while os.path.exists(os.path.join(DEST_ROOT, backup_filename)):
            name, ext = os.path.splitext(original_backup_filename)
            backup_filename = f"{name}_{counter}{ext}"
            counter += 1
        
        dest = os.path.join(DEST_ROOT, backup_filename)
        
        try:
            # Copy file to flat structure
            shutil.copy2(src, dest)
            file_size = os.path.getsize(dest)
            results["total_size"] += file_size
            results["files_copied"].append({
                "file": file_rel,
                "backup_filename": backup_filename,
                "size": file_size,
                "src": src,
                "dest": dest
            })
            results["file_mapping"][file_rel] = backup_filename
            print(f"✅ Copied: {file_rel} -> {backup_filename}")
            
        except Exception as e:
            print(f"❌ Failed: {file_rel} - {e}")
            results["files_failed"].append({
                "file": file_rel, 
                "reason": str(e),
                "src": src,
                "dest": dest
            })
    
    return results

def generate_structure_documentation(results: Dict[str, Any]) -> str:
    """Generate backup_block_README.md file documenting the actual repository structure"""
    
    print(f"📋 Generating repository structure documentation...")
    
    structure_content = []
    structure_content.append("# WH40K Tactics RL - Repository Structure at Backup Time")
    structure_content.append("")
    structure_content.append("## Overview")
    structure_content.append("This document shows the actual repository structure at the time of backup.")
    structure_content.append("Files are saved with clean names (no path prefixes), and their original locations are documented below.")
    structure_content.append("")
    structure_content.append(f"**Backup created:** {results['timestamp']}")
    structure_content.append(f"**Source directory:** {results['source_root']}")
    structure_content.append(f"**Files backed up:** {len(results['files_copied'])}")
    structure_content.append("")
    
    # Scan actual repository structure
    structure_content.append("## 📁 Actual Repository Structure")
    structure_content.append("")
    structure_content.append("```")
    
    def scan_directory(path: str, prefix: str = "", max_depth: int = 4, current_depth: int = 0) -> List[str]:
        """Recursively scan directory structure"""
        items = []
        if current_depth >= max_depth:
            return items
            
        try:
            entries = sorted(os.listdir(path))
            dirs = [e for e in entries if os.path.isdir(os.path.join(path, e))]
            files = [e for e in entries if os.path.isfile(os.path.join(path, e))]
            
            # Filter out ignored directories and files
            ignored_dirs = {'.git', 'node_modules', 'dist', 'build', '__pycache__', 
                          '.vscode', '.idea', 'tensorboard', 'ai/models', 'ai/event_log', 
                          'backup', 'versions', 'temp', 'cache', '.venv', 'Lib'}
            ignored_files = {'.DS_Store', 'Thumbs.db', '*.pyc', '*.log', '*.tmp'}
            
            dirs = [d for d in dirs if d not in ignored_dirs]
            files = [f for f in files if not any(f.endswith(pattern.replace('*', '')) for pattern in ignored_files)]
            
            # Add directories
            for i, dir_name in enumerate(dirs):
                is_last_dir = i == len(dirs) - 1 and len(files) == 0
                dir_prefix = "└── " if is_last_dir else "├── "
                items.append(f"{prefix}{dir_prefix}📂 {dir_name}/")
                
                # Recurse into directory
                next_prefix = prefix + ("    " if is_last_dir else "│   ")
                subpath = os.path.join(path, dir_name)
                items.extend(scan_directory(subpath, next_prefix, max_depth, current_depth + 1))
            
            # Add files
            for i, file_name in enumerate(files):
                is_last = i == len(files) - 1
                file_prefix = "└── " if is_last else "├── "
                items.append(f"{prefix}{file_prefix}📄 {file_name}")
                
        except PermissionError:
            items.append(f"{prefix}└── ❌ Permission denied")
        except Exception as e:
            items.append(f"{prefix}└── ❌ Error: {e}")
            
        return items
    
    # Scan from project root
    root_name = os.path.basename(ROOT) or "wh40k-tactics"
    structure_content.append(f"{root_name}/")
    structure_lines = scan_directory(ROOT)
    structure_content.extend(structure_lines)
    structure_content.append("```")
    structure_content.append("")
    
    # Add file mapping section with repository information
    structure_content.append("## 📋 File Mapping (Backup Filename ← Original Location)")
    structure_content.append("")
    structure_content.append("Files are saved with clean names. This table shows where each backup file originally came from:")
    structure_content.append("")
    structure_content.append("| Backup Filename | Original Repository Path | Repository |")
    structure_content.append("|-----------------|--------------------------|------------|")
    
    for original_path, backup_filename in results.get("file_mapping", {}).items():
        # Determine repository/section
        if original_path.startswith("ai/"):
            repository = "🤖 AI Backend"
        elif original_path.startswith("config/"):
            repository = "⚙️ Configuration"
        elif original_path.startswith("frontend/src/components/"):
            repository = "🎮 Frontend Components"
        elif original_path.startswith("frontend/src/hooks/"):
            repository = "🪝 Frontend Hooks"
        elif original_path.startswith("frontend/src/pages/"):
            repository = "📄 Frontend Pages"
        elif original_path.startswith("frontend/src/roster/"):
            repository = "⚔️ Unit Roster"
        elif original_path.startswith("frontend/src/"):
            repository = "🎮 Frontend Core"
        elif original_path.startswith("frontend/public/"):
            repository = "📁 Frontend Public"
        elif original_path.startswith("frontend/"):
            repository = "🎮 Frontend Config"
        elif original_path.startswith("scripts/"):
            repository = "🛠️ Scripts"
        else:
            repository = "📂 Project Root"
            
        structure_content.append(f"| `{backup_filename}` | `{original_path}` | {repository} |")
    
    structure_content.append("")
    
    # Add repository sections
    structure_content.append("## 🗂️ Repository Sections")
    structure_content.append("")
    
    # Group files by repository
    repositories = {}
    for original_path, backup_filename in results.get("file_mapping", {}).items():
        if original_path.startswith("ai/"):
            repo_key = "🤖 AI Backend"
        elif original_path.startswith("config/"):
            repo_key = "⚙️ Configuration"
        elif original_path.startswith("frontend/src/components/"):
            repo_key = "🎮 Frontend Components"
        elif original_path.startswith("frontend/src/hooks/"):
            repo_key = "🪝 Frontend Hooks"
        elif original_path.startswith("frontend/src/pages/"):
            repo_key = "📄 Frontend Pages"
        elif original_path.startswith("frontend/src/roster/"):
            repo_key = "⚔️ Unit Roster"
        elif original_path.startswith("frontend/src/"):
            repo_key = "🎮 Frontend Core"
        elif original_path.startswith("frontend/"):
            repo_key = "🎮 Frontend Config"
        elif original_path.startswith("scripts/"):
            repo_key = "🛠️ Scripts"
        else:
            repo_key = "📂 Project Root"
            
        if repo_key not in repositories:
            repositories[repo_key] = []
        repositories[repo_key].append((backup_filename, original_path))
    
    for repo_name, files in repositories.items():
        structure_content.append(f"### {repo_name}")
        structure_content.append("")
        for backup_filename, original_path in sorted(files):
            structure_content.append(f"- **`{backup_filename}`** ← `{original_path}`")
        structure_content.append("")
    
    # Add backup statistics
    structure_content.append("## 📊 Backup Statistics")
    structure_content.append("")
    structure_content.append(f"- **Total files copied:** {len(results['files_copied'])}")
    structure_content.append(f"- **Total files failed:** {len(results['files_failed'])}")
    structure_content.append(f"- **Total size:** {round(results['total_size'] / (1024 * 1024), 2)} MB")
    
    if results['files_failed']:
        structure_content.append("")
        structure_content.append("### ⚠️ Failed Files")
        for failed in results['files_failed']:
            structure_content.append(f"- `{failed['file']}`: {failed['reason']}")
    
    structure_content.append("")
    structure_content.append("## 🔄 Restoration Guide")
    structure_content.append("")
    structure_content.append("To restore files to their original locations:")
    structure_content.append("")
    structure_content.append("```bash")
    structure_content.append("# Use the restore script")
    structure_content.append("python scripts/restore_block.py backup/backup_TIMESTAMP.zip")
    structure_content.append("")
    structure_content.append("# Or manually restore specific files:")
    for original_path, backup_filename in list(results.get("file_mapping", {}).items())[:5]:  # Show first 5 examples
        dir_path = os.path.dirname(original_path)
        if dir_path:
            structure_content.append(f"# mkdir -p {dir_path}")
            structure_content.append(f"# cp {backup_filename} {original_path}")
        else:
            structure_content.append(f"# cp {backup_filename} {original_path}")
    structure_content.append("```")
    
    # Write structure file
    structure_file = os.path.join(DEST_ROOT, "backup_block_README.md")
    with open(structure_file, "w", encoding="utf-8") as f:
        f.write("\n".join(structure_content))
    
    print(f"✅ Structure documentation created: {structure_file}")
    return structure_file

def generate_tree_snapshot() -> str:
    """Generate _backup_structure.md file with repository tree snapshot"""
    
    print(f"🌳 Generating repository tree snapshot...")
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    tree_content = []
    tree_content.append("# WH40K Tactics RL - Repository Tree Snapshot")
    tree_content.append("")
    tree_content.append(f"**Snapshot taken:** {timestamp}")
    tree_content.append(f"**Source directory:** {ROOT}")
    tree_content.append("")
    tree_content.append("This file contains a complete snapshot of the repository structure at backup time.")
    tree_content.append("")
    
    def scan_directory_complete(path: str, prefix: str = "", max_depth: int = 6, current_depth: int = 0) -> List[str]:
        """Recursively scan directory structure with more depth for complete snapshot"""
        items = []
        if current_depth >= max_depth:
            return items
            
        try:
            entries = sorted(os.listdir(path))
            dirs = [e for e in entries if os.path.isdir(os.path.join(path, e))]
            files = [e for e in entries if os.path.isfile(os.path.join(path, e))]
            
            # Filter out ignored directories but keep more for snapshot
            ignored_dirs = {'.git', '__pycache__', '.vscode', '.idea', '.venv', 'Lib'}
            # Note: We include more directories in snapshot (like node_modules, dist) to show complete structure
            # but mark them specially
            
            special_dirs = {'node_modules', 'dist', 'build', 'tensorboard', 'backup', 'versions', 'temp', 'cache'}
            
            # Filter out only critical ignored dirs
            dirs = [d for d in dirs if d not in ignored_dirs]
            
            # Filter files
            ignored_files = {'.DS_Store', 'Thumbs.db'}
            files = [f for f in files if f not in ignored_files and not f.endswith('.pyc')]
            
            # Add directories
            for i, dir_name in enumerate(dirs):
                is_last_dir = i == len(dirs) - 1 and len(files) == 0
                dir_prefix = "└── " if is_last_dir else "├── "
                
                # Mark special directories
                if dir_name in special_dirs:
                    items.append(f"{prefix}{dir_prefix}📂 {dir_name}/ (generated/ignored)")
                    # Don't recurse into these directories to keep snapshot clean
                else:
                    items.append(f"{prefix}{dir_prefix}📂 {dir_name}/")
                    
                    # Recurse into regular directories
                    next_prefix = prefix + ("    " if is_last_dir else "│   ")
                    subpath = os.path.join(path, dir_name)
                    items.extend(scan_directory_complete(subpath, next_prefix, max_depth, current_depth + 1))
            
            # Add files
            for i, file_name in enumerate(files):
                is_last = i == len(files) - 1
                file_prefix = "└── " if is_last else "├── "
                
                # Get file size for information
                try:
                    file_path = os.path.join(path, file_name)
                    file_size = os.path.getsize(file_path)
                    if file_size > 1024 * 1024:  # > 1MB
                        size_info = f" ({round(file_size / (1024 * 1024), 1)}MB)"
                    elif file_size > 1024:  # > 1KB
                        size_info = f" ({round(file_size / 1024, 1)}KB)"
                    else:
                        size_info = ""
                    
                    items.append(f"{prefix}{file_prefix}📄 {file_name}{size_info}")
                except:
                    items.append(f"{prefix}{file_prefix}📄 {file_name}")
                
        except PermissionError:
            items.append(f"{prefix}└── ❌ Permission denied")
        except Exception as e:
            items.append(f"{prefix}└── ❌ Error: {e}")
            
        return items
    
    # Generate complete tree
    tree_content.append("## 📁 Complete Repository Tree")
    tree_content.append("")
    tree_content.append("```")
    
    root_name = os.path.basename(ROOT) or "wh40k-tactics"
    tree_content.append(f"{root_name}/")
    tree_lines = scan_directory_complete(ROOT)
    tree_content.extend(tree_lines)
    
    tree_content.append("```")
    tree_content.append("")
    
    # Add legend
    tree_content.append("## 📖 Legend")
    tree_content.append("")
    tree_content.append("- 📂 **Directory**")
    tree_content.append("- 📄 **File** (with size if > 1KB)")
    tree_content.append("- **(generated/ignored)** - Directories typically not included in backups")
    tree_content.append("")
    
    # Add summary stats
    try:
        total_files = 0
        total_dirs = 0
        total_size = 0
        
        for root, dirs, files in os.walk(ROOT):
            # Skip ignored directories
            dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', '.vscode', '.idea', 'node_modules', 'dist', '.venv', 'Lib'}]
            
            total_dirs += len(dirs)
            for file in files:
                if not file.endswith('.pyc') and file not in {'.DS_Store', 'Thumbs.db'}:
                    total_files += 1
                    try:
                        file_path = os.path.join(root, file)
                        total_size += os.path.getsize(file_path)
                    except:
                        pass
        
        tree_content.append("## 📊 Repository Statistics")
        tree_content.append("")
        tree_content.append(f"- **Total directories:** {total_dirs}")
        tree_content.append(f"- **Total files:** {total_files}")
        tree_content.append(f"- **Total size:** {round(total_size / (1024 * 1024), 1)} MB")
        tree_content.append("")
        
    except Exception as e:
        tree_content.append(f"## ⚠️ Could not calculate statistics: {e}")
        tree_content.append("")
    
    tree_content.append("---")
    tree_content.append("")
    tree_content.append(f"*Generated on {timestamp} by backup_block.py*")
    
    # Write tree snapshot file
    tree_file = os.path.join(DEST_ROOT, "_backup_structure.md")
    with open(tree_file, "w", encoding="utf-8") as f:
        f.write("\n".join(tree_content))
    
    print(f"✅ Tree snapshot created: {tree_file}")
    return tree_file

def create_backup_metadata(results: Dict[str, Any]) -> str:
    """Create backup metadata file"""
    metadata_file = os.path.join(DEST_ROOT, "backup_metadata.json")
    
    # Add summary
    results["summary"] = {
        "total_files_attempted": len(results["files_copied"]) + len(results["files_failed"]),
        "files_copied_count": len(results["files_copied"]), 
        "files_failed_count": len(results["files_failed"]),
        "total_size_mb": round(results["total_size"] / (1024 * 1024), 2),
        "success_rate": round(len(results["files_copied"]) / max(1, len(results["files_copied"]) + len(results["files_failed"])) * 100, 1)
    }
    
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    return metadata_file

def create_zip_archive() -> str:
    """Create zip archive of backup preserving flat structure"""
    zip_path = f"{DEST_ROOT}.zip"
    
    print(f"📦 Creating zip archive: {zip_path}")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipf:
        backup_path = Path(DEST_ROOT)
        
        for file_path in backup_path.rglob('*'):
            if file_path.is_file():
                # Preserve flat structure in zip
                arc_path = file_path.relative_to(backup_path)
                zipf.write(file_path, arc_path)
                
    zip_size = os.path.getsize(zip_path)
    print(f"✅ Zip created: {zip_path} ({round(zip_size / (1024 * 1024), 2)} MB)")
    
    return zip_path

###########################################################################################
### MAIN EXECUTION
###########################################################################################

def main():
    """Main backup execution"""
    try:
        print("=" * 80)
        print("🚀 WH40K Tactics RL - Complete Project Backup")
        print("=" * 80)
        
        # Create flat backup
        results = create_flat_backup()
        
        # Generate structure documentation
        structure_file = generate_structure_documentation(results)
        
        # Generate repository tree snapshot
        tree_snapshot_file = generate_tree_snapshot()
        
        # Create metadata
        metadata_file = create_backup_metadata(results)
        print(f"📋 Metadata saved: {metadata_file}")
        
        # Create zip archive
        zip_path = create_zip_archive()
        
        # Print summary
        print("\n" + "=" * 80)
        print(f"📊 BACKUP SUMMARY")
        print("=" * 80)
        summary = results["summary"]
        print(f"✅ Files copied: {summary['files_copied_count']}")
        print(f"❌ Files failed: {summary['files_failed_count']}")
        print(f"💾 Total size: {summary['total_size_mb']} MB")
        print(f"📈 Success rate: {summary['success_rate']}%")
        print(f"📦 Zip archive: {zip_path}")
        print(f"📋 Metadata: {metadata_file}")
        print(f"📋 Structure doc: {structure_file}")
        print(f"📋 Tree snapshot: {tree_snapshot_file}")
        print(f"📁 Backup structure: Clean filenames (no path prefixes)")
        
        if summary['files_failed_count'] > 0:
            print(f"\n⚠️  {summary['files_failed_count']} files failed to copy:")
            for failed in results["files_failed"]:
                print(f"   - {failed['file']}: {failed['reason']}")
        
        print(f"\n🎯 Backup completed successfully!")
        print(f"📁 Backup directory: {DEST_ROOT}")
        print(f"📦 Zip archive: {zip_path}")
        print(f"🗂️  File structure: Clean filenames with backup_block_README.md documentation")
        print(f"🌳 Tree snapshot: _backup_structure.md contains complete repository tree")
        
        return zip_path
        
    except Exception as e:
        print(f"\n❌ Backup failed: {e}")
        raise

if __name__ == "__main__":
    main()