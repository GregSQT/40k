import { resolveBaseSizeForUnitDisplay } from "./hexFootprint";

/** Le sous-ensemble de `PIXI.Graphics` que le réticule utilise (testable sans PIXI). */
export interface ReticleCanvas {
  lineStyle(width: number, color?: number, alpha?: number): unknown;
  beginFill(color: number, alpha?: number): unknown;
  endFill(): unknown;
  drawCircle(x: number, y: number, radius: number): unknown;
  moveTo(x: number, y: number): unknown;
  lineTo(x: number, y: number): unknown;
}

/**
 * Réticule de visée (cercle + 4 traits cardinaux) sur CHAQUE figurine d'une unité cible ;
 * `veil` ajoute le voile jaune léger de la cible active du menu. Source unique du tracé pour la
 * désignation (menu d'armes : toutes les unités désignées, décision du 2026-09-18) et le lot en
 * cours (après Shoot / Fight : la seule unité que le lot résout, clignotante).
 */
export function drawReticle(
  overlay: ReticleCanvas,
  hexRadius: number,
  centerOf: (pos: [number, number]) => [number, number],
  target: Parameters<typeof resolveBaseSizeForUnitDisplay>[0],
  hexesByModel: Record<string, [number, number]>,
  opts: { veil: boolean; alpha: number }
): void {
  const base = resolveBaseSizeForUnitDisplay(target);
  const tR = base > 1 ? (base * 1.5 * hexRadius) / 2 : hexRadius * 0.7;
  const rr = tR * 1.15; // rayon du réticule
  const tickIn = rr * 0.75; // les traits cardinaux chevauchent le cercle
  const tickOut = rr * 1.35;
  const reticleW = Math.max(3, hexRadius * 0.38);
  for (const pos of Object.values(hexesByModel)) {
    const [cx, cy] = centerOf(pos);
    if (opts.veil) {
      overlay.lineStyle(0);
      overlay.beginFill(0xf5c518, 0.22);
      overlay.drawCircle(cx, cy, tR);
      overlay.endFill();
    }
    overlay.lineStyle(reticleW, 0xff2b2b, opts.alpha);
    overlay.drawCircle(cx, cy, rr);
    overlay.moveTo(cx, cy - tickIn);
    overlay.lineTo(cx, cy - tickOut);
    overlay.moveTo(cx, cy + tickIn);
    overlay.lineTo(cx, cy + tickOut);
    overlay.moveTo(cx - tickIn, cy);
    overlay.lineTo(cx - tickOut, cy);
    overlay.moveTo(cx + tickIn, cy);
    overlay.lineTo(cx + tickOut, cy);
  }
}

/**
 * Unités sur lesquelles le réticule du LOT EN COURS se pose, et s'il bat. Allocation en cours ou
 * attente de lot verrouillée sur une unité → cette seule unité, clignotante ; attente de lot
 * ouverte (l'attaquant choisit encore l'unité, 04.03) → chaque unité candidate, fixe.
 */
export function attackLotReticleTargets(
  lotRequest: {
    locked_target_unit_id: string | null;
    lots: Array<{ target_unit_id: string }>;
  } | null,
  allocationTargetUnitId: string | null
): { targets: string[]; blinking: boolean } {
  const inProgress =
    allocationTargetUnitId !== null
      ? String(allocationTargetUnitId)
      : lotRequest?.locked_target_unit_id
        ? String(lotRequest.locked_target_unit_id)
        : null;
  if (inProgress !== null) return { targets: [inProgress], blinking: true };
  return {
    targets: Array.from(new Set((lotRequest?.lots ?? []).map((l) => String(l.target_unit_id)))),
    blinking: false,
  };
}
