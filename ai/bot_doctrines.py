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
    `Documentation/Chantiers/backlog/panel_reference.md`.
"""

import random
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from engine import macro_intents as mi
from engine.combat_utils import calculate_hex_distance
from engine.game_state import (
    fold_control_contributions, objective_control_contributions, objective_hex_sets,
    unit_is_within_objective,
)
from engine.game_utils import get_effective_turn_limit
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
    _best_slot_action, _target_slot_entries, _select_weighted_deployment_action,
    DEPLOYMENT_ACTIONS, WAIT_ACTION,
)

#: Nombre de destinations retenues pour l'evaluation COUTEUSE (terme de tir).
#: Le pool BFS de move monte a ~458 cellules sur x1 et ~634 sur x5 (mesure du 2026-08-11) :
#: evaluer les degats depuis chacune coute plus que la partie entiere. Le pre-tri garde les
#: meilleures selon le terme geometrique (objectif/ennemi), qui est O(1) par candidate.
DESTINATION_SHORTLIST = 24

# ─────────────────────────────────────────────────────────────────────────────────────────────
# Constantes de capacites communes (Bot_refactor.md §4.A)
# ─────────────────────────────────────────────────────────────────────────────────────────────

#: Avance en VP pour passer en mode « proteger l'avance » (late_game_state).
_VP_LEAD_MARGIN: float = 15.0

#: Tours FINAUX qui declenchent « desperate_push » quand l'ecart de VP est inferieur a la marge.
_PUSH_LAST_TURNS: int = 3

#: Seuil de (pression × gain de style) au-dela duquel la preservation bloque une charge.
#: alpha (g=0) n'est jamais bloque ; scorer (g=0.6) l'est des que la pression depasse 0.5.
_PRESERVATION_CHARGE_THRESHOLD: float = 0.3


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Config des profils de style — bot_doctrine_profiles.json
# ─────────────────────────────────────────────────────────────────────────────────────────────

_PROFILES_CONFIG = "bot_doctrine_profiles"


def _profiles_config() -> Dict[str, Any]:
    from config_loader import get_config_loader
    return get_config_loader().load_config(_PROFILES_CONFIG, force_reload=False)


def load_style_profile(bot_key: str) -> Dict[str, Any]:
    """Profil de capacites du style `bot_key` : late_game, preservation, persistence, focus_shared."""
    return require_key(require_key(_profiles_config(), "profiles"), bot_key)


def _late_game_transform_cfg() -> Dict[str, Any]:
    return require_key(_profiles_config(), "late_game_transform")


def _state_overrides_cfg() -> Dict[str, Any]:
    return require_key(_profiles_config(), "state_overrides")


def get_jitter_config() -> Dict[str, float]:
    """Magnitudes du jitter (mouvement + comportement). Importe par env_wrappers."""
    cfg = require_key(_profiles_config(), "jitter")
    return {
        "movement_weight_jitter": float(require_key(cfg, "movement_weight_jitter")),
        "behavior_parameter_jitter": float(require_key(cfg, "behavior_parameter_jitter")),
    }


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

    def _score(sid: str, entry: Dict[str, Any], game_state) -> float:  # jamais `None`, cf.
        return _damage_on(game_state, att_id, sid, is_ranged)          # `_score_kill_now`

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

    ⚠️ `float`, PAS `Optional[float]` : ce scorer n'ECARTE aucune cible, il les classe toutes,
    zero degat compris. Le contrat de `_best_slot_action` autorise `None` — `_score_contester`
    s'en sert — mais l'annoncer ici quand on ne le rend jamais faisait ecrire chez les appelants
    des gardes `is None` MORTES (deux, corrigees le 2026-08-14 : `_elect` et le `target_score`
    de `DecapitationBot`). « Peut ecarter » se lit sur le type, donc le type doit etre vrai.
    """
    att_id = str(require_key(attacker, "id"))

    def _score(sid: str, entry: Dict[str, Any], game_state) -> float:
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

    def _score(sid: str, entry: Dict[str, Any], game_state) -> float:  # jamais `None`, cf.
        damage = _damage_on(game_state, att_id, sid, is_ranged)        # `_score_kill_now`
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
    couple sur lequel se decide toute charge du panel — `_DoctrineBot.wants_charge` pour la
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


#: Rabais de distance, EN HEXES, applique a un objectif selon qui le tient (cf.
#: `_objective_terms`). Un objectif tenu par l'ADVERSAIRE vaut double : le lui prendre le fait
#: passer de « il marque » a « je marque ». Un objectif NEUTRE vaut simple. Le mien vaut zero —
#: y envoyer une deuxieme escouade ne rapporte rien, la premiere le tient deja.
_CONTEST_PULL = {"enemy": 2.0, "neutral": 1.0, "mine": 0.0}


def _surplus_oc_by_zone(game_state, zones, me: int, sauf_escouade: str, contributions=None) -> List[float]:
    """Par zone : de combien d'OC MON camp y depasse deja l'adversaire, hors mon escouade.

    C'est la grandeur qui dit « cette zone est deja servie ». Le controle se tranche a la SOMME
    DES OC (`GameStateManager.calculate_objective_control` : `if player_1_oc > player_2_oc`),
    donc l'excedent au-dela de celui d'en face est exactement ce qui ne rapporte rien de plus.

    ⚠️ LE COMPTAGE EST CELUI DU MOTEUR, PAS UN SECOND (corrige le 2026-08-12). Cette fonction
    tranchait la presence sur l'hexe-CENTRE de chaque figurine et ignorait la regle 01.07, quand
    `sum_objective_control_oc_multi` compte des qu'une case de l'EMPREINTE DE SOCLE recouvre la
    zone et retire les escouades battle-shocked (02.02 : leur OC vaut '-'). Les deux ecarts
    tiraient dans des sens opposes et tous deux vers le defaut que ce chantier corrige : un gros
    socle au bord tenait la zone pour le moteur mais pas pour le bot, qui y renvoyait donc une
    escouade de plus ; une escouade choquee fabriquait a l'inverse un surplus FANTOME et faisait
    deserter une zone que le camp ne tenait pas. Deriver du moteur supprime la question : il n'y a
    plus qu'un comptage, donc plus rien a garder en phase.

    ⚠️ `sauf_escouade` est EXCLUE du total : sans ca, une escouade seule sur sa zone se verrait
    elle-meme comme un encombrement et la quitterait aussitot. L'exclusion est un FILTRE sur les
    contributions, jamais une question posee au moteur — le pourquoi est chez
    `objective_control_contributions`. Ce qui reste ici est de l'addition, pas de la geometrie.

    Aucune memoire de tour n'est necessaire : les escouades s'activent l'une apres l'autre et
    l'etat est a jour entre deux activations, donc la presence physique porte deja les
    deplacements qui viennent d'etre joues.
    """
    if not zones:
        return []
    if contributions is None:
        contributions = objective_control_contributions(game_state, zones)
    sauf = str(sauf_escouade)
    sums = fold_control_contributions(
        (part for squad_id, part in contributions.items() if squad_id != sauf), len(zones)
    )
    mien = 0 if int(me) == 1 else 1
    return [max(0.0, float(zone[mien] - zone[1 - mien])) for zone in sums]


