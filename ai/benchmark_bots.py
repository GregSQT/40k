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

       ⚠️ L'INTENTION S'ELIT AU NIVEAU ARMEE AVANT DE S'ELIRE AU NIVEAU ESCOUADE (R0a §3.1,
       2026-08-21). Elle s'elisait LOCALEMENT : personne ne marquait d'abord et toutes les
       escouades visaient la meme zone. Une passe d'assignation ouvre desormais chaque tour —
       une RECLAMANTE par objectif non tenu par le camp, qui joue SCORE vers l'objectif qui lui
       est assigne ; les autres seulement recoivent l'intention doctrinale ci-dessous. Cette
       reparation etait la condition du role d'etalon : saturees a 1,00 des la premiere
       evaluation, les references n'avaient jamais rien mesure cote agent.

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

import numpy as np

from engine.combat_utils import calculate_hex_distance
from engine.game_state import (
    objective_control_contributions, objective_hex_sets, objective_hex_zones,
    unit_is_within_objective,
)
from engine.objective_distance import objective_distance_maps
from engine.phase_handlers.shared_utils import (
    entry_is_on_battlefield, get_hp_from_cache, is_unit_alive,
    require_unit_from_cache, require_unit_position,
)
from engine.utils.weapon_helpers import get_max_ranged_range
from engine.weapon_damage_cache import squad_expected_damage
from shared.data_validation import require_key

from ai.bot_doctrines import DESTINATION_SHORTLIST, _surplus_oc_by_zone
from ai.evaluation_bots import (
    DEPLOYMENT_ACTIONS, WAIT_ACTION,
    _best_slot_action, _select_weighted_deployment_action,
)
from engine import macro_intents as mi

# ─────────────────────────────────────────────────────────────────────────────────────────────
# Constantes — independantes de config/bot_movement_weights.json
# ─────────────────────────────────────────────────────────────────────────────────────────────

#: Ecart de VP au-dela duquel on considere avoir une avance a proteger (PRESERVE pour balanced,
#: bascule SCORE pour reactive). Valeur retenue : 8.
#: §3.5 (2026-08-22) : teste 4 — balanced +0.002 / denial +0.002 / reactive +0.007 vs baseline
#: (10 ep., seed 42, board/44x60x1, holdout). Nul. 8 conserve.
_VP_LEAD = 8.0

#: Seuil de VALUE perdue ce tour au-dela de laquelle le reactif bascule de plan. Valeur retenue : 3.
#: §3.5 (2026-08-22) : teste 1 — balanced -0.003 / denial +0.005 / reactive +0.009 vs baseline
#: (10 ep., seed 42, board/44x60x1, holdout). Bruit. 3 conserve.
_VALUE_LOSS_THRESHOLD = 3.0

#: Facteur de ponderation de l'intention SCORE dans _elect_intent (reference_balanced uniquement).
#: Sans scaling, s_score (0-4 objectifs libres) serait toujours ecrase par s_kill (10-50+).
#: Valeur retenue : 12 (= VP cumule par objectif sur la partie, point de depart calibre).
#: §3.5 (2026-08-22) : teste 20 — balanced +0.002 / denial +0.005 / reactive +0.009 vs baseline
#: (10 ep., seed 42, board/44x60x1, holdout). Nul. 12 conserve.
_ELECT_INTENT_SCALE = 12.0

#: Prime de TENUE, en hexes, ajoutee au terme d'objectif quand la position est DANS une aire
#: (R0a §3.2, 2026-08-21). Sans elle, le score de destination fait sortir une escouade d'une zone
#: qu'elle controle des qu'un hexe voisin est marginalement « meilleur » — elle perd alors le VP
#: du tour pour un gain geometrique nul. Meme grandeur et meme valeur que `hold_bonus` du panel
#: doctrine (config/bot_movement_weights.json, 3.0), volontairement : le point de depart d'un
#: reglage benchmark est celui qui a deja ete mesure a cote, mais la constante est ICI parce
#: qu'un benchmark regle sur le fichier des bots d'entrainement serait regle en meme temps qu'eux.
_BENCH_HOLD_BONUS = 3.0

#: Penalite d'ENCOMBREMENT ALLIE, en hexes par point d'OC de surplus, ajoutee a la distance de
#: chaque zone pour les NON-reclamantes (R0a §3.3, 2026-08-21). L'assignation §3.1 regle
#: l'empilement des reclamantes ; ce terme regle celui des autres. Point de depart 2.0, valeur
#: du panel doctrine apres sa propre mesure du 2026-08-13 : le surplus d'OC typique vaut ~2, donc
#: la penalite (~4) doit depasser `_BENCH_HOLD_BONUS` (3.0) pour que l'etalement l'emporte sur la
#: tenue d'une zone deja gagnee large. En dessous de 1.5 le terme est inerte.
_W_CROWD_BENCH = 2.0

