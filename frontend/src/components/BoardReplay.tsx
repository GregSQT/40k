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
  reward?: number;
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

  // Auto-load train_step.log on mount
  useEffect(() => {
    const loadDefaultLog = async () => {
      try {
        const response = await fetch('http://localhost:5000/api/replay/default');
        if (!response.ok) {
          // Silent fail - file might not exist, user can still browse manually
          console.log('No default train_step.log found, user can browse manually');
          return;
        }

        const text = await response.text();

        // Parse it directly on frontend
        const { parse_log_file_from_text } = await import('../utils/replayParser');
        const data = parse_log_file_from_text(text);

        setReplayData(data);
        setSelectedFileName('train_step.log');
        setSelectedEpisode(null);
        setCurrentActionIndex(0);
        setIsPlaying(false);
        setLoadError(null);

        console.log(`Auto-loaded train_step.log with ${data.total_episodes} episodes`);
      } catch (error) {
        // Silent fail - user can still browse manually
        console.log('Could not auto-load train_step.log:', error);
      }
    };

    loadDefaultLog();
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
          if (prev >= episode.total_actions) {
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
  // For shoot actions, ensure shooter has SHOOT_LEFT > 0 for LoS calculation
  const unitsWithGhost = currentState?.units ? [...currentState.units].map((u: any) => {
    // During shoot action, ensure shooter has SHOOT_LEFT > 0 to trigger LoS display
    if (currentAction?.type === 'shoot' && u.id === currentAction.shooter_id) {
      return { ...u, SHOOT_LEFT: Math.max(u.SHOOT_LEFT || 0, 1) };
    }
    return u;
  }) : [];
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
        // Get target from the state AFTER this action
        const stateAfterAction = currentEpisode.states[i];
        const target = stateAfterAction?.units?.find((u: any) => u.id === targetId);
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

        // Check if THIS shot killed the target by comparing HP before and after
        // Get target's HP from state BEFORE this action
        const stateBeforeAction = i === 0 ? currentEpisode.initial_state : currentEpisode.states[i - 1];
        const targetBefore = stateBeforeAction?.units?.find((u: any) => u.id === targetId);
        const hpBefore = targetBefore ? (targetBefore as any).HP_CUR : 0;
        const hpAfter = target ? (target as any).HP_CUR : 0;

        // Target died if HP went from >0 to <=0 after this action
        const targetDied = hpBefore > 0 && hpAfter <= 0;

        // Build shootDetails for color coding (must match format expected by getEventTypeClass)
        // Note: Don't include targetDied here - shoot lines should show hit/wound/save results
        // Death is shown as a separate black line below
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
          shootDetails,  // Include for color coding
          // Add reward info for debug mode display (player 0 = agent)
          is_ai_action: action.player === 0,
          reward: action.reward,
          action_name: 'shoot'
        } as any);

        // Add separate death event if target was killed (like PvP mode does)
        if (targetDied && target) {
          const targetType = (target as any).type || 'Unknown';
          gameLog.addEvent({
            type: 'death',
            message: `Unit ${targetId} (${targetType}) was DESTROYED!`,
            unitId: targetId,
            turnNumber: turnNumber,
            phase: 'shooting',
            player: action.player  // Use acting player (shooter), not target's player
          });
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentActionIndex, currentEpisode]);

  // Playback control component (inserted between TurnPhaseTracker and UnitStatusTable)
  const PlaybackControls = () => {
    if (!currentEpisode) return null;

    return (
      <div className="replay-playback-controls-container">
        {/* Single row: Step controls left, Playback controls center-left, Speed center, Action count right */}
        <div className="replay-controls-row">
          {/* Step controls - LEFT */}
          <div className="replay-step-buttons">
            <button
              onClick={() => setCurrentActionIndex(prev => Math.max(0, prev - 1))}
              disabled={currentActionIndex === 0}
              className="replay-btn replay-btn--nav"
            >
              <span className="replay-icon replay-icon--prev">⏪</span>
            </button>
            <button
              onClick={() => setCurrentActionIndex(prev => Math.min(currentEpisode.total_actions, prev + 1))}
              disabled={currentActionIndex >= currentEpisode.total_actions}
              className="replay-btn replay-btn--nav"
            >
              <span className="replay-icon replay-icon--next">⏩</span>
            </button>
          </div>

          {/* Main playback controls - CENTER-LEFT */}
          <div className="replay-nav-buttons">
            <button
              onClick={() => setCurrentActionIndex(0)}
              className="replay-btn replay-btn--nav"
              title="Go to start"
            >
              <span className="replay-icon replay-icon--start">⏮</span>
            </button>
            {!isPlaying ? (
              <button
                onClick={() => setIsPlaying(true)}
                className="replay-btn replay-btn--play"
              >
                ▶
              </button>
            ) : (
              <button
                onClick={() => setIsPlaying(false)}
                className="replay-btn replay-btn--pause"
              >
                ⏸
              </button>
            )}
            <button
              onClick={() => { setIsPlaying(false); setCurrentActionIndex(0); }}
              className="replay-btn replay-btn--stop"
            >
              ⏹
            </button>
            <button
              onClick={() => setCurrentActionIndex(currentEpisode.total_actions)}
              className="replay-btn replay-btn--nav"
            >
              <span className="replay-icon replay-icon--end">⏭</span>
            </button>
          </div>

          {/* Speed controls - CENTER */}
          <div className="replay-speed-controls">
            <span className="replay-speed-label">Speed:</span>
            {[0.25, 0.5, 1.0, 2.0, 4.0].map((speed) => (
              <button
                key={speed}
                onClick={() => setPlaybackSpeed(speed)}
                className={`replay-btn replay-btn--speed ${playbackSpeed === speed ? 'active' : ''}`}
              >
                {speed}x
              </button>
            ))}
          </div>

          {/* Action counter - RIGHT */}
          <div className="replay-action-counter">
            {currentActionIndex === 0 ? (
              <>Initial State</>
            ) : (
              <>Action {currentActionIndex} / {currentEpisode.total_actions}</>
            )}
          </div>
        </div>

        {/* Progress bar - separate row below */}
        <div className="replay-progress-bar">
          <div
            className="replay-progress-fill"
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
        <div className="replay-error">
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
        <div className="replay-selector-row">
          {/* Left: Browse button + Select file text */}
          <div className="replay-browse-group">
            <label className="replay-browse-btn">
              Browse
              <input
                type="file"
                accept=".log"
                onChange={handleFileSelect}
                className="hidden"
              />
            </label>
            <span className="replay-file-status">
              {selectedFileName ? `File selected: ${selectedFileName}` : 'Select file'}
            </span>
          </div>

          {/* Right: Episode dropdown (only visible after file selected) */}
          {replayData && replayData.episodes.length > 0 && (
            <select
              value={selectedEpisode || ''}
              onChange={(e) => selectEpisode(parseInt(e.target.value))}
              className="replay-episode-select"
            >
              <option value="">Select Episode</option>
              {replayData.episodes.map((ep) => {
                // Extract scenario identifier (e.g., "phase1-bot3" from "..._scenario_phase1-bot3")
                const scenarioMatch = ep.scenario.match(/_scenario_(.+)$/);
                const scenarioId = scenarioMatch ? scenarioMatch[1] : '';
                return (
                  <option key={ep.episode_num} value={ep.episode_num}>
                    Episode {ep.episode_num} - {scenarioId || 'Unknown'} - {ep.bot_name || 'Unknown'} - {ep.final_result || 'Unknown'}
                  </option>
                );
              })}
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
        <GameLog {...gameLog} availableHeight={200} debugMode={showHexCoordinates} />
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

  // Get moving unit ID for boot icon during movement phase
  const movingUnitId = (currentAction?.type === 'move' || currentAction?.type === 'move_wait') && currentAction?.unit_id
    ? currentAction.unit_id
    : null;

  // For move actions, select the ghost unit to show movement range
  // For shoot actions, select the shooter to show LoS/attack range
  // Ghost unit has ID -1 and is at the starting position
  const replaySelectedUnitId = currentAction?.type === 'move'
    ? -1
    : (currentAction?.type === 'shoot' ? currentAction.shooter_id : null);

  // Center column: Board
  const centerContent = currentState && gameConfig ? (
    <BoardPvp
      units={unitsWithGhost}
      selectedUnitId={replaySelectedUnitId}
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
      currentPlayer={(currentAction?.type === 'move' || currentAction?.type === 'shoot') ? (currentAction.player as 0 | 1) : (currentState.currentPlayer || 0)}
      unitsMoved={[]}
      phase={currentAction?.type === 'move' ? 'move' : (currentAction?.type === 'shoot' ? 'shoot' : (currentState.phase || 'move'))}
      onShoot={() => {}}
      gameState={currentState}
      getChargeDestinations={() => []}
      shootingTargetId={shootingTargetId}
      shootingUnitId={shootingUnitId}
      movingUnitId={movingUnitId}
      wallHexesOverride={currentState.walls}
    />
  ) : (
    <div className="replay-empty-state">
      <div className="replay-empty-state__content">
        <h2 className="replay-empty-state__title">Replay Viewer</h2>
        <p className="replay-empty-state__subtitle">Select a log file and episode to start replay</p>
        <p className="replay-empty-state__info">
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
