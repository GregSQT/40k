#!/usr/bin/env python3
"""
w40k_core.py - Slim W40K Game Engine Core
Delegates to specialized modules, orchestrates game flow.
"""

import os
import threading
import time
import copy
import json
import random
import gymnasium as gym
import numpy as np
from typing import Dict, List, Literal, Tuple, Set, Optional, Any, overload

# Import shared utilities
from shared.data_validation import (
    require_key,
    require_non_negative_int,
    require_positive_int,
    require_present,
)
from engine.combat_utils import calculate_hex_distance, normalize_coordinates, resolve_dice_value, set_unit_coordinates
from engine.hex_utils import phantom_bottom_hexes
from engine.weapon_damage_cache import load_weapon_damage_table, stamp_weapon_keys, build_best_weapon_cache
from engine.utils.weapon_helpers import melee_weapons, ranged_weapons

# Phase handlers (existing - keep these)
from engine.phase_handlers import movement_handlers, shooting_handlers, charge_handlers, fight_handlers, command_handlers, deployment_handlers

# units_cache helpers (single source of truth for position/HP of living units)
from engine.phase_handlers.shared_utils import (
    build_units_cache,
    rebuild_choice_timing_index,
    is_unit_alive,
    require_unit_position,
    # Id d'action, importe de shared_utils et non de macro_intents (`ACTION_WAIT`, meme valeur) :
    # c'est CE symbole que le constructeur de masque pose (`mask[SQUAD_ACTION_WAIT] = 1`), et le
    # drapeau d'attente forcee compare une action AU MASQUE. Les deux constantes sont definies
    # independamment dans les deux modules ; lire celle du masque interdit qu'elles divergent ici.
    SQUAD_ACTION_WAIT,
    ACTION,
    WAIT,
    NO,
    PASS,
    SHOOTING,
    MOVE,
    CHARGE,
    FIGHT,
    FLED,
)

#: Borne de la chaine d'attentes forcees auto-jouees d'affilee (cf. `step_with_mask`). Ce n'est PAS
#: un reglage de jeu : la chaine se draine seule, chaque attente retirant une escouade de son pool.
#: La depasser signale donc une boucle, et le moteur LEVE au lieu de rendre un episode fige.
#: Elle borne AUSSI la pile : l'auto-jeu est re-entrant, donc une chaine de N vaut N frames de
#: `step_with_mask`, methode qui appelle elle-meme profond dans les handlers. 64 laisse une marge
#: confortable sous la limite de recursion de Python tout en depassant tres largement le reel — le
#: scenario d'entrainement compte 31,8 attentes forcees par EPISODE ENTIER, pas par chaine.
FORCED_WAIT_CHAIN_LIMIT = 64

#: Les seules cles d'`info` qui decrivent la FIN D'EPISODE et non l'action qui vient d'etre jouee.
#: Quand `step_with_mask` auto-joue des attentes forcees, l'`info` rendu reste celui de l'action de
#: L'AGENT (cf. `ai/env_wrappers.AGENT_STEP_INFO_KEYS`, preleve apres le retour du moteur) et seules
#: ces cles-ci sont reprises du dernier step de la chaine.
#:
#: ENUMERATION VERIFIEE, et non declarative : le bloc de terminaison de `step_with_mask` pose ses
#: cles dans un dict dedie (`terminal_info`) et LEVE si ce dict porte une cle absente d'ici. La
#: premiere version de cette liste omettait `tactical_data` et `deployment_mode` — deux cles
#: EXIGEES (`require_key`) par `ai/training_callbacks._handle_episode_end` et
#: `ai/metrics_tracker.log_episode` : un episode qui se terminait PENDANT une chaine auto-jouee les
#: perdait, et le run mourait dessus. Allonger la liste ne suffisait pas : c'est l'oubli
#: d'enumeration qui devait cesser d'etre silencieux. Il echoue desormais au premier episode
#: termine, donc dans n'importe quel test d'episode complet.
TERMINAL_INFO_KEYS = (
    "winner", "win_method", "episode",
    # Bilan d'episode lu par l'entrainement. `tactical_data` porte TOUT
    # `episode_tactical_data` (compteurs de combat, VP, reserves, ventilation de recompense) ;
    # `deployment_mode` ventile les courbes par mode de la rampe de deploiement.
    "tactical_data", "deployment_mode",
    # Pose par la sortie anticipee « limite de tours atteinte », qui construit son `info` a la
    # main et ne passe donc pas par le garde de `terminal_info`.
    "turn_limit_exceeded",
    # Troncature : posees ENSEMBLE avec `truncated = True`. Les omettre rendrait un `truncated`
    # sans son motif des que la troncature tombe pendant une chaine auto-jouee, et
    # `ai/training_callbacks` lit `truncation_debug`.
    "truncation_reason", "truncation_debug",
)


def _mask_only_opens_wait(mask: Any) -> bool:
    """« Le masque ne laisse que `wait` » — SOURCE UNIQUE du predicat d'attente forcee.

    Nomme parce que le lot le pose a DEUX endroits : a l'entree de `step_with_mask` (l'action de
    l'agent est-elle une attente contrainte ? -> pas de penalite) et a sa sortie (l'etat rendu
    laisse-t-il un choix ? -> le moteur enchaine lui-meme). Deux formulations libres du meme test
    auraient a rester en phase pour que recompense et auto-jeu parlent de la meme chose.

    MEME POLITIQUE, autre etage, que `ActionDecoder.activation_selection_slots` (« un seul slot
    ouvert : poser la decision couterait un step pour aucune information ») : celle-la elide la
    QUESTION dans le masque, celle-ci joue la REPONSE quand la question ne se pose plus.

    Chemin le plus chaud du moteur, d'ou les deux choix de forme, mesures sur un masque booleen de
    1139 entrees : le bit `wait` est teste AVANT le comptage (39 ns, et il elimine la quasi-totalite
    des etats sans toucher au reste du tableau), et le comptage est `np.count_nonzero` (297 ns) et
    non `.sum()` (1264 ns). Pas d'`asarray` : `ActionDecoder` rend deja un `ndarray` booleen, le
    convertir serait un no-op defensif paye a chaque step.
    """
    return bool(mask[SQUAD_ACTION_WAIT]) and int(np.count_nonzero(mask)) == 1

# Import shared utilities FIRST (no circular dependencies)
from engine.episode_schedule import episodes_per_env
from engine.game_utils import (
    ONCE_CLAIMS_KEY, get_controlled_player, get_unit_by_id, once_claim, once_claimed,
    turn_limit_reached, get_effective_turn_limit,
)

# Import NEW extracted modules
from engine.observation_builder import ObservationBuilder
from engine.action_decoder import (
    DEPLOY_SLOT_CANDIDATES_CACHE_KEY,
    INGRESS_SLOT_CANDIDATES_CACHE_KEY,
    ActionDecoder,
)
from engine.debug_trace import CH_STEP, trace
from engine.reward_calculator import RewardCalculator
from engine.game_state import (
    GameStateManager, initial_command_points, initial_faction_ability_state,
)
from engine.macro_intents import (
    ACTION_FAMILIES,
    DEPLOY_STRATEGY_SLOTS,
    INTENT_INVADE,
    MAX_OBJECTIVES,
    action_family,
    get_nearest_objective_zone,
    get_objective_control,
    get_objective_control_for_player,
    open_placement_slots,
)
from engine.agent_decision import (
    clear_pending_agent_decision,
    initialize_agent_decision_state,
    read_pending_agent_decision,
    set_pending_agent_decision,
)
from engine.pve_controller import PvEController

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ai.step_logger import StepLogger

# Global flag to ensure debug.log is cleared only once per training session
_debug_log_cleared = False

_engine_id_counter = 0
_engine_id_lock = threading.Lock()

#: Les cinq categories de `reward_breakdown` posees par RewardCalculator (`total` est leur
#: resultat, pas une categorie).
REWARD_BREAKDOWN_COMPONENTS = ('base_actions', 'result_bonuses', 'objective', 'situational', 'penalties')

#: Categories DENSES : celles qui paient un COMPORTEMENT. `situational` (le +-50 terminal) paie
#: le RESULTAT et sa masse ecraserait toute comparaison ; `penalties` est negatif et n'est PAS
#: disjoint de `base_actions` (`wait` et `charge_fail` sont ecrits dans les deux), l'additionner
#: compterait chaque attente deux fois. Seules ces trois-la portent un flux positif cumule.
DENSE_REWARD_BREAKDOWN_COMPONENTS = ('base_actions', 'result_bonuses', 'objective')


def empty_reward_breakdown_totals() -> Dict[str, float]:
    """Accumulateur de ventilation vide : totaux nets + flux positif des composantes denses."""
    totals: Dict[str, float] = {key: 0.0 for key in REWARD_BREAKDOWN_COMPONENTS}
    for key in DENSE_REWARD_BREAKDOWN_COMPONENTS:
        totals[f'{key}_positive'] = 0.0
    return totals


def _empty_episode_tactical_data() -> Dict[str, Any]:
    """Accumulateur tactique d'épisode, remis à zéro. SOURCE UNIQUE de sa forme.

    Ce dict était écrit DEUX FOIS mot pour mot (`__init__` et `reset`) : toute clé ajoutée à
    un site et pas à l'autre donne un `require_key` qui lève au premier épisode joué par le
    chemin oublié — motif JUMEAU du dépôt, et raison d'être de cette fabrique.
    """
    return {
        'shots_fired': 0,
        'hits': 0,
        'damage_dealt': 0,
        'damage_received': 0,
        'units_killed': 0,
        'units_lost': 0,
        'enemy_value_destroyed': 0.0,
        'ally_value_lost': 0.0,
        'valid_actions': 0,
        'invalid_actions': 0,
        'wait_actions': 0,
        'total_actions': 0,
        'total_enemy_units': 0,
        # Usage par FAMILLE d'action : quelle decision l'agent exerce reellement. Une
        # dimension jamais choisie, ou toujours choisie, est cassee quel que soit le
        # win-rate — et cela se voit en quelques milliers de pas, pas en fin de run.
        'action_family_counts': {name: 0 for name in ACTION_FAMILIES},
        # Issues du cache de scoring du deploiement (V11 §0.46 axe A) : recopiees ICI depuis
        # le `game_state` a la terminaison, comme `shots_fired` l'est depuis `action_logs`.
        'deployment_cache_counts': ActionDecoder.empty_deployment_cache_counts(),
        'reward_breakdown': empty_reward_breakdown_totals(),
        # Réserves stratégiques (20.01/20.04) : usage de l'agent sur l'épisode.
        'reserves_placed_agent': 0,
        'reserves_deployed_agent': 0,
        'reserves_destroyed_turn3': 0,
    }


def _reserves_game_state_defaults() -> Dict[str, int]:
    """Compteurs de réserves dans game_state — SOURCE UNIQUE (jumeau init/reset).

    Intégrer avec ** dans le dict initial ET dans game_state.update() du reset.
    Miroir de fly_declaration_reset_state() pour les drapeaux de vol.
    """
    return {
        "_reserves_placed_agent": 0,
        "_reserves_deployed_agent": 0,
        "_reserves_destroyed_turn3": 0,
    }


def _next_engine_id() -> int:
    """Monotonic ID per engine instance. Prevents cache collision when id() is reused after GC."""
    global _engine_id_counter
    with _engine_id_lock:
        _engine_id_counter += 1
        return _engine_id_counter


def reset_debug_log_flag():
    """Reset the debug log cleared flag. Call this at the start of each training run."""
    global _debug_log_cleared
    _debug_log_cleared = False


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def repo_relative_scenario_path(scenario_file: Optional[str]) -> Optional[str]:
    """Chemin du scénario relatif à la racine du dépôt, en séparateurs POSIX. None si aucun.

    Journalisé par `log_episode_start` : le replay le repasse à `/api/config/board` pour retrouver
    le décor de CE scénario (cf. Documentation/Implémentation/Replay.md §2.4). Un chemin hors du
    dépôt lève — l'API refuserait de le résoudre, et le journaliser produirait un replay qui
    échoue silencieusement au chargement du décor.
    """
    if not scenario_file:
        return None
    scenario_abs = os.path.abspath(scenario_file)
    relative = os.path.relpath(scenario_abs, _REPO_ROOT)
    if relative.startswith(".."):
        raise ValueError(
            f"Scenario file hors du dépôt, non journalisable pour le replay : "
            f"{scenario_abs} (racine {_REPO_ROOT})"
        )
    return relative.replace(os.sep, "/")


def destroy_unarrived_strategic_reserves(game_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """20.04 — fin du 3e round de bataille : les réserves qui ne sont pas arrivées sont DÉTRUITES.

    « At the end of the third battle round, unless otherwise stated, all strategic reserves
    units that have not made one or more ingress moves are destroyed, with the following
    exceptions: units embarked within TRANSPORTS that have made an ingress move during the
    battle ; repositioned units (20.02). »

    Les deux exceptions sont appliquées :
      - **unités repositionnées** (20.02, ex. Da Jump) : drapeau `reserves_repositioned` ;
      - **embarquées dans un transport ayant fait un ingress** : les transports (PDF 18) ne sont
        pas modélisés — aucune unité ne peut être embarquée, donc l'exception n'a aucun sujet.
        Elle est nommée ici pour que son absence soit une CONSTATATION et non un oubli ; elle
        deviendra effective avec le chantier transports.

    C'est une RÈGLE DE JEU : elle se journalise comme un événement normal (console log +
    `destroy_model` avec sa raison propre), jamais comme une erreur. Retourne les UNITÉS détruites
    (et non leurs seuls ids) : l'appelant a besoin de leur `player`, et les re-résoudre par id
    l'obligerait à rattraper un `None` que cette boucle sait déjà impossible.

    Appelée par le SEUL point où un round de bataille s'achève (fin de la phase de combat du
    joueur 2, `fight_handlers._fight_v11_phase_complete`), AVANT l'incrément de tour et avant le
    scoring de fin de partie : une unité détruite par cette règle ne doit pas compter dans le
    départage aux points.
    """
    from engine.game_utils import add_console_log
    from engine.phase_handlers.shared_utils import destroy_model

    destroyed: List[Dict[str, Any]] = []
    for unit in list(require_key(game_state, "units")):
        unit_id = str(require_key(unit, "id"))
        if not unit.get("in_strategic_reserves", False):  # get allowed (champ optionnel, cf. loader)
            continue
        if not is_unit_alive(unit_id, game_state):
            continue
        if bool(unit.get("reserves_repositioned", False)):  # get allowed (idem)
            continue
        squad_models = require_key(game_state, "squad_models")
        models_cache = require_key(game_state, "models_cache")
        for model_id in list(squad_models.get(str(unit_id), [])):  # get allowed
            if model_id in models_cache:
                destroy_model(game_state, model_id, "strategic_reserves_timeout")
        destroyed.append(unit)
        add_console_log(
            game_state,
            f"STRATEGIC RESERVES (20.04): unit {unit_id} never made an ingress move by the end "
            f"of battle round {require_key(game_state, 'turn')} — destroyed",
        )
    return destroyed


class W40KEngine(gym.Env):
    """
    Slim W40K game engine - delegates to specialized modules.
    Core responsibilities: Gym interface, phase orchestration, episode management.
    """

    # Config d'entraînement de la phase courante. Annotation SEULE (pas d'affectation) : elle
    # type l'attribut sans le créer, donc un chemin d'``__init__`` qui oublierait de l'assigner
    # lève toujours AttributeError au lieu de passer pour un ``None`` légitime. ``None`` est une
    # valeur métier du chemin API multi-agents (aucun agent connu déclaré) ; les chemins
    # d'entraînement lèvent plutôt que de la laisser vide.
    training_config: Optional[Dict[str, Any]]


    # ============================================================================
    # INITIALIZATION (KEEP FROM LINES 42-214)
    # ============================================================================
    
    def __init__(self, config=None, rewards_config=None, training_config_name=None,
                controlled_agent=None, active_agents=None, scenario_file=None,
                scenario_files=None,  # NEW: List of scenarios for random selection per episode
                unit_registry=None, quiet=True, gym_training_mode=False, debug_mode=False,
                training_n_envs: Optional[int] = None,
                training_episode_start_index: int = 0, **kwargs):
        """Initialize W40K engine with AI_TURN.md compliance - training system compatible.

        Args:
            scenario_file: Single scenario file path (used if scenario_files not provided)
            scenario_files: List of scenario file paths for random selection per episode
        """

        # Store gym training mode for handler access
        self.gym_training_mode = gym_training_mode
        self.debug_mode = debug_mode
        self.current_mode_code: Optional[str] = None
        # Report de la construction d'observation dans ``step`` (cf. ``_step_observation``).
        # Faux par defaut : tout appelant qui ne connait pas ce contrat recoit une observation.
        self.defer_observation: bool = False

        # Store scenario files list for random selection during reset
        # If scenario_files provided, use it; otherwise create single-item list from scenario_file
        if scenario_files and len(scenario_files) > 0:
            self._scenario_files = scenario_files
            self._random_scenario_mode = True
            # Use first scenario for initial setup
            scenario_file = scenario_files[0]
        else:
            self._scenario_files = [scenario_file] if scenario_file else []
            self._random_scenario_mode = False

        # Store current scenario file path for reference
        self._current_scenario_file = scenario_file
        
        # Dénominateur des rampes par-épisode, mémoïsé sur (total_episodes, n_envs).
        self._episode_ramp_budget: Optional[Tuple[int, Any]] = None
        self._episode_ramp_denominator: int = 1
        # Le `n_envs` de `training_config` a-t-il été RÉSOLU par l'appelant, ou n'est-ce que la
        # valeur déclarée du profil ? Les deux sont indiscernables une fois dans le dict, et un
        # site qui oublie de résoudre repart en silence sur 48 envs imaginaires — c'est le défaut
        # §0.57 qui se reforme. Une rampe refuse donc de tourner sur une valeur non résolue.
        self._episode_ramp_n_envs_is_runtime = False

        # Episodes deja joues par CET environnement lors d'un run precedent (reprise, chunk de
        # curriculum) : la rampe repart de la, au lieu de `active_ratio_start`. Cf. ai/run_state.py.
        require_non_negative_int(training_episode_start_index, "training_episode_start_index")

        if config is not None and training_n_envs is not None:
            raise ValueError(
                "W40KEngine(training_n_envs=...) n'est accepté que sur le chemin d'entraînement "
                "(config=None + training_config_name) : le chemin API/PvP ne joue pas d'épisodes "
                "rampés."
            )

        # Handle both new engine format (single config) and old training system format
        if config is None:
            # Build config from training system parameters
            from config_loader import get_config_loader, require_engine_game_config_sections
            config_loader = get_config_loader()

            # Load agent-specific rewards configuration
            if not controlled_agent:
                raise ValueError("controlled_agent parameter required when config is None - cannot load agent-specific rewards")

            # CRITICAL FIX: Extract base agent key for file loading (strip phase suffix)
            # controlled_agent may be "Agent_phase1", but file is at "config/agents/Agent/Agent_rewards_config.json"
            base_agent_key = controlled_agent
            for phase_suffix in ['_phase1', '_phase2', '_phase3', '_phase4']:
                if controlled_agent.endswith(phase_suffix):
                    base_agent_key = controlled_agent[:-len(phase_suffix)]
                    break

            self.rewards_config = config_loader.load_agent_rewards_config(base_agent_key)
            if not self.rewards_config:
                raise RuntimeError(f"Failed to load rewards configuration for agent: {base_agent_key}")

            # Store the agent-specific config name for reference
            self.rewards_config_name = rewards_config
            if not self.rewards_config_name:
                raise ValueError("rewards_config parameter required - specifies which reward section to use")

            # Load agent-specific training configuration for turn limits
            if not training_config_name:
                raise ValueError("training_config_name parameter required when config is None - cannot load agent-specific training config")

            self.training_config = config_loader.load_agent_training_config(base_agent_key, training_config_name)
            if not self.training_config:
                raise RuntimeError(f"Failed to load training configuration for agent {controlled_agent}, phase {training_config_name}")
            # PROFIL d'entraînement chargé depuis config/agents/<agent>/<agent>_training_config.json :
            # le contrat complet des schedulers y est EXIGÉ (cf.
            # _configure_deployment_mode_for_episode). Les autres chemins de construction (API/PvP)
            # ne fournissent qu'un fragment (observation_params) et n'ont pas d'épisodes à ramper.
            self._training_config_is_agent_profile = True
            # Le nom de phase n'était posé que sur le chemin API : sans lui, tout message d'erreur
            # portant sur le profil chargé ne peut pas dire DE QUEL profil il parle.
            self.training_config_name = training_config_name
            # n_envs RÉELLEMENT ouverts par le run. Le profil, lui, ne déclare qu'une intention :
            # un worker relit le JSON (48) même quand `--step` n'a ouvert qu'un environnement.
            # Écrit sur une COPIE — rien ne garantit que ce dict ne soit pas partagé ailleurs.
            # Pourquoi ce nombre décide de tout : engine/episode_schedule.py.
            if training_n_envs is not None:
                self.training_config = dict(self.training_config)
                self.training_config["n_envs"] = require_positive_int(training_n_envs, "training_n_envs")
                self._episode_ramp_n_envs_is_runtime = True
            
            # Load base configuration
            board_config = config_loader.get_board_config()
            game_config = config_loader.get_game_config()

            # CRITICAL FIX: Initialize PvE mode BEFORE config creation
            # Training mode: pve_mode=False (SelfPlayWrapper handles Player 1)
            # PvE mode in API: pve_mode=True (load AI model for Player 1)
            pve_mode_value = False  # Training uses SelfPlayWrapper, not pve_mode

            # Extract observation_params for module access - NO DEFAULTS
            if "observation_params" not in self.training_config:
                raise KeyError(f"observation_params missing from {controlled_agent} training config phase {training_config_name}")
            obs_params = self.training_config["observation_params"]

            # Load scenario data (units + optional terrain)
            scenario_result = self._load_units_from_scenario(scenario_file, unit_registry)
            scenario_units = scenario_result["units"]
            scenario_roster_info = scenario_result.get("roster_info")
            scenario_primary_objective_ids = scenario_result.get("primary_objectives")
            scenario_deployment_type = scenario_result.get("deployment_type")
            scenario_deployment_type_by_player = scenario_result.get("deployment_type_by_player")
            scenario_deployment_zone = scenario_result.get("deployment_zone")
            scenario_deployment_pools = scenario_result.get("deployment_pools")
            scenario_primary_objective_id = None
            if scenario_primary_objective_ids is None:
                scenario_primary_objective_id = scenario_result.get("primary_objective")

            if scenario_primary_objective_ids is not None:
                if not isinstance(scenario_primary_objective_ids, list):
                    raise TypeError("primary_objectives must be a list of objective IDs")
                if not scenario_primary_objective_ids:
                    raise ValueError("primary_objectives list cannot be empty")
                primary_objective_config = [
                    config_loader.load_primary_objective_config(obj_id)
                    for obj_id in scenario_primary_objective_ids
                ]
            elif scenario_primary_objective_id is not None:
                primary_objective_config = config_loader.load_primary_objective_config(
                    scenario_primary_objective_id
                )
            else:
                primary_objective_config = None

            # Determine wall_hexes: use scenario if provided, otherwise use board config
            if scenario_result.get("wall_hexes") is not None:
                scenario_wall_hexes = scenario_result["wall_hexes"]
            else:
                # Use board config
                if "default" in board_config:
                    d = board_config["default"]
                    scenario_wall_hexes = d["wall_hexes"] if "wall_hexes" in d else []
                else:
                    scenario_wall_hexes = board_config["wall_hexes"] if "wall_hexes" in board_config else []

            # Objectifs : source UNIQUE = terrains "objective": true, déjà résolus par le
            # loader de scénario en {id, hexes}. Aucun fallback board config (système legacy supprimé).
            scenario_objectives = require_key(scenario_result, "objectives")

            # Store scenario terrain for game_state initialization
            self._scenario_wall_hexes = scenario_wall_hexes
            # Sous-ensemble Solid/dense (rule 13.5 Gone to Ground). None si absent (jamais
            # de repli vers wall_hexes complet : un mur non typé n'est pas Solid-prouvable).
            self._scenario_dense_wall_hexes = scenario_result.get("dense_wall_hexes")
            self._scenario_objectives = scenario_objectives
            self._scenario_terrain_areas = scenario_result.get("terrain_areas")
            self._scenario_primary_objective = primary_objective_config
            self._scenario_roster_info = scenario_roster_info
            # Taille de bataille (points) du scénario — plafond des réserves 20.01.
            self._scenario_points_limit = scenario_result.get("points_limit")
            self._scenario_has_random_agent_roster = bool(
                scenario_roster_info and scenario_roster_info.get("agent_ref_randomized")
            )

            # Extract scenario name from file path for logging
            scenario_name = scenario_file if scenario_file else "Unknown Scenario"
            if scenario_name and "/" in scenario_name:
                scenario_name = scenario_name.split("/")[-1].replace(".json", "")
            elif scenario_name and "\\" in scenario_name:
                scenario_name = scenario_name.split("\\")[-1].replace(".json", "")

            self.config = {
                "board": board_config,
                **require_engine_game_config_sections(game_config),
                "units": scenario_units,
                "name": scenario_name,  # Store scenario name for logging
                "rewards_config_name": self.rewards_config_name,
                "training_config_name": training_config_name,
                "training_config": self.training_config,
                "observation_params": obs_params,  # ✓ CHANGE 1: Add to config root for ObservationBuilder
                "controlled_agent": controlled_agent,
                "active_agents": active_agents,
                "quiet": quiet,
                "gym_training_mode": gym_training_mode,  # CRITICAL: Pass flag to handlers
                "debug_mode": debug_mode,  # CRITICAL: Pass debug flag to handlers
                "pve_mode": pve_mode_value,  # CRITICAL: Add PvE mode for handler detection
                "controlled_player": 1,  # FIXED: Agent controls player 1 (matches scenario setup)
                "primary_objective": primary_objective_config,
                "deployment_type": scenario_deployment_type,
                "deployment_type_by_player": scenario_deployment_type_by_player,
                "deployment_zone": scenario_deployment_zone,
                "deployment_pools": scenario_deployment_pools,
                # Oath of Moment (chantier 03) : « If you are using a Codex: Space Marines
                # Detachment ». Aucun systeme de detachement n'existe dans le moteur, la valeur
                # est donc une DONNEE DE SCENARIO, comme la zone de deploiement juste au-dessus.
                # `.get` et non `require_key` : la cle n'a de sens que si une armee ADEPTUS
                # ASTARTES est en jeu. Son absence ne leve pas ICI mais au moment ou le +1 Wound
                # en depend (`game_state.uses_codex_detachment`) — la ou le message peut dire
                # de quelle armee il s'agit, plutot que de bloquer tous les scenarios orks.
                "uses_codex_detachment": scenario_result.get("uses_codex_detachment"),
                # Faction d'Armee DECLAREE par joueur, meme nature et meme regime que la cle
                # ci-dessus : une donnee de scenario que le moteur ne deduit pas. Son absence
                # leve dans `game_state.army_faction`, au moment ou 08.04 la demande.
                "army_faction": scenario_result.get("army_faction"),
            }
            self._scenario_loaded_for_controlled_player = int(require_key(self.config, "controlled_player"))
        else:
            # Use provided config directly and add gym_training_mode
            self.config = config.copy()
            self.config["gym_training_mode"] = gym_training_mode
            self.config["debug_mode"] = debug_mode
            # CRITICAL: Ensure pve_mode is in config for handler delegation
            if "pve_mode" not in self.config:
                self.config["pve_mode"] = config.get("pve_mode", False)
            # CHANGE 5: Ensure controlled_player is set
            if "controlled_player" not in self.config:
                if gym_training_mode:
                    raise KeyError(
                        "Training mode requires explicit config['controlled_player']; "
                        "implicit defaults when the key is absent are forbidden."
                    )
                self.config["controlled_player"] = 1  # Legacy non-training default

            # CRITICAL: Extract rewards_config from config dict for module initialization
            self.rewards_config = config["rewards_config"] if "rewards_config" in config else {}
            # Faux en dur, même quand `roster_info` porte `agent_ref_randomized` : ce drapeau ne
            # sert qu'à REDEMANDER un scénario au reset (tirage de roster entre deux épisodes
            # d'entraînement). Une partie API/PvP ne rejoue pas d'épisode ; le dériver ici
            # ouvrirait un rechargement de scénario en cours de partie, pas une rotation.
            self._scenario_has_random_agent_roster = False
            # Chemin API/PvP : le scénario est chargé par l'APPELANT (services/api_server.py),
            # qui reforwarde ici le produit du loader. `None` quand la clé est absente = valeur
            # MÉTIER (« ce scénario ne déclare ni roster ni `scale` »), et non un défaut
            # anti-erreur : c'est déjà la sémantique posée par le loader lui-même
            # (engine/game_state.py). Les poser ICI, sur les DEUX branches de construction, est
            # ce qui autorise l'accès direct partout au lieu d'un getattr par point de lecture.
            self._scenario_roster_info = self.config.get("roster_info")
            # Taille de bataille en points : plafond des réserves stratégiques 20.01. Absente =
            # règle invérifiable, donc aucun dépôt en réserves (cf. strategic_reserves_usage).
            self._scenario_points_limit = self.config.get("points_limit")
            self._scenario_loaded_for_controlled_player = int(require_key(self.config, "controlled_player"))
            
            # CRITICAL: Extract training_config from config dict for observation_params access
            # API server provides training_configs dict with agent keys, or training_config_name to select phase
            # Ce chemin ne charge PAS un profil d'entraînement complet (cf. l'autre branche) :
            # les schedulers par épisode n'y sont pas exigibles.
            self._training_config_is_agent_profile = False
            if "training_configs" in config and training_config_name:
                # Multi-agent config: extract specific agent's training config
                agent_keys = config["agent_keys"] if "agent_keys" in config else []
                first_agent = list(agent_keys)[0] if agent_keys else None
                if first_agent and first_agent in config["training_configs"]:
                    full_training_config = config["training_configs"][first_agent]
                    # Extract the specific phase (e.g., "default")
                    self.training_config = full_training_config[training_config_name] if training_config_name in full_training_config else {}
                    self.training_config_name = training_config_name
                else:
                    self.training_config = None
            elif "training_config" in config:
                # Direct training_config provided
                self.training_config = config["training_config"]
                self.training_config_name = training_config_name if training_config_name else "default"
            else:
                # Try to construct from observation_params if available
                if "observation_params" in config:
                    # Create minimal training_config structure for observation_params access
                    self.training_config = {
                        "observation_params": config["observation_params"]
                    }
                    self.training_config_name = training_config_name if training_config_name else "default"
                else:
                    self.training_config = None

            # Scenario provided via config (API path). Objectifs : source unique = terrains
            # "objective": true, déjà résolus en {id, name, hexes} par le loader et passés via
            # 'scenario_objectives'. Absent du config = aucun objectif fourni → liste vide (état
            # métier valide, pas un fallback masquant : zéro terrain objectif = zéro objectif).
            self._scenario_wall_hexes = self.config.get("scenario_wall_hexes")
            self._scenario_dense_wall_hexes = self.config.get("scenario_dense_wall_hexes")
            self._scenario_objectives = self.config.get("scenario_objectives") or []
            self._scenario_terrain_areas = self.config.get("scenario_terrain_areas")
            self._scenario_primary_objective = self.config.get("primary_objective")
        
        # Scale game_rules distance values from inches to sub-hex grid units.
        # Data files keep values in inches (GW standard); the engine works in grid steps.
        # CRITICAL: deep-copy mutable sub-dicts before scaling to avoid mutating
        # the cached config_loader objects (causes cumulative ×10 on each game restart).
        _board_cfg = require_key(self.config, "board")
        _board_default = _board_cfg.get("default", _board_cfg)
        _scale = int(require_key(_board_default, "inches_to_subhex"))
        if _scale != 1:
            # `require_key` et non `.get` : une section absente ne SAUTAIT que la mise a
            # l'echelle, laissant `engagement_zone` / `charge_max_distance` en POUCES sur un
            # plateau x5 ou x10 — memes sections, meme extinction silencieuse que la 14.02
            # (cf. `config_loader.GAME_CONFIG_SECTIONS_REQUIRED_BY_ENGINE`).
            gr = copy.deepcopy(require_key(self.config, "game_rules"))
            self.config["game_rules"] = gr
            for _key in (
                "engagement_zone",
                "advance_distance_range",
                "avg_charge_roll",
                "max_search_distance",
                "unit_model_cohesion_range",
                "unit_global_cohesion_range",
            ):
                if _key in gr:
                    gr[_key] = int(gr[_key]) * _scale
            charge_cfg = copy.deepcopy(require_key(self.config, "charge"))
            self.config["charge"] = charge_cfg
            if "charge_max_distance" in charge_cfg:
                charge_cfg["charge_max_distance"] = int(charge_cfg["charge_max_distance"]) * _scale
            self.config["inches_to_subhex"] = _scale
        else:
            self.config["inches_to_subhex"] = 1

        # Plafond anti-runaway de l'episode : derive PARESSEUSEMENT de game_rules au
        # premier depassement du seuil de veille (cf. _episode_step_limit_value). Le calcul
        # n'est pas fait ici car des harnais legitimes construisent le moteur avec un
        # game_rules partiel ; exiger max_turns/max_steps_per_turn des la construction
        # imposerait la config complete a des appelants qui ne jouent aucun episode.
        self._episode_step_limit_cache: Optional[int] = None

        # Store training system compatibility parameters
        self.quiet = quiet
        self.unit_registry = unit_registry
        self.step_logger: Optional["StepLogger"] = None  # Will be set by training system if enabled
        self.is_evaluation_mode: bool = False  # Set by training system during evaluation
        self._force_evaluation_mode: bool = False  # Set by training system during evaluation
        
        # Detect training context to suppress debug logs
        self.is_training = training_config_name in ["debug", "default", "conservative", "aggressive"]
        
        # PvE mode configuration
        # AI_TURN.md COMPLIANCE: self.config is normalized above (training + API paths); never read
        # from the raw `config` parameter here — it can diverge from self.config after copy/fill.
        if "pve_mode" not in self.config:
            raise KeyError(
                "pve_mode must be present in config after engine config build"
            )
        self.is_pve_mode = self.config["pve_mode"]
        self._ai_model = None
        if not isinstance(self.is_pve_mode, bool):
            raise TypeError(f"is_pve_mode must be bool, got {type(self.is_pve_mode).__name__}")
        player_types = {
            "1": "human",
            "2": "ai" if self.is_pve_mode else "human",
        }

        board_cols = self.config["board"]["default"]["cols"] if "default" in self.config["board"] else self.config["board"]["cols"]
        board_rows = self.config["board"]["default"]["rows"] if "default" in self.config["board"] else self.config["board"]["rows"]
        max_range = self._calculate_board_max_range(board_cols, board_rows)
        _board = self.config["board"]
        _fallback_walls = (
            _board["default"]["wall_hexes"] if "wall_hexes" in _board["default"] else []
        ) if "default" in _board else (
            _board["wall_hexes"] if "wall_hexes" in _board else []
        )
        base_wall_hexes = (
            set(map(tuple, self._scenario_wall_hexes))
            if self._scenario_wall_hexes is not None
            else set(map(tuple, _fallback_walls))
        )
        # Set Solid/dense (rule 13.5) : uniquement les murs de terrains dense. Les murs de bord
        # de plateau ajoutés ci-dessous ne sont PAS des terrains Solid → hors de ce set.
        base_dense_wall_hexes = (
            set(map(tuple, self._scenario_dense_wall_hexes or []))
        )
        base_wall_hexes |= phantom_bottom_hexes(board_cols, board_rows)

        from engine.combat_utils import GYM_DISTANCE_METRIC_KEY, gym_distance_metric_override
        from config_loader import get_config_loader

        # CRITICAL: Initialize game_state FIRST before any other operations
        # _cache_instance_id: unique per engine instance, prevents id(game_state) reuse collision
        # when multiple envs run in same process (bot eval) and old game_state is GC'd
        self.game_state = {
            "_cache_instance_id": _next_engine_id(),
            # Core game state
            "units": [],
            "current_player": 1,
            "player_types": player_types,
            "gym_training_mode": self.config["gym_training_mode"],  # Embed for handler access
            "debug_mode": self.config.get("debug_mode", False),  # Embed for handler access
            "training_config_name": training_config_name if training_config_name else "",  # NEW: For debug mode detection
            "phase": "command",
            "turn": 1,
            "episode_steps": 0,
            "unit_activation_count": 0,
            "game_over": False,
            "winner": None,
            "victory_points": {1: 0, 2: 0},
            # Points de commandement des deux joueurs (08.02). Meme cycle de vie que
            # `victory_points` : pose a l'init ET remis a la dotation de depart au reset.
            "command_points": initial_command_points(get_config_loader().get_game_config()),
            # Capacites de faction (chantier 03) — meme cycle de vie que `command_points`.
            **initial_faction_ability_state(),
            "primary_objective": self._scenario_primary_objective,
            # Marqueurs « etape deja resolue » : registre `_once_claims`, cree paresseusement
            # et purge au reset — plus declares ici (POURQUOI : `engine.game_utils`).
            "controlled_objective_samples_scoring_turns": [],
            "opponent_objective_samples_scoring_turns": [],
            # Mode tire par `deployment_mode_schedule` pour l'episode ("active"|"auto"), None
            # hors entrainement. Pose A L'INIT et pas au seul reset : les chemins API/PvP
            # construisent le moteur puis jouent sans passer par `reset()`, et le bloc terminal
            # de `step` lit cette cle pour la publier dans `info`. Le `.update()` du reset ne la
            # reecrit pas — c'est la neutralisation explicite en tete de reset qui s'en charge,
            # avant le tirage.
            "deployment_mode_schedule_mode": None,
            "zone_intents": [INTENT_INVADE] * MAX_OBJECTIVES,
            "zone_intent_free_steps_remaining": 0,
            "unit_zone_assignments": {},
            # Declarations d'intents en attente de solde, par joueur. REMISE A ZERO ICI parce
            # que `reset` fait un `update()` de game_state, pas une recreation : une declaration
            # non soldee (l'adversaire, ou l'agent sur un episode tronque) serait sinon soldee au
            # tour 1 de l'episode SUIVANT, contre un plateau sans aucun rapport.
            "_zone_intent_declarations": {},
            # Meme raison pour le solde DEJA CALCULE mais pas encore verse : il n'est poppe que
            # par une action non-zone-intent, et plusieurs chemins n'y arrivent jamais (fin de
            # partie pendant les free steps, sortie anticipee turn-limit, auto-advance). Il
            # atterrirait alors sur la premiere action de l'episode suivant.
            "_pending_zone_shaping": 0.0,

            # AI_TURN.md required tracking sets
            "units_moved": set(),
            "moved_distance_by_model": {},
            "units_fled": set(),
            "units_cannot_charge": set(),
            "units_shot": set(),
            "units_shot_previous_turn": set(),
            "units_charged": set(),
            "units_reacted_this_enemy_turn": set(),
            "reaction_window_active": False,
            "_unit_move_version": 0,
            "last_move_event_id": 0,
            "last_move_cause": "normal",
            "reactive_mode": "micro",
            "reactive_macro_order_current_window": [],
            "reactive_decision_mode": "auto",
            "reactive_decision_payload": {},
            
            # Phase management
            "command_activation_pool": [],
            "move_activation_pool": [],
            "shoot_activation_pool": [],
            "charge_activation_pool": [],
            
            # AI_MOVE.md movement preview state
            "valid_move_destinations_pool": [],
            "preview_hexes": [],
            "move_preview_footprint_span": None,
            "active_movement_unit": None,
            
            # Fight state
            "fight_subphase": None,
            "charge_range_rolls": {},
            
            # Metrics tracking
            "action_logs": [],  # CRITICAL: For metrics collection - tracks all actions per episode
            "action_log_seq": 0,  # Monotonic stamp per append_action_log (not cleared with action_logs flush)
            "log_delta": [],  # Combat log : events depuis la dernière row de timeline (drainé dans meta['log_delta'] à chaque capture). Reconstruit le Game Log au Load/rewind du replay (delta linéaire, pas de cumul par row)
            **_reserves_game_state_defaults(),

            # PERFORMANCE: Hex-coordinate LoS cache (walls static within episode)
            "hex_los_cache": {},

            # CHANGE 11: Add rewards_configs (plural) to game_state for handler access
            "rewards_configs": {
                self.config.get("controlled_agent", "default"): self.rewards_config
            },
            # Handler access for single-agent reward config (required, no defaults)
            "reward_configs": self.rewards_config,
            "config": self.config,

            # Duree de bataille illimitee : seul l'Endless Duty (base sur des vagues)
            # l'active, via services/endless_duty_runtime. Partout ailleurs la duree
            # vient de game_rules.max_turns (cf. get_effective_turn_limit).
            "unlimited_turns": False,

            # Board state - handle both config formats
            "board_cols": board_cols,
            "board_rows": board_rows,
            "inches_to_subhex": require_key(_board.get("default", _board), "inches_to_subhex"),
            # Taille de bataille en points (règle 20.01 : le plafond des réserves stratégiques
            # vaut 50 % de cette limite). None quand le scénario ne déclare pas de `scale`.
            "points_limit": self._scenario_points_limit,
            # Métrique imposée par la PHASE de training (opt-in). Posée à côté de
            # `inches_to_subhex` parce qu'elle joue le même rôle : un paramètre du monde, lu par
            # les sélecteurs de distance depuis l'état plutôt que depuis le config global.
            # `None` = phase muette → les sélecteurs lisent `game_config` comme avant.
            # RÉSOLUE ICI, donc VALIDÉE à la construction : une phase avec une valeur invalide
            # doit faire échouer le lancement du run, pas se découvrir au premier pool de move
            # d'un worker vectorisé. `self.training_config` est None hors training (API/PvP) :
            # pas de phase, pas d'override — le réglage ne peut structurellement pas fuir en PvP.
            GYM_DISTANCE_METRIC_KEY: gym_distance_metric_override(self.training_config),
            "max_range": max_range,
            # Use scenario terrain if loaded, otherwise use board config
            "wall_hexes": base_wall_hexes,
            # Murs de terrains Solid/dense (rule 13.5 Gone to Ground) — sous-ensemble de wall_hexes
            "dense_wall_hexes": base_dense_wall_hexes,
            # Polygon terrain areas (obscuring/cover, rules 13.08-13.10), rasterized to hexes
            "terrain_areas": self._scenario_terrain_areas or [],
            # Objectives: grouped structure with id, name, hexes (for objective control calculation)
            "objectives": self._scenario_objectives,
        }

        self.game_state.pop("_wall_set_cache", None)
        self.game_state.pop("_dense_wall_set_cache", None)
        self.game_state.pop("_obscuring_area_sets_cache", None)
        self.game_state.pop("_obscuring_hex_to_area_cache", None)
        # Grilles de blocage de la LoS vectorisee : DERIVEES des deux caches ci-dessus, donc
        # purgees AVEC eux — survivantes, elles porteraient les murs du terrain precedent.
        self.game_state.pop("_los_blocking_grids_cache", None)
        self.game_state.pop("_unit_los_pair_cache", None)

        self.game_state["weapon_damage_table"] = load_weapon_damage_table()

        objectives = require_key(self.game_state, "objectives")
        assert len(objectives) <= MAX_OBJECTIVES, (
            f"Scenario has {len(objectives)} objectives but MAX_OBJECTIVES={MAX_OBJECTIVES}. "
            "Increase MAX_OBJECTIVES in macro_intents.py or reduce scenario objectives."
        )
        self.game_state["macro_target_objective_index"] = 0 if objectives else None
        self.game_state["macro_target_objective_id"] = str(require_key(objectives[0], "id")) if objectives else None

        # CRITICAL: Instantiate all module managers BEFORE using them
        self.state_manager = GameStateManager(self.config, self.unit_registry)
        self.obs_builder = ObservationBuilder(self.config)
        self.action_decoder = ActionDecoder(self.config)
        # Le bloc « candidats de déploiement » de l'observation (§0.40 point 3) LIT le décodeur :
        # l'hexe décrit à l'agent est celui que le commit posera, jamais un second calcul.
        self.obs_builder.action_decoder = self.action_decoder
        # Use rewards_config from config dict if not already loaded
        _rc = self.config["rewards_config"] if "rewards_config" in self.config else {}
        rewards_cfg = getattr(self, 'rewards_config', _rc)
        self.reward_calculator = RewardCalculator(self.config, self.rewards_config, self.unit_registry, self.state_manager)
        self.pve_controller = PvEController(self.config, self.unit_registry)
        
        # Initialize units from config AFTER game_state exists
        self._initialize_units()

        for unit in self.game_state["units"]:
            stamp_weapon_keys(unit)

        # Build reward configs for all units present in the scenario.
        reward_configs = self._build_reward_configs_for_current_units()
        self.game_state["reward_configs"] = reward_configs
        self.game_state["rewards_configs"] = reward_configs

        # CRITICAL: Initialize Gym spaces BEFORE any other operations
        # Gym interface properties - dynamic action space based on phase
        _total_action_size = self.action_decoder.total_action_size
        self.action_space = gym.spaces.Discrete(_total_action_size)
        self._current_valid_actions = list(range(_total_action_size))  # Will be masked dynamically
        
        # Observation space: Asymmetric egocentric perception with R=25 radius
        # Size is now configurable via training_config.json observation_params.obs_size
        # Default was 300 floats = 15 global (incl. objectives) + 8 unit + 32 terrain + 72 allies + 138 enemies + 35 targets
        # New size: 313 floats = 15 global + 22 unit capabilities + 32 terrain + 72 allies + 132 enemies + 40 targets
        
        # Load perception parameters from training config if available
        if hasattr(self, 'training_config') and self.training_config:
            obs_params = self.training_config["observation_params"] if "observation_params" in self.training_config else {}
            
            # Validation stricte: obs_size DOIT être présent
            if "obs_size" not in obs_params:
                raise KeyError(
                    f"training_config missing required 'obs_size' in observation_params. "
                    f"Must be defined in training_config.json. "
                    f"Config: {self.training_config_name if hasattr(self, 'training_config_name') else 'unknown'}"
                )
            
            obs_size = obs_params["obs_size"]  # NO DEFAULT - raise error si manquant
            # `observation_params` ne porte plus que `obs_size` : les anciens parametres de
            # perception (perception_radius / max_nearby_units / max_valid_targets) etaient
            # propres au pipeline mono-figurine et ont ete supprimes avec lui (2026-07-28).
            # L'etendue percue par l'agent est desormais celle de la grille egocentrique
            # (`engine/spatial_grid.py`), qui est aussi celle du masque et du decodeur.
        else:
            # Pas de config = erreur (pas de valeur par défaut)
            raise ValueError(
                "W40KEngine requires training_config with observation_params.obs_size. "
                "No default value allowed."
            )

        # `obs_size` doit designer le layout squad EN VIGUEUR. Une valeur perimee construisait
        # auparavant un Box(obs_size) que RIEN ne sait remplir, et l'incoherence n'apparaissait
        # qu'a la 1re observation — alors que la cause reelle est « la config porte une taille
        # perimee ». C'est exactement le repli masquant que la convention projet interdit : le
        # layout squad change a chaque evolution du schema d'entites, donc ce cas se produit
        # VRAIMENT (rencontre le 2026-07-26 en portant le bloc figurines de 6 a 20 slots).
        _squad_obs_size = self.obs_builder.SQUAD_OBS_SIZE_TARGET
        if obs_size != _squad_obs_size:
            raise ValueError(
                f"observation_params.obs_size={obs_size} ne correspond pas au pipeline "
                f"d'observation : attendu {_squad_obs_size} (pipeline squad, taille calculee "
                f"par ObservationBuilder.SQUAD_OBS_SIZE_TARGET depuis le schema d'entites). "
                f"Si le layout squad vient de changer, mettre obs_size a {_squad_obs_size} dans "
                f"la config d'agent — et relancer un entrainement `--new` : les modeles existants "
                f"sont incompatibles par construction."
            )

        # Pipeline squad : obs Dict de TENSEURS D'ENTITES (V11 §0.30 T-D) + la grille
        # egocentrique (perception du terrain, spec §4.1), branche sur la policy via
        # MultiInputPolicy. Pipeline mono-fig legacy : Box inchange.
        #
        # Les formes viennent de ObservationBuilder.squad_obs_shapes() — source UNIQUE, jamais
        # recopiee ici. Bornes : les cles "_cont" portent des grandeurs BRUTES (une borne 0..1
        # mentirait sur des PV ou des subhex), les cles "_bin" des valeurs discretes dans
        # [-1, 1] (drapeaux, phase, controle d objectif).
        if obs_size == self.obs_builder.SQUAD_OBS_SIZE_TARGET:
            from engine.spatial_grid import GRID_CHANNELS, GRID_SIZE

            spaces_dict = {}
            for key, shape in self.obs_builder.squad_obs_shapes().items():
                if key.endswith("_bin"):
                    spaces_dict[key] = gym.spaces.Box(
                        low=-1.0, high=1.0, shape=shape, dtype=np.float32
                    )
                elif key.endswith("_ids"):
                    # Ensembles d'ids de capacites/statuts (chantier 01) : des INDEX de ligne
                    # d'embedding, bornes par le registre. Le Box DECLARE ce domaine (il decrit
                    # l'espace, pour SB3 et pour qui lit la config) ; il ne le FAIT PAS RESPECTER
                    # — rien ne valide jamais une observation contre son espace sur le chemin
                    # d'entrainement. C'est `observation_builder._fill_id_slots` qui leve, au site
                    # d'ecriture, ou l'erreur peut encore nommer l'escouade fautive.
                    from engine.observation_entities import OBS_ID_MAX

                    spaces_dict[key] = gym.spaces.Box(
                        low=0.0, high=float(OBS_ID_MAX), shape=shape, dtype=np.float32
                    )
                else:
                    spaces_dict[key] = gym.spaces.Box(
                        low=-np.inf, high=np.inf, shape=shape, dtype=np.float32
                    )
            spaces_dict["grid"] = gym.spaces.Box(
                low=0.0, high=1.0,
                shape=(GRID_CHANNELS, GRID_SIZE, GRID_SIZE), dtype=np.float32,
            )
            self.observation_space = gym.spaces.Dict(spaces_dict)
        else:
            self.observation_space = gym.spaces.Box(
                low=0.0, high=1.0, shape=(obs_size,), dtype=np.float32
            )
        
        # NOTE: last_unit_positions removed - now using game_state["units_cache_prev"] for movement_direction
        
        # Episode-level metrics accumulation for MetricsCollectionCallback
        self.episode_reward_accumulator = 0.0
        self.episode_length_accumulator = 0
        self.episode_number = int(training_episode_start_index)  # compteur d'episodes de CET env (offset de reprise inclus)
        # Épisode `auto` de la rampe : le MOTEUR choisit les poses du joueur-agent (cf.
        # `_configure_deployment_mode_for_episode`). Déclaré ici pour que `step` puisse le lire
        # même avant le premier reset, sans `getattr` de complaisance.
        self._deployment_auto_episode = False
        # Pose ARMÉE par `auto_deployment_action` et consommée par le `step` suivant : voir cette
        # méthode. Déclaré ici pour la même raison que la ligne au-dessus.
        self._auto_deployment_pending_action: Optional[int] = None

        # Clear debug.log ONCE at the start of training, only when --debug (avoid I/O when not debugging)
        global _debug_log_cleared
        if debug_mode and not _debug_log_cleared:
            movement_debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'debug.log')
            try:
                with open(movement_debug_path, 'w', encoding='utf-8', errors='replace') as f:
                    f.write("=== MOVEMENT DEBUG LOG ===\n")
                    f.write("Cleared at training session start\n")
                    f.write("=" * 80 + "\n\n")
                    f.flush()
                _debug_log_cleared = True
            except Exception as e:
                print(f"⚠️ Failed to clear debug.log: {e}")
        self.episode_tactical_data = _empty_episode_tactical_data()
        
        # ==================================================

    @staticmethod
    def _strip_phase_suffix(agent_key: str) -> str:
        """Strip optional phase suffix (_phase1.._phase4) from an agent key."""
        base_agent_key = agent_key
        for phase_suffix in ['_phase1', '_phase2', '_phase3', '_phase4']:
            if agent_key.endswith(phase_suffix):
                base_agent_key = agent_key[:-len(phase_suffix)]
                break
        return base_agent_key

    def _is_training_scenario_context(self) -> bool:
        """Return True when current scenario belongs to training split."""
        current_path = self._current_scenario_file
        if not isinstance(current_path, str) or not current_path.strip():
            return False
        normalized = current_path.replace("\\", "/")
        return "/scenarios/training/" in normalized

    def _episode_schedule_progress(self, episode_index: int, total_episodes: int) -> float:
        """Progression d'une rampe par-épisode. Le POURQUOI vit dans `engine/episode_schedule.py`.

        `n_envs` est lu dans `training_config`, où le chemin d'entraînement a écrit le nombre
        d'environnements RÉELLEMENT ouverts (cf. `training_n_envs` dans `__init__`).

        Le couple (total, n_envs) est invariant sur la vie d'un worker, mais les tests le
        remplacent après construction : on mémoïse sur sa valeur plutôt qu'à l'init, ce qui évite
        de revalider deux fois par épisode (une fois par rampe) pendant tout le run.
        """
        if not isinstance(self.training_config, dict):
            raise TypeError(
                "_episode_schedule_progress requires a training_config dict "
                f"(got {type(self.training_config).__name__})"
            )
        if not self._episode_ramp_n_envs_is_runtime:
            raise KeyError(
                "W40KEngine(training_n_envs=...) est OBLIGATOIRE pour jouer une rampe par-épisode "
                f"(profil '{self.training_config_name}') : le compteur d'épisodes du moteur est "
                "LOCAL à un environnement, donc la rampe se rapporte au nombre d'environnements "
                "RÉELLEMENT ouverts — que le profil ne connaît pas (il en déclare 48 même sous "
                "`--step`, qui n'en ouvre qu'un). Un site sériel passe 1. "
                "Cf. engine/episode_schedule.py."
            )
        budget = (int(total_episodes), self.training_config["n_envs"])
        if budget != self._episode_ramp_budget:
            self._episode_ramp_denominator = max(1, episodes_per_env(*budget) - 1)
            self._episode_ramp_budget = budget
        return min(1.0, max(0.0, float(max(0, episode_index)) / float(self._episode_ramp_denominator)))

    def _configure_deployment_mode_for_episode(self) -> Optional[str]:
        """Scheduler par-épisode du MODE de déploiement (auto ↔ active), rampé sur la progression.

        On choisit, par épisode, QUI décide des poses : le moteur (``auto``, tirage parmi les slots
        de pose ouverts) ou la politique (``active``). Les deux jouent une VRAIE phase de
        déploiement — c'est la seule différence, et elle porte sur le décideur, pas sur les règles.

        Contrat (training_config):
          deployment_mode_schedule:
            enabled: bool
            training_only: bool
            active_ratio_start: float in [0,1]   # proba 'active' au début du training
            active_ratio_end: float in [0,1]     # proba 'active' à la fin
            schedule: "linear"
            freeze_after_progress: float in [0,1]

        Retourne "active" | "auto" pour l'épisode, ou None si inactif (mode laissé au JSON).

        'auto' a remplacé 'fixed' le 2026-08-08. 'fixed' rejouait les positions par figurine
        écrites dans les rosters, sans phase de déploiement ; elles étaient générées hors ligne
        contre UN terrain et tombaient sur des murs dès qu'un second entrait dans la rotation.
        'auto' joue une vraie phase de déploiement dont le MOTEUR décide les poses.
        """
        if not isinstance(self.training_config, dict):
            return None
        cfg = self.training_config.get("deployment_mode_schedule")
        if cfg is None:
            # Un PROFIL d'entraînement DOIT porter le bloc. Le rendre optionnel désactivait la
            # rampe en silence : deux profils (`x5_append`, `x1_debug`) ont ainsi entraîné un
            # agent qui ne se déploie jamais, puis l'ont noté sur des parties à déployer —
            # l'évaluation impose TOUJOURS une phase de déploiement. Absence = erreur explicite,
            # jamais une valeur par défaut.
            if self._training_config_is_agent_profile:
                raise KeyError(
                    "training_config.deployment_mode_schedule est OBLIGATOIRE dans un profil "
                    f"d'entraînement (profil '{self.training_config_name}'). Sans ce bloc la "
                    "rampe de déploiement est silencieusement désactivée : l'agent n'apprend "
                    "jamais à se déployer alors que l'évaluation l'exige. Clés attendues : "
                    "enabled, training_only, active_ratio_start, active_ratio_end, schedule, "
                    "freeze_after_progress."
                )
            return None
        if not isinstance(cfg, dict):
            raise TypeError(
                "training_config.deployment_mode_schedule must be an object "
                f"(got {type(cfg).__name__})"
            )

        enabled = require_key(cfg, "enabled")
        if not isinstance(enabled, bool):
            raise TypeError(
                "training_config.deployment_mode_schedule.enabled must be bool "
                f"(got {type(enabled).__name__})"
            )
        if not enabled:
            return None

        training_only = require_key(cfg, "training_only")
        if not isinstance(training_only, bool):
            raise TypeError(
                "training_config.deployment_mode_schedule.training_only must be bool "
                f"(got {type(training_only).__name__})"
            )
        if training_only and not self._is_training_scenario_context():
            return None

        ratio_start = require_key(cfg, "active_ratio_start")
        ratio_end = require_key(cfg, "active_ratio_end")
        for name, val in (("active_ratio_start", ratio_start), ("active_ratio_end", ratio_end)):
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise TypeError(
                    f"training_config.deployment_mode_schedule.{name} must be number "
                    f"(got {type(val).__name__})"
                )
            if float(val) < 0.0 or float(val) > 1.0:
                raise ValueError(
                    f"training_config.deployment_mode_schedule.{name} must be in [0,1] (got {val})"
                )
        ratio_start = float(ratio_start)
        ratio_end = float(ratio_end)

        schedule = require_key(cfg, "schedule")
        if schedule != "linear":
            raise ValueError(
                "training_config.deployment_mode_schedule.schedule must be 'linear' "
                f"(got {schedule!r})"
            )
        freeze_after_progress = require_key(cfg, "freeze_after_progress")
        if not isinstance(freeze_after_progress, (int, float)) or isinstance(freeze_after_progress, bool):
            raise TypeError(
                "training_config.deployment_mode_schedule.freeze_after_progress must be number "
                f"(got {type(freeze_after_progress).__name__})"
            )
        freeze_after_progress = float(freeze_after_progress)
        if freeze_after_progress < 0.0 or freeze_after_progress > 1.0:
            raise ValueError(
                "training_config.deployment_mode_schedule.freeze_after_progress must be in [0,1] "
                f"(got {freeze_after_progress})"
            )

        total_episodes = require_key(self.training_config, "total_episodes")
        if not isinstance(total_episodes, int) or isinstance(total_episodes, bool):
            raise TypeError(
                "training_config.total_episodes must be integer "
                f"(got {type(total_episodes).__name__})"
            )
        if total_episodes <= 0:
            raise ValueError(f"training_config.total_episodes must be > 0 (got {total_episodes})")

        # Progression : self.episode_number est PRÉ-incrément à ce stade du reset (l'incrément a
        # lieu plus bas). Premier épisode → 0 → proba = active_ratio_start. Base cohérente avec
        # l'index utilisé par le loader (`_training_episode_index`).
        episode_index = max(0, int(self.episode_number))
        progress = self._episode_schedule_progress(episode_index, total_episodes)
        capped_progress = min(progress, freeze_after_progress)
        p_active = ratio_start + ((ratio_end - ratio_start) * capped_progress)
        p_active = min(1.0, max(0.0, p_active))

        mode = "active" if random.random() < p_active else "auto"
        self.game_state["deployment_mode_schedule_p_active"] = p_active
        self.game_state["deployment_mode_schedule_mode"] = mode
        self._deployment_auto_episode = mode == "auto"
        # `auto` charge le scenario en `active` : unites HORS TABLE, phase de deploiement jouee,
        # zones respectees. Seul change QUI decide des poses — le moteur, pas la politique.
        return "active" if mode == "auto" else mode

    def _should_auto_deploy_for_agent(self, action_mask: np.ndarray) -> bool:
        """True quand le MOTEUR doit choisir la pose a la place du joueur-agent (episode `auto`).

        C'est ce qui remplace l'ancien mode `fixed` de la rampe : au lieu de rejouer des positions
        ecrites dans le roster — hors zone de deploiement, et invalides des que le terrain change —
        l'episode joue une VRAIE phase de deploiement dont l'agent ne decide simplement pas encore.

        Strictement borne au joueur controle : l'adversaire a deja ses bots
        (`BotControlledEnv._select_bot_deploy_action`), et deployer a sa place ici les
        court-circuiterait en silence.
        """
        if not self._deployment_auto_episode:
            return False
        if self.game_state.get("phase") != "deployment":
            return False
        if not isinstance(action_mask, np.ndarray):
            raise TypeError(f"action_mask must be np.ndarray (got {type(action_mask).__name__})")
        if action_mask.size <= 0:
            return False
        current_player = int(require_key(self.game_state, "current_player"))
        controlled_player = int(require_key(self.config, "controlled_player"))
        return current_player == controlled_player

    def _pick_placement_action(self, action_mask: np.ndarray, context: str) -> int:
        """Tire une POSE parmi les slots de strategie ouverts. Jamais `ACTION_WAIT`.

        Source unique du filtre : `macro_intents.open_placement_slots` — la meme que celle des
        bots. Ce que ce detour achete est concret : `ACTION_WAIT` est ouvert au deploiement et n'y
        est PAS une attente, il met l'unite en RESERVES STRATEGIQUES (20.01). Un tirage uniforme
        sur le masque brut envoie donc des unites en reserves au hasard, ce que personne n'a
        demande — c'est le defaut mesure du chantier 04c, cote bots.
        """
        open_actions = [int(i) for i, value in enumerate(action_mask) if bool(value)]
        placements = open_placement_slots(open_actions)
        if not placements:
            # Pas de repli sur `ACTION_WAIT` : ce serait mettre l'unite en reserves pour masquer
            # un defaut moteur. Le decodeur leve « Deployment deadlock » avant d'en arriver la.
            raise RuntimeError(
                f"{context} : masque de deploiement sans aucun slot de pose "
                f"{list(DEPLOY_STRATEGY_SLOTS)} ouvert (actions ouvertes : {open_actions})."
            )
        return int(random.choice(placements))

    def auto_deployment_action(self, action_mask: np.ndarray) -> Optional[int]:
        """La pose que le MOTEUR joue pour le joueur-agent sur cet etat, ou None s'il ne pose pas.

        POINT D'ENTREE DE L'ABSORPTION. En episode `auto`, ces steps de deploiement ne sont PAS des
        decisions de la politique : la boucle d'entrainement les joue elle-meme
        (`BotControlledEnv._ensure_actionable_controlled_turn`) et ne les remonte jamais a
        l'apprenant. Sans ca, SB3 rangeait dans son rollout l'action ECHANTILLONNEE et son log_prob
        alors que `step` en executait une autre : PPO calculait son ratio sur une action jamais
        jouee (~10 steps de deploiement par episode, sur la part `auto` de la rampe).

        L'action rendue est ARMEE : le `step` qui la recoit l'execute telle quelle au lieu d'en
        tirer une seconde. Un appelant qui ne passe pas par ici (moteur nu : tests, scripts) voit
        toujours son action remplacee par une pose dans `step` — la ou aucun apprentissage ne se
        fait, le remplacement est le comportement voulu.
        """
        if not self._should_auto_deploy_for_agent(action_mask):
            self._auto_deployment_pending_action = None
            return None
        action = self._pick_placement_action(action_mask, "deployment_mode_schedule 'auto'")
        self._auto_deployment_pending_action = action
        return action

    def _build_reward_configs_for_current_units(self) -> Dict[str, Dict[str, Any]]:
        """Build reward config mapping for all units in current game state."""
        from config_loader import get_config_loader
        config_loader = get_config_loader()

        reward_configs: Dict[str, Dict[str, Any]] = {}
        controlled_agent = self.config.get("controlled_agent")
        units = require_key(self.game_state, "units")

        # Single-policy mode: use controlled agent rewards for every unit model key.
        if controlled_agent:
            base_agent_key = self._strip_phase_suffix(controlled_agent)
            agent_rewards = config_loader.load_agent_rewards_config(base_agent_key)
            controlled_rewards = require_key(agent_rewards, base_agent_key)
            reward_configs[controlled_agent] = controlled_rewards

            mapped_model_keys: Set[str] = set()
            for unit in units:
                unit_type = require_key(unit, "unitType")
                model_key = require_present(self.unit_registry, "unit_registry").get_model_key(unit_type)
                if model_key in mapped_model_keys:
                    continue
                reward_configs[model_key] = controlled_rewards
                mapped_model_keys.add(model_key)
            return reward_configs

        # Legacy mode: no controlled agent; load rewards per model key.
        for unit in units:
            unit_type = require_key(unit, "unitType")
            model_key = require_present(self.unit_registry, "unit_registry").get_model_key(unit_type)
            if model_key in reward_configs:
                continue
            agent_rewards = config_loader.load_agent_rewards_config(model_key)
            reward_configs[model_key] = require_key(agent_rewards, model_key)

        return reward_configs

    # ============================================================================
    # GYM INTERFACE - KEEP THESE CORE METHODS
    # ============================================================================
    
    def reset(self, *, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
        """Reset game state for new episode - gym.Env interface."""

        # Call parent reset for gym compliance
        super().reset(seed=seed)

        if seed is not None:
            random.seed(seed)

        should_reload_scenario = False
        current_controlled_player = int(require_key(self.config, "controlled_player"))
        if self._scenario_loaded_for_controlled_player != current_controlled_player:
            should_reload_scenario = True
        if self._random_scenario_mode and len(self._scenario_files) > 1:
            self._current_scenario_file = random.choice(self._scenario_files)
            should_reload_scenario = True
        elif self._scenario_has_random_agent_roster:
            should_reload_scenario = True

        # Scheduler par-épisode fixed↔active : impose un rechargement avec le mode tiré (rampé sur
        # la progression du training). None = scheduler inactif → mode laissé au JSON du scénario.
        #
        # La clé est posée à None AVANT l'appel pour qu'elle existe à CHAQUE épisode : le
        # scheduler ne l'écrit que sur son chemin actif (5 `return None` en amont), et une clé
        # tantôt présente tantôt absente forcerait ses lecteurs à un `.get` — donc à confondre
        # « scheduler inactif » avec « épisode où personne n'a rien écrit ».
        self.game_state["deployment_mode_schedule_mode"] = None
        # Même raison que la ligne au-dessus : le scheduler ne pose ce drapeau que sur son chemin
        # actif. Sans remise à False ici, un épisode `auto` contaminerait tous les suivants — le
        # moteur continuerait de déployer à la place d'une politique censée apprendre à le faire.
        self._deployment_auto_episode = False
        # Une pose armée et non consommée n'appartient qu'à l'épisode qui l'a demandée.
        self._auto_deployment_pending_action = None
        episode_deployment_mode = self._configure_deployment_mode_for_episode()
        if episode_deployment_mode is not None:
            should_reload_scenario = True

        # RANDOM SCENARIO SELECTION: Pick a random scenario for this episode
        if should_reload_scenario:
            self._reload_scenario(
                require_present(self._current_scenario_file, "_current_scenario_file"),
                deployment_type_override=episode_deployment_mode,
            )
            # Rebuild reward configs for units in the new scenario.
            reward_configs = self._build_reward_configs_for_current_units()
            self.game_state["reward_configs"] = reward_configs
            self.game_state["rewards_configs"] = reward_configs

        # ── Purges d'episode : `game_state` est le MEME objet d'un reset a l'autre et
        # `_reload_scenario` en change le contenu. Tout ce qui est memoise par episode DOIT
        # mourir ici, sinon il survit dans l'episode suivant sans que rien ne le signale.
        #
        # Grille spatiale (T1) : tableaux memoises de murs/objectifs. Sans purge, l'agent
        # observerait le terrain de l'episode precedent (corruption silencieuse de l'obs).
        self.game_state.pop("_grid_static_hex_arrays", None)
        # Hexes d'objectif par slot (distances/directions du contexte global). Meme raison que
        # ci-dessus : un scenario recharge change les zones, pas les cles du cache.
        # (Le cache des profils d'armes, lui, tombe dans `build_units_cache` — il est indexe par
        # figurines vivantes, donc lie a la reconstruction des caches, pas au scenario.)
        self.game_state.pop(ObservationBuilder.OBJECTIVE_HEX_ARRAYS_KEY, None)
        # Ancre de grille des escouades pas encore posees (§0.40 point 2) : elle derive du pool
        # de deploiement du joueur, que `_reload_scenario` remplace (autre terrain, autres zones).
        # Sans purge, l'agent deploierait en regardant la zone de l'episode precedent.
        self.game_state.pop("_grid_deployment_zone_anchor", None)
        # Candidats des slots de deploiement (§0.40 point 3) : l'hexe que chaque slot 4-8
        # poserait, lu par le decodeur ET par l'observation. Son tampon est l'etat des unites
        # posees — qui recommence IDENTIQUE (aucune unite posee) a chaque episode : sans purge,
        # le 1er step du nouvel episode servirait les candidats du terrain precedent.
        self.game_state.pop(DEPLOY_SLOT_CANDIDATES_CACHE_KEY, None)
        # Jumeau pour l'ingress move (20.04) : même raisonnement, même risque — son tampon est
        # l'état des unités posées + le round, qui recommencent identiques à chaque épisode.
        self.game_state.pop(INGRESS_SLOT_CANDIDATES_CACHE_KEY, None)
        # Cache de SCORING du deploiement (expositions LoS par hexe, allies par colonne). Il
        # n'etait purge NULLE PART : `reset_episode_caches` ne voit que les caches d'instance du
        # decodeur, pas ceux poses dans le game_state. Son garde-fou (« le jeu d'hexes valides
        # a-t-il change ? ») ne mord PAS au cas critique : un episode interrompu AVANT la 1re
        # pose laisse un cache dont le jeu d'hexes coincide exactement avec celui du nouvel
        # episode — servi tel quel, il porterait les expositions LoS des murs du terrain
        # PRECEDENT. Trouve le 2026-07-29 en verifiant §0.40 point 3, qui LIT ce cache pour
        # decrire les candidats a l'agent : la corruption y serait devenue une observation.
        self.game_state.pop(ActionDecoder.DEPLOYMENT_SCORING_CACHE_KEY, None)
        # Zones de terrain contenant un mur DENSE (Solid 13.11), memoisees par
        # `_squad_terrain_flags` pour le drapeau « gone to ground pret » (13.5). Elles derivent
        # de `terrain_areas` ET de `dense_wall_hexes`, que `_reload_scenario` remplace : sans
        # purge, un episode joue sur un autre terrain lisait les zones du precedent. Trouve le
        # 2026-07-28 — les tests d'observation la faisaient a la main, c'est ICI qu'elle
        # manquait (meme motif que §0.26).
        self.game_state.pop("_obs_solid_terrain_areas", None)
        # Cartes de cellules de move (T3) : elles portent les destinations du pool de l'episode
        # precedent. Leur tampon (ancre, phase) NE protege PAS ici — au nouvel episode l'escouade
        # peut se redeployer sur la meme ancre en phase move, le tampon coincide, et une carte
        # calculee sur d'AUTRES murs passerait le controle.
        self.game_state.pop("_squad_move_cell_maps", None)
        # Jets d'Advance pre-tires : `get_squad_action_mask_and_eligible_units` ne re-tire QUE si
        # la cle est absente. Un jet survivant a un episode interrompu (turn limit avec une
        # activation en cours) serait donc reutilise tel quel dans l'episode suivant, au lieu
        # d'etre re-tire (09.06 : un jet par Advance).
        self.game_state.pop("_squad_advance_rolls", None)
        # Derniere frontiere de phase/tour vue par `refresh_objective_control_on_boundary`. Sans
        # purge, elle porte encore ("fight", 5) de l'episode precedent : au premier build d'obs du
        # nouvel episode, (phase, tour) differe, le checkpoint 14.02 se declenche et fige des
        # controleurs AVANT que la moindre phase se soit terminee — alors que la methode documente
        # l'inverse (« debut de bataille : aucune frontiere franchie → aucun objectif controle »).
        self.game_state.pop("_objective_control_last_boundary", None)
        # Dernier instantane de controle/VP ecrit dans step.log. Il ne sert qu'a eviter de reecrire
        # une ligne identique ; survivant a l'episode, il ferait SAUTER l'instantane initial du
        # nouvel episode (memes controleurs vides et memes VP a 0), et le replay demarrerait sans
        # aucune donnee de controle.
        self.game_state.pop(self.OBJECTIVE_CONTROL_LOGGED_KEY, None)
        # Jumeau exact pour l'instantane d'ETAT : la cle porte un NUMERO DE TOUR, qui se repete
        # d'un episode a l'autre. Sans cette purge, l'episode 2 verrait « tour 1 deja ecrit » et
        # perdrait sa premiere ligne d'etat — donc le seul point de recalage de son debut.
        self.game_state.pop(self.STATE_SNAPSHOT_LOGGED_KEY, None)
        # Jumeau : sans la purge, l'episode 2 verrait « meme etat d'effets qu'a la fin de
        # l'episode 1 » et n'ecrirait jamais sa ligne initiale.
        self.game_state.pop(self.EFFECTS_SNAPSHOT_LOGGED_KEY, None)
        # Curseur de drainage : indexe `action_logs`, remis a zero avec elle a chaque episode.
        self.game_state.pop(self.STEP_LOG_DRAINED_KEY, None)
        # POINT DE PURGE UNIQUE de toutes les etapes « resolues une fois par (tour, joueur) » :
        # scoring du primaire, recompense d'objectif, penalite de coherency, cp_gain_on_objective,
        # evenements de choix de regle (cf. `engine.game_utils.once_claim`). Leurs cles sont
        # indexees sur le tour, donc elles se REPETENT d'un episode a l'autre : sans cette ligne,
        # chacune de ces etapes serait consideree resolue des l'episode 2 et ne se declencherait
        # plus jamais, en silence — MESURE sur `_choice_timing_fired_events` avant que la purge
        # existe, 3 episodes enchaines : 16 decisions, puis 2, puis 0.
        # Verrous : tests/unit/engine/test_once_claims_registry.py et
        # tests/unit/engine/test_agent_decision_mechanism.py::test_the_choice_mechanism_survives_the_first_episode.
        self.game_state.pop(ONCE_CLAIMS_KEY, None)

        # Choix d'escouade à activer (V11 §0.48 `L2`) : sa portée est (tour, phase, joueur), donc
        # elle REDEVIENT valide par coïncidence à l'épisode suivant — le tour repart à 1. Un
        # marqueur survivant supprimerait le premier choix de sa phase, en silence (vérifié :
        # marqueur posé en fin d'épisode, encore là après `reset(seed=1)`).
        self.game_state.pop(self.action_decoder.ACTIVATION_CHOSEN_KEY, None)

        # Reset episode-level metric accumulators
        self.episode_reward_accumulator = 0.0
        self.episode_length_accumulator = 0
        self.action_decoder.reset_episode_caches()
        
        # Increment episode number (original logic - works fine for everything except debug.log)
        self.episode_number += 1
        from config_loader import get_config_loader

        if not isinstance(self.is_pve_mode, bool):
            raise TypeError(f"is_pve_mode must be bool, got {type(self.is_pve_mode).__name__}")
        player_types = {
            "1": "human",
            "2": "ai" if self.is_pve_mode else "human",
        }
        
        # Reset game state
        self.game_state.update({
            "current_player": 1,
            "player_types": player_types,
            "phase": "command",
            "turn": 1,
            "episode_steps": 0,
            "unit_activation_count": 0,
            "episode_number": self.episode_number,
            "game_over": False,
            "turn_limit_reached": False,
            "winner": None,
            "victory_points": {1: 0, 2: 0},
            # Remise a la dotation de depart : un episode ne peut pas heriter des CP du
            # precedent (`reset` fait un `update()` de game_state, pas une recreation).
            "command_points": initial_command_points(get_config_loader().get_game_config()),
            "primary_objective": self._scenario_primary_objective,
            # Marqueurs « etape deja resolue » : purges par le `pop("_once_claims")` du bloc
            # ci-dessus, plus declares ici (cf. `engine.game_utils`).
            "controlled_objective_samples_scoring_turns": [],
            "opponent_objective_samples_scoring_turns": [],
            "zone_intents": [INTENT_INVADE] * MAX_OBJECTIVES,
            "zone_intent_free_steps_remaining": 0,
            "unit_zone_assignments": {},
            # Declarations d'intents en attente de solde, par joueur. REMISE A ZERO ICI parce
            # que `reset` fait un `update()` de game_state, pas une recreation : une declaration
            # non soldee (l'adversaire, ou l'agent sur un episode tronque) serait sinon soldee au
            # tour 1 de l'episode SUIVANT, contre un plateau sans aucun rapport.
            "_zone_intent_declarations": {},
            # Meme raison pour le solde DEJA CALCULE mais pas encore verse : il n'est poppe que
            # par une action non-zone-intent, et plusieurs chemins n'y arrivent jamais (fin de
            # partie pendant les free steps, sortie anticipee turn-limit, auto-advance). Il
            # atterrirait alors sur la premiere action de l'episode suivant.
            "_pending_zone_shaping": 0.0,
            "units_moved": set(),
            "moved_distance_by_model": {},
            "units_fled": set(),
            "units_cannot_charge": set(),
            "units_shot": set(),
            "units_shot_previous_turn": set(),
            "units_charged": set(),
            "units_advanced": set(),
            "advance_rolls": {},
            # 21.03 `L6` : declarations de vol, et « la question a ete posee » (distinct — un refus
            # laisse le set de declaration vide et doit malgre tout laisser une trace). Cles
            # DERIVEES de `_TAKE_TO_THE_SKIES_BY_PHASE`, comme au reset de tour.
            **movement_handlers.fly_declaration_reset_state(),
            "units_reacted_this_enemy_turn": set(),
            "reaction_window_active": False,
            "_unit_move_version": 0,
            "last_move_event_id": 0,
            "last_move_cause": "normal",
            "reactive_mode": "micro",
            "reactive_macro_order_current_window": [],
            "reactive_decision_mode": "auto",
            "reactive_decision_payload": {},
            "command_activation_pool": [],
            "move_activation_pool": [],
            "fight_subphase": None,
            "charge_range_rolls": {},
            "action_logs": [],  # CRITICAL: Reset action logs for new episode metrics
            "action_log_seq": 0,
            "log_delta": [],  # Combat log : events depuis la dernière row de timeline (voir init du game_state)
            **_reserves_game_state_defaults(),
            "gym_training_mode": self.gym_training_mode,  # ADDED: For handler access
            "debug_mode": self.debug_mode,  # ADDED: For handler access
            "console_logs": [],  # CRITICAL: Initialize console_logs for debug logging across all episodes
            "hex_los_cache": {},  # PERFORMANCE: Clear hex-coordinate LoS cache for new episode
            "objective_controllers": {},  # RESET: Clear objective control for new episode
            "pending_shooting_phase_init": False,
            "_pile_in_toCol": None,
            "_pile_in_toRow": None,
            # ── État des CHOIX DE RÈGLE / DÉCISIONS AGENT — purge d'épisode (V11 §9.3 P2) ──
            # `_choice_timing_fired_events` a rejoint le registre `_once_claims` (purgé par le
            # `pop` du bloc ci-dessus) : c'est la MÊME famille de marqueur que les quatre
            # autres, et c'est ici que son mode de défaillance a été observé pour de vrai.
            # Une décision ou un prompt encore en attente appartient à la partie qui vient de
            # finir : les laisser vivre ferait démarrer l'épisode suivant bloqué sur un choix
            # portant sur une unité qui n'existe plus.
            "pending_rule_choice_queue": [],
            "active_rule_choice_prompt": None,
            "pending_agent_decision": None,
            # ── CAPACITÉS DE FACTION (chantier 03) — purge d'épisode ──
            # Waaagh! est « once per battle » : sans cette remise à zéro, un agent qui l'a appelé
            # à l'épisode N ne pourrait plus jamais l'appeler. Même famille de marqueur que les
            # trois clés ci-dessus, même mode de défaillance.
            **initial_faction_ability_state(),
        })
        self.game_state["deployment_type"] = self.config.get("deployment_type")
        self.game_state["deployment_type_by_player"] = self.config.get("deployment_type_by_player")
        self.game_state["deployment_zone"] = self.config.get("deployment_zone")
        objectives = require_key(self.game_state, "objectives")
        assert len(objectives) <= MAX_OBJECTIVES, (
            f"Scenario has {len(objectives)} objectives but MAX_OBJECTIVES={MAX_OBJECTIVES}."
        )
        self._episode_step_calls = 0  # Safety: reset for runaway truncation check in step()
        # Profondeur de la chaine d'attentes forcees auto-jouees (cf. `step_with_mask`). Initialise
        # ici, comme le compteur ci-dessus : un `getattr` avec defaut au site chaud cacherait
        # l'attribut au typage et paierait le defaut a chaque chaine.
        self._forced_wait_depth = 0
        # (`_step_calls_since_increment` vivait ici : il n'alimentait que le `step_calls_since_last`
        #  des `log_action` du bloc step_logger de `_process_semantic_action`, supprime le
        #  2026-07-29 — voir la pierre tombale dans cette methode. Plus aucun lecteur.)

        # Reset unit health and positions to original scenario values
        # AI_TURN.md COMPLIANCE: Direct access - units must be provided
        if "units" not in self.config:
            raise KeyError("Config missing required 'units' field during reset")
        unit_configs = self.config["units"]
        for unit in self.game_state["units"]:
            # Clear transient shooting state from previous episode.
            # These fields are activation-scoped and must never leak across reset.
            transient_shoot_fields = (
                "valid_target_pool",
                "_pool_from_cache",
                "_pool_cache_key",
                "TOTAL_ATTACK_LOG",
                "selected_target_id",
                "activation_position",
                "_shooting_with_close_quarters",
                "_manual_weapon_selected",
                "manualWeaponSelected",
                "_shoot_activation_started",
                "_pending_move_after_shooting",
                "_move_after_shooting_destinations",
                "_move_after_shooting_resolved",
                "_move_after_shooting_distance",
                "_current_shoot_nb",
                # Les 7 champs `_rapid_fire_*` ont ete retires le 2026-07-29 (V11 §0hist.38) :
                # plus rien ne les ecrit depuis que [RAPID FIRE] 24.30 est resolu a la
                # constitution du pool d attaques (`_manual_roll_intent`). Purger une cle que
                # personne ne pose n a aucun effet, mais laisse croire a un etat qui existe.
            )
            for field_name in transient_shoot_fields:
                if field_name in unit:
                    del unit[field_name]

            # PR4 4c : pour un squad multi-fig, HP_CUR au niveau unit = somme des HP_MAX
            # PAR FIGURINE. Surtout PAS `HP_MAX * model_count` : `unit["HP_MAX"]` porte le
            # profil de BASE, donc cette formule perdait les PV des personnages attaches
            # (19.01) — une escouade a 21 PV annonces pour 26 reellement repartis, puis un
            # total qui AUGMENTE a la premiere perte, `_recompute_squad_hp_total` sommant
            # lui les figurines reelles. Une seule definition, celle des figurines.
            # Sinon HP_CUR == HP_MAX (mono-fig).
            # Une figurine sans override porte le profil de l escouade : meme convention
            # que le constructeur de models_cache (shared_utils.py:778,
            # `spec.get("HP_MAX", hp_max)`), pour que les deux donnent le meme total.
            if isinstance(unit.get("models"), list) and unit["models"]:
                _unit_hp_max = int(require_key(unit, "HP_MAX"))
                unit["HP_CUR"] = sum(
                    int(m["HP_MAX"]) if "HP_MAX" in m else _unit_hp_max for m in unit["models"]
                )
            else:
                unit["HP_CUR"] = unit["HP_MAX"]

            # CRITICAL: Reset shooting state per episode
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon or first weapon
            from engine.utils.weapon_helpers import get_selected_ranged_weapon, get_selected_melee_weapon
            
            # Initialize SHOOT_LEFT from selected ranged weapon
            selected_rng_weapon = get_selected_ranged_weapon(unit)
            if selected_rng_weapon:
                unit["SHOOT_LEFT"] = resolve_dice_value(
                    require_key(selected_rng_weapon, "NB"),
                    "reset_shoot_left",
                )
            elif ranged_weapons(unit):
                unit["SHOOT_LEFT"] = resolve_dice_value(
                    require_key(unit["RNG_WEAPONS"][0], "NB"),
                    "reset_shoot_left_fallback",
                )
            else:
                unit["SHOOT_LEFT"] = 0
            
            # Initialize ATTACK_LEFT from selected melee weapon
            selected_cc_weapon = get_selected_melee_weapon(unit)
            if selected_cc_weapon:
                unit["ATTACK_LEFT"] = resolve_dice_value(
                    require_key(selected_cc_weapon, "NB"),
                    "reset_attack_left",
                )
            elif melee_weapons(unit):
                unit["ATTACK_LEFT"] = resolve_dice_value(
                    require_key(unit["CC_WEAPONS"][0], "NB"),
                    "reset_attack_left_fallback",
                )
            else:
                unit["ATTACK_LEFT"] = 0

            # Find original position from config - match by string conversion
            unit_id_str = str(unit["id"])
            original_config = None
            for cfg in unit_configs:
                if str(cfg["id"]) == unit_id_str:
                    original_config = cfg
                    break

            if original_config:
                unit["col"], unit["row"] = normalize_coordinates(original_config["col"], original_config["row"])
                # ETAT DE MISE EN PLACE — restaure depuis la MEME source que la position, et pour
                # la meme raison : les objets `unit` SURVIVENT d'un episode a l'autre (mesure :
                # 10/10 reutilises), donc tout champ mute pendant l'episode et non restaure ici
                # fuit sur le suivant. La position l'etait deja ; ces trois-la ne l'etaient pas.
                #
                # Consequence mesuree, et elle rendait le chantier 04 inerte : une unite declaree
                # en reserves par son roster (20.01) arrive pendant l'episode 1, ce qui met
                # `in_strategic_reserves` a False (`_apply_deploy_plan`, source unique du passage
                # hors table -> table). Au reset de l'episode 2 elle repartait donc SANS reserve.
                # Un roster a `strategic_reserves: true` ne se comportait comme tel qu'au PREMIER
                # episode de chaque worker — soit une poignee sur des milliers en entrainement.
                #
                # `deployed_on_turn` est le jumeau de `col` (cf. `entry_is_on_battlefield`) : il se
                # restaure ICI, avec elle, pour TOUS les modes de deploiement. Le mode 'active'
                # remet ensuite la sentinelle et le repasse a None (plus bas) — il deplace l'unite
                # hors table quelle que soit la position du scenario.
                # Valeurs relues avec EXACTEMENT la semantique de `create_unit` (game_state.py),
                # qui est la definition de ces champs a la mise en place — et non un defaut muet :
                # une config de scenario ecrite a la main (fixture moteur nu) ne porte aucune de
                # ces cles, alors que la config issue du chargeur les porte toutes.
                unit["deployed_on_turn"] = (
                    None if int(original_config["col"]) < 0 else 0
                )
                unit["in_strategic_reserves"] = bool(
                    original_config.get(  # get allowed (2 sources, cf. `create_unit`)
                        "in_strategic_reserves",
                        original_config.get("strategic_reserves", False),
                    )
                )
                unit["reserves_repositioned"] = bool(
                    original_config.get("reserves_repositioned", False)  # get allowed (idem)
                )
            else:
                raise ValueError(f"Unit {unit['id']} not found in scenario config during reset")
        
        # Build units_cache once after all units are initialized (single source of truth)
        build_units_cache(self.game_state)
        rebuild_choice_timing_index(self.game_state)

        # Nombre de FIGURINES reellement en jeu : base des gardes anti-runaway, qui sont
        # comptes par action et donc par figurine. Releve ici (et pas en config) pour que
        # les plafonds suivent le roster charge — une escouade de 20 ne se borne pas comme
        # une unite seule. Invalide le cache : le meme moteur peut etre reset sur un autre
        # scenario, avec un nombre de figurines different.
        self._model_count = sum(
            len(mids) for mids in require_key(self.game_state, "squad_models").values()
        )
        if self._model_count <= 0:
            raise ValueError("reset produced zero models: cannot derive runaway step limits")
        self._episode_step_limit_cache = None
        # Initialize units_cache_prev for first step (Phase 2: units_cache always exists after reset)
        uc = require_key(self.game_state, "units_cache")
        self.game_state["units_cache_prev"] = {
            uid: {"col": d["col"], "row": d["row"], "HP_CUR": d["HP_CUR"], "player": d["player"]}
            for uid, d in uc.items()
        }

        self.game_state["_best_weapon_cache"] = build_best_weapon_cache(
            self.game_state["units"],
            require_key(self.game_state, "weapon_damage_table"),
            uc,
        )

        # Load AI model for PvE mode after units_cache is built
        if self.is_pve_mode and self.pve_controller.ai_model is None:
            self.pve_controller.load_ai_model_for_pve(self.game_state, self)

        deployment_type = self.config.get("deployment_type")
        deployment_type_by_player = self.config.get("deployment_type_by_player")
        effective_deployment_type_by_player = {1: deployment_type, 2: deployment_type}
        if isinstance(deployment_type_by_player, dict):
            p1_type = deployment_type_by_player.get(1, deployment_type_by_player.get("1", deployment_type))
            p2_type = deployment_type_by_player.get(2, deployment_type_by_player.get("2", deployment_type))
            effective_deployment_type_by_player = {1: p1_type, 2: p2_type}
        # ZONES DE DEPLOIEMENT — donnee de SCENARIO, publiee QUEL QUE SOIT le mode de mise en
        # place. Elles ont longtemps vecu dans `deployment_state`, lui-meme ecrit uniquement quand
        # un joueur deploie en `active`. Or deux lecteurs en ont besoin HORS phase de deploiement :
        # la clause « aucune figurine dans la zone adverse avant le 3e round » de l'ingress 20.04
        # (`_opponent_deployment_zone_cells`) et l'ancre de grille d'une escouade hors table
        # (`squad_grid_anchor`). En mode `fixed`, une unite en reserves 20.01 est hors table DES LE
        # RESET : les deux levaient « Required key 'deployment_state' », et le reset entier avec.
        # La ZONE ne depend pas du mode de mise en place ; seule la PHASE en depend.
        scenario_deployment_pools = self.config.get("deployment_pools")
        if scenario_deployment_pools is None:
            # Scenario sans zones declarees : on RETIRE la cle plutot que d'en laisser une perimee
            # d'un episode precedent. Les lecteurs levent alors explicitement (require_key).
            self.game_state.pop("deployment_pools", None)
        else:
            self.game_state["deployment_pools"] = scenario_deployment_pools
        if any(
            effective_deployment_type_by_player[player_id] == "active"
            for player_id in (1, 2)
        ):
            if scenario_deployment_pools is None:
                raise KeyError("deployment_pools is required for active deployment")
            deployable_units = {1: [], 2: []}
            for unit in self.game_state["units"]:
                unit_player = require_key(unit, "player")
                unit_player_int = int(unit_player)
                player_deployment_type = effective_deployment_type_by_player.get(unit_player_int)
                if player_deployment_type is None:
                    raise ValueError(f"Missing deployment type for player {unit_player_int}")
                # 20.01 — une unité en réserves n'est PAS déployable : elle n'entre pas dans
                # `deployable_units`, donc ni dans l'alternance des déployeurs ni dans le masque
                # de déploiement. Elle arrivera par un ingress move (20.04). Sa position reste la
                # sentinelle hors table posée par le chargeur.
                if require_key(unit, "in_strategic_reserves"):
                    continue
                if player_deployment_type == "active":
                    set_unit_coordinates(unit, -1, -1)
                    # JUMEAU OBLIGATOIRE de la sentinelle. `deployed_on_turn` et `col >= 0` sont
                    # les deux faces du meme etat (cf. `entry_is_on_battlefield`) : les deux
                    # autres ecrivains du « hors table » les posent ENSEMBLE (`_apply_deploy_plan`
                    # pour l'arrivee, `reposition_unit_to_strategic_reserves` 20.02 pour le
                    # retrait). Ce troisieme ecrivain ne remettait que la position, et les objets
                    # `unit` SURVIVENT d'un episode a l'autre : au reset de l'episode 2, les 10
                    # unites mesurees etaient a col=-1 avec `deployed_on_turn=0` herite de
                    # l'episode 1. L'observation batit son `on_battlefield` sur ce champ — elle
                    # declarait donc « posees » des escouades a la sentinelle, et [HEAVY] 24.16 le
                    # lit aussi. Fuite inter-episodes, invisible tant que rien ne levait.
                    unit["deployed_on_turn"] = None
                    if unit_player_int == 1:
                        deployable_units[1].append(str(unit["id"]))
                    elif unit_player_int == 2:
                        deployable_units[2].append(str(unit["id"]))
                    else:
                        raise ValueError(f"Invalid unit player for deployment: {unit_player}")
                elif player_deployment_type in ("fixed", "random"):
                    # Keep scenario-provided coordinates for fixed/random players.
                    pass
                else:
                    raise ValueError(
                        f"Invalid deployment type for player {unit_player_int}: {player_deployment_type}"
                    )
            # Rebuild cache after forcing active-deployment units to (-1, -1).
            build_units_cache(self.game_state)
            rebuild_choice_timing_index(self.game_state)
            uc = require_key(self.game_state, "units_cache")
            self.game_state["units_cache_prev"] = {
                uid: {"col": d["col"], "row": d["row"], "HP_CUR": d["HP_CUR"], "player": d["player"]}
                for uid, d in uc.items()
            }
            self.game_state["deployment_type"] = deployment_type
            self.game_state["deployment_type_by_player"] = effective_deployment_type_by_player
            self.game_state["deployment_zone"] = self.config.get("deployment_zone")
            # `deployment_pools` N'EST PLUS ici : les zones sont publiees plus haut dans
            # `game_state["deployment_pools"]`, source UNIQUE valable dans tous les modes.
            # `deployment_state` ne porte plus que la comptabilite MUTABLE de la phase.
            self.game_state["deployment_state"] = {
                "current_deployer": 1,
                "deployable_units": deployable_units,
                "deployed_units": set(),
                "deployment_complete": False
            }
            if not deployable_units[1] and deployable_units[2]:
                self.game_state["deployment_state"]["current_deployer"] = 2
            if not deployable_units[1] and not deployable_units[2]:
                self.game_state["deployment_state"]["deployment_complete"] = True
                cmd_result = self.start_command_phase()
                if not (cmd_result and cmd_result.get("phase_complete") is False):
                    movement_handlers.movement_phase_start(self.game_state)
            else:
                deployment_handlers.deployment_phase_start(self.game_state)
        else:
            # Initialize command phase for game start using handler delegation
            # Phase 2: if command_phase_start returns phase_complete=False (free steps active),
            # stay in command phase — agent will issue zone intent actions first.
            cmd_result = self.start_command_phase()
            if not (cmd_result and cmd_result.get("phase_complete") is False):
                movement_handlers.movement_phase_start(self.game_state)
        self.episode_tactical_data = _empty_episode_tactical_data()
        # Compte initial des réserves déclarées dans le roster (strategic_reserves: true).
        # Le hook dans deployment_place_in_strategic_reserves ajoute ensuite les unités placées
        # manuellement pendant la phase de déploiement active. Les deux sources s'additionnent.
        controlled_player_for_reserves = get_controlled_player(self.game_state)
        self.game_state["_reserves_placed_agent"] = sum(
            1 for u in require_key(self.game_state, "units")
            if u.get("in_strategic_reserves", False)
            and int(require_key(u, "player")) == controlled_player_for_reserves
        )

        # Log episode start with all unit positions, walls, and objectives
        if hasattr(self, 'step_logger') and self.step_logger and self.step_logger.enabled:
            # Extract scenario name: prefer config "name", otherwise use filename pattern
            scenario_name = self.config.get("name")
            if not scenario_name or scenario_name == "Unknown Scenario":
                # Extract from filename: AgentName_scenario_phase1-bot3.json -> phase1-bot3
                if self._current_scenario_file:
                    filename = os.path.basename(self._current_scenario_file)
                    # Match pattern: *_scenario_*.json
                    import re
                    match = re.search(r'_scenario_(.+?)\.json$', filename)
                    if match:
                        scenario_name = match.group(1)
                    else:
                        # Use filename without extension
                        scenario_name = os.path.splitext(filename)[0]
                else:
                    scenario_name = "Unknown Scenario"
            
            # Determine bot_name for self-play (default to "SelfPlay" if not set)
            bot_name = None
            if hasattr(self.step_logger, 'current_bot_name') and self.step_logger.current_bot_name:
                bot_name = self.step_logger.current_bot_name
            else:
                # In self-play mode, use a default name
                bot_name = "SelfPlay"
            
            # Use _scenario_wall_hexes (set during scenario loading) - convert to step_logger format
            raw_walls = self._scenario_wall_hexes if self._scenario_wall_hexes is not None else []
            walls = [{"col": normalize_coordinates(w[0], w[1])[0], "row": normalize_coordinates(w[0], w[1])[1]} for w in raw_walls] if raw_walls else []
            # Use _scenario_objectives (set during scenario loading)
            objectives = self._scenario_objectives
            
            # Single source of truth: episode_units from units_cache (col, row, player); unitType from units
            uc = require_key(self.game_state, "units_cache")
            unit_by_id = {str(u["id"]): u for u in self.game_state["units"]}
            episode_units = []
            for uid, entry in uc.items():
                unit = unit_by_id.get(uid)
                if unit is None:
                    raise ValueError(f"units_cache contains unknown unit id {uid}")
                unit_type = require_key(unit, "unitType")
                hp_max = require_key(unit, "HP_MAX")
                episode_units.append({
                    "id": uid,
                    "col": entry["col"],
                    "row": entry["row"],
                    "player": entry["player"],
                    "unitType": unit_type,
                    "HP_MAX": hp_max,
                    "BASE_SIZE": require_key(unit, "BASE_SIZE"),
                    "BASE_SHAPE": require_key(unit, "BASE_SHAPE"),
                    # Positions per-figurine initiales (deploiement) : occupied_hexes_by_model est
                    # peuple au build du cache (reset), donc valable ici. Permet au replay d'afficher
                    # tous les socles des le debut, pas seulement l'ancre.
                    "models_segment": self._models_segment_for_unit(uid),
                    # Datasheet PAR FIGURINE : une escouade n'est pas homogène (règle 19,
                    # sergents, armes spéciales). Cf. `_model_types_segment_for_unit`.
                    "model_types_segment": self._model_types_segment_for_unit(uid, unit_type),
                })
            board_cols = self.game_state["board_cols"]
            board_rows = self.game_state["board_rows"]
            inches_to_subhex = self.game_state["inches_to_subhex"]
            _board_default = require_key(self.config, "board")
            _board_default = _board_default.get("default", _board_default)
            hex_radius = require_key(_board_default, "hex_radius")
            margin = require_key(_board_default, "margin")
            # Contrainte MIROIR de `ai.scenario_scratch` : les deux producteurs de scénarios
            # matérialisés (override de wall_ref à l'éval et à l'entraînement) écrivent sous la
            # racine, ce contrôle le constate. Les laisser écrire dans /tmp faisait échouer ici
            # tout épisode journalisé.
            scenario_path_logged = repo_relative_scenario_path(self._current_scenario_file)
            self.step_logger.log_episode_start(
                episode_units,
                scenario_name,
                bot_name=bot_name,
                walls=walls,
                objectives=objectives,
                primary_objective_config=self._scenario_primary_objective,
                roster_info=self._scenario_roster_info,
                board_config={
                    "cols": board_cols,
                    "rows": board_rows,
                    "inches_to_subhex": inches_to_subhex,
                    "hex_radius": hex_radius,
                    "margin": margin,
                },
                scenario_path=scenario_path_logged,
                run_rules=self._run_rules_for_step_log(),
            )
            
            # CRITICAL: Synchronize game_state["episode_number"] with step_logger.episode_number
            # This ensures debug.log uses the same episode number as step.log
            # step_logger.episode_number was incremented in log_episode_start()
            self.game_state["episode_number"] = self.step_logger.episode_number
        
        if self.game_state.get("deployment_type") == "active":
            self.game_state["phase"] = "deployment"
            deployment_state = self.game_state.get("deployment_state")
            if deployment_state is not None:
                self.game_state["current_player"] = int(require_key(deployment_state, "current_deployer"))
        # Initialise unit_zone_assignments avant le premier obs build (command phase pas encore atteinte).
        # Couvre le cas déploiement (command_phase_start pas encore appelé) et le tour bot en reset.
        if not self.game_state.get("unit_zone_assignments"):
            assignments = {}
            for unit in self.game_state["units"]:
                if unit.get("col", -1) >= 0 and unit.get("row", -1) >= 0:
                    assignments[str(unit["id"])] = get_nearest_objective_zone(unit, self.game_state)
                else:
                    assignments[str(unit["id"])] = 0  # Unité non déployée : zone 0 par défaut
            self.game_state["unit_zone_assignments"] = assignments
        observation = self._build_observation()
        info = {"phase": self.game_state["phase"]}
        
        return observation, info    
    
    def get_turn_step_limit(self) -> int:
        """Plafond anti-runaway d'UN tour de joueur, pour le moteur et ses wrappers.

        Derive du nombre de figurines relevé au reset (cf. compute_turn_step_limit) : les
        wrappers doivent borner leurs boucles sur la MEME source que le moteur, sinon
        l'un coupe des parties que l'autre juge encore valides.
        """
        from config_loader import compute_turn_step_limit
        return compute_turn_step_limit(
            require_key(self.config, "game_rules"), self._get_model_count()
        )

    def _get_model_count(self) -> int:
        """Nombre de figurines en jeu, relevé au reset."""
        model_count = getattr(self, "_model_count", None)
        if model_count is None:
            raise RuntimeError(
                "model count unavailable: reset() must run before deriving step limits"
            )
        return int(model_count)

    def _get_episode_step_limit(self) -> Optional[int]:
        """Plafond anti-runaway de l'episode, derive et memoise.

        Derive (et non constant) pour suivre le roster charge et le nombre de tours :
        cf. compute_episode_step_limit. Memoise car releve une fois par reset ; le cache
        est invalide a chaque reset, un meme moteur pouvant rejouer un autre scenario.
        L'absence des cles de config reste une erreur explicite, jamais un defaut.

        None en duree illimitee (Endless Duty) : une partie sans fin n'a pas de borne
        d'episode. Le garde par TOUR reste actif et suffit a detecter une boucle infinie.
        """
        if get_effective_turn_limit(self.game_state) is None:
            return None
        if self._episode_step_limit_cache is None:
            from config_loader import compute_episode_step_limit
            self._episode_step_limit_cache = compute_episode_step_limit(
                require_key(self.config, "game_rules"), self._get_model_count()
            )
        return self._episode_step_limit_cache

    def step(
        self, action: int
    ) -> Tuple[Optional[Dict[str, np.ndarray]], float, bool, bool, Dict[str, Any]]:
        """Interface gym.Env — 5-uplet fixe. L'implementation est ``step_with_mask``.

        Le 5-uplet de gym n'a pas de place pour le masque, et gym.Wrapper.step ne transmet que
        l'action : un appelant qui a DEJA le masque de l'etat courant, ou qui voudrait celui de
        l'etat de sortie, ne peut ni le donner ni le recevoir par ici. C'est ``step_with_mask`` qui
        ouvre les deux sens, pour les appelants qui tiennent une reference au moteur
        (``ai/env_wrappers``). Ici, les deux sont simplement ignores.
        """
        observation, reward, terminated, truncated, info, _mask = self.step_with_mask(action)
        return observation, reward, terminated, truncated, info

    def _drain_forced_waits(
        self,
        observation: Any,
        reward: float,
        terminated: bool,
        truncated: bool,
        info: Dict[str, Any],
        out_mask: Optional[Tuple[np.ndarray, List[Dict[str, Any]]]],
        actor: int,
    ) -> Tuple[Any, float, bool, bool, Dict[str, Any], Optional[Tuple[np.ndarray, List[Dict[str, Any]]]]]:
        """Joue les attentes que le masque IMPOSE, au lieu de rendre la main pour rien.

        Si l'etat de sortie n'ouvre que `wait`, rendre la main a l'agent revient a lui poser une
        question a une seule reponse : un aller-retour complet moteur <-> politique (forward du
        reseau compris) pour zero information. Volume mesure : cf. `RewardCalculator._wait_reward`.

        APPELEE AUX DEUX SORTIES NON TERMINALES de `step_with_mask` — le retour final ET celui de
        la transition de phase automatique (pool vide). Accrochee a une seule, l'economie se serait
        appliquee « selon le chemin emprunte », ce qui est pire qu'une economie absente : le nombre
        de steps d'un episode dependrait d'un detail d'implementation.

        RE-ENTRANTE PAR CONCEPTION : on rejoue par `step_with_mask` lui-meme, jamais par un chemin
        d'execution parallele. Le log (`_flush_squad_action_logs_to_step_logger`), les compteurs
        (`episode_steps`, `action_family_counts`) et le garde anti-runaway (`_episode_step_calls`)
        restent donc EXACTEMENT ceux d'un step joue par l'agent : un `wait` auto-joue est un vrai
        step du moteur, et s'il ne se comptait pas comme tel, la calibration du plafond de tour
        (figurines x actions x marge) ne voudrait plus rien dire et le replay divergerait.

        `actor` BORNE LA CHAINE AU JOUEUR QUI VIENT D'AGIR. Sans lui, une chaine franchissant la
        frontiere de tour ferait jouer par le moteur les attentes de L'ADVERSAIRE a l'interieur du
        step de l'agent, et `info` rendrait son `acting_player` / `is_controlled_action`.
        Atteignable : `command_phase_start` pose `zone_intent_free_steps_remaining = 0` sur un tour
        non-agent, ce qui reduit a `wait` le masque de commandement du bot.

        CUMUL DE LA RECOMPENSE, et ce n'est pas cosmetique : la branche `squad_wait` ajoute
        `objective_turn_reward` APRES la penalite, donc une attente forcee peut porter une
        recompense d'objectif non nulle meme si sa part `base_actions` vaut 0. La perdre
        deplacerait silencieusement du reward hors du retour d'episode.
        """
        if terminated or truncated:
            return observation, reward, terminated, truncated, info, out_mask
        if int(require_key(self.game_state, "current_player")) != actor:
            return observation, reward, terminated, truncated, info, out_mask
        if out_mask is None:
            # Masque de sortie non construit : on ne draine pas, et on ne le RECONSTRUIT pas. Les
            # trois seuls etats concernes (`_build_observation_and_mask`) sont une decision d'agent
            # en attente — masque reduit aux `CHOICE_i` —, la phase de deploiement — au moins un
            # slot de pose ouvert, `wait` n'y etant jamais seul —, et `game_over`. Aucun ne peut
            # produire un masque reduit a `wait` : la reponse du test est connue d'avance, la payer
            # serait un build de masque complet par step de deploiement, et ce serait en prime une
            # seconde route vers l'etat de sortie, a cote de la source unique observation+masque.
            return observation, reward, terminated, truncated, info, out_mask
        if not _mask_only_opens_wait(out_mask[0]):
            return observation, reward, terminated, truncated, info, out_mask

        self._forced_wait_depth += 1
        try:
            if self._forced_wait_depth > FORCED_WAIT_CHAIN_LIMIT:
                # LEVE au lieu de rendre un etat plausible : la chaine se draine d'elle-meme
                # (chaque attente retire une escouade de son pool), donc la depasser n'est pas un
                # cas de jeu mais une boucle — et un episode fige et silencieux couterait des
                # heures avant d'etre remarque.
                raise RuntimeError(
                    f"Chaine d'attentes forcees > {FORCED_WAIT_CHAIN_LIMIT} sans qu'aucune action "
                    f"ne s'ouvre (tour {self.game_state.get('turn')}, phase "
                    f"{self.game_state.get('phase')}) : le masque est bloque sur `wait`."
                )
            observation, chain_reward, terminated, truncated, chain_info, out_mask = self.step_with_mask(
                SQUAD_ACTION_WAIT, mask_and_eligible=out_mask
            )
            reward += chain_reward
            # `info` DECRIT L'ACTION DE L'APPELANT, il ne doit pas devenir celle de l'attente que le
            # moteur s'est jouee a lui-meme : `ai/env_wrappers.AGENT_STEP_INFO_KEYS` (action,
            # success, phase, intent_value, zone_control, charge_succeeded, is_controlled_action)
            # est preleve APRES le retour du moteur. L'ecraser ferait disparaitre la DERNIERE action
            # reelle de chaque phase — dont le `zone_intent` qui, en mettant
            # `zone_intent_free_steps_remaining` a 0, produit justement un masque reduit a `wait`.
            # Seules les cles de FIN D'EPISODE sont reprises de la chaine : elles decrivent l'etat
            # final, pas l'action.
            for key in TERMINAL_INFO_KEYS:
                if key in chain_info:
                    info[key] = chain_info[key]
        finally:
            self._forced_wait_depth -= 1
        return observation, reward, terminated, truncated, info, out_mask

    def step_with_mask(
        self,
        action: int,
        mask_and_eligible: Optional[Tuple[np.ndarray, List[Dict[str, Any]]]] = None,
    ) -> Tuple[
        Optional[Dict[str, np.ndarray]],
        float,
        bool,
        bool,
        Dict[str, Any],
        Optional[Tuple[np.ndarray, List[Dict[str, Any]]]],
    ]:
        """
        Execute gym action with built-in step counting - gym.Env interface.

        L'observation vaut ``None`` — et seulement dans ce cas — quand l'appelant a arme
        ``defer_observation`` : il s'est alors engage a construire l'observation finale lui-meme
        (cf. ``_step_observation`` et ``BotControlledEnv.step``). Le type l'expose au lieu de le
        cacher : un appelant qui ignore ce contrat doit se faire signaler ici, pas plus loin.

        ``mask_and_eligible`` (ENTREE) — masque et pool deja construits par l'appelant pour l'etat
        d'ENTREE. Mesure : le wrapper d'entrainement construisait ce masque pour savoir a qui est la
        decision, puis cette fonction le reconstruisait a l'identique juste apres (124,2 fois par
        episode, 100 % des reconstructions rendant un couple bit-a-bit identique). Meme regle que
        ``_build_observation`` : l'appelant doit pouvoir PROUVER que rien n'a touche ``game_state``
        entre sa construction et cet appel. ``W40K_MASK_VERIFY=2`` recalcule et compare, et leve si
        l'appelant s'est trompe (cf. ``_verify_supplied_mask``).

        6e ELEMENT RENDU — le couple ``(masque, pool)`` de l'etat de SORTIE, ou ``None`` quand
        aucune construction n'a eu lieu sur le chemin emprunte. L'appelant y reprend le masque au
        lieu de le reconstruire pour reposer la question « a qui est la decision maintenant ? »
        (96,5 reconstructions identiques par episode). Sa validite jusqu'au ``return`` a ete
        auditee : entre la derniere construction et la sortie ne tournent que ``calculate_reward``,
        des compteurs et la fabrication d'``info``, et RIEN de ce que ``calculate_reward`` ecrit
        dans ``game_state`` (``last_reward_breakdown``, ``_pile_in_toCol/Row``, et les familles
        ``objective_rewarded_turns`` / ``coherency_penalized_turns`` du registre
        ``_once_claims``) n'est lu par la construction du masque — verifie par grep sur
        ``action_decoder``, ``phase_handlers`` et ``spatial_grid``. ``_pending_zone_shaping`` est poppe ici, pas par le calcul de recompense.

        ATTENTES FORCEES — les deux sorties non terminales passent par ``_drain_forced_waits`` : un
        etat qui n'ouvre que ``wait`` est joue par le moteur au lieu d'etre rendu a l'agent. Un step
        d'agent peut donc recouvrir plusieurs steps de moteur ; ``reward`` les cumule, et ``info``
        reste celui de l'action de l'APPELANT (seules les cles de ``TERMINAL_INFO_KEYS`` viennent du
        dernier step de la chaine).
        """
        # Reste None sur tout chemin qui ne construit aucune observation : l'appelant reconstruit
        # alors le masque lui-meme. Jamais un couple perime — c'est l'inverse du defaut a eviter.
        out_mask: Optional[Tuple[np.ndarray, List[Dict[str, Any]]]] = None
        # `self.debug_mode` et non `game_state.get("debug_mode")` (§0.46 axe D) : le drapeau est
        # un attribut d'instance, le relire par hachage de chaine dans le dict d'etat coutait un
        # acces de plus a chaque appel de `step`, le chemin le plus chaud du moteur.
        if self.debug_mode:
            trace(
                CH_STEP, self.debug_mode,
                "W40KEngine.step enter episode=%s turn=%s phase=%s current_player=%s action=%s",
                self.game_state.get("episode_number", "?"),
                self.game_state.get("turn", "?"),
                self.game_state.get("phase", "?"),
                self.game_state.get("current_player", "?"),
                action,
            )
        # Safety: count step() calls per episode to truncate runaways (e.g. stuck in eval)
        self._episode_step_calls = getattr(self, '_episode_step_calls', 0) + 1

        # CRITICAL: Check turn limit BEFORE processing any action
        if turn_limit_reached(self.game_state):
            # Turn limit exceeded - return terminated episode immediately
            # CRITICAL: Set turn_limit_reached flag in game_state for winner determination
            self.game_state["game_over"] = True
            self.game_state["turn_limit_reached"] = True
            observation, out_mask = self._step_observation()
            winner, win_method = self._determine_winner_with_method()
            
            # CRITICAL: win_method should never be None when game is terminated
            if win_method is None:
                raise ValueError(
                    f"win_method is None but terminated=True. Winner={winner}, Turn={self.game_state.get('turn')}"
                )
            
            info = {"turn_limit_exceeded": True, "winner": winner, "win_method": win_method}
            
            # Log episode end if step_logger is enabled
            if hasattr(self, 'step_logger') and self.step_logger and self.step_logger.enabled:
                objective_control = self.state_manager.calculate_objective_control(self.game_state)
                self.step_logger.log_episode_end(self.game_state["episode_steps"], winner, win_method, objective_control)
            
            return observation, 0.0, True, False, info, out_mask

        # Check for game termination before action
        self.game_state["game_over"] = self._check_game_over()

        # Snapshot units_cache → units_cache_prev BEFORE processing the action (Phase 2: units_cache always exists)
        uc = require_key(self.game_state, "units_cache")
        self.game_state["units_cache_prev"] = {
            uid: {"col": d["col"], "row": d["row"], "HP_CUR": d["HP_CUR"], "player": d["player"]}
            for uid, d in uc.items()
        }

        _step_t0 = None
        
        # CRITICAL FIX: Auto-advance phase when no valid actions exist
        # This handles the case where fight phase pools are empty
        # PERF: compute mask+eligible_units once, reuse for convert_squad_action
        # L'appelant qui tient deja ce couple pour l'etat d'entree le transmet (cf. docstring) ;
        # sinon on le construit. `_verify_supplied_mask` est un no-op hors `W40K_MASK_VERIFY=2`.
        if mask_and_eligible is not None:
            action_mask, eligible_units = mask_and_eligible
            self._verify_supplied_mask(action_mask, eligible_units, "W40KEngine.step_with_mask")
        else:
            action_mask, eligible_units = self.action_decoder.get_squad_action_mask_and_eligible_units(self.game_state)
        # ATTENTE FORCEE : le masque d'ENTREE n'ouvrait que `wait`, l'agent n'a donc rien choisi.
        # Le pourquoi et la mesure sont dans `RewardCalculator._wait_reward`, qui lit ce drapeau.
        # Le canal est `game_state` et non le payload `result` parce que le fait est connu ICI,
        # avant que l'action ne soit jouee, alors que `result` n'existe qu'apres elle.
        # PURGE PUIS POSE : la cle ne doit exister que pour le step courant, et ce chemin compte
        # des sorties anticipees qui rendent sans passer par `calculate_reward`.
        self.game_state.pop("_wait_was_forced", None)
        if int(action) == SQUAD_ACTION_WAIT and _mask_only_opens_wait(action_mask):
            self.game_state["_wait_was_forced"] = True
        if self.debug_mode:
            from engine.game_utils import add_debug_file_log
            episode = self.game_state.get("episode_number", "?")
            turn = self.game_state.get("turn", "?")
            phase = self.game_state.get("phase", "?")
            current_player = self.game_state.get("current_player", "?")
            mask_indices = [i for i, v in enumerate(action_mask) if v]
            add_debug_file_log(
                self.game_state,
                f"[GYM ACTION DEBUG] E{episode} T{turn} P{current_player} step: "
                f"phase={phase} action_int={action} mask_true_indices={mask_indices} "
                f"eligible_units={[u.get('id') for u in eligible_units]}"
            )
        _step_t1 = time.perf_counter() if _step_t0 is not None else None
        if not eligible_units and not action_mask.any():
            # No eligible units and no valid actions - trigger phase transition
            current_phase = self.game_state["phase"]
            # Joueur AVANT la transition : `advance_phase` peut rendre la main a l'adversaire, et
            # l'auto-jeu des attentes forcees ne doit jamais se poursuivre pour lui (cf.
            # `_drain_forced_waits`). Capture ici, comparee apres.
            player_before_advance = int(require_key(self.game_state, "current_player"))
            advance_action = {"action": "advance_phase", "from": current_phase, "reason": "pool_empty"}
            advance_success, result = self._advance_phase_and_drain(advance_action)
            if not advance_success:
                raise RuntimeError(f"advance_phase failed: {result}")
            _step_t2_early = time.perf_counter() if _step_t0 is not None else None
            # After phase transition, get new observation
            observation, out_mask = self._step_observation()
            _step_t3_early = time.perf_counter() if _step_t0 is not None else None
            # Check if game ended after phase transition
            self.game_state["game_over"] = self._check_game_over()
            
            # CRITICAL: Copy turn_limit_reached from result to game_state if present
            if isinstance(result, dict) and result.get("turn_limit_reached", False):
                self.game_state["turn_limit_reached"] = True
            
            terminated = self.game_state["game_over"]
            info = {"phase_auto_advanced": True, "previous_phase": current_phase}
            if terminated:
                winner, win_method = self._determine_winner_with_method()
                
                # CRITICAL: win_method should never be None when game is terminated
                if win_method is None:
                    raise ValueError(
                        f"win_method is None but terminated=True. Winner={winner}, Turn={self.game_state.get('turn')}"
                    )
                
                info["winner"] = winner
                info["win_method"] = win_method
                
                # Log episode end if step_logger is enabled
                if hasattr(self, 'step_logger') and self.step_logger and self.step_logger.enabled:
                    objective_control = self.state_manager.calculate_objective_control(self.game_state)
                    self.step_logger.log_episode_end(self.game_state["episode_steps"], winner, win_method, objective_control)
            
            # Sortie NON TERMINALE quand la transition de phase n'a pas fini la partie : elle doit
            # drainer les attentes forcees comme le retour final, sinon l'economie dependrait du
            # chemin emprunte. L'acteur de reference est celui d'AVANT la transition — la chaine ne
            # doit pas se poursuivre pour l'adversaire si la phase a change de joueur.
            return self._drain_forced_waits(
                observation, 0.0, terminated, False, info, out_mask, player_before_advance
            )

        # Épisode `auto` : le moteur pose à la place du joueur-agent (ex-mode `fixed` de la rampe).
        if self._should_auto_deploy_for_agent(action_mask):
            pending = self._auto_deployment_pending_action
            self._auto_deployment_pending_action = None
            if pending is None:
                # Moteur nu (tests, scripts) : personne n'a demandé la pose, on la tire ici.
                action = self._pick_placement_action(action_mask, "deployment_mode_schedule 'auto'")
            elif int(action) != int(pending):
                raise RuntimeError(
                    "deployment_mode_schedule 'auto' : pose armée par auto_deployment_action "
                    f"({pending}) mais step a reçu {action}. L'appelant qui arme DOIT rejouer la "
                    "pose rendue — en tirer une seconde ici ferait exécuter une action que "
                    "l'appelant n'a pas vue."
                )
            auto_steps = self.game_state.get("_deployment_auto_steps", 0)  # get allowed : compteur initialisé au 1er pas auto
            if not isinstance(auto_steps, int) or isinstance(auto_steps, bool):
                raise TypeError(
                    f"_deployment_auto_steps must be integer (got {type(auto_steps).__name__})"
                )
            self.game_state["_deployment_auto_steps"] = auto_steps + 1
        
        # Normalize raw action once.
        if self.debug_mode:
            trace(
                CH_STEP, self.debug_mode,
                "W40KEngine.step before normalize_action_input phase=%s action=%s",
                self.game_state.get("phase", "?"), action,
            )
        action_int = self.action_decoder.normalize_action_input(
            raw_action=action,
            phase=require_key(self.game_state, "phase"),
            source="w40k_core.step",
            action_space_size=len(action_mask),
        )
        if self.debug_mode:
            trace(
                CH_STEP, self.debug_mode,
                "W40KEngine.step after normalize_action_input phase=%s action_int=%s",
                self.game_state.get("phase", "?"), action_int,
            )

        # Convert gym integer action to semantic action (reuse precomputed mask+eligible_units)
        if self.debug_mode:
            trace(
                CH_STEP, self.debug_mode,
                "W40KEngine.step before convert_squad_action phase=%s action_int=%s",
                self.game_state.get("phase", "?"), action_int,
            )
        semantic_action = self.action_decoder.convert_squad_action(
            action_int, self.game_state, eligible_units=eligible_units
        )
        if self.debug_mode:
            trace(
                CH_STEP, self.debug_mode,
                "W40KEngine.step after convert_squad_action phase=%s semantic_action=%s",
                self.game_state.get("phase", "?"), semantic_action,
            )
        self.game_state["_last_semantic_action"] = copy.deepcopy(semantic_action)
        if self.debug_mode:
            from engine.game_utils import add_debug_file_log
            episode = self.game_state.get("episode_number", "?")
            turn = self.game_state.get("turn", "?")
            current_player = self.game_state.get("current_player", "?")
            add_debug_file_log(
                self.game_state,
                f"[GYM ACTION DEBUG] E{episode} T{turn} P{current_player} step: "
                f"semantic_action={semantic_action}"
            )
        _step_t2 = time.perf_counter() if _step_t0 is not None else None

        # Joueur pre-action : requis par info["acting_player"] apres execution.
        pre_action_player = int(require_key(self.game_state, "current_player"))
        # Phase pre-action : l'execution peut la faire avancer, et la famille d'une action en
        # DEPEND (les ids 4-8 sont des slots de deploiement en phase deployment, des cellules
        # de move ailleurs). La lire apres coup classerait l'action dans la phase suivante.
        pre_action_phase = require_key(self.game_state, "phase")

        _pre_action_turn = require_key(self.game_state, "turn")
        # Etat fight AVANT l'action : le formateur "combat" exige fight_subphase (contrat replay).
        # L'action peut faire transiter la sous-phase (end_activation) — on capture donc AVANT, pour
        # journaliser la sous-phase DANS laquelle l'action a eu lieu. Le cercle vert du replay (unite
        # active) est derive de l'attaquant de la ligne, pas d'un pool (cf. Documentation Replay.md).
        _pre_action_fight_state = {
            "fight_subphase": self.game_state.get("fight_subphase"),  # get allowed
        }

        # Process semantic action with AI_TURN.md compliance
        if self.debug_mode:
            trace(
                CH_STEP, self.debug_mode,
                "W40KEngine.step before _process_semantic_action phase=%s semantic_action=%s",
                self.game_state.get("phase", "?"), semantic_action,
            )
        action_result = self._process_squad_action(semantic_action)
        if self.debug_mode:
            trace(
                CH_STEP, self.debug_mode,
                "W40KEngine.step after _process_semantic_action phase=%s action_result=%s",
                self.game_state.get("phase", "?"), action_result,
            )
        _step_t3 = time.perf_counter() if _step_t0 is not None else None
        if isinstance(action_result, tuple) and len(action_result) == 2:
            success, result = action_result
        else:
            success, result = True, action_result
        # V11 T6 (T6-c) : transfere au StepLogger les action_logs produits par cette action.
        # Point d'accroche UNIQUE du chemin squad (no-op si --step absent).
        self._flush_squad_action_logs_to_step_logger(
            _pre_action_turn, _pre_action_fight_state
        )
        result_action = result.get("action") if isinstance(result, dict) else None
        result_error = result.get("error") if isinstance(result, dict) else None
        result_waiting_for_player = result.get("waiting_for_player") if isinstance(result, dict) else None
        result_context = result.get("context") if isinstance(result, dict) else None
        self.game_state["_last_action_debug"] = {
            "semantic_action": self.game_state.get("_last_semantic_action"),
            "success": success,
            "result_action": result_action,
            "result_error": result_error,
            "result_waiting_for_player": result_waiting_for_player,
            "result_context": result_context,
        }

        # BUILT-IN STEP COUNTING - AFTER validation, only for successful actions
        if success:
            self.game_state["episode_steps"] += 1

            # NEW: AI_TURN.md compliance tracking - verify ONE unit per step
            compliance_data = {
                'units_activated_this_step': 1,  # Should always be 1 per AI_TURN.md
                'phase_end_reason': 'unknown',
                'duplicate_activation_attempts': 0,
                'pool_corruption_detected': 0
            }

            # Validate sequential activation (ONE unit per step)
            if hasattr(self, '_units_activated_this_step'):
                if self._units_activated_this_step > 1:
                    compliance_data['units_activated_this_step'] = self._units_activated_this_step

            # Store compliance data for metrics callback
            self.game_state['last_compliance_data'] = compliance_data

            # Reset per-step counter
            self._units_activated_this_step = 0
        
        # Convert to gym format
        action_mask, eligible_units = self.action_decoder.get_squad_action_mask_and_eligible_units(self.game_state)
        if not eligible_units and not action_mask.any():
            if self.game_state.get("game_over", False):
                # Adjacent au masque ci-dessus : seules des lectures separent les deux.
                observation, out_mask = self._step_observation(
                    mask_and_eligible=(action_mask, eligible_units)
                )
            else:
            # Pool empty -> advance phase before building observation (no recursion)
            # (les observations construites plus bas suivent un `_process_squad_action` : leur
            #  masque a change, elles n'en passent aucun.)
                current_phase = self.game_state.get("phase", "unknown")
                advance_action = {"action": "advance_phase", "from": current_phase, "reason": "pool_empty"}
                advance_success, advance_result = self._advance_phase_and_drain(advance_action)
                if not advance_success:
                    if (
                        isinstance(advance_result, dict)
                        and advance_result.get("error") == "game_over"
                    ):
                        self.game_state["game_over"] = True
                        observation, out_mask = self._step_observation()
                    else:
                        raise RuntimeError(f"advance_phase failed: {advance_result}")
                else:
                    # `result` GARDE le resultat de l'action de l'agent. Le `advance_phase` ci-dessus
                    # avance la phase, il ne decrit pas ce que l'agent a fait : `calculate_reward` et
                    # `info` (construits plus bas depuis `result`) doivent voir l'action, pas la
                    # transition qu'elle a declenchee.
                    #
                    # Ce qui vivait ici, et pourquoi c'est parti : une cascade de phases doublonnee
                    # (morte — `_process_squad_action` cascade lui-meme avant de rendre la main ; 0
                    # appel a `*_phase_start` mesure) dont l'initialiseur de boucle `result =
                    # advance_result` etait, lui, bien vivant. Effet mesure sur 8 episodes : 25,6
                    # substitutions par episode, soit 25 % des calculs de recompense, ou le payload
                    # `reason: "pool_empty"` forcait `is_system_response` (reward_calculator) et
                    # versait `system_penalties['system_response']` = 0.0 a la place de la recompense
                    # de l'action — la DERNIERE activation de chaque phase, dernier tir et dernier
                    # corps-a-corps compris (+68,20 de recompense d'action annulee sur 8 episodes).
                    # `info` y perdait aussi `action` et `unitId`, invisibilisant ces steps pour toute
                    # metrique par type d'action. Aucun consommateur ne lisait `info["next_phase"]`
                    # ni `info["phase_complete"]`.
                    #
                    # Verrouille par tests/unit/engine/test_engine_step.py
                    # (TestStepPostActionPoolEmpty) : reintroduire la substitution rend ces tests
                    # rouges. Ce changement DEPLACE les recompenses : il exige un re-entrainement.
                    observation, out_mask = self._step_observation()
        else:
            # Aucune transition de phase n'a eu lieu : l'etat est EXACTEMENT celui sur lequel le
            # masque ci-dessus a ete calcule, on le transmet au lieu de le refaire calculer a
            # l'identique (cf. `_build_observation`, parametre `mask_and_eligible`). Les branches
            # ci-dessus, elles, ont avance la phase : leur masque est perime, elles n'en passent
            # aucun.
            observation, out_mask = self._step_observation(mask_and_eligible=(action_mask, eligible_units))
        _step_t4 = time.perf_counter() if _step_t0 is not None else None
        # Calculate reward (independent of step_logger)
        # Shaping zone-intent verse a ce step, cumule pour la VENTILATION : il n'est pas produit
        # par `calculate_reward`, donc il n'apparait pas dans `last_reward_breakdown`. Sans le
        # rattacher, il gonflait le retour de l'episode sans entrer dans aucune categorie — les
        # cinq `reward/*_total` ne sommaient plus le retour, et `reward/objective_share`, la
        # metrique meme que ce shaping doit eclairer, ignorait un flux d'objectif reellement percu.
        zone_shaping_paid = 0.0
        # Zone intent free step: reward is always 0.0 (agent learns via deferred rewards)
        if isinstance(result, dict) and result.get("action") == "zone_intent":
            reward = 0.0
        else:
            reward = self.reward_calculator.calculate_reward(success, result, self.game_state)
            # Shaping zone-intent : solde d'une declaration d'un tour PRECEDENT, pose a
            # l'ouverture de la command phase du declarant (cf. _process_command_phase).
            # La cle est posee a l'init ET au reset : sa lecture est stricte, et le versement
            # la remet a 0.0 au lieu de la supprimer — un `pop` avec defaut masquerait une
            # desynchronisation du cycle declaration/solde.
            shaping = require_key(self.game_state, "_pending_zone_shaping")
            self.game_state["_pending_zone_shaping"] = 0.0
            reward += shaping
            zone_shaping_paid += shaping
        _step_t5 = time.perf_counter() if _step_t0 is not None else None
        terminated = self.game_state["game_over"]
        if terminated:
            # SOLDE TERMINAL. La declaration du dernier tour n'atteindra jamais la command phase
            # suivante : sans ce rattrapage, le dernier tour de CHAQUE episode ne serait jamais
            # paye — un tour sur N systematiquement muet, et justement celui qui decide la
            # partie.
            #
            # On solde celle du JOUEUR CONTROLE, pas celle de l'auteur du dernier step : la
            # partie se termine le plus souvent pendant le tour de l'adversaire, et l'agent n'a
            # alors plus aucun step pour porter son solde. Verser ici reste correct — les
            # wrappers d'adversaire cumulent les recompenses des steps du bot dans celle rendue
            # a l'agent (`cumulative_reward`, ai/env_wrappers.py). La declaration eventuelle de
            # l'adversaire n'est jamais soldee : sa recompense n'entraine rien, et `reset` la
            # jette avec le reste de `game_state`.
            terminal_shaping = self.settle_pending_zone_intent_declaration(
                int(require_key(self.config, "controlled_player"))
            )
            reward += terminal_shaping
            zone_shaping_paid += terminal_shaping
        truncated = False
        info = result.copy() if isinstance(result, dict) else {}
        info["success"] = success
        controlled_player = int(require_key(self.config, "controlled_player"))
        opponent_player = 2 if controlled_player == 1 else 1
        is_controlled_action = pre_action_player == controlled_player
        info["controlled_player"] = controlled_player
        info["opponent_player"] = opponent_player
        info["acting_player"] = pre_action_player
        info["is_controlled_action"] = is_controlled_action
        
        # CRITICAL: Copy turn_limit_reached from result to game_state if present
        # This must happen BEFORE calling _determine_winner_with_method()
        if isinstance(result, dict) and result.get("turn_limit_reached", False):
            self.game_state["turn_limit_reached"] = True
        
        # Accumulate episode-level metrics
        self.episode_reward_accumulator += reward
        self.episode_length_accumulator += 1
        
        # Track action metrics for controlled agent only (seat-aware).
        if is_controlled_action:
            self.episode_tactical_data['total_actions'] += 1
            if success:
                self.episode_tactical_data['valid_actions'] += 1
            else:
                self.episode_tactical_data['invalid_actions'] += 1
            if isinstance(result, dict):
                action_name = result.get("action")
                if action_name in {"wait", "skip"}:
                    self.episode_tactical_data['wait_actions'] += 1
            # `action_int`, pas `action` : `normalize_action_input` accepte un ndarray de
            # taille 1, forme sur laquelle `int()` leve depuis NumPy 2. Compter la valeur
            # brute ferait planter le step pour une statistique.
            # `setting_up` : l'action a-t-elle ete jouee par une escouade HORS TABLE (arrivee de
            # reserves, 20.04) ? Lu AVANT l'action via son resultat — `ingress_move` est la seule
            # semantique produite par ce cas — parce qu'apres la pose l'unite n'est plus en
            # reserves et la question ne se poserait plus.
            family = action_family(
                action_int, pre_action_phase,
                setting_up=isinstance(result, dict) and result.get("action") == "ingress_move",
            )
            self.episode_tactical_data['action_family_counts'][family] += 1

        # VENTILATION DE LA RECOMPENSE — cumulee ICI, pas cote callback.
        #
        # Chaque step moteur pose sa ventilation dans `last_reward_breakdown` et l'ecrase au
        # suivant. Le callback d'entrainement ne voit, lui, qu'UN info par step GYM, et cet info
        # est celui du DERNIER step moteur : les wrappers d'adversaire (BotControlledEnv,
        # SelfPlayWrapper) rejouent le bot apres l'action de l'agent et remplacent l'info par
        # celle du bot — la ventilation de l'action de l'agent etait donc jetee, et rien du tout
        # n'etait accumule quand le bot ne jouait pas. Cumulee ici, elle traverse : elle voyage
        # dans `episode_tactical_data`, que le bloc de terminaison ci-dessous copie dans info.
        #
        # `*_positive` : le flux POSITIF des composantes denses. Le signe ne se lit qu'AU PAS
        # (une action, un signe) — une fois l'episode somme, les +0,3 de chaque tir et les -0,1
        # de chaque attente ne sont plus separables, et c'est ce flux-la que la part d'objectif
        # (reward/objective_share) doit prendre au denominateur.
        if "last_reward_breakdown" in self.game_state:
            step_breakdown = self.game_state["last_reward_breakdown"]
            del self.game_state["last_reward_breakdown"]
            totals = self.episode_tactical_data['reward_breakdown']
            for key in REWARD_BREAKDOWN_COMPONENTS:
                value = float(require_key(step_breakdown, key))
                totals[key] += value
                if key in DENSE_REWARD_BREAKDOWN_COMPONENTS:
                    totals[f'{key}_positive'] += max(0.0, value)

        if zone_shaping_paid != 0.0:
            # Categorie `objective` : le shaping paie la prise et la conservation d'objectifs.
            # Accumule ici et non dans `last_reward_breakdown` — celui-ci n'existe pas sur tous
            # les chemins qui versent (un solde terminal peut tomber sur un step zone-intent,
            # ou `calculate_reward` n'est pas appele).
            totals = self.episode_tactical_data['reward_breakdown']
            totals['objective'] += zone_shaping_paid
            totals['objective_positive'] += max(0.0, zone_shaping_paid)

        # Cles de FIN D'EPISODE, tenues a part de l'`info` d'action. Deux raisons, et la seconde
        # est celle qui a coute : (1) elles sont les seules que `_drain_forced_waits` reprend du
        # dernier step de la chaine auto-jouee, (2) les tenir dans un dict dedie rend
        # l'enumeration de `TERMINAL_INFO_KEYS` VERIFIABLE — le garde juste avant le drain leve si
        # une cle posee ici n'y figure pas. Sans ce dict, la frontiere « cle d'action / cle
        # terminale » n'existait que dans une liste ecrite a la main, a cote de 500 lignes qui
        # ecrivent dans `info` : c'est exactement comme ca que `tactical_data` et
        # `deployment_mode` ont manque a l'appel.
        terminal_info: Dict[str, Any] = {}

        # Add winner info when game ends
        if terminated:
            winner, win_method = self._determine_winner_with_method()
            
            # CRITICAL: win_method should never be None when game is terminated
            if win_method is None:
                raise ValueError(
                    f"win_method is None but terminated=True. Winner={winner}, Turn={self.game_state.get('turn')}"
                )
            
            terminal_info["winner"] = winner
            terminal_info["win_method"] = win_method

            # CRITICAL: Populate info["episode"] for Stable-Baselines3 MetricsCollectionCallback
            terminal_info["episode"] = {
                "r": float(self.episode_reward_accumulator),
                "l": int(self.episode_length_accumulator),
                "t": int(self.episode_length_accumulator),
            }
            
            # Calculate units killed/lost
            # Controlled player is explicit in engine config (seat-aware).
            controlled_player = int(require_key(self.config, "controlled_player"))
            
            units_cache = require_key(self.game_state, "units_cache")
            surviving_ally_units = sum(1 for _uid, entry in units_cache.items()
                                      if entry["player"] == controlled_player)
            surviving_enemy_units = sum(1 for _uid, entry in units_cache.items()
                                       if entry["player"] != controlled_player)
            
            total_ally_units = sum(1 for u in self.game_state["units"] 
                                  if u["player"] == controlled_player)
            total_enemy_units = sum(1 for u in self.game_state["units"] 
                                   if u["player"] != controlled_player)
            
            self.episode_tactical_data['units_lost'] = total_ally_units - surviving_ally_units
            self.episode_tactical_data['units_killed'] = total_enemy_units - surviving_enemy_units
            self.episode_tactical_data['total_enemy_units'] = total_enemy_units
            self.episode_tactical_data['total_ally_units'] = total_ally_units

            # Attrition en FIGURINES et en VALUE : une seule passe sur models_cache, dont les
            # mortes sont retirees. Les references de depart (effectif, VALUE) sont les photos
            # posees par build_units_cache au reset — rien ne les redonne ensuite.
            #
            # LES DEUX CAMPS SONT COMPTES DE LA MEME FACON, et le camp perdant comme le camp
            # gagnant : c'est ce qui rend les courbes lisibles cote a cote. Le compte de kills
            # du journal (shoot_kills + melee_kills) ne conviendrait PAS comme numerateur cote
            # ennemi — il ignore les figurines retirees hors attaque (hazard 24.16, retrait de
            # coherence 03.03) que la difference des survivants compte forcement cote allie.
            # L'attribution des kills a l'agent, elle, reste lisible sur g_/h_.
            models_cache = require_key(self.game_state, "models_cache")
            models_at_start = require_key(self.game_state, "model_count_at_start_by_player")
            value_at_start = require_key(self.game_state, "value_at_start")
            opponent_player = 2 if controlled_player == 1 else 1

            surviving_ally_models = 0
            surviving_enemy_models = 0
            surviving_ally_value = 0.0
            surviving_enemy_value = 0.0
            for model in models_cache.values():
                model_value = float(require_key(model, "VALUE"))
                if int(require_key(model, "player")) == controlled_player:
                    surviving_ally_models += 1
                    surviving_ally_value += model_value
                else:
                    surviving_enemy_models += 1
                    surviving_enemy_value += model_value

            initial_ally_models = int(require_key(models_at_start, controlled_player))
            initial_enemy_models = int(require_key(models_at_start, opponent_player))
            if surviving_ally_models > initial_ally_models or surviving_enemy_models > initial_enemy_models:
                raise ValueError(
                    f"more surviving models than at start (ally {surviving_ally_models}/"
                    f"{initial_ally_models}, enemy {surviving_enemy_models}/{initial_enemy_models}): "
                    "model_count_at_start_by_player is not the reset snapshot"
                )
            self.episode_tactical_data['initial_ally_models'] = initial_ally_models
            self.episode_tactical_data['initial_enemy_models'] = initial_enemy_models
            self.episode_tactical_data['models_lost'] = initial_ally_models - surviving_ally_models
            self.episode_tactical_data['models_killed'] = initial_enemy_models - surviving_enemy_models

            action_logs = self.game_state["action_logs"]

            # Volume de combat, kills et attrition, meme source action_logs (seat-aware).
            #
            # Ces quatre compteurs etaient DECLARES et jamais incrementes depuis le commit
            # fe1df7d8 « metrics OK » (2025-10-25), qui a deplace episode_tactical_data du
            # callback vers le moteur : le deplacement a reimplemente valid_actions /
            # invalid_actions / units_lost / units_killed, mais pas ceux-ci, tout en supprimant
            # leur calcul cote callback dans le meme diff. Quatre courbes muettes pendant neuf
            # mois (damage_dealt, damage_received, accuracy, damage_efficiency), sans erreur
            # pour le signaler : leurs consommateurs sont gardes par `> 0`, donc une courbe
            # absente ne se distingue pas d'un agent qui ne se bat jamais.
            #
            # POURQUOI ICI, et pas au point ou chaque attaque se resout : les deux endroits de
            # ce fichier qui construisent un dictionnaire par attaque (attack_details, pour le
            # step.log) sont a l'interieur de
            # `if (self.step_logger and self.step_logger.enabled)`. Y incrementer rendrait les
            # compteurs dependants de --step : nuls a l'entrainement normal, non nuls en debug.
            # Et `result["all_attack_results"]`, l'autre canal, ne remonte JAMAIS jusqu'a step()
            # dans le pipeline squad V11 (mesure sur partie reelle : 0 step sur un episode
            # complet). action_logs est la source que reward_calculator et shoot_kills/
            # melee_kills utilisent deja, elle est remise a zero par reset() et jamais purgee
            # en cours d'episode : une passe unique ici ne peut pas double-compter.
            #
            # DEFINITION : shots_fired / hits comptent le TIR seul (`type == "shoot"`), comme
            # a l'origine et comme le vocabulaire 40K l'impose — accuracy = precision au tir
            # (BS), que melanger avec la melee (WS) rendrait ininterpretable. Les deux viennent
            # du meme filtre, donc hits <= shots_fired par construction. damage_dealt et
            # damage_received, eux, couvrent tir ET melee : c'est l'attrition totale.
            #
            # KILLS — DEFINITION : une FIGURINE detruite = 1, dans les deux phases. Le compte se
            # fait donc sur `shootDetails[i]["targetDied"]` (pose par attaque, sur celle qui
            # acheve la figurine), et JAMAIS sur le `target_died` de l'entete, qui vaut
            # `kills > 0` pour tout le groupe (arme, cible) : un groupe qui tue trois figurines
            # ne compterait que pour un. Jusqu'au 2026-07-30 la melee lisait le seul
            # `shootDetails[0]`, ce qui ne mesurait que « la premiere attaque du groupe a-t-elle
            # tue ? » — une probabilite quasi constante (~0,15 mesure) independante de la
            # competence de l'agent, d'ou une courbe 02_combat/h_melee_model_kills plate et bruitee pendant que
            # g_shoot_model_kills, elle, progressait.
            # `*_value_killed` somme la VALUE des figurines ainsi detruites : distinguer 20
            # gretchins a 4 points d'un monstre a 120 est ce qui separe un agent qui grignote
            # d'un agent qui frappe ce qui compte. Distinct de `enemy_value_destroyed`,
            # calcule plus bas : les deux comptent par figurine, mais celui-la somme la VALUE
            # perdue TOUTES CAUSES confondues et sans ventilation par phase, la ou ceux-ci
            # n'attribuent que ce que l'agent a detruit au tir ou en melee.
            shots_fired = 0
            hits = 0
            damage_dealt = 0
            damage_received = 0
            shoot_kills = 0
            melee_kills = 0
            shoot_value_killed = 0.0
            melee_value_killed = 0.0
            # CHARGES — comptees POUR LES DEUX CAMPS, seul bloc de cette passe a le faire.
            # Le taux de reussite d'une charge (2D6 contre la distance a laquelle elle est
            # declaree) ne se lit que rapporte a une reference : un agent qui reussit 40% de
            # ses charges joue bien ou mal selon que l'adversaire en reussit 30% ou 70%. Sans
            # la colonne d'en face, la courbe ne distingue pas la competence de la difficulte
            # du scenario. Les compteurs `*_opponent` sont donc la mesure, pas un supplement.
            #
            # `charge` et `charge_fail` sont les deux SEULS types emis pour une tentative, et
            # ils le sont par les DEUX chemins — pipeline squad V11 (ce fichier) et handlers
            # legacy/PvP (charge_handlers ~L2914/4233/5409/5531/5689) — donc le comptage tient
            # quel que soit le chemin qui a joue. `charge_impact` est exclu : c'est la
            # consequence d'une charge deja reussie, pas une tentative.
            charge_attempts = 0
            charge_successes = 0
            charge_attempts_opponent = 0
            charge_successes_opponent = 0
            # PARTICIPATION PAR PHASE — « quelle part des occasions l'agent a-t-il saisies ».
            #
            # Ces trois taux (deplacement, tir, fuite) ont ete emis par le callback jusqu'a ce
            # que son unique appelant disparaisse : `log_phase_performance` n'avait plus AUCUN
            # appel de production, donc `game_tactical/movement_efficiency`,
            # `shooting_participation` et `game_detailed/flee_rate` n'existaient
            # dans aucun run — verifie sur les 124 tags d'un run de 50 000 episodes. Meme
            # defaut silencieux que les quatre compteurs plus haut : une courbe absente ne se
            # distingue pas d'un agent qui n'agit jamais.
            #
            # Recomptes ICI et pas rebranches la-bas : le callback deduisait la phase et le camp
            # de l'`info` d'un step gym, ou un step enchaine plusieurs steps moteur — c'est ce
            # qui lui faisait ranger les actions du BOT sous le drapeau de l'agent. Dans
            # `action_logs`, phase et camp sont des DONNEES de chaque ligne.
            #
            # PAS de taux de participation pour la CHARGE : son denominateur ne serait pas
            # « les occasions de charger » mais « les fois ou le moteur a expose la phase »
            # — quand le pool de charge est vide, aucun step n'est joue, donc aucun `wait` n'est
            # journalise et le tour n'entre nulle part (mesure : sur un montage ou les deux camps
            # arrivent au contact en se deplacant, la phase charge n'est jamais exposee). Le
            # VOLUME de charges declarees (`charge_attempts`) repond a la question sans cette
            # ambiguite, et la comparaison avec l'adversaire lui sert d'echelle.
            #
            # ACTIVATIONS, pas lignes de journal : le tir emet un log par groupe (arme, cible),
            # donc une escouade qui tire trois armes produirait trois « participations ». Le
            # couple (turn, shooterId) ramene le compte a ce qu'il pretend mesurer — combien de
            # fois une escouade a choisi de tirer plutot que d'attendre. Le deplacement et la
            # charge, eux, emettent une ligne par activation : rien a dedupliquer.
            move_actions = 0
            move_flees = 0
            move_waits = 0
            shoot_activations: Set[Tuple[int, str]] = set()
            shoot_waits = 0
            for log in action_logs:
                log_type = log.get("type")
                if log_type == "move":
                    if int(require_key(log, "player")) == controlled_player:
                        move_actions += 1
                        if require_key(log, "was_flee"):
                            move_flees += 1
                    continue
                if log_type == "wait":
                    if int(require_key(log, "player")) == controlled_player:
                        log_phase = require_key(log, "phase")
                        if log_phase == "move":
                            move_waits += 1
                        elif log_phase == "shoot":
                            shoot_waits += 1
                    continue
                if log_type in ("charge", "charge_fail"):
                    if int(require_key(log, "player")) == controlled_player:
                        charge_attempts += 1
                        if log_type == "charge":
                            charge_successes += 1
                    else:
                        charge_attempts_opponent += 1
                        if log_type == "charge":
                            charge_successes_opponent += 1
                    continue
                if log_type not in ("shoot", "combat"):
                    continue
                by_controlled = int(require_key(log, "player")) == controlled_player
                # `damage` est la perte de PV reellement appliquee a la cible pour cette
                # activation (verifie sur partie reelle : la somme par attaquant egale
                # exactement les PV perdus par le camp d'en face).
                log_damage = int(require_key(log, "damage"))
                if by_controlled:
                    damage_dealt += log_damage
                else:
                    damage_received += log_damage
                if not by_controlled:
                    continue
                # `type == "combat"` n'a qu'un seul emetteur (FIGHT_CTX, `phase_label="fight"`) :
                # une autre phase serait un log de melee produit par un chemin inconnu, pas une
                # ligne a ranger au tir en silence.
                is_melee = log_type == "combat"
                if not is_melee:
                    # Une ACTIVATION de tir = une escouade, un tour. Cf. le commentaire des
                    # compteurs de participation : le journal en emet une ligne par arme.
                    shoot_activations.add(
                        (int(require_key(log, "turn")), str(require_key(log, "shooterId")))
                    )
                if is_melee and log.get("phase") != "fight":
                    raise ValueError(
                        f"action_log de type 'combat' hors phase fight (phase="
                        f"{log.get('phase')!r}) — emetteur inattendu, kills non ventilables"
                    )
                for shot in require_key(log, "shootDetails"):
                    if not is_melee:
                        shots_fired += 1
                        if require_key(shot, "hitResult") == "HIT":
                            hits += 1
                    # `targetDied` n'est pose que sur les attaques qui ont applique des degats
                    # (une attaque ratee ou sauvegardee n'a pas de cible morte) : absence = False.
                    if not shot.get("targetDied", False):  # get allowed
                        continue
                    model_value = float(require_key(shot, "targetValue"))
                    if is_melee:
                        melee_kills += 1
                        melee_value_killed += model_value
                    else:
                        shoot_kills += 1
                        shoot_value_killed += model_value
            self.episode_tactical_data['shots_fired'] = shots_fired
            self.episode_tactical_data['hits'] = hits
            self.episode_tactical_data['damage_dealt'] = damage_dealt
            self.episode_tactical_data['damage_received'] = damage_received
            self.episode_tactical_data['shoot_kills'] = shoot_kills
            self.episode_tactical_data['melee_kills'] = melee_kills
            self.episode_tactical_data['shoot_value_killed'] = shoot_value_killed
            self.episode_tactical_data['melee_value_killed'] = melee_value_killed
            self.episode_tactical_data['charge_attempts'] = charge_attempts
            self.episode_tactical_data['charge_successes'] = charge_successes
            self.episode_tactical_data['charge_attempts_opponent'] = charge_attempts_opponent
            self.episode_tactical_data['charge_successes_opponent'] = charge_successes_opponent
            self.episode_tactical_data['move_actions'] = move_actions
            self.episode_tactical_data['move_flees'] = move_flees
            self.episode_tactical_data['move_waits'] = move_waits
            self.episode_tactical_data['shoot_activations'] = len(shoot_activations)
            self.episode_tactical_data['shoot_waits'] = shoot_waits

            # Issues du cache de scoring du deploiement, lues sur le decodeur qui les compte.
            # COPIE (`deployment_cache_counts()` en rend une) : le compteur du decodeur est remis
            # a zero au prochain `reset_episode_caches`, l'appelant lit celui-ci APRES.
            self.episode_tactical_data['deployment_cache_counts'] = (
                self.action_decoder.deployment_cache_counts()
            )
            # Réserves stratégiques : compteurs incrémentés par les handlers via game_state.
            self.episode_tactical_data['reserves_placed_agent'] = require_key(self.game_state, "_reserves_placed_agent")
            self.episode_tactical_data['reserves_deployed_agent'] = require_key(self.game_state, "_reserves_deployed_agent")
            self.episode_tactical_data['reserves_destroyed_turn3'] = require_key(self.game_state, "_reserves_destroyed_turn3")

            # VALUE attrition metrics (episode-level): destroyed enemy value and lost ally value.
            #
            # PAR FIGURINE, des deux cotes (survivants accumules avec les effectifs plus haut).
            # Ces deux quantites se comptaient a l'ESCOUADE : la valeur survivante etait
            # `unit["VALUE"]` entiere tant qu'une seule figurine tenait, donc une escouade de
            # 10 reduite a 1 pesait 0 de perte. Les courbes d'attrition en VALUE (combat/f_,
            # combat/g_, 02_combat/a_, e_, f_) affichaient alors 0.0 la ou le compte de
            # figurines montrait 0.9 — la mesure ne pouvait pas etre lue a cote de c_/d_.
            total_ally_value = float(require_key(value_at_start, controlled_player))
            total_enemy_value = float(require_key(value_at_start, opponent_player))
            # Pas de `max(0.0, ...)` ici : depart et survivants sortent des memes figurines,
            # rien n'ajoute de figurine en cours de partie. Un ecart negatif signifierait que
            # la photo de depart n'en est pas une — a signaler, pas a ramener a zero.
            if surviving_ally_value > total_ally_value or surviving_enemy_value > total_enemy_value:
                raise ValueError(
                    f"surviving VALUE exceeds start VALUE (ally {surviving_ally_value}/"
                    f"{total_ally_value}, enemy {surviving_enemy_value}/{total_enemy_value}): "
                    "value_at_start is not the reset snapshot"
                )
            self.episode_tactical_data['ally_value_lost'] = total_ally_value - surviving_ally_value
            self.episode_tactical_data['enemy_value_destroyed'] = total_enemy_value - surviving_enemy_value
            self.episode_tactical_data['total_ally_value'] = total_ally_value
            self.episode_tactical_data['total_enemy_value'] = total_enemy_value

            # Store turn number for metrics filtering (e.g., objectives only on turn 5+)
            self.episode_tactical_data['final_turn'] = self.game_state["turn"]

            # Unit-rule forcing exposure metrics:
            # Count units that have at least one configured UNIT_RULES entry.
            units = require_key(self.game_state, "units")
            forced_unit_counts_controlled: Dict[str, int] = {}
            forced_unit_counts_all: Dict[str, int] = {}
            for unit in units:
                unit_rules = require_key(unit, "UNIT_RULES")
                if not isinstance(unit_rules, list):
                    raise TypeError(
                        f"UNIT_RULES must be list for unit {require_key(unit, 'id')} "
                        f"(got {type(unit_rules).__name__})"
                    )
                if len(unit_rules) == 0:
                    continue
                unit_name = str(require_key(unit, "unitType"))
                unit_player = require_key(unit, "player")
                if unit_name not in forced_unit_counts_all:
                    forced_unit_counts_all[unit_name] = 0
                forced_unit_counts_all[unit_name] += 1
                if unit_player == controlled_player:
                    if unit_name not in forced_unit_counts_controlled:
                        forced_unit_counts_controlled[unit_name] = 0
                    forced_unit_counts_controlled[unit_name] += 1

            self.episode_tactical_data['forced_unit_episode_has_controlled'] = (
                1 if len(forced_unit_counts_controlled) > 0 else 0
            )
            self.episode_tactical_data['forced_unit_episode_has_any'] = (
                1 if len(forced_unit_counts_all) > 0 else 0
            )
            self.episode_tactical_data['forced_unit_instances_controlled'] = int(
                sum(forced_unit_counts_controlled.values())
            )
            self.episode_tactical_data['forced_unit_instances_all'] = int(
                sum(forced_unit_counts_all.values())
            )
            self.episode_tactical_data['forced_unit_counts_controlled'] = dict(
                sorted(forced_unit_counts_controlled.items(), key=lambda item: item[0])
            )
            self.episode_tactical_data['forced_unit_counts_all'] = dict(
                sorted(forced_unit_counts_all.items(), key=lambda item: item[0])
            )

            victory_points = require_key(self.game_state, "victory_points")
            controlled_vp = float(require_key(victory_points, controlled_player))
            opponent_vp = float(require_key(victory_points, opponent_player))
            self.episode_tactical_data['victory_points_cumulative_episode'] = controlled_vp
            self.episode_tactical_data['victory_points_controlled_episode'] = controlled_vp
            self.episode_tactical_data['victory_points_opponent_episode'] = opponent_vp
            self.episode_tactical_data['victory_points_diff_controlled_minus_opponent'] = (
                controlled_vp - opponent_vp
            )
            # Cles exigees : posees a l'init du game_state et au reset. Le `.get(...) if
            # isinstance(...) else []` qui occupait cette place transformait leur absence en
            # liste vide, et une liste vide desarme silencieusement les courbes qui la lisent
            # (01_VP/e_objectives_held, d_objectives_held_diff) — exactement ce qui a masque
            # pendant 50 000 episodes que personne ne remplissait ces listes.
            self.episode_tactical_data['controlled_objective_samples'] = list(
                require_key(self.game_state, "controlled_objective_samples_scoring_turns")
            )
            self.episode_tactical_data['opponent_objective_samples'] = list(
                require_key(self.game_state, "opponent_objective_samples_scoring_turns")
            )

            # Add tactical data to info
            terminal_info["tactical_data"] = self.episode_tactical_data.copy()

            # Mode de déploiement de CET épisode ("active" | "auto" | None), pour que les
            # courbes puissent être ventilées par mode. Sans cette ventilation, la rampe
            # `deployment_mode_schedule` fait varier la population mesurée pendant tout le run :
            # une métrique agrégée mélange alors deux tâches de difficulté différente dans des
            # proportions qui changent à chaque épisode, et son plateau ne distingue plus un
            # agent qui stagne d'un agent qui progresse sur une tâche qui durcit.
            terminal_info["deployment_mode"] = self.game_state["deployment_mode_schedule_mode"]
            
            # Log episode end with final stats and win method
            if hasattr(self, 'step_logger') and self.step_logger and self.step_logger.enabled:
                objective_control = self.state_manager.calculate_objective_control(self.game_state)
                self.step_logger.log_episode_end(self.game_state["episode_steps"], winner, win_method, objective_control)
        else:
            info["winner"] = None
        
        # CRITICAL: Add action_logs to info dict so metrics can access it
        # This must happen BEFORE reset clears action_logs. action_logs is always present (init + reset).
        info["action_logs"] = self.game_state["action_logs"].copy()

        # `info["reward_breakdown"] = last_reward_breakdown` occupait cette place, un step
        # moteur a la fois. Son unique lecteur (MetricsCollectionCallback) ne voit qu'un info
        # par step GYM — celui du dernier step moteur, c'est-a-dire celui du BOT des que le
        # wrapper d'adversaire rejoue apres l'agent : la ventilation de l'action de l'agent
        # etait jetee. Elle est desormais cumulee dans `episode_tactical_data['reward_breakdown']`
        # (voir plus haut), qui voyage dans `info["tactical_data"]` a la terminaison.

        # NOTE: last_unit_positions loop removed - now using units_cache_prev snapshot at step() start
        
        if "console_logs" in self.game_state and self.game_state["console_logs"]:
            self.game_state["console_logs"] = []

        # Safety: truncate runaways (e.g. stuck in eval, phase transition bug).
        # Plafond derive de game_rules (max_steps_per_turn * marge * max_turns) : il suit
        # la taille des rosters au lieu d'etre une constante a re-regler a chaque escouade.
        _calls = getattr(self, '_episode_step_calls', 0)
        _episode_limit = self._get_episode_step_limit()
        if not terminated and _episode_limit is not None and _calls > _episode_limit:
            episode = self.game_state.get("episode_number", "?")
            turn = self.game_state.get("turn", "?")
            phase = self.game_state.get("phase", "?")
            current_scenario = require_key(self.__dict__, "_current_scenario_file")
            scenario_name = (
                os.path.basename(current_scenario)
                if isinstance(current_scenario, str) and current_scenario
                else None
            )
            current_player = require_key(self.game_state, "current_player")
            fight_subphase = self.game_state.get("fight_subphase")
            units = require_key(self.game_state, "units")
            if not isinstance(units, list):
                raise TypeError(f"game_state['units'] must be list (got {type(units).__name__})")
            if phase == "move":
                active_unit_id = self.game_state.get("active_movement_unit")
            elif phase == "shoot":
                active_unit_id = self.game_state.get("active_shooting_unit")
            elif phase == "fight":
                active_unit_id = self.game_state.get("active_fight_unit")
            else:
                active_unit_id = None
            active_unit_name = None
            shoot_debug: Optional[Dict[str, Any]] = None
            if active_unit_id is not None:
                active_unit_id_str = str(active_unit_id)
                active_unit = next((u for u in units if str(require_key(u, "id")) == active_unit_id_str), None)
                if active_unit is not None:
                    active_unit_name = require_key(active_unit, "DISPLAY_NAME")
                    if phase == "shoot":
                        selected_weapon_index_raw = active_unit.get("selectedRngWeaponIndex")
                        selected_weapon_index = None
                        if selected_weapon_index_raw is not None:
                            try:
                                selected_weapon_index = int(selected_weapon_index_raw)
                            except (TypeError, ValueError):
                                selected_weapon_index = None

                        selected_weapon_name = None
                        rng_weapons = ranged_weapons(active_unit)
                        if (
                            isinstance(rng_weapons, list)
                            and selected_weapon_index is not None
                            and 0 <= selected_weapon_index < len(rng_weapons)
                        ):
                            selected_weapon_name = rng_weapons[selected_weapon_index].get("display_name")

                        valid_target_pool = active_unit.get("valid_target_pool")
                        if isinstance(valid_target_pool, list):
                            valid_target_pool_count = len(valid_target_pool)
                            valid_target_pool_sample = valid_target_pool[:5]
                        else:
                            valid_target_pool_count = None
                            valid_target_pool_sample = None

                        shoot_pool_ids = [str(uid) for uid in require_key(self.game_state, "shoot_activation_pool")]
                        units_shot = require_key(self.game_state, "units_shot")
                        active_unit_in_units_shot = active_unit_id_str in [str(uid) for uid in units_shot]

                        # Le DICT est la source ; le message console n'en est qu'un rendu.
                        # L'inverse (formater une chaine puis la coller dans le payload JSON)
                        # rendait illisible a la machine la seule cle qui compte en phase shoot.
                        shoot_debug = {
                            'active_in_pool': active_unit_id_str in shoot_pool_ids,
                            'active_in_units_shot': active_unit_in_units_shot,
                            'shoot_left': active_unit.get('SHOOT_LEFT'),
                            'current_shoot_nb': active_unit.get('_current_shoot_nb'),
                            'selected_weapon_index': selected_weapon_index_raw,
                            'selected_weapon_name': selected_weapon_name,
                            'valid_target_pool_count': valid_target_pool_count,
                            'valid_target_pool_sample': valid_target_pool_sample,
                            'shoot_activation_started': active_unit.get('_shoot_activation_started'),
                            'manual_weapon_selected': active_unit.get('_manual_weapon_selected'),
                            'shooting_with_close_quarters': active_unit.get('_shooting_with_close_quarters'),
                        }
            move_pool = len(require_key(self.game_state, "move_activation_pool"))
            shoot_pool = len(require_key(self.game_state, "shoot_activation_pool"))
            charge_pool = len(require_key(self.game_state, "charge_activation_pool"))
            error_msg = (
                f"\n ❌ ERROR: Episode exceeded {_episode_limit} steps (episode={episode}, turn={turn}, "
                f"phase={phase}, scenario={scenario_name}, scenario_path={current_scenario}, "
                f"player={current_player}, fight_subphase={fight_subphase}, "
                f"active_unit_id={active_unit_id}, active_unit_name={active_unit_name}, "
                f"move_pool={move_pool}, shoot_pool={shoot_pool}, charge_pool={charge_pool}"
                f"{', shoot_debug=' + repr(shoot_debug) if shoot_debug else ''}, "
                f"last_action_debug={self.game_state.get('_last_action_debug')}). Forcing termination."
            )
            print(error_msg, flush=True)
            from engine.game_utils import add_debug_log
            add_debug_log(self.game_state, f"[MAX_STEPS LIMIT REACHED] {error_msg}")
            truncated = True
            terminal_info["truncation_reason"] = "episode_steps_limit"
            # Le diagnostic TRAVERSE le VecEnv. Sans ca il n'existait que dans le `print` du
            # worker — noye dans la console a n_envs=48, perdu au scroll — et dans
            # `add_debug_log`, muet hors `debug_mode` et de toute facon local a ce process.
            # Une troncature signale une BOUCLE dans le moteur : ce qu'il faut, c'est de quoi
            # la reproduire. Cf. le lecteur dans ai/training_callbacks.py.
            terminal_info["truncation_debug"] = {
                "episode": episode,
                "turn": turn,
                "phase": phase,
                "scenario": scenario_name,
                "scenario_path": current_scenario,
                "player": current_player,
                "fight_subphase": fight_subphase,
                "active_unit_id": active_unit_id,
                "active_unit_name": active_unit_name,
                "steps": _calls,
                "step_limit": _episode_limit,
                "move_pool": move_pool,
                "shoot_pool": shoot_pool,
                "charge_pool": charge_pool,
                "shoot_debug": shoot_debug,
                "last_action_debug": self.game_state.get("_last_action_debug"),
            }
            terminal_info["winner"] = -1  # draw so eval does not skew win rate
            terminal_info["win_method"] = "step_limit"

        # GARDE D'ENUMERATION — la frontiere « cle d'action / cle terminale » a UNE source, et
        # c'est la construction ci-dessus, pas la liste. Une cle de fin d'episode ajoutee sans
        # etre declaree ferait perdre cette cle a tout episode qui se termine pendant une chaine
        # d'attentes forcees, chez le seul appelant qui l'exige (`ai/training_callbacks`) et
        # seulement une fois sur N episodes : elle echoue ici, immediatement et partout.
        unlisted = tuple(key for key in terminal_info if key not in TERMINAL_INFO_KEYS)
        if unlisted:
            raise RuntimeError(
                f"Cles de fin d'episode absentes de TERMINAL_INFO_KEYS : {unlisted}. "
                f"Les declarer, sinon `_drain_forced_waits` ne les remontera pas quand l'episode "
                f"se termine pendant une chaine d'attentes forcees auto-jouees."
            )
        info.update(terminal_info)

        # Auto-jeu des attentes forcees : cf. `_drain_forced_waits`. Applique AUX DEUX sorties
        # non terminales de cette fonction, sinon il s'appliquerait « selon le chemin emprunte ».
        (observation, reward, terminated, truncated, info, out_mask) = self._drain_forced_waits(
            observation, reward, terminated, truncated, info, out_mask, pre_action_player
        )
        return observation, reward, terminated, truncated, info, out_mask
    
    
    # ============================================================================
    # ACTION EXECUTION - KEEP THESE (They delegate to phase_handlers)
    # ============================================================================
    
    def execute_semantic_action(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Execute semantic actions directly from frontend.
        Public interface for human player actions.
        """
        from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

        gs = self.game_state
        _perf = perf_timing_enabled(gs)
        _t0 = time.perf_counter() if _perf else None
        success, result = self._process_semantic_action(action)
        if _perf and _t0 is not None:
            dt = time.perf_counter() - _t0
            ep = gs.get("episode_number", "?")
            trn = gs.get("turn", "?")
            phase = gs.get("phase", "?")
            act = action.get("action") if isinstance(action, dict) else None
            append_perf_timing_line(
                f"EXECUTE_SEMANTIC_TOTAL episode={ep} turn={trn} phase={phase} action={act!r} "
                f"duration_s={dt:.6f} success={success}"
            )
        return success, result
    
    
    def execute_ai_turn(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Execute AI turn using same decision tree as humans.
        AI_TURN.md compliant - only decision-making logic differs from humans.
        """
        # Validate PvE mode and AI player turn
        if not self.is_pve_mode:
            return False, {"error": "not_pve_mode"}
        
        current_player = self.game_state["current_player"]
        current_phase = self.game_state["phase"]
        
        # CRITICAL: In fight phase, current_player can be 1 but AI can still act in alternating phase
        # Only check current_player for non-fight phases
        if current_phase != "fight" and current_player != 2:  # AI is player 2
            return False, {"error": "not_ai_player_turn", "current_player": current_player, "phase": current_phase}
        
        # For fight phase, check if AI has eligible units in the appropriate pool
        if current_phase == "fight":
            from engine.phase_handlers.fight_handlers import fight_v11_current_pool
            fight_subphase = self.game_state.get("fight_subphase")
            # V11 : éligibilité dérivée de la machine de sélection (non-mutante).
            has_eligible_ai = False
            pool_to_check = fight_v11_current_pool(self.game_state) if fight_subphase else []

            # Check if any unit in the pool is an AI unit (player 2)
            for unit_id in pool_to_check:
                unit = self._get_unit_by_id(str(unit_id))
                if unit and unit.get("player") == 2:
                    has_eligible_ai = True
                    break
            
            if not has_eligible_ai:
                return False, {"error": "not_ai_player_turn", "current_player": current_player, "phase": current_phase, "fight_subphase": fight_subphase, "reason": "no_eligible_ai_units_in_pool", "pool_checked": pool_to_check}
        
        # Check PvE controller readiness without coupling to controller mode.
        if not hasattr(self, "pve_controller") or not self.pve_controller.is_ready_for_decision():
            return False, {"error": "ai_model_not_loaded"}
        
        # Make AI decision - replaces human click
        try:
            ai_semantic_action = self.pve_controller.make_ai_decision(self.game_state, self)

            # Execute through the SQUAD dispatcher : la decision vient de la politique squad,
            # donc sa semantique est celle de `convert_squad_action` (squad_normal_move,
            # squad_shoot, zone_intent...). `_process_semantic_action` ne connait pas ce
            # vocabulaire — c'est `_process_squad_action` qui l'execute, en appelant les MEMES
            # handlers de phase que le joueur humain.
            result = self._process_squad_action(ai_semantic_action)
            return result
            
        except Exception as e:
            pass
            import traceback
            traceback.print_exc()
            return False, {"error": "ai_decision_failed", "message": str(e)}

    def _initialize_rule_choice_runtime_state(self) -> None:
        """Initialize in-memory state for timing-based rule choices."""
        initialize_agent_decision_state(self.game_state)
        if "pending_rule_choice_queue" not in self.game_state:
            self.game_state["pending_rule_choice_queue"] = []
        if "active_rule_choice_prompt" not in self.game_state:
            self.game_state["active_rule_choice_prompt"] = None

    def _get_unit_rule_registry(self) -> Dict[str, Dict[str, Any]]:
        """Return config/unit_rules.json registry."""
        from config_loader import get_config_loader
        return get_config_loader().load_unit_rules_config()

    def _resolve_rule_id_to_technical(self, rule_id: str, visited: Optional[Set[str]] = None) -> str:
        """Resolve display rule id to technical rule id via optional alias chain."""
        if not isinstance(rule_id, str) or not rule_id.strip():
            raise ValueError(f"rule_id must be non-empty string, got {rule_id!r}")
        normalized_rule_id = rule_id.strip()
        registry = self._get_unit_rule_registry()
        if normalized_rule_id not in registry:
            raise KeyError(f"Unknown rule id '{normalized_rule_id}' in config/unit_rules.json")
        if visited is None:
            visited = set()
        if normalized_rule_id in visited:
            raise ValueError(f"Rule alias cycle detected while resolving '{normalized_rule_id}'")
        visited.add(normalized_rule_id)
        alias_rule_id = registry[normalized_rule_id].get("alias")
        if alias_rule_id is None:
            return normalized_rule_id
        if not isinstance(alias_rule_id, str) or not alias_rule_id.strip():
            raise ValueError(f"Rule '{normalized_rule_id}' has invalid alias: {alias_rule_id!r}")
        return self._resolve_rule_id_to_technical(alias_rule_id.strip(), visited)

    def _is_player_human(self, player: int) -> bool:
        """Return True when player is controlled by a human."""
        # Training mode is fully programmatic: never block on manual rule choices.
        if self.gym_training_mode:
            return False
        current_mode_code = self.game_state.get("current_mode_code")
        if not isinstance(current_mode_code, str) or not current_mode_code:
            current_mode_code = getattr(self, "current_mode_code", None)
        if current_mode_code == "pve_test":
            # PvE test mode exposes rule-choice prompts for both players.
            return True
        player_types = self.game_state.get("player_types")
        if isinstance(player_types, dict) and str(player) in player_types:
            return player_types[str(player)] == "human"
        if player == 2 and self.is_pve_mode:
            return False
        return True

    def _clear_turn_scoped_rule_choices(self) -> None:
        """Clear non-unique chosen options at command phase start."""
        units = require_key(self.game_state, "units")
        for unit in units:
            unit_rules = require_key(unit, "UNIT_RULES")
            for rule in unit_rules:
                usage_value = rule.get("usage")
                if usage_value == "or" and "_selected_granted_rule_id" in rule:
                    del rule["_selected_granted_rule_id"]

    def _enqueue_rule_choice_candidates(
        self,
        trigger: str,
        event_phase: Optional[str] = None,
        activation_unit_id: Optional[str] = None,
        event_player: Optional[int] = None,
    ) -> None:
        """Collect all choice prompts matching one timing event and append them to queue."""
        self._initialize_rule_choice_runtime_state()
        if "choice_timing_index" not in self.game_state:
            rebuild_choice_timing_index(self.game_state)

        choice_timing_index = require_key(self.game_state, "choice_timing_index")
        if trigger in choice_timing_index:
            trigger_entries = choice_timing_index[trigger]
        else:
            # Missing trigger entry means no rule choice is registered for this timing event.
            trigger_entries = []
        if not isinstance(trigger_entries, list):
            raise TypeError(f"choice_timing_index['{trigger}'] must be a list")

        current_turn = int(require_key(self.game_state, "turn"))
        current_player = int(require_key(self.game_state, "current_player"))
        owner_event_player = current_player if event_player is None else int(event_player)
        registry = self._get_unit_rule_registry()
        queue = require_key(self.game_state, "pending_rule_choice_queue")
        if not isinstance(queue, list):
            raise TypeError("pending_rule_choice_queue must be a list")

        for entry in trigger_entries:
            unit_id = str(require_key(entry, "unit_id"))
            rule_id = require_key(entry, "rule_id")
            usage_value = entry.get("usage")

            # No choice prompt for always-active or additive rules.
            if usage_value in (None, "and", "always"):
                continue
            if usage_value not in {"or", "unique"}:
                raise ValueError(f"Invalid usage '{usage_value}' for rule choice entry {entry}")

            if trigger == "activation_start":
                if activation_unit_id is None or str(activation_unit_id) != unit_id:
                    continue
            if trigger == "on_deploy":
                if activation_unit_id is None or str(activation_unit_id) != unit_id:
                    continue

            choice_timing = require_key(entry, "choice_timing")
            if not isinstance(choice_timing, dict):
                raise TypeError(f"choice_timing must be object in entry {entry}")
            if trigger in {"phase_start", "activation_start"}:
                required_phase = require_key(choice_timing, "phase")
                if required_phase != event_phase:
                    continue

            unit_player = int(require_key(entry, "unit_player"))
            if trigger == "phase_start":
                active_player_scope = require_key(choice_timing, "active_player_scope")
            else:
                active_player_scope = choice_timing.get("active_player_scope", "owner")
            if active_player_scope == "owner" and unit_player != owner_event_player:
                continue
            if active_player_scope == "opponent" and unit_player == owner_event_player:
                continue
            if active_player_scope not in {"owner", "opponent", "both"}:
                raise ValueError(
                    f"Invalid active_player_scope '{active_player_scope}' in choice_timing"
                )

            unit = self._get_unit_by_id(unit_id)
            if unit is None:
                continue
            if not is_unit_alive(unit_id, self.game_state):
                continue

            unit_rules = require_key(unit, "UNIT_RULES")
            source_rule_entry = None
            for rule in unit_rules:
                if require_key(rule, "ruleId") == rule_id:
                    source_rule_entry = rule
                    break
            if source_rule_entry is None:
                continue

            if usage_value == "unique" and source_rule_entry.get("_selected_granted_rule_id") is not None:
                continue

            grants_rule_ids = require_key(entry, "grants_rule_ids")
            if not isinstance(grants_rule_ids, list):
                raise TypeError(f"grants_rule_ids must be list for rule choice entry {entry}")
            if len(grants_rule_ids) < 2:
                continue

            event_key = (
                f"{trigger}|{current_turn}|{event_phase or '-'}|{owner_event_player}|"
                f"{unit_id}|{rule_id}"
            )
            # RÉSERVE AVANT D'AGIR, comme `cp_gain_on_objective_resolved` : ce qui suit
            # empile un prompt, le rejouer en empilerait deux.
            if once_claimed(self.game_state, "_choice_timing_fired_events", event_key):
                continue
            once_claim(self.game_state, "_choice_timing_fired_events", event_key)

            options: List[Dict[str, str]] = []
            for granted_display_rule_id_raw in grants_rule_ids:
                granted_display_rule_id = str(granted_display_rule_id_raw)
                if granted_display_rule_id not in registry:
                    raise KeyError(
                        f"Unknown granted display rule id '{granted_display_rule_id}' "
                        f"for unit {unit_id} rule '{rule_id}'"
                    )
                granted_rule_cfg = registry[granted_display_rule_id]
                option_label = require_key(granted_rule_cfg, "name")
                if not isinstance(option_label, str) or not option_label.strip():
                    raise ValueError(
                        f"Rule '{granted_display_rule_id}' must define non-empty 'name' for choice label"
                    )
                options.append(
                    {
                        "display_rule_id": granted_display_rule_id,
                        "technical_rule_id": self._resolve_rule_id_to_technical(granted_display_rule_id),
                        "label": option_label.strip(),
                    }
                )

            queue.append(
                {
                    "trigger": trigger,
                    "phase": event_phase,
                    "player": unit_player,
                    "unit_id": unit_id,
                    "rule_id": rule_id,
                    "display_name": require_key(entry, "display_name"),
                    "usage": usage_value,
                    "options": options,
                }
            )

    def _record_rule_choice_action_log(
        self,
        prompt: Dict[str, Any],
        selected_display_rule_id: str,
        consumes_gym_step: bool = False,
    ) -> None:
        """Record one rule choice in action_logs and step.log.

        `consumes_gym_step` : True quand le choix a été joué par une ACTION GYM (`CHOICE_i` du
        mécanisme de décision, V11 §9.3 P2). Ce cas consomme un `step()` complet, donc un step du
        moteur : sans ce drapeau, la ligne `Steps=` de fin d'épisode (compteur du StepLogger)
        serait inférieure à `Total=` (compteur moteur) d'exactement le nombre de décisions, et
        l'écart passerait pour le symptôme de §T6-c (« actions non journalisées »).
        Les autres chemins — prompt humain PvP, résolution PvE par `pve_controller` — ne
        consomment aucun step gym : le drapeau y reste False.
        """
        unit_id = str(require_key(prompt, "unit_id"))
        prompt_player = int(require_key(prompt, "player"))
        registry = self._get_unit_rule_registry()
        if selected_display_rule_id not in registry:
            raise KeyError(
                f"Unknown selected display rule id '{selected_display_rule_id}' in rule choice log"
            )
        selected_rule_cfg = registry[selected_display_rule_id]
        selected_rule_name = require_key(selected_rule_cfg, "name")
        if not isinstance(selected_rule_name, str) or not selected_rule_name.strip():
            raise ValueError(
                f"Rule '{selected_display_rule_id}' must define non-empty 'name' for rule choice logging"
            )
        selected_rule_name_upper = selected_rule_name.strip().upper()
        unit = self._get_unit_by_id(unit_id)
        if unit is None:
            raise KeyError(f"Cannot record rule choice log: unit {unit_id} not found")
        unit_col, unit_row = require_unit_position(unit, self.game_state)
        message = f"Unit {unit_id}({unit_col},{unit_row}) chose [{selected_rule_name_upper}]"

        action_logs = self.game_state.get("action_logs")
        if not isinstance(action_logs, list):
            raise TypeError(
                f"game_state['action_logs'] must be a list before rule choice logging, got {type(action_logs).__name__}"
            )
        from engine.action_log_utils import append_action_log

        append_action_log(
            self.game_state,
            {
                "type": "rule_choice",
                "message": message,
                "unitId": unit_id,
                "player": prompt_player,
                "col": unit_col,
                "row": unit_row,
                "selectedRuleId": selected_display_rule_id,
                "selectedRuleName": selected_rule_name_upper,
                "ruleId": require_key(prompt, "rule_id"),
                "trigger": require_key(prompt, "trigger"),
                "phase": prompt.get("phase"),
            },
        )

        # write to step.log immediately because select_rule_choice bypasses normal step logger flow
        #
        # Pas de try/except autour de ce bloc. Il y en avait un, `except Exception` -> console log,
        # cense « ne pas faire tomber la partie pour un defaut de journal ». Il ne tenait pas cette
        # promesse : ce qui peut legitimement echouer ici, c'est l'ecriture disque, et elle est deja
        # protegee un cran plus bas — `StepLogger.log_action` enveloppe tout son formatage et son
        # write dans son propre try/except (`ai/step_logger.py`, « Step logging error »).
        # Ce filet-ci n'attrapait donc QUE les `require_key` ci-dessous : une rupture d'etat du
        # game_state (`phase`/`turn`/`episode_number` manquants), qui n'est pas une panne de journal
        # et doit rester bruyante. Le depot a deja paye pour ce motif — un journal qui avale ses
        # exceptions a coute un diagnostic entier sur le replay.
        if self.step_logger and self.step_logger.enabled:
            phase_raw = prompt.get("phase")
            if not isinstance(phase_raw, str) or not phase_raw.strip():
                phase_for_log = str(require_key(self.game_state, "phase"))
            else:
                phase_for_log = phase_raw.strip()
            self.step_logger.log_action(
                unit_id=unit_id,
                action_type="rule_choice",
                phase=phase_for_log,
                player=prompt_player,
                success=True,
                step_increment=consumes_gym_step,
                action_details={
                    "current_turn": require_key(self.game_state, "turn"),
                    "current_episode": require_key(self.game_state, "episode_number"),
                    "unit_with_coords": f"{unit_id}({unit_col},{unit_row})",
                    "selected_rule_name": selected_rule_name_upper,
                    "reward": 0.0,
                },
            )

    def _apply_rule_choice_selection(
        self,
        prompt: Dict[str, Any],
        selected_display_rule_id: str,
        consumes_gym_step: bool = False,
    ) -> None:
        """Apply one selected option to unit rule runtime state.

        `consumes_gym_step` : cf. `_record_rule_choice_action_log` — True uniquement quand le
        choix vient d'une action gym `CHOICE_i` (V11 §9.3 P2).
        """
        unit_id = str(require_key(prompt, "unit_id"))
        rule_id = require_key(prompt, "rule_id")
        options = require_key(prompt, "options")
        allowed_display_rule_ids = {require_key(opt, "display_rule_id") for opt in options}
        if selected_display_rule_id not in allowed_display_rule_ids:
            raise ValueError(
                f"Invalid selected display rule '{selected_display_rule_id}' for prompt {prompt}"
            )

        unit = self._get_unit_by_id(unit_id)
        if unit is None:
            raise KeyError(f"Cannot apply rule choice: unit {unit_id} not found")
        unit_rules = require_key(unit, "UNIT_RULES")
        for rule in unit_rules:
            if require_key(rule, "ruleId") == rule_id:
                rule["_selected_granted_rule_id"] = selected_display_rule_id
                self._record_rule_choice_action_log(
                    prompt, selected_display_rule_id, consumes_gym_step=consumes_gym_step
                )
                return
        raise KeyError(f"Rule '{rule_id}' not found in UNIT_RULES for unit {unit_id}")

    def _push_rule_choice_agent_decision(self, prompt: Dict[str, Any]) -> Dict[str, Any]:
        """Expose un prompt de rule choice à l'agent (V11 §9.3 P2) et rend la main.

        Miroir EXACT du `waiting_for_player` PvP : le moteur s'arrête sur le point de choix au
        lieu de le trancher pour l'agent. L'ordre des candidats est celui du prompt — donc celui
        de `grants_rule_ids` dans la datasheet, STABLE d'un step à l'autre (contrat §9.6).

        Remplace `raw_action_int % len(options)` (§9.4 point 0) : l'agent « choisissait » via une
        action émise pour tout autre chose, sans voir le prompt.
        """
        options = require_key(prompt, "options")
        if not isinstance(options, list) or not options:
            raise ValueError(f"Agent rule choice requires non-empty options list, got: {options!r}")

        decision_options: List[Dict[str, Any]] = []
        for option in options:
            display_rule_id = require_key(option, "display_rule_id")
            technical_rule_id = require_key(option, "technical_rule_id")
            decision_options.append(
                {
                    "label": require_key(option, "label"),
                    # Ce que le candidat ACCORDE, dans le vocabulaire d'observation des règles
                    # d'unité (§0.31) : c'est la seule description qui ait un sens pour l'agent.
                    "effect_ids": (str(technical_rule_id),),
                    # `rule_choice` n'a pas de candidat « ne rien faire » : le prompt naît d'une
                    # règle en « usage: or », chaque candidat ACCORDE quelque chose. Déclaré et
                    # non omis — le champ est exigé, pour qu'un futur type de décision optionnel
                    # ne puisse pas passer en silence.
                    "declines": False,
                    "payload": {"display_rule_id": str(display_rule_id)},
                }
            )
        set_pending_agent_decision(
            self.game_state,
            decision_type="rule_choice",
            player=int(require_key(prompt, "player")),
            unit_id=str(require_key(prompt, "unit_id")),
            options=decision_options,
        )
        return {
            "action": "waiting_for_agent_decision",
            "waiting_for_player": True,
            "decision_type": "rule_choice",
            "rule_choice_prompt": prompt,
            "unitId": require_key(prompt, "unit_id"),
            "player": int(require_key(prompt, "player")),
        }

    def _handle_agent_decision_action(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Applique le candidat choisi par l'agent (action `CHOICE_i`), puis reprend le moteur."""
        decision = read_pending_agent_decision(self.game_state)
        if decision is None:
            return False, {"error": "no_pending_agent_decision"}
        option_index = require_key(action, "option_index")
        if not isinstance(option_index, int) or isinstance(option_index, bool):
            raise TypeError(
                f"agent_decision requiert un 'option_index' entier, recu {option_index!r}"
            )
        options = require_key(decision, "options")
        if option_index < 0 or option_index >= len(options):
            raise ValueError(
                f"agent_decision: candidat {option_index} hors des {len(options)} candidats "
                "— le masque n'aurait pas du l'autoriser"
            )
        decision_type = require_key(decision, "type")
        selected_option = options[option_index]

        if decision_type == "waaagh_call":
            # Waaagh! (chantier 03) : décision d'ARMÉE, sans file de prompts ni unité. L'ordre des
            # candidats est CONTRACTUEL — c'est lui, et non un `effect_ids`, qui porte le sens
            # (cf. AGENT_DECISION_TYPE_IDS) : le payload le rend explicite côté moteur.
            called = bool(require_key(require_key(selected_option, "payload"), "call"))
            # Le joueur passé au vérificateur vient de l'ÉTAT, jamais de la décision. Le lire dans
            # la décision pour le lui repasser comparait la décision à elle-même : un contrôle
            # qui ne pouvait pas se déclencher (« vert vacant »). Lu ici, il refuse une décision
            # qui a survécu au tour de son propriétaire — le seul siège qui puisse y répondre.
            # Mesuré sur 3 épisodes : 31 décisions, 0 dont le joueur diffère de `current_player`.
            decision_player = int(require_key(self.game_state, "current_player"))
            # `apply_waaagh_call_decision` efface la decision elle-meme (ecrivain unique).
            command_handlers.apply_waaagh_call_decision(
                self.game_state, decision_player, called
            )
            return True, self._resume_command_phase_after_faction_decision(
                {
                    "action": "agent_decision",
                    "waiting_for_player": False,
                    "decision_type": decision_type,
                    "unitId": require_key(decision, "unit_id"),
                    "player": decision_player,
                    "option_index": option_index,
                    "waaaghCalled": called,
                    "success": True,
                }
            )

        if decision_type == "fly_declaration":
            # 21.03 « take to the skies » (V11 §0.48 `L6`) : décision d'ESCOUADE, par mouvement,
            # sans file de prompts. Comme pour le Waaagh!, c'est l'ORDRE des candidats qui porte
            # le sens (aucun `effect_ids`) et le payload qui le rend explicite côté moteur.
            declared = bool(require_key(require_key(selected_option, "payload"), "declare"))
            decision_squad_id = str(require_key(decision, "unit_id"))
            # `apply_fly_declaration_decision` efface la decision elle-meme (ecrivain unique).
            movement_handlers.apply_fly_declaration_decision(
                self.game_state, decision_squad_id, declared
            )
            # Aucune reprise de phase a enchainer : l'activation reprend d'elle-meme au step
            # suivant, le masque etant reconstruit sur la declaration desormais ecrite.
            return True, {
                "action": "agent_decision",
                "waiting_for_player": False,
                "decision_type": decision_type,
                "unitId": decision_squad_id,
                "player": int(require_key(decision, "player")),
                "option_index": option_index,
                "tookToSkies": declared,
                "success": True,
            }

        if decision_type != "rule_choice":
            raise NotImplementedError(
                f"agent_decision: type '{decision_type}' declare mais sans application moteur. "
                "Chaque type ajoute a AGENT_DECISION_TYPE_IDS doit etre branche ICI."
            )

        queue = require_key(self.game_state, "pending_rule_choice_queue")
        if not isinstance(queue, list) or not queue:
            raise RuntimeError(
                "agent_decision: decision 'rule_choice' en attente alors que la file de prompts "
                "est vide — l'etat de choix a ete efface sans effacer la decision."
            )
        prompt = queue[0]
        if str(require_key(prompt, "unit_id")) != str(require_key(decision, "unit_id")):
            raise RuntimeError(
                f"agent_decision: la decision porte sur l'unite {decision['unit_id']} mais la file "
                f"presente {prompt['unit_id']} — les deux etats ont divergé."
            )
        selected_display_rule_id = require_key(
            require_key(selected_option, "payload"), "display_rule_id"
        )
        # L'action `CHOICE_i` a consommé un step gym complet : la ligne de step.log doit
        # l'incrémenter, sinon `Steps=` et `Total=` divergent en fin d'épisode.
        self._apply_rule_choice_selection(
            prompt, selected_display_rule_id, consumes_gym_step=True
        )
        queue.pop(0)
        clear_pending_agent_decision(self.game_state)

        # Un même événement peut avoir empilé plusieurs prompts : le suivant repose immédiatement
        # une décision, et le moteur rend de nouveau la main.
        next_prompt_result = self._emit_next_rule_choice_prompt_if_needed()
        if next_prompt_result is not None:
            return True, next_prompt_result
        return True, {
            "action": "agent_decision",
            "waiting_for_player": False,
            "decision_type": decision_type,
            "unitId": require_key(decision, "unit_id"),
            "player": int(require_key(decision, "player")),
            "option_index": option_index,
            "selectedRuleId": selected_display_rule_id,
            "success": True,
        }

    # ── Capacités de faction (chantier 03) : Waaagh! et Oath of Moment ─────────────────────
    #
    # Les décisions sont POSÉES par `command_handlers.command_step_command_abilities` (08.04) et
    # RÉSOLUES ici, parce que c'est ici que vit la seule chose que le handler ne connaît pas :
    # qui pilote un siège. Trois cas, exactement les mêmes que pour les choix de règle :
    #   - gym            → le siège passe par le MASQUE (agent ou bot), le moteur rend la main ;
    #   - humain (PvP)   → `waiting_for_player`, résolu par une action explicite de l'API ;
    #   - IA hors gym    → tranché immédiatement par la politique ci-dessous.

    def start_command_phase(self) -> Dict[str, Any]:
        """Ouvre la phase de commandement — POINT D'ENTRÉE UNIQUE, moteur ET services.

        `command_phase_start` seule ne suffit plus depuis que 08.04 peut poser une décision : un
        siège piloté par une IA hors gym n'a personne pour y répondre, et la phase resterait
        arrêtée. Router les appels par ici évite qu'un seul oublie la résolution — c'est
        exactement le motif « corrigé d'un côté, pas de l'autre » du dépôt.

        PUBLIQUE, et c'est le correctif du finding 2 de la review du 2026-08-05 : quatre
        appelants HORS moteur (`services/endless_duty_runtime`, `services/api_server`)
        appelaient le handler directement, jetaient son retour et enchaînaient sur la phase de
        mouvement. Une désignation d'Oath y restait posée pour tout le run — et Endless Duty
        commence justement avec un Intercessor, donc ADEPTUS ASTARTES.

        ⚠️ Le retour DOIT être respecté : `phase_complete` faux signifie que la phase attend une
        réponse, et enchaîner sur le mouvement la perd.
        """
        command_handlers.command_phase_start(self.game_state)
        # UNE seule exécution de `command_phase_resume`, ici. `command_phase_start` ne la rend
        # plus : elle la rendait avant, ce qui obligeait ce site à la rejouer et donc à garder
        # un `if` pour ne pas exécuter `command_phase_end` deux fois. `_resolve…` sort d'elle-même
        # quand rien n'attend, et elle est bornée au joueur actif.
        self._resolve_faction_decisions_for_ai_seats()
        return command_handlers.command_phase_resume(self.game_state)

    def _resume_command_phase_after_faction_decision(
        self, result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Complète le résultat d'une décision de 08.04 par la suite de la phase.

        Sans cela, une phase de commandement arrêtée sur une décision ne repartirait jamais : le
        tour d'un joueur bot se terminerait sur un masque vide, et le moteur ne passerait pas au
        move. `command_phase_resume` est idempotente — c'est ce qui permet de la rappeler ici
        après CHAQUE décision, y compris quand une seconde vient d'être posée.

        ⚠️ Le retour de la reprise est HONORÉ ici, pas seulement recopié dans `result` : les deux
        routes de décision (`agent_decision`, `select_oath_target`) sortent de
        `_process_semantic_action` / `_process_squad_action` AVANT la boucle de cascade, qui est
        le seul endroit où une transition de phase s'exécute. Le `phase_complete` rendu au client
        décrivait donc une transition qui n'avait pas eu lieu : la partie restait en phase de
        commandement une fois l'Oath désigné. Le gym s'en sortait par accident (son masque garde
        un WAIT, qui termine la phase au step suivant) ; le PvP, lui, n'a AUCUN verbe de sortie de
        cette phase — il n'en avait pas besoin tant que rien ne l'y arrêtait. C'est le même
        `if phase_complete → movement_phase_start` que les quatre appelants de
        `start_command_phase` hors moteur (`api_server`, `endless_duty_runtime`).
        """
        self._resolve_faction_decisions_for_ai_seats()
        resume = command_handlers.command_phase_resume(self.game_state)
        result.update(resume)
        if resume.get("phase_complete"):  # get allowed : absent == phase non close
            movement_handlers.movement_phase_start(self.game_state)
        return result

    def _resolve_faction_decisions_for_ai_seats(self) -> None:
        """Tranche les décisions de 08.04 des sièges qui ne répondent ni par le masque ni par l'UI.

        Boucle : appliquer le Waaagh! peut poser l'Oath juste derrière (une armée qui porterait
        les deux mots-clés de faction). Le compteur borne l'enchaînement — deux décisions par
        phase au maximum, une troisième signalerait un état incohérent plutôt qu'un cas de jeu.
        """
        # En gym, les DEUX sièges répondent par le masque : cette fonction n'a rien à trancher.
        # Le test est INVARIANT, il sort donc avant la boucle au lieu d'être répété dans chacune
        # de ses deux branches.
        if self.gym_training_mode:
            return
        current_player = int(require_key(self.game_state, "current_player"))
        # Bornée par le nombre de mécanismes de 08.04, pas par un littéral : appliquer le Waaagh!
        # peut poser l'Oath juste derrière (armée portant les deux mots-clés de faction), et une
        # itération de plus signalerait un état qui ne se vide pas — pas un cas de jeu.
        for _ in range(len(command_handlers.COMMAND_PHASE_DECISION_TYPES) + 1):
            if not command_handlers.faction_decision_is_pending(self.game_state, current_player):
                return
            if self._is_player_human(current_player):
                return
            decision = read_pending_agent_decision(self.game_state)
            if decision is not None and str(
                require_key(decision, "type")
            ) in command_handlers.COMMAND_PHASE_DECISION_TYPES:
                command_handlers.apply_waaagh_call_decision(
                    self.game_state, current_player, self._select_ai_waaagh_call(current_player)
                )
                continue
            command_handlers.apply_oath_selection(
                self.game_state, current_player, self._select_ai_oath_target(current_player)
            )
        raise RuntimeError(
            "08.04 : plus de decisions de capacite de faction enchainees qu'il n'existe de "
            "mecanismes pour un meme joueur — l'etat de decision ne se vide pas."
        )

    def _reject_action_while_faction_decision_pending(
        self, action: Dict[str, Any]
    ) -> Optional[Tuple[bool, Dict[str, Any]]]:
        """Refuse toute action tant que 08.04 attend la réponse du joueur ACTIF.

        L'arrêt de phase de `command_phase_resume` n'était pas OPPOSABLE : les deux points
        d'entrée (`_process_semantic_action` pour l'UI PvP, `_process_squad_action` pour le
        gym) routent d'abord la réponse à la décision, puis laissaient passer TOUT le reste.
        Or `advance_phase` est intercepté AVANT le dispatch de phase et rend
        `{"next_phase": "move"}`, et n'importe quel autre verbe tombait dans
        `_process_command_phase` → `command_phase_end()`. Dans les deux cas la phase se
        terminait avec `pending_oath_selection` encore posé : la désignation d'Oath était
        perdue pour tout le tour (purgée à l'ouverture de la command phase suivante par
        `expire_faction_abilities_for_player`), donc plus aucune relance de touche, sans le
        moindre message. Un seul clic hors overlay suffisait.

        Rend un refus INERTE (aucune mutation) : c'est ce qui rend l'arrêt réel plutôt que
        conventionnel. Appelée APRÈS le routage de `agent_decision` / `select_oath_target` —
        seule la réponse à la décision est légale, ce que le masque du gym exprime déjà en
        étant exclusif.
        """
        if self.game_state["phase"] != "command":
            return None
        current_player = int(require_key(self.game_state, "current_player"))
        if not command_handlers.faction_decision_is_pending(self.game_state, current_player):
            return None
        # Forme des refus des trois autres phases (`movement_handlers.py:1043` et ses jumeaux) :
        # le motif machine dans `error`, le verbe refusé dans `action`, la phase dans `phase`.
        return False, {
            "error": "faction_decision_pending",
            "action": action.get("action"),
            "phase": "command",
            "player": current_player,
        }

    def _select_ai_waaagh_call(self, player: int) -> bool:
        """Politique du siège IA hors gym pour « appeler ou non le Waaagh! ».

        Appelle dès qu'au moins une unité orke est à portée de charge : le Waaagh! est une
        décision de TEMPO, et son rendement (+1 S/A en mêlée, charge après Advance) est nul tant
        que rien ne peut atteindre l'adversaire. Ce n'est pas une valeur par défaut mais une
        politique explicite, du même ordre que `_select_ai_rule_choice_option` — le gym, lui, ne
        passe jamais ici : l'agent apprend ce tempo, c'est tout l'intérêt de la décision.
        """
        from engine.game_state import unit_has_waaagh_ability
        from engine.phase_handlers.shooting_handlers import _ranged_distance_metric
        from engine.combat_utils import ranged_edge_distance, socle_from_cache_entry
        from engine.spatial_relations import (
            enemy_entries_on_battlefield, entries_on_battlefield,
        )

        units_cache = require_key(self.game_state, "units_cache")
        metric = _ranged_distance_metric(self.game_state)
        # 11.02 : la charge est un 2D6, donc 12" au maximum. Mesure en subhex, comme tout le
        # reste du moteur (`inches_to_subhex`, config de plateau).
        charge_reach = float(require_key(self.config, "inches_to_subhex")) * 12.0
        # `*_on_battlefield` et pas « vivante » : une unité en réserves (20.01) est vivante ET
        # présente dans `units_cache`, mais posée à la sentinelle (-1,-1). Un filtre écrit sur
        # « vivante » la laisse passer, et la distance mesurée depuis la sentinelle ne décrit
        # rien — c'est le filtre UNIQUE que `spatial_relations` existe pour porter.
        enemy_socles = {
            enemy_id: socle_from_cache_entry(entry)
            for enemy_id, entry in enemy_entries_on_battlefield(units_cache, int(player))
        }
        if not enemy_socles:
            return False
        for squad_id, entry in entries_on_battlefield(units_cache):
            if int(require_key(entry, "player")) != int(player):
                continue
            unit = self._get_unit_by_id(squad_id)
            if unit is None or not unit_has_waaagh_ability(self.game_state, unit):
                continue
            socle = socle_from_cache_entry(entry)
            # Socles des DEUX camps précalculés : `_ranged_squad_edge_distance` reconstruisait
            # celui de la cible à chaque appel, donc une fois par unité orke et par ennemi.
            for enemy_socle in enemy_socles.values():
                if ranged_edge_distance(socle, enemy_socle, metric) <= charge_reach:
                    return True
        return False

    def _select_ai_oath_target(self, player: int) -> str:
        """Politique du siège IA hors gym pour la cible d'Oath : l'ennemi vivant le plus coûteux.

        « select ONE unit » est obligatoire : cette fonction ne peut pas rendre « aucune », et
        elle lève si le pool est vide — un état que `command_step_command_abilities` ne produit
        pas (il ne pose la désignation que s'il existe une cible).
        """
        candidates = command_handlers.oath_selectable_enemy_ids(self.game_state, int(player))
        if not candidates:
            raise RuntimeError(
                f"_select_ai_oath_target: aucune unite ennemie vivante pour le joueur {player} — "
                f"la designation n'aurait pas du etre posee."
            )
        # `_get_unit_by_id` (index `unit_by_id`) plutôt qu'un second index reconstruit ici : la
        # classe l'utilise déjà partout ailleurs, et l'index existe depuis le reset.
        def _value_of(unit_id: str) -> Tuple[int, str]:
            unit = self._get_unit_by_id(unit_id)
            if unit is None:
                raise KeyError(f"_select_ai_oath_target: unite {unit_id!r} absente de l'index")
            return int(require_key(unit, "VALUE")), unit_id

        return max(candidates, key=_value_of)

    def _handle_select_activation_action(
        self, action: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """Enregistre l'escouade que l'agent a choisi d'activer (V11 §0.48 élément L2 / §9 P3-3).

        N'active RIEN par elle-même : elle pose le marqueur que
        `ActionDecoder._get_eligible_units_for_current_phase` lit pour remonter cette escouade en
        tête du pool. L'activation proprement dite reste le step suivant, avec le masque et
        l'observation de l'escouade choisie — c'est ce que la grille de move égocentrique impose
        (`ObservationBuilder.squad_grid_anchor`) : « aller en cellule (gx,gy) » n'a pas de sens
        tant qu'on ne sait pas qui bouge.

        La légalité est revérifiée ici, contre la MÊME source que le masque : le moteur ne fait
        jamais confiance à un `unitId` reçu, qu'il vienne du décodeur ou de l'API.
        """
        slots = self.action_decoder.activation_selection_slots(self.game_state)
        if slots is None:
            return False, {"error": "no_pending_activation_choice"}
        unit_id = str(require_key(action, "unitId"))
        if unit_id not in set(slots.values()):
            return False, {
                "error": "activation_choice_not_open",
                "unitId": unit_id,
                "open": sorted(set(slots.values())),
            }
        # Le marqueur porte SA PORTÉE (tour, phase, joueur) : sans elle, il survivrait au
        # changement de phase — les pools sont par phase, donc l'escouade qui vient de bouger est
        # toujours dans le pool de tir, et son marqueur y aurait supprimé le choix suivant.
        self.game_state[self.action_decoder.ACTIVATION_CHOSEN_KEY] = {
            "squad_id": unit_id,
            "scope": self.action_decoder.activation_choice_scope(self.game_state),
        }
        return True, {
            "action": "select_activation",
            "unitId": unit_id,
            "phase": require_key(self.game_state, "phase"),
            "success": True,
        }

    def _handle_select_oath_target_action(
        self, action: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """Applique la désignation d'Oath — chemin COMMUN au gym (slot décodé) et au PvP (UI).

        Le décodeur produit exactement ce dict pour un `OATH_SLOT_i` ; l'API PvP l'émet tel
        quel. Une seule application, donc une seule règle : c'est ce qui empêche le PvP et le gym
        de diverger sur une capacité (motif « jumeau » du dépôt).
        """
        pending = self.game_state.get("pending_oath_selection")  # get allowed : None = aucune
        if pending is None:
            return False, {"error": "no_pending_oath_selection"}
        player = int(pending)
        if "player" in action and int(action["player"]) != player:
            return False, {
                "error": "oath_wrong_player",
                "expected_player": player,
                "received_player": int(action["player"]),
            }
        target_unit_id = str(require_key(action, "unitId"))
        command_handlers.apply_oath_selection(self.game_state, player, target_unit_id)
        return True, self._resume_command_phase_after_faction_decision(
            {
                "action": "select_oath_target",
                "waiting_for_player": False,
                "player": player,
                "unitId": target_unit_id,
                "success": True,
            }
        )

    def _select_ai_rule_choice_option(self, prompt: Dict[str, Any]) -> str:
        """
        Select one rule-choice option for AI players using trained policy.
        """
        options = require_key(prompt, "options")
        if not isinstance(options, list) or not options:
            raise ValueError(f"AI rule choice requires non-empty options list, got: {options!r}")

        if not hasattr(self, "pve_controller"):
            raise RuntimeError("AI rule choice requires pve_controller to be initialized")
        if not self.pve_controller.is_ready_for_decision():
            raise RuntimeError("AI rule choice requires loaded micro models in pve_controller")
        return self.pve_controller.select_rule_choice_with_policy(
            prompt=prompt,
            game_state=self.game_state,
            engine=self,
        )

    def _emit_next_rule_choice_prompt_if_needed(self) -> Optional[Dict[str, Any]]:
        """Return waiting payload for next human prompt, auto-resolving AI prompts."""
        self._initialize_rule_choice_runtime_state()
        queue = require_key(self.game_state, "pending_rule_choice_queue")
        if not isinstance(queue, list):
            raise TypeError("pending_rule_choice_queue must be a list")

        while queue:
            prompt = queue[0]
            prompt_player = int(require_key(prompt, "player"))
            options = require_key(prompt, "options")
            if not isinstance(options, list) or not options:
                queue.pop(0)
                continue

            if self._is_player_human(prompt_player):
                self.game_state["active_rule_choice_prompt"] = prompt
                return {
                    "action": "waiting_for_rule_choice",
                    "waiting_for_player": True,
                    "rule_choice_prompt": prompt,
                    "unitId": require_key(prompt, "unit_id"),
                    "player": prompt_player,
                }

            if self.gym_training_mode:
                # Gym : le choix appartient à celui qui joue ce siège (agent OU bot adversaire —
                # tous deux passent par le masque). Le moteur rend la main au lieu de trancher.
                # `active_rule_choice_prompt` reste None : c'est l'état du prompt HUMAIN, et le
                # poser ici court-circuiterait `_process_squad_action` avant l'action CHOICE.
                self.game_state["active_rule_choice_prompt"] = None
                return self._push_rule_choice_agent_decision(prompt)

            # AI side: policy-based option selection (no heuristic default behavior).
            selected_display_rule_id = self._select_ai_rule_choice_option(prompt)
            self._apply_rule_choice_selection(prompt, selected_display_rule_id)
            queue.pop(0)
            self.game_state["active_rule_choice_prompt"] = None

        self.game_state["active_rule_choice_prompt"] = None
        return None

    def _handle_select_rule_choice_action(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Apply player's explicit rule-choice selection."""
        self._initialize_rule_choice_runtime_state()
        active_prompt = self.game_state.get("active_rule_choice_prompt")
        if active_prompt is None:
            return False, {"error": "no_active_rule_choice_prompt"}
        queue = require_key(self.game_state, "pending_rule_choice_queue")
        if not isinstance(queue, list):
            raise TypeError("pending_rule_choice_queue must be a list")

        selected_display_rule_id_raw = action.get("selectedRuleId")
        if not isinstance(selected_display_rule_id_raw, str) or not selected_display_rule_id_raw.strip():
            raise ValueError("select_rule_choice action requires non-empty 'selectedRuleId'")
        selected_display_rule_id = selected_display_rule_id_raw.strip()

        action_unit_id = str(require_key(action, "unitId"))
        selected_prompt = active_prompt
        prompt_unit_id = str(require_key(active_prompt, "unit_id"))
        if action_unit_id != prompt_unit_id:
            matching_prompt = None
            for queued_prompt in queue:
                if str(require_key(queued_prompt, "unit_id")) == action_unit_id:
                    matching_prompt = queued_prompt
                    break
            if matching_prompt is None:
                return False, {
                    "error": "rule_choice_wrong_unit",
                    "expected_unit_id": prompt_unit_id,
                    "received_unit_id": action_unit_id,
                }
            selected_prompt = matching_prompt

        expected_player = int(require_key(selected_prompt, "player"))
        if "player" in action and int(action["player"]) != expected_player:
            return False, {
                "error": "rule_choice_wrong_player",
                "expected_player": expected_player,
                "received_player": int(action["player"]),
            }

        self._apply_rule_choice_selection(selected_prompt, selected_display_rule_id)
        selected_prompt_unit_id = str(require_key(selected_prompt, "unit_id"))
        if queue and queue[0] == selected_prompt:
            queue.pop(0)
        else:
            queue[:] = [prompt for prompt in queue if prompt != selected_prompt]
        self.game_state["active_rule_choice_prompt"] = None

        next_prompt_result = self._emit_next_rule_choice_prompt_if_needed()
        if next_prompt_result is not None:
            return True, next_prompt_result

        return True, {
            "action": "select_rule_choice",
            "waiting_for_player": False,
            "unitId": selected_prompt_unit_id,
            "player": expected_player,
            "ruleId": require_key(selected_prompt, "rule_id"),
            "selectedRuleId": selected_display_rule_id,
            "success": True,
        }
    
    
    def _handle_hazard_confirm(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Desperate Escape (09.07) — validation du popup hazard à l'activation.

        Résout le hazard (06.03) + attribution 06.02 AVANT de bouger, puis :
        - unité détruite → fin d'activation sans move (``desperate_escape_died``) ;
        - unité vivante  → (re)construit le pool Fall Back et repasse en preview.
        """
        from engine.phase_handlers.shared_utils import (
            desperate_escape_pre_move, _squad_is_in_enemy_er,
        )

        uid = action.get("unitId")
        if uid is None:
            return False, {"error": "hazard_confirm requires unitId"}
        unit = self._get_unit_by_id(str(uid))
        if unit is None:
            return False, {"error": f"hazard_confirm: unit {uid} not found"}

        was_engaged = _squad_is_in_enemy_er(self.game_state, str(uid))
        if not was_engaged or not bool(require_key(unit, "battle_shocked")):
            return False, {
                "error": f"hazard_confirm: unit {uid} not in Desperate Escape "
                          "(engaged + battle_shocked required)"
            }

        auto_resolve = bool(self.game_state.get("gym_training_mode", False))
        desperate_escape_pre_move(str(uid), self.game_state, was_engaged, auto_resolve)

        # Un choix d'attribution joueur est-il en attente ? → prompt (declaration d'ordre des
        # groupes puis/ou clic figurine), calque sur l'allocation des pertes au tir.
        if self.game_state.get("pending_hazard_allocation") is not None:
            from engine.phase_handlers.shared_utils import manual_allocation_waiting_payload, HAZARD_CTX
            return True, manual_allocation_waiting_payload(self.game_state, HAZARD_CTX)

        # Attribution terminée (auto / pas de choix) → reprise du flux move.
        return self._resume_after_hazard(str(uid))


    def _handle_hazard_declare_order(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Declaration de l'ordre des groupes pour l'attribution des mortal wounds (hazard).

        Enregistre l'ordre puis avance : nouveau point de decision (choix de figurine) →
        prompt ; allocation terminee → reprise du flux move (Fall Back ou mort de l'unité)."""
        from engine.phase_handlers.shared_utils import apply_manual_shoot_declare_order, HAZARD_CTX
        pending = self.game_state.get("pending_hazard_allocation")
        if pending is None:
            return False, {"error": "squad_hazard_declare_order: no pending hazard allocation"}
        order = action.get("order")
        if order is None:
            return False, {"error": "squad_hazard_declare_order requires order"}
        uid = str(pending["attacker_squad_id"])
        alloc_result = apply_manual_shoot_declare_order(self.game_state, list(order), HAZARD_CTX)
        if alloc_result.get("waiting_for_player"):
            return True, alloc_result
        return self._resume_after_hazard(uid)


    def _handle_hazard_allocate_model(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Clic figurine pour l'attribution manuelle des mortal wounds (hazard, 06.02).

        Applique 1 MW à la figurine choisie puis poursuit la séquence : si un nouveau choix
        apparaît → re-prompt ; sinon → reprise du flux move (Fall Back ou mort de l'unité)."""
        from engine.phase_handlers.shared_utils import apply_manual_shoot_allocation, HAZARD_CTX
        pending = self.game_state.get("pending_hazard_allocation")
        if pending is None:
            return False, {"error": "squad_hazard_allocate_model: no pending hazard allocation"}
        model_id = action.get("modelId")
        if model_id is None:
            return False, {"error": "squad_hazard_allocate_model requires modelId"}
        uid = str(pending["attacker_squad_id"])
        alloc_result = apply_manual_shoot_allocation(self.game_state, str(model_id), HAZARD_CTX)
        if alloc_result.get("waiting_for_player"):
            return True, alloc_result
        return self._resume_after_hazard(uid)


    def _resume_after_hazard(self, uid: str) -> Tuple[bool, Dict[str, Any]]:
        """Reprise du flux après attribution du hazard, selon l'ORIGINE du jet.

        - ``shoot`` / ``fight`` : [HAZARDOUS] 24.15, déclenché APRÈS que l'unité a résolu
          toutes ses attaques. Il n'y a plus rien à reprendre : l'activation est terminée.
        - ``move`` (défaut historique) : Desperate Escape 09.07, déclenché AVANT le fall back —
          unité morte → fin d'activation sans move ; sinon → pool Fall Back + preview.
        """
        from engine.phase_handlers.shared_utils import is_unit_alive
        from engine.phase_handlers import movement_handlers as _mh
        sid = str(uid)
        hazard_origin = self.game_state.pop("hazard_origin", "move")
        if hazard_origin in ("shoot", "fight"):
            return True, {
                "action": f"squad_{hazard_origin}_manual_alloc",
                "unitId": sid,
                "activation_complete": True,
                "waiting_for_player": False,
                "done": True,
            }
        if not is_unit_alive(sid, self.game_state):
            _mh._invalidate_all_destination_pools_after_movement(self.game_state)
            _mh.movement_clear_preview(self.game_state)
            return True, {
                "action": "desperate_escape_died",
                "unitId": sid,
                "activation_complete": True,
                "waiting_for_player": False,
            }
        # Hazard résolu, unité vivante → on (re)pose l'unité active + le pool Fall Back. Côté
        # front, ce payload est identique à une activation engagée normale → le flux move preview
        # (ghost + Valider) reprend exactement comme pour une unité non hazardée.
        self.game_state["active_movement_unit"] = sid
        _mh.movement_build_valid_destinations_pool(self.game_state, sid)
        pool = self.game_state["valid_move_destinations_pool"]
        self.game_state["preview_hexes"] = pool
        unit = self._get_unit_by_id(sid)
        if unit is None:
            raise KeyError(f"Flee-preview unit {sid} missing from game_state['units']")
        return True, {
            "unit_activated": True,
            "unitId": unit["id"],
            "valid_destinations": pool,
            "preview_data": _mh.movement_preview(pool),
            "waiting_for_player": True,
            "would_flee": True,
            "advance_roll": _mh._advance_roll_for(sid, self.game_state),
            # Desperate Escape : le hazard a consommé le clic qui, normalement, entre dans le plan
            # par-figurine. Ce marqueur dit au front d'auto-entrer en perModelMove (Fall Back)
            # pour les survivants, sinon l'unité reste en mode select (trou → quick-move au clic).
            "fall_back_resume": True,
        }




    # HISTORIQUE — ce corps a porte une sourdine `# pyright: ignore[reportGeneralTypeIssues]`
    # motivee par « Code is too complex to analyze » : pyright renoncait a analyser la methode
    # entiere (1582 lignes, 205 `if`), donc le point unique de journalisation des actions
    # n'etait couvert par AUCUN controle de types. Trois defauts reels y avaient ete trouves en
    # levant la sourdine, et corriges : (a) `action_details` possiblement non lie quand l'unite
    # n'existe plus (UnboundLocalError avale par le `except Exception` du bloc), (b)
    # `require_unit_position` appele avec `updated_unit` optionnel sur la branche advance,
    # (c) deux `result.get(x).strip()` controles sur un autre acces que celui utilise.
    # La sourdine elle-meme est levee depuis que le corps a ete decompose : deux blocs qui y
    # figuraient en double a l'identique sont partis dans `_log_attack_results` (195 lignes
    # dupliquees mot pour mot) et `_log_handler_action_log_entry` (les deux passes de flush de
    # `action_logs`). Toute regression de taille ici reramene le « too complex » et rend a
    # nouveau ce corps invisible au verificateur : decomposer plutot que remettre une sourdine.
    def _process_semantic_action(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Process semantic action with detailed execution debugging.
        CRITICAL: This is the SINGLE POINT OF LOGGING for all actions (training, frontend, PvE).
        """
        if self.game_state.get("game_over", False):
            return False, {"error": "game_over", "winner": self.game_state.get("winner")}

        self._initialize_rule_choice_runtime_state()

        # Rule-choice submission action is processed before phase handlers.
        if action.get("action") == "select_rule_choice":
            return self._handle_select_rule_choice_action(action)

        # Capacités de faction (chantier 03) — MÊME rang, et c'est le chemin de l'UI PvP.
        # `_process_squad_action` les routait déjà pour le gym ; ici passe TOUT ce que le
        # frontend envoie (`execute_semantic_action`). Sans ces deux lignes, l'action tombait
        # dans `_process_command_phase` → `command_handlers.execute_action`, qui l'ignore et rend
        # `command_phase_end()` : le clic sautait à la phase de mouvement sans rien appliquer, et
        # la désignation restait posée — donc l'overlay bloquait le plateau pour de bon.
        if action.get("action") == "agent_decision":
            return self._handle_agent_decision_action(action)
        if action.get("action") == "select_oath_target":
            return self._handle_select_oath_target_action(action)
        # Choix de l'escouade à activer (V11 §0.48 L2) : MÊME rang — le moteur est arrêté sur un
        # choix de joueur qui précède l'activation, aucune action de phase n'a de sens avant.
        if action.get("action") == "select_activation":
            return self._handle_select_activation_action(action)

        blocked = self._reject_action_while_faction_decision_pending(action)
        if blocked is not None:
            return blocked

        # TEST/DEBUG : force un battle-shock roll (01.07) sur une unité, hors séquence de jeu.
        # Permet de tester le Desperate Escape (09.07) en rendant une unité battle-shocked à la demande.
        if action.get("action") == "force_battle_shock":
            from engine.phase_handlers.shared_utils import roll_battle_shock
            uid = action.get("unitId")
            if uid is None:
                return False, {"error": "force_battle_shock requires unitId"}
            if self._get_unit_by_id(str(uid)) is None:
                return False, {"error": f"force_battle_shock: unit {uid} not found"}
            shocked = roll_battle_shock(str(uid), self.game_state)
            return True, {
                "action": "force_battle_shock",
                "unitId": str(uid),
                "battle_shocked": shocked,
            }

        # TEST/DEBUG : force le statut « a chargé » (ajout à units_charged) sur une unité, hors
        # séquence de jeu. Permet de tester l'ordre Fights First (12.x) en phase fight à la demande.
        if action.get("action") == "force_charged":
            uid = action.get("unitId")
            if uid is None:
                return False, {"error": "force_charged requires unitId"}
            if self._get_unit_by_id(str(uid)) is None:
                return False, {"error": f"force_charged: unit {uid} not found"}
            self.game_state.setdefault("units_charged", set()).add(str(uid))
            return True, {
                "action": "force_charged",
                "unitId": str(uid),
                "charged": True,
            }

        # Desperate Escape (09.07) : tant qu'une attribution de mortal wounds (hazard) est en
        # attente d'un choix joueur, seul le clic figurine (squad_hazard_allocate_model) passe.
        if (
            self.game_state.get("pending_hazard_allocation") is not None
            and action.get("action") not in ("squad_hazard_allocate_model", "squad_hazard_declare_order")
        ):
            from engine.phase_handlers.shared_utils import manual_allocation_waiting_payload, HAZARD_CTX
            return True, manual_allocation_waiting_payload(self.game_state, HAZARD_CTX)

        # Desperate Escape (09.07) : le joueur a validé le popup hazard affiché à l'activation.
        # On résout le hazard (06.03) + l'attribution des mortal wounds (06.02) AVANT de bouger,
        # puis on reprend le move preview (Fall Back) ou on termine l'activation si l'unité meurt.
        if action.get("action") == "hazard_confirm":
            return self._handle_hazard_confirm(action)

        # Declaration de l'ordre des groupes pour l'attribution des mortal wounds (hazard).
        if action.get("action") == "squad_hazard_declare_order":
            return self._handle_hazard_declare_order(action)

        # Clic figurine pour l'attribution manuelle des mortal wounds (hazard).
        if action.get("action") == "squad_hazard_allocate_model":
            return self._handle_hazard_allocate_model(action)

        # Block gameplay actions while an explicit choice prompt is pending.
        active_prompt = self.game_state.get("active_rule_choice_prompt")
        if active_prompt is not None:
            return True, {
                "action": "waiting_for_rule_choice",
                "waiting_for_player": True,
                "rule_choice_prompt": active_prompt,
                "unitId": require_key(active_prompt, "unit_id"),
                "player": int(require_key(active_prompt, "player")),
            }

        # Block gameplay actions while a manual casualty allocation is pending
        # (defenseur humain). Only the allocation action is allowed through.
        if (
            self.game_state.get("pending_shoot_allocation") is not None
            and action.get("action") not in ("squad_shoot_allocate_model", "squad_shoot_declare_order")
        ):
            from engine.phase_handlers.shared_utils import manual_allocation_waiting_payload, SHOOT_CTX
            return True, manual_allocation_waiting_payload(self.game_state, SHOOT_CTX)

        # Idem combat (defenseur humain) : pendant l'allocation des pertes, seules les
        # actions d'allocation fight passent.
        if (
            self.game_state.get("pending_fight_allocation") is not None
            and action.get("action") not in ("squad_fight_manual_alloc", "squad_fight_declare_order", "squad_fight_cancel")
        ):
            from engine.phase_handlers.shared_utils import manual_allocation_waiting_payload
            from engine.phase_handlers.fight_handlers import FIGHT_CTX
            return True, manual_allocation_waiting_payload(self.game_state, FIGHT_CTX)

        current_phase = self.game_state["phase"]
        
        # Capture phase, turn et episode AVANT l'execution du handler : les traces de perf en aval
        # doivent nommer l'etat d'ou l'action est partie, pas celui ou la cascade l'a laissee.
        # (`pre_action_player` et la capture des positions vivaient ici pour la journalisation
        #  step.log du chemin PvP — partis avec elle, voir la pierre tombale plus bas.)
        pre_action_phase = self.game_state["phase"]
        pre_action_turn = self.game_state.get("turn", 1)
        pre_action_episode = self.game_state.get("episode_number", 1)  # CRITICAL: Capture episode BEFORE action execution
        # AI_TURN.md COMPLIANCE: Direct field access for semantic actions
        if "unitId" not in action:
            unit_id = None
        else:
            unit_id = action["unitId"]
        if unit_id:
            pre_unit = self._get_unit_by_id(str(unit_id))
            if not pre_unit:
                # Saisie invalide vs incoherence d etat. Un id que le moteur ne connait
                # NULLE PART vient du client : c est un refus metier, comme dans la
                # dizaine de handlers qui renvoient deja `unit_not_found`. Ce
                # pre-traitement n a aucune raison d etre plus dur que la logique de
                # jeu qu il precede.
                # A l inverse, un id present dans units_cache ou squad_models mais absent
                # de units est une vraie rupture de coherence interne : elle doit rester
                # bruyante.
                key = str(unit_id)
                known_elsewhere = (
                    key in require_key(self.game_state, "units_cache")
                    or key in require_key(self.game_state, "squad_models")
                )
                if not known_elsewhere:
                    return False, {"error": "unit_not_found", "unitId": key}
                raise KeyError(f"Unit {unit_id} missing from game_state['units']")
            # (la capture de position pre-action pour step.log est partie avec la journalisation
            #  du chemin PvP — voir la pierre tombale plus bas dans cette methode)

        # Activation-start choice trigger happens before the unit activation resolves.
        if action.get("action") == "activate_unit" and unit_id is not None:
            self._enqueue_rule_choice_candidates(
                trigger="activation_start",
                event_phase=current_phase,
                activation_unit_id=str(unit_id),
                event_player=int(require_key(self.game_state, "current_player")),
            )
            choice_prompt_result = self._emit_next_rule_choice_prompt_if_needed()
            if choice_prompt_result is not None:
                return True, choice_prompt_result

        # PERF: segment timings — enable with W40K_PERF_TIMING=1 or game_state["perf_timing"]
        from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

        _perf = perf_timing_enabled(self.game_state)
        _t_entry: Optional[float] = time.perf_counter() if _perf else None
        _t_after_handlers: Optional[float] = None
        _t_pre_cascade: Optional[float] = None
        _t_post_cascade: Optional[float] = None

        # Handle special "advance_phase" action when pool is empty
        if action.get("action") == "advance_phase":
            # Pool is empty - trigger phase transition
            from_phase = action.get("from", current_phase)
            if from_phase == "shoot":
                result = shooting_handlers.shooting_phase_end(self.game_state)
                self._shooting_phase_initialized = False
                if "phase_complete" not in result:
                    result["phase_complete"] = True
                if "reason" not in result:
                    result["reason"] = "pool_empty"
            elif from_phase == "fight":
                result = fight_handlers.fight_phase_end(self.game_state)
                if "phase_complete" not in result:
                    result["phase_complete"] = True
                if "reason" not in result:
                    result["reason"] = "pool_empty"
            elif from_phase == "deployment":
                result = {"phase_complete": True, "next_phase": "command", "reason": "pool_empty"}
            else:
                result = {"phase_complete": True, "reason": "pool_empty"}

                # Determine next phase based on current phase
                if from_phase == "move":
                    result["next_phase"] = "shoot"
                elif from_phase == "charge":
                    result["next_phase"] = "fight"
                elif from_phase == "command":
                    result["next_phase"] = "move"
                else:
                    result["next_phase"] = "move"

            # CRITICAL FIX: Don't return early - fall through to cascade loop
            # to actually execute the phase transition in game_state
            success = True
            # Fall through to cascade loop below

        # Route to phase handlers with detailed logging (only if not advance_phase)
        elif current_phase == "deployment":
            success, result = deployment_handlers.execute_deployment_action(self.game_state, action)
        elif current_phase == "command":
            success, result = self._process_command_phase(action)
        elif current_phase == "move":
            success, result = self._process_movement_phase(action)
        elif current_phase == "shoot":
            success, result = self._process_shooting_phase(action)
        elif current_phase == "charge":
            success, result = self._process_charge_phase(action)
        elif current_phase == "fight":
            success, result = self._process_fight_phase(action)
        else:
            return False, {"error": "invalid_phase", "phase": current_phase}

        if _perf:
            _t_after_handlers = time.perf_counter()

        # CRITICAL FIX: Log action BEFORE cascade to ensure action is logged even if phase completes
        # Log action with result (before cascade modifies it)
        # API « end phase » : un skip par unité avec manual_end_phase — éviter N× step_logger + reward (~très lent).
        # PIERRE TOMBALE — journalisation step.log du chemin PvP humain (supprimee le 2026-07-29).
        #
        # Il y avait ici 516 lignes gardees par
        #     `if (self.step_logger and self.step_logger.enabled) and not action.get("manual_end_phase")`
        # qui ecrivaient step.log pour chaque action : routage de `result["action"]`, log par-attaque
        # (tir/melee), vidage de `game_state["action_logs"]` en deux passes, et un filet de securite
        # pour le mouvement post-tir. Deux methodes n'existaient que pour elles et partent avec :
        # `_log_attack_results` et `_log_handler_action_log_entry`.
        #
        # POURQUOI MORT : cette garde ne pouvait plus jamais etre vraie. `_process_semantic_action`
        # n'a qu'un appelant, `execute_semantic_action`, lui-meme appele seulement par
        # `services/api_server.py` et `main.py` — le PvP humain, qui n'assigne jamais de StepLogger.
        # Symetriquement, les seuls a en assigner un (`ai/train.py`, `ai/replay_converter.py`,
        # `ai/bot_evaluation.py`) passent par `step()` et n'appellent jamais
        # `execute_semantic_action`. Les deux ensembles sont disjoints.
        # C'est le constat qui avait motive la rupture V11 T6-c (« step.log reduit a ses en-tetes
        # sur 474/475 episodes d'un run reel ») : le remplacant a ete ecrit, l'original n'avait
        # jamais ete retire.
        #
        # OU REGARDER MAINTENANT : `_flush_squad_action_logs_to_step_logger`, point d'accroche unique
        # du chemin vif (gym et bot PvE), appele depuis `step()`. Il draine la meme source de verite
        # (`game_state["action_logs"]`) au lieu de dupliquer des sites `log_action`.
                # Don't re-raise - let action execution continue
        
        if _perf:
            _t_pre_cascade = time.perf_counter()
            if _t_entry is not None and _t_after_handlers is not None and _t_pre_cascade is not None:
                append_perf_timing_line(
                    f"SEMANTIC_SEGMENTS episode={pre_action_episode} turn={pre_action_turn} pre_phase={pre_action_phase} "
                    f"action={action.get('action')!r} handlers_and_prerun_s={_t_after_handlers - _t_entry:.6f} "
                    f"step_logger_block_s={_t_pre_cascade - _t_after_handlers:.6f}"
                )

        # Auto-advance to next phase when current phase completes
        # Loop to handle cascading empty phases (e.g., charge -> fight -> move if all empty)
        # CRITICAL: This must happen AFTER logging to allow logging of actions before phase transitions
        max_cascade = 10  # Prevent infinite loops
        cascade_count = 0
        started_phases: List[str] = []
        while success and result.get("phase_complete") and result.get("next_phase") and cascade_count < max_cascade:
            next_phase = result["next_phase"]
            current_phase = self.game_state.get("phase", "unknown")
            cascade_count += 1

            # CRITICAL FIX: Only transition if next_phase is different from current phase
            # This prevents reinitializing a phase that is already active, which would
            # rebuild activation pools and re-add units that have already completed activation
            if next_phase == current_phase:
                from engine.game_utils import add_console_log, add_debug_log
                episode = self.game_state.get("episode_number", "?")
                turn = self.game_state.get("turn", "?")
                add_debug_log(self.game_state, f"[CASCADE LOOP FIX] E{episode} T{turn} Skipping phase transition: already in {next_phase} phase")
                # Break the cascade loop - we're already in the target phase
                break

            from engine.game_utils import add_console_log
            add_console_log(self.game_state, f"🔄 PHASE TRANSITION: {current_phase} -> {next_phase} (cascade #{cascade_count})")

            import time as _cascade_time
            _cascade_t0 = _cascade_time.perf_counter()
            # Initialize next phase using phase handlers
            phase_init_result = None
            if next_phase == "deployment":
                phase_init_result = deployment_handlers.deployment_phase_start(self.game_state)
            elif next_phase == "command":
                phase_init_result = self.start_command_phase()
                self._clear_turn_scoped_rule_choices()
            elif next_phase == "shoot":
                phase_init_result = shooting_handlers.shooting_phase_start(self.game_state)
                # Aligner avec _process_shooting_phase : évite un second shooting_phase_start (~1,5 s)
                # sur la première action tir après une transition cascade move → shoot.
                self._shooting_phase_initialized = True
            elif next_phase == "charge":
                phase_init_result = charge_handlers.charge_phase_start(self.game_state)
            elif next_phase == "fight":
                phase_init_result = fight_handlers.fight_phase_start(self.game_state)
            elif next_phase == "move":
                phase_init_result = movement_handlers.movement_phase_start(self.game_state)
            started_phases.append(next_phase)

            _cascade_dur = _cascade_time.perf_counter() - _cascade_t0
            _ep_c = int(require_key(self.game_state, "episode_number"))
            # Écriture synchrone dans debug.log désactivée par défaut (coûteuse à chaque transition en cascade).
            if os.environ.get("W40K_CASCADE_DEBUG_FILE", "").lower() in ("1", "true", "yes"):
                try:
                    _debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                    with open(_debug_path, "a", encoding="utf-8", errors="replace") as _f:
                        _f.write(
                            f"CASCADE_TIMING episode={_ep_c} cascade_num={cascade_count} "
                            f"from_phase={current_phase} to_phase={next_phase} duration_s={_cascade_dur:.6f}\n"
                        )
                except (OSError, IOError):
                    pass
            if _perf:
                append_perf_timing_line(
                    f"CASCADE_ITER episode={_ep_c} cascade_num={cascade_count} from_phase={current_phase} "
                    f"to_phase={next_phase} duration_s={_cascade_dur:.6f}"
                )

            add_console_log(self.game_state, f"🔄 PHASE NOW: {self.game_state.get('phase', 'UNKNOWN')}")

            # If phase_start returns phase_complete, cascade to next phase
            if phase_init_result and phase_init_result.get("phase_complete") and phase_init_result.get("next_phase"):
                # CRITICAL: Preserve combat action data before replacing result
                # When fight phase completes and transitions to next phase, we must preserve
                # the combat action data (action, unitId, all_attack_results) for logging
                preserved_combat_data = {}
                combat_keys = ["action", "unitId", "all_attack_results", "targetId", "attack_result", "target_died", "reason", "phase"]
                for key in combat_keys:
                    if key in result:
                        preserved_combat_data[key] = result[key]
                
                result = phase_init_result  # Update result for next iteration
                
                # CRITICAL: Restore preserved combat data for logging
                for key, value in preserved_combat_data.items():
                    if value is not None:  # Only restore non-None values
                        result[key] = value
            else:
                break  # Phase has eligible units, stop cascading
        
        if _perf:
            _t_post_cascade = time.perf_counter()
            if _t_pre_cascade is not None:
                append_perf_timing_line(
                    f"CASCADE_LOOP_TOTAL episode={pre_action_episode} turn={pre_action_turn} "
                    f"duration_s={_t_post_cascade - _t_pre_cascade:.6f} iterations={cascade_count}"
                )

        # Keep semantic-action flow aligned with step() terminal detection.
        self.game_state["game_over"] = self._check_game_over()
        if self.game_state["game_over"]:
            winner, win_method = self._determine_winner_with_method()
            self.game_state["winner"] = winner
            result["game_over"] = True
            result["winner"] = winner
            if win_method is not None:
                result["win_method"] = win_method

        # Queue timing-based choice prompts after successful state transitions/actions.
        if success:
            current_player_for_event = int(require_key(self.game_state, "current_player"))
            if result.get("action") == "deploy_unit" and result.get("unitId") is not None:
                deployed_unit_id = str(result["unitId"])
                deployed_unit = self._get_unit_by_id(deployed_unit_id)
                deployed_player = (
                    int(require_key(deployed_unit, "player"))
                    if deployed_unit is not None
                    else current_player_for_event
                )
                self._enqueue_rule_choice_candidates(
                    trigger="on_deploy",
                    activation_unit_id=deployed_unit_id,
                    event_player=deployed_player,
                )

            for started_phase in started_phases:
                if started_phase == "command":
                    self._enqueue_rule_choice_candidates(
                        trigger="turn_start",
                        event_phase=started_phase,
                        event_player=current_player_for_event,
                    )
                    self._enqueue_rule_choice_candidates(
                        trigger="player_turn_start",
                        event_phase=started_phase,
                        event_player=current_player_for_event,
                    )

                self._enqueue_rule_choice_candidates(
                    trigger="phase_start",
                    event_phase=started_phase,
                    event_player=current_player_for_event,
                )

            choice_prompt_result = self._emit_next_rule_choice_prompt_if_needed()
            if choice_prompt_result is not None:
                if _perf and _t_post_cascade is not None:
                    _t_tail = time.perf_counter()
                    append_perf_timing_line(
                        f"SEMANTIC_POST_CASCADE episode={pre_action_episode} turn={pre_action_turn} "
                        f"duration_s={_t_tail - _t_post_cascade:.6f} early_return=rule_choice_prompt"
                    )
                return True, choice_prompt_result

        if _perf and _t_post_cascade is not None:
            _t_tail = time.perf_counter()
            append_perf_timing_line(
                f"SEMANTIC_POST_CASCADE episode={pre_action_episode} turn={pre_action_turn} "
                f"duration_s={_t_tail - _t_post_cascade:.6f} early_return=none"
            )
        return success, result

    def _process_squad_manual_shoot(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Tir PvP humain par figurine (pipeline squad, shared_utils).

        Actions frontend :
          - squad_shoot_activate  : demarre l activation tir de l escouade (SHOOT_LEFT/pending).
          - squad_select_weapon   : change l arme pour toutes les figs de l escouade.
          - squad_shoot_assign    : assigne la cible d UNE figurine (modelId -> targetId).
          - squad_shoot_unassign  : retire la cible d une figurine.
          - squad_shoot_validate  : lock + resolution simultanee + end_activation.
        Le pipeline mono-fig legacy reste intact pour l IA/training.
        """
        from engine.phase_handlers.shared_utils import (
            squad_shooting_unit_activation_start,
            squad_declare_shoot_model,
            squad_undeclare_shoot_model,
            squad_model_valid_targets,
            squad_shoot_los_overview,
            squad_declare_shoot_weapon,
            squad_declare_shoot_weapon_qty,
            squad_shoot_weapon_qty_max,
            squad_undeclare_shoot_weapon,
            squad_undeclare_shoot_weapon_qty,
            squad_shoot_weapons_for_target,
            squad_shoot_menu_weapons,
            squad_shoot_eligible_models,
            squad_shoot_toggle_model_weapon,
            squad_shoot_models_status,
            squad_shoot_models_weapons,
            squad_weapon_valid_targets,
            squad_lock_shoot,
            build_manual_shoot_allocation,
            apply_manual_shoot_allocation,
            apply_manual_shoot_declare_order,
            clear_pending_shoot_intent,
            SHOOT_CTX,
        )
        from engine.phase_handlers.generic_handlers import end_activation
        from engine.phase_handlers.shooting_handlers import (
            build_unit_los_cache,
            build_cover_by_unit_id_for_valid_targets,
            build_hidden_too_far_by_unit_id,
            build_hidden_detection_info_by_unit_id,
        )

        name = action.get("action")
        squad_id = str(require_key(action, "unitId"))

        def _squad_available_weapons(unit: Dict[str, Any]) -> List[Dict[str, Any]]:
            """available_weapons pour le menu : union des armes par-figurine, avec `can_use`
            calcule PAR-FIGURINE (≥1 fig peut tirer sur ≥1 ennemi) + exclusion Close-quarters/non-Close-quarters
            au niveau unite (10.06). Cf. squad_shoot_menu_weapons."""
            return squad_shoot_menu_weapons(self.game_state, str(unit["id"]))

        def _squad_cover_by_unit_id(valid_targets: List[str]) -> Dict[str, bool]:
            """Cover geometrique par cible valide (brique LoS partagee, single source of truth).

            IGNORES_COVER est applique cote arme par le frontend ; ici le cover est purement
            geometrique (cible en terrain / partiellement visible), identique au tir mono-fig.
            """
            build_unit_los_cache(self.game_state, squad_id)
            unit_obj = get_unit_by_id(squad_id, self.game_state)
            assert unit_obj is not None, f"unit {squad_id} not found in game_state"
            return build_cover_by_unit_id_for_valid_targets(self.game_state, unit_obj, valid_targets)

        def _squad_hidden_too_far() -> Dict[str, bool]:
            """Ennemis cachés-trop-loin (œil rouge) relativement au squad actif. Même brique LoS
            partagée que ``_squad_cover_by_unit_id`` (build_unit_los_cache idempotent)."""
            build_unit_los_cache(self.game_state, squad_id)
            unit_obj = get_unit_by_id(squad_id, self.game_state)
            assert unit_obj is not None, f"unit {squad_id} not found in game_state"
            return build_hidden_too_far_by_unit_id(self.game_state, unit_obj)

        def _squad_hidden_detection_info() -> Dict[str, Dict[str, Any]]:
            """Detection range effective (15" / 12" GtG) + too_far par ennemi caché, pour le badge
            numérique frontend. Même brique LoS partagée (build_unit_los_cache idempotent)."""
            build_unit_los_cache(self.game_state, squad_id)
            unit_obj = get_unit_by_id(squad_id, self.game_state)
            assert unit_obj is not None, f"unit {squad_id} not found in game_state"
            return build_hidden_detection_info_by_unit_id(self.game_state, unit_obj)

        if name == "squad_shoot_activate":
            # Cancel implicite de l activation en cours. active_shooting_unit est un
            # singleton : des que le joueur active une autre escouade (ou reactive la
            # meme), la precedente devient inaccessible. Le front n envoie PAS de
            # squad_shoot_cancel avant d activer (useEngineAPI.handleStartSquadModelShoot),
            # ce qui laissait son pending orphelin et faisait lever
            # assert_no_pending_shoot_intent au retour sur elle. On libere donc ici
            # exactement ce que squad_shoot_cancel aurait libere : ses declarations
            # d armes sont perdues, comme elles l etaient deja de fait.
            previous_active = self.game_state.get("active_shooting_unit")
            if previous_active is not None:
                clear_pending_shoot_intent(self.game_state, str(previous_active))
                del self.game_state["active_shooting_unit"]
            squad_shooting_unit_activation_start(self.game_state, squad_id)
            self.game_state["active_shooting_unit"] = squad_id
            unit = get_unit_by_id(squad_id, self.game_state)
            available_weapons = _squad_available_weapons(unit) if unit is not None else []
            return True, {"action": name, "unitId": squad_id, "activation_started": True, "available_weapons": available_weapons}

        if name == "squad_select_weapon":
            weapon_index_raw = action.get("weaponIndex")
            if weapon_index_raw is None:
                return False, {"error": "missing_weapon_index"}
            try:
                weapon_index = int(weapon_index_raw)
            except (TypeError, ValueError):
                return False, {"error": "invalid_weapon_index_type"}
            unit = get_unit_by_id(squad_id, self.game_state)
            if unit is None:
                return False, {"error": "unit_not_found", "unitId": squad_id}
            rng_weapons = require_key(unit, "RNG_WEAPONS")
            if weapon_index < 0 or weapon_index >= len(rng_weapons):
                return False, {"error": "invalid_weapon_index", "weaponIndex": weapon_index}
            unit["selectedRngWeaponIndex"] = weapon_index
            unit["_manual_weapon_selected"] = True
            unit["manualWeaponSelected"] = True
            # Propage le choix d arme a chaque figurine du squad.
            models_cache = require_key(self.game_state, "models_cache")
            squad_models_map = require_key(self.game_state, "squad_models")
            for mid in squad_models_map.get(squad_id, []):  # get allowed
                m = models_cache.get(mid)
                if m is not None:
                    model_weapons = require_key(m, "RNG_WEAPONS")
                    if weapon_index < len(model_weapons):
                        m["selectedRngWeaponIndex"] = weapon_index
            available_weapons = _squad_available_weapons(unit)
            # Cibles valides de l arme choisie (alimente le HP blink frontend pour l arme active).
            valid_targets = squad_weapon_valid_targets(self.game_state, squad_id, weapon_index)
            return True, {
                "action": name, "unitId": squad_id, "weaponIndex": weapon_index,
                "available_weapons": available_weapons, "valid_targets": valid_targets,
                "cover_by_unit_id": _squad_cover_by_unit_id(valid_targets),
                "hidden_too_far_by_unit_id": _squad_hidden_too_far(),
                "hidden_detection_info_by_unit_id": _squad_hidden_detection_info(),
            }

        if name == "squad_shoot_select_model":
            # Read-only : cibles valides de la fig (alimente le HP blink frontend).
            model_id = str(require_key(action, "modelId"))
            valid_targets = squad_model_valid_targets(self.game_state, squad_id, model_id)
            return True, {
                "action": name, "unitId": squad_id, "modelId": model_id,
                "valid_targets": valid_targets,
                "cover_by_unit_id": _squad_cover_by_unit_id(valid_targets),
                "hidden_too_far_by_unit_id": _squad_hidden_too_far(),
                "hidden_detection_info_by_unit_id": _squad_hidden_detection_info(),
            }  # get allowed

        if name == "squad_shoot_los_overview":
            # Read-only : cibles tirables de TOUTE l escouade + nb de figs qui voient
            # chaque ennemi (double-click frontend : blink escouade + compteur N/M).
            overview = squad_shoot_los_overview(self.game_state, squad_id)
            return True, {
                "action": name, "unitId": squad_id,
                "valid_targets": overview["valid_targets"],
                "count_by_unit_id": overview["count_by_unit_id"],
                "squad_alive_count": overview["squad_alive_count"],
                "squad_free_count": overview["squad_free_count"],
                "cover_by_unit_id": _squad_cover_by_unit_id(overview["valid_targets"]),
                "hidden_too_far_by_unit_id": _squad_hidden_too_far(),
                "hidden_detection_info_by_unit_id": _squad_hidden_detection_info(),
            }  # get allowed

        if name == "squad_shoot_assign":
            model_id = str(require_key(action, "modelId"))
            target_id = str(require_key(action, "targetId"))
            try:
                intent = squad_declare_shoot_model(self.game_state, squad_id, model_id, target_id)
            except ValueError as e:
                return False, {"error": "cannot_shoot", "reason": str(e)}
            return True, {
                "action": name, "unitId": squad_id, "intent": intent,
                "declarations": list(self.game_state["pending_squad_shoot_intents"].get(squad_id, [])),  # get allowed
            }

        if name == "squad_shoot_unassign":
            model_id = str(require_key(action, "modelId"))
            removed = squad_undeclare_shoot_model(self.game_state, squad_id, model_id)
            return True, {
                "action": name, "unitId": squad_id, "removed": removed,
                "declarations": list(self.game_state["pending_squad_shoot_intents"].get(squad_id, [])),  # get allowed
            }

        if name == "squad_shoot_weapon_targets":
            # Read-only : cibles valides de l arme (alimente le HP blink frontend).
            weapon_index_raw = action.get("weaponIndex")
            if weapon_index_raw is None:
                return False, {"error": "missing_weapon_index"}
            try:
                weapon_index = int(weapon_index_raw)
            except (TypeError, ValueError):
                return False, {"error": "invalid_weapon_index_type"}
            valid_targets = squad_weapon_valid_targets(self.game_state, squad_id, weapon_index)
            return True, {
                "action": name, "unitId": squad_id, "weaponIndex": weapon_index,
                "valid_targets": valid_targets,
                "cover_by_unit_id": _squad_cover_by_unit_id(valid_targets),
                "hidden_too_far_by_unit_id": _squad_hidden_too_far(),
                "hidden_detection_info_by_unit_id": _squad_hidden_detection_info(),
            }

        if name == "squad_shoot_assign_weapon":
            weapon_index_raw = action.get("weaponIndex")
            if weapon_index_raw is None:
                return False, {"error": "missing_weapon_index"}
            try:
                weapon_index = int(weapon_index_raw)
            except (TypeError, ValueError):
                return False, {"error": "invalid_weapon_index_type"}
            target_id = str(require_key(action, "targetId"))
            try:
                created = squad_declare_shoot_weapon(self.game_state, squad_id, weapon_index, target_id)
            except ValueError as e:
                return False, {"error": "cannot_shoot", "reason": str(e)}
            return True, {
                "action": name, "unitId": squad_id, "weaponIndex": weapon_index,
                "target_unit_id": target_id, "created": created,
                "declarations": list(self.game_state["pending_squad_shoot_intents"].get(squad_id, [])),  # get allowed
            }

        if name == "squad_shoot_assign_weapon_qty":
            # Attribution QUANTIFIEE par identite d arme (Cyclone Frag/Krak, escouades
            # heterogenes) : `count` figurines portant `weaponCode` tirent sur la cible.
            weapon_code = action.get("weaponCode")
            count_raw = action.get("count")
            if weapon_code is None or count_raw is None:
                return False, {"error": "missing_weaponCode_or_count"}
            try:
                count = int(count_raw)
            except (TypeError, ValueError):
                return False, {"error": "invalid_count_type"}
            target_id = str(require_key(action, "targetId"))
            model_id = action.get("modelId")  # optionnel : attribution par-fig
            try:
                created = squad_declare_shoot_weapon_qty(
                    self.game_state, squad_id, str(weapon_code), count, target_id,
                    None if model_id is None else str(model_id),
                )
            except ValueError as e:
                return False, {"error": "cannot_shoot", "reason": str(e)}
            return True, {
                "action": name, "unitId": squad_id, "weaponCode": str(weapon_code),
                "count": count, "target_unit_id": target_id, "created": created,
                "declarations": list(self.game_state["pending_squad_shoot_intents"].get(squad_id, [])),  # get allowed
            }

        if name == "squad_shoot_menu_weapons":
            # Read-only : profils du menu avec can_use par-fig + exclusion Close-quarters/non-Close-quarters.
            weapons = squad_shoot_menu_weapons(self.game_state, squad_id)
            return True, {"action": name, "unitId": squad_id, "weapons": weapons}

        if name == "squad_shoot_weapons_for_target":
            # Read-only : menu cible-d abord — armes pouvant viser la cible + (m, x).
            target_id = action.get("targetId")
            if target_id is None:
                return False, {"error": "missing_targetId"}
            model_id = action.get("modelId")  # optionnel : menu par-fig (m/x scopes)
            weapons = squad_shoot_weapons_for_target(
                self.game_state, squad_id, str(target_id),
                None if model_id is None else str(model_id),
            )
            return True, {
                "action": name, "unitId": squad_id, "targetId": str(target_id),
                "weapons": weapons,
            }

        if name == "squad_shoot_models_weapons":
            # Read-only : armes par figurine (indépendant de la cible) — encart jaune au clic-fig.
            models = squad_shoot_models_weapons(self.game_state, squad_id)
            return True, {"action": name, "unitId": squad_id, "models": models}

        if name == "squad_shoot_models_status":
            # Read-only : voiles vert/gris — état de chaque fig de l'unité vis-à-vis de la cible.
            target_id = action.get("targetId")
            if target_id is None:
                return False, {"error": "missing_targetId"}
            models = squad_shoot_models_status(self.game_state, squad_id, str(target_id))
            return True, {
                "action": name, "unitId": squad_id, "targetId": str(target_id), "models": models,
            }

        if name == "squad_shoot_eligible_models":
            # Read-only : voile vert — figs pouvant tirer weaponCode sur la cible.
            weapon_code = action.get("weaponCode")
            target_id = action.get("targetId")
            if weapon_code is None or target_id is None:
                return False, {"error": "missing_weaponCode_or_targetId"}
            models = squad_shoot_eligible_models(self.game_state, squad_id, str(weapon_code), str(target_id))
            return True, {
                "action": name, "unitId": squad_id, "weaponCode": str(weapon_code),
                "targetId": str(target_id), "models": models,
            }

        if name == "squad_shoot_toggle_model_weapon":
            # Clic sur fig verte : toggle l attribution de cette fig pour (weaponCode, cible).
            model_id = action.get("modelId")
            weapon_code = action.get("weaponCode")
            target_id = action.get("targetId")
            if model_id is None or weapon_code is None or target_id is None:
                return False, {"error": "missing_modelId_weaponCode_or_targetId"}
            try:
                toggled = squad_shoot_toggle_model_weapon(
                    self.game_state, squad_id, str(model_id), str(weapon_code), str(target_id)
                )
            except ValueError as e:
                return False, {"error": "cannot_shoot", "reason": str(e)}
            return True, {
                "action": name, "unitId": squad_id, "modelId": str(model_id),
                "weaponCode": str(weapon_code), "targetId": str(target_id), "toggled": toggled,
                "declarations": list(self.game_state["pending_squad_shoot_intents"].get(squad_id, [])),  # get allowed
            }

        if name == "squad_shoot_weapon_qty_max":
            # Read-only : borne du champ count (figs pouvant tirer weaponCode sur la cible).
            weapon_code = action.get("weaponCode")
            target_id = action.get("targetId")
            if weapon_code is None or target_id is None:
                return False, {"error": "missing_weaponCode_or_targetId"}
            model_id = action.get("modelId")  # optionnel : borne par-fig
            qty_max = squad_shoot_weapon_qty_max(
                self.game_state, squad_id, str(weapon_code), str(target_id),
                None if model_id is None else str(model_id),
            )
            return True, {
                "action": name, "unitId": squad_id, "weaponCode": str(weapon_code),
                "targetId": str(target_id), "qty_max": qty_max,
            }

        if name == "squad_shoot_unassign_weapon_qty":
            weapon_code = action.get("weaponCode")
            target_id = action.get("targetId")
            if weapon_code is None or target_id is None:
                return False, {"error": "missing_weaponCode_or_targetId"}
            model_id = action.get("modelId")  # optionnel : retrait par-fig
            removed = squad_undeclare_shoot_weapon_qty(
                self.game_state, squad_id, str(weapon_code), str(target_id),
                None if model_id is None else str(model_id),
            )
            return True, {
                "action": name, "unitId": squad_id, "weaponCode": str(weapon_code),
                "targetId": str(target_id), "removed": removed,
                "declarations": list(self.game_state["pending_squad_shoot_intents"].get(squad_id, [])),  # get allowed
            }

        if name == "squad_shoot_unassign_weapon":
            weapon_index_raw = action.get("weaponIndex")
            if weapon_index_raw is None:
                return False, {"error": "missing_weapon_index"}
            try:
                weapon_index = int(weapon_index_raw)
            except (TypeError, ValueError):
                return False, {"error": "invalid_weapon_index_type"}
            removed = squad_undeclare_shoot_weapon(self.game_state, squad_id, weapon_index)
            return True, {
                "action": name, "unitId": squad_id, "weaponIndex": weapon_index, "removed": removed,
                "declarations": list(self.game_state["pending_squad_shoot_intents"].get(squad_id, [])),  # get allowed
            }

        if name == "squad_shoot_cancel":
            # Annulation : nettoie le pending + libere l unite active SANS la retirer
            # du pool (elle pourra etre re-selectionnee). Pas de end_activation.
            clear_pending_shoot_intent(self.game_state, squad_id)
            if self.game_state.get("active_shooting_unit") == squad_id:
                del self.game_state["active_shooting_unit"]
            return True, {"action": name, "unitId": squad_id, "cancelled": True}

        if name == "squad_shoot_validate":
            squad_lock_shoot(self.game_state, squad_id)
            unit = get_unit_by_id(squad_id, self.game_state)
            if unit is None:
                raise KeyError(f"Squad {squad_id} introuvable pour resolution tir manuel")
            attacker_player = int(require_key(unit, "player"))
            defender_player = 2 if attacker_player == 1 else 1
            if self._is_player_human(defender_player):
                # Allocation manuelle des pertes par le defenseur (regle 05.04) :
                # jets resolus, application differee, end_activation reporte a la fin.
                alloc_result = build_manual_shoot_allocation(self.game_state, squad_id)
                if alloc_result.get("waiting_for_player"):
                    return True, alloc_result
                return True, self._finish_manual_shoot_after_allocation(squad_id, alloc_result)
            # Defenseur IA : convergence §8 -> moteur d allocation par-figurine
            # (groupes 05.03/05.04, T bodyguard 19.02, save par-fig). auto_decider headless.
            _shoot_alloc = build_manual_shoot_allocation(self.game_state, squad_id)
            if not _shoot_alloc.get("done"):
                raise RuntimeError(
                    f"squad_shoot_validate: allocation tir non terminee en auto pour squad "
                    f"{squad_id} (defenseur non-IA ?) — action={_shoot_alloc.get('action')}"
                )
            shoot_result = _shoot_alloc["shoot_result"]
            end_result = end_activation(self.game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 0)
            if self.game_state.get("active_shooting_unit") == squad_id:
                del self.game_state["active_shooting_unit"]
            return True, {
                **end_result, "action": "squad_shoot", "unitId": squad_id,
                "shoot_result": shoot_result,
            }

        if name == "squad_shoot_allocate_model":
            chosen = action.get("modelId")
            if chosen is None:
                return False, {"error": "missing_model_id"}
            alloc_result = apply_manual_shoot_allocation(self.game_state, str(chosen), SHOOT_CTX)
            if alloc_result.get("waiting_for_player"):
                return True, alloc_result
            return True, self._finish_manual_shoot_after_allocation(squad_id, alloc_result)

        if name == "squad_shoot_declare_order":
            order = action.get("order")
            if order is None:
                return False, {"error": "missing_order"}
            alloc_result = apply_manual_shoot_declare_order(self.game_state, list(order), SHOOT_CTX)
            if alloc_result.get("waiting_for_player"):
                return True, alloc_result
            return True, self._finish_manual_shoot_after_allocation(squad_id, alloc_result)

        raise ValueError(f"Unknown squad manual shoot action: {name!r}")

    def _finish_manual_shoot_after_allocation(
        self, squad_id: str, alloc_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """end_activation differe : appele quand l allocation manuelle est terminee (done)."""
        from engine.phase_handlers.generic_handlers import end_activation
        unit = get_unit_by_id(squad_id, self.game_state)
        if unit is None:
            raise KeyError(f"Squad {squad_id} introuvable pour end_activation apres allocation")
        end_result = end_activation(self.game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 0)
        if self.game_state.get("active_shooting_unit") == squad_id:
            del self.game_state["active_shooting_unit"]
        return {
            **end_result, "action": "squad_shoot", "unitId": squad_id,
            "shoot_result": alloc_result.get("shoot_result"),
        }


    # ============================================================================
    # SQUAD PIPELINE DISPATCH
    # ============================================================================

    # V11 T6 — mapping type d'action_log moteur -> action_type du formateur du StepLogger
    # (ai/step_logger.py::_format_replay_style_message). Les noms coincident deja presque tous ;
    # seuls "hazard"->"hazardous" et le move (dont la nuance vit dans move_type) different.
    # Un type ABSENT de cette table est ignore volontairement : il n'a pas de formateur
    # (death, battle_shock, roll_info, reactive_move_declined).
    # Journalise mais NE CONSOMME PAS de step gym : le move reactif est DECLENCHE par le
    # deplacement adverse, pas choisi par l'agent — l'entete de step.log liste les actions qui
    # incrementent (move, shoot, charge, combat, wait). L'y compter decalerait `total_actions`
    # et le compte de steps de tous les episodes, sans qu'aucune decision supplementaire n'ait
    # ete prise.
    _STEP_LOG_NON_INCREMENTING_TYPES: frozenset = frozenset({"reactive_move"})

    _STEP_LOG_TYPE_MAP: Dict[str, str] = {
        "shoot": "shoot",
        "combat": "combat",
        "hazard": "hazardous",
        "charge": "charge",
        "charge_fail": "charge_fail",
        "charge_impact": "charge_impact",
        "pile_in": "pile_in",
        "consolidation": "consolidation",
        "wait": "wait",
        # Le move REACTIF (24.xx, capacite `reactive_move`) est un vrai deplacement, soumis aux
        # memes contraintes que les autres (murs, figurines, budget) — il doit donc etre
        # journalise pour etre verifiable. Son formateur existait deja dans `step_logger` ; seul
        # ce mapping manquait, si bien que la ligne n'atteignait jamais step.log et que TOUS les
        # controles reactifs de l'analyzer etaient du code mort.
        "reactive_move": "reactive_move",
        # ⚠️ `rule_choice` N'EST PAS ici : `_record_rule_choice_action_log` écrit DÉJÀ sa ligne
        # directement dans step.log, au moment où le choix est appliqué. Le laisser dans ce
        # mapping le journalisait une SECONDE fois — et cette seconde tentative échouait toujours,
        # en silence (`Rule_choice action missing required selected_rule_name`) : l'action_log
        # moteur porte la clé `selectedRuleName`, que `_build_step_log_details` ne lit pas.
        # Le défaut était latent tant que les choix étaient appliqués hors de la fenêtre de flush
        # (cascade de `_build_observation`) ; le mécanisme de décision (§9.3 P2) les fait passer
        # par un step, donc par le flush, et le rendait systématique. Mesuré : 16 erreurs avalées
        # pour 16 choix. Corriger le mapping aurait produit un DOUBLON de chaque ligne.
        "move_after_shooting": "move_after_shooting",
        "deploy_unit": "deploy_unit",
    }

    # Le moteur emet un seul type "move" ; la nuance vit dans move_type (cf. move_type_map du
    # handler squad_*_move). Mapping exhaustif : un move_type hors de ces 3 valeurs est un bug.
    _STEP_LOG_MOVE_TYPE_MAP: Dict[str, str] = {
        "normal": "move",
        "advance": "advance",
        "fall_back": "flee",
    }

    # V11 T6 — traduction d'un shot_record moteur (shared_utils ~L6045 / fight_handlers ~L5727,
    # structure IDENTIQUE tir et combat) vers les champs du formateur du StepLogger.
    # camelCase moteur -> snake_case formateur. Les 11 champs sont EXIGES (presence de la cle)
    # par le formateur, meme sur un MISS : il ne rend `Wound` que si hit_result == "HIT" et
    # `Save`/`Dmg` que plus loin dans la sequence — une valeur None sur un MISS est donc
    # correcte et jamais affichee.
    _SHOT_RECORD_FIELD_MAP: Dict[str, str] = {
        "attackRoll": "hit_roll",
        "hitResult": "hit_result",
        "hitTarget": "hit_target",
        "strengthRoll": "wound_roll",
        "strengthResult": "wound_result",
        "woundTarget": "wound_target",
        "saveRoll": "save_roll",
        "saveTarget": "save_target",
        "damageDealt": "damage_dealt",
        # Regles d armes : sans ces cles, les branches d affichage du formateur du StepLogger
        # sont INATTEIGNABLES, et les controles de conformite de `ai/analyzer_phases/
        # shoot_handler.py` (qui les cherchent par regex dans la ligne) restent muets — tout
        # comme le replay (`replayParser.ts`). Chaine verrouillee de bout en bout par
        # tests/unit/ai/test_step_log_weapon_rule_tokens.py. Cf. V11 §0hist.38.
        "saveSkipped": "save_skipped",
        "saveSkipReason": "save_skip_reason",
        # Nom de l abilite d unite qui a ouvert la relance de blessure, quand elle a
        # EFFECTIVEMENT eu lieu (le socle trace la cause, `_manual_roll_intent` la nomme).
        "woundAbility": "wound_ability_display_name",
        # Regle d ARME ayant ouvert la relance de blessure ([TWIN-LINKED] 24.38). Sans cette
        # entree, le champ n atteint que le Game Log PvP : step.log, le replay et l analyzer
        # voient un de relance sans cause, alors qu ils nomment celle des capacites d unite.
        "woundRerollRule": "wound_reroll_rule_name",
        # JUMEAU cote TOUCHE (chantier 03) : `hit_1` (capacite de datasheet) ou `hit_any_fail`
        # (Oath of Moment). Sans cette entree, le champ n atteint jamais step.log et l analyzer
        # ne peut pas distinguer une relance POSSIBLE d une relance EFFECTUEE.
        "hitAbility": "hit_ability_display_name",
        # MODIFICATEUR de blessure (+1 d Oath), pas une relance : sans cette entree le seuil
        # ameliore atteint step.log sans sa cause, alors que la relance de touche y est nommee.
        "woundBonusAbility": "wound_bonus_ability_display_name",
        # Jets AVANT relance. Sans ces trois entrees, step.log rend `Hit 3(3+) [OATH OF MOMENT]`,
        # indiscernable d une touche directe : le nom de la capacite dit que la relance ETAIT
        # POSSIBLE, le de d origine est le seul a dire qu elle a EU LIEU (et ce qu elle a change).
        "attackRollInitial": "hit_roll_initial",
        "strengthRollInitial": "wound_roll_initial",
        "saveRollInitial": "save_roll_initial",
        # [SUSTAINED HITS X] 24.36 : touche ADDITIONNELLE nee d une touche critique — pas une
        # attaque, donc aucun jet de touche (`attackRoll=None`, rendu « Hit None(3+) »). Sans
        # ce marqueur, l analyzer ne peut ni la distinguer d une ligne malformee, ni la sortir
        # du plafond de tirs (`shoot_over_rng_nb`), ni attester l usage de la regle en 1.8 :
        # 12 lignes pour 9 attaques remontaient « shots over RNG_NB » pendant que la meme
        # regle etait affichee « NOT USED ». Miroir exact de [RAPID FIRE] ci-dessus.
        "sustainedHit": "sustained_hit",
        # WAAAGH! (melee) : +1 en Force ET en Attaques. Sans cette entree, le drapeau pose par le
        # roller de melee n atteint jamais step.log, et le plafond d attaques recalcule par
        # l analyzer est inferieur d un cran a celui que le moteur a reellement applique.
        "waaaghMelee": "waaagh_melee",
    }

    def _models_segment_for_unit(self, unit_id: Any, label: str = "MODELS") -> str:
        """Segment ``[MODELS: <mid>@(c,r) ...]`` des positions per-figurine COURANTES de l'unite.

        Source de verite : ``units_cache[unit_id]['occupied_hexes_by_model']`` (resynchronise
        par ``commit_move`` apres chaque deplacement). Permet a l'analyzer de raisonner par
        socle au lieu de l'ancre. Chaine vide si l'unite n'a pas d'entree cache exploitable
        (id absent, unite retiree) : le per-figurine est une INFO de log, jamais un chemin de
        regle — il ne doit en aucun cas faire crasher le flux de journalisation.
        """
        if unit_id is None:
            return ""
        from engine.action_log_utils import format_models_segment
        units_cache = self.game_state.get("units_cache")  # get allowed
        if not isinstance(units_cache, dict):
            return ""
        entry = units_cache.get(unit_id)  # get allowed
        if not isinstance(entry, dict):
            return ""
        by_model = entry.get("occupied_hexes_by_model")  # get allowed
        if not isinstance(by_model, dict) or not by_model:
            return ""
        # Hauteur de plancher par figurine (pouces) : elle voyage AVEC la position, sinon
        # l'analyzer ne peut pas appliquer le gate vertical §03.04 et reste 2D là où le moteur
        # est 3D. Les deux cartes sont écrites ENSEMBLE par les deux seuls écrivains du cache
        # (`_recompute_squad_occupied_hexes`, `update_units_cache_position`) : une figurine
        # présente dans l'une et absente de l'autre est une corruption de cache.
        #
        # `require_key` plutôt qu'un `return ""` : lâcher le segment ferait disparaître la couche
        # per-figurine ENTIÈRE (les POSITIONS, pas seulement les altitudes) — l'analyzer
        # retomberait en silence sur l'ancre d'escouade, exactement le raisonnement par-ancre que
        # cette couche existe pour remplacer. Un journal muet vaut moins qu'une erreur visible.
        floors = require_key(entry, "floor_height_by_model")
        return format_models_segment(
            (
                (mid, pos[0], pos[1], require_key(floors, mid))
                for mid, pos in by_model.items()
            ),
            label=label,
        )

    def _model_types_segment_for_unit(self, unit_id: Any, squad_unit_type: str) -> str:
        """Segment ``[MODEL_TYPES: <mid>=<UnitType> ...]`` — la DATASHEET de chaque figurine.

        Une escouade n'est pas homogène : la règle 19 (Attached units) y replie un personnage
        COMME figurine, et le roster y place sergents et armes spéciales. Le type d'ESCOUADE ne
        décrit donc pas chaque socle, et tout plafond calculé par figurine à partir de lui est
        faux — c'est ce qui produisait les faux « Attacks over CC_NB » de l'analyzer (voir le
        commentaire du site d'écriture dans `ai/step_logger.py`).

        Écrit UNE fois, dans l'entête d'épisode : la composition ne change pas en cours de partie
        (une figurine meurt, elle ne change pas de datasheet). Les figurines sans type propre
        portent celui de l'escouade — explicitement, plutôt que par une règle implicite que
        chaque lecteur devrait redécouvrir.

        ⚠️ CLÉ `unitType`, camelCase — c'est celle que `models_cache` écrit
        (`shared_utils._build_models_cache_entry`, « "unitType": spec.get("unit_type") or … » :
        le SPEC de scénario est en snake_case, le CACHE en camelCase). Ce site lisait
        `unit_type` : la clé n'existait pas, le repli sur le type d'escouade s'appliquait donc à
        TOUTES les figurines, et le segment rendait exactement l'information qu'il existe pour
        remplacer. Mesuré sur le journal du 2026-08-09 : `5#0..5#6=Intercessor` sur une escouade
        dont deux socles frappent au Master-crafted Power Weapon et au Power Fist — deux armes
        qu'aucun Intercessor ne porte. Le plafond « par figurine » de l'analyzer restait donc un
        plafond par escouade sous un autre nom. Tous les autres lecteurs de `models_cache` lisent
        déjà `unitType` ; celui-ci était le seul à diverger.
        """
        if unit_id is None:
            return ""
        squad_models = self.game_state.get("squad_models")  # get allowed
        models_cache = self.game_state.get("models_cache")  # get allowed
        if not isinstance(squad_models, dict) or not isinstance(models_cache, dict):
            return ""
        mids = squad_models.get(str(unit_id))  # get allowed
        if not mids:
            return ""
        parts = []
        for mid in mids:
            model = models_cache.get(str(mid))  # get allowed : figurine déjà retirée
            if model is None:
                continue
            parts.append(f"{mid}={model.get('unitType') or squad_unit_type}")  # get allowed
        if not parts:
            return ""
        return "[MODEL_TYPES: " + " ".join(parts) + "]"

    def _build_shot_details(
        self, raw_log: Dict[str, Any], shot: Dict[str, Any], pre_action_turn: Any,
        fight_state: Optional[Dict[str, Any]], include_target_models: bool = False,
    ) -> Dict[str, Any]:
        """Details d'UN jet (tir ou combat) pour le formateur du StepLogger.

        Le formateur travaille par ATTAQUE (Hit/Wound/Save/Dmg d'un jet), alors que le moteur
        agrege les jets d'un groupe (arme, cible) dans `shootDetails`. On emet donc une ligne
        par jet — c'est la granularite qu'attend aussi l'analyzer (`Dmg:(\\d+)HP` par attaque).
        """
        details: Dict[str, Any] = {
            "current_turn": raw_log.get("turn", pre_action_turn),  # get allowed
            "reward": 0.0,
            "target_id": raw_log.get("targetId"),  # get allowed
        }
        unit_id = raw_log.get("shooterId")  # get allowed
        s_col, s_row = raw_log.get("shooterCol"), raw_log.get("shooterRow")  # get allowed
        if s_col is not None and s_row is not None:
            details["unit_with_coords"] = f"{unit_id}({s_col},{s_row})"
        t_col, t_row = raw_log.get("targetCol"), raw_log.get("targetRow")  # get allowed
        if t_col is not None and t_row is not None:
            details["target_coords"] = (t_col, t_row)
        weapon_name = raw_log.get("weaponName")  # get allowed
        if weapon_name:
            details["weapon_name"] = weapon_name
        # [HEAVY] 24.16 : proprietes de l ACTIVATION (constantes sur le groupe), pas du jet —
        # elles viennent donc du log de groupe, pas de `shot`. Le formateur en tire
        # `Hit 4(4+->3+) [HEAVY]`, que l analyzer et le replay cherchent par regex.
        # Absentes en melee (ni couvert ni HEAVY) : etat metier valide.
        if raw_log.get("heavyApplied"):  # get allowed
            details["hit_rule_modifier"] = "HEAVY"
            details["hit_target_base"] = raw_log.get("bsBase")  # get allowed
        # Benefit of Cover 13.08 : dans CE moteur le couvert degrade le SEUIL DE TOUCHE
        # (`_cover_worsened_bs`), pas la sauvegarde — le token va donc du cote de la touche,
        # comme [HEAVY]. Le formateur du StepLogger portait l ancien modele (couvert sur la
        # sauvegarde, `save_cover_applied`/`save_target_base`), que plus rien n alimentait.
        elif raw_log.get("cover"):  # get allowed
            details["hit_rule_modifier"] = "COVER"
            details["hit_target_base"] = raw_log.get("bsBase")  # get allowed
        # [RAPID FIRE] 24.30 : la regle grossit le POOL d attaques du groupe, elle n est pas
        # une propriete d un jet — le marqueur est donc porte par toutes les lignes du groupe.
        # C est ce qui leve le plafond de tirs cote analyzer (NB de base -> NB + X).
        _rapid_fire = raw_log.get("rapidFireApplied")  # get allowed
        if _rapid_fire:
            details["rapid_fire_bonus_shot"] = True
            details["rapid_fire_rule_value"] = int(_rapid_fire)
        # Les 11 champs par-jet : la cle DOIT exister (le formateur teste `not in details`).
        for src, dst in self._SHOT_RECORD_FIELD_MAP.items():
            details[dst] = shot.get(src)  # get allowed
        # saveSuccess (bool moteur) -> save_result (le formateur teste `== "FAIL"` pour afficher
        # les degats). Absent tant que l'allocation n'a pas complete le record.
        save_success = shot.get("saveSuccess")  # get allowed
        details["save_result"] = None if save_success is None else ("SAVE" if save_success else "FAIL")
        if fight_state is not None:
            details.update(fight_state)
        details["models_segment"] = self._models_segment_for_unit(unit_id)
        # Figs ayant EFFECTIVEMENT tire (sous-ensemble de [MODELS:]) : porte par le log de groupe
        # (_emit_squad_shoot_log -> "shooterModels"). Absent sur les actions sans resolution par-fig.
        shooter_models = raw_log.get("shooterModels")  # get allowed
        if shooter_models:
            from engine.action_log_utils import format_shooter_models_segment
            details["shooter_models_segment"] = format_shooter_models_segment(shooter_models)
        # Survivants per-figurine de la CIBLE, post-pertes (le flush intervient apres resolution
        # complete de l'action -> figurines mortes deja retirees du cache). Le segment [MODELS:]
        # ne couvre que l'unite qui agit ; sans ce segment cible, une escouade decimee par le tir
        # ne perdrait ses socles a l'ecran (replay) qu'a sa prochaine action. Chaine vide si la
        # cible est entierement detruite (plus d'entree cache) -> le parser la retire via HP<=0.
        #
        # include_target_models : n'est vrai que sur le DERNIER jet visant cette cible (calcule par
        # _flush_squad_action_logs_to_step_logger). Regle 40K : les pertes se retirent APRES
        # resolution de toutes les attaques (04/05), pas jet par jet. Emettre le segment sur chaque
        # jet ferait chuter les socles des le 1er jet (avant que les degats soient montres) ; le
        # deferer au dernier jet aligne la chute des socles sur la fin des degats -> HP descend
        # d'abord, socles ensuite, conforme au sequencage des regles.
        if include_target_models:
            target_id = raw_log.get("targetId")  # get allowed
            if target_id is not None:
                details["target_models_segment"] = self._models_segment_for_unit(
                    target_id, label="TARGET_MODELS"
                )
        return details

    def _flush_squad_action_logs_to_step_logger(
        self, pre_action_turn: Any,
        pre_action_fight_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Transfere vers le StepLogger les action_logs produits par la derniere action squad.

        V11 T6 (rupture T6-c) : le pipeline squad (`_process_squad_action`, chemin VIF du gym et,
        depuis le 2026-07-28, du bot PvE) n'appelait AUCUN `log_action` — les 17 sites vivent dans
        `_process_semantic_action` (chemin du joueur humain PvP). Resultat : step.log reduit a ses en-tetes (`Actions=0, Steps=0` sur
        474/475 episodes d'un run reel) et `ai/analyzer.py` sans matiere, alors que CLAUDE.md
        fait de « --step + analyzer.py + replay » la SEULE strategie de validation du training.

        Plutot que de dupliquer 17 sites, on draine la source de verite deja produite par les
        handlers : `game_state["action_logs"]`. Ne journalise que les entrees APRES le curseur,
        donc strictement celles de l'action courante. No-op complet si le StepLogger est absent
        ou desactive (cas PvP/production).
        """
        if not (self.step_logger and self.step_logger.enabled):
            return
        action_logs = self.game_state.get("action_logs", [])  # get allowed
        if not isinstance(action_logs, list):
            raise TypeError(
                f"game_state['action_logs'] must be a list, got {type(action_logs).__name__}"
            )
        # CURSEUR PERSISTANT, ET LUI SEUL. Il définit « ce qui n'a pas encore été écrit », ce qui
        # rend ce drainage IDEMPOTENT : deux fenêtres qui se recouvrent (celle d'une transition de
        # phase imbriquée et celle du step qui l'englobe) n'écrivent la ligne qu'une seule fois.
        #
        # Un paramètre `pre_action_logs_len` vivait ici en parallèle, borné par `max()` avec le
        # curseur. Il ne pouvait rien AJOUTER — seulement retrancher : un appelant qui mesure sa
        # longueur trop tard exclut des entrées que le curseur, lui, aurait rattrapées. C'est
        # exactement le mode d'échec qu'on vient de payer (zéro ligne `PILED IN` dans 22 Mo de
        # journal, et un contrôle « Pile-in au-delà de 3" » qui affichait 0 en ne regardant rien).
        # Une borne qui ne peut que perdre des lignes n'a pas sa place à côté d'une qui n'en perd
        # aucune.
        #
        # Un curseur AU-DELÀ de la liste est une VIOLATION D'INVARIANT, pas un état à rattraper.
        # Une remise à 0 vivait ici, justifiée par « l'API PvP vide la liste après chaque
        # réponse » : ce chemin n'atteint jamais cette ligne — `services/api_server` n'installe
        # aucun StepLogger, donc le drain sort au retour anticipé ci-dessus. Sur le seul chemin
        # qui journalise (entraînement/replay), `action_logs` n'est QUE complétée, et le seul
        # vidage (`reset`) purge le curseur dans la même fonction. La remise à 0 ne pouvait donc
        # corriger qu'un état impossible — et, le jour où il cesserait de l'être, elle
        # rédrainerait en SILENCE des entrées déjà écrites : lignes dupliquées dans step.log,
        # donc attaques, activations et distances comptées double par `ai/analyzer.py`.
        pre_action_logs_len = int(self.game_state.get(self.STEP_LOG_DRAINED_KEY, 0))  # get allowed
        if pre_action_logs_len > len(action_logs):
            raise ValueError(
                f"{self.STEP_LOG_DRAINED_KEY}={pre_action_logs_len} cannot exceed current length "
                f"of game_state['action_logs'] ({len(action_logs)}) : la liste a été tronquée "
                f"sans que le curseur de drainage soit purgé (cf. reset)."
            )
        self.game_state[self.STEP_LOG_DRAINED_KEY] = len(action_logs)
        # Position (index raw_log, index jet) du DERNIER jet visant chaque cible sur l'ensemble de
        # l'action : le segment [TARGET_MODELS:] n'est emis que la (retrait des socles en bloc apres
        # les attaques, cf. _build_shot_details). Le dernier ecrit gagne -> derniere arme, dernier jet.
        sub_logs = action_logs[pre_action_logs_len:]
        last_target_jet: Dict[Any, Tuple[int, int]] = {}
        for _ri, _rl in enumerate(sub_logs):
            if not isinstance(_rl, dict):
                continue
            _rl_type = _rl.get("type")  # get allowed
            if isinstance(_rl_type, str) and self._STEP_LOG_TYPE_MAP.get(_rl_type) in ("shoot", "combat"):
                _tid = _rl.get("targetId")  # get allowed
                _shots = _rl.get("shootDetails")  # get allowed
                if _tid is not None and isinstance(_shots, list) and _shots:
                    last_target_jet[_tid] = (_ri, len(_shots) - 1)

        for _raw_idx, raw_log in enumerate(sub_logs):
            if not isinstance(raw_log, dict):
                raise TypeError(f"action_logs entry must be a dict, got {type(raw_log).__name__}")
            raw_type = require_key(raw_log, "type")
            if raw_type == "move":
                # La nuance normal/advance/fall_back vit dans move_type (miroir du legacy, qui
                # emet toujours "move" + was_flee) : le formateur, lui, a 3 types distincts.
                move_type = require_key(raw_log, "move_type")
                if move_type not in self._STEP_LOG_MOVE_TYPE_MAP:
                    raise ValueError(
                        f"action_log de type 'move' avec move_type inconnu: {move_type!r} — "
                        f"attendu {sorted(self._STEP_LOG_MOVE_TYPE_MAP)}"
                    )
                action_type = self._STEP_LOG_MOVE_TYPE_MAP[move_type]
            else:
                action_type = self._STEP_LOG_TYPE_MAP.get(raw_type)  # get allowed
                if action_type is None:
                    continue  # type sans formateur -> volontairement non journalise

            phase = str(raw_log.get("phase") or self.game_state.get("phase") or "unknown")  # get allowed
            player = raw_log.get("player")  # get allowed

            # Tir/combat : le moteur agrege les jets d'un groupe (arme, cible) dans shootDetails,
            # le formateur travaille PAR JET -> une ligne par jet.
            if action_type in ("shoot", "combat"):
                shots = raw_log.get("shootDetails")  # get allowed
                if not isinstance(shots, list):
                    raise TypeError(
                        f"action_log de type {raw_type!r} sans 'shootDetails' exploitable "
                        f"(got {type(shots).__name__}) — contrat _emit_squad_shoot_log rompu"
                    )
                fight_state = pre_action_fight_state if action_type == "combat" else None
                _target_id = raw_log.get("targetId")  # get allowed
                _last_jet = last_target_jet.get(_target_id)  # get allowed
                for _shot_idx, shot in enumerate(shots):
                    if not isinstance(shot, dict):
                        raise TypeError(f"shootDetails entry must be a dict, got {type(shot).__name__}")
                    # Segment cible uniquement sur le DERNIER jet visant cette cible sur toute
                    # l'action (retrait des socles en bloc apres les attaques, cf. _build_shot_details).
                    _emit_target = _last_jet is not None and (_raw_idx, _shot_idx) == _last_jet
                    self.step_logger.log_action(
                        unit_id=raw_log.get("shooterId"),  # get allowed
                        action_type=action_type,
                        phase=phase,
                        player=player,
                        success=True,
                        step_increment=True,
                        action_details=self._build_shot_details(
                            raw_log, shot, pre_action_turn, fight_state,
                            include_target_models=_emit_target,
                        ),
                    )
                continue

            self.step_logger.log_action(
                unit_id=raw_log.get("unitId"),  # get allowed
                action_type=action_type,
                phase=phase,
                player=player,
                success=True,
                step_increment=action_type not in self._STEP_LOG_NON_INCREMENTING_TYPES,
                action_details=self._build_step_log_details(raw_log, pre_action_turn),
            )

    def _run_rules_for_step_log(self) -> Dict[str, Any]:
        """Valeurs de regle REELLEMENT appliquees par ce run, pour l'entete de step.log.

        Elles vivent dans `config/game_config.json`, qu'on edite entre deux runs. L'analyzer les
        relisait dans le fichier COURANT : basculer `distance_metric.engagement` de `hex` a
        `euclidean` changeait tous les verdicts d'engagement d'un vieux journal, en silence et
        sans le garde-fou qui protege deja l'echelle. On les journalise donc a la source.

        `engagement_zone` est pris dans le `game_state`, ou il est DEJA en subhexes (converti au
        chargement) : le consommateur n'a plus aucune conversion a refaire, donc aucune occasion
        de diverger.

        Les metriques passent par les SELECTEURS de phase, jamais par la cle de config brute :
        eux seuls appliquent la resolution (cf. `geometry_is_hex`), donc eux seuls rendent la
        valeur reellement mesuree.
        """
        from engine.spatial_relations import engagement_distance_metric
        from engine.phase_handlers.shooting_handlers import _ranged_distance_metric

        game_rules = require_key(require_key(self.game_state, "config"), "game_rules")
        move_rules = require_key(require_key(self.game_state, "config"), "move")
        return {
            "engagement_zone_subhex": int(require_key(game_rules, "engagement_zone")),
            # Volet VERTICAL de 03.04, en POUCES et non en subhexes : il se compare a des hauteurs
            # de plancher, qui sont deja en pouces. Il est journalise pour la meme raison que son
            # jumeau horizontal — c'est une regle du RUN, et le config s'edite entre deux runs.
            "engagement_zone_vertical_inches": float(
                require_key(game_rules, "engagement_zone_vertical")
            ),
            "metric.engagement": engagement_distance_metric(self.game_state),
            "metric.ranged": _ranged_distance_metric(self.game_state),
            "move.thru_ez": bool(require_key(move_rules, "can_move_through_enemy_engagement_zone")),
            "move.thru_enemy": bool(require_key(move_rules, "can_move_through_enemy_model")),
            "move.thru_friendly": bool(require_key(move_rules, "can_move_through_friendly_model")),
            # 03.03 Coherency. Memes trois parametres que `coherency_violation_flags`, sous les
            # memes noms de config, et pour la meme raison que la zone d'engagement : ils sont
            # deja convertis en subhexes a l'init, et `config/game_config.json` s'edite entre
            # deux runs. Sans eux dans l'entete, l'analyzer ne peut PAS verifier la coherency
            # d'escouade — la seule autre source serait le config du jour, qui juge un vieux
            # journal avec les regles d'aujourd'hui.
            "cohesion.model_subhex": int(require_key(game_rules, "unit_model_cohesion_range")),
            "cohesion.global_subhex": int(require_key(game_rules, "unit_global_cohesion_range")),
            "cohesion.min_neighbors": int(require_key(game_rules, "squad_min_neighbors")),
        }

    def _advance_phase_and_drain(self, advance_action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """`advance_phase` système + DRAINAGE de ses action_logs vers le StepLogger.

        ⚠️ ROOT CAUSE D'UN JOURNAL MUET. Les trois sites `advance_phase` « pool_empty » appelaient
        `_process_squad_action` SANS drainer ensuite. Or cette transition n'est pas neutre : elle
        déclenche `fight_phase_start` puis `_fight_v11_gym_after_phase_start`, donc TOUT le PILE IN
        groupé (12.02). Le drainage de l'action de l'agent, lui, a déjà eu lieu plus haut avec un
        curseur antérieur ; celui du step suivant repart de la longueur COURANTE. Les entrées
        produites entre les deux ne sont drainées par personne.

        Mesuré sur un run de 600 épisodes : ZÉRO ligne `PILED IN` dans 22 Mo de journal, pour
        203 `CONSOLIDATED` — la consolidation, elle, est produite pendant `squad_fight`, donc dans
        la fenêtre. Instrumentation du chemin de production : `fight_pile_in_plan` appelé 24 fois,
        jamais None ; `_gym_commit_fight_move` 24 fois ; `_append_fight_move_log` 24 fois ;
        **drainé 0 fois**. Conséquence côté lecteurs : 229 chargeurs sur 319 changent de position
        entre leur ligne de charge et leur ligne de combat sans qu'aucune ligne ne l'explique, et
        le contrôle « Pile-in au-delà de 3" » de l'analyzer affichait 0 en ne regardant rien.

        UN SEUL point de passage pour les trois sites : trois copies redivergeraient, et c'est
        exactement de cette divergence que le défaut est né.
        """
        # Contexte de FORMATAGE seulement (le tour n'est qu'un repli de `raw_log["turn"]`, la
        # sous-phase sert au contrat replay des lignes de combat) : la BORNE, elle, est le curseur
        # persistant, à l'intérieur du flush. Il n'y a plus rien à mesurer ici.
        # Construit uniquement si quelqu'un journalise : ces valeurs, dont une allocation de dict,
        # tombaient sur le chemin d'entraînement et le PvP, où le flush sort immédiatement.
        _logging = self.step_logger is not None and self.step_logger.enabled
        _pre_turn = require_key(self.game_state, "turn") if _logging else None
        _pre_fight = (
            {"fight_subphase": self.game_state.get("fight_subphase")} if _logging else None  # get allowed
        )
        success, result = self._process_squad_action(advance_action)
        if _logging:
            self._flush_squad_action_logs_to_step_logger(_pre_turn, _pre_fight)
        return success, result

    def _build_step_log_details(self, raw_log: Dict[str, Any], pre_action_turn: Any) -> Dict[str, Any]:
        """Mappe un payload d'action_log moteur vers les action_details du formateur StepLogger.

        Les cles du moteur (camelCase : toCol/targetCol/shootDetails) et celles du formateur
        (snake_case : col/target_coords) divergent — cette fonction est le seul point de
        traduction. `current_turn` est le seul champ EXIGE par `log_action` (require_key).
        Tous les autres sont optionnels cote formateur, qui degrade proprement
        (« (dice data incomplete) ») : une entree pauvre produit une ligne valide, jamais un crash.
        """
        unit_id = raw_log.get("unitId")  # get allowed
        to_col = raw_log.get("toCol")  # get allowed
        to_row = raw_log.get("toRow")  # get allowed
        from_col = raw_log.get("fromCol")  # get allowed
        from_row = raw_log.get("fromRow")  # get allowed
        details: Dict[str, Any] = {
            "current_turn": raw_log.get("turn", pre_action_turn),  # get allowed
            "reward": raw_log.get("reward", 0.0),  # get allowed
        }
        if to_col is not None and to_row is not None:
            details["col"] = to_col
            details["row"] = to_row
            details["end_pos"] = (to_col, to_row)
            details["unit_with_coords"] = f"{unit_id}({to_col},{to_row})"
        elif "col" in raw_log and "row" in raw_log:
            details["col"] = raw_log["col"]
            details["row"] = raw_log["row"]
            details["unit_with_coords"] = f"{unit_id}({raw_log['col']},{raw_log['row']})"
        if from_col is not None and from_row is not None:
            details["start_pos"] = (from_col, from_row)
        # [HAZARDOUS] 24.15 : le formateur exige ce champ, et le payload moteur le porte
        # desormais. Sans cette traduction, la ligne leve et `log_action` avale l'exception —
        # « ⚠️ Step logging error », journal muet, zero ligne HAZARD sur un run entier.
        _hazard_mw = raw_log.get("hazardousMortalWounds")  # get allowed : types non-hasardeux
        if _hazard_mw is not None:
            details["hazardous_mortal_wounds"] = _hazard_mw
        target_col = raw_log.get("targetCol")  # get allowed
        target_row = raw_log.get("targetRow")  # get allowed
        if target_col is not None and target_row is not None:
            details["target_coords"] = (target_col, target_row)
        # 21.03 : le drapeau de traversée FLY produit par les handlers de move. Sans ce
        # mapping, `step_logger` n'écrit jamais `MOVED [FLY]` et l'analyzer pathfinde une
        # escouade volante comme de l'infanterie.
        details["is_fly_move"] = bool(raw_log.get("is_fly_move", False))  # get allowed
        # Champs propres au move REACTIF, exiges par son formateur (`require_key`) : sans eux
        # `log_action` avale l'exception et la ligne disparait en silence.
        for _src, _dst in (
            ("triggered_by_unit_id", "triggered_by_unit_id"),
            ("range_roll", "range_roll"),
            ("ability_display_name", "ability_display_name"),
        ):
            _val = raw_log.get(_src)  # get allowed
            if _val is not None:
                details[_dst] = _val
        _ev_to_col = raw_log.get("event_toCol")  # get allowed
        _ev_to_row = raw_log.get("event_toRow")  # get allowed
        if _ev_to_col is not None and _ev_to_row is not None:
            details["trigger_to_pos"] = (_ev_to_col, _ev_to_row)
        for src, dst in (
            ("targetId", "target_id"),
            ("weaponName", "weapon_name"),
            ("charge_roll", "charge_roll"),
            ("charge_failed_reason", "charge_failed_reason"),
            ("advance_roll", "advance_range"),
            ("selected_rule_name", "selected_rule_name"),
        ):
            value = raw_log.get(src)  # get allowed
            if value is not None:
                details[dst] = value
        details["models_segment"] = self._models_segment_for_unit(unit_id)
        return details

    def _gym_commit_fight_move(
        self, gs: Dict[str, Any], uid: str, plan: List[Tuple[str, int, int, int]], kind: str
    ) -> None:
        """Commit gym d'un move fight groupé (pile-in/consolidation) + log par-figurine.

        Le driver gym résout ces déplacements via ``commit_move`` sans passer par les handlers
        interactifs : le log par-figurine (source du step.log/replay ET du game log PvP) doit donc
        être émis ICI, via la helper partagée ``_append_fight_move_log`` — sinon le training ne
        produit AUCUNE ligne pile-in/consolidation. Miroir strict du chemin manuel : capture des
        positions par-figurine + ancre AVANT le commit, arrivée relue APRÈS.
        """
        from engine.phase_handlers.shared_utils import commit_move
        from engine.phase_handlers.fight_handlers import _append_fight_move_log

        unit = self._get_unit_by_id(str(uid))
        if unit is None:
            raise KeyError(f"_gym_commit_fight_move: unité {uid!r} absente de game_state['units']")
        models_cache = require_key(gs, "models_cache")
        squad_models = require_key(gs, "squad_models")
        alive = [str(m) for m in require_key(squad_models, str(uid)) if str(m) in models_cache]
        before = {
            m: (int(models_cache[m]["col"]), int(models_cache[m]["row"])) for m in alive
        }
        uc_before = require_key(gs, "units_cache")[str(uid)]
        from_col, from_row = int(uc_before["col"]), int(uc_before["row"])
        plan_dest = {str(e[0]): (int(e[1]), int(e[2])) for e in plan}

        commit_move(plan, gs, kind)

        uc_after = require_key(gs, "units_cache")[str(uid)]
        to_col, to_row = int(uc_after["col"]), int(uc_after["row"])
        move_details = [
            {
                "modelId": m,
                "fromCol": before[m][0],
                "fromRow": before[m][1],
                "toCol": plan_dest.get(m, before[m])[0],
                "toRow": plan_dest.get(m, before[m])[1],
            }
            for m in alive
        ]
        _append_fight_move_log(
            gs, unit, kind=kind,
            from_col=from_col, from_row=from_row,
            to_col=to_col, to_row=to_row,
            move_details=move_details,
        )

    def _fight_v11_gym_settle(self) -> None:
        """Deroule les etapes NON-DECISIONNELLES de la machine V11 (chemin gym uniquement).

        La phase de combat (12.01-12.09) alterne trois etapes : PILE IN groupe (12.02), FIGHT
        (12.04), CONSOLIDATE groupe (12.07). Une seule comporte une decision que l agent prenne
        reellement : le CHOIX de l unite qui combat (12.04). Les destinations de pile-in et de
        consolidation, elles, sont deja calculees par le moteur (`fight_pile_in_plan` /
        `squad_consolidate_plan`) — l agent n en a jamais choisi aucune. Ce driver resout donc
        les deux etapes groupees de bout en bout et rend la main a l agent exactement quand la
        machine attend une selection FIGHT.

        Consequence — et c est l objet du fix : le snapshot `engaged_at_fight_step_start` (12.04
        « was engaged at the start of this step », et sa negation pour l overrun 12.06) est pris
        par `fight_v11_enter_fight_step` APRES que TOUS les pile-in des DEUX joueurs sont
        resolus. C est la seule datation conforme, et elle est impossible a obtenir tant que le
        pile-in d une escouade s intercale entre deux combats.

        Pile-in/consolidation sont resolus PAR-FIGURINE (`fight_pile_in_plan`,
        `squad_consolidate_plan`) et non via les helpers par-ancre `_fight_v11_auto_pile_in` /
        `_fight_v11_auto_consolidate` : le pile-in de reference est le par-figurine du PvP, le
        par-ancre est condamne.

        Chemin `_process_squad_action` (gym + bot PvE) : le PvP humain conduit la meme machine pas
        a pas via `fight_handlers`, qui n est pas touche.

        Ne termine PAS la phase : le gym transitionne par l action systeme `advance_phase` quand
        le masque se vide (`fight_phase_end`), jamais par une cascade depuis une action d unite.
        Completer ici ferait cascader `squad_fight` vers la phase suivante, et la cascade
        REMPLACE le resultat de l action — l agent perdrait le `fight_result` (donc le reward) du
        combat qui cloture la phase. Une fois les trois etapes drainees, le pool 12.04 est vide,
        le masque aussi, et la route existante prend le relais.
        """
        from engine.phase_handlers.fight_handlers import (
            fight_v11_advance_selection,
            fight_v11_enter_consolidate,
            fight_v11_enter_fight_step,
            fight_v11_grouped_next,
        )
        from engine.phase_handlers.shared_utils import (
            fight_pile_in_plan,
            squad_consolidate_plan,
        )

        gs = self.game_state
        phase = require_key(gs, "phase")
        if phase != "fight":
            raise RuntimeError(f"_fight_v11_gym_settle appele hors phase fight (phase={phase!r})")

        # Chaque tour de boucle marque >=1 unite `*_done` ou franchit une etape : la borne ne
        # peut etre atteinte que si la machine ne progresse pas -> bug, donc erreur explicite.
        max_iterations = 4 * len(require_key(gs, "units")) + 16
        for _ in range(max_iterations):
            sub = require_key(gs, "fight_subphase")

            if sub == "pile_in":
                nxt = fight_v11_grouped_next(gs, "pile_in")
                if nxt is None:
                    fight_v11_enter_fight_step(gs)
                    continue
                for uid in nxt[1]:
                    plan = fight_pile_in_plan(gs, str(uid))
                    if plan is not None:
                        self._gym_commit_fight_move(gs, str(uid), plan, "pile_in")
                    # 12.02 : « Each unit cannot make more than one pile-in move during this
                    # step » — le marquage vaut aussi pour un plan vide (skip legal, 12 encart).
                    require_key(gs, "pile_in_done").add(str(uid))
                continue

            if sub == "fight":
                # Non-mutant du point de vue de la selection : `advance_selection` ne marque
                # rien, il ne fait qu avancer `fight_step`/`fight_selector` (handoff 12.04).
                if fight_v11_advance_selection(gs) is None:
                    fight_v11_enter_consolidate(gs)
                    continue
                return  # une selection est possible : la main revient a l agent

            if sub == "consolidate":
                nxt = fight_v11_grouped_next(gs, "consolidate")
                if nxt is None:
                    return  # 12.07 drainee : pool vide -> masque vide -> `advance_phase`
                for uid in nxt[1]:
                    plan = squad_consolidate_plan(gs, str(uid))
                    if plan is not None:
                        self._gym_commit_fight_move(gs, str(uid), plan, "consolidation")
                    require_key(gs, "consolidation_done").add(str(uid))
                continue

            raise ValueError(f"fight_subphase inattendu dans le chemin gym: {sub!r}")

        raise RuntimeError(
            f"_fight_v11_gym_settle n a pas converge en {max_iterations} iterations "
            f"(fight_subphase={gs.get('fight_subphase')!r}, "
            f"pile_in_done={sorted(gs.get('pile_in_done', set()))}, "
            f"units_selected_to_fight={sorted(gs.get('units_selected_to_fight', set()))})"
        )

    def _fight_v11_gym_after_phase_start(
        self, phase_init_result: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Enchaine `_fight_v11_gym_settle` sur `fight_phase_start` (chemin gym).

        Resout le PILE IN groupe (12.02) des l entree en phase, pour que la premiere action que
        l agent voie soit deja une selection FIGHT (12.04) sur un snapshot pris au bon moment.

        `fight_phase_start` peut avoir deja complete une phase vide (aucune unite engagee ni
        ayant charge) : la machine est alors eteinte (`fight_subphase is None`) et il n y a rien
        a derouler. `phase_init_result` est rendu tel quel : la fin de phase ne passe jamais par
        ce driver (cf. `_fight_v11_gym_settle`).
        """
        if self.game_state.get("fight_subphase") is None:  # get allowed (phase vide -> machine eteinte)
            return phase_init_result
        self._fight_v11_gym_settle()
        return phase_init_result

    def _process_squad_action(self, semantic: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Dispatch sémantique squad vers helpers squad. Remplace _process_semantic_action."""
        from engine.action_log_utils import append_action_log
        from engine.phase_handlers.generic_handlers import end_activation
        from engine.phase_handlers.shared_utils import (
            execute_squad_move,
            clear_squad_move_cell_map,
            squad_shooting_unit_activation_start,
            squad_declare_shoot,
            squad_lock_shoot,
            build_manual_shoot_allocation,
            squad_fight_restart_activation,
            squad_declare_fight,
            commit_move,
            charge_build_valid_plan,
            get_enemy_slot_mapping,
        )
        from engine.game_utils import add_console_log
        # 21.03 « take to the skies » — consomme par le move squad ET par la charge squad :
        # les deux emettent un action_log qui doit porter `is_fly_move`.
        from engine.phase_handlers.movement_handlers import _fly_traversal_active as _fta
        # Capacité qui rend une charge après Advance légale (datasheet ou Waaagh!) : MÊME source
        # que les deux chemins de commit de `charge_handlers`, pour que `step.log` nomme la même
        # capacité ici que là-bas (l'analyzer agrège son usage).
        from engine.phase_handlers.charge_handlers import _charge_enabling_ability

        if self.game_state.get("game_over", False):
            return False, {"error": "game_over", "winner": self.game_state.get("winner")}

        self._initialize_rule_choice_runtime_state()

        if semantic.get("action") == "select_rule_choice":
            return self._handle_select_rule_choice_action(semantic)

        # Décision agent (V11 §9.3 P2) : traitée AVANT le court-circuit `active_rule_choice_prompt`
        # et avant toute action de phase — c'est la seule action légale tant qu'une décision est
        # en attente, et c'est elle qui débloque le moteur.
        if semantic.get("action") == "agent_decision":
            return self._handle_agent_decision_action(semantic)

        # Désignation d'Oath of Moment (chantier 03) : même rang que les deux ci-dessus — la
        # phase de commandement est arrêtée dessus, aucune action de phase n'a de sens tant
        # qu'elle n'est pas jouée.
        if semantic.get("action") == "select_oath_target":
            return self._handle_select_oath_target_action(semantic)

        # Choix de l'escouade à activer (V11 §0.48 L2) : même rang que les trois ci-dessus.
        if semantic.get("action") == "select_activation":
            return self._handle_select_activation_action(semantic)

        blocked = self._reject_action_while_faction_decision_pending(semantic)
        if blocked is not None:
            return blocked

        active_prompt = self.game_state.get("active_rule_choice_prompt")
        if active_prompt is not None:
            return True, {
                "action": "waiting_for_rule_choice",
                "waiting_for_player": True,
                "rule_choice_prompt": active_prompt,
                "unitId": require_key(active_prompt, "unit_id"),
                "player": int(require_key(self.game_state, "current_player")),
            }

        current_phase = self.game_state["phase"]
        success = True
        result: Dict[str, Any] = {}
        action_name = semantic.get("action")

        # ── advance_phase : transition pool vide ──────────────────────────────
        if action_name == "advance_phase":
            from_phase = semantic.get("from", current_phase)
            if from_phase == "shoot":
                result = shooting_handlers.shooting_phase_end(self.game_state)
                self._shooting_phase_initialized = False
                result.setdefault("phase_complete", True)
                result.setdefault("reason", "pool_empty")
            elif from_phase == "fight":
                result = fight_handlers.fight_phase_end(self.game_state)
                result.setdefault("phase_complete", True)
                result.setdefault("reason", "pool_empty")
            elif from_phase == "deployment":
                result = {"phase_complete": True, "next_phase": "command", "reason": "pool_empty"}
            else:
                next_phase_map = {"move": "shoot", "charge": "fight", "command": "move"}
                result = {
                    "phase_complete": True,
                    "next_phase": next_phase_map.get(from_phase, "move"),
                    "reason": "pool_empty",
                }

        # ── deployment : logique existante inchangée ──────────────────────────
        elif action_name == "deploy_unit":
            success, result = deployment_handlers.execute_deployment_action(self.game_state, semantic)
            # V11 T6 : `deployment_handlers` n'emet AUCUN action_log (grep = 0). Consequence
            # mesuree : l'en-tete d'episode ecrit les unites non deployees en (-1,-1) et
            # l'analyzer, faute de log de deploiement, n'apprend JAMAIS leur position reelle ->
            # suivi de positions faux des le depart (49 « collisions » 2.2, faux positifs).
            # Emis ici, apres succes, avec la position canonique (units_cache), comme le move.
            if success:
                _dep_unit_id = semantic.get("unitId")  # get allowed
                if _dep_unit_id is not None:
                    _dep_unit = get_unit_by_id(str(_dep_unit_id), self.game_state)
                    if _dep_unit is None:
                        raise KeyError(f"Unit {_dep_unit_id} introuvable apres deploy_unit")
                    _dep_col, _dep_row = require_unit_position(str(_dep_unit_id), self.game_state)
                    append_action_log(
                        self.game_state,
                        {
                            "type": "deploy_unit",
                            "message": (
                                f"Unit {_dep_unit_id} DEPLOYED from (-1,-1) "
                                f"to ({_dep_col},{_dep_row})"
                            ),
                            "turn": require_key(self.game_state, "turn"),
                            "phase": "deployment",
                            "unitId": _dep_unit_id,
                            "player": require_key(_dep_unit, "player"),
                            # (-1,-1) = convention « non deployee » de l'en-tete d'episode
                            # (log_episode_start ecrit « Starting position (-1,-1) ») : le
                            # formateur deploy_unit exige start_pos ET end_pos.
                            "fromCol": -1,
                            "fromRow": -1,
                            "toCol": _dep_col,
                            "toRow": _dep_row,
                            "timestamp": "server_time",
                            "reward": 0.0,
                        },
                    )

        # ── 20.01 : mise en réserves au lieu du déploiement ───────────────────
        elif action_name == "deploy_strategic_reserves":
            success, result = deployment_handlers.deployment_place_in_strategic_reserves(
                self.game_state, semantic
            )

        # ── 20.04 : ingress move (arrivée de réserves) ────────────────────────
        elif action_name == "ingress_move":
            squad_id = str(require_key(semantic, "unitId"))
            # MÊME point d'exécution que le flux PvP (`movement_handlers.execute_action`) : le
            # plan y est reconstruit par `build_validated_deployment_plan`, déterministe, donc
            # identique à celui que le masque a validé. Deux implémentations — une par siège —
            # ont déjà produit ici un ingress sans fin d'activation côté PvP.
            _ing_unit = get_unit_by_id(squad_id, self.game_state)
            if _ing_unit is None:
                raise KeyError(f"Unit {squad_id} introuvable pour ingress_move")
            success, result = movement_handlers.execute_action(
                self.game_state, _ing_unit,
                {
                    "action": "ingress_move", "unitId": squad_id,
                    "destCol": int(require_key(semantic, "destCol")),
                    "destRow": int(require_key(semantic, "destRow")),
                },
                self.config,
            )
            if not success:
                # Le plan vient du MÊME `ingress_slot_candidates` que le masque : un refus est
                # une rupture d'invariant masque/exécution, pas un cas nominal.
                raise ValueError(
                    f"ingress_move refusé pour l'escouade {squad_id} alors que le masque "
                    f"l'autorisait : {result}"
                )
            # Journal d'action et fin d'activation : faits par `movement_handlers`, pour les
            # DEUX sièges. Les refaire ici produirait une ligne en double et retirerait une
            # SECONDE unité du pool.
            # Pas de `end_activation` ici : `movement_handlers` l'a déjà faite, comme pour tout
            # autre type de mouvement. La refaire retirerait une SECONDE unité du pool.

        # ── zone_intent : command phase ───────────────────────────────────────
        elif action_name == "zone_intent":
            success, result = self._process_command_phase(semantic)

        # ── command_wait : passer la phase command sans action ────────────────
        elif action_name == "command_wait":
            success, result = self._process_command_phase({"action": "skip"})

        # ── squad_wait : fin d'activation sans action ─────────────────────────
        elif action_name == "squad_wait":
            squad_id = semantic["squad_id"]
            # (tracking Arg3, pool Arg4). Arg4 retire du pool d'activation — c'est lui qui
            # interdit la ré-activation. Arg3 marque « l'unité A FAIT l'action », ce qui est faux
            # pour un WAIT en phase de charge : `units_charged` ne sert qu'aux règles 11.04 /
            # 12.03 / 12.04, qui exigent toutes un charge move EFFECTUÉ. Une escouade qui renonce
            # à charger gagnait ainsi Fights First. -> PASS en Arg3, CHARGE en Arg4.
            phase_tracking = {
                "move": ("MOVE", "MOVE"),
                "shoot": ("SHOOTING", "SHOOTING"),
                "charge": (PASS, "CHARGE"),  # get allowed
                "fight": ("FIGHT", "FIGHT"),
            }
            tracking, pool = phase_tracking.get(current_phase, ("MOVE", "MOVE"))
            unit = get_unit_by_id(squad_id, self.game_state)
            if unit is None:
                raise KeyError(f"Squad {squad_id} introuvable pour squad_wait")
            if current_phase == "move":
                self.game_state.get("_squad_advance_rolls", {}).pop(squad_id, None)  # get allowed
                # Miroir du pop du jet : la carte de cellules est propre a cette activation.
                clear_squad_move_cell_map(self.game_state, squad_id)
            end_result = end_activation(self.game_state, unit, WAIT, 1, tracking, pool, 0)
            result = {**end_result, "action": "squad_wait", "squad_id": squad_id}

        # ── mouvement : normal / advance / fall_back ──────────────────────────
        elif action_name in ("squad_normal_move", "squad_advance", "squad_fall_back"):
            squad_id = semantic["squad_id"]
            move_type_map = {
                "squad_normal_move": "normal",  # get allowed
                "squad_advance": "advance",
                "squad_fall_back": "fall_back",
            }
            move_type = move_type_map[action_name]
            # Advance : le jet est produit par le decoder (pre-tire au masque, §10.4). Son absence
            # est une rupture de contrat, pas un cas nominal -> require_key, jamais `.get()`.
            advance_roll = int(require_key(semantic, "advance_roll")) if move_type == "advance" else None

            # Destination issue du POOL BFS via la carte de cellules du masque (refonte spatiale
            # §7 T3). JAMAIS reconstruite a la main : l'ancien code visait `neighbors[direction]`,
            # donc l'hex ADJACENT — c'etait la root cause §3 (1 subhex par phase). Et sauter a
            # « ancre + budget x direction » traverserait les murs (§4.2), puisque
            # `validate_move_plan` ne controle que la case d'arrivee, jamais le trajet.
            dest_col = int(require_key(semantic, "destCol"))
            dest_row = int(require_key(semantic, "destRow"))

            # V11 T6 : position CANONIQUE de l'unite (units_cache) AVANT le move, capturee ici
            # car execute_squad_move la mute. L'analyzer suit cette position (celle de l'en-tete
            # d'episode et de _emit_squad_shoot_log).
            _move_from_col, _move_from_row = require_unit_position(squad_id, self.game_state)

            # 21.03 « take to the skies » : capture AVANT le commit, comme la position d'ancre —
            # le drapeau qualifie le mouvement QUI EST FAIT. C'est ce chemin (pipeline squad) que
            # le gym exécute, pas `movement_commit_move_plan_handler` (PvP) : le drapeau n'y était
            # pas transmis, aucun `[FLY]` n'atteignait step.log, et l'analyzer pathfindait au SOL
            # des escouades volantes — 1014 faux « au-delà du budget » mesurés sur un run de 600
            # épisodes. Les deux émetteurs PvP de `movement_handlers` le portaient déjà.
            _move_unit_pre = get_unit_by_id(squad_id, self.game_state)
            if _move_unit_pre is None:
                raise KeyError(f"Squad {squad_id} introuvable avant déplacement")
            _move_is_fly = _fta(self.game_state, _move_unit_pre, str(squad_id))

            # Plus de dry-run de legalite ici, et plus de degradation silencieuse en `squad_wait` :
            # la destination VIENT du pool que le masque a lui-meme utilise (meme carte, cf.
            # `read_squad_move_cell_map`), donc elle est legale par construction. L'ancien
            # `_squad_direction_move_legal` + repli sur wait existait parce que le masque
            # directionnel pouvait diverger de l'execution ; ce repli MASQUAIT ce mismatch au lieu
            # de le signaler. Si `execute_squad_move` echoue desormais, c'est un bug d'invariant
            # -> erreur explicite.
            ok = execute_squad_move(squad_id, dest_col, dest_row, move_type, self.game_state, advance_roll)
            if not ok:
                # L'invariant viole doit NOMMER la contrainte qui l'a rejete : sans cela chaque
                # occurrence oblige a re-deviner la cause. Rejoue la MEME construction de plan et
                # les MEMES contraintes que `execute_squad_move` (helpers partages, aucune
                # reimplementation) — chemin d'erreur uniquement, donc zero cout nominal.
                from engine.phase_handlers.shared_utils import (
                    build_rigid_plan,
                    explain_move_plan_rejection,
                    resolve_squad_move_constraints,
                )
                _plan = build_rigid_plan(dest_col, dest_row, squad_id, self.game_state)
                if _plan is None:
                    _reason = "build_rigid_plan a renvoyé None (aucune figurine vivante)"
                else:
                    _reason = explain_move_plan_rejection(
                        _plan,
                        self.game_state,
                        resolve_squad_move_constraints(
                            squad_id, self.game_state, move_type, advance_roll
                        ),
                    ) or "aucune contrainte violée au rejeu (état muté entre-temps)"
                raise ValueError(
                    f"execute_squad_move a échoué : squad={squad_id} type={move_type} "
                    f"dest=({dest_col},{dest_row}) depuis ({_move_from_col},{_move_from_row}) — "
                    f"la destination vient du pool BFS du masque, elle DOIT être exécutable "
                    f"(incohérence masque/exécution). Contrainte violée : {_reason}"
                )
            self.game_state.get("_squad_advance_rolls", {}).pop(squad_id, None)  # get allowed
            clear_squad_move_cell_map(self.game_state, squad_id)
            unit = get_unit_by_id(squad_id, self.game_state)
            if unit is None:
                raise KeyError(f"Squad {squad_id} introuvable après déplacement")
            tracking = "FLED" if move_type == "fall_back" else "MOVE"
                # V11 T6 — contrat de journalisation : `end_activation(..., ACTION, ...)` signifie
                # « action DEJA journalisee par le handler » (generic_handlers ~L72-74). Or
                # `execute_squad_move` n'emet aucun action_log (contrairement au chemin legacy
                # par-figurine, movement_handlers ~L3701) : le chemin squad violait ce contrat,
                # laissant game_state["action_logs"] incomplet — d'ou un step.log sans aucune
                # action et un analyzer sans matiere (cf. T6-c). Emission en miroir du payload
                # legacy (meme type "move" + was_flee ; `move_type` porte la nuance
                # normal/advance/fall_back pour le mapping vers le formateur du StepLogger).
            # `execute_squad_move` n'a qu'un appelant : ce site (gym + bot PvE) -> zero impact
            # sur le PvP humain, qui passe par execute_semantic_action.
            _move_to_col, _move_to_row = require_unit_position(squad_id, self.game_state)
            append_action_log(
                self.game_state,
                {
                    "type": "move",
                    "message": (
                        f"Unit {squad_id} ({_move_from_col},{_move_from_row}) MOVED "
                        f"to ({_move_to_col},{_move_to_row})"
                    ),
                    "turn": require_key(self.game_state, "turn"),
                    "phase": "move",
                    "unitId": squad_id,
                    "player": require_key(unit, "player"),
                    "fromCol": _move_from_col,
                    "fromRow": _move_from_row,
                    "toCol": _move_to_col,
                    "toRow": _move_to_row,
                    "was_flee": move_type == "fall_back",
                    "move_type": move_type,
                    "advance_roll": advance_roll,
                    "is_fly_move": _move_is_fly,
                    "timestamp": "server_time",
                    "action_name": action_name,
                    "reward": 0.0,
                },
            )
            # Emission AVANT end_activation(ACTION) : c'est l'ordre qu'impose le contrat
            # (« action already logged by handlers »).
            end_result = end_activation(self.game_state, unit, ACTION, 1, tracking, MOVE, 0)
            result = {
                **end_result,
                "action": action_name,
                "squad_id": squad_id,
                "move_type": move_type,
                "toCol": dest_col,
                "toRow": dest_row,
            }

        # ── tir ───────────────────────────────────────────────────────────────
        elif action_name == "squad_shoot":
            squad_id = semantic["squad_id"]
            target_slot = int(semantic["target_slot"])
            units_cache = require_key(self.game_state, "units_cache")
            cache_entry = units_cache.get(squad_id)
            if cache_entry is None:
                raise KeyError(f"Squad {squad_id} absent de units_cache pour squad_shoot")
            our_player = int(require_key(cache_entry, "player"))
            enemy_slots = get_enemy_slot_mapping(self.game_state, our_player)
            if target_slot >= len(enemy_slots):
                raise ValueError(
                    f"squad_shoot: target_slot {target_slot} hors limite (len={len(enemy_slots)})"
                )
            target_squad_id = enemy_slots[target_slot]
            if target_squad_id is None:
                raise ValueError(
                    f"squad_shoot: target_slot {target_slot} est None — mask aurait dû l'empêcher"
                )
            eligible_slots = [sid for sid in enemy_slots if sid is not None]

            squad_shooting_unit_activation_start(self.game_state, squad_id)
            # `active_shooting_unit` n'est volontairement PAS posée ici (V11 §0.48 L2) : cette clé
            # désigne une activation de tir EN COURS, or celle de l'agent est ATOMIQUE — aucun
            # lecteur entre la pose et le retrait, et toute sortie par exception la laisserait
            # périmée. Le front lit le tireur dans `result.unitId` (fourni par `end_activation`).
            squad_declare_shoot(self.game_state, squad_id, target_squad_id, eligible_slots)
            squad_lock_shoot(self.game_state, squad_id)
            # Convergence §8 : resolution tir via le moteur d allocation par-figurine
            # (groupes 05.03/05.04, T bodyguard 19.02, save par-fig). Defenseur IA garanti
            # en gym/auto -> auto_decider headless -> resolution complete (done).
            _shoot_alloc = build_manual_shoot_allocation(self.game_state, squad_id)
            if not _shoot_alloc.get("done"):
                raise RuntimeError(
                    f"squad_shoot: allocation tir non terminee en auto pour squad {squad_id} "
                    f"(defenseur non-IA ?) — action={_shoot_alloc.get('action')}"
                )
            shoot_result = _shoot_alloc["shoot_result"]

            unit = get_unit_by_id(squad_id, self.game_state)
            if unit is None:
                raise KeyError(f"Squad {squad_id} introuvable pour end_activation après tir")
            end_result = end_activation(self.game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 0)
            result = {
                **end_result,
                "action": "squad_shoot",
                "squad_id": squad_id,
                "target_squad_id": target_squad_id,
                "shoot_result": shoot_result,
            }

        # ── charge ────────────────────────────────────────────────────────────
        elif action_name == "squad_charge":
            squad_id = semantic["squad_id"]
            from engine.phase_handlers.shared_utils import (
                charge_check_eligibility, roll_charge_distance, unit_can_reroll_charge,
            )
            # V11 §9 P3-2 : la cible de charge est CHOISIE PAR L AGENT, via le slot ennemi porte
            # par l action (11.02 « Declare Charge » : la selection de la cible est un choix de
            # joueur). Le decodeur ne tranche plus par `get_best_enemy_score_for_unit`.
            # Parite masque/commit dans les DEUX sens : le masque n ouvre un slot que si sa cible
            # est declarable, et le commit refuse tout slot dont la cible ne l est pas. Aucun
            # repli sur une heuristique — une divergence est une rupture, pas un cas a absorber.
            _charge_units_cache = require_key(self.game_state, "units_cache")
            _charge_entry = _charge_units_cache.get(str(squad_id))
            if _charge_entry is None:
                raise KeyError(f"Squad {squad_id} absent de units_cache pour squad_charge")
            target_slot = int(semantic["target_slot"])
            enemy_slot_ids = get_enemy_slot_mapping(
                self.game_state, int(require_key(_charge_entry, "player"))
            )
            if not (0 <= target_slot < len(enemy_slot_ids)):
                raise ValueError(
                    f"squad_charge: target_slot {target_slot} hors du mapping de slots ennemis "
                    f"({len(enemy_slot_ids)} slots)"
                )
            target_squad_id = enemy_slot_ids[target_slot]
            if target_squad_id is None:
                raise ValueError(
                    f"squad_charge: slot {target_slot} vide — le masque n aurait pas du l ouvrir"
                )
            target_squad_id = str(target_squad_id)
            if not charge_check_eligibility(self.game_state, str(squad_id), [target_squad_id]):
                raise ValueError(
                    f"squad_charge: slot {target_slot} -> cible {target_squad_id} non declarable "
                    f"(11.02) pour squad {squad_id} (rupture masque/commit)"
                )
            charge_roll = roll_charge_distance(self.game_state, squad_id)
            plan = charge_build_valid_plan(self.game_state, squad_id, [target_squad_id], charge_roll)
            # `reroll_charge` (unit_rules.json ; 19.04 pour une unité attachée) : « it CAN reroll
            # the charge roll ». La décision est prise sur le seul critère qui compte et qui est
            # ici connu sans approximation — le jet n'atteint aucune destination légale au contact
            # de la cible. Un dé ne se relance qu'une fois (01 Core, Re-rolls) : une seule tentative.
            if plan is None and unit_can_reroll_charge(self.game_state, squad_id):
                charge_roll = roll_charge_distance(
                    self.game_state, squad_id, previous_roll=charge_roll
                )
                plan = charge_build_valid_plan(
                    self.game_state, squad_id, [target_squad_id], charge_roll
                )
            unit = get_unit_by_id(squad_id, self.game_state)
            if unit is None:
                raise KeyError(f"Squad {squad_id} introuvable pour squad_charge")
            # V11 T6 : coords ancre AVANT commit (le plan deplace les figurines).
            _sq_uc = self.game_state.get("units_cache", {}).get(str(squad_id), {})  # get allowed
            _tgt_uc = self.game_state.get("units_cache", {}).get(str(target_squad_id), {})  # get allowed
            _charge_from = (int(_sq_uc["col"]), int(_sq_uc["row"])) if "col" in _sq_uc else None
            _charge_target = (int(_tgt_uc["col"]), int(_tgt_uc["row"])) if "col" in _tgt_uc else None
            if plan is None:
                # Arg3 = PASS, pas CHARGE : une charge RATÉE n'est pas un charge move. 11.04 place
                # le grant de Fights First sous « AFTER MOVING » du charge move, et 12.03/12.04
                # disent « made a charge move this turn » — un jet insuffisant n'en fait aucun.
                # Avec Arg3 = CHARGE, `end_activation` ajoutait l'escouade à `units_charged`, dont
                # les SEULS consommateurs sont ces règles-là (`is_fights_first`,
                # `_fight_v11_charged_this_turn`) : l'escouade gagnait Fights First et passait
                # devant les vrais chargeurs. Le jumeau PvP (`charge_handlers` ~L2929) passait déjà
                # PASS ; c'était une divergence gym. Arg4 reste CHARGE : le retrait du
                # `charge_activation_pool` est ce qui interdit la ré-activation, pas `units_charged`.
                end_result = end_activation(self.game_state, unit, NO, 1, PASS, CHARGE, 0)
                # V11 T6 — contrat de journalisation (cf. squad_move) : le chemin squad n'emettait
                # aucun action_log de charge. Miroir du type legacy "charge_fail"
                # (charge_handlers ~L3010/4425/5719). `charge_failed_reason` est le SEUL champ
                # obligatoire du formateur qu'aucune donnee existante ne fournissait : ici l'echec
                # est exactement « aucun plan de charge valide pour ce jet » (2D6 insuffisant ou
                # aucune destination legale au contact — charge_build_valid_plan a renvoye None).
                append_action_log(
                    self.game_state,
                    {
                        "type": "charge_fail",
                        "message": (
                            f"Unit {squad_id} FAILED CHARGE at Unit {target_squad_id} "
                            f"- Roll:{charge_roll}"
                        ),
                        "turn": require_key(self.game_state, "turn"),
                        "phase": "charge",
                        "unitId": squad_id,
                        "player": require_key(unit, "player"),
                        "targetId": target_squad_id,
                        "charge_roll": charge_roll,
                        "charge_failed_reason": "no valid charge plan for roll",
                        "targetCol": _charge_target[0] if _charge_target else None,
                        "targetRow": _charge_target[1] if _charge_target else None,
                        "timestamp": "server_time",
                        "reward": 0.0,
                    },
                )
                result = {
                    **end_result,
                    "action": "squad_charge",
                    "squad_id": squad_id,
                    "target_squad_id": target_squad_id,
                    "charge_roll": charge_roll,
                    "charge_succeeded": False,
                }
            else:
                # 21.03 — JUMEAU du drapeau pose sur le move squad, capture AVANT le commit pour
                # la meme raison. Le moteur retranche deja 2" au jet (`_charge_budget_subhex`) et
                # autorise la traversee ; sans ce drapeau, la ligne `CHARGED` de step.log ne porte
                # pas `[FLY]` et l'analyzer juge la charge avec un budget 2" trop large ET des
                # murs qui ne s'appliquent pas. Le formateur du StepLogger le lit deja.
                _charge_is_fly = _fta(self.game_state, unit, str(squad_id))
                # JUMEAU du commit PvP : le nom de la capacité qui a autorisé la charge (repli,
                # Assault, Waaagh!) est lu AVANT le commit — `commit_move` ne touche pas
                # `units_advanced`, mais l'ordre reste celui du chemin PvP pour que les deux
                # lisent le même état.
                _charge_ability, _charge_rule_marker = _charge_enabling_ability(self.game_state, unit)
                commit_move(plan, self.game_state, "charge")
                end_result = end_activation(self.game_state, unit, ACTION, 1, CHARGE, CHARGE, 0)
                _dest_uc = self.game_state.get("units_cache", {}).get(str(squad_id), {})  # get allowed
                append_action_log(
                    self.game_state,
                    {
                        "type": "charge",
                        "message": (
                            f"Unit {squad_id} CHARGED{_charge_rule_marker} "
                            f"Unit {target_squad_id} - Roll:{charge_roll}"
                        ),
                        "turn": require_key(self.game_state, "turn"),
                        "phase": "charge",
                        "unitId": squad_id,
                        "player": require_key(unit, "player"),
                        "targetId": target_squad_id,
                        "charge_roll": charge_roll,
                        "fromCol": _charge_from[0] if _charge_from else None,
                        "fromRow": _charge_from[1] if _charge_from else None,
                        "toCol": int(_dest_uc["col"]) if "col" in _dest_uc else None,
                        "toRow": int(_dest_uc["row"]) if "row" in _dest_uc else None,
                        "targetCol": _charge_target[0] if _charge_target else None,
                        "targetRow": _charge_target[1] if _charge_target else None,
                        "is_fly_move": _charge_is_fly,
                        # JUMEAU de `is_fly_move` : `step_logger` réécrit la ligne de charge et
                        # n'y pose le token de capacité que depuis ce champ. Sans lui, une charge
                        # après Advance permise par le Waaagh! n'était nommée nulle part côté IA.
                        "ability_display_name": _charge_ability,
                        "timestamp": "server_time",
                        "reward": 0.0,
                    },
                )
                result = {
                    **end_result,
                    "action": "squad_charge",
                    "squad_id": squad_id,
                    "target_squad_id": target_squad_id,
                    "charge_roll": charge_roll,
                    "charge_succeeded": True,
                }

        # ── combat ────────────────────────────────────────────────────────────
        elif action_name == "squad_fight":
            squad_id = str(semantic["squad_id"])
            units_cache = require_key(self.game_state, "units_cache")
            cache_entry = units_cache.get(squad_id)
            if cache_entry is None:
                raise KeyError(f"Squad {squad_id} absent de units_cache pour squad_fight")

            # `squad_fight` = UNE selection de l etape FIGHT (12.04), rien d autre. Le PILE IN
            # groupe (12.02) et la CONSOLIDATION groupee (12.07) encadrent l etape et sont
            # resolus par `_fight_v11_gym_settle`. Cette repartition est ce qui rend l ordre de
            # la phase conforme : 12.02 exige que TOUS les pile-in des DEUX joueurs precedent le
            # premier combat, et 12.04 date son snapshot d eligibilite du debut de l etape FIGHT.
            # L ancien code resolvait pile-in + fight + consolidation par escouade, en une passe,
            # sans jamais avancer la machine V11 : l ordre etait faux ET aucun etat n etait pose.
            sub = require_key(self.game_state, "fight_subphase")
            if sub != "fight":
                raise RuntimeError(
                    f"squad_fight recu en sous-phase {sub!r} : la machine V11 n a pas ete "
                    f"deroulee jusqu a l etape FIGHT — `_fight_v11_gym_settle` manque sur le "
                    f"chemin d entree en phase fight"
                )

            # Convergence §9.4b-1 : resolution combat via le moteur d allocation par-figurine
            # (groupes 05.03/05.04, T bodyguard 19.02, save par-fig allouee). Defenseur IA
            # garanti en training -> auto_decider headless -> resolution complete (done).
            from engine.phase_handlers.fight_handlers import (
                build_manual_fight_allocation,
                _fight_build_valid_target_pool,
                _fight_v11_register_selection,
                fight_v11_current_pool,
            )
            # OVERRUN FIGHT 12.06 (pile-in additionnel de reengagement) NON implemente ici :
            # il n existe qu en modele par-ANCRE (_fight_v11_auto_overrun_pile_in), condamne par
            # la decision « le pile-in de reference est le par-figurine du PvP ». 12.06 dit
            # « CAN make one additional pile-in move » -> optionnel, son absence ne viole rien :
            # l escouade non engagee resout un fight « a vide » (0 attaque). A implementer en
            # par-figurine : Documentation/Implémentation/A_faire/pile_in_overrun_par_figurine.md

            # Parite masque/commit : le masque gym derive du MEME pool 12.04 (action_decoder ->
            # fight_v11_current_pool). Un squad hors pool est une rupture, pas un cas a absorber.
            pool = fight_v11_current_pool(self.game_state)
            if squad_id not in pool:
                raise ValueError(
                    f"squad_fight: squad {squad_id} hors du pool de selection 12.04 {pool} "
                    f"(rupture masque/commit)"
                )
            unit = get_unit_by_id(squad_id, self.game_state)
            if unit is None:
                raise KeyError(f"Squad {squad_id} introuvable pour squad_fight")

            # Ordre du flux PvP (`_fight_v11_auto_step`) : marquer « selected to fight » AVANT de
            # resoudre. C est ce marquage qui interdit a une escouade de combattre deux fois dans
            # la phase (12.04, « has not already been selected to fight this phase ») et qui ouvre
            # son eligibilite a la consolidation (12.08, « was eligible to fight this phase »).
            _fight_v11_register_selection(self.game_state, squad_id)

            # Prédicat de cible = celui du flux PvP (_fight_v11_resolve_attacks) : pool
            # d ennemis en zone d engagement (12.05), pas le mapping de slots gele du tir.
            # Pool vide = fight « a vide » (12.04 : une unite qui a charge reste eligible
            # meme si sa cible est morte -> overrun 12.06 sans cible). Le PvP le resout en
            # 0 attaque ; le gym en fait autant, via le MEME moteur (0 intent declare ->
            # summary vide, done=True). Aucun dict fabrique a la main.
            targets = [str(t) for t in _fight_build_valid_target_pool(self.game_state, unit)]

            # V11 §9 P3-1 : la cible est CHOISIE PAR L AGENT, via le slot ennemi porte par
            # l action. `_ai_select_fight_target` ne tranche plus rien ici — elle reste vive pour
            # le flux PvP (clic sans cible) et pour les bots, jamais pour le pipeline gym.
            # Parite masque/commit, dans les DEUX sens : le masque n ouvre un slot que si sa cible
            # est dans le pool 12.05, et n ouvre `FIGHT_NO_TARGET` que si le pool est vide. Toute
            # divergence est une rupture, pas un cas a absorber par un repli sur une heuristique.
            if "target_slot" in semantic:
                if not targets:
                    raise ValueError(
                        f"squad_fight: slot de cible recu pour squad {squad_id} alors que le pool "
                        f"12.05 est VIDE (rupture masque/commit)"
                    )
                target_slot = int(semantic["target_slot"])
                enemy_slot_ids = get_enemy_slot_mapping(
                    self.game_state, int(require_key(cache_entry, "player"))
                )
                if not (0 <= target_slot < len(enemy_slot_ids)):
                    raise ValueError(
                        f"squad_fight: target_slot {target_slot} hors du mapping de slots ennemis "
                        f"({len(enemy_slot_ids)} slots)"
                    )
                best_target_id = enemy_slot_ids[target_slot]
                if best_target_id is None or str(best_target_id) not in targets:
                    raise ValueError(
                        f"squad_fight: slot {target_slot} -> cible {best_target_id!r} hors du pool "
                        f"de combat 12.05 {targets} pour squad {squad_id} (rupture masque/commit)"
                    )
                best_target_id = str(best_target_id)
            else:
                if targets:
                    raise ValueError(
                        f"squad_fight: action « combat a vide » recue pour squad {squad_id} alors "
                        f"que le pool 12.05 offre {targets} (rupture masque/commit)"
                    )
                best_target_id = None

            squad_fight_restart_activation(self.game_state, squad_id)
            if best_target_id is not None:
                squad_declare_fight(self.game_state, squad_id, best_target_id)
            _fight_alloc = build_manual_fight_allocation(self.game_state, squad_id)
            if not _fight_alloc.get("done"):
                raise RuntimeError(
                    f"squad_fight: allocation combat non terminee en auto pour squad {squad_id} "
                    f"(defenseur non-IA ?) — action={_fight_alloc.get('action')}"
                )
            fight_result = _fight_alloc["shoot_result"]

            unit = get_unit_by_id(squad_id, self.game_state)
            if unit is None:
                raise KeyError(f"Squad {squad_id} introuvable après combat")
            end_result = end_activation(self.game_state, unit, ACTION, 1, FIGHT, FIGHT, 0)
            # `end_activation` derive son `phase_complete` des pools V10 (charging/alternating)
            # que `fight_phase_start` V11 ne construit plus : toujours vides -> toujours True.
            # Signal mort d un sous-systeme retire. Il etait deja inerte avant ce fix (aucun
            # `next_phase` ne l accompagne, donc aucune cascade) ; on l ecarte pour ne pas le
            # laisser mentir sur l etat de la phase, dont l autorite est la machine V11.
            end_result.pop("phase_complete", None)
            result = {
                **end_result,
                "action": "squad_fight",
                "squad_id": squad_id,
                "target_squad_id": best_target_id,
                "fight_result": fight_result,
            }
            # Draine l etape FIGHT si plus personne n est selectionnable, puis la CONSOLIDATION
            # groupee (12.07) : le prochain masque reflete l etat reel de la machine.
            self._fight_v11_gym_settle()

        else:
            return False, {"error": "unknown_squad_action", "action": action_name}

        # ── cascade : auto-avance les phases vides ────────────────────────────
        max_cascade = 10
        cascade_count = 0
        started_phases: List[str] = []
        while (
            success
            and result.get("phase_complete")
            and result.get("next_phase")
            and cascade_count < max_cascade
        ):
            next_phase = result["next_phase"]
            current_phase = self.game_state.get("phase", "unknown")
            cascade_count += 1
            if next_phase == current_phase:
                break
            add_console_log(
                self.game_state,
                f"🔄 PHASE TRANSITION: {current_phase} -> {next_phase} (cascade #{cascade_count})",
            )
            phase_init_result = None
            if next_phase == "deployment":
                phase_init_result = deployment_handlers.deployment_phase_start(self.game_state)
            elif next_phase == "command":
                phase_init_result = self.start_command_phase()
                self._clear_turn_scoped_rule_choices()
            elif next_phase == "shoot":
                phase_init_result = shooting_handlers.shooting_phase_start(self.game_state)
                self._shooting_phase_initialized = True
            elif next_phase == "charge":
                phase_init_result = charge_handlers.charge_phase_start(self.game_state)
            elif next_phase == "fight":
                phase_init_result = fight_handlers.fight_phase_start(self.game_state)
                phase_init_result = self._fight_v11_gym_after_phase_start(phase_init_result)
            elif next_phase == "move":
                phase_init_result = movement_handlers.movement_phase_start(self.game_state)
            started_phases.append(next_phase)
            if phase_init_result and phase_init_result.get("phase_complete") and phase_init_result.get("next_phase"):
                result = phase_init_result
            else:
                break

        # ── game_over / winner ────────────────────────────────────────────────
        self.game_state["game_over"] = self._check_game_over()
        if self.game_state["game_over"]:
            winner, win_method = self._determine_winner_with_method()
            self.game_state["winner"] = winner
            result["game_over"] = True
            result["winner"] = winner
            if win_method is not None:
                result["win_method"] = win_method

        # ── rule choices post-transition ──────────────────────────────────────
        if success:
            current_player_for_event = int(require_key(self.game_state, "current_player"))
            if result.get("action") == "deploy_unit" and result.get("unitId") is not None:
                deployed_unit_id = str(result["unitId"])
                deployed_unit = self._get_unit_by_id(deployed_unit_id)
                deployed_player = (
                    int(require_key(deployed_unit, "player"))
                    if deployed_unit is not None
                    else current_player_for_event
                )
                self._enqueue_rule_choice_candidates(
                    trigger="on_deploy",
                    activation_unit_id=deployed_unit_id,
                    event_player=deployed_player,
                )
            for started_phase in started_phases:
                if started_phase == "command":
                    self._enqueue_rule_choice_candidates(
                        trigger="turn_start",
                        event_phase=started_phase,
                        event_player=current_player_for_event,
                    )
                    self._enqueue_rule_choice_candidates(
                        trigger="player_turn_start",
                        event_phase=started_phase,
                        event_player=current_player_for_event,
                    )
                self._enqueue_rule_choice_candidates(
                    trigger="phase_start",
                    event_phase=started_phase,
                    event_player=current_player_for_event,
                )
            choice_prompt_result = self._emit_next_rule_choice_prompt_if_needed()
            if choice_prompt_result is not None:
                return True, choice_prompt_result

        return success, result

    # ============================================================================
    # PHASE PROCESSING - KEEP THESE (They delegate to phase_handlers)
    # ============================================================================

    def _process_movement_phase(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """AI_MOVE.md EXACT: Pure engine orchestration - handler manages everything"""
        
        # Get current unit for handler (handler expects unit parameter)
        unit_id = action.get("unitId")
        current_unit = None
        if unit_id:
            current_unit = self._get_unit_by_id(unit_id)

        # **FULL DELEGATION**: movement_handlers.execute_action(game_state, unit, action, config)
        success, result = movement_handlers.execute_action(self.game_state, current_unit, action, self.config)
        
        # DEBUG: Check if unit position actually changed
        if success and action.get("action") == "move":
            unit_id = action.get("unitId")
            if unit_id:
                unit = self._get_unit_by_id(unit_id)
                if unit:
                    # CRITICAL: No default values - require explicit coordinates for debug check
                    if "destCol" in action and "destRow" in action:
                        expected_col = action["destCol"]
                        expected_row = action["destRow"]
                        unit_col, unit_row = require_unit_position(unit, self.game_state)
                        expected_col_int, expected_row_int = normalize_coordinates(expected_col, expected_row)
                        if expected_col_int == unit_col and expected_row_int == unit_row:
                            pass
                    # If destCol/destRow missing, skip debug check (not an error, just incomplete debug data)
        
        # CRITICAL: No workaround for invalid_destination - let error propagate
        # If destination is invalid, the error should be raised, not masked by auto-skip
        # The agent should learn not to select invalid destinations
        
        # Check response for phase_complete flag
        if result.get("phase_complete"):
            from engine.phase_handlers import movement_handlers as _mh_phase_end
            _mh_phase_end.movement_phase_end(self.game_state)
            self._movement_phase_initialized = False
            self._shooting_phase_initialized = False
            # Gym / RL: keep move + shooting init in one step (same as before).
            # PvP / human API: defer shooting_phase_start to a second request so the last move
            # returns quickly; client calls advance_phase from "move" to run cascade (shoot init).
            if getattr(self, "gym_training_mode", False):
                init_result = self._shooting_phase_init()
                if init_result.get("phase_complete"):
                    if "next_phase" not in init_result:
                        raise KeyError("shooting_phase_start returned phase_complete without next_phase")
                    result.update(init_result)
                    result["phase_transition"] = True
                    result["next_phase"] = init_result["next_phase"]
                else:
                    result["phase_transition"] = True
                    result["next_phase"] = "shoot"
            else:
                self.game_state["pending_shooting_phase_init"] = True
                result["pending_shooting_phase_init"] = True
                result["phase_transition"] = False
                if "next_phase" in result:
                    del result["next_phase"]

        return success, result
    
    
    def _process_shooting_phase(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        AI_TURN.md EXACT: Pure delegation - handler manages complete phase lifecycle
        """
        from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

        _pw = perf_timing_enabled(self.game_state)
        _t_wrap0 = time.perf_counter() if _pw else None
        _phase_start_called = False
        _t_ps0: Optional[float] = None
        _t_ps1: Optional[float] = None

        # Align with MOVE phase: initialize shooting phase once per phase
        if not getattr(self, "_shooting_phase_initialized", False):
            _phase_start_called = True
            _t_ps0 = time.perf_counter()
            shooting_handlers.shooting_phase_start(self.game_state)
            self._shooting_phase_initialized = True
            _t_ps1 = time.perf_counter()
        # Tir PvP humain par figurine : pipeline squad (shared_utils), pas le legacy mono-fig.
        if action.get("action") in (
            "squad_shoot_activate", "squad_select_weapon", "squad_shoot_select_model",
            "squad_shoot_assign", "squad_shoot_unassign", "squad_shoot_validate", "squad_shoot_cancel",
            "squad_shoot_assign_weapon", "squad_shoot_unassign_weapon", "squad_shoot_weapon_targets",
            "squad_shoot_allocate_model", "squad_shoot_declare_order", "squad_shoot_los_overview",
            "squad_shoot_assign_weapon_qty", "squad_shoot_unassign_weapon_qty",
            "squad_shoot_weapon_qty_max", "squad_shoot_weapons_for_target",
            "squad_shoot_eligible_models", "squad_shoot_toggle_model_weapon",
            "squad_shoot_models_status", "squad_shoot_models_weapons",
            "squad_shoot_menu_weapons",
        ):
            return self._process_squad_manual_shoot(action)
        # Pure delegation - handler manages initialization, player progression, everything
        _t_ex0 = time.perf_counter() if _pw else None
        handler_response = shooting_handlers.execute_action(self.game_state, None, action, self.config)
        _t_ex1 = time.perf_counter() if _pw and _t_ex0 is not None else None
        if isinstance(handler_response, tuple) and len(handler_response) == 2:
            success, result = handler_response
        else:
            # Handler returned non-tuple or wrong tuple length
            success = True
            result: Dict[str, Any] = handler_response if isinstance(handler_response, dict) else {"error": "invalid_handler_response"}
        
        _t_pe0: Optional[float] = None
        _t_pe1: Optional[float] = None
        # Check response for phase_complete flag (aligned with MOVE phase)
        if result.get("phase_complete"):
            _t_pe0 = time.perf_counter() if _pw else None
            self._shooting_phase_initialized = False
            # Call shooting_phase_end to get next_phase and all_attack_results (like MOVE calls _shooting_phase_init)
            phase_end_result = shooting_handlers.shooting_phase_end(self.game_state)
            # Merge phase transition data into result
            result.update(phase_end_result)
            result["phase_transition"] = True
            # CRITICAL: Preserve all_attack_results if already set (for logging)
            if "all_attack_results" in result and result["all_attack_results"]:
                # Keep existing all_attack_results (from handler)
                pass
            elif "all_attack_results" in phase_end_result:
                # Use all_attack_results from phase_end_result
                result["all_attack_results"] = phase_end_result["all_attack_results"]
            if _pw and _t_pe0 is not None:
                _t_pe1 = time.perf_counter()

        if _pw and _t_wrap0 is not None:
            _t_wrap1 = time.perf_counter()
            ep = self.game_state.get("episode_number", "?")
            trn = self.game_state.get("turn", "?")
            act = action.get("action")
            uid = action.get("unitId", "?")
            ps_s = (_t_ps1 - _t_ps0) if _t_ps0 is not None and _t_ps1 is not None else 0.0
            ex_s = (_t_ex1 - _t_ex0) if _t_ex0 is not None and _t_ex1 is not None else 0.0
            pe_s = (_t_pe1 - _t_pe0) if _t_pe0 is not None and _t_pe1 is not None else 0.0
            total_s = _t_wrap1 - _t_wrap0
            append_perf_timing_line(
                f"SHOOT_PHASE_HANDLER episode={ep} turn={trn} action={act!r} unitId={uid} "
                f"shooting_phase_start_called={int(_phase_start_called)} shooting_phase_start_s={ps_s:.6f} "
                f"execute_action_s={ex_s:.6f} phase_end_s={pe_s:.6f} total_handler_s={total_s:.6f}"
            )

        return success, result
    
    
    def _process_charge_phase(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """AI_TURN.md EXACT: Pure delegation - handler manages complete charge phase."""
        # Get current unit for handler
        unit_id = action.get("unitId")
        current_unit = None
        if unit_id:
            current_unit = self._get_unit_by_id(unit_id)

        # Full delegation to charge_handlers
        handler_response = charge_handlers.execute_action(self.game_state, current_unit, action, self.config)
        if isinstance(handler_response, tuple) and len(handler_response) == 2:
            success, result = handler_response
            return success, result
        else:
            return True, handler_response

    def _record_zone_intent_declaration(self) -> None:
        """Fige les intents declares CE tour et le controle d'objectif au moment du choix.

        Le controle est memorise ici et non relu au solde : le shaping compare l'etat VISE a
        l'etat OBTENU, et l'etat vise n'existe plus une fois le tour joue. Une declaration par
        joueur — les deux camps traversent ce code en self-play, et solder celle du mauvais
        joueur verserait le shaping de l'adversaire dans la recompense de l'agent.
        """
        current_player = int(require_key(self.game_state, "current_player"))
        zone_intents = require_key(self.game_state, "zone_intents")
        declarations = require_key(self.game_state, "_zone_intent_declarations")
        declarations[current_player] = {
            "turn": self.game_state["turn"],
            "intents": list(zone_intents),
            "control": [
                get_objective_control_for_player(zone_idx, self.game_state, current_player)
                for zone_idx in range(len(zone_intents))
            ],
        }

    def settle_pending_zone_intent_declaration(self, player: int) -> float:
        """Solde la declaration de `player` et rend le shaping du, 0.0 s'il n'y en a pas.

        Appelee a l'OUVERTURE de la command phase du joueur (command_handlers), donc apres que
        la frontiere de tour a rafraichi ``objective_controllers`` (14.02) : le controle lu est
        bien celui OBTENU pendant le tour ecoule. C'est aussi le seul instant ou l'on est sur
        que la prochaine action jouee sera celle du declarant, donc que le shaping ira dans SA
        recompense — un solde a la frontiere de tour elle-meme tomberait sur le step de
        l'adversaire.

        Point de solde independant de la declaration : un joueur qui ne joue aucun free step un
        tour laisse quand meme sa declaration precedente se solder ici.
        """
        declarations = require_key(self.game_state, "_zone_intent_declarations")
        declaration = declarations.pop(int(player), None)
        if declaration is None:
            return 0.0
        return self.reward_calculator.settle_zone_intent_declaration(
            self.game_state, declaration, int(player)
        )

    #: Verbes que la phase de commandement accepte, et les SEULS. `zone_intent` joue un free
    #: step (gym), `skip` sort de la phase — c'est ce que `command_wait` envoie, et le seul
    #: chemin de sortie qui atteigne ce handler (`advance_phase` est intercepté en amont, dans
    #: les deux points d'entrée). Tout autre verbe était traité comme une « sortie volontaire »
    #: et terminait la phase : un `activate_unit` sur une unité ADVERSE, ou un verbe hors
    #: vocabulaire, la faisaient basculer vers le move en rendant `success: True`.
    COMMAND_PHASE_ACTIONS = frozenset({"zone_intent", "skip"})

    def _process_command_phase(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Process command phase actions."""
        # Vocabulaire validé AVANT le solde et avant la consommation des free steps : un refus
        # doit être inerte, et le solde de la déclaration du tour précédent n'a pas à être
        # déclenché par une action que la phase n'accepte pas.
        action_name = action.get("action")
        if action_name not in self.COMMAND_PHASE_ACTIONS:
            return False, {
                "error": "invalid_action_for_phase",
                "action": action_name,
                "phase": "command",
            }

        # SOLDE de la declaration du tour precedent, avant tout traitement d'action.
        #
        # Ici et pas a la frontiere de tour : a cet instant le controle d'objectif a deja ete
        # rafraichi par la frontiere (14.02), et l'action en cours est celle du declarant — donc
        # `_pending_zone_shaping` ira dans SA recompense. Solder a la frontiere elle-meme le
        # ferait tomber sur le step de l'adversaire.
        #
        # `zone_intent_free_steps_remaining` PLEIN est le marqueur d'un tour dont aucun intent
        # n'a encore ete joue (command_phase_start vient de le remettre a MAX_OBJECTIVES) : le
        # solde a donc lieu exactement une fois par command phase, que l'agent enchaine des free
        # steps ou sorte immediatement, et meme s'il n'en joue aucun.
        if self.game_state["zone_intent_free_steps_remaining"] == MAX_OBJECTIVES:
            pending = self.settle_pending_zone_intent_declaration(
                int(require_key(self.game_state, "current_player"))
            )
            if pending != 0.0:
                self.game_state["_pending_zone_shaping"] = (
                    require_key(self.game_state, "_pending_zone_shaping") + pending
                )

        # Phase 2: handle zone intent free step actions
        if action.get("action") == "zone_intent":
            zone_idx = action["zone_idx"]
            intent_value = action["intent_value"]

            free_steps = self.game_state["zone_intent_free_steps_remaining"]
            if free_steps <= 0:
                # Guard: mask should have prevented this, but be explicit
                return False, {
                    "action": "invalid",
                    "error": "zone_intent_action_but_no_free_steps_remaining",
                    "zone_idx": zone_idx,
                    "intent_value": intent_value,
                }

            zone_intents = self.game_state["zone_intents"]
            if zone_idx >= len(zone_intents):
                return False, {
                    "action": "invalid",
                    "error": f"zone_idx {zone_idx} out of range (len={len(zone_intents)})",
                }

            # Etat de controle de l'objectif AU MOMENT du choix : c'est l'axe que
            # `settle_zone_intent_declaration` recompense, donc le seul axe sur lequel mesurer si la
            # tete zone-intent conditionne sa decision. Publie dans l'info, jamais compte ici :
            # les metriques ont un ecrivain unique, le callback d'entrainement.
            zone_control = get_objective_control(zone_idx, self.game_state)

            zone_intents[zone_idx] = intent_value
            self.game_state["zone_intent_free_steps_remaining"] = free_steps - 1

            if self.game_state["zone_intent_free_steps_remaining"] == 0:
                # Cap epuise : la declaration est close, on l'enregistre. Elle sera SOLDEE au
                # tour suivant du meme joueur, contre le controle obtenu entre-temps.
                self._record_zone_intent_declaration()

            # Return without phase_complete — env re-demande une action (free step)
            return True, {
                "action": "zone_intent",
                "zone_idx": zone_idx,
                "intent_value": intent_value,
                "zone_control": zone_control,
                "zone_intent_free_steps_remaining": self.game_state["zone_intent_free_steps_remaining"],
            }

        # Non-zone-intent action in command phase: exit free steps
        free_steps = self.game_state["zone_intent_free_steps_remaining"]
        if free_steps > 0:
            # Sortie volontaire : n'enregistrer une declaration que si un intent a ete joue.
            intents_played = MAX_OBJECTIVES - free_steps
            if intents_played > 0:
                self._record_zone_intent_declaration()
            self.game_state["zone_intent_free_steps_remaining"] = 0

        unit_id = action.get("unitId")
        current_unit = None
        if unit_id:
            current_unit = self._get_unit_by_id(unit_id)

        success, result = command_handlers.execute_action(self.game_state, current_unit, action, self.config)
        return success, result
    
    def _process_fight_phase(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """AI_TURN.md EXACT: Pure delegation - handler manages complete fight phase.

        Y compris le combat PvP humain cible-d abord par arme/quantite/figurine : ces
        actions squad_fight_* sont traitees DANS la machine V11 (_fight_v11_manual_step),
        pas ici — le garde-fou d allocation les protege donc automatiquement.
        """
        # Get current unit for handler
        unit_id = action.get("unitId")
        current_unit = None
        if unit_id:
            current_unit = self._get_unit_by_id(unit_id)

        # Full delegation to fight_handlers
        handler_response = fight_handlers.execute_action(self.game_state, current_unit, action, self.config)
        if isinstance(handler_response, tuple) and len(handler_response) == 2:
            success, result = handler_response
            return success, result
        else:
            return True, handler_response

    # ============================================================================
    # PHASE INITIALIZATION - KEEP THESE (Handler delegation)
    # ============================================================================
    
    def _shooting_phase_init(self):
        """AI_SHOOT.md EXACT: Pure delegation to handler"""
        # Handler manages everything including phase setting and pool building
        result = shooting_handlers.shooting_phase_start(self.game_state)
        self._shooting_phase_initialized = True
        return result
    
    
    def _tracking_cleanup(self):
        """Clear tracking sets at the VERY BEGINNING of movement phase."""
        self.game_state["units_moved"] = set()
        self.game_state["moved_distance_by_model"] = {}
        self.game_state["units_fled"] = set()
        self.game_state["units_cannot_charge"] = set()
        self.game_state["units_shot"] = set()
        self.game_state["units_charged"] = set()
        self.game_state["units_fought"] = set()
        self.game_state["move_activation_pool"] = []
    
    
    # ============================================================================
    # HELPER METHODS - KEEP THESE SIMPLE ONES
    # ============================================================================
    
    def _get_unit_by_id(self, unit_id: str) -> Optional[Dict[str, Any]]:
        """Get unit by ID from game state - delegates to module utility."""
        return get_unit_by_id(unit_id, self.game_state)
    
    
    def _check_game_over(self) -> bool:
        """Check if game is over - turn limit reached."""
        # Check turn limit first
        if turn_limit_reached(self.game_state):
            # CRITICAL: Flag turn limit reached for winner determination
            self.game_state["turn_limit_reached"] = True
            return True
        if require_key(self.game_state, "turn_limit_reached"):
            return True
        return False
    
    
    def _determine_winner(self) -> Optional[int]:
        """Determine winner - delegates to state_manager for full victory logic."""
        return self.state_manager.determine_winner(self.game_state)

    def _determine_winner_with_method(self) -> tuple:
        """Determine winner AND win method - delegates to state_manager."""
        return self.state_manager.determine_winner_with_method(self.game_state)
    
    
    def _get_action_phase_for_logging(self, action_type: str) -> str:
        """Map action types to their logical phases for step logging."""
        action_phase_map = {
            "move": "move",
            "shoot": "shoot", 
            "charge": "charge",
            "combat": "fight",
            "fight": "fight",
            "wait": "move",  # CHANGE 10: Wait actions happen during move phase
            "skip": self.game_state["phase"]  # Use current phase for skip (legacy)
        }
        return action_phase_map.get(action_type, self.game_state["phase"])
    
    
    def validate_compliance(self) -> List[str]:
        """Validate AI_TURN.md compliance - returns list of violations."""
        violations = []
        
        # Check single source of truth
        if not hasattr(self, 'game_state'):
            violations.append("Missing single game_state object")
        
        # Check UPPERCASE fields
        for unit in self.game_state["units"]:
            if "HP_CUR" not in unit or "RNG_ATK" not in unit:
                violations.append(f"Unit {unit['id']} missing UPPERCASE fields")
        
        # Check tracking sets are sets
        # `units_fought` n'est PAS de la liste : contrairement aux quatre autres, il n'est pas posé
        # par `reset()` mais par `command_phase_start` (invariant documenté par
        # `tests/_state_invariants.py`). L'exiger ici ferait lever sur un état pourtant valide.
        tracking_fields = ["units_moved", "units_fled", "units_shot", "units_charged"]
        for field in tracking_fields:
            if not isinstance(self.game_state[field], set):
                violations.append(f"{field} must be set type, got {type(self.game_state[field])}")
        
        return violations
    
    
    # ============================================================================
    # DELEGATED METHODS - NOW CALL MODULE METHODS
    # ============================================================================
    
    def get_action_mask(self) -> np.ndarray:
        """Get valid action mask. Auto-advances phase when mask is empty (e.g. fight with empty pools)."""
        action_mask, _ = self.action_decoder.get_squad_action_mask_and_eligible_units(self.game_state)
        while not np.any(action_mask) and not self.game_state.get("game_over", False):
            current_phase = self.game_state.get("phase")
            if current_phase == "fight":
                from engine.phase_handlers import fight_handlers
                fight_handlers.fight_phase_end(self.game_state)
            else:
                break
            self.game_state["game_over"] = self._check_game_over()
            action_mask, _ = self.action_decoder.get_squad_action_mask_and_eligible_units(self.game_state)
        return action_mask
    
    
    OBJECTIVE_CONTROL_LOGGED_KEY = "_objective_control_last_logged"

    def _log_objective_control_snapshot_if_changed(self) -> None:
        """Journalise dans step.log l'etat de partie du moteur (controleurs, VP, CP) quand il CHANGE.

        POURQUOI : le replay affichait un controle d'objectif RECALCULE dans le navigateur
        (`BoardReplay.tsx`), par ancre d'escouade et sans le battle-shock — deux ecarts
        irrattrapables cote client (l'empreinte de socle et le drapeau `battle_shocked` n'existent
        pas dans le step.log), donc des points de victoire affiches differents de ceux attribues.
        Il lit desormais CET instantane, seul etat faisant foi.

        Declenchement sur CHANGEMENT plutot qu'a la seule frontiere de phase : le controle bouge a
        la frontiere (`refresh_objective_control_on_boundary`, juste au-dessus) mais les points de
        victoire bougent DANS les handlers (`apply_primary_objective_scoring`, phases command et
        fight). Un declencheur unique manquerait l'un ou l'autre.
        """
        step_logger = getattr(self, "step_logger", None)
        if step_logger is None or not step_logger.enabled:
            return
        objectives = self.game_state.get("objectives")  # get allowed : scenario sans objectif
        if not objectives:
            return
        controllers = require_key(self.game_state, "objective_controllers")
        victory_points = require_key(self.game_state, "victory_points")
        # Les CP entrent dans la CLE de deduplication, pas seulement dans la ligne : sinon un
        # gain de CP sans changement de controle ni de VP (08.02, chaque phase de commandement)
        # ne serait jamais journalise, et le replay afficherait un stock fige.
        command_points = require_key(self.game_state, "command_points")
        snapshot = (
            tuple(sorted((str(k), v) for k, v in controllers.items())),
            require_key(victory_points, 1),
            require_key(victory_points, 2),
            require_key(command_points, 1),
            require_key(command_points, 2),
        )
        # get allowed : absent au tout premier passage de l'episode (cle purgee au reset)
        if snapshot == self.game_state.get(self.OBJECTIVE_CONTROL_LOGGED_KEY):
            return
        self.game_state[self.OBJECTIVE_CONTROL_LOGGED_KEY] = snapshot
        step_logger.log_objective_control_snapshot(
            require_key(self.game_state, "turn"),
            objectives,
            controllers,
            victory_points,
            command_points,
        )

    #: Dernier tour pour lequel l'instantané d'état a été écrit (déduplication).
    STATE_SNAPSHOT_LOGGED_KEY = "_state_snapshot_logged_turn"

    #: Dernier instantané d'EFFETS écrit (déduplication : la ligne n'est réécrite qu'au
    #: CHANGEMENT, comme l'instantané de contrôle d'objectif).
    EFFECTS_SNAPSHOT_LOGGED_KEY = "_effects_snapshot_last_logged"

    #: Curseur PERSISTANT du drainage vers le StepLogger : index de la première entrée de
    #: `action_logs` pas encore écrite. Empêche qu'un drainage imbriqué (`advance_phase`) et le
    #: drainage englobant du step réécrivent les mêmes lignes.
    STEP_LOG_DRAINED_KEY = "_step_log_drained_upto"

    def _log_state_snapshot_if_turn_changed(self) -> None:
        """Écrit UNE ligne d'état par tour : socles vivants, positions, hauteurs, PV.

        Le raisonnement complet est dans `StepLogger.log_state_snapshot`. En deux mots : tout
        lecteur du journal reconstruit l'état par accumulation d'événements et n'avait AUCUN
        point de correction ; une donnée manquante dérivait jusqu'à la fin de l'épisode.

        MÊME SOURCE que le segment `[MODELS:]` des lignes d'action (`occupied_hexes_by_model` /
        `floor_height_by_model` de `units_cache`, plus `HP_CUR` de `models_cache`) : deux sources
        parallèles finiraient par diverger, et c'est justement une divergence qu'on veut pouvoir
        MESURER — pas en fabriquer une nouvelle.

        Une figurine absente de `models_cache` est morte : elle n'apparaît pas. Une unité sans
        figurine vivante n'apparaît pas non plus. L'absence EST la mort ; il n'y a donc aucun
        drapeau « vivant/mort » à accorder avec les positions.

        Déclenchement au CHANGEMENT DE TOUR et non à chaque frontière de phase : une ligne par
        tour suffit à borner la dérive, et coûte ~3 000 lignes sur un run de 600 épisodes.
        """
        step_logger = getattr(self, "step_logger", None)
        if step_logger is None or not step_logger.enabled:
            return
        turn = require_key(self.game_state, "turn")
        # get allowed : absent au tout premier passage de l'épisode (clé purgée au reset).
        if self.game_state.get(self.STATE_SNAPSHOT_LOGGED_KEY) == turn:
            return
        self.game_state[self.STATE_SNAPSHOT_LOGGED_KEY] = turn

        units_cache = require_key(self.game_state, "units_cache")
        models_cache = require_key(self.game_state, "models_cache")
        units_state: List[Tuple[str, List[Tuple[str, int, int, float, int]]]] = []
        for uid, entry in units_cache.items():
            by_model = entry.get("occupied_hexes_by_model")  # get allowed
            if not isinstance(by_model, dict) or not by_model:
                continue
            floors = require_key(entry, "floor_height_by_model")
            models: List[Tuple[str, int, int, float, int]] = []
            for mid, pos in by_model.items():
                model = models_cache.get(str(mid))  # get allowed : figurine détruite
                if model is None:
                    continue
                models.append((
                    str(mid), int(pos[0]), int(pos[1]),
                    float(require_key(floors, mid)), int(require_key(model, "HP_CUR")),
                ))
            if models:
                units_state.append((str(uid), models))
        step_logger.log_state_snapshot(turn, units_state)

    def _log_effects_snapshot_if_changed(self) -> None:
        """Journalise les effets de règle EN VIGUEUR, avec leur contribution chiffrée.

        Le raisonnement complet est dans `StepLogger.log_effects_snapshot`. En deux mots : une
        capacité d'ARMÉE (Waaagh! 24, Oath of Moment 08.04) est vraie pour un joueur pendant un
        tour ; la recopier en token sur chaque ligne d'attaque obligeait chaque lecteur à la
        re-dériver, et à RÉ-ENCODER la règle pour en connaître l'effet.

        DÉCLENCHEMENT AU CHANGEMENT, pas à la frontière de tour : le Waaagh se déclare en phase
        de commandement, donc au milieu du tour. Même parti que
        `_log_objective_control_snapshot_if_changed`, dont les VP bougent aussi dans les handlers.

        Les VALEURS viennent des constantes du moteur (`WAAAGH_MELEE_BONUS`, `WAAAGH_INVUL_SAVE`,
        `OATH_WOUND_ROLL_BONUS`) : le journal dit ce que le moteur a appliqué, il ne le
        redécrit pas. Un lecteur qui coderait « waaagh ⇒ +1 » en dur ferait vivre une seconde
        définition de la règle, qui divergerait en silence le jour où la première bouge.
        """
        step_logger = getattr(self, "step_logger", None)
        if step_logger is None or not step_logger.enabled:
            return
        from engine.game_state import (
            OATH_WOUND_ROLL_BONUS,
            WAAAGH_INVUL_SAVE,
            WAAAGH_MELEE_BONUS,
            oath_target_id,
            waaagh_is_active,
        )

        effects_by_player: List[Tuple[int, List[Tuple[str, Any]]]] = []
        for player in (1, 2):
            entries: List[Tuple[str, Any]] = []
            if waaagh_is_active(self.game_state, player):
                # Les deux moitiés de la règle sont écrites SÉPARÉMENT bien qu'elles partagent
                # une constante : un lecteur qui ne s'intéresse qu'aux attaques ne doit pas avoir
                # à savoir que la Force suit. C'est aussi ce qui rend le +1 Force attribuable —
                # il n'était représenté nulle part.
                entries.append(("waaagh", "on"))
                entries.append(("waaagh_melee_str", f"+{WAAAGH_MELEE_BONUS}"))
                entries.append(("waaagh_melee_atk", f"+{WAAAGH_MELEE_BONUS}"))
                entries.append(("waaagh_invul", WAAAGH_INVUL_SAVE))
            _oath = oath_target_id(self.game_state, player)
            if _oath is not None:
                entries.append(("oath_target", _oath))
                entries.append(("oath_wound", f"+{OATH_WOUND_ROLL_BONUS}"))
            effects_by_player.append((player, entries))

        snapshot = tuple((p, tuple(e)) for p, e in effects_by_player)
        # get allowed : absent au tout premier passage de l'épisode (clé purgée au reset).
        if snapshot == self.game_state.get(self.EFFECTS_SNAPSHOT_LOGGED_KEY):
            return
        self.game_state[self.EFFECTS_SNAPSHOT_LOGGED_KEY] = snapshot
        step_logger.log_effects_snapshot(require_key(self.game_state, "turn"), effects_by_player)

    def _verify_supplied_mask(
        self,
        action_mask: np.ndarray,
        eligible_units: List[Dict[str, Any]],
        source: str,
    ) -> None:
        """Controle d'un masque transmis par un appelant — no-op hors ``W40K_MASK_VERIFY=2``.

        Le gain de la transmission repose sur une affirmation de l'appelant que rien ne verifiait
        (cf. ``engine.mask_verification.verify_supplied_mask``). Armer ce mode sur un run de
        validation transforme cette affirmation en fait.

        ``source`` nomme la PORTE d'entree — il y en a deux (``step_with_mask`` et
        ``_build_observation_and_mask``) et le message d'erreur doit designer la bonne.
        """
        from engine.mask_verification import verify_supplied_mask

        verify_supplied_mask(self.game_state, action_mask, eligible_units, source)

    def _step_observation(
        self, mask_and_eligible: Optional[Tuple[np.ndarray, List[Dict[str, Any]]]] = None
    ):
        """Observation RETOURNEE par ``step`` — ``None`` quand l'appelant a demande le report.

        Un step gym du wrapper d'entrainement enchaine plusieurs ``step`` moteur (tours du bot,
        WAIT forces, cascades de phase) mais PPO ne lit que la derniere observation : les autres
        etaient construites puis ecrasees. Mesure sur un worker x1 : la construction d'observation
        pese 55 % du temps CPU et ~70 % de ces constructions etaient jetees.

        L'appelant qui positionne ``defer_observation`` s'engage a construire lui-meme
        l'observation finale via ``_build_observation``. Une observation intermediaire vaut alors
        ``None`` : toute lecture leve immediatement, jamais un tenseur silencieusement faux.

        Le report traverse ``_build_observation`` au lieu de la court-circuiter, et c'est DELIBERE :
        cette fonction n'est pas un pur constructeur de tenseur, elle MUTE l'etat (checkpoint de
        controle d'objectif 14.02, journal VP, et surtout ``advance_phase`` quand le pool est vide).
        Un report qui sautait l'appel supprimait ces transitions : le moteur rendait la main sur un
        etat non avance, ``terminated`` etait calcule dessus et le wrapper compensait par un WAIT
        force — steps et journal decales. Seule la production du tenseur est reportee (parametre
        ``tensor``) ; la sequence d'effets de bord est rigoureusement la meme dans les deux modes.

        ``mask_and_eligible`` : cf. ``_build_observation``. Seul un appelant IMMEDIATEMENT adjacent
        peut le fournir.

        Rend ``(observation, masque_utilise)`` — le second element est celui de
        ``_build_observation_and_mask`` (couple ``(masque, pool)`` sur lequel cette construction
        s'est appuyee, ou ``None`` quand elle n'en a construit aucun). ``step_with_mask`` le propage
        jusqu'a son appelant, qui evite ainsi de le reconstruire a l'identique sur l'etat de sortie.
        """
        return self._build_observation_and_mask(
            tensor=not self.defer_observation, mask_and_eligible=mask_and_eligible
        )

    @overload
    def _build_observation(
        self,
        tensor: Literal[True] = True,
        mask_and_eligible: Optional[Tuple[np.ndarray, List[Dict[str, Any]]]] = None,
    ) -> Dict[str, np.ndarray]: ...

    @overload
    def _build_observation(
        self,
        tensor: bool,
        mask_and_eligible: Optional[Tuple[np.ndarray, List[Dict[str, Any]]]] = None,
    ) -> Optional[Dict[str, np.ndarray]]: ...

    def _build_observation(
        self,
        tensor: bool = True,
        mask_and_eligible: Optional[Tuple[np.ndarray, List[Dict[str, Any]]]] = None,
    ) -> Optional[Dict[str, np.ndarray]]:
        """Facade : l'observation seule. L'implementation est ``_build_observation_and_mask``.

        Quinze appelants n'ont besoin que du tenseur ; ils gardent cette signature. Ceux qui ont
        AUSSI besoin du masque (le PvE : observation pour le modele, masque pour le masquage des
        actions) appellent l'implementation et obtiennent les deux du MEME passage — plus besoin
        de recalculer un masque et d'argumenter qu'il decrit le meme etat.
        """
        return self._build_observation_and_mask(
            tensor=tensor, mask_and_eligible=mask_and_eligible
        )[0]

    def _observer_squad_for_pending_decision(self, decision: Dict[str, Any]) -> str:
        """Escouade DEPUIS LAQUELLE observer une décision en attente — RÈGLE UNIQUE.

        §0.40 point 1 : l'observation décrit l'unité SUR LAQUELLE porte le choix, jamais une
        autre — la prendre ailleurs décrirait un contexte étranger à la question posée.

        Cette règle a DEUX consommateurs dans `_build_observation_and_mask`, et ils ne peuvent
        pas fusionner : le premier voit les décisions déjà posées à l'entrée (`waaagh_call`,
        `rule_choice`), le second celles que la construction du masque vient d'ARMER
        (`fly_declaration`, V11 §0.48 `L6`) — le pool d'éligibles est alors vide et la branche
        d'entrée ne les avait pas vues. Écrite deux fois, elle divergerait en silence : les deux
        copies rendraient une escouade, simplement pas la même.

        Cas d'ARMÉE (`waaagh_call`) : la décision ne porte sur AUCUNE unité, son `unit_id`
        identifie le point de choix (`player_<n>`). Ce que le candidat accorde est global — les
        drapeaux Waaagh! de `global_bin` — donc n'importe laquelle de MES escouades vivantes est
        un repère égocentrique valable ; la première du joueur décideur, pour que le choix soit
        reproductible. Le contrôle strict reste entier pour les autres types : une décision dont
        l'unité a disparu décrit un état incohérent, et doit lever.
        """
        decision_unit_id = str(require_key(decision, "unit_id"))
        units_cache = require_key(self.game_state, "units_cache")
        if decision_unit_id in units_cache:
            return decision_unit_id
        if str(require_key(decision, "type")) != "waaagh_call":
            raise KeyError(
                f"_build_observation: unite {decision_unit_id} de la decision en attente "
                "absente de units_cache — la decision survit a son unite."
            )
        decision_player = int(require_key(decision, "player"))
        observer_id = next(
            (
                str(sid) for sid, entry in units_cache.items()
                if int(require_key(entry, "player")) == decision_player
            ),
            None,
        )
        if observer_id is None:
            raise KeyError(
                f"_build_observation: decision 'waaagh_call' du joueur {decision_player} "
                "alors qu'il n'a plus aucune escouade — 08.04 n'aurait pas du la poser."
            )
        return observer_id

    def _build_observation_and_mask(
        self,
        tensor: bool = True,
        mask_and_eligible: Optional[Tuple[np.ndarray, List[Dict[str, Any]]]] = None,
    ) -> Tuple[
        Optional[Dict[str, np.ndarray]], Optional[Tuple[np.ndarray, List[Dict[str, Any]]]]
    ]:
        """Build observation — pipeline squad, seul pipeline existant.

        Rend ``(observation, masque_utilise)``. Le second element est le couple
        ``(masque, pool eligible)`` sur lequel CETTE construction s'est appuyee, ou ``None`` quand
        elle n'en a construit aucun (decision en attente, phase de deploiement : l'observateur y
        est designe autrement). Un appelant qui a besoin du masque le reprend tel quel au lieu de
        le reconstruire : ils viennent alors du meme passage, donc du meme etat, PAR CONSTRUCTION —
        c'est un mecanisme, pas un argument d'adjacence. Sur ``None``, il le construit lui-meme.

        Pourquoi cette sortie et pas l'entree ``mask_and_eligible`` : ici l'ordre est impose dans
        l'autre sens. Cette fonction peut AVANCER LA PHASE (pool vide) ; un masque calcule avant
        elle decrirait alors la phase precedente. Le masque doit donc sortir d'elle, jamais y entrer,
        pour tout appelant qui ne peut pas prouver qu'aucune transition n'aura lieu.

        L'obs est un Dict de TENSEURS D'ENTITES (V11 §0.30 T-D — une unite, amie ou ennemie, y
        porte le meme schema de features), toujours scinde continues/discretes (V11 §9.5), plus
        la grille egocentrique (perception du terrain, spec §4.1 / T1b). La geometrie de la
        grille est celle de `engine.spatial_grid`, partagee avec le masque (T2) et le decoder (T3).

        ``tensor=False`` (report d'observation, cf. ``_step_observation``) : le corps est parcouru
        A L'IDENTIQUE — frontiere 14.02, journal VP, ``advance_phase`` sur pool vide — mais rend
        ``None`` au lieu d'encoder. Cette fonction n'est PAS pure : ces mutations font partie du
        pas de simulation, seul l'encodage est facultatif. Les deux fabriques locales ci-dessous
        sont les SEULS producteurs de tenseur (tous les `return` y passent) : porter le drapeau la
        garantit qu'aucune sortie ne l'oublie.

        ``mask_and_eligible`` — masque et pool DEJA calcules par l'appelant, pour ne pas les
        recalculer ici. Ce n'est pas un cache : rien n'est conserve, donc rien a perimer. Le masque
        n'est de toute facon pas memoisable — il tire le jet d'Advance au premier appel d'une
        activation (cf. ``action_decoder``).

        LA REGLE, et non une liste d'appelants autorises — une telle liste rouille en silence des
        qu'un site s'ajoute (c'est arrive dans le commit meme qui l'a ecrite) : l'appelant doit
        pouvoir PROUVER que rien n'a touche ``game_state`` entre la construction du masque et cet
        appel. Adjacence de ligne quand la valeur ne bouge pas ; quand elle traverse des cadres de
        pile, tout chemin mutant doit la remettre a ``None`` — discipline tenue et documentee par
        ``ai/env_wrappers.MaskDecision``. Dans le doute : ``None``, et le masque est reconstruit ici
        (correct dans tous les cas, seulement plus lent).

        Le rafraichissement de frontiere 14.02 fait juste en dessous ne change pas la legalite des
        actions : verifie par recalcul-comparaison a la mise en place, et re-verifiable a tout moment
        par ``W40K_MASK_VERIFY=1``, qui recompare la carte de cellules memoisee
        (``engine.mask_verification``, appelee depuis ``shared_utils.read_squad_move_cell_map`` et
        ``movement_handlers``).
        """
        # Regle 14.02 : le controle d objectif est determine a la FIN de chaque phase/tour.
        # Ce point de passage est le seul commun aux 7 sites de construction d observation du
        # moteur (step, reset, cascades de transition) : y placer la detection de frontiere
        # garantit que l observation lit un `objective_controllers` a jour, sans jamais
        # recalculer quoi que ce soit pendant une phase. Le rafraichissement lui-meme est
        # no-op tant que (phase, tour) n a pas change — cf.
        # GameStateManager.refresh_objective_control_on_boundary (partage avec le PvP).
        self.state_manager.refresh_objective_control_on_boundary(self.game_state)
        self._log_objective_control_snapshot_if_changed()
        # Instantané d'ÉTAT (une ligne par tour) : même point de passage, choisi pour la même
        # raison — c'est le seul commun aux 7 sites de construction d'observation, donc le seul
        # où l'on soit sûr de voir chaque tour exactement une fois.
        self._log_state_snapshot_if_turn_changed()
        # Effets en vigueur : MÊME point de passage, mais déclenché au CHANGEMENT (une capacité
        # se déclare au milieu d'un tour, cf. `_log_effects_snapshot_if_changed`).
        self._log_effects_snapshot_if_changed()

        def _zero_obs():
            if not tensor:
                return None
            from engine.spatial_grid import GRID_CHANNELS, GRID_SIZE

            obs = self.obs_builder._empty_squad_observation()
            obs["grid"] = np.zeros((GRID_CHANNELS, GRID_SIZE, GRID_SIZE), dtype=np.float32)
            return obs

        def _build_for_squad(squad_id: str):  # get allowed
            if not tensor:
                return None
            obs = self.obs_builder.build_squad_observation(self.game_state, squad_id)
            obs["grid"] = self.obs_builder.build_squad_grid(self.game_state, squad_id)
            return obs

        # Décision agent en attente (V11 §9.3 P2) : l'observateur est l'unité SUR LAQUELLE porte
        # la décision — c'est elle que les candidats concernent. La prendre ailleurs décrirait un
        # contexte étranger au choix demandé (le défaut §0.40 point 1, à ne pas reproduire ici).
        pending_decision = read_pending_agent_decision(self.game_state)
        if pending_decision is not None:
            # Aucun masque construit sur ce chemin : l'observateur est l'unite de la decision.
            return _build_for_squad(
                self._observer_squad_for_pending_decision(pending_decision)
            ), None

        if self.game_state.get("phase") == "deployment":
            # §0.40 point 1 : l'obs decrit l'unite SUR LAQUELLE LE MASQUE AGIT, jamais une autre.
            # Elle lisait `next(iter(units_cache))` — la 1ere cle du cache, tous joueurs confondus
            # et deployes compris — alors que le masque ouvre les slots 4-8 pour
            # `deployable_units[current_deployer][0]` : l'agent decrivait A et posait B. Meme
            # doctrine que la branche `pending_agent_decision` ci-dessus : UNE source, celle du
            # masque (`get_deployment_active_unit`, qui leve si le pool est vide au lieu de rendre
            # une obs nulle qui masquerait l'incoherence).
            # Aucun masque construit ici non plus : l'unite active vient du pool de deploiement.
            return _build_for_squad(
                str(require_key(self.action_decoder.get_deployment_active_unit(self.game_state), "id"))
            ), None

        if mask_and_eligible is not None:
            action_mask, eligible_units = mask_and_eligible
            # Meme controle que dans `step_with_mask`, et pour la meme raison : ce parametre est
            # l'AUTRE porte d'entree d'un masque construit ailleurs (quatre appelants de
            # production). Elle n'etait pas verifiee alors que la docstring ci-dessus renvoie a
            # `W40K_MASK_VERIFY=2` — un mode arme qui ne regarde qu'une porte sur deux donne un
            # feu vert partiel qui se lit comme un feu vert.
            self._verify_supplied_mask(
                action_mask, eligible_units, "W40KEngine._build_observation_and_mask"
            )
        else:
            action_mask, eligible_units = self.action_decoder.get_squad_action_mask_and_eligible_units(self.game_state)
        if not eligible_units and not action_mask.any():
            if self.game_state.get("game_over", False):
                return _zero_obs(), (action_mask, eligible_units)
            current_phase = self.game_state.get("phase", "unknown")
            advance_action = {"action": "advance_phase", "from": current_phase, "reason": "pool_empty"}
            advance_success, advance_result = self._advance_phase_and_drain(advance_action)
            if not advance_success:
                if isinstance(advance_result, dict) and advance_result.get("error") == "game_over":
                    # `_process_squad_action` a echoue APRES avoir potentiellement mute l'etat :
                    # le masque ci-dessus ne le decrit plus, on n'en rend aucun.
                    return _zero_obs(), None
                raise RuntimeError(f"advance_phase failed: {advance_result}")
            # La phase vient d'avancer : on garde le masque RECALCULE, pas celui d'avant. Il etait
            # jete dans `_action_mask` — le couple rendu serait alors incoherent (masque d'avant la
            # transition, pool d'apres), exactement le defaut que cette sortie doit empecher.
            action_mask, eligible_units = self.action_decoder.get_squad_action_mask_and_eligible_units(self.game_state)
            if not eligible_units:  # get allowed
                return _zero_obs(), (action_mask, eligible_units)
        # Active squad = 1er eligible (convention 1 unit = 1 squad).
        # Si eligible_units vide mais mask any (cas degenere),
        # prendre 1ere unite vivante du player courant.
        # Décision ARMÉE PAR la construction du masque ci-dessus (déclaration de vol 21.03,
        # V11 §0.48 `L6`) : elle n'existait pas au contrôle d'entrée de cette fonction, donc la
        # branche du haut ne l'a pas vue. Même règle, MÊME code
        # (`_observer_squad_for_pending_decision`) — sinon l'agent décrirait une escouade et
        # déclarerait pour une autre (le défaut §0.40 point 1).
        armed_decision = read_pending_agent_decision(self.game_state)
        if eligible_units:
            active_squad_id = str(eligible_units[0]["id"])
        elif armed_decision is not None:
            active_squad_id = self._observer_squad_for_pending_decision(armed_decision)
        else:
            uc = self.game_state.get("units_cache", {})  # get allowed
            current_player = int(self.game_state.get("current_player", 1))
            active_squad_id = next(
                (str(sid) for sid, e in uc.items() if int(e.get("player", -1)) == current_player),
                None,
            )
            if active_squad_id is None:
                return _zero_obs(), (action_mask, eligible_units)
        return _build_for_squad(active_squad_id), (action_mask, eligible_units)

    def _calculate_board_max_range(self, board_cols: int, board_rows: int) -> int:
        """
        Calculate maximum hex distance across the board based on board dimensions.
        """
        if board_cols <= 0 or board_rows <= 0:
            raise ValueError(f"Invalid board dimensions: cols={board_cols}, rows={board_rows}")
        corners = [
            (0, 0),
            (0, board_rows - 1),
            (board_cols - 1, 0),
            (board_cols - 1, board_rows - 1),
        ]
        max_distance = 0
        for i in range(len(corners)):
            for j in range(i + 1, len(corners)):
                c1 = corners[i]
                c2 = corners[j]
                distance = calculate_hex_distance(c1[0], c1[1], c2[0], c2[1])
                if distance > max_distance:
                    max_distance = distance
        return max_distance
    
    
    def _calculate_reward(self, success: bool, result: Dict[str, Any]) -> float:
        """Calculate reward - delegates to reward_calculator."""
        return self.reward_calculator.calculate_reward(success, result, self.game_state)
    
    
    def _initialize_units(self):
        """Initialize units - delegates to state_manager."""
        self.state_manager.initialize_units(self.game_state)
        self._rebuild_unit_by_id()

    def _rebuild_unit_by_id(self):
        """Build O(1) index game_state['unit_by_id'] from game_state['units'].
        Logs error if duplicate unit IDs detected.
        """
        units = require_key(self.game_state, "units")
        seen_ids = set()
        unit_by_id = {}
        for u in units:
            uid = str(u["id"])
            if uid in seen_ids:
                if self.debug_mode:
                    from engine.game_utils import add_debug_file_log
                    add_debug_file_log(
                        self.game_state,
                        f"[unit_by_id] ERROR: duplicate unit id {uid} in game_state['units']"
                    )
            seen_ids.add(uid)
            unit_by_id[uid] = u
        self.game_state["unit_by_id"] = unit_by_id

    def _load_units_from_scenario(self, scenario_file, unit_registry, deployment_type_override=None):
        """Load units from scenario - delegates to state_manager.

        ``deployment_type_override`` : propage le mode de déploiement choisi pour l'épisode
        (scheduler fixed↔active), voir ``GameStateManager.load_units_from_scenario``.
        """
        # Create temporary state_manager just for loading during init.
        # During early bootstrap, self.config may not exist yet; default bootstrap seat is player 1.
        bootstrap_controlled_player = 1
        if hasattr(self, "config") and isinstance(self.config, dict) and "controlled_player" in self.config:
            bootstrap_controlled_player = int(require_key(self.config, "controlled_player"))
        from config_loader import get_config_loader
        bootstrap_config = {"board": get_config_loader().get_board_config(), "controlled_player": bootstrap_controlled_player}
        if hasattr(self, "training_config") and isinstance(self.training_config, dict):
            bootstrap_config["training_config"] = self.training_config
        episode_number = None
        if hasattr(self, "game_state") and isinstance(self.game_state, dict):
            episode_number = self.game_state.get("episode_number")
        if isinstance(episode_number, int) and not isinstance(episode_number, bool):
            bootstrap_config["_training_episode_index"] = max(0, int(episode_number) - 1)
        else:
            bootstrap_config["_training_episode_index"] = 0
        temp_manager = GameStateManager(
            bootstrap_config,
            unit_registry
        )
        return temp_manager.load_units_from_scenario(
            scenario_file, unit_registry, deployment_type_override=deployment_type_override
        )

    def _reload_scenario(self, scenario_file: str, deployment_type_override=None):
        """Reload scenario data for random scenario selection during training.

        This method is called during reset() when random_scenario_mode is enabled.
        It reloads units, walls, and objectives from the selected scenario file.

        ``deployment_type_override`` : mode de déploiement imposé pour l'épisode
        (scheduler fixed↔active, cf. ``_configure_deployment_mode_for_episode``).
        """
        from config_loader import get_config_loader
        config_loader = get_config_loader()
        board_config = config_loader.get_board_config()

        # Load scenario data (units + optional terrain)
        scenario_result = self._load_units_from_scenario(
            scenario_file, self.unit_registry, deployment_type_override=deployment_type_override
        )
        scenario_units = scenario_result["units"]
        scenario_roster_info = scenario_result.get("roster_info")
        scenario_primary_objective_ids = scenario_result.get("primary_objectives")
        scenario_deployment_type = scenario_result.get("deployment_type")
        scenario_deployment_type_by_player = scenario_result.get("deployment_type_by_player")
        scenario_deployment_zone = scenario_result.get("deployment_zone")
        scenario_deployment_pools = scenario_result.get("deployment_pools")
        scenario_primary_objective_id = None
        if scenario_primary_objective_ids is None:
            scenario_primary_objective_id = scenario_result.get("primary_objective")

        if scenario_primary_objective_ids is not None:
            if not isinstance(scenario_primary_objective_ids, list):
                raise TypeError("primary_objectives must be a list of objective IDs")
            if not scenario_primary_objective_ids:
                raise ValueError("primary_objectives list cannot be empty")
            primary_objective_config = [
                config_loader.load_primary_objective_config(obj_id)
                for obj_id in scenario_primary_objective_ids
            ]
        elif scenario_primary_objective_id is not None:
            primary_objective_config = config_loader.load_primary_objective_config(
                scenario_primary_objective_id
            )
        else:
            primary_objective_config = None

        # Determine wall_hexes: use scenario if provided, otherwise use board config
        if scenario_result.get("wall_hexes") is not None:
            scenario_wall_hexes = scenario_result["wall_hexes"]
        else:
            if "default" in board_config:
                d = board_config["default"]
                scenario_wall_hexes = d["wall_hexes"] if "wall_hexes" in d else []
            else:
                scenario_wall_hexes = board_config["wall_hexes"] if "wall_hexes" in board_config else []

        # Normalize walls to tuple coordinates for O(1) membership checks.
        normalized_wall_hexes = set()
        for raw_wall in scenario_wall_hexes:
            if not isinstance(raw_wall, (list, tuple)) or len(raw_wall) != 2:
                raise ValueError(
                    f"Invalid wall hex format in scenario reload '{scenario_file}': {raw_wall!r}"
                )
            wall_col, wall_row = normalize_coordinates(raw_wall[0], raw_wall[1])
            normalized_wall_hexes.add((wall_col, wall_row))
        self._scenario_wall_hexes = sorted(normalized_wall_hexes)

        # Murs Solid/dense (rule 13.5). None si absent → set vide (jamais de repli wall_hexes).
        normalized_dense_wall_hexes = set()
        for raw_wall in (scenario_result.get("dense_wall_hexes") or []):
            if not isinstance(raw_wall, (list, tuple)) or len(raw_wall) != 2:
                raise ValueError(
                    f"Invalid dense wall hex format in scenario reload '{scenario_file}': {raw_wall!r}"
                )
            wall_col, wall_row = normalize_coordinates(raw_wall[0], raw_wall[1])
            normalized_dense_wall_hexes.add((wall_col, wall_row))
        self._scenario_dense_wall_hexes = sorted(normalized_dense_wall_hexes)

        self.game_state["weapon_damage_table"] = load_weapon_damage_table()

        # Clear target pool cache on scenario rotation (defense in depth)
        from engine.phase_handlers import shooting_handlers
        shooting_handlers.clear_target_pool_cache()

        # Objectifs : source UNIQUE = terrains "objective": true (résolus en {id, hexes}).
        self._scenario_objectives = require_key(scenario_result, "objectives")

        self.config["deployment_type"] = scenario_deployment_type
        self.config["deployment_type_by_player"] = scenario_deployment_type_by_player
        self.config["deployment_zone"] = scenario_deployment_zone
        self.config["deployment_pools"] = scenario_deployment_pools
        # JUMEAU de la pose initiale (cf. le bloc de config du constructeur) : la rotation de
        # scénario change d'armée, donc la clause de détachement d'Oath doit suivre. Sans cette
        # ligne, un scénario chargé en second garderait la valeur du précédent.
        self.config["uses_codex_detachment"] = scenario_result.get("uses_codex_detachment")
        # Meme JUMEAU pour la Faction d'Armee : la rotation change d'armee, donc de faction.
        self.config["army_faction"] = scenario_result.get("army_faction")
        self._scenario_primary_objective = primary_objective_config
        self._scenario_roster_info = scenario_roster_info
        # Taille de bataille (points) du nouveau scénario — plafond des réserves 20.01. Doit
        # suivre la rotation de scénario, sinon le plafond resterait celui du scénario précédent.
        self._scenario_points_limit = scenario_result.get("points_limit")
        self.game_state["points_limit"] = self._scenario_points_limit
        self._scenario_has_random_agent_roster = bool(
            scenario_roster_info and scenario_roster_info.get("agent_ref_randomized")
        )
        self._scenario_loaded_for_controlled_player = int(require_key(self.config, "controlled_player"))

        # Extract scenario name from file path for logging
        scenario_name = scenario_file
        if scenario_name and "/" in scenario_name:
            scenario_name = scenario_name.split("/")[-1].replace(".json", "")
        elif scenario_name and "\\" in scenario_name:
            scenario_name = scenario_name.split("\\")[-1].replace(".json", "")

        # Update config with new scenario data
        # CRITICAL: Store ORIGINAL positions in config as a deepcopy (immutable reference)
        # This prevents position corruption when game_state units are modified during gameplay
        self.config["units"] = copy.deepcopy(scenario_units)
        self.config["name"] = scenario_name
        self.config["primary_objective"] = primary_objective_config

        # Reinitialize game_state units with a SEPARATE deepcopy
        # This ensures game_state["units"] is independent from config["units"]
        self.game_state["units"] = copy.deepcopy(scenario_units)
        for unit in self.game_state["units"]:
            stamp_weapon_keys(unit)
        self._rebuild_unit_by_id()

        # Update wall_hexes and objectives in game_state if present
        if "wall_hexes" in self.game_state:
            # JUMEAU de la pose initiale (constructeur) : les demi-cases fantômes du bord
            # bas ne viennent PAS du scénario, donc réécrire le set avec les seuls murs
            # normalisés les perdrait. La rotation de scénario ne change pas le plateau,
            # d'où les dimensions relues dans game_state.
            self.game_state["wall_hexes"] = set(normalized_wall_hexes) | phantom_bottom_hexes(
                require_key(self.game_state, "board_cols"),
                require_key(self.game_state, "board_rows"),
            )
        self.game_state["dense_wall_hexes"] = set(normalized_dense_wall_hexes)
        if "objectives" in self.game_state:
            self.game_state["objectives"] = self._scenario_objectives
        if "primary_objective" in self.game_state:
            self.game_state["primary_objective"] = self._scenario_primary_objective
        # Terrain areas change on scenario rotation: refresh and drop derived static caches.
        self._scenario_terrain_areas = scenario_result.get("terrain_areas")
        self.game_state["terrain_areas"] = self._scenario_terrain_areas or []
        self.game_state.pop("_obscuring_area_sets_cache", None)
        self.game_state.pop("_obscuring_hex_to_area_cache", None)
        self.game_state.pop("_los_blocking_grids_cache", None)
        self.game_state.pop("_unit_los_pair_cache", None)
        self.game_state.pop("_wall_set_cache", None)
        self.game_state.pop("_dense_wall_set_cache", None)
        self.game_state.pop("_hex_los_state_cache", None)
        objectives = require_key(self.game_state, "objectives")
        self.game_state["macro_target_objective_index"] = 0 if objectives else None
        self.game_state["macro_target_objective_id"] = str(require_key(objectives[0], "id")) if objectives else None


# ============================================================================
# KEEP AT END OF FILE
# ============================================================================

if __name__ == "__main__":
    print("W40K Engine requires proper config from training system - no standalone execution")
