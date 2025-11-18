// frontend/src/components/BoardReplay.tsx
// Replay viewer that reuses existing BoardWithAPI structure

import React, { useState, useEffect, useRef } from 'react';
import '../App.css';
import BoardPvp from './BoardPvp';
import { useGameConfig } from '../hooks/useGameConfig';
import SharedLayout from './SharedLayout';
import { ErrorBoundary } from './ErrorBoundary';
import { UnitStatusTable } from './UnitStatusTable';
import { GameLog } from './GameLog';
import { TurnPhaseTracker } from './TurnPhaseTracker';
import { useGameLog } from '../hooks/useGameLog';
import { initializeUnitRegistry, getUnitClass } from '../data/UnitFactory';

// Import replay parser types
interface ReplayAction {
  type: string;
  timestamp: string;
  turn: string;
  player: number;
  unit_id?: number;
  from?: { col: number; row: number };
  to?: { col: number; row: number };
  pos?: { col: number; row: number };
  shooter_id?: number;
  shooter_pos?: { col: number; row: number };
  target_id?: number;
  damage?: number;
  hit_roll?: number;
  wound_roll?: number;
  save_roll?: number;
  save_target?: number;
}

interface ReplayEpisode {
  episode_num: number;
  scenario: string;
  bot_name: string;
  initial_state: any;
  actions: ReplayAction[];
  states: any[];
  total_actions: number;
  final_result: string | null;
}

interface ReplayData {
  total_episodes: number;
  episodes: ReplayEpisode[];
}

