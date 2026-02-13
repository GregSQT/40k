// shared/gameLogUtils.ts
// Shared game log message formatting functions ONLY
// Extracted from PvP useGameLog.ts - preserves exact format

/**
 * Format game log messages exactly like PvP useGameLog.ts
 * This is the REFERENCE implementation - do not modify
 */
export function formatShootingMessage(shooterId: number, targetId: number): string {
  return `Unit ${shooterId} SHOT at Unit ${targetId}`;
}

export function formatMoveMessage(
  unitId: number,
  startCol: number,
  startRow: number,
  endCol: number,
  endRow: number
): string {
  const startHex = `(${startCol}, ${startRow})`;
  const endHex = `(${endCol}, ${endRow})`;
  return `Unit ${unitId} MOVED from ${startHex} to ${endHex}`;
}

export function formatNoMoveMessage(unitId: number): string {
  return `Unit ${unitId} NO MOVE`;
}

export function formatCombatMessage(attackerId: number, targetId: number): string {
  return `Unit ${attackerId} FOUGHT unit ${targetId}`;
}

export function formatChargeMessage(
  unitName: string,
  unitId: number,
  targetName: string,
  targetId: number,
  startCol: number,
  startRow: number,
  endCol: number,
  endRow: number
): string {
  const startHex = `(${startCol}, ${startRow})`;
  const endHex = `(${endCol}, ${endRow})`;
  return `Unit ${unitName} ${unitId} CHARGED Unit ${targetName} ${targetId} from ${startHex} to ${endHex}`;
}

export function formatDeathMessage(unitId: number, unitType: string): string {
  return `Unit ${unitId} (${unitType}) DIED !`;
}

export function formatMoveCancelMessage(unitName: string, unitId: number): string {
  return `Unit ${unitName} ${unitId} cancelled its move action`;
}

export function formatChargeCancelMessage(unitName: string, unitId: number): string {
  return `Unit ${unitName} ${unitId} cancelled its charge action`;
}

export function formatTurnStartMessage(turnNumber: number): string {
  return `Start of Turn ${turnNumber}`;
}

export function formatPhaseChangeMessage(playerName: string, phase: string): string {
  return `Start ${playerName}'s ${phase.toUpperCase()} phase`;
}
