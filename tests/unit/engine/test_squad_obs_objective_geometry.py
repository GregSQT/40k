"""Verrou : l'observation porte OU sont les objectifs, pas seulement qui les controle.

Trou ferme ici. L'action space offre 3 intents de zone par objectif (15 actions,
`macro_intents.MAX_OBJECTIVES * 3`), et l'observation ne portait AUCUNE position d'objectif :
`global_bin` n'avait que le controle et la presence. La seule source spatiale etait le canal 4
de la grille egocentrique, dont la demi-etendue vaut le budget d'Advance (12" mesure sur le
board x5) et qui ecarte sans clamp tout hex hors fenetre. Mesure au reset du scenario de
training : 1 a 2 objectifs sur 5 seulement tombaient dans la fenetre. L'agent disposait donc
d'actions pour designer des objectifs qu'il ne percevait pas, et d'aucun moyen d'apprendre a
naviguer vers un objectif lointain.

Ce que ces tests verrouillent :
  - la distance est celle de l'hex le PLUS PROCHE de la zone (une zone se rejoint par son bord),
    en subhex bruts, conforme a un ORACLE scalaire independant ;
  - la direction est un vecteur UNITAIRE vers ce meme hex ;
  - le cas degenere (escouade sur l'objectif) ne fabrique pas de direction ;
  - un slot sans objectif reste a zero, lu via `objective_present_i` ;
  - et surtout : un objectif HORS de la fenetre de grille est bien decrit par le vecteur —
    c'est tout l'objet de la tranche.
"""

from __future__ import annotations

import math
import os

import numpy as np
import pytest

from tests.unit.engine._config_helpers import bank_training_scenarios
from ai.unit_registry import UnitRegistry
from engine.hex_utils import _hex_center
from engine.observation_builder import ObservationBuilder
from engine.observation_entities import global_bin_index, global_cont_index
from engine.spatial_grid import (
    GRID_CH_OBJECTIVE,
    grid_half_extent_subhex,
    hex_arrays_to_cells,
)
from engine.w40k_core import W40KEngine

#: TOUS les terrains de la banque. Ce fichier mesure la distance et la DIRECTION de l'escouade
#: vers chaque objectif : les objectifs sont des zones du TERRAIN, donc changer de terrain change
#: la géométrie mesurée — ce n'est pas une répétition.
TEMPLATES = bank_training_scenarios()
#: Terrain courant, réécrit par la fixture `terrain`. Passé par un attribut de module plutôt qu'en
#: paramètre : aucun test du fichier n'est spécifique à un terrain, et `_make_env()` est appelée
#: sans argument par tous.
TEMPLATE = TEMPLATES[0]
HEX_STEP = math.sqrt(3.0)


@pytest.fixture(autouse=True, params=TEMPLATES, ids=os.path.basename)
def terrain(request, monkeypatch):
    """Rejoue CHAQUE test du fichier sur tous les terrains de la banque.

    `monkeypatch` et non un `global` + `try/finally` maison : la restauration devient l'affaire
    de pytest, y compris si le test lève.
    """
    monkeypatch.setattr(f"{__name__}.TEMPLATE", request.param)
    return request.param


def _make_env() -> W40KEngine:
    return W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x1",
        controlled_agent="ArmageddonAgent",
        scenario_file=TEMPLATE,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,  # UN environnement joue en serie (engine/episode_schedule.py)
    )


def _reset_deployed(env, **kwargs):
    """`reset` PUIS sortie de la phase de déploiement : ce fichier observe des unités POSÉES.

    Nécessaire depuis que la rampe oppose 'active' à 'auto' (2026-08-08) et non plus à 'fixed'.
    'fixed' rejouait les positions écrites dans le roster, donc les figurines étaient sur la
    table dès le reset ; 'auto' joue une vraie phase de déploiement, et une figurine encore hors
    table est à la sentinelle (-1,-1). Les distances aux objectifs y sont constantes — le test
    « la distance diminue quand l'escouade s'approche » comparait deux fois la même valeur.

    Le mode n'est pas non plus laissé au tirage : certains profils démarrent à
    `active_ratio_start` > 0, donc l'ancien code observait des états différents d'une exécution
    à l'autre.
    """
    import numpy as _np

    out = env.reset(**kwargs)
    gs = env.game_state
    steps = 0
    while steps < 400 and str(gs["phase"]) == "deployment":
        legal = _np.flatnonzero(env.get_action_mask())
        assert legal.size > 0, "plus aucune action légale en phase de déploiement"
        env.step(int(legal[0]))
        steps += 1
    assert str(gs["phase"]) != "deployment", f"toujours en déploiement après {steps} steps"
    return out


