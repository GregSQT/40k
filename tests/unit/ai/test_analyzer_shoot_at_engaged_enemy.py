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

import pytest

from tests.unit.ai._fabriques import entete_step_log

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


_UNITS = (
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    "[10:00:00] Unit 2 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
)


def _setup(brawler: tuple[int, int]) -> str:
    b = f"({brawler[0]},{brawler[1]})"
    return (
        f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{S} DEPLOYED from (-1,-1) to {S} [R:+0.0] [SUCCESS]\n"
        f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2{b} DEPLOYED from (-1,-1) to {b} [R:+0.0] [SUCCESS]\n"
        f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{T} DEPLOYED from (-1,-1) to {T} [R:+0.0] [SUCCESS]\n"
    )


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
    log.write_text(entete_step_log(_setup(brawler) + body, units=_UNITS, ez_vertical_inches=None))
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


# --- cas FLED ---
# L'allié (unité 2) est déployé avec [MODELS:] adjacent à la cible, puis se dégage (FLED).
# Les lignes FLED ne portent pas de [MODELS:], donc positions_by_model reste à l'ancienne
# position sauf si on le purge explicitement après la mise à jour de l'ancre.
BE = f"({BRAWLER_ENGAGED[0]},{BRAWLER_ENGAGED[1]})"
BA = f"({BRAWLER_AWAY[0]},{BRAWLER_AWAY[1]})"

_SETUP_WITH_MODELS = (
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{S} DEPLOYED from (-1,-1) to {S} [R:+0.0] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2{BE} DEPLOYED from (-1,-1) to {BE}"
    f" [R:+0.0] [MODELS: 2#0@({BRAWLER_ENGAGED[0]},{BRAWLER_ENGAGED[1]},z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{T} DEPLOYED from (-1,-1) to {T} [R:+0.0] [SUCCESS]\n"
)

_UNIT2_FLED = (
    f"[10:00:01] E1 T1 P1 MOVE : Unit 2{BA} FLED from {BE} to {BA} [R:+0.0] [SUCCESS]\n"
)


def _stats_with_models(tmp_path, body: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(_SETUP_WITH_MODELS + body, units=_UNITS, ez_vertical_inches=None))
    return an.parse_step_log(str(log))


def test_fled_ally_no_longer_engages_target(tmp_path):
    """Faux positif 04.02 : positions_by_model périmées après un FLED sans [MODELS:].

    L'allié est déployé avec [MODELS:] adjacent à la cible (positions_by_model = engagé).
    Il se dégage via FLED (pas de [MODELS:] → ancre mise à jour mais positions_by_model stale).
    Le tir suivant sur la cible ne doit PAS compter comme shoot_at_engaged_enemy : l'allié
    n'engage plus la cible depuis sa nouvelle position (ancre = BRAWLER_AWAY).
    """
    stats = _stats_with_models(tmp_path, _UNIT2_FLED + _SHOT)
    assert stats["shoot_at_engaged_enemy"][1] == 0


# --- cas PILED IN ---
# Miroir exact du cas FLED : l'allié (unité 2) est déployé avec [MODELS:] adjacent à la cible,
# puis pile-in vers BRAWLER_AWAY (phase FIGHT). Les lignes PILED IN ne portent pas de [MODELS:],
# donc positions_by_model reste à l'ancienne position (adjacent) sauf si on le purge après
# _position_cache_set. Le tir au tour suivant sur la cible doit être un faux positif avant fix.
_UNIT2_PILED_IN = (
    f"[10:00:02] E1 T1 P1 FIGHT : Unit 2{BA} PILED IN from {BE} to {BA} [R:+0.0] [SUCCESS]\n"
)

_UNIT2_CONSOLIDATED = (
    f"[10:00:02] E1 T1 P1 FIGHT : Unit 2{BA} CONSOLIDATED from {BE} to {BA} [R:+0.0] [SUCCESS]\n"
)

_SHOT_T2 = (
    f"[10:00:03] E1 T2 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Bolt Rifle]"
    " - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [SUCCESS]\n"
)


@pytest.mark.parametrize("action", [_UNIT2_PILED_IN, _UNIT2_CONSOLIDATED], ids=["piled_in", "consolidated"])
def test_fight_move_ally_no_longer_engages_target(tmp_path, action):
    """Faux positif 04.02 : positions_by_model périmées après PILED IN ou CONSOLIDATED sans [MODELS:].

    Verrou contre toute dérive qui limiterait le pop(positions_by_model) au seul kind=='pile_in' :
    PILED IN et CONSOLIDATED passent par le même handler (handle_fight_move) et le même
    _position_cache_set, le purge doit couvrir les deux verbes.
    """
    stats = _stats_with_models(tmp_path, action + _SHOT_T2)
    assert stats["shoot_at_engaged_enemy"][1] == 0
