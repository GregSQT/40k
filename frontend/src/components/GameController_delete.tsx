// src/components/GameController.tsx

import React from "react";
import { useLocation } from 'react-router-dom';
import { SharedLayout } from "./SharedLayout";
import { ErrorBoundary } from "./ErrorBoundary";
import { UnitStatusTable } from "./UnitStatusTable";
import { GameBoard } from "./GameBoard";
//import { GameStatus } from "./GameStatus";
import { GameLog } from "./GameLog";
import { useGameState } from "../hooks/useGameState";
import { useGameActions } from "../hooks/useGameActions";
import { useGameConfig } from "../hooks/useGameConfig";
import { useAITurn } from "../hooks/useAITurn";
import { usePhaseTransition } from "../hooks/usePhaseTransition";
import { useGameLog } from "../hooks/useGameLog";
import type { Unit } from "../types/game";
import { useState, useEffect } from "react";
//import { createUnit, getAvailableUnitTypes } from "../data/UnitFactory";
import { TurnPhaseTracker } from "./TurnPhaseTracker";

interface GameControllerProps {
  initialUnits?: Unit[];  // Make optional
  className?: string;
}

export const GameController: React.FC<GameControllerProps> = ({
  initialUnits,
  className,
}) => {
  // ALL HOOKS CALLED FIRST - FIXED ORDER TO PREVENT HOOK VIOLATIONS
  const [gameUnits, setGameUnits] = useState<Unit[]>(initialUnits || []);
  const [player0Collapsed, setPlayer0Collapsed] = useState(false);
  const [player1Collapsed, setPlayer1Collapsed] = useState(false);
  const [clickedUnitId, setClickedUnitId] = useState<number | null>(null);
  const [logAvailableHeight, setLogAvailableHeight] = useState(220);
  
  const location = useLocation();
  const { config, loading, error } = useGameConfig();
  const gameLog = useGameLog();
  const { gameState, movePreview, attackPreview, shootingPhaseState, chargeRollPopup, actions } = useGameState(gameUnits);
  
  useEffect(() => {
    if (!initialUnits || initialUnits.length === 0) {
      // Load units from scenario.json - no fallbacks
      fetch('/config/scenario.json')
        .then(response => response.json())
        .then(scenarioData => {
          if (scenarioData.units) {
            setGameUnits(scenarioData.units);
          } else {
            throw new Error('No units found in scenario.json');
          }
        })
        .catch(error => {
          console.error('Failed to load scenario.json:', error);
          throw new Error(`Failed to load units from scenario.json: ${error.message}`);
        });
    }
  }, [initialUnits]);

  // Detect game mode from URL (after hooks)
  const gameMode = location.pathname.includes('/pve') ? 'pve' : 
                   location.pathname.includes('/replay') ? 'training' : 'pvp';
  const isPvE = gameMode === 'pve';
  const boardConfig = config; // Alias for compatibility
  
  // Set up game actions (called unconditionally with safe defaults)
  const originalGameActions = useGameActions({
    gameState,
    movePreview,
    attackPreview,
    shootingPhaseState,
    boardConfig: boardConfig || null, // Safe default
    actions: {
      ...actions,
      setMode: (mode: any) => actions.setMode(mode || "select"),
    },
    gameLog,
  });

  // Calculate eligible units by calling the useGameActions.isUnitEligible function (no duplicate logic)
  const eligibleUnitIds = React.useMemo(() => {
    if (!boardConfig) return [];
    
    return gameState.units.filter(unit => {
      // Call the ACTUAL isUnitEligible function from useGameActions (single source of truth)
      return originalGameActions.isUnitEligible(unit);
    }).map(unit => unit.id);
  }, [gameState.units, boardConfig, originalGameActions.isUnitEligible, gameState.phase, gameState.currentPlayer, gameState.unitsMoved, gameState.unitsCharged, gameState.unitsAttacked, gameState.unitsFled]);

  // Initialize AI turn processing for PvE mode
  const { isAIProcessing, processAITurn, aiError, clearAIError } = useAITurn({
    gameState,
    gameActions: {
      ...originalGameActions,
      addMovedUnit: actions.addMovedUnit,
      addChargedUnit: actions.addChargedUnit,
      addAttackedUnit: actions.addAttackedUnit,
    },
    currentPlayer: gameState.currentPlayer ?? 0,
    phase: gameState.phase,
    units: gameState.units
  });

  // Manage phase transitions
  usePhaseTransition({
    gameState,
    boardConfig,
    isUnitEligible: (unit: Unit) => Boolean(originalGameActions.isUnitEligible(unit)), // Pass the authoritative eligibility function
    actions: {
      setPhase: actions.setPhase,
      setCurrentPlayer: actions.setCurrentPlayer,
      setSelectedUnitId: actions.setSelectedUnitId,
      setMode: (mode: any) => actions.setMode(mode || "select"),
      resetMovedUnits: actions.resetMovedUnits,
      resetChargedUnits: actions.resetChargedUnits,
      resetAttackedUnits: actions.resetAttackedUnits,
      resetFledUnits: actions.resetFledUnits,
      initializeFightPhase: actions.initializeFightPhase,
      setCurrentTurn: actions.setCurrentTurn,
      setFightSubPhase: actions.setFightSubPhase,
      setFightActivePlayer: actions.setFightActivePlayer,
      setUnits: actions.setUnits,
    },
  });

  // Initialize shooting phase when entering shoot phase
  React.useEffect(() => {
    if (gameState.phase === 'shoot') {
      actions.initializeShootingPhase();
    }
  }, [gameState.phase]);

  // Initialize fight phase when entering fight phase
  React.useEffect(() => {
    if (gameState.phase === 'fight') {
      actions.initializeFightPhase();
    }
  }, [gameState.phase]);

  // Calculate available height for GameLog dynamically
  React.useEffect(() => {
    // Wait for DOM to be fully rendered before measuring
    setTimeout(() => {
      const turnPhaseTracker = document.querySelector('.turn-phase-tracker-right');
      const allTables = document.querySelectorAll('.unit-status-table-container');
      const gameLogHeader = document.querySelector('.game-log__header') || document.querySelector('[class*="game-log"]');
      
      if (!turnPhaseTracker) throw new Error('TurnPhaseTracker element not found');
      if (allTables.length < 2) throw new Error(`Expected 2 unit status tables, found ${allTables.length}`);
      if (!gameLogHeader) throw new Error('GameLog header element not found');
      
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
      if (!sampleLogEntry) throw new Error('No log entry found to measure height');
      setLogAvailableHeight(availableForLogEntries);
    }, 100); // Wait 100ms for DOM to render
  }, [player0Collapsed, player1Collapsed, gameState.units, gameState.phase]);

  // AI Turn Processing Effect - Trigger AI when it's AI player's turn
  React.useEffect(() => {
    // Check if game is over by examining unit health
    const player0Alive = gameState.units.some(u => u.player === 0 && (u.HP_CUR ?? u.HP_MAX) > 0);
    const player1Alive = gameState.units.some(u => u.player === 1 && (u.HP_CUR ?? u.HP_MAX) > 0);
    const gameNotOver = player0Alive && player1Alive;
    
    if (isPvE && gameState.currentPlayer === 1 && !isAIProcessing && gameNotOver) {
      // Small delay to ensure UI updates are complete
      const timer = setTimeout(() => {
        processAITurn();
      }, 1000);
      
      return () => clearTimeout(timer);
    }
  }, [isPvE, gameState.currentPlayer, gameState.phase, isAIProcessing, gameState.units, processAITurn]);

  // Track turn changes with ref to prevent infinite loops
  const lastLoggedTurn = React.useRef<number>(0);
  
  React.useEffect(() => {
    const currentTurn = gameState.currentTurn ?? 1;
    if (currentTurn > 1 && currentTurn !== lastLoggedTurn.current) {
      gameLog.logTurnStart(currentTurn);
      lastLoggedTurn.current = currentTurn;
    }
  }, [gameState.currentTurn, gameLog]);

  // Track phase changes with ref to prevent duplicates
  const lastLoggedPhase = React.useRef<string>('');
  
  React.useEffect(() => {
    const currentTurn = gameState.currentTurn ?? 1;
    if (currentTurn >= 1) { // Only log phases after game starts
      const currentPhaseKey = `${currentTurn}-${gameState.phase}-${gameState.currentPlayer}`;
      
      if (currentPhaseKey !== lastLoggedPhase.current) {
        gameLog.logPhaseChange(gameState.phase, gameState.currentPlayer ?? 0, currentTurn);
        lastLoggedPhase.current = currentPhaseKey;
      }
    }
  }, [gameState.phase, gameState.currentPlayer, gameState.currentTurn, gameLog]);

  // Track unit deaths
  React.useEffect(() => {
    const deadUnits = gameState.units.filter(unit => (unit.HP_CUR ?? unit.HP_MAX) <= 0);
    deadUnits.forEach(unit => {
      // Check if we haven't already logged this death
      const alreadyLogged = gameLog.events.some(event => 
        event.type === 'death' && 
        event.unitId === unit.id
      );
      
      if (!alreadyLogged) {
        gameLog.logUnitDeath(unit, gameState.currentTurn ?? 1);
      }
    });
  }, [gameState.units, gameState.currentTurn, gameLog]);

  // Track board clicks for highlighting
  const previousSelectedUnit = React.useRef<number | null>(null);
  
  React.useEffect(() => {
    // If selectedUnitId didn't change but we had a click, it means a non-selectable unit was clicked
    if (gameState.selectedUnitId === previousSelectedUnit.current) {
      // Check if there was a recent board click that didn't result in selection
      // This is a workaround since we can't easily intercept board clicks
    }
    previousSelectedUnit.current = (gameState.selectedUnitId ?? null) as number | null;
  }, [gameState.selectedUnitId]);

  // NOW handle loading and error states AFTER all hooks
  if (loading) {
    return <div>Loading configuration...</div>;
  }
  
  if (error) {
    throw new Error(`Configuration error: ${error}`);
  }
  
  if (!config) {
    throw new Error('Game configuration required but not loaded');
  }
  
  // Extract maxTurns from config with proper error handling
  const configAny = config as any; // Bypass TypeScript restrictions
  const maxTurns = configAny?.game_rules?.max_turns as number;
  if (!maxTurns) {
    throw new Error(`maxTurns not found in game configuration. Required: config.game_rules.max_turns. Config structure: ${JSON.stringify(Object.keys(configAny || {}))}`);
  }

  // Use original game actions without modification
  const gameActions = originalGameActions;

  // All duplicate declarations removed - using hooks and refs declared at top of component

  // Use the logAvailableHeight from useState declared at top
  React.useEffect(() => {
    // Wait for DOM to be fully rendered before measuring
    setTimeout(() => {
      const turnPhaseTracker = document.querySelector('.turn-phase-tracker-right');
      const allTables = document.querySelectorAll('.unit-status-table-container');
      const gameLogHeader = document.querySelector('.game-log__header') || document.querySelector('[class*="game-log"]');
      
      if (!turnPhaseTracker) throw new Error('TurnPhaseTracker element not found');
      if (allTables.length < 2) throw new Error(`Expected 2 unit status tables, found ${allTables.length}`);
      if (!gameLogHeader) throw new Error('GameLog header element not found');
      
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
      if (!sampleLogEntry) throw new Error('No log entry found to measure height');
      setLogAvailableHeight(availableForLogEntries);
    }, 100); // Wait 100ms for DOM to render
  }, [player0Collapsed, player1Collapsed, gameState.units, gameState.phase]);

  // AI Turn Processing Effect - Trigger AI when it's AI player's turn
  React.useEffect(() => {
    // Check if game is over by examining unit health
    const player0Alive = gameState.units.some(u => u.player === 0 && (u.HP_CUR ?? u.HP_MAX) > 0);
    const player1Alive = gameState.units.some(u => u.player === 1 && (u.HP_CUR ?? u.HP_MAX) > 0);
    const gameNotOver = player0Alive && player1Alive;
    
    if (isPvE && gameState.currentPlayer === 1 && !isAIProcessing && gameNotOver) {
      // Small delay to ensure UI updates are complete
      const timer = setTimeout(() => {
        processAITurn();
      }, 1000);
      
      return () => clearTimeout(timer);
    }
  }, [isPvE, gameState.currentPlayer, gameState.phase, isAIProcessing, gameState.units, processAITurn]);

  // Track turn changes with ref to prevent infinite loops
  React.useEffect(() => {
    const currentTurn = gameState.currentTurn ?? 1;
    if (currentTurn > 1 && currentTurn !== lastLoggedTurn.current) {
      gameLog.logTurnStart(currentTurn);
      lastLoggedTurn.current = currentTurn;
    }
  }, [gameState.currentTurn, gameLog]);

  // Track phase changes with ref to prevent duplicates
  React.useEffect(() => {
    const currentTurn = gameState.currentTurn ?? 1;
    if (currentTurn >= 1) { // Only log phases after game starts
      const currentPhaseKey = `${currentTurn}-${gameState.phase}-${gameState.currentPlayer}`;
      
      if (currentPhaseKey !== lastLoggedPhase.current) {
        gameLog.logPhaseChange(gameState.phase, gameState.currentPlayer ?? 0, currentTurn);
        lastLoggedPhase.current = currentPhaseKey;
      }
    }
  }, [gameState.phase, gameState.currentPlayer, gameState.currentTurn, gameLog]);

  // Track unit deaths
  React.useEffect(() => {
    const deadUnits = gameState.units.filter(unit => (unit.HP_CUR ?? unit.HP_MAX) <= 0);
    deadUnits.forEach(unit => {
      // Check if we haven't already logged this death
      const alreadyLogged = gameLog.events.some(event => 
        event.type === 'death' && 
        event.unitId === unit.id
      );
      
      if (!alreadyLogged) {
        gameLog.logUnitDeath(unit, gameState.currentTurn ?? 1);
      }
    });
  }, [gameState.units, gameState.currentTurn, gameLog]);

  // Track board clicks for highlighting
  React.useEffect(() => {
    // If selectedUnitId didn't change but we had a click, it means a non-selectable unit was clicked
    if (gameState.selectedUnitId === previousSelectedUnit.current) {
      // Check if there was a recent board click that didn't result in selection
      // This is a workaround since we can't easily intercept board clicks
    }
    previousSelectedUnit.current = (gameState.selectedUnitId ?? null) as number | null;
  }, [gameState.selectedUnitId]);

  const rightColumnContent = (
    <>
      <TurnPhaseTracker 
        currentTurn={gameState.currentTurn ?? 1} 
        currentPhase={gameState.phase}
        phases={["move", "shoot", "charge", "fight"]}
        maxTurns={maxTurns}
        className="turn-phase-tracker-right"
      />
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
    <SharedLayout 
      className={className}
      rightColumnContent={rightColumnContent}
    >
      <GameBoard
        units={gameState.units}
        selectedUnitId={gameState.selectedUnitId ?? null}
        phase={gameState.phase}
        eligibleUnitIds={eligibleUnitIds}
        mode={gameState.mode}
        movePreview={movePreview}
        attackPreview={attackPreview}
        currentPlayer={gameState.currentPlayer}
        unitsMoved={gameState.unitsMoved ?? []}
        unitsCharged={gameState.unitsCharged ?? []}
        unitsAttacked={gameState.unitsAttacked ?? []}
        unitsFled={gameState.unitsFled ?? []}
        fightSubPhase={gameState.fightSubPhase}
        fightActivePlayer={gameState.fightActivePlayer}
        currentTurn={gameState.currentTurn ?? 1}
        gameState={gameState}
        getChargeDestinations={gameActions.getChargeDestinations}
        onSelectUnit={(unitId) => {
          if (unitId === null) return;
          gameActions.selectUnit(unitId);
          setClickedUnitId(null);
        }}
        onStartMovePreview={gameActions.startMovePreview}
        onStartAttackPreview={gameActions.startAttackPreview}
        onConfirmMove={gameActions.confirmMove}
        onCancelMove={gameActions.cancelMove}
        onDirectMove={gameActions.directMove}
        onShoot={gameActions.handleShoot}
        onFightAttack={gameActions.handleFightAttack}
        onCharge={gameActions.handleCharge}
        onMoveCharger={gameActions.moveCharger}
        onCancelCharge={gameActions.cancelCharge}
        onValidateCharge={gameActions.validateCharge}
        shootingPhaseState={shootingPhaseState}
        targetPreview={gameState.targetPreview ?? null}
        onCancelTargetPreview={() => {
          if (gameState.targetPreview?.blinkTimer) {
            clearInterval(gameState.targetPreview.blinkTimer);
          }
          actions.setTargetPreview(null);
          
          // Keep the unit selected and stay in attackPreview mode (red hexes)
          if (gameState.selectedUnitId) {
            const selectedUnit = gameState.units.find(u => u.id === gameState.selectedUnitId);
            if (selectedUnit) {
              actions.setAttackPreview({ unitId: gameState.selectedUnitId, col: selectedUnit.col, row: selectedUnit.row });
              actions.setMode("attackPreview");
            }
          }
        }}
        chargeRollPopup={chargeRollPopup}
      />
    </SharedLayout>
  );
};