"""L'analyzer ne doit PLUS inventer d'erreur de tir à partir d'une LoS ancre-à-ancre.

Régression verrouillée (2026-07-16). `ai/analyzer_phases/shoot_handler.py` comptait
`shoot_through_wall` + `shoot_invalid['no_los']` dès que `has_line_of_sight(ancre_tireur,
ancre_cible)` rendait False — un point contre un point. Sur un run réel : 6 faux positifs sur
9 tirs P1, zéro vraie violation moteur.

Règle 06.01 : la LoS se trace « from any part of that model to any part of the model being
observed » → socle-à-socle, par figurine. L'ancre-à-ancre est plus restrictif que la règle.
Le moteur, lui, gate le tir avec `_attacker_model_can_reach_squad` (per-figurine) — cf.
tests/unit/engine/test_shoot_los_perfig_parity.py, qui porte désormais la vérification.

Ce test échoue sur l'ancien code : avec cette géométrie (ancre du tireur masquée par un mur
troué hors de son axe), l'ancien analyzer comptait 1 `shoot_through_wall` et 1 `no_los`.
"""
from __future__ import annotations

import pytest

# Même géométrie que tests/unit/engine/test_shoot_los_perfig_parity.py : mur plein col=60 troué
# en row 49 seulement, tireur ancré row 50 → la ligne ancre→cible est bloquée, alors que le
# socle (round/6, 19 hexes, rows 48..52) enfile le trou. Tir légitime, 06.01.
SHOOTER = (50, 50)
TARGET = (80, 50)  # 30 subhex = 6" — largement dans les 24" du Sternguard Bolt Rifle
WALLS = ";".join(f"({60},{r})" for r in range(40, 61) if r != 49)
# Format du moteur : "(col,row)" SANS espace (cf. step_logger._format_replay_style_message).
S = f"({SHOOTER[0]},{SHOOTER[1]})"
T = f"({TARGET[0]},{TARGET[1]})"
# Zone d'objectif hors de l'axe de tir : l'analyzer exige des objectifs parsés avant toute
# action incrémentant un step, mais leur position est sans effet sur ce test.
OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))

STEP_LOG = f"""=== STEP-BY-STEP ACTION LOG ===
================================================================================

[10:00:00] === EPISODE 1 START ===
[10:00:00] Scenario: scenario_bot-01
[10:00:00] Opponent: SelfplayBot
[10:00:00] Walls: {WALLS}
[10:00:00] Objectives: rect b NW:{OBJECTIVES}
[10:00:00] Board: cols=220 rows=300 inches_to_subhex=5 hex_radius=2.78 margin=1
[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (-1,-1), HP_MAX=2 base=round/6
[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6
[10:00:00] === ACTIONS START ===
[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{S} DEPLOYED from (-1,-1) to {S} [R:+0.0] [SUCCESS]
[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{T} DEPLOYED from (-1,-1) to {T} [R:+0.0] [SUCCESS]
[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [SUCCESS]
"""


@pytest.fixture
def stats(tmp_path):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(STEP_LOG)
    return an.parse_step_log(str(log))


def test_geometry_premise_anchor_los_is_blocked():
    """Sans cette prémisse le test ne prouve rien : c'est bien un tir que l'ancien contrôle
    ancre-à-ancre refusait."""
    import ai.analyzer as an

    walls = {(60, r) for r in range(40, 61) if r != 49}
    assert an.has_line_of_sight(SHOOTER[0], SHOOTER[1], TARGET[0], TARGET[1], walls) is False


def test_legitimate_shot_is_not_counted_as_invalid(stats):
    """Le tir est légitime (06.01, socle-à-socle) → aucune erreur de tir ne doit être comptée."""
    assert stats["shoot_invalid"][1] == {"total": 1, "out_of_range": 0, "adjacent_non_pistol": 0}


def test_shoot_through_wall_counter_is_gone(stats):
    """Le compteur a été supprimé, pas remis à zéro : il n'était pas réparable depuis step.log
    (pas d'empreintes, pas de terrain obscurcissant 13.10, pas de LoS 3D)."""
    assert "shoot_through_wall" not in stats
    assert "no_los" not in stats["shoot_invalid"][1]


def test_has_line_of_sight_raises_instead_of_silently_denying():
    """Le `except Exception: return False` est supprimé (CLAUDE.md : aucun fallback masquant une
    erreur). Un refus silencieux est indiscernable d'un vrai « ne voit pas »."""
    import ai.analyzer as an

    with pytest.raises(Exception):
        an.has_line_of_sight("pas-un-entier", 1, 2, 2, set())
