"""Le contrôle close-quarters doit mesurer l'ENGAGEMENT (10.06), pas une adjacence d'ancre.

10.06 CLOSE-QUARTERS SHOOTING, volet « Non-MONSTER/Non-VEHICLE Models » : « You can only select
[CLOSE-QUARTERS] weapons to make attacks with and you can only select enemy units that are
**engaged with your unit** as targets. »

L'ancien contrôle comptait une faute dès que
`calculate_hex_distance(ancre_tireur, ancre_cible) != 1`. Faux deux fois : ancre au lieu du
par-figurine, et adjacence au lieu de la zone d'engagement du run (ici 10 subhex = 2"). Le moteur,
lui, gate le tir sur `enemy_engaged_with_shooter` (`shooting_handlers` ~L693) : le contrôle
contredisait le moteur ET la règle. 144 faux positifs mesurés sur un run de 600 épisodes.

Troisième occurrence de la famille « ancre vs par-figurine », après le contrôle LoS
(test_analyzer_no_anchor_los_false_positive) et le fight non-adjacent
(test_analyzer_no_fight_non_adjacent_false_positive).
"""
from __future__ import annotations

import pytest

# Échelle x5 : la zone d'engagement du run vaut 10 subhex (2"). Le tireur et sa cible sont à
# 8 subhex d'ancre à ancre — donc ENGAGÉS au sens du moteur, et pourtant jamais « adjacents ».
# C'est exactement la configuration qui produisait le faux positif.
SHOOTER = (50, 50)
ENGAGED_TARGET = (50, 58)
# Deuxième ennemi, hors de toute zone d'engagement du tireur : le viser AVEC une arme
# [CLOSE-QUARTERS] alors qu'on est engagé est la VRAIE faute 10.06.
FAR_TARGET = (50, 90)
# Troisième ennemi, engagé lui aussi avec le tireur. Il tient `shooter_engaged_at_all` à VRAI
# quand la cible du tir meurt : sans lui, le contrôle ne se déclencherait plus pour une raison
# étrangère à ce qu'on teste, et les tests de mort ci-dessous seraient des verts vacants.
OTHER_ENGAGING = (50, 42)
OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))

S = f"({SHOOTER[0]},{SHOOTER[1]})"
T = f"({ENGAGED_TARGET[0]},{ENGAGED_TARGET[1]})"
F = f"({FAR_TARGET[0]},{FAR_TARGET[1]})"
OTH = f"({OTHER_ENGAGING[0]},{OTHER_ENGAGING[1]})"

_HEADER = f"""=== STEP-BY-STEP ACTION LOG ===
================================================================================

[10:00:00] === EPISODE 1 START ===
[10:00:00] Scenario: scenario_bot-01
[10:00:00] Opponent: SelfplayBot
[10:00:00] Walls:
[10:00:00] Objectives: rect b NW:{OBJECTIVES}
[10:00:00] Board: cols=220 rows=300 inches_to_subhex=5 hex_radius=2.78 margin=1
[10:00:00] Run rules: engagement_zone_subhex=10 metric.engagement=hex metric.ranged=euclidean move.thru_ez=True move.thru_enemy=False move.thru_friendly=True cohesion.model_subhex=10 cohesion.global_subhex=45 cohesion.min_neighbors=1
[10:00:00] Unit 1 (VanguardVeteranSquadJumpPack) P1: Starting position (-1,-1), HP_MAX=2 base=round/6
[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6
[10:00:00] Unit 102 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6
[10:00:00] Unit 103 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6
[10:00:00] === ACTIONS START ===
[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{S} DEPLOYED from (-1,-1) to {S} [R:+0.0] [SUCCESS]
[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{T} DEPLOYED from (-1,-1) to {T} [R:+0.0] [SUCCESS]
[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 102{F} DEPLOYED from (-1,-1) to {F} [R:+0.0] [SUCCESS]
[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 103{OTH} DEPLOYED from (-1,-1) to {OTH} [R:+0.0] [SUCCESS]
"""

_SHOT_AT_ENGAGED = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Heavy Bolt Pistol]"
    " - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [SUCCESS]\n"
)
_SHOT_AT_FAR = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 102{F} with [Heavy Bolt Pistol]"
    " - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [SUCCESS]\n"
)


_KILLS_ENGAGED = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Heavy Bolt Pistol]"
    " - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:2HP [R:+0.0] [SUCCESS]\n"
)
_EXCESS_SHOT_AFTER_KILL = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Heavy Bolt Pistol]"
    " - Hit 5(3+) - Wound 2(4+) [R:+0.0] [SUCCESS]\n"
)
_KILLS_FAR = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 102{F} with [Heavy Bolt Pistol]"
    " - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:2HP [R:+0.0] [SUCCESS]\n"
)


