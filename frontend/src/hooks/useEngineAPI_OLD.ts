// frontend/src/hooks/useEngineAPI.ts
import { useState, useEffect, useCallback, useRef } from 'react';
import type { Unit, PlayerId } from '../types';
import { offsetToCube, cubeDistance } from '../utils/gameHelpers';

// Get max_turns from config instead of hardcoded fallback
const getMaxTurnsFromConfig = async (): Promise<number> => {
  try {
    const response = await fetch('/config/game_config.json');
    if (!response.ok) {
      throw new Error(`Config fetch failed: ${response.status}`);
    }
    const config = await response.json();
    if (!config.game_rules?.max_turns) {
      throw new Error(`Missing required max_turns in game config`);
    }
    return config.game_rules.max_turns;
  } catch (error) {
    throw new Error(`CRITICAL CONFIG ERROR: Failed to load max_turns from config: ${error}`);
  }
};

const API_BASE = 'http://localhost:5001/api';

// Prevent duplicate AI turn calls
let aiTurnInProgress = false;

interface APIGameState {
  units: Array<{
    id: string;
    player: number;
    col: number;
    row: number;
    HP_CUR: number;
    HP_MAX: number;
    MOVE: number;
    T: number;
    ARMOR_SAVE: number;
    INVUL_SAVE: number;
    RNG_RNG: number;
    RNG_DMG: number;
    RNG_NB: number;
    RNG_ATK: number;
    RNG_STR: number;
    RNG_AP: number;
    CC_DMG: number;
    CC_RNG?: number;
    CC_NB: number;
    CC_ATK: number;
    CC_STR: number;
    CC_AP: number;
    LD: number;
    OC: number;
    VALUE: number;
    ICON: string;
    ICON_SCALE?: number;
    unitType: string;
    SHOOT_LEFT?: number;
    ATTACK_LEFT?: number;
    // AI_TURN.md shooting state fields
    valid_target_pool?: string[];
    selected_target_id?: string;
    TOTAL_ATTACK_LOG?: string;
  }>;
  current_player: number;
  phase: string;
  turn: number;
  episode_steps: number;
  max_turns: number;
  units_moved: string[];
  units_fled: string[];
  units_shot: string[];
  units_charged: string[];
  units_attacked: string[];
  move_activation_pool: string[];
  shoot_activation_pool: string[];
  charge_activation_pool: string[];
  charging_activation_pool: string[];
  active_alternating_activation_pool: string[];
  non_active_alternating_activation_pool: string[];
  fight_subphase: string | null;
  // AI_TURN.md shooting phase state
  active_shooting_unit?: string;
  pve_mode?: boolean; // Add PvE mode flag
}

