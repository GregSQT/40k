// frontend/src/pages/ReplayPage.tsx
import React from 'react';
import { ReplayViewer } from '../components/ReplayViewer';

export const ReplayPage: React.FC = () => {
  return (
    <div className="min-h-screen bg-gray-900">
      <ReplayViewer replayFile="ai/event_log/train_best_game_replay.json" />
    </div>
  );
};

export default ReplayPage;