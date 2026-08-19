"""Fantôme du camp adverse (P1) bloque le BFS d'une avance Gretchin (P2) — E383.

CONTEXTE
Gretchin P2, 10 figurines, 2 retirées par cohérence avant l'avance. Un fantôme P1 (figurine 1#1
retirée par 03.03) occupe (37,17), un hex sur le chemin le plus court de (40,15) à (32,20).
Budget : M6 + jet 3 = 9 sous-hex. La seule déviation qui contourne ce verrou atteint 10 pas —
au-delà du budget. Sans la ligne COHERENCY REMOVED pour 1#1, l'analyzer signale
`move_distance_over_limit/advance P2 == 1`. Avec, il signale 0.

DIFFÉRENCE AVEC test_analyzer_coherency_removal_ghost.py
L'autre test couvre le cas où le fantôme est DANS la zone d'engagement de l'avanceur (distance ≤ 2
sous-hex) : il déclenche DEUX fautes simultanées — `advance_from_adjacent` et
`move_distance_over_limit`. Ici, le fantôme est à distance 4 (> EZ=2) : seul `move_distance_over_limit`
peut être levé. C'est le cas pur « fantôme-bloque-BFS sans engagement ».

GÉOMÉTRIE
  ADV_FROM  = (40, 15)   départ Gretchin
  ADV_TO    = (32, 20)   arrivée — distance hex directe = 9 = budget
  GHOST     = (37, 17)   figurine P1 retirée, sur la seule colonne de 9-pas restante après mur
  WALL      = (36, 17)   condamne l'autre hex du goulot (step 4), force tout passage par GHOST
  GRETCH_ISO= (3, 55)    2 Gretchin P2 isolés (hors cohérence), retirés avant l'avance

Avec le mur, les deux seuls chemins de longueur 9 au step 4 sont (36,17) [muré] et (37,17)
[fantôme si sans retrait]. Le BFS de chaque figurine retourne 10 → violation ; avec retrait → 9.
"""
from __future__ import annotations

import pytest

from engine.hex_utils import hex_distance
from tests.unit.ai._fabriques import entete_step_log

ADV_FROM = (40, 15)      # ancre d'escouade au départ de l'avance
ADV_TO = (32, 20)        # ancre d'escouade à l'arrivée
GHOST = (37, 17)         # figurine 1#1 : retirée par 03.03, verrou du BFS
P1_SURVIVOR = (3, 3)     # figurine 1#0 : survit, loin de l'action
GRETCH_ISO = (3, 55)     # figurines 101#8 et 101#9 : hors cohérence, retirées avant l'avance
WALL = (36, 17)          # seul hex muré — suffit à fermer le couloir
_ITS = 1                 # inches_to_subhex de ce test (ligne 86 du header)
_EZ = 2 * _ITS           # zone d'engagement en sous-hex (= 2 * inches_to_subhex, cf. _fabriques:284)
OBJECTIVES = ";".join(f"(22,{r})" for r in range(28, 34))

# COULOIR À UNE VOIE par le mur + fantôme.
# Les deux chemins les plus courts qui passent au « step 4 » (équidistants) sont :
#   (36,17) — condamné par le mur
#   (37,17) — occupé par le fantôme (sans COHERENCY REMOVED)
# Toute autre route requiert 10 pas minimum → dépasse le budget de 9.
# Sans mur, le BFS contournerait le fantôme via (36,17) et ne déclencherait rien.
_WALLS_STR = f"({WALL[0]},{WALL[1]})"

# Survivants P1 apres retrait du fantôme
_P1_MODELS_APRES = f"1#0@({P1_SURVIVOR[0]},{P1_SURVIVOR[1]},z0)"
# Gretchin après retrait de 101#8 et 101#9
_GRETCH_MODELS_APRES = " ".join(
    f"101#{ i}@({ADV_FROM[0]},{ADV_FROM[1]},z0)" for i in range(8)
)
# Gretchin à l'arrivée (8 survivants)
_GRETCH_MODELS_END = " ".join(
    f"101#{i}@({ADV_TO[0]},{ADV_TO[1]},z0)" for i in range(8)
)

