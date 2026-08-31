"""Règle 19.02 (Attacking attached units) — T du jet de blessure.

Contre une unité attachée contenant des figurines bodyguard, le jet de blessure utilise la PLUS
HAUTE T des **bodyguards**, jamais celle du leader/support (même s'il a une T différente). Si
l'unité ne contient que des figurines leader/support, on prend la plus haute T de celles-ci.

Verrou déplacé ici (et non dans un scénario) car aucun appariement LÉGAL du roster n'a
leader-T ≠ bodyguard-T : les captains menant une intercessor squad sont T4 comme elle. On
construit donc directement un squad hétérogène (bodyguard T4 + leader T5) au niveau moteur.

Contre-épreuve : si `_target_highest_bodyguard_toughness` prenait le max sur TOUTES les
figurines (bug), le premier test renverrait 5 → rouge.
"""
from __future__ import annotations

from engine.phase_handlers.shared_utils import _target_highest_bodyguard_toughness


def _gs(models: dict) -> dict:
    """game_state minimal exposant ce que lit la règle 19.02."""
    return {
        "models_cache": models,
        "squad_models": {"9": list(models.keys())},
        "unit_by_id": {"9": {"id": "9", "UNIT_RULES": []}},
    }


def test_wound_uses_bodyguard_toughness_not_leader():
    """Bodyguard T4 + leader T5 attaché → la T retenue est 4 (bodyguard), pas 5 (leader)."""
    gs = _gs({
        "9#0": {"role": None, "T": 4},      # bodyguard (Intercessor)
        "9#1": {"role": "leader", "T": 5},  # leader attaché, T supérieure
    })
    assert _target_highest_bodyguard_toughness(gs, "9") == 4


def test_highest_among_several_bodyguards():
    """Plusieurs bodyguards → plus haute T des bodyguards, leader toujours ignoré."""
    gs = _gs({
        "9#0": {"role": None, "T": 4},
        "9#1": {"role": "special_weapon", "T": 6},  # non-character = bodyguard
        "9#2": {"role": "leader", "T": 5},
    })
    assert _target_highest_bodyguard_toughness(gs, "9") == 6


def test_leader_only_unit_uses_leader_toughness():
    """Unité ne contenant que du leader/support → plus haute T de ceux-ci (fallback métier 19.02)."""
    gs = _gs({
        "9#0": {"role": "support", "T": 5},
        "9#1": {"role": "leader", "T": 6},
    })
    assert _target_highest_bodyguard_toughness(gs, "9") == 6
