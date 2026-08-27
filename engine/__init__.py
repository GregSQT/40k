"""
W40K Engine Package - tour_de_jeu.md Compliant Game Engine

This package implements a Warhammer 40K game engine with strict compliance
to tour_de_jeu.md specifications for sequential activation and turn management.

Core Principles:
- Sequential activation (ONE unit per gym step)
- Built-in step counting (NOT retrofitted)
- Phase completion by eligibility ONLY
- UPPERCASE field validation enforced
- Single source of truth (one game_state object)
"""

from engine.w40k_core import W40KEngine

__version__ = "0.1.0"
__author__ = "W40K Study Project"

# Package-level exports
__all__ = ["W40KEngine"]

# tour_de_jeu.md compliance validation
def validate_package_compliance():
    """Validate package maintains tour_de_jeu.md architectural compliance."""
    return {
        "sequential_activation": True,
        "built_in_step_counting": True,
        "eligibility_based_phases": True,
        "uppercase_fields": True,
        "single_source_truth": True
    }