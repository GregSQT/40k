"""Contrat /api/board_config — structure des groupes de murs.

Vérifie que chaque groupe de murs dans `walls` expose ses hexagones expandus
et son type, et que leur union coincide avec `wall_hexes`.
"""

from __future__ import annotations

import pytest
from services.api_server import app
from tests.integration.pvp._shared import (
    _TEST_AUTH_USER,
    _TEST_PERMISSIONS,
    _in_memory_write_cursor,
    INTEGRATION_SCENARIO,
)
import services.api_server as api_server

pytestmark = pytest.mark.integration

SCENARIO_WITH_WALLS = "config/board/44x60x5/scenario/scenario_pvp_mc1.json"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api_server, "_get_authenticated_user_or_response", lambda: (_TEST_AUTH_USER, None))
    monkeypatch.setattr(api_server, "_resolve_permissions_for_profile", lambda _conn, _pid: _TEST_PERMISSIONS)
    monkeypatch.setattr(api_server, "auth_db_write_cursor", _in_memory_write_cursor)
    monkeypatch.setattr(api_server, "_SNAPSHOT_PERSIST_ENABLED", False)
    monkeypatch.setattr(api_server, "_AUTOSAVE_ENABLED", False)
    with app.test_client() as c:
        yield c


def test_board_config_walls_groups_have_hexes_and_type(client):
    """Chaque groupe de murs expose type (light|dense) et hexes non vide.

    wall_hexes == union des hexes de tous les groupes.
    """
    resp = client.get(
        "/api/config/board",
        query_string={"scenario_file": SCENARIO_WITH_WALLS},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    config = resp.get_json()["config"]

    walls = config.get("walls", [])
    wall_hexes_flat = config.get("wall_hexes", [])

    assert len(walls) > 0, "Ce scénario doit avoir des murs"

    union_from_groups: list[list[int]] = []
    for i, group in enumerate(walls):
        assert "type" in group, f"walls[{i}] manque 'type'"
        assert group["type"] in ("light", "dense"), (
            f"walls[{i}].type={group['type']!r} invalide"
        )
        assert "hexes" in group, f"walls[{i}] manque 'hexes'"
        hexes = group["hexes"]
        assert isinstance(hexes, list), f"walls[{i}].hexes doit être une liste"
        assert len(hexes) > 0, f"walls[{i}].hexes ne doit pas être vide"
        for hi, h in enumerate(hexes):
            assert isinstance(h, list) and len(h) == 2, (
                f"walls[{i}].hexes[{hi}] doit être [col, row]"
            )
        union_from_groups.extend(hexes)

    # Tous les hexes des groupes sont dans wall_hexes.
    wall_hexes_set = {tuple(h) for h in wall_hexes_flat}
    for h in union_from_groups:
        assert tuple(h) in wall_hexes_set, (
            f"hex {h} présent dans un groupe mais absent de wall_hexes"
        )

    # wall_hexes n'a pas de surplus hors des groupes.
    group_set = {tuple(h) for h in union_from_groups}
    for h in wall_hexes_flat:
        assert tuple(h) in group_set, (
            f"hex {h} dans wall_hexes mais dans aucun groupe"
        )


def test_board_config_walls_none_json_produces_empty_walls(client):
    """Le plateau sans scénario utilise walls-none.json : walls absent ou vide."""
    resp = client.get("/api/config/board")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    config = resp.get_json()["config"]
    walls = config.get("walls", [])
    # walls-none.json a une liste vide → pas de groupes, walls absent ou [].
    assert walls == [] or walls is None, f"Attendu vide, obtenu: {walls}"
