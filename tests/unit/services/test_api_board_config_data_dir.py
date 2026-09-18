"""`GET /api/config/board` — le dossier qui PORTE murs et terrain suit le SCÉNARIO.

Le rendu (PvP et replay) lit terrain, icônes, zones de déploiement et segments de murs dans un
dossier de plateau qui n'est pas forcément celui qui est joué : les données sont écrites une seule
fois, à leur résolution native, et converties au chargement. Ce dossier était déduit d'une table
codée en dur indexée par `board_path`, qui imposait `44x60x5` comme source à TOUT scénario ; il est
désormais déclaré par le scénario via `board_ref`, selon la règle de
`GameStateManager._resolve_board_dir` (miroir moteur).

Le scénario du test est écrit dans un fichier temporaire sous `config/board/44x60x1/scenario/`,
supprimé en sortie : aucun code de production ne balaye ce chemin (il est toujours construit
nommément, jamais globé), donc un entraînement en cours ne peut pas le ramasser.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

import services.api_server as api_server

PROJECT_ROOT = Path(api_server.__file__).resolve().parent.parent
# Murs écrits en x1, et qui n'existent QUE sous le plateau x1 : c'est ce qui rend le test
# discriminant. Résolus dans `44x60x5` (l'ancien comportement), ils sont introuvables.
X1_WALL_REF = "tutorial_walls-01.json"


@pytest.fixture
def scenario_in_x1_board() -> Iterator[Path]:
    """Scénario déclarant `board_ref: 44x60x1`, posé le temps du test."""
    scenario_dir = PROJECT_ROOT / "config" / "board" / "44x60x1" / "scenario"
    created_dir = not scenario_dir.exists()
    scenario_dir.mkdir(parents=True, exist_ok=True)
    scenario_path = scenario_dir / "_tmp_board_ref_data_dir_test.json"
    scenario_path.write_text(
        json.dumps({"board_ref": "44x60x1", "wall_ref": X1_WALL_REF}), encoding="utf-8"
    )
    try:
        yield scenario_path
    finally:
        scenario_path.unlink(missing_ok=True)
        if created_dir:
            shutil.rmtree(scenario_dir, ignore_errors=True)


def _request(scenario_path: Path, board_path: str):
    relative = scenario_path.relative_to(PROJECT_ROOT).as_posix()
    client = api_server.app.test_client()
    return client.get(f"/api/config/board?scenario_file={relative}&board_path={board_path}")


def test_board_ref_designates_the_data_board(scenario_in_x1_board: Path) -> None:
    """`board_ref: 44x60x1` → murs lus sous 44x60x1, à l'échelle x1, sans conversion.

    Avec l'ancienne table, `board_path=x1` forçait `44x60x5` comme dossier de données : ce
    `wall_ref` n'y existe pas, la requête tombait en 404.
    """
    response = _request(scenario_in_x1_board, "x1")

    assert response.status_code == 200, response.get_json()
    config = response.get_json()["config"]
    assert (config["cols"], config["rows"], config["inches_to_subhex"]) == (44, 60, 1)

    wall_hexes = config["wall_hexes"]
    assert wall_hexes, "aucun mur chargé : le test ne prouverait rien (cf. vert vacant)"
    # Murs déjà en x1 et plateau joué en x1 → ratio 1. Une conversion ×5 parasite les tasserait
    # dans le premier cinquième du plateau, donc on vérifie qu'ils occupent bien toute la grille.
    max_col = max(col for col, _ in wall_hexes)
    assert max_col > 44 // 5, (
        f"murs confinés à max_col={max_col} sur 44 colonnes — signe d'une réduction indue"
    )
    assert all(0 <= col < 44 and 0 <= row < 60 for col, row in wall_hexes)


SCENARIO_PVP = "config/board/44x60x5/scenario/scenario_pvp.json"


def _board_config(query: str):
    return api_server.app.test_client().get(
        f"/api/config/board?scenario_file={SCENARIO_PVP}&{query}"
    )


@pytest.mark.parametrize(("inches_to_subhex", "cols", "rows"), [(1, 44, 60), (5, 220, 300)])
def test_resolution_designates_the_played_board(inches_to_subhex: int, cols: int, rows: int):
    """La RÉSOLUTION suffit à désigner le plateau : le client n'a aucun dossier à connaître.

    C'est la valeur que le moteur journalise (`Board: … inches_to_subhex=…`), donc celle que le
    replay possède sans traduction. La table des dossiers vit ici seule (`config_loader`).
    """
    response = _board_config(f"inches_to_subhex={inches_to_subhex}")

    assert response.status_code == 200, response.get_json()
    config = response.get_json()["config"]
    assert (config["cols"], config["rows"]) == (cols, rows)
    assert config["inches_to_subhex"] == inches_to_subhex


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("inches_to_subhex=3", "must be one of"),
        ("inches_to_subhex=abc", "must be an integer"),
        ("inches_to_subhex=1&board_path=x1", "mutually exclusive"),
    ],
)
def test_resolution_rejects_unusable_values(query: str, expected: str):
    """Résolution inconnue, non numérique, ou doublée d'un `board_path` → erreur explicite."""
    response = _board_config(query)

    assert response.status_code >= 400
    assert expected in response.get_json()["error"]


