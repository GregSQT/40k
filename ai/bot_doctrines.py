#!/usr/bin/env python3
"""ai/bot_doctrines.py — les six styles orthogonaux du panel d'evaluation.

CE QUE CE MODULE REMPLACE, ET POURQUOI
    Les six bots de `ai/evaluation_bots.py` tranchaient toutes leurs decisions sur
    `max(NB x DMG)` d'une seule arme : ni jet pour toucher, ni Force contre Endurance, ni AP
    contre sauvegarde, ni nombre de figurines, ni portee. Mesure du 2026-08-11 sur le roster
    500 pts d'ArmageddonAgent : **16 unites sur 23** passaient pour des unites de melee sous ce
    proxy, Intercessor compris — et c'est exactement le test qui decide de charger. Les bots
    envoyaient donc leurs tireurs au contact.
    Mesure du meme jour, cote resultat : le panel ne rendait que **deux signaux distincts pour
    six bots** (intervalles de confiance de `tactical`, `adaptive` et `value_trade` entierement
    recouvrants ; `greedy` 0,98 et `defensive` 0,96 indiscernables ; seul `control` 0,73
    informatif). Six adversaires pour deux mesures.

LE PRINCIPE — le PLANCHER est commun, le STYLE differencie
    Tous les bots d'ici partagent le meme socle de competence : ils estiment les degats par
    `engine.weapon_damage_cache.squad_expected_damage`, la MEME table pre-calculee que lit
    l'observation de l'agent (`ObservationBuilder._score_weapon_vs_target`). Aucun ne peut plus
    « ne pas savoir » viser. Ce qui les separe est le CRITERE : quoi maximiser, et quand.

LES SIX AXES — chacun punit une erreur DIFFERENTE de l'agent
    | style        | doctrine                                          | erreur punie                         |
    |--------------|---------------------------------------------------|--------------------------------------|
    | Racer        | prend tous les objectifs au plus vite, refuse le combat | l'agent qui campe sans contester |
    | Endgame      | tient le minimum tot, prend le maximum a partir du tour 3 | l'agent qui marque tot et se croit gagnant |
    | AlphaStrike  | cherche le contact au plus tot sur la piece cle    | l'agent qui expose ses tireurs      |
    | Attrition    | joue le departage VALUE, preserve ses pieces cheres | l'agent qui trade mal              |
    | Decapitation | concentre TOUT sur une escouade par tour            | l'agent qui etale ses forces        |
    Racer/Endgame sont les deux bornes du TEMPO, Attrition/Decapitation les deux facons
    opposees de depenser ses degats, AlphaStrike la distance nulle.

    ⚠️ `StandoffBot` (« tenir ses distances ») A ETE SUPPRIME le 2026-08-11, apres deux
    campagnes et une correction de poids : 0,92 / 0,90 / 0,97 contre trois agents de forces
    differentes, soit une amplitude de 0,05 — dans le bruit. Un bot qui rend le meme chiffre
    face a un agent faible et a un agent fort occupe une place de mesure sans rien mesurer.
    La cause est probablement le FORMAT : les points courent des le tour 2 et la partie
    s'arrete au tour 5, donc un style qui se preserve n'a jamais le temps d'etre paye.
    Il n'a pas ete remplace : cinq axes qui mesurent valent mieux que six dont un est muet.

    `AdaptiveBot` n'a PAS de successeur ici : c'etait un commutateur entre trois autres styles,
    donc correle a eux par construction — exactement ce que le panel doit cesser d'etre.

CE QUI RESTE DANS `evaluation_bots.py`
    Les six anciens bots, GELES (pas une ligne modifiee) jusqu'a la campagne de correspondance,
    et les primitives d'ESPACE D'ACTION (mapping slot -> escouade ennemie, pose ponderee), qui ne
    portent aucune doctrine et sont importees ici. Cf.
    `Documentation/Implementation/A_faire/bots_refonte_panel.md`.
"""

import random
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from engine import macro_intents as mi
from engine.combat_utils import calculate_hex_distance
from engine.game_state import objective_hex_sets, unit_is_within_objective
from engine.objective_distance import objective_distance_maps
from engine.phase_handlers.shared_utils import (
    get_hp_from_cache, is_unit_alive, is_unit_at_or_below_half_strength,
    require_unit_from_cache, require_unit_position,
    entry_is_on_battlefield,
)
from engine.utils.weapon_helpers import get_max_ranged_range
from engine.weapon_damage_cache import squad_expected_damage
from shared.data_validation import require_key

# Primitives d'espace d'action — AUCUNE doctrine, donc pas de raison de les redire ici. Les
# reecrire creerait le doublon divergent qui est le mode d'echec n°1 de ce depot.
from ai.evaluation_bots import (
    _acting_player, _best_slot_action, _select_weighted_deployment_action,
    DEPLOYMENT_ACTIONS, WAIT_ACTION,
)

