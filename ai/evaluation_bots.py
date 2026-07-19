#!/usr/bin/env python3
"""
ai/evaluation_bots.py - Tactical bots for measuring agent performance

Bot Hierarchy (easiest to hardest):

Tier 1 — Simple strategy bots:
  1. RandomBot - Random actions (baseline)
  2. GreedyBot - Shoots first, moves toward enemies (aggressive)
  3. DefensiveBot - Retreats from threats, shoots when possible
  4. ControlBot - Captures and holds objectives, shoots contesters

Tier 2 — Smart bots (focus-fire, advance, charge):
  5. AggressiveSmartBot - Focus-fires low HP, advances, charges always
  6. DefensiveSmartBot - Focus-fires threats, keeps distance, never charges
  7. AdaptiveBot - Adapts posture to game state (early rush / winning hold / losing push)

Legacy:
  8. TacticalBot - Full phase awareness. V11 §10.5 : HOLDOUT d'evaluation — utilise
     UNIQUEMENT en evaluation, jamais dans bot_training.ratios, et exclu de tout
     signal de selection de modele. Jamais valide runtime sur le pipeline squad.

All bots implement all 4 phases: MOVE, SHOOT, CHARGE, FIGHT
"""

import random
from typing import Dict, List, Tuple, Any, Optional
from shared.data_validation import require_key, require_present
from engine.combat_utils import calculate_hex_distance, get_unit_coordinates
from engine.hex_utils import min_distance_between_sets
from engine.phase_handlers.shared_utils import (
    is_unit_alive, get_hp_from_cache,
    get_unit_position, require_unit_position,
    compute_candidate_footprint,
)
from engine import macro_intents as mi
from engine.utils.weapon_helpers import get_max_ranged_damage, get_max_melee_damage

# Espace d'action squad (source unique : engine/macro_intents.py). Aucun littéral nu.
DEPLOYMENT_ACTIONS = list(mi.DEPLOY_SLOTS)   # 4-8 (slots de déploiement)
WAIT_ACTION = mi.ACTION_WAIT                 # 18


def _first_action_in(valid_actions, action_ids):
    """Retourne la première action de action_ids présente dans valid_actions, sinon None."""
    for a in action_ids:
        if a in valid_actions:
            return a
    return None


# --- Heuristiques de destination (refonte spatiale du move, spec §T4) --------
# En move spatial, le TYPE de move (normal/advance/fall_back) est INFERE du cout geodesique par
# le moteur (shared_utils.infer_squad_move_type) : le bot ne choisit plus qu'une DESTINATION
# parmi le pool BFS legal (les hexes reellement executables), via select_movement_destination.
# Le wrapper d'eval traduit ensuite destination -> cellule -> action entiere. Choisir « la
# premiere cellule legale » donnerait un coin arbitraire de la grille (root cause §3 transposee,
# c'est explicitement rejete) : ces helpers donnent a chaque bot une vraie geometrie.
#
# Convention WAIT : renvoyer la position courante de l'unite (`require_unit_position`) signale
# « je ne bouge pas » — le wrapper la traduit en WAIT. `start_pos` etant exclu du pool (§4.6),
# l'ancre n'est jamais une destination legale : le signal est donc sans ambiguite.

def _living_enemy_positions(unit, game_state):
    """Ancres (col,row) des ennemis vivants de `unit`, depuis units_cache."""
    units_cache = require_key(game_state, "units_cache")
    positions = []
    for enemy in require_key(game_state, "units"):
        if enemy.get("player") == unit.get("player"):
            continue
        if not is_unit_alive(str(enemy["id"]), game_state):
            continue
        entry = units_cache.get(str(enemy["id"]))
        if entry is not None:
            positions.append((int(entry["col"]), int(entry["row"])))
        else:
            positions.append((int(enemy["col"]), int(enemy["row"])))
    return positions


def _dest_nearest_enemy_hexdist(dest, enemy_positions):
    """Distance-hex de la destination a l'ancre ennemie la plus proche."""
    return min(calculate_hex_distance(dest[0], dest[1], ec, er) for ec, er in enemy_positions)


def _dest_toward_enemies(valid_destinations, unit, game_state):
    """Destination minimisant la distance-hex a l'ennemi le plus proche (poussee offensive).

    Distance ancre->ancre (O(1)/cellule) et non empreinte->empreinte : sur board x5 le pool
    contient ~337 cellules jouables (jusqu'a 634), et recalculer une empreinte par candidate
    coutait ~44 ms/decision de bot. Une distance hex suffit a une heuristique de bot.
    """
    enemy_pos = _living_enemy_positions(unit, game_state)
    if not enemy_pos:
        return valid_destinations[0]
    return min(
        valid_destinations,
        key=lambda d: _dest_nearest_enemy_hexdist(d, enemy_pos),
    )


def _dest_away_from_enemies(valid_destinations, unit, game_state):
    """Destination maximisant la distance-hex a l'ennemi le plus proche (repli)."""
    enemy_pos = _living_enemy_positions(unit, game_state)
    if not enemy_pos:
        return valid_destinations[0]
    return max(
        valid_destinations,
        key=lambda d: _dest_nearest_enemy_hexdist(d, enemy_pos),
    )


def _dest_toward_objective(valid_destinations, unit, game_state):
    """Destination la plus proche du centre de l'objectif le plus proche de l'unite."""
    objectives = game_state.get("objectives")
    if not objectives:
        return _dest_toward_enemies(valid_destinations, unit, game_state)
    ucol, urow = get_unit_coordinates(unit)
    nearest = min(
        objectives,
        key=lambda o: calculate_hex_distance(ucol, urow, *mi.get_objective_center(o)),
    )
    ocol, orow = mi.get_objective_center(nearest)
    return min(
        valid_destinations,
        key=lambda d: calculate_hex_distance(d[0], d[1], ocol, orow),
    )


def _select_weighted_deployment_action(
    valid_actions: List[int],
    weights_by_action: Dict[int, float],
    last_action: Optional[int],
    repeat_count: int,
    max_repeat: int,
) -> int:
    """Select deployment intent with weighted randomness and anti-repeat guard."""
    candidates = [a for a in DEPLOYMENT_ACTIONS if a in valid_actions]
    if not candidates:
        raise ValueError("No deployment actions available in valid_actions")

    if last_action in candidates and repeat_count >= max_repeat and len(candidates) > 1:
        candidates = [a for a in candidates if a != last_action]

    candidate_weights: List[float] = []
    for action in candidates:
        if action not in weights_by_action:
            raise KeyError(f"Missing deployment weight for action {action}")
        candidate_weights.append(float(weights_by_action[action]))

    total_weight = sum(candidate_weights)
    if total_weight <= 0:
        raise ValueError(f"Invalid deployment weights sum: {total_weight}")

    return int(random.choices(candidates, weights=candidate_weights, k=1)[0])