#: Seuil d'echange de charge (R0a-bis Fix 1, 2026-08-22).
#: Le benchmark ne charge que si les degats melee esperes atteignent au moins cette fraction
#: du tir espere. Meme valeur qu'AlphaStrikeBot.MELEE_TRADE_FLOOR — un echange en dessous de
#: ce seuil coute plus en degats tir perdus qu'il ne rapporte en pression melee.
_MELEE_TRADE_FLOOR = 0.5

#: Rabais de distance, EN HEXES, applique a un objectif selon qui le tient (R0a-bis Fix 3,
#: 2026-08-22). Meme schema que _CONTEST_PULL de bot_doctrines.py :
#:   - ennemi : 2.0 (lui prendre la zone fait passer de « il marque » a « je marque »)
#:   - neutre : 1.0 (l'objectif libre vaut une demi-attraction)
#:   - mien   : 0.0 (y envoyer une deuxieme escouade ne rapporte rien)
#: Le terme -w_contest * distance_pleine est retire ; le rabais constant est incorpore dans
#: la carte d'objectifs avant le min-reduce, ce qui ne modifie pas l'ordonnancement des
#: candidates pour la reclamante (constante) mais corrige l'attraction pour les non-reclamantes.
_CONTEST_PULL_ENEMY = 2.0
_CONTEST_PULL_NEUTRAL = 1.0

#: Poids par slot de deploiement — commun aux trois benchmarks.
_BENCHMARK_PLACEMENT_WEIGHTS: Dict[int, float] = {
    DEPLOYMENT_ACTIONS[0]: 0.20,
    DEPLOYMENT_ACTIONS[1]: 0.25,
    DEPLOYMENT_ACTIONS[2]: 0.25,
    DEPLOYMENT_ACTIONS[3]: 0.10,
    DEPLOYMENT_ACTIONS[4]: 0.10,
    DEPLOYMENT_ACTIONS[5]: 0.05,
    DEPLOYMENT_ACTIONS[6]: 0.05,
}

# ─────────────────────────────────────────────────────────────────────────────────────────────
# Poids de deplacement — hardcodes, jamais dans bot_movement_weights.json (§4.C isolation)
# ─────────────────────────────────────────────────────────────────────────────────────────────
#
# Tuple : (w_obj, w_enn, w_fire, w_risk, w_contest)
#   w_obj     : penalise la distance a l'objectif non-tenu par le joueur (> 0 = se rapprocher)
#   w_enn     : penalise la distance a l'ennemi le plus proche
#               (> 0 = approcher, < 0 = fuir — meme semantique que bot_movement_weights.json)
#   w_fire    : valorise les degats esperes depuis la destination (> 0)
#   w_risk    : penalise les degats recus esperes depuis la destination (> 0)
#   w_contest : penalise la distance aux objectifs tenus par l'adversaire (> 0)
#
# Point de calibrage : les bots d'entrainement ont w_obj ∈ [0.7, 1.3], w_enn ∈ [-0.35, 1.2],
# w_fire ∈ [0, 1.0], w_risk ∈ [0, 0.9], w_contest ∈ [1.0, 4.0] (bot_movement_weights.json).
# Rejouer avec scripts/bot_ranking.py --bots reference_balanced,...
# apres chaque ajustement — NE PAS toucher bot_movement_weights.json.

_W_BALANCED_SCORE:    Tuple[float, ...] = (1.0, 0.1, 0.5, 0.15, 3.5)
_W_BALANCED_KILL:     Tuple[float, ...] = (0.5, 1.1, 1.0, 0.0, 1.2)
_W_BALANCED_PRESERVE: Tuple[float, ...] = (0.8, -0.5, 0.2, 0.5, 1.2)

_W_DENIAL: Tuple[float, ...] = (1.4, 0.6, 1.0, 0.1, 3.0)

