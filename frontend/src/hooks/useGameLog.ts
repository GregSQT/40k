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

/**
 * Construit l'entrée de base d'un event de Game Log (avant id/timestamp finalisés) à partir d'un
 * payload backend. Source de vérité UNIQUE partagée par le flux live (``backendLogEvent``) et par la
 * réhydratation du replay (``game_log_history``). Gère les alias camel/snake et la reconstruction de
 * ``shootDetails`` depuis les champs plats (phase tir) ou depuis ``shootDetails`` (phase fight).
 */
function baseEntryFromLogData(logData: Record<string, unknown>): Record<string, unknown> {
  const details = logData.shootDetails;
  const shot =
    Array.isArray(details) && details.length > 0
      ? (details[0] as Record<string, unknown>)
      : undefined;
  const hitRoll = logData.hitRoll ?? logData.hit_roll ?? shot?.attackRoll;
  const woundRoll = logData.woundRoll ?? logData.wound_roll ?? shot?.strengthRoll;
  const saveRoll = logData.saveRoll ?? logData.save_roll ?? shot?.saveRoll;
  const saveTarget = logData.saveTarget ?? logData.save_target ?? shot?.saveTarget;
  const damage = logData.damage ?? shot?.damageDealt;
  const targetDied = logData.target_died ?? shot?.targetDied ?? false;

  let shootDetails = details;
  if (!shootDetails && hitRoll) {
    const saveSkipped =
      (logData.saveSkipped ?? logData.save_skipped) === true &&
      (logData.saveSkipReason ?? logData.save_skip_reason) === "DEVASTATING_WOUNDS";
    // Build shootDetails from flat fields (shooting phase format)
    shootDetails = [
      {
        shotNumber: 1,
        attackRoll: hitRoll,
        strengthRoll: woundRoll,
        saveRoll,
        saveTarget,
        damageDealt: damage,
        hitResult: hitRoll ? "HIT" : "MISS",
        strengthResult: woundRoll ? "SUCCESS" : "FAILED",
        saveSuccess: !saveSkipped && Number(saveRoll) >= Number(saveTarget),
        targetDied,
      },
    ];
  }

  const idOf = (v: unknown): number => parseInt(String(v ?? ""), 10);
  return {
    type: logData.type,
    message: logData.message, // Full detailed message from backend
    turnNumber: logData.turn,
    phase: logData.phase,
    player: logData.player,
    unitId: idOf(logData.shooterId || logData.attackerId || logData.unitId),
    targetId: idOf(logData.targetId),
    reward: logData.reward,
    action_name: logData.action_name,
    is_ai_action: logData.is_ai_action,
    result: logData.result,
    weaponName: logData.weaponName,
    targetUnitType: logData.targetUnitType,
    shootDetails,
    moveDetails: logData.moveDetails,
    hazardDetails: logData.hazardDetails,
  };
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

  // Réhydrate le Game Log depuis l'historique complet d'une partie/point chargé (replay). Remplace
  // intégralement les events par ceux du backend (game_log_history). L'ordre chronologique est porté
  // par ``logSeq`` (timestamp dérivé) — GameLog trie par timestamp décroissant (plus récent en haut).
  const hydrateFromHistory = useCallback((entries: Array<Record<string, unknown>>) => {
    if (!Array.isArray(entries)) return;
    eventIdCounter.current = 0;
    const rebuilt = entries.map((entry, index) => {
      const base = baseEntryFromLogData(entry);
      const seq = typeof entry.logSeq === "number" ? entry.logSeq : index + 1;
      return {
        ...base,
        message:
          typeof base.message === "string" ? sanitizeGameLogMessage(base.message) : base.message,
        id: `hydrate_${seq}`,
        timestamp: new Date(seq),
        turnNumber: typeof base.turnNumber === "number" ? base.turnNumber : 1,
      } as GameLogEvent;
    });
    setEvents(rebuilt);
  }, []);

  // Réhydratation déclenchée par le hook API (Load / rewind / retour live) via un event window,
  // même canal que ``backendLogEvent`` pour le flux live → pas de threading de props.
  useEffect(() => {
    const handleHydrate = (event: CustomEvent) => {
      const entries = (event.detail?.entries ?? []) as Array<Record<string, unknown>>;
      hydrateFromHistory(entries);
    };
    window.addEventListener("gameLogHydrate", handleHydrate as EventListener);
    return () => {
      window.removeEventListener("gameLogHydrate", handleHydrate as EventListener);
    };
  }, [hydrateFromHistory]);

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
      // addEvent finalise id/timestamp et surcharge turnNumber avec le tour live courant.
      addEvent(baseEntryFromLogData((event.detail ?? {}) as Record<string, unknown>));
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
    hydrateFromHistory,
    addEvent, // Export for custom messages (e.g., replay viewer)
  };
}
