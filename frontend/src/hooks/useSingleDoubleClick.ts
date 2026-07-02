// frontend/src/hooks/useSingleDoubleClick.ts
import { useCallback, useEffect, useRef } from "react";

/**
 * Distingue simple vs double clic sur une même « clé » (id de cible), en évitant que
 * l'effet du simple parte AVANT le double.
 *
 * Le simple est RETARDÉ de `delay` ms : si un 2e clic sur la même clé arrive avant
 * l'échéance, on annule le simple et on joue le double. Un clic sur une clé différente
 * pendant qu'un simple est en attente exécute d'abord ce simple, puis démarre un
 * nouveau cycle. Toute la gestion (timer + comparaison de clé) est encapsulée ici pour
 * être réutilisée (clic-cible tir, sélection de figurine, etc.).
 *
 * @param delay Fenêtre de détection du double-clic en ms (défaut 250).
 * @returns `trigger(key, onSingle, onDouble)` — stable, appelable dans un event listener.
 */
export function useSingleDoubleClick(
  delay = 250
): (key: string | number, onSingle: () => void, onDouble: () => void) => void {
  const timerRef = useRef<number | null>(null);
  const pendingRef = useRef<{ key: string; onSingle: () => void } | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const trigger = useCallback(
    (key: string | number, onSingle: () => void, onDouble: () => void) => {
      const k = String(key);
      const pending = pendingRef.current;

      // 2e clic sur la MÊME clé avant l'échéance → double (le simple en attente est annulé).
      if (pending && pending.key === k && timerRef.current !== null) {
        clearTimer();
        pendingRef.current = null;
        onDouble();
        return;
      }

      // Un simple était en attente sur une autre clé → le jouer immédiatement avant de repartir.
      if (pending) {
        clearTimer();
        pendingRef.current = null;
        pending.onSingle();
      }

      // Arme le simple courant ; il ne partira que si aucun 2e clic n'arrive dans `delay`.
      pendingRef.current = { key: k, onSingle };
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null;
        const p = pendingRef.current;
        pendingRef.current = null;
        if (p) p.onSingle();
      }, delay);
    },
    [delay, clearTimer]
  );

  // Nettoyage au démontage : ne pas laisser un simple différé partir après unmount.
  useEffect(() => () => clearTimer(), [clearTimer]);

  return trigger;
}
