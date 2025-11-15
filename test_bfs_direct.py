import sys
import json
sys.path.insert(0, '.')

# Force reimport
if 'engine.phase_handlers.movement_handlers' in sys.modules:
    del sys.modules['engine.phase_handlers.movement_handlers']

from engine.phase_handlers import movement_handlers

# Load minimal game state
with open('config/board_config.json', encoding='utf-8-sig') as f:
    board = json.load(f)['default']

game_state = {
    'board_cols': 25,
    'board_rows': 21,
    'wall_hexes': set((w[0], w[1]) for w in board['wall_hexes']),
    'units': [
        {'id': '1', 'col': 9, 'row': 12, 'player': 0, 'HP_CUR': 100, 'MOVE': 6, 'CC_RNG': 1},
        {'id': '2', 'col': 11, 'row': 12, 'player': 0, 'HP_CUR': 100, 'MOVE': 6, 'CC_RNG': 1},
        {'id': '5', 'col': 9, 'row': 7, 'player': 1, 'HP_CUR': 100, 'MOVE': 6, 'CC_RNG': 1},
    ]
}

print("Calling BFS for unit 1...")
dests = movement_handlers.movement_build_valid_destinations_pool(game_state, '1')
print(f"Got {len(dests)} destinations")
print(f"Is (3,9) in destinations? {(3,9) in dests}")
