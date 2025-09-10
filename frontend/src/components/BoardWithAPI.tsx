// frontend/src/components/BoardWithAPI.tsx
import React from 'react';
import BoardPvp from './BoardPvp';
import { useEngineAPI } from '../hooks/useEngineAPI';
import SharedLayout from './SharedLayout';
import { ErrorBoundary } from './ErrorBoundary';
import { UnitStatusTable } from './UnitStatusTable';
import { GameLog } from './GameLog';
import { TurnPhaseTracker } from './TurnPhaseTracker';
import { useGameLog } from '../hooks/useGameLog';
import type { PlayerId } from '../types';

export const BoardWithAPI: React.FC = () => {
  const apiProps = useEngineAPI();
  const gameLog = useGameLog();

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

  const rightColumnContent = (
      <>
        {gameConfig ? (
          <TurnPhaseTracker 
            currentTurn={gameState.currentTurn ?? 1} 
            currentPhase={gameState.phase}
            phases={["move", "shoot", "charge", "fight"]}
            maxTurns={(() => {
            if (!gameConfig?.game_rules?.max_turns) {
              throw new Error(`max_turns not found in game configuration. Config structure: ${JSON.stringify(Object.keys(gameConfig || {}))}. Expected: gameConfig.game_rules.max_turns`);
            }
            return gameConfig.game_rules.max_turns;
          })()}
            className="turn-phase-tracker-right"
          />
        ) : (
          <div className="turn-phase-tracker-right">Loading game configuration...</div>
        )}
        {/* AI Status Display */}
        {isPvE && (
          <div className={`flex items-center gap-2 px-3 py-2 rounded mb-2 ${
            gameState.currentPlayer === 1 
              ? isAIProcessing 
                ? 'bg-purple-900 border border-purple-700' 
                : 'bg-purple-800 border border-purple-600'
              : 'bg-gray-800 border border-gray-600'
          }`}>
            <span className="text-sm font-medium text-white">
              {gameState.currentPlayer === 1 ? 'ðŸ¤– AI Turn' : 'ðŸ‘¤ Your Turn'}
            </span>
            {gameState.currentPlayer === 1 && isAIProcessing && (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-purple-300"></div>
                <span className="text-purple-200 text-sm">AI thinking...</span>
              </>
            )}
          </div>
        )}
  
        {/* AI Error Display */}
        {aiError && (
          <div className="bg-red-900 border border-red-700 rounded p-3 mb-2">
            <div className="flex items-center justify-between">
              <div className="text-red-100 text-sm">
                <strong>ðŸ¤– AI Error:</strong> {aiError}
              </div>
              <button
                onClick={clearAIError}
                className="text-red-300 hover:text-red-100 ml-2"
              >
              </button>
            </div>
          </div>
        )}
  
        <ErrorBoundary fallback={<div>Failed to load player 0 status</div>}>
          <UnitStatusTable
            units={gameState.units}
            player={0}
            selectedUnitId={gameState.selectedUnitId ?? null}
            clickedUnitId={clickedUnitId}
            onSelectUnit={(unitId) => {
              gameActions.selectUnit(unitId);
              setClickedUnitId(null);
            }}
            gameMode={gameMode}
            onCollapseChange={setPlayer0Collapsed}
          />
        </ErrorBoundary>
  
        <ErrorBoundary fallback={<div>Failed to load player 1 status</div>}>
          <UnitStatusTable
            units={gameState.units}
            player={1}
            selectedUnitId={gameState.selectedUnitId ?? null}
            clickedUnitId={clickedUnitId}
            onSelectUnit={(unitId) => {
              gameActions.selectUnit(unitId);
              setClickedUnitId(null);
            }}
            gameMode={gameMode}
            onCollapseChange={setPlayer1Collapsed}
          />
        </ErrorBoundary>
  
        {/* Game Log Component */}
        <ErrorBoundary fallback={<div>Failed to load game log</div>}>
          <GameLog 
            events={gameLog.events}
            getElapsedTime={gameLog.getElapsedTime}
            availableHeight={logAvailableHeight}
          />
        </ErrorBoundary>
      </>
    );

  return (
    <SharedLayout rightColumnContent={rightColumnContent}>
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
    </SharedLayout>
  );
};