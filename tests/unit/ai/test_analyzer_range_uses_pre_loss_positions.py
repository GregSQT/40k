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

from typing import Any

import pytest

from engine.hex_utils import offset_to_cube
from tests.unit.ai._fabriques import entete_step_log


def _d(a: tuple, b: tuple) -> int:
    ax, ay, az = offset_to_cube(*a)
    bx, by, bz = offset_to_cube(*b)
    return max(abs(ax - bx), abs(ay - by), abs(az - bz))

# Board x1 (inches_to_subhex=1) : 1 hex = 1 pouce, la lecture des distances est directe.
SHOOTER = (10, 20)
PROCHE = (22, 20)    # 12 hex du tireur : DANS les 24" du Sternguard Bolt Rifle
LOIN = (42, 20)      # 32 hex : HORS des 24"
OBJECTIVES = ";".join(f"(60,{r})" for r in range(40, 46))

_COMMON: dict[str, Any] = dict(
    inches_to_subhex=1,
    hex_radius="13.9",
    margin=5,
    objectives=OBJECTIVES,
    metric_ranged="hex",
    units=(
        "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
        "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
    ),
)

STEP_LOG = entete_step_log(
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) DEPLOYED from (-1,-1) to ({SHOOTER[0]},{SHOOTER[1]}) [R:+0.0] [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101({PROCHE[0]},{PROCHE[1]}) DEPLOYED from (-1,-1) to ({PROCHE[0]},{PROCHE[1]}) [R:+0.0] [MODELS: 101#0@({PROCHE[0]},{PROCHE[1]},z0) 101#1@({LOIN[0]},{LOIN[1]},z0)] [SUCCESS]\n"
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) SHOT [DESIGNATED:101] Unit 101({PROCHE[0]},{PROCHE[1]}) with [Sternguard Bolt Rifle] - Hit 4(5+) - Wound 5(4+) - Save 2(5+) - Dmg:1HP [ALLOC_MODEL: 101#0] [R:+0.0] [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [TARGET_MODELS: 101#1@({LOIN[0]},{LOIN[1]},z0)] [SHOOTER_MODELS: 1#0] [SUCCESS]\n",
    board="cols=44 rows=60",
    **_COMMON,
)


# Deuxième journal : une activation de DEUX tirs sur une cible entièrement HORS portée, dont le
# premier tue une figurine. La carte per-socle vive est purgée à cette perte (le journal ne dit pas
# quelle figurine tombe) : sans le gel au Select Targets step, le contrôle de portée n'a plus aucune
# source à partir de la deuxième ligne et cesse SILENCIEUSEMENT de juger le reste de l'activation.
LOIN_2 = (44, 20)  # 34 hex : hors portée, comme LOIN
STEP_LOG_ACTIVATION = entete_step_log(
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) DEPLOYED from (-1,-1) to ({SHOOTER[0]},{SHOOTER[1]}) [R:+0.0] [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101({LOIN[0]},{LOIN[1]}) DEPLOYED from (-1,-1) to ({LOIN[0]},{LOIN[1]}) [R:+0.0] [MODELS: 101#0@({LOIN[0]},{LOIN[1]},z0) 101#1@({LOIN_2[0]},{LOIN_2[1]},z0)] [SUCCESS]\n"
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) SHOT [DESIGNATED:101] Unit 101({LOIN[0]},{LOIN[1]}) with [Sternguard Bolt Rifle] - Hit 4(5+) - Wound 5(4+) - Save 2(5+) - Dmg:2HP [ALLOC_MODEL: 101#0] [R:+0.0] [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SHOOTER_MODELS: 1#0] [SUCCESS]\n"
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) SHOT [DESIGNATED:101] Unit 101({LOIN_2[0]},{LOIN_2[1]}) with [Sternguard Bolt Rifle] - Hit 4(5+) - Wound 5(4+) - Save 2(5+) - Dmg:1HP [ALLOC_MODEL: 101#0] [R:+0.0] [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SHOOTER_MODELS: 1#0] [SUCCESS]\n",
    board="cols=48 rows=60",
    **_COMMON,
)


@pytest.fixture
def stats(tmp_path):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(STEP_LOG)
    return an.parse_step_log(str(log))


def test_premisse_la_figurine_visee_est_a_portee_et_la_survivante_ne_l_est_pas():
    """Sans cet écart le test ne prouve rien : les deux mesures rendraient le même verdict."""
    assert _d(SHOOTER, PROCHE) <= 24, "la figurine visée doit être À PORTÉE de l'arme"
    assert _d(SHOOTER, LOIN) > 24, "la survivante listée doit être HORS portée"


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
    assert _d(SHOOTER, LOIN) > 24 and _d(SHOOTER, LOIN_2) > 24


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
# dans une activation SUIVANTE. Le tir de la première NOMME la figurine touchée, si bien que le
# survivant garde sa position connue et que l'activation suivante se juge normalement. Avant que
# `[ALLOC_MODEL:]` soit lu partout, le lecteur perdait ici toute la carte de la cible et
# renonçait : ce journal mesure ce que l'allocation nominative a rendu jugeable.
STEP_LOG_SANS_SOCLE = entete_step_log(
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) DEPLOYED from (-1,-1) to ({SHOOTER[0]},{SHOOTER[1]}) [R:+0.0] [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2({SHOOTER[0]},{SHOOTER[1] + 2}) DEPLOYED from (-1,-1) to ({SHOOTER[0]},{SHOOTER[1] + 2}) [R:+0.0] [MODELS: 2#0@({SHOOTER[0]},{SHOOTER[1] + 2},z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101({PROCHE[0]},{PROCHE[1]}) DEPLOYED from (-1,-1) to ({PROCHE[0]},{PROCHE[1]}) [R:+0.0] [MODELS: 101#0@({PROCHE[0]},{PROCHE[1]},z0) 101#1@({LOIN[0]},{LOIN[1]},z0)] [SUCCESS]\n"
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) SHOT [DESIGNATED:101] Unit 101({PROCHE[0]},{PROCHE[1]}) with [Sternguard Bolt Rifle] - Hit 4(5+) - Wound 5(4+) - Save 2(5+) - Dmg:2HP [ALLOC_MODEL: 101#0] [R:+0.0] [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SHOOTER_MODELS: 1#0] [SUCCESS]\n"
    f"[10:00:03] E1 T2 P1 SHOOT : Unit 2({SHOOTER[0]},{SHOOTER[1] + 2}) SHOT [DESIGNATED:101] Unit 101({PROCHE[0]},{PROCHE[1]}) with [Sternguard Bolt Rifle] - Hit 4(5+) [R:+0.0] [MODELS: 2#0@({SHOOTER[0]},{SHOOTER[1] + 2},z0)] [SHOOTER_MODELS: 2#0] [SUCCESS]\n",
    board="cols=48 rows=60",
    units=(
        "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
        "[10:00:00] Unit 2 (SternguardVeteranBoltRifle) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
        "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
    ),
    **{k: v for k, v in _COMMON.items() if k != "units"},
)


def test_une_perte_nommee_laisse_l_activation_suivante_jugeable(tmp_path):
    """La figurine touchée est NOMMÉE, donc le survivant reste situé : le tir suivant se juge.

    C'est le gain de l'allocation nominative. Tant que le journal taisait laquelle était
    tombée, le lecteur perdait la carte de la cible et renonçait à mesurer — un tir hors
    portée passait alors inaperçu, ce que la seconde assertion interdit désormais.
    """
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(STEP_LOG_SANS_SOCLE)
    stats = an.parse_step_log(str(log))

    assert stats["shoot_range_unverifiable"][1] == 0, (
        "le survivant est situé : rien n'autorise le contrôle à renoncer"
    )
    assert stats["shoot_invalid"][1]["out_of_range"] == 1, (
        "le second tir vise une cible hors portée et doit être compté comme tel"
    )


# ── Quatrième journal : DEAD-before-SHOOT ──────────────────────────────────────────────────────
# Le moteur flush la ligne DEAD AVANT la ligne de tir qui l'a causée. `_resync_living_models`
# retire le socle de `positions_by_model` (via [MODELS:] de la DEAD line) AVANT que le gel du
# Select Targets step ne soit construit. Sans correction, le gel ne voit que les survivants POST-
# DEAD — ici un seul socle à 32 hex d'une arme de 24" — et déclare le tir hors portée.
# Avec le fix (`dead_model_positions_episode`), le socle mort est réintégré dans le gel :
# distance min = min(12, 32) = 12 ≤ 24 → pas de faux out_of_range.
_DEAD_BEFORE_SHOOT_CLOSE = (22, 20)   # 12 hex du tireur — dans les 24"
_DEAD_BEFORE_SHOOT_LOIN  = (42, 20)   # 32 hex            — hors portée

STEP_LOG_DEAD_BEFORE_SHOOT = entete_step_log(
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) DEPLOYED from (-1,-1) "
    f"to ({SHOOTER[0]},{SHOOTER[1]}) [R:+0.0] [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 103({_DEAD_BEFORE_SHOOT_CLOSE[0]},{_DEAD_BEFORE_SHOOT_CLOSE[1]}) "
    f"DEPLOYED from (-1,-1) to ({_DEAD_BEFORE_SHOOT_CLOSE[0]},{_DEAD_BEFORE_SHOOT_CLOSE[1]}) [R:+0.0] "
    f"[MODELS: 103#0@({_DEAD_BEFORE_SHOOT_CLOSE[0]},{_DEAD_BEFORE_SHOOT_CLOSE[1]},z0) "
    f"103#1@({_DEAD_BEFORE_SHOOT_LOIN[0]},{_DEAD_BEFORE_SHOOT_LOIN[1]},z0)] [SUCCESS]\n"
    # DEAD line : flush AVANT la ligne de tir (artifact d'ordonnancement du moteur)
    f"[10:00:02] E1 T1 P2 SHOOT : Unit 103({_DEAD_BEFORE_SHOOT_CLOSE[0]},{_DEAD_BEFORE_SHOOT_CLOSE[1]}) "
    f"DEAD model=103#0 reason=combat "
    f"[MODELS: 103#1@({_DEAD_BEFORE_SHOOT_LOIN[0]},{_DEAD_BEFORE_SHOOT_LOIN[1]},z0)] [SUCCESS]\n"
    # La ligne de tir qui a causé la mort de 103#0 — socle à portée (12 hex) de l'arme (24")
    f"[10:00:03] E1 T1 P1 SHOOT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) "
    f"SHOT [DESIGNATED:103] Unit 103({_DEAD_BEFORE_SHOOT_CLOSE[0]},{_DEAD_BEFORE_SHOOT_CLOSE[1]}) "
    f"with [Sternguard Bolt Rifle] - Hit 4(5+) - Wound 5(4+) - Save 2(5+) - Dmg:1HP [R:+0.0] "
    f"[MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] "
    f"[SHOOTER_MODELS: 1#0] [ALLOC_MODEL: 103#0] [SUCCESS]\n",
    board="cols=48 rows=60",
    units=(
        "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
        "[10:00:00] Unit 103 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=1 base=round/1\n"
    ),
    **{k: v for k, v in _COMMON.items() if k not in ("units",)}
)


def test_premisse_dead_before_shoot_positions():
    """Sans l'écart de distance, retirer 103#0 tôt ou tard rendrait le même verdict."""
    assert _d(SHOOTER, _DEAD_BEFORE_SHOOT_CLOSE) <= 24, "le socle mort doit être À PORTÉE"
    assert _d(SHOOTER, _DEAD_BEFORE_SHOOT_LOIN)  >  24, "le survivant doit être HORS portée"


def test_dead_avant_shoot_n_est_pas_out_of_range(tmp_path):
    """VERROU : DEAD line (reason=combat) avant la ligne SHOOT ne doit pas causer out_of_range.

    Sans le fix (`dead_model_positions_episode`), le gel du Select Targets step ne voit que
    103#1 à 32 hex → out_of_range=1. Avec le fix, 103#0 est réintégré → distance min=12 → 0.

    Verrou prouvé : supprimer `dead_model_positions_episode` du gel → ROUGE (1 hors portée).
    """
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(STEP_LOG_DEAD_BEFORE_SHOOT)
    stats = an.parse_step_log(str(log))
    assert stats["shoot_invalid"][1]["out_of_range"] == 0, (
        "103#0 était à 12 hex quand le moteur a jugé la portée — la DEAD line ne peut pas "
        "rendre le tir hors portée rétroactivement"
    )
    assert stats["shoot_range_unverifiable"][1] == 0, (
        "le contrôle doit avoir jugé — 0 non-vérifiable prouve qu'aucune distance n'a été "
        "renoncée, donc l'assertion ci-dessus n'est pas un silence"
    )


# ── Cinquième journal : tir sur CADAVRE ────────────────────────────────────────────────────────
# L'autre porte d'entrée de l'abstention, et la seule que les quatre journaux ci-dessus ne
# franchissent jamais : la cible n'a pas perdu des socles, elle est DÉTRUITE depuis un tour
# antérieur. `freeze_select_targets` lit alors `hp=None` (l'unité n'est plus dans `unit_hp`) et
# `engagement_maps` sort par son retour anticipé `if hp is None` APRÈS avoir retiré la cible des
# trois cartes : aucun socle n'est rendu, `edge_dist` vaut None, le contrôle renonce.
# Ce renoncement est légitime — une unité détruite n'a plus de géométrie figée à mesurer — mais
# il doit se COMPTER. Sans ce verrou, remplacer l'incrément par un `pass` ne fait rougir personne
# et le contrôle redevient silencieux sur ce chemin, exactement le « vert vacant » que les
# journaux précédents interdisent sur le leur.
CADAVRE = (22, 20)          # cible détruite au tour 1 — 12 hex du tireur qui la tue
TIREUR_LOIN = (54, 20)      # 32 hex du cadavre : HORS des 24" de l'arme

# Déploiements + le tir du tour 1 qui DÉTRUIT la cible, à portée (12 hex) donc parfaitement légal.
# PAS de ligne DEAD, et c'est MESURÉ, pas un oubli : flushée avant le tir qui la cause, elle
# retirerait la cible — une seule figurine ici — de `unit_hp` avant même le gel de ce tir, qui
# renoncerait alors lui aussi. Le compteur monterait à 2 et ne dirait plus laquelle des deux
# lignes ce test verrouille. Cet ordonnancement a son propre journal ci-dessus,
# `STEP_LOG_DEAD_BEFORE_SHOOT`, sur une cible de deux figurines.
_CADAVRE_PREAMBULE = (
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) DEPLOYED from (-1,-1) "
    f"to ({SHOOTER[0]},{SHOOTER[1]}) [R:+0.0] [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2({TIREUR_LOIN[0]},{TIREUR_LOIN[1]}) DEPLOYED from (-1,-1) "
    f"to ({TIREUR_LOIN[0]},{TIREUR_LOIN[1]}) [R:+0.0] "
    f"[MODELS: 2#0@({TIREUR_LOIN[0]},{TIREUR_LOIN[1]},z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 104({CADAVRE[0]},{CADAVRE[1]}) DEPLOYED from (-1,-1) "
    f"to ({CADAVRE[0]},{CADAVRE[1]}) [R:+0.0] [MODELS: 104#0@({CADAVRE[0]},{CADAVRE[1]},z0)] [SUCCESS]\n"
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) "
    f"SHOT [DESIGNATED:104] Unit 104({CADAVRE[0]},{CADAVRE[1]}) with [Sternguard Bolt Rifle] "
    f"- Hit 4(5+) - Wound 5(4+) - Save 2(5+) - Dmg:2HP [R:+0.0] "
    f"[MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SHOOTER_MODELS: 1#0] [ALLOC_MODEL: 104#0] [SUCCESS]\n"
)

