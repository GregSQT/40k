"""Un site d'ERREUR ne doit jamais être atteignable là où son site d'EXERCICE ne l'est pas.

Quand l'exercice est gardé plus étroitement que l'erreur, la couverture rend « Exercices 0 /
Erreurs N » — un état que `coverage_rows` classe en ERREURS sans pouvoir dire que c'est
l'instrumentation qui manque, et que son commentaire déclarait « arithmétiquement impossible ».
Trois chemins le produisaient, mesurés le 2026-09-07 :

1. `PROJ.1.2.advance_post_tir` — l'exercice était sous `if phase == 'SHOOT'`, le contrôle non.
   L'ADVANCE étant un type de mouvement (09.02, « Select Move Type ») et la phase de tir n'en
   portant aucun (10.02), ce garde était toujours faux : mesuré sur le step.log du dépôt,
   10849 lignes ADVANCED, 10849 en phase MOVE, zéro en SHOOT.
2. Les trois règles `PROJ.2.8.*` du recalage — l'exercice était sous `unit_player is not None`,
   les trois compteurs d'erreurs s'incrémentent sans lui (cf. `test_analyzer_state_resync_*`).
3. Les règles PDF de double-activation (09.02 / 10.02 / 11.02 / 12.07) — aucun site d'exercice
   du tout, alors que leur compteur d'erreurs a un écrivain vivant.

Le contrôle `advance_twice_in_shoot_phase` a été SUPPRIMÉ dans le même geste : gardé par la même
condition morte, il ne pouvait rien compter, et la faute qu'il visait (deux sélections de
mouvement dans la même phase, 09.02) est mesurée par `double_activation_by_phase['MOVE']` —
`test_double_advance_dans_la_phase_move_est_compte` en fait la preuve.
"""
from __future__ import annotations

import ai.analyzer as an
from ai.analyzer_rules import coverage_rows

from tests.unit.ai._fabriques import entete_step_log

_OBJECTIFS = ";".join(f"(150,{r})" for r in range(150, 156))
_UNITS = (
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2\n"
)


def _log(corps: str) -> str:
    return entete_step_log(
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50)"
        " [R:+0.0] [SUCCESS]\n"
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(90,50) DEPLOYED from (-1,-1) to (90,50)"
        " [R:+0.0] [SUCCESS]\n" + corps,
        inches_to_subhex=5,
        objectives=_OBJECTIFS,
        units=_UNITS,
        ez_vertical_inches=None,
    )


def _avance(depart: str, arrivee: str, horodatage: str = "10:00:03") -> str:
    col, row = arrivee.strip("()").split(",")
    return (
        f"[{horodatage}] E1 T1 P1 MOVE : Unit 1({col},{row}) ADVANCED from {depart} to {arrivee}"
        f" [Roll: 3] [R:+0.0] [MODELS: 1#0@({col},{row})] [SUCCESS]\n"
    )


# Grammaire RÉELLE du formateur (`step_logger`) : ` with [arme]` et `Dmg:XHP`. L'ancienne forme
# `- Bolt Rifle - … - Damage 1` n'a jamais été produite par le moteur ; elle passait parce
# qu'aucun lecteur n'exigeait le nom d'arme sur une ligne à sauvegarde — `note_shoot_allocation`
# l'exige désormais (un groupe de tir anonyme est inidentifiable, T1).
_TIR = (
    "[10:00:02] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 101(90,50) with [Bolt Rifle]"
    " - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP [SHOOTER_MODELS: 1#0] [SUCCESS]\n"
)


def _ligne(stats: dict, section: str, rule_id: str) -> dict:
    return next(r for r in coverage_rows(stats, section) if r["id"] == rule_id)


def test_chaque_avance_note_un_exercice_de_advance_post_tir(tmp_path) -> None:
    """L'ADVANCE arrive en phase MOVE : c'est LÀ que l'occasion se juge, pas en phase de tir."""
    log = tmp_path / "step.log"
    log.write_text(_log(_avance("(50,50)", "(52,50)")))
    stats = an.parse_step_log(str(log))

    ligne = _ligne(stats, "1.2", "PROJ.1.2.advance_post_tir")
    assert ligne["exercised"] == 1, "l'avance en phase MOVE ne note aucune occasion jugée"
    assert ligne["errors"] == 0
    assert ligne["verdict"] == "OK"


def test_une_avance_apres_tir_est_une_erreur_ET_un_exercice(tmp_path) -> None:
    """LE cas qui produisait « Exercices 0 / Erreurs 1 ».

    Journal volontairement désordonné (tir en phase SHOOT, puis avance en phase MOVE du MÊME
    tour) : `units_shot` n'est purgé qu'au changement de TOUR, donc le contrôle voit la faute.
    C'est le seul contrôle qui la voit — `phase_order_violations` et `wrong_phase` restent à 0,
    chaque ligne étant dans la phase que sa propre action réclame.
    """
    log = tmp_path / "step.log"
    log.write_text(_log(_TIR + _avance("(50,50)", "(52,50)")))
    stats = an.parse_step_log(str(log))

    assert stats["advance_after_shoot"][1] == 1
    assert stats["phase_order_violations"] == 0, "prémisse : la séquence de phases reste valide"
    ligne = _ligne(stats, "1.2", "PROJ.1.2.advance_post_tir")
    assert ligne["errors"] == 1
    assert ligne["exercised"] == 1, (
        "l'exercice est plus étroit que l'erreur : la couverture rend « Exercices 0 / Erreurs 1 »"
    )
    assert ligne["verdict"] == "ERREURS"


def test_double_advance_dans_la_phase_move_est_compte(tmp_path) -> None:
    """09.02 : « select one friendly unit that has NOT been selected to move this phase ».

    La faute est comptée par `double_activation_by_phase['MOVE']` — le contrôle supprimé, gardé
    par `phase == 'SHOOT'`, ne pouvait pas la voir. Et elle est désormais ATTRIBUÉE : le compteur
    n'appartenait à aucune règle du corpus avant le 2026-09-07.
    """
    log = tmp_path / "step.log"
    log.write_text(_log(_avance("(50,50)", "(52,50)") + _avance("(52,50)", "(54,50)", "10:00:04")))
    stats = an.parse_step_log(str(log))

    assert stats["double_activation_by_phase"]["MOVE"] == 1
    assert an.error_totals(stats)["double_activation"] == 1
    ligne = _ligne(stats, "pdf", "09.02")
    assert ligne["errors"] == 1, "la double sélection de mouvement n'est rattachée à aucune règle"
    assert ligne["exercised"] == 2, "une occasion par ligne d'activation de la phase"
    assert ligne["verdict"] == "ERREURS"


def test_les_regles_pdf_de_double_activation_sortent_OK_sur_un_run_propre(tmp_path) -> None:
    """Sans site d'exercice, 09.02/10.02/11.02/12.07 ne pouvaient afficher que JAMAIS EXERCÉE."""
    log = tmp_path / "step.log"
    log.write_text(_log(_TIR + _avance("(50,50)", "(52,50)", "10:00:04")))
    stats = an.parse_step_log(str(log))

    for rule_id in ("09.02", "10.02"):
        ligne = _ligne(stats, "pdf", rule_id)
        assert ligne["exercised"] > 0, f"{rule_id} : aucune occasion jugée sur un journal qui agit"
        assert ligne["verdict"] == "OK", f"{rule_id} : {ligne}"
