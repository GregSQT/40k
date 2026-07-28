#!/usr/bin/env python3
"""
observation_builder.py - Builds observations from game state
"""

import numpy as np
from typing import Dict, List, Any, Optional, Tuple
from shared.data_validation import require_key
from engine.combat_utils import (
    calculate_hex_distance,
    expected_dice_value,
)
from engine.game_utils import get_unit_by_id
# Projection géométrique des hexes (§0.32 T-I) : UNE seule géométrie dans l'observation — celle
# de la grille égocentrique et des directions d'objectif. `hex_utils` est une feuille (math/numpy
# seulement), l'import de module ne crée aucun cycle.
from engine.hex_utils import _hex_center
from engine.phase_handlers.shared_utils import (
    get_hp_from_cache, require_hp_from_cache,
    unit_has_rule_effect,
    # PR4 4a: nouveau pipeline d observation squad
    get_fighting_models,
    # D1 : ordre des slots ennemis IDENTIQUE a l action tir/charge (source unique)
    get_enemy_slot_mapping,
    # V11 §9 P3-2 : support du choix de cible de charge. L'oracle moteur, jamais une
    # reimplementation — c'est celui qu'execute le commit `squad_charge`.
    CHARGE_MAX_ROLL,
    charge_build_valid_plan,
)
from engine.weapon_damage_cache import lookup_best_weapon
from engine.observation_weapon_profiles import (
    PROFILE_BIN_SIZE,
    PROFILE_CONT_SIZE,
    encode_squad_weapon_profiles,
)
from engine.agent_decision import read_pending_agent_decision
from engine.observation_entities import (
    AGENT_DECISION_TYPE_IDS,
    DECISION_CTX_BIN_SIZE,
    DECISION_OPTION_BIN_SIZE,
    MAX_DECISION_OPTIONS,
    decision_ctx_bin_index,
    decision_option_bin_index,
    GLOBAL_BIN_SIZE,
    GLOBAL_CONT_SIZE,
    MODEL_TYPE_BIN_SIZE,
    MODEL_TYPE_CONT_SIZE,
    OBS_PHASE_IDS,
    SELF_MODEL_BIN_SIZE,
    SELF_MODEL_CONT_SIZE,
    UNIT_BIN_SIZE,
    UNIT_CONT_SIZE,
    UNIT_RULE_EFFECT_IDS,
    WEAPON_PROFILE_CACHE_KEY,
    global_bin_index,
    global_cont_index,
    unit_bin_index,
    unit_cont_index,
)

