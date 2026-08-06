"""Intégration — engagement 3D de la charge (chantier « Étages » 3a/3b) sur le VRAI scénario.

Construit un vrai jeu (W40KEngine + config/board/44x60x5/scenario/scenario_floors_test.json : ruine
centrale avec floors L1=3"/L2=6", vraies unités roster), place une cible ennemie à l'étage et un
chargeur au sol au même (col,row) horizontal, puis vérifie la chaîne roster → units_cache →
primitive 3D :
  1. MODEL_HEIGHT du roster arrive dans units_cache (vraies unités) et floor_height_by_model est
     peuplé via les vrais floors rasterisés (0.0 au sol, 3.0 à L1, 6.0 à L2).
  2. Le gate d'engagement 3D (spatial_relations, vertical_zone_inches) bascule exactement au gap
     vertical réel.
  3. 3b — le chargeur MONTE : le champ climb produit des destinations d'étage (coût de montée §13.06
     soustrait du jet) et le pool charge_model_plan_state porte le niveau par ancre.

Seul moyen de non-régression du gameplay 3D d'étages (le RL ne l'exerce pas).

Rapatrié de `scripts/charge3d_integration_test.py` (2026-07-26) : ce fichier vivait hors de `tests/`,
donc n'était jamais collecté par la suite.
"""

from __future__ import annotations

import os

import pytest

from engine.phase_handlers.shared_utils import update_model_position
from engine.spatial_relations import unit_entries_within_engagement_zone
from engine.terrain_utils import floor_hexes_at_level

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCENARIO = os.path.join(PROJECT_ROOT, "config/board/44x60x5/scenario/scenario_floors_test.json")


@pytest.fixture(scope="module")
def floors_env():
    from ai.training_utils import setup_imports
    from ai.unit_registry import UnitRegistry
    from services.api_server import get_agents_from_scenario

    W40KEngine, _ = setup_imports()
    ur = UnitRegistry()
    if not os.path.exists(SCENARIO):
        raise FileNotFoundError(SCENARIO)
    env = W40KEngine(
        rewards_config="default",
        training_config_name="x5_new",
        controlled_agent=sorted(get_agents_from_scenario(SCENARIO, ur))[0],
        scenario_file=SCENARIO,
        unit_registry=ur,
        quiet=True,
        gym_training_mode=True,
    )
    env.reset(seed=42)
    return env