#: Nombre de destinations retenues pour l'evaluation COUTEUSE (terme de tir).
#: Le pool BFS de move monte a ~458 cellules sur x1 et ~634 sur x5 (mesure du 2026-08-11) :
#: evaluer les degats depuis chacune coute plus que la partie entiere. Le pre-tri garde les
#: meilleures selon le terme geometrique (objectif/ennemi), qui est O(1) par candidate.
DESTINATION_SHORTLIST = 24


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Degats esperes — socle commun a tous les criteres de cible
# ─────────────────────────────────────────────────────────────────────────────────────────────

def _damage_on(game_state, attacker_id, target_id, is_ranged: bool) -> float:
    """Degats esperes d'une activation de `attacker_id` sur `target_id`, figurines comprises."""
    return squad_expected_damage(game_state, str(attacker_id), str(target_id), is_ranged)


def _phase_is_ranged(game_state) -> bool:
    """Le mode d'attaque de la phase courante. Tir en `shoot`, melee partout ailleurs.

    La charge se juge sur la MELEE : declarer une charge, c'est promettre un corps a corps.
    """
    return require_key(game_state, "phase") == "shoot"


def _score_efficiency(attacker, is_ranged: bool):
    """Cible sur laquelle JE fais le plus de degats. Le critere par defaut du panel.

    C'est la correction de fond : `_score_wounded` (ancien `GreedyBot`) achevait la cible la plus
    entamee, `_score_threat` (ancien `DefensiveBot`) visait la plus armee — aucun des deux ne
    regardait si l'attaquant pouvait seulement la blesser. Un bolter contre un vehicule T10 Sv2
    valait autant qu'un bolter contre de l'infanterie.
    """
    att_id = str(require_key(attacker, "id"))

    def _score(sid: str, entry: Dict[str, Any], game_state) -> Optional[float]:
        return _damage_on(game_state, att_id, sid, is_ranged)

    return _score


def _hp_left(sid: str, game_state) -> float:
    """PV restants d'une cible ouverte par le masque. Porte les DEUX invariants, une fois.

    `units_cache` ne contient que des escouades vivantes : une cible absente, ou presente a
    HP_CUR <= 0, est une divergence entre le masque et le cache — jamais un cas a absorber.
    Ces gardes vivaient recopiees dans `_score_kill_now` et `_score_value_removed`, dont une
    seule des deux verifiait la positivite.
    """
    hp = get_hp_from_cache(sid, game_state)
    if hp is None:
        raise RuntimeError(f"Cible {sid} ouverte par le masque mais absente du cache de HP.")
    hp_left = float(hp)
    if hp_left <= 0:
        raise RuntimeError(
            f"Cible {sid} presente dans units_cache avec HP_CUR={hp} : le cache ne contient "
            "que des escouades vivantes, l'invariant est rompu."
        )
    return hp_left


def _score_kill_now(attacker, is_ranged: bool):
    """Tuable CE TOUR d'abord, puis efficacite. Retirer une escouade retire son OC et ses tirs.

    « Tuable » se lit ici sur les degats esperes de TOUTE l'escouade attaquante contre les PV
    restants de la cible. L'ancien `_score_killable_then_wounded` comparait les PV de l'escouade
    au degat d'UNE arme d'UNE figurine : sur toute escouade multi-figurines la branche etait
    quasi toujours fausse, et le bonus de 1000 points ne se declenchait jamais.
    """
    att_id = str(require_key(attacker, "id"))

    def _score(sid: str, entry: Dict[str, Any], game_state) -> Optional[float]:
        damage = _damage_on(game_state, att_id, sid, is_ranged)
        return (1000.0 if damage >= _hp_left(sid, game_state) else 0.0) + damage

    return _score


def _score_value_removed(attacker, is_ranged: bool):
    """Points RETIRES a l'adversaire : VALUE x probabilite de retirer l'escouade.

    `determine_winner_with_method` departage les egalites de VP sur la VALUE totale restante, et
    une escouade ne rend sa VALUE qu'ENTIEREMENT, a sa mort. Le gain d'une activation est donc
    `VALUE x P(la tuer)`, approximee par la fraction de PV qu'on lui enleve.
    """
    att_id = str(require_key(attacker, "id"))

    def _score(sid: str, entry: Dict[str, Any], game_state) -> Optional[float]:
        damage = _damage_on(game_state, att_id, sid, is_ranged)
        return float(require_key(entry, "VALUE")) * min(
            1.0, damage / _hp_left(sid, game_state)
        )

    return _score


