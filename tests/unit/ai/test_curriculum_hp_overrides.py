"""Verrous du mecanisme training_config_overrides (curriculum.py + train.py).

Trois invariants :
1. get_stage_hp_overrides retourne {} quand le bloc est absent, le dict sinon.
2. validate_curriculum refuse les cles inconnues et les types invalides.
3. _apply_stage_hp_overrides mute la config correctement (total_episodes, model_params.*, callback_params.*).
"""

import pytest

from ai.curriculum import (
    STAGE_HP_OVERRIDES_ALLOWED_CALLBACK_PARAMS,
    STAGE_HP_OVERRIDES_ALLOWED_MODEL_PARAMS,
    STAGE_HP_OVERRIDES_ALLOWED_TOP_KEYS,
    _validate_stage_hp_overrides,
    get_stage_hp_overrides,
    validate_curriculum,
)
from ai.train import _apply_stage_hp_overrides


# ── get_stage_hp_overrides ──────────────────────────────────────────────────

def test_get_stage_hp_overrides_absent():
    assert get_stage_hp_overrides({"role": "learner"}) == {}


def test_get_stage_hp_overrides_present():
    overrides = {"total_episodes": 75000}
    stage = {"role": "learner", "training_config_overrides": overrides}
    assert get_stage_hp_overrides(stage) == overrides


def test_get_stage_hp_overrides_non_dict_returns_empty():
    # Si la valeur n'est pas un dict, on renvoie {} plutot que lever (la validation leve).
    assert get_stage_hp_overrides({"training_config_overrides": None}) == {}


# ── _validate_stage_hp_overrides ────────────────────────────────────────────

def test_validate_hp_overrides_absent_ok():
    _validate_stage_hp_overrides("P0", {"role": "learner"}, "<test>")


def test_validate_hp_overrides_total_episodes_ok():
    stage = {
        "role": "learner",
        "training_config_overrides": {"total_episodes": 75000},
    }
    _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_model_params_ok():
    stage = {
        "role": "learner",
        "training_config_overrides": {
            "model_params": {"n_epochs": 5, "vf_coef": 0.5},
        },
    }
    _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_unknown_top_key_rejected():
    stage = {
        "role": "learner",
        "training_config_overrides": {"obs_size": 9999},
    }
    with pytest.raises(ValueError, match="cles non autorisees"):
        _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_deployment_mode_schedule_rejected():
    stage = {
        "role": "learner",
        "training_config_overrides": {"deployment_mode_schedule": {}},
    }
    with pytest.raises(ValueError, match="cles non autorisees"):
        _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_unknown_model_param_rejected():
    stage = {
        "role": "learner",
        "training_config_overrides": {
            "model_params": {"clip_range": 0.3},
        },
    }
    with pytest.raises(ValueError, match="cles non autorisees"):
        _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_total_episodes_zero_rejected():
    stage = {
        "role": "learner",
        "training_config_overrides": {"total_episodes": 0},
    }
    with pytest.raises(ValueError, match="total_episodes"):
        _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_n_epochs_float_rejected():
    stage = {
        "role": "learner",
        "training_config_overrides": {"model_params": {"n_epochs": 5.0}},
    }
    with pytest.raises(ValueError, match="n_epochs"):
        _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_vf_coef_negative_rejected():
    stage = {
        "role": "learner",
        "training_config_overrides": {"model_params": {"vf_coef": -0.5}},
    }
    with pytest.raises(ValueError, match="vf_coef"):
        _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_on_exploiter_rejected():
    stage = {
        "role": "exploiter",
        "training_config_overrides": {"total_episodes": 50000},
    }
    with pytest.raises(ValueError, match="exploiteur"):
        _validate_stage_hp_overrides("E1", stage, "<test>")


# ── _apply_stage_hp_overrides ───────────────────────────────────────────────

def _base_cfg():
    return {
        "total_episodes": 50000,
        "model_params": {
            "n_epochs": 3,
            "vf_coef": 1.0,
            "ent_coef": {"start": 0.1, "end": 0.01, "decay_fraction": 0.4},
            "learning_rate": {"initial": 0.002, "final": 0.0005, "decay_fraction": 0.9},
            "gamma": 0.99,
        },
        "callback_params": {
            "bot_eval_freq": 10000,
            "bot_eval_final": 300,
            "save_best_robust": True,
        },
    }


def test_apply_hp_overrides_empty_is_noop():
    cfg = _base_cfg()
    _apply_stage_hp_overrides(cfg, {})
    assert cfg["total_episodes"] == 50000
    assert cfg["model_params"]["n_epochs"] == 3


def test_apply_hp_overrides_total_episodes():
    cfg = _base_cfg()
    _apply_stage_hp_overrides(cfg, {"total_episodes": 75000})
    assert cfg["total_episodes"] == 75000


def test_apply_hp_overrides_n_epochs():
    cfg = _base_cfg()
    _apply_stage_hp_overrides(cfg, {"model_params": {"n_epochs": 5}})
    assert cfg["model_params"]["n_epochs"] == 5
    # les autres cles de model_params sont preservees
    assert cfg["model_params"]["vf_coef"] == 1.0
    assert cfg["model_params"]["gamma"] == 0.99


def test_apply_hp_overrides_vf_coef():
    cfg = _base_cfg()
    _apply_stage_hp_overrides(cfg, {"model_params": {"vf_coef": 0.5}})
    assert cfg["model_params"]["vf_coef"] == 0.5


