#!/usr/bin/env python3
"""
ai/training_utils.py - Training utility functions

Contains:
- check_gpu_availability: Check and display GPU availability
- setup_imports: Setup system path imports for project
- make_training_env: Create training environment with proper configuration
- get_agent_scenario_file: Get scenario file path for agent-specific training
- get_scenario_list_for_phase: Get all available scenarios for a training phase

Extracted from ai/train.py during refactoring (2025-01-21)
"""

import os
import sys
import glob
import time
import torch
import torch.nn as nn
import gymnasium as gym
from typing import Optional, List, Tuple
from stable_baselines3.common.monitor import Monitor
from sb3_contrib.common.wrappers import ActionMasker
from ai.env_wrappers import SelfPlayWrapper, BotControlledEnv
from shared.data_validation import require_key, require_positive_int

__all__ = [
    'check_gpu_availability',
    'benchmark_device_speed',
    'setup_imports',
    'make_training_env',

    'get_agent_scenario_file',
    'get_scenario_list_for_phase',
    'describe_expected_bot_self_scenario_files',
]


def check_gpu_availability():
    """Check and display GPU availability for training."""
    print("\n🔍 GPU AVAILABILITY CHECK")
    print("=" * 30)

    if torch.cuda.is_available():
        device_count = torch.cuda.device_count()
        current_device = torch.cuda.current_device()
        device_name = torch.cuda.get_device_name(current_device)
        memory_gb = torch.cuda.get_device_properties(current_device).total_memory / 1024**3

        print(f"✅ CUDA Available: YES")
        print(f"📊 GPU Devices: {device_count}")
        print(f"🎯 Current Device: {current_device} ({device_name})")
        print(f"💾 GPU Memory: {memory_gb:.1f} GB")
        print(f"🚀 PyTorch CUDA Version: {getattr(torch, 'version').cuda}")

        # Force PyTorch to use GPU for Stable-Baselines3
        torch.cuda.set_device(current_device)

        return True
    else:
        print(f"❌ CUDA Available: NO")
        print(f"⚠️  Training will use CPU (much slower)")
        print(f"💡 Install CUDA-enabled PyTorch: pip install torch --index-url https://download.pytorch.org/whl/cu118")

        return False


def benchmark_device_speed(obs_size: int, net_arch: List[int], batch_size: int = 2048,
                           n_warmup: int = 5, n_iters: int = 30) -> Optional[Tuple[str, bool]]:
    """
    Run a quick benchmark to determine whether CPU or GPU is faster for the given
    network architecture. Simulates PPO forward pass with typical batch size.

    Args:
        obs_size: Observation space dimension.
        net_arch: List of hidden layer sizes (e.g. [512, 512]).
        batch_size: Batch size for benchmark (typical PPO batch).
        n_warmup: Warmup iterations to avoid CUDA init skew.
        n_iters: Iterations to average for timing.

    Returns:
        ("cuda", True) or ("cpu", False) if benchmark succeeds, None on failure.
    """
    if not torch.cuda.is_available():
        return ("cpu", False)

    arch = net_arch if isinstance(net_arch, list) else [512]
    layers = []
    prev = obs_size
    for h in arch:
        layers.append(nn.Linear(prev, h))
        layers.append(nn.ReLU())
        prev = h
    layers.append(nn.Linear(prev, 64))  # action head
    net = nn.Sequential(*layers)

    def run_on_device(device: str) -> float:
        d = torch.device(device)
        m = net.to(d)
        x = torch.randn(batch_size, obs_size, device=d)
        for _ in range(n_warmup):
            _ = m(x)
        if d.type == "cuda":
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(n_iters):
            _ = m(x)
        if d.type == "cuda":
            torch.cuda.synchronize()
        return time.perf_counter() - t0

    try:
        t_cpu = run_on_device("cpu")
        t_gpu = run_on_device("cuda")
        use_gpu = t_gpu < t_cpu
        winner = "GPU" if use_gpu else "CPU"
        ratio = (t_cpu / t_gpu) if use_gpu else (t_gpu / t_cpu)
        print(f"📊 Device benchmark: {winner} faster ({ratio:.1f}x) | CPU={t_cpu*1000:.0f}ms GPU={t_gpu*1000:.0f}ms")
        return ("cuda", True) if use_gpu else ("cpu", False)
    except Exception as e:
        print(f"⚠️ Device benchmark failed ({e}), falling back to heuristic")
        return None


