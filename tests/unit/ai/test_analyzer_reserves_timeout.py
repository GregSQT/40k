"""Destruction 20.04 en step.log : l'escouade détruite ne doit plus être traitée comme vivante.

Trou réparé le 2026-08-12 : `destroy_unarrived_strategic_reserves` n'émettait qu'un
`add_console_log` (debug-only, no-op en entraînement). Résultat : step.log ne portait aucune
trace de la destruction, et l'analyzer gardait les escouades concernées « vivantes » — leurs
socles faussaient l'engagement et les compteurs d'attrition.

CE QUE CE TEST VERROUILLE :
  - la ligne `RESERVES TIMEOUT` est parsée et marque l'escouade comme morte ;
  - le compteur `reserves_timeout_destroyed` est incrémenté ;
  - le chaînon `_STEP_LOG_TYPE_MAP` et le non-incrément `_STEP_LOG_NON_INCREMENTING_TYPES`
    sont couverts par test_step_logger.py (verrous séparés).
"""
from __future__ import annotations

import pytest

OBJECTIVES = ";".join(f"(30,{r})" for r in range(30, 33))

_HEADER = (
    "=== STEP-BY-STEP ACTION LOG ===\n"
    "================================================================================\n\n"
    "[10:00:00] === EPISODE 1 START ===\n"
    "[10:00:00] Scenario: scenario_bot-01\n"
    "[10:00:00] Rosters: scale=1 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)\n"
    "[10:00:00] Opponent: SelfplayBot\n"
    "[10:00:00] Walls: none\n"
    f"[10:00:00] Objectives: rect b NW:{OBJECTIVES}\n"
    "[10:00:00] Board: cols=40 rows=40 inches_to_subhex=1 hex_radius=2.78 margin=1\n"
    "[10:00:00] Run rules: engagement_zone_subhex=2 engagement_zone_vertical_inches=5.0 "
    "metric.engagement=hex metric.ranged=euclidean move.thru_ez=True move.thru_enemy=False "
    "move.thru_friendly=True cohesion.model_subhex=2 cohesion.global_subhex=9 "
    "cohesion.min_neighbors=1\n"
    # Unité 1 = en réserves (col=-1, row=-1 : sentinelle), jamais déployée
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
    "[10:00:00] Unit 101 (Intercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
    "[10:00:00] === ACTIONS START ===\n"
    # Unité 101 déployée, unité 1 reste en réserves — pas de DEPLOYMENT pour 1
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(30,30) DEPLOYED from (-1,-1) to (30,30) "
    "[R:+0.0] [MODELS: 101#0@(30,30,z0)] [SUCCESS]\n"
)

# Ligne de destruction 20.04 : l'escouade 1 (P1) jamais arrivée est détruite en fin de 3e round.
# Le player dans la ligne = le player de l'UNITÉ (pas le joueur dont c'est le tour) : c'est ainsi
# que l'action_log moteur est construit ("player": int(require_key(unit, "player"))).
# Le segment [MODELS:] est ABSENT (escouade entière détruite, plus rien dans units_cache).
_TIMEOUT_LINE = (
    "[10:00:02] E1 T3 P1 FIGHT : Unit 1 RESERVES TIMEOUT (20.04) "
    "[R:+0.0] [SUCCESS]\n"
)

_END = (
    "[10:00:08] T3 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
    "[10:00:09] EPISODE END: Winner=2, Method=objectives, Actions=0, Steps=0, "
    "Total=0, Duration=1.000s\n"
)


def _stats(tmp_path, body: str = ""):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(_HEADER + body + _END)
    return an.parse_step_log(str(log))


def test_reserves_timeout_increments_counter(tmp_path):
    """VERROU : supprimer la branche RESERVES TIMEOUT de l'analyzer rend ce test ROUGE."""
    stats = _stats(tmp_path, _TIMEOUT_LINE)
    assert stats["reserves_timeout_destroyed"][1] == 1, (
        "la ligne RESERVES TIMEOUT doit incrémenter le compteur du joueur 1"
    )
    assert stats["reserves_timeout_destroyed"][2] == 0


def test_reserves_timeout_does_not_appear_in_death_orders(tmp_path):
    """Le timeout 20.04 n'est pas un kill : l'unité ne doit PAS figurer dans death_orders."""
    stats = _stats(tmp_path, _TIMEOUT_LINE)
    # coherency_removal a le même comportement : la mort par règle n'est pas créditée à un joueur.
    # death_orders ne doit pas contenir l'escouade 1 — sinon player_kills[1] serait faussé.
    # Ce log ne contient aucune mort par attaque : death_orders doit être vide.
    assert stats["death_orders"] == [], (
        "timeout 20.04 ne doit PAS être compté comme kill dans death_orders"
    )


def test_no_reserves_timeout_no_counter(tmp_path):
    """Sans ligne RESERVES TIMEOUT, le compteur reste à 0."""
    stats = _stats(tmp_path)
    assert stats["reserves_timeout_destroyed"] == {1: 0, 2: 0}


def test_reserves_timeout_rule_usage_noted(tmp_path):
    """20.04 doit être noté comme exercée : `rule_usage["20.04"]` doit être > 0."""
    stats = _stats(tmp_path, _TIMEOUT_LINE)
    assert stats["rule_usage"]["20.04"][1] == 1, (
        "20.04 doit être comptée comme exercée pour le joueur 1"
    )
