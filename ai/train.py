# ai/train.py
#!/usr/bin/env python3
"""
ai/train.py - Main training script following AI_INSTRUCTIONS.md exactly
"""

import os
import sys
import io
import argparse
import tempfile
import atexit
import hashlib

# Fix Windows encoding for emoji/Unicode output with line buffering
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

# Suppress NumPy MINGW-W64 warnings on Windows (MUST be before numpy import)
import warnings
warnings.filterwarnings('ignore')  # Suppress all warnings
import os
os.environ['PYTHONWARNINGS'] = 'ignore'

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
    _order = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "PYTORCH_CUDA_ALLOC_CONF", "CUDA_LAUNCH_BLOCKING")
    _parts = " ".join(f"{k}={os.environ.get(k, '')}" for k in _order if k in _training_env_vars)
    if _parts:
        print(f"   env: {_parts}")
    print(f"   torch.compile_mode: {_torch_compile_mode or 'off'}")

import numpy as np
import glob
import shutil
import random
from pathlib import Path
from typing import Callable, Dict, List, Tuple, Any, Optional, Set, cast

# Fix import paths - Add both script dir and project root
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, script_dir)
sys.path.insert(0, project_root)
from ai.unit_registry import UnitRegistry
sys.path.insert(0, project_root)

# Import evaluation bots for testing
try:
    from ai.evaluation_bots import RandomBot, GreedyBot, DefensiveBot
    EVALUATION_BOTS_AVAILABLE = True
except ImportError:
    EVALUATION_BOTS_AVAILABLE = False

# Import MaskablePPO - enforces action masking during training
from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3 import PPO
MASKABLE_PPO_AVAILABLE = True

from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback, BaseCallback, CallbackList
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv, VecNormalize
from stable_baselines3.common.utils import get_schedule_fn  # Convert float hyperparameters to callable schedules


def _build_training_bots_from_config(training_config):
    """Build weighted bot list from training_config.bot_training.

    Config format:
      bot_training:
        ratios: {random: 0.4, greedy: 0.3, defensive: 0.3}
        randomness: {greedy: 0.10, defensive: 0.10}

    Returns list of bot instances for random.choice() selection.
    """
    from ai.evaluation_bots import (
        RandomBot, GreedyBot, DefensiveBot, ControlBot,
        AggressiveSmartBot, DefensiveSmartBot, AdaptiveBot,
    )
    
    cfg = require_key(training_config, "bot_training")
    ratios = cfg.get("ratios", {"random": 0.2, "greedy": 0.4, "defensive": 0.4})
    randomness_cfg = cfg["randomness"] if "randomness" in cfg else {}

    BOT_CLASSES = {
        "random": RandomBot,
        "greedy": GreedyBot,
        "defensive": DefensiveBot,
        "control": ControlBot,
        "aggressive_smart": AggressiveSmartBot,
        "defensive_smart": DefensiveSmartBot,
        "adaptive": AdaptiveBot,
    }

    total = 10
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
            r_val = float(randomness_cfg.get(bot_name, 0.10))
            for _ in range(count):
                bots.append(BOT_CLASSES[bot_name](randomness=r_val))
        else:
            raise ValueError(f"Unknown bot name in ratios: {bot_name!r}")
    
    return bots


def _make_learning_rate_schedule(lr_config):
    """Convert learning_rate config to callable for PPO. Supports:
    - float: constant learning rate
    - dict: {"initial": 0.00015, "final": 0.00005} for linear decay over training
    SB3 uses progress_remaining: 1 at start, 0 at end."""
    if isinstance(lr_config, (int, float)):
        return get_schedule_fn(float(lr_config))
    if isinstance(lr_config, dict):
        initial = float(lr_config["initial"])
        final = float(lr_config["final"])
        def schedule(progress_remaining):
            return initial + (final - initial) * (1 - progress_remaining)
        return schedule
    raise ValueError(f"learning_rate must be float or dict with initial/final, got {type(lr_config)}")


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


def _resolve_n_envs_for_step_logging(n_envs: int, log=print) -> int:
    """Force un environnement unique quand la journalisation --step est active.

    V11 T6 — root cause d'un no-op SILENCIEUX : `--step` n'a qu'un objet, journaliser les
    actions dans step.log (consomme par `ai/analyzer.py`). Or le StepLogger n'est branche
    QUE sur la branche mono-env (`if step_logger: base_env.step_logger = step_logger`) ;
    les trois branches vectorisees construisent leurs envs avec `step_logger_enabled=False`.
    Avec `n_envs > 1` (48 dans x1_debug), le run annoncait "Step logging enabled" puis
    n'ecrivait jamais la moindre entree — step.log reduit a son en-tete.

    Meme traitement que `--replay`/`--convert-steplog`, qui forcent deja un env unique :
    on force ET on le DIT (pas de no-op silencieux, pas de promesse non tenue).
    """
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

    Raises ValueError listing the available phases when an agent is selected but no
    training-config phase was provided.
    """
    if agent_key and training_config_name is None:
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
    path_hash = hashlib.sha1(hash_payload.encode("utf-8")).hexdigest()[:16]
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


def _load_rule_checker_scenarios(project_root_path: str) -> List[str]:
    """
    Load rule-checker scenario paths from config/rule_checker/manifest.json.
    Strict mode: raises if the manifest or scenario list is missing or invalid.
    """
    manifest_path = os.path.join(project_root_path, "config", "rule_checker", "manifest.json")
    if not os.path.isfile(manifest_path):
        raise FileNotFoundError(
            f"--rule-checker requires manifest file: {manifest_path}. "
            "Generate it first with: python scripts/roster_matchup_stats.py --agent <AGENT> --rule-checker"
        )
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    if not isinstance(manifest, dict):
        raise TypeError(
            f"Rule-checker manifest must be JSON object (got {type(manifest).__name__})"
        )
    raw_paths = require_key(manifest, "scenario_paths")
    if not isinstance(raw_paths, list):
        raise TypeError(
            f"rule_checker manifest key 'scenario_paths' must be list (got {type(raw_paths).__name__})"
        )
    if len(raw_paths) == 0:
        raise ValueError("rule_checker manifest contains no scenarios")

    resolved_paths: List[str] = []
    missing_paths: List[str] = []
    for raw_path in raw_paths:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(f"Invalid scenario path in rule_checker manifest: {raw_path!r}")
        scenario_path = raw_path.strip()
        if not os.path.isabs(scenario_path):
            scenario_path = os.path.join(project_root_path, scenario_path)
        if not os.path.isfile(scenario_path):
            missing_paths.append(scenario_path)
            continue
        resolved_paths.append(scenario_path)

    if missing_paths:
        raise FileNotFoundError(
            "rule_checker manifest references missing scenarios. "
            f"First missing files: {missing_paths[:5]}"
        )

    deduped = sorted(set(resolved_paths))
    if len(deduped) == 0:
        raise ValueError("rule_checker scenario list is empty after validation")
    return deduped


# Multi-agent orchestration imports
from ai.scenario_manager import ScenarioManager
from ai.multi_agent_trainer import MultiAgentTrainer
from config_loader import get_config_loader, get_max_turns
from ai.game_replay_logger import GameReplayIntegration
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
from tqdm import tqdm  # For episode progress bar
import gymnasium as gym  # For SelfPlayWrapper to inherit from gym.Wrapper

# Environment wrappers (extracted to ai/env_wrappers.py)
from ai.env_wrappers import BotControlledEnv, SelfPlayWrapper


# Step logger (extracted to ai/step_logger.py)
from ai.step_logger import StepLogger

# Bot evaluation (extracted to ai/bot_evaluation.py)
from ai.bot_evaluation import evaluate_against_bots

# Training callbacks (extracted to ai/training_callbacks.py)
from ai.training_callbacks import (
    LearningRateScheduleCallback,
    EntropyScheduleCallback,
    EpisodeTerminationCallback,
    EpisodeBasedEvalCallback,
    MetricsCollectionCallback,
    BotEvaluationCallback
)

# Training utilities (extracted to ai/training_utils.py)
from ai.training_utils import (
    check_gpu_availability,
    benchmark_device_speed,
    setup_imports,
    make_training_env,

    get_agent_scenario_file,
    get_scenario_list_for_phase,
    describe_expected_bot_self_scenario_files,
    ensure_scenario
)
from ai.vec_normalize_utils import save_vec_normalize, load_vec_normalize, get_vec_normalize_path

from shared.data_validation import require_key, require_present

_progress_bar_width_cache: Optional[Dict[str, int]] = None
_wall_override_temp_dir: Optional[str] = None


def _cleanup_wall_override_temp_dir() -> None:
    """Remove temporary directory used for wall-ref scenario overrides."""
    global _wall_override_temp_dir
    if _wall_override_temp_dir and os.path.isdir(_wall_override_temp_dir):
        shutil.rmtree(_wall_override_temp_dir, ignore_errors=True)
    _wall_override_temp_dir = None


def _get_wall_override_temp_dir() -> str:
    """Create (once) and return temporary directory for wall-ref scenario overrides."""
    global _wall_override_temp_dir
    if _wall_override_temp_dir is None:
        _wall_override_temp_dir = tempfile.mkdtemp(prefix="w40k_wallmix_")
        atexit.register(_cleanup_wall_override_temp_dir)
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
            "curriculum_phase_width",
            "macro_eval_width",
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
    extract_scenario_name_for_replay,
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
    """True si l'obs est le Dict {"vec", "grid"} du pipeline squad spatial (T1b)."""
    return isinstance(observation_space, gym.spaces.Dict)


def _vec_norm_obs_keys(observation_space):
    """Cles a normaliser par VecNormalize.

    Obs Dict : normaliser UNIQUEMENT "vec" — la grille porte des canaux deja dans [0,1]
    (occupation/murs/EZ/objectifs 0-1, niveau normalise), la normaliser detruirait sa
    semantique et son creux (spec T1b). Obs Box : comportement historique (None = tout).
    """
    return ["vec"] if _is_dict_obs_space(observation_space) else None


