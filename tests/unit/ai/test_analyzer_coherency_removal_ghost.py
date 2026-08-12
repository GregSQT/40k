"""Une figurine retirée à l'étape End of Turn (03.03) ne doit plus engager personne.

Régression mesurée sur le run du 2026-08-12 (600 épisodes, E485). L'escouade 102 avance et
l'analyzer lui compte DEUX fautes — « advance from adjacent » et « advance au-delà du budget » —
à cause de la seule figurine `2#9`, qui n'était plus sur la table : le moteur l'avait retirée à
l'étape End of Turn du tour précédent, faute de cohérence. Ce retrait est la SEULE mort qui ne
descend d'aucune attaque, et il n'écrivait AUCUNE ligne dans step.log (`add_console_log` est
debug-only) : zéro occurrence de `COHERENCY` dans 35 Mo de journal.

Un lecteur qui reconstruit l'état par accumulation d'événements gardait donc la figurine vivante
jusqu'à la prochaine action de son escouade. Elle engageait ses ennemis (zone d'engagement) et
bloquait leurs chemins (`move.thru_enemy=False`) — deux fautes inventées sur un tour légal.

CE QUE CE TEST CONSTRUIT — et il ne prouve rien sans ça : une figurine isolée de son escouade,
à portée d'engagement de l'escouade adverse, retirée par 03.03 juste avant que l'adversaire
n'avance. Les survivantes de son escouade sont, elles, LOIN de l'avance.
  - sans la ligne de retrait (l'état d'avant le 2026-08-12) → 1 « advance from adjacent » ;
  - avec la ligne                                          → 0.
"""
from __future__ import annotations

import pytest

# Board x1 (inches_to_subhex=1) : 1 hex = 1 pouce.
ISOLEE = (30, 20)      # figurine 1#2 : hors cohérence (>2 de ses voisines), retirée par 03.03
GROUPE = [(10, 20), (11, 20)]   # 1#0 / 1#1 : cohérentes entre elles, LOIN de l'avance
ADV_FROM = (32, 20)    # départ de l'avance : à 2 hex de ISOLEE, donc DANS sa zone d'engagement
ADV_TO = (24, 20)      # arrivée : 8 hex EN LIGNE DROITE PAR-DESSUS la figurine retirée, et le
                       # budget (M6 + jet 2 = 8) ne paie AUCUN détour. Tant que le fantôme est là,
                       # `move.thru_enemy=False` interdit la case et le chemin dépasse le budget :
                       # c'est le second symptôme mesuré sur E485, sur la même ligne.
OBJECTIVES = ";".join(f"(60,{r})" for r in range(40, 46))
# COULOIR À UNE VOIE. Sur une grille hexagonale, un chemin le plus court n'est jamais unique :
# bloquer UNE case au milieu d'une ligne droite ne rallonge rien du tout. Sans ces murs, le
# fantôme ne bloquerait donc rien et le second symptôme (le budget) ne se reproduirait pas — le
# test passerait au vert sans rien mesurer.
WALLS = ";".join(f"({c},{r})" for c in range(23, 34) for r in (19, 21))

_HEADER = f"""=== STEP-BY-STEP ACTION LOG ===
================================================================================

[10:00:00] === EPISODE 1 START ===
[10:00:00] Scenario: scenario_bot-01
[10:00:00] Opponent: SelfplayBot
[10:00:00] Walls: {WALLS}
[10:00:00] Objectives: rect b NW:{OBJECTIVES}
[10:00:00] Board: cols=44 rows=60 inches_to_subhex=1 hex_radius=13.9 margin=5
[10:00:00] Run rules: engagement_zone_subhex=2 engagement_zone_vertical_inches=5.0 metric.engagement=hex metric.ranged=hex move.thru_ez=True move.thru_enemy=False move.thru_friendly=True cohesion.model_subhex=2 cohesion.global_subhex=9 cohesion.min_neighbors=1
[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (-1,-1), HP_MAX=2 base=round/1
[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/1
[10:00:00] === ACTIONS START ===
[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({GROUPE[0][0]},{GROUPE[0][1]}) DEPLOYED from (-1,-1) to ({GROUPE[0][0]},{GROUPE[0][1]}) [R:+0.0] [MODELS: 1#0@({GROUPE[0][0]},{GROUPE[0][1]},z0) 1#1@({GROUPE[1][0]},{GROUPE[1][1]},z0) 1#2@({ISOLEE[0]},{ISOLEE[1]},z0)] [SUCCESS]
[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101({ADV_FROM[0]},{ADV_FROM[1]}) DEPLOYED from (-1,-1) to ({ADV_FROM[0]},{ADV_FROM[1]}) [R:+0.0] [MODELS: 101#0@({ADV_FROM[0]},{ADV_FROM[1]},z0)] [SUCCESS]
"""

