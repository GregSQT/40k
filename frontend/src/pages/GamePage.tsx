// frontend/src/pages/GamePage.tsx
import React, { useEffect, useState } from "react";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { GameController } from "../components/GameController";
import "../App.css";
import { initializeUnitRegistry } from "../data/UnitFactory";

export default function GamePage() {
  const [registryInitialized, setRegistryInitialized] = useState(false);
  const [initError, setInitError] = useState<string | null>(null);
  const [initialUnits, setInitialUnits] = useState<any[]>([]);

  useEffect(() => {
    const initRegistry = async () => {
      try {
        await initializeUnitRegistry();
        
        // Import scenario AFTER registry is ready
        const { default: units } = await import("../data/Scenario");
        setInitialUnits(units);
        setRegistryInitialized(true);
      } catch (error) {
        console.error('❌ Failed to initialize unit registry:', error);
        setInitError(error instanceof Error ? error.message : 'Unknown error');
      }
    };
    
    initRegistry();
  }, []);

  if (initError) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-red-500 text-center">
          <h1>Unit Registry Error</h1>
          <p>{initError}</p>
        </div>
      </div>
    );
  }

  if (!registryInitialized) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-white text-center">
          <h1>Loading Unit Registry...</h1>
          <p>Discovering available units...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-900">
      <ErrorBoundary>
        <GameController initialUnits={initialUnits} />
      </ErrorBoundary>
    </div>
  );
}
