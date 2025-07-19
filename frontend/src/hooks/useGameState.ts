// hooks/useGameState.ts

import { useState, useCallback } from 'react';
import { GameState, Unit, UnitId, PlayerId, GamePhase, GameMode, MovePreview, AttackPreview, ShootingPhaseState, TargetPreview } from '../types/game';

interface UseGameStateReturn {
  gameState: GameState;
  movePreview: MovePreview | null;
  attackPreview: AttackPreview | null;
  shootingPhaseState: ShootingPhaseState;
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
    addFledUnit: (unitId: UnitId) => void;  // NEW
    resetMovedUnits: () => void;
    resetChargedUnits: () => void;
    resetAttackedUnits: () => void;
    resetFledUnits: () => void;  // NEW
    updateUnit: (unitId: UnitId, updates: Partial<Unit>) => void;
    removeUnit: (unitId: UnitId) => void;
    initializeShootingPhase: () => void;
    initializeCombatPhase: () => void;
    updateShootingPhaseState: (updates: Partial<ShootingPhaseState>) => void;
    decrementShotsLeft: (unitId: UnitId) => void;
    setTargetPreview: (preview: TargetPreview | null) => void;
    setCurrentTurn: (turn: number) => void;
  };
}

export const useGameState = (initialUnits: Unit[]): UseGameStateReturn => {
  const [gameState, setGameState] = useState<GameState>({
    units: initialUnits.map(unit => {
      if (unit.RNG_NB === undefined) {
        throw new Error('unit.RNG_NB is required');
      }
      return {
        ...unit,
        SHOOT_LEFT: unit.RNG_NB
      };
    }),
    currentPlayer: 0,
    phase: "move",
    mode: "select",
    selectedUnitId: null,
    unitsMoved: [],
    unitsCharged: [],
    unitsAttacked: [],
    unitsFled: [],
    targetPreview: null,
    currentTurn: 1,
  });

  const [movePreview, setMovePreview] = useState<MovePreview | null>(null);
  const [attackPreview, setAttackPreview] = useState<AttackPreview | null>(null);
  const [shootingPhaseState, setShootingPhaseState] = useState<ShootingPhaseState>({
    activeShooters: [],
    currentShooter: null,
    singleShotState: null,
  });

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

  const initializeCombatPhase = useCallback(() => {
    console.log('🔧 INITIALIZING COMBAT PHASE - Setting ATTACK_LEFT for all units');
    setGameState(prev => ({
      ...prev,
      units: prev.units.map(unit => {
        if (unit.CC_NB === undefined) {
          throw new Error('unit.CC_NB is required');
        }
        console.log(`🔧 Unit ${unit.name} (${unit.id}): ATTACK_LEFT set to ${unit.CC_NB}`);
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

  const addMovedUnit = useCallback((unitId: UnitId) => {
    setGameState(prev => ({
      ...prev,
      unitsMoved: prev.unitsMoved.includes(unitId) 
        ? prev.unitsMoved 
        : [...prev.unitsMoved, unitId]
    }));
  }, []);

  const addChargedUnit = useCallback((unitId: UnitId) => {
    setGameState(prev => ({
      ...prev,
      unitsCharged: prev.unitsCharged.includes(unitId)
        ? prev.unitsCharged
        : [...prev.unitsCharged, unitId]
    }));
  }, []);

  const addAttackedUnit = useCallback((unitId: UnitId) => {
    setGameState(prev => ({
      ...prev,
      unitsAttacked: prev.unitsAttacked.includes(unitId)
        ? prev.unitsAttacked
        : [...prev.unitsAttacked, unitId]
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

  const addFledUnit = useCallback((unitId: UnitId) => {
    setGameState(prev => ({
      ...prev,
      unitsFled: prev.unitsFled.includes(unitId)
        ? prev.unitsFled
        : [...prev.unitsFled, unitId]
    }));
  }, []);

  const resetFledUnits = useCallback(() => {
    setGameState(prev => ({ ...prev, unitsFled: [] }));
  }, []);

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

  const setTargetPreview = useCallback((preview: TargetPreview | null) => {
    setGameState(prev => ({ ...prev, targetPreview: preview }));
  }, []);

  const setCurrentTurn = useCallback((turn: number) => {
    setGameState(prev => ({ ...prev, currentTurn: turn }));
  }, []);

  return {
    gameState,
    movePreview,
    attackPreview,
    shootingPhaseState,
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
      addFledUnit,  // NEW
      resetMovedUnits,
      resetChargedUnits,
      resetAttackedUnits,
      resetFledUnits,  // NEW
      updateUnit,
      removeUnit,
      initializeShootingPhase,
      initializeCombatPhase,
      updateShootingPhaseState,
      decrementShotsLeft,
      setTargetPreview,
      setCurrentTurn,
    },
  };
};