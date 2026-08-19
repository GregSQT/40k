"""[TARGET_DECL:N] corrige §1.4 fight_over_cc_nb quand l'effectif de la cible est reconstruit.

Régression verrouillée (2026-08-19).

MÉCANISME. Sans [TARGET_DECL:N] (anciens logs), l'effectif de la cible au SelectTargets step
est reconstruit depuis unit_model_hp. Fix 2 peut sous-estimer cet effectif après purge des
entrées périmées : l'analyzer tombe en-dessous d'un palier CLEAVE (5, 10, 15…) et compute
un cc_nb trop bas, condamnant des attaques légales.

FIX. [TARGET_DECL:N] porte l'effectif moteur exact. Les logs sans token déclarent les
potentiels surplus non-jugeables (fight_over_cc_nb_unverifiable) plutôt que violations.

CE QUE CE TEST CONSTRUIT. Cible 4 socles deployée (positions_by_model[101]={#0..#3}).
Token [TARGET_DECL:5] indique que le moteur en voyait 5. Kustom Choppa NB=6, [CLEAVE:1].

Plafond selon effectif :
  effectif=5  → CLEAVE = 5//5 = 1 → cc_nb = 6+1 = 7  (voie [TARGET_DECL:5])
  effectif=4  → CLEAVE = 4//5 = 0 → cc_nb = 6+0 = 6  (voie reconstituée)

7 attaques :
  AVEC [TARGET_DECL:5]  : 7 ≤ 7 → 0 violation, 0 unverifiable.
  SANS [TARGET_DECL:N]  : 7 > 6 → 0 violation certifiée, 1 non-jugeable.

Verrou prouvé par mutation : retirer _alive_override de freeze_select_targets → avec token,
alive devient 4 (reconstruit) → cc_nb=6 → 7>6 → fight_over_cc_nb=1 → ROUGE.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

ATTACKER = (10, 10)
TARGET_ANCHOR = (10, 11)

_M0 = (10, 11)
_M1 = (10, 12)
_M2 = (11, 11)
_M3 = ( 9, 11)
# 4 socles seulement dans [MODELS:] (le 5e est absent de positions_by_model).
_ALL_101 = (
    f"101#0@({_M0[0]},{_M0[1]},z0) 101#1@({_M1[0]},{_M1[1]},z0) "
    f"101#2@({_M2[0]},{_M2[1]},z0) 101#3@({_M3[0]},{_M3[1]},z0)"
)

A = f"({ATTACKER[0]},{ATTACKER[1]})"
T = f"({TARGET_ANCHOR[0]},{TARGET_ANCHOR[1]})"
OBJECTIVES = ";".join(f"(60,{r})" for r in range(40, 46))

_UNITS = (
    "[10:00:00] Unit 1 (BoyzNobKustomShoota) P1: Starting position (-1,-1), HP_MAX=5 "
    "base=round/1\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=1 "
    "base=round/1\n"
)

def _make_log(body: str) -> str:
    return entete_step_log(
        body,
        inches_to_subhex=1,
        board="cols=44 rows=60",
        hex_radius="13.9",
        margin=5,
        objectives=OBJECTIVES,
        metric_engagement="hex",
        metric_ranged="hex",
        log_grammar=2,
        units=_UNITS,
    )

_DEPLOYMENT = (
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{A} DEPLOYED from (-1,-1) to {A} [R:+0.0] "
    f"[MODELS: 1#0@({ATTACKER[0]},{ATTACKER[1]},z0)] [SUCCESS]\n"
    f"[10:00:02] E1 T1 P2 DEPLOYMENT : Unit 101{T} DEPLOYED from (-1,-1) to {T} [R:+0.0] "
    f"[MODELS: {_ALL_101}] [SUCCESS]\n"
)


def _fought_lines(with_token: bool, n_fights: int = 7) -> str:
    # [TARGET_DECL:5] indique 5 socles au SelectTargets (1 manquant dans positions_by_model).
    token = " [TARGET_DECL:5]" if with_token else ""
    return "".join(
        f"[10:00:{3 + i:02d}] E1 T1 P1 FIGHT : Unit 1{A} FOUGHT [CLEAVE:1]{token} Unit 101{T} "
        f"with [Kustom Choppa] - Hit 4(2+) - Wound 5(2+) - Save 2(3+) - Dmg:0HP [R:+0.0] "
        f"[FIGHT_SUBPHASE:fight] [MODELS: 1#0@({ATTACKER[0]},{ATTACKER[1]},z0)] "
        f"[SHOOTER_MODELS: 1#0] [ALLOC_MODEL: 101#0] [SUCCESS]\n"
        for i in range(n_fights)
    )


def test_target_decl_elimine_faux_fight_over_cc_nb(tmp_path):
    """VERROU : [TARGET_DECL:5] + 4 socles déployés + 7 attaques [CLEAVE:1] → 0 violation.

    alive_override=5 → CLEAVE = 5//5 = 1 → cc_nb = NB(6)+1 = 7 → 7 ≤ 7 → pas de violation.
    Mutation de preuve : retirer _alive_override → alive=4 → cc_nb=6 → 7>6 → violation → ROUGE.
    """
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(_make_log(_DEPLOYMENT + _fought_lines(with_token=True)))
    stats = an.parse_step_log(str(log))
    assert stats["fight_over_cc_nb"][1] == 0, (
        "[TARGET_DECL:5] : alive=5 → CLEAVE=1 → limit=7 → 7 attaques légales"
    )
    assert stats["fight_over_cc_nb_unverifiable"][1] == 0, (
        "effectif certifié par [TARGET_DECL:N] : fight_over_cc_nb_unverifiable doit rester 0"
    )


def test_sans_target_decl_violation_reclassee_unverifiable(tmp_path):
    """Sans [TARGET_DECL:N], un surplus est marqué non-jugeable, pas violation certifiée.

    alive reconstruit=4 (4 socles déployés) → CLEAVE=0 → cc_nb=6 → 7e attaque > 6.
    Effectif non certifié → fight_over_cc_nb_unverifiable=1, fight_over_cc_nb=0.
    """
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(_make_log(_DEPLOYMENT + _fought_lines(with_token=False)))
    stats = an.parse_step_log(str(log))
    assert stats["fight_over_cc_nb"][1] == 0, (
        "sans [TARGET_DECL:N] : pas de violation certifiée possible"
    )
    assert stats["fight_over_cc_nb_unverifiable"][1] == 1, (
        "sans [TARGET_DECL:N] : 7e attaque > limite reconstituée → non-jugeable"
    )
