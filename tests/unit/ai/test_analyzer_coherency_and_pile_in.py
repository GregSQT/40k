"""Deux règles que l'analyzer ne contrôlait pas, alors que le journal portait tout — 03.03 et 12.02.

**03.03 Coherency.** « A unit that contains more than one model must be set up and end any kind of
move in coherency. A unit is in coherency while both of the following apply to every model in that
unit: within 2" of at least one other model in that unit ; within 9" of every other model. » Le
segment `[MODELS:]` donne toutes les positions par figurine depuis des mois, et rien ne les
regardait : le trou est identifié depuis V11 T6-i. Le moteur purge les figurines incohérentes à la
fin du tour ; personne ne vérifiait que les formations JOURNALISÉES respectaient la règle à chaque
fin de déplacement, qui est ce que 03.03 exige.

Le verdict n'est pas ré-écrit côté analyzer : `squad_coherency_offenders` mesure, puis délègue à
`_coherency_verdict` du MOTEUR. La 1re puce n'est pas « au moins un voisin » mais la CONNEXITÉ de
toute l'escouade — deux paquets séparés respectant chacun les 2" ne sont PAS en cohérence, et le
moteur a vécu ce défaut-là avant de le corriger. Le dernier test du fichier verrouille ce point.

**12.02 Pile in.** « Each unit cannot make more than one pile-in move during this step. » §1.6
(double-activation) ne pouvait pas le voir : son marqueur d'activation en phase de combat est
`CONSOLIDATED` (12.07), et un second pile-in ne produit aucune consolidation supplémentaire.

Les trois seuils de cohérence viennent de l'entête `Run rules:` du journal analysé — le moteur les
y écrit depuis ce chantier. C'est la même exigence que la zone d'engagement et l'échelle : un
journal d'hier ne se juge pas avec le `game_config.json` d'aujourd'hui.
"""
from __future__ import annotations

import re

import ai.analyzer as an

from tests.unit.ai._fabriques import entete_step_log


SCALE = 1
COH, COH_MAX = 2 * SCALE, 9 * SCALE

# Formation SAINE : chaîne de trois socles, chacun à 2 de son voisin, étalement 4 ≤ 9.
COHERENT = [(10, 10), (10, 12), (10, 14)]
# Formation FAUTIVE : le 3e socle est à 8 du 2e (aucun voisin à 2) et à 10 du 1er (> 9).
INCOHERENT = [(10, 10), (10, 12), (10, 20)]
# DEUX PAQUETS, chacun cohérent à l'intérieur, séparés de 8 : c'est le piège de la 1re puce.
# Une lecture « au moins un voisin » les accepte ; la connexité exigée par 03.03 les refuse.
TWO_CLUMPS = [(10, 10), (10, 12), (10, 20), (10, 22)]

OBJECTIVES = ";".join(f"(30,{r})" for r in range(30, 33))

_HEADER = entete_step_log(
    units=(
        "[10:00:00] Unit 1 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
        "[10:00:00] Unit 101 (Intercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
    ),
    inches_to_subhex=SCALE,
    board="cols=40 rows=40",
    walls="none",
    objectives=OBJECTIVES,
    rosters="scale=1 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
)

_END = ("[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
        "[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, "
        "Total=0, Duration=1.000s\n")


def _models(unit_id: str, positions) -> str:
    return " ".join(f"{unit_id}#{i}@({c},{r},z0)" for i, (c, r) in enumerate(positions))


def _deployed(unit_id: str, positions) -> str:
    anchor = positions[0]
    return (
        f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit {unit_id}({anchor[0]},{anchor[1]}) DEPLOYED "
        f"from (-1,-1) to ({anchor[0]},{anchor[1]}) [R:+0.0] "
        f"[MODELS: {_models(unit_id, positions)}] [SUCCESS]\n"
    )


def _stats(tmp_path, body: str):
    log = tmp_path / "step.log"
    log.write_text(_HEADER + body + _END)
    return an.parse_step_log(str(log))


# ═════════════════════════════════════════════════════════════════════════════════════════════
# 03.03 Coherency
# ═════════════════════════════════════════════════════════════════════════════════════════════

def test_premise_the_three_distances_fall_where_the_rule_changes_verdict():
    """Aucune distance du témoin ne doit tomber SUR un seuil : un test posé sur la frontière
    change de verdict au premier arrondi, et ne prouve alors plus rien."""
    from ai.analyzer import calculate_hex_distance as d

    assert d(*COHERENT[0], *COHERENT[1]) == 2 <= COH
    assert d(*COHERENT[0], *COHERENT[2]) == 4 < COH_MAX
    assert d(*INCOHERENT[1], *INCOHERENT[2]) == 8 > COH, "le socle isolé doit n'avoir aucun voisin"
    assert d(*INCOHERENT[0], *INCOHERENT[2]) == 10 > COH_MAX, "et dépasser aussi l'étalement"


