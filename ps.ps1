# tools/debug_replay_movement.ps1

Write-Host "Debugging Replay Movement Issues..." -ForegroundColor Cyan

# Check if replay file exists
$replayFile = "ai\event_log\train_best_game_replay.json"
if (-not (Test-Path $replayFile)) {
    Write-Host "Replay file not found: $replayFile" -ForegroundColor Red
    exit 1
}

Write-Host "Found replay file: $replayFile" -ForegroundColor Green

# Load and analyze replay data
try {
    $replayData = Get-Content $replayFile | ConvertFrom-Json
    Write-Host "Replay loaded with $($replayData.events.Count) events" -ForegroundColor Yellow
    
    # Check first few events for unit positions
    Write-Host "`nChecking unit positions in first 5 events:" -ForegroundColor Cyan
    
    for ($i = 0; $i -lt [Math]::Min(5, $replayData.events.Count); $i++) {
        $replayEvent = $replayData.events[$i]
        Write-Host "Event $i - Turn: $($replayEvent.turn)" -ForegroundColor White
        
        if ($replayEvent.units) {
            foreach ($unit in $replayEvent.units) {
                Write-Host "  Unit $($unit.id): Player $($unit.player) at [$($unit.col), $($unit.row)] HP: $($unit.CUR_HP)/$($unit.HP_MAX)" -ForegroundColor Gray
            }
        } else {
            Write-Host "  No units data in this event" -ForegroundColor Yellow
        }
        Write-Host ""
    }
    
    # Check for position changes between consecutive events
    Write-Host "Checking for movement between events:" -ForegroundColor Cyan
    $movementFound = $false
    
    for ($i = 1; $i -lt [Math]::Min(10, $replayData.events.Count); $i++) {
        $currentReplayEvent = $replayData.events[$i]
        $prevReplayEvent = $replayData.events[$i - 1]
        
        if ($currentReplayEvent.units -and $prevReplayEvent.units) {
            foreach ($unit in $currentReplayEvent.units) {
                $prevUnit = $prevReplayEvent.units | Where-Object { $_.id -eq $unit.id }
                if ($prevUnit -and (($unit.col -ne $prevUnit.col) -or ($unit.row -ne $prevUnit.row))) {
                    Write-Host "  Unit $($unit.id) moved from [$($prevUnit.col), $($prevUnit.row)] to [$($unit.col), $($unit.row)] at event $i" -ForegroundColor Green
                    $movementFound = $true
                }
            }
        }
    }
    
    if (-not $movementFound) {
        Write-Host "  No unit movement detected in first 10 events" -ForegroundColor Yellow
        Write-Host "      This could explain why you dont see units moving!" -ForegroundColor Red
    }
    
    # Check for animation timing settings
    Write-Host "`nAnimation Settings Check:" -ForegroundColor Cyan
    $gameConfigFile = "frontend\src\constants\gameConfig.ts"
    if (Test-Path $gameConfigFile) {
        $content = Get-Content $gameConfigFile -Raw
        if ($content -match "ANIMATION_DURATION:\s*(\d+)") {
            Write-Host "  Animation Duration: $($Matches[1])ms" -ForegroundColor Green
        }
        if ($content -match "TIMING\s*=\s*{[^}]*ANIMATION_DURATION:\s*(\d+)") {
            Write-Host "  Found timing config: $($Matches[1])ms" -ForegroundColor Green
        }
    }
    
    Write-Host "`nRecommendations:" -ForegroundColor Cyan
    Write-Host "1. Check browser console for JavaScript errors during replay" -ForegroundColor White
    Write-Host "2. Verify that PIXI.js is properly initializing sprites" -ForegroundColor White
    Write-Host "3. Test with a shorter animation duration (e.g. 250ms)" -ForegroundColor White
    Write-Host "4. Check if replay auto-play speed is too fast to see animations" -ForegroundColor White
    
} catch {
    Write-Host "Error analyzing replay file: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "`nDebug analysis complete!" -ForegroundColor Green