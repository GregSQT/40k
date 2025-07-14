// frontend/src/types/api.ts
export interface APIResponse<T = any> {
  data: T;
  success: boolean;
  message?: string;
  error?: string;
}

export interface APIError {
  code: string;
  message: string;
  details?: Record<string, any>;
}

export interface AIActionRequest {
  state: {
    units: Array<{
      id: number;
      player: number;
      col: number;
      row: number;
      CUR_HP: number;
      MOVE: number;
      RNG_RNG: number;
      RNG_DMG: number;
      CC_DMG: number;
    }>;
  };
}

export interface AIActionResponse {
  action: "move" | "moveAwayToRngRng" | "shoot" | "charge" | "attack" | "skip";
  unitId: number;
  destCol?: number;
  destRow?: number;
  targetId?: number;
}

export interface RequestConfig {
  timeout?: number;
  retries?: number;
  headers?: Record<string, string>;
  abortController?: AbortController;
}