def _apply_vec_normalize(env, model_path_for_vn, vec_norm_cfg, new_model, n_envs, log_fn):
    """Enveloppe `env` dans VecNormalize (charge les stats du checkpoint ou en cree de neuves).

    Ne charge l'ancienne VecNormalize que si elle sera reellement reutilisee. Sur un retrain
    from-scratch (new_model) ou un reset de curriculum, le .pkl est ecarte de toute facon ;
    le charger planterait sur le shape check de set_venv des que l'obs space a change
    (ex: passage Box(108) -> Dict), sans raison metier.

    Retourne l'env enveloppe. Factorise les 3 sites identiques (create_model,
    create_multi_agent_model, rotation de scenario).
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


def _inject_spatial_extractor(policy_kwargs) -> None:
    """Branche le CNN spatial sur `MultiInputPolicy` (obs Dict).

    Un extracteur ne se declare pas en JSON (c'est une classe) : il est injecte ici. Le defaut
    `CombinedExtractor` aplatirait la grille (6 canaux -> non reconnue comme image), d'ou
    `SpatialCombinedExtractor` (spec §6.2 / ai/spatial_extractor.py).

    `cnn_features` est un hyperparametre : il DOIT venir du JSON de l'agent
    (`policy_kwargs.features_extractor_kwargs.cnn_features`) — sb3 transmet ces kwargs au
    constructeur de l'extracteur. Absence = erreur explicite, jamais de valeur par defaut.
    """
    from ai.spatial_extractor import SpatialCombinedExtractor

    fx_kwargs = require_key(policy_kwargs, "features_extractor_kwargs")
    require_key(fx_kwargs, "cnn_features")
    policy_kwargs["features_extractor_class"] = SpatialCombinedExtractor


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


def create_model(config, training_config_name, rewards_config_name, new_model, append_training, args):
    """Create or load PPO model with configuration following AI_INSTRUCTIONS.md."""
    
    # Import metrics tracker for training monitoring
    from metrics_tracker import W40KMetricsTracker
    
    # Check GPU availability
    gpu_available = check_gpu_availability()
    
    # Load training configuration from config files (not script parameters)
    training_config = config.load_training_config(training_config_name)
    model_params = training_config["model_params"]

    # Handle entropy coefficient scheduling if configured
    # Use START value for model creation; callback will handle the schedule
    if "ent_coef" in model_params and isinstance(model_params["ent_coef"], dict):
        ent_config = model_params["ent_coef"]
        start_val = float(ent_config["start"])
        end_val = float(ent_config["end"])
        model_params["ent_coef"] = start_val  # Use initial value
        print(f"✅ Entropy coefficient schedule: {start_val} -> {end_val} (will be applied via callback)")

    # Import environment
    W40KEngine, register_environment = setup_imports()
    
    # Register environment
    register_environment()
    
    # Create environment with specified rewards config
    # ensure scenario.json exists in config/
    cfg = get_config_loader()
    scenario_file = os.path.join(cfg.config_dir, "scenario.json")
    if not os.path.isfile(scenario_file):
        raise FileNotFoundError(f"Missing scenario.json in config/: {scenario_file}")
    # Load unit registry for environment creation
    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()
    
    # CRITICAL FIX: Auto-detect controlled_agent from scenario's Player 0 units
    # This allows curriculum training without --agent parameter
    controlled_agent_key = None
    try:
        with open(scenario_file, 'r') as f:
            scenario_data = json.load(f)
    
        # Get first Player 0 unit to determine agent type
        units = require_key(scenario_data, "units")
        player_0_units = [u for u in units if require_key(u, "player") == 0]
        if player_0_units:
            first_unit_type = require_key(player_0_units[0], "unit_type")
            if first_unit_type:
                base_agent_key = unit_registry.get_model_key(first_unit_type)
                
                # CRITICAL FIX: Use rewards_config_name directly as controlled_agent_key
                # rewards_config.json has keys like "SpaceMarine_Infantry_Troop_RangedSwarm_phase1"
                # The rewards_config_name parameter already contains the full key
                if rewards_config_name not in ["default", "test"]:
                    controlled_agent_key = rewards_config_name
                    print(f"ℹ️  Auto-detected base agent: {base_agent_key}")
                    print(f"✅ Using phase-specific rewards: {controlled_agent_key}")
                else:
                    controlled_agent_key = base_agent_key
                    print(f"ℹ️  Auto-detected controlled_agent: {controlled_agent_key}")
                
    except Exception as e:
        print(f"⚠️  Failed to auto-detect controlled_agent: {e}")
        raise ValueError(f"Cannot proceed without controlled_agent - auto-detection failed: {e}")
    
    # ✓ CHANGE 3: Check if vectorization is enabled in config
    n_envs = require_key(training_config, "n_envs")
    
    # ✓ CHANGE 3: Special handling for replay/steplog modes (must be single env)
    if args.replay or args.convert_steplog:
        n_envs = 1  # Force single environment for replay generation
        print("ℹ️  Replay mode: Using single environment (vectorization disabled)")
    else:
        n_envs = _resolve_n_envs_for_step_logging(n_envs)
    
    # V11 §10.4 : meme construction d'adversaires que les chemins rotation et agent.
    opponents = build_training_opponents(
        training_config,
        "bot_training" in training_config,
        training_config["total_episodes"] if "total_episodes" in training_config else None,
        print,
    )

    base_env = None
    if n_envs > 1:
        # ✓ CHANGE 3: Create vectorized environments for parallel training
        print(f"🚀 Creating {n_envs} parallel environments for accelerated training...")

        # Disable step logger for vectorized training (avoid file conflicts)
        vec_envs = SubprocVecEnv([
            make_training_env(
                rank=i,
                scenario_file=scenario_file,
                rewards_config_name=rewards_config_name,
                training_config_name=training_config_name,
                controlled_agent_key=controlled_agent_key,
                unit_registry=unit_registry,
                step_logger_enabled=False,  # Disabled for parallel envs
                debug_mode=args.debug,
                use_bots=opponents["use_bots"],
                training_bots=opponents["training_bots"],
                agent_seat_mode=opponents["agent_seat_mode"],
                global_seed=opponents["agent_seat_seed"],
                opponent_mix_config=opponents["opponent_mix_config"],
            )
            for i in range(n_envs)
        ])
        
        env = vec_envs
        print(f"✅ Vectorized training environment created with {n_envs} parallel processes")
        
    else:
        # ✓ CHANGE 3: Single environment (original behavior)
        base_env = W40KEngine(
            rewards_config=rewards_config_name,
            training_config_name=training_config_name,
            controlled_agent=controlled_agent_key,  # Use auto-detected agent
            active_agents=None,
            scenario_file=scenario_file,
            unit_registry=unit_registry,
            quiet=True,
            gym_training_mode=True,
            debug_mode=args.debug
        )
        
        # Connect step logger after environment creation - compliant engine compatibility
        if step_logger:
            # Connect StepLogger directly to compliant W40KEngine
            base_env.step_logger = step_logger
            print("✅ StepLogger connected to compliant W40KEngine")
        
        # Enable replay logging for replay generation modes only
        if args.replay or args.convert_steplog:
            # Use same pattern as evaluate.py for working icon movement
            base_env.is_evaluation_mode = True
            base_env._force_evaluation_mode = True
            # Direct integration without wrapper
            base_env = GameReplayIntegration.enhance_training_env(base_env)
            if hasattr(base_env, 'replay_logger') and base_env.replay_logger:
                base_env.replay_logger.is_evaluation_mode = True
                base_env.replay_logger.capture_initial_state()
        
        # Wrap environment with ActionMasker for MaskablePPO compatibility
        def mask_fn(env):
            return env.get_action_mask()
        
        masked_env = ActionMasker(base_env, mask_fn)

        if opponents["use_bots"]:
            # V11 §10.4 : bots ponderes de bot_training, comme le chemin rotation.
            bot_env = BotControlledEnv(
                masked_env,
                bots=opponents["training_bots"],
                unit_registry=unit_registry,
                agent_seat_mode=require_present(opponents["agent_seat_mode"], "agent_seat_mode"),
                global_seed=opponents["agent_seat_seed"],
            )
            env = Monitor(bot_env)
        else:
            # Pas de bot_training : self-play. frozen_model=None est refuse par
            # SelfPlayWrapper (V11 §10.4).
            selfplay_env = SelfPlayWrapper(masked_env, frozen_model=None, update_frequency=100)
            env = Monitor(selfplay_env)

    # VecNormalize: observations and rewards normalization (optional, configurable)
    vec_norm_cfg = training_config.get("vec_normalize", {})  # get allowed: optional config
    vec_normalize_enabled = vec_norm_cfg.get("enabled", False)
    if vec_normalize_enabled:
        model_path_for_vn = build_agent_model_path(
            config.get_models_root(), require_present(controlled_agent_key, "controlled_agent_key")
        )
        env = _apply_vec_normalize(env, model_path_for_vn, vec_norm_cfg, new_model, n_envs, print)

    # Check if action masking is available (works for both vectorized and single env)
    if n_envs == 1:
        if hasattr(base_env, 'get_action_mask'):
            print("✅ Action masking enabled - AI will only see valid actions")
        else:
            print("⚠️ Action masking not available")
    
    # Check if action masking is available
    if hasattr(base_env, 'get_action_mask'):
        print("✅ Action masking enabled - AI will only see valid actions")
    else:
        print("⚠️ Action masking not available")
    
    # Use auto-detected agent key for model path
    models_root = config.get_models_root()
    if controlled_agent_key:
        model_path = build_agent_model_path(models_root, controlled_agent_key)
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        print(f"📝 Using agent-specific model path: {model_path}")
    else:
        raise ValueError("controlled_agent_key is required to build model path")
    
    # Set device for model creation
    # PPO optimization: MlpPolicy performs BETTER on CPU (proven by benchmarks)
    # GPU only beneficial for CNN policies or networks with >2000 hidden units
    policy_kwargs = require_key(model_params, "policy_kwargs")
    net_arch = require_key(policy_kwargs, "net_arch")
    total_params = sum(net_arch) if isinstance(net_arch, list) else 512

    # BENCHMARK RESULTS: CPU 311 it/s vs GPU 282 it/s (10% faster on CPU)
    # Use GPU only for very large networks (>2000 hidden units)
    # Obs Dict (pipeline squad spatial) : CNN -> GPU, extracteur injecte (le benchmark MlpPolicy
    # ne s'applique plus). Obs Box legacy : logique historique inchangee.
    if _is_dict_obs_space(env.observation_space):
        _inject_spatial_extractor(policy_kwargs)
    cache_key = (
        require_present(controlled_agent_key, "controlled_agent_key"),
        training_config_name,
        rewards_config_name,
    )
    device, use_gpu, obs_size = _resolve_device_for_obs(
        env.observation_space, args.mode if args else None, gpu_available, total_params,
        net_arch=net_arch, cache_key=cache_key,
    )

    model_params["device"] = device
    model_params["verbose"] = 0  # Disable verbose logging

    if use_gpu:
        print(f"🖥️  Using GPU for PPO")
    elif gpu_available:
        print(f"ℹ️  Using CPU for PPO (10% faster than GPU for MlpPolicy with {obs_size} features)")
        print(f"ℹ️  Benchmark: CPU 311 it/s vs GPU 282 it/s")
    
    # Determine whether to create new model or load existing
    specific_log_dir = ""
    if new_model or not os.path.exists(model_path):
        print(f"🆕 Creating new model on {device.upper()}...")
        print("✅ Using MaskablePPO with action masking for tactical combat")

        # Use specific log directory for continuous TensorBoard graphs across runs
        tb_log_name = f"{training_config_name}_{controlled_agent_key}"
        specific_log_dir = os.path.join(model_params["tensorboard_log"], tb_log_name)
        os.makedirs(specific_log_dir, exist_ok=True)

        # Update model_params to use specific directory
        model_params_copy = model_params.copy()
        model_params_copy["tensorboard_log"] = specific_log_dir
        if "learning_rate" in model_params_copy and isinstance(model_params_copy["learning_rate"], dict):
            model_params_copy["learning_rate"] = _make_learning_rate_schedule(model_params_copy["learning_rate"])

        model = MaskablePPO(env=env, **model_params_copy)
        # Properly suppress rollout console output
        if hasattr(model, '_logger') and model._logger:
            original_info = model._logger.info
            def filtered_info(*args):
                msg = args[0] if args else ""
                if not any(x in str(msg) for x in ['rollout/', 'exploration_rate']):
                    original_info(*args)
            model._logger.info = filtered_info
    elif append_training:
        print(f"📁 Loading existing model for continued training: {model_path}")
        try:
            model = MaskablePPO.load(model_path, env=env, device=device)
            # Update any model parameters that might have changed
            model.tensorboard_log = model_params["tensorboard_log"]
            model.verbose = model_params["verbose"]

            # CURRICULUM LEARNING: Apply new phase hyperparameters to loaded model
            # This allows Phase 2 to use different learning rates, entropy, etc. than Phase 1
            # while preserving the neural network weights learned in Phase 1
            if "learning_rate" in model_params:
                model.learning_rate = _make_learning_rate_schedule(model_params["learning_rate"])
            if "ent_coef" in model_params:
                model.ent_coef = model_params["ent_coef"]
            if "clip_range" in model_params:
                # Convert to callable schedule function (required by PPO)
                model.clip_range = get_schedule_fn(model_params["clip_range"])
            if "gamma" in model_params:
                model.gamma = model_params["gamma"]
            if "gae_lambda" in model_params:
                model.gae_lambda = model_params["gae_lambda"]
            if "n_steps" in model_params:
                model.n_steps = model_params["n_steps"]
            if "batch_size" in model_params:
                model.batch_size = model_params["batch_size"]
            if "n_epochs" in model_params:
                model.n_epochs = model_params["n_epochs"]
            if "vf_coef" in model_params:
                model.vf_coef = model_params["vf_coef"]
            if "max_grad_norm" in model_params:
                model.max_grad_norm = model_params["max_grad_norm"]

            print(f"✅ Applied new phase hyperparameters: lr={model.learning_rate}, ent={model.ent_coef}, clip={model.clip_range}")

            # CRITICAL FIX: Reinitialize logger after loading from checkpoint
            # This ensures PPO training metrics (policy_loss, value_loss, etc.) are logged correctly
            # Without this, model.logger.name_to_value remains empty/stale from the checkpoint
            from stable_baselines3.common.logger import configure

            # Use specific log directory to ensure continuous TensorBoard graphs across runs
            # Format: ./tensorboard/{config_name}_{controlled_agent_key}/{run_name}
            # This prevents creating new timestamped subdirectories on each script run
            tb_log_name = f"{training_config_name}_{controlled_agent_key}"
            specific_log_dir = os.path.join(model.tensorboard_log, tb_log_name)

            # Create directory if it doesn't exist
            os.makedirs(specific_log_dir, exist_ok=True)

            new_logger = configure(specific_log_dir, ["tensorboard"])
            model.set_logger(new_logger)
            print(f"✅ Logger reinitialized for continuous TensorBoard: {specific_log_dir}")
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("🆕 Creating new model instead...")
            # Use same specific directory as above
            model_params_copy = model_params.copy()
            model_params_copy["tensorboard_log"] = specific_log_dir
            if "learning_rate" in model_params_copy and isinstance(model_params_copy["learning_rate"], dict):
                model_params_copy["learning_rate"] = _make_learning_rate_schedule(model_params_copy["learning_rate"])
            model = MaskablePPO(env=env, **model_params_copy)
    else:
        print(f"📁 Loading existing model: {model_path}")
        try:
            model = MaskablePPO.load(model_path, env=env, device=device)
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("🆕 Creating new model instead...")
            # Need to create specific directory here too
            tb_log_name = f"{training_config_name}_{controlled_agent_key}"
            specific_log_dir = os.path.join(model_params["tensorboard_log"], tb_log_name)
            os.makedirs(specific_log_dir, exist_ok=True)
            model_params_copy = model_params.copy()
            model_params_copy["tensorboard_log"] = specific_log_dir
            if "learning_rate" in model_params_copy and isinstance(model_params_copy["learning_rate"], dict):
                model_params_copy["learning_rate"] = _make_learning_rate_schedule(model_params_copy["learning_rate"])
            model = MaskablePPO(env=env, **model_params_copy)

    _apply_torch_compile(model)
    return model, env, training_config, model_path

def create_multi_agent_model(config, training_config_name="default", rewards_config_name="default",
                            agent_key=None, new_model=False, append_training=False, scenario_override=None,
                            debug_mode=False, device_mode: Optional[str] = None):
    """Create or load PPO model for specific agent with configuration following AI_INSTRUCTIONS.md."""
    
    # Check GPU availability
    gpu_available = check_gpu_availability()
    
    # Load training configuration - agent-specific REQUIRED when agent_key provided
    if agent_key:
        # CRITICAL: NO FALLBACK - agent-specific config MUST exist
        training_config = config.load_agent_training_config(agent_key, training_config_name)
        print(f"✅ Loaded agent-specific training config: config/agents/{agent_key}/{agent_key}_training_config.json [{training_config_name}]")
        agent_specific_mode = True
    else:
        # No agent specified, use global config
        training_config = config.load_training_config(training_config_name)
        agent_specific_mode = False

    model_params = training_config["model_params"]

    # Handle entropy coefficient scheduling if configured
    # Use START value for model creation; callback will handle the schedule
    if "ent_coef" in model_params and isinstance(model_params["ent_coef"], dict):
        ent_config = model_params["ent_coef"]
        start_val = float(ent_config["start"])
        end_val = float(ent_config["end"])
        model_params["ent_coef"] = start_val  # Use initial value
        print(f"✅ Entropy coefficient schedule: {start_val} -> {end_val} (will be applied via callback)")

    # Import environment
    W40KEngine, register_environment = setup_imports()
    
    # Register environment
    register_environment()
    
    # Create agent-specific environment
    cfg = get_config_loader()
    
    # Get scenario file (agent-specific or global)
    scenario_file = get_agent_scenario_file(cfg, agent_key if agent_specific_mode else None, training_config_name, scenario_override)
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

    # V11 §10.4 : meme construction d'adversaires que le chemin rotation.
    opponents = build_training_opponents(
        training_config,
        use_bots,
        training_config["total_episodes"] if "total_episodes" in training_config else None,
        print,
    )

    if n_envs > 1:
        # ✓ CHANGE 8: Create vectorized environments for parallel training
        print(f"🚀 Creating {n_envs} parallel environments for accelerated training...")

        vec_envs = SubprocVecEnv([
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
            )
            for i in range(n_envs)
        ])
        
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
            debug_mode=debug_mode
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
        model_path_for_vn = build_agent_model_path(
            config.get_models_root(), require_present(agent_key, "agent_key")
        )
        env = _apply_vec_normalize(env, model_path_for_vn, vec_norm_cfg, new_model, n_envs, print)

    # Agent-specific model path
    models_root = config.get_models_root()
    model_path = build_agent_model_path(models_root, require_present(agent_key, "agent_key"))
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    
    # Set device for model creation
    # PPO optimization: MlpPolicy performs BETTER on CPU (proven by benchmarks)
    # GPU only beneficial for CNN policies or networks with >2000 hidden units
    policy_kwargs = require_key(model_params, "policy_kwargs")
    net_arch = require_key(policy_kwargs, "net_arch")
    total_params = sum(net_arch) if isinstance(net_arch, list) else 512

    # BENCHMARK RESULTS: CPU 311 it/s vs GPU 282 it/s (10% faster on CPU)
    # Use GPU only for very large networks (>2000 hidden units)
    if _is_dict_obs_space(env.observation_space):
        _inject_spatial_extractor(policy_kwargs)
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
            model_params_copy["learning_rate"] = _make_learning_rate_schedule(model_params_copy["learning_rate"])

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
        try:
            model = MaskablePPO.load(model_path, env=env, device=device)
            if "tensorboard_log" not in model_params:
                raise KeyError("model_params missing required 'tensorboard_log' field")
            model.tensorboard_log = model_params["tensorboard_log"]
            model.verbose = model_params["verbose"]

            # CURRICULUM LEARNING: Apply new phase hyperparameters to loaded model
            # This allows Phase 2 to use different learning rates, entropy, etc. than Phase 1
            # while preserving the neural network weights learned in Phase 1
            if "learning_rate" in model_params:
                model.learning_rate = _make_learning_rate_schedule(model_params["learning_rate"])
            if "ent_coef" in model_params:
                model.ent_coef = model_params["ent_coef"]
            if "clip_range" in model_params:
                # Convert to callable schedule function (required by PPO)
                model.clip_range = get_schedule_fn(model_params["clip_range"])
            if "gamma" in model_params:
                model.gamma = model_params["gamma"]
            if "gae_lambda" in model_params:
                model.gae_lambda = model_params["gae_lambda"]
            if "n_steps" in model_params:
                model.n_steps = model_params["n_steps"]
            if "batch_size" in model_params:
                model.batch_size = model_params["batch_size"]
            if "n_epochs" in model_params:
                model.n_epochs = model_params["n_epochs"]
            if "vf_coef" in model_params:
                model.vf_coef = model_params["vf_coef"]
            if "max_grad_norm" in model_params:
                model.max_grad_norm = model_params["max_grad_norm"]

            print(f"✅ Applied new phase hyperparameters: lr={model.learning_rate}, ent={model.ent_coef}, clip={model.clip_range}")

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
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("🆕 Creating new model instead...")
            # Use same specific directory as above
            model_params_copy = model_params.copy()
            model_params_copy["tensorboard_log"] = specific_log_dir
            if "learning_rate" in model_params_copy and isinstance(model_params_copy["learning_rate"], dict):
                model_params_copy["learning_rate"] = _make_learning_rate_schedule(model_params_copy["learning_rate"])
            model = MaskablePPO(env=env, **model_params_copy)
    else:
        print(f"📁 Loading existing model: {model_path}")
        try:
            model = MaskablePPO.load(model_path, env=env, device=device)
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("�' Creating new model instead...")
            # Need to create specific directory here too
            tb_log_name = f"{training_config_name}_{agent_key}"
            specific_log_dir = os.path.join(model_params["tensorboard_log"], tb_log_name)
            os.makedirs(specific_log_dir, exist_ok=True)
            model_params_copy = model_params.copy()
            model_params_copy["tensorboard_log"] = specific_log_dir
            if "learning_rate" in model_params_copy and isinstance(model_params_copy["learning_rate"], dict):
                model_params_copy["learning_rate"] = _make_learning_rate_schedule(model_params_copy["learning_rate"])
            model = MaskablePPO(env=env, **model_params_copy)
    
    _apply_torch_compile(model)
    return model, env, training_config, model_path


def create_macro_controller_model(config, training_config_name, rewards_config_name,
                                  agent_key, new_model=False, append_training=False,
                                  scenario_override=None, debug_mode=False, device_mode: Optional[str] = None):
    """Phase 1 macro controller — removed in Phase 2. Use create_model() instead."""
    raise NotImplementedError(
        "create_macro_controller_model is a Phase 1 artifact and has been removed. "
        "Phase 2 uses the unified micro agent (create_model) with zone intent actions."
    )


def _build_macro_eval_env(config, training_config_name, rewards_config_name, agent_key,
                          scenario_override, debug_mode, bot=None):
    """Phase 1 macro eval env — removed in Phase 2."""
    raise NotImplementedError(
        "_build_macro_eval_env is a Phase 1 artifact and has been removed. "
        "Phase 2 uses the unified micro agent with zone intent actions."
    )


def _print_eval_progress(completed, total, start_time, label):
    progress_pct = (completed / total) * 100
    bar_length = _get_progress_bar_width("macro_eval_width")
    filled = int(bar_length * completed / total)
    bar = '█' * filled + '░' * (bar_length - filled)

    elapsed = time.time() - start_time
    avg_time = elapsed / completed if completed > 0 else 0
    remaining = total - completed
    eta = avg_time * remaining

    def format_time(seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    elapsed_str = format_time(elapsed)
    eta_str = format_time(eta)
    speed = completed / elapsed if elapsed > 0 else 0
    speed_str = f"{speed:.2f}ep/s" if speed >= 0.01 else f"{speed * 60:.1f}ep/m"

    sys.stdout.write(f"\r{progress_pct:3.0f}% {bar} {completed}/{total} {label} [{elapsed_str}<{eta_str}, {speed_str}]")
    sys.stdout.flush()


def _evaluate_macro_model(model, env, n_episodes, macro_player, deterministic=True, progress_state=None, label=""):
    wins = 0
    losses = 0
    draws = 0
    for _ in range(n_episodes):
        obs, _info = env.reset()
        done = False
        info: Any = {}
        while not done:
            action_masks = env.get_action_mask()
            action, _ = model.predict(obs, action_masks=action_masks, deterministic=deterministic)
            obs, _reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
        winner = None
        if isinstance(info, dict):
            winner = info.get("winner")
        if winner is None:
            winner, _win_method = env.engine._determine_winner_with_method()
        if winner == macro_player:
            wins += 1
        elif winner in (1, 2):
            losses += 1
        else:
            draws += 1
        if progress_state is not None:
            progress_state["completed"] += 1
            _print_eval_progress(progress_state["completed"], progress_state["total"], progress_state["start_time"], label)
    return wins, losses, draws

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


def build_training_opponents(
    training_config: Dict[str, Any],
    use_bots: bool,
    total_episodes: Optional[int],
    log: Callable[[str], None],
) -> Dict[str, Any]:
    """Construction de l'adversaire d'entrainement — CHEMIN UNIQUE (V11 §10.4).

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

    if not EVALUATION_BOTS_AVAILABLE:
        raise ImportError("Evaluation bots not available but use_bots=True")

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

    ratios = require_key(training_config, "bot_training").get("ratios", {"random": 0.2, "greedy": 0.4, "defensive": 0.4})
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


def train_with_scenario_rotation(config, agent_key, training_config_name, rewards_config_name,
                                 scenario_list, total_episodes,
                                 new_model=False, append_training=False, use_bots=False, debug_mode=False,
                                 device_mode: Optional[str] = None,
                                 training_config_override: Optional[Dict[str, Any]] = None,
                                 callback_total_episodes_override: Optional[int] = None,
                                 callback_global_episode_offset: int = 0,
                                 callback_phase_episode_offset: int = 0,
                                 phase_label: Optional[str] = None,
                                 silent_chunk: bool = False,
                                 return_run_info: bool = False):
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
        Tuple of (success: bool, final_model, final_env) by default.
        If return_run_info=True, returns (success, final_model, final_env, run_info).
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

    max_steps = resolve_turn_step_limit(scenario_list, training_config, use_bots, chunk_log)

    # Calculate average steps per episode for timestep conversion
    max_turns = get_max_turns()
    avg_steps_per_episode = max_turns * max_steps * 0.6  # Estimate: 60% of max
    
    # Get model path
    models_root = config.get_models_root()
    model_path = build_agent_model_path(models_root, agent_key)
    
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
        vec_envs = SubprocVecEnv([
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
            )
            for i in range(n_envs)
        ])
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
            debug_mode=debug_mode
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
                self_play_opponent_enabled=(
                    bool(opponent_mix_config is not None and opponent_mix_config.get("enabled") is True)
                ),
                self_play_ratio_start=(
                    float(opponent_mix_config["self_play_ratio_start"])
                    if opponent_mix_config is not None and opponent_mix_config.get("enabled") is True
                    else None
                ),
                self_play_ratio_end=(
                    float(opponent_mix_config["self_play_ratio_end"])
                    if opponent_mix_config is not None and opponent_mix_config.get("enabled") is True
                    else None
                ),
                self_play_total_episodes=(
                    int(opponent_mix_config["total_episodes"])
                    if opponent_mix_config is not None and opponent_mix_config.get("enabled") is True
                    else None
                ),
                self_play_warmup_episodes=(
                    int(opponent_mix_config["warmup_episodes"])
                    if opponent_mix_config is not None and opponent_mix_config.get("enabled") is True
                    else None
                ),
                self_play_snapshot_path=(
                    str(opponent_mix_config["snapshot_model_path"])
                    if opponent_mix_config is not None and opponent_mix_config.get("enabled") is True
                    else None
                ),
                self_play_snapshot_refresh_episodes=(
                    int(opponent_mix_config["snapshot_refresh_episodes"])
                    if opponent_mix_config is not None and opponent_mix_config.get("enabled") is True
                    else None
                ),
                self_play_snapshot_device=(
                    str(opponent_mix_config["snapshot_device"])
                    if opponent_mix_config is not None and opponent_mix_config.get("enabled") is True
                    else None
                ),
                self_play_deterministic=(
                    bool(opponent_mix_config["deterministic"])
                    if opponent_mix_config is not None and opponent_mix_config.get("enabled") is True
                    else False
                ),
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

    # Automatic n_steps adjustment when n_envs > 1: keep total steps per update constant
    base_n_steps = model_params.get("n_steps", 10240)
    if n_envs > 1:
        effective_n_steps = max(1, base_n_steps // n_envs)
        model_params["n_steps"] = effective_n_steps
        chunk_log(f"📊 n_envs={n_envs}: using n_steps={effective_n_steps} per env ({base_n_steps} total per update)")

    # Handle entropy coefficient scheduling if configured
    # Use START value for model creation; callback will handle the schedule
    if "ent_coef" in model_params and isinstance(model_params["ent_coef"], dict):
        ent_config = model_params["ent_coef"]
        start_val = float(ent_config["start"])
        end_val = float(ent_config["end"])
        model_params["ent_coef"] = start_val  # Use initial value
        chunk_log(f"✅ Entropy coefficient schedule: {start_val} -> {end_val} (will be applied via callback)")

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
        _inject_spatial_extractor(policy_kwargs)
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
            model_params_copy["learning_rate"] = _make_learning_rate_schedule(lr_cfg)
            chunk_log(f"✅ Learning rate schedule: {lr_cfg['initial']} → {lr_cfg['final']} (linear decay)")
        model = MaskablePPO(env=env, **model_params_copy)
    elif append_training:
        chunk_log(f"📁 Loading existing model for continued training: {model_path}")
        try:
            model = MaskablePPO.load(model_path, env=env, device=device)

            # CURRICULUM LEARNING: Apply new phase hyperparameters to loaded model
            # This allows Phase 2 to use different learning rates, entropy, etc. than Phase 1
            # while preserving the neural network weights learned in Phase 1
            if "learning_rate" in model_params:
                model.learning_rate = _make_learning_rate_schedule(model_params["learning_rate"])
            if "ent_coef" in model_params:
                model.ent_coef = model_params["ent_coef"]
            if "clip_range" in model_params:
                # Convert to callable schedule function (required by PPO)
                model.clip_range = get_schedule_fn(model_params["clip_range"])
            if "gamma" in model_params:
                model.gamma = model_params["gamma"]
            if "gae_lambda" in model_params:
                model.gae_lambda = model_params["gae_lambda"]
            if "n_steps" in model_params:
                model.n_steps = model_params["n_steps"]
                # Rollout buffer buffer_size was set from the checkpoint's n_steps;
                # recreate it so it matches the (possibly adjusted) n_steps.
                from sb3_contrib.common.maskable.buffers import MaskableRolloutBuffer
                model.rollout_buffer = MaskableRolloutBuffer(
                    model.n_steps,
                    model.observation_space,
                    model.action_space,
                    device=model.device,
                    gae_lambda=model.gae_lambda,
                    gamma=model.gamma,
                    n_envs=model.n_envs,
                )
            if "batch_size" in model_params:
                model.batch_size = model_params["batch_size"]
            if "n_epochs" in model_params:
                model.n_epochs = model_params["n_epochs"]
            if "vf_coef" in model_params:
                model.vf_coef = model_params["vf_coef"]
            if "max_grad_norm" in model_params:
                model.max_grad_norm = model_params["max_grad_norm"]

            chunk_log(f"✅ Applied new phase hyperparameters: lr={model.learning_rate}, ent={model.ent_coef}, clip={model.clip_range}")

            # CRITICAL FIX: Reinitialize logger after loading from checkpoint
            # This ensures PPO training metrics (policy_loss, value_loss, etc.) are logged correctly
            # Without this, model.logger.name_to_value remains empty/stale from the checkpoint
            from stable_baselines3.common.logger import configure
            new_logger = configure(specific_log_dir, ["tensorboard"])
            model.set_logger(new_logger)
            chunk_log(f"✅ Logger reinitialized for TensorBoard run: {specific_log_dir}")
        except Exception as e:
            chunk_log(f"⚠️ Failed to load model: {e}")
            chunk_log("🆕 Creating new model instead...")
            model_params_copy = model_params.copy()
            model_params_copy["tensorboard_log"] = specific_log_dir
            if "learning_rate" in model_params_copy and isinstance(model_params_copy["learning_rate"], dict):
                model_params_copy["learning_rate"] = _make_learning_rate_schedule(model_params_copy["learning_rate"])
            model = MaskablePPO(env=env, **model_params_copy)
    else:
        chunk_log(f"⚠️ Model exists but neither --new nor --append specified. Creating new model.")
        model_params_copy = model_params.copy()
        model_params_copy["tensorboard_log"] = specific_log_dir
        if "learning_rate" in model_params_copy and isinstance(model_params_copy["learning_rate"], dict):
            model_params_copy["learning_rate"] = _make_learning_rate_schedule(model_params_copy["learning_rate"])
        model = MaskablePPO(env=env, **model_params_copy)
    
    _apply_torch_compile(model)
    # Import metrics tracker
    from ai.metrics_tracker import W40KMetricsTracker

    # Initialize frozen model for self-play
    # The frozen model is a copy of the learning model used by Player 1
    frozen_model = None
    frozen_model_update_frequency = 100  # Episodes between frozen model updates
    last_frozen_model_update = 0

    # Bot ratios printed when building training_bots

    # Keep tracker aligned with selected run directory.
    model_tensorboard_dir = specific_log_dir
    
    # Create metrics tracker for entire rotation training
    metrics_tracker = W40KMetricsTracker(
        agent_key,
        model_tensorboard_dir,
        initial_episode_count=callback_global_episode_offset,
        initial_step_count=int(getattr(model, "num_timesteps", 0)),
        show_banner=not silent_chunk
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
            debug_mode=debug_mode
        )
        base_env._metrics_tracker = metrics_tracker
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
        model.set_env(env)
    
    def _debug_train_marker(message: str) -> None:
        if debug_mode:
            print(f"[TRAIN DEBUG] {message}", flush=True)

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
        total_episodes_override=(
            callback_total_episodes_override
            if callback_total_episodes_override is not None
            else total_episodes
        ),
        max_episodes_override=total_episodes,  # Train directly to total_episodes
        scenario_info=scenario_display,
        global_episode_offset=callback_global_episode_offset,
        phase_episode_offset=callback_phase_episode_offset,
        global_start_time=global_start_time,
        phase_label=phase_label,
        silent_logs=silent_chunk
    )
    callback_names = [callback.__class__.__name__ for callback in training_callbacks]
    _debug_train_marker(
        f"after setup_callbacks(): count={len(training_callbacks)} callbacks={callback_names}"
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
        "after CallbackList assembly: "
        f"ordered_callbacks={[callback.__class__.__name__ for callback in ordered_training_callbacks]}"
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
    target_episode_count = callback_global_episode_offset + total_episodes
    last_snapshot_episode_count = metrics_tracker.episode_count
    if self_play_snapshot_enabled:
        _debug_train_marker("before initial self-play snapshot publish")
        _publish_self_play_snapshot()
        _debug_train_marker("after initial self-play snapshot publish")
    _debug_train_marker(
        "before learn loop: "
        f"episode_count={metrics_tracker.episode_count} "
        f"target_episode_count={target_episode_count} "
        f"chunk_timesteps={chunk_timesteps} "
        f"model_num_timesteps={model.num_timesteps}"
    )
    while metrics_tracker.episode_count < target_episode_count:
        # As a safety guard, we still use the same chunk_timesteps. 
        # EpisodeTerminationCallback is responsible for stopping promptly when the episode budget is reached.
        _debug_train_marker(
            "before model.learn(): "
            f"episode_count={metrics_tracker.episode_count} "
            f"target_episode_count={target_episode_count} "
            f"chunk_timesteps={chunk_timesteps} "
            f"model_num_timesteps={model.num_timesteps}"
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
            "after model.learn(): "
            f"episode_count={metrics_tracker.episode_count} "
            f"target_episode_count={target_episode_count} "
            f"chunk_timesteps={chunk_timesteps} "
            f"model_num_timesteps={model.num_timesteps}"
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
    episodes_trained = metrics_tracker.episode_count - callback_global_episode_offset

    callback_params = require_key(training_config, "callback_params")
    save_best_robust = bool(require_key(callback_params, "save_best_robust"))

    # Final save unless robust mode owns canonical output.
    if not save_best_robust:
        _debug_train_marker("before final model.save()")
        model.save(model_path)
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
    if EVALUATION_BOTS_AVAILABLE:
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
                    known_bot_keys = (
                        "random",
                        "greedy",
                        "defensive",
                        "control",
                        "aggressive_smart",
                        "defensive_smart",
                        "adaptive",
                        "tactical",  # V11 §10.5 : holdout d'evaluation
                    )
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
                    for bot_name in sorted(bot_results.keys()):
                        if bot_name.endswith(('_wins', '_losses', '_draws', '_episodes')) or bot_name in ('combined', 'worst_bot_score', 'worst_bot_name', 'eval_reliable', 'eval_duration_seconds', 'total_failed_episodes'):
                            continue
                        if isinstance(bot_results[bot_name], (int, float)):
                            win_rate = bot_results[bot_name] * 100
                            wins = bot_results.get(f'{bot_name}_wins', '?')
                            losses = bot_results.get(f'{bot_name}_losses', '?')
                            draws = bot_results.get(f'{bot_name}_draws', '?')
                            print(f"  vs {bot_name:20s}: {win_rate:5.1f}% ({wins}W-{losses}L-{draws}D)")

                    combined = require_key(bot_results, 'combined') * 100
                    print(f"  Combined Score: {combined:5.1f}%")
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

def setup_callbacks(config, model_path, training_config, training_config_name="default", metrics_tracker=None,
                   total_episodes_override=None, max_episodes_override=None, scenario_info=None, global_episode_offset=0,
                   phase_episode_offset: int = 0,
                   global_start_time=None, agent=None, rewards_config_name=None,
                   phase_label: Optional[str] = None, silent_logs: bool = False):
    W40KEngine, _ = setup_imports()
    callbacks = []
    total_eps = 0

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
            phase_label=phase_label,
            phase_episode_offset=phase_episode_offset,
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
            total_eps = total_episodes_override if total_episodes_override else training_config["total_episodes"]
            lr_callback = LearningRateScheduleCallback(
                start_lr=start_lr,
                end_lr=end_lr,
                total_episodes=total_eps,
                initial_episode_count=phase_episode_offset,
                verbose=1
            )
            callbacks.append(lr_callback)
            if not silent_logs:
                print(f"✅ Added learning-rate schedule callback: {start_lr} -> {end_lr} over {total_eps} episodes")

    # Add entropy coefficient schedule callback if configured
    if "model_params" in training_config and "ent_coef" in training_config["model_params"]:
        ent_coef = training_config["model_params"]["ent_coef"]
        if isinstance(ent_coef, dict) and "start" in ent_coef and "end" in ent_coef:
            start_ent = float(ent_coef["start"])
            end_ent = float(ent_coef["end"])
            total_eps = total_episodes_override if total_episodes_override else training_config["total_episodes"]

            entropy_callback = EntropyScheduleCallback(
                start_ent=start_ent,
                end_ent=end_ent,
                total_episodes=total_eps,
                initial_episode_count=phase_episode_offset,
                verbose=1
            )
            callbacks.append(entropy_callback)
            if not silent_logs:
                print(f"✅ Added entropy schedule callback: {start_ent} -> {end_ent} over {total_eps} episodes")

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

        class RotatingCheckpointCallback(CheckpointCallback):
            """Checkpoint callback that keeps only the most recent N checkpoints."""

            def __init__(self, max_checkpoints: int, **kwargs):
                super().__init__(**kwargs)
                self.max_checkpoints = max_checkpoints

            def _cleanup_old_checkpoints(self) -> None:
                pattern = os.path.join(self.save_path, f"{self.name_prefix}_*_steps.zip")
                checkpoint_files = sorted(
                    glob.glob(pattern),
                    key=lambda p: os.path.getmtime(p),
                    reverse=True,
                )
                for old_checkpoint in checkpoint_files[self.max_checkpoints:]:
                    if os.path.exists(old_checkpoint):
                        os.remove(old_checkpoint)

            def _on_step(self) -> bool:
                continue_training = super()._on_step()
                if self.save_freq > 0 and self.n_calls % self.save_freq == 0:
                    self._cleanup_old_checkpoints()
                return continue_training

        checkpoint_callback = RotatingCheckpointCallback(
            max_checkpoints=max_checkpoints,
            save_freq=callback_params["checkpoint_save_freq"],
            save_path=os.path.dirname(model_path),
            name_prefix=callback_params["checkpoint_name_prefix"],
        )
    else:
        checkpoint_callback = CheckpointCallback(
            save_freq=callback_params["checkpoint_save_freq"],
            save_path=os.path.dirname(model_path),
            name_prefix=callback_params["checkpoint_name_prefix"]
        )
    callbacks.append(checkpoint_callback)
    
    # Add enhanced bot evaluation callback (replaces standard EvalCallback)
    if EVALUATION_BOTS_AVAILABLE:
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
        save_best_robust = bool(_resolve_callback_value("save_best_robust"))
        model_gating_enabled = bool(_resolve_callback_value("model_gating_enabled"))
        model_gating_min_combined = None
        model_gating_min_worst_bot = None
        model_gating_min_worst_scenario_combined = None
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
                gate_display_state=training_config.get("_gate_display_state"),
                eval_deterministic=eval_deterministic,
                final_summary_target_episodes=total_eps,
                initial_episode_marker=max(0, int(global_episode_offset)),
                show_eval_progress=bot_eval_show_progress,
                phase_progress_total_episodes=(int(total_eps) if phase_label else None),
                phase_progress_episode_offset=(int(phase_episode_offset) if phase_label else 0),
                early_stopping_patience=int(callback_params["early_stopping_patience"]),
                save_best_min_episodes=int(callback_params["save_best_min_episodes"]),
            )
            callbacks.append(bot_eval_callback)
        
        freq_unit = "episodes" if bot_eval_use_episodes else "timesteps"
    else:
        if not silent_logs:
            print("⚠️ Evaluation bots not available - no evaluation metrics")
            print("   Install evaluation_bots.py to enable progress tracking")
    
    return callbacks

def train_model(model, training_config, callbacks, model_path, training_config_name, rewards_config_name, controlled_agent=None):
    """Execute the training process with metrics tracking."""
    
    # Import metrics tracker
    from ai.metrics_tracker import W40KMetricsTracker
    
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
    metrics_tracker = W40KMetricsTracker(agent_name, model_tensorboard_dir)
    
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
                    if verbose := 0:  # Only log if verbose
                        print(f"   Removed: {os.path.basename(checkpoint_file)}")
                except Exception as e:
                    print(f"   ⚠️  Could not remove {os.path.basename(checkpoint_file)}: {e}")
            print(f"✅ Checkpoint cleanup complete")
        
        # Also remove interrupted file if it exists
        interrupted_path = model_path.replace('.zip', '_interrupted.zip')
        if os.path.exists(interrupted_path):
            try:
                os.remove(interrupted_path)
                print(f"🧹 Removed old interrupted file")
            except Exception as e:
                print(f"   ⚠️  Could not remove interrupted file: {e}")
        
        return True
        
    except KeyboardInterrupt:
        print("\n⏹️ Training interrupted by user")
        # Save current progress
        interrupted_path = model_path.replace('.zip', '_interrupted.zip')
        model.save(interrupted_path)
        if save_vec_normalize(model.get_env(), interrupted_path):
            print("   VecNormalize stats saved")
        print(f"💾 Progress saved to: {interrupted_path}")
        return False
        
    except Exception as e:
        print(f"❌ Training failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_trained_model(model, num_episodes, training_config_name="default", agent_key=None, rewards_config_name="default", debug_mode=False):
    """Test the trained model."""
    
    W40KEngine, _ = setup_imports()
    # Load scenario and unit registry for testing
    from ai.unit_registry import UnitRegistry
    cfg = get_config_loader()
    scenario_file = os.path.join(cfg.config_dir, "scenario.json")
    unit_registry = UnitRegistry()
    
    env = W40KEngine(
        rewards_config=rewards_config_name,
        training_config_name=training_config_name,
        controlled_agent=agent_key,
        active_agents=None,
        scenario_file=scenario_file,
        unit_registry=unit_registry,
        quiet=True,
        debug_mode=debug_mode
    )
    wins = 0
    total_rewards = []
    
    for episode in range(num_episodes):
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
            wins += 1
    
    if num_episodes <= 0:
            raise ValueError("num_episodes must be positive - no default episodes allowed")
    
    win_rate = wins / num_episodes
    avg_reward = sum(total_rewards) / len(total_rewards)
    
    print(f"\n📊 Test Results:")
    print(f"   Win Rate: {win_rate:.1%} ({wins}/{num_episodes})")
    print(f"   Average Reward: {avg_reward:.2f}")
    print(f"   Reward Range: {min(total_rewards):.2f} to {max(total_rewards):.2f}")
    
    env.close()
    return win_rate, avg_reward

def test_scenario_manager_integration():
    """Test scenario manager integration."""
    print("🧪 Testing Scenario Manager Integration")
    print("=" * 50)
    
    try:
        config = get_config_loader()
        
        # Test unit registry integration
        unit_registry = UnitRegistry()
        
        # Test scenario manager
        scenario_manager = ScenarioManager(config, unit_registry)
        print(f"✅ ScenarioManager initialized with {len(scenario_manager.get_available_templates())} templates")
        agents = unit_registry.get_required_models()
        print(f"✅ UnitRegistry found {len(agents)} agents: {agents}")
        
        # Test scenario generation
        if len(agents) >= 2:
            template_name = scenario_manager.get_available_templates()[0]
            scenario = scenario_manager.generate_training_scenario(
                template_name, agents[0], agents[1]
            )
            print(f"✅ Generated scenario with {len(scenario['units'])} units")
        
        # Test training rotation
        rotation = scenario_manager.get_balanced_training_rotation(100)
        print(f"✅ Generated training rotation with {len(rotation)} matchups")
        
        print("🎉 Scenario manager integration tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def _get_curriculum_log_path(agent_key: str) -> str:
    """Return the curriculum log path for an agent."""
    return os.path.join(project_root, "logs", f"{agent_key}.curriculum.log")


def _write_curriculum_event(log_path: str, event_type: str, payload: Dict[str, Any]) -> None:
    """Append one structured curriculum event (JSON line)."""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "event": event_type,
    }
    entry.update(payload)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def _get_phase_scenarios(config, agent_key: str, phase_name: str) -> List[str]:
    """Get all scenario files for one curriculum phase directory."""
    phase_dir = os.path.join(config.config_dir, "agents", agent_key, "scenarios", phase_name)
    if not os.path.isdir(phase_dir):
        raise FileNotFoundError(
            f"Missing curriculum scenario directory: {phase_dir}. "
            f"Create it and add scenario json files."
        )
    scenarios = sorted(glob.glob(os.path.join(phase_dir, "*.json")))
    if not scenarios:
        raise FileNotFoundError(
            f"No scenario files found in {phase_dir}. Expected at least one *.json file."
        )
    return scenarios


def _build_phase_mix(
    current_phase_scenarios: List[str],
    previous_phase_scenarios: List[str],
    current_ratio_percent: int,
    previous_ratio_percent: int
) -> List[str]:
    """Build weighted scenario list for one curriculum phase chunk."""
    if current_ratio_percent <= 0:
        raise ValueError(
            f"curriculum current_phase_ratio_percent must be > 0 (got {current_ratio_percent})"
        )
    if previous_ratio_percent < 0:
        raise ValueError(
            f"curriculum previous_phase_ratio_percent must be >= 0 (got {previous_ratio_percent})"
        )
    if (current_ratio_percent + previous_ratio_percent) != 100:
        raise ValueError(
            "curriculum ratios must sum to 100: "
            f"current_phase_ratio_percent={current_ratio_percent}, "
            f"previous_phase_ratio_percent={previous_ratio_percent}"
        )
    if previous_ratio_percent > 0 and not previous_phase_scenarios:
        raise ValueError(
            "previous_phase_ratio_percent > 0 but there is no previous phase scenario pool"
        )

    weighted = list(current_phase_scenarios) * current_ratio_percent
    if previous_phase_scenarios:
        weighted.extend(list(previous_phase_scenarios) * previous_ratio_percent)
    return weighted


def _apply_bot_matchup_multipliers(
    phase_scenarios: List[str],
    phase_cfg: Dict[str, Any],
) -> List[str]:
    """
    Apply optional per-matchup multipliers inside one phase scenario pool.

    Config format (optional):
      "bot_matchup_multipliers": {
        "bot-3": 2
      }

    Matching rule:
    - key is matched against scenario basename (substring), or exact basename/stem.
    - default multiplier is 1 when no key matches.
    """
    multipliers_cfg = phase_cfg.get("bot_matchup_multipliers")
    if multipliers_cfg is None:
        return list(phase_scenarios)
    if not isinstance(multipliers_cfg, dict):
        raise ValueError(
            f"bot_matchup_multipliers must be a dictionary (got {type(multipliers_cfg).__name__})"
        )
    if len(multipliers_cfg) == 0:
        raise ValueError("bot_matchup_multipliers cannot be empty when provided")

    validated_multipliers: Dict[str, int] = {}
    for key, value in multipliers_cfg.items():
        if not isinstance(key, str) or key.strip() == "":
            raise ValueError("bot_matchup_multipliers keys must be non-empty strings")
        multiplier = int(value)
        if multiplier <= 0:
            raise ValueError(
                f"bot_matchup_multipliers['{key}'] must be > 0 (got {multiplier})"
            )
        validated_multipliers[key] = multiplier

    key_match_counts: Dict[str, int] = {key: 0 for key in validated_multipliers}
    expanded_scenarios: List[str] = []
    for scenario_path in phase_scenarios:
        basename = os.path.basename(scenario_path)
        stem = os.path.splitext(basename)[0]
        matching_keys = [
            key for key in validated_multipliers
            if key in basename or key == basename or key == stem
        ]
        if len(matching_keys) > 1:
            raise ValueError(
                f"Ambiguous bot_matchup_multipliers for scenario '{basename}': "
                f"matched keys={matching_keys}"
            )

        scenario_multiplier = 1
        if matching_keys:
            matched_key = matching_keys[0]
            key_match_counts[matched_key] += 1
            scenario_multiplier = validated_multipliers[matched_key]
        expanded_scenarios.extend([scenario_path] * scenario_multiplier)

    missing_keys = [key for key, count in key_match_counts.items() if count == 0]
    if missing_keys:
        raise ValueError(
            "bot_matchup_multipliers keys did not match any scenario file: "
            f"{missing_keys}"
        )

    return expanded_scenarios


def _extract_worst_bot_scores_for_gate(eval_results: Dict[str, Any]) -> Tuple[float, float]:
    """
    Extract (mean, min_raw) worst-bot scores for curriculum gates.

    Gate semantics:
    - mean: primary threshold for phase transition stability
    - min_raw: safety floor to avoid passing with a severe blind spot

    Raises:
        ValueError: If scenario_scores are missing/invalid.
    """
    scenario_scores = eval_results.get("scenario_scores")
    if not isinstance(scenario_scores, dict) or len(scenario_scores) == 0:
        raise ValueError(
            "Missing scenario_scores for curriculum gate worst-bot aggregation. "
            "Expected non-empty 'scenario_scores' dictionary."
        )

    scenario_worst_scores: List[float] = []
    for scenario_name, values in scenario_scores.items():
        if not isinstance(values, dict):
            raise ValueError(
                "Invalid scenario_scores format for curriculum gate: "
                f"scenario '{scenario_name}' must map to a dictionary."
            )
        if "worst_bot_score" not in values:
            raise ValueError(
                "Invalid scenario_scores format for curriculum gate: "
                f"scenario '{scenario_name}' missing required key 'worst_bot_score'."
            )
        scenario_worst_scores.append(float(require_key(values, "worst_bot_score")))

    if not scenario_worst_scores:
        raise ValueError(
            "Cannot compute curriculum gate worst-bot aggregation: scenario_scores is empty."
        )

    mean_score = float(sum(scenario_worst_scores) / len(scenario_worst_scores))
    min_raw_score = float(min(scenario_worst_scores))
    return mean_score, min_raw_score


def _format_phase_label_for_display(phase_name: str) -> str:
    """Format curriculum phase name for user-facing progress."""
    if phase_name.startswith("phase") and len(phase_name) > 5 and phase_name[5:].isdigit():
        return f"phase {phase_name[5:]}"
    return phase_name


def _build_curriculum_phase_progress_prefix(
    phase_episodes: int,
    max_episodes_in_phase: int,
    bar_length: Optional[int] = None
) -> str:
    """Build fixed left progress panel for curriculum gate evaluations."""
    if max_episodes_in_phase <= 0:
        raise ValueError(
            f"max_episodes_in_phase must be > 0 (got {max_episodes_in_phase})"
        )
    if bar_length is None:
        bar_length = _get_progress_bar_width("curriculum_phase_width")
    bounded_episodes = min(max(phase_episodes, 0), max_episodes_in_phase)
    progress_ratio = bounded_episodes / max_episodes_in_phase
    progress_pct = progress_ratio * 100.0
    filled = int(bar_length * progress_ratio)
    bar = '█' * filled + '░' * (bar_length - filled)
    return f"{progress_pct:3.0f}% {bar} {bounded_episodes}/{max_episodes_in_phase}"


def _print_inline_status_line(line: str) -> None:
    """
    Print an inline terminal status line with proper cleanup of leftovers
    from previous longer lines.
    """
    current_len = len(line)
    previous_len = getattr(_print_inline_status_line, "_last_len", 0)
    clear_padding = " " * max(0, previous_len - current_len)
    print(f"\r{line}{clear_padding}", end="", flush=True)
    cast(Any, _print_inline_status_line)._last_len = current_len


def train_with_curriculum(
    config,
    agent_key: str,
    training_config_name: str,
    rewards_config_name: str,
    start_phase: str,
    new_model: bool = False,
    append_training: bool = False,
    debug_mode: bool = False,
    device_mode: Optional[str] = None
):
    """Run multi-phase curriculum training from start_phase."""
    training_config = config.load_agent_training_config(agent_key, training_config_name)
    curriculum = require_key(training_config, "curriculum")
    enabled = require_key(curriculum, "enabled")
    if not isinstance(enabled, bool) or not enabled:
        raise ValueError(
            f"Curriculum is disabled in {agent_key}/{training_config_name} training config"
        )

    phase_order = require_key(curriculum, "phase_order")
    if not isinstance(phase_order, list) or not phase_order:
        raise ValueError("curriculum.phase_order must be a non-empty list")
    if start_phase not in phase_order:
        raise ValueError(
            f"start_phase '{start_phase}' not present in curriculum.phase_order={phase_order}"
        )

    phases_cfg = require_key(curriculum, "phases")
    current_ratio_percent = int(require_key(curriculum, "current_phase_ratio_percent"))
    previous_ratio_percent = int(require_key(curriculum, "previous_phase_ratio_percent"))

    callback_params = require_key(training_config, "callback_params")
    bot_eval_freq = int(require_key(callback_params, "bot_eval_freq"))
    bot_eval_use_episodes = require_key(callback_params, "bot_eval_use_episodes")
    if not isinstance(bot_eval_use_episodes, bool) or not bot_eval_use_episodes:
        raise ValueError("Curriculum requires callback_params.bot_eval_use_episodes=true")
    if bot_eval_freq <= 0:
        raise ValueError(f"callback_params.bot_eval_freq must be > 0 (got {bot_eval_freq})")
    gate_eval_freq = int(require_key(curriculum, "gate_eval_freq"))
    if gate_eval_freq <= 0:
        raise ValueError(f"curriculum.gate_eval_freq must be > 0 (got {gate_eval_freq})")
    if gate_eval_freq % bot_eval_freq != 0:
        raise ValueError(
            "curriculum.gate_eval_freq must be a multiple of callback_params.bot_eval_freq "
            f"(got gate_eval_freq={gate_eval_freq}, bot_eval_freq={bot_eval_freq})"
        )

    start_index = phase_order.index(start_phase)
    selected_phases = phase_order[start_index:]
    log_path = _get_curriculum_log_path(agent_key)

    _write_curriculum_event(
        log_path,
        "curriculum_start",
        {
            "agent": agent_key,
            "training_config": training_config_name,
            "rewards_config": rewards_config_name,
            "start_phase": start_phase,
            "phase_order": selected_phases
        }
    )

    first_run = True
    total_global_episodes = 0
    previous_phase_scenarios: List[str] = []
    final_model = None
    final_env = None
    final_run_info: Dict[str, Any] = {}

    for phase_index, phase_name in enumerate(selected_phases):
        phase_cfg = require_key(phases_cfg, phase_name)
        min_episodes_in_phase = int(require_key(phase_cfg, "min_episodes_in_phase"))
        max_episodes_in_phase = int(require_key(phase_cfg, "max_episodes_in_phase"))
        combined_min = float(require_key(phase_cfg, "combined_min"))
        worst_bot_score_mean_min = float(require_key(phase_cfg, "worst_bot_score_min"))
        worst_bot_score_floor_min = float(require_key(phase_cfg, "worst_bot_score_floor_min"))
        consecutive_evals_required = int(require_key(phase_cfg, "consecutive_evals_required"))

        if min_episodes_in_phase <= 0:
            raise ValueError(
                f"{phase_name}.min_episodes_in_phase must be > 0 (got {min_episodes_in_phase})"
            )
        if max_episodes_in_phase < min_episodes_in_phase:
            raise ValueError(
                f"{phase_name}.max_episodes_in_phase must be >= min_episodes_in_phase "
                f"({max_episodes_in_phase} < {min_episodes_in_phase})"
            )
        if consecutive_evals_required <= 0:
            raise ValueError(
                f"{phase_name}.consecutive_evals_required must be > 0 "
                f"(got {consecutive_evals_required})"
            )

        raw_phase_scenarios = _get_phase_scenarios(config, agent_key, phase_name)
        current_phase_scenarios = _apply_bot_matchup_multipliers(raw_phase_scenarios, phase_cfg)
        phase_label = _format_phase_label_for_display(phase_name)
        print(
            f"\n🎯 Phase start: {phase_label} "
            f"({phase_index + 1}/{len(selected_phases)}) | "
            f"target combined>={combined_min:.3f}, worst_bot_score_mean>={worst_bot_score_mean_min:.3f}, "
            f"worst_bot_score_min_raw>={worst_bot_score_floor_min:.3f}, "
            f"consecutive={consecutive_evals_required}, min_ep={min_episodes_in_phase}, max_ep={max_episodes_in_phase}"
        )
        _write_curriculum_event(
            log_path,
            "phase_start",
            {
                "agent": agent_key,
                "phase": phase_name,
                "phase_index": phase_index + 1,
                "phase_count": len(selected_phases),
                "scenario_count": len(current_phase_scenarios),
                "min_episodes_in_phase": min_episodes_in_phase,
                "max_episodes_in_phase": max_episodes_in_phase,
                "combined_min": combined_min,
                "worst_bot_score_mean_min": worst_bot_score_mean_min,
                "worst_bot_score_floor_min": worst_bot_score_floor_min,
                "consecutive_evals_required": consecutive_evals_required
            }
        )

        phase_episodes = 0
        consecutive_ok = 0
        phase_eval_index = 0
        phase_completed = False
        is_last_phase = (phase_name == selected_phases[-1])
        combined = 0.0
        worst_bot_score_mean = 0.0
        worst_bot_score_min_raw = 0.0

        while phase_episodes < max_episodes_in_phase:
            remaining = max_episodes_in_phase - phase_episodes
            chunk_episodes = min(bot_eval_freq, remaining)
            if chunk_episodes <= 0:
                raise ValueError(f"Invalid curriculum chunk size for phase {phase_name}: {chunk_episodes}")

            mixed_scenarios = _build_phase_mix(
                current_phase_scenarios=current_phase_scenarios,
                previous_phase_scenarios=previous_phase_scenarios,
                current_ratio_percent=current_ratio_percent if previous_phase_scenarios else 100,
                previous_ratio_percent=previous_ratio_percent if previous_phase_scenarios else 0
            )

            chunk_config = deepcopy(training_config)
            chunk_config["total_episodes"] = chunk_episodes
            chunk_callback_params = require_key(chunk_config, "callback_params")
            chunk_bot_eval_freq = min(bot_eval_freq, chunk_episodes)
            if chunk_bot_eval_freq <= 0:
                raise RuntimeError(
                    f"Invalid chunk bot_eval_freq={chunk_bot_eval_freq} "
                    f"for phase={phase_name}, chunk_episodes={chunk_episodes}"
                )
            chunk_callback_params["bot_eval_freq"] = chunk_bot_eval_freq
            # In curriculum mode, disable per-chunk final evaluation.
            # A single final evaluation is executed once after the whole curriculum.
            chunk_callback_params["bot_eval_final"] = 0

            # Robust checkpoint summary is relevant only for the final phase.
            if not is_last_phase:
                chunk_callback_params["save_best_robust"] = False

            success, model, env, run_info = cast(Tuple[Any, Any, Any, Any], train_with_scenario_rotation(
                config=config,
                agent_key=agent_key,
                training_config_name=training_config_name,
                rewards_config_name=rewards_config_name,
                scenario_list=mixed_scenarios,
                total_episodes=chunk_episodes,
                new_model=(new_model and first_run),
                append_training=(append_training or not first_run),
                use_bots=True,
                debug_mode=debug_mode,
                device_mode=device_mode,
                training_config_override=chunk_config,
                callback_total_episodes_override=max_episodes_in_phase,
                callback_global_episode_offset=total_global_episodes,
                callback_phase_episode_offset=phase_episodes,
                phase_label=phase_label,
                silent_chunk=True,
                return_run_info=True
            ))
            if not success:
                return False, model, env

            first_run = False
            final_model = model
            final_env = env
            final_run_info = run_info
            chunk_episodes_trained = int(require_key(run_info, "episodes_trained"))
            if chunk_episodes_trained <= 0:
                raise RuntimeError(
                    f"Invalid chunk episodes_trained={chunk_episodes_trained} "
                    f"for phase={phase_name}, expected > 0"
                )
            if chunk_episodes_trained < chunk_episodes:
                raise RuntimeError(
                    f"Chunk trained fewer episodes than requested: "
                    f"trained={chunk_episodes_trained}, requested={chunk_episodes} "
                    f"(phase={phase_name})."
                )
            phase_episodes += chunk_episodes_trained
            total_global_episodes += chunk_episodes_trained

            is_gate_eval_checkpoint = (
                (phase_episodes % gate_eval_freq == 0)
                or (phase_episodes >= max_episodes_in_phase)
            )
            if not is_gate_eval_checkpoint:
                continue

            phase_eval_index += 1
            eval_progress_prefix = _build_curriculum_phase_progress_prefix(
                phase_episodes=phase_episodes,
                max_episodes_in_phase=max_episodes_in_phase
            )
            last_eval = run_info.get("last_bot_eval")
            if last_eval is None:
                raise RuntimeError(
                    "Curriculum gate requires synchronized bot evaluation result, but run_info['last_bot_eval'] "
                    f"is missing at phase={phase_name}, phase_episodes={phase_episodes}, "
                    f"global_episodes={total_global_episodes}. "
                    "No implicit alternate evaluation is allowed by strict mode."
                )
            last_eval_marker = run_info.get("last_bot_eval_marker")
            if last_eval_marker is None:
                raise RuntimeError(
                    "Curriculum gate requires synchronized bot evaluation marker, but run_info['last_bot_eval_marker'] "
                    f"is missing at phase={phase_name}, phase_episodes={phase_episodes}, "
                    f"global_episodes={total_global_episodes}. "
                    "No implicit alternate evaluation is allowed by strict mode."
                )
            if int(last_eval_marker) != int(total_global_episodes):
                raise RuntimeError(
                    "Curriculum gate evaluation is out of sync: "
                    f"expected marker={total_global_episodes}, got marker={last_eval_marker} "
                    f"(phase={phase_name}, phase_episodes={phase_episodes}). "
                    "No implicit alternate evaluation is allowed by strict mode."
                )

            # Redraw fixed training state immediately after evaluation output.
            _print_inline_status_line(f"{eval_progress_prefix} | training | {phase_label}")

            combined = float(require_key(last_eval, "combined"))
            worst_bot_score_mean, worst_bot_score_min_raw = _extract_worst_bot_scores_for_gate(last_eval)
            gate_now = (
                phase_episodes >= min_episodes_in_phase
                and combined >= combined_min
                and worst_bot_score_mean >= worst_bot_score_mean_min
                and worst_bot_score_min_raw >= worst_bot_score_floor_min
            )
            consecutive_ok = (consecutive_ok + 1) if gate_now else 0

            _write_curriculum_event(
                log_path,
                "phase_eval",
                {
                    "agent": agent_key,
                    "phase": phase_name,
                    "phase_episodes": phase_episodes,
                    "global_episodes": total_global_episodes,
                    "combined": combined,
                    "worst_bot_score_mean": worst_bot_score_mean,
                    "worst_bot_score_min_raw": worst_bot_score_min_raw,
                    "gate_ok": gate_now,
                    "consecutive_ok": consecutive_ok
                }
            )

            if consecutive_ok >= consecutive_evals_required:
                print()
                print(
                    f"✅ Phase transition: {phase_label} -> "
                    f"{_format_phase_label_for_display(selected_phases[phase_index + 1]) if not is_last_phase else 'end'}\n"
                    f"   trigger eval: {phase_eval_index}\n"
                    f"   targets: combined>={combined_min:.3f}, worst_bot_score_mean>={worst_bot_score_mean_min:.3f}, "
                    f"worst_bot_score_min_raw>={worst_bot_score_floor_min:.3f}, "
                    f"consecutive>={consecutive_evals_required}, min_ep>={min_episodes_in_phase}\n"
                    f"   reached: combined={combined:.3f}, worst_bot_score_mean={worst_bot_score_mean:.3f}, "
                    f"worst_bot_score_min_raw={worst_bot_score_min_raw:.3f}, "
                    f"consecutive={consecutive_ok}, phase_ep={phase_episodes}"
                )
                _write_curriculum_event(
                    log_path,
                    "phase_complete",
                    {
                        "agent": agent_key,
                        "phase": phase_name,
                        "reason": "gate_reached",
                        "phase_episodes": phase_episodes,
                        "global_episodes": total_global_episodes
                    }
                )
                phase_completed = True
                break

        if not phase_completed:
            print()
            print(
                f"✅ Phase transition (max reached): {phase_label} -> "
                f"{_format_phase_label_for_display(selected_phases[phase_index + 1]) if not is_last_phase else 'end'}\n"
                f"   last eval: {phase_eval_index}\n"
                f"   targets: combined>={combined_min:.3f}, worst_bot_score_mean>={worst_bot_score_mean_min:.3f}, "
                f"worst_bot_score_min_raw>={worst_bot_score_floor_min:.3f}, "
                f"consecutive>={consecutive_evals_required}, min_ep>={min_episodes_in_phase}\n"
                f"   reached: combined={combined:.3f}, worst_bot_score_mean={worst_bot_score_mean:.3f}, "
                f"worst_bot_score_min_raw={worst_bot_score_min_raw:.3f}, "
                f"max_ep={max_episodes_in_phase}, phase_ep={phase_episodes}"
            )
            _write_curriculum_event(
                log_path,
                "phase_complete",
                {
                    "agent": agent_key,
                    "phase": phase_name,
                    "reason": "max_episodes_reached",
                    "phase_episodes": phase_episodes,
                    "global_episodes": total_global_episodes
                }
            )

        previous_phase_scenarios = current_phase_scenarios

    if final_run_info:
        _write_curriculum_event(
            log_path,
            "curriculum_final_summary",
            {
                "agent": agent_key,
                "best_robust_score": final_run_info.get("best_robust_score"),
                "combined_at_robust_best": final_run_info.get("best_robust_combined"),
                "selected_at_episodes": final_run_info.get("best_robust_eval_marker")
            }
        )

    final_eval_episodes = int(require_key(callback_params, "bot_eval_final"))
    if final_eval_episodes > 0:
        final_eval_deterministic = require_key(callback_params, "eval_deterministic")
        if not isinstance(final_eval_deterministic, bool):
            raise ValueError(
                f"callback_params.eval_deterministic must be boolean "
                f"(got {type(final_eval_deterministic).__name__})"
            )
        print("\n" + "=" * 80)
        print(
            f"🤖 CURRICULUM FINAL BOT EVALUATION "
            f"({final_eval_episodes} episodes per bot across all scenarios)"
        )
        print("=" * 80 + "\n")
        final_eval_results = evaluate_against_bots(
            model=final_model,
            training_config_name=training_config_name,
            rewards_config_name=rewards_config_name,
            n_episodes=final_eval_episodes,
            controlled_agent=rewards_config_name,
            show_progress=True,
            deterministic=final_eval_deterministic,
            show_summary=True,
            scenario_pool="holdout",
        )
        _write_curriculum_event(
            log_path,
            "curriculum_final_bot_eval",
            {
                "agent": agent_key,
                "episodes_per_bot": final_eval_episodes,
                "deterministic": final_eval_deterministic,
                "combined": final_eval_results.get("combined"),
            }
        )
    _write_curriculum_event(
        log_path,
        "curriculum_end",
        {
            "agent": agent_key,
            "global_episodes": total_global_episodes
        }
    )

    return True, final_model, final_env

def start_multi_agent_orchestration(config, total_episodes: int, training_config_name: str = "default",
                                   rewards_config_name: str = "default", max_concurrent: Optional[int] = None,
                                   training_phase: Optional[str] = None):
    """Start multi-agent orchestration training with optional phase specification."""
    
    try:
        trainer = MultiAgentTrainer(config, max_concurrent_sessions=max_concurrent)
        results = trainer.start_balanced_training(
            total_episodes=total_episodes,
            training_config_name=training_config_name,
            rewards_config_name=rewards_config_name,
            training_phase=training_phase
        )
        
        print(f"✅ Orchestration completed: {results['total_matchups']} matchups")
        return results
        
    except Exception as e:
        print(f"❌ Orchestration failed: {e}")
        return None

def main():
    """Main training function following AI_INSTRUCTIONS.md exactly."""
    parser = argparse.ArgumentParser(description="Train W40K AI (see Documentation/AI_TURN.md and AI_IMPLEMENTATION.md)")
    parser.add_argument("--training-config", default=None,
                       help="Training config phase name (required, no silent default; e.g. x1, x1_debug)")
    parser.add_argument("--rewards-config", default=None,
                       help="Rewards config (default: same as --agent when agent set, else 'default')")
    parser.add_argument("--new", action="store_true", 
                       help="Force creation of new model")
    parser.add_argument("--append", action="store_true", 
                       help="Continue training existing model")
    parser.add_argument("--test-only", action="store_true", 
                       help="Only test existing model, don't train")
    parser.add_argument("--eval", action="store_true",
                       help="Alias for --test-only")
    parser.add_argument("--test-episodes", type=int, default=0, 
                       help="Number of episodes for testing")
    parser.add_argument("--multi-agent", action="store_true",
                       help="Use multi-agent training system")
    parser.add_argument("--agent", type=str, default=None,
                       help="Train specific agent (e.g., 'SpaceMarine_Ranged')")
    parser.add_argument("--orchestrate", action="store_true",
                       help="Start balanced multi-agent orchestration training")
    parser.add_argument("--total-episodes", type=int, default=None,
                       help="Total episodes for training (overrides config file value)")
    parser.add_argument("--max-concurrent", type=int, default=None,
                       help="Maximum concurrent training sessions")
    parser.add_argument("--training-phase", type=str, choices=["solo", "cross_faction", "full_composition"],
                       help="Specific training phase for 3-phase training plan")
    parser.add_argument("--test-integration", action="store_true",
                       help="Test scenario manager integration")
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
                       help="Scenario (default: default; use 'bot' for bot training, 'phase1' for curriculum, etc.)")
    parser.add_argument("--macro-eval-mode", type=str, choices=["micro", "bot"], default="micro",
                       help="MacroController evaluation mode: micro (vs trained agents) or bot (vs evaluation bots)")
    parser.add_argument("--mode", type=str, default=None,
                       help="Force training device: CPU or GPU (case-insensitive). If omitted, auto-selects based on network size and GPU availability.")
    parser.add_argument("--rule-checker", action="store_true",
                       help="Train only on scenarios listed in config/rule_checker/manifest.json (no implicit scenario list).")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug console output (verbose logging)")
    parser.add_argument("--param", action="append", nargs=2, metavar=("KEY", "VALUE"),
                       help="Override config parameter (e.g. n_steps 10240 or model_params.batch_size 2048). Can be repeated.")
    parser.add_argument("--resolution", type=int, choices=[1, 5, 10], default=None,
                       help="Board resolution: 1 (25x21, fast), 5 (44x60x5 = 220x300, mid) or 10 (44x60x10 = 360x312, full). Overrides W40K_BOARD_PATH env var.")

    args = parser.parse_args()

    _RESOLUTION_TO_BOARD = {1: "board/25x21", 5: "board/44x60x5", 10: "board/44x60x10"}
    if args.resolution is not None:
        os.environ["W40K_BOARD_PATH"] = _RESOLUTION_TO_BOARD[args.resolution]
    args.test_only = args.test_only or args.eval

    # Default rewards-config to agent when agent is set (simplifies: --agent X implies rewards X)
    if args.rewards_config is None:
        args.rewards_config = args.agent if args.agent else "default"

    # Apply --param overrides to config loader (affects all subsequent config loads)
    if getattr(args, "param", None):
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
    print(f"Multi-agent: {args.multi_agent}")
    print(f"Orchestrate: {args.orchestrate}")
    print(f"Step logging: {args.step}")
    print(f"Rule-checker mode: {args.rule_checker}")
    print(f"Debug mode: {args.debug}")
    if args.resolution is not None:
        print(f"Resolution: x{args.resolution} ({_RESOLUTION_TO_BOARD[args.resolution]})")
    if args.mode:
        print(f"Device mode: {args.mode}")
    if getattr(args, "param", None):
        print(f"Param overrides: {args.param}")
    if hasattr(args, 'convert_steplog') and args.convert_steplog:
        print(f"Convert steplog: {args.convert_steplog}")
    if hasattr(args, 'replay') and args.replay:
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
        if args.step and not args.agent:
            raise ValueError("--step requires --agent to read step_log_buffer_size from agent training config")
        _require_training_config_phase(config, args.agent, args.training_config)
        step_log_buffer_size: Optional[int] = None
        if args.agent:
            tc = config.load_agent_training_config(args.agent, args.training_config)
            step_log_buffer_size = int(require_key(tc, "step_log_buffer_size"))
        # Initialize global step logger based on --step argument
        global step_logger
        step_logger = StepLogger(
            os.path.join(project_root, "step.log"),
            enabled=args.step,
            buffer_size=cast(int, step_log_buffer_size),
            debug_mode=args.debug,
        )
        
        # Sync configs to frontend automatically
        try:
            subprocess.run(['node', 'scripts/copy-configs.js'], 
                         cwd=project_root, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Config sync failed: {e}")
        
        # Ensure scenario exists ONLY for generic training (no agent specified)
        if not args.agent:
            ensure_scenario()
        
        # Convert existing steplog mode
        if args.convert_steplog:
            success = convert_steplog_to_replay(args.convert_steplog)
            return 0 if success else 1

        # Generate steplog AND convert to replay (one-shot mode)
        if args.replay:
            success = generate_steplog_and_replay(config, args)
            return 0 if success else 1

        # Test integration if requested
        if args.test_integration:
            success = test_scenario_manager_integration()
            return 0 if success else 1
        
        # Multi-agent orchestration mode
        if args.orchestrate:
            # Use training config value when total_episodes is not provided
            total_episodes = args.total_episodes
            if total_episodes is None:
                # Orchestration mode requires agent parameter
                if not args.agent:
                    raise ValueError("--agent parameter required when using --orchestrate without --total-episodes")
                training_config = config.load_agent_training_config(args.agent, args.training_config)
                if "total_episodes" not in training_config:
                    raise KeyError(f"total_episodes missing from {args.agent} training config phase {args.training_config}")
                total_episodes = training_config["total_episodes"]
                print(f"📊 Using total_episodes from config: {total_episodes}")
            else:
                print(f"📊 Using total_episodes from command line: {total_episodes}")
                
            results = start_multi_agent_orchestration(
                config=config,
                total_episodes=total_episodes,
                training_config_name=args.training_config,
                rewards_config_name=args.rewards_config,
                max_concurrent=args.max_concurrent,
                training_phase=args.training_phase
            )
            return 0 if results else 1

        # Test-only mode - check BEFORE training
        elif args.test_only:
            if not args.agent:
                raise ValueError("--agent parameter required for --test-only mode")

            if args.agent == "MacroController":
                if args.scenario in ("all", "self", "bot"):
                    raise ValueError("MacroController test-only does not support scenario rotation modes")

                models_root = config.get_models_root()
                model_path = build_agent_model_path(models_root, args.agent)
                if not os.path.exists(model_path):
                    print(f"❌ Model not found: {model_path}")
                    return 1
                model = MaskablePPO.load(model_path)

                training_config = config.load_agent_training_config(args.agent, args.training_config)
                macro_player = require_key(training_config, "macro_player")
                episodes_per_bot = args.test_episodes if args.test_episodes else require_key(training_config, "eval_episodes")

                if args.macro_eval_mode == "bot":
                    from ai.evaluation_bots import RandomBot, GreedyBot, DefensiveBot
                    bots = {
                        "random": RandomBot(),
                        "greedy": GreedyBot(randomness=0.15),
                        "defensive": DefensiveBot(randomness=0.15)
                    }
                    results = {}
                    total_episodes = episodes_per_bot * len(bots)
                    progress_state = {
                        "completed": 0,
                        "total": total_episodes,
                        "start_time": time.time()
                    }
                    print("\n" + "="*80)
                    print("🎯 RUNNING BOT EVALUATION")
                    print(f"Episodes per bot: {episodes_per_bot} (Total: {total_episodes})")
                    print("="*80)
                    for bot_name, bot in bots.items():
                        env = _build_macro_eval_env(
                            config,
                            args.training_config,
                            args.rewards_config,
                            agent_key=args.agent,
                            scenario_override=args.scenario,
                            debug_mode=args.debug,
                            bot=bot
                        )
                        if step_logger and step_logger.enabled:
                            step_logger.current_bot_name = bot_name
                        wins, losses, draws = _evaluate_macro_model(
                            model,
                            env,
                            episodes_per_bot,
                            macro_player,
                            deterministic=True,
                            progress_state=progress_state,
                            label=f"vs {bot_name.capitalize()}Bot [macro]"
                        )
                        results[bot_name] = wins / max(1, (wins + losses + draws))
                        results[f"{bot_name}_wins"] = wins
                        results[f"{bot_name}_losses"] = losses
                        results[f"{bot_name}_draws"] = draws
                    combined = (results["random"] + results["greedy"] + results["defensive"]) / 3
                    results["combined"] = combined
                    sys.stdout.write("\n")

                    print("\n" + "="*80)
                    print("📊 BOT EVALUATION RESULTS")
                    print("="*80)
                    for bot_name in bots:
                        wr = results[bot_name]
                        print(f"vs {bot_name:20s}: {wr:.2f} (W:{results[f'{bot_name}_wins']} L:{results[f'{bot_name}_losses']} D:{results[f'{bot_name}_draws']})")
                    print(f"\nCombined Score:   {results['combined']:.2f}")
                    print("="*80 + "\n")
                    return 0

                env = _build_macro_eval_env(
                    config,
                    args.training_config,
                    args.rewards_config,
                    agent_key=args.agent,
                    scenario_override=args.scenario,
                    debug_mode=args.debug,
                    bot=None
                )
                progress_state = {
                    "completed": 0,
                    "total": episodes_per_bot,
                    "start_time": time.time()
                }
                wins, losses, draws = _evaluate_macro_model(
                    model,
                    env,
                    episodes_per_bot,
                    macro_player,
                    deterministic=True,
                    progress_state=progress_state,
                    label="macro-vs-micro"
                )
                sys.stdout.write("\n")
                print("\n" + "="*80)
                print("📊 MACRO vs MICRO RESULTS")
                print("="*80)
                total = wins + losses + draws
                print(f"W:{wins} L:{losses} D:{draws} (Total: {total})")
                print("="*80 + "\n")
                return 0
            
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
            if args.rule_checker:
                eval_scenario_list_override = _load_rule_checker_scenarios(project_root)
                scenario_file = eval_scenario_list_override[0]
                print(
                    f"📋 Rule-checker test-only mode: {len(eval_scenario_list_override)} scenario(s) from manifest"
                )
                print(f"📋 Using first rule-checker scenario for env init: {os.path.basename(scenario_file)}")
            else:
                # Test-only mode must evaluate on holdout scenarios only.
                if args.scenario == "bot":
                    raise ValueError(
                        "--scenario bot is not allowed in --test-only mode. "
                        "Use holdout scenarios for evaluation."
                    )
                holdout_scenarios = get_scenario_list_for_phase(
                    cfg,
                    args.agent,
                    args.training_config,
                    scenario_type="holdout",
                )
                if not holdout_scenarios:
                    raise FileNotFoundError(
                        f"No holdout scenarios found for agent '{args.agent}' "
                        f"and phase '{args.training_config}'"
                    )
                scenario_file = holdout_scenarios[0]
                print(f"📋 Using holdout scenario: {os.path.basename(scenario_file)}")
            
            # CRITICAL FIX: Use rewards_config for controlled_agent (includes phase suffix)
            effective_agent_key = args.rewards_config if args.rewards_config else args.agent

            base_env = W40KEngine(
                rewards_config=args.rewards_config,
                training_config_name=args.training_config,
                controlled_agent=effective_agent_key,
                active_agents=None,
                scenario_file=scenario_file,
                unit_registry=unit_registry,
                quiet=True,
                gym_training_mode=True,
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
            
            print("\n" + "="*80)
            print("🎯 RUNNING BOT EVALUATION")
            print(f"Episodes per bot: {episodes_per_bot} (Total: {episodes_per_bot * 3})")
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
            )
            
            # Fiabilité stricte, miroir de `_apply_eval_results` (training_callbacks) : un épisode
            # planté est retiré du dénominateur par `_get_result_with_timeout`, donc publier un
            # score ici reviendrait à mesurer sur un échantillon tronqué SANS le signaler. Un crash
            # moteur n'est pas une défaite de l'agent : il n'a pas à être compté, il a à faire
            # échouer la mesure.
            total_failed_episodes = int(require_key(results, "total_failed_episodes"))
            eval_duration_seconds = float(require_key(results, "eval_duration_seconds"))
            if total_failed_episodes > 0:
                raise RuntimeError(
                    "Bot evaluation failed episodes detected: "
                    f"failed_episodes={total_failed_episodes}, "
                    f"duration_seconds={eval_duration_seconds:.1f}. "
                    "Evaluation stops immediately to enforce strict evaluation reliability."
                )

            scenario_scores = require_key(results, "scenario_scores")
            if not isinstance(scenario_scores, dict) or not scenario_scores:
                raise ValueError("eval-only requires non-empty scenario_scores in evaluation results")

            bot_eval_weights = require_key(require_key(training_config, "callback_params"), "bot_eval_weights")
            bot_scores = {bn: float(require_key(results, bn)) for bn in bot_eval_weights}
            worst_bot_name, worst_bot_score = min(bot_scores.items(), key=lambda item: item[1])

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
            for bot_name in sorted(results.keys()):
                if bot_name.endswith(('_wins', '_losses', '_draws', '_episodes')) or bot_name in ('combined', 'worst_bot_score', 'worst_bot_name', 'eval_reliable', 'eval_duration_seconds', 'total_failed_episodes'):
                    continue
                if isinstance(results[bot_name], (int, float)) and f'{bot_name}_wins' in results:
                    wr = results[bot_name]
                    print(f"  vs {bot_name:20s}: {wr:.2f} (W:{results[f'{bot_name}_wins']} L:{results[f'{bot_name}_losses']} D:{results[f'{bot_name}_draws']})")
            print(f"Combined Score: {float(require_key(results, 'combined')):.4f}")
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
        elif args.agent:
            if args.rule_checker and args.agent == "MacroController":
                raise ValueError("--rule-checker is not supported for MacroController")

            if args.agent == "MacroController":
                if args.scenario in ("self", "bot"):
                    raise ValueError("MacroController supports --scenario all, but not self/bot modes")

                model, env, training_config, model_path = cast(Tuple[Any, Any, Any, Any], create_macro_controller_model(
                    config,
                    args.training_config,
                    args.rewards_config,
                    agent_key=args.agent,
                    new_model=args.new,
                    append_training=args.append,
                    scenario_override=args.scenario,
                    debug_mode=args.debug,
                    device_mode=args.mode
                ))

                # MacroController n'emprunte pas la rotation de scenarios : le budget par
                # tour est releve sur son propre moteur, deja construit et reset, pour
                # rester la MEME valeur que celle qui tronquera les episodes.
                training_config["_turn_step_limit"] = env.unwrapped.get_turn_step_limit()

                callbacks = setup_callbacks(
                    config, model_path, training_config, args.training_config,
                    agent=args.agent, rewards_config_name=args.rewards_config
                )

                success = train_model(
                    model,
                    training_config,
                    callbacks,
                    model_path,
                    args.training_config,
                    args.rewards_config,
                    controlled_agent=args.rewards_config
                )

                if success:
                    if args.test_episodes > 0:
                        test_trained_model(model, args.test_episodes, args.training_config, debug_mode=args.debug)
                    else:
                        print("📊 Skipping testing (--test-episodes 0)")
                    return 0
                return 1

            if args.rule_checker:
                scenario_list = _load_rule_checker_scenarios(project_root)
                print(f"🧪 Rule-checker mode: {len(scenario_list)} scenario(s) from config/rule_checker/manifest.json")
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

                success, model, env = cast(Tuple[Any, Any, Any], train_with_scenario_rotation(
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
                ))
                if success and args.test_episodes > 0:
                    test_trained_model(
                        model,
                        args.test_episodes,
                        args.training_config,
                        args.agent,
                        args.rewards_config,
                        debug_mode=args.debug
                    )
                return 0 if success else 1

            # Curriculum mode: --scenario phaseX
            if args.scenario and args.scenario.startswith("phase"):
                training_config = config.load_agent_training_config(args.agent, args.training_config)
                curriculum_cfg = training_config.get("curriculum")
                if curriculum_cfg is None:
                    raise KeyError(
                        f"--scenario {args.scenario} requires a curriculum block in "
                        f"{args.agent}/{args.training_config} training config"
                    )

                phase_order = require_key(curriculum_cfg, "phase_order")
                if not isinstance(phase_order, list) or not phase_order:
                    raise ValueError("curriculum.phase_order must be a non-empty list")
                if args.scenario not in phase_order:
                    raise ValueError(
                        f"Unknown curriculum phase '{args.scenario}'. Expected one of: {phase_order}"
                    )

                if args.scenario == phase_order[0]:
                    print(f"🎓 Curriculum mode enabled from {args.scenario} ({len(phase_order)} phases)")
                    success, model, env = train_with_curriculum(
                        config=config,
                        agent_key=args.agent,
                        training_config_name=args.training_config,
                        rewards_config_name=args.rewards_config,
                        start_phase=args.scenario,
                        new_model=args.new,
                        append_training=args.append,
                        debug_mode=args.debug,
                        device_mode=args.mode
                    )
                    if success and args.test_episodes > 0:
                        test_trained_model(
                            model,
                            args.test_episodes,
                            args.training_config,
                            args.agent,
                            args.rewards_config,
                            debug_mode=args.debug
                        )
                    return 0 if success else 1

                print(f"🎯 Single phase mode: {args.scenario}")
                phase_scenarios = _get_phase_scenarios(config, args.agent, args.scenario)
                curriculum_phases = require_key(curriculum_cfg, "phases")
                phase_cfg = require_key(curriculum_phases, args.scenario)
                total_episodes = int(require_key(phase_cfg, "max_episodes_in_phase"))

                success, model, env = cast(Tuple[Any, Any, Any], train_with_scenario_rotation(
                    config=config,
                    agent_key=args.agent,
                    training_config_name=args.training_config,
                    rewards_config_name=args.rewards_config,
                    scenario_list=phase_scenarios,
                    total_episodes=total_episodes,
                    new_model=args.new,
                    append_training=args.append,
                    debug_mode=args.debug,
                    use_bots=True,
                    device_mode=args.mode
                ))

                if success and args.test_episodes > 0:
                    test_trained_model(
                        model,
                        args.test_episodes,
                        args.training_config,
                        args.agent,
                        args.rewards_config,
                        debug_mode=args.debug
                    )
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
                success, model, env = cast(Tuple[Any, Any, Any], train_with_scenario_rotation(
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
                ))

                if success and args.test_episodes > 0:
                    test_trained_model(model, args.test_episodes, args.training_config, args.agent, args.rewards_config, debug_mode=args.debug)

                return 0 if success else 1
            
            # Standard single-scenario training (no rotation)
            model, env, training_config, model_path = create_multi_agent_model(
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
            callbacks = setup_callbacks(config, model_path, training_config, args.training_config,
                                      agent=args.agent, rewards_config_name=args.rewards_config)
            
            # Train model
            # CRITICAL: Use rewards_config for controlled_agent (includes phase suffix like "_phase1")
            success = train_model(model, training_config, callbacks, model_path, args.training_config, args.rewards_config, controlled_agent=args.rewards_config)
            
            if success:
                # Only test if episodes > 0
                if args.test_episodes > 0:
                    test_trained_model(model, args.test_episodes, args.training_config, debug_mode=args.debug)
                else:
                    print("📊 Skipping testing (--test-episodes 0)")
                return 0
            else:
                return 1
        
        else:
            # Generic training mode
            # Create/load model
            model, env, training_config, model_path = create_model(
            config, 
            args.training_config,
            args.rewards_config, 
            args.new, 
            args.append,
            args
        )
        
        # Setup callbacks
        callbacks = setup_callbacks(config, model_path, training_config, args.training_config,
                                    rewards_config_name=args.rewards_config)
        
        # Train model
        success = train_model(model, training_config, callbacks, model_path, args.training_config, args.rewards_config, controlled_agent=args.agent)
        
        if success:
            # Only test if episodes > 0
            if args.test_episodes > 0:
                test_trained_model(model, args.test_episodes, args.training_config, args.agent, args.rewards_config, debug_mode=args.debug)
                
                # Save training replay with our unified system
                if hasattr(env, 'replay_logger'):
                    from ai.game_replay_logger import GameReplayIntegration
                    final_reward = 0.0  # Average reward from testing
                    replay_file = GameReplayIntegration.save_episode_replay(
                        env, 
                        episode_reward=final_reward, 
                        output_dir="ai/event_log", 
                        is_best=False
                    )
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

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
