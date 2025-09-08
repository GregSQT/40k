// frontend/src/hooks/useGameState.ts
import { useState, useCallback } from 'react';
import type { GameState, Unit, UnitId, PlayerId, GamePhase, GameMode, ShootingPhaseState, TargetPreview, CombatSubPhase } from '../types/game';

// AI_TURN.md: Define missing preview types locally
interface MovePreview {
  unitId: UnitId;
  col: number;
  row: number;
}

interface AttackPreview {
  unitId: UnitId;
  col: number;
  row: number;
}

interface ChargeRollPopup {
  unitId: UnitId;
  roll: number;
  tooLow: boolean;
  timestamp: number;
}

interface UseGameStateReturn {
  gameState: GameState;
  movePreview: MovePreview | null;
  attackPreview: AttackPreview | null;
  shootingPhaseState: ShootingPhaseState;
  chargeRollPopup: ChargeRollPopup | null;
  actions: {
    setUnits: (units: Unit[]) => void;
    setCurrentPlayer: (player: PlayerId) => void;
    setPhase: (phase: GamePhase) => void;
    setMode: (mode: GameMode) => void;
    setSelectedUnitId: (id: UnitId | null) => void;
    setMovePreview: (preview: MovePreview | null) => void;
    setAttackPreview: (preview: AttackPreview | null) => void;
    addMovedUnit: (unitId: UnitId) => void;
    addChargedUnit: (unitId: UnitId) => void;
    addAttackedUnit: (unitId: UnitId) => void;
    addFledUnit: (unitId: UnitId) => void;
    resetMovedUnits: () => void;
    resetChargedUnits: () => void;
    resetAttackedUnits: () => void;
    resetFledUnits: () => void;
    updateUnit: (unitId: UnitId, updates: Partial<Unit>) => void;
    removeUnit: (unitId: UnitId) => void;
    initializeShootingPhase: () => void;
    initializeCombatPhase: () => void;
    updateShootingPhaseState: (updates: Partial<ShootingPhaseState>) => void;
    decrementShotsLeft: (unitId: UnitId) => void;
    setTargetPreview: (preview: TargetPreview | null) => void;
    setCurrentTurn: (turn: number) => void;
    setCombatSubPhase: (subPhase: CombatSubPhase | undefined) => void;
    setCombatActivePlayer: (player: PlayerId | undefined) => void;
  };
}

