// frontend/src/ai/ai.ts

interface GameState {
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
}

export async function fetchAiAction(gameState: GameState) {
  console.log("[AI] Sending gameState to backend:", gameState);
  const response = await fetch("http://localhost:8000/ai/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ state: { units: gameState.units } })
  });
  const result = await response.json();
  console.log("[AI] Got result from backend:", result);
  return result;
}
