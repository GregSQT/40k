"""
AI_TURN.md Phase Handler Modules
Pure stateless functions implementing AI_TURN.md specification
"""

from . import movement_handlers
from . import shooting_handlers
from . import charge_handlers  
from . import fight_handlers
from . import deployment_handlers

__all__ = [
    'movement_handlers',
    'shooting_handlers', 
    'charge_handlers',
    'fight_handlers',
    'deployment_handlers'
]