class RandomBot:
    """Picks random valid actions, but prioritizes shooting when available"""

    def select_action(self, valid_actions: List[int]) -> int:
        if not valid_actions:
            raise ValueError("RandomBot.select_action requires at least one valid action")
        return random.choice(valid_actions)

    def select_action_with_state(self, valid_actions: List[int], game_state) -> int:
        """Phase-aware selection to avoid deployment/shooting action index ambiguity."""
        if not valid_actions:
            return WAIT_ACTION
        phase = require_key(game_state, "phase")
        if phase == "deployment":
            deploy_actions = [a for a in DEPLOYMENT_ACTIONS if a in valid_actions]
            if deploy_actions:
                return random.choice(deploy_actions)
            return random.choice(valid_actions)
        if phase == "shoot":
            shoot_actions = [a for a in mi.SHOOT_SLOTS if a in valid_actions]
            if shoot_actions:
                return random.choice(shoot_actions)
            if WAIT_ACTION in valid_actions:
                return WAIT_ACTION
            return random.choice(valid_actions)
        if WAIT_ACTION in valid_actions:
            non_wait_actions = [a for a in valid_actions if a != WAIT_ACTION]
            if non_wait_actions:
                return random.choice(non_wait_actions)
        return random.choice(valid_actions)

    def select_movement_destination(self, unit, valid_destinations: List[Tuple[int, int]], game_state=None) -> Tuple[int, int]:
        if valid_destinations:
            return random.choice(valid_destinations)
        if game_state is not None:
            return require_unit_position(unit, game_state)
        return get_unit_coordinates(unit)

    def select_shooting_target(self, valid_targets: List[str]) -> str:
        return random.choice(valid_targets) if valid_targets else ""


class GreedyBot:
    """Shoots nearest enemy, moves toward closest target"""

    def __init__(self, randomness: float = 0.0):
        """
        Initialize GreedyBot with optional randomness.

        Args:
            randomness: Probability [0.0-1.0] of making a random move instead of greedy choice.
                       0.0 = pure greedy, 0.15 = 15% random actions (recommended for training)
        """
        self.randomness = max(0.0, min(1.0, randomness))  # Clamp to [0, 1]
        self._deployment_last_action: Optional[int] = None
        self._deployment_repeat_count = 0
        self._deployment_episode_marker: Optional[Any] = None

    def select_action(self, valid_actions: List[int]) -> int:
        # Add randomness to prevent overfitting
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_actions) if valid_actions else WAIT_ACTION

        # Repli stateless (jamais utilise en move : le move passe par
        # select_movement_destination). Prefer shoot > wait/first.
        shoot = _first_action_in(valid_actions, mi.SHOOT_SLOTS)
        if shoot is not None:
            return shoot
        return valid_actions[0] if valid_actions else WAIT_ACTION

    def select_action_with_state(self, valid_actions: List[int], game_state) -> int:
        """Phase-aware greedy policy. Le move est routee par le wrapper vers
        select_movement_destination : cette methode ne traite plus la phase move."""
        if not valid_actions:
            return WAIT_ACTION
        phase = require_key(game_state, "phase")
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_actions)
        if phase == "deployment":
            episode_marker = game_state.get("episode_number")
            if self._deployment_episode_marker != episode_marker:
                self._deployment_episode_marker = episode_marker
                self._deployment_last_action = None
                self._deployment_repeat_count = 0
            deployment_weights = {
                DEPLOYMENT_ACTIONS[0]: 0.30,  # aggressive front
                DEPLOYMENT_ACTIONS[1]: 0.30,  # objective pressure
                DEPLOYMENT_ACTIONS[2]: 0.20,  # safe/cohesion
                DEPLOYMENT_ACTIONS[3]: 0.10,  # left flank
                DEPLOYMENT_ACTIONS[4]: 0.10,  # right flank
            }
            chosen = _select_weighted_deployment_action(
                valid_actions=valid_actions,
                weights_by_action=deployment_weights,
                last_action=self._deployment_last_action,
                repeat_count=self._deployment_repeat_count,
                max_repeat=2,
            )
            if self._deployment_last_action == chosen:
                self._deployment_repeat_count += 1
            else:
                self._deployment_last_action = chosen
                self._deployment_repeat_count = 1
            return chosen
        if phase == "shoot":
            shoot = _first_action_in(valid_actions, mi.SHOOT_SLOTS)
            if shoot is not None:
                return shoot
            if WAIT_ACTION in valid_actions:
                return WAIT_ACTION
            return valid_actions[0]
        if WAIT_ACTION in valid_actions and len(valid_actions) > 1:
            return valid_actions[0] if valid_actions[0] != WAIT_ACTION else valid_actions[1]
        return valid_actions[0]

    def select_movement_destination(self, unit, valid_destinations: List[Tuple[int, int]], game_state=None) -> Tuple[int, int]:
        """Greedy : pousse vers l'ennemi le plus proche (poussee offensive)."""
        if not valid_destinations:
            if game_state is not None:
                return require_unit_position(unit, game_state)
            return get_unit_coordinates(unit)

        # Add randomness to movement
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_destinations)

        if game_state is None:
            return valid_destinations[0]
        return _dest_toward_enemies(valid_destinations, unit, game_state)

    def select_shooting_target(self, valid_targets: List[str], game_state=None) -> str:
        """
        Greedy target selection: prioritize low HP enemies.
        If game_state provided, actually check HP. Otherwise use first target.
        """
        if not valid_targets:
            return ""

        # Add randomness to target selection
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_targets)

        if game_state:
            min_hp = float('inf')
            best_target = valid_targets[0]

            for target_id in valid_targets:
                target = self._get_unit_by_id(game_state, target_id)
                if target and is_unit_alive(str(target["id"]), game_state):
                    hp = get_hp_from_cache(str(target["id"]), game_state)
                    if hp is not None and hp < min_hp:
                        min_hp = hp
                        best_target = target_id

            return best_target

        return valid_targets[0]
    
    def _get_unit_by_id(self, game_state, unit_id: str):
        """Helper to find unit by ID."""
        for unit in require_key(game_state, 'units'):
            if str(unit['id']) == str(unit_id):
                return unit
        return None