# Tour 3, une AUTRE unité vise le cadavre depuis 32 hex : hors portée SI la géométrie était
# mesurable. Elle ne l'est pas — c'est cette ligne, et elle seule, qui doit faire renoncer.
_CADAVRE_TIR_SUR_CORPS = (
    f"[10:00:03] E1 T3 P1 SHOOT : Unit 2({TIREUR_LOIN[0]},{TIREUR_LOIN[1]}) "
    f"SHOT [DESIGNATED:104] Unit 104({CADAVRE[0]},{CADAVRE[1]}) with [Sternguard Bolt Rifle] "
    f"- Hit 4(5+) - Wound 5(4+) - Save 2(5+) - Dmg:1HP [R:+0.0] "
    f"[MODELS: 2#0@({TIREUR_LOIN[0]},{TIREUR_LOIN[1]},z0)] [SHOOTER_MODELS: 2#0] "
    f"[ALLOC_MODEL: 104#0] [SUCCESS]\n"
)

_CADAVRE_ENTETE: dict[str, Any] = dict(
    board="cols=60 rows=60",
    units=(
        "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
        "[10:00:00] Unit 2 (SternguardVeteranBoltRifle) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
        "[10:00:00] Unit 104 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
    ),
    **{k: v for k, v in _COMMON.items() if k != "units"},
)

