// frontend/src/pages/GamePage.tsx
import React from 'react';
import { useSearchParams } from 'react-router-dom';
import { SharedLayout } from '../components/SharedLayout';
import { GameController } from '../components/GameController';
import { useGameState } from '../hooks/useGameState';

export const GamePage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const mode = searchParams.get('mode') || 'pvp';
  
  // Use existing game state management
  const { gameState } = useGameState([]);

  return (
    <GameController />
  );
};

export default GamePage;