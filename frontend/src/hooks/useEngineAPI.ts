// frontend/src/hooks/useEngineAPI.ts
import { useState, useEffect, useCallback } from 'react';
import type { Unit, PlayerId } from '../types';

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
  const [selectedUnitId, setSelectedUnitId] = useState<number | null>(null);
  const [mode, setMode] = useState<"select" | "movePreview" | "attackPreview" | "chargePreview">("select");
  const [movePreview, setMovePreview] = useState<{ unitId: number; destCol: number; destRow: number } | null>(null);

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
      const response = await fetch(`${API_BASE}/game/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(action)
      });
      
      if (!response.ok) {
        throw new Error(`Action failed: ${response.status}`);
      }
      
      const data = await response.json();
      if (data.success) {
        setGameState(data.game_state);
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
    setSelectedUnitId(typeof unitId === 'string' ? parseInt(unitId) : unitId);
    setMode("select");
    setMovePreview(null);
  }, []);

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
    
    await executeAction(action);
    setMovePreview(null);
    setMode("select");
    setSelectedUnitId(null);
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
      onCombatAttack: () => {},
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
    currentPlayer: gameState.current_player as PlayerId,
    maxTurns: gameState.max_turns || (() => { throw new Error('API ERROR: Missing required max_turns field in game state'); })(),
    unitsMoved: gameState.units_moved ? gameState.units_moved.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_moved array'); })(),
    unitsCharged: gameState.units_charged ? gameState.units_charged.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_charged array'); })(),
    unitsAttacked: gameState.units_attacked ? gameState.units_attacked.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_attacked array'); })(),
    unitsFled: gameState.units_fled ? gameState.units_fled.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_fled array'); })(),
    phase: gameState.phase as "move" | "shoot" | "charge" | "combat",
    gameState: {
      episode_steps: gameState.episode_steps,
      units: convertUnits(gameState.units),
      currentPlayer: gameState.current_player as PlayerId,
      phase: gameState.phase as "move" | "shoot" | "charge" | "combat",
      mode,
      selectedUnitId,
      unitsMoved: gameState.units_moved ? gameState.units_moved.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_moved array in gameState'); })(),
      unitsCharged: gameState.units_charged ? gameState.units_charged.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_charged array in gameState'); })(),
      unitsAttacked: gameState.units_attacked ? gameState.units_attacked.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_attacked array in gameState'); })(),
      unitsFled: gameState.units_fled ? gameState.units_fled.map(id => parseInt(id)) : (() => { throw new Error('API ERROR: Missing required units_fled array in gameState'); })(),
      targetPreview: null,
      currentTurn: gameState.turn,
      maxTurns: gameState.max_turns,
      unitChargeRolls: {},
    },
    onSelectUnit: handleSelectUnit,
    onStartMovePreview: handleStartMovePreview,
    onDirectMove: handleDirectMove,
    onStartAttackPreview: () => {},
    onConfirmMove: handleConfirmMove,
    onCancelMove: handleCancelMove,
    onShoot: () => {},
    onCombatAttack: () => {},
    onCharge: () => {},
    onMoveCharger: () => {},
    onCancelCharge: () => {},
    onValidateCharge: () => {},
    onLogChargeRoll: () => {},
    getChargeDestinations,
  };
};