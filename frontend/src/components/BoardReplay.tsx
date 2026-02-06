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
import { offsetToCube, cubeDistance } from '../utils/gameHelpers';
import { getSelectedRangedWeapon, getSelectedMeleeWeapon } from '../utils/weaponHelpers';
import type { Unit, GameState, Weapon } from '../types/game';
import { SettingsMenu } from './SettingsMenu';

// Extended Unit type for replay mode (with ghost units)
interface UnitWithGhost extends Unit {
  isGhost?: boolean;
}

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
  target_pos?: { col: number; row: number };
  damage?: number;
  hit_roll?: number;
  wound_roll?: number;
  save_roll?: number;
  save_target?: number;
  reward?: number;
  // Fight action fields
  attacker_id?: number;
  attacker_pos?: { col: number; row: number };
  hit_target?: number;
  hit_result?: string;
  wound_target?: number;
  wound_result?: string;
  save_result?: string;
  // Weapon info
  weapon_name?: string;
  // Fight phase metadata (AI_TURN.md compliance)
  fight_subphase?: string;
  charging_activation_pool?: number[];
  active_alternating_activation_pool?: number[];
  non_active_alternating_activation_pool?: number[];
  // Charge action fields
  charge_roll?: number;
  charge_success?: boolean;
  // Advance action fields
  advance_roll?: number;
}

// Extended GameState for replay mode (with additional properties from parser)
interface ReplayGameState extends Omit<GameState, 'episode_steps'> {
  episode_steps?: number; // Optional in replay mode
  board_cols?: number;
  board_rows?: number;
  walls?: Array<{ col: number; row: number }>;
  objectives?: Array<{ name: string; hexes: Array<{ col: number; row: number }> }>;
}

interface ReplayEpisode {
  episode_num: number;
  scenario: string;
  bot_name: string;
  win_method?: string | null;
  initial_state: ReplayGameState;
  actions: ReplayAction[];
  states: ReplayGameState[];
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
  const [availableLogFiles, setAvailableLogFiles] = useState<Array<{name: string, size: number, modified: string}>>([]);

