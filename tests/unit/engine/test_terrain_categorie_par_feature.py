"""13.02 / 13.09 / 13.10 — la catégorie d'une zone de terrain se dérive de ses murs typés.

Règles lues (Documentation/40k_rules/13 Terrain.pdf) :
- 13.02 : « Each terrain FEATURE belongs to a terrain category » — la catégorie appartient à la
  feature, pas à la zone ; « terrain features sharing the same terrain area can belong to
  different terrain categories ».
- 13.09 Hidden : « within a terrain area that contains one or more DENSE terrain features ».
- 13.10 Obscuring : « Terrain areas containing one or more light or dense terrain features are
  obscuring terrain areas ».

Une seule source : le champ ``type`` ∈ {light, dense} des groupes ``walls`` du fichier terrain.
Le flag ``obscuring`` saisi à la main disparaît (clé refusée au chargement) ; ``dense`` apparaît ;
hidden exige du dense (une zone à murs light seuls donne le couvert, pas hidden — mesuré sur
terrain-mc1 : 4 zones accordaient hidden hors règle ; terrain-mc2 : 6 zones à murs typés étaient
en obscuring=false contre 13.10).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple
from unittest.mock import patch

import pytest

from engine.game_state import GameStateManager
from engine.observation_builder import ObservationBuilder
from engine.observation_entities import unit_bin_index
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config, build_game_rules

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BOARD_X5 = PROJECT_ROOT / "config" / "board" / "44x60x5"
BANK_SCEN = str(
    PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent_x1" / "scenarios" / "training"
    / "scenario_training_armageddon1.json"
)

#: Zone de test : colonnes 28..36, lignes 18..22 (mêmes coordonnées que la fixture hidden).
_ZONE = {
    "id": "zone", "name": "zone", "shape": "polygon", "objective": False,
    "vertices": [[28, 18], [36, 18], [36, 22], [28, 22]],
}
_WALL_INSIDE = [[28, 18]]   # hex de mur DANS la zone (coin), hors de la ligne de vue est-ouest
_WALL_OUTSIDE = [[50, 50]]  # hex de mur HORS de la zone


def _terrain(walls: List[Dict[str, Any]], zone: Dict[str, Any] = _ZONE) -> Dict[str, Any]:
    return {"terrain_id": "t", "terrain": [dict(zone)], "walls": walls}


@pytest.fixture
def board_x5() -> Iterator[None]:
    """Plateau 44x60x5 actif : c'est lui qui porte les 9 fichiers terrain réels."""
    previous = os.environ.get("W40K_BOARD_PATH")
    os.environ["W40K_BOARD_PATH"] = "board/44x60x5"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("W40K_BOARD_PATH", None)
        else:
            os.environ["W40K_BOARD_PATH"] = previous


