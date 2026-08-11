#!/usr/bin/env python3
"""ai/bot_holdout.py — le holdout d'evaluation : il n'a pas de doctrine, il joue pour gagner.

CE QU'EST UN HOLDOUT, ET POURQUOI L'ANCIEN N'EN ETAIT PAS UN
    L'ancien `TacticalBot` etait le plus FORT du panel, mais fait de la meme matiere que les
    autres : memes helpers, memes scores ponderes. Il mesurait donc la generalisation A
    L'INTERIEUR d'une famille — un agent qui apprend a battre des heuristiques ponderees bat par
    construction une heuristique ponderee plus forte. Un holdout doit differer en NATURE, pas en
    degre.

CE QUE FAIT CELUI-CI
    Il ESSAIE ses coups. Pour chaque action legale : cloner l'etat, jouer le coup, evaluer l'etat
    obtenu, garder le meilleur. Aucune doctrine, aucun style : une fonction de valeur, et la
    recherche du coup qui la maximise. Les six styles de `ai/bot_doctrines.py` sont des
    caricatures qui exagerent un axe ; lui joue la partie.

LA FONCTION DE VALEUR (option C, arbitree le 2026-08-11)
    points marques + zones tenues + differentiel de VALEUR des armees, PONDERE PAR LES TOURS
    RESTANTS. C'est ce dernier facteur qui produit un vrai joueur : au tour 1 il preserve ses
    unites (le differentiel de valeur pese lourd, une zone tenue ne rapportera que dans quatre
    tours) ; au tour 5 il sacrifie une escouade pour une zone decisive (plus aucun tour pour la
    rentabiliser autrement). Les options ecartees : « points marques seulement » en faisait un
    myope, clone du style Racer ; « points + zones » ne lui faisait jamais risquer une unite.

CE QUE COUTE UNE DECISION — mesure du 2026-08-11 (x1, scenario holdout)
    Cloner l'etat coute 68 ms en copie profonde nue, dont 75 % pour une table d'armes IMMUABLE ;
    en reutilisant les cles statiques deja declarees par le rewind PvP (`_GS_STATIC_KEYS`), le
    clone tombe a 9,6 ms. Jouer le coup coute 6,85 ms. Le branchement median est de 5 actions
    (≈ 82 ms par decision, tenable) mais monte a 458 en phase de MOVE (≈ 7,6 s, hors de portee).
    D'ou le pre-tri : en move, seules les `MOVE_SHORTLIST` meilleures destinations d'un score
    geometrique sont reellement essayees (option B, arbitree le 2026-08-11). Le pre-tri n'ecarte
    que des destinations dominees ; il ne choisit pas a la place de la recherche.
"""

import copy
import random
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from engine import macro_intents as mi
from engine.combat_utils import calculate_hex_distance
from engine.game_state import objective_hex_sets
from engine.objective_distance import objective_distance_maps
from engine.phase_handlers.shared_utils import is_unit_alive, require_unit_position
from engine.spatial_relations import enemy_entries_on_battlefield
from services.game_snapshots import _GS_STATIC_KEYS
from shared.data_validation import require_key

from ai.bot_doctrines import _PlacementMemory
from ai.evaluation_bots import DEPLOYMENT_ACTIONS, WAIT_ACTION

#: Destinations reellement essayees en phase de move (cf. le cout mesure en tete de module).
MOVE_SHORTLIST = 12

#: Duree d'une bataille (07 The battle round). Sert a ponderer par les tours RESTANTS.
BATTLE_TURNS = 5


#: Caches que le moteur derive du TERRAIN et pose paresseusement dans `game_state`. Ils sont
#: partages par reference avec l'etat simule, comme les cles statiques.
#:
#: ⚠️ POURQUOI UNE LISTE A PART, et pas un ajout a `_GS_STATIC_KEYS` : celle-la repond a une AUTRE
#: question (« que reattacher depuis l'etat vivant au restore d'un snapshot PvP »), et les deux
#: proprietes ne coincident que par hasard. Ici la question est « qu'est-ce qui est sur a PARTAGER
#: entre l'etat reel et un etat hypothetique divergent » : uniquement ce qui derive du terrain,
#: lequel ne change pas de la partie. Les caches derives de la POSITION DES UNITES
#: (`_charge_*`, `_move_*`, `_best_weapon_cache`, `_unit_los_pair_cache`...) sont exclus a
#: dessein — les partager laisserait la simulation ecrire dans l'etat reel.
#:
#: Sans ce partage, le clone deep-copiait `_objective_hex_zones_cache` hexe par hexe (10 538 hexes
#: sur le plateau de reference), et la copie perdait l'identite que le cache teste pour se valider
#: — donc chaque simulation le RECONSTRUISAIT en plus de l'avoir copie.
_TERRAIN_DERIVED_CACHES = frozenset({
    "_objective_hex_zones_cache",
    "_wall_set_cache",
    "_dense_wall_set_cache",
    "_wall_hexes_tuple_cache",
    "_obscuring_area_sets_cache",
    "_obscuring_hex_to_area_cache",
    "_los_blocking_grids_cache",
    "_hex_los_state_cache",
})

