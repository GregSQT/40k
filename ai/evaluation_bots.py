#!/usr/bin/env python3
"""
ai/evaluation_bots.py - Tactical bots for measuring agent performance

Panel de bots (du plus simple au plus dur) :
  1. RandomBot - Random actions (baseline)
  2. GreedyBot - Shoots first, pousse vers l'ennemi, acheve le blesse en melee
  3. DefensiveBot - Maintient la distance, tire, contre-charge les unites de melee qui
     menacent sa ligne
  4. ControlBot - Captures and holds objectives, shoots contesters
  5. AdaptiveBot - Adapts posture to game state (early rush / winning hold / losing push)
  6. ValueTradeBot - Joue le DEPARTAGE : maximise le differentiel de VALUE (cible la plus
     rentable en points par degat, engagement selon son propre profil, retrait des pieces
     cheres entamees)
  7. TacticalBot - Full phase awareness. V11 §10.5 : HOLDOUT d'evaluation — utilise
     UNIQUEMENT en evaluation, jamais dans bot_training.ratios, et exclu de tout
     signal de selection de modele. Jamais valide runtime sur le pipeline squad.

⚠️ `AggressiveSmartBot` et `DefensiveSmartBot` ont ete SUPPRIMES, avec le regroupement
« palier 2 » qui les portait. Le premier etait un doublon strict de `GreedyBot` (meme geometrie
de move, meme `_score_wounded` aux trois phases d'action ; seul ecart : un poids de
deploiement) — il gonflait donc l'evaluation d'un adversaire deja mesure. Le second n'etait
instancie ni a l'entrainement ni en evaluation, et etait domine par `DefensiveBot`, qui a sa
contre-charge.

Le DEPLACEMENT de tous les bots (hors RandomBot) est un score pondere unique — cf. la section
« Geometrie de deplacement » : plus aucun bot ne peut ignorer les objectifs, qui decident la
victoire.

All bots implement all 4 phases: MOVE, SHOOT, CHARGE, FIGHT
"""

import random
from typing import Dict, List, Tuple, Any, Optional
from shared.data_validation import require_key
from engine.combat_utils import calculate_hex_distance, get_unit_coordinates
from engine.game_state import objective_hex_sets, unit_is_within_objective
from engine.hex_utils import min_distance_between_sets
from engine.phase_handlers.shared_utils import (
    is_unit_alive, get_hp_from_cache, is_unit_at_or_below_half_strength,
    require_unit_position, require_unit_from_cache,
    compute_candidate_footprint, get_enemy_slot_mapping,
    # HORS TABLE (20.01) : VIVANTE n'est pas SUR LA TABLE. Les bots itèrent `game_state["units"]`
    # en ne filtrant que sur `is_unit_alive`, donc une réserve ennemie y entrait avec une
    # empreinte VIDE -> `min_distance_between_sets` lève. Même motif que le moteur, mêmes
    # primitives (cf. Documentation/Implémentation/Implémenté/1_unites_hors_table_chemins_geometriques.md).
    entry_footprint, entry_is_on_battlefield,
)
from engine import macro_intents as mi
from engine.utils.weapon_helpers import get_max_ranged_damage, get_max_melee_damage

# Espace d'action squad (source unique : engine/macro_intents.py). Aucun littéral nu.
DEPLOYMENT_ACTIONS = list(mi.DEPLOY_STRATEGY_SLOTS)   # 4-8 (slots PORTANT une strategie)
# ⚠️ `DEPLOY_STRATEGY_SLOTS` et non `DEPLOY_SLOTS` : ce dernier inclut les slots RESERVES
# (V11 §0.48 arbitrage 2), que le masque n'ouvre jamais et pour lesquels ces tables de poids
# n'ont donc aucune entree — les prendre ici levait `Missing deployment weight for action 9`.
WAIT_ACTION = mi.ACTION_WAIT                 # 1024 (au-dessus des cellules de move 0-1023)


def _has_action_in(valid_actions, action_ids) -> bool:
    """True si au moins une action de `action_ids` est ouverte par le masque."""
    return any(a in valid_actions for a in action_ids)


# CONTRAT DES POLITIQUES DE POSE (`select_placement_action`, toutes implementations)
# ---------------------------------------------------------------------------------
# `valid_actions` est un pool NON VIDE de slots de mise en place (4-8), jamais un masque brut.
# Il est construit une seule fois par l'appelant — `BotControlledEnv._open_placement_slots`, pour
# les deux sites de mise en place (deploiement 03.02 et ingress move 20.04), qui y traitent aussi
# le cas du pool vide.
#
# ⚠️ Ce que ce contrat protege : `WAIT_ACTION` n'est PAS une attente au deploiement, le masque l'y
# ouvre pour la decision 20.01 « placer cette unite en RESERVES STRATEGIQUES »
# (`ActionDecoder.get_squad_action_mask_and_eligible_units`). Un bot ne prend jamais cette
# decision — c'est un choix de LISTE, pas de doctrine. Quand le filtre etait porte par les bots,
# un site oublie ne plantait pas, il remettait le bot a decider des reserves en silence : mesure
# du chantier 04c, TacticalBot 400 mises en reserves sur 400, cinq bots ponderes 1 a 3 % des leurs.
# Le filtre a donc ete remonte chez l'appelant, ou il est structurellement impossible a oublier.
# Aucun garde ne le double ici : un controle place APRES le filtre ne pourrait plus rien voir.


# ⚠️ HISTORIQUE — « le premier slot ouvert = la cible la plus menacante » etait FAUX.
# Les helpers `_first_charge_action_in` / `_first_fight_action_in` justifiaient le choix du
# premier slot par l'ordre de `_enemy_threat_order`. Trois raisons de rejeter cette caution :
#   1. `_enemy_threat_order` trie par PV x controle d'objectif (HP_CUR x OC_TOTAL), une mesure
#      de VALEUR D'OBJECTIF — pas de dangerosite ; les scores de menace des bots portent, eux,
#      sur les degats attendus (`get_max_ranged_damage` / `get_max_melee_damage`).
#   2. `_refresh_enemy_slot_mapping` garantit qu'une escouade vivante GARDE son slot : l'ordre
#      est fige a l'attribution et ne reflete plus aucun classement des la premiere mort, un
#      slot libere etant repris par n'importe quelle escouade non mappee.
#   3. L'ordre des slots est un detail d'implementation du masque, pas une doctrine de bot.
# Tout choix de cible passe donc par un critere explicite (`_best_slot_action`).


# --- Choix de cible par CRITERE EXPLICITE (jamais par ordre de tri) ----------
# `valid_actions` est la liste TRIEE des bits a True du masque : `valid_actions[0]` designe
# l'action d'indice le plus bas, donc une cible choisie par accident d'ordre. Les helpers
# ci-dessous relisent le mapping slot -> escouade ennemie (`get_enemy_slot_mapping` : la MEME
# source que le masque — cf. action_decoder.get_squad_action_mask_and_eligible_units — et que la
# ligne du tenseur ennemi de l'observation), puis tranchent sur une PROPRIETE de la cible.
#
# Un slot ouvert par le masque sans escouade en face est une divergence d'invariant : erreur
# explicite, jamais un repli silencieux sur un autre slot.

def _acting_player(game_state: Dict[str, Any], active_unit: Dict[str, Any]) -> int:
    """Joueur dont le masque a ete construit : celui de l'ESCOUADE ACTIVEE, lu dans units_cache.

    ⚠️ SURTOUT PAS `current_player`. Le masque derive son joueur de l'escouade activee
    (`action_decoder.get_squad_action_mask_and_eligible_units` : `our_player` vient de
    `units_cache[eligible_units[0]["id"]]["player"]`), et en phase de COMBAT les deux DIFFERENT :
    la selection 12.04 alterne entre les joueurs (`fight_handlers._fight_v11_register_selection`
    bascule `fight_selector` par `3 - selector`, et `fight_v11_current_pool` lit ce selecteur).
    Un bot selecteur sans etre joueur courant lirait donc le mapping de SES PROPRES escouades.
    Meme source que le masque, ou rien.
    """
    units_cache = require_key(game_state, "units_cache")
    squad_id = str(require_key(active_unit, "id"))
    cache_entry = units_cache.get(squad_id)
    if cache_entry is None:
        raise RuntimeError(
            f"Escouade activee {squad_id} absente de units_cache : impossible d'en deriver le "
            f"joueur comme le fait le masque."
        )
    return int(require_key(cache_entry, "player"))


def _target_slot_entries(
    valid_actions: List[int],
    slots,
    slot_base: int,
    game_state: Dict[str, Any],
    active_unit: Dict[str, Any],
) -> List[Tuple[int, str, Dict[str, Any]]]:
    """[(action, squad_id ennemi, UNITE de game_state["units"])] pour les slots ouverts par le masque.

    ⚠️ L'unite rendue est la DATASHEET (`game_state["units"]`), PAS l'entree `units_cache` :
    `build_units_cache` ne recopie que l'etat spatial et vital (col/row/level/HP_CUR/player/
    VALUE/socle/empreintes) — jamais RNG_WEAPONS/CC_WEAPONS. Rendre l'entree de cache faisait
    donc lever `get_max_ranged_damage` (« Required key 'RNG_WEAPONS' is missing ») des qu'un bot
    de menace ouvrait un slot. La presence dans `units_cache` reste la preuve de VIE (les morts
    en sont retires), et toute lecture de POSITION passe par le cache, jamais par la datasheet.
    """
    open_actions = [a for a in valid_actions if a in slots]
    if not open_actions:
        return []
    mapping = get_enemy_slot_mapping(game_state, _acting_player(game_state, active_unit))
    units_cache = require_key(game_state, "units_cache")
    units_by_id = {str(require_key(u, "id")): u for u in require_key(game_state, "units")}
    entries: List[Tuple[int, str, Dict[str, Any]]] = []
    for action in open_actions:
        slot = action - slot_base
        if slot >= len(mapping) or mapping[slot] is None:
            raise RuntimeError(
                f"Slot {slot} (action {action}) ouvert par le masque mais sans escouade ennemie "
                f"dans get_enemy_slot_mapping : masque et mapping ont diverge."
            )
        sid = str(mapping[slot])
        if sid not in units_cache:
            raise RuntimeError(
                f"Escouade ennemie {sid} du slot {slot} absente de units_cache."
            )
        unit = units_by_id.get(sid)
        if unit is None:
            raise RuntimeError(
                f"Escouade ennemie {sid} du slot {slot} absente de game_state['units'] : "
                f"impossible d'en lire la datasheet (armes)."
            )
        entries.append((action, sid, unit))
    return entries


