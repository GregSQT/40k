// frontend/src/hooks/useGameLog.ts
import { useState, useCallback, useRef, useEffect } from 'react';
import type { Unit } from '../types/game';

import type { GameLogEvent } from '../components/GameLog';

export function useGameLog(currentTurn?: number) {
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
      turnNumber: currentTurn ?? baseEntry.turnNumber ?? 1,  // Capture live turn here
    };
    
    setEvents(prevEvents => [newEvent, ...prevEvents]);
  }, [currentTurn]);

  // Listen for detailed backend log events
  useEffect(() => {
    const handleBackendLog = (event: CustomEvent) => {
      const logData = event.detail;

      // AI_TURN.md: Use shootDetails directly if passed from fight handler,
      // otherwise build from flat fields (shooting handler format)
      let shootDetails = logData.shootDetails;
      if (!shootDetails && logData.hitRoll) {
        // Build shootDetails from flat fields (shooting phase format)
        shootDetails = [{
          shotNumber: 1,
          attackRoll: logData.hitRoll,
          strengthRoll: logData.woundRoll,
          saveRoll: logData.saveRoll,
          saveTarget: logData.saveTarget,
          damageDealt: logData.damage,
          hitResult: logData.hitRoll ? 'HIT' : 'MISS',
          strengthResult: logData.woundRoll ? 'SUCCESS' : 'FAILED',
          saveSuccess: logData.saveRoll >= logData.saveTarget,
          targetDied: logData.target_died || false
        }];
      }

      addEvent({
        type: logData.type,
        message: logData.message,  // Full detailed message from backend
        turnNumber: logData.turn,  // Use backend data, but addEvent will override with live turn
        phase: logData.phase,
        player: logData.player,
        unitId: parseInt(logData.shooterId),
        targetId: parseInt(logData.targetId),
        reward: logData.reward,
        action_name: logData.action_name,
        is_ai_action: logData.is_ai_action,
        shootDetails
      });
    };

    window.addEventListener('backendLogEvent', handleBackendLog as EventListener);
    return () => {
      window.removeEventListener('backendLogEvent', handleBackendLog as EventListener);
    };
  }, [addEvent]);

  // GameController compatible logging functions
  const logTurnStart = useCallback((turnNumber: number) => {
    addEvent({
      type: 'turn_change',
      message: `Turn ${turnNumber} started`,
      turnNumber: currentTurn ?? turnNumber
    });
  }, [addEvent, currentTurn]);

  const logPhaseChange = useCallback((phase: string, player: number, turnNumber: number) => {
    addEvent({
      type: 'phase_change',
      message: `Player ${player} ${phase} phase`,
      phase,
      turnNumber: currentTurn ?? turnNumber
    });
  }, [addEvent, currentTurn]);

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
      turnNumber: currentTurn ?? turnNumber,
      phase: 'movement',
      startHex: `(${startCol}, ${startRow})`,
      endHex: `(${endCol}, ${endRow})`
    });
  }, [addEvent, currentTurn]);

  const logNoMoveAction = useCallback((unit: Unit, turnNumber: number) => {
    addEvent({
      type: 'move',
      message: `${unit.name} chose not to move`,
      unitId: unit.id,
      turnNumber: currentTurn ?? turnNumber,
      phase: 'movement'
    });
  }, [addEvent, currentTurn]);

  const logMoveCancellation = useCallback((unit: Unit, turnNumber: number) => {
    addEvent({
      type: 'move_cancel',
      message: `${unit.name} movement cancelled`,
      unitId: unit.id,
      turnNumber: currentTurn ?? turnNumber,
      phase: 'movement'
    });
  }, [addEvent, currentTurn]);

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
      turnNumber: currentTurn ?? turnNumber,
      phase: 'shooting',
      shootDetails
    });
  }, [addEvent, currentTurn]);

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
      turnNumber: currentTurn ?? turnNumber,
      phase: 'charge',
      startHex: `(${startCol}, ${startRow})`,
      endHex: `(${endCol}, ${endRow})`
    });
  }, [addEvent, currentTurn]);

  const logChargeCancellation = useCallback((unit: Unit, turnNumber: number) => {
    addEvent({
      type: 'charge_cancel',
      message: `${unit.name} charge cancelled`,
      unitId: unit.id,
      turnNumber: currentTurn ?? turnNumber,
      phase: 'charge'
    });
  }, [addEvent, currentTurn]);

  const logCombatAction = useCallback((
    attacker: Unit,
    target: Unit,
    combatDetails: any,
    turnNumber: number
  ) => {
    addEvent({
      type: 'combat',
      message: `${attacker.name} attacked ${target.name} in combat`,
      unitId: attacker.id,
      targetId: target.id,
      turnNumber: currentTurn ?? turnNumber,
      phase: 'combat',
      shootDetails: combatDetails
    });
  }, [addEvent, currentTurn]);

  const logUnitDeath = useCallback((unit: Unit, turnNumber: number, phase: string = 'unknown') => {
    addEvent({
      type: 'death',
      message: `${unit.name} was destroyed`,
      unitId: unit.id,
      turnNumber: currentTurn ?? turnNumber,
      phase
    });
  }, [addEvent, currentTurn]);

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
    addEvent,  // Export for custom messages (e.g., replay viewer)
  };
}