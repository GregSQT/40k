import sqlite3
from typing import Any, Dict, Optional, Tuple, cast

import pytest

from ai.unit_registry import UnitRegistry
from engine.phase_handlers import movement_handlers
from services import api_server
from shared.data_validation import require_present


class _StateManagerStub:
    """Doublure du state_manager du moteur pour les tests de SERIALISATION.

    `_game_state_for_json` declenche le rafraichissement de frontiere du controle d'objectif
    (regle 14.02, `refresh_objective_control_on_boundary`) : un faux moteur doit donc porter un
    `state_manager`, comme le vrai. Le stub compte les appels, ce qui permet de VERIFIER le
    contrat (cf. test_game_state_for_json_triggers_objective_control_refresh) au lieu de le
    contourner.
    """

    def __init__(self) -> None:
        self.boundary_refresh_calls = 0

    def refresh_objective_control_on_boundary(self, game_state: Dict[str, Any]) -> bool:
        self.boundary_refresh_calls += 1
        return False


class _EngineStub:
    """Faux moteur minimal pour les helpers de serialisation de l'API.

    Classe NOMMEE plutot que `type("E", (), {...})()` : les attributs sont declares, donc le
    contrat lu par `_game_state_for_json` (`game_state` + `state_manager`),
    `_attach_player_types` (`current_mode_code`) et `_build_units_from_scenario_army`
    (`unit_registry`) reste verifiable au lieu d'etre un objet opaque ou l'on greffe des
    attributs a la volee.
    """

    def __init__(
        self,
        game_state: Dict[str, Any],
        *,
        current_mode_code: str = "pvp",
        unit_registry: Optional[UnitRegistry] = None,
    ) -> None:
        self.game_state = game_state
        self.current_mode_code = current_mode_code
        self.unit_registry = unit_registry
        self.state_manager = _StateManagerStub()



def test_make_json_serializable_handles_tuple_keys_set_and_object_dict() -> None:
    class Dummy:
        def __init__(self) -> None:
            self.value = {("a", 1): {1, 2}}

    result = cast(Dict[str, Any], api_server.make_json_serializable(Dummy()))
    assert "a,1" in result["value"]
    assert sorted(result["value"]["a,1"]) == [1, 2]


def test_make_json_serializable_numpy_array_and_scalar() -> None:
    np = pytest.importorskip("numpy")
    assert api_server.make_json_serializable(np.array([1, 2, 3])) == [1, 2, 3]
    assert api_server.make_json_serializable(np.int64(7)) == 7
    assert api_server.make_json_serializable(np.float64(3.5)) == 3.5


def test_api_json_response_orjson_encodes_set_and_numpy_without_pre_walk() -> None:
    if getattr(api_server, "_orjson", None) is None:
        pytest.skip("orjson not available")
    orjson = pytest.importorskip("orjson")
    np = pytest.importorskip("numpy")
    payload = {
        "ok": True,
        "tags": {1, 2, 3},
        "arr": np.array([[1, 2], [3, 4]], dtype=np.int64),
    }
    resp = api_server.api_json_response(payload)
    assert require_present(resp.mimetype, "mimetype").startswith("application/json")
    out = orjson.loads(resp.get_data())
    assert out["ok"] is True
    assert set(out["tags"]) == {1, 2, 3}
    assert out["arr"] == [[1, 2], [3, 4]]


def test_game_state_for_json_removes_heavy_engine_keys() -> None:
    engine_instance = _EngineStub(
        {"wall_hexes": {(1, 2)}, "weapon_damage_table": {}, "x": 3, "terrain_areas": [], "units_cache": {}}
    )
    state = api_server._game_state_for_json(engine_instance)
    assert "wall_hexes" not in state
    assert "weapon_damage_table" not in state
    assert state["x"] == 3


def test_game_state_for_json_drops_footprint_zone_when_mask_loops_present() -> None:
    engine_instance = _EngineStub(
        {
            "phase": "move",
            "terrain_areas": [],
            "units_cache": {},
            "move_preview_footprint_zone": {(1, 2), (3, 4)},
            "move_preview_footprint_mask_loops": [[[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]]],
        }
    )
    state = api_server._game_state_for_json(engine_instance)
    assert "move_preview_footprint_zone" not in state
    assert state["move_preview_footprint_mask_loops"] is not None
    assert isinstance(state["move_preview_footprint_mask_loops_hash"], str)
    assert len(state["move_preview_footprint_mask_loops_hash"]) == 64
    assert state["move_preview_footprint_mask_loops"][0][0] == 0.0


