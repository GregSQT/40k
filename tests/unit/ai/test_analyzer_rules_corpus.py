"""La couverture des règles — le rapport doit DIRE ce qu'il n'a pas vu, et si c'était normal.

L'analyzer relit ce que le moteur a FAIT. Il attrape donc ce qu'il fait de trop — un déplacement
trop long, un tir hors de portée — et rien de ce qu'il fait de trop peu : une règle que le moteur
n'applique pas ne produit aucune ligne fautive, donc aucun compteur ne bouge, donc le rapport
affiche un vert franc. Mesuré le 2026-08-10 : « ✅ 1.1 Erreurs en phase de move : 0 » pendant que
le moteur violait 17.01 à chaque déplacement de véhicule non volant.

`config/rules_corpus.json` répond en séparant trois situations que « 0 » confondait :

- HORS ROSTER — aucune unité jouée ne porte la règle, elle ne POUVAIT pas servir ;
- OK — la règle a été exercée n fois, sans faute ;
- JAMAIS EXERCÉE — elle était applicable, et aucun contrôle n'a rien eu à juger. C'est le seul
  verdict qui demande une action, et c'est celui qui manquait.

Ce fichier verrouille les trois, plus l'invariant qui empêche le corpus de devenir une SECONDE
somme d'erreurs divergeant de la première — le défaut V16, pris par l'autre bout : ici, une faute
comptée dans le total de section mais portée par aucune règle.
"""
from __future__ import annotations

import pytest

import ai.analyzer as an
from tests.unit.ai._fabriques import entete_step_log
from ai.analyzer_rules import (
    coverage_gaps,
    coverage_rows,
    load_rules_corpus,
    new_rule_usage_counters,
    note_rule_usage,
)


OBJECTIVES = ";".join(f"(30,{r})" for r in range(30, 33))

