from pathlib import Path

import pytest

from ai.step_logger import StepLogger
from shared.data_validation import ConfigurationError
from tests._state_invariants import unit_invariants


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_init_requires_buffer_size_when_enabled(tmp_path: Path) -> None:
    output_file = tmp_path / "step.log"
    with pytest.raises(ValueError, match=r"buffer_size is required"):
        StepLogger(output_file=str(output_file), enabled=True, buffer_size=None)


def test_init_writes_header_when_enabled(tmp_path: Path) -> None:
    output_file = tmp_path / "step.log"
    StepLogger(output_file=str(output_file), enabled=True, buffer_size=2)
    content = _read_text(output_file)
    assert "=== STEP-BY-STEP ACTION LOG ===" in content
    assert "AI_TURN.md COMPLIANCE" in content


def test_format_display_name_suffix_handles_empty_and_valid_values() -> None:
    logger = StepLogger(enabled=False)
    assert logger._format_display_name_suffix(None, "name") == ""
    assert logger._format_display_name_suffix({"name": "   "}, "name") == ""
    assert logger._format_display_name_suffix({"name": "Alpha"}, "name") == " [Alpha]"


def test_format_replay_style_message_move_wait_skip_rule_choice() -> None:
    logger = StepLogger(enabled=False)
    move_message = logger._format_replay_style_message(
        1,
        "move",
        {
            "unit_with_coords": "1(4, 5)",
            "start_pos": (1, 1),
            "end_pos": (2, 2),
            "reward": 1.5,
        },
    )
    assert move_message == "Unit 1(4, 5) MOVED from (1,1) to (2,2)[R:+1.5]"
    assert logger._format_replay_style_message(1, "wait", {"unit_with_coords": "1(4, 5)"}) == "Unit 1(4, 5) WAIT"
    assert logger._format_replay_style_message(
        1, "skip", {"unit_with_coords": "1(4, 5)", "skip_reason": "no target"}
    ) == "Unit 1(4, 5) SKIP (no target)"
    assert logger._format_replay_style_message(
        1, "rule_choice", {"unit_with_coords": "1(4, 5)", "selected_rule_name": "sustained hits"}
    ) == "Unit 1(4, 5) chose [SUSTAINED HITS]"


def test_format_replay_style_message_rule_choice_requires_name() -> None:
    logger = StepLogger(enabled=False)
    with pytest.raises(KeyError, match=r"selected_rule_name"):
        logger._format_replay_style_message(1, "rule_choice", {"unit_with_coords": "1(2, 3)"})


def test_format_replay_style_message_dead_produces_line() -> None:
    """VERROU finding-1 : _format_replay_style_message doit retourner la ligne DEAD
    quand model_id et reason sont fournis. Avant le fix, _build_step_log_details ne les
    mappait pas → KeyError avalé par log_action → ligne silencieusement absente."""
    logger = StepLogger(enabled=False)
    line = logger._format_replay_style_message(
        42, "dead", {"model_id": "m7", "reason": "combat"}
    )
    assert line == "Unit 42 DEAD model=m7 reason=combat"


def test_format_replay_style_message_dead_requires_model_id() -> None:
    logger = StepLogger(enabled=False)
    with pytest.raises(KeyError, match=r"model_id"):
        logger._format_replay_style_message(1, "dead", {"reason": "combat"})


def test_format_replay_style_message_dead_requires_reason() -> None:
    logger = StepLogger(enabled=False)
    with pytest.raises(KeyError, match=r"reason"):
        logger._format_replay_style_message(1, "dead", {"model_id": "m1"})