class ObservationBuilder:
    """Builds observations for the agent."""

    # SQUAD_OBS_SIZE_TARGET (taille totale du vecteur squad) est CALCULÉE depuis le schéma
    # d'entités, plus bas — cf. « OBSERVATION SQUAD — TENSEURS D'ENTITÉS ».

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.unit_registry: Optional[Any] = None
        
        obs_params = config.get("observation_params")
        if not obs_params:
            raise KeyError("Config missing required 'observation_params' field - check w40k_core.py config dict creation")  # ✓ CHANGE 3: Enforce required config
        
        # CRITIQUE: obs_size depuis config, NO DEFAULT - raise error si manquant
        if "obs_size" not in obs_params:
            raise KeyError(
                f"Config missing required 'obs_size' in observation_params. "
                f"Must be defined in training_config.json. Current obs_params: {obs_params}"
            )
        self.obs_size = obs_params["obs_size"]  # Source unique de vérité

    def _use_ranged_scoring_for_phase(self, game_state: Dict[str, Any]) -> bool:
        """
        Resolve phase-aware weapon mode for target scoring features.

        Returns:
            True for ranged scoring, False for melee scoring.
        """
        phase = require_key(game_state, "phase")
        if phase in ("shoot", "move", "command", "deployment"):
            return True
        if phase in ("charge", "fight"):
            return False
        raise KeyError(f"Unknown phase for phase-aware weapon scoring: {phase}")

    def _get_phase_aware_best_weapon_features(
        self,
        attacker: Dict[str, Any],
        target: Dict[str, Any],
        game_state: Dict[str, Any],
    ) -> Tuple[int, float, bool]:
        """
        Common scoring service used by enemy and valid-target encoding.

        Uses _best_weapon_cache for O(1) lookup (pre-computed at episode reset).

        Returns:
            (best_weapon_index, best_kill_probability, is_ranged_mode)
        """
        is_ranged_mode = self._use_ranged_scoring_for_phase(game_state)
        cache = game_state.get("_best_weapon_cache")
        if cache is None:
            return (-1, 0.0, is_ranged_mode)

        hp_cur = get_hp_from_cache(str(target["id"]), game_state)
        if hp_cur is None or hp_cur <= 0:
            return (-1, 0.0, is_ranged_mode)

        best_idx, best_dmg = lookup_best_weapon(
            cache, str(attacker["id"]), str(target["id"]), is_ranged_mode,
        )
        if best_idx < 0 or best_dmg <= 0.0:
            return (-1, 0.0, is_ranged_mode)
        kp = min(1.0, best_dmg / float(hp_cur))
        return best_idx, kp, is_ranged_mode
    
    # ============================================================================
    # ============================================================================
    # ============================================================================
    # ============================================================================
    # ============================================================================
    # ============================================================================

    
    # ========================================================================
    # OBSERVATION SQUAD — TENSEURS D'ENTITÉS (V11 §0.30, tranche T-D)
    # ========================================================================
    # L'observation n'est plus un vecteur PLAT. Elle est un jeu de tenseurs où chaque UNITÉ —
    # la mienne, mes alliées, les ennemies — est décrite par le MÊME schéma de features
    # (`engine/observation_entities.py`, source unique) et encodée par le MÊME réseau
    # (`ai/spatial_extractor.py`). Motif (V11_entity_encoder_pointer.md §1.8, mesuré) : au
    # format plat, la première couche portait 640 paramètres PAR DIMENSION d'observation et un
    # jeu de poids DISTINCT par slot ennemi — le réseau réapprenait « évaluer un ennemi » cinq
    # fois, et chaque slot supplémentaire coûtait ~226 k paramètres. En tenseurs d'entités, le
    # coût d'un slot est nul en paramètres et le réseau généralise d'un slot à l'autre (§3.3).
    #
    # CLÉS (toutes float32 ; `grid` est ajoutée par W40KEngine._build_observation) :
    #
    #   global_cont        (GLOBAL_CONT_SIZE,)              contexte continu (normalisé
    #                                                       par VecNormalize — clé SINGLETON,
    #                                                       aucun partage de poids en jeu)
    #   global_bin         (GLOBAL_BIN_SIZE,)               contexte discret, JAMAIS normalisé
    #   allies_cont        (K_ALLY_SLOTS, UNIT_CONT_SIZE)   ⚠ LIGNE 0 = l'unité ACTIVE
    #   allies_bin         (K_ALLY_SLOTS, UNIT_BIN_SIZE)
    #   allies_wpn_cont    (K_ALLY_SLOTS, K_WEAPONS, PROFILE_CONT_SIZE)
    #   allies_wpn_bin     (K_ALLY_SLOTS, K_WEAPONS, PROFILE_BIN_SIZE)
    #   allies_types_cont  (K_ALLY_SLOTS, K_MODEL_TYPES, MODEL_TYPE_CONT_SIZE)
    #   allies_types_bin   (K_ALLY_SLOTS, K_MODEL_TYPES, MODEL_TYPE_BIN_SIZE)
    #   enemies_*          idem avec K_ENEMY_SLOTS         ⚠ ordre = get_enemy_slot_mapping
    #   self_models_cont   (SQUAD_TOP_K, SELF_MODEL_CONT_SIZE)
    #   self_models_bin    (SQUAD_TOP_K, SELF_MODEL_BIN_SIZE)
    #
    # ⚠️ L'ORDRE DES SLOTS ENNEMIS EST CONTRACTUEL (invariant D1, cf. V11_audit_observation.md
    # §8) : `enemies_*[i]` décrit l'ennemi que désigne l'action de tir de slot `i`. Les alliés,
    # eux, sont AGRÉGÉS par le réseau (aucune action ne les désigne) : leur ordre n'a donc pas
    # de sémantique — c'est précisément ce qui débloque le bloc E, resté en attente tant que
    # l'observation était plate (il aurait fallu inventer un ordre de slots, §11).
    #
    # NORMALISATION (V11 §9.5, maintenue) : les grandeurs continues restent BRUTES (aucune
    # division fixe : une division est une seconde normalisation, saturante et non
    # ré-estimable) ; les valeurs discrètes ne sont jamais normalisées. Ce qui CHANGE avec les
    # tenseurs d'entités : `VecNormalize` normalise élément par élément, donc chaque slot
    # aurait ses propres statistiques et le même encodeur verrait des échelles différentes
    # selon le slot — ce qui annulerait le partage de poids. Les clés d'entités sont donc
    # HORS `norm_obs_keys` et normalisées DANS l'encodeur, par une statistique commune à tous
    # les slots (`EntityRunningNorm`, ai/spatial_extractor.py).

    # --- Cardinalités (source unique ; le miroir avec l'espace d'action est verrouillé par
    # --- tests/unit/engine/test_entity_obs_contract.py) ---
    #: Unité active (ligne 0) + escouades alliées. Mesuré sur les rosters réels : au plus
    #: 6 escouades par camp ; K=8 laisse de la marge. Tout dépassement est LOGUÉ.
    K_ALLY_SLOTS = 8
    #: DOIT valoir SQUAD_ACTION_SHOOT_SLOT_COUNT (une action de tir par slot ennemi).
    #: 5 -> 20 en T-E : a 5 slots, 9 resets sur 10 laissaient au moins une escouade ennemie
    #: hors de l'observation ET hors de portee d'action (§1.1, mesure).
    K_ENEMY_SLOTS = 20
    #: Profils d'armes par registre et par unité — MÊME valeur pour les deux camps (§3.3 : une
    #: arme est une arme des deux côtés). Mesuré sur les rosters d'entraînement réels : au plus
    #: 6 profils de tir et 5 de mêlée par escouade. K = 10 par registre (décision §2.4) laisse
    #: donc une marge nette, et ne coûte plus rien en paramètres depuis que les armes passent par
    #: un encodeur PARTAGÉ (le coût est en compute, pas en poids — §3.4). Tout dépassement reste
    #: LOGUÉ : le jour où un roster dépasse K, on le sait au lieu de le subir.
    K_WEAPONS_RANGED = 10
    K_WEAPONS_MELEE = 10
    K_WEAPONS = K_WEAPONS_RANGED + K_WEAPONS_MELEE
    #: Types de figurines par unité (profil défensif + rôle + effectif du type), des DEUX côtés.
    #: Mesuré : jusqu'à 5 types défensifs distincts par escouade.
    K_MODEL_TYPES = 6
    #: Figurines individuelles de l'unité active (positions + engagement). Ce bloc est AGRÉGÉ
    #: par l'extracteur (aucune action ne désigne une figurine) : son plafond ne coûte donc plus
    #: aucun paramètre, et l'état par-figurine est de toute façon DÉJÀ calculé pour l'escouade
    #: entière (les tests d'EZ bouclent sur toutes les figurines vivantes). Le laisser à 6
    #: n'économisait que des scalaires, au prix de la moitié d'une escouade de 12 — mesuré :
    #: jusqu'à 12 figurines vivantes par escouade sur les rosters d'entraînement. Tout
    #: dépassement est LOGUÉ.
    SQUAD_TOP_K = 20
    SQUAD_N_OBJECTIVE_SLOTS = 5

    #: Rôles d'allocation (règle 19), ordre FIGÉ du one-hot. `None` (figurine de base) = tous
    #: les bits à zéro : c'est le cas majoritaire, il n'a pas besoin d'un bit dédié.
    SQUAD_MODEL_ROLES = ("special_weapon", "sergeant", "support", "leader")

    #: Nombre TOTAL de scalaires de l'observation vectorielle (grille exclue). C'est cette
    #: valeur que la config d'agent porte dans `observation_params.obs_size` et qui route le
    #: dispatch (w40k_core._build_observation) : elle change à chaque évolution du schéma, ce
    #: qui rend un modèle existant explicitement incompatible (retrain `--new`).
    SQUAD_OBS_SIZE_TARGET = (
        GLOBAL_CONT_SIZE
        + GLOBAL_BIN_SIZE
        + (K_ALLY_SLOTS + K_ENEMY_SLOTS)
        * (
            UNIT_CONT_SIZE
            + UNIT_BIN_SIZE
            + K_WEAPONS * (PROFILE_CONT_SIZE + PROFILE_BIN_SIZE)
            + K_MODEL_TYPES * (MODEL_TYPE_CONT_SIZE + MODEL_TYPE_BIN_SIZE)
        )
        + SQUAD_TOP_K * (SELF_MODEL_CONT_SIZE + SELF_MODEL_BIN_SIZE)
        # Bloc « contexte de décision » (V11 §9.3 P2) : sans lui, `CHOICE_i` serait un choix à
        # l'aveugle — exactement le défaut de la pseudo-décision qu'il remplace.
        + DECISION_CTX_BIN_SIZE
        + MAX_DECISION_OPTIONS * DECISION_OPTION_BIN_SIZE
    )

    @classmethod
    def squad_obs_shapes(cls) -> "Dict[str, Tuple[int, ...]]":
        """Forme de CHAQUE clé de l'observation vectorielle squad (grille exclue).

        Source unique consommée par l'espace d'observation (`W40KEngine.__init__`),
        l'observation nulle et les tests de contrat : aucune forme n'est recopiée ailleurs.
        """
        return {
            "global_cont": (GLOBAL_CONT_SIZE,),
            "global_bin": (GLOBAL_BIN_SIZE,),
            "allies_cont": (cls.K_ALLY_SLOTS, UNIT_CONT_SIZE),
            "allies_bin": (cls.K_ALLY_SLOTS, UNIT_BIN_SIZE),
            "allies_wpn_cont": (cls.K_ALLY_SLOTS, cls.K_WEAPONS, PROFILE_CONT_SIZE),
            "allies_wpn_bin": (cls.K_ALLY_SLOTS, cls.K_WEAPONS, PROFILE_BIN_SIZE),
            "allies_types_cont": (cls.K_ALLY_SLOTS, cls.K_MODEL_TYPES, MODEL_TYPE_CONT_SIZE),
            "allies_types_bin": (cls.K_ALLY_SLOTS, cls.K_MODEL_TYPES, MODEL_TYPE_BIN_SIZE),
            "enemies_cont": (cls.K_ENEMY_SLOTS, UNIT_CONT_SIZE),
            "enemies_bin": (cls.K_ENEMY_SLOTS, UNIT_BIN_SIZE),
            "enemies_wpn_cont": (cls.K_ENEMY_SLOTS, cls.K_WEAPONS, PROFILE_CONT_SIZE),
            "enemies_wpn_bin": (cls.K_ENEMY_SLOTS, cls.K_WEAPONS, PROFILE_BIN_SIZE),
            "enemies_types_cont": (cls.K_ENEMY_SLOTS, cls.K_MODEL_TYPES, MODEL_TYPE_CONT_SIZE),
            "enemies_types_bin": (cls.K_ENEMY_SLOTS, cls.K_MODEL_TYPES, MODEL_TYPE_BIN_SIZE),
            "self_models_cont": (cls.SQUAD_TOP_K, SELF_MODEL_CONT_SIZE),
            "self_models_bin": (cls.SQUAD_TOP_K, SELF_MODEL_BIN_SIZE),
            # Décision agent (§9.3 P2). ⚠ L'ORDRE DES CANDIDATS EST CONTRACTUEL, comme celui des
            # slots ennemis : `decision_options_bin[i]` décrit le candidat que joue `CHOICE_i`.
            "decision_ctx_bin": (DECISION_CTX_BIN_SIZE,),
            "decision_options_bin": (MAX_DECISION_OPTIONS, DECISION_OPTION_BIN_SIZE),
        }

    #: Clés dont les statistiques de normalisation sont partagées entre TOUS les slots
    #: (interdiction de les confier à VecNormalize, cf. l'en-tête ci-dessus).
    ENTITY_CONT_KEYS = (
        "allies_cont", "enemies_cont",
        "allies_wpn_cont", "enemies_wpn_cont",
        "allies_types_cont", "enemies_types_cont",
        "self_models_cont",
    )


    @staticmethod
    def _weapon_truncation_logger(game_state: Dict[str, Any], squad_id: str):
        """Callback de troncature du bloc profils d armes — LOGUE, jamais silencieux (§11)."""

        def _log(weapons_key: str, n_profiles: int, k_slots: int) -> None:
            from engine.game_utils import add_debug_file_log

            add_debug_file_log(
                game_state,
                f"[OBS] escouade {squad_id} : {n_profiles} profils {weapons_key} pour "
                f"{k_slots} slots — les profils les moins portes ne sont pas observes.",
            )

        return _log

    @staticmethod
    def _squad_model_types(
        alive_mids: List[str], models_cache: Dict[str, Any]
    ) -> List[Tuple[Tuple[Any, int, int, int, int], int]]:
        """Regroupe les figurines vivantes par TYPE : [( (role, HP_MAX, T, save, invul), nb ), …].

        Une escouade est homogene, sauf exceptions (arme speciale, sergent, personnage attache
        fusionne COMME figurine par la regle 19). Decrire chaque figurine separement repeterait
        le meme profil des dizaines de fois et plafonnerait arbitrairement l effectif observe ;
        decrire les TYPES avec leur effectif decrit l escouade ENTIERE en quelques dimensions
        (mesure sur les rosters reels : 4 types au maximum).

        Ordre DETERMINISTE et independant de l etat mouvant : tier de role decroissant
        (leader > support > sergeant > special_weapon > base), puis profil defensif. Les slots
        ne permutent donc pas d un step a l autre.
        """
        from engine.phase_handlers.shared_utils import ROLE_TIER

        counts: Dict[Tuple[Any, int, int, int, int], int] = {}
        for mid in alive_mids:
            model = models_cache[mid]
            key = (
                model.get("role"),  # get allowed (None = figurine de base)
                int(require_key(model, "HP_MAX")),
                int(require_key(model, "T")),
                int(require_key(model, "ARMOR_SAVE")),
                int(require_key(model, "INVUL_SAVE")),
            )
            counts[key] = counts.get(key, 0) + 1  # get allowed : accumulateur, 0 = 1re occurrence

        def _rank(item: Tuple[Tuple[Any, int, int, int, int], int]) -> Tuple[int, int, int, int, int]:
            (role, hp_max, toughness, save, invul), _count = item
            tier = ROLE_TIER[role] if role in ROLE_TIER else 0
            return (-tier, -hp_max, -toughness, save, invul)

        return sorted(counts.items(), key=_rank)

    @staticmethod
    def _squad_models_for_observation(
        alive_mids: List[str],
        models_cache: Dict[str, Any],
        squad_defence: Tuple[int, int, int, int],
    ) -> List[str]:
        """Ordonne les figurines pour le bloc C : les EXCEPTIONS d abord, puis les figurines de base.

        Le bloc n expose que `SQUAD_TOP_K` figurines. Les prendre dans l ordre de creation les
        tronque au mauvais endroit : sur les rosters reels, les personnages attaches (regle 19)
        sont ajoutes EN FIN de liste — un Warboss en 11e position d une escouade de 12 Boyz
        n etait jamais observe, ce qui rendait inoperants le role et le profil derogatoire.

        Tri par pertinence decroissante : tier de role (leader > support > sergeant >
        special_weapon > base), puis profil defensif derogatoire, puis index de creation. Il est
        DETERMINISTE a composition donnee (pas de dependance a la position ni aux PV, qui
        feraient permuter les slots d un step a l autre et brouilleraient l apprentissage).
        Aucune action ne cible une figurine par son slot (le move passe par la grille, le fight
        est oui/non), donc reordonner ce bloc n a pas d effet de bord sur le masque — a la
        difference des slots ennemis, qui restent alignes sur `get_enemy_slot_mapping`.
        """
        from engine.phase_handlers.shared_utils import ROLE_TIER

        def _rank(indexed: Tuple[int, str]) -> Tuple[int, int, int]:
            idx, mid = indexed
            model = models_cache[mid]
            role = model.get("role")  # get allowed (None = figurine de base)
            tier = ROLE_TIER[role] if role in ROLE_TIER else 0
            defence = (
                int(require_key(model, "HP_MAX")),
                int(require_key(model, "T")),
                int(require_key(model, "ARMOR_SAVE")),
                int(require_key(model, "INVUL_SAVE")),
            )
            return (-tier, 0 if defence != squad_defence else 1, idx)

        return [mid for _idx, mid in sorted(enumerate(alive_mids), key=_rank)]

    @staticmethod
    def _engagement_relevant_entries(
        game_state: Dict[str, Any],
        reference_entry: Dict[str, Any],
        engagement_zone: int,
        enemy_of_player: int,
    ) -> List[Dict[str, Any]]:
        """Escouades adverses assez proches pour POUVOIR etre en zone d engagement.

        Sur-approximation STRICTE : la borne (distance hex entre figurines les plus proches
        <= ez + rayons majorants d empreinte) est celle du pruning du move
        (`movement_handlers._relevant_enemies_for_move`, meme helpers) — tout ce qui est
        elimine est hors de portee d engagement quelle que soit la forme des socles. Le
        resultat des tests EZ est donc identique a un scan complet, sans en payer le cout :
        le test exact compare des EMPREINTES entieres (jusqu a ~200 cases par grande base) et
        l observation l evalue pour 6 figurines a chaque step.
        """
        from engine.combat_utils import calculate_hex_distance
        from engine.phase_handlers.movement_handlers import (
            _hex_radius_upper_for_engagement_prune,
            _move_preview_footprint_span,
        )
        from engine.phase_handlers.shared_utils import get_max_base_size_hex

        units_cache = require_key(game_state, "units_cache")
        max_bs = get_max_base_size_hex(game_state)
        ref_r = _hex_radius_upper_for_engagement_prune(_move_preview_footprint_span(reference_entry))
        ref_positions = list(
            require_key(reference_entry, "occupied_hexes_by_model").values()
        ) or [(int(reference_entry["col"]), int(reference_entry["row"]))]

        out: List[Dict[str, Any]] = []
        for _sid, entry in units_cache.items():
            if int(entry["player"]) == enemy_of_player:
                continue
            e_r = _hex_radius_upper_for_engagement_prune(
                min(_move_preview_footprint_span(entry), max_bs)
            )
            horizon = int(engagement_zone) + ref_r + e_r + 1
            by_model = entry.get("occupied_hexes_by_model")  # get allowed (mono-fig)
            positions = list(by_model.values()) if by_model else [(int(entry["col"]), int(entry["row"]))]
            if any(
                calculate_hex_distance(int(rc), int(rr), int(pc), int(pr)) <= horizon
                for rc, rr in ref_positions
                for pc, pr in positions
            ):
                out.append(entry)
        return out

    def _squad_terrain_flags(
        self, game_state: Dict[str, Any], active_squad_id: str, active_unit: Dict[str, Any]
    ) -> Tuple[float, float, float]:
        """(hidden, gone_to_ground_ready, in_cover) de l escouade — regles 13.09, 13.5, 13.08.

        Les trois sont calcules ICI, a l instant de l observation, et non lus sur
        ``unit['hidden']`` : ce champ n est rafraichi qu au DEBUT de la phase de tir
        (``compute_hidden_statuses``), donc il est perime pendant le move — exactement le moment
        ou l agent decide d aller se cacher. Meme geometrie que le moteur
        (``compute_models_within_terrain``), aucune duplication de regle.

        - **hidden (13.09)** : hideable (INFANTRY/BEASTS/SWARM) ET toutes les figurines vivantes
          dans une zone obscurante ET l unite n a tire ni ce tour ni au tour precedent.
        - **gone to ground « pret » (13.5)** : hidden ET toutes les figurines vivantes dans une
          zone de terrain contenant un terrain **Solid** (dense, 13.11). La derniere condition
          de 13.5 — « pas entierement visible pour la figurine ATTAQUANTE a cause d un Solid
          intervenant » — depend du tireur et n a donc PAS de valeur au niveau escouade : elle
          reste dans le calcul par-paire du moteur (``hidden_enemy_out_of_detection``). Ce
          drapeau dit « je remplis tout ce qui ne depend pas de l ennemi ».
        - **in_cover (13.08)** : hideable ET toutes les figurines vivantes dans une zone de
          terrain — c est la premiere des deux conditions alternatives de 13.08, et elle ne
          depend PAS de l attaquant : si elle est remplie par toutes mes figurines, l escouade a
          le benefice du couvert contre TOUTE attaque a distance. La seconde condition
          (« pas entierement visible pour la figurine attaquante ») est par-tireur et reste dans
          ``compute_unit_los``.
        """
        from engine.phase_handlers.shooting_handlers import compute_models_within_terrain

        units_cache = require_key(game_state, "units_cache")
        entry = units_cache[active_squad_id]
        by_model = require_key(entry, "occupied_hexes_by_model")
        # `hideable` : MEME convention de lecture que le calcul de reference du moteur
        # (`compute_hidden_statuses`, shooting_handlers) — absence = non hideable. Etre plus
        # strict ici que la source de la regle ferait diverger observation et resolution.
        if not by_model or not bool(active_unit.get("hideable")):  # get allowed (cf. ci-dessus)
            return 0.0, 0.0, 0.0
        terrain_areas = require_key(game_state, "terrain_areas")

        in_any_terrain = compute_models_within_terrain(
            entry, by_model, game_state, terrain_areas, obscuring_only=False
        )
        all_in_terrain = len(in_any_terrain) == len(by_model)
        # Les passes suivantes sont conditionnees : une zone obscurante EST une zone de terrain,
        # donc « toutes dans une zone obscurante » implique « toutes dans une zone ». Si le
        # couvert est deja faux, hidden l est aussi — inutile de rescanner (le test
        # figurine<->polygone est le poste dominant de cette fonction).
        shot_now = str(active_squad_id) in {str(x) for x in game_state.get("units_shot", set())}
        shot_prev = str(active_squad_id) in {
            str(x) for x in game_state.get("units_shot_previous_turn", set())
        }
        hidden = False
        if all_in_terrain and not shot_now and not shot_prev:
            in_obscuring = compute_models_within_terrain(
                entry, by_model, game_state, terrain_areas, obscuring_only=True
            )
            hidden = len(in_obscuring) == len(by_model)

        gtg_ready = False
        if hidden:
            # Zones contenant un terrain Solid (13.11 : les terrains dense ont la regle Solid).
            # Le moteur ne type le « dense » qu au niveau des MURS (dense_wall_hexes) : une zone
            # est donc Solid des qu elle contient un mur dense. Statique -> memoise.
            solid_areas = game_state.get("_obs_solid_terrain_areas")  # get allowed
            if solid_areas is None:
                from engine.phase_handlers.shooting_handlers import _get_dense_wall_set

                dense = _get_dense_wall_set(game_state)
                solid_areas = [
                    a
                    for a in terrain_areas
                    if any((int(h[0]), int(h[1])) in dense for h in require_key(a, "hexes"))
                ]
                game_state["_obs_solid_terrain_areas"] = solid_areas
            if solid_areas:
                in_solid = compute_models_within_terrain(
                    entry, by_model, game_state, solid_areas, obscuring_only=False
                )
                gtg_ready = len(in_solid) == len(by_model)

        return (1.0 if hidden else 0.0), (1.0 if gtg_ready else 0.0), (1.0 if all_in_terrain else 0.0)

    def _squad_objective_control(
        self, game_state: Dict[str, Any], active_player: int
    ) -> Tuple[List[float], List[float]]:
        """Controle et presence des 5 slots d objectif, du point de vue de `active_player`.

        Retourne (controle, presence) :
          - controle[i] : +1 je controle, -1 l ennemi controle, 0 conteste/neutre/absent ;
          - presence[i] : 1 si l objectif existe dans le scenario, 0 sinon (sans ce bit, le 0
            de controle est ambigu : « conteste » ou « pas d objectif »).

        LECTURE PURE de `objective_controllers`, l etat persistant du moteur — **aucun calcul
        ici**. Regle 14.02 : le controle est determine a la FIN de chaque phase et de chaque
        tour, pas en continu ; le rafraichir a chaque action serait a la fois faux (l agent
        verrait un controle qui n existe pas encore) et couteux (somme des OC par figurine sur
        toutes les zones). Le rafraichissement de frontiere est fait par
        `GameStateManager.refresh_objective_control_on_boundary`, appele par le moteur avant
        toute construction d observation (et par l API PvP) — meme source que le scoring des VP.

        Debut de bataille : aucune frontiere franchie, donc aucun controleur → 0 partout, ce
        qui est la verite de la regle, pas une valeur par defaut.
        """
        objectives = require_key(game_state, "objectives")
        controllers = game_state.get("objective_controllers", {})  # get allowed (avant 1re frontiere)

        control: List[float] = []
        presence: List[float] = []
        for i in range(self.SQUAD_N_OBJECTIVE_SLOTS):
            if i >= len(objectives):
                control.append(0.0)
                presence.append(0.0)
                continue
            controller = controllers.get(str(require_key(objectives[i], "id")))  # get allowed
            if controller is None:
                control.append(0.0)
            else:
                control.append(1.0 if int(controller) == active_player else -1.0)
            presence.append(1.0)
        return control, presence

    #: Clé du cache des hexes d'objectif, un tableau par slot (cf. `_objective_hex_arrays`).
    OBJECTIVE_HEX_ARRAYS_KEY = "_obs_objective_hex_arrays"

    def _objective_hex_arrays(
        self, game_state: Dict[str, Any]
    ) -> List[Tuple[np.ndarray, np.ndarray]]:
        """Hexes de CHAQUE objectif, un couple (cols, rows) par slot. Mémoïsé par épisode.

        Distinct de `_grid_static_hex_arrays`, qui agrège tous les objectifs en un seul tableau
        pour peindre un canal : ici il faut la distance PAR objectif, donc la séparation par
        slot. Les zones totalisent ~10 500 hexes sur le board x5 — les reconstruire à chaque
        step reviendrait à payer, en distance, ce que la grille a déjà mémoïsé en peinture.
        """
        cached = game_state.get(self.OBJECTIVE_HEX_ARRAYS_KEY)  # get allowed (1er appel)
        if cached is not None:
            return cached

        arrays: List[Tuple[np.ndarray, np.ndarray]] = []
        for objective in require_key(game_state, "objectives"):
            # `hexes` est REQUIS (même contrat que la rasterisation du canal objectif) : un
            # objectif malformé doit lever, pas devenir silencieusement infiniment lointain.
            hexes = require_key(objective, "hexes")
            cols = np.empty(len(hexes), dtype=np.float64)
            rows = np.empty(len(hexes), dtype=np.float64)
            for idx, hex_entry in enumerate(hexes):
                if isinstance(hex_entry, (list, tuple)):
                    cols[idx], rows[idx] = float(hex_entry[0]), float(hex_entry[1])
                else:
                    cols[idx] = float(require_key(hex_entry, "col"))
                    rows[idx] = float(require_key(hex_entry, "row"))
            arrays.append((cols, rows))

        game_state[self.OBJECTIVE_HEX_ARRAYS_KEY] = arrays
        return arrays

    def _squad_objective_geometry(
        self, game_state: Dict[str, Any], cx: float, cy: float
    ) -> Tuple[List[float], List[float], List[float]]:
        """(distances, cos, sin) de l'escouade observatrice vers chacun des 5 slots d'objectif.

        - **distance** : jusqu'à l'hex le PLUS PROCHE de la zone, en subhex bruts (une zone se
          rejoint par son bord, pas par son centre) ; grandeur brute, comme le reste des
          continues (V11 §9.5).
        - **direction** : vecteur unitaire vers ce même hex, dans l'espace projeté
          `_hex_center` — la projection déjà utilisée par la grille égocentrique et par le
          rendu. Mesurer la distance en subhex et la direction dans la projection reste
          cohérent : `HEX_STEP_PX` est le pas centre-à-centre de deux hexes voisins, uniforme
          sur les 6 voisins et les 2 parités (`spatial_grid`), donc les deux espaces ne
          diffèrent que d'un facteur d'échelle.

        Slot sans objectif -> (0, 0, 0), lu comme « absent » via le bit `objective_present_i`
        déjà émis. Escouade PILE sur un hex de l'objectif -> distance 0 et direction nulle : il
        n'y a pas de direction à donner, et normaliser un vecteur nul serait une division par
        zéro maquillée.

        ⚠️ **Ex-aequo tranchés explicitement.** Une zone rectangulaire présente très souvent
        deux hexes à distance égale (un de chaque côté de l'axe) : leurs directions sont alors
        opposées en `sin`. Laisser `argmin` trancher ferait dépendre la feature de l'ordre des
        hexes dans le fichier et du dernier bit du calcul flottant — deux choses qui n'ont
        aucun sens de jeu. Le départage se fait donc sur le plus petit (col, row).
        """
        from engine.hex_utils import _hex_center
        from engine.spatial_grid import HEX_STEP_PX

        arrays = self._objective_hex_arrays(game_state)
        ax, ay = _hex_center(int(round(cx)), int(round(cy)))

        distances: List[float] = []
        cosines: List[float] = []
        sines: List[float] = []
        for i in range(self.SQUAD_N_OBJECTIVE_SLOTS):
            if i >= len(arrays) or arrays[i][0].size == 0:
                distances.append(0.0)
                cosines.append(0.0)
                sines.append(0.0)
                continue
            cols, rows = arrays[i]
            # Inline de `_hex_center` vectorisé — même formule, mêmes constantes (le jumeau
            # scalaire ci-dessus sert d'oracle dans les tests).
            hex_width = 1.5
            xs = cols * hex_width + hex_width / 2.0
            ys = rows * HEX_STEP_PX + (np.mod(cols, 2.0) * HEX_STEP_PX) / 2.0 + HEX_STEP_PX / 2.0
            dx = xs - ax
            dy = ys - ay
            d2 = dx * dx + dy * dy
            min_d2 = float(d2.min())
            # Tolérance RELATIVE : deux hexes symétriques donnent le même carré à quelques ulps
            # près, et un `==` strict retomberait sur l'aléa du dernier bit.
            tied = np.flatnonzero(d2 <= min_d2 * (1.0 + 1e-9) + 1e-12)
            nearest = int(tied[np.lexsort((rows[tied], cols[tied]))[0]])
            dist_px = float(np.sqrt(d2[nearest]))
            distances.append(dist_px / HEX_STEP_PX)
            if dist_px <= 0.0:
                cosines.append(0.0)
                sines.append(0.0)
            else:
                cosines.append(float(dx[nearest]) / dist_px)
                sines.append(float(dy[nearest]) / dist_px)
        return distances, cosines, sines

    def _encode_pending_decision(
        self, game_state: Dict[str, Any], obs: Dict[str, np.ndarray], active_player: int
    ) -> None:
        """Remplit le bloc « contexte de décision » (V11 §9.3 P2).

        Le bloc reste NUL — `decision_pending` à 0 — quand aucune décision n'est en attente, ou
        quand celle en attente appartient à l'autre camp : décrire à un joueur un choix qui n'est
        pas le sien lui ferait observer des candidats qu'aucune de ses actions ne peut jouer.

        Le masque de candidat (`present`) porte le NOMBRE de candidats : les slots au-delà restent
        à zéro et sont exclus par l'encodeur, comme un slot ennemi vide.
        """
        decision = read_pending_agent_decision(game_state)
        if decision is None:
            return
        if int(require_key(decision, "player")) != int(active_player):
            return

        ctx = obs["decision_ctx_bin"]
        ctx[decision_ctx_bin_index("decision_pending")] = 1.0
        decision_type = str(require_key(decision, "type"))
        if decision_type not in AGENT_DECISION_TYPE_IDS:
            raise KeyError(
                f"_encode_pending_decision: type de decision inconnu {decision_type!r}. "
                f"Types du schema d'observation : {AGENT_DECISION_TYPE_IDS}"
            )
        ctx[decision_ctx_bin_index(f"decision_type_{decision_type}")] = 1.0

        options = require_key(decision, "options")
        if len(options) > MAX_DECISION_OPTIONS:
            raise ValueError(
                f"_encode_pending_decision: {len(options)} candidats pour "
                f"{MAX_DECISION_OPTIONS} slots — `set_pending_agent_decision` aurait du lever."
            )
        opts = obs["decision_options_bin"]
        for slot, option in enumerate(options):
            for effect_id in require_key(option, "effect_ids"):
                opts[slot, decision_option_bin_index(f"grants_{effect_id}")] = 1.0
            opts[slot, decision_option_bin_index("present")] = 1.0

    def _empty_squad_observation(self) -> Dict[str, np.ndarray]:
        """Observation nulle (escouade morte/absente) — mêmes clés et formes que le cas nominal."""
        return {
            key: np.zeros(shape, dtype=np.float32)
            for key, shape in self.squad_obs_shapes().items()
        }

    # ------------------------------------------------------------------
    # Sous-registres d'une entité (armes, types de figurines)
    # ------------------------------------------------------------------

    def _encode_entity_weapons(
        self,
        game_state: Dict[str, Any],
        squad_id: str,
        models: List[Dict[str, Any]],
        alive_mids: List[str],
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Sous-tenseurs (K_WEAPONS, PROFILE_*_SIZE) des profils d'armes d'une unité.

        MÊME encodeur et MÊME K pour une unité amie et une unité ennemie (§3.3 : « une arme est
        une arme des deux côtés »). Avant T-D, les slots ennemis n'exposaient que 2 profils de
        tir et 1 de mêlée pour un maximum MESURÉ de 6 et 5 : l'arme d'exception d'un ennemi (le
        fuseur du sergent, l'arme [ANTI] du perso attaché) était tronquée à chaque épisode
        (§1.5).

        MÉMOÏSÉ par (escouade, figurines vivantes). Ce bloc est le poste dominant de
        l'observation — il est émis pour les 16 entités à CHAQUE step — alors que son contenu
        est celui des datasheets : il ne bouge que si une figurine meurt (le nombre de porteurs
        change) ou si l'escouade change de composition. La clé porte donc les mids vivants, ce
        qui invalide exactement au bon moment ; le cache lui-même vit dans le `game_state` et
        est vidé par `build_units_cache` (reconstruction des caches au reset), sans quoi la
        rotation de rosters d'un épisode à l'autre pourrait réutiliser les armes du précédent.

        ⚠️ Le tableau renvoyé est celui du cache : l'appelant l'écrit dans l'observation par
        affectation numpy (donc par copie) et ne le mute jamais.
        ⚠️ La TRONCATURE est mise en cache elle aussi, et REJOUÉE à chaque appel. Sans cela le
        cache rendrait muet le garde-fou « aucun cap silencieux » (§11) dès le second step d'une
        composition — un verrou qui cesse d'observer est pire que pas de verrou.
        """
        cache = game_state.setdefault(WEAPON_PROFILE_CACHE_KEY, {})
        cache_key = (squad_id, tuple(alive_mids))
        hit = cache.get(cache_key)  # get allowed (absence = cache froid, pas une erreur)
        if hit is None:
            cont: List[float] = []
            binv: List[float] = []
            # Les dépassements sont COLLECTÉS au calcul froid, pas logués directement : c'est
            # la rediffusion ci-dessous qui les émet, pour que froid et chaud tracent pareil.
            truncations: List[Tuple[str, int, int]] = []
            encode_squad_weapon_profiles(
                cont,
                binv,
                models,
                self.K_WEAPONS_RANGED,
                self.K_WEAPONS_MELEE,
                on_truncation=lambda key, n, k: truncations.append((key, n, k)),
            )
            # Une escouade ne traverse qu'un nombre borné de compositions (une par perte), et
            # le cache meurt avec l'épisode : pas d'éviction à prévoir.
            hit = (
                np.asarray(cont, dtype=np.float32).reshape(self.K_WEAPONS, PROFILE_CONT_SIZE),
                np.asarray(binv, dtype=np.float32).reshape(self.K_WEAPONS, PROFILE_BIN_SIZE),
                tuple(truncations),
            )
            cache[cache_key] = hit

        log_truncation = self._weapon_truncation_logger(game_state, squad_id)
        for weapons_key, n_profiles, k_slots in hit[2]:
            log_truncation(weapons_key, n_profiles, k_slots)
        return hit[0], hit[1]

    def _encode_entity_model_types(
        self,
        game_state: Dict[str, Any],
        squad_id: str,
        alive_mids: List[str],
        models_cache: Dict[str, Any],
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Sous-tenseurs (K_MODEL_TYPES, …) des TYPES de figurines d'une unité.

        Chaque type porte son profil défensif, son rôle d'allocation (règle 19) et son effectif
        VIVANT : l'unité entière est décrite, quelle que soit sa taille. Émis pour les DEUX
        camps (§3.3) — les slots ennemis n'avaient auparavant qu'un profil défensif d'escouade,
        alors que jusqu'à 5 types défensifs distincts coexistent dans une escouade (§1.6) :
        l'agent ne pouvait pas voir qu'un Nob est plus dur que les Boyz qui l'entourent, ce qui
        décide pourtant de l'allocation des pertes et de la rentabilité d'une cible.
        """
        cont = np.zeros((self.K_MODEL_TYPES, MODEL_TYPE_CONT_SIZE), dtype=np.float32)
        binv = np.zeros((self.K_MODEL_TYPES, MODEL_TYPE_BIN_SIZE), dtype=np.float32)
        types = self._squad_model_types(alive_mids, models_cache)
        if len(types) > self.K_MODEL_TYPES:
            # Troncature LOGUÉE, jamais silencieuse (§11).
            from engine.game_utils import add_debug_file_log

            add_debug_file_log(
                game_state,
                f"[OBS] escouade {squad_id} : {len(types)} types de figurines pour "
                f"{self.K_MODEL_TYPES} slots — les moins prioritaires ne sont pas observes.",
            )
        for t_idx in range(min(self.K_MODEL_TYPES, len(types))):
            (role, hp_max, toughness, save, invul), count = types[t_idx]
            cont[t_idx] = (
                float(hp_max), float(toughness), float(save), float(invul), float(count)
            )
            for r_idx, role_name in enumerate(self.SQUAD_MODEL_ROLES):
                binv[t_idx, r_idx] = 1.0 if role == role_name else 0.0
            binv[t_idx, len(self.SQUAD_MODEL_ROLES)] = 1.0  # slot occupé
        return cont, binv

    def _encode_unit_entity(
        self,
        game_state: Dict[str, Any],
        squad_id: str,
        ctx: Dict[str, Any],
        *,
        is_ally: bool,
        is_active: bool,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Encode UNE unité selon le schéma unifié (`observation_entities`).

        Retourne (cont, bin, armes_cont, armes_bin, types_cont, types_bin). Les features
        marquées « unité ACTIVE uniquement » dans le schéma restent à zéro pour les autres
        entités : leur masque est le bit `is_active` (§3.3).
        """
        units_cache = game_state["units_cache"]
        models_cache = game_state["models_cache"]
        squad_models = game_state["squad_models"]
        squad_cache = game_state["squad_cache"]

        entry = units_cache[squad_id]
        # `squad_cache` est construit pour CHAQUE escouade de `squad_models`, en même temps que
        # `units_cache` (`build_squad_cache`) : une entrée absente est une incohérence de cache, pas
        # un cas de jeu. L'ancien `else {}` la transformait en escouade d'OC nul (§0.32 T-J).
        sq = require_key(squad_cache, squad_id)
        unit = get_unit_by_id(str(squad_id), game_state)
        if unit is None:
            raise KeyError(f"Unit {squad_id} missing from game_state['units'] for observation")
        alive_mids = [m for m in squad_models.get(squad_id, []) if m in models_cache]  # get allowed
        if not alive_mids:
            # Une escouade présente dans units_cache SANS figurine vivante est une incohérence de
            # cache (destroy_model retire l'escouade à la dernière perte) : erreur explicite
            # plutôt qu'une ligne de zéros qui se lirait « unité intacte et vide ».
            raise RuntimeError(
                f"build_squad_observation: escouade {squad_id} presente dans units_cache "
                f"mais sans figurine vivante dans models_cache (cache incoherent)."
            )
        models = [models_cache[mid] for mid in alive_mids]

        cont = np.zeros(UNIT_CONT_SIZE, dtype=np.float32)
        binv = np.zeros(UNIT_BIN_SIZE, dtype=np.float32)

        def _c(field: str, value: float) -> None:
            cont[unit_cont_index(field)] = float(value)

        def _b(field: str, value: bool) -> None:
            binv[unit_bin_index(field)] = 1.0 if value else 0.0

        # `model_count_at_start` est POSÉ pour chaque escouade par `build_units_cache`
        # (`entry["model_count_at_start"] = entry["model_count"]`) et PRÉSERVÉ à chaque
        # recalcul (`_recompute_squad_cache`) : absent, ou nul sur une escouade qu'on encode
        # comme vivante, c'est une incohérence de cache. Les deux replis précédents la
        # masquaient (§0.32 T-J) : `.get(…, len(alive_mids))` rendait un ratio de 1.0 —
        # « escouade intacte » — sur une escouade décimée, et `max(1, …)` transformait un 0 en
        # ratio > 1 servi tel quel au réseau. Le reste du moteur lit déjà cette clé sans repli
        # (`shared_utils.py:4331`, `:7151`, `fight_handlers.py:5175`).
        model_count_at_start = int(require_key(sq, "model_count_at_start"))
        if model_count_at_start <= 0:
            raise ValueError(
                f"build_squad_observation: squad_cache[{squad_id!r}]['model_count_at_start'] = "
                f"{model_count_at_start} pour une escouade encodee vivante "
                f"({len(alive_mids)} figurines) — incoherence de cache."
            )
        _c("alive_models", len(alive_mids))
        # HP_CUR : REQUIS. `build_units_cache` le pose toujours et les writers l'entretiennent —
        # un défaut à 0 dirait « escouade à 0 PV » sur une entrée de cache incomplète (§0.32 T-J).
        _c("hp_total", int(require_key(entry, "HP_CUR")))
        # VALUE vivante : somme PAR FIGURINE (exacte sur une escouade hétérogène en points).
        _c("value_alive", sum(float(require_key(models_cache[mid], "VALUE")) for mid in alive_mids))
        # OC cumulé : REQUIS. Un défaut à 0 aurait dit « cette escouade ne prend aucun objectif »
        # (règle 14) pour une entrée de cache incomplète, sans rien lever (§0.32 T-J).
        _c("oc_total", int(require_key(sq, "oc_total")))
        _c("model_count_ratio", len(alive_mids) / float(model_count_at_start))
        # En 40K les pertes s'allouent une figurine à la fois : au plus une figurine est
        # partiellement blessée. Aucune entamée -> 1.0, lecture exacte du minimum (pas un repli).
        _c(
            "wounded_hp_ratio",
            min(
                int(require_key(m, "HP_CUR")) / float(int(require_key(m, "HP_MAX")))
                for m in models
            ),
        )
        # Position mesurée depuis la figurine la PLUS PROCHE de mon centroïde, et non depuis
        # l'ancre (V11 §9.2) : sur une escouade de 20 Boyz étalée, l'ancre peut être à l'opposé
        # de la figurine qui me menace.
        #
        # Position ET choix de la figurine dans la projection `_hex_center` (§0.32 T-I) : en
        # coordonnées offset, deux voisins hexagonaux de parités de ligne différentes n'ont pas la
        # même norme, donc « la plus proche » et sa direction dépendaient de la parité. Même
        # repère que la grille égocentrique et que les directions d'objectif.
        # Une SEULE passe, sans table intermédiaire : la projection n'est utile que pour le
        # gagnant, et ce bloc tourne pour les 28 entités à chaque step (mesuré : la table coûtait
        # 1 µs par entité de plus). `<` strict -> à égalité, la première de `alive_mids` gagne,
        # comme le `min` qu'il remplace.
        anchor_x, anchor_y = ctx["anchor_x"], ctx["anchor_y"]
        nearest_d2: float = 0.0
        nearest_x: float = 0.0
        nearest_y: float = 0.0
        for i, mid in enumerate(alive_mids):
            entry_m = models_cache[mid]
            px, py = _hex_center(int(entry_m["col"]), int(entry_m["row"]))
            d2 = (px - anchor_x) ** 2 + (py - anchor_y) ** 2
            if i == 0 or d2 < nearest_d2:
                nearest_d2, nearest_x, nearest_y = d2, px, py
        _c("col_rel", nearest_x - anchor_x)
        _c("row_rel", nearest_y - anchor_y)
        if not is_active:
            # MÊME mesure que le gate de portée du moteur (socles par-figurine), donc
            # directement comparable aux portées d'armes exposées par les profils.
            from engine.phase_handlers.shared_utils import _ranged_squad_edge_distance

            _c(
                "edge_distance",
                float(
                    _ranged_squad_edge_distance(
                        game_state,
                        ctx["active_squad_id"],
                        squad_id,
                        metric=ctx["ranged_metric"],
                        attacker_socle=ctx["active_socle"],
                    )
                ),
            )
        _c("move", require_key(unit, "MOVE"))
        _c("hp_max", require_key(unit, "HP_MAX"))
        _c("toughness", require_key(unit, "T"))
        _c("armor_save", require_key(unit, "ARMOR_SAVE"))
        _c("invul_save", require_key(unit, "INVUL_SAVE"))
        # Distance PARCOURUE ce tour, en subhex GÉODÉSIQUES (le coût réel du chemin, pas l'écart
        # départ↔arrivée). Le max porte la clause 3 de [HEAVY] 24.16, la somme dit si toute
        # l'escouade a bougé ou une seule figurine.
        moved_by_model = ctx["moved_by_model"]
        moved = [float(moved_by_model.get(mid, 0.0)) for mid in alive_mids]  # get allowed
        _c("moved_max", max(moved))
        _c("moved_sum", sum(moved))

        _b("present", True)
        _b("is_ally", is_ally)
        _b("is_active", is_active)
        _b("moved", squad_id in game_state.get("units_moved", set()))      # get allowed
        _b("shot", squad_id in game_state.get("units_shot", set()))        # get allowed
        _b("fought", squad_id in game_state.get("units_attacked", set()))  # get allowed
        _b("advanced", squad_id in game_state.get("units_advanced", set()))  # get allowed
        _b("fled", squad_id in game_state.get("units_fled", set()))        # get allowed
        _b("coherent", bool(sq.get("is_coherent", False)))                 # get allowed
        _b("engaged", squad_id in ctx["engaged_squads"])
        # Mise en place / réserve : source unique `deployed_on_turn`, la MÊME que la clause 2 de
        # [HEAVY] 24.16. L'état seul ne dit pas si la pose est de CE tour — or c'est ce dernier
        # point qui supprime le bonus.
        deployed_on_turn = require_key(unit, "deployed_on_turn")
        _b("deploy_not_on_board", deployed_on_turn is None)
        _b("deploy_pre_battle", deployed_on_turn == 0)
        _b("deploy_in_battle", deployed_on_turn is not None and int(deployed_on_turn) > 0)
        _b(
            "deployed_this_turn",
            deployed_on_turn is not None and int(deployed_on_turn) == ctx["current_turn"],
        )
        # Règles d'UNITÉ en vigueur (19.04 : union escouade + characters attachés encore vivants).
        # Émises pour TOUTE entité, amie comme ennemie : savoir qu'une escouade adverse relance
        # ses charges ou pénètre l'armure de la cible la plus proche change l'évaluation de la
        # menace autant que ses armes. `unit_has_rule_effect` résout les règles SOURCES vers
        # leurs effets (une capacité nommée confère un effet technique), donc exposer les
        # effets décrit exactement ce que le moteur applique.
        for rule_id in UNIT_RULE_EFFECT_IDS:
            _b(f"rule_{rule_id}", unit_has_rule_effect(unit, rule_id))

        if not is_ally:
            # Couvert et visibilité de cette entité ENNEMIE vus depuis l'unité observatrice.
            # `cover` est la valeur EXACTE de 13.08 (ses DEUX conditions alternatives, dont
            # « pas entièrement visible pour la figurine attaquante », qui dépend du tireur) :
            # c'est ce que la résolution applique en `-1 BS`, et rien d'autre dans l'obs ne le
            # portait — le canal « couvert » de la grille dit où sont les cases couvrantes, mais
            # la fenêtre égocentrique s'arrête au budget d'Advance (~12″) quand une arme porte
            # à 24″, donc la cible tirable est souvent hors de la grille.
            #
            # `los_can_see` accompagne obligatoirement `cover_vs_observer` : sans lui, un couvert
            # à 0 serait ambigu (cible invisible OU visible sans couvert) — `cover` implique
            # `can_see` dans `compute_unit_los`.
            #
            # Coût : appel PAIR-CACHÉ (`_unit_los_pair_cache`), invalidé de façon ciblée par le
            # choke-point `_touch_unit_los` à chaque écriture de position ou perte de figurine —
            # donc correct même quand un ennemi bouge pendant mon tour (`reactive_move`). La
            # fiabilité de ce cache a été VÉRIFIÉE par mesure, pas déduite : 23 398 paires
            # comparées au calcul non caché sur 400 steps, 0 divergence.
            from engine.phase_handlers.shooting_handlers import compute_unit_los

            los = compute_unit_los(game_state, ctx["active_unit"], unit)
            _b("los_can_see", bool(los["can_see"]))
            _b("cover_vs_observer", bool(los["cover"]))

            # Combien de MES figurines peuvent frapper CETTE cible (04.02) — support du choix de
            # cible de mêlée (V11 §9 P3-1, cf. le commentaire de `n_models_engaging`).
            #
            # L'oracle est `_model_can_fight_target`, la fonction MOTEUR qu'emprunte la
            # déclaration d'attaque (`FIGHT_DECLARE_CTX.can_target`) : réimplémenter le test
            # d'engagement ici en ferait une seconde copie, libre de diverger sur la métrique —
            # le comptage annoncerait alors un volume d'attaques que la résolution ne produit pas.
            #
            # Garde par le pool 12.05 : hors pool, aucune figurine ne peut atteindre la cible
            # (le pool teste l'empreinte de l'escouade, qui contient celle de chaque figurine),
            # donc 0 sans boucler. Le coût par-figurine n'est payé qu'au contact réel.
            if squad_id in ctx["fight_target_pool"]:
                from engine.phase_handlers.fight_handlers import model_entry_can_fight_target

                # Les empreintes synthétiques par figurine sont DÉJÀ construites plus haut
                # (`synth_by_mid`, pour les drapeaux d'engagement) : on les repasse au prédicat
                # au lieu de les reconstruire. Mesuré : la reconstruction pesait ~10x le test.
                target_entry = require_key(game_state, "units_cache")[squad_id]
                _c(
                    "n_models_engaging",
                    sum(
                        1
                        for synth in ctx["synth_by_mid"].values()
                        if model_entry_can_fight_target(
                            game_state, synth, target_entry, ctx["engagement_zone"]
                        )
                    ),
                )

            # V11 §9 P3-2 — support du choix de cible de CHARGE.
            #
            # UNE seule garde, celle de la PHASE : hors charge, la question n'a pas de sens et
            # l'appel — le plus cher de l'observation — n'est pas fait. Il n'y en a PAS de
            # seconde sur l'éligibilité 11.02, et c'est une correction : `charge_build_valid_plan`
            # commence lui-même par `charge_check_eligibility` et rend `None`. Un pré-test ici
            # était donc DOUBLE pour une cible déclarable (mesuré : 4 appels pour 2 cibles) et
            # sans gain pour une cible hors portée, qui court-circuite de toute façon.
            #
            # L'oracle est `charge_build_valid_plan`, la fonction MOTEUR qu'exécute le commit
            # (`squad_charge`) : une réimplémentation annoncerait une atteignabilité que la
            # résolution ne produirait pas.
            if ctx["is_charge_phase"]:
                _b(
                    "charge_reachable_max_roll",
                    charge_build_valid_plan(
                        game_state, ctx["active_squad_id"], [squad_id], CHARGE_MAX_ROLL
                    )
                    is not None,
                )

        if is_active:
            # État terrain (13.09 / 13.5 / 13.08) recalculé à chaud : le champ unit['hidden'] du
            # moteur n'est rafraîchi qu'au début de la phase de tir, le lire ici renverrait un
            # état périmé pendant le move — exactement le moment où l'agent décide d'aller se
            # cacher.
            hidden_flag, gtg_flag, cover_flag = self._squad_terrain_flags(
                game_state, squad_id, unit
            )
            binv[unit_bin_index("hidden")] = hidden_flag
            binv[unit_bin_index("gone_to_ground")] = gtg_flag
            binv[unit_bin_index("in_cover")] = cover_flag
            _c("n_fight_eligible", ctx["n_fight_eligible"])
            _c("n_in_enemy_ez", ctx["n_in_enemy_ez"])
            _c("n_relayed_ez", ctx["n_relayed_ez"])

        wpn_cont, wpn_bin = self._encode_entity_weapons(game_state, squad_id, models, alive_mids)
        types_cont, types_bin = self._encode_entity_model_types(
            game_state, squad_id, alive_mids, models_cache
        )
        return cont, binv, wpn_cont, wpn_bin, types_cont, types_bin

    def build_squad_observation(
        self, game_state: Dict[str, Any], active_squad_id: str
    ) -> Dict[str, np.ndarray]:
        """Construit l'observation squad en TENSEURS D'ENTITÉS (clés : cf. en-tête de section).

        La grille égocentrique est fournie à part par `build_squad_grid` ; l'assemblage du Dict
        final (avec "grid") est la responsabilité de `W40KEngine._build_observation`.
        """
        # C2 cleanup (audit) : message d'erreur explicite si l'ordre d'init est cassé.
        if not all(k in game_state for k in ("units_cache", "models_cache", "squad_models", "squad_cache")):
            missing = [k for k in ("units_cache", "models_cache", "squad_models", "squad_cache") if k not in game_state]
            raise RuntimeError(
                f"build_squad_observation requires fully initialized caches. "
                f"Missing: {missing}. Initialize caches via build_units_cache before calling this function."
            )
        units_cache = game_state["units_cache"]
        models_cache = game_state["models_cache"]
        squad_models = game_state["squad_models"]
        squad_cache = game_state["squad_cache"]

        if active_squad_id not in units_cache or active_squad_id not in squad_cache:
            return self._empty_squad_observation()  # squad dead/absent -> zero observation
        active_entry = units_cache[active_squad_id]
        active_sq = squad_cache[active_squad_id]
        active_player = int(active_entry["player"])
        active_unit = get_unit_by_id(str(active_squad_id), game_state)
        if active_unit is None:
            raise KeyError(f"Unit {active_squad_id} missing from game_state['units'] for observation")

        from engine.spatial_relations import (
            get_engagement_zone,
            unit_entries_within_engagement_zone,
        )
        from engine.phase_handlers.shared_utils import _synth_model_entry
        from engine.phase_handlers.shooting_handlers import _ranged_distance_metric
        from engine.combat_utils import socle_from_cache_entry

        ez_zone = get_engagement_zone(game_state)
        current_turn = int(game_state.get("turn", 0))  # get allowed (etat non initialise = tour 0)
        enemy_player = 2 if active_player == 1 else 1
        # Centroïde : REQUIS. `_compute_squad_cache_entry` le pose toujours (même escouade morte) ;
        # un repli sur l'ancre de l'unité déplacerait l'origine T-I en silence sur un cache
        # incomplet — même famille que les replis fermés en §0.32 T-J.
        cx = float(require_key(active_sq, "centroid_col"))
        cy = float(require_key(active_sq, "centroid_row"))
        # Origine des positions RELATIVES, dans la projection `_hex_center` (§0.32 T-I) : la même
        # origine que les directions d'objectif (`_squad_objective_geometry`), donc un seul repère
        # pour tout ce que l'observation exprime « depuis moi ».
        anchor_x, anchor_y = _hex_center(int(round(cx)), int(round(cy)))

        obs = self._empty_squad_observation()

        # === CONTEXTE GLOBAL ===
        victory_points = require_key(game_state, "victory_points")
        value_at_start = require_key(game_state, "value_at_start")
        value_alive = {active_player: 0.0, enemy_player: 0.0}
        for m in models_cache.values():
            p = int(require_key(m, "player"))
            if p in value_alive:
                value_alive[p] += float(require_key(m, "VALUE"))
        g_cont = obs["global_cont"]
        g_cont[global_cont_index("turn")] = float(current_turn)
        g_cont[global_cont_index("episode_steps")] = float(int(game_state.get("episode_steps", 0)))  # get allowed
        g_cont[global_cont_index("my_victory_points")] = float(require_key(victory_points, active_player))
        g_cont[global_cont_index("enemy_victory_points")] = float(require_key(victory_points, enemy_player))
        for field, p in (("my_value_ratio", active_player), ("enemy_value_ratio", enemy_player)):
            start_value = float(require_key(value_at_start, p))
            if start_value <= 0:
                raise ValueError(
                    f"value_at_start[{p}] = {start_value} : une armee de valeur nulle rend la "
                    f"force d usure indefinie (donnee de roster invalide)."
                )
            g_cont[global_cont_index(field)] = value_alive[p] / start_value
        g_bin = obs["global_bin"]
        g_bin[global_bin_index("is_my_turn")] = (
            1.0 if int(require_key(game_state, "current_player")) == active_player else 0.0
        )
        # Phase en ONE-HOT (§0.32 T-J) : l'encodage ordinal donnait la MÊME valeur à `deployment`
        # et `command`, alors que les ids d'action 4–8 y désignent l'un un slot de déploiement,
        # l'autre une cellule de move. Aucun repli : une phase hors schéma LÈVE — un `.get(…, 0.0)`
        # aurait servi « déploiement » pour une phase inconnue.
        phase = str(require_key(game_state, "phase"))
        if phase not in OBS_PHASE_IDS:
            raise ValueError(
                f"build_squad_observation: phase inconnue {phase!r}. Phases du schema "
                f"d'observation : {OBS_PHASE_IDS} (cf. action_decoder.GAME_PHASES)."
            )
        g_bin[global_bin_index(f"phase_{phase}")] = 1.0
        # Objectifs : contrôle dans {-1, 0, +1} + bit de PRÉSENCE (distingue « contesté/vide »
        # d'« objectif absent du scénario », impossible à lire sur le seul 0).
        control, presence = self._squad_objective_control(game_state, active_player)
        for i in range(self.SQUAD_N_OBJECTIVE_SLOTS):
            g_bin[global_bin_index(f"objective_control_{i}")] = control[i]
            g_bin[global_bin_index(f"objective_present_{i}")] = presence[i]
        # Où est cet objectif, depuis MOI : distance (continue, brute) + direction unitaire.
        # La grille égocentrique ne porte que ce qui tombe dans le budget d'Advance ; au-delà,
        # ces trois nombres sont la SEULE trace d'un objectif que 3 actions de zone désignent.
        obj_dist, obj_cos, obj_sin = self._squad_objective_geometry(game_state, cx, cy)
        for i in range(self.SQUAD_N_OBJECTIVE_SLOTS):
            g_cont[global_cont_index(f"objective_distance_{i}")] = obj_dist[i]
            g_bin[global_bin_index(f"objective_dir_cos_{i}")] = obj_cos[i]
            g_bin[global_bin_index(f"objective_dir_sin_{i}")] = obj_sin[i]

        # === DÉCISION AGENT EN ATTENTE (V11 §9.3 P2) ===
        self._encode_pending_decision(game_state, obs, active_player)

        # === ENGAGEMENT (règle 03.04) — une seule passe pour toutes les entités ===
        # Le test EZ exact compare des EMPREINTES (jusqu'à ~200 cases pour une grande base) :
        # on élimine d'abord les escouades trop loin pour POUVOIR engager, avec la même borne
        # conservatrice que le pruning du move (sur-approximation stricte -> résultat
        # identique). metric="hex" ÉPINGLÉ : feature d'observation IA (V11 §10).
        friendly_sids = sorted(
            (sid for sid, e in units_cache.items() if int(e["player"]) == active_player),
            key=str,
        )
        engaged_squads: set = set()
        active_relevant_enemies: List[Dict[str, Any]] = []
        # Les entrees de `units_cache` ne portent pas leur identifiant : on retrouve le sid par
        # identite d objet (les entrees rendues par le pruning SONT celles du cache).
        sid_by_entry_id: Dict[int, str] = {id(e): sid for sid, e in units_cache.items()}
        for fsid in friendly_sids:
            f_entry = units_cache[fsid]
            relevant = self._engagement_relevant_entries(
                game_state, f_entry, ez_zone, enemy_of_player=active_player
            )
            if fsid == active_squad_id:
                active_relevant_enemies = relevant
            for e_entry in relevant:
                if unit_entries_within_engagement_zone(f_entry, e_entry, ez_zone, metric="hex"):
                    engaged_squads.add(fsid)
                    esid_of_entry = sid_by_entry_id.get(id(e_entry))
                    if esid_of_entry is None:
                        raise RuntimeError(
                            "build_squad_observation: entree ennemie hors de units_cache "
                            "(le pruning d engagement doit rendre les entrees du cache)."
                        )
                    engaged_squads.add(esid_of_entry)

        # === FIGURINES DE L'UNITÉ ACTIVE (bloc irréductiblement individuel) ===
        # Contact par figurine = présence dans la ZONE D'ENGAGEMENT (03.04) : même primitive que
        # le moteur, sur des entrées synthétiques par figurine (comme get_fighting_models).
        active_alive_mids_raw = [m for m in squad_models.get(active_squad_id, []) if m in models_cache]  # get allowed
        squad_defence = (
            int(require_key(active_unit, "HP_MAX")),
            int(require_key(active_unit, "T")),
            int(require_key(active_unit, "ARMOR_SAVE")),
            int(require_key(active_unit, "INVUL_SAVE")),
        )
        # Les EXCEPTIONS d'abord (persos attachés, sergent…) : le bloc n'expose que SQUAD_TOP_K
        # figurines et les persos attachés sont ajoutés EN FIN de liste par le moteur.
        alive_mids = self._squad_models_for_observation(
            active_alive_mids_raw, models_cache, squad_defence
        )
        fighting_set: set = set()
        try:
            fighting_set = set(get_fighting_models(game_state, active_squad_id))
        except Exception:
            fighting_set = set()
        synth_by_mid: Dict[str, Dict[str, Any]] = {}
        in_enemy_ez: Dict[str, bool] = {}
        for mid in alive_mids:
            m = models_cache[mid]
            synth = _synth_model_entry(game_state, active_squad_id, m, int(m["col"]), int(m["row"]))
            synth_by_mid[mid] = synth
            in_enemy_ez[mid] = any(
                unit_entries_within_engagement_zone(synth, ee, ez_zone, metric="hex")
                for ee in active_relevant_enemies
            )
        relayed_by_mid: Dict[str, bool] = {}
        for mid in alive_mids:
            relayed = False
            if not in_enemy_ez[mid]:
                for other_mid in alive_mids:
                    if other_mid == mid or not in_enemy_ez[other_mid]:
                        continue
                    if unit_entries_within_engagement_zone(
                        synth_by_mid[mid], synth_by_mid[other_mid], ez_zone, metric="hex"
                    ):
                        relayed = True
                        break
            relayed_by_mid[mid] = relayed
        sm_cont = obs["self_models_cont"]
        sm_bin = obs["self_models_bin"]
        if len(alive_mids) > self.SQUAD_TOP_K:
            # Troncature LOGUÉE, jamais silencieuse (§11). L'ordre place les EXCEPTIONS d'abord :
            # ce sont les figurines de base qui sortent en premier.
            from engine.game_utils import add_debug_file_log

            add_debug_file_log(
                game_state,
                f"[OBS] escouade {active_squad_id} : {len(alive_mids)} figurines vivantes pour "
                f"{self.SQUAD_TOP_K} slots — les moins prioritaires ne sont pas observees "
                f"individuellement (leur profil reste decrit par le bloc TYPES).",
            )
        for k_idx in range(min(self.SQUAD_TOP_K, len(alive_mids))):
            mid = alive_mids[k_idx]
            m = models_cache[mid]
            mx, my = _hex_center(int(m["col"]), int(m["row"]))
            sm_cont[k_idx] = (mx - anchor_x, my - anchor_y)
            sm_bin[k_idx] = (
                1.0 if mid in fighting_set else 0.0,
                1.0 if in_enemy_ez[mid] else 0.0,
                1.0 if relayed_by_mid[mid] else 0.0,
                # Masque EXPLICITE (§0.32 T-H) : cette figurine peut n'avoir aucun drapeau et
                # tomber pile sur le centroïde arrondi, donc une ligne entièrement nulle. Un
                # masque déduit de la ligne la comptait absente, sans rien lever.
                1.0,
            )

        # V11 §9 P3-1 — pool de cibles de mêlée de l'unité active (12.05). MÊME fonction que le
        # masque d'action (`build_squad_action_mask`, phase fight) : l'observation et le masque
        # doivent décrire le même ensemble de cibles, sinon l'agent verrait « frappable » ce que
        # le masque interdit. Sert aussi de garde au comptage par-figurine ci-dessous.
        from engine.phase_handlers.fight_handlers import _fight_build_valid_target_pool

        fight_target_pool = {
            str(t) for t in _fight_build_valid_target_pool(game_state, active_unit)
        }

        ctx: Dict[str, Any] = {
            "active_squad_id": active_squad_id,
            # Requis par les bits de PAIRE (couvert/visibilité vus depuis l'observateur).
            "active_unit": active_unit,
            "cx": cx,
            "cy": cy,
            # Origine PROJETÉE des positions relatives (§0.32 T-I), calculée une fois pour les 28
            # entités : `_hex_center` du centroïde arrondi de l'unité observatrice.
            "anchor_x": anchor_x,
            "anchor_y": anchor_y,
            "current_turn": current_turn,
            "engaged_squads": engaged_squads,
            "moved_by_model": require_key(game_state, "moved_distance_by_model"),
            "ranged_metric": _ranged_distance_metric(),
            "active_socle": socle_from_cache_entry(active_entry),
            # Compteurs sur l'escouade ENTIÈRE : l'état de combat ne dépend pas du plafond du
            # bloc figurines (une escouade de 20 Boyz dont 12 sont engagées le dit).
            "n_fight_eligible": sum(1 for mid in alive_mids if mid in fighting_set),
            "n_in_enemy_ez": sum(1 for mid in alive_mids if in_enemy_ez[mid]),
            "n_relayed_ez": sum(1 for mid in alive_mids if relayed_by_mid[mid]),
            # V11 §9 P3-1 — support du choix de cible de mêlée (`n_models_engaging`).
            # Le pool 12.05 est la MÊME source que le masque d'action : un ennemi qui n'y est
            # pas ne peut être frappé par AUCUNE de mes figurines (le pool teste l'empreinte de
            # l'escouade entière, qui contient celle de chaque figurine). Il sert donc de garde :
            # hors pool -> 0 sans boucler. Le coût par-figurine n'est payé qu'en mêlée réelle.
            "fight_target_pool": fight_target_pool,
            # V11 §9 P3-2 — garde de phase du bit `charge_reachable_max_roll` : hors charge, la
            # question n'a pas de sens et le plan (coûteux) n'est pas construit.
            "is_charge_phase": str(require_key(game_state, "phase")).lower() == "charge",
            # Empreintes par figurine, réutilisées telles quelles pour le comptage 04.02.
            "synth_by_mid": synth_by_mid,
            "engagement_zone": ez_zone,
        }

        def _write_entity(prefix: str, row: int, sid: str, *, is_ally: bool, is_active: bool) -> None:
            (
                e_cont, e_bin, e_wpn_cont, e_wpn_bin, e_types_cont, e_types_bin,
            ) = self._encode_unit_entity(
                game_state, sid, ctx, is_ally=is_ally, is_active=is_active
            )
            obs[f"{prefix}_cont"][row] = e_cont
            obs[f"{prefix}_bin"][row] = e_bin
            obs[f"{prefix}_wpn_cont"][row] = e_wpn_cont
            obs[f"{prefix}_wpn_bin"][row] = e_wpn_bin
            obs[f"{prefix}_types_cont"][row] = e_types_cont
            obs[f"{prefix}_types_bin"][row] = e_types_bin

        # === ENTITÉS AMIES — ligne 0 = l'unité ACTIVE (contrat, cf. en-tête de section) ===
        # Les autres alliées sont AGRÉGÉES par le réseau : leur ordre n'a pas de sémantique,
        # il est seulement DÉTERMINISTE (tri par identifiant) pour ne pas permuter d'un step à
        # l'autre.
        _write_entity("allies", 0, active_squad_id, is_ally=True, is_active=True)
        other_allies = [sid for sid in friendly_sids if sid != active_squad_id]
        if len(other_allies) > self.K_ALLY_SLOTS - 1:
            from engine.game_utils import add_debug_file_log

            add_debug_file_log(
                game_state,
                f"[OBS] joueur {active_player} : {len(other_allies) + 1} escouades alliees pour "
                f"{self.K_ALLY_SLOTS} slots — les dernieres ne sont pas observees.",
            )
        for row, sid in enumerate(other_allies[: self.K_ALLY_SLOTS - 1], start=1):
            _write_entity("allies", row, sid, is_ally=True, is_active=False)

        # === ENTITÉS ENNEMIES — l'ordre des slots EST celui de l'action de tir (invariant D1) ===
        # Source unique partagée avec le masque (build_squad_action_mask) et l'exécution
        # (action_decoder) : obs-slot-i et action-slot-i décrivent le MÊME ennemi.
        enemy_slot_ids = get_enemy_slot_mapping(game_state, active_player)
        for slot_i in range(self.K_ENEMY_SLOTS):
            esid = enemy_slot_ids[slot_i] if slot_i < len(enemy_slot_ids) else None
            if esid is None or esid not in units_cache:
                continue  # slot vide/mort : ligne de zéros, le bit `present` porte l'information
            _write_entity("enemies", slot_i, str(esid), is_ally=False, is_active=False)

        return obs

    # ========================================================================
    # T1 — GRILLE SPATIALE EGOCENTRIQUE (move_action_space_spatial_rework §6.2)
    # ========================================================================

    @staticmethod
    def squad_grid_anchor(game_state: Dict[str, Any], active_squad_id: str) -> Tuple[int, int]:
        """Hex sur lequel la grille egocentrique est centree.

        Cas normal : l'ancre de l'escouade (`units_cache[sid]["col"/"row"]`).

        Cas §0.40 point 2 — escouade PAS ENCORE POSEE : `deployed_on_turn is None` (marqueur
        pose par `create_unit`/`w40k_core` sous la forme `col < 0`). Elle n'a alors AUCUNE
        position, et centrer sur (-1,-1) sortait la fenetre du plateau : murs, allies, ennemis,
        objectifs et couvert etaient tous vides ou tronques a l'instant precis ou l'agent choisit
        son point d'entree dans la partie. On l'ancre donc sur sa ZONE DE DEPLOIEMENT, lue telle
        quelle dans `deployment_state["deployment_pools"]` — la MEME collection d'hexes que celle
        ou le decodeur choisit l'hexe (`_get_valid_deployment_hexes`). Aucune geometrie n'est
        recalculee ici, et la GEOMETRIE de la grille (`engine.spatial_grid`) est inchangee : seul
        le point d'ancrage bouge.

        Ancre = l'hex du pool le plus proche de son barycentre, pas le barycentre nu : une zone
        concave (polygone du terrain, zone amputee par les murs) peut avoir un barycentre hors
        zone. Memoise par joueur : le pool est statique sur la partie.

        Leve si l'escouade n'est pas posee et qu'aucun pool de deploiement n'existe pour son
        joueur — c'est un etat incoherent (une unite hors plateau sans zone ou la poser), pas un
        cas a absorber par une position de repli.
        """
        units_cache = require_key(game_state, "units_cache")
        active_entry = units_cache[active_squad_id]

        unit = get_unit_by_id(str(active_squad_id), game_state)
        if unit is None:
            raise KeyError(
                f"squad_grid_anchor: escouade {active_squad_id} absente de game_state['units']"
            )
        if require_key(unit, "deployed_on_turn") is not None:
            return int(active_entry["col"]), int(active_entry["row"])

        player = int(require_key(active_entry, "player"))
        anchors: Optional[Dict[int, Tuple[int, int]]] = game_state.get(
            "_grid_deployment_zone_anchor"
        )  # get allowed (memoisation construite ici au 1er appel)
        if anchors is None:
            anchors = {}
            game_state["_grid_deployment_zone_anchor"] = anchors
        if player in anchors:
            return anchors[player]

        deployment_state = require_key(game_state, "deployment_state")
        deployment_pools = require_key(deployment_state, "deployment_pools")
        pool = deployment_pools.get(player, deployment_pools.get(str(player)))
        if not pool:
            raise KeyError(
                f"squad_grid_anchor: escouade {active_squad_id} non deployee mais aucun pool de "
                f"deploiement pour le joueur {player} — impossible d'ancrer la grille."
            )
        from engine.spatial_grid import hex_centers_px

        pool_np = np.array(
            [
                (int(h[0]), int(h[1]))
                if isinstance(h, (list, tuple))
                else (int(require_key(h, "col")), int(require_key(h, "row")))
                for h in pool
            ],
            dtype=np.int64,
        )
        # Barycentre en coordonnees de RENDU et non en (col,row) : la grille hexagonale est
        # decalee d'une demi-ligne une colonne sur deux, donc une moyenne brute de (col,row) ne
        # designe pas le centre geometrique de la zone. Projection VECTORISEE (`hex_centers_px`,
        # le jumeau lot de `_hex_center` deja utilise par la rasterisation) : la zone fait
        # ~16 000 hexes, la boucle scalaire coutait 19 ms au premier appel de chaque episode.
        px, py = hex_centers_px(pool_np[:, 0], pool_np[:, 1])
        d2 = (px - px.mean()) ** 2 + (py - py.mean()) ** 2
        nearest = int(np.argmin(d2))
        anchor = (int(pool_np[nearest, 0]), int(pool_np[nearest, 1]))
        anchors[player] = anchor
        return anchor

    def build_squad_grid(self, game_state: Dict[str, Any], active_squad_id: str) -> np.ndarray:
        """Grille egocentrique (GRID_CHANNELS, GRID_SIZE, GRID_SIZE) autour de l'escouade active.

        Corrige le defaut le plus grave de l'obs squad vectorielle : elle ne contenait AUCUN terrain
        (spec §4.1), donc l'agent ne percevait pas les murs — le masque l'empechait de jouer
        illegal, jamais de contourner, de se couvrir ou de bloquer une ligne de vue.

        Canaux (spec §10.1 + V11 §9.10 + V11 §0.32) : murs, occupation alliee, occupation
        ennemie, EZ ennemie, objectifs, niveau (etages), couvert, SELF (l'escouade active seule,
        §0.32 T-L) et COUT GEODESIQUE normalise des cellules du pool de move (§0.32 T-K).

        Geometrie deleguee a `engine/spatial_grid` — source UNIQUE partagee avec le masque (T2)
        et le decoder (T3). Layout (C,H,W) = convention CNN de sb3 (`NatureCNN`).

        Rasterisation depuis les caches existants (spec §7 T1) : `wall_hexes`, `models_cache`,
        `enemy_adjacent_hexes_player_*`. On itere le CONTENU (sparse) et non la fenetre : a
        half_extent=60 la fenetre fait ~17 900 hexes, alors que murs+figurines+EZ en couvrent
        une fraction.
        """
        from engine.spatial_grid import (
            GRID_CHANNELS,
            GRID_CH_ALLY,
            GRID_CH_COVER,
            GRID_CH_ENEMY,
            GRID_CH_EZ,
            GRID_CH_LEVEL,
            GRID_CH_MOVE_COST,
            GRID_CH_OBJECTIVE,
            GRID_CH_SELF,
            GRID_CH_WALL,
            GRID_SIZE,
            cover_dilation_cells,
            dilate_channel,
            grid_half_extent_subhex,
            hex_arrays_to_cells,
        )

        grid = np.zeros((GRID_CHANNELS, GRID_SIZE, GRID_SIZE), dtype=np.float32)

        units_cache = require_key(game_state, "units_cache")
        if active_squad_id not in units_cache:
            return grid  # squad mort/absent -> grille vide (miroir de build_squad_observation)
        active_entry = units_cache[active_squad_id]
        active_player = int(active_entry["player"])
        # §0.40 point 2 : ancre deleguee — une escouade pas encore posee est ancree sur sa zone
        # de deploiement, sinon la fenetre tombait hors plateau et TOUS les canaux etaient vides.
        anchor_col, anchor_row = self.squad_grid_anchor(game_state, active_squad_id)

        half_extent = grid_half_extent_subhex(game_state, active_squad_id)

        def _paint_arrays(channel: int, cols: np.ndarray, rows: np.ndarray, value: float = 1.0) -> None:
            """Peint un LOT d'hexes (tableaux) sur un canal. Hors grille ecarte (pas de clamp)."""
            if cols.size == 0:
                return
            gx, gy, valid = hex_arrays_to_cells(cols, rows, anchor_col, anchor_row, half_extent)
            if not valid.any():
                return
            np.maximum.at(grid[channel], (gy[valid], gx[valid]), np.float32(value))

        def _paint(channel: int, hexes, value: float = 1.0) -> None:
            if not hexes:
                return
            cols = np.fromiter((h[0] for h in hexes), dtype=np.int64, count=len(hexes))
            rows = np.fromiter((h[1] for h in hexes), dtype=np.int64, count=len(hexes))
            _paint_arrays(channel, cols, rows, value)

        # Murs et objectifs sont STATIQUES sur la partie : on memoise leurs tableaux une fois
        # plutot que de reconstruire ~11 500 tuples Python a chaque step. Memoisation de donnees
        # de scenario, pas un cache masquant un recalcul necessaire.
        static: Optional[Dict[str, Tuple[np.ndarray, np.ndarray]]] = game_state.get(
            "_grid_static_hex_arrays"
        )  # get allowed (construit ici au 1er appel)
        if static is None:
            def _to_arrays(hexes) -> Tuple[np.ndarray, np.ndarray]:
                hexes = list(hexes)
                if not hexes:
                    return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)
                return (
                    np.fromiter((h[0] for h in hexes), dtype=np.int64, count=len(hexes)),
                    np.fromiter((h[1] for h in hexes), dtype=np.int64, count=len(hexes)),
                )

            objective_hexes: List[Tuple[int, int]] = []
            for objective in game_state.get("objectives", []):  # get allowed (scenario sans objectif)
                # `hexes` est REQUIS : verifie sur les objectifs runtime (20/20 le portent, cles =
                # hexes/id/name). Un acces tolerant avec defaut liste vide rendrait un objectif malforme invisible
                # dans le canal sans que rien ne le signale.
                for hex_entry in require_key(objective, "hexes"):
                    if isinstance(hex_entry, (list, tuple)):
                        objective_hexes.append((int(hex_entry[0]), int(hex_entry[1])))
                    else:
                        objective_hexes.append((int(hex_entry["col"]), int(hex_entry["row"])))

            # Cases donnant le benefice du couvert (13.08) = hexes des terrain areas. MEME
            # ensemble que celui peint en `cover_cells` par la preview de tir du moteur : une
            # figurine hideable qui s y tient est « within a terrain area ». Statique comme les
            # murs et les objectifs.
            cover_hexes: List[Tuple[int, int]] = []
            for area in game_state.get("terrain_areas", []):  # get allowed (scenario sans terrain)
                for hex_entry in require_key(area, "hexes"):
                    cover_hexes.append((int(hex_entry[0]), int(hex_entry[1])))

            static = {
                "walls": _to_arrays(game_state.get("wall_hexes", set())),  # get allowed (board sans mur)
                "objectives": _to_arrays(objective_hexes),
                "cover": _to_arrays(cover_hexes),
            }
            game_state["_grid_static_hex_arrays"] = static

        # --- Canal 0 : murs ---------------------------------------------------
        _paint_arrays(GRID_CH_WALL, *static["walls"])

        # --- Canaux 1/2/7 : occupation self / alliee / ennemie ----------------
        # V11 §0.32 T-L : l'escouade ACTIVE a son propre canal. La grille est centree sur elle et
        # chaque cellule jouable translate SON bloc : la noyer dans le canal allie la rendait
        # indistinguable d'une escouade amie voisine. `GRID_CH_ALLY` ne porte donc plus que les
        # AUTRES escouades du joueur actif.
        models_cache = require_key(game_state, "models_cache")
        squad_models = require_key(game_state, "squad_models")
        self_hexes: List[Tuple[int, int]] = []
        ally_hexes: List[Tuple[int, int]] = []
        enemy_hexes: List[Tuple[int, int]] = []
        for sid, entry in units_cache.items():
            if str(sid) == str(active_squad_id):
                sink = self_hexes
            elif int(entry["player"]) == active_player:
                sink = ally_hexes
            else:
                sink = enemy_hexes
            for mid in squad_models.get(sid, []):  # get allowed (squad sans figurine vivante)
                model = models_cache.get(mid)
                if model is None:
                    continue
                sink.append((int(model["col"]), int(model["row"])))
        _paint(GRID_CH_SELF, self_hexes)
        _paint(GRID_CH_ALLY, ally_hexes)
        _paint(GRID_CH_ENEMY, enemy_hexes)

        # --- Canal 3 : EZ ennemie ---------------------------------------------
        # Meme ensemble que celui consomme par le pool BFS (source unique de la regle).
        ez_cache_key = f"enemy_adjacent_hexes_player_{active_player}"
        if ez_cache_key in game_state:
            ez_hexes = game_state[ez_cache_key]
        else:
            # Cache construit au demarrage des phases move/shoot/charge uniquement. Hors de
            # ces phases on appelle le MEME constructeur canonique (qui memoise) plutot que
            # de laisser le canal vide : un canal EZ faussement nul serait une erreur muette.
            from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes

            ez_hexes = build_enemy_adjacent_hexes(game_state, active_player)
        _paint(GRID_CH_EZ, list(ez_hexes))

        # --- Canal 4 : objectifs ----------------------------------------------
        # Sur le board x5 les objectifs sont des ZONES (~10 500 hexes), pas des points : c'est
        # de loin le canal le plus lourd, d'ou la memoisation ci-dessus.
        _paint_arrays(GRID_CH_OBJECTIVE, *static["objectives"])

        # --- Canal 6 : couvert -------------------------------------------------
        # Hexes des terrain areas, PUIS dilatation du rayon de socle de l escouade active :
        # la regle 13.08 accorde le couvert des que le SOCLE chevauche la zone, donc les cases
        # de la couronne autour de la zone donnent aussi le couvert. Sans dilatation, l agent
        # voyait ces cases a 0 alors qu elles couvrent (ecart ~2 cellules pour un socle
        # d infanterie de 16 subhex sur le board x5). Dilatation en espace grille : exacte au
        # grain de la grille et de cout negligeable.
        _paint_arrays(GRID_CH_COVER, *static["cover"])
        grid[GRID_CH_COVER] = dilate_channel(
            grid[GRID_CH_COVER],
            cover_dilation_cells(require_key(active_entry, "BASE_SIZE"), half_extent),
        )

        # --- Canal 5 : niveau (etages) ----------------------------------------
        # Vaut 0 partout tant qu'aucun etage n'est declare : le sol EST le niveau 0, ce n'est
        # pas une absence de donnee (les etages sont un chantier en cours, spec §6.1).
        terrain_areas = game_state.get("terrain_areas", [])  # get allowed (scenario sans terrain)
        levels = sorted({int(fl["level"]) for a in terrain_areas for fl in a.get("floors", [])})  # get allowed
        if levels:
            from engine.terrain_utils import floor_hexes_at_level

            max_level = float(levels[-1])
            for level in levels:
                _paint(
                    GRID_CH_LEVEL,
                    list(floor_hexes_at_level(terrain_areas, level)),
                    value=float(level) / max_level,
                )

        # --- Canal 8 : cout geodesique du pool de move (V11 §0.32 T-K) --------
        # Ce cout etait deja calcule a chaque activation POUR LE MASQUE, puis jete — alors que
        # c'est lui qui arbitre normal vs advance (`classify_squad_move_type`), donc le droit de
        # tirer non-[ASSAULT] et de charger.
        #
        # GRATUIT PAR CONSTRUCTION : on relit la carte que le masque vient de memoiser
        # (`read_squad_move_cell_map`), on n'en redemande pas une. `_build_observation` construit
        # le masque AVANT l'obs et pour le MEME squad actif, donc aucun BFS supplementaire, et
        # surtout aucun appel de pool avec une cle de fingerprint differente de celle du masque —
        # ce qui aurait fait rater le cache a chaque step (le poste a 95,6 % du training, §0.22).
        # Un recalcul independant rouvrirait aussi la divergence obs/masque/decoder.
        #
        # Hors phase de mouvement le canal reste a 0 : aucune activation de move n'est en cours,
        # donc aucune destination n'existe. Peindre le pool d'une phase passee ferait croire a
        # l'agent qu'il peut encore bouger.
        #
        # L'encodage est affine PAR MORCEAUX (`normalize_move_costs`) pour que la frontiere
        # normal/advance tombe sur une valeur CONSTANTE : le CNN ne recoit que la grille, il ne
        # peut pas croiser le canal avec le MOVE de l'unite pour retrouver ou est cette frontiere.
        # `phase` : REQUIS, même doctrine que le vecteur (§0.32 T-J) — une phase absente doit
        # lever, pas produire silencieusement un canal de coût vide.
        # Une DÉCISION AGENT en attente (§9.3 P2) arrête le moteur sur un point de choix : le
        # masque n'expose que les `CHOICE_i`, donc aucune carte de cellules n'a été construite —
        # et il n'y en a pas à construire, puisque aucune activation de move n'est en cours. Le
        # canal reste à 0, exactement comme hors phase de mouvement. En construire une ici
        # relancerait un BFS pour peindre des destinations que l'agent ne peut pas jouer.
        if (
            str(require_key(game_state, "phase")).lower() == "move"
            and read_pending_agent_decision(game_state) is None
        ):
            from engine.phase_handlers.shared_utils import (
                _squad_is_in_enemy_er,
                read_squad_move_cell_map,
                squad_normal_move_frontier_subhex,
            )
            from engine.spatial_grid import normalize_move_costs

            cell_map = read_squad_move_cell_map(game_state, active_squad_id)
            if cell_map:
                cell_idxs = np.fromiter(cell_map.keys(), dtype=np.int64, count=len(cell_map))
                costs = np.fromiter(
                    (cost for _dest, cost in cell_map.values()),
                    dtype=np.float64,
                    count=len(cell_map),
                )
                # `normal_budget` vient de la MEME source que celle que `classify_squad_move_type`
                # compare au cout dans le masque : la frontiere du canal et celle de la regle sont
                # la meme grandeur, pas deux calculs paralleles. `normalize_move_costs` leve si un
                # cout sort de [0, demi-etendue] — pas de clip silencieux, qui ecraserait a la meme
                # valeur toutes les destinations les plus lointaines.
                grid[GRID_CH_MOVE_COST, cell_idxs // GRID_SIZE, cell_idxs % GRID_SIZE] = (
                    normalize_move_costs(
                        costs,
                        squad_normal_move_frontier_subhex(game_state, active_squad_id),
                        half_extent,
                        # Le MEME predicat d engagement que le masque (`classify_squad_move_type`
                        # recoit in_er de `_squad_is_in_enemy_er`) : engagee, tout move est un
                        # Fall Back qui coute le tir — encode au-dessus du seuil.
                        engaged=_squad_is_in_enemy_er(game_state, active_squad_id),
                    )
                )

        return grid

    # ============================================================================
    # HELPER METHODS
    # ============================================================================

    def _target_priority_score(
        self,
        target: Dict[str, Any],
        active_unit: Dict[str, Any],
        game_state: Dict[str, Any],
        positions: Dict[str, Tuple[int, int]],
    ):
        """
        Sort key for valid targets: (lower = higher priority).
        Returns (-strategic_efficiency, distance) so best targets sort first.
        """
        active_col, active_row = positions[str(active_unit["id"])]
        target_col, target_row = positions[str(target["id"])]
        distance = calculate_hex_distance(
            active_col, active_row, target_col, target_row
        )
        if "VALUE" not in target:
            raise KeyError(f"Target missing required 'VALUE' field: {target}")
        target_value = target["VALUE"]
        best_weapon_idx, _, is_ranged_mode = self._get_phase_aware_best_weapon_features(
            active_unit, target, game_state
        )
        if is_ranged_mode:
            weapons = require_key(active_unit, "RNG_WEAPONS")
        else:
            weapons = require_key(active_unit, "CC_WEAPONS")

        if best_weapon_idx < 0:
            return (0.0, distance)
        if best_weapon_idx >= len(weapons):
            raise ValueError(
                f"Phase-aware best weapon index out of range in target priority: idx={best_weapon_idx}, "
                f"weapons_len={len(weapons)}, is_ranged_mode={is_ranged_mode}, "
                f"active_unit_id={active_unit.get('id')}, target_id={target.get('id')}"
            )
        weapon = weapons[best_weapon_idx]
        unit_attacks = expected_dice_value(require_key(weapon, "NB"), "target_priority_nb")
        unit_bs = weapon["ATK"]
        unit_s = weapon["STR"]
        unit_ap = weapon["AP"]
        unit_dmg = expected_dice_value(require_key(weapon, "DMG"), "target_priority_dmg")
        if "T" not in target or "ARMOR_SAVE" not in target:
            raise KeyError(f"Target missing required T/ARMOR_SAVE: {target}")
        target_t = target["T"]
        target_save = target["ARMOR_SAVE"]
        target_hp = require_hp_from_cache(str(target["id"]), game_state)
        our_hit_prob = (7 - unit_bs) / 6.0
        if unit_s >= target_t * 2:
            our_wound_prob = 5 / 6
        elif unit_s > target_t:
            our_wound_prob = 4 / 6
        elif unit_s == target_t:
            our_wound_prob = 3 / 6
        elif unit_s * 2 <= target_t:
            our_wound_prob = 1 / 6
        else:
            our_wound_prob = 2 / 6
        target_modified_save = target_save - unit_ap
        target_failed_save = (
            1.0 if target_modified_save > 6 else (target_modified_save - 1) / 6.0
        )
        damage_per_attack = (
            our_hit_prob * our_wound_prob * target_failed_save * unit_dmg
        )
        if damage_per_attack > 0:
            activations_to_kill = target_hp / damage_per_attack
        else:
            activations_to_kill = 100
        if activations_to_kill > 0:
            strategic_efficiency = target_value / activations_to_kill
        else:
            strategic_efficiency = target_value * 100
        return (-strategic_efficiency, distance)
    
    # ============================================================================
    # DIRECTIONAL HELPERS
    # ============================================================================
    