def _best_slot_action(
    valid_actions: List[int],
    slots,
    slot_base: int,
    game_state: Dict[str, Any],
    active_unit: Dict[str, Any],
    score_fn,
) -> Optional[int]:
    """Action de slot dont la cible MAXIMISE `score_fn`, ou None si aucune cible retenue.

    `score_fn(squad_id, cache_entry, game_state) -> Optional[float]` ; renvoyer None ecarte la
    cible (doctrine du bot), ce qui n'est pas la meme chose qu'un score bas.
    """
    best_action: Optional[int] = None
    best_score = -float("inf")
    for action, sid, entry in _target_slot_entries(
        valid_actions, slots, slot_base, game_state, active_unit
    ):
        score = score_fn(sid, entry, game_state)
        if score is None:
            continue
        if score > best_score:
            best_score = score
            best_action = action
    return best_action


def _score_threat(sid: str, entry: Dict[str, Any], game_state: Dict[str, Any]) -> Optional[float]:
    """Menace de la cible : meilleur degat attendu, tir ou melee (meme mesure que
    RewardMapper._get_unit_threat)."""
    return max(get_max_ranged_damage(entry), get_max_melee_damage(entry))


def _score_wounded(sid: str, entry: Dict[str, Any], game_state: Dict[str, Any]) -> Optional[float]:
    """Cible la plus ENTAMEE : score = -HP (focus fire, doctrine greedy/agressive)."""
    hp = get_hp_from_cache(sid, game_state)
    if hp is None:
        raise RuntimeError(f"Cible {sid} ouverte par le masque mais absente du cache de HP.")
    return -float(hp)


def _score_objective_proximity(
    sid: str, entry: Dict[str, Any], game_state: Dict[str, Any]
) -> Optional[float]:
    """Cible la plus proche d'un objectif (doctrine de CONTROLE : frapper qui conteste).

    Score = -distance-hex a l'objectif le plus proche. Sans objectif sur la table la doctrine
    n'a pas d'objet : on retombe sur la menace, jamais sur un ordre de liste.
    """
    from engine.objective_distance import objective_distance_maps

    objectives = game_state.get("objectives")
    if not objectives:
        return _score_threat(sid, entry, game_state)
    # Position = units_cache (source de verite spatiale), jamais le col/row de la datasheet.
    col, row = require_unit_position(sid, game_state)
    # Distance a l'AIRE de l'objectif, pas a son centre (14.02) : le bot doit mesurer la meme
    # geometrie que l'agent qu'il sert a evaluer, sinon le score de reference decrit un autre jeu.
    return -float(min(int(m[col, row]) for m in objective_distance_maps(game_state)))


def _score_value_per_damage(
    sid: str, entry: Dict[str, Any], game_state: Dict[str, Any]
) -> Optional[float]:
    """Points RETIRES a l'adversaire par point de degat inflige : VALUE / PV restants.

    C'est la mesure exacte du critere de DEPARTAGE : `determine_winner_with_method` compare les
    VP d'objectifs, puis, a egalite, somme `unit["VALUE"]` sur les escouades ENCORE PRESENTES
    dans units_cache (« value_tiebreaker »). Une escouade ne rend donc sa VALUE qu'ENTIEREMENT,
    a sa mort — jamais au prorata des figurines tombees : le gain marginal d'un point de degat
    vaut VALUE / PV_restants. Un monstre a 120 points sur 10 PV (12.0 par PV) passe devant
    20 points de gretchins sur 2 PV (10.0 par PV) — l'inverse de `_score_wounded`, qui achevait
    le moins cher parce qu'il etait le plus proche de mourir.

    VALUE est lue sur la DATASHEET (`entry`, cf. `_target_slot_entries` : units_cache la porte
    aussi, mais la datasheet est la source de verite du contrat d'unite) et les PV sur
    units_cache, source de verite des HP_CUR.
    """
    hp = get_hp_from_cache(sid, game_state)
    if hp is None:
        raise RuntimeError(f"Cible {sid} ouverte par le masque mais absente du cache de HP.")
    hp_left = float(hp)
    if hp_left <= 0:
        raise RuntimeError(
            f"Cible {sid} presente dans units_cache avec HP_CUR={hp} : le cache ne contient que "
            f"des escouades vivantes, l'invariant est rompu."
        )
    return float(require_key(entry, "VALUE")) / hp_left


def _score_killable_then_wounded(attacker: Dict[str, Any], melee: bool):
    """Critere de TacticalBot : tuable ce tour > peu de PV > menace elevee.

    Ferme sur l'ATTAQUANT (ses degats attendus decident de « tuable »), d'ou la fabrique :
    `_best_slot_action` ne passe que la CIBLE a son `score_fn`.
    """
    our_damage = get_max_melee_damage(attacker) if melee else get_max_ranged_damage(attacker)

    def _score(sid: str, entry: Dict[str, Any], game_state: Dict[str, Any]) -> Optional[float]:
        hp = get_hp_from_cache(sid, game_state)
        if hp is None:
            raise RuntimeError(f"Cible {sid} ouverte par le masque mais absente du cache de HP.")
        threat = max(get_max_ranged_damage(entry), get_max_melee_damage(entry))
        return (1000.0 if hp <= our_damage else 0.0) + (10.0 - float(hp)) * 10.0 + threat * 5.0

    return _score


def _score_silence_the_guns(
    sid: str, entry: Dict[str, Any], game_state: Dict[str, Any]
) -> Optional[float]:
    """Cible de charge de TacticalBot : l'escouade de TIR la plus dangereuse (la faire taire)."""
    return get_max_ranged_damage(entry)


def _score_melee_threat_only(
    sid: str, entry: Dict[str, Any], game_state: Dict[str, Any]
) -> Optional[float]:
    """Contre-charge : ne retient que les cibles dont la MELEE prime sur le TIR ; parmi elles,
    la plus dangereuse au corps a corps. Une unite de tir est ecartee (None)."""
    melee = get_max_melee_damage(entry)
    if melee <= get_max_ranged_damage(entry):
        return None
    return melee


def _fight_action_by(
    valid_actions: List[int],
    game_state: Dict[str, Any],
    active_unit: Dict[str, Any],
    score_fn,
) -> Optional[int]:
    """Action de combat : cible tranchee par `score_fn`, sinon combat a vide (12.04/12.06)."""
    action = _best_slot_action(
        valid_actions, mi.FIGHT_SLOTS, mi.FIGHT_SLOT_BASE, game_state, active_unit, score_fn
    )
    if action is not None:
        return action
    if mi.ACTION_FIGHT_NO_TARGET in valid_actions:
        return mi.ACTION_FIGHT_NO_TARGET
    return None


def _charge_action_by(
    valid_actions: List[int],
    game_state: Dict[str, Any],
    active_unit: Dict[str, Any],
    score_fn,
) -> Optional[int]:
    """Action de charge (11.02) : cible tranchee par `score_fn`, None si aucune retenue.

    Il n'existe pas d'action « charger sans cible » : 11.02 conditionne la declaration a la
    presence d'au moins un ennemi a 12", donc sans cible aucun slot n'est ouvert.
    """
    return _best_slot_action(
        valid_actions, mi.CHARGE_SLOTS, mi.CHARGE_SLOT_BASE, game_state, active_unit, score_fn
    )


# --- Geometrie de deplacement : UNE fonction de score ponderee ---------------
# En move spatial, le TYPE de move (normal/advance/fall_back) est INFERE du cout geodesique par
# le moteur (shared_utils.infer_squad_move_type) : le bot ne choisit plus qu'une DESTINATION
# parmi le pool BFS legal (les hexes reellement executables), via select_movement_destination.
# Le wrapper d'eval traduit ensuite destination -> cellule -> action entiere. Choisir « la
# premiere cellule legale » donnerait un coin arbitraire de la grille (root cause §3 transposee,
# c'est explicitement rejete) : ce score donne a chaque bot une vraie geometrie.
#
# ⚠️ REFONTE — les trois heuristiques exclusives `_dest_toward_enemies` /
# `_dest_away_from_enemies` / `_dest_toward_objective` ont ete REMPLACEES par une seule fonction
# de score ponderee. Motif mesure : la victoire se decide aux VP d'objectifs
# (`determine_winner_with_method` : les kills ne tranchent qu'a egalite), et le win-rate de
# l'agent contre chaque bot suivait EXACTEMENT le rapport de ce bot aux objectifs — les bots qui
# les ignoraient etaient les plus faciles, et progressaient d'un run a l'autre pendant que les
# deux qui les jouaient regressaient. Une geometrie exclusive laissait un bot ignorer TOTALEMENT
# la condition de victoire ; un score pondere ne le permet plus.
#
#     score(dest) = w_obj * (-d_objectif) + w_enn * (-d_ennemi) [+ w_obj * hold_bonus sur zone]
#
# w_enn > 0 = se rapprocher, w_enn < 0 = s'eloigner. Le STYLE d'un bot est ce couple de poids,
# lu dans config/bot_movement_weights.json (aucun defaut : une cle absente leve).
#
# « Tenir l'objectif » est une REGLE DE SCORE (le bonus ci-dessus), plus une doctrine exclusive a
# ControlBot : tout bot assez objectif-centre reste sur une zone qu'il occupe deja.
#
# Convention WAIT : renvoyer la position courante de l'unite (`require_unit_position`) signale
# « je ne bouge pas » — le wrapper la traduit en WAIT. `start_pos` etant exclu du pool (§4.6),
# l'ancre n'est jamais une destination legale : le signal est donc sans ambiguite. La position
# courante est TOUJOURS candidate au score, et l'emporte a egalite (on ne bouge pas pour rien).

