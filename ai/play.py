# ai/play.py

from stable_baselines3 import DQN
from ai.gym40k import W40KEnv

def display_state(env):
    print("\n--- Board State ---")
    for idx, u in enumerate(env.units):
        status = "Alive" if u["alive"] else "Dead"
        print(
            f"Unit {idx}: P{u['player']} {u['unit_type']} | Pos: ({u['col']},{u['row']}) | HP: {u['cur_hp']} | {status}"
        )

def main():
    env = W40KEnv()
    model = DQN.load("ai/model.zip")
    obs, info = env.reset()
    done = False

    while not done:
        # ---- Human player's turn ----
        env.reset_phase_flags()
        human_units = [
            (idx, u) for idx, u in enumerate(env.units)
            if u["player"] == 0 and u["alive"] and not u["has_acted_this_phase"]
        ]
        for idx, unit in human_units:
            display_state(env)
            print(f"\nYour turn: Unit {idx} ({unit['unit_type']})")
            print("Choose action: 0 = Move Close, 1 = Move Away, 2 = Move to Safe, 3 = Move to RNG Range, "
                  "4 = Move to Charge, 5 = Shoot/Attack, 6 = Charge, 7 = Wait")
            action = int(input("Action (0-7): "))
            obs, reward, terminated, truncated, info = env.step(action)
            if terminated or truncated:
                done = True
                break

        if done:
            break

        # ---- AI player's turn ----
        env.reset_phase_flags()
        ai_units = [
            (idx, u) for idx, u in enumerate(env.units)
            if u["player"] == 1 and u["alive"] and not u["has_acted_this_phase"]
        ]
        for idx, unit in ai_units:
            action, _ = model.predict(obs, deterministic=True)
            print(f"\nAI (Unit {idx} - {unit['unit_type']}) chooses action: {action}")
            obs, reward, terminated, truncated, info = env.step(action)
            if terminated or truncated:
                done = True
                break

    display_state(env)
    print("\nGame Over!")
    if env.did_win():
        print("AI wins!")
    else:
        print("Human wins!")
    env.close()

if __name__ == "__main__":
    main()