STEP_LOG_CADAVRE = entete_step_log(
    _CADAVRE_PREAMBULE + _CADAVRE_TIR_SUR_CORPS, **_CADAVRE_ENTETE
)
# Le MÊME journal amputé de sa dernière ligne : c'est la seule façon d'attribuer l'abstention.
# Le compteur est global à la partie ; sans ce témoin, « 1 » pourrait venir du tir du tour 1.
STEP_LOG_CADAVRE_SANS_TIR_SUR_CORPS = entete_step_log(_CADAVRE_PREAMBULE, **_CADAVRE_ENTETE)


def test_premisse_le_tireur_du_cadavre_est_hors_portee():
    """Sans cet écart, renoncer et mesurer rendraient le même verdict (0 hors portée)."""
    assert _d(SHOOTER, CADAVRE) <= 24, "le tir qui tue doit être À PORTÉE, sinon il est illégal"
    assert _d(TIREUR_LOIN, CADAVRE) > 24, (
        "le tir sur le cadavre doit être HORS portée : c'est ce qui distingue une abstention "
        "d'une mesure"
    )


def test_le_tir_qui_detruit_la_cible_est_bien_juge(tmp_path):
    """Témoin d'attribution : sans la ligne du tour 3, le compteur d'abstention reste à 0.

    C'est lui qui donne son sens au test suivant : `shoot_range_unverifiable` compte la partie
    entière, donc un « 1 » ne prouve rien tant qu'on n'a pas établi que le reste du journal en
    produit zéro.
    """
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(STEP_LOG_CADAVRE_SANS_TIR_SUR_CORPS)
    stats = an.parse_step_log(str(log))

    assert stats["shoot_range_unverifiable"][1] == 0, (
        "la cible est vivante au gel de ce tir : le contrôle a de quoi mesurer, il ne renonce pas"
    )
    assert stats["shoot_invalid"][1]["out_of_range"] == 0, "12 hex pour une arme de 24\""