export const BoardReplay: React.FC = () => {
  const { gameConfig } = useGameConfig();
  const gameLog = useGameLog();

  // Replay data
  const [replayData, setReplayData] = useState<ReplayData | null>(null);
  const [selectedEpisode, setSelectedEpisode] = useState<number | null>(null);
  const [selectedFileName, setSelectedFileName] = useState<string>('');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [unitRegistryReady, setUnitRegistryReady] = useState<boolean>(false);

  // Playback state
  const [currentActionIndex, setCurrentActionIndex] = useState<number>(0);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1.0);
  const [showHexCoordinates, setShowHexCoordinates] = useState<boolean>(false);

  const playbackInterval = useRef<number | null>(null);

  // Initialize UnitFactory registry on mount
  useEffect(() => {
    const initRegistry = async () => {
      try {
        await initializeUnitRegistry();
        setUnitRegistryReady(true);
      } catch (error) {
        console.error('Failed to initialize unit registry:', error);
        setLoadError('Failed to initialize unit registry');
      }
    };
    initRegistry();
  }, []);

  // Enrich units with stats from UnitFactory
  const enrichUnitsWithStats = (units: any[]): any[] => {
    if (!unitRegistryReady) return units;

    return units.map(unit => {
      try {
        const UnitClass = getUnitClass(unit.type);

        // Merge UnitClass stats with unit data
        // Fix HP: replayParser hardcodes HP_MAX=2, so if HP_CUR==HP_MAX==2, reset to correct values
        // Otherwise preserve HP_CUR from parsed data (tracks damage taken during replay)
        const correctHpMax = UnitClass.HP_MAX || 1;
        let currentHp = unit.HP_CUR;
        if (unit.HP_MAX === 2 && unit.HP_CUR === 2) {
          // This is the hardcoded placeholder value, reset to correct HP_MAX
          currentHp = correctHpMax;
        }

        return {
          ...unit,
          HP_MAX: correctHpMax,
          HP_CUR: currentHp,
          MOVE: UnitClass.MOVE || 0,
          T: UnitClass.T || 0,
          ARMOR_SAVE: UnitClass.ARMOR_SAVE || 0,
          RNG_RNG: UnitClass.RNG_RNG || 0,
          RNG_NB: UnitClass.RNG_NB || 0,
          RNG_ATK: UnitClass.RNG_ATK || 0,
          RNG_STR: UnitClass.RNG_STR || 0,
          RNG_AP: UnitClass.RNG_AP || 0,
          RNG_DMG: UnitClass.RNG_DMG || 0,
          CC_NB: UnitClass.CC_NB || 0,
          CC_ATK: UnitClass.CC_ATK || 0,
          CC_STR: UnitClass.CC_STR || 0,
          CC_AP: UnitClass.CC_AP || 0,
          CC_DMG: UnitClass.CC_DMG || 0,
          ICON: UnitClass.ICON || '',
          ICON_SCALE: UnitClass.ICON_SCALE || 1
        };
      } catch (error) {
        console.warn(`Failed to enrich unit ${unit.id} (${unit.type}):`, error);
        return unit;
      }
    });
  };

  const handleFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setSelectedFileName(file.name);

    try {
      // Read file content
      const text = await file.text();

      // Parse it directly on frontend
      const { parse_log_file_from_text } = await import('../utils/replayParser');
      const data = parse_log_file_from_text(text);

      setReplayData(data);
      setSelectedEpisode(null);
      setCurrentActionIndex(0);
      setIsPlaying(false);
      setLoadError(null);
    } catch (error: any) {
      console.error('Failed to parse replay:', error);
      setLoadError(`Failed to parse file: ${error.message}`);
      setSelectedFileName('');
    }
  };

  const selectEpisode = (episodeNum: number) => {
    setSelectedEpisode(episodeNum);
    setCurrentActionIndex(0);
    setIsPlaying(false);
    gameLog.clearLog();
  };

  // Playback engine
  useEffect(() => {
    if (isPlaying && selectedEpisode !== null && replayData) {
      const episode = replayData.episodes[selectedEpisode - 1];
      const interval = (500 / playbackSpeed);

      playbackInterval.current = setInterval(() => {
        setCurrentActionIndex(prev => {
          if (prev >= episode.total_actions - 1) {
            setIsPlaying(false);
            return prev;
          }
          return prev + 1;
        });
      }, interval);

      return () => {
        if (playbackInterval.current) clearInterval(playbackInterval.current);
      };
    }
  }, [isPlaying, selectedEpisode, playbackSpeed, replayData]);

  // Get current game state
  const getCurrentGameState = () => {
    if (!selectedEpisode || !replayData) return null;
    const episode = replayData.episodes[selectedEpisode - 1];

    // Action index 0 = initial state (before any actions)
    // Action index 1 = state after first action (states[0])
    // Action index N = state after Nth action (states[N-1])
    if (currentActionIndex === 0) {
      // Enrich initial state units with stats
      return {
        ...episode.initial_state,
        units: enrichUnitsWithStats(episode.initial_state.units || [])
      };
    } else {
      const state = episode.states[currentActionIndex - 1];

      // Enrich state units with stats
      const enrichedUnits = enrichUnitsWithStats(state?.units || []);

      return {
        ...state,
        units: enrichedUnits
      };
    }
  };

  const currentState = getCurrentGameState();
  const currentEpisode = selectedEpisode !== null && replayData
    ? replayData.episodes[selectedEpisode - 1]
    : null;

  // Get current action for move preview
  const currentAction = currentEpisode && currentActionIndex > 0
    ? currentEpisode.actions[currentActionIndex - 1]
    : null;

  // Add ghost unit at starting position for move actions
  const unitsWithGhost = currentState?.units ? [...currentState.units] : [];
  if (currentAction?.type === 'move' && currentAction?.from && currentAction.unit_id) {
    // Add a ghost unit at the starting position
    const originalUnit = unitsWithGhost.find((u: any) => u.id === currentAction.unit_id);
    if (originalUnit) {
      unitsWithGhost.push({
        ...originalUnit,
        id: -1, // Special ID for ghost unit
        col: currentAction.from.col,
        row: currentAction.from.row,
        isGhost: true // Mark as ghost for special rendering
      });
    }
  }

  // Update game log when action index changes
  useEffect(() => {
    if (!currentEpisode) return;

    // Clear and rebuild log up to current action
    gameLog.clearLog();

    for (let i = 0; i < currentActionIndex; i++) {
      const action = currentEpisode.actions[i];
      const turnNumber = parseInt(action.turn.replace('T', ''));

      if (action.type === 'move' && action.from && action.to) {
        gameLog.logMoveAction(
          { id: action.unit_id!, name: `Unit ${action.unit_id}` } as any,
          action.from.col,
          action.from.row,
          action.to.col,
          action.to.row,
          turnNumber
        );
      } else if (action.type === 'move_wait' && action.pos) {
        gameLog.logNoMoveAction(
          { id: action.unit_id!, name: `Unit ${action.unit_id}` } as any,
          turnNumber
        );
      } else if (action.type === 'shoot') {
        // Parse shooting details from log format to match PvP mode
        const shooterId = action.shooter_id!;
        const targetId = action.target_id!;
        const shooter = currentEpisode.actions.find((a: any) => a.shooter_id === shooterId);
        const shooterPos = shooter?.shooter_pos || action.shooter_pos || { col: 0, row: 0 };
        const target = currentState?.units?.find((u: any) => u.id === targetId);
        const targetPos = target ? { col: target.col, row: target.row } : { col: 0, row: 0 };

        // Reconstruct message in the same format as shooting_handlers.py
        let message = '';
        const hitRoll = action.hit_roll;
        const woundRoll = action.wound_roll;
        const saveRoll = action.save_roll;
        const saveTarget = action.save_target || 0;
        const damage = action.damage || 0;

        // Determine hit target (assuming 3+ for now - could be in log later)
        const hitTarget = 3;
        const woundTarget = 4; // Assuming 4+ for now

        // Build shootDetails for color coding (must match format expected by getEventTypeClass)
        const shootDetails = hitRoll !== undefined ? [{
          shotNumber: 1,
          attackRoll: hitRoll,
          strengthRoll: woundRoll || 0,
          hitResult: hitRoll >= hitTarget ? 'HIT' : 'MISS',
          strengthResult: woundRoll && woundRoll >= woundTarget ? 'SUCCESS' : 'FAILED',
          saveRoll: saveRoll,
          saveTarget: saveTarget,
          saveSuccess: saveRoll !== undefined && saveTarget > 0 ? saveRoll >= saveTarget : false,
          damageDealt: damage
        }] : undefined;

        if (hitRoll !== undefined && hitRoll < hitTarget) {
          // Hit failed
          message = `Unit ${shooterId} (${shooterPos.col}, ${shooterPos.row}) SHOT Unit ${targetId} (${targetPos.col}, ${targetPos.row}) : Hit ${hitRoll}(${hitTarget}+) : FAILED !`;
        } else if (woundRoll !== undefined && woundRoll < woundTarget) {
          // Wound failed
          message = `Unit ${shooterId} (${shooterPos.col}, ${shooterPos.row}) SHOT Unit ${targetId} (${targetPos.col}, ${targetPos.row}) : Hit ${hitRoll}(${hitTarget}+) - Wound ${woundRoll}(${woundTarget}+) : FAILED !`;
        } else if (saveRoll !== undefined && saveTarget > 0 && saveRoll >= saveTarget) {
          // Save succeeded
          message = `Unit ${shooterId} (${shooterPos.col}, ${shooterPos.row}) SHOT Unit ${targetId} (${targetPos.col}, ${targetPos.row}) : Hit ${hitRoll}(${hitTarget}+) - Wound ${woundRoll}(${woundTarget}+) - Save ${saveRoll}(${saveTarget}+) : SAVED !`;
        } else if (damage > 0) {
          // Damage dealt
          message = `Unit ${shooterId} (${shooterPos.col}, ${shooterPos.row}) SHOT Unit ${targetId} (${targetPos.col}, ${targetPos.row}) : Hit ${hitRoll}(${hitTarget}+) - Wound ${woundRoll}(${woundTarget}+) - Save ${saveRoll}(${saveTarget}+) - ${damage} DAMAGE DELT !`;
        } else {
          // Fallback
          message = `Unit ${shooterId} (${shooterPos.col}, ${shooterPos.row}) SHOT Unit ${targetId} (${targetPos.col}, ${targetPos.row})`;
        }

        // Use addEvent directly with custom formatted message to match PvP format
        gameLog.addEvent({
          type: 'shoot',
          message,
          unitId: shooterId,
          targetId: targetId,
          turnNumber: turnNumber,
          phase: 'shooting',
          player: action.player,
          shootDetails  // Include for color coding
        });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentActionIndex, currentEpisode]);

  // Playback control component (inserted between TurnPhaseTracker and UnitStatusTable)
  const PlaybackControls = () => {
    if (!currentEpisode) return null;

    return (
      <div className="replay-playback-controls-container">
        {/* Single row: Controls left, Speed center, Action count right */}
        <div className="flex items-center justify-between gap-4">
          {/* Navigation controls - LEFT */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => setCurrentActionIndex(0)}
              className="px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm"
              title="Go to start"
            >
              ⏮
            </button>
            <button
              onClick={() => setCurrentActionIndex(prev => Math.max(0, prev - 1))}
              disabled={currentActionIndex === 0}
              className="px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm disabled:opacity-50"
            >
              ⏪
            </button>
            {!isPlaying ? (
              <button
                onClick={() => setIsPlaying(true)}
                className="px-3 py-1 bg-green-600 hover:bg-green-500 rounded text-sm font-bold"
              >
                ▶
              </button>
            ) : (
              <button
                onClick={() => setIsPlaying(false)}
                className="px-3 py-1 bg-yellow-600 hover:bg-yellow-500 rounded text-sm font-bold"
              >
                ⏸
              </button>
            )}
            <button
              onClick={() => { setIsPlaying(false); setCurrentActionIndex(0); }}
              className="px-2 py-1 bg-red-600 hover:bg-red-500 rounded text-sm"
            >
              ⏹
            </button>
            <button
              onClick={() => setCurrentActionIndex(prev => Math.min(currentEpisode.total_actions - 1, prev + 1))}
              disabled={currentActionIndex >= currentEpisode.total_actions - 1}
              className="px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm disabled:opacity-50"
            >
              ⏩
            </button>
            <button
              onClick={() => setCurrentActionIndex(currentEpisode.total_actions - 1)}
              className="px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm"
            >
              ⏭
            </button>
          </div>

          {/* Speed controls - CENTER */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400">Speed:</span>
            {[0.25, 0.5, 1.0, 2.0, 4.0].map((speed) => (
              <button
                key={speed}
                onClick={() => setPlaybackSpeed(speed)}
                className={`px-2 py-1 rounded text-xs ${
                  playbackSpeed === speed ? 'bg-blue-600' : 'bg-gray-700 hover:bg-gray-600'
                }`}
              >
                {speed}x
              </button>
            ))}
          </div>

          {/* Action counter - RIGHT */}
          <div className="text-sm text-gray-300 whitespace-nowrap">
            {currentActionIndex === 0 ? (
              <>Initial State</>
            ) : (
              <>Action {currentActionIndex} / {currentEpisode.total_actions}</>
            )}
          </div>
        </div>

        {/* Progress bar - separate row below */}
        <div className="w-full bg-gray-700 rounded h-1.5">
          <div
            className="bg-blue-600 h-1.5 rounded transition-all"
            style={{ width: `${(currentActionIndex / currentEpisode.total_actions) * 100}%` }}
          />
        </div>
      </div>
    );
  };


  // Right column content (like BoardWithAPI but with replay controls)
  const rightColumnContent = (
    <>
      {/* Error display */}
      {loadError && (
        <div className="bg-red-900 border border-red-700 rounded p-3 mb-4 text-sm">
          <strong>Error:</strong> {loadError}
        </div>
      )}

      {/* Turn/Phase Tracker */}
      {gameConfig && currentState && currentEpisode && (
        <div className="turn-phase-tracker-right">
          <TurnPhaseTracker
            currentTurn={currentActionIndex > 0 ? parseInt(currentEpisode.actions[currentActionIndex - 1].turn.replace('T', '')) : 1}
            currentPhase={currentState.phase || 'move'}
            phases={["move", "shoot", "charge", "fight"]}
            maxTurns={gameConfig.game_rules.max_turns}
            className=""
          />
        </div>
      )}

      {/* File and Episode selector - single line */}
      <div className="replay-file-selector-container">
        <div className="flex items-center justify-between gap-4">
          {/* Left: Browse button + Select file text */}
          <div className="flex items-center gap-3">
            <label
              className="text-sm cursor-pointer"
              style={{
                backgroundColor: '#d4a843',
                color: '#1f2937',
                borderRadius: '6px',
                border: '1px solid #b8942f',
                boxShadow: '0 2px 4px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.3)',
                transition: 'all 0.15s ease',
                paddingLeft: '24px',
                paddingRight: '24px',
                paddingTop: '1px',
                paddingBottom: '1px'
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = '#e5b94d';
                e.currentTarget.style.boxShadow = '0 3px 6px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.4)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = '#d4a843';
                e.currentTarget.style.boxShadow = '0 2px 4px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.3)';
              }}
              onMouseDown={(e) => {
                e.currentTarget.style.boxShadow = 'inset 0 2px 4px rgba(0, 0, 0, 0.3)';
              }}
              onMouseUp={(e) => {
                e.currentTarget.style.boxShadow = '0 2px 4px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.3)';
              }}
            >
              Browse
              <input
                type="file"
                accept=".log"
                onChange={handleFileSelect}
                className="hidden"
              />
            </label>
            <span className="text-sm text-gray-300" style={{ marginLeft: '16px' }}>
              {selectedFileName ? `File selected: ${selectedFileName}` : 'Select file'}
            </span>
          </div>

          {/* Right: Episode dropdown (only visible after file selected) */}
          {replayData && replayData.episodes.length > 0 && (
            <select
              value={selectedEpisode || ''}
              onChange={(e) => selectEpisode(parseInt(e.target.value))}
              className="px-2 py-1 bg-gray-700 rounded text-sm min-w-[120px]"
            >
              <option value="">Select Episode</option>
              {replayData.episodes.map((ep) => (
                <option key={ep.episode_num} value={ep.episode_num}>
                  Episode {ep.episode_num} - {ep.bot_name || 'Unknown'} - {ep.final_result || 'Unknown'}
                </option>
              ))}
            </select>
          )}
        </div>
      </div>

      {/* PLAYBACK CONTROLS - inserted here between TurnPhaseTracker and UnitStatusTable */}
      <PlaybackControls />

      {/* Unit Status Tables */}
      {currentState && (
        <>
          <ErrorBoundary fallback={<div>Failed to load player 0 status</div>}>
            <UnitStatusTable
              units={currentState.units || []}
              player={0}
              selectedUnitId={null}
              clickedUnitId={null}
              onSelectUnit={() => {}}
              gameMode="training"
              onCollapseChange={() => {}}
            />
          </ErrorBoundary>

          <ErrorBoundary fallback={<div>Failed to load player 1 status</div>}>
            <UnitStatusTable
              units={currentState.units || []}
              player={1}
              selectedUnitId={null}
              clickedUnitId={null}
              onSelectUnit={() => {}}
              gameMode="training"
              onCollapseChange={() => {}}
            />
          </ErrorBoundary>
        </>
      )}

      {/* Game Log */}
      <ErrorBoundary fallback={<div>Failed to load game log</div>}>
        <GameLog {...gameLog} availableHeight={200} />
      </ErrorBoundary>
    </>
  );

  // Get shooting target ID for explosion icon and shooter ID for shooting indicator
  const shootingTargetId = currentAction?.type === 'shoot' && currentAction?.target_id
    ? currentAction.target_id
    : null;
  const shootingUnitId = currentAction?.type === 'shoot' && currentAction?.shooter_id
    ? currentAction.shooter_id
    : null;

  // Center column: Board
  const centerContent = currentState && gameConfig ? (
    <BoardPvp
      units={unitsWithGhost}
      selectedUnitId={null}
      eligibleUnitIds={unitsWithGhost.map((u: any) => u.id)}
      showHexCoordinates={showHexCoordinates}
      mode="select"
      movePreview={null}
      attackPreview={null}
      onSelectUnit={() => {}}
      onStartMovePreview={() => {}}
      onDirectMove={() => {}}
      onStartAttackPreview={() => {}}
      onConfirmMove={() => {}}
      onCancelMove={() => {}}
      currentPlayer={currentState.currentPlayer || 0}
      unitsMoved={[]}
      phase={currentState.phase || 'move'}
      onShoot={() => {}}
      gameState={currentState}
      getChargeDestinations={() => []}
      shootingTargetId={shootingTargetId}
      shootingUnitId={shootingUnitId}
    />
  ) : (
    <div className="flex items-center justify-center h-full text-white bg-gray-900">
      <div className="text-center p-8">
        <h2 className="text-2xl font-bold mb-4">Replay Viewer</h2>
        <p className="text-gray-400 mb-2">Select a log file and episode to start replay</p>
        <p className="text-xs text-gray-500">
          File: {selectedFileName || 'None'} |
          Episode: {selectedEpisode ? `#${selectedEpisode}` : 'None'}
        </p>
      </div>
    </div>
  );

  // Removed verbose render log to reduce console flooding
  // console.log('BoardReplay render:', {
  //   selectedFileName,
  //   selectedEpisode,
  //   currentState: !!currentState,
  //   units: currentState?.units?.map((u: any) => ({ id: u.id, player: u.player, type: u.type }))
  // });

  return (
    <SharedLayout
      rightColumnContent={rightColumnContent}
      showHexCoordinates={showHexCoordinates}
      onToggleHexCoordinates={setShowHexCoordinates}
    >
      {centerContent}
    </SharedLayout>
  );
};
