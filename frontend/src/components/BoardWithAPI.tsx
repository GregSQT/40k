// frontend/src/components/BoardWithAPI.tsx
import React from 'react';
import BoardPvp from './BoardPvp';
import { useEngineAPI } from '../hooks/useEngineAPI';

export const BoardWithAPI: React.FC = () => {
  console.log('🚨 ABOUT TO CALL useEngineAPI');
  const apiProps = useEngineAPI();
  console.log('🚨 useEngineAPI returned:', apiProps);

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
      {/* Game Status */}
      <div style={{ 
        marginBottom: '20px', 
        padding: '15px', 
        background: '#1f2937', 
        borderRadius: '8px',
        color: 'white',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <div>
          <h3 style={{ margin: '0 0 5px 0' }}>W40K Engine - Live Board</h3>
          <div>
            Turn: {apiProps.gameState?.currentTurn} | 
            Player: {apiProps.currentPlayer} | 
            Phase: {apiProps.phase} | 
            Steps: {apiProps.gameState?.episode_steps}
          </div>
        </div>
        <div style={{ 
          padding: '8px 12px', 
          background: '#065f46', 
          borderRadius: '4px',
          fontSize: '14px'
        }}>
          AI_TURN.md Compliant
        </div>
      </div>

      {/* Board */}
      <BoardPvp
        units={apiProps.units}
        selectedUnitId={apiProps.selectedUnitId}
        eligibleUnitIds={apiProps.eligibleUnitIds}
        mode={apiProps.mode}
        movePreview={apiProps.movePreview}
        attackPreview={apiProps.attackPreview || null}
        onSelectUnit={apiProps.onSelectUnit}
        onStartMovePreview={apiProps.onStartMovePreview}
        onDirectMove={apiProps.onDirectMove}
        onStartAttackPreview={apiProps.onStartAttackPreview}
        onConfirmMove={apiProps.onConfirmMove}
        onCancelMove={apiProps.onCancelMove}
        onShoot={apiProps.onShoot}
        onCombatAttack={apiProps.onCombatAttack}
        currentPlayer={apiProps.currentPlayer}
        unitsMoved={apiProps.unitsMoved}
        unitsCharged={apiProps.unitsCharged}
        unitsAttacked={apiProps.unitsAttacked}
        unitsFled={apiProps.unitsFled}
        phase={apiProps.phase}
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