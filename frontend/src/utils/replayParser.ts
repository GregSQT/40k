// frontend/src/utils/replayParser.ts
// Parse train_step.log into replay format on the frontend
// VERSION: 2025-11-17-11-35 - Dead unit tracking implementation

interface ReplayAction {
  type: string;
  timestamp: string;
  turn: string;
  player: number;
  log_message?: string;
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
  hit_target?: number;
  hit_target_base?: number;
  wound_roll?: number;
  wound_target?: number;
  save_roll?: number;
  save_target?: number;
  save_skipped?: boolean;
  save_skip_reason?: string;
  devastating_wounds_applied?: boolean;
  rapid_fire_bonus_shot?: boolean;
  rapid_fire_rule_value?: number;
  heavy_applied?: boolean;
  hazardous_test_roll?: number;
  hazardous_triggered?: boolean;
  hazardous_self_died?: boolean;
  hazardous_mortal_wounds?: number;
  reward?: number;
  move_mode?: string;
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
  charge_failed_reason?: string;
  // Advance action fields
  advance_roll?: number;
  // Rule choice fields
  selected_rule_name?: string;
}

interface PrimaryObjectiveRule {
  id: string;
  name?: string;
  identifier?: string;
  description?: string;
  scoring: {
    start_turn: number;
    max_points_per_turn: number;
    rules: Array<{ id: string; points: number; condition: string }>;
  };
  timing: {
    default_phase: string;
    round5_second_player_phase: string;
  };
  control: {
    method: string;
    control_method: string;
    tie_behavior: string;
  };
}

interface ReplayRules {
  primary_objective: PrimaryObjectiveRule | PrimaryObjectiveRule[] | null;
}

const validateReplayRules = (rules: ReplayRules, episodeNumber: number): void => {
  const primaryObjective = rules.primary_objective;
  const primaryObjectiveConfig = Array.isArray(primaryObjective)
    ? (() => {
        if (primaryObjective.length !== 1) {
          throw new Error(
            `Replay rules primary_objective must contain exactly one config (episode ${episodeNumber})`
          );
        }
        return primaryObjective[0];
      })()
    : primaryObjective;

  if (!primaryObjectiveConfig) {
    throw new Error(`Replay rules primary_objective is missing (episode ${episodeNumber})`);
  }

  if (!primaryObjectiveConfig.control || !primaryObjectiveConfig.control.control_method) {
    throw new Error(
      `Replay rules primary_objective.control.control_method is missing (episode ${episodeNumber}). ` +
        `Regenerate step.log after updating primary objective config.`
    );
  }
};

interface ReplayGameState {
  [key: string]: unknown;
  episode_steps?: number;
  board_cols?: number;
  board_rows?: number;
  walls?: Array<{ col: number; row: number }>;
  objectives?: Array<{ name: string; hexes: Array<{ col: number; row: number }> }>;
  rules?: ReplayRules;
}

// Temporary interface for parsing (has additional properties)
interface ReplayEpisodeDuringParsing {
  episode_num: number;
  scenario: string;
  bot_name: string;
  win_method?: string | null;
  actions: ReplayAction[];
  units: Record<
    number,
    {
      id: number;
      player: number;
      col: number;
      row: number;
      HP_CUR: number;
      HP_MAX: number;
      type?: string;
      [key: string]: unknown;
    }
  >;
  initial_positions: Record<number, { col: number; row: number }>;
  first_seen_positions: Record<number, { col: number; row: number }>;
  deployed_unit_ids: Set<number>;
  walls: Array<{ col: number; row: number }>;
  objectives: Array<{ name: string; hexes: Array<{ col: number; row: number }> }>;
  rules?: ReplayRules;
  final_result: string | null;
}

// Final interface for parsed data
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

