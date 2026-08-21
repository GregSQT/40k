#!/usr/bin/env python3
"""
ai/bot_evaluation.py - Bot evaluation functionality

Contains:
- evaluate_against_bots: Standalone bot evaluation function for all bot testing

Extracted from ai/train.py during refactoring (2025-01-21)
"""

import hashlib
import json
import logging
import multiprocessing as mp
import os
import sys
import time
import tempfile
import shutil
import atexit
import numpy as np
import re
from collections import defaultdict, deque
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from typing import Callable, Optional, Dict, List, Any, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from ai.env_wrappers import BotControlledEnv

from engine.constants import DRAW_WINNER
from shared.data_validation import require_key, require_present
from shared.torch_safe_globals import register_torch_safe_globals
from shared.json_atomic import write_json_atomic
from shared.progress_writer import ProgressWriter
from ai.scenario_scratch import make_scenario_scratch_dir

# Avant tout `MaskablePPO.load` de ce module : torch >= 2.6 charge en `weights_only=True`.
register_torch_safe_globals()

__all__ = [
    'evaluate_against_bots',
    'validate_bot_eval_worker_params',
    'discover_checkpoint_archives',
    'evaluate_against_checkpoints',
]

# Worker globals (scope processus)
_worker_model = None
_worker_obs_normalizer = None
_eval_ref_temp_dir: Optional[str] = None


def validate_bot_eval_worker_params(callback_params: Dict[str, Any]) -> Dict[str, Any]:
    """Valide les trois parametres de parallelisation de l'evaluation bot.

    FABRIQUE UNIQUE, appelee a DEUX moments qui ne sont pas redondants :
    - `ai/train.py`, au demarrage, avec les autres `callback_params.bot_eval_*` : c'est la
      qu'une config incomplete doit arreter le run, pas apres des minutes d'entrainement ;
    - `evaluate_against_bots`, qui est aussi un point d'entree autonome (evaluation hors
      entrainement) et ne peut donc pas s'en remettre au controle de train.py.

    Ces trois cles etaient lues par `.get()` avec defaut silencieux, et vivaient au niveau
    SUPERIEUR de la section de phase alors que toute la chaine les cherche dans
    `callback_params` (cf. `_resolve_callback_value` dans `ai/train.py`). Elles etaient donc
    invisibles : `bot_eval_n_workers` retombait sur `min(n_envs, n_scenarios * n_bots)` = 24
    workers quelle que soit la valeur ecrite. Mesure : 24 workers = 47 Go de RSS (~1,9 Go
    chacun) contre 9,6 Go a 4, et une evaluation 42 % PLUS LENTE (598 s contre 349 s) parce que
    la VM swappait. Un repli qui contredit silencieusement la config est ce qu'interdit T1.

    Aucune de ces trois cles n'est definie dans `config/agents/_training_common.json` : il n'y
    a donc pas de valeur partagee a resoudre, l'absence est une erreur de config.
    """
    use_subprocess = require_key(callback_params, "bot_eval_use_subprocess")
    if not isinstance(use_subprocess, bool):
        raise TypeError(
            "callback_params.bot_eval_use_subprocess must be boolean "
            f"(got {type(use_subprocess).__name__})"
        )
    task_timeout_seconds = require_key(callback_params, "bot_eval_task_timeout_seconds")
    if not isinstance(task_timeout_seconds, int) or isinstance(task_timeout_seconds, bool):
        raise TypeError(
            "callback_params.bot_eval_task_timeout_seconds must be an integer "
            f"(got {type(task_timeout_seconds).__name__})"
        )
    if task_timeout_seconds <= 0:
        raise ValueError(
            "callback_params.bot_eval_task_timeout_seconds must be > 0 "
            f"(got {task_timeout_seconds})"
        )
    n_workers = require_key(callback_params, "bot_eval_n_workers")
    if not isinstance(n_workers, int) or isinstance(n_workers, bool) or n_workers <= 0:
        raise ValueError(
            f"callback_params.bot_eval_n_workers must be a positive integer (got {n_workers!r})"
        )
    return {
        "use_subprocess": use_subprocess,
        "task_timeout_seconds": task_timeout_seconds,
        "n_workers": n_workers,
    }


def _cleanup_eval_ref_temp_dir() -> None:
    """Efface le répertoire de travail des scénarios d'éval.

    N'est PLUS branché sur `atexit` : le replay est ouvert après le run et a besoin du scénario
    matérialisé pour dessiner son décor (`ai.scenario_scratch`). La purge des runs révolus se
    fait à la création du suivant. Reste appelable explicitement — les tests s'en servent."""
    global _eval_ref_temp_dir
    if _eval_ref_temp_dir and os.path.isdir(_eval_ref_temp_dir):
        shutil.rmtree(_eval_ref_temp_dir, ignore_errors=True)
    _eval_ref_temp_dir = None


def _get_eval_ref_temp_dir() -> str:
    """Create (once) and return temp dir for eval scenario ref overrides.

    Sous la racine du dépôt (cf. `ai.scenario_scratch`) : le scénario matérialisé est celui que
    l'épisode joue réellement, et son chemin doit rester journalisable pour le replay."""
    global _eval_ref_temp_dir
    if _eval_ref_temp_dir is None:
        _eval_ref_temp_dir = make_scenario_scratch_dir("w40k_eval_refmix_")
    return _eval_ref_temp_dir


