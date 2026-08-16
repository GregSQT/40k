"""Verrou D4 : gain=0 pour toutes les capacites reproduit EXACTEMENT le comportement precedent.

Teste que `movement_weights()` avec gain=0 retourne le meme vecteur que `load_doctrine_weights`
(source de verite), et que les decisions de charge et de ciblage sont identiques.

T4 : mutation introduite → rouge, corrigee → vert.
"""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import pytest

import ai.bot_doctrines as doctrines
from ai.bot_doctrines import (
    AttritionBot,
    DecapitationBot,
    EndgameBot,
    AlphaStrikeBot,
    RacerBot,
    ScorerBot,
    late_game_state,
    load_doctrine_weights,
)


# ─── Profil neutre ─────────────────────────────────────────────────────────────

_NEUTRAL_PROFILE = {
    "late_game": 0.0,
    "preservation": 0.0,
    "persistence": 0.0,
    "focus_shared": False,
}

# Vecteurs de poids factices mais coherents par style.
_FAKE_WEIGHTS: Dict[str, tuple] = {
    "racer":              (1.3, 0.2, 0.0, 0.0, 4.0, 3.0),
    "endgame":            (0.9, -0.35, 0.6, 0.9, 1.0, 1.0),
    "endgame_push":       (1.5, 0.2, 0.3, 0.2, 4.0, 3.0),
    "alpha":              (0.8, 1.2, 0.0, 0.0, 1.0, 2.0),
    "attrition":          (0.7, 0.2, 0.8, 0.6, 1.5, 1.0),
    "attrition_withdraw": (0.3, -1.0, 0.0, 1.0, 0.0, 0.0),
    "decapitation":       (1.0, 0.6, 1.0, 0.2, 1.5, 2.0),
    "scorer":             (1.0, 0.3, 0.6, 0.4, 3.5, 2.5),
}


_ATTACKER: Dict[str, Any] = {"id": "u1", "player": 1}


def _game_state(*, turn: int = 1, limit: int = 5,
                vp1: float = 0.0, vp2: float = 0.0) -> Dict[str, Any]:
    return {
        "turn": turn,
        "config": {"game_rules": {"max_turns": limit}},
        "victory_points": {1: vp1, 2: vp2},
        "units": [],
        "units_cache": {},
        "objectives": None,
    }


def _patch_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise la config : gain=0 partout, poids factices."""
    monkeypatch.setattr(doctrines, "load_style_profile", lambda key: dict(_NEUTRAL_PROFILE))
    monkeypatch.setattr(doctrines, "load_doctrine_weights", lambda key: _FAKE_WEIGHTS[key])
    monkeypatch.setattr(doctrines, "_state_overrides_cfg", lambda: {
        "endgame": {"desperate_push": "endgame_push"},
        "attrition": {"preserve": "attrition_withdraw"},
    })
    monkeypatch.setattr(doctrines, "_late_game_transform_cfg", lambda: {
        "push_gain": 0.5, "protect_gain": 0.5,
    })
    # Pas d'ennemis, pas de pression → preservation=0, late_game=normal
    monkeypatch.setattr(doctrines, "_living_enemies_on_table", lambda unit, gs: [])
    monkeypatch.setattr(doctrines, "preservation_pressure", lambda unit, gs: 0.0)
    monkeypatch.setattr(doctrines, "is_unit_at_or_below_half_strength", lambda sid, gs: False)


def _patch_high_preservation(monkeypatch: pytest.MonkeyPatch) -> None:
    """preservation=1.0, pressure=0.5 => 0.5 >= 0.3 => _preservation_blocks_charge=True."""
    monkeypatch.setattr(doctrines, "load_style_profile", lambda key: {
        "late_game": 0.0,
        "preservation": 1.0,
        "persistence": 0.0,
        "focus_shared": False,
    })
    monkeypatch.setattr(doctrines, "preservation_pressure", lambda unit, gs: 0.5)


# ─── Identite de movement_weights a gain=0 ────────────────────────────────────

STYLES = [
    ("racer",        RacerBot),
    ("endgame",      EndgameBot),
    ("alpha",        AlphaStrikeBot),
    ("attrition",    AttritionBot),
    ("decapitation", DecapitationBot),
    ("scorer",       ScorerBot),
]


@pytest.mark.parametrize("key,BotClass", STYLES, ids=[s[0] for s in STYLES])
def test_movement_weights_gain_zero_equals_load_doctrine_weights(
    key: str, BotClass, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D4 : gain=0 rend exactement le vecteur brut de la config."""
    _patch_all(monkeypatch)
    bot = BotClass()
    unit = {"id": "u1", "player": 1}
    gs = _game_state()
    result = bot.movement_weights(unit, gs)
    expected = _FAKE_WEIGHTS[key]
    assert result == expected, (
        f"{key}: movement_weights(gain=0) attendu={expected}, obtenu={result}"
    )


# ─── Identite de wants_charge a gain=0 ────────────────────────────────────────