def setup_imports():
    """
    Setup import paths and return required modules.
    Returns W40KEngine and register_environment function.
    """
    try:
        # tour_de_jeu.md COMPLIANCE: Use compliant engine with gym interface
        from engine.w40k_core import W40KEngine

        # Compatibility function for training system
        def register_environment():
            """No registration needed for direct engine usage"""
            pass

        return W40KEngine, register_environment
    except ImportError as e:
        raise ImportError(f"w40k_engine import failed: {e}")

# Argument `self_play_*` de `BotControlledEnv` -> (cle lue dans `opponent_mix`, conversion).
# Table UNIQUE : les deux etats (actif / inactif) en derivent, donc une cle ajoutee ici ne peut
# pas etre oubliee d'un cote.
_SELF_PLAY_ARGS = (
    ("self_play_ratio_start", "self_play_ratio_start", float),
    ("self_play_ratio_end", "self_play_ratio_end", float),
    ("self_play_total_episodes", "total_episodes", int),
    ("self_play_warmup_episodes", "warmup_episodes", int),
    ("self_play_n_envs", "n_envs", int),
    ("self_play_snapshot_device", "snapshot_device", str),
    ("self_play_deterministic", "deterministic", bool),
)


def self_play_is_enabled(opponent_mix_config) -> bool:
    """`opponent_mix` demande-t-il un adversaire fige ? Absent = non, sans erreur."""
    return opponent_mix_config is not None and opponent_mix_config.get("enabled") is True


def build_self_play_kwargs(opponent_mix_config, env_rank: int = 0) -> dict:
    """Arguments `self_play_*` de `BotControlledEnv`, derives d'`opponent_mix`. SOURCE UNIQUE.

    Ce cablage etait recopie a la main sur chaque site de construction : les branches mono-env
    l'OMETTAIENT purement et simplement, donc un `opponent_mix.enabled: true` y etait ignore EN
    SILENCE (aucun self-play, aucun message), et la branche qui le portait a rate l'ajout de
    `self_play_n_envs` (V11 §0.57). Un seul point de verite supprime les deux defauts.

    `env_rank` : `opponent_mix.pool` est une LISTE PONDEREE d'adversaires figes, et la
    composition du pool est realisee par la repartition des ENVIRONNEMENTS, pas par un tirage
    par episode. Cet environnement-ci recoit donc UN membre, resolu ici, qu'il chargera une
    fois pour toutes (`self_play_snapshot_frozen`). Tirer par episode aurait impose de garder
    les treize membres du plus gros pool vivants dans CHACUN des quarante-huit processus.
    """
    enabled = self_play_is_enabled(opponent_mix_config)
    kwargs: dict = {"self_play_opponent_enabled": enabled}
    for arg, key, cast in _SELF_PLAY_ARGS:
        kwargs[arg] = cast(opponent_mix_config[key]) if enabled else (False if cast is bool else None)
    # Les adversaires d'`opponent_mix` sont TOUJOURS figes depuis le curriculum : plus aucun
    # instantane du modele courant n'est republie pendant le run, donc rien a rafraichir.
    kwargs["self_play_snapshot_frozen"] = enabled
    kwargs["self_play_snapshot_refresh_episodes"] = None
    if not enabled:
        kwargs["self_play_snapshot_path"] = None
        return kwargs

    from ai.curriculum import assign_pool_members_to_envs

    pool = require_key(opponent_mix_config, "pool")
    n_envs = require_positive_int(opponent_mix_config.get("n_envs"), "opponent_mix.n_envs")
    if not isinstance(env_rank, int) or isinstance(env_rank, bool) or not (0 <= env_rank < n_envs):
        raise ValueError(
            f"build_self_play_kwargs: env_rank doit etre dans [0,{n_envs}[ (got {env_rank!r})"
        )
    member = assign_pool_members_to_envs(pool, n_envs)[env_rank]
    kwargs["self_play_snapshot_path"] = str(require_key(member, "path"))
    kwargs["self_play_snapshot_label"] = str(require_key(member, "label"))
    ramp_end = opponent_mix_config.get("ramp_end_episodes")
    kwargs["self_play_ramp_end_episodes"] = int(ramp_end) if ramp_end is not None else None
    return kwargs