def test_apply_hp_overrides_ent_coef_replaces_whole_dict():
    cfg = _base_cfg()
    new_ent = {"start": 0.1, "end": 0.01, "decay_fraction": 0.65}
    _apply_stage_hp_overrides(cfg, {"model_params": {"ent_coef": new_ent}})
    assert cfg["model_params"]["ent_coef"] == new_ent


def test_apply_hp_overrides_learning_rate_replaces_whole_dict():
    cfg = _base_cfg()
    new_lr = {"initial": 0.001, "final": 0.0005, "decay_fraction": 0.9}
    _apply_stage_hp_overrides(cfg, {"model_params": {"learning_rate": new_lr}})
    assert cfg["model_params"]["learning_rate"] == new_lr


def test_apply_hp_overrides_full_p1_bundle():
    cfg = _base_cfg()
    overrides = {
        "total_episodes": 75000,
        "model_params": {
            "learning_rate": {"initial": 0.001, "final": 0.0005, "decay_fraction": 0.9},
            "ent_coef": {"start": 0.1, "end": 0.01, "decay_fraction": 0.65},
            "n_epochs": 5,
            "vf_coef": 0.5,
        },
    }
    _apply_stage_hp_overrides(cfg, overrides)
    assert cfg["total_episodes"] == 75000
    assert cfg["model_params"]["n_epochs"] == 5
    assert cfg["model_params"]["vf_coef"] == 0.5
    assert cfg["model_params"]["ent_coef"]["decay_fraction"] == 0.65
    assert cfg["model_params"]["learning_rate"]["initial"] == 0.001
    assert cfg["model_params"]["gamma"] == 0.99  # inchange


# ── callback_params validation ──────────────────────────────────────────────

def test_validate_hp_overrides_callback_params_ok():
    stage = {
        "role": "learner",
        "training_config_overrides": {
            "callback_params": {"bot_eval_freq": 15000, "bot_eval_final": 300},
        },
    }
    _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_callback_params_unknown_key_rejected():
    stage = {
        "role": "learner",
        "training_config_overrides": {
            "callback_params": {"bot_eval_freq": 10000, "checkpoint_save_freq": 5000},
        },
    }
    with pytest.raises(ValueError, match="cles non autorisees"):
        _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_callback_params_non_dict_rejected():
    stage = {
        "role": "learner",
        "training_config_overrides": {"callback_params": 10000},
    }
    with pytest.raises(TypeError, match="callback_params"):
        _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_bot_eval_freq_zero_rejected():
    stage = {
        "role": "learner",
        "training_config_overrides": {"callback_params": {"bot_eval_freq": 0}},
    }
    with pytest.raises(ValueError, match="bot_eval_freq"):
        _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_bot_eval_freq_float_rejected():
    stage = {
        "role": "learner",
        "training_config_overrides": {"callback_params": {"bot_eval_freq": 10000.0}},
    }
    with pytest.raises(ValueError, match="bot_eval_freq"):
        _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_coherence_total_episodes_too_small():
    """total_episodes < bot_eval_freq * 3 (robust_window_min) → rejet."""
    stage = {
        "role": "learner",
        "training_config_overrides": {
            "total_episodes": 25000,
            "callback_params": {"bot_eval_freq": 10000},
        },
    }
    with pytest.raises(ValueError, match="robust_window_min"):
        _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_coherence_ok():
    """total_episodes >= bot_eval_freq * 3 → accepte."""
    stage = {
        "role": "learner",
        "training_config_overrides": {
            "total_episodes": 75000,
            "callback_params": {"bot_eval_freq": 10000},
        },
    }
    _validate_stage_hp_overrides("P1", stage, "<test>")


# ── _apply_stage_hp_overrides : callback_params ─────────────────────────────

def test_apply_hp_overrides_bot_eval_freq():
    cfg = _base_cfg()
    _apply_stage_hp_overrides(cfg, {"callback_params": {"bot_eval_freq": 15000}})
    assert cfg["callback_params"]["bot_eval_freq"] == 15000
    # les autres cles de callback_params sont preservees
    assert cfg["callback_params"]["bot_eval_final"] == 300
    assert cfg["callback_params"]["save_best_robust"] is True


def test_apply_hp_overrides_bot_eval_final():
    cfg = _base_cfg()
    _apply_stage_hp_overrides(cfg, {"callback_params": {"bot_eval_final": 500}})
    assert cfg["callback_params"]["bot_eval_final"] == 500
    assert cfg["callback_params"]["bot_eval_freq"] == 10000


# ── validate_curriculum avec le vrai curriculum.json ────────────────────────

def test_real_curriculum_validates_with_overrides():
    """validate_curriculum accepte le curriculum reel qui contient des overrides sur P1/P2."""
    from ai.curriculum import load_curriculum
    curriculum = load_curriculum("ArmageddonAgent")
    # validate_curriculum est appele par load_curriculum — si on arrive ici, il a passe.
    stages = curriculum["stages"]
    assert "training_config_overrides" in stages["P1"]
    assert "training_config_overrides" in stages["P2"]
    assert stages["P1"]["training_config_overrides"]["total_episodes"] == 75000
    assert stages["P2"]["training_config_overrides"]["total_episodes"] == 100000
