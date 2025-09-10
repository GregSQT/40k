// shared/gameLogStructure.ts
// Unified game log structure for both PvP and Replay systems
// Based on replay log format as the standard

/**
 * Base log entry interface - used by both PvP and Replay
 * This matches the replay log format exactly
 */
import { formatMoveMessage, formatShootingMessage, formatCombatMessage, formatChargeMessage, formatDeathMessage, formatMoveCancelMessage, formatChargeCancelMessage, formatTurnStartMessage, formatPhaseChangeMessage } from './gameLogUtils';

export interface BaseLogEntry {
  type: 'move' | 'shoot' | 'combat' | 'charge' | 'death' | 'turn_change' | 'phase_change' | 'move_cancel' | 'charge_cancel';
  message: string;
  turnNumber?: number;
  phase?: string;
  unitType?: string;
  unitId?: number;
  targetUnitType?: string;
  targetUnitId?: number;
  player?: number;
  startHex?: string;
  endHex?: string;
  shootDetails?: ShootDetail[];
}

/**
 * Training-enhanced log entry - extends base with training-specific data
 * Only used by replay/training systems
 */
export interface TrainingLogEntry extends BaseLogEntry {
  reward?: number;
  actionName?: string;
  timestamp?: string;
  id?: string; // For frontend display compatibility
}

/**
 * Shooting detail structure (matches current replay format)
 */
export interface ShootDetail {
  shotNumber: number;
  attackRoll: number;
  strengthRoll: number;
  hitResult: 'HIT' | 'MISS';
  strengthResult: 'SUCCESS' | 'FAILED';
  hitTarget?: number;
  woundTarget?: number;
  saveTarget?: number;
  saveRoll?: number;
  saveSuccess?: boolean;
  damageDealt?: number;
}

/**
 * Parameters for creating log entries
 */
export interface LogEntryParams {
  type: BaseLogEntry['type'];
  actingUnit?: {
    id: number;
    unitType: string;
    player: number;
    col?: number;
    row?: number;
  };
  targetUnit?: {
    id: number;
    unitType: string;
    player: number;
    col?: number;
    row?: number;
  };
  turnNumber?: number;
  phase?: string;
  startHex?: string;
  endHex?: string;
  shootDetails?: ShootDetail[];
  // Training-only fields
  reward?: number;
  actionName?: string;
}

/**
 * Create standardized log entry using replay format as standard
 * This function ensures both PvP and replay generate identical base structure
 */
export function createLogEntry(params: LogEntryParams): BaseLogEntry {
  const {
    type,
    actingUnit,
    targetUnit,
    turnNumber,
    phase,
    startHex,
    endHex,
    shootDetails
  } = params;

  // Use shared message formatting functions for consistency
  const messageFormatters = {
    shoot: formatShootingMessage,
    move: (unitId: number, startHex: string, endHex: string) => {
      // Parse coordinates from hex strings like "(25, 12)"
      try {
        const startMatch = startHex.match(/\((\d+),\s*(\d+)\)/);
        const endMatch = endHex.match(/\((\d+),\s*(\d+)\)/);
        if (startMatch && endMatch) {
          const startCol = parseInt(startMatch[1]);
          const startRow = parseInt(startMatch[2]);
          const endCol = parseInt(endMatch[1]);
          const endRow = parseInt(endMatch[2]);
          return formatMoveMessage(unitId, startCol, startRow, endCol, endRow);
        }
      } catch (error) {
        // Fallback to original format if parsing fails
      }
      return `Unit ${unitId} MOVED from ${startHex} to ${endHex}`;
    },
    combat: formatCombatMessage,
    charge: (unitName: string, unitId: number, targetName: string, targetId: number, startHex: string, endHex: string) => {
      // Parse coordinates for charge messages too
      try {
        const startMatch = startHex.match(/\((\d+),\s*(\d+)\)/);
        const endMatch = endHex.match(/\((\d+),\s*(\d+)\)/);
        if (startMatch && endMatch) {
          const startCol = parseInt(startMatch[1]);
          const startRow = parseInt(startMatch[2]);
          const endCol = parseInt(endMatch[1]);
          const endRow = parseInt(endMatch[2]);
          return formatChargeMessage(unitName, unitId, targetName, targetId, startCol, startRow, endCol, endRow);
        }
      } catch (error) {
        // Fallback to original format if parsing fails
      }
      return `Unit ${unitName} ${unitId} CHARGED unit ${targetName} ${targetId} from ${startHex} to ${endHex}`;
    },
    death: formatDeathMessage,
    move_cancel: formatMoveCancelMessage,
    charge_cancel: formatChargeCancelMessage,
    turn_change: formatTurnStartMessage,
    phase_change: formatPhaseChangeMessage
  };

  // Generate message based on type
  let message = '';
  switch (type) {
    case 'shoot':
      message = messageFormatters.shoot(actingUnit?.id || 0, targetUnit?.id || 0);
      break;
    case 'move':
      message = messageFormatters.move(actingUnit?.id || 0, startHex || '', endHex || '');
      break;
    case 'combat':
      message = messageFormatters.combat(actingUnit?.id || 0, targetUnit?.id || 0);
      break;
    case 'charge':
      message = messageFormatters.charge(
        actingUnit?.unitType || 'unknown',
        actingUnit?.id || 0,
        targetUnit?.unitType || 'unknown', 
        targetUnit?.id || 0,
        startHex || '',
        endHex || ''
      );
      break;
    case 'death':
      message = messageFormatters.death(targetUnit?.id || actingUnit?.id || 0, targetUnit?.unitType || actingUnit?.unitType || 'unknown');
      break;
    case 'move_cancel':
      message = messageFormatters.move_cancel(actingUnit?.unitType || 'unknown', actingUnit?.id || 0);
      break;
    case 'charge_cancel':
      message = messageFormatters.charge_cancel(actingUnit?.unitType || 'unknown', actingUnit?.id || 0);
      break;
    case 'turn_change':
      message = messageFormatters.turn_change(turnNumber || 1);
      break;
    case 'phase_change':
      const playerName = actingUnit?.player === 0 ? 'Player 1' : 'Player 2';
      message = messageFormatters.phase_change(playerName, phase || 'unknown');
      break;
    default:
      message = `Unknown action: ${type}`;
  }

  // Build base log entry (replay format structure)
  const logEntry: BaseLogEntry = {
    type,
    message,
    turnNumber,
    phase,
    unitType: actingUnit?.unitType,
    unitId: actingUnit?.id,
    targetUnitType: targetUnit?.unitType,
    targetUnitId: targetUnit?.id,
    player: actingUnit?.player,
    startHex,
    endHex,
    shootDetails
  };

  // Remove undefined fields to keep JSON clean
  Object.keys(logEntry).forEach(key => {
    if (logEntry[key as keyof BaseLogEntry] === undefined) {
      delete logEntry[key as keyof BaseLogEntry];
    }
  });

  return logEntry;
}

