// components/GameStatus.tsx
import { memo } from 'react';
import type { GameState, Unit, UnitId } from '../types';

interface GameStatusProps {
  currentPlayer: GameState['currentPlayer'];
  phase: GameState['phase'];
  units: Unit[];
  unitsMoved: UnitId[];
  unitsCharged: UnitId[];
  unitsAttacked: UnitId[];
  unitsFled: UnitId[];  // ✅ ADD THIS LINE
}

const PHASE_LABELS = {
  move: 'Movement',
  shoot: 'Shooting',
  charge: 'Charge',
  fight: 'Fight',
} as const;

const PLAYER_LABELS = {
  0: 'Player 1',
  1: 'Player 2 (AI)',
} as const;

export const GameStatus = memo<GameStatusProps>(({
  currentPlayer,
  phase,
  units,
  unitsMoved,
  unitsCharged,
  unitsAttacked,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  unitsFled: _unitsFled,
}) => {
  // Get current player's units that have acted
  // Note: unitsFled.length could be used for future statistics
  const currentPlayerUnits = units.filter(u => u.player === currentPlayer);
  
  const getActedUnits = () => {
    switch (phase) {
      case 'move':
      case 'shoot':
        return currentPlayerUnits.filter(u => unitsMoved.includes(u.id));
      case 'charge':
        return currentPlayerUnits.filter(u => unitsCharged.includes(u.id));
      case 'fight':
        return currentPlayerUnits.filter(u => unitsAttacked.includes(u.id));
      default:
        return [];
    }
  };

  const actedUnits = getActedUnits();
  const actedUnitNames = actedUnits.map(u => u.name).join(', ') || 'None';

  // Calculate game statistics
  const player1Units = units.filter(u => u.player === 0);
  const player2Units = units.filter(u => u.player === 1);
  
  const player1HP = player1Units.reduce((total, unit) => total + (unit.HP_CUR ?? unit.HP_MAX), 0);
  const player2HP = player2Units.reduce((total, unit) => total + (unit.HP_CUR ?? unit.HP_MAX), 0);

  return (
    <div className="game-status">
      <div className="game-status__row">
        <span className="game-status__label">Current Player:</span>{' '}
        <span className="game-status__value">
          {currentPlayer !== undefined ? PLAYER_LABELS[currentPlayer] : 'Unknown Player'}
        </span>
      </div>
      
      <div className="game-status__row">
        <span className="game-status__label">Phase:</span>{' '}
        <span className="game-status__value">
          {PHASE_LABELS[phase]}
        </span>
      </div>

      <div className="game-status__row">
        <span className="game-status__label">
          Units {phase === 'fight' ? 'attacked' : phase === 'charge' ? 'charged' : 'acted'}:
        </span>{' '}
        <span className={`game-status__value ${actedUnits.length === 0 ? 'game-status__value--empty' : ''}`}>
          {actedUnitNames}
        </span>
      </div>

      <div className="game-status__row">
        <span className="game-status__label">Progress:</span>{' '}
        <span className="game-status__value">
          {actedUnits.length} / {currentPlayerUnits.length}
        </span>
      </div>

      <div className="game-status__divider" style={{ margin: '12px 0', height: '1px', backgroundColor: '#444' }} />

      <div className="game-status__row">
        <span className="game-status__label">Player 1 Units:</span>{' '}
        <span className="game-status__value">
          {player1Units.length} ({player1HP} HP)
        </span>
      </div>

      <div className="game-status__row">
        <span className="game-status__label">Player 2 Units:</span>{' '}
        <span className="game-status__value">
          {player2Units.length} ({player2HP} HP)
        </span>
      </div>
    </div>
  );
});

GameStatus.displayName = 'GameStatus';