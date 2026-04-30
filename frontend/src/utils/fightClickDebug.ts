/**
 * Logs de diagnostic pour les clics / attaques CC (phase fight).
 * - En build Vite dev : actif par défaut.
 * - Sinon : `localStorage.setItem("DEBUG_FIGHT_CLICK", "1")` puis recharger.
 *
 * Les traces **Game Log / action_logs** (`[ACTION_LOG_TRACE]` dans la console) suivent le même
 * critère, ou forcer uniquement ces traces avec `localStorage.setItem("DEBUG_ACTION_LOG", "1")`.
 */
export function isFightClickDebugEnabled(): boolean {
  try {
    if (typeof import.meta !== "undefined" && import.meta.env?.DEV === true) {
      return true;
    }
  } catch {
    /* ignore */
  }
  if (typeof localStorage === "undefined") {
    return false;
  }
  return localStorage.getItem("DEBUG_FIGHT_CLICK") === "1";
}

export function logFightClick(message: string, detail?: Record<string, unknown>): void {
  if (!isFightClickDebugEnabled()) {
    return;
  }
  if (detail !== undefined) {
    console.info("[FIGHT_CLICK]", message, detail);
  } else {
    console.info("[FIGHT_CLICK]", message);
  }
}
