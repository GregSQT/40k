"""Les positions de socles morts d'une activation précédente ne doivent pas polluer le gel
de Select Targets d'une activation ultérieure.

MÉCANISME DU BUG (avant le fix du 2026-08-19)
──────────────────────────────────────────────
1. T1 P1 FIGHT : retrait de cohérence 2#10 (03.03) → `dead_model_positions_episode["2"]`
   accumule la position de 2#10@STALE_POS.
2. T2 P1 MOVE : Unit 2 bouge. `_resync_living_models` est appelé avec la liste des socles
   vivants — inchangée depuis le retrait (même effectif, même IDs). `removed = {}`.
   SANS LE FIX : le cas `else` n'existait pas, aucun nettoyage n'avait lieu.
   AVEC LE FIX  : le `else` vide `dead_model_positions_episode["2"]`.
3. T2 P2 SHOOT : Unit 104 vise Unit 2. `freeze_select_targets` dépile
   `dead_model_positions_episode["2"]`.
   SANS LE FIX : STALE_POS (à portée du tireur 104) est incluse → faux engagement →
   `engaged_non_close_quarters` == 1.
   AVEC LE FIX  : dict vide → seuls 2#0 / 2#1 (loin de 104) → 0.

CE QUE CE TEST CONSTRUIT
─────────────────────────
- Unit 2 (P1, cible) déployée avec 3 socles : 2#0 / 2#1 loin du tireur, 2#10 à exactement
  EZ_HEX hexagones de 104.
- T1 FIGHT : retrait de cohérence 2#10 → position périmée accumulée.
- T2 MOVE   : Unit 2 bouge (tous les survivants intacts → removed = {}).
- T2 SHOOT  : Unit 104 tire sur Unit 2.
  · Sans le MOVE (stats_sans_move) : position périmée encore là → 1 erreur.
  · Avec le MOVE (stats_avec_move) : position purgée par le MOVE → 0 erreur.
"""
from __future__ import annotations

import pytest

from tests.unit.ai._fabriques import entete_step_log

# ─────────────────────────────────────────────────────────────────────────────
# Géométrie (inches_to_subhex=1 : 1 hex = 1 pouce = 1 subhex)
# ─────────────────────────────────────────────────────────────────────────────
EZ_HEX = 2          # engagement_zone_subhex = 2 * inches_to_subhex = 2
SHOOTER_POS = (34, 10)              # 104#0
STALE_POS   = (34, 12)              # 2#10 retiré en T1 FIGHT — à distance EZ_HEX du tireur
SAFE_POS_0  = (30, 1)               # 2#0  — loin du tireur
SAFE_POS_1  = (30, 2)               # 2#1  — loin du tireur

_HEADER = entete_step_log(
    # Déploiement
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2({SAFE_POS_0[0]},{SAFE_POS_0[1]}) DEPLOYED"
    f" from (-1,-1) to ({SAFE_POS_0[0]},{SAFE_POS_0[1]}) [R:+0.0]"
    f" [MODELS: 2#0@({SAFE_POS_0[0]},{SAFE_POS_0[1]},z0)"
    f" 2#1@({SAFE_POS_1[0]},{SAFE_POS_1[1]},z0)"
    f" 2#10@({STALE_POS[0]},{STALE_POS[1]},z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 104({SHOOTER_POS[0]},{SHOOTER_POS[1]}) DEPLOYED"
    f" from (-1,-1) to ({SHOOTER_POS[0]},{SHOOTER_POS[1]}) [R:+0.0]"
    f" [MODELS: 104#0@({SHOOTER_POS[0]},{SHOOTER_POS[1]},z0)] [SUCCESS]\n",
    units=(
        "[10:00:00] Unit 2 (SternguardVeteranBoltRifle) P1:"
        " Starting position (-1,-1), HP_MAX=2 base=round/1\n"
        # Intercessor : seul unit type avec bolt_rifle (non-[CLOSE_QUARTERS]) → weapon_found=True
        # ce qui est requis pour que engaged_non_close_quarters soit compté (shoot_handler.py L801).
        "[10:00:00] Unit 104 (Intercessor) P2:"
        " Starting position (-1,-1), HP_MAX=2 base=round/1\n"
    ),
    inches_to_subhex=1,
    board="cols=44 rows=60",
    hex_radius="13.9",
    margin=5,
    objectives=None,   # pas besoin de snapshot objectifs
    metric_ranged="hex",
    ez_vertical_inches=5.0,   # requis quand heights_by_model est non-vide (z0 peuplés)
)

# T1 FIGHT : retrait de cohérence — 2#10 disparaît du [MODELS:]
_COHERENCY_REMOVAL = (
    f"[10:00:02] E1 T1 P1 FIGHT : Unit 2({SAFE_POS_0[0]},{SAFE_POS_0[1]})"
    f" COHERENCY REMOVED 2#10 (03.03)"
    f" [MODELS: 2#0@({SAFE_POS_0[0]},{SAFE_POS_0[1]},z0)"
    f" 2#1@({SAFE_POS_1[0]},{SAFE_POS_1[1]},z0)] [SUCCESS]\n"
)