export function parse_log_file_from_text(text: string): ReplayData {
  const lines = text.split("\n");
  const extractLogMessage = (line: string): string => {
    const entryMatch = line.match(
      /^\[[^\]]+\]\s(?:E\d+\s+)?T\d+\sP\d+\s[A-Z_]+\s:\s(.+?)\s\[(?:SUCCESS|FAILED)\]$/
    );
    if (!entryMatch) {
      return line.trim();
    }
    return entryMatch[1].replace(/\s?\[R:[+-]?\d+\.?\d*\]$/, "").trim();
  };
  const parsePoolList = (value: string, label: string): number[] => {
    if (value === "") {
      return [];
    }
    const rawIds = value.split(",");
    const parsedIds = rawIds.map((raw) => {
      const parsed = parseInt(raw, 10);
      if (Number.isNaN(parsed)) {
        throw new Error(`Invalid ${label} pool id value in step.log: "${raw}"`);
      }
      return parsed;
    });
    return parsedIds;
  };
  const episodes: ReplayEpisodeDuringParsing[] = [];
  let currentEpisode: ReplayEpisodeDuringParsing | null = null;
  const syncKnownUnitPosition = (
    episode: ReplayEpisodeDuringParsing,
    unitId: number,
    col: number,
    row: number
  ): void => {
    if (col < 0 || row < 0) {
      return;
    }
    if (!episode.first_seen_positions[unitId]) {
      episode.first_seen_positions[unitId] = { col, row };
    }
    if (episode.units[unitId]) {
      episode.units[unitId].col = col;
      episode.units[unitId].row = row;
    }
  };

  for (const line of lines) {
    const trimmed = line.trim();

    // Episode start - matches both "=== EPISODE START ===" and "=== EPISODE 1 START ==="
    if (trimmed.includes("=== EPISODE") && trimmed.includes("START ===")) {
      if (currentEpisode) {
        episodes.push(currentEpisode);
      }
      currentEpisode = {
        episode_num: episodes.length + 1,
        actions: [],
        units: {},
        initial_positions: {},
        first_seen_positions: {},
        deployed_unit_ids: new Set<number>(),
        final_result: null,
        win_method: null,
        scenario: "Unknown",
        bot_name: "Unknown",
        walls: [],
        objectives: [],
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
      if (wallsStr !== "none") {
        // Parse format: (col,row);(col,row);...
        const wallCoords = wallsStr.split(";");
        for (const coord of wallCoords) {
          const match = coord.match(/\((\d+),(\d+)\)/);
          if (match) {
            currentEpisode.walls.push({
              col: parseInt(match[1], 10),
              row: parseInt(match[2], 10),
            });
          }
        }
      }
      continue;
    }

    const rulesMatch = trimmed.match(/Rules: (.+)/);
    if (rulesMatch) {
      const rulesStr = rulesMatch[1];
      try {
        currentEpisode.rules = JSON.parse(rulesStr);
        if (!currentEpisode.rules) {
          throw new Error("Replay rules parsed to an empty value");
        }
        validateReplayRules(currentEpisode.rules, currentEpisode.episode_num);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        throw new Error(`Invalid Rules JSON in step.log: ${message}`);
      }
      continue;
    }

    // Objectives - format: name:(col,row);(col,row)|name2:(col,row);...
    const objectivesMatch = trimmed.match(/Objectives: (.+)/);
    if (objectivesMatch) {
      const objectivesStr = objectivesMatch[1];
      if (objectivesStr !== "none") {
        // Parse format: name:(col,row);(col,row)|name2:(col,row);...
        const objectiveGroups = objectivesStr.split("|");
        for (const group of objectiveGroups) {
          const [name, hexesStr] = group.split(":");
          if (name && hexesStr) {
            const hexes: { col: number; row: number }[] = [];
            const hexCoords = hexesStr.split(";");
            for (const coord of hexCoords) {
              const match = coord.match(/\((\d+),(\d+)\)/);
              if (match) {
                hexes.push({
                  col: parseInt(match[1], 10),
                  row: parseInt(match[2], 10),
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
    const unitStart = trimmed.match(
      /Unit (\d+) \((.+?)\)(?: \[[^\]]+\])? P(\d+): Starting position \((-?\d+),\s*(-?\d+)\),\s*HP_MAX=(\d+)/
    );
    if (unitStart) {
      const unitId = parseInt(unitStart[1], 10);
      const unitType = unitStart[2];
      const player = parseInt(unitStart[3], 10);
      const col = parseInt(unitStart[4], 10);
      const row = parseInt(unitStart[5], 10);
      const unitHP = parseInt(unitStart[6], 10);
      if (Number.isNaN(unitHP) || unitHP <= 0) {
        throw new Error(`Invalid HP_MAX in step.log unit start line: ${trimmed}`);
      }

      currentEpisode.units[unitId] = {
        id: unitId,
        type: unitType,
        player: player,
        col: col,
        row: row,
        HP_CUR: unitHP,
        HP_MAX: unitHP,
        // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Replace single weapon fields with arrays
        // Add placeholder stats - will be filled from gameConfig later
        MOVE: 0,
        T: 0,
        ARMOR_SAVE: 0,
        RNG_WEAPONS: [],
        CC_WEAPONS: [],
      };
      currentEpisode.initial_positions[unitId] = { col, row };
      continue;
    }

    // Parse DEPLOYMENT actions
    const deployMatch = trimmed.match(
      /\[([^\]]+)\] (?:E\d+\s+)?(T\d+) P(\d+) DEPLOYMENT : Unit (\d+)\((-?\d+),(-?\d+)\) DEPLOYED from \((-?\d+),(-?\d+)\) to \((-?\d+),(-?\d+)\)/
    );
    if (deployMatch) {
      const timestamp = deployMatch[1];
      const turn = deployMatch[2];
      const player = parseInt(deployMatch[3], 10);
      const unitId = parseInt(deployMatch[4], 10);
      const fromCol = parseInt(deployMatch[7], 10);
      const fromRow = parseInt(deployMatch[8], 10);
      const toCol = parseInt(deployMatch[9], 10);
      const toRow = parseInt(deployMatch[10], 10);

      currentEpisode.actions.push({
        type: "deploy",
        timestamp,
        turn,
        player,
        unit_id: unitId,
        from: { col: fromCol, row: fromRow },
        to: { col: toCol, row: toRow },
      });

      currentEpisode.deployed_unit_ids.add(unitId);
      syncKnownUnitPosition(currentEpisode, unitId, toCol, toRow);
      continue;
    }

    // Parse MOVE actions
    const moveMatch = trimmed.match(
      /\[([^\]]+)\] (?:E\d+\s+)?(T\d+) P(\d+) MOVE : Unit (\d+)\((\d+),(\d+)\) (MOVED(?: \[[^\]]+\])?(?: \[FLY\])?|REACTIVE MOVED|WAIT|FLED)/
    );
    if (moveMatch) {
      const timestamp = moveMatch[1];
      const turn = moveMatch[2];
      const player = parseInt(moveMatch[3], 10);
      const unitId = parseInt(moveMatch[4], 10);
      const endCol = parseInt(moveMatch[5], 10);
      const endRow = parseInt(moveMatch[6], 10);
      const actionType = moveMatch[7];
      const isFlyMove = actionType.includes("[FLY]");
      const isReactiveMove =
        actionType.startsWith("REACTIVE MOVED") ||
        (actionType.startsWith("MOVED [") && trimmed.includes(" - trigger: Unit "));
      syncKnownUnitPosition(currentEpisode, unitId, endCol, endRow);

      if (
        actionType === "MOVED" ||
        actionType.startsWith("MOVED [") ||
        actionType === "FLED" ||
        actionType === "REACTIVE MOVED"
      ) {
        const fromMatch = trimmed.match(/from \((\d+),(\d+)\)/);
        let fromCol = endCol;
        let fromRow = endRow;
        if (fromMatch) {
          fromCol = parseInt(fromMatch[1], 10);
          fromRow = parseInt(fromMatch[2], 10);
        } else if (currentEpisode.units[unitId]) {
          fromCol = currentEpisode.units[unitId].col;
          fromRow = currentEpisode.units[unitId].row;
        }

        currentEpisode.actions.push({
          type: isReactiveMove ? "reactive_move" : "move",
          timestamp,
          turn,
          player,
          unit_id: unitId,
          from: { col: fromCol, row: fromRow },
          to: { col: endCol, row: endRow },
          log_message: extractLogMessage(trimmed),
          ...(isFlyMove ? { move_mode: "fly" } : {}),
        });

        if (currentEpisode.units[unitId]) {
          currentEpisode.units[unitId].col = endCol;
          currentEpisode.units[unitId].row = endRow;
        }
      } else if (actionType === "WAIT") {
        currentEpisode.actions.push({
          type: "move_wait",
          timestamp,
          turn,
          player,
          log_message: extractLogMessage(trimmed),
          unit_id: unitId,
          pos: { col: endCol, row: endRow },
        });
      }
      continue;
    }

    const hazardousResultMatch = trimmed.match(
      /\[([^\]]+)\]\s(?:E\d+\s+)?(T\d+)\sP(\d+)\sSHOOT\s:\sUnit\s(\d+)\((\d+),(\d+)\)\s(SUFFERS\s3\sMortal\sWounds\s\[HAZARDOUS\]|was\sDESTROYED\s\[HAZARDOUS\])/
    );
    if (hazardousResultMatch) {
      const timestamp = hazardousResultMatch[1];
      const turn = hazardousResultMatch[2];
      const player = parseInt(hazardousResultMatch[3], 10);
      const unitId = parseInt(hazardousResultMatch[4], 10);
      const unitCol = parseInt(hazardousResultMatch[5], 10);
      const unitRow = parseInt(hazardousResultMatch[6], 10);
      const outcome = hazardousResultMatch[7];
      currentEpisode.actions.push({
        type: "hazardous",
        timestamp,
        turn,
        player,
        unit_id: unitId,
        pos: { col: unitCol, row: unitRow },
        hazardous_triggered: true,
        hazardous_self_died: outcome.includes("was DESTROYED"),
        hazardous_mortal_wounds: 3,
        log_message: extractLogMessage(trimmed),
      });
      continue;
    }

    // Parse SHOOT actions
    const shootMatch = trimmed.match(
      /\[([^\]]+)\] (?:E\d+\s+)?(T\d+) P(\d+) SHOOT : Unit (\d+)\((\d+),(\d+)\) ((?:SHOT(?: \[[^\]]+\])*(?: \[RAPID(?: |_)?FIRE:[^\]]+\])? at Unit)|WAIT|ADVANCED)/
    );
    if (shootMatch) {
      // Removed verbose logging
      // console.log('Matched SHOOT line:', trimmed);
      const timestamp = shootMatch[1];
      const turn = shootMatch[2];
      const player = parseInt(shootMatch[3], 10);
      const shooterId = parseInt(shootMatch[4], 10);
      const shooterCol = parseInt(shootMatch[5], 10);
      const shooterRow = parseInt(shootMatch[6], 10);
      const actionType = shootMatch[7];
      syncKnownUnitPosition(currentEpisode, shooterId, shooterCol, shooterRow);
      // console.log('Action type:', actionType);

      if (actionType === "ADVANCED") {
        // Parse advance action: Unit X(col, row) ADVANCED from (col1, row1) to (col2, row2) (Roll: X)
        const fromMatch = trimmed.match(/from \((\d+),(\d+)\)/);
        const toMatch = trimmed.match(/to \((\d+),(\d+)\)/);
        // Match both [Roll:X] and (Roll: X) formats
        const rollMatch = trimmed.match(/(?:\[Roll:|\(Roll:)\s*(\d+)\)?/);
        const rewardMatch = trimmed.match(/\[R:([+-]?\d+\.?\d*)\]/);

        if (fromMatch && toMatch) {
          const fromCol = parseInt(fromMatch[1], 10);
          const fromRow = parseInt(fromMatch[2], 10);
          const toCol = parseInt(toMatch[1], 10);
          const toRow = parseInt(toMatch[2], 10);
          const advanceRoll = rollMatch ? parseInt(rollMatch[1], 10) : undefined;

          const action: ReplayAction = {
            type: "advance",
            timestamp,
            turn,
            player,
            log_message: extractLogMessage(trimmed),
            unit_id: shooterId,
            from: { col: fromCol, row: fromRow },
            to: { col: toCol, row: toRow },
          };

          if (advanceRoll !== undefined) {
            action.advance_roll = advanceRoll;
          }
          if (rewardMatch) {
            action.reward = parseFloat(rewardMatch[1]);
          }

          currentEpisode.actions.push(action);

          // Update unit position immediately (like move actions)
          if (currentEpisode.units[shooterId]) {
            currentEpisode.units[shooterId].col = toCol;
            currentEpisode.units[shooterId].row = toRow;
          }
        }
      } else if (actionType.startsWith("SHOT")) {
        const targetMatch = trimmed.match(/SHOT(?: \[[^\]]+\])*(?: \[RAPID(?: |_)?FIRE:[^\]]+\])? at Unit (\d+)\((\d+),(\d+)\)/);
        const damageMatch = trimmed.match(/Dmg:(\d+)HP/);

        // Try to extract detailed combat rolls from format: Hit:3+:6(HIT) Wound:4+:5(SUCCESS) Save:3+:2(FAILED)
        const hitMatch = trimmed.match(/Hit:(\d+)\+(?:->(\d+)\+)?:(\d+)/);
        const woundMatch = trimmed.match(/Wound:(\d+)\+:(\d+)/);
        const saveMatch = trimmed.match(/Save:(\d+)\+:(\d+)/);
        const saveSkippedMatch = trimmed.match(/Save:SKIPPED(?:\(([^)]+)\))?/);
        const rapidFireMatch = trimmed.match(/\[RAPID(?: |_)?FIRE:(\d+)\]/);
        const devastatingWoundsMatch = trimmed.match(/\[DEVASTATING WOUNDS\]/);
        const heavyMatch = trimmed.match(/\[HEAVY\]/);
        const hazardousRollMatch = trimmed.match(/\[HAZARDOUS\]\s+Roll:(\d+)/i);
        // Extract reward from format: [R:+53.2] or [R:-10.0]
        const rewardMatch = trimmed.match(/\[R:([+-]?\d+\.?\d*)\]/);
        // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Extract weapon name from format: with [weapon_name]
        const weaponMatch = trimmed.match(/with \[([^\]]+)\]/);

        // Removed verbose logging
        // console.log('Parsing shoot line:', trimmed);
        // if (hitMatch) console.log('Found Hit - target:', hitMatch[1], 'roll:', hitMatch[2]);

        if (targetMatch) {
          const targetId = parseInt(targetMatch[1], 10);
          const targetCol = parseInt(targetMatch[2], 10);
          const targetRow = parseInt(targetMatch[3], 10);
          const damage = damageMatch ? parseInt(damageMatch[1], 10) : 0;

          const action: ReplayAction = {
            type: "shoot",
            timestamp,
            turn,
            player,
            log_message: extractLogMessage(trimmed),
            shooter_id: shooterId,
            shooter_pos: { col: shooterCol, row: shooterRow },
            target_id: targetId,
            target_pos: { col: targetCol, row: targetRow },
            damage,
          };

          // Add detailed rolls if available (format: Hit:3+:6 means target 3+, rolled 6)
          if (hitMatch) {
            if (hitMatch[2]) {
              action.hit_target_base = parseInt(hitMatch[1], 10);
              action.hit_target = parseInt(hitMatch[2], 10);
              action.hit_roll = parseInt(hitMatch[3], 10);
            } else {
              action.hit_target = parseInt(hitMatch[1], 10);
              action.hit_roll = parseInt(hitMatch[3], 10);
            }
          }
          if (woundMatch) {
            action.wound_target = parseInt(woundMatch[1], 10);
            action.wound_roll = parseInt(woundMatch[2], 10);
          }
          if (saveMatch) {
            action.save_target = parseInt(saveMatch[1], 10); // The target number
            action.save_roll = parseInt(saveMatch[2], 10); // The actual roll
          }
          if (saveSkippedMatch) {
            action.save_skipped = true;
            action.save_skip_reason = saveSkippedMatch[1];
            if (saveSkippedMatch[1] === "DEVASTATING_WOUNDS" || devastatingWoundsMatch) {
              action.devastating_wounds_applied = true;
            }
          }
          if (rapidFireMatch) {
            action.rapid_fire_bonus_shot = true;
            action.rapid_fire_rule_value = parseInt(rapidFireMatch[1], 10);
          }
          if (heavyMatch) {
            action.heavy_applied = true;
          }
          if (hazardousRollMatch) {
            action.hazardous_test_roll = parseInt(hazardousRollMatch[1], 10);
            action.hazardous_triggered = action.hazardous_test_roll === 1;
          }
          // Add reward if available
          if (rewardMatch) {
            action.reward = parseFloat(rewardMatch[1]);
          }
          // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Add weapon name if available
          if (weaponMatch) {
            action.weapon_name = weaponMatch[1];
          }

          currentEpisode.actions.push(action);
        }
      } else if (actionType === "WAIT") {
        currentEpisode.actions.push({
          type: "wait",
          timestamp,
          turn,
          player,
          log_message: extractLogMessage(trimmed),
          unit_id: shooterId,
          pos: { col: shooterCol, row: shooterRow },
        });
      }
      continue;
    }

    // Parse CHARGE actions
    // Format: [timestamp] T1 P0 CHARGE : Unit 2(9, 6) CHARGED Unit 8 from (7, 13) to (9, 6) [SUCCESS]
    // Or: [timestamp] T1 P0 CHARGE : Unit 1(19, 15) WAIT [SUCCESS]
    // Or: [timestamp] T1 P0 CHARGE : Unit 2(23,6) FAILED CHARGE to unit 7(21,10) [Roll: 5] [SUCCESS]
    // Or: [timestamp] T1 P0 CHARGE : Unit 2(23, 6) FAILED charge to unit 7 [Roll:5] [FAILED: roll_too_low] [FAILED] (legacy format)
    const chargeImpactMatch = trimmed.match(
      /\[([^\]]+)\] (?:E\d+\s+)?(T\d+) P(\d+) CHARGE : Unit (\d+)\((\d+),(\d+)\) IMPACTED \[([^\]]+)\] Unit (\d+)\((\d+),(\d+)\) - Hit:(\d+)\+:(\d+)\((HIT|FAIL)\)(?: Wound:AUTO Save:NONE\[MW\] Dmg:(\d+)HP)?/
    );
    if (chargeImpactMatch) {
      const timestamp = chargeImpactMatch[1];
      const turn = chargeImpactMatch[2];
      const player = parseInt(chargeImpactMatch[3], 10);
      const unitId = parseInt(chargeImpactMatch[4], 10);
      const unitCol = parseInt(chargeImpactMatch[5], 10);
      const unitRow = parseInt(chargeImpactMatch[6], 10);
      const targetId = parseInt(chargeImpactMatch[8], 10);
      const targetCol = parseInt(chargeImpactMatch[9], 10);
      const targetRow = parseInt(chargeImpactMatch[10], 10);
      syncKnownUnitPosition(currentEpisode, unitId, unitCol, unitRow);
      syncKnownUnitPosition(currentEpisode, targetId, targetCol, targetRow);
      currentEpisode.actions.push({
        type: "charge_impact",
        timestamp,
        turn,
        player,
        unit_id: unitId,
        target_id: targetId,
        damage: chargeImpactMatch[14] ? parseInt(chargeImpactMatch[14], 10) : 0,
        charge_roll: parseInt(chargeImpactMatch[12], 10),
        hit_target: parseInt(chargeImpactMatch[11], 10),
        hit_result: chargeImpactMatch[13],
        log_message: extractLogMessage(trimmed),
      });
      continue;
    }

    const chargeMatch = trimmed.match(
      /\[([^\]]+)\] (?:E\d+\s+)?(T\d+) P(\d+) CHARGE : Unit (\d+)\((\d+),(\d+)\) (CHARGED(?: \[[^\]]+\])? Unit|WAIT|FAILED CHARGE to unit|FAILED charge to unit)/
    );
    if (chargeMatch) {
      const timestamp = chargeMatch[1];
      const turn = chargeMatch[2];
      const player = parseInt(chargeMatch[3], 10);
      const unitId = parseInt(chargeMatch[4], 10);
      const unitCol = parseInt(chargeMatch[5], 10);
      const unitRow = parseInt(chargeMatch[6], 10);
      const actionType = chargeMatch[7];
      syncKnownUnitPosition(currentEpisode, unitId, unitCol, unitRow);

      if (actionType.startsWith("CHARGED")) {
        // Parse target unit and positions
        const targetMatch = trimmed.match(/CHARGED(?: \[[^\]]+\])? Unit (\d+)\((\d+),(\d+)\)/);
        const fromMatch = trimmed.match(/from \((\d+),(\d+)\)/);
        const toMatch = trimmed.match(/to \((\d+),(\d+)\)/);
        // Parse actual charge roll (2d6) if available: [Roll:X]
        const rollMatch = trimmed.match(/\[Roll:(\d+)\]/);

        if (targetMatch && fromMatch && toMatch) {
          const targetId = parseInt(targetMatch[1], 10);
          const targetCol = parseInt(targetMatch[2], 10);
          const targetRow = parseInt(targetMatch[3], 10);
          const fromCol = parseInt(fromMatch[1], 10);
          const fromRow = parseInt(fromMatch[2], 10);
          const toCol = parseInt(toMatch[1], 10);
          const toRow = parseInt(toMatch[2], 10);

          // Use actual roll if available, otherwise calculate distance as fallback
          let chargeRoll: number;
          if (rollMatch) {
            chargeRoll = parseInt(rollMatch[1], 10);
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
            type: "charge",
            timestamp,
            turn,
            player,
            log_message: extractLogMessage(trimmed),
            unit_id: unitId,
            target_id: targetId,
            target_pos: { col: targetCol, row: targetRow },
            from: { col: fromCol, row: fromRow },
            to: { col: toCol, row: toRow },
            charge_roll: chargeRoll, // The actual 2d6 roll
            charge_success: true,
          });

          // Update unit position after charge
          if (currentEpisode.units[unitId]) {
            currentEpisode.units[unitId].col = toCol;
            currentEpisode.units[unitId].row = toRow;
          }
        }
      } else if (actionType === "WAIT") {
        // WAIT means the charge roll was too low or unit chose not to charge
        // We don't know the exact roll, but we can indicate it failed
        currentEpisode.actions.push({
          type: "charge_wait",
          timestamp,
          turn,
          player,
          log_message: extractLogMessage(trimmed),
          unit_id: unitId,
          pos: { col: unitCol, row: unitRow },
          charge_roll: 0, // Unknown roll, but too low
          charge_success: false,
        });
      } else if (actionType === "FAILED CHARGE to unit" || actionType === "FAILED charge to unit") {
        // FAILED charge - parse target/roll from current format, or from legacy format.
        let targetId: number | undefined;
        let chargeRoll: number = 0;
        let failedReason: string = "roll_too_low";
        let fromPos: { col: number; row: number } | undefined;
        let toPos: { col: number; row: number } | undefined;
        let targetPos: { col: number; row: number } | undefined;

        // Current format: "FAILED CHARGE to unit X(col,row) [Roll: Y]"
        const newFormatMatch = trimmed.match(
          /FAILED CHARGE to unit (\d+)\((\d+),(\d+)\)\s+\[Roll:\s*(\d+)\]/
        );
        if (newFormatMatch) {
          targetId = parseInt(newFormatMatch[1], 10);
          targetPos = { col: parseInt(newFormatMatch[2], 10), row: parseInt(newFormatMatch[3], 10) };
          chargeRoll = parseInt(newFormatMatch[4], 10);
        } else {
          // Legacy format: "FAILED charge to unit X [Roll:Y] [FAILED: reason]"
          const targetMatch = trimmed.match(/FAILED charge to unit (\d+)/);
          const rollMatch = trimmed.match(/\[Roll:(\d+)\]/);
          const failedReasonMatch = trimmed.match(/\[FAILED: (.+?)\]/);

          targetId = targetMatch ? parseInt(targetMatch[1], 10) : undefined;
          chargeRoll = rollMatch ? parseInt(rollMatch[1], 10) : 0;
          failedReason = failedReasonMatch ? failedReasonMatch[1] : "roll_too_low";
        }

        currentEpisode.actions.push({
          type: "charge_fail",
          timestamp,
          turn,
          player,
          log_message: extractLogMessage(trimmed),
          unit_id: unitId,
          target_id: targetId,
          target_pos: targetPos,
          pos: { col: unitCol, row: unitRow }, // Position actuelle de l'unité (from regex match)
          from: fromPos, // Position de départ (new format)
          to: toPos, // Position de destination prévue (new format)
          charge_roll: chargeRoll,
          charge_success: false,
          charge_failed_reason: failedReason,
        });

        // CRITICAL: Unit position stays at unitCol/unitRow (from regex match) - no movement on failed charge
        // The unit position is already correct from the regex match, no need to update
      }
      continue;
    }

    // Parse RULE CHOICE actions
    // Format: [timestamp] E1 T1 P1 FIGHT : Unit 3(7,12) chose [ADRENALISED ONSLAUGHT] [SUCCESS]
    const ruleChoiceMatch = trimmed.match(
      /\[([^\]]+)\] (?:E\d+\s+)?(T\d+) P(\d+) (\w+) : Unit (\d+)\((\d+),\s*(\d+)\) chose \[([^\]]+)\] \[(SUCCESS|FAILED)\]/
    );
    if (ruleChoiceMatch) {
      const timestamp = ruleChoiceMatch[1];
      const turn = ruleChoiceMatch[2];
      const player = parseInt(ruleChoiceMatch[3], 10);
      const unitId = parseInt(ruleChoiceMatch[5], 10);
      const unitCol = parseInt(ruleChoiceMatch[6], 10);
      const unitRow = parseInt(ruleChoiceMatch[7], 10);
      const selectedRuleName = ruleChoiceMatch[8].trim();
      syncKnownUnitPosition(currentEpisode, unitId, unitCol, unitRow);

      currentEpisode.actions.push({
        type: "rule_choice",
        timestamp,
        turn,
        player,
        unit_id: unitId,
        pos: { col: unitCol, row: unitRow },
        selected_rule_name: selectedRuleName,
        log_message: extractLogMessage(trimmed),
      });
      continue;
    }

    // Parse FIGHT actions
    // Format: [timestamp] T1 P0 FIGHT : Unit 2(9,6) FOUGHT Unit 8(9,7) with [weapon] - Hit:3+:2(MISS) [SUCCESS]
    const fightMatch = trimmed.match(
      /\[([^\]]+)\] (?:E\d+\s+)?(T\d+) P(\d+) FIGHT : Unit (\d+)\((\d+),(\d+)\) (?:ATTACKED|FOUGHT) Unit (\d+)/
    );
    if (fightMatch) {
      const timestamp = fightMatch[1];
      const turn = fightMatch[2];
      const player = parseInt(fightMatch[3], 10);
      const attackerId = parseInt(fightMatch[4], 10);
      const attackerCol = parseInt(fightMatch[5], 10);
      const attackerRow = parseInt(fightMatch[6], 10);
      const targetId = parseInt(fightMatch[7], 10);
      syncKnownUnitPosition(currentEpisode, attackerId, attackerCol, attackerRow);

      // Parse weapon name if present (MULTIPLE_WEAPONS_IMPLEMENTATION.md)
      const weaponMatch = trimmed.match(/with \[([^\]]+)\]/);
      const weaponName = weaponMatch ? weaponMatch[1] : undefined;

      // Parse combat details - Hit:3+:2(MISS/HIT) Wound:4+:5(SUCCESS/FAIL) Save:3+:2(FAIL) Dmg:1HP
      const hitMatch = trimmed.match(/Hit:(\d+)\+:(\d+)\((HIT|MISS)\)/);
      const woundMatch = trimmed.match(/Wound:(\d+)\+:(\d+)\((SUCCESS|WOUND|FAIL)\)/);
      const saveMatch = trimmed.match(/Save:(\d+)\+:(\d+)\((FAIL|SAVED?)\)/);
      const dmgMatch = trimmed.match(/Dmg:(\d+)HP/);
      const fightSubphaseMatch = trimmed.match(/\[FIGHT_SUBPHASE:([^\]]+)\]/);
      const fightPoolsMatch = trimmed.match(
        /\[FIGHT_POOLS:charging=([^;\]]*);active=([^;\]]*);non_active=([^\]]*)\]/
      );
      if (!fightSubphaseMatch || !fightPoolsMatch) {
        throw new Error(`Missing fight metadata in step.log line: ${trimmed}`);
      }
      const fightSubphase = fightSubphaseMatch[1];
      const chargingPool = parsePoolList(fightPoolsMatch[1], "charging");
      const activePool = parsePoolList(fightPoolsMatch[2], "active");
      const nonActivePool = parsePoolList(fightPoolsMatch[3], "non_active");

      const action: ReplayAction = {
        type: "fight",
        timestamp,
        turn,
        player,
        log_message: extractLogMessage(trimmed),
        attacker_id: attackerId,
        attacker_pos: { col: attackerCol, row: attackerRow },
        target_id: targetId,
        weapon_name: weaponName, // Add weapon name for display
        damage: 0, // Will be calculated below based on combat results
        fight_subphase: fightSubphase,
        charging_activation_pool: chargingPool,
        active_alternating_activation_pool: activePool,
        non_active_alternating_activation_pool: nonActivePool,
      };

      // Add detailed combat rolls if available
      if (hitMatch) {
        action.hit_target = parseInt(hitMatch[1], 10);
        action.hit_roll = parseInt(hitMatch[2], 10);
        action.hit_result = hitMatch[3];
      }
      if (woundMatch) {
        action.wound_target = parseInt(woundMatch[1], 10);
        action.wound_roll = parseInt(woundMatch[2], 10);
        action.wound_result = woundMatch[3];
      }
      if (saveMatch) {
        action.save_target = parseInt(saveMatch[1], 10);
        action.save_roll = parseInt(saveMatch[2], 10);
        action.save_result = saveMatch[3];
      }

      // FIGHT logs don't have Dmg:XHP format - infer damage from combat results
      // Damage is dealt if: hit succeeded AND wound succeeded AND save failed
      if (dmgMatch) {
        // If Dmg:XHP is present, use it (future-proofing)
        action.damage = parseInt(dmgMatch[1], 10);
      } else if (
        action.hit_result === "HIT" &&
        (action.wound_result === "WOUND" || action.wound_result === "SUCCESS") &&
        action.save_result === "FAIL"
      ) {
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
    const episodeEndMatch = trimmed.match(/EPISODE END: Winner=(-?\d+)(?:, Method=([a-zA-Z_]+))?/);
    if (episodeEndMatch) {
      const winner = parseInt(episodeEndMatch[1], 10);
      const winMethod = episodeEndMatch[2] || null;
      if (currentEpisode) {
        if (winner === -1) {
          currentEpisode.final_result = "Draw";
        } else if (winner === 1) {
          currentEpisode.final_result = "Agent Win";
        } else if (winner === 2) {
          currentEpisode.final_result = "Bot Win";
        } else {
          throw new Error(`Unknown winner value in step.log: ${winner}`);
        }
        currentEpisode.win_method = winMethod;
      }
    }
  }

  // Add last episode
  if (currentEpisode && currentEpisode.actions.length > 0) {
    episodes.push(currentEpisode);
  }

  // Convert to replay format
  const replayEpisodes = episodes.map((episode) => {
    if (!episode.rules) {
      throw new Error(`Missing Rules block for episode ${episode.episode_num}`);
    }
    // Build initial units with starting positions (episode.units has been mutated by move parsing)
    const initialUnits = [];
    for (const uid in episode.units) {
      const unit = episode.units[uid];
      const startPosRaw = episode.initial_positions[uid];
      if (!startPosRaw) {
        throw new Error(`Missing initial position for unit ${uid} in replay parser`);
      }
      let startPos = startPosRaw;
      const isUndeployedStart = startPosRaw.col < 0 || startPosRaw.row < 0;
      // Backward compatibility: old logs may not contain explicit DEPLOYMENT actions.
      // In that case, infer a usable start position from first seen coordinates.
      if (isUndeployedStart && !episode.deployed_unit_ids.has(Number(uid))) {
        const inferred = episode.first_seen_positions[Number(uid)];
        if (inferred) {
          startPos = inferred;
        }
      }
      // Use unit's actual HP_MAX (set based on unit type during parsing)
      const unitHP = unit.HP_MAX;
      initialUnits.push({
        ...unit,
        col: startPos.col,
        row: startPos.row,
        HP_CUR: unitHP,
        HP_MAX: unitHP,
      });
    }

    const initialState = {
      units: initialUnits,
      walls: episode.walls || [],
      objectives: episode.objectives || [],
      rules: episode.rules,
      currentTurn: 1,
      current_player: 1,
      phase: "move",
    };

    // Build states
    interface UnitInParser {
      id: number;
      player: number;
      col: number;
      row: number;
      HP_CUR: number;
      HP_MAX: number;
      isJustKilled?: boolean;
      [key: string]: unknown;
    }
    const states: ReplayGameState[] = [];
    const currentUnits: Record<number, UnitInParser> = {};
    // Initialize currentUnits with initial positions (episode.units has been mutated)
    for (const unit of initialUnits) {
      currentUnits[unit.id] = { ...unit };
    }

    // Track units to remove after they've been shown as dead
    const unitsToRemove = new Set<number>();

    for (const action of episode.actions) {
      // Clear isJustKilled flag and remove units that were killed in the previous action
      unitsToRemove.forEach((unitId) => {
        if (currentUnits[unitId]) {
          // First clear the flag so the unit shows normally (if it somehow survived)
          delete currentUnits[unitId].isJustKilled;
          // Then remove the unit since it's dead
          delete currentUnits[unitId];
        }
      });
      unitsToRemove.clear();

      if (action.type === "deploy" && action.unit_id) {
        const unitId = action.unit_id;
        if (currentUnits[unitId] && action.to) {
          currentUnits[unitId].col = action.to.col;
          currentUnits[unitId].row = action.to.row;
        }
      } else if ((action.type === "move" || action.type === "reactive_move") && action.unit_id) {
        const unitId = action.unit_id;
        if (currentUnits[unitId] && action.to) {
          currentUnits[unitId].col = action.to.col;
          currentUnits[unitId].row = action.to.row;
        }
      } else if (action.type === "move_wait" && action.unit_id && action.pos) {
        const unitId = action.unit_id;
        if (currentUnits[unitId]) {
          currentUnits[unitId].col = action.pos.col;
          currentUnits[unitId].row = action.pos.row;
        }
      } else if (action.type === "charge" && action.unit_id) {
        // Handle charge actions - update unit position
        const unitId = action.unit_id;
        if (currentUnits[unitId] && action.to) {
          currentUnits[unitId].col = action.to.col;
          currentUnits[unitId].row = action.to.row;
        }
      } else if (action.type === "advance" && action.unit_id) {
        // Handle advance actions - update unit position
        const unitId = action.unit_id;
        if (currentUnits[unitId] && action.to) {
          currentUnits[unitId].col = action.to.col;
          currentUnits[unitId].row = action.to.row;
        }
      } else if (action.type === "shoot" && action.target_id !== undefined) {
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
      } else if (action.type === "hazardous" && action.unit_id !== undefined) {
        const unitId = action.unit_id;
        const hazardousDamage = action.hazardous_mortal_wounds || 0;
        if (currentUnits[unitId] && hazardousDamage > 0) {
          const wasAlive = currentUnits[unitId].HP_CUR > 0;
          currentUnits[unitId].HP_CUR -= hazardousDamage;
          if (currentUnits[unitId].HP_CUR < 0) {
            currentUnits[unitId].HP_CUR = 0;
          }
          const hpAfter = currentUnits[unitId].HP_CUR;
          if (hpAfter <= 0 && wasAlive) {
            currentUnits[unitId].isJustKilled = true;
            unitsToRemove.add(unitId);
          }
        }
      } else if (action.type === "fight" && action.target_id !== undefined) {
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
      let phase = "move";
      if (action.type === "deploy") {
        phase = "deployment";
      } else if (action.type.includes("move")) {
        phase = "move";
      } else if (action.type.includes("shoot") || action.type === "advance") {
        phase = "shoot";
      } else if (action.type.includes("charge")) {
        phase = "charge";
      } else if (action.type.includes("fight")) {
        phase = "fight";
      }

      const fightStateFields = action.type.includes("fight")
        ? {
            fight_subphase: action.fight_subphase,
            charging_activation_pool: action.charging_activation_pool,
            active_alternating_activation_pool: action.active_alternating_activation_pool,
            non_active_alternating_activation_pool: action.non_active_alternating_activation_pool,
          }
        : {};

      // Create state with current units (including just-killed units with flag preserved)
      const stateUnits = Object.values(currentUnits).map((u) => {
        const unitCopy = { ...u };
        // Preserve isJustKilled flag in the copy
        if (u.isJustKilled) {
          unitCopy.isJustKilled = true;
        }
        return unitCopy;
      });

      const turnNumber = parseInt(action.turn.replace("T", ""), 10);
      if (Number.isNaN(turnNumber)) {
        throw new Error(`Invalid turn value in step.log action: ${action.turn}`);
      }
      states.push({
        units: stateUnits,
        walls: episode.walls || [],
        objectives: episode.objectives || [],
        rules: episode.rules,
        currentTurn: turnNumber,
        current_player: action.player,
        phase,
        action,
        ...fightStateFields,
      });
    }

    return {
      episode_num: episode.episode_num,
      scenario: episode.scenario,
      bot_name: episode.bot_name || "Unknown",
      win_method: episode.win_method,
      initial_state: initialState,
      actions: episode.actions,
      states: states,
      total_actions: episode.actions.length,
      final_result: episode.final_result,
    };
  });

  return {
    total_episodes: replayEpisodes.length,
    episodes: replayEpisodes,
  };
}