_W_REACTIVE_KILL:    Tuple[float, ...] = (0.4, 1.1, 1.0, 0.0, 1.0)
_W_REACTIVE_SCORE:   Tuple[float, ...] = (1.1, 0.1, 0.5, 0.15, 2.5)
_W_REACTIVE_CONTEST: Tuple[float, ...] = (1.0, -0.1, 0.4, 0.3, 2.5)


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
    """Critere de cible : bonus 1000 si la cible est tuable ce tour, + degats esperes.

    Motif _score_kill_now (bot_doctrines.py) : retirer une escouade entiere retire son OC
    et ses tirs immediatement — un demi-kill ne rapporte rien. Le bonus discret 1000 fait
    passer une cible tuable devant n'importe quelle cible non-tuable, quelle que soit sa
    VALUE. L'ancien critere (P(kill) x VALUE + damage) laissait une cible a haute VALUE
    non-tuable dominer une cible tuable a VALUE nulle — le bot n'eliminait personne.
    """
    def _score(sid: str, entry: Dict[str, Any], game_state: Dict[str, Any]) -> float:
        damage = squad_expected_damage(game_state, attacker_id, sid, is_ranged)
        hp = get_hp_from_cache(sid, game_state)
        if hp is None:
            raise ValueError(f"_swing_score_fn: {sid} absent du cache (unité ciblée non vivante)")
        if hp <= 0:
            raise ValueError(f"_swing_score_fn: {sid} HP={hp} dans le cache (attendu >0)")
        return (1000.0 if damage >= float(hp) else 0.0) + damage
    return _score


def _count_zones(game_state: Dict[str, Any], player: int) -> int:
    """Nombre d'objectifs controles par `player`."""
    controllers: Dict[str, Optional[int]] = game_state.get("objective_controllers") or {}
    return sum(1 for v in controllers.values() if v == player)


def _objective_holders(game_state: Dict[str, Any]) -> List[Optional[int]]:
    """Detenteur par objectif, DANS L'ORDRE de `objective_distance_maps`.

    L'ordre est le contrat partage par `objective_hex_zones`, `objective_hex_sets` et les cartes
    de distance : tout ce fichier indexe les trois par le meme numero de zone.
    """
    controllers: Dict[str, Optional[int]] = game_state.get("objective_controllers") or {}
    return [controllers.get(str(obj_id)) for obj_id, _zone in objective_hex_zones(game_state)]


def _enemy_anchors(
    enemies: List[Dict[str, Any]], game_state: Dict[str, Any]
) -> List[Tuple[int, int]]:
    """(col, row) de chaque escouade ennemie — lu UNE fois par decision, pas par candidate."""
    return [
        (int(entry["col"]), int(entry["row"]))
        for entry in (
            require_unit_from_cache(str(e["id"]), game_state, "_enemy_anchors") for e in enemies
        )
    ]


def _squad_is_on_table(squad_id: str, game_state: Dict[str, Any]) -> bool:
    """Escouade vivante ET sur la table — critere de rupture d'une reclamation (§3.1)."""
    if not is_unit_alive(squad_id, game_state):
        return False
    return entry_is_on_battlefield(
        require_unit_from_cache(squad_id, game_state, "_squad_is_on_table")
    )


def _assign_claimants(game_state: Dict[str, Any], player: int) -> Dict[str, int]:
    """{escouade: index de zone} — UNE reclamante par objectif non tenu par le camp (R0a §3.1).

    POURQUOI CETTE PASSE EXISTE. Chaque escouade elisait son intention LOCALEMENT : personne ne
    « marquait d'abord » et toutes visaient la meme zone (la plus proche d'elles, souvent la
    meme). Dans ce format — 5 tours, VP d'objectifs chaque tour des le tour 2, cumules — « nier
    sans marquer » accumule un retard irrattrapable : c'est le mecanisme mesure qui a tue le bot
    `standoff` (supprime le 2026-08-11). Le deni devient donc un comportement EN PLUS d'une base
    qui marque, plus jamais A LA PLACE.

    Assignation GLOUTONNE sur la distance a l'AIRE (14.02) : la paire (objectif libre, escouade)
    la plus courte est servie d'abord, chaque objectif recoit au plus une reclamante et chaque
    escouade en reclame au plus un. Egalites tranchees par (index de zone, id d'escouade) : sans
    cet ordre, la decision dependrait de l'ordre de parcours d'un dictionnaire.

    « Non tenu par le camp » couvre le neutre ET l'adverse : le detenteur `None` n'est pas un
    defaut de lecture, c'est l'etat reel tant qu'aucun controle n'a ete calcule.
    """
    maps = objective_distance_maps(game_state)
    if not maps:
        return {}
    holders = _objective_holders(game_state)
    free = [i for i, holder in enumerate(holders) if holder != player]
    if not free:
        return {}

    squads: List[Tuple[str, int, int]] = []
    for unit in require_key(game_state, "units"):
        if unit.get("player") != player:
            continue
        squad_id = str(unit["id"])
        if not is_unit_alive(squad_id, game_state):
            continue
        entry = require_unit_from_cache(squad_id, game_state, "_assign_claimants")
        if not entry_is_on_battlefield(entry):
            continue
        squads.append((squad_id, int(entry["col"]), int(entry["row"])))
    if not squads:
        return {}

    pairs = sorted(
        (int(maps[zone_index][col, row]), zone_index, squad_id)
        for zone_index in free
        for squad_id, col, row in squads
    )
    claims: Dict[str, int] = {}
    taken: Set[int] = set()
    for _distance, zone_index, squad_id in pairs:
        if zone_index in taken or squad_id in claims:
            continue
        claims[squad_id] = zone_index
        taken.add(zone_index)
    return claims