class DefensiveBot:
    """Prioritizes survival, maintains distance"""

    def __init__(self, randomness: float = 0.0):
        """
        Initialize DefensiveBot with optional randomness.

        Args:
            randomness: Probability [0.0-1.0] of making a random move instead of defensive choice.
                       0.0 = pure defensive, 0.15 = 15% random actions (recommended for training)
        """
        self.randomness = max(0.0, min(1.0, randomness))  # Clamp to [0, 1]
        self._deployment_last_action: Optional[int] = None
        self._deployment_repeat_count = 0
        self._deployment_episode_marker: Optional[Any] = None

    def select_action(self, valid_actions: List[int]) -> int:
        # Add randomness to prevent overfitting
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_actions) if valid_actions else WAIT_ACTION

        # Conservative: shoot when possible, otherwise wait
        shoot = _first_action_in(valid_actions, mi.SHOOT_SLOTS)
        if shoot is not None:
            return shoot
        if WAIT_ACTION in valid_actions:
            return WAIT_ACTION
        return valid_actions[0] if valid_actions else WAIT_ACTION
    
    def select_movement_destination(self, unit, valid_destinations: List[Tuple[int, int]], game_state=None) -> Tuple[int, int]:
        """Defensif : s'eloigne de l'ennemi le plus proche (maintien de distance)."""
        if not valid_destinations:
            if game_state is not None:
                return require_unit_position(unit, game_state)
            return get_unit_coordinates(unit)

        # Add randomness to movement
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_destinations)

        if game_state is None:
            return valid_destinations[0]
        return _dest_away_from_enemies(valid_destinations, unit, game_state)

    def select_shooting_target(self, valid_targets: List[str]) -> str:
        if not valid_targets:
            return ""

        # Add randomness to target selection
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_targets)

        # Shoot first available target
        return valid_targets[0]
    
    def select_action_with_state(self, valid_actions: List[int], game_state) -> int:
        """
        Enhanced defensive logic with threat awareness.
        Prioritize shooting threats, move away from danger zones.
        """
        if not valid_actions:
            return WAIT_ACTION
        phase = require_key(game_state, "phase")
        if phase == "deployment":
            episode_marker = game_state.get("episode_number")
            if self._deployment_episode_marker != episode_marker:
                self._deployment_episode_marker = episode_marker
                self._deployment_last_action = None
                self._deployment_repeat_count = 0
            deployment_weights = {
                DEPLOYMENT_ACTIONS[0]: 0.20,  # aggressive front
                DEPLOYMENT_ACTIONS[1]: 0.25,  # objective pressure
                DEPLOYMENT_ACTIONS[2]: 0.35,  # safe/cohesion
                DEPLOYMENT_ACTIONS[3]: 0.10,  # left flank
                DEPLOYMENT_ACTIONS[4]: 0.10,  # right flank
            }
            chosen = _select_weighted_deployment_action(
                valid_actions=valid_actions,
                weights_by_action=deployment_weights,
                last_action=self._deployment_last_action,
                repeat_count=self._deployment_repeat_count,
                max_repeat=2,
            )
            if self._deployment_last_action == chosen:
                self._deployment_repeat_count += 1
            else:
                self._deployment_last_action = chosen
                self._deployment_repeat_count = 1
            return chosen

        current_player = require_key(game_state, 'current_player')
        
        active_unit = None
        for unit in require_key(game_state, 'units'):
            if unit['player'] == current_player and is_unit_alive(str(unit["id"]), game_state):
                active_unit = unit
                break
        
        if not active_unit:
            return valid_actions[0]
        
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_actions)

        nearby_threats = self._count_nearby_threats(active_unit, game_state)

        # La phase move est routee par le wrapper vers select_movement_destination (repli
        # geometrique) : cette methode ne la traite plus.

        if phase == "shoot":
            shoot = _first_action_in(valid_actions, mi.SHOOT_SLOTS)
            if shoot is not None:
                return shoot
            if WAIT_ACTION in valid_actions:
                return WAIT_ACTION
            return valid_actions[0]

        shoot = _first_action_in(valid_actions, mi.SHOOT_SLOTS)
        if nearby_threats > 0 and shoot is not None:
            return shoot

        if WAIT_ACTION in valid_actions:
            return WAIT_ACTION
        return valid_actions[0]
    
    def _count_nearby_threats(self, unit, game_state) -> int:
        """Count enemy units within threatening range."""
        threat_count = 0
        _scale = game_state["inches_to_subhex"]
        threat_range = 12 * _scale
        units_cache = game_state["units_cache"]
        unit_entry = units_cache.get(str(unit["id"]))
        unit_fp = unit_entry.get("occupied_hexes", {(unit["col"], unit["row"])}) if unit_entry else {(unit["col"], unit["row"])}

        for enemy in require_key(game_state, 'units'):
            if enemy['player'] != unit['player'] and is_unit_alive(str(enemy["id"]), game_state):
                enemy_entry = units_cache.get(str(enemy["id"]))
                enemy_fp = enemy_entry.get("occupied_hexes", {(enemy["col"], enemy["row"])}) if enemy_entry else {(enemy["col"], enemy["row"])}
                distance = min_distance_between_sets(unit_fp, enemy_fp, max_distance=threat_range)
                if distance <= threat_range:
                    threat_count += 1

        return threat_count


