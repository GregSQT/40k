"""Canal `GRID_CH_LOS_EXPOSURE` — part des escouades ennemies qui VOIENT chaque cellule jouable.

POURQUOI CE CANAL EXISTE. La branche spatiale est une pile de conv 3x3 stride 1
(`ai/spatial_extractor.py`) : elle agrège un voisinage, elle ne trace pas de rayon. La règle 13.10
est une propriété de PAIRE sur un segment de longueur arbitraire — aucune profondeur de conv ne la
reconstitue depuis les canaux « mur » et « obscurant ». L'information doit donc être écrite DANS la
cellule, comme le coût géodésique.

CE QUE CES TESTS VERROUILLENT, dans l'ordre :
1. l'exclusion 13.10 côté CIBLE — une cellule DANS une zone obscurante reste vue ;
2. l'égalité cellule par cellule avec `compute_unit_los`, la règle du moteur ;
3. le fait que déplacer un ennemi recalcule le canal — c'est le garde-fou du REJET du cache
   (mesuré : 26 % de ratés, gain nul), pas une clause décorative ;
4. le dénominateur : la valeur est une FRACTION des ennemis, pas un compte ;
5. le canal nul hors phase de mouvement, même doctrine que le coût géodésique.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import numpy as np
import pytest

from engine.spatial_grid import (
    GRID_CH_LOS_EXPOSURE,
    GRID_SIZE,
    cell_index,
    grid_half_extent_subhex,
)
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config
from tests.unit.engine.test_squad_grid_observation import (
    ANCHOR_COL,
    ANCHOR_ROW,
    _config,
)

#: Ennemi de la fixture `_config` : plein EST de l'ancre, hors de la grille (col 40 > ~34).
ENEMY_HEX = (40, 20)

#: Zone obscurante posée ENTRE l'ennemi et la moitié ouest de la grille, sur la rangée de tir.
#: Elle est DANS la grille : c'est indispensable pour que des cellules jouables tombent DEDANS,
#: donc pour observer l'exclusion 13.10 côté cible.
OBSCURING_COLS = range(28, 31)
OBSCURING_ROWS = range(18, 23)
OBSCURING_HEXES = [[c, r] for c in OBSCURING_COLS for r in OBSCURING_ROWS]


def _terrain_area() -> Dict[str, Any]:
    return {
        "id": "ecran",
        "name": "ecran",
        "obscuring": True,
        "polygon_vertices": [[28, 18], [30, 18], [30, 22], [28, 22]],
        "hexes": OBSCURING_HEXES,
    }


def _purge_terrain_caches(gs: Dict[str, Any]) -> None:
    """Le terrain est posé APRÈS `reset`, donc tous ses dérivés mémoïsés sont périmés.

    Les oublier laisserait le test vert en observant un plateau SANS zone obscurante — le vert
    vacant exact que cette fixture doit éviter.
    """
    for key in (
        "_grid_static_hex_arrays",
        "_obscuring_area_sets_cache",
        "_obscuring_hex_to_area_cache",
        "_los_blocking_grids_cache",
        "_unit_los_pair_cache",
        "_obs_solid_terrain_areas",
    ):
        gs.pop(key, None)


def _engine(extra_units: List[Dict[str, Any]] | None = None) -> W40KEngine:
    cfg = _config([], [{"id": "obj1", "name": "Alpha", "hexes": [[22, 22]]}])
    if extra_units:
        cfg["units"].extend(extra_units)
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(cfg))
    eng.reset()
    eng.game_state["terrain_areas"] = [_terrain_area()]
    _purge_terrain_caches(eng.game_state)
    return eng


def _canal_et_carte(eng: W40KEngine) -> Tuple[np.ndarray, Dict[int, Tuple[Tuple[int, int], float]]]:
    from engine.phase_handlers.shared_utils import read_squad_move_cell_map

    grid = eng.obs_builder.build_squad_grid(eng.game_state, "1")
    return grid, read_squad_move_cell_map(eng.game_state, "1")


def _valeur(grid: np.ndarray, idx: int) -> float:
    return float(grid[GRID_CH_LOS_EXPOSURE, idx // GRID_SIZE, idx % GRID_SIZE])


def test_une_cellule_dans_la_zone_obscurante_reste_vue():
    """13.10 : l'exclusion porte sur les zones « that one or both of those models are within ».

    C'est LE point de la règle qu'un canal « zone obscurante » ne peut pas dire tout seul : se
    tenir DANS l'écran ne cache pas de l'ennemi qui est dehors — seul un écran INTERMÉDIAIRE cache.
    Une cellule dans la zone doit donc être exposée, celle qui est derrière ne doit pas l'être.
    """
    eng = _engine()
    grid, cell_map = _canal_et_carte(eng)
    ecran = {(int(c), int(r)) for c, r in OBSCURING_HEXES}

    dedans = [idx for idx, (dest, _c) in cell_map.items() if (int(dest[0]), int(dest[1])) in ecran]
    derriere = [
        idx
        for idx, (dest, _c) in cell_map.items()
        if int(dest[0]) < min(OBSCURING_COLS)
        and int(dest[1]) in OBSCURING_ROWS
        and (int(dest[0]), int(dest[1])) not in ecran
    ]
    assert dedans, "fixture creuse : aucune cellule jouable ne tombe DANS la zone obscurante"
    assert derriere, "fixture creuse : aucune cellule jouable derrière la zone obscurante"

    for idx in dedans:
        assert _valeur(grid, idx) == 1.0, (
            f"cellule {idx} (destination {cell_map[idx][0]}) est DANS l'écran : 13.10 exclut "
            f"la zone de la cible, elle doit rester vue"
        )
    caches = [idx for idx in derriere if _valeur(grid, idx) == 0.0]
    assert caches, (
        "aucune cellule derrière l'écran n'est cachée : le canal ne lit pas les zones obscurantes"
    )


def test_le_canal_egale_compute_unit_los_cellule_par_cellule():
    """ORACLE : la RÈGLE du moteur, une cellule à la fois, sur TOUTE la carte de cellules.

    `compute_unit_los` sur des dicts coordonnées-seules est exactement ce que le reste du moteur
    appelle. Si le canal et lui divergent d'une seule cellule, l'agent apprend une visibilité que
    la résolution n'applique pas.
    """
    from engine.phase_handlers.shooting_handlers import compute_unit_los

    eng = _engine()
    grid, cell_map = _canal_et_carte(eng)
    gs = eng.game_state
    assert cell_map, "fixture : carte de cellules vide, l'oracle ne comparerait rien"

    source = {"col": ENEMY_HEX[0], "row": ENEMY_HEX[1]}
    vus = 0
    for idx, (dest, _cost) in cell_map.items():
        attendu = float(
            bool(compute_unit_los(gs, source, {"col": int(dest[0]), "row": int(dest[1])})["can_see"])
        )
        assert _valeur(grid, idx) == attendu, (
            f"cellule {idx} (destination {dest}) : canal={_valeur(grid, idx)} vs règle={attendu}"
        )
        vus += int(attendu)
    # CONTRE LE VERT VACANT : un canal nul et une règle qui ne voit jamais rien seraient d'accord.
    assert 0 < vus < len(cell_map), (
        f"{vus} cellules vues sur {len(cell_map)} : la comparaison ne discrimine rien"
    )


def test_deplacer_un_ennemi_recalcule_le_canal():
    """GARDE-FOU DU CACHE REJETÉ. Le canal est recalculé à chaque construction de grille.

    Un cache de visibilité par hexe source a été mesuré puis écarté (26 % de ratés, gain nul).
    Si quelqu'un le réintroduit sans invalidation, ce test vire au rouge : l'écran est franchi en
    déplaçant l'ennemi au NORD, d'où il voit ce qu'il ne voyait pas.
    """
    eng = _engine()
    grid_avant, cell_map = _canal_et_carte(eng)
    avant = np.array([_valeur(grid_avant, idx) for idx in sorted(cell_map)])

    # Mutation EN PLACE de l'entrée-cache, puis `_touch_unit_los` : c'est le couple exact que
    # pratique le moteur (`translate_squad_to_destination` écrit puis appelle le choke-point).
    from engine.phase_handlers.shared_utils import _touch_unit_los

    gs = eng.game_state
    cible = (20, 40)
    for unit in gs["units"]:
        if str(unit["id"]) == "2":
            unit["col"], unit["row"] = cible
    entry = gs["units_cache"]["2"]
    entry["col"], entry["row"] = cible
    entry["occupied_hexes"] = {cible}
    entry["occupied_hexes_by_model"] = {mid: cible for mid in entry["occupied_hexes_by_model"]}
    for mid in gs["squad_models"]["2"]:
        model = gs["models_cache"][mid]
        model["col"], model["row"] = cible
    _touch_unit_los(gs, "2")

    grid_apres, cell_map_apres = _canal_et_carte(eng)
    assert set(cell_map_apres) == set(cell_map), (
        "fixture : la carte de cellules a bougé, les deux vecteurs ne sont plus comparables"
    )
    apres = np.array([_valeur(grid_apres, idx) for idx in sorted(cell_map_apres)])
    assert not np.array_equal(avant, apres), (
        "l'ennemi a franchi l'écran et le canal n'a pas bougé : une valeur périmée est servie"
    )


def test_la_valeur_est_une_fraction_des_ennemis_pas_un_compte():
    """Dénominateur = escouades ennemies VIVANTES ET POSÉES. Deux ennemis → des demis existent.

    Sans division, le canal sortirait de [0,1] et l'échelle dépendrait de la taille de l'armée
    adverse — un même danger vaudrait 1 contre une armée d'une escouade et 4 contre quatre.
    """
    from tests.unit.engine.test_squad_grid_observation import _unit_cfg

    # Second ennemi placé au NORD : il voit ce que l'écran cache au premier, et réciproquement.
    eng = _engine(extra_units=[_unit_cfg(3, 2, 20, 40)])
    grid, cell_map = _canal_et_carte(eng)
    valeurs = {_valeur(grid, idx) for idx in cell_map}

    assert valeurs <= {0.0, 0.5, 1.0}, f"valeurs hors du pas 1/2 attendu avec 2 ennemis : {valeurs}"
    assert 0.5 in valeurs, (
        "aucune cellule vue d'un seul des deux ennemis : le dénominateur n'est pas observé "
        f"(valeurs={valeurs})"
    )


def test_le_canal_est_nul_hors_phase_de_mouvement():
    """Même doctrine que le coût géodésique : hors mouvement, une cellule ne désigne rien.

    Peindre l'exposition d'un pool périmé ferait croire à l'agent qu'il peut encore s'y rendre.
    """
    eng = _engine()
    gs = eng.game_state
    assert float(eng.obs_builder.build_squad_grid(gs, "1")[GRID_CH_LOS_EXPOSURE].sum()) > 0.0, (
        "fixture : le canal est déjà nul en phase de mouvement, le test ne prouverait rien"
    )
    gs["phase"] = "shoot"
    grid = eng.obs_builder.build_squad_grid(gs, "1")
    assert float(grid[GRID_CH_LOS_EXPOSURE].sum()) == 0.0
