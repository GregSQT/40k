import json
from pathlib import Path
from typing import Dict, Optional

import pytest

import ai.analyzer as an


def test_max_dice_value_valid_and_invalid() -> None:
    assert an.max_dice_value(3, "ctx") == 3
    assert an.max_dice_value("D6+1", "ctx") == 7
    with pytest.raises(TypeError, match=r"Invalid dice value type"):
        an.max_dice_value(1.5, "ctx")
    with pytest.raises(ValueError, match=r"Unsupported dice expression"):
        an.max_dice_value("D8", "ctx")


def _write_terrain(tmp_path: Path, filename: str, areas: list) -> Path:
    """Terrain sous config/board/44x60x5/terrain/ (contrat board_ref de V11 T4)."""
    terrain_dir = tmp_path / "config" / "board" / "44x60x5" / "terrain"
    terrain_dir.mkdir(parents=True, exist_ok=True)
    path = terrain_dir / filename
    path.write_text(json.dumps({"terrain_id": "t", "terrain": areas}), encoding="utf-8")
    return path


def test_resolve_scenario_path_and_objective_maps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """V11 T6 : la table nom->id vient du TERRAIN (areas "objective": true), plus du scénario.

    T3/T4 ont fait des terrains la source UNIQUE des objectifs (14.01/14.02) ; les clés legacy
    'objectives'/'objectives_ref' sont rejetées par le moteur. Ce test encode le contrat actuel
    (il échouait avant la migration de `_get_objective_name_to_id_map`).
    """
    monkeypatch.setattr(an, "project_root", str(tmp_path))
    _write_terrain(tmp_path, "terrain-train-01.json", [
        {"id": "wall_a", "name": "mur A", "hexes": []},                      # pas un objectif
        {"id": "rect_b_nw_OK", "name": "alpha", "objective": True, "hexes": []},
        {"id": "rect_b_ne_OK", "name": "beta", "objective": True, "hexes": []},
    ])
    scenario = tmp_path / "scenario_test.json"
    scenario.write_text(
        '{"board_ref":"44x60x5","terrain_ref":"terrain-train-01.json","primary_objectives":["obj1"]}',
        encoding="utf-8",
    )
    assert an._resolve_scenario_path("scenario_test") == str(scenario)

    an._scenario_objective_name_to_id_cache.clear()
    mapping = an._get_objective_name_to_id_map("scenario_test")
    # Id positionnel (1..N) dans l'ordre de déclaration du terrain ; les areas non-objectif
    # sont ignorées. Le NOM est la clé d'appariement avec la ligne "Objectives:" de step.log.
    assert mapping == {"alpha": 1, "beta": 2}

    an._scenario_primary_objective_ids_cache.clear()
    primary_ids = an._get_primary_objective_ids_for_scenario("scenario_test")
    assert primary_ids == ["obj1"]


def test_get_objective_name_to_id_map_legacy_scenario_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Un scénario au contrat LEGACY (objectives_ref, sans terrain_ref) -> erreur explicite.

    Remplace l'ancien test `..._via_objectives_ref` : ce chemin n'existe plus (le dossier
    config/board/<board>/objectives/ a été supprimé en T3). Pas de fallback silencieux.
    """
    monkeypatch.setattr(an, "project_root", str(tmp_path))
    scenario = tmp_path / "scenario_ref.json"
    scenario.write_text('{"objectives_ref":"demo"}', encoding="utf-8")

    an._scenario_objective_name_to_id_cache.clear()
    with pytest.raises(ValueError, match=r"no valid 'terrain_ref'"):
        an._get_objective_name_to_id_map("scenario_ref")


def test_get_objective_name_to_id_map_terrain_without_objective_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Piège documenté (T4) : un terrain sans area "objective": true -> erreur, pas liste vide."""
    monkeypatch.setattr(an, "project_root", str(tmp_path))
    _write_terrain(tmp_path, "terrain-flat.json", [{"id": "wall_a", "name": "mur A", "hexes": []}])
    scenario = tmp_path / "scenario_noobj.json"
    scenario.write_text(
        '{"board_ref":"44x60x5","terrain_ref":"terrain-flat.json"}', encoding="utf-8"
    )

    an._scenario_objective_name_to_id_cache.clear()
    with pytest.raises(ValueError, match=r'declares no area with "objective": true'):
        an._get_objective_name_to_id_map("scenario_noobj")