class ControlBot:
    """
    Objective-focused bot that prioritizes capturing and holding control points.

    Strategy:
    - MOVE: Move toward nearest uncontrolled/enemy objective (action 0 aggressive
      when objectives are between us and enemies, action 1 tactical otherwise).
      Hold position (WAIT) when already on an objective.
    - SHOOT: Prioritize enemies near objectives (contesting control).
    - CHARGE/FIGHT: Only engage to defend or contest an objective.
    - DEPLOYMENT: Weighted toward objective pressure.
    """

    def __init__(self, randomness: float = 0.0):
        """
        Initialize ControlBot with optional randomness.

        Args:
            randomness: Probability [0.0-1.0] of making a random action.
        """
        self.randomness = max(0.0, min(1.0, randomness))
        self._deployment_last_action: Optional[int] = None
        self._deployment_repeat_count = 0
        self._deployment_episode_marker: Optional[Any] = None

    def select_action(self, valid_actions: List[int]) -> int:
        """Action selection when only the valid action list is available (no game_state)."""
        if not valid_actions:
            return WAIT_ACTION
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_actions)
        shoot = _first_action_in(valid_actions, mi.SHOOT_SLOTS)
        if shoot is not None:
            return shoot
        return valid_actions[0]

    def select_action_with_state(self, valid_actions: List[int], game_state) -> int:
        """Objective-aware action selection. Le move est routee par le wrapper vers
        select_movement_destination : cette methode ne traite plus la phase move."""
        if not valid_actions:
            return WAIT_ACTION
        phase = require_key(game_state, "phase")

        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_actions)

        if phase == "deployment":
            return self._deployment_action(valid_actions, game_state)

        current_player = require_key(game_state, "current_player")
        active_unit = self._find_active_unit(game_state, current_player)
        if not active_unit:
            return valid_actions[0]

        on_objective = self._is_on_objective(active_unit, game_state)

        if phase == "shoot":
            return self._shoot_action(valid_actions)
        if phase == "charge":
            if on_objective and WAIT_ACTION in valid_actions:
                return WAIT_ACTION
            if mi.ACTION_CHARGE in valid_actions:
                return mi.ACTION_CHARGE
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]
        if phase == "fight":
            if mi.ACTION_FIGHT in valid_actions:
                return mi.ACTION_FIGHT
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

        return valid_actions[0]

    def _deployment_action(self, valid_actions: List[int], game_state) -> int:
        """Deploy with bias toward objectives."""
        episode_marker = game_state.get("episode_number")
        if self._deployment_episode_marker != episode_marker:
            self._deployment_episode_marker = episode_marker
            self._deployment_last_action = None
            self._deployment_repeat_count = 0
        deployment_weights = {
            DEPLOYMENT_ACTIONS[0]: 0.15,
            DEPLOYMENT_ACTIONS[1]: 0.45,
            DEPLOYMENT_ACTIONS[2]: 0.20,
            DEPLOYMENT_ACTIONS[3]: 0.10,
            DEPLOYMENT_ACTIONS[4]: 0.10,
        }
        chosen = _select_weighted_deployment_action(
            valid_actions=valid_actions,
            weights_by_action=deployment_weights,
            last_action=self._deployment_last_action,
            repeat_count=self._deployment_repeat_count,
            max_repeat=2,
        )
        if self._deployment_last_action == chosen:
            self._deployment_repeat_count += 1
        else:
            self._deployment_last_action = chosen
            self._deployment_repeat_count = 1
        return chosen

    def select_movement_destination(self, unit, valid_destinations: List[Tuple[int, int]], game_state=None) -> Tuple[int, int]:
        """Vers l'objectif le plus proche ; tient sa position s'il est deja dessus.

        « Tenir » = renvoyer l'hex courant (le wrapper le traduit en WAIT), `start_pos` etant
        exclu du pool donc jamais une destination legale.
        """
        if not valid_destinations:
            if game_state is not None:
                return require_unit_position(unit, game_state)
            return get_unit_coordinates(unit)
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_destinations)
        if game_state is None:
            return valid_destinations[0]
        if self._is_on_objective(unit, game_state):
            return require_unit_position(unit, game_state)
        return _dest_toward_objective(valid_destinations, unit, game_state)

    def _shoot_action(self, valid_actions: List[int]) -> int:
        """Shoot whenever possible."""
        shoot = _first_action_in(valid_actions, mi.SHOOT_SLOTS)
        if shoot is not None:
            return shoot
        if WAIT_ACTION in valid_actions:
            return WAIT_ACTION
        return valid_actions[0]

    def _find_active_unit(
        self, game_state: Dict[str, Any], current_player: int
    ) -> Optional[Dict[str, Any]]:
        """Return the first living unit for current_player."""
        for unit in require_key(game_state, "units"):
            if unit["player"] == current_player and is_unit_alive(str(unit["id"]), game_state):
                return unit
        return None

    def _is_on_objective(self, unit: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
        """Check if unit is standing on an objective hex."""
        objectives = game_state.get("objectives")
        if not objectives:
            return False
        unit_col, unit_row = get_unit_coordinates(unit)
        for obj in objectives:
            if not isinstance(obj, dict):
                continue
            _hx = obj.get("hexes")
            hexes = _hx if isinstance(_hx, list) else []
            for h in hexes:
                if isinstance(h, dict):
                    if unit_col == int(h.get("col", -1)) and unit_row == int(h.get("row", -1)):
                        return True
                elif isinstance(h, (list, tuple)) and len(h) == 2:
                    if unit_col == int(h[0]) and unit_row == int(h[1]):
                        return True
        return False


# ---------------------------------------------------------------------------
# PALIER 2 — Smart bots with focus-fire, advance and charge awareness
# ---------------------------------------------------------------------------

def _find_active_unit_for_bot(
    game_state: Dict[str, Any], current_player: int
) -> Optional[Dict[str, Any]]:
    """Return the active eligible unit for *current_player* (first alive)."""
    for unit in require_key(game_state, "units"):
        if unit["player"] == current_player and is_unit_alive(str(unit["id"]), game_state):
            return unit
    return None


def _best_target_slot_by_hp(
    active_unit: Dict[str, Any], game_state: Dict[str, Any]
) -> Optional[int]:
    """Return the target slot index (0-4) of the lowest-HP target, or None."""
    pool = active_unit.get("valid_target_pool")
    if not pool:
        return None
    best_slot = 0
    best_hp = float("inf")
    for slot, target_id in enumerate(pool):
        hp = get_hp_from_cache(str(target_id), game_state)
        if hp is not None and hp < best_hp:
            best_hp = hp
            best_slot = slot
    return best_slot


def _best_target_slot_by_threat(
    active_unit: Dict[str, Any], game_state: Dict[str, Any]
) -> Optional[int]:
    """Return the target slot of the highest-threat enemy (most damage output)."""
    pool = active_unit.get("valid_target_pool")
    if not pool:
        return None
    best_slot = 0
    best_threat = -1.0
    units_cache = require_key(game_state, "units_cache")
    for slot, target_id in enumerate(pool):
        tid = str(target_id)
        hp = get_hp_from_cache(tid, game_state)
        if hp is None:
            continue
        cache_entry = units_cache.get(tid)
        if cache_entry is None:
            continue
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md : RNG_DMG/CC_DMG ont ete SUPPRIMES du contrat
        # d'unite. La menace se calcule desormais sur les tableaux d'armes (NB x DMG attendu),
        # meme source que RewardMapper._get_unit_threat.
        threat = max(get_max_ranged_damage(cache_entry), get_max_melee_damage(cache_entry))
        if threat > best_threat:
            best_threat = threat
            best_slot = slot
    return best_slot


def _shoot_focus_fire(
    valid_actions: List[int],
    active_unit: Optional[Dict[str, Any]],
    game_state: Dict[str, Any],
    target_fn=_best_target_slot_by_hp,
) -> int:
    """Pick the shoot action (19-23) for the best target, else the first available shoot slot."""
    if active_unit is not None:
        slot = target_fn(active_unit, game_state)
        if slot is not None:
            action = mi.SHOOT_SLOT_BASE + slot
            if action in valid_actions:
                return action
    shoot = _first_action_in(valid_actions, mi.SHOOT_SLOTS)
    if shoot is not None:
        return shoot
    return WAIT_ACTION


def _count_objectives_controlled(game_state: Dict[str, Any], player: int) -> int:
    """Count how many objectives have at least one friendly unit on them."""
    objectives = game_state.get("objectives")
    if not objectives:
        return 0
    units_cache = require_key(game_state, "units_cache")
    friendly_positions: set = set()
    for uid, entry in units_cache.items():
        if int(entry.get("player", -1)) == player:
            friendly_positions.add((int(entry["col"]), int(entry["row"])))

    controlled = 0
    for obj in objectives:
        if isinstance(obj, dict):
            _oh = obj.get("hexes")
            hexes = _oh if isinstance(_oh, list) else []
        else:
            hexes = []
        for h in hexes:
            if isinstance(h, dict):
                pos = (int(h["col"]), int(h["row"]))
            elif isinstance(h, (list, tuple)) and len(h) == 2:
                pos = (int(h[0]), int(h[1]))
            else:
                continue
            if pos in friendly_positions:
                controlled += 1
                break
    return controlled


class AggressiveSmartBot:
    """
    Palier 2 — Aggressive with intelligence.

    Always pushes forward, uses advance when no targets, charges every chance,
    and focus-fires the lowest HP enemy to maximise kills.
    """

    def __init__(self, randomness: float = 0.0):
        self.randomness = max(0.0, min(1.0, randomness))
        self._deployment_last_action: Optional[int] = None
        self._deployment_repeat_count = 0
        self._deployment_episode_marker: Optional[Any] = None

    def select_action(self, valid_actions: List[int]) -> int:
        if not valid_actions:
            return WAIT_ACTION
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_actions)
        shoot = _first_action_in(valid_actions, mi.SHOOT_SLOTS)
        if shoot is not None:
            return shoot
        return valid_actions[0]

    def select_action_with_state(self, valid_actions: List[int], game_state) -> int:
        if not valid_actions:
            return WAIT_ACTION
        phase = require_key(game_state, "phase")

        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_actions)

        if phase == "deployment":
            return self._deploy(valid_actions, game_state)

        current_player = require_key(game_state, "current_player")
        active = _find_active_unit_for_bot(game_state, current_player)

        # La phase move est routee par le wrapper vers select_movement_destination.

        if phase == "shoot":
            if any(a in valid_actions for a in mi.SHOOT_SLOTS):
                return _shoot_focus_fire(valid_actions, active, game_state, _best_target_slot_by_hp)
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

        if phase == "charge":
            if mi.ACTION_CHARGE in valid_actions:
                return mi.ACTION_CHARGE
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

        if phase == "fight":
            if mi.ACTION_FIGHT in valid_actions:
                return mi.ACTION_FIGHT
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

        return valid_actions[0]

    def select_movement_destination(self, unit, valid_destinations: List[Tuple[int, int]], game_state=None) -> Tuple[int, int]:
        """Agressif : pousse toujours vers l'ennemi le plus proche."""
        if not valid_destinations:
            if game_state is not None:
                return require_unit_position(unit, game_state)
            return get_unit_coordinates(unit)
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_destinations)
        if game_state is None:
            return valid_destinations[0]
        return _dest_toward_enemies(valid_destinations, unit, game_state)

    def _deploy(self, valid_actions: List[int], game_state) -> int:
        episode_marker = game_state.get("episode_number")
        if self._deployment_episode_marker != episode_marker:
            self._deployment_episode_marker = episode_marker
            self._deployment_last_action = None
            self._deployment_repeat_count = 0
        weights = {
            DEPLOYMENT_ACTIONS[0]: 0.50,
            DEPLOYMENT_ACTIONS[1]: 0.20,
            DEPLOYMENT_ACTIONS[2]: 0.10,
            DEPLOYMENT_ACTIONS[3]: 0.10,
            DEPLOYMENT_ACTIONS[4]: 0.10,
        }
        chosen = _select_weighted_deployment_action(
            valid_actions=valid_actions,
            weights_by_action=weights,
            last_action=self._deployment_last_action,
            repeat_count=self._deployment_repeat_count,
            max_repeat=2,
        )
        if self._deployment_last_action == chosen:
            self._deployment_repeat_count += 1
        else:
            self._deployment_last_action = chosen
            self._deployment_repeat_count = 1
        return chosen


