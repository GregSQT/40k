"""Verrous de `scripts/seat_advantage_probe.py` (plafonnement_p1.md §13).

Les deux verrous de frontière de tour portent sur des défauts MESURÉS pendant la mise au point
de la sonde, pas sur des cas imaginés :

- l'ordre canonique doit tolérer un tour de joueur SAUTÉ (résolu en entier dans un seul step
  moteur par la cascade `phase_complete`). Exiger le successeur immédiat désynchronisait la
  timeline pour tout le reste de l'épisode — constaté sur 1 épisode de 1 200, où le tour du
  joueur 1 au round 5 disparaissait ;
- un aller-retour de `current_player` À L'INTÉRIEUR d'un tour (allocation de pertes, désignation
  de cohérence, déploiement alterné) ne doit ouvrir aucun segment : sans ce filtre, 16 épisodes
  produisaient 116 relevés.

Un chiffre de la sonde lu sur une timeline désynchronisée est faux sans rien signaler, d'où ces
verrous sur les fonctions pures plutôt que sur la sortie.
"""
from __future__ import annotations

import pytest

from scripts.seat_advantage_probe import (
    VARIANTS,
    _canonical_index,
    _episode_seed,
    _opens_new_turn,
    _require_supported_mission,
    _segments,
    board_path_for_agent,
)


def test_chaque_tache_tire_ses_propres_sieges() -> None:
    """La graine de siège doit dépendre du bot ET du scénario, pas seulement du run.

    `BotControlledEnv._resolve_controlled_player_for_episode` tire le siège d'un hachage de
    (graine, rang d'env, index d'épisode). Toutes les tâches partagent le rang 0 et l'index de
    départ 0 : avec une graine commune, l'épisode i jouait le MÊME siège dans toutes les tâches,
    et le bot du siège agent ne changeait jamais de côté à index donné — le contrôle de chemin de
    décision ne contrôlait alors rien (mesuré : 0 épisode au siège 1 sur un lot de 24).
    """
    graines = {
        _episode_seed(4242, bot, scenario_index, 0)
        for bot in ("alpha", "attrition", "racer")
        for scenario_index in range(4)
    }
    assert len(graines) == 12, "deux tâches ne doivent pas partager leur suite de sièges"


def test_le_deploiement_n_ouvre_aucun_tour_de_joueur() -> None:
    # Le déploiement alterne `current_player` à chaque pose : sans ce refus, la suite canonique
    # serait consommée avant la première phase de commandement.
    assert _opens_new_turn(None, 1, 1, "deployment") is False
    assert _opens_new_turn((1, 1), 1, 2, "deployment") is False


def test_la_suite_s_ouvre_sur_le_premier_joueur_du_premier_round() -> None:
    assert _opens_new_turn(None, 1, 1, "command") is True
    assert _opens_new_turn(None, 1, 2, "command") is False, (
        "commencer au joueur 2 décalerait tout l'épisode d'un demi-round"
    )


def test_un_aller_retour_de_siege_dans_un_tour_n_ouvre_rien() -> None:
    """Défaut MESURÉ : 116 relevés pour 16 épisodes quand tout basculement comptait.

    `current_player` passe à l'adversaire aux points d'arrêt qui lui sont rendus (allocation de
    pertes en tir, désignation de cohérence, sous-phases de combat), puis revient.
    """
    assert _opens_new_turn((2, 1), 2, 2, "shoot") is True     # vraie frontière
    assert _opens_new_turn((2, 2), 2, 1, "shoot") is False    # retour en arrière
    assert _opens_new_turn((2, 2), 2, 2, "fight") is False    # même tour, rien de neuf
    assert _opens_new_turn((2, 2), 1, 2, "move") is False     # round antérieur


def test_un_tour_effondre_ne_desynchronise_pas_la_suite() -> None:
    """Un tour de joueur sans rien à y faire est résolu dans un seul step et reste invisible.

    Défaut MESURÉ sur 1 épisode de 1 200 : en exigeant le successeur immédiat, le tour du
    joueur 1 au round 5 manquait ET la timeline ne se rattrapait jamais.
    """
    assert _opens_new_turn((4, 2), 5, 2, "command") is True, (
        "le tour (5,1) a été sauté : (5,2) doit quand même ouvrir un segment"
    )


