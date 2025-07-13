// frontend/src/pages/ReplayPage.tsx
import React from 'react';
import { ReplayViewer } from '../components/ReplayViewer';

export const ReplayPage: React.FC = () => {
  const [replayFile, setReplayFile] = React.useState<string | null>(null);
  const [selectedFileName, setSelectedFileName] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  // Handle file selection from Windows explorer
  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      // Validate file type
      if (!file.name.endsWith('.json')) {
        setError('Please select a JSON file');
        return;
      }

      // Check if it's a replay file based on naming patterns
      const isReplayFile = file.name.startsWith('training_replay_') ||
                          file.name.startsWith('phase_based_replay_') ||
                          file.name.includes('_vs_') ||
                          file.name.startsWith('replay_') ||
                          file.name.startsWith('training_');

      if (!isReplayFile) {
        setError('Please select a valid replay JSON file');
        return;
      }

      // Create file URL for local file access
      const fileUrl = URL.createObjectURL(file);
      setReplayFile(fileUrl);
      setSelectedFileName(file.name);
      setError(null);
      console.log(`✅ Selected replay file: ${file.name}`);
    }
  };

  // Open file browser
  const openFileBrowser = () => {
    fileInputRef.current?.click();
  };

  if (error && !replayFile) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-white text-center max-w-md">
          <div className="text-red-500 text-xl mb-4">⚠️ File Selection Error</div>
          <div className="text-gray-300 mb-4">{error}</div>
          <button
            onClick={openFileBrowser}
            className="px-6 py-3 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
          >
            Browse for Replay Files
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-gray-900 flex flex-col">
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".json"
        onChange={handleFileSelect}
        style={{ display: 'none' }}
      />

      {/* File Selection Header */}
      <div className="bg-gray-800 border-b border-gray-700 p-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-white">Replay Viewer</h1>
          <div className="flex items-center space-x-4">
            <button
              onClick={openFileBrowser}
              className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
            >
              Browse Files
            </button>
          </div>
        </div>

        {/* Current File Info */}
        {selectedFileName && (
          <div className="mt-2 text-sm text-gray-400">
            Current file: {selectedFileName}
          </div>
        )}

        {/* Error Display */}
        {error && replayFile && (
          <div className="mt-2 text-sm text-red-400">
            {error}
          </div>
        )}
      </div>

      {/* Replay Viewer or Instructions */}
      <div className="flex-1">
        {replayFile ? (
          <ReplayViewer replayFile={replayFile} />
        ) : (
          <div className="h-full flex items-center justify-center">
            <div className="text-center text-gray-400">
              <div className="text-xl mb-4">No replay file selected</div>
              <button
                onClick={openFileBrowser}
                className="px-6 py-3 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
              >
                Browse for Replay Files
              </button>
              <div className="text-sm mt-4">
                <div>Select JSON files from ai/Event_log/ directory</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default ReplayPage;