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
  // AI_TURN.md shooting phase state
  active_shooting_unit?: string;
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
      const response = await fetch(`${API_BASE}/game/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: requestBody
      });
      
      if (!response.ok) {
        throw new Error(`Action failed: ${response.status}`);
      }
      
      const data = await response.json();
      if (data.success) {
        // Only log shooting phase state changes
        if (data.game_state?.phase === "shoot" && data.game_state?.active_shooting_unit) {
          console.log("🎯 UNIT ACTIVATED:", data.game_state.active_shooting_unit);
        }
        setGameState(data.game_state);
        
        // Set visual state based on shooting activation
        if (data.game_state?.phase === "shoot" && data.game_state?.active_shooting_unit) {
          console.log("  🎯 SETTING ATTACK PREVIEW MODE");
          setSelectedUnitId(parseInt(data.game_state.active_shooting_unit));
          setMode("attackPreview");
        } else {
          setSelectedUnitId(null);
        }
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
    // AI_TURN.md: Shooting phase activation with comprehensive debugging
    if (gameState && gameState.phase === "shoot") {
      console.log("🎯 SHOOTING PHASE CLICK DEBUG:");
      console.log("  - Phase:", gameState.phase);
      console.log("  - Clicked unit ID:", numericUnitId);
      console.log("  - Active shooting unit:", gameState.active_shooting_unit);
      console.log("  - Shoot activation pool:", gameState.shoot_activation_pool);
      
      if (numericUnitId !== null) {
        const shootActivationPool = gameState.shoot_activation_pool?.map(id => parseInt(id)) || [];
        console.log("  - Parsed pool:", shootActivationPool);
        console.log("  - Unit in pool?", shootActivationPool.includes(numericUnitId));
        console.log("  - No active unit?", !gameState.active_shooting_unit);
        
        if (shootActivationPool.includes(numericUnitId) && !gameState.active_shooting_unit) {
          console.log("  ✅ ACTIVATING UNIT:", numericUnitId);
          await executeAction({
            action: "activate_unit", 
            unitId: numericUnitId.toString()
          });
          return;
        } else if (gameState.active_shooting_unit) {
          console.log("  ✅ SENDING LEFT_CLICK - Active unit exists");
          console.log("    - Active unit:", gameState.active_shooting_unit);
          console.log("    - Target unit:", numericUnitId);
          console.log("    - Click target type:", determineClickTarget(numericUnitId, gameState));
          await executeAction({
            action: "left_click",
            unitId: gameState.active_shooting_unit,
            targetId: numericUnitId.toString(),
            clickTarget: determineClickTarget(numericUnitId, gameState)
          });
          return;
        } else {
          console.log("  ❌ NO ACTION: Unit not in pool or conditions not met");
          console.log("    - Unit in pool:", shootActivationPool.includes(numericUnitId));
          console.log("    - Active unit exists:", !!gameState.active_shooting_unit);
        }
      } else {
        console.log("  ❌ NO ACTION: numericUnitId is null");
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

  const handleStartTargetPreview = useCallback((shooterId: number | string, targetId: number | string) => {
    console.log("🎯 STARTING TARGET PREVIEW:", {shooterId, targetId});
    setTargetPreview({
      shooterId: typeof shooterId === 'number' ? shooterId : parseInt(shooterId),
      targetId: typeof targetId === 'number' ? targetId : parseInt(targetId)
    });
    setMode("targetPreview");
    console.log("✅ TARGET PREVIEW STATE SET");
  }, []);

  // Get eligible units
  const getEligibleUnitIds = useCallback((): number[] => {
    if (!gameState) return [];
    
    if (gameState.phase === 'move') {
      return gameState.move_activation_pool.map(id => parseInt(id)).filter(id => !isNaN(id));
    } else if (gameState.phase === 'shoot') {
      return gameState.shoot_activation_pool.map(id => parseInt(id)).filter(id => !isNaN(id));
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
    onStartTargetPreview: (shooterId: number | string, targetId: number | string) => {
      console.log("🔗 CALLBACK RECEIVED - onStartTargetPreview");
      handleStartTargetPreview(shooterId, targetId);
    },
    onFightAttack: () => {},
    onCharge: () => {},
    onMoveCharger: () => {},
    onCancelCharge: () => {},
    onValidateCharge: () => {},
    onLogChargeRoll: () => {},
    getChargeDestinations,
  };
};