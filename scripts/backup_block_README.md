# WH40K Tactics RL - Backup & Restore System

## Overview
Complete backup and restore system for the WH40K Tactics RL project with timestamped archives and full validation.

## 📁 **Backup Structure**

The system creates backups in your project's `backup/` directory with this structure:

```
wh40k-tactics/
├── 📂 backup/                     # All backups stored here
│   ├── 📂 backup_20250712_143022/ # Uncompressed backup directory
│   │   ├── 📄 gym40k.py           # Clean name: ai/gym40k.py
│   │   ├── 📄 config.json         # Clean name: config/config.json  
│   │   ├── 📄 App.tsx             # Clean name: frontend/src/App.tsx
│   │   ├── 📄 Board.tsx           # Clean name: frontend/src/components/Board.tsx
│   │   ├── 📄 config_loader.py    # Root file: config_loader.py
│   │   ├── 📄 backup_block_README.md     # Repository structure documentation
│   │   ├── 📄 _backup_structure.md       # Complete repository tree snapshot
│   │   └── 📄 backup_metadata.json       # Backup information & file mapping
│   │
│   ├── 📄 backup_20250712_143022.zip # Compressed archive
│   ├── 📄 backup_20250712_150000.zip # Multiple timestamped backups
│   └── 📄 backup_20250713_090000.zip
│
├── ai/                            # Your working files (unchanged)
├── config/
├── frontend/
└── ...
```

### **Key Features:**
- ✅ **Clean filenames** - `gym40k.py` instead of `ai_gym40k.py`
- ✅ **Repository mapping** - `backup_block_README.md` shows where each file belongs
- ✅ **Tree snapshot** - `_backup_structure.md` contains complete repository tree at backup time
- ✅ **Conflict handling** - Duplicate names get incremental numbers (config.json, config_1.json)
- ✅ **Structure documentation** - Complete repository layout preserved
- ✅ **Simple naming** - `backup_YYYYMMDD_HHMMSS.zip`

### **Why Local Instead of Remote Repository?**
1. **Size Concerns**: Includes AI models (can be 50-200MB each)
2. **Speed**: Local backups are much faster for large files
3. **Privacy**: Your development code and trained models stay private
4. **Frequency**: Can backup before each major change without bandwidth concerns
5. **Versioning**: Built-in timestamping provides automatic version control

## 🚀 **Quick Start**

### **Create a Backup**
```bash
# From project root
python scripts/backup_block.py
```

### **Restore from Backup**
```bash
# Restore from zip archive
python scripts/restore_block.py "path/to/backup.zip"

# Restore from directory
python scripts/restore_block.py "path/to/backup_directory"
```

## 📋 **Script Features**

### **Backup Script (`backup_block.py`)**
- ✅ **Auto-detection**: Finds project root automatically
- ✅ **Timestamped**: Creates unique backup names with timestamps
- ✅ **Complete**: Backs up all source files, configs, and documentation
- ✅ **Clean filenames**: Saves files with original names (gym40k.py, not ai_gym40k.py)
- ✅ **Repository documentation**: Creates backup_block_README.md with structure info
- ✅ **Compressed**: Creates ZIP archives for space efficiency
- ✅ **Metadata**: Includes detailed backup information
- ✅ **Validation**: Checks file integrity during backup
- ✅ **Progress**: Real-time progress reporting

### **Restore Script (`restore_block.py`)**
- ✅ **ZIP Support**: Can restore from ZIP archives or directories
- ✅ **Tree-based restoration**: Uses _backup_structure.md to reconstruct file paths
- ✅ **Validation**: Validates backup before and after restore
- ✅ **Safety**: Creates backup of current state before restore
- ✅ **Multiple sources**: Falls back to backup_block_README.md if tree structure unavailable
- ✅ **Verification**: Post-restore integrity checking
- ✅ **Error Handling**: Comprehensive error reporting and recovery
- ✅ **Auto-detection**: Finds project root automatically
- ✅ **Timestamped**: Creates unique backup names with timestamps
- ✅ **Complete**: Backs up all source files, configs, and documentation
- ✅ **Compressed**: Creates ZIP archives for space efficiency
- ✅ **Metadata**: Includes detailed backup information
- ✅ **Validation**: Checks file integrity during backup
- ✅ **Progress**: Real-time progress reporting

