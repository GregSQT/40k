"""Verrou — surcharge_atk tir : cap RAPID FIRE conditionnelle à la présence du token.

[RAPID FIRE:X] est émis par le moteur sur TOUTES les lignes d'un groupe quand la cible
est à demi-portée, et ABSENT sinon. Le plafond doit donc inclure RF_CAP uniquement quand
le token est présent — symétrique exact de [BLAST] via additive_rule_extra_dice.

Cycle rouge→vert :
  - test_rapid_fire_cap[half-range-legal]  : remettre la cap inconditionnelle → 2 faux positifs.
  - test_rapid_fire_cap[long-range-over-nb]: remettre la cap inconditionnelle → violation manquée.
"""
from __future__ import annotations

import pytest

from tests.unit.ai._fabriques import entete_step_log, EPISODE_TAIL

SQUAD_TYPE = "Boyz"
WEAPON = "Shoota"
NB = 2          # NB par figurine (Shoota)
RF = 1          # RAPID_FIRE:1
N_SHOOTERS = 2

SHOOTER = (50, 50)
TARGET = (50, 56)
OBJECTIVES = ";".join(f"(200,{r})" for r in range(150, 156))

S = f"({SHOOTER[0]},{SHOOTER[1]})"
T = f"({TARGET[0]},{TARGET[1]})"

PER_MODEL_CAP = NB * N_SHOOTERS       # 4
RF_CAP = RF * N_SHOOTERS              # 2
MAX_LEGAL_HALF = PER_MODEL_CAP + RF_CAP    # 6 — plafond demi-portée (RF actif)
MAX_LEGAL_LONG = PER_MODEL_CAP             # 4 — plafond longue portée (RF inactif)

_MODELS = (
    f"[MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)"
    f" 1#1@({SHOOTER[0]},{SHOOTER[1] + 1},z0)]"
)
_SHOOTERS = "[SHOOTER_MODELS: 1#0 1#1]"

_HEADER = entete_step_log(
    units=(
        f"[10:00:00] Unit 1 ({SQUAD_TYPE}) P1: Starting position {S}, HP_MAX=9 base=round/6"
        f" [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)"
        f" 1#1@({SHOOTER[0]},{SHOOTER[1] + 1},z0)]"
        f" [MODEL_TYPES: 1#0={SQUAD_TYPE} 1#1={SQUAD_TYPE}]\n"
        f"[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position {T},"
        f" HP_MAX=2 base=round/6"
        f" [MODELS: 101#0@({TARGET[0]},{TARGET[1]},z0)]\n"
    ),
    rosters="scale=5 AGENT_PLAYER=1 AGENT=orks (ref) OPPONENT=sm (ref)",
    objectives=OBJECTIVES,
)


def _shot(i: int, *, with_rf_token: bool) -> str:
    """Ligne de tir avec ou sans [RAPID FIRE:X] selon que la cible est à demi-portée."""
    ts = f"[10:00:{2 + i:02d}]"
    rf_tag = f" [RAPID FIRE:{RF}]" if with_rf_token else ""
    return (
        f"{ts} E1 T1 P1 SHOOT : Unit 1{S} SHOT{rf_tag} Unit 101{T} with [{WEAPON}]"
        f" - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:0HP {_MODELS} {_SHOOTERS}"
        " [R:+0.0] [SUCCESS]\n"
    )


def _stats(tmp_path, n_shots: int, *, with_rf_token: bool):
    import ai.analyzer as an
    log = tmp_path / "step.log"
    log.write_text(
        _HEADER
        + "".join(_shot(i, with_rf_token=with_rf_token) for i in range(n_shots))
        + EPISODE_TAIL
    )
    return an.parse_step_log(str(log))


def test_registry_premise_boyz_shoota_has_rapid_fire():
    """Prémisse : la Shoota a bien RAPID_FIRE:1, sinon le test ne prouve rien."""
    from ai.unit_registry import UnitRegistry
    ur = UnitRegistry()
    w = next(
        (w for w in ur.units[SQUAD_TYPE]["RNG_WEAPONS"] if w["display_name"] == WEAPON),
        None,
    )
    assert w is not None, f"Arme '{WEAPON}' introuvable pour {SQUAD_TYPE}"
    assert w["NB"] == NB, w
    rf_rules = [r for r in w["WEAPON_RULES"] if "RAPID_FIRE" in r]
    assert len(rf_rules) == 1, rf_rules
    assert rf_rules[0] == f"RAPID_FIRE:{RF}", rf_rules[0]


@pytest.mark.parametrize("with_rf_token,n_shots,expected", [
    pytest.param(True,  MAX_LEGAL_HALF,     0, id="half-range-legal"),
    pytest.param(True,  MAX_LEGAL_HALF + 2, 2, id="half-range-over-cap"),
    pytest.param(False, MAX_LEGAL_LONG + 1, 1, id="long-range-over-nb"),
    pytest.param(False, MAX_LEGAL_LONG,     0, id="long-range-legal"),
])
def test_rapid_fire_cap(tmp_path, with_rf_token, n_shots, expected):
    stats = _stats(tmp_path, n_shots, with_rf_token=with_rf_token)
    assert stats["shoot_over_rng_nb"][1] == expected, (
        stats["first_error_lines"]["shoot_over_rng_nb"][1]
    )