class DefensiveSmartBot:
    """
    Palier 2 — Defensive with intelligence.

    Keeps distance, never charges or advances, focus-fires the highest-threat
    enemy to neutralise damage sources.
    """

    def __init__(self, randomness: float = 0.0):
        self.randomness = max(0.0, min(1.0, randomness))
        self._deployment_last_action: Optional[int] = None
        self._deployment_repeat_count = 0
        self._deployment_episode_marker: Optional[Any] = None

    def select_action(self, valid_actions: List[int]) -> int:
        if not valid_actions:
            return WAIT_ACTION
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_actions)
        shoot = _first_action_in(valid_actions, mi.SHOOT_SLOTS)
        if shoot is not None:
            return shoot
        if WAIT_ACTION in valid_actions:
            return WAIT_ACTION
        return valid_actions[0]

    def select_action_with_state(self, valid_actions: List[int], game_state) -> int:
        if not valid_actions:
            return WAIT_ACTION
        phase = require_key(game_state, "phase")

        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_actions)

        if phase == "deployment":
            return self._deploy(valid_actions, game_state)

        current_player = require_key(game_state, "current_player")
        active = _find_active_unit_for_bot(game_state, current_player)

        # La phase move est routee par le wrapper vers select_movement_destination (repli).

        if phase == "shoot":
            if any(a in valid_actions for a in mi.SHOOT_SLOTS):
                return _shoot_focus_fire(valid_actions, active, game_state, _best_target_slot_by_threat)
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

        if phase == "charge":
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

        if phase == "fight":
            if mi.ACTION_FIGHT in valid_actions:
                return mi.ACTION_FIGHT
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

        return valid_actions[0]

    def select_movement_destination(self, unit, valid_destinations: List[Tuple[int, int]], game_state=None) -> Tuple[int, int]:
        """Defensif : garde ses distances, s'eloigne de l'ennemi le plus proche."""
        if not valid_destinations:
            if game_state is not None:
                return require_unit_position(unit, game_state)
            return get_unit_coordinates(unit)
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_destinations)
        if game_state is None:
            return valid_destinations[0]
        return _dest_away_from_enemies(valid_destinations, unit, game_state)

    def _deploy(self, valid_actions: List[int], game_state) -> int:
        episode_marker = game_state.get("episode_number")
        if self._deployment_episode_marker != episode_marker:
            self._deployment_episode_marker = episode_marker
            self._deployment_last_action = None
            self._deployment_repeat_count = 0
        weights = {
            DEPLOYMENT_ACTIONS[0]: 0.10,
            DEPLOYMENT_ACTIONS[1]: 0.20,
            DEPLOYMENT_ACTIONS[2]: 0.45,
            DEPLOYMENT_ACTIONS[3]: 0.10,
            DEPLOYMENT_ACTIONS[4]: 0.15,
        }
        chosen = _select_weighted_deployment_action(
            valid_actions=valid_actions,
            weights_by_action=weights,
            last_action=self._deployment_last_action,
            repeat_count=self._deployment_repeat_count,
            max_repeat=2,
        )
        if self._deployment_last_action == chosen:
            self._deployment_repeat_count += 1
        else:
            self._deployment_last_action = chosen
            self._deployment_repeat_count = 1
        return chosen