def test_log_episode_start_writes_units_and_metadata(tmp_path: Path) -> None:
    output_file = tmp_path / "step.log"
    logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=10)
    units = [
        {**unit_invariants(),
            "id": 1,
            "col": 2,
            "row": 3,
            "player": 1,
            "HP_MAX": 2,
            "unitType": "Intercessor",
            "DISPLAY_NAME": "Alpha",
            "BASE_SHAPE": "round",
            "BASE_SIZE": 1,
            "MODEL_HEIGHT": 2.5,
        }
    ]
    logger.log_episode_start(
        run_rules={"engagement_zone_subhex": 10, "metric.engagement": "hex",
                   "metric.ranged": "euclidean", "move.thru_ez": True,
                   "move.thru_enemy": False, "move.thru_friendly": True},
        units_data=units,
        scenario_info="demo-scenario",
        bot_name="random",
        walls=[{"col": 7, "row": 8}],
        objectives=[{"id": 1, "hexes": [(4, 4)]}],
        primary_objective_config={"mode": "control"},
        roster_info={
            "agent_roster_id": "A1",
            "opponent_roster_id": "B2",
            "agent_roster_ref": "space_marines",
            "opponent_roster_ref": "tyranids",
            "scale": 2000,
            # Siège de l'agent : EXIGÉ dans l'entête (`controlled_player_mode` accepte p2 et
            # random). Sans lui, tout lecteur du journal suppose « agent == P1 ».
            "agent_player": 1,
        },
        board_config={
            "cols": 15, "rows": 13, "hex_radius": 1.0,
            "margin": 0.0, "inches_to_subhex": 2.0,
        },
    )
    content = _read_text(output_file)
    assert "=== EPISODE 1 START ===" in content
    assert "Scenario: demo-scenario" in content
    assert "Opponent: RandomBot" in content
    assert "Walls: (7,8)" in content
    assert "Objectives: Obj1:(4,4)" in content
    assert 'Rules: {"primary_objective":{"mode":"control"}}' in content
    assert "Unit 1 (Intercessor) [Alpha] P1: Starting position (2,3), HP_MAX=2" in content
    assert logger.episode_number == 1
    assert logger.episode_step_count == 0
    assert logger.episode_action_count == 0
    # Aucun scenario_path fourni : pas de ligne, plutôt qu'un chemin vide que le replay
    # repasserait tel quel à l'API.
    assert "Scenario file:" not in content


def test_log_episode_start_writes_scenario_path(tmp_path: Path) -> None:
    """Le chemin du scénario tiré est journalisé : c'est la seule trace, dans tout le step.log,
    de la config d'où le replay doit relire terrain, icônes et zones de déploiement."""
    output_file = tmp_path / "step.log"
    logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=10)
    logger.log_episode_start(
        run_rules={"engagement_zone_subhex": 10, "metric.engagement": "hex",
                   "metric.ranged": "euclidean", "move.thru_ez": True,
                   "move.thru_enemy": False, "move.thru_friendly": True},
        units_data=[],
        scenario_info="Random from 3 scenarios",
        board_config={
            "cols": 15, "rows": 13, "hex_radius": 1.0,
            "margin": 0.0, "inches_to_subhex": 2.0,
        },
        scenario_path="config/agents/ArmageddonAgent/scenarios/training/scenario_bot-02.json",
    )
    content = _read_text(output_file)
    assert (
        "Scenario file: config/agents/ArmageddonAgent/scenarios/training/scenario_bot-02.json"
        in content
    )
    assert "Scenario: Random from 3 scenarios" in content


def test_log_action_increments_counters_and_flushes_on_threshold(tmp_path: Path) -> None:
    output_file = tmp_path / "step.log"
    logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=1)
    logger.log_episode_start(
        run_rules={"engagement_zone_subhex": 10, "metric.engagement": "hex",
                   "metric.ranged": "euclidean", "move.thru_ez": True,
                   "move.thru_enemy": False, "move.thru_friendly": True},
        units_data=[{**unit_invariants(), "id": 1, "col": 1, "row": 1, "player": 1, "HP_MAX": 1, "unitType": "Intercessor"}]
    )
    logger.log_action(
        unit_id=1,
        action_type="wait",
        phase="move",
        player=1,
        success=True,
        step_increment=True,
        action_details={"current_turn": 2, "unit_with_coords": "1(1, 1)"},
    )
    content = _read_text(output_file)
    assert "E1 T2 P1 MOVE : Unit 1(1, 1) WAIT [SUCCESS]" in content
    assert logger.action_count == 1
    assert logger.step_count == 1
    assert logger.episode_action_count == 1
    assert logger.episode_step_count == 1


