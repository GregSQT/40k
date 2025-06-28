# fix_all_configs.ps1
# Complete setup script to create all missing config files and organize them properly

Write-Host "🔧 WH40K Config Files Organization Fix" -ForegroundColor Yellow
Write-Host "=" * 50

# Ensure all required directories exist
$directories = @(
    "config",
    "frontend\public\ai",
    "frontend\public\ai\config"
)

foreach ($dir in $directories) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    Write-Host "✅ Directory: $dir" -ForegroundColor Green
}

# 1. Create config/board_config.json
Write-Host "`n📐 Creating board_config.json..." -ForegroundColor Cyan
$boardConfig = @{
    "default" = @{
        "cols" = 24
        "rows" = 18
        "hex_radius" = 24
        "margin" = 32
        "colors" = @{
            "background" = "0x002200"
            "cell_even" = "0x002200"
            "cell_odd" = "0x001a00"
            "cell_border" = "0x00ff00"
            "player_0" = "0x244488"
            "player_1" = "0x882222"
            "hp_full" = "0x36e36b"
            "hp_damaged" = "0x444444"
            "highlight" = "0x80ff80"
            "current_unit" = "0xffd700"
        }
    }
    "small" = @{
        "cols" = 12
        "rows" = 9
        "hex_radius" = 20
        "margin" = 24
        "colors" = @{
            "background" = "0x002200"
            "cell_even" = "0x002200"
            "cell_odd" = "0x001a00"
            "cell_border" = "0x00ff00"
            "player_0" = "0x244488"
            "player_1" = "0x882222"
            "hp_full" = "0x36e36b"
            "hp_damaged" = "0x444444"
            "highlight" = "0x80ff80"
            "current_unit" = "0xffd700"
        }
    }
    "large" = @{
        "cols" = 36
        "rows" = 27
        "hex_radius" = 20
        "margin" = 40
        "colors" = @{
            "background" = "0x002200"
            "cell_even" = "0x002200"
            "cell_odd" = "0x001a00"
            "cell_border" = "0x00ff00"
            "player_0" = "0x244488"
            "player_1" = "0x882222"
            "hp_full" = "0x36e36b"
            "hp_damaged" = "0x444444"
            "highlight" = "0x80ff80"
            "current_unit" = "0xffd700"
        }
    }
}

# 2. Create config/unit_definitions.json
Write-Host "🚀 Creating unit_definitions.json..." -ForegroundColor Cyan
$unitDefinitions = @{
    "Intercessor" = @{
        "hp_max" = 3
        "move" = 4
        "ranged_range" = 8
        "ranged_damage" = 2
        "melee_damage" = 1
        "is_ranged" = $true
        "is_melee" = $false
        "cost" = 100
        "description" = "Standard Space Marine with bolt rifle"
    }
    "AssaultIntercessor" = @{
        "hp_max" = 4
        "move" = 6
        "ranged_range" = 4
        "ranged_damage" = 1
        "melee_damage" = 2
        "is_ranged" = $false
        "is_melee" = $true
        "cost" = 120
        "description" = "Close combat specialist Space Marine"
    }
    "Terminator" = @{
        "hp_max" = 5
        "move" = 3
        "ranged_range" = 6
        "ranged_damage" = 3
        "melee_damage" = 3
        "is_ranged" = $true
        "is_melee" = $true
        "cost" = 200
        "description" = "Heavy armored elite unit"
    }
    "Scout" = @{
        "hp_max" = 2
        "move" = 5
        "ranged_range" = 10
        "ranged_damage" = 1
        "melee_damage" = 1
        "is_ranged" = $true
        "is_melee" = $false
        "cost" = 80
        "description" = "Fast reconnaissance unit"
    }
}

# 3. Create config/training_config.json
Write-Host "🧠 Creating training_config.json..." -ForegroundColor Cyan
$trainingConfig = @{
    "default" = @{
        "description" = "Default training configuration"
        "total_timesteps" = 500000
        "learning_rate" = 0.0003
        "batch_size" = 64
        "buffer_size" = 1000000
        "learning_starts" = 50000
        "target_update_interval" = 1000
        "train_freq" = 4
        "gradient_steps" = 1
        "exploration_fraction" = 0.1
        "exploration_initial_eps" = 1.0
        "exploration_final_eps" = 0.05
        "max_grad_norm" = 10
        "tensorboard_log" = "./tensorboard/"
    }
    "debug" = @{
        "description" = "Quick debug training - 50k timesteps"
        "total_timesteps" = 50000
        "learning_rate" = 0.001
        "batch_size" = 32
        "buffer_size" = 100000
        "learning_starts" = 5000
        "target_update_interval" = 500
        "train_freq" = 2
        "gradient_steps" = 1
        "exploration_fraction" = 0.2
        "exploration_initial_eps" = 1.0
        "exploration_final_eps" = 0.1
        "max_grad_norm" = 10
        "tensorboard_log" = "./tensorboard/"
    }
    "production" = @{
        "description" = "Production training - longer with better exploration"
        "total_timesteps" = 2000000
        "learning_rate" = 0.0001
        "batch_size" = 128
        "buffer_size" = 2000000
        "learning_starts" = 100000
        "target_update_interval" = 2000
        "train_freq" = 8
        "gradient_steps" = 2
        "exploration_fraction" = 0.05
        "exploration_initial_eps" = 1.0
        "exploration_final_eps" = 0.02
        "max_grad_norm" = 5
        "tensorboard_log" = "./tensorboard/"
    }
}

