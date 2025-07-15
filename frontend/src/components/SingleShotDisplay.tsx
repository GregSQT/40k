// frontend/src/components/SingleShotDisplay.tsx
import React from 'react';
import { SingleShotState } from '../types/game';

interface SingleShotDisplayProps {
  singleShotState: SingleShotState | null;
  shooterName: string;
  targetName?: string;
}

export const SingleShotDisplay: React.FC<SingleShotDisplayProps> = ({
  singleShotState,
  shooterName,
  targetName
}) => {
  if (!singleShotState?.isActive) return null;

  const getStepIcon = (step: string) => {
    switch (step) {
      case 'target_selection': return '🎯';
      case 'hit_roll': return '🎲';
      case 'wound_roll': return '⚔️';
      case 'save_roll': return '🛡️';
      case 'damage_application': return '💥';
      default: return '•';
    }
  };

  const getStepDescription = (step: string) => {
    switch (step) {
      case 'target_selection': return 'Select target for this shot';
      case 'hit_roll': return 'Rolling to hit';
      case 'wound_roll': return 'Rolling to wound';
      case 'save_roll': return 'Rolling armor save';
      case 'damage_application': return 'Applying damage';
      default: return step;
    }
  };

  const renderStepResult = () => {
    const { stepResults } = singleShotState;
    
    switch (singleShotState.currentStep) {
      case 'hit_roll':
        if (stepResults.hitRoll !== undefined) {
          return (
            <div className="text-center p-2 bg-blue-50 rounded">
              <div className="text-lg font-bold text-blue-600">
                Hit Roll: {stepResults.hitRoll}
              </div>
              <div className="text-sm text-gray-600">
                {stepResults.hitSuccess ? '✅ HIT!' : '❌ MISS'}
              </div>
            </div>
          );
        }
        break;
        
      case 'wound_roll':
        if (stepResults.woundRoll !== undefined) {
          return (
            <div className="text-center p-2 bg-red-50 rounded">
              <div className="text-lg font-bold text-red-600">
                Wound Roll: {stepResults.woundRoll}
              </div>
              <div className="text-sm text-gray-600">
                {stepResults.woundSuccess ? '✅ WOUND!' : '❌ NO WOUND'}
              </div>
            </div>
          );
        }
        break;
        
      case 'save_roll':
        if (stepResults.saveRoll !== undefined) {
          return (
            <div className="text-center p-2 bg-green-50 rounded">
              <div className="text-lg font-bold text-green-600">
                Save Roll: {stepResults.saveRoll}
              </div>
              <div className="text-sm text-gray-600">
                {stepResults.saveSuccess ? '✅ SAVED' : '❌ FAILED'}
              </div>
            </div>
          );
        }
        break;
        
      case 'damage_application':
        if (stepResults.damageDealt !== undefined) {
          return (
            <div className="text-center p-2 bg-orange-50 rounded">
              <div className="text-lg font-bold text-orange-600">
                💥 {stepResults.damageDealt} Damage Dealt!
              </div>
            </div>
          );
        }
        break;
    }
    
    return null;
  };

  return (
    <div className="fixed top-4 right-4 bg-white border-2 border-gray-300 rounded-lg shadow-lg p-4 min-w-80 max-w-96 z-50">
      <div className="text-center mb-4">
        <h3 className="text-lg font-bold text-gray-800">Individual Shot Resolution</h3>
        <p className="text-sm text-gray-600">
          <span className="font-medium text-blue-600">{shooterName}</span>
          {targetName && (
            <>
              {' shoots '}
              <span className="font-medium text-red-600">{targetName}</span>
            </>
          )}
        </p>
      </div>

      {/* Shot Counter */}
      <div className="text-center mb-4 p-2 bg-gray-100 rounded">
        <div className="text-lg font-bold text-gray-800">
          Shot {singleShotState.currentShotNumber} of {singleShotState.totalShots}
        </div>
        <div className="text-sm text-gray-600">
          {singleShotState.shotsRemaining} shots remaining
        </div>
      </div>

      {/* Current Step */}
      <div className="mb-4">
        <div className="flex items-center space-x-2 p-2 rounded bg-blue-50">
          <span className="text-lg">{getStepIcon(singleShotState.currentStep)}</span>
          <span className="text-sm font-medium text-blue-600">
            {getStepDescription(singleShotState.currentStep)}
          </span>
        </div>
      </div>

      {/* Step Result */}
      {renderStepResult()}

      {/* Target Selection Instructions */}
      {singleShotState.currentStep === 'target_selection' && (
        <div className="mt-4 p-2 bg-yellow-50 rounded border border-yellow-200">
          <p className="text-sm text-yellow-800">
            Click on an enemy unit within range to select target for this shot.
          </p>
        </div>
      )}
    </div>
  );
};