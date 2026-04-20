import type { RefObject } from "react";
import { normalizeMaskLoopsFromApi } from "./movePreviewFootprintMaskLoops";

/** Remplit un Set ``col,row`` depuis les listes moteur (couples, objets ou chaînes ``"c,r"``). */
export function addHexKeysToSet(raw: unknown, out: Set<string>): void {
  if (!Array.isArray(raw)) return;
  for (const d of raw) {
    if (Array.isArray(d) && d.length >= 2) {
      out.add(`${Number(d[0])},${Number(d[1])}`);
    } else if (d && typeof d === "object" && "col" in d && "row" in d) {
      const o = d as { col: unknown; row: unknown };
      out.add(`${Number(o.col)},${Number(o.row)}`);
    } else if (typeof d === "string") {
      const sep = d.indexOf(",");
      if (sep > 0) {
        out.add(`${Number(d.slice(0, sep))},${Number(d.slice(sep + 1))}`);
      }
    }
  }
}

export type SyncMoveDestinationPoolRefsOptions = {
  gameState: {
    valid_move_destinations_pool?: unknown;
    /** Alias moteur parfois présent si le pool principal est absent. */
    preview_hexes?: unknown;
    move_preview_footprint_zone?: unknown;
    move_preview_footprint_mask_loops?: unknown;
  } | null;
  phase: string;
  mode: string;
  selectedUnitId: number | null;
  moveDestPoolRef: RefObject<Set<string>> | undefined;
  footprintZoneRef?: RefObject<Set<string>> | undefined;
  /** Hit-test / debug quand la zone hex n’est pas dans le JSON (boucles monde). */
  footprintMaskLoopsRef?: RefObject<number[][] | null> | undefined;
  /** Aligné sur ``pendingPreviewAction === "move_after_shooting"`` (useEngineAPI). */
  pendingMoveAfterShooting?: boolean;
};

/**
 * Met à jour moveDestPoolRef / footprintZoneRef depuis le game_state.
 * À appeler **avant** drawBoard (comme syncChargePoolRefs synchrone en phase charge) :
 * un useEffect parent après l’enfant laissait la ref vide au premier paint.
 */
export function syncMoveDestinationPoolRefs(o: SyncMoveDestinationPoolRefsOptions): void {
  const {
    gameState,
    phase,
    mode,
    selectedUnitId,
    moveDestPoolRef,
    footprintZoneRef,
    footprintMaskLoopsRef,
    pendingMoveAfterShooting,
  } = o;

  if (!moveDestPoolRef?.current) return;

  const clearBoth = (): void => {
    moveDestPoolRef.current = new Set();
    if (footprintZoneRef?.current) {
      footprintZoneRef.current = new Set();
    }
    if (footprintMaskLoopsRef) {
      footprintMaskLoopsRef.current = null;
    }
  };

  const applyFromState = (): void => {
    if (!gameState) return;
    const anchorSource =
      gameState.valid_move_destinations_pool ??
      (gameState.preview_hexes as unknown);
    // Ne pas remplacer la ref par un Set vide si le state n’a pas encore les clés (course avec
    // executeAction qui remplit la ref avant le prochain game_state complet) — sinon on efface
    // des milliers d’ancres et le plateau retombe sur les pastilles hex.
    if (anchorSource === undefined || anchorSource === null) {
      return;
    }
    if (!Array.isArray(anchorSource)) {
      return;
    }
    const poolSet = new Set<string>();
    addHexKeysToSet(anchorSource, poolSet);
    moveDestPoolRef.current = poolSet;
    const maskLoops = normalizeMaskLoopsFromApi(
      (gameState as { move_preview_footprint_mask_loops?: unknown }).move_preview_footprint_mask_loops,
    );
    if (footprintMaskLoopsRef) {
      footprintMaskLoopsRef.current = maskLoops;
    }
    if (footprintZoneRef?.current) {
      if (poolSet.size === 0) {
        footprintZoneRef.current = new Set();
      } else if (maskLoops && maskLoops.length > 0) {
        footprintZoneRef.current = new Set();
      } else {
        const fpRaw = gameState.move_preview_footprint_zone;
        if (Array.isArray(fpRaw) && fpRaw.length > 0) {
          const fpSet = new Set<string>();
          addHexKeysToSet(fpRaw, fpSet);
          footprintZoneRef.current = fpSet;
        } else {
          footprintZoneRef.current = new Set();
        }
      }
    }
  };

  /** Phase command (PvP) : même pool que move — avant seul ``move`` remplissait la ref. */
  if (phase === "move" || phase === "command") {
    if (selectedUnitId === null) {
      clearBoth();
      return;
    }
    applyFromState();
    return;
  }

  /** Advance : même source ``valid_move_destinations_pool`` / ``preview_hexes`` que le move (portée M+D6×10, etc.) — ne pas exiger ``phase === "shoot"`` (replay). */
  if (mode === "advancePreview") {
    applyFromState();
    return;
  }

  if (phase === "shoot" && pendingMoveAfterShooting) {
    if (selectedUnitId === null) {
      clearBoth();
      return;
    }
    applyFromState();
  }
}