def _materialize_eval_scenario_refs(
    scenario_path: str,
    wall_ref: str,
) -> str:
    """Create temporary scenario JSON with overridden wall_ref.

    Objectives are sourced from the terrain (terrain-flagged objectives, rules
    14.01/14.02) — the legacy per-scenario objectives_ref key is no longer emitted
    (rejected by the engine).
    """
    if not isinstance(wall_ref, str) or not wall_ref.strip():
        raise ValueError(f"Invalid eval wall_ref override: {wall_ref!r}")
    with open(scenario_path, "r", encoding="utf-8-sig") as f:
        scenario_data = json.load(f)
    if not isinstance(scenario_data, dict):
        raise TypeError(f"Scenario JSON must be object: {scenario_path}")
    scenario_copy = dict(scenario_data)
    scenario_copy.pop("wall_hexes", None)
    # Legacy objectives keys are rejected by the engine (objectives now come from the
    # terrain, rules 14.01/14.02) — never emit them in the materialized eval scenario.
    scenario_copy.pop("objectives_ref", None)
    scenario_copy.pop("objectives", None)
    scenario_copy.pop("objective_hexes", None)
    scenario_copy["wall_ref"] = wall_ref.strip()

    source_parts = tuple(os.path.abspath(scenario_path).split(os.sep))
    if "agents" not in source_parts:
        raise ValueError(
            f"Eval scenario override requires path containing 'agents': {scenario_path}"
        )
    agents_idx = source_parts.index("agents")
    if agents_idx + 1 >= len(source_parts):
        raise ValueError(f"Cannot resolve agent key from eval scenario path: {scenario_path}")
    agent_key = source_parts[agents_idx + 1]
    try:
        scenarios_idx = source_parts.index("scenarios", agents_idx + 2)
        split_dir = source_parts[scenarios_idx + 1]
    except (ValueError, IndexError):
        raise ValueError(
            f"Cannot resolve split directory (training/holdout_*) from eval scenario path: {scenario_path}"
        )

    temp_root = _get_eval_ref_temp_dir()
    out_dir = os.path.join(temp_root, "agents", agent_key, "scenarios", split_dir)
    os.makedirs(out_dir, exist_ok=True)
    path_hash = hashlib.sha1(
        f"{os.path.abspath(scenario_path)}|{wall_ref}".encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()[:16]
    out_path = os.path.join(out_dir, f"{os.path.basename(scenario_path)[:-5]}__{path_hash}.json")
    if not os.path.exists(out_path):
        write_json_atomic(out_path, scenario_copy)
    return out_path


def _load_bot_eval_params(config_loader, agent_key: str, training_config_name: str):
    """Load bot evaluation weights and randomness from agent training config."""
    if not agent_key:
        raise ValueError("controlled_agent is required to load bot evaluation parameters from agent config")

    training_cfg = config_loader.load_agent_training_config(agent_key, training_config_name)
    callback_params = require_key(training_cfg, "callback_params")

    bot_eval_weights = require_key(callback_params, "bot_eval_weights")
    weights: Dict[str, float] = {
        name: float(w) for name, w in bot_eval_weights.items()
    }
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > 1e-9:
        detail = ", ".join(f"{k}={v}" for k, v in weights.items())
        raise ValueError(
            f"callback_params.bot_eval_weights must sum to 1.0 "
            f"(got {detail}, total={total_weight})"
        )

    bot_eval_randomness = require_key(callback_params, "bot_eval_randomness")
    randomness: Dict[str, float] = {
        name: float(r) for name, r in bot_eval_randomness.items()
    }

    return {
        "weights": weights,
        "randomness": randomness,
    }


#: Couple de factions dont l'ecart de win-rate est publie en 00_critical/0_gap_sm-ork.
#: L'ORDRE porte le sens de la courbe : gap = score(ROSTER_GAP_FACTIONS[0]) - score([1]),
#: donc positif = Space Marines dominants, negatif = Orks dominants. Changer cet ordre
#: inverserait le sens d'une courbe deja tracee : le nom du tag doit suivre.
ROSTER_GAP_FACTIONS: Tuple[str, str] = ("Spacemarine", "Ork")


def _agent_faction_from_engine(engine: Any) -> str:
    """
    Faction reellement jouee par l'agent sur l'episode courant.

    MESUREE sur les unites chargees, pas deduite du nom du fichier de scenario : le roster
    de l'agent peut etre tire au sort (`agent_roster_ref: "*_random"`, autorise en holdout
    comme en training par GameStateManager._resolve_roster_ref), auquel cas le scenario ne
    dit pas quelle faction a ete jouee. A appeler APRES reset() et AVANT la fin de partie —
    une escouade morte disparait de game_state["units"].

    Un roster MIXTE rend la cle composite ("Ork+Spacemarine") au lieu de lever : cette
    fonction sert une metrique de DIAGNOSTIC, elle ne doit pas pouvoir abattre un run de
    36 h. La cle composite ne figure dans aucun couple de ROSTER_GAP_FACTIONS, donc elle
    est visible dans `bot_eval/faction/*` et n'entre jamais dans le gap — ce n'est pas un
    repli qui masque une erreur, c'est le domaine de definition de la mesure : « faction
    jouee » n'a pas de valeur unique pour un roster mixte.
    Un roster VIDE, lui, leve : aucune unite pour le joueur controle est une anomalie
    d'environnement, pas un cas de jeu.
    """
    unit_registry = require_present(engine.unit_registry, "engine.unit_registry")
    controlled_player = int(require_key(engine.config, "controlled_player"))
    # `unitType` (camelCase) et non `unit_type` : c'est la clef des unites MATERIALISEES dans
    # game_state (GameStateManager._build_enhanced_unit) ; `unit_type` n'existe que dans la
    # declaration de scenario en amont.
    factions = {
        str(require_key(unit_registry.get_unit_data(require_key(unit, "unitType")), "faction"))
        for unit in require_key(engine.game_state, "units")
        if int(require_key(unit, "player")) == controlled_player
    }
    if not factions:
        raise ValueError(
            f"No unit belongs to the controlled player {controlled_player}: cannot attribute "
            f"a faction to this episode"
        )
    return "+".join(sorted(factions))


#: Roster non identifiable : le scenario declare ses unites en dur au lieu de referencer un
#: roster, donc `roster_info` est absent. Meme parti que la cle de faction composite
#: (`_agent_faction_from_engine`) : la ventilation par roster est une metrique de DIAGNOSTIC et
#: ne doit pas pouvoir abattre un run de 36 h. La valeur est VISIBLE dans TensorBoard et ne se
#: confond avec aucun roster reel — elle signale un scenario a cabler, elle ne le masque pas.
NO_ROSTER_REF = "<no_roster_ref>"

#: Les deux camps dont le roster est ventile. Constante et pas litteral repete : l'ensemble etait
#: reecrit sous trois formes (tuple de boucle, set de validation, litteral d'initialisation) sur
#: huit sites, et un oubli sur `_failed_task_result` fait sauter le run au premier timeout.
ROSTER_SIDES: Tuple[str, str] = ("agent", "opponent")

#: Les deux SIEGES que l'agent peut occuper, dans l'ordre ou le gap les soustrait.
#:
#: POURQUOI CETTE VENTILATION EXISTE. `agent_seat_mode: "random"` fait jouer l'agent premier ou
#: second a parts egales, et l'entrainement mesure les deux separement (`seat_aware/winrate_agent_p1`
#: / `_p2`). L'EVALUATION, elle, ne le faisait pas : son `combined` melangeait les deux sieges, si
#: bien que le chiffre qui SELECTIONNE le modele livre (score robuste) etait aveugle a l'ecart entre
#: eux. Mesure du run x1_long du 2026-08-12 : 0.707 en jouant premier contre 0.586 en jouant second,
#: 12 points, stables jusqu'a la fin du run. Un 0.909 de combined peut donc cacher un 0.95/0.87 —
#: c'est-a-dire un agent qui perd la moitie de ses parties reelles pour une raison qu'aucune courbe
#: d'evaluation ne montrait.
SEAT_KEYS: Tuple[str, str] = ("p1", "p2")


def _seat_key(controlled_player: int) -> str:
    """`1 -> "p1"`, `2 -> "p2"`. Aucun autre siege n'existe : tout le reste est une rupture."""
    seat = int(controlled_player)
    if seat not in (1, 2):
        raise ValueError(f"controlled_player doit valoir 1 ou 2, pas {controlled_player!r}")
    return f"p{seat}"


def _episode_roster_ids(engine: Any) -> Dict[str, str]:
    """`{"agent": <roster_id>, "opponent": <roster_id>}` de l'episode courant.

    MESURE sur l'etat charge, pas deduite du nom du scenario — meme raison que
    `_agent_faction_from_engine` : `agent_roster_ref: "training_random"` tire le roster au sort a
    chaque reset, donc le scenario ne dit pas lequel a ete joue. C'est precisement ce que cette
    ventilation existe pour rendre lisible : une variante de liste (avec / sans reserves
    strategiques) est un ROSTER, pas un scenario — la figer dans un scenario tuerait la rotation
    aleatoire qui sert la generalisation.

    A appeler APRES reset().

    Acces DIRECT a l'attribut, sans `getattr(..., None)` : les DEUX branches de
    `W40KEngine.__init__` le posent (chargement de scenario cote entrainement, `None` explicite
    cote API/PvP faute de loader), ainsi que chaque rotation de scenario, donc un defaut ne
    couvrirait aucun cas reel — il ne ferait que transformer un renommage d'attribut, ou un
    moteur qui n'a jamais charge de scenario, en « 100 % des episodes sous `NO_ROSTER_REF` ».
    L'operateur lirait alors « scenario a cabler » la ou la metrique est cassee. `None` reste une
    valeur legitime, elle : un scenario qui declare ses unites en dur n'a pas de roster.
    """
    roster_info = engine._scenario_roster_info
    if roster_info is None:
        return {side: NO_ROSTER_REF for side in ROSTER_SIDES}
    return {
        "agent": str(require_key(roster_info, "agent_roster_id")),
        "opponent": str(require_key(roster_info, "opponent_roster_id")),
    }


def _bot_tally(
    results_list: List[Dict[str, Any]],
    active_bot_names: Tuple[str, ...],
    stats_of: Callable[[Dict[str, Any]], Dict[str, Dict[str, int]]],
) -> Dict[str, Dict[str, List[int]]]:
    """`tally[cle][bot] = [wins, total]` — le SEUL comptage croise <cle d'episode> x bot.

    `stats_of` extrait d'un resultat de tache la sous-table `{cle: {"wins", "total"}}` relevee
    episode par episode : `faction_stats` pour la faction jouee, `roster_stats[side]` pour le
    roster de chaque camp.

    UNE mecanique pour toutes les ventilations, et c'est ce qui rend vraie la propriete qu'elles
    annoncent : la somme des cellules retombe sur le win-rate global parce que le filtre de bot,
    l'accumulation et les coercions sont litteralement le meme code, pas parce que deux copies
    se ressemblent aujourd'hui. Une regle ajoutee ici (exclure les taches en erreur, ponderer,
    seuil d'episodes) vaut pour les trois publications d'un coup — recopiee, elle en aurait
    manque deux, et les courbes `bot_eval/faction/*` et `bot_eval/roster/*` auraient publie des
    denominateurs differents pour le meme run.
    """
    tally: Dict[str, Dict[str, List[int]]] = {}
    for result in results_list:
        bot_name = result.get("bot_name")
        if bot_name not in active_bot_names:
            continue
        for key, stats in stats_of(result).items():
            per_bot = tally.setdefault(str(key), {})
            wins, total = per_bot.setdefault(str(bot_name), [0, 0])
            per_bot[str(bot_name)] = [
                wins + int(require_key(stats, "wins")),
                total + int(require_key(stats, "total")),
            ]
    return tally


def _faction_bot_tally(
    results_list: List[Dict[str, Any]],
    active_bot_names: Tuple[str, ...],
) -> Dict[str, Dict[str, List[int]]]:
    """`tally[faction][bot] = [wins, total]`.

    Existe pour que la ventilation publiee (`_compute_bot_win_rates`) et l'agregat par faction
    (`_compute_faction_scores`) derivent du meme comptage : deux parcours independants de
    `results_list` divergeraient au premier changement de ponderation ou de filtre.
    """
    return _bot_tally(
        results_list, active_bot_names, lambda r: require_key(r, "faction_stats")
    )


def _seat_bot_tally(
    results_list: List[Dict[str, Any]],
    active_bot_names: Tuple[str, ...],
) -> Dict[str, Dict[str, List[int]]]:
    """`tally[seat][bot] = [wins, total]`, `seat` valant "p1" ou "p2" (cf. SEAT_KEYS).

    Meme mecanique que la faction et le roster, et c'est ce qui garantit la propriete annoncee :
    la somme des deux sieges retombe sur le win-rate global parce que le filtre de bot et
    l'accumulation sont LE MEME code, pas parce que trois copies se ressemblent.
    """
    return _bot_tally(
        results_list, active_bot_names, lambda r: require_key(r, "seat_stats")
    )


def _roster_bot_tally(
    results_list: List[Dict[str, Any]],
    active_bot_names: Tuple[str, ...],
    side: str,
) -> Dict[str, Dict[str, List[int]]]:
    """`tally[roster_id][bot] = [wins, total]` pour un COTE (`agent` ou `opponent`)."""
    if side not in ROSTER_SIDES:
        raise ValueError(
            f"_roster_bot_tally: side doit valoir l'un de {ROSTER_SIDES}, pas {side!r}"
        )
    return _bot_tally(
        results_list, active_bot_names, lambda r: require_key(r, "roster_stats")[side]
    )


def _compute_bot_win_rates(
    tally: Dict[str, Dict[str, List[int]]],
) -> Dict[str, Dict[str, float]]:
    """Win-rate BRUT de chaque bot, ventile par la cle du `tally` (faction V11 §10.6, ou roster).

    Croisement que ni `bot_eval/vs_<bot>` (toutes cles confondues) ni `bot_eval/faction/<faction>`
    (agregat pondere) ne donnent : c'est lui qui dit si une faiblesse contre un adversaire tient a
    UNE cle ou a toutes. Par roster, c'est le seul endroit ou deux variantes d'une meme faction
    (avec et sans reserves strategiques) cessent d'etre confondues — sans quoi une baisse apres
    l'ajout des reserves serait inattribuable : liste plus faible, ou agent qui ne sait pas
    defendre contre une arrivee ?

    Contrairement a l'agregat, aucune cle n'est ecartee : chaque cellule est un win-rate autonome,
    sur sa propre echelle, donc une couverture partielle reste lisible. Un couple (cle, bot) sans
    episode joue n'est pas publie — un 0.0 y serait un score invente.
    """
    return {
        key: {
            bot_name: wins / total
            for bot_name, (wins, total) in per_bot.items()
            if total > 0
        }
        for key, per_bot in tally.items()
    }


def _compute_faction_scores(
    tally: Dict[str, Dict[str, List[int]]],
    active_bot_names: Tuple[str, ...],
    eval_weights: Dict[str, float],
) -> Dict[str, float]:
    """
    Win-rate pondere par bot, ventile par faction jouee par l'agent.

    Meme ponderation que `results["combined"]` (bot_eval_weights) pour que les deux courbes
    soient comparables : le gap entre factions est un ecart de combined, pas un ecart de
    win-rate brut qui melangerait des adversaires de difficultes differentes.
    Une faction dont un seul bot n'a produit aucun episode est ECARTEE : son score partiel
    ne serait pas sur la meme echelle que celui des autres.

    Prend le `tally` CONSTRUIT, pas `results_list` : c'est le meme objet que consomme
    `_compute_bot_win_rates`, donc les deux ventilations ne peuvent pas diverger sur
    un comptage. Meme geste que `scenario_bot_stats`, construit une fois puis derive.
    """
    faction_scores: Dict[str, float] = {}
    for faction, per_bot in tally.items():
        if any(bn not in per_bot or per_bot[bn][1] == 0 for bn in active_bot_names):
            continue
        faction_scores[faction] = sum(
            eval_weights[bn] * (per_bot[bn][0] / per_bot[bn][1]) for bn in active_bot_names
        )
    return faction_scores


def _scenario_name_from_file(base_agent_key: str, scenario_file: str) -> str:
    """Build short scenario name used in logs/results."""
    basename = os.path.basename(scenario_file).replace(".json", "")
    parent_dir = os.path.basename(os.path.dirname(scenario_file))
    name = basename
    if base_agent_key:
        agent_prefix = f"{base_agent_key}_"
        if name.startswith(agent_prefix):
            name = name[len(agent_prefix):]
    if name.startswith("scenario_"):
        name = name[len("scenario_"):]
    bot_match = re.fullmatch(r"bot-(\d+)", name)
    if bot_match and parent_dir in {"holdout_regular", "holdout_hard"}:
        return f"{parent_dir}_bot-{bot_match.group(1)}"
    return name


def _scenario_metric_slug(scenario_name: str) -> str:
    """Convert scenario label to TensorBoard-safe metric suffix."""
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", scenario_name.strip()).strip("_").lower()
    if not normalized:
        raise ValueError(f"Invalid scenario name for metric slug: '{scenario_name}'")
    return normalized


def _scenario_split_metric_key(scenario_name: str) -> Optional[str]:
    """
    Convert scenario name to split metric key.

    Supported names:
      - training_bot-<n>        -> training_bot_<n>
      - holdout_hard_bot-<n>    -> hard_bot_<n>
      - holdout_regular_bot-<n> -> regular_bot_<n>
    """
    name = scenario_name.strip()
    if name.startswith("scenario_"):
        name = name[len("scenario_"):]
    training_match = re.fullmatch(r"training_bot-(\d+)", name)
    if training_match:
        return f"training_bot_{training_match.group(1)}"

    hard_match = re.fullmatch(r"holdout_hard_bot-(\d+)", name)
    if hard_match:
        return f"hard_bot_{hard_match.group(1)}"

    regular_match = re.fullmatch(r"holdout_regular_bot-(\d+)", name)
    if regular_match:
        return f"regular_bot_{regular_match.group(1)}"

    return None


def _compute_scenario_split_scores(
    scenario_scores: Dict[str, Dict[str, float]],
) -> Dict[str, float]:
    """Build split score dictionary keyed by training/hard/regular bot identifiers."""
    split_scores: Dict[str, float] = {}
    for scenario_name, values in scenario_scores.items():
        metric_key = _scenario_split_metric_key(str(scenario_name))
        if metric_key is None:
            continue
        split_scores[metric_key] = float(require_key(values, "combined"))
    return split_scores


def _filter_scenarios_from_config(
    training_cfg: Dict[str, Any],
    scenario_list: List[str],
    base_agent_key: str,
) -> List[str]:
    """
    Optionally filter evaluation scenarios from callback_params.bot_eval_scenarios.

    Expected format:
      callback_params:
        bot_eval_scenarios: ["bot-1", "bot-2"]
    """
    callback_params = require_key(training_cfg, "callback_params")
    requested = callback_params.get("bot_eval_scenarios")
    if requested is None:
        return scenario_list
    if not isinstance(requested, list):
        raise TypeError(
            "callback_params.bot_eval_scenarios must be a list of scenario names"
        )
    if len(requested) == 0:
        raise ValueError("callback_params.bot_eval_scenarios cannot be an empty list")

    requested_names = [str(name) for name in requested]
    scenario_map = {
        _scenario_name_from_file(base_agent_key, path): path
        for path in scenario_list
    }

    missing = [name for name in requested_names if name not in scenario_map]
    if missing:
        available = ", ".join(sorted(scenario_map.keys()))
        missing_fmt = ", ".join(missing)
        raise KeyError(
            "Unknown scenario(s) in callback_params.bot_eval_scenarios: "
            f"{missing_fmt}. Available: {available}"
        )

    return [scenario_map[name] for name in requested_names]


def _compute_holdout_split_metrics(
    training_cfg: Dict[str, Any],
    scenario_scores: Dict[str, Dict[str, float]],
    scenario_pool: str,
) -> Dict[str, float]:
    """Compute holdout regular/hard aggregates from callback_params scenario lists."""
    if scenario_pool != "holdout":
        return {}

    callback_params = require_key(training_cfg, "callback_params")
    regular_names = callback_params.get("holdout_regular_scenarios")
    hard_names = callback_params.get("holdout_hard_scenarios")

    if regular_names is None and hard_names is None:
        return {}
    if not isinstance(regular_names, list) or len(regular_names) == 0:
        raise ValueError(
            "callback_params.holdout_regular_scenarios must be a non-empty list "
            "when holdout split metrics are configured"
        )
    if not isinstance(hard_names, list) or len(hard_names) == 0:
        raise ValueError(
            "callback_params.holdout_hard_scenarios must be a non-empty list "
            "when holdout split metrics are configured"
        )

    available = set(scenario_scores.keys())
    regular_keys = [str(name) for name in regular_names]
    hard_keys = [str(name) for name in hard_names]

    missing_regular = [name for name in regular_keys if name not in available]
    missing_hard = [name for name in hard_keys if name not in available]
    if missing_regular or missing_hard:
        # Not enough episodes to cover every holdout split scenario.
        # Keep evaluation running, but skip split aggregates to avoid misleading partial means.
        return {}

    regular_values = [float(require_key(scenario_scores[name], "combined")) for name in regular_keys]
    hard_values = [float(require_key(scenario_scores[name], "combined")) for name in hard_keys]
    all_values = regular_values + hard_values
    if len(all_values) == 0:
        raise ValueError("Holdout split metrics cannot be computed from empty scenario score sets")

    return {
        "holdout_regular_mean": float(sum(regular_values) / len(regular_values)),
        "holdout_hard_mean": float(sum(hard_values) / len(hard_values)),
        "holdout_overall_mean": float(sum(all_values) / len(all_values)),
    }


def _format_elapsed(seconds: float) -> str:
    """Format seconds as MM:SS or H:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


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
    agent_seat_mode: str,
    agent_seat_seed: Optional[int],
) -> "BotControlledEnv":
    """
    Crée un env d'éval. Utilisé en mode sérial et dans les workers.

    Tout ce qui est passé doit être sérialisable (picklable) pour usage en workers.
    """
    from ai.training_utils import setup_imports
    from ai.env_wrappers import BotControlledEnv
    from sb3_contrib.common.wrappers import ActionMasker
    from ai.unit_registry import UnitRegistry
    from ai.bot_registry import build_bot

    unit_registry = UnitRegistry()
    W40KEngine, _ = setup_imports()

    # SOURCE UNIQUE de la table cle -> classe : `ai/bot_registry.py`. Elle vivait ici en copie,
    # avec une jumelle dans `scripts/bot_ranking.py` — brancher un bot dans l'une laissait
    # l'autre lever « Unknown bot type » (mesure du 2026-08-11, sur `racer`).
    bot = build_bot(bot_type, randomness_config)

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
        # Evaluation : UN environnement, joue en serie (denominateur des rampes par-episode).
        training_n_envs=1,
    )
    masked_env = ActionMasker(base_env, mask_fn)
    return BotControlledEnv(
        masked_env,
        bot,
        unit_registry,
        agent_seat_mode=agent_seat_mode,
        global_seed=agent_seat_seed,
        env_rank=0,
    )


def _build_eval_obs_normalizer_for_worker(
    model,
    model_path: Optional[str],
    vec_normalize_enabled: bool,
    vec_eval_enabled: bool,
) -> Optional[Callable[[Any], Any]]:
    """Version worker : pas d'accès à l'env de training.

    Le normalizer rendu accepte les DEUX formes d'observation et rend la même : un `dict`
    (pipeline squad, VecNormalize entraînée avec `norm_obs_keys=["global_cont"]`) ou un
    `np.ndarray` (chemin legacy Box à plat). D'où `Callable[[Any], Any]` : une signature
    `ndarray -> ndarray` mentirait sur le chemin Dict, qui est celui du pipeline actuel.

    ⚠️ V11 §0.35 — les stats sont dérivées de `model_path`, le zip que CE worker charge. Il n'y
    a volontairement AUCUN paramètre de chemin de stats séparé : c'est cette séparation qui a
    permis d'évaluer un modèle avec la normalisation d'un autre (l'appelant passait le canonique
    alors que les workers chargeaient un snapshot). Divergence rendue irreprésentable.
    """
    if not vec_normalize_enabled or not vec_eval_enabled:
        return None
    if not model_path:
        raise RuntimeError("VecNormalize enabled but model_path not provided for worker")
    from ai.vec_normalize_utils import normalize_observation_for_inference, get_vec_normalize_path

    # Obs Dict (pipeline squad spatial, tenseurs d'entites V11 §0.30) : VecNormalize a ete
    # entrainee avec norm_obs_keys=["global_cont"] — les tenseurs d'entites sont normalises
    # DANS l'extracteur (statistique partagee entre slots), la grille et les drapeaux restent
    # bruts. normalize_obs ne touche donc que "global_cont". On charge l'objet une fois au lieu de
    # recharger le pkl a chaque step. Le chemin legacy (obs Box a plat) reste byte-identique.
    _dict_vecnorm = {"obj": None}

    def _dict_normalizer():
        if _dict_vecnorm["obj"] is None:
            import pickle
            pkl_path = get_vec_normalize_path(model_path)
            if not os.path.exists(pkl_path):
                raise RuntimeError(
                    f"VecNormalize enabled but stats not found for Dict obs: {pkl_path}"
                )
            with open(pkl_path, "rb") as f:
                vn = pickle.load(f)
            vn.training = False
            vn.norm_reward = False
            _dict_vecnorm["obj"] = vn
        return _dict_vecnorm["obj"]

    def _normalize(obs):
        if isinstance(obs, dict):
            return _dict_normalizer().normalize_obs(obs)
        obs_arr = np.asarray(obs, dtype=np.float32)
        if obs_arr.ndim == 1:
            obs_arr = obs_arr.reshape(1, -1)
        normalized = normalize_observation_for_inference(obs_arr, model_path)
        return np.asarray(normalized, dtype=np.float32).squeeze()

    return _normalize


def _accumulate_behavior(
    behavior_stats: Dict[str, Dict[str, Any]],
    issue: str,
    env: Any,
    controlled_player: Any,
) -> None:
    """Collecte les metriques comportementales d'un episode termine (§4.D.4).

    Appelee AVANT le prochain `env.reset()` : les shoot_stats sont reinitialisees au reset,
    donc elles refletent encore L'EPISODE QUI VIENT DE SE TERMINER.

    `controlled_player` peut valoir None si l'episode a ete tronque tres tot (backstop avec
    step_count=0) — dans ce cas on saute le profil pour cet episode.
    """
    if controlled_player is None:
        return
    player = int(controlled_player)
    gs = env.engine.game_state if hasattr(env, "engine") else {}

    # VP de l'agent a la fin de cet episode.
    vp_dict = gs.get("victory_points") or {}
    ep_vp = float(vp_dict[player]) if vp_dict else 0.0

    # Zones tenues par l'agent.
    controllers = gs.get("objective_controllers") or {}
    ep_zones = sum(1 for v in controllers.values() if v == player)

    # Stats de tir de l'agent (ai_shoot_*) — reinitialisees au prochain reset.
    shoot = env.get_shoot_stats() if hasattr(env, "get_shoot_stats") else {}
    ep_ai_shoot_opp = int(shoot["ai_shoot_opportunities"]) if shoot else 0
    ep_ai_shoot_act = int(shoot["ai_shoot_actions"]) if shoot else 0

    bucket = behavior_stats.setdefault(issue, {
        "vp": 0.0, "zones_held": 0.0,
        "ai_shoot_opportunities": 0, "ai_shoot_actions": 0, "count": 0,
    })
    bucket["vp"] += ep_vp
    bucket["zones_held"] += ep_zones
    bucket["ai_shoot_opportunities"] += ep_ai_shoot_opp
    bucket["ai_shoot_actions"] += ep_ai_shoot_act
    bucket["count"] += 1


def _episode_seed(base_seed: int, bot_name: str, scenario_idx: int, ep_idx: int) -> int:
    """Seed déterministe par (bot, scenario, épisode). Reproductible entre exécutions."""
    key = f"{bot_name}:{scenario_idx}:{ep_idx}"
    h = int(hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()[:8], 16) % (2**31)
    return (base_seed + h) % (2**31)


def _torch_compile_eval_extractor(model) -> None:
    """torch.compile(mode='reduce-overhead') sur le features_extractor CPU.

    Payé une fois dans _eval_worker_init ; amortit sur les 22 500 steps d'une task d'eval
    finale (150 épisodes × ~150 steps). Gain mesuré ~3× sur le seul extracteur.
    CPU uniquement : CUDA passe par _apply_torch_compile dans train.py.
    Aucun effet si le modèle n'a pas de features_extractor (architecture inattendue).
    """
    import torch

    device = getattr(model, "device", None)
    if device is None or str(device).startswith("cuda"):
        return
    policy = getattr(model, "policy", None)
    if policy is None:
        return
    extractor = getattr(policy, "features_extractor", None)
    if extractor is None:
        return
    extractor.forward = torch.compile(extractor.forward, mode="reduce-overhead")


def _warmup_eval_inference(model) -> None:
    """Forward pass factice pour déclencher la compilation torch avant le 1er épisode.

    Sans warmup la compilation se produit au 1er step du 1er épisode, qui semble bloquer
    ~60-120s — indiscernable d'un hang. Le warmup rend ce délai visible dans l'init du worker,
    au même titre que le chargement du modèle.
    """
    import gymnasium as gym

    obs_space = model.observation_space
    if isinstance(obs_space, gym.spaces.Dict):
        dummy_obs = {}
        for k, v in obs_space.spaces.items():
            if v.shape is None:
                raise RuntimeError(f"Espace d'observation '{k}' sans shape : warm-up impossible")
            dummy_obs[k] = np.zeros(v.shape, dtype=np.float32)
    else:
        dummy_obs = np.zeros(obs_space.shape, dtype=np.float32)
    action_masks = np.ones((1, model.action_space.n), dtype=bool)
    model.predict(dummy_obs, action_masks=action_masks, deterministic=True)


def _eval_worker_init(
    model_path: str,
    worker_model_device: str,
    vec_normalize_enabled: bool,
    vec_eval_enabled: bool,
    training_config_name: str,
    rewards_config_name: str,
    controlled_agent: str,
    base_agent_key: str,
    torch_compile_cpu: bool = False,
) -> None:
    """Appelé une fois au démarrage de chaque worker. Charge modèle + normalizer.

    Les stats VecNormalize viennent du MÊME `model_path` que la politique (V11 §0.35) : un
    worker ne peut pas normaliser avec les stats d'un autre modèle, par construction.
    Si `torch_compile_cpu` est True, le features_extractor est compilé avec
    torch.compile(mode='reduce-overhead') et un forward pass factice déclenche la compilation
    avant le 1er épisode.
    """
    global _worker_model, _worker_obs_normalizer
    from sb3_contrib import MaskablePPO

    _worker_model = MaskablePPO.load(model_path, device=worker_model_device)
    _worker_obs_normalizer = _build_eval_obs_normalizer_for_worker(
        _worker_model, model_path, vec_normalize_enabled, vec_eval_enabled
    )
    if torch_compile_cpu:
        _torch_compile_eval_extractor(_worker_model)
        _warmup_eval_inference(_worker_model)


def _eval_worker_task(
    task: Dict[str, Any],
    progress_callback: Optional[Callable[[], None]] = None,
) -> Dict[str, Any]:
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
    from sb3_contrib.common.maskable.utils import get_action_masks
    global _worker_model, _worker_obs_normalizer
    if _worker_model is None:
        raise RuntimeError("Worker not initialized (call _eval_worker_init before tasks)")

    import random

    config_params = task["config_params"]
    env = _create_eval_env(
        bot_name=task["bot_name"],
        bot_type=task["bot_type"],
        randomness_config=task["randomness_config"],
        scenario_file=task["scenario_file"],
        **{k: config_params[k] for k in [
            "training_config_name", "rewards_config_name", "controlled_agent",
            "base_agent_key", "debug_mode", "agent_seat_mode", "agent_seat_seed"
        ] if k in config_params},
    )

    # step_logger : uniquement en mode sérial (non picklable, ne pas ajouter en mode parallèle)
    if config_params.get("step_logger"):
        step_logger = config_params["step_logger"]
        env.engine.step_logger = step_logger
        # ADVERSAIRE RÉELLEMENT AFFRONTÉ, posé ICI et nulle part ailleurs : c'est le seul endroit
        # qui tient à la fois le journal et la tâche. `current_bot_name` portait le commentaire
        # « Set externally for bot-evaluation logging » depuis sa création sans qu'aucun code ne
        # l'assigne : le moteur retombait alors sur l'étiquette en dur « SelfPlay », écrite sur
        # 100 % des lignes — 600 épisodes contre six bots pondérés annoncés comme du self-play.
        step_logger.current_bot_name = task["bot_name"]

    wins, losses, draws = 0, 0, 0
    # Troncatures rencontrees PENDANT L'EVAL. Sans elles, une boucle du moteur qui ne se
    # reproduit qu'ici (`deterministic=True`, rosters du holdout) etait invisible : le moteur
    # pose `winner = -1`, donc elle se comptait en NUL et le bilan de fin de run affichait
    # « 0 troncature » — un feu vert faux, la classe de defaut que V11 §0.61 existe pour fermer.
    # Ces episodes ne sont PAS des episodes d'entrainement : ils ne touchent pas `episode_count`.
    truncations: List[Dict[str, Any]] = []
    # §4.D.4 : profil comportemental ventile par issue (win/draw/loss).
    # Structure : {issue: {metric: total, "count": n}}. Consomme dans l'agregation puis dans
    # metrics_tracker.log_behavioral_profile pour publier sous bot_eval/profile/<bot>/<metric>.
    behavior_stats: Dict[str, Dict[str, Any]] = {}
    # Faction jouee par l'agent, relevee A CHAQUE episode : un roster tire au sort peut
    # changer de faction d'un reset a l'autre au sein d'une meme tache.
    faction_stats: Dict[str, Dict[str, int]] = {}
    # Meme releve, meme raison, pour les deux ROSTERS de l'episode : une variante de liste est un
    # roster, et `agent_roster_ref: "training_random"` peut en changer a chaque reset.
    roster_stats: Dict[str, Dict[str, Dict[str, int]]] = {side: {} for side in ROSTER_SIDES}
    # Meme releve, meme raison, pour le SIEGE de l'episode (cf. SEAT_KEYS) : `agent_seat_mode`
    # peut valoir "random", auquel cas le siege est tire a chaque reset et la tache ne le connait
    # pas d'avance.
    seat_stats: Dict[str, Dict[str, int]] = {}

    def _count_episode(
        faction: str, roster_ids: Dict[str, str], seat: str, won: bool
    ) -> None:
        """Comptabilise UN episode dans les trois ventilations, gagne ou non.

        Un seul site d'ecriture, appele une fois par episode : le `total` et le `wins` d'une
        meme cle ne peuvent donc plus etre incrementes a deux endroits differents, ni sur deux
        seaux distincts. La forme precedente rendait ses seaux a l'appelant pour qu'il y ajoute
        `wins` plus loin — un aliasing a preserver a la main, alors que `winner` est connu avant
        l'appel.
        """
        for stats, key in [(faction_stats, faction), (seat_stats, seat)] + [
            (roster_stats[side], roster_ids[side]) for side in ROSTER_SIDES
        ]:
            bucket = stats.setdefault(key, {"wins": 0, "total": 0})
            bucket["total"] += 1
            bucket["wins"] += int(won)

    for ep_idx in range(task["n_episodes"]):
        ep_seed = _episode_seed(task["base_seed"], task["bot_name"], task["scenario_index"], ep_idx)
        random.seed(ep_seed)
        np.random.seed(ep_seed)
        obs, info = env.reset(seed=ep_seed)
        episode_faction = _agent_faction_from_engine(env.engine)
        episode_roster_ids = _episode_roster_ids(env.engine)
        # `require_key` sur l'`info` du RESET, et non `env.engine.config` : c'est
        # `BotControlledEnv._apply_episode_seat` qui tire le siege de l'episode et le publie ici
        # (meme cle que celle dont vivent les courbes `seat_aware/*` de l'entrainement). Un siege
        # absent est une anomalie d'environnement, pas un cas de jeu.
        episode_seat = _seat_key(require_key(info, "controlled_player"))
        done = False
        step_count = 0
        # BACKSTOP, et il ne peut PAS preempter le garde moteur : les deux compteurs n'ont pas
        # la meme unite. Un step gym vaut PLUSIEURS steps moteur (tour du bot, WAIT forces —
        # cf. `BotControlledEnv.step`), mesure a 1,3-1,4 sur ce depot, donc le compteur du
        # moteur atteint SON plafond avant que celui-ci n'atteigne le sien. Aucun ajustement
        # n'est donc necessaire, et en poser un serait du code pour un scenario qui n'existe pas.
        #
        # Ce backstop sert le cas ou le moteur n'a AUCUN plafond d'episode : duree illimitee
        # (Endless Duty), ou `_get_episode_step_limit` rend None. Le releve est garde pour le
        # diagnostic — savoir lequel des deux gardes etait arme change ce qu'on va chercher.
        max_steps_per_episode = int(require_key(task, "max_steps_per_episode"))
        engine_episode_limit = env.engine._get_episode_step_limit()
        while not done and step_count < max_steps_per_episode:
            model_obs = _worker_obs_normalizer(obs) if _worker_obs_normalizer else obs
            # `get_action_masks` de sb3_contrib = le chemin de PPO : il resout `action_masks` sur
            # le wrapper le PLUS EXTERNE, donc `BotControlledEnv.action_masks`, qui sert la decision
            # deja etablie. L'appel direct `env.engine.get_action_mask()` qui vivait ici POIGNARDAIT
            # ce depot : il fait avancer la phase de combat sur masque vide (cf. sa docstring), donc
            # il pouvait deplacer l'etat ENTRE deux `step()` — le step suivant consommait alors le
            # masque d'un etat revolu, sans que rien ne leve. Il ne gagnait rien au passage : cette
            # boucle n'utilisait pas le depot, elle ne faisait que le perimer.
            # L'avancement de phase reste assure : sans depot, `action_masks()` retombe sur
            # `engine.get_action_mask()` ; avec depot, le masque est non vide par precondition, donc
            # la boucle d'avancement n'aurait de toute facon rien fait.
            action_masks = np.asarray(get_action_masks(env), dtype=bool)
            if action_masks.ndim == 1:
                action_masks = action_masks.reshape(1, -1)
            if isinstance(model_obs, dict):
                # Obs Dict (MultiInputPolicy + CNN) : predict la gere nativement, ne pas aplatir.
                model_input = model_obs
            else:
                model_input = np.asarray(model_obs, dtype=np.float32)
                if model_input.ndim == 1:
                    model_input = model_input.reshape(1, -1)
            action, _ = _worker_model.predict(
                model_input,
                action_masks=action_masks,
                deterministic=task.get("deterministic", True),
            )
            action_scalar = int(np.asarray(action).flat[0])
            obs, reward, terminated, truncated, info = env.step(action_scalar)
            if truncated:
                # Le payload traverse la frontiere de process avec le resultat de la tache.
                truncations.append({
                    "reason": require_key(info, "truncation_reason"),
                    "bot_name": task["bot_name"],
                    "scenario_name": _scenario_name_from_task(task),
                    "episode_index": ep_idx,
                    "episode_seed": ep_seed,
                    "deterministic": bool(task.get("deterministic", True)),
                    **require_key(info, "truncation_debug"),
                })
            done = bool(terminated or truncated)
            step_count += 1
        if not done:
            # Le backstop a tire : le garde moteur ne pouvait pas (duree illimitee — il rend
            # None) ou n'a pas suffi. La partie n'a PAS fini : la compter en defaite (ce que
            # faisait `winner is None` en tombant dans le `else` plus bas) attribue au modele un
            # resultat qu'il n'a pas produit et efface l'incident. Nul + trace, comme le moteur.
            truncations.append({
                "reason": "eval_loop_cap",
                "bot_name": task["bot_name"],
                "scenario_name": _scenario_name_from_task(task),
                "episode_index": ep_idx,
                "episode_seed": ep_seed,
                "deterministic": bool(task.get("deterministic", True)),
                # `gym_*` et non `steps`/`step_limit` : ces deux cles-la portent des STEPS
                # MOTEUR dans les lignes `episode_steps_limit` du meme journal. Un step gym en
                # vaut plusieurs — les melanger sous un nom commun rend les lignes
                # incomparables, et c'est un journal fait pour etre relu.
                "gym_steps": step_count,
                "gym_step_limit": max_steps_per_episode,
                "engine_step_limit": engine_episode_limit,
            })
            draws += 1
            _count_episode(episode_faction, episode_roster_ids, episode_seat, won=False)
            # §4.D.4 : profil comportemental pour cet episode (truncate = draw).
            ep_controlled = info.get("controlled_player") if info else None
            _accumulate_behavior(behavior_stats, "draw", env, ep_controlled)
            if progress_callback is not None:
                progress_callback()
            continue
        # Pas de `info.get("winner")` : un `None` de repli n'est ni `controlled_player` ni -1,
        # l'episode serait compte en DEFAITE alors que la donnee manque. Le moteur ecrit
        # toujours la cle dans `W40KEngine.step`, partie terminee comme partie en cours :
        # son absence est une anomalie d'environnement, pas un cas de jeu.
        winner = require_key(info, "winner")
        controlled_player = require_key(info, "controlled_player")
        _count_episode(
            episode_faction, episode_roster_ids, episode_seat,
            won=(winner == controlled_player),
        )
        if winner == controlled_player:
            wins += 1
            ep_issue = "win"
        elif winner == DRAW_WINNER:
            draws += 1
            ep_issue = "draw"
        else:
            losses += 1
            ep_issue = "loss"
        # §4.D.4 : profil comportemental pour cet episode.
        _accumulate_behavior(behavior_stats, ep_issue, env, controlled_player)
        if progress_callback is not None:
            progress_callback()

    env.close()
    return {
        "wins": wins, "losses": losses, "draws": draws,
        "truncations": truncations,
        "failed_episodes": 0,
        "bot_name": task["bot_name"],
        "scenario_name": task["scenario_name"],
        "faction_stats": faction_stats,
        "seat_stats": seat_stats,
        "roster_stats": roster_stats,
        "behavior_stats": behavior_stats,
    }


def _failed_task_result(
    task: Dict[str, Any],
    scenario_name: str,
    **cause: Any,
) -> Dict[str, Any]:
    """
    Resultat d'une tache d'evaluation qui n'a produit aucun episode exploitable.

    FABRIQUE UNIQUE : ce dict etait construit a l'identique sur QUATRE sites (les deux
    branches de _get_result_with_timeout et les deux de _collect_parallel_results_with_timeouts).
    Chaque nouvelle cle d'agregat devait etre ajoutee aux quatre — `faction_stats` ne l'a
    ete que sur deux, et le premier timeout venu tuait alors le run sur un `require_key`,
    en contradiction avec la regle « un TIMEOUT n'est pas un bug, le training CONTINUE »
    (BotEvaluationCallback._apply_eval_results). Un seul site desormais.

    `cause` porte `timeout=True` ou `error=<str>` : les deux sont distingues en aval
    (V11 §0.27, crash moteur vs lenteur mesuree).
    """
    return {
        "wins": 0,
        "losses": 0,
        "draws": 0,
        # Cle PRESENTE et vide, jamais absente : meme regle que `faction_stats` ci-dessous.
        "truncations": [],
        "failed_episodes": int(require_key(task, "n_episodes")),
        "bot_name": require_key(task, "bot_name"),
        "scenario_name": scenario_name,
        # Aucun episode joue : la tache ne contribue a aucune faction. Cle PRESENTE et vide,
        # jamais absente — _compute_faction_scores la lit par require_key.
        "faction_stats": {},
        # Meme regle pour le siege : `_seat_bot_tally` lit `seat_stats` par require_key.
        "seat_stats": {},
        # Meme regle, et c'est TOUT LE POINT de cette fabrique unique : `_roster_bot_tally` lit
        # `roster_stats[side]` par require_key, donc les deux cotes doivent exister meme vides,
        # sans quoi le premier timeout tuerait le run.
        "roster_stats": {side: {} for side in ROSTER_SIDES},
        # Aucun episode joue : aucun profil comportemental a agréger (§4.D.4).
        "behavior_stats": {},
        **cause,
    }


def _scenario_name_from_task(task: Dict[str, Any]) -> str:
    """Nom de scenario d'une tache, y compris quand elle n'a pas pu s'executer."""
    declared = task.get("scenario_name")
    if declared:
        return str(declared)
    return os.path.basename(require_key(task, "scenario_file")).replace(".json", "")


