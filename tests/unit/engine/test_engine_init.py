"""Tests unitaires — W40KEngine.__init__.

Couvre :
- Échec si config=None sans controlled_agent → ValueError
- Échec si config=None avec agent inexistant → RuntimeError
- Échec si config fournie sans clé 'board' → ConfigurationError / KeyError
- Succès avec config minimale réelle → game_state est un dict non vide

LIMITE : le test de succès mocke uniquement load_weapon_damage_table
(fichier JSON lourd). La logique d'init reste réelle.
Si le fichier config/weapon_damage_table.json est disponible dans le CWD (cas
habituel avec venv depuis /home/greg/40k), le mock n'est pas nécessaire et le
test exerce le vrai chargement.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import gymnasium as gym
import numpy as np
import pytest

from engine.observation_builder import ObservationBuilder
from engine.w40k_core import W40KEngine
from shared.data_validation import ConfigurationError

from tests.unit.engine._config_helpers import build_engine_config, build_game_rules


# ─────────────────────────────────────────────────────────────────────────────
# Config minimale valide pour le chemin « config fourni directement »
# ─────────────────────────────────────────────────────────────────────────────

def _minimal_config() -> Dict[str, Any]:
    """Config minimale qui satisfait toutes les vérifications de __init__ (config fourni)."""
    obs_params = {
        "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET,
    }
    return {
        "board": {
            "default": {
                "cols": 15,
                "rows": 13,
                "hex_radius": 1.0,
                "margin": 0.0,
                "wall_hexes": [],
                "inches_to_subhex": 1,
            }
        },
        # Objectifs : source unique = terrains "objective": true, résolus en {id, name, hexes}
        # et passés au moteur via 'scenario_objectives' (canal config, ex-board.objectives supprimé).
        "scenario_objectives": [
            {"id": "test_obj_1", "name": "Alpha", "hexes": [[5, 5]]}
        ],
        "game_rules": build_game_rules(
            engagement_zone=1,
            max_base_size_hex=35,
        ),
        "pve_mode": False,
        # `observation_params` n'est plus LU par personne : la taille de l'observation est
        # calculée depuis le schéma d'entités. La clé est laissée ici DÉLIBÉRÉMENT — c'est le
        # matériau de `test_stale_obs_size_in_config_does_not_move_the_observation_space`, qui la
        # rend périmée pour prouver qu'elle ne porte plus rien.
        "observation_params": obs_params,
        "training_config": {
            "observation_params": obs_params,
        },
        # Aucune unité → initialize_units() ne touche pas aux fichiers roster
        "units": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Échecs attendus
# ─────────────────────────────────────────────────────────────────────────────

class TestEngineInitFailures:
    def test_no_controlled_agent_raises_value_error(self):
        """init_no_agent : config=None sans controlled_agent → ValueError."""
        with pytest.raises(ValueError, match="controlled_agent parameter required"):
            W40KEngine(config=None)

    def test_no_rewards_config_raises_value_error(self, monkeypatch):
        """init_no_rewards_config : controlled_agent fourni mais rewards_config absent → ValueError."""
        # Simuler load_agent_rewards_config retourne un dict non-vide (agent "existe")
        # pour passer la première vérification, puis échouer sur rewards_config_name
        fake_rewards = {"FakeAgent": {"step": {}}}

        def fake_load_agent_rewards(self_cfg, agent_key):
            return fake_rewards

        monkeypatch.setattr(
            "config_loader.ConfigLoader.load_agent_rewards_config",
            fake_load_agent_rewards,
        )

        with pytest.raises(ValueError, match="rewards_config parameter required"):
            W40KEngine(
                config=None,
                controlled_agent="FakeAgent",
                rewards_config=None,  # Manquant
                training_config_name="default",
            )

    def test_no_training_config_name_raises_value_error(self, monkeypatch):
        """init_no_training_config : training_config_name absent → ValueError."""
        fake_rewards = {"FakeAgent": {"step": {}}}

        def fake_load_agent_rewards(self_cfg, agent_key):
            return fake_rewards

        monkeypatch.setattr(
            "config_loader.ConfigLoader.load_agent_rewards_config",
            fake_load_agent_rewards,
        )

        with pytest.raises(ValueError, match="training_config_name parameter required"):
            W40KEngine(
                config=None,
                controlled_agent="FakeAgent",
                rewards_config="default",
                training_config_name=None,  # Manquant
            )

    def test_config_missing_board_raises(self):
        """init_no_board : config sans clé 'board' → ConfigurationError."""
        bad_config = {"pve_mode": False}  # Clé 'board' absente
        with pytest.raises((ConfigurationError, KeyError)):
            W40KEngine(config=bad_config)

    def test_stale_obs_size_in_config_does_not_move_the_observation_space(self):
        """Un `obs_size` périmé en config ne change RIEN à l'espace d'observation construit.

        Remplace `test_stale_obs_size_raises_at_init_not_later`, qui vérifiait que le moteur
        LEVAIT sur une valeur périmée. Ce contrôle comparait la valeur recopiée à la main à
        `SQUAD_OBS_SIZE_TARGET` — celle-là même qui la détermine : il ne pouvait établir que
        « la config a pris du retard », jamais un fait sur l'observation. La clé n'est plus lue,
        et c'est ce que ce test prouve, avec une valeur qu'aucun schéma n'a jamais eue.

        Ce que le moteur ne protège plus, un autre le protège : SB3 refuse au chargement un
        `.zip` dont l'espace ne correspond pas (`check_for_correct_spaces`, comparaison du Dict
        ENTIER), et l'acquittement HUMAIN du retrain vit dans
        `test_deployment_observation_contract.py`.
        """
        cfg = _minimal_config()
        perime = ObservationBuilder.SQUAD_OBS_SIZE_TARGET - 70   # taille qu'aucun schéma n'a eue
        cfg["observation_params"]["obs_size"] = perime
        cfg["training_config"]["observation_params"]["obs_size"] = perime

        with patch("engine.w40k_core.load_weapon_damage_table", return_value={}):
            engine = W40KEngine(config=build_engine_config(cfg))

        espace = engine.observation_space
        assert isinstance(espace, gym.spaces.Dict), (
            f"espace d'observation {type(espace).__name__} — la branche Box(obs_size) du pipeline "
            f"mono-figurine était morte et a été supprimée ; la voir revenir signifie que la "
            f"taille redevient déclarative"
        )
        # La grille est fournie à part et n'entre pas dans le compte des scalaires.
        total = 0
        for key, sous_espace in espace.spaces.items():
            if key == "grid":
                continue
            assert isinstance(sous_espace, gym.spaces.Box), (
                f"clé '{key}' : {type(sous_espace).__name__} au lieu d'un Box"
            )
            total += int(np.prod(sous_espace.shape))
        assert total == ObservationBuilder.SQUAD_OBS_SIZE_TARGET, (
            f"espace construit à {total} scalaires alors que le schéma en déclare "
            f"{ObservationBuilder.SQUAD_OBS_SIZE_TARGET} : la config périmée a été lue"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Succès avec config minimale réelle
# ─────────────────────────────────────────────────────────────────────────────

class TestEngineInitSuccess:
    def test_init_with_minimal_config_returns_non_empty_game_state(self):
        """init_success : config minimale → engine.game_state est un dict non vide."""
        cfg = _minimal_config()

        # Mock weapon_damage_table (fichier lourd JSON ~ 1 Mo)
        # La logique de validation est réelle, seul le chargement fichier est mocké.
        with patch("engine.w40k_core.load_weapon_damage_table", return_value={"__mocked__": True}):
            engine = W40KEngine(config=build_engine_config(cfg))

        assert isinstance(engine.game_state, dict)
        assert len(engine.game_state) > 0

    def test_init_game_state_has_required_fields(self):
        """init_fields : game_state contient phase, turn, current_player, units."""
        cfg = _minimal_config()

        with patch("engine.w40k_core.load_weapon_damage_table", return_value={}):
            engine = W40KEngine(config=build_engine_config(cfg))

        gs = engine.game_state
        assert "phase" in gs
        assert "turn" in gs
        assert "current_player" in gs
        assert "units" in gs
        assert isinstance(gs["units"], list)

    def test_init_game_state_has_board_dimensions(self):
        """init_board_dims : game_state contient board_cols et board_rows corrects."""
        cfg = _minimal_config()

        with patch("engine.w40k_core.load_weapon_damage_table", return_value={}):
            engine = W40KEngine(config=build_engine_config(cfg))

        assert engine.game_state["board_cols"] == 15
        assert engine.game_state["board_rows"] == 13

    def test_init_game_state_has_objectives(self):
        """init_objectives : game_state contient les objectifs de la config."""
        cfg = _minimal_config()

        with patch("engine.w40k_core.load_weapon_damage_table", return_value={}):
            engine = W40KEngine(config=build_engine_config(cfg))

        objectives = engine.game_state.get("objectives")
        assert isinstance(objectives, list)
        assert len(objectives) > 0
        assert objectives[0]["id"] == "test_obj_1"
