"""Tests unitaires — W40KEngine.reset().

Vérifie que reset() remet correctement à zéro le game_state entre deux épisodes :
- turn=1, game_over=False, phase="move" (après cascade command→move)
- Sets de tracking vidés (units_moved, units_fled, units_shot, etc.)
- HP des unités restauré à HP_MAX
- Positions remises aux valeurs de la config
- episode_number incrémenté
- Pools d'activation vidés

Stratégie : créer un engine réel avec config minimale + 2 unités,
simuler un état mi-partie, puis appeler reset() et vérifier l'état.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import numpy as np
import pytest

from engine.observation_builder import ObservationBuilder
from engine.w40k_core import W40KEngine
from tests._state_invariants import TURN_STATE_KEYS, turn_state_invariants


@pytest.fixture(autouse=True)
def mock_build_obs(monkeypatch):
    """Mocke _build_observation pour tous les tests — on ne teste pas l'obs builder ici."""
    # `_step_observation` appelle l'IMPLEMENTATION `_build_observation_and_mask`, pas la
    # facade : doubler la seule facade laissait tourner le vrai constructeur d'observation
    # (et son `advance_phase` sur pool vide) sur ces etats de test.
    monkeypatch.setattr(
        W40KEngine, "_build_observation_and_mask", lambda self, *_a, **_k: (np.zeros(ObservationBuilder.SQUAD_OBS_SIZE_TARGET), None)
    )
    monkeypatch.setattr(W40KEngine, "_build_observation", lambda self, *_a, **_k: np.zeros(ObservationBuilder.SQUAD_OBS_SIZE_TARGET))


# ─────────────────────────────────────────────────────────────────────────────
# Config minimale avec 2 unités
# ─────────────────────────────────────────────────────────────────────────────

def _unit_cfg(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    """Config minimale d'unité pour W40KEngine.__init__."""
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "unitType": "TestUnit",
        "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 3,
        "HP_MAX": 3,
        "MOVE": 6,
        "T": 4,
        "ARMOR_SAVE": 4,
        "INVUL_SAVE": 0,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "UNIT_RULES": [],
        "UNIT_KEYWORDS": [],
        "LD": 7,
        "OC": 1,
        "VALUE": 100,
        "ICON": "test",
        "ICON_SCALE": 1.0,
        "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 2.5,
    }


def _minimal_config_with_units() -> Dict[str, Any]:
    """Config minimale valide avec 2 unités pour tester reset()."""
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
                "objectives": [
                    {"id": "test_obj_1", "name": "Alpha", "hexes": [[5, 5]]}
                ],
                "inches_to_subhex": 1,
            }
        },
        "game_rules": {
            "engagement_zone": 1,
            "engagement_zone_vertical": 5,
            "max_base_size_hex": 35,
        },
        "charge": {
            "charge_max_distance": 12,
        },
        "pve_mode": False,
        "observation_params": obs_params,
        "training_config": {
            "observation_params": obs_params,
        },
        "units": [
            _unit_cfg(1, 1, 3, 3),
            _unit_cfg(2, 2, 10, 10),
        ],
    }


def _make_engine() -> W40KEngine:
    """Crée un engine réel avec config minimale."""
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        return W40KEngine(config=_minimal_config_with_units())


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestEngineResetBasicState:

    def test_reset_increments_episode_number(self):
        """reset_episode : episode_number incrémenté après reset()."""
        engine = _make_engine()
        episode_before = engine.episode_number

        engine.reset()

        assert engine.episode_number == episode_before + 1

    def test_reset_episode_number_reflected_in_game_state(self):
        """reset_episode_gs : game_state['episode_number'] == engine.episode_number après reset()."""
        engine = _make_engine()

        engine.reset()

        assert engine.game_state["episode_number"] == engine.episode_number

    def test_reset_clears_game_over_flag(self):
        """reset_game_over : game_over remis à False après reset()."""
        engine = _make_engine()
        engine.game_state["game_over"] = True
        engine.game_state["winner"] = 1

        engine.reset()

        assert engine.game_state["game_over"] is False

    def test_reset_clears_winner(self):
        """reset_winner : winner remis à None après reset()."""
        engine = _make_engine()
        engine.game_state["winner"] = 2

        engine.reset()

        assert engine.game_state["winner"] is None

    def test_reset_sets_turn_to_1(self):
        """reset_turn : turn remis à 1 après reset()."""
        engine = _make_engine()
        engine.game_state["turn"] = 5

        engine.reset()

        assert engine.game_state["turn"] == 1

    def test_reset_sets_current_player_to_1(self):
        """reset_player : current_player remis à 1 après reset()."""
        engine = _make_engine()
        engine.game_state["current_player"] = 2

        engine.reset()

        assert engine.game_state["current_player"] == 1