### **Restore Script (`restore_backup.py`)**
- ✅ **ZIP Support**: Can restore from ZIP archives or directories
- ✅ **Validation**: Validates backup before and after restore
- ✅ **Safety**: Creates backup of current state before restore
- ✅ **Verification**: Post-restore integrity checking
- ✅ **Error Handling**: Comprehensive error reporting and recovery

## 🛠 **Usage Examples**

### **1. Daily Development Backup**
```bash
# Quick backup before major changes
cd /path/to/wh40k-tactics
python scripts/backup_block.py

# Output:
# ✅ Backup created: backup/backup_20250712_143022.zip
# 📋 Structure doc: backup/backup_20250712_143022/backup_block_README.md
# 🌳 Tree snapshot: backup/backup_20250712_143022/_backup_structure.md
# 🗂️  File structure: Clean filenames with backup_block_README.md documentation
```

### **2. Restore from Backup**
```bash
# List available backups
ls backup/

# Restore specific backup (automatically maps files back to original locations)
python scripts/restore_block.py "backup/backup_20250712_143022.zip"

# View repository structure at backup time
cat backup/backup_20250712_143022/backup_block_README.md

# View complete repository tree snapshot
cat backup/backup_20250712_143022/_backup_structure.md
```

### **3. Manual File Extraction**
```bash
# Extract specific files manually using clean names
unzip backup/backup_20250712_143022.zip

# Check file mapping in README
cat backup_block_README.md  # Shows: gym40k.py ← ai/gym40k.py

# Copy specific file back to original location (easy with clean names!)
cp gym40k.py ../ai/gym40k.py
cp Board.tsx ../frontend/src/components/Board.tsx
```

### **4. Emergency Recovery**
```bash
# Force restore even if validation fails
python scripts/restore_block.py "backup/backup_20250712_143022.zip" --force

# Restore to different location
python scripts/restore_block.py "backup/backup_20250712_143022.zip" --target "/recovery/location"
```" --target "/recovery/location"
```

## ⚙️ **Configuration Options**

### **Custom Backup Configuration**
Create `scripts/backup_config.json`:
```json
{
  "ROOT": "/path/to/project",
  "DEST_ROOT": "/custom/backup/location",
  "files_to_copy": [
    "custom_file.py",
    "additional/directory/*"
  ]
}
```

### **Environment Variables**
```bash
# Set custom project root
export PROJECT_ROOT="/path/to/wh40k-tactics"

