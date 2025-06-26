// frontend/src/pages/ReplayPage.tsx
import React from 'react';
import { GameReplayViewer } from '../components/GameReplayViewer';

export const ReplayPage: React.FC = () => {
  return (
    <div className="min-h-screen bg-gray-900">
      <GameReplayViewer replayFile="ai/event_log/train_best_game_replay.json" />
    </div>
  );
};

export default ReplayPage;