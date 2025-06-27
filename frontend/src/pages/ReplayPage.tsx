// frontend/src/pages/ReplayPage.tsx
import React from 'react';
import { SimpleReplayViewer } from '../components/SimpleReplayViewer';

export const ReplayPage: React.FC = () => {
  return (
    <div className="min-h-screen bg-gray-900">
      <SimpleReplayViewer replayFile="ai/event_log/train_best_game_replay.json" />
    </div>
  );
};

export default ReplayPage;