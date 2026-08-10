"""Tests — conversion des données de plateau vers une résolution plus grossière.

`board_ref` déclare la résolution NATIVE des fichiers partagés (murs, terrain). Quand le
plateau actif est le même plateau physique à une résolution plus grossière (banc x1 : 1 hex =
1 pouce), les coordonnées sont converties au chargement. Une seule source de vérité : aucun
jeu de terrain dupliqué par résolution.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Dict, Iterator

import pytest

from engine.game_state import GameStateManager

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BANK_SCEN = str(
    PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent" / "scenarios" / "training"
    / "scenario_training_armageddon1.json"
)


@pytest.fixture
def gsm() -> GameStateManager:
    return GameStateManager(config={})


@pytest.fixture
def board_x1() -> Iterator[None]:
    """Active le plateau 44x60x1 le temps du test (le cache du loader est indexé par override)."""
    previous = os.environ.get("W40K_BOARD_PATH")
    os.environ["W40K_BOARD_PATH"] = "board/44x60x1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("W40K_BOARD_PATH", None)
        else:
            os.environ["W40K_BOARD_PATH"] = previous


@pytest.fixture
def board_x5() -> Iterator[None]:
    previous = os.environ.get("W40K_BOARD_PATH")
    os.environ["W40K_BOARD_PATH"] = "board/44x60x5"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("W40K_BOARD_PATH", None)
        else:
            os.environ["W40K_BOARD_PATH"] = previous


# ── Rapport d'échelle ───────────────────────────────────────────────────────────

def test_ratio_is_one_when_resolutions_match(gsm, board_x5) -> None:
    """Plateau actif == plateau des données : aucune conversion (neutralité PvP/x5)."""
    assert gsm._board_ref_downscale_ratio(BANK_SCEN, "44x60x5") == 1


def test_ratio_five_from_x5_data_to_x1_board(gsm, board_x1) -> None:
    assert gsm._board_ref_downscale_ratio(BANK_SCEN, "44x60x5") == 5


def test_ratio_rejects_a_different_physical_board(gsm, board_x1) -> None:
    """44x60x10 fait 360×312 : ÷10 donne 36×31, pas 44×60. Erreur explicite, pas de conversion."""
    with pytest.raises(ValueError, match="réduit pas|même plateau physique|hors plateau"):
        gsm._board_ref_downscale_ratio(BANK_SCEN, "44x60x10")


# ── Conversion des coordonnées ─────────────────────────────────────────────────

def _terrain_fixture() -> Dict[str, Any]:
    return {
        "terrain_id": "t",
        "terrain": [{
            "id": "a", "shape": "polygon", "obscuring": True, "objective": True,
            "vertices": [[25, 30], [60, 30], [60, 90]],
            "floors": [{"level": 1, "height_inches": 3, "vertices": [[55, 85], [55, 65], [40, 65]]}],
        }],
        "walls": [{"name": "w", "type": "dense", "segments": [[[28, 33], [43, 33]]]}],
        "icons": [{"id": 1, "path": "x.png", "center": [40, 60], "size": 80, "alpha": 0.7}],
        "deployment_zones": [{"id": "1", "shape": "polygon", "vertices": [[0, 300], [220, 150], [220, 300]]}],
    }


def _nearest_coarse_cell(col: int, row: int, ratio: int, cols: int, rows: int) -> list:
    """Oracle indépendant : balaie TOUT le plateau grossier et garde le centre le plus proche.

    Même définition géométrique que le moteur (odd-q, colonnes impaires décalées d'une
    demi-hauteur), mais sans la fenêtre de recherche de `downscale_cell` — ce qui valide aussi
    cette fenêtre.
    """
    x = col * 1.5 / ratio
    y = (row * math.sqrt(3.0) + (col % 2) * math.sqrt(3.0) / 2) / ratio
    best: list = []
    best_d = math.inf
    for c in range(cols):
        for r in range(rows):
            hx = c * 1.5
            hy = r * math.sqrt(3.0) + (c % 2) * math.sqrt(3.0) / 2
            d = (hx - x) ** 2 + (hy - y) ** 2
            if d < best_d:
                best, best_d = [c, r], d
    return best


def test_downscale_matches_an_independent_geometric_oracle() -> None:
    """La conversion suit la géométrie odd-q, pas une division par axe.

    Diviser col et row séparément ignore le décalage d'une demi-hauteur des colonnes impaires
    et déplace ~28 % des points d'une case (mesuré sur terrain-mc1).
    """
    out = GameStateManager._downscale_terrain_data(_terrain_fixture(), 5)
    source = _terrain_fixture()
    assert out["terrain"][0]["vertices"] == [
        _nearest_coarse_cell(c, r, 5, 44, 60) for c, r in source["terrain"][0]["vertices"]
    ]
    assert out["walls"][0]["segments"][0] == [
        _nearest_coarse_cell(c, r, 5, 44, 60) for c, r in source["walls"][0]["segments"][0]
    ]
    # Contrôle qu'un point au moins diffère de la division naïve, sinon le test ne prouve rien.
    naive = [[round(c / 5), round(r / 5)] for c, r in source["walls"][0]["segments"][0]]
    assert out["walls"][0]["segments"][0] != naive


def test_downscale_converts_only_coordinate_fields() -> None:
    out = GameStateManager._downscale_terrain_data(_terrain_fixture(), 5)
    area = out["terrain"][0]
    # Hauteur en POUCES : jamais en subhex, donc jamais convertie.
    assert area["floors"][0]["height_inches"] == 3
    assert area["obscuring"] is True and area["objective"] is True
    assert area["id"] == "a" and area["shape"] == "polygon"
    assert len(area["floors"][0]["vertices"]) == 3
    assert out["walls"][0]["type"] == "dense" and out["walls"][0]["name"] == "w"
    assert len(out["deployment_zones"][0]["vertices"]) == 3
    # Icône : le centre est en CASES (converti), la taille est en PIXELS D'ÉCRAN (invariante).
    # Un plateau occupe la même surface écran à toutes ses résolutions — `hex_radius` et `margin`
    # sont multipliés là où `cols`/`rows` sont divisés — donc une icône de 80 px reste 80 px.
    # Ce test exigeait 400 : il verrouillait le défaut qui affichait les icônes du plateau x1
    # cinq fois trop grandes.
    assert out["icons"][0]["center"] == _nearest_coarse_cell(40, 60, 5, 44, 60)
    assert out["icons"][0]["size"] == 80
    assert out["icons"][0]["alpha"] == 0.7
    assert out["icons"][0]["path"] == "x.png"


def test_downscale_ratio_one_is_identity() -> None:
    src = _terrain_fixture()
    assert GameStateManager._downscale_terrain_data(src, 1) == src


def test_downscale_does_not_mutate_the_source() -> None:
    src = _terrain_fixture()
    GameStateManager._downscale_terrain_data(src, 5)
    assert src["terrain"][0]["vertices"] == [[25, 30], [60, 30], [60, 90]]


def test_collapsed_segment_survives_as_one_hex() -> None:
    """Un mur plus court qu'un hex après conversion devient une case, il ne disparaît pas."""
    data = {"walls": [{"name": "w", "segments": [[[10, 10], [12, 10]]]}]}
    out = GameStateManager._downscale_terrain_data(data, 5)
    assert out["walls"][0]["segments"] == [[[2, 2], [2, 2]]]