/**
 * Create training-enhanced log entry (for replay systems only)
 */
export function createTrainingLogEntry(params: LogEntryParams): TrainingLogEntry {
  const baseEntry = createLogEntry(params);
  
  const trainingEntry: TrainingLogEntry = {
    ...baseEntry,
    reward: params.reward,
    actionName: params.actionName,
    timestamp: new Date().toISOString(),
    id: `${Date.now()}_${Math.random().toString(36).substr(2, 9)}` // Unique ID for frontend
  };

  // Remove undefined training fields
  Object.keys(trainingEntry).forEach(key => {
    if (trainingEntry[key as keyof TrainingLogEntry] === undefined) {
      delete trainingEntry[key as keyof TrainingLogEntry];
    }
  });

  return trainingEntry;
}

/**
 * Convert legacy PvP GameLogEvent to new standardized format
 */
export function convertLegacyPvPEvent(legacyEvent: any): BaseLogEntry {
  return {
    type: legacyEvent.type,
    message: legacyEvent.message,
    turnNumber: legacyEvent.turnNumber,
    phase: legacyEvent.phase,
    unitType: legacyEvent.unitType,
    unitId: legacyEvent.unitId,
    targetUnitType: legacyEvent.targetUnitType,
    targetUnitId: legacyEvent.targetUnitId,
    player: legacyEvent.player,
    startHex: legacyEvent.startHex,
    endHex: legacyEvent.endHex,
    shootDetails: legacyEvent.shootDetails
  };
}

/**
 * Display utility functions (compatible with existing GameLog component)
 */
export function getEventIcon(type: string): string {
  switch (type) {
    case 'turn_change': return '🔄';
    case 'phase_change': return '⏭️';
    case 'move': return '👟';
    case 'shoot': return '🎯';
    case 'charge': return '⚡';
    case 'combat': return '⚔️';
    case 'death': return '💀';
    case 'move_cancel': return '❌';
    case 'charge_cancel': return '❌';
    default: return '📝';
  }
}

export function getEventTypeClass(event: BaseLogEntry | TrainingLogEntry): string {
  switch (event.type) {
    case 'turn_change': return 'game-log-entry--turn';
    case 'phase_change': return 'game-log-entry--phase';
    case 'move': return 'game-log-entry--move';
    case 'shoot':
      // Check shootDetails for actual shooting results (same logic as BoardReplay.tsx)
      if (event.shootDetails && Array.isArray(event.shootDetails)) {
        const hasWounds = event.shootDetails.some((shot: any) => shot.damageDealt && shot.damageDealt > 0);
        const hasSaves = event.shootDetails.some((shot: any) => shot.saveSuccess === true);
        
        if (hasWounds) {
          return 'game-log-entry--shoot-damage'; // Red - target loses HP
        } else if (hasSaves) {
          return 'game-log-entry--shoot-saved'; // Orange - target succeeded save roll
        }
      }
      return 'game-log-entry--shoot-failed'; // Yellow - failed during hit or wound rolls
    case 'charge': return 'game-log-entry--charge';
    case 'combat':
      // Check shootDetails for actual combat results (same logic as shooting)
      if (event.shootDetails && Array.isArray(event.shootDetails)) {
        const hasWounds = event.shootDetails.some((shot: any) => shot.damageDealt && shot.damageDealt > 0);
        const hasSaves = event.shootDetails.some((shot: any) => shot.saveSuccess === true);
        
        if (hasWounds) {
          return 'game-log-entry--combat-damage'; // Red - target loses HP
        } else if (hasSaves) {
          return 'game-log-entry--combat-saved'; // Orange - target succeeded save roll
        }
      }
      return 'game-log-entry--combat-failed'; // Yellow - failed during hit or wound rolls
    case 'death': return 'game-log-entry--death';
    case 'move_cancel': return 'game-log-entry--cancel';
    case 'charge_cancel': return 'game-log-entry--cancel';
    default: return 'game-log-entry--default';
  }
}