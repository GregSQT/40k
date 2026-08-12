"""La portée d'un tir se juge sur les positions d'AVANT les pertes, jamais sur `[TARGET_MODELS:]`.

Régression verrouillée (2026-08-12). `shoot_handler` mesurait la distance vers le segment
`[TARGET_MODELS:]` de la ligne. Or ce segment liste les survivants **post-pertes** et n'est émis
que sur le DERNIER jet visant la cible (`w40k_core`) : la figurine visée — la plus proche, celle
sur laquelle le moteur a jugé la portée — en disparaît dès qu'elle meurt du tir. L'analyzer
mesurait alors la distance au survivant suivant, plus loin, et déclarait le tir hors portée.

`step_logger` énonce d'ailleurs le contrat à la source : ce segment est « consommé UNIQUEMENT par
le replay », tenu distinct de `[MODELS:]` précisément pour ne pas perturber l'analyzer.

MESURÉ sur le run du 2026-08-12 (600 épisodes, 27 991 tirs) : **35 verdicts `out_of_range`,
tous artefacts** — zéro tir réellement illégal. Après correction, le contrôle rend encore
18 702 verdicts et n'en condamne aucun : il mesure, il ne s'est pas tu.

Même famille que le contrôle « fight from non-adjacent », retiré le 2026-07-24 pour cette raison.

CE QUE CE TEST CONSTRUIT — et il ne prouve rien sans ça : une cible de DEUX figurines dont une
seule est à portée. Le tir la tue, donc `[TARGET_MODELS:]` ne liste plus que la lointaine.
  - ancienne source (segment)        → 32" mesurés pour une arme de 24" → 1 erreur ;
  - source correcte (avant l'action) → 12" → 0 erreur.
"""
from __future__ import annotations

import pytest

# Board x1 (inches_to_subhex=1) : 1 hex = 1 pouce, la lecture des distances est directe.
SHOOTER = (10, 20)
PROCHE = (22, 20)    # 12 hex du tireur : DANS les 24" du Sternguard Bolt Rifle
LOIN = (42, 20)      # 32 hex : HORS des 24"
OBJECTIVES = ";".join(f"(60,{r})" for r in range(40, 46))

STEP_LOG = f"""=== STEP-BY-STEP ACTION LOG ===
================================================================================

[10:00:00] === EPISODE 1 START ===
[10:00:00] Scenario: scenario_bot-01
[10:00:00] Opponent: SelfplayBot
[10:00:00] Walls:
[10:00:00] Objectives: rect b NW:{OBJECTIVES}
[10:00:00] Board: cols=44 rows=60 inches_to_subhex=1 hex_radius=13.9 margin=5
[10:00:00] Run rules: engagement_zone_subhex=2 engagement_zone_vertical_inches=5.0 metric.engagement=hex metric.ranged=hex move.thru_ez=True move.thru_enemy=False move.thru_friendly=True cohesion.model_subhex=2 cohesion.global_subhex=9 cohesion.min_neighbors=1
[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (-1,-1), HP_MAX=2 base=round/1
[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/1
[10:00:00] === ACTIONS START ===
[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) DEPLOYED from (-1,-1) to ({SHOOTER[0]},{SHOOTER[1]}) [R:+0.0] [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SUCCESS]
[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101({PROCHE[0]},{PROCHE[1]}) DEPLOYED from (-1,-1) to ({PROCHE[0]},{PROCHE[1]}) [R:+0.0] [MODELS: 101#0@({PROCHE[0]},{PROCHE[1]},z0) 101#1@({LOIN[0]},{LOIN[1]},z0)] [SUCCESS]
[10:00:02] E1 T1 P1 SHOOT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) SHOT Unit 101({PROCHE[0]},{PROCHE[1]}) with [Sternguard Bolt Rifle] - Hit 4(5+) - Wound 5(4+) - Save 2(5+) - Dmg:1HP [R:+0.0] [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [TARGET_MODELS: 101#1@({LOIN[0]},{LOIN[1]},z0)] [SHOOTER_MODELS: 1#0] [SUCCESS]
"""


