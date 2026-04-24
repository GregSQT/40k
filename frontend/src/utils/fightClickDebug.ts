/**
 * Logs de diagnostic pour les clics / attaques CC (phase fight).
 * - En build Vite dev : actif par défaut.
 * - Sinon : `localStorage.setItem("DEBUG_FIGHT_CLICK", "1")` puis recharger.
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
