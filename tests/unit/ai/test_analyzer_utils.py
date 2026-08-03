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


def test_unit_hp_and_damage_helpers() -> None:
    stats = {
        "parse_errors": [],
        "damage_missing_unit_hp": {1: 0, 2: 0},
        "first_error_lines": {"damage_missing_unit_hp": {1: None, 2: None}},
        "wounded_enemies": {1: set(), 2: set()},
        "current_episode_deaths": [],
    }
    unit_hp = {"u1": 3, "u2": 1}
    unit_models_alive = {"u1": 1, "u2": 1}
    unit_hp_max_per_model = {"u1": 3, "u2": 1}
    unit_types = {"u2": "Termagant"}
    unit_positions = {"u2": (1, 1)}
    unit_deaths = []
    unit_kill_context = {}
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
        attacker_id="a1",
        damage=1,
        player=1,
        turn=1,
        phase="shoot",
        line_number=10,
        current_episode_num=1,
        line_text="line",
        dead_units_current_episode=dead,
        unit_hp=unit_hp,
        unit_models_alive=unit_models_alive,
        unit_hp_max_per_model=unit_hp_max_per_model,
        unit_types=unit_types,
        unit_positions=unit_positions,
        unit_deaths=unit_deaths,
        unit_kill_context=unit_kill_context,
        stats=stats,
    )
    assert stats["damage_missing_unit_hp"][1] == 1

    an._apply_damage_and_handle_death(
        target_id="u2",
        attacker_id="a1",
        damage=2,
        player=1,
        turn=1,
        phase="shoot",
        line_number=11,
        current_episode_num=1,
        line_text="line2",
        dead_units_current_episode=dead,
        unit_hp=unit_hp,
        unit_models_alive=unit_models_alive,
        unit_hp_max_per_model=unit_hp_max_per_model,
        unit_types=unit_types,
        unit_positions=unit_positions,
        unit_deaths=unit_deaths,
        unit_kill_context=unit_kill_context,
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
    # Les primitives géométriques exigent l'échelle ET les règles du run ; hors parse_step_log
    # on les pose. Explicitement : cet état est porté par le module, donc un test qui l'a fixé
    # avant celui-ci le lui laisserait (`parse_step_log` le repose à chaque passe en production).
    from ai.analyzer_config import set_run_rules

    an.set_analyzer_board_scale(1)
    set_run_rules({
        "engagement_zone_subhex": "2",
        "metric.engagement": "hex",
        "metric.ranged": "euclidean",
        "move.thru_ez": "True",
        "move.thru_enemy": "False",
        "move.thru_friendly": "True",
    })
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
    # 03.01 : une figurine traverse ses ALLIES, jamais un ennemi. Ici e1 est ennemi de a1 (P1),
    # donc bloquant, et ses DEUX socles occupent — pas seulement son ancre.
    occ, ez_band = an._build_move_bfs_blockers(
        {"e1": {"e1#0": (2, 1), "e1#1": (2, 3)}}, unit_positions, {}, unit_player, unit_hp,
        mover_unit_id="a1",
    )
    assert (2, 1) in occ and (2, 3) in occ
    # La bande d'EZ ennemie se traverse (can_move_through_enemy_engagement_zone) : pas un obstacle.
    assert ez_band == set()
    # Unité sans donnée per-figurine : repli sur son ancre (donnée absente, pas contrôle désarmé).
    occ_anchor, _ = an._build_move_bfs_blockers(
        {}, unit_positions, {}, unit_player, unit_hp, mover_unit_id="a1",
    )
    assert occ_anchor == {(2, 1)}
    # Le même e1 vu par un ALLIÉ ne bloque plus rien (le camp vient de `unit_player`).
    occ_friendly, _ = an._build_move_bfs_blockers(
        {"e1": {"e1#0": (2, 1)}}, unit_positions, {}, {"e1": 2, "a1": 2}, unit_hp,
        mover_unit_id="a1",
    )
    assert occ_friendly == set()

    path_len = an._bfs_shortest_path_length(1, 1, 3, 1, 5, set(), set(), set())
    assert path_len is not None

    stats = {"action_phase_accuracy": {}, "first_error_lines": {"action_phase_mismatch": {}}}
    an._track_action_phase_accuracy(stats, "move", "SHOOT", 1, "line")
    assert stats["action_phase_accuracy"]["move"]["wrong"] == 1

    enemies = an.get_adjacent_enemies(1, 1, unit_player, unit_positions, unit_hp, {"e1": "x"}, player=1)
    assert "e1" in enemies

    cache = {}
    an._position_cache_set(cache, "u1", 3, 4)
    assert cache["u1"] == (3, 4)
    an._position_cache_remove(cache, "u1")
    assert "u1" not in cache


@pytest.mark.parametrize(
    "fn_name,line,expected",
    [
        ("parse_step_timings_from_debug", "STEP_TIMING episode=1 step_index=2 duration_s=0.123", (1, 2, 0.123)),
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


def test_parse_step_timings_still_reads_archived_step_calls_suffix(tmp_path: Path) -> None:
    """Un debug.log archive porte un suffixe ` step_calls=<n>` que plus rien ne produit.

    Le producteur (`StepLogger.log_action(step_calls_since_last=...)`, alimente par le bloc
    step_logger de `_process_semantic_action`) a ete supprime le 2026-07-29 parce qu'inatteignable,
    et le 4e champ du tuple avec lui. Retirer le groupe optionnel de la regex ne devait PAS rendre
    les anciens runs illisibles : les 3 premiers champs doivent continuer a se parser, le suffixe
    etant simplement ignore. Sans ce test, la promesse n'est verifiee par rien.
    """
    log_path = tmp_path / "debug.log"
    log_path.write_text(
        "\n".join(
            [
                "STEP_TIMING episode=1 step_index=2 duration_s=0.123 step_calls=3",
                "STEP_TIMING episode=1 step_index=3 duration_s=0.456",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    parsed = an.parse_step_timings_from_debug(str(log_path))
    assert parsed == [(1, 2, 0.123), (1, 3, 0.456)]


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


# ── Points de victoire : LUS de l'instantané moteur, jamais recalculés (2026-07-29) ──
# Vivaient ici 6 tests sur `_resolve_scenario_path`, `_get_objective_name_to_id_map`,
# `_calculate_primary_objective_points` et `_calculate_objective_control_snapshot`. Ces fonctions
# sont supprimées : elles ne servaient qu'à reconstruire le contrôle d'objectif à l'ANCRE, sans
# battle-shock (01.07) et hors des frontières 14.02. Mesuré sur une vraie partie : l'analyzer
# annonçait P1=60 / P2=20 là où le moteur avait attribué 35/35.


_LOG_HEAD = [
    "=== STEP-BY-STEP ACTION LOG ===",
    "[12:00:00] === EPISODE 1 START ===",
    "[12:00:00] Scenario: scenario_demo",
    "[12:00:00] Walls: none",
    # L'échelle du run vient de CETTE ligne, jamais du config courant : sans elle
    # `parse_step_log` refuse d'analyser (cf. parse_board_scale_from_log).
    "[12:00:00] Board: cols=220 rows=300 inches_to_subhex=5 hex_radius=2.78 margin=1",
    "[10:00:00] Run rules: engagement_zone_subhex=10 metric.engagement=hex metric.ranged=euclidean move.thru_ez=True move.thru_enemy=False move.thru_friendly=True",
]
_LOG_END = (
    "[12:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, "
    "Total=0, Duration=1.000s"
)


def _write_log(tmp_path: Path, lines: list) -> str:
    path = tmp_path / "step.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def test_victory_points_come_from_engine_snapshot(tmp_path: Path) -> None:
    """Le DERNIER instantané de l'épisode fait foi : les VP sont un total courant, pas un delta."""
    log = _write_log(tmp_path, _LOG_HEAD + [
        "[12:00:00] Objectives: West:(1,1)|North:(5,5)",
        "[12:00:01] T1 OBJECTIVE CONTROL: VP1=0 VP2=0 ZONES=West:Ctrl=none|North:Ctrl=none",
        # VP non nuls AVANT le dernier instantané : une accumulation (au lieu d'un écrasement)
        # donnerait 17/9 au lieu de 12/7 — le moteur journalise un TOTAL, pas un delta.
        "[12:00:03] T2 OBJECTIVE CONTROL: VP1=5 VP2=2 ZONES=West:Ctrl=1|North:Ctrl=none",
        "[12:00:05] T3 OBJECTIVE CONTROL: VP1=12 VP2=7 ZONES=West:Ctrl=1|North:Ctrl=2",
        _LOG_END,
    ])
    stats = an.parse_step_log(log)
    assert stats["victory_points_by_episode"][1] == {1: 12, 2: 7}
    assert stats["victory_points_values"][1] == [12]
    assert stats["victory_points_values"][2] == [7]


def test_end_of_episode_recap_is_not_read_as_a_snapshot(tmp_path: Path) -> None:
    """`[ts] OBJECTIVE CONTROL: Obj1:P1_OC=…` n'a ni T{tour} ni VP1= : il doit être ignoré,
    sinon il écraserait les VP par un format qui n'en porte pas."""
    log = _write_log(tmp_path, _LOG_HEAD + [
        "[12:00:00] Objectives: West:(1,1)",
        "[12:00:05] T3 OBJECTIVE CONTROL: VP1=12 VP2=7 ZONES=West:Ctrl=1",
        "[12:00:08] OBJECTIVE CONTROL: Objwest:P1_OC=9,P2_OC=0,Ctrl=1",
        _LOG_END,
    ])
    stats = an.parse_step_log(log)
    assert stats["victory_points_by_episode"][1] == {1: 12, 2: 7}


def test_log_with_objectives_but_no_snapshot_is_rejected(tmp_path: Path) -> None:
    """Journal antérieur au format : erreur explicite qui demande la régénération, pas des VP
    devinés (même contrat que le replay, cf. replayParser.ts)."""
    log = _write_log(tmp_path, _LOG_HEAD + [
        "[12:00:00] Objectives: West:(1,1)",
        _LOG_END,
    ])
    with pytest.raises(ValueError, match=r"no 'T<turn> OBJECTIVE CONTROL:' snapshot"):
        an.parse_step_log(log)


def test_log_without_objectives_is_accepted(tmp_path: Path) -> None:
    """Un scénario sans zone n'écrit aucun instantané : ce n'est pas un journal périmé."""
    log = _write_log(tmp_path, _LOG_HEAD + [
        "[12:00:00] Objectives: none",
        _LOG_END,
    ])
    stats = an.parse_step_log(log)
    assert stats["victory_points_values"][1] == []
    assert stats["victory_points_values"][2] == []
