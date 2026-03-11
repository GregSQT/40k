# Plan de refactoring : Eval intégré + robustesse maximale (v21)

Version corrigée de PLAN01 : corrections pour application sans erreur par un prompt.
Intègre : seeds déterministes (hashlib), Worker initializer (charge modèle une fois par worker).

## Objectifs

1. **Robustesse** : Éliminer les collisions de cache LoS (envs dans le même processus)
2. **Performance** : Paralléliser l'éval sans dégrader la fiabilité
3. **Simplicité** : Un seul point d'entrée (`train.py`), pas de script eval séparé
4. **Reproductibilité** : Seeds explicites pour comparaison avant/après

---

## État actuel

- `wall_hexes` déjà dans la clé du cache (shooting_handlers.py)
- `_cache_instance_id = id(self)` dans w40k_core.py (risque de réutilisation après GC)
- Eval : N envs dans le processus principal, boucle manuelle
- `--test-only` dans train.py fait déjà l'éval standalone

---

## Phase 0 : Prérequis (avant Phase 2)

### 0.1 Contrat de sérialisation

Tout ce qui est passé aux workers **doit être sérialisable** (picklable) :

- `model_path` : str ✓
- `scenario_file` : str ✓
- `bot_name` : str ✓
- `bot_type` : str (ex. `"random"`, `"greedy"`, `"defensive"`) ✓
- `randomness_config` : dict ✓
- `config_params` : dict (training_config_name, rewards_config_name, controlled_agent, vec_normalize_enabled, vec_model_path, etc.) ✓

**Ne pas passer** : instances de bots, objets modèle, UnitRegistry. Le worker instancie tout.

### 0.2 Factorisation de la création d'env

**Fichier** : `ai/bot_evaluation.py`

Extraire une fonction réutilisable pour le mode sérial et les workers :

```python
def _create_eval_env(
    bot_name: str,
    bot_type: str,
    randomness_config: Dict[str, float],
    scenario_file: str,
    training_config_name: str,
    rewards_config_name: str,
    controlled_agent: str,
    base_agent_key: str,
    debug_mode: bool,
) -> BotControlledEnv:
    """Crée un env d'éval. Utilisé en mode sérial et dans les workers."""
    from ai.evaluation_bots import RandomBot, GreedyBot, DefensiveBot
    from ai.training_utils import setup_imports
    from ai.env_wrappers import BotControlledEnv
    from sb3_contrib.common.wrappers import ActionMasker
    from ai.unit_registry import UnitRegistry

    unit_registry = UnitRegistry()
    W40KEngine, _ = setup_imports()

    # CRITICAL: RandomBot() n'accepte pas randomness ; GreedyBot/DefensiveBot oui
    if bot_type == "random":
        bot = RandomBot()
    else:
        bot_class = {"greedy": GreedyBot, "defensive": DefensiveBot}[bot_type]
        bot = bot_class(randomness=randomness_config.get(bot_type, 0.15))

    def mask_fn(env):
        return env.get_action_mask()

    base_env = W40KEngine(
        rewards_config=rewards_config_name,
        training_config_name=training_config_name,
        controlled_agent=controlled_agent,
        active_agents=None,
        scenario_file=scenario_file,
        unit_registry=unit_registry,
        quiet=True,
        gym_training_mode=True,
        debug_mode=debug_mode,
    )
    masked_env = ActionMasker(base_env, mask_fn)
    return BotControlledEnv(masked_env, bot, unit_registry)
```

**Effort** : ~45 lignes | **Risque** : faible

---

## Phase 1 : Quick wins (faible risque, ~30 min)

### 1.1 Alias `--eval` dans train.py

**Fichier** : `ai/train.py`

- Ajouter `parser.add_argument("--eval", action="store_true", help="Alias for --test-only")`
- Au parsing : `args.test_only = args.test_only or args.eval`
- Conserver `--test-only` pour rétrocompatibilité (non breaking)

**Effort** : 5 lignes | **Risque** : nul

### 1.2 ID unique par engine (remplacer id(self))

**Fichier** : `engine/w40k_core.py`

