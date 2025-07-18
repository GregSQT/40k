// src/components/GameController.tsx
import React from "react";
import { ErrorBoundary } from "./ErrorBoundary";
import { UnitStatusTable } from "./UnitStatusTable";
import { GameBoard } from "./GameBoard";
import { GameStatus } from "./GameStatus";
import { GameLog } from "./GameLog";
import { useGameState } from "../hooks/useGameState";
import { useGameActions } from "../hooks/useGameActions";
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
  className = "",
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

  // Initialize game log hook
  const gameLog = useGameLog();

  // Set up game actions with game log
  const gameActions = useGameActions({
    gameState,
    movePreview,
    attackPreview,
    shootingPhaseState,
    actions,
    gameLog,
  });

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
  usePhaseTransition({
    gameState,
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
              currentTurn={gameState.currentTurn}
              onSelectUnit={gameState.phase === "charge" ? gameActions.selectCharger : gameActions.selectUnit}
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
                onSelectUnit={gameState.phase === "charge" ? 
                  gameActions.selectCharger : gameActions.selectUnit}
              />
            </ErrorBoundary>

            <ErrorBoundary fallback={<div>Failed to load player 1 status</div>}>
              <UnitStatusTable
                units={gameState.units}
                player={1}
                selectedUnitId={gameState.selectedUnitId}
                onSelectUnit={gameState.phase === "charge" ? 
                  gameActions.selectCharger : gameActions.selectUnit}
              />
            </ErrorBoundary>

            {/* Game Log Component */}
            <ErrorBoundary fallback={<div>Failed to load game log</div>}>
              <GameLog 
                events={gameLog.events}
                maxEvents={50}
              />
            </ErrorBoundary>
          </div>
        </div>

        <footer className="game-footer">
          <GameStatus
            currentPlayer={gameState.currentPlayer}
            phase={gameState.phase}
            units={gameState.units}
            unitsMoved={gameState.unitsMoved}
            unitsCharged={gameState.unitsCharged}
            unitsAttacked={gameState.unitsAttacked}
            unitsFled={gameState.unitsFled}
          />
        </footer>
      </main>
    </div>
  );
};