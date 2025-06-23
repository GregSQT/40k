# ai/train.py

import os
import sys
import json
import subprocess

from stable_baselines3 import DQN
from stable_baselines3.common.env_checker import check_env
from ai.gym40k import W40KEnv

######################################################################################
### Training configuration
total_timesteps_setup = 1_000_000  # Total timesteps for training. Debug : 100_000
exploration_fraction_setup = 0.5   # Fraction of timesteps spent exploring
######################################################################################

def parse_args():
    resume = None
    for arg in sys.argv[1:]:
        if arg.lower() == "--resume":
            resume = True
        elif arg.lower() == "--new":
            resume = False
    return resume

if __name__ == "__main__":
    print("🔧 Regenerating scenario.json from Scenario.ts...")
    subprocess.run(["python", "generate_scenario.py"], check=True)
    env = W40KEnv()
    check_env(env)  # Good for debugging!
    model_path = "ai/model.zip"
    resume_flag = parse_args()

    if os.path.exists(model_path):
        if resume_flag is None:
            # No explicit flag, default: resume
            print("Model exists. Resuming training from last checkpoint (default).")
            resume = True
        else:
            resume = resume_flag
        if resume:
            print("Resuming from previous model...")
            model = DQN.load(model_path, env=env)
        else:
            print("Starting new model (overwriting previous model)...")
            model = DQN(
                "MlpPolicy",
                env,
                verbose=1,
                buffer_size=10000,
                learning_rate=1e-3,
                learning_starts=100,
                batch_size=64,
                train_freq=4,
                target_update_interval=500,
                exploration_fraction=exploration_fraction_setup,
                exploration_final_eps=0.05,
                tensorboard_log="./tensorboard/"
            )
    else:
        print("No previous model found. Starting new model...")
        model = DQN(
            "MlpPolicy",
            env,
            verbose=1,
            buffer_size=10000,
            learning_rate=1e-3,
            learning_starts=100,
            batch_size=64,
            train_freq=4,
            target_update_interval=500,
            exploration_fraction=0.5,
            exploration_final_eps=0.05,
            tensorboard_log="./tensorboard/"
        )

    model.learn(total_timesteps=total_timesteps_setup)
    os.makedirs("ai", exist_ok=True)
    model.save(model_path)
    if hasattr(env, "episode_logs") and env.episode_logs:
        # Find best and worst by total reward
        best_log, best_reward = max(env.episode_logs, key=lambda x: x[1])
        worst_log, worst_reward = min(env.episode_logs, key=lambda x: x[1])
        with open("ai/best_event_log.json", "w") as f:
            json.dump(best_log, f, indent=2)
        with open("ai/worst_event_log.json", "w") as f:
            json.dump(worst_log, f, indent=2)
        print(f"Saved best and worst episode logs: rewards {best_reward}, {worst_reward}")
    print("Model saved to ai/model.zip")
    env.close()
