// frontend/src/components/TurnPhaseTracker.tsx
import React from 'react';
import { useGameConfig } from '../hooks/useGameConfig';

interface TurnPhaseTrackerProps {
  currentTurn: number;
  currentPhase: string;
  phases?: string[]; // Optional - will load from config if not provided
  maxTurns?: number;
  className?: string;
}

export const TurnPhaseTracker: React.FC<TurnPhaseTrackerProps> = ({
  currentTurn,
  currentPhase,
  phases: phasesProp,
  maxTurns,
  className = ""
}) => {
  const { gameConfig } = useGameConfig();
  
  // Use phases from props or fallback to config
  const phases = phasesProp || gameConfig?.gameplay?.phase_order || ['move', 'shoot', 'charge', 'combat'];
  
  // Use maxTurns from props or fallback to config
  const effectiveMaxTurns = maxTurns || gameConfig?.game_rules?.max_turns;
  
  // Generate turn numbers array (1-5 turns max for game)
  const maxGameTurns = 5;
  const turns = Array.from({ length: maxGameTurns }, (_, i) => i + 1);
  
  const getTurnStatus = (turn: number): 'passed' | 'current' | 'upcoming' => {
    // Default to turn 1 if currentTurn is undefined
    const actualCurrentTurn = currentTurn || 1;
    console.log(`Turn ${turn}, currentTurn: ${currentTurn}, actualCurrentTurn: ${actualCurrentTurn}`);
    if (turn < actualCurrentTurn) {
      return 'passed';
    } else if (turn === actualCurrentTurn) {
      return 'current';
    } else {
      return 'upcoming';
    }
  };

  const getTurnStyle = (status: 'passed' | 'current' | 'upcoming'): React.CSSProperties => {
    const baseStyle: React.CSSProperties = {
      padding: '6px 12px',
      borderRadius: '4px',
      fontWeight: 'medium',
      fontSize: '14px',
      border: '1px solid',
      cursor: 'default',
      outline: 'none'
    };
    
    switch (status) {
      case 'passed':
        return {
          ...baseStyle,
          backgroundColor: '#6B7280', // grey-500
          color: '#FFFFFF',
          borderColor: '#4B5563' // grey-600
        };
      case 'current':
        return {
          ...baseStyle,
          backgroundColor: '#059669', // green-600
          color: '#FFFFFF',
          borderColor: '#047857', // green-700
          fontWeight: 'bold',
          boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)'
        };
      case 'upcoming':
        return {
          ...baseStyle,
          backgroundColor: '#BFDBFE', // blue-200
          color: '#1E40AF', // blue-800
          borderColor: '#93C5FD' // blue-300
        };
      default:
        return baseStyle;
    }
  };

  const getPhaseStatus = (phase: string): 'passed' | 'current' | 'upcoming' => {
    const currentPhaseIndex = phases.indexOf(currentPhase);
    const phaseIndex = phases.indexOf(phase);
    
    if (currentPhaseIndex === -1 || phaseIndex === -1) {
      return 'upcoming';
    }
    
    if (phaseIndex < currentPhaseIndex) {
      return 'passed';
    } else if (phaseIndex === currentPhaseIndex) {
      return 'current';
    } else {
      return 'upcoming';
    }
  };

  const getPhaseStyle = (status: 'passed' | 'current' | 'upcoming'): React.CSSProperties => {
    const baseStyle: React.CSSProperties = {
      padding: '6px 12px',
      borderRadius: '4px',
      fontWeight: 'medium',
      fontSize: '14px',
      border: '1px solid',
      cursor: 'default',
      outline: 'none'
    };
    
    switch (status) {
      case 'passed':
        return {
          ...baseStyle,
          backgroundColor: '#6B7280', // grey-500
          color: '#FFFFFF',
          borderColor: '#4B5563' // grey-600
        };
      case 'current':
        return {
          ...baseStyle,
          backgroundColor: '#059669', // green-600
          color: '#FFFFFF',
          borderColor: '#047857', // green-700
          fontWeight: 'bold',
          boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)'
        };
      case 'upcoming':
        return {
          ...baseStyle,
          backgroundColor: '#BFDBFE', // blue-200
          color: '#1E40AF', // blue-800
          borderColor: '#93C5FD' // blue-300
        };
      default:
        return baseStyle;
    }
  };

  const formatPhaseName = (phase: string): string => {
    return phase.charAt(0).toUpperCase() + phase.slice(1);
  };
      return (
    <div className={`bg-white border-b border-gray-200 shadow-sm ${className}`}>
      <div className="flex items-center px-6 py-3 w-full overflow-hidden">
        <div className="flex items-center space-x-2 flex-shrink-0">
          {turns.map((turn) => {
            const status = getTurnStatus(turn);
            const style = getTurnStyle(status);

            return (
              <button
                key={turn}
                style={style}
                className="min-w-0"
                disabled
              >
                Turn {turn}
              </button>
            );
          })}
        </div>
        <div className="ml-auto overflow-hidden">
          <div className="flex items-center justify-end space-x-2 flex-nowrap overflow-x-auto">
            {phases.map((phase) => {
              const status = getPhaseStatus(phase);
              const style = getPhaseStyle(status);

              return (
                <button
                  key={phase}
                  style={{
                    ...style,
                    fontSize: '0.85rem'
                  }}
                  className="min-w-0"
                  disabled
                >
                  {formatPhaseName(phase)}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );



};