_HEADER = entete_step_log(
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(10,10) DEPLOYED from (-1,-1) to (10,10) [R:+0.0] [MODELS: 1#0@(10,10,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(30,30) DEPLOYED from (-1,-1) to (30,30) [R:+0.0] [MODELS: 101#0@(30,30,z0)] [SUCCESS]\n",
    units=(
        "[10:00:00] Unit 1 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
        "[10:00:00] Unit 101 (Intercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
    ),
    inches_to_subhex=1,
    board="cols=40 rows=40",
    walls="none",
    objectives=OBJECTIVES,
    rosters="scale=1 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
)

_END = ("[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
        "[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, "
        "Total=0, Duration=1.000s\n")

#: Un déplacement normal banal : dans le budget, loin de tout ennemi, une seule figurine.
_A_NORMAL_MOVE = (
    "[10:00:02] E1 T2 P1 MOVE : Unit 1(10,12) MOVED from (10,10) to (10,12)"
    "[R:+0.0] [MODELS: 1#0@(10,12,z0)] [SUCCESS]\n"
)


def _stats(tmp_path, body: str = ""):
    log = tmp_path / "step.log"
    log.write_text(_HEADER + body + _END)
    return an.parse_step_log(str(log))


def _row(stats, rule_id: str):
    for row in coverage_rows(stats, "1.1"):
        if row["id"] == rule_id:
            return row
    raise AssertionError(f"règle {rule_id!r} absente de la couverture §1.1")


# ─────────────────────────────────────────────────────────────────────────────
# Structure : rien ne se crée à la volée
# ─────────────────────────────────────────────────────────────────────────────

def test_every_corpus_rule_has_its_counter_declared(tmp_path):
    """Une clé de `stats` qui n'existe qu'au premier incrément est le défaut V17, qui faisait
    lever tout consommateur du `stats` rendu. Ici : déclarées d'avance, toutes."""
    stats = _stats(tmp_path)
    usage = stats["rule_usage"]
    for entry in load_rules_corpus():
        assert entry["id"] in usage, f"{entry['id']} n'a pas de compteur d'exercice déclaré"
        assert usage[entry["id"]] == {1: 0, 2: 0}


def test_an_unknown_rule_raises_instead_of_creating_a_counter():
    """Un compteur d'exercice sans entrée de corpus ne serait lu par personne — donc il lève."""
    stats = {"rule_usage": new_rule_usage_counters()}
    with pytest.raises(KeyError, match="rules_corpus"):
        note_rule_usage(stats, "99.99", 1)


# ─────────────────────────────────────────────────────────────────────────────
# Les trois verdicts
# ─────────────────────────────────────────────────────────────────────────────

def test_a_rule_the_roster_cannot_carry_is_out_of_scope(tmp_path):
    """Aucune unité jouée ne porte le move réactif : la règle ne pouvait pas servir. Ce n'est
    pas une anomalie, et ça ne doit pas peser comme un zéro suspect."""
    stats = _stats(tmp_path, _A_NORMAL_MOVE)
    row = _row(stats, "PROJET.reactive_move")
    assert row["applicable"] is False
    assert row["verdict"] == "HORS ROSTER"


def test_an_exercised_rule_reports_how_many_times(tmp_path):
    """Le compte d'exercices est ce qui distingue « rien trouvé » de « rien regardé »."""
    stats = _stats(tmp_path, _A_NORMAL_MOVE * 3)
    row = _row(stats, "09.05")
    assert row["exercised"] == 3, "le compteur d'exercice ne suit pas les lignes jugées"
    assert row["errors"] == 0
    assert row["verdict"] == "OK"


def test_an_applicable_rule_never_exercised_is_flagged(tmp_path):
    """LE signal du chantier. Les deux escouades du journal n'ont qu'une figurine : 03.03 ne
    gouverne aucune d'elles (« a unit that contains more than one model »), donc la cohérence
    n'a JAMAIS été mise à l'épreuve — alors que des déplacements ont eu lieu.

    Sans ce verdict, la section affiche « 0 erreur » et laisse croire que la règle est tenue.
    """
    stats = _stats(tmp_path, _A_NORMAL_MOVE)
    row = _row(stats, "03.03")
    assert row["applicable"] is True, "des déplacements ont eu lieu : la règle était applicable"
    assert row["exercised"] == 0
    assert row["verdict"] == "JAMAIS EXERCÉE"


def test_the_warning_is_rendered_and_names_the_rule(tmp_path):
    """Un verdict qui n'apparaît pas dans le rapport rendu n'existe pas pour le lecteur."""
    stats = _stats(tmp_path, _A_NORMAL_MOVE)
    rendered: list = []
    an.print_statistics(stats, output_lines=rendered, emit_console=False)
    warnings = [l for l in rendered if "jamais exercee" in l]
    assert len(warnings) >= 1, rendered[-60:]
    assert any("03.03" in w for w in warnings)


def test_summary_signals_never_exercised_rules(tmp_path):
    """Le SUMMARY affiche ⚠️ sur la ligne 1.1 quand une règle est applicable mais jamais exercée.

    Cas fondateur : 03.03 est applicable (un déplacement a eu lieu) mais jamais jugée
    (les deux escouades n'ont qu'une figurine). Sans ce signal, la ligne affiche
    « ✅ 1.1 Erreurs en phase de move : 0 » alors que le contrôle n'a rien regardé.
    """
    stats = _stats(tmp_path, _A_NORMAL_MOVE)
    rendered: list = []
    an.print_statistics(stats, output_lines=rendered, emit_console=False)
    summary_start = next((i for i, l in enumerate(rendered) if l.strip() == "SUMMARY"), None)
    assert summary_start is not None, "section SUMMARY absente du rendu"
    summary_lines = rendered[summary_start:]
    line_11 = next((l for l in summary_lines if "1.1" in l and "move" in l.lower()), None)
    assert line_11 is not None, "ligne 1.1 absente du SUMMARY"
    assert "jamais exerc" in line_11.lower(), (
        f"le SUMMARY ne signale pas les règles jamais exercées sur la ligne 1.1 : {line_11!r}"
    )
    assert "⚠" in line_11, f"aucune icône ⚠️ sur la ligne 1.1 du SUMMARY : {line_11!r}"


# ─────────────────────────────────────────────────────────────────────────────
# L'invariant : la somme par règle retombe sur le total de section
# ─────────────────────────────────────────────────────────────────────────────

def test_the_per_rule_sum_matches_the_section_total(tmp_path):
    """Chaque compteur d'erreur de §1.1 appartient à exactement UNE règle.

    Sans cet invariant, le corpus deviendrait une seconde somme d'erreurs divergeant en silence
    de `error_totals` — c'est le défaut V16, pris par l'autre bout : une faute affichée dans le
    total de la section que plus aucune règle ne porte.
    """
    stats = _stats(tmp_path, _A_NORMAL_MOVE)
    # Chaque compteur du bucket, l'un après l'autre : le contrôle ne doit pas dépendre du fait
    # qu'ils soient tous à zéro.
    stats["move_to_adjacent_enemy"][1] = 1
    stats["flee_still_engaged"][2] = 1
    stats["squad_coherency_violations"][1] = 1
    stats["reactive_move_stats"][2]["abnormal"] = 1
    stats["move_after_shooting_distance_over_limit"][1] = 1
    stats["reactive_move_checks"]["into_wall"][2] = 1
    stats["move_distance_over_limit"]["move"][1] = 1
    stats["move_distance_over_limit"]["flee"][2] = 1
    stats["wall_collisions"][1] = 1
    stats["move_adjacent_before_non_flee"][2] = 1
    stats["flee_from_unengaged"][1] = 1
    stats["reactive_move_checks"]["to_adjacent_enemy"][1] = 1
    stats["reactive_move_checks"]["distance_over_roll"][2] = 1
    assert an.error_totals(stats)["move"] == 13, "le bucket ne voit pas les 13 compteurs"
    assert coverage_gaps(stats) == [], (
        "un compteur d'erreur de §1.1 n'est porté par aucune règle du corpus, ou l'est par deux"
    )


def test_a_counter_dropped_from_the_corpus_is_reported(tmp_path):
    """Le contrôle doit MORDRE : on retire un compteur du corpus, l'écart doit remonter."""
    stats = _stats(tmp_path, _A_NORMAL_MOVE)
    stats["wall_collisions"][1] = 1
    corpus = load_rules_corpus()
    entry = next(e for e in corpus if e["id"] == "03.01")
    saved = entry["controls"]
    entry["controls"] = []
    try:
        gaps = coverage_gaps(stats)
    finally:
        entry["controls"] = saved
    assert gaps == [("1.1", 0, 1)], (
        "l'écart entre la somme par règle et le total de section n'est pas détecté"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Ce que la revue du 2026-08-10 a démontré : le rapport pouvait se contredire
# ─────────────────────────────────────────────────────────────────────────────

def test_a_rule_with_errors_is_never_reported_out_of_roster(tmp_path):
    """Le verdict testait l'applicabilité AVANT les erreurs : une règle fautive sortait donc
    « HORS ROSTER », avec ses exercices imprimés en tiret, pendant que la section affichait ❌.

    Une faute est un FAIT : elle prouve que la situation s'est présentée. Ici le journal ne porte
    aucun mouvement — le prédicat dit donc « pas applicable » — mais le compteur de 03.01 est
    armé, et c'est lui qui doit gagner.
    """
    stats = _stats(tmp_path)
    stats["wall_collisions"][1] = 1
    row = _row(stats, "03.01")
    assert row["verdict"] == "ERREURS", "une erreur réelle est masquée par un verdict d'applicabilité"


def test_a_rule_that_was_exercised_is_never_reported_out_of_roster(tmp_path):
    """Même principe, par l'autre bout : 03.03 est jugée dès la mise en place, alors que son
    applicabilité se dérivait de la présence d'un DÉPLACEMENT. Un journal de déploiement seul
    rendait donc des exercices > 0 sous un verdict « hors roster » — le rapport contredisant la
    mesure qu'il venait d'imprimer.
    """
    body = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(10,10) DEPLOYED from (-1,-1) to (10,10) "
        "[R:+0.0] [MODELS: 1#0@(10,10,z0) 1#1@(10,12,z0)] [SUCCESS]\n"
    )
    stats = _stats(tmp_path, body)
    row = _row(stats, "03.03")
    assert row["exercised"] > 0, "la formation déployée n'a pas été jugée"
    assert row["verdict"] != "HORS ROSTER", (
        "le rapport déclare hors roster une règle qu'il vient de mesurer"
    )


def test_the_fall_back_site_also_counts_an_exercise_of_03_01(tmp_path):
    """`wall_collisions` a TROIS sites d'incrément et n'en notait qu'un : sur un journal de
    fall-back, 03.01 criait « jamais exercée » alors que son contrôle avait travaillé. Une fausse
    alerte sur le seul verdict que ce chantier a créé est pire qu'une absence d'alerte."""
    body = (
        "[10:00:02] E1 T2 P1 MOVE : Unit 1(10,11) FLED from (10,10) to (10,11)"
        " [R:+0.0] [MODELS: 1#0@(10,11,z0)] [SUCCESS]\n"
    )
    stats = _stats(tmp_path, body)
    assert _row(stats, "03.01")["exercised"] > 0, (
        "le site fall-back de wall_collisions ne note toujours pas d'exercice"
    )
