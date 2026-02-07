// frontend/src/hooks/useEngineAPI.ts
import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import type { Unit, PlayerId, GameMode } from '../types';
import { offsetToCube, cubeDistance } from '../utils/gameHelpers';
import { getMeleeRange } from '../utils/weaponHelpers';
import { getPreferredRangedWeaponAgainstTarget } from '../utils/probabilityCalculator';

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
    // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Replace single weapon fields with arrays
    RNG_WEAPONS: Array<{
      code_name: string;
      display_name: string;
      RNG?: number;
      NB: number;
      ATK: number;
      STR: number;
      AP: number;
      DMG: number;
    }>;
    available_weapons?: Array<{
      index: number;
      weapon: Record<string, unknown>;
      can_use: boolean;
      reason?: string;
    }>;
    CC_WEAPONS: Array<{
      code_name: string;
      display_name: string;
      NB: number;
      ATK: number;
      STR: number;
      AP: number;
      DMG: number;
    }>;
    selectedRngWeaponIndex?: number;
    selectedCcWeaponIndex?: number;
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
  units_advanced?: string[]; // Units that have advanced this turn
  move_activation_pool: string[];
  shoot_activation_pool: string[];
  charge_activation_pool: string[];
  charging_activation_pool: string[];
  active_alternating_activation_pool: string[];
  non_active_alternating_activation_pool: string[];
  fight_subphase: string | null;
  units_cache?: Record<string, { col: number; row: number; HP_CUR: number; player: number }>;
  active_movement_unit?: string;
  active_shooting_unit?: string;
  active_fight_unit?: string;
  pve_mode?: boolean;
  victory_points?: Record<string, number>;
  primary_objective?: Record<string, unknown> | Array<Record<string, unknown>> | null;
}

