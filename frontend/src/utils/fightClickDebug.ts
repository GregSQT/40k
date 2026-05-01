/**
 * Logs de diagnostic pour les clics / attaques CC (phase fight).
 * Désactivé par défaut (y compris en dev Vite) pour limiter le bruit console.
 * Activer : `localStorage.setItem("DEBUG_FIGHT_CLICK", "1")` puis recharger.
 *
 * Les traces **Game Log / action_logs** (`[ACTION_LOG_TRACE]` dans la console) :
 * même opt-in via `DEBUG_FIGHT_CLICK`, ou uniquement Game Log avec
 * `localStorage.setItem("DEBUG_ACTION_LOG", "1")`.
 */
export function isFightClickDebugEnabled(): boolean {
  if (typeof localStorage === "undefined") {
    return false;
  }
  try {
    return localStorage.getItem("DEBUG_FIGHT_CLICK") === "1";
  } catch {
    return false;
  }
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
