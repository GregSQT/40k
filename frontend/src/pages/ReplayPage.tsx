// frontend/src/pages/ReplayPage.tsx
import React, { useState, useCallback } from 'react';
import { SharedLayout } from '../components/SharedLayout';
import { ReplayViewer } from '../components/ReplayViewer';

export const ReplayPage: React.FC = () => {
  const [replayFile, setReplayFile] = useState<string | null>(null);
  const [selectedFileName, setSelectedFileName] = useState<string | undefined>(undefined);
  const [currentStep, setCurrentStep] = useState(0);
  const [totalSteps, setTotalSteps] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTurn, setCurrentTurn] = useState(1);
  const [currentPhase, setCurrentPhase] = useState('move');
  
  // Auto-play interval
  const [playInterval, setPlayInterval] = useState<NodeJS.Timeout | null>(null);

  // Handle file selection
  const handleFileSelect = useCallback((file: File) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const content = e.target?.result as string;
        const data = JSON.parse(content);
        
        // Create blob URL for ReplayViewer
        const blob = new Blob([content], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        
        setReplayFile(url);
        setSelectedFileName(file.name);
        setCurrentStep(0);
        setTotalSteps(data.events?.length || data.actions?.length || 0);
        setIsPlaying(false);
        
        // Clear any existing interval
        if (playInterval) {
          clearInterval(playInterval);
          setPlayInterval(null);
        }
      } catch (error) {
        console.error('Error parsing replay file:', error);
        alert('Invalid replay file format');
      }
    };
    reader.readAsText(file);
  }, [playInterval]);

  // Control handlers
  const handlePlayPause = useCallback(() => {
    if (isPlaying) {
      // Pause
      if (playInterval) {
        clearInterval(playInterval);
        setPlayInterval(null);
      }
      setIsPlaying(false);
    } else {
      // Play
      if (currentStep < totalSteps - 1) {
        const interval = setInterval(() => {
          setCurrentStep(prev => {
            if (prev >= totalSteps - 1) {
              clearInterval(interval);
              setIsPlaying(false);
              return prev;
            }
            return prev + 1;
          });
        }, 1000); // 1 second per step
        
        setPlayInterval(interval);
        setIsPlaying(true);
      }
    }
  }, [isPlaying, playInterval, currentStep, totalSteps]);

  const handlePrevious = useCallback(() => {
    setCurrentStep(prev => Math.max(0, prev - 1));
    if (isPlaying) {
      setIsPlaying(false);
      if (playInterval) {
        clearInterval(playInterval);
        setPlayInterval(null);
      }
    }
  }, [isPlaying, playInterval]);

  const handleNext = useCallback(() => {
    setCurrentStep(prev => Math.min(totalSteps - 1, prev + 1));
    if (isPlaying) {
      setIsPlaying(false);
      if (playInterval) {
        clearInterval(playInterval);
        setPlayInterval(null);
      }
    }
  }, [isPlaying, playInterval, totalSteps]);

  const handleReset = useCallback(() => {
    setCurrentStep(0);
    setIsPlaying(false);
    if (playInterval) {
      clearInterval(playInterval);
      setPlayInterval(null);
    }
  }, [playInterval]);

  // Cleanup interval on unmount
  React.useEffect(() => {
    return () => {
      if (playInterval) {
        clearInterval(playInterval);
      }
    };
  }, [playInterval]);

  return (
    <SharedLayout
      currentTurn={currentTurn}
      currentPhase={currentPhase}
      maxTurns={5}
      showReplayControls={true}
      replayControls={{
        onFileSelect: handleFileSelect,
        onPlayPause: handlePlayPause,
        onPrevious: handlePrevious,
        onNext: handleNext,
        onReset: handleReset,
        isPlaying,
        currentStep,
        totalSteps,
        selectedFileName
      }}
    >
      {replayFile ? (
        <ReplayViewer 
          replayFile={replayFile}
          externalStep={currentStep}
          onStepChange={setCurrentStep}
          onTurnChange={setCurrentTurn}
          onPhaseChange={setCurrentPhase}
        />
      ) : (
        <div className="h-full flex items-center justify-center">
          <div className="text-center text-gray-400">
            <div className="text-xl mb-4">No replay file selected</div>
            <div className="text-sm">
              Use the "Browse Replay Files" button above to select a JSON file from ai/event_log/ directory
            </div>
          </div>
        </div>
      )}
    </SharedLayout>
  );
};

export default ReplayPage;