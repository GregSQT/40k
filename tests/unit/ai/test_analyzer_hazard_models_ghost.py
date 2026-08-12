"""La ligne [HAZARD] doit porter [MODELS:] pour ne pas laisser de socles morts pour vivants.

`roll_hazard_for_unit` pose `"unitId": int(unit_id)` dans son payload, mais `units_cache` est
clé par CHAÎNE. Avant le fix du 2026-08-12, `_models_segment_for_unit` cherchait l'entrée avec
la valeur brute — le lookup échouait en silence pour les `int`, et la ligne `[HAZARDOUS]` sortait
sans `[MODELS:]`. Résultat : quand une blessure mortelle tuait un socle d'une escouade qui
survivait, le lecteur du journal ne le voyait pas et gardait l'ancien socle mort pour vivant.

CE QUE CE TEST CONSTRUIT : une escouade P1 à deux socles est touchée par une arme [HAZARDOUS]
et perd son socle A, dont la position est à portée d'engagement du point de départ de P2. Le
socle B survivant est loin. P2 avance ensuite depuis ce point.

  - sans [MODELS:] sur la ligne [HAZARD] (état d'avant le fix) → 1 « advance from adjacent » :
    le lecteur croit que P1 a encore un socle à portée d'engagement de P2 ;
  - avec [MODELS:]                                              → 0.
"""
from __future__ import annotations

import pytest

# Board x1 (inches_to_subhex=1) : 1 hex = 1 pouce.
A_DEAD = (5, 10)    # socle 1#0 : tué par [HAZARDOUS], reste à portée d'engagement de P2
A_ALIVE = (20, 10)  # socle 1#1 : survit, loin de P2
B_FROM = (7, 10)    # départ de P2 : à 2 hex de A_DEAD (dans la zone d'engagement=2)
B_TO = (15, 10)     # arrivée de P2 : hors zone d'engagement des deux socles

_HEADER = f"""=== STEP-BY-STEP ACTION LOG ===
================================================================================

[10:00:00] === EPISODE 1 START ===
[10:00:00] Scenario: scenario_bot-01
[10:00:00] Opponent: SelfplayBot
[10:00:00] Walls: none
[10:00:00] Objectives: rect b NW:(60,40);(60,41);(60,42)
[10:00:00] Board: cols=80 rows=80 inches_to_subhex=1 hex_radius=13.9 margin=5
[10:00:00] Run rules: engagement_zone_subhex=2 engagement_zone_vertical_inches=5.0 metric.engagement=hex metric.ranged=hex move.thru_ez=True move.thru_enemy=False move.thru_friendly=True cohesion.model_subhex=2 cohesion.global_subhex=9 cohesion.min_neighbors=1
[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (-1,-1), HP_MAX=2 base=round/1
[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/1
[10:00:00] === ACTIONS START ===
[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({A_DEAD[0]},{A_DEAD[1]}) DEPLOYED from (-1,-1) to ({A_DEAD[0]},{A_DEAD[1]}) [R:+0.0] [MODELS: 1#0@({A_DEAD[0]},{A_DEAD[1]},z0) 1#1@({A_ALIVE[0]},{A_ALIVE[1]},z0)] [SUCCESS]
[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101({B_FROM[0]},{B_FROM[1]}) DEPLOYED from (-1,-1) to ({B_FROM[0]},{B_FROM[1]}) [R:+0.0] [MODELS: 101#0@({B_FROM[0]},{B_FROM[1]},z0)] [SUCCESS]
"""

def _hazard_line(with_models: bool) -> str:
    suffix = f" [MODELS: 1#1@({A_ALIVE[0]},{A_ALIVE[1]},z0)]" if with_models else ""
    return (
        f"[10:00:02] E1 T1 P1 SHOOT : Unit 1({A_DEAD[0]},{A_DEAD[1]})"
        f" SUFFERS 1 Mortal Wounds [HAZARDOUS]{suffix} [SUCCESS]\n"
    )

_ADVANCE = (
    f"[10:00:03] E1 T1 P2 MOVE : Unit 101({B_TO[0]},{B_TO[1]}) ADVANCED from "
    f"({B_FROM[0]},{B_FROM[1]}) to ({B_TO[0]},{B_TO[1]}) [Roll: 2] [R:+0.0] "
    f"[MODELS: 101#0@({B_TO[0]},{B_TO[1]},z0)] [SUCCESS]\n"
)


def _stats(tmp_path, log_text, name):
    import ai.analyzer as an

    log = tmp_path / name
    log.write_text(log_text)
    return an.parse_step_log(str(log))


@pytest.fixture
def stats_avec_models(tmp_path):
    return _stats(tmp_path, _HEADER + _hazard_line(True) + _ADVANCE, "avec.log")


@pytest.fixture
def stats_sans_models(tmp_path):
    """État avant le fix : ligne [HAZARDOUS] sans [MODELS:], socle mort resté dans l'état."""
    return _stats(tmp_path, _HEADER + _hazard_line(False) + _ADVANCE, "sans.log")


def test_premisse_le_socle_mort_est_adjacent_et_le_survivant_ne_lest_pas():
    """Sans cet écart, les deux journaux rendraient le même verdict."""
    from engine.hex_utils import offset_to_cube

    def d(a, b):
        ax, ay, az = offset_to_cube(*a)
        bx, by, bz = offset_to_cube(*b)
        return max(abs(ax - bx), abs(ay - by), abs(az - bz))

    assert d(B_FROM, A_DEAD) <= 2, "le socle mort doit être dans la zone d'engagement de P2"
    assert d(B_FROM, A_ALIVE) > 2, "le socle survivant doit être hors zone d'engagement"


def test_sans_models_le_socle_mort_fabrique_un_advance_from_adjacent(stats_sans_models):
    """VERROU du verrou : c'est le comportement d'avant le fix.

    Si ce test devient vert, le journal « avec [MODELS:] » ne prouve plus rien — le contrôle
    ne regarderait plus rien.
    """
    assert stats_sans_models["advance_from_adjacent"][2] == 1, (
        "le socle mort de P1 ne devrait plus être dans l'état — le test ne mesure rien"
    )


def test_avec_models_le_socle_mort_est_purge(stats_avec_models):
    """VERROU : retirer le [MODELS:] de la ligne [HAZARDOUS] rend ce test ROUGE.

    Le segment [MODELS:] déclenche _resync_living_models, qui retire du suivi tous les socles
    absents de la liste. Sans lui, le socle mort reste dans positions_by_model et engage encore
    les ennemis du joueur, fabriquant de fausses violations dans tous les contrôles géométriques.
    """
    assert stats_avec_models["advance_from_adjacent"][2] == 0, (
        "le socle tué par [HAZARDOUS] engage encore : [MODELS:] n'a pas purgé l'état"
    )