_MOVEMENT_WEIGHTS_CONFIG = "bot_movement_weights"


def _movement_weights_config() -> Dict[str, Any]:
    """config/bot_movement_weights.json, memoise par le config_loader."""
    from config_loader import get_config_loader

    return get_config_loader().load_config(_MOVEMENT_WEIGHTS_CONFIG, force_reload=False)


def load_movement_weights(bot_key: str, posture: Optional[str] = None) -> Tuple[float, float]:
    """(w_objective, w_enemy) du bot `bot_key` — `posture` pour les bots a postures.

    Aucune valeur par defaut : un bot absent du fichier, ou une cle de poids manquante, leve.
    """
    bots = require_key(_movement_weights_config(), "bots")
    entry = require_key(bots, bot_key)
    if posture is not None:
        entry = require_key(entry, posture)
    return float(require_key(entry, "w_objective")), float(require_key(entry, "w_enemy"))


def load_hold_bonus() -> float:
    """Bonus (en distance-hex) accorde a une destination situee dans une zone d'objectif."""
    return float(require_key(_movement_weights_config(), "hold_bonus"))


def _squad_on_objective(unit, game_state, zones=None) -> bool:
    """L'escouade est-elle a portee d'un objectif ? 14.02, lecture PAR FIGURINE.

    ⚠️ ROOT CAUSE CORRIGEE — les bots comparaient l'ANCRE d'escouade (`get_unit_coordinates`)
    aux hexes d'objectif. Le controle reel se joue sur l'EMPREINTE DE SOCLE de chaque figurine :
    une escouade dont une figurine couvre la zone alors que son ancre est a cote comptait pour
    le moteur et pas pour le bot. Implementation unique, celle du moteur
    (`game_state.unit_is_within_objective`) — les bots ne repondent pas a leur facon a une
    question de regle.
    """
    return unit_is_within_objective(game_state, unit, zones)


def _objective_context(game_state):
    """(cartes de distance aux aires, zones d'objectif, bonus de tenue) — une fois par decision.

    Les CARTES et non les centres : un objectif est toute son aire de terrain (14.02), et le bot
    qui sert de reference doit mesurer la meme geometrie que l'agent evalue. Les cartes sont
    memoisees par contenu (`engine.objective_distance`), donc ce contexte reste O(1).
    """
    from engine.objective_distance import objective_distance_maps

    objectives = game_state.get("objectives")  # get allowed : scenario sans objectif
    distance_maps = objective_distance_maps(game_state) if objectives else []
    return distance_maps, objective_hex_sets(game_state), load_hold_bonus()


def _objective_term(
    dest, distance_maps, zones, hold_bonus: float, w_obj: float,
    on_objective: Optional[bool] = None,
) -> float:
    """Part « objectif » du score d'une destination. Sans objectif sur la table : 0.0.

    `on_objective` force le verdict de presence (lecture exacte par figurine pour la position
    courante) ; None le derive de l'ancre de la destination candidate (heuristique O(1)).
    """
    if not len(distance_maps):
        return 0.0
    score = -w_obj * min(int(m[dest[0], dest[1]]) for m in distance_maps)
    inside = any(dest in zone for zone in zones) if on_objective is None else on_objective
    if inside:
        score += w_obj * hold_bonus
    return score


def _select_destination(
    valid_destinations, unit, game_state, w_obj: float, w_enn: float
) -> Tuple[int, int]:
    """Destination maximisant le score pondere ; la position courante est candidate (= WAIT).

    Cout : O(1) par candidate (distances ancre->ancre / ancre->centre d'objectif). Le pool BFS
    compte jusqu'a ~634 cellules sur board x5 ; recalculer une empreinte par candidate coutait
    ~44 ms/decision de bot. Le bonus de tenue se lit donc par ANCRE sur les candidates (choix de
    bot, heuristique assumee) et PAR FIGURINE sur la position courante (`_squad_on_objective`,
    exact) — c'est la position courante qui porte la decision « je tiens », donc c'est elle qui
    exige la lecture juste.
    """
    current = require_unit_position(unit, game_state)
    enemy_positions = _living_enemy_positions(unit, game_state)
    distance_maps, zones, hold_bonus = _objective_context(game_state)

    def _score(dest, on_objective: Optional[bool]) -> float:
        score = _objective_term(dest, distance_maps, zones, hold_bonus, w_obj, on_objective)
        if enemy_positions:
            score -= w_enn * _dest_nearest_enemy_hexdist(dest, enemy_positions)
        return score

    best_dest = current
    best_score = _score(current, _squad_on_objective(unit, game_state, zones))
    for dest in valid_destinations:
        score = _score(dest, None)
        if score > best_score:
            best_score = score
            best_dest = dest
    return best_dest


class _WeightedMover:
    """Socle des bots dont le deplacement est un couple de poids (cf. `_select_destination`).

    `MOVEMENT_BOT_KEY` designe l'entree du fichier de config ; `movement_weights` permet a un
    appelant (test) de fournir explicitement les poids au lieu de les lire dans la config.
    """

    MOVEMENT_BOT_KEY: str = ""

    # Pose par le __init__ de CHAQUE sous-classe (clampe dans [0,1]) : le socle le declare pour
    # que `_weighted_destination`, qui le lit, soit verifiable — il n'y a pas de valeur ici, une
    # sous-classe qui oublierait de l'initialiser doit lever a l'acces, pas heriter d'un 0.0.
    randomness: float

    # Poids de MISE EN PLACE par slot 4-8, et etat de la garde anti-repetition. Meme regle que
    # `randomness` : declares sans valeur, une sous-classe qui les oublie leve a l'acces.
    # TacticalBot ne les pose pas — il redefinit `select_placement_action` (cf. sa docstring).
    PLACEMENT_WEIGHTS: Dict[int, float]
    _deployment_last_action: Optional[int]
    _deployment_repeat_count: int
    _deployment_episode_marker: Optional[Any]

    def _random_escape_action(self, valid_actions: List[int]) -> int:
        """Tirage d'EXPLORATION (`randomness`) — le seul site autorise a ignorer la doctrine.

        Ne connait plus la phase, et n'a plus a la connaitre : la MISE EN PLACE ne passe plus par
        `select_action_with_state`. Le wrapper route deploiement et ingress directement vers
        `select_placement_action` (`BotControlledEnv._ask_bot_placement`), donc ce tirage ne peut
        plus voir un masque de deploiement — ni, avec lui, le `WAIT_ACTION` qui y vaut mise en
        RESERVES (20.01).

        ⚠️ CONSEQUENCE ASSUMEE (arbitree le 2026-08-05) : la mise en place n'a plus de clause
        d'exploration du tout. Elle en avait une au deploiement — un tirage UNIFORME sur les slots
        ouverts, qui court-circuitait la table de poids du bot dans `randomness` % des cas — et
        aucune a l'ingress, qui appelait deja `select_placement_action` en direct. Les deux sites
        etant des jumeaux, ils jouent desormais la MEME chose : la doctrine pure. TacticalBot, le
        holdout, devient donc strictement deterministe a la pose (premier slot ouvert) : ses
        win-rates d'avant ce chantier ne sont plus bit-a-bit comparables.
        """
        return int(random.choice(valid_actions))

    def select_placement_action(self, valid_actions: List[int], game_state) -> int:
        """Slot de MISE EN PLACE (03.02) : deploiement initial ET ingress move (20.04).

        L'ingress EST une mise en place, et le moteur en a fait le JUMEAU exact du deploiement
        (`ActionDecoder.ingress_slot_candidates` : memes 5 strategies, memes slots 4-8, seule
        l'aire legale change). Le bot y joue donc la MEME politique — deux tables de poids
        separees divergeraient au premier reglage, et un bot agressif arriverait de reserve
        comme un bot prudent.

        La garde anti-repetition est volontairement COMMUNE aux deux : son role est d'eviter
        que tout un camp se pose au meme endroit, et une arrivee de reserves qui reproduit le
        slot deja joue au deploiement pose exactement ce probleme.

        ⚠️ `require_key` et non un `.get` : le moteur ecrit `episode_number` a chaque reset
        (`W40KEngine.reset`), donc un etat qui fait poser un bot le porte toujours. Absent, le
        marqueur valait `None` d'un episode a l'autre et la garde anti-repetition ne se
        reinitialisait JAMAIS : une instance reutilisee entre episodes heritait du dernier slot
        pose et l'ecartait a la premiere pose du suivant. Jumeau exact du socle des doctrines
        (`ai/bot_doctrines.py`, `_PlacementMemory`) et du marqueur de tour de
        `DecapitationBot._focus`, durcis ensemble.
        """
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

    def _weights(self, posture: Optional[str] = None) -> Tuple[float, float]:
        override = getattr(self, "_movement_weights_override", None)
        if override is not None:
            entry = override if posture is None else require_key(override, posture)
            return float(entry[0]), float(entry[1])
        return load_movement_weights(self.MOVEMENT_BOT_KEY, posture)

    def _weighted_destination(
        self, unit, valid_destinations, game_state, posture=None
    ) -> Tuple[int, int]:
        """Chemin commun : tirage aleatoire eventuel, puis score pondere."""
        if game_state is None:
            raise ValueError(
                f"{type(self).__name__}.select_movement_destination exige game_state : le score "
                f"de destination lit les objectifs, les ennemis et la position courante."
            )
        # Le pool vide se tranche AVANT le tirage : sinon un bot sans destination legale
        # consommerait quand meme un tirage du RNG global, decalant la sequence de tous les
        # bots pour le reste de l'episode (ils partagent `random`).
        if valid_destinations and self.randomness > 0 and random.random() < self.randomness:
            chosen = random.choice(valid_destinations)
            return (int(chosen[0]), int(chosen[1]))
        w_obj, w_enn = self._weights(posture)
        return _select_destination(valid_destinations, unit, game_state, w_obj, w_enn)