def _get_result_with_timeout(
    future,
    task: Dict[str, Any],
    timeout_seconds: int = 300,
) -> Dict[str, Any]:
    """Récupère le résultat d'une tâche avec timeout. Retourne dict avec timeout/error si échec."""
    bot_name = task["bot_name"]
    scenario_name = _scenario_name_from_task(task)
    try:
        return future.result(timeout=timeout_seconds)
    except TimeoutError:
        import sys as _sys
        _sys.stderr.write(f"BOT_EVAL_TIMEOUT bot={bot_name} scenario={scenario_name} n_episodes={task.get('n_episodes')} timeout={timeout_seconds}s\n")
        _sys.stderr.flush()
        logging.warning(f"Eval task timeout: bot={bot_name} scenario={scenario_name}")
        return _failed_task_result(task, scenario_name, timeout=True)
    except Exception as e:
        logging.exception(f"Eval task failed: bot={bot_name} scenario={scenario_name} error={e}")
        return _failed_task_result(task, scenario_name, error=str(e))


def _force_terminate_process_pool(pool: ProcessPoolExecutor) -> None:
    """
    Force-stop worker processes to avoid hangs when a task exceeds timeout.

    This uses ProcessPoolExecutor internals intentionally as a last-resort safety
    mechanism for robust evaluation runs.
    """
    processes = getattr(pool, "_processes", None)
    if not isinstance(processes, dict):
        return
    for process in processes.values():
        if process is None:
            continue
        if process.is_alive():
            process.terminate()
    for process in processes.values():
        if process is None:
            continue
        process.join(timeout=1.0)


