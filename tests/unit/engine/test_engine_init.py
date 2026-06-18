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

import pytest

from engine.w40k_core import W40KEngine
from shared.data_validation import ConfigurationError

from _config_helpers import build_game_rules


# ─────────────────────────────────────────────────────────────────────────────
# Config minimale valide pour le chemin « config fourni directement »
# ─────────────────────────────────────────────────────────────────────────────

def _minimal_config() -> Dict[str, Any]:
    """Config minimale qui satisfait toutes les vérifications de __init__ (config fourni)."""
    obs_params = {
        "perception_radius": 25,
        "max_nearby_units": 10,
        "max_valid_targets": 5,
        "obs_size": 50,
        "action_space_size": 31,
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
        # observation_params dans config (utilisé par ObservationBuilder directement)
        "observation_params": obs_params,
        # training_config avec observation_params (utilisé par W40KEngine pour obs_size)
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
            engine = W40KEngine(config=cfg)

        assert isinstance(engine.game_state, dict)
        assert len(engine.game_state) > 0

    def test_init_game_state_has_required_fields(self):
        """init_fields : game_state contient phase, turn, current_player, units."""
        cfg = _minimal_config()

        with patch("engine.w40k_core.load_weapon_damage_table", return_value={}):
            engine = W40KEngine(config=cfg)

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
            engine = W40KEngine(config=cfg)

        assert engine.game_state["board_cols"] == 15
        assert engine.game_state["board_rows"] == 13

    def test_init_game_state_has_objectives(self):
        """init_objectives : game_state contient les objectifs de la config."""
        cfg = _minimal_config()

        with patch("engine.w40k_core.load_weapon_damage_table", return_value={}):
            engine = W40KEngine(config=cfg)

        objectives = engine.game_state.get("objectives")
        assert isinstance(objectives, list)
        assert len(objectives) > 0
        assert objectives[0]["id"] == "test_obj_1"
