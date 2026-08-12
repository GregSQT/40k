# ai/train.py
#!/usr/bin/env python3
"""
ai/train.py - Main training script following AI_INSTRUCTIONS.md exactly
"""

import os
import pathlib
import sys
import io
import argparse
import tempfile
import atexit
import hashlib

import warnings

# Fix Windows encoding for emoji/Unicode output with line buffering
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    # Le seul avertissement vise : NumPy compile avec MINGW-W64 (MUST be before numpy import).
    # Filtrer plus large eteignait les depreciations de nos propres dependances pour tout script
    # qui importe simplement `ai.train`.
    warnings.filterwarnings('ignore', message='.*MINGW-W64.*', category=RuntimeWarning)

import subprocess
import json
import multiprocessing
from copy import deepcopy

# Load training_env from config/config.json (MUST be before numpy/torch import)
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
_config_path = os.path.join(_project_root, "config", "config.json")
_training_env_vars = {}
_torch_compile_mode = None  # "off" by default; set to "reduce-overhead", "max-autotune", or "default" to enable
try:
    with open(_config_path, "r") as _f:
        _cfg = json.load(_f)
    _training_env_vars = _cfg.get("training_env", {})  # get allowed: optional config
    _raw = _cfg.get("torch", {}).get("compile_mode", "off")  # get allowed: optional config
    _torch_compile_mode = None if _raw in (None, "off", "false", "none") else _raw
    for _k, _v in _training_env_vars.items():
        _val = str(int(_v)) if isinstance(_v, (int, float)) else str(_v)
        os.environ.setdefault(_k, _val)
except Exception:
    pass
if (_training_env_vars or _torch_compile_mode) and multiprocessing.current_process().name == "MainProcess":
    _rel = os.path.relpath(_config_path, _project_root) if _project_root else _config_path
    print(f"📋 Config from {_rel}")
    # Ordre de lecture prefere, PUIS toute clef ajoutee a `training_env` : une liste figee
    # affichait un env partiel (NUMEXPR_NUM_THREADS, TORCH_LOGS manquaient), donc une ligne
    # d'entete qui ment sur ce qui est reellement pose dans l'environnement du run.
    _order = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "PYTORCH_CUDA_ALLOC_CONF", "CUDA_LAUNCH_BLOCKING")
    _keys = [k for k in _order if k in _training_env_vars] + [k for k in _training_env_vars if k not in _order]
    _parts = " ".join(f"{k}={os.environ[k]}" for k in _keys)
    if _parts:
        print(f"   env: {_parts}")
    print(f"   torch.compile_mode: {_torch_compile_mode or 'off'}")

import numpy as np
import glob
import shutil
import random
from pathlib import Path
from typing import Callable, Dict, List, Literal, Tuple, Any, Optional, Set, Union, cast, overload

# Fix import paths - Add both script dir and project root
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, script_dir)
sys.path.insert(0, project_root)
from ai.unit_registry import UnitRegistry
sys.path.insert(0, project_root)

# Un import de RandomBot / GreedyBot / DefensiveBot sous try/except ImportError, avec un drapeau
# EVALUATION_BOTS_AVAILABLE, occupait cette place. Jumeau exact de celui deja retire de
# ai/training_callbacks.py : ai/evaluation_bots.py est dans le depot, ce n'est pas une dependance
# optionnelle, et il n'y a pas de cycle a eviter (il ne tire que engine/* et shared/*, et engine
# n'importe ai que paresseusement). Le drapeau valait donc toujours True et ses trois gardes
# etaient morts. Les trois noms importes ici n'etaient de toute facon jamais utilises au niveau
# module : les bots d'entrainement sont construits par _build_training_bots_from_config, qui
# importe les sept classes localement et sans condition.

# Import MaskablePPO - enforces action masking during training
from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3 import PPO
MASKABLE_PPO_AVAILABLE = True

from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback, BaseCallback, CallbackList
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv, VecNormalize, VecEnv  # VecEnv : resout la forward-ref de GymEnv pour get_type_hints()
from stable_baselines3.common.utils import ConstantSchedule, FloatSchedule  # Convert float hyperparameters to callable schedules
from stable_baselines3.common.type_aliases import GymEnv


def _build_training_bots_from_config(training_config):
    """Build weighted bot list from training_config.bot_training.

    Config format:
      bot_training:
        ratios: {random: 0.4, greedy: 0.3, defensive: 0.3}
        randomness: {greedy: 0.10, defensive: 0.10}

    Returns list of bot instances for random.choice() selection.
    """
    from ai.evaluation_bots import (
        RandomBot, GreedyBot, DefensiveBot, ControlBot, AdaptiveBot, ValueTradeBot,
    )

    cfg = require_key(training_config, "bot_training")
    ratios = require_key(cfg, "ratios")
    randomness_cfg = require_key(cfg, "randomness")

    BOT_CLASSES = {
        "random": RandomBot,
        "greedy": GreedyBot,
        "defensive": DefensiveBot,
        "control": ControlBot,
        "adaptive": AdaptiveBot,
        "value_trade": ValueTradeBot,
    }

    # La somme des ratios EST le budget d'entrainement : elle doit valoir 1.0, comme
    # `bot_eval_weights` cote evaluation (`bot_evaluation._load_bot_eval_params`, meme controle).
    # Sans lui, un ratio oublie ou en double deplace silencieusement le budget d'adversaire.
    total_ratio = sum(float(r) for r in ratios.values())
    if abs(total_ratio - 1.0) > 1e-9:
        detail = ", ".join(f"{k}={v}" for k, v in ratios.items())
        raise ValueError(
            f"bot_training.ratios must sum to 1.0 (got {detail}, total={total_ratio})"
        )

    # ⚠️ Pool de 100, pas de 10. `BotControlledEnv` tire l'adversaire de l'episode par un
    # `random.choice` UNIFORME sur cette liste (env_wrappers, `_use_random_bots`) : la frequence
    # reelle d'un bot vaut donc count / len(bots), et `round(ratio * 10)` la deformait. Sur le
    # panel a six bots, 0.35/0.15/0.15/0.15/0.15/0.05 donnait 4/2/2/2/2/1 = 13 instances, soit
    # 0.31 pour control (-11 %) et 0.077 pour random (+54 %) : le budget d'adversaire n'etait
    # pas celui de la config. A 100, tout ratio au centieme pres tombe juste.
    total = 100
    bots = []
    for bot_name, ratio in ratios.items():
        count = round(ratio * total)
        if bot_name == "random":
            count = max(1, count)
        if count <= 0:
            continue
        if bot_name == "random":
            for _ in range(count):
                bots.append(RandomBot())
        elif bot_name in BOT_CLASSES:
            # Pas de defaut : un bot pondere sans entree de randomness est une config
            # incomplete, pas un bot a 10 % de bruit choisi en silence (regle T1).
            r_val = float(require_key(randomness_cfg, bot_name))
            for _ in range(count):
                bots.append(BOT_CLASSES[bot_name](randomness=r_val))
        else:
            raise ValueError(f"Unknown bot name in ratios: {bot_name!r}")
    
    return bots


def _describe_ramp(name: str, start: float, end: float, total_eps: int, decay_fraction: float) -> str:
    """Ligne de log d'une rampe : ou elle s'acheve, et le fait qu'elle tienne son plancher."""
    return (
        f"✅ Added {name} schedule callback: {start} -> {end} over {int(total_eps * decay_fraction)} "
        f"episodes (decay_fraction {decay_fraction} of {total_eps}), then held at {end}"
    )


def _model_params_with_ent_coef_frozen(model_params: dict, log=print) -> dict:
    """COPIE de `model_params` ou une rampe `ent_coef` est reduite a sa valeur de depart.

    PPO n'accepte qu'un scalaire ; la decroissance est ensuite pilotee par
    `EntropyScheduleCallback`. La copie n'est pas de la prudence : les deux appelants qui
    lisaient `training_config["model_params"]` directement ECRASAIENT la rampe dans la config
    elle-meme, si bien que `setup_callbacks`, qui relit la MEME structure plus tard, y trouvait
    un float, ne creait aucun callback d'entropie et figeait `ent_coef` a sa valeur de depart
    pour tout le run -- `decay_fraction` compris, sans le moindre signal. Rendre une copie est
    ce qui empeche la lecture d'une config de dependre de qui l'a lue avant.
    """
    if not isinstance(model_params.get("ent_coef"), dict):
        return dict(model_params)
    ent_config = model_params["ent_coef"]
    start_val = float(ent_config["start"])
    frozen = dict(model_params)
    frozen["ent_coef"] = start_val
    log(
        f"✅ Entropy coefficient schedule: {start_val} -> {float(ent_config['end'])} "
        f"(will be applied via callback)"
    )
    return frozen


def _make_constant_lr_schedule(lr_config):
    """Valeur INITIALE du learning rate, sous la forme de callable qu'attend SB3.

    Rend une constante dans les deux cas : `float` (LR constant, aucun callback ne le pilote) et
    `dict {"initial", "final", "decay_fraction"}` (constante a `initial`, la decroissance etant
    pilotee par `LearningRateScheduleCallback`, PAR EPISODE).

    Le nom dit « constant » parce qu'une rampe rendue ici serait inerte ET fausse : le seul usage
    du callable est `optimizer(lr=lr_schedule(1))`, et `learn()` etant appele par chunks,
    `progress_remaining` refait 1 -> 0 a chaque chunk. Demonstration complete dans
    Documentation/AI_TRAINING.md, section « Rampes learning_rate / ent_coef ».
    """
    if isinstance(lr_config, (int, float)):
        return ConstantSchedule(float(lr_config))
    if isinstance(lr_config, dict):
        return ConstantSchedule(float(lr_config["initial"]))
    raise ValueError(f"learning_rate must be float or dict with initial/final, got {type(lr_config)}")


# `model_params` que `--append` ne reapplique PAS a un modele charge : `tensorboard_log`, `verbose`
# et `device` sont poses par les appelants, `policy`/`policy_kwargs` decrivent le RESEAU, dont les
# poids sont precisement ce qu'on conserve — les changer impose un `--new`, pas un `--append`.
# Source unique : `_apply_curriculum_model_params` et son test derivent tous deux de cette ligne.
CURRICULUM_EXCLUDED_MODEL_PARAMS = frozenset({
    "policy", "policy_kwargs", "tensorboard_log", "verbose", "device",
})

# Hyperparametres recopies tels quels sur le modele, tous AVANT la reconstruction du rollout
# buffer (gamma/gae_lambda y sont recopies). Ceux qui demandent une conversion — `learning_rate`,
# `clip_range`, `clip_range_vf` — et `n_steps`, que `test_every_n_steps_assignment_rebuilds_the_buffer`
# suit par analyse syntaxique, restent des affectations explicites dans la fonction.
_PLAIN_CURRICULUM_KEYS = (
    "ent_coef", "normalize_advantage", "target_kl", "gamma", "gae_lambda",
    "batch_size", "n_epochs", "vf_coef", "max_grad_norm",
)


def _apply_curriculum_model_params(model, model_params: dict, log=print) -> None:
    """CURRICULUM LEARNING : applique les hyperparametres du run a un modele CHARGE.

    Permet a une phase 2 (`--append`) de tourner avec d'autres learning rate, entropie, clip...
    que la phase 1, en conservant les poids appris. `MaskablePPO.load` rejoue bien `_setup_model`,
    mais APRES avoir ecrase `__dict__` avec les hyperparametres du CHECKPOINT
    (stable_baselines3/common/base_class.py:738-740) : tout ce qu'il derive — `lr_schedule`,
    `clip_range`, le rollout buffer — vient donc de la phase precedente. Sans cette passe, la
    config du run serait ignoree en silence.

    Appele par les deux appelants (`create_multi_agent_model`, `train_with_scenario_rotation`),
    qui portaient ce bloc en DOUBLE. `log` absorbe la seule variation restante entre les deux
    (`print` / `chunk_log`). Le chargement lui-meme passe par `_load_checkpoint` et ne rattrape
    plus rien : un refus emis ici, comme un checkpoint illisible, remonte et arrete le run — il ne
    peut plus se transformer en abandon silencieux des poids de la phase 1.

    Doit couvrir TOUT `model_params` hors `CURRICULUM_EXCLUDED_MODEL_PARAMS`.
    `test_curriculum_covers_every_model_param` derive la liste attendue du fichier de config REEL :
    un hyperparametre ajoute a un profil sans etre traite ici rend le test rouge.

    `clip_range`/`clip_range_vf` passent par `FloatSchedule` et `learning_rate` ecrit AUSSI
    `lr_schedule` : c'est ce que `_setup_model` derive, et il l'a derive du CHECKPOINT.
    """
    clip_vf = model_params.get("clip_range_vf")
    if clip_vf is not None and not clip_vf > 0:
        # Le meme refus que `MaskablePPO._setup_model` (ppo_mask.py:177), qui ne s'execute QU'A la
        # creation : sans lui, `clip_range_vf: 0` est rejete en --new et accepte en --append, ou
        # il gele la value function pour tout le run. `null` en revanche est la valeur METIER
        # « pas de clipping », que SB3 teste explicitement — pas une absence a combler.
        raise ValueError(
            f"model_params.clip_range_vf doit etre > 0 (ou null pour desactiver le clipping "
            f"de la value function), got {clip_vf}"
        )

    if "learning_rate" in model_params:
        model.learning_rate = _make_constant_lr_schedule(model_params["learning_rate"])
        model.lr_schedule = model.learning_rate
    if "clip_range" in model_params:
        model.clip_range = FloatSchedule(model_params["clip_range"])
    if "clip_range_vf" in model_params:
        model.clip_range_vf = None if clip_vf is None else FloatSchedule(clip_vf)
    for key in _PLAIN_CURRICULUM_KEYS:
        if key in model_params:
            setattr(model, key, model_params[key])

    # Reconstruction INCONDITIONNELLE du rollout buffer, et APRES n_steps/gamma/gae_lambda : le
    # buffer recopie les trois a sa construction (`RolloutBuffer.__init__`, buffers.py:386-387) et
    # c'est SA copie que lit `compute_returns_and_advantage`. La conditionner a `n_steps` — sa
    # seule raison d'etre historique, le redimensionnement — laissait un profil qui change le
    # discount sans toucher n_steps calculer son GAE avec le gamma du CHECKPOINT, pendant que le
    # log annoncait l'autre. Sans changement de taille, une reallocation d'un buffer vide.
    if "n_steps" in model_params:
        model.n_steps = model_params["n_steps"]
    recreate_rollout_buffer(model, log=log)

    log(f"✅ Applied new phase hyperparameters: lr={model.learning_rate}, ent={model.ent_coef}, clip={model.clip_range}")


def _load_checkpoint(model_path: str, env, device: str) -> MaskablePPO:
    """Charge un checkpoint MaskablePPO. LEVE si le fichier est illisible — jamais de repli.

    Les trois sites de chargement de ce module entouraient `MaskablePPO.load` d'un
    `except Exception` qui construisait un modele NEUF et poursuivait l'entrainement : un
    `--append` dont le .zip est corrompu, tronque ou remplace par autre chose tournait des heures
    depuis des poids aleatoires, sortait en code 0, et n'en disait que deux lignes noyees dans le
    log. Le seul signal du desastre etait le win-rate du run suivant. C'est exactement le repli
    anti-erreur que T1 refuse : ici l'echec de lecture n'a AUCUNE reprise metier valide, il n'y a
    rien a continuer.

    Passe par un helper unique et non recopie sur les trois sites : le motif etait deja divergent
    (deux `print`, un `chunk_log`, et un des trois messages avec un emoji casse), et c'est
    precisement ainsi qu'un repli survit a la suppression de son jumeau.
    """
    try:
        return MaskablePPO.load(model_path, env=env, device=device)
    except Exception as exc:
        raise RuntimeError(
            f"Checkpoint illisible : {model_path} ({type(exc).__name__}: {exc}). "
            f"L'entrainement s'arrete au lieu de repartir de poids aleatoires. Verifier le "
            f"chemin et l'integrite du .zip ; pour repartir volontairement de zero, relancer "
            f"avec --new (qui archive le modele existant) au lieu de --append."
        ) from exc


def _load_configured_unit_rule_ids(project_root_path: str) -> Set[str]:
    """Load configured rule IDs from config/unit_rules.json."""
    unit_rules_path = os.path.join(project_root_path, "config", "unit_rules.json")
    with open(unit_rules_path, "r", encoding="utf-8") as f:
        raw_rules = json.load(f)
    if not isinstance(raw_rules, dict):
        raise TypeError(
            f"config/unit_rules.json must be an object mapping rule keys to rule definitions "
            f"(got {type(raw_rules).__name__})"
        )
    configured_rule_ids: Set[str] = set()
    for rule_key, rule_data in raw_rules.items():
        if not isinstance(rule_data, dict):
            raise TypeError(
                f"Rule entry '{rule_key}' must be an object in config/unit_rules.json "
                f"(got {type(rule_data).__name__})"
            )
        configured_id = require_key(rule_data, "id")
        if not isinstance(configured_id, str) or not configured_id.strip():
            raise ValueError(f"Rule entry '{rule_key}' has invalid id: {configured_id!r}")
        configured_rule_ids.add(configured_id.strip())
    if len(configured_rule_ids) == 0:
        raise ValueError("config/unit_rules.json does not contain any configured rule id")
    return configured_rule_ids


def _scenario_has_forced_controlled_unit(
    scenario_file: str,
    unit_registry: Any,
    configured_rule_ids: Set[str],
    controlled_player_mode: str,
) -> bool:
    """Return True if scenario includes at least one controlled unit with configured rule."""
    from engine.game_state import GameStateManager

    if controlled_player_mode not in {"p1", "p2", "random"}:
        raise ValueError(
            f"controlled_player_mode must be one of 'p1', 'p2', 'random' "
            f"(got {controlled_player_mode!r})"
        )
    if controlled_player_mode == "p1":
        seats_to_check = [1]
    elif controlled_player_mode == "p2":
        seats_to_check = [2]
    else:
        seats_to_check = [1, 2]

    for seat in seats_to_check:
        temp_manager = GameStateManager({"board": {}, "controlled_player": seat}, unit_registry)
        scenario_result = temp_manager.load_units_from_scenario(scenario_file, unit_registry)
        units = require_key(scenario_result, "units")
        if not isinstance(units, list):
            raise TypeError(
                f"Scenario '{scenario_file}' must resolve to a list of units "
                f"(got {type(units).__name__})"
            )

        for unit in units:
            unit_player = require_key(unit, "player")
            if unit_player != seat:
                continue
            unit_rules = require_key(unit, "UNIT_RULES")
            if not isinstance(unit_rules, list):
                raise TypeError(
                    f"UNIT_RULES must be list for unit {require_key(unit, 'id')} "
                    f"in scenario '{scenario_file}' (got {type(unit_rules).__name__})"
                )
            for entry in unit_rules:
                if not isinstance(entry, dict):
                    raise TypeError(
                        f"Each UNIT_RULES entry must be object for unit {require_key(unit, 'id')} "
                        f"in scenario '{scenario_file}' (got {type(entry).__name__})"
                    )
                rule_id = require_key(entry, "ruleId")
                if not isinstance(rule_id, str) or not rule_id.strip():
                    raise ValueError(
                        f"Invalid ruleId for unit {require_key(unit, 'id')} in scenario '{scenario_file}': {rule_id!r}"
                    )
                if rule_id in configured_rule_ids:
                    return True
    return False


def _apply_unit_rule_forcing_weights(
    scenario_list: List[str],
    training_config: Dict[str, Any],
    unit_registry: Any,
    controlled_player_mode: str,
) -> List[str]:
    """Increase weights of scenarios with controlled units having configured unit rules."""
    forcing_cfg = training_config.get("unit_rule_forcing")
    if forcing_cfg is None:
        return scenario_list
    if not isinstance(forcing_cfg, dict):
        raise TypeError(
            f"unit_rule_forcing must be an object in training config "
            f"(got {type(forcing_cfg).__name__})"
        )

    enabled = require_key(forcing_cfg, "enabled")
    if not isinstance(enabled, bool):
        raise TypeError(f"unit_rule_forcing.enabled must be bool (got {type(enabled).__name__})")
    if not enabled:
        return scenario_list

    target_ratio = require_key(forcing_cfg, "target_controlled_episode_ratio")
    if not isinstance(target_ratio, (int, float)):
        raise TypeError(
            f"unit_rule_forcing.target_controlled_episode_ratio must be number "
            f"(got {type(target_ratio).__name__})"
        )
    target_ratio = float(target_ratio)
    if target_ratio <= 0.0 or target_ratio > 1.0:
        raise ValueError(
            "unit_rule_forcing.target_controlled_episode_ratio must be in (0, 1]"
        )

    max_scenario_weight = require_key(forcing_cfg, "max_scenario_weight")
    if not isinstance(max_scenario_weight, int):
        raise TypeError(
            f"unit_rule_forcing.max_scenario_weight must be integer "
            f"(got {type(max_scenario_weight).__name__})"
        )
    if max_scenario_weight < 1:
        raise ValueError("unit_rule_forcing.max_scenario_weight must be >= 1")

    configured_rule_ids = _load_configured_unit_rule_ids(project_root)
    scenario_counts: Dict[str, int] = {}
    for scenario_path in scenario_list:
        if scenario_path not in scenario_counts:
            scenario_counts[scenario_path] = 0
        scenario_counts[scenario_path] += 1

    forced_scenarios: List[str] = []
    for scenario_path in scenario_counts.keys():
        if _scenario_has_forced_controlled_unit(
            scenario_path,
            unit_registry,
            configured_rule_ids,
            controlled_player_mode,
        ):
            forced_scenarios.append(scenario_path)

    if len(forced_scenarios) == 0:
        raise ValueError(
            "unit_rule_forcing.enabled=true but no scenario contains a controlled unit "
            "with configured UNIT_RULES"
        )

    total_weight = sum(scenario_counts.values())
    forced_weight = sum(scenario_counts[path] for path in forced_scenarios)
    current_ratio = forced_weight / float(total_weight)
    if current_ratio >= target_ratio:
        return scenario_list

    weighted_forced = sorted(forced_scenarios)
    idx = 0
    while (forced_weight / float(total_weight)) < target_ratio:
        scenario_to_boost = weighted_forced[idx % len(weighted_forced)]
        current_weight = scenario_counts[scenario_to_boost]
        if current_weight < max_scenario_weight:
            scenario_counts[scenario_to_boost] = current_weight + 1
            forced_weight += 1
            total_weight += 1
        idx += 1
        if idx >= len(weighted_forced) and all(
            scenario_counts[path] >= max_scenario_weight for path in weighted_forced
        ):
            break

    final_ratio = forced_weight / float(total_weight)
    if final_ratio < target_ratio:
        raise ValueError(
            "unit_rule_forcing target cannot be reached with current scenarios and max_scenario_weight. "
            f"target={target_ratio:.4f}, reached={final_ratio:.4f}, "
            f"forced_scenarios={len(weighted_forced)}, max_scenario_weight={max_scenario_weight}"
        )

    weighted_scenario_list: List[str] = []
    for scenario_path, weight in sorted(scenario_counts.items(), key=lambda item: item[0]):
        weighted_scenario_list.extend([scenario_path] * weight)
    return weighted_scenario_list


def _normalize_scenario_name(scenario_path: str) -> str:
    """Normalize scenario file path to canonical scenario name without prefix/suffix."""
    if not isinstance(scenario_path, str) or not scenario_path.strip():
        raise ValueError(f"Invalid scenario path: {scenario_path!r}")
    scenario_filename = os.path.basename(scenario_path.strip())
    if not scenario_filename.endswith(".json"):
        raise ValueError(f"Scenario path must end with .json: {scenario_path}")
    scenario_name = scenario_filename[:-5]
    # Temporary ref-mixed scenarios use suffix "__<hash>".
    # Keep canonical scenario name for config matching (training_hard, etc.).
    if "__" in scenario_name:
        scenario_name = scenario_name.split("__", 1)[0]
    if scenario_name.startswith("scenario_"):
        scenario_name = scenario_name[len("scenario_"):]
    if not scenario_name:
        raise ValueError(f"Cannot normalize scenario name from path: {scenario_path}")
    return scenario_name


def _apply_training_hard_weights(
    scenario_list: List[str],
    training_config: Dict[str, Any],
) -> List[str]:
    """Increase weights of configured training_hard scenarios to reach target ratio."""
    training_hard_cfg = training_config.get("training_hard")
    if training_hard_cfg is None:
        return scenario_list
    if not isinstance(training_hard_cfg, dict):
        raise TypeError(
            f"training_hard must be an object in training config "
            f"(got {type(training_hard_cfg).__name__})"
        )

    enabled = require_key(training_hard_cfg, "enabled")
    if not isinstance(enabled, bool):
        raise TypeError(f"training_hard.enabled must be bool (got {type(enabled).__name__})")
    if not enabled:
        return scenario_list

    target_ratio = require_key(training_hard_cfg, "target_episode_ratio")
    if not isinstance(target_ratio, (int, float)):
        raise TypeError(
            f"training_hard.target_episode_ratio must be number "
            f"(got {type(target_ratio).__name__})"
        )
    target_ratio = float(target_ratio)
    if target_ratio <= 0.0 or target_ratio > 1.0:
        raise ValueError("training_hard.target_episode_ratio must be in (0, 1]")

    max_scenario_weight = require_key(training_hard_cfg, "max_scenario_weight")
    if not isinstance(max_scenario_weight, int):
        raise TypeError(
            f"training_hard.max_scenario_weight must be integer "
            f"(got {type(max_scenario_weight).__name__})"
        )
    if max_scenario_weight < 1:
        raise ValueError("training_hard.max_scenario_weight must be >= 1")

    raw_scenario_names = require_key(training_hard_cfg, "scenario_names")
    if not isinstance(raw_scenario_names, list):
        raise TypeError(
            f"training_hard.scenario_names must be list "
            f"(got {type(raw_scenario_names).__name__})"
        )
    if len(raw_scenario_names) == 0:
        raise ValueError("training_hard.enabled=true requires non-empty training_hard.scenario_names")

    configured_scenario_names: Set[str] = set()
    for raw_name in raw_scenario_names:
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError(f"Invalid entry in training_hard.scenario_names: {raw_name!r}")
        configured_scenario_names.add(raw_name.strip())
    if len(configured_scenario_names) == 0:
        raise ValueError("training_hard.scenario_names must contain at least one non-empty name")

    scenario_counts: Dict[str, int] = {}
    for scenario_path in scenario_list:
        if scenario_path not in scenario_counts:
            scenario_counts[scenario_path] = 0
        scenario_counts[scenario_path] += 1

    training_hard_scenarios: List[str] = []
    for scenario_path in scenario_counts.keys():
        normalized_name = _normalize_scenario_name(scenario_path)
        if normalized_name in configured_scenario_names:
            training_hard_scenarios.append(scenario_path)

    if len(training_hard_scenarios) == 0:
        configured_preview = sorted(configured_scenario_names)
        raise ValueError(
            "training_hard.enabled=true but none of scenario_list matches training_hard.scenario_names. "
            f"Configured names: {configured_preview}"
        )

    total_weight = sum(scenario_counts.values())
    training_hard_weight = sum(scenario_counts[path] for path in training_hard_scenarios)
    current_ratio = training_hard_weight / float(total_weight)
    if current_ratio >= target_ratio:
        return scenario_list

    weighted_training_hard = sorted(training_hard_scenarios)
    idx = 0
    while (training_hard_weight / float(total_weight)) < target_ratio:
        scenario_to_boost = weighted_training_hard[idx % len(weighted_training_hard)]
        current_weight = scenario_counts[scenario_to_boost]
        if current_weight < max_scenario_weight:
            scenario_counts[scenario_to_boost] = current_weight + 1
            training_hard_weight += 1
            total_weight += 1
        idx += 1
        if idx >= len(weighted_training_hard) and all(
            scenario_counts[path] >= max_scenario_weight for path in weighted_training_hard
        ):
            break

    final_ratio = training_hard_weight / float(total_weight)
    if final_ratio < target_ratio:
        raise ValueError(
            "training_hard target cannot be reached with current scenarios and max_scenario_weight. "
            f"target={target_ratio:.4f}, reached={final_ratio:.4f}, "
            f"training_hard_scenarios={len(weighted_training_hard)}, "
            f"max_scenario_weight={max_scenario_weight}"
        )

    weighted_scenario_list: List[str] = []
    for scenario_path, weight in sorted(scenario_counts.items(), key=lambda item: item[0]):
        weighted_scenario_list.extend([scenario_path] * weight)
    return weighted_scenario_list


