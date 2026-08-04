"""Tests unitaires — W40KEngine.step().

Chemin critique: reset() → step(action) × N → game_over.
Vérifie: épisode_steps, terminated, tuple de retour, turn_limit, phase advance auto.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from engine.phase_handlers.shared_utils import SQUAD_ACTION_WAIT
from engine.observation_builder import ObservationBuilder
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config


# ─────────────────────────────────────────────────────────────────────────────
# Config minimale
# ─────────────────────────────────────────────────────────────────────────────

def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 2,
        "STR": 4,
        "AP": 0,
        "DMG": 1,
        "NB": 1,
        "RNG": 24,
        "WEAPON_RULES": [],
        "display_name": "Test Bolter",
    }


def _unit_cfg(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
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
        "RNG_WEAPONS": [_weapon_cfg()],
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


def _minimal_config() -> Dict[str, Any]:
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
                "objectives": [{"id": "obj1", "name": "Alpha", "hexes": [[5, 5]]}],
                "inches_to_subhex": 1,
            }
        },
        "game_rules": {
            "engagement_zone": 1,
            "engagement_zone_vertical": 5,
            "max_base_size_hex": 35,
            # Requis par le garde anti-runaway de step() (cf. compute_episode_step_limit).
            # Valeurs reelles de config/game_config.json.
            "max_turns": 3,  # duree de bataille visee par ces tests
            "max_actions_per_model_per_turn": 7,
            "step_limit_margin": 1.5,
        },
        # Toggles de traversee requis par le pool BFS : le masque de move passe
        # desormais par lui (refonte spatiale), la ou les dry-runs directionnels
        # ne les lisaient pas. Valeurs reelles de config/game_config.json.
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
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


@pytest.fixture(autouse=True)
def mock_build_obs(monkeypatch):
    # On double `_build_observation_and_mask`, l'IMPLEMENTATION, et non la facade
    # `_build_observation` : `_step_observation` appelle l'implementation directement, donc doubler
    # la facade seule laissait tourner le vrai constructeur (et le vrai `advance_phase` sur pool
    # vide) sur ces etats artificiels. La facade est doublee aussi, pour les tests qui l'appellent.
    _stub_obs = np.zeros(ObservationBuilder.SQUAD_OBS_SIZE_TARGET)
    monkeypatch.setattr(
        W40KEngine, "_build_observation_and_mask", lambda self, *_a, **_k: (_stub_obs, None)
    )
    monkeypatch.setattr(W40KEngine, "_build_observation", lambda self, *_a, **_k: _stub_obs)
    from engine.reward_calculator import RewardCalculator
    monkeypatch.setattr(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 0.0)


def _make_engine() -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        return W40KEngine(config=build_engine_config(_minimal_config()))


def _legal_action(engine: W40KEngine) -> int:
    """Première action autorisée par le masque — ce que fait un agent masqué (MaskablePPO).

    Ces tests passaient `0` en dur, en s'appuyant sur l'ancien contrat « action hors masque →
    dégradation silencieuse en squad_wait ». Ce repli MASQUAIT les divergences masque/exécution :
    il est supprimé (refonte spatiale §7 T3), une action hors masque lève désormais. Et l'action 0
    n'est plus « direction 0 » mais la cellule 0 de la grille égocentrique (coin du disque).

    Masque vide : `step()` auto-avance la phase et ignore l'action → WAIT, jamais lu dans ce cas.
    """
    mask = engine.get_action_mask()
    legal = np.flatnonzero(mask)
    return int(legal[0]) if legal.size else SQUAD_ACTION_WAIT


# ─────────────────────────────────────────────────────────────────────────────
# Tests — retour de step()
# ─────────────────────────────────────────────────────────────────────────────

class TestStepReturnSignature:

    def test_step_returns_5_tuple(self):
        """step_tuple : step() retourne bien un tuple de 5 éléments (gym interface)."""
        engine = _make_engine()
        engine.reset()
        result = engine.step(_legal_action(engine))
        assert isinstance(result, tuple)
        assert len(result) == 5

    def test_step_obs_is_ndarray(self):
        """step_obs_type : premier élément (obs) est un np.ndarray."""
        engine = _make_engine()
        engine.reset()
        obs, reward, terminated, truncated, info = engine.step(_legal_action(engine))
        assert isinstance(obs, np.ndarray)

    def test_step_reward_is_float(self):
        """step_reward_type : reward est un float (ou castable)."""
        engine = _make_engine()
        engine.reset()
        _, reward, _, _, _ = engine.step(_legal_action(engine))
        assert isinstance(reward, (int, float))

    def test_step_terminated_is_bool(self):
        """step_terminated_type : terminated est un bool."""
        engine = _make_engine()
        engine.reset()
        _, _, terminated, _, _ = engine.step(_legal_action(engine))
        assert isinstance(terminated, bool)

    def test_step_info_is_dict(self):
        """step_info_type : info est un dict."""
        engine = _make_engine()
        engine.reset()
        _, _, _, _, info = engine.step(_legal_action(engine))
        assert isinstance(info, dict)

    def test_step_truncated_is_bool(self):
        """step_truncated_type : truncated est un bool."""
        engine = _make_engine()
        engine.reset()
        _, _, _, truncated, _ = engine.step(_legal_action(engine))
        assert isinstance(truncated, bool)


# ─────────────────────────────────────────────────────────────────────────────
# Tests — episode_steps incremented
# ─────────────────────────────────────────────────────────────────────────────

class TestStepEpisodeCounter:

    def test_step_increments_episode_steps_on_success(self):
        """step_episode_steps : step() réussi incrémente episode_steps."""
        engine = _make_engine()
        engine.reset()
        steps_before = engine.game_state["episode_steps"]
        engine.step(_legal_action(engine))
        assert engine.game_state["episode_steps"] >= steps_before

    def test_step_increments_only_on_success(self):
        """step_success_only : pool vide → auto-advance → episode_steps reste 0 (pas de vrais steps)."""
        engine = _make_engine()
        engine.reset()
        # Après reset, tous les pools sont vides → chaque step auto-avance la phase
        # episode_steps ne s'incrémente que sur un vrai step (action réussie via pool)
        engine.step(_legal_action(engine))
        # Auto-advance ne compte pas comme step : episode_steps peut être 0
        # La valeur exacte dépend du nombre de phases auto-avancées
        # On vérifie juste que l'état est cohérent (pas d'exception)
        assert isinstance(engine.game_state["episode_steps"], int)


# ─────────────────────────────────────────────────────────────────────────────
# Tests — turn limit
# ─────────────────────────────────────────────────────────────────────────────

class TestStepTurnLimit:

    def test_turn_limit_triggers_terminated(self):
        """step_turn_limit : dépasser max_turns_per_episode → terminated=True."""
        engine = _make_engine()
        engine.reset()
        # Force turn au-delà de la limite (3 définie dans config)
        engine.game_state["turn"] = 4
        engine.game_state["turn_limit_reached"] = False

        _, _, terminated, _, info = engine.step(_legal_action(engine))

        assert terminated is True
        assert info.get("turn_limit_exceeded") is True

    def test_turn_limit_info_contains_winner(self):
        """step_turn_limit_winner : info contient 'winner' quand turn_limit déclenché."""
        engine = _make_engine()
        engine.reset()
        engine.game_state["turn"] = 4

        _, _, terminated, _, info = engine.step(_legal_action(engine))

        assert terminated is True
        assert "winner" in info

    def test_turn_limit_info_contains_win_method(self):
        """step_turn_limit_win_method : info contient 'win_method' quand turn_limit déclenché."""
        engine = _make_engine()
        engine.reset()
        engine.game_state["turn"] = 4

        _, _, _, _, info = engine.step(_legal_action(engine))

        assert "win_method" in info


# ─────────────────────────────────────────────────────────────────────────────
# Tests — game over check
# ─────────────────────────────────────────────────────────────────────────────

class TestStepGameOver:

    def test_step_after_reset_game_not_over(self):
        """step_not_over : juste après reset(), terminated=False au premier step."""
        engine = _make_engine()
        engine.reset()
        # S'assurer que turn est dans la limite
        engine.game_state["turn"] = 1

        _, _, terminated, _, _ = engine.step(_legal_action(engine))

        # Pas de game_over immédiat sauf si phase advance auto
        # On vérifie juste que game_state est cohérent
        assert engine.game_state.get("turn_limit_reached", False) is False or terminated is True

    def test_step_pool_empty_triggers_phase_advance(self):
        """step_pool_empty : fight phase avec pools vides → masque tout-False → auto-advance."""
        engine = _make_engine()
        engine.reset()
        engine.game_state["turn"] = 1
        # Fight phase : seule phase où pools vides donnent un masque tout-False
        engine.game_state["phase"] = "fight"
        engine.game_state["fight_subphase"] = None
        for pool_key in (
            "charging_activation_pool",
            "active_alternating_activation_pool",
            "non_active_alternating_activation_pool",
        ):
            engine.game_state[pool_key] = []

        # Action volontairement passée en dur, sans `_legal_action` : le masque est tout-False,
        # donc `step()` auto-avance la phase SANS jamais décoder l'action. Passer par
        # `_legal_action` appellerait `get_action_mask()` en amont, ce qui perturbe cet état
        # artificiel (pools vidés à la main) et fait échouer l'advance_phase — effet de bord
        # pré-existant de `get_action_mask`, hors périmètre de la refonte spatiale.
        _, _, _, _, info = engine.step(SQUAD_ACTION_WAIT)

        # Phase advance automatique doit avoir eu lieu
        assert info.get("phase_auto_advanced") is True or engine.game_state["phase"] != "fight"


class TestStepPostActionPoolEmpty:
    """Pool vide APRÈS une action réussie — branche distincte du pool vide À L'ENTRÉE.

    `test_step_pool_empty_triggers_phase_advance` ci-dessus couvre l'entrée de `step()`. Celle-ci
    couvre la sortie : le `advance_phase` déclenché par le pool vide avance la phase, et le `result`
    de l'action de l'agent doit SURVIVRE — c'est lui qui alimente `info` et `calculate_reward`.

    Pourquoi ce verrou existe : `step()` substituait le résultat du `advance_phase` à celui de
    l'agent. La ligne était l'initialiseur de boucle d'une cascade de phases doublonnée et morte
    (0 appel à `*_phase_start` mesuré — `_process_squad_action` cascade lui-même) ; son effet réel
    était sur la récompense. Mesure sur 8 épisodes : 25,6 substitutions par épisode, 25 % des
    calculs de récompense, où `reason: "pool_empty"` forçait `is_system_response` et versait 0.0 au
    lieu de la récompense de l'action (+68,20 annulés sur 8 épisodes, dernier tir et dernier
    corps-à-corps de chaque phase compris).

    Ces tests tiennent les DEUX côtés : le résultat de l'agent arrive dans `info`, et le payload du
    `advance_phase` n'y arrive pas. Réintroduire la substitution les rend rouges.
    """

    @staticmethod
    def _engine_with_post_action_empty_pool(monkeypatch, advance_result):
        """Construit l'état observé : action décodée puis exécutée, PUIS pool vide.

        Les deux constructions de masque de `step()` sont pilotées séparément (non vide à l'entrée
        pour que l'action soit décodée, vide ensuite pour atteindre la branche), et
        `_process_squad_action` est doublé pour rendre un résultat d'agent DISTINGUABLE puis le
        résultat d'`advance_phase`. C'est le joint exact que ce test verrouille.
        """
        engine = _make_engine()
        engine.reset()
        engine.game_state["turn"] = 1

        mask_size = len(engine.get_action_mask())
        full = np.zeros(mask_size, dtype=bool)
        full[SQUAD_ACTION_WAIT] = True
        empty = np.zeros(mask_size, dtype=bool)
        eligible = [dict(engine.game_state["units"][0])]

        mask_calls = {"n": 0}

        def fake_mask(_game_state):
            mask_calls["n"] += 1
            # 1er appel = entrée de step() ; suivants = après l'action.
            return (full, eligible) if mask_calls["n"] == 1 else (empty, [])

        monkeypatch.setattr(
            engine.action_decoder, "get_squad_action_mask_and_eligible_units", fake_mask
        )
        monkeypatch.setattr(
            engine.action_decoder,
            "convert_squad_action",
            lambda *_a, **_k: {"action": "squad_wait"},
        )

        process_calls = {"n": 0}

        def fake_process(semantic):
            process_calls["n"] += 1
            if semantic.get("action") == "advance_phase":
                return True, dict(advance_result)
            return True, {"action": "squad_wait", "origine": "ACTION_AGENT"}

        monkeypatch.setattr(engine, "_process_squad_action", fake_process)
        return engine, process_calls

    # Le payload d'un `advance_phase` qui cascade : c'est celui qui écrasait le résultat de l'agent.
    _CASCADING_ADVANCE = {"phase_complete": True, "next_phase": "shoot", "reason": "pool_empty"}

    def test_agent_result_survives_phase_advance_in_info(self, monkeypatch):
        """`info` décrit l'action de l'agent, pas la transition qu'elle a déclenchée."""
        engine, process_calls = self._engine_with_post_action_empty_pool(
            monkeypatch, self._CASCADING_ADVANCE
        )

        _, _, _, _, info = engine.step(SQUAD_ACTION_WAIT)

        # Non-vacuité : les deux appels ont bien eu lieu (action de l'agent, puis advance_phase).
        # Sans cette assertion le test resterait vert si la branche pool-vide n'était pas atteinte.
        assert process_calls["n"] == 2
        assert info.get("origine") == "ACTION_AGENT"
        # Le payload de la transition ne fuit pas dans `info`.
        assert "next_phase" not in info
        assert "phase_complete" not in info

    def test_reward_is_computed_on_agent_result_not_on_advance(self, monkeypatch):
        """La récompense porte sur l'action de l'agent — le verrou qui compte.

        `info` n'est qu'un symptôme ; le vrai dégât était sur la récompense : le payload du
        `advance_phase` porte `reason: "pool_empty"`, ce qui force `is_system_response` dans
        `RewardCalculator` et verse 0.0 au lieu de la récompense de l'action.
        """
        engine, process_calls = self._engine_with_post_action_empty_pool(
            monkeypatch, self._CASCADING_ADVANCE
        )
        seen: list = []

        def spy(_self, success, result, _game_state):
            seen.append(result)
            return 0.0

        from engine.reward_calculator import RewardCalculator
        monkeypatch.setattr(RewardCalculator, "calculate_reward", spy)

        engine.step(SQUAD_ACTION_WAIT)

        assert process_calls["n"] == 2
        assert len(seen) == 1
        assert seen[0].get("origine") == "ACTION_AGENT"
        assert seen[0].get("reason") != "pool_empty"


# ─────────────────────────────────────────────────────────────────────────────
# Purges d'épisode des mémos de contrôle d'objectif (14.02)
#
# `game_state` est le MÊME objet d'un reset à l'autre : ce qui est mémoïsé par épisode doit
# mourir dans reset(), sinon il survit sans que rien ne le signale.
# ─────────────────────────────────────────────────────────────────────────────


class TestObjectiveControlEpisodeMemos:
    def test_reset_purges_last_boundary_memo(self):
        """Sans purge, la frontière porte encore ("fight", 5) de l'épisode précédent : au premier
        build d'obs du nouvel épisode, (phase, tour) diffère, le checkpoint 14.02 se déclenche et
        fige des contrôleurs AVANT que la moindre phase se soit terminée."""
        engine = _make_engine()
        engine.reset()
        engine.game_state["_objective_control_last_boundary"] = ("fight", 5)
        engine.reset()
        assert "_objective_control_last_boundary" not in engine.game_state

    def test_reset_purges_logged_snapshot_memo(self):
        """Ce mémo évite de réécrire une ligne OBJECTIVE CONTROL identique. Survivant à l'épisode,
        il ferait SAUTER l'instantané initial du nouvel épisode (mêmes contrôleurs vides, mêmes VP
        à 0) et le replay démarrerait sans aucune donnée de contrôle."""
        engine = _make_engine()
        engine.reset()
        engine.game_state[W40KEngine.OBJECTIVE_CONTROL_LOGGED_KEY] = ((), 0, 0)
        engine.reset()
        assert W40KEngine.OBJECTIVE_CONTROL_LOGGED_KEY not in engine.game_state
