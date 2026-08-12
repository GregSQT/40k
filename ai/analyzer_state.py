"""
AnalyzerState — état partagé entre les handlers de parse_step_log.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from ai.analyzer_perfig import Base

#: cf. `AnalyzerState.phase_activation_seen`.
PhaseActivationKey = Union[Tuple[int, str, int], Tuple[str, int, int]]


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
    #: Effectif de la CIBLE au Select Targets step, figé à l'OUVERTURE de chaque séquence de
    #: tir/combat (même clé que les compteurs ci-dessus). C'est la donnée qu'exigent [BLAST]
    #: 24.05 et [CLEAVE] 24.06 : « every five models that were in the target unit IN THE SELECT
    #: TARGETS STEP ». Le lire à la ligne courante donnerait l'effectif APRÈS les pertes déjà
    #: infligées par la séquence elle-même — donc un plafond trop bas, et le faux positif de
    #: retour dès que la cible franchit un multiple de 5 en cours d'activation.
    shot_sequence_target_models: Dict = field(default_factory=dict)
    fight_sequence_target_models: Dict = field(default_factory=dict)
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
    #: Géométrie de la CIBLE au Select Targets step, figée à la PREMIÈRE ligne de chaque
    #: activation : `(clé) -> (ancre, PV de la figurine front, socles)`. Jumeau exact de
    #: `shot_sequence_target_models` / `fight_sequence_target_models`, qui figent l'EFFECTIF de la
    #: même cible au même instant et pour la même raison (24.05, 24.06). Clé préfixée par la
    #: phase : les deux familles de clés n'ont ni la même forme ni la même durée de vie.
    activation_target_geometry: Dict[
        Tuple[Any, ...],
        Tuple[Optional[Tuple[int, int]], Optional[int], Optional[Dict[str, Tuple[int, int]]]]
    ] = field(default_factory=dict)
    last_shoot_shooter_id: Optional[str] = None
    last_shoot_weapon: Optional[str] = None
    last_shoot_target_id: Optional[str] = None
    #: JUMEAU de `last_fight_shooters` — même rôle, même raison. Le tir était resté sans, et le
    #: défaut que la mêlée avait fermé y vivait encore : mesuré sur le run du 2026-08-11,
    #: 320 fausses « Shots over RNG_NB » sur 23 169 tirs.
    last_shoot_shooters: Tuple[str, ...] = ()
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

    def select_targets_engagement_maps(
        self,
        key: Tuple[Any, ...],
        target_id: str,
        log_anchor: Optional[Tuple[int, int]] = None,
    ) -> Tuple[
        Dict[str, Tuple[int, int]], Dict[str, int], Dict[str, Dict[str, Tuple[int, int]]]
    ]:
        """``(unit_positions, unit_hp, positions_by_model)`` avec la CIBLE telle qu'elle était au
        Select Targets step de l'activation ``key``.

        POURQUOI CETTE MÉTHODE EXISTE. Les dégâts d'une ligne sont appliqués par `analyzer_core`
        AVANT que le handler ne voie cette ligne : quand un contrôle d'engagement s'exécute, la
        cible a déjà encaissé les pertes de l'attaque qu'il prétend juger. `_apply_damage_and_
        handle_death` purge alors ses socles (`positions_by_model`), et si elle meurt la retire de
        `unit_hp` et `unit_positions`. Une cible morte disparaît de l'énumération des ennemis :
        le tireur est déclaré « non engagé avec sa cible » — mesuré le 2026-08-12 (E422, un
        pistolet tuant à bout portant l'unité avec laquelle il était engagé), et c'est la
        troisième fois que ce dépôt juge une géométrie sur un état postérieur à la décision
        (mêlée 2026-07-24, portée 2026-08-12).

        POURQUOI PAR ACTIVATION, ET NON PAR LIGNE. 10.06 et 04.02 sont des règles de CIBLAGE :
        le moteur les tranche au Select Targets step (`_shoot_engagement_blocks_target`), une
        fois pour l'activation entière, avant d'en résoudre la moindre attaque. Un gel par ligne
        laisserait la deuxième attaque d'une activation juger sur les pertes de la première —
        même défaut, un tir plus tard. C'est déjà la raison d'être des gels d'effectif jumeaux
        (`shot_sequence_target_models`, [BLAST] 24.05).

        Les autres unités restent lues sur les cartes VIVES : une activation n'inflige de pertes
        qu'à sa cible, et le reste du plateau doit rester au plus frais. ``log_anchor`` (ancre de
        la cible portée par la ligne) prime sur l'ancre en cache, périmée dès que l'escouade perd
        la figurine qui la portait.
        """
        frozen = self.activation_target_geometry.get(key)  # get allowed
        if frozen is None:
            frozen = (
                log_anchor if log_anchor is not None else self.unit_positions_pre_line.get(target_id),  # get allowed
                self.unit_hp_pre_line.get(target_id),  # get allowed
                self.positions_by_model_pre_line.get(target_id),  # get allowed
            )
            self.activation_target_geometry[key] = frozen
        anchor, hp, models = frozen
        positions = dict(self.unit_positions)
        hps = dict(self.unit_hp)
        models_by_unit = dict(self.positions_by_model)
        # TOUT OU RIEN, et c'est la VIVACITÉ qui commande. Une cible sans PV au Select Targets step
        # (déjà détruite par une activation antérieure — le journal contient bien ces lignes, cf.
        # le contrôle `shoot_at_dead_unit`) n'est pas mesurable : lui rendre son ancre sans ses PV
        # la faisait ressortir « unité sans données » à chaque ligne de l'activation, une erreur de
        # parsing que les cartes vives ne produisaient pas — elles ne la portaient plus du tout.
        if hp is None:
            for carte in (positions, hps, models_by_unit):
                carte.pop(target_id, None)
            return positions, hps, models_by_unit
        hps[target_id] = hp
        # Absence figée = absence restituée : des socles inconnus au Select Targets step ne doivent
        # pas réapparaître depuis la carte vive (elle ne porte que l'après).
        for carte, valeur in ((positions, anchor), (models_by_unit, models)):
            if valeur is None:
                carte.pop(target_id, None)
            else:
                carte[target_id] = valeur
        return positions, hps, models_by_unit


def make_initial_state(stats: Dict) -> "AnalyzerState":
    """Crée un AnalyzerState vierge en début de parse_step_log."""
    return AnalyzerState(stats=stats)
