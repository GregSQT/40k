// frontend/src/utils/replayParser.ts
// Parse train_step.log into replay format on the frontend

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
  initial_state: any;
  actions: ReplayAction[];
  states: any[];
  total_actions: number;
  final_result: string | null;
}

export function parse_log_file_from_text(text: string) {
  console.log('Starting replay parser...');
  const lines = text.split('\n');
  const episodes: any[] = [];
  let currentEpisode: any = null;

  for (const line of lines) {
    const trimmed = line.trim();

    // Debug: log all SHOOT lines
    if (trimmed.includes(' SHOOT :')) {
      console.log('RAW SHOOT LINE:', trimmed);
    }

    // Episode start
    if (trimmed.includes('=== EPISODE START ===')) {
      if (currentEpisode) {
        episodes.push(currentEpisode);
      }
      currentEpisode = {
        episode_num: episodes.length + 1,
        actions: [],
        units: {},
        initial_positions: {},
        final_result: null,
        scenario: 'Unknown'
      };
      continue;
    }

    if (!currentEpisode) continue;

    // Scenario name
    const scenarioMatch = trimmed.match(/Scenario: (.+)/);
    if (scenarioMatch) {
      currentEpisode.scenario = scenarioMatch[1];
      continue;
    }

    // Unit starting positions
    const unitStart = trimmed.match(/Unit (\d+) \((.+?)\) P(\d+): Starting position \((\d+), (\d+)\)/);
    if (unitStart) {
      const unitId = parseInt(unitStart[1]);
      const unitType = unitStart[2];
      const player = parseInt(unitStart[3]);
      const col = parseInt(unitStart[4]);
      const row = parseInt(unitStart[5]);

      currentEpisode.units[unitId] = {
        id: unitId,
        type: unitType,
        player: player,
        col: col,
        row: row,
        HP_CUR: 2,
        HP_MAX: 2
      };
      currentEpisode.initial_positions[unitId] = { col, row };
      continue;
    }

    // Parse MOVE actions
    const moveMatch = trimmed.match(/\[([^\]]+)\] (T\d+) P(\d+) MOVE : Unit (\d+)\((\d+), (\d+)\) (MOVED|WAIT)/);
    if (moveMatch) {
      const timestamp = moveMatch[1];
      const turn = moveMatch[2];
      const player = parseInt(moveMatch[3]);
      const unitId = parseInt(moveMatch[4]);
      const endCol = parseInt(moveMatch[5]);
      const endRow = parseInt(moveMatch[6]);
      const actionType = moveMatch[7];

      if (actionType === 'MOVED') {
        const fromMatch = trimmed.match(/from \((\d+), (\d+)\)/);
        let fromCol = endCol;
        let fromRow = endRow;
        if (fromMatch) {
          fromCol = parseInt(fromMatch[1]);
          fromRow = parseInt(fromMatch[2]);
        } else if (currentEpisode.units[unitId]) {
          fromCol = currentEpisode.units[unitId].col;
          fromRow = currentEpisode.units[unitId].row;
        }

        currentEpisode.actions.push({
          type: 'move',
          timestamp,
          turn,
          player,
          unit_id: unitId,
          from: { col: fromCol, row: fromRow },
          to: { col: endCol, row: endRow }
        });

        if (currentEpisode.units[unitId]) {
          currentEpisode.units[unitId].col = endCol;
          currentEpisode.units[unitId].row = endRow;
        }
      } else if (actionType === 'WAIT') {
        currentEpisode.actions.push({
          type: 'move_wait',
          timestamp,
          turn,
          player,
          unit_id: unitId,
          pos: { col: endCol, row: endRow }
        });
      }
      continue;
    }

    // Parse SHOOT actions
    const shootMatch = trimmed.match(/\[([^\]]+)\] (T\d+) P(\d+) SHOOT : Unit (\d+)\((\d+), (\d+)\) (SHOT|WAIT)/);
    if (shootMatch) {
      console.log('Matched SHOOT line:', trimmed);
      const timestamp = shootMatch[1];
      const turn = shootMatch[2];
      const player = parseInt(shootMatch[3]);
      const shooterId = parseInt(shootMatch[4]);
      const shooterCol = parseInt(shootMatch[5]);
      const shooterRow = parseInt(shootMatch[6]);
      const actionType = shootMatch[7];
      console.log('Action type:', actionType);

      if (actionType === 'SHOT') {
        const targetMatch = trimmed.match(/SHOT at unit (\d+)/);
        const damageMatch = trimmed.match(/Dmg:(\d+)HP/);

        // Try to extract detailed combat rolls from format: Hit:3+:6(HIT) Wound:4+:5(SUCCESS) Save:3+:2(FAILED)
        const hitMatch = trimmed.match(/Hit:(\d+)\+:(\d+)/);
        const woundMatch = trimmed.match(/Wound:(\d+)\+:(\d+)/);
        const saveMatch = trimmed.match(/Save:(\d+)\+:(\d+)/);

        console.log('Parsing shoot line:', trimmed);
        if (hitMatch) console.log('Found Hit - target:', hitMatch[1], 'roll:', hitMatch[2]);

        if (targetMatch) {
          const targetId = parseInt(targetMatch[1]);
          const damage = damageMatch ? parseInt(damageMatch[1]) : 0;

          const action: any = {
            type: 'shoot',
            timestamp,
            turn,
            player,
            shooter_id: shooterId,
            shooter_pos: { col: shooterCol, row: shooterRow },
            target_id: targetId,
            damage
          };

          // Add detailed rolls if available (format: Hit:3+:6 means target 3+, rolled 6)
          if (hitMatch) {
            action.hit_roll = parseInt(hitMatch[2]);  // The actual roll
            action.save_target = parseInt(hitMatch[1]);  // Will be overridden by save target if present
          }
          if (woundMatch) {
            action.wound_roll = parseInt(woundMatch[2]);  // The actual roll
          }
          if (saveMatch) {
            action.save_target = parseInt(saveMatch[1]);  // The target number
            action.save_roll = parseInt(saveMatch[2]);  // The actual roll
          }

          currentEpisode.actions.push(action);

          if (damage > 0 && currentEpisode.units[targetId]) {
            currentEpisode.units[targetId].HP_CUR -= damage;
            if (currentEpisode.units[targetId].HP_CUR < 0) {
              currentEpisode.units[targetId].HP_CUR = 0;
            }
          }
        }
      } else if (actionType === 'WAIT') {
        currentEpisode.actions.push({
          type: 'shoot_wait',
          timestamp,
          turn,
          player,
          unit_id: shooterId,
          pos: { col: shooterCol, row: shooterRow }
        });
      }
      continue;
    }
  }

  // Add last episode
  if (currentEpisode && currentEpisode.actions.length > 0) {
    episodes.push(currentEpisode);
  }

  // Convert to replay format
  const replayEpisodes = episodes.map(episode => {
    // Build initial units with starting positions (episode.units has been mutated by move parsing)
    const initialUnits = [];
    for (const uid in episode.units) {
      const unit = episode.units[uid];
      const startPos = episode.initial_positions[uid];
      initialUnits.push({
        ...unit,
        col: startPos.col,
        row: startPos.row,
        HP_CUR: 2,
        HP_MAX: 2
      });
    }
    console.log(`Episode ${episode.episode_num}: ${initialUnits.length} units`, initialUnits.map((u: any) => ({ id: u.id, player: u.player, pos: `(${u.col},${u.row})` })));

    const initialState = {
      units: initialUnits,
      currentTurn: 1,
      currentPlayer: 0,
      phase: 'move'
    };

    // Build states
    const states: any[] = [];
    const currentUnits: any = {};
    // Initialize currentUnits with initial positions (episode.units has been mutated)
    for (const unit of initialUnits) {
      currentUnits[unit.id] = { ...unit };
    }

    for (const action of episode.actions) {
      if (action.type === 'move' && action.unit_id) {
        const unitId = action.unit_id;
        if (currentUnits[unitId] && action.to) {
          currentUnits[unitId].col = action.to.col;
          currentUnits[unitId].row = action.to.row;
        }
      } else if (action.type === 'shoot' && action.target_id && action.damage) {
        const targetId = action.target_id;
        if (currentUnits[targetId]) {
          currentUnits[targetId].HP_CUR -= action.damage;
          if (currentUnits[targetId].HP_CUR < 0) {
            currentUnits[targetId].HP_CUR = 0;
          }
        }
      }

      states.push({
        units: Object.values(currentUnits).map(u => ({ ...u })),
        currentTurn: 1,
        currentPlayer: action.player,
        phase: action.type.includes('move') ? 'move' : action.type.includes('shoot') ? 'shoot' : 'move',
        action
      });
    }

    return {
      episode_num: episode.episode_num,
      scenario: episode.scenario,
      initial_state: initialState,
      actions: episode.actions,
      states: states,
      total_actions: episode.actions.length,
      final_result: episode.final_result
    };
  });

  return {
    total_episodes: replayEpisodes.length,
    episodes: replayEpisodes
  };
}
