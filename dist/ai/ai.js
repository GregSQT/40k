// frontend/src/ai/ai.ts
export async function fetchAiAction(gameState) {
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