export const useEngineAPI = () => {
  const [gameState, setGameState] = useState<APIGameState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [maxTurnsFromConfig, setMaxTurnsFromConfig] = useState<number>(8);
  const [selectedUnitId, setSelectedUnitId] = useState<number | null>(null);
  const [mode, setMode] = useState<"select" | "movePreview" | "attackPreview" | "targetPreview" | "chargePreview" | "advancePreview">("select");
  const [movePreview, setMovePreview] = useState<{ unitId: number; destCol: number; destRow: number } | null>(null);
  const [attackPreview, setAttackPreview] = useState<{ unitId: number; col: number; row: number } | null>(null);
  const [chargeDestinations, setChargeDestinations] = useState<Array<{ col: number; row: number }>>([]);
  // ADVANCE_IMPLEMENTATION_PLAN.md Phase 5: Advance state management
  const [advanceDestinations, setAdvanceDestinations] = useState<Array<{ col: number; row: number }>>([]);
  const [advancingUnitId, setAdvancingUnitId] = useState<number | null>(null);
  const [advanceRoll, setAdvanceRoll] = useState<number | null>(null);
  const [advanceWarningPopup, setAdvanceWarningPopup] = useState<{ unitId: number; timestamp: number } | null>(null);
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
  const [blinkingUnits, setBlinkingUnits] = useState<{unitIds: number[], blinkTimer: number | null, attackerId?: number | null}>({unitIds: [], blinkTimer: null, attackerId: null});
  const [blinkVersion, setBlinkVersion] = useState(0);
  
  // State for failed charge roll display
  const [failedChargeRoll, setFailedChargeRoll] = useState<{unitId: number, roll: number, targetId?: number} | null>(null);
  // State for successful charge target display
  const [successfulChargeTarget, setSuccessfulChargeTarget] = useState<{unitId: number, targetId: number} | null>(null);
  
  // Track last action to detect activate_unit in shoot phase
  const lastActionRef = useRef<{action: string, phase: string, unitId?: string} | null>(null);
  
  // Load config values
  useEffect(() => {
    getMaxTurnsFromConfig().then(setMaxTurnsFromConfig);
  }, []);

  // Initialize game - FIXED: Added ref to prevent multiple calls
  const gameInitialized = useRef(false);
  
  useEffect(() => {
    if (gameInitialized.current) {
      return;
    }
    
    const startGame = async () => {
      try {
        gameInitialized.current = true;
        setLoading(true);
        
        // Detect Debug mode from URL
        const urlParams = new URLSearchParams(window.location.search);
        const isDebugMode = urlParams.get('mode') === 'debug';
        
        console.log(`Starting game in ${isDebugMode ? 'Debug' : 'PvP'} mode`);
        
        const response = await fetch(`${API_BASE}/game/start`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pve_mode: isDebugMode })
        });
        
        if (!response.ok) {
          throw new Error(`Failed to start game: ${response.status}`);
        }
        
        const data = await response.json();
        if (data.success) {
          setGameState(data.game_state);
          console.log(`Game started successfully in ${data.game_state.pve_mode ? 'Debug' : 'PvP'} mode`);
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

  // Listen for weapon selection events to update gameState
  useEffect(() => {
    const weaponSelectedHandler = (e: Event) => {
      interface WeaponSelectedEventDetail {
        gameState: APIGameState;
      }
      const { gameState: newGameState } = (e as CustomEvent<WeaponSelectedEventDetail>).detail;
      if (newGameState) {
        if (newGameState.units && newGameState.active_shooting_unit) {
          const activeId = newGameState.active_shooting_unit.toString();
          const updatedUnits = [...newGameState.units];
          const unitIndex = updatedUnits.findIndex((u: { id: string | number }) => u.id.toString() === activeId);
          if (unitIndex >= 0) {
            updatedUnits[unitIndex] = {
              ...updatedUnits[unitIndex],
              manualWeaponSelected: true
            };
            newGameState.units = updatedUnits;
          }
        }
        setGameState(newGameState);
        setBlinkVersion(prev => prev + 1);
        if (newGameState.phase === "shoot" && targetPreview) {
          const shooter = newGameState.units.find(u => {
            const unitId = typeof u.id === 'string' ? parseInt(u.id) : u.id;
            return unitId === targetPreview.shooterId;
          });
          const target = newGameState.units.find(u => {
            const unitId = typeof u.id === 'string' ? parseInt(u.id) : u.id;
            return unitId === targetPreview.targetId;
          });
          if (!shooter || !target) {
            throw new Error("Missing shooter or target when updating target preview after weapon selection");
          }
          const shooterUnit: Unit = {
            ...shooter,
            id: typeof shooter.id === 'string' ? parseInt(shooter.id) : shooter.id,
            player: shooter.player as PlayerId
          };
          const preferred = getPreferredRangedWeaponAgainstTarget(shooterUnit, target as Unit);
          if (!preferred) {
            throw new Error(`No ranged weapon available for unit ${shooterUnit.id} after weapon selection`);
          }
          if (blinkingUnits.blinkTimer) {
            clearInterval(blinkingUnits.blinkTimer);
          }
          setBlinkingUnits({unitIds: [], blinkTimer: null, attackerId: null});
          setTargetPreview(prevPreview => {
            if (!prevPreview) return null;
            return {
              ...prevPreview,
              hitProbability: preferred.hitProbability,
              woundProbability: preferred.woundProbability,
              saveProbability: preferred.saveProbability,
              overallProbability: preferred.overallProbability,
              potentialDamage: preferred.potentialDamage,
              expectedDamage: preferred.expectedDamage
            };
          });
        }
      }
    };

    window.addEventListener('weaponSelected', weaponSelectedHandler);
    return () => {
      window.removeEventListener('weaponSelected', weaponSelectedHandler);
    };
  }, [targetPreview, blinkingUnits.blinkTimer, blinkingUnits.unitIds, blinkingUnits.attackerId]);

  // Reset mode to "select" when phase changes
  useEffect(() => {
    if (gameState?.phase) {
      // Reset mode when phase changes (except if we're already in the correct mode for the phase)
      // This ensures mode is reset after fight phase ends
      setMode("select");
      setSelectedUnitId(null);
      setMovePreview(null);
      setAttackPreview(null);
      setChargeDestinations([]);
      setAdvanceDestinations([]);
      setAdvancingUnitId(null);
      setAdvanceRoll(null);
    }
  }, [gameState?.phase]);

  // Execute action via API
  const executeAction = useCallback(async (action: Record<string, unknown>) => {
    
    if (!gameState) {
      return;
    }
    
    // Track last action for auto-advance detection
    lastActionRef.current = {
      action: action.action as string,
      phase: gameState.phase,
      unitId: typeof action.unitId === 'string' || typeof action.unitId === 'number' ? String(action.unitId) : undefined
    };
    
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


      // Process detailed backend action logs FIRST
      if (data.action_logs && data.action_logs.length > 0) {
        interface ActionLogEntry {
          message?: string;
          shootDetails?: Array<Record<string, unknown>>;
          [key: string]: unknown;
        }
        data.action_logs.forEach((logEntry: ActionLogEntry) => {
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
              // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Pass through weapon name
              weaponName: logEntry.weaponName,
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
              await executeAction({ action: "advance_phase", from: "shoot" });
            }, 100);
          }
          
          // CRITICAL: Handle empty fight phase pools - all 3 pools must be empty
          if (data.game_state?.phase === "fight") {
            const chargingPool = Array.isArray(data.game_state.charging_activation_pool) ? data.game_state.charging_activation_pool : [];
            const activePool = Array.isArray(data.game_state.active_alternating_activation_pool) ? data.game_state.active_alternating_activation_pool : [];
            const nonActivePool = Array.isArray(data.game_state.non_active_alternating_activation_pool) ? data.game_state.non_active_alternating_activation_pool : [];
            
            const allPoolsEmpty = chargingPool.length === 0 && activePool.length === 0 && nonActivePool.length === 0;
            
            if (allPoolsEmpty) {
              console.log("🔥 EMPTY FIGHT POOLS DETECTED - Auto-advancing phase");
              setTimeout(async () => {
                await executeAction({ action: "advance_phase", from: "fight" });
              }, 100);
            }
          }
          
          // Handle advance execution with destination - display advance roll badge before cleanup
          // Clean up advance preview when advance is executed (advance_range returned), even if activation_ended is not set
          if (lastActionRef.current?.action === "advance" && 
            data.result?.advance_range !== undefined) {
          // Advance was executed - show badge with the roll value
          const unitId = parseInt(data.result.unitId || lastActionRef.current.unitId);
          const advanceRollValue = data.result.advance_range; // Backend returns advance_range, use as advance_roll
          setAdvanceRoll(advanceRollValue);
          setAdvancingUnitId(unitId);
          // Keep selected unit to show badge
          setSelectedUnitId(unitId);
          // Clear advance preview (destinations and mode) since advance is complete
          setAdvanceDestinations([]);
          // AI_TURN.md COMPLIANCE: Don't reset mode to "select" if unit can shoot after advance
          // If blinking_units is present, unit has valid targets and can shoot - mode will be set to "attackPreview" by blinking_units handler
          if (!data.result?.blinking_units || !data.result?.start_blinking) {
            setMode("select");
          }
        }
          
          // Check if we just activated a unit in shoot phase (use lastActionRef phase, not current phase which may have changed)
          // Backend returns allow_advance: true when unit has no valid targets
          // Don't auto-trigger advance - wait for user to click advance icon
          // AI_TURN.md: "⚠️ POINT OF NO RETURN (Human: Click ADVANCE logo)"
          // The advance roll should only be made when user explicitly clicks the advance icon
          if (lastActionRef.current?.action === "activate_unit" &&
            lastActionRef.current?.phase === "shoot" &&
            data.result?.unitId && 
            data.result?.unitId === lastActionRef.current?.unitId &&
            data.result?.allow_advance === true) {
            // Set selectedUnitId to show advance icon, but don't trigger advance automatically
            const unitId = parseInt(data.result.unitId);
            setSelectedUnitId(unitId);
            // Set mode to allow advance icon to be displayed
            setMode("select");
          }
          
          // Process backend cleanup signals
          if (data.result?.clear_preview) {
            setTargetPreview(null);
          }
          
          if (data.result?.clear_blinking_gentle) {
            // Clear central timers only - don't destroy renderer
            if (blinkingUnits.blinkTimer) {
              clearInterval(blinkingUnits.blinkTimer);
            }
            setBlinkingUnits({unitIds: [], blinkTimer: null, attackerId: null});
            
            if (targetPreview?.blinkTimer) {
              clearInterval(targetPreview.blinkTimer);
            }
            setTargetPreview(null);
          }

          if (lastActionRef.current?.phase === "shoot" && (data.result?.activation_ended || data.result?.phase_complete)) {
            if (blinkingUnits.blinkTimer) {
              clearInterval(blinkingUnits.blinkTimer);
            }
            setBlinkingUnits({unitIds: [], blinkTimer: null, attackerId: null});
            
            if (targetPreview?.blinkTimer) {
              clearInterval(targetPreview.blinkTimer);
            }
            setTargetPreview(null);
            if (data.game_state?.units && lastActionRef.current?.unitId) {
              const unitIndex = data.game_state.units.findIndex((u: { id: string | number }) =>
                u.id.toString() === lastActionRef.current?.unitId
              );
              if (unitIndex >= 0) {
                const updatedUnits = [...data.game_state.units];
                updatedUnits[unitIndex] = {
                  ...updatedUnits[unitIndex],
                  manualWeaponSelected: false
                };
                data.game_state = {
                  ...data.game_state,
                  units: updatedUnits
                };
              }
            }
          }
          
          if (data.result?.reset_mode) {
            setMode("select");
            // Clear advance state when mode resets
            setAdvanceDestinations([]);
            setAdvancingUnitId(null);
            setAdvanceRoll(null);
          }
          
          if (data.result?.clear_selected_unit) {
            setSelectedUnitId(null);
            // Clear advance state when selected unit is cleared
            setAdvanceDestinations([]);
            setAdvancingUnitId(null);
            setAdvanceRoll(null);
          }
          
          if (data.result?.clear_attack_preview && !advanceWarningPopup) {
            setMode("select");
          }
          
          // Auto-display Python console logs in browser (only during actions)
          if (data.game_state?.console_logs && data.game_state.console_logs.length > 0) {
            data.game_state.console_logs = [];
          }
          
          // Process blinking data and available_weapons from backend
          // Handle both cases: with and without empty_target_pool
          
          // STEP 1: Start blinking if blinking_units is present (regardless of empty_target_pool)
          if (data.result?.blinking_units && data.result?.start_blinking) {
            const newUnitIds = data.result.blinking_units.map((id: string) => parseInt(id));
            const newAttackerId = (data.game_state?.phase === "charge" && data.result?.unitId) 
              ? parseInt(data.result.unitId) 
              : null;
            
            // Check if we need to update: different unitIds, different attackerId, or no timer
            const unitIdsChanged = newUnitIds.length !== blinkingUnits.unitIds.length ||
              !newUnitIds.every((id: number) => blinkingUnits.unitIds.includes(id));
            const attackerIdChanged = newAttackerId !== blinkingUnits.attackerId;
            const needsUpdate = !blinkingUnits.blinkTimer || unitIdsChanged || attackerIdChanged;
            
            if (needsUpdate) {
              // Clear any existing blinking timer
              if (blinkingUnits.blinkTimer) {
                clearInterval(blinkingUnits.blinkTimer);
              }
  
              // Start blinking for all valid targets
              // Note: Actual blinking animation is handled locally in UnitRenderer
              // We only track which units should blink, not the blink state itself
              const timer = window.setInterval(() => {
                // Empty interval - blinking is handled locally in UnitRenderer
                // This timer is kept for cleanup purposes only
              }, 500);
              
              // Also update gameState and selectedUnitId for consistency
              if (data.game_state?.phase === "charge" && data.result?.unitId) {
                data.game_state = {
                  ...data.game_state,
                  active_charge_unit: data.result.unitId
                };
                setSelectedUnitId(parseInt(data.result.unitId));
              }
  
              setBlinkingUnits({unitIds: newUnitIds, blinkTimer: timer, attackerId: newAttackerId});
            }
          } else if (data.result?.blinking_units && !data.result?.start_blinking) {
            console.warn("💫 WARNING: blinking_units present but start_blinking is false");
          }
          
          // STEP 2: Propagate available_weapons to unit in game_state (required for weapon icon)
          // CRITICAL: This must happen BEFORE setGameState to ensure React detects the change
          if (data.result?.available_weapons && Array.isArray(data.result.available_weapons)) {
            // Check both data.game_state.active_shooting_unit AND data.result.unitId (fallback)
            const activeUnitId = data.game_state.active_shooting_unit || data.result.unitId;
            if (activeUnitId && data.game_state.units) {
              const unitIndex = data.game_state.units.findIndex((u: { id: string | number }) => 
                u.id.toString() === activeUnitId.toString()
              );
              if (unitIndex >= 0) {
                // Create new array to ensure React detects the change
                const updatedUnits = [...data.game_state.units];
                updatedUnits[unitIndex] = {
                  ...updatedUnits[unitIndex],
                  available_weapons: data.result.available_weapons
                };
                // Also update selectedRngWeaponIndex if provided in result
                if (data.result.selectedRngWeaponIndex !== undefined) {
                  updatedUnits[unitIndex].selectedRngWeaponIndex = data.result.selectedRngWeaponIndex;
                  updatedUnits[unitIndex].manualWeaponSelected = true;
                }
                data.game_state = {
                  ...data.game_state,
                  units: updatedUnits
                };
              } else {
                console.warn("🔫 WARNING: Could not find unit", activeUnitId, "in game_state.units");
              }
            } else {
              console.warn("🔫 WARNING: No active_shooting_unit or unitId in response", {
                active_shooting_unit: data.game_state.active_shooting_unit,
                unitId: data.result.unitId,
                has_available_weapons: !!data.result.available_weapons
              });
            }
          }
          // Also handle selectedRngWeaponIndex even if available_weapons is not present
          else if (data.result?.selectedRngWeaponIndex !== undefined) {
            const activeUnitId = data.game_state.active_shooting_unit || data.result.unitId;
            if (activeUnitId && data.game_state.units) {
              const unitIndex = data.game_state.units.findIndex((u: { id: string | number }) => 
                u.id.toString() === activeUnitId.toString()
              );
              if (unitIndex >= 0) {
                const updatedUnits = [...data.game_state.units];
                updatedUnits[unitIndex] = {
                  ...updatedUnits[unitIndex],
                  selectedRngWeaponIndex: data.result.selectedRngWeaponIndex,
                  manualWeaponSelected: true
                };
                data.game_state = {
                  ...data.game_state,
                  units: updatedUnits
                };
              }
            }
          }
          
          // STEP 3: Set mode to attackPreview only if unit has valid targets (not empty_target_pool)
          // This prevents shooting preview from showing when unit can only advance
          // CRITICAL FIX: After advance move, blinking_units indicates valid targets are available
          if (data.result?.blinking_units && data.result?.start_blinking) {
            // If blinking_units is present and has elements, unit has valid targets
            // blinking_units IS the list of valid target IDs, so if it exists and has length > 0, targets are available
            const hasValidTargets = Array.isArray(data.result.blinking_units) && data.result.blinking_units.length > 0;
            
            if (hasValidTargets) {
              // AI_TURN.md COMPLIANCE: Clear stale attackPreview when entering attackPreview mode for shooting
              // This prevents units from rendering at old positions from previous fight phases
              setAttackPreview(null);
              setMode("attackPreview");

              // CRITICAL: Set selectedUnitId to active_shooting_unit or unitId from result
              // This MUST happen BEFORE setGameState to ensure weapon icon appears
              // active_shooting_unit is set by backend (shooting_handlers.py line 3180) after advance
              const activeUnitId = data.game_state?.active_shooting_unit || data.result?.unitId;
              if (activeUnitId) {
                setSelectedUnitId(parseInt(activeUnitId));
              }
            }
          }

          setGameState(data.game_state);


        // ADVANCE_IMPLEMENTATION_PLAN.md Phase 5: Handle advance activation response
        if (data.result?.advance_destinations && data.result?.advance_roll) {
          // Clear shooting preview when entering advancePreview mode (from either advance button click or unit activation)
          if (targetPreview?.blinkTimer) {
            clearInterval(targetPreview.blinkTimer);
          }
          setTargetPreview(null);
          setAttackPreview(null);
          // Clear HP bar blinking
          if (blinkingUnits.blinkTimer) {
            clearInterval(blinkingUnits.blinkTimer);
          }
          setBlinkingUnits({unitIds: [], blinkTimer: null, attackerId: null});
          setAdvanceDestinations(data.result.advance_destinations);
          setAdvanceRoll(data.result.advance_roll);
          setAdvancingUnitId(parseInt(data.result.unitId));
          setSelectedUnitId(parseInt(data.result.unitId));
          setMode("advancePreview" as GameMode);
        }
        // Handle movement activation response with valid destinations
        else if (data.result?.valid_destinations && data.result?.waiting_for_player && data.game_state?.phase === "move") {
          setSelectedUnitId(parseInt(data.result.unitId));
          // Note: valid_destinations are stored in game_state.valid_move_destinations_pool
          // BoardPvp will read them from gameState to display green hexes
        }
        // Handle charge activation response - can have blinking_units without valid_destinations yet
        // After handleActivateCharge, backend returns blinking_units (targets) but not destinations yet
        // Destinations are calculated after clicking on a target (handleChargeEnemyUnit)
        else if (data.game_state?.phase === "charge" && data.result?.waiting_for_player && data.result?.blinking_units && data.result?.start_blinking && !data.result?.valid_destinations) {
          // Charge activation: blinking_units present but no destinations yet - set mode to chargePreview
          const newUnitIds = data.result.blinking_units.map((id: string) => parseInt(id));
          const needsNewTimer = !blinkingUnits.blinkTimer || 
            !blinkingUnits.unitIds.some(id => newUnitIds.includes(id));
          
          if (needsNewTimer) {
            // Clear any existing blinking timer
            if (blinkingUnits.blinkTimer) {
              clearInterval(blinkingUnits.blinkTimer);
            }

            // Start blinking for all valid targets
            const timer = window.setInterval(() => {
              // Empty interval - blinking is handled locally in UnitRenderer
            }, 500);

            const attackerId = data.result?.unitId ? parseInt(data.result.unitId) : null;
            
            if (data.result?.unitId) {
              data.game_state = {
                ...data.game_state,
                active_charge_unit: data.result.unitId
              };
              setSelectedUnitId(parseInt(data.result.unitId));
            }
            
            setBlinkingUnits({unitIds: newUnitIds, blinkTimer: timer, attackerId});
          }
          
          setSelectedUnitId(parseInt(data.result.unitId));
          setMode("chargePreview");
        }
        // Handle charge activation response with valid destinations (after target selection)
        // MUST be after setGameState to prevent being overwritten
        else if (data.result?.valid_destinations && data.result?.waiting_for_player) {
          // STEP 1: Start blinking if blinking_units is present (for charge phase)
          if (data.result?.blinking_units && data.result?.start_blinking) {
            const newUnitIds = data.result.blinking_units.map((id: string) => parseInt(id));
            const needsNewTimer = !blinkingUnits.blinkTimer || 
              !blinkingUnits.unitIds.some(id => newUnitIds.includes(id));
            
            if (needsNewTimer) {
              // Clear any existing blinking timer
              if (blinkingUnits.blinkTimer) {
                clearInterval(blinkingUnits.blinkTimer);
              }
  
              // Start blinking for all valid targets
              // Note: Actual blinking animation is handled locally in UnitRenderer
              // We only track which units should blink, not the blink state itself
              const timer = window.setInterval(() => {
                // Empty interval - blinking is handled locally in UnitRenderer
                // This timer is kept for cleanup purposes only
              }, 500);
  
              // For charge phase, store attacker ID directly in blinkingUnits to avoid React timing issues
              const attackerId = (data.game_state?.phase === "charge" && data.result?.unitId) 
                ? parseInt(data.result.unitId) 
                : null;
              
              // Also update gameState for consistency
              if (data.game_state?.phase === "charge" && data.result?.unitId) {
                data.game_state = {
                  ...data.game_state,
                  active_charge_unit: data.result.unitId
                };
                setSelectedUnitId(parseInt(data.result.unitId));
              }
              
              setBlinkingUnits({unitIds: newUnitIds, blinkTimer: timer, attackerId});
            }
          } else if (data.result?.blinking_units && !data.result?.start_blinking) {
            console.warn("💫 WARNING: blinking_units present but start_blinking is false (charge phase)");
          }
          
          setChargeDestinations(data.result.valid_destinations);
          setSelectedUnitId(parseInt(data.result.unitId));
          setMode("chargePreview");
        }
        // NEW RULE: Handle charge failure - show failed roll badge
        // Use EXACT same logic as successful charges: reset mode immediately, store targetId
        else if (data.result?.charge_failed && data.result?.charge_roll !== undefined) {
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
          // Clear blinking from charge preview to avoid stale attacker stats
          if (blinkingUnits.blinkTimer) {
            clearInterval(blinkingUnits.blinkTimer);
          }
          setBlinkingUnits({unitIds: [], blinkTimer: null, attackerId: null});
          // Clear failedChargeRoll after delay to show badge
          setTimeout(() => {
            setFailedChargeRoll(null); // Clear after display
          }, 2000); // Show badge for 2 seconds
        }
        // Handle charge completion - reset to select mode
        // CRITICAL FIX: When phase_complete=true, backend has already transitioned to next phase
        // So we check activation_complete AND (current phase is charge OR phase just completed)
        else if (data.result?.activation_complete &&
          (data.game_state?.phase === "charge" || data.result?.phase_complete)) {
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
          // Clear blinking from charge preview when charge resolves
          if (blinkingUnits.blinkTimer) {
            clearInterval(blinkingUnits.blinkTimer);
          }
          setBlinkingUnits({unitIds: [], blinkTimer: null, attackerId: null});
        }
        // Handle fight phase multi-attack (ATTACK_LEFT > 0, waiting_for_player)
        else if (data.game_state?.phase === "fight" && data.result?.waiting_for_player && data.result?.valid_targets) {

          // Keep the attacking unit selected and show valid targets
          const unitId = parseInt(data.result.unitId || data.game_state.active_fight_unit);
          setSelectedUnitId(unitId);
          setMode("attackPreview");

          // Set attackPreview state for red hexes to appear
          interface UnitWithId {
            id: string | number;
            col: number;
            row: number;
          }
          const unit = data.game_state.units.find((u: UnitWithId) => parseInt(u.id.toString()) === unitId);
          if (unit) {
            setAttackPreview({ unitId, col: unit.col, row: unit.row });
          }

          // Start/update blinking for valid fight targets (keep attacker in sync)
          if (data.result.valid_targets.length > 0) {
            const unitIds = data.result.valid_targets.map((id: string) => parseInt(id));
            const attackerId = unitId;
            const unitIdsChanged = unitIds.length !== blinkingUnits.unitIds.length ||
              !unitIds.every((id: number) => blinkingUnits.unitIds.includes(id));
            const attackerIdChanged = attackerId !== blinkingUnits.attackerId;
            let timer = blinkingUnits.blinkTimer;
            if (!timer) {
              // Note: Actual blinking animation is handled locally in UnitRenderer
              // We only track which units should blink, not the blink state itself
              timer = window.setInterval(() => {
                // Empty interval - blinking is handled locally in UnitRenderer
                // This timer is kept for cleanup purposes only
              }, 500);
            }
            if (unitIdsChanged || attackerIdChanged || !blinkingUnits.blinkTimer) {
              setBlinkingUnits({unitIds, blinkTimer: timer, attackerId});
            }
          }
        }
        // Handle fight phase completion (ATTACK_LEFT = 0, activation_ended)
        else if (data.game_state?.phase === "fight" && data.result?.activation_ended) {
          // Clear blinking
          if (blinkingUnits.blinkTimer) {
            clearInterval(blinkingUnits.blinkTimer);
          }
          setBlinkingUnits({unitIds: [], blinkTimer: null});
          setAttackPreview(null);
          setSelectedUnitId(null);
          setMode("select");
        }
        // Set visual state based on shooting activation
        // AI_TURN.md COMPLIANCE: Clear stale attackPreview from previous fight phases
        // This prevents Unit 3 (fled) from rendering at old position when Unit 4 (shooter) is activated
        // Root cause: attackPreview was set during fight phase and never cleared when shooting started
        // Don't set mode to attackPreview here - wait for backend response (blinking_units or allow_advance)
        // Skip this if allow_advance is present (will be handled by advance handler)
        else if (data.game_state?.phase === "shoot" && data.game_state?.active_shooting_unit && !data.result?.allow_advance) {
          setSelectedUnitId(parseInt(data.game_state.active_shooting_unit));
          setAttackPreview(null);  // Clear stale attackPreview to prevent ghost rendering
          // Mode will be set by blinking_units handler (attackPreview) or allow_advance handler (advancePreview)
        } else {
          setSelectedUnitId(null);
        }
        
        // CRITICAL FIX: Propagate available_weapons independently of allow_advance condition
        // This ensures weapon icons appear after advance when unit has ASSAULT weapon and LoS
        // Must happen after setSelectedUnitId to ensure active_shooting_unit is set
        if (data.game_state?.phase === "shoot" && data.game_state?.active_shooting_unit) {
          // Propagate available_weapons from API response to unit if present
          // Update the unit in game_state before setGameState is called later
          if (data.result?.available_weapons && Array.isArray(data.result.available_weapons) && data.game_state.units) {
            const activeUnitId = data.game_state.active_shooting_unit;
            const unitIndex = data.game_state.units.findIndex((u: { id: string | number }) => 
              u.id.toString() === activeUnitId.toString()
            );
            if (unitIndex >= 0) {
              data.game_state.units[unitIndex] = {
                ...data.game_state.units[unitIndex],
                available_weapons: data.result.available_weapons
              };
            }
          }
        }
      }
    } catch (err) {
      console.error('Action error:', err);
    }
  }, [gameState, advanceWarningPopup, blinkingUnits.blinkTimer, blinkingUnits.unitIds, blinkingUnits.attackerId, targetPreview?.blinkTimer]);

  // Convert API units to frontend format
  const convertUnits = useCallback((apiUnits: APIGameState['units']): Unit[] => {
    return apiUnits.map(unit => {
      // NEVER create defaults - raise errors for missing data
      // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Validate weapons arrays exist
      if (!unit.RNG_WEAPONS || !Array.isArray(unit.RNG_WEAPONS)) {
        throw new Error(`API ERROR: Unit ${unit.id} missing required RNG_WEAPONS array`);
      }
      if (!unit.CC_WEAPONS || !Array.isArray(unit.CC_WEAPONS)) {
        throw new Error(`API ERROR: Unit ${unit.id} missing required CC_WEAPONS array`);
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
        id: parseInt(unit.id) || (typeof unit.id === 'number' ? unit.id : parseInt(unit.id)),
        name: unit.unitType,
        type: unit.unitType,
        player: unit.player as PlayerId,
        col: unit.col,
        row: unit.row,
        color: unit.player === 1 ? 0x244488 : 0x882222,
        MOVE: unit.MOVE,
        HP_MAX: unit.HP_MAX,
        HP_CUR: unit.HP_CUR,
        T: unit.T,
        ARMOR_SAVE: unit.ARMOR_SAVE,
        INVUL_SAVE: unit.INVUL_SAVE,
        LD: unit.LD,
        OC: unit.OC,
        VALUE: unit.VALUE,
        // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Map weapons arrays
        RNG_WEAPONS: unit.RNG_WEAPONS,
        CC_WEAPONS: unit.CC_WEAPONS,
        selectedRngWeaponIndex: unit.selectedRngWeaponIndex,
        selectedCcWeaponIndex: unit.selectedCcWeaponIndex,
        manualWeaponSelected: unit.manualWeaponSelected,
        ICON: unit.ICON,
        ICON_SCALE: unit.ICON_SCALE,
        SHOOT_LEFT: unit.SHOOT_LEFT,
        ATTACK_LEFT: unit.ATTACK_LEFT,
        available_weapons: unit.available_weapons,
      };
    });
  }, []);
  

  // Helper function using backend state only
  const determineClickTarget = useCallback((unitId: number, gameState: APIGameState): string => {
    if (!gameState) return "elsewhere";
    
    interface UnitWithId {
      id: string | number;
      [key: string]: unknown;
    }
    const unit = gameState.units.find((u: UnitWithId) => parseInt(u.id.toString()) === unitId);
    if (!unit) return "elsewhere";
    
    const current_player = gameState.current_player;
    const activeShooterId = gameState.active_shooting_unit ? parseInt(gameState.active_shooting_unit) : null;
    
    if (unit.player === current_player) {
      if (unitId === activeShooterId) {
        return "active_unit";
      } else {
        // Check if unit is in activation pool for "friendly_unit" detection
        const shootPool = gameState.shoot_activation_pool || [];
        const unitIdStr = unitId.toString();
        if (shootPool.includes(unitIdStr)) {
          return "friendly_unit";
        }
        return "friendly";
      }
    } else {
      return "enemy";
    }
  }, []);

  // Backend-driven shooting phase management
  const handleShootingPhaseClick = useCallback(async (unitId: number, clickType: 'left' | 'right') => {
    if (!gameState) return;
    
    const clickTarget = determineClickTarget(unitId, gameState);
    const activeShooterId = gameState.active_shooting_unit;
    
    // Backend handles all context awareness
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
    
    // Block unit selection when in advancePreview or chargePreview mode (but allow deselection with null)
    if ((mode === "advancePreview" || mode === "chargePreview") && numericUnitId !== null) {
      return;
    }
    
    // Shooting phase click handling
    if (gameState && gameState.phase === "shoot") {
      if (numericUnitId === null && mode === "attackPreview" && selectedUnitId !== null) {
        // Shooting phase: postpone (deselect active unit, return to pool)
        const activeShooterId = gameState.active_shooting_unit;
        if (activeShooterId) {
          await executeAction({
            action: "left_click",
            unitId: activeShooterId.toString(),
            clickTarget: "active_unit"
          });
        }
        setSelectedUnitId(null);
        setMode("select");
        return;
      } else if (numericUnitId !== null) {
        if (!gameState.shoot_activation_pool) {
          throw new Error(`API ERROR: Missing required shoot_activation_pool during shooting phase`);
        }
        const shootActivationPool = gameState.shoot_activation_pool.map(id => parseInt(id));
        
        if (shootActivationPool.includes(numericUnitId) && 
            (!gameState.active_shooting_unit || gameState.active_shooting_unit === numericUnitId.toString())) {
          await executeAction({
            action: "activate_unit", 
            unitId: numericUnitId.toString()
          });
          return;
        } else if (gameState.active_shooting_unit) {
          // Clicking on target when unit is active
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
    
    // Movement phase click handling
    if (gameState && gameState.phase === "move" && numericUnitId !== null) {
      if (!gameState.move_activation_pool) {
        console.error("❌ MOVEMENT SELECT ERROR: Missing move_activation_pool");
        throw new Error(`API ERROR: Missing required move_activation_pool during movement phase`);
      }
      const moveActivationPool = gameState.move_activation_pool.map(id => parseInt(id));
      
      if (moveActivationPool.includes(numericUnitId)) {
        await executeAction({
          action: "activate_unit", 
          unitId: numericUnitId.toString()
        });
        return;
      }
    }
    
    // Normal unit selection for other phases
    // If deselecting in chargePreview mode, send postpone action to backend
    if (numericUnitId === null && mode === "chargePreview" && selectedUnitId !== null) {
      await executeAction({
        action: "left_click",
        unitId: selectedUnitId.toString(),
        clickTarget: "active_unit"
      });
      setChargeDestinations([]);
    } else if (numericUnitId === null && mode === "advancePreview") {
      setAdvanceDestinations([]);
      setAdvancingUnitId(null);
      setAdvanceRoll(null);
    }
    setSelectedUnitId(numericUnitId);
    setMode("select");
    setMovePreview(null);
    setTargetPreview(null);
    // Remove all frontend shooting state - backend manages everything
  }, [gameState, executeAction, mode, determineClickTarget, selectedUnitId]);

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
      console.error("❌ DIRECT MOVE FAILED:", error);
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

  // Backend handles all shooting logic - frontend just sends clicks
  const handleShoot = useCallback(async (_shooterId: number | string, targetId: number | string) => {
    // Convert to left_click action that backend understands
    await handleShootingPhaseClick(typeof targetId === 'string' ? parseInt(targetId) : targetId, 'left');
  }, [handleShootingPhaseClick]);

  const handleSkipShoot = useCallback(async (unitId: number | string, actionType: 'wait' | 'action' = 'action') => {
    // Check if we're still in shooting phase - if phase changed, don't send skip action
    if (gameState?.phase !== 'shoot') {
      return;
    }
    // Convert to right_click or skip action
    if (actionType === 'wait') {
      await handleRightClick(typeof unitId === 'string' ? parseInt(unitId) : unitId);
    } else {
      await executeAction({
        action: "skip",
        unitId: typeof unitId === 'string' ? unitId : unitId.toString()
      });
    }
  }, [handleRightClick, executeAction, gameState]);

  // Charge activation - sends left_click to trigger 2d6 roll and destination building
  const handleActivateCharge = useCallback(async (chargerId: number | string) => {
    const numericChargerId = typeof chargerId === 'string' ? parseInt(chargerId) : chargerId;

    // Send left_click action to backend
    // Backend will call _handle_unit_activation which:
    // 1. Rolls 2d6 for charge_range
    // 2. Builds valid_charge_destinations_pool via BFS pathfinding
    // 3. Returns destinations for orange highlighting
    await executeAction({
      action: "left_click",
      unitId: numericChargerId.toString()
    });
  }, [executeAction]);

  // Fight activation - sends activate_unit to activate unit and get valid targets
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

  // ADVANCE_IMPLEMENTATION_PLAN.md Phase 5: Handle advance action
  const handleAdvance = useCallback(async (unitId: number) => {
    // Cancel target preview IMMEDIATELY (replace shooting preview with advance preview)
    // Clear blinking timer if it exists
    if (targetPreview?.blinkTimer) {
      clearInterval(targetPreview.blinkTimer);
    }
    setTargetPreview(null);
    // Also clear attackPreview if it exists
    setAttackPreview(null);
    // Clear HP bar blinking (blinkingUnits)
    if (blinkingUnits.blinkTimer) {
      clearInterval(blinkingUnits.blinkTimer);
    }
    setBlinkingUnits({unitIds: [], blinkTimer: null});
    // Change mode immediately to prevent shooting preview from showing
    setMode("select");
    
    // Check if advance warning popup is enabled (from localStorage)
    const showAdvanceWarningStr = localStorage.getItem('showAdvanceWarning');
    const showAdvanceWarning = showAdvanceWarningStr ? JSON.parse(showAdvanceWarningStr) : false;
    
    if (showAdvanceWarning) {
      // Show warning popup
      setAdvanceWarningPopup({
        unitId: unitId,
        timestamp: Date.now()
      });
    } else {
      // Auto-confirm: execute advance directly (bypass popup)
      await executeAction({
        action: "advance",
        unitId: unitId.toString()
      });
    }
    
    // Backend will return valid_destinations and advance_roll
    // State will be updated in executeAction response handler (will set mode to advancePreview)
  }, [executeAction, targetPreview, blinkingUnits]);

  // ADVANCE_IMPLEMENTATION_PLAN.md Phase 5: Cancel advance action
  const handleCancelAdvance = useCallback(async () => {
    // Get the advancing unit ID before clearing state
    const unitIdToSkip = advancingUnitId;
    
    // Clear advance state
    setAdvanceDestinations([]);
    setAdvancingUnitId(null);
    setAdvanceRoll(null);
    setMode("select");
    setSelectedUnitId(null);
    
    // Send skip action to backend to remove unit from activation pool
    if (unitIdToSkip !== null) {
      await executeAction({
        action: "skip",
        unitId: unitIdToSkip.toString()
      });
    }
  }, [executeAction, advancingUnitId]);

  // Handle advance warning popup confirmation
  const handleConfirmAdvanceWarning = useCallback(async () => {
    if (!advanceWarningPopup) return;
    
    const unitId = advanceWarningPopup.unitId;
    
    // Clear popup
    setAdvanceWarningPopup(null);
    
    // Cancel target preview IMMEDIATELY (replace shooting preview with advance preview)
    if (targetPreview?.blinkTimer) {
      clearInterval(targetPreview.blinkTimer);
    }
    setTargetPreview(null);
    setAttackPreview(null);
    // Clear HP bar blinking
    if (blinkingUnits.blinkTimer) {
      clearInterval(blinkingUnits.blinkTimer);
    }
    setBlinkingUnits({unitIds: [], blinkTimer: null});
    setMode("select");
    
    // Send advance action to backend to trigger 1D6 roll and get destinations
    await executeAction({
      action: "advance",
      unitId: unitId.toString()
    });
  }, [advanceWarningPopup, executeAction, targetPreview, blinkingUnits]);

  // Handle advance warning popup cancellation
  const handleCancelAdvanceWarning = useCallback(() => {
    // Clear popup
    setAdvanceWarningPopup(null);
    // Clear all advance-related state and reset to selection mode
    // Don't send skip - keep unit in pool for re-activation
    setAdvanceDestinations([]);
    setAdvancingUnitId(null);
    setAdvanceRoll(null);
    setMode("select");
    setSelectedUnitId(null);
  }, []);

  // Handle skip from advance warning popup
  const handleSkipAdvanceWarning = useCallback(async () => {
    if (!advanceWarningPopup) return;
    
    const unitIdToSkip = advanceWarningPopup.unitId;
    
    // Clear popup
    setAdvanceWarningPopup(null);
    
    // Clear all advance-related state
    setAdvanceDestinations([]);
    setAdvancingUnitId(null);
    setAdvanceRoll(null);
    setMode("select");
    setSelectedUnitId(null);
    
    // Send skip action to backend to remove unit from activation pool
    await executeAction({
      action: "skip",
      unitId: unitIdToSkip.toString()
    });
  }, [advanceWarningPopup, executeAction]);

  // ADVANCE_IMPLEMENTATION_PLAN.md Phase 5: Handle advance move to destination
  const handleAdvanceMove = useCallback(async (unitId: number | string, destCol: number, destRow: number) => {
    const numericUnitId = typeof unitId === 'string' ? parseInt(unitId) : unitId;

    // Send advance action with destination to backend
    await executeAction({
      action: "advance",
      unitId: numericUnitId.toString(),
      destCol: destCol,
      destRow: destRow
    });

    // Don't reset advance state here - let backend cleanup signals handle it
    // This allows the advance roll badge to be displayed before cleanup
  }, [executeAction]);

  const handleFightAttack = useCallback(async (attackerId: number | string, targetId: number | string | null) => {
    // Fight action - send fight action to backend
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

  // Handle clicking on enemy unit in chargePreview mode - triggers charge roll and destination building
  const handleChargeEnemyUnit = useCallback(async (chargerId: number | string, enemyUnitId: number | string) => {
    const numericChargerId = typeof chargerId === 'string' ? parseInt(chargerId) : chargerId;
    const numericEnemyId = typeof enemyUnitId === 'string' ? parseInt(enemyUnitId) : enemyUnitId;

    // Send left_click action with targetId to backend
    // Backend will:
    // 1. Roll 2d6 for charge_range
    // 2. Build valid_charge_destinations_pool via BFS pathfinding
    // 3. Return destinations for violet highlighting
    await executeAction({
      action: "left_click",
      unitId: numericChargerId.toString(),
      targetId: numericEnemyId.toString(),
      clickTarget: "enemy"
    });
  }, [executeAction]);

  const handleMoveCharger = useCallback(async (chargerId: number | string, destCol: number, destRow: number) => {
    const numericChargerId = typeof chargerId === 'string' ? parseInt(chargerId) : chargerId;

    // Find target enemy adjacent to destination
    if (!gameState) return;

    const charger = gameState.units.find(u => parseInt(u.id) === numericChargerId);
    if (!charger) {
      console.error("🟠 Charger unit not found:", numericChargerId);
      return;
    }

    // Find enemy units adjacent to destination (within CC_RNG)
    const enemies = gameState.units.filter(u =>
      u.player !== charger.player &&
      u.HP_CUR > 0
    );

    const destCube = offsetToCube(destCol, destRow);
    let targetEnemy = null;

    for (const enemy of enemies) {
      const enemyCube = offsetToCube(enemy.col, enemy.row);
      const distance = cubeDistance(destCube, enemyCube);
      // Use getMeleeRange() (always 1)
      if (distance <= getMeleeRange()) {
        targetEnemy = enemy;
        break; // Use first adjacent enemy
      }
    }

    if (!targetEnemy) {
      console.error("🟠 No enemy found adjacent to destination:", { destCol, destRow });
      return;
    }

    // Send charge action with correct field names
    await executeAction({
      action: "charge",
      unitId: numericChargerId.toString(),
      destCol: destCol,
      destRow: destRow,
      targetId: targetEnemy.id.toString()
    });
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
    // Handle both string and number IDs
    const shooter = gameState?.units.find(u => {
      const unitId = typeof u.id === 'string' ? parseInt(u.id) : u.id;
      return unitId === numericShooterId;
    });
    const target = gameState?.units.find(u => {
      const unitId = typeof u.id === 'string' ? parseInt(u.id) : u.id;
      return unitId === numericTargetId;
    });
    
    let hitProbability = 0.5;
    let woundProbability = 0.5;
    let saveProbability = 0.5;
    let potentialDamage = 0;
    
    if (shooter && target) {
      // Get best ranged weapon for this target
      // Convert shooter to proper Unit type (id as number, player as PlayerId)
      const shooterUnit: Unit = {
        ...shooter,
        id: typeof shooter.id === 'string' ? parseInt(shooter.id) : shooter.id,
        player: shooter.player as PlayerId
      };
      const preferred = getPreferredRangedWeaponAgainstTarget(shooterUnit, target as Unit);
      if (!preferred) {
        return;
      }
      
      hitProbability = preferred.hitProbability;
      woundProbability = preferred.woundProbability;
      saveProbability = preferred.saveProbability;
      potentialDamage = preferred.potentialDamage;
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
  }, [gameState, executeAction]);

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

    if (gameState.phase === 'command') {
      // Command phase: empty pool for now, ready for future
      return [];
    } else if (gameState.phase === 'move') {
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
      return eligible;
    } else if (gameState.phase === 'fight') {
      // Fight phase has sub-phases - only show units from current sub-phase
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

  const getChargeDestinations = useCallback(() => {
    return chargeDestinations;
  }, [chargeDestinations]);

  // Return props compatible with BoardPvp
  if (error) {
    throw new Error(`API ERROR: ${error}`);
  }
  
  // Memoize blinkingUnits.unitIds to prevent re-renders when only blinkState changes
  // Compare by content (string) to avoid re-renders when only blinkState toggles
  const blinkingUnitsIds = useMemo(() => {
    // Return sorted copy to ensure stable reference when content is same
    return [...blinkingUnits.unitIds].sort((a, b) => a - b);
  }, [blinkingUnits.unitIds]);
  
  // Memoize isBlinkingActive to prevent re-renders when only blinkState toggles
  const isBlinkingActiveMemo = useMemo(() => {
    return blinkingUnits.blinkTimer !== null;
  }, [blinkingUnits.blinkTimer]);
  
  // Memoize units conversion to prevent unnecessary re-renders
  const memoizedUnits = useMemo(() => {
    return convertUnits(gameState?.units || []);
  }, [gameState?.units, convertUnits]);
  
  // Memoize derived arrays to prevent unnecessary re-renders
  const memoizedUnitsMoved = useMemo(() => {
    return gameState?.units_moved ? gameState.units_moved.map(id => parseInt(id)) : [];
  }, [gameState?.units_moved]);
  
  const memoizedUnitsCharged = useMemo(() => {
    return gameState?.units_charged ? gameState.units_charged.map(id => parseInt(id)) : [];
  }, [gameState?.units_charged]);
  
  const memoizedUnitsAttacked = useMemo(() => {
    return gameState?.units_attacked ? gameState.units_attacked.map(id => parseInt(id)) : [];
  }, [gameState?.units_attacked]);
  
  const memoizedUnitsFled = useMemo(() => {
    return gameState?.units_fled ? gameState.units_fled.map(id => parseInt(id)) : [];
  }, [gameState?.units_fled]);
  
  const memoizedUnitsAdvanced = useMemo(() => {
    return gameState?.units_advanced ? gameState.units_advanced.map(id => parseInt(id)) : [];
  }, [gameState?.units_advanced]);
  
  // Memoize inline callbacks to prevent re-renders
  const onStartAttackPreviewMemo = useCallback((unitId: number) => {
    setSelectedUnitId(typeof unitId === 'string' ? parseInt(unitId) : unitId);
    setAttackPreview(null);
    setMode("attackPreview");
  }, []);
  
  const emptyCallback = useCallback(() => {}, []);
  const getAdvanceDestinationsMemo = useCallback(() => advanceDestinations, [advanceDestinations]);
  
  // Memoize gameState to prevent re-renders when content hasn't changed
  const memoizedGameState = useMemo(() => {
    if (!gameState) return null;
    return {
      episode_steps: gameState.episode_steps,
      units: memoizedUnits,
      current_player: gameState.current_player as PlayerId,
      phase: gameState.phase as "move" | "shoot" | "charge" | "fight",
      mode,
      selectedUnitId,
      unitsMoved: memoizedUnitsMoved,
      unitsCharged: memoizedUnitsCharged,
      unitsAttacked: memoizedUnitsAttacked,
      unitsFled: memoizedUnitsFled,
      unitsAdvanced: memoizedUnitsAdvanced,
      targetPreview: null,
      currentTurn: gameState.turn,
      maxTurns: maxTurnsFromConfig,
      unitChargeRolls: {},
      pve_mode: gameState.pve_mode,
      move_activation_pool: gameState.move_activation_pool,
      shoot_activation_pool: gameState.shoot_activation_pool,
      charge_activation_pool: gameState.charge_activation_pool,
      fight_subphase: gameState.fight_subphase as "charging" | "alternating_non_active" | "alternating_active" | "cleanup_non_active" | "cleanup_active" | null | undefined,
      charging_activation_pool: gameState.charging_activation_pool,
      active_alternating_activation_pool: gameState.active_alternating_activation_pool,
      non_active_alternating_activation_pool: gameState.non_active_alternating_activation_pool,
      active_movement_unit: gameState.active_movement_unit,
      active_shooting_unit: gameState.active_shooting_unit,
      active_fight_unit: gameState.active_fight_unit,
      units_cache: gameState.units_cache,
      victory_points: gameState.victory_points,
      primary_objective: gameState.primary_objective,
    };
  }, [
    gameState,
    memoizedUnits,
    mode,
    selectedUnitId,
    memoizedUnitsMoved,
    memoizedUnitsCharged,
    memoizedUnitsAttacked,
    memoizedUnitsFled,
    memoizedUnitsAdvanced,
    maxTurnsFromConfig
  ]);
  
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
        current_player: null,
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
        onCancelAdvance: () => {},
        onAdvanceMove: async () => {},
        onShoot: () => {},
        onSkipShoot: () => {},
        onStartTargetPreview: () => {},
        onFightAttack: () => {},
        onActivateFight: () => {},
        onCharge: () => {},
        onActivateCharge: () => {},
        onMoveCharger: () => {},
        onChargeEnemyUnit: async () => {},
        onCancelCharge: () => {},
        onValidateCharge: () => {},
        onLogChargeRoll: () => {},
        getChargeDestinations: () => [],
        onAdvance: async () => {},
        getAdvanceDestinations: () => [],
        advancingUnitId: null,
        advanceRoll: null,
        advanceWarningPopup: null,
        onConfirmAdvanceWarning: async () => {},
        onCancelAdvanceWarning: () => {},
        onSkipAdvanceWarning: async () => {},
        blinkingUnits: [],
        blinkingAttackerId: null,
        isBlinkingActive: false,
        blinkVersion: 0,
        // blinkState removed - blinking is handled locally in UnitRenderer
        fightSubPhase: null,
        executeAITurn: async () => {},
      };
    }
  
    // Normal case
    const returnObject = {
      loading: false,
    error: null,
    units: memoizedUnits,
    selectedUnitId,
    eligibleUnitIds: getEligibleUnitIds(),
    mode,
    movePreview,
    attackPreview,
    targetPreview,
    current_player: gameState.current_player as PlayerId,
    maxTurns: maxTurnsFromConfig,
    unitsMoved: memoizedUnitsMoved,
    unitsCharged: memoizedUnitsCharged,
    unitsAttacked: memoizedUnitsAttacked,
    unitsFled: memoizedUnitsFled,
    phase: gameState.phase as "move" | "shoot" | "charge" | "fight",
    // Expose fight_subphase for UnitRenderer click handling
    fightSubPhase: gameState.fight_subphase as "charging" | "alternating_non_active" | "alternating_active" | "cleanup_non_active" | "cleanup_active" | null,
    gameState: memoizedGameState,
    onSelectUnit: handleSelectUnit,
    onSkipUnit: handleSkipUnit,
    onStartMovePreview: handleStartMovePreview,
    onDirectMove: handleDirectMove,
    onStartAttackPreview: onStartAttackPreviewMemo,
    onConfirmMove: handleConfirmMove,
    onCancelMove: handleCancelMove,
    onShoot: handleShoot,
    onSkipShoot: handleSkipShoot,
    onStartTargetPreview: handleStartTargetPreview,
    onFightAttack: handleFightAttack,
    onActivateFight: handleActivateFight,
    onCharge: emptyCallback,
    onActivateCharge: handleActivateCharge,
    onChargeEnemyUnit: handleChargeEnemyUnit,
    onMoveCharger: handleMoveCharger,
    onAdvanceMove: handleAdvanceMove,
    onCancelCharge: emptyCallback,
    onValidateCharge: emptyCallback,
    onLogChargeRoll: emptyCallback,
    getChargeDestinations,
    // ADVANCE_IMPLEMENTATION_PLAN.md Phase 5: Export advance state and handler
    getAdvanceDestinations: getAdvanceDestinationsMemo,
    advancingUnitId,
    advanceRoll,
    onAdvance: handleAdvance,
    onCancelAdvance: handleCancelAdvance,
    advanceWarningPopup,
    onConfirmAdvanceWarning: handleConfirmAdvanceWarning,
    onCancelAdvanceWarning: handleCancelAdvanceWarning,
    onSkipAdvanceWarning: handleSkipAdvanceWarning,
    // Export blinking state for HP bar components
    blinkingUnits: blinkingUnitsIds,
    blinkingAttackerId: blinkingUnits.attackerId ?? null,
    isBlinkingActive: isBlinkingActiveMemo,
    blinkVersion,
    // blinkState removed - blinking is handled locally in UnitRenderer
    // Export charge roll info for failed charge display
    chargingUnitId: failedChargeRoll ? failedChargeRoll.unitId : null,
    chargeRoll: failedChargeRoll ? failedChargeRoll.roll : null,
    chargeSuccess: failedChargeRoll ? false : undefined,
    // Export charge target ID for target icon display (for both successful and failed charges)
    chargeTargetId: (() => {
      const targetId = failedChargeRoll?.targetId || successfulChargeTarget?.targetId || null;
      return targetId;
    })(),
    // Add AI turn execution for PvE mode
    executeAITurn: async () => {
      if (aiTurnInProgress) {
        return;
      }
      aiTurnInProgress = true;
      
      const urlParams = new URLSearchParams(window.location.search);
      const isDebugFromURL = urlParams.get('mode') === 'debug';
      
      // Check if AI has eligible units in current phase FIRST
      const phaseCheck = gameState.phase;
      
      if (!gameState || (!gameState.pve_mode && !isDebugFromURL)) {
        aiTurnInProgress = false;
        return;
      }
      
      // CRITICAL: In fight phase, current_player can be 1 but AI can still act in alternating phase
      // Only check current_player for non-fight phases
      if (phaseCheck !== 'fight' && gameState.current_player !== 2) {
        aiTurnInProgress = false;
        return;
      }
      let eligibleAICount = 0;
      
      if (phaseCheck === 'shoot' && gameState.shoot_activation_pool) {
        const shootPool = gameState.shoot_activation_pool || [];
        eligibleAICount = shootPool.filter(unitId => {
          // Normalize comparison: pools contain strings, unit.id might be number
          const unit = gameState.units.find(u => String(u.id) === String(unitId));
          return unit && unit.player === 2;
        }).length;
        console.log(`🎯 SHOOT PHASE AI CHECK: pool=${JSON.stringify(shootPool)}, eligibleAICount=${eligibleAICount}, current_player=${gameState.current_player}`);
      } else       if (phaseCheck === 'move' && gameState.move_activation_pool) {
        eligibleAICount = gameState.move_activation_pool.filter(unitId => {
          // Normalize comparison: pools contain strings, unit.id might be number
          const unit = gameState.units.find(u => String(u.id) === String(unitId));
          return unit && unit.player === 2;
        }).length;
      } else if (phaseCheck === 'charge' && gameState.charge_activation_pool) {
        eligibleAICount = gameState.charge_activation_pool.filter(unitId => {
          // Normalize comparison: pools contain strings, unit.id might be number
          const unit = gameState.units.find(u => String(u.id) === String(unitId));
          return unit && unit.player === 2;
        }).length;
      } else if (phaseCheck === 'fight') {
        // Fight phase has 3 sub-phases with different pools
        const fightSubphase = gameState.fight_subphase;
        
        let fightPool: string[] = [];
        if (fightSubphase === 'charging' && gameState.charging_activation_pool) {
          fightPool = gameState.charging_activation_pool;
        } else if (fightSubphase === 'alternating_active' && gameState.active_alternating_activation_pool) {
          fightPool = gameState.active_alternating_activation_pool;
        } else if (fightSubphase === 'alternating_non_active' && gameState.non_active_alternating_activation_pool) {
          fightPool = gameState.non_active_alternating_activation_pool;
        } else if (fightSubphase === 'cleanup_active' && gameState.active_alternating_activation_pool) {
          fightPool = gameState.active_alternating_activation_pool;
        } else if (fightSubphase === 'cleanup_non_active' && gameState.non_active_alternating_activation_pool) {
          fightPool = gameState.non_active_alternating_activation_pool;
        }
        
        eligibleAICount = fightPool.filter(unitId => {
          // Normalize comparison: pools contain strings, unit.id might be number
          const unit = gameState.units.find(u => String(u.id) === String(unitId));
          return unit && unit.player === 2;
        }).length;
      }
      
      if (eligibleAICount === 0) {
        console.log(`🤖 AI TURN SKIP: No eligible AI units in ${phaseCheck} phase (eligibleAICount=0)`);
        aiTurnInProgress = false;
        return;
      }
      
      // Check if AI has eligible units in current phase (already checked above, but keeping for clarity)
      const currentPhase = gameState.phase;
      let aiEligibleUnits = 0;
      
      if (currentPhase === 'move' && gameState.move_activation_pool) {
        aiEligibleUnits = gameState.move_activation_pool.filter(unitId => {
          // Normalize comparison: pools contain strings, unit.id might be number
          const unit = gameState.units.find(u => String(u.id) === String(unitId));
          return unit && unit.player === 2;
        }).length;
      } else if (currentPhase === 'shoot' && gameState.shoot_activation_pool) {
        const shootPool = gameState.shoot_activation_pool || [];
        aiEligibleUnits = shootPool.filter(unitId => {
          // Normalize comparison: pools contain strings, unit.id might be number
          const unit = gameState.units.find(u => String(u.id) === String(unitId));
          return unit && unit.player === 2;
        }).length;
        console.log(`🎯 SHOOT PHASE AI ELIGIBLE: pool=${JSON.stringify(shootPool)}, aiEligibleUnits=${aiEligibleUnits}`);
      } else if (currentPhase === 'charge' && gameState.charge_activation_pool) {
        aiEligibleUnits = gameState.charge_activation_pool.filter(unitId => {
          // Normalize comparison: pools contain strings, unit.id might be number
          const unit = gameState.units.find(u => String(u.id) === String(unitId));
          return unit && unit.player === 2;
        }).length;
      } else if (currentPhase === 'fight') {
        // Same fight pool logic as above
        const fightSubphase = gameState.fight_subphase;
        let fightPool: string[] = [];
        if (fightSubphase === 'charging' && gameState.charging_activation_pool) {
          fightPool = gameState.charging_activation_pool;
        } else if (fightSubphase === 'alternating_active' && gameState.active_alternating_activation_pool) {
          fightPool = gameState.active_alternating_activation_pool;
        } else if (fightSubphase === 'alternating_non_active' && gameState.non_active_alternating_activation_pool) {
          fightPool = gameState.non_active_alternating_activation_pool;
        } else if (fightSubphase === 'cleanup_active' && gameState.active_alternating_activation_pool) {
          fightPool = gameState.active_alternating_activation_pool;
        } else if (fightSubphase === 'cleanup_non_active' && gameState.non_active_alternating_activation_pool) {
          fightPool = gameState.non_active_alternating_activation_pool;
        }
        
        aiEligibleUnits = fightPool.filter(unitId => {
          // Normalize comparison: pools contain strings, unit.id might be number
          const unit = gameState.units.find(u => String(u.id) === String(unitId));
          return unit && unit.player === 2;
        }).length;
      }
      
      if (aiEligibleUnits === 0) {
        console.log(`🤖 AI TURN SKIP: No eligible AI units in ${currentPhase} phase (aiEligibleUnits=0)`);
        aiTurnInProgress = false;
        return;
      }
      
      // Helper function to make AI movement decision
      const makeMovementDecision = (validDestinations: number[][], unitId: string, currentGameState: APIGameState) => {
        if (!validDestinations || validDestinations.length === 0) {
          return { action: 'skip', unitId };
        }
        
        // Strategy: Move toward nearest enemy using FRESH game state
        const enemies = currentGameState?.units.filter((u) => u.player === 1 && u.HP_CUR > 0) || [];
        
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
        const currentUnit = currentGameState?.units.find((u) => u.id.toString() === unitId);
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
        
        // CRITICAL FIX: Use proper hex distance calculation (cubeDistance from gameHelpers)
        const nearestEnemy = enemies.reduce((nearest, enemy) => {
          const distToCurrent = cubeDistance(offsetToCube(currentUnit.col, currentUnit.row), offsetToCube(enemy.col, enemy.row));
          const distToNearest = cubeDistance(offsetToCube(currentUnit.col, currentUnit.row), offsetToCube(nearest.col, nearest.row));
          return distToCurrent < distToNearest ? enemy : nearest;
        });
        
        // Pick destination closest to nearest enemy FROM VALID DESTINATIONS ONLY
        const bestDestination = validDestinations.reduce((best, dest) => {
          const distToEnemy = cubeDistance(offsetToCube(dest[0], dest[1]), offsetToCube(nearestEnemy.col, nearestEnemy.row));
          const bestDistToEnemy = cubeDistance(offsetToCube(best[0], best[1]), offsetToCube(nearestEnemy.col, nearestEnemy.row));
          return distToEnemy < bestDistToEnemy ? dest : best;
        });
        
        return {
          action: 'move',
          unitId,
          destCol: bestDestination[0],
          destRow: bestDestination[1]
        };
      };
      
      // Helper function to make AI shooting decision
      const makeShootingDecision = (validTargets: string[], unitId: string, currentGameState: APIGameState) => {
        if (!validTargets || validTargets.length === 0) {
          return { action: 'skip', unitId };
        }
        
        // Strategy: Shoot nearest/most threatening target using fresh game state
        const shooter = currentGameState?.units.find((u) => u.id.toString() === unitId);
        if (!shooter) {
          return {
            action: 'shoot',
            unitId,
            targetId: validTargets[0]
          };
        }
        
        // Find nearest target
        const nearestTarget = validTargets.reduce((nearest, targetId) => {
          const target = currentGameState?.units.find((u) => u.id.toString() === targetId);
          const nearestTargetUnit = currentGameState?.units.find((u) => u.id.toString() === nearest);
          
          if (!target || !nearestTargetUnit) return nearest;
          
          const distToCurrent = cubeDistance(offsetToCube(target.col, target.row), offsetToCube(shooter.col, shooter.row));
          const distToNearest = cubeDistance(offsetToCube(nearestTargetUnit.col, nearestTargetUnit.row), offsetToCube(shooter.col, shooter.row));
          
          return distToCurrent < distToNearest ? targetId : nearest;
        });
        
        return {
          action: 'shoot',
          unitId,
          targetId: nearestTarget
        };
      };

      // Helper function to make AI fight decision
      const makeFightDecision = (validTargets: Array<{ id: string | number }> | string[], unitId: string, currentGameState: APIGameState) => {
        if (!validTargets || validTargets.length === 0) {
          return { action: 'skip', unitId };
        }
        
        // Strategy: Attack nearest/most threatening target using fresh game state
        const attacker = currentGameState?.units.find((u) => u.id.toString() === unitId);
        if (!attacker) {
          // Extract target ID from first target (could be object or string)
          const firstTarget = validTargets[0];
          const targetId = typeof firstTarget === 'object' ? firstTarget.id : firstTarget;
          return {
            action: 'fight',
            unitId,
            targetId: targetId.toString()
          };
        }
        
        // Find nearest target
        const nearestTarget = validTargets.reduce((nearest, target) => {
          const targetId = typeof target === 'object' ? target.id : target;
          const targetUnit = currentGameState?.units.find((u) => u.id.toString() === targetId.toString());
          const nearestTargetId = typeof nearest === 'object' ? nearest.id : nearest;
          const nearestTargetUnit = currentGameState?.units.find((u) => u.id.toString() === nearestTargetId.toString());
          
          if (!targetUnit || !nearestTargetUnit) return nearest;
          
          const distToCurrent = cubeDistance(offsetToCube(targetUnit.col, targetUnit.row), offsetToCube(attacker.col, attacker.row));
          const distToNearest = cubeDistance(offsetToCube(nearestTargetUnit.col, nearestTargetUnit.row), offsetToCube(attacker.col, attacker.row));
          
          return distToCurrent < distToNearest ? target : nearest;
        });
        
        const finalTargetId = typeof nearestTarget === 'object' ? nearestTarget.id : nearestTarget;
        return {
          action: 'fight',
          unitId,
          targetId: finalTargetId.toString()
        };
      };
      
      try {
        let totalUnitsProcessed = 0;
        const maxIterations = 10; // Reduced to prevent infinite loops
        let iteration = 0;
        let lastPoolSize = -1;
        let samePoolSizeCount = 0;
        
        while (iteration < maxIterations) {
          iteration++;
          
          console.log(`🤖 AI Sequential Step ${iteration}: Activating next AI unit (phase=${gameState?.phase}, current_player=${gameState?.current_player})`);
          
          const canCallAiTurn = (() => {
            if (!gameState) {
              throw new Error("Missing gameState during AI turn check");
            }
            if (gameState.current_player === undefined || gameState.current_player === null) {
              throw new Error("Missing current_player in gameState during AI turn check");
            }
            if (gameState.phase === 'fight') {
              const fightSubphase = gameState.fight_subphase;
              if (!fightSubphase) {
                throw new Error("Missing fight_subphase in gameState during AI turn check");
              }
              let pool: Array<string | number> | undefined;
              if (fightSubphase === 'charging') {
                pool = gameState.charging_activation_pool;
              } else if (fightSubphase === 'alternating_non_active' || fightSubphase === 'cleanup_non_active') {
                pool = gameState.non_active_alternating_activation_pool;
              } else if (fightSubphase === 'alternating_active' || fightSubphase === 'cleanup_active') {
                pool = gameState.active_alternating_activation_pool;
              } else {
                throw new Error(`Unknown fight_subphase during AI turn check: ${fightSubphase}`);
              }
              if (!pool) {
                throw new Error(`Missing fight activation pool for subphase: ${fightSubphase}`);
              }
              const aiUnitIds = new Set(
                gameState.units.filter(u => u.player === 2).map(u => u.id.toString())
              );
              return pool.some(id => aiUnitIds.has(id.toString()));
            }
            return gameState.current_player === 2;
          })();

          if (!canCallAiTurn) {
            break;
          }

          // Step 1: Call backend to activate next AI unit
          const aiResponse = await fetch(`${API_BASE}/game/ai-turn`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
          });
          
          if (!aiResponse.ok) {
            const errorData = await aiResponse.json().catch(() => ({}));
            const errorInfo = errorData.error || errorData;
            
            // Handle expected errors gracefully (AI not eligible or turn already advanced)
            if (errorInfo.error === 'not_ai_player_turn') {
              // No more eligible AI units - fetch current game state and exit gracefully
              try {
                const stateResponse = await fetch(`${API_BASE}/game/state`);
                if (stateResponse.ok) {
                  const stateData = await stateResponse.json();
                  if (stateData.game_state) {
                    setGameState(stateData.game_state);
                  }
                }
              } catch (stateErr) {
                console.warn('Failed to fetch game state after AI error:', stateErr);
              }
              // Exit loop - no more AI units eligible
              break;
            }
            
            // For other errors, log and throw
            console.error(`❌ [FRONTEND] AI activation failed: status=${aiResponse.status}, error=`, errorData);
            throw new Error(`AI activation failed: ${aiResponse.status} - ${JSON.stringify(errorData)}`);
          }
          
          const activationData = await aiResponse.json();
          
          // Process AI activation logs immediately
          if (activationData.action_logs && activationData.action_logs.length > 0) {
            interface ActivationLogEntry {
              message?: string;
              type?: string;
              turn?: number;
              phase?: string;
              shooterId?: string;
              targetId?: string;
              player?: number;
              damage?: number;
              target_died?: boolean;
              hitRoll?: number;
              woundRoll?: number;
              saveRoll?: number;
              saveTarget?: number;
              weaponName?: string;
              action_name?: string;
              reward?: number;
              is_ai_action?: boolean;
              [key: string]: unknown;
            }
            activationData.action_logs.forEach((logEntry: ActivationLogEntry) => {
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
                  weaponName: logEntry.weaponName,  // MULTIPLE_WEAPONS_IMPLEMENTATION.md
                  action_name: logEntry.action_name,
                  reward: logEntry.reward,
                  is_ai_action: logEntry.is_ai_action,
                  timestamp: new Date()
                }
              }));
            });
          }
          
          if (!activationData.success) {
            console.error(`❌ AI activation failed:`, activationData);
            console.error(`AI decision failed:`, activationData);
            break;
          }
          
          // Update game state from activation
          if (activationData.game_state) {
            setGameState(activationData.game_state);
          }
          
          // Step 2: Check if we got a preview response requiring decision
          if (activationData.result?.waiting_for_player) {
            let aiDecision;
            const unitId = activationData.result?.unitId || 
                          (activationData.game_state?.active_movement_unit) ||
                          (activationData.game_state?.active_shooting_unit);
            
            // Step 3: Make AI decision based on preview data using FRESH game state
            const currentPhase = activationData.game_state?.phase;
            
            if (activationData.result.valid_destinations) {
              if (currentPhase === 'charge') {
                // Charge phase - we have destinations after target selection and roll
                // Pick best destination and execute charge
                const validDestinations = activationData.result.valid_destinations;
                
                if (!validDestinations || validDestinations.length === 0) {
                  aiDecision = { action: 'skip', unitId };
                } else {
                  interface ChargeUnit {
                    id: string | number;
                    player: number;
                    HP_CUR: number;
                    col: number;
                    row: number;
                  }
                  const currentUnit = activationData.game_state?.units.find((u: ChargeUnit) => String(u.id) === String(unitId));
                  
                  if (!currentUnit) {
                    aiDecision = { action: 'skip', unitId };
                  } else {
                    // Find enemies
                    const enemies = activationData.game_state?.units.filter((u: ChargeUnit) => 
                      u.player !== currentUnit.player && u.HP_CUR > 0
                    ) || [];
                    
                    if (enemies.length === 0) {
                      aiDecision = { action: 'skip', unitId };
                    } else {
                      // Find nearest enemy
                      const nearestEnemy = enemies.reduce((nearest: ChargeUnit, enemy: ChargeUnit) => {
                        const distToCurrent = cubeDistance(offsetToCube(enemy.col, enemy.row), offsetToCube(currentUnit.col, currentUnit.row));
                        const distToNearest = cubeDistance(offsetToCube(nearest.col, nearest.row), offsetToCube(currentUnit.col, currentUnit.row));
                        return distToCurrent < distToNearest ? enemy : nearest;
                      });
                      
                      // Pick destination closest to nearest enemy
                      const bestDestination = validDestinations.reduce((best: number[], dest: number[]) => {
                        const distToEnemy = cubeDistance(offsetToCube(dest[0], dest[1]), offsetToCube(nearestEnemy.col, nearestEnemy.row));
                        const bestDistToEnemy = cubeDistance(offsetToCube(best[0], best[1]), offsetToCube(nearestEnemy.col, nearestEnemy.row));
                        return distToEnemy < bestDistToEnemy ? dest : best;
                      });
                      
                      // Execute charge with destination (targetId is already stored in game_state from previous step)
                      aiDecision = {
                        action: 'charge',
                        unitId,
                        destCol: bestDestination[0],
                        destRow: bestDestination[1]
                        // Note: targetId is NOT needed here - it's stored in game_state from target selection step
                      };
                    }
                  }
                }
              } else {
                // Movement phase - pick destination using fresh backend state
                aiDecision = makeMovementDecision(
                  activationData.result.valid_destinations, 
                  unitId,
                  activationData.game_state
                );
              }
            } else if (currentPhase === 'charge' && activationData.result.blinking_units && activationData.result.start_blinking) {
              // Charge phase - we have blinking_units (potential targets) but no destinations yet
              // Step 1: Select target (this will trigger roll and build destinations)
              const blinkingUnits = activationData.result.blinking_units;
              
              if (!blinkingUnits || blinkingUnits.length === 0) {
                aiDecision = { action: 'skip', unitId };
              } else {
                interface ChargeUnit {
                  id: string | number;
                  player: number;
                  HP_CUR: number;
                  col: number;
                  row: number;
                }
                const currentUnit = activationData.game_state?.units.find((u: ChargeUnit) => String(u.id) === String(unitId));
                
                if (!currentUnit) {
                  aiDecision = { action: 'skip', unitId };
                } else {
                  // Find nearest enemy from blinking_units
                  const enemies = activationData.game_state?.units.filter((u: ChargeUnit) => 
                    u.player !== currentUnit.player && 
                    u.HP_CUR > 0 &&
                    blinkingUnits.includes(String(u.id))
                  ) || [];
                  
                  if (enemies.length === 0) {
                    aiDecision = { action: 'skip', unitId };
                  } else {
                    // Find nearest enemy
                    const nearestEnemy = enemies.reduce((nearest: ChargeUnit, enemy: ChargeUnit) => {
                      const distToCurrent = cubeDistance(offsetToCube(enemy.col, enemy.row), offsetToCube(currentUnit.col, currentUnit.row));
                      const distToNearest = cubeDistance(offsetToCube(nearest.col, nearest.row), offsetToCube(currentUnit.col, currentUnit.row));
                      return distToCurrent < distToNearest ? enemy : nearest;
                    });
                    
                    // Step 1: Select target (this will roll 2d6 and build destinations)
                    aiDecision = {
                      action: 'charge',
                      unitId,
                      targetId: nearestEnemy.id
                      // Note: NO destCol/destRow here - that's step 2
                    };
                  }
                }
              }
            } else if (activationData.result.valid_targets) {
              // Handle valid targets (uniformized to snake_case in backend)
              const targets = activationData.result.valid_targets;
              
              if (currentPhase === 'fight') {
                // Fight phase - pick target using fresh backend state
                aiDecision = makeFightDecision(
                  targets, 
                  unitId,
                  activationData.game_state
                );
              } else {
                // Shooting phase - pick target using fresh backend state
                aiDecision = makeShootingDecision(
                  targets, 
                  unitId,
                  activationData.game_state
                );
              }
            } else {
              console.error('Unknown preview type:', activationData.result);
              break;
            }
            
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
            
            if (decisionData.success) {
              // Process action logs
              if (decisionData.action_logs && decisionData.action_logs.length > 0) {
                interface DecisionLogEntry {
                  message?: string;
                  type?: string;
                  turn?: number;
                  phase?: string;
                  shooterId?: string;
                  targetId?: string;
                  player?: number;
                  damage?: number;
                  target_died?: boolean;
                  hitRoll?: number;
                  woundRoll?: number;
                  saveRoll?: number;
                  saveTarget?: number;
                  weaponName?: string;
                  action_name?: string;
                  reward?: number;
                  is_ai_action?: boolean;
                  [key: string]: unknown;
                }
                decisionData.action_logs.forEach((logEntry: DecisionLogEntry) => {
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
                      weaponName: logEntry.weaponName,  // MULTIPLE_WEAPONS_IMPLEMENTATION.md
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
                break;
              }
              
            } else {
              console.error('AI decision failed:', decisionData);
              break;
            }
            
          } else if (activationData.result?.activation_ended) {
            // Unit completed activation immediately (SKIP, no valid targets, etc.)
            totalUnitsProcessed++;
            
            // Check if phase complete after unit completion
            if (activationData.result?.phase_complete) {
              break;
            }
            
          } else if (!activationData.result?.waiting_for_player && 
                     !activationData.result?.valid_targets && 
                     !activationData.result?.valid_destinations) {
            // No valid action available - skip this unit
            // This can happen when unit has no valid targets in shoot phase
            const unitId = activationData.result?.unitId || 
                          (activationData.game_state?.active_shooting_unit) ||
                          (activationData.game_state?.active_movement_unit);
            
            if (unitId) {
              // Send skip action to backend
              try {
                const skipResponse = await fetch(`${API_BASE}/game/action`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ action: 'skip', unitId: String(unitId) })
                });
                
                if (skipResponse.ok) {
                  const skipData = await skipResponse.json();
                  setGameState(skipData.game_state);
                  totalUnitsProcessed++;
                  
                  if (skipData.result?.phase_complete) {
                    break;
                  }
                }
              } catch (err) {
                console.error('Failed to skip unit:', err);
                break; // Exit loop on error
              }
            } else {
              // No unit ID available - exit loop to prevent infinite loop
              console.warn('AI loop: No valid action and no unit ID - breaking');
              break;
            }
            
            // CRITICAL: Check if pool size changed (unit was removed)
            const updatedGameState = activationData.game_state;
            const currentPhase = updatedGameState?.phase;
            let currentPoolSize = 0;
            
            if (currentPhase === 'fight') {
              const fightSubphase = updatedGameState?.fight_subphase;
              if (fightSubphase === 'charging' && updatedGameState?.charging_activation_pool) {
                currentPoolSize = updatedGameState.charging_activation_pool.length;
              } else if (fightSubphase === 'alternating_non_active' && updatedGameState?.non_active_alternating_activation_pool) {
                currentPoolSize = updatedGameState.non_active_alternating_activation_pool.length;
              } else if (fightSubphase === 'alternating_active' && updatedGameState?.active_alternating_activation_pool) {
                currentPoolSize = updatedGameState.active_alternating_activation_pool.length;
              } else if (fightSubphase === 'cleanup_non_active' && updatedGameState?.non_active_alternating_activation_pool) {
                currentPoolSize = updatedGameState.non_active_alternating_activation_pool.length;
              } else if (fightSubphase === 'cleanup_active' && updatedGameState?.active_alternating_activation_pool) {
                currentPoolSize = updatedGameState.active_alternating_activation_pool.length;
              }
            } else if (currentPhase === 'move' && updatedGameState?.move_activation_pool) {
              currentPoolSize = updatedGameState.move_activation_pool.length;
            } else if (currentPhase === 'charge' && updatedGameState?.charge_activation_pool) {
              currentPoolSize = updatedGameState.charge_activation_pool.length;
            }
            
            // If pool is empty, break
            if (currentPoolSize === 0) {
              break;
            }
            
            // Safety: If pool size hasn't changed after multiple skips, break
            if (currentPoolSize === lastPoolSize) {
              samePoolSizeCount++;
              if (samePoolSizeCount >= 3) {
                console.warn(`AI Step ${iteration}: Pool size unchanged after ${samePoolSizeCount} skips - breaking to prevent infinite loop`);
                break;
              }
            } else {
              samePoolSizeCount = 0;
              lastPoolSize = currentPoolSize;
            }
            
            // Check if there are still eligible AI units in the pool
            let hasMoreEligibleUnits = false;
            if (currentPhase === 'fight') {
              const fightSubphase = updatedGameState?.fight_subphase;
              let fightPool: string[] = [];
              if (fightSubphase === 'charging' && updatedGameState?.charging_activation_pool) {
                fightPool = updatedGameState.charging_activation_pool;
              } else if (fightSubphase === 'alternating_non_active' && updatedGameState?.non_active_alternating_activation_pool) {
                fightPool = updatedGameState.non_active_alternating_activation_pool;
              } else if (fightSubphase === 'alternating_active' && updatedGameState?.active_alternating_activation_pool) {
                fightPool = updatedGameState.active_alternating_activation_pool;
              } else if (fightSubphase === 'cleanup_non_active' && updatedGameState?.non_active_alternating_activation_pool) {
                fightPool = updatedGameState.non_active_alternating_activation_pool;
              } else if (fightSubphase === 'cleanup_active' && updatedGameState?.active_alternating_activation_pool) {
                fightPool = updatedGameState.active_alternating_activation_pool;
              }
              
              hasMoreEligibleUnits = fightPool.some(unitId => {
                const unit = updatedGameState?.units?.find((u: APIGameState['units'][0]) => String(u.id) === String(unitId));
                return unit && unit.player === 2 && (unit.HP_CUR ?? unit.HP_MAX) > 0;
              });
            } else if (currentPhase === 'move' && updatedGameState?.move_activation_pool) {
              hasMoreEligibleUnits = updatedGameState.move_activation_pool.some((unitId: string) => {
                const unit = updatedGameState?.units?.find((u: APIGameState['units'][0]) => String(u.id) === String(unitId));
                return unit && unit.player === 2 && (unit.HP_CUR ?? unit.HP_MAX) > 0;
              });
            } else if (currentPhase === 'charge' && updatedGameState?.charge_activation_pool) {
              hasMoreEligibleUnits = updatedGameState.charge_activation_pool.some((unitId: string) => {
                const unit = updatedGameState?.units?.find((u: APIGameState['units'][0]) => String(u.id) === String(unitId));
                return unit && unit.player === 2 && (unit.HP_CUR ?? unit.HP_MAX) > 0;
              });
            }
            
            if (!hasMoreEligibleUnits) {
              break;
            }
            
            // Safety: If we've processed many units without progress, break
            if (totalUnitsProcessed >= 5 && iteration >= 10) {
              console.warn(`AI Step ${iteration}: Safety break - processed ${totalUnitsProcessed} units in ${iteration} steps without progress`);
              break;
            }
            
          } else if (activationData.result?.phase_complete) {
            // Phase already complete
            break;
            
          } else {
            // Unexpected response format - continue
          }
          
          // Small delay for UX
          await new Promise(resolve => setTimeout(resolve, 150));
        }
        
        if (iteration >= maxIterations) {
          console.warn(`AI reached maximum iterations (${maxIterations})`);
        }
        
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