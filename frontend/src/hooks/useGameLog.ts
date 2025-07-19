// frontend/src/hooks/useGameLog.ts
import { useState, useCallback, useRef } from 'react';
import { GameLogEvent } from '../components/GameLog';
import { Unit } from '../types/game';

export const useGameLog = () => {
  const [events, setEvents] = useState<GameLogEvent[]>([]);
  const eventIdCounter = useRef(0);

  const generateEventId = (): string => {
    eventIdCounter.current += 1;
    return `event_${eventIdCounter.current}_${Date.now()}`;
  };

  const addEvent = useCallback((event: Omit<GameLogEvent, 'id' | 'timestamp'>) => {
    const newEvent: GameLogEvent = {
      ...event,
      id: generateEventId(),
      timestamp: new Date(),
    };
    
    setEvents(prevEvents => [newEvent, ...prevEvents]);
  }, []);

  // Turn change event
  const logTurnStart = useCallback((turnNumber: number) => {
    addEvent({
      type: 'turn_change',
      message: `Start of Turn ${turnNumber}`,
      turnNumber,
    });
  }, [addEvent]);

  // Phase change event
  const logPhaseChange = useCallback((phase: string, player: number, turnNumber: number) => {
    const playerName = player === 0 ? 'Player 1' : 'Player 2';
    addEvent({
      type: 'phase_change',
      message: `Start ${playerName}'s ${phase.toUpperCase()} phase`,
      turnNumber,
      phase,
      player,
    });
  }, [addEvent]);

  // Move action
  const logMoveAction = useCallback((
    unit: Unit, 
    startCol: number, 
    startRow: number, 
    endCol: number, 
    endRow: number,
    turnNumber: number
  ) => {
    const startHex = `(${startCol}, ${startRow})`;
    const endHex = `(${endCol}, ${endRow})`;
    
    addEvent({
      type: 'move',
      message: `Unit ${unit.id} MOVED from ${startHex} to ${endHex}`,
      turnNumber,
      unitType: unit.type,
      unitId: unit.id,
      startHex,
      endHex,
      player: unit.player,
    });
  }, [addEvent]);

  // Move cancel
  const logMoveCancellation = useCallback((unit: Unit, turnNumber: number) => {
    addEvent({
      type: 'move_cancel',
      message: `Unit ${unit.name} ${unit.id} cancelled its move action`,
      turnNumber,
      unitType: unit.name,
      unitId: unit.id,
      player: unit.player,
    });
  }, [addEvent]);

  // Shooting action
  const logShootingAction = useCallback((
    shooter: Unit,
    target: Unit,
    shootDetails: GameLogEvent['shootDetails'],
    turnNumber: number
  ) => {
    addEvent({
      type: 'shoot',
      message: `Unit ${shooter.id} SHOT at unit ${target.id}`,
      turnNumber,
      unitType: shooter.type,
      unitId: shooter.id,
      targetUnitType: target.type,
      targetUnitId: target.id,
      player: shooter.player,
      shootDetails,
    });
  }, [addEvent]);

  // Charge action
  const logChargeAction = useCallback((
    unit: Unit,
    target: Unit,
    startCol: number,
    startRow: number,
    endCol: number,
    endRow: number,
    turnNumber: number
  ) => {
    const startHex = `(${startCol}, ${startRow})`;
    const endHex = `(${endCol}, ${endRow})`;
    
    addEvent({
      type: 'charge',
      message: `Unit ${unit.name} ${unit.id} CHARGED unit ${target.name} ${target.id} from ${startHex} to ${endHex}`,
      turnNumber,
      unitType: unit.name,
      unitId: unit.id,
      targetUnitType: target.name,
      targetUnitId: target.id,
      startHex,
      endHex,
      player: unit.player,
    });
  }, [addEvent]);

  // Charge cancel
  const logChargeCancellation = useCallback((unit: Unit, turnNumber: number) => {
    addEvent({
      type: 'charge_cancel',
      message: `Unit ${unit.name} ${unit.id} cancelled its charge action`,
      turnNumber,
      unitType: unit.name,
      unitId: unit.id,
      player: unit.player,
    });
  }, [addEvent]);

  // Combat action (similar to shooting but for melee)
  const logCombatAction = useCallback((
    attacker: Unit,
    target: Unit,
    combatDetails: GameLogEvent['shootDetails'], // Using same structure for combat rolls
    turnNumber: number
  ) => {
    addEvent({
      type: 'combat',
      message: `Unit ${attacker.id} FOUGHT unit ${target.id}`,
      turnNumber,
      unitType: attacker.type,
      unitId: attacker.id,
      targetUnitType: target.type,
      targetUnitId: target.id,
      player: attacker.player,
      shootDetails: combatDetails, // Reusing structure for combat rolls
    });
  }, [addEvent]);

  // Unit death
  const logUnitDeath = useCallback((unit: Unit, turnNumber: number) => {
    addEvent({
      type: 'death',
      message: `Unit ${unit.id} (${unit.type}) DIED !`,
      turnNumber,
      unitType: unit.type,
      unitId: unit.id,
      player: unit.player,
    });
  }, [addEvent]);

  // Clear all events (useful for game reset)
  const clearLog = useCallback(() => {
    setEvents([]);
    eventIdCounter.current = 0;
  }, []);

  return {
    events,
    logTurnStart,
    logPhaseChange,
    logMoveAction,
    logMoveCancellation,
    logShootingAction,
    logChargeAction,
    logChargeCancellation,
    logCombatAction,
    logUnitDeath,
    clearLog,
  };
};