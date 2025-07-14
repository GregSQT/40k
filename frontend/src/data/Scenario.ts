// src/data/Scenario.ts
import { Unit } from '../types/game';
import { createUnit } from './UnitFactory';

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
    name: "A-I",
    type: "Intercessor",
    player: 1,
    col: 0,
    row: 5,
    color: 0x882222,
  }),
  createUnit({
    id: 3,
    name: "A-A",
    type: "AssaultIntercessor",
    player: 1,
    col: 22,
    row: 3,
    color: 0x6633cc,
  }),
];

// Debug: Log the created units
console.log('🔧 Created units with properties:', initialUnits.map(unit => ({
  name: unit.name,
  type: unit.type,
  RNG_NB: unit.RNG_NB,
  RNG_ATK: unit.RNG_ATK,
  RNG_STR: unit.RNG_STR,
  RNG_AP: unit.RNG_AP,
  T: unit.T,
  ARMOR_SAVE: unit.ARMOR_SAVE,
  INVUL_SAVE: unit.INVUL_SAVE,
  RNG_RNG: unit.RNG_RNG
})));

export default initialUnits;