def _count_units_from_roster_scenario(scenario_data: Dict[str, Any], scenario_file: str) -> int:
    """Count units for roster-based scenarios without triggering deployment (avoids O(board_size) cost)."""
    import glob as _glob
    scale_name = str(require_key(scenario_data, "scale")).strip()
    scenario_path_obj = Path(os.path.abspath(scenario_file))
    parts = scenario_path_obj.parts
    try:
        agents_idx = parts.index("agents")
        scenario_agent_key = parts[agents_idx + 1]
    except (ValueError, IndexError):
        raise ValueError(f"Cannot resolve agent key from scenario path: {scenario_file}")

    def _split_from_path(path_str: str) -> str:
        if "/scenarios/training/" in path_str:
            return "training"
        if "/scenarios/holdout_regular/" in path_str:
            return "holdout_regular"
        if "/scenarios/holdout_hard/" in path_str:
            return "holdout_hard"
        raise ValueError(f"Cannot resolve split from scenario path: {path_str}")

    split = _split_from_path(scenario_file)
    holdout_split = "holdout" if split != "training" else "training"
    project_root = Path(os.path.abspath(__file__)).parent.parent

    def _roster_model_count(roster_data: Dict[str, Any]) -> int:
        """Nombre total de FIGURINES d'un roster compact (escouades × figurines).

        Le compteur dimensionné en aval (max_steps_per_turn -> max_bot_iterations dans
        BotControlledEnv) s'incrémente par action, et les actions sont par figurine
        (cf. generic_handlers: 'episode_steps compte par action/figurine'). Compter les
        escouades sous-dimensionnerait la borne et déclencherait une fausse détection de
        boucle infinie sur toute escouade multi-figurines.
        """
        total = 0
        for e in roster_data["composition"]:
            if not isinstance(e, dict):
                continue
            if "models_per_unit" in e and "models" in e:
                raise ValueError(
                    "Roster composition entry cannot define both 'models_per_unit' and 'models'"
                )
            if "models_per_unit" in e:
                models_per_unit = int(e["models_per_unit"])
            elif "models" in e:
                models_per_unit = len(e["models"])
            else:
                models_per_unit = 1
            total += int(e["count"]) * models_per_unit
        return total

    def _max_count_for_ref(ref_value: str, roster_kind: str) -> int:
        """Return max unit count across all matching roster files for a given ref."""
        if isinstance(ref_value, str):
            ref_stripped = ref_value.strip().replace("\\", "/")
        else:
            return 0
        random_token = f"{holdout_split}_random" if split != "training" else "training_random"
        if ref_stripped == random_token or ref_stripped.endswith("_random"):
            actual_split = holdout_split if split != "training" else "training"
            if roster_kind == "agent":
                base_dir = project_root / "config" / "agents" / scenario_agent_key / "rosters" / scale_name / actual_split
                pattern = f"agent_{actual_split}_roster*.json"
            else:
                base_dir = project_root / "config" / "agents" / "_p2_rosters" / scale_name / actual_split
                pattern = f"opponent_{actual_split}_roster*.json"
            if not base_dir.exists():
                return 0
            roster_files = sorted(base_dir.glob(pattern))
            roster_files = [p for p in roster_files if "_kpis" not in p.name and "_matchups" not in p.name]
            if not roster_files:
                return 0
            max_count = 0
            for rf in roster_files:
                try:
                    rd = json.load(open(rf))
                    max_count = max(max_count, _roster_model_count(rd))
                except Exception:
                    pass
            return max_count
        else:
            parts_ref = ref_stripped.split("/")
            ref_filename = parts_ref[-1] if parts_ref else ref_stripped
            if roster_kind == "agent":
                roster_path = project_root / "config" / "agents" / scenario_agent_key / "rosters" / scale_name / ref_stripped
            else:
                roster_path = project_root / "config" / "agents" / "_p2_rosters" / scale_name / ref_stripped
            if not roster_path.exists():
                return 0
            try:
                rd = json.load(open(roster_path))
                return _roster_model_count(rd)
            except Exception:
                return 0

    agent_ref = require_key(scenario_data, "agent_roster_ref")
    opponent_ref = require_key(scenario_data, "opponent_roster_ref")
    return _max_count_for_ref(str(agent_ref), "agent") + _max_count_for_ref(str(opponent_ref), "opponent")


def _load_scenario_wall_ref(scenario_path: str) -> Optional[str]:
    """Load the scenario's wall_ref, or None when the scenario declares none.

    The engine contract (game_state.py, resolution des murs) rend 'wall_ref' OPTIONNEL :
    un scenario tire ses murs de 'wall_hexes', de 'wall_ref', et/ou de 'terrain_ref'
    (additif). La banque migree en V11 T4 est terrain-only : aucun 'wall_ref'.
    None represente donc fidelement "pas de dimension wall a ponderer" — ce n'est pas
    une valeur par defaut masquant une erreur. Une cle presente reste strictement validee.
    """
    if not isinstance(scenario_path, str) or not scenario_path.strip():
        raise ValueError(f"Invalid scenario path: {scenario_path!r}")
    with open(scenario_path, "r", encoding="utf-8-sig") as f:
        scenario_data = json.load(f)
    if not isinstance(scenario_data, dict):
        raise TypeError(
            f"Scenario JSON must be an object for wall_ref weighting: {scenario_path}"
        )
    if "wall_ref" not in scenario_data:
        return None
    wall_ref_raw = scenario_data["wall_ref"]
    if not isinstance(wall_ref_raw, str) or not wall_ref_raw.strip():
        raise ValueError(f"Scenario wall_ref must be a non-empty string: {scenario_path}")
    return wall_ref_raw.strip()


# Environnements vectorises ouverts, dans l'ordre de creation. Un `SubprocVecEnv` possede des
# PROCESSUS : le perdre de vue, c'est les laisser tuer par signal a la sortie. Les fermetures
# nominales couvrent les chemins nominaux ; ce registre couvre le reste — exception levee au
# milieu d'un run, branche d'echec, retour anticipe — sans exiger un `finally`
# dans chacune des fonctions concernees.
_OPEN_VEC_ENVS: List[Any] = []


def register_vec_env(env):
    """Enregistre un environnement vectorise pour le balayage final. Rend `env` inchange."""
    _OPEN_VEC_ENVS.append(env)
    return env


def close_all_training_envs(log=print) -> None:
    """Ferme ce qui reste ouvert. Idempotent : `close()` d'un VecEnv deja ferme ne fait rien."""
    while _OPEN_VEC_ENVS:
        close_training_env(_OPEN_VEC_ENVS.pop(), "balayage final", log)


def close_training_env(env, contexte: str, log=print, timeout_s: float = 30.0) -> None:
    """Arrete proprement l'environnement d'entrainement (workers compris).

    POURQUOI : avec `SubprocVecEnv`, chaque env vit dans un processus fils DEMONIQUE. Sans
    `close()`, personne ne leur demande jamais de s'arreter : a la fin du run, le gestionnaire
    `multiprocessing` du pere les termine par signal. Un fils tue par signal n'execute AUCUN
    code de fin — tout tampon non vide est perdu. Symptome observe : la queue de
    `perf_timing.log` de chaque worker, donc precisement ses derniers episodes, disparaissait.
    `close()` leur envoie l'ordre d'arret puis attend leur sortie normale.

    Appelee depuis un `finally` : l'echec est IMPRIME et non leve. Lever ici remplacerait
    l'exception d'entrainement en cours de propagation et masquerait la vraie cause — c'est le
    seul endroit ou taire l'exception est moins grave que de la substituer.

    BORNEE DANS LE TEMPS : `SubprocVecEnv.close()` fait `remote.recv()` puis `process.join()`
    SANS timeout. Un worker bloque figerait donc la fin du run — regression par rapport a
    l'avant, ou le processus sortait toujours (quitte a tuer ses fils). La fermeture tourne dans
    un thread demonique : passe le delai, on renonce et on le DIT ; la sortie du processus
    terminera les workers comme avant, avec la perte de tampon que cela implique.
    """
    if env is None:
        log(f"⚠️  {contexte} : aucun environnement attaché au modèle, "
            f"workers potentiellement laissés en vie.")
        return

    # UNE seule tentative par environnement. Sans ce retrait, une fermeture qui EXPIRE laissait
    # l'env dans le registre : le balayage final en relancait une seconde, concurrente de la
    # premiere restee vivante — deux threads emettant sur la meme `multiprocessing.Connection`
    # et attendant les memes fils, pour 30 s de plus. La borne de temps annoncee ne tenait plus.
    # Le retrait suit la chaine des wrappers : on ferme souvent un `VecNormalize`, alors que
    # c'est le `SubprocVecEnv` qu'il enveloppe qui est enregistre.
    enveloppes = []
    sonde = env
    while sonde is not None:
        enveloppes.append(id(sonde))
        sonde = getattr(sonde, "venv", None)
    _OPEN_VEC_ENVS[:] = [e for e in _OPEN_VEC_ENVS if id(e) not in enveloppes]

    import threading

    echec: List[str] = []

    def _fermer() -> None:
        try:
            env.close()
        except Exception as exc:  # noqa: BLE001 — voir docstring : dans un finally, on n'ecrase pas
            echec.append(str(exc))

    fermeture = threading.Thread(target=_fermer, name="close_training_env", daemon=True)
    fermeture.start()
    fermeture.join(timeout_s)
    if fermeture.is_alive():
        log(f"⚠️  {contexte} : fermeture toujours en cours après {timeout_s:.0f}s "
            f"(worker bloqué ?) — abandon, le processus terminera ses fils par signal.")
    elif echec:
        log(f"⚠️  {contexte} : fermeture de l'environnement échouée ({echec[0]}). "
            f"Les processus workers ont pu être tués par signal.")


def apply_rollout_n_steps(model_params: Dict[str, Any], n_envs: int, observation_space,
                          log=print) -> int:
    """Convertit `model_params["n_steps"]` (TOTAL par update) en pas PAR ENV, et borne le buffer.

    POINT DE PASSAGE UNIQUE : tout chemin qui construit un `SubprocVecEnv` de `n_envs` passe
    par ici. La division a vecu un temps dans le seul `train_with_scenario_rotation`, et un
    chemin oublie a alloue `8192 x 48 = 393 216` transitions, soit 44 Go rien que pour les
    observations, jusqu'a tuer la VM WSL. Mesures et verrous :
    `tests/unit/ai/test_rollout_buffer_sizing.py`.

    Le total journalise est celui REELLEMENT obtenu (`effective * n_envs`), jamais le total
    demande : `//` tronque, donc 8192 sur 48 envs ne donne pas 8192 mais 8160. Annoncer le
    total demande a deja fait valider a `scripts/ab_train_common.py` deux configurations que
    le clamp rendait identiques.

    Le garde-fou de taille refuse de construire un buffer plus gros que la memoire
    disponible : sans lui, l'erreur ne se manifeste qu'apres plusieurs minutes de
    remplissage, sous la forme d'un OOM sans rapport apparent avec `n_steps`.
    """
    if "n_steps" not in model_params:
        raise KeyError("model_params.n_steps is required to size the PPO rollout buffer")
    base_n_steps = model_params["n_steps"]
    if not isinstance(base_n_steps, int) or isinstance(base_n_steps, bool) or base_n_steps <= 0:
        raise ValueError(f"model_params.n_steps must be a positive integer (got {base_n_steps!r})")
    if n_envs > 1:
        effective_n_steps = max(1, base_n_steps // n_envs)
        model_params["n_steps"] = effective_n_steps
        log(
            f"📊 n_envs={n_envs}: using n_steps={effective_n_steps} per env "
            f"({effective_n_steps * n_envs} total per update, config asked {base_n_steps})"
        )
    else:
        effective_n_steps = base_n_steps

    floats_per_obs = _observation_floats(observation_space)
    buffer_bytes = floats_per_obs * 4 * effective_n_steps * n_envs
    available_bytes = _available_memory_bytes()
    if available_bytes is not None and buffer_bytes > available_bytes * 0.5:
        raise MemoryError(
            f"PPO rollout buffer would need {buffer_bytes / 2**30:.1f} GiB of observations "
            f"({effective_n_steps} steps x {n_envs} envs x {floats_per_obs} floats), "
            f"for {available_bytes / 2**30:.1f} GiB available. "
            "Reduce model_params.n_steps (it is a TOTAL, divided by n_envs) or n_envs."
        )
    return effective_n_steps


def recreate_rollout_buffer(model, log=print) -> None:
    """Reconstruit le rollout buffer apres un changement de `model.n_steps` sur un modele charge.

    `MaskablePPO.load` dimensionne le buffer sur le `n_steps` du CHECKPOINT. Ecrire
    `model.n_steps` ensuite ne le redimensionne pas : le modele collecte alors sur l'ancienne
    taille, en contradiction silencieuse avec la config du run.

    La classe depend de l'espace d'observation. `MaskableRolloutBuffer` etait code en dur ici,
    alors que le pipeline squad expose un espace `Dict` — il lui faut `MaskableDictRolloutBuffer`.
    """
    import gymnasium as gym
    from sb3_contrib.common.maskable.buffers import (
        MaskableDictRolloutBuffer,
        MaskableRolloutBuffer,
    )

    buffer_cls = (
        MaskableDictRolloutBuffer
        if isinstance(model.observation_space, gym.spaces.Dict)
        else MaskableRolloutBuffer
    )
    model.rollout_buffer = buffer_cls(
        model.n_steps,
        model.observation_space,
        model.action_space,
        device=model.device,
        gae_lambda=model.gae_lambda,
        gamma=model.gamma,
        n_envs=model.n_envs,
    )
    log(f"📊 rollout buffer rebuilt: {buffer_cls.__name__}, n_steps={model.n_steps}, "
        f"n_envs={model.n_envs}")


def _observation_floats(observation_space) -> int:
    """Nombre de flottants d'UNE observation, espace Dict comme espace Box."""
    import gymnasium as gym

    if isinstance(observation_space, gym.spaces.Dict):
        total = 0
        for name, sub in observation_space.spaces.items():
            if sub.shape is None:
                raise ValueError(
                    f"sous-espace d'observation '{name}' sans shape ({type(sub).__name__}) : "
                    "impossible de dimensionner le buffer"
                )
            total += int(np.prod(sub.shape))
        return total
    if observation_space.shape is None:
        raise ValueError(
            f"espace d'observation sans shape ({type(observation_space).__name__}) : "
            "impossible de dimensionner le buffer"
        )
    return int(np.prod(observation_space.shape))


def _available_memory_bytes() -> Optional[int]:
    """MemAvailable de /proc/meminfo, ou None hors Linux (le garde-fou ne mord alors pas)."""
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, IndexError, ValueError):
        return None
    return None


def _resolve_n_envs_for_step_logging(n_envs: int, log=print) -> int:
    """Force un environnement unique quand la journalisation --step est active.

    V11 T6 — root cause d'un no-op SILENCIEUX : `--step` n'a qu'un objet, journaliser les
    actions dans step.log (consomme par `ai/analyzer.py`). Or le StepLogger n'est branche
    QUE sur la branche mono-env (`if step_logger: base_env.step_logger = step_logger`) ;
    les branches vectorisees construisent leurs envs avec `step_logger_enabled=False`.
    Avec `n_envs > 1` (48 dans x1_debug), le run annoncait "Step logging enabled" puis
    n'ecrivait jamais la moindre entree — step.log reduit a son en-tete.

    Meme traitement que `--replay`, qui construit deja son env unique
    (`ai/replay_converter.py`, `training_n_envs=1`) :
    on force ET on le DIT (pas de no-op silencieux, pas de promesse non tenue).
    Le controle `n_envs > 0` vit ici parce que c'est le SEUL passage obligatoire des
    lectures de `training_config["n_envs"]`. Il vivait auparavant dans
    `ai/bot_evaluation.evaluate_against_bots`, ou il n'etait atteint qu'au premier marqueur
    d'evaluation — donc apres des minutes d'entrainement — et ou il ne servait plus qu'a
    alimenter un repli de `bot_eval_n_workers` depuis supprime.
    """
    if not isinstance(n_envs, int) or isinstance(n_envs, bool) or n_envs <= 0:
        raise ValueError(f"training config n_envs must be a positive integer (got {n_envs!r})")
    if step_logger is None or not getattr(step_logger, "enabled", False):
        return n_envs
    if n_envs > 1:
        log(
            f"ℹ️  Step logging (--step): using single environment "
            f"(vectorization disabled, config n_envs={n_envs}) — "
            f"le StepLogger n'est branche que sur le chemin mono-env."
        )
    return 1


def _require_training_config_phase(config, agent_key, training_config_name) -> None:
    """Enforce an explicit --training-config (R1): no silent 'default' alias.

    Raises ValueError listing the available phases when no training-config phase was
    provided. La garde `agent_key and ...` qui encadrait ce controle est tombee avec le mode
    sans agent : `--agent` est desormais exige par argparse, et non vide.
    """
    if training_config_name is None:
        full_cfg = config.load_agent_training_config(agent_key, None)
        available_phases = [k for k in full_cfg.keys() if not str(k).startswith("_")]
        raise ValueError(
            f"--training-config is required (no silent default). "
            f"Available phases for agent '{agent_key}': {available_phases}"
        )


def _list_available_board_refs(ref_kind: str) -> List[str]:
    """List available board refs for walls/objectives from current board directory."""
    if ref_kind not in {"walls", "objectives"}:
        raise ValueError(f"Unsupported ref_kind: {ref_kind}")
    config_loader = get_config_loader()
    board_dir = os.path.join(str(config_loader.get_board_dir()), ref_kind)
    if not os.path.isdir(board_dir):
        raise FileNotFoundError(f"Board {ref_kind} directory not found: {board_dir}")
    pattern = "walls-*.json" if ref_kind == "walls" else "objectives-*.json"
    refs = [os.path.basename(path) for path in sorted(glob.glob(os.path.join(board_dir, pattern)))]
    if len(refs) == 0:
        raise FileNotFoundError(
            f"No {pattern} files found in board {ref_kind} directory: {board_dir}"
        )
    return refs


def _expand_random_ref_weights(
    configured_weights: Dict[str, float],
    ref_kind: str,
    config_key_name: str,
) -> List[Tuple[str, float]]:
    """
    Expand configured random-ref weights to concrete refs.

    Rules:
    - explicit keys (except 'default') target exact refs.
    - 'default' weight is evenly distributed across remaining available refs.
    - returned list is normalized to sum exactly 1.0.
    """
    explicit_weights = {
        key: value for key, value in configured_weights.items() if key != "default"
    }
    default_weight = float(configured_weights.get("default", 0.0))
    available_refs = _list_available_board_refs(ref_kind=ref_kind)

    missing_explicit = [
        ref_name for ref_name in explicit_weights.keys() if ref_name not in available_refs
    ]
    if missing_explicit:
        raise ValueError(
            f"{config_key_name} contains unknown refs for board {ref_kind}: "
            f"{sorted(missing_explicit)}"
        )

    expanded: Dict[str, float] = dict(explicit_weights)
    remaining_refs = [
        ref_name for ref_name in available_refs if ref_name not in explicit_weights
    ]
    if default_weight > 0.0:
        if len(remaining_refs) == 0:
            raise ValueError(
                f"{config_key_name}.default > 0 but no remaining {ref_kind} refs are available"
            )
        per_remaining = default_weight / float(len(remaining_refs))
        for ref_name in remaining_refs:
            expanded[ref_name] = per_remaining

    total = sum(expanded.values())
    if total <= 0.0:
        raise ValueError(f"{config_key_name} expands to zero total weight")
    normalized = [(ref_name, weight / total) for ref_name, weight in sorted(expanded.items())]
    return normalized


