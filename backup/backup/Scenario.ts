// src/data/Scenario.ts
import { Unit } from '../types/game';

const initialUnits: Unit[] = [
  // Player 0 units
  {
    id: 0,
    name: "P-I",
    type: "Intercessor",
    player: 0,
    col: 23,
    row: 12,
    color: 0x244488,
    MOVE: 4,
    HP_MAX: 3,
    RNG_RNG: 8,
    RNG_DMG: 2,
    CC_DMG: 1,
    ICON: "/icons/Intercessor.webp",
  },
  {
    id: 1,
    name: "P-A",
    type: "Assault Intercessor",
    player: 0,
    col: 1,
    row: 12,
    color: 0xff3333,
    MOVE: 6,
    HP_MAX: 4,
    RNG_RNG: 4,
    RNG_DMG: 1,
    CC_DMG: 2,
    ICON: "/icons/AssaultIntercessor.webp",
  },
  // Player 1 units (AI)
  {
    id: 2,
    name: "A-I",
    type: "Intercessor",
    player: 1,
    col: 0,
    row: 5,
    color: 0x882222,
    MOVE: 4,
    HP_MAX: 3,
    RNG_RNG: 8,
    RNG_DMG: 2,
    CC_DMG: 1,
    ICON: "/icons/Intercessor.webp",
  },
  {
    id: 3,
    name: "A-A",
    type: "Assault Intercessor",
    player: 1,
    col: 22,
    row: 3,
    color: 0x6633cc,
    MOVE: 6,
    HP_MAX: 4,
    RNG_RNG: 4,
    RNG_DMG: 1,
    CC_DMG: 2,
    ICON: "/icons/AssaultIntercessor.webp",
  },
];

export default initialUnits;