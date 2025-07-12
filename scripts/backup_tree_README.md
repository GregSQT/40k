# WH40K Tactics RL - Backup & Restore System

## Overview
Complete backup and restore system for the WH40K Tactics RL project with timestamped archives and full validation.

## 📁 **Backup Structure**

The system creates backups in your project's `backup/` directory with this structure:

```
wh40k-tactics/
├── 📂 backup/                     # All backups stored here
│   ├── 📂 backup_20250712_143022/ # Uncompressed backup directory
│   │   ├── ai/                    # Exact copy of ai/ directory
│   │   ├── config/                # Exact copy of config/ directory  
│   │   ├── frontend/              # Exact copy of frontend/ directory
│   │   ├── scripts/               # Exact copy of scripts/ directory
│   │   ├── config_loader.py       # Root files preserved
│   │   ├── tsconfig.json
│   │   └── backup_metadata.json   # Backup information
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
- ✅ **Preserves exact file structure** - backup contains identical directory layout
- ✅ **Root-level backup directory** - all backups in `backup/` folder
- ✅ **Simple naming** - `backup_YYYYMMDD_HHMMSS.zip`
- ✅ **Both formats** - uncompressed directory + zip archive

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
python scripts/complete_backup.py
```

### **Restore from Backup**
```bash
# Restore from zip archive
python scripts/restore_backup.py "path/to/backup.zip"

# Restore from directory
python scripts/restore_backup.py "path/to/backup_directory"
```

## 📋 **Script Features**

### **Backup Script (`complete_backup.py`)**
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
python scripts/complete_backup.py

# Output:
# ✅ Backup created: backup/backup_20250712_143022.zip
# 🗂️  File structure: Preserved exactly as in source
```

### **2. Restore from Backup**
```bash
# List available backups
ls backup/

# Restore specific backup
python scripts/restore_backup.py "backup/backup_20250712_143022.zip"

# Restore with options
python scripts/restore_backup.py "backup/backup_20250712_143022.zip" --target "/different/location" --no-backup
```

### **3. Emergency Recovery**
```bash
# Force restore even if validation fails
python scripts/restore_backup.py "backup/backup_20250712_143022.zip" --force

# Restore to different location
python scripts/restore_backup.py "backup/backup_20250712_143022.zip" --target "/recovery/location"
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
├── backup_20250712_160000.zip    # Before AI training
├── backup_20250712_180000.zip    # End of day
├── backup_20250713_090000.zip    # Next day
├── backup_20250713_143000.zip    # Before major changes
└── backup_20250713_170000.zip    # Latest backup

# Directory structure inside each backup preserves original layout:
# backup_20250712_143022/
# ├── ai/gym40k.py
# ├── config/config.json  
# ├── frontend/src/App.tsx
# └── ... (exact copy of project structure)
```

### **4. Recovery Testing**
```bash
# Test restore in different location
python scripts/restore_backup.py "backup.zip" --target "/tmp/test_restore"

# Verify critical files exist
ls /tmp/test_restore/ai/
ls /tmp/test_restore/config/
ls /tmp/test_restore/frontend/src/
```

## 🚨 **Emergency Procedures**

### **1. Complete Project Loss**
```bash
# 1. Find latest backup
ls -la backup/*.zip

# 2. Restore to new location  
mkdir /recovery/wh40k-tactics
python scripts/restore_backup.py "backup/backup_20250712_143022.zip" --target "/recovery/wh40k-tactics"

# 3. Verify restoration
cd /recovery/wh40k-tactics
python ai/train.py --help  # Test AI scripts
cd frontend && npm install  # Restore dependencies
```

### **2. Partial File Corruption**
```bash
# 1. Create backup of current state
python scripts/complete_backup.py

# 2. Restore specific files (manual extraction)
unzip -j "backup/backup_20250712_143022.zip" "ai/gym40k.py" -d "ai/"
unzip -j "backup/backup_20250712_143022.zip" "config/config.json" -d "config/"

# 3. Verify restoration
python config_loader.py  # Test configuration loading
```

### **3. Configuration Reset**
```bash
# Extract only configuration files
unzip "backup/backup_20250712_143022.zip" "config/*" -d "."
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
- ✅ **Complete project preservation**
- ✅ **Fast, reliable restoration**
- ✅ **Automatic validation and verification**
- ✅ **Space-efficient compression**
- ✅ **Detailed logging and metadata**
- ✅ **Cross-platform compatibility** (Windows/Linux)
- ✅ **Integration with existing project structure**

Perfect for maintaining your WH40K Tactics RL development environment with confidence!