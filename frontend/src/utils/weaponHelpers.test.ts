import { describe, expect, it } from "vitest";

import { getDiceAverage, getSelectedRangedWeapon } from "./weaponHelpers";

describe("weaponHelpers", () => {
  it("returns null when unit has no ranged weapons", () => {
    const unit = { id: "u1", RNG_WEAPONS: [] } as any;
    expect(getSelectedRangedWeapon(unit)).toBeNull();
  });

  it("returns selected ranged weapon by index", () => {
    const unit = {
      id: "u2",
      RNG_WEAPONS: [
        { id: "w1", ATK: 4, STR: 4, AP: 0, DMG: 1 },
        { id: "w2", ATK: 3, STR: 5, AP: 1, DMG: 2 },
      ],
      selectedRngWeaponIndex: 1,
    } as any;

    expect(getSelectedRangedWeapon(unit)).toEqual(unit.RNG_WEAPONS[1]);
  });

  it("throws when selected ranged index is invalid", () => {
    const unit = {
      id: "u3",
      RNG_WEAPONS: [{ id: "w1", ATK: 4, STR: 4, AP: 0, DMG: 1 }],
      selectedRngWeaponIndex: 10,
    } as any;

    expect(() => getSelectedRangedWeapon(unit)).toThrow(
      "Invalid selectedRngWeaponIndex 10 for unit u3"
    );
  });

  it("computes D6 dice average", () => {
    expect(getDiceAverage("D6")).toBe(3.5);
  });
});
