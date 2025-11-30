"""Debug script to trace why fight phase doesn't remove units from charging_activation_pool."""

import sys
sys.path.insert(0, '.')

from engine.w40k_core import W40KEngine
from engine.phase_handlers import fight_handlers
from engine.phase_handlers.generic_handlers import end_activation

# Monkey-patch end_activation to trace calls
original_end_activation = end_activation

def traced_end_activation(game_state, unit, arg1, arg2, arg3, arg4, arg5):
    print(f"\n>>> END_ACTIVATION CALLED:")
    print(f"   unit_id: {unit.get('id') if unit else 'None'}")
    print(f"   arg1={arg1}, arg2={arg2}, arg3={arg3}, arg4={arg4}, arg5={arg5}")
    print(f"   BEFORE - charging_pool: {game_state.get('charging_activation_pool', [])}")

    result = original_end_activation(game_state, unit, arg1, arg2, arg3, arg4, arg5)

    print(f"   AFTER - charging_pool: {game_state.get('charging_activation_pool', [])}")
    print(f"   result: {result}")
    return result

# Apply patch
import engine.phase_handlers.generic_handlers as gh
gh.end_activation = traced_end_activation

# Also patch the fight_handlers import
import engine.phase_handlers.fight_handlers as fh
fh.end_activation = traced_end_activation


def main():
    print("=" * 60)
    print("FIGHT PHASE DEBUG TEST")
    print("=" * 60)

    # Create game state directly (no environment needed for handler test)
    game_state = {
        "units": [
            {"id": "1", "unit_type": "Intercessor", "player": 0, "col": 12, "row": 10,
             "HP_CUR": 3, "HP_MAX": 3, "CC_NB": 1, "CC_HIT": 3, "CC_AP": 0, "CC_DMG": 1, "CC_STR": 4,
             "CC_RNG": 1, "CC_ATK": 1, "ATTACK_LEFT": 1, "HAS_CHARGED": True, "TOUGHNESS": 4, "T": 4,
             "SAVE": 3, "SV": 3, "ARMOR_SAVE": 3, "INVUL_SAVE": 7},
            {"id": "2", "unit_type": "Termagant", "player": 1, "col": 12, "row": 11,
             "HP_CUR": 1, "HP_MAX": 1, "CC_NB": 1, "CC_HIT": 4, "CC_AP": 0, "CC_DMG": 1, "CC_STR": 3,
             "CC_RNG": 1, "CC_ATK": 1, "ATTACK_LEFT": 1, "HAS_CHARGED": False, "TOUGHNESS": 3, "T": 3,
             "SAVE": 5, "SV": 5, "ARMOR_SAVE": 5, "INVUL_SAVE": 7},
        ],
        "wall_hexes": [],
        "objectives": [],
        "phase": "fight",
        "current_player": 0,
        "turn": 1,
        "gym_training_mode": True
    }

    # Setup fighting pools
    game_state["charging_activation_pool"] = ["1"]
    game_state["active_alternating_activation_pool"] = []
    game_state["non_active_alternating_activation_pool"] = ["2"]
    unit1 = game_state["units"][0]

    print(f"\nInitial state:")
    print(f"  Phase: {game_state['phase']}")
    print(f"  charging_activation_pool: {game_state['charging_activation_pool']}")
    print(f"  active_alternating_pool: {game_state['active_alternating_activation_pool']}")
    print(f"  non_active_alternating_pool: {game_state['non_active_alternating_activation_pool']}")

    # Build valid targets for unit 1
    valid_targets = fh._fight_build_valid_target_pool(game_state, unit1)
    print(f"  valid_targets for unit 1: {valid_targets}")
    game_state["valid_fight_targets"] = valid_targets

    # Process fight action
    print("\n" + "=" * 60)
    print("PROCESSING FIGHT ACTION")
    print("=" * 60)

    action = {"action": "fight", "unitId": "1"}
    config = {"gym_training_mode": True}

    print(f"Action: {action}")
    print(f"Config: {config}")

    success, result = fh.execute_action(game_state, unit1, action, config)

    print(f"\nResult: success={success}")
    print(f"Result dict: {result}")

    print(f"\nFinal state:")
    print(f"  Phase: {game_state['phase']}")
    print(f"  charging_activation_pool: {game_state.get('charging_activation_pool', [])}")
    print(f"  active_alternating_pool: {game_state.get('active_alternating_activation_pool', [])}")
    print(f"  non_active_alternating_pool: {game_state.get('non_active_alternating_activation_pool', [])}")


if __name__ == "__main__":
    main()
