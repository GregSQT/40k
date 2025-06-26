// frontend/src/App.tsx
import React from "react";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { GameController } from "./components/GameController";
import initialUnits from "./data/Scenario";
import "./App.css";

export default function App() {
  return (
    <div className="min-h-screen bg-gray-900">
      <div className="app-container">
        <ErrorBoundary>
          <GameController initialUnits={initialUnits} />
        </ErrorBoundary>
      </div>
    </div>
  );
}
