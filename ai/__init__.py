# ai/__init__.py
"""
W40K AI Training Package
"""

# Try to import gym40k module with fallback
try:
    from .gym40k import W40KEnv
except ImportError:
    # Fallback for when running scripts directly
    try:
        from gym40k import W40KEnv
    except ImportError:
        W40KEnv = None

__all__ = ['W40KEnv']