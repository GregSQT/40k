"""
AnalyzerState — état partagé entre les handlers de parse_step_log.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ai.analyzer_perfig import Base


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
    #: PV pleins des figurines qui deviendront « front » APRÈS l'actuelle, dans l'ordre où
    #: elles encaisseront (06.02 : les non-CHARACTER d'abord, les CHARACTER en dernier).
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
    unit_model_hp_queue: Dict[str, List[int]] = field(default_factory=dict)
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
    last_shoot_shooter_id: Optional[str] = None
    last_shoot_weapon: Optional[str] = None
    last_shoot_target_id: Optional[str] = None
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
    phase_activation_seen: Dict[Tuple[int, str, int], Set[str]] = field(default_factory=dict)
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


def make_initial_state(stats: Dict) -> "AnalyzerState":
    """Crée un AnalyzerState vierge en début de parse_step_log."""
    return AnalyzerState(stats=stats)