_HEADER = entete_step_log(
    # P1 : 2 figurines (1#0 survivant, 1#1 futur fantôme hors cohérence)
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({P1_SURVIVOR[0]},{P1_SURVIVOR[1]}) DEPLOYED"
    f" from (-1,-1) to ({P1_SURVIVOR[0]},{P1_SURVIVOR[1]})"
    f" [R:+0.0] [MODELS:"
    f" 1#0@({P1_SURVIVOR[0]},{P1_SURVIVOR[1]},z0)"
    f" 1#1@({GHOST[0]},{GHOST[1]},z0)] [SUCCESS]\n"
    # P2 : 10 Gretchin — 8 au départ, 2 isolés (101#8, 101#9 à GRETCH_ISO)
    f"[10:00:02] E1 T1 P2 DEPLOYMENT : Unit 101({ADV_FROM[0]},{ADV_FROM[1]}) DEPLOYED"
    f" from (-1,-1) to ({ADV_FROM[0]},{ADV_FROM[1]})"
    f" [R:+0.0] [MODELS:"
    f" 101#0@({ADV_FROM[0]},{ADV_FROM[1]},z0)"
    f" 101#1@({ADV_FROM[0]},{ADV_FROM[1]},z0)"
    f" 101#2@({ADV_FROM[0]},{ADV_FROM[1]},z0)"
    f" 101#3@({ADV_FROM[0]},{ADV_FROM[1]},z0)"
    f" 101#4@({ADV_FROM[0]},{ADV_FROM[1]},z0)"
    f" 101#5@({ADV_FROM[0]},{ADV_FROM[1]},z0)"
    f" 101#6@({ADV_FROM[0]},{ADV_FROM[1]},z0)"
    f" 101#7@({ADV_FROM[0]},{ADV_FROM[1]},z0)"
    f" 101#8@({GRETCH_ISO[0]},{GRETCH_ISO[1]},z0)"
    f" 101#9@({GRETCH_ISO[0]},{GRETCH_ISO[1]},z0)] [SUCCESS]\n",
    units=(
        "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1:"
        " Starting position (-1,-1), HP_MAX=2 base=round/1\n"
        "[10:00:00] Unit 101 (Gretchin) P2:"
        " Starting position (-1,-1), HP_MAX=1 base=round/1\n"
    ),
    inches_to_subhex=1,
    board="cols=44 rows=60",
    hex_radius="13.9",
    margin=5,
    walls=_WALLS_STR,
    objectives=OBJECTIVES,
    metric_ranged="hex",
)

# Retrait de 2 Gretchin P2 hors cohérence — toujours présent (sans et avec)
_P2_REMOVAL = (
    f"[10:00:03] E1 T1 P2 FIGHT : Unit 101({ADV_FROM[0]},{ADV_FROM[1]})"
    f" COHERENCY REMOVED 101#8 101#9 (03.03)"
    f" [MODELS: {_GRETCH_MODELS_APRES}] [SUCCESS]\n"
)

# Retrait du fantôme P1 — PRÉSENT seulement dans le journal « avec retrait »
_P1_REMOVAL = (
    f"[10:00:04] E1 T1 P1 FIGHT : Unit 1({P1_SURVIVOR[0]},{P1_SURVIVOR[1]})"
    f" COHERENCY REMOVED 1#1 (03.03)"
    f" [MODELS: {_P1_MODELS_APRES}] [SUCCESS]\n"
)

