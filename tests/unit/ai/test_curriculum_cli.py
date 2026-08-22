"""`--etape` : ce que l'etape impose a la ligne de commande et a la config chargee.

`--etape` COEXISTE avec `--training-config` : elle ne touche ni aux episodes ni aux
hyperparametres. Ce qu'elle decide, et que ces tests verrouillent :
  - le mode de demarrage (`--new` ou la promotion `--resume-from` du champion source) ;
  - la presence d'`opponent_mix` dans TOUTE lecture ulterieure de la config de l'agent ;
  - le refus explicite des combinaisons qui demanderaient deux regimes a la fois.
"""

import json
import os
from types import SimpleNamespace

import pytest

import ai.train
from ai.train import _prepare_curriculum_stage, _stage_opponent_mix
from tests.unit.ai.test_resume_from_checkpoint import _FakeConfigLoader

CURRICULUM = {
    "order": ["P0", "P1", "E1"],
    "opponent": {"snapshot_device": "cpu", "deterministic": False},
    "gate": {
        "min_score_vs_champion": 0.55,
        "target_score_vs_champion": 0.60,
        "eval_episodes": 300,
    },
    "stages": {
        "P0": {
            "role": "learner", "init": "new", "warmup_episodes": 0,
            "ratio_start": 0.0, "ratio_end": 0.0, "pool": [],
        },
        "P1": {
            "role": "learner", "init": "new", "warmup_episodes": 10,
            "ratio_start": 0.0, "ratio_end": 0.4,
            "pool": [{"kind": "champion", "members": ["P0"], "weight": 0.4}],
        },
        "E1": {
            "role": "exploiter", "init": "from:P1", "warmup_episodes": 0,
            "ratio_start": 1.0, "ratio_end": 1.0,
            "pool": [{"kind": "champion", "members": ["P1"], "weight": 1.0}],
        },
    },
}


@pytest.fixture
def curriculum_agent(tmp_path, monkeypatch):
    """Un agent `TestAgent` avec son curriculum et sa racine de modeles, tous deux en tmp."""
    curriculum_file = tmp_path / "curriculum.json"
    curriculum_file.write_text(json.dumps(CURRICULUM), encoding="utf-8")
    monkeypatch.setattr("ai.curriculum.curriculum_path", lambda agent_key: str(curriculum_file))
    models_root = tmp_path / "models"
    (models_root / "TestAgent").mkdir(parents=True)
    config = _FakeConfigLoader(str(models_root))
    # `_FakeConfigLoader` n'expose que ce dont `--resume-from` a besoin ; l'etape, elle, decore
    # le chargement de la config d'entrainement.
    config.load_agent_training_config = lambda agent_key, phase=None: {"n_envs": 4}
    monkeypatch.setattr("ai.train.get_config_loader", lambda: config)
    return SimpleNamespace(config=config, models_root=models_root)


def _args(etape: str) -> SimpleNamespace:
    return SimpleNamespace(
        agent="TestAgent", etape=etape, new=False, append=False, resume_from=None,
        scenario="bot", training_config="x1", rewards_config="TestAgent",
    )


def _write_stage_model(models_root, stage: str) -> str:
    path = models_root / "TestAgent" / f"model_TestAgent_{stage}.zip"
    path.write_bytes(b"POIDS")
    return str(path)


# ── INIT ───────────────────────────────────────────────────────────────────────────────────

def test_init_new_asks_for_a_fresh_model(curriculum_agent) -> None:
    args = _args("P1")
    _prepare_curriculum_stage(args, curriculum_agent.config)
    assert args.new is True
    assert args.resume_from is None
    assert args.append is False


def test_init_from_reuses_resume_from_on_the_source_stage_model(curriculum_agent) -> None:
    """La promotion d'un champion passe par `--resume-from`, pas par un second mecanisme."""
    source = _write_stage_model(curriculum_agent.models_root, "P1")
    args = _args("E1")
    _prepare_curriculum_stage(args, curriculum_agent.config)
    assert args.resume_from == source
    assert args.append is True
    assert args.new is False


def test_init_from_refuses_when_the_source_stage_was_never_played(curriculum_agent) -> None:
    args = _args("E1")
    with pytest.raises(FileNotFoundError, match="from:P1"):
        _prepare_curriculum_stage(args, curriculum_agent.config)


# ── OPPONENT_MIX INJECTE ───────────────────────────────────────────────────────────────────