def _expected_ranged_from(
    attacker: Dict[str, Any],
    enemies: List[Dict[str, Any]],
    dest: Tuple[int, int],
    game_state: Dict[str, Any],
) -> float:
    """Degats esperes totaux depuis `dest` (heuristique ancre-ancre)."""
    att_id = str(require_key(attacker, "id"))
    my_range = get_max_ranged_range(attacker) if attacker.get("RNG_WEAPONS") else 0
    total = 0.0
    for enemy in enemies:
        eid = str(enemy["id"])
        entry = require_unit_from_cache(eid, game_state, "_expected_ranged_from")
        if calculate_hex_distance(dest[0], dest[1], int(entry["col"]), int(entry["row"])) <= my_range:
            total += squad_expected_damage(game_state, att_id, eid, True)
    return total


def _received_damage_from(
    attacker: Dict[str, Any],
    enemies: List[Dict[str, Any]],
    dest: Tuple[int, int],
    game_state: Dict[str, Any],
) -> float:
    """Degats esperes recus a `dest` depuis les ennemis (heuristique ancre-ancre)."""
    att_id = str(require_key(attacker, "id"))
    total = 0.0
    for enemy in enemies:
        eid = str(enemy["id"])
        entry = require_unit_from_cache(eid, game_state, "_received_damage_from")
        enemy_range = get_max_ranged_range(enemy) if enemy.get("RNG_WEAPONS") else 0
        if calculate_hex_distance(dest[0], dest[1], int(entry["col"]), int(entry["row"])) <= enemy_range:
            total += squad_expected_damage(game_state, eid, att_id, True)
    return total


