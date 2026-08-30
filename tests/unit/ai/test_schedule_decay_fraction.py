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
  3. le contrat de config : la clé est OBLIGATOIRE dans TOUS les profils, sans défaut.
"""

from __future__ import annotations

import json
import os
from typing import Callable, Container, Optional, cast

import pytest
from stable_baselines3.common.base_class import BaseAlgorithm
from stable_baselines3.common.callbacks import BaseCallback

from ai.training_callbacks import (
    EntropyScheduleCallback,
    LearningRateScheduleCallback,
    schedule_progress,
)
from config_loader import get_config_loader

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


def _unwritten_schedule(_progress_remaining: float) -> float:
    """`lr_schedule` avant tout passage du callback : l'appeler doit ÉCHOUER, pas rendre None."""
    raise AssertionError("lr_schedule n'a jamais ete remplace par le callback")


class _FakeModel:
    """Surface SB3 réellement touchée par les callbacks (cf. `LearningRateScheduleCallback._apply`)."""

    def __init__(self) -> None:
        self.learning_rate: Optional[float] = None
        self.lr_schedule: Callable[[float], float] = _unwritten_schedule
        self.ent_coef: Optional[float] = None
        self.policy = _FakePolicy()


def _attach(callback: BaseCallback, model: _FakeModel) -> None:
    """SB3 injecte le vrai modèle ; le double n'en implémente que la surface touchée."""
    callback.model = cast(BaseAlgorithm, model)


def _drive(callback: BaseCallback, model: _FakeModel, episodes: int,
           dones_per_step: int = 4) -> None:
    """Pilote le callback comme SB3 : `_on_training_start`, puis des lots de `dones`."""
    _attach(callback, model)
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
    _attach(cb, model)
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
PROFILE_NAMES = sorted(PROFILES)

# `callback_params` est HÉRITABLE : une clé absente ou nulle retombe sur `_training_common.json`
# (`_resolve_callback_value`, train.py:3444-3459). Lire le profil brut mesurerait donc autre chose
# que ce que le run appliquera — et `_training_common.json` définit justement `save_best_robust`,
# `bot_eval_freq` et `robust_window`. On relit la MÊME source que le runtime, pas une copie.
TRAINING_COMMON = get_config_loader().load_training_common_config()


def _resolved_cb(callback_params: dict, key: str):
    """Miroir de `_resolve_callback_value` (train.py:3444-3459), même ordre, mêmes erreurs."""
    value = callback_params[key] if key in callback_params else None
    if value is not None:
        return value
    if key not in TRAINING_COMMON:
        raise KeyError(
            f"callback_params.{key} est absent/null et _training_common.json ne définit pas '{key}'"
        )
    shared = TRAINING_COMMON[key]
    if shared is None:
        raise ValueError(f"_training_common.json définit '{key}' à null")
    return shared


# Quels profils PROMETTENT un best model. Table explicite et exhaustive : `save_best_robust` est
# écarté des comparaisons en bloc (il dépend de la longueur du run) et le test paramétré plus bas
# SKIP ceux qui ne promettent rien — sans cette table, le passer à false n'importe où resterait
# vert partout, et un run de mesure ne produirait plus aucun modèle sélectionné.
# false = le profil ne SÉLECTIONNE rien, sa sortie est son modèle FINAL. Deux causes distinctes :
# le run est trop court pour remplir la fenêtre une seule fois (`x1_debug`),
# ou il la remplit exactement une fois — une seule position de fenêtre, donc le « meilleur »
# modèle est mécaniquement le dernier point évalué (`x1` depuis le 2026-08-11 : 5 points pour une
# fenêtre de 5). Dans les deux cas la promesse était vide ; c'est le sens du `false`.
PROMISES_BEST_MODEL = {
    "x1": False, "x1_long": True, "x1_debug": False,
    "x5_new": False, "x5_long": True, "x5_debug": False,
}