def _objective_terms(
    game_state,
    me: Optional[int] = None,
    w_contest: float = 0.0,
    w_crowd: float = 0.0,
    escouade: Optional[str] = None,
    contributions=None,
):
    """(carte de distance COMBINEE, zones) — une seule reduction par decision.

    Les cartes par objectif sont memoisees, mais leur reduction ne l'etait pas : `min(m[dest] for
    m in maps)` coutait une indexation numpy et un `int()` PAR CARTE et PAR CANDIDATE, sur un pool
    qui monte a 458 cellules (x1) et ~634 (x5). `np.minimum.reduce` une fois par decision rend la
    meme valeur pour un sixieme du temps.

    ⚠️ LA CARTE EST PONDEREE PAR QUI TIENT QUOI — ajoute le 2026-08-12, et c'est le trou n°2 du
    §1 du chantier, reste ouvert par la refonte. Avant, la reduction etait une distance NUE : chaque
    escouade partait vers l'objectif le PLUS PROCHE d'elle, sans jamais savoir qu'une zone etait
    tenue par l'adversaire. Aucun bot n'allait donc contester quoi que ce soit — chacun s'asseyait
    sur son cote de la table. Mesure du 2026-08-12 sur 600 parties : le bot marquait 27,2 VP de
    moyenne contre 53,8 a l'agent, soit une zone tenue contre trois, et **zero victoire par
    elimination** — les deux camps se regardaient.
    Le rabais est retire de la DISTANCE, donc exprime en hexes : un objectif adverse a 10 hexes
    avec `w_contest = 3` pese comme un objectif neutre a 4. Il ne remplace pas la geometrie, il la
    corrige.

    ⚠️ LA CARTE EST AUSSI PENALISEE PAR L'ENCOMBREMENT ALLIE (`w_crowd`, 2026-08-12). Mesure sur
    600 parties du panel refondu : les bots empilent **2,6 a 3,0 escouades par zone** et n'en
    couvrent que 1,7 sur 5, quand l'agent etale les siennes sur 2,9. Ils ne sont ni lents (92 % de
    l'armee est dans une zone des le tour 3) ni battus au decompte (ils controlent 1,66 des 1,92
    zones ou ils sont presents) : ils vont simplement tous au meme endroit.
    C'est aussi ce qui rendait `w_contest` INERTE — rendre une zone plus attirante quand les cinq
    escouades calculent la meme reponse chacune dans son coin ne fait que DEPLACER LE TAS.
    La penalite porte sur le SURPLUS d'OC (cf. `_surplus_oc_by_zone`), pas sur l'occupation : une
    zone disputee n'est pas penalisee, donc les renforts y vont ; une zone deja gagnee large repousse
    la suivante. Elle est ajoutee a la DISTANCE, dans la meme unite que le rabais de contestation.

    `w_contest = 0.0` et `w_crowd = 0.0` rendent exactement la carte d'avant, au bit pres : c'est le
    defaut, et c'est ce qui rend chaque terme mesurable separement.
    """
    objectives = game_state.get("objectives")  # get allowed : scenario sans objectif
    maps = objective_distance_maps(game_state) if objectives else []
    if not len(maps):
        return None, objective_hex_sets(game_state)
    zones = objective_hex_sets(game_state)
    if w_crowd and me is not None and escouade is not None:
        surplus = _surplus_oc_by_zone(game_state, zones, int(me), str(escouade), contributions=contributions)
        maps = [m + w_crowd * s if s else m for m, s in zip(maps, surplus)]
    if w_contest and me is not None:
        # `get allowed` : le dict est cree PARESSEUSEMENT par `calculate_objective_control`, donc
        # legitimement absent tant qu'aucun controle n'a ete calcule (debut de partie). Absent =
        # personne ne tient rien, ce qui est l'etat reel et non un repli sur une valeur commode.
        controllers = game_state.get("objective_controllers") or {}
        opponent = 3 - int(me)
        pulls = []
        for objective in objectives:
            holder = controllers.get(str(require_key(objective, "id")))
            if holder is None:
                side = "neutral"
            else:
                side = "mine" if int(holder) == int(me) else (
                    "enemy" if int(holder) == opponent else "neutral"
                )
            pulls.append(w_contest * _CONTEST_PULL[side])
        # UNE soustraction par objectif et par DECISION (pas par candidate) : le cout est celui
        # d'un `np.subtract` sur la grille, deja paye par la memoisation des cartes.
        maps = [m - pull if pull else m for m, pull in zip(maps, pulls)]
    # FLOTTANT TOUJOURS. Les cartes du moteur sont des `int16` que les deux ponderations ci-dessus
    # promeuvent en `float64` — mais seulement si elles s'appliquent, et « un surplus non nul » est
    # une donnee de PARTIE, pas un reglage : sans cette conversion, le dtype du retour dependrait
    # de l'etat du jeu. Un lecteur serait alors juste tant qu'aucun allie ne tient de zone, puis
    # faux. `copy=False` : aucune copie quand la promotion a deja eu lieu.
    combined = np.minimum.reduce(maps).astype(np.float64, copy=False)
    return combined, zones


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Capacites communes — late_game, preservation, persistence (Bot_refactor.md §4.A)
# ─────────────────────────────────────────────────────────────────────────────────────────────

def late_game_state(game_state, player: int) -> str:
    """Etat global de partie du point de vue de `player`.

    Retourne "protect_lead" | "normal" | "desperate_push".

    Regles (Bot_refactor.md §4.A.1) :
    - desperate_push : tours_restants <= PUSH_LAST_TURNS ET ecart VP < _VP_LEAD_MARGIN
    - protect_lead   : ecart VP >= _VP_LEAD_MARGIN
    - normal         : sinon

    ⚠️ `get_effective_turn_limit` peut rendre `None` pour les batailles sans fin (Endless Duty).
    Dans ce cas la notion de « derniers tours » n'a pas de sens : on retombe sur normal/protect_lead
    selon le score uniquement.
    """
    vp_map = require_key(game_state, "victory_points")
    my_vp = float(require_key(vp_map, player))
    opp_vp = float(require_key(vp_map, 3 - player))
    vp_diff = my_vp - opp_vp

    if vp_diff >= _VP_LEAD_MARGIN:
        return "protect_lead"

    battle_turns = get_effective_turn_limit(game_state)
    if battle_turns is not None:
        current_turn = int(require_key(game_state, "turn"))
        turns_remaining = battle_turns - current_turn + 1
        if turns_remaining <= _PUSH_LAST_TURNS:
            return "desperate_push"

    return "normal"


