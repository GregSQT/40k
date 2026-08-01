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


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_on_objective_reward — cohérence avec le contrôle réel (01.07 + 14.02)
# ─────────────────────────────────────────────────────────────────────────────

def _objective_gs(battle_shocked: bool) -> Dict[str, Any]:
    """Escouade de 2 figurines dont l'ANCRE est HORS de la zone et la SECONDE figurine dedans.

    Ce montage est ce qui rend le test non vacant : le bonus se juge par FIGURINE (14.02, meme
    lecteur que ``sum_objective_control_oc_multi``), et une lecture a l'ancre d'escouade —
    l'erreur classique de ce depot — rendrait 0.0 ici alors que l'escouade est bien sur
    l'objectif. Les trois caches sont ceux que ``iter_living_model_footprints`` exige.
    """
    unit = {"id": "1", "player": 1, "battle_shocked": battle_shocked}
    return {
        "units": [unit],
        "unit_by_id": {"1": unit},
        "units_cache": {"1": {"player": 1, "col": 3, "row": 3, "HP_CUR": 1, "orientation": 0}},
        "squad_models": {"1": ["1#0", "1#1"]},
        "models_cache": {
            "1#0": {"col": 3, "row": 3, "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1},
            "1#1": {"col": 5, "row": 5, "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1},
        },
        "objectives": [{"id": "obj1", "hexes": [{"col": 5, "row": 5}]}],
        "objective_controllers": {"obj1": None},
        "current_player": 1,
    }


def _objective_calculator() -> RewardCalculator:
    rc = RewardCalculator(
        config={"quiet": True, "controlled_player": 1},
        rewards_config={},
        unit_registry=None,
        state_manager=None,
    )
    rc._get_unit_reward_config = lambda unit: {
        "objective_rewards": {"on_objective_bonus": 2.5}
    }
    return rc


class TestOnObjectiveRewardBattleShock:
    """Le bonus paie la progression vers un contrôle (14.02). Une unité battle-shocked a l'OC
    de toutes ses figurines à '-' (01.07) : elle ne peut RIEN prendre, donc rien à payer."""

    def test_bonus_paid_when_not_battle_shocked(self):
        """obj_reward_ok : unité saine sur un objectif non contrôlé → bonus versé."""
        rc = _objective_calculator()
        result = {"unitId": "1", "toCol": 5, "toRow": 5}
        assert rc._calculate_on_objective_reward(_objective_gs(False), result) == 2.5

    def test_no_bonus_when_battle_shocked(self):
        """obj_reward_shock : même mouvement sous battle-shock → aucun bonus."""
        rc = _objective_calculator()
        result = {"unitId": "1", "toCol": 5, "toRow": 5}
        assert rc._calculate_on_objective_reward(_objective_gs(True), result) == 0.0
