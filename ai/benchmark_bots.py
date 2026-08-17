#!/usr/bin/env python3
"""ai/benchmark_bots.py — Trois benchmarks de holdout a mecanisme de decision DIFFERENT.

CE QUI LES SEPARE DES SIX STYLES D'ENTRAINEMENT (Bot_refactor.md §4.C)
    Les six styles (ai/bot_doctrines.py) evaluent CHAQUE destination par une somme ponderee
    Sigma(poids x features) et choisissent leur cible par un critere unique fixe par la doctrine.
    Les trois benchmarks ne font ni l'un ni l'autre :

    1. Intention macro d'abord, geometrie ensuite. Le bot elit une intention pour l'unite
       (SCORE, DENY, KILL, PRESERVE) a partir de l'etat de partie, PUIS cherche une destination
       coherente avec cette intention. Un bot d'entrainement peut marcher vers un objectif et
       tirer sur autre chose sans jamais s'en apercevoir ; ici l'intention est la contrainte.

    2. Ciblage par swing espere, une seule formule pour les trois :
       P(kill) x VALUE + base_damage, au lieu des quatre criteres du panel d'entrainement.

    3. Aucun de leurs parametres ne vient de config/bot_movement_weights.json. Un benchmark
       regle sur le meme fichier que les bots d'entrainement serait regle en meme temps qu'eux.

CE QUI LES SEPARE ENTRE EUX : l'intention qu'ils privilegient a etat egal.
    reference_balanced  : arbitre en temps reel entre SCORE / KILL / PRESERVE
    reference_denial    : refuse de laisser l'agent marquer (contester, bloquer, cibler les porteurs)
    reference_reactive  : revise son plan sur ce que l'agent VIENT de faire
"""

import random
from typing import Any, Dict, List, Optional, Set, Tuple

from engine.combat_utils import calculate_hex_distance
from engine.game_state import (
    objective_hex_sets, objective_hex_zones, unit_is_within_objective,
)
from engine.phase_handlers.shared_utils import (
    entry_is_on_battlefield, get_hp_from_cache, is_unit_alive,
    require_unit_from_cache, require_unit_position,
)
from engine.weapon_damage_cache import squad_expected_damage
from shared.data_validation import require_key

from ai.evaluation_bots import (
    DEPLOYMENT_ACTIONS, WAIT_ACTION,
    _best_slot_action, _select_weighted_deployment_action,
)
from engine import macro_intents as mi

# ─────────────────────────────────────────────────────────────────────────────────────────────
# Constantes — independantes de config/bot_movement_weights.json
# ─────────────────────────────────────────────────────────────────────────────────────────────

#: Ecart de VP au-dela duquel on considere avoir une avance a proteger.
_VP_LEAD = 12.0

#: Seuil de destruction : VALUE perdue ce tour au-dela de laquelle le reactif bascule de plan.
_VALUE_LOSS_THRESHOLD = 5.0

#: Poids par slot de deploiement — commun aux trois benchmarks.
_BENCHMARK_PLACEMENT_WEIGHTS: Dict[int, float] = {
    DEPLOYMENT_ACTIONS[0]: 0.20,
    DEPLOYMENT_ACTIONS[1]: 0.30,
    DEPLOYMENT_ACTIONS[2]: 0.30,
    DEPLOYMENT_ACTIONS[3]: 0.10,
    DEPLOYMENT_ACTIONS[4]: 0.10,
}


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Primitives communes
# ─────────────────────────────────────────────────────────────────────────────────────────────

