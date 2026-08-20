"""Vérifie que _count_engaged_models_after_charge continue sur la cible suivante
quand entries_in_engagement_zone lève ValueError (figurine hors table).

DÉFAUT VERROUILLÉ : avant le fix, `except (ValueError, KeyError): break` sortait de la
boucle cible au premier ValueError, laissant les cibles suivantes non vérifiées et
sous-comptant les figurines engagées.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch


def _minimal_game_state() -> Dict[str, Any]:
    """State minimal : 1 chargeur C#0, 2 cibles T#0 (hors table) et T#1 (valide)."""
    return {
        "models_cache": {
            "C#0": {"id": "C#0"},
            "T#0": {"id": "T#0"},
            "T#1": {"id": "T#1"},
        },
        "squad_models": {
            "100": ["C#0"],
            "200": ["T#0", "T#1"],
        },
        "inches_to_subhex": 2,
    }


def _call(game_state: Dict[str, Any]) -> tuple[int, int]:
    from engine.phase_handlers.charge_handlers import _count_engaged_models_after_charge

    return _count_engaged_models_after_charge(game_state, "100", "200")


def _side_effect_raises_then_true(first_entry, second_entry, *args, **kwargs):
    """Lève ValueError sur T#0, retourne True sur T#1."""
    if second_entry.get("id") == "T#0":
        raise ValueError("off_battlefield_sentinel")
    return True


def test_continue_sur_target_hors_table():
    """C#0 doit être comptée engagée via T#1 même si T#0 lève ValueError."""
    gs = _minimal_game_state()
    with patch(
        "engine.spatial_relations.entries_in_engagement_zone",
        side_effect=_side_effect_raises_then_true,
    ), patch(
        "engine.spatial_relations.engagement_distance_metric",
        return_value="euclidean",
    ):
        engaged, total = _call(gs)

    assert total == 1, f"total attendu 1, obtenu {total}"
    assert engaged == 1, (
        f"C#0 doit être engagée via T#1 (T#0 hors table) — engaged={engaged}"
    )


