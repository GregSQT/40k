import sqlite3

import pytest

from services import api_server


def test_make_json_serializable_handles_tuple_keys_set_and_object_dict() -> None:
    class Dummy:
        def __init__(self) -> None:
            self.value = {("a", 1): {1, 2}}

    result = api_server.make_json_serializable(Dummy())
    assert "a,1" in result["value"]
    assert sorted(result["value"]["a,1"]) == [1, 2]


def test_make_json_serializable_numpy_array_and_scalar() -> None:
    np = pytest.importorskip("numpy")
    assert api_server.make_json_serializable(np.array([1, 2, 3])) == [1, 2, 3]
    assert api_server.make_json_serializable(np.int64(7)) == 7
    assert api_server.make_json_serializable(np.float64(3.5)) == 3.5


def test_game_state_for_json_removes_topology_arrays() -> None:
    engine_instance = type("E", (), {"game_state": {"los_topology": 1, "pathfinding_topology": 2, "x": 3}})()
    state = api_server._game_state_for_json(engine_instance)
    assert "los_topology" not in state
    assert "pathfinding_topology" not in state
    assert state["x"] == 3


def test_game_state_for_json_drops_footprint_zone_when_mask_loops_present() -> None:
    engine_instance = type(
        "E",
        (),
        {
            "game_state": {
                "phase": "move",
                "move_preview_footprint_zone": {(1, 2), (3, 4)},
                "move_preview_footprint_mask_loops": [[[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]]],
            },
        },
    )()
    state = api_server._game_state_for_json(engine_instance)
    assert "move_preview_footprint_zone" not in state
    assert state["move_preview_footprint_mask_loops"] is not None


def test_game_state_for_json_strips_internal_engine_keys() -> None:
    engine_instance = type(
        "E",
        (),
        {
            "game_state": {
                "phase": "move",
                "turn": 1,
                "units_cache_prev": {"1": {"col": 0, "row": 0}},
                "last_compliance_data": {"x": 1},
                "_best_weapon_cache": {"k": "v"},
                "console_logs": ["noise"],
            },
        },
    )()
    state = api_server._game_state_for_json(engine_instance)
    assert state["turn"] == 1
    assert "units_cache_prev" not in state
    assert "last_compliance_data" not in state
    assert "_best_weapon_cache" not in state
    assert "console_logs" not in state


def test_game_state_for_json_drops_preview_hexes_when_move_pool_present() -> None:
    """``preview_hexes`` est un alias du pool d’ancres — ne pas dupliquer le JSON."""
    anchors = [[1, 2], [3, 4]]
    engine_instance = type(
        "E",
        (),
        {
            "game_state": {
                "phase": "move",
                "valid_move_destinations_pool": anchors,
                "preview_hexes": list(anchors),
            },
        },
    )()
    state = api_server._game_state_for_json(engine_instance)
    assert state["valid_move_destinations_pool"] == anchors
    assert "preview_hexes" not in state


def test_game_state_for_json_excludes_move_preview_border() -> None:
    engine_instance = type(
        "E",
        (),
        {
            "game_state": {
                "phase": "move",
                "valid_move_destinations_pool": [[1, 2], [3, 4]],
                "move_preview_border": [[1, 2]],
            },
        },
    )()
    state = api_server._game_state_for_json(engine_instance)
    assert "move_preview_border" not in state
    assert state["valid_move_destinations_pool"] == [[1, 2], [3, 4]]


def test_sync_units_hp_from_cache_applies_cache_and_sets_zero_for_dead() -> None:
    serializable_state = {"units": [{"id": "1", "HP_CUR": 99}, {"id": "2", "HP_CUR": 99}]}
    game_state = {"units_cache": {"1": {"HP_CUR": 4}}}
    api_server._sync_units_hp_from_cache(serializable_state, game_state)
    assert serializable_state["units"][0]["HP_CUR"] == 4
    assert serializable_state["units"][1]["HP_CUR"] == 0


def test_build_and_attach_player_types_for_pve() -> None:
    assert api_server._build_player_types(True, "pve") == {"1": "human", "2": "ai"}
    engine_instance = type("E", (), {"game_state": {}, "current_mode_code": "pve"})()
    serializable_state = {}
    api_server._attach_player_types(serializable_state, engine_instance)
    assert serializable_state["player_types"]["2"] == "ai"
    assert engine_instance.game_state["current_mode_code"] == "pve"


def test_attach_player_types_rejects_invalid_mode() -> None:
    engine_instance = type("E", (), {"game_state": {}, "current_mode_code": "invalid"})()
    with pytest.raises(ValueError, match=r"Unsupported current_mode_code"):
        api_server._attach_player_types({}, engine_instance)


