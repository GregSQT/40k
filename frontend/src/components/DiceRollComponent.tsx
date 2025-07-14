// frontend/src/components/DiceRollComponent.tsx
import React, { useState, useEffect } from 'react';

interface DiceRollProps {
  isVisible: boolean;
  targetValue?: number; // What value is needed to succeed
  onRollComplete: (result: number) => void;
  diceColor?: 'red' | 'blue' | 'green' | 'white';
  size?: 'small' | 'medium' | 'large';
}

export const DiceRoll: React.FC<DiceRollProps> = ({
  isVisible,
  targetValue,
  onRollComplete,
  diceColor = 'white',
  size = 'medium'
}) => {
  const [currentValue, setCurrentValue] = useState<number>(1);
  const [isRolling, setIsRolling] = useState<boolean>(false);
  const [finalResult, setFinalResult] = useState<number | null>(null);

  const sizeClasses = {
    small: 'w-8 h-8 text-sm',
    medium: 'w-12 h-12 text-base',
    large: 'w-16 h-16 text-lg'
  };

  const colorClasses = {
    red: 'bg-red-600 border-red-800',
    blue: 'bg-blue-600 border-blue-800',
    green: 'bg-green-600 border-green-800',
    white: 'bg-gray-100 border-gray-300 text-black'
  };

  useEffect(() => {
    if (isVisible && !isRolling && finalResult === null) {
      startRoll();
    }
  }, [isVisible]);

  const startRoll = () => {
    setIsRolling(true);
    setFinalResult(null);
    
    // Animate dice rolling for 1 second
    const rollInterval = setInterval(() => {
      setCurrentValue(Math.floor(Math.random() * 6) + 1);
    }, 100);

    setTimeout(() => {
      clearInterval(rollInterval);
      const result = Math.floor(Math.random() * 6) + 1;
      setCurrentValue(result);
      setFinalResult(result);
      setIsRolling(false);
      onRollComplete(result);
    }, 1000);
  };

  const getSuccessStatus = () => {
    if (finalResult === null || targetValue === undefined) return null;
    return finalResult >= targetValue ? 'success' : 'failure';
  };

  const successStatus = getSuccessStatus();

  if (!isVisible) return null;

  return (
    <div className="flex flex-col items-center space-y-2">
      <div
        className={`
          ${sizeClasses[size]}
          ${colorClasses[diceColor]}
          border-2 rounded-lg
          flex items-center justify-center
          font-bold shadow-lg
          transition-all duration-200
          ${isRolling ? 'animate-pulse scale-110' : ''}
          ${successStatus === 'success' ? 'ring-2 ring-green-400' : ''}
          ${successStatus === 'failure' ? 'ring-2 ring-red-400' : ''}
        `}
      >
        {currentValue}
      </div>
      
      {targetValue && finalResult !== null && (
        <div className={`text-xs font-medium ${
          successStatus === 'success' ? 'text-green-600' : 'text-red-600'
        }`}>
          {successStatus === 'success' ? 'HIT!' : 'MISS!'}
        </div>
      )}
    </div>
  );
};

interface MultipleDiceRollProps {
  isVisible: boolean;
  numberOfDice: number;
  targetValue?: number;
  onAllRollsComplete: (results: number[]) => void;
  diceColor?: 'red' | 'blue' | 'green' | 'white';
  label?: string;
}

export const MultipleDiceRoll: React.FC<MultipleDiceRollProps> = ({
  isVisible,
  numberOfDice,
  targetValue,
  onAllRollsComplete,
  diceColor = 'white',
  label
}) => {
  const [completedRolls, setCompletedRolls] = useState<number[]>([]);
  const [activeRoll, setActiveRoll] = useState<number>(0);

  useEffect(() => {
    if (isVisible) {
      setCompletedRolls([]);
      setActiveRoll(0);
    }
  }, [isVisible]);

  useEffect(() => {
    if (completedRolls.length === numberOfDice && completedRolls.length > 0) {
      onAllRollsComplete(completedRolls);
    }
  }, [completedRolls, numberOfDice, onAllRollsComplete]);

  const handleSingleRollComplete = (result: number) => {
    setCompletedRolls(prev => [...prev, result]);
    setActiveRoll(prev => prev + 1);
  };

  if (!isVisible || numberOfDice === 0) return null;

  return (
    <div className="flex flex-col items-center space-y-4">
      {label && (
        <div className="text-sm font-medium text-gray-700">{label}</div>
      )}
      
      <div className="flex flex-wrap gap-2 justify-center max-w-xs">
        {Array.from({ length: numberOfDice }).map((_, index) => (
          <DiceRoll
            key={index}
            isVisible={index === activeRoll}
            targetValue={targetValue}
            onRollComplete={handleSingleRollComplete}
            diceColor={diceColor}
            size="medium"
          />
        ))}
        
        {/* Show completed dice results */}
        {completedRolls.slice(0, -1).map((result, index) => (
          <div
            key={`completed-${index}`}
            className={`
              w-12 h-12 border-2 rounded-lg
              flex items-center justify-center
              font-bold text-base
              ${colorClasses[diceColor]}
              ${result >= (targetValue || 0) ? 'ring-2 ring-green-400' : 'ring-2 ring-red-400'}
            `}
          >
            {result}
          </div>
        ))}
      </div>
      
      {targetValue && (
        <div className="text-xs text-gray-600">
          Need {targetValue}+ to succeed
        </div>
      )}
    </div>
  );
};

// Re-export color classes for external use
export const colorClasses = {
  red: 'bg-red-600 border-red-800',
  blue: 'bg-blue-600 border-blue-800', 
  green: 'bg-green-600 border-green-800',
  white: 'bg-gray-100 border-gray-300 text-black'
};