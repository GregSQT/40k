class Unit:
    def __init__(self, name, x, y):
        self.name = name
        self.x = float(x)
        self.y = float(y)
        self.hp = 3

class GameState:
    def __init__(self, board_shape):
        self.board_shape = board_shape
        self.units = [...]  # List of Unit

    def reset(self):
        # Place units at (int) grid positions
        pass

    def observe(self):
        # Return flattened (x, y, hp) for each unit
        return np.array([unit.x, unit.y, unit.hp] for unit in self.units).flatten()

    def apply_action(self, action):
        # Map action to move/attack; update positions (int now, float later)
        # Return new obs, reward, done, info
        pass
