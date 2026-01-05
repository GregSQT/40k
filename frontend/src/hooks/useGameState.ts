// frontend/src/hooks/useGameState.ts
import React, { useState, useCallback } from 'react';
import type { GameState, Unit, UnitId, PlayerId, GamePhase, GameMode, ShootingPhaseState, TargetPreview, FightSubPhase, MovePreview, AttackPreview } from '../types/game';
import { getSelectedRangedWeapon, getSelectedMeleeWeapon } from '../utils/weaponHelpers';

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
    initializeFightPhase: () => void;
    updateShootingPhaseState: (updates: Partial<ShootingPhaseState>) => void;
    decrementShotsLeft: (unitId: UnitId) => void;
    setTargetPreview: (preview: TargetPreview | null) => void;
    setCurrentTurn: (turn: number) => void;
    setFightSubPhase: (subPhase: FightSubPhase | undefined) => void;
    setFightActivePlayer: (player: PlayerId | undefined) => void;
  };
}

export const useGameState = (initialUnits: Unit[]): UseGameStateReturn => {
  // Single source of truth - one game_state object
  const [gameState, setGameState] = useState<GameState>({
    units: [],
    currentPlayer: 1,
    phase: "command",
    mode: "select",
    selectedUnitId: null,
    currentTurn: 1,
    unitsMoved: [],
    unitsCharged: [],
    unitsAttacked: [],
    unitsFled: [],
    episode_steps: 0, // Built-in step counting
    fightSubPhase: undefined,
    fightActivePlayer: undefined,
    targetPreview: null
  });

  // React hook pattern: respond to parameter changes
  React.useEffect(() => {
    if (initialUnits.length > 0) {
      setGameState(prev => ({
        ...prev,
        units: initialUnits.map(unit => {
          // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Validate weapons arrays
          if (!unit.RNG_WEAPONS || unit.RNG_WEAPONS.length === 0) {
            // Unit must have at least one weapon type (ranged or melee)
            if (!unit.CC_WEAPONS || unit.CC_WEAPONS.length === 0) {
              throw new Error(`Unit ${unit.id} missing required weapons (must have RNG_WEAPONS or CC_WEAPONS)`);
            }
            return {
              ...unit,
              SHOOT_LEFT: 0, // No ranged weapons
              HP_CUR: unit.HP_CUR ?? unit.HP_MAX
            };
          }
          // Get NB from selected or first weapon
          const selectedWeapon = getSelectedRangedWeapon(unit) || unit.RNG_WEAPONS[0];
          return {
            ...unit,
            SHOOT_LEFT: selectedWeapon?.NB || 0,
            HP_CUR: unit.HP_CUR ?? unit.HP_MAX
          };
        })
      }));
    }
  }, [initialUnits]);

  const [movePreview, setMovePreview] = useState<MovePreview | null>(null);
  const [attackPreview, setAttackPreview] = useState<AttackPreview | null>(null);
  const [shootingPhaseState, setShootingPhaseState] = useState<ShootingPhaseState>({
    activeShooters: [],
    currentShooter: null,
    singleShotState: {
      isActive: false,
      shooterId: 0,
      targetId: null,
      currentShotNumber: 0,
      totalShots: 0,
      shotsRemaining: 0,
      isSelectingTarget: false,
      currentStep: 'target_selection',
      stepResults: {}
    }
  });
  const [chargeRollPopup] = useState<ChargeRollPopup | null>(null);

  // Update unit with UPPERCASE field validation
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

  // Initialize shooting phase with UPPERCASE field validation
  const initializeShootingPhase = useCallback(() => {
    setGameState(prev => ({
      ...prev,
      units: prev.units.map(unit => {
        // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Validate weapons arrays
        if (!unit.RNG_WEAPONS || unit.RNG_WEAPONS.length === 0) {
          // Unit must have at least one weapon type (ranged or melee)
          if (!unit.CC_WEAPONS || unit.CC_WEAPONS.length === 0) {
            throw new Error('unit must have RNG_WEAPONS or CC_WEAPONS');
          }
          return { ...unit, SHOOT_LEFT: 0 };
          }
          // Get NB from selected or first weapon
          const selectedWeapon = getSelectedRangedWeapon(unit) || unit.RNG_WEAPONS[0];
        return { ...unit, SHOOT_LEFT: selectedWeapon?.NB || 0 };
      })
    }));
  }, []);

  // Initialize fight phase with UPPERCASE field validation
  const initializeFightPhase = useCallback(() => {
    setGameState(prev => ({
      ...prev,
      units: prev.units.map(unit => {
        // Get NB from selected or first CC weapon
        const selectedWeapon = getSelectedMeleeWeapon(unit) || unit.CC_WEAPONS?.[0];
        return { ...unit, ATTACK_LEFT: selectedWeapon?.NB || 0 };
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

  const setFightSubPhase = useCallback((subPhase: FightSubPhase | undefined) => {
    setGameState(prev => ({ ...prev, fightSubPhase: subPhase }));
  }, []);

  const setFightActivePlayer = useCallback((player: PlayerId | undefined) => {
    setGameState(prev => ({ ...prev, fightActivePlayer: player }));
  }, []);

  // Tracking set management (sequential activation)
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
      initializeFightPhase,
      updateShootingPhaseState,
      decrementShotsLeft,
      setTargetPreview,
      setCurrentTurn,
      setFightSubPhase,
      setFightActivePlayer,
    },
  };
};