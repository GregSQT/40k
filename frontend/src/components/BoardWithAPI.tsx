// frontend/src/components/BoardWithAPI.tsx
import React from 'react';
import BoardPvp from './BoardPvp';
import { useEngineAPI } from '../hooks/useEngineAPI';
import type { PlayerId } from '../types';

export const BoardWithAPI: React.FC = () => {
  const apiProps = useEngineAPI();

  if (apiProps.loading) {
    return (
      <div style={{ 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'center', 
        height: '600px',
        background: '#1f2937',
        borderRadius: '8px',
        color: 'white',
        fontSize: '18px'
      }}>
        Starting W40K Engine Game...
      </div>
    );
  }

  if (apiProps.error) {
    return (
      <div style={{ 
        display: 'flex', 
        flexDirection: 'column',
        alignItems: 'center', 
        justifyContent: 'center', 
        height: '600px',
        background: '#7f1d1d',
        borderRadius: '8px',
        color: '#fecaca',
        fontSize: '18px',
        padding: '20px'
      }}>
        <div>Error: {apiProps.error}</div>
        <button 
          onClick={() => window.location.reload()} 
          style={{
            marginTop: '10px',
            padding: '10px 20px',
            backgroundColor: '#dc2626',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer'
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div style={{ padding: '20px' }}>
      {/* Board */}
      <BoardPvp
        units={apiProps.units}
        selectedUnitId={apiProps.selectedUnitId}
        eligibleUnitIds={apiProps.eligibleUnitIds}
        mode={apiProps.mode}
        movePreview={apiProps.movePreview}
        attackPreview={apiProps.attackPreview || null}
        onSelectUnit={apiProps.onSelectUnit}
        onSkipUnit={apiProps.onSkipUnit}
        onStartMovePreview={apiProps.onStartMovePreview}
        onDirectMove={apiProps.onDirectMove}
        onStartAttackPreview={apiProps.onStartAttackPreview}
        onConfirmMove={apiProps.onConfirmMove}
        onCancelMove={apiProps.onCancelMove}
        onShoot={apiProps.onShoot}
        onSkipShoot={apiProps.onSkipShoot}
        onStartTargetPreview={apiProps.onStartTargetPreview}
        onFightAttack={apiProps.onFightAttack}
        currentPlayer={apiProps.currentPlayer as PlayerId}
        unitsMoved={apiProps.unitsMoved}
        unitsCharged={apiProps.unitsCharged}
        unitsAttacked={apiProps.unitsAttacked}
        unitsFled={apiProps.unitsFled}
        phase={apiProps.phase as "move" | "shoot" | "charge" | "fight"}
        onCharge={apiProps.onCharge}
        onMoveCharger={apiProps.onMoveCharger}
        onCancelCharge={apiProps.onCancelCharge}
        onValidateCharge={apiProps.onValidateCharge}
        onLogChargeRoll={apiProps.onLogChargeRoll}
        gameState={apiProps.gameState!}
        getChargeDestinations={apiProps.getChargeDestinations}
      />
    </div>
  );
};