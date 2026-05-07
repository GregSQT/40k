"""
episode_handler.py — gestion des lignes EPISODE START et EPISODE END.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai.analyzer_state import AnalyzerState
    from ai.analyzer_config import AnalyzerConfig


PLAYER_ONE_ID = 1
PLAYER_TWO_ID = 2


def handle_episode_start(state: "AnalyzerState", config: "AnalyzerConfig", line: str) -> None:
    """Traite une ligne '=== EPISODE N START ==='."""
    from ai.analyzer import parse_timestamp_to_seconds

    stats = state.stats

    if state.current_episode:
        stats['episodes_without_end'].append({
            'episode_num': state.current_episode_num,
            'actions': state.episode_actions,
            'turn': state.episode_turn,
            'last_line': state.current_episode[-1][:100] if state.current_episode else 'N/A'
        })

        if stats['current_episode_deaths']:
            stats['death_orders'].append(tuple(stats['current_episode_deaths']))

        stats['episode_lengths'].append((state.current_episode_num, state.episode_actions))
        if state.episode_turn > 0:
            stats['turns_distribution'][state.episode_turn] += 1

    state.current_episode = []
    stats['total_episodes'] += 1
    state.current_episode_num = stats['total_episodes']
    state.episode_turn = 0
    state.episode_actions = 0
    state.episode_step_index = 0
    state.episode_start_time = parse_timestamp_to_seconds(line)
    stats['current_episode_deaths'] = []
    stats['wounded_enemies'] = {1: set(), 2: set()}
    state.unit_hp = {}
    state.unit_player = {}
    state.unit_positions = {}
    state.unit_types = {}
    state.unit_move = {}
    state.wall_hexes = set()
    state.objective_hexes = {}
    state.objective_controllers = {}
    state.positions_at_turn_start = {}
    state.positions_at_move_phase_start = {}
    state.dead_units_current_episode = set()
    state.revived_units_current_episode = set()
    state.current_scenario = 'Unknown'
    state.units_moved = set()
    state.units_shot = set()
    state.units_fled = set()
    state.units_advanced = set()
    state.units_fought = set()
    state.charged_units_current_fight = set()
    state.charged_units_fought = set()
    state.units_moved_after_shooting_in_turn = set()
    state.unit_movement_history = {}
    state.shot_sequence_counts = {}
    state.fight_sequence_counts = {}
    state.last_fight_fighter_id = None
    state.last_fight_weapon = None
    state.combi_profile_usage = {}
    state.combi_conflicts_seen = set()
    state.unit_deaths = []
    state.phase_activation_seen = {}
    stats['objective_control_history'][state.current_episode_num] = []
    state.last_objective_snapshot = None
    state.seen_turn_player = set()
    state.episode_victory_points = {PLAYER_ONE_ID: 0, PLAYER_TWO_ID: 0}
    state.scored_turns = set()
    state.primary_objective_configs = []
    state.selected_choice_by_unit_source = {}
