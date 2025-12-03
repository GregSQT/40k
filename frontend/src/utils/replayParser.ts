// frontend/src/utils/replayParser.ts
// Parse train_step.log into replay format on the frontend
// VERSION: 2025-11-17-11-35 - Dead unit tracking implementation

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

export function parse_log_file_from_text(text: string) {
  const lines = text.split('\n');
  const episodes: any[] = [];
  let currentEpisode: any = null;

  for (const line of lines) {
    const trimmed = line.trim();

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
        scenario: 'Unknown',
        bot_name: 'Unknown',
        walls: [],
        objectives: []
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

    // Bot name (opponent)
    const botMatch = trimmed.match(/(?:Bot|Opponent|P1_Agent): (.+)/);
    if (botMatch) {
      currentEpisode.bot_name = botMatch[1];
      continue;
    }

    // Walls/obstacles
    const wallsMatch = trimmed.match(/Walls: (.+)/);
    if (wallsMatch) {
      const wallsStr = wallsMatch[1];
      if (wallsStr !== 'none') {
        // Parse format: (col,row);(col,row);...
        const wallCoords = wallsStr.split(';');
        for (const coord of wallCoords) {
          const match = coord.match(/\((\d+),(\d+)\)/);
          if (match) {
            currentEpisode.walls.push({
              col: parseInt(match[1]),
              row: parseInt(match[2])
            });
          }
        }
      }
      continue;
    }

    // Objectives - format: name:(col,row);(col,row)|name2:(col,row);...
    const objectivesMatch = trimmed.match(/Objectives: (.+)/);
    if (objectivesMatch) {
      const objectivesStr = objectivesMatch[1];
      if (objectivesStr !== 'none') {
        // Parse format: name:(col,row);(col,row)|name2:(col,row);...
        const objectiveGroups = objectivesStr.split('|');
        for (const group of objectiveGroups) {
          const [name, hexesStr] = group.split(':');
          if (name && hexesStr) {
            const hexes: { col: number; row: number }[] = [];
            const hexCoords = hexesStr.split(';');
            for (const coord of hexCoords) {
              const match = coord.match(/\((\d+),(\d+)\)/);
              if (match) {
                hexes.push({
                  col: parseInt(match[1]),
                  row: parseInt(match[2])
                });
              }
            }
            currentEpisode.objectives.push({ name, hexes });
          }
        }
      }
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

      // Determine HP based on unit type
      const unitHP = (unitType === 'Termagant' || unitType === 'Hormagaunt' || unitType === 'Genestealer') ? 1 : 2;

      currentEpisode.units[unitId] = {
        id: unitId,
        type: unitType,
        player: player,
        col: col,
        row: row,
        HP_CUR: unitHP,
        HP_MAX: unitHP,
        // Add placeholder stats - will be filled from gameConfig later
        MOVE: 0,
        T: 0,
        ARMOR_SAVE: 0,
        RNG_RNG: 0,
        RNG_NB: 0,
        RNG_ATK: 0,
        RNG_STR: 0,
        RNG_AP: 0,
        RNG_DMG: 0,
        MEL_NB: 0,
        MEL_ATK: 0,
        MEL_STR: 0,
        MEL_AP: 0,
        MEL_DMG: 0
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
      // Removed verbose logging
      // console.log('Matched SHOOT line:', trimmed);
      const timestamp = shootMatch[1];
      const turn = shootMatch[2];
      const player = parseInt(shootMatch[3]);
      const shooterId = parseInt(shootMatch[4]);
      const shooterCol = parseInt(shootMatch[5]);
      const shooterRow = parseInt(shootMatch[6]);
      const actionType = shootMatch[7];
      // console.log('Action type:', actionType);

      if (actionType === 'SHOT') {
        const targetMatch = trimmed.match(/SHOT at unit (\d+)/);
        const damageMatch = trimmed.match(/Dmg:(\d+)HP/);

        // Try to extract detailed combat rolls from format: Hit:3+:6(HIT) Wound:4+:5(SUCCESS) Save:3+:2(FAILED)
        const hitMatch = trimmed.match(/Hit:(\d+)\+:(\d+)/);
        const woundMatch = trimmed.match(/Wound:(\d+)\+:(\d+)/);
        const saveMatch = trimmed.match(/Save:(\d+)\+:(\d+)/);
        // Extract reward from format: [R:+53.2] or [R:-10.0]
        const rewardMatch = trimmed.match(/\[R:([+-]?\d+\.?\d*)\]/);

        // Removed verbose logging
        // console.log('Parsing shoot line:', trimmed);
        // if (hitMatch) console.log('Found Hit - target:', hitMatch[1], 'roll:', hitMatch[2]);

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
          // Add reward if available
          if (rewardMatch) {
            action.reward = parseFloat(rewardMatch[1]);
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

    // Parse CHARGE actions
    // Format: [timestamp] T1 P0 CHARGE : Unit 2(9, 6) CHARGED unit 8 from (7, 13) to (9, 6) [SUCCESS]
    // Or: [timestamp] T1 P0 CHARGE : Unit 1(19, 15) WAIT [SUCCESS]
    // Or: [timestamp] T1 P0 CHARGE : Unit 2(23, 6) FAILED charge to unit 7 [Roll:5] [FAILED: roll_too_low] [FAILED]
    const chargeMatch = trimmed.match(/\[([^\]]+)\] (T\d+) P(\d+) CHARGE : Unit (\d+)\((\d+), (\d+)\) (CHARGED|WAIT|FAILED charge)/);
    if (chargeMatch) {
      const timestamp = chargeMatch[1];
      const turn = chargeMatch[2];
      const player = parseInt(chargeMatch[3]);
      const unitId = parseInt(chargeMatch[4]);
      const unitCol = parseInt(chargeMatch[5]);
      const unitRow = parseInt(chargeMatch[6]);
      const actionType = chargeMatch[7];

      if (actionType === 'CHARGED') {
        // Parse target unit and positions
        const targetMatch = trimmed.match(/CHARGED unit (\d+)/);
        const fromMatch = trimmed.match(/from \((\d+), (\d+)\)/);
        const toMatch = trimmed.match(/to \((\d+), (\d+)\)/);
        // Parse actual charge roll (2d6) if available: [Roll:X]
        const rollMatch = trimmed.match(/\[Roll:(\d+)\]/);

        if (targetMatch && fromMatch && toMatch) {
          const targetId = parseInt(targetMatch[1]);
          const fromCol = parseInt(fromMatch[1]);
          const fromRow = parseInt(fromMatch[2]);
          const toCol = parseInt(toMatch[1]);
          const toRow = parseInt(toMatch[2]);

          // Use actual roll if available, otherwise calculate distance as fallback
          let chargeRoll: number;
          if (rollMatch) {
            chargeRoll = parseInt(rollMatch[1]);
          } else {
            // Fallback: Calculate charge distance (for old logs without roll)
            const offsetToCube = (col: number, row: number) => {
              const x = col;
              const z = row - ((col - (col & 1)) >> 1);
              const y = -x - z;
              return { x, y, z };
            };
            const fromCube = offsetToCube(fromCol, fromRow);
            const toCube = offsetToCube(toCol, toRow);
            chargeRoll = Math.max(
              Math.abs(fromCube.x - toCube.x),
              Math.abs(fromCube.y - toCube.y),
              Math.abs(fromCube.z - toCube.z)
            );
          }

          currentEpisode.actions.push({
            type: 'charge',
            timestamp,
            turn,
            player,
            unit_id: unitId,
            target_id: targetId,
            from: { col: fromCol, row: fromRow },
            to: { col: toCol, row: toRow },
            charge_roll: chargeRoll,  // The actual 2d6 roll
            charge_success: true
          });

          // Update unit position after charge
          if (currentEpisode.units[unitId]) {
            currentEpisode.units[unitId].col = toCol;
            currentEpisode.units[unitId].row = toRow;
          }
        }
      } else if (actionType === 'WAIT') {
        // WAIT means the charge roll was too low or unit chose not to charge
        // We don't know the exact roll, but we can indicate it failed
        currentEpisode.actions.push({
          type: 'charge_wait',
          timestamp,
          turn,
          player,
          unit_id: unitId,
          pos: { col: unitCol, row: unitRow },
          charge_roll: 0,  // Unknown roll, but too low
          charge_success: false
        });
      } else if (actionType === 'FAILED charge') {
        // FAILED charge - parse target and roll
        const targetMatch = trimmed.match(/FAILED charge to unit (\d+)/);
        const rollMatch = trimmed.match(/\[Roll:(\d+)\]/);
        const failedReasonMatch = trimmed.match(/\[FAILED: (.+?)\]/);
        
        const targetId = targetMatch ? parseInt(targetMatch[1]) : undefined;
        const chargeRoll = rollMatch ? parseInt(rollMatch[1]) : 0;
        const failedReason = failedReasonMatch ? failedReasonMatch[1] : 'roll_too_low';
        
        currentEpisode.actions.push({
          type: 'charge_fail',
          timestamp,
          turn,
          player,
          unit_id: unitId,
          target_id: targetId,
          pos: { col: unitCol, row: unitRow },
          charge_roll: chargeRoll,
          charge_success: false,
          charge_failed_reason: failedReason
        });
      }
      continue;
    }

    // Parse FIGHT actions
    // Format: [timestamp] T1 P0 FIGHT : Unit 2(9, 6) FOUGHT unit 8 - Hit:3+:2(MISS) [SUCCESS]
    const fightMatch = trimmed.match(/\[([^\]]+)\] (T\d+) P(\d+) FIGHT : Unit (\d+)\((\d+), (\d+)\) FOUGHT unit (\d+)/);
    if (fightMatch) {
      const timestamp = fightMatch[1];
      const turn = fightMatch[2];
      const player = parseInt(fightMatch[3]);
      const attackerId = parseInt(fightMatch[4]);
      const attackerCol = parseInt(fightMatch[5]);
      const attackerRow = parseInt(fightMatch[6]);
      const targetId = parseInt(fightMatch[7]);

      // Parse combat details - Hit:3+:2(MISS/HIT) Wound:4+:5(SUCCESS/FAIL) Save:3+:2(FAIL) Dmg:1HP
      const hitMatch = trimmed.match(/Hit:(\d+)\+:(\d+)\((HIT|MISS)\)/);
      const woundMatch = trimmed.match(/Wound:(\d+)\+:(\d+)\((SUCCESS|WOUND|FAIL)\)/);
      const saveMatch = trimmed.match(/Save:(\d+)\+:(\d+)\((FAIL|SAVED?)\)/);
      const dmgMatch = trimmed.match(/Dmg:(\d+)HP/);

      const action: any = {
        type: 'fight',
        timestamp,
        turn,
        player,
        attacker_id: attackerId,
        attacker_pos: { col: attackerCol, row: attackerRow },
        target_id: targetId,
        damage: 0  // Will be calculated below based on combat results
      };

      // Add detailed combat rolls if available
      if (hitMatch) {
        action.hit_target = parseInt(hitMatch[1]);
        action.hit_roll = parseInt(hitMatch[2]);
        action.hit_result = hitMatch[3];
      }
      if (woundMatch) {
        action.wound_target = parseInt(woundMatch[1]);
        action.wound_roll = parseInt(woundMatch[2]);
        action.wound_result = woundMatch[3];
      }
      if (saveMatch) {
        action.save_target = parseInt(saveMatch[1]);
        action.save_roll = parseInt(saveMatch[2]);
        action.save_result = saveMatch[3];
      }

      // FIGHT logs don't have Dmg:XHP format - infer damage from combat results
      // Damage is dealt if: hit succeeded AND wound succeeded AND save failed
      if (dmgMatch) {
        // If Dmg:XHP is present, use it (future-proofing)
        action.damage = parseInt(dmgMatch[1]);
      } else if (action.hit_result === 'HIT' &&
                 (action.wound_result === 'WOUND' || action.wound_result === 'SUCCESS') &&
                 action.save_result === 'FAIL') {
        // Infer damage: melee attacks typically deal 1 damage
        // Note: This assumes CC_DMG=1, which is standard for most units
        action.damage = 1;
      }

      currentEpisode.actions.push(action);

      // Apply damage to target unit
      const damage = action.damage || 0;
      if (damage > 0 && currentEpisode.units[targetId]) {
        currentEpisode.units[targetId].HP_CUR -= damage;
        if (currentEpisode.units[targetId].HP_CUR < 0) {
          currentEpisode.units[targetId].HP_CUR = 0;
        }
      }
      continue;
    }

    // Parse EPISODE END line
    const episodeEndMatch = trimmed.match(/EPISODE END: Winner=(-?\d+)/);
    if (episodeEndMatch) {
      const winner = parseInt(episodeEndMatch[1]);
      if (currentEpisode) {
        currentEpisode.final_result = winner === -1 ? 'Draw' : winner === 0 ? 'Agent Win' : 'Bot Win';
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
      // Use unit's actual HP_MAX (set based on unit type during parsing)
      const unitHP = unit.HP_MAX || 2;
      initialUnits.push({
        ...unit,
        col: startPos.col,
        row: startPos.row,
        HP_CUR: unitHP,
        HP_MAX: unitHP
      });
    }
    // Removed verbose episode units logging
    // console.log(`Episode ${episode.episode_num}: ${initialUnits.length} units`, initialUnits.map((u: any) => ({ id: u.id, player: u.player, pos: `(${u.col},${u.row})` })));

    const initialState = {
      units: initialUnits,
      walls: episode.walls || [],
      objectives: episode.objectives || [],
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

    // Track units to remove after they've been shown as dead
    const unitsToRemove = new Set<number>();

    for (const action of episode.actions) {
      // Clear isJustKilled flag and remove units that were killed in the previous action
      unitsToRemove.forEach(unitId => {
        if (currentUnits[unitId]) {
          // First clear the flag so the unit shows normally (if it somehow survived)
          delete currentUnits[unitId].isJustKilled;
          // Then remove the unit since it's dead
          delete currentUnits[unitId];
        }
      });
      unitsToRemove.clear();

      if (action.type === 'move' && action.unit_id) {
        const unitId = action.unit_id;
        if (currentUnits[unitId] && action.to) {
          currentUnits[unitId].col = action.to.col;
          currentUnits[unitId].row = action.to.row;
        }
      } else if (action.type === 'charge' && action.unit_id) {
        // Handle charge actions - update unit position
        const unitId = action.unit_id;
        if (currentUnits[unitId] && action.to) {
          currentUnits[unitId].col = action.to.col;
          currentUnits[unitId].row = action.to.row;
        }
      } else if (action.type === 'shoot' && action.target_id !== undefined) {
        // Handle shoot actions (even if damage is 0)
        const targetId = action.target_id;
        const damage = action.damage || 0;

        if (currentUnits[targetId]) {
          const wasAlive = currentUnits[targetId].HP_CUR > 0;

          // Apply damage
          if (damage > 0) {
            currentUnits[targetId].HP_CUR -= damage;
            if (currentUnits[targetId].HP_CUR < 0) {
              currentUnits[targetId].HP_CUR = 0;
            }
          }

          const hpAfter = currentUnits[targetId].HP_CUR;

          // Check if unit was just killed
          if (hpAfter <= 0 && wasAlive) {
            currentUnits[targetId].isJustKilled = true;
            unitsToRemove.add(targetId);
          }
        }
      } else if (action.type === 'fight' && action.target_id !== undefined) {
        // Handle fight actions - same damage logic as shoot
        const targetId = action.target_id;
        const damage = action.damage || 0;

        if (currentUnits[targetId]) {
          const wasAlive = currentUnits[targetId].HP_CUR > 0;

          // Apply damage
          if (damage > 0) {
            currentUnits[targetId].HP_CUR -= damage;
            if (currentUnits[targetId].HP_CUR < 0) {
              currentUnits[targetId].HP_CUR = 0;
            }
          }

          const hpAfter = currentUnits[targetId].HP_CUR;

          // Check if unit was just killed
          if (hpAfter <= 0 && wasAlive) {
            currentUnits[targetId].isJustKilled = true;
            unitsToRemove.add(targetId);
          }
        }
      }

      // Determine phase from action type
      let phase = 'move';
      if (action.type.includes('move')) {
        phase = 'move';
      } else if (action.type.includes('shoot')) {
        phase = 'shoot';
      } else if (action.type.includes('charge')) {
        phase = 'charge';
      } else if (action.type.includes('fight')) {
        phase = 'fight';
      }

      // Create state with current units (including just-killed units with flag preserved)
      const stateUnits = Object.values(currentUnits).map(u => {
        const unitCopy = { ...u };
        // Preserve isJustKilled flag in the copy
        if ((u as any).isJustKilled) {
          (unitCopy as any).isJustKilled = true;
        }
        return unitCopy;
      });

      states.push({
        units: stateUnits,
        walls: episode.walls || [],
        objectives: episode.objectives || [],
        currentTurn: 1,
        currentPlayer: action.player,
        phase,
        action
      });
    }

    return {
      episode_num: episode.episode_num,
      scenario: episode.scenario,
      bot_name: episode.bot_name || 'Unknown',
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