def test_game_state_for_json_omits_large_mask_loops_when_client_hash_matches() -> None:
    loop = [[float(i), 0.0] for i in range(70)]
    loops = [loop]
    engine_instance = _EngineStub(
        {
            "phase": "move",
            "terrain_areas": [],
            "units_cache": {},
            "move_preview_footprint_zone": {(0, 0)},
            "move_preview_footprint_mask_loops": loops,
        }
    )
    state1 = api_server._game_state_for_json(engine_instance, mask_loops_client_hash=None)
    h = state1["move_preview_footprint_mask_loops_hash"]
    assert isinstance(h, str)
    state2 = api_server._game_state_for_json(engine_instance, mask_loops_client_hash=h)
    assert state2.get("move_preview_footprint_mask_loops_unchanged") is True
    assert state2.get("move_preview_footprint_mask_loops") is None


def test_game_state_for_json_does_not_omit_small_mask_loops_even_if_hash_matches() -> None:
    loops = [[[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]]]
    engine_instance = _EngineStub(
        {
            "phase": "move",
            "terrain_areas": [],
            "units_cache": {},
            "move_preview_footprint_mask_loops": loops,
        }
    )
    state1 = api_server._game_state_for_json(engine_instance)
    h = state1["move_preview_footprint_mask_loops_hash"]
    state2 = api_server._game_state_for_json(engine_instance, mask_loops_client_hash=h)
    assert state2.get("move_preview_footprint_mask_loops_unchanged") is not True
    assert state2.get("move_preview_footprint_mask_loops") is not None


def test_game_state_for_json_strips_internal_engine_keys() -> None:
    engine_instance = _EngineStub(
        {
            "phase": "move",
            "terrain_areas": [],
            "units_cache": {},
            "turn": 1,
            "units_cache_prev": {"1": {"col": 0, "row": 0}},
            "last_compliance_data": {"x": 1},
            "_best_weapon_cache": {"k": "v"},
            "console_logs": ["noise"],
        }
    )
    state = api_server._game_state_for_json(engine_instance)
    assert state["turn"] == 1
    assert "units_cache_prev" not in state
    assert "last_compliance_data" not in state
    assert "_best_weapon_cache" not in state
    assert "console_logs" not in state


def test_game_state_for_json_drops_preview_hexes_when_move_pool_present() -> None:
    """``preview_hexes`` est un alias du pool d’ancres — ne pas dupliquer le JSON."""
    anchors = [[1, 2], [3, 4]]
    engine_instance = _EngineStub(
        {
            "phase": "move",
            "terrain_areas": [],
            "units_cache": {},
            "valid_move_destinations_pool": anchors,
            "preview_hexes": list(anchors),
        }
    )
    state = api_server._game_state_for_json(engine_instance)
    assert state["valid_move_destinations_pool"] == anchors
    assert "preview_hexes" not in state


def test_game_state_for_json_omits_objectives_when_for_post_action() -> None:
    engine_instance = _EngineStub(
        {
            "phase": "move",
            "terrain_areas": [],
            "units_cache": {},
            "objectives": [{"name": "A", "hexes": [{"col": 0, "row": 0}]}],
            "turn": 1,
        }
    )
    full = api_server._game_state_for_json(engine_instance, for_post_action=False)
    assert full.get("objectives") is not None
    slim = api_server._game_state_for_json(engine_instance, for_post_action=True)
    assert "objectives" not in slim


def test_slim_execute_action_result_drops_duplicate_move_pool_fields() -> None:
    r = api_server._slim_execute_action_result_for_api(
        {
            "unit_activated": True,
            "unitId": "3",
            "waiting_for_player": True,
            "valid_destinations": [[1, 2]],
            "preview_data": {"x": 1},
        },
        {"action": "activate_unit", "unitId": "3"},
    )
    assert "valid_destinations" not in r
    assert "preview_data" not in r
    assert r.get("unitId") == "3"
    gym = api_server._slim_execute_action_result_for_api(
        {
            "unit_activated": True,
            "unitId": "3",
            "waiting_for_player": False,
            "valid_destinations": [[1, 2]],
        },
        {"action": "activate_unit", "unitId": "3"},
    )
    assert "valid_destinations" in gym


def test_game_state_for_json_excludes_config_blob() -> None:
    engine_instance = _EngineStub(
        {
            "phase": "move",
            "terrain_areas": [],
            "units_cache": {},
            "config": {"game_rules": {"max_turns": 5}, "board": {"x": 1}},
            "turn": 1,
        }
    )
    state = api_server._game_state_for_json(engine_instance)
    assert state["turn"] == 1
    assert "config" not in state


def test_game_state_for_json_excludes_weapon_damage_table_and_per_player_adjacent_caches() -> None:
    engine_instance = _EngineStub(
        {
            "phase": "move",
            "terrain_areas": [],
            "units_cache": {},
            "weapon_damage_table": {"A": {"B": {"C": 1}}},
            "enemy_adjacent_hexes_player_1": {(1, 2), (3, 4)},
            "enemy_adjacent_counts_player_2": {"x": 3},
            "turn": 1,
        }
    )
    state = api_server._game_state_for_json(engine_instance)
    assert state["turn"] == 1
    assert "weapon_damage_table" not in state
    assert "enemy_adjacent_hexes_player_1" not in state
    assert "enemy_adjacent_counts_player_2" not in state


