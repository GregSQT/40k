// frontend/src/pages/ReplayPage.tsx
import React, { useState } from 'react';

export const ReplayPage: React.FC = () => {
  const [selectedFile, setSelectedFile] = useState<string>('');
  const [replayData, setReplayData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadReplayFile = async (filename: string) => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(`/${filename}`);
      if (!response.ok) {
        throw new Error(`Failed to load ${filename}: ${response.statusText}`);
      }
      
      const data = await response.json();
      setReplayData(data);
      console.log('Loaded replay data:', data);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to load replay';
      setError(errorMsg);
      console.error('Error loading replay:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleFileSelect = (filename: string) => {
    setSelectedFile(filename);
    loadReplayFile(filename);
  };

  return (
    <div className="min-h-screen bg-gray-900 text-white p-6">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold mb-6">Game Replay Viewer</h1>
        
        {/* File Selection */}
        <div className="mb-6 p-4 bg-gray-800 rounded-lg">
          <h2 className="text-xl font-semibold mb-4">Select Replay File</h2>
          <div className="space-y-2">
            <button
              onClick={() => handleFileSelect('ai/event_log/train_best_game_replay.json')}
              className={`block w-full text-left px-4 py-2 rounded transition-colors ${
                selectedFile === 'ai/event_log/train_best_game_replay.json'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
              }`}
            >
              🏆 Best Training Replay
            </button>
            <button
              onClick={() => handleFileSelect('ai/event_log/train_worst_game_replay.json')}
              className={`block w-full text-left px-4 py-2 rounded transition-colors ${
                selectedFile === 'ai/event_log/train_worst_game_replay.json'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
              }`}
            >
              📉 Worst Training Replay
            </button>
          </div>
        </div>

        {/* Loading State */}
        {loading && (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-16 w-16 border-b-2 border-blue-500"></div>
            <span className="ml-4 text-lg">Loading replay...</span>
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="mb-6 p-4 bg-red-900 border border-red-700 rounded-lg">
            <h3 className="text-lg font-semibold text-red-300 mb-2">Error Loading Replay</h3>
            <p className="text-red-200">{error}</p>
            <div className="mt-4 text-sm text-red-300">
              <p className="font-semibold">Troubleshooting steps:</p>
              <ul className="list-disc list-inside mt-2 space-y-1">
                <li>Make sure you've run training: <code className="bg-red-800 px-2 py-1 rounded">python ai/train.py</code></li>
                <li>Check that replay files exist in <code className="bg-red-800 px-2 py-1 rounded">ai/event_log/</code></li>
                <li>Ensure the development server can access the files</li>
                <li>Try refreshing the page</li>
              </ul>
            </div>
          </div>
        )}

        {/* Replay Data Display */}
        {replayData && !loading && (
          <div className="space-y-6">
            {/* Metadata */}
            {replayData.metadata && (
              <div className="p-4 bg-gray-800 rounded-lg">
                <h3 className="text-lg font-semibold mb-3">Replay Information</h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                  <div>
                    <span className="text-gray-400">Format:</span><br />
                    <span className="text-white">{replayData.metadata.format || 'N/A'}</span>
                  </div>
                  <div>
                    <span className="text-gray-400">Total Events:</span><br />
                    <span className="text-white">{replayData.metadata.total_events || replayData.events?.length || 'N/A'}</span>
                  </div>
                  <div>
                    <span className="text-gray-400">Episode Reward:</span><br />
                    <span className="text-white">{replayData.metadata.episode_reward?.toFixed(2) || 'N/A'}</span>
                  </div>
                  <div>
                    <span className="text-gray-400">Created:</span><br />
                    <span className="text-white">{replayData.metadata.created ? new Date(replayData.metadata.created).toLocaleDateString() : 'N/A'}</span>
                  </div>
                </div>
              </div>
            )}

            {/* Events List */}
            <div className="p-4 bg-gray-800 rounded-lg">
              <h3 className="text-lg font-semibold mb-3">Events ({replayData.events?.length || 0})</h3>
              {replayData.events && replayData.events.length > 0 ? (
                <div className="max-h-96 overflow-y-auto">
                  <div className="space-y-2">
                    {replayData.events.slice(0, 20).map((event: any, index: number) => (
                      <div key={index} className="p-3 bg-gray-700 rounded">
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm">
                          <div>
                            <span className="text-gray-400">Turn:</span> {event.turn || index + 1}
                          </div>
                          <div>
                            <span className="text-gray-400">Action:</span> {event.action || event.action_id || 'N/A'}
                          </div>
                          <div>
                            <span className="text-gray-400">AI Units:</span> {event.ai_units_alive || 'N/A'}
                          </div>
                          <div>
                            <span className="text-gray-400">Player Units:</span> {event.enemy_units_alive || 'N/A'}
                          </div>
                        </div>
                        {event.reward !== undefined && (
                          <div className="mt-2 text-sm">
                            <span className="text-gray-400">Reward:</span> {event.reward.toFixed(3)}
                          </div>
                        )}
                      </div>
                    ))}
                    {replayData.events.length > 20 && (
                      <div className="p-3 text-center text-gray-400">
                        ... and {replayData.events.length - 20} more events
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <p className="text-gray-400">No events found in replay data</p>
              )}
            </div>

            {/* Raw Data (for debugging) */}
            <details className="p-4 bg-gray-800 rounded-lg">
              <summary className="text-lg font-semibold cursor-pointer">Raw Replay Data (Debug)</summary>
              <pre className="mt-4 p-4 bg-gray-900 rounded text-sm overflow-x-auto">
                {JSON.stringify(replayData, null, 2)}
              </pre>
            </details>
          </div>
        )}

        {/* Instructions */}
        {!selectedFile && (
          <div className="p-4 bg-blue-900 border border-blue-700 rounded-lg">
            <h3 className="text-lg font-semibold text-blue-300 mb-2">Getting Started</h3>
            <p className="text-blue-200 mb-3">To view replays, you need to generate them first:</p>
            <ol className="list-decimal list-inside text-blue-200 space-y-1">
              <li>Run training: <code className="bg-blue-800 px-2 py-1 rounded">python ai/train.py</code></li>
              <li>Wait for training to complete</li>
              <li>Replay files will be generated in <code className="bg-blue-800 px-2 py-1 rounded">ai/event_log/</code></li>
              <li>Select a replay file above to view it</li>
            </ol>
          </div>
        )}
      </div>
    </div>
  );
};

export default ReplayPage;