def _comparable(block: dict, ignored: Container[str] = ()) -> dict:
    """Le bloc privé de `ignored` et de ses clés-commentaires.

    Une clé-commentaire de ce fichier, c'est un suffixe `_normal` ET une valeur TEXTE : de la
    prose documentant le réglage voisin. Les écarter par cette règle, plutôt qu'en les
    énumérant, évite qu'ajouter un commentaire au JSON fasse rougir une comparaison qui n'a
    rien à voir.

    Le suffixe seul ne suffit PAS : dans `config/agents/_training_common.json` il porte des
    valeurs réelles (`bot_eval_freq_normal: 1000`, `save_best_robust_normal: true`), et un jour
    où une telle clé apparaîtrait ici, l'écarter au nom de la convention laisserait passer en
    silence exactement la dérive x1/x1_long que ce test verrouille.
    """
    return {
        k: v for k, v in block.items()
        if k not in ignored and not (k.endswith("_normal") and isinstance(v, str))
    }


@pytest.mark.parametrize("profile_name", PROFILE_NAMES)
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


#: Longueur ATTENDUE de chaque profil `_long`. Épinglée et non lue depuis le JSON :
#: sans elle, un `_long` ramené par mégarde à la longueur de sa référence resterait vert alors
#: qu'il ne mesurerait plus rien de long. x1_long et x5_long : 100 000 épisodes chacun (10 points
#: de mesure à `bot_eval_freq` 10000, `robust_window` 3 identique sur les deux profils depuis
#: le 2026-08-30 ; cf. `robust_window_normal` dans la config).
LONG_PROFILE_EPISODES = {"x1_long": 100_000, "x5_long": 100_000}

#: `bot_eval_final` ATTENDU de chaque profil de RÉFÉRENCE (le court des deux), par couple.
#: ÉPINGLÉ pour la même raison que la table ci-dessus, et plus commun aux deux couples depuis le
#: 2026-08-11 : `x1` est descendu de 100 à 10. C'est la BASE DE DÉVELOPPEMENT (ROADMAP §1 pt 6 /
#: V11 §0.70) — son éval finale est du MONITORING, pas une mesure : à 10 épisodes par bot,
#: l'erreur-type de l'écart entre deux win-rates `combined` vaut ≈ 0,707/√(6 × 10) = 9,1 points,
#: donc aucun écart réaliste n'en sort. Le chiffre publié vient de `x1_long` (300 depuis le
#: 2026-08-16, voir LONG_PROFILE_BOT_EVAL_FINAL), et de rien d'autre.
REFERENCE_BOT_EVAL_FINAL = {"x1": 10, "x5_new": 100}

#: `bot_eval_final` ATTENDU de chaque profil `_long`. Épinglé (pas lu depuis le JSON) pour la
#: même raison que ci-dessus. x1_long : 300 épisodes PAR BOT, chronométré le 2026-08-16
#: (2,76 s/ép. à 12 workers sur 8 cœurs, 3 répétitions, dispersion < 2 %). L'erreur-type d'un
#: win-rate autour de 0,5 vaut 0,5/√n : 2,9 points à 300. Le détail est dans
#: `bot_eval_final_normal` du JSON, seule source.
#: ⚠️ Le « 1 h 23 » que portait ce commentaire est corrigé le 2026-08-27 : il valait 6 × 300,
#: alors que 10 bots étaient alors joués (cf. `EXPECTED_BOT_EVAL_COUNT`), soit 3000 épisodes et
#: ~2 h 18. Depuis la suppression des 4 bots à poids nul, 6 × 300 = 1800 épisodes et le ~1 h 23
#: redevient exact — mais il DÉPEND du nombre de bots, jamais du seul `bot_eval_final`.
LONG_PROFILE_BOT_EVAL_FINAL = {"x1_long": 300, "x5_long": 300}

