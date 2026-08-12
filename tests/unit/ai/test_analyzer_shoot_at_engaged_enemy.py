"""04.02 : la cible d'un tir doit être NON ENGAGÉE — et ça se juge avant les pertes du tir.

« Unengaged : you can only select enemy units that are not engaged with any of your units as
targets. » Le contrôle `shoot_at_engaged_enemy` demande donc si la cible est engagée par un ALLIÉ
du tireur, au moment où le moteur a choisi la cible.

POURQUOI CE FICHIER EXISTE. Ce contrôle valait 0 sur les runs disponibles, avant comme après le
correctif d'engagement du 2026-08-12 : rien ne prouvait qu'il voyait encore quelque chose, ni que le
correctif ne l'avait pas éteint. Un compteur à zéro sans verrou est indiscernable d'un contrôle
mort — c'est exactement ce qui a laissé vivre trois faux positifs de cette famille (LoS 2026-07-16,
mêlée 2026-07-24, portée et engagement 2026-08-12).

Jumeau de `test_analyzer_close_quarters_engagement.py` (10.06) : même journal synthétique, même
piège, autre règle.
"""
from __future__ import annotations

OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))

# Échelle x5 : zone d'engagement du run = 10 subhex. Le tireur est LOIN (il ne doit lui-même être
# engagé avec personne, sinon c'est 10.06 qui parlerait, pas 04.02) et à portée de son Bolt Rifle
# (24" = 120 subhex).
SHOOTER = (50, 50)
TARGET = (100, 100)
# L'allié de mêlée : au contact de la cible (engagement), ou à l'autre bout (témoin négatif).
BRAWLER_ENGAGED = (100, 92)
BRAWLER_AWAY = (20, 20)

S = f"({SHOOTER[0]},{SHOOTER[1]})"
T = f"({TARGET[0]},{TARGET[1]})"


def _header(brawler: tuple[int, int]) -> str:
    b = f"({brawler[0]},{brawler[1]})"
    return f"""=== STEP-BY-STEP ACTION LOG ===
================================================================================

[10:00:00] === EPISODE 1 START ===
[10:00:00] Scenario: scenario_bot-01
[10:00:00] Opponent: SelfplayBot
[10:00:00] Walls:
[10:00:00] Objectives: rect b NW:{OBJECTIVES}
[10:00:00] Board: cols=220 rows=300 inches_to_subhex=5 hex_radius=2.78 margin=1
[10:00:00] Run rules: engagement_zone_subhex=10 metric.engagement=hex metric.ranged=euclidean move.thru_ez=True move.thru_enemy=False move.thru_friendly=True cohesion.model_subhex=10 cohesion.global_subhex=45 cohesion.min_neighbors=1
[10:00:00] Unit 1 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6
[10:00:00] Unit 2 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6
[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6
[10:00:00] === ACTIONS START ===
[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{S} DEPLOYED from (-1,-1) to {S} [R:+0.0] [SUCCESS]
[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2{b} DEPLOYED from (-1,-1) to {b} [R:+0.0] [SUCCESS]
[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{T} DEPLOYED from (-1,-1) to {T} [R:+0.0] [SUCCESS]
"""


# Arme NON-[CLOSE_QUARTERS] : c'est 04.02 qu'on teste, pas la restriction d'armes de 10.06.
_SHOT = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Bolt Rifle]"
    " - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [SUCCESS]\n"
)
# Le MÊME tir, mortel (la cible a 2 PV) : elle est retirée de l'état AVANT que le contrôle ne mesure.
_SHOT_KILLS = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Bolt Rifle]"
    " - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:2HP [R:+0.0] [SUCCESS]\n"
)


def _stats(tmp_path, brawler: tuple[int, int], body: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(_header(brawler) + body)
    return an.parse_step_log(str(log))


def test_geometry_premise():
    """Sans ces trois distances, aucun des tests suivants ne prouve ce qu'il annonce."""
    import ai.analyzer as an

    d = an.calculate_hex_distance
    assert d(*BRAWLER_ENGAGED, *TARGET) <= 10, "l'allié doit ENGAGER la cible"
    assert d(*BRAWLER_AWAY, *TARGET) > 10, "le témoin négatif ne doit engager personne"
    assert d(*SHOOTER, *TARGET) > 10, "le tireur ne doit pas être engagé : sinon c'est 10.06"


def test_shooting_an_enemy_engaged_with_a_friendly_is_the_violation(tmp_path):
    """04.02 : la cible est au contact de l'unité 2, alliée du tireur -> faute."""
    stats = _stats(tmp_path, BRAWLER_ENGAGED, _SHOT)
    assert stats["shoot_at_engaged_enemy"][1] == 1


def test_shooting_an_unengaged_enemy_is_legal(tmp_path):
    """Témoin négatif : même tir, allié à l'autre bout du plateau -> aucune faute."""
    stats = _stats(tmp_path, BRAWLER_AWAY, _SHOT)
    assert stats["shoot_at_engaged_enemy"][1] == 0


def test_the_verdict_survives_the_kill(tmp_path):
    """MOMENT de la mesure : la cible tuée par le tir jugé disparaît de l'état reconstruit.

    `analyzer_core` applique les dégâts avant d'aiguiller la ligne : sans le gel au Select Targets
    step, la cible morte n'a plus ni PV ni socles, la mesure d'engagement s'arrête sur un sujet
    absent et la faute s'évapore. Le contrôle ne doit pas dépendre de la survie de sa cible.
    """
    stats = _stats(tmp_path, BRAWLER_ENGAGED, _SHOT_KILLS)
    assert stats["shoot_at_engaged_enemy"][1] == 1
