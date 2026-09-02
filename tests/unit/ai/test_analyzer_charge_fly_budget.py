"""_per_model_move_violation : mouvement FLY mesuré en distance hexagonale cube-coords.

Le moteur utilise `calculate_hex_distance` (cube coords) pour les mouvements FLY
(`move_plan_distance_mode → "cube" → model_reach_predicate → calculate_hex_distance ≤ budget`).
L'analyzer doit utiliser la même métrique pour ne pas produire de faux positifs.

Cas du journal (2026-09-02) : unité FLY de (43,58) à (34,53) avec budget = 10.
  - Distance hexagonale : max(9, 10, 1) = 10 ≤ 10 → moteur autorise
  - Distance euclidienne : √(81+25) ≈ 10.30 > 10 → l'ancienne formule produisait un faux positif

(L'ancienne formule utilisait l'euclidien, suite à un précédent fix qui avait constaté que hex >
euclidien pour certains mouvements diagonaux. Les deux métriques peuvent être dans l'un ou l'autre
sens selon la trajectoire — seule la métrique du moteur, `calculate_hex_distance`, est correcte.)
"""
from __future__ import annotations

import math

from ai.analyzer import _per_model_move_violation
from engine.combat_utils import calculate_hex_distance


def test_fly_dans_budget_hex_ok():
    """FLY de (43,58) à (34,53) avec budget 10 : hex = 10 ≤ 10 → pas de violation."""
    ok = _per_model_move_violation(
        None, None, (43, 58), (34, 53), 10, True, set(), set(), set()
    )
    assert not ok, "FLY dans budget hexagonal ne doit pas être une violation"


def test_fly_hors_budget_hex_violation():
    """FLY de (43,58) à (34,53) avec budget 9 : hex = 10 > 9 → violation."""
    viol = _per_model_move_violation(
        None, None, (43, 58), (34, 53), 9, True, set(), set(), set()
    )
    assert viol, "FLY hors budget hexagonal doit être une violation"


def test_hex_distance_temoins():
    """Témoins : hex_distance(43,58 → 34,53) = 10 ; euclidien ≈ 10.30 (supérieur au budget)."""
    assert calculate_hex_distance(43, 58, 34, 53) == 10
    assert math.sqrt((34 - 43) ** 2 + (53 - 58) ** 2) > 10