def make_training_env(rank, scenario_file, rewards_config_name, training_config_name,
                     controlled_agent_key, unit_registry, step_logger_enabled=False,
                     scenario_files=None, debug_mode=False, use_bots=False, training_bots=None,
                     agent_seat_mode=None, agent_seat_p2_ratio=None,
                     global_seed=None, opponent_mix_config=None,
                     n_envs=None, episode_start_index=0,
                     vec_normalize_enabled=False, vec_normalize_eval_enabled=False,
                     deploy_active_ratio_start=None):
    """
    Factory function to create a single W40KEngine instance for vectorization.

    Args:
        rank: Environment index (0, 1, 2, 3, ...)
        scenario_file: Path to scenario JSON file (used if scenario_files not provided)
        rewards_config_name: Name of rewards configuration
        training_config_name: Name of training configuration
        controlled_agent_key: Agent key for this environment
        unit_registry: Shared UnitRegistry instance
        step_logger_enabled: Whether step logging is enabled (disable for vectorized envs)
        scenario_files: List of scenario files for random selection per episode
        debug_mode: Enable debug mode
        use_bots: If True, wrap with BotControlledEnv instead of SelfPlayWrapper
        training_bots: List of bot instances for BotControlledEnv (required if use_bots=True)
        agent_seat_p2_ratio: Part des episodes ou l'agent joue SECOND quand
            `agent_seat_mode='random'`. Obligatoire dans la config d'entrainement (cf.
            `ai.train.build_training_opponents`), et propage jusqu'ici sans reinterpretation :
            l'evaluation, qui n'emprunte pas ce chemin, garde son tirage equitable.
        n_envs: Nombre d'environnements REELLEMENT ouverts (deja resolu par
            `_resolve_n_envs_for_step_logging`). Obligatoire : c'est le denominateur des rampes
            par-episode, moteur ET self-play (V11 §0.57).
        episode_start_index: Episodes deja joues PAR CET environnement lors d'un run precedent
            (reprise). Il n'est passe QU'AU MOTEUR : la rampe de deploiement est une COMPETENCE
            ACQUISE, elle reprend ou elle en etait. Le wrapper, lui, part de zero — la rampe de
            self-play appartient au REGIME du run qu'on lance, et son introduction progressive
            n'a de sens que depuis le debut de ce run. Cf. ai/run_state.py.
        deploy_active_ratio_start: Depart de la rampe de deploiement decide par le PARENT, ou
            None pour laisser le JSON faire foi. Une etape de curriculum reprise a chaud le fige
            a sa valeur terminale ; ce figeage vit dans le parent (decoration du loader) et NE
            FRANCHIT PAS la frontiere `forkserver`/`spawn` d'un worker, qui reimporte tout et
            relit le JSON. Le passer en argument est donc la seule facon qu'il atteigne le
            moteur — meme raison que `n_envs` et `episode_start_index` ci-dessus.

    Returns:
        Callable that creates and returns a wrapped environment instance
    """
    if not isinstance(n_envs, int) or isinstance(n_envs, bool) or n_envs <= 0:
        raise ValueError(
            f"make_training_env requiert n_envs (nombre d'environnements REELLEMENT ouverts), "
            f"entier > 0 : c'est le denominateur des rampes par-episode (got {n_envs!r})"
        )
    # V11 §10.4 : un worker vectorise ne peut PAS recevoir de frozen_model (pas de
    # partage inter-processus) ; `SelfPlayWrapper(frozen_model=None)` y jouait donc des
    # actions aleatoires en permanence, silencieusement. Le self-play vectorise passe par
    # BotControlledEnv + opponent_mix (snapshot relu sur disque), pas par ce wrapper.
    # Verifie AVANT de forker les workers, pas dans _init.
    if not (use_bots and training_bots):
        raise ValueError(
            "make_training_env requiert use_bots=True et training_bots non vide : "
            "un environnement vectorise n'a pas d'adversaire de self-play utilisable "
            "(V11 §10.4). Configurer 'bot_training' dans la config d'entrainement."
        )

    def _init():
        # Import environment (inside function to avoid import issues)
        from engine.w40k_core import W40KEngine
        if debug_mode:
            try:
                debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                    f.write(f"WORKER_INIT_START env_rank={int(rank)} scenario_file={scenario_file}\n")
            except (OSError, IOError):
                pass

        # Create base environment with scenario_files for random selection
        base_env = W40KEngine(
            rewards_config=rewards_config_name,
            training_config_name=training_config_name,
            controlled_agent=controlled_agent_key,
            active_agents=None,
            scenario_file=scenario_file,
            scenario_files=scenario_files,  # NEW: Pass list for random selection
            unit_registry=unit_registry,
            quiet=True,
            gym_training_mode=True,
            debug_mode=debug_mode,
            # n_envs REELLEMENT ouverts : il prime sur la valeur declaree du profil, seule facon
            # que les rampes par-episode du moteur et celle du self-play partagent le meme
            # denominateur (V11 §0.57).
            training_n_envs=n_envs,
            training_episode_start_index=episode_start_index,
            training_deploy_active_ratio_start=deploy_active_ratio_start,
        )
        
        # ✓ CHANGE 9: Removed seed() call - W40KEngine uses reset(seed=...) instead
        # Seeding will happen naturally during first reset() call
        
        # Disable step logger for parallel envs to avoid file conflicts
        if not step_logger_enabled:
            base_env.step_logger = None  # ✓ CHANGE 2: Prevent log conflicts
        
        # Wrap with ActionMasker for MaskablePPO
        def mask_fn(env):
            return env.get_action_mask()
        
        masked_env = ActionMasker(base_env, mask_fn)

        # Bot training (le self-play vectorise passe par opponent_mix, cf. garde ci-dessus)
        if agent_seat_mode is None:
            raise KeyError("agent_seat_mode is required when use_bots=True")
        wrapped_env = BotControlledEnv(
            masked_env,
            bots=training_bots,
            unit_registry=unit_registry,
            agent_seat_mode=agent_seat_mode,
            agent_seat_p2_ratio=agent_seat_p2_ratio,
            global_seed=global_seed,
            env_rank=rank,
            self_play_vec_normalize_enabled=vec_normalize_enabled,
            self_play_vec_normalize_eval_enabled=vec_normalize_eval_enabled,
            **build_self_play_kwargs(opponent_mix_config, env_rank=rank),
        )

        # Wrap with Monitor for episode statistics
        monitored_env = Monitor(wrapped_env)
        if debug_mode:
            try:
                debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                    f.write(f"WORKER_INIT_END env_rank={int(rank)}\n")
            except (OSError, IOError):
                pass
        return monitored_env
    
    return _init