export const useEngineAPI = () => {
  const [gameState, setGameState] = useState<APIGameState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [maxTurnsFromConfig, setMaxTurnsFromConfig] = useState<number>(8);
  const [selectedUnitId, setSelectedUnitId] = useState<number | null>(null);
  const [mode, setMode] = useState<"select" | "movePreview" | "attackPreview" | "targetPreview" | "chargePreview">("select");
  const [movePreview, setMovePreview] = useState<{ unitId: number; destCol: number; destRow: number } | null>(null);
  const [attackPreview, setAttackPreview] = useState<{ unitId: number; col: number; row: number } | null>(null);
  const [chargeDestinations, setChargeDestinations] = useState<Array<{ col: number; row: number }>>([]);
  const [targetPreview, setTargetPreview] = useState<{
  shooterId: number;
  targetId: number;
  currentBlinkStep?: number;
  totalBlinkSteps?: number;
  blinkTimer?: number | null;
  hitProbability?: number;
  woundProbability?: number;
  saveProbability?: number;
  overallProbability?: number;
  potentialDamage?: number;
  expectedDamage?: number;
  lastUpdate?: number;
} | null>(null);
  
  // State for multi-unit HP bar blinking
  const [blinkingUnits, setBlinkingUnits] = useState<{unitIds: number[], blinkTimer: number | null, blinkState: boolean}>({unitIds: [], blinkTimer: null, blinkState: false});
  
  // State for failed charge roll display
  const [failedChargeRoll, setFailedChargeRoll] = useState<{unitId: number, roll: number, targetId?: number} | null>(null);
  // State for successful charge target display
  const [successfulChargeTarget, setSuccessfulChargeTarget] = useState<{unitId: number, targetId: number} | null>(null);
  
  // Load config values
  useEffect(() => {
    getMaxTurnsFromConfig().then(setMaxTurnsFromConfig);
  }, []);

  // Initialize game - FIXED: Added ref to prevent multiple calls
  const gameInitialized = useRef(false);
  const lastShownLogs = useRef(new Set<string>());
  
  useEffect(() => {
    if (gameInitialized.current) {
      return;
    }
    
    const startGame = async () => {
      try {
        gameInitialized.current = true;
        setLoading(true);
        
        // Detect PvE mode from URL
        const urlParams = new URLSearchParams(window.location.search);
        const isPvE = urlParams.get('mode') === 'pve' || window.location.pathname.includes('/pve');
        
        console.log(`Starting game in ${isPvE ? 'PvE' : 'PvP'} mode`);
        
        const response = await fetch(`${API_BASE}/game/start`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pve_mode: isPvE })
        });
        
        if (!response.ok) {
          throw new Error(`Failed to start game: ${response.status}`);
        }
        
        const data = await response.json();
        if (data.success) {
          setGameState(data.game_state);
          console.log(`Game started successfully in ${data.game_state.pve_mode ? 'PvE' : 'PvP'} mode`);
        } else {
          throw new Error(data.error || 'Failed to start game');
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
        gameInitialized.current = false; // Reset on error
      } finally {
        setLoading(false);
      }
    };
    
    startGame();
  }, []);

  // Execute action via API
  const executeAction = useCallback(async (action: any) => {
    
    if (!gameState) {
      return;
    }
    
    try {
      const requestId = Date.now();
      const requestBody = JSON.stringify({...action, requestId});
      const response = await fetch(`${API_BASE}/game/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: requestBody
      });
      
      if (!response.ok) {
        throw new Error(`Action failed: ${response.status}`);
      }
      
      const data = await response.json();

      // ONLY LOG FIGHT PHASE FOR DEBUGGING
      if (data.game_state?.phase === "fight") {
        console.log("🎯 Backend result:", data.result);
        console.log("🎯 game_state.action_logs:", data.game_state?.action_logs);
      }

      // Process detailed backend action logs FIRST
      if (data.action_logs && data.action_logs.length > 0) {
        data.action_logs.forEach((logEntry: any) => {
          // console.log(`🎯 DETAILED BACKEND LOG: ${logEntry.message}`);

          // Send detailed log to GameLog component via custom event
          // AI_TURN.md: Handle both shooting (flat fields) and fight (shootDetails array) formats
          // Fight handler sends shootDetails array, shooting handler sends flat fields
          // Extract from shootDetails[0] if shootDetails exists (fight phase)
          const shootDetail = logEntry.shootDetails?.[0];

          window.dispatchEvent(new CustomEvent('backendLogEvent', {
            detail: {
              type: logEntry.type,
              message: logEntry.message,
              turn: logEntry.turn,
              phase: logEntry.phase,
              shooterId: logEntry.shooterId || logEntry.attackerId,  // shooting uses shooterId, fight uses attackerId
              targetId: logEntry.targetId,
              player: logEntry.player,
              // Extract damage/target_died from shootDetails if present (fight), otherwise use flat fields (shooting)
              damage: logEntry.damage ?? shootDetail?.damageDealt,
              target_died: logEntry.target_died ?? shootDetail?.targetDied,
              // Extract roll data from shootDetails if present (fight), otherwise use flat fields (shooting)
              hitRoll: logEntry.hitRoll || logEntry.hit_roll || shootDetail?.attackRoll,
              woundRoll: logEntry.woundRoll || logEntry.wound_roll || shootDetail?.strengthRoll,
              saveRoll: logEntry.saveRoll || logEntry.save_roll || shootDetail?.saveRoll,
              saveTarget: logEntry.saveTarget || logEntry.save_target || shootDetail?.saveTarget,
              // Pass through shootDetails for direct use by getEventTypeClass color logic
              shootDetails: logEntry.shootDetails,
              timestamp: new Date()
            }
          }));
        });
      }
      
      // DEBUG: Log full response structure to understand blinking data location
      
        if (data.success) {
          // CRITICAL: Handle empty activation pools before other processing
          if (data.game_state?.phase === "shoot" && 
              Array.isArray(data.game_state.shoot_activation_pool) && 
              data.game_state.shoot_activation_pool.length === 0) {
            console.log("🔥 EMPTY SHOOTING POOL DETECTED - Auto-advancing phase");
            setTimeout(async () => {
              await executeAction({ action: "advance_phase", phase: "shoot" });
            }, 100);
          }
          
          // Process backend cleanup signals FIRST
          if (data.result?.clear_preview) {
            console.log("🧹 Backend requested preview cleanup");
            setTargetPreview(null);
          }
          
          if (data.result?.clear_blinking_gentle) {
            console.log("🧹 Backend requested gentle blinking cleanup");
            // Clear central timers only - don't destroy renderer
            if (blinkingUnits.blinkTimer) {
              clearInterval(blinkingUnits.blinkTimer);
            }
            setBlinkingUnits({unitIds: [], blinkTimer: null, blinkState: false});
            
            if (targetPreview?.blinkTimer) {
              clearInterval(targetPreview.blinkTimer);
            }
            setTargetPreview(null);
          }
          
          if (data.result?.reset_mode) {
            console.log("🧹 Backend requested mode reset");
            setMode("select");
          }
          
          if (data.result?.clear_selected_unit) {
            console.log("🧹 Backend requested selected unit clear");
            setSelectedUnitId(null);
          }
          
          if (data.result?.clear_attack_preview) {
            console.log("🧹 Backend requested attack preview clear");
            setMode("select");
          }
          
          // Auto-display Python console logs in browser (only during actions)
          if (data.game_state?.console_logs && data.game_state.console_logs.length > 0) {
            // DISABLED TO REDUCE FLOOD
            // const newLogs = data.game_state.console_logs.filter((log: string) =>
            //   !lastShownLogs.current.has(log)
            // );
            // if (newLogs.length > 0) {
            //   newLogs.forEach((log: string) => {
            //     console.log(`  ${log}`);
            //     lastShownLogs.current.add(log);
            //   });
            // }
            
            // Clear logs from the data before setting state to prevent persistence
            data.game_state.console_logs = [];
          }
          
          // Process blinking data from backend
          if (data.result?.blinking_units && data.result?.start_blinking) {

            // Clear any existing blinking timer
            if (blinkingUnits.blinkTimer) {
              clearInterval(blinkingUnits.blinkTimer);
            }

            // Start blinking for all valid targets
            const unitIds = data.result.blinking_units.map((id: string) => parseInt(id));
            const timer = window.setInterval(() => {
              // Toggle blink state for visual effect
              setBlinkingUnits(prev => ({
                ...prev,
                blinkState: !prev.blinkState
              }));
            }, 500);

            setBlinkingUnits({unitIds, blinkTimer: timer, blinkState: false});
            // AI_TURN.md COMPLIANCE: Clear stale attackPreview when entering attackPreview mode for shooting
            // This prevents units from rendering at old positions from previous fight phases
            setAttackPreview(null);
            setMode("attackPreview");

            // Force component re-render to ensure props propagate
            setSelectedUnitId(prevId => prevId);
          }

          setGameState(data.game_state);

        // DEBUG: Check what values we have for fight phase detection
        if (data.game_state?.phase === "fight") {
          console.log("🔍 FIGHT PHASE RESPONSE DEBUG:", {
            phase: data.game_state?.phase,
            waiting_for_player: data.result?.waiting_for_player,
            has_valid_targets: !!data.result?.valid_targets,
            valid_targets_length: data.result?.valid_targets?.length,
            ATTACK_LEFT: data.result?.ATTACK_LEFT
          });
        }

        // AI_TURN.md: Handle charge activation response with valid destinations
        // MUST be after setGameState to prevent being overwritten
        if (data.result?.valid_destinations && data.result?.waiting_for_player) {
          console.log("🎯 CHARGE ACTIVATION: Valid destinations received, switching to chargePreview mode");
          console.log("🎯 Valid destinations count:", data.result.valid_destinations.length);
          console.log("🎯 Charge roll:", data.result.charge_roll);
          console.log("🎯 Setting selectedUnitId to:", data.result.unitId);
          setChargeDestinations(data.result.valid_destinations);
          setSelectedUnitId(parseInt(data.result.unitId));
          setMode("chargePreview");
        }
        // NEW RULE: Handle charge failure - show failed roll badge
        // Use EXACT same logic as successful charges: reset mode immediately, store targetId
        else if (data.result?.charge_failed && data.result?.charge_roll !== undefined) {
          console.log("🎯 CHARGE FAILED: Roll too low", data.result.charge_roll);
          const failedUnitId = parseInt(data.result.unitId || "0");
          const targetId = data.result.targetId ? parseInt(data.result.targetId) : undefined;
          // Store failed charge info for badge display
          setFailedChargeRoll({ unitId: failedUnitId, roll: data.result.charge_roll });
          // Store target separately (EXACT same as successful charges) for target icon display
          if (targetId) {
            setSuccessfulChargeTarget({ unitId: failedUnitId, targetId });
            // Clear after a delay to show target icon (EXACT same as successful charges)
            setTimeout(() => {
              setSuccessfulChargeTarget(null);
            }, 2000);
          }
          // CRITICAL: Reset mode immediately (EXACT same as successful charges) so logo renders in stable state
          setChargeDestinations([]);
          setSelectedUnitId(null);
          setMode("select");
          // Clear failedChargeRoll after delay to show badge
          setTimeout(() => {
            setFailedChargeRoll(null); // Clear after display
          }, 2000); // Show badge for 2 seconds
        }
        // AI_TURN.md: Handle charge completion - reset to select mode
        // CRITICAL FIX: When phase_complete=true, backend has already transitioned to next phase
        // So we check activation_complete AND (current phase is charge OR phase just completed)
        else if (data.result?.activation_complete &&
                 (data.game_state?.phase === "charge" || data.result?.phase_complete)) {
          console.log("🎯 CHARGE COMPLETE: Resetting to select mode");
          // Store successful charge target for target icon display
          if (data.result?.targetId && data.result?.unitId) {
            const chargerId = parseInt(data.result.unitId);
            const targetId = parseInt(data.result.targetId);
            setSuccessfulChargeTarget({ unitId: chargerId, targetId });
            // Clear after a delay to show target icon
            setTimeout(() => {
              setSuccessfulChargeTarget(null);
            }, 2000);
          }
          setChargeDestinations([]);
          setSelectedUnitId(null);
          setMode("select");
        }
        // AI_TURN.md: Handle fight phase multi-attack (ATTACK_LEFT > 0, waiting_for_player)
        else if (data.game_state?.phase === "fight" && data.result?.waiting_for_player && data.result?.valid_targets) {
          console.log("✅ FIGHT CONDITION MATCHED - staying in attackPreview");
          console.log("🎯 FIGHT ATTACK: Unit still has attacks left, staying in attackPreview mode");
          console.log("🎯 Valid targets:", data.result.valid_targets);
          console.log("🎯 ATTACK_LEFT:", data.result.ATTACK_LEFT);

          // Keep the attacking unit selected and show valid targets
          const unitId = parseInt(data.result.unitId || data.game_state.active_fight_unit);
          setSelectedUnitId(unitId);
          setMode("attackPreview");

          // Set attackPreview state for red hexes to appear
          const unit = data.game_state.units.find((u: any) => parseInt(u.id) === unitId);
          if (unit) {
            setAttackPreview({ unitId, col: unit.col, row: unit.row });
          }

          // Start blinking for valid fight targets if not already blinking
          if (data.result.valid_targets.length > 0 && !blinkingUnits.blinkTimer) {
            const unitIds = data.result.valid_targets.map((id: string) => parseInt(id));
            const timer = window.setInterval(() => {
              setBlinkingUnits(prev => ({
                ...prev,
                blinkState: !prev.blinkState
              }));
            }, 500);
            setBlinkingUnits({unitIds, blinkTimer: timer, blinkState: false});
          }
        }
        // AI_TURN.md: Handle fight phase completion (ATTACK_LEFT = 0, activation_ended)
        else if (data.game_state?.phase === "fight" && data.result?.activation_ended) {
          console.log("🎯 FIGHT COMPLETE: Activation ended, resetting to select mode");
          console.log("🔍 FIGHT POOLS AFTER ACTIVATION:", {
            fight_subphase: data.game_state.fight_subphase,
            charging_pool: data.game_state.charging_activation_pool,
            non_active_pool: data.game_state.non_active_alternating_activation_pool,
            active_pool: data.game_state.active_alternating_activation_pool
          });
          // Clear blinking
          if (blinkingUnits.blinkTimer) {
            clearInterval(blinkingUnits.blinkTimer);
          }
          setBlinkingUnits({unitIds: [], blinkTimer: null, blinkState: false});
          setAttackPreview(null);
          setSelectedUnitId(null);
          setMode("select");
        }
        // Set visual state based on shooting activation
        // AI_TURN.md COMPLIANCE: Clear stale attackPreview from previous fight phases
        // This prevents Unit 3 (fled) from rendering at old position when Unit 4 (shooter) is activated
        // Root cause: attackPreview was set during fight phase and never cleared when shooting started
        else if (data.game_state?.phase === "shoot" && data.game_state?.active_shooting_unit) {
          setSelectedUnitId(parseInt(data.game_state.active_shooting_unit));
          setAttackPreview(null);  // Clear stale attackPreview to prevent ghost rendering
          setMode("attackPreview");
        } else {
          setSelectedUnitId(null);
        }
      }
    } catch (err) {
      console.error('Action error:', err);
    }
  }, [gameState]);

  // Convert API units to frontend format
  const convertUnits = useCallback((apiUnits: APIGameState['units']): Unit[] => {
    return apiUnits.map(unit => {
      // AI_TURN.md: NEVER create defaults - raise errors for missing data
      if (unit.CC_RNG === undefined || unit.CC_RNG === null) {
        throw new Error(`API ERROR: Unit ${unit.id} missing required CC_RNG field`);
      }
      if (unit.ICON_SCALE === undefined || unit.ICON_SCALE === null) {
        throw new Error(`API ERROR: Unit ${unit.id} missing required ICON_SCALE field`);
      }
      if (unit.SHOOT_LEFT === undefined || unit.SHOOT_LEFT === null) {
        throw new Error(`API ERROR: Unit ${unit.id} missing required SHOOT_LEFT field`);
      }
      if (unit.ATTACK_LEFT === undefined || unit.ATTACK_LEFT === null) {
        throw new Error(`API ERROR: Unit ${unit.id} missing required ATTACK_LEFT field`);
      }
      
      return {
        id: parseInt(unit.id) || unit.id as any,
        name: unit.unitType,
        type: unit.unitType,
        player: unit.player as PlayerId,
        col: unit.col,
        row: unit.row,
        color: unit.player === 0 ? 0x244488 : 0x882222,
        MOVE: unit.MOVE,
        HP_MAX: unit.HP_MAX,
        HP_CUR: unit.HP_CUR,
        T: unit.T,
        ARMOR_SAVE: unit.ARMOR_SAVE,
        INVUL_SAVE: unit.INVUL_SAVE,
        RNG_RNG: unit.RNG_RNG,
        RNG_DMG: unit.RNG_DMG,
        RNG_NB: unit.RNG_NB,
        RNG_ATK: unit.RNG_ATK,
        RNG_STR: unit.RNG_STR,
        RNG_AP: unit.RNG_AP,
        CC_DMG: unit.CC_DMG,
        CC_RNG: unit.CC_RNG,
        CC_NB: unit.CC_NB,
        CC_ATK: unit.CC_ATK,
        CC_STR: unit.CC_STR,
        CC_AP: unit.CC_AP,
        ICON: unit.ICON,
        ICON_SCALE: unit.ICON_SCALE,
        SHOOT_LEFT: unit.SHOOT_LEFT,
        ATTACK_LEFT: unit.ATTACK_LEFT,
      };
    });
  }, []);

  // Helper function using backend state only
  const determineClickTarget = useCallback((unitId: number, gameState: APIGameState): string => {
    if (!gameState) return "elsewhere";
    
    const unit = gameState.units.find((u: any) => parseInt(u.id) === unitId);
    if (!unit) return "elsewhere";
    
    const currentPlayer = gameState.current_player;
    const activeShooterId = gameState.active_shooting_unit ? parseInt(gameState.active_shooting_unit) : null;
    
    if (unit.player === currentPlayer) {
      if (unitId === activeShooterId) {
        return "active_unit";
      } else {
        return "friendly";
      }
    } else {
      return "enemy";
    }
  }, []);

  // AI_TURN.md: Backend-driven shooting phase management
  const handleShootingPhaseClick = useCallback(async (unitId: number, clickType: 'left' | 'right') => {
    if (!gameState) return;
    
    const clickTarget = determineClickTarget(unitId, gameState);
    const activeShooterId = gameState.active_shooting_unit;
    
    // AI_TURN.md: Backend handles all context awareness
    const action = {
      action: clickType === 'left' ? 'left_click' : 'right_click',
      unitId: activeShooterId || selectedUnitId?.toString(),
      targetId: unitId.toString(),
      clickTarget: clickTarget
    };
    
    await executeAction(action);
  }, [gameState, selectedUnitId, determineClickTarget, executeAction]);

  // Event handlers aligned with backend
  const handleSelectUnit = useCallback(async (unitId: number | string | null) => {
    const numericUnitId = typeof unitId === 'string' ? parseInt(unitId) : unitId;
    
    // AI_TURN.md: Shooting phase click handling
    // AI_TURN.md: Shooting phase click handling
    if (gameState && gameState.phase === "shoot") {
      if (numericUnitId !== null) {
        if (!gameState.shoot_activation_pool) {
          throw new Error(`API ERROR: Missing required shoot_activation_pool during shooting phase`);
        }
        const shootActivationPool = gameState.shoot_activation_pool.map(id => parseInt(id));
        
        if (shootActivationPool.includes(numericUnitId) && !gameState.active_shooting_unit) {
          await executeAction({
            action: "activate_unit", 
            unitId: numericUnitId.toString()
          });
          return;
        } else if (gameState.active_shooting_unit) {
          await executeAction({
            action: "left_click",
            unitId: gameState.active_shooting_unit,
            targetId: numericUnitId.toString(),
            clickTarget: determineClickTarget(numericUnitId, gameState)
          });
          return;
        }
      }
      return;
    }
    
    // Normal unit selection for other phases
    setSelectedUnitId(numericUnitId);
    setMode("select");
    setMovePreview(null);
    setTargetPreview(null);
    // Remove all frontend shooting state - backend manages everything
  }, [gameState, handleShootingPhaseClick, executeAction]);

  // Right-click handler for shooting phase
  const handleRightClick = useCallback(async (unitId: number) => {
    if (gameState?.phase === "shoot") {
      await handleShootingPhaseClick(unitId, 'right');
    }
  }, [gameState, handleShootingPhaseClick]);

  const handleSkipUnit = useCallback(async (unitId: number | string) => {
    const action = {
      action: "skip",
      unitId: typeof unitId === 'string' ? unitId : unitId.toString(),
    };
    
    try {
      await executeAction(action);
      setSelectedUnitId(null);
      setMode("select");
    } catch (error) {
      console.error("Skip unit failed:", error);
    }
  }, [executeAction]);

  const handleStartMovePreview = useCallback((unitId: number | string, col: number | string, row: number | string) => {
    setMovePreview({
      unitId: typeof unitId === 'string' ? parseInt(unitId) : unitId,
      destCol: typeof col === 'string' ? parseInt(col) : col,
      destRow: typeof row === 'string' ? parseInt(row) : row,
    });
    setMode("movePreview");
  }, []);

  const handleDirectMove = useCallback(async (unitId: number | string, col: number | string, row: number | string) => {
    
    const action = {
      action: "move",
      unitId: typeof unitId === 'string' ? unitId : unitId.toString(),
      destCol: typeof col === 'string' ? parseInt(col) : col,
      destRow: typeof row === 'string' ? parseInt(row) : row,
    };
    
    try {
      await executeAction(action);
      setMovePreview(null);
      setMode("select");
    } catch (error) {
      console.error("Move failed:", error);
    }
  }, [executeAction]);

  const handleConfirmMove = useCallback(async () => {
    if (movePreview) {
      await handleDirectMove(movePreview.unitId, movePreview.destCol, movePreview.destRow);
    }
  }, [movePreview, handleDirectMove]);

  const handleCancelMove = useCallback(() => {
    setMovePreview(null);
    setMode("select");
  }, []);

  // AI_TURN.md: Backend handles all shooting logic - frontend just sends clicks
  const handleShoot = useCallback(async (_shooterId: number | string, targetId: number | string) => {
    // Convert to left_click action that backend understands
    await handleShootingPhaseClick(typeof targetId === 'string' ? parseInt(targetId) : targetId, 'left');
  }, [handleShootingPhaseClick]);

  const handleSkipShoot = useCallback(async (unitId: number | string, actionType: 'wait' | 'action' = 'action') => {
    // Convert to right_click or skip action
    if (actionType === 'wait') {
      await handleRightClick(typeof unitId === 'string' ? parseInt(unitId) : unitId);
    } else {
      await executeAction({
        action: "skip",
        unitId: typeof unitId === 'string' ? unitId : unitId.toString()
      });
    }
  }, [handleRightClick, executeAction]);

  // AI_TURN.md: Charge activation - sends left_click to trigger 2d6 roll and destination building
  const handleActivateCharge = useCallback(async (chargerId: number | string) => {
    console.log("🎯 handleActivateCharge called with chargerId:", chargerId);
    const numericChargerId = typeof chargerId === 'string' ? parseInt(chargerId) : chargerId;
    console.log("🎯 Converted to numeric:", numericChargerId);

    // Send left_click action to backend
    // Backend will call _handle_unit_activation which:
    // 1. Rolls 2d6 for charge_range
    // 2. Builds valid_charge_destinations_pool via BFS pathfinding
    // 3. Returns destinations for orange highlighting
    console.log("🎯 Sending executeAction with:", {
      action: "left_click",
      unitId: numericChargerId.toString()
    });
    await executeAction({
      action: "left_click",
      unitId: numericChargerId.toString()
    });
    console.log("🎯 executeAction completed");
  }, [executeAction]);

  // AI_TURN.md: Fight activation - sends activate_unit to activate unit and get valid targets
  const handleActivateFight = useCallback(async (fighterId: number | string) => {
    const numericFighterId = typeof fighterId === 'string' ? parseInt(fighterId) : fighterId;

    // Send activate_unit action to backend
    // Backend will call _handle_fight_unit_activation which:
    // 1. Sets ATTACK_LEFT = CC_NB
    // 2. Builds valid_targets list (enemies adjacent within CC_RNG)
    // 3. Returns waiting_for_player if targets exist, triggering attackPreview mode
    // Backend will reject if unit not in current pool
    await executeAction({
      action: "activate_unit",
      unitId: numericFighterId.toString()
    });
  }, [executeAction]);

  const handleFightAttack = useCallback(async (attackerId: number | string, targetId: number | string | null) => {
    // AI_TURN.md: Fight action - send fight action to backend
    if (targetId === null) {
      console.warn("🟠 Fight attack called with null target");
      return;
    }

    const numericAttackerId = typeof attackerId === 'string' ? parseInt(attackerId) : attackerId;
    const numericTargetId = typeof targetId === 'string' ? parseInt(targetId) : targetId;

    await executeAction({
      action: "fight",
      unitId: numericAttackerId.toString(),
      targetId: numericTargetId.toString()
    });
  }, [executeAction]);

  const handleMoveCharger = useCallback(async (chargerId: number | string, destCol: number, destRow: number) => {
    console.log("🎯 handleMoveCharger called with:", { chargerId, destCol, destRow });
    const numericChargerId = typeof chargerId === 'string' ? parseInt(chargerId) : chargerId;

    // AI_TURN.md: Find target enemy adjacent to destination
    if (!gameState) return;

    const charger = gameState.units.find(u => parseInt(u.id) === numericChargerId);
    if (!charger) {
      console.error("🟠 Charger unit not found:", numericChargerId);
      return;
    }

    // Find enemy units adjacent to destination (within CC_RNG)
    const enemies = gameState.units.filter(u =>
      u.player !== charger.player &&
      parseInt(u.HP_CUR) > 0
    );

    const destCube = offsetToCube(destCol, destRow);
    let targetEnemy = null;

    for (const enemy of enemies) {
      const enemyCube = offsetToCube(enemy.col, enemy.row);
      const distance = cubeDistance(destCube, enemyCube);
      if (distance <= (charger.CC_RNG || 1)) {
        targetEnemy = enemy;
        break; // Use first adjacent enemy
      }
    }

    if (!targetEnemy) {
      console.error("🟠 No enemy found adjacent to destination:", { destCol, destRow });
      return;
    }

    console.log("🎯 Target enemy found:", targetEnemy.id);

    // AI_TURN.md: Send charge action with correct field names
    await executeAction({
      action: "charge",
      unitId: numericChargerId.toString(),
      destCol: destCol,
      destRow: destRow,
      targetId: targetEnemy.id.toString()
    });
    console.log("🎯 handleMoveCharger completed");
  }, [executeAction, gameState]);

  const handleStartTargetPreview = useCallback(async (shooterId: number | string, targetId: number | string) => {
    const numericShooterId = typeof shooterId === 'number' ? shooterId : parseInt(shooterId);
    const numericTargetId = typeof targetId === 'number' ? targetId : parseInt(targetId);
    
    // Send backend action to trigger target selection and blinking response
    await executeAction({
      action: "left_click",
      unitId: numericShooterId.toString(),
      targetId: numericTargetId.toString(),
      clickTarget: "enemy"
    });
    
    // Calculate actual probabilities using game units
    const shooter = gameState?.units.find(u => parseInt(u.id) === numericShooterId);
    const target = gameState?.units.find(u => parseInt(u.id) === numericTargetId);
    
    let hitProbability = 0.5;
    let woundProbability = 0.5;
    let saveProbability = 0.5;
    let potentialDamage = 0;
    
    if (shooter && target) {
      // Calculate hit probability (need 7 - RNG_ATK or higher on d6)
      const hitTarget = 7 - shooter.RNG_ATK;
      hitProbability = Math.max(0, (7 - hitTarget) / 6);
      
      // Calculate wound probability based on STR vs T
      const strength = shooter.RNG_STR;
      const toughness = target.T;
      let woundTarget = 4; // Default
      
      if (strength >= toughness * 2) woundTarget = 2;
      else if (strength > toughness) woundTarget = 3;
      else if (strength === toughness) woundTarget = 4;
      else if (strength * 2 <= toughness) woundTarget = 6;
      else woundTarget = 5;
      
      woundProbability = Math.max(0, (7 - woundTarget) / 6);
      
      // Calculate save probability (save succeeds if roll >= save target)
      const saveTarget = Math.max(2, Math.min(target.ARMOR_SAVE - shooter.RNG_AP, target.INVUL_SAVE));
      saveProbability = Math.max(0, (saveTarget - 1) / 6);
      
      // Potential damage per shot
      potentialDamage = shooter.RNG_DMG;
    }
    
    const overallProbability = hitProbability * woundProbability * (1 - saveProbability);
    const expectedDamage = overallProbability * potentialDamage;
    
    // Create target preview with blinking animation
    const preview = {
      shooterId: numericShooterId,
      targetId: numericTargetId,
      currentBlinkStep: 0,
      totalBlinkSteps: 2,
      blinkTimer: null as number | null,
      hitProbability,
      woundProbability,
      saveProbability,
      overallProbability,
      potentialDamage,
      expectedDamage
    };
    
    // Start blinking animation with functional state updates
    preview.blinkTimer = window.setInterval(() => {
      setTargetPreview(prevPreview => {
        if (!prevPreview) return null;
        const newStep = ((prevPreview.currentBlinkStep || 0) + 1) % (prevPreview.totalBlinkSteps || 2);
        return {
          ...prevPreview,
          currentBlinkStep: newStep,
          lastUpdate: Date.now()
        };
      });
    }, 500);
    
    setTargetPreview(preview);
    setMode("targetPreview");
  }, [gameState]);

  // Cleanup interval when targetPreview changes or component unmounts
  useEffect(() => {
    return () => {
      if (targetPreview?.blinkTimer) {
        clearInterval(targetPreview.blinkTimer);
      }
    };
  }, [targetPreview?.blinkTimer]);

  // Get eligible units
  const getEligibleUnitIds = useCallback((): number[] => {
    if (!gameState) {
      throw new Error(`API ERROR: gameState is null when getting eligible units`);
    }

    if (gameState.phase === 'move') {
      if (!gameState.move_activation_pool) {
        throw new Error(`API ERROR: Missing move_activation_pool in move phase`);
      }
      return gameState.move_activation_pool.map(id => parseInt(id)).filter(id => !isNaN(id));
    } else if (gameState.phase === 'shoot') {
      if (!gameState.shoot_activation_pool || gameState.shoot_activation_pool.length === 0) {
        return []; // Empty pool is valid - let backend handle phase advancement
      }
      return gameState.shoot_activation_pool.map(id => parseInt(id)).filter(id => !isNaN(id));
    } else if (gameState.phase === 'charge') {
      if (!gameState.charge_activation_pool || gameState.charge_activation_pool.length === 0) {
        return []; // Empty pool is valid - phase will auto-advance
      }
      const eligible = gameState.charge_activation_pool.map(id => parseInt(id)).filter(id => !isNaN(id));
      console.log("🔍 getEligibleUnitIds returning for charge phase:", eligible);
      return eligible;
    } else if (gameState.phase === 'fight') {
      // AI_TURN.md COMPLIANCE: Fight phase has sub-phases - only show units from current sub-phase
      const subphase = gameState.fight_subphase;

      if (subphase === 'charging') {
        // Sub-Phase 1: Only charging units (current player's charged units)
        if (!gameState.charging_activation_pool) {
          return [];
        }
        return gameState.charging_activation_pool.map(id => parseInt(id)).filter(id => !isNaN(id));
      } else if (subphase === 'alternating_non_active') {
        // Sub-Phase 2: Non-active player's turn in alternating
        if (!gameState.non_active_alternating_activation_pool) {
          return [];
        }
        return gameState.non_active_alternating_activation_pool.map(id => parseInt(id)).filter(id => !isNaN(id));
      } else if (subphase === 'alternating_active') {
        // Sub-Phase 2: Active player's turn in alternating
        if (!gameState.active_alternating_activation_pool) {
          return [];
        }
        return gameState.active_alternating_activation_pool.map(id => parseInt(id)).filter(id => !isNaN(id));
      } else if (subphase === 'cleanup_non_active') {
        // Sub-Phase 3: Cleanup - only non-active pool has units left
        if (!gameState.non_active_alternating_activation_pool) {
          return [];
        }
        return gameState.non_active_alternating_activation_pool.map(id => parseInt(id)).filter(id => !isNaN(id));
      } else if (subphase === 'cleanup_active') {
        // Sub-Phase 3: Cleanup - only active pool has units left
        if (!gameState.active_alternating_activation_pool) {
          return [];
        }
        return gameState.active_alternating_activation_pool.map(id => parseInt(id)).filter(id => !isNaN(id));
      }

      // No subphase set or unknown subphase - return empty (phase not ready)
      return [];
    }

    throw new Error(`API ERROR: Unsupported phase for eligible units: ${gameState.phase}`);
  }, [gameState]);

  const getChargeDestinations = useCallback((_unitId: number) => {
    return chargeDestinations;
  }, [chargeDestinations]);

  // Return props compatible with BoardPvp
  if (error) {
    throw new Error(`API ERROR: ${error}`);
  }
  
  if (loading || !gameState) {
    return {
      loading: true,
      error: null,
      units: [],
      selectedUnitId: null,
      eligibleUnitIds: [],
      mode: "select" as const,
      movePreview: null,
      attackPreview: null,
      targetPreview: null,
      currentPlayer: null,
      maxTurns: null,
      unitsMoved: [],
      unitsCharged: [],
      unitsAttacked: [],
      unitsFled: [],
      phase: null,
      gameState: null,
      onSelectUnit: () => {},
      onSkipUnit: () => {},
      onStartMovePreview: () => {},
      onDirectMove: () => {},
      onStartAttackPreview: () => {},
      onConfirmMove: () => {},
      onCancelMove: () => {},
      onShoot: () => {},
      onSkipShoot: () => {},
      onStartTargetPreview: () => {},
      onFightAttack: () => {},
      onCharge: () => {},
      onActivateCharge: () => {},
      onMoveCharger: () => {},
      onCancelCharge: () => {},
      onValidateCharge: () => {},
      onLogChargeRoll: () => {},
      getChargeDestinations: () => [],
      blinkingUnits: [],
      isBlinkingActive: false,
      blinkState: false,
      executeAITurn: async () => {}, // Add missing executeAITurn function
    };
  }

  const returnObject = {
    loading: false,
    error: null,
    units: convertUnits(gameState.units),
    selectedUnitId,
    eligibleUnitIds: getEligibleUnitIds(),
    mode,
    movePreview,
    attackPreview,
    targetPreview,
    currentPlayer: gameState.current_player as PlayerId,
    maxTurns: maxTurnsFromConfig,
    unitsMoved: gameState.units_moved ? gameState.units_moved.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_moved array'); })(),
    unitsCharged: gameState.units_charged ? gameState.units_charged.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_charged array'); })(),
    unitsAttacked: gameState.units_attacked ? gameState.units_attacked.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_attacked array'); })(),
    unitsFled: gameState.units_fled ? gameState.units_fled.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_fled array'); })(),
    phase: gameState.phase as "move" | "shoot" | "charge" | "fight",
    // AI_TURN.md COMPLIANCE: Expose fight_subphase for UnitRenderer click handling
    fightSubPhase: gameState.fight_subphase as "charging" | "alternating_non_active" | "alternating_active" | "cleanup_non_active" | "cleanup_active" | null,
    gameState: {
      episode_steps: gameState.episode_steps,
      units: convertUnits(gameState.units),
      currentPlayer: gameState.current_player as PlayerId,
      phase: gameState.phase as "move" | "shoot" | "charge" | "fight",
      mode,
      selectedUnitId,
      unitsMoved: gameState.units_moved ? gameState.units_moved.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_moved array in gameState'); })(),
      unitsCharged: gameState.units_charged ? gameState.units_charged.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_charged array in gameState'); })(),
      unitsAttacked: gameState.units_attacked ? gameState.units_attacked.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_attacked array in gameState'); })(),
      unitsFled: gameState.units_fled ? gameState.units_fled.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_fled array in gameState'); })(),
      targetPreview: null,
      currentTurn: gameState.turn,
      maxTurns: maxTurnsFromConfig,
      unitChargeRolls: {},
      pve_mode: gameState.pve_mode, // Add PvE mode flag
    },
    onSelectUnit: handleSelectUnit,
    onSkipUnit: handleSkipUnit,
    onStartMovePreview: handleStartMovePreview,
    onDirectMove: (unitId: number | string, col: number | string, row: number | string) => {
      return handleDirectMove(unitId, col, row);
    },
    onStartAttackPreview: (unitId: number) => {
      setSelectedUnitId(typeof unitId === 'string' ? parseInt(unitId) : unitId);
      // AI_TURN.md COMPLIANCE: Clear stale attackPreview when entering attackPreview mode
      // This prevents units from rendering at old positions from previous fight phases
      setAttackPreview(null);
      setMode("attackPreview");
    },
    onConfirmMove: handleConfirmMove,
    onCancelMove: handleCancelMove,
    onShoot: handleShoot,
    onSkipShoot: handleSkipShoot,
    onStartTargetPreview: handleStartTargetPreview,
    onFightAttack: handleFightAttack,
    onActivateFight: handleActivateFight,
    onCharge: () => {},
    onActivateCharge: handleActivateCharge,
    onMoveCharger: handleMoveCharger,
    onCancelCharge: () => {},
    onValidateCharge: () => {},
onLogChargeRoll: () => {},
    getChargeDestinations,
    // Export blinking state for HP bar components
    blinkingUnits: blinkingUnits.unitIds,
    isBlinkingActive: blinkingUnits.blinkTimer !== null,
    blinkState: blinkingUnits.blinkState,
    // Export charge roll info for failed charge display
    chargingUnitId: failedChargeRoll ? failedChargeRoll.unitId : null,
    chargeRoll: failedChargeRoll ? failedChargeRoll.roll : null,
    chargeSuccess: failedChargeRoll ? false : undefined,
    // Export charge target ID for target icon display (for both successful and failed charges)
    chargeTargetId: (() => {
      const targetId = failedChargeRoll?.targetId || successfulChargeTarget?.targetId || null;
      if (targetId) {
        console.log("🎯 Exporting chargeTargetId:", targetId, "from failedChargeRoll:", failedChargeRoll?.targetId, "from successfulChargeTarget:", successfulChargeTarget?.targetId);
      }
      return targetId;
    })(),
    // Add AI turn execution for PvE mode
    executeAITurn: async () => {
      if (aiTurnInProgress) {
        console.log('executeAITurn already running, skipping');
        return;
      }
      aiTurnInProgress = true;
      
      const urlParams = new URLSearchParams(window.location.search);
      const isPvEFromURL = urlParams.get('mode') === 'pve' || window.location.pathname.includes('/pve');
      
      console.log('executeAITurn check:', {
        hasGameState: !!gameState,
        gameStatePveMode: gameState?.pve_mode,
        isPvEFromURL,
        currentPlayer: gameState?.current_player,
        phase: gameState?.phase,
        aiUnitsInPool: gameState?.phase === 'shoot' ? gameState?.shoot_activation_pool?.filter(id => {
          const unit = gameState?.units.find(u => u.id === id);
          return unit?.player === 1;
        }).length : gameState?.phase === 'move' ? gameState?.move_activation_pool?.filter(id => {
          const unit = gameState?.units.find(u => u.id === id);
          return unit?.player === 1;
        }).length : 0,
        willProceed: !(!gameState || (!gameState.pve_mode && !isPvEFromURL))
      });
      
      if (!gameState || (!gameState.pve_mode && !isPvEFromURL)) {
        console.log('executeAITurn returning early - not PvE mode');
        aiTurnInProgress = false;
        return;
      }
      
      // Check if it's AI player's turn (player 1)
      if (gameState.current_player !== 1) {
        console.log(`executeAITurn skipped - not AI player turn (current: ${gameState.current_player})`);
        aiTurnInProgress = false;
        return;
      }
      
      // Check if AI has eligible units in current phase
      const phaseCheck = gameState.phase;
      let eligibleAICount = 0;
      
      if (phaseCheck === 'shoot' && gameState.shoot_activation_pool) {
        eligibleAICount = gameState.shoot_activation_pool.filter(unitId => {
          const unit = gameState.units.find(u => u.id === unitId);
          return unit && unit.player === 1;
        }).length;
      } else if (phaseCheck === 'move' && gameState.move_activation_pool) {
        eligibleAICount = gameState.move_activation_pool.filter(unitId => {
          const unit = gameState.units.find(u => u.id === unitId);
          return unit && unit.player === 1;
        }).length;
      }
      
      if (eligibleAICount === 0) {
        console.log(`executeAITurn skipped - AI has no eligible units in ${phaseCheck} phase (total pool: ${phaseCheck === 'shoot' ? gameState.shoot_activation_pool?.length : gameState.move_activation_pool?.length})`);
        aiTurnInProgress = false;
        return;
      }
      
      console.log(`executeAITurn proceeding - AI has ${eligibleAICount} eligible units in ${phaseCheck} phase`);
      
      // Check if it's AI player's turn (player 1)
      if (gameState.current_player !== 1) {
        console.log(`executeAITurn returning early - not AI player turn (current: ${gameState.current_player})`);
        aiTurnInProgress = false;
        return;
      }
      
      // Check if AI has eligible units in current phase
      const currentPhase = gameState.phase;
      let aiEligibleUnits = 0;
      
      if (currentPhase === 'move' && gameState.move_activation_pool) {
        aiEligibleUnits = gameState.move_activation_pool.filter(unitId => {
          const unit = gameState.units.find(u => u.id === unitId);
          return unit && unit.player === 1;
        }).length;
      } else if (currentPhase === 'shoot' && gameState.shoot_activation_pool) {
        aiEligibleUnits = gameState.shoot_activation_pool.filter(unitId => {
          const unit = gameState.units.find(u => u.id === unitId);
          return unit && unit.player === 1;
        }).length;
      }
      
      if (aiEligibleUnits === 0) {
        console.log(`executeAITurn returning early - no eligible AI units in ${currentPhase} phase (pool: ${currentPhase === 'move' ? gameState.move_activation_pool : gameState.shoot_activation_pool})`);
        aiTurnInProgress = false;
        return;
      }
      
      console.log(`executeAITurn proceeding - AI has ${aiEligibleUnits} eligible units in ${currentPhase} phase`);
      
      console.log('executeAITurn proceeding with sequential AI processing');
      
      // Helper function to make AI movement decision
      const makeMovementDecision = (validDestinations: number[][], unitId: string, currentGameState: any) => {
        if (!validDestinations || validDestinations.length === 0) {
          return { action: 'skip', unitId };
        }
        
        // Strategy: Move toward nearest enemy using FRESH game state
        const enemies = currentGameState?.units.filter((u: any) => u.player === 0 && u.HP_CUR > 0) || [];
        
        if (enemies.length === 0) {
          // No enemies - just take first destination
          const dest = validDestinations[0];
          return {
            action: 'move',
            unitId,
            destCol: dest[0],
            destRow: dest[1]
          };
        }
        
        // Find nearest enemy using fresh unit positions
        const currentUnit = currentGameState?.units.find((u: any) => u.id === unitId);
        if (!currentUnit) {
          console.log(`AI DECISION ERROR: Unit ${unitId} not found in current game state`);
          const dest = validDestinations[0];
          return {
            action: 'move',
            unitId,
            destCol: dest[0],
            destRow: dest[1]
          };
        }
        
        const nearestEnemy = enemies.reduce((nearest: any, enemy: any) => {
          const distToCurrent = Math.abs(enemy.col - currentUnit.col) + Math.abs(enemy.row - currentUnit.row);
          const distToNearest = Math.abs(nearest.col - currentUnit.col) + Math.abs(nearest.row - currentUnit.row);
          return distToCurrent < distToNearest ? enemy : nearest;
        });
        
        console.log(`AI DECISION DEBUG: Nearest enemy at (${nearestEnemy.col}, ${nearestEnemy.row})`);
        
        // Pick destination closest to nearest enemy FROM VALID DESTINATIONS ONLY
        const bestDestination = validDestinations.reduce((best, dest) => {
          const distToEnemy = Math.abs(dest[0] - nearestEnemy.col) + Math.abs(dest[1] - nearestEnemy.row);
          const bestDistToEnemy = Math.abs(best[0] - nearestEnemy.col) + Math.abs(best[1] - nearestEnemy.row);
          // console.log(`AI DECISION CALC: Destination (${dest[0]}, ${dest[1]}) distance to enemy: ${distToEnemy}, current best: ${bestDistToEnemy}`);
          return distToEnemy < bestDistToEnemy ? dest : best;
        });
        
        console.log(`AI DECISION FINAL: Selected destination (${bestDestination[0]}, ${bestDestination[1]}) from ${validDestinations.length} valid options`);
        console.log(`AI DECISION FINAL: Target enemy at (${nearestEnemy.col}, ${nearestEnemy.row})`);
        console.log(`AI DECISION FINAL: Is selected destination in valid list?`, validDestinations.some(dest => dest[0] === bestDestination[0] && dest[1] === bestDestination[1]));
        
        return {
          action: 'move',
          unitId,
          destCol: bestDestination[0],
          destRow: bestDestination[1]
        };
      };
      
      // Helper function to make AI shooting decision
      const makeShootingDecision = (validTargets: string[], unitId: string, currentGameState: any) => {
        if (!validTargets || validTargets.length === 0) {
          return { action: 'skip', unitId };
        }
        
        // Strategy: Shoot nearest/most threatening target using fresh game state
        const shooter = currentGameState?.units.find((u: any) => u.id === unitId);
        if (!shooter) {
          return {
            action: 'shoot',
            unitId,
            targetId: validTargets[0]
          };
        }
        
        // Find nearest target
        const nearestTarget = validTargets.reduce((nearest, targetId) => {
          const target = currentGameState?.units.find((u: any) => u.id === targetId);
          const nearestTargetUnit = currentGameState?.units.find((u: any) => u.id === nearest);
          
          if (!target || !nearestTargetUnit) return nearest;
          
          const distToCurrent = Math.abs(target.col - shooter.col) + Math.abs(target.row - shooter.row);
          const distToNearest = Math.abs(nearestTargetUnit.col - shooter.col) + Math.abs(nearestTargetUnit.row - shooter.row);
          
          return distToCurrent < distToNearest ? targetId : nearest;
        });
        
        return {
          action: 'shoot',
          unitId,
          targetId: nearestTarget
        };
      };
      
      try {
        let totalUnitsProcessed = 0;
        let maxIterations = 20;
        let iteration = 0;
        
        while (iteration < maxIterations) {
          iteration++;
          
          console.log(`AI Sequential Step ${iteration}: Activating next AI unit`);
          
          // Step 1: Call backend to activate next AI unit
          const aiResponse = await fetch(`${API_BASE}/game/ai-turn`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
          });
          
          if (!aiResponse.ok) {
            throw new Error(`AI activation failed: ${aiResponse.status}`);
          }
          
          const activationData = await aiResponse.json();
          console.log(`AI Step ${iteration} ACTIVATION:`, activationData);
          
          // Process AI activation logs immediately
          if (activationData.action_logs && activationData.action_logs.length > 0) {
            activationData.action_logs.forEach((logEntry: any) => {
              console.log(`🎯 AI ACTIVATION LOG: ${logEntry.message}`);
              
              window.dispatchEvent(new CustomEvent('backendLogEvent', {
                detail: {
                  type: logEntry.type,
                  message: logEntry.message,
                  turn: gameState?.turn || logEntry.turn,  // Use live turn
                  phase: logEntry.phase,
                  shooterId: logEntry.shooterId,
                  targetId: logEntry.targetId,
                  player: logEntry.player,
                  damage: logEntry.damage,
                  target_died: logEntry.target_died,
                  hitRoll: logEntry.hitRoll,
                  woundRoll: logEntry.woundRoll,
                  saveRoll: logEntry.saveRoll,
                  saveTarget: logEntry.saveTarget,
                  action_name: logEntry.action_name,
                  reward: logEntry.reward,
                  is_ai_action: logEntry.is_ai_action,
                  timestamp: new Date()
                }
              }));
            });
          }
          
          if (!activationData.success) {
            console.error(`AI activation failed:`, activationData.error);
            break;
          }
          
          // Update game state from activation
          setGameState(activationData.game_state);
          
          // Step 2: Check if we got a preview response requiring decision
          if (activationData.result?.waiting_for_player) {
            console.log(`AI Step ${iteration}: Preview received - making immediate decision`);
            
            let aiDecision;
            const unitId = activationData.result?.unitId || 
                          (activationData.game_state?.active_movement_unit) ||
                          (activationData.game_state?.active_shooting_unit);
            
            // Step 3: Make AI decision based on preview data using FRESH game state
            if (activationData.result.valid_destinations) {
              // Movement phase - pick destination using fresh backend state
              aiDecision = makeMovementDecision(
                activationData.result.valid_destinations, 
                unitId,
                activationData.game_state
              );
            } else if (activationData.result.validTargets) {
              // Shooting phase - pick target using fresh backend state
              aiDecision = makeShootingDecision(
                activationData.result.validTargets, 
                unitId,
                activationData.game_state
              );
            } else {
              console.error('Unknown preview type:', activationData.result);
              break;
            }
            
            console.log(`AI Step ${iteration}: Decision made:`, aiDecision);
            
            // Step 4: Send AI decision immediately
            const decisionResponse = await fetch(`${API_BASE}/game/action`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(aiDecision)
            });
            
            if (!decisionResponse.ok) {
              throw new Error(`AI decision failed: ${decisionResponse.status}`);
            }
            
            const decisionData = await decisionResponse.json();
            console.log(`AI Step ${iteration}: Decision executed:`, decisionData);
            
            if (decisionData.success) {
              // Process action logs
              if (decisionData.action_logs && decisionData.action_logs.length > 0) {
                decisionData.action_logs.forEach((logEntry: any) => {
                  console.log(`🎯 AI ACTION LOG: ${logEntry.message}`);
                  console.log("🎯 ACTION LOG FULL DATA:", logEntry);
                  
                  window.dispatchEvent(new CustomEvent('backendLogEvent', {
                    detail: {
                      type: logEntry.type,
                      message: logEntry.message,
                      turn: logEntry.turn,
                      phase: logEntry.phase,
                      shooterId: logEntry.shooterId,
                      targetId: logEntry.targetId,
                      player: logEntry.player,
                      damage: logEntry.damage,
                      target_died: logEntry.target_died,
                      hitRoll: logEntry.hitRoll,
                      woundRoll: logEntry.woundRoll,
                      saveRoll: logEntry.saveRoll,
                      saveTarget: logEntry.saveTarget,
                      action_name: logEntry.action_name,
                      reward: logEntry.reward,
                      is_ai_action: logEntry.is_ai_action,
                      timestamp: new Date()
                    }
                  }));
                });
              }
              
              // Update game state from decision
              setGameState(decisionData.game_state);
              totalUnitsProcessed++;
              
              // Check if phase complete
              if (decisionData.result?.phase_complete) {
                console.log(`AI Step ${iteration}: Phase complete`);
                break;
              }
              
            } else {
              console.error('AI decision failed:', decisionData);
              break;
            }
            
          } else if (activationData.result?.activation_ended) {
            // Unit completed activation immediately (SKIP, no valid targets, etc.)
            console.log(`AI Step ${iteration}: Unit completed immediately - ${activationData.result.endType}`);
            totalUnitsProcessed++;
            
            // Check if phase complete after unit completion
            if (activationData.result?.phase_complete) {
              console.log(`AI Step ${iteration}: Phase complete after unit completion`);
              break;
            }
            
          } else if (activationData.result?.phase_complete) {
            // Phase already complete
            console.log(`AI Step ${iteration}: Phase complete - no more units`);
            break;
            
          } else {
            // Unexpected response format
            console.log(`AI Step ${iteration}: Unexpected response - continuing`);
          }
          
          // Small delay for UX
          await new Promise(resolve => setTimeout(resolve, 150));
        }
        
        if (iteration >= maxIterations) {
          console.warn(`AI reached maximum iterations (${maxIterations})`);
        }
        
        console.log(`AI Turn Complete: processed ${totalUnitsProcessed} units in ${iteration} steps`);
        
      } catch (err) {
        console.error('AI turn error:', err);
        setError(`AI turn failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
      } finally {
        aiTurnInProgress = false;
      }
    },
  };
  
  return returnObject;
};