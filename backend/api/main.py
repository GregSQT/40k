from fastapi import FastAPI
from backend.rl.env_gym import WH40KEnv

app = FastAPI()
env = WH40KEnv()

@app.post("/reset")
def reset():
    obs, _ = env.reset()
    return {"obs": obs.tolist()}

@app.post("/step")
def step(action: int):
    obs, reward, terminated, truncated, info = env.step(action)
    return {
        "obs": obs.tolist(),
        "reward": reward,
        "terminated": terminated,
        "truncated": truncated,
        "info": info,
    }
