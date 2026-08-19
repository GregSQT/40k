"""
AnalyzerState — état partagé entre les handlers de parse_step_log.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, NamedTuple, Optional, Set, Tuple, Union

from ai.analyzer_perfig import Base
from shared.data_validation import require_key

#: cf. `AnalyzerState.phase_activation_seen`.
PhaseActivationKey = Union[Tuple[int, str, int], Tuple[str, int, int]]


class SelectTargetsFreeze(NamedTuple):
    """La CIBLE d'une activation, telle qu'elle était au Select Targets step.

    UN SEUL enregistrement, parce que ces quatre grandeurs décrivent le MÊME instant et servent
    des règles de la même famille — le ciblage, que le moteur tranche une fois pour l'activation
    entière avant d'en résoudre la moindre attaque :

    - ``models_alive`` : effectif, qu'exigent [BLAST] 24.05 et [CLEAVE] 24.06 (« models that were
      in the target unit IN THE SELECT TARGETS STEP ») ;
    - ``anchor`` / ``hp`` / ``models`` : la géométrie, qu'exigent 10.06, 04.02 et l'alternance
      12.04 ;
    - ``wounded_enemies`` : les ennemis DÉJÀ blessés que l'attaquant voyait en choisissant sa
      cible. Ce n'est pas une propriété de la cible mais du champ de tir ; elle est ici parce
      qu'elle décrit le même instant et sert la même question — celle du CHOIX de cible.

    Les deux moitiés ont vécu dans deux dictionnaires séparés le temps d'une livraison, et
    l'invariant « même instant » n'a tenu que par un commentaire — il a cédé le jour même : deux
    mesures jumelles se sont mises à lire deux ancres différentes de la même cible. Les réunir le
    rend STRUCTUREL : un site ne peut plus geler une moitié en oubliant l'autre.
    """
    models_alive: int
    anchor: Optional[Tuple[int, int]]
    hp: Optional[int]
    models: Optional[Dict[str, Tuple[int, int]]]
    wounded_enemies: FrozenSet[str]


@dataclass
class AnalyzerState:
    # Stats globales (référence partagée, pas une copie)
    stats: Dict

    # Suivi épisode
    current_episode: List = field(default_factory=list)
    current_episode_num: int = 0
    current_scenario: str = "Unknown"
    #: Siège occupé par l'AGENT dans l'épisode courant (`AGENT_PLAYER=` de l'entête `Rosters:`).
    #: `controlled_player_mode` accepte `p2` et `random` : supposer « agent == P1 » attribuait
    #: les victoires de l'agent au bot dans 180 épisodes sur 600 (33,3 % affichés, 45,3 % réels).
    current_agent_player: Optional[int] = None
    #: Datasheet PAR FIGURINE (`[MODEL_TYPES: <mid>=<UnitType> …]` de l'entête d'épisode).
    #: Une escouade n'est pas homogène : la règle 19 y replie un personnage COMME figurine, et
    #: cinq armes distinctes s'appellent « Close Combat Weapon » (NB de 2 à 6). Sans cette carte,
    #: tout plafond par figurine repose sur le type d'ESCOUADE, donc sur la mauvaise datasheet.
    model_types: Dict[str, str] = field(default_factory=dict)
    #: Effets de règle EN VIGUEUR par joueur, avec leur contribution CHIFFRÉE, lus de la ligne
    #: `T{tour} EFFECTS:` (ex. `{2: {"waaagh": "on", "waaagh_melee_atk": "+1"}}`).
    #: Le journal porte la valeur appliquée par le moteur : sans elle, l'analyzer devrait
    #: RÉ-ENCODER la règle (« waaagh ⇒ +1 »), donc en faire vivre une seconde définition qui
    #: diverge en silence le jour où la première bouge.
    active_effects: Dict[int, Dict[str, str]] = field(default_factory=dict)
    #: Socles tués et pas encore retirés de `positions_by_model` (unité → mids), avec l'unité dont
    #: l'ACTIVATION les a tués. Ils sont retirés quand une autre unité agit : pendant une salve,
    #: les jets se jugent tous sur l'empreinte d'AVANT la salve (la portée se décide au Select
    #: Targets, une fois). Cf. le bloc qui les applique dans `analyzer_core.run`.
    pending_model_removals: Dict[str, Set[str]] = field(default_factory=dict)
    pending_removals_actor: Optional[str] = None
    #: Version de grammaire déclarée par l'entête `Log grammar:` du journal (1 si absente).
    #: Elle dit ce que le journal GARANTIT porter : à partir de 2, une ligne d'attaque qui
    #: applique des dégâts DOIT nommer sa figurine allouée, et son absence est une panne du
    #: producteur — pas un vieux format sur lequel on retomberait en silence.
    log_grammar: int = 1
    episode_turn: int = 0
    episode_actions: int = 0
    last_turn: int = 0
    episode_start_time: Optional[int] = None

    # Suivi unités
    # Modèle HP par-figurine (05 Attack sequence) : unit_hp[uid] = PV de la figurine
    # "front" en cours d'endommagement ; unit_models_alive[uid] = nb de figurines vivantes.
    # Invariant conservé : uid présent dans unit_hp avec valeur > 0 ⟺ escouade vivante.
    unit_hp: Dict[str, int] = field(default_factory=dict)
    unit_models_alive: Dict[str, int] = field(default_factory=dict)
    #: PV RESTANTS de chaque figurine vivante, INDEXÉS PAR SOCLE : ``{uid: {mid: pv}}``.
    #:
    #: ⚠️ Remplace une file positionnelle de PV pleins, qui ne pouvait pas dire QUELLE figurine
    #: portait quels PV. Conséquence mesurée : au recalage sur un segment ``[MODELS:]`` — qui
    #: donne les socles vivants mais pas leurs PV — la relève était reconstruite à PV pleins et
    #: SOIGNAIT les figurines entamées (`queue=[…, 1, 2, 4]` → `[…, 2, 5, 4]`). L'escouade 102 y
    #: survivait à 4 PV de dégâts pour 4 PV restants, et le contrôle « tir sur cible engagée »
    #: la comptait encore comme engageant sa cible. Indexer par socle supprime l'ambiguïté :
    #: recaler, c'est ne garder que les socles listés, jamais réinventer leurs PV.
    #:
    #: La figurine « front » (celle qui encaisse) est IMPLICITE : la première de l'ordre 06.02
    #: parmi les vivantes (cf. `_ordered_living_mids`). ``unit_hp[uid]`` en est le miroir scalaire,
    #: conservé pour l'invariant d'aliveness et ses nombreux lecteurs.
    #:
    #: ⚠️ Remplace `unit_hp_max_per_model: Dict[str, int]`, qui donnait à TOUTE figurine de
    #: l'escouade le `HP_MAX` de la datasheet de tête. Une escouade hétérogène était donc
    #: sous-évaluée : l'Intercessor 105 (`HP_MAX=2`) porte un Captain à 6 PV et un Ancient à 4,
    #: soit 20 PV côté moteur contre 14 côté analyzer. L'analyzer épuisait l'escouade six points
    #: trop tôt et la déclarait détruite — c'est le compteur « unités tuées à tort » de la
    #: section 2.8, et surtout un faux NÉGATIF pour tout contrôle qui filtre sur les unités
    #: vivantes (l'engagement du move, entre autres).
    #:
    #: Source : `[MODEL_TYPES:]` de l'entête d'épisode (datasheet par socle) + `HP_MAX` du
    #: registry. Journal sans `[MODEL_TYPES:]` (antérieur à cette clé) → file uniforme au
    #: `HP_MAX` d'escouade, c'est-à-dire exactement l'ancien comportement : donnée absente,
    #: jamais une composition supposée.
    unit_model_hp: Dict[str, Dict[str, int]] = field(default_factory=dict)
    #: `HP_MAX` de la datasheet d'ESCOUADE (registry). Ne sert plus qu'aux figurines dont la
    #: datasheet est inconnue — journal sans `[MODEL_TYPES:]`. C'est l'ancienne valeur unique,
    #: réduite à son seul usage légitime : un défaut de donnée, pas le cas courant.
    unit_hp_squad_max: Dict[str, int] = field(default_factory=dict)
    unit_player: Dict[str, int] = field(default_factory=dict)
    unit_positions: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    unit_types: Dict[str, str] = field(default_factory=dict)
    unit_move: Dict[str, int] = field(default_factory=dict)

    # Couche per-figurine (V11) : socles vivants par unité, maintenu frame-à-frame
    # depuis le segment [MODELS:] de chaque ligne. unit_id = préfixe de mid avant '#'.
    positions_by_model: Dict[str, Dict[str, Tuple[int, int]]] = field(default_factory=dict)
    # Escouades dont les socles connus ont été INVALIDÉS par une perte de figurine (le log ne
    # dit pas laquelle est tombée). Distingue « on n'a jamais su » de « on ne sait plus » : dans
    # le second cas l'ancre d'escouade se recalcule sans action de l'unité, et un écart avec la
    # position de départ loguée est du bruit d'ancre, pas une incohérence.
    models_invalidated: Set[str] = field(default_factory=set)
    #: Socles SURVIVANTS de la CIBLE, lus dans `[TARGET_MODELS:]` de la ligne courante et
    #: fusionnés dans `positions_by_model` au même rythme que `current_line_models` (décalage
    #: d'une ligne). C'est la seule donnée qui lève l'invalidation posée à la mort d'une
    #: figurine : `_apply_damage_and_handle_death` purge les socles de la cible parce que le
    #: journal ne dit pas LAQUELLE tombe — mais ce segment, lui, dit qui RESTE.
    current_line_target_models: Dict[str, Dict[str, Tuple[int, int]]] = field(default_factory=dict)
    # Socles listés SUR LA LIGNE COURANTE (nouvelles positions de l'unité qui agit) ;
    # positions_by_model garde encore l'état PRÉCÉDENT tant que la ligne n'est pas finie.
    current_line_models: Dict[str, Dict[str, Tuple[int, int]]] = field(default_factory=dict)
    # Base (shape, size) par unité, lue sur la ligne "Starting position ... base=".
    unit_base: Dict[str, Base] = field(default_factory=dict)
    # Volet VERTICAL de la couche per-figurine (§03.04) : hauteur du PLANCHER sous chaque socle,
    # en pouces, lue dans le même token `[MODELS:]` que la position (`z<hauteur>`). Jumeaux
    # exacts de `positions_by_model` / `current_line_models`, MÊME décalage d'une ligne : les
    # deux cartes sont lues ENSEMBLE par l'engagement 3D, et n'en décaler qu'une mesurerait une
    # figurine à l'altitude de sa case précédente.
    heights_by_model: Dict[str, Dict[str, float]] = field(default_factory=dict)
    current_line_heights: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # MODEL_HEIGHT par unité (borne haute de l'intervalle vertical, §01.04). Lue au MÊME endroit
    # que HP_MAX/MOVE — le registry, pas le log : c'est une stat d'unité constante.
    unit_model_height: Dict[str, float] = field(default_factory=dict)

    # Board
    wall_hexes: Set[Tuple[int, int]] = field(default_factory=set)
    # `objective_hexes` / `objective_controllers` ont disparu avec le recalcul du contrôle
    # d'objectif côté analyzer (par ancre, sans battle-shock). L'état 14.02 est celui du moteur,
    # lu dans la ligne `T{tour} OBJECTIVE CONTROL:` du step.log — cf. Replay.md §2.3.

    #: IDs de socles retirés de `unit_model_hp` par `_resync_living_models` (log DEAD ou [MODELS:]
    #: montrant les survivants) AVANT que la ligne d'attaque correspondante ne soit traitée.
    #: Utilisé par `_apply_damage_to_named_model` pour distinguer ce décalage d'ordonnancement
    #: (artifact log) d'une vraie divergence moteur/analyzer : si `alloc_model_id` est ici,
    #: le moteur a bien ciblé ce socle — il était vivant à l'allocation — et l'analyzer ne
    #: doit pas compter l'événement en `alloc_model_unknown`.
    #: Réinitialisé à chaque début d'épisode. Jamais alimenté par `_apply_damage_to_named_model`
    #: (kills explicites via attaque) : ceux-là doivent rester détectables en `alloc_model_unknown`.
    dead_model_ids_episode: Dict[str, Set[str]] = field(default_factory=dict)

    #: Positions des socles retirés par `_resync_living_models` (même artifact d'ordonnancement que
    #: `dead_model_ids_episode`, même portée épisode). Utilisé dans `freeze_select_targets` pour
    #: restituer la géométrie et l'effectif réels au Select Targets step :
    #:   § 1.2 — portée jugée sur les survivants POST-DEAD au lieu des socles vivants au ST step.
    #:   § 1.4 — effectif cible sous-évalué → [CLEAVE]/[BLAST] dés additionnels à 0 → faux CC_NB.
    #: Clé = unit_id ; valeur = {model_id: (col, row)}.
    #: Vidé par unité dès le premier gel de l'activation (freeze_select_targets → .pop()) pour ne
    #: pas contaminer les gels ultérieurs (positions de morts des tours précédents).
    dead_model_positions_episode: Dict[str, Dict[str, Tuple[int, int]]] = field(default_factory=dict)

    # Suivi morts
    unit_deaths: List = field(default_factory=list)
    # Contexte de la destruction d'une escouade : dead_id -> (attaquant, turn, phase).
    # Sert à ne pas compter comme « attaque sur unité morte » les attaques restantes de
    # LA MÊME activation qui a détruit la cible (excess attacks lost, 05 Attack sequence),
    # tout en gardant le contrôle pour une unité tierce attaquant un vrai cadavre.
    unit_kill_context: Dict[str, Tuple[str, int, str]] = field(default_factory=dict)
    line_number: int = 0
    dead_units_current_episode: Set[str] = field(default_factory=set)
    revived_units_current_episode: Set[str] = field(default_factory=set)

    # Historique de mouvement
    unit_movement_history: Dict[str, List] = field(default_factory=dict)

    # Séquences de tir/combat
    shot_sequence_counts: Dict = field(default_factory=dict)
    fight_sequence_counts: Dict = field(default_factory=dict)
    #: La CIBLE au Select Targets step — effectif ET géométrie, un seul `SelectTargetsFreeze` par
    #: activation (même clé que les compteurs ci-dessus). Cf. la docstring de ce type : la lire à
    #: la ligne courante donnerait l'état APRÈS les pertes déjà infligées par l'activation
    #: elle-même, donc un plafond trop bas ([BLAST] 24.05) et une géométrie d'après-coup (10.06).
    shot_sequence_target_models: Dict[Tuple[Any, ...], SelectTargetsFreeze] = field(default_factory=dict)
    fight_sequence_target_models: Dict[Tuple[Any, ...], SelectTargetsFreeze] = field(default_factory=dict)
    #: `unit_models_alive` tel qu'il était AVANT l'application des dégâts de la ligne courante.
    #: Les dégâts sont appliqués par `analyzer_core` en amont de l'aiguillage vers les handlers :
    #: à l'ouverture d'une séquence, la première ligne a déjà pu retirer une figurine de la cible.
    models_alive_pre_line: Dict[str, int] = field(default_factory=dict)
    #: JUMEAUX GÉOMÉTRIQUES de `models_alive_pre_line`, mêmes rythme et raison : vivacité, ancre
    #: et socles de CHAQUE unité avant les dégâts de la ligne courante. Ce sont les seules
    #: sources dont dispose un handler pour reconstituer l'état du Select Targets step — les
    #: cartes vives, elles, portent déjà les pertes de la ligne qu'il est en train de juger.
    unit_hp_pre_line: Dict[str, int] = field(default_factory=dict)
    unit_positions_pre_line: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    positions_by_model_pre_line: Dict[str, Dict[str, Tuple[int, int]]] = field(default_factory=dict)
    #: `stats['wounded_enemies']` avant les dégâts de la ligne courante, par joueur. Même famille
    #: que les trois ci-dessus : la priorité de ciblage se juge sur les blessés que le joueur
    #: VOYAIT en choisissant sa cible, pas sur ceux que son tir vient de faire ou d'achever.
    wounded_enemies_pre_line: Dict[int, Set[str]] = field(default_factory=dict)
    last_shoot_shooter_id: Optional[str] = None
    last_shoot_weapon: Optional[str] = None
    last_shoot_target_id: Optional[str] = None
    #: JUMEAU de `last_fight_shooters` — même rôle, même raison. Le tir était resté sans, et le
    #: défaut que la mêlée avait fermé y vivait encore : mesuré sur le run du 2026-08-11,
    #: 320 fausses « Shots over RNG_NB » sur 23 169 tirs.
    last_shoot_shooters: Tuple[str, ...] = ()
    #: Dernière unité dont un SHOT a déclenché un marqueur d'activation SHOOT (frontière
    #: d'activation 10.02). Réinitialisé à ``None`` en début de phase SHOOT et au changement
    #: de tour. Mis à jour uniquement sur les lignes SHOT (pas sur les actions non-tir).
    shoot_last_activator: Optional[str] = None
    last_fight_fighter_id: Optional[str] = None
    last_fight_weapon: Optional[str] = None
    #: Socles ayant frappé sur la dernière ligne de combat (`[SHOOTER_MODELS:]`). Entre dans la
    #: clé du compteur d'attaques PARCE QU'IL DÉTERMINE LE PLAFOND : sans lui, la somme de deux
    #: groupes (une escouade répartissant ses attaques entre deux cibles) était opposée au
    #: plafond d'un seul.
    last_fight_shooters: Tuple[str, ...] = ()
    combi_profile_usage: Dict = field(default_factory=dict)
    combi_conflicts_seen: Set = field(default_factory=set)

    # Marqueurs de phase / tour
    units_moved: Set[str] = field(default_factory=set)
    units_shot: Set[str] = field(default_factory=set)
    units_fled: Set[str] = field(default_factory=set)
    units_advanced: Set[str] = field(default_factory=set)
    units_fought: Set[str] = field(default_factory=set)
    charged_units_current_fight: Set[str] = field(default_factory=set)
    charged_units_fought: Set[str] = field(default_factory=set)
    units_moved_after_shooting_in_turn: Set[str] = field(default_factory=set)
    positions_at_turn_start: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    positions_at_move_phase_start: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    last_player: Optional[int] = None
    last_phase: Optional[str] = None
    #: Clé d'identité d'une phase pour la détection de double activation. DEUX formes, parce que
    #: deux grandeurs différentes identifient une phase : `(tour, phase, joueur)` hors combat,
    #: `(phase, fight_phase_seq_id, joueur)` en combat — un tour contient DEUX phases de combat
    #: (12.04), et le joueur de la ligne est celui de l'unité qui agit, pas celui de la phase.
    phase_activation_seen: Dict[PhaseActivationKey, Set[str]] = field(default_factory=dict)
    #: 12.02 : unités ayant DÉJÀ fait leur pile-in, par `(fight_phase_seq_id, joueur)`. Ensemble
    #: SÉPARÉ de `phase_activation_seen` : pile-in (12.02) et consolidation (12.07) sont deux
    #: étapes distinctes de la même phase, une unité fait légalement les deux, et les mélanger
    #: compterait chaque combat normal comme une double activation.
    pile_in_seen: Dict[Tuple[int, int], Set[str]] = field(default_factory=dict)
    reactive_activation_counts: Dict[Tuple[int, int, int], Dict[str, int]] = field(default_factory=dict)
    fight_phase_seq_id: int = 0
    # Points de victoire de l'épisode : recopiés du dernier instantané moteur, jamais calculés.
    episode_victory_points: Dict[int, int] = field(default_factory=dict)
    # L'épisode a-t-il livré au moins un instantané `OBJECTIVE CONTROL` / déclaré des objectifs ?
    # Les deux ensemble distinguent « scénario sans zone » (légitime) de « journal périmé ».
    objective_control_seen: bool = False
    objectives_declared: bool = False
    selected_choice_by_unit_source: Dict[str, Dict[str, str]] = field(default_factory=dict)

    def engagement_3d_kwargs(self) -> Dict[str, Any]:
        """Paire d'arguments verticaux de ``is_within_engine_engagement_zone`` (§03.04).

        Un seul point d'assemblage : ces valeurs vont TOUJOURS ensemble avec
        ``positions_by_model``/``unit_base``, et les recopier site par site rendait un oubli
        silencieux — un contrôle resté 2D ne lève pas, il rend juste un verdict faux sur un
        plateau à étages.

        Les hauteurs rendues sont celles d'AVANT la ligne courante, comme ``positions_by_model``
        dont elles sont le jumeau : c'est ce que mesurent les contrôles au départ d'un mouvement.
        Un appelant qui passe ``subject_models`` tiré de ``current_line_models`` (position
        d'ARRIVÉE) doit passer le ``subject_heights`` correspondant, tiré de
        ``current_line_heights`` — sinon il mesurerait une arrivée à l'altitude du départ.
        """
        return {
            "heights_by_model": self.heights_by_model,
            "unit_model_height": self.unit_model_height,
        }

    def freeze_select_targets(
        self,
        store: Dict[Tuple[Any, ...], SelectTargetsFreeze],
        key: Tuple[Any, ...],
        target_id: str,
        player: int,
        log_anchor: Optional[Tuple[int, int]] = None,
        alive_override: Optional[int] = None,
    ) -> SelectTargetsFreeze:
        """La cible de l'activation ``key``, figée à la PREMIÈRE ligne qui la nomme.

        POURQUOI UN GEL. Les dégâts d'une ligne sont appliqués par `analyzer_core` AVANT que le
        handler ne voie cette ligne : quand un contrôle s'exécute, la cible a déjà encaissé les
        pertes de l'attaque qu'il prétend juger. `_apply_damage_and_handle_death` purge ses socles
        (`positions_by_model`), et si elle meurt la retire de `unit_hp` et `unit_positions`.

        POURQUOI PAR ACTIVATION, ET NON PAR LIGNE. Ciblage et effectif sont tranchés par le moteur
        au Select Targets step (`_shoot_engagement_blocks_target`), une fois pour l'activation
        entière, avant d'en résoudre la moindre attaque. Un gel par ligne laisserait la deuxième
        attaque juger sur les pertes de la première — même défaut, un tir plus tard.

        APPELÉ HORS DE TOUTE BRANCHE DE RÉSOLUTION D'ARME, à la première ligne de l'activation :
        une arme dont le NB ne se résout pas (`parse_error`) tue quand même, et si elle avait
        empêché le gel, l'arme suivante aurait hérité de l'état d'APRÈS ses pertes.

        ``log_anchor`` (ancre portée par la ligne) prime sur l'ancre en cache, périmée dès que
        l'escouade perd la figurine qui la portait. L'effectif, lui, LÈVE s'il est inconnu : une
        cible nommée par le journal a toujours été comptée.
        """
        frozen = store.get(key)  # get allowed
        if frozen is None:
            # § 1.2 / 1.4 — artifact d'ordonnancement DEAD-before-SHOOT : les DEAD lines (reason=
            # combat) sont flushées dans le log AVANT la ligne d'attaque qui les a causées. Chaque
            # DEAD line appelle `_resync_living_models`, qui retire le socle de `unit_model_hp` et
            # de `positions_by_model` (via `current_line_models`) AVANT que le gel ci-dessous n'ait
            # eu lieu. Résultat : `positions_by_model_pre_line` et `models_alive_pre_line` ne voient
            # que les survivants POST-DEAD, alors que le moteur avait ALL models vivants au Select
            # Targets step. Conséquences mesurées :
            #   § 1.2 — portée jugée uniquement sur le survivant le plus éloigné → faux out_of_range.
            #   § 1.4 — effectif < 5 → [CLEAVE] dés additionnels à 0 → faux fight_over_cc_nb.
            # Fix : `_resync_living_models` accumule les positions des socles retirés dans
            # `dead_model_positions_episode` ; on les réintègre ici, puis on vide le dict pour cette
            # unité (pop) afin que seule l'activation courante en bénéficie, et non les suivantes
            # (qui sinon verraient les morts des tours précédents à des positions périmées).
            _extra = self.dead_model_positions_episode.pop(target_id, {})  # pop : une seule activation
            _models_raw = self.positions_by_model_pre_line.get(target_id)  # get allowed
            if _extra:
                _models_full: Optional[Dict[str, Tuple[int, int]]] = {**_extra, **(_models_raw or {})}
            else:
                _models_full = _models_raw
            _computed_alive = require_key(self.models_alive_pre_line, target_id) + len(_extra)
            # [TARGET_DECL:N] loggé par le moteur au SelectTargets step : prend le pas sur la
            # valeur reconstruite quand elle est disponible (logs récents). Sans lui, l'analyzer
            # repose sur `models_alive_pre_line` + `dead_model_positions_episode`, qui peuvent
            # diverger de l'état moteur après fix 2 (purge des entrées périmées).
            frozen = SelectTargetsFreeze(
                models_alive=alive_override if alive_override is not None else _computed_alive,
                anchor=log_anchor if log_anchor is not None else self.unit_positions_pre_line.get(target_id),  # get allowed
                hp=self.unit_hp_pre_line.get(target_id),  # get allowed
                models=_models_full,
                wounded_enemies=frozenset(
                    require_key(self.wounded_enemies_pre_line, int(player))
                ),
            )
            store[key] = frozen
        return frozen

    def engagement_maps(
        self,
        frozen: SelectTargetsFreeze,
        target_id: str,
    ) -> Tuple[
        Dict[str, Tuple[int, int]], Dict[str, int], Dict[str, Dict[str, Tuple[int, int]]]
    ]:
        """``(unit_positions, unit_hp, positions_by_model)`` où la CIBLE est celle de ``frozen``.

        C'est la forme que consomment les contrôles d'engagement (10.06, 04.02, alternance 12.04)
        et de portée : ils énumèrent des cartes complètes. Les autres unités y restent VIVES —
        une activation n'inflige de pertes qu'à sa cible, et le reste du plateau doit rester au
        plus frais.

        Sans ce recalage, une cible morte disparaît de l'énumération des ennemis et le tireur est
        déclaré « non engagé avec sa cible » — mesuré le 2026-08-12 (E422, un pistolet tuant à
        bout portant l'unité avec laquelle il était engagé), troisième fois que ce dépôt juge une
        géométrie sur un état postérieur à la décision (mêlée 2026-07-24, portée 2026-08-12).
        """
        anchor, hp, models = frozen.anchor, frozen.hp, frozen.models
        positions = dict(self.unit_positions)
        hps = dict(self.unit_hp)
        models_by_unit = dict(self.positions_by_model)
        # Absence figée = absence restituée : la cible est d'abord RETIRÉE des trois cartes vives
        # (elles ne portent que l'après), puis rendue à partir du seul gel. Ce qui n'a pas été figé
        # au Select Targets step ne réapparaît donc jamais.
        positions.pop(target_id, None)
        hps.pop(target_id, None)
        models_by_unit.pop(target_id, None)
        # TOUT OU RIEN, et c'est la VIVACITÉ qui commande. Une cible sans PV au Select Targets step
        # (déjà détruite par une activation antérieure — le journal contient bien ces lignes, cf.
        # le contrôle `shoot_at_dead_unit`) n'est pas mesurable : lui rendre son ancre sans ses PV
        # la faisait ressortir « unité sans données » à chaque ligne de l'activation, une erreur de
        # parsing que les cartes vives ne produisaient pas — elles ne la portaient plus du tout.
        if hp is None:
            return positions, hps, models_by_unit
        hps[target_id] = hp
        if anchor is not None:
            positions[target_id] = anchor
        if models is not None:
            models_by_unit[target_id] = models
        return positions, hps, models_by_unit


def make_initial_state(stats: Dict) -> "AnalyzerState":
    """Crée un AnalyzerState vierge en début de parse_step_log."""
    return AnalyzerState(stats=stats)