# Deuxième journal : une activation de DEUX tirs sur une cible entièrement HORS portée, dont le
# premier tue une figurine. La carte per-socle vive est purgée à cette perte (le journal ne dit pas
# quelle figurine tombe) : sans le gel au Select Targets step, le contrôle de portée n'a plus aucune
# source à partir de la deuxième ligne et cesse SILENCIEUSEMENT de juger le reste de l'activation.
LOIN_2 = (44, 20)  # 34 hex : hors portée, comme LOIN
STEP_LOG_ACTIVATION = f"""=== STEP-BY-STEP ACTION LOG ===
================================================================================

[10:00:00] === EPISODE 1 START ===
[10:00:00] Scenario: scenario_bot-01
[10:00:00] Opponent: SelfplayBot
[10:00:00] Walls:
[10:00:00] Objectives: rect b NW:{OBJECTIVES}
[10:00:00] Board: cols=48 rows=60 inches_to_subhex=1 hex_radius=13.9 margin=5
[10:00:00] Run rules: engagement_zone_subhex=2 engagement_zone_vertical_inches=5.0 metric.engagement=hex metric.ranged=hex move.thru_ez=True move.thru_enemy=False move.thru_friendly=True cohesion.model_subhex=2 cohesion.global_subhex=9 cohesion.min_neighbors=1
[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (-1,-1), HP_MAX=2 base=round/1
[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/1
[10:00:00] === ACTIONS START ===
[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) DEPLOYED from (-1,-1) to ({SHOOTER[0]},{SHOOTER[1]}) [R:+0.0] [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SUCCESS]
[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101({LOIN[0]},{LOIN[1]}) DEPLOYED from (-1,-1) to ({LOIN[0]},{LOIN[1]}) [R:+0.0] [MODELS: 101#0@({LOIN[0]},{LOIN[1]},z0) 101#1@({LOIN_2[0]},{LOIN_2[1]},z0)] [SUCCESS]
[10:00:02] E1 T1 P1 SHOOT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) SHOT Unit 101({LOIN[0]},{LOIN[1]}) with [Sternguard Bolt Rifle] - Hit 4(5+) - Wound 5(4+) - Save 2(5+) - Dmg:2HP [R:+0.0] [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SHOOTER_MODELS: 1#0] [SUCCESS]
[10:00:02] E1 T1 P1 SHOOT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) SHOT Unit 101({LOIN_2[0]},{LOIN_2[1]}) with [Sternguard Bolt Rifle] - Hit 4(5+) - Wound 5(4+) - Save 2(5+) - Dmg:1HP [R:+0.0] [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SHOOTER_MODELS: 1#0] [SUCCESS]
"""


@pytest.fixture
def stats(tmp_path):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(STEP_LOG)
    return an.parse_step_log(str(log))


def test_premisse_la_figurine_visee_est_a_portee_et_la_survivante_ne_l_est_pas():
    """Sans cet écart le test ne prouve rien : les deux mesures rendraient le même verdict."""
    from engine.hex_utils import offset_to_cube

    def d(a, b):
        ax, ay, az = offset_to_cube(*a)
        bx, by, bz = offset_to_cube(*b)
        return max(abs(ax - bx), abs(ay - by), abs(az - bz))

    assert d(SHOOTER, PROCHE) <= 24, "la figurine visée doit être À PORTÉE de l'arme"
    assert d(SHOOTER, LOIN) > 24, "la survivante listée doit être HORS portée"


def test_un_tir_legitime_n_est_pas_compte_hors_portee(stats):
    """VERROU : remettre `parse_target_models_segment(action_desc)` comme source rend ce test ROUGE
    (le survivant lointain est alors la seule cible mesurée → 1 `out_of_range`)."""
    assert stats["shoot_invalid"][1]["out_of_range"] == 0, (
        "portée jugée sur les survivants POST-pertes : la figurine visée, à portée, a été tuée "
        "par ce tir et ne figure plus dans [TARGET_MODELS:]"
    )


def test_le_controle_rend_bien_un_verdict(stats):
    """Un contrôle qui ne juge plus rien afficherait 0 sans rien regarder — pire que le faux
    positif qu'on retire. Le tir doit avoir été COMPTÉ, donc mesuré.

    Les DEUX assertions sont nécessaires, et la seconde est la seule qui porte sur la PORTÉE :
    `total` compte les lignes de tir traitées, et il est incrémenté à l'entrée du handler,
    bien avant le bloc de portée — une ligne peut donc y figurer sans qu'aucune distance ait
    été mesurée. `shoot_range_unverifiable` compte exactement les tirs auxquels le contrôle a
    RENONCÉ : à 0, il a jugé ; sans lui, « 0 hors portée » ne se distingue pas d'un silence.
    """
    assert stats["shoot_invalid"][1]["total"] == 1
    assert stats["shoot_range_unverifiable"][1] == 0


def test_premisse_les_deux_figurines_sont_hors_portee():
    """Sans cette prémisse, le test suivant ne distingue pas « pas de verdict » de « verdict 0 »."""
    from engine.hex_utils import offset_to_cube

    def d(a, b):
        ax, ay, az = offset_to_cube(*a)
        bx, by, bz = offset_to_cube(*b)
        return max(abs(ax - bx), abs(ay - by), abs(az - bz))

    assert d(SHOOTER, LOIN) > 24 and d(SHOOTER, LOIN_2) > 24