def test_un_tir_sur_cadavre_compte_son_abstention(tmp_path):
    """VERROU — l'abstention sur cible DÉTRUITE se compte au lieu de se taire.

    Le tour 3 vise depuis 32 hex, avec une arme de 24", une unité détruite au tour 1. La cible
    n'a plus ni PV ni socles figés : le contrôle de portée n'a rien à mesurer. Il doit donc
    renoncer — d'où 0 `out_of_range`, la distance à un état d'après-mort ne prouvant rien — et
    inscrire ce renoncement dans `shoot_range_unverifiable`.

    Verrou prouvé par mutation : remplacer l'incrément de la branche `if edge_dist is None`
    (`shoot_handler`) par un `pass` → ROUGE ici. Mesuré aussi sous la même mutation :
    `test_analyzer_target_decl_portee` et `test_analyzer_dead_unit_false_positive`, les deux
    fichiers qui touchent ce compteur et ce chemin, restent VERTS — ce test est le seul à tenir
    cette branche.
    """
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(STEP_LOG_CADAVRE)
    stats = an.parse_step_log(str(log))

    assert stats["shoot_range_unverifiable"][1] == 1, (
        "cible détruite : aucun socle figé à mesurer, le contrôle renonce et doit le compter"
    )
    assert stats["shoot_invalid"][1]["out_of_range"] == 0, (
        "renoncer interdit de condamner : la distance aux positions d'après-mort ne prouve rien"
    )
    # Anti-vacant : la ligne du tour 3 a bien été lue, et la cible qu'elle vise est bien un
    # cadavre — c'est ce qui rend la géométrie non mesurable. Sans cette assertion, une cible
    # simplement dépourvue de socles donnerait le même compte pour une autre raison.
    assert stats["shoot_at_dead_unit"][1] == 1, (
        "le tir du tour 3 vise un cadavre — c'est la ligne dont l'abstention est comptée"
    )
    assert stats["shoot_invalid"][1]["total"] == 2, "les deux lignes de tir ont été traitées"
