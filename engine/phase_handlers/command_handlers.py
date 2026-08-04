#!/usr/bin/env python3
"""
command_handlers.py - Command Phase Implementation
Pure stateless functions implementing command phase specification

The command phase handles all administrative tasks (reset marks, clear caches, etc.)
before the movement phase. In Phase 2, the agent may take zone intent free steps
(up to MAX_OBJECTIVES) before transitioning to move.
"""

from typing import Dict, List, Tuple, Set, Optional, Any
from shared.data_validation import require_key
from engine.game_state import (
    CORE_CP_GAIN_PER_COMMAND_PHASE, GameStateManager, gain_command_points,
)


def command_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Initialize command phase - do all maintenance/resets, then either:
    - Stay in command if zone intent free steps are available (Phase 2), or
    - Auto-advance to move (no free steps or bot player).

    LES CINQ ÉTAPES DE LA PHASE (PDF 08) — l'ordre est celui du PDF, et c'est un contrat :
      08.01 `command_step_start_of_phase`     — début de phase (remises à zéro, caches)
      08.02 `command_step_gain_core_cp`       — les DEUX joueurs gagnent 1 CP
      08.03 `command_step_battle_shock`       — jets du joueur ACTIF seulement
      08.04 `command_step_command_abilities`  — capacités « in your command phase »
      08.05 `command_phase_end`               — fin de phase
    Elles sont découpées en fonctions nommées parce que plusieurs capacités se déclenchent à une
    étape PRÉCISE (Waaagh! et Oath au début, Get da Good Bitz en fin) : sans les étapes, il n'y a
    aucun endroit où les accrocher, et elles finiraient au petit bonheur dans le corps de la phase.

    Phase 2 changes:
    - Initializes zone_intent_free_steps_remaining = MAX_OBJECTIVES
    - Populates unit_zone_assignments (one per alive friendly unit)
    - Returns without phase_complete if free steps > 0 (agent will issue zone intent actions)
    """
    from engine.macro_intents import INTENT_INVADE, MAX_OBJECTIVES, get_nearest_objective_zone

    command_step_start_of_phase(game_state)   # 08.01
    command_step_gain_core_cp(game_state)     # 08.02
    command_step_battle_shock(game_state)     # 08.03

    # Build activation pool (empty for now, structure ready for future)
    command_build_activation_pool(game_state)

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    command_pool = require_key(game_state, "command_activation_pool")
    add_debug_file_log(game_state, f"[POOL BUILD] E{episode} T{turn} command command_activation_pool={command_pool}")

    # Console log
    from engine.game_utils import add_console_log
    add_console_log(game_state, "COMMAND PHASE START")

    command_step_command_abilities(game_state)  # 08.04

    # Primary objective scoring (command phase). Règle de MISSION (14.03), pas une des cinq
    # étapes : elle est laissée APRÈS 08.03 parce qu'elle lit l'OC, que le battle-shock vient de
    # modifier à '-' (01.07) — l'avancer changerait les VP marqués.
    state_manager = GameStateManager(require_key(game_state, "config"))
    state_manager.apply_primary_objective_scoring(game_state, "command")

    # Phase 2: Initialize zone intent free steps
    # Only for the controlled agent player during gym training
    gym_training_mode = game_state.get("gym_training_mode", False)
    current_player = game_state.get("current_player")
    config = game_state["config"]
    controlled_player = config.get("controlled_player")

    is_agent_turn = (
        gym_training_mode
        and controlled_player is not None
        and current_player == controlled_player
    )

    # Populate unit_zone_assignments for ALL alive units (both players)
    from engine.phase_handlers.shared_utils import is_unit_alive
    assignments = {}
    for unit in game_state["units"]:
        if not is_unit_alive(str(unit["id"]), game_state):
            continue
        if unit.get("col", -1) >= 0 and unit.get("row", -1) >= 0:
            zone_idx = get_nearest_objective_zone(unit, game_state)
        else:
            zone_idx = 0
        assignments[str(unit["id"])] = zone_idx
    game_state["unit_zone_assignments"] = assignments

    if is_agent_turn:
        # Reset zone_intent_free_steps_remaining to MAX_OBJECTIVES.
        # Cette valeur PLEINE est aussi le signal qu'aucun intent n'a encore ete joue ce tour :
        # `W40KEngine._process_command_phase` s'en sert pour solder la declaration du tour
        # precedent exactement une fois (cf. `settle_pending_zone_intent_declaration`).
        game_state["zone_intent_free_steps_remaining"] = MAX_OBJECTIVES

        # Stay in command phase — agent will issue zone intent actions
        return {"phase_complete": False, "phase": "command"}

    # Bot player or non-training: skip free steps, auto-advance to move
    game_state["zone_intent_free_steps_remaining"] = 0
    return command_phase_end(game_state)


def command_step_start_of_phase(game_state: Dict[str, Any]) -> None:
    """08.01 START OF PHASE — pose la phase et remet à zéro l'état « ce tour ».

    Point d'accrochage des capacités « at the start of your Command phase ». Rien ne s'y
    déclenche aujourd'hui : les capacités qui le feront appartiennent aux chantiers 03 et 06.
    """
    # Set phase
    game_state["phase"] = "command"

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    units_cache = require_key(game_state, "units_cache")
    add_debug_file_log(game_state, f"[PHASE START] E{episode} T{turn} command units_cache={units_cache}")

    # Snapshot last turn's shooting BEFORE reset (rule 13.09 Hidden: "did not make ranged
    # attacks during this turn or during the previous turn"). Captured at each turn start so
    # it holds the previous player-turn's shots when evaluating enemy targets.
    game_state["units_shot_previous_turn"] = set(game_state.get("units_shot", set()))

    # Reset ALL tracking sets (moved from movement_phase_start)
    game_state["units_moved"] = set()
    # Distance parcourue par figurine (V11 §9.2.5) — MEME cycle de vie que `units_moved` :
    # c'est la version continue du meme fait ("cette figurine a bouge de X ce tour").
    game_state["moved_distance_by_model"] = {}
    game_state["units_fled"] = set()
    game_state["units_shot"] = set()
    game_state["units_charged"] = set()
    game_state["units_fought"] = set()
    game_state["units_attacked"] = set()
    game_state["units_advanced"] = set()
    game_state["advance_rolls"] = {}
    game_state["units_took_to_skies"] = set()
    game_state["units_took_to_skies_charge"] = set()
    game_state["units_reacted_this_enemy_turn"] = set()

    game_state["reactive_macro_order_current_window"] = []
    game_state["reaction_window_active"] = False
    game_state["reactive_decision_payload"] = {}

    # Clear movement preview state
    game_state["valid_move_destinations_pool"] = []
    game_state["preview_hexes"] = []
    game_state["move_preview_footprint_zone"] = set()
    game_state["move_preview_footprint_mask_loops"] = None
    game_state["move_preview_footprint_span"] = None
    game_state["active_movement_unit"] = None

    # Clear enemy reachable positions cache (enemy positions may have changed)
    # Used by RewardCalculator._get_enemy_reachable_positions for defensive threat calculation
    game_state["enemy_reachable_cache"] = {}


def command_step_gain_core_cp(game_state: Dict[str, Any]) -> None:
    """08.02 GAIN CORE CP — « Both players gain 1 Command Point (CP). »

    LES DEUX joueurs, pas le seul joueur actif : c'est la différence avec 08.03 juste en dessous,
    et l'erreur que la lecture rapide du PDF produit. Le montant est la constante du PDF, pas un
    réglage de scénario.
    """
    for player in (1, 2):
        gain_command_points(
            game_state, player, CORE_CP_GAIN_PER_COMMAND_PHASE, "08.02 Core CP"
        )


def command_step_battle_shock(game_state: Dict[str, Any]) -> None:
    """08.03 BATTLE-SHOCK — un jet par unité concernée, pour le joueur ACTIF seulement.

    « The active player must now make one battle-shock roll for each unit IN THEIR ARMY that
    fulfils one or both of the following conditions : that unit is currently battle-shocked ;
    that unit is at, or below, half-strength. » Les deux conditions sont une UNION : une unité
    déjà battle-shocked rejette même revenue au-dessus du demi-effectif — c'est ce jet qui lui
    permet d'en sortir (clause de sortie appliquée par `roll_battle_shock`).
    """
    from engine.phase_handlers.shared_utils import (
        is_unit_alive, is_unit_at_or_below_half_strength, roll_battle_shock,
    )

    current_player = require_key(game_state, "current_player")
    for unit in require_key(game_state, "units"):
        if require_key(unit, "player") != current_player:
            continue
        unit_id = str(unit["id"])
        if not is_unit_alive(unit_id, game_state):
            continue
        needs_roll = require_key(unit, "battle_shocked") or is_unit_at_or_below_half_strength(
            unit_id, game_state
        )
        if needs_roll:
            # `roll_battle_shock` journalise le jet (action log + trace debug) : il connaît déjà
            # le seuil qu'il a employé, le recalculer ici pour le logger le balayait deux fois.
            roll_battle_shock(unit_id, game_state)


def command_step_command_abilities(game_state: Dict[str, Any]) -> None:
    """08.04 COMMAND ABILITIES — capacités qui se déclenchent « in your Command phase ».

    Point d'accrochage nommé, sans effet aujourd'hui : les capacités concernées (Grot Orderly,
    Waaagh!, Oath of Moment) appartiennent aux chantiers 03 et 06. Elles se brancheront ICI,
    entre le battle-shock et la fin de phase, comme le PDF les ordonne.
    """
    return None


def command_build_activation_pool(game_state: Dict[str, Any]) -> None:
    """
    Build command activation pool (empty for now, structure ready for future).
    """
    game_state["command_activation_pool"] = []


def command_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    08.05 END OF PHASE — end command phase and transition to move phase.

    Point d'accrochage des capacités « at the end of your Command phase » (Get da Good Bitz,
    chantier 06).

    CRITICAL: Returns ONLY the dict, does NOT call movement_phase_start() directly.
    The cascade loop in w40k_core.py handles the transition automatically.
    """
    from engine.game_utils import add_console_log
    add_console_log(game_state, "COMMAND PHASE COMPLETE")

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    command_pool = require_key(game_state, "command_activation_pool")
    add_debug_file_log(game_state, f"[POOL PRE-TRANSITION] E{episode} T{turn} command command_activation_pool={command_pool}")
    
    # Return only the dict - cascade loop will call movement_phase_start()
    return {
        "phase_complete": True,
        "next_phase": "move",
        "phase_transition": True,
        "clear_blinking_gentle": True
    }


def execute_action(game_state: Dict[str, Any], unit: Optional[Dict[str, Any]], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Execute action for command phase (structure ready for future).
    
    For now, no actions - phase auto-advances.
    Structure ready for future unit actions in command phase.
    """
    # For now, no actions - phase auto-advances
    # Structure ready for future unit actions in command phase
    return True, command_phase_end(game_state)