def test_board_ref_pointing_nowhere_is_an_explicit_error(tmp_path: Path) -> None:
    """`board_ref` inexistant → erreur nommant le dossier, jamais un repli silencieux."""
    scenario_dir = PROJECT_ROOT / "config" / "board" / "44x60x5" / "scenario"
    scenario_path = scenario_dir / "_tmp_board_ref_missing_test.json"
    scenario_path.write_text(json.dumps({"board_ref": "44x60x999"}), encoding="utf-8")
    try:
        response = _request(scenario_path, "x5_44x60")
        assert response.status_code == 404
        assert "44x60x999" in response.get_json()["error"]
    finally:
        scenario_path.unlink(missing_ok=True)


SCENARIO_CHECKLIST = "config/board/44x60x5/scenario/scenario_pvp_checklist.json"


@pytest.mark.parametrize("inches_to_subhex", [1, 5])
def test_terrain_ref_in_a_subfolder_is_served_like_the_engine_loads_it(inches_to_subhex: int) -> None:
    """`terrain_ref: divers/terrain-checklist.json` — huit scénarios du dépôt référencent un
    sous-dossier de `terrain/`, que le moteur résout (`GameStateManager._read_terrain_file`).
    La route exigeait un nom de fichier seul et répondait 400 : le front ne pouvait pas dessiner
    le plateau d'une partie que le moteur joue."""
    with open(PROJECT_ROOT / SCENARIO_CHECKLIST, encoding="utf-8") as fh:
        assert json.load(fh)["terrain_ref"].startswith("divers/"), "prémisse : sous-dossier"

    response = api_server.app.test_client().get(
        f"/api/config/board?scenario_file={SCENARIO_CHECKLIST}&inches_to_subhex={inches_to_subhex}"
    )

    assert response.status_code == 200, response.get_json()
    config = response.get_json()["config"]
    assert config["inches_to_subhex"] == inches_to_subhex
    assert config["wall_hexes"], "aucun mur : le terrain n'a pas été lu (vert vacant)"
    assert config["terrain_zones"], "aucune aire de terrain lue"
    # Même conversion que le moteur : à x1 les murs tiennent dans le premier 1/5 du plateau x5.
    assert max(row for _col, row in config["wall_hexes"]) < 60 * inches_to_subhex


@pytest.mark.parametrize(
    "terrain_ref",
    ["../walls/walls-33.json", "/etc/passwd.json", "divers/../../walls/walls-33.json"],
)
def test_terrain_ref_cannot_leave_the_terrain_folder(terrain_ref: str) -> None:
    """Le sous-dossier est admis, la traversée non : le fichier résolu doit rester sous `terrain/`."""
    scenario_dir = PROJECT_ROOT / "config" / "board" / "44x60x5" / "scenario"
    scenario_path = scenario_dir / "_tmp_terrain_ref_traversal_test.json"
    scenario_path.write_text(json.dumps({"terrain_ref": terrain_ref}), encoding="utf-8")
    try:
        response = _request(scenario_path, "x5_44x60")
        assert response.status_code == 400, response.get_json()
        assert "terrain_ref" in response.get_json()["error"]
    finally:
        scenario_path.unlink(missing_ok=True)


def test_terrain_zone_categories_are_derived_like_the_engine() -> None:
    """`obscuring` / `dense` des zones servies au front sont DÉRIVÉS des murs typés du fichier
    terrain (13.02/13.10), par la même fonction que le moteur — la clé JSON `obscuring` n'existe
    plus. Le cône LoS du front (bloqueurs = zones `obscuring`) doit lire la vérité du moteur :
    sur terrain-checklist, `ruin_west` contient des murs dense, `objective_center` aucun mur."""
    from engine.game_state import GameStateManager

    response = api_server.app.test_client().get(
        f"/api/config/board?scenario_file={SCENARIO_CHECKLIST}&inches_to_subhex=5"
    )
    assert response.status_code == 200, response.get_json()
    zones = {z["id"]: z for z in response.get_json()["config"]["terrain_zones"]}
    assert zones["ruin_west"]["obscuring"] is True and zones["ruin_west"]["dense"] is True
    assert zones["objective_center"]["obscuring"] is False
    assert zones["objective_center"]["dense"] is False

    engine_areas = {
        a["id"]: a
        for a in GameStateManager(config={})._load_terrain_areas_from_ref(
            "divers/terrain-checklist.json", str(PROJECT_ROOT / SCENARIO_CHECKLIST), board_ref="44x60x5"
        )
    }
    assert set(engine_areas) == set(zones)
    for zid, area in engine_areas.items():
        assert (zones[zid]["obscuring"], zones[zid]["dense"]) == (area["obscuring"], area["dense"]), zid
