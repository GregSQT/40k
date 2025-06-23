# ai/replay.py

import json
import time
import os

BOARD_WIDTH = 24
BOARD_HEIGHT = 18

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def get_unit_symbol(unit):
    # Show A/a for player 0, B/b for player 1; capital = ranged, lower = melee
    if not unit["alive"]:
        return "x"
    if unit["player"] == 0:
        return "A" if unit.get("is_ranged", False) else "a"
    else:
        return "B" if unit.get("is_ranged", False) else "b"

def print_board(units):
    board = [["." for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)]
    for unit in units:
        if not unit["alive"]:
            continue
        c, r = unit["col"], unit["row"]
        if 0 <= r < BOARD_HEIGHT and 0 <= c < BOARD_WIDTH:
            board[r][c] = get_unit_symbol(unit)
    print("   " + " ".join(f"{i:2}" for i in range(BOARD_WIDTH)))
    for rowidx, row in enumerate(board):
        print(f"{rowidx:2} " + " ".join(row))
    print()

def print_event(event):
    print(
        f"Turn {event['turn']}, Phase: {event['phase']}, "
        f"Unit: {event['acting_unit_idx']}, "
        f"Target: {event['target_unit_idx']}, "
        f"Flags: {event['event_flags']}, "
        f"Stats: {event['unit_stats']}"
    )

def replay_live(event_log, title):
    print(f"\n=== {title} ===\n")
    for event in event_log:
        clear_screen()
        print_event(event)
        if "units" in event:
            print_board(event["units"])
        time.sleep(0.7)

if __name__ == "__main__":
    with open("ai/best_event_log.json", "r") as f:
        best_log = json.load(f)
    replay_live(best_log, "BEST EPISODE REPLAY")
