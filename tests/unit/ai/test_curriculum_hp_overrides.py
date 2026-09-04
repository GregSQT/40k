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
    curriculum = load_curriculum("ArmageddonAgent_x1")
    # validate_curriculum est appele par load_curriculum — si on arrive ici, il a passe.
    stages = curriculum["stages"]
    assert "training_config_overrides" in stages["P1"]
    assert "training_config_overrides" in stages["P2"]


# ── F2 : validation learning_rate / ent_coef ────────────────────────────────

def test_validate_hp_overrides_learning_rate_zero_rejected():
    stage = {
        "role": "learner",
        "training_config_overrides": {"model_params": {"learning_rate": 0}},
    }
    with pytest.raises(ValueError, match="learning_rate"):
        _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_learning_rate_string_rejected():
    stage = {
        "role": "learner",
        "training_config_overrides": {"model_params": {"learning_rate": "bad"}},
    }
    with pytest.raises(ValueError, match="learning_rate"):
        _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_learning_rate_positive_float_ok():
    stage = {
        "role": "learner",
        "training_config_overrides": {"model_params": {"learning_rate": 0.001}},
    }
    _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_ent_coef_string_rejected():
    stage = {
        "role": "learner",
        "training_config_overrides": {"model_params": {"ent_coef": "bad"}},
    }
    with pytest.raises(ValueError, match="ent_coef"):
        _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_ent_coef_negative_rejected():
    stage = {
        "role": "learner",
        "training_config_overrides": {"model_params": {"ent_coef": -0.01}},
    }
    with pytest.raises(ValueError, match="ent_coef"):
        _validate_stage_hp_overrides("P1", stage, "<test>")


def test_validate_hp_overrides_ent_coef_zero_ok():
    stage = {
        "role": "learner",
        "training_config_overrides": {"model_params": {"ent_coef": 0}},
    }
    _validate_stage_hp_overrides("P1", stage, "<test>")


# ── F3 : _apply_stage_hp_overrides leve sur cfg sans model_params/callback_params ──

def test_apply_hp_overrides_missing_model_params_raises():
    cfg = {"total_episodes": 50000}
    with pytest.raises(ValueError, match="model_params"):
        _apply_stage_hp_overrides(cfg, {"model_params": {"n_epochs": 5}})


def test_apply_hp_overrides_missing_callback_params_raises():
    cfg = {"total_episodes": 50000}
    with pytest.raises(ValueError, match="callback_params"):
        _apply_stage_hp_overrides(cfg, {"callback_params": {"bot_eval_freq": 10000}})


# ── F4 : non-dict override sur exploiteur → TypeError (type avant exploiteur) ──

def test_validate_hp_overrides_non_dict_on_exploiter_raises_type_error():
    stage = {
        "role": "exploiter",
        "training_config_overrides": 42,
    }
    with pytest.raises(TypeError, match="objet JSON"):
        _validate_stage_hp_overrides("E1", stage, "<test>")


# ── F1 : coherence effective quand seul bot_eval_freq est overriddé ──────────

def test_apply_hp_overrides_coherence_only_bot_eval_freq_too_large_raises():
    """bot_eval_freq overriddé seul : total_episodes effectif (base) < freq * 3 → ValueError."""
    cfg = _base_cfg()  # total_episodes = 50000
    # 50000 < 20000 * 3 = 60000
    with pytest.raises(ValueError, match="robust_window_min"):
        _apply_stage_hp_overrides(cfg, {"callback_params": {"bot_eval_freq": 20000}})


def test_apply_hp_overrides_coherence_only_bot_eval_freq_ok():
    """bot_eval_freq overriddé seul : total_episodes effectif >= freq * 3 → accepte."""
    cfg = _base_cfg()  # total_episodes = 50000
    # 50000 >= 15000 * 3 = 45000
    _apply_stage_hp_overrides(cfg, {"callback_params": {"bot_eval_freq": 15000}})
    assert cfg["callback_params"]["bot_eval_freq"] == 15000


# ── agent_seat_p2_ratio : surcharge d'EXPOSITION, pas de modele ─────────────
#
# Seule cle non structurelle de la liste blanche. Elle decrit quelle part des episodes l'agent
# joue en SECOND, le siege ou il est le plus faible, donc elle releve de l'adversite au meme titre
# que le pool et la rampe. Elle ne compromet pas la comparabilite que la liste protege parce que
# `ai/bot_evaluation.py` ne la lit jamais : l'evaluation garde un tirage equitable.
#
# MESURE qui motive sa variation par etape, run P1 du 2026-09-04 : a 0.75, l'ecart de win-rate
# entre les deux sieges est passe de 0.277 a 0.001 sur 80 000 episodes (`00_critical/0_gap_p1-p2`,
# siege premier 0.929 contre siege second 0.927), donc le desequilibre que ce reglage corrigeait a
# disparu et l'etape suivante n'a plus besoin du meme sur-echantillonnage.


def test_agent_seat_p2_ratio_is_an_allowed_stage_override():
    stage = {
        "role": "learner",
        "training_config_overrides": {"agent_seat_p2_ratio": 0.6},
    }
    _validate_stage_hp_overrides("P2", stage, "<test>")
    assert "agent_seat_p2_ratio" in STAGE_HP_OVERRIDES_ALLOWED_TOP_KEYS


@pytest.mark.parametrize("ratio", [0.0, 0.5, 1.0])
def test_agent_seat_p2_ratio_accepts_the_whole_range(ratio):
    """Les deux bornes sont des reglages valides : 0.0 = toujours premier, 1.0 = toujours second."""
    stage = {"role": "learner", "training_config_overrides": {"agent_seat_p2_ratio": ratio}}
    _validate_stage_hp_overrides("P2", stage, "<test>")


@pytest.mark.parametrize("ratio", [-0.1, 1.5])
def test_agent_seat_p2_ratio_outside_the_range_is_refused(ratio):
    """C'est une PART d'episodes : hors [0,1] elle n'a pas de sens.

    Le refus vit dans la validation du curriculum et non au montage des environnements, pour
    qu'une etape fautive soit rejetee au chargement plutot que plusieurs minutes plus tard.
    """
    stage = {"role": "learner", "training_config_overrides": {"agent_seat_p2_ratio": ratio}}
    with pytest.raises(ValueError, match="agent_seat_p2_ratio"):
        _validate_stage_hp_overrides("P2", stage, "<test>")


@pytest.mark.parametrize("ratio", ["0.6", None, True])
def test_agent_seat_p2_ratio_non_numeric_is_refused(ratio):
    """`True` compris : un booleen est un entier en Python, et 1.0 n'est pas ce qu'on declare."""
    stage = {"role": "learner", "training_config_overrides": {"agent_seat_p2_ratio": ratio}}
    with pytest.raises((TypeError, ValueError), match="agent_seat_p2_ratio"):
        _validate_stage_hp_overrides("P2", stage, "<test>")


def test_apply_hp_overrides_agent_seat_p2_ratio():
    """La valeur atteint la config : sans cela, `build_training_opponents` lirait celle du profil."""
    cfg = _base_cfg()
    cfg["agent_seat_p2_ratio"] = 0.75
    _apply_stage_hp_overrides(cfg, {"agent_seat_p2_ratio": 0.6})
    assert cfg["agent_seat_p2_ratio"] == 0.6


def test_apply_hp_overrides_leaves_the_seat_ratio_alone_when_not_declared():
    cfg = _base_cfg()
    cfg["agent_seat_p2_ratio"] = 0.75
    _apply_stage_hp_overrides(cfg, {"total_episodes": 75000})
    assert cfg["agent_seat_p2_ratio"] == 0.75