def test_a_coherent_formation_raises_nothing(tmp_path):
    stats = _stats(tmp_path, _deployed("1", COHERENT))
    assert stats["squad_coherency_violations"][1] == 0


def test_a_broken_formation_is_counted(tmp_path):
    """Un socle hors des 2" ET hors des 9" : la FORMATION est fautive, comptée une fois."""
    stats = _stats(tmp_path, _deployed("1", INCOHERENT))
    assert stats["squad_coherency_violations"][1] == 1, (
        "03.03 n'est plus contrôlée : `[MODELS:]` porte pourtant toutes les positions"
    )


def test_a_single_model_unit_is_never_incoherent(tmp_path):
    """« A unit that contains more than one model » : la règle ne vise pas les unités à un socle."""
    stats = _stats(tmp_path, _deployed("1", [(10, 10)]))
    assert stats["squad_coherency_violations"][1] == 0


def test_two_separate_clumps_are_not_coherency(tmp_path):
    """Le piège de la 1re puce : chaque paquet a son voisin à 2, mais l'escouade est coupée en deux.

    C'est ce que verrouille la délégation à `_coherency_verdict` : une lecture « au moins un
    voisin », que le moteur a lui-même portée avant de la corriger, accepterait cette formation.
    """
    stats = _stats(tmp_path, _deployed("1", TWO_CLUMPS))
    assert stats["squad_coherency_violations"][1] == 1, (
        "deux paquets disjoints sont acceptés : le verdict est reparti sur « au moins un voisin » "
        "au lieu de la connexité exigée par 03.03"
    )


def test_the_violation_reaches_the_MOVE_error_total_of_the_summary(tmp_path):
    """Un compteur hors de tout total est un compteur que personne ne lit (mode d'échec V1/V16)."""
    stats = _stats(tmp_path, _deployed("1", INCOHERENT))
    rendered: list = []
    an.print_statistics(stats, output_lines=rendered, emit_console=False)
    summary = [l for l in rendered if "1.1 Erreurs en phase de move" in l]
    assert len(summary) == 1, rendered[-40:]
    m = re.search(r": (\d+)", summary[0])
    assert m and int(m.group(1)) == 1, summary[0]


# ═════════════════════════════════════════════════════════════════════════════════════════════
# 12.02 — un seul pile-in par unité et par étape
# ═════════════════════════════════════════════════════════════════════════════════════════════

def _fight_move(verb: str, unit_id: str, frm, to, *, timestamp: str = "10:00:03") -> str:
    return (
        f"[{timestamp}] E1 T2 P1 FIGHT : Unit {unit_id}({frm[0]},{frm[1]}) {verb} from "
        f"({frm[0]},{frm[1]}) to ({to[0]},{to[1]}) [R:+0.0] "
        f"[MODELS: {_models(unit_id, [to])}] [SUCCESS]\n"
    )


_ONE_MODEL_DEPLOY = _deployed("1", [(10, 10)])


def test_premise_a_single_pile_in_is_not_a_fault(tmp_path):
    """Sans ça, le test suivant pourrait passer parce que TOUT pile-in est compté."""
    stats = _stats(tmp_path, _ONE_MODEL_DEPLOY + _fight_move("PILED IN", "1", (10, 10), (10, 11)))
    assert stats["fight_double_pile_in"][1] == 0


def test_a_second_pile_in_in_the_same_phase_is_counted(tmp_path):
    stats = _stats(
        tmp_path,
        _ONE_MODEL_DEPLOY
        + _fight_move("PILED IN", "1", (10, 10), (10, 11))
        + _fight_move("PILED IN", "1", (10, 11), (10, 12), timestamp="10:00:04"),
    )
    assert stats["fight_double_pile_in"][1] == 1, (
        "12.02 n'est plus contrôlée : un second pile-in passe inaperçu"
    )


def test_a_pile_in_followed_by_a_consolidation_is_legal(tmp_path):
    """12.02 puis 12.07 : deux ÉTAPES distinctes de la même phase, une unité fait légalement les
    deux. Les compter sur la même clé ferait de chaque combat normal un doublon."""
    stats = _stats(
        tmp_path,
        _ONE_MODEL_DEPLOY
        + _fight_move("PILED IN", "1", (10, 10), (10, 11))
        + _fight_move("CONSOLIDATED", "1", (10, 11), (10, 12), timestamp="10:00:05"),
    )
    assert stats["fight_double_pile_in"][1] == 0
    assert stats["double_activation_by_phase"]["FIGHT"] == 0
