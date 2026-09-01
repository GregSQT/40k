"""Clés de phase combat en attente : purge au reset et pré-capture de l'attaquant.

Deux invariants :
1. `PENDING_FIGHT_WEAPON_KEY` et `PENDING_FIGHT_TARGET_KEY` doivent être effacées à chaque
   `reset()`. Un épisode peut se terminer (turn limit) pendant la fenêtre d'attente d'arme, et
   ces clés survivaient dans game_state, forçant au reset suivant un masque de sélection d'arme
   pour une escouade qui n'avait jamais activé — cause du crash ConfigurationError en training.
2. `_build_manual_allocation` doit pré-capturer la position de l'attaquant AVANT la boucle
   d'intents. Lue après `roll_intent_fn` (qui modifie game_state), elle ouvrait une fenêtre de
   corruption symétrique au bug cible corrigé en de9f8230.
"""
from __future__ import annotations

import json
import random
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest

from engine.action_decoder import PENDING_FIGHT_TARGET_KEY, PENDING_FIGHT_WEAPON_KEY
import engine.phase_handlers.shooting_handlers as _sh
from engine.phase_handlers.fight_handlers import build_manual_fight_allocation
from shared.data_validation import ConfigurationError
from smoke_t5_bare import MELEE_SCENARIO
from tests._state_invariants import turn_state_invariants
from tests.unit.engine._config_helpers import build_game_rules
from tests.unit.engine._state_builders import units_cache_entry as _uc


@pytest.fixture()
def _melee_file():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "melee.json"
        path.write_text(json.dumps(MELEE_SCENARIO))
        yield str(path)


def _engine(scenario_file: str):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    return W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent",
        scenario_file=scenario_file,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Invariant 1 — clés de phase combat en attente purgées au reset
# ─────────────────────────────────────────────────────────────────────────────


class TestStaleKeyPurgedAtReset:
    """Avant le fix : ces clés survivaient au reset, corruptant l'épisode suivant."""

    def test_pending_fight_weapon_key_cleared(self, _melee_file):
        """stale_weapon_key : PENDING_FIGHT_WEAPON_KEY est effacée à chaque reset."""
        eng = _engine(_melee_file)
        eng.reset(seed=1)
        eng.game_state[PENDING_FIGHT_WEAPON_KEY] = {"squad_id": "101", "weapon_index": 0}
        eng.reset(seed=2)
        assert PENDING_FIGHT_WEAPON_KEY not in eng.game_state

    def test_pending_fight_target_key_cleared(self, _melee_file):
        """stale_target_key : PENDING_FIGHT_TARGET_KEY est effacée à chaque reset."""
        eng = _engine(_melee_file)
        eng.reset(seed=1)
        eng.game_state[PENDING_FIGHT_TARGET_KEY] = {"squad_id": "101"}
        eng.reset(seed=2)
        assert PENDING_FIGHT_TARGET_KEY not in eng.game_state

    def test_pending_fight_intents_cleared(self, _melee_file):
        """stale_fight_intents : pending_squad_fight_intents est remis à {} à chaque reset."""
        eng = _engine(_melee_file)
        eng.reset(seed=1)
        eng.game_state["pending_squad_fight_intents"] = {
            "101": [
                {
                    "model_id": "1011",
                    "target_unit_id": "1",
                    "weapon_index": 0,
                    "n_attacks_resolved": 3,
                    "target_squad_size_at_declaration": 5,
                }
            ]
        }
        eng.reset(seed=2)
        assert eng.game_state.get("pending_squad_fight_intents") == {}

    def test_pending_shoot_intents_cleared(self, _melee_file):
        """stale_shoot_intents : pending_squad_shoot_intents est remis à {} à chaque reset."""
        eng = _engine(_melee_file)
        eng.reset(seed=1)
        eng.game_state["pending_squad_shoot_intents"] = {
            "1": [{"model_id": "11", "target_unit_id": "101", "weapon_index": 0,
                   "n_attacks_resolved": 2, "target_squad_size_at_declaration": 10}]
        }
        eng.reset(seed=2)
        assert eng.game_state.get("pending_squad_shoot_intents") == {}

    @pytest.mark.parametrize(
        "key,sentinel",
        [
            (
                "pending_fight_allocation",
                {"attacker_squad_id": "101", "remaining_hits": [{"dmg": 1, "ap": 0, "mw": False}]},
            ),
            (
                "pending_shoot_allocation",
                {"attacker_squad_id": "1", "remaining_hits": [{"dmg": 1, "ap": 0, "mw": False}]},
            ),
            (
                "pending_hazard_allocation",
                {"squad_id": "101", "remaining_mw": 1},
            ),
        ],
    )
    def test_pending_allocation_cleared(self, _melee_file, key, sentinel):
        """stale_alloc : les clés d'allocation manuelle (fight/shoot/hazard) sont effacées au reset.

        Sans ces pop, un épisode tronqué pendant une allocation humaine gelait l'épisode suivant
        dès le premier step (guards lignes 5022/5056/5065 bloquent toute action).
        """
        eng = _engine(_melee_file)
        eng.reset(seed=1)
        eng.game_state[key] = sentinel
        eng.reset(seed=2)
        assert key not in eng.game_state


