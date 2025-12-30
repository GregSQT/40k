// frontend/src/components/TurnPhaseTracker.tsx
import React from 'react';

interface TurnPhaseTrackerProps {
  currentTurn: number;
  currentPhase: string;
  phases: string[]; // Required - AI_TURN.md compliance: no config wrappers
  maxTurns: number; // Required - AI_TURN.md compliance: direct data flow
  className?: string;
}

export const TurnPhaseTracker: React.FC<TurnPhaseTrackerProps> = ({
  currentTurn,
  currentPhase,
  phases,
  maxTurns,
  className = ""
}) => {
  
  // Validate required props (raise errors for missing data)
  if (!phases || phases.length === 0) {
    throw new Error('TurnPhaseTracker: phases array is required and cannot be empty');
  }
  if (!maxTurns || maxTurns <= 0) {
    throw new Error('TurnPhaseTracker: maxTurns must be a positive number');
  }
  
  // Generate turn numbers array based on provided maxTurns
  const turns = Array.from({ length: maxTurns }, (_, i) => i + 1);
  
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