def preservation_pressure(unit, game_state) -> float:
    """Pression de preservation pour `unit` : 0.0 (saine ou non exposee) .. 1.0.

    Facteurs (Bot_refactor.md §4.A.2) :
    - Saine (pas en dessous du demi-effectif, 08.03) -> 0.0 immediatement.
    - VALUE relative aux autres escouades du camp.
    - Titulaire d'objectif -> pression reduite de 50 % (sortir coute des points).

    ⚠️ « Entamee » est une question de REGLE, tranchee par `is_unit_at_or_below_half_strength`
    (08.03) et jamais par un `HP < HP_MAX/2` maison — `units_cache["HP_CUR"]` est la SOMME des
    PV de l'escouade alors que `unit["HP_MAX"]` est le PV d'UNE figurine.
    """
    sid = str(require_key(unit, "id"))
    if not is_unit_at_or_below_half_strength(sid, game_state):
        return 0.0

    my_value = float(require_key(unit, "VALUE"))
    others = [
        float(require_key(friend, "VALUE"))
        for friend in require_key(game_state, "units")
        if friend.get("player") == unit.get("player")
        and str(friend["id"]) != sid
        and is_unit_alive(str(friend["id"]), game_state)
    ]
    avg_value = sum(others) / len(others) if others else 0.0

    # Ratio normalise : l'escouade "moyenne" (my_value == avg_value) => pressure 0.5.
    # 2× la moyenne => pressure ~0.67. Zero value allies (derniere escouade) => 1.0.
    total = my_value + avg_value
    pressure = my_value / total if total > 0.0 else 1.0

    # Titulaire : la quitter couterait des points -> pression reduite.
    if unit_is_within_objective(game_state, unit, objective_hex_sets(game_state)):
        pressure *= 0.5

    return min(1.0, pressure)


def _apply_late_game_transform(
    weights: Tuple[float, float, float, float, float, float],
    state: str,
    g: float,
    k: float,
) -> Tuple[float, float, float, float, float, float]:
    """Transformation canonique du vecteur de poids selon l'etat de fin de partie.

    Regles (Bot_refactor.md §4.A.1, corrige 2026-08-15) :
    - desperate_push : w_obj*(1+g*k), w_contest*(1+g*k), w_risk*(1-g)
    - protect_lead   : w_risk*(1+g*k), w_enemy (signe-aware), w_contest*(1-g)
    - normal         : identite

    ⚠️ w_enemy SIGNE dans protect_lead : w>0 -> ×(1-g) ; w<0 -> ×(1+g·k) ; 0 reste 0.
    Une attenuation aveugle (1-g) sur un poids NEGATIF affaiblirait l'evitement au moment meme
    ou on veut le renforcer — `endgame` a w_enemy=-0.35.
    """
    w_obj, w_enn, w_fire, w_risk, w_contest, w_crowd = weights
    if state == "desperate_push":
        return (
            w_obj * (1.0 + g * k),
            w_enn,
            w_fire,
            w_risk * max(0.0, 1.0 - g),
            w_contest * (1.0 + g * k),
            w_crowd,
        )
    if state == "protect_lead":
        if w_enn > 0.0:
            w_enn_new = w_enn * max(0.0, 1.0 - g)
        elif w_enn < 0.0:
            w_enn_new = w_enn * (1.0 + g * k)
        else:
            w_enn_new = 0.0
        return (
            w_obj,
            w_enn_new,
            w_fire,
            w_risk * (1.0 + g * k),
            w_contest * max(0.0, 1.0 - g),
            w_crowd,
        )
    return weights


def _apply_jitter_weights(
    weights: Tuple[float, float, float, float, float, float],
    factors: Tuple[float, float, float, float, float, float],
) -> Tuple[float, float, float, float, float, float]:
    """Multiplication element par element — zero reste zero, signe conserve (spec §4.B)."""
    return tuple(w * f for w, f in zip(weights, factors))  # type: ignore[return-value]


def _best_slot_action_persistent(
    valid_actions: List[int],
    slots,
    slot_base: int,
    game_state: Dict[str, Any],
    active_unit: Dict[str, Any],
    score_fn,
    persistence_p: float,
    use_contester_scale: bool,
    targets_dict: Dict[str, Tuple[str, Any]],
) -> Tuple[Optional[int], Optional[str]]:
    """Action de slot avec regle de conservation de cible (Bot_refactor.md §4.A.3).

    Retourne (action, target_sid) — target_sid est stocke dans `targets_dict` pour le tour
    courant et relu a la prochaine activation de la meme escouade.

    Regle de conservation : garder la cible precedente ssi
    `meilleur - score(precedente) <= p * echelle`,
    ou echelle = abs(score precedent) pour les criteres positifs (ratio),
    ou 10.0 (un hex) pour `_score_contester`.

    Rupture : cible morte / hors table / absente du masque / score None / fin de tour.

    ⚠️ Ne touche PAS `evaluation_bots._best_slot_action` (bots geles, D10).
    """
    attacker_sid = str(require_key(active_unit, "id"))
    turn_marker: Any = (game_state.get("episode_number"), int(require_key(game_state, "turn")))

    entries = _target_slot_entries(valid_actions, slots, slot_base, game_state, active_unit)
    if not entries:
        targets_dict.pop(attacker_sid, None)
        return None, None

    # Score toutes les cibles ouvertes par le masque.
    scored: List[Tuple[float, int, str]] = []
    for action, sid, entry in entries:
        score = score_fn(sid, entry, game_state)
        if score is None:
            continue
        scored.append((score, action, sid))

    if not scored:
        targets_dict.pop(attacker_sid, None)
        return None, None

    best_score, best_action, best_sid = max(scored, key=lambda t: t[0])

    # Regle de conservation : tenter de garder la cible precedente.
    if persistence_p > 0.0:
        prev = targets_dict.get(attacker_sid)
        if prev is not None:
            prev_sid, prev_marker = prev
            if prev_marker == turn_marker:
                # Chercher la precedente dans le lot score (absente = rupture).
                prev_candidates = [(s, a, s2) for s, a, s2 in scored if s2 == prev_sid]
                if prev_candidates:
                    prev_score = prev_candidates[0][0]
                    if use_contester_scale:
                        scale = 10.0
                    else:
                        scale = abs(prev_score) if prev_score != 0.0 else 0.0
                    gap = best_score - prev_score
                    if gap <= persistence_p * scale:
                        best_action = prev_candidates[0][1]
                        best_sid = prev_sid

    targets_dict[attacker_sid] = (best_sid, turn_marker)
    return best_action, best_sid


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

    #: Poids par slot 4-10. Chaque bot la definit ; son absence est une erreur de programmation,
    #: pas un cas a absorber (d'ou l'annotation sans valeur).
    PLACEMENT_WEIGHTS: Dict[int, float]

    def __init__(self) -> None:
        self._deployment_last_action: Optional[int] = None
        self._deployment_repeat_count = 0
        self._deployment_episode_marker: Optional[Any] = None

    def select_placement_action(self, valid_actions: List[int], game_state) -> int:
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