def test_la_deuxieme_ligne_d_une_activation_est_encore_jugee(tmp_path):
    """VERROU — extinction SILENCIEUSE du contrôle après la première perte de l'activation.

    La carte per-socle vive est purgée dès qu'une figurine tombe : lue telle quelle, le contrôle
    n'avait plus de socles à mesurer et ne rendait AUCUN verdict pour le reste de l'activation.
    Un contrôle qui se tait ne se distingue pas d'un contrôle qui absout. Les deux tirs sont hors
    portée, les deux doivent être comptés.
    """
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(STEP_LOG_ACTIVATION)
    stats = an.parse_step_log(str(log))
    assert stats["shoot_invalid"][1]["out_of_range"] == 2
    # Et AUCUN des deux tirs n'a échappé à la mesure : c'est ce que l'extinction silencieuse
    # produisait — deux lignes traitées, zéro distance mesurée, zéro faute affichée.
    assert stats["shoot_range_unverifiable"][1] == 0

# Troisième journal : la cible perd une figurine dans une activation, puis un AUTRE tireur la vise
# dans une activation SUIVANTE. Entre les deux, aucun segment ne redonne ses socles : le gel de la
# nouvelle activation part donc d'une carte vide, et le contrôle ne PEUT pas juger. C'est le seul
# cas où renoncer est légitime — et c'est celui que le compteur doit rendre visible.
STEP_LOG_SANS_SOCLE = f"""=== STEP-BY-STEP ACTION LOG ===
================================================================================

[10:00:00] === EPISODE 1 START ===
[10:00:00] Scenario: scenario_bot-01
[10:00:00] Opponent: SelfplayBot
[10:00:00] Walls:
[10:00:00] Objectives: rect b NW:{OBJECTIVES}
[10:00:00] Board: cols=48 rows=60 inches_to_subhex=1 hex_radius=13.9 margin=5
[10:00:00] Run rules: engagement_zone_subhex=2 engagement_zone_vertical_inches=5.0 metric.engagement=hex metric.ranged=hex move.thru_ez=True move.thru_enemy=False move.thru_friendly=True cohesion.model_subhex=2 cohesion.global_subhex=9 cohesion.min_neighbors=1
[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (-1,-1), HP_MAX=2 base=round/1
[10:00:00] Unit 2 (SternguardVeteranBoltRifle) P1: Starting position (-1,-1), HP_MAX=2 base=round/1
[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/1
[10:00:00] === ACTIONS START ===
[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) DEPLOYED from (-1,-1) to ({SHOOTER[0]},{SHOOTER[1]}) [R:+0.0] [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SUCCESS]
[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2({SHOOTER[0]},{SHOOTER[1] + 2}) DEPLOYED from (-1,-1) to ({SHOOTER[0]},{SHOOTER[1] + 2}) [R:+0.0] [MODELS: 2#0@({SHOOTER[0]},{SHOOTER[1] + 2},z0)] [SUCCESS]
[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101({PROCHE[0]},{PROCHE[1]}) DEPLOYED from (-1,-1) to ({PROCHE[0]},{PROCHE[1]}) [R:+0.0] [MODELS: 101#0@({PROCHE[0]},{PROCHE[1]},z0) 101#1@({LOIN[0]},{LOIN[1]},z0)] [SUCCESS]
[10:00:02] E1 T1 P1 SHOOT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) SHOT Unit 101({PROCHE[0]},{PROCHE[1]}) with [Sternguard Bolt Rifle] - Hit 4(5+) - Wound 5(4+) - Save 2(5+) - Dmg:2HP [R:+0.0] [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SHOOTER_MODELS: 1#0] [SUCCESS]
[10:00:03] E1 T2 P1 SHOOT : Unit 2({SHOOTER[0]},{SHOOTER[1] + 2}) SHOT Unit 101({PROCHE[0]},{PROCHE[1]}) with [Sternguard Bolt Rifle] - Hit 4(5+) [R:+0.0] [MODELS: 2#0@({SHOOTER[0]},{SHOOTER[1] + 2},z0)] [SHOOTER_MODELS: 2#0] [SUCCESS]
"""


def test_un_tir_non_jugeable_est_compte_comme_tel(tmp_path):
    """TÉMOIN POSITIF du compteur : à 0 partout, il ne prouverait rien.

    Ici le contrôle a une raison LÉGITIME de se taire — plus aucun socle connu pour la cible.
    Il doit alors le DIRE, pas afficher la même chose qu'un tir jugé conforme. Sans cette
    assertion, un compteur cassé (jamais incrémenté) passerait tous les autres tests du fichier.
    """
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(STEP_LOG_SANS_SOCLE)
    stats = an.parse_step_log(str(log))

    assert stats["shoot_range_unverifiable"][1] == 1, (
        "le second tir a été jugé alors qu'aucun socle de la cible n'est connu, ou son "
        "renoncement n'a pas été compté"
    )
    assert stats["shoot_invalid"][1]["out_of_range"] == 0
