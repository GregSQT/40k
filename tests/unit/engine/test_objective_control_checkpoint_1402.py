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

    Présence seulement pour `game_rules` / `move` / `charge` : le moteur convertit leurs
    distances en subhex à l'init (× `inches_to_subhex`), donc une égalité au JSON serait fausse
    par construction. `objective_control_check` ne porte aucune distance — il est comparé, lui,
    à l'identique, puisque c'est la section dont l'omission a éteint la règle 14.02.
    """
    from config_loader import get_config_loader

    game_config = get_config_loader().get_game_config()
    for section in GAME_CONFIG_SECTIONS_REQUIRED_BY_ENGINE:
        assert section in gym_engine.config, (
            f"section '{section}' absente de la config du moteur d'ENTRAÎNEMENT : la "
            f"fonctionnalité qu'elle porte s'éteint en silence (cf. en-tête du fichier)"
        )
    assert gym_engine.config["objective_control_check"] == game_config["objective_control_check"]


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
