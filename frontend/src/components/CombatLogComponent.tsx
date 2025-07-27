// frontend/src/components/CombatLogComponent.tsx
import React from 'react';
import { MultipleDiceRoll } from './DiceRollComponent';

export interface CombatStep {
  step: 'shots' | 'range' | 'hit' | 'wound' | 'save' | 'damage';
  status: 'pending' | 'active' | 'complete';
  description: string;
  diceRolls?: number[];
  successes?: number;
  targetValue?: number;
}

export interface CombatResult {
  totalShots: number;
  hits: number;
  wounds: number;
  saves: number;
  damageDealt: number;
  steps: CombatStep[];
}

interface CombatLogProps {
  isVisible: boolean;
  shooterName: string;
  targetName: string;
  currentStep: CombatStep | null;
  combatResult: CombatResult | null;
  onStepComplete: () => void;
  onCombatComplete: () => void;
}

export const CombatLog: React.FC<CombatLogProps> = ({
  isVisible,
  shooterName,
  targetName,
  currentStep,
  combatResult,
  onStepComplete,
  onCombatComplete
}) => {
  if (!isVisible) return null;

  const handleDiceRollComplete = (results: number[]) => {
    // For automatic rolling, we don't need to wait for dice interaction
    // The dice rolls are handled automatically by ShootingSequenceManager
    
    // Immediately proceed to next step (no delay needed for automatic rolling)
    onStepComplete();
  };

  const getStepIcon = (step: string) => {
    switch (step) {
      case 'shots': return '🎯';
      case 'range': return '📏';
      case 'hit': return '🎲';
      case 'wound': return '⚔️';
      case 'save': return '🛡️';
      case 'damage': return '💥';
      default: return '•';
    }
  };

  const getStepColor = (status: string) => {
    switch (status) {
      case 'complete': return 'text-green-600';
      case 'active': return 'text-blue-600';
      case 'pending': return 'text-gray-400';
      default: return 'text-gray-400';
    }
  };

  return (
    <div className="fixed top-4 right-4 bg-white border-2 border-gray-300 rounded-lg shadow-lg p-4 min-w-80 max-w-96 z-50">
      <div className="text-center mb-4">
        <h3 className="text-lg font-bold text-gray-800">Combat Resolution</h3>
        <p className="text-sm text-gray-600">
          <span className="font-medium text-blue-600">{shooterName}</span>
          {' shoots '}
          <span className="font-medium text-red-600">{targetName}</span>
        </p>
      </div>

      {/* Combat Steps Progress */}
      {combatResult && (
        <div className="space-y-2 mb-4">
          {combatResult.steps.map((step, index) => (
            <div
              key={index}
              className={`flex items-center space-x-2 p-2 rounded ${
                step.status === 'active' ? 'bg-blue-50' : 
                step.status === 'complete' ? 'bg-green-50' : 'bg-gray-50'
              }`}
            >
              <span className="text-lg">{getStepIcon(step.step)}</span>
              <span className={`text-sm font-medium ${getStepColor(step.status)}`}>
                {step.description}
              </span>
              {step.status === 'complete' && step.successes !== undefined && (
                <span className="ml-auto text-xs font-bold text-gray-700">
                  {step.successes}/{step.diceRolls?.length || 0}
                </span>
              )}
            </div>
          ))}
        </div>
      )}

        {/* Active Dice Rolling */}
        {currentStep && currentStep.status === 'active' && (
        <div className="border-t pt-4">
            <div className="text-center mb-3">
            <h4 className="font-medium text-gray-800">{currentStep.description}</h4>
            </div>

            {/* Different dice roll display based on step */}
            {currentStep.step === 'hit' && combatResult && (
            <div className="text-center">
                <div className="text-sm font-medium text-gray-700 mb-2">Rolling {combatResult.totalShots} dice to hit</div>
                <div className="text-lg font-bold text-blue-600">
                {currentStep.diceRolls ? `Rolled: ${currentStep.diceRolls.join(', ')}` : 'Rolling...'}
                </div>
                {currentStep.successes !== undefined && (
                <div className="text-sm font-medium text-green-600">
                    {currentStep.successes} hits!
                </div>
                )}
            </div>
            )}

            {currentStep.step === 'wound' && combatResult && (
            <div className="text-center">
                <div className="text-sm font-medium text-gray-700 mb-2">Rolling {combatResult.hits} dice to wound</div>
                <div className="text-lg font-bold text-red-600">
                {currentStep.diceRolls ? `Rolled: ${currentStep.diceRolls.join(', ')}` : 'Rolling...'}
                </div>
                {currentStep.successes !== undefined && (
                <div className="text-sm font-medium text-green-600">
                    {currentStep.successes} wounds!
                </div>
                )}
            </div>
            )}

            {currentStep.step === 'save' && combatResult && (
            <div className="text-center">
                <div className="text-sm font-medium text-gray-700 mb-2">Rolling {combatResult.wounds} armor saves</div>
                <div className="text-lg font-bold text-green-600">
                {currentStep.diceRolls ? `Rolled: ${currentStep.diceRolls.join(', ')}` : 'Rolling...'}
                </div>
                {currentStep.successes !== undefined && (
                <div className="text-sm font-medium text-green-600">
                    {currentStep.successes} saves made!
                </div>
                )}
            </div>
            )}

            {currentStep.step === 'wound' && combatResult && (
            <MultipleDiceRoll
                isVisible={true}
                numberOfDice={combatResult.hits}
                targetValue={currentStep.targetValue}
                onAllRollsComplete={handleDiceRollComplete}
                diceColor="red"
                label="Rolling to Wound"
            />
            )}

            {currentStep.step === 'save' && combatResult && (
            <MultipleDiceRoll
                isVisible={true}
                numberOfDice={combatResult.wounds}
                targetValue={currentStep.targetValue}
                onAllRollsComplete={handleDiceRollComplete}
                diceColor="green"
                label="Rolling Armor Saves"
            />
            )}
        </div>
        )}

      {/* Final Results Summary */}
      {combatResult && combatResult.steps.every(step => step.status === 'complete') && (
        <div className="border-t pt-4 mt-4">
          <h4 className="font-bold text-center mb-3">Combat Summary</h4>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div className="text-gray-600">Shots fired:</div>
            <div className="font-medium">{combatResult.totalShots}</div>
            
            <div className="text-gray-600">Hits:</div>
            <div className="font-medium text-blue-600">{combatResult.hits}</div>
            
            <div className="text-gray-600">Wounds:</div>
            <div className="font-medium text-red-600">{combatResult.wounds}</div>
            
            <div className="text-gray-600">Saves made:</div>
            <div className="font-medium text-green-600">{combatResult.saves}</div>
            
            <div className="text-gray-600 font-bold">Damage dealt:</div>
            <div className="font-bold text-orange-600">{combatResult.damageDealt}</div>
          </div>
          
          <button
            onClick={onCombatComplete}
            className="w-full mt-3 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
          >
            Continue
          </button>
        </div>
      )}
    </div>
  );
};