def test_log_episode_end_flushes_buffer_and_logs_objective_control(tmp_path: Path) -> None:
    output_file = tmp_path / "step.log"
    logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=50)
    logger.log_episode_start(
        run_rules={"engagement_zone_subhex": 10, "metric.engagement": "hex",
                   "metric.ranged": "euclidean", "move.thru_ez": True,
                   "move.thru_enemy": False, "move.thru_friendly": True},
        units_data=[{**unit_invariants(), "id": 1, "col": 1, "row": 1, "player": 1, "HP_MAX": 1, "unitType": "Intercessor"}]
    )
    logger.log_action(
        unit_id=1,
        action_type="wait",
        phase="move",
        player=1,
        success=True,
        step_increment=True,
        action_details={"current_turn": 1, "unit_with_coords": "1(1, 1)"},
    )

    # Buffered line must be flushed by log_episode_end().
    logger.log_episode_end(
        total_episodes_steps=42,
        winner=1,
        win_method="objectives",
        objective_control={1: {"player_1_oc": 3, "player_2_oc": 0, "controller": 1}},
    )
    content = _read_text(output_file)
    assert "E1 T1 P1 MOVE : Unit 1(1, 1) WAIT [SUCCESS]" in content
    assert "EPISODE END: Winner=1, Method=objectives" in content
    assert "OBJECTIVE CONTROL: Obj1:P1_OC=3,P2_OC=0,Ctrl=1" in content


def test_format_replay_style_message_reactive_move_and_validations() -> None:
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(
        4,
        "reactive_move",
        {
            "unit_with_coords": "4(5, 6)",
            "start_pos": (5, 6),
            "end_pos": (6, 6),
            "triggered_by_unit_id": 9,
            "trigger_to_pos": (6, 5),
            "range_roll": 4,
            "ability_display_name": "Heroic Intervention",
            "reward": 0.2,
        },
    )
    assert "REACTIVE MOVED [HEROIC INTERVENTION]" in msg
    assert "[R:+0.2]" in msg

    with pytest.raises(ValueError, match=r"range_roll must be int"):
        logger._format_replay_style_message(
            4,
            "reactive_move",
            {
                "unit_with_coords": "4(5, 6)",
                "start_pos": (5, 6),
                "end_pos": (6, 6),
                "triggered_by_unit_id": 9,
                "trigger_to_pos": (6, 5),
                "range_roll": True,
                "ability_display_name": "Heroic Intervention",
            },
        )


def test_format_replay_style_message_charge_fail_and_impact() -> None:
    logger = StepLogger(enabled=False)
    fail_msg = logger._format_replay_style_message(
        2,
        "charge_fail",
        {
            "unit_with_coords": "2(3, 3)",
            "target_id": 7,
            "charge_roll": 5,
            "charge_failed_reason": "distance_too_far",
            "target_coords": (6, 3),
        },
    )
    assert "FAILED CHARGE to unit 7(6,3) [Roll: 5]" in fail_msg

    impact_msg = logger._format_replay_style_message(
        2,
        "charge_impact",
        {
            "unit_with_coords": "2(3, 3)",
            "target_id": 7,
            "impact_roll": 6,
            "impact_threshold": 4,
            "impact_hit_result": "HIT",
            "mortal_wounds": 2,
            "ability_display_name": "Hammer of Wrath",
            "target_coords": (6, 3),
            "reward": 1.0,
        },
    )
    assert "IMPACTED [HAMMER OF WRATH]" in impact_msg
    assert "Dmg:2HP" in impact_msg
    assert "[R:+1.0]" in impact_msg


