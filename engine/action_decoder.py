#!/usr/bin/env python3
"""
action_decoder.py - Decodes actions and computes masks
"""

import numpy as np
import hashlib
import os
import pickle
import time
from typing import Dict, List, Any, Optional, Set, Tuple
from shared.data_validation import require_key
from engine.debug_trace import CH_DEPLOY_CACHE, channel_enabled, trace
from engine.game_utils import get_unit_by_id
from engine.combat_utils import calculate_hex_distance, get_unit_coordinates
from engine.phase_handlers.shooting_handlers import (
    batch_ground_hex_can_see,
    ground_los_blocking_signature,
)
from engine.phase_handlers.shared_utils import (
    is_unit_alive,
    compute_candidate_footprint,
    build_squad_action_mask,
    get_enemy_slot_mapping,
    get_ally_slot_mapping,
    require_unit_from_cache,
    roll_advance_for_squad,
    # Refonte spatiale du move : action = cellule de la grille egocentrique. Constantes importees,
    # jamais de litteral nu : le plan d'actions a change (WAIT 18 -> 1024, etc.).
    SQUAD_ACTION_CHARGE_SLOT_BASE,
    SQUAD_ACTION_CHARGE_SLOT_COUNT,
    SQUAD_ACTION_FIGHT_NO_TARGET,
    SQUAD_ACTION_FIGHT_SLOT_BASE,
    SQUAD_ACTION_FIGHT_SLOT_COUNT,
    SQUAD_ACTION_MOVE_CELL_BASE,
    SQUAD_ACTION_MOVE_CELL_COUNT,
    SQUAD_ACTION_SHOOT_SLOT_BASE,
    SQUAD_ACTION_SHOOT_SLOT_COUNT,
    SQUAD_ACTION_SIZE,
    SQUAD_ACTION_WAIT,
    build_squad_move_cell_map,
    infer_squad_move_type,
    read_squad_move_cell_map,
    squad_advance_or_fall_back_allowed,
    store_squad_move_cell_map,
)
from engine.macro_intents import (
    ACTIVATE_SLOT_BASE,
    ACTIVATE_SLOTS,
    BASE_ZONE_INTENT,
    CHOICE_BASE,
    DEPLOY_SLOT_BASE,
    DEPLOY_SLOTS,
    DEPLOY_STRATEGY_COUNT,
    TOTAL_ACTION_SIZE,
    MAX_OBJECTIVES,
    OATH_SLOT_BASE,
    OATH_SLOTS,
    decode_agent_decision_action,
    is_agent_decision_action,
    is_zone_intent_action,
    decode_zone_intent_action,
)
from engine.agent_decision import read_pending_agent_decision
# 21.03 « take to the skies » (V11 §0.48 `L6`) : le point de choix s'ouvre AVANT le pool, puisque
# la declaration en change le budget et la traversee. Importe ici, module de la table de phase.
from engine.phase_handlers.movement_handlers import arm_fly_declaration_decision

# Game phases - single source of truth for phase count
GAME_PHASES = ["deployment", "command", "move", "shoot", "charge", "fight"]

#: Clé du `game_state` portant les candidats des slots de déploiement (V11 §0.40 point 3).
#: Un slot OUVERT y porte l'hexe que sa stratégie choisit, le plan de formation validé qui va
#: avec, et les grandeurs qui ont produit ce choix. Le décodeur ET l'observation la lisent :
#: c'est ce qui garantit que l'agent voit EXACTEMENT ce que son action exécutera.
#: Purgée au reset d'épisode (`w40k_core`) — son tampon est l'état de déploiement, qui
#: recommence identique (aucune unité posée) d'un épisode à l'autre.
DEPLOY_SLOT_CANDIDATES_CACHE_KEY = "_deployment_slot_candidates"
#: Jumeau du précédent pour l'ingress move (20.04) — clé DISTINCTE : les deux mises en place
#: coexistent dans un même épisode (déploiement au tour 0, ingress à partir du round 2) et
#: décrivent des aires légales différentes.
INGRESS_SLOT_CANDIDATES_CACHE_KEY = "_ingress_slot_candidates"


def open_deploy_slot_count(num_valid_hexes: int) -> int:
    """Nombre de slots de déploiement OUVERTS pour ce nombre d'hexes valides.

    SOURCE UNIQUE de la question « quels slots de déploiement sont jouables ». Le masque l'appelle
    pour ouvrir ses bits, le constructeur de candidats pour savoir combien de stratégies évaluer,
    et l'observation en hérite par le second. Écrite en trois `min(5, n)` littéraux, cette règle
    aurait pu dériver d'un site à l'autre — et l'observation aurait alors décrit comme jouable
    un slot que le masque ferme (ou l'inverse), exactement le désalignement obs ↔ action D1.

    La borne est `DEPLOY_STRATEGY_COUNT` (stratégies DÉFINIES) et non `DEPLOY_SLOT_COUNT` (slots
    décrits) : les slots réservés au-delà des stratégies existantes ne s'ouvrent jamais. C'est
    cette borne, et elle seule, qui rend le pré-dimensionnement de `N_DEPLOY_SLOTS` sûr — sans
    elle, l'agent pourrait jouer un slot dont `_deployment_slot_order` ne sait rien.
    """
    if num_valid_hexes < 0:
        raise ValueError(f"num_valid_hexes negatif: {num_valid_hexes}")
    return min(DEPLOY_STRATEGY_COUNT, int(num_valid_hexes))

class ActionValidationError(ValueError):
    """Raised when an action fails strict normalization or mask validation."""

    def __init__(self, code: str, message: str, context: Dict[str, Any]):
        self.code = code
        self.context = context
        super().__init__(f"{code}: {message} | context={context}")


