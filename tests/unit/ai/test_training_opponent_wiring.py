"""V11 §10.4 — l'agent ne doit JAMAIS s'entrainer contre un adversaire aleatoire.

Avant ce correctif, seul `train_with_scenario_rotation` construisait les bots ponderes ;
le chemin single-scenario tombait sur `SelfPlayWrapper(frozen_model=None)`, dont le frozen
n'etait jamais mis a jour — P2 jouait au hasard du premier au dernier episode, sans qu'aucun
log ne le signale. Ces tests verrouillent les deux cotes de l'invariant : la construction
mutualisee des adversaires, et le refus explicite du repli aleatoire.
"""

import pytest

from ai.train import build_training_opponents
from ai.training_utils import make_training_env


def _silent(_message: str) -> None:
    return None


BOT_TRAINING_CONFIG = {
    "bot_training": {
        "ratios": {"random": 0.5, "greedy": 0.5},
        "randomness": {"greedy": 0.05},
    },
    "agent_seat_mode": "random",
    "agent_seat_seed": 7,
}


def test_build_training_opponents_returns_weighted_bots() -> None:
    opponents = build_training_opponents(dict(BOT_TRAINING_CONFIG), True, 10, _silent)
    assert opponents["use_bots"] is True
    assert opponents["training_bots"]
    assert opponents["agent_seat_mode"] == "random"
    assert opponents["agent_seat_seed"] == 7
    # opponent_mix absent de la config -> desactive, sans erreur
    assert opponents["opponent_mix_config"] is None
    assert opponents["self_play_snapshot_enabled"] is False


def test_build_training_opponents_without_bots_is_inert() -> None:
    opponents = build_training_opponents(dict(BOT_TRAINING_CONFIG), False, 10, _silent)
    assert opponents["use_bots"] is False
    assert opponents["training_bots"] is None


def test_build_training_opponents_rejects_seat_mode_random_without_seed() -> None:
    config = {
        "bot_training": {"ratios": {"greedy": 1.0}},
        "agent_seat_mode": "random",
    }
    with pytest.raises(KeyError, match="agent_seat_seed"):
        build_training_opponents(config, True, 10, _silent)


def test_build_training_opponents_requires_total_episodes_for_opponent_mix() -> None:
    config = dict(BOT_TRAINING_CONFIG)
    config["opponent_mix"] = {
        "enabled": True,
        "self_play_ratio_start": 0.0,
        "self_play_ratio_end": 0.5,
        "warmup_episodes": 1,
        "snapshot_model_path": "ai/models/tmp/snapshot.zip",
        "snapshot_update_freq_episodes": 5,
        "self_play_snapshot_device": "cpu",
        "self_play_deterministic": False,
    }
    with pytest.raises(ValueError, match="total_episodes"):
        build_training_opponents(config, True, None, _silent)


def test_make_training_env_refuses_missing_opponents() -> None:
    # Un worker vectorise sans bots n'a AUCUN adversaire utilisable : erreur explicite,
    # jamais un P2 aleatoire silencieux.
    # L'erreur tombe a la CONSTRUCTION de la factory, avant de forker les workers.
    with pytest.raises(ValueError, match="use_bots=True"):
        make_training_env(
            rank=0,
            scenario_file="unused.json",
            rewards_config_name="default",
            training_config_name="default",
            controlled_agent_key="agent",
            unit_registry=None,
            use_bots=False,
            training_bots=None,
        )