class AdaptiveBot:
    """
    Palier 2 — Adapts strategy to game state.

    - Early turns (1-2): rush objectives (action 3), charge to contest.
    - Late turns winning: defensive hold, no advance/charge.
    - Late turns losing: ultra-aggressive, advance + charge + focus fire.
    Focus-fires lowest HP target throughout.
    """

    EARLY_TURN_THRESHOLD = 2

    def __init__(self, randomness: float = 0.0):
        self.randomness = max(0.0, min(1.0, randomness))
        self._deployment_last_action: Optional[int] = None
        self._deployment_repeat_count = 0
        self._deployment_episode_marker: Optional[Any] = None

    def select_action(self, valid_actions: List[int]) -> int:
        if not valid_actions:
            return WAIT_ACTION
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_actions)
        shoot = _first_action_in(valid_actions, mi.SHOOT_SLOTS)
        if shoot is not None:
            return shoot
        return valid_actions[0]

    def select_action_with_state(self, valid_actions: List[int], game_state) -> int:
        if not valid_actions:
            return WAIT_ACTION
        phase = require_key(game_state, "phase")

        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_actions)

        if phase == "deployment":
            return self._deploy(valid_actions, game_state)

        current_player = require_key(game_state, "current_player")
        active = _find_active_unit_for_bot(game_state, current_player)
        turn = int(game_state.get("turn", 1))
        posture = self._evaluate_posture(game_state, current_player, turn)

        # La phase move est routee par le wrapper vers select_movement_destination (posture).
        if phase == "shoot":
            return self._shoot(valid_actions, active, game_state, posture)
        if phase == "charge":
            return self._charge(valid_actions, posture)
        if phase == "fight":
            if mi.ACTION_FIGHT in valid_actions:
                return mi.ACTION_FIGHT
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

        return valid_actions[0]

    def _evaluate_posture(self, game_state: Dict[str, Any], player: int, turn: int) -> str:
        """Return 'early', 'winning', or 'losing'."""
        if turn <= self.EARLY_TURN_THRESHOLD:
            return "early"
        my_obj = _count_objectives_controlled(game_state, player)
        enemy_obj = _count_objectives_controlled(game_state, 1 - player)
        if my_obj > enemy_obj:
            return "winning"
        return "losing"

    def select_movement_destination(self, unit, valid_destinations: List[Tuple[int, int]], game_state=None) -> Tuple[int, int]:
        """Destination selon la posture (le type de move est infere par le moteur) :
        early -> rush objectif ; losing -> pousse vers l'ennemi ; winning -> garde ses distances.
        """
        if not valid_destinations:
            if game_state is not None:
                return require_unit_position(unit, game_state)
            return get_unit_coordinates(unit)
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_destinations)
        if game_state is None:
            return valid_destinations[0]
        current_player = require_key(game_state, "current_player")
        turn = int(game_state.get("turn", 1))
        posture = self._evaluate_posture(game_state, current_player, turn)
        if posture == "winning":
            return _dest_away_from_enemies(valid_destinations, unit, game_state)
        if posture == "early":
            return _dest_toward_objective(valid_destinations, unit, game_state)
        return _dest_toward_enemies(valid_destinations, unit, game_state)

    def _shoot(
        self,
        valid_actions: List[int],
        active: Optional[Dict[str, Any]],
        game_state: Dict[str, Any],
        posture: str,
    ) -> int:
        if any(a in valid_actions for a in mi.SHOOT_SLOTS):
            return _shoot_focus_fire(valid_actions, active, game_state, _best_target_slot_by_hp)
        return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

    def _charge(self, valid_actions: List[int], posture: str) -> int:
        if posture != "winning" and mi.ACTION_CHARGE in valid_actions:
            return mi.ACTION_CHARGE
        return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

    def _deploy(self, valid_actions: List[int], game_state) -> int:
        episode_marker = game_state.get("episode_number")
        if self._deployment_episode_marker != episode_marker:
            self._deployment_episode_marker = episode_marker
            self._deployment_last_action = None
            self._deployment_repeat_count = 0
        weights = {
            DEPLOYMENT_ACTIONS[0]: 0.25,
            DEPLOYMENT_ACTIONS[1]: 0.35,
            DEPLOYMENT_ACTIONS[2]: 0.20,
            DEPLOYMENT_ACTIONS[3]: 0.10,
            DEPLOYMENT_ACTIONS[4]: 0.10,
        }
        chosen = _select_weighted_deployment_action(
            valid_actions=valid_actions,
            weights_by_action=weights,
            last_action=self._deployment_last_action,
            repeat_count=self._deployment_repeat_count,
            max_repeat=2,
        )
        if self._deployment_last_action == chosen:
            self._deployment_repeat_count += 1
        else:
            self._deployment_last_action = chosen
            self._deployment_repeat_count = 1
        return chosen