class _DoctrineBot(_PlacementMemory):
    """Socle commun. Une sous-classe ne redefinit que ce qui fait SON style.

    Points de variation, dans l'ordre d'importance :
      - `target_score(attacker, is_ranged, game_state)` : le critere de cible ;
      - `wants_charge(attacker, game_state)` : declarer une charge ou tenir sa ligne ;
      - `movement_weights(unit, game_state)` : (w_objectif, w_ennemi, w_tir, w_risque, w_contest, w_crowd) ;
      - `PLACEMENT_WEIGHTS` : la pose.

    Capacites communes (Bot_refactor.md §4.A) : late_game, preservation, persistence.
    Chaque capacite est activee par un gain dans `config/bot_doctrine_profiles.json` :
    gain=0 -> identite exacte avec l'implementation precedente (verrou D4).

    Jitter (Bot_refactor.md §4.B) : multiplicatif sur le tuple de poids de mouvement et sur les
    gains de comportement. Stocke par `apply_episode_jitter`, jamais sur la config source.
    """

    #: Cle de l'entree de `config/bot_movement_weights.json` ET de `bot_doctrine_profiles.json`.
    MOVEMENT_BOT_KEY: str = ""

    PLACEMENT_WEIGHTS: Dict[int, float] = {}

    def __init__(self, randomness: float = 0.0):
        super().__init__()
        self.randomness = max(0.0, min(1.0, randomness))
        # Persistance de cible par escouade attaquante : sid -> (target_sid, turn_marker).
        self._persistence_targets: Dict[str, Tuple[str, Any]] = {}
        # Cache d'activation de objective_control_contributions (cle + valeur).
        self._contributions_cache_key: Optional[Any] = None
        self._contributions_cache_val: Optional[Any] = None
        # Jitter d'episode (§4.B). Facteurs multiplicatifs, neutre par defaut (1.0).
        self._jitter_movement: Tuple[float, float, float, float, float, float] = (
            1.0, 1.0, 1.0, 1.0, 1.0, 1.0
        )
        self._jitter_behavior: float = 1.0
        self._jitter_episode_marker: Optional[Any] = None

    # -- Jitter ------------------------------------------------------------------------------------

    def apply_episode_jitter(
        self,
        movement_factors: Tuple[float, float, float, float, float, float],
        behavior_factor: float,
        episode_marker: Any,
    ) -> None:
        """Stocke les facteurs de jitter de cet episode. Idempotent si meme marqueur.

        ⚠️ Suit exactement le patron de `_deployment_episode_marker` (§1.2.c du chantier) :
        les instances sont PARTAGEES entre episodes, donc tout etat doit etre garde sous un
        marqueur — sinon une fuite inter-episodes reproduit les bugs de `_focus_turn` et de
        la memoire de pose.
        """
        if self._jitter_episode_marker == episode_marker:
            return
        self._jitter_episode_marker = episode_marker
        self._jitter_movement = movement_factors
        self._jitter_behavior = behavior_factor

    # -- Profil de style ---------------------------------------------------------------------------

    def _style_profile(self) -> Dict[str, Any]:
        return load_style_profile(self.MOVEMENT_BOT_KEY)

    def _late_game_g(self) -> float:
        return float(require_key(self._style_profile(), "late_game")) * self._jitter_behavior

    def _preservation_g(self) -> float:
        return float(require_key(self._style_profile(), "preservation")) * self._jitter_behavior

    def _persistence_p(self) -> float:
        return float(require_key(self._style_profile(), "persistence")) * self._jitter_behavior

    def _is_preserving(self, unit, game_state) -> bool:
        """Etat de preservation par unite — FAUX par defaut (aucun override de vecteur).

        `AttritionBot` le surchage avec `_withdrawing` (route vers attrition_withdraw).
        Pour les autres styles, la preservation est continue (`preservation_pressure × g`)
        et module le vecteur sans passer par un override.
        """
        return False

    # -- Seuil de charge ---------------------------------------------------------------------------

    def _charge_trade_floor(self, game_state, player: int) -> float:
        """Facteur multiplicatif du seuil d'echange pour la charge, module par late_game.

        Retourne 1.0 a g=0 : le comportement est alors identique a `melee > ranged * 1.0`
        (c'est-a-dire l'ancien `_melee_beats_ranged`).

        desperate_push : abaisse le seuil (plus agressif).
        protect_lead   : releve le seuil (plus prudent).
        """
        g = self._late_game_g()
        if g <= 0.0:
            return 1.0
        lg = late_game_state(game_state, player)
        cfg = _late_game_transform_cfg()
        if lg == "desperate_push":
            return max(0.0, 1.0 - g)
        if lg == "protect_lead":
            k = float(require_key(cfg, "protect_gain"))
            return 1.0 + g * k
        return 1.0

    def _preservation_blocks_charge(self, attacker, game_state) -> bool:
        """La preservation continue coupe-t-elle la charge de cette escouade ?

        Produit (pression × sensibilite_style) compare au seuil. alpha (g=0) n'est jamais bloque.
        """
        g_pres = self._preservation_g()
        if g_pres <= 0.0:
            return False
        pressure = preservation_pressure(attacker, game_state)
        return pressure * g_pres >= _PRESERVATION_CHARGE_THRESHOLD

    # -- Critere de cible — persistance ------------------------------------------------------------

    def _uses_contester_score(self, unit, game_state) -> bool:
        """Ce style utilise-t-il `_score_contester` comme critere de cible ?

        Contester a une echelle fixe (10.0 = un hex) ; les autres criteres ont une echelle ratio.
        Surchargee par `RacerBot` et `ScorerBot` (toujours vrai), `EndgameBot` (selon l'etat).
        """
        return False

    # -- Points de variation -----------------------------------------------------------------------

    def target_score(
        self, attacker, is_ranged: bool, game_state
    ) -> Callable[[str, Dict[str, Any], Any], Optional[float]]:
        """Critere de cible du style. Par defaut : la cible sur laquelle je fais le plus de mal."""
        return _score_efficiency(attacker, is_ranged)

    def wants_charge(self, attacker, game_state) -> bool:
        """Declarer une charge ? Par defaut : melee > ranged * floor, avec preservation.

        ⚠️ C'est ici que le proxy `NB x DMG` faisait le plus de degats : il classait 16 unites
        sur 23 du roster comme « melee », Intercessor (24") compris. La comparaison porte
        desormais sur les degats esperes CONTRE LES CIBLES REELLES, pas sur une caracteristique
        d'arme lue a vide.

        Le seuil est module par `_charge_trade_floor` : desperate_push l'abaisse (plus agressif),
        protect_lead le releve (plus prudent). A gain=0 : floor=1.0 => melee > ranged (identique).
        """
        if self._is_preserving(attacker, game_state):
            return False
        if self._preservation_blocks_charge(attacker, game_state):
            return False
        profile = _best_melee_and_ranged(attacker, game_state)
        if profile is None:
            return False
        melee, ranged = profile
        if melee <= 0.0:
            return False
        player = int(require_key(attacker, "player"))
        return melee > ranged * self._charge_trade_floor(game_state, player)

    def movement_weights(self, unit, game_state) -> Tuple[float, float, float, float, float, float]:
        """(w_objectif, w_ennemi, w_tir, w_risque, w_contest, w_crowd) — lus dans la config.

        Logique (Bot_refactor.md §4.A, gain=0 => identite exacte) :
        1. Si _is_preserving() -> override "preserve" de state_overrides si disponible.
        2. Si late_game_state -> override direct si disponible dans state_overrides.
        3. Sinon : poids de base + transformation late_game + modulation de preservation.
        4. Jitter multiplicatif applique dans tous les cas (neutre a 1.0).
        """
        player = int(require_key(unit, "player"))

        overrides = _state_overrides_cfg().get(self.MOVEMENT_BOT_KEY, {})  # get allowed : override optionnel par doctrine

        # 1. Override de preservation par unite (uniquement AttritionBot via _withdrawing).
        if self._is_preserving(unit, game_state):
            if "preserve" in overrides:
                base = load_doctrine_weights(overrides["preserve"])
                return _apply_jitter_weights(base, self._jitter_movement)

        # 2. Override late_game.
        lg_state = late_game_state(game_state, player)
        if lg_state in overrides:
            base = load_doctrine_weights(overrides[lg_state])
            return _apply_jitter_weights(base, self._jitter_movement)

        # 3. Poids de base + transformations.
        base = load_doctrine_weights(self.MOVEMENT_BOT_KEY)

        g_late = self._late_game_g()
        if g_late > 0.0 and lg_state != "normal":
            cfg = _late_game_transform_cfg()
            k = float(require_key(cfg, "push_gain" if lg_state == "desperate_push" else "protect_gain"))
            base = _apply_late_game_transform(base, lg_state, g_late, k)

        g_pres = self._preservation_g()
        if g_pres > 0.0:
            pressure = preservation_pressure(unit, game_state)
            pres_eff = min(1.0, pressure * g_pres)
            if pres_eff > 0.0:
                # Module comme protect_lead avec g=pres_eff (protege une avance locale).
                cfg = _late_game_transform_cfg()
                k = float(require_key(cfg, "protect_gain"))
                base = _apply_late_game_transform(base, "protect_lead", pres_eff, k)

        return _apply_jitter_weights(base, self._jitter_movement)

    # -- Chemin commun -----------------------------------------------------------------------------

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
        p = self._persistence_p()
        use_contester = self._uses_contester_score(active_unit, game_state)
        action, _ = _best_slot_action_persistent(
            valid_actions, mi.SHOOT_SLOTS, mi.SHOOT_SLOT_BASE, game_state, active_unit,
            self.target_score(active_unit, True, game_state),
            p, use_contester, self._persistence_targets,
        )
        return action if action is not None else WAIT_ACTION

    def _charge(self, valid_actions, game_state, active_unit) -> int:
        if not self.wants_charge(active_unit, game_state):
            return self._wait_or_first(valid_actions)
        p = self._persistence_p()
        use_contester = self._uses_contester_score(active_unit, game_state)
        action, _ = _best_slot_action_persistent(
            valid_actions, mi.CHARGE_SLOTS, mi.CHARGE_SLOT_BASE, game_state, active_unit,
            self.target_score(active_unit, False, game_state),
            p, use_contester, self._persistence_targets,
        )
        return action if action is not None else self._wait_or_first(valid_actions)

    def _fight(self, valid_actions, game_state, active_unit) -> int:
        """Au contact il n'y a plus de portee a tenir : on frappe toujours (12.04/12.06)."""
        p = self._persistence_p()
        use_contester = self._uses_contester_score(active_unit, game_state)
        action, _ = _best_slot_action_persistent(
            valid_actions, mi.FIGHT_SLOTS, mi.FIGHT_SLOT_BASE, game_state, active_unit,
            self.target_score(active_unit, False, game_state),
            p, use_contester, self._persistence_targets,
        )
        if action is not None:
            return action
        if mi.ACTION_FIGHT_NO_TARGET in valid_actions:
            return mi.ACTION_FIGHT_NO_TARGET
        return self._wait_or_first(valid_actions)

    # -- Deplacement -------------------------------------------------------------------------------

    def _enemy_anchors(
        self, unit, game_state, enemies: List[Dict[str, Any]]
    ) -> List[Tuple[int, int]]:
        """Ancres ennemies que le terme d'ennemi du deplacement prend en compte.

        TOUTES par defaut : le terme vaut `-w_enemy x min(distance)`, c'est-a-dire « l'ennemi le
        plus proche, quel qu'il soit ». Un seul style restreint ce jeu (`DecapitationBot`, qui ne
        regarde que sa cible du tour), d'ou un point d'extension plutot qu'une branche par style
        dans `select_movement_destination` — celui-ci reste COMMUN aux six.
        """
        return [require_unit_position(x, game_state) for x in enemies]

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

        w_obj, w_enn, w_fire, w_risk, w_contest, w_crowd = self.movement_weights(unit, game_state)
        # Cache objective_control_contributions par activation (episode, tour, phase, unite).
        # Gate sur w_crowd : seul terme qui l'utilise — sans cache, _surplus_oc_by_zone l'appelle
        # une fois par figurine active dans le pool BFS.
        contributions = None
        if w_crowd:
            cache_key = (
                require_key(game_state, "episode_number"),
                require_key(game_state, "turn"),
                require_key(game_state, "phase"),
                str(require_key(unit, "id")),
            )
            if self._contributions_cache_key != cache_key:
                self._contributions_cache_key = cache_key
                zones_for_cache = objective_hex_sets(game_state)
                self._contributions_cache_val = objective_control_contributions(game_state, zones_for_cache)
            contributions = self._contributions_cache_val
        # La carte de distance est PONDEREE par qui tient quoi ET par ce que les allies couvrent
        # deja : c'est ici que le bot cesse d'aller betement vers la zone la plus proche, et qu'il
        # cesse d'y aller a cinq (cf. `_objective_terms`).
        distance_map, zones = _objective_terms(
            game_state,
            me=int(require_key(unit, "player")),
            w_contest=w_contest,
            w_crowd=w_crowd,
            escouade=str(require_key(unit, "id")),
            contributions=contributions,
        )
        enemies = _living_enemies_on_table(unit, game_state)
        enemy_anchors = self._enemy_anchors(unit, game_state, enemies)
        hold_bonus = load_hold_bonus()

        def _geometric(dest, inside: bool) -> float:
            """`inside` est FOURNI par l'appelant : la position courante le sait par figurine
            (14.02, exact), les candidates par ancre (heuristique assumee). Le tri-etat
            `Optional[bool]` qui vivait ici mettait une branche dans le chemin chaud pour un seul
            appelant sur les ~458."""
            score = 0.0
            if distance_map is not None:
                # `float` et NON `int` (corrige le 2026-08-12). La carte n'est plus la distance
                # entiere du moteur : `_objective_terms` y a deja ajoute `w_crowd x surplus` et
                # retranche le rabais de contestation, tous deux FRACTIONNAIRES. Tronquer ici
                # annulait purement et simplement tout poids inferieur a 1 — `w_crowd: 0.5` avec
                # un surplus de 1 rendait 5 + 0,5 -> 5, soit aucune penalite.
                score -= w_obj * float(distance_map[dest[0], dest[1]])
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