def _load_areas(terrain_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Passe par le VRAI loader (`_load_terrain_areas_from_ref`) sur un fichier en mémoire."""
    gsm = GameStateManager(config={})
    with patch.object(
        GameStateManager, "_read_terrain_file",
        return_value=(terrain_data, Path("<memoire>/terrain-test.json")),
    ):
        return gsm._load_terrain_areas_from_ref("terrain-test.json", BANK_SCEN, board_ref="44x60x5")


# ── (1) à (5) : dérivation et refus ─────────────────────────────────────────────

def test_zone_avec_mur_light_seul_est_obscurante_mais_pas_dense(board_x5):
    areas = _load_areas(_terrain([{"name": "w", "type": "light", "hexes": _WALL_INSIDE}]))
    assert len(areas) == 1
    assert areas[0]["obscuring"] is True
    assert areas[0]["dense"] is False


def test_zone_avec_mur_dense_est_dense_et_obscurante(board_x5):
    areas = _load_areas(_terrain([{"name": "w", "type": "dense", "hexes": _WALL_INSIDE}]))
    assert areas[0]["dense"] is True
    assert areas[0]["obscuring"] is True


def test_zone_sans_mur_n_est_ni_obscurante_ni_dense(board_x5):
    """Aucun mur, ou un mur dense HORS de la zone : la zone reste exposée (13.03)."""
    assert _load_areas(_terrain([]))[0]["obscuring"] is False
    areas = _load_areas(_terrain([{"name": "w", "type": "dense", "hexes": _WALL_OUTSIDE}]))
    assert areas[0]["obscuring"] is False and areas[0]["dense"] is False


def test_cle_obscuring_saisie_a_la_main_est_refusee(board_x5):
    zone = dict(_ZONE, obscuring=True)
    with pytest.raises(ValueError, match="obscuring.*obsol"):
        _load_areas(_terrain([], zone))


def test_mur_sans_type_est_refuse(board_x5):
    with pytest.raises(ValueError, match="type"):
        _load_areas(_terrain([{"name": "w", "hexes": _WALL_INSIDE}]))
    with pytest.raises(ValueError, match="type"):
        _load_areas(_terrain([{"name": "w", "type": "ruin", "hexes": _WALL_INSIDE}]))
    # Même exigence sur le lecteur des murs (dense_wall_hexes) : un groupe non typé lève aussi.
    gsm = GameStateManager(config={})
    with patch.object(
        GameStateManager, "_read_terrain_file",
        return_value=(_terrain([{"name": "w", "hexes": _WALL_INSIDE}]), Path("<memoire>")),
    ):
        with pytest.raises(ValueError, match="type"):
            gsm._load_terrain_walls_from_ref("terrain-test.json", BANK_SCEN, board_ref="44x60x5")


# ── (6) verrou sur les terrains réels ───────────────────────────────────────────

def _real_terrain_files() -> List[Path]:
    files = sorted(
        p for p in (PROJECT_ROOT / "config" / "board").glob("*/terrain/**/*.json")
        if p.name != "terrain_list.json"
    )
    assert files, "VERT VACANT : aucun fichier terrain trouvé sous config/board/*/terrain"
    return files


@pytest.mark.parametrize("path", _real_terrain_files(), ids=lambda p: str(p.relative_to(PROJECT_ROOT)))
def test_terrain_reel_se_charge_sans_cle_obscuring(path: Path, board_x5):
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    assert "terrain" in raw, f"{path} : pas un fichier terrain"
    offenders = [a.get("id") for a in raw["terrain"] if isinstance(a, dict) and "obscuring" in a]
    assert not offenders, f"{path} : clé 'obscuring' encore saisie à la main sur {offenders}"
    board_dir = path.parents[1] if path.parent.name == "terrain" else path.parents[2]
    assert board_dir.parent.name == "board", f"{path} : arborescence inattendue"
    terrain_ref = str(path.relative_to(board_dir / "terrain"))
    areas = GameStateManager(config={})._load_terrain_areas_from_ref(
        terrain_ref, BANK_SCEN, board_ref=board_dir.name
    )
    for area in areas:
        assert isinstance(area["obscuring"], bool) and isinstance(area["dense"], bool)
        assert not (area["dense"] and not area["obscuring"]), "dense ⇒ obscuring (13.10)"


def test_terrain_mc1_et_mc2_categories_attendues(board_x5):
    """Cas mesurés à l'audit : mc1 a des zones à murs light seuls (couvert, pas hidden) ; mc2 avait
    des zones à murs typés déclarées non obscurantes contre 13.10."""
    gsm = GameStateManager(config={})
    mc1 = {a["id"]: a for a in gsm._load_terrain_areas_from_ref("terrain-mc1.json", BANK_SCEN, board_ref="44x60x5")}
    for zid in ("rect_s_n_OK", "line_s_w_OK", "rect_s_s_OK", "line_s_e_OK"):
        assert mc1[zid]["obscuring"] is True and mc1[zid]["dense"] is False, zid
    assert mc1["ruin_center_OK"]["dense"] is True
    mc2 = {a["id"]: a for a in gsm._load_terrain_areas_from_ref("terrain-mc2.json", BANK_SCEN, board_ref="44x60x5")}
    for zid in ("line_l_nw_OK", "line_l_se"):
        assert mc2[zid]["dense"] is True and mc2[zid]["obscuring"] is True, zid
    for zid in ("line_s_nw", "rect_s_nw_OK", "rect_s_se", "line_s_se"):
        assert mc2[zid]["obscuring"] is True and mc2[zid]["dense"] is False, zid


# ── (7) hidden exige du dense ───────────────────────────────────────────────────

BIN_HIDDEN = unit_bin_index("hidden")
BIN_PRESENT = unit_bin_index("present")
_SQUAD = [(30, 20), (32, 20)]   # entièrement dans la zone 28..36 × 18..22
_ENEMY = [(80, 20)]


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "code": "test_weapon", "display_name": "Test Bolter", "shot": 0,
    }


def _unit_cfg(uid: int, player: int, positions: List[Tuple[int, int]]) -> Dict[str, Any]:
    specs = [{"col": c, "row": r, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10} for c, r in positions]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(specs), "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [_weapon_cfg()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _engine_with_loaded_zone(wall_type: str) -> W40KEngine:
    """Escouade 1 (INFANTRY, n'a pas tiré) entièrement dans la zone ; la zone est produite par le
    VRAI loader à partir d'un mur ``wall_type`` situé dedans."""
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    wall = [[28, 18]]
    cfg = {
        "board": {"default": {
            "cols": 120, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
            "wall_hexes": wall, "inches_to_subhex": 1,
        }},
        "game_rules": build_game_rules(
            engagement_zone=1, engagement_zone_vertical=5, max_base_size_hex=35,
            unit_model_cohesion_range=2, unit_global_cohesion_range=9,
            squad_min_neighbors=1, cohesion_distance_mode="euclidean",
        ),
        "charge": {"charge_max_distance": 12},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "scenario_objectives": [],
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [_unit_cfg(1, 1, _SQUAD), _unit_cfg(2, 2, _ENEMY)],
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(cfg))
    eng.reset()
    gs = eng.game_state
    gs["terrain_areas"] = _load_areas(_terrain([{"name": "w", "type": wall_type, "hexes": wall}]))
    gs["wall_hexes"] = wall
    gs["dense_wall_hexes"] = wall if wall_type == "dense" else []
    for key in ("_dense_wall_set_cache", "_wall_set_cache", "_obscuring_area_sets_cache",
                "_obscuring_hex_to_area_cache", "_unit_los_pair_cache"):
        gs.pop(key, None)
    return eng


def _hidden_flags(eng: W40KEngine) -> Tuple[bool, float]:
    """(statut moteur `unit['hidden']`, drapeau d'observation hidden de l'unité active)."""
    from engine.phase_handlers.shooting_handlers import compute_hidden_statuses
    gs = eng.game_state
    compute_hidden_statuses(gs)
    obs = eng.obs_builder.build_squad_observation(gs, "1")
    return bool(gs["unit_by_id"]["1"]["hidden"]), float(obs["allies_bin"][0][BIN_HIDDEN])


def test_hidden_refuse_dans_une_zone_obscurante_sans_dense(board_x5):
    """13.09 : zone à mur LIGHT seul = obscurante (13.10) mais sans dense → pas hidden."""
    eng = _engine_with_loaded_zone("light")
    zone = eng.game_state["terrain_areas"][0]
    assert zone["obscuring"] is True and zone["dense"] is False, "fixture : zone light attendue"
    hidden, obs_hidden = _hidden_flags(eng)
    assert hidden is False, "hidden accordé dans une zone sans terrain dense (13.09)"
    assert obs_hidden == 0.0


def test_hidden_accorde_dans_une_zone_dense(board_x5):
    eng = _engine_with_loaded_zone("dense")
    assert eng.game_state["terrain_areas"][0]["dense"] is True
    hidden, obs_hidden = _hidden_flags(eng)
    assert hidden is True
    assert obs_hidden == 1.0
