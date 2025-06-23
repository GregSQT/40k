// hooks/useGameState.ts
import { useState, useCallback } from 'react';
import { GameState, Unit, UnitId, PlayerId, GamePhase, GameMode, MovePreview, AttackPreview } from '../types/game';

interface UseGameStateReturn {
  gameState: GameState;
  movePreview: MovePreview | null;
  attackPreview: AttackPreview | null;
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
    resetMovedUnits: () => void;
    resetChargedUnits: () => void;
    resetAttackedUnits: () => void;
    updateUnit: (unitId: UnitId, updates: Partial<Unit>) => void;
    removeUnit: (unitId: UnitId) => void;
  };
}

export const useGameState = (initialUnits: Unit[]): UseGameStateReturn => {
  const [gameState, setGameState] = useState<GameState>({
    units: initialUnits,
    currentPlayer: 0,
    phase: "move",
    mode: "select",
    selectedUnitId: null,
    unitsMoved: [],
    unitsCharged: [],
    unitsAttacked: [],
  });

  const [movePreview, setMovePreview] = useState<MovePreview | null>(null);
  const [attackPreview, setAttackPreview] = useState<AttackPreview | null>(null);

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

  return {
    gameState,
    movePreview,
    attackPreview,
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
      resetMovedUnits,
      resetChargedUnits,
      resetAttackedUnits,
      updateUnit,
      removeUnit,
    },
  };
};