# ── Bout en bout sur le vrai terrain ───────────────────────────────────────────

def test_real_terrain_fits_the_x1_board(gsm, board_x1) -> None:
    """terrain-mc1 chargé sur 44x60 : murs et zones de déploiement dans les bornes."""
    walls = gsm._load_terrain_walls_from_ref("terrain-mc1.json", BANK_SCEN, board_ref="44x60x5")
    assert walls, "terrain-mc1 doit produire des murs"
    assert all(0 <= c < 44 and 0 <= r < 60 for c, r in walls)

    zones = gsm._load_deployment_zones_from_ref("terrain-mc1.json", BANK_SCEN, board_ref="44x60x5")
    assert zones is not None and len(zones) == 2
    for zone in zones:
        for col, row in zone["vertices"]:
            assert 0 <= col <= 44 and 0 <= row <= 60


def test_inline_wall_hexes_are_converted_too(board_x1, tmp_path) -> None:
    """Les murs écrits DANS le scénario suivent la même conversion que les murs partagés.

    Sans ça, ils resteraient les seuls en coordonnées natives sur un plateau réduit — le trou
    exact que cette mécanique est censée fermer.
    """
    import json as _json

    from ai.unit_registry import UnitRegistry
    from config_loader import get_config_loader

    scenario = {
        "primary_objectives": ["objectives_control"],
        "board_ref": "44x60x5",
        "terrain_ref": "terrain-mc1.json",
        "deployment_type": "fixed",
        "wall_hexes": [[100, 150], [105, 150]],
        "units": [
            {"id": "1", "player": 1, "unit_type": "Intercessor", "col": 10, "row": 20},
            {"id": "2", "player": 2, "unit_type": "Intercessor", "col": 30, "row": 40},
        ],
    }
    path = tmp_path / "scenario_inline_walls.json"
    path.write_text(_json.dumps(scenario), encoding="utf-8")

    loader = get_config_loader()
    manager = GameStateManager(
        {"board": loader.get_board_config(), "controlled_player": 1}, UnitRegistry()
    )
    result = manager.load_units_from_scenario(str(path), UnitRegistry())
    walls = [tuple(w) for w in (result.get("wall_hexes") or [])]
    assert (100, 150) not in walls and (105, 150) not in walls
    for expected in ((100, 150), (105, 150)):
        assert tuple(_nearest_coarse_cell(expected[0], expected[1], 5, 44, 60)) in walls


