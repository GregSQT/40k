#!/usr/bin/env python3
"""Validation d'intégration — engagement 3D de la charge (chantier "Étages" 3a) sur le VRAI scénario.

Construit un vrai jeu (W40KEngine + config/board/44x60x5/scenario/scenario_floors_test.json : ruine
centrale avec floors L1=3"/L2=6", vraies unités roster), place une cible ennemie à l'étage et un chargeur
au sol au même (col,row) horizontal, puis vérifie la chaîne roster -> units_cache -> primitive 3D :
  1. MODEL_HEIGHT du roster arrive dans units_cache (vraies unités).
  2. floor_height_by_model peuplé via les vrais floors rasterisés (0.0 au sol, 3.0 à L1, 6.0 à L2).
  3. Le gate d'engagement 3D (spatial_relations.entries_in_engagement_zone, vertical_zone_inches) mord
     au seuil vertical réel avec ces données.

Seul moyen de non-régression du gameplay 3D d'étages (le RL est HS -> pas de test pytest gameplay).
Lancement : source .venv/bin/activate && python3 scripts/charge3d_integration_test.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ai.training_utils import setup_imports
from ai.unit_registry import UnitRegistry
from services.api_server import get_agents_from_scenario
from engine.phase_handlers.shared_utils import update_model_position
from engine.terrain_utils import floor_hexes_at_level
from engine.spatial_relations import unit_entries_within_engagement_zone

SCENARIO = os.path.join(REPO, "config/board/44x60x5/scenario/scenario_floors_test.json")


def build_env():
    W40KEngine, _ = setup_imports()
    ur = UnitRegistry()
    if not os.path.exists(SCENARIO):
        raise FileNotFoundError(SCENARIO)
    env = W40KEngine(
        rewards_config="default", training_config_name="x5_new",
        controlled_agent=sorted(get_agents_from_scenario(SCENARIO, ur))[0],
        scenario_file=SCENARIO, unit_registry=ur, quiet=True, gym_training_mode=True,
    )
    env.reset(seed=42)
    return env


def main() -> int:
    env = build_env()
    gs = env.game_state
    ubi = gs["unit_by_id"]
    p1 = [(str(k), u) for k, u in ubi.items() if u["player"] == 1]
    p2 = [(str(k), u) for k, u in ubi.items() if u["player"] == 2]
    if not p1 or not p2:
        raise RuntimeError("Scénario sans deux camps")

    ta = gs["terrain_areas"]
    fh1 = sorted(floor_hexes_at_level(ta, 1))
    fh2 = sorted(floor_hexes_at_level(ta, 2))
    print(f"floor L1 hexes={len(fh1)} L2 hexes={len(fh2)}")
    # hex central de chaque étage (pour que l'ancre tienne sur le plancher)
    c1 = fh1[len(fh1) // 2]
    c2 = fh2[len(fh2) // 2]

    tgt_uid, tgt_u = p2[0]
    chg_uid, chg_u = p1[0]
    tgt_mid = gs["squad_models"][tgt_uid][0]
    chg_mid = gs["squad_models"][chg_uid][0]

    def place(mid, col, row, level):
        update_model_position(gs, str(mid), int(col), int(row), level=int(level))

    # 1) cible à l'étage L1 (3"), chargeur au SOL au même (col,row) horizontal
    place(tgt_mid, c1[0], c1[1], 1)
    place(chg_mid, c1[0], c1[1], 0)
    te = gs["units_cache"][tgt_uid]
    ce = gs["units_cache"][chg_uid]
    tgt_h = te["floor_height_by_model"][tgt_mid]
    chg_h = ce["floor_height_by_model"][chg_mid]
    tgt_mh = te.get("MODEL_HEIGHT")
    chg_mh = ce.get("MODEL_HEIGHT")
    print(f"[cible {tgt_u.get('unit_type')}] floor_height={tgt_h} MODEL_HEIGHT={tgt_mh}")
    print(f"[chargeur {chg_u.get('unit_type')}] floor_height={chg_h} MODEL_HEIGHT={chg_mh}")
    assert tgt_h == 3.0, f"cible L1 doit avoir floor_height 3.0, eu {tgt_h}"
    assert chg_h == 0.0, f"chargeur sol doit avoir floor_height 0.0, eu {chg_h}"
    assert tgt_mh is not None and chg_mh is not None, "MODEL_HEIGHT absent (roster non propagé)"

    ez = int(gs["config"]["game_rules"]["engagement_zone"])
    # même (col,row) -> distance horizontale nulle : seul le gate vertical décide
    r_3d = unit_entries_within_engagement_zone(ce, te, ez, metric="euclidean", vertical_zone_inches=5.0)
    r_2d = unit_entries_within_engagement_zone(ce, te, ez, metric="euclidean")
    print(f'cible L1 (3") : 3D(vz=5)={r_3d}  2D={r_2d}')
    assert r_3d and r_2d, "cible L1 doit être engageable (gap vertical faible)"

    # 2) cible à L2 (6") : le gate doit REFUSER en abaissant vz sous le gap réel
    place(tgt_mid, c2[0], c2[1], 2)
    place(chg_mid, c2[0], c2[1], 0)
    te = gs["units_cache"][tgt_uid]
    ce = gs["units_cache"][chg_uid]
    assert te["floor_height_by_model"][tgt_mid] == 6.0
    # gap vertical réel entre [0, chg_mh] et [6, 6+tgt_mh] = max(0, 6 - chg_mh)
    gap = max(0.0, 6.0 - float(chg_mh))
    print(f'cible L2 (6") : gap vertical réel = {gap}')
    r_below = unit_entries_within_engagement_zone(ce, te, ez, metric="euclidean", vertical_zone_inches=gap - 0.5)
    r_above = unit_entries_within_engagement_zone(ce, te, ez, metric="euclidean", vertical_zone_inches=gap + 0.5)
    print(f"cible L2 : vz={gap - 0.5}(sous gap)->{r_below}  vz={gap + 0.5}(sur gap)->{r_above}")
    assert (not r_below) and r_above, "le gate vertical doit basculer exactement au gap réel"

    # ------------------------------------------------------------------------------------------------
    # 3) 3b — LE CHARGEUR MONTE : le champ climb produit des destinations d'étage (coût de montée §13.06
    #    soustrait du jet) et le pool charge_model_plan_state porte le niveau par ancre.
    # ------------------------------------------------------------------------------------------------
    from engine.game_state import unit_can_occupy_upper_floor
    from engine.hex_utils import get_neighbors
    from engine.phase_handlers.charge_handlers import (
        _charge_model_climb_reachable_floor_cells, charge_model_plan_state,
    )
    from engine.terrain_utils import low_clearance_ground_hexes

    # Chargeur montant : première unité p1 capable de finir en hauteur (INFANTRY/BEASTS/SWARM/FLY/MONSTER).
    climber = next(
        ((uid, u) for uid, u in p1 if unit_can_occupy_upper_floor(u["UNIT_KEYWORDS"])), None
    )
    if climber is None:
        print("\n3b : aucune unité p1 montante dans ce roster — sous-test climb sauté (non bloquant).")
        print("\nOK — engagement 3D charge validé sur le VRAI scénario à étages (données roster + floors réels).")
        return 0
    clb_uid, clb_u = climber
    clb_mid = gs["squad_models"][clb_uid][0]
    clb_model = gs["models_cache"][clb_mid]

    # Cible sur L1 (c1) ; chargeur au SOL sur un hex adjacent au pied de la ruine (hors plancher, hors mur).
    place(tgt_mid, c1[0], c1[1], 1)
    walls = set(gs.get("wall_hexes", set()))
    fh1_set = set(fh1)
    ground_start = next(
        (nb for cell in fh1 for nb in get_neighbors(cell[0], cell[1])
         if nb not in fh1_set and nb not in walls
         and 0 <= nb[0] < gs["board_cols"] and 0 <= nb[1] < gs["board_rows"]),
        None,
    )
    if ground_start is None:
        raise RuntimeError("3b : pas d'hex de sol adjacent au plancher L1")
    place(clb_mid, ground_start[0], ground_start[1], 0)

    ish = int(gs["inches_to_subhex"])
    budget = 12 * ish  # gros jet de charge (2D6 max) en sous-hex
    ta = gs["terrain_areas"]
    ground_obs = set(walls) | low_clearance_ground_hexes(ta, float(clb_u["MODEL_HEIGHT"]))
    # (les ennemis ne bloquent pas ici : on teste la montée pure)
    fcells = _charge_model_climb_reachable_floor_cells(
        gs, clb_u, clb_uid, clb_model, (ground_start[0], ground_start[1]), budget, 1, ground_obs, ta,
    )
    print(f"3b climb : chargeur={clb_u.get('unit_type')} depart_sol={ground_start} "
          f"budget_subhex={budget} -> {len(fcells)} cases L1 atteignables")
    assert fcells, "3b : le chargeur montant doit atteindre au moins une case de l'étage L1"
    assert all(isinstance(d, int) and d >= 0 for d in fcells.values()), "3b : distances climb invalides"

    # Budget serré : monter coûte au moins la hauteur de l'étage (3") -> budget < 3" => aucune case L1.
    tiny = max(0, (2 * ish) - 1)  # ~2" < 3" de montée
    fcells_tiny = _charge_model_climb_reachable_floor_cells(
        gs, clb_u, clb_uid, clb_model, (ground_start[0], ground_start[1]), tiny, 1, ground_obs, ta,
    )
    print(f"3b climb : budget serré {tiny} sous-hex (<3\" de montée) -> {len(fcells_tiny)} cases L1")
    assert not fcells_tiny, "3b : sous le coût de montée §13.06, aucune case d'étage ne doit être atteignable"

    # Pool bout-en-bout : déclaration de charge injectée -> charge_model_plan_state en vue L1 renvoie des
    # ancres [col,row,level>=1] (le chargeur peut finir engagé EN HAUTEUR avec la cible surélevée).
    # Le chemin 3D d'étage est euclidean-only (métrique GAMEPLAY) ; l'env de test est en gym (metric hex,
    # 2D par design RL) -> on bascule en mode PvP (distance_metric['charge'] = euclidean) pour ce sous-test.
    gs["gym_training_mode"] = False
    gs.setdefault("charge_target_selections", {})[clb_uid] = [tgt_uid]
    gs.setdefault("charge_roll_values", {})[clb_uid] = 12
    state = charge_model_plan_state(gs, clb_uid, {}, selected_model=clb_mid, level=1)
    floor_anchors = [a for a in state["pool"] if len(a) >= 3 and int(a[2]) >= 1]
    print(f"3b pool : phase={state['current_phase']} pool_total={len(state['pool'])} "
          f"ancres_etage={len(floor_anchors)}")
    assert floor_anchors, "3b : charge_model_plan_state (vue L1) doit produire des ancres d'étage level>=1"
    assert all(len(a) == 3 for a in state["pool"]), "3b : chaque ancre du pool doit porter [col,row,level]"

    print("\nOK 3b — le chargeur MONTE : destinations d'étage (coût §13.06) + pool niveau-conscient validés.")
    print("\nOK — engagement 3D charge validé sur le VRAI scénario à étages (données roster + floors réels).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