#: `bot_eval_intermediate` ATTENDU de chaque profil `_long`. x1_long et x5_long : 30 (aligné
#: depuis le 2026-08-30, avec 4 workers intermédiaires sur les deux profils).
LONG_PROFILE_BOT_EVAL_INTERMEDIATE = {"x1_long": 30, "x5_long": 30}

#: Fenêtre du score robuste de chaque profil `_long`. Elle DÉPEND de la longueur du run : la
#: fenêtre glisse sur les points de mesure, donc `total // freq - window + 1` est le nombre de
#: positions. À une seule position le « meilleur modèle » est mécaniquement le dernier. x1_long
#: et x5_long : 100 000 épisodes → 10 points, fenêtre de 3 (8 positions). Aligné 2026-08-30.
LONG_PROFILE_ROBUST_WINDOW = {"x1_long": 3, "x5_long": 3}

#: `eval_episodes` ATTENDU des profils `_long` et de leurs références. Épinglé pour la même raison
#: que les tables ci-dessus : un glissement silencieux du nombre d'épisodes holdout changerait la
#: puissance statistique du signal sans rien casser dans la comparaison en bloc.
#: x1_long=100 vs x1=50 : signal plus fort sur le profil de mesure ;
#: x5_long=100 = x1_long=100 : aligné sur x1_long depuis le 2026-08-30.
LONG_PROFILE_EVAL_EPISODES: dict[str, int] = {"x1_long": 100, "x5_long": 100}
REFERENCE_EVAL_EPISODES: dict[str, int] = {"x1": 50, "x5_new": 10}

#: `model_gating_enabled` ATTENDU de chaque profil `_long`. Lié à `save_best_robust` : un profil
#: qui ne sélectionne rien (save_best_robust=false) n'a aucun modèle candidat à filtrer, donc le
#: gate n'y a pas de sens. x1_long et x5_long activent le gate (save_best_robust=true sur les
#: deux) depuis le 2026-08-30 où x5_long a été aligné sur x1_long.
LONG_PROFILE_MODEL_GATING_ENABLED: dict[str, bool] = {"x1_long": True, "x5_long": True}

#: Nombre de bots RÉELLEMENT joués à chaque évaluation, par profil. C'est `len(bot_eval_weights)`
#: et RIEN D'AUTRE : `evaluate_against_bots` construit ses adversaires par
#: `active_bot_names = tuple(eval_weights.keys())` (`ai/bot_evaluation.py`), donc un bot à poids
#: `0.0` est joué comme les autres — le poids ne pèse que sur l'agrégat `combined`.
#:
#: ÉPINGLÉ parce que l'absence de ce verrou a laissé vivre un écart de 67 % sur le budget
#: d'évaluation. Jusqu'au 2026-08-26 (commit `8bb4e42e`) le dictionnaire portait 10 clés, dont 4 à
#: poids nul, pendant que les notes `*_normal` du JSON chiffraient le coût sur 6 bots : l'éval
#: finale de `x1_long` était annoncée à 6 × 300 = 1800 épisodes et en jouait 10 × 300 = 3000,
#: soit ~2 h 18 au lieu des ~1 h 23 annoncés. Rien n'était rouge, parce que rien ne confrontait
#: les deux. Les 4 bots à poids nul ont été supprimés (`tactical` et les trois `reference_*`,
#: saturés à 1.00 — cf. `evaluate_stage_gate` dans `ai/curriculum.py`).
#:
#: TOUCHER À CETTE TABLE OBLIGE À METTRE À JOUR, DANS LA MÊME LIVRAISON, les décompositions
#: écrites dans les notes `bot_eval_n_workers_normal`, `bot_eval_freq_normal` et
#: `bot_eval_final_normal` du JSON : elles multiplient toutes ce nombre par un budget par bot.
EXPECTED_BOT_EVAL_COUNT: dict[str, int] = {
    "x1": 6,
    "x1_long": 6,
    "x1_debug": 6,
    "x5_new": 6,
    "x5_long": 6,
    "x5_debug": 6,
}


