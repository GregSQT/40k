"""Tests unitaires — lacunes de couverture de combat_utils.py.

Complète test_combat_utils.py (2 tests) et test_combat_utils_extended.py.
Cible les variantes de résolution de dés et chemins d'erreur non couverts.
"""

from __future__ import annotations

import pytest

from engine.combat_utils import (
    calculate_hex_distance,
    calculate_pathfinding_distance,
    calculate_wound_target,
    check_los_cached,
    expected_dice_value,
    get_hex_neighbors,
    get_unit_by_id,
    normalize_coordinate,
    resolve_dice_value,
)


# ─────────────────────────────────────────────────────────────────────────────
# resolve_dice_value — variantes non testées
# ─────────────────────────────────────────────────────────────────────────────

class TestResolveDiceValueVariants:

    def test_d3_range(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """dice_d3 : D3 (d6/2 arrondi au sup) → valeur dans [1,3]."""
        monkeypatch.setattr("random.randint", lambda a, b: 5)
        result = resolve_dice_value("D3", "ctx")
        assert result == 3  # (5+1)//2 = 3

    def test_d3_low_roll(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """dice_d3_low : D3 avec d6=1 → 1."""
        monkeypatch.setattr("random.randint", lambda a, b: 1)
        assert resolve_dice_value("D3", "ctx") == 1

    def test_d6_returns_roll(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """dice_d6 : D6 retourne la valeur du dé brut."""
        monkeypatch.setattr("random.randint", lambda a, b: 4)
        assert resolve_dice_value("D6", "ctx") == 4

    def test_d6_plus_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """dice_d6p1 : D6+1 avec dé=3 → 4."""
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        assert resolve_dice_value("D6+1", "ctx") == 4

    def test_d6_plus_2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """dice_d6p2 : D6+2 avec dé=3 → 5."""
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        assert resolve_dice_value("D6+2", "ctx") == 5

    def test_d6_plus_3(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """dice_d6p3 : D6+3 avec dé=3 → 6."""
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        assert resolve_dice_value("D6+3", "ctx") == 6

    def test_raises_type_error_on_float(self) -> None:
        """dice_float : float → TypeError (pas int, pas str)."""
        with pytest.raises(TypeError, match=r"Invalid dice value type"):
            resolve_dice_value(3.5, "ctx")  # type: ignore[arg-type]

    def test_raises_type_error_on_none(self) -> None:
        """dice_none : None → TypeError."""
        with pytest.raises(TypeError, match=r"Invalid dice value type"):
            resolve_dice_value(None, "ctx")  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# expected_dice_value — variantes non testées
# ─────────────────────────────────────────────────────────────────────────────

class TestExpectedDiceValueVariants:

    def test_d6_returns_3_5(self) -> None:
        """exp_d6 : D6 → 3.5."""
        assert expected_dice_value("D6", "ctx") == 3.5

    def test_2d6_returns_7(self) -> None:
        """exp_2d6 : 2D6 → 7.0."""
        assert expected_dice_value("2D6", "ctx") == 7.0

    def test_d6_plus_1_returns_4_5(self) -> None:
        """exp_d6p1 : D6+1 → 4.5."""
        assert expected_dice_value("D6+1", "ctx") == 4.5

    def test_d6_plus_2_returns_5_5(self) -> None:
        """exp_d6p2 : D6+2 → 5.5."""
        assert expected_dice_value("D6+2", "ctx") == 5.5


# ─────────────────────────────────────────────────────────────────────────────
# check_los_cached — chemin target absent du cache
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckLosCachedGaps:

    def test_returns_0_when_los_false(self) -> None:
        """los_false : los_cache=False → 0.0."""
        shooter = {"id": "s1", "los_cache": {"t1": False}}
        target = {"id": "t1"}
        assert check_los_cached(shooter, target, {}) == 0.0

    def test_raises_when_target_missing_from_cache(self) -> None:
        """los_missing_target : target absent du los_cache → ValueError."""
        shooter = {"id": "s1", "los_cache": {"other": True}}
        target = {"id": "t_unknown"}
        with pytest.raises(ValueError, match=r"los_cache missing target"):
            check_los_cached(shooter, target, {})


# ─────────────────────────────────────────────────────────────────────────────
# calculate_pathfinding_distance — cas position identique
# ─────────────────────────────────────────────────────────────────────────────

def test_pathfinding_distance_same_position_returns_0() -> None:
    """pf_same : distance entre une position et elle-même = 0."""
    gs = {"board_cols": 10, "board_rows": 10, "wall_hexes": set()}
    assert calculate_pathfinding_distance(3, 5, 3, 5, gs) == 0


# ─────────────────────────────────────────────────────────────────────────────
# calculate_hex_distance — cas supplémentaires
# ─────────────────────────────────────────────────────────────────────────────

class TestCalculateHexDistanceGaps:

    def test_distance_symmetric(self) -> None:
        """hex_sym : dist(A,B) == dist(B,A)."""
        assert calculate_hex_distance(2, 3, 5, 7) == calculate_hex_distance(5, 7, 2, 3)

    def test_distance_same_column_adjacent_rows(self) -> None:
        """hex_adj_col : même colonne, lignes adjacentes → distance=1."""
        assert calculate_hex_distance(4, 4, 4, 5) == 1

    def test_distance_is_non_negative(self) -> None:
        """hex_nonneg : distance toujours >= 0."""
        assert calculate_hex_distance(0, 0, 10, 10) >= 0
