import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
//
export default function UnitSelector({ units, currentPlayer, selectedUnitId, onSelect, unitsMoved, unitsCharged = [], unitsAttacked = [], phase = "move" }) {
    console.log("UnitSelector props", { phase, unitsCharged, unitsAttacked });
    // Filter units according to phase eligibility
    const filteredUnits = units.filter(unit => {
        const reason = [];
        if (unit.player !== currentPlayer) {
            reason.push("not current player");
            return false;
        }
        if (phase === "move") {
            if (unitsMoved.includes(Number(unit.id))) {
                reason.push("already moved");
                return false;
            }
            return true;
        }
        if (phase === "shoot") {
            if (unitsMoved.includes(Number(unit.id))) {
                reason.push("already shot");
                return false;
            }
            const enemies = units.filter(u2 => u2.player !== currentPlayer);
            const inRange = enemies.some(eu => Math.max(Math.abs(unit.col - eu.col), Math.abs(unit.row - eu.row)) <= unit.RNG_RNG);
            if (!inRange) {
                reason.push("no enemy in range");
                return false;
            }
            return true;
        }
        if (phase === "charge") {
            if (unitsCharged.includes(Number(unit.id))) {
                reason.push("already charged");
                return false;
            }
            const enemies = units.filter(u2 => u2.player !== currentPlayer);
            const isAdjacent = enemies.some(eu => Math.max(Math.abs(unit.col - eu.col), Math.abs(unit.row - eu.row)) === 1);
            if (isAdjacent) {
                reason.push("enemy adjacent");
                return false;
            }
            const inRange = enemies.some(eu => Math.max(Math.abs(unit.col - eu.col), Math.abs(unit.row - eu.row)) <= unit.MOVE);
            if (!inRange) {
                reason.push("no enemy in move range");
                return false;
            }
            return true;
        }
        if (phase === "combat") {
            if (unitsAttacked.includes(Number(unit.id)))
                return false;
            const enemies = units.filter(u2 => u2.player !== currentPlayer);
            const isAdjacent = enemies.some(eu => Math.max(Math.abs(unit.col - eu.col), Math.abs(unit.row - eu.row)) === 1);
            if (!isAdjacent)
                return false;
            return true;
        }
        return true;
    });
    // Print out which units are eligible, and reasons for exclusion
    units.forEach(unit => {
        if (filteredUnits.includes(unit)) {
            console.log(`[UnitSelector] Eligible for phase '${phase}':`, unit.name);
        }
        else {
            console.log(`[UnitSelector] NOT eligible for phase '${phase}':`, unit.name);
        }
    });
    return (_jsxs("div", { style: {
            display: "flex",
            flexDirection: "column",
            gap: "8px",
            background: "#222",
            border: "1px solid #555",
            borderRadius: "10px",
            padding: "12px",
            margin: "12px",
            color: "#fff",
            minWidth: "160px",
        }, children: [_jsx("b", { style: { marginBottom: 8 }, children: "Select your unit" }), filteredUnits.map(unit => (_jsxs("button", { onClick: () => {
                    console.log("UnitSelector click", unit.id, unitsMoved, unitsCharged, phase);
                    onSelect(Number(unit.id));
                }, disabled: (phase === "move" && unitsMoved.includes(Number(unit.id))) ||
                    (phase === "shoot" && unitsMoved.includes(Number(unit.id))) ||
                    (phase === "charge" && unitsCharged.includes(Number(unit.id))) ||
                    unit.player !== currentPlayer, style: {
                    background: unit.id === selectedUnitId ? "#1e90ff" : "#444",
                    color: "#fff",
                    border: "none",
                    borderRadius: "7px",
                    padding: "7px 11px",
                    fontWeight: unit.id === selectedUnitId ? 700 : 500,
                    cursor: "pointer",
                    outline: unit.id === selectedUnitId ? "2px solid #aee6ff" : "none",
                }, children: [_jsx("span", { style: { marginRight: 6, fontWeight: 700 }, children: unit.name }), _jsx("span", { style: { fontSize: 11, opacity: 0.7 }, children: unit.type })] }, unit.id)))] }));
}