@pytest.mark.parametrize("profile_name", PROFILE_NAMES)
def test_bot_eval_count_table_is_exhaustive(profile_name: str) -> None:
    """Tout profil JSON doit figurer dans EXPECTED_BOT_EVAL_COUNT.

    La table épingle le budget d'évaluation ; un profil absent n'est jamais vérifié par
    `test_bot_eval_bot_count_is_pinned`, qui itère sur la table, pas sur les profils.
    """
    assert profile_name in EXPECTED_BOT_EVAL_COUNT, (
        f"profil '{profile_name}' absent de EXPECTED_BOT_EVAL_COUNT : l'inscrire avec le "
        f"nombre de bots attendus dans bot_eval_weights ET mettre à jour les décompositions "
        f"chiffrées des notes *_normal du JSON."
    )


@pytest.mark.parametrize("profile_name", sorted(EXPECTED_BOT_EVAL_COUNT))
def test_bot_eval_bot_count_is_pinned(profile_name: str) -> None:
    """Le nombre de bots joués par évaluation est épinglé : il FIXE le budget d'évaluation.

    Verrou du budget, pas du panel : ajouter ou retirer une clé de `bot_eval_weights` multiplie
    ou divise le coût de CHAQUE évaluation — intermédiaire comme finale, puisque les deux passent
    par `evaluate_against_bots` et n'y diffèrent que par `n_episodes`. Un ajout silencieux
    rallongerait un run de plusieurs heures sans qu'aucune autre assertion ne bouge.
    """
    cb = PROFILES[profile_name]["callback_params"]
    weights = cb["bot_eval_weights"]
    assert len(weights) == EXPECTED_BOT_EVAL_COUNT[profile_name], (
        f"{profile_name} : {len(weights)} bots dans bot_eval_weights "
        f"({sorted(weights)}), table épinglée à {EXPECTED_BOT_EVAL_COUNT[profile_name]}. "
        f"Ce nombre MULTIPLIE le budget d'évaluation : mettre à jour la table ET les "
        f"décompositions chiffrées des notes *_normal du JSON."
    )
    # Miroir du contrôle runtime (bot_evaluation.py:1566) : randomness doit couvrir tous les bots
    # pondérés ; des clés supplémentaires dans randomness sont tolérées par le runtime.
    missing = [name for name in weights if name not in cb["bot_eval_randomness"]]
    assert not missing, (
        f"{profile_name} : bot_eval_randomness manque des entrées pour les bots pondérés "
        f"— manquants={missing}, weights={sorted(weights)}, "
        f"randomness={sorted(cb['bot_eval_randomness'])}."
    )