def describe_expected_bot_self_scenario_files(is_self_play: bool) -> str:
    """
    Texte d'aide pour erreurs CLI : motifs et dossiers alignés sur get_scenario_list_for_phase
    lorsque scenario_type vaut 'bot' ou 'self'.
    """
    kind = "self" if is_self_play else "bot"
    return (
        f"patterns: scenario_{kind}*.json, scenario_*_{kind}*.json, *_scenario_{kind}*.json; "
        "search: scenarios/training/, holdout_regular/, holdout_hard/ (chaque dossier présent), "
        "sinon la racine scenarios/"
    )


def _gather_scenario_files_in_dir(
    search_dir: str,
    scenario_type: Optional[str],
    training_config_name: str,
) -> List[str]:
    """Collecte les chemins JSON pour un dossier de scénarios (logique unique pour glob)."""
    search_dir_name = os.path.basename(search_dir)
    if scenario_type in ("bot", "self"):
        patterns = [
            f"scenario_{scenario_type}*.json",
            f"scenario_*_{scenario_type}*.json",
            f"*_scenario_{scenario_type}*.json",
        ]
    else:
        patterns = [
            f"scenario_{training_config_name}.json",
            f"scenario_{training_config_name}-*.json",
            f"{training_config_name}_scenario_*.json",
        ]
        if search_dir_name in {"training", "holdout_regular", "holdout_hard"}:
            patterns.append(f"{search_dir_name}_scenario_*.json")

    matches: List[str] = []
    for pattern in patterns:
        matches.extend(glob.glob(os.path.join(search_dir, pattern)))

    if not matches:
        matches = glob.glob(os.path.join(search_dir, "scenario_*.json"))
        matches.extend(glob.glob(os.path.join(search_dir, "*_scenario_*.json")))

    return matches