def _score_contester(attacker, is_ranged: bool):
    """Cible qui CONTESTE : la plus proche d'un objectif, a efficacite non nulle.

    Sans objectif sur la table la doctrine n'a pas d'objet — on retombe sur l'efficacite pure,
    jamais sur un ordre de slot.
    """
    att_id = str(require_key(attacker, "id"))

    def _score(sid: str, entry: Dict[str, Any], game_state) -> Optional[float]:
        damage = _damage_on(game_state, att_id, sid, is_ranged)
        if damage <= 0.0:
            # ⚠️ RENDRE `None`, ET SURTOUT PAS 0.0 — bug corrige le 2026-08-11. Le score des
            # cibles VALIDES est `-distance x 100 + degats`, donc NEGATIF des que la cible n'est
            # pas sur un objectif. Un 0.0 pour « je ne peux pas la blesser » etait alors le plus
            # HAUT score du lot : le bot visait en priorite les escouades contre lesquelles il
            # ne pouvait rien, et tirait dans le vide tant qu'il en restait une sur la table.
            # `None` ECARTE la cible (contrat de `_best_slot_action`), ce qui est la seule
            # reponse juste — « inattaquable » n'est pas une qualite de cible, c'est une
            # absence de cible.
            return None
        objectives = game_state.get("objectives")  # get allowed : scenario sans objectif
        if not objectives:
            return damage
        col, row = require_unit_position(sid, game_state)
        distance = min(int(m[col, row]) for m in objective_distance_maps(game_state))
        # Le degat departage a distance PROCHE, pas seulement a distance egale.
        #
        # ⚠️ Le facteur valait 100 : la distance ecrasait alors totalement les degats (un hex de
        # plus valait 100, quand une activation entiere en vaut 5 a 20). Le bot vidait ses bolters
        # sur le blinde pose sur la zone plutot que d'effacer l'infanterie a un hex de la. A 10,
        # la distance reste dominante — c'est la doctrine — mais l'efficacite departage entre deux
        # cibles proches l'une de l'autre, ce qui est exactement ce qu'on veut d'un bot qui
        # conteste : contester avec des tirs qui ne blessent pas, ce n'est pas contester.
        return -float(distance) * 10.0 + damage

    return _score


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Geometrie de deplacement — terme d'objectif, terme d'ennemi, terme de TIR
# ─────────────────────────────────────────────────────────────────────────────────────────────

def _best_melee_and_ranged(attacker, game_state) -> Optional[Tuple[float, float]]:
    """(meilleure melee, meilleur tir) de `attacker` CONTRE LES CIBLES REELLES, ou None sans ennemi.

    Compare sur l'ennemi le plus rentable dans chaque mode : une unite peut avoir une melee
    theoriquement superieure et n'avoir aucune cible qu'elle puisse entamer au contact. C'est le
    couple sur lequel se decide toute charge du panel — `_DoctrineBot._melee_beats_ranged` pour la
    regle par defaut, `AlphaStrikeBot.wants_charge` pour son seuil d'echange. Les deux le
    calculaient separement : le jour ou « meilleure cible » se raffine (portee de charge, cibles
    inatteignables), un seul des deux aurait suivi — et c'est justement le critere que tout ce
    module existe pour corriger.
    """
    att_id = str(require_key(attacker, "id"))
    enemies = _living_enemies_on_table(attacker, game_state)
    if not enemies:
        return None
    melee = max(_damage_on(game_state, att_id, str(e["id"]), False) for e in enemies)
    ranged = max(_damage_on(game_state, att_id, str(e["id"]), True) for e in enemies)
    return melee, ranged


def _living_enemies_on_table(unit, game_state) -> List[Dict[str, Any]]:
    """Escouades ennemies vivantes ET sur la table (20.01 : vivante n'est pas deployee)."""
    enemies = []
    for enemy in require_key(game_state, "units"):
        if enemy.get("player") == unit.get("player"):
            continue
        sid = str(enemy["id"])
        if not is_unit_alive(sid, game_state):
            continue
        entry = require_unit_from_cache(sid, game_state, "_living_enemies_on_table")
        if not entry_is_on_battlefield(entry):
            continue
        enemies.append(enemy)
    return enemies


def _firepower_profile(unit, enemies, game_state) -> List[Tuple[int, int, float, float, int]]:
    """(col, row, degats infliges, degats subis, portee ennemie) par ennemi — INDEPENDANT de `dest`.

    ⚠️ Ces quatre grandeurs ne dependent QUE du couple (attaquant, ennemi) : seule la comparaison
    « suis-je a portee ? » depend de la destination. Elles etaient recalculees pour CHACUNE des
    `DESTINATION_SHORTLIST` candidates, soit 48 x E appels de `squad_expected_damage` par decision
    de mouvement la ou 2 x E suffisent (chacun fait un lookup plus un comptage des figurines
    vivantes). Le profil est donc construit une fois par decision, et la boucle sur les
    destinations ne garde qu'une distance et deux comparaisons.
    """
    att_id = str(require_key(unit, "id"))
    profile = []
    for enemy in enemies:
        sid = str(enemy["id"])
        entry = require_unit_from_cache(sid, game_state, "_firepower_profile")
        profile.append((
            int(entry["col"]), int(entry["row"]),
            _damage_on(game_state, att_id, sid, True),
            _damage_on(game_state, sid, att_id, True),
            get_max_ranged_range(enemy),
        ))
    return profile


