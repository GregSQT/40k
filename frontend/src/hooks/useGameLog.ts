// frontend/src/hooks/useGameLog.ts
import { useState, useCallback, useRef } from 'react';
import type { Unit } from '../types/game';

// AI_TURN.md compliant interface matching GameController expectations
export interface GameLogEvent {
  id: string;
  timestamp: Date;
  type: string;
  message: string;
  unitId?: number;
  targetId?: number;
  phase?: string;
  turnNumber?: number;
  startHex?: string;
  endHex?: string;
  shootDetails?: any;
}

export function useGameLog() {
  const [events, setEvents] = useState<GameLogEvent[]>([]);
  const eventIdCounter = useRef(0);
  const gameStartTime = useRef<Date | null>(null);

  const generateEventId = (): string => {
    eventIdCounter.current += 1;
    return `event_${eventIdCounter.current}_${Date.now()}`;
  };

  const addEvent = useCallback((baseEntry: any) => {
    const currentTime = new Date();
    
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

  // GameController compatible logging functions
  const logTurnStart = useCallback((turnNumber: number) => {
    addEvent({
      type: 'turn_change',
      message: `Turn ${turnNumber} started`,
      turnNumber
    });
  }, [addEvent]);

  const logPhaseChange = useCallback((phase: string, player: number, turnNumber: number) => {
    addEvent({
      type: 'phase_change',
      message: `Player ${player} ${phase} phase`,
      phase,
      turnNumber
    });
  }, [addEvent]);

  const logMoveAction = useCallback((
    unit: Unit, 
    startCol: number, 
    startRow: number, 
    endCol: number, 
    endRow: number,
    turnNumber: number
  ) => {
    addEvent({
      type: 'move',
      message: `${unit.name} moved from (${startCol}, ${startRow}) to (${endCol}, ${endRow})`,
      unitId: unit.id,
      turnNumber,
      phase: 'movement',
      startHex: `(${startCol}, ${startRow})`,
      endHex: `(${endCol}, ${endRow})`
    });
  }, [addEvent]);

  const logNoMoveAction = useCallback((unit: Unit, turnNumber: number) => {
    addEvent({
      type: 'move',
      message: `${unit.name} chose not to move`,
      unitId: unit.id,
      turnNumber,
      phase: 'movement'
    });
  }, [addEvent]);

  const logMoveCancellation = useCallback((unit: Unit, turnNumber: number) => {
    addEvent({
      type: 'move_cancel',
      message: `${unit.name} movement cancelled`,
      unitId: unit.id,
      turnNumber,
      phase: 'movement'
    });
  }, [addEvent]);

  const logShootingAction = useCallback((
    shooter: Unit,
    target: Unit,
    shootDetails: any,
    turnNumber: number
  ) => {
    addEvent({
      type: 'shoot',
      message: `${shooter.name} shot at ${target.name}`,
      unitId: shooter.id,
      targetId: target.id,
      turnNumber,
      phase: 'shooting',
      shootDetails
    });
  }, [addEvent]);

  const logChargeAction = useCallback((
    unit: Unit,
    target: Unit,
    startCol: number,
    startRow: number,
    endCol: number,
    endRow: number,
    turnNumber: number
  ) => {
    addEvent({
      type: 'charge',
      message: `${unit.name} charged ${target.name}`,
      unitId: unit.id,
      targetId: target.id,
      turnNumber,
      phase: 'charge',
      startHex: `(${startCol}, ${startRow})`,
      endHex: `(${endCol}, ${endRow})`
    });
  }, [addEvent]);

  const logChargeCancellation = useCallback((unit: Unit, turnNumber: number) => {
    addEvent({
      type: 'charge_cancel',
      message: `${unit.name} charge cancelled`,
      unitId: unit.id,
      turnNumber,
      phase: 'charge'
    });
  }, [addEvent]);

  const logCombatAction = useCallback((
    attacker: Unit,
    target: Unit,
    combatDetails: any,
    turnNumber: number
  ) => {
    addEvent({
      type: 'fight',
      message: `${attacker.name} attacked ${target.name} in fight`,
      unitId: attacker.id,
      targetId: target.id,
      turnNumber,
      phase: 'fight',
      shootDetails: combatDetails
    });
  }, [addEvent]);

  const logUnitDeath = useCallback((unit: Unit, turnNumber: number, phase: string = 'unknown') => {
    addEvent({
      type: 'death',
      message: `${unit.name} was destroyed`,
      unitId: unit.id,
      turnNumber,
      phase
    });
  }, [addEvent]);

  const clearLog = useCallback(() => {
    setEvents([]);
    eventIdCounter.current = 0;
    gameStartTime.current = null;
  }, []);

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
}