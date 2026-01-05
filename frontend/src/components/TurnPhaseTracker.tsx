// frontend/src/components/TurnPhaseTracker.tsx
import React from 'react';

interface TurnPhaseTrackerProps {
  currentTurn: number;
  currentPhase: string;
  phases: string[]; // Required - AI_TURN.md compliance: no config wrappers
  maxTurns: number; // Required - AI_TURN.md compliance: direct data flow
  currentPlayer?: number; // Current player (1 or 2) for P1/P2 buttons
  className?: string;
  onTurnClick?: (turn: number) => void; // Optional callback for turn button clicks (replay mode)
  onPhaseClick?: (phase: string) => void; // Optional callback for phase button clicks (replay mode)
  onPlayerClick?: (player: number) => void; // Optional callback for player button clicks (replay mode)
}

export const TurnPhaseTracker: React.FC<TurnPhaseTrackerProps> = ({
  currentTurn,
  currentPhase,
  phases,
  maxTurns,
  currentPlayer,
  className = "",
  onTurnClick,
  onPhaseClick,
  onPlayerClick
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

  const getTurnStyle = (status: 'passed' | 'current' | 'upcoming', hasClickHandler: boolean): React.CSSProperties => {
    const baseStyle: React.CSSProperties = {
      padding: '4px 8px',
      borderRadius: '4px',
      fontWeight: 'medium',
      fontSize: '14px',
      border: '1px solid',
      cursor: hasClickHandler ? 'pointer' : 'default',
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

  const getPhaseBaseColor = (phase: string): { bg: string; text: string; border: string } => {
    switch (phase.toLowerCase()) {
      case 'command':
        return { bg: '#FCD34D', text: '#FFFFFF', border: '#F59E0B' }; // yellow-300, white, yellow-500
      case 'move':
        return { bg: '#15803D', text: '#FFFFFF', border: '#166534' }; // green-700, white, green-800
        case 'shoot':
          return { bg: '#1D4ED8', text: '#FFFFFF', border: '#1E40AF' }; // blue-700, white, blue-800
        case 'charge':
          return { bg: '#7E22CE', text: '#FFFFFF', border: '#6B21A8' }; // purple-700, white, purple-800
        case 'fight':
          return { bg: '#B91C1C', text: '#FFFFFF', border: '#991B1B' }; // red-700, white, red-800
      default:
        return { bg: '#6B7280', text: '#FFFFFF', border: '#4B5563' }; // grey-500, white, grey-600
    }
  };

  const getPhaseStyle = (phase: string, status: 'passed' | 'current' | 'upcoming', hasClickHandler: boolean): React.CSSProperties => {
    const baseStyle: React.CSSProperties = {
      padding: '4px 8px',
      borderRadius: '4px',
      fontWeight: 'medium',
      fontSize: '14px',
      border: '1px solid',
      cursor: hasClickHandler ? 'pointer' : 'default',
      outline: 'none'
    };
    
    const baseColor = getPhaseBaseColor(phase);
    
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
          backgroundColor: baseColor.bg,
          color: baseColor.text,
          borderColor: baseColor.border,
          fontWeight: 'bold',
          boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)'
        };
      case 'upcoming':
        return {
          ...baseStyle,
          backgroundColor: baseColor.bg + '80', // Add transparency
          color: baseColor.text,
          borderColor: baseColor.border + '80',
          opacity: 0.7
        };
      default:
        return baseStyle;
    }
  };

  const formatPhaseName = (phase: string): string => {
    return phase.charAt(0).toUpperCase() + phase.slice(1);
  };

  const getPlayerStyle = (player: number, isActive: boolean, hasClickHandler: boolean): React.CSSProperties => {
    const baseStyle: React.CSSProperties = {
      padding: '4px 8px',
      borderRadius: '4px',
      fontWeight: 'medium',
      fontSize: '14px',
      border: '1px solid',
      cursor: hasClickHandler ? 'pointer' : 'default',
      outline: 'none'
    };

    const playerColor = player === 1 
      ? { bg: '#1D4ED8', border: '#1E3A8A' } // blue-700, blue-900
      : { bg: '#dc2626', border: '#dc2626' }; // red

    if (isActive) {
      return {
        ...baseStyle,
        backgroundColor: playerColor.bg,
        color: '#FFFFFF',
        borderColor: playerColor.border,
        fontWeight: 'bold',
        boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)'
      };
    } else {
      return {
        ...baseStyle,
        backgroundColor: playerColor.bg + '80', // Add transparency
        color: '#FFFFFF',
        borderColor: playerColor.border + '80',
        opacity: 0.7
      };
    }
  };

    return (
    <div className={className} style={{ background: '#1f2937', border: '1px solid #555', borderRadius: '8px', padding: '8px' }}>
      <div style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
      <div style={{ display: 'flex', gap: '2px' }}>
          {turns.map((turn) => {
            const status = getTurnStatus(turn);
            const style = getTurnStyle(status, !!onTurnClick);

            return (
              <button
                key={turn}
                style={style}
                disabled={!onTurnClick}
                onClick={() => onTurnClick?.(turn)}
              >
                Turn {turn}
              </button>
            );
          })}
        </div>
        {currentPlayer !== undefined && (
          <div style={{ display: 'flex', gap: '2px' }}>
            <button
              style={getPlayerStyle(1, currentPlayer === 1, !!onPlayerClick)}
              onClick={() => onPlayerClick?.(1)}
              disabled={!onPlayerClick}
            >
              P1
            </button>
            <button
              style={getPlayerStyle(2, currentPlayer === 2, !!onPlayerClick)}
              onClick={() => onPlayerClick?.(2)}
              disabled={!onPlayerClick}
            >
              P2
            </button>
          </div>
        )}
        <div style={{ display: 'flex', gap: '2px' }}>
          {phases.map((phase) => {
            const status = getPhaseStatus(phase);
            const style = getPhaseStyle(phase, status, !!onPhaseClick);

            return (
              <button
                key={phase}
                style={style}
                disabled={!onPhaseClick}
                onClick={() => onPhaseClick?.(phase)}
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