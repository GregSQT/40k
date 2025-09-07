// frontend/src/data/units.ts

import { createUnit } from "@data/UnitFactory";

export type { Unit } from "@data/UnitFactory";

export const initialUnits = [
  // AI units
  createUnit({
    id: 1,
    name: "A-I",
    type: "Intercessor",
    player: 1,
    col: 0,
    row: 0,
    color: 0x3377cc,
  }),
  createUnit({
    id: 2,
    name: "A-A",
    type: "AssaultIntercessor",
    player: 1,
    col: 22,
    row: 0,
    color: 0x6633cc,
  }),
  // Player units
  createUnit({
    id: 3,
    name: "P-A",
    type: "AssaultIntercessor",
    player: 0,
    col: 1,
    row: 17,
    color: 0xff3333,
  }),
  createUnit({
    id: 4,
    name: "P-I",
    type: "Intercessor",
    player: 0,
    col: 23,
    row: 17,
    color: 0x0078ff,
  }),
];
