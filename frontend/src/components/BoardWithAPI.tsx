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
import type { PlayerId, Unit, TargetPreview } from '../types';
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
  
  // Track UnitStatusTable collapse states
  const [player1Collapsed, setPlayer1Collapsed] = useState(false);
  const [player2Collapsed, setPlayer2Collapsed] = useState(false);
  
  // Settings menu state
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const handleOpenSettings = () => setIsSettingsOpen(true);
  
  // Settings preferences (from localStorage)
  const [settings, setSettings] = useState(() => {
    const showAdvanceWarningStr = localStorage.getItem('showAdvanceWarning');
    const showDebugStr = localStorage.getItem('showDebug');
    const autoSelectWeaponStr = localStorage.getItem('autoSelectWeapon');
    return {
      showAdvanceWarning: showAdvanceWarningStr ? JSON.parse(showAdvanceWarningStr) : false,
      showDebug: showDebugStr ? JSON.parse(showDebugStr) : false,
      autoSelectWeapon: autoSelectWeaponStr ? JSON.parse(autoSelectWeaponStr) : true,
    };
  });
  
  const handleToggleAdvanceWarning = (value: boolean) => {
    setSettings(prev => ({ ...prev, showAdvanceWarning: value }));
    localStorage.setItem('showAdvanceWarning', JSON.stringify(value));
  };
  
  const handleToggleDebug = (value: boolean) => {
    setSettings(prev => ({ ...prev, showDebug: value }));
    localStorage.setItem('showDebug', JSON.stringify(value));
  };
  
  const handleToggleAutoSelectWeapon = (value: boolean) => {
    setSettings(prev => ({ ...prev, autoSelectWeapon: value }));
    localStorage.setItem('autoSelectWeapon', JSON.stringify(value));
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
    const player1Alive = apiProps.gameState.units.some(u => u.player === 1 && (u.HP_CUR ?? u.HP_MAX) > 0);
    const player2Alive = apiProps.gameState.units.some(u => u.player === 2 && (u.HP_CUR ?? u.HP_MAX) > 0);
    const gameNotOver = player1Alive && player2Alive;
    
    // CRITICAL: Check if AI has eligible units in current phase
    // Use simple heuristic instead of missing activation pools
    const currentPhase = apiProps.gameState.phase;
    let hasEligibleAIUnits = false;
    
    if (currentPhase === 'move') {
      // Move phase: Check move activation pool for AI eligibility
      if (apiProps.gameState.move_activation_pool) {
        hasEligibleAIUnits = apiProps.gameState.move_activation_pool.some(unitId => {
          // Normalize comparison: pools contain strings, unit.id might be number
          const unit = apiProps.gameState!.units.find((u: Unit) => String(u.id) === String(unitId));
          return unit && unit.player === 2 && (unit.HP_CUR ?? unit.HP_MAX) > 0;
        });
      }
    } else if (currentPhase === 'shoot') {
      // Let backend handle shooting phase logic - it will auto-advance if no valid targets
      hasEligibleAIUnits = apiProps.gameState.units.some(unit => 
        unit.player === 2 && 
        (unit.HP_CUR ?? unit.HP_MAX) > 0
      );
    } else if (currentPhase === 'charge') {
      // Charge phase: Check charge activation pool for AI eligibility
      if (apiProps.gameState.charge_activation_pool) {
        hasEligibleAIUnits = apiProps.gameState.charge_activation_pool.some(unitId => {
          // Normalize comparison: pools contain strings, unit.id might be number
          const unit = apiProps.gameState!.units.find((u: Unit) => String(u.id) === String(unitId));
          return unit && unit.player === 2 && (unit.HP_CUR ?? unit.HP_MAX) > 0;
        });
      }
    } else if (currentPhase === 'fight') {
      // Fight phase: Check fight subphase pools for AI eligibility
      // Try both apiProps.fightSubPhase and apiProps.gameState.fight_subphase
      const fightSubphase = apiProps.fightSubPhase || apiProps.gameState?.fight_subphase;
      
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
      
      hasEligibleAIUnits = fightPool.some(unitId => {
        // Normalize comparison: pools contain strings, unit.id might be number
        const unit = apiProps.gameState!.units.find((u: Unit) => String(u.id) === String(unitId));
        const isAI = unit && unit.player === 2 && (unit.HP_CUR ?? unit.HP_MAX) > 0;
        return isAI;
      });
    }
    
    // CRITICAL: In fight phase, currentPlayer stays 1, but AI can still act in alternating phase
    const fightSubphaseForCheck = apiProps.fightSubPhase || apiProps.gameState?.fight_subphase;
    const currentPlayer = apiProps.gameState?.currentPlayer;
    const isAITurn = currentPhase === 'fight' 
      ? hasEligibleAIUnits && (
          // Charging subphase: AI turn if currentPlayer is 2
          (fightSubphaseForCheck === 'charging' && currentPlayer === 2) ||
          // Alternating active: AI turn if currentPlayer is 2 (active pool = current player's units)
          (fightSubphaseForCheck === 'alternating_active' && currentPlayer === 2) ||
          // Alternating non-active: AI turn if currentPlayer is 1 (non-active = opposite of current player)
          // When currentPlayer is 2, non-active pool contains P1 units, so it's NOT AI turn
          // When currentPlayer is 1, non-active pool contains P2 units, so it IS AI turn
          (fightSubphaseForCheck === 'alternating_non_active' && currentPlayer === 1) ||
          // Cleanup active: AI turn if currentPlayer is 2
          (fightSubphaseForCheck === 'cleanup_active' && currentPlayer === 2) ||
          // Cleanup non-active: AI turn if currentPlayer is 1
          (fightSubphaseForCheck === 'cleanup_non_active' && currentPlayer === 1)
        )
      : currentPlayer === 2;
    
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
        prevAICheckRef.current = currentAICheck;
      }
    
    if (shouldTriggerAI) {
      isAIProcessingRef.current = true;
      // Don't set lastProcessedTurn here - wait until AI completes successfully
      
      // Small delay to ensure UI updates are complete
      setTimeout(async () => {
        try {
          if (apiProps.executeAITurn) {
            await apiProps.executeAITurn();
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
      // AI turn skipped - no eligible units
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
  }, [isPvE, apiProps, lastProcessedTurn]);
  
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
        setLastProcessedTurn('');
      }
    }
  }, [apiProps.gameState, apiProps.fightSubPhase, lastProcessedTurn]);

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
      
      const player1Table = allTables[0];
      const player2Table = allTables[1];
      
      // Get actual heights from DOM measurements
      const turnPhaseHeight = turnPhaseTracker.getBoundingClientRect().height;
      const player1Height = player1Table.getBoundingClientRect().height;
      const player2Height = player2Table.getBoundingClientRect().height;
      const gameLogHeaderHeight = gameLogHeader.getBoundingClientRect().height;
      
      // Calculate available space based purely on actual measurements
      const viewportHeight = window.innerHeight;
      const appContainer = document.querySelector('.app-container') || document.body;
      const appMargins = viewportHeight - appContainer.getBoundingClientRect().height;
      const usedSpace = turnPhaseHeight + player1Height + player2Height + gameLogHeaderHeight;
      const availableForLogEntries = viewportHeight - usedSpace - appMargins;
    
      const sampleLogEntry = document.querySelector('.game-log-entry');
      if (!sampleLogEntry) {
        setLogAvailableHeight(220);
        return;
      }
      setLogAvailableHeight(availableForLogEntries);
    }, 100); // Wait 100ms for DOM to render
  }, [player1Collapsed, player2Collapsed, apiProps.gameState?.units, apiProps.gameState?.phase]);

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
          currentPlayer={apiProps.gameState?.currentPlayer}
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
          apiProps.gameState?.currentPlayer === 2 
            ? isAIProcessingRef.current 
              ? 'bg-purple-900 border border-purple-700' 
              : 'bg-purple-800 border border-purple-600'
            : 'bg-gray-800 border border-gray-600'
        }`}>
          <span className="text-sm font-medium text-white">
            {apiProps.gameState?.currentPlayer === 2 ? '🤖 AI Turn' : '👤 Your Turn'}
          </span>
          {apiProps.gameState?.currentPlayer === 2 && isAIProcessingRef.current && (
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

      <ErrorBoundary fallback={<div>Failed to load player 2 status</div>}>
        <UnitStatusTable
          units={apiProps.gameState?.units ?? []}
          player={2}
          selectedUnitId={apiProps.selectedUnitId ?? null}
          clickedUnitId={clickedUnitId}
          onSelectUnit={(unitId) => {
            apiProps.onSelectUnit(unitId);
            setClickedUnitId(null);
          }}
          gameMode={gameMode}
          onCollapseChange={setPlayer2Collapsed}
        />
      </ErrorBoundary>

      {/* Game Log Component */}
      <ErrorBoundary fallback={<div>Failed to load game log</div>}>
        <GameLog 
          events={gameLog.events}
          getElapsedTime={gameLog.getElapsedTime}
          availableHeight={logAvailableHeight}
          currentTurn={apiProps.gameState?.currentTurn ?? 1}
          debugMode={settings.showDebug}
        />
      </ErrorBoundary>
    </>
  );

  return (
    <SharedLayout 
      rightColumnContent={rightColumnContent}
      onOpenSettings={handleOpenSettings}
    >
      <BoardPvp
        units={apiProps.units}
        selectedUnitId={apiProps.selectedUnitId}
        showHexCoordinates={settings.showDebug}
        eligibleUnitIds={apiProps.eligibleUnitIds}
        mode={apiProps.mode}
        movePreview={apiProps.movePreview}
        attackPreview={apiProps.attackPreview || null}
        targetPreview={apiProps.targetPreview ? {
          targetId: apiProps.targetPreview.targetId,
          shooterId: apiProps.targetPreview.shooterId,
          currentBlinkStep: apiProps.targetPreview.currentBlinkStep ?? 0,
          totalBlinkSteps: apiProps.targetPreview.totalBlinkSteps ?? 2,
          blinkTimer: apiProps.targetPreview.blinkTimer ?? null,
          hitProbability: apiProps.targetPreview.hitProbability ?? 0.5,
          woundProbability: apiProps.targetPreview.woundProbability ?? 0.5,
          saveProbability: apiProps.targetPreview.saveProbability ?? 0.5,
          overallProbability: apiProps.targetPreview.overallProbability ?? 0.25
        } : null}
        blinkingUnits={apiProps.blinkingUnits}
        blinkingAttackerId={apiProps.blinkingAttackerId}
        isBlinkingActive={apiProps.isBlinkingActive}
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
          const targetPreview = apiProps.targetPreview as TargetPreview | null;
          if (targetPreview?.blinkTimer) {
            clearInterval(targetPreview.blinkTimer);
          }
          // Clear target preview in engine API
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
        showAdvanceWarningPopup={settings.showAdvanceWarning}
        autoSelectWeapon={settings.autoSelectWeapon}
        />
        <SettingsMenu
          isOpen={isSettingsOpen}
          onClose={() => setIsSettingsOpen(false)}
          showAdvanceWarning={settings.showAdvanceWarning}
          onToggleAdvanceWarning={handleToggleAdvanceWarning}
          showDebug={settings.showDebug}
          onToggleDebug={handleToggleDebug}
          autoSelectWeapon={settings.autoSelectWeapon}
          onToggleAutoSelectWeapon={handleToggleAutoSelectWeapon}
        />
      </SharedLayout>
    );
  };
  