# ── Coordonnées de roster (placement fixe) ─────────────────────────────────────

def _fixed_unit(unit_id: str, player: int, cells: list) -> Dict[str, Any]:
    return {
        "id": unit_id, "player": player, "unit_type": "Intercessor",
        "col": cells[0][0], "row": cells[0][1],
        "models": [
            {"unit_type": "Intercessor", "col": c, "row": r} for c, r in cells
        ],
    }


def _load_fixed_scenario(tmp_path, units: list):
    import json as _json

    from ai.unit_registry import UnitRegistry
    from config_loader import get_config_loader

    scenario = {
        "primary_objectives": ["objectives_control"],
        "board_ref": "44x60x5",
        "terrain_ref": "terrain-mc1.json",
        "deployment_type": "fixed",
        "units": units,
    }
    path = tmp_path / "scenario_fixed.json"
    path.write_text(_json.dumps(scenario), encoding="utf-8")
    loader = get_config_loader()
    manager = GameStateManager(
        {"board": loader.get_board_config(), "controlled_player": 1}, UnitRegistry()
    )
    return manager.load_units_from_scenario(str(path), UnitRegistry())


def test_squad_models_keep_distinct_cells_after_downscale(board_x1, tmp_path) -> None:
    """5 subhex d'écart deviennent 0 hex : sans relayout, l'escouade s'écrase sur une case."""
    cells = [(100, 150), (100, 154), (100, 158), (104, 150), (104, 154), (96, 150)]
    result = _load_fixed_scenario(tmp_path, [
        _fixed_unit("1", 1, cells),
        _fixed_unit("2", 2, [(160, 220), (160, 224)]),
    ])
    squad = next(u for u in result["units"] if str(u["id"]) == "1")
    placed = [(m["col"], m["row"]) for m in squad["models"]]
    assert len(set(placed)) == len(cells), f"figurines superposées : {placed}"
    assert all(0 <= c < 44 and 0 <= r < 60 for c, r in placed)


def test_anchor_follows_first_model(board_x1, tmp_path) -> None:
    """Invariant ancre == models[0], sur lequel repose build_units_cache."""
    result = _load_fixed_scenario(tmp_path, [
        _fixed_unit("1", 1, [(100, 150), (100, 154), (104, 150)]),
        _fixed_unit("2", 2, [(160, 220)]),
    ])
    squad = next(u for u in result["units"] if str(u["id"]) == "1")
    assert (squad["col"], squad["row"]) == (squad["models"][0]["col"], squad["models"][0]["row"])