def test_base_wants_charge_follows_melee_beats_ranged(monkeypatch: pytest.MonkeyPatch) -> None:
    """A gain=0 : wants_charge() <=> melee > ranged (comportement precedent)."""
    _patch_all(monkeypatch)
    # melee > ranged => charge
    monkeypatch.setattr(doctrines, "_best_melee_and_ranged",
                        lambda unit, gs: (10.0, 5.0))
    bot = DecapitationBot()
    attacker = _ATTACKER
    gs = _game_state()
    assert bot.wants_charge(attacker, gs) is True


def test_base_wants_charge_no_charge_ranged_better(monkeypatch: pytest.MonkeyPatch) -> None:
    """A gain=0 : ranged > melee => pas de charge."""
    _patch_all(monkeypatch)
    monkeypatch.setattr(doctrines, "_best_melee_and_ranged",
                        lambda unit, gs: (3.0, 10.0))
    bot = DecapitationBot()
    attacker = _ATTACKER
    gs = _game_state()
    assert bot.wants_charge(attacker, gs) is False


def test_base_wants_charge_preservation_blocks_when_pressure_high(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_preservation_blocks_charge coupe la charge quand pressure * g_pres >= seuil."""
    _patch_all(monkeypatch)
    # melee > ranged => chargerait normalement
    monkeypatch.setattr(doctrines, "_best_melee_and_ranged",
                        lambda unit, gs: (10.0, 5.0))
    _patch_high_preservation(monkeypatch)
    bot = DecapitationBot()
    attacker = _ATTACKER
    gs = _game_state()
    assert bot.wants_charge(attacker, gs) is False


def test_attrition_wants_charge_is_preserving_blocks_before_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AttritionBot._is_preserving bloque la charge meme quand la base l'autoriserait."""
    _patch_all(monkeypatch)
    monkeypatch.setattr(doctrines, "_best_melee_and_ranged",
                        lambda unit, gs: (10.0, 5.0))
    # Unité entamée et au-dessus de la valeur moyenne => _withdrawing=True => bloque
    monkeypatch.setattr(doctrines, "is_unit_at_or_below_half_strength",
                        lambda sid, gs: True)
    bot = AttritionBot()
    attacker = {"id": "u1", "player": 1, "VALUE": 100.0}
    gs = _game_state()
    # units=[] => others=[] => _withdrawing=True (derniere escouade)
    assert bot.wants_charge(attacker, gs) is False


def test_attrition_wants_charge_calls_base_preservation_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AttritionBot._is_preserving=False => super() => _preservation_blocks_charge coupe.

    Verifie que AttritionBot.wants_charge appelle bien super() et ne court-circuite pas
    _preservation_blocks_charge. Sans le fix (return _melee_beats_ranged), ce test est ROUGE.
    """
    _patch_all(monkeypatch)
    # melee > ranged => chargerait si le fix est absent
    monkeypatch.setattr(doctrines, "_best_melee_and_ranged",
                        lambda unit, gs: (10.0, 5.0))
    # _is_preserving=False : unité non entamée
    monkeypatch.setattr(doctrines, "is_unit_at_or_below_half_strength",
                        lambda sid, gs: False)
    _patch_high_preservation(monkeypatch)
    bot = AttritionBot()
    attacker = _ATTACKER
    gs = _game_state()
    assert bot.wants_charge(attacker, gs) is False


# ─── Verrou T4 : mutation revele l'identite ────────────────────────────────────

def test_mutation_verrou_d4(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preuve rouge/vert : remplacer gain=0 par gain=1.0 casse l'identite.

    Protocole T4 :
    1. Baseline : gain=0 => weights == expected [vert attendu]
    2. Mutant  : gain=1.0 => weights != expected [rouge attendu]
    3. Retabli : gain=0 => weights == expected [vert retabli]
    """
    # Baseline
    _patch_all(monkeypatch)
    bot = RacerBot()
    unit = {"id": "u1", "player": 1}
    gs = _game_state(turn=3, limit=5, vp1=0.0, vp2=0.0)
    baseline = bot.movement_weights(unit, gs)
    assert baseline == _FAKE_WEIGHTS["racer"], "Baseline D4 doit etre identique"

    # Mutant : late_game_g()=1.0, etat desperate_push
    monkeypatch.setattr(doctrines, "load_style_profile", lambda key: {
        "late_game": 1.0, "preservation": 0.0,
        "persistence": 0.0, "focus_shared": False,
    })
    mutant = bot.movement_weights(unit, gs)
    assert mutant != _FAKE_WEIGHTS["racer"], (
        "Mutant (gain=1.0) DOIT produire un vecteur different — "
        "sinon D4 ne distingue pas gain=0 de gain≠0"
    )

    # Retabli
    monkeypatch.setattr(doctrines, "load_style_profile", lambda key: dict(_NEUTRAL_PROFILE))
    restored = bot.movement_weights(unit, gs)
    assert restored == _FAKE_WEIGHTS["racer"], "D4 retabli : identique a baseline"