def test_game_state_for_json_excludes_move_preview_border() -> None:
    engine_instance = _EngineStub(
        {
            "phase": "move",
            "terrain_areas": [],
            "units_cache": {},
            "valid_move_destinations_pool": [[1, 2], [3, 4]],
            "move_preview_border": [[1, 2]],
        }
    )
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
    # Pas de `cast` : `_attach_player_types` declare son besoin reel (`_PlayerTypesSource`),
    # que ce stub satisfait structurellement — donc pyright VERIFIE le stub au lieu de le croire.
    engine_instance = _EngineStub({}, current_mode_code="pve")
    serializable_state: Dict[str, Any] = {}
    api_server._attach_player_types(serializable_state, engine_instance)
    assert serializable_state["player_types"]["2"] == "ai"
    assert engine_instance.game_state["current_mode_code"] == "pve"


def test_attach_player_types_rejects_invalid_mode() -> None:
    engine_instance = _EngineStub({}, current_mode_code="invalid")
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
        """Mauvais joueur : le helper doit sortir AVANT de piloter le moteur.

        `execute_semantic_action` est declare (le contrat `_EndPhaseEngine` l'exige) mais leve :
        le test verrouille ainsi qu'aucune action n'est executee sur le mauvais joueur.
        """

        def __init__(self) -> None:
            self.game_state: Dict[str, Any] = {"phase": "move", "current_player": 1}

        def execute_semantic_action(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
            raise AssertionError(f"aucune action ne doit etre executee pour le mauvais joueur : {action}")

    engine_instance = DummyEngine()
    success, result = api_server._execute_end_phase_action(engine_instance, {"player": 2})
    assert success is False
    assert result["error"] == "wrong_player_end_phase"


def test_execute_end_phase_action_processes_pool_and_advances_phase() -> None:
    class DummyEngine:
        def __init__(self) -> None:
            self.game_state: Dict[str, Any] = {
                "phase": "move",
                "current_player": 1,
                "move_activation_pool": ["u1"],
            }

        def execute_semantic_action(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
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


def test_game_state_for_json_triggers_objective_control_refresh() -> None:
    """La sérialisation d'état déclenche le rafraîchissement de frontière du contrôle d'objectif.

    Règle 14.02 : le contrôle est réévalué à la fin de chaque phase/tour. Côté PvP, c'est ici que
    la frontière est détectée — via `refresh_objective_control_on_boundary`, la MÊME fonction que
    le chemin gym (avant, l'API portait sa propre détection inline). Ce test verrouille l'appel :
    s'il disparaît, le contrôle d'objectif du PvP se fige silencieusement.
    """
    engine_instance = _EngineStub(
        {"phase": "move", "turn": 1, "terrain_areas": [], "units_cache": {}}
    )

    api_server._game_state_for_json(engine_instance)
    api_server._game_state_for_json(engine_instance)

    assert engine_instance.state_manager.boundary_refresh_calls == 2


def test_build_units_from_scenario_army_folds_attached_characters() -> None:
    """`change_roster` sur une army au FORMAT SCENARIO doit construire les unites.

    Ce chemin appelait `_fold_attached_characters` sans son argument `unit_registry` : toute
    tentative de changer de roster avec un fichier au format scenario levait un TypeError avant
    d'avoir construit la moindre unite. Le test verrouille l'appel ET son effet metier (regle 19 :
    un character `attached_squad` n'existe plus comme unite separee, il est replie dans sa squad).
    """
    import json
    from pathlib import Path

    army_path = (
        Path(__file__).resolve().parents[3]
        / "config/board/44x60x5/scenario/scenario_pvp.json"
    )
    army_cfg = json.loads(army_path.read_text())
    raw_units = army_cfg["units"]
    attached_count = sum(1 for u in raw_units if "attached_squad" in u)
    assert attached_count > 0, "fixture invalide : ce scenario doit porter des characters attaches"

    # Pas de `cast` : `_build_units_from_scenario_army` declare desormais son besoin reel
    # (`_UnitRegistryHolder`), que ce stub satisfait structurellement.
    engine_instance = _EngineStub({}, unit_registry=UnitRegistry())

    built, next_id = api_server._build_units_from_scenario_army(engine_instance, army_cfg, 1, 1)

    assert len(built) == len(raw_units) - attached_count
    assert next_id == 1 + len(built)
    assert {u["player"] for u in built} == {1}
    # Deploiement actif : positions sentinelles, le joueur place ensuite.
    assert all(u["col"] == -1 and u["row"] == -1 for u in built)


def test_build_units_from_scenario_army_requires_unit_registry() -> None:
    """Sans registre, on leve explicitement au lieu de construire des unites incompletes."""
    engine_instance = _EngineStub({}, unit_registry=None)
    with pytest.raises(ValueError, match=r"unit_registry is required"):
        api_server._build_units_from_scenario_army(engine_instance, {"units": []}, 1, 1)


# ---------------------------------------------------------------------------
# Réserves stratégiques (20.01) — ce que l'UI PvP affiche et ce qu'elle refuse
# ---------------------------------------------------------------------------


def test_strategic_reserves_summary_reports_points_per_player() -> None:
    """Le ratio « 120/250 » du conteneur PvP vient du MOTEUR, pas d'un calcul TypeScript."""
    game_state = {
        "points_limit": 500,
        "units": [
            {"id": "1", "player": 1, "VALUE": 120, "in_strategic_reserves": True},
            {"id": "2", "player": 1, "VALUE": 80, "in_strategic_reserves": False},
            {"id": "3", "player": 2, "VALUE": 60, "in_strategic_reserves": True},
        ],
    }
    summary = api_server._strategic_reserves_summary(game_state)
    assert summary["1"]["used_points"] == 120
    assert summary["1"]["cap_points"] == 250
    assert summary["2"]["used_points"] == 60
    assert summary["2"]["cap_points"] == 250
    # 20.04 — le round de destruction est LU du moteur : le popup « dernier tour » du client s'y
    # accroche au lieu de recoder « 3 ».
    assert summary["last_round"] == movement_handlers.STRATEGIC_RESERVES_LAST_ROUND


def test_strategic_reserves_summary_only_offers_units_the_engine_would_accept() -> None:
    """`placeable_unit_ids` = ce que `deployment_place_in_strategic_reserves` accepterait.

    BORNE du plafond (20.01) : avec 120 pts déjà engagés sur un plafond de 250, une unité de
    130 pts tient encore (130 <= 130) et une de 131 ne tient plus. Une FORTIFICATION ne tient
    JAMAIS, quelle que soit la place restante — c'est ce test-là que le client ne peut pas faire.
    """
    game_state = {
        "points_limit": 500,
        "units": [
            {
                "id": "1", "player": 1, "VALUE": 120, "in_strategic_reserves": True,
                "deployed_on_turn": None, "UNIT_KEYWORDS": [],
            },
            {
                "id": "2", "player": 1, "VALUE": 130, "in_strategic_reserves": False,
                "deployed_on_turn": None, "UNIT_KEYWORDS": [],
            },
            {
                "id": "3", "player": 1, "VALUE": 131, "in_strategic_reserves": False,
                "deployed_on_turn": None, "UNIT_KEYWORDS": [],
            },
            {
                "id": "4", "player": 1, "VALUE": 10, "in_strategic_reserves": False,
                "deployed_on_turn": None,
                "UNIT_KEYWORDS": [{"keywordId": "Fortification"}],
            },
        ],
        "deployment_state": {"deployable_units": {1: ["2", "3", "4"], 2: []}},
    }
    game_state["unit_by_id"] = {u["id"]: u for u in game_state["units"]}
    summary = api_server._strategic_reserves_summary(game_state)
    assert summary["1"]["placeable_unit_ids"] == ["2"]
    assert summary["2"]["placeable_unit_ids"] == []


def test_strategic_reserves_summary_offers_nothing_once_deployment_is_over() -> None:
    """Hors déploiement il n'y a plus rien à mettre en réserves : la liste est vide, pas absente."""
    summary = api_server._strategic_reserves_summary({"points_limit": 500, "units": []})
    assert summary["1"]["placeable_unit_ids"] == []
    assert summary["2"]["placeable_unit_ids"] == []


def test_strategic_reserves_summary_closes_the_rule_without_battle_size() -> None:
    """Sans `scale`, le plafond de 50 % est invérifiable : plafond 0, donc aucun dépôt possible.

    C'est la RÈGLE qui ferme (20.01 parle d'un pourcentage de la taille de bataille), pas un
    défaut d'affichage rattrapé par une valeur arbitraire.
    """
    summary = api_server._strategic_reserves_summary({"points_limit": None, "units": []})
    assert summary["1"]["cap_points"] == 0
    assert summary["2"]["cap_points"] == 0


def test_maybe_precompute_ingress_pools_is_a_noop_outside_move_phase() -> None:
    """Le rechauffage n'a lieu qu'en phase de mouvement : ailleurs, il ne LIT meme pas l'etat."""
    class _Boom(dict):
        def __missing__(self, key: str) -> Any:  # pragma: no cover - garde de test
            raise AssertionError(f"état lu hors phase move (clé {key!r})")

    state = _Boom({"phase": "shoot", "current_player": 1})
    api_server._maybe_precompute_ingress_pools(_EngineStub(state))