def _stats(tmp_path, body: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(_HEADER + body)
    return an.parse_step_log(str(log))


def test_geometry_premise_engaged_but_never_adjacent():
    """Sans cette prémisse le test ne prouve rien : ancre à 8, engagement à 10, adjacence à 1."""
    import ai.analyzer as an

    d = an.calculate_hex_distance(SHOOTER[0], SHOOTER[1], ENGAGED_TARGET[0], ENGAGED_TARGET[1])
    assert d == 8, d
    assert d != 1, "l'ancien contrôle ne se serait pas déclenché : test inopérant"
    assert d <= 10, "les deux escouades doivent être dans la zone d'engagement du run"


def test_close_quarters_shot_at_the_unit_it_is_engaged_with_is_legal(tmp_path):
    """10.06 : cible engagée avec le tireur -> tir légal, aucune erreur."""
    stats = _stats(tmp_path, _SHOT_AT_ENGAGED)
    assert stats["close_quarters_shot_at_unengaged_target"][1] == 0
    assert stats["engaged_shot_with_non_close_quarters_weapon"][1] == 0
    assert stats["close_quarters_shots"][1]["engaged_target"] == 1
    assert stats["close_quarters_shots"][1]["unengaged_target"] == 0


def test_close_quarters_shot_at_a_unit_not_engaged_with_is_the_real_violation(tmp_path):
    """Contrôle anti-vert-vacant : la VRAIE faute 10.06 est toujours détectée.

    Le tireur est engagé avec l'unité 101 ; il tire sur 102, avec laquelle il ne l'est pas.
    Sans ce cas, « 0 erreur » ne prouverait rien d'autre que la mort du contrôle.
    """
    stats = _stats(tmp_path, _SHOT_AT_FAR)
    assert stats["close_quarters_shot_at_unengaged_target"][1] == 1
    assert stats["close_quarters_shots"][1]["unengaged_target"] == 1


def test_geometry_premise_third_enemy_also_engages_the_shooter():
    """Prémisse des trois tests de mort : 103 engage le tireur, 102 non."""
    import ai.analyzer as an

    assert an.calculate_hex_distance(SHOOTER[0], SHOOTER[1], OTHER_ENGAGING[0], OTHER_ENGAGING[1]) <= 10
    assert an.calculate_hex_distance(SHOOTER[0], SHOOTER[1], FAR_TARGET[0], FAR_TARGET[1]) > 10


def test_pistol_that_kills_its_engaged_target_is_not_a_violation(tmp_path):
    """MOMENT de la mesure : 10.06 se juge au Select Targets step, pas après les pertes.

    Le tireur est engagé avec 101 (sa cible) ET avec 103. Le pistolet TUE 101 : quand le handler
    voit la ligne, `analyzer_core` a déjà retiré 101 de `unit_hp`/`unit_positions` et purgé ses
    socles. La cible sort de l'énumération des ennemis, le tireur reste engagé (103), et le
    contrôle concluait « tir engagé sur une unité non engagée » sur un tir parfaitement légal.
    Mesuré sur le run du 2026-08-12 (E422 T4) : 1 faux positif, zéro tir réellement illégal.
    """
    stats = _stats(tmp_path, _KILLS_ENGAGED)
    assert stats["close_quarters_shot_at_unengaged_target"][1] == 0
    assert stats["close_quarters_shots"][1]["engaged_target"] == 1
    assert stats["close_quarters_shots"][1]["unengaged_target"] == 0


def test_excess_attack_of_the_same_activation_is_judged_at_select_targets(tmp_path):
    """Le gel est par ACTIVATION : la 2e attaque ne se juge pas sur les pertes de la 1re.

    C'est ce qui distingue le gel au Select Targets step (10.06 est une règle de ciblage, tranchée
    une fois pour l'activation entière) d'un simple instantané par ligne, qui laisserait revenir
    le même faux positif un tir plus tard.
    """
    stats = _stats(tmp_path, _KILLS_ENGAGED + _EXCESS_SHOT_AFTER_KILL)
    assert stats["close_quarters_shot_at_unengaged_target"][1] == 0
    assert stats["close_quarters_shots"][1]["engaged_target"] == 2


def test_killing_a_unit_it_is_not_engaged_with_remains_a_violation(tmp_path):
    """Anti-vert-vacant : restituer la cible ne doit pas absoudre la VRAIE faute.

    Même tir illégal que le test précédent, mais mortel : le contrôle doit compter 1, sinon le
    correctif aurait simplement éteint le contrôle sur toutes les attaques qui tuent.
    """
    stats = _stats(tmp_path, _KILLS_FAR)
    assert stats["close_quarters_shot_at_unengaged_target"][1] == 1
    assert stats["close_quarters_shots"][1]["unengaged_target"] == 1