class TestEngineResetTrackingSets:

    def test_reset_clears_units_moved(self):
        """reset_units_moved : units_moved vidé après reset()."""
        engine = _make_engine()
        engine.game_state["units_moved"] = {"1", "2"}

        engine.reset()

        assert engine.game_state["units_moved"] == set()

    def test_reset_clears_units_fled(self):
        """reset_units_fled : units_fled vidé après reset()."""
        engine = _make_engine()
        engine.game_state["units_fled"] = {"1"}

        engine.reset()

        assert engine.game_state["units_fled"] == set()

    def test_reset_clears_units_shot(self):
        """reset_units_shot : units_shot vidé après reset()."""
        engine = _make_engine()
        engine.game_state["units_shot"] = {"1", "2"}

        engine.reset()

        assert engine.game_state["units_shot"] == set()

    def test_reset_clears_units_charged(self):
        """reset_units_charged : units_charged vidé après reset()."""
        engine = _make_engine()
        engine.game_state["units_charged"] = {"1"}

        engine.reset()

        assert engine.game_state["units_charged"] == set()

    def test_reset_clears_units_fought(self):
        """reset_units_fought : units_fought vidé après reset()."""
        engine = _make_engine()
        engine.game_state["units_fought"] = {"1", "2"}

        engine.reset()

        assert engine.game_state["units_fought"] == set()

    def test_reset_clears_units_advanced(self):
        """reset_units_advanced : units_advanced vidé après reset()."""
        engine = _make_engine()
        engine.game_state["units_advanced"] = {"1"}

        engine.reset()

        assert engine.game_state["units_advanced"] == set()


class TestEngineResetUnitState:

    def test_reset_restores_unit_hp_to_max(self):
        """reset_hp : HP_CUR de chaque unité restauré à HP_MAX."""
        engine = _make_engine()
        # Simuler dégâts
        for unit in engine.game_state["units"]:
            unit["HP_CUR"] = 1

        engine.reset()

        for unit in engine.game_state["units"]:
            assert unit["HP_CUR"] == unit["HP_MAX"]

    def test_reset_restores_unit_positions(self):
        """reset_pos : positions des unités remises aux valeurs de la config."""
        engine = _make_engine()
        # Simuler mouvement
        for unit in engine.game_state["units"]:
            unit["col"] = 1
            unit["row"] = 1

        engine.reset()

        # Les unités doivent retrouver leurs positions d'origine (config)
        cfg_positions = {str(u["id"]): (u["col"], u["row"]) for u in _minimal_config_with_units()["units"]}
        for unit in engine.game_state["units"]:
            uid = str(unit["id"])
            orig_col, orig_row = cfg_positions[uid]
            assert unit["col"] == orig_col
            assert unit["row"] == orig_row

    def test_reset_rebuilds_units_cache(self):
        """reset_cache : units_cache reconstruit après reset()."""
        engine = _make_engine()
        # Vider le cache manuellement
        engine.game_state["units_cache"] = {}

        engine.reset()

        # Cache doit être reconstruit avec les 2 unités
        assert len(engine.game_state["units_cache"]) == 2

    def test_reset_preserves_unit_list(self):
        """reset_units : la liste des unités est préservée après reset()."""
        engine = _make_engine()
        unit_ids_before = {str(u["id"]) for u in engine.game_state["units"]}

        engine.reset()

        unit_ids_after = {str(u["id"]) for u in engine.game_state["units"]}
        assert unit_ids_before == unit_ids_after


class TestEngineResetPools:

    def test_reset_clears_fight_subphase(self):
        """reset_fight_subphase : fight_subphase remis à None après reset()."""
        engine = _make_engine()
        engine.game_state["fight_subphase"] = "alternating_active"

        engine.reset()

        assert engine.game_state["fight_subphase"] is None

    def test_reset_clears_action_logs(self):
        """reset_action_logs : action_logs vidé après reset()."""
        engine = _make_engine()
        engine.game_state["action_logs"] = [{"type": "move", "message": "test"}]

        engine.reset()

        assert engine.game_state["action_logs"] == []