# Avance P2 : 8 Gretchin survivants, Roll=3 (budget M6+3=9), (40,15)→(32,20)
_ADVANCE = (
    f"[10:00:05] E1 T1 P2 MOVE : Unit 101({ADV_TO[0]},{ADV_TO[1]}) ADVANCED from"
    f" ({ADV_FROM[0]},{ADV_FROM[1]}) to ({ADV_TO[0]},{ADV_TO[1]})"
    f" [Roll: 3] [R:+0.0]"
    f" [MODELS: {_GRETCH_MODELS_END}] [SUCCESS]\n"
)


def _stats(tmp_path, log_text, name):
    import ai.analyzer as an

    log = tmp_path / name
    log.write_text(log_text)
    return an.parse_step_log(str(log))


@pytest.fixture
def stats_avec_retrait(tmp_path):
    return _stats(tmp_path, _HEADER + _P2_REMOVAL + _P1_REMOVAL + _ADVANCE, "avec.log")


@pytest.fixture
def stats_sans_retrait(tmp_path):
    """Journal sans la ligne de retrait P1 : le fantôme 1#1 reste vivant côté analyzer."""
    return _stats(tmp_path, _HEADER + _P2_REMOVAL + _ADVANCE, "sans.log")


def test_premisse_ghost_hors_engagement():
    """PRÉREQUIS : sans cet écart le test confond deux mécanismes.

    Le fantôme doit être HORS de la zone d'engagement de l'avanceur au départ :
    distance > EZ (2 sous-hex à x1). Si distance ≤ 2, `advance_from_adjacent` se
    déclencherait aussi, et le test ne vérifierait plus le blocage BFS pur — c'est
    l'autre test (test_analyzer_coherency_removal_ghost.py) qui couvre ce cas.
    """
    def d(a, b):
        return hex_distance(a[0], a[1], b[0], b[1])

    _ez_hex = _EZ // _ITS  # EZ en hex (toujours 2, quelle que soit la résolution)
    assert d(ADV_FROM, GHOST) > _ez_hex, (
        f"le fantôme doit être hors zone d'engagement (>{_ez_hex} hex) pour ne tester que le BFS"
    )
    assert d(ADV_FROM, GHOST) + d(GHOST, ADV_TO) == d(ADV_FROM, ADV_TO), (
        "le fantôme doit être sur un chemin le plus court entre départ et arrivée"
    )


def test_sans_retrait_fantome_bloque_bfs(stats_sans_retrait):
    """VERROU : sans la ligne COHERENCY REMOVED pour P1, le fantôme occupe le couloir.

    Le BFS trouve un chemin de 10 pas (budget = 9) → `move_distance_over_limit/advance P2`.
    `advance_from_adjacent` reste à 0 : le fantôme est hors engagement (distance 4 > EZ 2) —
    mécanisme DISTINCT de test_analyzer_coherency_removal_ghost.py (fantôme dans l'EZ).
    """
    assert stats_sans_retrait["move_distance_over_limit"]["advance"][2] == 1, (
        "le fantôme 1#1 doit bloquer le BFS et déclencher move_distance_over_limit pour P2"
    )
    assert stats_sans_retrait["advance_from_adjacent"][2] == 0, (
        "le fantôme est hors zone d'engagement : advance_from_adjacent ne doit pas se lever"
    )


def test_avec_retrait_fantome_purge(stats_avec_retrait):
    """VERROU de régression : supprimer la branche COHERENCY REMOVED de l'analyzer (ou ne pas
    journaliser le retrait côté moteur) rend ce test ROUGE.

    Avec la ligne, le fantôme 1#1 est retiré de `positions_by_model` avant l'avance → le BFS
    trouve le chemin direct de 9 pas (= budget) → 0 violation.
    """
    assert stats_avec_retrait["move_distance_over_limit"]["advance"][2] == 0, (
        "le fantôme retiré par 03.03 ne doit plus bloquer le chemin de l'avance"
    )
    assert stats_avec_retrait["advance_from_adjacent"][2] == 0



def test_pas_erreurs_de_parsing(stats_avec_retrait):
    assert stats_avec_retrait["parse_errors"] == []