def _living_enemy_positions(unit, game_state):
    """Ancres (col,row) des ennemis vivants de `unit`, depuis units_cache."""
    units_cache = require_key(game_state, "units_cache")
    positions = []
    for enemy in require_key(game_state, "units"):
        if enemy.get("player") == unit.get("player"):
            continue
        if not is_unit_alive(str(enemy["id"]), game_state):
            continue
        # `is_unit_alive` ci-dessus PROUVE la présence dans `units_cache` : la branche `else`
        # était morte, et elle repliait sur le col/row de la DATASHEET — pas la source de vérité
        # spatiale, donc une position potentiellement périmée. Même motif que les six autres
        # sites de ce fichier, écrit sous une autre forme (d'où sa survie au premier grep).
        entry = require_unit_from_cache(str(enemy["id"]), game_state, "_living_enemy_positions")
        if not entry_is_on_battlefield(entry):
            continue
        positions.append((int(entry["col"]), int(entry["row"])))
    return positions


def _dest_nearest_enemy_hexdist(dest, enemy_positions):
    """Distance-hex de la destination a l'ancre ennemie la plus proche."""
    return min(calculate_hex_distance(dest[0], dest[1], ec, er) for ec, er in enemy_positions)


def _select_weighted_deployment_action(
    valid_actions: List[int],
    weights_by_action: Dict[int, float],
    last_action: Optional[int],
    repeat_count: int,
    max_repeat: int,
) -> int:
    """Select deployment intent with weighted randomness and anti-repeat guard."""
    # `valid_actions` est deja le pool de slots de pose (cf. CONTRAT DES POLITIQUES DE POSE).
    candidates = list(valid_actions)

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

    randomness: float = 1.0

    def select_placement_action(self, valid_actions: List[int], game_state) -> int:
        """Slot de MISE EN PLACE (03.02) : deploiement initial ET ingress move (20.04).

        Uniforme sur les slots OUVERTS — c'est la doctrine de ce bot. `valid_actions` ne porte
        QUE des slots 4-8 : le wrapper a deja retire `WAIT_ACTION`, qui n'est pas une strategie
        de pose mais la decision 20.01 de mettre l'unite EN RESERVES au deploiement, et le
        choix de reserve appartient a la LISTE, jamais au bot (cf. CONTRAT DES POLITIQUES DE POSE).
        """
        return random.choice(valid_actions)

    def select_action_with_state(
        self, valid_actions: List[int], game_state, active_unit: Dict[str, Any]
    ) -> int:
        """Selection par phase. La MISE EN PLACE n'y figure pas : le wrapper route deploiement et
        ingress vers `select_placement_action` (`BotControlledEnv._ask_bot_placement`)."""
        if not valid_actions:
            return WAIT_ACTION
        phase = require_key(game_state, "phase")
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


class GreedyBot(_WeightedMover):
    """Pousse vers l'ennemi le plus proche et ACHEVE les cibles entamees.

    Critere de cible unique aux trois phases d'action (tir, charge, melee) : l'escouade la plus
    ENTAMEE (`_score_wounded`), lue sur le mapping de slots ennemis — jamais sur l'ordre des
    slots. Deplacement : poussee offensive dominante, corrigee d'un attrait d'objectif (il ne
    traverse plus la table en ignorant une zone qui gagne la partie).
    """

    MOVEMENT_BOT_KEY = "greedy"

    PLACEMENT_WEIGHTS = {
        DEPLOYMENT_ACTIONS[0]: 0.30,  # aggressive front
        DEPLOYMENT_ACTIONS[1]: 0.30,  # objective pressure
        DEPLOYMENT_ACTIONS[2]: 0.20,  # safe/cohesion
        DEPLOYMENT_ACTIONS[3]: 0.10,  # left flank
        DEPLOYMENT_ACTIONS[4]: 0.10,  # right flank
        DEPLOYMENT_ACTIONS[5]: 0.08,  # centre hub
        DEPLOYMENT_ACTIONS[6]: 0.02,  # safe rear
    }

    def __init__(self, randomness: float = 0.0, movement_weights=None):
        """
        Initialize GreedyBot with optional randomness.

        Args:
            randomness: Probability [0.0-1.0] of making a random move instead of greedy choice.
                       0.0 = pure greedy, 0.15 = 15% random actions (recommended for training)
            movement_weights: (w_objective, w_enemy) explicites ; None = lus dans la config.
        """
        self.randomness = max(0.0, min(1.0, randomness))  # Clamp to [0, 1]
        self._movement_weights_override = movement_weights
        self._deployment_last_action: Optional[int] = None
        self._deployment_repeat_count = 0
        self._deployment_episode_marker: Optional[Any] = None

    def select_action_with_state(
        self, valid_actions: List[int], game_state, active_unit: Dict[str, Any]
    ) -> int:
        """Phase-aware greedy policy. Le move est routee par le wrapper vers
        select_movement_destination : cette methode ne traite plus la phase move."""
        if not valid_actions:
            return WAIT_ACTION
        phase = require_key(game_state, "phase")
        if self.randomness > 0 and random.random() < self.randomness:
            return self._random_escape_action(valid_actions)
        # Doctrine greedy : ACHEVER. Tir, charge et melee visent l'escouade la plus ENTAMEE —
        # un seul critere, le meme partout, jamais l'ordre des slots.
        if phase == "shoot":
            if _has_action_in(valid_actions, mi.SHOOT_SLOTS):
                return _shoot_focus_fire(valid_actions, game_state, active_unit, _score_wounded)
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]
        if phase == "charge":
            charge = _charge_action_by(valid_actions, game_state, active_unit, _score_wounded)
            if charge is not None:
                return charge
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]
        if phase == "fight":
            fight = _fight_action_by(valid_actions, game_state, active_unit, _score_wounded)
            if fight is not None:
                return fight
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]
        return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

    def select_movement_destination(self, unit, valid_destinations: List[Tuple[int, int]], game_state=None) -> Tuple[int, int]:
        """Greedy : poussee offensive ponderee d'un attrait d'objectif."""
        return self._weighted_destination(unit, valid_destinations, game_state)