def load_doctrine_weights(bot_key: str) -> Tuple[float, float, float, float, float, float]:
    """(w_objectif, w_ennemi, w_tir, w_risque, w_contest, w_crowd) du style `bot_key`.

    Quatre termes et non deux : les six anciens bots n'avaient que la geometrie
    (objectif, ennemi), ce qui rendait impossible d'exprimer « je me place pour tirer » ou
    « je reste hors de portee ». Ces deux-la sont precisement les axes de Standoff et d'Endgame.

    `w_contest` (2026-08-12) est le cinquieme : il dit a quel point le style prefere une zone
    TENUE PAR L'ADVERSAIRE a la zone la plus proche (cf. `_objective_terms`). Il voyage dans le
    MEME tuple que les autres, et ce n'est pas cosmetique : `EndgameBot` et `AttritionBot`
    echangent l'entree entiere selon leur mode (`endgame_push`, `attrition_withdraw`), donc un
    poids charge a part resterait sur la valeur du mode precedent.
    """
    bots = require_key(_weights_config(), "doctrines")
    entry = require_key(bots, bot_key)
    return (float(require_key(entry, "w_objective")), float(require_key(entry, "w_enemy")),
            float(require_key(entry, "w_fire")), float(require_key(entry, "w_risk")),
            float(require_key(entry, "w_contest")), float(require_key(entry, "w_crowd")))


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
        DEPLOYMENT_ACTIONS[0]: 0.10, DEPLOYMENT_ACTIONS[1]: 0.40, DEPLOYMENT_ACTIONS[2]: 0.10,
        DEPLOYMENT_ACTIONS[3]: 0.15, DEPLOYMENT_ACTIONS[4]: 0.15,
        DEPLOYMENT_ACTIONS[5]: 0.05, DEPLOYMENT_ACTIONS[6]: 0.05,
    }

    def target_score(self, attacker, is_ranged: bool, game_state):
        """Il tire sur qui conteste ses zones — le reste ne lui coute pas de points."""
        return _score_contester(attacker, is_ranged)

    def _uses_contester_score(self, unit, game_state) -> bool:
        return True

    def wants_charge(self, attacker, game_state) -> bool:
        return False