export const useGameState = (initialUnits: Unit[]): UseGameStateReturn => {
  // AI_TURN.md: Single source of truth - one game_state object
  const [gameState, setGameState] = useState<GameState>({
    units: initialUnits,
    currentPlayer: 0,
    phase: "move",
    mode: "select",
    selectedUnitId: null,
    currentTurn: 1,
    unitsMoved: [],
    unitsCharged: [],
    unitsAttacked: [],
    unitsFled: [],
    episode_steps: 0, // AI_TURN.md: Built-in step counting
    combatSubPhase: undefined,
    combatActivePlayer: undefined,
    targetPreview: null
  });

  const [movePreview, setMovePreview] = useState<MovePreview | null>(null);
  const [attackPreview, setAttackPreview] = useState<AttackPreview | null>(null);
  const [shootingPhaseState, setShootingPhaseState] = useState<ShootingPhaseState>({
    activeShooters: [],
    currentShooter: null,
    singleShotState: {
      isActive: false,
      targetId: null,
      shotNumber: 0,
      totalShots: 0
    }
  });
  const [chargeRollPopup, setChargeRollPopup] = useState<ChargeRollPopup | null>(null);

  // AI_TURN.md: Update unit with UPPERCASE field validation
  const updateUnit = useCallback((unitId: UnitId, updates: Partial<Unit>) => {
    setGameState(prev => ({
      ...prev,
      units: prev.units.map(unit => 
        unit.id === unitId ? { ...unit, ...updates } : unit
      )
    }));
  }, []);

  const removeUnit = useCallback((unitId: UnitId) => {
    setGameState(prev => ({
      ...prev,
      units: prev.units.filter(unit => unit.id !== unitId)
    }));
  }, []);

  // AI_TURN.md: Initialize shooting phase with UPPERCASE field validation
  const initializeShootingPhase = useCallback(() => {
    setGameState(prev => ({
      ...prev,
      units: prev.units.map(unit => {
        if (unit.RNG_NB === undefined) {
          throw new Error('unit.RNG_NB is required');
        }
        return { ...unit, SHOOT_LEFT: unit.RNG_NB };
      })
    }));
  }, []);

  // AI_TURN.md: Initialize combat phase with UPPERCASE field validation
  const initializeCombatPhase = useCallback(() => {
    setGameState(prev => ({
      ...prev,
      units: prev.units.map(unit => {
        if (unit.CC_NB === undefined) {
          throw new Error('unit.CC_NB is required');
        }
        return { ...unit, ATTACK_LEFT: unit.CC_NB };
      })
    }));
  }, []);

  const updateShootingPhaseState = useCallback((updates: Partial<ShootingPhaseState>) => {
    setShootingPhaseState(prev => ({ ...prev, ...updates }));
  }, []);

  const decrementShotsLeft = useCallback((unitId: UnitId) => {
    setGameState(prev => ({
      ...prev,
      units: prev.units.map(unit => {
        if (unit.id === unitId) {
          if (unit.SHOOT_LEFT === undefined) {
            throw new Error('unit.SHOOT_LEFT is required');
          }
          return { ...unit, SHOOT_LEFT: Math.max(0, unit.SHOOT_LEFT - 1) };
        }
        return unit;
      })
    }));
  }, []);

  // Core state setters
  const setUnits = useCallback((units: Unit[]) => {
    setGameState(prev => ({ ...prev, units }));
  }, []);

  const setCurrentPlayer = useCallback((player: PlayerId) => {
    setGameState(prev => ({ ...prev, currentPlayer: player }));
  }, []);

  const setPhase = useCallback((phase: GamePhase) => {
    setGameState(prev => ({ ...prev, phase }));
  }, []);

  const setMode = useCallback((mode: GameMode) => {
    setGameState(prev => ({ ...prev, mode }));
  }, []);

  const setSelectedUnitId = useCallback((id: UnitId | null) => {
    setGameState(prev => ({ ...prev, selectedUnitId: id }));
  }, []);

  const setTargetPreview = useCallback((preview: TargetPreview | null) => {
    setGameState(prev => ({ ...prev, targetPreview: preview }));
  }, []);

  const setCurrentTurn = useCallback((turn: number) => {
    setGameState(prev => ({ ...prev, currentTurn: turn }));
  }, []);

  const setCombatSubPhase = useCallback((subPhase: CombatSubPhase | undefined) => {
    setGameState(prev => ({ ...prev, combatSubPhase: subPhase }));
  }, []);

  const setCombatActivePlayer = useCallback((player: PlayerId | undefined) => {
    setGameState(prev => ({ ...prev, combatActivePlayer: player }));
  }, []);

  // AI_TURN.md: Tracking set management (sequential activation)
  const addMovedUnit = useCallback((unitId: UnitId) => {
    setGameState(prev => ({
      ...prev,
      unitsMoved: (prev.unitsMoved ?? []).includes(unitId) 
        ? (prev.unitsMoved ?? [])
        : [...(prev.unitsMoved ?? []), unitId]
    }));
  }, []);

  const addChargedUnit = useCallback((unitId: UnitId) => {
    setGameState(prev => ({
      ...prev,
      unitsCharged: (prev.unitsCharged ?? []).includes(unitId)
        ? (prev.unitsCharged ?? [])
        : [...(prev.unitsCharged ?? []), unitId]
    }));
  }, []);

  const addAttackedUnit = useCallback((unitId: UnitId) => {
    setGameState(prev => ({
      ...prev,
      unitsAttacked: (prev.unitsAttacked ?? []).includes(unitId)
        ? (prev.unitsAttacked ?? [])
        : [...(prev.unitsAttacked ?? []), unitId]
    }));
  }, []);

  const addFledUnit = useCallback((unitId: UnitId) => {
    setGameState(prev => ({
      ...prev,
      unitsFled: (prev.unitsFled ?? []).includes(unitId)
        ? (prev.unitsFled ?? [])
        : [...(prev.unitsFled ?? []), unitId]
    }));
  }, []);

  const resetMovedUnits = useCallback(() => {
    setGameState(prev => ({ ...prev, unitsMoved: [] }));
  }, []);

  const resetChargedUnits = useCallback(() => {
    setGameState(prev => ({ ...prev, unitsCharged: [] }));
  }, []);

  const resetAttackedUnits = useCallback(() => {
    setGameState(prev => ({ ...prev, unitsAttacked: [] }));
  }, []);

  const resetFledUnits = useCallback(() => {
    setGameState(prev => ({ ...prev, unitsFled: [] }));
  }, []);

  return {
    gameState,
    movePreview,
    attackPreview,
    shootingPhaseState,
    chargeRollPopup,
    actions: {
      setUnits,
      setCurrentPlayer,
      setPhase,
      setMode,
      setSelectedUnitId,
      setMovePreview,
      setAttackPreview,
      addMovedUnit,
      addChargedUnit,
      addAttackedUnit,
      addFledUnit,
      resetMovedUnits,
      resetChargedUnits,
      resetAttackedUnits,
      resetFledUnits,
      updateUnit,
      removeUnit,
      initializeShootingPhase,
      initializeCombatPhase,
      updateShootingPhaseState,
      decrementShotsLeft,
      setTargetPreview,
      setCurrentTurn,
      setCombatSubPhase,
      setCombatActivePlayer,
    },
  };
};