def test_hash_and_verify_password_roundtrip_and_failures() -> None:
    stored = api_server._hash_password("secret")
    assert api_server._verify_password("secret", stored) is True
    assert api_server._verify_password("wrong", stored) is False
    with pytest.raises(ValueError, match=r"Invalid password hash format"):
        api_server._verify_password("secret", "bad-format")


def test_extract_bearer_token_from_request_context() -> None:
    with api_server.app.test_request_context(headers={"Authorization": "Bearer token-123"}):
        assert api_server._extract_bearer_token() == "token-123"
    with api_server.app.test_request_context(headers={"Authorization": "Invalid token"}):
        with pytest.raises(ValueError, match=r"Invalid Authorization header format"):
            api_server._extract_bearer_token()


def test_resolve_permissions_for_profile_from_sqlite_rows() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()
    cursor.executescript(
        """
        CREATE TABLE game_modes (id INTEGER PRIMARY KEY, code TEXT, label TEXT);
        CREATE TABLE options (id INTEGER PRIMARY KEY, code TEXT, label TEXT);
        CREATE TABLE profile_game_modes (profile_id INTEGER, game_mode_id INTEGER);
        CREATE TABLE profile_options (profile_id INTEGER, option_id INTEGER, enabled INTEGER);
        """
    )
    cursor.execute("INSERT INTO game_modes VALUES (1, 'pvp', 'PVP')")
    cursor.execute("INSERT INTO options VALUES (1, 'auto_weapon_selection', 'Auto')")
    cursor.execute("INSERT INTO profile_game_modes VALUES (7, 1)")
    cursor.execute("INSERT INTO profile_options VALUES (7, 1, 1)")
    connection.commit()

    permissions = api_server._resolve_permissions_for_profile(connection, 7)
    assert permissions["game_modes"] == ["pvp"]
    assert permissions["options"]["auto_weapon_selection"] is True

    connection.close()


def test_is_mode_allowed_supports_test_backward_compatibility() -> None:
    permissions = {"game_modes": ["test"]}
    assert api_server._is_mode_allowed("pvp_test", permissions) is True
    assert api_server._is_mode_allowed("pve_test", permissions) is True
    assert api_server._is_mode_allowed("pve", permissions) is False


def test_get_activation_pool_key_for_phase_and_invalid() -> None:
    assert api_server._get_activation_pool_key_for_phase("move") == "move_activation_pool"
    assert api_server._get_activation_pool_key_for_phase("shoot") == "shoot_activation_pool"
    assert api_server._get_activation_pool_key_for_phase("charge") == "charge_activation_pool"
    with pytest.raises(ValueError, match=r"end_phase is not supported"):
        api_server._get_activation_pool_key_for_phase("fight")


def test_execute_end_phase_action_returns_wrong_player_error() -> None:
    class DummyEngine:
        def __init__(self) -> None:
            self.game_state = {"phase": "move", "current_player": 1}

    engine_instance = DummyEngine()
    success, result = api_server._execute_end_phase_action(engine_instance, {"player": 2})
    assert success is False
    assert result["error"] == "wrong_player_end_phase"


def test_execute_end_phase_action_processes_pool_and_advances_phase() -> None:
    class DummyEngine:
        def __init__(self) -> None:
            self.game_state = {
                "phase": "move",
                "current_player": 1,
                "move_activation_pool": ["u1"],
            }

        def execute_semantic_action(self, action):
            if action["action"] == "skip":
                self.game_state["move_activation_pool"] = []
                return True, {"action": "skip", "unitId": action["unitId"]}
            if action["action"] == "advance_phase":
                self.game_state["phase"] = "shoot"
                return True, {"phase": "shoot"}
            raise AssertionError("Unexpected action")

    success, result = api_server._execute_end_phase_action(DummyEngine(), {"player": 1})
    assert success is True
    assert result["action"] == "end_phase"


def test_load_army_file_and_list_armies_from_temp_config(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path
    armies_dir = root / "config" / "armies"
    armies_dir.mkdir(parents=True, exist_ok=True)
    factions_path = root / "config" / "factions.json"
    factions_path.write_text('{"spaceMarine":{"display_name":"Space Marine"}}', encoding="utf-8")
    (armies_dir / "sm.json").write_text(
        """
        {
          "faction": "spaceMarine",
          "display_name": "SM Army",
          "description": "Desc",
          "units": [{"unit_type": "Intercessor", "count": 2}]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(api_server, "abs_parent", str(root))

    army_cfg = api_server._load_army_file("sm.json")
    assert army_cfg["display_name"] == "SM Army"
    armies = api_server._list_armies()
    assert len(armies) == 1
    assert armies[0]["faction_display_name"] == "Space Marine"
