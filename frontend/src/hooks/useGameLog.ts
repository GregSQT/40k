// frontend/src/hooks/useGameLog.ts
import { useState, useCallback, useRef } from 'react';
import { GameLogEvent } from '../components/GameLog';
import { Unit } from '../types/game';
import { createLogEntry, LogEntryParams } from '../../../shared/gameLogStructure';

export const useGameLog = () => {
  const [events, setEvents] = useState<GameLogEvent[]>([]);
  const eventIdCounter = useRef(0);
  const gameStartTime = useRef<Date | null>(null);

  const generateEventId = (): string => {
    eventIdCounter.current += 1;
    return `event_${eventIdCounter.current}_${Date.now()}`;
  };

  const addEvent = useCallback((baseEntry: any) => {
    const currentTime = new Date();
    
    // Set game start time on first event
    if (gameStartTime.current === null) {
      gameStartTime.current = currentTime;
    }
    
    const newEvent: GameLogEvent = {
      ...baseEntry,
      id: generateEventId(),
      timestamp: currentTime,
    };
    
    setEvents(prevEvents => [newEvent, ...prevEvents]);
  }, []);

  // Turn change event
  const logTurnStart = useCallback((turnNumber: number) => {
    const logParams: LogEntryParams = {
      type: 'turn_change',
      turnNumber
    };

    const baseEntry = createLogEntry(logParams);
    addEvent(baseEntry);
  }, [addEvent]);

  // Phase change event
  const logPhaseChange = useCallback((phase: string, player: number, turnNumber: number) => {
    const logParams: LogEntryParams = {
      type: 'phase_change',
      actingUnit: {
        id: 0,
        unitType: '',
        player: player
      },
      turnNumber,
      phase
    };

    const baseEntry = createLogEntry(logParams);
    addEvent(baseEntry);
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
    const logParams: LogEntryParams = {
      type: 'move',
      actingUnit: {
        id: unit.id,
        unitType: unit.type,
        player: unit.player,
        col: endCol,
        row: endRow
      },
      turnNumber,
      phase: 'movement',
      startHex: `(${startCol}, ${startRow})`,
      endHex: `(${endCol}, ${endRow})`
    };

    const baseEntry = createLogEntry(logParams);
    addEvent(baseEntry);
  }, [addEvent]);

  // Move cancel
  const logMoveCancellation = useCallback((unit: Unit, turnNumber: number) => {
    const logParams: LogEntryParams = {
      type: 'move_cancel',
      actingUnit: {
        id: unit.id,
        unitType: unit.name,
        player: unit.player,
        col: unit.col,
        row: unit.row
      },
      turnNumber,
      phase: 'movement'
    };

    const baseEntry = createLogEntry(logParams);
    addEvent(baseEntry);
  }, [addEvent]);

  // No move action
  const logNoMoveAction = useCallback((unit: Unit, turnNumber: number) => {
    const logParams: LogEntryParams = {
      type: 'move',
      actingUnit: {
        id: unit.id,
        unitType: unit.type,
        player: unit.player,
        col: unit.col,
        row: unit.row
      },
      turnNumber,
      phase: 'movement'
    };

    const baseEntry = createLogEntry(logParams);
    addEvent(baseEntry);
  }, [addEvent]);

  // Shooting action
  const logShootingAction = useCallback((
    shooter: Unit,
    target: Unit,
    shootDetails: GameLogEvent['shootDetails'],
    turnNumber: number
  ) => {
    const logParams: LogEntryParams = {
      type: 'shoot',
      actingUnit: {
        id: shooter.id,
        unitType: shooter.type,
        player: shooter.player,
        col: shooter.col,
        row: shooter.row
      },
      targetUnit: {
        id: target.id,
        unitType: target.type,
        player: target.player,
        col: target.col,
        row: target.row
      },
      turnNumber,
      phase: 'shooting',
      shootDetails
    };

    const baseEntry = createLogEntry(logParams);
    addEvent(baseEntry);
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
    const logParams: LogEntryParams = {
      type: 'charge',
      actingUnit: {
        id: unit.id,
        unitType: unit.name,
        player: unit.player,
        col: endCol,
        row: endRow
      },
      targetUnit: {
        id: target.id,
        unitType: target.name,
        player: target.player,
        col: target.col,
        row: target.row
      },
      turnNumber,
      phase: 'charge',
      startHex: `(${startCol}, ${startRow})`,
      endHex: `(${endCol}, ${endRow})`
    };

    const baseEntry = createLogEntry(logParams);
    addEvent(baseEntry);
  }, [addEvent]);

  // Charge cancel
  const logChargeCancellation = useCallback((unit: Unit, turnNumber: number) => {
    const logParams: LogEntryParams = {
      type: 'charge_cancel',
      actingUnit: {
        id: unit.id,
        unitType: unit.name,
        player: unit.player,
        col: unit.col,
        row: unit.row
      },
      turnNumber,
      phase: 'charge'
    };

    const baseEntry = createLogEntry(logParams);
    addEvent(baseEntry);
  }, [addEvent]);

  // Combat action (similar to shooting but for melee)
  const logCombatAction = useCallback((
    attacker: Unit,
    target: Unit,
    combatDetails: GameLogEvent['shootDetails'], // Using same structure for combat rolls
    turnNumber: number
  ) => {
    const logParams: LogEntryParams = {
      type: 'combat',
      actingUnit: {
        id: attacker.id,
        unitType: attacker.type,
        player: attacker.player,
        col: attacker.col,
        row: attacker.row
      },
      targetUnit: {
        id: target.id,
        unitType: target.type,
        player: target.player,
        col: target.col,
        row: target.row
      },
      turnNumber,
      phase: 'combat',
      shootDetails: combatDetails
    };

    const baseEntry = createLogEntry(logParams);
    addEvent(baseEntry);
  }, [addEvent]);

  // Unit death
  const logUnitDeath = useCallback((unit: Unit, turnNumber: number, phase: string = 'unknown') => {
    const logParams: LogEntryParams = {
      type: 'death',
      targetUnit: {
        id: unit.id,
        unitType: unit.type,
        player: unit.player,
        col: unit.col,
        row: unit.row
      },
      turnNumber,
      phase
    };

    const baseEntry = createLogEntry(logParams);
    addEvent(baseEntry);
  }, [addEvent]);

  // Clear all events (useful for game reset)
  const clearLog = useCallback(() => {
    setEvents([]);
    eventIdCounter.current = 0;
  }, []);

  // Calculate elapsed time from game start
  const getElapsedTime = useCallback((timestamp: Date): string => {
    if (gameStartTime.current === null) {
      return '00:00:00';
    }
    
    const elapsedMs = timestamp.getTime() - gameStartTime.current.getTime();
    const elapsedSeconds = Math.floor(elapsedMs / 1000);
    
    const hours = Math.floor(elapsedSeconds / 3600);
    const minutes = Math.floor((elapsedSeconds % 3600) / 60);
    const seconds = elapsedSeconds % 60;
    
    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
  }, []);

  return {
    events,
    getElapsedTime,
    logTurnStart,
    logPhaseChange,
    logMoveAction,
    logNoMoveAction,
    logMoveCancellation,
    logShootingAction,
    logChargeAction,
    logChargeCancellation,
    logCombatAction,
    logUnitDeath,
    clearLog,
  };
};