def _combat_details() -> dict:
    return {
        "unit_with_coords": "3(4, 4)",
        "target_id": 8,
        "hit_roll": 5,
        "wound_roll": 4,
        "save_roll": 2,
        "damage_dealt": 1,
        "hit_result": "HIT",
        "wound_result": "WOUND",
        "save_result": "FAIL",
        "hit_target": 3,
        "wound_target": 4,
        "save_target": 3,
        "fight_subphase": "fight",
    }


def test_format_replay_style_message_combat_requires_fight_subphase() -> None:
    logger = StepLogger(enabled=False)
    details = _combat_details()
    del details["fight_subphase"]
    with pytest.raises(KeyError, match=r"fight_subphase"):
        logger._format_replay_style_message(3, "combat", details)


def test_format_replay_style_message_combat_emits_only_fight_subphase() -> None:
    # Contrat replay : la ligne combat porte UNIQUEMENT [FIGHT_SUBPHASE:…]. Aucun pool loggué —
    # le cercle vert (unité active) est dérivé de l'attaquant côté parser.
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(3, "combat", _combat_details())
    assert "[FIGHT_SUBPHASE:fight]" in msg
    assert "FIGHT_ELIGIBLE" not in msg
    assert "CHARGING_POOL" not in msg


def test_unknown_action_type_raises_and_phase_transition_logs(tmp_path: Path) -> None:
    logger = StepLogger(enabled=False)
    with pytest.raises(ValueError, match=r"Unknown action_type"):
        logger._format_replay_style_message(1, "unknown_action", {})

    output_file = tmp_path / "step.log"
    enabled_logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=2)
    enabled_logger.log_phase_transition("move", "shoot", player=1, turn_number=3)
    content = _read_text(output_file)
    assert "T3 P1 SHOOT phase Start" in content


# ── Instantané 14.02 : contrôle d'objectif + points de victoire (source du replay) ──


def _objectives() -> list:
    return [
        {"id": 1, "name": "West", "hexes": [[2, 10]]},
        {"id": 2, "name": "North", "hexes": [[12, 1]]},
        {"id": 3, "hexes": [[22, 10]]},  # sans nom -> clé "Obj3"
    ]


def test_objective_control_snapshot_writes_engine_state(tmp_path: Path) -> None:
    output_file = tmp_path / "step.log"
    logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=1)
    logger.log_objective_control_snapshot(
        3, _objectives(), {"1": 1, "2": None, "3": 2}, {1: 5, 2: 2}, {1: 4, 2: 3}
    )
    content = _read_text(output_file)
    assert (
        "T3 OBJECTIVE CONTROL: VP1=5 VP2=2 CP1=4 CP2=3 "
        "ZONES=West:Ctrl=1|North:Ctrl=none|Obj3:Ctrl=2"
        in content
    )


def test_objective_control_snapshot_key_matches_objectives_line(tmp_path: Path) -> None:
    # Le replay apparie zones et géométrie par ce nom : les deux lignes DOIVENT employer la
    # même clé, y compris pour un objectif sans nom.
    output_file = tmp_path / "step.log"
    logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=1)
    logger.log_episode_start(
        [],
        "scenario",
        walls=None,
        objectives=_objectives(),
        primary_objective_config=None,
        board_config={"cols": 1, "rows": 1, "inches_to_subhex": 1, "hex_radius": 1, "margin": 1},
    )
    logger.log_objective_control_snapshot(1, _objectives(), {}, {1: 0, 2: 0}, {1: 0, 2: 0})
    content = _read_text(output_file)
    geometry_names = [
        group.split(":")[0]
        for group in content.split("Objectives: ")[1].split("\n")[0].split("|")
    ]
    zones = content.split("ZONES=")[1].split("\n")[0]
    control_names = [zone.split(":")[0] for zone in zones.split("|")]
    assert geometry_names == control_names == ["West", "North", "Obj3"]