# Run backup
python scripts/complete_backup.py
```

## 📊 **Backup Contents**

### **What Gets Backed Up**
```
✅ Source Code
  - All Python AI scripts (ai/*.py)
  - All TypeScript frontend files (frontend/src/**/*.ts, *.tsx)
  - Configuration files (config/*.json)
  - Project management files (package.json, tsconfig.json, etc.)

✅ Documentation
  - Project documentation (docs/*)
  - AI instructions and guidelines
  - README and setup files

✅ Configuration
  - Training configurations
  - Game rules and settings
  - Board and unit definitions
  - Reward system configurations

✅ Scripts
  - Development utilities
  - Backup and restore scripts
  - PowerShell utilities
```

### **What Gets Excluded**
```
❌ Large Generated Files
  - node_modules/ (can be regenerated with npm install)
  - ai/models/ (trained models - too large, can be retrained)
  - tensorboard/ (training logs - regenerated during training)
  - dist/ (build output - regenerated with npm run build)

❌ Temporary Files
  - ai/event_log/ (game logs - regenerated during training)
  - temp/ and cache/ directories
  - .git/ (version control - separate system)

❌ User-Specific Files
  - .env files with sensitive data
  - Local configuration overrides
  - IDE-specific settings
```

## 🔧 **Advanced Usage**

### **Automated Backup Script**
Create `scripts/auto_backup.py`:
```python
#!/usr/bin/env python3
import os
import subprocess
import schedule
import time

def daily_backup():
    """Run daily backup"""
    try:
        result = subprocess.run(['python', 'scripts/complete_backup.py'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ Daily backup completed successfully")
        else:
            print(f"❌ Daily backup failed: {result.stderr}")
    except Exception as e:
        print(f"❌ Backup error: {e}")

# Schedule daily backup at 2 AM
schedule.every().day.at("02:00").do(daily_backup)

# Schedule weekly backup on Sunday
schedule.every().sunday.at("01:00").do(daily_backup)

print("🕐 Backup scheduler started...")
while True:
    schedule.run_pending()
    time.sleep(60)  # Check every minute
```

### **PowerShell Integration**
Create `ps_backup.ps1`:
```powershell
# ps_backup.ps1 - PowerShell wrapper for backup system
param(
    [string]$Action = "backup",
    [string]$BackupPath = "",
    [switch]$Force
)

Write-Host "🚀 WH40K Tactics RL Backup System" -ForegroundColor Green

switch ($Action.ToLower()) {
    "backup" {
        Write-Host "📦 Creating backup..." -ForegroundColor Yellow
        python scripts/complete_backup.py
    }
    "restore" {
        if (-not $BackupPath) {
            Write-Host "❌ Backup path required for restore" -ForegroundColor Red
            exit 1
        }
        
        $args = @("scripts/restore_backup.py", $BackupPath)
        if ($Force) { $args += "--force" }
        
        Write-Host "🔄 Restoring from: $BackupPath" -ForegroundColor Yellow
        python @args
    }
    "list" {
        Write-Host "📋 Available backups:" -ForegroundColor Yellow
        Get-ChildItem "backups/" -Filter "*.zip" | Format-Table Name, Length, LastWriteTime
    }
    default {
        Write-Host "❌ Unknown action: $Action" -ForegroundColor Red
        Write-Host "Usage: .\ps_backup.ps1 [-Action backup|restore|list] [-BackupPath path] [-Force]"
    }
}
```

## 🛡️ **Best Practices**

### **1. Regular Backup Schedule**
```bash
# Before major changes
python scripts/complete_backup.py

# Before training new models
python scripts/complete_backup.py

# Weekly milestone backups
python scripts/complete_backup.py
```

### **2. Backup Naming Convention**
The script automatically creates descriptive names:
```
backup_20250712_143022.zip
│      │        │
│      │        └── Time (14:30:22)
│      └── Date (2025-07-12) 
└── Simple backup prefix
```

### **3. Storage Organization**
```
backup/
├── backup_20250712_143022.zip    # Morning backup
│   └── Contains: gym40k.py, config.json, App.tsx, Board.tsx, backup_block_README.md
├── backup_20250712_160000.zip    # Before AI training  
├── backup_20250712_180000.zip    # End of day
├── backup_20250713_090000.zip    # Next day
├── backup_20250713_143000.zip    # Before major changes
└── backup_20250713_170000.zip    # Latest backup

# Each backup contains clean filenames with repository documentation:
# backup_20250712_143022/
# ├── gym40k.py                    # Original: ai/gym40k.py
# ├── config.json                  # Original: config/config.json (root config)
# ├── config_1.json                # Original: config/game_config.json (conflict resolved)
# ├── App.tsx                      # Original: frontend/src/App.tsx
# ├── Board.tsx                    # Original: frontend/src/components/Board.tsx
# ├── backup_block_README.md       # Repository structure with file mapping
# ├── _backup_structure.md         # Complete repository tree snapshot
# └── backup_metadata.json         # Technical backup information
```

### **4. Recovery Testing**
```bash
# Test restore in different location
python scripts/restore_block.py "backup/backup_20250712_143022.zip" --target "/tmp/test_restore"

# Verify critical files exist in correct locations (easy with clean names!)
ls /tmp/test_restore/ai/gym40k.py           # Should exist
ls /tmp/test_restore/config/config.json    # Should exist  
ls /tmp/test_restore/frontend/src/App.tsx  # Should exist

# Check that structure was preserved correctly
cat /tmp/test_restore/backup_block_README.md        # Review what was backed up and where files belong
```

## 🚨 **Emergency Procedures**

### **1. Complete Project Loss**
```bash
# 1. Find latest backup
ls -la backup/*.zip

# 2. Restore to new location  
mkdir /recovery/wh40k-tactics
python scripts/restore_block.py "backup/backup_20250712_143022.zip" --target "/recovery/wh40k-tactics"

# 3. Check what was restored using structure doc
cat /recovery/wh40k-tactics/backup_block_README.md

# 4. Verify restoration
cd /recovery/wh40k-tactics
python ai/train.py --help  # Test AI scripts
cd frontend && npm install  # Restore dependencies
```

### **2. Partial File Corruption**
```bash
# 1. Create backup of current state
python scripts/backup_block.py

# 2. Check file path reconstruction from tree structure
unzip -l backup/backup_20250712_143022.zip | grep _backup_structure
unzip -p backup/backup_20250712_143022.zip _backup_structure.md | grep "gym40k.py"

# 3. Restore specific files using clean backup filename (much easier!)
unzip backup/backup_20250712_143022.zip gym40k.py
# The restore script will know it goes to ai/gym40k.py from _backup_structure.md
cp gym40k.py ai/gym40k.py

unzip backup/backup_20250712_143022.zip Board.tsx  
# The restore script will know it goes to frontend/src/components/Board.tsx
cp Board.tsx frontend/src/components/Board.tsx

# Or use restore script for automatic path reconstruction from tree structure
python scripts/restore_block.py "backup/backup_20250712_143022.zip"
```

### **3. Configuration Reset**
```bash
# Check which config files are in backup (easy with clean names!)
unzip -l backup/backup_20250712_143022.zip | grep "\.json"

# Extract config files (they have clean names like config.json, game_config.json, etc.)
unzip backup/backup_20250712_143022.zip "*.json"

# Check the tree structure to see file locations
cat _backup_structure.md | grep -A5 -B5 config.json

# Use restore script to map them back automatically using tree structure
python scripts/restore_block.py "backup/backup_20250712_143022.zip"
```

## 📈 **Monitoring & Maintenance**

### **1. Backup Size Monitoring**
```bash
# Check backup sizes
du -sh backup/*.zip | sort -hr

# Archive old backups (keep last 10)
ls -t backup/*.zip | tail -n +11 | xargs rm
```

### **2. Automated Cleanup**
```python
# Add to backup script
def cleanup_old_backups(backup_dir: str, keep_count: int = 20):
    """Keep only the most recent backups"""
    backups = sorted(glob.glob(f"{backup_dir}/*.zip"), 
                    key=os.path.getmtime, reverse=True)
    
    for old_backup in backups[keep_count:]:
        os.remove(old_backup)
        print(f"🗑️ Removed old backup: {old_backup}")
```

## 🎯 **Summary**

This backup system provides:
- ✅ **Clean filename storage** - files saved with original names (gym40k.py, not ai_gym40k.py)
- ✅ **Repository organization** - backup_block_README.md groups files by function
- ✅ **Conflict resolution** - duplicate names get incremental numbers (config.json, config_1.json)
- ✅ **Automatic file mapping** - restore script reconstructs original paths
- ✅ **Fast, reliable restoration** - handles both manual and automated recovery
- ✅ **Detailed documentation** - complete repository structure with file origins
- ✅ **Space-efficient compression** - ZIP archives with clean structure
- ✅ **Cross-platform compatibility** (Windows/Linux)
- ✅ **Integration with existing project structure** - works in `backup/` directory

### **Key Advantages of Clean Filenames:**
1. **Intuitive identification** - immediately recognize files (gym40k.py vs ai_gym40k.py)
2. **Easy manual extraction** - grab specific files without complex path reconstruction
3. **Simple conflict resolution** - duplicate names become config.json, config_1.json, config_2.json
4. **Repository awareness** - backup_block_README.md shows which repository each file belongs to
5. **Documentation preserved** - complete repository structure and file origins documented

Perfect for maintaining your WH40K Tactics RL development environment with maximum clarity and simplicity!