def test_resolve_scenario_path_skips_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """V11 T6 : l'archive pré-V11 de T4 ne doit JAMAIS masquer un scénario vif.

    T4 a déposé la banque pré-V11 sous `scenarios/_archive_pre_v11/`, DANS l'arbre parcouru par
    `_resolve_scenario_path` -> `Ambiguous scenario path`. La marche élague les dossiers _archive*.
    """
    monkeypatch.setattr(an, "project_root", str(tmp_path))
    live = tmp_path / "config" / "agents" / "CoreAgent" / "scenarios" / "training"
    live.mkdir(parents=True)
    (live / "scenario_dup.json").write_text('{"board_ref":"44x60x5"}', encoding="utf-8")

    archived = tmp_path / "config" / "agents" / "CoreAgent" / "scenarios" / "_archive_pre_v11" / "training_save"
    archived.mkdir(parents=True)
    (archived / "scenario_dup.json").write_text('{"objectives_ref":"legacy"}', encoding="utf-8")

    assert an._resolve_scenario_path("scenario_dup") == str(live / "scenario_dup.json")


def test_calculate_primary_objective_points_and_invalid_condition() -> None:
    control = {1: {"controller": 1}, 2: {"controller": 2}, 3: {"controller": 1}}
    cfg = {
        "scoring": {
            "max_points_per_turn": 5,
            "rules": [
                {"condition": "control_at_least_one", "points": 2},
                {"condition": "control_at_least_two", "points": 2},
                {"condition": "control_more_than_opponent", "points": 2},
            ],
        }
    }
    assert an._calculate_primary_objective_points(control, cfg, player_id=1) == 5
    cfg["scoring"]["rules"] = [{"condition": "unknown", "points": 1}]
    with pytest.raises(ValueError, match=r"Unsupported primary objective condition"):
        an._calculate_primary_objective_points(control, cfg, player_id=1)


def test_unit_hp_and_damage_helpers() -> None:
    stats = {
        "parse_errors": [],
        "damage_missing_unit_hp": {1: 0, 2: 0},
        "first_error_lines": {"damage_missing_unit_hp": {1: None, 2: None}},
        "wounded_enemies": {1: set(), 2: set()},
        "current_episode_deaths": [],
    }
    unit_hp = {"u1": 3, "u2": 1}
    unit_types = {"u2": "Termagant"}
    unit_positions = {"u2": (1, 1)}
    unit_deaths = []
    dead = set()

    assert an._get_unit_hp_value(unit_hp, "u1", context="ctx") == 3
    assert an._get_unit_hp_value(
        unit_hp,
        "missing",
        stats=stats,
        current_episode_num=1,
        turn=1,
        phase="move",
        line_text="x",
        context="ctx",
    ) is None
    assert len(stats["parse_errors"]) == 1

    an._apply_damage_and_handle_death(
        target_id="missing",
        damage=1,
        player=1,
        turn=1,
        phase="shoot",
        line_number=10,
        current_episode_num=1,
        line_text="line",
        dead_units_current_episode=dead,
        unit_hp=unit_hp,
        unit_types=unit_types,
        unit_positions=unit_positions,
        unit_deaths=unit_deaths,
        stats=stats,
    )
    assert stats["damage_missing_unit_hp"][1] == 1

    an._apply_damage_and_handle_death(
        target_id="u2",
        damage=2,
        player=1,
        turn=1,
        phase="shoot",
        line_number=11,
        current_episode_num=1,
        line_text="line2",
        dead_units_current_episode=dead,
        unit_hp=unit_hp,
        unit_types=unit_types,
        unit_positions=unit_positions,
        unit_deaths=unit_deaths,
        stats=stats,
    )
    assert "u2" in dead
    assert "u2" not in unit_hp
    assert "u2" not in unit_positions


def test_reappearance_and_movement_history_helpers() -> None:
    stats = {
        "parse_errors": [],
        "unit_revived": {1: 0, 2: 0},
        "first_error_lines": {"unit_revived": {1: None, 2: None}},
    }
    unit_hp = {"u1": 2}
    unit_player = {"u1": 1}
    dead = {"u1"}
    revived = set()
    an._track_unit_reappearance("u1", unit_hp, unit_player, dead, revived, stats, 1, "line")
    assert stats["unit_revived"][1] == 1
    assert "u1" in revived

    unit_positions = {"u1": (1, 1)}
    history = {"u1": [{"position": (2, 2)}]}
    assert an._get_latest_position_from_history("u1", unit_positions, history) == (2, 2)
    with pytest.raises(ValueError, match=r"Movement history is empty"):
        an._get_latest_position_from_history("u1", unit_positions, {"u1": []})


