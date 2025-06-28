# copy_missing_config.ps1
# Fix missing game_config.json in frontend/public/ai/config/

Write-Host "🔧 Fixing missing config files..." -ForegroundColor Yellow

# Check if source config files exist
$sourceGameConfig = "config\game_config.json"
$sourceBoardConfig = "config\board_config.json"

if (!(Test-Path $sourceGameConfig)) {
    Write-Host "❌ Source file missing: $sourceGameConfig" -ForegroundColor Red
    Write-Host "   Please create this file first with max_turns configuration" -ForegroundColor Red
    exit 1
}

if (!(Test-Path $sourceBoardConfig)) {
    Write-Host "❌ Source file missing: $sourceBoardConfig" -ForegroundColor Red
    exit 1
}

# Ensure target directory exists
$targetDir = "frontend\public\ai\config"
if (!(Test-Path $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    Write-Host "✅ Created directory: $targetDir" -ForegroundColor Green
}

# Copy missing game_config.json
$targetGameConfig = "$targetDir\game_config.json"
try {
    Copy-Item $sourceGameConfig $targetGameConfig -Force
    Write-Host "✅ Copied: $sourceGameConfig -> $targetGameConfig" -ForegroundColor Green
} catch {
    Write-Host "❌ Failed to copy game_config.json: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Verify board_config.json exists (should already be there)
$targetBoardConfig = "$targetDir\board_config.json"
if (!(Test-Path $targetBoardConfig)) {
    Copy-Item $sourceBoardConfig $targetBoardConfig -Force
    Write-Host "✅ Copied: $sourceBoardConfig -> $targetBoardConfig" -ForegroundColor Green
}

# Validate JSON files
Write-Host "`n🔍 Validating copied config files..." -ForegroundColor Cyan

$configFiles = @(
    $targetGameConfig,
    $targetBoardConfig
)

foreach ($file in $configFiles) {
    if (Test-Path $file) {
        try {
            $testJson = Get-Content $file -Raw | ConvertFrom-Json
            Write-Host "  ✅ $file - VALID JSON" -ForegroundColor Green
        } catch {
            Write-Host "  ❌ $file - INVALID JSON: $($_.Exception.Message)" -ForegroundColor Red
        }
    } else {
        Write-Host "  ❌ $file - MISSING" -ForegroundColor Red
    }
}

Write-Host "`n🎯 Config files are now available for frontend!" -ForegroundColor Green
Write-Host "   Frontend can now load:" -ForegroundColor Cyan
Write-Host "   - /ai/config/game_config.json" -ForegroundColor Cyan
Write-Host "   - /ai/config/board_config.json" -ForegroundColor Cyan