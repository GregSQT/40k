# ai/api.py

from fastapi import FastAPI
from pydantic import BaseModel
from ai.agent import RLAgent

app = FastAPI()
agent = RLAgent(model_path="ai/model.zip")  # make sure this exists!

class Unit(BaseModel):
    id: int
    player: int
    col: int
    row: int
    CUR_HP: int
    MOVE: int
    RNG_RNG: int
    RNG_DMG: int
    CC_DMG: int

class State(BaseModel):
    units: list[Unit]

class AIRequest(BaseModel):
    state: State

@app.post("/ai/action")
async def ai_action(request: AIRequest):
    # Convert pydantic object to dict, flatten units for RL agent
    state_dict = request.state.dict()
    action = agent.predict(state_dict)
    # Map numeric action to game command
    # Example: 0 = move_toward, 1 = move_away, 2 = shoot_closest, etc.
    action_map = [
        "move_toward_closest", 
        "move_away_closest", 
        "move_to_rng_rng", 
        "shoot_closest", 
        "shoot_lowest_hp", 
        "charge_closest", 
        "charge_lowest_hp", 
        "attack_lowest_hp"
    ]
    action_name = action_map[action] if action < len(action_map) else "end_turn"
    return {"action": action_name}