def _firepower_from(dest, profile, my_range: int) -> Tuple[float, float]:
    """(degats que J'infligerais depuis `dest`, degats que JE subirais a cette distance).

    Portee seule, PAS de ligne de vue : la LoS par candidate coute un calcul d'occultation par
    paire (destination, cible), et le pool de move compte des centaines de cellules. Le pre-tri
    `DESTINATION_SHORTLIST` borne le nombre de candidates evaluees ici ; la LoS reste hors de ce
    budget et n'est donc PAS prise en compte — un bot peut viser une position d'ou il n'a pas
    l'angle. C'est la limite assumee de cette geometrie, et elle est la meme pour les six styles,
    donc elle ne biaise aucune comparaison entre eux.

    Les distances sont ANCRE a ANCRE (les empreintes coutent une union d'hexes par candidate).
    """
    mine = 0.0
    theirs = 0.0
    for col, row, my_damage, their_damage, their_range in profile:
        distance = calculate_hex_distance(dest[0], dest[1], col, row)
        if distance <= my_range:
            mine += my_damage
        if distance <= their_range:
            theirs += their_damage
    return mine, theirs


def _objective_terms(game_state):
    """(carte de distance COMBINEE, zones) — une seule reduction par decision.

    Les cartes par objectif sont memoisees, mais leur reduction ne l'etait pas : `min(m[dest] for
    m in maps)` coutait une indexation numpy et un `int()` PAR CARTE et PAR CANDIDATE, sur un pool
    qui monte a 458 cellules (x1) et ~634 (x5). `np.minimum.reduce` une fois par decision rend la
    meme valeur pour un sixieme du temps.
    """
    objectives = game_state.get("objectives")  # get allowed : scenario sans objectif
    maps = objective_distance_maps(game_state) if objectives else []
    combined = np.minimum.reduce(maps) if len(maps) else None
    return combined, objective_hex_sets(game_state)


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Socle des doctrines
# ─────────────────────────────────────────────────────────────────────────────────────────────

class _PlacementMemory:
    """Politique de MISE EN PLACE ponderee, avec sa garde anti-repetition.

    SOURCE UNIQUE pour tout bot du panel refondu. Le meme automate — marqueur d'episode,
    `last_action`, `repeat_count`, `max_repeat=2` — existait en TROIS exemplaires : le module gele,
    le socle des doctrines et le holdout, qui par ailleurs revendique de n'avoir aucune doctrine de
    deploiement. Trois copies pour un seul comportement, donc trois editions au premier reglage.

    Le deploiement initial (03.02) et l'ingress move (20.04) jouent la MEME politique : le moteur
    a fait du second le jumeau exact du premier (memes cinq strategies, memes slots 4-8, seule
    l'aire legale change). Deux tables separees divergeraient au premier reglage, et un bot
    agressif arriverait de reserve comme un bot prudent. La garde anti-repetition est commune aux
    deux pour la meme raison : son role est d'eviter que tout un camp se pose au meme endroit, et
    une arrivee de reserves qui reproduit le slot du deploiement pose exactement ce probleme.

    `valid_actions` ne porte QUE des slots de pose : le wrapper a deja retire `WAIT_ACTION`, qui
    vaut « mise en RESERVES » (20.01) — un choix de LISTE qu'un bot ne prend jamais.
    """

    #: Poids par slot 4-8. Chaque bot la definit ; son absence est une erreur de programmation,
    #: pas un cas a absorber (d'ou l'annotation sans valeur).
    PLACEMENT_WEIGHTS: Dict[int, float]

    def __init__(self) -> None:
        self._deployment_last_action: Optional[int] = None
        self._deployment_repeat_count = 0
        self._deployment_episode_marker: Optional[Any] = None

    def select_placement_action(self, valid_actions: List[int], game_state) -> int:
        episode_marker = game_state.get("episode_number")  # get allowed (absent hors episode)
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