def test_geometry_and_los_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(an.hex_to_pixel(1, 2), tuple)
    assert an.line_segments_intersect((0, 0), (2, 2), (0, 2), (2, 0)) is True
    assert an.line_segments_intersect((0, 0), (1, 0), (0, 1), (1, 1)) is False
    points = an.get_hex_points(0.0, 0.0)
    assert len(points) == 9
    assert an.line_passes_through_hex((0.0, 0.0), (100.0, 0.0), 0, 0) is True

    class _Cfg:
        @staticmethod
        def get_board_size():
            return (4, 3)

    monkeypatch.setattr("config_loader.get_config_loader", lambda: _Cfg())
    walls = an._get_los_wall_hexes(set())
    assert (1, 2) in walls and (3, 2) in walls

    monkeypatch.setattr(
        "engine.hex_utils.compute_los_state",
        lambda *args, **kwargs: (0.7, True),
    )
    assert an.has_line_of_sight(1, 1, 2, 2, set()) is True


def test_adjacency_and_position_cache_helpers() -> None:
    assert an.is_adjacent(1, 1, 2, 1) is True
    assert an.parse_timestamp_to_seconds("[01:02:03] line") == 3723
    assert an.parse_timestamp_to_seconds("line") is None

    unit_player = {"e1": "2", "a1": 1}
    unit_positions = {"e1": (2, 1), "a1": (1, 1)}
    unit_hp = {"e1": 1, "a1": 1}
    assert an.is_adjacent_to_enemy(1, 1, unit_player, unit_positions, unit_hp, player=1) is True
    assert an.is_hex_anchor_adjacent_to_enemy(1, 1, unit_player, unit_positions, unit_hp, player=1) is True
    assert an.is_within_engine_engagement_zone("a1", unit_player, unit_positions, unit_hp, engagement_zone=1) is True
    unit_positions["e1"] = (3, 1)
    assert an.is_hex_anchor_adjacent_to_enemy(1, 1, unit_player, unit_positions, unit_hp, player=1) is False
    assert an.is_within_engine_engagement_zone("a1", unit_player, unit_positions, unit_hp, engagement_zone=2) is True
    unit_positions["e1"] = (2, 1)
    assert an._build_enemy_adjacent_hexes(unit_positions, unit_player, unit_hp, player=1)
    occ = an._build_occupied_positions(unit_positions, unit_hp, exclude_unit_id="a1")
    assert (2, 1) in occ

    path_len = an._bfs_shortest_path_length(1, 1, 3, 1, 5, set(), set(), set())
    assert path_len is not None

    stats = {"action_phase_accuracy": {}, "first_error_lines": {"action_phase_mismatch": {}}}
    an._track_action_phase_accuracy(stats, "move", "SHOOT", 1, "line")
    assert stats["action_phase_accuracy"]["move"]["wrong"] == 1

    enemies = an.get_adjacent_enemies(1, 1, unit_player, unit_positions, unit_hp, {"e1": "x"}, player=1)
    assert "e1" in enemies
    assert an.is_engaged("a1", unit_player, unit_positions, unit_hp) is True

    cache = {}
    an._position_cache_set(cache, "u1", 3, 4)
    assert cache["u1"] == (3, 4)
    an._position_cache_remove(cache, "u1")
    assert "u1" not in cache


def test_objective_control_snapshot() -> None:
    objective_hexes = {1: {(1, 1)}}
    objective_controllers: Dict[int, Optional[int]] = {1: None}
    unit_positions = {"u1": (1, 1), "u2": (2, 2)}
    unit_player = {"u1": 1, "u2": 2}
    unit_types = {"u1": "A", "u2": "B"}

    class _Registry:
        units = {"A": {"OC": 2}, "B": {"OC": 1}}

    snap = an._calculate_objective_control_snapshot(
        objective_hexes, objective_controllers, unit_positions, unit_player, unit_types, _Registry()
    )
    assert snap[1]["player_1_oc"] == 2
    assert snap[1]["controller"] == 1


