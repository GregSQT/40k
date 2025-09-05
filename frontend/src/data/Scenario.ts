// frontend/src/data/Scenario.ts
import { Unit } from '../types/game';
import { createUnit, getAvailableUnitTypes } from './UnitFactory';

const initialUnits: Unit[] = [
  // Player 0 units
  createUnit({
    id: 0,
    name: "P-C",
    type: "CaptainGravis",
    player: 0,
    col: 21,
    row: 3, 
    color: 0x244488,
  }),
  createUnit({
    id: 1,
    name: "P-I",
    type: "Intercessor",
    player: 0,
    col: 3,
    row: 3,
    color: 0x244488,
  }),

  // Player 1 units (AI)
  createUnit({
    id: 2,
    name: "A-H",
    type: "Hormagaunt",
    player: 1,
    col: 17,
    row: 0,
    color: 0x882222,
  }),
   createUnit({
    id: 3,
    name: "A-T",
    type: "Hormagaunt",
    player: 1,
    col: 6,
    row: 1,
    color: 0x882222,
  }),
  createUnit({
    id: 4,
    name: "A-T",
    type: "Hormagaunt",
    player: 1,
    col: 18,
    row: 1,
    color: 0x882222,
  }),
  createUnit({
    id: 5,
    name: "A-T",
    type: "Hormagaunt",
    player: 1,
    col: 22,
    row: 2,
    color: 0x882222,
  }),
  createUnit({
    id: 6,
    name: "A-T",
    type: "Hormagaunt",
    player: 1,
    col: 23,
    row: 2,
    color: 0x882222,
  }),
  createUnit({
    id: 7,
    name: "A-C",
    type: "Carnifex",
    player: 1,
    col: 20,
    row: 1,
    color: 0x6633cc,
  }),
  createUnit({
    id: 8,
    name: "A-H",
    type: "Hormagaunt",
    player: 1,
    col: 2,
    row: 2,
    color: 0x882222,
  }),
  createUnit({
    id: 9,
    name: "A-H",
    type: "Hormagaunt",
    player: 1,
    col: 4,
    row: 2,
    color: 0x882222,
  }),
];

export default initialUnits;