def test_objective_control_snapshot_missing_controller_is_uncontrolled(tmp_path: Path) -> None:
    # Aucune frontière de phase franchie (14.02) : le moteur n'a pas encore d'entrée pour la zone.
    output_file = tmp_path / "step.log"
    logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=1)
    logger.log_objective_control_snapshot(1, _objectives(), {}, {1: 0, 2: 0}, {1: 0, 2: 0})
    assert "ZONES=West:Ctrl=none|North:Ctrl=none|Obj3:Ctrl=none" in _read_text(output_file)


def test_objective_control_snapshot_rejects_unexpected_controller(tmp_path: Path) -> None:
    # Pas de valeur de repli : un contrôleur inattendu doit NOMMER ce qu'il a rencontré.
    output_file = tmp_path / "step.log"
    logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=1)
    with pytest.raises(ValueError, match=r"Unexpected objective controller for 1: 7"):
        logger.log_objective_control_snapshot(1, _objectives(), {"1": 7}, {1: 0, 2: 0}, {1: 0, 2: 0})


def test_objective_control_snapshot_goes_through_buffer(tmp_path: Path) -> None:
    # Ordre du journal : le replay place l'instantané d'après le nombre d'actions déjà lues.
    # Une écriture directe le ferait passer AVANT des actions encore bufferisées.
    output_file = tmp_path / "step.log"
    logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=99)
    logger.log_objective_control_snapshot(1, _objectives(), {}, {1: 0, 2: 0}, {1: 0, 2: 0})
    assert "OBJECTIVE CONTROL" not in _read_text(output_file)
    assert any("OBJECTIVE CONTROL" in line for line in logger.log_buffer)
    logger._flush_buffer()
    assert "OBJECTIVE CONTROL" in _read_text(output_file)


def test_les_cp_sont_journalises_pour_le_replay(tmp_path: Path) -> None:
    """08.02 : le replay affiche les CP dans le MEME en-tete que les VP (`UnitStatusTable`).

    Il ne rejoue pas un `game_state`, il relit ce journal : un compteur que le moteur n'ecrit
    pas ici n'existe pas pour lui. C'est la raison pour laquelle les CP n'apparaissaient nulle
    part en replay alors que le conteneur d'affichage etait deja commun avec le PvP.

    La position est un contrat : entre les VP et `ZONES=`, parce que les DEUX parseurs de cette
    ligne (`ai/analyzer_core.py` et `frontend/src/utils/replayParser.ts`) l'ancrent sur `ZONES=`
    et lisent `CP1=/CP2=` en groupe optionnel.
    """
    output_file = tmp_path / "step.log"
    logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=1)
    logger.log_objective_control_snapshot(2, _objectives(), {}, {1: 10, 2: 5}, {1: 7, 2: 6})
    content = _read_text(output_file)
    assert "VP1=10 VP2=5 CP1=7 CP2=6 ZONES=" in content, content


def test_un_stock_de_cp_absent_leve(tmp_path: Path) -> None:
    """Aucune valeur par defaut : un joueur sans CP est un etat corrompu, pas un 0."""
    output_file = tmp_path / "step.log"
    logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=1)
    with pytest.raises(ConfigurationError):
        logger.log_objective_control_snapshot(1, _objectives(), {}, {1: 0, 2: 0}, {1: 0})


# ─────────────────────────────────────────────────────────────────────────────
# `_ability_token` — le contrat de FORME du token de capacité
#
# Le seul contrôle qui le mentionnait (`test_faction_abilities`) compte des occurrences dans
# `inspect.getsource(StepLogger)` : il verrouille l'ORTHOGRAPHE des sites d'appel, pas le
# comportement de la fonction. La preuve : ce contrôle a dû être réécrit par le commit qui a
# extrait l'helper. Un test qu'il faut réécrire à chaque refactor de ce qu'il garde ne le garde
# pas. `_ability_token` pouvait rendre `"[]"` ou ` [NONE]` sur un nom vide sans rien rougir.
# ─────────────────────────────────────────────────────────────────────────────

