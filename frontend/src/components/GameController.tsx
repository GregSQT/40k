// src/components/GameController.tsx
import React from "react";
import { useLocation } from 'react-router-dom';
import { SharedLayout } from "./SharedLayout";
import { ErrorBoundary } from "./ErrorBoundary";
import { UnitStatusTable } from "./UnitStatusTable";
import { GameBoard } from "./GameBoard";
import { GameStatus } from "./GameStatus";
import { GameLog } from "./GameLog";
import { useGameState } from "../hooks/useGameState";
import { useGameActions } from "../hooks/useGameActions";
import { useGameConfig } from "../hooks/useGameConfig";
import { useAIPlayer } from "../hooks/useAIPlayer";
import { usePhaseTransition } from "../hooks/usePhaseTransition";
import { useGameLog } from "../hooks/useGameLog";
import { Unit } from "../types/game";
import { useState, useEffect } from "react";
import { createUnit, getAvailableUnitTypes } from "../data/UnitFactory";
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
  const gameMode = location.pathname.includes('/pve') ? 'pve' : 
                   location.pathname.includes('/replay') ? 'training' : 'pvp';
                   
  // Track UnitStatusTable collapse states
  const [player0Collapsed, setPlayer0Collapsed] = useState(false);
  const [player1Collapsed, setPlayer1Collapsed] = useState(false);
  
  useEffect(() => {
    if (!initialUnits || initialUnits.length === 0) {
      // Generate units dynamically using available types
      const availableTypes = getAvailableUnitTypes();
      
      if (availableTypes.length >= 4) {
        const dynamicUnits: Unit[] = [
          createUnit({
            id: 0,
            name: "P-I",
            type: availableTypes.includes('Intercessor') ? 'Intercessor' : availableTypes[0],
            player: 0,
            col: 23,
            row: 12,
            color: 0x244488,
          }),
          createUnit({
            id: 1,
            name: "P-A",
            type: availableTypes.includes('AssaultIntercessor') ? 'AssaultIntercessor' : availableTypes[1],
            player: 0,
            col: 1,
            row: 12,
            color: 0xff3333,
          }),
          createUnit({
            id: 2,
            name: "A-T",
            type: availableTypes.includes('Termagant') ? 'Termagant' : availableTypes[2] || availableTypes[0],
            player: 1,
            col: 0,
            row: 5,
            color: 0x882222,
          }),
          createUnit({
            id: 3,
            name: "A-H",
            type: availableTypes.includes('Hormagaunt') ? 'Hormagaunt' : availableTypes[3] || availableTypes[1],
            player: 1,
            col: 22,
            row: 3,
            color: 0x6633cc,
          }),
        ];
        setGameUnits(dynamicUnits);
      }
    }
  }, [initialUnits]);

  // Initialize game state with custom hook
  const { gameState, movePreview, attackPreview, shootingPhaseState, chargeRollPopup, actions } = useGameState(gameUnits);
  
  // Track clicked (but not selected) units for blue highlighting
  const [clickedUnitId, setClickedUnitId] = useState<number | null>(null);

  // Get board configuration for line of sight calculations
  const { boardConfig } = useGameConfig();

  // Initialize game log hook
  const gameLog = useGameLog();

  // Set up game actions with game log
  const originalGameActions = useGameActions({
    gameState,
    movePreview,
    attackPreview,
    shootingPhaseState,
    boardConfig,
    actions,
    gameLog,
  });

  // Use original game actions without modification
  const gameActions = originalGameActions;

  // Calculate available height for GameLog dynamically
  const [logAvailableHeight, setLogAvailableHeight] = useState(220);
  
  React.useEffect(() => {
    // Calculate space taken by UnitStatusTables
    const HEADER_HEIGHT = 60; // TurnPhaseTracker height
    const TABLE_HEADER_HEIGHT = 45; // Each table header
    const ROW_HEIGHT = 35; // Each unit row height
    const COLLAPSED_HEIGHT = 45; // Just header when collapsed
    
    // Count units per player
    const player0Units = gameState.units.filter(u => u.player === 0 && (u.CUR_HP ?? u.HP_MAX) > 0).length;
    const player1Units = gameState.units.filter(u => u.player === 1 && (u.CUR_HP ?? u.HP_MAX) > 0).length;
    
    // Calculate actual table heights
    const player0Height = player0Collapsed ? COLLAPSED_HEIGHT : (TABLE_HEADER_HEIGHT + (player0Units * ROW_HEIGHT));
    const player1Height = player1Collapsed ? COLLAPSED_HEIGHT : (TABLE_HEADER_HEIGHT + (player1Units * ROW_HEIGHT));
    
    // Assume total available space is ~800px, subtract used space
    const TOTAL_SPACE = 800;
    const usedSpace = HEADER_HEIGHT + player0Height + player1Height + 60; // 60px for margins/padding
    const availableForLog = Math.max(100, TOTAL_SPACE - usedSpace); // Minimum 100px
    
    console.log(`Height calculation DEBUG:`);
    console.log(`- Player0: collapsed=${player0Collapsed}, units=${player0Units}, height=${player0Height}px`);
    console.log(`- Player1: collapsed=${player1Collapsed}, units=${player1Units}, height=${player1Height}px`);
    console.log(`- Total space=${TOTAL_SPACE}px, used=${usedSpace}px, available=${availableForLog}px`);
    console.log(`- Calculated rows: ${Math.floor(availableForLog / 52)}`);
    setLogAvailableHeight(availableForLog);
  }, [player0Collapsed, player1Collapsed, gameState.units]);

  // Calculate eligible units by calling the useGameActions.isUnitEligible function (no duplicate logic)
  const eligibleUnitIds = React.useMemo(() => {
    if (!boardConfig) return [];
    
    return gameState.units.filter(unit => {
      // Call the ACTUAL isUnitEligible function from useGameActions (single source of truth)
      return originalGameActions.isUnitEligible(unit);
    }).map(unit => unit.id);
  }, [gameState.units, boardConfig, originalGameActions.isUnitEligible, gameState.phase, gameState.currentPlayer, gameState.unitsMoved, gameState.unitsCharged, gameState.unitsAttacked, gameState.unitsFled]);

  // Handle AI player behavior
  useAIPlayer({
    gameState,
    gameActions: {
      ...gameActions,
      addMovedUnit: actions.addMovedUnit,
      addChargedUnit: actions.addChargedUnit,
      addAttackedUnit: actions.addAttackedUnit,
      updateUnit: actions.updateUnit,
    },
    enabled: false,  // Disable AI - player controls all units
  });

  // Manage phase transitions
  // Manage phase transitions
  usePhaseTransition({
    gameState,
    boardConfig,
    isUnitEligible: originalGameActions.isUnitEligible, // Pass the authoritative eligibility function
    actions: {
      setPhase: actions.setPhase,
      setCurrentPlayer: actions.setCurrentPlayer,
      setSelectedUnitId: actions.setSelectedUnitId,
      setMode: actions.setMode,
      resetMovedUnits: actions.resetMovedUnits,
      resetChargedUnits: actions.resetChargedUnits,
      resetAttackedUnits: actions.resetAttackedUnits,
      resetFledUnits: actions.resetFledUnits,
      initializeCombatPhase: actions.initializeCombatPhase,
      setCurrentTurn: actions.setCurrentTurn,
      setCombatSubPhase: actions.setCombatSubPhase,
      setCombatActivePlayer: actions.setCombatActivePlayer,
      setUnits: actions.setUnits,
    },
  });
  // Initialize shooting phase when entering shoot phase
  React.useEffect(() => {
    if (gameState.phase === 'shoot') {
      actions.initializeShootingPhase();
    }
  }, [gameState.phase]);

  // Initialize combat phase when entering combat phase
  React.useEffect(() => {
    if (gameState.phase === 'combat') {
      actions.initializeCombatPhase();
    }
  }, [gameState.phase]);

  // Track turn changes with ref to prevent infinite loops
  const lastLoggedTurn = React.useRef<number>(0);
  
  React.useEffect(() => {
    if (gameState.currentTurn > 1 && gameState.currentTurn !== lastLoggedTurn.current) {
      gameLog.logTurnStart(gameState.currentTurn);
      lastLoggedTurn.current = gameState.currentTurn;
    }
  }, [gameState.currentTurn, gameLog]);

  // Track phase changes with ref to prevent duplicates
  const lastLoggedPhase = React.useRef<string>('');
  
  React.useEffect(() => {
    if (gameState.currentTurn >= 1) { // Only log phases after game starts
      const currentPhaseKey = `${gameState.currentTurn}-${gameState.phase}-${gameState.currentPlayer}`;
      
      if (currentPhaseKey !== lastLoggedPhase.current) {
        gameLog.logPhaseChange(gameState.phase, gameState.currentPlayer, gameState.currentTurn);
        lastLoggedPhase.current = currentPhaseKey;
      }
    }
  }, [gameState.phase, gameState.currentPlayer, gameState.currentTurn, gameLog]);

  // Track unit deaths
  React.useEffect(() => {
    const deadUnits = gameState.units.filter(unit => (unit.CUR_HP ?? unit.HP_MAX) <= 0);
    deadUnits.forEach(unit => {
      // Check if we haven't already logged this death
      const alreadyLogged = gameLog.events.some(event => 
        event.type === 'death' && 
        event.unitId === unit.id
      );
      
      if (!alreadyLogged) {
        gameLog.logUnitDeath(unit, gameState.currentTurn);
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
    previousSelectedUnit.current = gameState.selectedUnitId;
  }, [gameState.selectedUnitId]);

  const rightColumnContent = (
    <>
      <TurnPhaseTracker 
        currentTurn={gameState.currentTurn} 
        currentPhase={gameState.phase}
        className="turn-phase-tracker-right"
      />
      <ErrorBoundary fallback={<div>Failed to load player 0 status</div>}>
        <UnitStatusTable
          units={gameState.units}
          player={0}
          selectedUnitId={gameState.selectedUnitId}
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
          selectedUnitId={gameState.selectedUnitId}
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
        selectedUnitId={gameState.selectedUnitId}
        phase={gameState.phase}
        eligibleUnitIds={eligibleUnitIds}
        mode={gameState.mode}
        movePreview={movePreview}
        attackPreview={attackPreview}
        currentPlayer={gameState.currentPlayer}
        unitsMoved={gameState.unitsMoved}
        unitsCharged={gameState.unitsCharged}
        unitsAttacked={gameState.unitsAttacked}
        unitsFled={gameState.unitsFled}
        combatSubPhase={gameState.combatSubPhase}
        combatActivePlayer={gameState.combatActivePlayer}
        currentTurn={gameState.currentTurn}
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
        onCombatAttack={gameActions.handleCombatAttack}
        onCharge={gameActions.handleCharge}
        onMoveCharger={gameActions.moveCharger}
        onCancelCharge={gameActions.cancelCharge}
        onValidateCharge={gameActions.validateCharge}
        shootingPhaseState={shootingPhaseState}
        targetPreview={gameState.targetPreview}
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