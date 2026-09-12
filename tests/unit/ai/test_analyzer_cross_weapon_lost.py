"""Tir fractionné : attaques d'une arme perdues sur une cible qu'une AUTRE arme de la même
activation venait d'anéantir — `stats['shoot_cross_weapon_attacks_lost']`.

Le moteur résout lot par lot (cible × profil, `_build_manual_allocation`) ; quand le lot de
l'arme A anéantit la cible, le lot de l'arme B ne trouve plus un seul groupe vivant et toutes
ses blessures sont journalisées `Save [NOT ALLOCATED]` (`_mark_manual_overkill_wasted`, seul
chemin qui laisse une blessure sans allocataire). Le verdict se rend PAR GROUPE : dans un lot,
l'ordre des lignes est celui des tirs, pas celui de l'allocation (pool trié par sauvegarde
croissante, 05.04) — une ligne non allouée du tueur peut donc précéder sa première ligne de
dégâts, et un verdict ligne à ligne la compterait à tort (scénario 4).

Ordre moteur réel reproduit : `DEAD model=` est écrit PENDANT la résolution, donc AVANT les
lignes SHOT du groupe qui l'a causé (`_finalize_manual_allocation` n'émet qu'après allocation
complète) — cf. `test_analyzer_dead_unit_false_positive.py`.
"""
from __future__ import annotations

import pytest

import ai.analyzer as an
from tests.unit.ai._fabriques import EPISODE_TAIL, entete_step_log

S = "(50,50)"
T = "(80,50)"
T2 = "(80,60)"
OBJECTIVES = ";".join(f"(200,{r})" for r in range(150, 156))

_HEADER = entete_step_log(
    units=(
        f"[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position {S}, HP_MAX=2 base=round/6 [MODELS: 1#0@(50,50)]\n"
        f"[10:00:00] Unit 102 (AssaultIntercessor) P2: Starting position {T}, HP_MAX=2 base=round/6 [MODELS: 102#0@(80,50)]\n"
        f"[10:00:00] Unit 103 (AssaultIntercessor) P2: Starting position {T2}, HP_MAX=2 base=round/6 [MODELS: 103#0@(80,60)]\n"
    ),
    rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
    objectives=OBJECTIVES,
    ez_vertical_inches=None,
)

A = "Sternguard Bolt Rifle"   # arme du slot 0
B = "Bolt Pistol"             # arme du slot 1


def _shot(weapon: str, target: str, target_pos: str, save: str, hit: str = "3+") -> str:
    """Une ligne SHOT de l'unité 1 ; `save` est le segment de sauvegarde complet."""
    return (
        f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit {target}{target_pos} with [{weapon}]"
        f" - Hit 4({hit}) - Wound 5(4+) - {save} [R:+0.0] [MODELS: 1#0@(50,50)] [SUCCESS]\n"
    )


def _dmg(weapon: str, target: str = "102", target_pos: str = T) -> str:
    return _shot(weapon, target, target_pos, f"→ {target}#0 - Save 2(3+) - Dmg:1HP")


def _lost(weapon: str, target: str = "102", target_pos: str = T) -> str:
    return _shot(weapon, target, target_pos, "Save [NOT ALLOCATED]")


_DEAD_102 = "[10:00:02] E1 T1 P2 SHOOT : Unit 102 DEAD model=102#0 reason=combat [SUCCESS]\n"


def _stats(tmp_path, body: str, end: str = EPISODE_TAIL):
    log = tmp_path / "step.log"
    log.write_text(_HEADER + body + end)
    return an.parse_step_log(str(log))


def test_le_groupe_du_slot_1_perdu_derriere_le_slot_0_tueur_compte_chaque_ligne(tmp_path):
    """Scénario 1 : A tue (2 PV, 2 lignes Dmg + 1 overkill propre), B arrive sur un cadavre :
    ses 3 lignes sont perdues, et SEULEMENT elles — l'overkill propre de A ne compte pas."""
    body = (
        _DEAD_102
        + _dmg(A) + _lost(A) + _dmg(A)
        + _lost(B) + _lost(B) + _lost(B)
    )
    stats = _stats(tmp_path, body)
    assert stats["shoot_cross_weapon_attacks_lost"][1] == 3
    assert stats["shoot_cross_weapon_lost_groups"][1] == 1
    assert stats["shoot_cross_weapon_attacks_lost"][2] == 0
    sample = stats["shoot_cross_weapon_lost_sample"][1]
    assert sample is not None and f"with [{B}]" in sample["line"], sample


