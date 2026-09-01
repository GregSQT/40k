"""Dakkablitz (weapon_attacks_bonus_vs_keyword) : +6 A au Blitzcannon vs non-MONSTER/VEHICLE.

Avant le fix, `max_allowed_shots` n'incluait pas ce bonus : cap = NB seulement.
Blitzcannon : NB=8, bonus=6 vs non-MONSTER/VEHICLE → cap correct = 14 par tireur.
Sans le fix : cap=8 → 6 erreurs sur 14 tirs légitimes (la différence entre 14 et 8).

Scénarios :
  1. BigMekDakkarig (1 socle) tire 14 coups sur AssaultIntercessor (non-M/V) → 0 erreur.
  2. Même avec 15 coups → 1 erreur (témoin inverse).
  3. BigMekDakkarig tire 8 coups sur DreadnoughtBallistus (VEHICLE) → bonus n'applique pas →
     cap=8 → 0 erreur.
  4. Idem avec 9 coups → 1 erreur (témoin inverse VEHICLE).
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

SHOOTER_POS = (50, 50)
TARGET_POS = (80, 80)
S = f"({SHOOTER_POS[0]},{SHOOTER_POS[1]})"
T = f"({TARGET_POS[0]},{TARGET_POS[1]})"

_UNITS_NON_MV = (
    "[10:00:00] Unit 1 (BigMekDakkarig) P1: Starting position (-1,-1), HP_MAX=4 base=round/40"
    " [MODEL_TYPES: 1#0=BigMekDakkarig]\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
)

_UNITS_VEHICLE = (
    "[10:00:00] Unit 1 (BigMekDakkarig) P1: Starting position (-1,-1), HP_MAX=4 base=round/40"
    " [MODEL_TYPES: 1#0=BigMekDakkarig]\n"
    "[10:00:00] Unit 101 (DreadnoughtBallistus) P2: Starting position (-1,-1), HP_MAX=10 base=round/65\n"
)

_SETUP_TMPL = (
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{S} DEPLOYED from (-1,-1) to {S}"
    " [R:+0.0] [MODELS: 1#0@({sx},{sy},z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{T} DEPLOYED from (-1,-1) to {T}"
    " [R:+0.0] [MODELS: 101#0@({tx},{ty},z0)] [SUCCESS]\n"
    "[10:00:01] T1 EFFECTS: P1 none | P2 none\n"
)

_SETUP = _SETUP_TMPL.format(
    S=S, T=T,
    sx=SHOOTER_POS[0], sy=SHOOTER_POS[1],
    tx=TARGET_POS[0], ty=TARGET_POS[1],
)


def _tir(seconde: int, coup: int) -> str:
    return (
        f"[10:00:{seconde:02d}] E1 T1 P1 SHOOT : Unit 1{S}"
        f" SHOT Unit 101{T} with [Blitzcannon]"
        f" - Hit {coup}(4+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP [R:+0.0]"
        f" [MODELS: 1#0@({SHOOTER_POS[0]},{SHOOTER_POS[1]},z0)]"
        f" [SHOOTER_MODELS: 1#0] [SUCCESS]\n"
    )


def _stats(tmp_path, n_shots: int, units_header: str) -> dict:
    import ai.analyzer as an

    shots = "".join(_tir(i + 2, i + 1) for i in range(n_shots))
    log = tmp_path / "step.log"
    log.write_text(
        entete_step_log(
            _SETUP + shots,
            units=units_header,
            ez_vertical_inches=None,
        )
    )
    return an.parse_step_log(str(log))


def test_14_tirs_blitzcannon_non_mv_pas_d_erreur(tmp_path):
    """1 tireur × (8 NB + 6 Dakkablitz) = 14 tirs max vs non-M/V → 0 erreur."""
    stats = _stats(tmp_path, 14, _UNITS_NON_MV)
    assert stats["shoot_over_rng_nb"][1] == 0, (
        f"Attendu 0 erreur shoot_over_rng_nb P1, obtenu {stats['shoot_over_rng_nb'][1]}"
    )


def test_15_tirs_blitzcannon_non_mv_declenche_erreur(tmp_path):
    """Témoin inverse : 15 tirs dépasse le plafond → 1 erreur."""
    stats = _stats(tmp_path, 15, _UNITS_NON_MV)
    assert stats["shoot_over_rng_nb"][1] == 1, (
        f"Attendu 1 erreur shoot_over_rng_nb P1, obtenu {stats['shoot_over_rng_nb'][1]}"
    )


def test_8_tirs_blitzcannon_vehicle_pas_d_erreur(tmp_path):
    """Cible VEHICLE : Dakkablitz ne s'applique pas, cap = NB = 8 → 0 erreur sur 8 tirs."""
    stats = _stats(tmp_path, 8, _UNITS_VEHICLE)
    assert stats["shoot_over_rng_nb"][1] == 0, (
        f"Attendu 0 erreur shoot_over_rng_nb P1 (VEHICLE, cap=8), "
        f"obtenu {stats['shoot_over_rng_nb'][1]}"
    )


def test_9_tirs_blitzcannon_vehicle_declenche_erreur(tmp_path):
    """Cible VEHICLE : cap = NB = 8 → 9 tirs déclenche 1 erreur."""
    stats = _stats(tmp_path, 9, _UNITS_VEHICLE)
    assert stats["shoot_over_rng_nb"][1] == 1, (
        f"Attendu 1 erreur shoot_over_rng_nb P1 (VEHICLE), "
        f"obtenu {stats['shoot_over_rng_nb'][1]}"
    )
