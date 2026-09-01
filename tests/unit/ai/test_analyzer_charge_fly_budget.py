"""_per_model_move_violation : mouvement FLY mesuré en euclidien, pas en hexagonal.

Avant le fix, `calculate_hex_distance` (cube coords) était utilisé pour les mouvements FLY.
Or, un FLY se déplace en ligne droite, ignorant murs et obstacles — la distance pertinente est
euclidienne. La distance hexagonale peut être PLUS GRANDE que l'euclidienne pour un mouvement
diagonal, produisant de faux « charge over budget ».

Exemple : de (0,0) à (4,10).
  - Distance euclidienne : √(16+100) ≈ 10,77
  - Distance hexagonale (cube coords) : max(4, 12, 8) = 12

Avec budget = 11 : euclidien → dans le budget, hexagonal → dépassement.

Fix : `math.sqrt(Δcol² + Δrow²) > budget` pour is_fly=True.
"""
from __future__ import annotations

import math

from ai.analyzer import _per_model_move_violation
from engine.combat_utils import calculate_hex_distance


def test_fly_budget_euclidien_ok(tmp_path=None):
    """FLY vers (4,10) avec budget 11 : eucl ≈ 10.77 ≤ 11 → pas de violation."""
    ok = _per_model_move_violation(
        None, None, (0, 0), (4, 10), 11, True, set(), set(), set()
    )
    assert not ok, f"FLY dans budget euclidien ne doit pas être une violation"


def test_hex_distance_diverge_du_budget():
    """Témoin : hex_distance(0,0 → 4,10) = 12 > 11 → l'ancien code produisait une violation."""
    assert calculate_hex_distance(0, 0, 4, 10) == 12
    assert math.sqrt(4**2 + 10**2) < 11