def _collect_parallel_results_with_timeouts(
    pool: ProcessPoolExecutor,
    tasks: List[Dict[str, Any]],
    task_timeout_seconds: int,
    max_in_flight: int,
    on_result: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[Dict[str, Any]]:
    """
    Collect parallel eval results with per-task deadline enforcement.

    Unlike as_completed(), this loop never blocks indefinitely on a hung worker.
    If any running task exceeds timeout, the pool is force-terminated and all
    remaining tasks are marked as failed timeouts.

    Les tasks sont soumises AU FIL DE L'EAU, au plus `max_in_flight` (= `bot_eval_n_workers`)
    a la fois : il n'existe donc jamais de task en attente dans le pool, et l'instant de
    soumission EST l'instant de depart. C'est ce qui rend `task_start_times` exact, et donc
    `bot_eval_task_timeout_seconds` fidele a son nom. Tout soumettre d'un coup en faisait une
    deadline GLOBALE sur l'evaluation entiere : a 24 tasks sur 4 workers, celles de la 6e vague
    avaient consomme 5 durees de task avant de commencer, et UNE seule qui deborde
    force-termine le pool, donc annule la mesure. Se rabattre sur `future.running()` ne suffit
    pas : CPython arme RUNNING quand le future part dans la `call_queue` du pool, pas quand un
    worker le prend (mesure : 4 futures RUNNING pour 2 workers).
    """
    if task_timeout_seconds <= 0:
        raise ValueError(
            f"task_timeout_seconds must be > 0 for parallel collection (got {task_timeout_seconds})"
        )
    if max_in_flight <= 0:
        raise ValueError(
            f"max_in_flight must be > 0 for parallel collection (got {max_in_flight})"
        )

    queued = deque(tasks)
    future_to_task: Dict[Any, Dict[str, Any]] = {}
    task_start_times: Dict[Any, float] = {}
    pending: set = set()
    results_list: List[Dict[str, Any]] = []
    must_abort_pool = False

    while queued or pending:
        # Un worker libre <=> une soumission : le task part maintenant, il demarre maintenant.
        while queued and len(pending) < max_in_flight:
            task = queued.popleft()
            future = pool.submit(_eval_worker_task, task)
            future_to_task[future] = task
            task_start_times[future] = time.monotonic()
            pending.add(future)

        done, not_done = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
        now = time.monotonic()

        # Collect completed tasks.
        for future in done:
            task = require_key(future_to_task, future)
            # Already done -> timeout=0 is safe and non-blocking.
            result = _get_result_with_timeout(future, task, timeout_seconds=0)
            results_list.append(result)
            if on_result is not None:
                on_result(result)

        # Enforce per-task timeout on still-running tasks.
        timed_out_futures: List[Any] = []
        for future in not_done:
            if now - require_key(task_start_times, future) >= task_timeout_seconds:
                task = require_key(future_to_task, future)
                timeout_result = _failed_task_result(task, _scenario_name_from_task(task), timeout=True)
                results_list.append(timeout_result)
                if on_result is not None:
                    on_result(timeout_result)
                timed_out_futures.append(future)
                must_abort_pool = True

        # Remove handled futures from pending.
        for future in done:
            pending.discard(future)
        for future in timed_out_futures:
            pending.discard(future)

        # A single timeout indicates potential hung worker process.
        # Abort the whole pool to guarantee we don't hang forever.
        if must_abort_pool:
            break

    if must_abort_pool:
        _force_terminate_process_pool(pool)
        # Les tasks encore en vol ET celles jamais soumises : l'evaluation est invalidee en
        # bloc, l'appelant compte des episodes manquants et leve. Les taire donnerait un score
        # calcule sur un denominateur tronque.
        abandoned = [require_key(future_to_task, f) for f in pending] + list(queued)
        for task in abandoned:
            abandoned_result = _failed_task_result(task, _scenario_name_from_task(task), timeout=True)
            results_list.append(abandoned_result)
            if on_result is not None:
                on_result(abandoned_result)
    return results_list


def _render_scenario_ranking(scenario_scores, total_failed_episodes):
    """Lignes a imprimer pour le classement des scenarios (V11 §0.16(a)).

    Quand des episodes ont echoue, les `combined`/`worst_bot_score` par scenario sont
    calcules sur un denominateur TRONQUE (les episodes plantes sont retires du
    denominateur par `_get_result_with_timeout`). L'appelant eval-only leve alors sur
    `total_failed_episodes > 0` ; afficher un classement net juste avant ce raise
    presenterait une mesure invalide comme fiable. On supprime donc le ranking et on
    signale explicitement la non-fiabilite plutot que de masquer le probleme.

    Retourne une liste de lignes (vide si aucun scenario n'a ete score).
    """
    if not scenario_scores:
        return []
    if int(total_failed_episodes) > 0:
        return [
            f"⚠️  Scenario ranking SUPPRIME : evaluation NON FIABLE "
            f"({int(total_failed_episodes)} episode(s) echoue(s)). Les scores par "
            f"scenario sont calcules sur un echantillon tronque — ne pas les reporter."
        ]
    ranking = sorted(
        scenario_scores.items(),
        key=lambda item: item[1]["combined"],
        reverse=True,
    )
    lines = ["🏁 Scenario ranking (combined):"]
    for name, values in ranking:
        lines.append(
            f"  - {name}: combined={values['combined']:.3f} "
            f"| worst_bot_score={values['worst_bot_score']:.3f}"
        )
    return lines


def _strip_phase_suffix(agent_key: str) -> str:
    for suffix in ('_phase1', '_phase2', '_phase3', '_phase4'):
        if agent_key.endswith(suffix):
            return agent_key[:-len(suffix)]
    return agent_key


def evaluate_against_bots(model, training_config_name, rewards_config_name, n_episodes,
                         controlled_agent=None, show_progress=False, deterministic=True,
                         step_logger=None, debug_mode=False, eval_progress_label: Optional[str] = None,
                         show_summary: bool = True, eval_progress_prefix: Optional[str] = None,
                         scenario_pool: str = "training", model_path: Optional[str] = None,
                         line_length_state: Optional[Dict[str, Any]] = None,
                         scenario_list_override: Optional[List[str]] = None,
                         materialize_eval_refs: bool = True,
                         n_workers_override: Optional[int] = None):
    """
    Standalone bot evaluation function - single source of truth for all bot testing.

    Args:
        model: Trained model to evaluate
        training_config_name: Name of training config to use (e.g., "phase1", "default")
        n_episodes: Number of episodes per bot (will be split across all available scenarios)
        controlled_agent: Agent identifier (None for player 0, otherwise player 1)
        show_progress: Show progress bar with time estimates
        deterministic: Use deterministic policy
        step_logger: Optional StepLogger instance for detailed action logging
        eval_progress_label: Optional suffix displayed on evaluation progress line
        show_summary: Print diagnostic and scenario ranking summary at end
        eval_progress_prefix: Optional fixed prefix shown before eval progress (e.g., phase progress)
        line_length_state: Optional dict partage avec la barre d'entrainement (ProgressWriter) :
                           chaque barre y publie la longueur de la ligne affichee et y relit celle
                           de l'autre, pour reprendre la main sans laisser trainer sa queue

    Returns:
        Dict with keys: 'random', 'greedy', 'defensive', 'combined',
                       'random_wins', 'greedy_wins', 'defensive_wins'
    """
    from config_loader import get_config_loader

    # Import evaluation bots for testing
    eval_wall_start = time.time()
    # Import inconditionnel. Un try/except ImportError posait ici un drapeau
    # EVALUATION_BOTS_AVAILABLE, suivi d'un `if not ...: return {}` — troisieme copie du meme
    # motif (les deux autres sont parties de ai/training_callbacks.py et ai/train.py).
    # ai/evaluation_bots.py est dans le depot, ce n'est pas une dependance optionnelle, et il ne
    # cree aucun cycle. Le drapeau valait toujours True ; le repli `return {}` aurait rendu une
    # evaluation vide au lieu de lever, ce qui est exactement ce qu'on ne veut pas ici.
    from ai.evaluation_bots import (
        RandomBot, GreedyBot, DefensiveBot, ControlBot, AdaptiveBot,
    )

    # Import scenario utilities from training_utils
    from ai.training_utils import get_scenario_list_for_phase

    config = get_config_loader()
    global_config = config.load_config("config", force_reload=False)
    progress_bar_cfg = require_key(global_config, "progress_bar")
    bot_eval_bar_length = require_key(progress_bar_cfg, "bot_eval_width")
    if not isinstance(bot_eval_bar_length, int) or isinstance(bot_eval_bar_length, bool):
        raise TypeError(
            "config.progress_bar.bot_eval_width must be an integer "
            f"(got {type(bot_eval_bar_length).__name__})"
        )
    if bot_eval_bar_length <= 0:
        raise ValueError(
            f"config.progress_bar.bot_eval_width must be > 0 (got {bot_eval_bar_length})"
        )

    controlled_agent = require_present(controlled_agent, "controlled_agent")
    base_agent_key: str = _strip_phase_suffix(controlled_agent)

    training_cfg = config.load_agent_training_config(base_agent_key, training_config_name)
    agent_seat_mode = require_key(training_cfg, "agent_seat_mode")
    if agent_seat_mode not in {"p1", "p2", "random"}:
        raise ValueError(
            f"training_config.agent_seat_mode must be one of 'p1', 'p2', 'random' "
            f"(got {agent_seat_mode!r})"
        )
    agent_seat_seed = None
    if agent_seat_mode == "random":
        agent_seat_seed = _resolve_seat_seed(training_cfg)
    vec_norm_cfg = require_key(training_cfg, "vec_normalize")
    if not isinstance(vec_norm_cfg, dict):
        raise TypeError(f"vec_normalize must be a dict (got {type(vec_norm_cfg).__name__})")
    vec_normalize_enabled = bool(require_key(vec_norm_cfg, "enabled"))

    vec_norm_eval_cfg = require_key(training_cfg, "vec_normalize_eval")
    if not isinstance(vec_norm_eval_cfg, dict):
        raise TypeError(f"vec_normalize_eval must be a dict (got {type(vec_norm_eval_cfg).__name__})")
    vec_eval_enabled = bool(require_key(vec_norm_eval_cfg, "enabled"))
    vec_eval_training = require_key(vec_norm_eval_cfg, "training")
    if not isinstance(vec_eval_training, bool):
        raise TypeError(
            f"vec_normalize_eval.training must be boolean (got {type(vec_eval_training).__name__})"
        )
    vec_eval_norm_reward = require_key(vec_norm_eval_cfg, "norm_reward")
    if not isinstance(vec_eval_norm_reward, bool):
        raise TypeError(
            f"vec_normalize_eval.norm_reward must be boolean (got {type(vec_eval_norm_reward).__name__})"
        )
    if vec_eval_training:
        raise ValueError("vec_normalize_eval.training must be false for bot evaluation")
    if vec_eval_norm_reward:
        raise ValueError("vec_normalize_eval.norm_reward must be false for bot evaluation")
    if vec_eval_enabled and not vec_normalize_enabled:
        raise ValueError(
            "vec_normalize_eval.enabled is true but vec_normalize.enabled is false"
        )

    # model_path optionnel : permet d'évaluer un snapshot explicite (mode async).
    # Si absent, on sauvegarde un snapshot temporaire du modèle courant.
    _temp_model_path = None
    if model_path:
        effective_model_path = model_path
        if not os.path.exists(effective_model_path):
            raise FileNotFoundError(f"Evaluation snapshot not found: {effective_model_path}")
    else:
        # Pendant l'entraînement, le fichier canonique (model_agent.zip) n'est mis à jour qu'à la fin.
        # On snapshot donc le modèle courant pour éviter d'évaluer un artefact obsolète.
        import tempfile
        _fd, effective_model_path = tempfile.mkstemp(suffix=".zip")
        os.close(_fd)
        model.save(effective_model_path)
        if vec_normalize_enabled:
            from ai.vec_normalize_utils import save_vec_normalize

            if not save_vec_normalize(model.get_env(), effective_model_path):
                raise RuntimeError(
                    "VecNormalize est active mais l'env du modele n'est pas enveloppe par "
                    "VecNormalize : impossible de sauver les stats du snapshot d'evaluation. "
                    "Evaluer sans stats normaliserait avec celles d'un AUTRE modele (V11 §0.35)."
                )
        _temp_model_path = effective_model_path

    # ⚠️ V11 §0.35 — les stats de normalisation sont celles du modele EVALUE, jamais celles du
    # modele canonique. Il n'existe plus de `vec_model_path` distinct : chaque worker derive le
    # pkl du zip qu'il charge (`_eval_worker_init` → `get_vec_normalize_path(model_path)`).
    # L'ancien chemin separe valait `<models_root>/<agent>/model_<agent>.zip` en dur alors que
    # les workers chargeaient un SNAPSHOT en mode async : on evaluait un modele avec la
    # normalisation d'un AUTRE, sans lever tant qu'un pkl trainait dans le dossier — jusqu'a ce
    # qu'une rotation d'artefacts le supprime et arrete un run de 5 h 30 au marqueur 24 000.

    # Le try commence DES la preparation : toute levee entre le snapshot tempfile et la
    # boucle des workers (config incomplete, scenario absent...) passait AVANT l'ancien
    # try/finally et fuyait un zip+pkl orphelin dans /tmp a chaque tentative.
    try:
        bot_eval_cfg = _load_bot_eval_params(config, base_agent_key, training_config_name)
        eval_weights = bot_eval_cfg["weights"]
        eval_randomness = bot_eval_cfg["randomness"]
        # V11 §10.5 : ce dict ne recopiait que greedy/defensive/control — aggressive_smart,
        # adaptive et tactical retombaient SILENCIEUSEMENT sur 0.15 a la construction du bot,
        # rendant leur `bot_eval_randomness` de config lettre morte. On transmet la config
        # entiere, et l'absence d'une entree est une erreur, pas un defaut.
        randomness_config = dict(eval_randomness)

        active_bot_names = tuple(eval_weights.keys())

        missing_randomness = [name for name in active_bot_names if name not in randomness_config]
        if missing_randomness:
            raise KeyError(
                "callback_params.bot_eval_randomness manque une entree pour les bots ponderes "
                f"en evaluation : {sorted(missing_randomness)}. Renseigner une valeur explicite "
                "(aucun defaut n'est applique)."
            )

        if scenario_list_override is not None:
            if not isinstance(scenario_list_override, list):
                raise TypeError(
                    f"scenario_list_override must be list or None (got {type(scenario_list_override).__name__})"
                )
            if len(scenario_list_override) == 0:
                raise ValueError("scenario_list_override cannot be empty")
            scenario_list = [str(path) for path in scenario_list_override]
            for scenario_path in scenario_list:
                if not os.path.isfile(scenario_path):
                    raise FileNotFoundError(f"scenario_list_override contains missing file: {scenario_path}")
        else:
            if scenario_pool not in ("training", "holdout"):
                raise ValueError(
                    f"scenario_pool must be 'training' or 'holdout' (got {scenario_pool!r})"
                )

            scenario_list = get_scenario_list_for_phase(
                config,
                base_agent_key,
                training_config_name,
                scenario_type=scenario_pool
            )

            if len(scenario_list) == 0:
                expected_dir = os.path.join(
                    config.config_dir,
                    "agents",
                    base_agent_key,
                    "scenarios",
                    scenario_pool
                )
                raise FileNotFoundError(
                    f"No {scenario_pool} scenarios found for agent '{base_agent_key}'. "
                    f"Expected files in: {expected_dir} with naming '{base_agent_key}_*.json'."
                )
            scenario_list = _filter_scenarios_from_config(training_cfg, scenario_list, base_agent_key)

        if n_episodes <= 0:
            raise ValueError("n_episodes must be > 0 for bot evaluation")
        # Calculate episodes per scenario (distribute exactly, remainder goes to first scenarios)
        episodes_per_scenario = n_episodes // len(scenario_list)
        extra_episodes = n_episodes % len(scenario_list)

        callback_params = require_key(training_cfg, "callback_params")
        sampling_cfg = training_cfg.get("scenario_sampling")
        eval_wall_refs: List[str] = []
        eval_ref_strict = False
        if scenario_pool == "holdout" and materialize_eval_refs:
            if not isinstance(sampling_cfg, dict):
                raise TypeError(
                    "scenario_sampling must be an object in training config for holdout evaluation"
                )
            raw_eval_wall_refs = require_key(sampling_cfg, "eval_wall_refs")
            raw_eval_ref_strict = sampling_cfg.get("eval_ref_strict", True)
            if not isinstance(raw_eval_ref_strict, bool):
                raise TypeError(
                    "scenario_sampling.eval_ref_strict must be boolean "
                    f"(got {type(raw_eval_ref_strict).__name__})"
                )
            eval_ref_strict = raw_eval_ref_strict
            if not isinstance(raw_eval_wall_refs, list) or len(raw_eval_wall_refs) == 0:
                raise ValueError(
                    "scenario_sampling.eval_wall_refs must be a non-empty list for holdout evaluation"
                )
            for raw_ref in raw_eval_wall_refs:
                if not isinstance(raw_ref, str) or not raw_ref.strip():
                    raise ValueError(f"Invalid wall ref in scenario_sampling.eval_wall_refs: {raw_ref!r}")
                eval_wall_refs.append(raw_ref.strip())

        worker_params = validate_bot_eval_worker_params(callback_params)
        use_subprocess = worker_params["use_subprocess"]
        torch_compile_cpu = bool(callback_params.get("bot_eval_torch_compile_cpu", False))
        worker_model_device_raw = require_key(callback_params, "bot_eval_worker_device")
        worker_model_device = str(worker_model_device_raw).strip().lower()
        if worker_model_device not in {"cpu", "auto"}:
            raise ValueError(
                "callback_params.bot_eval_worker_device must be either 'cpu' or 'auto' "
                f"(got {worker_model_device!r})"
            )
        if step_logger and step_logger.enabled:
            use_subprocess = False
        if debug_mode:
            use_subprocess = False

        config_params = {
            "training_config_name": training_config_name,
            "rewards_config_name": rewards_config_name,
            "controlled_agent": controlled_agent,
            "base_agent_key": base_agent_key,
            "vec_normalize_enabled": vec_normalize_enabled,
            "debug_mode": debug_mode,
            "agent_seat_mode": agent_seat_mode,
            "agent_seat_seed": agent_seat_seed,
        }
        if not use_subprocess and step_logger and step_logger.enabled:
            config_params["step_logger"] = step_logger

        base_seed = 42
        task_timeout_seconds = worker_params["task_timeout_seconds"]
        n_workers = worker_params["n_workers"]
        if n_workers_override is not None:
            if isinstance(n_workers_override, bool) or not isinstance(n_workers_override, int) or n_workers_override <= 0:
                raise ValueError(
                    f"n_workers_override must be a positive integer (got {n_workers_override!r})"
                )
            n_workers = n_workers_override

        from config_loader import get_max_turns

        tasks: List[Dict[str, Any]] = []
        for bot_name in active_bot_names:
            for scenario_index, scenario_file in enumerate(scenario_list):
                scenario_name = _scenario_name_from_file(base_agent_key, scenario_file)
                task_scenario_file = scenario_file
                if scenario_pool == "holdout" and eval_ref_strict and materialize_eval_refs:
                    wall_ref = eval_wall_refs[(scenario_index + len(bot_name)) % len(eval_wall_refs)]
                    task_scenario_file = _materialize_eval_scenario_refs(
                        scenario_path=scenario_file,
                        wall_ref=wall_ref,
                    )
                episodes_for_scenario = episodes_per_scenario + (1 if scenario_index < extra_episodes else 0)
                if episodes_for_scenario <= 0:
                    continue
                tasks.append({
                    "bot_name": bot_name,
                    "bot_type": bot_name,
                    "randomness_config": randomness_config,
                    "scenario_file": task_scenario_file,
                    "scenario_name": scenario_name,
                    "n_episodes": episodes_for_scenario,
                    "base_seed": base_seed,
                    "scenario_index": scenario_index,
                    "deterministic": deterministic,
                    "config_params": config_params,
                    "max_steps_per_episode": int(get_max_turns()) * 400,  # duree de bataille = game_rules.max_turns
                })

        initargs = (
            effective_model_path,
            worker_model_device,
            vec_normalize_enabled,
            vec_eval_enabled,
            training_config_name,
            rewards_config_name,
            controlled_agent,
            base_agent_key,
            torch_compile_cpu,
        )

        total_episodes = len(active_bot_names) * n_episodes
        start_time = time.time() if show_progress else None
        progress_writer = ProgressWriter(line_length_state)

        def _print_progress(completed_ep: int, total_ep: int) -> None:
            """Print progress bar during eval (overwrites line)."""
            if not show_progress or start_time is None:
                return
            progress_pct = (completed_ep / total_ep) * 100 if total_ep > 0 else 0
            bar_length = bot_eval_bar_length
            filled = int(bar_length * completed_ep / total_ep) if total_ep > 0 else 0
            bar = '█' * filled + '░' * (bar_length - filled)
            elapsed = time.time() - start_time
            elapsed_str = _format_elapsed(elapsed)
            speed_str = f"{completed_ep/elapsed:.2f}ep/s" if elapsed > 0 and completed_ep > 0 else "0.00ep/s"
            if eval_progress_prefix and eval_progress_label:
                line = f"{eval_progress_prefix}{eval_progress_label}: {progress_pct:3.0f}% {bar} {completed_ep}/{total_ep} [{elapsed_str}, {speed_str}]"
            elif eval_progress_label:
                line = f"{eval_progress_label}: {progress_pct:3.0f}% {bar} {completed_ep}/{total_ep} [{elapsed_str}, {speed_str}]"
            else:
                line = f"{progress_pct:3.0f}% {bar} {completed_ep}/{total_ep} [{elapsed_str}, {speed_str}]"
            progress_writer.write(line)

        if show_progress:
            _print_progress(0, total_episodes)

        if use_subprocess and n_workers > 1:
            ctx = mp.get_context("spawn")
            _parallel_completed = [0]

            def _on_task_result(result: Dict[str, Any]) -> None:
                _parallel_completed[0] += (
                    int(require_key(result, "wins"))
                    + int(require_key(result, "losses"))
                    + int(require_key(result, "draws"))
                    + int(require_key(result, "failed_episodes"))
                )
                _print_progress(min(_parallel_completed[0], total_episodes), total_episodes)

            with ProcessPoolExecutor(
                max_workers=n_workers,
                mp_context=ctx,
                initializer=_eval_worker_init,
                initargs=initargs,
            ) as pool:
                results_list = _collect_parallel_results_with_timeouts(
                    pool=pool,
                    tasks=tasks,
                    task_timeout_seconds=int(task_timeout_seconds),
                    max_in_flight=n_workers,
                    on_result=_on_task_result if show_progress else None,
                )
        else:
            _eval_worker_init(*initargs)
            results_list = []
            completed_episodes = 0
            def _on_episode_completed() -> None:
                nonlocal completed_episodes
                completed_episodes += 1
                _print_progress(completed_episodes, total_episodes)
            for t in tasks:
                result = _eval_worker_task(t, progress_callback=_on_episode_completed)
                results_list.append(result)
    finally:
        if _temp_model_path:
            from ai.vec_normalize_utils import get_vec_normalize_path

            _temp_vec_path = get_vec_normalize_path(_temp_model_path)
            if os.path.exists(_temp_vec_path):
                os.remove(_temp_vec_path)
        if _temp_model_path and os.path.exists(_temp_model_path):
            try:
                os.remove(_temp_model_path)
            except OSError:
                pass

    # Agrégation (section 2.9) — passe unique sur results_list.
    results: Dict[str, Any] = {}
    by_bot: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in results_list:
        bn = r.get("bot_name")
        if bn is not None:
            by_bot[bn].append(r)
    for bn in active_bot_names:
        bot_results = by_bot[bn]
        wins = sum(r["wins"] for r in bot_results)
        losses = sum(r["losses"] for r in bot_results)
        draws = sum(r["draws"] for r in bot_results)
        total = wins + losses + draws
        results[bn] = wins / max(1, total)
        results[f"{bn}_wins"] = wins
        results[f"{bn}_losses"] = losses
        results[f"{bn}_draws"] = draws
    # §4.D.4 : profil comportemental agrege par bot, ventile par issue (win/draw/loss).
    # Chaque tache produit un {issue: {metric: total, "count": n}} pour son bot ;
    # on additionne les totaux ici, la moyenne reste calculee en aval (metrics_tracker).
    behavioral_profile: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for bn in active_bot_names:
        merged: Dict[str, Dict[str, Any]] = {}
        for r in by_bot[bn]:
            for issue, bucket in (r.get("behavior_stats") or {}).items():
                m = merged.setdefault(issue, {
                    "vp": 0.0, "zones_held": 0.0,
                    "ai_shoot_opportunities": 0, "ai_shoot_actions": 0, "count": 0,
                })
                for k in ("vp", "zones_held", "ai_shoot_opportunities", "ai_shoot_actions", "count"):
                    m[k] += bucket[k]
        if merged:
            behavioral_profile[bn] = merged
    results["behavioral_profile"] = behavioral_profile

    # Troncatures rencontrees pendant CETTE evaluation, toutes taches confondues. Le moteur pose
    # `winner = -1` sur une troncature, donc sans cette remontee elle se comptait en NUL et
    # n'existait nulle part ailleurs (V11 §0.61).
    results["truncations"] = [
        entry for r in results_list for entry in require_key(r, "truncations")
    ]

    scenario_bot_stats: Dict[str, Dict[str, Dict[str, float]]] = {}
    for r in results_list:
        sn, bn = r.get("scenario_name"), r.get("bot_name")
        if sn and bn:
            if sn not in scenario_bot_stats:
                scenario_bot_stats[sn] = {}
            total = r["wins"] + r["losses"] + r["draws"]
            scenario_bot_stats[sn][bn] = {
                "win_rate": r["wins"] / max(1, total),
                "wins": r["wins"],
                "losses": r["losses"],
                "draws": r["draws"],
            }

    # V11 §0.27 : deux causes d'echec sont agregees separement car elles n'ont PAS la meme
    # consequence. `timeout` = la tache a depasse son deadline (LENTEUR mesuree : parties
    # degenerees x cout geodesique), le moteur est sain. `error` = exception dans le worker
    # (crash moteur). Un crash doit arreter le training ; une lenteur doit invalider la MESURE
    # sans tuer un run de 36 h. Les deux restent comptes dans total_failed_episodes, qui garde
    # sa semantique historique « la mesure n'est pas fiable ».
    total_failed_episodes = sum(int(require_key(r, "failed_episodes")) for r in results_list)
    total_timeout_episodes = sum(
        int(require_key(r, "failed_episodes")) for r in results_list if r.get("timeout")
    )
    total_error_episodes = total_failed_episodes - total_timeout_episodes
    results["total_failed_episodes"] = total_failed_episodes
    results["total_timeout_episodes"] = total_timeout_episodes
    results["total_error_episodes"] = total_error_episodes
    results["eval_duration_seconds"] = float(time.time() - eval_wall_start)
    # Denominateur HONNETE de la duree : les episodes reellement joues, hors abandons. Sans lui,
    # la seule facon de connaitre le cout d'une evaluation etait de multiplier `bot_eval_*` par
    # le nombre de bots actifs — un calcul de tete que rien ne verifie.
    results["total_episodes_played"] = sum(
        int(require_key(r, "wins")) + int(require_key(r, "losses")) + int(require_key(r, "draws"))
        for r in results_list
    )

    results["combined"] = sum(
        eval_weights[bn] * results[bn] for bn in active_bot_names
    )
    results["scenario_bot_stats"] = scenario_bot_stats

    # Ventilation par faction jouee par l'agent. `roster_gap` n'est produit QUE si les deux
    # factions de ROSTER_GAP_FACTIONS sont toutes deux representees : un pool mono-faction,
    # ou melangeant d'autres factions, n'a pas d'ecart a publier — la cle reste alors absente
    # et le callback ne trace pas de courbe, plutot que d'en tracer une qui vaudrait un score
    # absolu deguise en ecart.
    # UN seul comptage croise faction x bot, deux derivations : l'agregat pondere ci-dessous et
    # le croisement brut (V11 §0.55 / §10.6). Le croisement porte `tactical`, dont le poids nul
    # l'efface de `faction_scores` sans l'effacer d'ici — c'est justement le holdout qu'on veut
    # lire par roster.
    faction_tally = _faction_bot_tally(results_list, active_bot_names)
    faction_scores = _compute_faction_scores(faction_tally, active_bot_names, eval_weights)
    results["faction_scores"] = faction_scores
    results["faction_bot_win_rates"] = _compute_bot_win_rates(faction_tally)
    if all(faction in faction_scores for faction in ROSTER_GAP_FACTIONS):
        results["roster_gap"] = (
            faction_scores[ROSTER_GAP_FACTIONS[0]] - faction_scores[ROSTER_GAP_FACTIONS[1]]
        )

    # Ventilation par SIEGE (cf. SEAT_KEYS). `results["combined"]` melange les deux, donc le
    # chiffre qui selectionne le modele livre ne voyait pas l'ecart entre eux — 12 points sur le
    # run du 2026-08-12, cote entrainement, sans aucune contrepartie en evaluation.
    # `_compute_faction_scores` est AGNOSTIQUE a la cle du tally (elle ne fait que ponderer par bot
    # et ecarter les cles a couverture partielle) : l'appeler ici donne un `combined` par siege
    # directement comparable a `results["combined"]`, ce qu'un win-rate brut ne serait pas.
    seat_tally = _seat_bot_tally(results_list, active_bot_names)
    seat_scores = _compute_faction_scores(seat_tally, active_bot_names, eval_weights)
    results["seat_scores"] = seat_scores
    results["seat_bot_win_rates"] = _compute_bot_win_rates(seat_tally)
    # L'ECART, publie seulement si les deux sieges sont couverts : un run en `agent_seat_mode: p1`
    # n'a pas d'ecart a montrer, et en publier un vaudrait un score absolu deguise en ecart —
    # meme regle que `roster_gap` ci-dessus.
    if all(seat in seat_scores for seat in SEAT_KEYS):
        results["seat_gap"] = seat_scores[SEAT_KEYS[0]] - seat_scores[SEAT_KEYS[1]]

    # Ventilation par ROSTER, des DEUX cotes (chantier 04c). `faction_bot_win_rates` confond
    # deux variantes d'une meme faction — typiquement « avec » et « sans » reserves
    # strategiques — et c'est exactement l'ecart qu'on veut lire.
    # Les deux cotes repondent a deux questions DIFFERENTES, et les melanger les rendrait
    # illisibles : le roster de l'AGENT dit s'il sait UTILISER ses reserves, celui de
    # l'ADVERSAIRE s'il sait ENCAISSER une arrivee.
    # Meme `results_list`, meme cle `roster_stats`, meme forme de tally que la faction : la
    # somme ponderee par roster retombe donc sur le win-rate global par construction, ce n'est
    # pas une coincidence a re-verifier a chaque changement.
    for side in ROSTER_SIDES:
        results[f"{side}_roster_bot_win_rates"] = _compute_bot_win_rates(
            _roster_bot_tally(results_list, active_bot_names, side)
        )

    # V11 §10.5 : le holdout (tactical) est MESURE et affiche, mais EXCLU du worst_bot_score,
    # qui alimente le gate de curriculum (_extract_worst_bot_scores_for_gate). Le poids nul ne
    # protege pas ce site : min() itere sur des win-rates, pas sur des poids. Import local
    # (training_callbacks importe bot_evaluation en differe) : discipline anti-circularite du module.
    from ai.training_callbacks import selection_worst_bot

    scenario_scores: Dict[str, Dict[str, float]] = {}
    for scenario_name, per_bot in scenario_bot_stats.items():
        bot_win_rates: Dict[str, float] = {}
        for bn in active_bot_names:
            stats = require_key(per_bot, bn)
            bot_win_rates[bn] = float(require_key(stats, "win_rate"))

        combined_score = sum(
            eval_weights[bn] * bot_win_rates[bn] for bn in active_bot_names
        )
        _, worst_bot_score = selection_worst_bot(bot_win_rates)
        scenario_scores[scenario_name] = {
            "combined": combined_score,
            "worst_bot_score": worst_bot_score,
        }
    results["scenario_scores"] = scenario_scores
    results["scenario_split_scores"] = _compute_scenario_split_scores(scenario_scores)
    holdout_split_metrics = _compute_holdout_split_metrics(training_cfg, scenario_scores, scenario_pool)
    results.update(holdout_split_metrics)

    if show_progress:
        # Show final progress bar (100%) before moving to next line
        progress_pct = 100.0
        bar_length = bot_eval_bar_length
        bar = '█' * bar_length
        elapsed = time.time() - require_present(start_time, "start_time")
        elapsed_str = _format_elapsed(elapsed)
        speed_str = f"{total_episodes/elapsed:.2f}ep/s" if elapsed > 0 else "0.00ep/s"
        if eval_progress_prefix and eval_progress_label:
            final_line = (
                f" [{elapsed_str}, {speed_str}] | "
                f"{eval_progress_label}: {progress_pct:3.0f}% {bar} {total_episodes}/{total_episodes}"
            )
            full_final_line = f"{eval_progress_prefix}{final_line}"
        elif eval_progress_label:
            final_line = (
                f"{progress_pct:3.0f}% {bar} {total_episodes}/{total_episodes} "
                f"[Completed] [{elapsed_str}, {speed_str}] {eval_progress_label}"
            )
            full_final_line = final_line
        else:
            final_line = (
                f"{progress_pct:3.0f}% {bar} {total_episodes}/{total_episodes} "
                f"[Completed] [{elapsed_str}, {speed_str}]"
            )
            full_final_line = f"{eval_progress_prefix} {final_line}" if eval_progress_prefix else final_line
        progress_writer.write(full_final_line)

    # total_failed_episodes déjà dans results ; ne pas faire planter tout l'éval (PLAN21)

    # DIAGNOSTIC: Print shoot statistics (sample from last episode of each bot)
    if show_progress and show_summary:
        print("\n" + "="*80)
        print("📊 DIAGNOSTIC: Shoot Phase Behavior")
        print("="*80)
        print("Bot behavior analysis completed - check logs for detailed stats")
        print("="*80 + "\n")
        ranking_lines = _render_scenario_ranking(scenario_scores, total_failed_episodes)
        if ranking_lines:
            for line in ranking_lines:
                print(line)
            print()

    return results


# ── R0b — CHECKPOINT ÉTALONS ───────────────────────────────────────────────

_CHECKPOINT_INCOMPATIBLE_COMMIT = "d5ddffb5"  # rupture charge_pair_net (§12.15)


def discover_checkpoint_archives(
    models_dir: str,
    agent_key: str,
) -> List[Tuple[str, str]]:
    """(zip_path, score_label) pour chaque archive *_robust_*.zip compatible.

    Compatible = possède le _vec_normalize.pkl compagnon (post-charge_pair_net).
    Incompatible (pas de pkl) → log INFO nommant le commit de rupture §12.15, jamais un crash.
    Retourne les archives triées par score croissant (plus faible → plus fort).
    """
    from ai.vec_normalize_utils import get_vec_normalize_path

    agent_dir = os.path.join(models_dir, agent_key)
    if not os.path.isdir(agent_dir):
        return []

    pattern = re.compile(r'^' + re.escape(agent_key) + r'_\d+_robust_(\d+\.\d+)\.zip$')
    compatible: List[Tuple[str, str]] = []
    for fname in os.listdir(agent_dir):
        m = pattern.match(fname)
        if m is None:
            continue
        score_label = m.group(1)
        zip_path = os.path.join(agent_dir, fname)
        pkl_path = get_vec_normalize_path(zip_path)
        if not os.path.exists(pkl_path):
            logging.info(
                "CHECKPOINT_SKIP %s : pas de _vec_normalize.pkl "
                "(archive pre-charge_pair_net, rupture %s) — ignoree.",
                fname, _CHECKPOINT_INCOMPATIBLE_COMMIT,
            )
            continue
        compatible.append((zip_path, score_label))

    compatible.sort(key=lambda t: float(t[1]))
    return compatible


def _resolve_seat_seed(training_cfg: dict) -> int:
    """Résout la seed siège depuis la config : agent_seat_seed en priorité, puis seed globale.

    Utilise `in` pour distinguer clé absente de valeur null explicite.
    """
    if "agent_seat_seed" in training_cfg:
        seed_raw = require_key(training_cfg, "agent_seat_seed")
    else:
        seed_raw = require_key(training_cfg, "seed")
    if not isinstance(seed_raw, int) or isinstance(seed_raw, bool):
        raise TypeError("Seat seed doit etre un entier quand agent_seat_mode='random'")
    return seed_raw


class _NormalizedFrozenModel:
    """Modèle figé + son propre VecNormalize — interface predict() identique à MaskablePPO.

    Intercept predict() pour appliquer la normalisation du CHECKPOINT (jamais celle du
    modèle courant — spec R0b). Substitut drop-in dans BotControlledEnv._frozen_model :
    BotControlledEnv._get_self_play_opponent_action() appelle self._frozen_model.predict(),
    ce wrapper l'intercepte avant d'appeler le vrai modèle.
    """

    def __init__(self, model: Any, normalizer: Optional[Any]) -> None:
        self._model = model
        self._normalizer = normalizer

    def predict(self, obs: Any, **kwargs: Any) -> Any:
        if self._normalizer is not None:
            obs = self._normalizer(obs)
        return self._model.predict(obs, **kwargs)


def evaluate_against_checkpoints(
    model_path: str,
    checkpoint_archives: List[Tuple[str, str]],
    training_config_name: str,
    rewards_config_name: str,
    n_episodes: int,
    controlled_agent: str,
    scenario_pool: str = "holdout",
    scenario_list_override: Optional[List[str]] = None,
    device: str = "cpu",
) -> Dict[str, Any]:
    """Win-rate du modèle courant contre chaque archive checkpoint figée.

    Hors sélection et hors gate (R0b) : indicateur de force relative sur la durée.
    L'adversaire checkpoint reçoit ses observations via SON propre _vec_normalize.pkl,
    jamais celui du modèle courant (spec R0b).

    Réutilise BotControlledEnv + le chemin self-play (ratio=1.0) : l'adversaire checkpoint
    est injecté dans _frozen_model via _NormalizedFrozenModel avant le premier épisode.

    Retourne {} si checkpoint_archives est vide.
    """
    if not checkpoint_archives:
        return {}

    import random as _random
    from sb3_contrib import MaskablePPO
    from config_loader import get_config_loader, get_max_turns
    from ai.training_utils import setup_imports, get_scenario_list_for_phase
    from ai.env_wrappers import BotControlledEnv
    from ai.unit_registry import UnitRegistry
    from ai.evaluation_bots import RandomBot
    from sb3_contrib.common.wrappers import ActionMasker
    from sb3_contrib.common.maskable.utils import get_action_masks

    config = get_config_loader()
    base_agent_key = _strip_phase_suffix(controlled_agent)

    training_cfg = config.load_agent_training_config(base_agent_key, training_config_name)
    agent_seat_mode = require_key(training_cfg, "agent_seat_mode")
    if agent_seat_mode not in {"p1", "p2", "random"}:
        raise ValueError(
            f"training_config.agent_seat_mode doit valoir p1/p2/random (got {agent_seat_mode!r})"
        )
    agent_seat_seed: Optional[int] = None
    if agent_seat_mode == "random":
        agent_seat_seed = _resolve_seat_seed(training_cfg)

    vec_norm_cfg = require_key(training_cfg, "vec_normalize")
    vec_normalize_enabled = bool(require_key(vec_norm_cfg, "enabled"))
    vec_norm_eval_cfg = require_key(training_cfg, "vec_normalize_eval")
    vec_eval_enabled = bool(require_key(vec_norm_eval_cfg, "enabled"))

    if scenario_list_override is not None:
        scenario_list = [str(p) for p in scenario_list_override]
        for p in scenario_list:
            if not os.path.isfile(p):
                raise FileNotFoundError(f"scenario_list_override contient un fichier absent : {p}")
    else:
        scenario_list = get_scenario_list_for_phase(
            config, base_agent_key, training_config_name, scenario_type=scenario_pool
        )
        if not scenario_list:
            return {}

    n_scenarios = len(scenario_list)
    eps_per_scenario = max(1, n_episodes // n_scenarios)
    max_steps = int(get_max_turns()) * 400

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Modèle principal absent : {model_path}")
    main_model = MaskablePPO.load(model_path, device=device)
    main_normalizer = _build_eval_obs_normalizer_for_worker(
        main_model, model_path, vec_normalize_enabled, vec_eval_enabled
    )

    W40KEngine, _ = setup_imports()
    results: Dict[str, float] = {}

    for zip_path, score_label in checkpoint_archives:
        ckpt_model = MaskablePPO.load(zip_path, device=device)
        ckpt_normalizer = _build_eval_obs_normalizer_for_worker(
            ckpt_model, zip_path, vec_normalize_enabled, vec_eval_enabled
        )
        normalized_ckpt = _NormalizedFrozenModel(ckpt_model, ckpt_normalizer)
        ckpt_mtime = float(os.path.getmtime(zip_path))

        wins, losses, draws, total = 0, 0, 0, 0
        for sc_idx, sc_file in enumerate(scenario_list):
            unit_registry = UnitRegistry()
            base_env = W40KEngine(
                rewards_config=rewards_config_name,
                training_config_name=training_config_name,
                controlled_agent=controlled_agent,
                active_agents=None,
                scenario_file=sc_file,
                unit_registry=unit_registry,
                quiet=True,
                gym_training_mode=True,
                training_n_envs=1,
            )
            masked_env = ActionMasker(base_env, lambda env: env.get_action_mask())
            env = BotControlledEnv(
                masked_env,
                bot=RandomBot(),
                unit_registry=unit_registry,
                agent_seat_mode=agent_seat_mode,
                global_seed=agent_seat_seed,
                env_rank=0,
                self_play_opponent_enabled=True,
                self_play_ratio_start=1.0,
                self_play_ratio_end=1.0,
                self_play_total_episodes=eps_per_scenario,
                self_play_warmup_episodes=0,
                self_play_n_envs=1,
                self_play_snapshot_path=zip_path,
                self_play_snapshot_refresh_episodes=eps_per_scenario + 1,
                self_play_snapshot_device=device,
                self_play_deterministic=True,
            )
            # Injection du modèle checkpoint normalisé avant le premier épisode.
            # _reload_self_play_snapshot_if_needed ne rechargera pas depuis le fichier tant que
            # _frozen_model_mtime correspond au mtime du fichier et le compteur d'épisodes
            # reste sous refresh_episodes.
            env._frozen_model = normalized_ckpt
            env._frozen_model_mtime = ckpt_mtime

            for ep_idx in range(eps_per_scenario):
                ep_seed = _episode_seed(42, score_label, sc_idx, ep_idx)
                _random.seed(ep_seed)
                np.random.seed(ep_seed)
                obs, info = env.reset(seed=ep_seed)
                done = False
                step_count = 0
                while not done and step_count < max_steps:
                    model_obs = main_normalizer(obs) if main_normalizer else obs
                    masks = np.asarray(get_action_masks(env), dtype=bool)
                    if masks.ndim == 1:
                        masks = masks.reshape(1, -1)
                    if isinstance(model_obs, dict):
                        inp = model_obs
                    else:
                        inp = np.asarray(model_obs, dtype=np.float32)
                        if inp.ndim == 1:
                            inp = inp.reshape(1, -1)
                    action, _ = main_model.predict(inp, action_masks=masks, deterministic=True)
                    obs, _, terminated, truncated, info = env.step(int(action.item()))
                    done = bool(terminated or truncated)
                    step_count += 1

                total += 1
                if not done:
                    continue
                winner = require_key(info, "winner")
                controlled_player = require_key(info, "controlled_player")
                if winner == controlled_player:
                    wins += 1
                elif winner == DRAW_WINNER:
                    draws += 1
                else:
                    losses += 1

            env.close()

        results[score_label] = wins / max(1, total)
        results[f"{score_label}_wins"] = wins
        results[f"{score_label}_losses"] = losses
        results[f"{score_label}_draws"] = draws

    return results
