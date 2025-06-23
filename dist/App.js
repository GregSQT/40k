import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// frontend/src/App.tsx
import React, { useState, useEffect } from "react";
import Board from "@components/Board";
import UnitSelector from "@components/UnitSelector";
import initialUnits from "@data/Scenario";
import { fetchAiAction } from "./ai/ai";
export default function App() {
    const [units, setUnits] = useState(initialUnits);
    const [currentPlayer, setCurrentPlayer] = useState(0);
    const [selectedUnitId, setSelectedUnitId] = useState(null);
    const [movePreview, setMovePreview] = useState(null);
    const [attackPreview, setAttackPreview] = useState(null);
    const [unitsMoved, setUnitsMoved] = useState([]);
    const [unitsCharged, setUnitsCharged] = useState([]);
    const [unitsAttacked, setUnitsAttacked] = useState([]);
    const [mode, setMode] = useState("select");
    const [phase, setPhase] = useState("move");
    // ==============================
    // ===== AI PLAYER INSERTION ====
    // ==============================
    useEffect(() => {
        // Only act if it's the AI's turn (Player 2: currentPlayer === 1)
        if (currentPlayer !== 1)
            return;
        async function doAiPhase() {
            switch (phase) {
                case "move":
                    await runAiMovePhase();
                    break;
                case "shoot":
                    await runAiShootPhase();
                    break;
                case "charge":
                    await runAiChargePhase();
                    break;
                case "combat":
                    await runAiCombatPhase();
                    break;
                default:
                    break;
            }
        }
        doAiPhase();
        // eslint-disable-next-line
    }, [currentPlayer, phase, units, unitsMoved, unitsAttacked, unitsCharged]);
    // --- MOVE PHASE ---
    async function runAiMovePhase() {
        const aiUnits = units.filter(u => u.player === 1 && !unitsMoved.includes(u.id));
        for (const unit of aiUnits) {
            const gameState = {
                units: units.map(u => ({
                    id: u.id,
                    player: u.player,
                    col: u.col,
                    row: u.row,
                    CUR_HP: u.CUR_HP,
                    MOVE: u.MOVE,
                    RNG_RNG: u.RNG_RNG,
                    RNG_DMG: u.RNG_DMG,
                    CC_DMG: u.CC_DMG,
                }))
            };
            const result = await fetchAiAction(gameState);
            // Handle move action with target cell
            if (result.action === "move" && result.unitId === unit.id) {
                setUnits(prev => prev.map(u => u.id === result.unitId
                    ? { ...u, col: result.destCol, row: result.destRow }
                    : u));
                setUnitsMoved(prev => prev.includes(unit.id) ? prev : [...prev, unit.id]);
            }
            // --- NEW LOGIC: Move away but at RNG_RNG distance ---
            else if (result.action === "moveAwayToRngRng" && result.unitId === unit.id) {
                setUnits(prev => prev.map(u => u.id === result.unitId
                    ? { ...u, col: result.destCol, row: result.destRow }
                    : u));
                setUnitsMoved(prev => prev.includes(unit.id) ? prev : [...prev, unit.id]);
            }
            // Handle skip (unchanged)
            else if (result.action === "skip" && result.unitId === unit.id) {
                setUnitsMoved(prev => prev.includes(unit.id) ? prev : [...prev, unit.id]);
            }
            await new Promise(r => setTimeout(r, 180));
        }
    }
    // --- SHOOTING PHASE ---
    async function runAiShootPhase() {
        const aiUnits = units.filter(u => u.player === 1 && !unitsMoved.includes(u.id));
        for (const unit of aiUnits) {
            const gameState = {
                units: units.map(u => ({
                    id: u.id,
                    player: u.player,
                    col: u.col,
                    row: u.row,
                    CUR_HP: u.CUR_HP,
                    MOVE: u.MOVE,
                    RNG_RNG: u.RNG_RNG,
                    RNG_DMG: u.RNG_DMG,
                    CC_DMG: u.CC_DMG,
                }))
            };
            const result = await fetchAiAction(gameState);
            // Handle shoot action with target unit
            if (result.action === "shoot" && result.unitId === unit.id && typeof result.targetId === "number") {
                handleShoot(result.unitId, result.targetId);
                setUnitsMoved(prev => prev.includes(unit.id) ? prev : [...prev, unit.id]);
            }
            else if (result.action === "skip" && result.unitId === unit.id) {
                setUnitsMoved(prev => prev.includes(unit.id) ? prev : [...prev, unit.id]);
            }
            await new Promise(r => setTimeout(r, 180));
        }
    }
    // --- CHARGE PHASE ---
    async function runAiChargePhase() {
        const aiUnits = units.filter(u => u.player === 1 && !unitsCharged.includes(u.id));
        for (const unit of aiUnits) {
            const gameState = {
                units: units.map(u => ({
                    id: u.id,
                    player: u.player,
                    col: u.col,
                    row: u.row,
                    CUR_HP: u.CUR_HP,
                    MOVE: u.MOVE,
                    RNG_RNG: u.RNG_RNG,
                    RNG_DMG: u.RNG_DMG,
                    CC_DMG: u.CC_DMG,
                }))
            };
            const result = await fetchAiAction(gameState);
            // Handle charge action with target unit
            if (result.action === "charge" && result.unitId === unit.id && typeof result.targetId === "number") {
                handleCharge(result.unitId, result.targetId);
                setUnitsCharged(prev => prev.includes(unit.id) ? prev : [...prev, unit.id]);
            }
            else if (result.action === "skip" && result.unitId === unit.id) {
                setUnitsCharged(prev => prev.includes(unit.id) ? prev : [...prev, unit.id]);
            }
            await new Promise(r => setTimeout(r, 180));
        }
    }
    // --- COMBAT PHASE ---
    async function runAiCombatPhase() {
        const aiUnits = units.filter(u => u.player === 1 && !unitsAttacked.includes(u.id));
        for (const unit of aiUnits) {
            const gameState = {
                units: units.map(u => ({
                    id: u.id,
                    player: u.player,
                    col: u.col,
                    row: u.row,
                    CUR_HP: u.CUR_HP,
                    MOVE: u.MOVE,
                    RNG_RNG: u.RNG_RNG,
                    RNG_DMG: u.RNG_DMG,
                    CC_DMG: u.CC_DMG,
                }))
            };
            const result = await fetchAiAction(gameState);
            // Handle attack action with target unit
            if (result.action === "attack" && result.unitId === unit.id && typeof result.targetId === "number") {
                handleCombatAttack(result.unitId, result.targetId);
                setUnitsAttacked(prev => prev.includes(unit.id) ? prev : [...prev, unit.id]);
            }
            else if (result.action === "skip" && result.unitId === unit.id) {
                setUnitsAttacked(prev => prev.includes(unit.id) ? prev : [...prev, unit.id]);
            }
            await new Promise(r => setTimeout(r, 180));
        }
    }
    // ==============================
    // ===== END AI PLAYER CODE =====
    // ==============================
    // Handles selection with move/attack preview and block logic
    function handleSelectUnit(unitId) {
        if (unitId === null) {
            setSelectedUnitId(null);
            setMovePreview(null);
            setAttackPreview(null);
            setMode("select");
            return;
        }
        unitId = Number(unitId);
        const unit = units.find(u => u.id === unitId);
        // Allow selection in combat phase regardless of unitsMoved!
        const isCombat = phase === "combat";
        const blocked = !unit || unit.player !== currentPlayer || (!isCombat && unitsMoved.includes(unitId));
        if (blocked)
            return;
        // --- MOVEMENT PHASE: second click on already selected unit marks it as "moved" and deselects
        if (phase === "move" && selectedUnitId === unitId) {
            setUnitsMoved(prev => prev.includes(unitId) ? prev : [...prev, unitId]);
            setSelectedUnitId(null);
            setMovePreview(null);
            setMode("select");
            return;
        }
        // ---- SHOOTING PHASE ----
        if (phase === "shoot") {
            setSelectedUnitId(unitId);
            setMovePreview(null);
            setAttackPreview({ unitId, col: unit.col, row: unit.row });
            setMode("attackPreview");
            return;
        }
        // ---- MOVE PHASE: normal selection ----
        setSelectedUnitId(unitId);
        setMovePreview(null);
        setAttackPreview(null);
        setMode("select");
    }
    // Start move preview if valid
    function handleStartMovePreview(unitId, col, row) {
        unitId = Number(unitId);
        col = Number(col);
        row = Number(row);
        const unit = units.find(u => u.id === unitId);
        if (!unit || unit.player !== currentPlayer || unitsMoved.includes(unitId))
            return;
        setMovePreview({ unitId, destCol: col, destRow: row });
        setMode("movePreview");
        setAttackPreview(null);
    }
    // Start attack preview (used by Board)
    function handleStartAttackPreview(unitId, col, row) {
        setAttackPreview({ unitId, col, row });
        setMode("attackPreview");
        setMovePreview(null);
    }
    // Confirm a move or an attack
    function handleConfirmMove() {
        let movedUnitId = null;
        if (mode === "movePreview" && movePreview) {
            setUnits(prev => prev.map(u => u.id === movePreview.unitId
                ? { ...u, col: movePreview.destCol, row: movePreview.destRow }
                : u));
            movedUnitId = movePreview.unitId;
        }
        else if (mode === "attackPreview" && attackPreview) {
            movedUnitId = attackPreview.unitId;
        }
        if (movedUnitId !== null) {
            setUnitsMoved(prev => prev.includes(movedUnitId) ? prev : [...prev, movedUnitId]);
        }
        setMovePreview(null);
        setAttackPreview(null);
        setSelectedUnitId(null);
        setMode("select");
    }
    // Cancel preview
    function handleCancelMove() {
        setMovePreview(null);
        setAttackPreview(null);
        setMode("select");
    }
    // === PATCH: Shooting logic ===
    function handleShoot(shooterId, targetId) {
        const shooter = units.find(u => u.id === shooterId);
        const target = units.find(u => u.id === targetId);
        if (!shooter || !target)
            return;
        // Apply damage
        const newHP = (target.CUR_HP ?? target.HP_MAX) - (shooter.RNG_DMG ?? 1);
        setUnits(prev => prev
            .map(u => u.id === targetId
            ? { ...u, CUR_HP: newHP }
            : u)
            .filter(u => u.id !== targetId || newHP > 0) // Remove dead unit
        );
        // Mark shooter as "has shot"
        setUnitsMoved(prev => prev.includes(shooterId) ? prev : [...prev, shooterId]);
        // Exit attack preview for this shooter
        setAttackPreview(null);
        setSelectedUnitId(null);
        setMode("select");
    }
    // === PATCH: Combat logic (melee attack) ===
    function handleCombatAttack(attackerId, targetId) {
        // If targetId is null, skip attack but mark attacker as "has attacked"
        if (targetId === null) {
            setUnitsAttacked(prev => prev.includes(attackerId) ? prev : [...prev, attackerId]);
            setSelectedUnitId(null);
            setMode("select");
            return;
        }
        const attacker = units.find(u => u.id === attackerId);
        const target = units.find(u => u.id === targetId);
        if (!attacker || !target)
            return;
        if (unitsAttacked.includes(attackerId))
            return;
        // Must be adjacent
        const dist = Math.max(Math.abs(attacker.col - target.col), Math.abs(attacker.row - target.row));
        if (dist !== 1)
            return;
        // Apply CC_DMG (close combat damage)
        const newHP = (target.CUR_HP ?? target.HP_MAX) - (attacker.CC_DMG ?? 1);
        setUnits(prev => prev
            .map(u => u.id === targetId
            ? { ...u, CUR_HP: newHP }
            : u)
            .filter(u => u.id !== targetId || newHP > 0));
        setUnitsAttacked(prev => prev.includes(attackerId) ? prev : [...prev, attackerId]);
        setSelectedUnitId(null);
        setMode("select");
    }
    // === PATCH: Charging logic (visuals only for now) ===
    function handleCharge(chargerId, targetId) {
        // For now, just log and mark as charged. You can add charge resolution later.
        console.log(`Charge! Unit ${chargerId} charges unit ${targetId}`);
        setUnitsCharged(prev => prev.includes(chargerId) ? prev : [...prev, chargerId]);
        setSelectedUnitId(null);
        setMode("select");
    }
    // ---- CHARGE: move charger to orange cell ----
    function handleMoveCharger(chargerId, destCol, destRow) {
        setUnits(prev => prev.map(u => u.id === chargerId
            ? { ...u, col: destCol, row: destRow }
            : u));
        setMode("chargePreview");
        // Do not mark as charged yet, wait for validate (next click on the unit)
    }
    // ---- CHARGE: cancel charge preview (right click on charger) ----
    function handleCancelCharge() {
        setMode("select");
        setMovePreview(null);
        setAttackPreview(null);
    }
    // ---- CHARGE: validate charge (left click on charger after moving) ----
    function handleValidateCharge(chargerId) {
        setUnitsCharged(prev => prev.includes(chargerId) ? prev : [...prev, chargerId]);
        setSelectedUnitId(null);
        setMode("select");
    }
    // Used for selecting eligible charger (charge phase)
    function handleSelectCharger(unitId) {
        console.log("handleSelectCharger called", unitId, phase, mode);
        if (unitId === null) {
            setSelectedUnitId(null);
            setMode("select");
            return;
        }
        unitId = Number(unitId);
        const unit = units.find(u => u.id === unitId);
        if (!unit || unit.player !== currentPlayer || unitsCharged.includes(unitId))
            return;
        // Eligibility: no enemy adjacent, at least one enemy within MOVE
        const enemyUnits = units.filter(u2 => u2.player !== currentPlayer);
        const isAdjacent = enemyUnits.some(eu => Math.max(Math.abs(unit.col - eu.col), Math.abs(unit.row - eu.row)) === 1);
        const inRange = enemyUnits.some(eu => Math.max(Math.abs(unit.col - eu.col), Math.abs(unit.row - eu.row)) <= unit.MOVE);
        if (isAdjacent || !inRange)
            return;
        setSelectedUnitId(unitId);
        setMode("chargePreview");
    }
    // --- PHASE SYSTEM: move -> shoot -> charge -> combat -> next player ---
    React.useEffect(() => {
        const playerUnitIds = units.filter(u => u.player === currentPlayer).map(u => Number(u.id));
        if (phase === "move" && playerUnitIds.length > 0 && playerUnitIds.every(id => unitsMoved.includes(id))) {
            const timeout = setTimeout(() => {
                setPhase("shoot");
                setUnitsMoved([]);
                setSelectedUnitId(null);
            }, 300);
            return () => clearTimeout(timeout);
        }
        if (phase === "shoot") {
            console.log(`Shoot phase: current player ${currentPlayer}`);
            const playerUnits = units.filter(u => u.player === currentPlayer);
            const enemyUnits = units.filter(u => u.player !== currentPlayer);
            const shootableIds = playerUnits.filter(u => !unitsMoved.includes(u.id) &&
                enemyUnits.some(eu => Math.max(Math.abs(u.col - eu.col), Math.abs(u.row - eu.row)) <= u.RNG_RNG)).map(u => u.id);
            if (shootableIds.length === 0 && playerUnits.length > 0) {
                const timeout = setTimeout(() => {
                    setPhase("charge");
                    setUnitsCharged([]);
                    setSelectedUnitId(null);
                }, 300);
                return () => clearTimeout(timeout);
            }
        }
        if (phase === "charge") {
            console.log(`Charge phase: current player ${currentPlayer}`);
            const playerUnits = units.filter(u => u.player === currentPlayer);
            const enemyUnits = units.filter(u => u.player !== currentPlayer);
            function isAdjacent(unitA, unitB) {
                return Math.max(Math.abs(unitA.col - unitB.col), Math.abs(unitA.row - unitB.row)) === 1;
            }
            const chargeableIds = playerUnits.filter(u => {
                if (unitsCharged.includes(u.id))
                    return false;
                if (enemyUnits.some(eu => isAdjacent(u, eu)))
                    return false;
                return enemyUnits.some(eu => Math.max(Math.abs(u.col - eu.col), Math.abs(u.row - eu.row)) <= u.MOVE);
            }).map(u => u.id);
            if (chargeableIds.length === 0 && playerUnits.length > 0) {
                // All units have charged or can't, go to COMBAT phase
                const timeout = setTimeout(() => {
                    setPhase("combat");
                    setSelectedUnitId(null);
                    setUnitsAttacked([]);
                    setMode("select"); // <<<--- THIS LINE!
                }, 300);
                return () => clearTimeout(timeout);
            }
        }
        // After all eligible units have attacked in combat, end turn
        if (phase === "combat") {
            console.log(`Combat phase: current player ${currentPlayer}`);
            const playerUnits = units.filter(u => u.player === currentPlayer);
            const enemyUnits = units.filter(u => u.player !== currentPlayer);
            // Eligible if: not already attacked, has enemy adjacent
            const eligibleIds = playerUnits.filter(u => !unitsAttacked.includes(u.id) &&
                enemyUnits.some(eu => Math.max(Math.abs(u.col - eu.col), Math.abs(u.row - eu.row)) === 1)).map(u => u.id);
            if (eligibleIds.length === 0 && playerUnits.length > 0) {
                // End turn: switch player and return to move phase
                const timeout = setTimeout(() => {
                    setCurrentPlayer(p => (p === 0 ? 1 : 0));
                    setPhase("move");
                    setUnitsMoved([]);
                    setUnitsCharged([]);
                    setUnitsAttacked([]);
                    setSelectedUnitId(null);
                }, 300);
                return () => clearTimeout(timeout);
            }
        }
    }, [unitsMoved, unitsCharged, unitsAttacked, currentPlayer, units, phase]);
    return (_jsxs("div", { style: { display: "flex", flexDirection: "row", width: "100vw", height: "100vh", background: "#222" }, children: [_jsx(UnitSelector, { units: units, currentPlayer: currentPlayer, selectedUnitId: selectedUnitId, onSelect: phase === "charge" ? handleSelectCharger : handleSelectUnit, unitsMoved: unitsMoved, unitsCharged: unitsCharged, unitsAttacked: unitsAttacked, phase: phase }), _jsxs("div", { style: {
                    flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center"
                }, children: [_jsx("h1", { style: {
                            color: "#aee6ff", fontFamily: "Arial, sans-serif",
                            fontWeight: 700, fontSize: "2rem", margin: "24px 0 12px 0",
                            letterSpacing: "0.04em"
                        }, children: "WH40K Tactics RL Demo" }), _jsx("div", { style: {
                            flex: 1, width: "100%", display: "flex",
                            justifyContent: "center", alignItems: "center"
                        }, children: _jsx(Board, { units: units, selectedUnitId: selectedUnitId, phase: phase, mode: mode, movePreview: movePreview, attackPreview: attackPreview, onSelectUnit: phase === "charge" ? handleSelectCharger : handleSelectUnit, onStartMovePreview: handleStartMovePreview, onStartAttackPreview: handleStartAttackPreview, onConfirmMove: handleConfirmMove, onCancelMove: handleCancelMove, onShoot: handleShoot, onCombatAttack: handleCombatAttack, onCharge: handleCharge, unitsCharged: unitsCharged, unitsAttacked: unitsAttacked, currentPlayer: currentPlayer, unitsMoved: unitsMoved, onMoveCharger: handleMoveCharger, onCancelCharge: handleCancelCharge, onValidateCharge: handleValidateCharge }) }), _jsxs("div", { style: { marginTop: 20 }, children: [_jsx("b", { style: { color: "#fff" }, children: "Current player:" }), " ", _jsx("span", { style: { color: "#aee6ff" }, children: currentPlayer === 0 ? "Player 1" : "Player 2" }), _jsx("br", {}), _jsx("b", { style: { color: "#fff" }, children: "Units moved:" }), " ", _jsx("span", { style: { color: "#aee6ff" }, children: units
                                    .filter(u => u.player === currentPlayer && unitsMoved.includes(Number(u.id)))
                                    .map(u => u.name)
                                    .join(", ") || "None" })] })] })] }));
}