def get_scenario_list_for_phase(config, agent_key, training_config_name, scenario_type=None):
    """
    Get all available scenarios for a training phase.

    Args:
        config: ConfigLoader instance
        agent_key: Agent identifier (e.g., 'SpaceMarine_Infantry_Troop_RangedSwarm')
        training_config_name: Phase name (e.g., 'phase1', 'phase2')
        scenario_type: Optional filter for specific scenario type (e.g., 'bot', 'self', '1')

    Returns:
        List of scenario file paths

    Bot / self (entraînement contre bots ou self-play) :
        Cherche UNIQUEMENT dans scenarios/training/ (ou la racine scenarios/ si training/
        n'existe pas). Les dossiers holdout_regular/ et holdout_hard/ sont exclus : ce sont
        les jeux de test. Si aucun scénario n'est trouvé, l'appelant lève une erreur
        explicite — pas de repli sur le holdout.
    """
    scenarios: List[str] = []
    if not agent_key:
        return scenarios

    scenarios_root = os.path.join(config.config_dir, "agents", agent_key, "scenarios")
    if not os.path.isdir(scenarios_root):
        import re as _re
        base_key = _re.sub(r"_P\d+$", "", agent_key)
        if base_key != agent_key:
            scenarios_root = os.path.join(config.config_dir, "agents", base_key, "scenarios")
    if not os.path.isdir(scenarios_root):
        return scenarios

    training_dir = os.path.join(scenarios_root, "training")
    holdout_regular_dir = os.path.join(scenarios_root, "holdout_regular")
    holdout_hard_dir = os.path.join(scenarios_root, "holdout_hard")
    has_training_dir = os.path.isdir(training_dir)
    has_holdout_regular_dir = os.path.isdir(holdout_regular_dir)
    has_holdout_hard_dir = os.path.isdir(holdout_hard_dir)

    if scenario_type == "holdout":
        search_dirs: List[str] = []
        if has_holdout_regular_dir:
            search_dirs.append(holdout_regular_dir)
        if has_holdout_hard_dir:
            search_dirs.append(holdout_hard_dir)
    elif scenario_type == "training":
        search_dirs = [training_dir] if has_training_dir else []
    elif scenario_type in ("bot", "self"):
        # Modes d'ENTRAÎNEMENT : jamais les dossiers holdout_* — ce sont les jeux de test
        # (mesure du critère §10.6). Les balayer revient à entraîner sur le jeu de test,
        # silencieusement. Si training/ n'existe pas, la racine sert de dossier de scénarios.
        search_dirs = [training_dir] if has_training_dir else [scenarios_root]
    else:
        # Default training behavior:
        # - if training/ exists, use it exclusively
        # - otherwise, use scenarios root.
        search_dirs = [training_dir] if has_training_dir else [scenarios_root]

    for search_dir in search_dirs:
        scenarios.extend(
            _gather_scenario_files_in_dir(search_dir, scenario_type, training_config_name)
        )

    # Filter by explicit subtype marker (e.g. "1", "2", "bot-1"), if provided.
    if scenario_type and scenario_type not in ("bot", "self", "training", "holdout"):
        filtered: List[str] = []
        for scenario_path in scenarios:
            basename = os.path.basename(scenario_path)
            if f"-{scenario_type}" in basename:
                filtered.append(scenario_path)
        scenarios = filtered

    # Deduplicate + deterministic ordering
    return sorted(set(scenarios))

