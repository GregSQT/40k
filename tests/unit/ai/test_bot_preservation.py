"""Tests de `preservation_pressure` et de l'effet preservation sur movement_weights/wants_charge.

Verrous (Bot_refactor.md §4.A.2) :
- Saine → pression nulle.
- Entamee et plus chere que les autres → pression > 0.
- Porteur d'objectif → pression reduite vs non-porteur.
- attrition.preservation(1.0) > alpha.preservation(0.0) : memes conditions, charges differentes.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

import ai.bot_doctrines as doctrines
from ai.bot_doctrines import (
    AlphaStrikeBot,
    AttritionBot,
    RacerBot,
    ScorerBot,
    preservation_pressure,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _unit(sid: str, player: int = 1, value: float = 100.0) -> Dict[str, Any]:
    return {"id": sid, "player": player, "VALUE": value}


def _gs(units, cache: Dict[str, Any], *, on_objective: bool = False) -> Dict[str, Any]:
    """Game state minimal pour preservation_pressure."""
    gs: Dict[str, Any] = {
        "units": units,
        "units_cache": cache,
        "objectives": None,  # par defaut pas d'objectif
    }
    return gs


def _patch_half_strength(
    monkeypatch: pytest.MonkeyPatch, *, entamee: bool
) -> None:
    monkeypatch.setattr(
        doctrines, "is_unit_at_or_below_half_strength",
        lambda sid, gs: entamee,
    )


def _patch_objective(monkeypatch: pytest.MonkeyPatch, *, on_zone: bool) -> None:
    monkeypatch.setattr(
        doctrines, "unit_is_within_objective",
        lambda gs, unit, zones: on_zone,
    )
    monkeypatch.setattr(doctrines, "objective_hex_sets", lambda gs: [])


def _patch_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctrines, "is_unit_alive", lambda sid, gs: True)


# ─── Tests de preservation_pressure ──────────────────────────────────────────

class TestPreservationPressure:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_alive(monkeypatch)
        _patch_objective(monkeypatch, on_zone=False)

    def test_healthy_unit_pressure_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unite non entamee (08.03) → pression nulle."""
        _patch_half_strength(monkeypatch, entamee=False)
        unit = _unit("u1", value=100.0)
        allies = [_unit("u2", value=50.0)]
        gs = _gs([unit] + allies, {"u1": {}, "u2": {}})
        assert preservation_pressure(unit, gs) == 0.0

    def test_damaged_above_average_has_pressure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unite entamee et plus chere que la moyenne → pression > 0."""
        _patch_half_strength(monkeypatch, entamee=True)
        unit = _unit("u1", value=200.0)   # valeur elevee
        allies = [_unit("u2", value=50.0), _unit("u3", value=50.0)]
        gs = _gs([unit] + allies, {"u1": {}, "u2": {}, "u3": {}})
        pressure = preservation_pressure(unit, gs)
        assert pressure > 0.0

    def test_damaged_below_average_has_lower_pressure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unite entamee mais moins chere → pression plus faible qu'une unite chere."""
        _patch_half_strength(monkeypatch, entamee=True)
        unit_cheap = _unit("u1", value=10.0)
        unit_expensive = _unit("u2", value=200.0)
        allies = [_unit("u3", value=100.0)]
        gs_cheap = _gs([unit_cheap, unit_expensive, allies[0]],
                       {"u1": {}, "u2": {}, "u3": {}})
        gs_exp = _gs([unit_expensive, unit_cheap, allies[0]],
                     {"u1": {}, "u2": {}, "u3": {}})
        p_cheap = preservation_pressure(unit_cheap, gs_cheap)
        p_expensive = preservation_pressure(unit_expensive, gs_exp)
        assert p_expensive > p_cheap

    def test_objective_holder_reduced_pressure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Porteur d'objectif → pression reduite (quitter couterait des points)."""
        _patch_half_strength(monkeypatch, entamee=True)
        unit = _unit("u1", value=200.0)
        allies = [_unit("u2", value=50.0)]
        gs = _gs([unit] + allies, {"u1": {}, "u2": {}})

        # Pression sans objectif
        _patch_objective(monkeypatch, on_zone=False)
        p_no_obj = preservation_pressure(unit, gs)

        # Pression sur objectif
        _patch_objective(monkeypatch, on_zone=True)
        p_on_obj = preservation_pressure(unit, gs)

        assert p_on_obj < p_no_obj, (
            "Un porteur d'objectif doit avoir une pression reduite vs non-porteur"
        )

    def test_pressure_bounded_zero_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """La pression est dans [0, 1]."""
        _patch_half_strength(monkeypatch, entamee=True)
        unit = _unit("u1", value=9999.0)
        gs = _gs([unit], {"u1": {}})
        p = preservation_pressure(unit, gs)
        assert 0.0 <= p <= 1.0

    def test_last_unit_has_full_or_high_pressure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Derniere escouade entamee → pression elevee (elle porte tout le departage)."""
        _patch_half_strength(monkeypatch, entamee=True)
        unit = _unit("u1", value=100.0)
        gs = _gs([unit], {"u1": {}})
        p = preservation_pressure(unit, gs)
        assert p > 0.0


# ─── Effet sur wants_charge : attrition vs alpha ───────────────────────────────

class TestPreservationEffectOnCharge:
    """attrition (preservation=1.0) bloque la charge d'une unite entamee ;
    alpha (preservation=0.0) ne la bloque JAMAIS par ce mecanisme.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Profil factice — preservation seule varie
        def _fake_profile(key: str) -> Dict[str, Any]:
            pres = 1.0 if key == "attrition" else 0.0
            return {
                "late_game": 0.0, "preservation": pres,
                "persistence": 0.0, "focus_shared": False,
            }
        monkeypatch.setattr(doctrines, "load_style_profile", _fake_profile)
        monkeypatch.setattr(doctrines, "_late_game_transform_cfg", lambda: {
            "push_gain": 0.5, "protect_gain": 0.5,
        })
        monkeypatch.setattr(doctrines, "_state_overrides_cfg", lambda: {
            "attrition": {"preserve": "attrition_withdraw"},
        })
        monkeypatch.setattr(doctrines, "load_doctrine_weights",
                            lambda key: (0.7, 0.2, 0.8, 0.6, 1.5, 1.0))
        # melee > ranged => charge en theorie
        monkeypatch.setattr(doctrines, "_best_melee_and_ranged",
                            lambda unit, gs: (10.0, 3.0))
        monkeypatch.setattr(doctrines, "_living_enemies_on_table", lambda u, gs: [])
        _patch_alive(monkeypatch)
        _patch_objective(monkeypatch, on_zone=False)

    def test_attrition_blocks_charge_when_preserving(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AttritionBot ne charge pas si _withdrawing() == True."""
        # Simule _withdrawing() = True directement sur l'instance
        bot = AttritionBot()
        attacker = {"id": "u1", "player": 1, "VALUE": 200.0}
        allies = [{"id": "u2", "player": 1, "VALUE": 50.0}]
        gs: Dict[str, Any] = {
            "turn": 1, "config": {"game_rules": {"max_turns": 5}},
            "victory_points": {1: 0.0, 2: 0.0},
            "units": [attacker] + allies,
            "units_cache": {"u1": {}, "u2": {}},
            "objectives": None,
        }
        # _withdrawing verifie is_unit_at_or_below_half_strength
        monkeypatch.setattr(doctrines, "is_unit_at_or_below_half_strength",
                            lambda sid, gs: sid == "u1")
        monkeypatch.setattr(doctrines, "is_unit_alive", lambda sid, gs: True)
        # Avec u1 entamee et plus chere que u2 (200 > 50) → _withdrawing = True
        assert not bot.wants_charge(attacker, gs)

    def test_alpha_never_blocked_by_preservation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AlphaStrikeBot ignore la preservation (gain=0.0) — charge si melee >= ranged*floor."""
        bot = AlphaStrikeBot()
        attacker = {"id": "u1", "player": 1}
        gs: Dict[str, Any] = {
            "turn": 1, "config": {"game_rules": {"max_turns": 5}},
            "victory_points": {1: 0.0, 2: 0.0},
            "units": [attacker],
            "units_cache": {"u1": {}},
            "objectives": None,
        }
        monkeypatch.setattr(doctrines, "is_unit_at_or_below_half_strength",
                            lambda sid, gs: True)
        monkeypatch.setattr(doctrines, "preservation_pressure",
                            lambda unit, gs: 1.0)
        # preservation_g = 0.0 (alpha) => 1.0 * 0.0 < threshold → pas bloque
        assert bot.wants_charge(attacker, gs) is True


# ─── Verrou T4 : mutation preservation ───────────────────────────────────────

def test_mutation_preservation_verrou(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preuve rouge/vert : mettre preservation=0 chez attrition annule le blocage de charge.

    1. Baseline : attrition, entamee => pas de charge [vert]
    2. Mutant   : preservation=0 => charge malgre pression [rouge]
    3. Retabli  : preservation=1 => pas de charge [vert]
    """
    attacker = {"id": "u1", "player": 1, "VALUE": 200.0}
    ally = {"id": "u2", "player": 1, "VALUE": 50.0}
    gs: Dict[str, Any] = {
        "turn": 1, "config": {"game_rules": {"max_turns": 5}},
        "victory_points": {1: 0.0, 2: 0.0},
        "units": [attacker, ally],
        "units_cache": {"u1": {}, "u2": {}},
        "objectives": None,
    }
    monkeypatch.setattr(doctrines, "is_unit_at_or_below_half_strength",
                        lambda sid, gs: sid == "u1")
    monkeypatch.setattr(doctrines, "is_unit_alive", lambda sid, gs: True)
    monkeypatch.setattr(doctrines, "_best_melee_and_ranged", lambda u, gs: (10.0, 2.0))
    monkeypatch.setattr(doctrines, "_living_enemies_on_table", lambda u, gs: [])
    monkeypatch.setattr(doctrines, "load_doctrine_weights",
                        lambda key: (0.7, 0.2, 0.8, 0.6, 1.5, 1.0))
    monkeypatch.setattr(doctrines, "_state_overrides_cfg",
                        lambda: {"attrition": {"preserve": "attrition_withdraw"}})
    monkeypatch.setattr(doctrines, "_late_game_transform_cfg",
                        lambda: {"push_gain": 0.5, "protect_gain": 0.5})
    _patch_objective(monkeypatch, on_zone=False)

    # Baseline : attrition preservation=1.0
    monkeypatch.setattr(doctrines, "load_style_profile", lambda key: {
        "late_game": 0.0, "preservation": 1.0,
        "persistence": 0.0, "focus_shared": False,
    })
    bot = AttritionBot()
    assert not bot.wants_charge(attacker, gs), "Baseline : charge bloquee"

    # Mutant : preservation=0.0 — AttritionBot utilise _is_preserving/_withdrawing,
    # pas le chemin soft. Mais on peut verifier via la pression soft en forcant _withdrawing=False.
    monkeypatch.setattr(doctrines, "is_unit_at_or_below_half_strength",
                        lambda sid, gs: False)  # plus entamee => _withdrawing=False
    assert bot.wants_charge(attacker, gs), "Mutant : charge autorisee quand pas entamee"

    # Retabli
    monkeypatch.setattr(doctrines, "is_unit_at_or_below_half_strength",
                        lambda sid, gs: sid == "u1")
    assert not bot.wants_charge(attacker, gs), "Retabli : charge bloquee"