# Ligne de retrait 03.03 : le `[MODELS:]` ne porte QUE les survivantes — c'est lui qui purge la
# figurine retirée chez tout lecteur du journal.
_REMOVAL = (
    f"[10:00:02] E1 T1 P1 FIGHT : Unit 1({GROUPE[0][0]},{GROUPE[0][1]}) COHERENCY REMOVED 1#2 "
    f"(03.03) [MODELS: 1#0@({GROUPE[0][0]},{GROUPE[0][1]},z0) 1#1@({GROUPE[1][0]},{GROUPE[1][1]},z0)]"
    " [SUCCESS]\n"
)

_ADVANCE = (
    f"[10:00:03] E1 T1 P2 MOVE : Unit 101({ADV_TO[0]},{ADV_TO[1]}) ADVANCED from "
    f"({ADV_FROM[0]},{ADV_FROM[1]}) to ({ADV_TO[0]},{ADV_TO[1]}) [Roll: 2] [R:+0.0] "
    f"[MODELS: 101#0@({ADV_TO[0]},{ADV_TO[1]},z0)] [SUCCESS]\n"
)


def _stats(tmp_path, log_text, name):
    import ai.analyzer as an

    log = tmp_path / name
    log.write_text(log_text)
    return an.parse_step_log(str(log))


@pytest.fixture
def stats_avec_retrait(tmp_path):
    return _stats(tmp_path, _HEADER + _REMOVAL + _ADVANCE, "avec.log")


@pytest.fixture
def stats_sans_retrait(tmp_path):
    """L'état du moteur avant le 2026-08-12 : le retrait a lieu, mais rien ne le journalise."""
    return _stats(tmp_path, _HEADER + _ADVANCE, "sans.log")


def test_premisse_la_figurine_retiree_engage_et_les_survivantes_non():
    """Sans cet écart le test ne prouve rien : les deux journaux rendraient le même verdict."""
    from engine.hex_utils import offset_to_cube

    def d(a, b):
        ax, ay, az = offset_to_cube(*a)
        bx, by, bz = offset_to_cube(*b)
        return max(abs(ax - bx), abs(ay - by), abs(az - bz))

    assert d(ADV_FROM, ISOLEE) <= 2, "la figurine retirée doit être dans la zone d'engagement"
    assert min(d(ADV_FROM, pos) for pos in GROUPE) > 2, "les survivantes doivent être hors zone"


def test_le_journal_sans_retrait_fabrique_bien_les_deux_fautes(stats_sans_retrait):
    """VERROU du verrou : c'est ce que produisait le moteur muet. Si ce test devient vert, le
    journal « avec retrait » ne prouve plus rien — le contrôle ne regarderait plus rien.

    Les DEUX symptômes de E485 sont là, sur la même ligne et pour la même figurine : elle engage
    (zone d'engagement) et elle bloque (`move.thru_enemy=False`).
    """
    assert stats_sans_retrait["advance_from_adjacent"][2] == 1
    assert stats_sans_retrait["move_distance_over_limit"]["advance"][2] == 1


def test_la_ligne_de_retrait_supprime_le_fantome(stats_avec_retrait):
    """VERROU : retirer l'`append_action_log` du moteur (ou la branche de l'analyzer qui laisse le
    segment `[MODELS:]` faire son travail) rend ce test ROUGE."""
    assert stats_avec_retrait["advance_from_adjacent"][2] == 0, (
        "la figurine retirée par 03.03 engage encore : le journal ne l'a pas retirée du plateau"
    )
    assert stats_avec_retrait["move_distance_over_limit"]["advance"][2] == 0, (
        "la figurine retirée par 03.03 bloque encore le chemin de l'avance"
    )


def test_le_retrait_est_compte_comme_exercice_de_la_regle(
    stats_avec_retrait, stats_sans_retrait
):
    """Un retrait 03.03 est la RÈGLE qui s'applique, pas une faute : il se compte à part.

    La violation comptée dans les deux journaux vient de la ligne de DÉPLOIEMENT (03.03 vaut à la
    mise en place, et la fixture y pose délibérément une figurine isolée). La ligne de retrait,
    elle, n'en ajoute aucune : elle n'est pas un déplacement, et sa formation est cohérente.
    """
    assert stats_avec_retrait["coherency_removals"][1] == 1
    assert stats_avec_retrait["coherency_removals"][2] == 0
    assert stats_sans_retrait["coherency_removals"][1] == 0
    assert (
        stats_avec_retrait["squad_coherency_violations"][1]
        == stats_sans_retrait["squad_coherency_violations"][1]
    ), "la ligne de retrait ne doit être jugée par aucun contrôle de cohérence"


def test_la_ligne_de_retrait_ne_produit_aucune_erreur_de_parsing(stats_avec_retrait):
    assert stats_avec_retrait["parse_errors"] == []