def _oracle(objective, cx: int, cy: int):
    """(distance en subhex, cos, sin) par balayage SCALAIRE — reimplementation independante.

    Volontairement naif : boucle Python sur `_hex_center`, la fonction de projection du moteur,
    sans aucun des tableaux vectorises de l'implementation. C'est ce qui en fait un oracle.

    Ex-aequo departages sur le plus petit (col, row), comme le code de production : une zone
    rectangulaire offre presque toujours deux hexes equidistants, de directions opposees en
    `sin`. Sans regle explicite, oracle et implementation divergeraient sur un simple alea
    d'ordre de fichier — c'est exactement ce que ce test a fait apparaitre.
    """
    ax, ay = _hex_center(cx, cy)
    candidates = []
    for hex_entry in objective["hexes"]:
        col, row = (
            (int(hex_entry[0]), int(hex_entry[1]))
            if isinstance(hex_entry, (list, tuple))
            else (int(hex_entry["col"]), int(hex_entry["row"]))
        )
        hx, hy = _hex_center(col, row)
        candidates.append((math.hypot(hx - ax, hy - ay), col, row, hx - ax, hy - ay))
    best_d = min(c[0] for c in candidates)
    tied = [c for c in candidates if c[0] <= best_d * (1.0 + 1e-9) + 1e-12]
    dist_px, _, _, dx, dy = min(tied, key=lambda c: (c[1], c[2]))
    if dist_px <= 0.0:
        return 0.0, 0.0, 0.0
    return dist_px / HEX_STEP, dx / dist_px, dy / dist_px


def _active_squad(gs) -> str:
    cp = int(gs.get("current_player", 1))
    return next(s for s, e in gs["units_cache"].items() if int(e["player"]) == cp)


def test_matches_an_independent_scalar_oracle():
    """Distance et direction egalent l'oracle scalaire, sur toutes les escouades et objectifs."""
    env = _make_env()
    _reset_deployed(env)
    gs = env.game_state
    objectives = gs["objectives"]

    checked = 0
    for sid in list(gs["units_cache"].keys()):
        # L'oracle mesure depuis le CENTROÏDE de l'escouade. Une escouade HORS TABLE (réserves
        # 20.01, ou en attente de déploiement) n'a pas de centroïde : le sien est la sentinelle
        # (-1,-1), alors que l'obs mesure depuis l'ancre de sa ZONE (§0.40 point 2). Comparer les
        # deux ne mesurerait pas un écart de calcul mais deux origines différentes, l'une des
        # deux étant hors plateau. Le cas « pas de position » a son propre verrou
        # (test_deployment_observation_contract).
        if int(gs["units_cache"][sid]["col"]) < 0:
            continue
        obs = env.obs_builder.build_squad_observation(gs, sid)
        sq = gs["squad_cache"][sid]
        entry = gs["units_cache"][sid]
        cx = int(round(float(sq.get("centroid_col", entry["col"]))))
        cy = int(round(float(sq.get("centroid_row", entry["row"]))))
        for i, objective in enumerate(objectives[: ObservationBuilder.SQUAD_N_OBJECTIVE_SLOTS]):
            exp_d, exp_c, exp_s = _oracle(objective, cx, cy)
            got_d = float(obs["global_cont"][global_cont_index(f"objective_distance_{i}")])
            got_c = float(obs["global_bin"][global_bin_index(f"objective_dir_cos_{i}")])
            got_s = float(obs["global_bin"][global_bin_index(f"objective_dir_sin_{i}")])
            assert got_d == float(np.float32(exp_d)), f"{sid}/obj{i}: distance {got_d} != {exp_d}"
            assert abs(got_c - exp_c) < 1e-5, f"{sid}/obj{i}: cos {got_c} != {exp_c}"
            assert abs(got_s - exp_s) < 1e-5, f"{sid}/obj{i}: sin {got_s} != {exp_s}"
            checked += 1

    assert checked > 0, "aucune escouade posée confrontée à l'oracle — test sans valeur"


def test_direction_is_a_unit_vector_or_exactly_zero():
    """Norme 1 quand l'objectif est ailleurs, 0 quand on est dessus (aucune direction inventee)."""
    env = _make_env()
    obs, _ = _reset_deployed(env)
    gb = obs["global_bin"]
    gc = obs["global_cont"]

    seen_far = False
    for i in range(ObservationBuilder.SQUAD_N_OBJECTIVE_SLOTS):
        if not gb[global_bin_index(f"objective_present_{i}")]:
            continue
        c = float(gb[global_bin_index(f"objective_dir_cos_{i}")])
        s = float(gb[global_bin_index(f"objective_dir_sin_{i}")])
        d = float(gc[global_cont_index(f"objective_distance_{i}")])
        norm = math.hypot(c, s)
        if d == 0.0:
            assert norm == 0.0, "direction fabriquee alors que la distance est nulle"
        else:
            seen_far = True
            assert abs(norm - 1.0) < 1e-5, f"obj{i}: direction non unitaire ({norm})"
    assert seen_far, "aucun objectif distant dans ce scenario — le test n'a rien verifie"


