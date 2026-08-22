"""Composition de _close_curriculum_stage (ai/train.py).

Les briques individuelles (evaluate_stage_gate, pool_monotonicity_diagnostic,
promote_stage_model, append_curriculum_log) sont testees dans test_curriculum.py.
Ce fichier verrouille leur ENCHAINEMENT et les deux codes de sortie.

_score_stage_against_pool est mocke : il charge de vrais modeles zip.
copy_tensorboard_run est mocke : I/O tensorboard irrelevant ici.
Tout le reste s'execute reellement.
"""

import json
from types import SimpleNamespace

import ai.train as train_mod
import ai.curriculum as curriculum_mod


# ── Fixtures ────────────────────────────────────────────────────────────────────────────────


def _make_args(etape: str = "P4") -> SimpleNamespace:
    return SimpleNamespace(
        etape=etape,
        training_config="x1",
        rewards_config="x1",
        agent="TestAgent",
    )


def _make_config(models_root: str):
    class _Cfg:
        def get_models_root(self):
            return models_root

    return _Cfg()


def _make_curriculum() -> dict:
    return {
        "order": ["P3", "P4"],
        "gate": {
            "min_score_vs_champion": 0.55,
            "target_score_vs_champion": 0.60,
            "eval_episodes": 10,
        },
        "stages": {
            "P3": {"role": "learner", "pool": [], "init": None, "ratio_start": 0.0, "ratio_end": 0.0, "warmup_episodes": 0},
            "P4": {
                "role": "learner",
                "pool": [{"kind": "champion", "members": ["P3"], "weight": 1.0}],
                "init": "P3",
                "ratio_start": 0.20,
                "ratio_end": 0.50,
                "warmup_episodes": 100,
            },
        },
    }


def _make_run_info(tmp_path) -> dict:
    tb_dir = tmp_path / "tb_run"
    tb_dir.mkdir()
    return {
        "last_bot_eval": {"random": 0.80},
        "episodes_trained": 50000,
        "tensorboard_run_dir": str(tb_dir),
    }


def _make_canonical_model(tmp_path) -> str:
    """Cree un zip minimal sous le nom retourne par le mock de build_agent_model_path."""
    model = tmp_path / "model_Stub.zip"
    model.write_bytes(b"fake-weights")
    return str(model)


# ── Tests ───────────────────────────────────────────────────────────────────────────────────


def _patch_common(monkeypatch, canonical: str, score: float):
    """Mocks communs aux deux tests : score + chemin canonique. TB est mockee par chaque test."""
    monkeypatch.setattr(train_mod, "build_agent_model_path", lambda _root, _key: canonical)
    monkeypatch.setattr(train_mod, "_score_stage_against_pool", lambda *_a, **_kw: {"P3": score})


def test_gate_refus_renvoie_exit_1_et_nescrit_aucun_zip(tmp_path, monkeypatch):
    """Score sous le plancher → exit 1, aucun _P4.zip cree, copy_tensorboard_run non appele, journal ecrit quand meme."""
    canonical = _make_canonical_model(tmp_path)
    args = _make_args()
    config = _make_config(str(tmp_path))
    curriculum = _make_curriculum()
    stage = curriculum["stages"]["P4"]
    run_info = _make_run_info(tmp_path)

    _patch_common(monkeypatch, canonical, score=0.40)

    tb_copied = []
    monkeypatch.setattr(
        train_mod, "copy_tensorboard_run",
        lambda run_dir, etape: tb_copied.append((run_dir, etape)) or "/fake/tb",
    )

    log_path = tmp_path / "curriculum.log"
    monkeypatch.setattr(
        train_mod, "append_curriculum_log",
        lambda entry, path=None: curriculum_mod.append_curriculum_log(entry, str(log_path)),
    )

    exit_code = train_mod._close_curriculum_stage(args, config, curriculum, stage, run_info)

    assert exit_code == 1

    promoted = tmp_path / "model_Stub_P4.zip"
    assert not promoted.exists(), "aucun zip promeu attendu sur refus"

    assert not tb_copied, "copy_tensorboard_run ne doit pas etre appele sur refus"

    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert entries, "le journal doit etre ecrit meme sur refus"
    assert entries[-1]["gate_accepted"] is False
    assert entries[-1]["etape"] == "P4"
    assert entries[-1]["scores_vs_pool"] == {"P3": 0.40}


def test_gate_accepte_renvoie_exit_0_et_ecrit_zip_et_journal(tmp_path, monkeypatch):
    """Score au-dessus de la cible → exit 0, _P4.zip cree, TB copie, journal marque accepted."""
    canonical = _make_canonical_model(tmp_path)
    args = _make_args()
    config = _make_config(str(tmp_path))
    curriculum = _make_curriculum()
    stage = curriculum["stages"]["P4"]
    run_info = _make_run_info(tmp_path)

    _patch_common(monkeypatch, canonical, score=0.65)

    tb_copied = []
    monkeypatch.setattr(
        train_mod,
        "copy_tensorboard_run",
        lambda run_dir, etape: tb_copied.append((run_dir, etape)) or "/fake/tb/P4",
    )

    log_path = tmp_path / "curriculum.log"
    monkeypatch.setattr(
        train_mod, "append_curriculum_log",
        lambda entry, path=None: curriculum_mod.append_curriculum_log(entry, str(log_path)),
    )

    exit_code = train_mod._close_curriculum_stage(args, config, curriculum, stage, run_info)

    assert exit_code == 0

    promoted = tmp_path / "model_Stub_P4.zip"
    assert promoted.exists(), "_P4.zip doit etre cree sur acceptation"
    assert promoted.read_bytes() == b"fake-weights"

    assert tb_copied, "copy_tensorboard_run doit etre appele sur acceptation"
    assert tb_copied[0][1] == "P4"

    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert entries[-1]["gate_accepted"] is True
    assert entries[-1]["scores_vs_pool"] == {"P3": 0.65}
    assert entries[-1]["scores_vs_bots"] == {"random": 0.80}
