"""Tests pour le profil comportemental §4.D.4.

Trois invariants :
1. Profil présent pour chaque adversaire ayant joué des épisodes.
2. Ventilation par issue : les comptes win+draw+loss = total épisodes.
3. Valeurs correctes : VP, zones, shoot_actions correspondent à ce que le moteur produit.
"""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from ai.bot_evaluation import _accumulate_behavior


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────────────────────

def _mock_env(
    vp_player1: float = 10.0,
    zones_player1: int = 2,
    ai_shoot_opportunities: int = 5,
    ai_shoot_actions: int = 3,
    player: int = 1,
) -> MagicMock:
    """Env factice qui expose engine.game_state et get_shoot_stats()."""
    env = MagicMock()
    # Construire objective_controllers avec exactement zones_player1 zones pour `player`.
    controllers = {}
    for i in range(zones_player1):
        controllers[f"obj_p{i}"] = player
    controllers["obj_opp"] = 3 - player  # une zone adverse
    env.engine.game_state = {
        "victory_points": {player: vp_player1, 3 - player: 5.0},
        "objective_controllers": controllers,
    }
    env.get_shoot_stats.return_value = {
        "ai_shoot_opportunities": ai_shoot_opportunities,
        "ai_shoot_actions": ai_shoot_actions,
    }
    return env


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 1. _accumulate_behavior remplit le seau avec les bonnes valeurs
# ─────────────────────────────────────────────────────────────────────────────────────────────

def test_accumulate_behavior_win_episode() -> None:
    """Un épisode gagné remplit le seau 'win' avec les valeurs de l'env."""
    behavior_stats: Dict[str, Any] = {}
    env = _mock_env(vp_player1=10.0, zones_player1=2, ai_shoot_opportunities=5, ai_shoot_actions=3)

    _accumulate_behavior(behavior_stats, "win", env, controlled_player=1)

    assert "win" in behavior_stats
    bucket = behavior_stats["win"]
    assert bucket["count"] == 1
    assert bucket["vp"] == pytest.approx(10.0)
    assert bucket["zones_held"] == 2
    assert bucket["ai_shoot_opportunities"] == 5
    assert bucket["ai_shoot_actions"] == 3


def test_accumulate_behavior_skips_when_no_controlled_player() -> None:
    """Si controlled_player est None (épisode tronqué très tôt), on ne crée aucun seau."""
    behavior_stats: Dict[str, Any] = {}
    env = _mock_env()

    _accumulate_behavior(behavior_stats, "draw", env, controlled_player=None)

    assert behavior_stats == {}


def test_accumulate_behavior_sums_across_episodes() -> None:
    """Plusieurs épisodes s'additionnent dans le même seau."""
    behavior_stats: Dict[str, Any] = {}
    env1 = _mock_env(vp_player1=10.0, zones_player1=2, ai_shoot_opportunities=4, ai_shoot_actions=2)
    env2 = _mock_env(vp_player1=20.0, zones_player1=1, ai_shoot_opportunities=6, ai_shoot_actions=5)

    _accumulate_behavior(behavior_stats, "win", env1, controlled_player=1)
    _accumulate_behavior(behavior_stats, "win", env2, controlled_player=1)

    bucket = behavior_stats["win"]
    assert bucket["count"] == 2
    assert bucket["vp"] == pytest.approx(30.0)
    assert bucket["zones_held"] == 3
    assert bucket["ai_shoot_opportunities"] == 10
    assert bucket["ai_shoot_actions"] == 7


def test_accumulate_behavior_different_issues_separate_buckets() -> None:
    """Wins et losses restent dans des seaux séparés."""
    behavior_stats: Dict[str, Any] = {}
    env_win = _mock_env(vp_player1=15.0, zones_player1=3)
    env_loss = _mock_env(vp_player1=5.0, zones_player1=0)

    _accumulate_behavior(behavior_stats, "win", env_win, controlled_player=1)
    _accumulate_behavior(behavior_stats, "loss", env_loss, controlled_player=1)

    assert behavior_stats["win"]["vp"] == pytest.approx(15.0)
    assert behavior_stats["loss"]["vp"] == pytest.approx(5.0)


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 2. Ventilation : count(win) + count(draw) + count(loss) = total épisodes joués
# ─────────────────────────────────────────────────────────────────────────────────────────────

