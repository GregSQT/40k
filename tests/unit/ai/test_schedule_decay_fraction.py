"""Verrou de `decay_fraction` : les rampes lr/entropie s'achèvent AVANT la fin d'un run long.

Les deux rampes (`LearningRateScheduleCallback`, `EntropyScheduleCallback`) sont normalisées sur
`total_episodes`. Allonger un run les étire donc mécaniquement : la rampe 0.002 → 0.0002 calibrée
pour 50k épisodes tient le LR au-dessus de 0.001 pendant 83k épisodes sur un run de 150k, contre
28k sur un run de 50k. Ce qui compte pour PPO n'est pas la fraction du run écoulée mais le nombre
d'updates de gradient passés à haut LR / haute entropie — d'où `decay_fraction`, qui achève la
rampe à une fraction du run et tient le plancher ensuite.

Ce fichier vérifie les trois choses qui peuvent réellement casser :
  1. la valeur produite (rampe terminée au bon épisode, plancher tenu ensuite) ;
  2. le fait que les callbacks ÉCRIVENT bien dans le modèle (une rampe juste mais jamais appliquée
     ne règle rien — c'est le motif d'échec récurrent de ce dépôt) ;
  3. le contrat de config : la clé est OBLIGATOIRE dans les six profils, sans défaut.
"""

from __future__ import annotations

import json
import os

import pytest

from ai.training_callbacks import (
    EntropyScheduleCallback,
    LearningRateScheduleCallback,
    schedule_progress,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
AGENT_CONFIG = os.path.join(
    PROJECT_ROOT, "config/agents/ArmageddonAgent/ArmageddonAgent_training_config.json"
)


class _FakeOptimizer:
    def __init__(self) -> None:
        self.param_groups = [{"lr": None}]


class _FakePolicy:
    def __init__(self) -> None:
        self.optimizer = _FakeOptimizer()


class _FakeModel:
    """Surface SB3 réellement touchée par les callbacks (cf. `LearningRateScheduleCallback._apply`)."""

    def __init__(self) -> None:
        self.learning_rate = None
        self.lr_schedule = None
        self.ent_coef = None
        self.policy = _FakePolicy()


def _drive(callback, model, episodes: int, dones_per_step: int = 4) -> None:
    """Pilote le callback comme SB3 : `_on_training_start`, puis des lots de `dones`."""
    callback.model = model
    callback.num_timesteps = 0
    callback._on_training_start()
    delivered = 0
    while delivered < episodes:
        batch = min(dones_per_step, episodes - delivered)
        callback.locals = {"dones": [True] * batch}
        callback.num_timesteps += 1
        assert callback._on_step() is True
        delivered += batch


# --- 1. La valeur produite --------------------------------------------------------------------

@pytest.mark.parametrize(
    "episode, expected",
    [
        (0, 0.0),
        (30_000, 0.5),      # mi-rampe : 30k / (150k * 0.4) = 0.5
        (60_000, 1.0),      # fin de rampe à 40 % du run
        (60_001, 1.0),      # plancher tenu…
        (150_000, 1.0),     # …jusqu'au bout
    ],
)
def test_progress_reaches_one_at_decay_fraction(episode: int, expected: float) -> None:
    assert schedule_progress(episode, 150_000, 0.4) == pytest.approx(expected)


def test_decay_fraction_one_is_the_historical_ramp() -> None:
    """`1.0` doit reproduire EXACTEMENT l'ancien calcul, sinon les 5 profils existants dérivent."""
    for episode in (0, 1, 4_999, 10_000, 20_000):
        assert schedule_progress(episode, 10_000, 1.0) == pytest.approx(
            min(1.0, episode / 10_000)
        )


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.1, 2.0])
def test_invalid_decay_fraction_raises(bad: float) -> None:
    with pytest.raises(ValueError, match="decay_fraction"):
        schedule_progress(0, 10_000, bad)


def test_zero_total_episodes_raises_instead_of_dividing_by_zero() -> None:
    with pytest.raises(ValueError, match="total_episodes"):
        schedule_progress(0, 0, 1.0)


@pytest.mark.parametrize("bad", [0.0, 1.5])
def test_callbacks_reject_invalid_decay_fraction_at_construction(bad: float) -> None:
    """Échouer à la construction, pas au premier épisode : le setup d'un run coûte des minutes."""
    with pytest.raises(ValueError, match="decay_fraction"):
        LearningRateScheduleCallback(0.002, 0.0002, 150_000, decay_fraction=bad)
    with pytest.raises(ValueError, match="decay_fraction"):
        EntropyScheduleCallback(0.1, 0.01, 150_000, decay_fraction=bad)


