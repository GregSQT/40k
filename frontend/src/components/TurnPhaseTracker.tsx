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
    
    if (phaseIndex < currentPhaseIndex) {
      return 'passed';
    } else if (phaseIndex === currentPhaseIndex) {
      return 'current';
    } else {
      return 'upcoming';
    }
  };

  const getPhaseClassName = (status: 'passed' | 'current' | 'upcoming'): string => {
    const baseClasses = "px-3 py-1 rounded font-medium text-sm border";
    
    switch (status) {
      case 'passed':
        return `${baseClasses} bg-gray-400 text-white border-gray-500`;
      case 'current':
        return `${baseClasses} bg-green-500 text-white border-green-600`;
      case 'upcoming':
        return `${baseClasses} bg-blue-200 text-blue-800 border-blue-300`;
      default:
        return baseClasses;
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
            
            return (
              <button
                key={phase}
                className={getPhaseClassName(status)}
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