```python
# En tête du module (ajouter import threading si absent)
import threading

_engine_id_counter = 0
_engine_id_lock = threading.Lock()

def _next_engine_id() -> int:
    """Monotonic ID per engine instance. Prevents cache collision when id() is reused after GC."""
    global _engine_id_counter
    with _engine_id_lock:
        _engine_id_counter += 1
        return _engine_id_counter
```

**Emplacement** : Dans `__init__`, à la création de `self.game_state` (ligne ~336), remplacer :
```python
# AVANT
"_cache_instance_id": id(self),

# APRÈS
"_cache_instance_id": _next_engine_id(),
```

**Note** : Il n'existe pas de méthode `_create_initial_game_state()` — le `game_state` est créé directement dans `__init__`.

**Effort** : ~15 lignes | **Risque** : faible

---

## Phase 2 : Eval avec isolation par processus (robustesse + perf)

### Stratégie : ProcessPoolExecutor (pas SubprocVecEnv)

**Pourquoi pas SubprocVecEnv ?**
- SubprocVecEnv.reset() réinitialise tous les envs
- Quand un env termine, on ne peut pas reset un seul worker
- Adapter la boucle eval à cette contrainte est lourd

**Alternative : ProcessPoolExecutor**
- Chaque worker = 1 processus, 1 env, 0 partage de cache
- Chaque worker exécute N épisodes en série, renvoie (wins, losses, draws)
- Pas d'interface VecEnv à modifier
- Même niveau d'isolation que SubprocVecEnv

### 2.0 Démarrage des processus : spawn (pas fork)

**CRITIQUE** : Sous Linux, `multiprocessing` utilise `fork` par défaut. Avec fork, le worker hérite de la mémoire du parent (caches, état PyTorch) → risques de comportements indéterminés.

```python
import multiprocessing as mp
ctx = mp.get_context("spawn")
# Utiliser mp_context=ctx dans ProcessPoolExecutor (voir section 2.6)
```

### 2.1 Worker initializer (charger le modèle une fois par worker)

**Objectif** : Éviter de recharger le modèle à chaque tâche. Avec 3 bots × 4 scénarios = 12 tâches et 4 workers : sans initializer = 12 chargements ; avec initializer = 4 chargements.

**Fichier** : `ai/bot_evaluation.py`

```python
# Variables globales du worker (scope processus)
_worker_model = None
_worker_obs_normalizer = None

def _eval_worker_init(
    model_path: str,
    vec_model_path: Optional[str],
    vec_normalize_enabled: bool,
    vec_eval_enabled: bool,
    training_config_name: str,
    rewards_config_name: str,
    controlled_agent: str,
    base_agent_key: str,
) -> None:
    """Appelé une fois au démarrage de chaque worker. Charge modèle + normalizer."""
    global _worker_model, _worker_obs_normalizer
    from sb3_contrib import MaskablePPO
    _worker_model = MaskablePPO.load(model_path)
    _worker_obs_normalizer = _build_eval_obs_normalizer_for_worker(
        _worker_model, vec_model_path, vec_normalize_enabled, vec_eval_enabled
    )
```

**Mode sérial** : Appeler `_eval_worker_init(*initargs)` dans le processus principal **avant** la boucle des tâches, afin que `_worker_model` et `_worker_obs_normalizer` soient disponibles.

### 2.2 Fonction worker pour l'éval

**Fichier** : `ai/bot_evaluation.py`

