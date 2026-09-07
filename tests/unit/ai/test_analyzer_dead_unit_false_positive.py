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

from tests.unit.ai._fabriques import entete_step_log

# Unit 101 = escouade de 3 figurines à 2 PV (registry HP_MAX=2) → 6 PV effectifs.
# Unit 1 lui inflige 4 tirs Dmg:2HP dans UNE seule activation (T1 P1 SHOOT) :
#   tir 1 → 1re figurine morte (escouade vivante),
#   tir 2 → 2e figurine morte (escouade vivante),
#   tir 3 → 3e/dernière figurine morte → escouade détruite,
#   tir 4 → « excess attack lost » (même activation).
# L'ancien modèle comptait les tirs 2,3,4 comme tir sur unité morte + dégât sans unit_hp.
DEPLOY_MODELS = "[MODELS: 101#0@(80,50) 101#1@(84,50) 101#2@(88,50)]"

STEP_LOG = entete_step_log(
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(80,50) DEPLOYED from (-1,-1) to (80,50) [R:+0.0] [SUCCESS]\n"
    "[10:00:02] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 101(80,50) with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:2HP [R:+0.0] [SUCCESS]\n"
    "[10:00:02] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 101(80,50) with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:2HP [R:+0.0] [SUCCESS]\n"
    "[10:00:02] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 101(80,50) with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:2HP [R:+0.0] [SUCCESS]\n"
    "[10:00:02] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 101(80,50) with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:2HP [R:+0.0] [SUCCESS]\n",
    units=(
        "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (50,50), HP_MAX=2 base=round/6 [MODELS: 1#0@(50,50)]\n"
        f"[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (80,50), HP_MAX=2 base=round/6 {DEPLOY_MODELS}\n"
    ),
    ez_vertical_inches=None,
)


