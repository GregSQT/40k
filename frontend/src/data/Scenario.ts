// frontend/src/data/Scenario.ts

import { createUnit } from "./UnitFactory.js";

const units = [
  // Player 0 units
  createUnit({
    id: 0,
    name: "P-I",
    type: "Intercessor",
    player: 0,
    col: 23,
    row: 12, // Game 17, Test 12
    color: 0x244488,
  }),
  createUnit({
    id: 1,
    name: "P-A",
    type: "Assault Intercessor",
    player: 0,
    col: 1,
    row: 12, // Game 17, Test 12
    color: 0xff3333,
  }),
  // Player 1 units
  createUnit({
    id: 2,
    name: "A-I",
    type: "Intercessor",
    player: 1,
    col: 0,
    row: 5, // Game 0, Test 5
    color: 0x882222,
  }),
  createUnit({
    id: 3,
    name: "A-A",
    type: "Assault Intercessor",
    player: 1,
    col: 22,
    row: 3, // Game 0, Test 3
    color: 0x6633cc,
  }),
];

export default units;
