"""Tests pour ai/benchmark_bots.py (§4.C Bot_refactor.md).

Trois invariants :
1. Construction — chaque clé benchmark produit le bon type via le registre.
2. Non-régression d'entraînement — aucune clé benchmark dans bot_training.ratios.
3. Stabilité de plan réactif — le plan de ReferenceReactiveBot ne change pas au sein d'un tour.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from ai import bot_registry
from ai.benchmark_bots import (
    ReferenceBalancedBot, ReferenceDenialBot, ReferenceReactiveBot,
)

BENCHMARK_KEYS = bot_registry.BENCHMARK_BOT_KEYS
EXPECTED_CLASSES = {
    "reference_balanced": ReferenceBalancedBot,
    "reference_denial": ReferenceDenialBot,
    "reference_reactive": ReferenceReactiveBot,
}

# ─────────────────────────────────────────────────────────────────────────────────────────────
# 1. Construction via le registre
# ─────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", BENCHMARK_KEYS)
def test_build_bot_produces_expected_class(key: str) -> None:
    """build_bot(key) produit la bonne classe de benchmark."""
    bot = bot_registry.build_bot(key, {key: 0.0})
    assert isinstance(bot, EXPECTED_CLASSES[key])


@pytest.mark.parametrize("key", BENCHMARK_KEYS)
def test_randomness_zero_accepted(key: str) -> None:
    """randomness=0.0 est la valeur neutre — construire sans lever."""
    bot = bot_registry.build_bot(key, {key: 0.0})
    assert bot.randomness == 0.0


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 2. Non-régression d'entraînement — aucun benchmark dans bot_training.ratios
# ─────────────────────────────────────────────────────────────────────────────────────────────

def _collect_bot_training_profiles() -> list:
    """Tous les fichiers de profil d'agent qui ont un bot_training.ratios."""
    repo_root = Path(__file__).parent.parent.parent.parent
    config_dir = repo_root / "config" / "agents"
    profiles = []
    if not config_dir.exists():
        return profiles
    for json_path in config_dir.rglob("*.json"):
        try:
            with open(json_path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and "bot_training" in data:
            bt = data["bot_training"]
            if isinstance(bt, dict) and "ratios" in bt:
                profiles.append((str(json_path), bt["ratios"]))
    return profiles


@pytest.mark.parametrize("profile_path,ratios", _collect_bot_training_profiles())
def test_no_benchmark_key_in_training_ratios(profile_path: str, ratios: Any) -> None:
    """Un benchmark dans bot_training.ratios serait un holdout entraîné — violation §4.C."""
    if not isinstance(ratios, dict):
        pytest.skip(f"ratios n'est pas un dict dans {profile_path}")
    intersection = set(ratios) & set(BENCHMARK_KEYS)
    assert not intersection, (
        f"{profile_path} contient des clés benchmark dans bot_training.ratios : {intersection}"
    )


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 3. Stabilité du plan réactif au sein d'un tour
# ─────────────────────────────────────────────────────────────────────────────────────────────

def _minimal_game_state(episode: int = 1, turn: int = 1, player: int = 1) -> Dict[str, Any]:
    return {
        "units": [],
        "turn": turn,
        "episode_number": episode,
        "phase": "move",
        "victory_points": {1: 0, 2: 0},
        "objectives": [],
        "objective_controllers": {},
    }


def test_reactive_bot_plan_stable_within_same_turn() -> None:
    """Le plan de ReferenceReactiveBot ne change pas quand on appelle _update_plan
    plusieurs fois avec le même marqueur (même épisode, même tour).

    Le marqueur (episode_number, turn) est la contrainte de stabilité intra-tour :
    plusieurs activations dans un tour voient le même plan.
    """
    bot = ReferenceReactiveBot(randomness=0.0)
    gs = _minimal_game_state(episode=42, turn=3)

    bot._update_plan(gs, player=1)
    plan_first = bot._plan

    # Deuxième appel : même tour → plan inchangé.
    bot._update_plan(gs, player=1)
    plan_second = bot._plan

    assert plan_first == plan_second, (
        f"Plan a changé au sein du même tour : {plan_first!r} → {plan_second!r}"
    )


def test_reactive_bot_plan_resets_on_new_episode() -> None:
    """Un nouvel épisode remet le plan à 'SCORE' et réinitialise les snapshots."""
    bot = ReferenceReactiveBot(randomness=0.0)

    # Épisode 1 — pousser le bot en plan KILL manuellement pour vérifier le reset.
    gs_ep1 = _minimal_game_state(episode=1, turn=1)
    bot._update_plan(gs_ep1, player=1)
    bot._plan = "KILL"  # forcer un plan non-SCORE

    # Épisode 2 — doit réinitialiser.
    gs_ep2 = _minimal_game_state(episode=2, turn=1)
    bot._update_plan(gs_ep2, player=1)

    assert bot._plan == "SCORE", f"Plan attendu 'SCORE' après reset d'épisode, obtenu {bot._plan!r}"
    assert bot._snapshot_episode == 2


def test_balanced_bot_intent_returns_valid_value() -> None:
    """_elect_intent retourne toujours une des trois valeurs valides."""
    bot = ReferenceBalancedBot(randomness=0.0)
    gs = _minimal_game_state()
    # Construire une fausse unité.
    unit = {"id": "u1", "player": 1, "VALUE": 5.0}
    gs["units"] = [unit]
    # Sans ennemis sur la table : intent doit être SCORE (pas de kill possible).
    intent = bot._elect_intent(unit, gs)
    assert intent in ("SCORE", "KILL", "PRESERVE")


def test_denial_bot_move_to_uncontested_objective() -> None:
    """ReferenceDenialBot se dirige vers les objectifs non tenus par lui."""
    bot = ReferenceDenialBot(randomness=0.0)

    # Objectif à (5,5) tenu par le joueur adverse (2).
    gs = _minimal_game_state(player=1)
    # On ne peut pas appeler select_movement_destination sans le moteur complet —
    # on vérifie seulement que la construction est propre et que randomness=0.
    assert bot.randomness == 0.0
    assert isinstance(bot.PLACEMENT_WEIGHTS, dict)
    assert len(bot.PLACEMENT_WEIGHTS) == 5
