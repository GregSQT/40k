// frontend/src/components/GameController.tsx
import React from 'react';

interface GameControllerProps {
  initialUnits?: any[];
}

export function GameController({ initialUnits = [] }: GameControllerProps) {
  return (
    <div className="min-h-screen bg-gray-900 text-white p-8">
      <div className="max-w-4xl mx-auto">
        <header className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Warhammer 40K Engine</h1>
          <p className="text-gray-300">AI_TURN.md Compliant Implementation</p>
        </header>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-gray-800 p-6 rounded-lg">
            <h2 className="text-xl font-semibold mb-4">Engine Status</h2>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span>Architecture:</span>
                <span className="text-green-400">AI_TURN.md Compliant</span>
              </div>
              <div className="flex justify-between">
                <span>State Management:</span>
                <span className="text-green-400">Single Source</span>
              </div>
              <div className="flex justify-between">
                <span>Step Counting:</span>
                <span className="text-green-400">Built-in</span>
              </div>
              <div className="flex justify-between">
                <span>Activation:</span>
                <span className="text-green-400">Sequential</span>
              </div>
            </div>
          </div>
          
          <div className="bg-gray-800 p-6 rounded-lg">
            <h2 className="text-xl font-semibold mb-4">Implementation Progress</h2>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span>Engine Core:</span>
                <span className="text-yellow-400">In Development</span>
              </div>
              <div className="flex justify-between">
                <span>Movement Phase:</span>
                <span className="text-yellow-400">Planned</span>
              </div>
              <div className="flex justify-between">
                <span>Combat Phase:</span>
                <span className="text-yellow-400">Planned</span>
              </div>
              <div className="flex justify-between">
                <span>Frontend Integration:</span>
                <span className="text-yellow-400">Phase 4</span>
              </div>
            </div>
          </div>
        </div>
        
        <div className="mt-8 bg-gray-800 p-6 rounded-lg">
          <h2 className="text-xl font-semibold mb-4">Unit Registry</h2>
          <p className="text-gray-300 mb-4">Initial units loaded: {initialUnits.length}</p>
          <div className="text-sm text-gray-400">
            Frontend will connect to compliant engine once Phase 0-3 implementation is complete.
          </div>
        </div>
      </div>
    </div>
  );
}