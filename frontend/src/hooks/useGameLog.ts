// frontend/src/hooks/useGameLog.ts
import { useCallback, useEffect, useRef, useState } from "react";
import type { GameLogEvent } from "../components/GameLog";
import type { Unit } from "../types/game";

function sanitizeGameLogMessage(message: string): string {
  return message
    .replace(/\s?\[R:[+-]?\d+\.?\d*\]/g, "")
    .replace(/\s?\[FIGHT_SUBPHASE:[^\]]+\]/g, "")
    .replace(/\s?\[FIGHT_POOLS:[^\]]+\]/g, "")
    .trim();
}

export function useGameLog(currentTurn?: number) {
  const [events, setEvents] = useState<GameLogEvent[]>([]);
  const eventIdCounter = useRef(0);

  const generateEventId = useCallback((): string => {
    eventIdCounter.current += 1;
    return `event_${eventIdCounter.current}_${Date.now()}`;
  }, []);

  const addEvent = useCallback(
    (baseEntry: Record<string, unknown>) => {
      const currentTime = new Date();

      const newEvent: GameLogEvent = {
        ...baseEntry,
        message:
          typeof baseEntry.message === "string"
            ? sanitizeGameLogMessage(baseEntry.message)
            : baseEntry.message,
        id: generateEventId(),
        timestamp: currentTime,
        turnNumber:
          currentTurn ?? (typeof baseEntry.turnNumber === "number" ? baseEntry.turnNumber : 1), // Capture live turn here
      } as GameLogEvent;

      setEvents((prevEvents) => [newEvent, ...prevEvents]);
    },
    [currentTurn, generateEventId]
  );

  const getUnitDisplayName = useCallback((unit: Unit): string => {
    if (typeof unit.DISPLAY_NAME === "string" && unit.DISPLAY_NAME.trim().length > 0) {
      return unit.DISPLAY_NAME;
    }
    if (typeof unit.name === "string" && unit.name.trim().length > 0) {
      return unit.name;
    }
    if (typeof unit.type === "string" && unit.type.trim().length > 0) {
      return unit.type;
    }
    return `Unit ${unit.id}`;
  }, []);

  // Listen for detailed backend log events
  useEffect(() => {
    const handleBackendLog = (event: CustomEvent) => {
      const logData = event.detail;

      // Use shootDetails directly if passed from fight handler,
      // otherwise build from flat fields (shooting handler format)
      let shootDetails = logData.shootDetails;
      if (!shootDetails && logData.hitRoll) {
        const saveSkipped =
          logData.saveSkipped === true && logData.saveSkipReason === "DEVASTATING_WOUNDS";
        // Build shootDetails from flat fields (shooting phase format)
        shootDetails = [
          {
            shotNumber: 1,
            attackRoll: logData.hitRoll,
            strengthRoll: logData.woundRoll,
            saveRoll: logData.saveRoll,
            saveTarget: logData.saveTarget,
            damageDealt: logData.damage,
            hitResult: logData.hitRoll ? "HIT" : "MISS",
            strengthResult: logData.woundRoll ? "SUCCESS" : "FAILED",
            saveSuccess: !saveSkipped && logData.saveRoll >= logData.saveTarget,
            targetDied: logData.target_died || false,
          },
        ];
      }

      addEvent({
        type: logData.type,
        message: logData.message, // Full detailed message from backend
        turnNumber: logData.turn, // Use backend data, but addEvent will override with live turn
        phase: logData.phase,
        player: logData.player,
        unitId: parseInt(logData.shooterId || logData.attackerId || logData.unitId, 10),
        targetId: parseInt(logData.targetId, 10),
        reward: logData.reward,
        action_name: logData.action_name,
        is_ai_action: logData.is_ai_action,
        shootDetails,
      });
    };

    window.addEventListener("backendLogEvent", handleBackendLog as EventListener);
    return () => {
      window.removeEventListener("backendLogEvent", handleBackendLog as EventListener);
    };
  }, [addEvent]);

  // GameController compatible logging functions
  const logTurnStart = useCallback(
    (turnNumber: number) => {
      addEvent({
        type: "turn_change",
        message: `Turn ${turnNumber} started`,
        turnNumber: currentTurn ?? turnNumber,
      });
    },
    [addEvent, currentTurn]
  );

  const logPhaseChange = useCallback(
    (phase: string, player: number, turnNumber: number) => {
      addEvent({
        type: "phase_change",
        message: `Player ${player} ${phase.toUpperCase()} PHASE`,
        phase: phase.toUpperCase(),
        turnNumber: currentTurn ?? turnNumber,
      });
    },
    [addEvent, currentTurn]
  );

  const logMoveAction = useCallback(
    (
      unit: Unit,
      startCol: number,
      startRow: number,
      endCol: number,
      endRow: number,
      turnNumber: number,
      player?: number
    ) => {
      addEvent({
        type: "move",
        message: `${getUnitDisplayName(unit)} MOVED from (${startCol},${startRow}) to (${endCol},${endRow})`,
        unitId: unit.id,
        turnNumber: currentTurn ?? turnNumber,
        phase: "MOVE",
        startHex: `(${startCol},${startRow})`,
        endHex: `(${endCol},${endRow})`,
        player: player ?? unit.player,
      });
    },
    [addEvent, currentTurn, getUnitDisplayName]
  );

  const logNoMoveAction = useCallback(
    (unit: Unit, turnNumber: number, player?: number) => {
      addEvent({
        type: "move",
        message: `${getUnitDisplayName(unit)} WAIT`,
        unitId: unit.id,
        turnNumber: currentTurn ?? turnNumber,
        phase: "MOVE",
        player: player ?? unit.player,
      });
    },
    [addEvent, currentTurn, getUnitDisplayName]
  );

  const logMoveCancellation = useCallback(
    (unit: Unit, turnNumber: number, player?: number) => {
      addEvent({
        type: "move_cancel",
        message: `${getUnitDisplayName(unit)} CANCELLED MOVE`,
        unitId: unit.id,
        turnNumber: currentTurn ?? turnNumber,
        phase: "MOVE",
        player: player ?? unit.player,
      });
    },
    [addEvent, currentTurn, getUnitDisplayName]
  );

  const logShootingAction = useCallback(
    (
      shooter: Unit,
      target: Unit,
      shootDetails: Array<Record<string, unknown>>,
      turnNumber: number,
      player?: number
    ) => {
      addEvent({
        type: "shoot",
        message: `${getUnitDisplayName(shooter)} shot at ${getUnitDisplayName(target)}`,
        unitId: shooter.id,
        targetId: target.id,
        turnNumber: currentTurn ?? turnNumber,
        phase: "SHOOT",
        shootDetails,
        player: player ?? shooter.player,
      });
    },
    [addEvent, currentTurn, getUnitDisplayName]
  );

  const logChargeAction = useCallback(
    (
      unit: Unit,
      target: Unit,
      startCol: number,
      startRow: number,
      endCol: number,
      endRow: number,
      turnNumber: number,
      player?: number
    ) => {
      addEvent({
        type: "charge",
        message: `${getUnitDisplayName(unit)} CHARGED ${getUnitDisplayName(target)}`,
        unitId: unit.id,
        targetId: target.id,
        turnNumber: currentTurn ?? turnNumber,
        phase: "CHARGE",
        startHex: `(${startCol}, ${startRow})`,
        endHex: `(${endCol}, ${endRow})`,
        player: player ?? unit.player,
      });
    },
    [addEvent, currentTurn, getUnitDisplayName]
  );

  const logChargeCancellation = useCallback(
    (unit: Unit, turnNumber: number, player?: number) => {
      addEvent({
        type: "charge_cancel",
        message: `${getUnitDisplayName(unit)} CANCELLED CHARGE`,
        unitId: unit.id,
        turnNumber: currentTurn ?? turnNumber,
        phase: "CHARGE",
        player: player ?? unit.player,
      });
    },
    [addEvent, currentTurn, getUnitDisplayName]
  );

  const logAdvanceAction = useCallback(
    (
      unit: Unit,
      startCol: number,
      startRow: number,
      endCol: number,
      endRow: number,
      turnNumber: number,
      player?: number
    ) => {
      addEvent({
        type: "advance",
        message: `${getUnitDisplayName(unit)} ADVANCED from (${startCol}, ${startRow}) to (${endCol}, ${endRow})`,
        unitId: unit.id,
        turnNumber: currentTurn ?? turnNumber,
        phase: "SHOOT",
        startHex: `(${startCol}, ${startRow})`,
        endHex: `(${endCol}, ${endRow})`,
        player: player ?? unit.player,
      });
    },
    [addEvent, currentTurn, getUnitDisplayName]
  );

  const logCombatAction = useCallback(
    (
      attacker: Unit,
      target: Unit,
      combatDetails: Array<Record<string, unknown>>,
      turnNumber: number,
      player?: number
    ) => {
      addEvent({
        type: "combat",
        message: `${getUnitDisplayName(attacker)} FOUGHT ${getUnitDisplayName(target)}`,
        unitId: attacker.id,
        targetId: target.id,
        turnNumber: currentTurn ?? turnNumber,
        phase: "FIGHT",
        shootDetails: combatDetails,
        player: player ?? attacker.player,
      });
    },
    [addEvent, currentTurn, getUnitDisplayName]
  );

  const logUnitDeath = useCallback(
    (unit: Unit, turnNumber: number, phase: string = "unknown", player?: number) => {
      addEvent({
        type: "death",
        message: `${getUnitDisplayName(unit)} was DESTROYED`,
        unitId: unit.id,
        turnNumber: currentTurn ?? turnNumber,
        phase,
        player: player ?? unit.player,
      });
    },
    [addEvent, currentTurn, getUnitDisplayName]
  );

  const clearLog = useCallback(() => {
    setEvents([]);
    eventIdCounter.current = 0;
  }, []);

  return {
    events,
    logTurnStart,
    logPhaseChange,
    logMoveAction,
    logNoMoveAction,
    logMoveCancellation,
    logShootingAction,
    logChargeAction,
    logChargeCancellation,
    logAdvanceAction,
    logCombatAction,
    logUnitDeath,
    clearLog,
    addEvent, // Export for custom messages (e.g., replay viewer)
  };
}
