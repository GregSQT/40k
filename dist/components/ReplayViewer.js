import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// frontend/src/components/ReplayViewer.tsx
import { useState, useEffect } from "react";
import Board from "@components/Board";
export default function ReplayViewer({ eventLog, boardProps = {}, stepDelay = 700 }) {
    const [step, setStep] = useState(0);
    useEffect(() => {
        if (!eventLog || eventLog.length === 0)
            return;
        if (step >= eventLog.length - 1)
            return;
        const id = setTimeout(() => setStep(s => s + 1), stepDelay);
        return () => clearTimeout(id);
    }, [step, eventLog, stepDelay]);
    if (!eventLog || eventLog.length === 0)
        return _jsx("div", { children: "No replay loaded" });
    const current = eventLog[step];
    return (_jsxs("div", { children: [_jsx(Board, { units: current.units, selectedUnitId: current.acting_unit_idx, phase: current.phase, mode: "select", movePreview: null, attackPreview: null, onSelectUnit: () => { }, onStartMovePreview: () => { }, onStartAttackPreview: () => { }, onConfirmMove: () => { }, onCancelMove: () => { }, onShoot: () => { }, onCombatAttack: () => { }, onCharge: () => { }, unitsCharged: [], unitsAttacked: [], currentPlayer: 1, unitsMoved: [], onMoveCharger: () => { }, onCancelCharge: () => { }, onValidateCharge: () => { }, ...boardProps }), _jsxs("div", { style: { marginTop: 16, color: "#aee6ff" }, children: [_jsx("b", { children: "Turn:" }), " ", current.turn, " \u00A0", _jsx("b", { children: "Phase:" }), " ", current.phase, " \u00A0", _jsx("b", { children: "Unit:" }), " ", current.acting_unit_idx, " \u00A0", _jsx("b", { children: "Target:" }), " ", String(current.target_unit_idx), _jsxs("div", { children: ["Step ", step + 1, " / ", eventLog.length] })] })] }));
}
