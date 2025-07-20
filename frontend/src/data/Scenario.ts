// src/data/Scenario.ts
import { Unit } from '../types/game';
import { createUnit, getAvailableUnitTypes } from './UnitFactory';

const initialUnits: Unit[] = [
  // Player 0 units
  createUnit({
    id: 0,
    name: "P-I",
    type: "Intercessor",
    player: 0,
    col: 23,
    row: 12,
    color: 0x244488,
  }),
  createUnit({
    id: 1,
    name: "P-A",
    type: "AssaultIntercessor",
    player: 0,
    col: 1,
    row: 12,
    color: 0xff3333,
  }),
  // Player 1 units (AI)
  createUnit({
    id: 2,
    name: "A-T",
    type: "Termagant",
    player: 1,
    col: 0,
    row: 5,
    color: 0x882222,
  }),
  createUnit({
    id: 3,
    name: "A-C",
    type: "Carnifex",
    player: 1,
    col: 22,
    row: 3,
    color: 0x6633cc,
  }),
];

export default initialUnits;