# ai/test.py
from stable_baselines3 import DQN
from ai.gym40k import W40KEnv

env = W40KEnv()
model = DQN.load("ai/model.zip")

obs, _ = env.reset()
done = False
while not done:
    action, _states = model.predict(obs, deterministic=True)
    obs, reward, terminated, truncated, info = env.step(action)
    done = terminated or truncated
    print(f"Action: {action}, Reward: {reward}")