def test_ability_token_rend_le_vide_sur_un_nom_absent_ou_blanc() -> None:
    """Absence de capacité = AUCUN token, pas un token vide.

    Un ` []` traverserait `RULE_TOKEN_REGEX` côté frontend (`[^\\]]+` ne matche pas le vide,
    mais ` [ ]` oui) et serait compté comme un usage de règle par l'analyzer.
    """
    from ai.step_logger import _ability_token

    for absent in (None, "", "   ", "\t", 0, False, []):
        assert _ability_token(absent) == "", repr(absent)


def test_ability_token_normalise_en_majuscules_sans_espaces_parasites() -> None:
    """MAJUSCULES et `strip` : c'est la forme que le frontend et l'analyzer cherchent."""
    from ai.step_logger import _ability_token

    assert _ability_token("Oath of Moment") == " [OATH OF MOMENT]"
    assert _ability_token("  Targeted Intercession  ") == " [TARGETED INTERCESSION]"


def test_ability_token_commence_par_une_espace() -> None:
    """L'espace de tête est PORTEUSE : le token est concaténé juste après `Wound 4(3+)`.

    Sans elle le log écrit `Wound 4(3+)[OATH OF MOMENT]`, que le tokenizer de segment du
    replay (`replayParser.ts`, `\\s*\\[`) accepte encore, mais que la ligne de synthèse et la
    lecture humaine collent. C'est le genre de détail qu'un `.strip()` bien intentionné retire.
    """
    from ai.step_logger import _ability_token

    token = _ability_token("Oath of Moment")
    assert token.startswith(" "), repr(token)
    assert token == f" [{token.strip()[1:-1]}]"


# --- 03.03 End of Turn : la ligne de retrait pour cohérence ------------------------------------
#
# Chaînon du MILIEU. Le moteur pose l'entrée d'action_log et l'analyzer/le replay lisent la ligne ;
# entre les deux, le mapping `_STEP_LOG_TYPE_MAP` et ce formateur décident si la ligne existe.
# Un type sans entrée de mapping est « volontairement non journalisé » — en silence.


def test_format_replay_style_message_coherency_removal() -> None:
    logger = StepLogger(enabled=False)
    assert logger._format_replay_style_message(
        1, "coherency_removal", {"unit_with_coords": "1(4, 5)", "removed_models": ["1#2", "1#3"]}
    ) == "Unit 1(4, 5) COHERENCY REMOVED 1#2 1#3 (03.03)"


def test_format_replay_style_message_coherency_removal_requires_models() -> None:
    """Une ligne sans figurine nommée ne dirait pas QUI part : le segment `[MODELS:]` ne donne
    que les survivantes, et aucun lecteur ne peut déduire l'absente d'un effectif plus court."""
    logger = StepLogger(enabled=False)
    with pytest.raises(KeyError, match=r"removed_models"):
        logger._format_replay_style_message(1, "coherency_removal", {"unit_with_coords": "1(2, 3)"})


def test_coherency_removal_is_mapped_and_does_not_increment_steps() -> None:
    """VERROU du chaînon manquant : sans l'entrée de mapping, l'entrée d'action_log du moteur est
    ignorée au drainage et AUCUNE ligne n'atteint step.log — exactement l'état d'avant le fix."""
    from engine.w40k_core import W40KEngine

    assert W40KEngine._STEP_LOG_TYPE_MAP["coherency_removal"] == "coherency_removal"
    # Effet de fin de tour, pas action d'agent : l'incrémenter décalerait `episode_steps`.
    assert "coherency_removal" in W40KEngine._STEP_LOG_NON_INCREMENTING_TYPES


def test_format_replay_style_message_reserves_timeout() -> None:
    """VERROU : supprimer le formateur 'strategic_reserves_timeout' rend ce test ROUGE."""
    logger = StepLogger(enabled=False)
    result = logger._format_replay_style_message(1, "strategic_reserves_timeout", {})
    assert result == "Unit 1 RESERVES TIMEOUT (20.04)"