def test_l_overkill_propre_d_une_seule_arme_ne_compte_pas(tmp_path):
    """Scénario 2 : une seule arme, cible tuée, une blessure de trop → 0. Un jet, pas un choix."""
    body = _DEAD_102 + _dmg(A) + _dmg(A) + _lost(A)
    stats = _stats(tmp_path, body)
    assert stats["shoot_cross_weapon_attacks_lost"][1] == 0
    assert stats["shoot_cross_weapon_lost_groups"][1] == 0
    assert stats["shoot_cross_weapon_lost_sample"][1] is None


def test_deux_armes_sur_deux_cibles_ne_comptent_pas(tmp_path):
    """Scénario 3 : A tue 102, B tire sur 103 (vivante, blessures allouées) → 0."""
    body = _DEAD_102 + _dmg(A) + _dmg(A) + _dmg(B, "103", T2)
    stats = _stats(tmp_path, body)
    assert stats["shoot_cross_weapon_attacks_lost"][1] == 0
    assert stats["shoot_cross_weapon_lost_groups"][1] == 0


def test_une_ligne_non_allouee_du_tueur_imprimee_avant_son_premier_degat_ne_compte_pas(tmp_path):
    """Scénario 4 : A blesse sans tuer, B tue avec overkill — et sa ligne `[NOT ALLOCATED]` est
    imprimée AVANT sa première ligne Dmg (ordre des tirs ≠ ordre d'allocation). Un verdict
    ligne à ligne verrait « arme B ≠ dernière arme à Dmg (A) » et compterait 1. Attendu : 0."""
    body = (
        _DEAD_102
        + _dmg(A)
        + _lost(B) + _dmg(B)
    )
    stats = _stats(tmp_path, body)
    assert stats["shoot_cross_weapon_attacks_lost"][1] == 0
    assert stats["shoot_cross_weapon_lost_groups"][1] == 0


def test_une_ligne_a_sauvegarde_sans_nom_d_arme_leve(tmp_path):
    """T1 : un groupe anonyme ne peut être ni distingué du tueur ni compté — on lève, on ne
    laisse pas le compteur dépendre de ce que le journal veut bien nommer."""
    anonymous = (
        f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 102{T}"
        " - Hit 4(3+) - Wound 5(4+) - Save [NOT ALLOCATED] [R:+0.0] [SUCCESS]\n"
    )
    with pytest.raises(ValueError, match="sans ` with \\[arme\\]`"):
        _stats(tmp_path, _DEAD_102 + anonymous)


def test_deux_lots_de_meme_nom_a_seuils_differents_sont_deux_groupes(tmp_path):
    """Le moteur groupe par attaques IDENTIQUES (`gkey`), pas par nom : un Bolt Pistol de
    personnage rattaché (BS 2+) et ceux de l'escouade (BS 3+) font deux lots, résolus à leur
    rang. Ordre : BP 2+ alloue sans tuer, le Plasma tue, BP 3+ arrive sur un cadavre. Une clé
    au seul nom fusionnerait les deux BP en un groupe mixte → 0 ; attendu : 2 attaques perdues,
    1 groupe."""
    body = (
        _DEAD_102
        + _shot(B, "102", T, "→ 102#0 - Save 2(3+) - Dmg:1HP", hit="2+")
        + _dmg("Plasma Pistol")
        + _lost(B) + _lost(B)
    )
    stats = _stats(tmp_path, body)
    assert stats["shoot_cross_weapon_attacks_lost"][1] == 2
    assert stats["shoot_cross_weapon_lost_groups"][1] == 1


def test_le_dernier_episode_sans_episode_end_est_juge_aussi(tmp_path):
    """Journal lu pendant un entraînement ou tronqué : le verdict se rend en fin de lecture,
    `EPISODE END` ou pas."""
    body = _DEAD_102 + _dmg(A) + _dmg(A) + _lost(B) + _lost(B)
    stats = _stats(tmp_path, body, end="")
    assert stats["episodes_without_end"], "le scénario doit bien être un épisode sans fin"
    assert stats["shoot_cross_weapon_attacks_lost"][1] == 2


def test_le_compteur_reste_hors_du_total_d_erreurs_shooting(tmp_path):
    """Perte observée, pas faute de règle : le total `shooting` n'en bouge pas."""
    body = _DEAD_102 + _dmg(A) + _dmg(A) + _lost(B)
    stats = _stats(tmp_path, body)
    assert stats["shoot_cross_weapon_attacks_lost"][1] == 1
    totals = an.error_totals(stats)
    assert totals["shooting"] == 0, totals
