// frontend/src/services/aiService.ts
import { AIGameState, AIAction } from '../types';

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
      timeout: 3000, // Shorter timeout for faster failure detection
      retries: 1, // Single retry since backend is either up or down
      ...config,
    };
}

  private pendingRequests = new Map<string, Promise<AIAction>>();

  async fetchAiAction(gameState: AIGameState, currentUnitId?: number): Promise<AIAction> {
    // Create a unique key for this request to prevent duplicates
    const requestKey = `${gameState.units.map(u => `${u.id}-${u.col}-${u.row}-${u.CUR_HP}`).join('|')}-${currentUnitId}-${Date.now()}`;
    
    // If same request is already pending, return existing promise
    if (this.pendingRequests.has(requestKey)) {
      console.log('[AI] Reusing pending request for same game state');
      return this.pendingRequests.get(requestKey)!;
    }

    const requestPromise = this.executeAiRequest(gameState, currentUnitId);
    this.pendingRequests.set(requestKey, requestPromise);
    
    try {
      const result = await requestPromise;
      return result;
    } finally {
      this.pendingRequests.delete(requestKey);
    }
  }

  private async executeAiRequest(gameState: AIGameState, currentUnitId?: number): Promise<AIAction> {
    let lastError: Error | null = null;

    for (let attempt = 1; attempt <= this.config.retries; attempt++) {
      try {
        console.log(`[AI] Attempt ${attempt}/${this.config.retries} - Sending gameState:`, gameState);
        
        const controller = new AbortController();
        const timeoutId = setTimeout(() => {
          console.warn(`[AI] Request timeout after ${this.config.timeout}ms - backend likely unavailable`);
          controller.abort();
        }, this.config.timeout);

        let response: Response;
        try {
          response = await fetch(`${this.config.baseUrl}/ai/action`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ state: { units: gameState.units } }),
            signal: controller.signal,
          });
        } finally {
          clearTimeout(timeoutId);
        }

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

    // If all attempts failed, return fallback action instead of throwing
    console.warn('[AI] All attempts failed, using fallback action');
    return this.getFallbackAction(currentUnitId || gameState.units[0]?.id || 1);
  }

  /**
   * Get fallback action when AI service is unavailable
   */
  getFallbackAction(unitId: number): AIAction {
    console.log(`[AI] Using fallback 'skip' action for unit ${unitId}`);
    return {
      action: 'skip',
      unitId: unitId,
    };
  }

  /**
   * Check if backend is likely available (optional health check)
   */
  async isBackendAvailable(): Promise<boolean> {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 1000); // Very short timeout
      
      const response = await fetch(`${this.config.baseUrl}/health`, {
        method: 'GET',
        signal: controller.signal,
      });
      
      clearTimeout(timeoutId);
      return response.ok;
    } catch {
      console.log('[AI] Backend health check failed - backend not available');
      return false;
    }
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