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
    episode_turn: int = 0
    episode_actions: int = 0
    last_turn: int = 0
    episode_start_time: Optional[int] = None

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
    # MODEL_HEIGHT (POUCES) par unité, lu dans le registry — borne haute de l'intervalle
    # vertical d'une figurine, exigée par le gate d'engagement 3D du moteur.
    unit_model_height: Dict[str, float] = field(default_factory=dict)

    # Couche per-figurine (V11) : socles vivants par unité, maintenu frame-à-frame
    # depuis le segment [MODELS:] de chaque ligne. unit_id = préfixe de mid avant '#'.
    positions_by_model: Dict[str, Dict[str, Tuple[int, int]]] = field(default_factory=dict)
    # Hauteur du plancher (POUCES) sous chaque socle, lue sur le même segment [MODELS:].
    # Séparée des positions parce que toute la couche per-figurine est HORIZONTALE : l'altitude
    # ne sert qu'au gate vertical de l'engagement (§03.04, 2" horiz ET 5" vert).
    #
    # MÊME cycle de vie en deux fronts que `positions_by_model` / `current_line_models`, et pour
    # la même raison : plusieurs contrôles mesurent l'engagement à l'ancre d'AVANT le mouvement
    # (`position_override=start_pos`). Fusionner les deux fronts leur donnerait l'altitude
    # d'APRÈS à une position d'AVANT — une unité qui descend d'une ruine serait évaluée à son
    # ancre de ruine avec sa hauteur de sol, ce qui INVERSE le gate vertical.
    heights_by_model: Dict[str, Dict[str, float]] = field(default_factory=dict)
    current_line_heights: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # Socles listés SUR LA LIGNE COURANTE (nouvelles positions de l'unité qui agit) ;
    # positions_by_model garde encore l'état PRÉCÉDENT tant que la ligne n'est pas finie.
    current_line_models: Dict[str, Dict[str, Tuple[int, int]]] = field(default_factory=dict)
    # Base (shape, size) par unité, lue sur la ligne "Starting position ... base=".
    unit_base: Dict[str, Base] = field(default_factory=dict)

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

    def _engagement_3d_kwargs(self, heights: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
        from ai.analyzer import _get_engagement_zone_vertical_for_analyzer

        return {
            "heights_by_model": heights,
            "unit_model_height": self.unit_model_height,
            "vertical_zone_inches": _get_engagement_zone_vertical_for_analyzer(),
        }

    def engagement_3d_kwargs(self) -> Dict[str, Any]:
        """Trio d'arguments verticaux de ``is_within_engine_engagement_zone`` (§03.04), aux
        positions COURANTES (celles de la ligne en cours de traitement).

        Un seul point d'assemblage : ces trois valeurs vont toujours ensemble, et les recopier
        site par site rendait un oubli silencieux — un contrôle resté 2D ne lève pas, il rend
        juste un verdict faux sur un plateau à étages.
        """
        merged = dict(self.heights_by_model)
        merged.update(self.current_line_heights)
        return self._engagement_3d_kwargs(merged)

    def engagement_3d_kwargs_at_start(self) -> Dict[str, Any]:
        """Idem, mais aux altitudes d'AVANT la ligne courante.

        À utiliser avec ``position_override`` = ancre de DÉPART : mesurer une position d'avant le
        mouvement avec l'altitude d'après inverse le gate vertical (unité qui descend d'une ruine
        évaluée à son ancre de ruine, mais à hauteur de sol).
        """
        return self._engagement_3d_kwargs(self.heights_by_model)


def make_initial_state(stats: Dict) -> "AnalyzerState":
    """Crée un AnalyzerState vierge en début de parse_step_log."""
    return AnalyzerState(stats=stats)
