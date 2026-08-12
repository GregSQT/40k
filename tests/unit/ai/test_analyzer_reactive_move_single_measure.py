"""Le move réactif était mesuré DEUX fois, et les deux mesures se contredisaient — vert vacant V5.

Sur la même ligne de journal, `reactive_move_abnormal` comparait la distance d'ANCRE à ANCRE
(à vol d'oiseau, sans mur ni figurine) au D6 loggué, pendant que son voisin immédiat
`distance_over_roll` posait la même question via le contrôle mutualisé
`_per_model_move_violation` : par figurine, chemin réel, budget converti à l'échelle du run.

Les deux compteurs entrent dans le total « 1.1 Erreurs en phase de move ». Conséquences
observables, l'une et l'autre fausses :

- un dépassement réel comptait **2 fautes pour 1** ;
- une reformation d'escouade (l'ancre bondit, aucune figurine ne dépasse) n'en déclenchait qu'un
  des deux, et le rapport affichait une erreur là où le jeu n'en voit aucune.

La mesure d'ancre est supprimée. `reactive_move_abnormal` ne pose plus que SA question — le move
réactif a-t-il eu lieu dans une phase où il n'a rien à y faire ? — et le budget reste à la mesure
par socle.
"""
from __future__ import annotations

import ai.analyzer as an

from tests.unit.ai._fabriques import entete_step_log


SCALE = 1
START = (10, 10)
LEGAL_DEST = (10, 12)     # 2 cases pour un D6 de 2 : dans le budget
OVER_DEST = (10, 15)      # 5 cases pour un D6 de 2 : au-delà
ROLL = 2

OBJECTIVES = ";".join(f"(30,{r})" for r in range(30, 33))

_HEADER = entete_step_log(
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({START[0]},{START[1]}) DEPLOYED from (-1,-1) to ({START[0]},{START[1]}) [R:+0.0] [MODELS: 1#0@({START[0]},{START[1]},z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(30,30) DEPLOYED from (-1,-1) to (30,30) [R:+0.0] [MODELS: 101#0@(30,30,z0)] [SUCCESS]\n",
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


def _reactive(dest, *, phase: str = "SHOOT") -> str:
    return (
        f"[10:00:02] E1 T2 P1 {phase} : Unit 1({START[0]},{START[1]}) REACTIVE MOVED [FALL BACK] "
        f"from ({START[0]},{START[1]}) to ({dest[0]},{dest[1]}) [Roll: {ROLL}] "
        f"- trigger: Unit 101->(30,30) [R:+0.0] [MODELS: 1#0@({dest[0]},{dest[1]},z0)] [SUCCESS]\n"
    )


def _stats(tmp_path, body: str):
    log = tmp_path / "step.log"
    log.write_text(_HEADER + body + _END)
    return an.parse_step_log(str(log))


def test_premise_the_reactive_line_is_recognised(tmp_path):
    """Sans ça, tous les zéros de ce fichier ne prouveraient que l'illisibilité de la ligne."""
    stats = _stats(tmp_path, _reactive(LEGAL_DEST))
    assert stats["reactive_move_stats"][1]["applied"] == 1, (
        "la ligne réactive n'a pas été reconnue : le format du journal a changé"
    )


def test_a_legal_reactive_move_counts_nothing(tmp_path):
    stats = _stats(tmp_path, _reactive(LEGAL_DEST))
    assert stats["reactive_move_stats"][1]["abnormal"] == 0
    assert stats["reactive_move_checks"]["distance_over_roll"][1] == 0


def test_a_reactive_move_beyond_the_roll_is_counted_ONCE(tmp_path):
    """LE défaut : une seule faute, un seul compteur. C'est la mesure par socle qui la porte."""
    stats = _stats(tmp_path, _reactive(OVER_DEST))
    assert stats["reactive_move_checks"]["distance_over_roll"][1] == 1, (
        "la mesure par socle ne voit plus le dépassement"
    )
    assert stats["reactive_move_stats"][1]["abnormal"] == 0, (
        "la mesure d'ancre est de retour : le dépassement est compté deux fois"
    )


def test_the_move_error_total_of_the_summary_counts_one(tmp_path):
    """C'est la ligne du SUMMARY que l'utilisateur lit — c'est elle qui doit dire 1, pas 2."""
    stats = _stats(tmp_path, _reactive(OVER_DEST))
    rendered: list = []
    an.print_statistics(stats, output_lines=rendered, emit_console=False)
    summary = [l for l in rendered if "1.1 Erreurs en phase de move" in l]
    assert len(summary) == 1, rendered[-40:]
    assert summary[0].rstrip().endswith(" 1"), summary[0]


def test_a_reactive_move_outside_MOVE_or_SHOOT_is_still_abnormal(tmp_path):
    """La question propre au compteur survit : une phase où le move réactif n'a rien à faire."""
    stats = _stats(tmp_path, _reactive(LEGAL_DEST, phase="CHARGE"))
    assert stats["reactive_move_stats"][1]["abnormal"] == 1
    assert stats["reactive_move_checks"]["distance_over_roll"][1] == 0
