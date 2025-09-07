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
  
  // Use phases from props or safely load from config
  const phases = phasesProp || (gameConfig?.gameplay?.phase_order || []);
  
  // Early return if we don't have phases and config is still loading
  if (!phases.length && !gameConfig) {
    return <div className={className}>Loading...</div>;
  }
  
  // Throw error only if config is loaded but phase_order is missing
  if (!phases.length && gameConfig && !gameConfig.gameplay?.phase_order) {
    throw new Error('gameConfig.gameplay.phase_order is required but was not provided');
  }
  
  // Use maxTurns from props or safely load from config
  const effectiveMaxTurns = maxTurns || gameConfig?.game_rules?.max_turns || 5;
  
  // Generate turn numbers array (1-5 turns max for game)
  const maxGameTurns = 5;
  const turns = Array.from({ length: maxGameTurns }, (_, i) => i + 1);
  
  const getTurnStatus = (turn: number): 'passed' | 'current' | 'upcoming' => {
    // Default to turn 1 if currentTurn is undefined
    const actualCurrentTurn = currentTurn || 1;
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
      padding: '4px 8px',
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
      padding: '4px 8px',
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
    <div className={className} style={{ background: '#1f2937', border: '1px solid #555', borderRadius: '8px', padding: '8px' }}>
      <div style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
        <div style={{ display: 'flex', gap: '2px' }}>
          {turns.map((turn) => {
            const status = getTurnStatus(turn);
            const style = getTurnStyle(status);

            return (
              <button
                key={turn}
                style={style}
                disabled
              >
                Turn {turn}
              </button>
            );
          })}
        </div>
        <div style={{ display: 'flex', gap: '2px' }}>
          {phases.map((phase) => {
            const status = getPhaseStatus(phase);
            const style = getPhaseStyle(status);

            return (
              <button
                key={phase}
                style={style}
                disabled
              >
                {formatPhaseName(phase)}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
};