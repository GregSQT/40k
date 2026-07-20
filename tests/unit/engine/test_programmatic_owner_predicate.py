"""R4 / T1 — prédicat unique « ce joueur est piloté par la machine ».

Contexte (V11 §0.19.1). §8.3 exige pour R4 « une matrice complète : (gym_training_mode
True/False) × (player_types human/ai) ; allocation tir auto en gym ; allocation fight auto en
gym ; en PvP humain, l'allocation reste manuelle (miroir) ; `_is_ai_controlled_shooting_unit`
NON branché sur gym (test négatif) ». L'audit du 2026-07-20 a constaté que **rien** dans
`tests/` ne référençait `is_programmatic_owner` ni `is_programmatic_defender` — la seule
couverture était indirecte (la branche gym=True, via
`test_t5_bare_loop.py::test_bare_loop_melee_losses_via_fight_ctx`). Ce fichier ferme le trou.

Contrat couvert ([shared_utils.py:97-124](../../engine/phase_handlers/shared_utils.py#L97-L124)) :
- en gym, **toujours** True (self-play : `player_types` vaut human/human mais aucun humain réel) ;
- hors gym, comportement historique `player_types[p] == "ai"` ;
- **aucun repli silencieux** : `player_types` manquant hors gym, ou joueur absent de la table,
  est un bug → erreur explicite.

⚠️ Le test négatif sur `_is_ai_controlled_shooting_unit` est le verrou anti-récidive du ⚠️ R4 :
l'auto-activation ne doit JAMAIS basculer sur le prédicat gym, sous peine de faire jouer des
unités toutes seules en entraînement.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.phase_handlers.shared_utils import (
    is_programmatic_defender,
    is_programmatic_owner,
)
from shared.data_validation import ConfigurationError


# ── Matrice gym × player_types ─────────────────────────────────────────────────

@pytest.mark.parametrize("p1_type,p2_type", [
    ("human", "human"),
    ("human", "ai"),
    ("ai", "human"),
    ("ai", "ai"),
])
@pytest.mark.parametrize("player", ["1", "2"])
def test_gym_mode_is_always_programmatic(player, p1_type, p2_type):
    """En gym, le prédicat vaut True pour TOUT joueur, quel que soit `player_types`.

    C'est le cœur de R4 : en self-play `player_types` vaut human/human alors qu'aucun humain
    n'est là pour répondre à une allocation.
    """
    gs = {"gym_training_mode": True, "player_types": {"1": p1_type, "2": p2_type}}
    assert is_programmatic_owner(gs, player) is True


@pytest.mark.parametrize("ptype,expected", [("ai", True), ("human", False)])
@pytest.mark.parametrize("player", ["1", "2"])
def test_out_of_gym_follows_player_types(player, ptype, expected):
    """Hors gym, comportement historique : `player_types[p] == "ai"` (miroir PvP/PvE inchangé)."""
    gs = {"gym_training_mode": False, "player_types": {"1": ptype, "2": ptype}}
    assert is_programmatic_owner(gs, player) is expected


def test_out_of_gym_human_is_not_programmatic_even_if_other_is_ai():
    """PvE : le joueur humain reste manuel alors que son adversaire est piloté."""
    gs = {"gym_training_mode": False, "player_types": {"1": "human", "2": "ai"}}
    assert is_programmatic_owner(gs, "1") is False
    assert is_programmatic_owner(gs, "2") is True


def test_gym_flag_absent_behaves_as_out_of_gym():
    """Absence de `gym_training_mode` = PvP : on retombe sur player_types, pas sur True."""
    gs = {"player_types": {"1": "human", "2": "ai"}}
    assert is_programmatic_owner(gs, "1") is False


# ── Aucun repli silencieux ─────────────────────────────────────────────────────

def test_missing_player_types_out_of_gym_raises():
    """`player_types` absent hors gym = bug → erreur explicite, jamais un défaut."""
    gs: Dict[str, Any] = {"gym_training_mode": False}
    with pytest.raises(ConfigurationError, match="player_types"):
        is_programmatic_owner(gs, "1")


def test_unknown_player_raises_explicitly():
    """Joueur absent de `player_types` → KeyError nommant le joueur."""
    gs = {"gym_training_mode": False, "player_types": {"1": "ai"}}
    with pytest.raises(KeyError, match="99"):
        is_programmatic_owner(gs, "99")


def test_missing_player_types_is_bypassed_in_gym():
    """En gym la table n'est pas lue : pas d'erreur même sans `player_types`.

    Verrouille l'ordre des tests dans le prédicat (le court-circuit gym précède le require_key).
    """
    assert is_programmatic_owner({"gym_training_mode": True}, "1") is True


# ── is_programmatic_defender : résolution du propriétaire de la cible ──────────

def test_defender_resolves_owner_through_units_cache():
    """Le défenseur délègue à la source unique après résolution du propriétaire de la cible."""
    gs = {
        "gym_training_mode": False,
        "player_types": {"1": "human", "2": "ai"},
        "units_cache": {"10": {"player": 1}, "20": {"player": 2}},
    }
    assert is_programmatic_defender(gs, "10") is False
    assert is_programmatic_defender(gs, "20") is True


def test_defender_in_gym_is_always_programmatic():
    """En gym, le défenseur est toujours auto — c'est ce qui débloque l'allocation FIGHT_CTX."""
    gs = {
        "gym_training_mode": True,
        "player_types": {"1": "human", "2": "human"},
        "units_cache": {"10": {"player": 1}},
    }
    assert is_programmatic_defender(gs, "10") is True


def test_defender_missing_target_raises():
    """Cible absente de `units_cache` = bug → erreur explicite, pas un défaut."""
    gs = {"gym_training_mode": True, "units_cache": {}}
    with pytest.raises(KeyError, match="404"):
        is_programmatic_defender(gs, "404")


def test_defender_missing_units_cache_raises():
    """`units_cache` absent = bug → erreur explicite."""
    with pytest.raises(ConfigurationError, match="units_cache"):
        is_programmatic_defender({"gym_training_mode": True}, "10")


# ── Test NÉGATIF : l'auto-activation ne bascule PAS sur le prédicat gym ────────

def test_shooting_auto_activation_is_not_gym_aware():
    """⚠️ R4 : `_is_ai_controlled_shooting_unit` lit `player_types`, JAMAIS le flag gym.

    Le brancher sur la bascule gym ferait auto-activer les unités du joueur entraîné pendant
    l'entraînement. Ce test rougit si quelqu'un « harmonise » les deux prédicats.
    """
    from engine.phase_handlers.shooting_handlers import _is_ai_controlled_shooting_unit

    gs = {"gym_training_mode": True, "player_types": {"1": "human", "2": "human"}}
    unit = {"player": 1}
    assert _is_ai_controlled_shooting_unit(gs, unit, {}) is False, (
        "l'auto-activation de tir est devenue gym-aware — cf. ⚠️ R4"
    )