class EndgameBot(_DoctrineBot):
    """TEMPO bas : il se preserve, puis prend les zones quand elles comptent.

    Punit l'agent qui marque tot et relache. Avant le tour de bascule il tient ses distances et
    tire ; apres, il joue exactement comme un Racer.

    La bascule utilise `late_game_state` (Bot_refactor.md §4.A.1) : l'ancien predicat
    `_pushing` et `PUSH_LAST_TURNS=3` sont remplaces par la fonction commune. Le comportement
    sur une bataille de 5 tours est inchange : la bascule survient au tour 3 quand le score est
    serre (vp_diff < 15), exactement comme avant — c'est un test.

    Les overrides de vecteur (`endgame` → `desperate_push` → `endgame_push`) et le profil
    de style (gain late_game = 1.0) sont lus dans la config par le socle commun.
    """

    MOVEMENT_BOT_KEY = "endgame"
    PLACEMENT_WEIGHTS = {
        DEPLOYMENT_ACTIONS[0]: 0.05, DEPLOYMENT_ACTIONS[1]: 0.20, DEPLOYMENT_ACTIONS[2]: 0.45,
        DEPLOYMENT_ACTIONS[3]: 0.10, DEPLOYMENT_ACTIONS[4]: 0.10,
        DEPLOYMENT_ACTIONS[5]: 0.05, DEPLOYMENT_ACTIONS[6]: 0.05,
    }

    def _in_push_mode(self, game_state, player: int) -> bool:
        return late_game_state(game_state, player) == "desperate_push"

    def target_score(self, attacker, is_ranged: bool, game_state):
        player = int(require_key(attacker, "player"))
        if self._in_push_mode(game_state, player):
            return _score_contester(attacker, is_ranged)
        return _score_efficiency(attacker, is_ranged)

    def _uses_contester_score(self, unit, game_state) -> bool:
        return self._in_push_mode(game_state, int(require_key(unit, "player")))

    def wants_charge(self, attacker, game_state) -> bool:
        player = int(require_key(attacker, "player"))
        if not self._in_push_mode(game_state, player):
            return False
        return super().wants_charge(attacker, game_state)

    def _pushing(self, game_state) -> bool:
        """Vrai si on est dans la fenetre de poussee finale (`_PUSH_LAST_TURNS` derniers tours).

        Leve si la bataille n'a pas de fin (Endless Duty) : jouer la fin de partie n'a pas de
        sens sans fin de partie — et masquer cette rupture d'invariant produirait un mode « jamais
        en poussee » permanent, sans signal.
        """
        battle_turns = get_effective_turn_limit(game_state)
        if battle_turns is None:
            raise ValueError(
                "Endless Duty: jouer la fin de partie n'a pas de sens sans fin de partie."
            )
        current_turn = int(require_key(game_state, "turn"))
        return battle_turns - current_turn + 1 <= _PUSH_LAST_TURNS


class AlphaStrikeBot(_DoctrineBot):
    """DISTANCE nulle : il cherche le contact au plus tot, sur la piece qui compte.

    Punit l'agent qui expose ses tireurs. Il charge des qu'une cible est declarable — meme si sa
    melee n'est pas son meilleur mode : immobiliser un tireur adverse vaut le tir qu'il perd.
    """

    MOVEMENT_BOT_KEY = "alpha"
    PLACEMENT_WEIGHTS = {
        DEPLOYMENT_ACTIONS[0]: 0.45, DEPLOYMENT_ACTIONS[1]: 0.20, DEPLOYMENT_ACTIONS[2]: 0.05,
        DEPLOYMENT_ACTIONS[3]: 0.10, DEPLOYMENT_ACTIONS[4]: 0.10,
        DEPLOYMENT_ACTIONS[5]: 0.05, DEPLOYMENT_ACTIONS[6]: 0.05,
    }

    #: Part de son tir qu'il accepte de sacrifier pour aller au contact. Charger avec une unite
    #: dont la melee vaut MOINS que le tir est un echange perdant en degats bruts — mais un
    #: tireur adverse immobilise ne tire plus, et c'est la valeur propre de l'alpha strike. En
    #: dessous de ce seuil l'echange n'est plus rattrapable par cet effet.
    MELEE_TRADE_FLOOR = 0.5

    def target_score(self, attacker, is_ranged: bool, game_state):
        return _score_kill_now(attacker, is_ranged)

    def _charge_trade_floor(self, game_state, player: int) -> float:
        """Floor propre a AlphaStrike : MELEE_TRADE_FLOOR * le floor du socle commun.

        A g=0 : floor = 0.5 * 1.0 = 0.5, identique a l'ancien `melee >= ranged * 0.5`.
        """
        return self.MELEE_TRADE_FLOOR * super()._charge_trade_floor(game_state, player)

    def wants_charge(self, attacker, game_state) -> bool:
        """Charge si le contact vaut au moins `_charge_trade_floor` fois son tir.

        ⚠️ VALAIT `True` INCONDITIONNEL, et c'etait perdant des deux cotes — mesure du
        2026-08-11 : dernier du panel en bot-contre-bot (0,292) et sature contre l'agent
        (0,98). Charger avec n'importe quelle unite, y compris un tireur a 36 pouces face a une
        cible qu'il ne peut pas entamer au corps a corps, c'est offrir son escouade ET perdre
        son tir. Le seuil garde l'agressivite du style — il charge encore la ou les autres
        s'abstiennent — sans en faire un suicide systematique.
        """
        if self._preservation_blocks_charge(attacker, game_state):
            return False
        profile = _best_melee_and_ranged(attacker, game_state)
        if profile is None:
            return False
        melee, ranged = profile
        if melee <= 0.0:
            return False  # rien a faire au contact : y aller est une perte seche
        player = int(require_key(attacker, "player"))
        return melee >= ranged * self._charge_trade_floor(game_state, player)