def _point(turn: int, player: int, vp1: int, vp2: int, value1: int, value2: int) -> dict:
    return {
        "turn": turn, "player": player,
        "vp_p1": vp1, "vp_p2": vp2, "value_p1": value1, "value_p2": value2,
    }


def test_l_ordre_canonique_des_tours_de_joueur_est_strictement_croissant() -> None:
    suite = [(1, 1), (1, 2), (2, 1), (2, 2), (3, 1)]
    rangs = [_canonical_index(turn, player) for turn, player in suite]
    assert rangs == sorted(rangs), "la suite (1,1), (1,2), (2,1)… doit être ordonnée"
    assert len(set(rangs)) == len(rangs), "deux tours de joueur distincts ne peuvent pas être ex æquo"
    # Le retour au joueur 1 au round suivant AVANCE ; le retour au joueur 1 dans le même round
    # RECULE, et c'est ce qui distingue une frontière d'un aller-retour interne.
    assert _canonical_index(3, 1) > _canonical_index(2, 2)
    assert _canonical_index(2, 1) < _canonical_index(2, 2)


def test_un_segment_porte_la_valeur_detruite_pendant_ce_tour_de_joueur() -> None:
    timeline = [
        _point(1, 1, 0, 0, 500, 500),
        _point(1, 2, 0, 0, 500, 460),   # le joueur 1 a détruit 40 chez le joueur 2
        _point(2, 1, 0, 0, 470, 460),   # le joueur 2 a détruit 30 chez le joueur 1
    ]
    segments = _segments(timeline)
    assert [(s["turn"], s["player"]) for s in segments] == [(1, 1), (1, 2)]
    assert segments[0]["value_lost_p2"] == 40
    assert segments[0]["value_lost_p1"] == 0
    assert segments[1]["value_lost_p1"] == 30
    assert segments[1]["value_lost_p2"] == 0


def test_un_tour_de_joueur_saute_ne_fabrique_pas_de_segment_fantome() -> None:
    """Tour effondré : aucun segment ne lui est attribué, et la suite reste lisible.

    Le tour du joueur 1 au round 2 n'apparaît pas dans la timeline (résolu en un seul step).
    L'attrition observée entre (1,2) et (2,2) appartient alors à un segment qui COUVRE les deux
    tours — c'est une lecture honnête du relevé, alors qu'inventer un segment (2,1) vide
    attribuerait au joueur 1 une destruction qu'il n'a pas forcément faite.
    """
    timeline = [
        _point(1, 1, 0, 0, 500, 500),
        _point(1, 2, 0, 0, 500, 460),
        _point(2, 2, 0, 0, 450, 460),
    ]
    segments = _segments(timeline)
    assert [(s["turn"], s["player"]) for s in segments] == [(1, 1), (1, 2)]
    assert segments[1]["value_lost_p1"] == 50
    assert all(s["turn"] != 2 or s["player"] != 1 for s in segments)


def test_une_timeline_d_un_seul_point_ne_rend_aucun_segment() -> None:
    assert _segments([_point(1, 1, 0, 0, 500, 500)]) == []


def test_les_missions_non_implementees_sont_refusees_avec_leur_raison() -> None:
    """Le moteur ne lit que le format `scoring` ; les missions `scoring_events` lèveraient au
    premier tour marquant, plusieurs minutes après le lancement, sur un message muet sur la cause."""
    _require_supported_mission("objectives_control")  # ne doit pas lever
    with pytest.raises(ValueError, match="scoring_events"):
        _require_supported_mission("battlefield_dominance")
    with pytest.raises(ValueError, match="introuvable"):
        _require_supported_mission("mission_qui_n_existe_pas")


def test_le_contrefactuel_de_marquage_est_une_variante_declaree() -> None:
    # `--variant` est contraint par ce tuple : une variante mal orthographiée doit être refusée
    # par argparse, pas silencieusement ignorée par `_install_variant`.
    assert VARIANTS[0] == "none"
    assert "p2-scores-end-of-turn" in VARIANTS


def test_le_plateau_suit_le_suffixe_de_resolution_de_l_agent() -> None:
    assert board_path_for_agent("ArmageddonAgent_x1") == "board/44x60x1"
    with pytest.raises(ValueError, match="_x1 / _x5"):
        board_path_for_agent("AgentSansSuffixe")
