"""Le diagnostic de la section 1.1 doit NOMMER l'unité qui engage — avec la mesure du compteur.

DÉFAUT VERROUILLÉ (mesuré le 2026-08-09). Le compteur « Moves to adjacent enemy » décide avec
`is_within_engine_engagement_zone` : par-figurine, seuil `engagement_zone`, métrique du run. La
ligne de diagnostic, elle, nommait les coupables avec `get_adjacent_enemies` : adjacence
d'ANCRE à distance hex 1. À ×5 (`ez=10`) une escouade peut être engagée bord-à-bord tout en
ayant ses ancres à 13 cases l'une de l'autre — l'adjacence d'ancre ne se lève donc jamais, et le
rapport imprimait « Adjacent after move: none » sous une erreur qui venait de se déclencher.

Deux mesures pour une même question dans la même fonction : c'est le motif JUMEAU du dépôt.

Les positions sont celles du témoin réel (E3 T3, journal du 2026-08-09) : l'escouade 105 finit
son move avec `105#5` et `105#6` dans la zone d'engagement de l'unité 1.
"""

from __future__ import annotations

import pytest

import ai.analyzer as an
from tests.unit.ai._fabriques import pose_etat_du_run


EZ = 10          # 2" × inches_to_subhex 5, déjà scalé (contrat moteur)
BASE = ("round", 6)

ENEMY_MODELS = {"1#0": (144, 59), "1#1": (144, 53), "1#2": (138, 53),
                "1#3": (144, 47), "1#4": (138, 47), "1#5": (142, 40)}
MOVER_MODELS = {"105#0": (173, 61), "105#1": (168, 65), "105#2": (167, 59),
                "105#3": (164, 55), "105#4": (162, 67), "105#5": (159, 60),
                "105#6": (157, 52)}
MOVER_ANCHOR = MOVER_MODELS["105#0"]


@pytest.fixture(autouse=True)
def _regles_du_run():
    """Règles du run posées à la main : hors `parse_step_log` les getters lèvent plutôt que de
    retomber sur le config du jour. `metric.engagement=euclidean` est celle du témoin."""
    pose_etat_du_run(5, ez_subhex=EZ, ez_vertical_inches=5.0, metric_engagement="euclidean")


def _args():
    return {
        "unit_player": {"1": 1, "105": 2},
        "unit_positions": {"1": ENEMY_MODELS["1#0"], "105": MOVER_ANCHOR},
        "unit_hp": {"1": 12, "105": 14},
        "engagement_zone": EZ,
        "position_override": MOVER_ANCHOR,
        "positions_by_model": {"1": dict(ENEMY_MODELS), "105": dict(MOVER_MODELS)},
        "unit_base": {"1": BASE, "105": BASE},
        "subject_models": dict(MOVER_MODELS),
    }


def test_premise_the_counter_fires_on_this_situation():
    """Sans ça, tout le reste du fichier verrouillerait le vide."""
    assert an.is_within_engine_engagement_zone("105", **_args()), (
        "le compteur ne se déclenche pas sur le témoin : les positions ou les règles du run ne "
        "décrivent plus la situation mesurée"
    )


def test_premise_anchor_adjacency_sees_nothing_here():
    """L'ancienne source du diagnostic est aveugle ici — c'est TOUT le défaut."""
    offenders_anchor = an.get_adjacent_enemies(
        MOVER_ANCHOR[0], MOVER_ANCHOR[1], {"1": 1, "105": 2},
        {"1": ENEMY_MODELS["1#0"], "105": MOVER_ANCHOR}, {"1": 12, "105": 14}, {}, 2,
    )
    assert not offenders_anchor, (
        "l'adjacence d'ancre trouve un ennemi : le témoin ne démontre plus l'écart entre les "
        "deux mesures, et le test ne verrouille rien"
    )


def test_the_diagnostic_names_the_engaging_unit():
    """Le correctif : la mesure du compteur, rendue en nommé."""
    assert an.engine_engagement_zone_offenders("105", **_args()) == ["1"], (
        "le diagnostic doit nommer l'unité 1 — s'il rend une liste vide, il est reparti sur "
        "une mesure d'ancre et le rapport réaffichera « none » sous une vraie erreur"
    )


def test_predicate_and_diagnostic_cannot_disagree():
    """Le booléen n'est que « la liste est-elle non vide ». Une seule mesure, deux formes."""
    for override, subject in (
        (MOVER_ANCHOR, dict(MOVER_MODELS)),            # engagé
        ((10, 10), {"105#0": (10, 10)}),               # à l'autre bout du plateau
    ):
        args = {**_args(), "position_override": override, "subject_models": subject}
        assert an.is_within_engine_engagement_zone("105", **args) == bool(
            an.engine_engagement_zone_offenders("105", **args)
        ), "prédicat et diagnostic divergent : la mesure a été dupliquée"


def test_a_unit_engaged_by_several_of_its_models_is_named_once():
    """105#5 ET 105#6 engagent l'unité 1 : elle ne doit apparaître qu'une fois."""
    offenders = an.engine_engagement_zone_offenders("105", **_args())
    assert len(offenders) == len(set(offenders)), f"doublons dans le diagnostic : {offenders}"


def test_report_line_distinguishes_absent_key_from_empty_list():
    """« clé absente » (câblage) et « liste vide » (contradiction) ne se disent pas pareil.

    Les confondre en « none » est ce qui a rendu la ligne inexploitable : elle affichait la
    même chose quand le diagnostic n'était pas renseigné et quand il ne trouvait personne.
    """
    assert an._offenders_str({}) != an._offenders_str({"adjacent_after": []})
    assert "Unit 1" in an._offenders_str({"adjacent_after": ["1"]})
