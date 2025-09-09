// frontend/src/hooks/useEngineAPI.ts
import { useState, useEffect, useCallback } from 'react';
import type { Unit, PlayerId } from '../types';

// Get max_turns from config instead of hardcoded fallback
const getMaxTurnsFromConfig = async (): Promise<number> => {
  try {
    const response = await fetch('/config/game_config.json');
    const config = await response.json();
    return config.game_rules?.max_turns ?? 8;
  } catch (error) {
    console.warn('Failed to load max_turns from config, using fallback:', error);
    return 8;
  }
};

const API_BASE = 'http://localhost:5000/api';

interface APIGameState {
  units: Array<{
    id: string;
    player: number;
    col: number;
    row: number;
    HP_CUR: number;
    HP_MAX: number;
    MOVE: number;
    RNG_RNG: number;
    RNG_DMG: number;
    RNG_NB: number;
    RNG_ATK: number;
    CC_DMG: number;
    CC_RNG?: number;
    CC_NB: number;
    CC_ATK: number;
    CC_STR: number;
    ICON: string;
    ICON_SCALE?: number;
    unitType: string;
    SHOOT_LEFT?: number;
    ATTACK_LEFT?: number;
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
}

export const useEngineAPI = () => {
  const [gameState, setGameState] = useState<APIGameState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [maxTurnsFromConfig, setMaxTurnsFromConfig] = useState<number>(8);
  const [selectedUnitId, setSelectedUnitId] = useState<number | null>(null);
  const [mode, setMode] = useState<"select" | "movePreview" | "attackPreview" | "targetPreview" | "chargePreview">("select");
  const [movePreview, setMovePreview] = useState<{ unitId: number; destCol: number; destRow: number } | null>(null);
  const [targetPreview, setTargetPreview] = useState<{shooterId: number, targetId: number} | null>(null);
  
  // AI_TURN.md: Shooting phase state management
  const [shootingState, setShootingState] = useState<{
    activeShooterId: number | null;
    shootLeft: number;
    rngNb: number;
    validTargetPool: number[];
    totalActionLog: string;
  }>({
    activeShooterId: null,
    shootLeft: 0,
    rngNb: 0,
    validTargetPool: [],
    totalActionLog: ""
  });

  // Load config values
  useEffect(() => {
    getMaxTurnsFromConfig().then(setMaxTurnsFromConfig);
  }, []);

  // Initialize game
  useEffect(() => {
    const startGame = async () => {
      try {
        setLoading(true);
        const response = await fetch(`${API_BASE}/game/start`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' }
        });
        
        if (!response.ok) {
          throw new Error(`Failed to start game: ${response.status}`);
        }
        
        const data = await response.json();
        if (data.success) {
          setGameState(data.game_state);
        } else {
          throw new Error(data.error || 'Failed to start game');
        }
      } catch (err) {
        console.error('🔍 API Error:', err);
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };
    
    startGame();
  }, []);

  // Execute action via API
  const executeAction = useCallback(async (action: any) => {
    if (!gameState) return;
    
    try {
      const requestBody = JSON.stringify(action);
      console.log("📡 SENDING API REQUEST:", requestBody);
      const response = await fetch(`${API_BASE}/game/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: requestBody
      });
      
      if (!response.ok) {
        throw new Error(`Action failed: ${response.status}`);
      }
      
      const data = await response.json();
      console.log("✅ API RESPONSE:", data);
      if (data.success) {
        console.log("🔄 UPDATING GAME STATE");
        setGameState(data.game_state);
        setSelectedUnitId(null); // Reset after game state is updated
        console.log("✅ GAME STATE UPDATED");
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
        RNG_RNG: unit.RNG_RNG,
        RNG_DMG: unit.RNG_DMG,
        RNG_NB: unit.RNG_NB,
        RNG_ATK: unit.RNG_ATK,
        CC_DMG: unit.CC_DMG,
        CC_RNG: unit.CC_RNG,
        CC_NB: unit.CC_NB,
        CC_ATK: unit.CC_ATK,
        CC_STR: unit.CC_STR,
        ICON: unit.ICON,
        ICON_SCALE: unit.ICON_SCALE,
        SHOOT_LEFT: unit.SHOOT_LEFT,
        ATTACK_LEFT: unit.ATTACK_LEFT,
      };
    });
  }, []);

  // Event handlers
  const handleSelectUnit = useCallback((unitId: number | string | null) => {
    const numericUnitId = typeof unitId === 'string' ? parseInt(unitId) : unitId;
    
    // AI_TURN.md: Shooting phase click handling
    if (gameState && gameState.phase === "shoot") {
      
      // Case 1: No unit currently selected - start activation
      if (selectedUnitId === null && numericUnitId !== null) {
        // AI_TURN.md: Clear any unit remaining in valid_target_pool + Clear TOTAL_ATTACK log + SHOOT_LEFT = RNG_NB
        const unit = gameState.units.find(u => parseInt(u.id) === numericUnitId);
        if (unit) {
          setShootingState({
            activeShooterId: numericUnitId,
            shootLeft: unit.RNG_NB,
            rngNb: unit.RNG_NB,
            validTargetPool: [],
            totalActionLog: ""
          });
          setSelectedUnitId(numericUnitId);
          setMode("attackPreview");
        }
        return;
      }
      
      // Case 2: Unit already selected
      if (selectedUnitId !== null) {
        
        // Case 2a: Left click on active unit during target preview - no effect
        if (mode === "targetPreview" && numericUnitId === selectedUnitId) {
          return;
        }
        
        // Case 2b: Left click on another unit
        if (numericUnitId !== selectedUnitId && numericUnitId !== null) {
          // AI_TURN.md: Check if SHOOT_LEFT = RNG_NB for postpone
          if (shootingState.shootLeft === shootingState.rngNb) {
            // Can postpone - start new unit activation
            const newUnit = gameState.units.find(u => parseInt(u.id) === numericUnitId);
            if (newUnit) {
              setShootingState({
                activeShooterId: numericUnitId,
                shootLeft: newUnit.RNG_NB,
                rngNb: newUnit.RNG_NB,
                validTargetPool: [],
                totalActionLog: ""
              });
              setSelectedUnitId(numericUnitId);
              setMode("attackPreview");
              setTargetPreview(null);
            }
          }
          // If SHOOT_LEFT < RNG_NB, unit must end activation - no switch allowed
          return;
        }
        
        // Case 2c: Left click on same unit
        if (numericUnitId === selectedUnitId) {
          // During attackPreview - no effect per AI_TURN.md
          return;
        }
      }
    }
    
    // Normal unit selection for other phases
    setSelectedUnitId(numericUnitId);
    setMode("select");
    setMovePreview(null);
    setTargetPreview(null);
    setShootingState({
      activeShooterId: null,
      shootLeft: 0,
      rngNb: 0,
      validTargetPool: [],
      totalActionLog: ""
    });
  }, [gameState, mode, selectedUnitId, shootingState]);

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
      // Let executeAction handle state reset after updating game state
      setMovePreview(null);
      setMode("select");
      // Don't reset selectedUnitId here - let it reset when gameState updates
    } catch (error) {
      console.error("Move failed:", error);
      // Don't reset state if move failed
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

  const handleShoot = useCallback(async (shooterId: number | string, targetId: number | string) => {
    const action = {
      action: "shoot",
      unitId: typeof shooterId === 'string' ? shooterId : shooterId.toString(),
      targetId: typeof targetId === 'string' ? targetId : targetId.toString(),
    };
    
    try {
      await executeAction(action);
      
      // AI_TURN.md: SHOOT_LEFT -= 1, update total action log
      const newShootLeft = Math.max(0, shootingState.shootLeft - 1);
      setShootingState(prev => ({
        ...prev,
        shootLeft: newShootLeft,
        totalActionLog: prev.totalActionLog + `Shot at target ${targetId}; `
      }));
      
      setTargetPreview(null);
      
      // If SHOOT_LEFT > 0, continue shooting
      if (newShootLeft > 0) {
        setMode("attackPreview");
      } else {
        // End activation when SHOOT_LEFT = 0
        setSelectedUnitId(null);
        setMode("select");
        setShootingState({
          activeShooterId: null,
          shootLeft: 0,
          rngNb: 0,
          validTargetPool: [],
          totalActionLog: ""
        });
      }
    } catch (error) {
      console.error("Shoot action failed:", error);
    }
  }, [executeAction, shootingState]);

  const handleSkipShoot = useCallback(async (unitId: number | string, actionType: 'wait' | 'action' = 'action') => {
    const action = {
      action: actionType === 'wait' ? "wait" : "skip",
      unitId: typeof unitId === 'string' ? unitId : unitId.toString(),
    };
    
    try {
      await executeAction(action);
      // AI_TURN.md: Both WAIT and ACTION end activation
      setSelectedUnitId(null);
      setTargetPreview(null);
      setMode("select");
      setShootingState({
        activeShooterId: null,
        shootLeft: 0,
        rngNb: 0,
        validTargetPool: [],
        totalActionLog: ""
      });
    } catch (error) {
      console.error("Skip/Wait shoot failed:", error);
    }
  }, [executeAction]);

  const handleStartTargetPreview = useCallback((shooterId: number | string, targetId: number | string) => {
    // Start HP bar blinking animation for target
    setMode("targetPreview");
    setTargetPreview({
      shooterId: typeof shooterId === 'number' ? shooterId : parseInt(shooterId),
      targetId: typeof targetId === 'number' ? targetId : parseInt(targetId)
    });
  }, []);

  // Get eligible units
  const getEligibleUnitIds = useCallback((): number[] => {
    if (!gameState) return [];
    
    if (gameState.phase === 'move') {
      return gameState.move_activation_pool.map(id => parseInt(id)).filter(id => !isNaN(id));
    }
    
    return gameState.units
      .filter(unit => unit.player === gameState.current_player)
      .map(unit => parseInt(unit.id))
      .filter(id => !isNaN(id));
  }, [gameState]);

  const getChargeDestinations = useCallback((_unitId: number) => {
    return [];
  }, []);

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
      currentPlayer: null,
      maxTurns: null,
      unitsMoved: [],
      unitsCharged: [],
      unitsAttacked: [],
      unitsFled: [],
      phase: null,
      gameState: null,
      onSelectUnit: () => {},
      onStartMovePreview: () => {},
      onDirectMove: () => {},
      onStartAttackPreview: () => {},
      onConfirmMove: () => {},
      onCancelMove: () => {},
      onShoot: () => {},
      onFightAttack: () => {},
      onCharge: () => {},
      onMoveCharger: () => {},
      onCancelCharge: () => {},
      onValidateCharge: () => {},
      onLogChargeRoll: () => {},
      getChargeDestinations: () => [],
    };
  }

  return {
    loading: false,
    error: null,
    units: convertUnits(gameState.units),
    selectedUnitId,
    eligibleUnitIds: getEligibleUnitIds(),
    mode,
    movePreview,
    attackPreview: null,
    targetPreview,
    currentPlayer: gameState.current_player as PlayerId,
    maxTurns: maxTurnsFromConfig,
    unitsMoved: gameState.units_moved ? gameState.units_moved.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_moved array'); })(),
    unitsCharged: gameState.units_charged ? gameState.units_charged.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_charged array'); })(),
    unitsAttacked: gameState.units_attacked ? gameState.units_attacked.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_attacked array'); })(),
    unitsFled: gameState.units_fled ? gameState.units_fled.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_fled array'); })(),
    phase: gameState.phase as "move" | "shoot" | "charge" | "fight",
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
    },
    onSelectUnit: handleSelectUnit,
    onSkipUnit: handleSkipUnit,
    onStartMovePreview: handleStartMovePreview,
    onDirectMove: handleDirectMove,
    onStartAttackPreview: (unitId: number) => {
      setSelectedUnitId(typeof unitId === 'string' ? parseInt(unitId) : unitId);
      setMode("attackPreview");
    },
    onConfirmMove: handleConfirmMove,
    onCancelMove: handleCancelMove,
    onShoot: handleShoot,
    onSkipShoot: handleSkipShoot,
    onStartTargetPreview: handleStartTargetPreview,
    onFightAttack: () => {},
    onCharge: () => {},
    onMoveCharger: () => {},
    onCancelCharge: () => {},
    onValidateCharge: () => {},
    onLogChargeRoll: () => {},
    getChargeDestinations,
  };
};