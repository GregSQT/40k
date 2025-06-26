// frontend/src/App.tsx
import React from "react";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { GameController } from "./components/GameController";
import initialUnits from "./data/Scenario";
import "./App.css";
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import ReplayPage from './pages/ReplayPage';

// Simple HomePage component
const HomePage: React.FC = () => {
  return (
    <div className="min-h-screen bg-gray-900 text-white flex items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold mb-6">Warhammer 40K Tactics</h1>
        <p className="text-xl mb-8 text-gray-300">
          Tactical combat game with AI opponents
        </p>
        <div className="space-x-4">
          <Link 
            to="/game" 
            className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-500 inline-block"
          >
            Start Game
          </Link>
          <Link 
            to="/replay" 
            className="px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-500 inline-block"
          >
            Watch Replay
          </Link>
        </div>
      </div>
    </div>
  );
};

// GamePage component using your existing GameController
const GamePage: React.FC = () => {
  return (
    <div className="min-h-screen bg-gray-900">
      <div className="app-container">
        <ErrorBoundary>
          <GameController initialUnits={initialUnits} />
        </ErrorBoundary>
      </div>
    </div>
  );
};

function App() {
  return (
    <Router>
      <div className="min-h-screen bg-gray-900 text-white">
        {/* Navigation */}
        <nav className="bg-gray-800 p-4">
          <div className="max-w-7xl mx-auto flex space-x-4">
            <Link to="/" className="text-blue-400 hover:text-blue-300">Home</Link>
            <Link to="/game" className="text-blue-400 hover:text-blue-300">Game</Link>
            <Link to="/replay" className="text-blue-400 hover:text-blue-300">Replay</Link>
          </div>
        </nav>

        {/* Routes */}
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/game" element={<GamePage />} />
          <Route path="/replay" element={<ReplayPage />} />
        </Routes>
      </div>
    </Router>
  );
}

export default App;