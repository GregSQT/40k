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
    # Obligatoire des que le siege est tire au sort (cf. tests/unit/ai/test_agent_seat_ratio.py,
    # qui verrouille la cle elle-meme) : part des episodes joues en SECOND.
    "agent_seat_p2_ratio": 0.65,
}


def test_build_training_opponents_returns_weighted_bots() -> None:
    opponents = build_training_opponents(dict(BOT_TRAINING_CONFIG), True, 10, _silent)
    assert opponents["use_bots"] is True
    assert opponents["training_bots"]
    assert opponents["agent_seat_mode"] == "random"
    assert opponents["agent_seat_seed"] == 7
    # opponent_mix absent de la config -> desactive, sans erreur
    assert opponents["opponent_mix_config"] is None


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


def _opponent_mix_with_pool(pool: list) -> dict:
    return {
        "enabled": True,
        "self_play_ratio_start": 0.0,
        "self_play_ratio_end": 0.5,
        "warmup_episodes": 1,
        "pool": pool,
        "self_play_snapshot_device": "cpu",
        "self_play_deterministic": False,
    }


def test_build_training_opponents_requires_total_episodes_for_opponent_mix(tmp_path) -> None:
    archive = tmp_path / "model_agent_P0.zip"
    archive.write_bytes(b"")
    config = dict(BOT_TRAINING_CONFIG)
    config["n_envs"] = 2
    config["opponent_mix"] = _opponent_mix_with_pool(
        [{"label": "P0", "path": str(archive), "weight": 0.5}]
    )
    with pytest.raises(ValueError, match="total_episodes"):
        build_training_opponents(config, True, None, _silent)


def test_build_training_opponents_refuses_a_pool_member_that_does_not_exist(tmp_path) -> None:
    """Un adversaire fige absent est un curriculum joue dans le desordre, pas un detail.

    Sans ce refus, l'echec ne tombait qu'au PREMIER episode de self-play d'un worker
    vectorise — donc apres la construction des quarante-huit processus, dans un traceback de
    sous-processus, et seulement pour les rangs affectes a ce membre-la.
    """
    config = dict(BOT_TRAINING_CONFIG)
    config["n_envs"] = 2
    config["opponent_mix"] = _opponent_mix_with_pool(
        [{"label": "P0", "path": str(tmp_path / "jamais_produit.zip"), "weight": 0.5}]
    )
    with pytest.raises(FileNotFoundError, match="P0"):
        build_training_opponents(config, True, 10, _silent)


def test_build_training_opponents_carries_the_weighted_pool(tmp_path) -> None:
    first = tmp_path / "model_agent_P0.zip"
    second = tmp_path / "model_agent_P1.zip"
    for archive in (first, second):
        archive.write_bytes(b"")
    config = dict(BOT_TRAINING_CONFIG)
    config["n_envs"] = 4
    config["opponent_mix"] = _opponent_mix_with_pool([
        {"label": "P1", "path": str(second), "weight": 0.3},
        {"label": "P0", "path": str(first), "weight": 0.2},
    ])
    mix = build_training_opponents(config, True, 10, _silent)["opponent_mix_config"]
    assert mix is not None
    assert [member["label"] for member in mix["pool"]] == ["P1", "P0"]
    assert [member["weight"] for member in mix["pool"]] == [0.3, 0.2]
    assert mix["n_envs"] == 4
    assert mix["total_episodes"] == 10


def test_each_env_rank_gets_exactly_one_frozen_opponent(tmp_path) -> None:
    """Le pool est realise par la repartition des ENVIRONNEMENTS, pas par un tirage par episode.

    Chaque rang recoit UN chemin, qu'il chargera une fois (`self_play_snapshot_frozen`) : c'est
    ce qui garde l'empreinte memoire a un `_frozen_model` par processus. Le verrou porte donc
    sur les deux : un seul chemin par rang, et la distribution des rangs conforme aux poids.
    """
    from collections import Counter

    from ai.training_utils import build_self_play_kwargs

    archives = {}
    for label in ("P0", "P1"):
        path = tmp_path / f"model_agent_{label}.zip"
        path.write_bytes(b"")
        archives[label] = str(path)
    config = dict(BOT_TRAINING_CONFIG)
    config["n_envs"] = 10
    config["opponent_mix"] = _opponent_mix_with_pool([
        {"label": "P1", "path": archives["P1"], "weight": 0.3},
        {"label": "P0", "path": archives["P0"], "weight": 0.2},
    ])
    mix = build_training_opponents(config, True, 100, _silent)["opponent_mix_config"]

    assigned = []
    for rank in range(10):
        kwargs = build_self_play_kwargs(mix, env_rank=rank)
        assert kwargs["self_play_opponent_enabled"] is True
        assert kwargs["self_play_snapshot_frozen"] is True
        assert kwargs["self_play_snapshot_refresh_episodes"] is None
        assigned.append(kwargs["self_play_snapshot_path"])
    assert Counter(assigned) == {archives["P1"]: 6, archives["P0"]: 4}


def test_a_rank_outside_the_env_count_is_refused(tmp_path) -> None:
    from ai.training_utils import build_self_play_kwargs

    archive = tmp_path / "model_agent_P0.zip"
    archive.write_bytes(b"")
    config = dict(BOT_TRAINING_CONFIG)
    config["n_envs"] = 2
    config["opponent_mix"] = _opponent_mix_with_pool(
        [{"label": "P0", "path": str(archive), "weight": 0.5}]
    )
    mix = build_training_opponents(config, True, 100, _silent)["opponent_mix_config"]
    with pytest.raises(ValueError, match="env_rank"):
        build_self_play_kwargs(mix, env_rank=2)


def test_disabled_opponent_mix_leaves_every_self_play_argument_inert() -> None:
    from ai.training_utils import build_self_play_kwargs

    kwargs = build_self_play_kwargs(None)
    assert kwargs["self_play_opponent_enabled"] is False
    assert kwargs["self_play_snapshot_path"] is None
    assert kwargs["self_play_snapshot_frozen"] is False
    assert kwargs["self_play_snapshot_refresh_episodes"] is None


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
