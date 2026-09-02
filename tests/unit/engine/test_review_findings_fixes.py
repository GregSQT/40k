"""Verrous pour les bugs identifiés lors du code review de game_state.py.

F2 — path traversal via double-slash dans _resolve_roster_ref
F7 — arme RNG par-figurine sans clé "RNG" passe en silence le scaling à x5
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from engine.game_state import GameStateManager
from shared.data_validation import ConfigurationError


# ─────────────────────────────────────────────────────────────────────────────
# F2 — path traversal via double-slash dans _resolve_roster_ref
# ─────────────────────────────────────────────────────────────────────────────

def _minimal_manager() -> GameStateManager:
    config = {
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0, "inches_to_subhex": 1}},
    }
    return GameStateManager(config, unit_registry=None)


class TestResolveRosterRefPathTraversal:

    def test_double_slash_leve_une_valeur_invalide(self):
        """training//etc/passwd.json → ValueError ; avant correction, ref_filename='/etc/passwd.json'
        et pathlib écrasait la base pour pointer vers /etc/passwd.json.
        """
        mgr = _minimal_manager()
        with pytest.raises(ValueError, match="unsafe roster ref"):
            mgr._resolve_roster_ref(
                raw_ref="training//etc/passwd.json",
                expected_split="training",
                scenario_file="scenario.json",
                field_name="roster_ref",
                allow_random=False,
                scenario_agent_key="ArmageddonAgent",
                scale_name="x1",
                roster_kind="agent",
                random_seed=None,
            )

    def test_chemin_normal_ne_leve_pas_unsafe(self):
        """training/valid.json → ne lève pas 'unsafe roster ref' (peut lever FileNotFoundError ensuite).

        On vérifie que le garde de path traversal ne rejette pas un chemin sans double-slash.
        Les levées ultérieures (fichier absent) sont en dehors du périmètre.
        """
        mgr = _minimal_manager()
        try:
            mgr._resolve_roster_ref(
                raw_ref="training/valid.json",
                expected_split="training",
                scenario_file="scenario.json",
                field_name="roster_ref",
                allow_random=False,
                scenario_agent_key="ArmageddonAgent",
                scale_name="x1",
                roster_kind="agent",
                random_seed=None,
            )
        except ValueError as exc:
            assert "unsafe roster ref" not in str(exc), (
                f"chemin valide ne doit pas lever 'unsafe roster ref' : {exc}"
            )
        except FileNotFoundError:
            pass  # fichier absent en test : normal


# ─────────────────────────────────────────────────────────────────────────────
# F7 — arme RNG par-figurine sans clé "RNG" passe en silence le scaling à x5
# ─────────────────────────────────────────────────────────────────────────────

def _make_manager_x5() -> GameStateManager:
    config = {
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0, "inches_to_subhex": 5}},
        "controlled_player": 1,
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
    }
    return GameStateManager(config, unit_registry=None)


def _full_unit_data_minimal() -> dict:
    return {
        "unit_type": "MainType",
        "DISPLAY_NAME": "Marine",
        "ICON": "marine.png",
        "ICON_SCALE": 1.0,
        "ILLUSTRATION_RATIO": 1.0,
        "HP_MAX": 2,
        "HP": 2,
        "T": 4,
        "ARMOR_SAVE": 3,
        "INVUL_SAVE": 7,
        "LD": 6,
        "OC": 2,
        "MOVE": 6,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 4.0,
        "VALUE": 20,
        "RNG_WEAPONS": [{"code": "bolt_rifle", "RNG": 24, "NB": 2, "STR": 4, "AP": 1, "DMG": 1, "WEAPON_RULES": []}],
        "CC_WEAPONS": [{"code": "melee", "NB": 3, "STR": 4, "AP": 0, "DMG": 1, "ATK": 3, "WEAPON_RULES": []}],
        "UNIT_RULES": [],
        "UNIT_KEYWORDS": [],
        "FACTION_KEYWORDS": [],
    }


def _heavy_model_data(**overrides: object) -> dict:
    base = {
        "DISPLAY_NAME": "Heavy",
        "ICON": "heavy.png",
        "ICON_SCALE": 1.0,
        "ILLUSTRATION_RATIO": 1.0,
        "HP_MAX": 3,
        "HP": 3,
        "T": 5,
        "ARMOR_SAVE": 2,
        "INVUL_SAVE": 7,
        "LD": 7,
        "OC": 2,
        "MOVE": 5,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 4.0,
        "VALUE": 40,
        "CC_WEAPONS": [],
        "UNIT_RULES": [],
        "UNIT_KEYWORDS": [],
        "FACTION_KEYWORDS": [],
    }
    return {**base, **overrides}


def _unit_data_with_per_model_override() -> dict:
    return {
        "id": "u1",
        "player": 1,
        "unit_type": "MainType",
        "col": 5,
        "row": 5,
        "models": [
            {"col": 5, "row": 5},
            {"col": 6, "row": 5, "unit_type": "HeavyModel"},
        ],
    }


class TestPerModelRngScaling:

    def test_rng_weapon_sans_cle_rng_leve_a_x5(self):
        """Un override par-figurine avec RNG_WEAPONS sans champ 'RNG' lève ConfigurationError à x5.

        Avant correction, `if 'RNG' in w` ignorait silencieusement le scaling,
        laissant la portée à sa valeur native non-scalée (ex. 24 subhex au lieu de 120).
        """
        mgr = _make_manager_x5()
        mock_registry = MagicMock()
        mock_registry.get_unit_data.return_value = _heavy_model_data(
            RNG_WEAPONS=[{"code": "heavy_bolter", "NB": 3, "STR": 5, "AP": 2, "DMG": 2, "WEAPON_RULES": []}],
        )

        with pytest.raises(ConfigurationError, match="RNG"):
            mgr._build_enhanced_unit(
                unit_data=_unit_data_with_per_model_override(),
                full_unit_data=_full_unit_data_minimal(),
                unit_type="MainType",
                unit_player=1,
                player_deployment_type="fixed",
                chosen_col=5,
                chosen_row=5,
                unit_registry=mock_registry,
            )

    def test_rng_weapon_avec_cle_rng_scale_correctement_a_x5(self):
        """Un override par-figurine avec RNG_WEAPONS avec champ 'RNG' est scalé correctement."""
        mgr = _make_manager_x5()
        mock_registry = MagicMock()
        mock_registry.get_unit_data.return_value = _heavy_model_data(
            RNG_WEAPONS=[{"code": "heavy_bolter", "RNG": 36, "NB": 3, "STR": 5, "AP": 2, "DMG": 2, "WEAPON_RULES": []}],
        )

        result = mgr._build_enhanced_unit(
            unit_data=_unit_data_with_per_model_override(),
            full_unit_data=_full_unit_data_minimal(),
            unit_type="MainType",
            unit_player=1,
            player_deployment_type="fixed",
            chosen_col=5,
            chosen_row=5,
            unit_registry=mock_registry,
        )

        # La figurine HeavyModel (index 1) doit avoir RNG = 36 * 5 = 180
        heavy_model = result["models"][1]
        scaled_rng = heavy_model["RNG_WEAPONS"][0]["RNG"]
        assert scaled_rng == 180, f"RNG attendu=180, obtenu={scaled_rng}"