def _score_destinations_weighted(
    unit: Dict[str, Any],
    current: Tuple[int, int],
    valid_destinations: List[Tuple[int, int]],
    weights: Tuple[float, ...],
    game_state: Dict[str, Any],
    assigned_zone: Optional[int] = None,
    contributions: Optional[Dict[str, Tuple[int, List[int]]]] = None,
) -> Tuple[int, int]:
    """Passe-1 : pre-tri geometrique (w_obj, w_enn, w_contest) ;
    Passe-2 : scoring tir (w_fire, w_risk) sur le top DESTINATION_SHORTLIST.

    ⚠️ GEOMETRIE PAR AIRE, ET NON PAR ANCRE (R0a §3.4, 2026-08-21). La distance a un objectif
    etait celle de l'ancre de la destination a l'ANCRE de l'objectif — l'hexe de plus petites
    coordonnees de l'aire. Sur les aires reelles (14.02 : plusieurs milliers d'hexes), une
    escouade posee DANS une zone ressortait a des dizaines d'hexes de « l'objectif » et pouvait
    en viser un autre. Le bot qui sert d'etalon doit mesurer la meme geometrie que l'agent qu'il
    evalue : c'est desormais `objective_distance_maps`, la source unique du moteur.

    `assigned_zone` : la reclamante de §3.1 vise SON objectif, pas « le plus proche global ».
    Elle n'est alors pas penalisee par l'encombrement allie — l'assignation le regle deja — et sa
    contestation ne la tire que vers cet objectif-la s'il est adverse, jamais vers un autre.
    """
    w_obj, w_enn, w_fire, w_risk, w_contest = weights
    player = int(require_key(unit, "player"))
    enemies = _living_enemies(unit, game_state)
    enemy_anchors = _enemy_anchors(enemies, game_state)

    maps = objective_distance_maps(game_state)
    zones = objective_hex_sets(game_state)
    obj_map = None
    if maps:
        holders = _objective_holders(game_state)
        if assigned_zone is not None:
            obj_map = maps[assigned_zone]
            # Pas de contest_map pour la reclamante : un rabais constant (_CONTEST_PULL) ne
            # modifie pas l'ordonnancement des candidates (decalage uniforme). Le terme
            # -w_contest * distance_pleine est retire (R0a-bis Fix 3, 2026-08-22).
        else:
            # La penalite porte sur le SURPLUS d'OC allie (ce que mes allies tiennent DEJA sans
            # moi), pas sur l'occupation : une zone disputee n'est pas penalisee, donc les
            # renforts y vont ; une zone deja gagnee large repousse la suivante.
            surplus = _surplus_oc_by_zone(
                game_state, zones, player, str(require_key(unit, "id")),
                contributions=contributions,
            )
            free = [i for i, holder in enumerate(holders) if holder != player]
            targets = free if free else list(range(len(maps)))
            # Fix R0a-bis §3 (2026-08-22) : -w_contest * distance_pleine remplace par le rabais
            # _CONTEST_PULL incorpore dans la carte avant min-reduce (motif _objective_terms de
            # bot_doctrines). Un objectif ennemi semble _CONTEST_PULL_ENEMY * w_contest hexes plus
            # proche, un neutre _CONTEST_PULL_NEUTRAL * w_contest hexes plus proche. La carte
            # est promue en float64 des qu'un rabais ou une penalite s'applique.
            target_maps = []
            for i in targets:
                m: Any = maps[i]
                if surplus[i]:
                    m = m + _W_CROWD_BENCH * surplus[i]
                pull = w_contest * (
                    _CONTEST_PULL_ENEMY if holders[i] == 3 - player else _CONTEST_PULL_NEUTRAL
                )
                if pull:
                    m = m.astype(np.float64, copy=False) - pull
                target_maps.append(m)
            obj_map = np.minimum.reduce(target_maps)

    def _geo(dest: Tuple[int, int], inside: bool) -> float:
        score = 0.0
        if obj_map is not None:
            # `float` et NON `int` : la carte n'est plus la distance entiere du moteur, la
            # penalite d'encombrement ou le rabais _CONTEST_PULL y est FRACTIONNAIRE —
            # tronquer annulerait tout poids < 1.
            score -= w_obj * float(obj_map[dest[0], dest[1]])
            if inside:
                score += w_obj * _BENCH_HOLD_BONUS
        if enemy_anchors:
            score -= w_enn * float(
                min(calculate_hex_distance(dest[0], dest[1], c, r) for c, r in enemy_anchors)
            )
        return score

    # La position courante est lue PAR FIGURINE (14.02, exact), les candidates par ancre
    # (heuristique assumee, la meme que `_select_destination` cote doctrine) : c'est la position
    # courante qui porte la decision « je tiens deja cette zone ».
    scored = [(_geo(current, unit_is_within_objective(game_state, unit, zones)), current)]
    scored.extend(
        (_geo(d, any(d in zone for zone in zones)), d) for d in valid_destinations
    )
    scored.sort(key=lambda pair: pair[0], reverse=True)

    if w_fire == 0.0 and w_risk == 0.0:
        return scored[0][1]

    best_dest, best_score = scored[0][1], -float("inf")
    for geometric, dest in scored[:DESTINATION_SHORTLIST]:
        fire = _expected_ranged_from(unit, enemies, dest, game_state) if w_fire != 0.0 else 0.0
        risk = _received_damage_from(unit, enemies, dest, game_state) if w_risk != 0.0 else 0.0
        total = geometric + w_fire * fire - w_risk * risk
        if total > best_score:
            best_score = total
            best_dest = dest
    return best_dest


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Socle de deploiement — commun aux trois
# ─────────────────────────────────────────────────────────────────────────────────────────────

