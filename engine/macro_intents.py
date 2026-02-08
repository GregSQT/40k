#!/usr/bin/env python3
"""
engine/macro_intents.py - Shared macro intent definitions for macro/micro coordination.
"""

from typing import Dict

INTENT_TAKE_OBJECTIVE = 0
INTENT_HOLD_OBJECTIVE = 1
INTENT_FOCUS_KILL = 2
INTENT_SCREEN = 3
INTENT_ATTRITION = 4
INTENT_COUNT = 5

DETAIL_OBJECTIVE = 0
DETAIL_ENEMY = 1
DETAIL_ALLY = 2
DETAIL_NONE = 3

INTENT_NAMES: Dict[int, str] = {
    INTENT_TAKE_OBJECTIVE: "take_objective",
    INTENT_HOLD_OBJECTIVE: "hold_objective",
    INTENT_FOCUS_KILL: "focus_kill",
    INTENT_SCREEN: "screen",
    INTENT_ATTRITION: "attrition",
}

INTENT_DETAIL_TYPE: Dict[int, int] = {
    INTENT_TAKE_OBJECTIVE: DETAIL_OBJECTIVE,
    INTENT_HOLD_OBJECTIVE: DETAIL_OBJECTIVE,
    INTENT_FOCUS_KILL: DETAIL_ENEMY,
    INTENT_SCREEN: DETAIL_ALLY,
    INTENT_ATTRITION: DETAIL_OBJECTIVE,
}

def get_intent_detail_type(intent_id: int) -> int:
    """Return detail type for intent."""
    if intent_id not in INTENT_DETAIL_TYPE:
        raise KeyError(f"Unknown intent id: {intent_id}")
    return INTENT_DETAIL_TYPE[intent_id]