def get_agent_scenario_file(config, agent_key, training_config_name, scenario_override=None):
    """Get scenario file path for agent-specific training.

    Args:
        config: ConfigLoader instance
        agent_key: Agent identifier (e.g., 'SpaceMarine_Infantry_Troop_RangedSwarm')
        training_config_name: Phase name (e.g., 'phase1', 'phase2')
        scenario_override: Optional specific scenario name (e.g., 'phase2-3')

    Returns:
        Path to scenario file

    Raises:
        FileNotFoundError: If no valid scenario file found
    """
    scenarios_root = os.path.join(config.config_dir, "agents", agent_key, "scenarios")
    training_dir = os.path.join(scenarios_root, "training")
    has_training_dir = os.path.isdir(training_dir)

    # Search order for training: prefer training/ when it exists.
    search_dirs = [training_dir, scenarios_root] if has_training_dir else [scenarios_root]

    # If specific scenario requested, accept explicit file path first.
    if scenario_override and scenario_override != "all":
        if isinstance(scenario_override, str) and os.path.isfile(scenario_override):
            return scenario_override
        for search_dir in search_dirs:
            explicit_candidates = [
                os.path.join(search_dir, f"scenario_{scenario_override}.json"),
                os.path.join(search_dir, f"scenario_{training_config_name}-{scenario_override}.json"),
                os.path.join(search_dir, f"{training_config_name}_scenario_{scenario_override}.json"),
            ]
            found_explicit = sorted([p for p in explicit_candidates if os.path.isfile(p)])
            if len(found_explicit) == 1:
                return found_explicit[0]
            if len(found_explicit) > 1:
                raise FileNotFoundError(
                    f"Ambiguous scenario_override '{scenario_override}' for agent '{agent_key}' "
                    f"and phase '{training_config_name}'. Candidates: {found_explicit}. "
                    f"Please specify an exact scenario file name."
                )

    exact_candidates: List[str] = []
    for search_dir in search_dirs:
        exact_candidates.append(os.path.join(search_dir, f"scenario_{training_config_name}.json"))
    exact_matches = sorted([p for p in exact_candidates if os.path.isfile(p)])
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise FileNotFoundError(
            f"Ambiguous exact scenario for agent '{agent_key}' and phase '{training_config_name}': "
            f"{exact_matches}. Please keep only one exact phase scenario."
        )

    # Try variants for this phase (training-bot1, holdout-hard-bot-1, etc.).
    matching_files: List[str] = []
    for search_dir in search_dirs:
        matching_files.extend(sorted(glob.glob(
            os.path.join(search_dir, f"scenario_{training_config_name}-*.json")
        )))
        matching_files.extend(sorted(glob.glob(
            os.path.join(search_dir, f"{training_config_name}_scenario_*.json")
        )))
    matching_files = sorted(set(matching_files))

    if len(matching_files) == 1:
        return matching_files[0]
    elif len(matching_files) > 1:
        variant_names = [os.path.basename(f) for f in matching_files]
        raise FileNotFoundError(
            f"Multiple scenario variants found for agent '{agent_key}' and phase '{training_config_name}': "
            f"{variant_names}. You must specify --scenario with an explicit variant name."
        )

    # No valid scenario found
    #
    # Le message nomme AUSSI les trois mots-clés de rotation. Sans eux il est trompeur : il
    # décrit un problème de NOMMAGE DE FICHIER alors que la cause la plus fréquente est un
    # `--scenario <mot inconnu>`, qui fait retomber l'appelant sur la voie « scénario unique »
    # au lieu de la rotation. Diagnostic vécu le 2026-08-05 : `--scenario training` a été lu
    # comme « les scénarios du dossier training/ », et l'erreur a fait conclure à un scénario
    # d'agent mal nommé — alors que `--scenario bot` fonctionnait.
    scenario_dirs = ", ".join(os.path.basename(d) or d for d in search_dirs)
    raise FileNotFoundError(
        f"No scenario file found for agent '{agent_key}' with phase '{training_config_name}'"
        + (f" (searched in: {scenario_dirs})" if scenario_dirs else "")
        + ".\n"
        f"  - Pour faire tourner TOUS les scenarios d'entrainement de l'agent, `--scenario` "
        f"attend un des mots-cles de ROTATION : 'bot', 'self' ou 'all' "
        f"(les dossiers holdout_* en sont exclus : ce sont les jeux de test).\n"
        f"  - Pour UN scenario precis, `--scenario` attend son nom ou son chemin, avec l'un de "
        f"ces nommages : 'scenario_<nom>.json', 'scenario_{training_config_name}.json', "
        f"'scenario_{training_config_name}-*.json', ou '{training_config_name}_scenario_*.json'."
    )
