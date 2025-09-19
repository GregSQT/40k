// frontend/src/components/BoardWithAPI.tsx
import React, { useState, useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import '../App.css';
import BoardPvp from './BoardPvp';
import { useEngineAPI } from '../hooks/useEngineAPI';
import { useGameConfig } from '../hooks/useGameConfig';
import SharedLayout from './SharedLayout';
import { ErrorBoundary } from './ErrorBoundary';
import { UnitStatusTable } from './UnitStatusTable';
import { GameLog } from './GameLog';
import { TurnPhaseTracker } from './TurnPhaseTracker';
import { useGameLog } from '../hooks/useGameLog';
import type { PlayerId } from '../types';

export const BoardWithAPI: React.FC = () => {
  const apiProps = useEngineAPI();
  const gameLog = useGameLog(apiProps.gameState?.currentTurn ?? 1);
  
  // Detect game mode from URL
  const location = useLocation();
  const gameMode = location.pathname.includes('/pve') ? 'pve' : 
                   location.pathname.includes('/replay') ? 'training' :
                   (location.pathname === '/game' && location.search.includes('mode=pve')) ? 'pve' : 'pvp';
  const isPvE = gameMode === 'pve' || window.location.search.includes('mode=pve') || apiProps.gameState?.pve_mode === true;
  
  // Get board configuration for line of sight calculations
  const { gameConfig } = useGameConfig();
  
  // Track clicked (but not selected) units for blue highlighting
  const [clickedUnitId, setClickedUnitId] = useState<number | null>(null);
  
  // Track hex coordinate display toggle
  const [showHexCoordinates, setShowHexCoordinates] = useState<boolean>(false);
  
  // Track UnitStatusTable collapse states
  const [player0Collapsed, setPlayer0Collapsed] = useState(false);
  const [player1Collapsed, setPlayer1Collapsed] = useState(false);
  
  // Calculate available height for GameLog dynamically
  const [logAvailableHeight, setLogAvailableHeight] = useState(220);
  
  // Track AI processing with ref to avoid re-render loops
  const isAIProcessingRef = useRef(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [lastProcessedTurn, setLastProcessedTurn] = useState<string>('');
  
  const clearAIError = () => setAiError(null);

  // AI Turn Processing Effect - Trigger AI when it's AI player's turn and has eligible units
  useEffect(() => {
    if (!apiProps.gameState) return;
    
    // Check if in PvE mode
    const isPvEMode = apiProps.gameState.pve_mode || isPvE;
    
    // Check if game is over by examining unit health
    const player0Alive = apiProps.gameState.units.some(u => u.player === 0 && (u.HP_CUR ?? u.HP_MAX) > 0);
    const player1Alive = apiProps.gameState.units.some(u => u.player === 1 && (u.HP_CUR ?? u.HP_MAX) > 0);
    const gameNotOver = player0Alive && player1Alive;
    
    // CRITICAL: Check if AI has eligible units in current phase
    // Use simple heuristic instead of missing activation pools
    const currentPhase = apiProps.gameState.phase;
    let hasEligibleAIUnits = false;
    
    if (currentPhase === 'move') {
      // Check if any AI units haven't moved yet
      hasEligibleAIUnits = apiProps.gameState.units.some(unit => 
        unit.player === 1 && 
        (unit.HP_CUR ?? unit.HP_MAX) > 0 && 
        !apiProps.unitsMoved.includes(typeof unit.id === 'string' ? parseInt(unit.id) : unit.id)
      );
    } else if (currentPhase === 'shoot') {
      // Trust the backend eligibility - if there are any AI units eligible, let the backend handle it
      hasEligibleAIUnits = apiProps.eligibleUnitIds.some(unitId => {
        const unit = apiProps.gameState.units.find(u => (typeof u.id === 'string' ? parseInt(u.id) : u.id) === unitId);
        return unit && unit.player === 1;
      });
    } else if (currentPhase === 'charge') {
      // Check if any AI units can charge
      hasEligibleAIUnits = apiProps.gameState.units.some(unit => 
        unit.player === 1 && 
        (unit.HP_CUR ?? unit.HP_MAX) > 0 && 
        !apiProps.unitsCharged.includes(typeof unit.id === 'string' ? parseInt(unit.id) : unit.id)
      );
    } else if (currentPhase === 'fight') {
      // Check if any AI units can fight
      hasEligibleAIUnits = apiProps.gameState.units.some(unit => 
        unit.player === 1 && 
        (unit.HP_CUR ?? unit.HP_MAX) > 0 && 
        !apiProps.unitsAttacked.includes(typeof unit.id === 'string' ? parseInt(unit.id) : unit.id)
      );
    }
    
    const turnKey = `${apiProps.gameState.currentPlayer}-${currentPhase}-${apiProps.gameState.currentTurn || 1}`;
    const shouldTriggerAI = isPvEMode && 
                           apiProps.gameState.currentPlayer === 1 && 
                           !isAIProcessingRef.current && 
                           gameNotOver && 
                           hasEligibleAIUnits &&
                           lastProcessedTurn !== turnKey;
    
    if (shouldTriggerAI) {
      console.log(`Triggering AI turn for Player 1 (AI) - Phase: ${currentPhase}, Eligible AI units: ${hasEligibleAIUnits}`);
      isAIProcessingRef.current = true;
      setLastProcessedTurn(turnKey);
      
      // Small delay to ensure UI updates are complete
      setTimeout(async () => {
        console.log('Timer fired, checking executeAITurn:', typeof apiProps.executeAITurn);
        try {
          if (apiProps.executeAITurn) {
            console.log('Calling executeAITurn...');
            await apiProps.executeAITurn();
            console.log('AI turn completed');
          } else {
            console.error('executeAITurn function not available, type:', typeof apiProps.executeAITurn);
            setAiError('AI function not available');
          }
        } catch (error) {
          console.error('AI turn failed:', error);
          setAiError(error instanceof Error ? error.message : 'AI turn failed');
        } finally {
          isAIProcessingRef.current = false;
        }
      }, 1500);
    } else if (isPvEMode && apiProps.gameState.currentPlayer === 1 && !hasEligibleAIUnits) {
      console.log(`AI turn skipped - Phase: ${currentPhase}, No eligible AI units in activation pool`);
    }
  }, [isPvE, apiProps.gameState?.currentPlayer, apiProps.gameState?.phase, apiProps.gameState?.pve_mode, apiProps.unitsMoved, apiProps.unitsCharged, apiProps.unitsAttacked, apiProps.gameState?.units, apiProps.executeAITurn]);

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
            ? isAIProcessingRef.current 
              ? 'bg-purple-900 border border-purple-700' 
              : 'bg-purple-800 border border-purple-600'
            : 'bg-gray-800 border border-gray-600'
        }`}>
          <span className="text-sm font-medium text-white">
            {apiProps.gameState?.currentPlayer === 1 ? '🤖 AI Turn' : '👤 Your Turn'}
          </span>
          {apiProps.gameState?.currentPlayer === 1 && isAIProcessingRef.current && (
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
          currentTurn={apiProps.gameState?.currentTurn ?? 1}
        />
      </ErrorBoundary>
    </>
  );

  return (
    <SharedLayout 
      rightColumnContent={rightColumnContent}
      showHexCoordinates={showHexCoordinates}
      onToggleHexCoordinates={setShowHexCoordinates}
    >
      <BoardPvp
        units={apiProps.units}
        selectedUnitId={apiProps.selectedUnitId}
        showHexCoordinates={showHexCoordinates}
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
        blinkingUnits={apiProps.blinkingUnits}
        isBlinkingActive={apiProps.isBlinkingActive}
        blinkState={apiProps.blinkState}
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