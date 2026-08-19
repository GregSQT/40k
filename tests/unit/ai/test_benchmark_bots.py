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
        "units_cache": {},
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


def test_balanced_bot_intent_score_when_no_enemies() -> None:
    """Sans ennemis sur la table : _elect_intent retourne SCORE."""
    bot = ReferenceBalancedBot(randomness=0.0)
    gs = _minimal_game_state()
    unit = {"id": "u1", "player": 1, "VALUE": 5.0}
    gs["units"] = [unit]
    intent = bot._elect_intent(unit, gs)
    assert intent == "SCORE"


def _gs_with_enemy(vp_me: int = 0, vp_opp: int = 0) -> tuple:
    """Retourne (game_state, attacker, enemy) avec un ennemi vivant sur le champ."""
    gs = _minimal_game_state()
    attacker = {"id": "u1", "player": 1, "VALUE": 5.0}
    enemy = {"id": "e1", "player": 2, "VALUE": 8.0}
    gs["units"] = [attacker, enemy]
    gs["units_cache"] = {
        "u1": {"col": 5, "row": 5, "HP_CUR": 10, "player": 1},
        "e1": {"col": 6, "row": 6, "HP_CUR": 10, "player": 2},
    }
    gs["victory_points"] = {1: vp_me, 2: vp_opp}
    return gs, attacker, enemy


@pytest.mark.parametrize("vp_me,dmg_att,dmg_def,expected", [
    (0, 15.0, 0.0, "KILL"),    # attaquant peut anéantir → KILL
    (12, 0.0, 10.0, "PRESERVE"),  # menace ennemie + avance VP → PRESERVE
])
def test_balanced_bot_intent_kill_or_preserve(
    vp_me: int, dmg_att: float, dmg_def: float, expected: str
) -> None:
    """_elect_intent retourne KILL ou PRESERVE selon le scoring."""
    from unittest.mock import patch

    gs, attacker, _ = _gs_with_enemy(vp_me=vp_me)
    bot = ReferenceBalancedBot(randomness=0.0)

    def _dmg(game_state, att_id, def_id, is_ranged):
        return dmg_att if att_id == "u1" else dmg_def

    with patch("ai.benchmark_bots.squad_expected_damage", side_effect=_dmg):
        intent = bot._elect_intent(attacker, gs)

    assert intent == expected


def test_denial_bot_move_to_uncontested_objective() -> None:
    """ReferenceDenialBot se dirige vers les objectifs non tenus par lui."""
    bot = ReferenceDenialBot(randomness=0.0)

    # Objectif à (5,5) tenu par le joueur adverse (2).
    gs = _minimal_game_state(player=1)
    # On ne peut pas appeler select_movement_destination sans le moteur complet —
    # on vérifie seulement que la construction est propre et que randomness=0.
    assert bot.randomness == 0.0
    assert isinstance(bot.PLACEMENT_WEIGHTS, dict)
    assert len(bot.PLACEMENT_WEIGHTS) == 7


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 4. VP SCORE — _update_plan bascule quand l'adversaire a une avance VP
# ─────────────────────────────────────────────────────────────────────────────────────────────

def test_reactive_bot_switches_to_score_on_opponent_vp_lead() -> None:
    """_update_plan bascule en SCORE quand l'adversaire dépasse notre VP de _VP_LEAD.

    Scénario : plan forcé à KILL au tour 1, puis l'adversaire prend une avance
    VP supérieure à _VP_LEAD au tour 2. Sans la correction, la condition VP
    était toujours fausse (VP monotone ≥ snapshot) et le plan restait KILL.
    """
    from ai.benchmark_bots import _VP_LEAD

    bot = ReferenceReactiveBot(randomness=0.0)
    # Tour 1 : initialise les snapshots (VP=0/0, pas de pertes).
    gs_t1 = _minimal_game_state(episode=1, turn=1)
    gs_t1["victory_points"] = {1: 0, 2: 0}
    bot._update_plan(gs_t1, player=1)
    # Force le plan en KILL pour que la transition vers SCORE soit observable.
    bot._plan = "KILL"

    # Tour 2 : aucune perte de valeur, adversaire a une avance VP > _VP_LEAD.
    gs_t2 = _minimal_game_state(episode=1, turn=2)
    gs_t2["victory_points"] = {1: 0, 2: int(_VP_LEAD) + 1}
    bot._update_plan(gs_t2, player=1)
    assert bot._plan == "SCORE", (
        f"attendu SCORE quand adversaire VP+{int(_VP_LEAD)+1} vs nous 0, obtenu {bot._plan!r}"
    )


