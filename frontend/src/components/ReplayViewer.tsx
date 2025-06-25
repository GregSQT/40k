// frontend/src/components/ReplayViewer.tsx

import React, { useState, useEffect } from "react";
import Board from "@components/Board";

type ReplayViewerProps = {
  eventLog: any[];
  boardProps?: Record<string, any>;
  stepDelay?: number;
};

export default function ReplayViewer({ eventLog, boardProps = {}, stepDelay = 700 }: ReplayViewerProps) {
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!eventLog || eventLog.length === 0) return;
    if (step >= eventLog.length - 1) return;
    const id = setTimeout(() => setStep(s => s + 1), stepDelay);
    return () => clearTimeout(id);
  }, [step, eventLog, stepDelay]);

  if (!eventLog || eventLog.length === 0) return <div>No replay loaded</div>;
  const current = eventLog[step];

  // Check if this is the simple format (without units array)
  // If so, create mock units or show simplified replay
  if (!current.units && !current.acting_unit_idx) {
    return (
      <div>
        <div style={{ padding: "20px", color: "#aee6ff" }}>
          <h3>Simple Replay Format</h3>
          <div style={{ background: "#1a1a2e", padding: "15px", borderRadius: "8px", marginBottom: "10px" }}>
            <b>Turn:</b> {current.turn || 'N/A'} &nbsp;
            <b>Action:</b> {current.action || 'N/A'} &nbsp;
            <b>Reward:</b> {current.reward || 'N/A'} &nbsp;
            <b>AI Units Alive:</b> {current.ai_units_alive || 'N/A'} &nbsp;
            <b>Enemy Units Alive:</b> {current.enemy_units_alive || 'N/A'}
          </div>
          <div>
            <b>Game Over:</b> {current.game_over ? 'Yes' : 'No'} &nbsp;
            <b>Step:</b> {step + 1} / {eventLog.length}
          </div>
          <div style={{ marginTop: "15px" }}>
            <button 
              onClick={() => setStep(Math.max(0, step - 1))}
              style={{ marginRight: "10px", padding: "5px 10px" }}
            >
              Previous
            </button>
            <button 
              onClick={() => setStep(Math.min(eventLog.length - 1, step + 1))}
              style={{ padding: "5px 10px" }}
            >
              Next
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Check if current event has units, if not, try to create default units
  let unitsToShow = current.units;
  if (!unitsToShow) {
    // Create mock units based on the alive count if available
    unitsToShow = [];
    const aiUnitsAlive = current.ai_units_alive || 2;
    const enemyUnitsAlive = current.enemy_units_alive || 2;
    
    // Create AI units (player 1)
    for (let i = 0; i < aiUnitsAlive; i++) {
      unitsToShow.push({
        id: i + 3, // AI unit IDs typically start at 3
        name: `AI Unit ${i + 1}`,
        unit_type: "Intercessor",
        player: 1,
        col: 20 + i,
        row: 8 + i,
        hp: 3,
        hp_max: 3,
        alive: true,
        color: "#4CAF50"
      });
    }
    
    // Create enemy units (player 0)
    for (let i = 0; i < enemyUnitsAlive; i++) {
      unitsToShow.push({
        id: i + 1, // Enemy unit IDs typically start at 1
        name: `Enemy Unit ${i + 1}`,
        unit_type: "AssaultIntercessor",
        player: 0,
        col: 2 + i,
        row: 8 + i,
        hp: 4,
        hp_max: 4,
        alive: true,
        color: "#F44336"
      });
    }
  }

  return (
    <div>
      <Board
        units={unitsToShow}
        selectedUnitId={current.acting_unit_idx || null}
        phase={current.phase || "move"}
        mode="select"
        movePreview={null}
        attackPreview={null}
        onSelectUnit={() => {}}
        onStartMovePreview={() => {}}
        onStartAttackPreview={() => {}}
        onConfirmMove={() => {}}
        onCancelMove={() => {}}
        onShoot={() => {}}
        onCombatAttack={() => {}}
        onCharge={() => {}}
        unitsCharged={[]}
        unitsAttacked={[]}
        currentPlayer={1}
        unitsMoved={[]}
        onMoveCharger={() => {}}
        onCancelCharge={() => {}}
        onValidateCharge={() => {}}
        {...boardProps}
      />
      <div style={{ marginTop: 16, color: "#aee6ff" }}>
        <b>Turn:</b> {current.turn || 'N/A'} &nbsp;
        <b>Phase:</b> {current.phase || 'N/A'} &nbsp;
        <b>Unit:</b> {current.acting_unit_idx || 'N/A'} &nbsp;
        <b>Target:</b> {String(current.target_unit_idx || 'N/A')}
        <div>
          Step {step + 1} / {eventLog.length}
        </div>
        {current.reward !== undefined && (
          <div>
            <b>Reward:</b> {current.reward} &nbsp;
            <b>AI Alive:</b> {current.ai_units_alive} &nbsp;
            <b>Enemy Alive:</b> {current.enemy_units_alive}
          </div>
        )}
      </div>
    </div>
  );
}