"""note_rule_usage : cinq sites PROJ exercés au moins une fois.

Chaque test vérifie que `stats["rule_usage"][rule_id][player]` atteint ≥ 1 après parsing
d'un step.log minimal déclenchant la règle ciblée. Ces règles portent toutes le risque
d'être déclarées « JAMAIS EXERCÉES » dans le rapport de couverture si le site est muet :
le compteur doit monter dans des conditions normales de jeu.

Couverture des sites :
  PROJ.2.1.dead_shot_at   — analyzer_core.py       (SHOT avec Dmg:NHP > 0)
  PROJ.1.2.surcharge_atk  — analyzer_phases/shoot_handler.py  (plafond de tirs calculé)
  PROJ.1.3.budget         — analyzer_phases/charge_handler.py (budget de charge mesuré)
  PROJ.1.4.pile_in        — analyzer_phases/fight_handler.py  (ancre pile-in bouge)
  PROJ.1.4.consolidation  — analyzer_phases/fight_handler.py  (ancre consolidation bouge)
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

# ---------------------------------------------------------------------------
# SHOOT fixture — PROJ.2.1.dead_shot_at + PROJ.1.2.surcharge_atk
#
# SternguardVeteranBoltRifle est dans la config (rng_nb non nul) : le handler
# atteint le plafond de tirs et note_rule_usage est appelé pour les deux règles.
# Dmg:2HP > 0 déclenche en plus le contrôle « tir sur unité morte ».
# ---------------------------------------------------------------------------
_SHOOT_LOG = entete_step_log(
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50)"
    " [R:+0.0] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(80,50) DEPLOYED from (-1,-1) to (80,50)"
    " [R:+0.0] [SUCCESS]\n"
    "[10:00:02] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 101(80,50)"
    " with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:2HP"
    " [R:+0.0] [SUCCESS]\n",
    units=(
        "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (50,50),"
        " HP_MAX=2 base=round/6 [MODELS: 1#0@(50,50)]\n"
        "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (80,50),"
        " HP_MAX=2 base=round/6 [MODELS: 101#0@(80,50)]\n"
    ),
    ez_vertical_inches=None,
)

# ---------------------------------------------------------------------------
# CHARGE fixture — PROJ.1.3.budget
#
# Le marqueur [Roll: 8] permet au handler d'atteindre _per_model_move_violation
# et note_rule_usage. La position de départ/arrivée est valide (pas de violation).
# ---------------------------------------------------------------------------
_CHARGE_LOG = entete_step_log(
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50)"
    " [R:+0.0] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(50,100) DEPLOYED from (-1,-1) to (50,100)"
    " [R:+0.0] [SUCCESS]\n"
    "[10:00:02] E1 T1 P1 CHARGE : Unit 1(50,50) CHARGED Unit 101(50,100)"
    ' from (50,50) to (50,90) [Roll: 8] [Dist: 2.0" | Nearest: 2.0"]'
    " [R:+0.0] [SUCCESS]\n",
    units=(
        "[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (50,50),"
        " HP_MAX=2 base=round/6\n"
        "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (50,100),"
        " HP_MAX=2 base=round/6\n"
    ),
    ez_vertical_inches=None,
)

# ---------------------------------------------------------------------------
# FIGHT fixture — PROJ.1.4.pile_in + PROJ.1.4.consolidation
#
# handle_fight_move vérifie `unit_id in state.unit_hp` (HP > 0 requis) et
# `anchor_from != anchor_to` (moved = True) avant d'appeler note_rule_usage.
# Les deux unités sont déployées ; les ancres from/to diffèrent dans les deux cas.
# ---------------------------------------------------------------------------
_FIGHT_LOG = entete_step_log(
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(100,90) DEPLOYED from (-1,-1) to (100,90)"
    " [R:+0.0] [SUCCESS]\n"
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2(100,110) DEPLOYED from (-1,-1) to (100,110)"
    " [R:+0.0] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(100,100) DEPLOYED from (-1,-1) to (100,100)"
    " [R:+0.0] [SUCCESS]\n"
    "[10:00:02] E1 T1 P1 FIGHT : Unit 1(100,90) PILED IN from (100,90) to (100,75)"
    " [R:+0.0] [SUCCESS]\n"
    "[10:00:03] E1 T1 P1 FIGHT : Unit 2(100,110) CONSOLIDATED from (100,110) to (100,125)"
    " [R:+0.0] [SUCCESS]\n",
    units=(
        "[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (100,90),"
        " HP_MAX=2 base=round/6\n"
        "[10:00:00] Unit 2 (AssaultIntercessor) P1: Starting position (100,110),"
        " HP_MAX=2 base=round/6\n"
        "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (100,100),"
        " HP_MAX=2 base=round/6\n"
    ),
    ez_vertical_inches=None,
)


def _parse(tmp_path, contenu: str):
    import ai.analyzer as an
    log = tmp_path / "step.log"
    log.write_text(contenu)
    return an.parse_step_log(str(log))


def test_rule_usage_proj21_dead_shot_at(tmp_path):
    """PROJ.2.1.dead_shot_at est noté dès qu'un SHOT porte Dmg:NHP > 0."""
    stats = _parse(tmp_path, _SHOOT_LOG)
    assert stats["rule_usage"]["PROJ.2.1.dead_shot_at"][1] >= 1


def test_rule_usage_proj12_surcharge_atk(tmp_path):
    """PROJ.1.2.surcharge_atk est noté quand le plafond de tirs est évalué."""
    stats = _parse(tmp_path, _SHOOT_LOG)
    assert stats["rule_usage"]["PROJ.1.2.surcharge_atk"][1] >= 1


def test_rule_usage_proj13_budget(tmp_path):
    """PROJ.1.3.budget est noté quand le budget de charge est mesuré par figurine."""
    stats = _parse(tmp_path, _CHARGE_LOG)
    assert stats["rule_usage"]["PROJ.1.3.budget"][1] >= 1


def test_rule_usage_proj14_pile_in(tmp_path):
    """PROJ.1.4.pile_in est noté quand l'ancre du pile-in est déplacée."""
    stats = _parse(tmp_path, _FIGHT_LOG)
    assert stats["rule_usage"]["PROJ.1.4.pile_in"][1] >= 1


def test_rule_usage_proj14_consolidation(tmp_path):
    """PROJ.1.4.consolidation est noté quand l'ancre de consolidation est déplacée."""
    stats = _parse(tmp_path, _FIGHT_LOG)
    assert stats["rule_usage"]["PROJ.1.4.consolidation"][1] >= 1