class DefensiveBot(_WeightedMover):
    """Prioritizes survival, maintains distance, contre-charge les menaces de melee.

    Deplacement : recule DEVANT l'ennemi mais VERS son objectif — le repli pur l'emmenait au
    bord de la table, hors de la seule chose qui marque des points.
    Charge : cf. `_charge_action` (doctrine de contre-charge).
    Combat : frappe la cible la PLUS MENACANTE (neutraliser la source de degats).
    """

    MOVEMENT_BOT_KEY = "defensive"

    PLACEMENT_WEIGHTS = {
        DEPLOYMENT_ACTIONS[0]: 0.20,  # aggressive front
        DEPLOYMENT_ACTIONS[1]: 0.25,  # objective pressure
        DEPLOYMENT_ACTIONS[2]: 0.35,  # safe/cohesion
        DEPLOYMENT_ACTIONS[3]: 0.10,  # left flank
        DEPLOYMENT_ACTIONS[4]: 0.10,  # right flank
        DEPLOYMENT_ACTIONS[5]: 0.03,  # centre hub
        DEPLOYMENT_ACTIONS[6]: 0.17,  # safe rear
    }

    def __init__(self, randomness: float = 0.0, movement_weights=None):
        """
        Initialize DefensiveBot with optional randomness.

        Args:
            randomness: Probability [0.0-1.0] of making a random move instead of defensive choice.
                       0.0 = pure defensive, 0.15 = 15% random actions (recommended for training)
            movement_weights: (w_objective, w_enemy) explicites ; None = lus dans la config.
        """
        self.randomness = max(0.0, min(1.0, randomness))  # Clamp to [0, 1]
        self._movement_weights_override = movement_weights
        self._deployment_last_action: Optional[int] = None
        self._deployment_repeat_count = 0
        self._deployment_episode_marker: Optional[Any] = None

    def select_movement_destination(self, unit, valid_destinations: List[Tuple[int, int]], game_state=None) -> Tuple[int, int]:
        """Defensif : maintien de distance, mais l'attrait d'objectif borne le repli."""
        return self._weighted_destination(unit, valid_destinations, game_state)

    def select_action_with_state(
        self, valid_actions: List[int], game_state, active_unit: Dict[str, Any]
    ) -> int:
        """
        Enhanced defensive logic with threat awareness.
        Prioritize shooting threats, move away from danger zones.
        """
        if not valid_actions:
            return WAIT_ACTION
        phase = require_key(game_state, "phase")

        # L'escouade activee est FOURNIE par le wrapper (`eligible_units[0]`), la meme que celle
        # dont le masque est construit. La deviner (« premiere unite vivante de current_player »)
        # designait potentiellement une AUTRE escouade — et, en phase de combat, un autre joueur,
        # la selection 12.04 alternant entre les deux camps.
        if self.randomness > 0 and random.random() < self.randomness:
            return self._random_escape_action(valid_actions)

        nearby_threats = self._count_nearby_threats(active_unit, game_state)

        # La phase move est routee par le wrapper vers select_movement_destination (repli
        # geometrique) : cette methode ne la traite plus.

        # Doctrine defensive : NEUTRALISER LA SOURCE DE DEGATS — tir et melee visent la cible
        # la PLUS MENACANTE (c'est ce que la docstring de la methode promettait deja), la charge
        # obeit a la contre-charge (`_charge_action`).
        if phase == "shoot":
            if _has_action_in(valid_actions, mi.SHOOT_SLOTS):
                return _shoot_focus_fire(valid_actions, game_state, active_unit, _score_threat)
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

        if phase == "charge":
            return self._charge_action(valid_actions, game_state, active_unit)

        if phase == "fight":
            fight = _fight_action_by(valid_actions, game_state, active_unit, _score_threat)
            if fight is not None:
                return fight
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

        # Hors phase d'action : sous la menace, tirer si le masque l'autorise ; sinon tenir.
        if nearby_threats > 0 and _has_action_in(valid_actions, mi.SHOOT_SLOTS):
            return _shoot_focus_fire(valid_actions, game_state, active_unit, _score_threat)

        if WAIT_ACTION in valid_actions:
            return WAIT_ACTION
        return valid_actions[0]

    def _charge_action(
        self, valid_actions: List[int], game_state, active_unit: Dict[str, Any]
    ) -> int:
        """CONTRE-CHARGE : le defensif ne cherche pas la melee, il refuse de la subir.

        Doctrine : quand une escouade ennemie de MELEE (degat de melee > degat de tir) est deja
        declarable comme cible de charge (11.02), elle viendra au contact de toute facon au tour
        suivant ; la laisser charger, c'est lui offrir Fights First (12.04 : « It made a charge
        move this turn ») et encaisser ses attaques en premier. Le bot prend donc les devants sur
        la plus dangereuse au corps a corps. Face a une escouade de TIR, charger reviendrait a
        abandonner sa position defensive pour un gain incertain : il tient sa ligne (WAIT).

        Avant cette doctrine, la branche terminale « si l'attente est disponible, attendre »
        s'appliquait a la phase de charge, dont le masque arme WAIT INCONDITIONNELLEMENT
        (shared_utils, phase charge) : le bot ne chargeait JAMAIS.
        """
        charge = _charge_action_by(
            valid_actions, game_state, active_unit, _score_melee_threat_only
        )
        if charge is not None:
            return charge
        return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]


    def _count_nearby_threats(self, unit, game_state) -> int:
        """Count enemy units within threatening range."""
        threat_count = 0
        _scale = game_state["inches_to_subhex"]
        threat_range = 12 * _scale
        unit_entry = require_unit_from_cache(str(unit["id"]), game_state, "_count_nearby_threats")
        if not entry_is_on_battlefield(unit_entry):
            return 0  # hors table : aucune menace ne l'atteint (20.01)
        unit_fp = entry_footprint(unit_entry)

        for enemy in require_key(game_state, 'units'):
            if enemy['player'] != unit['player'] and is_unit_alive(str(enemy["id"]), game_state):
                enemy_entry = require_unit_from_cache(
                    str(enemy["id"]), game_state, "_count_nearby_threats/enemy"
                )
                if not entry_is_on_battlefield(enemy_entry):
                    continue
                enemy_fp = entry_footprint(enemy_entry)
                distance = min_distance_between_sets(unit_fp, enemy_fp, max_distance=threat_range)
                if distance <= threat_range:
                    threat_count += 1

        return threat_count


