// src/components/GameController.tsx
import React from "react";
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
  const { gameState, movePreview, attackPreview, shootingPhaseState, actions } = useGameState(gameUnits);
  
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
    boardConfig,  // Add this line
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

  return (
    <div className={`game-controller ${className}`}>
      <main className="main-content">

        <div className="game-area">
          <div className="game-board-section">
            <ErrorBoundary fallback={<div>Failed to load game board</div>}>
            <GameBoard
              units={gameState.units}
              selectedUnitId={gameState.selectedUnitId}
              phase={gameState.phase}
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
              onSelectUnit={(unitId) => {
                if (unitId === null) return;
                
                const unit = gameState.units.find(u => u.id === unitId);
                if (!unit) return;
                
                // Check if unit is selectable based on game rules
                // NEW: Use the same eligibility logic as useGameActions for combat phase
                let isSelectable = false;
                if (gameState.phase === "combat") {
                  // In combat phase, use combat-specific eligibility
                  if (!gameState.unitsAttacked.includes(unitId) && (unit.CUR_HP ?? unit.HP_MAX) > 0) {
                    const combatSubPhase = gameState.combatSubPhase;
                    const combatActivePlayer = gameState.combatActivePlayer;
                    
                    if (combatSubPhase === "charged_units") {
                      // Phase 1: Only active player's charged units
                      isSelectable = unit.player === gameState.currentPlayer && unit.hasChargedThisTurn === true;
                    } else if (combatSubPhase === "alternating_combat") {
                      // Phase 2: Only combat active player's non-charged units
                      isSelectable = unit.player === combatActivePlayer && unit.hasChargedThisTurn !== true;
                    } else {
                      // Fallback
                      isSelectable = unit.player === gameState.currentPlayer;
                    }
                  }
                } else {
                  // Original logic for non-combat phases
                  isSelectable = unit.player === gameState.currentPlayer && 
                    !gameState.unitsMoved.includes(unitId) &&
                    (unit.CUR_HP ?? unit.HP_MAX) > 0;
                }
                
                if (isSelectable) {
                  // Unit is selectable, use normal selection
                  gameActions.selectUnit(unitId);
                  setClickedUnitId(null);
                } else {
                  // Unit is not selectable, show blue highlight
                  setClickedUnitId(unitId);
                  // Clear clicked highlight after 2 seconds
                  setTimeout(() => setClickedUnitId(null), 2000);
                }
              }}
              onStartMovePreview={gameActions.startMovePreview}
              onStartAttackPreview={gameActions.startAttackPreview}
              onConfirmMove={gameActions.confirmMove}
              onCancelMove={gameActions.cancelMove}
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
            />
          </ErrorBoundary>
          </div>

          <div className="unit-status-tables">
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
                  const unit = gameState.units.find(u => u.id === unitId);
                  if (!unit) return;
                  
                  // Check if unit is selectable based on game rules
                  const isSelectable = unit.player === gameState.currentPlayer && 
                    !gameState.unitsMoved.includes(unitId) &&
                    (unit.CUR_HP ?? unit.HP_MAX) > 0;
                  
                  if (isSelectable) {
                    // Unit is selectable, use normal selection
                    const originalSelectFunction = gameState.phase === "charge" ? 
                      gameActions.selectCharger : gameActions.selectUnit;
                    originalSelectFunction(unitId);
                    setClickedUnitId(null);
                  } else {
                    // Unit is not selectable, show blue highlight
                    setClickedUnitId(unitId);
                    // Clear clicked highlight after 2 seconds
                    setTimeout(() => setClickedUnitId(null), 2000);
                  }
                }}
              />
            </ErrorBoundary>

            <ErrorBoundary fallback={<div>Failed to load player 1 status</div>}>
              <UnitStatusTable
                units={gameState.units}
                player={1}
                selectedUnitId={gameState.selectedUnitId}
                clickedUnitId={clickedUnitId}
                onSelectUnit={(unitId) => {
                  const unit = gameState.units.find(u => u.id === unitId);
                  if (!unit) {
                    return;
                  }
                  
                  const isSelectable = unit.player === gameState.currentPlayer && 
                    !gameState.unitsMoved.includes(unitId) &&
                    (unit.CUR_HP ?? unit.HP_MAX) > 0;
                  
                  if (isSelectable) {
                    const originalSelectFunction = gameState.phase === "charge" ? 
                      gameActions.selectCharger : gameActions.selectUnit;
                    originalSelectFunction(unitId);
                    setClickedUnitId(null);
                  } else {
                    setClickedUnitId(unitId);
                    setTimeout(() => {
                      setClickedUnitId(null);
                    }, 2000);
                  }
                }}
              />
            </ErrorBoundary>

            {/* Game Log Component */}
            <ErrorBoundary fallback={<div>Failed to load game log</div>}>
              <GameLog 
                events={gameLog.events}
              />
            </ErrorBoundary>
          </div>
        </div>
      </main>
    </div>
  );
};