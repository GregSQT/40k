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
  training_data?: {
    timestep?: number;
    decision?: {
      timestep: number;
      action_chosen: number;
      is_exploration: boolean;
      epsilon?: number;
      model_confidence?: number;
      q_values?: number[];
      best_q_value?: number;
      action_q_value?: number;
    };
  };
}

export interface ReplayMetadata {
  version?: string;
  format?: string;
  game_type?: string;
  created?: string;
  episode_reward?: number;
  total_events?: number;
  source?: string;
  format_version?: string;
  replay_type?: string;
  training_context?: {
    timestep?: number;
    episode_num?: number;
    model_info?: Record<string, any>;
    start_time?: string;
  };
  web_compatible?: boolean;
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
  training_summary?: {
    total_decisions?: number;
    exploration_decisions?: number;
    exploitation_decisions?: number;
    exploration_rate?: number;
    avg_model_confidence?: number;
    timestep_range?: {
      start: number;
      end: number;
    };
  };
  game_states?: any[]; // For compatibility with game_replay_logger format
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