"""Régression : _invalidate_los_cache_for_moved_unit — prévention des bugs "shoot through wall"."""

from __future__ import annotations

from typing import Any, Dict

from engine.phase_handlers.shooting_handlers import _invalidate_los_cache_for_moved_unit


def _make_game_state_with_caches() -> Dict[str, Any]:
    return {
        "los_cache": {
            ("1", "2"): 1.0,
            ("2", "1"): 1.0,
            ("1", "3"): 0.0,
            ("3", "1"): 0.5,
            ("2", "3"): 1.0,
        },
        "hex_los_cache": {
            ((5, 10), (20, 10)): 1.0,
            ((5, 10), (15, 5)): 0.0,
            ((20, 10), (15, 5)): 1.0,
        },
    }


class TestInvalidateLosCacheForMovedUnit:
    def test_removes_all_los_cache_entries_for_moved_unit(self):
        gs = _make_game_state_with_caches()
        _invalidate_los_cache_for_moved_unit(gs, "1")
        remaining = set(gs["los_cache"].keys())
        assert ("1", "2") not in remaining
        assert ("2", "1") not in remaining
        assert ("1", "3") not in remaining
        assert ("3", "1") not in remaining
        # Entry not involving unit 1 preserved
        assert ("2", "3") in remaining

    def test_clears_hex_los_cache_fully_when_no_old_position(self):
        gs = _make_game_state_with_caches()
        _invalidate_los_cache_for_moved_unit(gs, "1")
        assert gs["hex_los_cache"] == {}

    def test_selective_hex_cache_invalidation_with_old_position(self):
        gs = _make_game_state_with_caches()
        _invalidate_los_cache_for_moved_unit(gs, "1", old_col=5, old_row=10)
        # Entries involving old position (5,10) must be removed
        assert ((5, 10), (20, 10)) not in gs["hex_los_cache"]
        assert ((5, 10), (15, 5)) not in gs["hex_los_cache"]
        # Entry not involving (5,10) preserved
        assert ((20, 10), (15, 5)) in gs["hex_los_cache"]

    def test_no_crash_when_los_cache_missing(self):
        gs = {"hex_los_cache": {}}
        _invalidate_los_cache_for_moved_unit(gs, "1")

    def test_no_crash_when_hex_los_cache_missing(self):
        gs = {"los_cache": {("1", "2"): 1.0}}
        _invalidate_los_cache_for_moved_unit(gs, "1")
        assert gs["los_cache"] == {}

    def test_string_and_int_unit_id_normalized(self):
        gs = {
            "los_cache": {("1", "2"): 1.0, (1, 2): 0.5},
            "hex_los_cache": {},
        }
        _invalidate_los_cache_for_moved_unit(gs, 1)
        # Both string "1" and int 1 keys involving unit 1 removed
        assert ("1", "2") not in gs["los_cache"]
        assert (1, 2) not in gs["los_cache"]

    def test_empty_caches_no_crash(self):
        gs = {"los_cache": {}, "hex_los_cache": {}}
        _invalidate_los_cache_for_moved_unit(gs, "1")
        assert gs["los_cache"] == {}
        assert gs["hex_los_cache"] == {}

    def test_mixed_type_key_tuple_removed(self):
        """Clé avec types mixtes (str, int) — str(key[n]) normalise → doit être supprimée."""
        gs = {
            "los_cache": {
                ("1", 2): 0.5,   # clé mixte : "1" (str) et 2 (int)
                (1, "2"): 0.8,   # autre mixte : 1 (int) et "2" (str)
                ("3", "4"): 1.0, # non impliqué
            },
            "hex_los_cache": {},
        }
        _invalidate_los_cache_for_moved_unit(gs, "1")
        assert ("1", 2) not in gs["los_cache"]
        assert (1, "2") not in gs["los_cache"]
        assert ("3", "4") in gs["los_cache"]