class _DoctrineBot(_PlacementMemory):
    """Socle commun. Une sous-classe ne redefinit que ce qui fait SON style.

    Points de variation, dans l'ordre d'importance :
      - `target_score(attacker, is_ranged, game_state)` : le critere de cible ;
      - `wants_charge(attacker, game_state)` : declarer une charge ou tenir sa ligne ;
      - `movement_weights(unit, game_state)` : (w_objectif, w_ennemi, w_tir, w_risque) ;
      - `PLACEMENT_WEIGHTS` : la pose.
    """

    #: Cle de l'entree de `config/bot_movement_weights.json`. Aucune valeur par defaut nulle part.
    MOVEMENT_BOT_KEY: str = ""

    PLACEMENT_WEIGHTS: Dict[int, float] = {}

    def __init__(self, randomness: float = 0.0):
        super().__init__()
        self.randomness = max(0.0, min(1.0, randomness))


    # -- Points de variation ------------------------------------------------------------------

    def target_score(self, attacker, is_ranged: bool, game_state):
        """Critere de cible du style. Par defaut : la cible sur laquelle je fais le plus de mal."""
        return _score_efficiency(attacker, is_ranged)

    def wants_charge(self, attacker, game_state) -> bool:
        """Declarer une charge ? Par defaut : seulement si la melee est mon meilleur mode.

        ⚠️ C'est ici que le proxy `NB x DMG` faisait le plus de degats : il classait 16 unites
        sur 23 du roster comme « melee », Intercessor (24") compris. La comparaison porte
        desormais sur les degats esperes CONTRE LES CIBLES REELLES, pas sur une caracteristique
        d'arme lue a vide.
        """
        return self._melee_beats_ranged(attacker, game_state)

    def movement_weights(self, unit, game_state) -> Tuple[float, float, float, float]:
        """(w_objectif, w_ennemi, w_tir, w_risque), lus dans la config. Aucun defaut."""
        return load_doctrine_weights(self.MOVEMENT_BOT_KEY)

    # -- Chemin commun ------------------------------------------------------------------------

    def _melee_beats_ranged(self, attacker, game_state) -> bool:
        """Mes degats esperes au contact depassent-ils mes degats esperes a distance ?"""
        profile = _best_melee_and_ranged(attacker, game_state)
        if profile is None:
            return False
        melee, ranged = profile
        return melee > ranged

    def select_action_with_state(
        self, valid_actions: List[int], game_state, active_unit: Dict[str, Any]
    ) -> int:
        """Selection par phase. La mise en place et le move sont routes ailleurs par le wrapper."""
        if not valid_actions:
            return WAIT_ACTION
        phase = require_key(game_state, "phase")

        if self.randomness > 0 and random.random() < self.randomness:
            return int(random.choice(valid_actions))

        if phase == "shoot":
            return self._shoot(valid_actions, game_state, active_unit)
        if phase == "charge":
            return self._charge(valid_actions, game_state, active_unit)
        if phase == "fight":
            return self._fight(valid_actions, game_state, active_unit)
        return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

    def _wait_or_first(self, valid_actions: List[int]) -> int:
        return WAIT_ACTION if WAIT_ACTION in valid_actions else valid_actions[0]

    def _shoot(self, valid_actions, game_state, active_unit) -> int:
        if not any(a in valid_actions for a in mi.SHOOT_SLOTS):
            return self._wait_or_first(valid_actions)
        action = _best_slot_action(
            valid_actions, mi.SHOOT_SLOTS, mi.SHOOT_SLOT_BASE, game_state, active_unit,
            self.target_score(active_unit, True, game_state),
        )
        return action if action is not None else WAIT_ACTION

    def _charge(self, valid_actions, game_state, active_unit) -> int:
        if not self.wants_charge(active_unit, game_state):
            return self._wait_or_first(valid_actions)
        action = _best_slot_action(
            valid_actions, mi.CHARGE_SLOTS, mi.CHARGE_SLOT_BASE, game_state, active_unit,
            self.target_score(active_unit, False, game_state),
        )
        return action if action is not None else self._wait_or_first(valid_actions)

    def _fight(self, valid_actions, game_state, active_unit) -> int:
        """Au contact il n'y a plus de portee a tenir : on frappe toujours (12.04/12.06)."""
        action = _best_slot_action(
            valid_actions, mi.FIGHT_SLOTS, mi.FIGHT_SLOT_BASE, game_state, active_unit,
            self.target_score(active_unit, False, game_state),
        )
        if action is not None:
            return action
        if mi.ACTION_FIGHT_NO_TARGET in valid_actions:
            return mi.ACTION_FIGHT_NO_TARGET
        return self._wait_or_first(valid_actions)

    # -- Deplacement --------------------------------------------------------------------------

    def select_movement_destination(
        self, unit, valid_destinations: List[Tuple[int, int]], game_state=None
    ) -> Tuple[int, int]:
        """Destination maximisant le score du style. La position courante est candidate (= WAIT).

        `start_pos` etant exclu du pool BFS, renvoyer la position courante est un signal sans
        ambiguite pour le wrapper : « je ne bouge pas ».
        """
        if game_state is None:
            raise ValueError(
                f"{type(self).__name__}.select_movement_destination exige game_state : le score "
                "lit les objectifs, les ennemis et les degats esperes."
            )
        current = require_unit_position(unit, game_state)
        if not valid_destinations:
            return current
        if self.randomness > 0 and random.random() < self.randomness:
            chosen = random.choice(valid_destinations)
            return (int(chosen[0]), int(chosen[1]))

        w_obj, w_enn, w_fire, w_risk = self.movement_weights(unit, game_state)
        distance_map, zones = _objective_terms(game_state)
        enemies = _living_enemies_on_table(unit, game_state)
        enemy_anchors = [
            (int(e["col"]), int(e["row"]))
            for e in (require_unit_from_cache(str(x["id"]), game_state, "_move") for x in enemies)
        ]
        hold_bonus = load_hold_bonus()

        def _geometric(dest, inside: bool) -> float:
            """`inside` est FOURNI par l'appelant : la position courante le sait par figurine
            (14.02, exact), les candidates par ancre (heuristique assumee). Le tri-etat
            `Optional[bool]` qui vivait ici mettait une branche dans le chemin chaud pour un seul
            appelant sur les ~458."""
            score = 0.0
            if distance_map is not None:
                score -= w_obj * int(distance_map[dest[0], dest[1]])
                if inside:
                    score += w_obj * hold_bonus
            if enemy_anchors:
                score -= w_enn * min(
                    calculate_hex_distance(dest[0], dest[1], ec, er) for ec, er in enemy_anchors
                )
            return score

        # 1re passe, O(1) par candidate : la position courante est lue PAR FIGURINE (14.02,
        # exact), les candidates par ancre (heuristique assumee, c'est la position courante qui
        # porte la decision « je tiens »).
        scored = [(_geometric(current, unit_is_within_objective(game_state, unit, zones)), current)]
        scored.extend(
            (_geometric(d, any(d in zone for zone in zones)), d) for d in valid_destinations
        )
        scored.sort(key=lambda pair: pair[0], reverse=True)

        # 2de passe, COUTEUSE, bornee au pre-tri : les degats esperes depuis la destination.
        if w_fire == 0.0 and w_risk == 0.0:
            return scored[0][1]
        my_range = get_max_ranged_range(unit) if require_key(unit, "RNG_WEAPONS") else 0
        profile = _firepower_profile(unit, enemies, game_state)
        best_dest, best_score = scored[0][1], -float("inf")
        for geometric, dest in scored[:DESTINATION_SHORTLIST]:
            mine, theirs = _firepower_from(dest, profile, my_range)
            total = geometric + w_fire * mine - w_risk * theirs
            if total > best_score:
                best_score = total
                best_dest = dest
        return best_dest


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Poids — aucune valeur par defaut, une cle absente leve
# ─────────────────────────────────────────────────────────────────────────────────────────────