#: Tout ce que la simulation partage plutot que de copier.
_SHARED_BY_SIMULATION = frozenset(_GS_STATIC_KEYS) | _TERRAIN_DERIVED_CACHES


def _clone_state(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Copie de l'etat pour une simulation, cles STATIQUES partagees par reference.

    `_GS_STATIC_KEYS` est la liste que `services/game_snapshots.py` a etablie pour le rewind PvP :
    des cles reellement invariantes pendant une partie (table de degats d'armes, config, murs,
    terrain, objectifs). La reutiliser au lieu d'en ecrire une seconde evite qu'une cle devienne
    mutable d'un cote sans que l'autre l'apprenne — et fait tomber le clone de 68 a 9,6 ms.
    """
    return {
        k: (v if k in _SHARED_BY_SIMULATION else copy.deepcopy(v))
        for k, v in game_state.items()
    }


class LookaheadHoldoutBot(_PlacementMemory):
    """Holdout d'evaluation : il essaie ses coups et garde le meilleur.

    ⚠️ CLE DE REGISTRE — il est enregistre sous `tactical_lookahead` et NON `tactical` tant que
    l'ancien `TacticalBot` sert la campagne de correspondance (etape 7 du chantier). Il prendra
    le nom `tactical` quand l'ancien partira : c'est l'ancien qui a un historique a preserver,
    pas lui. Le renommage changera ses graines d'evaluation — sans consequence, ses seuls
    chiffres d'ici la seront ceux du reglage bot-contre-bot.
    """

    #: Declaration EXPLICITE : ce bot ne peut pas decider sans essayer ses coups.
    #: `BotControlledEnv._attach_engine_if_needed` la lit sur la CLASSE et appelle `attach_engine`.
    NEEDS_ENGINE = True

    #: Pose : ce bot n'a pas de doctrine de deploiement non plus. Poids uniformes sur les cinq
    #: strategies — la mise en place ne se simule pas (l'armee entiere n'est pas encore posee,
    #: donc l'etat evalue ne dirait rien), et un biais serait un style deguise.
    PLACEMENT_WEIGHTS = {slot: 0.20 for slot in DEPLOYMENT_ACTIONS[:5]}

    def __init__(self, randomness: float = 0.0):
        # `randomness` est accepte pour que la construction soit celle de tous les bots
        # (`bot_registry.build_bot`), mais il vaut ZERO par doctrine : un metre etalon ne joue
        # pas aux des. Une valeur non nulle est refusee plutot qu'ignoree en silence.
        if randomness:
            raise ValueError(
                "LookaheadHoldoutBot est deterministe par construction : il definit le metre, et "
                f"un metre bruite ne mesure pas. randomness={randomness} refuse — mettre 0.0 dans "
                "callback_params.bot_eval_randomness."
            )
        super().__init__()
        self.randomness = 0.0
        self._engine = None
        #: Graine des des de SIMULATION, avancee d'une unite par DECISION (pas par candidate) :
        #: toutes les candidates d'une decision sont donc jugees sur le meme tirage, et deux
        #: decisions successives n'utilisent pas le meme. Elle ne touche jamais le hasard de la
        #: partie, restaure a l'identique par `_simulation`.
        self._simulation_draw = 0
    # -- Acces moteur -------------------------------------------------------------------------

    def attach_engine(self, engine) -> None:
        """Recoit le moteur du wrapper (contrat `NEEDS_ENGINE`)."""
        self._engine = engine

    def _require_engine(self):
        if self._engine is None:
            raise RuntimeError(
                "LookaheadHoldoutBot n'a pas recu le moteur : il declare NEEDS_ENGINE, donc "
                "BotControlledEnv doit appeler attach_engine(). Sans moteur il ne peut rien "
                "essayer, et jouer au hasard ferait de lui un metre faux plutot qu'absent."
            )
        return self._engine

    # -- Fonction de valeur -------------------------------------------------------------------

    def _state_value(self, game_state: Dict[str, Any], me: int) -> float:
        """Valeur de l'etat pour le joueur `me`. Plus c'est haut, plus je suis pres de gagner.

        Trois termes, dans l'ordre de ce qui gagne une partie :
          1. les POINTS deja marques (c'est la condition de victoire) ;
          2. les ZONES tenues a cet instant (ce sont les points des tours a venir) ;
          3. le DIFFERENTIEL DE VALEUR des armees (le departage, et la capacite a tenir).

        Les termes 2 et 3 sont ponderes par les tours RESTANTS : une zone tenue vaut ce qu'elle
        rapportera encore, une unite preservee vaut ce qu'elle jouera encore. En fin de partie
        les deux s'effacent devant les points — d'ou le sacrifice pour une zone decisive au
        dernier tour.

        ⚠️ LE CONTROLE EST RECALCULE ICI, IL N'EST PAS LU. `objective_controllers` n'est rafraichi
        par le moteur qu'aux FRONTIERES de phase et de tour : le lire rendait la meme valeur pour
        toutes les destinations d'une phase de mouvement, donc tous les candidats etaient a
        egalite et la baseline « ne pas bouger » l'emportait par `>` strict. Mesure de la review
        du 2026-08-11 : `[-20.0, -20.0, -20.0]` pour trois destinations differentes — le holdout
        ne se deplacait JAMAIS, et le pre-tri comme `MOVE_SHORTLIST` ne servaient a rien.
        Recalculer donne aussi la meme base a tous les candidats : sans ca, celui qui franchit
        une frontiere de phase declenchait le rafraichissement et partait avec un bonus que les
        autres n'avaient pas.
        """
        opponent = 3 - me
        turn = int(require_key(game_state, "turn"))
        turns_left = max(0, BATTLE_TURNS - turn)

        # `victory_points` est indexe par ENTIER (1/2) et le moteur exige les deux joueurs.
        # Aucun `.get` avec defaut : un score absent est une rupture d'invariant, pas un zero.
        victory_points = require_key(game_state, "victory_points")
        my_vp = float(require_key(victory_points, me))
        their_vp = float(require_key(victory_points, opponent))

        control = self._require_engine().state_manager.calculate_objective_control(game_state)
        my_zones = sum(1 for entry in control.values() if entry.get("controller") == me)
        their_zones = sum(1 for entry in control.values() if entry.get("controller") == opponent)

        my_value, their_value = 0.0, 0.0
        for unit in require_key(game_state, "units"):
            if not is_unit_alive(str(unit["id"]), game_state):
                continue
            value = float(require_key(unit, "VALUE"))
            if int(require_key(unit, "player")) == me:
                my_value += value
            else:
                their_value += value

        # 5 VP par palier de controle (`objectives_control`) : une zone tenue un tour de plus
        # vaut de cet ordre, d'ou le facteur 5 sur le terme de zones.
        return (
            (my_vp - their_vp)
            + 5.0 * (my_zones - their_zones) * turns_left
            + 0.10 * (my_value - their_value) * turns_left
        )

    # -- Recherche a un coup ------------------------------------------------------------------

    def _value_after(self, action: int, game_state: Dict[str, Any], me: int) -> float:
        """Valeur de l'etat APRES `action`, jouee sur un clone. L'etat reel n'est pas touche.

        Le moteur est repointe sur le clone le temps du coup, puis rendu a l'etat reel — c'est le
        seul moyen de faire jouer le coup par le CODE DE PRODUCTION plutot que par une seconde
        implementation des regles, qui divergerait.
        """
        with self._simulation() as engine:
            engine.step(action)
            return self._state_value(engine.game_state, me)

    @contextmanager
    def _simulation(self):
        """Prete le moteur pour UN coup simule, et rend tout ce qu'il a mute.

        ⚠️ TROIS FUITES D'ETAT, toutes mesurees par la review du 2026-08-11 sur la version qui ne
        restaurait que `game_state` :

        1. LES COMPTEURS DU MOTEUR. `step_with_mask` incremente `_episode_step_calls`,
           `episode_length_accumulator`, `episode_reward_accumulator` et remplit
           `episode_tactical_data`. Simuler cinq coups par decision multipliait le compteur de pas
           par cinq a treize : le garde anti-runaway tronquait les episodes du holdout en annoncant
           `episode_steps_limit`, et le metre etalon rendait des parties coupees.
        2. LE JOURNAL. Un `step_logger` attache en evaluation recevait un `log_action` par coup
           SIMULE — des actions jamais jouees, ecrites dans le journal qui sert a analyser la
           partie. Il est detache le temps de la simulation.
        3. LE HASARD. Chaque simulation consomme des jets de des. Sans rembobinage, les cinq
           cibles d'un tir etaient comparees sur cinq tirages DIFFERENTS : l'argmax portait sur le
           bruit et non sur la fonction de valeur, et l'evaluation cessait d'etre reproductible a
           graine fixee — pour un bot dont le contrat est d'etre deterministe (`__init__` refuse
           toute randomness).

        La restauration reassigne TOUS les attributs du moteur, et non une liste choisie : une
        liste diverge des que le moteur gagne un compteur. `episode_tactical_data` est en plus
        copie en profondeur, car il est mute EN PLACE (le reassigner ne suffirait pas).
        Verrou : `tests/unit/ai/test_holdout_simulation_isolation.py`, qui compare l'etat complet
        du moteur avant et apres une simulation.
        """
        engine = self._require_engine()
        real_state = engine.game_state
        attributes = dict(vars(engine))
        tactical = copy.deepcopy(getattr(engine, "episode_tactical_data", None))
        logger = getattr(engine, "step_logger", None)
        rng_state = random.getstate()
        np_state = np.random.get_state()
        engine.step_logger = None
        # Des DE SIMULATION, distincts de ceux de la partie. Deux exigences opposees :
        #
        #  - toutes les candidates d'une meme decision doivent affronter le MEME tirage, sinon
        #    l'argmax designe le coup le plus chanceux et non le meilleur ;
        #  - le tirage simule ne doit PAS etre celui que la partie jouera ensuite, sinon le bot
        #    choisit en connaissant le resultat reel des des — un oracle, releve par la review du
        #    2026-08-11 comme consequence directe du simple « sauvegarde/restaure » precedent :
        #    en rendant le RNG a son etat d'avant, le vrai coup rejouait EXACTEMENT la sequence
        #    de la simulation gagnante, donc le bot choisissait l'arme qui tue AVEC CES DES-LA au
        #    lieu de celle qui tue en esperance.
        #
        # `_simulation_draw` fige la graine pour la duree d'une decision (cf. `_best_action` et
        # `select_movement_destination`, qui l'incrementent UNE fois par decision) : equite entre
        # candidates, independance vis-a-vis de la partie.
        random.seed(self._simulation_draw)
        np.random.seed(self._simulation_draw % (2**32))
        try:
            engine.game_state = _clone_state(real_state)
            yield engine
        finally:
            vars(engine).clear()
            vars(engine).update(attributes)
            if tactical is not None:
                engine.episode_tactical_data = tactical
            engine.game_state = real_state
            engine.step_logger = logger
            random.setstate(rng_state)
            np.random.set_state(np_state)

    def _best_action(self, actions: List[int], game_state, me: int) -> Optional[int]:
        """Action de valeur maximale. `None` si aucune n'a pu etre evaluee."""
        self._simulation_draw += 1  # un tirage par DECISION : toutes les candidates l'affrontent
        best_action, best_value = None, -float("inf")
        for action in actions:
            value = self._value_after(action, game_state, me)
            if value > best_value:
                best_value, best_action = value, action
        return best_action

    # -- Interface de bot ---------------------------------------------------------------------

    # La MISE EN PLACE est celle de `_PlacementMemory` : meme automate pour tout le panel. Ce
    # bot ne simule PAS sa pose — l'armee n'est pas encore sur la table, l'etat evalue ne
    # distinguerait pas deux strategies — et ses poids uniformes disent qu'il n'a pas de doctrine
    # de deploiement non plus.

    def select_action_with_state(
        self, valid_actions: List[int], game_state, active_unit: Dict[str, Any]
    ) -> int:
        """Toutes les actions legales sont essayees — le branchement y est de 5 en median."""
        if not valid_actions:
            return WAIT_ACTION
        me = int(require_key(
            require_key(game_state, "units_cache")[str(require_key(active_unit, "id"))], "player"
        ))
        best = self._best_action(valid_actions, game_state, me)
        if best is None:
            raise RuntimeError(
                "LookaheadHoldoutBot n'a evalue aucune action alors que le masque en ouvrait "
                f"{len(valid_actions)} : la simulation n'a rien rendu, il n'y a pas de repli."
            )
        return best

    def select_movement_destination(
        self, unit, valid_destinations: List[Tuple[int, int]], game_state=None
    ) -> Tuple[int, int]:
        """Destination essayee parmi les `MOVE_SHORTLIST` meilleures d'un pre-tri geometrique.

        ⚠️ LE PRE-TRI N'EST PAS LE CHOIX. Il retire des candidates dominees — celles qui
        s'eloignent a la fois des objectifs et des ennemis — pour ramener 458 essais a 12. La
        decision reste celle de la recherche. Sans lui, une seule phase de move couterait ~7,6 s
        (mesure du 2026-08-11), soit plus que la partie entiere.

        ⚠️ Le pre-tri ne SIMULE rien : il ne peut donc pas etre remplace par la fonction de
        valeur, qui exige un clone par candidate. C'est bien la contrainte de cout, et elle est
        assumee : le holdout ne verra pas une destination geometriquement mediocre mais
        tactiquement geniale.
        """
        if game_state is None:
            raise ValueError(
                "LookaheadHoldoutBot.select_movement_destination exige game_state."
            )
        current = require_unit_position(unit, game_state)
        if not valid_destinations:
            return current
        me = require_key(unit, "player")

        objectives = game_state.get("objectives")  # get allowed : scenario sans objectif
        maps = objective_distance_maps(game_state) if objectives else []
        zones = objective_hex_sets(game_state)
        # `enemy_entries_on_battlefield` porte deja « ennemi + vivant + pose » : `units_cache` ne
        # contient que du vivant, et `entries_on_battlefield` ecarte les reserves. L'enumeration
        # maison qui vivait ici refaisait les trois, et devait re-tomber dans le piege de la
        # comparaison de camp (`2` contre `"2"`) que ce helper ferme par son `int()`.
        enemies = [
            (int(entry["col"]), int(entry["row"]))
            for _sid, entry in enemy_entries_on_battlefield(
                require_key(game_state, "units_cache"), int(me)
            )
        ]

        def _geometric(dest) -> float:
            """Pre-tri : proche d'un objectif, et pas indifferent a l'ennemi. Aucune doctrine —
            ce score ne sert qu'a ecarter les candidates dominees, pas a departager les bonnes."""
            score = 0.0
            if maps:
                score -= float(min(int(m[dest[0], dest[1]]) for m in maps))
                if any(dest in zone for zone in zones):
                    score += 3.0
            if enemies:
                score -= 0.25 * min(
                    calculate_hex_distance(dest[0], dest[1], ec, er) for ec, er in enemies
                )
            return score

        shortlist = sorted(valid_destinations, key=_geometric, reverse=True)[:MOVE_SHORTLIST]

        # NE PAS BOUGER est un coup, et il se simule par `ACTION_WAIT` — surtout PAS en cherchant
        # la position courante dans la carte des cellules.
        #
        # ⚠️ C'est ce que faisait la premiere version, et l'option etait silencieusement perdue :
        # `start_pos` est EXCLU du pool BFS (cf. `BotControlledEnv._select_bot_move_action`), donc
        # la position courante n'a jamais de cellule et `cell_map.get(current)` rendait toujours
        # `None`. Le holdout ne pouvait donc jamais tenir sa position, contrairement a ce que sa
        # docstring promettait — il partait forcement quelque part, y compris quand rester valait
        # mieux. Le wrapper traduit le renvoi de la position courante en WAIT : on evalue donc
        # l'action WAIT elle-meme, qui est ce que le moteur jouerait vraiment.
        self._simulation_draw += 1  # un tirage par DECISION (cf. `_simulation`)
        cell_map = self._destination_to_action(game_state, unit)
        best_dest = current
        best_value = self._value_after(mi.ACTION_WAIT, game_state, int(me))
        for dest in shortlist:
            action = cell_map.get(tuple(dest))
            if action is None:
                continue
            value = self._value_after(action, game_state, int(me))
            if value > best_value:
                best_value, best_dest = value, dest
        return best_dest

    def _destination_to_action(self, game_state, unit) -> Dict[Tuple[int, int], int]:
        """destination -> action entiere, lue sur la carte MEMOISEE par le moteur au masque.

        Meme source que le wrapper (`read_squad_move_cell_map`) : recalculer la correspondance
        ici en ferait une seconde, qui designerait d'autres cellules a la premiere divergence.
        """
        from engine.phase_handlers.shared_utils import read_squad_move_cell_map

        # `read_squad_move_cell_map` rend {cellule: (destination, cout)} et LEVE si la carte est
        # absente ou perimee — pas de garde a doubler ici. Les cellules SONT les actions de move
        # (`MOVE_CELL_BASE = 0`), c'est ce que joue deja le wrapper.
        cell_map = read_squad_move_cell_map(game_state, str(require_key(unit, "id")))
        destination_to_action: Dict[Tuple[int, int], int] = {}
        for cell_idx, payload in cell_map.items():
            destination = tuple(payload[0])
            # Plusieurs cellules peuvent mener a la meme destination : on garde la premiere, comme
            # le wrapper (`dest_to_cell`), pour que le holdout joue la cellule qu'il jouerait.
            destination_to_action.setdefault(destination, mi.MOVE_CELL_BASE + int(cell_idx))
        return destination_to_action
