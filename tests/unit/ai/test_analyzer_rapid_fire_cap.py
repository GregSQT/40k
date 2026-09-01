"""Verrou — surcharge_atk tir : RAPID FIRE à demi-portée sans [RAPID FIRE:X] dans le log.

Le token [RAPID FIRE:X] a été supprimé du log moteur le 2026-07-29 (modèle pool).
Sans lui, `rapid_fire_bonus_for_this_shot` restait 0, et `rapid_fire_value_squad` n'était jamais
ajouté au plafond → toute activation RAPID FIRE à demi-portée produisait un faux
« shoot_over_rng_nb ». Fix : toujours additionner rapid_fire_value_squad dans max_allowed_shots.

Cycle rouge→vert : réintroduire la conditionnelle supprimée dans shoot_handler.py L621 fait
passer test_rapid_fire_legal_shots_not_flagged en rouge (2 faux positifs au lieu de 0).
"""
from __future__ import annotations

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
MAX_LEGAL = PER_MODEL_CAP + RF_CAP    # 6  — plafond correct avec RF

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


def _shot(i: int) -> str:
    """Une ligne de tir sans token [RAPID FIRE:X] — format post-2026-07-29."""
    ts = f"[10:00:{2 + i:02d}]"
    return (
        f"{ts} E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [{WEAPON}]"
        f" - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:0HP {_MODELS} {_SHOOTERS}"
        " [R:+0.0] [SUCCESS]\n"
    )


def _stats(tmp_path, n_shots: int):
    import ai.analyzer as an
    log = tmp_path / "step.log"
    log.write_text(_HEADER + "".join(_shot(i) for i in range(n_shots)) + EPISODE_TAIL)
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


def test_rapid_fire_legal_shots_not_flagged(tmp_path):
    """MAX_LEGAL tirs d'un groupe RF sans token [RAPID FIRE:X] → 0 violation (§1.7).

    Avant fix : rapid_fire_bonus_for_this_shot=0 → cap=4 → 2 faux positifs (shots 5 et 6).
    Après fix  : cap=4+2=6 → 0 violation.
    """
    stats = _stats(tmp_path, MAX_LEGAL)
    assert stats["shoot_over_rng_nb"][1] == 0, stats["first_error_lines"]["shoot_over_rng_nb"][1]


def test_beyond_rf_cap_is_still_caught(tmp_path):
    """Anti-vert-vacant : un vrai dépassement au-delà de NB+RF est toujours compté."""
    stats = _stats(tmp_path, MAX_LEGAL + 2)
    assert stats["shoot_over_rng_nb"][1] == 2