_WEIGHTS_CONFIG = "bot_movement_weights"


def _weights_config() -> Dict[str, Any]:
    from config_loader import get_config_loader

    return get_config_loader().load_config(_WEIGHTS_CONFIG, force_reload=False)


def load_doctrine_weights(bot_key: str) -> Tuple[float, float, float, float]:
    """(w_objectif, w_ennemi, w_tir, w_risque) du style `bot_key`.

    Quatre termes et non deux : les six anciens bots n'avaient que la geometrie
    (objectif, ennemi), ce qui rendait impossible d'exprimer « je me place pour tirer » ou
    « je reste hors de portee ». Ces deux-la sont precisement les axes de Standoff et d'Endgame.
    """
    bots = require_key(_weights_config(), "doctrines")
    entry = require_key(bots, bot_key)
    return (float(require_key(entry, "w_objective")), float(require_key(entry, "w_enemy")),
            float(require_key(entry, "w_fire")), float(require_key(entry, "w_risk")))


def load_hold_bonus() -> float:
    return float(require_key(_weights_config(), "hold_bonus"))


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Les six styles
# ─────────────────────────────────────────────────────────────────────────────────────────────

class RacerBot(_DoctrineBot):
    """TEMPO haut : il prend tout, tout de suite, et refuse le combat.

    Punit l'agent qui s'assied sur ses objectifs sans jamais contester les autres. Il ne charge
    jamais — un corps a corps l'immobilise, or son avantage est le nombre de zones tenues.
    """

    MOVEMENT_BOT_KEY = "racer"
    PLACEMENT_WEIGHTS = {
        DEPLOYMENT_ACTIONS[0]: 0.10, DEPLOYMENT_ACTIONS[1]: 0.50, DEPLOYMENT_ACTIONS[2]: 0.10,
        DEPLOYMENT_ACTIONS[3]: 0.15, DEPLOYMENT_ACTIONS[4]: 0.15,
    }

    def target_score(self, attacker, is_ranged: bool, game_state):
        """Il tire sur qui conteste ses zones — le reste ne lui coute pas de points."""
        return _score_contester(attacker, is_ranged)

    def wants_charge(self, attacker, game_state) -> bool:
        return False


