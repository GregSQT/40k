/**
 * Client : déduplication des entrées ``action_logs`` avant dispatch ``backendLogEvent``.
 * Traces : même activation que ``fightClickDebug`` (dev Vite ou ``DEBUG_FIGHT_CLICK``)
 * ou forcer avec ``localStorage.setItem("DEBUG_ACTION_LOG", "1")``.
 */

import { isFightClickDebugEnabled } from "./fightClickDebug";

export function isActionLogTraceEnabled(): boolean {
  try {
    if (typeof localStorage !== "undefined" && localStorage.getItem("DEBUG_ACTION_LOG") === "1") {
      return true;
    }
  } catch {
    /* ignore */
  }
  return isFightClickDebugEnabled();
}

/** Clé stable pour une entrée ``action_logs`` (évite doublons 1 vs "1" sur ``unitId``). */
export function actionLogDedupeKey(e: Record<string, unknown>): string {
  const uidRaw = e.unitId ?? e.shooterId ?? e.attackerId;
  const uid = uidRaw === undefined || uidRaw === null ? "" : String(uidRaw);
  const typ = typeof e.type === "string" ? e.type : "";
  const msg = typeof e.message === "string" ? e.message : "";
  const ph = e.phase === undefined || e.phase === null ? "" : String(e.phase);
  return [typ, msg, String(e.turn ?? ""), uid, ph].join("\u0001");
}

/**
 * Même réponse API : une ligne Game Log par entrée ``action_logs``.
 * Déduplication **dans le lot** (entrées identiques côte à côte).
 */
export function dedupeActionLogBatch<T extends Record<string, unknown>>(entries: T[]): T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const e of entries) {
    const key = actionLogDedupeKey(e);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(e);
  }
  return out;
}

const recentActionLogEmitAt = new Map<string, number>();
export const CROSS_ACTION_LOG_SUPPRESS_MS = 5000;
const ACTION_LOG_EMIT_MAP_MAX = 300;

/** Évite la même ligne sur **plusieurs** réponses HTTP rapprochées (move + ``advance_phase`` chaîné, etc.). */
export function shouldEmitActionLogEvent(entry: Record<string, unknown>): boolean {
  const key = actionLogDedupeKey(entry);
  const now = Date.now();
  const last = recentActionLogEmitAt.get(key);
  if (last !== undefined && now - last < CROSS_ACTION_LOG_SUPPRESS_MS) {
    return false;
  }
  recentActionLogEmitAt.set(key, now);
  if (recentActionLogEmitAt.size > ACTION_LOG_EMIT_MAP_MAX) {
    const cutoff = now - CROSS_ACTION_LOG_SUPPRESS_MS;
    for (const [k, t] of recentActionLogEmitAt) {
      if (t < cutoff) recentActionLogEmitAt.delete(k);
    }
  }
  return true;
}

export function summarizeActionLogEntry(e: Record<string, unknown>): Record<string, unknown> {
  const uidRaw = e.unitId ?? e.shooterId ?? e.attackerId;
  const msg = typeof e.message === "string" ? e.message : "";
  return {
    type: e.type,
    phase: e.phase,
    turn: e.turn,
    player: e.player,
    attackerOrShooter: uidRaw === undefined || uidRaw === null ? undefined : String(uidRaw),
    targetId: e.targetId,
    messagePreview: msg.length > 100 ? `${msg.slice(0, 100)}…` : msg,
  };
}

/** Résumé du lot brut + après dédup intra-lot (diagnostic Game Log / fight). */
export function logActionLogBatchTrace(
  source: string,
  raw: ReadonlyArray<Record<string, unknown>>,
  context: Record<string, unknown>
): void {
  if (!isActionLogTraceEnabled()) return;
  const arr = Array.isArray(raw) ? [...raw] : [];
  const deduped = dedupeActionLogBatch(arr);
  console.info("[ACTION_LOG_TRACE]", source, "batch", {
    ...context,
    rawCount: arr.length,
    afterIntraBatchDedupe: deduped.length,
    droppedDuplicatesInBatch: arr.length - deduped.length,
    entries: deduped.map((e) => summarizeActionLogEntry(e)),
  });
}

export function logActionLogEmitTrace(
  source: string,
  entry: Record<string, unknown>,
  emitted: boolean,
  reason?: string
): void {
  if (!isActionLogTraceEnabled()) return;
  console.info("[ACTION_LOG_TRACE]", source, emitted ? "→ dispatch backendLogEvent" : "→ SUPPRIMÉ", {
    ...summarizeActionLogEntry(entry),
    dedupeKey: actionLogDedupeKey(entry),
    reason,
  });
}