```python
def _eval_worker_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """
    Exécuté dans un processus séparé (ou en sérial). Utilise _worker_model et _worker_obs_normalizer
    chargés par _eval_worker_init.

    Args:
        task: dict avec bot_name, bot_type, randomness_config, scenario_file, n_episodes,
              base_seed, scenario_index, config_params

    Returns:
        {"wins": int, "losses": int, "draws": int, "shoot_stats": dict, "bot_name": str, "scenario_name": str,
         "timeout": bool?, "error": str?}
    """
    global _worker_model, _worker_obs_normalizer
    if _worker_model is None:
        raise RuntimeError("Worker not initialized (call _eval_worker_init before tasks)")

    import random
    import numpy as np

    config_params = task["config_params"]
    env = _create_eval_env(
        bot_name=task["bot_name"],
        bot_type=task["bot_type"],
        randomness_config=task["randomness_config"],
        scenario_file=task["scenario_file"],
        **{k: config_params[k] for k in [
            "training_config_name", "rewards_config_name", "controlled_agent",
            "base_agent_key", "debug_mode"
        ] if k in config_params},
    )

    # step_logger : uniquement en mode sérial (non picklable, ne pas ajouter en mode parallèle)
    if config_params.get("step_logger"):
        env.engine.step_logger = config_params["step_logger"]

    wins, losses, draws = 0, 0, 0
    for ep_idx in range(task["n_episodes"]):
        ep_seed = _episode_seed(task["base_seed"], task["bot_name"], task["scenario_index"], ep_idx)
        random.seed(ep_seed)
        np.random.seed(ep_seed)
        obs, info = env.reset(seed=ep_seed)
        done = False
        while not done:
            model_obs = _worker_obs_normalizer(obs) if _worker_obs_normalizer else obs
            model_obs_arr = np.asarray(model_obs, dtype=np.float32)
            if model_obs_arr.ndim == 1:
                model_obs_arr = model_obs_arr.reshape(1, -1)
            action_masks = np.asarray(env.engine.get_action_mask(), dtype=bool)
            if action_masks.ndim == 1:
                action_masks = action_masks.reshape(1, -1)
            action, _ = _worker_model.predict(
                model_obs_arr,
                action_masks=action_masks,
                deterministic=task.get("deterministic", True),
            )
            obs, reward, terminated, truncated, info = env.step(int(action))
            done = bool(terminated or truncated)
        winner = info.get("winner")
        if winner == 1:
            wins += 1
        elif winner == -1:
            draws += 1
        else:
            losses += 1

    shoot_stats = env.get_shoot_stats() if hasattr(env, "get_shoot_stats") else {}
    env.close()
    return {
        "wins": wins, "losses": losses, "draws": draws,
        "shoot_stats": shoot_stats,
        "bot_name": task["bot_name"],
        "scenario_name": task["scenario_name"],
    }
```

- Le worker utilise le modèle pré-chargé par `_eval_worker_init`
- **CRITICAL** : `model.predict` doit recevoir `action_masks` (MaskablePPO)

### 2.3 Seeds déterministes (hashlib, pas hash())

**CRITIQUE** : `hash()` en Python n'est pas déterministe entre exécutions (randomisation au démarrage de l'interpréteur). Utiliser `hashlib.md5`.

```python
import hashlib

def _episode_seed(base_seed: int, bot_name: str, scenario_idx: int, ep_idx: int) -> int:
    """Seed déterministe par (bot, scenario, épisode). Reproductible entre exécutions."""
    key = f"{bot_name}:{scenario_idx}:{ep_idx}"
    h = int(hashlib.md5(key.encode()).hexdigest()[:8], 16) % (2**31)
    return (base_seed + h) % (2**31)
```

### 2.4 VecNormalize / observation normalization

**Problème** : `_build_eval_obs_normalizer` actuel utilise l'env du modèle (training) ou `vec_model_path`. Dans un worker, pas d'env de training.

**Solution** : Créer `_build_eval_obs_normalizer_for_worker` qui :
- Reçoit `model`, `vec_model_path`, `vec_normalize_enabled`, `vec_eval_enabled`
- Si `vec_normalize_enabled and vec_eval_enabled` : utilise `vec_model_path`
- Retourne une fonction `obs -> normalized_obs` ou `None`

```python
def _build_eval_obs_normalizer_for_worker(
    model,
    vec_model_path: Optional[str],
    vec_normalize_enabled: bool,
    vec_eval_enabled: bool,
) -> Optional[Callable[[np.ndarray], np.ndarray]]:
    """Version worker : pas d'accès à l'env de training."""
    if not vec_normalize_enabled or not vec_eval_enabled:
        return None
    if not vec_model_path:
        raise RuntimeError("VecNormalize enabled but vec_model_path not provided for worker")
    from ai.vec_normalize_utils import normalize_observation_for_inference
    def _normalize(obs: np.ndarray) -> np.ndarray:
        obs_arr = np.asarray(obs, dtype=np.float32)
        if obs_arr.ndim == 1:
            obs_arr = obs_arr.reshape(1, -1)
        normalized = normalize_observation_for_inference(obs_arr, vec_model_path)
        return np.asarray(normalized, dtype=np.float32).squeeze()
    return _normalize
```