class _BenchmarkBase:
    """Deploiement partage et interface commune.

    Suit le patron de `_PlacementMemory` (ai/bot_doctrines.py) : les instances sont PARTAGEES
    dans un pool de 100, donc tout etat doit etre marque par episode. Cf. §1.2.c du chantier.
    """

    PLACEMENT_WEIGHTS: Dict[int, float] = _BENCHMARK_PLACEMENT_WEIGHTS

    #: Poids de deplacement de l'intention SCORE — ceux que joue une RECLAMANTE (§3.1), quel que
    #: soit ce que la doctrine aurait elu pour elle.
    SCORE_WEIGHTS: Tuple[float, ...] = ()

    def __init__(self, randomness: float = 0.0) -> None:
        self.randomness = max(0.0, min(1.0, randomness))
        self._deployment_last_action: Optional[int] = None
        self._deployment_repeat_count = 0
        self._deployment_episode_marker: Optional[Any] = None
        self._claims: Dict[str, int] = {}
        self._claims_marker: Optional[Tuple[Any, int, int]] = None
        self._contributions_marker: Optional[Tuple[Any, Any, Any, str]] = None
        self._contributions_val: Optional[Dict[str, Tuple[int, List[int]]]] = None

    def _army_claims(self, game_state: Dict[str, Any], player: int) -> Dict[str, int]:
        """Assignation objectif ↔ reclamante du TOUR courant (§3.1), memoisee.

        Marqueur `(episode_number, turn, player)`, patron de `DecapitationBot._focus_turn` : les
        instances sont PARTAGEES dans un pool de 100, donc tout etat est marque par episode.

        RUPTURE : une reclamante morte ou sortie de la table invalide l'assignation entiere, qui
        est recalculee a la lecture suivante — sinon son objectif resterait reserve a un cadavre
        pour la fin du tour.
        """
        marker = (
            require_key(game_state, "episode_number"),
            int(require_key(game_state, "turn")),
            int(player),
        )
        if self._claims_marker == marker and all(
            _squad_is_on_table(squad_id, game_state) for squad_id in self._claims
        ):
            return self._claims
        self._claims = _assign_claimants(game_state, int(player))
        self._claims_marker = marker
        return self._claims

    def _contributions_for(
        self, game_state: Dict[str, Any], unit: Dict[str, Any]
    ) -> Dict[str, Tuple[int, List[int]]]:
        """Contributions de controle du moteur, mises en cache par ACTIVATION.

        Sans ce cache, `_surplus_oc_by_zone` recompte le controle une fois par figurine du pool
        BFS. Meme cle que `_select_destination` cote doctrine — l'etat change entre deux
        activations, jamais a l'interieur d'une seule.
        """
        key = (
            require_key(game_state, "episode_number"),
            require_key(game_state, "turn"),
            require_key(game_state, "phase"),
            str(require_key(unit, "id")),
        )
        if self._contributions_marker != key or self._contributions_val is None:
            self._contributions_marker = key
            self._contributions_val = objective_control_contributions(
                game_state, objective_hex_sets(game_state)
            )
        return self._contributions_val

    def _move_to(
        self,
        unit: Dict[str, Any],
        current: Tuple[int, int],
        valid_destinations: List[Tuple[int, int]],
        doctrinal_weights: Tuple[float, ...],
        game_state: Dict[str, Any],
    ) -> Tuple[int, int]:
        """Deplacement commun : la reclamante joue SCORE vers SON objectif, les autres la doctrine."""
        player = int(require_key(unit, "player"))
        # `get allowed` : ne pas figurer dans l'assignation est l'etat REEL d'une non-reclamante,
        # pas une donnee manquante.
        assigned = self._army_claims(game_state, player).get(str(require_key(unit, "id")))
        if assigned is not None:
            return _score_destinations_weighted(
                unit, current, valid_destinations, self.SCORE_WEIGHTS, game_state,
                assigned_zone=assigned,
            )
        return _score_destinations_weighted(
            unit, current, valid_destinations, doctrinal_weights, game_state,
            contributions=self._contributions_for(game_state, unit),
        )

    def _is_claimant(self, game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
        """L'unite marque-t-elle un objectif ce tour ? Une reclamante joue SCORE, donc ne charge pas."""
        player = int(require_key(unit, "player"))
        return str(require_key(unit, "id")) in self._army_claims(game_state, player)

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

    def _should_charge(self, attacker: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
        """Vrai si les degats melee esperes valent au moins _MELEE_TRADE_FLOOR * les degats tir.

        Fix R0a-bis §1 (2026-08-22) : meme critere qu'AlphaStrikeBot.wants_charge. Charger avec
        une unite dont la melee vaut moins de la moitie du tir est un echange perdant en degats
        bruts ; en dessous de ce seuil la pression melee ne compense pas les tirs perdus.
        """
        att_id = str(require_key(attacker, "id"))
        enemies = _living_enemies(attacker, game_state)
        if not enemies:
            return False
        best_melee = max(
            squad_expected_damage(game_state, att_id, str(e["id"]), False) for e in enemies
        )
        best_ranged = max(
            squad_expected_damage(game_state, att_id, str(e["id"]), True) for e in enemies
        )
        return best_melee >= best_ranged * _MELEE_TRADE_FLOOR

    def _charge(self, valid_actions: List[int], game_state: Dict[str, Any], active_unit: Dict[str, Any]) -> int:
        if not self._should_charge(active_unit, game_state):
            return self._wait_or_first(valid_actions)
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
    TOUTES les decisions de l'activation (move + attaque). Sauf pour la RECLAMANTE du tour
    (§3.1), dont l'intention est SCORE par assignation d'armee.
    """

    SCORE_WEIGHTS = _W_BALANCED_SCORE

    def _elect_intent(
        self,
        unit: Dict[str, Any],
        game_state: Dict[str, Any],
        enemies: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Retourne 'SCORE' | 'KILL' | 'PRESERVE'.

        Fix R0a-bis §2 (2026-08-22) : s_kill et s_survive ne comptent que les ennemis
        atteignables ce tour (distance ancre-ancre <= portee_max + MOVE), motif _firepower_from.
        Avant ce correctif, le bot comptait TOUS les ennemis, y compris ceux a l'autre bout de
        la table : s_kill devenait toujours dominant, l'intention KILL ecrasait SCORE meme quand
        aucun ennemi n'etait a portee.
        """
        player = int(require_key(unit, "player"))
        att_id = str(require_key(unit, "id"))
        if enemies is None:
            enemies = _living_enemies(unit, game_state)

        objectives = game_state.get("objectives") or []
        zones_mine = _count_zones(game_state, player)
        s_score_scaled = float(max(0, len(objectives) - zones_mine)) * _ELECT_INTENT_SCALE

        # Portee de l'attaquant ce tour : max_ranged_range + MOVE (motif _firepower_from).
        att_range = get_max_ranged_range(unit) if unit.get("RNG_WEAPONS") else 0
        att_reach = att_range + int(require_key(unit, "MOVE"))

        s_kill = 0.0
        s_survive = 0.0
        att_col: Optional[int] = None
        att_row: Optional[int] = None

        for e in enemies:
            eid = str(e["id"])
            e_entry = require_unit_from_cache(eid, game_state, "_elect_intent")
            e_col, e_row = int(e_entry["col"]), int(e_entry["row"])

            # Position de l'attaquant chargee une seule fois (lazy).
            if att_col is None:
                att_e = require_unit_from_cache(att_id, game_state, "_elect_intent")
                att_col, att_row = int(att_e["col"]), int(att_e["row"])

            dist = calculate_hex_distance(att_col, att_row, e_col, e_row)

            # Integrite des donnees — toujours verifier, independamment de la portee (T1).
            dmg = squad_expected_damage(game_state, att_id, eid, True)
            hp = get_hp_from_cache(eid, game_state)
            if hp is None:
                raise ValueError(f"_elect_intent: {eid} absent du cache (ennemi vivant attendu)")
            if hp <= 0:
                raise ValueError(f"_elect_intent: {eid} HP={hp} dans le cache (attendu >0)")

            # s_kill : seulement les ennemis atteignables par NOS tirs ce tour.
            if dist <= att_reach:
                p_kill = min(1.0, dmg / float(hp))
                value = float(e.get("VALUE", 0.0))
                s_kill = max(s_kill, p_kill * value + dmg)

            # s_survive : seulement les ennemis qui peuvent nous atteindre ce tour.
            e_range = get_max_ranged_range(e) if e.get("RNG_WEAPONS") else 0
            e_reach = e_range + int(require_key(e, "MOVE"))
            if dist <= e_reach:
                s_survive += squad_expected_damage(game_state, eid, att_id, True)

        vp = require_key(game_state, "victory_points")
        my_vp = float(vp[player])
        opp_vp = float(vp[3 - player])
        if s_survive >= 8.0 and my_vp >= opp_vp + _VP_LEAD:
            return "PRESERVE"
        if s_kill >= s_score_scaled and s_kill > 0.0:
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

        # L'election doctrinale n'est PAS calculee pour une reclamante : son intention est deja
        # SCORE par assignation d'armee, et `_elect_intent` coute une passe de degats esperes.
        if self._is_claimant(game_state, unit):
            weights = self.SCORE_WEIGHTS
        else:
            weights = {
                "KILL": _W_BALANCED_KILL,
                "PRESERVE": _W_BALANCED_PRESERVE,
                "SCORE": _W_BALANCED_SCORE,
            }[self._elect_intent(unit, game_state)]
        return self._move_to(unit, current, list(valid_destinations), weights, game_state)

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
            if self._is_claimant(game_state, active_unit):
                return self._wait_or_first(valid_actions)
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

    ⚠️ Le deni s'exerce EN PLUS d'une base qui marque, jamais A LA PLACE (§3.1) : la reclamante
    du tour va tenir son objectif assigne. Le bot ne dispose que d'un jeu de poids, donc
    l'intention SCORE d'une reclamante est ce meme jeu — c'est la CIBLE geometrique qui change,
    son objectif au lieu du plus proche global.
    """

    SCORE_WEIGHTS = _W_DENIAL

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
            base = (1000.0 if damage >= float(hp) else 0.0) + damage
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

        return self._move_to(unit, current, list(valid_destinations), _W_DENIAL, game_state)

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
            if self._is_claimant(game_state, active_unit):
                return self._wait_or_first(valid_actions)
            # Ne charger que si un ennemi est sur un objectif — la faute punie est le push aveugle.
            zones = objective_hex_sets(game_state)
            if zones and any(
                unit_is_within_objective(game_state, str(e["id"]), zones)
                for e in _living_enemies(active_unit, game_state)
            ):
                return self._charge(valid_actions, game_state, active_unit)
            return self._wait_or_first(valid_actions)
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

    Plans : 'KILL' | 'SCORE' | 'CONTEST'

    Transitions : echange favorable -> presser (KILL) ; echange defavorable -> contester les
    objectifs (CONTEST) ; en retard au score -> scorer (SCORE) ; sinon conserver le plan courant.

    Faute punie : l'agent exploitable par un adversaire qui s'adapte.

    Memoire de tour : marqueur `(episode_number, turn)`, meme patron que
    `DecapitationBot._focus_turn`. Le plan reste stable jusqu'au tour suivant — test §4.C.3.

    Le plan ne s'applique qu'aux NON-reclamantes : la reclamante du tour joue SCORE vers son
    objectif assigne (§3.1), quel que soit le plan courant.
    """

    SCORE_WEIGHTS = _W_REACTIVE_SCORE

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

    def _has_reachable_enemies(self, game_state: Dict[str, Any], player: int) -> bool:
        """Vrai si au moins une escouade de `player` a un ennemi atteignable ce tour.

        Fix R0a-bis §2 (2026-08-22) : la transition KILL de _update_plan ne s'active que s'il
        existe reellement des cibles atteignables. Meme critere de portee qu'_elect_intent :
        distance ancre-ancre <= portee_max + MOVE.
        """
        alive_enemies = [
            u for u in require_key(game_state, "units")
            if u.get("player") != player
            and is_unit_alive(str(u["id"]), game_state)
            and entry_is_on_battlefield(
                require_unit_from_cache(str(u["id"]), game_state, "_has_reachable_enemies")
            )
        ]
        if not alive_enemies:
            return False
        for unit in require_key(game_state, "units"):
            if unit.get("player") != player:
                continue
            uid = str(unit["id"])
            if not is_unit_alive(uid, game_state):
                continue
            entry = require_unit_from_cache(uid, game_state, "_has_reachable_enemies")
            if not entry_is_on_battlefield(entry):
                continue
            att_col, att_row = int(entry["col"]), int(entry["row"])
            att_range = get_max_ranged_range(unit) if unit.get("RNG_WEAPONS") else 0
            att_reach = att_range + int(require_key(unit, "MOVE"))
            for e in alive_enemies:
                e_entry = require_unit_from_cache(
                    str(e["id"]), game_state, "_has_reachable_enemies"
                )
                dist = calculate_hex_distance(
                    att_col, att_row, int(e_entry["col"]), int(e_entry["row"])
                )
                if dist <= att_reach:
                    return True
        return False

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
            self._plan = "CONTEST"
        elif loss_opp > loss_me + _VALUE_LOSS_THRESHOLD and self._has_reachable_enemies(game_state, player):
            # Fix R0a-bis §2 : KILL seulement si des cibles sont atteignables ce tour.
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
        weights = {"KILL": _W_REACTIVE_KILL, "SCORE": _W_REACTIVE_SCORE, "CONTEST": _W_REACTIVE_CONTEST}[self._plan]
        return self._move_to(unit, current, list(valid_destinations), weights, game_state)

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
            if self._plan == "KILL" and not self._is_claimant(game_state, active_unit):
                return self._charge(valid_actions, game_state, active_unit)
            return self._wait_or_first(valid_actions)
        if phase == "fight":
            return self._fight(valid_actions, game_state, active_unit)
        return self._wait_or_first(valid_actions)
