// services/aiService.ts
import { AIGameState, AIAction } from '../types/game';

export class AIServiceError extends Error {
  constructor(message: string, public readonly cause?: Error) {
    super(message);
    this.name = 'AIServiceError';
  }
}

export interface AIServiceConfig {
  baseUrl: string;
  timeout: number;
  retries: number;
}

export class AIService {
  private config: AIServiceConfig;

  constructor(config: Partial<AIServiceConfig> = {}) {
    this.config = {
      baseUrl: 'http://localhost:8000',
      timeout: 5000,
      retries: 3,
      ...config,
    };
  }

  async fetchAiAction(gameState: AIGameState): Promise<AIAction> {
    let lastError: Error | null = null;

    for (let attempt = 1; attempt <= this.config.retries; attempt++) {
      try {
        console.log(`[AI] Attempt ${attempt}/${this.config.retries} - Sending gameState:`, gameState);
        
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), this.config.timeout);

        const response = await fetch(`${this.config.baseUrl}/ai/action`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ state: { units: gameState.units } }),
          signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();
        
        if (!this.isValidAIAction(result)) {
          throw new Error('Invalid AI action response format');
        }

        console.log('[AI] Received valid response:', result);
        return result;

      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));
        console.warn(`[AI] Attempt ${attempt} failed:`, lastError.message);
        
        if (attempt < this.config.retries) {
          // Exponential backoff
          await this.delay(Math.pow(2, attempt) * 500);
        }
      }
    }

    throw new AIServiceError(
      `Failed to fetch AI action after ${this.config.retries} attempts`,
      lastError || undefined
    );
  }

  private isValidAIAction(obj: any): obj is AIAction {
    return (
      obj &&
      typeof obj === 'object' &&
      typeof obj.action === 'string' &&
      ['move', 'moveAwayToRngRng', 'shoot', 'charge', 'attack', 'skip'].includes(obj.action) &&
      typeof obj.unitId === 'number' &&
      (obj.destCol === undefined || typeof obj.destCol === 'number') &&
      (obj.destRow === undefined || typeof obj.destRow === 'number') &&
      (obj.targetId === undefined || typeof obj.targetId === 'number')
    );
  }

  private delay(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}

// Singleton instance
export const aiService = new AIService();