# Grammaire RÉELLE du moteur : la ligne `DEAD model=` est écrite PENDANT la résolution
# (`destroy_model`), donc AVANT les lignes SHOT du groupe d'armes qui l'ont causée
# (`_finalize_manual_allocation` ne les émet qu'après allocation complète). Le tir fatal, ici la
# dernière ligne, SUIT donc l'annonce de la mort qu'il provoque.
#
# La fixture STEP_LOG ci-dessus ne porte AUCUNE ligne `DEAD model=` ni `[ALLOC_MODEL:]` : elle
# n'exerçait pas cette inversion, et laissait passer 3156 faux positifs mesurés en production.
DEAD_BEFORE_SHOT_LOG = entete_step_log(
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [MODELS: 1#0@(50,50)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 102(80,50) DEPLOYED from (-1,-1) to (80,50) [R:+0.0] [MODELS: 102#0@(80,50)] [SUCCESS]\n"
    "[10:00:02] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 102(80,50) with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - → 102#0 - Save 2(3+) - Dmg:1HP [R:+0.0] [MODELS: 1#0@(50,50)] [ALLOC_MODEL: 102#0] [SUCCESS]\n"
    "[10:00:02] E1 T1 P2 SHOOT : Unit 102 DEAD model=102#0 reason=combat [SUCCESS]\n"
    "[10:00:02] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 102(80,50) with [Sternguard Bolt Rifle] - Hit 5(3+) - Wound 4(4+) - → 102#0 - Save 2(3+) - Dmg:1HP [R:+0.0] [MODELS: 1#0@(50,50)] [ALLOC_MODEL: 102#0] [SUCCESS]\n",
    units=(
        "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (50,50), HP_MAX=2 base=round/6 [MODELS: 1#0@(50,50)]\n"
        "[10:00:00] Unit 102 (AssaultIntercessor) P2: Starting position (80,50), HP_MAX=2 base=round/6 [MODELS: 102#0@(80,50)]\n"
    ),
    ez_vertical_inches=None,
)

# Variante cross-turn de DEAD_BEFORE_SHOT_LOG : la mort survient via l'artefact DEAD-before-SHOOT
# (DEAD line avant la ligne SHOT mortelle), puis une activation d'un TOUR ULTÉRIEUR vise le cadavre.
# Teste que le handler DEAD enregistre la mort dans unit_deaths/unit_kill_context afin que
# `died_before_phase` puisse dater la mort même quand `_apply_damage_to_named_model` retourne tôt.
# Ordre moteur réel : DEAD précède TOUTES les lignes SHOT de l'activation.
# destroy_model écrit la ligne DEAD immédiatement (shared_utils.py:4185), puis
# _finalize_manual_allocation émet les SHOT après l'allocation complète (line 10963).
# Contrairement à DEAD_BEFORE_SHOT_LOG (SHOT_1 → DEAD → SHOT_2), ici aucun SHOT n'est
# vu avant DEAD → state.pending_removals_actor est None → unit_kill_context[102] = (None, T, P).
# Sans correctif : same_activation_kill = False sur SHOT_1 → faux positif.
DEAD_BEFORE_ALL_SHOTS_LOG = entete_step_log(
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [MODELS: 1#0@(50,50)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 102(80,50) DEPLOYED from (-1,-1) to (80,50) [R:+0.0] [MODELS: 102#0@(80,50)] [SUCCESS]\n"
    "[10:00:02] E1 T1 P2 SHOOT : Unit 102 DEAD model=102#0 reason=combat [SUCCESS]\n"
    "[10:00:03] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 102(80,50) with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - → 102#0 - Save 2(3+) - Dmg:1HP [R:+0.0] [MODELS: 1#0@(50,50)] [ALLOC_MODEL: 102#0] [SUCCESS]\n"
    "[10:00:04] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 102(80,50) with [Sternguard Bolt Rifle] - Hit 5(3+) - Wound 4(4+) - → 102#0 - Save 2(3+) - Dmg:1HP [R:+0.0] [MODELS: 1#0@(50,50)] [ALLOC_MODEL: 102#0] [SUCCESS]\n",
    units=(
        "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (50,50), HP_MAX=2 base=round/6 [MODELS: 1#0@(50,50)]\n"
        "[10:00:00] Unit 102 (AssaultIntercessor) P2: Starting position (80,50), HP_MAX=2 base=round/6 [MODELS: 102#0@(80,50)]\n"
    ),
    ez_vertical_inches=None,
)

DEAD_BEFORE_SHOT_CROSS_TURN_LOG = entete_step_log(
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [MODELS: 1#0@(50,50)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 102(80,50) DEPLOYED from (-1,-1) to (80,50) [R:+0.0] [MODELS: 102#0@(80,50)] [SUCCESS]\n"
    "[10:00:02] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 102(80,50) with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - → 102#0 - Save 2(3+) - Dmg:1HP [R:+0.0] [MODELS: 1#0@(50,50)] [ALLOC_MODEL: 102#0] [SUCCESS]\n"
    "[10:00:02] E1 T1 P2 SHOOT : Unit 102 DEAD model=102#0 reason=combat [SUCCESS]\n"
    "[10:00:03] E1 T3 P1 SHOOT : Unit 1(50,50) SHOT Unit 102(80,50) with [Sternguard Bolt Rifle] - Hit 5(3+) - Wound 4(4+) - → 102#0 - Save 2(3+) - Dmg:1HP [R:+0.0] [MODELS: 1#0@(50,50)] [ALLOC_MODEL: 102#0] [SUCCESS]\n",
    units=(
        "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (50,50), HP_MAX=2 base=round/6 [MODELS: 1#0@(50,50)]\n"
        "[10:00:00] Unit 102 (AssaultIntercessor) P2: Starting position (80,50), HP_MAX=2 base=round/6 [MODELS: 102#0@(80,50)]\n"
    ),
    ez_vertical_inches=None,
)

# Vraie violation : la cible meurt au tour 1, et une activation d'un tour ULTÉRIEUR la vise encore.
# Garde la preuve que le contrôle n'est pas devenu vacant en neutralisant l'artefact ci-dessus.
SHOT_AT_CORPSE_LOG = entete_step_log(
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [MODELS: 1#0@(50,50)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 102(80,50) DEPLOYED from (-1,-1) to (80,50) [R:+0.0] [MODELS: 102#0@(80,50)] [SUCCESS]\n"
    "[10:00:02] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 102(80,50) with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - → 102#0 - Save 2(3+) - Dmg:2HP [R:+0.0] [MODELS: 1#0@(50,50)] [ALLOC_MODEL: 102#0] [SUCCESS]\n"
    "[10:00:03] E1 T3 P1 SHOOT : Unit 1(50,50) SHOT Unit 102(80,50) with [Sternguard Bolt Rifle] - Hit 5(3+) - Wound 4(4+) - → 102#0 - Save 2(3+) - Dmg:1HP [R:+0.0] [MODELS: 1#0@(50,50)] [ALLOC_MODEL: 102#0] [SUCCESS]\n",
    units=(
        "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (50,50), HP_MAX=2 base=round/6 [MODELS: 1#0@(50,50)]\n"
        "[10:00:00] Unit 102 (AssaultIntercessor) P2: Starting position (80,50), HP_MAX=2 base=round/6 [MODELS: 102#0@(80,50)]\n"
    ),
    ez_vertical_inches=None,
)


# LE cas de production, que les trois fixtures ci-dessus manquaient toutes : une AUTRE unité a
# tiré JUSTE AVANT l'activation qui tue. `state.pending_removals_actor` porte alors l'acteur de
# cette activation précédente (« 1 »), pas celui de l'activation en cours (« 5 ») — le handler
# DEAD en faisait le tueur, et `same_activation_kill` échouait sur CHAQUE activation qui détruit
# sa cible. Mesuré sur un run de 600 épisodes : §2.1 passait de 0 à 4293 erreurs, toutes fausses.
# Les fixtures existantes ne pouvaient pas le voir : DEAD_BEFORE_SHOT_LOG a le même attaquant des
# deux côtés de la ligne DEAD, et DEAD_BEFORE_ALL_SHOTS_LOG n'a aucune activation antérieure.
_UNITS_DEUX_ATTAQUANTS = (
    "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (50,50), HP_MAX=2 base=round/6 [MODELS: 1#0@(50,50)]\n"
    "[10:00:00] Unit 5 (SternguardVeteranBoltRifle) P1: Starting position (60,50), HP_MAX=2 base=round/6 [MODELS: 5#0@(60,50)]\n"
    "[10:00:00] Unit 102 (AssaultIntercessor) P2: Starting position (80,50), HP_MAX=2 base=round/6 [MODELS: 102#0@(80,50)]\n"
    "[10:00:00] Unit 103 (AssaultIntercessor) P2: Starting position (90,50), HP_MAX=2 base=round/6 [MODELS: 103#0@(90,50)]\n"
)
_DEPLOIEMENTS_DEUX_ATTAQUANTS = (
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [MODELS: 1#0@(50,50)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 5(60,50) DEPLOYED from (-1,-1) to (60,50) [R:+0.0] [MODELS: 5#0@(60,50)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 102(80,50) DEPLOYED from (-1,-1) to (80,50) [R:+0.0] [MODELS: 102#0@(80,50)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 103(90,50) DEPLOYED from (-1,-1) to (90,50) [R:+0.0] [MODELS: 103#0@(90,50)] [SUCCESS]\n"
)
# Unit 1 blesse 103 sans la tuer (elle pose `pending_removals_actor`), puis 102 meurt sous les
# tirs de Unit 5 — dont la ligne d'attaque, comme toujours, SUIT l'annonce de la mort.
DEAD_APRES_ACTIVATION_D_UNE_AUTRE_UNITE_LOG = entete_step_log(
    _DEPLOIEMENTS_DEUX_ATTAQUANTS
    + "[10:00:02] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 103(90,50) with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - → 103#0 - Save 2(3+) - Dmg:1HP [R:+0.0] [MODELS: 1#0@(50,50)] [ALLOC_MODEL: 103#0] [SUCCESS]\n"
    "[10:00:03] E1 T1 P2 SHOOT : Unit 102 DEAD model=102#0 reason=combat [SUCCESS]\n"
    "[10:00:04] E1 T1 P1 SHOOT : Unit 5(60,50) SHOT Unit 102(80,50) with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - → 102#0 - Save 2(3+) - Dmg:1HP [R:+0.0] [MODELS: 5#0@(60,50)] [ALLOC_MODEL: 102#0] [SUCCESS]\n"
    "[10:00:05] E1 T1 P1 SHOOT : Unit 5(60,50) SHOT Unit 102(80,50) with [Sternguard Bolt Rifle] - Hit 5(3+) - Wound 4(4+) - → 102#0 - Save 2(3+) - Dmg:1HP [R:+0.0] [MODELS: 5#0@(60,50)] [ALLOC_MODEL: 102#0] [SUCCESS]\n",
    units=_UNITS_DEUX_ATTAQUANTS,
    ez_vertical_inches=None,
)
# Même ouverture, mais c'est Unit 1 qui tire APRÈS que Unit 5 a revendiqué la mort : là, le
# cadavre est visé par une unité tierce et la faute doit rester comptée.
CADAVRE_VISE_PAR_UNE_TIERCE_UNITE_LOG = entete_step_log(
    _DEPLOIEMENTS_DEUX_ATTAQUANTS
    + "[10:00:02] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 103(90,50) with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - → 103#0 - Save 2(3+) - Dmg:1HP [R:+0.0] [MODELS: 1#0@(50,50)] [ALLOC_MODEL: 103#0] [SUCCESS]\n"
    "[10:00:03] E1 T1 P2 SHOOT : Unit 102 DEAD model=102#0 reason=combat [SUCCESS]\n"
    "[10:00:04] E1 T1 P1 SHOOT : Unit 5(60,50) SHOT Unit 102(80,50) with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - → 102#0 - Save 2(3+) - Dmg:1HP [R:+0.0] [MODELS: 5#0@(60,50)] [ALLOC_MODEL: 102#0] [SUCCESS]\n"
    "[10:00:05] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 102(80,50) with [Sternguard Bolt Rifle] - Hit 5(3+) - Wound 4(4+) - → 102#0 - Save 2(3+) - Dmg:1HP [R:+0.0] [MODELS: 1#0@(50,50)] [ALLOC_MODEL: 102#0] [SUCCESS]\n",
    units=_UNITS_DEUX_ATTAQUANTS,
    ez_vertical_inches=None,
)


def _parse(tmp_path, contenu: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(contenu)
    return an.parse_step_log(str(log))


@pytest.fixture
def stats(tmp_path):
    return _parse(tmp_path, STEP_LOG)


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


def test_dead_line_written_before_its_own_shot_is_not_a_violation(tmp_path):
    """Le tir qui CAUSE la mort suit la ligne `DEAD` au journal : ce n'est pas un tir sur cadavre.

    Verrou de l'artefact d'ordonnancement : `unit_hp` seul date la mort de la ligne `DEAD`, donc
    d'un point ANTÉRIEUR à l'attaque responsable. Le garde `died_before_phase` date la mort de la
    ligne de dégâts elle-même.
    """
    stats = _parse(tmp_path, DEAD_BEFORE_SHOT_LOG)
    assert stats["shoot_at_dead_unit"][1] == 0
    assert stats["shoot_at_dead_unit"][2] == 0


def test_une_activation_anterieure_d_une_autre_unite_ne_devient_pas_le_tueur(tmp_path):
    """LE cas de production : Unit 5 tue, Unit 1 avait tiré juste avant.

    Le handler DEAD prenait `pending_removals_actor` — l'acteur de la dernière ligne d'attaque
    LUE, donc Unit 1 — pour le tueur de la cible de Unit 5. `same_activation_kill` échouait alors
    sur chaque activation qui détruit sa cible, et le contrôle comptait les « excess attacks
    lost » de l'attaquant comme des tirs sur cadavre : 4293 fausses erreurs §2.1 mesurées.
    """
    stats = _parse(tmp_path, DEAD_APRES_ACTIVATION_D_UNE_AUTRE_UNITE_LOG)
    assert stats["shoot_at_dead_unit"][1] == 0, (
        "les tirs de l'activation qui TUE sont comptés comme des tirs sur cadavre"
    )
    assert stats["shoot_at_dead_unit"][2] == 0


def test_le_cadavre_vise_par_une_tierce_unite_reste_compte(tmp_path):
    """Non-vacuité du correctif : seul le tueur est amnistié, pas l'unité suivante.

    Sans cette garde, poser « tueur inconnu » reviendrait à amnistier le premier attaquant venu
    et le contrôle deviendrait vacant — l'inverse exact du défaut qu'on corrige.
    """
    stats = _parse(tmp_path, CADAVRE_VISE_PAR_UNE_TIERCE_UNITE_LOG)
    assert stats["shoot_at_dead_unit"][1] == 1, (
        "un tir d'une unité tierce sur un cadavre déjà revendiqué doit rester une violation"
    )


def test_shot_at_a_unit_killed_on_an_earlier_turn_is_still_flagged(tmp_path):
    """Non-vacuité : une cible tuée au tour 1 et visée au tour 3 reste une violation."""
    stats = _parse(tmp_path, SHOT_AT_CORPSE_LOG)
    assert stats["shoot_at_dead_unit"][1] == 1


def test_dead_before_shot_cross_turn_is_flagged(tmp_path):
    """Chemin DEAD-before-SHOOT + tour ultérieur : la violation doit être détectée.

    La cible meurt via l'artefact (DEAD line avant la ligne SHOT mortelle) au tour 1.
    _apply_damage_to_named_model retourne tôt (dead_model_ids_episode), donc unit_deaths
    n'est jamais rempli par ce chemin. Le handler DEAD doit le faire directement.
    Un tir au tour 3 doit toujours être compté comme shoot_at_dead_unit.
    """
    stats = _parse(tmp_path, DEAD_BEFORE_SHOT_CROSS_TURN_LOG)
    assert stats["shoot_at_dead_unit"][1] == 1


def test_dead_before_shot_same_activation_not_flagged_after_fix(tmp_path):
    """Le fix du handler DEAD ne crée pas de faux positif sur l'activation qui a tué la cible.

    Le tir excédentaire dans la MÊME activation (même tour/phase que le DEAD) doit rester
    à zéro : unit_kill_context est posé dans le handler DEAD pour que same_activation_kill
    soit True.
    """
    stats = _parse(tmp_path, DEAD_BEFORE_SHOT_LOG)
    assert stats["shoot_at_dead_unit"][1] == 0
    assert stats["shoot_at_dead_unit"][2] == 0


def test_dead_before_all_shots_real_production_order_not_flagged(tmp_path):
    """DEAD précède TOUTES les lignes SHOT de l'activation (ordre moteur réel) : pas de faux positif.

    Dans l'ordre réel (destroy_model écrit DEAD pendant l'allocation, _finalize_manual_allocation
    émet les SHOT après), pending_removals_actor est None quand le handler DEAD s'exécute.
    Sans correctif, unit_kill_context[102] = (None, T, P) → same_activation_kill = False sur
    SHOT_1 → faux positif. Le handler SHOT doit propager l'acteur réel dans unit_kill_context
    avant le test same_activation_kill.
    """
    stats = _parse(tmp_path, DEAD_BEFORE_ALL_SHOTS_LOG)
    assert stats["shoot_at_dead_unit"][1] == 0
    assert stats["shoot_at_dead_unit"][2] == 0


# Jumeau FIGHT de DEAD_BEFORE_ALL_SHOTS_LOG : même artefact d'ordonnancement (destroy_model écrit
# DEAD pendant l'allocation de mêlée, AVANT les lignes FOUGHT de _finalize_manual_allocation).
# Comme pour le tir, pending_removals_actor est None quand le handler DEAD s'exécute en phase
# FIGHT → unit_kill_context[102] = (None, T1, FIGHT). Le handler FOUGHT propage l'acteur réel.
# Sans le correctif dans fight_handler.py : fight_dead_unit_target[1] == 2 (faux positif sur les
# deux lignes). Avec le correctif : 0.
DEAD_BEFORE_ALL_FIGHTS_LOG = entete_step_log(
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [MODELS: 1#0@(50,50,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 102(51,50) DEPLOYED from (-1,-1) to (51,50) [R:+0.0] [MODELS: 102#0@(51,50,z0)] [SUCCESS]\n"
    "[10:00:02] E1 T1 P2 FIGHT : Unit 102(51,50) DEAD model=102#0 reason=combat [SUCCESS]\n"
    "[10:00:03] E1 T1 P1 FIGHT : Unit 1(50,50) FOUGHT Unit 102(51,50) with [Close Combat Weapon] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [FIGHT_SUBPHASE:fight] [MODELS: 1#0@(50,50,z0)] [SUCCESS]\n"
    "[10:00:04] E1 T1 P1 FIGHT : Unit 1(50,50) FOUGHT Unit 102(51,50) with [Close Combat Weapon] - Hit 5(3+) - Wound 4(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [FIGHT_SUBPHASE:fight] [MODELS: 1#0@(50,50,z0)] [SUCCESS]\n",
    units=(
        "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (50,50), HP_MAX=2 base=round/6 [MODELS: 1#0@(50,50,z0)]\n"
        "[10:00:00] Unit 102 (AssaultIntercessor) P2: Starting position (51,50), HP_MAX=2 base=round/6 [MODELS: 102#0@(51,50,z0)]\n"
    ),
    ez_vertical_inches=None,
)


# Jumeau FIGHT du cas de production : une AUTRE unité a frappé juste avant l'activation qui tue.
# Le motif d'échec n°1 du dépôt est la correction faite d'un seul côté d'un miroir ; le défaut
# `pending_removals_actor` vit dans le handler DEAD, donc il frappe les deux phases.
DEAD_APRES_ACTIVATION_D_UNE_AUTRE_UNITE_FIGHT_LOG = entete_step_log(
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [MODELS: 1#0@(50,50,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 5(52,50) DEPLOYED from (-1,-1) to (52,50) [R:+0.0] [MODELS: 5#0@(52,50,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 102(51,50) DEPLOYED from (-1,-1) to (51,50) [R:+0.0] [MODELS: 102#0@(51,50,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 103(53,50) DEPLOYED from (-1,-1) to (53,50) [R:+0.0] [MODELS: 103#0@(53,50,z0)] [SUCCESS]\n"
    "[10:00:02] E1 T1 P1 FIGHT : Unit 1(50,50) FOUGHT Unit 103(53,50) with [Close Combat Weapon] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [FIGHT_SUBPHASE:fight] [MODELS: 1#0@(50,50,z0)] [SUCCESS]\n"
    "[10:00:03] E1 T1 P2 FIGHT : Unit 102(51,50) DEAD model=102#0 reason=combat [SUCCESS]\n"
    "[10:00:04] E1 T1 P1 FIGHT : Unit 5(52,50) FOUGHT Unit 102(51,50) with [Close Combat Weapon] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [FIGHT_SUBPHASE:fight] [MODELS: 5#0@(52,50,z0)] [SUCCESS]\n"
    "[10:00:05] E1 T1 P1 FIGHT : Unit 5(52,50) FOUGHT Unit 102(51,50) with [Close Combat Weapon] - Hit 5(3+) - Wound 4(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [FIGHT_SUBPHASE:fight] [MODELS: 5#0@(52,50,z0)] [SUCCESS]\n",
    units=(
        "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (50,50), HP_MAX=2 base=round/6 [MODELS: 1#0@(50,50,z0)]\n"
        "[10:00:00] Unit 5 (SternguardVeteranBoltRifle) P1: Starting position (52,50), HP_MAX=2 base=round/6 [MODELS: 5#0@(52,50,z0)]\n"
        "[10:00:00] Unit 102 (AssaultIntercessor) P2: Starting position (51,50), HP_MAX=2 base=round/6 [MODELS: 102#0@(51,50,z0)]\n"
        "[10:00:00] Unit 103 (AssaultIntercessor) P2: Starting position (53,50), HP_MAX=2 base=round/6 [MODELS: 103#0@(53,50,z0)]\n"
    ),
    ez_vertical_inches=None,
)


def test_fight_une_activation_anterieure_d_une_autre_unite_ne_devient_pas_le_tueur(tmp_path):
    """Jumeau mêlée : Unit 5 tue, Unit 1 avait frappé juste avant.

    Le défaut vit dans le handler DEAD, commun aux deux phases : `pending_removals_actor` y
    désignait l'acteur de l'activation précédente. Corriger le seul côté tir aurait laissé la
    mêlée compter les « excess attacks lost » de l'attaquant comme des attaques sur cadavre —
    1500 des 4293 fausses erreurs mesurées venaient de là.
    """
    stats = _parse(tmp_path, DEAD_APRES_ACTIVATION_D_UNE_AUTRE_UNITE_FIGHT_LOG)
    assert stats["fight_dead_unit_target"][1] == 0, (
        "les attaques de l'activation qui TUE sont comptées comme des attaques sur cadavre"
    )
    assert stats["fight_dead_unit_target"][2] == 0


def test_dead_before_all_fights_real_production_order_not_flagged(tmp_path):
    """DEAD précède TOUTES les lignes FOUGHT de l'activation (ordre moteur réel) : pas de faux positif.

    Jumeau FIGHT du test SHOOT ci-dessus. destroy_model écrit DEAD pendant l'allocation de mêlée,
    _finalize_manual_allocation émet les FOUGHT après. pending_removals_actor est None quand le
    handler DEAD s'exécute → unit_kill_context[102] = (None, T1, FIGHT). Le handler FOUGHT dans
    fight_handler.py propage l'acteur réel avant le test same_activation_kill.
    Mutation proof : sans le bloc `if _kill_ctx_fight[0] is None`, same_activation_kill serait
    False pour les deux lignes → fight_dead_unit_target[1] == 2.
    """
    stats = _parse(tmp_path, DEAD_BEFORE_ALL_FIGHTS_LOG)
    assert stats["fight_dead_unit_target"][1] == 0
    assert stats["fight_dead_unit_target"][2] == 0