class ControlBot(_WeightedMover):
    """
    Objective-focused bot that prioritizes capturing and holding control points.

    Strategy:
    - MOVE: score pondere fortement objectif (le bonus de tenue le fait rester sur une zone
      qu'il occupe deja — c'est desormais une regle de score commune, plus une clause propre
      a ce bot).
    - SHOOT: Prioritize enemies near objectives (contesting control).
    - CHARGE/FIGHT: Only engage to defend or contest an objective.
    - DEPLOYMENT: Weighted toward objective pressure.
    """

    MOVEMENT_BOT_KEY = "control"

    #: Biais vers la pression d'objectif, doctrine de la classe.
    PLACEMENT_WEIGHTS = {
        DEPLOYMENT_ACTIONS[0]: 0.15,
        DEPLOYMENT_ACTIONS[1]: 0.45,
        DEPLOYMENT_ACTIONS[2]: 0.20,
        DEPLOYMENT_ACTIONS[3]: 0.10,
        DEPLOYMENT_ACTIONS[4]: 0.10,
        DEPLOYMENT_ACTIONS[5]: 0.15,  # centre hub : multi-objectif = contrôle
        DEPLOYMENT_ACTIONS[6]: 0.05,  # safe rear
    }

    def __init__(self, randomness: float = 0.0, movement_weights=None):
        """
        Initialize ControlBot with optional randomness.

        Args:
            randomness: Probability [0.0-1.0] of making a random action.
            movement_weights: (w_objective, w_enemy) explicites ; None = lus dans la config.
        """
        self.randomness = max(0.0, min(1.0, randomness))
        self._movement_weights_override = movement_weights
        self._deployment_last_action: Optional[int] = None
        self._deployment_repeat_count = 0
        self._deployment_episode_marker: Optional[Any] = None

    def select_action_with_state(
        self, valid_actions: List[int], game_state, active_unit: Dict[str, Any]
    ) -> int:
        """Objective-aware action selection. Le move est routee par le wrapper vers
        select_movement_destination : cette methode ne traite plus la phase move."""
        if not valid_actions:
            return WAIT_ACTION
        phase = require_key(game_state, "phase")

        if self.randomness > 0 and random.random() < self.randomness:
            return self._random_escape_action(valid_actions)

        # Escouade activee FOURNIE par le wrapper : plus de devinette « premiere unite vivante
        # de current_player », qui pouvait designer une autre escouade et, en combat, un autre
        # joueur (la selection 12.04 alterne entre les camps).
        #
        # Doctrine de CONTROLE : frapper qui CONTESTE, c'est-a-dire la cible la plus proche d'un
        # objectif (`_score_objective_proximity`) — tir, charge et melee alignes sur le meme
        # critere, conformement a la docstring de la classe.
        if phase == "shoot":
            return self._shoot_action(valid_actions, game_state, active_unit)
        if phase == "charge":
            # « Suis-je sur un objectif ? » n'est lu QUE par la charge : la question est
            # calculee ici et pas en tete de methode. Depuis qu'elle se lit par figurine
            # (14.02 : empreinte de socle de chaque figurine vs zones d'objectif) elle n'est
            # plus une egalite de coordonnees, et ControlBot est le chemin le plus chaud du
            # panel (35 % des bots d'entrainement, 0.40 du poids d'evaluation).
            if self._is_on_objective(active_unit, game_state) and WAIT_ACTION in valid_actions:
                return WAIT_ACTION
            charge = _charge_action_by(
                valid_actions, game_state, active_unit, _score_objective_proximity
            )
            if charge is not None:
                return charge
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]
        if phase == "fight":
            fight = _fight_action_by(
                valid_actions, game_state, active_unit, _score_objective_proximity
            )
            if fight is not None:
                return fight
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

        return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

    def select_movement_destination(self, unit, valid_destinations: List[Tuple[int, int]], game_state=None) -> Tuple[int, int]:
        """Vers l'objectif ; le bonus de tenue le maintient sur la zone qu'il occupe deja.

        « Tenir » = renvoyer l'hex courant (le wrapper le traduit en WAIT), `start_pos` etant
        exclu du pool donc jamais une destination legale.
        """
        return self._weighted_destination(unit, valid_destinations, game_state)

    def _shoot_action(
        self, valid_actions: List[int], game_state: Dict[str, Any], active_unit: Dict[str, Any]
    ) -> int:
        """Tirer des que possible, sur l'escouade qui conteste le plus pres d'un objectif."""
        if _has_action_in(valid_actions, mi.SHOOT_SLOTS):
            return _shoot_focus_fire(
                valid_actions, game_state, active_unit, _score_objective_proximity
            )
        if WAIT_ACTION in valid_actions:
            return WAIT_ACTION
        return valid_actions[0]

    def _is_on_objective(self, unit: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
        """Lecture PAR FIGURINE (14.02) — cf. `_squad_on_objective`, implementation unique."""
        return _squad_on_objective(unit, game_state)


# ---------------------------------------------------------------------------
# PALIER 2 — Smart bots with focus-fire, advance and charge awareness
# ---------------------------------------------------------------------------

def _shoot_focus_fire(
    valid_actions: List[int],
    game_state: Dict[str, Any],
    active_unit: Dict[str, Any],
    score_fn,
) -> int:
    """Action de tir sur la cible qui maximise `score_fn`, sinon WAIT (aucun slot ouvert).

    ⚠️ ROOT CAUSE CORRIGEE — le focus-fire etait DEBRANCHE. L'ancienne implementation cherchait
    le meilleur index dans `active_unit["valid_target_pool"]` (le pool de tir de l'unite, construit
    par `shooting_build_valid_target_pool`) et l'utilisait comme INDEX DE SLOT
    (`SHOOT_SLOT_BASE + slot`). Or le masque ouvre `SHOOT_SLOT_BASE + slot_i` ou `slot_i` indexe
    `get_enemy_slot_mapping` (ordre : menace decroissante, stable sur la partie) : deux listes
    d'ordre ET de contenu differents. Le bot tirait donc sur une cible legale AUTRE que celle que
    son critere avait designee, et la garde `if action in valid_actions` masquait la divergence
    au lieu de la reveler. La cible est desormais lue sur le mapping, MEME source que le masque.

    L'unite active n'est plus un parametre : le mapping est par JOUEUR, pas par escouade. Les bots
    n'ont d'ailleurs pas acces a l'unite reellement activee (`eligible_units[0]` cote wrapper) —
    ils devinaient « la premiere unite vivante du joueur », qui pouvait etre une AUTRE escouade,
    donc un pool de cibles etranger a l'activation en cours.
    """
    action = _best_slot_action(
        valid_actions, mi.SHOOT_SLOTS, mi.SHOOT_SLOT_BASE, game_state, active_unit, score_fn
    )
    if action is not None:
        return action
    return WAIT_ACTION


def _count_objectives_controlled(game_state: Dict[str, Any], player: int) -> int:
    """Objectifs CONTROLES par `player`, lus dans l'etat que le moteur ecrit.

    ⚠️ ROOT CAUSE CORRIGEE — ce comptage recalculait un pseudo-controle « au moins une ANCRE
    amie sur un hexe d'objectif ». Le controle reel (14.02) est la somme des OC PAR FIGURINE sur
    l'empreinte, fige a chaque fin de phase et de tour par `calculate_objective_control`, qui
    ecrit `objective_controllers`. Un bot ne recalcule donc rien : il relit cet etat, comme
    l'observation de l'agent (`ObservationBuilder._squad_objective_control`) et comme le calcul
    de recompense (`reward_calculator`). L'ancien comptage ignorait aussi l'OC adverse : une
    zone contestee et PERDUE y comptait comme controlee.
    """
    controllers = require_key(game_state, "objective_controllers")
    return sum(1 for controller in controllers.values() if controller == player)



class AdaptiveBot(_WeightedMover):
    """
    Adapte sa strategie a l'etat de la partie.

    - Tours 1-2 (`early`) : rush objectif, charge pour contester.
    - `winning` : il TIENT ses objectifs (poids objectif fort + bonus de tenue), sans charger.
    - `losing` : ultra-agressif, pousse vers l'ennemi et charge.
    Focus-fire de la cible la plus entamee en permanence.

    ⚠️ « winning » signifiait S'ELOIGNER (`_dest_away_from_enemies`) : une fois le comptage
    d'objectifs juste (`_count_objectives_controlled` relit `objective_controllers`), cette
    posture se declenche bien plus souvent — et faisait alors FUIR les objectifs qui font
    gagner. Les deux corrections vont ensemble.
    """

    EARLY_TURN_THRESHOLD = 2
    MOVEMENT_BOT_KEY = "adaptive"

    PLACEMENT_WEIGHTS = {
        DEPLOYMENT_ACTIONS[0]: 0.25,
        DEPLOYMENT_ACTIONS[1]: 0.35,
        DEPLOYMENT_ACTIONS[2]: 0.20,
        DEPLOYMENT_ACTIONS[3]: 0.10,
        DEPLOYMENT_ACTIONS[4]: 0.10,
        DEPLOYMENT_ACTIONS[5]: 0.10,  # centre hub
        DEPLOYMENT_ACTIONS[6]: 0.10,  # safe rear
    }

    def __init__(self, randomness: float = 0.0, movement_weights=None):
        self.randomness = max(0.0, min(1.0, randomness))
        self._movement_weights_override = movement_weights
        self._deployment_last_action: Optional[int] = None
        self._deployment_repeat_count = 0
        self._deployment_episode_marker: Optional[Any] = None

    def select_action_with_state(
        self, valid_actions: List[int], game_state, active_unit: Dict[str, Any]
    ) -> int:
        if not valid_actions:
            return WAIT_ACTION
        phase = require_key(game_state, "phase")

        if self.randomness > 0 and random.random() < self.randomness:
            return self._random_escape_action(valid_actions)

        # Posture evaluee du point de vue du joueur AGISSANT (celui de l'escouade activee, la
        # source du masque), jamais de `current_player` : en combat, la selection 12.04 alterne.
        acting_player = _acting_player(game_state, active_unit)
        turn = int(game_state.get("turn", 1))
        posture = self._evaluate_posture(game_state, acting_player, turn)

        # La phase move est routee par le wrapper vers select_movement_destination (posture).
        if phase == "shoot":
            return self._shoot(valid_actions, game_state, active_unit, posture)
        if phase == "charge":
            return self._charge(valid_actions, game_state, active_unit, posture)
        if phase == "fight":
            fight = _fight_action_by(valid_actions, game_state, active_unit, _score_wounded)
            if fight is not None:
                return fight
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

        return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

    def _evaluate_posture(self, game_state: Dict[str, Any], player: int, turn: int) -> str:
        """Return 'early', 'winning', or 'losing'."""
        if turn <= self.EARLY_TURN_THRESHOLD:
            return "early"
        my_obj = _count_objectives_controlled(game_state, player)
        # Adversaire = `3 - player` : le moteur ne connait que les joueurs 1 et 2 (cf.
        # fight_handlers `3 - selector`). `1 - player` designait le joueur 0 ou -1, qui ne
        # controle jamais rien — la posture etait donc « winning » des qu'on tenait un objectif.
        enemy_obj = _count_objectives_controlled(game_state, 3 - player)
        if my_obj > enemy_obj:
            return "winning"
        return "losing"

    def select_movement_destination(self, unit, valid_destinations: List[Tuple[int, int]], game_state=None) -> Tuple[int, int]:
        """Destination selon la posture (le type de move est infere par le moteur) :
        early -> rush objectif ; losing -> pousse vers l'ennemi ; winning -> TIENT l'objectif.
        """
        if game_state is None:
            raise ValueError(
                "AdaptiveBot.select_movement_destination exige game_state : la posture et le "
                "score de destination le lisent."
            )
        turn = int(game_state.get("turn", 1))
        posture = self._evaluate_posture(game_state, _acting_player(game_state, unit), turn)
        return self._weighted_destination(unit, valid_destinations, game_state, posture=posture)

    def _shoot(
        self,
        valid_actions: List[int],
        game_state: Dict[str, Any],
        active_unit: Dict[str, Any],
        posture: str,
    ) -> int:
        if any(a in valid_actions for a in mi.SHOOT_SLOTS):
            # Adaptatif : focus-fire de l'escouade la plus ENTAMEE, quelle que soit la posture.
            return _shoot_focus_fire(valid_actions, game_state, active_unit, _score_wounded)
        return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

    def _charge(
        self,
        valid_actions: List[int],
        game_state: Dict[str, Any],
        active_unit: Dict[str, Any],
        posture: str,
    ) -> int:
        """En posture defensive (« winning »), on ne charge pas ; sinon on charge l'escouade la
        plus ENTAMEE, meme critere que le tir et la melee de ce bot."""
        if posture == "winning":
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]
        charge = _charge_action_by(valid_actions, game_state, active_unit, _score_wounded)
        if charge is not None:
            return charge
        return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]