### 2.5 Granularité des tâches (données sérialisables)

**Ne pas passer** d'instances de bots (RandomBot(), etc.) — pas garantis picklables.

**Format des tâches** (dict sérialisable) :
```python
task = {
    "bot_name": str,
    "bot_type": str,
    "randomness_config": dict,
    "scenario_file": str,
    "scenario_name": str,  # pour agrégation et retour (ex: holdout_regular_bot-1)
    "n_episodes": int,
    "base_seed": int,
    "scenario_index": int,
    "deterministic": bool,
    "config_params": dict,
}
```

Le worker instancie le bot via `_create_eval_env` qui gère RandomBot vs GreedyBot/DefensiveBot.

### 2.6 Refactor de `evaluate_against_bots`

**Structure cible** :

```python
def evaluate_against_bots(model, ...):
    model_path = ...  # chemin vers model.zip
    base_seed = 42  # ou depuis config
    use_subprocess = callback_params.get("bot_eval_use_subprocess", True)
    if step_logger and step_logger.enabled:
        use_subprocess = False
    if debug_mode:
        use_subprocess = False

    config_params = {
        "training_config_name": ...,
        "rewards_config_name": ...,
        "controlled_agent": ...,
        "base_agent_key": ...,
        "vec_normalize_enabled": ...,
        "vec_model_path": ...,
        "debug_mode": ...,
    }
    # step_logger : ajouter UNIQUEMENT si use_subprocess=False (non picklable)
    if not use_subprocess and step_logger and step_logger.enabled:
        config_params["step_logger"] = step_logger

    # vec_eval_enabled : training_cfg.vec_normalize_eval.enabled
    # (training_cfg = config.load_agent_training_config(base_agent_key, training_config_name))
    vec_norm_eval_cfg = require_key(training_cfg, "vec_normalize_eval")
    vec_eval_enabled = bool(require_key(vec_norm_eval_cfg, "enabled"))
    initargs = (model_path, vec_model_path, vec_normalize_enabled, vec_eval_enabled,
                training_config_name, rewards_config_name, controlled_agent, base_agent_key)

    # Répartition des épisodes par scénario (identique à l'actuel)
    episodes_per_scenario = n_episodes // len(scenario_list)
    extra_episodes = n_episodes % len(scenario_list)

    tasks = []
    for bot_name in bots.keys():
        bot_type = bot_name  # bot_name == bot_type ("random", "greedy", "defensive")
        randomness_config = {
            "greedy": eval_randomness.get("greedy", 0.15),
            "defensive": eval_randomness.get("defensive", 0.15),
        }
        for scenario_index, scenario_file in enumerate(scenario_list):
            episodes_for_scenario = episodes_per_scenario + (1 if scenario_index < extra_episodes else 0)
            if episodes_for_scenario <= 0:
                continue
            scenario_name = _scenario_name_from_file(base_agent_key, scenario_file)
            tasks.append({
                "bot_name": bot_name,
                "bot_type": bot_type,
                "randomness_config": randomness_config,
                "scenario_file": scenario_file,
                "scenario_name": scenario_name,
                "n_episodes": episodes_for_scenario,
                "base_seed": base_seed,
                "scenario_index": scenario_index,
                "deterministic": deterministic,
                "config_params": config_params,
            })

    if use_subprocess and n_workers > 1:
        ctx = mp.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=n_workers,
            mp_context=ctx,
            initializer=_eval_worker_init,
            initargs=initargs,
        ) as pool:
            futures = [pool.submit(_eval_worker_task, t) for t in tasks]
            results_list = [_get_result_with_timeout(f, t, task_timeout_seconds) for f, t in zip(futures, tasks)]
    else:
        # Mode sérial : initialiser dans le processus principal puis exécuter les tâches
        _eval_worker_init(*initargs)
        results_list = [_eval_worker_task(t) for t in tasks]

    # Agréger results_list dans results (dict final) — voir section 2.9
```

### 2.7 Timeout et gestion d'erreurs