def test_two_squads_do_not_overlap_after_downscale(board_x1, tmp_path) -> None:
    """Deux escouades voisines à x5 ne doivent pas se marcher dessus une fois réduites."""
    result = _load_fixed_scenario(tmp_path, [
        _fixed_unit("1", 1, [(100, 150), (100, 154), (104, 150)]),
        _fixed_unit("2", 2, [(102, 152), (106, 152), (98, 152)]),
    ])
    cells = [
        (m["col"], m["row"]) for u in result["units"] for m in u["models"]
    ]
    assert len(set(cells)) == len(cells), f"chevauchement entre escouades : {cells}"


def test_downscale_is_deterministic(board_x1, tmp_path) -> None:
    units = [_fixed_unit("1", 1, [(100, 150), (100, 154), (104, 150)]),
             _fixed_unit("2", 2, [(160, 220)])]
    first = _load_fixed_scenario(tmp_path, units)
    second = _load_fixed_scenario(tmp_path, units)
    assert [(m["col"], m["row"]) for u in first["units"] for m in u["models"]] == \
           [(m["col"], m["row"]) for u in second["units"] for m in u["models"]]


def test_squads_stay_coherent_on_the_real_scenario(board_x1) -> None:
    """Le relayout compact ne casse pas la cohérence d'escouade (03.03).

    Le roster d'agent est tiré au hasard entre SM et Orks à chaque chargement : plusieurs seeds
    couvrent les deux compositions.
    """
    from ai.unit_registry import UnitRegistry
    from engine.phase_handlers.shared_utils import validate_squad_coherency
    from engine.w40k_core import W40KEngine

    engine = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1",
        controlled_agent="ArmageddonAgent", scenario_file=str(BANK_SCEN),
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
        training_n_envs=1,  # UN environnement joue en serie (engine/episode_schedule.py)
    )
    # Le RELAYOUT est ce qui est mesuré ici : il n'existe qu'en placement FIXE (positions du
    # scénario). `deployment_mode_schedule` du profil `x1` tire fixed↔active par épisode ; dès
    # que son `active_ratio_start` est non nul, une graine peut rendre un plateau où AUCUNE
    # figurine n'est encore posée (toutes à (-1,-1)) et le test observe alors autre chose que ce
    # qu'il annonce. Le mode est donc imposé, jamais espéré d'un tirage (cf.
    # `test_auto_deployment_positions`).
    assert engine.training_config is not None
    engine.training_config = dict(engine.training_config)
    engine.training_config["deployment_mode_schedule"] = {
        "enabled": True, "training_only": False,
        "active_ratio_start": 0.0, "active_ratio_end": 0.0,
        "schedule": "linear", "freeze_after_progress": 1.0,
    }
    for seed in range(4):
        engine.reset(seed=seed)
        state = engine.game_state
        assert state["deployment_mode_schedule_mode"] == "auto", f"seed {seed}: mode non imposé"
        # `auto` (ex-`fixed`) joue une VRAIE phase de déploiement : les figurines ne sont posées
        # qu'à sa sortie, alors que les positions du roster les posaient dès le reset. Sans cette
        # boucle, `cells` serait vide et l'assertion « aucune figurine posée » sauterait —
        # le relayout mesuré ici ne serait plus observé du tout.
        import numpy as _np

        _steps = 0
        while _steps < 400 and str(state["phase"]) == "deployment":
            _legal = _np.flatnonzero(engine.get_action_mask())
            assert _legal.size > 0, f"seed {seed}: plus aucune action légale en déploiement"
            engine.step(int(_legal[0]))
            _steps += 1
        # Les figurines HORS TABLE (réserves 20.01, tirage `training_random`) partagent toutes la
        # sentinelle (-1,-1) : les compter ferait voir une superposition là où il n'y a
        # simplement pas de position. Le relayout mesuré ici ne concerne que les figurines posées.
        cells = [
            (m["col"], m["row"]) for m in state["models_cache"].values() if int(m["col"]) >= 0
        ]
        assert cells, f"seed {seed}: aucune figurine posée — le relayout n'est pas observé"
        assert len(cells) == len(set(cells)), f"seed {seed}: figurines superposées"
        incoherent = [
            sid for sid in state["squad_models"] if not validate_squad_coherency(state, str(sid))
        ]
        assert not incoherent, f"seed {seed}: escouades incohérentes {incoherent}"