  // Playback state
  const [currentActionIndex, setCurrentActionIndex] = useState<number>(0);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1.0);
  
  // Settings menu state
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const handleOpenSettings = () => setIsSettingsOpen(true);
  
  // Settings preferences (from localStorage)
  const [settings, setSettings] = useState(() => {
    const showDebugStr = localStorage.getItem('showDebug');
    return {
      showDebug: showDebugStr ? JSON.parse(showDebugStr) : false,
    };
  });
  
  const handleToggleDebug = (value: boolean) => {
    setSettings(prev => ({ ...prev, showDebug: value }));
    localStorage.setItem('showDebug', JSON.stringify(value));
  };
  
  // Debug mode - read from settings state
  const showHexCoordinates = settings.showDebug;

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

  // Load available log files from server on mount
  useEffect(() => {
    const loadAvailableFiles = async () => {
      try {
        const response = await fetch('http://localhost:5001/api/replay/list');
        if (response.ok) {
          const data = await response.json();
          setAvailableLogFiles(data.logs || []);
        }
      } catch (error) {
        console.error('Failed to load available log files:', error);
      }
    };

    loadAvailableFiles();
  }, []);

  // Auto-load step.log on mount
  useEffect(() => {
    const loadDefaultLog = async () => {
      try {
        const response = await fetch('http://localhost:5001/api/replay/default');
        if (!response.ok) {
          // Silent fail - file might not exist, user can still browse manually
          console.log('No default step.log found, user can browse manually');
          return;
        }

        const text = await response.text();

        // Parse it directly on frontend
        const { parse_log_file_from_text } = await import('../utils/replayParser');
        const data = parse_log_file_from_text(text);

        // Type assertion with proper conversion
        const typedData = data as unknown as ReplayData;
        setReplayData(typedData);
        setSelectedFileName('step.log');
        setSelectedEpisode(1);
        setCurrentActionIndex(0);
        setIsPlaying(false);
        setLoadError(null);

        console.log(`Auto-loaded step.log with ${data.total_episodes} episodes`);
      } catch (error) {
        // Silent fail - user can still browse manually
        console.log('Could not auto-load step.log:', error);
      }
    };

    loadDefaultLog();
  }, []);

  // Enrich units with stats from UnitFactory
  const enrichUnitsWithStats = (units: Unit[]): Unit[] => {
    if (!unitRegistryReady) return units;

    return units.map(unit => {
      try {
        const UnitClass = getUnitClass(unit.type || '');

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
          LD: UnitClass.LD || 0,
          OC: UnitClass.OC || 0,
          VALUE: UnitClass.VALUE || 0,
          // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Extract from weapons arrays
          RNG_WEAPONS: (UnitClass.RNG_WEAPONS || []) as unknown as Weapon[],
          CC_WEAPONS: (UnitClass.CC_WEAPONS || []) as unknown as Weapon[],
          selectedRngWeaponIndex: UnitClass.RNG_WEAPONS && UnitClass.RNG_WEAPONS.length > 0 ? 0 : undefined,
          selectedCcWeaponIndex: UnitClass.CC_WEAPONS && UnitClass.CC_WEAPONS.length > 0 ? 0 : undefined,
          ICON: UnitClass.ICON || '',
          ICON_SCALE: UnitClass.ICON_SCALE || 1
        };
      } catch (error) {
        console.error(`❌ Failed to enrich unit ${unit.id} (${unit.type}):`, error);
        return unit;
      }
    });
  };

  const handleFileSelectFromServer = async (filename: string) => {
    if (!filename) return;

    setSelectedFileName(filename);
    setLoadError(null);

    try {
      // Load file content from server
      const response = await fetch(`http://localhost:5001/api/replay/file/${encodeURIComponent(filename)}`);
      if (!response.ok) {
        throw new Error(`Failed to load file: ${response.statusText}`);
      }

      const text = await response.text();

      // Parse it directly on frontend
      const { parse_log_file_from_text } = await import('../utils/replayParser');
      const data = parse_log_file_from_text(text);

      // Type assertion - parser returns any types, we cast to ReplayData
      setReplayData(data as unknown as ReplayData);
      setSelectedEpisode(null);
      setCurrentActionIndex(0);
      setIsPlaying(false);
      setLoadError(null);
    } catch (error: unknown) {
      console.error('Failed to parse replay:', error);
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      setLoadError(`Failed to load file: ${errorMessage}`);
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
  const getCurrentGameState = (): ReplayGameState | null => {
    if (!selectedEpisode || !replayData) return null;
    const episode = replayData.episodes[selectedEpisode - 1];

    // Action index 0 = initial state (before any actions)
    // Action index 1 = state after first action (states[0])
    // Action index N = state after Nth action (states[N-1])
    if (currentActionIndex === 0) {
      // Enrich initial state units with stats
      return {
        ...episode.initial_state,
        units: enrichUnitsWithStats(episode.initial_state.units || []),
        episode_steps: episode.initial_state.episode_steps || 0
      } as ReplayGameState;
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
  // For shoot actions, compute SHOOT_LEFT for the active shooter exactly like PvP,
  // based on RNG_NB and the number of shots already fired in the current shooting phase.
  const unitsWithGhost = currentState?.units ? [...currentState.units].map((u: Unit) => {
    // During shoot action, adjust SHOOT_LEFT only for the active shooting unit
    // EXACT mirror of PvP behavior: counter shows shots remaining *before* current shot.
    if (currentAction?.type === 'shoot' && currentEpisode && currentActionIndex > 0 && u.id === currentAction.shooter_id) {
      // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get from selected weapon (imported at top)
      const selectedRngWeapon = getSelectedRangedWeapon(u);
      const rngNb = selectedRngWeapon?.NB || 0;
      const shooterId = currentAction.shooter_id;

      // Index of the last *completed* action before the current one
      const lastCompletedIndex = currentActionIndex - 2; // actions are 0-based, state index is +1
      if (lastCompletedIndex < 0) {
        // No previous actions in this phase: full shots available
        return { ...u, SHOOT_LEFT: rngNb };
      }

      // Find the start of the current shooting phase by scanning backwards
      // from the last completed action until we hit a non-shoot action.
      let shootingPhaseStart = 0;
      for (let i = lastCompletedIndex; i >= 0; i--) {
        const action = currentEpisode.actions[i];
        if (action.type !== 'shoot' && action.type !== 'shoot_wait') {
          shootingPhaseStart = i + 1;
          break;
        }
      }

      // Count how many shots this unit has fired in the current shooting phase
      let shotsFired = 0;
      for (let i = shootingPhaseStart; i <= lastCompletedIndex && i < currentEpisode.actions.length; i++) {
        const action = currentEpisode.actions[i];
        if (action.type === 'shoot' && action.shooter_id === shooterId) {
          shotsFired++;
        }
      }

      // Counter shows remaining shots *before* current shot:
      // first shot: RNG_NB, second: RNG_NB-1, etc.
      const shootLeft = Math.max(0, rngNb - shotsFired);
      return { ...u, SHOOT_LEFT: shootLeft };
    }

    // During fight action, compute ATTACK_LEFT only for the active attacker,
    // mirroring PvP: counter shows attacks remaining *before* current swing.
    if (currentAction?.type === 'fight' && currentEpisode && currentActionIndex > 0 && u.id === currentAction.attacker_id) {
      // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get from selected weapon (imported at top)
      const selectedCcWeapon = getSelectedMeleeWeapon(u);
      const ccNb = selectedCcWeapon?.NB || 0;
      const attackerId = currentAction.attacker_id;

      const lastCompletedIndex = currentActionIndex - 2;
      if (lastCompletedIndex < 0) {
        return { ...u, ATTACK_LEFT: ccNb };
      }

      // Fight phase is delimited by non-fight actions
      let fightPhaseStart = 0;
      for (let i = lastCompletedIndex; i >= 0; i--) {
        const action = currentEpisode.actions[i];
        if (action.type !== 'fight') {
          fightPhaseStart = i + 1;
          break;
        }
      }

      let attacksUsed = 0;
      for (let i = fightPhaseStart; i <= lastCompletedIndex && i < currentEpisode.actions.length; i++) {
        const action = currentEpisode.actions[i];
        if (action.type === 'fight' && action.attacker_id === attackerId) {
          attacksUsed++;
        }
      }

      const attacksLeft = Math.max(0, ccNb - attacksUsed);
      return { ...u, ATTACK_LEFT: attacksLeft };
    }

    return u;
  }) : [];
  if (currentAction?.type === 'move' && currentAction?.from && currentAction.unit_id) {
    // Add a ghost unit at the starting position
    const originalUnit = unitsWithGhost.find((u: Unit) => u.id === currentAction.unit_id);
    if (originalUnit) {
      unitsWithGhost.push({
        ...originalUnit,
        id: -1, // Special ID for ghost unit
        col: currentAction.from.col,
        row: currentAction.from.row,
        isGhost: true // Mark as ghost for special rendering
      } as UnitWithGhost);
    }
  }

  // Add ghost unit at starting position for charge actions (like move)
  if (currentAction?.type === 'charge' && currentAction?.from && currentAction.unit_id) {
    // Add a ghost unit at the starting position
    const originalUnit = unitsWithGhost.find((u: Unit) => u.id === currentAction.unit_id);
    if (originalUnit) {
      unitsWithGhost.push({
        ...originalUnit,
        id: -2, // Special ID for charge ghost unit (different from move ghost)
        col: currentAction.from.col,
        row: currentAction.from.row,
        isGhost: true // Mark as ghost for special rendering
      } as UnitWithGhost);
    }
  }

  // Add ghost unit at starting position for advance actions (like move)
  if (currentAction?.type === 'advance' && currentAction?.from && currentAction.unit_id) {
    // Add a ghost unit at the starting position
    const originalUnit = unitsWithGhost.find((u: Unit) => u.id === currentAction.unit_id);
    if (originalUnit) {
      unitsWithGhost.push({
        ...originalUnit,
        id: -3, // Special ID for advance ghost unit (different from move and charge)
        col: currentAction.from.col,
        row: currentAction.from.row,
        isGhost: true // Mark as ghost for special rendering
      } as UnitWithGhost);
    }
  }

  // Update game log when action index changes
  useEffect(() => {
    if (!currentEpisode) return;
    if (!unitRegistryReady) return;

    // Clear and rebuild log up to current action
    gameLog.clearLog();

    // Track persistent objective control and log changes (replay mode)
    const objectiveControllers: Record<string, number | null> = {};
    const logObjectiveControlChanges = (
      units: Unit[],
      objectives: Array<{ name: string; hexes: Array<{ col: number; row: number }> }>,
      turnNumber: number
    ) => {
      for (const obj of objectives) {
        const hexSet = new Set(obj.hexes.map((h) => `${h.col},${h.row}`));
        let p1_oc = 0;
        let p2_oc = 0;

        for (const unit of units) {
          if (unit.id < 0) {
            continue;
          }
          if ((unit.HP_CUR ?? unit.HP_MAX) <= 0) {
            continue;
          }
          const unitHex = `${unit.col},${unit.row}`;
          if (hexSet.has(unitHex)) {
            if (unit.OC === undefined || unit.OC === null) {
              throw new Error(`Unit ${unit.id} missing required OC for objective control`);
            }
            if (unit.player === 1) {
              p1_oc += unit.OC;
            } else {
              p2_oc += unit.OC;
            }
          }
        }

        const prevController = objectiveControllers[obj.name] ?? null;
        let newController = prevController;
        if (p1_oc > p2_oc) {
          newController = 1;
        } else if (p2_oc > p1_oc) {
          newController = 2;
        }

        if (newController !== prevController) {
          if (newController === 1) {
            gameLog.addEvent({
              type: 'phase_change',
              message: `P1 controls objective ${obj.name} (OC ${p1_oc} vs ${p2_oc})`,
              turnNumber: turnNumber,
              phase: 'command',
              player: 1,
              action_name: 'objective_control'
            });
          } else if (newController === 2) {
            gameLog.addEvent({
              type: 'phase_change',
              message: `P2 controls objective ${obj.name} (OC ${p1_oc} vs ${p2_oc})`,
              turnNumber: turnNumber,
              phase: 'command',
              player: 2,
              action_name: 'objective_control'
            });
          } else {
            gameLog.addEvent({
              type: 'phase_change',
              message: `Objective ${obj.name} contested (OC ${p1_oc} vs ${p2_oc})`,
              turnNumber: turnNumber,
              phase: 'command',
              action_name: 'objective_control'
            });
          }
        }

        objectiveControllers[obj.name] = newController;
      }
    };

    for (let i = 0; i < currentActionIndex; i++) {
      const action = currentEpisode.actions[i];
      const turnNumber = parseInt(action.turn.replace('T', ''));

      if (action.type === 'move' && action.from && action.to) {
        gameLog.logMoveAction(
          { id: action.unit_id!, name: `Unit ${action.unit_id}` } as Unit,
          action.from.col,
          action.from.row,
          action.to.col,
          action.to.row,
          turnNumber,
          action.player
        );
      } else if (action.type === 'advance' && action.from && action.to) {
        // Calculate advance roll from distance between from and to
        const fromCube = offsetToCube(action.from.col, action.from.row);
        const toCube = offsetToCube(action.to.col, action.to.row);
        const advanceRoll = cubeDistance(fromCube, toCube);
        
        // Log advance actions with roll to match PvP/PvE format
        gameLog.addEvent({
          type: 'advance',
          message: `Unit ${action.unit_id} advanced from (${action.from.col},${action.from.row}) to (${action.to.col},${action.to.row}) (rolled ${advanceRoll})`,
          unitId: action.unit_id!,
          turnNumber: turnNumber,
          phase: 'shooting',
          startHex: `(${action.from.col},${action.from.row})`,
          endHex: `(${action.to.col},${action.to.row})`,
          player: action.player
        });
      } else if (action.type === 'move_wait' && action.pos) {
        gameLog.logNoMoveAction(
          { id: action.unit_id!, name: `Unit ${action.unit_id}` } as Unit,
          turnNumber,
          action.player
        );
      } else if (action.type === 'shoot_wait' && action.pos) {
        gameLog.addEvent({
          type: 'shoot',
          message: `Unit ${action.unit_id} (${action.pos.col},${action.pos.row}) chose not to shoot`,
          unitId: action.unit_id!,
          turnNumber: turnNumber,
          phase: 'shooting',
          player: action.player
        });
      } else if (action.type === 'shoot') {
        // Parse shooting details from log format to match PvP mode
        const shooterId = action.shooter_id!;
        const targetId = action.target_id!;
        const shooterPos = action.shooter_pos || { col: 0, row: 0 };
        const targetPos = action.target_pos || { col: 0, row: 0 };

        // Reconstruct message in the same format as shooting_handlers.py
        let message = '';
        const hitRoll = action.hit_roll;
        const woundRoll = action.wound_roll;
        const saveRoll = action.save_roll;
        const saveTarget = action.save_target || 0;
        const damage = action.damage || 0;

        // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Include weapon name if available
        const weaponName = action.weapon_name;
        const weaponSuffix = weaponName ? ` with [${weaponName}]` : '';

        // Determine hit target (assuming 3+ for now - could be in log later)
        const hitTarget = 3;
        const woundTarget = 4; // Assuming 4+ for now

        // Check if THIS shot killed the target by comparing HP before and after
        // Get target's HP from state BEFORE and AFTER this action
        const stateBeforeAction = i === 0 ? currentEpisode.initial_state : currentEpisode.states[i - 1];
        const stateAfterAction = currentEpisode.states[i];
        const targetBefore = stateBeforeAction?.units?.find((u: Unit) => u.id === targetId);
        const targetAfter = stateAfterAction?.units?.find((u: Unit) => u.id === targetId);
        const hpBefore = targetBefore ? targetBefore.HP_CUR : 0;
        const hpAfter = targetAfter ? targetAfter.HP_CUR : 0;

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
          message = `Unit ${shooterId} (${shooterPos.col},${shooterPos.row}) SHOT Unit ${targetId} (${targetPos.col},${targetPos.row})${weaponSuffix} : Hit ${hitRoll}(${hitTarget}+) : FAILED !`;
        } else if (woundRoll !== undefined && woundRoll < woundTarget) {
          // Wound failed
          message = `Unit ${shooterId} (${shooterPos.col},${shooterPos.row}) SHOT Unit ${targetId} (${targetPos.col},${targetPos.row})${weaponSuffix} : Hit ${hitRoll}(${hitTarget}+) - Wound ${woundRoll}(${woundTarget}+) : FAILED !`;
        } else if (saveRoll !== undefined && saveTarget > 0 && saveRoll >= saveTarget) {
          // Save succeeded
          message = `Unit ${shooterId} (${shooterPos.col},${shooterPos.row}) SHOT Unit ${targetId} (${targetPos.col},${targetPos.row})${weaponSuffix} : Hit ${hitRoll}(${hitTarget}+) - Wound ${woundRoll}(${woundTarget}+) - Save ${saveRoll}(${saveTarget}+) : SAVED !`;
        } else if (damage > 0) {
          // Damage dealt
          message = `Unit ${shooterId} (${shooterPos.col},${shooterPos.row}) SHOT Unit ${targetId} (${targetPos.col},${targetPos.row})${weaponSuffix} : Hit ${hitRoll}(${hitTarget}+) - Wound ${woundRoll}(${woundTarget}+) - Save ${saveRoll}(${saveTarget}+) - ${damage} DAMAGE DELT !`;
        } else {
          // Fallback
          message = `Unit ${shooterId} (${shooterPos.col},${shooterPos.row}) SHOT Unit ${targetId} (${targetPos.col},${targetPos.row})${weaponSuffix}`;
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
          is_ai_action: action.player === 2,
          reward: action.reward,
          action_name: 'shoot'
        });

        // Add separate death event if target was killed (like PvP mode does)
        if (targetDied && targetAfter) {
          const targetType = targetAfter.type || 'Unknown';
          gameLog.addEvent({
            type: 'death',
            message: `Unit ${targetId} (${targetType}) was DESTROYED!`,
            unitId: targetId,
            turnNumber: turnNumber,
            phase: 'shooting',
            player: action.player  // Use acting player (shooter), not target's player
          });
        }
      } else if (action.type === 'charge' && action.from && action.to) {
        // Handle charge actions
        const unitId = action.unit_id!;
        const targetId = action.target_id;
        const chargeRollValue = action.charge_roll;
        const rollInfo = chargeRollValue !== undefined ? ` (rolled ${chargeRollValue})` : '';
        const targetPos = action.target_pos || { col: 0, row: 0 };

        gameLog.addEvent({
          type: 'charge',
          message: `Unit ${unitId}(${action.to.col},${action.to.row}) CHARGED Unit ${targetId}(${targetPos.col},${targetPos.row}) from (${action.from.col},${action.from.row}) to (${action.to.col},${action.to.row})${rollInfo}`,
          unitId: unitId,
          targetId: targetId,
          turnNumber: turnNumber,
          phase: 'charge',
          player: action.player,
          startHex: `(${action.from.col},${action.from.row})`,
          endHex: `(${action.to.col},${action.to.row})`
        });
      } else if (action.type === 'charge_wait') {
        // Handle charge wait actions (failed charge or chose not to charge)
        const unitId = action.unit_id!;
        const chargeRollValue = action.charge_roll;
        const rollMessage = chargeRollValue !== undefined && chargeRollValue > 0
          ? `Unit ${unitId} failed charge (rolled ${chargeRollValue})`
          : `Unit ${unitId} chose not to charge`;
        gameLog.addEvent({
          type: 'charge_fail',  // Use charge_fail type for light purple styling
          message: rollMessage,
          unitId: unitId,
          turnNumber: turnNumber,
          phase: 'charge',
          player: action.player
        });
      } else if (action.type === 'charge_fail') {
        // Handle explicit charge_fail actions (from train_step.log)
        const unitId = action.unit_id!;
        const targetId = action.target_id;
        const chargeRollValue = action.charge_roll || 0;
        const rollMessage = targetId
          ? `Unit ${unitId} FAILED charge to unit ${targetId} (Roll: ${chargeRollValue})`
          : `Unit ${unitId} FAILED charge (Roll: ${chargeRollValue})`;
        gameLog.addEvent({
          type: 'charge_fail',  // Use charge_fail type for light purple styling
          message: rollMessage,
          unitId: unitId,
          targetId: targetId,
          turnNumber: turnNumber,
          phase: 'charge',
          player: action.player
        });
      } else if (action.type === 'fight') {
        // Handle fight actions
        const attackerId = action.attacker_id!;
        const targetId = action.target_id!;
        const attackerPos = action.attacker_pos || { col: 0, row: 0 };
        
        // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Include weapon name if available
        const weaponName = action.weapon_name;
        const weaponSuffix = weaponName ? ` with [${weaponName}]` : '';

        // Build message based on combat results
        let message = `Unit ${attackerId} (${attackerPos.col},${attackerPos.row}) FOUGHT Unit ${targetId}${weaponSuffix}`;
        if (action.hit_roll !== undefined) {
          const hitResult = action.hit_result || (action.hit_roll >= (action.hit_target || 3) ? 'HIT' : 'MISS');
          message += ` : Hit ${action.hit_roll}(${action.hit_target || 3}+)`;
          if (hitResult === 'HIT' && action.wound_roll !== undefined) {
            const woundResult = action.wound_result || (action.wound_roll >= (action.wound_target || 4) ? 'WOUND' : 'FAIL');
            message += ` - Wound ${action.wound_roll}(${action.wound_target || 4}+)`;
            if (woundResult === 'WOUND' || woundResult === 'SUCCESS') {
              if (action.save_roll !== undefined) {
                message += ` - Save ${action.save_roll}(${action.save_target || 6}+)`;
              }
              if (action.damage && action.damage > 0) {
                message += ` - ${action.damage} DAMAGE DELT !`;
              }
            } else {
              message += ` : FAILED !`;
            }
          } else if (hitResult === 'MISS') {
            message += ` : FAILED !`;
          }
        }

        // Get target info for death check
        const stateAfterAction = currentEpisode.states[i];
        const target = stateAfterAction?.units?.find((u: Unit) => u.id === targetId);
        const stateBeforeAction = i === 0 ? currentEpisode.initial_state : currentEpisode.states[i - 1];
        const targetBefore = stateBeforeAction?.units?.find((u: Unit) => u.id === targetId);
        const hpBefore = targetBefore ? targetBefore.HP_CUR : 0;
        const hpAfter = target ? target.HP_CUR : 0;
        const targetDied = hpBefore > 0 && hpAfter <= 0;

        // Determine the correct player to attribute this combat action to:
        // use the attacker unit's player, not the current turn player.
        const attackerUnitBefore = stateBeforeAction?.units?.find((u: Unit) => u.id === attackerId);
        const attackerPlayer = attackerUnitBefore ? attackerUnitBefore.player : action.player;

        // Build shootDetails for color coding
        const fightDetails = action.hit_roll !== undefined ? [{
          shotNumber: 1,
          attackRoll: action.hit_roll,
          strengthRoll: action.wound_roll || 0,
          hitResult: action.hit_result || 'MISS',
          strengthResult: action.wound_result || 'FAILED',
          saveRoll: action.save_roll,
          saveTarget: action.save_target,
          saveSuccess: action.save_roll !== undefined && action.save_target ? action.save_roll >= action.save_target : false,
          damageDealt: action.damage || 0
        }] : undefined;

        gameLog.addEvent({
          type: 'combat',
          message,
          unitId: attackerId,
          targetId: targetId,
          turnNumber: turnNumber,
          phase: 'fight',
          player: attackerPlayer,
          shootDetails: fightDetails,
          is_ai_action: action.player === 2,
          reward: action.reward,
          action_name: 'fight'
        });

        // Add death event if target died
        if (targetDied && target) {
          const targetType = target.type || 'Unknown';
          gameLog.addEvent({
            type: 'death',
            message: `Unit ${targetId} (${targetType}) was DESTROYED!`,
            unitId: targetId,
            turnNumber: turnNumber,
            phase: 'fight',
            // Attribute death to the attacker player for consistency
            player: attackerPlayer
          });
        }
      }

      const stateAfterAction = currentEpisode.states[i];
      const objectives = stateAfterAction?.objectives || currentEpisode.initial_state.objectives || [];
      if (objectives.length > 0 && stateAfterAction?.units) {
        const enrichedObjectiveUnits = enrichUnitsWithStats(stateAfterAction.units as Unit[]);
        logObjectiveControlChanges(enrichedObjectiveUnits, objectives, turnNumber);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentActionIndex, currentEpisode, unitRegistryReady]);

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
            phases={["command", "move", "shoot", "charge", "fight"]}
            currentPlayer={currentState.currentPlayer}
            maxTurns={gameConfig.game_rules.max_turns}
            className=""
            onTurnClick={(turn) => {
              // Find the first action of the selected turn
              const targetTurn = `T${turn}`;
              
              // First, find the last action of the previous turn (turn - 1)
              // This ensures we skip any actions from turn 1 that might have turn === "T2" (like death actions)
              const previousTurn = `T${turn - 1}`;
              let lastPreviousTurnIndex = -1;
              
              // Find the last action of the previous turn
              for (let i = currentEpisode.actions.length - 1; i >= 0; i--) {
                if (currentEpisode.actions[i].turn === previousTurn) {
                  lastPreviousTurnIndex = i;
                  break;
                }
              }
              
              // Now find the first action of the target turn that comes AFTER the last action of previous turn
              const startSearchIndex = lastPreviousTurnIndex + 1;
              const firstActionArrayIndex = currentEpisode.actions.findIndex(
                (action, index) => index >= startSearchIndex && action.turn === targetTurn
              );
              
              if (firstActionArrayIndex !== -1) {
                // currentActionIndex represents number of actions executed
                // To show the FIRST action of turn N (currentAction will be actions[firstActionArrayIndex]),
                // we need currentActionIndex = firstActionArrayIndex + 1
                // This makes currentAction = actions[currentActionIndex - 1] = actions[firstActionArrayIndex]
                setCurrentActionIndex(firstActionArrayIndex + 1);
                setIsPlaying(false); // Pause playback if playing
              } else {
                // If turn not found, go to start (turn 1, action 0)
                setCurrentActionIndex(0);
                setIsPlaying(false);
              }
            }}
            onPhaseClick={(phase) => {
              // Get the current turn from the state we're viewing
              // We need to determine which turn we're currently in based on currentActionIndex
              let currentTurn: string;
              if (currentActionIndex === 0) {
                // At initial state, get turn from first action
                currentTurn = currentEpisode.actions[0]?.turn || 'T1';
              } else {
                // Get turn from the action that will be executed next (the one at currentActionIndex)
                // Or from the last executed action if we're viewing its result
                const nextAction = currentEpisode.actions[currentActionIndex];
                if (nextAction) {
                  currentTurn = nextAction.turn;
                } else {
                  // We're at the end, get turn from last action
                  const lastAction = currentEpisode.actions[currentActionIndex - 1];
                  currentTurn = lastAction?.turn || currentEpisode.actions[0]?.turn || 'T1';
                }
              }
              
              // Map phase names to action types
              const phaseToActionTypes: Record<string, string[]> = {
                'move': ['move', 'move_wait'],
                'shoot': ['shoot', 'shoot_wait', 'advance'],
                'charge': ['charge', 'charge_wait', 'charge_fail'],
                'fight': ['fight']
              };
              
              const actionTypes = phaseToActionTypes[phase] || [phase];
              
              // Get the current player from the state
              const currentPlayer = currentState.currentPlayer;
              
              // Find the first action of the selected phase in the current turn for the current player
              const firstPhaseActionArrayIndex = currentEpisode.actions.findIndex(action => {
                return action.turn === currentTurn && 
                       action.player === currentPlayer &&
                       actionTypes.includes(action.type);
              });
              
              if (firstPhaseActionArrayIndex !== -1) {
                // To show the FIRST action of the phase (currentAction will be actions[firstPhaseActionArrayIndex]),
                // we need currentActionIndex = firstPhaseActionArrayIndex + 1
                // This makes currentAction = actions[currentActionIndex - 1] = actions[firstPhaseActionArrayIndex]
                setCurrentActionIndex(firstPhaseActionArrayIndex + 1);
                setIsPlaying(false); // Pause playback if playing
              }
            }}
            onPlayerClick={(player) => {
              // Get the current turn from the state we're viewing
              let currentTurn: string;
              if (currentActionIndex === 0) {
                currentTurn = currentEpisode.actions[0]?.turn || 'T1';
              } else {
                const nextAction = currentEpisode.actions[currentActionIndex];
                if (nextAction) {
                  currentTurn = nextAction.turn;
                } else {
                  const lastAction = currentEpisode.actions[currentActionIndex - 1];
                  currentTurn = lastAction?.turn || currentEpisode.actions[0]?.turn || 'T1';
                }
              }
              
              // Find the first action of the current turn for the selected player
              // The first action of a player's turn is typically in the "command" phase
              const firstPlayerActionArrayIndex = currentEpisode.actions.findIndex(action => {
                return action.turn === currentTurn && action.player === player;
              });
              
              if (firstPlayerActionArrayIndex !== -1) {
                // To show the FIRST action of the player's turn (currentAction will be actions[firstPlayerActionArrayIndex]),
                // we need currentActionIndex = firstPlayerActionArrayIndex + 1
                setCurrentActionIndex(firstPlayerActionArrayIndex + 1);
                setIsPlaying(false); // Pause playback if playing
              }
            }}
          />
        </div>
      )}

      {/* File and Episode selector - single line */}
      <div className="replay-file-selector-container">
        <div className="replay-selector-row">
          {/* Left: File dropdown (loads from server) */}
          <div className="replay-browse-group">
            <select
              value={selectedFileName || ''}
              onChange={(e) => handleFileSelectFromServer(e.target.value)}
              className="replay-file-select"
            >
              <option value="">Select log file from server...</option>
              {availableLogFiles.map((log) => (
                <option key={log.name} value={log.name}>
                  {log.name} ({Math.round(log.size / 1024)}KB, {log.modified})
                </option>
              ))}
            </select>
            {selectedFileName && (
              <span className="replay-file-status">
                Loaded: {selectedFileName}
              </span>
            )}
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
                // Extract scenario identifier (e.g., "phase1-bot3" from "..._scenario_phase1-bot3" or just "phase1-bot3")
                let scenarioId = '';
                if (ep.scenario) {
                  const scenarioMatch = ep.scenario.match(/_scenario_(.+)$/);
                  if (scenarioMatch) {
                    scenarioId = scenarioMatch[1];
                  } else {
                    // If no _scenario_ prefix, use the scenario name as-is (but avoid "Unknown Scenario")
                    scenarioId = ep.scenario !== 'Unknown Scenario' ? ep.scenario : '';
                  }
                }
                return (
                  <option key={ep.episode_num} value={ep.episode_num}>
                    Episode {ep.episode_num} - {scenarioId || 'Unknown'} - {ep.bot_name || 'Unknown'} - {ep.final_result || 'Unknown'}{ep.win_method ? ` (${ep.win_method})` : ''}
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
              player={1}
              selectedUnitId={null}
              clickedUnitId={null}
              onSelectUnit={() => {}}
              gameMode="training"
              isReplay={true}
              onCollapseChange={() => {}}
            />
          </ErrorBoundary>

          <ErrorBoundary fallback={<div>Failed to load player 1 status</div>}>
            <UnitStatusTable
              units={currentState.units || []}
              player={2}
              selectedUnitId={null}
              clickedUnitId={null}
              onSelectUnit={() => {}}
              gameMode="training"
              isReplay={true}
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

  // Get charging unit ID for lightning icon during charge phase (include charge_wait and charge_fail for failed charge badge)
  const chargingUnitId = (currentAction?.type === 'charge' || currentAction?.type === 'charge_wait' || currentAction?.type === 'charge_fail') && currentAction?.unit_id
    ? currentAction.unit_id
    : null;
  // Get charge target ID for target logo (include charge_fail and charge_wait so logo appears even when charge fails)
  const chargeTargetId = (currentAction?.type === 'charge' || currentAction?.type === 'charge_fail' || currentAction?.type === 'charge_wait') && currentAction?.target_id
    ? currentAction.target_id
    : null;

  // Get fighting unit ID for crossed swords icon during fight phase
  const fightingUnitId = currentAction?.type === 'fight' && currentAction?.attacker_id
    ? currentAction.attacker_id
    : null;
  const fightTargetId = currentAction?.type === 'fight' && currentAction?.target_id
    ? currentAction.target_id
    : null;

  // Get charge roll info for badge display
  const chargeRoll = (currentAction?.type === 'charge' || currentAction?.type === 'charge_wait' || currentAction?.type === 'charge_fail') && currentAction?.charge_roll !== undefined
    ? currentAction.charge_roll
    : null;
  const chargeSuccess = (currentAction?.type === 'charge' || currentAction?.type === 'charge_wait' || currentAction?.type === 'charge_fail')
    ? (currentAction?.charge_success !== false && currentAction?.type !== 'charge_fail')  // charge_fail is always false
    : false;

  // Get advance roll info for badge display
  const advanceRoll = (currentAction?.type === 'advance' && currentAction?.advance_roll !== undefined)
    ? currentAction.advance_roll
    : null;
    const advancingUnitId = (currentAction?.type === 'advance' && currentAction?.unit_id)
    ? currentAction.unit_id  // Use real unit ID so icon shows on preview at destination, not on ghost
    : null;

  // For move actions, select the ghost unit to show movement range
  // For shoot actions, select the shooter to show LoS/attack range
  // For charge actions, select the charging unit to show charge destination
  // For advance actions, select the ghost unit to show advance destinations
  // Ghost unit has ID -1 (move), -2 (charge), or -3 (advance) and is at the starting position
  const replaySelectedUnitId: number | null = currentAction?.type === 'move'
    ? -1
    : (currentAction?.type === 'charge'
      ? (currentAction.unit_id ?? null)  // Select the actual charging unit to trigger getChargeDestinations
      : (currentAction?.type === 'advance'
        ? -3  // Select the ghost unit to trigger getAdvanceDestinations
        : (currentAction?.type === 'shoot' ? (currentAction.shooter_id ?? null) : null)));

  // Center column: Board
  const centerContent = currentState && gameConfig ? (
    <BoardPvp
      units={unitsWithGhost}
      selectedUnitId={replaySelectedUnitId}
      eligibleUnitIds={unitsWithGhost.map((u: Unit) => u.id)}
      showHexCoordinates={showHexCoordinates}
      mode={currentAction?.type === 'advance' ? 'advancePreview' : 'select'}
      movePreview={currentAction?.type === 'advance' && currentAction?.to && currentAction?.unit_id
        ? { unitId: currentAction.unit_id, destCol: currentAction.to.col, destRow: currentAction.to.row }
        : null}
      attackPreview={null}
      onSelectUnit={() => {}}
      onStartMovePreview={() => {}}
      onDirectMove={() => {}}
      onStartAttackPreview={() => {}}
      onConfirmMove={() => {}}
      onCancelMove={() => {}}
      currentPlayer={(currentAction?.type === 'move' || currentAction?.type === 'shoot' || currentAction?.type === 'charge' || currentAction?.type === 'fight') ? (currentAction.player as 1 | 2) : (currentState.currentPlayer || 1)}
      unitsMoved={[]}
      phase={currentState.phase || 'move'}
      onShoot={() => {}}
      gameState={currentState as GameState}
      replayActionIndex={currentActionIndex}
      getChargeDestinations={(unitId: number) => {
        // Calculate ALL valid charge destinations for replay mode using BFS
        if (currentAction?.type === 'charge' && currentAction?.from && currentAction.unit_id === unitId) {
          const chargeFrom = currentAction.from;
          // Use the charge_roll from the action, not the actual distance traveled
          const chargeRoll = currentAction.charge_roll;
          
          if (!chargeRoll || chargeRoll <= 0) {
            return [];
          }

          // Find all enemy units (units from the other player)
          const chargingUnit = unitsWithGhost.find((u: Unit) => u.id === unitId);
          if (!chargingUnit) {
            return [];
          }

          const enemyUnits = unitsWithGhost.filter((u: Unit) =>
            u.player !== chargingUnit?.player &&
            u.id >= 0 && // Not a ghost unit
            u.HP_CUR > 0
          );

          if (enemyUnits.length === 0) {
            return [];
          }

          // Helper function to get hex neighbors (6 directions)
          const getHexNeighbors = (col: number, row: number): { col: number; row: number }[] => {
            const parity = col & 1; // 0 for even, 1 for odd
            if (parity === 0) { // Even column
              return [
                { col, row: row - 1 },      // N
                { col: col + 1, row: row - 1 }, // NE
                { col: col + 1, row },     // SE
                { col, row: row + 1 },      // S
                { col: col - 1, row },      // SW
                { col: col - 1, row: row - 1 } // NW
              ];
            } else { // Odd column
              return [
                { col, row: row - 1 },      // N
                { col: col + 1, row },      // NE
                { col: col + 1, row: row + 1 }, // SE
                { col, row: row + 1 },      // S
                { col: col - 1, row: row + 1 }, // SW
                { col: col - 1, row }       // NW
              ];
            }
          };

          // Helper function to check if hex is traversable
          const isTraversable = (col: number, row: number): boolean => {
            const boardCols = currentState?.board_cols || 25;
            const boardRows = currentState?.board_rows || 21;
            
            // Check bounds
            if (col < 0 || row < 0 || col >= boardCols || row >= boardRows) {
              return false;
            }
            
            // Check walls
            if (currentState?.walls?.some((w: { col: number; row: number }) => w.col === col && w.row === row)) {
              return false;
            }
            
            // Check if occupied by another unit (excluding the charging unit)
            if (unitsWithGhost.some((u: Unit) =>
              u.col === col && u.row === row && u.id !== unitId && u.id >= 0 && u.HP_CUR > 0
            )) {
              return false;
            }
            
            return true;
          };

          // Helper function to check if hex is adjacent to an enemy
          const isAdjacentToEnemy = (col: number, row: number): boolean => {
            const hexCube = offsetToCube(col, row);
            return enemyUnits.some((enemy: Unit) => {
              const enemyCube = offsetToCube(enemy.col, enemy.row);
              return cubeDistance(hexCube, enemyCube) === 1;
            });
          };

          // BFS to find all reachable hexes within charge_roll distance
          const validDestinations: { col: number; row: number }[] = [];
          const visited = new Set<string>();
          const queue: Array<{ col: number; row: number; distance: number }> = [];
          
          const startKey = `${chargeFrom.col},${chargeFrom.row}`;
          visited.add(startKey);
          queue.push({ col: chargeFrom.col, row: chargeFrom.row, distance: 0 });

          while (queue.length > 0) {
            const current = queue.shift()!;
            
            // If we've reached max charge range, don't explore further
            if (current.distance >= chargeRoll) {
              continue;
            }

            // Explore all 6 hex neighbors
            const neighbors = getHexNeighbors(current.col, current.row);
            
            for (const neighbor of neighbors) {
              const neighborKey = `${neighbor.col},${neighbor.row}`;
              
              // Skip if already visited
              if (visited.has(neighborKey)) {
                continue;
              }

              // Check if traversable
              if (!isTraversable(neighbor.col, neighbor.row)) {
                continue;
              }

              // Mark as visited
              visited.add(neighborKey);
              const neighborDistance = current.distance + 1;

              // Check if this hex is adjacent to an enemy (valid destination)
              if (isAdjacentToEnemy(neighbor.col, neighbor.row)) {
                // Double-check that the destination hex is not occupied
                if (!unitsWithGhost.some((u: Unit) =>
                  u.col === neighbor.col && u.row === neighbor.row && u.id !== unitId && u.id >= 0 && u.HP_CUR > 0
                )) {
                  validDestinations.push({ col: neighbor.col, row: neighbor.row });
                }
              }

              // Continue exploring (charges can move through enemy-adjacent hexes)
              queue.push({ col: neighbor.col, row: neighbor.row, distance: neighborDistance });
            }
          }

          return validDestinations;
        }
        return [];
      }}
      getAdvanceDestinations={(unitId: number) => {
        // Calculate ALL valid advance destinations for replay mode using BFS
        // For advance, unitId will be -3 (ghost unit), so we need to find the actual unit
        if (currentAction?.type === 'advance' && currentAction?.from && currentAction?.advance_roll && unitId === -3) {
          const advanceFrom = currentAction.from;
          const advanceRollValue = currentAction.advance_roll;
          
          if (!advanceRollValue || advanceRollValue <= 0) {
            return [];
          }

          // Find the advancing unit (actual unit, not ghost)
          const advancingUnit = unitsWithGhost.find((u: Unit) => u.id === currentAction.unit_id);
          if (!advancingUnit) {
            return [];
          }

          // Helper function to get hex neighbors (6 directions)
          const getHexNeighbors = (col: number, row: number): { col: number; row: number }[] => {
            const parity = col & 1; // 0 for even, 1 for odd
            if (parity === 0) { // Even column
              return [
                { col, row: row - 1 },      // N
                { col: col + 1, row: row - 1 }, // NE
                { col: col + 1, row },     // SE
                { col, row: row + 1 },      // S
                { col: col - 1, row },      // SW
                { col: col - 1, row: row - 1 } // NW
              ];
            } else { // Odd column
              return [
                { col, row: row - 1 },      // N
                { col: col + 1, row },      // NE
                { col: col + 1, row: row + 1 }, // SE
                { col, row: row + 1 },      // S
                { col: col - 1, row: row + 1 }, // SW
                { col: col - 1, row }       // NW
              ];
            }
          };

          // Helper function to check if hex is traversable (advance cannot end adjacent to enemies)
          const isTraversable = (col: number, row: number): boolean => {
            const boardCols = currentState?.board_cols || 25;
            const boardRows = currentState?.board_rows || 21;
            
            // Check bounds
            if (col < 0 || row < 0 || col >= boardCols || row >= boardRows) {
              return false;
            }
            
            // Check walls
            if (currentState?.walls?.some((w: { col: number; row: number }) => w.col === col && w.row === row)) {
              return false;
            }
            
            // Check if occupied by another unit (excluding the advancing unit)
            if (unitsWithGhost.some((u: Unit) =>
              u.col === col && u.row === row && u.id !== currentAction.unit_id && u.id >= 0 && u.HP_CUR > 0
            )) {
              return false;
            }
            
            return true;
          };

          // BFS to find all reachable hexes within advance_roll distance
          const validDestinations: { col: number; row: number }[] = [];
          const visited = new Set<string>();
          const queue: Array<{ col: number; row: number; distance: number }> = [{ col: advanceFrom.col, row: advanceFrom.row, distance: 0 }];
          visited.add(`${advanceFrom.col},${advanceFrom.row}`);

          while (queue.length > 0) {
            const current = queue.shift()!;
            const { col, row, distance } = current;

            if (distance > 0 && distance <= advanceRollValue && isTraversable(col, row)) {
              validDestinations.push({ col, row });
            }

            if (distance < advanceRollValue) {
              const neighbors = getHexNeighbors(col, row);
              for (const neighbor of neighbors) {
                const neighborKey = `${neighbor.col},${neighbor.row}`;
                if (!visited.has(neighborKey)) {
                  visited.add(neighborKey);
                  const neighborDistance = distance + 1;
                  if (neighborDistance <= advanceRollValue && isTraversable(neighbor.col, neighbor.row)) {
                    queue.push({ col: neighbor.col, row: neighbor.row, distance: neighborDistance });
                  }
                }
              }
            }
          }

          return validDestinations;
        }
        return [];
      }}
      advanceRoll={advanceRoll}
      advancingUnitId={advancingUnitId}
      shootingTargetId={shootingTargetId}
      shootingUnitId={shootingUnitId}
      movingUnitId={movingUnitId}
      chargingUnitId={chargingUnitId}
      chargeTargetId={chargeTargetId}
      fightingUnitId={fightingUnitId}
      fightTargetId={fightTargetId}
      chargeRoll={chargeRoll}
      chargeSuccess={chargeSuccess}
      wallHexesOverride={currentState.walls}
      objectivesOverride={currentState.objectives}
      availableCellsOverride={(() => {
        if (currentAction?.type === 'advance' && currentAction?.from && (currentAction?.advance_roll !== undefined || currentAction?.to)) {
          return (() => {
            const advanceFrom = currentAction.from;
            // Use advance_roll from log (the actual dice roll), NOT the distance traveled
            let advanceRollValue: number;
            if (currentAction.advance_roll !== undefined) {
              advanceRollValue = currentAction.advance_roll;
            } else if (currentAction.to) {
              // Fallback: calculate from distance (should not happen if parser works correctly)
              const fromCube = offsetToCube(advanceFrom.col, advanceFrom.row);
              const toCube = offsetToCube(currentAction.to.col, currentAction.to.row);
              advanceRollValue = cubeDistance(fromCube, toCube);
            } else {
              return [];
            }
            
            if (!advanceRollValue || advanceRollValue <= 0) {
              return [];
            }

            const advancingUnit = unitsWithGhost.find((u: Unit) => u.id === currentAction.unit_id);
            if (!advancingUnit) {
              return [];
            }

            const getHexNeighbors = (col: number, row: number): { col: number; row: number }[] => {
              const parity = col & 1;
              if (parity === 0) {
                return [
                  { col, row: row - 1 },
                  { col: col + 1, row: row - 1 },
                  { col: col + 1, row },
                  { col, row: row + 1 },
                  { col: col - 1, row },
                  { col: col - 1, row: row - 1 }
                ];
              } else {
                return [
                  { col, row: row - 1 },
                  { col: col + 1, row },
                  { col: col + 1, row: row + 1 },
                  { col, row: row + 1 },
                  { col: col - 1, row: row + 1 },
                  { col: col - 1, row }
                ];
              }
            };

            const isTraversable = (col: number, row: number): boolean => {
              const boardCols = currentState?.board_cols || 25;
              const boardRows = currentState?.board_rows || 21;
              
              if (col < 0 || row < 0 || col >= boardCols || row >= boardRows) {
                return false;
              }
              
              if (currentState?.walls?.some((w: { col: number; row: number }) => w.col === col && w.row === row)) {
                return false;
              }
              
              if (unitsWithGhost.some((u: Unit) =>
                u.col === col && u.row === row && u.id !== currentAction.unit_id && u.id >= 0 && u.HP_CUR > 0
              )) {
                return false;
              }
              
              return true;
            };

            const validDestinations: { col: number; row: number }[] = [];
            const visited = new Set<string>();
            const queue: Array<{ col: number; row: number; distance: number }> = [{ col: advanceFrom.col, row: advanceFrom.row, distance: 0 }];
            visited.add(`${advanceFrom.col},${advanceFrom.row}`);

            while (queue.length > 0) {
              const current = queue.shift()!;
              const { col, row, distance } = current;

              if (distance > 0 && distance <= advanceRollValue && isTraversable(col, row)) {
                validDestinations.push({ col, row });
              }

              if (distance < advanceRollValue) {
                const neighbors = getHexNeighbors(col, row);
                for (const neighbor of neighbors) {
                  const neighborKey = `${neighbor.col},${neighbor.row}`;
                  if (!visited.has(neighborKey)) {
                    visited.add(neighborKey);
                    const neighborDistance = distance + 1;
                    if (neighborDistance <= advanceRollValue && isTraversable(neighbor.col, neighbor.row)) {
                      queue.push({ col: neighbor.col, row: neighbor.row, distance: neighborDistance });
                    }
                  }
                }
              }
            }

            return validDestinations;
          })();
        }
        return undefined;
      })()}
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

  return (
    <>
      <SharedLayout
        rightColumnContent={rightColumnContent}
        onOpenSettings={handleOpenSettings}
      >
        {centerContent}
      </SharedLayout>
      <SettingsMenu
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        showAdvanceWarning={false}
        onToggleAdvanceWarning={() => {}}
        showDebug={settings.showDebug}
        onToggleDebug={handleToggleDebug}
        autoSelectWeapon={true}
        onToggleAutoSelectWeapon={() => {}}
      />
    </>
  );
};