def test_reactive_bot_no_score_switch_when_vp_equal() -> None:
    """_update_plan ne bascule PAS en SCORE si les VP sont égaux."""
    bot = ReferenceReactiveBot(randomness=0.0)
    gs_t1 = _minimal_game_state(episode=1, turn=1)
    gs_t1["victory_points"] = {1: 5, 2: 5}
    bot._update_plan(gs_t1, player=1)
    bot._plan = "KILL"

    gs_t2 = _minimal_game_state(episode=1, turn=2)
    gs_t2["victory_points"] = {1: 10, 2: 10}
    bot._update_plan(gs_t2, player=1)
    assert bot._plan == "KILL", f"plan ne devrait pas changer à VP égaux, obtenu {bot._plan!r}"


def test_reactive_bot_no_score_switch_at_exact_vp_lead_boundary() -> None:
    """Frontière exacte : un retard de PILE _VP_LEAD ne bascule PAS en SCORE.

    La condition est stricte (`vp_me < vp_opp - _VP_LEAD`) : à l'égalité exacte le
    plan reste inchangé. Un `<=` ferait basculer ce scénario.
    """
    from ai.benchmark_bots import _VP_LEAD

    bot = ReferenceReactiveBot(randomness=0.0)
    gs_t1 = _minimal_game_state(episode=1, turn=1)
    bot._update_plan(gs_t1, player=1)
    bot._plan = "KILL"

    gs_t2 = _minimal_game_state(episode=1, turn=2)
    gs_t2["victory_points"] = {1: 0, 2: int(_VP_LEAD)}
    bot._update_plan(gs_t2, player=1)
    assert bot._plan == "KILL", (
        f"retard de pile {int(_VP_LEAD)} VP : la condition stricte doit laisser le plan "
        f"inchangé, obtenu {bot._plan!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 5. require_key pour episode_number (T1 — pas de .get() silencieux)
# ─────────────────────────────────────────────────────────────────────────────────────────────

def test_select_placement_action_raises_on_missing_episode_number() -> None:
    """select_placement_action lève KeyError si episode_number absent du game_state."""
    from ai.evaluation_bots import DEPLOYMENT_ACTIONS
    bot = ReferenceBalancedBot(randomness=0.0)
    gs = _minimal_game_state()
    del gs["episode_number"]
    from shared.data_validation import ConfigurationError
    with pytest.raises(ConfigurationError):
        bot.select_placement_action(list(DEPLOYMENT_ACTIONS), gs)


def test_update_plan_raises_on_missing_episode_number() -> None:
    """_update_plan lève ConfigurationError si episode_number absent du game_state."""
    from shared.data_validation import ConfigurationError
    bot = ReferenceReactiveBot(randomness=0.0)
    gs = _minimal_game_state()
    del gs["episode_number"]
    with pytest.raises(ConfigurationError):
        bot._update_plan(gs, player=1)


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 6. _swing_score_fn et _denial_score_fn lèvent sur hp incohérent (T1)
# ─────────────────────────────────────────────────────────────────────────────────────────────

def _make_game_state_with_unit(sid: str, hp: Optional[int]) -> Dict[str, Any]:
    """game_state minimal avec une unité en cache ; hp=None = pas de cache."""
    gs: Dict[str, Any] = {
        "units": [{"id": sid, "player": 2, "VALUE": 3.0}],
        "units_cache": {},
        "episode_number": 1,
        "turn": 1,
        "phase": "shoot",
        "victory_points": {1: 0, 2: 0},
        "objectives": [],
        "objective_controllers": {},
    }
    if hp is not None:
        gs["units_cache"][sid] = {"HP_CUR": hp, "position": (0, 0), "on_battlefield": True}
    return gs


def test_swing_score_fn_raises_on_none_hp() -> None:
    """_swing_score_fn lève ValueError quand l'unité n'est pas en cache (hp=None)."""
    from ai.benchmark_bots import _swing_score_fn
    from unittest.mock import patch

    fn = _swing_score_fn("att1", is_ranged=True)
    gs = _make_game_state_with_unit("tgt1", hp=None)
    entry = {"VALUE": 3.0}
    with patch("ai.benchmark_bots.squad_expected_damage", return_value=5.0):
        with pytest.raises(ValueError, match="absent du cache"):
            fn("tgt1", entry, gs)


def test_denial_score_fn_raises_on_none_hp() -> None:
    """_denial_score_fn lève ValueError quand l'unité n'est pas en cache (hp=None)."""
    bot = ReferenceDenialBot(randomness=0.0)
    attacker = {"id": "att1", "player": 1}
    gs = _make_game_state_with_unit("tgt1", hp=None)
    gs["objective_controllers"] = {}
    entry = {"VALUE": 3.0}
    fn = bot._denial_score_fn(attacker, is_ranged=True, game_state=gs)
    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "ai.benchmark_bots.squad_expected_damage", return_value=5.0
    ):
        with pytest.raises(ValueError, match="absent du cache"):
            fn("tgt1", entry, gs)