class EndgameBot(_DoctrineBot):
    """TEMPO bas : il se preserve, puis prend les zones quand elles comptent.

    Punit l'agent qui marque tot et relache. Avant le tour de bascule il tient ses distances et
    tire ; apres, il joue exactement comme un Racer.
    """

    MOVEMENT_BOT_KEY = "endgame"
    #: Tour a partir duquel il fond sur les objectifs.
    #:
    #: ⚠️ VALAIT 4, ET C'ETAIT PERDU D'AVANCE — mesure du 2026-08-11 : 0,025 de win-rate moyen
    #: contre les cinq autres styles, dernier de tres loin. Le score primaire court a partir du
    #: tour 2 (`config/primary_objective/.../Objectives_Control.json` : `start_turn: 2`,
    #: 15 VP/tour) et la partie dure 5 tours : ne rien tenir avant le tour 4, c'est renoncer aux
    #: tours 2 et 3, soit la MOITIE des tours qui rapportent. Aucun jeu de poids ne rattrape ca.
    #: « Jouer la fin de partie » ne peut donc pas vouloir dire « ne rien marquer avant » : il
    #: prend le premier palier tot (5 VP des qu'on tient une zone) et ne bascule sur le maximum
    #: qu'au tour 3, en gardant ses unites intactes pour ce moment-la.
    PUSH_TURN = 3
    PLACEMENT_WEIGHTS = {
        DEPLOYMENT_ACTIONS[0]: 0.05, DEPLOYMENT_ACTIONS[1]: 0.25, DEPLOYMENT_ACTIONS[2]: 0.50,
        DEPLOYMENT_ACTIONS[3]: 0.10, DEPLOYMENT_ACTIONS[4]: 0.10,
    }

    def _pushing(self, game_state) -> bool:
        return int(game_state.get("turn", 1)) >= self.PUSH_TURN

    def target_score(self, attacker, is_ranged: bool, game_state):
        if self._pushing(game_state):
            return _score_contester(attacker, is_ranged)
        return _score_efficiency(attacker, is_ranged)

    def wants_charge(self, attacker, game_state) -> bool:
        return self._pushing(game_state) and self._melee_beats_ranged(attacker, game_state)

    def movement_weights(self, unit, game_state):
        key = f"{self.MOVEMENT_BOT_KEY}_push" if self._pushing(game_state) else self.MOVEMENT_BOT_KEY
        return load_doctrine_weights(key)


class AlphaStrikeBot(_DoctrineBot):
    """DISTANCE nulle : il cherche le contact au plus tot, sur la piece qui compte.

    Punit l'agent qui expose ses tireurs. Il charge des qu'une cible est declarable — meme si sa
    melee n'est pas son meilleur mode : immobiliser un tireur adverse vaut le tir qu'il perd.
    """

    MOVEMENT_BOT_KEY = "alpha"
    PLACEMENT_WEIGHTS = {
        DEPLOYMENT_ACTIONS[0]: 0.55, DEPLOYMENT_ACTIONS[1]: 0.20, DEPLOYMENT_ACTIONS[2]: 0.05,
        DEPLOYMENT_ACTIONS[3]: 0.10, DEPLOYMENT_ACTIONS[4]: 0.10,
    }

    #: Part de son tir qu'il accepte de sacrifier pour aller au contact. Charger avec une unite
    #: dont la melee vaut MOINS que le tir est un echange perdant en degats bruts — mais un
    #: tireur adverse immobilise ne tire plus, et c'est la valeur propre de l'alpha strike. En
    #: dessous de ce seuil l'echange n'est plus rattrapable par cet effet.
    MELEE_TRADE_FLOOR = 0.5

    def target_score(self, attacker, is_ranged: bool, game_state):
        return _score_kill_now(attacker, is_ranged)

    def wants_charge(self, attacker, game_state) -> bool:
        """Charge si le contact vaut au moins la moitie de son tir.

        ⚠️ VALAIT `True` INCONDITIONNEL, et c'etait perdant des deux cotes — mesure du
        2026-08-11 : dernier du panel en bot-contre-bot (0,292) et sature contre l'agent
        (0,98). Charger avec n'importe quelle unite, y compris un tireur a 36 pouces face a une
        cible qu'il ne peut pas entamer au corps a corps, c'est offrir son escouade ET perdre
        son tir. Le seuil garde l'agressivite du style — il charge encore la ou les autres
        s'abstiennent — sans en faire un suicide systematique.
        """
        profile = _best_melee_and_ranged(attacker, game_state)
        if profile is None:
            return False
        melee, ranged = profile
        if melee <= 0.0:
            return False  # rien a faire au contact : y aller est une perte seche
        return melee >= ranged * self.MELEE_TRADE_FLOOR


class AttritionBot(_DoctrineBot):
    """VALEUR : il maximise le differentiel de points, et retire ses pieces cheres entamees.

    Punit l'agent qui trade mal. Seul style a jouer le critere de DEPARTAGE
    (`determine_winner_with_method`, « value_tiebreaker »).
    """

    MOVEMENT_BOT_KEY = "attrition"
    PLACEMENT_WEIGHTS = {
        DEPLOYMENT_ACTIONS[0]: 0.10, DEPLOYMENT_ACTIONS[1]: 0.35, DEPLOYMENT_ACTIONS[2]: 0.35,
        DEPLOYMENT_ACTIONS[3]: 0.10, DEPLOYMENT_ACTIONS[4]: 0.10,
    }

    def target_score(self, attacker, is_ranged: bool, game_state):
        return _score_value_removed(attacker, is_ranged)

    def _withdrawing(self, unit, game_state) -> bool:
        """Escouade a lui, ENTAMEE (08.03) et plus chere que la moyenne de ses AUTRES escouades.

        « Entamee » est une question de REGLE, tranchee par le moteur, pas par un `HP < HP_MAX/2`
        maison : `units_cache["HP_CUR"]` porte la SOMME des PV des figurines vivantes alors que
        `unit["HP_MAX"]` est le PV d'UNE figurine — le test naif est faux sur toute escouade
        multi-figurines.
        """
        sid = str(require_key(unit, "id"))
        if not is_unit_at_or_below_half_strength(sid, game_state):
            return False
        others = [
            float(require_key(friend, "VALUE"))
            for friend in require_key(game_state, "units")
            if friend.get("player") == unit.get("player")
            and str(friend["id"]) != sid
            and is_unit_alive(str(friend["id"]), game_state)
        ]
        if not others:
            return True  # derniere escouade : elle porte a elle seule tout le departage
        return float(require_key(unit, "VALUE")) > sum(others) / len(others)

    def wants_charge(self, attacker, game_state) -> bool:
        if self._withdrawing(attacker, game_state):
            return False
        return self._melee_beats_ranged(attacker, game_state)

    def movement_weights(self, unit, game_state):
        key = f"{self.MOVEMENT_BOT_KEY}_withdraw" if self._withdrawing(unit, game_state) \
            else self.MOVEMENT_BOT_KEY
        return load_doctrine_weights(key)


