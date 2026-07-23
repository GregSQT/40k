"""
AnalyzerState — état partagé entre les handlers de parse_step_log.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class AnalyzerState:
    # Stats globales (référence partagée, pas une copie)
    stats: Dict

    # Suivi épisode
    current_episode: List = field(default_factory=list)
    current_episode_num: int = 0
    current_scenario: str = "Unknown"
    episode_turn: int = 0
    episode_actions: int = 0
    last_turn: int = 0
    episode_start_time: Optional[int] = None
    episode_step_index: int = 0

    # Suivi unités
    # Modèle HP par-figurine (05 Attack sequence) : unit_hp[uid] = PV de la figurine
    # "front" en cours d'endommagement ; unit_models_alive[uid] = nb de figurines vivantes ;
    # unit_hp_max_per_model[uid] = PV_MAX d'une figurine (registry). Invariant conservé :
    # uid présent dans unit_hp avec valeur > 0 ⟺ escouade vivante (≥1 figurine).
    unit_hp: Dict[str, int] = field(default_factory=dict)
    unit_models_alive: Dict[str, int] = field(default_factory=dict)
    unit_hp_max_per_model: Dict[str, int] = field(default_factory=dict)
    unit_player: Dict[str, int] = field(default_factory=dict)
    unit_positions: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    unit_types: Dict[str, str] = field(default_factory=dict)
    unit_move: Dict[str, int] = field(default_factory=dict)

    # Couche per-figurine (V11) : socles vivants par unité, maintenu frame-à-frame
    # depuis le segment [MODELS:] de chaque ligne. unit_id = préfixe de mid avant '#'.
    positions_by_model: Dict[str, Dict[str, Tuple[int, int]]] = field(default_factory=dict)
    # Socles listés SUR LA LIGNE COURANTE (nouvelles positions de l'unité qui agit) ;
    # positions_by_model garde encore l'état PRÉCÉDENT tant que la ligne n'est pas finie.
    current_line_models: Dict[str, Dict[str, Tuple[int, int]]] = field(default_factory=dict)
    # Base (shape, size) par unité, lue sur la ligne "Starting position ... base=".
    unit_base: Dict[str, Tuple[str, object]] = field(default_factory=dict)

    # Board
    wall_hexes: Set[Tuple[int, int]] = field(default_factory=set)
    objective_hexes: Dict[int, Set[Tuple[int, int]]] = field(default_factory=dict)
    objective_controllers: Dict[int, Optional[int]] = field(default_factory=dict)

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
    last_objective_snapshot: Optional[Dict[int, Dict[str, Any]]] = None
    seen_turn_player: Set[Tuple[int, int]] = field(default_factory=set)
    episode_victory_points: Dict[int, int] = field(default_factory=dict)
    scored_turns: Set[Tuple[str, int, int]] = field(default_factory=set)
    primary_objective_configs: List[Dict[str, Any]] = field(default_factory=list)
    selected_choice_by_unit_source: Dict[str, Dict[str, str]] = field(default_factory=dict)


def make_initial_state(stats: Dict) -> "AnalyzerState":
    """Crée un AnalyzerState vierge en début de parse_step_log."""
    return AnalyzerState(stats=stats)
