# scripts/restore_backup.py
"""
Complete WH40K Tactics RL Project Restore Script
Restores from timestamped backups or zip archives
"""

import os
import shutil
import json
import zipfile
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional
import datetime

###########################################################################################
### RESTORE CONFIGURATION
###########################################################################################

class RestoreConfig:
    def __init__(self, backup_path: str, target_root: str = None):
        self.backup_path = backup_path
        self.target_root = target_root or self._find_project_root()
        self.metadata = None
        self.is_zip = backup_path.endswith('.zip')
        
        # Validation
        if not os.path.exists(backup_path):
            raise FileNotFoundError(f"Backup not found: {backup_path}")
    
    def _find_project_root(self) -> str:
        """Auto-detect project root by looking for key files"""
        current = Path(__file__).resolve().parent.parent  # Go up from scripts/
        key_files = ["config_loader.py", "tsconfig.json"]
        
        for _ in range(3):  # Check up to 3 levels up
            if any((current / file).exists() for file in key_files):
                return str(current)
            current = current.parent
        
        # Fallback to current directory
        return os.getcwd()
    
    def load_metadata(self, temp_dir: str = None) -> Optional[Dict[str, Any]]:
        """Load backup metadata if available"""
        metadata_file = None
        
        if self.is_zip:
            # Extract metadata from zip
            if temp_dir:
                metadata_file = os.path.join(temp_dir, "backup_metadata.json")
        else:
            # Direct access to metadata
            metadata_file = os.path.join(self.backup_path, "backup_metadata.json")
        
        if metadata_file and os.path.exists(metadata_file):
            try:
                with open(metadata_file, "r", encoding="utf-8") as f:
                    self.metadata = json.load(f)
                return self.metadata
            except Exception as e:
                print(f"⚠️  Could not load metadata: {e}")
        
        return None

###########################################################################################
### RESTORE FUNCTIONS
###########################################################################################

def extract_zip_backup(zip_path: str, temp_dir: str) -> str:
    """Extract zip backup to temporary directory"""
    print(f"📦 Extracting zip backup: {zip_path}")
    
    os.makedirs(temp_dir, exist_ok=True)
    
    with zipfile.ZipFile(zip_path, 'r') as zipf:
        zipf.extractall(temp_dir)
    
    # The files are extracted directly preserving the original structure
    print(f"✅ Extracted to: {temp_dir}")
    return temp_dir

def validate_backup_structure(backup_dir: str) -> Dict[str, Any]:
    """Validate backup contains expected files"""
    validation_results = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "found_files": [],
        "missing_critical": []
    }
    
    # Critical files that should exist
    critical_files = [
        "config_loader.py",
        "ai/gym40k.py", 
        "ai/train.py",
        "frontend/src/App.tsx",
        "config/config.json"
    ]
    
    print(f"🔍 Validating backup structure...")
    
    for critical_file in critical_files:
        file_path = os.path.join(backup_dir, critical_file)
        if os.path.exists(file_path):
            validation_results["found_files"].append(critical_file)
        else:
            validation_results["missing_critical"].append(critical_file)
            validation_results["errors"].append(f"Missing critical file: {critical_file}")
    
    # Check for backup metadata
    metadata_file = os.path.join(backup_dir, "backup_metadata.json")
    if os.path.exists(metadata_file):
        validation_results["found_files"].append("backup_metadata.json")
    else:
        validation_results["warnings"].append("No backup metadata found")
    
    # Determine validity
    if validation_results["missing_critical"]:
        validation_results["valid"] = False
        print(f"❌ Backup validation failed: {len(validation_results['missing_critical'])} critical files missing")
    else:
        print(f"✅ Backup validation passed: {len(validation_results['found_files'])} files found")
    
    return validation_results