# --- 2. Les callbacks écrivent bien dans le modèle ---------------------------------------------

def test_lr_callback_hits_the_floor_at_decay_fraction_and_holds() -> None:
    """Sans `decay_fraction`, à 60k/150k le LR vaudrait encore 0.00128 : 6x le plancher."""
    model = _FakeModel()
    cb = LearningRateScheduleCallback(0.002, 0.0002, 150_000, decay_fraction=0.4)
    _drive(cb, model, 60_000)

    assert model.learning_rate == pytest.approx(0.0002)
    # Les trois points d'accès SB3 sont alignés : `lr_schedule` est celui que lit
    # `_update_learning_rate` dans PPO.train(), l'optimizer celui qui applique réellement.
    assert model.lr_schedule(1.0) == pytest.approx(0.0002)
    assert model.lr_schedule(0.0) == pytest.approx(0.0002)
    assert model.policy.optimizer.param_groups[0]["lr"] == pytest.approx(0.0002)

    # Plancher TENU sur les 90k épisodes restants, pas dépassé vers le bas.
    _drive(cb, model, 90_000)
    assert model.learning_rate == pytest.approx(0.0002)


def test_lr_ramp_is_calibrated_like_a_short_run() -> None:
    """À 40 % de 150k, le LR doit suivre la même courbe qu'un run de 60k sans decay_fraction."""
    long_model, short_model = _FakeModel(), _FakeModel()
    long_cb = LearningRateScheduleCallback(0.002, 0.0002, 150_000, decay_fraction=0.4)
    short_cb = LearningRateScheduleCallback(0.002, 0.0002, 60_000, decay_fraction=1.0)
    _drive(long_cb, long_model, 24_000)
    _drive(short_cb, short_model, 24_000)
    assert long_model.learning_rate == pytest.approx(short_model.learning_rate)


def test_entropy_callback_hits_the_floor_at_decay_fraction_and_holds() -> None:
    """Sans `decay_fraction`, à 60k/150k l'entropie vaudrait encore 0.064 : 6x le plancher."""
    model = _FakeModel()
    cb = EntropyScheduleCallback(0.1, 0.01, 150_000, decay_fraction=0.4)
    _drive(cb, model, 60_000)
    assert model.ent_coef == pytest.approx(0.01)
    _drive(cb, model, 90_000)
    assert model.ent_coef == pytest.approx(0.01)


def test_resume_mid_run_starts_at_the_right_value() -> None:
    """`initial_episode_count` (reprise / phase de curriculum) passe par la MÊME formule."""
    model = _FakeModel()
    cb = LearningRateScheduleCallback(
        0.002, 0.0002, 150_000, decay_fraction=0.4, initial_episode_count=30_000
    )
    cb.model = model
    cb._on_training_start()
    assert model.learning_rate == pytest.approx(0.0011)  # mi-rampe


# --- 3. La config survit à sa lecture -----------------------------------------------------------

def _ramped_config() -> dict:
    return {
        "model_params": {
            "ent_coef": {"start": 0.1, "end": 0.01, "decay_fraction": 0.4},
            "learning_rate": {"initial": 0.002, "final": 0.0002, "decay_fraction": 0.4},
        }
    }


def test_freezing_ent_coef_leaves_the_config_intact() -> None:
    """La rampe doit SURVIVRE à la création du modèle, sinon aucun callback n'est créé.

    `create_model` / `create_multi_agent_model` lisaient `training_config["model_params"]` sans
    copie et y écrasaient `ent_coef` par un float. `setup_callbacks` relit la MÊME structure plus
    tard : il y trouvait un scalaire, ne créait pas d'`EntropyScheduleCallback`, et l'entropie
    restait figée à 0.1 pour tout le run — `decay_fraction` sans aucun effet, sans aucun signal.
    """
    import ai.train as train

    config = _ramped_config()
    frozen = train._model_params_with_ent_coef_frozen(config["model_params"], log=lambda _m: None)

    assert frozen["ent_coef"] == pytest.approx(0.1), "PPO n'accepte qu'un scalaire"
    assert isinstance(config["model_params"]["ent_coef"], dict), (
        "la config source a été mutée : setup_callbacks ne verra plus la rampe"
    )
    assert config["model_params"]["ent_coef"]["decay_fraction"] == 0.4

    # La condition exacte que teste `setup_callbacks` sur la config relue.
    assert isinstance(config["model_params"]["ent_coef"], dict)
    assert isinstance(config["model_params"]["learning_rate"], dict)


