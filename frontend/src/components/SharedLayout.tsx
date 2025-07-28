// frontend/src/components/SharedLayout.tsx
import React from 'react';
import { useLocation } from 'react-router-dom';
import { TurnPhaseTracker } from './TurnPhaseTracker';

interface ReplayControlsProps {
  onFileSelect: (file: File) => void;
  onPlayPause: () => void;
  onPrevious: () => void;
  onNext: () => void;
  onReset: () => void;
  isPlaying: boolean;
  currentStep: number;
  totalSteps: number;
  selectedFileName?: string;
}

interface SharedLayoutProps {
  currentTurn: number;
  currentPhase: string;
  maxTurns?: number;
  showReplayControls?: boolean;
  replayControls?: ReplayControlsProps;
  children: React.ReactNode;
  rightColumnContent?: React.ReactNode; // NEW: For unit status tables
}

const Navigation: React.FC = () => {
  const location = useLocation();
  
  const getButtonStyle = (path: string) => ({
    padding: '10px 18px',
    backgroundColor: location.pathname === path ? '#1e40af' : '#64748b',
    color: 'white',
    border: 'none',
    borderRadius: '4px',
    marginRight: '8px',
    cursor: 'pointer',
    fontWeight: location.pathname === path ? 'bold' : 'normal'
  });

  return (
    <nav style={{ display: 'flex', gap: '8px', marginBottom: '20px', justifyContent: 'flex-start', paddingTop: '8px' }}>
      <button onClick={() => window.location.href = '/game'} style={getButtonStyle('/game')}>PvP</button>
      <button onClick={() => window.location.href = '/pve'} style={getButtonStyle('/pve')}>PvE</button>
      <button onClick={() => window.location.href = '/replay'} style={getButtonStyle('/replay')}>Replay</button>
    </nav>
  );
};

const ReplayControls: React.FC<ReplayControlsProps> = ({
  onFileSelect,
  onPlayPause,
  onPrevious,
  onNext,
  onReset,
  isPlaying,
  currentStep,
  totalSteps,
  selectedFileName
}) => {
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      onFileSelect(file);
    }
  };

  const openFileBrowser = () => {
    fileInputRef.current?.click();
  };

  return (
    <div className="bg-white p-4 border-b shadow-sm">
      {/* File Selection Row */}
      <div className="flex items-center gap-4 mb-4">
        <button
          onClick={openFileBrowser}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
        >
          📁 Browse Replay Files
        </button>
        {selectedFileName && (
          <span className="text-sm text-gray-600">
            File: {selectedFileName}
          </span>
        )}
        <input
          ref={fileInputRef}
          type="file"
          accept=".json"
          onChange={handleFileChange}
          style={{ display: 'none' }}
        />
      </div>

      {/* Control Panel Row */}
      <div className="flex items-center gap-2">
        <button
          onClick={onReset}
          className="px-3 py-1 bg-gray-500 text-white rounded hover:bg-gray-600 transition-colors"
          title="Reset to beginning"
        >
          ⏮️
        </button>
        <button
          onClick={onPrevious}
          className="px-3 py-1 bg-gray-500 text-white rounded hover:bg-gray-600 transition-colors"
          title="Previous step"
        >
          ⏪
        </button>
        <button
          onClick={onPlayPause}
          className={`px-3 py-1 text-white rounded transition-colors ${
            isPlaying ? 'bg-red-500 hover:bg-red-600' : 'bg-green-500 hover:bg-green-600'
          }`}
          title={isPlaying ? 'Pause' : 'Play'}
        >
          {isPlaying ? '⏸️' : '▶️'}
        </button>
        <button
          onClick={onNext}
          className="px-3 py-1 bg-gray-500 text-white rounded hover:bg-gray-600 transition-colors"
          title="Next step"
        >
          ⏩
        </button>
        <div className="ml-4 text-sm text-gray-600">
          Step {currentStep + 1} of {totalSteps}
        </div>
      </div>
    </div>
  );
};

export const SharedLayout: React.FC<SharedLayoutProps> = ({
  currentTurn,
  currentPhase,
  maxTurns = 5,
  showReplayControls = false,
  replayControls,
  children,
  rightColumnContent
}) => {
  return (
    <div className="min-h-screen bg-gray-900 text-white">
      {/* Navigation removed from fixed top position */}
      
      {/* Main Content */}
      <div>
        {/* Replay Controls (if enabled) */}
        {showReplayControls && replayControls && (
          <ReplayControls {...replayControls} />
        )}
        
        <div style={{ 
          display: 'flex', 
          height: '100vh',
          backgroundColor: '#222'
        }}>
          {/* Left Column: Game Board */}
          <div style={{ 
            flex: '1', 
            maxWidth: '800px', 
            padding: '16px'
          }}>
            {children}
          </div>

          {/* Right Column: Navigation + Turn Tracker + Unit Status Tables */}
          <div style={{ 
            width: '450px', 
            padding: '8px 16px 16px 16px', 
            backgroundColor: '#444',
            overflow: 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: '16px'
          }}>
            <Navigation />
            <TurnPhaseTracker 
              currentTurn={currentTurn}
              currentPhase={currentPhase}
              maxTurns={maxTurns}
              className="turn-phase-tracker-right"
            />
            
            {/* Unit status tables and game log */}
            {rightColumnContent}
          </div>
        </div>
      </div>
    </div>
  );
};

export default SharedLayout;