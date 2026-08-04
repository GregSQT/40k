"""Règle 14.02 — le checkpoint de contrôle d'objectif tourne AUSSI en entraînement.

DÉFAUT CORRIGÉ (2026-08-04, mesuré). `run_objective_control_checkpoint` sort immédiatement sur
``if not check_cfg`` quand la section ``objective_control_check`` manque de la config du moteur.
Les deux constructeurs de l'API/PvP la posaient (`api_server.py:1711` et `:1881`) ; la branche
d'ENTRAÎNEMENT de `W40KEngine.__init__` l'avait omise. Le checkpoint 14.02 était donc un
**no-op complet en gym** : `objective_controllers` n'y était rafraîchi que par effet de bord des
chemins de scoring VP (`calculate_objective_control` appelé en direct), à des moments qui ne sont
pas ceux de la règle. Mesuré avant correction : le contrôle restait figé tout le tour 1, et ne
changeait qu'aux phases de commandement.

C'est le motif « code testé mais jamais appelé » : `refresh_objective_control_on_boundary` avait
été écrite pour partager le checkpoint entre gym et PvP, sa docstring l'annonce, et la config ne
l'a jamais atteinte du côté gym.

Ce fichier verrouille les deux moitiés : la config est complète, ET le checkpoint tire vraiment.
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCENARIO = (
    PROJECT_ROOT
    / "config" / "agents" / "ArmageddonAgent" / "scenarios" / "training"
    / "scenario_training_armageddon.json"
)

#: Sections de `config/game_config.json` que le MOTEUR lit, quel que soit le chemin de
#: construction. C'est le contrat partagé entre la branche d'entraînement
#: (`W40KEngine.__init__`, `config is None`) et les deux constructeurs de `services/api_server`.
#: En omettre une ne lève nulle part : la fonctionnalité qu'elle porte s'éteint en silence — ce
#: qui est arrivé à `objective_control_check` pendant toute la vie du chemin gym.
GAME_CONFIG_SECTIONS_REQUIRED_BY_ENGINE = (
    "game_rules",
    "objective_control_check",
    "move",
    "charge",
)


@pytest.fixture(scope="module")
def gym_engine():
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    engine = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent", training_n_envs=1,
        scenario_file=str(SCENARIO), unit_registry=UnitRegistry(),
        quiet=True, gym_training_mode=True,
    )
    engine.reset(seed=0)
    return engine


def test_la_config_dentrainement_porte_toutes_les_sections_du_moteur(gym_engine) -> None:
    """Chaque section de `game_config.json` dont le moteur dépend est PRÉSENTE.

    Le contenu de la section n'est PAS comparé à celui du loader : celui-ci est mémoïsé et la
    config du moteur en stocke la RÉFÉRENCE, donc l'égalité comparerait l'objet avec lui-même
    (`a is b` vaut True) — une assertion qui ne peut jamais échouer. On vérifie ce qui a un sens :
    la section est présente et EXPLOITABLE, c'est-à-dire qu'elle déclare au moins un point de
    contrôle. Une section vide rendrait `run_objective_control_checkpoint` inerte exactement
    comme son absence (`if not points: return`), sans qu'aucune présence ne le signale.
    """
    for section in GAME_CONFIG_SECTIONS_REQUIRED_BY_ENGINE:
        assert section in gym_engine.config, (
            f"section '{section}' absente de la config du moteur d'ENTRAÎNEMENT : la "
            f"fonctionnalité qu'elle porte s'éteint en silence (cf. en-tête du fichier)"
        )
    points = gym_engine.config["objective_control_check"]["points"]
    assert points, (
        "`objective_control_check.points` est vide : `run_objective_control_checkpoint` sort "
        "sur `if not points` et la règle 14.02 s'éteint, comme si la section manquait"
    )
    assert {"phase": "command", "moment": "end"} in points, (
        "la fin de la phase de commandement n'est plus un point de contrôle : c'est elle qui "
        "détermine le contrôle lu au début de la phase de mouvement (cp_gain_on_objective)"
    )


def test_le_checkpoint_1402_tire_reellement_en_entrainement(gym_engine) -> None:
    """VERT VACANT : une config complète ne prouve pas que le checkpoint s'exécute.

    On force une frontière de phase et on exige que `refresh_objective_control_on_boundary`
    rende True ET que `objective_controllers` soit renseigné. Sans la section, la méthode rend
    True aussi (elle a bien vu la frontière) mais `run_objective_control_checkpoint` sort avant
    d'écrire quoi que ce soit — d'où la vérification sur le CONTENU, pas sur le retour.
    """
    game_state = gym_engine.game_state
    game_state["objective_controllers"] = {}
    # Deux appels : le premier mémorise la frontière courante, le second en franchit une.
    game_state["_objective_control_last_boundary"] = ("command", int(game_state["turn"]))
    game_state["phase"] = "move"

    fired = gym_engine.state_manager.refresh_objective_control_on_boundary(game_state)

    assert fired is True, "la frontière command -> move n'a pas été détectée"
    assert game_state["objective_controllers"], (
        "le checkpoint 14.02 n'a rien écrit : la section `objective_control_check` manque de la "
        "config du moteur, et `run_objective_control_checkpoint` sort sur `if not check_cfg`"
    )
    objectives = game_state["objectives"]
    assert set(game_state["objective_controllers"]) == {str(o["id"]) for o in objectives}, (
        "le checkpoint n'a pas évalué tous les objectifs du scénario"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cache des zones d'objectif
# ─────────────────────────────────────────────────────────────────────────────

def test_le_cache_de_zones_rend_les_memes_zones_et_se_perime_a_la_rotation() -> None:
    """`objective_hex_zones` mémoïse par IDENTITÉ de la liste source (perf, 1,46 % d'un épisode).

    Un cache de géométrie sur un chemin de RÈGLE (14.02) ne vaut que s'il est prouvé équivalent
    ET incapable de rester périmé. Les deux moitiés sont ici :
      - mêmes zones, au hexe près, avec et sans cache ;
      - remplacer `game_state["objectives"]` (reset, rotation de roster) suffit à l'invalider,
        parce que la clé du cache est la liste ELLE-MÊME, comparée par `is`. C'est ce qui évite
        d'avoir un site d'invalidation à ne pas oublier — le mode de défaillance d'un cache
        invalidé à la main.

    Mesuré le 2026-08-04 : 3,9 ms par appel sans cache (10 538 hexes reparsés et normalisés),
    0,2 µs avec, 62 appels par épisode d'entraînement.
    """
    from engine.game_state import objective_hex_zones

    game_state = {
        "objectives": [
            {"id": "a", "hexes": [[1, 1], [1, 2]]},
            {"id": "b", "hexes": [{"col": 5, "row": 5}]},
        ]
    }
    cached = objective_hex_zones(game_state)
    assert "_objective_hex_zones_cache" in game_state, "rien n'a été mémoïsé"

    fresh_state = {"objectives": game_state["objectives"]}
    fresh = objective_hex_zones(fresh_state)
    assert [(i, sorted(z)) for i, z in cached] == [(i, sorted(z)) for i, z in fresh], (
        "le cache ne rend pas les mêmes zones qu'un calcul neuf"
    )

    # Rotation de roster : une NOUVELLE liste est affectée -> le cache doit être ignoré.
    game_state["objectives"] = [{"id": "c", "hexes": [[9, 9]]}]
    after = objective_hex_zones(game_state)
    assert [i for i, _ in after] == ["c"], (
        "le cache a survécu au remplacement de `objectives` : il rendrait les zones de l'ancien "
        "scénario après une rotation de roster"
    )