def test_issue_counts_sum_to_total_episodes() -> None:
    """Quel que soit le résultat, chaque épisode est compté exactement une fois."""
    behavior_stats: Dict[str, Any] = {}
    env = _mock_env()
    issues = ["win", "win", "loss", "draw", "win", "loss"]

    for issue in issues:
        _accumulate_behavior(behavior_stats, issue, env, controlled_player=1)

    total = sum(behavior_stats[i]["count"] for i in behavior_stats)
    assert total == len(issues)


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 3. log_behavioral_profile publie les bonnes courbes TensorBoard
# ─────────────────────────────────────────────────────────────────────────────────────────────

def test_log_behavioral_profile_writes_scalars() -> None:
    """log_behavioral_profile appelle writer.add_scalar pour chaque (bot, metric)."""
    from unittest.mock import call
    from ai.metrics_tracker import W40KMetricsTracker as MetricsTracker

    writer = MagicMock()
    tracker = MagicMock(spec=MetricsTracker)
    tracker.writer = writer
    tracker.episode_count = 0

    profile = {
        "reference_balanced": {
            "win": {"vp": 30.0, "zones_held": 6, "ai_shoot_opportunities": 10,
                    "ai_shoot_actions": 7, "count": 3},
            "loss": {"vp": 10.0, "zones_held": 1, "ai_shoot_opportunities": 8,
                     "ai_shoot_actions": 4, "count": 2},
        },
    }

    # Appeler la méthode réelle (pas sur le MagicMock du tracker).
    MetricsTracker.log_behavioral_profile(tracker, profile, step=5000)

    calls = writer.add_scalar.call_args_list
    call_tags = [c[0][0] for c in calls]

    # Les métriques agrégées (win+loss) doivent être publiées par bot.
    for metric in ("vp", "zones_held", "ai_shoot_opportunities", "ai_shoot_actions", "count"):
        assert any(f"bot_eval/profile/reference_balanced/{metric}" in tag for tag in call_tags), \
            f"Métrique manquante dans les scalars TensorBoard : bot_eval/profile/reference_balanced/{metric}"


def test_log_behavioral_profile_skips_empty_profile() -> None:
    """Un profil vide ne provoque aucun appel writer.add_scalar."""
    from ai.metrics_tracker import W40KMetricsTracker as MetricsTracker

    writer = MagicMock()
    tracker = MagicMock(spec=MetricsTracker)
    tracker.writer = writer
    tracker.episode_count = 0

    MetricsTracker.log_behavioral_profile(tracker, {}, step=1000)

    writer.add_scalar.assert_not_called()


def test_log_behavioral_profile_aggregates_issues() -> None:
    """Les totaux win+loss sont ADDITIONNÉS (pas moyennés) dans la courbe TensorBoard."""
    from ai.metrics_tracker import W40KMetricsTracker as MetricsTracker

    writer = MagicMock()
    tracker = MagicMock(spec=MetricsTracker)
    tracker.writer = writer
    tracker.episode_count = 0

    profile = {
        "tactical": {
            "win": {"vp": 10.0, "count": 2},
            "draw": {"vp": 4.0, "count": 1},
        },
    }

    MetricsTracker.log_behavioral_profile(tracker, profile, step=1000)

    # vp agrégé = 10.0 + 4.0 = 14.0
    calls = {c[0][0]: c[0][1] for c in writer.add_scalar.call_args_list}
    vp_tag = "bot_eval/profile/tactical/vp"
    assert vp_tag in calls, f"Tag {vp_tag!r} attendu"
    assert calls[vp_tag] == pytest.approx(14.0)
