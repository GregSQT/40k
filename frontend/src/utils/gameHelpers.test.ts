import { describe, expect, it } from "vitest";
import {
  applyDamage,
  findUnitById,
  getAdjacentPositions,
  getEnemiesInRange,
  getHexDistance,
  getPlayerUnits,
  getUnitsAtPosition,
  getValidMovePositions,
  hasLineOfSight,
  isGameOver,
  isPositionOccupied,
  isUnitAlive,
  isValidMove,
  offsetToCube,
} from "./gameHelpers";

const makeUnit = (id: number, player: number, col: number, row: number, move = 2) =>
  ({
    id,
    name: `U${id}`,
    player,
    col,
    row,
    MOVE: move,
    HP_MAX: 5,
    HP_CUR: 5,
    RNG_WEAPONS: [],
    CC_WEAPONS: [],
  }) as any;

describe("gameHelpers", () => {
  it("calcule des distances coherentes sur grille hex", () => {
    const a = offsetToCube(0, 0);
    const b = offsetToCube(1, 0);
    expect(getHexDistance({ col: 0, row: 0 }, { col: 1, row: 0 })).toBe(1);
    expect(a.x).toBe(0);
    expect(b.x).toBe(1);
  });

  it("retourne LoS direct sans murs", () => {
    const shooter = makeUnit(1, 1, 0, 0);
    const target = makeUnit(2, 2, 3, 0);
    const los = hasLineOfSight(shooter, target, [], 0.6, 0.4);
    expect(los.canSee).toBe(true);
    expect(los.inCover).toBe(false);
    expect(los.visibilityRatio).toBe(1);
  });

  it("filtre et localise les unites", () => {
    const units = [makeUnit(1, 1, 0, 0), makeUnit(2, 2, 1, 0), makeUnit(3, 1, 1, 0)];
    expect(findUnitById(units, 2 as any)?.player).toBe(2);
    expect(getUnitsAtPosition(units, { col: 1, row: 0 })).toHaveLength(2);
    expect(getPlayerUnits(units, 1)).toHaveLength(2);
    expect(isPositionOccupied(units, { col: 1, row: 0 })).toBe(true);
    expect(isPositionOccupied(units, { col: 1, row: 0 }, 2 as any)).toBe(true);
  });

  it("calcule les portees et mouvements valides", () => {
    const center = makeUnit(1, 1, 0, 0, 2);
    const enemyNear = makeUnit(2, 2, 1, 0);
    const enemyFar = makeUnit(3, 2, 4, 4);
    const ally = makeUnit(4, 1, 0, 1);
    const units = [center, enemyNear, enemyFar, ally];

    expect(getEnemiesInRange(units, center, 1)).toHaveLength(1);

    const validMoves = getValidMovePositions(center, units, 5, 5);
    expect(validMoves.length).toBeGreaterThan(0);
    expect(isValidMove(center, { col: 1, row: 0 }, units, 5, 5)).toBe(false);
    expect(isValidMove(center, { col: 2, row: 0 }, units, 5, 5)).toBe(true);
  });

  it("gere HP, vie et fin de partie", () => {
    const u1 = makeUnit(1, 1, 0, 0);
    const u2 = makeUnit(2, 2, 1, 0);
    const damaged = applyDamage(u1, 2);
    expect(damaged.HP_CUR).toBe(3);
    expect(isUnitAlive(damaged)).toBe(true);
    expect(isUnitAlive(applyDamage(u2, 10))).toBe(false);

    expect(isGameOver([u1, u2]).gameOver).toBe(false);
    expect(isGameOver([u1]).winner).toBe(1);
  });

  it("retourne des adjacences dans les bornes du plateau", () => {
    const positions = getAdjacentPositions({ col: 0, row: 0 }, 3, 3);
    expect(positions.every((p) => p.col >= 0 && p.row >= 0)).toBe(true);
    expect(positions.length).toBeGreaterThan(0);
  });
});