def test_downscale_refuses_a_multi_hex_footprint_board(gsm, board_x5, tmp_path) -> None:
    """Conversion de roster vers un plateau à empreintes multi-hex : refus explicite.

    Le placement converti raisonne par CASE ; sur un plateau à socles multi-hex, ne réserver que
    la case centrale laisserait deux socles se chevaucher en silence. Aucune donnée du dépôt
    n'atteint ce cas (les rosters sont en x5, la seule cible plus grossière est x1), d'où un
    refus plutôt qu'un placement par empreinte non testé.
    """
    import json as _json

    from ai.unit_registry import UnitRegistry
    from config_loader import get_config_loader

    scenario = {
        "primary_objectives": ["objectives_control"],
        "board_ref": "44x60x5",
        "terrain_ref": "terrain-mc1.json",
        "units": [
            {"id": "1", "player": 1, "unit_type": "Intercessor", "col": 100, "row": 150},
            {"id": "2", "player": 2, "unit_type": "Intercessor", "col": 160, "row": 220},
        ],
    }
    path = tmp_path / "scenario_multi_hex.json"
    path.write_text(_json.dumps(scenario), encoding="utf-8")
    loader = get_config_loader()
    manager = GameStateManager(
        {"board": loader.get_board_config(), "controlled_player": 1}, UnitRegistry()
    )
    # Aucune paire de plateaux du dépôt ne produit ce cas (x10 ÷ 2 donne 180x156, pas 220x300) :
    # le rapport est donc forcé ici pour exercer la garde elle-même.
    manager._board_ref_downscale_ratio = lambda *_args, **_kwargs: 2
    with pytest.raises(ValueError, match="empreintes multi-hex"):
        manager.load_units_from_scenario(str(path), UnitRegistry())


def test_non_round_socle_is_normalized_at_x1(board_x1, tmp_path) -> None:
    """À x1 le socle tombe à `round`/1 — voir `test_socle_normalized_at_x1.py` pour le pourquoi.

    Ici on vérifie seulement que le chargement d'un roster converti produit bien un socle
    normalisé : `_socle_edge_primitives` indexe `size[0]` sur un ovale, et le chemin multi-hex du
    pool de move diverge de `validate_move_plan` — les deux échecs que la normalisation évite.
    """
    from ai.unit_registry import UnitRegistry

    registry = UnitRegistry()
    assert isinstance(registry.get_unit_data("WarTrakk")["BASE_SIZE"], list)
    result = _load_fixed_scenario(tmp_path, [
        {"id": "1", "player": 1, "unit_type": "WarTrakk", "col": 100, "row": 150},
        {"id": "2", "player": 2, "unit_type": "Intercessor", "col": 160, "row": 220},
    ])
    war_trakk = next(u for u in result["units"] if str(u["id"]) == "1")
    assert war_trakk["BASE_SHAPE"] == "round"
    assert war_trakk["BASE_SIZE"] == 1


def test_real_terrain_keeps_full_size_on_x5(gsm, board_x5) -> None:
    """Contrôle de non-régression : à x5 les mêmes murs restent en coordonnées natives."""
    walls = gsm._load_terrain_walls_from_ref("terrain-mc1.json", BANK_SCEN, board_ref="44x60x5")
    assert max(c for c, _ in walls) > 44, "à x5 les murs doivent dépasser les bornes du x1"
    assert all(0 <= c < 220 and 0 <= r < 300 for c, r in walls)
