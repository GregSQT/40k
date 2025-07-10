from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from ai.agent import RLAgent
from config_loader import get_config_loader

app = FastAPI()

# Add CORS middleware to allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],  # Frontend URLs
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Load configuration
config_loader = get_config_loader()
model_path = config_loader.get_model_path()
agent = RLAgent(model_path=model_path)

# Load API configuration
api_config = config_loader.get_game_config().get("api", {})
api_prefix = api_config.get("prefix", "/ai")
action_endpoint = api_config.get("action_endpoint", "/action")

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

@app.post(f"{api_prefix}{action_endpoint}")
async def ai_action(request: AIRequest):
    # Convert pydantic object to dict, flatten units for RL agent
    state_dict = request.state.dict()
    action = agent.predict(state_dict)
    # Map numeric action to game command
    def get_action_map():
        """Get action mapping from config files instead of hardcoding."""
        rewards_config = config_loader.get_rewards_config()
        first_unit_type = list(rewards_config.keys())[0]
        return list(rewards_config[first_unit_type].keys())

    # Load action mapping from config
    action_map = get_action_map()
    if isinstance(action, int) and 0 <= action < len(action_map):
        action_name = action_map[action]
    else:
        action_name = "end_turn"
    
    # Get first unit ID from request for response
    first_unit_id = request.state.units[0].id if request.state.units else 1
    
    return {
        "action": action_name if action_name != "end_turn" else "skip",
        "unitId": first_unit_id
    }

