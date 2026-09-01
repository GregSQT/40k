"""Hail of Bolts (weapon_attacks_bonus_vs_designated_target) : +2A au Bolt Rifle.

Avant le fix, `max_allowed_shots` n'incluait pas ce bonus : cap par tireur = NB seulement.
Bolt Rifle : NB=2, bonus=2, donc cap correct = 4. Sans le fix, cap=2 → 2 erreurs par tireur
sur 4 tirs légitimes.

Fix : `atk_bonus_by_weapon` dans `unit_attack_limits[Intercessor]`, inclus dans le cap.

Scénario :
  - P1 : 2 Intercessors (tireurs), 1 Bolt Rifle chacun (NB=2), Hail of Bolts +2A
  - P2 : 1 AssaultIntercessor (cible)
  - 2 groupes indépendants (par tireur) : 4 coups chacun, tous sur la même cible désignée
  - Attendu : 0 erreur shoot_over_rng_nb

Contrainte test : [MODEL_TYPES:] doit être présent dans l'entête pour que per_model_attack_cap
résolve les datasheets par figurine (pas le repli escouade). Sans lui, atk_bonus_squad = 0.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

SHOOTER_POS = (50, 50)
TARGET_POS = (80, 80)
S = f"({SHOOTER_POS[0]},{SHOOTER_POS[1]})"
T = f"({TARGET_POS[0]},{TARGET_POS[1]})"

_UNITS = (
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6"
    " [MODEL_TYPES: 1#0=Intercessor 1#1=Intercessor]\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
)

_SETUP = (
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{S} DEPLOYED from (-1,-1) to {S}"
    f" [R:+0.0] [MODELS: 1#0@({SHOOTER_POS[0]},{SHOOTER_POS[1]},z0)"
    f" 1#1@({SHOOTER_POS[0]},{SHOOTER_POS[1]},z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{T} DEPLOYED from (-1,-1) to {T}"
    f" [R:+0.0] [MODELS: 101#0@({TARGET_POS[0]},{TARGET_POS[1]},z0)] [SUCCESS]\n"
    # Oath of Moment de P1 posé sur une TROISIÈME unité (999), jamais sur la cible tirée.
    # « Cible désignée » = la cible déclarée du tir, pas l'Oath : le bonus doit tomber quand
    # même. C'est le verrou de la régression du 2026-09-02 (gate `oath_target` → 4879 faux
    # `shoot_over_rng_nb` sur le run de 300 épisodes).
    "[10:00:01] T1 EFFECTS: P1 oath_target=999 | P2 none\n"
)


def _tir(seconde: int, coup: int, shooters: str) -> str:
    """Un coup du groupe de tir Intercessor → AssaultIntercessor."""
    return (
        f"[10:00:{seconde:02d}] E1 T1 P1 SHOOT : Unit 1{S}"
        f" SHOT Unit 101{T} with [Bolt Rifle]"
        f" - Hit {coup}(3+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP [R:+0.0]"
        f" [MODELS: 1#0@({SHOOTER_POS[0]},{SHOOTER_POS[1]},z0)"
        f" 1#1@({SHOOTER_POS[0]},{SHOOTER_POS[1]},z0)]"
        f" [SHOOTER_MODELS: {shooters}] [SUCCESS]\n"
    )


def _stats(tmp_path, n_shots: int) -> dict:
    """Parse un groupe de n_shots coups, tous sur la même cible désignée.

    Les premiers 4 coups = modèle 1#0 ; les suivants = modèle 1#1.
    Cap par tireur = NB(2) + Hail of Bolts(2) = 4.
    """
    import ai.analyzer as an

    shots = ""
    for i in range(n_shots):
        mid = "1#0" if i < 4 else "1#1"
        shots += _tir(i + 2, i + 1, mid)

    log = tmp_path / "step.log"
    log.write_text(
        entete_step_log(
            _SETUP + shots,
            units=_UNITS,
            ez_vertical_inches=None,
        )
    )
    return an.parse_step_log(str(log))


def test_bonus_applique_meme_si_la_cible_n_est_pas_l_oath_target(tmp_path):
    """VERROU : l'Oath de P1 vise 999, le tir vise 101 — le bonus tombe quand même.

    Le moteur (`shared_utils.py`) n'applique AUCUN filtre : « la cible de l intent EST la
    cible designee ». Gater le bonus sur `oath_target` avait fait passer le plafond de 4 à 2
    par figurine, donc 4 faux positifs sur ces 8 tirs légitimes.
    """
    stats = _stats(tmp_path, 8)
    assert stats["shoot_over_rng_nb"][1] == 0, (
        "Le bonus Hail of Bolts doit s'appliquer quelle que soit la cible de l'Oath ; "
        f"obtenu {stats['shoot_over_rng_nb'][1]} erreur(s)"
    )


def test_8_tirs_bolt_rifle_hail_of_bolts_pas_d_erreur(tmp_path):
    """2 tireurs × (2 NB + 2 bonus Hail of Bolts) = 8 tirs max → 0 erreur."""
    stats = _stats(tmp_path, 8)
    assert stats["shoot_over_rng_nb"][1] == 0, (
        f"Attendu 0 erreur shoot_over_rng_nb P1, obtenu {stats['shoot_over_rng_nb'][1]}"
    )


def test_9_tirs_bolt_rifle_declenche_erreur(tmp_path):
    """Témoin inverse : 9 tirs dépasse le plafond (1#1 tire 5 fois) → 1 erreur."""
    stats = _stats(tmp_path, 9)
    assert stats["shoot_over_rng_nb"][1] == 1, (
        f"Attendu 1 erreur shoot_over_rng_nb P1, obtenu {stats['shoot_over_rng_nb'][1]}"
    )