def _materialize_scenario_with_refs(
    scenario_path: str,
    wall_ref: Optional[str] = None,
) -> str:
    """Create a temporary scenario copy with an overridden wall_ref and return its path.

    V11 T6 (hygiene) : le parametre 'objectives_ref' a ete purge. Les objectifs ont pour
    source UNIQUE les terrains flagges "objective": true (14.01/14.02) depuis V11 T3/T4 ;
    le moteur REJETTE les cles legacy 'objectives'/'objectives_ref'/'objective_hexes'
    (game_state.py). La branche d'emission etait morte (appelant unique = wall_ref seul)
    et tout futur appelant aurait produit un scenario refuse par le moteur.
    """
    if wall_ref is None:
        return scenario_path
    if not isinstance(wall_ref, str) or not wall_ref.strip():
        raise ValueError(f"Invalid wall_ref override: {wall_ref!r}")
    with open(scenario_path, "r", encoding="utf-8-sig") as f:
        scenario_data = json.load(f)
    if not isinstance(scenario_data, dict):
        raise TypeError(
            f"Scenario JSON must be an object for ref override: {scenario_path}"
        )

    scenario_copy = deepcopy(scenario_data)
    scenario_copy.pop("wall_hexes", None)
    scenario_copy["wall_ref"] = wall_ref.strip()

    temp_root = _get_wall_override_temp_dir()
    source_parts = Path(os.path.abspath(scenario_path)).parts
    if "agents" not in source_parts:
        raise ValueError(
            f"Scenario override requires path containing 'agents': {scenario_path}"
        )
    agents_idx = source_parts.index("agents")
    if agents_idx + 1 >= len(source_parts):
        raise ValueError(f"Cannot resolve agent key from scenario path: {scenario_path}")
    agent_key = source_parts[agents_idx + 1]
    try:
        scenarios_idx = source_parts.index("scenarios", agents_idx + 2)
        split_dir = source_parts[scenarios_idx + 1]
    except (ValueError, IndexError):
        raise ValueError(
            f"Cannot resolve split directory (training/holdout_*) from scenario path: {scenario_path}"
        )
    temp_dir = os.path.join(temp_root, "agents", agent_key, "scenarios", split_dir)
    os.makedirs(temp_dir, exist_ok=True)
    hash_payload = f"{os.path.abspath(scenario_path)}|{wall_ref}"
    path_hash = hashlib.sha1(hash_payload.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    file_name = f"{Path(scenario_path).stem}__{path_hash}.json"
    out_path = os.path.join(temp_dir, file_name)
    if not os.path.exists(out_path):
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(scenario_copy, f, ensure_ascii=True, indent=2)
    return out_path


def _apply_wall_ref_weighting(
    scenario_list: List[str],
    training_config: Dict[str, Any],
) -> List[str]:
    """
    Apply optional per-wall_ref weighting from training config.

    Config format:
      scenario_sampling:
        train_wall_ref_weights:
          "walls-11.json": 0.3
          "walls-21.json": 0.3
          "walls-31.json": 0.3
          "default": 0.1
    """
    sampling_cfg = training_config.get("scenario_sampling")
    if sampling_cfg is None:
        return scenario_list
    if not isinstance(sampling_cfg, dict):
        raise TypeError(
            f"scenario_sampling must be an object in training config "
            f"(got {type(sampling_cfg).__name__})"
        )

    raw_weights = sampling_cfg.get("train_wall_ref_weights")
    raw_multipliers = sampling_cfg.get("train_wall_ref_multipliers")
    if raw_weights is None and raw_multipliers is None:
        return scenario_list
    if raw_weights is not None and raw_multipliers is not None:
        raise ValueError(
            "Use only one of scenario_sampling.train_wall_ref_weights or "
            "scenario_sampling.train_wall_ref_multipliers"
        )

    wall_ref_weights: Dict[str, float] = {}
    if raw_weights is not None:
        if not isinstance(raw_weights, dict):
            raise TypeError(
                "scenario_sampling.train_wall_ref_weights must be an object "
                f"(got {type(raw_weights).__name__})"
            )
        if len(raw_weights) == 0:
            raise ValueError("scenario_sampling.train_wall_ref_weights cannot be empty")
        for wall_ref, weight_raw in raw_weights.items():
            if not isinstance(wall_ref, str) or not wall_ref.strip():
                raise ValueError(
                    "scenario_sampling.train_wall_ref_weights keys must be non-empty strings"
                )
            if not isinstance(weight_raw, (int, float)):
                raise TypeError(
                    f"Weight for wall_ref '{wall_ref}' must be numeric "
                    f"(got {type(weight_raw).__name__})"
                )
            weight = float(weight_raw)
            if wall_ref.strip() == "default":
                if weight < 0.0:
                    raise ValueError("Weight for wall_ref 'default' must be >= 0")
            else:
                if weight <= 0.0:
                    raise ValueError(f"Weight for wall_ref '{wall_ref}' must be > 0")
            wall_ref_weights[wall_ref.strip()] = weight
        if "default" not in wall_ref_weights:
            raise KeyError(
                "scenario_sampling.train_wall_ref_weights must define a 'default' weight"
            )
        weight_sum = sum(wall_ref_weights.values())
        if abs(weight_sum - 1.0) > 1e-9:
            raise ValueError(
                "scenario_sampling.train_wall_ref_weights must sum to 1.0 "
                f"(got {weight_sum:.12f})"
            )
    else:
        if not isinstance(raw_multipliers, dict):
            raise TypeError(
                "scenario_sampling.train_wall_ref_multipliers must be an object "
                f"(got {type(raw_multipliers).__name__})"
            )
        if len(raw_multipliers) == 0:
            raise ValueError("scenario_sampling.train_wall_ref_multipliers cannot be empty")

        default_multiplier = raw_multipliers.get("default", 1)
        if not isinstance(default_multiplier, int):
            raise TypeError(
                "scenario_sampling.train_wall_ref_multipliers['default'] must be integer "
                f"(got {type(default_multiplier).__name__})"
            )
        if default_multiplier < 1:
            raise ValueError(
                "scenario_sampling.train_wall_ref_multipliers['default'] must be >= 1"
            )

        multipliers: Dict[str, int] = {}
        for wall_ref, multiplier_raw in raw_multipliers.items():
            if wall_ref == "default":
                continue
            if not isinstance(wall_ref, str) or not wall_ref.strip():
                raise ValueError(
                    "scenario_sampling.train_wall_ref_multipliers keys must be non-empty strings"
                )
            if not isinstance(multiplier_raw, int):
                raise TypeError(
                    f"Multiplier for wall_ref '{wall_ref}' must be integer "
                    f"(got {type(multiplier_raw).__name__})"
                )
            if multiplier_raw < 1:
                raise ValueError(f"Multiplier for wall_ref '{wall_ref}' must be >= 1")
            multipliers[wall_ref.strip()] = int(multiplier_raw)

        total_multiplier = float(default_multiplier + sum(multipliers.values()))
        wall_ref_weights["default"] = float(default_multiplier) / total_multiplier
        for wall_ref, mult in multipliers.items():
            wall_ref_weights[wall_ref] = float(mult) / total_multiplier

    scenario_counts: Dict[str, int] = {}
    for scenario_path in scenario_list:
        if scenario_path not in scenario_counts:
            scenario_counts[scenario_path] = 0
        scenario_counts[scenario_path] += 1

    per_scenario_scale = 10
    weighted_scenario_list: List[str] = []
    for scenario_path, base_count in sorted(scenario_counts.items(), key=lambda item: item[0]):
        original_wall_ref = _load_scenario_wall_ref(scenario_path)
        units_total = base_count * per_scenario_scale
        if units_total <= 0:
            continue

        if original_wall_ref == "random":
            wall_weight_items = _expand_random_ref_weights(
                configured_weights=wall_ref_weights,
                ref_kind="walls",
                config_key_name="scenario_sampling.train_wall_ref_weights",
            )
        else:
            wall_weight_items = sorted(wall_ref_weights.items(), key=lambda item: item[0])

        provisional: List[Tuple[str, int, float]] = []
        assigned = 0
        for wall_key, wall_weight in wall_weight_items:
            exact = float(wall_weight) * float(units_total)
            count = int(exact)
            assigned += count
            provisional.append((wall_key, count, exact - float(count)))

        remainder = units_total - assigned
        if remainder > 0:
            provisional.sort(key=lambda item: item[2], reverse=True)
            for i in range(remainder):
                wall_key, count, frac = provisional[i % len(provisional)]
                provisional[i % len(provisional)] = (wall_key, count + 1, frac)

        for wall_key, count, _ in provisional:
            if count <= 0:
                continue
            effective_wall_ref = original_wall_ref if wall_key == "default" else wall_key
            weighted_path = _materialize_scenario_with_refs(
                scenario_path=scenario_path,
                wall_ref=effective_wall_ref if effective_wall_ref != original_wall_ref else None,
            )
            weighted_scenario_list.extend([weighted_path] * count)

    if len(weighted_scenario_list) == 0:
        raise ValueError("Wall-ref weighting produced an empty weighted scenario list")
    return weighted_scenario_list


def _load_rule_checker_scenarios(project_root_path: str, agent_key: str) -> List[str]:
    """Regenere les scenarios rule-checker et rend leurs chemins.

    GENERES A CHAQUE LANCEMENT, jamais lus d'un depot : leur nombre est le CARRE du nombre de
    types d'unites a regle implementee (18 types -> 324 fichiers en mars 2026, 52 -> 2704), et ils
    derivent entierement des `RULES_STATUS` des rosters. Les versionner faisait pourrir des
    milliers d'artefacts derives, devenus illisibles par le moteur sans que rien ne le dise. Le
    dossier produit est ignore par git.
    """
    from shared import rule_checker_scenarios

    # Les trois controles qui vivaient ici (fichiers presents, doublons, liste vide) validaient un
    # MANIFESTE versionne, qui pouvait mentir. Ils n'ont plus d'objet face a un generateur : il
    # vient d'ecrire ces fichiers et rend leurs chemins, `write_text` leve si l'ecriture echoue,
    # les noms sont uniques par `enumerate`, et `select_units` leve deja quand la selection est
    # vide. Les garder faisait 2704 `os.path.isfile` sur ce qu'on venait d'ecrire.
    root = pathlib.Path(project_root_path)
    # Les parametres de la DERNIERE generation, jamais des defauts en dur : sinon un jeu produit a
    # 500pts par scripts/roster_matchup_stats.py serait double d'un jeu 100pts, et l'entrainement
    # tournerait sur un autre plateau que celui demande, sans un mot.
    params = rule_checker_scenarios.resolve_params(root)
    print(
        f"🧪 Rule-checker: {params.scale} / {params.board_ref} / {params.terrain_ref} "
        "(parametres de la derniere generation)"
    )
    return sorted(rule_checker_scenarios.generate(root, agent_key=agent_key, params=params))


# Multi-agent orchestration imports
from config_loader import get_config_loader, get_max_turns
import torch

# Use TF32 for faster matmul on Ampere+ GPUs (RTX 30xx, 40xx, A100, etc.)
if hasattr(torch, "set_float32_matmul_precision"):
    torch.set_float32_matmul_precision("high")


def build_agent_model_path(models_root: str, agent_key: str) -> str:
    """Build model path from models root and agent key.

    Inter-faction keys are resolved to the configured storage key to keep
    model loading/saving aligned with selected source agents during migration.
    """
    config_loader = get_config_loader()
    model_storage_key = config_loader._resolve_agent_config_key(agent_key)
    return os.path.join(models_root, model_storage_key, f"model_{model_storage_key}.zip")
import time  # Add time import for StepLogger timestamps

#: Artefacts CANONIQUES d'un run : ceux qui portent un nom FIXE et qu'un run suivant ecraserait
#: (ou lirait comme une reference). Les sauvegardes horodatees et les modeles nommes avec leur
#: score (`<agent>_<seed>_robust_<score>.zip`) n'en font PAS partie : leur nom est unique, ils
#: sont l'historique et doivent rester en place.
def canonical_run_artifacts(model_path: str) -> list:
    """Chemins des artefacts a nom FIXE d'un run, pour `model_path` = le modele canonique."""
    model_dir = os.path.dirname(model_path)
    stem = os.path.splitext(os.path.basename(model_path))[0]

    return [
        model_path,                                              # model_<agent>.zip
        *model_companion_paths(model_path),                      # ..._vec_normalize.pkl, ..._run_state.json
        os.path.join(model_dir, f"{stem}_robust_meta.json"),     # seuil du score robuste
        os.path.join(model_dir, "best_model.zip"),               # meilleur modele SB3 du run
    ]


def archive_canonical_artifacts_for_new_run(model_path: str, log_fn=print) -> list:
    """`--new` : ECARTE les artefacts canoniques du run precedent au lieu de les ecraser.

    Deux raisons distinctes, toutes deux constatees en production (V11 §0.36) :

    1. `model_<agent>_robust_meta.json` est lu par `BotEvaluationCallback` comme un SEUIL
       (`_read_canonical_robust_score` : le modele canonique n'est mis a jour que si le nouveau
       score robuste le depasse). Laisse en place, il impose au run NEUF de battre le score d'un
       run precedent — mesure sur un autre modele, parfois sur un run avorte. Constate : un run
       relance a du battre `0.457372` herite d'un run mort au marqueur 24 000.
    2. `model_<agent>.zip` et `best_model.zip` sont ECRASES en silence par le run neuf. L'agent
       precedent disparait sans trace, alors que c'est le seul artefact servi au PvE.

    Renommage horodate `<stem>_<AAAAMMJJ-HHMM><ext>`, jamais une suppression : c'est l'agent de
    l'utilisateur. Idempotent — un artefact absent n'est pas une erreur, et un second appel dans
    le meme run ne fait rien (les fichiers ont deja ete deplaces).

    ⚠️ Cette fonction RENOMME des `.zip` de `ai/models/`, ce que le projet interdit par defaut.
    C'est une exception DEMANDEE explicitement par l'utilisateur (2026-07-28), et elle ne
    supprime rien : elle empeche precisement l'ecrasement silencieux que la regle protege.
    """
    stamp = time.strftime("%Y%m%d-%H%M")
    moved = []
    for path in canonical_run_artifacts(model_path):
        if not os.path.exists(path):
            continue
        stem, ext = os.path.splitext(path)
        archived = f"{stem}_{stamp}{ext}"
        if os.path.exists(archived):
            raise FileExistsError(
                f"archive_canonical_artifacts_for_new_run: {archived} existe deja — "
                f"deux runs --new dans la meme minute, l'archivage ecraserait une sauvegarde."
            )
        os.rename(path, archived)
        moved.append(archived)
    if moved:
        log_fn(f"📦 --new : {len(moved)} artefact(s) du run precedent archive(s) :")
        for path in moved:
            log_fn(f"   {os.path.basename(path)}")
    return moved


def prepare_run_artifacts(
    models_root: str,
    agent_key: Any,
    new_model: bool,
    append_training: bool,
    n_envs: int,
    log_fn=print,
) -> Tuple[str, int, int]:
    """Prologue commun des chemins d'entrainement : ou ecrit ce run, et d'ou il repart.

    Rend `(model_path, episode_offset, episode_start_index)`. Ce prologue etait recopie sur
    chaque chemin, avec des divergences deja constatees : un `os.makedirs` place dans le `if
    new_model` (donc jamais execute sur un `--append`), un `os.makedirs` en triple exemplaire,
    et l'annonce de reprise conditionnee tantot par `append_training`, tantot par l'offset.

    `--new` GAGNE SUR `--append`. Les deux drapeaux sont des `store_true` independants et rien
    ne les rend exclusifs : sans cette regle, `--new --append` faisait demarrer un modele NEUF
    sur le compte d'episodes de l'ancien — rampe de deploiement a `active_ratio_end` pour des
    poids initialises au hasard. Elle est appliquee ICI, sur l'argument passe a
    `resume_episode_offset`, et non par l'ordre des deux appels : un ordre ne se verifie pas,
    il se re-casse au refactor suivant.
    """
    model_path = build_agent_model_path(models_root, require_present(agent_key, "agent_key"))
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    if new_model:
        archive_canonical_artifacts_for_new_run(model_path, log_fn)

    episode_offset = resume_episode_offset(model_path, append_training and not new_model)
    if episode_offset > 0:
        log_fn(f"⏱️  Reprise : {episode_offset} episodes deja joues (rampes reprises a ce point)")
    # Index de depart PAR ENVIRONNEMENT : le compteur d'un worker est local (episode_schedule.py).
    episode_start_index = episodes_per_env(episode_offset, n_envs) if episode_offset > 0 else 0
    return model_path, episode_offset, episode_start_index

from tqdm import tqdm  # For episode progress bar
import gymnasium as gym  # For SelfPlayWrapper to inherit from gym.Wrapper

# Environment wrappers (extracted to ai/env_wrappers.py)
from ai.env_wrappers import BotControlledEnv, SelfPlayWrapper


# Step logger (extracted to ai/step_logger.py)
from ai.step_logger import StepLogger

# Bot evaluation (extracted to ai/bot_evaluation.py)
from ai.bot_evaluation import ROSTER_SIDES, evaluate_against_bots

# Training callbacks (extracted to ai/training_callbacks.py)
from ai.bot_registry import ALL_BOT_KEYS
from ai.training_callbacks import (
    iter_bot_score_rows,
    LearningRateScheduleCallback,
    EntropyScheduleCallback,
    EpisodeTerminationCallback,
    MetricsCollectionCallback,
    BotEvaluationCallback,
    selection_worst_bot,
)

# Training utilities (extracted to ai/training_utils.py)
from ai.training_utils import (
    build_self_play_kwargs,
    self_play_is_enabled,
    check_gpu_availability,
    benchmark_device_speed,
    setup_imports,
    make_training_env,
    get_agent_scenario_file,
    get_scenario_list_for_phase,
    describe_expected_bot_self_scenario_files,
)
from ai.vec_normalize_utils import (
    save_vec_normalize,
    load_vec_normalize,
    get_vec_normalize_path,
)

from engine.episode_schedule import episodes_per_env
from ai.model_artifacts import model_companion_paths, remove_model_with_companions
from ai.run_state import get_run_state_path, load_run_state, save_run_state
from ai.truncation_log import TruncationLog, agent_log_dir
from shared.data_validation import (
    require_key,
    require_non_negative_int,
    require_positive_int,
    require_present,
)
from shared.torch_safe_globals import register_torch_safe_globals

# Avant tout `MaskablePPO.load` de ce module : torch >= 2.6 charge en `weights_only=True`.
register_torch_safe_globals()

_progress_bar_width_cache: Optional[Dict[str, int]] = None
_wall_override_temp_dir: Optional[str] = None


def _cleanup_wall_override_temp_dir() -> None:
    """Remove temporary directory used for wall-ref scenario overrides."""
    global _wall_override_temp_dir
    if _wall_override_temp_dir and os.path.isdir(_wall_override_temp_dir):
        shutil.rmtree(_wall_override_temp_dir, ignore_errors=True)
    _wall_override_temp_dir = None


def _get_wall_override_temp_dir() -> str:
    """Create (once) and return temporary directory for wall-ref scenario overrides.

    JUMEAU du répertoire d'éval : sous la racine du dépôt (cf. `ai.scenario_scratch`), pour la
    même raison — un scénario matérialisé dans `/tmp` fait refuser l'épisode par le moteur dès
    que le step logging est actif, son chemin n'étant pas journalisable pour le replay."""
    global _wall_override_temp_dir
    if _wall_override_temp_dir is None:
        from ai.scenario_scratch import make_scenario_scratch_dir
        # Pas d'`atexit` : cf. `ai.scenario_scratch`, le replay lit ce fichier après le run.
        _wall_override_temp_dir = make_scenario_scratch_dir("w40k_wallmix_")
    return _wall_override_temp_dir


def _get_progress_bar_width(config_key: str) -> int:
    """Load and validate progress bar width from config/config.json."""
    global _progress_bar_width_cache
    if _progress_bar_width_cache is None:
        config_loader = get_config_loader()
        global_config = config_loader.load_config("config", force_reload=False)
        progress_bar_cfg = require_key(global_config, "progress_bar")
        validated_widths: Dict[str, int] = {}
        for key in (
            "training_width",
            "bot_eval_width",
        ):
            width = require_key(progress_bar_cfg, key)
            if not isinstance(width, int) or isinstance(width, bool):
                raise TypeError(
                    f"config.progress_bar.{key} must be an integer "
                    f"(got {type(width).__name__})"
                )
            if width <= 0:
                raise ValueError(
                    f"config.progress_bar.{key} must be > 0 (got {width})"
                )
            validated_widths[key] = width
        _progress_bar_width_cache = validated_widths
    return require_key(_progress_bar_width_cache, config_key)


def _get_tensorboard_run_meta_path(model_path: str) -> str:
    """Return sidecar metadata path storing active TensorBoard run directory."""
    return f"{model_path}.tb_run.json"


def _read_tensorboard_run_meta(model_path: str) -> Dict[str, Any]:
    """Read TensorBoard run metadata from model sidecar file."""
    meta_path = _get_tensorboard_run_meta_path(model_path)
    if not os.path.exists(meta_path):
        raise FileNotFoundError(
            f"TensorBoard run metadata not found: {meta_path}. "
            "Run with --new once to initialize run tracking before --append."
        )
    with open(meta_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    if not isinstance(metadata, dict):
        raise TypeError(f"Invalid TensorBoard metadata format in {meta_path}: expected object")
    return metadata


def _write_tensorboard_run_meta(model_path: str, run_dir: str) -> None:
    """Persist active TensorBoard run directory alongside model path."""
    meta_path = _get_tensorboard_run_meta_path(model_path)
    model_dir = os.path.dirname(model_path)
    if model_dir:
        os.makedirs(model_dir, exist_ok=True)
    payload = {"run_dir": run_dir}
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


class VecNormalizeCheckpointCallback(CheckpointCallback):
    """Checkpoint periodique qui ecrit AUSSI les stats VecNormalize du checkpoint.

    Sans ce pkl jumeau un `ppo_checkpoint_*_steps.zip` est INEXPLOITABLE pour reprendre un
    entrainement : la reprise exige `<stem>_vec_normalize.pkl` (V11 §0.35) et echoue
    explicitement s'il manque — le seul artefact reprenable etait le `_interrupted` du Ctrl-C.
    `save_vecnormalize=True` de SB3 ne convient pas : il ecrit
    `<prefix>_vecnormalize_<n>_steps.pkl`, un nom que `get_vec_normalize_path` ne resout pas.
    """

    #: Compteur d'episodes GLOBAL, pose apres construction — le tracker de metriques n'existe pas
    #: encore quand les callbacks sont crees. Meme convention que `BotEvaluationCallback`.
    metrics_tracker: Any = None

    def _on_step(self) -> bool:
        continue_training = super()._on_step()
        if self.save_freq > 0 and self.n_calls % self.save_freq == 0:
            if self.metrics_tracker is None:
                raise RuntimeError(
                    "VecNormalizeCheckpointCallback.metrics_tracker absent : un checkpoint sans "
                    "son compte d'episodes n'est pas reprenable (cf. ai/run_state.py)."
                )
            checkpoint_path = self._checkpoint_path(extension="zip")
            save_vec_normalize(self.model.get_env(), checkpoint_path)
            save_run_state(checkpoint_path, int(self.metrics_tracker.episode_count))
        return continue_training


class RotatingCheckpointCallback(VecNormalizeCheckpointCallback):
    """Checkpoint callback that keeps only the most recent N checkpoints."""

    def __init__(self, max_checkpoints: int, **kwargs):
        super().__init__(**kwargs)
        self.max_checkpoints = max_checkpoints

    def _cleanup_old_checkpoints(self) -> None:
        pattern = os.path.join(self.save_path, f"{self.name_prefix}_*_steps.zip")
        # Tri sur le NOMBRE DE PAS, pas sur mtime : plusieurs checkpoints ecrits dans la meme
        # granularite d'horloge se departageraient arbitrairement, et c'est bien le plus ancien
        # en pas — pas en date de fichier — qu'il faut retirer.
        checkpoint_files = sorted(
            glob.glob(pattern),
            key=lambda p: int(os.path.basename(p)[len(self.name_prefix) + 1:-len("_steps.zip")]),
            reverse=True,
        )
        for old_checkpoint in checkpoint_files[self.max_checkpoints:]:
            # Les compagnons partent AVEC leur zip : un orphelin serait relu par un futur
            # checkpoint de meme nom (cf. ai/model_artifacts.py).
            remove_model_with_companions(old_checkpoint)

    def _on_step(self) -> bool:
        continue_training = super()._on_step()
        if self.save_freq > 0 and self.n_calls % self.save_freq == 0:
            self._cleanup_old_checkpoints()
        return continue_training


def _promote_checkpoint_for_resume(
    checkpoint_path: str, agent_key: str, config_loader: Any, log_fn=print
) -> str:
    """`--resume-from` : installe un checkpoint au chemin CANONIQUE du modele, puis rend la main.

    `--append` recharge toujours `model_<agent>.zip` (il n'existe pas de chemin de modele
    parametrable pour l'entrainement) : reprendre depuis un checkpoint consiste donc a l'y
    installer AVEC ses stats VecNormalize. Leur absence est une erreur explicite, jamais un
    repli sur les stats d'un autre modele : ce serait un decalage muet de normalisation
    (V11 §0.35).

    Le modele canonique deja en place est ECARTE, pas ecrase (meme principe que `--new`), et le
    run TensorBoard est remis a neuf : un checkpoint est un point ANTERIEUR, prolonger le run qui
    l'a produit ferait reculer les steps dans les courbes.
    """
    if not agent_key:
        raise ValueError("--resume-from exige --agent (chemin du modele canonique inconnu sinon)")
    if not os.path.exists(checkpoint_path):
        raise FileNotFoundError(f"--resume-from : checkpoint introuvable : {checkpoint_path}")
    checkpoint_vec_path = get_vec_normalize_path(checkpoint_path)
    if not os.path.exists(checkpoint_vec_path):
        raise FileNotFoundError(
            f"--resume-from : stats VecNormalize absentes pour ce checkpoint : "
            f"{checkpoint_vec_path}. Les checkpoints ecrits avant que le callback ne sauve ses "
            f"stats n'en ont pas : ils ne sont pas reprenables."
        )

    checkpoint_run_state = get_run_state_path(checkpoint_path)
    if not os.path.exists(checkpoint_run_state):
        raise FileNotFoundError(
            f"--resume-from : etat de run absent pour ce checkpoint : {checkpoint_run_state}. "
            f"Les checkpoints ecrits avant ce mecanisme n'ont pas leur compte d'episodes : "
            f"les reprendre relancerait la rampe de deploiement depuis `active_ratio_start` et "
            f"repartirait le compte d'episodes de zero (cf. ai/run_state.py). Repartir avec --new."
        )

    model_path = build_agent_model_path(config_loader.get_models_root(), agent_key)
    if os.path.abspath(checkpoint_path) == os.path.abspath(model_path):
        raise ValueError(
            f"--resume-from : le checkpoint EST deja le modele canonique ({model_path}). "
            f"Utiliser --append seul."
        )
    os.makedirs(os.path.dirname(model_path), exist_ok=True)

    if os.path.exists(model_path):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        stem = os.path.splitext(model_path)[0]
        set_aside = f"{stem}_pre_resume_{stamp}.zip"
        shutil.move(model_path, set_aside)
        # Les compagnons suivent le modele ecarte : restes en place, ils seraient lus comme ceux
        # du modele installe a sa place (cf. ai/model_artifacts.py).
        for previous, archived in zip(model_companion_paths(model_path), model_companion_paths(set_aside)):
            if os.path.exists(previous):
                shutil.move(previous, archived)
        log_fn(f"📦 --resume-from : modele canonique precedent ecarte -> {stem}_pre_resume_{stamp}.zip")

    shutil.copy2(checkpoint_path, model_path)
    shutil.copy2(checkpoint_vec_path, get_vec_normalize_path(model_path))
    shutil.copy2(checkpoint_run_state, get_run_state_path(model_path))

    _write_tensorboard_run_meta(model_path, "")
    log_fn(f"♻️  --resume-from : {os.path.basename(checkpoint_path)} installe en {model_path}")
    return model_path


def _resolve_tensorboard_run_dir(
    base_log_root: str,
    training_config_name: str,
    agent_key: str,
    model_path: str,
    new_model: bool,
    append_training: bool,
) -> Tuple[str, str]:
    """Resolve experiment/run directories based on --new/--append semantics."""
    experiment_dir = os.path.join(base_log_root, f"{training_config_name}_{agent_key}")
    os.makedirs(experiment_dir, exist_ok=True)

    if append_training and not new_model:
        meta = _read_tensorboard_run_meta(model_path)
        existing_run_dir = meta.get("run_dir") if meta else None
        if existing_run_dir and os.path.isdir(existing_run_dir):
            return experiment_dir, existing_run_dir

    if append_training:
        run_id = time.strftime("%Y%m%d-%H%M%S")
        run_dir = os.path.join(experiment_dir, f"run_{run_id}")
        os.makedirs(run_dir, exist_ok=True)
        _write_tensorboard_run_meta(model_path, run_dir)
        return experiment_dir, run_dir

    # --new (or implicit non-append training) creates an isolated run directory.
    run_id = time.strftime("%Y%m%d-%H%M%S")
    run_dir = os.path.join(experiment_dir, f"run_{run_id}")
    os.makedirs(run_dir, exist_ok=True)
    _write_tensorboard_run_meta(model_path, run_dir)
    return experiment_dir, run_dir


def _apply_torch_compile(model) -> None:
    """Wrap policy.forward to move action_masks to model device (GPU or CPU), then apply torch.compile on CUDA.
    CUDA graphs require all inputs on GPU; action_masks from env are numpy (CPU)."""
    policy = getattr(model, "policy", None)
    if policy is None:
        return
    device = getattr(model, "device", None)
    if device is None:
        return
    original_forward = policy.forward
    # Only compile when on CUDA and compile_mode is enabled (not null/"off")
    on_cuda = str(device).startswith("cuda")
    compile_mode = _torch_compile_mode
    inner_forward = (
        torch.compile(original_forward, mode=compile_mode) if (on_cuda and compile_mode) else original_forward
    )

    def _forward_with_device_masks(obs, deterministic=False, action_masks=None):
        if action_masks is not None:
            action_masks = torch.as_tensor(action_masks, device=device, dtype=torch.bool)
        return inner_forward(obs, deterministic=deterministic, action_masks=action_masks)

    policy.forward = _forward_with_device_masks


# Aliases for --param: short keys map to nested config paths (or stay as-is for root keys)
_PARAM_ALIASES = {
    "n_steps": "model_params.n_steps",
    "batch_size": "model_params.batch_size",
    "n_epochs": "model_params.n_epochs",
    "learning_rate": "model_params.learning_rate",
    "gamma": "model_params.gamma",
    "gae_lambda": "model_params.gae_lambda",
    "clip_range": "model_params.clip_range",
    "ent_coef": "model_params.ent_coef",
    "vf_coef": "model_params.vf_coef",
    # Seat-aware training keys
    "seed": "agent_seat_seed",
    # Root-level keys (no mapping needed, but listed for clarity)
    "n_envs": "n_envs",
    "total_episodes": "total_episodes",
}


def _parse_param_value(value: str) -> Any:
    """Parse --param VALUE string to int, float, bool, or str."""
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return value


def _apply_param_overrides(config: dict, overrides: Optional[List[List[str]]], log_overrides: bool = True) -> None:
    """Apply --param key value overrides to config in-place.
    Key can use dot notation (e.g. model_params.n_steps) or short aliases (e.g. n_steps).
    """
    if not overrides:
        return
    for key, value in overrides:
        path = _PARAM_ALIASES.get(key, key)
        keys = path.split(".")
        v = _parse_param_value(value)
        d = config
        for k in keys[:-1]:
            if k not in d:
                d[k] = {}
            d = d[k]
        d[keys[-1]] = v
        if log_overrides:
            print(f"   ⚙️  Override: {path} = {v}")

# Replay converter (extracted to ai/replay_converter.py)
from ai.replay_converter import (
    resolve_agent_bot_scenario,
    convert_steplog_to_replay,
    generate_steplog_and_replay,
    parse_steplog_file,
    parse_action_message,
    calculate_episode_reward_from_actions,
    convert_to_replay_format
)



# Global step logger instance
step_logger = None

def _read_device_benchmark_cache(agent_key: str, training_config: str, rewards_config: str) -> Optional[Tuple[str, bool]]:
    """Read cached device recommendation from scripts/benchmark_device.py --save-result."""
    cache_path = os.path.join(project_root, "config", ".device_benchmark.json")
    if not os.path.isfile(cache_path):
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
        if (cache.get("agent") == agent_key
                and cache.get("training_config") == training_config
                and cache.get("rewards_config") == rewards_config):
            rec = cache.get("recommendation", "").upper()
            if rec == "GPU":
                return ("cuda", True)
            if rec == "CPU":
                return ("cpu", False)
    except (json.JSONDecodeError, OSError):
        pass
    return None


def resolve_device_mode(device_mode: Optional[str], gpu_available: bool, total_params: int,
                       obs_size: Optional[int] = None, net_arch: Optional[List[int]] = None,
                       cache_key: Optional[Tuple[str, str, str]] = None) -> Tuple[str, bool]:
    """
    Resolve device selection for training.

    Args:
        device_mode: "CPU", "GPU", or None to auto-select.
        gpu_available: Whether CUDA GPU is available.
        total_params: Sum of network hidden units (heuristic estimate when net_arch not available).
        obs_size: Observation size for benchmark (optional).
        net_arch: Network architecture for benchmark (optional).
        cache_key: Optional (agent_key, training_config, rewards_config) to use cached benchmark result.

    Returns:
        Tuple of (device, use_gpu).
    """
    if device_mode is None:
        if cache_key and gpu_available:
            cached = _read_device_benchmark_cache(cache_key[0], cache_key[1], cache_key[2])
            if cached is not None:
                print(f"📊 Device: using cached benchmark result ({cached[0].upper()})")
                return cached
        if gpu_available and obs_size is not None and net_arch is not None:
            result = benchmark_device_speed(obs_size, net_arch)
            if result is not None:
                return result
        use_gpu = gpu_available and (total_params > 2000)
        return ("cuda" if use_gpu else "cpu"), use_gpu

    mode = str(device_mode).upper()
    if mode not in ["CPU", "GPU"]:
        raise ValueError(f"Invalid --mode value: {device_mode}. Expected CPU or GPU.")
    if mode == "GPU":
        if not gpu_available:
            raise ValueError("GPU mode requested but no CUDA GPU available")
        return "cuda", True
    return "cpu", False


def _is_dict_obs_space(observation_space) -> bool:
    """True si l'obs est le Dict de tenseurs d'entites du pipeline squad spatial."""
    return isinstance(observation_space, gym.spaces.Dict)


def _vec_norm_obs_keys(observation_space):
    """Cles a normaliser par VecNormalize.

    Obs Dict : normaliser UNIQUEMENT "global_cont" (V11 §9.5 + §0.30 T-D).
    - "global_cont" porte des grandeurs BRUTES qui n'appartiennent a aucune entite (tour,
      points de mission, force d'usure) : c'est exactement ce que la running mean/var de
      VecNormalize doit mettre a l'echelle — d'ou l'absence de division manuelle dans
      l'observation. C'est une cle SINGLETON : aucun partage de poids n'est en jeu.
    - Les cles d'ENTITES ("allies_*", "enemies_*", "self_models_*") en sont EXCLUES :
      VecNormalize normalise element par element, donc chaque slot aurait ses propres
      statistiques et le meme encodeur partage verrait des echelles differentes selon le slot —
      ce qui annulerait le partage de poids. Elles sont normalisees DANS l'extracteur, par une
      statistique commune a tous les slots (`EntityRunningNorm`, ai/spatial_extractor.py).
    - Les cles "_bin" portent des valeurs discretes (drapeaux 0/1, phase, controle d'objectif
      dans {-1,0,1}) : les recentrer/reduire detruirait leur semantique.
    - "grid" porte des canaux deja dans [0,1] : la normaliser detruirait sa semantique et son
      creux (spec T1b).
    Obs Box : comportement historique (None = tout).
    """
    return ["global_cont"] if _is_dict_obs_space(observation_space) else None


def _apply_vec_normalize(env, model_path_for_vn, vec_norm_cfg, new_model, n_envs, log_fn):
    """Enveloppe `env` dans VecNormalize (charge les stats du checkpoint ou en cree de neuves).

    Ne charge l'ancienne VecNormalize que si elle sera reellement reutilisee. Sur un retrain
    from-scratch (new_model) ou un reset de curriculum, le .pkl est ecarte de toute facon ;
    le charger planterait sur le shape check de set_venv des que l'obs space a change
    (ex: passage Box(108) -> Dict), sans raison metier.

    Retourne l'env enveloppe. Factorise les 2 sites identiques (create_multi_agent_model,
    rotation de scenario).
    """
    if n_envs == 1:
        env = DummyVecEnv([cast(Any, lambda: env)])
    reset_vec_normalize = vec_norm_cfg.get("reset_on_curriculum", False)
    vec_norm_loaded = (
        load_vec_normalize(env, model_path_for_vn)
        if not new_model and not reset_vec_normalize
        else None
    )
    if vec_norm_loaded is not None:
        env = vec_norm_loaded
        env.training = True
        env.norm_reward = vec_norm_cfg.get("norm_reward", True)
        log_fn("✅ VecNormalize: loaded stats from checkpoint")
    elif not new_model and not reset_vec_normalize:
        # Reprise (--step) SANS stats sur disque : creer des stats neuves en silence ferait
        # continuer un modele entraine normalise sur une distribution recalee de zero — un
        # decalage muet, la classe de bug V11 §0.35. L'absence est une erreur explicite.
        expected_path = get_vec_normalize_path(model_path_for_vn)
        legacy_path = os.path.join(os.path.dirname(model_path_for_vn), "vec_normalize.pkl")
        legacy_hint = (
            f" Un pkl LEGACY partagé existe ({legacy_path}) : il peut appartenir à un AUTRE "
            f"modèle du dossier — le renommer en '{os.path.basename(expected_path)}' "
            f"explicitement si ces stats sont bien celles de ce modèle."
            if os.path.exists(legacy_path)
            else ""
        )
        raise FileNotFoundError(
            f"VecNormalize: reprise d'entraînement demandée mais stats absentes : "
            f"{expected_path}.{legacy_hint} Sinon, relancer avec --new (from scratch) ou "
            f"reset_on_curriculum."
        )
    else:
        env = VecNormalize(
            cast(Any, env),
            norm_obs=vec_norm_cfg.get("norm_obs", True),
            norm_reward=vec_norm_cfg.get("norm_reward", True),
            clip_obs=vec_norm_cfg.get("clip_obs", 10.0),
            clip_reward=vec_norm_cfg.get("clip_reward", 10.0),
            gamma=vec_norm_cfg.get("gamma", 0.99),
            norm_obs_keys=_vec_norm_obs_keys(env.observation_space),
        )
        log_fn("✅ VecNormalize: enabled (obs + reward normalization)")
    return env


def _inject_spatial_extractor(model_params) -> None:
    """Branche l'extracteur d'entites ET la tete pointeur sur l'obs Dict.

    Ni un extracteur ni une classe de policy ne se declarent en JSON (ce sont des classes) :
    elles sont injectees ici.
    - `SpatialCombinedExtractor` : le defaut `CombinedExtractor` aplatirait la grille (7 canaux
      -> non reconnue comme image) et traiterait les tenseurs d'entites comme un vecteur plat,
      exactement ce que la refonte supprime.
    - `PointerMaskablePolicy` (V11 §0.30 T-E) : les logits de tir viennent d'un produit scalaire
      requete x embedding d'ennemi. Le `"policy"` du JSON ("MultiInputPolicy") est donc REMPLACE
      — la valeur JSON reste la documentation du type d'obs attendu.

    `cnn_features` est un hyperparametre : il DOIT venir du JSON de l'agent
    (`policy_kwargs.features_extractor_kwargs.cnn_features`) — sb3 transmet ces kwargs au
    constructeur de l'extracteur. Absence = erreur explicite, jamais de valeur par defaut.
    """
    from ai.pointer_policy import PointerMaskablePolicy
    from ai.spatial_extractor import SpatialCombinedExtractor

    policy_kwargs = require_key(model_params, "policy_kwargs")
    fx_kwargs = require_key(policy_kwargs, "features_extractor_kwargs")
    require_key(fx_kwargs, "cnn_features")
    policy_kwargs["features_extractor_class"] = SpatialCombinedExtractor
    require_key(model_params, "policy")  # doit exister en config, meme s'il est remplace ici
    model_params["policy"] = PointerMaskablePolicy


def _resolve_device_for_obs(observation_space, device_mode, gpu_available, total_params,
                            net_arch, cache_key):
    """(device, use_gpu, obs_size). Obs Dict -> CNN -> GPU si dispo (le benchmark MlpPolicy
    CPU ne s'applique pas). Obs Box -> logique historique `resolve_device_mode`."""
    if _is_dict_obs_space(observation_space):
        mode = str(device_mode).upper() if device_mode else None
        if mode == "CPU":
            return "cpu", False, None
        if mode == "GPU":
            if not gpu_available:
                raise ValueError("GPU mode requested but no CUDA GPU available")
            return "cuda", True, None
        return ("cuda", True, None) if gpu_available else ("cpu", False, None)
    obs_size = require_present(observation_space.shape, "observation_space.shape")[0]
    device, use_gpu = resolve_device_mode(
        device_mode, gpu_available, total_params,
        obs_size=obs_size, net_arch=net_arch, cache_key=cache_key,
    )
    return device, use_gpu, obs_size


def create_multi_agent_model(config, training_config_name, rewards_config_name, agent_key: str,
                            new_model=False, append_training=False, scenario_override=None,
                            debug_mode=False, device_mode: Optional[str] = None):
    """Create or load PPO model for specific agent with configuration following AI_INSTRUCTIONS.md."""

    # Check GPU availability
    gpu_available = check_gpu_availability()

    # CRITICAL: NO FALLBACK - agent-specific config MUST exist. La branche « pas d'agent »
    # tombait sur `config.load_training_config`, un stub deprecie qui leve sans condition :
    # elle n'a jamais pu aboutir, et le mode qui l'alimentait n'existe plus.
    training_config = config.load_agent_training_config(agent_key, training_config_name)
    print(f"✅ Loaded agent-specific training config: config/agents/{agent_key}/{agent_key}_training_config.json [{training_config_name}]")

    model_params = _model_params_with_ent_coef_frozen(training_config["model_params"])

    # Import environment
    W40KEngine, register_environment = setup_imports()
    
    # Register environment
    register_environment()
    
    # Create agent-specific environment
    cfg = get_config_loader()
    
    # Get scenario file (agent-specific or global)
    scenario_file = get_agent_scenario_file(cfg, agent_key, training_config_name, scenario_override)
    print(f"✅ Using scenario: {scenario_file}")

    # V11 §10.4 : l'adversaire vient de la CONFIG (bot_training), plus du nom du fichier
    # scenario. L'ancienne heuristique ("bot" dans le nom) faisait tomber tout scenario
    # nomme autrement sur SelfPlayWrapper(frozen_model=None) — donc un P2 ALEATOIRE
    # permanent, silencieux.
    use_bots = "bot_training" in training_config

    # Meme budget par tour que le chemin rotation : setup_callbacks / train_model
    # convertissent des episodes en timesteps sans moteur sous la main.
    resolve_turn_step_limit(
        [scenario_file],
        training_config,
        use_bots=use_bots,
        log=print,
    )

    # Load unit registry for multi-agent environment
    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()
    
    # CRITICAL FIX: Use rewards_config_name for controlled_agent (includes phase suffix)
    # agent_key is the directory name for config loading
    # rewards_config_name is the SECTION NAME within the rewards file (e.g., "..._phase1")
    effective_agent_key = rewards_config_name if rewards_config_name else agent_key
    
    # ✓ CHANGE 8: Check if vectorization is enabled in config
    n_envs = require_key(training_config, "n_envs")

    n_envs = _resolve_n_envs_for_step_logging(n_envs)

    training_config = resolve_run_budget(training_config, n_envs)

    # V11 §10.4 : meme construction d'adversaires que le chemin rotation.
    opponents = build_training_opponents(
        training_config,
        use_bots,
        training_config["total_episodes"] if "total_episodes" in training_config else None,
        print,
    )

    # `opponent_mix` exige qu'un snapshot du modele soit REPUBLIE pendant le run : seul
    # `train_with_scenario_rotation` le fait (`_publish_self_play_snapshot`). Ici, le premier
    # tirage de self-play lirait un fichier absent — ou pire, un snapshot fige d'un run precedent,
    # adversaire immobile pour tout l'entrainement. Erreur explicite plutot que les deux.
    # Valide AVANT `prepare_run_artifacts` : ce refus est une erreur de configuration, il ne
    # doit pas laisser derriere lui un `--new` qui a deja mis le modele precedent de cote.
    if self_play_is_enabled(opponents["opponent_mix_config"]):
        raise ValueError(
            "opponent_mix.enabled=True n'est supporte que par le chemin de rotation de scenarios "
            "(seul `train_with_scenario_rotation` republie le snapshot de self-play). Lancer "
            "l'entrainement par ce chemin, ou desactiver opponent_mix."
        )

    model_path, _episode_offset, episode_start_index = prepare_run_artifacts(
        config.get_models_root(), agent_key, new_model, append_training, n_envs
    )

    if n_envs > 1:
        # ✓ CHANGE 8: Create vectorized environments for parallel training
        print(f"🚀 Creating {n_envs} parallel environments for accelerated training...")

        vec_envs = register_vec_env(SubprocVecEnv([
            make_training_env(
                rank=i,
                scenario_file=scenario_file,
                rewards_config_name=rewards_config_name,
                training_config_name=training_config_name,
                controlled_agent_key=effective_agent_key,
                unit_registry=unit_registry,
                step_logger_enabled=False,
                debug_mode=debug_mode,
                use_bots=opponents["use_bots"],
                training_bots=opponents["training_bots"],
                agent_seat_mode=opponents["agent_seat_mode"],
                global_seed=opponents["agent_seat_seed"],
                opponent_mix_config=opponents["opponent_mix_config"],
                n_envs=n_envs,
                episode_start_index=episode_start_index,
            )
            for i in range(n_envs)
        ]))
        
        env = vec_envs
        print(f"✅ Vectorized training environment created with {n_envs} parallel processes")
        
    else:
        # ✓ CHANGE 8: Single environment (original behavior)
        base_env = W40KEngine(
            rewards_config=rewards_config_name,
            training_config_name=training_config_name,
            controlled_agent=effective_agent_key,
            active_agents=None,
            scenario_file=scenario_file,
            unit_registry=unit_registry,
            quiet=True,
            gym_training_mode=True,
            debug_mode=debug_mode,
            training_n_envs=n_envs,
            training_episode_start_index=episode_start_index,
        )
        
        # Connect step logger after environment creation - compliant engine compatibility
        if step_logger:
            # Connect StepLogger directly to compliant W40KEngine
            base_env.step_logger = step_logger
            print("✅ StepLogger connected to compliant W40KEngine")
        
        # Wrap environment with ActionMasker for MaskablePPO compatibility
        def mask_fn(env):
            return env.get_action_mask()

        masked_env = ActionMasker(base_env, mask_fn)

        # V11 §10.4 : bots PONDERES issus de bot_training (comme le chemin rotation),
        # plus un GreedyBot(0.15) code en dur declenche par le nom du fichier.
        if opponents["use_bots"]:
            bot_env = BotControlledEnv(
                masked_env,
                bots=opponents["training_bots"],
                unit_registry=unit_registry,
                agent_seat_mode=require_present(opponents["agent_seat_mode"], "agent_seat_mode"),
                global_seed=opponents["agent_seat_seed"],
                **build_self_play_kwargs(opponents["opponent_mix_config"]),
            )
            env = Monitor(bot_env)
        else:
            # Pas de bot_training en config : self-play. `frozen_model=None` est REFUSE
            # par SelfPlayWrapper (cf. §10.4) — un P2 aleatoire silencieux n'est pas un
            # adversaire d'entrainement valide.
            selfplay_env = SelfPlayWrapper(masked_env, frozen_model=None, update_frequency=100)
            env = Monitor(selfplay_env)

    # VecNormalize for create_multi_agent_model
    vec_norm_cfg = training_config.get("vec_normalize", {})  # get allowed: optional config
    vec_normalize_enabled = vec_norm_cfg.get("enabled", False)
    if vec_normalize_enabled:
        env = _apply_vec_normalize(env, model_path, vec_norm_cfg, new_model, n_envs, print)

    # Set device for model creation
    # PPO optimization: MlpPolicy performs BETTER on CPU (proven by benchmarks)
    # GPU only beneficial for CNN policies or networks with >2000 hidden units
    policy_kwargs = require_key(model_params, "policy_kwargs")
    net_arch = require_key(policy_kwargs, "net_arch")
    total_params = sum(net_arch) if isinstance(net_arch, list) else 512

    # BENCHMARK RESULTS: CPU 311 it/s vs GPU 282 it/s (10% faster on CPU)
    # Use GPU only for very large networks (>2000 hidden units)
    if _is_dict_obs_space(env.observation_space):
        _inject_spatial_extractor(model_params)
    cache_key = (
        require_present(agent_key, "agent_key"),
        training_config_name,
        rewards_config_name,
    )
    device, use_gpu, obs_size = _resolve_device_for_obs(
        env.observation_space, device_mode, gpu_available, total_params,
        net_arch=net_arch, cache_key=cache_key,
    )

    model_params["device"] = device
    # Jumeau de train_with_scenario_rotation : meme conversion TOTAL -> par env, meme garde-fou
    # de taille.
    apply_rollout_n_steps(model_params, n_envs, env.observation_space)

    if use_gpu:
        print(f"🖥️  Using GPU for {agent_key} PPO")
    elif gpu_available:
        print(f"ℹ️  Using CPU for {agent_key} PPO (10% faster than GPU for MlpPolicy)")
    
    # Determine whether to create new model or load existing
    specific_log_dir = ""
    if new_model or not os.path.exists(model_path):
        print(f"🆕 Creating new model for {agent_key} on {device.upper()}...")

        # Use specific log directory for continuous TensorBoard graphs across runs
        tb_log_name = f"{training_config_name}_{agent_key}"
        specific_log_dir = os.path.join(model_params["tensorboard_log"], tb_log_name)
        os.makedirs(specific_log_dir, exist_ok=True)

        # Update model_params to use specific directory
        model_params_copy = model_params.copy()
        model_params_copy["tensorboard_log"] = specific_log_dir
        if "learning_rate" in model_params_copy and isinstance(model_params_copy["learning_rate"], dict):
            model_params_copy["learning_rate"] = _make_constant_lr_schedule(model_params_copy["learning_rate"])

        model = MaskablePPO(env=env, **model_params_copy)
        # Disable rollout logging for multi-agent models (suppress verbose rollout/ metrics)
        if hasattr(model, 'logger') and model.logger:
            _orig_record = model.logger.record
            def _filtered_record(key, value, exclude=None):
                if key.startswith('rollout/'):
                    return
                return _orig_record(key, value, exclude)
            model.logger.record = _filtered_record
    elif append_training:
        print(f"📁 Loading existing model for continued training: {model_path}")
        model = _load_checkpoint(model_path, env, device)
        model.tensorboard_log = require_key(model_params, "tensorboard_log")
        model.verbose = require_key(model_params, "verbose")

        _apply_curriculum_model_params(model, model_params)

        # CRITICAL FIX: Reinitialize logger after loading from checkpoint
        # This ensures PPO training metrics (policy_loss, value_loss, etc.) are logged correctly
        # Without this, model.logger.name_to_value remains empty/stale from the checkpoint
        from stable_baselines3.common.logger import configure

        # Use specific log directory to ensure continuous TensorBoard graphs across runs
        # Format: ./tensorboard/{config_name}_{agent_key}/{run_name}
        # This prevents creating new timestamped subdirectories on each script run
        tb_log_name = f"{training_config_name}_{agent_key}"
        specific_log_dir = os.path.join(model.tensorboard_log, tb_log_name)

        # Create directory if it doesn't exist
        os.makedirs(specific_log_dir, exist_ok=True)

        new_logger = configure(specific_log_dir, ["tensorboard"])
        model.set_logger(new_logger)
        print(f"✅ Logger reinitialized for continuous TensorBoard: {specific_log_dir}")
    else:
        print(f"📁 Loading existing model: {model_path}")
        model = _load_checkpoint(model_path, env, device)
    
    _apply_torch_compile(model)
    return model, env, training_config, model_path, _episode_offset


# MacroController (agent "macro" de Phase 1) a ete retire ici. Occupaient cette place :
#   - create_macro_controller_model / _build_macro_eval_env : deux fonctions qui levaient
#     NotImplementedError sans condition depuis le passage en Phase 2, et dont les appels
#     etaient habilles par un cast en quadruplet. La branche --agent MacroController ne
#     pouvait donc que planter : une option de ligne de commande qui promet et ne tient pas.
#   - _evaluate_macro_model et son afficheur _print_eval_progress, tous deux appeles
#     uniquement depuis ces branches macro.
# Preuve de mort au-dela des stubs : ai/macro_training_env.py (les wrappers macro) n'existe
# pas, config/agents/MacroController/ (config + scenarios + modele) n'existe pas, et rien
# ne lisait les chemins macro_controller_config_* de config/config.json. La documentation
# qui presentait ce mode comme "implemente aujourd'hui" (Documentation/AI_TRAINING.md) a ete
# corrigee dans le meme mouvement.
# Phase 2 : l'agent micro unifie (create_multi_agent_model) porte l'intention de zone.
# Il n'y a pas de remplacant a chercher, il n'y a plus qu'un seul agent.


def resolve_turn_step_limit(
    scenario_files: List[str],
    training_config: Dict[str, Any],
    use_bots: bool,
    log: Callable[[str], None],
) -> int:
    """Budget d'actions d'un tour, derive du nombre de FIGURINES du scenario le plus
    charge — meme formule et meme config que le garde anti-runaway du moteur
    (compute_turn_step_limit), pour que l'estimation de timesteps et la troncature
    runtime ne divergent jamais. Ecrit dans training_config['_turn_step_limit'] :
    les fonctions qui convertissent des episodes en timesteps n'ont pas de moteur
    sous la main.
    """
    from engine.game_state import GameStateManager
    from config_loader import compute_turn_step_limit

    # Use the scenario with the highest unit count to avoid underestimating step budget.
    scenario_probe_players: List[int] = [1]
    if use_bots:
        probe_seat_mode = require_key(training_config, "agent_seat_mode")
        if probe_seat_mode not in {"p1", "p2", "random"}:
            raise ValueError(
                f"training_config.agent_seat_mode must be one of 'p1', 'p2', 'random' "
                f"(got {probe_seat_mode!r})"
            )
        if probe_seat_mode == "p2":
            scenario_probe_players = [2]
        elif probe_seat_mode == "random":
            scenario_probe_players = [1, 2]

    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()

    max_units = 0
    max_units_scenario: Optional[str] = None
    for scenario_file in sorted(set(scenario_files)):
        with open(scenario_file, "r", encoding="utf-8-sig") as f:
            scenario_data = json.load(f)
        if isinstance(scenario_data, dict) and "units" in scenario_data:
            scenario_unit_count = len(require_key(scenario_data, "units"))
        elif (
            isinstance(scenario_data, dict)
            and "agent_roster_ref" in scenario_data
            and "opponent_roster_ref" in scenario_data
        ):
            scenario_unit_count = _count_units_from_roster_scenario(scenario_data, scenario_file)
        else:
            scenario_unit_count_candidates: List[int] = []
            for probe_player in scenario_probe_players:
                temp_manager = GameStateManager(
                    {"board": {}, "controlled_player": probe_player},
                    unit_registry
                )
                scenario_result = temp_manager.load_units_from_scenario(scenario_file, unit_registry)
                scenario_unit_count_candidates.append(len(require_key(scenario_result, "units")))
            scenario_unit_count = max(scenario_unit_count_candidates)
        if scenario_unit_count <= 0:
            raise ValueError(f"Scenario '{scenario_file}' resolved to zero units")
        if scenario_unit_count > max_units:
            max_units = scenario_unit_count
            max_units_scenario = scenario_file

    if max_units_scenario is None:
        raise ValueError("No scenario available to compute the per-turn step budget")

    game_rules = require_key(get_config_loader().get_game_config(), "game_rules")
    max_steps = compute_turn_step_limit(game_rules, max_units)
    training_config["_turn_step_limit"] = max_steps
    log(
        "📊 Auto-calculated per-turn step budget: "
        f"{max_units} models × {require_key(game_rules, 'max_actions_per_model_per_turn')} actions "
        f"× {require_key(game_rules, 'step_limit_margin')} margin = {max_steps} "
        f"(max models from {os.path.basename(max_units_scenario)})"
    )
    return max_steps


def print_truncation_summary(metrics_tracker: Any, log_fn=print) -> None:
    """Bilan des troncatures en fin de run. Un ZERO est une information, il s'affiche aussi.

    Une troncature signale une BOUCLE dans le moteur (garde `_episode_step_limit` de
    `w40k_core.step_with_mask`), pas une fin de partie. Sans ce bilan, elle n'existait que dans
    le `print` d'un worker, noye dans la console a `n_envs=48` et perdu au scroll — un run de
    47 h pouvait en produire des centaines sans que personne le sache.
    """
    if metrics_tracker is None:
        return
    for line in metrics_tracker.truncation_summary_lines():
        log_fn(line)


def resume_episode_offset(model_path: str, append_training: bool) -> int:
    """Episodes deja joues par le modele qu'on reprend ; 0 pour un run neuf.

    Un seul point de lecture pour tous les chemins d'entrainement : sans lui, un `--append`
    relance la rampe de deploiement depuis `active_ratio_start` et repart d'un compte d'episodes
    nul. Il ne pilote PAS learning_rate ni ent_coef, rampes de REGIME propres a chaque run
    (cf. ai/run_state.py).

    `--append` SANS modele existant n'est pas une reprise : les chemins creent alors un
    modele neuf (`if new_model or not os.path.exists(model_path)`). Exiger un etat de run ferait
    echouer le premier entrainement d'un agent, avec un message qui accuse le mauvais coupable.
    """
    if not append_training or not os.path.exists(model_path):
        return 0
    return load_run_state(model_path)


def resolve_run_budget(training_config: Dict[str, Any], n_envs: int,
                       total_episodes: Any = None,
                       total_episodes_override: Optional[int] = None) -> Dict[str, Any]:
    """Config du RUN : les deux termes du denominateur des rampes par-episode, resolus.

    Le JSON ne porte que des INTENTIONS. `--step`/`--replay` n'ouvrent qu'un environnement la ou
    le profil en declare 48 ; `--total-episodes` remplace la longueur du run ; une phase de
    curriculum decoupe le run en chunks dont `total_episodes_override` porte la vraie longueur.
    Tout ce qui vit dans ce processus (callbacks, budgets d'`opponent_mix`) lit le dict rendu ici ;
    les workers, eux, relisent le fichier et recoivent les valeurs par `make_training_env`.
    Cf. engine/episode_schedule.py.

    `total_episodes=None` laisse la valeur du profil : les chemins qui n'ont pas de longueur de run
    propre (`create_multi_agent_model`) n'en ont pas d'autre.
    """
    resolved = {**training_config, "n_envs": require_positive_int(n_envs, "n_envs")}
    budget = total_episodes_override if total_episodes_override is not None else total_episodes
    if budget is not None:
        resolved["total_episodes"] = require_positive_int(budget, "total_episodes")
    return resolved


def build_training_opponents(
    training_config: Dict[str, Any],
    use_bots: bool,
    total_episodes: Optional[int],
    log: Callable[[str], None],
) -> Dict[str, Any]:
    """Construction de l'adversaire d'entrainement — CHEMIN UNIQUE (V11 §10.4).

    `training_config["n_envs"]` doit porter le nombre d'environnements REELLEMENT ouverts (le
    chemin d'entrainement l'y reecrit apres `_resolve_n_envs_for_step_logging`) : la rampe de
    self-play d'`opponent_mix` en depend. Cf. engine/episode_schedule.py.

    Historiquement seul `train_with_scenario_rotation` construisait les bots ponderes
    et `opponent_mix` ; le chemin single-scenario tombait sur
    `SelfPlayWrapper(frozen_model=None)`, dont le frozen n'etait JAMAIS mis a jour :
    P2 jouait des actions ALEATOIRES du premier au dernier episode, sans qu'aucun log
    ne le signale. Les deux chemins passent desormais par cette fonction.

    Retourne les parametres a transmettre a `make_training_env` / `BotControlledEnv`.
    """
    opponents: Dict[str, Any] = {
        "use_bots": use_bots,
        "training_bots": None,
        "agent_seat_mode": None,
        "agent_seat_seed": None,
        "opponent_mix_config": None,
        "self_play_snapshot_path": None,
        "self_play_snapshot_update_freq": None,
        "self_play_snapshot_enabled": False,
    }
    if not use_bots:
        return opponents

    opponents["training_bots"] = _build_training_bots_from_config(training_config)
    agent_seat_mode = require_key(training_config, "agent_seat_mode")
    if agent_seat_mode not in {"p1", "p2", "random"}:
        raise ValueError(
            f"training_config.agent_seat_mode must be one of 'p1', 'p2', 'random' "
            f"(got {agent_seat_mode!r})"
        )
    opponents["agent_seat_mode"] = agent_seat_mode
    if agent_seat_mode == "random":
        if "agent_seat_seed" in training_config:
            agent_seat_seed_raw = require_key(training_config, "agent_seat_seed")
        elif "seed" in training_config:
            agent_seat_seed_raw = require_key(training_config, "seed")
        else:
            raise KeyError(
                "agent_seat_mode='random' requires a seed key in training config. "
                "Provide 'agent_seat_seed' (preferred) or existing 'seed'."
            )
        if not isinstance(agent_seat_seed_raw, int) or isinstance(agent_seat_seed_raw, bool):
            raise TypeError(
                "Seat seed must be an integer when agent_seat_mode='random' "
                "(from 'agent_seat_seed' or 'seed')."
            )
        opponents["agent_seat_seed"] = int(agent_seat_seed_raw)

    ratios = require_key(require_key(training_config, "bot_training"), "ratios")
    ratio_parts = [f"{v*100:.0f}% {k.replace('_', ' ').title()}" for k, v in ratios.items() if v > 0]
    log(f"🤖 Bot training ratios: {', '.join(ratio_parts)}")
    log(f"🤖 Agent seat mode: {agent_seat_mode}")

    if "opponent_mix" not in training_config:
        return opponents

    mix_cfg = require_key(training_config, "opponent_mix")
    if not isinstance(mix_cfg, dict):
        raise TypeError("training_config.opponent_mix must be a mapping when provided.")
    if not bool(require_key(mix_cfg, "enabled")):
        return opponents

    self_play_ratio_start = float(require_key(mix_cfg, "self_play_ratio_start"))
    self_play_ratio_end = float(require_key(mix_cfg, "self_play_ratio_end"))
    warmup_episodes = int(require_key(mix_cfg, "warmup_episodes"))
    snapshot_path = str(require_key(mix_cfg, "snapshot_model_path"))
    snapshot_refresh_episodes = int(require_key(mix_cfg, "snapshot_update_freq_episodes"))
    snapshot_device = str(require_key(mix_cfg, "self_play_snapshot_device")).strip().lower()
    self_play_deterministic = bool(require_key(mix_cfg, "self_play_deterministic"))

    if not (0.0 <= self_play_ratio_start <= 1.0):
        raise ValueError(
            "opponent_mix.self_play_ratio_start must be in [0,1] "
            f"(got {self_play_ratio_start})"
        )
    if not (0.0 <= self_play_ratio_end <= 1.0):
        raise ValueError(
            "opponent_mix.self_play_ratio_end must be in [0,1] "
            f"(got {self_play_ratio_end})"
        )
    if warmup_episodes < 0:
        raise ValueError(
            f"opponent_mix.warmup_episodes must be >= 0 (got {warmup_episodes})"
        )
    if not snapshot_path.strip():
        raise ValueError("opponent_mix.snapshot_model_path must be a non-empty string.")
    if snapshot_refresh_episodes <= 0:
        raise ValueError(
            "opponent_mix.snapshot_update_freq_episodes must be > 0 "
            f"(got {snapshot_refresh_episodes})"
        )
    if snapshot_device not in {"cpu", "auto"}:
        raise ValueError(
            "opponent_mix.self_play_snapshot_device must be either 'cpu' or 'auto' "
            f"(got {snapshot_device!r})"
        )
    snapshot_dir = os.path.dirname(snapshot_path)
    if not snapshot_dir:
        raise ValueError(
            f"opponent_mix.snapshot_model_path must include a directory (got {snapshot_path!r})"
        )
    os.makedirs(snapshot_dir, exist_ok=True)
    if total_episodes is None:
        raise ValueError(
            "opponent_mix.enabled=True requires a known total_episodes to schedule the "
            "self-play ratio."
        )

    opponents["opponent_mix_config"] = {
        "enabled": True,
        "self_play_ratio_start": self_play_ratio_start,
        "self_play_ratio_end": self_play_ratio_end,
        "warmup_episodes": warmup_episodes,
        "total_episodes": int(total_episodes),
        # Budgets GLOBAUX ci-dessus ; le wrapper les ramene au budget d'UN environnement.
        "n_envs": require_positive_int(training_config.get("n_envs"), "training_config.n_envs"),
        "snapshot_model_path": snapshot_path,
        "snapshot_refresh_episodes": snapshot_refresh_episodes,
        "snapshot_device": snapshot_device,
        "deterministic": self_play_deterministic,
    }
    opponents["self_play_snapshot_enabled"] = True
    opponents["self_play_snapshot_path"] = snapshot_path
    opponents["self_play_snapshot_update_freq"] = snapshot_refresh_episodes
    log(
        "🤝 Opponent mix enabled: "
        f"self-play ratio {self_play_ratio_start:.2f}->{self_play_ratio_end:.2f} "
        f"(warmup={warmup_episodes} ep, snapshot every {snapshot_refresh_episodes} ep)"
    )
    return opponents


TrainRunResult = Tuple[bool, MaskablePPO, GymEnv]
TrainRunResultWithInfo = Tuple[bool, MaskablePPO, GymEnv, Dict[str, Any]]


@overload
def train_with_scenario_rotation(config, agent_key, training_config_name, rewards_config_name,
                                 scenario_list, total_episodes,
                                 new_model=..., append_training=..., use_bots=..., debug_mode=...,
                                 device_mode: Optional[str] = ...,
                                 training_config_override: Optional[Dict[str, Any]] = ...,
                                 silent_chunk: bool = ...,
                                 return_run_info: Literal[False] = ...) -> TrainRunResult: ...


@overload
def train_with_scenario_rotation(config, agent_key, training_config_name, rewards_config_name,
                                 scenario_list, total_episodes,
                                 new_model=..., append_training=..., use_bots=..., debug_mode=...,
                                 device_mode: Optional[str] = ...,
                                 training_config_override: Optional[Dict[str, Any]] = ...,
                                 silent_chunk: bool = ...,
                                 *, return_run_info: Literal[True]) -> TrainRunResultWithInfo: ...


def train_with_scenario_rotation(config, agent_key, training_config_name, rewards_config_name,
                                 scenario_list, total_episodes,
                                 new_model=False, append_training=False, use_bots=False, debug_mode=False,
                                 device_mode: Optional[str] = None,
                                 training_config_override: Optional[Dict[str, Any]] = None,
                                 silent_chunk: bool = False,
                                 return_run_info: bool = False) -> Union[TrainRunResult, TrainRunResultWithInfo]:
    """Train model with random scenario selection per episode.
    
    Args:
        config: ConfigLoader instance
        agent_key: Agent identifier
        training_config_name: Phase name (e.g., 'phase2')
        rewards_config_name: Rewards config name
        scenario_list: List of scenario file paths (randomly selected per episode)
        total_episodes: Total episodes for entire training
        new_model: Whether to create new model
        append_training: Whether to continue from existing model
        use_bots: If True, use bots for Player 1 instead of self-play frozen model

    Returns:
        TrainRunResult = (success, final_model, final_env) par defaut.
        TrainRunResultWithInfo = (success, final_model, final_env, run_info) si
        return_run_info=True. Les deux formes sont declarees par @overload
        ci-dessus : l'appelant n'a donc plus a caster le resultat.
    """
    def chunk_log(message: str) -> None:
        if not silent_chunk:
            print(message)

    # Load agent-specific training config to get model parameters
    training_config = training_config_override if training_config_override is not None else config.load_agent_training_config(agent_key, training_config_name)

    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()
    initial_weighted_entries = len(scenario_list)
    scenario_list = _apply_wall_ref_weighting(
        scenario_list=scenario_list,
        training_config=training_config,
    )
    if len(scenario_list) > initial_weighted_entries:
        sampling_cfg = training_config.get("scenario_sampling")
        if isinstance(sampling_cfg, dict):
            wall_weights_cfg = sampling_cfg.get("train_wall_ref_weights")
            multipliers_cfg = sampling_cfg.get("train_wall_ref_multipliers")
            if isinstance(wall_weights_cfg, dict):
                chunk_log(
                    "🎯 Wall-ref weighting enabled (weights): "
                    f"{wall_weights_cfg}"
                )
            elif isinstance(multipliers_cfg, dict):
                chunk_log(
                    "🎯 Wall-ref weighting enabled (multipliers - legacy): "
                    f"{multipliers_cfg}"
                )

    initial_weighted_entries = len(scenario_list)
    scenario_list = _apply_training_hard_weights(
        scenario_list=scenario_list,
        training_config=training_config,
    )
    if len(scenario_list) > initial_weighted_entries:
        training_hard_cfg = training_config.get("training_hard")
        if isinstance(training_hard_cfg, dict) and training_hard_cfg.get("enabled") is True:
            target_ratio = require_key(training_hard_cfg, "target_episode_ratio")
            chunk_log(
                f"🎯 training_hard enabled: target episode ratio={float(target_ratio):.2f}"
            )

    forced_initial_weighted_entries = len(scenario_list)
    forcing_controlled_player_mode = "p1"
    if use_bots:
        forcing_controlled_player_mode = require_key(training_config, "agent_seat_mode")
        if forcing_controlled_player_mode not in {"p1", "p2", "random"}:
            raise ValueError(
                f"training_config.agent_seat_mode must be one of 'p1', 'p2', 'random' "
                f"(got {forcing_controlled_player_mode!r})"
            )
    scenario_list = _apply_unit_rule_forcing_weights(
        scenario_list=scenario_list,
        training_config=training_config,
        unit_registry=unit_registry,
        controlled_player_mode=forcing_controlled_player_mode,
    )
    if len(scenario_list) > forced_initial_weighted_entries:
        forcing_cfg = training_config.get("unit_rule_forcing")
        if isinstance(forcing_cfg, dict) and forcing_cfg.get("enabled") is True:
            target_ratio = require_key(forcing_cfg, "target_controlled_episode_ratio")
            chunk_log(
                "🎯 Unit-rule forcing enabled: "
                f"target controlled exposure ratio={float(target_ratio):.2f} "
                f"(seat_mode={forcing_controlled_player_mode})"
            )

    chunk_log(f"\n{'='*80}")
    chunk_log("🔄 MULTI-SCENARIO TRAINING")
    chunk_log(f"{'='*80}")
    chunk_log(f"Total episodes: {total_episodes}")
    scenario_counts: Dict[str, int] = {}
    for scenario in scenario_list:
        scenario_name = os.path.basename(scenario)
        if scenario_name in scenario_counts:
            scenario_counts[scenario_name] += 1
        else:
            scenario_counts[scenario_name] = 1
    unique_scenarios = sorted(scenario_counts.items(), key=lambda item: item[0])
    chunk_log(
        f"Scenarios (weighted): {len(scenario_list)} entries, "
        f"{len(unique_scenarios)} unique files"
    )
    if len(scenario_list) > 1:
        chunk_log(f"🎲 RANDOM MODE: Each episode randomly selects one of the {len(scenario_list)} scenarios")
    chunk_log(f"{'='*80}\n")

    # Check GPU availability (match single-scenario training output)
    gpu_available = check_gpu_availability() if not silent_chunk else torch.cuda.is_available()
    
    # Require n_envs for consistency with single-scenario training
    n_envs = require_key(training_config, "n_envs")
    n_envs = _resolve_n_envs_for_step_logging(n_envs, log=chunk_log)

    training_config = resolve_run_budget(training_config, n_envs, total_episodes)

    max_steps = resolve_turn_step_limit(scenario_list, training_config, use_bots, chunk_log)

    # Calculate average steps per episode for timestep conversion
    max_turns = get_max_turns()
    avg_steps_per_episode = max_turns * max_steps * 0.6  # Estimate: 60% of max
    
    # Base de TOUTES les rampes par-episode : cf. ai/run_state.py.
    model_path, episode_offset, episode_start_index = prepare_run_artifacts(
        config.get_models_root(), agent_key, new_model, append_training, n_envs, chunk_log
    )

    # Create initial model with first scenario (or load if append_training)
    chunk_log(f"📦 {'Loading existing model' if append_training else 'Creating initial model'} with first scenario...")
    
    # Import environment
    W40KEngine, register_environment = setup_imports()
    register_environment()
    
    # Create initial environment with first scenario
    # CRITICAL FIX: Use rewards_config_name for controlled_agent (includes phase suffix)
    # agent_key is the directory name for config loading
    # rewards_config_name is the SECTION NAME within the rewards file (e.g., "..._phase1")
    effective_agent_key = rewards_config_name if rewards_config_name else agent_key
    
    # Create bots for bot training mode (random selection per episode)
    # V11 §10.4 : construction MUTUALISEE avec le chemin single-scenario.
    _opponents = build_training_opponents(training_config, use_bots, total_episodes, chunk_log)
    training_bots = _opponents["training_bots"]
    agent_seat_mode = _opponents["agent_seat_mode"]
    agent_seat_seed = _opponents["agent_seat_seed"]
    opponent_mix_config = _opponents["opponent_mix_config"]
    self_play_snapshot_path = _opponents["self_play_snapshot_path"]
    self_play_snapshot_update_freq = _opponents["self_play_snapshot_update_freq"]
    self_play_snapshot_enabled = _opponents["self_play_snapshot_enabled"]

    # Branch: n_envs > 1 uses SubprocVecEnv for parallel training
    if n_envs > 1:
        chunk_log(f"🚀 Creating {n_envs} parallel environments for accelerated training...")
        vec_envs = register_vec_env(SubprocVecEnv([
            make_training_env(
                rank=i,
                scenario_file=scenario_list[0],
                rewards_config_name=rewards_config_name,
                training_config_name=training_config_name,
                controlled_agent_key=effective_agent_key,
                unit_registry=unit_registry,
                step_logger_enabled=False,
                scenario_files=scenario_list,
                debug_mode=debug_mode,
                use_bots=use_bots,
                training_bots=training_bots,
                agent_seat_mode=require_present(agent_seat_mode, "agent_seat_mode"),
                global_seed=agent_seat_seed,
                opponent_mix_config=opponent_mix_config,
                n_envs=n_envs,
                episode_start_index=episode_start_index,
            )
            for i in range(n_envs)
        ]))
        env = vec_envs
        chunk_log(f"✅ Vectorized training environment created with {n_envs} parallel processes")
    else:
        # Single environment (original behavior)
        current_scenario = scenario_list[0]
        base_env = W40KEngine(
            rewards_config=rewards_config_name,
            training_config_name=training_config_name,
            controlled_agent=effective_agent_key,
            active_agents=None,
            scenario_file=current_scenario,
            scenario_files=scenario_list,
            unit_registry=unit_registry,
            quiet=True,
            gym_training_mode=True,
            debug_mode=debug_mode,
            training_n_envs=n_envs,
            training_episode_start_index=episode_start_index,
        )
        if step_logger:
            base_env.step_logger = step_logger
            chunk_log("✅ StepLogger connected to compliant W40KEngine")
        def mask_fn(env):
            return env.get_action_mask()
        masked_env = ActionMasker(base_env, mask_fn)
        if use_bots and training_bots:
            bot_env = BotControlledEnv(
                masked_env,
                bots=training_bots,
                unit_registry=unit_registry,
                agent_seat_mode=require_present(agent_seat_mode, "agent_seat_mode"),
                global_seed=agent_seat_seed,
                **build_self_play_kwargs(opponent_mix_config),
            )
            env = Monitor(bot_env)
        else:
            env = Monitor(masked_env)

    # VecNormalize for scenario rotation
    vec_norm_cfg = training_config.get("vec_normalize", {})  # get allowed: optional config
    vec_normalize_enabled = vec_norm_cfg.get("enabled", False)
    if vec_normalize_enabled:
        env = _apply_vec_normalize(env, model_path, vec_norm_cfg, new_model, n_envs, chunk_log)
    
    # Create or load model
    model_params = training_config["model_params"].copy()

    # n_steps est un TOTAL par update : le convertir en pas PAR ENV et borner le buffer.
    apply_rollout_n_steps(model_params, n_envs, env.observation_space, log=chunk_log)

    model_params = _model_params_with_ent_coef_frozen(model_params, log=chunk_log)

    tensorboard_root = require_key(model_params, "tensorboard_log")
    if not isinstance(tensorboard_root, str) or not tensorboard_root.strip():
        raise ValueError(
            f"model_params.tensorboard_log must be a non-empty string (got {tensorboard_root!r})"
        )
    tb_log_name = f"{training_config_name}_{agent_key}"
    experiment_log_dir, specific_log_dir = _resolve_tensorboard_run_dir(
        base_log_root=tensorboard_root,
        training_config_name=training_config_name,
        agent_key=agent_key,
        model_path=model_path,
        new_model=new_model,
        append_training=append_training,
    )
    chunk_log(f"📊 TensorBoard experiment: {experiment_log_dir}")
    chunk_log(f"📊 TensorBoard run: {specific_log_dir}")

    policy_kwargs = require_key(model_params, "policy_kwargs")
    net_arch = require_key(policy_kwargs, "net_arch")
    total_params = sum(net_arch) if isinstance(net_arch, list) else 512
    if _is_dict_obs_space(env.observation_space):
        _inject_spatial_extractor(model_params)
    cache_key = (
        require_present(agent_key, "agent_key"),
        training_config_name,
        rewards_config_name,
    )
    device, use_gpu, obs_size = _resolve_device_for_obs(
        env.observation_space, device_mode, gpu_available, total_params,
        net_arch=net_arch, cache_key=cache_key,
    )
    model_params["device"] = device

    if use_gpu:
        chunk_log(f"🖥️  Using GPU for {agent_key} PPO")
    elif gpu_available:
        chunk_log(f"ℹ️  Using CPU for {agent_key} PPO (10% faster than GPU for MlpPolicy)")

    if new_model or not os.path.exists(model_path):
        chunk_log(f"🆕 Creating new model: {model_path}")
        model_params_copy = model_params.copy()
        model_params_copy["tensorboard_log"] = specific_log_dir
        if "learning_rate" in model_params_copy and isinstance(model_params_copy["learning_rate"], dict):
            lr_cfg = model_params_copy["learning_rate"]
            model_params_copy["learning_rate"] = _make_constant_lr_schedule(lr_cfg)
            chunk_log(f"✅ Learning rate: constant {lr_cfg['initial']} (decay → {lr_cfg['final']} via LearningRateScheduleCallback)")
        model = MaskablePPO(env=env, **model_params_copy)
    elif append_training:
        chunk_log(f"📁 Loading existing model for continued training: {model_path}")
        model = _load_checkpoint(model_path, env, device)
        # Jumeau de `create_multi_agent_model` : ces deux cles sont exclues du bloc curriculum
        # parce que l'APPELANT les pose, et celui-ci ne le faisait pas — un profil qui change
        # `verbose` en --append heritait de la valeur du checkpoint, sans rien afficher.
        model.tensorboard_log = require_key(model_params, "tensorboard_log")
        model.verbose = require_key(model_params, "verbose")

        _apply_curriculum_model_params(model, model_params, log=chunk_log)

        # CRITICAL FIX: Reinitialize logger after loading from checkpoint
        # This ensures PPO training metrics (policy_loss, value_loss, etc.) are logged correctly
        # Without this, model.logger.name_to_value remains empty/stale from the checkpoint
        from stable_baselines3.common.logger import configure
        new_logger = configure(specific_log_dir, ["tensorboard"])
        model.set_logger(new_logger)
        chunk_log(f"✅ Logger reinitialized for TensorBoard run: {specific_log_dir}")
    else:
        chunk_log(f"⚠️ Model exists but neither --new nor --append specified. Creating new model.")
        model_params_copy = model_params.copy()
        model_params_copy["tensorboard_log"] = specific_log_dir
        if "learning_rate" in model_params_copy and isinstance(model_params_copy["learning_rate"], dict):
            model_params_copy["learning_rate"] = _make_constant_lr_schedule(model_params_copy["learning_rate"])
        model = MaskablePPO(env=env, **model_params_copy)
    
    _apply_torch_compile(model)
    # Import metrics tracker
    from ai.metrics_tracker import W40KMetricsTracker, resolve_perf_windows

    # Initialize frozen model for self-play
    # The frozen model is a copy of the learning model used by Player 1
    frozen_model = None
    frozen_model_update_frequency = 100  # Episodes between frozen model updates
    last_frozen_model_update = 0

    # Bot ratios printed when building training_bots

    # Keep tracker aligned with selected run directory.
    model_tensorboard_dir = specific_log_dir
    
    # Create metrics tracker for entire rotation training
    _perf_window, _perf_window_fast = resolve_perf_windows(training_config)
    metrics_tracker = W40KMetricsTracker(
        agent_key,
        model_tensorboard_dir,
        initial_episode_count=episode_offset,
        initial_step_count=int(getattr(model, "num_timesteps", 0)),
        show_banner=not silent_chunk,
        perf_window=_perf_window,
        perf_window_fast=_perf_window_fast,
    )
    # print(f"📈 Metrics tracking enabled for agent: {agent_key}")

    # Create metrics callback ONCE before loop (not inside it)
    from stable_baselines3.common.callbacks import CallbackList
    metrics_callback = MetricsCollectionCallback(metrics_tracker, model, controlled_agent=effective_agent_key)

    # Training loop with random scenario selection per episode
    episodes_trained = 0

    # Global start time for callbacks
    global_start_time = time.time()

    # Progress bar is handled by EpisodeTerminationCallback

    # PPO requires n_steps rollouts before each update; we use this as a natural chunk size
    # for our episode-budgeted outer loop.
    total_steps_per_update = model_params["n_steps"] * n_envs
    chunk_timesteps = total_steps_per_update * 4  # 4 updates per chunk for stable gradients

    # For n_envs==1: recreate env with frozen model for self-play (model already has env for n_envs>1)
    if n_envs == 1:
        initial_scenario = scenario_list[0]
        base_env = W40KEngine(
            rewards_config=rewards_config_name,
            training_config_name=training_config_name,
            controlled_agent=effective_agent_key,
            active_agents=None,
            scenario_file=initial_scenario,
            scenario_files=scenario_list,
            unit_registry=unit_registry,
            quiet=True,
            gym_training_mode=True,
            debug_mode=debug_mode,
            training_n_envs=n_envs,
            training_episode_start_index=episode_start_index,
        )
        # V11 T6 : ce bloc RECREE l'environnement (cf. commentaire ci-dessus) et remplace le
        # base_env construit plus haut — celui-la seul recevait le StepLogger (~L2377). Sans
        # cette reconnexion, `--step` journalisait "StepLogger connected" pour un env aussitot
        # jete, puis s'entrainait sur un moteur MUET : step.log reduit a son en-tete et
        # ai/analyzer.py sans matiere. Bug latent (ce chemin exige n_envs==1, or la config
        # vaut 48) revele par le forcage mono-env de --step. Miroir exact de la connexion ~L2377.
        if step_logger:
            base_env.step_logger = step_logger
        def mask_fn(env):
            return env.get_action_mask()
        masked_env = ActionMasker(base_env, mask_fn)
        if use_bots:
            bot_env = BotControlledEnv(
                masked_env,
                bots=training_bots,
                unit_registry=unit_registry,
                agent_seat_mode=require_present(agent_seat_mode, "agent_seat_mode"),
                global_seed=agent_seat_seed,
                **build_self_play_kwargs(opponent_mix_config),
            )
            env = Monitor(bot_env)
        else:
            if episodes_trained - last_frozen_model_update >= frozen_model_update_frequency or frozen_model is None:
                with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as f:
                    temp_path = f.name
                model.save(temp_path)
                frozen_model = MaskablePPO.load(temp_path)
                os.unlink(temp_path)
                last_frozen_model_update = episodes_trained
                if episodes_trained > 0:
                    print(f"  🔄 Self-play: Updated frozen opponent (Episode {episodes_trained})")
            selfplay_env = SelfPlayWrapper(masked_env, frozen_model=frozen_model, update_frequency=frozen_model_update_frequency)
            env = Monitor(selfplay_env)
        if vec_normalize_enabled:
            tmp_dir = tempfile.mkdtemp()
            tmp_model_path = os.path.join(tmp_dir, "model.zip")
            try:
                if save_vec_normalize(model.get_env(), tmp_model_path):
                    venv = DummyVecEnv([cast(Any, lambda: env)])
                    vec_norm = VecNormalize.load(get_vec_normalize_path(tmp_model_path), venv)
                    vec_norm.training = True
                    vec_norm.norm_reward = training_config.get("vec_normalize", {}).get("norm_reward", True)  # get allowed: optional config
                    env = vec_norm
            finally:
                if os.path.exists(tmp_dir):
                    for f in os.listdir(tmp_dir):
                        os.unlink(os.path.join(tmp_dir, f))
                    os.rmdir(tmp_dir)
        # L'environnement construit plus haut dans cette fonction est REMPLACE ici. Sans
        # fermeture, il reste ouvert jusqu'a la fin du process (fichiers, et processus fils si
        # la branche vectorisee l'avait produit) : `set_env` ne ferme pas l'ancien.
        close_training_env(model.get_env(), "remplacement d'environnement (rotation)", chunk_log)
        model.set_env(env)

    def _debug_train_marker(fmt: str, *args: Any) -> None:
        """Jalons de construction du run — RELAIS vers `debug_trace.trace`, canal `train`.

        Prend un format et ses arguments, jamais un message déjà construit : sinon les
        appelants formateraient AVANT la garde, et le canal `train` serait le seul du dépôt
        à payer son formatage en permanence. C'est la règle de l'en-tête de `debug_trace`,
        et le garde AST des tests vérifie ce relais comme il vérifie `trace` lui-même.
        """
        from engine.debug_trace import CH_TRAIN, trace

        trace(CH_TRAIN, debug_mode, fmt, *args)

    # Create callbacks for training
    scenario_display = f"Random from {len(scenario_list)} scenarios"
    _debug_train_marker("before setup_callbacks()")
    training_callbacks = setup_callbacks(
        config=config,
        model_path=model_path,
        training_config=training_config,
        training_config_name=training_config_name,
        rewards_config_name=rewards_config_name,
        metrics_tracker=metrics_tracker,
        total_episodes_override=total_episodes,
        max_episodes_override=total_episodes,  # Train directly to total_episodes
        scenario_info=scenario_display,
        global_episode_offset=episode_offset,
        global_start_time=global_start_time,
        silent_logs=silent_chunk
    )
    callback_names = [callback.__class__.__name__ for callback in training_callbacks]
    _debug_train_marker(
        "after setup_callbacks(): count=%s callbacks=%s", len(training_callbacks), callback_names
    )
    
    # Link metrics_tracker to bot evaluation callback
    for callback in training_callbacks:
        if hasattr(callback, '__class__') and callback.__class__.__name__ == 'BotEvaluationCallback':
            callback.metrics_tracker = metrics_tracker
    _debug_train_marker("after bot-eval callback metrics_tracker wiring")
    
    # Combine all callbacks with strict ordering:
    # 1) Metrics first (episode_count must be up to date)
    # 2) Bot eval before termination (ensure last_bot_eval exists at gate checkpoints)
    # 3) Episode termination last
    non_terminal_callbacks = []
    terminal_callbacks = []
    for callback in training_callbacks:
        callback_name = callback.__class__.__name__
        if callback_name == "EpisodeTerminationCallback":
            terminal_callbacks.append(callback)
        else:
            non_terminal_callbacks.append(callback)

    ordered_training_callbacks = non_terminal_callbacks + terminal_callbacks
    enhanced_callbacks = CallbackList(cast(List[BaseCallback], [metrics_callback] + ordered_training_callbacks))
    _debug_train_marker(
        "after CallbackList assembly: ordered_callbacks=%s",
        [callback.__class__.__name__ for callback in ordered_training_callbacks],
    )
    
    # Train directly to total_episodes using an EPISODE-BUDGETED wrapper around SB3.learn().
    #
    # SB3 only exposes a timestep budget, so we:
    # - repeatedly call learn() with a small, fixed chunk of timesteps
    # - after each chunk, check how many episodes actually completed (via metrics_tracker)
    # - stop when we reach the exact desired episode count (total_episodes)
    def _publish_self_play_snapshot() -> None:
        if not self_play_snapshot_enabled:
            return
        if self_play_snapshot_path is None:
            raise RuntimeError("self_play_snapshot_enabled=True but snapshot path is missing.")
        snapshot_dir = os.path.dirname(self_play_snapshot_path)
        if not snapshot_dir:
            raise RuntimeError(
                "self_play_snapshot_enabled=True but snapshot path has no parent directory."
            )
        os.makedirs(snapshot_dir, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".zip",
            dir=snapshot_dir,
            delete=False,
        ) as tmp_file:
            tmp_snapshot_path = tmp_file.name
        try:
            model.save(tmp_snapshot_path)
            os.replace(tmp_snapshot_path, self_play_snapshot_path)
        finally:
            if os.path.exists(tmp_snapshot_path):
                os.remove(tmp_snapshot_path)

    # reset_num_timesteps semantics:
    # - --append: keep monotonic timesteps (never reset) for true continuation.
    # - --new: fresh run directory allows reset from zero without overwriting prior runs.
    target_episode_count = episode_offset + total_episodes
    last_snapshot_episode_count = metrics_tracker.episode_count
    if self_play_snapshot_enabled:
        _debug_train_marker("before initial self-play snapshot publish")
        _publish_self_play_snapshot()
        _debug_train_marker("after initial self-play snapshot publish")
    _debug_train_marker(
        "before learn loop: episode_count=%s target_episode_count=%s "
        "chunk_timesteps=%s model_num_timesteps=%s",
        metrics_tracker.episode_count, target_episode_count, chunk_timesteps, model.num_timesteps
    )
    # `finally` : une interruption (Ctrl-C) ou un echec est justement le moment ou l'on veut
    # savoir si le moteur bouclait. Jumeau du `finally` de `train_model`.
    try:
        while metrics_tracker.episode_count < target_episode_count:
            # As a safety guard, we still use the same chunk_timesteps. 
            # EpisodeTerminationCallback is responsible for stopping promptly when the episode budget is reached.
            _debug_train_marker(
                "before model.learn(): episode_count=%s target_episode_count=%s "
                "chunk_timesteps=%s model_num_timesteps=%s",
                metrics_tracker.episode_count, target_episode_count, chunk_timesteps,
                model.num_timesteps,
            )
            model.learn(
                total_timesteps=chunk_timesteps,
                reset_num_timesteps=(not append_training and model.num_timesteps == 0),
                tb_log_name=tb_log_name,  # Same name = continuous graph
                callback=enhanced_callbacks,
                log_interval=1,  # Every iteration so MetricsCollectionCallback captures PPO metrics
                progress_bar=False  # Disabled - using episode-based progress
            )
            _debug_train_marker(
                "after model.learn(): episode_count=%s target_episode_count=%s "
                "chunk_timesteps=%s model_num_timesteps=%s",
                metrics_tracker.episode_count, target_episode_count, chunk_timesteps,
                model.num_timesteps,
            )
            if self_play_snapshot_enabled:
                if self_play_snapshot_update_freq is None:
                    raise RuntimeError(
                        "self_play_snapshot_enabled=True but snapshot update frequency is missing."
                    )
                episodes_since_snapshot = metrics_tracker.episode_count - last_snapshot_episode_count
                if episodes_since_snapshot >= self_play_snapshot_update_freq:
                    _publish_self_play_snapshot()
                    last_snapshot_episode_count = metrics_tracker.episode_count

        # Final episode count
        episodes_trained = metrics_tracker.episode_count - episode_offset

        callback_params = require_key(training_config, "callback_params")
        save_best_robust = bool(require_key(callback_params, "save_best_robust"))

        # Final save unless robust mode owns canonical output.
        if not save_best_robust:
            _debug_train_marker("before final model.save()")
            model.save(model_path)
            # Jumeau des stats VecNormalize : sans ce compteur, la prochaine reprise leve (et sans la
            # levee, elle relancerait toutes les rampes depuis leur valeur de depart).
            save_run_state(model_path, int(metrics_tracker.episode_count))
            if save_vec_normalize(model.get_env(), model_path):
                if not silent_chunk:
                    print(f"   VecNormalize stats saved")
        elif not os.path.exists(model_path):
            bot_eval_callback = next(
                (cb for cb in training_callbacks if cb.__class__.__name__ == "BotEvaluationCallback"),
                None
            )
            extra_detail = ""
            if bot_eval_callback is not None:
                extra_detail = (
                    f" (eval_count={int(getattr(bot_eval_callback, 'eval_count', 0))}, "
                    f"eval_freq={getattr(bot_eval_callback, 'eval_freq', 'n/a')}, "
                    f"use_episode_freq={getattr(bot_eval_callback, 'use_episode_freq', 'n/a')}, "
                    f"robust_window={getattr(bot_eval_callback, 'robust_window', 'n/a')}, "
                    f"gating_enabled={getattr(bot_eval_callback, 'model_gating_enabled', 'n/a')}, "
                    f"gating_pass={getattr(bot_eval_callback, 'gating_pass_count', 'n/a')}, "
                    f"gating_fail={getattr(bot_eval_callback, 'gating_fail_count', 'n/a')})"
                )
            raise RuntimeError(
                f"Robust save mode is enabled but canonical model was not produced: {model_path}{extra_detail}"
            )
        if not silent_chunk:
            print(f"\n{'='*80}")
            print(f"✅ TRAINING COMPLETE")
            print(f"   Total episodes trained: {episodes_trained}")
            print(f"   Final model: {model_path}")
            print(f"{'='*80}\n")

        # Run final comprehensive bot evaluation
        # Le garde `if EVALUATION_BOTS_AVAILABLE:` qui enveloppait ce bloc a ete retire : le
        # drapeau valait toujours True (voir la trace en tete de fichier). Il n'a jamais empeche
        # cette evaluation finale de tourner ; il la rendait seulement silencieusement optionnelle
        # au typage.
        _debug_train_marker("before final comprehensive bot evaluation")
        n_final = require_key(training_config, "_bot_eval_final")
        if not isinstance(n_final, int) or isinstance(n_final, bool) or n_final < 0:
            raise ValueError(
                f"Resolved bot_eval_final must be an integer >= 0 (got {n_final!r})"
            )
        if n_final <= 0:
            if not silent_chunk:
                print("ℹ️  Final bot evaluation skipped (bot_eval_final=0)")
        else:
                print(f"\n{'='*80}")
                print(f"🤖 FINAL BOT EVALUATION ({n_final} episodes per bot across all scenarios)")
                print(f"{'='*80}\n")

                bot_results = evaluate_against_bots(
                    model=model,
                    training_config_name=training_config_name,
                    rewards_config_name=rewards_config_name,
                    n_episodes=n_final,
                    controlled_agent=effective_agent_key,
                    show_progress=True,
                    deterministic=True,
                    step_logger=step_logger,
                    scenario_pool="holdout",
                )

                # Log final results to metrics tracker
                if metrics_tracker and bot_results:
                    # Cette eval-la ne passe pas par `BotEvaluationCallback._apply_eval_results` :
                    # son jumeau du routage des troncatures vit donc ici (V11 §0.61).
                    metrics_tracker.log_eval_truncations(
                        require_key(bot_results, "truncations")
                    )
                    # SOURCE UNIQUE des noms de bots : `ai/bot_registry.py`. Cette liste etait
                    # ecrite a la main et restee sur le panel d'origine : sur un profil qui ne joue
                    # que les styles refondus (`x1_panel`), elle ne reconnaissait AUCUNE cle et
                    # l'evaluation finale levait « did not return any known bot score keys » —
                    # les win-rates etaient la, c'est la liste qui ne savait pas les nommer.
                    known_bot_keys = tuple(sorted(ALL_BOT_KEYS))
                    available_bot_keys = [key for key in known_bot_keys if key in bot_results]
                    if len(available_bot_keys) == 0:
                        raise ValueError(
                            "Final bot evaluation did not return any known bot score keys. "
                            f"Expected at least one of: {known_bot_keys}"
                        )
                    final_bot_results = {
                        key: float(require_key(bot_results, key))
                        for key in available_bot_keys
                    }
                    final_bot_results["combined"] = float(require_key(bot_results, "combined"))
                    metrics_tracker.log_bot_evaluations(final_bot_results)
                    # Jumeau de BotEvaluationCallback._on_training_end : le gap par roster doit
                    # etre publie au score livre, pas seulement aux evaluations intermediaires.
                    metrics_tracker.log_faction_scores(
                        require_key(bot_results, "faction_scores"),
                        bot_results.get("roster_gap"),
                    )
                    metrics_tracker.log_faction_bot_win_rates(
                        require_key(bot_results, "faction_bot_win_rates")
                    )
                    # TROISIEME site de publication des ventilations, et le seul qui porte le
                    # SCORE LIVRE : cette evaluation finale est independante, ses resultats ne
                    # repassent par aucun callback. La ventilation par roster doit y figurer pour
                    # la meme raison que celle par faction juste au-dessus — sans elle,
                    # `bot_eval/roster/*` s'arrete a la derniere evaluation intermediaire pendant
                    # que `bot_eval/faction/*` va jusqu'au bout, et les deux cessent d'etre
                    # comparables exactement au point de mesure que l'on cite.
                    for _side in ROSTER_SIDES:
                        metrics_tracker.log_roster_bot_win_rates(
                            _side,
                            require_key(bot_results, f"{_side}_roster_bot_win_rates"),
                        )
                    holdout_split_metrics = {
                        key: float(require_key(bot_results, key))
                        for key in (
                            'holdout_regular_mean',
                            'holdout_hard_mean',
                            'holdout_overall_mean',
                        )
                        if key in bot_results
                    }
                    if holdout_split_metrics:
                        metrics_tracker.log_holdout_split_metrics(holdout_split_metrics)
                    scenario_split_scores = bot_results.get("scenario_split_scores")
                    if scenario_split_scores is not None:
                        if not isinstance(scenario_split_scores, dict):
                            raise TypeError(
                                f"bot_results.scenario_split_scores must be dict "
                                f"(got {type(scenario_split_scores).__name__})"
                            )
                        metrics_tracker.log_scenario_split_scores(scenario_split_scores)

                # Print summary
                print(f"\n{'='*80}")
                print(f"📊 FINAL BOT EVALUATION RESULTS")
                print(f"{'='*80}")
                if bot_results:
                    # LISTE BLANCHE, et non plus liste noire. La boucle imprimait toute clé
                    # numérique non exclue sous la forme « vs <clé> : <valeur×100> % », si bien
                    # que chaque agrégat ajouté aux résultats se présentait comme le win-rate
                    # d'un bot inexistant : `roster_gap` (un ÉCART de 0,012) s'affichait « vs
                    # roster_gap : 1.2% » et `total_episodes_played` (un COMPTE de 360 000)
                    # « vs total_episodes_played: 360000.0% ». Les deux mesures sont utiles —
                    # elles sont imprimées plus bas, dans leur unité. Une liste noire ne peut
                    # pas protéger de la PROCHAINE clé ajoutée ; la liste blanche des bots, si.
                    for bot_name, score, wins, losses, draws in iter_bot_score_rows(bot_results):
                        print(f"  vs {bot_name:20s}: {score * 100:5.1f}% ({wins}W-{losses}L-{draws}D)")

                    combined = require_key(bot_results, 'combined') * 100
                    print(f"  Combined Score: {combined:5.1f}%")
                    # Agrégats qui ne sont PAS des win-rates de bot. Chacun dans son unité, et
                    # seulement s'il a été produit : `roster_gap` est absent d'un pool
                    # mono-faction (bot_evaluation.py, garde `ROSTER_GAP_FACTIONS`), et
                    # l'imprimer à 0,0 s'y lirait « les deux factions sont à égalité ».
                    print(f"  {'-' * 38}")
                    if 'roster_gap' in bot_results:
                        gap_points = float(bot_results['roster_gap']) * 100
                        print(
                            f"  {'Écart Spacemarine - Ork':22s}: {gap_points:+5.1f} pt "
                            f"(win-rate pondéré, agent)"
                        )
                    # Le DÉBIT et pas seulement la durée : une éval intermédiaire (600 épisodes)
                    # et une finale (3600) ne se comparent qu'en épisodes par seconde, et c'est
                    # sur ce chiffre que `bot_eval_freq` se règle — il n'était mesuré nulle part.
                    _joues = int(require_key(bot_results, 'total_episodes_played'))
                    _duree = float(require_key(bot_results, 'eval_duration_seconds'))
                    print(
                        f"  {'Épisodes joués':22s}: {_joues:d} (hors abandons) "
                        f"en {_duree:.0f} s — {_joues / _duree:.2f} ép./s"
                    )
                print(f"{'='*80}\n")

        run_info: Dict[str, Any] = {}
        bot_eval_callback = next(
            (cb for cb in training_callbacks if isinstance(cb, BotEvaluationCallback)),
            None
        )
        if bot_eval_callback is not None:
            run_info = {
                "episodes_trained": int(episodes_trained),
                "last_bot_eval": bot_eval_callback.last_eval_results,
                "last_bot_eval_marker": bot_eval_callback.last_eval_marker,
                "best_robust_score": bot_eval_callback.best_robust_score,
                "best_robust_combined": bot_eval_callback.best_robust_combined,
                "best_robust_eval_marker": bot_eval_callback.best_robust_eval_marker
            }

        if return_run_info:
            return True, model, env, run_info
        return True, model, env
    finally:
        print_truncation_summary(metrics_tracker)

def setup_callbacks(config, model_path, training_config, training_config_name="default", metrics_tracker=None,
                   total_episodes_override=None, max_episodes_override=None, scenario_info=None, global_episode_offset=0,
                   global_start_time=None, agent=None, rewards_config_name=None,
                   silent_logs: bool = False):
    W40KEngine, _ = setup_imports()
    callbacks = []
    total_eps = 0
    resume_offset = require_non_negative_int(global_episode_offset, "global_episode_offset")

    # Add episode termination callback for debug AND step configs - NO FALLBACKS
    if "total_episodes" in training_config:
        if "total_episodes" not in training_config:
            raise KeyError(f"{training_config_name} training config missing required 'total_episodes'")
        max_episodes = training_config["total_episodes"]
        # Budget par tour derive des figurines du scenario (cf. '_turn_step_limit'), pas
        # une constante de game_config : il doit suivre le roster comme le fait le garde
        # anti-runaway du moteur.
        max_steps_per_episode = get_max_turns() * require_key(
            training_config, "_turn_step_limit"
        )
        expected_timesteps = max_episodes * max_steps_per_episode
        
        # Use overrides for rotation mode
        total_eps = total_episodes_override if total_episodes_override else max_episodes
        cycle_max_eps = max_episodes_override if max_episodes_override else max_episodes

        # Recalculate expected_timesteps for the actual cycle length
        if max_episodes_override:
            expected_timesteps = max_episodes_override * max_steps_per_episode

        # EPISODE-BASED ROTATION FIX: Always use episode-based stopping (never timestep-based)
        # The callback will stop training when exact episode count is reached
        # This prevents drift from timestep estimation errors
        gate_display_state: Dict[str, Any] = {"label": "Gate 🧱"}
        training_config["_gate_display_state"] = gate_display_state
        episode_callback = EpisodeTerminationCallback(
            cycle_max_eps,  # Use cycle length, not total
            expected_timesteps,
            verbose=1,
            total_episodes=total_eps,
            scenario_info=scenario_info,
            disable_early_stopping=False,  # FIXED: Always stop at exact episode count
            global_start_time=global_start_time,
            gate_display_state=gate_display_state,
            training_config=training_config,
        )
        episode_callback.global_episode_offset = global_episode_offset
        callbacks.append(episode_callback)

    # Add entropy coefficient schedule callback if configured
    if "model_params" in training_config and "learning_rate" in training_config["model_params"]:
        lr_cfg = training_config["model_params"]["learning_rate"]
        if isinstance(lr_cfg, dict):
            if "initial" not in lr_cfg or "final" not in lr_cfg:
                raise KeyError("model_params.learning_rate dict must contain required keys: 'initial' and 'final'")
            start_lr = float(lr_cfg["initial"])
            end_lr = float(lr_cfg["final"])
            decay_fraction = float(require_key(lr_cfg, "decay_fraction"))
            total_eps = total_episodes_override if total_episodes_override else training_config["total_episodes"]
            lr_callback = LearningRateScheduleCallback(
                start=start_lr,
                end=end_lr,
                total_episodes=total_eps,
                decay_fraction=decay_fraction,
                verbose=1
            )
            callbacks.append(lr_callback)
            if not silent_logs:
                print(_describe_ramp("learning-rate", start_lr, end_lr, total_eps, decay_fraction))

    # Add entropy coefficient schedule callback if configured
    if "model_params" in training_config and "ent_coef" in training_config["model_params"]:
        ent_coef = training_config["model_params"]["ent_coef"]
        if isinstance(ent_coef, dict) and "start" in ent_coef and "end" in ent_coef:
            start_ent = float(ent_coef["start"])
            end_ent = float(ent_coef["end"])
            ent_decay_fraction = float(require_key(ent_coef, "decay_fraction"))
            total_eps = total_episodes_override if total_episodes_override else training_config["total_episodes"]

            entropy_callback = EntropyScheduleCallback(
                start=start_ent,
                end=end_ent,
                total_episodes=total_eps,
                decay_fraction=ent_decay_fraction,
                verbose=1
            )
            callbacks.append(entropy_callback)
            if not silent_logs:
                print(_describe_ramp("entropy", start_ent, end_ent, total_eps, ent_decay_fraction))

    # Evaluation callback - test model periodically with logging enabled
    # Load scenario and unit registry for evaluation callback
    from ai.unit_registry import UnitRegistry
    cfg = get_config_loader()
    
    # Load callback parameters for CheckpointCallback
    if "callback_params" not in training_config:
        raise KeyError("Training config missing required 'callback_params' field")
    callback_params = training_config["callback_params"]
    
    required_callback_fields = ["checkpoint_save_freq", "checkpoint_name_prefix"]
    for field in required_callback_fields:
        if field not in callback_params:
            raise KeyError(f"callback_params missing required '{field}' field")
    
    # Checkpoint callback - save model periodically
    # Use reasonable checkpoint frequency based on total timesteps and config
    if "checkpoint_save_freq" not in callback_params:
        raise KeyError("callback_params missing required 'checkpoint_save_freq' field")
    if "checkpoint_name_prefix" not in callback_params:
        raise KeyError("callback_params missing required 'checkpoint_name_prefix' field")

    max_checkpoints = callback_params.get("max_checkpoints")
    if max_checkpoints is not None:
        if not isinstance(max_checkpoints, int) or isinstance(max_checkpoints, bool):
            raise ValueError(
                "callback_params.max_checkpoints must be an integer when provided "
                f"(got {type(max_checkpoints).__name__})"
            )
        if max_checkpoints <= 0:
            raise ValueError(
                f"callback_params.max_checkpoints must be > 0 when provided (got {max_checkpoints})"
            )

        checkpoint_callback = RotatingCheckpointCallback(
            max_checkpoints=max_checkpoints,
            save_freq=callback_params["checkpoint_save_freq"],
            save_path=os.path.dirname(model_path),
            name_prefix=callback_params["checkpoint_name_prefix"],
        )
    else:
        checkpoint_callback = VecNormalizeCheckpointCallback(
            save_freq=callback_params["checkpoint_save_freq"],
            save_path=os.path.dirname(model_path),
            name_prefix=callback_params["checkpoint_name_prefix"],
        )
    # Hors rotation, le tracker est cree plus tard (dans `train_model`, qui pose l'attribut).
    if metrics_tracker is not None:
        checkpoint_callback.metrics_tracker = metrics_tracker
    callbacks.append(checkpoint_callback)
    
    # Add enhanced bot evaluation callback (replaces standard EvalCallback)
    # Le garde `if EVALUATION_BOTS_AVAILABLE:` et sa branche `else` ont ete retires : le
    # drapeau valait toujours True (voir la trace en tete de fichier). L'else avertissait
    # « Evaluation bots not available - no evaluation metrics / Install evaluation_bots.py »
    # pour un fichier qui est dans le depot ; surtout, si le drapeau avait pu etre faux, ce
    # garde aurait silencieusement prive l'entrainement de sa callback d'evaluation.
    # Resolve nested callback params that can explicitly inherit from shared training config.
    shared_training_config = cfg.load_training_common_config()

    def _resolve_callback_value(key: str) -> Any:
        value = callback_params[key] if key in callback_params else None
        if value is not None:
            return value
        if key not in shared_training_config:
            raise KeyError(
                f"callback_params.{key} is missing/null and config/agents/_training_common.json "
                f"does not define '{key}'"
            )
        shared_value = shared_training_config[key]
        if shared_value is None:
            raise ValueError(
                f"Invalid shared value for callback_params.{key}: "
                f"config/agents/_training_common.json defines null"
            )
        return shared_value

    # Read bot evaluation parameters from config
    bot_eval_freq = _resolve_callback_value("bot_eval_freq")
    bot_n_episodes_intermediate = _resolve_callback_value("bot_eval_intermediate")
    bot_eval_use_episodes = require_key(callback_params, "bot_eval_use_episodes")
    eval_deterministic = require_key(callback_params, "eval_deterministic")
    if not isinstance(bot_eval_freq, int) or isinstance(bot_eval_freq, bool) or bot_eval_freq <= 0:
        raise ValueError(
            f"callback_params.bot_eval_freq must be a positive integer "
            f"(got {bot_eval_freq!r})"
        )
    if (
        not isinstance(bot_n_episodes_intermediate, int)
        or isinstance(bot_n_episodes_intermediate, bool)
        or bot_n_episodes_intermediate < 0
    ):
        raise ValueError(
            f"callback_params.bot_eval_intermediate must be an integer >= 0 "
            f"(got {bot_n_episodes_intermediate!r})"
        )
    if not isinstance(bot_eval_use_episodes, bool):
        raise ValueError(
            f"callback_params.bot_eval_use_episodes must be boolean "
            f"(got {type(bot_eval_use_episodes).__name__})"
        )
    if not isinstance(eval_deterministic, bool):
        raise ValueError(
            f"callback_params.eval_deterministic must be boolean "
            f"(got {type(eval_deterministic).__name__})"
        )
    bot_eval_scenario_pool = str(_resolve_callback_value("bot_eval_scenario_pool"))
    bot_eval_show_progress = bool(_resolve_callback_value("bot_eval_show_progress"))
    if not isinstance(bot_eval_show_progress, bool):
        raise ValueError(
            f"callback_params.bot_eval_show_progress must be boolean "
            f"(got {type(bot_eval_show_progress).__name__})"
        )
    # Parallelisation de l'evaluation bot : validee ICI, au demarrage, avec ses soeurs — et non
    # dans `evaluate_against_bots`, qui n'est atteinte qu'au premier marqueur d'evaluation, donc
    # apres des minutes d'entrainement. La fabrique est partagee avec ce point d'entree, qui
    # revalide pour son propre compte (il sert aussi a evaluer hors entrainement).
    from ai.bot_evaluation import validate_bot_eval_worker_params

    validate_bot_eval_worker_params(callback_params)
    save_best_robust = bool(_resolve_callback_value("save_best_robust"))
    model_gating_enabled = bool(_resolve_callback_value("model_gating_enabled"))
    model_gating_min_combined = None
    model_gating_min_worst_bot = None
    model_gating_min_worst_scenario_combined = None
    # Resolu INCONDITIONNELLEMENT : ce plancher mord meme gating desarme (cf.
    # `BotEvaluationCallback._evaluate_model_gate`). 0.0 est le seul moyen de le neutraliser.
    #
    # ⚠️ Lu DIRECTEMENT dans le profil de l'agent, SANS passer par `_resolve_callback_value` :
    # ce seuil decide si un modele est sauve ou jete, il doit etre un choix explicite du profil
    # qu'on lance, jamais une valeur heritee d'un fichier commun a tous les agents. Son absence
    # est une erreur, pas un defaut a 0.40. (`config/agents/_training_common.json` ne le definit
    # donc pas — verrou : tests/unit/ai/test_model_gate_control_floor.py.)
    if "model_gating_min_vs_control" not in callback_params:
        raise KeyError(
            "callback_params.model_gating_min_vs_control est OBLIGATOIRE dans le profil "
            "d'entrainement de l'agent (aucun repli sur _training_common.json) : ce plancher "
            "decide de la sauvegarde d'un modele. Mettre 0.0 pour le desarmer explicitement."
        )
    raw_min_vs_control = callback_params["model_gating_min_vs_control"]
    if raw_min_vs_control is None:
        raise ValueError(
            "callback_params.model_gating_min_vs_control vaut null : renseigner un nombre "
            "(0.0 pour desarmer le plancher)."
        )
    model_gating_min_vs_control = float(raw_min_vs_control)
    if model_gating_min_vs_control < 0.0 or model_gating_min_vs_control > 1.0:
        raise ValueError(
            "callback_params.model_gating_min_vs_control must be between 0.0 and 1.0 "
            f"(got {model_gating_min_vs_control})"
        )
    if model_gating_enabled or save_best_robust:
        if model_gating_enabled:
            model_gating_min_combined = float(_resolve_callback_value("model_gating_min_combined"))
        model_gating_min_worst_bot = float(_resolve_callback_value("model_gating_min_worst_bot"))
        model_gating_min_worst_scenario_combined = float(
            _resolve_callback_value("model_gating_min_worst_scenario_combined")
        )
        for key, value in (
            *(
                [("model_gating_min_combined", model_gating_min_combined)]
                if model_gating_enabled
                else []
            ),
            ("model_gating_min_worst_bot", model_gating_min_worst_bot),
            ("model_gating_min_worst_scenario_combined", model_gating_min_worst_scenario_combined),
        ):
            value_f = require_present(value, key)
            if value_f < 0.0 or value_f > 1.0:
                raise ValueError(
                    f"callback_params.{key} must be between 0.0 and 1.0 (got {value_f})"
                )
    robust_window = 3
    robust_drawdown_penalty = 0.5
    robust_penalty_bot = 0.0
    robust_penalty_hard = 0.0
    save_best_robust_seed = False
    robust_seed_value: Optional[int] = None
    if save_best_robust:
        robust_window = int(_resolve_callback_value("robust_window"))
        robust_drawdown_penalty = float(_resolve_callback_value("robust_drawdown_penalty"))
        save_best_robust_seed = bool(callback_params.get("save_best_robust_seed", False))
        if save_best_robust_seed:
            if "agent_seat_seed" in training_config:
                seed_raw = require_key(training_config, "agent_seat_seed")
            elif "seed" in training_config:
                seed_raw = require_key(training_config, "seed")
            else:
                raise KeyError(
                    "callback_params.save_best_robust_seed=true requires "
                    "'agent_seat_seed' or 'seed' in training config"
                )
            if not isinstance(seed_raw, int) or isinstance(seed_raw, bool):
                raise ValueError(
                    "Seed used for robust filename must be an integer "
                    f"(got {type(seed_raw).__name__})"
                )
            robust_seed_value = int(seed_raw)
        robust_penalty_bot = float(require_key(callback_params, "robust_penalty_bot"))
        robust_penalty_hard = float(require_key(callback_params, "robust_penalty_hard"))
        if robust_penalty_bot < 0.0:
            raise ValueError(
                f"robust_penalty_bot must be >= 0.0 (got {robust_penalty_bot})"
            )
        if robust_penalty_hard < 0.0:
            raise ValueError(
                f"robust_penalty_hard must be >= 0.0 (got {robust_penalty_hard})"
            )
        if robust_window <= 0:
            raise ValueError(
                f"callback_params.robust_window must be > 0 (got {robust_window})"
            )
        if bot_eval_use_episodes:
            expected_evals = int(total_eps) // int(bot_eval_freq)
            if expected_evals <= 0:
                raise ValueError(
                    "Invalid robust-eval configuration: save_best_robust=true but no bot evaluation "
                    f"will run in this phase (total_episodes={int(total_eps)}, "
                    f"bot_eval_freq={int(bot_eval_freq)}). "
                    "Reduce bot_eval_freq or increase total_episodes."
                )
            if expected_evals < robust_window:
                raise ValueError(
                    "Invalid robust-eval configuration: save_best_robust=true but "
                    f"robust_window={robust_window} requires at least {robust_window} evaluations, "
                    f"while this phase can run at most {expected_evals} "
                    f"(total_episodes={int(total_eps)}, bot_eval_freq={int(bot_eval_freq)}). "
                    "Reduce robust_window, reduce bot_eval_freq, or increase total_episodes."
                )

    # Store final eval count for use after training completes
    training_config["_bot_eval_final"] = _resolve_callback_value("bot_eval_final")

    if not rewards_config_name:
        raise KeyError("setup_callbacks requires rewards_config_name for BotEvaluationCallback")
    if bot_n_episodes_intermediate <= 0:
        if not silent_logs:
            print("ℹ️  Intermediate bot evaluation skipped (bot_eval_intermediate=0)")
    else:
        bot_eval_callback = BotEvaluationCallback(
            eval_freq=bot_eval_freq,
            n_eval_episodes=bot_n_episodes_intermediate,
            best_model_save_path=os.path.dirname(model_path),
            metrics_tracker=metrics_tracker,
            use_episode_freq=bot_eval_use_episodes,
            verbose=1,
            training_config_name=training_config_name,
            rewards_config_name=rewards_config_name,
            scenario_pool=bot_eval_scenario_pool,
            save_best_robust=save_best_robust,
            save_best_robust_seed=save_best_robust_seed,
            robust_seed_value=robust_seed_value,
            robust_window=robust_window,
            robust_drawdown_penalty=robust_drawdown_penalty,
            robust_penalty_bot=robust_penalty_bot,
            robust_penalty_hard=robust_penalty_hard,
            model_gating_enabled=model_gating_enabled,
            model_gating_min_combined=model_gating_min_combined,
            model_gating_min_worst_bot=model_gating_min_worst_bot,
            model_gating_min_worst_scenario_combined=model_gating_min_worst_scenario_combined,
            model_gating_min_vs_control=model_gating_min_vs_control,
            gate_display_state=training_config.get("_gate_display_state"),
            eval_deterministic=eval_deterministic,
            # Cible CUMULATIVE, comme `target_episode_count` dans train_model : le compteur du
            # tracker est amorce a l'offset de reprise (`initial_episode_count`).
            final_summary_target_episodes=resume_offset + total_eps,
            initial_episode_marker=resume_offset,
            show_eval_progress=bot_eval_show_progress,
            early_stopping_patience=int(callback_params["early_stopping_patience"]),
            save_best_min_episodes=int(callback_params["save_best_min_episodes"]),
        )
        callbacks.append(bot_eval_callback)

    # `freq_unit = "episodes" if bot_eval_use_episodes else "timesteps"` occupait cette ligne :
    # variable locale assignee et jamais lue, vestige d'un message de log disparu.

    return callbacks

def train_model(model, training_config, callbacks, model_path, training_config_name, rewards_config_name,
                controlled_agent=None, episode_offset: int = 0):
    """Execute the training process with metrics tracking.

    `episode_offset` : episodes deja joues par ce modele lors d'un run precedent (reprise). Le
    compteur du tracker est CUMULATIF — c'est lui qui est persiste a chaque sauvegarde. Parti de
    zero sur un `--append`, il ECRASERAIT le compte du modele par celui du seul run courant, et
    la reprise suivante repartirait presque du debut (cf. ai/run_state.py).
    """
    
    # Import metrics tracker
    from ai.metrics_tracker import W40KMetricsTracker, resolve_perf_windows
    
    # Extract agent name from model path for metrics
    agent_name = "default_agent"
    if "_" in os.path.basename(model_path):
        agent_name = os.path.basename(model_path).replace('.zip', '').replace('model_', '')
    
    # CRITICAL FIX: Use model's TensorBoard directory for metrics_tracker
    # SB3 creates subdirectories like ./tensorboard/PPO_1/
    # metrics_tracker MUST write to the SAME directory to appear in TensorBoard
    # Access tensorboard_log from model parameters (logger not initialized until learn() is called)
    if hasattr(model, 'tensorboard_log') and model.tensorboard_log:
        model_tensorboard_dir = model.tensorboard_log
        print(f"📊 Metrics will be logged to: {model_tensorboard_dir}")
    else:
        model_tensorboard_dir = "./tensorboard/"
        print(f"⚠️  No tensorboard_log found, using default: {model_tensorboard_dir}")
   
    # Create metrics tracker using model's directory
    _perf_window, _perf_window_fast = resolve_perf_windows(training_config)
    metrics_tracker = W40KMetricsTracker(
        agent_name,
        model_tensorboard_dir,
        perf_window=_perf_window,
        perf_window_fast=_perf_window_fast,
        initial_episode_count=episode_offset,
    )
    
    try:
        # Start training
        # AI_TURN COMPLIANCE: Use episode-based training
        if 'total_timesteps' in training_config:
            total_timesteps = training_config['total_timesteps']
            safety_timesteps = total_timesteps
            print(f"🎯 Training Mode: Step-based ({total_timesteps:,} steps)")
        elif 'total_episodes' in training_config:
            total_episodes = training_config['total_episodes']
            # Calculate timesteps based on required config values - NO DEFAULTS ALLOWED
            max_turns_per_episode = get_max_turns()
            # cf. '_turn_step_limit' : budget par tour derive des figurines du scenario.
            max_steps_per_turn = require_key(training_config, "_turn_step_limit")
            
            # CRITICAL FIX: Episode count controlled by EpisodeTerminationCallback, not timesteps
            # Use 5x multiplier to ensure timestep limit never stops training early
            # This accounts for complex scenarios (more units = longer episodes)
            theoretical_timesteps = total_episodes * max_turns_per_episode * max_steps_per_turn
            total_timesteps = theoretical_timesteps * 5
            
            print(f"🎮 Training Mode: Episode-based ({total_episodes:,} episodes)")
            print(f"📊 Theoretical timesteps: {theoretical_timesteps:,}")
            print(f"🛡️ Timestep limit (5x buffer): {total_timesteps:,}")
            print(f"💡 EpisodeTerminationCallback will stop at exactly {total_episodes} episodes")
        else:
            raise ValueError("Training config must have either 'total_timesteps' or 'total_episodes'")
        
        # Startup info (disabled for cleaner output)
        # print(f"📊 Progress tracking: Episodes are primary metric (AI_TURN.md compliance)")
        # print(f"📈 Metrics tracking enabled for agent: {agent_name}")
        
        # Enhanced callbacks with metrics collection
        metrics_callback = MetricsCollectionCallback(metrics_tracker, model, controlled_agent=controlled_agent)
        
        # Attach metrics_tracker to bot_eval_callback if it exists
        for callback in callbacks:
            if isinstance(callback, BotEvaluationCallback):
                callback.metrics_tracker = metrics_tracker
                print(f"✅ Linked BotEvaluationCallback to metrics_tracker")
        
        # Les callbacks arrivent de `setup_callbacks`, appelee AVANT que ce tracker n'existe :
        # c'est ici que le compteur d'episodes rejoint les checkpoints (cf. ai/run_state.py).
        for _callback in callbacks:
            if isinstance(_callback, VecNormalizeCheckpointCallback):
                _callback.metrics_tracker = metrics_tracker

        all_callbacks = callbacks + [metrics_callback]
        enhanced_callbacks = CallbackList(all_callbacks)
        
        # Use consistent naming: training_config_agent_key
        tb_log_name = f"{training_config_name}_{agent_name}"
        
        model.learn(
            total_timesteps=total_timesteps,
            tb_log_name=tb_log_name,
            callback=enhanced_callbacks,
            log_interval=1,  # Every iteration so MetricsCollectionCallback captures PPO metrics
            progress_bar=False  # Disabled - scenario mode uses episode-based progress
        )
        
        # Print final training summary with critical metrics and bot evaluation
        metrics_callback.print_final_training_summary(model=model, training_config=training_config, training_config_name=training_config_name, rewards_config_name=rewards_config_name)
        
        callback_params = require_key(training_config, "callback_params")
        save_best_robust = bool(require_key(callback_params, "save_best_robust"))

        # Save final model unless robust mode owns canonical output.
        if not save_best_robust:
            os.makedirs(os.path.dirname(model_path), exist_ok=True)
            model.save(model_path)
            save_run_state(model_path, int(metrics_tracker.episode_count))
            if save_vec_normalize(model.get_env(), model_path):
                print(f"   VecNormalize stats saved")
        
        # Clean up checkpoint files after successful training
        model_dir = os.path.dirname(model_path)
        checkpoint_pattern = os.path.join(model_dir, "ppo_*_steps.zip")
        checkpoint_files = glob.glob(checkpoint_pattern)
        
        if checkpoint_files:
            print(f"\n🧹 Cleaning up {len(checkpoint_files)} checkpoint files...")
            for checkpoint_file in checkpoint_files:
                try:
                    os.remove(checkpoint_file)
                    checkpoint_vec_path = get_vec_normalize_path(checkpoint_file)
                    if os.path.exists(checkpoint_vec_path):
                        os.remove(checkpoint_vec_path)
                    if verbose := 0:  # Only log if verbose
                        print(f"   Removed: {os.path.basename(checkpoint_file)}")
                except Exception as e:
                    print(f"   ⚠️  Could not remove {os.path.basename(checkpoint_file)}: {e}")
            print(f"✅ Checkpoint cleanup complete")
        
        # Also remove interrupted file if it exists — WITH its per-model VecNormalize stats
        # (V11 §0.35) : supprimer le zip en laissant le pkl fabrique un artefact orphelin.
        interrupted_path = model_path.replace('.zip', '_interrupted.zip')
        if os.path.exists(interrupted_path):
            try:
                os.remove(interrupted_path)
                interrupted_vec_path = get_vec_normalize_path(interrupted_path)
                if os.path.exists(interrupted_vec_path):
                    os.remove(interrupted_vec_path)
                print(f"🧹 Removed old interrupted file")
            except Exception as e:
                print(f"   ⚠️  Could not remove interrupted file: {e}")
        
        return True
        
    except KeyboardInterrupt:
        print("\n⏹️ Training interrupted by user")
        # Save current progress
        interrupted_path = model_path.replace('.zip', '_interrupted.zip')
        model.save(interrupted_path)
        save_run_state(interrupted_path, int(metrics_tracker.episode_count))
        if save_vec_normalize(model.get_env(), interrupted_path):
            print("   VecNormalize stats saved")
        print(f"💾 Progress saved to: {interrupted_path}")
        return False
        
    except Exception as e:
        print(f"❌ Training failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Dans le `finally` : une interruption ou un echec est justement le moment ou l'on veut
        # savoir si le moteur bouclait.
        print_truncation_summary(metrics_tracker)
        close_training_env(model.get_env(), "fin d'entraînement")

def resolve_final_eval_scenarios(config, agent_key, training_config_name):
    """Scenario de l'evaluation post-entrainement (`--test-episodes N`) : HOLDOUT, jamais moins.

    Deux raisons de ne pas laisser cette resolution a `test_trained_model` :

    1. QUOI. Le pool d'ENTRAINEMENT (`bot`/`self`) mesurerait le win-rate sur les scenarios qui
       viennent de servir a entrainer — un chiffre "Test Results" qui ne dit rien de la
       generalisation. Le chemin `--test-only` refuse deja explicitement `--scenario bot` et
       impose le holdout : c'est le meme jumeau, il tient la meme regle. Cela retire du meme
       coup la dependance au mode d'entrainement (`bot` code en dur cassait `--scenario self`).
    2. QUAND. Appelee AVANT l'entrainement (cf. `main`), l'absence de holdout est refusee en
       quelques millisecondes. Resolue au moment de l'eval, elle levait APRES un entrainement
       reussi, et `main()` sortait en code 1 sur un run de plusieurs heures.

    Rend la liste COMPLETE, pas un element. `get_scenario_list_for_phase` rend un
    `sorted(set(...))` de chemins complets ou `holdout_hard` trie AVANT `holdout_regular` :
    un `[0]` nu n'evaluait qu'un scenario sur les quatre, et basculait silencieusement du
    regular vers le hard le jour ou un agent gagne un dossier `holdout_hard/` — le win-rate
    aurait baisse sans aucun changement de code, et la lecture evidente aurait ete
    « regression du modele ». Le choix du sous-ensemble ne peut pas etre un accident
    alphabetique : on les joue TOUS, et le detail par scenario est imprime.
    """
    holdout_scenarios = get_scenario_list_for_phase(
        config, agent_key, training_config_name, scenario_type="holdout"
    )
    if not holdout_scenarios:
        raise FileNotFoundError(
            f"L'evaluation exige un scenario de holdout pour '{agent_key}' "
            f"(phase '{training_config_name}') : aucun trouve sous "
            f"config/agents/{agent_key}/scenarios/holdout_regular|holdout_hard/. "
            f"L'evaluation ne se mesure pas sur les scenarios d'entrainement."
        )
    return holdout_scenarios


def test_trained_model(model, num_episodes, training_config_name, rewards_config_name,
                       scenario_files, debug_mode=False):
    """Test the trained model.

    `scenario_files` est RESOLU PAR L'APPELANT (`resolve_final_eval_scenarios`, joue avant
    l'entrainement). Cette fonction chargeait `config/scenario.json`, un fichier absent du
    depot : `--test-episodes > 0` mourait au fond de `_load_units_from_scenario`, sans
    qu'aucune ligne ne nomme l'exigence.

    TOUS les scenarios de holdout sont joues, les episodes repartis entre eux : n'en mesurer
    qu'un rendait un chiffre dependant du tri alphabetique des dossiers. Le detail par scenario
    est imprime — une moyenne globale cache un holdout ou le modele s'effondre.

    `controlled_agent` est la cle de RECOMPENSES, pas `--agent` : c'est elle qui porte le
    suffixe de phase, et c'est ce que passent les deux jumeaux (`train_model` et l'eval
    `--test-only`). Sur un `--agent A --rewards-config B`, l'ancienne version calculait
    l'« Average Reward » final sous la table de A alors que l'entrainement l'avait optimisee
    sous celle de B — deux chiffres incomparables sous le meme libelle.
    """
    if num_episodes <= 0:
        raise ValueError("num_episodes must be positive - no default episodes allowed")
    if not scenario_files:
        raise ValueError("scenario_files est vide : rien a evaluer")

    W40KEngine, _ = setup_imports()
    # Load unit registry for testing
    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()

    # Repartition round-robin : le reste va aux PREMIERS scenarios, aucun episode perdu.
    per_scenario = [num_episodes // len(scenario_files)] * len(scenario_files)
    for i in range(num_episodes % len(scenario_files)):
        per_scenario[i] += 1

    wins = 0
    total_rewards = []
    per_scenario_results = []

    for scenario_file, episodes_here in zip(scenario_files, per_scenario):
        if episodes_here == 0:
            print(f"⏭️  {os.path.basename(scenario_file)} : 0 episode "
                  f"(--test-episodes {num_episodes} < {len(scenario_files)} scenarios de holdout)")
            continue
        print(f"📋 Holdout {os.path.basename(scenario_file)} : {episodes_here} episode(s)")
        env = W40KEngine(
            rewards_config=rewards_config_name,
            training_config_name=training_config_name,
            controlled_agent=rewards_config_name,
            active_agents=None,
            scenario_file=scenario_file,
            unit_registry=unit_registry,
            quiet=True,
            training_n_envs=1,  # test_trained_model : UN environnement, joue en serie
            debug_mode=debug_mode
        )
        scenario_wins = 0
        try:
            for _episode in range(episodes_here):
                obs, info = env.reset()
                episode_reward = 0
                done = False
                step_count = 0

                while not done and step_count < 1000:  # Prevent infinite loops
                    # Standard PPO doesn't support action masking
                    action, _ = model.predict(obs, deterministic=True)

                    obs, reward, terminated, truncated, info = env.step(action)
                    episode_reward += reward
                    done = terminated or truncated
                    step_count += 1

                total_rewards.append(episode_reward)

                # CRITICAL FIX: Learning agent is Player 0, not Player 1!
                if require_key(info, 'winner') == 0:  # AI (Player 0) won
                    scenario_wins += 1
        finally:
            env.close()
        wins += scenario_wins
        per_scenario_results.append(
            (os.path.basename(scenario_file), scenario_wins, episodes_here)
        )

    win_rate = wins / num_episodes
    avg_reward = sum(total_rewards) / len(total_rewards)

    print(f"\n📊 Test Results (holdout, {len(per_scenario_results)} scenario(s)):")
    for name, scenario_wins, episodes_here in per_scenario_results:
        print(f"   {name}: {scenario_wins / episodes_here:.1%} ({scenario_wins}/{episodes_here})")
    print(f"   Win Rate: {win_rate:.1%} ({wins}/{num_episodes})")
    print(f"   Average Reward: {avg_reward:.2f}")
    print(f"   Reward Range: {min(total_rewards):.2f} to {max(total_rewards):.2f}")

    return win_rate, avg_reward


def _non_empty_key(flag: str):
    """Valide une cle d'agent passee en argument : ni vide, ni entouree d'espaces.

    `required=True` n'exige que la PRESENCE du drapeau. Une chaine vide traversait argparse
    puis desamorcait les gardes ecrites en `if agent_key:` (`_require_training_config_phase`
    notamment, qui aurait laisse passer un --training-config absent).

    La valeur rendue est NETTOYEE, pas la brute : `" CoreAgent"` se propageait tel quel dans
    `config/agents/ CoreAgent/` et `ai/models/ CoreAgent/`, l'espace inclus dans le chemin.

    Applique aux DEUX drapeaux qui nomment un dossier de config : `--agent` et
    `--rewards-config`. Ne le poser que sur le premier laissait la porte grande ouverte —
    `--rewards-config " CoreAgent"` atteint exactement les memes chemins.
    """
    def _parse(value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise argparse.ArgumentTypeError(f"{flag} ne peut pas etre vide")
        return stripped

    return _parse


_non_empty_agent = _non_empty_key("--agent")


def main():
    """Main training function following AI_INSTRUCTIONS.md exactly."""
    parser = argparse.ArgumentParser(description="Train W40K AI (see Documentation/AI_TURN.md and AI_IMPLEMENTATION.md)")
    parser.add_argument("--training-config", default=None,
                       help="Training config phase name (required, no silent default; e.g. x1, x1_debug)")
    parser.add_argument("--rewards-config", default=None, type=_non_empty_key("--rewards-config"),
                       help="Rewards config (default: same as --agent)")
    parser.add_argument("--new", action="store_true", 
                       help="Force creation of new model")
    parser.add_argument("--append", action="store_true",
                       help="Continue training existing model")
    parser.add_argument("--resume-from", type=str, default=None, metavar="CHECKPOINT_ZIP",
                       help="Reprendre l'entrainement depuis un checkpoint (ex: "
                            "ai/models/<agent>/ppo_checkpoint_640000_steps.zip). Le checkpoint et "
                            "ses stats VecNormalize sont installes au chemin canonique du modele "
                            "(l'ancien est ecarte, pas ecrase) puis --append est active.")
    parser.add_argument("--test-only", "--eval", action="store_true",
                       help="Only test existing model, don't train")
    parser.add_argument("--test-episodes", type=int, default=0, 
                       help="Number of episodes for testing")
    # OBLIGATOIRE : le mode « generique » sans agent n'existe plus (il ne savait pas resoudre
    # l'agent controle). Tous les modes survivants resolvent leur config, leur scenario ou leur
    # modele depuis --agent. Refuser ici, a l'analyse des arguments, plutot qu'apres la
    # construction du StepLogger et la resynchronisation des configs frontend (`node
    # scripts/copy-configs.js`), qui sont des effets de bord payes pour rien.
    # `required` ne garantit que la PRESENCE : `--agent ""` passerait, et la chaine vide
    # desamorce silencieusement les gardes ecrites en `if agent_key:`. D'ou le validateur.
    parser.add_argument("--agent", type=_non_empty_agent, required=True,
                       help="Train specific agent (e.g., 'SpaceMarine_Ranged')")
    parser.add_argument("--total-episodes", type=int, default=None,
                       help="Total episodes for training (overrides config file value)")
    parser.add_argument("--step", action="store_true",
                       help="Enable step-by-step action logging to step.log")
    parser.add_argument("--convert-steplog", type=str, metavar="STEPLOG_FILE",
                       help="Convert existing steplog file to replay JSON format")
    parser.add_argument("--replay", action="store_true", 
                       help="Generate steplog AND convert to replay in one command")
    parser.add_argument("--model", type=str, default=None,
                       help="Specific model file to use for replay generation")
    parser.add_argument("--scenario-template", type=str, default=None,
                       help="Scenario template name from scenario_templates.json for replay generation")
    parser.add_argument("--scenario", type=str, default="default",
                       help="Scenario (default: default; use 'bot' for bot training)")
    # --macro-eval-mode retire : il ne pilotait que les branches --agent MacroController,
    # elles-memes supprimees (voir la trace au-dessus de resolve_turn_step_limit).
    parser.add_argument("--mode", type=str, default=None,
                       help="Force training device: CPU or GPU (case-insensitive). If omitted, auto-selects based on network size and GPU availability.")
    parser.add_argument("--rule-checker", action="store_true",
                       help="Train only on rule-checker scenarios, REGENERES au lancement dans config/rule_checker/ depuis les RULES_STATUS des rosters (no implicit scenario list).")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug console output (verbose logging)")
    parser.add_argument("--param", action="append", nargs=2, metavar=("KEY", "VALUE"),
                       help="Override config parameter (e.g. n_steps 10240 or model_params.batch_size 2048). Can be repeated.")
    parser.add_argument("--resolution", type=int, choices=[1, 5, 10], default=None,
                       help="Board resolution: 1 (44x60x1 = 44x60, 1 hex = 1 pouce, banc rapide) "
                            "ou 5 (44x60x5 = 220x300, resolution de reference). Les donnees d'un "
                            "scenario ne se convertissent que vers une resolution PLUS GROSSIERE : "
                            "10 (44x60x10 = 360x312) exige un scenario dont board_ref est deja en "
                            "x10, sinon erreur explicite. Overrides W40K_BOARD_PATH env var.")

    args = parser.parse_args()

    from config_loader import BOARD_DIR_BY_INCHES_TO_SUBHEX
    if args.resolution is not None:
        os.environ["W40K_BOARD_PATH"] = BOARD_DIR_BY_INCHES_TO_SUBHEX[args.resolution]

    # `--new` cree un modele neuf, `--append` continue l'existant : c'est l'un OU l'autre. Rien
    # dans argparse ne les rend exclusifs, et le code choisissait `--new` en silence — une
    # commande dont un drapeau ne sert a rien est une faute de frappe, pas une intention.
    if args.new and args.append:
        raise ValueError(
            "--new et --append sont exclusifs : --new cree un modele neuf (et ecarte le "
            "precedent), --append continue le modele existant."
        )

    if args.resume_from:
        if args.new:
            raise ValueError("--resume-from et --new sont exclusifs (--new repartirait de zero)")
        args.append = True

    # Default rewards-config to agent (simplifies: --agent X implies rewards X)
    if args.rewards_config is None:
        args.rewards_config = args.agent

    # Apply --param overrides to config loader (affects all subsequent config loads)
    if args.param:
        config = get_config_loader()
        _original_load = config.load_agent_training_config

        _overrides_logged = False

        def _load_with_overrides(agent_key: str, phase: Optional[str] = None) -> Dict[str, Any]:
            nonlocal _overrides_logged
            cfg = _original_load(agent_key, phase)
            if isinstance(cfg, dict):
                _apply_param_overrides(cfg, args.param, log_overrides=not _overrides_logged)
                _overrides_logged = True
            return cfg

        config.load_agent_training_config = _load_with_overrides
        print(f"⚙️  Param overrides: {len(args.param)} parameter(s) will override config file")

    print("🎮 W40K AI Training (AI_TURN.md / AI_IMPLEMENTATION.md)")
    print("=" * 70)
    print(f"Training config: {args.training_config}")
    print(f"Rewards config: {args.rewards_config}")
    print(f"New model: {args.new}")
    print(f"Append training: {args.append}")
    print(f"Test only: {args.test_only}")
    print(f"Step logging: {args.step}")
    print(f"Rule-checker mode: {args.rule_checker}")
    print(f"Debug mode: {args.debug}")
    if args.resolution is not None:
        print(f"Resolution: x{args.resolution} ({BOARD_DIR_BY_INCHES_TO_SUBHEX[args.resolution]})")
    if args.mode:
        print(f"Device mode: {args.mode}")
    if args.param:
        print(f"Param overrides: {args.param}")
    if args.convert_steplog:
        print(f"Convert steplog: {args.convert_steplog}")
    if args.replay:
        print(f"Replay generation: {args.replay}")
        if args.model:
            print(f"Model file: {args.model}")
        else:
            print(f"Model file: auto-detect")
    print()
    
    try:
        # Reset debug.log cleared flag at the start of each training run
        # This ensures debug.log is cleared even if the module was already loaded
        from engine.w40k_core import reset_debug_log_flag
        reset_debug_log_flag()
        
        # Setup environment and configuration (before step_logger to read step_log_buffer_size)
        config = get_config_loader()
        if args.resume_from:
            _promote_checkpoint_for_resume(args.resume_from, args.agent, config)
        _require_training_config_phase(config, args.agent, args.training_config)
        tc = config.load_agent_training_config(args.agent, args.training_config)
        step_log_buffer_size = int(require_key(tc, "step_log_buffer_size"))
        # Initialize global step logger based on --step argument
        global step_logger
        step_logger = StepLogger(
            os.path.join(project_root, "step.log"),
            enabled=args.step,
            buffer_size=step_log_buffer_size,
            debug_mode=args.debug,
        )
        
        # Sync configs to frontend automatically
        try:
            subprocess.run(['node', 'scripts/copy-configs.js'], 
                         cwd=project_root, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Config sync failed: {e}")
        
        # Convert existing steplog mode
        if args.convert_steplog:
            # Le scenario est resolu depuis --agent, comme pour --replay. Il transitait avant par
            # un attribut de fonction que ce chemin ne posait jamais, donc il retombait sur
            # `config/scenario.json` : un fichier absent du depot, et donc un FileNotFoundError
            # systematique. --agent est desormais requis, et l'erreur le dit.
            success = convert_steplog_to_replay(
                args.convert_steplog,
                resolve_agent_bot_scenario(config, args.agent),
            )
            return 0 if success else 1

        # Generate steplog AND convert to replay (one-shot mode)
        if args.replay:
            success = generate_steplog_and_replay(config, args)
            return 0 if success else 1

        # Test-only mode - check BEFORE training
        if args.test_only:
            # La branche --test-only --agent MacroController a ete retiree ici : elle
            # appelait _build_macro_eval_env, qui levait NotImplementedError sans condition.
            # Voir la trace au-dessus de resolve_turn_step_limit.

            # Load existing model
            models_root = config.get_models_root()
            model_path = build_agent_model_path(models_root, args.agent)
            
            if not os.path.exists(model_path):
                print(f"❌ Model not found: {model_path}")
                return 1
            
            print(f"📁 Loading model: {model_path}")
            
            # Create minimal environment for model loading
            W40KEngine, _ = setup_imports()
            from ai.unit_registry import UnitRegistry
            cfg = get_config_loader()
            unit_registry = UnitRegistry()

            eval_scenario_list_override = None
            # Un scenario explicite (chemin .json) est joue TEL QUEL : pas de repli holdout,
            # pas de materialisation wall_ref (celle-ci exige un scenario sous agents/ et
            # reecrit le terrain). Sert a jouer/visualiser un scenario cible (ex. placement
            # fixed) via --eval --step. Voir evaluate_against_bots(materialize_eval_refs).
            explicit_scenario_raw = False
            if args.rule_checker:
                eval_scenario_list_override = _load_rule_checker_scenarios(project_root, args.agent)
                scenario_file = eval_scenario_list_override[0]
                print(
                    f"📋 Rule-checker test-only mode: {len(eval_scenario_list_override)} scenario(s) generes"
                )
                print(f"📋 Using first rule-checker scenario for env init: {os.path.basename(scenario_file)}")
            elif args.scenario and args.scenario.endswith(".json"):
                scenario_file = (
                    args.scenario
                    if os.path.isabs(args.scenario)
                    else os.path.join(project_root, args.scenario)
                )
                if not os.path.exists(scenario_file):
                    raise FileNotFoundError(f"--scenario file not found: {scenario_file}")
                eval_scenario_list_override = [scenario_file]
                explicit_scenario_raw = True
                print(f"📋 Using explicit scenario (played as-is): {os.path.basename(scenario_file)}")
            else:
                # Test-only mode must evaluate on holdout scenarios only.
                if args.scenario == "bot":
                    raise ValueError(
                        "--scenario bot is not allowed in --test-only mode. "
                        "Use holdout scenarios for evaluation."
                    )
                # MEME resolveur que l'eval post-entrainement : meme split retenu, meme message
                # quand le dossier manque. Ce bloc l'open-codait, avec son propre `[0]` et son
                # propre libelle — deux reponses differentes a « quel holdout ? » selon qu'on
                # arrive par --test-only ou par --test-episodes.
                # `[0]` assume ici : ce scenario n'AMORCE que l'env, la mesure du holdout est
                # faite plus bas par `scenario_pool="holdout"`, qui balaye le pool entier.
                scenario_file = resolve_final_eval_scenarios(cfg, args.agent, args.training_config)[0]
                print(f"📋 Using holdout scenario: {os.path.basename(scenario_file)}")
            
            # CRITICAL FIX: Use rewards_config for controlled_agent (includes phase suffix).
            # `args.rewards_config` retombe sur `args.agent` des la lecture des arguments, donc
            # il est toujours renseigne ici — le repli qui vivait sur cette ligne etait mort.
            effective_agent_key = args.rewards_config

            base_env = W40KEngine(
                rewards_config=args.rewards_config,
                training_config_name=args.training_config,
                controlled_agent=effective_agent_key,
                active_agents=None,
                scenario_file=scenario_file,
                unit_registry=unit_registry,
                quiet=True,
                gym_training_mode=True,
                training_n_envs=1,  # test holdout : UN environnement, joue en serie
                debug_mode=args.debug
            )
            
            def mask_fn(env):
                return env.get_action_mask()
            
            from sb3_contrib.common.wrappers import ActionMasker
            masked_env = ActionMasker(base_env, mask_fn)
            
            # Load model
            try:
                model = MaskablePPO.load(model_path, env=masked_env)
            except ValueError as e:
                error_msg = str(e)
                if "Observation spaces do not match" in error_msg:
                    print(f"❌ Model incompatible: {error_msg}")
                    print(f"⚠️  The model was trained with a different observation space size.")
                    print(f"💡 Solution: Re-train the model with --new-model flag:")
                    print(f"   python ai/train.py --agent {args.agent} --training-config {args.training_config} --rewards-config {args.rewards_config} --scenario bot --new-model")
                    return 1
                else:
                    raise
            
            # Run bot evaluation ONLY
            training_config = cfg.load_agent_training_config(args.agent, args.training_config)
            episodes_per_bot = args.test_episodes if args.test_episodes else require_key(training_config, "eval_episodes")
            
            # Le total = episodes_per_bot x NOMBRE DE BOTS REELLEMENT JOUES. L'eval ne joue que
            # les bots ponderes (bot_evaluation: active_bot_names = tuple(eval_weights.keys())) —
            # le `* 3` code en dur ici datait de l'epoque a 3 bots et annoncait 30 pour 60 tours.
            eval_bot_count = len(require_key(
                require_key(training_config, "callback_params"), "bot_eval_weights"
            ))
            print("\n" + "="*80)
            print("🎯 RUNNING BOT EVALUATION")
            print(f"Episodes per bot: {episodes_per_bot} (Total: {episodes_per_bot * eval_bot_count})")
            print("="*80)
            
            results = evaluate_against_bots(
                model=model,
                training_config_name=args.training_config,
                rewards_config_name=args.rewards_config,
                debug_mode=args.debug,
                n_episodes=episodes_per_bot,
                controlled_agent=effective_agent_key,
                show_progress=True,
                deterministic=True,
                step_logger=step_logger,
                model_path=model_path,
                scenario_pool="holdout",
                scenario_list_override=eval_scenario_list_override,
                materialize_eval_refs=not explicit_scenario_raw,
            )

            # Dernier producteur d'eval de la famille, et le seul SANS tracker : il n'écrit
            # aucune courbe, donc rien ici ne comptait ses troncatures. Le moteur posant
            # `winner = -1` dessus, elles entraient en NUL dans le score publié — le pire des
            # trois silences, puisque c'est ce score-là qui est cité (V11 §0.61). Le bilan sort
            # AVANT le contrôle de fiabilité : une troncature est justement ce qu'on veut lire
            # quand la mesure échoue.
            # `tensorboard_log` peut être None (modèle entraîné sans TensorBoard) : le compte
            # tient quand même, et le bilan annonce l'absence de journal.
            eval_truncations = TruncationLog(
                agent_log_dir(model.tensorboard_log, effective_agent_key)
                if model.tensorboard_log else None
            )
            eval_truncations.record_eval_batch(require_key(results, "truncations"))
            for line in eval_truncations.summary_lines():
                print(line)

            # Fiabilité stricte, miroir de `_apply_eval_results` (training_callbacks) : un épisode
            # planté est retiré du dénominateur par `_get_result_with_timeout`, donc publier un
            # score ici reviendrait à mesurer sur un échantillon tronqué SANS le signaler. Un crash
            # moteur n'est pas une défaite de l'agent : il n'a pas à être compté, il a à faire
            # échouer la mesure.
            total_failed_episodes = int(require_key(results, "total_failed_episodes"))
            total_timeout_episodes = int(require_key(results, "total_timeout_episodes"))
            total_error_episodes = int(require_key(results, "total_error_episodes"))
            eval_duration_seconds = float(require_key(results, "eval_duration_seconds"))
            # V11 §0.27 : ce site est l'eval FINALE (score livre). Contrairement a l'eval
            # intermediaire, un score tronque ne peut pas etre publie — on leve dans les deux
            # cas, mais la cause est distinguee : `error` = crash moteur a corriger,
            # `timeout` = lenteur (baisser bot_eval_final ou monter le timeout).
            if total_failed_episodes > 0:
                cause = (
                    "crash(s) moteur" if total_error_episodes > 0 and total_timeout_episodes == 0
                    else "timeout(s) de task (lenteur, pas un crash)" if total_error_episodes == 0
                    else "crash(s) moteur ET timeout(s)"
                )
                raise RuntimeError(
                    f"Bot evaluation failed episodes detected — {cause}: "
                    f"failed_episodes={total_failed_episodes} "
                    f"(error={total_error_episodes}, timeout={total_timeout_episodes}), "
                    f"duration_seconds={eval_duration_seconds:.1f}. "
                    "Evaluation stops immediately to enforce strict evaluation reliability."
                )

            scenario_scores = require_key(results, "scenario_scores")
            if not isinstance(scenario_scores, dict) or not scenario_scores:
                raise ValueError("eval-only requires non-empty scenario_scores in evaluation results")

            bot_eval_weights = require_key(require_key(training_config, "callback_params"), "bot_eval_weights")
            bot_scores = {bn: float(require_key(results, bn)) for bn in bot_eval_weights}
            # V11 §10.5 : le holdout (tactical) est MESURE mais EXCLU des signaux de selection.
            # worst_bot_name pilote le diagnostic de point faible : un poids nul ne protege pas
            # ce site (min sur des NOMS). Source unique : selection_worst_bot (training_callbacks).
            worst_bot_name, worst_bot_score = selection_worst_bot(bot_scores)

            worst_scenario_name = None
            worst_scenario_combined = None
            worst_holdout_regular_name = None
            worst_holdout_regular_combined = None
            worst_holdout_hard_name = None
            worst_holdout_hard_combined = None
            for scenario_name, values in scenario_scores.items():
                if not isinstance(values, dict):
                    raise TypeError(
                        f"scenario_scores['{scenario_name}'] must be dict "
                        f"(got {type(values).__name__})"
                    )
                combined_score = float(require_key(values, "combined"))
                if worst_scenario_combined is None or combined_score < worst_scenario_combined:
                    worst_scenario_name = str(scenario_name)
                    worst_scenario_combined = combined_score
                if str(scenario_name).startswith("holdout_regular_"):
                    if (
                        worst_holdout_regular_combined is None
                        or combined_score < worst_holdout_regular_combined
                    ):
                        worst_holdout_regular_name = str(scenario_name)
                        worst_holdout_regular_combined = combined_score
                if str(scenario_name).startswith("holdout_hard_"):
                    if (
                        worst_holdout_hard_combined is None
                        or combined_score < worst_holdout_hard_combined
                    ):
                        worst_holdout_hard_name = str(scenario_name)
                        worst_holdout_hard_combined = combined_score

            # Display results (robustness-oriented summary)
            print("\n" + "="*80)
            print("📊 FINAL BOT EVALUATION SUMMARY")
            print("="*80)
            # JUMEAU du résumé de fin d'entraînement (plus haut dans ce fichier) : même liste
            # blanche, pour la même raison. Ici la liste noire ne produisait pas encore de faux
            # win-rate — la garde `f'{bot_name}_wins' in results` écartait par accident les
            # agrégats sans compteur de victoires — mais elle reposait sur cette coïncidence,
            # pas sur une règle. Le premier agrégat publié AVEC un `_wins` s'y serait affiché.
            for bot_name, wr, wins, losses, draws in iter_bot_score_rows(results):
                print(f"  vs {bot_name:20s}: {wr:.2f} (W:{wins} L:{losses} D:{draws})")
            print(f"Combined Score: {float(require_key(results, 'combined')):.4f}")
            if 'roster_gap' in results:
                print(f"Écart Spacemarine - Ork: {float(results['roster_gap']) * 100:+.1f} pt")
            _joues = int(require_key(results, 'total_episodes_played'))
            _duree = float(require_key(results, 'eval_duration_seconds'))
            print(
                f"Épisodes joués: {_joues} (hors abandons) en {_duree:.0f} s "
                f"— {_joues / _duree:.2f} ép./s"
            )
            print(f"Worst bot score: {worst_bot_name} = {worst_bot_score:.4f}")
            if worst_scenario_name is not None and worst_scenario_combined is not None:
                print(
                    "Worst scenario combined: "
                    f"{worst_scenario_name} = {worst_scenario_combined:.4f}"
                )
            if (
                worst_holdout_regular_name is not None
                and worst_holdout_regular_combined is not None
            ):
                print(
                    "Worst holdout regular combined: "
                    f"{worst_holdout_regular_name} = {worst_holdout_regular_combined:.4f}"
                )
            else:
                print("Worst holdout regular combined: N/A")
            if worst_holdout_hard_name is not None and worst_holdout_hard_combined is not None:
                print(
                    "Worst holdout hard combined: "
                    f"{worst_holdout_hard_name} = {worst_holdout_hard_combined:.4f}"
                )
            else:
                print("Worst holdout hard combined: N/A")
            print("="*80 + "\n")
            
            masked_env.close()
            return 0

        # Single agent training mode
        else:
            # La branche d'entrainement --agent MacroController a ete retiree ici : elle
            # appelait create_macro_controller_model, qui levait NotImplementedError sans
            # condition, sous un cast qui l'habillait en quadruplet. Ses deux gardes
            # (--rule-checker interdit, --scenario self/bot interdits) tombent avec elle.
            # Voir la trace au-dessus de resolve_turn_step_limit.

            # Position PRISE EN TENAILLE (le pourquoi du « avant l'entrainement » est dans la
            # docstring du resolveur) : APRES `--convert-steplog`, `--replay` et `--test-only`,
            # qui retournent sans jamais evaluer post-entrainement — et dont deux contournent le
            # holdout par construction (`--test-only --rule-checker`, `--test-only --scenario
            # foo.json`). Resoudre plus haut leur imposerait un dossier qu'ils ne demandent pas.
            final_eval_scenarios = (
                resolve_final_eval_scenarios(config, args.agent, args.training_config)
                if args.test_episodes > 0 else None
            )

            if args.rule_checker:
                scenario_list = _load_rule_checker_scenarios(project_root, args.agent)
                print(f"🧪 Rule-checker mode: {len(scenario_list)} scenario(s) generes dans config/rule_checker/")
                for scenario_path in scenario_list:
                    print(f"   - {os.path.basename(scenario_path)}")

                training_config = config.load_agent_training_config(args.agent, args.training_config)
                if "total_episodes" not in training_config:
                    raise KeyError(
                        f"total_episodes missing from {args.agent} training config phase {args.training_config}"
                    )
                if args.total_episodes is not None:
                    total_episodes = args.total_episodes
                    print(f"📊 Using total_episodes from CLI: {total_episodes}")
                else:
                    total_episodes = training_config["total_episodes"]
                    print(f"📊 Using total_episodes from config: {total_episodes}")

                success, model, env = train_with_scenario_rotation(
                    config=config,
                    agent_key=args.agent,
                    training_config_name=args.training_config,
                    rewards_config_name=args.rewards_config,
                    scenario_list=scenario_list,
                    total_episodes=total_episodes,
                    new_model=args.new,
                    append_training=args.append,
                    debug_mode=args.debug,
                    use_bots=True,
                    device_mode=args.mode
                )
                if success and args.test_episodes > 0:
                    test_trained_model(
                        model,
                        args.test_episodes,
                        args.training_config,
                        args.rewards_config,
                        require_present(final_eval_scenarios, "final_eval_scenarios"),
                        debug_mode=args.debug
                    )
                close_training_env(env, "fin de run")
                return 0 if success else 1

            # Check if scenario rotation is requested
            if args.scenario == "all" or args.scenario == "self" or args.scenario == "bot":
                # Get list of scenarios based on type
                if args.scenario == "self" or args.scenario == "all":
                    # "all" and "self" both mean: use self-play scenarios
                    scenario_list = get_scenario_list_for_phase(config, args.agent, args.training_config, scenario_type="self")
                    scenario_type_name = "self-play"
                else:  # args.scenario == "bot"
                    scenario_list = get_scenario_list_for_phase(config, args.agent, args.training_config, scenario_type="bot")
                    scenario_type_name = "bot"

                # NO FALLBACKS - if no scenarios found, ERROR
                if len(scenario_list) == 0:
                    raise FileNotFoundError(
                        f"No {scenario_type_name} scenarios found under "
                        f"config/agents/{args.agent}/scenarios/. "
                        f"{describe_expected_bot_self_scenario_files(scenario_type_name == 'self-play')}"
                    )

                print(f"📋 Found {len(scenario_list)} {scenario_type_name} scenario(s)")

                # Load agent-specific training config to get total episodes
                training_config = config.load_agent_training_config(args.agent, args.training_config)
                if "total_episodes" not in training_config:
                    raise KeyError(f"total_episodes missing from {args.agent} training config phase {args.training_config}")
                # CLI argument takes priority over config
                if args.total_episodes is not None:
                    total_episodes = args.total_episodes
                    print(f"📊 Using total_episodes from CLI: {total_episodes}")
                else:
                    total_episodes = training_config["total_episodes"]

                # Always use scenario rotation path for self/bot/all modes,
                # even when a single scenario is available.
                # This keeps random wall/objective ref materialization consistent.
                success, model, env = train_with_scenario_rotation(
                    config=config,
                    agent_key=args.agent,
                    training_config_name=args.training_config,
                    rewards_config_name=args.rewards_config,
                    scenario_list=scenario_list,
                    total_episodes=total_episodes,
                    new_model=args.new,
                    append_training=args.append,
                    debug_mode=args.debug,
                    use_bots=(args.scenario == "bot"),
                    device_mode=args.mode
                )

                if success and args.test_episodes > 0:
                    test_trained_model(model, args.test_episodes, args.training_config, args.rewards_config, require_present(final_eval_scenarios, "final_eval_scenarios"), debug_mode=args.debug)

                close_training_env(env, "fin de run")
                return 0 if success else 1
            
            # Standard single-scenario training (no rotation)
            model, env, training_config, model_path, _resume_offset = create_multi_agent_model(
                config,
                args.training_config,
                args.rewards_config,
                agent_key=args.agent,
                new_model=args.new,
                append_training=args.append,
                scenario_override=args.scenario,
                debug_mode=args.debug,
                device_mode=args.mode
            )
            
            # Setup callbacks with agent-specific model path
            # `_resume_offset` vient de `create_multi_agent_model` : une SEULE lecture de
            # l'etat de run par run. Il pilote le COMPTEUR (axe TensorBoard, barre de
            # progression), pas les rampes de regime — celles-la comptent depuis ce run.
            callbacks = setup_callbacks(config, model_path, training_config, args.training_config,
                                      agent=args.agent, rewards_config_name=args.rewards_config,
                                      global_episode_offset=_resume_offset)
            
            # Train model
            # CRITICAL: Use rewards_config for controlled_agent (includes phase suffix like "_phase1")
            success = train_model(model, training_config, callbacks, model_path, args.training_config, args.rewards_config, controlled_agent=args.rewards_config, episode_offset=_resume_offset)
            
            if success:
                # Only test if episodes > 0
                if args.test_episodes > 0:
                    test_trained_model(model, args.test_episodes, args.training_config, args.rewards_config, require_present(final_eval_scenarios, "final_eval_scenarios"), debug_mode=args.debug)
                else:
                    print("📊 Skipping testing (--test-episodes 0)")
                return 0
            else:
                return 1
        
    except Exception as e:
        print(f"💥 Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        # Filet unique de TOUTES les sorties de main() — retour normal, `return 1` anticipe,
        # exception levee au fond d'une phase de curriculum. Les fermetures nominales placees
        # plus haut ne couvrent que les chemins nominaux ; sans ce balayage, une exception
        # laissait les workers etre tues par signal, c'est-a-dire exactement la perte que ce
        # chantier corrige.
        close_all_training_envs()

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