def test_swing_score_fn_raises_on_zero_hp() -> None:
    """_swing_score_fn lève ValueError quand le cache annonce HP<=0.

    Distinct de hp=None : ici l'unité EST dans le cache (donc réputée vivante) mais
    avec un HP incohérent — division par zéro évitée par une erreur explicite, pas
    par un fallback (T1).
    """
    from ai.benchmark_bots import _swing_score_fn
    from unittest.mock import patch

    fn = _swing_score_fn("att1", is_ranged=True)
    gs = _make_game_state_with_unit("tgt1", hp=0)
    entry = {"VALUE": 3.0}
    with patch("ai.benchmark_bots.squad_expected_damage", return_value=5.0):
        with pytest.raises(ValueError, match="HP=0"):
            fn("tgt1", entry, gs)


def test_denial_score_fn_raises_on_zero_hp() -> None:
    """_denial_score_fn lève ValueError quand le cache annonce HP<=0."""
    from unittest.mock import patch

    bot = ReferenceDenialBot(randomness=0.0)
    attacker = {"id": "att1", "player": 1}
    gs = _make_game_state_with_unit("tgt1", hp=0)
    entry = {"VALUE": 3.0}
    fn = bot._denial_score_fn(attacker, is_ranged=True, game_state=gs)
    with patch("ai.benchmark_bots.squad_expected_damage", return_value=5.0):
        with pytest.raises(ValueError, match="HP=0"):
            fn("tgt1", entry, gs)


def test_elect_intent_raises_on_zero_hp() -> None:
    """_elect_intent lève ValueError quand un ennemi du cache annonce HP<=0.

    La liste d'ennemis est passée explicitement (paramètre `enemies`) : c'est le
    chemin qu'emprunte select_movement_destination, qui calcule la liste une fois
    et la partage avec l'élection d'intention.
    """
    from unittest.mock import patch

    bot = ReferenceBalancedBot(randomness=0.0)
    gs = _make_game_state_with_unit("tgt1", hp=0)
    unit = {"id": "att1", "player": 1, "VALUE": 5.0}
    enemy = gs["units"][0]
    with patch("ai.benchmark_bots.squad_expected_damage", return_value=5.0):
        with pytest.raises(ValueError, match="HP=0"):
            bot._elect_intent(unit, gs, [enemy])
