"""V11 §10.4 — l'agent ne doit JAMAIS s'entrainer contre un adversaire aleatoire.

Avant ce correctif, seul `train_with_scenario_rotation` construisait les bots ponderes ;
le chemin single-scenario tombait sur `SelfPlayWrapper(frozen_model=None)`, dont le frozen
n'etait jamais mis a jour — P2 jouait au hasard du premier au dernier episode, sans qu'aucun
log ne le signale. Ces tests verrouillent les deux cotes de l'invariant : la construction
mutualisee des adversaires, et le refus explicite du repli aleatoire.
"""

import pytest

from ai.train import build_training_opponents, resolve_run_budget
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
        "bot_training": {"ratios": {"greedy": 1.0}, "randomness": {"greedy": 0.05}},
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
            n_envs=4,
        )


def test_make_training_env_requires_n_envs() -> None:
    # `n_envs` est le denominateur des rampes par-episode (V11 §0.57) : l'omettre laisserait le
    # moteur retomber sur la valeur DECLAREE du profil, qui peut ne pas etre celle du run.
    with pytest.raises(ValueError, match="n_envs"):
        make_training_env(
            rank=0,
            scenario_file="unused.json",
            rewards_config_name="default",
            training_config_name="default",
            controlled_agent_key="agent",
            unit_registry=None,
            use_bots=True,
            training_bots=["bot"],
        )


# --- Budget du RUN : les deux termes du denominateur des rampes par-episode (V11 §0.57) --------


def test_resolve_run_budget_takes_the_runtime_n_envs() -> None:
    """Le profil declare une INTENTION (48) ; `--step` n'ouvre qu'un environnement."""
    resolved = resolve_run_budget({"n_envs": 48, "total_episodes": 200000}, 1)
    assert resolved["n_envs"] == 1
    assert resolved["total_episodes"] == 200000, "sans longueur de run propre, le profil fait foi"


def test_resolve_run_budget_takes_the_cli_total_episodes() -> None:
    """`--total-episodes 5000` : sans cette reecriture, la rampe se terminerait a 2,5 %."""
    resolved = resolve_run_budget({"n_envs": 48, "total_episodes": 200000}, 48, 5000)
    assert resolved["total_episodes"] == 5000


def test_resolve_run_budget_prefers_the_phase_length_over_the_chunk() -> None:
    """Curriculum : le run est decoupe en chunks, la rampe se rapporte a la PHASE entiere."""
    resolved = resolve_run_budget({"n_envs": 48, "total_episodes": 200000}, 48, 500, 40000)
    assert resolved["total_episodes"] == 40000


def test_resolve_run_budget_does_not_mutate_the_profile() -> None:
    """Le dict du profil est relu ailleurs : la resolution en rend une COPIE."""
    profile = {"n_envs": 48, "total_episodes": 200000}
    resolve_run_budget(profile, 1, 5000)
    assert profile == {"n_envs": 48, "total_episodes": 200000}


@pytest.mark.parametrize("n_envs,total", [(0, 100), (-1, 100), (True, 100), (4, 0), (4, -5)])
def test_resolve_run_budget_refuses_absurd_budgets(n_envs, total) -> None:
    with pytest.raises(Exception):
        resolve_run_budget({"n_envs": 48, "total_episodes": 200000}, n_envs, total)


def test_x1_selfplay_profile_is_consumable_end_to_end() -> None:
    """Le profil de PHASE 2 du fichier réel passe tout le contrat `opponent_mix`.

    Ces clés sont lues par `require_key`, sans valeur par défaut : une faute de frappe dans le
    JSON ne se verrait qu'au lancement d'un run de plusieurs heures. Le test lit le VRAI fichier.
    """
    import json
    import os

    from ai.training_utils import build_self_play_kwargs

    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    path = os.path.join(
        project_root, "config/agents/ArmageddonAgent/ArmageddonAgent_training_config.json"
    )
    with open(path, encoding="utf-8-sig") as handle:
        profile = json.load(handle)["x1_selfplay"]

    opponents = build_training_opponents(profile, True, profile["total_episodes"], _silent)
    mix = opponents["opponent_mix_config"]
    assert mix is not None and mix["enabled"] is True
    assert opponents["self_play_snapshot_enabled"] is True

    kwargs = build_self_play_kwargs(mix)
    assert kwargs["self_play_opponent_enabled"] is True
    # Budgets GLOBAUX dans la config ; c'est le wrapper qui les ramène au budget d'un env.
    assert kwargs["self_play_total_episodes"] == profile["total_episodes"]
    assert kwargs["self_play_n_envs"] == profile["n_envs"]

    # La rampe MONTE et ne sature pas : un agent qui ne joue plus que contre lui-même dérive
    # vers un équilibre local qu'aucun bot ne récompense, et l'évaluation note vs bots.
    assert 0.0 <= mix["self_play_ratio_start"] < mix["self_play_ratio_end"] <= 0.8
    assert 0 < mix["warmup_episodes"] < profile["total_episodes"]