@pytest.mark.parametrize(
    ("ref_name", "long_name"), [("x1", "x1_long"), ("x5_new", "x5_long")]
)
def test_long_profile_is_its_reference_recalibrated(ref_name: str, long_name: str) -> None:
    """Un profil `_long` ne diffère de sa référence que par ce qui dépend de la LONGUEUR du run.

    Toute autre divergence est une dérive : les deux profils doivent rester comparables, sinon un
    run long ne mesure plus la même chose qu'un run court.

    Couple actif : `x1_long` sur `x1` (2026-08-02). Le même verrou empêche toute dérive future
    si un profil `_long` est ajouté.
    """
    ref, long_ = PROFILES[ref_name], PROFILES[long_name]
    length_dependent = {
        "type",
        "total_episodes",
        "model_params",   # seuls les decay_fraction y changent, vérifiés juste après
        "callback_params",  # seuls bot_eval_freq et bot_eval_final, idem
        "eval_episodes",  # holdout uniquement (--test-only) ; x1_long=100 vs x1=50 pour signal plus fort
    }
    assert _comparable(long_, length_dependent) == _comparable(ref, length_dependent)

    assert long_["total_episodes"] == LONG_PROFILE_EPISODES[long_name]
    assert long_["eval_episodes"] == LONG_PROFILE_EVAL_EPISODES[long_name]
    assert ref["eval_episodes"] == REFERENCE_EVAL_EPISODES[ref_name]
    # Les deux rampes ont des `decay_fraction` DISTINCTES, et c'est délibéré : elles ne servent
    # pas la même chose. Ce sont des FRACTIONS du run, donc les deux longueurs les partagent :
    # l'entropie s'arrête aux 40 % (20k sur x1_long) parce qu'on veut que la politique cesse
    # d'explorer et exploite ; le learning rate descend jusqu'aux 90 % (45k) parce que le mettre
    # au plancher plus tôt fige la politique alors qu'il reste du budget.
    #
    # 0.9 et non 0.7 depuis le 2026-08-12, MESURÉ sur le run x1_long de 50 000 épisodes
    # (run_20260812-033643) : le plancher atteint à 35 000 épisodes laissait le dernier quart du
    # run à une fraction de clipping de 0.032, trois fois SOUS le `clip_fraction_min` que le
    # profil déclare (0.1), et à un approx_kl de 0.007 pour un `kl_min` de 0.005 — la politique ne
    # bougeait plus. Côté résultat : +8.7 points de win-rate entre 10k et 20k épisodes, +0.9 point
    # entre 40k et 50k. Le plancher lui-même est passé de 2e-4 à 5e-4 dans le même mouvement (cf.
    # la justification du bloc `learning_rate` dans le JSON), sur les DEUX membres de chaque paire
    # — l'assertion de comparabilité ci-dessous est ce qui l'exige.
    expected_decay = {"learning_rate": 0.9, "ent_coef": 0.4}
    for ramp_key, expected in expected_decay.items():
        long_ramp = long_["model_params"][ramp_key]
        ref_ramp = ref["model_params"][ramp_key]
        assert long_ramp["decay_fraction"] == expected, ramp_key
        assert ref_ramp["decay_fraction"] == 1.0
        assert _comparable(long_ramp, {"decay_fraction"}) == _comparable(ref_ramp, {"decay_fraction"}), \
            f"{long_name} change {ramp_key} au-delà de decay_fraction"
    assert expected_decay["ent_coef"] < expected_decay["learning_rate"], (
        "l'exploration doit s'arrêter AVANT que le learning rate n'atteigne son plancher, "
        "sinon la politique se fige alors qu'elle peut encore apprendre vite"
    )
    # Le reste de model_params (archi, n_steps, target_kl…) doit être identique : un run long
    # sert à mesurer plus longtemps, pas à changer le modèle mesuré.
    ramps = {"learning_rate", "ent_coef"}
    assert _comparable(long_["model_params"], ramps) == _comparable(ref["model_params"], ramps)

    long_cb, ref_cb = long_["callback_params"], ref["callback_params"]
    assert long_cb["bot_eval_freq"] == 10000, (
        "Un point de mesure tous les 10 000 épisodes : 10 sur x1_long (100k), 10 sur x5_long (100k) "
        "depuis le 2026-08-30 où les deux profils ont été alignés. La fenêtre robuste de 3 donne "
        "8 positions sur 10 points — la même sur les deux. Descendre à 5000 doublerait le coût "
        "de l'évaluation intermédiaire sans gain sur la précision du win-rate final."
    )
    # `bot_eval_final` est un nombre d'épisodes PAR BOT, et un profil `_long` est un run de
    # MESURE : son win-rate final est le chiffre publié, donc sa précision fait partie du
    # livrable. L'erreur-type d'un win-rate autour de 0,5 vaut 0,5/√n — 5,0 points à 100,
    # 2,9 à 300. x1_long et x5_long : 300, alignés depuis le 2026-08-30. Détail dans
    # `bot_eval_final_normal` du JSON, seule source.
    assert long_cb["bot_eval_final"] == LONG_PROFILE_BOT_EVAL_FINAL[long_name]
    assert ref_cb["bot_eval_final"] == REFERENCE_BOT_EVAL_FINAL[ref_name]
    # Corollaire OBLIGATOIRE de la ligne précédente : le timeout porte sur un TASK, et un task
    # joue `bot_eval_final / nb_scenarios` épisodes en séquence — un seul task qui déborde
    # force-termine tout le pool et perd la mesure publiée en fin de run. Arithmétique et marges
    # dans `bot_eval_task_timeout_seconds_normal` (source unique).
    assert long_cb["bot_eval_task_timeout_seconds"] == 7200
    assert ref_cb["bot_eval_task_timeout_seconds"] == 3600
    # `bot_eval_intermediate` est un nombre d'épisodes PAR BOT payé à CHAQUE éval intermédiaire :
    # son coût se rapporte à la durée du run, donc il en dépend au même titre que `bot_eval_freq`.
    # x1_long : 5 évals × 30 ép./bot (réduit de 100 à 30 par commit e07bdfd1, 4 workers), plus
    # l'éval FINALE à 300 ép./bot (≈ 1 h 23, payée une fois). Les durées d'ÉVALUATION ci-dessus se
    # comptent en épisodes de bot et ne dépendent pas du régime d'entraînement ; la durée du RUN,
    # elle, est mesurée et jamais dérivée d'un taux (x1 : 4 h 01 pour ses 10 000 épisodes ;
    # x1_long : 5 h 54 pour 50 000, 2026-08-18 — la pente n'est pas linéaire). Le « 0.1 s/ep →
    # 36k ép./h » que répétaient les notes `total_episodes_normal` de la config datait du régime
    # d'avant la refonte d'observation V11 ; il en a été retiré le 2026-08-23, et le « ~17 min
    # d'entraînement » qui figurait ici en sortait. Sur le run x1 réellement mesuré, 5 évals à
    # 100 ép./bot coûteraient ~65 min, soit ~27 % de la durée du run — assez pour les réduire,
    # pas les « QUATRE FOIS » qu'annonçait le régime périmé. À 10 ép./bot, ~7 min.
    # Ces évals alimentent aussi `save_best_robust` (train.py:3623), mais plus sur x1 : ses 5
    # points de mesure ne laissaient qu'UNE position de fenêtre, donc rien à départager, et le
    # profil est passé à `save_best_robust: false` le 2026-08-11 — sa sortie est son modèle
    # FINAL. Le chiffre publié, lui, sort de `bot_eval_final`, verrouillé plus haut.
    assert long_cb["bot_eval_intermediate"] == LONG_PROFILE_BOT_EVAL_INTERMEDIATE[long_name]
    assert ref_cb["bot_eval_intermediate"] == 10
    # `checkpoint_save_freq`, lui, est bien comparé en bloc, et ce n'est pas un oubli : SB3
    # sauvegarde tous les `save_freq` APPELS du callback (callbacks.py:300), un par pas du
    # VecEnv, jamais des épisodes ; le régler depuis la durée en épisodes n'a pas de sens, le
    # levier est `max_checkpoints`, un compte.
    # `save_best_robust` dépend lui aussi de la longueur du run, et pas par convention : un run
    # trop court ne PEUT pas produire de best model (cf.
    # `test_profile_can_produce_the_best_model_it_promises`), donc le déclarer y serait une
    # promesse vide. C'est le cas de `x5_new` (1000 épisodes) face à `x5_long` (200 000).
    # `robust_window` en dépend de la même façon, et depuis le 2026-08-11 la valeur n'est plus
    # commune aux deux couples : elle est vérifiée nommément juste en dessous.
    overridden = {
        "bot_eval_freq", "bot_eval_final", "bot_eval_task_timeout_seconds",
        "bot_eval_intermediate", "save_best_robust", "robust_window",
        # model_gating_enabled dépend de save_best_robust :
        # x1 (save_best_robust=false) n'active pas le gate, x1_long (true) si.
        "model_gating_enabled",
    }
    assert _comparable(long_cb, overridden) == _comparable(ref_cb, overridden)
    assert _resolved_cb(long_cb, "save_best_robust") is True, (
        "un run de mesure sélectionne son meilleur modèle"
    )
    # model_gating_enabled : lié à save_best_robust (cf. commentaire dans `overridden`).
    # Les deux profils de référence n'activent pas le gate (save_best_robust=false) — valeur
    # pinned sans table, elle est identique pour tous les profils courts.
    assert _resolved_cb(long_cb, "model_gating_enabled") == LONG_PROFILE_MODEL_GATING_ENABLED[long_name]
    assert _resolved_cb(ref_cb, "model_gating_enabled") is False
    # …et « sélectionne » doit vouloir dire quelque chose. La fenêtre GLISSE sur les points de
    # mesure : à `total // freq` points, elle occupe `points - window + 1` positions. Une seule
    # position, c'est la dernière, donc le best model EST le modèle final — le mécanisme tourne
    # sans rien départager, et son nom ment. C'est ce que x1_long est devenu en passant à 50 000
    # épisodes (5 points pour une fenêtre de 5), d'où sa fenêtre de 3.
    assert _resolved_cb(long_cb, "robust_window") == LONG_PROFILE_ROBUST_WINDOW[long_name]
    assert _resolved_cb(ref_cb, "robust_window") == 5
    points = LONG_PROFILE_EPISODES[long_name] // long_cb["bot_eval_freq"]
    positions = points - _resolved_cb(long_cb, "robust_window") + 1
    assert positions >= 2, (
        f"{long_name} : {points} points de mesure pour une fenêtre de "
        f"{_resolved_cb(long_cb, 'robust_window')} → {positions} position(s). Un run de MESURE "
        "doit pouvoir départager au moins deux candidats, sinon son best model est son modèle "
        "final sous un autre nom."
    )
    # L'écarter de la comparaison ne dispense PAS de le vérifier des deux côtés. La valeur attendue
    # vient de la table unique `PROMISES_BEST_MODEL`, verrouillée pour tous les profils par
    # `test_profile_promise_of_a_best_model_is_pinned` : x1 (5 points, une seule position),
    # x1_debug, x5_new (run trop court) et x5_debug ne promettent rien — modèle FINAL.
    assert _resolved_cb(ref_cb, "save_best_robust") is PROMISES_BEST_MODEL[ref_name]
    assert PROMISES_BEST_MODEL[long_name] is True



