"""Tests unitaires — reward_calculator : determine_winner."""

from __future__ import annotations

from typing import Any, Dict

from engine.reward_calculator import RewardCalculator


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_calculator() -> RewardCalculator:
    """Instance minimale sans state_manager ni unit_registry."""
    return RewardCalculator(
        config={"quiet": True},
        rewards_config={},
        unit_registry=None,
        state_manager=None,
    )


def _cache_entry(player: int) -> Dict[str, Any]:
    return {"player": player, "col": 0, "row": 0, "HP_CUR": 1}


def _gs_with_cache(entries: Dict[str, Any]) -> Dict[str, Any]:
    return {"units_cache": entries}


# ─────────────────────────────────────────────────────────────────────────────
# _determine_winner (chemin legacy sans state_manager)
# ─────────────────────────────────────────────────────────────────────────────

class TestDetermineWinner:
    def test_only_player1_wins(self):
        """winner_p1 : seul joueur 1 a des unités → winner=1."""
        rc = _make_calculator()
        cache = {"1": _cache_entry(1), "2": _cache_entry(1)}
        result = rc._determine_winner(_gs_with_cache(cache))
        assert result == 1

    def test_only_player2_wins(self):
        """winner_p2 : seul joueur 2 a des unités → winner=2."""
        rc = _make_calculator()
        cache = {"1": _cache_entry(2), "2": _cache_entry(2)}
        result = rc._determine_winner(_gs_with_cache(cache))
        assert result == 2

    def test_both_players_alive_returns_none(self):
        """winner_none : les deux joueurs ont des unités → None (partie en cours)."""
        rc = _make_calculator()
        cache = {"1": _cache_entry(1), "2": _cache_entry(2)}
        result = rc._determine_winner(_gs_with_cache(cache))
        assert result is None

    def test_empty_cache_returns_minus_one(self):
        """winner_draw : cache vide → -1 (égalité/élimination mutuelle)."""
        rc = _make_calculator()
        result = rc._determine_winner(_gs_with_cache({}))
        assert result == -1

    def test_multiple_units_same_player(self):
        """winner_multi : 3 unités joueur 1, 0 joueur 2 → winner=1."""
        rc = _make_calculator()
        cache = {"1": _cache_entry(1), "2": _cache_entry(1), "3": _cache_entry(1)}
        result = rc._determine_winner(_gs_with_cache(cache))
        assert result == 1

    def test_single_unit_player2_wins(self):
        """winner_single_p2 : 1 unité joueur 2 → winner=2."""
        rc = _make_calculator()
        cache = {"5": _cache_entry(2)}
        result = rc._determine_winner(_gs_with_cache(cache))
        assert result == 2
