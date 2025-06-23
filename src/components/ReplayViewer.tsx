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

  return (
    <div>
      <Board
        units={current.units}
        selectedUnitId={current.acting_unit_idx}
        phase={current.phase}
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
        <b>Turn:</b> {current.turn} &nbsp;
        <b>Phase:</b> {current.phase} &nbsp;
        <b>Unit:</b> {current.acting_unit_idx} &nbsp;
        <b>Target:</b> {String(current.target_unit_idx)}
        <div>
          Step {step + 1} / {eventLog.length}
        </div>
      </div>
    </div>
  );
}