def test_the_stage_pool_reaches_every_later_read_of_the_config(curriculum_agent) -> None:
    """La config est rechargee a plusieurs endroits ; la poser sur un exemplaire n'en couvre aucun.

    Sans le decorateur, `build_training_opponents` relisait une config SANS `opponent_mix` et
    l'etape s'entrainait contre les bots seuls, en silence.
    """
    _write_stage_model(curriculum_agent.models_root, "P0")
    config = curriculum_agent.config
    config.load_agent_training_config = lambda agent_key, phase=None: {"n_envs": 4}

    _prepare_curriculum_stage(_args("P1"), config)

    mix = config.load_agent_training_config("TestAgent", "x1")["opponent_mix"]
    assert mix["enabled"] is True
    assert mix["self_play_ratio_start"] == 0.0
    assert mix["self_play_ratio_end"] == 0.4
    assert mix["warmup_episodes"] == 10
    assert mix["pool"] == [{
        "label": "P0",
        "path": str(curriculum_agent.models_root / "TestAgent" / "model_TestAgent_P0.zip"),
        "weight": 0.4,
    }]
    # Un AUTRE agent ne doit pas heriter du pool de celui-ci.
    assert "opponent_mix" not in config.load_agent_training_config("OtherAgent", "x1")


def test_a_stage_without_pool_leaves_the_config_untouched(curriculum_agent) -> None:
    """P0 s'entraine contre les bots seuls : `opponent_mix` doit etre ABSENT, pas desarme."""
    config = curriculum_agent.config
    config.load_agent_training_config = lambda agent_key, phase=None: {"n_envs": 4}

    _prepare_curriculum_stage(_args("P0"), config)

    assert "opponent_mix" not in config.load_agent_training_config("TestAgent", "x1")


def test_the_stage_disarms_the_blind_benchmark_floor_gate(curriculum_agent) -> None:
    """`benchmark_floor` compare le pire score aux bots de REFERENCE, satures a 1.00.

    Le plancher de 0.9 de `x1_long` est donc franchi par n'importe quel modele : il ne separe
    rien. La selection d'une etape appartient au plancher dur contre le champion.
    """
    config = curriculum_agent.config
    config.load_agent_training_config = lambda agent_key, phase=None: {
        "n_envs": 4,
        "callback_params": {"model_gating_enabled": True, "model_gating_min_benchmark_floor": 0.9},
    }

    _prepare_curriculum_stage(_args("P0"), config)

    cfg = config.load_agent_training_config("TestAgent", "x1_long")
    assert cfg["callback_params"]["model_gating_min_benchmark_floor"] == 0.0
    # Un autre agent garde le sien.
    other = config.load_agent_training_config("OtherAgent", "x1_long")
    assert other["callback_params"]["model_gating_min_benchmark_floor"] == 0.9


def test_stage_opponent_mix_is_none_without_a_pool() -> None:
    assert _stage_opponent_mix(CURRICULUM, CURRICULUM["stages"]["P0"], "/m/model_A.zip") is None


# ── REFUS DE LA LIGNE DE COMMANDE ──────────────────────────────────────────────────────────

def _run_main(monkeypatch, argv: list) -> None:
    monkeypatch.setattr("sys.argv", ["train.py", *argv])
    ai.train.main()


BASE_ARGV = ["--agent", "TestAgent", "--training-config", "x1", "--scenario", "bot", "--etape", "P0"]


@pytest.mark.parametrize("flag", ["--new", "--append"])
def test_etape_refuses_the_flags_it_decides_itself(monkeypatch, flag: str) -> None:
    with pytest.raises(ValueError, match=f"--etape et {flag}"):
        _run_main(monkeypatch, [*BASE_ARGV, flag])


def test_etape_refuses_resume_from(monkeypatch, tmp_path) -> None:
    ckpt = tmp_path / "ppo_checkpoint_100_steps.zip"
    ckpt.write_bytes(b"")
    with pytest.raises(ValueError, match=r"--etape et --resume-from"):
        _run_main(monkeypatch, [*BASE_ARGV, "--resume-from", str(ckpt)])


def test_etape_refuses_the_modes_that_do_not_train(monkeypatch) -> None:
    with pytest.raises(ValueError, match="ENTRAINEMENT complet"):
        _run_main(monkeypatch, [*BASE_ARGV, "--test-only"])


def test_etape_refuses_a_scenario_other_than_bot(monkeypatch) -> None:
    argv = [a if a != "bot" else "all" for a in BASE_ARGV]
    with pytest.raises(ValueError, match="--scenario bot"):
        _run_main(monkeypatch, argv)


def test_an_unknown_stage_is_refused_before_anything_is_built(
    monkeypatch, curriculum_agent
) -> None:
    """Le refus doit tomber a la lecture des arguments, pas apres avoir ecarte un modele."""
    canonical = curriculum_agent.models_root / "TestAgent" / "model_TestAgent.zip"
    canonical.write_bytes(b"MODELE_PRECEDENT")
    argv = [a if a != "P0" else "P42" for a in BASE_ARGV]
    with pytest.raises(ValueError, match="Etape inconnue"):
        _run_main(monkeypatch, argv)
    assert os.path.exists(canonical), "un refus d'etape ne doit rien avoir ecarte"
    assert open(canonical, "rb").read() == b"MODELE_PRECEDENT"
