// frontend/src/pages/PlayerVsAIPage.tsx
import React, { useEffect, useState } from "react";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { GameController } from "../components/GameController";
import "../App.css";
import { initializeUnitRegistry } from "../data/UnitFactory";

export default function PlayerVsAIPage() {
  const [registryInitialized, setRegistryInitialized] = useState(false);
  const [initError, setInitError] = useState<string | null>(null);
  const [initialUnits, setInitialUnits] = useState<any[]>([]);

  useEffect(() => {
    const initRegistry = async () => {
      try {
        await initializeUnitRegistry();
        
        // Import PvE scenario AFTER registry is ready
        // Use same scenario as PvP but mark Player 1 as AI-controlled
        const { default: units } = await import("../data/Scenario");
        
        // Ensure Player 1 units are marked for AI control
        const pveUnits = units.map(unit => ({
          ...unit,
          // Add AI metadata for Player 1 units
          isAIControlled: unit.player === 1,
          aiDifficulty: 'normal', // Could be configurable later
        }));
        
        setInitialUnits(pveUnits);
        setRegistryInitialized(true);
      } catch (error) {
        console.error('❌ Failed to initialize PvE unit registry:', error);
        setInitError(error instanceof Error ? error.message : 'Unknown error');
      }
    };
    
    initRegistry();
  }, []);

  if (initError) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-red-500 text-center">
          <h1 className="text-2xl font-bold mb-4">Player vs AI Setup Error</h1>
          <p>{initError}</p>
          <button 
            onClick={() => window.location.reload()} 
            className="mt-4 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!registryInitialized) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-white text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-white mx-auto mb-4"></div>
          <h1 className="text-xl font-bold mb-2">Initializing Player vs AI...</h1>
          <p className="text-gray-400">Loading unit registry and AI opponent...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-900">
      <ErrorBoundary>
        {/* Header indicating PvE mode */}
        <div className="bg-purple-900 border-b border-purple-700 px-4 py-2">
          <div className="flex items-center justify-between">
            <h1 className="text-purple-100 font-bold">
              🤖 Player vs AI Mode
            </h1>
            <div className="text-purple-300 text-sm">
              You are Player 0 (Blue) • AI is Player 1 (Red)
            </div>
          </div>
        </div>
        
        {/* Use existing GameController with PvE units */}
        <GameController 
          initialUnits={initialUnits}
          className="pve-mode"
        />
      </ErrorBoundary>
    </div>
  );
}