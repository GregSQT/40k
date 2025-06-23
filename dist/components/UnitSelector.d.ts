import type { Unit } from "@data/Units";
type Props = {
    units: Unit[];
    currentPlayer: 0 | 1;
    selectedUnitId: number | null;
    onSelect: (id: number) => void;
    unitsMoved: number[];
    unitsCharged?: number[];
    unitsAttacked?: number[];
    phase?: "move" | "shoot" | "charge" | "combat";
};
export default function UnitSelector({ units, currentPlayer, selectedUnitId, onSelect, unitsMoved, unitsCharged, unitsAttacked, phase }: Props): import("react/jsx-runtime").JSX.Element;
export {};
