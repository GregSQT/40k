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
from ai.analyzer_rules import (
    coverage_gaps,
    coverage_rows,
    load_rules_corpus,
    new_rule_usage_counters,
    note_rule_usage,
)


OBJECTIVES = ";".join(f"(30,{r})" for r in range(30, 33))

_HEADER = (
    "=== STEP-BY-STEP ACTION LOG ===\n"
    "================================================================================\n\n"
    "[10:00:00] === EPISODE 1 START ===\n"
    "[10:00:00] Scenario: scenario_bot-01\n"
    "[10:00:00] Rosters: scale=1 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)\n"
    "[10:00:00] Opponent: SelfplayBot\n"
    "[10:00:00] Walls: none\n"
    f"[10:00:00] Objectives: rect b NW:{OBJECTIVES}\n"
    "[10:00:00] Board: cols=40 rows=40 inches_to_subhex=1 hex_radius=2.78 margin=1\n"
    "[10:00:00] Run rules: engagement_zone_subhex=2 engagement_zone_vertical_inches=5.0 "
    "metric.engagement=hex metric.ranged=euclidean move.thru_ez=True move.thru_enemy=False "
    "move.thru_friendly=True cohesion.model_subhex=2 cohesion.global_subhex=9 "
    "cohesion.min_neighbors=1\n"
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
    "[10:00:00] Unit 101 (Intercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
    "[10:00:00] === ACTIONS START ===\n"
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(10,10) DEPLOYED from (-1,-1) to (10,10) "
    "[R:+0.0] [MODELS: 1#0@(10,10,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(30,30) DEPLOYED from (-1,-1) to (30,30) "
    "[R:+0.0] [MODELS: 101#0@(30,30,z0)] [SUCCESS]\n"
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
    assert len(warnings) == 1, rendered[-60:]
    assert "03.03" in warnings[0]


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
