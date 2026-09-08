"""Vérifie que le profil x1_lineage porte bien la surcharge early_stop.promote_min_episodes."""
from __future__ import annotations

from ai.curriculum import _EARLY_STOP_REQUIRED_KEYS
from config_loader import get_config_loader


def _load_x1_lineage() -> dict:
    return get_config_loader().load_agent_training_config("ArmageddonAgent_x1", "x1_lineage")


def test_x1_lineage_early_stop_promote_min_is_30000() -> None:
    profile = _load_x1_lineage()
    assert profile["early_stop"]["promote_min_episodes"] == 30000


def test_x1_lineage_early_stop_keys_are_valid() -> None:
    """Seules les clés autorisées peuvent figurer dans early_stop du profil."""
    profile = _load_x1_lineage()
    unknown = set(profile["early_stop"]) - set(_EARLY_STOP_REQUIRED_KEYS)
    assert unknown == set(), f"Clés inconnues dans early_stop du profil : {sorted(unknown)}"