class TacticalBot:
    """
    Advanced tactical bot that properly uses all 4 game phases.

    This is the hardest bot to beat - it makes optimal decisions in each phase:
    - MOVE: Advances toward enemies if out of range, retreats if wounded
    - SHOOT: Always shoots if targets available, prioritizes wounded enemies
    - CHARGE: Charges if melee is advantageous (degats melee attendus > degats de tir)
    - FIGHT: Always fights when in melee, prioritizes killing wounded enemies

    Use this bot to test if agents learn proper multi-phase coordination.
    """

    def __init__(self, randomness: float = 0.1):
        """
        Initialize TacticalBot.

        Args:
            randomness: Probability [0.0-1.0] of making suboptimal choice.
                       0.1 = 10% random (recommended for training diversity)
        """
        self.randomness = max(0.0, min(1.0, randomness))

    def select_action(self, valid_actions: List[int], game_state: Optional[Dict] = None, phase: Optional[str] = None) -> int:
        """
        Select action based on current phase and game state.

        Args:
            valid_actions: List of valid action indices
            game_state: Current game state (required for smart decisions)
            phase: Current phase ('move', 'shoot', 'charge', 'fight')
        """
        if not valid_actions:
            return WAIT_ACTION  # Wait

        # Random action for diversity
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_actions)

        # Phase-specific logic
        if phase == 'move':
            return self._select_move_action(valid_actions, game_state)
        elif phase == 'shoot':
            return self._select_shoot_action(valid_actions, game_state)
        elif phase == 'charge':
            return self._select_charge_action(valid_actions, require_present(game_state, "game_state"))
        elif phase == 'fight':
            return self._select_fight_action(valid_actions, game_state)
        else:
            # Prefer combat actions when phase is unknown
            shoot = _first_action_in(valid_actions, mi.SHOOT_SLOTS)
            if shoot is not None:  # Shoot
                return shoot
            if mi.ACTION_CHARGE in valid_actions:  # Charge
                return mi.ACTION_CHARGE
            if mi.ACTION_FIGHT in valid_actions:  # Fight
                return mi.ACTION_FIGHT
            return valid_actions[0]

    def _select_move_action(self, valid_actions: List[int], game_state: Optional[Dict]) -> int:
        """Movement phase (repli stateless). Le move spatial passe par
        select_movement_destination : ici on prefere agir plutot qu'attendre."""
        non_wait = [a for a in valid_actions if a != WAIT_ACTION]
        if non_wait:
            return non_wait[0]
        if WAIT_ACTION in valid_actions:  # Wait
            return WAIT_ACTION
        return valid_actions[0] if valid_actions else WAIT_ACTION

    def _select_shoot_action(self, valid_actions: List[int], game_state: Optional[Dict]) -> int:
        """Shooting phase: always shoot if targets available."""
        shoot = _first_action_in(valid_actions, mi.SHOOT_SLOTS)
        if shoot is not None:  # Shoot
            return shoot
        if WAIT_ACTION in valid_actions:  # Wait/Skip
            return WAIT_ACTION
        return valid_actions[0] if valid_actions else WAIT_ACTION

    def _select_charge_action(self, valid_actions: List[int], game_state: Dict) -> int:
        """Charge phase: charge if melee is advantageous."""
        # Check if charging is beneficial
        if game_state and mi.ACTION_CHARGE in valid_actions:
            active_unit = self._get_active_unit(game_state)
            if active_unit:
                # Charge si la melee est AVANTAGEUSE (cf. docstring de la classe).
                # L'ancien critere `CC_DMG >= 2` portait sur un degat PAR TOUCHE d'un champ
                # supprime ; transpose tel quel sur NB x DMG il serait vrai presque toujours.
                # Le critere porte donc sur la comparaison melee vs tir, qui est la question
                # que le bot pose reellement.
                if get_max_melee_damage(active_unit) > get_max_ranged_damage(active_unit):
                    return mi.ACTION_CHARGE

        # Skip charge if not beneficial
        if WAIT_ACTION in valid_actions:
            return WAIT_ACTION
        return valid_actions[0] if valid_actions else WAIT_ACTION

    def _select_fight_action(self, valid_actions: List[int], game_state: Optional[Dict]) -> int:
        """Fight phase: always fight when in melee."""
        if mi.ACTION_FIGHT in valid_actions:  # Fight
            return mi.ACTION_FIGHT
        if WAIT_ACTION in valid_actions:  # Wait
            return WAIT_ACTION
        return valid_actions[0] if valid_actions else WAIT_ACTION

    def select_movement_destination(self, unit: Dict, valid_destinations: List[Tuple[int, int]],
                                     game_state: Optional[Dict] = None) -> Tuple[int, int]:
        """
        Select best movement destination.

        Strategy:
        - If no enemies in range: move toward nearest enemy
        - If enemies in range: move to position with best LoS
        - If wounded: move away from melee threats
        """
        if not valid_destinations:
            if game_state is not None:
                return require_unit_position(unit, game_state)
            return get_unit_coordinates(unit)

        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_destinations)

        if not game_state:
            return valid_destinations[0]

        # Find nearest enemy
        nearest_enemy = self._find_nearest_enemy(unit, game_state)
        if not nearest_enemy:
            return valid_destinations[0]

        # If wounded (< 50% HP), move away from melee units. Skip if unit dead (not in cache).
        hp_cur = get_hp_from_cache(str(unit["id"]), game_state)
        if hp_cur is None:
            return valid_destinations[0]
        hp_max = require_key(unit, "HP_MAX")
        if hp_max <= 0 or hp_cur < hp_max * 0.5:
            return self._find_safest_position(unit, valid_destinations, game_state)

        # Otherwise, move toward optimal shooting range
        return self._find_best_offensive_position(unit, valid_destinations, nearest_enemy, game_state)

    def select_shooting_target(self, valid_targets: List[str], game_state: Optional[Dict] = None) -> str:
        """
        Select best shooting target.

        Priority:
        1. Target that can be killed this turn (HP <= our damage)
        2. Lowest HP target (focus fire)
        3. Highest threat target (highest damage output)
        """
        if not valid_targets:
            return ""

        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_targets)

        if not game_state:
            return valid_targets[0]

        active_unit = self._get_active_unit(game_state)
        if not active_unit:
            return valid_targets[0]

        # Degats de tir attendus sur une phase (NB x DMG) — comparables a des HP, donc le test
        # `hp <= our_damage` ci-dessous est plus juste qu'avec l'ancien degat par touche.
        our_damage = get_max_ranged_damage(active_unit)
        best_target = valid_targets[0]
        best_score = -float('inf')

        for target_id in valid_targets:
            target = self._get_unit_by_id(game_state, target_id)
            if not target or not is_unit_alive(str(target["id"]), game_state):
                continue

            hp = get_hp_from_cache(str(target["id"]), game_state)
            if hp is None:
                continue
            threat = max(get_max_ranged_damage(target), get_max_melee_damage(target))

            # Scoring: killable > low HP > high threat
            score = 0
            if hp <= our_damage:
                score += 1000  # Can kill
            score += (10 - hp) * 10  # Lower HP = higher score
            score += threat * 5  # Higher threat = higher score

            if score > best_score:
                best_score = score
                best_target = target_id

        return best_target

    def select_charge_target(self, valid_targets: List[str], game_state: Optional[Dict] = None) -> str:
        """
        Select best charge target.

        Priority:
        1. Target that can be killed in melee
        2. Highest threat ranged unit (silence their guns)
        """
        if not valid_targets:
            return ""

        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_targets)

        if not game_state:
            return valid_targets[0]

        active_unit = self._get_active_unit(game_state)
        if not active_unit:
            return valid_targets[0]

        our_melee_damage = get_max_melee_damage(active_unit)
        best_target = valid_targets[0]
        best_score = -float('inf')

        for target_id in valid_targets:
            target = self._get_unit_by_id(game_state, target_id)
            if not target or not is_unit_alive(str(target["id"]), game_state):
                continue

            hp = get_hp_from_cache(str(target["id"]), game_state)
            if hp is None:
                continue
            ranged_threat = get_max_ranged_damage(target)

            # Scoring: killable > high ranged threat
            score = 0
            if hp <= our_melee_damage:
                score += 1000  # Can kill in melee
            score += ranged_threat * 20  # Prioritize silencing ranged units

            if score > best_score:
                best_score = score
                best_target = target_id

        return best_target

    def select_fight_target(self, valid_targets: List[str], game_state: Optional[Dict] = None) -> str:
        """Select best melee target - same logic as shooting but for melee."""
        return self.select_shooting_target(valid_targets, game_state)

    # Helper methods

    def _get_active_unit(self, game_state: Dict) -> Optional[Dict]:
        """Get the currently active unit."""
        current_player = require_key(game_state, 'current_player')
        for unit in require_key(game_state, 'units'):
            if unit.get('player') == current_player and is_unit_alive(str(unit.get("id")), game_state):
                return unit
        return None

    def _get_unit_by_id(self, game_state: Dict, unit_id: str) -> Optional[Dict]:
        """Find unit by ID."""
        for unit in require_key(game_state, 'units'):
            if str(unit.get('id')) == str(unit_id):
                return unit
        return None

    def _find_nearest_enemy(self, unit: Dict, game_state: Dict) -> Optional[Dict]:
        """Find nearest enemy unit."""
        nearest = None
        min_dist = float('inf')
        units_cache = game_state["units_cache"]
        unit_entry = units_cache.get(str(unit.get("id", "")))
        unit_fp = unit_entry.get("occupied_hexes", {(unit["col"], unit["row"])}) if unit_entry else {(unit["col"], unit["row"])}

        for enemy in require_key(game_state, 'units'):
            if enemy.get('player') != unit.get('player') and is_unit_alive(str(enemy.get("id")), game_state):
                enemy_entry = units_cache.get(str(enemy.get("id", "")))
                enemy_fp = enemy_entry.get("occupied_hexes", {(enemy["col"], enemy["row"])}) if enemy_entry else {(enemy["col"], enemy["row"])}
                dist = min_distance_between_sets(unit_fp, enemy_fp)
                if dist < min_dist:
                    min_dist = dist
                    nearest = enemy

        return nearest

    def _find_safest_position(self, unit: Dict, destinations: List[Tuple[int, int]],
                               game_state: Dict) -> Tuple[int, int]:
        """Find position furthest from melee threats."""
        best_pos = destinations[0]
        max_min_dist = -1
        units_cache = game_state["units_cache"]

        for col, row in destinations:
            unit_fp = compute_candidate_footprint(col, row, unit, game_state)
            min_enemy_dist = float('inf')
            for enemy in require_key(game_state, 'units'):
                if enemy.get('player') != unit.get('player') and is_unit_alive(str(enemy.get("id")), game_state):
                    # Only consider melee threats
                    if get_max_melee_damage(enemy) > get_max_ranged_damage(enemy):
                        enemy_entry = units_cache.get(str(enemy.get("id", "")))
                        enemy_fp = enemy_entry.get("occupied_hexes", {(enemy["col"], enemy["row"])}) if enemy_entry else {(enemy["col"], enemy["row"])}
                        dist = min_distance_between_sets(unit_fp, enemy_fp)
                        min_enemy_dist = min(min_enemy_dist, dist)

            if min_enemy_dist > max_min_dist:
                max_min_dist = min_enemy_dist
                best_pos = (col, row)

        return best_pos

    def _find_best_offensive_position(self, unit: Dict, destinations: List[Tuple[int, int]],
                                       target: Dict, game_state: Dict) -> Tuple[int, int]:
        """Find position closest to target but within shooting range."""
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
        from engine.utils.weapon_helpers import get_max_ranged_range
        rng_weapons = require_key(unit, 'RNG_WEAPONS')
        rng_rng = get_max_ranged_range(unit) if rng_weapons else 0
        units_cache = game_state["units_cache"]
        target_entry = units_cache.get(str(target.get("id", "")))
        target_fp = target_entry.get("occupied_hexes", {(target["col"], target["row"])}) if target_entry else {(target["col"], target["row"])}
        best_pos = destinations[0]
        best_dist = float('inf')

        for col, row in destinations:
            unit_fp = compute_candidate_footprint(col, row, unit, game_state)
            dist = min_distance_between_sets(unit_fp, target_fp, max_distance=rng_rng)
            # Prefer positions within shooting range
            if dist <= rng_rng and dist < best_dist:
                best_dist = dist
                best_pos = (col, row)

        # If no position in range, get closest
        if best_dist == float('inf'):
            for col, row in destinations:
                unit_fp = compute_candidate_footprint(col, row, unit, game_state)
                dist = min_distance_between_sets(unit_fp, target_fp)
                if dist < best_dist:
                    best_dist = dist
                    best_pos = (col, row)

        return best_pos