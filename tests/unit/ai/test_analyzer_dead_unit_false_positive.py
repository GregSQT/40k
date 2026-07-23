"""L'analyzer ne doit PLUS inventer d'interaction « unité morte » sur les escouades
multi-figurines ni sur les attaques restantes d'une même activation.

Régression verrouillée (2026-07-23). `ai/analyzer.py::_apply_damage_and_handle_death`
initialisait `unit_hp[squad] = HP_MAX` (PV d'UNE figurine, lu au registry) au lieu du total
d'escouade. Il décrémentait ce compteur unique avec les dégâts de TOUS les attaquants et
déclarait l'escouade entière morte dès que le cumul dépassait le PV d'une figurine → toute
attaque suivante était comptée `shoot_at_dead_unit` / `fight_dead_unit_target` /
`damage_missing_unit_hp`. Sur un run réel : 41 fausses « dead unit interactions » + 15 « DMG
issues », zéro violation moteur.

Correctif : modèle HP par-figurine (05 Attack sequence). unit_hp = PV de la figurine front,
`unit_models_alive` = nb de figurines vivantes (source de vérité = segment [MODELS:]), overkill
perdu, escouade retirée seulement à la mort de sa DERNIÈRE figurine. Les attaques restantes de
LA MÊME activation qui a détruit la cible sont des « excess attacks lost » (05) et ne sont pas
comptées (clé `unit_kill_context`).
"""
from __future__ import annotations

import pytest

# Unit 101 = escouade de 3 figurines à 2 PV (registry HP_MAX=2) → 6 PV effectifs.
# Unit 1 lui inflige 4 tirs Dmg:2HP dans UNE seule activation (T1 P1 SHOOT) :
#   tir 1 → 1re figurine morte (escouade vivante),
#   tir 2 → 2e figurine morte (escouade vivante),
#   tir 3 → 3e/dernière figurine morte → escouade détruite,
#   tir 4 → « excess attack lost » (même activation).
# L'ancien modèle comptait les tirs 2,3,4 comme tir sur unité morte + dégât sans unit_hp.
OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))
DEPLOY_MODELS = "[MODELS: 101#0@(80,50) 101#1@(84,50) 101#2@(88,50)]"

STEP_LOG = f"""=== STEP-BY-STEP ACTION LOG ===
================================================================================

[10:00:00] === EPISODE 1 START ===
[10:00:00] Scenario: scenario_bot-01
[10:00:00] Opponent: SelfplayBot
[10:00:00] Walls:
[10:00:00] Objectives: rect b NW:{OBJECTIVES}
[10:00:00] Board: cols=220 rows=300 inches_to_subhex=5 hex_radius=2.78 margin=1
[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (50,50), HP_MAX=2 base=round/6 [MODELS: 1#0@(50,50)]
[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (80,50), HP_MAX=2 base=round/6 {DEPLOY_MODELS}
[10:00:00] === ACTIONS START ===
[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [SUCCESS]
[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(80,50) DEPLOYED from (-1,-1) to (80,50) [R:+0.0] [SUCCESS]
[10:00:02] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 101(80,50) with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:2HP [R:+0.0] [SUCCESS]
[10:00:02] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 101(80,50) with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:2HP [R:+0.0] [SUCCESS]
[10:00:02] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 101(80,50) with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:2HP [R:+0.0] [SUCCESS]
[10:00:02] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 101(80,50) with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:2HP [R:+0.0] [SUCCESS]
"""


@pytest.fixture
def stats(tmp_path):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(STEP_LOG)
    return an.parse_step_log(str(log))


def test_multi_model_squad_not_flagged_dead_prematurely(stats):
    """Les tirs 2 et 3 (2e et 3e figurine) frappent une escouade encore vivante : aucun ne
    doit être compté comme tir sur unité morte."""
    assert stats["shoot_at_dead_unit"][1] == 0
    assert stats["shoot_at_dead_unit"][2] == 0


def test_excess_attack_after_squad_wiped_is_not_an_error(stats):
    """Le 4e tir, postérieur à la destruction de l'escouade dans LA MÊME activation, est une
    « excess attack lost » (05 Attack sequence) → ni tir-sur-mort, ni dégât orphelin."""
    assert stats["damage_missing_unit_hp"][1] == 0
    assert stats["shoot_at_dead_unit"][1] == 0


def test_squad_is_eventually_destroyed(stats):
    """La correction ne masque pas la mort : après 3 figurines × 2 PV encaissés, l'escouade
    figure bien parmi les morts de l'épisode."""
    dead_ids = {uid for (_player, uid, _utype) in stats["current_episode_deaths"]}
    assert "101" in dead_ids
