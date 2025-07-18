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
      <div className="flex items-center space-x-6 px-6 py-3">
        {/* Turn Information */}
        <div className="text-lg font-semibold text-gray-800">
          Turn {currentTurn}
          {effectiveMaxTurns && (
            <span className="text-gray-600"> / {effectiveMaxTurns}</span>
          )}
        </div>

        {/* Phase Buttons */}
        <div className="flex items-center space-x-2">
          {phases.map((phase) => {
            const status = getPhaseStatus(phase);
            const style = getPhaseStyle(status);
            console.log(`Phase ${phase}: status=${status}, style applied`);
            
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