def test_freezing_a_scalar_ent_coef_is_a_no_op_copy() -> None:
    import ai.train as train

    config = {"model_params": {"ent_coef": 0.05, "learning_rate": 0.0003}}
    frozen = train._model_params_with_ent_coef_frozen(config["model_params"], log=lambda _m: None)
    assert frozen == config["model_params"]
    assert frozen is not config["model_params"], "toujours une copie : pas de fuite par accident"


# --- 4. Le contrat de config ------------------------------------------------------------------

with open(AGENT_CONFIG, encoding="utf-8-sig") as _f:
    PROFILES = {k: v for k, v in json.load(_f).items() if isinstance(v, dict)}


@pytest.mark.parametrize("profile_name", sorted(PROFILES))
@pytest.mark.parametrize("ramp_key", ["learning_rate", "ent_coef"])
def test_every_profile_declares_decay_fraction(profile_name: str, ramp_key: str) -> None:
    """Clé OBLIGATOIRE : `setup_callbacks` la lit par `require_key`, sans défaut.

    Un profil qui l'omettrait ferait lever le run au démarrage — c'est voulu. Le silence
    (retomber sur une rampe étirée) est précisément le défaut que ce paramètre rend visible.
    """
    ramp = PROFILES[profile_name]["model_params"][ramp_key]
    assert isinstance(ramp, dict), f"{profile_name}.{ramp_key} n'est pas une rampe"
    assert "decay_fraction" in ramp, (
        f"profil '{profile_name}' : {ramp_key} sans decay_fraction — le run lèvera au démarrage."
    )
    value = ramp["decay_fraction"]
    assert isinstance(value, (int, float)) and not isinstance(value, bool)
    assert 0.0 < float(value) <= 1.0, f"{profile_name}.{ramp_key}.decay_fraction={value}"


def test_x1_long_is_x1_recalibrated_for_long_runs() -> None:
    """`x1_long` ne diffère de `x1` que par ce qui dépend de la LONGUEUR du run.

    Toute autre divergence est une dérive : les deux profils doivent rester comparables, sinon un
    run long ne mesure plus la même chose qu'un run court.
    """
    x1, x1_long = PROFILES["x1"], PROFILES["x1_long"]
    length_dependent = {
        "type",
        "total_episodes",
        "total_episodes_normal",  # commentaire libre, décrit le budget du profil
        "model_params",           # seul decay_fraction y change, vérifié juste après
        "callback_params",        # seul bot_eval_freq, idem
    }
    for key in set(x1) | set(x1_long):
        if key in length_dependent:
            continue
        assert x1[key] == x1_long[key], f"x1_long dérive de x1 sur '{key}'"

    assert x1_long["total_episodes"] == 150_000
    for ramp_key in ("learning_rate", "ent_coef"):
        long_ramp = dict(x1_long["model_params"][ramp_key])
        ref_ramp = dict(x1["model_params"][ramp_key])
        assert long_ramp.pop("decay_fraction") == 0.4
        assert ref_ramp.pop("decay_fraction") == 1.0
        assert long_ramp == ref_ramp, f"x1_long change {ramp_key} au-delà de decay_fraction"
    # Le reste de model_params (archi, n_steps, target_kl…) doit être identique : un run long
    # sert à mesurer plus longtemps, pas à changer le modèle mesuré.
    assert {k: v for k, v in x1_long["model_params"].items()
            if k not in ("learning_rate", "ent_coef")} == \
           {k: v for k, v in x1["model_params"].items()
            if k not in ("learning_rate", "ent_coef")}

    long_cb, ref_cb = x1_long["callback_params"], x1["callback_params"]
    assert long_cb["bot_eval_freq"] == 5000, (
        "à 2000, un run de 150k déclencherait 75 évaluations bot au lieu de 30."
    )
    # `checkpoint_save_freq` reste ALIGNÉ sur x1, et ce n'est pas un oubli : SB3 sauvegarde tous
    # les `save_freq` APPELS du callback (callbacks.py:300), soit un par pas du VecEnv — jamais
    # des épisodes. Le régler depuis la durée en épisodes d'un run n'a pas de sens ; le levier
    # pour couvrir plus d'historique est `max_checkpoints`, qui est un compte, sans ambiguïté.
    assert long_cb["checkpoint_save_freq"] == ref_cb["checkpoint_save_freq"]
    ignored = {"bot_eval_freq", "bot_eval_freq_normal"}
    assert {k: v for k, v in long_cb.items() if k not in ignored} == \
           {k: v for k, v in ref_cb.items() if k not in ignored}