def test_absent_slot_is_zero_and_flagged_absent():
    """Un slot sans objectif reste a zero et se lit via `objective_present_i`."""
    env = _make_env()
    _reset_deployed(env)
    gs = env.game_state
    sid = _active_squad(gs)

    # Scenario a 5 objectifs : on en retire un pour creer un slot vide.
    gs["objectives"] = gs["objectives"][:-1]
    gs.pop(ObservationBuilder.OBJECTIVE_HEX_ARRAYS_KEY, None)
    obs = env.obs_builder.build_squad_observation(gs, sid)

    last = ObservationBuilder.SQUAD_N_OBJECTIVE_SLOTS - 1
    assert obs["global_bin"][global_bin_index(f"objective_present_{last}")] == 0.0
    assert obs["global_cont"][global_cont_index(f"objective_distance_{last}")] == 0.0
    assert obs["global_bin"][global_bin_index(f"objective_dir_cos_{last}")] == 0.0
    assert obs["global_bin"][global_bin_index(f"objective_dir_sin_{last}")] == 0.0


def test_objective_outside_the_grid_window_is_still_described():
    """LE point de la tranche : un objectif hors fenetre est absent de la grille, present au vecteur.

    Sans ce couple distance/direction, un tel objectif n'existe NULLE PART dans l'observation,
    alors que 3 actions de zone le designent.
    """
    env = _make_env()
    _reset_deployed(env)
    gs = env.game_state
    sid = _active_squad(gs)
    obs = env.obs_builder.build_squad_observation(gs, sid)
    obs["grid"] = env.obs_builder.build_squad_grid(gs, sid)

    entry = gs["units_cache"][sid]
    sq = gs["squad_cache"][sid]
    cx = int(round(float(sq.get("centroid_col", entry["col"]))))
    cy = int(round(float(sq.get("centroid_row", entry["row"]))))
    half = grid_half_extent_subhex(gs, sid)

    outside = []
    for i, objective in enumerate(gs["objectives"][: ObservationBuilder.SQUAD_N_OBJECTIVE_SLOTS]):
        arr = np.array(
            [
                (h[0], h[1]) if isinstance(h, (list, tuple)) else (h["col"], h["row"])
                for h in objective["hexes"]
            ],
            dtype=float,
        )
        _, _, valid = hex_arrays_to_cells(arr[:, 0], arr[:, 1], cx, cy, half)
        if not valid.any():
            outside.append(i)

    assert outside, (
        "aucun objectif hors fenetre dans ce scenario : le test ne prouverait rien "
        f"(demi-etendue = {half} subhex)"
    )
    for i in outside:
        d = float(obs["global_cont"][global_cont_index(f"objective_distance_{i}")])
        c = float(obs["global_bin"][global_bin_index(f"objective_dir_cos_{i}")])
        s = float(obs["global_bin"][global_bin_index(f"objective_dir_sin_{i}")])
        assert d > half, f"obj{i} declare hors fenetre mais a distance {d} <= {half}"
        assert abs(math.hypot(c, s) - 1.0) < 1e-5, f"obj{i} hors fenetre sans direction"

    # Contre-epreuve : la grille, elle, ne peut rien en dire — c'est bien le vecteur qui porte.
    assert obs["grid"][GRID_CH_OBJECTIVE].sum() >= 0.0


def test_distance_decreases_when_the_squad_moves_closer():
    """La distance suit le deplacement reel de l'escouade (feature vivante, pas figee au reset)."""
    env = _make_env()
    _reset_deployed(env)
    gs = env.game_state
    sid = _active_squad(gs)

    before = float(
        env.obs_builder.build_squad_observation(gs, sid)["global_cont"][
            global_cont_index("objective_distance_1")
        ]
    )
    target = gs["objectives"][1]["hexes"][0]
    tcol, trow = (
        (int(target[0]), int(target[1]))
        if isinstance(target, (list, tuple))
        else (int(target["col"]), int(target["row"]))
    )
    # Rapprochement du centroide observe (l'obs lit `squad_cache`).
    sq = gs["squad_cache"][sid]
    sq["centroid_col"] = tcol
    sq["centroid_row"] = trow
    after = float(
        env.obs_builder.build_squad_observation(gs, sid)["global_cont"][
            global_cont_index("objective_distance_1")
        ]
    )

    assert after < before, f"distance non mise a jour ({before} -> {after})"
    assert after == 0.0, "sur un hex de la zone, la distance doit etre nulle"


def test_objective_hex_cache_does_not_survive_a_scenario_reload():
    """Le cache d'hexes d'objectif est purge par episode : sinon on decrit l'ancien terrain."""
    env = _make_env()
    _reset_deployed(env)
    gs = env.game_state
    sid = _active_squad(gs)
    env.obs_builder.build_squad_observation(gs, sid)
    assert gs.get(ObservationBuilder.OBJECTIVE_HEX_ARRAYS_KEY) is not None

    poison = [(np.array([0.0]), np.array([0.0]))] * len(gs["objectives"])
    gs[ObservationBuilder.OBJECTIVE_HEX_ARRAYS_KEY] = poison
    _reset_deployed(env)
    assert gs.get(ObservationBuilder.OBJECTIVE_HEX_ARRAYS_KEY) is not poison, (
        "cache d'objectifs survivant au reset"
    )
