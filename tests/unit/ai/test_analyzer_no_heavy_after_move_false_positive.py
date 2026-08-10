"""L'analyzer ne doit PLUS inventer d'usage invalide de [HEAVY] après un petit déplacement.

Régression verrouillée (2026-07-29, V11 §0hist.38). `ai/analyzer_phases/shoot_handler.py`
comptait `weapon_rule_invalid_usage[("HEAVY", …)]` dès que le tireur figurait dans
`units_moved` ou `units_advanced` — la borne conservatrice « aucune figurine n'a bougé »,
qui était celle du moteur AVANT le 2026-07-26.

PDF 24.16 (source de vérité) : le bonus s'applique si **aucune figurine de l'unité n'a
parcouru PLUS DE 3"** ce tour (plus les clauses « unengaged » et « pas posée ce tour »). Une
escouade qui s'est repositionnée de 2" garde donc son bonus, légitimement — et le moteur le
lui accorde depuis `_unit_moved_more_than_heavy_threshold`
(`engine/phase_handlers/shared_utils.py`), verrouillé par `tests/unit/engine/test_heavy_shoot.py`.

DEUX raisons de retirer le contrôle plutôt que de le réparer :

1. **Il n'est pas réparable depuis step.log.** Le critère du moteur porte sur la distance
   RÉELLEMENT parcourue par figurine (`moved_distance_by_model`, longueur de chemin
   GÉODÉSIQUE accumulée par `commit_move` : contourner un mur coûte plus cher que l'écart
   départ↔arrivée). La ligne `MOVED from (c,r) to (c,r)` ne porte que les ANCRES : ni la
   distance de chemin, ni le per-figurine. Aucune reconstruction fidèle n'est possible.
2. **Le moteur est déjà l'autorité.** Le token `[HEAVY]` n'est émis QUE lorsque le moteur a
   effectivement appliqué le bonus (`heavy_applied`), après avoir testé les trois clauses.
   Re-dériver la validité à côté ne peut produire qu'un désaccord avec l'autorité.

Même arbitrage que pour la LoS ancre-à-ancre (`test_analyzer_no_anchor_los_false_positive.py`)
et le « Fight from non-adjacent » (`test_analyzer_no_fight_non_adjacent_false_positive.py`) :
contrôle retiré de l'analyzer, vérification portée par le test moteur.

Ce test échoue sur l'ancien code : le tireur bouge de 2" (≤ 3") puis tire avec le bonus
appliqué → l'ancien analyzer comptait 1 usage INVALIDE.
"""
from __future__ import annotations

import pytest

UNIT_TYPE = "TerminatorAssaultCannon"
WEAPON_NAME = "Assault Cannon"
START = (50, 50)
AFTER_MOVE = (60, 50)  # 10 subhex = 2" (inches_to_subhex=5) — sous le seuil des 3"
TARGET = (90, 50)      # 30 subhex = 6" — dans les 24" de l'arme
OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))

STEP_LOG = f"""=== STEP-BY-STEP ACTION LOG ===
================================================================================

[10:00:00] === EPISODE 1 START ===
[10:00:00] Scenario: scenario_bot-01
[10:00:00] Opponent: SelfplayBot
[10:00:00] Walls:
[10:00:00] Objectives: rect b NW:{OBJECTIVES}
[10:00:00] Board: cols=220 rows=300 inches_to_subhex=5 hex_radius=2.78 margin=1
[10:00:00] Run rules: engagement_zone_subhex=10 metric.engagement=hex metric.ranged=euclidean move.thru_ez=True move.thru_enemy=False move.thru_friendly=True cohesion.model_subhex=10 cohesion.global_subhex=45 cohesion.min_neighbors=1
[10:00:00] Unit 1 ({UNIT_TYPE}) P1: Starting position (-1,-1), HP_MAX=2 base=round/6
[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6
[10:00:00] === ACTIONS START ===
[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{START} DEPLOYED from (-1,-1) to {START} [R:+0.0] [SUCCESS]
[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{TARGET} DEPLOYED from (-1,-1) to {TARGET} [R:+0.0] [SUCCESS]
[10:00:02] E1 T1 P1 MOVE : Unit 1{AFTER_MOVE} MOVED from {START} to {AFTER_MOVE} [R:+0.0] [SUCCESS]
[10:00:03] E1 T1 P1 SHOOT : Unit 1{AFTER_MOVE} SHOT Unit 101{TARGET} with [{WEAPON_NAME}] - Hit 4(3+->2+) [HEAVY] - Wound 5(3+) - Save 2(2+) - Dmg:1HP [R:+0.0] [SUCCESS]
"""


@pytest.fixture
def stats(tmp_path):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(STEP_LOG)
    return an.parse_step_log(str(log))


def test_premise_l_analyzer_a_bien_vu_un_deplacement(stats):
    """Sans cette prémisse le test ne prouve rien : il FAUT que l'analyzer ait enregistré le
    déplacement, sinon l'ancien critère ne se serait pas déclenché de toute façon."""
    assert stats["actions_by_type"]["move"] == 1, stats["actions_by_type"]
    # Et ce déplacement fait 2" : 10 subhex sur inches_to_subhex=5, donc sous le seuil 24.16.
    assert abs(AFTER_MOVE[0] - START[0]) == 10


def test_le_compteur_d_usage_invalide_est_supprime(stats):
    """Le compteur a été SUPPRIMÉ, pas remis à zéro : il n'était pas réparable depuis step.log
    (distance de chemin géodésique par figurine absente du log). Le remettre à zéro aurait
    laissé une mécanique prête à re-inventer le même faux positif.

    Sur l'ancien code ce test échoue sur l'assertion suivante : la clé existait et portait
    `{('HEAVY', 'Assault Cannon (TerminatorAssaultCannon)'): {1: 1, 2: 0}}` — un usage
    invalide inventé pour un déplacement de 2" parfaitement légal."""
    assert "weapon_rule_invalid_usage" not in stats
    assert "weapon_rule_invalid_first_lines" not in stats


def test_l_usage_de_heavy_reste_compte(stats):
    """Le contrôle de VALIDITÉ disparaît, pas le compteur d'USAGE : « la règle a-t-elle
    servi ? » reste une question à laquelle step.log peut répondre."""
    usage = {k: v for k, v in stats["weapon_rule_usage"].items() if k[0] == "HEAVY"}
    assert usage and any(sum(v.values()) > 0 for v in usage.values()), usage
