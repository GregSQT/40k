// src > data > units.ts

export type Unit = {
  id: number;
  name: string;
  col: number;
  row: number;
  color: number;
  MOVE: number;
};

export const initialUnits: Unit[] = [
  { id: 1, name: "I1", col: 3, row: 4, color: 0x0078ff, MOVE: 4 },
  { id: 2, name: "A1", col: 15, row: 10, color: 0xff3333, MOVE: 6 },
];
