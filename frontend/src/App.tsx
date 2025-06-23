// src/App.tsx
import React from "react";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { GameController } from "./components/GameController";
import initialUnits from "./data/Scenario";
import "./App.css";

export default function App() {
  return (
    <ErrorBoundary>
      <div className="app-container">
        <GameController initialUnits={initialUnits} />
      </div>
    </ErrorBoundary>
  );
}