def create_backup_of_current(target_root: str) -> str:
    """Create backup of current state before restore"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"pre_restore_backup_{timestamp}"
    backup_dir = os.path.join(target_root, "backup", backup_name)
    
    print(f"💾 Creating backup of current state: {backup_dir}")
    
    # Quick backup of critical files only
    critical_files = [
        "config_loader.py",
        "ai/gym40k.py",
        "ai/train.py", 
        "config/config.json",
        "frontend/src/App.tsx"
    ]
    
    os.makedirs(backup_dir, exist_ok=True)
    backed_up = []
    
    for file_rel in critical_files:
        src = os.path.join(target_root, file_rel)
        if os.path.exists(src):
            dest = os.path.join(backup_dir, file_rel)
            dest_dir = os.path.dirname(dest)
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(src, dest)
            backed_up.append(file_rel)
    
    print(f"✅ Pre-restore backup created: {len(backed_up)} files")
    return backup_dir

def restore_files(backup_dir: str, target_root: str, config: RestoreConfig) -> Dict[str, Any]:
    """Restore files from backup to target location"""
    
    print(f"🔄 Starting file restoration...")
    print(f"📁 Source: {backup_dir}")
    print(f"📁 Target: {target_root}")
    
    results = {
        "timestamp": datetime.datetime.now().isoformat(),
        "backup_source": config.backup_path,
        "target_root": target_root,
        "files_restored": [],
        "files_failed": [],
        "files_skipped": [],
        "directories_created": [],
        "total_size": 0
    }
    
    # Walk through all files in backup
    backup_path = Path(backup_dir)
    
    for file_path in backup_path.rglob('*'):
        if file_path.is_file():
            # Calculate relative path
            rel_path = file_path.relative_to(backup_path)
            
            # Skip metadata file
            if rel_path.name == "backup_metadata.json":
                continue
            
            src = str(file_path)
            dest = os.path.join(target_root, str(rel_path))
            dest_dir = os.path.dirname(dest)
            
            try:
                # Create destination directory
                if not os.path.exists(dest_dir):
                    os.makedirs(dest_dir, exist_ok=True)
                    if dest_dir not in results["directories_created"]:
                        results["directories_created"].append(dest_dir)
                
                # Copy file
                shutil.copy2(src, dest)
                file_size = os.path.getsize(dest)
                results["total_size"] += file_size
                results["files_restored"].append({
                    "file": str(rel_path),
                    "size": file_size,
                    "src": src,
                    "dest": dest
                })
                print(f"✅ Restored: {rel_path}")
                
            except Exception as e:
                print(f"❌ Failed: {rel_path} - {e}")
                results["files_failed"].append({
                    "file": str(rel_path),
                    "reason": str(e),
                    "src": src,
                    "dest": dest
                })
    
    return results

def post_restore_validation(target_root: str) -> Dict[str, Any]:
    """Validate installation after restore"""
    print(f"🔍 Post-restore validation...")
    
    validation = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "checks": {}
    }
    
    # Check critical files exist
    critical_files = {
        "config_loader.py": "Configuration loader",
        "ai/gym40k.py": "AI environment", 
        "ai/train.py": "Training script",
        "frontend/package.json": "Frontend dependencies",
        "config/config.json": "Main configuration"
    }
    
    for file_path, description in critical_files.items():
        full_path = os.path.join(target_root, file_path)
        exists = os.path.exists(full_path)
        validation["checks"][description] = exists
        
        if not exists:
            validation["valid"] = False
            validation["errors"].append(f"Missing {description}: {file_path}")
        else:
            print(f"  ✅ {description}")
    
    # Check directory structure
    required_dirs = ["ai", "config", "frontend/src", "scripts"]
    for dir_path in required_dirs:
        full_path = os.path.join(target_root, dir_path)
        exists = os.path.isdir(full_path)
        validation["checks"][f"Directory {dir_path}"] = exists
        
        if not exists:
            validation["warnings"].append(f"Missing directory: {dir_path}")
        else:
            print(f"  ✅ Directory {dir_path}")
    
    if validation["valid"]:
        print("✅ Post-restore validation passed")
    else:
        print("❌ Post-restore validation failed")
    
    return validation

def cleanup_temp_files(temp_dir: str):
    """Clean up temporary extraction directory"""
    if os.path.exists(temp_dir):
        try:
            shutil.rmtree(temp_dir)
            print(f"🗑️  Cleaned up temp directory: {temp_dir}")
        except Exception as e:
            print(f"⚠️  Failed to cleanup temp directory: {e}")

###########################################################################################
### MAIN EXECUTION
###########################################################################################

def main():
    """Main restore execution"""
    parser = argparse.ArgumentParser(description="Restore WH40K Tactics RL project from backup")
    parser.add_argument("backup_path", help="Path to backup directory or zip file")
    parser.add_argument("--target", help="Target directory (auto-detected if not specified)")
    parser.add_argument("--no-backup", action="store_true", help="Skip creating backup of current state")
    parser.add_argument("--force", action="store_true", help="Force restore even if validation fails")
    
    args = parser.parse_args()
    
    try:
        print("=" * 80)
        print("🔄 WH40K Tactics RL - Project Restore")
        print("=" * 80)
        
        # Initialize configuration
        config = RestoreConfig(args.backup_path, args.target)
        
        print(f"📦 Backup source: {config.backup_path}")
        print(f"📁 Target directory: {config.target_root}")
        print(f"📋 Backup type: {'ZIP archive' if config.is_zip else 'Directory'}")
        
        # Handle zip extraction
        temp_dir = None
        if config.is_zip:
            temp_dir = os.path.join(config.target_root, "temp_restore")
            backup_dir = extract_zip_backup(config.backup_path, temp_dir)
        else:
            backup_dir = config.backup_path
        
        # Load metadata
        metadata = config.load_metadata(temp_dir)
        if metadata:
            print(f"📋 Backup metadata loaded: {metadata['summary']['files_copied_count']} files")
        
        # Validate backup
        validation = validate_backup_structure(backup_dir)
        
        if not validation["valid"] and not args.force:
            print("❌ Backup validation failed. Use --force to proceed anyway.")
            if temp_dir:
                cleanup_temp_files(temp_dir)
            return 1
        
        # Create backup of current state
        if not args.no_backup:
            pre_restore_backup = create_backup_of_current(config.target_root)
            print(f"💾 Current state backed up to: {pre_restore_backup}")
        
        # Restore files
        restore_results = restore_files(backup_dir, config.target_root, config)
        
        # Post-restore validation
        post_validation = post_restore_validation(config.target_root)
        
        # Cleanup
        if temp_dir:
            cleanup_temp_files(temp_dir)
        
        # Print summary
        print("\n" + "=" * 80)
        print("📊 RESTORE SUMMARY")
        print("=" * 80)
        print(f"✅ Files restored: {len(restore_results['files_restored'])}")
        print(f"❌ Files failed: {len(restore_results['files_failed'])}")
        print(f"📁 Directories created: {len(restore_results['directories_created'])}")
        print(f"💾 Total size: {round(restore_results['total_size'] / (1024 * 1024), 2)} MB")
        
        if restore_results['files_failed']:
            print(f"\n⚠️  {len(restore_results['files_failed'])} files failed to restore:")
            for failed in restore_results['files_failed']:
                print(f"   - {failed['file']}: {failed['reason']}")
        
        if post_validation["valid"]:
            print(f"\n🎯 Restore completed successfully!")
            print(f"📁 Project restored to: {config.target_root}")
        else:
            print(f"\n⚠️  Restore completed with warnings:")
            for error in post_validation["errors"]:
                print(f"   - {error}")
        
        return 0 if post_validation["valid"] else 1
        
    except Exception as e:
        print(f"\n❌ Restore failed: {e}")
        if temp_dir:
            cleanup_temp_files(temp_dir)
        return 1

if __name__ == "__main__":
    exit(main())