class ValueTradeBot(_WeightedMover):
    """Maximise le DIFFERENTIEL DE VALUE — le critere qui departage a VP d'objectifs egaux.

    Aucun autre bot du panel ne joue ce critere : ils visent les PV les plus bas
    (`_score_wounded`), la menace (`_score_threat`) ou la proximite d'objectif
    (`_score_objective_proximity`). Or `determine_winner_with_method` tranche les egalites de VP
    sur la VALUE totale restante (« value_tiebreaker »), et l'agent n'a jamais eu d'adversaire qui
    la defende ou l'attaque.

    - CIBLE (tir, charge, melee — un seul critere aux trois phases) : `_score_value_per_damage`,
      VALUE de la cible / PV restants. Il tue le monstre a 120 points plutot que les gretchins a
      20, la ou `GreedyBot` fait l'inverse a degats egaux.
    - ENGAGEMENT selon SON PROPRE profil, pas une portee fixee d'avance : melee attendue > tir
      attendu -> il cherche le contact (posture « engage », charge ouverte) ; sinon il tient sa
      portee (posture « standoff », pas de charge). Meme comparaison que
      `TacticalBot._select_charge_action`, ici etendue a la geometrie de deplacement.
    - RETRAIT : une escouade a lui, de haute VALUE et entamee, est SORTIE DU JEU (posture
      « withdraw ») — la garder au contact, c'est offrir a l'adversaire le departage.

    Les trois postures sont des couples de poids de `_select_destination` (aucune geometrie
    dediee), lus dans config/bot_movement_weights.json comme pour les autres bots.
    """

    MOVEMENT_BOT_KEY = "value_trade"

    #: Mise en place prudente : on ne brade pas sa VALUE au premier tour (safe/cohesion et
    #: pression d'objectif dominent, l'avance agressive est marginale).
    PLACEMENT_WEIGHTS = {
        DEPLOYMENT_ACTIONS[0]: 0.10,  # aggressive front
        DEPLOYMENT_ACTIONS[1]: 0.35,  # objective pressure
        DEPLOYMENT_ACTIONS[2]: 0.35,  # safe/cohesion
        DEPLOYMENT_ACTIONS[3]: 0.10,  # left flank
        DEPLOYMENT_ACTIONS[4]: 0.10,  # right flank
        DEPLOYMENT_ACTIONS[5]: 0.10,  # centre hub
        DEPLOYMENT_ACTIONS[6]: 0.10,  # safe rear
    }

    def __init__(self, randomness: float = 0.0, movement_weights=None):
        """
        Args:
            randomness: probabilite [0.0-1.0] de jouer une action au hasard.
            movement_weights: {posture: (w_objective, w_enemy)} explicites ; None = config.
        """
        self.randomness = max(0.0, min(1.0, randomness))
        self._movement_weights_override = movement_weights
        self._deployment_last_action: Optional[int] = None
        self._deployment_repeat_count = 0
        self._deployment_episode_marker: Optional[Any] = None

    def select_action_with_state(
        self, valid_actions: List[int], game_state, active_unit: Dict[str, Any]
    ) -> int:
        """Un seul critere de cible aux trois phases d'action : la VALUE par point de degat."""
        if not valid_actions:
            return WAIT_ACTION
        phase = require_key(game_state, "phase")

        if self.randomness > 0 and random.random() < self.randomness:
            return self._random_escape_action(valid_actions)

        if phase == "shoot":
            if _has_action_in(valid_actions, mi.SHOOT_SLOTS):
                return _shoot_focus_fire(
                    valid_actions, game_state, active_unit, _score_value_per_damage
                )
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]
        if phase == "charge":
            return self._charge(valid_actions, game_state, active_unit)
        if phase == "fight":
            # Au contact, il n'y a plus de portee a tenir : on frappe, et on frappe ce qui rend
            # le plus de points par degat (12.04/12.06 : combat a vide si aucun slot ouvert).
            fight = _fight_action_by(
                valid_actions, game_state, active_unit, _score_value_per_damage
            )
            if fight is not None:
                return fight
            return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

        return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

    def _charge(
        self, valid_actions: List[int], game_state: Dict[str, Any], active_unit: Dict[str, Any]
    ) -> int:
        """Charge SI le contact est son meilleur profil de degats, sur la cible la plus rentable.

        Le SI porte sur l'ATTAQUANT (melee attendue > tir attendu), le QUI sur la cible — meme
        decoupage que `TacticalBot._select_charge_action`, avec le critere de VALUE au lieu du
        « faire taire les canons ». Une escouade de tir qui chargerait perdrait sa portee, donc
        les degats qui alimentent le differentiel : elle tient sa ligne.
        """
        if get_max_melee_damage(active_unit) > get_max_ranged_damage(active_unit):
            charge = _charge_action_by(
                valid_actions, game_state, active_unit, _score_value_per_damage
            )
            if charge is not None:
                return charge
        return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

    def select_movement_destination(self, unit, valid_destinations: List[Tuple[int, int]], game_state=None) -> Tuple[int, int]:
        """Destination selon la posture : withdraw (sortir la piece chere) > engage > standoff."""
        if game_state is None:
            raise ValueError(
                "ValueTradeBot.select_movement_destination exige game_state : la posture, les "
                "objectifs, les ennemis et la position courante y sont lus."
            )
        posture = self._posture(unit, game_state)
        return self._weighted_destination(unit, valid_destinations, game_state, posture=posture)

    def _posture(self, unit: Dict[str, Any], game_state: Dict[str, Any]) -> str:
        """« withdraw » | « engage » | « standoff ».

        Le retrait PRIME : une piece chere entamee qui reste au contact finance le departage
        adverse, quel que soit son profil de degats.
        """
        if self._is_wounded_high_value(unit, game_state):
            return "withdraw"
        if get_max_melee_damage(unit) > get_max_ranged_damage(unit):
            return "engage"
        return "standoff"

    def _is_wounded_high_value(self, unit: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
        """Escouade a lui, ENTAMEE (08.03) ET plus chere que la moyenne de ses AUTRES escouades.

        ⚠️ « Entamee » est une question de REGLE, tranchee par le moteur
        (`is_unit_at_or_below_half_strength`, 08.03), pas par une comparaison maison — meme principe que
        `_squad_on_objective` pour 14.02. Le seuil naif `HP_CUR < HP_MAX * 0.5` est FAUX sur
        toute escouade multi-figurines : `units_cache["HP_CUR"]` porte la SOMME des PV des
        figurines vivantes (`_recompute_squad_hp_total`) alors que `unit["HP_MAX"]` est le PV
        d'UNE figurine. Dix Boyz a 1 PV donnent 10 < 0.5 : jamais vrai, meme a un survivant —
        la posture n'aurait tout simplement jamais existe sur les rosters reels. 08.03 compte,
        elle, les figurines vivantes (`alive <= initial / 2`) et ne retombe sur les PV que pour
        les unites mono-figurine, ou les deux mesures coincident.

        « Haute VALUE » est RELATIF a l'armee du moment : un seuil absolu en points serait faux
        d'un roster a l'autre (et deviendrait faux a chaque rebalance), et il perdrait son sens
        des que l'escouade chere du debut de partie est morte.

        La moyenne exclut l'escouade elle-meme, sans quoi une armee reduite a une seule escouade
        ne pourrait jamais se retirer (elle serait sa propre moyenne). Derniere escouade vivante :
        elle porte a elle seule tout le departage, donc entamee elle se retire.
        """
        squad_id = str(require_key(unit, "id"))
        if not is_unit_at_or_below_half_strength(squad_id, game_state):
            return False

        other_values = [
            float(require_key(friend, "VALUE"))
            for friend in require_key(game_state, "units")
            if friend.get("player") == unit.get("player")
            and str(friend["id"]) != squad_id
            and is_unit_alive(str(friend["id"]), game_state)
        ]
        if not other_values:
            return True
        return float(require_key(unit, "VALUE")) > sum(other_values) / len(other_values)


class TacticalBot(_WeightedMover):
    """
    Advanced tactical bot that properly uses all 4 game phases.

    This is the hardest bot to beat - it makes optimal decisions in each phase:
    - MOVE: Advances toward enemies if out of range, retreats if wounded — les deux corriges
      d'un terme d'objectif (`w_objective`), pour qu'un bot du panel ne puisse pas ignorer la
      condition de victoire ; sa geometrie ennemie propre est conservee
    - SHOOT: Always shoots if targets available, prioritizes wounded enemies
    - CHARGE: Charges if melee is advantageous (degats melee attendus > degats de tir)
    - FIGHT: Always fights when in melee, prioritizes killing wounded enemies

    Use this bot to test if agents learn proper multi-phase coordination.
    """

    MOVEMENT_BOT_KEY = "tactical"

    def __init__(self, randomness: float = 0.1, movement_weights=None):
        """
        Initialize TacticalBot.

        Args:
            randomness: Probability [0.0-1.0] of making suboptimal choice.
                       0.1 = 10% random (recommended for training diversity)
            movement_weights: (w_objective, w_enemy) explicites ; None = lus dans la config.
                       Seul w_objective est utilise : la geometrie ennemie de ce bot lui est
                       propre (portee de tir / fuite des menaces de melee), le terme objectif
                       s'y AJOUTE au lieu de la remplacer.
        """
        self.randomness = max(0.0, min(1.0, randomness))
        self._movement_weights_override = movement_weights

    def select_placement_action(self, valid_actions: List[int], game_state) -> int:
        """Premier slot de mise en place ouvert — deploiement initial ET ingress move (20.04).

        REDEFINIE au lieu d'heriter du socle pondere : ce bot est le HOLDOUT d'evaluation, le
        metre etalon dont la valeur est GELEE (cf. config/bot_movement_weights.json, entree
        « tactical »). Lui donner une table de poids CHANGERAIT le metre et rendrait
        incomparables toutes les mesures anterieures. « Premier slot ouvert » est exactement ce
        qu'il jouait, par la clause de repli de `select_action_with_state`.

        ⚠️ Cette methode RESTAURE ce comportement, elle ne l'invente pas. Depuis que le masque
        de deploiement ouvre `WAIT_ACTION` pour la mise en reserves 20.01
        (`ActionDecoder.get_squad_action_mask_and_eligible_units`), ce repli tombait sur WAIT :
        le bot mettait EN RESERVES toute unite tenant sous le plafond de 50 %, a chaque
        deploiement (mesure : 400/400). Un bot ne decide jamais d'une mise en reserves — c'est
        un choix de LISTE. Le retrait de `WAIT_ACTION` se fait desormais UNE fois en amont
        (`BotControlledEnv._open_placement_slots`) : `valid_actions[0]` est donc bien le premier
        slot de POSE ouvert, et jamais la mise en reserves.

        ⚠️ Depuis le routage de la mise en place par le wrapper (2026-08-05), cette politique
        est le SEUL comportement de pose du holdout : sa clause d'exploration `randomness` ne
        voit plus la phase de deploiement, ou elle tirait un slot uniforme dans 5 % des cas.
        """
        return valid_actions[0]

    def select_action_with_state(
        self, valid_actions: List[int], game_state, active_unit: Dict[str, Any]
    ) -> int:
        """Politique par phase du bot tactique (HOLDOUT d'evaluation, cf. docstring de module).

        ⚠️ CETTE METHODE N'EXISTAIT PAS : le wrapper teste `hasattr(bot,
        'select_action_with_state')` et, faute de l'avoir, appelait `select_action(valid_actions)`
        avec UN seul argument — donc `phase=None` et `game_state=None`, c'est-a-dire la branche
        « phase inconnue » pour TOUTE la partie. Le bot le plus difficile du panel jouait ainsi
        « premier slot de tir, sinon premier slot de charge, sinon premier slot de melee », et
        aucune de ses heuristiques de phase n'etait jamais atteinte. Elles le sont desormais.
        """
        if not valid_actions:
            return WAIT_ACTION
        phase = require_key(game_state, "phase")

        if self.randomness > 0 and random.random() < self.randomness:
            return self._random_escape_action(valid_actions)

        # La phase move est routee par le wrapper vers select_movement_destination.
        if phase == "shoot":
            return self._select_shoot_action(valid_actions, game_state, active_unit)
        if phase == "charge":
            return self._select_charge_action(valid_actions, game_state, active_unit)
        if phase == "fight":
            return self._select_fight_action(valid_actions, game_state, active_unit)
        return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

    def _select_shoot_action(
        self, valid_actions: List[int], game_state: Dict[str, Any], active_unit: Dict[str, Any]
    ) -> int:
        """Tir : toujours tirer si une cible est ouverte ; cible tuable > entamee > menacante."""
        if _has_action_in(valid_actions, mi.SHOOT_SLOTS):
            return _shoot_focus_fire(
                valid_actions,
                game_state,
                active_unit,
                _score_killable_then_wounded(active_unit, melee=False),
            )
        if WAIT_ACTION in valid_actions:
            return WAIT_ACTION
        return valid_actions[0]

    def _select_charge_action(
        self, valid_actions: List[int], game_state: Dict[str, Any], active_unit: Dict[str, Any]
    ) -> int:
        """Charge si la melee est AVANTAGEUSE, sur l'escouade de tir la plus dangereuse.

        Deux decisions distinctes, comme le disait deja la docstring de la classe : le SI porte
        sur l'attaquant (melee attendue > tir attendu), le QUI sur la cible (faire taire les
        armes de tir adverses). L'ancien critere `CC_DMG >= 2` portait sur un degat PAR TOUCHE
        d'un champ supprime du contrat d'unite.
        """
        if get_max_melee_damage(active_unit) > get_max_ranged_damage(active_unit):
            charge = _charge_action_by(
                valid_actions, game_state, active_unit, _score_silence_the_guns
            )
            if charge is not None:
                return charge
        if WAIT_ACTION in valid_actions:
            return WAIT_ACTION
        return valid_actions[0]

    def _select_fight_action(
        self, valid_actions: List[int], game_state: Dict[str, Any], active_unit: Dict[str, Any]
    ) -> int:
        """Melee : toujours combattre ; meme critere qu'au tir, sur les degats de MELEE."""
        fight = _fight_action_by(
            valid_actions,
            game_state,
            active_unit,
            _score_killable_then_wounded(active_unit, melee=True),
        )
        if fight is not None:
            return fight
        if WAIT_ACTION in valid_actions:
            return WAIT_ACTION
        return valid_actions[0]

    def select_movement_destination(self, unit: Dict, valid_destinations: List[Tuple[int, int]],
                                     game_state: Optional[Dict] = None) -> Tuple[int, int]:
        """
        Select best movement destination.

        Strategy:
        - If no enemies in range: move toward nearest enemy
        - If enemies in range: move to position with best LoS
        - If wounded: move away from melee threats
        Les deux positions sont corrigees d'un terme d'objectif (cf. `_objective_term`).
        """
        if game_state is None:
            raise ValueError(
                "TacticalBot.select_movement_destination exige game_state : la geometrie lit "
                "les ennemis, les objectifs et la position courante."
            )
        if not valid_destinations:
            return require_unit_position(unit, game_state)

        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_destinations)

        # Plus d'ennemi vivant : plus de geometrie de menace, le terme d'objectif tranche seul.
        nearest_enemy = self._find_nearest_enemy(unit, game_state)
        if not nearest_enemy:
            w_obj, w_enn = self._weights()
            return _select_destination(valid_destinations, unit, game_state, w_obj, w_enn)

        # Escouade ENTAMEE : elle se replie hors des menaces de melee.
        #
        # ⚠️ ROOT CAUSE CORRIGEE — le test etait `HP_CUR < HP_MAX * 0.5`, qui compare la SOMME
        # des PV des figurines vivantes (`units_cache["HP_CUR"]`, cf. `_recompute_squad_hp_total`)
        # au PV d'UNE figurine (`unit["HP_MAX"]`). Sur toute escouade multi-figurines le test est
        # faux meme a un survivant (10 Boyz : `10 < 0.5`, puis `1 < 0.5`), donc
        # `_find_safest_position` etait INJOIGNABLE — avec le terme d'objectif qu'on y a ajoute.
        # 08.03 (`is_unit_at_or_below_half_strength`) est l'implementation unique de la question, et
        # retombe sur les PV pour les mono-figurine, ou les deux mesures coincident.
        if is_unit_at_or_below_half_strength(str(unit["id"]), game_state):
            return self._find_safest_position(unit, valid_destinations, game_state)

        # Otherwise, move toward optimal shooting range
        return self._find_best_offensive_position(unit, valid_destinations, nearest_enemy, game_state)

    def _find_nearest_enemy(self, unit: Dict, game_state: Dict) -> Optional[Dict]:
        """Find nearest enemy unit."""
        nearest = None
        min_dist = float('inf')
        unit_entry = require_unit_from_cache(str(unit["id"]), game_state, "_find_nearest_enemy")
        if not entry_is_on_battlefield(unit_entry):
            return None  # hors table : pas de position d'où mesurer (20.01)
        unit_fp = entry_footprint(unit_entry)

        for enemy in require_key(game_state, 'units'):
            if enemy.get('player') != unit.get('player') and is_unit_alive(str(enemy.get("id")), game_state):
                enemy_entry = require_unit_from_cache(
                    str(enemy["id"]), game_state, "_find_nearest_enemy/enemy"
                )
                if not entry_is_on_battlefield(enemy_entry):
                    continue
                enemy_fp = entry_footprint(enemy_entry)
                dist = min_distance_between_sets(unit_fp, enemy_fp)
                if dist < min_dist:
                    min_dist = dist
                    nearest = enemy

        return nearest

    def _find_safest_position(self, unit: Dict, destinations: List[Tuple[int, int]],
                               game_state: Dict) -> Tuple[int, int]:
        """Position la plus eloignee des menaces de melee, corrigee du terme d'objectif.

        Sans ce terme, le repli du blesse le sortait de la table plutot que de le ramener sur
        la zone qui marque — c'est le defaut mesure sur `DefensiveBot`, transpose ici.
        """
        best_pos = destinations[0]
        best_score = -float('inf')
        w_obj, _ = self._weights()
        distance_maps, zones, hold_bonus = _objective_context(game_state)

        for col, row in destinations:
            unit_fp = compute_candidate_footprint(col, row, unit, game_state)
            min_enemy_dist = float('inf')
            for enemy in require_key(game_state, 'units'):
                if enemy.get('player') != unit.get('player') and is_unit_alive(str(enemy.get("id")), game_state):
                    # Only consider melee threats
                    if get_max_melee_damage(enemy) > get_max_ranged_damage(enemy):
                        enemy_entry = require_unit_from_cache(
                            str(enemy["id"]), game_state, "_find_safest_position/enemy"
                        )
                        if not entry_is_on_battlefield(enemy_entry):
                            continue
                        enemy_fp = entry_footprint(enemy_entry)
                        dist = min_distance_between_sets(unit_fp, enemy_fp)
                        min_enemy_dist = min(min_enemy_dist, dist)

            # Aucune menace de melee sur la table : la distance vaut +inf pour TOUTES les
            # candidates (le jeu d'ennemis est le meme), le terme d'objectif tranche seul.
            safety = 0.0 if min_enemy_dist == float('inf') else float(min_enemy_dist)
            score = safety + _objective_term((col, row), distance_maps, zones, hold_bonus, w_obj)
            if score > best_score:
                best_score = score
                best_pos = (col, row)

        return best_pos

    def _find_best_offensive_position(self, unit: Dict, destinations: List[Tuple[int, int]],
                                       target: Dict, game_state: Dict) -> Tuple[int, int]:
        """Position a portee de tir de la cible et la plus proche d'elle, terme d'objectif inclus.

        Deux passes, comme avant l'ajout du terme d'objectif, et pour la meme raison de COUT :
        la premiere garde `max_distance=rng_rng`, qui laisse `min_distance_between_sets` sortir
        sur une borne par boite englobante des que la candidate est hors portee (le contrat
        n'exige l'exactitude que sous le seuil, ce qui suffit au test `<=`). Fusionner les deux
        passes obligeait a une distance EXACTE pour chaque candidate — sur un pool de ~337 a
        634 cellules et des empreintes allant jusqu'a 1113 hexes, c'est le budget que le
        commentaire de tete du module chiffre a ~44 ms/decision.

        La seconde passe (exacte) ne sert qu'au cas ou AUCUNE position n'est a portee : on se
        rabat alors sur la plus proche, ou le classement doit etre juste.
        """
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
        from engine.utils.weapon_helpers import get_max_ranged_range
        rng_weapons = require_key(unit, 'RNG_WEAPONS')
        rng_rng = get_max_ranged_range(unit) if rng_weapons else 0
        target_entry = require_unit_from_cache(
            str(target["id"]), game_state, "_find_best_offensive_position/target"
        )
        target_fp = entry_footprint(target_entry)
        w_obj, _ = self._weights()
        distance_maps, zones, hold_bonus = _objective_context(game_state)
        best_pos = destinations[0]
        best_score = -float('inf')
        found_in_range = False

        for col, row in destinations:
            unit_fp = compute_candidate_footprint(col, row, unit, game_state)
            dist = min_distance_between_sets(unit_fp, target_fp, max_distance=rng_rng)
            if dist > rng_rng:
                continue
            found_in_range = True
            score = -float(dist) + _objective_term((col, row), distance_maps, zones, hold_bonus, w_obj)
            if score > best_score:
                best_score = score
                best_pos = (col, row)

        if not found_in_range:
            for col, row in destinations:
                unit_fp = compute_candidate_footprint(col, row, unit, game_state)
                dist = min_distance_between_sets(unit_fp, target_fp)
                score = -float(dist) + _objective_term(
                    (col, row), distance_maps, zones, hold_bonus, w_obj
                )
                if score > best_score:
                    best_score = score
                    best_pos = (col, row)

        return best_pos