@pytest.fixture
def setup(floors_env):
    """Acteurs + hexes centraux de chaque étage (l'ancre doit tenir sur le plancher)."""
    gs = floors_env.game_state
    ubi = gs["unit_by_id"]
    p1 = [(str(k), u) for k, u in ubi.items() if u["player"] == 1]
    p2 = [(str(k), u) for k, u in ubi.items() if u["player"] == 2]
    assert p1 and p2, "scénario sans deux camps"

    ta = gs["terrain_areas"]
    fh1 = sorted(floor_hexes_at_level(ta, 1))
    fh2 = sorted(floor_hexes_at_level(ta, 2))
    assert fh1 and fh2, "scénario sans planchers L1/L2 rasterisés"

    tgt_uid, tgt_u = p2[0]
    chg_uid, chg_u = p1[0]
    return {
        "gs": gs,
        "p1": p1,
        "fh1": fh1,
        "c1": fh1[len(fh1) // 2],
        "c2": fh2[len(fh2) // 2],
        "tgt_uid": tgt_uid,
        "tgt_u": tgt_u,
        "chg_uid": chg_uid,
        "chg_u": chg_u,
        "tgt_mid": gs["squad_models"][tgt_uid][0],
        "chg_mid": gs["squad_models"][chg_uid][0],
    }


def _place(gs, mid, col, row, level):
    update_model_position(gs, str(mid), int(col), int(row), level=int(level))


def test_roster_heights_reach_units_cache(setup):
    """MODEL_HEIGHT du roster + floor_height_by_model (0.0 au sol, 3.0 à L1) arrivent en cache."""
    gs, c1 = setup["gs"], setup["c1"]
    _place(gs, setup["tgt_mid"], c1[0], c1[1], 1)
    _place(gs, setup["chg_mid"], c1[0], c1[1], 0)

    te = gs["units_cache"][setup["tgt_uid"]]
    ce = gs["units_cache"][setup["chg_uid"]]
    assert te["floor_height_by_model"][setup["tgt_mid"]] == 3.0
    assert ce["floor_height_by_model"][setup["chg_mid"]] == 0.0
    assert te.get("MODEL_HEIGHT") is not None, "MODEL_HEIGHT absent (roster non propagé)"
    assert ce.get("MODEL_HEIGHT") is not None, "MODEL_HEIGHT absent (roster non propagé)"


def test_target_on_l1_is_engageable(setup):
    """Cible à L1 (3") au même (col,row) : distance horizontale nulle → engageable en 3D comme en 2D."""
    gs, c1 = setup["gs"], setup["c1"]
    _place(gs, setup["tgt_mid"], c1[0], c1[1], 1)
    _place(gs, setup["chg_mid"], c1[0], c1[1], 0)
    te = gs["units_cache"][setup["tgt_uid"]]
    ce = gs["units_cache"][setup["chg_uid"]]
    ez = int(gs["config"]["game_rules"]["engagement_zone"])

    r_3d = unit_entries_within_engagement_zone(ce, te, ez, metric="euclidean", vertical_zone_inches=5.0)
    r_2d = unit_entries_within_engagement_zone(ce, te, ez, metric="euclidean")
    assert r_3d and r_2d, "cible L1 doit être engageable (gap vertical faible)"


def test_vertical_gate_switches_at_real_gap(setup):
    """Cible à L2 (6") : le gate vertical bascule exactement au gap réel (refuse en dessous)."""
    gs, c2 = setup["gs"], setup["c2"]
    _place(gs, setup["tgt_mid"], c2[0], c2[1], 2)
    _place(gs, setup["chg_mid"], c2[0], c2[1], 0)
    te = gs["units_cache"][setup["tgt_uid"]]
    ce = gs["units_cache"][setup["chg_uid"]]
    ez = int(gs["config"]["game_rules"]["engagement_zone"])
    assert te["floor_height_by_model"][setup["tgt_mid"]] == 6.0

    # gap vertical réel entre [0, chg_mh] et [6, 6+tgt_mh] = max(0, 6 - chg_mh)
    gap = max(0.0, 6.0 - float(ce["MODEL_HEIGHT"]))
    r_below = unit_entries_within_engagement_zone(
        ce, te, ez, metric="euclidean", vertical_zone_inches=gap - 0.5
    )
    r_above = unit_entries_within_engagement_zone(
        ce, te, ez, metric="euclidean", vertical_zone_inches=gap + 0.5
    )
    assert not r_below, f"vz={gap - 0.5} (sous le gap réel {gap}) doit refuser l'engagement"
    assert r_above, f"vz={gap + 0.5} (sur le gap réel {gap}) doit autoriser l'engagement"


def _climb_setup(setup):
    """Chargeur montant au pied de la ruine + cible sur L1. `None` si le roster n'a aucun montant."""
    from engine.game_state import unit_can_occupy_upper_floor
    from engine.hex_utils import get_neighbors

    gs = setup["gs"]
    climber = next(
        ((uid, u) for uid, u in setup["p1"] if unit_can_occupy_upper_floor(u["UNIT_KEYWORDS"])), None
    )
    if climber is None:
        return None
    clb_uid, clb_u = climber
    clb_mid = gs["squad_models"][clb_uid][0]

    c1, fh1 = setup["c1"], setup["fh1"]
    _place(gs, setup["tgt_mid"], c1[0], c1[1], 1)
    walls = set(gs.get("wall_hexes", set()))
    fh1_set = set(fh1)
    # Départ au SOL sur un hex adjacent au pied de la ruine (hors plancher, hors mur).
    ground_start = next(
        (nb for cell in fh1 for nb in get_neighbors(cell[0], cell[1])
         if nb not in fh1_set and nb not in walls
         and 0 <= nb[0] < gs["board_cols"] and 0 <= nb[1] < gs["board_rows"]),
        None,
    )
    assert ground_start is not None, "pas d'hex de sol adjacent au plancher L1"
    _place(gs, clb_mid, ground_start[0], ground_start[1], 0)
    return clb_uid, clb_u, clb_mid, ground_start


def test_climb_reachable_floor_cells_respect_climb_cost(setup):
    """3b : le chargeur montant atteint L1 avec un gros jet, et rien sous le coût de montée §13.06."""
    from engine.phase_handlers.charge_handlers import _charge_model_climb_reachable_floor_cells
    from engine.terrain_utils import low_clearance_ground_hexes

    climb = _climb_setup(setup)
    if climb is None:
        pytest.skip("aucune unité p1 montante dans ce roster")
    clb_uid, clb_u, clb_mid, ground_start = climb

    gs = setup["gs"]
    clb_model = gs["models_cache"][clb_mid]
    ish = int(gs["inches_to_subhex"])
    ta = gs["terrain_areas"]
    # (les ennemis ne bloquent pas ici : on teste la montée pure)
    ground_obs = set(gs.get("wall_hexes", set())) | low_clearance_ground_hexes(
        ta, float(clb_u["MODEL_HEIGHT"])
    )

    budget = 12 * ish  # gros jet de charge (2D6 max) en sous-hex
    fcells = _charge_model_climb_reachable_floor_cells(
        gs, clb_u, clb_uid, clb_model, (ground_start[0], ground_start[1]), budget, 1, ground_obs, ta,
    )
    assert fcells, "le chargeur montant doit atteindre au moins une case de l'étage L1"
    assert all(isinstance(d, int) and d >= 0 for d in fcells.values()), "distances climb invalides"

    # Budget serré : monter coûte au moins la hauteur de l'étage (3") → budget < 3" ⇒ aucune case L1.
    tiny = max(0, (2 * ish) - 1)  # ~2" < 3" de montée
    fcells_tiny = _charge_model_climb_reachable_floor_cells(
        gs, clb_u, clb_uid, clb_model, (ground_start[0], ground_start[1]), tiny, 1, ground_obs, ta,
    )
    assert not fcells_tiny, "sous le coût de montée §13.06, aucune case d'étage ne doit être atteignable"


def test_charge_pool_carries_floor_anchors(setup):
    """3b : charge_model_plan_state en vue L1 renvoie des ancres [col,row,level>=1]."""
    from engine.phase_handlers.charge_handlers import charge_model_plan_state

    climb = _climb_setup(setup)
    if climb is None:
        pytest.skip("aucune unité p1 montante dans ce roster")
    clb_uid, _clb_u, clb_mid, _ground_start = climb

    gs = setup["gs"]
    # Le chemin 3D d'étage est euclidean-only (métrique GAMEPLAY) ; l'env de test est en gym
    # (metric hex, 2D par design RL) → on bascule en mode PvP pour ce sous-test, puis on restaure
    # (l'env est partagé par le module).
    was_gym = gs["gym_training_mode"]
    gs["gym_training_mode"] = False
    gs.setdefault("charge_target_selections", {})[clb_uid] = [setup["tgt_uid"]]
    gs.setdefault("charge_roll_values", {})[clb_uid] = 12

    try:
        state = charge_model_plan_state(gs, clb_uid, {}, selected_model=clb_mid, level=1)
    finally:
        gs["gym_training_mode"] = was_gym
    floor_anchors = [a for a in state["pool"] if len(a) >= 3 and int(a[2]) >= 1]
    assert floor_anchors, "charge_model_plan_state (vue L1) doit produire des ancres d'étage level>=1"
    assert all(len(a) == 3 for a in state["pool"]), "chaque ancre du pool doit porter [col,row,level]"


def test_a_floor_destination_is_validated_by_the_climb_field_not_the_2d_bfs(setup):
    """3b — `_charge_model_pos_is_closer` en `dest_level>=1` passe par le champ climb (§13.06).

    Sans cette branche, la légalité d'une destination d'étage serait décidée par le BFS 2D, qui
    ignore le coût de montée : une ancre d'étage deviendrait légale avec un jet qui ne permet pas
    de monter. Le budget est la SEULE variable entre les deux appels ci-dessous.

    Ce chemin n'était couvert par aucun test (mesuré) alors qu'il décide de toute charge d'étage.
    """
    from engine.phase_handlers.charge_handlers import (
        _charge_model_climb_reachable_floor_cells,
        _charge_model_pos_is_closer,
    )
    from engine.terrain_utils import low_clearance_ground_hexes

    climb = _climb_setup(setup)
    if climb is None:
        pytest.skip("aucune unité p1 montante dans ce roster")
    clb_uid, clb_u, clb_mid, ground_start = climb

    gs = setup["gs"]
    ish = int(gs["inches_to_subhex"])
    ta = gs["terrain_areas"]
    ground_obs = set(gs.get("wall_hexes", set())) | low_clearance_ground_hexes(
        ta, float(clb_u["MODEL_HEIGHT"])
    )
    big = 12 * ish
    reachable = _charge_model_climb_reachable_floor_cells(
        gs, clb_u, clb_uid, gs["models_cache"][clb_mid],
        (ground_start[0], ground_start[1]), big, 1, ground_obs, ta,
    )
    assert reachable, "prémisse : le champ climb doit rendre au moins une case d'étage"

    # Le chemin 3D d'étage est euclidean-only (métrique gameplay) ; l'env de test est en gym (hex).
    was_gym = gs["gym_training_mode"]
    gs["gym_training_mode"] = False
    try:
        # PREMIÈRE case acceptée, pas toutes : ce test oppose DEUX budgets sur UNE case (le budget
        # est « la SEULE variable », cf. docstring), et n'assertait déjà que « au moins une ».
        # Balayer les 629 cases du champ climb coûtait 124 s pour une information que la première
        # porte entièrement — c'était le test le plus lourd de toute la suite unitaire (160 s).
        # `sorted` reste indispensable : il rend le choix déterministe, donc la case reprise plus
        # bas est toujours la même d'un run à l'autre.
        accepted = next(
            (cell for cell in sorted(reachable)
             if _charge_model_pos_is_closer(
                 gs, clb_u, clb_mid, cell[0], cell[1], [setup["tgt_uid"]], big, {}, dest_level=1,
             )),
            None,
        )
        assert accepted is not None, (
            "aucune case d'étage atteignable n'est jugée légale : la branche climb ne valide rien"
        )
        # Budget sous le coût de montée (§13.06, étage L1 = 3") : la MÊME case devient illégale.
        tiny = max(0, (2 * ish) - 1)
        assert not _charge_model_climb_reachable_floor_cells(
            gs, clb_u, clb_uid, gs["models_cache"][clb_mid],
            (ground_start[0], ground_start[1]), tiny, 1, ground_obs, ta,
        ), "prémisse : sous 3\" de montée, le champ climb doit être vide"
        assert _charge_model_pos_is_closer(
            gs, clb_u, clb_mid, accepted[0], accepted[1],
            [setup["tgt_uid"]], tiny, {}, dest_level=1,
        ) is False, (
            "une destination d'étage reste légale sous le coût de montée : le BFS 2D a décidé "
            "à la place du champ climb (§13.06)"
        )
    finally:
        gs["gym_training_mode"] = was_gym