class TestTurnStateInvariantsConformity:
    """Verrou de dérive du socle ``tests/_state_invariants.py``.

    Le socle **réplique** la liste des invariants d'état de tour au lieu de la dériver du moteur
    (les fixtures unitaires ne peuvent pas construire un engine complet). Ces deux tests sont ce
    qui empêche la copie de diverger : ils comparent le socle à ce que ``reset()`` produit
    réellement. Si le moteur ajoute, retire ou renomme un invariant, ils rougissent ici — pas dans
    62 fixtures silencieuses.
    """

    def test_socle_keys_all_posed_by_reset(self):
        """conformity_keys : les 20 clés du socle existent toutes dans le game_state après reset()."""
        engine = _make_engine()

        engine.reset()

        absentes = sorted(k for k in TURN_STATE_KEYS if k not in engine.game_state)
        assert absentes == [], f"Le socle réplique des clés que reset() ne pose pas : {absentes}"

    def test_socle_values_match_reset(self):
        """conformity_values : chaque valeur du socle == la valeur posée par reset()."""
        engine = _make_engine()

        engine.reset()

        socle = turn_state_invariants()
        # Les clés absentes du game_state sont le sujet du test précédent : ici on ne juge que
        # les valeurs, sinon une clé fantôme dans le socle remonterait en KeyError illisible.
        divergentes = {
            k: (v, engine.game_state[k])
            for k, v in socle.items()
            if k in engine.game_state
            and (engine.game_state[k] != v or type(engine.game_state[k]) is not type(v))
        }
        assert divergentes == {}, f"Socle désaligné de reset() : {divergentes}"

    def test_reset_poses_no_unknown_turn_state_key(self):
        """conformity_exhaustive : reset() ne pose aucun invariant d'état de tour hors du socle.

        Filet de dérive inverse : une 20ᵉ clé ``units_*`` / ``reactive_*`` / ``last_move_*``
        ajoutée au moteur doit entrer dans le socle, sinon les fixtures recommencent à décrire
        un état impossible.
        """
        engine = _make_engine()

        engine.reset()

        # ``units_cache`` / ``units_cache_prev`` sont des vues dérivées des unités
        # (``build_units_cache``, snapshot de mouvement), pas de l'état de tour : une fixture qui
        # en a besoin les construit, elle ne les hérite pas d'un socle.
        DERIVE = {"units_cache", "units_cache_prev"}
        candidates = {
            k for k in engine.game_state
            if k.startswith(("units_", "reactive_", "last_move_", "advance_", "reaction_"))
        }
        hors_socle = sorted(
            k for k in candidates
            if k not in TURN_STATE_KEYS and k not in DERIVE and not k.startswith("_")
        )
        assert hors_socle == [], (
            f"reset() pose des invariants d'état de tour absents du socle : {hors_socle}"
        )


class TestResetLogsScenarioPath:
    """reset() journalise le CHEMIN du scénario tiré pour l'épisode.

    Le step.log ne porte ni terrain, ni icônes, ni zones de déploiement : le replay les relit
    dans la config. Sans ce chemin il les relit pour le scénario par DÉFAUT, alors qu'un
    entraînement tire un scénario différent par épisode (``Scenario:`` vaut alors
    « Random from N scenarios », qui ne désigne aucun fichier).
    """

    @staticmethod
    def _engine_with_logger(tmp_path, scenario_file):
        from ai.step_logger import StepLogger

        with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
             patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
            engine = W40KEngine(
                config=_minimal_config_with_units(), scenario_file=scenario_file
            )
        log_path = tmp_path / "step.log"
        engine.step_logger = StepLogger(
            output_file=str(log_path), enabled=True, buffer_size=10
        )
        return engine, log_path

    def test_reset_logs_scenario_path_relative_to_repo(self, tmp_path):
        """Chemin ABSOLU en entrée → ligne journalisée relative à la racine du dépôt."""
        repo_root = Path(__file__).resolve().parents[3]
        relative = "config/board/44x60x5/scenario/scenario_pvp.json"
        engine, log_path = self._engine_with_logger(tmp_path, str(repo_root / relative))

        engine.reset()

        assert f"Scenario file: {relative}\n" in log_path.read_text(encoding="utf-8")

    def test_reset_rejects_scenario_outside_repo(self, tmp_path):
        """Hors dépôt → erreur explicite, jamais un chemin que le replay ne saura pas résoudre."""
        outside = tmp_path / "ailleurs" / "scenario_x.json"
        engine, _ = self._engine_with_logger(tmp_path, str(outside))

        with pytest.raises(ValueError, match=r"hors du dépôt"):
            engine.reset()

    def test_reset_omits_line_without_scenario_file(self, tmp_path):
        """Moteur nu (aucun scénario) → pas de ligne, pas de chemin inventé."""
        engine, log_path = self._engine_with_logger(tmp_path, None)

        engine.reset()

        assert "Scenario file:" not in log_path.read_text(encoding="utf-8")