def _living_enemies(unit: Dict[str, Any], game_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Escouades ennemies vivantes ET sur la table."""
    result = []
    for u in require_key(game_state, "units"):
        if u.get("player") == unit.get("player"):
            continue
        sid = str(u["id"])
        if not is_unit_alive(sid, game_state):
            continue
        entry = require_unit_from_cache(sid, game_state, "_living_enemies")
        if not entry_is_on_battlefield(entry):
            continue
        result.append(u)
    return result


def _swing_score_fn(attacker_id: str, is_ranged: bool):
    """Critere de cible : P(kill) x VALUE + degats esperes."""
    def _score(sid: str, entry: Dict[str, Any], game_state: Dict[str, Any]) -> float:
        damage = squad_expected_damage(game_state, attacker_id, sid, is_ranged)
        hp = get_hp_from_cache(sid, game_state)
        if hp is None:
            raise ValueError(f"_swing_score_fn: {sid} absent du cache (unité ciblée non vivante)")
        if hp <= 0:
            raise ValueError(f"_swing_score_fn: {sid} HP={hp} dans le cache (attendu >0)")
        p_kill = min(1.0, damage / float(hp))
        value = float(entry.get("VALUE", 0.0))
        return p_kill * value + damage
    return _score


def _count_zones(game_state: Dict[str, Any], player: int) -> int:
    """Nombre d'objectifs controles par `player`."""
    controllers: Dict[str, Optional[int]] = game_state.get("objective_controllers") or {}
    return sum(1 for v in controllers.values() if v == player)


def _objective_anchors(game_state: Dict[str, Any]) -> List[Tuple[int, int, Optional[int]]]:
    """(col, row, holder_player|None) par objectif — ancre = hex de plus petites coordonnees."""
    zones_list = objective_hex_zones(game_state)  # [(obj_id, Set[(col,row)]), ...]
    controllers: Dict[str, Optional[int]] = game_state.get("objective_controllers") or {}
    result = []
    for obj_id, zone in zones_list:
        if not zone:
            continue
        anchor = min(zone, key=lambda h: (h[0], h[1]))
        holder = controllers.get(str(obj_id))
        result.append((anchor[0], anchor[1], holder))
    return result


def _min_enemy_dist(dest: Tuple[int, int], enemies: List[Dict[str, Any]], game_state: Dict[str, Any]) -> int:
    """Distance hex minimale depuis `dest` vers le camp ennemi le plus proche."""
    if not enemies:
        return 999
    best = 999
    for e in enemies:
        entry = require_unit_from_cache(str(e["id"]), game_state, "_min_enemy_dist")
        d = calculate_hex_distance(dest[0], dest[1], int(entry["col"]), int(entry["row"]))
        if d < best:
            best = d
    return best


def _expected_ranged_from(
    attacker: Dict[str, Any],
    enemies: List[Dict[str, Any]],
    dest: Tuple[int, int],
    game_state: Dict[str, Any],
) -> float:
    """Degats esperes totaux depuis `dest` (heuristique ancre-ancre)."""
    from engine.utils.weapon_helpers import get_max_ranged_range
    att_id = str(require_key(attacker, "id"))
    my_range = get_max_ranged_range(attacker) if attacker.get("RNG_WEAPONS") else 0
    total = 0.0
    for enemy in enemies:
        eid = str(enemy["id"])
        entry = require_unit_from_cache(eid, game_state, "_expected_ranged_from")
        if calculate_hex_distance(dest[0], dest[1], int(entry["col"]), int(entry["row"])) <= my_range:
            total += squad_expected_damage(game_state, att_id, eid, True)
    return total


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Socle de deploiement — commun aux trois
# ─────────────────────────────────────────────────────────────────────────────────────────────

class _BenchmarkBase:
    """Deploiement partage et interface commune.

    Suit le patron de `_PlacementMemory` (ai/bot_doctrines.py) : les instances sont PARTAGEES
    dans un pool de 100, donc tout etat doit etre marque par episode. Cf. §1.2.c du chantier.
    """

    PLACEMENT_WEIGHTS: Dict[int, float] = _BENCHMARK_PLACEMENT_WEIGHTS

    def __init__(self, randomness: float = 0.0) -> None:
        self.randomness = max(0.0, min(1.0, randomness))
        self._deployment_last_action: Optional[int] = None
        self._deployment_repeat_count = 0
        self._deployment_episode_marker: Optional[Any] = None

    def select_placement_action(self, valid_actions: List[int], game_state: Dict[str, Any]) -> int:
        episode_marker = require_key(game_state, "episode_number")
        if self._deployment_episode_marker != episode_marker:
            self._deployment_episode_marker = episode_marker
            self._deployment_last_action = None
            self._deployment_repeat_count = 0
        chosen = _select_weighted_deployment_action(
            valid_actions=valid_actions,
            weights_by_action=self.PLACEMENT_WEIGHTS,
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

    def _shoot(self, valid_actions: List[int], game_state: Dict[str, Any], active_unit: Dict[str, Any]) -> int:
        if not any(a in valid_actions for a in mi.SHOOT_SLOTS):
            return self._wait_or_first(valid_actions)
        att_id = str(require_key(active_unit, "id"))
        action = _best_slot_action(
            valid_actions, mi.SHOOT_SLOTS, mi.SHOOT_SLOT_BASE,
            game_state, active_unit, _swing_score_fn(att_id, True),
        )
        return action if action is not None else WAIT_ACTION

    def _charge(self, valid_actions: List[int], game_state: Dict[str, Any], active_unit: Dict[str, Any]) -> int:
        att_id = str(require_key(active_unit, "id"))
        action = _best_slot_action(
            valid_actions, mi.CHARGE_SLOTS, mi.CHARGE_SLOT_BASE,
            game_state, active_unit, _swing_score_fn(att_id, False),
        )
        return action if action is not None else self._wait_or_first(valid_actions)

    def _fight(self, valid_actions: List[int], game_state: Dict[str, Any], active_unit: Dict[str, Any]) -> int:
        att_id = str(require_key(active_unit, "id"))
        action = _best_slot_action(
            valid_actions, mi.FIGHT_SLOTS, mi.FIGHT_SLOT_BASE,
            game_state, active_unit, _swing_score_fn(att_id, False),
        )
        if action is not None:
            return action
        if mi.ACTION_FIGHT_NO_TARGET in valid_actions:
            return mi.ACTION_FIGHT_NO_TARGET
        return self._wait_or_first(valid_actions)

    def _wait_or_first(self, valid_actions: List[int]) -> int:
        return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

    def select_action_with_state(
        self, valid_actions: List[int], game_state: Dict[str, Any], active_unit: Dict[str, Any]
    ) -> int:
        raise NotImplementedError

    def select_movement_destination(
        self, unit: Dict[str, Any], valid_destinations: List[Tuple[int, int]], game_state=None
    ) -> Tuple[int, int]:
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────────────────────────────
# reference_balanced — arbitrage permanent SCORE / KILL / PRESERVE
# ─────────────────────────────────────────────────────────────────────────────────────────────

class ReferenceBalancedBot(_BenchmarkBase):
    """A chaque activation, elit la meilleure intention parmi SCORE / KILL / PRESERVE.

    Faute punie : l'agent qui a UN plan. Un adversaire qui alterne les registres brise toute
    recette apprise contre une echelle de difficulte a une dimension.

    Mecanisme : compare trois scores d'intention sur l'etat courant, l'intention gagnante guide
    TOUTES les decisions de l'activation (move + attaque).
    """

    def _elect_intent(
        self,
        unit: Dict[str, Any],
        game_state: Dict[str, Any],
        enemies: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Retourne 'SCORE' | 'KILL' | 'PRESERVE'."""
        player = int(require_key(unit, "player"))
        att_id = str(require_key(unit, "id"))
        if enemies is None:
            enemies = _living_enemies(unit, game_state)

        objectives = game_state.get("objectives") or []
        zones_mine = _count_zones(game_state, player)
        s_score = float(max(0, len(objectives) - zones_mine))

        s_kill = 0.0
        for e in enemies:
            eid = str(e["id"])
            dmg = squad_expected_damage(game_state, att_id, eid, True)
            hp = get_hp_from_cache(eid, game_state)
            if hp is None:
                raise ValueError(f"_elect_intent: {eid} absent du cache (ennemi vivant attendu)")
            if hp <= 0:
                raise ValueError(f"_elect_intent: {eid} HP={hp} dans le cache (attendu >0)")
            p_kill = min(1.0, dmg / float(hp))
            value = float(e.get("VALUE", 0.0))
            s_kill = max(s_kill, p_kill * value + dmg)

        s_survive = sum(
            squad_expected_damage(game_state, str(e["id"]), att_id, True) for e in enemies
        )

        vp = require_key(game_state, "victory_points")
        my_vp = float(vp[player])
        opp_vp = float(vp[3 - player])
        if s_survive >= 8.0 and my_vp >= opp_vp + _VP_LEAD:
            return "PRESERVE"
        if s_kill >= s_score and s_kill > 0.0:
            return "KILL"
        return "SCORE"

    def select_movement_destination(
        self, unit: Dict[str, Any], valid_destinations: List[Tuple[int, int]], game_state=None
    ) -> Tuple[int, int]:
        if game_state is None:
            raise ValueError("ReferenceBalancedBot.select_movement_destination exige game_state")
        current = require_unit_position(unit, game_state)
        if not valid_destinations:
            return current
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_destinations)

        enemies = _living_enemies(unit, game_state)
        intent = self._elect_intent(unit, game_state, enemies)
        player = int(require_key(unit, "player"))
        candidates = [current] + list(valid_destinations)

        if intent == "KILL":
            def _score(d: Tuple[int, int]) -> float:
                return _expected_ranged_from(unit, enemies, d, game_state)
        elif intent == "PRESERVE":
            def _score(d: Tuple[int, int]) -> float:
                return float(_min_enemy_dist(d, enemies, game_state))
        else:  # SCORE
            obj_anchors = _objective_anchors(game_state)
            uncontested = [(c, r, h) for c, r, h in obj_anchors if h != player]
            targets = uncontested or obj_anchors
            if targets:
                def _score(d: Tuple[int, int]) -> float:
                    return -float(min(calculate_hex_distance(d[0], d[1], c, r) for c, r, _ in targets))
            else:
                def _score(d: Tuple[int, int]) -> float:
                    return 0.0

        best = max(candidates, key=_score)
        return (int(best[0]), int(best[1]))

    def select_action_with_state(
        self, valid_actions: List[int], game_state: Dict[str, Any], active_unit: Dict[str, Any]
    ) -> int:
        if not valid_actions:
            return WAIT_ACTION
        phase = require_key(game_state, "phase")
        if self.randomness > 0 and random.random() < self.randomness:
            return int(random.choice(valid_actions))
        if phase == "shoot":
            return self._shoot(valid_actions, game_state, active_unit)
        if phase == "charge":
            enemies = _living_enemies(active_unit, game_state)
            if self._elect_intent(active_unit, game_state, enemies) == "KILL":
                return self._charge(valid_actions, game_state, active_unit)
            return self._wait_or_first(valid_actions)
        if phase == "fight":
            return self._fight(valid_actions, game_state, active_unit)
        return self._wait_or_first(valid_actions)


# ─────────────────────────────────────────────────────────────────────────────────────────────
# reference_denial — refus de laisser marquer
# ─────────────────────────────────────────────────────────────────────────────────────────────

class ReferenceDenialBot(_BenchmarkBase):
    """Ne cherche pas d'abord a marquer : vise a ce que l'agent ne marque pas.

    Faute punie : l'agent qui marque par defaut, parce que personne ne conteste.

    Critere de cible : swing + bonus +10 si la cible est sur un objectif (porteur).
    Critere de deplacement : se rapprocher des objectifs tenus par l'adversaire ou neutres.
    """

    def _denial_score_fn(self, attacker: Dict[str, Any], is_ranged: bool, game_state: Dict[str, Any]):
        att_id = str(require_key(attacker, "id"))
        zones = objective_hex_sets(game_state)

        def _score(sid: str, entry: Dict[str, Any], gs: Dict[str, Any]) -> float:
            damage = squad_expected_damage(gs, att_id, sid, is_ranged)
            hp = get_hp_from_cache(sid, gs)
            if hp is None:
                raise ValueError(f"_denial_score_fn: {sid} absent du cache (unité ciblée non vivante)")
            if hp <= 0:
                raise ValueError(f"_denial_score_fn: {sid} HP={hp} dans le cache (attendu >0)")
            p_kill = min(1.0, damage / float(hp))
            value = float(entry.get("VALUE", 0.0))
            base = p_kill * value + damage
            if zones and unit_is_within_objective(gs, entry, zones):
                base += 10.0
            return base

        return _score

    def select_movement_destination(
        self, unit: Dict[str, Any], valid_destinations: List[Tuple[int, int]], game_state=None
    ) -> Tuple[int, int]:
        if game_state is None:
            raise ValueError("ReferenceDenialBot.select_movement_destination exige game_state")
        current = require_unit_position(unit, game_state)
        if not valid_destinations:
            return current
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_destinations)

        player = int(require_key(unit, "player"))
        obj_anchors = _objective_anchors(game_state)
        targets = [(c, r, h) for c, r, h in obj_anchors if h != player]
        if not targets:
            targets = obj_anchors

        candidates = [current] + list(valid_destinations)
        if targets:
            best = min(
                candidates,
                key=lambda d: min(calculate_hex_distance(d[0], d[1], c, r) for c, r, _ in targets),
            )
        else:
            best = current
        return (int(best[0]), int(best[1]))

    def select_action_with_state(
        self, valid_actions: List[int], game_state: Dict[str, Any], active_unit: Dict[str, Any]
    ) -> int:
        if not valid_actions:
            return WAIT_ACTION
        phase = require_key(game_state, "phase")
        if self.randomness > 0 and random.random() < self.randomness:
            return int(random.choice(valid_actions))
        if phase == "shoot":
            if not any(a in valid_actions for a in mi.SHOOT_SLOTS):
                return self._wait_or_first(valid_actions)
            action = _best_slot_action(
                valid_actions, mi.SHOOT_SLOTS, mi.SHOOT_SLOT_BASE,
                game_state, active_unit,
                self._denial_score_fn(active_unit, True, game_state),
            )
            return action if action is not None else WAIT_ACTION
        if phase == "charge":
            return self._charge(valid_actions, game_state, active_unit)
        if phase == "fight":
            if not any(a in valid_actions for a in mi.FIGHT_SLOTS):
                return mi.ACTION_FIGHT_NO_TARGET if mi.ACTION_FIGHT_NO_TARGET in valid_actions else self._wait_or_first(valid_actions)
            action = _best_slot_action(
                valid_actions, mi.FIGHT_SLOTS, mi.FIGHT_SLOT_BASE,
                game_state, active_unit,
                self._denial_score_fn(active_unit, False, game_state),
            )
            if action is not None:
                return action
            return mi.ACTION_FIGHT_NO_TARGET if mi.ACTION_FIGHT_NO_TARGET in valid_actions else self._wait_or_first(valid_actions)
        return self._wait_or_first(valid_actions)


# ─────────────────────────────────────────────────────────────────────────────────────────────
# reference_reactive — non-stationnarite basee sur l'historique de tour
# ─────────────────────────────────────────────────────────────────────────────────────────────

class ReferenceReactiveBot(_BenchmarkBase):
    """Revise son plan sur ce que l'agent VIENT de faire (valeur perdue le tour precedent).

    Plans : 'KILL' | 'SCORE' | 'RETREAT'

    Transitions : echange favorable -> presser (KILL) ; echange defavorable -> se replier
    (RETREAT) ; en retard au score -> contester (SCORE) ; sinon conserver le plan courant.

    Faute punie : l'agent exploitable par un adversaire qui s'adapte.

    Memoire de tour : marqueur `(episode_number, turn)`, meme patron que
    `DecapitationBot._focus_turn`. Le plan reste stable jusqu'au tour suivant — test §4.C.3.
    """

    def __init__(self, randomness: float = 0.0) -> None:
        super().__init__(randomness)
        self._plan: str = "SCORE"
        self._plan_turn_marker: Optional[Tuple[Any, int]] = None
        self._snapshot_value_me: float = 0.0
        self._snapshot_value_opp: float = 0.0
        self._snapshot_episode: Optional[Any] = None

    def _living_value(self, player: int, game_state: Dict[str, Any]) -> float:
        total = 0.0
        for u in require_key(game_state, "units"):
            if u.get("player") != player:
                continue
            sid = str(u["id"])
            if not is_unit_alive(sid, game_state):
                continue
            entry = require_unit_from_cache(sid, game_state, "_living_value")
            if not entry_is_on_battlefield(entry):
                continue
            total += float(u.get("VALUE", 0.0))
        return total

    def _current_turn_marker(self, game_state: Dict[str, Any]) -> Tuple[Any, int]:
        return (game_state.get("episode_number"), int(require_key(game_state, "turn")))

    def _update_plan(self, game_state: Dict[str, Any], player: int) -> None:
        """Met a jour le plan pour ce TOUR (idempotent si deja appele ce tour)."""
        episode_marker = require_key(game_state, "episode_number")
        curr_marker = self._current_turn_marker(game_state)

        if episode_marker != self._snapshot_episode:
            self._snapshot_episode = episode_marker
            self._snapshot_value_me = self._living_value(player, game_state)
            self._snapshot_value_opp = self._living_value(3 - player, game_state)
            self._plan = "SCORE"
            self._plan_turn_marker = curr_marker
            return

        if self._plan_turn_marker == curr_marker:
            return  # deja calcule pour ce tour

        val_me_now = self._living_value(player, game_state)
        val_opp_now = self._living_value(3 - player, game_state)
        loss_me = self._snapshot_value_me - val_me_now
        loss_opp = self._snapshot_value_opp - val_opp_now

        vp = require_key(game_state, "victory_points")
        vp_me = float(vp[player])
        vp_opp = float(vp[3 - player])

        if loss_me > loss_opp + _VALUE_LOSS_THRESHOLD:
            self._plan = "RETREAT"
        elif loss_opp > loss_me + _VALUE_LOSS_THRESHOLD:
            self._plan = "KILL"
        elif vp_me < vp_opp - _VP_LEAD:
            self._plan = "SCORE"
        # sinon : plan inchange

        self._snapshot_value_me = val_me_now
        self._snapshot_value_opp = val_opp_now
        self._plan_turn_marker = curr_marker

    def select_movement_destination(
        self, unit: Dict[str, Any], valid_destinations: List[Tuple[int, int]], game_state=None
    ) -> Tuple[int, int]:
        if game_state is None:
            raise ValueError("ReferenceReactiveBot.select_movement_destination exige game_state")
        current = require_unit_position(unit, game_state)
        if not valid_destinations:
            return current
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_destinations)

        player = int(require_key(unit, "player"))
        self._update_plan(game_state, player)
        candidates = [current] + list(valid_destinations)

        enemies = _living_enemies(unit, game_state) if self._plan in ("KILL", "RETREAT") else []
        if self._plan == "KILL":
            def _score(d: Tuple[int, int]) -> float:
                return -float(_min_enemy_dist(d, enemies, game_state))
            best = max(candidates, key=_score)
        elif self._plan == "RETREAT":
            def _score(d: Tuple[int, int]) -> float:
                return float(_min_enemy_dist(d, enemies, game_state))
            best = max(candidates, key=_score)
        else:  # SCORE
            obj_anchors = _objective_anchors(game_state)
            targets = [(c, r, h) for c, r, h in obj_anchors if h != player]
            if not targets:
                targets = obj_anchors
            if targets:
                def _score(d: Tuple[int, int]) -> float:
                    return -float(min(calculate_hex_distance(d[0], d[1], c, r) for c, r, _ in targets))
                best = max(candidates, key=_score)
            else:
                best = current
        return (int(best[0]), int(best[1]))

    def select_action_with_state(
        self, valid_actions: List[int], game_state: Dict[str, Any], active_unit: Dict[str, Any]
    ) -> int:
        if not valid_actions:
            return WAIT_ACTION
        phase = require_key(game_state, "phase")
        if self.randomness > 0 and random.random() < self.randomness:
            return int(random.choice(valid_actions))
        player = int(require_key(active_unit, "player"))
        self._update_plan(game_state, player)
        if phase == "shoot":
            return self._shoot(valid_actions, game_state, active_unit)
        if phase == "charge":
            if self._plan == "KILL":
                return self._charge(valid_actions, game_state, active_unit)
            return self._wait_or_first(valid_actions)
        if phase == "fight":
            return self._fight(valid_actions, game_state, active_unit)
        return self._wait_or_first(valid_actions)
