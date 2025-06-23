import type { Unit } from "@data/Units";
type Mode = "select" | "movePreview" | "attackPreview" | "chargePreview";
type BoardProps = {
    units: Unit[];
    selectedUnitId: number | null;
    mode: Mode;
    movePreview: {
        unitId: number;
        destCol: number;
        destRow: number;
    } | null;
    attackPreview: {
        unitId: number;
        col: number;
        row: number;
    } | null;
    onSelectUnit: (id: number | string | null) => void;
    onStartMovePreview: (unitId: number | string, col: number | string, row: number | string) => void;
    onStartAttackPreview: (unitId: number, col: number, row: number) => void;
    onConfirmMove: () => void;
    onCancelMove: () => void;
    onShoot: (shooterId: number, targetId: number) => void;
    onCombatAttack?: (attackerId: number, targetId: number | null) => void;
    currentPlayer: 0 | 1;
    unitsMoved: number[];
    unitsCharged?: number[];
    unitsAttacked?: number[];
    phase: "move" | "shoot" | "charge" | "combat";
    onCharge?: (chargerId: number, targetId: number) => void;
    onMoveCharger?: (chargerId: number, destCol: number, destRow: number) => void;
    onCancelCharge?: () => void;
    onValidateCharge?: (chargerId: number) => void;
};
export default function Board({ units, selectedUnitId, mode, movePreview, attackPreview, onSelectUnit, onStartMovePreview, onStartAttackPreview, onConfirmMove, onCancelMove, currentPlayer, unitsMoved, phase, onShoot, onCombatAttack, onCharge, unitsCharged, unitsAttacked, onMoveCharger, onCancelCharge, onValidateCharge, }: BoardProps): import("react/jsx-runtime").JSX.Element;
export {};
