// frontend/src/types/replay.ts
export interface ReplayUnit {
  id: number;
  name: string;
  type: string;
  player: 0 | 1;
  col: number;
  row: number;
  color: number;
  MOVE: number;
  HP_MAX: number;
  CUR_HP: number;
  RNG_RNG: number;
  RNG_DMG: number;
  CC_DMG: number;
  ICON: string;
  alive?: boolean;
}

export interface ReplayEvent {
  turn?: number;
  phase?: string;
  action?: number;
  acting_unit_idx?: number;
  target_unit_idx?: number;
  units?: ReplayUnit[];
  ai_units_alive?: number;
  enemy_units_alive?: number;
  game_over?: boolean;
  reward?: number;
  timestamp?: string;
  event_flags?: Record<string, any>;
  unit_stats?: Record<string, any>;
}

export interface ReplayMetadata {
  version?: string;
  format?: string;
  game_type?: string;
  created?: string;
  episode_reward?: number;
  total_events?: number;
  source?: string;
}

export interface ReplayData {
  metadata?: ReplayMetadata;
  game_summary?: {
    final_reward?: number;
    total_turns?: number;
    game_result?: string;
  };
  events: ReplayEvent[];
  web_compatible?: boolean;
  features?: string[];
}

export interface ScenarioUnit {
  id: number;
  unit_type: string;
  player: 0 | 1;
  col: number;
  row: number;
  cur_hp: number;
  hp_max: number;
  move: number;
  rng_rng: number;
  rng_dmg: number;
  cc_dmg: number;
  is_ranged: boolean;
  is_melee: boolean;
  alive: boolean;
}