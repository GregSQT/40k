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
import { SettingsMenu } from './SettingsMenu';

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
  
  // Settings menu state
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const handleOpenSettings = () => setIsSettingsOpen(true);
  
  // Settings preferences (from localStorage)
  const [showAdvanceWarning, setShowAdvanceWarning] = useState<boolean>(() => {
    const saved = localStorage.getItem('showAdvanceWarning');
    return saved ? JSON.parse(saved) : false; // Default: false (désactivé)
  });
  
  const handleToggleAdvanceWarning = (value: boolean) => {
    setShowAdvanceWarning(value);
    localStorage.setItem('showAdvanceWarning', JSON.stringify(value));
  };
  
  // Calculate available height for GameLog dynamically
  const [logAvailableHeight, setLogAvailableHeight] = useState(220);
  
  // Track AI processing with ref to avoid re-render loops
  const isAIProcessingRef = useRef(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [lastProcessedTurn, setLastProcessedTurn] = useState<string>('');
  
  // Track previous values to prevent console flooding during animations
  const prevAICheckRef = useRef<{
    currentPhase: string;
    currentPlayer: number;
    isAITurn: boolean;
    shouldTriggerAI: boolean;
    turnKey: string;
  } | null>(null);
  
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
      // Move phase: Check move activation pool for AI eligibility
      if (apiProps.gameState.move_activation_pool) {
        hasEligibleAIUnits = apiProps.gameState.move_activation_pool.some(unitId => {
          // Normalize comparison: pools contain strings, unit.id might be number
          const unit = apiProps.gameState.units.find((u: any) => String(u.id) === String(unitId));
          return unit && unit.player === 1 && (unit.HP_CUR ?? unit.HP_MAX) > 0;
        });
      }
    } else if (currentPhase === 'shoot') {
      // Let backend handle shooting phase logic - it will auto-advance if no valid targets
      hasEligibleAIUnits = apiProps.gameState.units.some(unit => 
        unit.player === 1 && 
        (unit.HP_CUR ?? unit.HP_MAX) > 0
      );
    } else if (currentPhase === 'charge') {
      // Charge phase: Check charge activation pool for AI eligibility
      if (apiProps.gameState.charge_activation_pool) {
        hasEligibleAIUnits = apiProps.gameState.charge_activation_pool.some(unitId => {
          // Normalize comparison: pools contain strings, unit.id might be number
          const unit = apiProps.gameState.units.find((u: any) => String(u.id) === String(unitId));
          return unit && unit.player === 1 && (unit.HP_CUR ?? unit.HP_MAX) > 0;
        });
      }
    } else if (currentPhase === 'fight') {
      // Fight phase: Check fight subphase pools for AI eligibility
      // Try both apiProps.fightSubPhase and apiProps.gameState.fight_subphase
      const fightSubphase = apiProps.fightSubPhase || apiProps.gameState?.fight_subphase;
      console.log(`🔍 [BOARD_WITH_API] Fight phase check:`, {
        fightSubphase_from_props: apiProps.fightSubPhase,
        fight_subphase_from_gameState: apiProps.gameState?.fight_subphase,
        fightSubphase_used: fightSubphase,
        gameState_keys: apiProps.gameState ? Object.keys(apiProps.gameState) : 'gameState is null'
      });
      console.log(`🔍 [BOARD_WITH_API] Available pools:`, {
        charging: apiProps.gameState?.charging_activation_pool,
        non_active: apiProps.gameState?.non_active_alternating_activation_pool,
        active: apiProps.gameState?.active_alternating_activation_pool,
        pools_length: {
          charging: apiProps.gameState?.charging_activation_pool?.length || 0,
          non_active: apiProps.gameState?.non_active_alternating_activation_pool?.length || 0,
          active: apiProps.gameState?.active_alternating_activation_pool?.length || 0
        }
      });
      
      let fightPool: string[] = [];
      if (fightSubphase === 'charging' && apiProps.gameState.charging_activation_pool) {
        fightPool = apiProps.gameState.charging_activation_pool;
      } else if (fightSubphase === 'alternating_non_active' && apiProps.gameState.non_active_alternating_activation_pool) {
        fightPool = apiProps.gameState.non_active_alternating_activation_pool;
      } else if (fightSubphase === 'alternating_active' && apiProps.gameState.active_alternating_activation_pool) {
        fightPool = apiProps.gameState.active_alternating_activation_pool;
      } else if (fightSubphase === 'cleanup_non_active' && apiProps.gameState.non_active_alternating_activation_pool) {
        fightPool = apiProps.gameState.non_active_alternating_activation_pool;
      } else if (fightSubphase === 'cleanup_active' && apiProps.gameState.active_alternating_activation_pool) {
        fightPool = apiProps.gameState.active_alternating_activation_pool;
      }
      
      console.log(`🔍 [BOARD_WITH_API] Selected fight pool: ${fightPool.length} units`, fightPool);
      
      hasEligibleAIUnits = fightPool.some(unitId => {
        // Normalize comparison: pools contain strings, unit.id might be number
        const unit = apiProps.gameState.units.find((u: any) => String(u.id) === String(unitId));
        const isAI = unit && unit.player === 1 && (unit.HP_CUR ?? unit.HP_MAX) > 0;
        if (unit) {
          console.log(`🔍 [BOARD_WITH_API] Checking unit: poolId=${unitId} (${typeof unitId}), unit.id=${unit.id} (${typeof unit.id}), player=${unit.player}, HP=${unit.HP_CUR}, isAI=${isAI}`);
        } else {
          console.log(`🔍 [BOARD_WITH_API] Unit not found for poolId=${unitId} (${typeof unitId}). Available unit IDs:`, apiProps.gameState.units.map((u: any) => `${u.id} (${typeof u.id})`));
        }
        return isAI;
      });
      
      console.log(`🔍 [BOARD_WITH_API] hasEligibleAIUnits=${hasEligibleAIUnits} for fight phase`);
    }
    
    // CRITICAL: In fight phase, currentPlayer stays 0, but AI can still act in alternating phase
    const fightSubphaseForCheck = apiProps.fightSubPhase || apiProps.gameState?.fight_subphase;
    const isAITurn = currentPhase === 'fight' 
      ? hasEligibleAIUnits && (fightSubphaseForCheck === 'alternating_non_active' || 
                               fightSubphaseForCheck === 'cleanup_non_active' ||
                               (fightSubphaseForCheck === 'charging' && apiProps.gameState?.currentPlayer === 1))
      : apiProps.gameState?.currentPlayer === 1;
    
    // Removed duplicate log - now handled below with change detection
    
    const fightSubphaseForKey = apiProps.fightSubPhase || apiProps.gameState?.fight_subphase || '';
    const turnKey = `${apiProps.gameState?.currentPlayer}-${currentPhase}-${fightSubphaseForKey}-${apiProps.gameState?.currentTurn || 1}`;
    
    // Reset lastProcessedTurn if turn/phase has changed (prevents blocking on failed AI turns)
    // Extract turn/phase from lastProcessedTurn to compare
    if (lastProcessedTurn) {
      const lastParts = lastProcessedTurn.split('-');
      const currentTurn = apiProps.gameState?.currentTurn || 1;
      const lastTurn = lastParts.length >= 4 ? parseInt(lastParts[3]) : null;
      const lastPhase = lastParts.length >= 2 ? lastParts[1] : null;
      
      // If turn or phase changed, reset lastProcessedTurn
      if (lastTurn !== currentTurn || lastPhase !== currentPhase) {
        console.log(`🔄 [BOARD_WITH_API] Turn/phase changed (turn: ${lastTurn}→${currentTurn}, phase: ${lastPhase}→${currentPhase}), resetting lastProcessedTurn`);
        setLastProcessedTurn('');
      }
    }
    
    // Allow multiple AI activations in same phase if there are still eligible units
    // Don't use lastProcessedTurn to block - rely on isAIProcessingRef and hasEligibleAIUnits
    // lastProcessedTurn is only used to detect turn/phase changes for reset
    const shouldTriggerAI = isPvEMode && 
                           isAITurn && 
                           !isAIProcessingRef.current && 
                           gameNotOver && 
                           hasEligibleAIUnits;
    
    // Only log when values actually change (prevents console flooding during animations)
    const currentAICheck = {
      currentPhase,
      currentPlayer: apiProps.gameState.currentPlayer,
      isAITurn,
      shouldTriggerAI,
      turnKey
    };
    
    const prevCheck = prevAICheckRef.current;
    const hasChanged = !prevCheck || 
      prevCheck.currentPhase !== currentAICheck.currentPhase ||
      prevCheck.currentPlayer !== currentAICheck.currentPlayer ||
      prevCheck.isAITurn !== currentAICheck.isAITurn ||
      prevCheck.shouldTriggerAI !== currentAICheck.shouldTriggerAI ||
      prevCheck.turnKey !== currentAICheck.turnKey;
    
    if (hasChanged) {
      console.log(`🔍 [BOARD_WITH_API] AI turn check:`, {
        currentPhase,
        currentPlayer: apiProps.gameState.currentPlayer,
        fight_subphase: apiProps.gameState.fight_subphase,
        hasEligibleAIUnits,
        isAITurn,
        isPvEMode,
        isAIProcessing: isAIProcessingRef.current,
        gameNotOver
      });
      console.log(`🔍 [BOARD_WITH_API] shouldTriggerAI=${shouldTriggerAI}, lastProcessedTurn=${lastProcessedTurn}, turnKey=${turnKey}`);
      prevAICheckRef.current = currentAICheck;
    }
    
    if (shouldTriggerAI) {
      console.log(`✅ [BOARD_WITH_API] Triggering AI turn for Player 1 (AI) - Phase: ${currentPhase}, Eligible AI units: ${hasEligibleAIUnits}`);
      isAIProcessingRef.current = true;
      // Don't set lastProcessedTurn here - wait until AI completes successfully
      
      // Small delay to ensure UI updates are complete
      setTimeout(async () => {
        console.log('⏱️ [BOARD_WITH_API] Timer fired, checking executeAITurn:', typeof apiProps.executeAITurn);
        try {
          if (apiProps.executeAITurn) {
            console.log('🤖 [BOARD_WITH_API] Calling executeAITurn...');
            await apiProps.executeAITurn();
            console.log('✅ [BOARD_WITH_API] AI turn completed');
            // Don't set lastProcessedTurn here - allow multiple activations in same phase
            // lastProcessedTurn will be set when phase actually changes (via useEffect dependency)
          } else {
            console.error('❌ [BOARD_WITH_API] executeAITurn function not available, type:', typeof apiProps.executeAITurn);
            setAiError('AI function not available');
          }
        } catch (error) {
          console.error('❌ [BOARD_WITH_API] AI turn failed:', error);
          setAiError(error instanceof Error ? error.message : 'AI turn failed');
        } finally {
          isAIProcessingRef.current = false;
        }
      }, 1500);
    } else if (isPvEMode && isAITurn && !hasEligibleAIUnits) {
      // Only log when this condition changes
      if (!prevCheck || prevCheck.shouldTriggerAI !== shouldTriggerAI) {
        console.log(`⚠️ [BOARD_WITH_API] AI turn skipped - Phase: ${currentPhase}, No eligible AI units in activation pool`);
      }
    } else if (isPvEMode && !shouldTriggerAI && hasChanged) {
      // Only log when values change, and only in debug scenarios
      // Suppress the "NOT triggered" warning to reduce console noise
      // Uncomment below if you need to debug AI triggering issues
      // console.log(`⚠️ [BOARD_WITH_API] AI turn NOT triggered. Reasons:`, {
      //   isPvEMode,
      //   isAITurn,
      //   isAIProcessing: isAIProcessingRef.current,
      //   gameNotOver,
      //   hasEligibleAIUnits,
      //   lastProcessedTurn,
      //   turnKey,
      //   turnKeyMatches: lastProcessedTurn === turnKey
      // });
    }
  }, [isPvE, apiProps.gameState?.currentPlayer, apiProps.gameState?.phase, apiProps.gameState?.fight_subphase, apiProps.gameState?.pve_mode, apiProps.gameState?.move_activation_pool, apiProps.gameState?.charge_activation_pool, apiProps.gameState?.non_active_alternating_activation_pool, apiProps.gameState?.active_alternating_activation_pool, apiProps.gameState?.charging_activation_pool, apiProps.unitsMoved, apiProps.unitsCharged, apiProps.unitsAttacked, apiProps.gameState?.units, apiProps.executeAITurn, lastProcessedTurn]);
  
  // Update lastProcessedTurn when phase/turn changes (to track phase transitions)
  useEffect(() => {
    if (!apiProps.gameState) return;
    const fightSubphaseForKey = apiProps.fightSubPhase || apiProps.gameState?.fight_subphase || '';
    const currentTurnKey = `${apiProps.gameState?.currentPlayer}-${apiProps.gameState?.phase}-${fightSubphaseForKey}-${apiProps.gameState?.currentTurn || 1}`;
    
    // Only update if phase/turn actually changed (not just on every render)
    if (lastProcessedTurn && lastProcessedTurn !== currentTurnKey) {
      // Phase/turn changed - reset to allow new AI activations
      const lastParts = lastProcessedTurn.split('-');
      const currentTurn = apiProps.gameState?.currentTurn || 1;
      const lastTurn = lastParts.length >= 4 ? parseInt(lastParts[3]) : null;
      const lastPhase = lastParts.length >= 2 ? lastParts[1] : null;
      
      if (lastTurn !== currentTurn || lastPhase !== apiProps.gameState?.phase) {
        console.log(`🔄 [BOARD_WITH_API] Phase/turn changed, clearing lastProcessedTurn`);
        setLastProcessedTurn('');
      }
    }
  }, [apiProps.gameState?.phase, apiProps.gameState?.currentTurn, apiProps.gameState?.currentPlayer, apiProps.fightSubPhase, apiProps.gameState?.fight_subphase, lastProcessedTurn]);

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
        <div className="turn-phase-tracker-right">
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
            className=""
          />
        </div>
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
          debugMode={showHexCoordinates}
        />
      </ErrorBoundary>
    </>
  );

  return (
    <SharedLayout 
      rightColumnContent={rightColumnContent}
      showHexCoordinates={showHexCoordinates}
      onToggleHexCoordinates={setShowHexCoordinates}
      onOpenSettings={handleOpenSettings}
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
        onActivateFight={apiProps.onActivateFight}
        currentPlayer={apiProps.currentPlayer as PlayerId}
        unitsMoved={apiProps.unitsMoved}
        unitsCharged={apiProps.unitsCharged}
        unitsAttacked={apiProps.unitsAttacked}
        unitsFled={apiProps.unitsFled}
        phase={apiProps.phase as "move" | "shoot" | "charge" | "fight"}
        fightSubPhase={apiProps.fightSubPhase}
        onCharge={apiProps.onCharge}
        onActivateCharge={apiProps.onActivateCharge}
        onMoveCharger={apiProps.onMoveCharger}
        onCancelCharge={apiProps.onCancelCharge}
        onValidateCharge={apiProps.onValidateCharge}
        onLogChargeRoll={apiProps.onLogChargeRoll}
        gameState={apiProps.gameState!}
        getChargeDestinations={apiProps.getChargeDestinations}
        onAdvance={apiProps.onAdvance}
        onAdvanceMove={apiProps.onAdvanceMove}
        onCancelAdvance={apiProps.onCancelAdvance}
        getAdvanceDestinations={apiProps.getAdvanceDestinations}
        advanceRoll={apiProps.advanceRoll}
        advancingUnitId={apiProps.advancingUnitId}
        advanceWarningPopup={apiProps.advanceWarningPopup}
        onConfirmAdvanceWarning={apiProps.onConfirmAdvanceWarning}
        onCancelAdvanceWarning={apiProps.onCancelAdvanceWarning}
        onSkipAdvanceWarning={apiProps.onSkipAdvanceWarning}
        showAdvanceWarningPopup={showAdvanceWarning}
        />
        <SettingsMenu
          isOpen={isSettingsOpen}
          onClose={() => setIsSettingsOpen(false)}
          showAdvanceWarning={showAdvanceWarning}
          onToggleAdvanceWarning={handleToggleAdvanceWarning}
        />
      </SharedLayout>
    );
  };
  