class AttritionBot(_DoctrineBot):
    """VALEUR : il maximise le differentiel de points, et retire ses pieces cheres entamees.

    Punit l'agent qui trade mal. Seul style a jouer le critere de DEPARTAGE
    (`determine_winner_with_method`, « value_tiebreaker »).
    """

    MOVEMENT_BOT_KEY = "attrition"
    PLACEMENT_WEIGHTS = {
        DEPLOYMENT_ACTIONS[0]: 0.10, DEPLOYMENT_ACTIONS[1]: 0.30, DEPLOYMENT_ACTIONS[2]: 0.30,
        DEPLOYMENT_ACTIONS[3]: 0.10, DEPLOYMENT_ACTIONS[4]: 0.10,
        DEPLOYMENT_ACTIONS[5]: 0.05, DEPLOYMENT_ACTIONS[6]: 0.05,
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

    def _is_preserving(self, unit, game_state) -> bool:
        """Etat de preservation d'attrition : identique a _withdrawing.

        Route vers l'override `attrition_withdraw` dans `movement_weights` (via socle commun).
        Coupe egalement la charge.
        """
        return self._withdrawing(unit, game_state)

class DecapitationBot(_DoctrineBot):
    """CONCENTRATION : toutes ses escouades frappent la MEME cible dans le tour.

    Punit l'agent qui etale ses forces. Retirer une escouade entiere retire son OC et ses tirs ;
    l'etaler laisse tout le monde debout et tirer.

    ⚠️ Le focus est une MEMOIRE de tour, pas un score : les bots decident escouade par escouade
    sans se voir les unes les autres, donc aucun critere local ne peut produire une concentration.
    La cible est ELUE a la premiere activation du tour (cf. `_elect`) et gardee tant qu'elle vit.
    Elle porte les DEUX faces de la doctrine : vers qui on tire (`target_score`) et vers qui on
    marche (`movement_enemy_anchors`) — concentrer ses tirs depuis cinq positions eclatees, c'est
    ne concentrer que la moitie de son activation.

    `focus_shared: true` dans le profil (Bot_refactor.md §4.A.2) : le focus inter-escouades est
    conserve EN PLUS de la persistance per-escouade de _persistence_targets (socle commun).
    Les deux coexistent sans conflit : le focus donne +10 000 a la cible commune, la persistance
    la conserve ensuite naturellement (le gap est quasi nul entre deux activations de la meme tour).
    """

    MOVEMENT_BOT_KEY = "decapitation"
    PLACEMENT_WEIGHTS = {
        DEPLOYMENT_ACTIONS[0]: 0.25, DEPLOYMENT_ACTIONS[1]: 0.25, DEPLOYMENT_ACTIONS[2]: 0.20,
        DEPLOYMENT_ACTIONS[3]: 0.10, DEPLOYMENT_ACTIONS[4]: 0.10,
        DEPLOYMENT_ACTIONS[5]: 0.05, DEPLOYMENT_ACTIONS[6]: 0.05,
    }

    def __init__(self, randomness: float = 0.0):
        super().__init__(randomness)
        self._focus_turn: Optional[Tuple[Any, int]] = None
        self._focus_target: Optional[str] = None
        self._focus_confirmed: bool = False

    def _focus(self, game_state, attacker=None) -> Optional[str]:
        """Cible du tour, ELUE a la premiere lecture, oubliee au changement de tour ou a sa mort.

        `require_key` sur `turn` ET sur `episode_number` (T1) : un `.get` sur l'un ou l'autre
        rendait un marqueur CONSTANT qui empechait le changement de cible entre tours ou entre
        episodes — un defaut de doctrine silencieux ne au masquage d'une rupture d'invariant.
        """
        marker = (require_key(game_state, "episode_number"), int(require_key(game_state, "turn")))
        if self._focus_turn != marker:
            self._focus_turn = marker
            self._focus_target = None
            self._focus_confirmed = False
        if self._focus_target is not None and not is_unit_alive(self._focus_target, game_state):
            self._focus_target = None
            self._focus_confirmed = False
        if self._focus_target is None and attacker is not None:
            enemies = _living_enemies_on_table(attacker, game_state)
            self._focus_target = self._elect(attacker, game_state, enemies)
        return self._focus_target

    def _elect(self, unit, game_state, enemies) -> Optional[str]:
        """Elit la cible du tour pour l'escouade qui active la premiere.

        ⚠️ ELECTION, et non plus memorisation du premier tir (2026-08-13). La cible etait
        enregistree depuis `_shoot`/`_fight`, or la phase move PRECEDE le tir dans le tour
        (`GAME_PHASES`) et le changement de tour vient d'effacer celle du tour precedent : le
        deplacement ne lisait donc JAMAIS qu'un focus vide. Les cinq escouades partaient chacune
        vers un ennemi different, puis concentraient leurs tirs depuis des positions eclatees —
        la doctrine s'annulait dans la phase qui la precede.

        Le critere reste celui du tir, `_score_kill_now`, pris au MEILLEUR des deux modes : au
        moment de bouger on ne sait pas encore si l'escouade tirera ou chargera, et une cible elue
        sur la mauvaise table de degats concentrerait tout le monde sur une escouade que personne
        ne peut entamer.

        AUCUN filtre sur les scores, et c'est le contrat de `_score_kill_now` qui le dit : il
        classe TOUTES les cibles, zero degat compris (contrairement a `_score_contester`, qui
        ecarte). Le filtre `is None` qui vivait ici etait donc mort, et avec lui le repli
        `if not scored`. `None` n'est rendu QUE sur une table sans ennemi.
        """
        if not enemies:
            return None
        ranged, melee = _score_kill_now(unit, True), _score_kill_now(unit, False)
        scored: List[Tuple[float, str]] = []
        for enemy in enemies:
            sid = str(enemy["id"])
            entry = require_unit_from_cache(sid, game_state, "_elect")
            # Le MEILLEUR des deux modes, par cible : « inattaquable au tir » n'est pas
            # « inattaquable » — l'escouade peut encore charger.
            scored.append((
                max(ranged(sid, entry, game_state), melee(sid, entry, game_state)), sid
            ))
        # `key=` et non `max(scored)` : a egalite de score, le premier de l'ordre des unites, et
        # surtout pas le plus petit identifiant — l'ordre des unites est le meme pour toutes les
        # escouades du tour, donc l'election reste la meme quelle que soit celle qui active.
        return max(scored, key=lambda pair: pair[0])[1]

    def _enemy_anchors(self, unit, game_state, enemies):
        """Le terme d'ennemi porte sur la CIBLE DU TOUR : c'est la doctrine, pas une geometrie.

        UN SEUL repli, et il est fonctionnel : plus aucun ennemi SUR LA TABLE (tous en reserves
        au tour 1, 20.01, ou tous morts) — `_focus` rend alors `None`, et le terme retombe sur
        toutes les ancres, c'est-a-dire sur rien puisque `enemies` est vide lui aussi.

        ⚠️ Une cible elue est FORCEMENT dans `enemies` : `_elect` n'elit que parmi
        `_living_enemies_on_table`, exactement la liste que `select_movement_destination` passe
        ici, et `_focus` efface celle qui meurt. Une escouade posee ne repasse jamais en
        reserves. Donc une cible absente d'`enemies` n'est PAS une cible « pas encore arrivee » :
        c'est une rupture d'invariant, et elle LEVE (T1). Le test d'appartenance qui vivait ici
        la faisait retomber en silence sur `min(distance)` — une doctrine cassee jouant comme un
        bot ordinaire, sans que rien ne le signale.
        """
        focused = self._focus(game_state, unit)
        if focused is None:
            return super()._enemy_anchors(unit, game_state, enemies)
        entry = require_unit_from_cache(focused, game_state, "_move_focus")
        if not entry_is_on_battlefield(entry):
            # Cible partie hors table (reserves 20.01) : reset et re-election sur les restants.
            self._focus_target = None
            self._focus_confirmed = False
            focused = self._focus(game_state, unit)
            if focused is None:
                return super()._enemy_anchors(unit, game_state, enemies)
            entry = require_unit_from_cache(focused, game_state, "_move_focus")
        return [(int(entry["col"]), int(entry["row"]))]

    def target_score(self, attacker, is_ranged: bool, game_state):
        focused = self._focus(game_state, attacker)
        kill_now = _score_kill_now(attacker, is_ranged)

        def _score(sid: str, entry: Dict[str, Any], game_state) -> float:
            # `kill_now` vaut `(1000 si letal) + degats`, et les PV sont strictement positifs
            # (`_hp_left`) : `base > 0` dit donc exactement « je peux l'entamer », sans qu'il
            # faille construire un second scorer pour poser la meme question. Il n'ecarte
            # jamais, d'ou l'absence de garde `is None` — cf. son contrat.
            base = kill_now(sid, entry, game_state)
            if focused is not None and sid == focused and base > 0.0:
                return base + 10_000.0  # la cible du tour prime, si on peut l'entamer
            return base

        return _score

    def _remember(self, action: int, game_state, active_unit) -> None:
        """Confirme la cible du tour a partir du premier tir reellement effectue.

        L'election au mouvement classe sur les degats esperes sans contrainte de portee : la cible
        elue peut etre hors du masque de l'activer. Le premier slot ouvert tranche et VERROUILLE —
        `_focus_confirmed` empeche les activations suivantes de rerouter la cible.
        """
        if self._focus_confirmed:
            return
        from engine.phase_handlers.shared_utils import get_enemy_slot_mapping
        player = int(require_key(active_unit, "player"))
        mapping = get_enemy_slot_mapping(game_state, player)
        slot_idx = action - mi.SHOOT_SLOT_BASE
        if slot_idx < len(mapping):
            self._focus_target = mapping[slot_idx]
            self._focus_confirmed = True

    def _shoot(self, valid_actions, game_state, active_unit) -> int:
        action = super()._shoot(valid_actions, game_state, active_unit)
        if action in mi.SHOOT_SLOTS:
            self._remember(action, game_state, active_unit)
        return action


class ScorerBot(_DoctrineBot):
    """Il joue pour MARQUER, et ne se bat que pour ca.

    Punit l'agent qui gagne des combats sans regarder les zones — la faute que le panel refondu
    ne savait plus punir. `racer` en est la caricature (il refuse le combat quoi qu'il arrive),
    `alpha`, `attrition` et `decapitation` jouent les pertes, `endgame` attend : aucun ne
    reprenait l'axe de l'ancien `ControlBot`, le SEUL des six d'origine a porter de
    l'information (il tenait l'agent a 0,73 la ou les autres saturaient au-dessus de 0,87).

    Ajoute le 2026-08-12, a la place du holdout a un coup supprime le meme jour : meme creneau,
    1x le cout au lieu de 9,5x, et un axe que la mesure designait comme manquant.

    Doctrine, en une phrase par phase :
      - CIBLE : celle qui conteste, c'est-a-dire la plus proche d'une zone (comme `racer`) ;
      - CHARGE : jamais depuis une zone tenue — la quitter coute des points — et ailleurs
        seulement si la melee est vraiment son meilleur mode ;
      - DEPLACEMENT : vers les zones, en acceptant l'exposition quand elle paie (`w_fire`
        au-dessus de `w_risk`).
    """

    MOVEMENT_BOT_KEY = "scorer"
    PLACEMENT_WEIGHTS = {
        DEPLOYMENT_ACTIONS[0]: 0.15, DEPLOYMENT_ACTIONS[1]: 0.35, DEPLOYMENT_ACTIONS[2]: 0.20,
        DEPLOYMENT_ACTIONS[3]: 0.10, DEPLOYMENT_ACTIONS[4]: 0.10,
        DEPLOYMENT_ACTIONS[5]: 0.05, DEPLOYMENT_ACTIONS[6]: 0.05,
    }

    def target_score(self, attacker, is_ranged: bool, game_state):
        """Il frappe qui conteste ses zones : le reste ne lui coute pas de points."""
        return _score_contester(attacker, is_ranged)

    def _uses_contester_score(self, unit, game_state) -> bool:
        return True

    def wants_charge(self, attacker, game_state) -> bool:
        """Se battre doit RAPPORTER une zone, jamais en coûter une.

        Tenir une zone et charger, c'est la quitter pour un corps a corps qui immobilise :
        l'escouade cesse de marquer pendant que l'adversaire encaisse. Le predicat est celui du
        moteur (`unit_is_within_objective`, empreinte de socle par figurine, 14.02) et non une
        egalite de coordonnees, qui manquerait les escouades a cheval sur une zone.

        Hors zone, la charge redevient un choix ordinaire, tranche par le socle commun sur les
        degats esperes CONTRE LES CIBLES REELLES.
        """
        if unit_is_within_objective(game_state, attacker, objective_hex_sets(game_state)):
            return False
        if self._preservation_blocks_charge(attacker, game_state):
            return False
        return self._melee_beats_ranged(attacker, game_state)


#: Les six styles, par cle de configuration. `tactical` (le holdout) n'est PAS ici : il ne porte
#: pas de doctrine — cf. le doc de chantier §3.3.
DOCTRINE_BOTS = {
    "racer": RacerBot,
    "endgame": EndgameBot,
    "alpha": AlphaStrikeBot,
    "attrition": AttritionBot,
    "decapitation": DecapitationBot,
    "scorer": ScorerBot,
}
