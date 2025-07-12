// frontend/src/pages/HomePage.tsx
import React from "react";
import { Link } from "react-router-dom";

export default function HomePage() {
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
}