@pytest.mark.parametrize(
    "fn_name,line,expected",
    [
        ("parse_step_timings_from_debug", "STEP_TIMING episode=1 step_index=2 duration_s=0.123 step_calls=3", (1, 2, 0.123, 3)),
        ("parse_predict_timings_from_debug", "PREDICT_TIMING episode=1 step_index=2 duration_s=0.123", (1, 2, 0.123)),
        (
            "parse_cascade_timings_from_debug",
            "CASCADE_TIMING episode=1 cascade_num=2 from_phase=move to_phase=shoot duration_s=0.123",
            (1, 2, "move", "shoot", 0.123),
        ),
        ("parse_between_step_timings_from_debug", "BETWEEN_STEP_TIMING episode=1 step_index=2 duration_s=0.123", (1, 2, 0.123)),
        ("parse_pre_step_timings_from_debug", "PRE_STEP_TIMING episode=1 step_index=2 duration_s=0.123", (1, 2, 0.123)),
        ("parse_post_step_timings_from_debug", "POST_STEP_TIMING episode=1 step_index=2 duration_s=0.123", (1, 2, 0.123)),
        ("parse_reset_timings_from_debug", "RESET_TIMING episode=1 duration_s=0.321", (1, 0.321)),
        ("parse_wrapper_step_timings_from_debug", "WRAPPER_STEP_TIMING episode=1 step_index=2 duration_s=0.123", (1, 2, 0.123)),
        (
            "parse_after_step_increment_timings_from_debug",
            "AFTER_STEP_INCREMENT_TIMING episode=1 step_index=2 duration_s=0.123",
            (1, 2, 0.123),
        ),
        (
            "parse_console_log_write_timings_from_debug",
            "CONSOLE_LOG_WRITE_TIMING episode=1 step_index=2 duration_s=0.123 lines=9",
            (1, 2, 0.123, 9),
        ),
        ("parse_get_mask_timings_from_debug", "GET_MASK_TIMING episode=1 step_index=2 duration_s=0.123", (1, 2, 0.123)),
    ],
)
def test_debug_timing_parsers(tmp_path: Path, fn_name: str, line: str, expected: tuple) -> None:
    log_path = tmp_path / "debug.log"
    log_path.write_text(line + "\n", encoding="utf-8")
    parser = getattr(an, fn_name)
    parsed = parser(str(log_path))
    assert parsed is not None
    assert parsed[0] == expected
    assert parser(str(tmp_path / "missing.log")) is None


def test_parse_step_breakdowns_new_and_old_formats(tmp_path: Path) -> None:
    log_path = tmp_path / "debug.log"
    log_path.write_text(
        "\n".join(
            [
                "STEP_BREAKDOWN episode=1 step_index=2 get_mask_s=0.1 convert_s=0.2 process_s=0.3 replay_s=0.4 build_obs_s=0.5 reward_s=0.6 total_s=2.1",
                "STEP_BREAKDOWN episode=2 step_index=3 get_mask_s=0.2 convert_s=0.3 process_s=0.4 build_obs_s=0.5 reward_s=0.6 total_s=2.0",
            ]
        ),
        encoding="utf-8",
    )
    parsed = an.parse_step_breakdowns_from_debug(str(log_path))
    assert parsed is not None
    assert parsed[0][0:3] == (1, 2, 0.1)
    assert parsed[1][5] == 0.0


def test_advance_is_expected_in_move_phase_rule_09_02() -> None:
    """Règle 09.02 (Documentation/40k_rules/« 09 Movement phase.pdf »).

    Étape MOVE UNITS > « Select Move Type » : l'Advance move est un TYPE DE MOUVEMENT de la
    phase de Mouvement, listé avec Remain stationary / Normal move / Fall-back move.
    L'analyzer attendait `"advance": "SHOOT"` (V11 T6) → un faux positif « wrong phase » sur
    CHAQUE advance (105 sur un run de 3 épisodes). Le moteur, lui, résout bien `squad_advance`
    dans la branche move de `_process_squad_action`.
    """
    stats = {
        "action_phase_accuracy": {},
        "first_error_lines": {"action_phase_mismatch": {}},
    }
    # Un advance journalisé en phase MOVE est CONFORME : zéro erreur.
    an._track_action_phase_accuracy(stats, "advance", "MOVE", 1, "line")
    assert stats["action_phase_accuracy"]["advance"] == {"total": 1, "wrong": 0}

    # Le même advance en phase SHOOT est une vraie violation.
    an._track_action_phase_accuracy(stats, "advance", "SHOOT", 1, "line")
    assert stats["action_phase_accuracy"]["advance"]["wrong"] == 1

    # Non-régression : les autres types gardent leur phase.
    for action_type, phase in (("move", "MOVE"), ("fled", "MOVE"), ("shoot", "SHOOT"),
                               ("charge", "CHARGE"), ("fight", "FIGHT"),
                               ("move_after_shooting", "SHOOT")):
        an._track_action_phase_accuracy(stats, action_type, phase, 1, "line")
        assert stats["action_phase_accuracy"][action_type]["wrong"] == 0, action_type