def test_reserves_timeout_is_mapped_and_does_not_increment_steps() -> None:
    """VERROU : sans ce mapping, l'entrée d'action_log 20.04 n'atteint jamais step.log."""
    from engine.w40k_core import W40KEngine

    assert W40KEngine._STEP_LOG_TYPE_MAP["strategic_reserves_timeout"] == "strategic_reserves_timeout"
    assert "strategic_reserves_timeout" in W40KEngine._STEP_LOG_NON_INCREMENTING_TYPES


def test_format_replay_style_message_hazardous_mortal_wounds() -> None:
    """VERROU : le formatter HAZARDOUS émet [ALLOC_MODEL:] — supprimer target_model_id rend ce test ROUGE."""
    logger = StepLogger(enabled=False)
    result = logger._format_replay_style_message(
        1, "hazardous", {"unit_with_coords": "3(2, 4)", "hazardous_mortal_wounds": 2, "target_model_id": "3#0"}
    )
    assert result == "Unit 3(2, 4) SUFFERS 2 Mortal Wounds [HAZARDOUS] [ALLOC_MODEL: 3#0]"


def test_format_replay_style_message_hazardous_missing_mortal_wounds_raises() -> None:
    """VERROU : un payload sans hazardous_mortal_wounds lève ConfigurationError."""
    from shared.data_validation import ConfigurationError

    logger = StepLogger(enabled=False)
    with pytest.raises(ConfigurationError, match=r"hazardous_mortal_wounds"):
        logger._format_replay_style_message(1, "hazardous", {"unit_with_coords": "3(2, 4)"})


def test_format_replay_style_message_hazardous_missing_target_model_id_raises() -> None:
    """VERROU : un payload sans target_model_id lève ConfigurationError (grammar 6 : modèle obligatoire)."""
    from shared.data_validation import ConfigurationError

    logger = StepLogger(enabled=False)
    with pytest.raises(ConfigurationError, match=r"target_model_id"):
        logger._format_replay_style_message(
            1, "hazardous", {"unit_with_coords": "3(2, 4)", "hazardous_mortal_wounds": 2}
        )


def test_step_timing_duration_not_unix_timestamp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """VERROU : le premier STEP_TIMING de chaque épisode doit être une durée réelle,
    pas un timestamp Unix (~1,79e9). Régression : _last_step_wall initialisé avec
    perf_counter() (uptime) mais lu avec time.time() (époque Unix)."""
    import re

    monkeypatch.chdir(tmp_path)
    output_file = tmp_path / "step.log"
    run_rules = {
        "engagement_zone_subhex": 10,
        "metric.engagement": "hex",
        "metric.ranged": "euclidean",
        "move.thru_ez": True,
        "move.thru_enemy": False,
        "move.thru_friendly": True,
    }
    units = [{**unit_invariants(), "id": 1, "col": 1, "row": 1, "player": 1, "HP_MAX": 1, "unitType": "Intercessor"}]
    logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=50, debug_mode=True)

    for _episode in range(2):
        logger.log_episode_start(run_rules=run_rules, units_data=units)
        for _ in range(3):
            logger.log_action(
                unit_id=1,
                action_type="wait",
                phase="move",
                player=1,
                success=True,
                step_increment=True,
                action_details={"current_turn": 1, "unit_with_coords": "1(1, 1)"},
            )
        logger.log_episode_end(total_episodes_steps=3, winner=1, win_method=None, objective_control={})

    debug_log = tmp_path / "debug.log"
    assert debug_log.exists(), "debug.log non créé — debug_mode inactif ou chemin incorrect"
    content = debug_log.read_text(encoding="utf-8")
    pattern = re.compile(r"STEP_TIMING.*?duration_s=([\d.]+)")
    durations = [float(m.group(1)) for m in pattern.finditer(content)]
    assert len(durations) == 6, f"Attendu 6 STEP_TIMING (2 épisodes × 3 steps), obtenu {len(durations)}"
    for i, d in enumerate(durations):
        assert d < 60, (
            f"STEP_TIMING[{i}] duration_s={d:.3f} ressemble à un timestamp Unix "
            f"(attendu < 60 s ; régression perf_counter vs time.time)"
        )
