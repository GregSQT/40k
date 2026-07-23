"""L'analyzer ne doit PLUS inventer d'erreur de combat « Fight from non-adjacent hex ».

Régression verrouillée (2026-07-24). `ai/analyzer_phases/fight_handler.py` comptait
`fight_from_non_adjacent` dès que la distance bord-à-bord EN HEX (`squads_min_edge_distance`
= `min_distance_between_sets` d'empreintes) entre attaquant et cible dépassait la zone
d'engagement (`ez` subhexes). Sur un run réel : 13 faux positifs, zéro vraie violation moteur.

DEUX causes, toutes deux fatales à la reconstruction depuis step.log :

1. MÉTRIQUE. Le moteur gate le combat en EUCLIDIEN (config
   `distance_metric.engagement="euclidean"` → `entries_in_engagement_zone`, seuil
   `engagement_minimum_clearance_norm(ez)` = ez×1,5). Le contrôle analyzer mesurait en HEX.
   Sur socles à grand diamètre (round/18 contre round/6), l'écart hex↔euclidien au bord
   dépasse 1 subhex : hexEdge=11 alors que euclidien=14,9 ≤ 15 → ENGAGÉ pour le moteur,
   « non-adjacent » faussement pour l'analyzer.

2. POSITION CIBLE. La position de la cible AU MOMENT DU COMBAT n'est pas journalisée de façon
   fiable : `positions_by_model` n'est mis à jour que quand la cible AGIT, et `[TARGET_MODELS:]`
   liste les SURVIVANTS POST-PERTES (socles proches détruits → survivants plus loin).

Le moteur garantit déjà l'invariant au gate `_fight_build_valid_target_pool` (n'ajoute que des
cibles dans la zone d'engagement euclidienne). Vérification portée par le test moteur
`tests/unit/engine/test_fight_spatial_contract.py::test_fight_b_engagement_pool_uses_full_footprint_distance`.

Ce test échoue sur l'ancien code : avec cette géométrie (attaquant round/18, cible round/6
à hexEdge=11 > ez=10 mais euclidien=14,9 ≤ 15), l'ancien analyzer comptait 1
`fight_from_non_adjacent`.
"""
from __future__ import annotations

import pytest

# Attaquant round/18 à (100,100) ; cible round/6 à (105,81). Empreintes moteur :
#   - distance bord-à-bord HEX  = 11 subhex (> ez=10 → ancien contrôle : FAUX POSITIF) ;
#   - distance bord-à-bord EUCL = 14,9 (≤ ez×1,5 = 15 → moteur : ENGAGÉ, combat légal).
ATTACKER = (100, 100)   # Unit 1, base round/18
TARGET = (105, 81)      # Unit 101, base round/6
OBJECTIVES = ";".join(f"(200,{r})" for r in range(200, 206))

STEP_LOG = f"""=== STEP-BY-STEP ACTION LOG ===
================================================================================

[10:00:00] === EPISODE 1 START ===
[10:00:00] Scenario: scenario_bot-01
[10:00:00] Opponent: SelfplayBot
[10:00:00] Walls: (300,300)
[10:00:00] Objectives: rect b NW:{OBJECTIVES}
[10:00:00] Board: cols=220 rows=300 inches_to_subhex=5 hex_radius=2.78 margin=1
[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (-1,-1), HP_MAX=2 base=round/18
[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6
[10:00:00] === ACTIONS START ===
[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({ATTACKER[0]},{ATTACKER[1]}) DEPLOYED from (-1,-1) to ({ATTACKER[0]},{ATTACKER[1]}) [R:+0.0] [SUCCESS]
[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101({TARGET[0]},{TARGET[1]}) DEPLOYED from (-1,-1) to ({TARGET[0]},{TARGET[1]}) [R:+0.0] [SUCCESS]
[10:00:02] E1 T1 P2 SHOOT : Unit 101({TARGET[0]},{TARGET[1]}) WAIT [MODELS: 101#0@({TARGET[0]},{TARGET[1]})] [SUCCESS]
[10:00:03] E1 T1 P1 FIGHT : Unit 1({ATTACKER[0]},{ATTACKER[1]}) FOUGHT Unit 101({TARGET[0]},{TARGET[1]}) with [Close Combat Weapon] - Hit 4(3+) [R:+0.0] [FIGHT_SUBPHASE:fight] [MODELS: 1#0@({ATTACKER[0]},{ATTACKER[1]})] [SUCCESS]
"""


def test_geometry_premise_hex_non_adjacent_but_euclidean_engaged() -> None:
    """La géométrie choisie EST le piège : hex > ez (déclenchait l'ancien contrôle) mais
    euclidien ≤ ez×1,5 (le moteur la considère engagée → combat légal)."""
    from engine.hex_utils import (
        compute_occupied_hexes,
        min_distance_between_sets,
        euclidean_edge_distance,
        engagement_minimum_clearance_norm,
        Socle,
    )

    ez = 10  # engagement_zone (2") × inches_to_subhex (5)
    a = Socle("round", 18, *ATTACKER, set(compute_occupied_hexes(*ATTACKER, "round", 18, 0)), [ATTACKER], 0)
    b = Socle("round", 6, *TARGET, set(compute_occupied_hexes(*TARGET, "round", 6, 0)), [TARGET], 0)

    hex_edge = min_distance_between_sets(a.fp, b.fp, max_distance=99)
    eucl_edge = euclidean_edge_distance(a, b)

    assert hex_edge > ez, f"prémisse invalide : hexEdge={hex_edge} devrait être > {ez}"
    assert eucl_edge <= engagement_minimum_clearance_norm(ez), (
        f"prémisse invalide : euclidien={eucl_edge} devrait être ≤ {engagement_minimum_clearance_norm(ez)}"
    )


@pytest.fixture
def stats(tmp_path):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(STEP_LOG)
    return an.parse_step_log(str(log))


def test_no_fight_from_non_adjacent_false_positive(stats) -> None:
    """Le combat légal (euclidien-engagé mais hex-non-adjacent) ne doit lever AUCUNE
    erreur `fight_from_non_adjacent`. L'ancien code en comptait 1."""
    fna = stats["fight_from_non_adjacent"]
    assert fna[1] == 0 and fna[2] == 0, f"faux positif Fight-from-non-adjacent : {fna}"
