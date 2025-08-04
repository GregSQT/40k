// shared/gameLogStructure.ts
// Unified game log structure for both PvP and Replay systems
// Based on replay log format as the standard

/**
 * Base log entry interface - used by both PvP and Replay
 * This matches the replay log format exactly
 */
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

  // Import existing message formatting functions
  const messageFormatters = {
    shoot: (actorId: number, targetId: number) => `Unit ${actorId} SHOT at unit ${targetId}`,
    move: (unitId: number, startHex: string, endHex: string) => `Unit ${unitId} MOVED from ${startHex} to ${endHex}`,
    combat: (attackerId: number, targetId: number) => `Unit ${attackerId} FOUGHT unit ${targetId}`,
    charge: (unitName: string, unitId: number, targetName: string, targetId: number, startHex: string, endHex: string) => 
      `Unit ${unitName} ${unitId} CHARGED unit ${targetName} ${targetId} from ${startHex} to ${endHex}`,
    death: (unitId: number, unitType: string) => `Unit ${unitId} (${unitType}) DIED !`,
    move_cancel: (unitName: string, unitId: number) => `Unit ${unitName} ${unitId} cancelled its move action`,
    charge_cancel: (unitName: string, unitId: number) => `Unit ${unitName} ${unitId} cancelled its charge action`,
    turn_change: (turnNumber: number) => `Start of Turn ${turnNumber}`,
    phase_change: (playerName: string, phase: string) => `Start ${playerName}'s ${phase.toUpperCase()} phase`
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
      const message = event.message;
      if (message.includes('HP') && message.includes('-')) {
        return 'game-log-entry--shoot-damage';
      }
      if (message.includes('Saved!') || (message.includes('Success!') && !message.includes('Failed!'))) {
        return 'game-log-entry--shoot-saved';
      }
      return 'game-log-entry--shoot';
    case 'charge': return 'game-log-entry--charge';
    case 'combat': return 'game-log-entry--combat';
    case 'death': return 'game-log-entry--death';
    case 'move_cancel': return 'game-log-entry--cancel';
    case 'charge_cancel': return 'game-log-entry--cancel';
    default: return 'game-log-entry--default';
  }
}