# ─────────────────────────────────────────────────────────────────────────────
# Invariant 2 — pré-capture position attaquant dans _build_manual_allocation
# ─────────────────────────────────────────────────────────────────────────────


def _fight_gs(n_attacks: int = 2) -> Dict[str, Any]:
    """Attaquant '1' (arme mêlée) vs escouade '2' d'une figurine."""
    weapon: Dict[str, Any] = {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": n_attacks, "RNG": 1,
        "WEAPON_RULES": [], "code": "claw", "display_name": "Claw",
    }
    attacker: Dict[str, Any] = {
        "id": "A1", "squad_id": "1", "player": 0, "T": 4,
        "SHOOT_LEFT": 1, "ATTACK_LEFT": n_attacks, "col": 0, "row": 0,
        "RNG_WEAPONS": [], "CC_WEAPONS": [weapon],
    }
    target: Dict[str, Any] = {
        "id": "T1", "squad_id": "2", "player": 1, "T": 4, "HP_CUR": 2, "HP_MAX": 2,
        "ARMOR_SAVE": 7, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt",
        "points_per_hp": 5.0, "VALUE": 10.0, "col": 1, "row": 0,
        "RNG_WEAPONS": [], "CC_WEAPONS": [],
        "level": 0, "BASE_SHAPE": "round", "BASE_SIZE": 1, "OC": 1,
    }
    return {
        **turn_state_invariants(),
        "player_types": {"0": "human", "1": "ai"},
        "turn": 1, "phase": "fight",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": {"A1": attacker, "T1": target},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "squad_cache": {
            "1": {"model_count_at_start": 1},
            "2": {"model_count_at_start": 1},
        },
        "units_cache": {"1": _uc(0, 0, player=0), "2": _uc(1, 0, player=1)},
        "units": [{"id": "1", "player": 0}, {"id": "2", "player": 1}],
        "unit_by_id": {
            "1": {"id": "1", "UNIT_RULES": [], "player": 0},
            "2": {"id": "2", "UNIT_RULES": [], "player": 1},
        },
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        "_unit_move_version": 0,
        "board_cols": 44, "board_rows": 60, "wall_hexes": set(),
        "config": {"game_rules": build_game_rules(engagement_zone=1)},
        "pending_squad_fight_intents": {
            "1": [
                {
                    "model_id": "A1",
                    "target_unit_id": "2",
                    "weapon_index": 0,
                    "n_attacks_resolved": n_attacks,
                    "target_squad_size_at_declaration": 1,
                }
            ]
        },
    }


class TestAttackerPreCapture:
    """Position attaquant lue avant la boucle (symétrie targets_meta de de9f8230)."""

    def test_attacker_absent_raises_configuration_error(self):
        """precap_missing : attaquant absent de units_cache → ConfigurationError avant la boucle."""
        gs = _fight_gs()
        del gs["units_cache"]["1"]
        with pytest.raises(ConfigurationError):
            build_manual_fight_allocation(gs, "1")

    def test_attacker_absent_empty_intents_raises_configuration_error(self):
        """precap_empty_loop : pré-capture lève ConfigurationError même boucle vide (intents={}).

        Sans pré-capture, la boucle ne tourne pas → aucune erreur. Avec pré-capture (fix),
        require_key(units_cache, attacker_squad_id) est appelé avant la boucle → ConfigurationError.
        Ce cas prouve que la garde est hors boucle, pas à l'intérieur.
        """
        gs = _fight_gs()
        gs["pending_squad_fight_intents"] = {}
        del gs["units_cache"]["1"]
        with pytest.raises(ConfigurationError):
            build_manual_fight_allocation(gs, "1")

    def test_normal_allocation_completes(self, monkeypatch):
        """precap_normal : allocation complète avec attaquant présent → 2 attaques résolues."""
        monkeypatch.setattr(random, "randint", lambda a, b: 4)
        monkeypatch.setattr(_sh, "compute_unit_los", lambda gs, s, t: {"cover": False})
        monkeypatch.setattr(_sh, "_get_unit_by_id", lambda gs, sid: {"id": sid})
        gs = _fight_gs(n_attacks=2)
        result = build_manual_fight_allocation(gs, "1")
        assert result["shoot_result"]["attacks_made"] == 2
