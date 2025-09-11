// frontend/src/components/BoardWithAPI.tsx
import React, { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import '../App.css';
import BoardPvp from './BoardPvp';
import { useEngineAPI } from '../hooks/useEngineAPI';
import { useGameConfig } from '../hooks/useGameConfig';
import { useAITurn } from '../hooks/useAITurn';
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
  
  // Detect game mode from URL
  const location = useLocation();
  const gameMode = location.pathname.includes('/pve') ? 'pve' : 
                   location.pathname.includes('/replay') ? 'training' : 'pvp';
  const isPvE = gameMode === 'pve';
  
  // Get board configuration for line of sight calculations
  const { gameConfig } = useGameConfig();
  
  // Track clicked (but not selected) units for blue highlighting
  const [clickedUnitId, setClickedUnitId] = useState<number | null>(null);
  
  // Track UnitStatusTable collapse states
  const [player0Collapsed, setPlayer0Collapsed] = useState(false);
  const [player1Collapsed, setPlayer1Collapsed] = useState(false);
  
  // Calculate available height for GameLog dynamically
  const [logAvailableHeight, setLogAvailableHeight] = useState(220);
  
  // Initialize AI turn processing for PvE mode
  const { isAIProcessing, processAITurn, aiError, clearAIError } = useAITurn({
    gameState: apiProps.gameState!,
    gameActions: {
      confirmMove: (unitId: number, destCol: number, destRow: number) => {
        // Map to engine API direct move action
        apiProps.onDirectMove && apiProps.onDirectMove(unitId, destCol, destRow);
      },
      handleShoot: (shooterId: number, targetId: number) => {
        // Engine API handles shooting through backend state - pass AI-selected targets
        console.debug('AI shoot action:', { shooterId, targetId });
        apiProps.onShoot && apiProps.onShoot(shooterId, targetId);
      },
      handleCharge: (unitId: number, targetId: number) => {
        // Engine API handles charging through backend state - zero-parameter trigger
        console.debug('AI charge action:', { unitId, targetId });
        apiProps.onCharge && apiProps.onCharge();
      },
      handleFightAttack: (attackerId: number, targetId: number) => {
        // Engine API handles fighting through backend state - zero-parameter trigger
        console.debug('AI fight action:', { attackerId, targetId });
        apiProps.onFightAttack && apiProps.onFightAttack();
      },
      addMovedUnit: (_unitId: number) => {
        // Engine API handles unit tracking internally
        console.debug('addMovedUnit: Engine API handles unit state tracking');
      },
      addChargedUnit: (_unitId: number) => {
        // Engine API handles unit tracking internally
        console.debug('addChargedUnit: Engine API handles unit state tracking');
      },
      addAttackedUnit: (_unitId: number) => {
        // Engine API handles unit tracking internally
        console.debug('addAttackedUnit: Engine API handles unit state tracking');
      },
    },
    currentPlayer: apiProps.gameState?.currentPlayer ?? 0,
    phase: apiProps.gameState?.phase ?? 'move',
    units: apiProps.gameState?.units ?? []
  });

  // AI Turn Processing Effect - Trigger AI when it's AI player's turn
  useEffect(() => {
    if (!apiProps.gameState) return;
    
    // Check if game is over by examining unit health
    const player0Alive = apiProps.gameState.units.some(u => u.player === 0 && (u.HP_CUR ?? u.HP_MAX) > 0);
    const player1Alive = apiProps.gameState.units.some(u => u.player === 1 && (u.HP_CUR ?? u.HP_MAX) > 0);
    const gameNotOver = player0Alive && player1Alive;
    
    if (isPvE && apiProps.gameState.currentPlayer === 1 && !isAIProcessing && gameNotOver) {
      // Small delay to ensure UI updates are complete
      const timer = setTimeout(() => {
        processAITurn();
      }, 1000);
      
      return () => clearTimeout(timer);
    }
  }, [isPvE, apiProps.gameState?.currentPlayer, apiProps.gameState?.phase, isAIProcessing, apiProps.gameState?.units, processAITurn]);

  // Calculate available height for GameLog dynamically
  useEffect(() => {
    // Wait for DOM to be fully rendered before measuring
    setTimeout(() => {
      const turnPhaseTracker = document.querySelector('.turn-phase-tracker-right');
      const allTables = document.querySelectorAll('.unit-status-table-container');
      const gameLogHeader = document.querySelector('.game-log__header') || document.querySelector('[class*="game-log"]');
      
      if (!turnPhaseTracker || allTables.length < 2 || !gameLogHeader) {
        setLogAvailableHeight(220);
        return;
      }
      
      const player0Table = allTables[0];
      const player1Table = allTables[1];
      
      // Get actual heights from DOM measurements
      const turnPhaseHeight = turnPhaseTracker.getBoundingClientRect().height;
      const player0Height = player0Table.getBoundingClientRect().height;
      const player1Height = player1Table.getBoundingClientRect().height;
      const gameLogHeaderHeight = gameLogHeader.getBoundingClientRect().height;
      
      // Calculate available space based purely on actual measurements
      const viewportHeight = window.innerHeight;
      const appContainer = document.querySelector('.app-container') || document.body;
      const appMargins = viewportHeight - appContainer.getBoundingClientRect().height;
      const usedSpace = turnPhaseHeight + player0Height + player1Height + gameLogHeaderHeight;
      const availableForLogEntries = viewportHeight - usedSpace - appMargins;
    
      const sampleLogEntry = document.querySelector('.game-log-entry');
      if (!sampleLogEntry) {
        setLogAvailableHeight(220);
        return;
      }
      sampleLogEntry.getBoundingClientRect().height;
      setLogAvailableHeight(availableForLogEntries);
    }, 100); // Wait 100ms for DOM to render
  }, [player0Collapsed, player1Collapsed, apiProps.gameState?.units, apiProps.gameState?.phase]);

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
          currentTurn={apiProps.gameState?.currentTurn ?? 1} 
          currentPhase={apiProps.gameState?.phase ?? 'move'}
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
          apiProps.gameState?.currentPlayer === 1 
            ? isAIProcessing 
              ? 'bg-purple-900 border border-purple-700' 
              : 'bg-purple-800 border border-purple-600'
            : 'bg-gray-800 border border-gray-600'
        }`}>
          <span className="text-sm font-medium text-white">
            {apiProps.gameState?.currentPlayer === 1 ? '🤖 AI Turn' : '👤 Your Turn'}
          </span>
          {apiProps.gameState?.currentPlayer === 1 && isAIProcessing && (
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
              <strong>🤖 AI Error:</strong> {aiError}
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
          units={apiProps.gameState?.units ?? []}
          player={0}
          selectedUnitId={apiProps.selectedUnitId ?? null}
          clickedUnitId={clickedUnitId}
          onSelectUnit={(unitId) => {
            apiProps.onSelectUnit(unitId);
            setClickedUnitId(null);
          }}
          gameMode={gameMode}
          onCollapseChange={setPlayer0Collapsed}
        />
      </ErrorBoundary>

      <ErrorBoundary fallback={<div>Failed to load player 1 status</div>}>
        <UnitStatusTable
          units={apiProps.gameState?.units ?? []}
          player={1}
          selectedUnitId={apiProps.selectedUnitId ?? null}
          clickedUnitId={clickedUnitId}
          onSelectUnit={(unitId) => {
            apiProps.onSelectUnit(unitId);
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
        targetPreview={apiProps.targetPreview ? {
          targetId: apiProps.targetPreview.targetId,
          shooterId: apiProps.targetPreview.shooterId,
          currentBlinkStep: (apiProps.targetPreview as any).currentBlinkStep || 0,
          totalBlinkSteps: (apiProps.targetPreview as any).totalBlinkSteps || 2,
          blinkTimer: (apiProps.targetPreview as any).blinkTimer || null,
          hitProbability: (apiProps.targetPreview as any).hitProbability || 0.5,
          woundProbability: (apiProps.targetPreview as any).woundProbability || 0.5,
          saveProbability: (apiProps.targetPreview as any).saveProbability || 0.5,
          overallProbability: (apiProps.targetPreview as any).overallProbability || 0.25
        } : null}
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
        onCancelTargetPreview={() => {
          const targetPreview = apiProps.targetPreview as any;
          if (targetPreview?.blinkTimer) {
            clearInterval(targetPreview.blinkTimer);
          }
          // Clear target preview in engine API
          console.log("🎯 Canceling target preview");
        }}
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