// Utility function to calculate wound threshold based on Strength vs Toughness
export const calculateWoundThreshold = (strength: number, toughness: number): number => {
  if (strength >= toughness * 2) return 2; // Easy wound
  if (strength > toughness) return 3;       // Normal wound  
  if (strength === toughness) return 4;     // Even match
  if (strength < toughness) return 5;       // Hard wound
  return 6; // Very hard wound (strength < toughness/2)
};

// Utility function to create combat steps
export const createCombatSteps = (
  shots: number,
  hitTarget: number,
  woundTarget: number,
  saveTarget: number
): CombatStep[] => [
  {
    step: 'shots',
    status: 'complete',
    description: `Number of shots: ${shots}`,
  },
  {
    step: 'range',
    status: 'complete',
    description: 'Target in range ✓',
  },
  {
    step: 'hit',
    status: 'pending',
    description: `Rolling ${shots} dice to hit`,
    targetValue: hitTarget,
  },
  {
    step: 'wound',
    status: 'pending',
    description: 'Rolling to wound hits',
    targetValue: woundTarget,
  },
  {
    step: 'save',
    status: 'pending',
    description: 'Target rolling armor saves',
    targetValue: saveTarget,
  },
  {
    step: 'damage',
    status: 'pending',
    description: 'Applying damage',
    targetValue: 0,
  },
];