// frontend/src/components/GameController.tsx

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
import { useGameLog } from "../hooks/useGameLog";
import type { Unit, GameMode } from "../types/game";
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
  // Generate default units if none provided
  const [gameUnits, setGameUnits] = useState<Unit[]>(initialUnits || []);
  
  // Detect game mode from URL
  const location = useLocation();
  const gameMode = location.pathname.includes('/replay') ? 'training' :
                   (location.pathname === '/game' && location.search.includes('mode=debug')) ? 'debug' :
                   (location.pathname === '/game' && location.search.includes('mode=pve')) ? 'pve' : 'pvp';
  const isDebugMode = gameMode === 'debug';
                   
  // Track UnitStatusTable collapse states
  const [player1Collapsed, setPlayer1Collapsed] = useState(false);
  const [player2Collapsed, setPlayer2Collapsed] = useState(false);
  
  // NEW: Debug mode state (shared with hex coordinates toggle)
  const [debugMode, setDebugMode] = useState(false);
  
  // Pass debug mode to child components
  const showHexCoordinates = debugMode;
  
  useEffect(() => {
    if (!initialUnits || initialUnits.length === 0) {
      // Initialize UnitFactory and load units from scenario.json
      const loadUnits = async () => {
        try {          
          // Initialize the unit registry first
          const { initializeUnitRegistry, createUnit } = await import('../data/UnitFactory');
          await initializeUnitRegistry();
          
          // Load scenario data
          const response = await fetch('/config/scenario.json');
          const scenarioData = await response.json();
          
          if (scenarioData.units) {
            
            // Transform scenario data using UnitFactory.createUnit()
            interface ScenarioUnit {
              id: number;
              unit_type: string;
              player: number;
              col: number;
              row: number;
            }
            const transformedUnits = scenarioData.units.map((unit: ScenarioUnit) => {
              return createUnit({
                id: unit.id,
                name: `${unit.unit_type}-${unit.id}`,
                type: unit.unit_type,
                player: unit.player as 1 | 2,
                col: unit.col,
                row: unit.row,
                color: unit.player === 1 ? 0x244488 : 0xff3333
              });
            });
            
            setGameUnits(transformedUnits);
          } else {
            throw new Error('No units found in scenario.json');
          }
        } catch (error) {
          throw new Error(`Failed to load units from scenario.json: ${error instanceof Error ? error.message : String(error)}`);
        }
      };
      
      loadUnits();
    }
  }, [initialUnits, isDebugMode]);

  // Initialize game state with custom hook
  const { gameState, movePreview, attackPreview, shootingPhaseState, chargeRollPopup, actions } = useGameState(gameUnits);
  
  // Track clicked (but not selected) units for blue highlighting
  const [clickedUnitId, setClickedUnitId] = useState<number | null>(null);

  // Get board configuration for line of sight calculations
  const { boardConfig, gameConfig } = useGameConfig();

  // Initialize game log hook with live turn tracking - AI_TURN.md compliance
  const gameLog = useGameLog(gameState.currentTurn ?? 1);

  // Set up game actions with game log
  const originalGameActions = useGameActions({
    gameState,
    movePreview,
    attackPreview,
    shootingPhaseState,
    boardConfig: boardConfig as Record<string, unknown> | null | undefined,
    actions: {
      ...actions,
      setMode: (mode: GameMode | null | undefined) => actions.setMode(mode || "select"),
    },
    gameLog,
  });

  // Use original game actions without modification
  const gameActions = originalGameActions;

  // Calculate available height for GameLog dynamically
  const [logAvailableHeight, setLogAvailableHeight] = useState(220);
  
  React.useEffect(() => {
    let resizeObserver: ResizeObserver | null = null;
    
    const calculateLogHeight = () => {
      const gameBoardSection = document.querySelector('.game-board-section');
      const turnPhaseTracker = document.querySelector('.turn-phase-tracker-right');
      const allTables = document.querySelectorAll('.unit-status-table-container');
      const gameLogHeader = document.querySelector('.game-log__header');
      
      if (!gameBoardSection || !turnPhaseTracker || allTables.length < 2 || !gameLogHeader) {
        return;
      }
      
      const player1Table = allTables[0] as HTMLElement;
      const player2Table = allTables[1] as HTMLElement;
      
      // Get actual heights from DOM measurements
      const boardHeight = gameBoardSection.getBoundingClientRect().height;
      const turnPhaseHeight = turnPhaseTracker.getBoundingClientRect().height;
      const player1Height = player1Table.getBoundingClientRect().height;
      const player2Height = player2Table.getBoundingClientRect().height;
      const gameLogHeaderHeight = gameLogHeader.getBoundingClientRect().height;
      
      // Calculate available space: board height minus elements above GameLog
      const usedSpace = turnPhaseHeight + player1Height + player2Height + gameLogHeaderHeight;
      const availableForLogEntries = boardHeight - usedSpace;
    
      // Ensure minimum height
      const finalHeight = Math.max(100, Math.floor(availableForLogEntries));
      setLogAvailableHeight(finalHeight);
    };
    
    // Initial calculation
    const timeoutId = setTimeout(calculateLogHeight, 150);
    
    // Set up ResizeObserver to detect height changes
    resizeObserver = new ResizeObserver(() => {
      calculateLogHeight();
    });
    
    // Observe elements after DOM is ready
    const setupTimeout = setTimeout(() => {
      const gameBoardSection = document.querySelector('.game-board-section');
      const turnPhaseTracker = document.querySelector('.turn-phase-tracker-right');
      const allTables = document.querySelectorAll('.unit-status-table-container');
      const gameLogHeader = document.querySelector('.game-log__header');
      
      if (gameBoardSection) resizeObserver!.observe(gameBoardSection);
      if (turnPhaseTracker) resizeObserver!.observe(turnPhaseTracker);
      if (allTables.length >= 2) {
        resizeObserver!.observe(allTables[0] as Element);
        resizeObserver!.observe(allTables[1] as Element);
      }
      if (gameLogHeader) resizeObserver!.observe(gameLogHeader);
    }, 200);
    
    return () => {
      clearTimeout(timeoutId);
      clearTimeout(setupTimeout);
      if (resizeObserver) resizeObserver.disconnect();
    };
  }, [player1Collapsed, player2Collapsed, gameState.units, gameState.phase]);

  // Calculate eligible units by calling the useGameActions.isUnitEligible function (no duplicate logic)
  const eligibleUnitIds = React.useMemo(() => {
    if (!boardConfig) return [];
    
    return gameState.units.filter(unit => {
      // Call the ACTUAL isUnitEligible function from useGameActions (single source of truth)
      return originalGameActions.isUnitEligible(unit);
    }).map(unit => unit.id);
  }, [gameState.units, boardConfig, originalGameActions]);

  // Initialize shooting phase when entering shoot phase
  React.useEffect(() => {
    if (gameState.phase === 'shoot') {
      actions.initializeShootingPhase();
    }
  }, [gameState.phase, actions]);

  // Initialize fight phase when entering fight phase
  React.useEffect(() => {
    if (gameState.phase === 'fight') {
      actions.initializeFightPhase();
    }
  }, [gameState.phase, actions]);

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
    if (currentTurn >= 1) {
      const currentPhaseKey = `${currentTurn}-${gameState.phase}-${gameState.current_player}`;
      
      if (currentPhaseKey !== lastLoggedPhase.current) {
        gameLog.logPhaseChange(gameState.phase, gameState.current_player ?? 1, currentTurn);
        lastLoggedPhase.current = currentPhaseKey;
      }
    }
  }, [gameState.phase, gameState.current_player, gameState.currentTurn, gameLog]);

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

  const rightColumnContent = (
    <>
      {gameConfig ? (
        <div className="turn-phase-tracker-right">
          <TurnPhaseTracker 
            currentTurn={gameState.currentTurn ?? 1} 
            currentPhase={gameState.phase}
            phases={["command", "move", "shoot", "charge", "fight"]}
            current_player={gameState.current_player}
            maxTurns={(() => {
            if (!gameConfig?.game_rules?.max_turns) {
              throw new Error(`max_turns not found in game configuration. Config structure: ${JSON.stringify(Object.keys(gameConfig || {}))}. Expected: gameConfig.game_rules.max_turns`);
            }
            return gameConfig.game_rules.max_turns;
          })()}
            className=""
          />
          
          <div className="hex-toggle-container">
            <label className="hex-toggle-label" htmlFor="debug-toggle">
              Debug
            </label>
            <div className="hex-toggle-switch">
              <input
                type="checkbox"
                id="debug-toggle"
                className="hex-toggle-input"
                checked={debugMode}
                onChange={(e) => setDebugMode(e.target.checked)}
              />
              <div className={`hex-toggle-track ${debugMode ? 'hex-toggle-track--on' : 'hex-toggle-track--off'}`}>
                <div className={`hex-toggle-thumb ${debugMode ? 'hex-toggle-thumb--on' : 'hex-toggle-thumb--off'}`} />
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="turn-phase-tracker-right">Loading game configuration...</div>
      )}

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

      <ErrorBoundary fallback={<div>Failed to load player 2 status</div>}>
        <UnitStatusTable
          units={gameState.units}
          player={2}
          selectedUnitId={gameState.selectedUnitId ?? null}
          clickedUnitId={clickedUnitId}
          onSelectUnit={(unitId) => {
            gameActions.selectUnit(unitId);
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
          currentTurn={gameState.currentTurn ?? 1}
          debugMode={debugMode}  // NEW: Pass debug mode
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
        showHexCoordinates={showHexCoordinates}
        movePreview={movePreview}
        attackPreview={attackPreview}
        current_player={gameState.current_player}
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
        onActivateCharge={gameActions.handleActivateCharge}
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