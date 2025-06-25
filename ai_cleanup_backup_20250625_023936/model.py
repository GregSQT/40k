# ai/model.py
import random

class SimpleModel:
    def predict(self, state):
        # Dummy: pick a random action for now
        # Later: use NN, policy, etc.
        actions = [
            "move_closer", "move_away", "move_to_range", 
            "shoot_closest", "shoot_weakest", 
            "charge_closest", "charge_weakest", "attack_weakest"
        ]
        return random.choice(actions)
