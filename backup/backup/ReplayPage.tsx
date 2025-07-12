// frontend/src/pages/ReplayPage.tsx
import React from 'react';
import { ReplayViewer } from '../components/ReplayViewer';

export const ReplayPage: React.FC = () => {
  const [replayFile, setReplayFile] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const findLatestPhaseBasedReplay = async () => {
      try {
        setLoading(true);
        console.log('🔍 Searching for latest training_replay_*.json file...');
        
        // Call backend API to list files in ai/event_log/
        const response = await fetch('/api/replay-files');
        
        if (!response.ok) {
          throw new Error(`API not available: ${response.status}. Using direct file access fallback.`);
        }
        
        const files = await response.json();
        
        // Find training_replay_*.json files and get the latest
        const phaseReplays = files
          .filter((file: string) => file.startsWith('training_replay_') && file.endsWith('.json'))
          .sort()
          .reverse(); // Get newest first (assuming timestamp in filename)
        
        if (phaseReplays.length > 0) {
          const latestFile = `ai/event_log/${phaseReplays[0]}`;
          console.log(`✅ Found latest phase-based replay: ${latestFile}`);
          setReplayFile(latestFile);
          return;
        }
        
        throw new Error('No training_replay_*.json files found');
        
      } catch (err) {
        console.warn('Backend API unavailable, using fallback:', err);
        
        // Fallback: Try to access the file directly (user must ensure it exists in public folder)
        const fallbackFile = 'ai/event_log/phase_based_replay_20250710_024121.json';
        
        try {
          const response = await fetch(`/${fallbackFile}`);
          if (response.ok) {
            console.log(`✅ Fallback: Found ${fallbackFile}`);
            setReplayFile(fallbackFile);
            return;
          }
        } catch (fallbackErr) {
          console.error('Fallback failed:', fallbackErr);
        }
        
        setError('No replay files found. Please ensure training_replay_*.json files are available or backend API is running.');
      } finally {
        setLoading(false);
      }
    };

    findLatestPhaseBasedReplay();
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-white text-center">
          <div className="animate-spin rounded-full h-16 w-16 border-b-2 border-blue-500 mx-auto mb-4"></div>
          <div>🔍 Finding latest training_replay_*.json...</div>
          <div className="text-sm text-gray-400 mt-2">Checking ai/event_log/ directory</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-white text-center max-w-md">
          <div className="text-red-500 text-xl mb-4">⚠️ No Replay Files</div>
          <div className="text-gray-300 mb-4">{error}</div>
          <div className="text-sm text-gray-400">
            <div className="mb-2">Expected location: ai/event_log/training_replay_*.json</div>
            <div>Make sure training has generated replay files</div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-gray-900">
      <ReplayViewer replayFile={replayFile!} />
    </div>
  );
};

export default ReplayPage;