@pytest.mark.parametrize("profile_name", PROFILE_NAMES)
def test_profile_promise_of_a_best_model_is_pinned(profile_name: str) -> None:
    """Chaque profil déclare-t-il le best model qu'on attend de lui — ni plus, ni moins.

    Le test suivant vérifie qu'une promesse est TENABLE, mais il skippe ceux qui ne promettent
    rien : à lui seul, il laisse passer le retrait d'une promesse. Un run sans best model ne rend
    que son dernier modèle — sans que rien ne rougisse. D'où cette table.

    Elle est exhaustive par construction : un profil ajouté au JSON sans y être classé échoue ici.
    """
    assert profile_name in PROMISES_BEST_MODEL, (
        f"profil '{profile_name}' non classé : décider s'il promet un best model et l'inscrire "
        "dans PROMISES_BEST_MODEL."
    )
    resolved = _resolved_cb(PROFILES[profile_name]["callback_params"], "save_best_robust")
    assert bool(resolved) is PROMISES_BEST_MODEL[profile_name]


@pytest.mark.parametrize("profile_name", PROFILE_NAMES)
def test_profile_can_produce_the_best_model_it_promises(profile_name: str) -> None:
    """Un profil qui déclare `save_best_robust` doit pouvoir calculer un score robuste.

    Le score n'existe qu'une fois `robust_window` évaluations accumulées
    (`training_callbacks.py:2029`) : il faut donc `robust_window × bot_eval_freq` épisodes rien
    que pour en obtenir un premier. En dessous, la promesse est intenable.

    Ce test DOUBLE une validation qui existe déjà — `setup_callbacks` lève au démarrage sur
    exactement cette condition (`train.py:3596-3612`). Le doublon est délibéré, et c'est le même
    usage que `test_every_profile_declares_decay_fraction` juste au-dessus : la validation runtime
    n'est atteinte qu'en lançant un run, qui coûte des minutes de setup avant de refuser de
    partir. Ici la faute se voit en quelques millisecondes, sur tous les profils qui promettent, sans
    qu'aucun ne soit lancé.

    Un profil qui ne promet rien est hors sujet ; il est SKIP et non vert, pour que
    `pytest -rs` montre qui n'est pas couvert plutôt que d'afficher des verts sans vérification.

    Hors périmètre volontairement : `save_best_min_episodes`, l'autre garde de sauvegarde
    (`training_callbacks.py:2008` et `:2088`). Elle se compare à `eval_marker`, qui est CUMULATIF
    et amorcé à l'offset de reprise (`train.py:3649-3651`) : le JSON seul ne connaît pas cet
    offset, donc aucun test lisant ce fichier ne peut trancher — l'invariant appartient à
    `setup_callbacks`, qui, lui, l'a sous la main.
    """
    profile = PROFILES[profile_name]
    cb = profile["callback_params"]
    if not _resolved_cb(cb, "save_best_robust"):
        pytest.skip(f"{profile_name} ne promet aucun best robust model")
    # La garde runtime ne s'applique qu'en cadence ÉPISODES : sinon `bot_eval_freq` compte des
    # timesteps et l'arithmétique ci-dessous ne veut rien dire. Cette clé-là n'hérite pas
    # (`require_key`, train.py:3464) — un profil qui l'omet fait lever le run, pas ce test.
    assert cb["bot_eval_use_episodes"] is True, (
        f"{profile_name} évalue en timesteps : la garde train.py:3596-3612 ne le couvre pas, "
        "et rien ne garantit plus qu'il atteigne sa fenêtre robuste."
    )
    total = profile["total_episodes"]
    freq, window = _resolved_cb(cb, "bot_eval_freq"), _resolved_cb(cb, "robust_window")
    needed = freq * window
    assert needed <= total, (
        f"{profile_name} : robust_window={window} × bot_eval_freq={freq} = {needed} épisodes "
        f"avant le PREMIER score robuste, pour un run de {total}. Le run refuserait de démarrer "
        "(train.py:3596-3612)."
    )
    # SÉLECTIONNER, et pas seulement CALCULER. La garde ci-dessus — celle de `setup_callbacks` —
    # se contente d'un premier score : elle laisse passer un profil qui n'en produit qu'UN, et
    # `save_best_robust` retient alors le dernier modèle en le présentant comme le meilleur.
    # C'est exactement l'état de `x1_long` avant le 2026-08-11 (50 000 épisodes, `bot_eval_freq`
    # 10000, fenêtre de 5 : une seule position possible, la dernière), corrigé ce jour-là en
    # ramenant la fenêtre à 3 — pas en abaissant `bot_eval_freq`, dont le coût est mesuré dans sa
    # note. Sans ce verrou, rien n'empêche le défaut de revenir au prochain changement de durée.
    #
    # Le seuil est le MINIMUM STRICT — deux positions de fenêtre, donc un vrai choix — et non un
    # confort : `x1_long` en a trois (5 évaluations pour une fenêtre de 3), et c'est ce qui rend
    # sa marge visible ici plutôt que supposée.
    evaluations = total // freq
    assert evaluations >= window + 1, (
        f"{profile_name} : {total} épisodes / bot_eval_freq={freq} = {evaluations} évaluations "
        f"pour robust_window={window} → {max(0, evaluations - window + 1)} score(s) robuste(s). "
        "Il en faut au moins 2 pour que save_best_robust choisisse au lieu de subir : baisser "
        f"robust_window à {max(1, evaluations - 1)} ou bot_eval_freq à {total // (window + 1)}."
    )