**Problème** : Un épisode peut rester bloqué (boucle infinie, etc.).

```python
def _get_result_with_timeout(
    future,
    task: Dict[str, Any],
    timeout_seconds: int = 300,
) -> Dict[str, Any]:
    """Récupère le résultat d'une tâche avec timeout. Retourne dict avec timeout/error si échec."""
    bot_name = task["bot_name"]
    scenario_name = task.get("scenario_name") or os.path.basename(task["scenario_file"]).replace(".json", "")
    try:
        return future.result(timeout=timeout_seconds)
    except TimeoutError:
        import logging
        logging.warning(f"Eval task timeout: bot={bot_name} scenario={scenario_name}")
        return {"wins": 0, "losses": 0, "draws": 0, "timeout": True, "bot_name": bot_name, "scenario_name": scenario_name}
    except Exception as e:
        import logging
        logging.exception(f"Eval task failed: bot={bot_name} scenario={scenario_name} error={e}")
        return {"wins": 0, "losses": 0, "draws": 0, "error": str(e), "bot_name": bot_name, "scenario_name": scenario_name}
```

- Config : `callback_params.bot_eval_task_timeout_seconds` (default: 300)
- En cas de timeout ou erreur : logger, ne pas faire planter tout l'éval, incrémenter `failed_episodes` dans l'agrégat

### 2.8 Paramètres de config

| Paramètre | Default | Description |
|-----------|---------|-------------|
| `callback_params.bot_eval_use_subprocess` | True | Activer ProcessPoolExecutor |
| `callback_params.bot_eval_n_workers` | min(n_envs, nb_tâches) | Nombre de workers parallèles |
| `callback_params.bot_eval_task_timeout_seconds` | 300 | Timeout par tâche (secondes) |

Si `step_logger.enabled` ou `debug_mode` : forcer `use_subprocess=False` (mode sérial)

### 2.9 Agrégation des résultats

Après `results = [_get_result_with_timeout(...) for ...]`, chaque élément est un dict avec `wins`, `losses`, `draws`, `bot_name`, `scenario_name`, `shoot_stats` (optionnel).