# 4. Create config/rewards_config.json
Write-Host "🏆 Creating rewards_config.json..." -ForegroundColor Cyan
$rewardsConfig = @{
    "original" = @{
        "description" = "Original reward system"
        "kill_enemy" = 100
        "damage_enemy" = 10
        "move_closer_to_enemy" = 1
        "move_away_from_enemy" = -2
        "invalid_action" = -50
        "win_game" = 1000
        "lose_game" = -1000
        "turn_penalty" = -1
    }
    "aggressive" = @{
        "description" = "Encourages aggressive play"
        "kill_enemy" = 200
        "damage_enemy" = 20
        "move_closer_to_enemy" = 5
        "move_away_from_enemy" = -10
        "invalid_action" = -100
        "win_game" = 1000
        "lose_game" = -1000
        "turn_penalty" = -2
    }
    "tactical" = @{
        "description" = "Encourages tactical positioning"
        "kill_enemy" = 100
        "damage_enemy" = 15
        "move_closer_to_enemy" = 2
        "move_away_from_enemy" = 0
        "good_position" = 10
        "bad_position" = -5
        "invalid_action" = -75
        "win_game" = 1000
        "lose_game" = -1000
        "turn_penalty" = -1
    }
}

# Write all config files
try {
    $boardConfig | ConvertTo-Json -Depth 10 | Out-File -FilePath "config\board_config.json" -Encoding UTF8
    $unitDefinitions | ConvertTo-Json -Depth 10 | Out-File -FilePath "config\unit_definitions.json" -Encoding UTF8
    $trainingConfig | ConvertTo-Json -Depth 10 | Out-File -FilePath "config\training_config.json" -Encoding UTF8
    $rewardsConfig | ConvertTo-Json -Depth 10 | Out-File -FilePath "config\rewards_config.json" -Encoding UTF8
    
    Write-Host "✅ Created all master config files in /config/" -ForegroundColor Green
    
    # Copy to frontend public directory for web access
    Copy-Item "config\board_config.json" "frontend\public\ai\config\board_config.json" -Force
    Copy-Item "config\unit_definitions.json" "frontend\public\ai\config\unit_definitions.json" -Force
    
    Write-Host "✅ Copied config files to frontend/public/ai/config/" -ForegroundColor Green
    
    # Create frontend scenario.json from existing config/scenarios.json if it exists
    if (Test-Path "config\scenarios.json") {
        $existingScenario = Get-Content "config\scenarios.json" -Raw | ConvertFrom-Json
        
        # Use first scenario or create basic structure
        $frontendScenario = @{
            "board_config" = "default"
            "units" = $existingScenario
        }
        
        $frontendScenario | ConvertTo-Json -Depth 10 | Out-File -FilePath "frontend\public\ai\scenario.json" -Encoding UTF8
        Write-Host "✅ Created frontend scenario.json from existing config" -ForegroundColor Green
    }
    
    # Validate all files
    Write-Host "`n🔍 Validating created files..." -ForegroundColor Yellow
    
    $configFiles = @(
        "config\board_config.json",
        "config\unit_definitions.json", 
        "config\training_config.json",
        "config\rewards_config.json",
        "frontend\public\ai\config\board_config.json",
        "frontend\public\ai\config\unit_definitions.json"
    )
    
    foreach ($file in $configFiles) {
        if (Test-Path $file) {
            $testJson = Get-Content $file -Raw | ConvertFrom-Json
            Write-Host "  ✅ $file - VALID JSON" -ForegroundColor Green
        } else {
            Write-Host "  ❌ $file - MISSING" -ForegroundColor Red
        }
    }
    
    Write-Host "`n🎯 CONFIGURATION SUMMARY:" -ForegroundColor Yellow
    Write-Host "  📁 Master configs: /config/ (4 files)" -ForegroundColor Cyan
    Write-Host "  🌐 Web configs: /frontend/public/ai/config/ (2 files)" -ForegroundColor Cyan
    Write-Host "  📋 Generated configs: /ai/ (managed by config_loader.py)" -ForegroundColor Cyan
    
    Write-Host "`n🎮 Your board should now display correctly!" -ForegroundColor Green
    Write-Host "Run the app and check the Game option." -ForegroundColor Green
    
} catch {
    Write-Host "❌ Error creating config files: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}