# T2 MOVE : Unit 2 bouge (survivants intacts → removed = {} → else branch purge les positions)
_MOVE = (
    f"[10:00:03] E1 T2 P1 MOVE : Unit 2({SAFE_POS_0[0]},{SAFE_POS_0[1]})"
    f" MOVED from ({SAFE_POS_0[0]},{SAFE_POS_0[1]})"
    f" to ({SAFE_POS_0[0]},{SAFE_POS_0[1]}) [R:+0.0]"
    f" [MODELS: 2#0@({SAFE_POS_0[0]},{SAFE_POS_0[1]},z0)"
    f" 2#1@({SAFE_POS_1[0]},{SAFE_POS_1[1]},z0)] [SUCCESS]\n"
)

# T2 SHOOT : Unit 104 tire sur Unit 2
_SHOOT = (
    f"[10:00:04] E1 T2 P2 SHOOT : Unit 104({SHOOTER_POS[0]},{SHOOTER_POS[1]})"
    f" SHOT Unit 2({SAFE_POS_0[0]},{SAFE_POS_0[1]}) with [Bolt Rifle]"
    f" - Hit 1(3+) - Wound 0(4+) - Dmg:0HP [R:+0.0]"
    f" [MODELS: 104#0@({SHOOTER_POS[0]},{SHOOTER_POS[1]},z0)] [SUCCESS]\n"
)


def _stats(tmp_path, log_text, name):
    import ai.analyzer as an

    log = tmp_path / name
    log.write_text(log_text)
    return an.parse_step_log(str(log))


@pytest.fixture
def stats_avec_move(tmp_path):
    """Retrait cohérence + MOVE + SHOOT : la position périmée doit être purgée par le MOVE."""
    return _stats(tmp_path, _HEADER + _COHERENCY_REMOVAL + _MOVE + _SHOOT, "avec_move.log")


@pytest.fixture
def stats_sans_move(tmp_path):
    """Retrait cohérence + SHOOT direct (pas de MOVE) : la position périmée reste.

    Ce fixture sert de VERROU DU VERROU : il prouve que la position périmée cause bien un
    faux engagement détecté. Sans lui, un log qui ne produirait jamais d'engagement ne
    prouverait rien sur le fix.
    """
    return _stats(tmp_path, _HEADER + _COHERENCY_REMOVAL + _SHOOT, "sans_move.log")


def test_premisse_la_position_perimee_est_dans_la_zone_d_engagement():
    """La position stale (34,12) doit être à exactement EZ_HEX hexagones du tireur (34,10).

    Si ce n'était pas le cas, le faux engagement ne se produirait pas et la suite ne prouverait
    rien.
    """
    from engine.hex_utils import offset_to_cube

    def hex_dist(a, b):
        ax, ay, az = offset_to_cube(*a)
        bx, by, bz = offset_to_cube(*b)
        return max(abs(ax - bx), abs(ay - by), abs(az - bz))

    assert hex_dist(STALE_POS, SHOOTER_POS) == EZ_HEX, (
        f"STALE_POS={STALE_POS} doit être à {EZ_HEX} hex de SHOOTER_POS={SHOOTER_POS}"
    )
    assert hex_dist(SAFE_POS_0, SHOOTER_POS) > EZ_HEX, (
        f"Les survivants de Unit 2 doivent être HORS zone d'engagement de 104"
    )


def test_verrou_du_verrou_sans_move_la_position_perimee_produit_un_faux_engagement(stats_sans_move):
    """SANS le MOVE, dead_model_positions_episode conserve 2#10@STALE_POS.

    freeze_select_targets la dépile → la position stale est incluse dans l'état gelé → le tireur
    104 est détecté « engagé » (distance = EZ_HEX) → engaged_non_close_quarters == 1.

    Ce test reste ROUGE avant ET après le fix du `else` dans `_resync_living_models` : le fix ne
    nettoie les positions qu'à l'occasion d'un [MODELS:] avec removed={}. Sans MOVE, rien ne
    déclenche ce nettoyage.

    Son rôle est de prouver que la mécanique (position stale → faux engagement) est réelle et
    mesurable, pas de valider le fix lui-même.
    """
    assert stats_sans_move["shoot_invalid"][2]["engaged_non_close_quarters"] == 1, (
        "La position périmée 2#10@STALE_POS doit produire un faux engagement pour Unit 104"
    )


def test_le_move_purge_les_positions_perimees(stats_avec_move):
    """AVEC le MOVE, dead_model_positions_episode est vidé → la position stale n'atteint pas le
    gel de Select Targets → tireur non engagé → 0 faute.

    Ce test était ROUGE avant le fix (le `else` n'existait pas dans `_resync_living_models`)
    et VERT après.
    """
    assert stats_avec_move["shoot_invalid"][2]["engaged_non_close_quarters"] == 0, (
        "Le MOVE doit avoir purgé la position stale 2#10@STALE_POS : 0 faux engagement attendu"
    )
