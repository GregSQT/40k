// frontend/src/data/Scenario.ts
import { Unit } from '../types/game';
import { createUnit, getAvailableUnitTypes } from './UnitFactory';

const initialUnits: Unit[] = [
  // Player 0 units
  createUnit({
    id: 0,
    name: "P-I",
    type: "Intercessor",
    player: 0,
    col: 2,
    row: 8,
    color: 0x244488,
  }),
  createUnit({
    id: 1,
    name: "P-I",
    type: "CaptainGravis",
    player: 0,
    col: 23,
    row: 9,
    color: 0x244488,
  }),
  createUnit({
    id: 2,
    name: "P-A",
    type: "AssaultIntercessor",
    player: 0,
    col: 16,
    row: 4,
    color: 0xff3333,
  }),
  // Player 1 units (AI)
  createUnit({
    id: 3,
    name: "A-T",
    type: "Termagant",
    player: 1,
    col: 20,
    row: 1,
    color: 0x882222,
  }),
  createUnit({
    id: 4,
    name: "A-T",
    type: "Termagant",
    player: 1,
    col: 21,
    row: 1,
    color: 0x882222,
  }),
  createUnit({
    id: 5,
    name: "A-T",
    type: "Hormagaunt",
    player: 1,
    col: 25,
    row: 1,
    color: 0x882222,
  }),
  createUnit({
    id: 6,
    name: "A-T",
    type: "Hormagaunt",
    player: 1,
    col: 26,
    row: 2,
    color: 0x882222,
  }),
  createUnit({
    id: 7,
    name: "A-C",
    type: "Carnifex",
    player: 1,
    col: 23,
    row: 1,
    color: 0x6633cc,
  }),
  createUnit({
    id: 8,
    name: "A-T",
    type: "Termagant",
    player: 1,
    col: 3,
    row: 3,
    color: 0x882222,
  }),
  createUnit({
    id: 9,
    name: "A-T",
    type: "Termagant",
    player: 1,
    col: 6,
    row: 4,
    color: 0x882222,
  }),
];

export default initialUnits;