**Agrégation à reproduire** (identique à l'actuel `evaluate_against_bots`) :

```python
# results_list = liste des dicts retournés par les workers (ou _get_result_with_timeout)
results = {}  # dict final à retourner

# 1. Par bot : wins, losses, draws, shoot_stats
for bot_name in bots.keys():
    bot_results = [r for r in results_list if r.get("bot_name") == bot_name]
    wins = sum(r["wins"] for r in bot_results)
    losses = sum(r["losses"] for r in bot_results)
    draws = sum(r["draws"] for r in bot_results)
    results[bot_name] = wins / max(1, wins + losses + draws)
    results[f"{bot_name}_wins"] = wins
    results[f"{bot_name}_losses"] = losses
    results[f"{bot_name}_draws"] = draws
    results[f"{bot_name}_shoot_stats"] = [
        r.get("shoot_stats", {}) for r in bot_results
        if r.get("shoot_stats")
    ]

# 2. Par scénario : scenario_bot_stats[scenario_name][bot_name]
scenario_bot_stats = {}
for r in results_list:
    sn, bn = r.get("scenario_name"), r.get("bot_name")
    if sn and bn:
        if sn not in scenario_bot_stats:
            scenario_bot_stats[sn] = {}
        total = r["wins"] + r["losses"] + r["draws"]
        scenario_bot_stats[sn][bn] = {
            "win_rate": r["wins"] / max(1, total),
            "wins": r["wins"], "losses": r["losses"], "draws": r["draws"],
        }

# 3. total_failed_episodes (timeout + error)
total_failed_episodes = sum(1 for r in results_list if r.get("timeout") or r.get("error"))

# 4. combined (pondéré par eval_weights)
results["combined"] = (
    eval_weights["random"] * results["random"] +
    eval_weights["greedy"] * results["greedy"] +
    eval_weights["defensive"] * results["defensive"]
)
results["scenario_bot_stats"] = scenario_bot_stats
# (scenario_scores, holdout_split_metrics, etc. — logique existante)
```

---

## Phase 3 : Intégration train.py (déjà en place)

- Le chemin `--test-only` / `--eval` appelle déjà `evaluate_against_bots()`
- Aucun changement de flux
- Après Phase 2, `evaluate_against_bots` utilisera les workers par défaut

---

## Ordre d'exécution recommandé

| Ordre | Phase | Fichiers | Validation |
|-------|-------|----------|------------|
| 0 | 0.1 + 0.2 | bot_evaluation.py | `_create_eval_env` utilisée en mode sérial |
| 1 | 1.1 + 1.2 | train.py, w40k_core.py | `python ai/train.py --eval --agent X ...` |
| 2 | 2.0–2.9 | bot_evaluation.py | Comparer résultats sérial vs parallèle (tolérance ±2 %) |
| 3 | - | - | Lancer un training complet et vérifier l'éval callback |

---

## Fichiers impactés

| Fichier | Modifications |
|---------|---------------|
| `ai/train.py` | +--eval, doc |
| `engine/w40k_core.py` | +_next_engine_id(), _cache_instance_id dans __init__ |
| `ai/bot_evaluation.py` | +_create_eval_env, +_eval_worker_init, +_eval_worker_task, +_episode_seed, +_build_eval_obs_normalizer_for_worker, +_get_result_with_timeout, refactor evaluate_against_bots avec ProcessPoolExecutor (spawn) + initializer + timeout |
| `config/agents/*/training_config.json` | +bot_eval_use_subprocess, +bot_eval_n_workers, +bot_eval_task_timeout_seconds (optionnels) |

---

## Tests de non-régression

1. **Eval standalone** : `python ai/train.py --eval --agent X --training-config Y` → résultats cohérents (seed fixe)
2. **Eval callback** : lancer un training court, vérifier que l'éval ne plante pas
3. **Cache collision** : lancer plusieurs évals d'affilée, vérifier absence d'erreur LoS
4. **Sérial vs parallèle** : exécuter 100 épisodes en mode sérial, puis 100 en parallèle (4 workers). Les win rates doivent être **statistiquement proches** (tolérance ±2 % sur combined score), pas identiques (ordre d'exécution diffère).

---

## Rollback

- Phase 0 : revert de `_create_eval_env` (réintégrer la logique inline)
- Phase 1 : revert des 2 patches
- Phase 2 : `bot_eval_use_subprocess=False` pour revenir à l'ancienne boucle (mode sérial)

---

## Corrections et ajouts par rapport à PLAN01

| Correction / Ajout | Description |
|-------------------|-------------|
| `_create_initial_game_state` | Référence corrigée : `game_state` est dans `__init__`, pas une méthode séparée |
| Instanciation RandomBot | `RandomBot()` sans argument ; `GreedyBot`/`DefensiveBot` avec `randomness=` |
| Timeout | Section 2.7 + `_get_result_with_timeout` pour éviter blocage |
| Alias --eval | Conserver `--test-only` pour rétrocompatibilité |
| **Seeds déterministes** | `hashlib.md5` au lieu de `hash()` (reproductible entre exécutions) |
| **Worker initializer** | `_eval_worker_init` charge modèle + normalizer une fois par worker ; mode sérial appelle `_eval_worker_init(*initargs)` avant la boucle |
| **action_masks** | `model.predict` reçoit `action_masks` (MaskablePPO) |
| **shoot_stats** | Worker retourne `shoot_stats` via `env.get_shoot_stats()` |
| **scenario_name** | Inclus dans la tâche et les retours (timeout/error) pour agrégation |
| **Boucle tâches** | `for bot_name in bots.keys()`, `randomness_config` depuis `eval_randomness` |
| **Répartition épisodes** | `episodes_per_scenario + (1 if scenario_index < extra_episodes else 0)` |
| **Agrégation** | Section 2.9 : results par bot, scenario_bot_stats, combined, total_failed_episodes |
| **step_logger** | En mode sérial : `config_params["step_logger"] = step_logger` ; après `_create_eval_env` : `env.engine.step_logger = config_params["step_logger"]` |
| **vec_eval_enabled** | Depuis `training_config.vec_normalize_eval.enabled` |
| **_create_eval_env** | Signature sans `vec_normalize_enabled`/`vec_model_path` (non utilisés pour la création d'env) |