class DecapitationBot(_DoctrineBot):
    """CONCENTRATION : toutes ses escouades frappent la MEME cible dans le tour.

    Punit l'agent qui etale ses forces. Retirer une escouade entiere retire son OC et ses tirs ;
    l'etaler laisse tout le monde debout et tirer.

    ⚠️ Le focus est une MEMOIRE de tour, pas un score : les bots decident escouade par escouade
    sans se voir les unes les autres, donc aucun critere local ne peut produire une concentration.
    La cible est choisie a la premiere activation du tour et gardee tant qu'elle vit.
    """

    MOVEMENT_BOT_KEY = "decapitation"
    PLACEMENT_WEIGHTS = {
        DEPLOYMENT_ACTIONS[0]: 0.30, DEPLOYMENT_ACTIONS[1]: 0.30, DEPLOYMENT_ACTIONS[2]: 0.20,
        DEPLOYMENT_ACTIONS[3]: 0.10, DEPLOYMENT_ACTIONS[4]: 0.10,
    }

    def __init__(self, randomness: float = 0.0):
        super().__init__(randomness)
        self._focus_turn: Optional[Tuple[Any, int]] = None
        self._focus_target: Optional[str] = None

    def _focus(self, game_state) -> Optional[str]:
        """Cible du tour, oubliee au changement de tour ou a la mort de la cible."""
        marker = (game_state.get("episode_number"), int(game_state.get("turn", 1)))
        if self._focus_turn != marker:
            self._focus_turn = marker
            self._focus_target = None
        if self._focus_target is not None and not is_unit_alive(self._focus_target, game_state):
            self._focus_target = None
        return self._focus_target

    def target_score(self, attacker, is_ranged: bool, game_state):
        focused = self._focus(game_state)
        kill_now = _score_kill_now(attacker, is_ranged)

        def _score(sid: str, entry: Dict[str, Any], game_state) -> Optional[float]:
            # `kill_now` vaut `(1000 si letal) + degats`, et les PV sont strictement positifs
            # (`_hp_left`) : `base > 0` dit donc exactement « je peux l'entamer », sans qu'il
            # faille construire un second scorer pour poser la meme question.
            base = kill_now(sid, entry, game_state)
            if base is None:
                return None
            if focused is not None and sid == focused and base > 0.0:
                return base + 10_000.0  # la cible du tour prime, si on peut l'entamer
            return base

        return _score

    def _remember(self, action: Optional[int], slot_base: int, game_state, active_unit) -> None:
        """Enregistre la cible reellement choisie, pour que les suivantes la reprennent."""
        if action is None or self._focus_target is not None:
            return
        from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

        mapping = get_enemy_slot_mapping(game_state, _acting_player(game_state, active_unit))
        slot = action - slot_base
        if 0 <= slot < len(mapping) and mapping[slot] is not None:
            self._focus_target = str(mapping[slot])

    def _shoot(self, valid_actions, game_state, active_unit) -> int:
        action = super()._shoot(valid_actions, game_state, active_unit)
        if action in mi.SHOOT_SLOTS:
            self._remember(action, mi.SHOOT_SLOT_BASE, game_state, active_unit)
        return action

    def _fight(self, valid_actions, game_state, active_unit) -> int:
        action = super()._fight(valid_actions, game_state, active_unit)
        if action in mi.FIGHT_SLOTS:
            self._remember(action, mi.FIGHT_SLOT_BASE, game_state, active_unit)
        return action


#: Les six styles, par cle de configuration. `tactical` (le holdout) n'est PAS ici : il ne porte
#: pas de doctrine, il joue pour gagner — cf. le doc de chantier §3.3.
DOCTRINE_BOTS = {
    "racer": RacerBot,
    "endgame": EndgameBot,
    "alpha": AlphaStrikeBot,
    "attrition": AttritionBot,
    "decapitation": DecapitationBot,
}