class ActionDecoder:
    """Decodes actions and computes valid action masks."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        # Taille de l'action space : DERIVEE du moteur, jamais configuree. C'est le plan d'actions
        # (`macro_intents`, miroir de `shared_utils.SQUAD_ACTION_*`) qui la determine ; la
        # recopier dans les configs creait une 2e source de verite qui ne pouvait qu'avoir tort —
        # une config perimee (l'ancien 41) se manifestait par un `IndexError` opaque au fond du
        # masque. Il n'y a plus rien a synchroniser, donc plus rien a verifier.
        # Les autres consommateurs derivaient deja la taille de `len(action_mask)`
        # (`env_wrappers`, `pve_controller`, `w40k_core`) : ce site etait le dernier a la lire
        # depuis la config.
        self.total_action_size = TOTAL_ACTION_SIZE
        # Clé : (déployeur, hexes de référence, signature des grilles de blocage). La signature
        # (`shooting_handlers.ground_los_blocking_signature`) porte les murs ET les areas
        # obscurantes — sans elles, deux terrains aux mêmes murs partageaient ce cache et le
        # fichier disque.
        self._deployment_potential_los_cache: Dict[
            tuple[int, tuple[tuple[int, int], ...], tuple],
            Dict[tuple[int, int], int],
        ] = {}
        self._wall_hexes_cache: tuple[frozenset, int] | None = None
        self._deployment_pool_cache: Dict[int, Tuple[set, List[Tuple[int, int]], np.ndarray, np.ndarray, np.ndarray]] = {}
        self._deployment_cache_counts: Dict[str, int] = self.empty_deployment_cache_counts()
        self._deployment_scoring_hexes_cache: Dict[int, List[tuple[int, int]]] = {}

    #: Clé du cache de SCORING du déploiement, dans le `game_state` (expositions LoS par hexe,
    #: alliés par colonne, snapshot des unités posées). Il vit dans l'état de partie et non sur
    #: l'instance, donc `reset_episode_caches` ne l'atteint pas : sa purge est dans le bloc de
    #: purges d'épisode de `w40k_core`, avec les caches d'observation qui en DÉPENDENT.
    DEPLOYMENT_SCORING_CACHE_KEY = "_deployment_scoring_cache"

    #: Issues possibles d'une consultation du cache de scoring, comptées par épisode.
    #:
    #: POURQUOI UN COMPTEUR ET PAS UNE TRACE (V11 §0.46 point 3, axe A). Ces quatre issues
    #: n'étaient visibles que sous `debug_mode`, donc JAMAIS sur un run réel — alors qu'elles
    #: mesurent un COÛT : un `full_build` reconstruit toutes les expositions LoS de la zone,
    #: un `incremental` ne touche que le delta d'une pose. Le rapport des deux est exactement
    #: la famille de défauts §0.22 (`MOVE_POOL_BUILD` = 95,6 % du training), qui ne lève rien
    #: et ne fait échouer aucun test : elle consomme. Compté toujours, publié toujours.
    #:
    #: `full_build_incremental_failed` est le signal à surveiller : l'incrémental a été TENTÉ et
    #: a rendu la main, donc le coût du delta a été payé EN PLUS de la reconstruction complète.
    #:
    #: Les deux sous-familles sont DÉCLARÉES, pas déduites : le consommateur (`metrics_tracker`)
    #: sommait au départ les rebuilds par soustraction (`total − incremental`), ce qui aurait
    #: classé en reconstruction toute 5ᵉ issue qui n'en serait pas une — sur une courbe publiée
    #: que personne ne re-dérive.
    INCREMENTAL_CACHE_OUTCOMES = ("incremental",)
    FULL_BUILD_CACHE_OUTCOMES = (
        "full_build_cold",
        "full_build_incremental_failed",
    )
    DEPLOYMENT_CACHE_OUTCOMES = INCREMENTAL_CACHE_OUTCOMES + FULL_BUILD_CACHE_OUTCOMES

    @classmethod
    def empty_deployment_cache_counts(cls) -> Dict[str, int]:
        """Compteurs d'issues du cache de scoring, remis à zéro. SOURCE UNIQUE de leur forme."""
        return {outcome: 0 for outcome in cls.DEPLOYMENT_CACHE_OUTCOMES}

    def _record_deployment_cache_outcome(self, outcome: str) -> None:
        """Compte une consultation du cache de scoring. Une issue non déclarée lève (`KeyError`).

        Attribut d'INSTANCE et non clé du `game_state` : le seul appelant du cache est interne
        au décodeur, et le décodeur a déjà son hook d'épisode (`reset_episode_caches`). Faire
        transiter un compteur par l'état de partie contaminerait le contrat du `game_state`
        avec une préoccupation d'instrumentation — toute doublure de test devrait porter la clé
        pour un chemin qui n'a rien à voir avec elle.
        """
        self._deployment_cache_counts[outcome] += 1

    def deployment_cache_counts(self) -> Dict[str, int]:
        """Copie des compteurs de l'épisode en cours (le moteur la fige à la terminaison)."""
        return dict(self._deployment_cache_counts)

    def reset_episode_caches(self) -> None:
        """Invalidate per-episode caches. Call on every env.reset()."""
        self._deployment_pool_cache = {}
        self._wall_hexes_cache = None
        # Le sur-ensemble de scoring dérive du pool ET des murs, tous deux invalidés ici : il
        # doit l'être AVEC eux, sinon il survivrait à un changement de terrain.
        self._deployment_scoring_hexes_cache = {}
        # Remis à zéro AVEC les autres caches d'épisode : un compteur qui survit à un `reset`
        # cumulerait d'un épisode à l'autre et rendrait le taux de rebuild ininterprétable —
        # sans jamais lever (§0.42).
        self._deployment_cache_counts = self.empty_deployment_cache_counts()

    #: Version du MODÈLE de ligne de vue utilisé pour les expositions de déploiement. Elle entre
    #: dans la clé du cache disque : sans elle, un run relirait des fichiers produits par le
    #: modèle précédent et le changement de modèle serait sans effet — le pire résultat possible,
    #: puisqu'il serait silencieux. À incrémenter à CHAQUE changement du modèle de LoS.
    #:
    #: v2 (V11 §0.64) : `compute_unit_los`, la règle du moteur (obscuring 13.10, plancher-occulteur
    #: 3D), au lieu de `batch_has_los_from_source` (grille de murs 2D), qui en divergeait sur 607
    #: hexes sur 16 104.
    DEPLOYMENT_LOS_MODEL_VERSION = 2

    def deployment_los(
        self, game_state: Dict[str, Any], from_hex: tuple[int, int], to_hexes: np.ndarray
    ) -> np.ndarray:
        """Ligne de vue d'un HEXE vers N HEXES pour le scoring de déploiement — LA RÈGLE DU MOTEUR.

        Passe par `shooting_handlers.batch_ground_hex_can_see`, jumeau VECTORISÉ de
        `compute_unit_los` sur les paires hexe→hexe au sol : même visibilité que l'éligibilité de
        tir, la validation de cible et la récompense (obscuring 13.10 compris). L'égalité des
        deux chemins est verrouillée hexe par hexe par
        `tests/unit/engine/test_deployment_los_vectorized_equivalence.py`.

        Le point d'entrée reste unique et public pour que les deux canaux d'exposition (réelle et
        potentielle) ne puissent plus diverger : c'est leur divergence, invisible tant que le
        chemin incrémental ne tournait pas, qui a coûté 607 valeurs fausses (V11 §0.64).

        BATCH ET NON PAR PAIRE, et ce n'est pas qu'une question de vitesse (V11 §0.64 suite) :
        par paire, la règle du moteur coûtait 10 µs × 146 781 paires = la MOITIÉ de la phase de
        déploiement. Les 16 104 lignes d'une même source se tracent d'un coup (×18 à ×70 mesuré).
        L'ancien chemin passait de plus par `combat_utils.has_line_of_sight`, dont le
        `hex_los_cache` ne servait RIEN ici — mesuré 146 776 consultations pour 146 781 calculs,
        soit zéro réutilisation, chaque paire n'étant posée qu'une fois — mais que chaque
        déplacement d'unité devait ensuite reparcourir pour l'invalider.
        """
        return batch_ground_hex_can_see(game_state, from_hex, to_hexes)

    def _get_deployment_potential_los_cache_file_path(self, topology_key: tuple) -> str:
        """Chemin de cache disque des expositions potentielles, pour une topologie donnée.

        Prend la clé MÉMOIRE telle quelle et n'y ajoute que la version du modèle. Les deux clés
        décrivaient les mêmes éléments en deux listes de paramètres à garder synchronisées — et
        `terrain_signature` est précisément le champ que la 1ʳᵉ rédaction avait oublié d'un côté.
        Il n'y a plus qu'un objet à faire entrer dans une clé pour qu'il entre dans les deux.
        """
        cache_payload = (self.DEPLOYMENT_LOS_MODEL_VERSION, *topology_key)
        cache_digest = hashlib.sha256(repr(cache_payload).encode("utf-8")).hexdigest()
        project_root = os.path.dirname(os.path.dirname(__file__))
        cache_dir = os.path.join(project_root, ".cache", "deployment_potential_los")
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, f"{cache_digest}.pkl")

    def _load_deployment_potential_los_disk_cache(
        self, cache_path: str
    ) -> Dict[tuple[int, int], int]:
        """Load exact deployment potential LoS cache from shared disk cache."""
        with open(cache_path, "rb") as f:
            loaded = pickle.load(f)
        if not isinstance(loaded, dict):
            raise TypeError(
                f"Deployment potential LoS disk cache must be dict, got {type(loaded).__name__}"
            )
        normalized: Dict[tuple[int, int], int] = {}
        for raw_key, raw_value in loaded.items():
            if not isinstance(raw_key, tuple) or len(raw_key) != 2:
                raise TypeError(f"Invalid deployment potential LoS cache key: {raw_key!r}")
            if not isinstance(raw_value, int) or isinstance(raw_value, bool):
                raise TypeError(
                    f"Invalid deployment potential LoS cache value type: {type(raw_value).__name__}"
                )
            normalized[(int(raw_key[0]), int(raw_key[1]))] = int(raw_value)
        return normalized

    def _save_deployment_potential_los_disk_cache(
        self,
        cache_path: str,
        potential_los_cache_for_topology: Dict[tuple[int, int], int],
    ) -> None:
        """Atomically persist exact deployment potential LoS cache for shared reuse."""
        tmp_path = f"{cache_path}.tmp.{os.getpid()}"
        with open(tmp_path, "wb") as f:
            pickle.dump(potential_los_cache_for_topology, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp_path, cache_path)
    
    # ============================================================================
    # ACTION MASKING
    # ============================================================================
    
    # ── PIERRE TOMBALE — masque et décodeur de l'ANCIEN espace d'actions (2026-07-29) ──────
    # Ont vécu ici, et sont morts ensemble :
    #   `convert_gym_action`            décodeur de l'espace 0-15, en dur (4-8 = tir, 9 = charge,
    #                                   10 = fight, 11 = wait) alors que l'espace réel fait 1107
    #   `_get_valid_actions_for_phase`  sa table de plages par phase
    #   `get_action_mask`               wrapper de `get_action_mask_and_eligible_units`
    #   `get_action_mask_for_unit`      variante par unité, sans aucun appelant
    #   `get_action_mask_and_eligible_units` + `_build_mask_for_units`  le masque 0-15 lui-même
    #
    # POURQUOI ils étaient morts : la production est passée au pipeline squad
    # (`get_squad_action_mask_and_eligible_units` + `convert_squad_action`) sans que l'ancien
    # chemin soit retiré. Aucun appelant de production ne subsistait ; seuls ~25 tests le
    # maintenaient vert. Le dernier appelant réel était un outil d'ÉVALUATION
    # (`scripts/roster_matchup_stats.py`), à qui ce masque périmé servait un espace d'actions
    # que le modèle ne parlait plus — un faux muet, pas une erreur.
    #
    # RÈGLE : dès qu'il existe DEUX constructeurs de masque pour un même agent, l'un des deux est
    # déjà mort ou le deviendra sans bruit — ils ne divergent pas bruyamment, ils divergent en
    # silence (même longueur de masque, donc rien ne lève). Le verrou anti-récidive est la parité
    # masque↔décodeur de `tests/unit/engine/test_agent_interface_contract.py` : tout entier
    # ouvert par le masque DOIT être décodable ; le rejet d'un entier fermé est verrouillé une
    # couche plus haut, dans `validate_action_against_mask`.
    # ─────────────────────────────────────────────────────────────────────────────────────────

    def _agent_decision_mask(self, decision: Dict[str, Any]) -> np.ndarray:
        """Masque d'une `pending_agent_decision` : ses `CHOICE_i`, et rien d'autre.

        UN seul constructeur pour les deux sites qui rendent ce masque — la décision déjà en
        attente à l'entrée, et celle que l'armement de la déclaration de vol vient de poser. Deux
        copies auraient pu diverger sans que rien ne lève (même longueur de masque).
        """
        mask = np.zeros(self.total_action_size, dtype=bool)
        for option_index in range(len(require_key(decision, "options"))):
            mask[CHOICE_BASE + option_index] = True
        return mask

    def get_squad_action_mask_and_eligible_units(
        self, game_state: Dict[str, Any]
    ) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
        """Build 41-element squad mask + eligible units for the squad pipeline.

        Deployment : actions 4-8 (deploy hexes, logique legacy préservée).
        Command    : wait (18) + zone intents (26-40).
        Move/Shoot/Charge/Fight : build_squad_action_mask (0-25) pour le squad actif.
        Advance roll : rollé ici une seule fois par activation, stocké dans game_state.
        """
        mask = np.zeros(self.total_action_size, dtype=bool)

        # Décision agent en attente (V11 §9.3 P2) : elle est EXCLUSIVE. Tant qu'elle n'est pas
        # jouée, le moteur est arrêté sur un point de choix — exactement comme le PvP l'est sur
        # un `waiting_for_player` — et aucune action de phase n'a de sens. Le pool d'unités
        # éligibles est vide : l'activation en cours reprendra APRÈS la décision.
        pending_decision = read_pending_agent_decision(game_state)
        if pending_decision is not None:
            return self._agent_decision_mask(pending_decision), []

        # DÉSIGNATION D'OATH OF MOMENT (chantier 03) — même exclusivité que ci-dessus, pour la
        # même raison : le moteur est arrêté au début de la phase de commandement sur un choix
        # de joueur. Elle est en revanche NON OPTIONNELLE (« select one unit from your opponent's
        # army ») : aucun slot « aucune cible », aucun WAIT, aucun zone intent tant qu'elle n'est
        # pas jouée. Fermer la sortie est le seul moyen d'imposer une règle qui n'offre pas de
        # choix de ne pas choisir.
        oath_selection_slots = self.oath_selection_slots(game_state)
        if oath_selection_slots is not None:
            if not oath_selection_slots:
                raise ValueError(
                    "Oath of Moment : designation en attente mais aucun slot ouvert — le masque "
                    "serait tout-faux, donc injouable. `command_step_command_abilities` ne pose "
                    "la designation que s'il existe une unite ennemie vivante."
                )
            for action_int in oath_selection_slots:
                mask[action_int] = True
            return mask, []

        eligible_units = self._get_eligible_units_for_current_phase(game_state)
        current_phase = game_state["phase"]

        if current_phase == "deployment":
            if eligible_units:
                current_deployer = self._get_current_deployer(game_state)
                active_unit = eligible_units[0]
                valid_hexes = self._get_valid_deployment_hexes(
                    game_state, current_deployer, str(require_key(active_unit, "id"))
                )
                num_hexes = len(valid_hexes)
                if num_hexes == 0:
                    raise ValueError(
                        f"Deployment deadlock: no valid hex for player {current_deployer}, "
                        f"unit {active_unit.get('id')}"
                    )
                for i in range(open_deploy_slot_count(num_hexes)):
                    mask[DEPLOY_SLOT_BASE + i] = True
                # 20.01 — « you can select one or more friendly units to place in strategic
                # reserves » : la mise en réserve est une DÉCISION DE JOUEUR, prise à la place
                # du déploiement de cette unité. Elle emprunte `SQUAD_ACTION_WAIT`, id inutilisé
                # en phase de déploiement (les slots 4-8 y portent les stratégies de pose) :
                # aucune dimension d'action n'est ajoutée. Le slot est FERMÉ dès que l'unité ne
                # tiendrait plus sous le plafond de 50 % — l'agent ne peut pas produire une
                # liste illégale, exactement comme il ne peut pas poser hors zone.
                from engine.phase_handlers.deployment_handlers import (
                    unit_can_be_placed_in_strategic_reserves,
                )

                if unit_can_be_placed_in_strategic_reserves(
                    game_state, str(require_key(active_unit, "id"))
                ):
                    mask[SQUAD_ACTION_WAIT] = True
            return mask, eligible_units

        if current_phase == "command":
            # SQUAD_ACTION_WAIT, jamais un litteral : il valait 18, il vaut 1024 depuis la refonte
            # spatiale. Ecrit en dur, ce site masquait une CELLULE DE MOVE en phase command.
            mask[SQUAD_ACTION_WAIT] = True
            free_steps = game_state["zone_intent_free_steps_remaining"]
            if free_steps > 0:
                objectives = game_state["objectives"]
                num_zones = min(len(objectives), MAX_OBJECTIVES)
                for zone_idx in range(num_zones):
                    for intent_val in range(3):
                        action_idx = BASE_ZONE_INTENT + zone_idx * 3 + intent_val
                        if action_idx < self.total_action_size:
                            mask[action_idx] = True
            return mask, eligible_units

        if not eligible_units:
            return mask, eligible_units

        squad_id = str(eligible_units[0]["id"])
        units_cache = require_key(game_state, "units_cache")
        cache_entry = units_cache.get(squad_id)
        if cache_entry is None:
            raise KeyError(f"Squad {squad_id} missing from units_cache")
        our_player = int(require_key(cache_entry, "player"))
        enemy_slot_ids = get_enemy_slot_mapping(game_state, our_player)

        from engine.phase_handlers.shared_utils import unit_is_in_strategic_reserves

        squad_in_reserves = current_phase == "move" and unit_is_in_strategic_reserves(
            game_state, squad_id
        )

        # ═══ ORDRE DES QUATRE SORTIES — il porte deux RÈGLES, pas un style de rédaction ═══
        #
        # 1. CHOIX D'ACTIVATION (`L2`) : personne n'est encore SÉLECTIONNÉ, donc rien de ce qui
        #    dépend de la sélection ne doit être fait — ni le jet d'Advance (09.03), ni la
        #    déclaration de vol (21.03). Les deux se feront pour l'escouade réellement désignée.
        # 2. INGRESS (20.04) : une escouade en réserves fait une MISE EN PLACE, pas un des quatre
        #    mouvements que 21.03 énumère. Elle sort AVANT la déclaration de vol.
        # 3. DÉCLARATION DE VOL (`L6`) : l'escouade est désignée ET sur le plateau, la question a
        #    un sens. Elle change le budget (-2") et la traversée, donc elle précède la carte.
        # 4. Carte de cellules + masque d'activation ordinaire.
        #
        # ⚠️ Déplacer ces sorties les unes par rapport aux autres est un défaut de RÈGLE, pas de
        # lisibilité. Les deux ordres qui comptent sont verrouillés par
        # `test_activation_choice_contract.py`.

        # ─── 1. CHOIX DE L'ESCOUADE À ACTIVER (V11 §0.48 élément `L2` / §9 P3-3) ───
        # Même exclusivité que les branches `pending_agent_decision` et Oath plus haut, et pour la
        # même raison : le moteur est arrêté sur un choix de joueur qui PRÉCÈDE l'activation.
        # Aucune sortie « ne pas choisir » : il faut bien activer quelqu'un, et le slot 0 est
        # toujours ouvert (cf. `activation_selection_slots`), donc le masque n'est jamais tout-faux.
        activation_slots = self.activation_selection_slots(game_state, eligible_units)
        if activation_slots is not None:
            # L'observation rendue AVEC ce masque contient la grille égocentrique de l'ancre, que
            # `build_squad_grid` remplit en relisant la carte mémoïsée ici — `read_squad_move_cell_map`
            # LÈVE si elle manque, sans repli. Elle est donc construite, mais au budget NORMAL :
            # 09.03 fait le jet d'Advance quand l'unité est SÉLECTIONNÉE, or personne ne l'est
            # encore. Le tirer ici le montrerait à l'agent — il alimente les cellules Advance de la
            # grille — avant qu'il ne choisisse, et pour la seule ancre du pool.
            # Cette carte est TRANSITOIRE : le step suivant la reconstruit pour l'escouade
            # désignée, avec son jet et sa déclaration de vol.
            if current_phase == "move" and not squad_in_reserves:
                store_squad_move_cell_map(
                    game_state, squad_id, build_squad_move_cell_map(game_state, squad_id, None)
                )
            for action_int in activation_slots:
                mask[action_int] = True
            return mask, eligible_units

        # ─── 2. INGRESS MOVE (20.04) ───
        # L'escouade active est en réserves : elle n'a aucune cellule de move (elle n'est pas sur
        # le plateau), elle a des candidats de MISE EN PLACE. Le masque ouvre donc les mêmes slots
        # 4-8 que le déploiement, dont c'est le jumeau, plus WAIT pour RENONCER (rester en réserves
        # ce tour-ci est un choix légal — jusqu'à la fin du 3e round, où 20.04 la détruit). Les
        # deux familles ne peuvent pas se confondre : une escouade en réserves n'a pas de cellule
        # jouable, une escouade posée n'a pas de candidat d'ingress.
        #
        # ⚠️ AVANT la déclaration de vol, et c'est une RÈGLE : 21.03 ouvre « take to the skies »
        # pour un mouvement Normal / Advance / Fall Back / Charge, pas pour une mise en place.
        # Sortir après ferait déclarer le vol à une escouade HORS TABLE, et la déclaration s'écrit
        # pour la PHASE (`declared_key`/`resolved_key`) : elle lui coûterait -2" sur un mouvement
        # qu'elle ne fait pas. `arm_fly_declaration_decision` documente cette précondition et ne la
        # revérifie pas — c'est ICI qu'elle est tenue.
        if squad_in_reserves:
            for action_int in self.ingress_slot_candidates(game_state, squad_id):
                mask[action_int] = True
            mask[SQUAD_ACTION_WAIT] = True
            return mask, eligible_units

        # ─── 3. TAKE TO THE SKIES (21.03, V11 §0.48 élément `L6`) ───
        # POINT DE CHOIX, posé ICI et pas ailleurs : la déclaration change le budget (-2") ET la
        # traversée, donc le POOL que les lignes suivantes construisent. La poser après serait la
        # poser trop tard ; la trancher par une constante moteur (ce que faisait §0.49 point 5)
        # revenait à décider à la place de l'agent. Le siège humain n'y passe jamais (il a le
        # toggle de l'UI, cf. `fly_declaration_decision_is_due`).
        #
        # ⚠️ APRÈS le choix d'activation : `squad_id` est alors l'escouade que l'agent a DÉSIGNÉE,
        # et non la tête du pool. Poser la déclaration avant l'aurait engagée pour la tête, et
        # `resolved_key` interdit de la reposer — l'agent aurait activé une AUTRE escouade en
        # laissant la première avec un vol déclaré pour un mouvement qu'elle ne fait pas.
        #
        # Le moteur REND LA MAIN comme le fait 08.04 pour le Waaagh! : masque exclusivement
        # `CHOICE_*`, pool vide, l'activation reprendra au step suivant avec la déclaration écrite.
        armed_decision = arm_fly_declaration_decision(game_state, squad_id)
        if armed_decision is not None:
            return self._agent_decision_mask(armed_decision), []

        # ─── 4. Carte de cellules + masque d'activation ordinaire ───
        advance_roll: Optional[int] = None
        move_cell_map = None
        if current_phase == "move":
            squad_advance_rolls = game_state.setdefault("_squad_advance_rolls", {})
            if squad_id not in squad_advance_rolls:
                squad_advance_rolls[squad_id] = roll_advance_for_squad(squad_id, game_state)
            advance_roll = squad_advance_rolls[squad_id]

            # Refonte spatiale : la carte cellule -> (destination, cout) est construite UNE fois
            # ici, sert a masquer, puis est memoisee pour que `convert_squad_action` execute
            # exactement la cellule masquee. Sans cette memoisation il faudrait un 2e BFS par step
            # et la carte du decodage pourrait differer de celle du masque.
            # `advance_roll` n'est pas transmis si Advance/Fall Back sont fermes : le pool retombe
            # alors au budget normal, donc aucune cellule Advance. La regle vient de
            # `squad_advance_or_fall_back_allowed`, la MEME que celle du masque : la reecrire ici
            # ferait deriver les deux (pool au budget Advance que le masque refuserait, ou l'inverse).
            move_cell_map = build_squad_move_cell_map(
                game_state,
                squad_id,
                advance_roll if squad_advance_or_fall_back_allowed(game_state, squad_id) else None,
            )
            store_squad_move_cell_map(game_state, squad_id, move_cell_map)

        squad_mask = build_squad_action_mask(
            game_state, squad_id, enemy_slot_ids, advance_roll, move_cell_map=move_cell_map
        )
        for i, v in enumerate(squad_mask):
            if v:
                mask[i] = True

        return mask, eligible_units

    def oath_selection_slots(
        self, game_state: Dict[str, Any]
    ) -> Optional[Dict[int, str]]:
        """`{action_int -> id d'escouade ennemie}` des `OATH_SLOTS` ouverts, ou None si aucune
        désignation d'Oath n'est en attente.

        SOURCE UNIQUE partagée par le masque, le décodage et la politique du bot — c'est ce qui
        rend tout slot ouvert exécutable, et interdit qu'un slot masqué désigne une escouade
        différente de celle que le décodeur en tirerait.

        INVARIANT D1. Le slot *i* est indexé sur `get_enemy_slot_mapping`, EXACTEMENT le même
        mapping que les slots de tir, de charge et de mêlée — donc la même ligne *i* du tenseur
        ennemi de l'observation. Les désolidariser ferait pointer l'action `OATH_SLOT_i` et la
        ligne *i* observée sur deux escouades différentes sans que rien ne lève : l'agent
        désignerait une cible en croyant en désigner une autre.

        Un slot dont l'escouade est morte ou absente du mapping reste FERMÉ : `set_oath_target`
        refuserait la désignation, et un masque qui l'ouvrirait produirait une action invalide.
        """
        pending_player = game_state.get("pending_oath_selection")  # get allowed : None = aucune
        if pending_player is None:
            return None
        from engine.phase_handlers.command_handlers import oath_selectable_enemy_ids
        from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

        player_int = int(pending_player)
        selectable = set(oath_selectable_enemy_ids(game_state, player_int))
        enemy_slot_ids = get_enemy_slot_mapping(game_state, player_int)
        return self._slots_from_mapping(enemy_slot_ids, OATH_SLOT_BASE, selectable)

    @staticmethod
    def _slots_from_mapping(
        slot_ids: List[Optional[str]], base: int, allowed_ids: Set[str]
    ) -> Dict[int, str]:
        """`{base + i -> escouade}` pour les lignes *i* du mapping qui portent une escouade
        autorisée. MATÉRIALISATION UNIQUE de l'invariant D1 : slot *i* = ligne *i* observée.

        Partagée par l'Oath (mapping ennemi) et l'activation (mapping allié) parce que les deux
        familles pointent le MÊME contrat. Deux boucles jumelles laisseraient une correction sur
        l'une (normalisation d'id, traitement d'un slot mort) ne pas atteindre l'autre.
        """
        return {
            base + slot_index: str(squad_id)
            for slot_index, squad_id in enumerate(slot_ids)
            if squad_id is not None and str(squad_id) in allowed_ids
        }

    @staticmethod
    def _resolve_slot_target(
        action_int: int, slots: Optional[Dict[int, str]], family: str, pending: str
    ) -> str:
        """Escouade désignée par un slot pointé, ou LÈVE si le masque n'aurait pas dû l'ouvrir.

        Jumeau exact pour l'Oath et l'activation : dans les deux cas la cible est RELUE dans la
        source unique du masque, jamais recalculée au décodage — c'est ce qui garantit que le slot
        joué désigne l'escouade que le masque avait ouverte. Les deux `raise` sont ici et pas
        recopiés par famille : un libellé qui dérive rend la panne plus dure à reconnaître.

        `family` nomme le bloc d'ids (`OATH_SLOT`), `pending` ce qui manque en amont
        (« designation d'Oath ») : les deux sont ce qui rend le message localisable, donc ils
        restent portés par l'appelant plutôt que dérivés l'un de l'autre.
        """
        if slots is None:
            raise ValueError(
                f"convert_squad_action: action {family} {action_int} sans {pending} en attente "
                "— le masque n'aurait pas du l'autoriser"
            )
        if action_int not in slots:
            raise ValueError(
                f"convert_squad_action: slot {family} {action_int} FERME "
                f"(ouverts : {sorted(slots)}) — action hors masque"
            )
        return slots[action_int]

    #: Phases qui activent les escouades une par une, donc les seules ou « qui joue maintenant ? »
    #: est une question. Le DEPLOIEMENT en est structurellement exclu : ses candidats ne sont pas
    #: encore sur le champ de bataille, donc ils n'ont pas de ligne d'observation alliee
    #: (`deployed_friendly_squad_ids`) — un slot d'activation y designerait une ligne vide, c'est
    #: a dire un choix a l'aveugle. L'ordre de pose reste celui du pool ; c'est une AUTRE decision.
    ACTIVATION_CHOICE_PHASES = ("move", "shoot", "charge", "fight")

    #: Escouade que l'agent a designee pour l'activation en cours. Cle unique de l'etat de L2.
    ACTIVATION_CHOSEN_KEY = "activation_chosen_squad"

    def activation_selection_slots(
        self,
        game_state: Dict[str, Any],
        eligible_units: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[int, str]]:
        """`{action_int -> id d'escouade}` des `ACTIVATE_SLOTS` ouverts, ou None si aucun choix
        d'activation n'est en attente.

        SOURCE UNIQUE partagée par le masque et le décodage — c'est ce qui rend tout slot ouvert
        exécutable, et interdit qu'un slot masqué désigne une escouade différente de celle que le
        décodeur en tirerait.

        INVARIANT D1, CÔTÉ ALLIÉ. Le slot *i* est indexé sur `get_ally_slot_mapping`, donc sur la
        ligne *i* du tenseur ALLIÉ de l'observation. L'ancre du mapping est `eligible_units[0]`,
        exactement l'escouade dont `W40KEngine._build_observation_and_mask` fait la ligne 0 : c'est
        pour cela que cette branche du masque rend le pool `eligible_units` et NON `[]` comme les
        `CHOICE_i` et les slots d'Oath. Rendre `[]` ici décrocherait l'observation du mapping.

        QUAND LE CHOIX EST POSÉ. Une seule fois par activation, et seulement s'il y a un VRAI
        choix — c'est-à-dire au moins DEUX SLOTS OUVERTS, pas au moins deux escouades éligibles.
        Les deux comptes diffèrent : une escouade en réserves stratégiques est éligible en phase
        de mouvement (ingress 20.04) mais n'a pas de ligne alliée, donc pas de slot. Un pool de
        deux dont l'une est en réserves n'offrait qu'une action légale — un step gym brûlé pour
        aucune information, et l'escouade en réserves inadressable (mesuré : tour 2, move, P1).

        PORTÉE DU MARQUEUR — (tour, phase, joueur, escouade), les quatre.
        Le marqueur est honoré tant que l'escouade désignée est encore dans le pool ET que
        l'activation est la MÊME. La seconde moitié n'est pas une précaution : les pools sont
        PAR PHASE, donc une escouade qui a fini de bouger reste dans le pool de tir. Sans la
        portée, son marqueur de la phase move survivait à la phase de tir et y supprimait le
        choix — mesuré : 9 des 20 premières activations (tour, phase, joueur) à pool ≥ 2 se
        faisaient sans qu'aucun choix ne soit proposé, forcées sur l'escouade précédente. Le tour
        et le joueur closent le même trou d'un cran plus haut (même phase, tour suivant ; même
        phase, joueur suivant).

        Un marqueur périmé n'est PAS effacé, il est ignoré : « désignée pour cette activation-ci »
        cesse simplement d'avoir un sens. Seul `reset()` le purge, parce qu'un état d'épisode qui
        survit à l'épisode est un autre problème — le tour repart à 1 et la clé redeviendrait
        valide par coïncidence.
        """
        phase = require_key(game_state, "phase")
        if phase not in self.ACTIVATION_CHOICE_PHASES:
            return None
        if eligible_units is None:
            eligible_units = self._get_eligible_units_for_current_phase(game_state)
        if not eligible_units:
            return None
        eligible_ids = {str(require_key(u, "id")) for u in eligible_units}
        chosen = self.current_activation_choice(game_state)
        if chosen is not None and chosen in eligible_ids:
            return None  # l'activation désignée est en cours

        anchor_id = str(require_key(eligible_units[0], "id"))
        anchor_entry = require_unit_from_cache(anchor_id, game_state, "activation_selection_slots")
        our_player = int(require_key(anchor_entry, "player"))
        ally_slot_ids = get_ally_slot_mapping(game_state, our_player, anchor_id)
        slots = self._slots_from_mapping(ally_slot_ids, ACTIVATE_SLOT_BASE, eligible_ids)
        if ACTIVATE_SLOT_BASE not in slots:
            raise ValueError(
                f"activation_selection_slots: l'ancre {anchor_id} n'a pas de slot alors qu'elle "
                "est la tête du pool — le mapping allié a décroché du pool. Le slot 0 porte "
                "l'ancre par construction (`get_ally_slot_mapping` la met en ligne 0)."
            )
        if len(slots) < 2:
            # Un seul slot ouvert : le choix est déjà fait, poser la décision coûterait un step
            # pour aucune information. Cf. la docstring — ce n'est PAS `len(eligible_units) < 2`.
            return None
        return slots

    def activation_choice_scope(self, game_state: Dict[str, Any]) -> Tuple[int, str, int]:
        """(tour, phase, joueur) — l'activation à laquelle un marqueur de choix appartient.

        Recopiée nulle part : le marqueur la STOCKE et `current_activation_choice` la compare.
        """
        return (
            int(require_key(game_state, "turn")),
            str(require_key(game_state, "phase")),
            int(require_key(game_state, "current_player")),
        )

    def current_activation_choice(self, game_state: Dict[str, Any]) -> Optional[str]:
        """Escouade désignée POUR L'ACTIVATION COURANTE, ou None si le marqueur est absent/périmé.

        SOURCE UNIQUE de la lecture du marqueur — `activation_selection_slots` et
        `_get_eligible_units_for_current_phase` passent toutes deux par ici, sans quoi l'une
        pourrait juger valide un marqueur que l'autre juge périmé, et le masque désignerait une
        escouade que le pool ne remonterait pas.
        """
        marker = game_state.get(self.ACTIVATION_CHOSEN_KEY)  # get allowed : None = aucun choix
        if marker is None:
            return None
        if tuple(require_key(marker, "scope")) != self.activation_choice_scope(game_state):
            return None  # marqueur d'une AUTRE activation : périmé, jamais réutilisé
        return str(require_key(marker, "squad_id"))

    def get_deployment_active_unit(self, game_state: Dict[str, Any]) -> Dict[str, Any]:
        """L'unité sur laquelle porte la décision de déploiement — SOURCE UNIQUE obs ↔ masque.

        `get_squad_action_mask_and_eligible_units` ouvre les slots 4-8 pour `eligible_units[0]`,
        c'est-à-dire la 1re unité vivante de `deployable_units[current_deployer]`. L'observation
        DOIT décrire cette unité-là : elle lisait auparavant la 1re clé de `units_cache` (tous
        joueurs confondus, déployés compris), donc l'agent décrivait A et posait B — défaut
        §0.40 point 1. Ce point d'entrée public expose la MÊME dérivation, sans reconstruire les
        hexes valides (le poste coûteux du masque).

        Lève si le pool est vide : en phase de déploiement c'est un état incohérent — le masque
        y serait tout-faux, donc injouable. Rendre une obs nulle masquerait cette incohérence.
        """
        phase = require_key(game_state, "phase")
        if phase != "deployment":
            raise ValueError(
                f"get_deployment_active_unit appelé en phase '{phase}' — ce point d'entrée ne "
                "décrit que la décision de déploiement."
            )
        eligible = self._get_eligible_units_for_current_phase(game_state)
        if not eligible:
            raise ValueError(
                "get_deployment_active_unit: aucune unité déployable vivante pour le joueur "
                f"{self._get_current_deployer(game_state)} — état incohérent "
                "(le masque de déploiement serait vide, donc injouable)."
            )
        return eligible[0]

    def _get_eligible_units_for_current_phase(self, game_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Pool d'activation de la phase, l'escouade DÉSIGNÉE PAR L'AGENT en tête.

        UNIQUE point où le choix de L2 (V11 §0.48) prend effet. Tout le moteur active
        `eligible_units[0]` — le masque, le décodeur, l'observation, les bots d'évaluation : c'est
        exactement ce qui rendait l'ordre d'activation inaccessible à l'agent, et c'est donc ici,
        et nulle part ailleurs, qu'il faut le rendre. Remplacer les ~9 sites `eligible_units[0]`
        un par un les aurait fait diverger au premier oublié.

        Le marqueur est ignoré dès que l'escouade n'est plus dans le pool : cf.
        `activation_selection_slots`, « pourquoi aucun site de purge ».
        """
        eligible = self._raw_eligible_units_for_current_phase(game_state)
        if require_key(game_state, "phase") not in self.ACTIVATION_CHOICE_PHASES:
            return eligible
        chosen_id = self.current_activation_choice(game_state)
        if chosen_id is None:
            return eligible
        for index, unit in enumerate(eligible):
            if str(require_key(unit, "id")) == chosen_id:
                # Rotation EN PLACE : `_raw_...` construit une liste neuve à chaque appel, jamais
                # partagée avec le pool de `game_state` (ce sont des ids qui y vivent).
                eligible.insert(0, eligible.pop(index))
                return eligible
        return eligible

    def _raw_eligible_units_for_current_phase(self, game_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get eligible units for current phase using handler's authoritative pools.

        CRITICAL: Filter out dead units when reading from pools.
        Units can die between pool construction and pool usage, so we must filter here.

        ⚠️ ORDRE BRUT DU POOL — n'appeler que depuis `_get_eligible_units_for_current_phase`, qui
        y applique le choix d'activation de l'agent. Un appelant qui court-circuite ce passage
        annulerait L2 en silence : il activerait la tête du pool, pas l'escouade désignée.
        """
        current_phase = game_state["phase"]

        if current_phase == "deployment":
            deployment_state = require_key(game_state, "deployment_state")
            current_deployer = self._get_current_deployer(game_state)
            deployable_units = require_key(deployment_state, "deployable_units")
            deployable_list = deployable_units.get(current_deployer, deployable_units.get(str(current_deployer)))
            if deployable_list is None:
                raise KeyError(f"deployable_units missing player {current_deployer}")
            eligible = []
            for uid in deployable_list:
                unit = get_unit_by_id(str(uid), game_state)
                if unit and is_unit_alive(str(unit["id"]), game_state):
                    eligible.append(unit)
            return eligible
        if current_phase == "command":
            return []  # Empty pool for now, ready for future
        elif current_phase == "move":
            # AI_TURN.md COMPLIANCE: Use handler's authoritative activation pool
            if "move_activation_pool" not in game_state:
                raise KeyError("game_state missing required 'move_activation_pool' field")
            pool_unit_ids = game_state["move_activation_pool"]
            # CRITICAL: Filter out dead units (units can die between pool build and use)
            eligible = []
            for uid in pool_unit_ids:
                unit = get_unit_by_id(uid, game_state)
                if unit and is_unit_alive(str(unit["id"]), game_state):
                    eligible.append(unit)
            return eligible
        elif current_phase == "shoot":
            # AI_TURN.md COMPLIANCE: Use handler's authoritative activation pool
            # STEP 2: UNIT_ACTIVABLE_CHECK - Pick one unit from shoot_activation_pool
            # No filtering by SHOOT_LEFT or can_advance - pool is built once at phase start
            # Units are removed ONLY via end_activation() with Arg4 = SHOOTING
            if "shoot_activation_pool" not in game_state:
                raise KeyError("game_state missing required 'shoot_activation_pool' field")
            pool_unit_ids = game_state["shoot_activation_pool"]
            current_player = require_key(game_state, "current_player")
            try:
                current_player_int = int(current_player)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid current_player value: {current_player}") from exc
            # PRINCIPLE: "Le Pool DOIT gérer les morts" - Pool should never contain dead units
            # If a unit dies after pool build, _remove_dead_unit_from_pools should have removed it
            # Defense in depth: filter dead units here as safety check only
            # CRITICAL: Pool contains string IDs (normalized at creation in shooting_build_activation_pool)
            eligible = []
            pool_unit_ids_str = [str(uid) for uid in pool_unit_ids]
            for uid in pool_unit_ids:
                # CRITICAL: Normalize uid to string for get_unit_by_id (which normalizes both sides)
                uid_str = str(uid)
                unit = get_unit_by_id(uid_str, game_state)
                if unit and is_unit_alive(str(unit["id"]), game_state):
                    cache_entry = require_key(game_state, "units_cache").get(uid_str)
                    if cache_entry is None:
                        raise KeyError(f"Unit {uid_str} missing from units_cache")
                    unit_player = require_key(cache_entry, "player")
                    try:
                        unit_player_int = int(unit_player)
                    except (TypeError, ValueError) as exc:
                        raise ValueError(f"Invalid player value in units_cache for unit {uid_str}: {unit_player}") from exc
                    if unit_player_int == current_player_int:
                        # AI_TURN.md: All units in pool are eligible - no SHOOT_LEFT filtering
                        eligible.append(unit)
            active_shooting_unit = game_state.get("active_shooting_unit")
            if active_shooting_unit is not None:
                active_unit_id = str(active_shooting_unit)
                if active_unit_id not in pool_unit_ids_str:
                    raise ValueError(
                        f"active_shooting_unit {active_unit_id} is not in shoot_activation_pool={pool_unit_ids_str}"
                    )
                active_unit = get_unit_by_id(active_unit_id, game_state)
                if active_unit is None:
                    raise ValueError(f"active_shooting_unit {active_unit_id} not found in game_state units")
                if not is_unit_alive(active_unit_id, game_state):
                    raise ValueError(f"active_shooting_unit {active_unit_id} is dead but still active")
                active_cache_entry = require_key(game_state, "units_cache").get(active_unit_id)
                if active_cache_entry is None:
                    raise KeyError(f"Active shooting unit {active_unit_id} missing from units_cache")
                active_player = require_key(active_cache_entry, "player")
                try:
                    active_player_int = int(active_player)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Invalid player value in units_cache for active unit {active_unit_id}: {active_player}"
                    ) from exc
                if active_player_int != current_player_int:
                    raise ValueError(
                        f"active_shooting_unit {active_unit_id} belongs to player {active_player_int}, "
                        f"current_player is {current_player_int}"
                    )
                return [active_unit]
            return eligible
        elif current_phase == "charge":
            # AI_TURN.md COMPLIANCE: Use handler's authoritative activation pool
            if "charge_activation_pool" not in game_state:
                return []  # Phase not initialized yet
            pool_unit_ids = game_state["charge_activation_pool"]
            # CRITICAL: Filter out dead units (units can die between pool build and use)
            eligible = []
            for uid in pool_unit_ids:
                unit = get_unit_by_id(uid, game_state)
                if unit and is_unit_alive(str(unit["id"]), game_state):
                    eligible.append(unit)
            return eligible
        elif current_phase == "fight":
            # V11 : éligibilité dérivée de la machine de sélection (non-mutante).
            from engine.phase_handlers.fight_handlers import fight_v11_current_pool
            pool_unit_ids = fight_v11_current_pool(game_state)
            # CRITICAL: Filter out dead units (units can die between pool build and use)
            eligible = []
            for uid in pool_unit_ids:
                unit = get_unit_by_id(uid, game_state)
                if unit and is_unit_alive(str(unit["id"]), game_state):
                    eligible.append(unit)
            return eligible
        else:
            return []
    
    # ============================================================================
    # ACTION CONVERSION
    # ============================================================================

    def normalize_action_input(
        self,
        raw_action: Any,
        phase: str,
        source: str,
        action_space_size: int,
    ) -> int:
        """Normalize action to int with strict type and range checks."""
        context: Dict[str, Any] = {
            "phase": phase,
            "source": source,
            "raw_action_repr": repr(raw_action),
            "raw_action_type": type(raw_action).__name__,
        }

        if isinstance(raw_action, bool):
            raise ActionValidationError("invalid_type", "bool action is not allowed", context)

        if isinstance(raw_action, np.ndarray):
            if raw_action.size != 1:
                raise ActionValidationError(
                    "invalid_shape",
                    f"numpy action must be scalar-like, got size={raw_action.size}",
                    context,
                )
            raw_action = raw_action.item()
            context["normalized_from"] = "ndarray"
            context["raw_action_type"] = type(raw_action).__name__

        if isinstance(raw_action, np.generic):
            raw_action = raw_action.item()
            context["normalized_from"] = "numpy_scalar"
            context["raw_action_type"] = type(raw_action).__name__

        if not isinstance(raw_action, int):
            raise ActionValidationError(
                "invalid_type",
                f"action must be int-compatible, got {type(raw_action).__name__}",
                context,
            )

        action_int = int(raw_action)
        if action_int < 0 or action_int >= action_space_size:
            context["normalized_action"] = action_int
            context["action_space_size"] = action_space_size
            raise ActionValidationError(
                "out_of_range",
                f"action {action_int} outside [0, {action_space_size - 1}]",
                context,
            )
        return action_int

    def validate_action_against_mask(
        self,
        action_int: int,
        action_mask: np.ndarray,
        phase: str,
        source: str,
        unit_id: Optional[Any] = None,
    ) -> None:
        """Validate normalized action against action mask."""
        if action_mask.dtype != bool:
            raise TypeError(f"action_mask must be bool dtype, got {action_mask.dtype}")
        if action_int >= len(action_mask):
            raise ActionValidationError(
                "out_of_range",
                f"action {action_int} outside mask length {len(action_mask)}",
                {"phase": phase, "source": source, "unit_id": unit_id},
            )
        if not bool(action_mask[action_int]):
            valid_actions = [i for i, is_valid in enumerate(action_mask) if bool(is_valid)]
            raise ActionValidationError(
                "masked_out",
                f"action {action_int} is masked out",
                {
                    "phase": phase,
                    "source": source,
                    "unit_id": unit_id,
                    "action": action_int,
                    "valid_actions": valid_actions,
                },
            )
    
    def convert_squad_action(
        self,
        action_int: int,
        game_state: Dict[str, Any],
        eligible_units: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Convertit un action int (0-40) en dict sémantique pour le pipeline squad.

        eligible_units : pool pré-calculé (évite recalcul si déjà disponible depuis step).
        Raise sur toute incohérence — aucune valeur par défaut silencieuse.
        """
        current_phase = game_state["phase"]

        # Décision agent (CHOICE_i) : elle prime sur la phase — le moteur est arrêté sur un point
        # de choix, pas sur une action de phase. Le masque n'expose qu'elles (cf. mask ci-dessus).
        if is_agent_decision_action(action_int):
            pending_decision = read_pending_agent_decision(game_state)
            if pending_decision is None:
                raise ValueError(
                    f"convert_squad_action: action CHOICE {action_int} sans decision en attente "
                    "— le masque n'aurait pas du l'autoriser"
                )
            option_index = decode_agent_decision_action(action_int)
            options = require_key(pending_decision, "options")
            if option_index >= len(options):
                raise ValueError(
                    f"convert_squad_action: candidat {option_index} inexistant "
                    f"({len(options)} candidats) — le masque n'aurait pas du l'autoriser"
                )
            return {"action": "agent_decision", "option_index": option_index}

        # Désignation d'Oath of Moment : prime sur la phase pour la MÊME raison que les CHOICE.
        # La cible est relue dans la source unique du masque, jamais recalculée ici — c'est ce
        # qui garantit que le slot joué désigne l'escouade que le masque avait ouverte.
        if action_int in OATH_SLOTS:
            # Cible résolue AVANT de lire `pending_oath_selection` : sans désignation en attente
            # celui-ci vaut None, et l'ordre inverse rendrait un TypeError opaque au lieu du
            # ValueError « le masque n'aurait pas du l'autoriser ».
            oath_target = self._resolve_slot_target(
                action_int,
                self.oath_selection_slots(game_state),
                "OATH_SLOT",
                "designation d'Oath",
            )
            return {
                "action": "select_oath_target",
                "player": int(require_key(game_state, "pending_oath_selection")),
                "unitId": oath_target,
            }

        # Choix de l'escouade à activer : prime sur la phase pour la MÊME raison que les CHOICE
        # et Oath — le moteur est arrêté sur un choix de joueur qui précède l'activation. La
        # cible est relue dans la source unique du masque, jamais recalculée ici : c'est ce qui
        # garantit que le slot joué désigne l'escouade que le masque avait ouverte.
        if action_int in ACTIVATE_SLOTS:
            return {
                "action": "select_activation",
                "unitId": self._resolve_slot_target(
                    action_int,
                    self.activation_selection_slots(game_state, eligible_units),
                    "ACTIVATE_SLOT",
                    "choix d'activation",
                ),
            }

        # Zone intents (26-40) : command uniquement
        if is_zone_intent_action(action_int):
            if current_phase != "command":
                raise ValueError(
                    f"convert_squad_action: zone_intent action {action_int} "
                    f"interdit en phase '{current_phase}'"
                )
            zone_idx, intent_value = decode_zone_intent_action(action_int)
            return {"action": "zone_intent", "zone_idx": zone_idx, "intent_value": intent_value}

        # Deployment : actions 4-8 → deploy_unit (logique existante préservée)
        if current_phase == "deployment":
            if eligible_units is None:
                eligible_units = self._get_eligible_units_for_current_phase(game_state)
            if not eligible_units:
                raise ValueError(
                    "convert_squad_action: aucune unité eligible en phase deployment"
                )
            selected_unit_id = eligible_units[0]["id"]
            # 20.01 — mise en réserves au lieu du déploiement (cf. masque).
            if action_int == SQUAD_ACTION_WAIT:
                return {"action": "deploy_strategic_reserves", "unitId": selected_unit_id}
            if action_int not in DEPLOY_SLOTS:
                raise ValueError(
                    f"convert_squad_action: action {action_int} invalide en phase deployment"
                )
            # Slot RESERVE (au-dela des strategies definies) : le masque ne l'ouvre jamais
            # (`open_deploy_slot_count`), donc l'agent ne peut pas l'atteindre. S'il arrive ici,
            # c'est un appel hors masque — l'erreur doit le dire, pas inventer une strategie.
            if action_int - DEPLOY_SLOT_BASE >= DEPLOY_STRATEGY_COUNT:
                raise ValueError(
                    f"convert_squad_action: slot de deploiement {action_int} RESERVE "
                    f"({DEPLOY_STRATEGY_COUNT} strategies definies, ids "
                    f"{DEPLOY_SLOT_BASE}..{DEPLOY_SLOT_BASE + DEPLOY_STRATEGY_COUNT - 1}). "
                    f"Le masque ne l'ouvre jamais : cet appel contourne le masque."
                )
            current_deployer = self._get_current_deployer(game_state)
            valid_hexes = self._get_valid_deployment_hexes(
                game_state, current_deployer, str(selected_unit_id)
            )
            if not valid_hexes:
                raise ValueError(
                    f"convert_squad_action: aucun hex de deployment pour unité {selected_unit_id}"
                )
            dest_col, dest_row = self._select_deployment_hex_for_action(
                action_int=action_int,
                unit_id=selected_unit_id,
                game_state=game_state,
                current_deployer=current_deployer,
                valid_hexes=valid_hexes,
            )
            return {
                "action": "deploy_unit",
                "unitId": selected_unit_id,
                "destCol": dest_col,
                "destRow": dest_row,
            }

        # En phase command, WAIT = passer sans unité sélectionnée (constante, pas un littéral).
        if current_phase == "command" and action_int == SQUAD_ACTION_WAIT:
            return {"action": "command_wait"}

        # Actions squad micro (0..SQUAD_ACTION_SIZE-1)
        if eligible_units is None:
            eligible_units = self._get_eligible_units_for_current_phase(game_state)
        if not eligible_units:
            raise ValueError(
                f"convert_squad_action: aucune unité eligible en phase '{current_phase}' "
                f"pour action {action_int}"
            )
        squad_id = str(eligible_units[0]["id"])

        # INGRESS MOVE (20.04) — jumeau du décodage de déploiement : le slot désigne une
        # stratégie, `ingress_slot_candidates` en donne l'ancre ET le plan déjà validé (source
        # UNIQUE partagée avec le masque, donc tout slot ouvert est exécutable).
        from engine.phase_handlers.shared_utils import unit_is_in_strategic_reserves

        if current_phase == "move" and unit_is_in_strategic_reserves(game_state, squad_id):
            if action_int == SQUAD_ACTION_WAIT:
                # RENONCER à arriver ce tour-ci : fin d'activation ordinaire (`squad_wait`),
                # l'unité reste en réserves. Aucune sémantique propre n'est nécessaire — c'est
                # exactement « cette escouade ne fait rien de sa phase de mouvement ».
                return {"action": "squad_wait", "squad_id": squad_id}
            if action_int not in list(DEPLOY_SLOTS):
                raise ValueError(
                    f"convert_squad_action: action {action_int} invalide pour une escouade en "
                    f"réserves stratégiques (slots d'ingress {list(DEPLOY_SLOTS)} ou WAIT)"
                )
            candidates = self.ingress_slot_candidates(game_state, squad_id)
            if action_int not in candidates:
                raise ValueError(
                    f"convert_squad_action: slot d'ingress {action_int} FERMÉ pour l'escouade "
                    f"{squad_id} (ouverts : {sorted(candidates)}) — action hors masque"
                )
            candidate = candidates[action_int]
            return {
                "action": "ingress_move",
                "unitId": squad_id,
                "destCol": int(candidate["hex"][0]),
                "destRow": int(candidate["hex"][1]),
                "plan": candidate["plan"],
            }

        if SQUAD_ACTION_MOVE_CELL_BASE <= action_int < (
            SQUAD_ACTION_MOVE_CELL_BASE + SQUAD_ACTION_MOVE_CELL_COUNT
        ):
            # Refonte spatiale (§6.2) : l'action designe une CELLULE de la grille egocentrique.
            # La destination vient du POOL BFS (jamais construite a la main : sauter a
            # « ancre + budget x direction » traverserait les murs, cf. §4.2), et le type de move
            # est DEDUIT de son cout geodesique — jamais d'une dimension d'action.
            cell_map = read_squad_move_cell_map(game_state, squad_id)
            cell_idx = action_int - SQUAD_ACTION_MOVE_CELL_BASE
            if cell_idx not in cell_map:
                raise ValueError(
                    f"convert_squad_action: cellule {cell_idx} injouable pour squad {squad_id} "
                    f"— action hors masque (le masque n'autorise que les cellules du pool)"
                )
            (dest_col, dest_row), geodesic_cost = cell_map[cell_idx]

            move_type = infer_squad_move_type(game_state, squad_id, geodesic_cost)
            semantic: Dict[str, Any] = {
                "action": {
                    "normal": "squad_normal_move",
                    "advance": "squad_advance",
                    "fall_back": "squad_fall_back",
                }[move_type],
                "squad_id": squad_id,
                "destCol": int(dest_col),
                "destRow": int(dest_row),
            }
            if move_type == "advance":
                # Jet pre-tire au masque (§10.4) : c'est celui qui a servi a construire le pool,
                # donc le seul coherent avec la cellule choisie. Absent = contrat rompu -> erreur.
                advance_roll = game_state.get("_squad_advance_rolls", {}).get(squad_id)  # get allowed
                if advance_roll is None:
                    raise ValueError(
                        f"convert_squad_action: advance_roll manquant pour squad {squad_id} "
                        "— get_squad_action_mask_and_eligible_units doit être appelé avant"
                    )
                semantic["advance_roll"] = advance_roll
            return semantic

        if action_int == SQUAD_ACTION_WAIT:
            return {"action": "squad_wait", "squad_id": squad_id}

        if SQUAD_ACTION_SHOOT_SLOT_BASE <= action_int < (
            SQUAD_ACTION_SHOOT_SLOT_BASE + SQUAD_ACTION_SHOOT_SLOT_COUNT
        ):
            return {
                "action": "squad_shoot",
                "target_slot": action_int - SQUAD_ACTION_SHOOT_SLOT_BASE,
                "squad_id": squad_id,
            }

        if SQUAD_ACTION_CHARGE_SLOT_BASE <= action_int < (
            SQUAD_ACTION_CHARGE_SLOT_BASE + SQUAD_ACTION_CHARGE_SLOT_COUNT
        ):
            # V11 §9 P3-2 : la cible de charge vient de l'ACTION. `target_slot` indexe le mapping
            # `get_enemy_slot_mapping` — le meme que le masque et que la ligne du tenseur ennemi.
            # La resolution slot -> escouade est faite par le moteur (`squad_charge`), qui verifie
            # l'eligibilite 11.02 : la traduire ici en dupliquerait la regle (patron P3-1).
            return {
                "action": "squad_charge",
                "squad_id": squad_id,
                "target_slot": action_int - SQUAD_ACTION_CHARGE_SLOT_BASE,
            }

        if SQUAD_ACTION_FIGHT_SLOT_BASE <= action_int < (
            SQUAD_ACTION_FIGHT_SLOT_BASE + SQUAD_ACTION_FIGHT_SLOT_COUNT
        ):
            # V11 §9 P3-1 : la cible de melee vient de l'ACTION. `target_slot` indexe le mapping
            # `get_enemy_slot_mapping` — le meme que le masque et que la ligne du tenseur ennemi.
            # La resolution slot -> escouade est faite par le moteur (`squad_fight`), qui verifie
            # l'appartenance au pool 12.05 : la traduire ici en dupliquerait la regle.
            return {
                "action": "squad_fight",
                "squad_id": squad_id,
                "target_slot": action_int - SQUAD_ACTION_FIGHT_SLOT_BASE,
            }

        if action_int == SQUAD_ACTION_FIGHT_NO_TARGET:
            # Combat a vide (12.04/12.06) : aucune cible eligible. `target_slot` absent — le
            # moteur exige alors un pool 12.05 VIDE (parite masque/commit).
            return {"action": "squad_fight", "squad_id": squad_id}

        raise ValueError(
            f"convert_squad_action: action {action_int} non gérée en phase '{current_phase}'"
        )

    def _get_current_deployer(self, game_state: Dict[str, Any]) -> int:
        """Return current deployment player with strict validation."""
        deployment_state = require_key(game_state, "deployment_state")
        current_deployer = require_key(deployment_state, "current_deployer")
        try:
            return int(current_deployer)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid deployment current_deployer: {current_deployer}") from exc

    def _wall_hex_set(self, game_state: Dict[str, Any]) -> frozenset:
        """Murs normalisés, mémoïsés sur leur NOMBRE (le terrain ne bouge pas en cours d'épisode)."""
        raw_wall_hexes = require_key(game_state, "wall_hexes")
        n_walls = len(raw_wall_hexes)
        if self._wall_hexes_cache is not None and self._wall_hexes_cache[1] == n_walls:
            return self._wall_hexes_cache[0]
        wall_hexes_mut = set()
        for raw_hex in raw_wall_hexes:
            if isinstance(raw_hex, (list, tuple)) and len(raw_hex) == 2:
                wall_hexes_mut.add((int(raw_hex[0]), int(raw_hex[1])))
            elif isinstance(raw_hex, dict):
                wall_hexes_mut.add(
                    (int(require_key(raw_hex, "col")), int(require_key(raw_hex, "row")))
                )
            else:
                raise TypeError(f"Invalid wall hex format: {raw_hex}")
        wall_hexes = frozenset(wall_hexes_mut)
        self._wall_hexes_cache = (wall_hexes, n_walls)
        return wall_hexes

    def _deployment_pool_entry(self, game_state: Dict[str, Any], current_deployer: int):
        """Pool du joueur, normalisé et mémoïsé : `(set, liste, np, grille, masque_pair)`."""
        if current_deployer in self._deployment_pool_cache:
            return self._deployment_pool_cache[current_deployer]

        deployment_pools = require_key(game_state, "deployment_pools")
        pool = deployment_pools.get(current_deployer, deployment_pools.get(str(current_deployer)))
        if pool is None:
            raise KeyError(f"deployment_pools missing player {current_deployer}")
        board_cols = int(require_key(game_state, "board_cols"))
        board_rows = int(require_key(game_state, "board_rows"))

        pool_set = set()
        normalized_pool_list: List[tuple[int, int]] = []
        for raw_hex in pool:
            if isinstance(raw_hex, (list, tuple)) and len(raw_hex) == 2:
                normalized = (int(raw_hex[0]), int(raw_hex[1]))
            elif isinstance(raw_hex, dict):
                normalized = (
                    int(require_key(raw_hex, "col")),
                    int(require_key(raw_hex, "row")),
                )
            else:
                raise TypeError(f"Invalid deployment hex format: {raw_hex}")
            normalized_pool_list.append(normalized)
            pool_set.add(normalized)
        pool_np = np.array(normalized_pool_list, dtype=np.int32)
        pool_grid = np.zeros((board_cols + 10, board_rows + 10), dtype=bool)
        pool_grid[pool_np[:, 0], pool_np[:, 1]] = True
        even_mask_np = pool_np[:, 0] % 2 == 0
        entry = (pool_set, normalized_pool_list, pool_np, pool_grid, even_mask_np)
        self._deployment_pool_cache[current_deployer] = entry
        return entry

    def deployment_scoring_hexes(
        self, game_state: Dict[str, Any], current_deployer: int
    ) -> List[tuple[int, int]]:
        """SUR-ENSEMBLE stable sur lequel le cache de scoring est calculé : pool moins murs.

        POURQUOI UN SUR-ENSEMBLE (V11 §0.46, suite). Le cache était calculé sur les hexes
        VALIDES de l'unité courante — un ensemble qui change à chaque unité (le socle change la
        clairance) ET à chaque pose (l'hexe occupé sort du jeu). Sa condition de validité, « même
        jeu d'hexes valides ? », ne pouvait donc jamais passer : mesuré `incremental=0` sur 10
        consultations, soit 100 % de reconstruction, 23-48 ms pièce.

        Or les grandeurs mises en cache — exposition LoS d'un hexe, alliés par colonne — sont des
        propriétés de l'HEXE, pas de l'unité qu'on y pose : mesuré 0 écart sur les intersections
        entre les cinq unités d'un roster. Les calculer une fois sur pool-moins-murs, qui ne
        dépend ni du socle ni des poses, et filtrer à la LECTURE (le consommateur itère déjà sur
        `valid_hexes`) est donc neutre pour l'observation §0.40 — donc sans ré-entraînement.

        L'inclusion `valid_hexes ⊆ deployment_scoring_hexes` est l'invariant qui rend ce
        filtrage sûr ; elle est verrouillée par test.
        """
        cached = self._deployment_scoring_hexes_cache.get(int(current_deployer))
        if cached is not None:
            return cached
        _pool_set, normalized_pool, _pool_np, _pool_grid, _even = self._deployment_pool_entry(
            game_state, current_deployer
        )
        wall_hexes = self._wall_hex_set(game_state)
        scoring = [hex_pos for hex_pos in normalized_pool if hex_pos not in wall_hexes]
        self._deployment_scoring_hexes_cache[int(current_deployer)] = scoring
        return scoring

    def _get_valid_deployment_hexes(
        self,
        game_state: Dict[str, Any],
        current_deployer: int,
        unit_id: str,
    ) -> List[tuple]:
        """Build sorted list of currently valid deployment hexes for player."""
        unit = get_unit_by_id(str(unit_id), game_state)
        if unit is None:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")

        wall_hexes = self._wall_hex_set(game_state)
        board_cols = int(require_key(game_state, "board_cols"))
        board_rows = int(require_key(game_state, "board_rows"))
        pool_set, normalized_pool, pool_np, pool_grid, even_mask_np = self._deployment_pool_entry(
            game_state, current_deployer
        )

        base_size = unit["BASE_SIZE"]
        from engine.phase_handlers.shared_utils import get_engagement_zone as _get_ez
        ez = _get_ez(game_state)

        # Volet DISCRET (bornes + murs + appartenance au pool) : miroir exact du commit
        # `deployment_handlers.deploy_unit` (footprint ⊆ pool, ∉ mur, dans les bornes).
        # Le chevauchement inter-unités N'EST PAS testé ici par cellules : le commit
        # utilise le clearance euclidien continu (`candidate_overlaps_any_unit`) — on
        # applique donc ce MÊME modèle en post-filtre (`_deployment_clearance_filter`),
        # sinon le masque proposerait des hexes que `deploy_unit` rejette (deadlock
        # `deploy_footprint_occupied`). Convention projet : le déploiement copie la phase move.
        # Empreinte mono-hex : géométrie hex (x1 — 1 fig = 1 case, `geometry_is_hex`) ou socle de
        # taille 1. Le prédicat était `ez <= 1`, qui ne désigne plus le x1 depuis que l'EZ vaut 2".
        from engine.spatial_relations import geometry_is_hex
        if geometry_is_hex(game_state) or base_size == 1:
            # Single-hex footprint: pool + murs (le chevauchement passe par le clearance)
            # Exactement le sur-ensemble de scoring (pool moins murs) : le recopier ici en
            # ferait diverger la définition du contrat `valid_hexes ⊆ scoring_hexes`.
            cell_valid = self.deployment_scoring_hexes(game_state, current_deployer)
            return self._deployment_clearance_filter(game_state, str(unit_id), unit, cell_valid)

        # Multi-hex units: vectorized numpy footprint check (bornes + murs + pool)
        from engine.hex_utils import precompute_footprint_offsets
        base_shape = unit["BASE_SHAPE"]
        orientation = int(unit["orientation"])
        off_e, off_o = precompute_footprint_offsets(base_shape, base_size, orientation)
        off_e_np = np.array(off_e, dtype=np.int32)
        off_o_np = np.array(off_o, dtype=np.int32)

        grid_cols = board_cols + 10
        grid_rows = board_rows + 10
        obstacle_grid = np.zeros((grid_cols, grid_rows), dtype=bool)
        if wall_hexes:
            obs_arr = np.array(list(wall_hexes), dtype=np.int32)
            in_grid = (
                (obs_arr[:, 0] >= 0) & (obs_arr[:, 0] < grid_cols) &
                (obs_arr[:, 1] >= 0) & (obs_arr[:, 1] < grid_rows)
            )
            obs_arr = obs_arr[in_grid]
            if len(obs_arr) > 0:
                obstacle_grid[obs_arr[:, 0], obs_arr[:, 1]] = True

        # Erosion morphologique. Le calcul direct materialisait un tableau (Nk, M, 2) par unite :
        # sur le board x5 le pool de deploiement fait ~16 000 hexes et un socle 18 pese 211
        # offsets, soit 3,4 M positions construites puis indexees a chaque appel. On erode plutot
        # UNE fois la grille des cellules acceptables par l'empreinte, puis on lit le resultat a
        # l'ancre : cout M x grille au lieu de Nk x M, et ici Nk >> grille/M (mesure : x31 a x62).
        #
        # Equivalence stricte avec le calcul direct : `acc[p] = ET sur les offsets de
        # ok_grid[p + off]` est exactement `np.all(in_pool & no_obstacle)` pour l'ancre p.
        # `ok_grid` porte deja la contrainte de bornes, donc une empreinte qui deborde du plateau
        # lit False — meme rejet que `in_bounds` cote calcul direct — et un decalage qui sort de
        # la grille etendue laisse la case a False (`shifted` initialise a zero).
        in_board = np.zeros_like(pool_grid)
        in_board[:board_cols, :board_rows] = True
        ok_grid = pool_grid & ~obstacle_grid & in_board

        valid_mask = np.zeros(len(pool_np), dtype=bool)
        for mask, off_arr in ((even_mask_np, off_e_np), (~even_mask_np, off_o_np)):
            if not np.any(mask):
                continue
            acc = np.ones_like(ok_grid)
            for _off in off_arr:
                dc = int(_off[0])
                dr = int(_off[1])
                shifted = np.zeros_like(ok_grid)
                c_lo = max(0, dc)
                c_hi = grid_cols - max(0, -dc)
                r_lo = max(0, dr)
                r_hi = grid_rows - max(0, -dr)
                if c_lo < c_hi and r_lo < r_hi:
                    shifted[c_lo - dc:c_hi - dc, r_lo - dr:r_hi - dr] = ok_grid[c_lo:c_hi, r_lo:r_hi]
                acc &= shifted
                if not acc.any():
                    break
            anchors = pool_np[mask]  # (Nk, 2)
            valid_mask[mask] = acc[anchors[:, 0], anchors[:, 1]]

        # `.tolist()` convertit le tableau en entiers Python en une passe C ; l'ancien
        # `(int(c), int(r))` par element payait deux appels `int()` par hex retenu.
        cell_valid = [(c, r) for c, r in pool_np[valid_mask].tolist()]
        return self._deployment_clearance_filter(game_state, str(unit_id), unit, cell_valid)

    def _deployment_clearance_filter(
        self,
        game_state: Dict[str, Any],
        unit_id: str,
        unit: Dict[str, Any],
        candidates: List[tuple],
    ) -> List[tuple]:
        """Ne garde que les hexes dont le socle ne chevauche AUCUNE unité selon le modèle
        du commit (`candidate_overlaps_any_unit` : clearance euclidien continu rond↔rond,
        méthode empreinte sinon). Broad-phase numpy (distance centre à centre vs rayons
        englobants) pour ne lancer le test exact que sur les candidats proches d'une unité
        — les autres sont trivialement valides. Miroir strict de `deploy_unit`."""
        if not candidates:
            return candidates
        from engine.phase_handlers.shared_utils import candidate_overlaps_any_unit
        from engine.hex_utils import Socle, bounding_radius_norm

        units_cache = require_key(game_state, "units_cache")
        shape = require_key(unit, "BASE_SHAPE")
        base_size = require_key(unit, "BASE_SIZE")
        cand_reach = bounding_radius_norm(shape, base_size)

        other_centers: List[tuple] = []
        other_reach: List[float] = []
        for uid, entry in units_cache.items():
            if str(uid) == str(unit_id):
                continue
            other_centers.append(
                (int(require_key(entry, "col")), int(require_key(entry, "row")))
            )
            other_reach.append(
                bounding_radius_norm(require_key(entry, "BASE_SHAPE"), require_key(entry, "BASE_SIZE"))
            )
        if not other_centers:
            return list(candidates)

        _SQRT3 = 1.7320508075688772

        def _cx(cols: np.ndarray) -> np.ndarray:
            return cols.astype(np.float64) * 1.5 + 0.75

        def _cy(cols: np.ndarray, rows: np.ndarray) -> np.ndarray:
            return (
                rows.astype(np.float64) * _SQRT3
                + ((cols & 1).astype(np.float64) * _SQRT3) / 2.0
                + _SQRT3 / 2.0
            )

        oc = np.array(other_centers, dtype=np.int32)
        ox = _cx(oc[:, 0])
        oy = _cy(oc[:, 0], oc[:, 1])
        orad = np.array(other_reach, dtype=np.float64)
        gate = cand_reach + orad + 1.0  # marge broad-phase conservatrice

        cand_arr = np.array(candidates, dtype=np.int32)
        ccx = _cx(cand_arr[:, 0])
        ccy = _cy(cand_arr[:, 0], cand_arr[:, 1])
        dist = np.hypot(ccx[:, None] - ox[None, :], ccy[:, None] - oy[None, :])  # (N,K)
        near_any = np.any(dist <= gate[None, :], axis=1)

        valid: List[tuple] = []
        for i, (col, row) in enumerate(candidates):
            if not near_any[i]:
                valid.append((col, row))
                continue
            fp = compute_candidate_footprint(int(col), int(row), unit, game_state)
            cand = Socle(shape=shape, base_size=base_size, col=int(col), row=int(row), fp=fp)
            if not candidate_overlaps_any_unit(game_state, cand, exclude_unit_id=str(unit_id)):
                valid.append((col, row))
        return valid

    def _get_enemy_reference_hexes(self, game_state: Dict[str, Any], current_deployer: int) -> List[tuple[int, int]]:
        """
        Build enemy reference hexes for distance scoring.

        Uses currently deployed enemy units when available; otherwise uses enemy deployment pool.
        """
        enemy_player = 2 if int(current_deployer) == 1 else 1
        enemy_deployed = []
        for unit in require_key(game_state, "units"):
            unit_player = int(require_key(unit, "player"))
            if unit_player != enemy_player:
                continue
            col = int(require_key(unit, "col"))
            row = int(require_key(unit, "row"))
            if col >= 0 and row >= 0:
                enemy_deployed.append((col, row))
        if enemy_deployed:
            return enemy_deployed

        deployment_pools = require_key(game_state, "deployment_pools")
        if enemy_player in deployment_pools:
            enemy_pool = deployment_pools[enemy_player]
        elif str(enemy_player) in deployment_pools:
            enemy_pool = deployment_pools[str(enemy_player)]
        else:
            raise KeyError(f"deployment_pools missing player {enemy_player}")
        parsed_enemy_pool = []
        for raw_hex in enemy_pool:
            if isinstance(raw_hex, (list, tuple)) and len(raw_hex) == 2:
                parsed_enemy_pool.append((int(raw_hex[0]), int(raw_hex[1])))
            elif isinstance(raw_hex, dict):
                parsed_enemy_pool.append((int(require_key(raw_hex, "col")), int(require_key(raw_hex, "row"))))
            else:
                raise TypeError(f"Invalid deployment hex format: {raw_hex}")
        return parsed_enemy_pool

    def _get_enemy_deployment_pool_hexes(
        self, game_state: Dict[str, Any], current_deployer: int
    ) -> List[tuple[int, int]]:
        """Get enemy deployment pool hexes (stable reference for potential LoS)."""
        enemy_player = 2 if int(current_deployer) == 1 else 1
        deployment_pools = require_key(game_state, "deployment_pools")
        if enemy_player in deployment_pools:
            enemy_pool = deployment_pools[enemy_player]
        elif str(enemy_player) in deployment_pools:
            enemy_pool = deployment_pools[str(enemy_player)]
        else:
            raise KeyError(f"deployment_pools missing player {enemy_player}")
        parsed_enemy_pool = []
        for raw_hex in enemy_pool:
            if isinstance(raw_hex, (list, tuple)) and len(raw_hex) == 2:
                parsed_enemy_pool.append((int(raw_hex[0]), int(raw_hex[1])))
            elif isinstance(raw_hex, dict):
                parsed_enemy_pool.append((int(require_key(raw_hex, "col")), int(require_key(raw_hex, "row"))))
            else:
                raise TypeError(f"Invalid deployment hex format: {raw_hex}")
        return parsed_enemy_pool

    def _get_objective_hexes(self, game_state: Dict[str, Any]) -> List[tuple[int, int]]:
        """Extract objective hexes from game_state with strict validation."""
        objectives = require_key(game_state, "objectives")
        objective_hexes: List[tuple[int, int]] = []
        for objective in objectives:
            objective_hex_list = require_key(objective, "hexes")
            for raw_hex in objective_hex_list:
                if isinstance(raw_hex, (list, tuple)) and len(raw_hex) == 2:
                    objective_hexes.append((int(raw_hex[0]), int(raw_hex[1])))
                elif isinstance(raw_hex, dict):
                    objective_hexes.append((int(require_key(raw_hex, "col")), int(require_key(raw_hex, "row"))))
                else:
                    raise TypeError(f"Invalid objective hex format: {raw_hex}")
        if not objective_hexes:
            raise ValueError("objectives are required for deployment scoring")
        return objective_hexes

    def _get_objective_centers(self, game_state: Dict[str, Any]) -> List[tuple[int, int]]:
        """Extract objective center hex (or centroid) from each objective — O(N_objectives)."""
        objectives = require_key(game_state, "objectives")
        centers: List[tuple[int, int]] = []
        for objective in objectives:
            if "center" in objective:
                c = objective["center"]
                centers.append((int(c[0]), int(c[1])))
            else:
                hexes = objective["hexes"]
                if not hexes:
                    raise ValueError(f"Objective {objective.get('id')} has no center and no hexes")
                avg_c = sum(int(h[0]) if isinstance(h, (list, tuple)) else int(h["col"]) for h in hexes) // len(hexes)
                avg_r = sum(int(h[1]) if isinstance(h, (list, tuple)) else int(h["row"]) for h in hexes) // len(hexes)
                centers.append((avg_c, avg_r))
        if not centers:
            raise ValueError("objectives are required for deployment scoring")
        return centers

    def _build_deployed_snapshot_version(
        self, deployed_snapshot: Dict[str, tuple[int, int, int]]
    ) -> tuple[tuple[str, int, int, int], ...]:
        """Build deterministic version token for currently deployed units."""
        version_items: List[tuple[str, int, int, int]] = []
        for unit_id, payload in deployed_snapshot.items():
            player, col, row = payload
            version_items.append((str(unit_id), int(player), int(col), int(row)))
        version_items.sort(key=lambda item: item[0])
        return tuple(version_items)

    def _build_enemy_los_reference_hexes(
        self, enemy_reference_hexes: List[tuple[int, int]]
    ) -> List[tuple[int, int]]:
        """
        Build a compact deterministic subset of enemy reference hexes for LoS potential.

        Using all deployment hexes is too expensive and redundant. We keep tactical signal
        with strategic anchors: left/right extremes, top/bottom extremes, and center.
        """
        if not enemy_reference_hexes:
            raise ValueError("enemy_reference_hexes cannot be empty")

        sorted_by_col = sorted(enemy_reference_hexes, key=lambda h: (h[0], h[1]))
        sorted_by_row = sorted(enemy_reference_hexes, key=lambda h: (h[1], h[0]))

        leftmost = sorted_by_col[0]
        rightmost = sorted_by_col[-1]
        topmost = sorted_by_row[0]
        bottommost = sorted_by_row[-1]

        center_col = (leftmost[0] + rightmost[0]) // 2
        center_row = (topmost[1] + bottommost[1]) // 2
        center_hex = min(
            enemy_reference_hexes,
            key=lambda h: (abs(h[0] - center_col) + abs(h[1] - center_row), h[0], h[1]),
        )

        anchors = [leftmost, rightmost, topmost, bottommost, center_hex]
        unique_anchors: List[tuple[int, int]] = []
        seen = set()
        for anchor in anchors:
            if anchor not in seen:
                seen.add(anchor)
                unique_anchors.append(anchor)
        return unique_anchors

    def _build_deployed_snapshot(
        self, game_state: Dict[str, Any]
    ) -> Dict[str, tuple[int, int, int]]:
        """Build snapshot of deployed units: unit_id -> (player, col, row)."""
        snapshot: Dict[str, tuple[int, int, int]] = {}
        for unit in require_key(game_state, "units"):
            col = int(require_key(unit, "col"))
            row = int(require_key(unit, "row"))
            if col < 0 or row < 0:
                continue
            unit_id = str(require_key(unit, "id"))
            player = int(require_key(unit, "player"))
            snapshot[unit_id] = (player, col, row)
        return snapshot

    def _build_deployment_scoring_cache(
        self,
        game_state: Dict[str, Any],
        current_deployer: int,
        valid_hexes: List[tuple[int, int]],
    ) -> Dict[str, Any]:
        """Build full deployment scoring cache for current state."""
        _debug_mode = channel_enabled(CH_DEPLOY_CACHE, bool(game_state.get("debug_mode", False)))
        _t_cache0 = time.perf_counter() if _debug_mode else None
        trace(
            CH_DEPLOY_CACHE, _debug_mode,
            "ActionDecoder._build_deployment_scoring_cache enter current_deployer=%s valid_hexes_n=%s",
            current_deployer, len(valid_hexes),
        )
        deployed_snapshot = self._build_deployed_snapshot(game_state)
        snapshot_version = self._build_deployed_snapshot_version(deployed_snapshot)
        enemy_player = 2 if int(current_deployer) == 1 else 1

        ally_col_counts: Dict[int, int] = {}
        ally_deployed_hexes: List[tuple[int, int]] = []
        enemy_deployed_units: List[Dict[str, Any]] = []
        for player, col, row in deployed_snapshot.values():
            if player == int(current_deployer):
                ally_deployed_hexes.append((col, row))
                if col in ally_col_counts:
                    ally_col_counts[col] = ally_col_counts[col] + 1
                else:
                    ally_col_counts[col] = 1
            elif player == enemy_player:
                enemy_deployed_units.append({"col": col, "row": row})
        trace(
            CH_DEPLOY_CACHE, _debug_mode,
            "ActionDecoder._build_deployment_scoring_cache after deployed snapshot split "
            "ally_deployed_hexes_n=%s enemy_deployed_units_n=%s",
            len(ally_deployed_hexes), len(enemy_deployed_units),
        )

        enemy_pool_hexes = self._get_enemy_deployment_pool_hexes(game_state, current_deployer)
        enemy_los_reference_hexes = self._build_enemy_los_reference_hexes(enemy_pool_hexes)
        trace(
            CH_DEPLOY_CACHE, _debug_mode,
            "ActionDecoder._build_deployment_scoring_cache after enemy refs "
            "enemy_pool_hexes_n=%s enemy_los_reference_hexes_n=%s",
            len(enemy_pool_hexes), len(enemy_los_reference_hexes),
        )
        # La signature de terrain vient des GRILLES de blocage elles-mêmes (murs + areas
        # obscurantes) : ce que `deployment_los` lit, ni plus ni moins. Une seule clé sert la
        # mémoire et le disque — les séparer, c'est rouvrir la possibilité qu'une seule des deux
        # soit corrigée (V11 §0.65).
        topology_key = (
            int(current_deployer),
            tuple(enemy_los_reference_hexes),
            ground_los_blocking_signature(game_state),
        )
        potential_los_cache_file_path = self._get_deployment_potential_los_cache_file_path(
            topology_key
        )
        if topology_key not in self._deployment_potential_los_cache:
            if os.path.exists(potential_los_cache_file_path):
                trace(
                    CH_DEPLOY_CACHE, _debug_mode,
                    "ActionDecoder._build_deployment_scoring_cache loading shared potential_los cache path=%s",
                    potential_los_cache_file_path,
                )
                self._deployment_potential_los_cache[topology_key] = (
                    self._load_deployment_potential_los_disk_cache(potential_los_cache_file_path)
                )
            else:
                self._deployment_potential_los_cache[topology_key] = {}
        potential_los_cache_for_topology = self._deployment_potential_los_cache[topology_key]

        los_exposure_by_hex: Dict[tuple[int, int], int] = {}
        potential_los_exposure_by_hex: Dict[tuple[int, int], int] = {}
        los_exposure_total_s = 0.0
        potential_los_total_s = 0.0

        if valid_hexes:
            valid_arr = np.array(valid_hexes, dtype=np.int64)

            # --- Batch LoS from each deployed enemy to all valid hexes ---
            # L'exposition s'accumule DANS UN TABLEAU, le dictionnaire n'est construit qu'une
            # fois à la fin : `counts += seen` coûte 0,004 ms là où la boucle Python sur les
            # ~9 600 hexes vus par ennemi en coûtait 0,60 (mesuré). Le dict produit est le
            # même, dans le même ordre — `valid_hexes` est sans doublon (c'est le pool moins
            # les murs), donc un `+= 1` par hexe vu vaut exactement une somme de booléens.
            _t_los0 = time.perf_counter() if _debug_mode else None
            counts = np.zeros(len(valid_hexes), dtype=np.int64)
            for enemy in enemy_deployed_units:
                enemy_col = int(require_key(enemy, "col"))
                enemy_row = int(require_key(enemy, "row"))
                if enemy_col < 0 or enemy_row < 0:
                    continue
                counts += self.deployment_los(game_state, (enemy_col, enemy_row), valid_arr)
            los_exposure_by_hex = {
                h: int(c) for h, c in zip(valid_hexes, counts.tolist())
            }
            # On teste le CHRONO, pas le drapeau : c'est la meme condition (`_t_los0` n'est pose
            # que si `_debug_mode`), mais celle-ci se prouve — l'ignore precedent ne faisait que
            # taire la soustraction sur un Optional.
            if _t_los0 is not None:
                los_exposure_total_s = time.perf_counter() - _t_los0

            # --- Batch potential LoS from reference hexes ---
            _t_potential0 = time.perf_counter() if _debug_mode else None
            uncached_valid = [
                (int(c), int(r)) for c, r in valid_hexes
                if (int(c), int(r)) not in potential_los_cache_for_topology
            ]
            if uncached_valid:
                uncached_arr = np.array(uncached_valid, dtype=np.int64)
                potential_counts = np.zeros(len(uncached_valid), dtype=np.int32)
                for ref_col, ref_row in enemy_los_reference_hexes:
                    potential_counts += self.deployment_los(
                        game_state, (int(ref_col), int(ref_row)), uncached_arr
                    )
                for i, (vc, vr) in enumerate(uncached_valid):
                    potential_los_cache_for_topology[(vc, vr)] = int(potential_counts[i])
            for col, row in valid_hexes:
                potential_los_exposure_by_hex[(col, row)] = potential_los_cache_for_topology[(int(col), int(row))]
            # Idem : le chrono lui-meme est la preuve que le mode debug etait actif.
            if _t_potential0 is not None:
                potential_los_total_s = time.perf_counter() - _t_potential0
        if _t_cache0 is not None:
            trace(
                CH_DEPLOY_CACHE, _debug_mode,
                "ActionDecoder._build_deployment_scoring_cache after los maps "
                "los_exposure_by_hex_n=%s potential_los_exposure_by_hex_n=%s "
                "los_exposure_total_s=%.6f potential_los_total_s=%.6f duration_s=%.6f",
                len(los_exposure_by_hex), len(potential_los_exposure_by_hex),
                los_exposure_total_s, potential_los_total_s, time.perf_counter() - _t_cache0,
            )
        if not os.path.exists(potential_los_cache_file_path):
            self._save_deployment_potential_los_disk_cache(
                potential_los_cache_file_path,
                potential_los_cache_for_topology,
            )
            trace(
                CH_DEPLOY_CACHE, _debug_mode,
                "ActionDecoder._build_deployment_scoring_cache saved shared potential_los cache path=%s",
                potential_los_cache_file_path,
            )

        return {
            "current_deployer": int(current_deployer),
            "deployed_snapshot": deployed_snapshot,
            "deployed_snapshot_version": snapshot_version,
            "scoring_hexes": list(valid_hexes),
            "ally_col_counts": ally_col_counts,
            "ally_deployed_hexes": ally_deployed_hexes,
            "enemy_deployed_units": enemy_deployed_units,
            "los_exposure_by_hex": los_exposure_by_hex,
            "potential_los_exposure_by_hex": potential_los_exposure_by_hex,
        }

    def _update_deployment_scoring_cache_incremental(
        self,
        cache: Dict[str, Any],
        game_state: Dict[str, Any],
        current_deployer: int,
        current_snapshot: Dict[str, tuple[int, int, int]],
    ) -> bool:
        """
        Update deployment scoring cache incrementally after one new deployment.

        Returns True when incremental update succeeded, False when full rebuild is required.
        """
        previous_snapshot = require_key(cache, "deployed_snapshot")
        previous_ids = set(previous_snapshot.keys())
        current_ids = set(current_snapshot.keys())
        removed_ids = previous_ids - current_ids
        added_ids = current_ids - previous_ids
        # Un RETRAIT n'est pas un delta de déploiement (une unité posée ne se dépose pas) : c'est
        # un état qu'on ne sait pas rattraper, donc reconstruction.
        if removed_ids:
            return False
        # Un REPOSITIONNEMENT non plus. `deployment_recommit_plan` (deployment_handlers) déplace
        # une unité DÉJÀ posée : l'ensemble des ids ne bouge pas, mais les expositions calculées
        # depuis son ancienne position sont fausses et rien ici ne sait les défaire. L'ancien
        # code s'en protégeait par accident (`len(added_ids) != 1` couvrait le cas) ; le rendre
        # explicite est ce qui permet d'accepter N ajouts sans rouvrir le trou.
        for unit_id in previous_ids & current_ids:
            if previous_snapshot[unit_id] != current_snapshot[unit_id]:
                return False
        if not added_ids:
            # Ni ajout, ni retrait, ni déplacement : le cache est à jour. Ce n'est pas un échec.
            return True

        # PLUSIEURS ajouts sont la NORME, pas l'exception : les joueurs déploient en ALTERNANCE
        # (mesuré `1,2,1,2,...`), donc quand un joueur revient il a manqué sa propre pose ET
        # celle de l'adversaire. La version précédente exigeait `len(added_ids) == 1` et rendait
        # donc la main dans tous les cas réels — le chemin incrémental n'était jamais pris.
        current_snapshot_version = self._build_deployed_snapshot_version(current_snapshot)

        scoring_hexes = require_key(cache, "scoring_hexes")
        los_exposure_by_hex = require_key(cache, "los_exposure_by_hex")
        potential_los_exposure_by_hex = require_key(cache, "potential_los_exposure_by_hex")
        ally_col_counts = require_key(cache, "ally_col_counts")
        ally_deployed_hexes = require_key(cache, "ally_deployed_hexes")
        enemy_deployed_units = require_key(cache, "enemy_deployed_units")

        # MÊME modèle de LoS que la reconstruction — `deployment_los`, la règle du moteur. Les
        # deux chemins du cache doivent rester cohérents ENTRE EUX, sans quoi l'observation
        # dépendrait de l'ordre des poses (V11 §0.64).
        # Les hexes occupés ne sont PAS retirés du sur-ensemble. Il couvre le pool moins les
        # murs, une constante de l'épisode : c'est ce qui le rend réutilisable d'une unité à
        # l'autre. Écarter un hexe occupé est le travail du filtre `valid_hexes`, appliqué à la
        # LECTURE — le faire ici aussi ferait diverger le cache incrémental de la
        # reconstruction (constaté : le test d'équivalence l'a signalé sur cet exact point).
        # Tableau des hexes de scoring construit UNE fois pour tous les ennemis ajoutés (le
        # sur-ensemble ne bouge pas d'un ajout à l'autre), et seulement s'il y a un ennemi à
        # traiter — un tour où le delta est purement allié ne le paie pas.
        scoring_arr: Optional[np.ndarray] = None
        # Deltas d'exposition accumulés sur TOUS les ennemis ajoutés, appliqués au dictionnaire
        # en une seule passe : le `+= 1` par hexe vu coûtait 0,60 ms par ennemi (mesuré), la
        # somme de booléens 0,004 ms. La garde `require_key` reste, au même endroit : un hexe
        # absent du cache est un cache corrompu, pas une valeur à créer.
        deltas: Optional[np.ndarray] = None
        for added_id in added_ids:
            player, col, row = current_snapshot[added_id]
            if int(player) == int(current_deployer):
                ally_deployed_hexes.append((col, row))
                if col in ally_col_counts:
                    ally_col_counts[col] = ally_col_counts[col] + 1
                else:
                    ally_col_counts[col] = 1
                continue

            enemy_deployed_units.append({"col": col, "row": row})
            # Pas de garde sur des coordonnées sentinelles : `_build_deployed_snapshot` écarte
            # déjà les unités non posées (`if col < 0 or row < 0: continue`), donc `added_ids`
            # n'en contient jamais. Une garde ici serait du code inatteignable — la mutation
            # qui la retire laisse le test d'équivalence VERT, ce qui le prouve.
            if scoring_arr is None:
                scoring_arr = np.array(scoring_hexes, dtype=np.int64)
            seen = self.deployment_los(game_state, (int(col), int(row)), scoring_arr)
            deltas = seen.astype(np.int64) if deltas is None else deltas + seen

        if deltas is not None:
            for i in np.flatnonzero(deltas):
                key = scoring_hexes[i]
                los_exposure_by_hex[key] = require_key(los_exposure_by_hex, key) + int(deltas[i])

        cache["deployed_snapshot"] = current_snapshot
        cache["deployed_snapshot_version"] = current_snapshot_version
        return True

    def _get_or_build_deployment_scoring_cache(
        self,
        game_state: Dict[str, Any],
        current_deployer: int,
    ) -> Dict[str, Any]:
        """Cache de scoring du déployeur, mis à jour incrémentalement quand c'est possible.

        Il ne prend PLUS les hexes valides de l'unité courante : il couvre le sur-ensemble
        stable `deployment_scoring_hexes` (pool moins murs), et c'est le consommateur qui
        filtre à la lecture. Le passer en paramètre laissait croire que le contenu du cache
        dépendait de l'unité — il n'en a jamais dépendu (mesuré : 0 écart sur les
        intersections), et c'est cette fausse dépendance qui interdisait toute réutilisation.
        """
        _debug_mode = channel_enabled(CH_DEPLOY_CACHE, bool(game_state.get("debug_mode", False)))
        _t_cache0 = time.perf_counter() if _debug_mode else None
        # SUR-ENSEMBLE stable, et non les hexes valides de l'unité courante : cf.
        # `deployment_scoring_hexes` pour la mesure qui justifie ce choix.
        scoring_hexes = self.deployment_scoring_hexes(game_state, current_deployer)
        trace(
            CH_DEPLOY_CACHE, _debug_mode,
            "ActionDecoder._get_or_build_deployment_scoring_cache enter current_deployer=%s scoring_hexes_n=%s",
            current_deployer, len(scoring_hexes),
        )
        current_snapshot = self._build_deployed_snapshot(game_state)
        cache_key = self.DEPLOYMENT_SCORING_CACHE_KEY

        # UN CACHE PAR JOUEUR. Les joueurs déploient en ALTERNANCE (mesuré `1,2,1,2,...`) et
        # chacun a son propre pool, donc son propre ensemble d'hexes : un cache unique se ferait
        # invalider à CHAQUE pose par le changement de déployeur — c'est ce qui a été mesuré en
        # cours de route (9 reconstructions sur 10 consultations, soit exactement l'état d'avant).
        caches_by_deployer = game_state.setdefault(cache_key, {})
        deployer_key = int(current_deployer)

        def _full_rebuild(outcome: str) -> Dict[str, Any]:
            """Les chemins de reconstruction, qui ne diffèrent que par leur cause.

            Ils étaient écrits trois fois à l'identique (trace, compte, construit, stocke,
            trace la sortie chronométrée) : la moindre évolution — une issue de plus, un
            argument de `_build_deployment_scoring_cache`, un champ dans la trace de sortie —
            demandait trois éditions dont une pouvait s'oublier en silence.
            """
            trace(
                CH_DEPLOY_CACHE, _debug_mode,
                "ActionDecoder._get_or_build_deployment_scoring_cache rebuild cause=%s", outcome,
            )
            self._record_deployment_cache_outcome(outcome)
            rebuilt = self._build_deployment_scoring_cache(
                game_state, current_deployer, scoring_hexes
            )
            caches_by_deployer[deployer_key] = rebuilt
            if _t_cache0 is not None:
                trace(
                    CH_DEPLOY_CACHE, _debug_mode,
                    "ActionDecoder._get_or_build_deployment_scoring_cache exit path=%s duration_s=%.6f",
                    outcome, time.perf_counter() - _t_cache0,
                )
            return rebuilt

        if deployer_key not in caches_by_deployer:
            return _full_rebuild("full_build_cold")

        cache = caches_by_deployer[deployer_key]

        trace(
            CH_DEPLOY_CACHE, _debug_mode,
            "ActionDecoder._get_or_build_deployment_scoring_cache before incremental_update",
        )
        updated = self._update_deployment_scoring_cache_incremental(
            cache=cache,
            game_state=game_state,
            current_deployer=current_deployer,
            current_snapshot=current_snapshot,
        )
        if not updated:
            return _full_rebuild("full_build_incremental_failed")

        self._record_deployment_cache_outcome("incremental")
        if _t_cache0 is not None:
            trace(
                CH_DEPLOY_CACHE, _debug_mode,
                "ActionDecoder._get_or_build_deployment_scoring_cache exit path=incremental duration_s=%.6f",
                time.perf_counter() - _t_cache0,
            )
        return cache

    # ------------------------------------------------------------------
    # Candidats des slots de déploiement (V11 §0.40 point 3)
    # ------------------------------------------------------------------

    @staticmethod
    def _offset_to_cube_vec(
        cols: "np.ndarray", rows: "np.ndarray"
    ) -> tuple["np.ndarray", "np.ndarray", "np.ndarray"]:
        """Jumeau VECTORISÉ de la conversion offset -> cube de `calculate_hex_distance`.

        Délègue à `hex_utils.offset_to_cube_vec`, où vit la géométrie : la conversion odd-q en
        était à trois exemplaires, dont un seul (celui-ci) sous test d'équivalence. Le test
        reste attaché à ce symbole — il vérifie que la distance de déploiement est CELLE du
        moteur, pas une approximation vectorielle, et cela ne dépend pas d'où vit le calcul.
        """
        from engine.hex_utils import offset_to_cube_vec

        return offset_to_cube_vec(cols, rows)

    @classmethod
    def _nearest_hex_distance_vec(
        cls, cols: "np.ndarray", rows: "np.ndarray", refs: List[tuple[int, int]]
    ) -> "np.ndarray":
        """Distance hex au plus proche des `refs`, pour TOUS les hexes d'un coup.

        Une liste de références vide LÈVE, comme la version scalaire qu'elle remplace : une
        distance « infinie » servie par défaut ferait scorer toute la zone à l'identique.
        """
        if not refs:
            raise ValueError("Reference hex list cannot be empty for deployment scoring")
        x1, y1, z1 = cls._offset_to_cube_vec(cols, rows)
        best: Optional["np.ndarray"] = None
        for ref_col, ref_row in refs:
            rc, rr = int(ref_col), int(ref_row)
            z2 = rr - ((rc - (rc & 1)) >> 1)
            x2 = rc
            y2 = -x2 - z2
            d = np.maximum(
                np.maximum(np.abs(x1 - x2), np.abs(y1 - y2)), np.abs(z1 - z2)
            )
            best = d if best is None else np.minimum(best, d)
        if best is None:
            raise RuntimeError("_nearest_hex_distance_vec: refs non vide mais aucune distance")
        return best

    def _deployment_score_columns(
        self,
        game_state: Dict[str, Any],
        current_deployer: int,
        valid_hexes: List[tuple[int, int]],
        scoring_cache: Optional[Dict[str, Any]] = None,
        with_los: bool = True,
    ) -> Dict[str, Any]:
        """Ingrédients de score, calculés UNE fois pour les 5 stratégies.

        Les 5 stratégies ne diffèrent que par l'ORDRE dans lequel elles trient ces mêmes
        grandeurs. Les recalculer par stratégie (ce que faisait la version scalaire, appelée une
        fois par action) coûtait 5 passes sur ~14 000 hexes ; ici c'est une passe vectorisée
        partagée. Les valeurs sont ENTIÈRES et identiques à celles de la version scalaire —
        c'est ce qui permet à un tri lexicographique numpy de reproduire exactement l'ancien
        `max` sur tuples.
        """
        # `scoring_cache` : cache CONSTRUIT PAR L'APPELANT sur d'autres hexes que la zone de
        # déploiement (ingress move 20.04). Le cache mémoïsé, lui, est indexé sur la zone : lui
        # demander l'exposition d'un hexe hors zone lèverait (« Missing los_exposure cache
        # entry »). Les colonnes de score, elles, sont les mêmes — c'est tout l'intérêt.
        cache = (
            scoring_cache if scoring_cache is not None
            else self._get_or_build_deployment_scoring_cache(game_state, current_deployer)
        )
        ally_col_counts = require_key(cache, "ally_col_counts")
        ally_deployed_hexes = require_key(cache, "ally_deployed_hexes")
        los_exposure_by_hex = require_key(cache, "los_exposure_by_hex")
        potential_los_exposure_by_hex = require_key(cache, "potential_los_exposure_by_hex")
        raw_enemy_refs = self._get_enemy_reference_hexes(game_state, current_deployer)
        enemy_reference_hexes = (
            self._build_enemy_los_reference_hexes(raw_enemy_refs)
            if len(raw_enemy_refs) > 10
            else raw_enemy_refs
        )
        objective_centers = self._get_objective_centers(game_state)

        hexes = np.asarray(valid_hexes, dtype=np.int64)
        cols = hexes[:, 0]
        rows = hexes[:, 1]
        center_col = (int(cols.min()) + int(cols.max())) // 2
        center_row = (int(rows.min()) + int(rows.max())) // 2

        n = len(valid_hexes)
        # `with_los=False` (ingress 20.04) : les deux colonnes d'exposition ne sont PAS calculées
        # et valent None — pas zéro. Un zéro serait une valeur par défaut indiscernable d'une
        # exposition réelle nulle ; None fait lever tout lecteur qui les attendrait.
        los = np.empty(n, dtype=np.int64) if with_los else None
        potential_los = np.empty(n, dtype=np.int64) if with_los else None
        cluster = np.empty(n, dtype=np.int64)
        for i, h in enumerate(valid_hexes):
            key = (int(h[0]), int(h[1]))
            if with_los:
                if key not in los_exposure_by_hex:
                    raise KeyError(f"Missing los_exposure cache entry for hex ({key[0]},{key[1]})")
                if key not in potential_los_exposure_by_hex:
                    raise KeyError(
                        f"Missing potential_los_exposure cache entry for hex ({key[0]},{key[1]})"
                    )
                los[i] = los_exposure_by_hex[key]  # type: ignore[index]
                potential_los[i] = potential_los_exposure_by_hex[key]  # type: ignore[index]
            cluster[i] = ally_col_counts[key[0]] if key[0] in ally_col_counts else 0

        nearest_enemy = self._nearest_hex_distance_vec(cols, rows, enemy_reference_hexes)
        nearest_objective = self._nearest_hex_distance_vec(cols, rows, objective_centers)
        if ally_deployed_hexes:
            nearest_ally = self._nearest_hex_distance_vec(cols, rows, ally_deployed_hexes)
        else:
            # 0 pour TOUS : c'est déjà ce que faisait la version scalaire (aucun allié posé =
            # aucune cohésion à mesurer), donc une constante, jamais un départage.
            nearest_ally = np.zeros(n, dtype=np.int64)

        return {
            "cols": cols,
            "rows": rows,
            "center_col": center_col,
            "center_row": center_row,
            "nearest_enemy": nearest_enemy,
            "nearest_objective": nearest_objective,
            "nearest_ally": nearest_ally,
            "has_deployed_ally": bool(ally_deployed_hexes),
            "los": los,
            "potential_los": potential_los,
            "cluster": cluster,
            "progress": (-rows if int(current_deployer) == 1 else rows),
            "center_distance": np.abs(cols - center_col),
        }

    @staticmethod
    def _deployment_slot_order(columns: Dict[str, Any], action_int: int) -> "np.ndarray":
        """Ordre de préférence de la stratégie `action_int` sur tous les hexes valides.

        Les 5 stratégies (4 front agressif · 5 pression sur objectif · 6 sûr/cohésion ·
        7 flanc gauche · 8 flanc droit) sont des tris LEXICOGRAPHIQUES sur les mêmes colonnes,
        le premier critère d'abord. `np.lexsort` trie en ASCENDANT avec la clé de FIN comme
        critère principal : les clés sont donc négées (on cherche le maximum) et passées à
        l'envers, l'index brut fermant la liste pour départager les ex æquo par leur ordre
        d'apparition — exactement ce que faisait `max()`, qui rend le PREMIER maximum.
        """
        nearest_enemy = columns["nearest_enemy"]
        nearest_objective = columns["nearest_objective"]
        nearest_ally = columns["nearest_ally"]
        los = columns["los"]
        potential_los = columns["potential_los"]
        cluster = columns["cluster"]
        progress = columns["progress"]
        center_distance = columns["center_distance"]
        cols = columns["cols"]
        rows = columns["rows"]

        # Départage FINAL commun aux 5 stratégies (il suivait le tuple de score dans la version
        # scalaire) : proximité au centre de la zone, en colonne puis en ligne.
        tail = (
            -np.abs(cols - columns["center_col"]),
            -np.abs(rows - columns["center_row"]),
        )
        if action_int == DEPLOY_SLOT_BASE + 0:
            keys = (progress, -nearest_enemy, -nearest_objective, -los, -potential_los,
                    -cluster, -center_distance) + tail
        elif action_int == DEPLOY_SLOT_BASE + 1:
            keys = (-nearest_objective, -los, -potential_los, progress, -nearest_enemy,
                    -cluster, -center_distance) + tail
        elif action_int == DEPLOY_SLOT_BASE + 2:
            keys = (-los, -potential_los, nearest_enemy, -nearest_objective, -nearest_ally,
                    -cluster, -center_distance) + tail
        elif action_int == DEPLOY_SLOT_BASE + 3:
            keys = (-los, -potential_los, -cols, -nearest_objective, nearest_enemy,
                    -cluster) + tail
        elif action_int == DEPLOY_SLOT_BASE + 4:
            keys = (-los, -potential_los, cols, -nearest_objective, nearest_enemy,
                    -cluster) + tail
        else:
            raise ValueError(f"Invalid deployment action: {action_int}")

        # `keys` reproduit LITTÉRALEMENT le tuple de score de la version scalaire, dont on
        # prenait le MAXIMUM ; `np.lexsort` trie en ascendant, d'où la négation de chaque clé.
        # L'index, lui, reste ascendant : à score égal, `max()` rendait le PREMIER hexe.
        index = np.arange(len(cols), dtype=np.int64)
        return np.lexsort((index,) + tuple(-key for key in reversed(keys)))

    def deployment_slot_candidates(
        self,
        game_state: Dict[str, Any],
        current_deployer: int,
        unit_id: Any,
        valid_hexes: Optional[List[tuple[int, int]]] = None,
    ) -> Dict[int, Dict[str, Any]]:
        """Ce que CHAQUE slot de déploiement ouvert ferait réellement, pour cette unité.

        Rend `{action_int: {"hex", "plan", grandeurs de score…}}` pour les slots OUVERTS
        (`open_deploy_slot_count`), et RIEN pour les autres — un slot fermé n'a pas de candidat
        plausible, il est absent.

        C'est la SOURCE UNIQUE du couple slot -> hexe : le décodeur y lit l'hexe qu'il commite
        (`_select_deployment_hex_for_action`) et l'observation y lit ce qu'elle décrit à l'agent
        (§0.40 point 3). Le point de conception est là : décrire les candidats en recalculant une
        seconde géométrie aurait laissé l'agent choisir un slot d'après un hexe que le commit
        n'aurait pas posé.

        ⚠️ Le lien slot -> STRATÉGIE n'est pas stable en fin de déploiement : le masque n'ouvre
        que `min(5, n_hexes)` slots, donc quand il reste moins de 5 hexes valides ce sont les
        stratégies d'INDICES BAS qui survivent, pas les plus pertinentes. C'est précisément
        pourquoi l'observation décrit l'EFFET de chaque slot et jamais son index.

        Mémoïsé par (unité, déployeur, état des unités posées) : l'observation et le commit d'un
        même step partagent donc un seul calcul. Le tampon est le `deployed_snapshot_version` du
        cache de scoring — toute pose change l'état ET la liste des hexes valides.
        """
        unit = get_unit_by_id(str(unit_id), game_state)
        if unit is None:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")

        snapshot_version = self._build_deployed_snapshot_version(
            self._build_deployed_snapshot(game_state)
        )
        cache_key = (str(unit_id), int(current_deployer), snapshot_version)
        store = game_state.get(DEPLOY_SLOT_CANDIDATES_CACHE_KEY)  # get allowed (1er appel)
        if store is not None and store["key"] == cache_key:
            return store["candidates"]

        if valid_hexes is None:
            valid_hexes = self._get_valid_deployment_hexes(
                game_state, current_deployer, str(unit_id)
            )
        if not valid_hexes:
            raise ValueError(
                f"Deployment deadlock: no valid hex for player {current_deployer}, "
                f"unit {unit_id}"
            )

        columns = self._deployment_score_columns(game_state, current_deployer, valid_hexes)
        cols = columns["cols"]
        rows = columns["rows"]

        # Meilleure ancre de la stratégie DONT LA FORMATION EST EXÉCUTABLE. Le score seul ne
        # suffit pas : `valid_hexes` ne contraint que l'ANCRE (empreinte ⊆ zone, hors mur,
        # clearance — miroir T5), alors que le commit place TOUTES les figurines (V11 T6-f).
        # Une ancre au bord de zone peut donc scorer 1re et n'admettre aucune formation légale ;
        # la retourner rouvrirait le deadlock masque/commit corrigé en T5. Ce n'est PAS un repli
        # masquant une erreur : les candidates sont ordonnées par la stratégie et on retient la
        # meilleure qui est jouable — épuisement = erreur explicite.
        from engine.phase_handlers.deployment_handlers import build_validated_deployment_plan

        candidates: Dict[int, Dict[str, Any]] = {}
        for slot in range(open_deploy_slot_count(len(valid_hexes))):
            action_int = DEPLOY_SLOT_BASE + slot
            order = self._deployment_slot_order(columns, action_int)
            chosen: Optional[int] = None
            plan = None
            for idx in order:
                i = int(idx)
                plan = build_validated_deployment_plan(
                    game_state, str(unit_id), int(cols[i]), int(rows[i])
                )
                if plan is not None:
                    chosen = i
                    break
            if chosen is None:
                raise ValueError(
                    f"Deployment deadlock: aucune des {len(valid_hexes)} ancres valides "
                    f"n'admet une formation légale pour l'escouade {unit_id} "
                    f"(joueur {current_deployer})"
                )
            candidates[action_int] = {
                "hex": (int(cols[chosen]), int(rows[chosen])),
                "plan": plan,
                "nearest_enemy_distance": int(columns["nearest_enemy"][chosen]),
                "nearest_objective_distance": int(columns["nearest_objective"][chosen]),
                "nearest_ally_distance": int(columns["nearest_ally"][chosen]),
                "has_deployed_ally": columns["has_deployed_ally"],
                "los_exposure": int(columns["los"][chosen]),
                "potential_los_exposure": int(columns["potential_los"][chosen]),
                "ally_col_count": int(columns["cluster"][chosen]),
            }

        game_state[DEPLOY_SLOT_CANDIDATES_CACHE_KEY] = {
            "key": cache_key,
            "candidates": candidates,
        }
        return candidates

    def _build_ingress_scoring_cache(
        self, game_state: Dict[str, Any], player: int
    ) -> Dict[str, Any]:
        """Ingrédients de score d'un ingress move — SANS exposition de ligne de vue.

        POURQUOI cette variante existe, et pourquoi elle n'est pas une dégradation cachée :
        `_build_deployment_scoring_cache` calcule, pour CHAQUE case candidate, combien d'unités
        ennemies la voient. C'est une LoS par (ennemi × case). La zone de déploiement fait
        ~16 000 cases et n'est scorée qu'une fois par pose ; le pool d'un ingress Deep Strike
        (24.09) fait TOUT le plateau — **57 538 cases mesurées** sur le board 44x60x5 — et doit
        être re-scoré à chaque round (les ennemis ont bougé). Mesure : **2,98 s** pour la seule
        exposition, contre 0,16 s pour tout le reste (colonnes + tri + validation du plan).
        À ce prix, une escouade en réserves coûterait plus cher qu'un épisode entier.

        Ce qui est perdu, exactement : les colonnes `los` / `potential_los` ne servaient QU'À
        départager les candidats d'un slot. L'agent ne les voit pas pour un ingress —
        `_encode_deployment_candidates` n'émet le registre de candidats qu'en PHASE DE
        DÉPLOIEMENT — donc aucune feature d'observation ne devient fausse. L'ordre des slots
        d'ingress est celui de `_ingress_slot_order`, qui n'en dépend pas.
        """
        deployed_snapshot = self._build_deployed_snapshot(game_state)
        ally_col_counts: Dict[int, int] = {}
        ally_deployed_hexes: List[tuple[int, int]] = []
        for unit_player, col, row in deployed_snapshot.values():
            if unit_player != int(player):
                continue
            ally_deployed_hexes.append((col, row))
            ally_col_counts[col] = ally_col_counts.get(col, 0) + 1  # get allowed (compteur)
        return {
            "current_deployer": int(player),
            "deployed_snapshot": deployed_snapshot,
            "deployed_snapshot_version": self._build_deployed_snapshot_version(deployed_snapshot),
            "ally_col_counts": ally_col_counts,
            "ally_deployed_hexes": ally_deployed_hexes,
            # Absentes VOLONTAIREMENT (cf. docstring) : tout lecteur qui les attendrait lèvera.
            "los_exposure_by_hex": None,
            "potential_los_exposure_by_hex": None,
        }

    @staticmethod
    def _ingress_slot_order(columns: Dict[str, Any], action_int: int) -> "np.ndarray":
        """Ordre de préférence de la stratégie ``action_int`` pour un INGRESS MOVE (20.04).

        Jumeau de `_deployment_slot_order` — mêmes 5 intentions, même tri lexicographique, même
        départage final par proximité au centre — PRIVÉ des deux clés d'exposition de ligne de
        vue, que le scoring d'ingress ne calcule pas (cf. `_build_ingress_scoring_cache`).
        Les intentions restent distinctes : 4 = front agressif, 5 = pression sur objectif,
        6 = sûr (loin des ennemis, près des alliés), 7 = flanc gauche, 8 = flanc droit.
        """
        nearest_enemy = columns["nearest_enemy"]
        nearest_objective = columns["nearest_objective"]
        nearest_ally = columns["nearest_ally"]
        cluster = columns["cluster"]
        progress = columns["progress"]
        center_distance = columns["center_distance"]
        cols = columns["cols"]
        rows = columns["rows"]

        tail = (
            -np.abs(cols - columns["center_col"]),
            -np.abs(rows - columns["center_row"]),
        )
        if action_int == DEPLOY_SLOT_BASE + 0:
            keys = (progress, -nearest_enemy, -nearest_objective, -cluster, -center_distance) + tail
        elif action_int == DEPLOY_SLOT_BASE + 1:
            keys = (-nearest_objective, progress, -nearest_enemy, -cluster, -center_distance) + tail
        elif action_int == DEPLOY_SLOT_BASE + 2:
            keys = (nearest_enemy, -nearest_objective, -nearest_ally, -cluster, -center_distance) + tail
        elif action_int == DEPLOY_SLOT_BASE + 3:
            keys = (-cols, -nearest_objective, nearest_enemy, -cluster) + tail
        elif action_int == DEPLOY_SLOT_BASE + 4:
            keys = (cols, -nearest_objective, nearest_enemy, -cluster) + tail
        else:
            raise ValueError(f"Invalid ingress action: {action_int}")

        index = np.arange(len(cols), dtype=np.int64)
        return np.lexsort((index,) + tuple(-key for key in reversed(keys)))

    def ingress_slot_candidates(
        self, game_state: Dict[str, Any], squad_id: str
    ) -> Dict[int, Dict[str, Any]]:
        """Ce que CHAQUE slot ouvert ferait pour un INGRESS MOVE (20.04) de cette escouade.

        JUMEAU EXACT de ``deployment_slot_candidates`` — mêmes 5 stratégies, mêmes colonnes de
        score, même contrat « un slot ouvert a un plan validé » — appliqué à une autre aire
        légale : le pool d'ingress (`ingress_setup_pool`) au lieu de la zone de déploiement.
        L'ingress EST une mise en place (03.02), donc rien de la chaîne de placement n'est
        réécrit ici ; seul l'ensemble de cases change, et il change à chaque round (positions
        ennemies, clause de zone adverse avant le 3e round).

        Rend ``{}`` quand aucune destination légale n'existe : c'est un état de jeu normal
        (l'unité reste en réserves), pas une erreur — contrairement au déploiement, où
        l'impossibilité de poser est un deadlock.
        """
        from engine.phase_handlers.deployment_handlers import build_validated_deployment_plan
        from engine.phase_handlers.movement_handlers import ingress_setup_pool

        units_cache = require_key(game_state, "units_cache")
        entry = require_key(units_cache, str(squad_id))
        player = int(require_key(entry, "player"))

        # Mémoïsation : le masque reconstruit ces candidats à CHAQUE step tant que l'escouade en
        # réserves est active, et le calcul (exposition LoS sur toute la bande de bord) est du
        # même ordre que celui d'un déploiement. Le tampon est l'état des unités POSÉES + le
        # round : ce sont exactement les deux entrées dont dépend le pool d'ingress (positions
        # ennemies pour les 8", round pour la clause de zone adverse).
        snapshot_version = self._build_deployed_snapshot_version(
            self._build_deployed_snapshot(game_state)
        )
        cache_key = (
            str(squad_id), int(require_key(game_state, "turn")), snapshot_version,
        )
        store = game_state.get(INGRESS_SLOT_CANDIDATES_CACHE_KEY)  # get allowed (1er appel)
        if store is not None and store["key"] == cache_key:
            return store["candidates"]

        pool = ingress_setup_pool(game_state, str(squad_id))
        if not pool:
            game_state[INGRESS_SLOT_CANDIDATES_CACHE_KEY] = {"key": cache_key, "candidates": {}}
            return {}
        # Ordre STABLE et déterministe : les stratégies trient ces hexes, et `np.lexsort`
        # départage les ex æquo par l'index d'apparition (cf. `_deployment_slot_order`).
        valid_hexes: List[tuple[int, int]] = sorted(pool)
        scoring_cache = self._build_ingress_scoring_cache(game_state, player)
        columns = self._deployment_score_columns(
            game_state, player, valid_hexes, scoring_cache, with_los=False
        )
        cols = columns["cols"]
        rows = columns["rows"]

        candidates: Dict[int, Dict[str, Any]] = {}
        for slot in range(open_deploy_slot_count(len(valid_hexes))):
            action_int = DEPLOY_SLOT_BASE + slot
            order = self._ingress_slot_order(columns, action_int)
            for idx in order:
                i = int(idx)
                plan = build_validated_deployment_plan(
                    game_state, str(squad_id), int(cols[i]), int(rows[i]), pool
                )
                if plan is None:
                    continue
                candidates[action_int] = {
                    "hex": (int(cols[i]), int(rows[i])),
                    "plan": plan,
                    "nearest_enemy_distance": int(columns["nearest_enemy"][i]),
                    "nearest_objective_distance": int(columns["nearest_objective"][i]),
                    "nearest_ally_distance": int(columns["nearest_ally"][i]),
                    "has_deployed_ally": columns["has_deployed_ally"],
                    "ally_col_count": int(columns["cluster"][i]),
                }
                break
        game_state[INGRESS_SLOT_CANDIDATES_CACHE_KEY] = {
            "key": cache_key,
            "candidates": candidates,
        }
        return candidates

    def _select_deployment_hex_for_action(
        self,
        action_int: int,
        unit_id: Any,
        game_state: Dict[str, Any],
        current_deployer: int,
        valid_hexes: List[tuple[int, int]],
    ) -> tuple[int, int]:
        """
        Select deployment hex using tactical criteria driven by deployment action.

        Action mapping (les 5 stratégies DÉFINIES, `DEPLOY_STRATEGY_SLOTS`) :
        - 4: aggressive front
        - 5: objective pressure
        - 6: safe/cohesion
        - 7: left flank
        - 8: right flank

        La garde ci-dessous admet toute la plage `DEPLOY_SLOTS` (4-11) et non ces 5 seuls ids :
        un slot 9-11 est un id d'action VALIDE mais sans stratégie, et c'est le contrôle de slot
        FERMÉ qui le rejette — avec le nombre d'hexes en cause, pas un « action invalide » muet.

        LECTURE de `deployment_slot_candidates` : le choix y est fait, une fois pour les
        `DEPLOY_STRATEGY_COUNT` slots ouverts, et l'observation lit le MÊME dictionnaire
        (§0.40 point 3).
        """
        if action_int not in list(DEPLOY_SLOTS):
            raise ValueError(f"Invalid deployment action: {action_int}")

        candidates = self.deployment_slot_candidates(
            game_state, current_deployer, unit_id, valid_hexes
        )
        if action_int not in candidates:
            raise ValueError(
                f"Deployment action {action_int} joue un slot FERMÉ : seuls "
                f"{sorted(candidates)} sont ouverts pour {len(valid_hexes)} hexes valides."
            )
        candidate = candidates[action_int]
        col, row = candidate["hex"]

        # Mémoisé pour que le commit exécute CE plan sans le recalculer.
        from engine.phase_handlers.deployment_handlers import store_validated_deployment_plan

        store_validated_deployment_plan(
            game_state, str(unit_id), int(col), int(row), candidate["plan"]
        )
        return (col, row)
    
    # ── PIERRE TOMBALE — « TARGET VALIDATION » de l'ancien décodeur (2026-07-29) ──────────────
    # Ont vécu ici :
    #   `get_all_valid_targets`          rendait TOUS les ennemis vivants, sans filtre de phase
    #                                    malgré sa docstring (« based on current phase »)
    #   `can_melee_units_charge_target`  « un allié de mêlée pourrait-il charger cette cible ? »,
    #                                    portée de charge approximée par `MOVE + charge_max_distance`
    #
    # POURQUOI elles étaient mortes : aucun appelant, nulle part (ni moteur, ni ai/, ni scripts,
    # ni services). Les pools de cibles réels sont construits par les handlers de phase
    # (`shooting_build_valid_target_pool`, pools 11.02 / 12.05) et exposés à l'agent par les
    # slots de cible du masque ; le reward a sa PROPRE `_get_all_valid_targets`
    # (`engine/reward_calculator.py`), qui n'a jamais eu de rapport avec celles-ci.
    #
    # RÈGLE : ces deux méthodes étaient présentées comme « Key Methods » dans
    # `Documentation/AI_IMPLEMENTATION.md` — une doc d'API décrit ce qu'on a écrit, jamais ce que
    # la production appelle. Elle ne vaut pas preuve de vie.
    # ─────────────────────────────────────────────────────────────────────────────────────────
