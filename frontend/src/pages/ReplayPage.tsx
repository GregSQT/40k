// frontend/src/pages/ReplayPage.tsx
import React, { useState, useRef } from 'react';
import { SharedLayout } from '../components/SharedLayout';
import { ReplayViewer } from '../components/ReplayViewer';
import { TurnPhaseTracker } from '../components/TurnPhaseTracker';
import { ErrorBoundary } from '../components/ErrorBoundary';
import "../App.css";

export const ReplayPage: React.FC = () => {
  const [replayFile, setReplayFile] = useState<string | null>(null);
  const [selectedFileName, setSelectedFileName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [totalSteps, setTotalSteps] = useState(0);
  const [currentTurn, setCurrentTurn] = useState(1);
  const [currentPhase, setCurrentPhase] = useState('move');
  const fileInputRef = useRef<HTMLInputElement>(null);

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
      setCurrentStep(0);
      console.log(`✅ Selected replay file: ${file.name}`);
    }
  };

  // Open file browser
  const openFileBrowser = () => {
    fileInputRef.current?.click();
  };

  // Replay control handlers
  const handlePlayPause = () => {
    setIsPlaying(!isPlaying);
  };

  const handlePrevious = () => {
    if (currentStep > 0) {
      setCurrentStep(currentStep - 1);
    }
  };

  const handleNext = () => {
    if (currentStep < totalSteps - 1) {
      setCurrentStep(currentStep + 1);
    }
  };

  const handleReset = () => {
    setCurrentStep(0);
    setIsPlaying(false);
  };

  // File Selection Controls Component
  const FileSelectionControls: React.FC = () => (
    <div className="unit-status-table-container" style={{ marginBottom: '16px' }}>
      <div style={{ padding: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
          <button
            onClick={openFileBrowser}
            style={{
              padding: '8px 16px',
              backgroundColor: '#1e40af',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontWeight: 'bold'
            }}
          >
            📁 Browse Replay Files
          </button>
          {selectedFileName && (
            <span style={{ fontSize: '12px', color: '#888' }}>
              {selectedFileName}
            </span>
          )}
        </div>
        {error && (
          <div style={{ fontSize: '12px', color: '#ff4444', marginTop: '4px' }}>
            {error}
          </div>
        )}
      </div>
      <input
        ref={fileInputRef}
        type="file"
        accept=".json"
        onChange={handleFileSelect}
        style={{ display: 'none' }}
      />
    </div>
  );

  // Replay Controls Component
  const ReplayControls: React.FC = () => (
    <div className="unit-status-table-container" style={{ marginBottom: '16px' }}>
      <div style={{ padding: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
          <button
            onClick={handleReset}
            style={{
              padding: '6px 12px',
              backgroundColor: '#64748b',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer'
            }}
            title="Reset to beginning"
          >
            ⏮️
          </button>
          <button
            onClick={handlePrevious}
            style={{
              padding: '6px 12px',
              backgroundColor: '#64748b',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer'
            }}
            title="Previous step"
          >
            ⏪
          </button>
          <button
            onClick={handlePlayPause}
            style={{
              padding: '6px 12px',
              backgroundColor: isPlaying ? '#dc2626' : '#16a34a',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontWeight: 'bold'
            }}
            title={isPlaying ? 'Pause' : 'Play'}
          >
            {isPlaying ? '⏸️' : '▶️'}
          </button>
          <button
            onClick={handleNext}
            style={{
              padding: '6px 12px',
              backgroundColor: '#64748b',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer'
            }}
            title="Next step"
          >
            ⏩
          </button>
        </div>
        <div style={{ fontSize: '12px', color: '#888', textAlign: 'center' }}>
          Step {currentStep + 1} of {totalSteps}
        </div>
      </div>
    </div>
  );

  // Right column content
  const rightColumnContent = (
    <>
      <FileSelectionControls />
      <ReplayControls />
      <TurnPhaseTracker 
        currentTurn={currentTurn} 
        currentPhase={currentPhase}
        className="turn-phase-tracker-right"
        maxTurns={5}
      />
      <ErrorBoundary fallback={<div>Failed to load replay info</div>}>
        <div className="unit-status-table-container">
          <div style={{ padding: '12px', textAlign: 'center', color: '#888' }}>
            {replayFile ? 'Replay loaded' : 'No replay file selected'}
          </div>
        </div>
      </ErrorBoundary>
    </>
  );

  // No file selected state
  if (!replayFile) {
    return (
      <SharedLayout rightColumnContent={rightColumnContent}>
        <div style={{ 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'center', 
          height: '100%',
          minHeight: '400px',
          color: '#888',
          textAlign: 'center',
          flexDirection: 'column',
          gap: '16px'
        }}>
          <div style={{ fontSize: '18px' }}>No replay file selected</div>
          <button
            onClick={openFileBrowser}
            style={{
              padding: '12px 24px',
              backgroundColor: '#1e40af',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '16px',
              fontWeight: 'bold'
            }}
          >
            Browse for Replay Files
          </button>
          <div style={{ fontSize: '12px', color: '#555' }}>
            Select JSON files from ai/Event_log/ directory
          </div>
        </div>
      </SharedLayout>
    );
  }

  // Main replay view
  return (
    <SharedLayout rightColumnContent={rightColumnContent}>
      <ReplayViewer replayFile={replayFile} />
    </SharedLayout>
  );
}

export default ReplayPage;