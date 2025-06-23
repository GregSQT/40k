import os
import json
from stable_baselines3 import DQN
from ai.gym40k import W40KEnv

def scripted_policy(unit, enemy_units):
    # Example: Always attack closest if in range, else move toward closest
    if unit["is_ranged"]:
        candidates = [e for e in enemy_units if e["alive"] and max(abs(unit["col"] - e["col"]), abs(unit["row"] - e["row"])) <= unit["rng_rng"]]
        if candidates:
            return "shoot", candidates[0]
    elif unit["is_melee"]:
        pass
    return "wait", None

def evaluate_vs_scripted(n_episodes=100):
    env = W40KEnv(scripted_opponent=True)
    model = DQN.load("ai/model.zip", env=env)
    ai_wins = 0
    rewards = []
    best_episode = None
    best_reward = float('-inf')

    for ep in range(n_episodes):
        obs, info = env.reset()
        done = False
        total_reward = 0
        event_log = []
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            # === Patch: Record event log for this episode
            if hasattr(env, "event_log"):
                # Deepcopy or reconstruct event log step to avoid references
                for ev in env.event_log[len(event_log):]:
                    # Patch: Ensure units have ICON, col, row, id, name, player, CUR_HP, HP_MAX
                    for u in ev["units"]:
                        # Fallback ICON if missing
                        if "ICON" not in u:
                            # Patch here with correct logic for your unit classes
                            if u.get("unit_type") == "AssaultIntercessor":
                                u["ICON"] = "/icons/AssaultIntercessor.webp"
                            elif u.get("unit_type") == "Intercessor":
                                u["ICON"] = "/icons/Intercessor.webp"
                            else:
                                u["ICON"] = "/icons/default.png"
                        if "CUR_HP" not in u:
                            u["CUR_HP"] = u.get("cur_hp", 1)
                        if "HP_MAX" not in u:
                            u["HP_MAX"] = u.get("hp_max", 4)
                        if "id" not in u:
                            u["id"] = u.get("id", -1)
                        if "name" not in u:
                            u["name"] = u.get("unit_type", "Unit")
                        if "player" not in u:
                            u["player"] = u.get("player", 0)
                        if "col" not in u or "row" not in u:
                            u["col"] = u.get("col", 0)
                            u["row"] = u.get("row", 0)
                    event_log.append(ev.copy())
            done = terminated or truncated

        if env.did_win():
            ai_wins += 1
        rewards.append(total_reward)
        if total_reward > best_reward:
            best_reward = total_reward
            best_episode = event_log.copy()  # Deepcopy for safety

    print(f"AI win rate vs scripted bot: {ai_wins}/{n_episodes} = {ai_wins / n_episodes:.2%}")
    print(f"Average reward vs scripted bot: {sum(rewards)/len(rewards):.2f}")

    # === Save best episode for replay
    if best_episode:
        os.makedirs("ai", exist_ok=True)
        with open("ai/best_event_log.json", "w") as f:
            json.dump(best_episode, f, indent=2)
        print("Best replay saved to ai/best_event_log.json")

if __name__ == "__main__":
    evaluate_vs_scripted(100)
