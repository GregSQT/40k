"""Non-régression LoS pair-cache (ligne_de_vue.md §6).

Construit un vrai jeu (board 44x60x5, murs walls-mc1, unités placées) puis exerce DIRECTEMENT
chaque fonction du choke-point d'invalidation LoS sur des unités réelles, en vérifiant après chaque
opération l'invariant :

    pour toute paire inter-camps (s, t) :
        compute_unit_los(gs, s, t)  ==  _compute_unit_los_uncached(gs, s, t)

`compute_unit_los` sert la valeur du pair-cache ; `_compute_unit_los_uncached` est la source de
vérité recalculée. Une entrée périmée (survivante d'un mouvement / d'une perte de figurine qui
aurait dû l'invalider) produit une divergence.

Chemins exercés : translate_squad_to_destination (move/charge/fight-translate), commit_move batch
(pile-in par-figurine), update_model_position figurine non-ancre, destroy_model (perte de figurine).

CONTRÔLE DE DENTS (`test_pair_cache_staleness_is_detectable`) : l'invalidation ciblée du pair-cache
est volontairement désactivée et on vérifie que l'invariant DÉTECTE la péremption. Sans ce contrôle,
un test vert ne prouverait rien (il pourrait passer sans jamais exercer la péremption).

Rapatrié de `scripts/los_cache_invariant_test.py` (2026-07-26) : ce fichier vivait hors de `tests/`,
donc n'était jamais collecté par la suite.
"""

from __future__ import annotations

import os

import pytest

import engine.phase_handlers.shared_utils as su
from engine.phase_handlers.shared_utils import (
    assert_los_pair_cache_consistent,
    commit_move,
    destroy_model,
    translate_squad_to_destination,
    update_model_position,
)

SCENARIO = "config/board/44x60x5/scenario/scenario_pvp_test.json"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _build_env():
    from ai.training_utils import setup_imports
    from ai.unit_registry import UnitRegistry
    from services.api_server import get_agents_from_scenario

    W40KEngine, _ = setup_imports()
    ur = UnitRegistry()
    sf = os.path.join(PROJECT_ROOT, SCENARIO)
    if not os.path.exists(sf):
        raise FileNotFoundError(sf)
    env = W40KEngine(
        rewards_config="default",
        training_config_name="x1",
        controlled_agent=sorted(get_agents_from_scenario(sf, ur))[0],
        scenario_file=sf,
        unit_registry=ur,
        quiet=True,
        gym_training_mode=True,
    )
    env.reset(seed=42)
    return env


def _is_ground_squad(gs, uid: str) -> bool:
    """Vrai si toutes les figurines de l'escouade sont au sol (level 0).

    Les mutations de ce test déplacent les figurines par deltas horizontaux arbitraires. Sur une
    escouade à l'étage, la destination sort de l'empreinte du plancher et le moteur lève
    (``floor_height_at``) — état invalide fabriqué par le test, orthogonal à l'invariant LoS
    vérifié ici. On n'exerce donc le choke-point que sur les escouades au sol.
    """
    mc = gs["models_cache"]
    mids = [m for m in gs.get("squad_models", {}).get(uid, []) if m in mc]
    return bool(mids) and all(int(mc[m]["level"]) == 0 for m in mids)


def _sides(gs):
    ubi = gs["unit_by_id"]
    p1 = [str(k) for k, u in ubi.items() if u["player"] == 1]
    p2 = [str(k) for k, u in ubi.items() if u["player"] == 2]
    assert p1 and p2, "scénario sans deux camps"
    return p1, p2


def test_pair_cache_consistent_across_chokepoint_operations():
    """Après chaque opération du choke-point, aucune paire inter-camps ne sert de valeur périmée."""
    env = _build_env()
    gs = env.game_state
    ubi = gs["unit_by_id"]
    p1, p2 = _sides(gs)

    checks = 0
    ops = 0

    def touch_all_pairs():
        # Peuple d'abord le pair-cache À l'état courant (comme l'observation en jeu réel), puis vérifie.
        nonlocal checks
        checks += assert_los_pair_cache_consistent(gs)

    # Baseline.
    touch_all_pairs()

    # 1) translate_squad_to_destination — déplace chaque unité p1 par petits deltas LOCAUX (évite de
    #    superposer les unités, ce qui créerait des états dégénérés hors sujet). Le footprint change →
    #    la LoS peut changer → l'invalidation ciblée doit s'appliquer.
    ground_p1 = [uid for uid in p1 if _is_ground_squad(gs, uid)]
    assert ground_p1, "aucune escouade p1 au sol — impossible d'exercer translate_squad_to_destination"
    for uid in ground_p1:
        u = ubi[uid]
        base_c, base_r = int(u["col"]), int(u["row"])
        for dc, dr in ((6, 0), (0, 6), (-6, -6)):
            touch_all_pairs()  # peuple le cache à la position AVANT le move
            translate_squad_to_destination(gs, uid, base_c + dc, base_r + dr)
            ops += 1
            touch_all_pairs()  # doit être cohérent APRÈS le move (sinon entrée périmée)

    # 2) commit_move (batch pile-in) sur les escouades multi-figurines de p2.
    sm = gs.get("squad_models", {})
    mc = gs["models_cache"]
    multi = [uid for uid in p2 if len(sm.get(uid, [])) > 1 and _is_ground_squad(gs, uid)]
    for uid in multi[:4]:
        mids = [m for m in sm.get(uid, []) if m in mc]
        if len(mids) < 2:
            continue
        # Plan par-figurine : décale chaque fig de (+1,+1) — footprint change, ancre incluse.
        plan = [
            (m, int(mc[m]["col"]) + 1, int(mc[m]["row"]) + 1, int(mc[m]["level"]))
            for m in mids
        ]
        touch_all_pairs()
        commit_move(plan, gs, "pile_in")
        ops += 1
        touch_all_pairs()

    # 3) update_model_position sur une figurine NON-ancre (ancre = 1er de la liste).
    for uid in multi[:4]:
        mids = [m for m in sm.get(uid, []) if m in mc]
        if len(mids) < 2:
            continue
        non_anchor = mids[-1]
        touch_all_pairs()
        update_model_position(gs, non_anchor, int(mc[non_anchor]["col"]) + 2, int(mc[non_anchor]["row"]))
        ops += 1
        touch_all_pairs()

    # 4) destroy_model — retire une figurine de plusieurs escouades.
    for uid in (multi[:4] + [u for u in p1 if len(sm.get(u, [])) >= 1][:4]):
        mids = [m for m in sm.get(uid, []) if m in mc]
        if not mids:
            continue
        touch_all_pairs()
        destroy_model(gs, mids[-1], reason="combat")
        ops += 1
        touch_all_pairs()

    assert ops > 0, "aucune opération de choke-point exercée — test sans valeur"
    assert checks > 0, "aucune paire vérifiée — test sans valeur"


def test_pair_cache_staleness_is_detectable(monkeypatch):
    """CONTRÔLE DE DENTS : sans invalidation ciblée, le cache sert une valeur périmée détectable."""
    from engine.phase_handlers.shooting_handlers import _compute_unit_los_uncached, compute_unit_los

    env = _build_env()
    gs = env.game_state
    ubi = gs["unit_by_id"]
    s = next(
        (str(k) for k, u in ubi.items() if u["player"] == 1 and _is_ground_squad(gs, str(k))),
        None,
    )
    assert s is not None, "aucune escouade p1 au sol — le sabotage ne peut pas être exercé"
    s_unit = ubi[s]
    enemies = [(str(k), u) for k, u in ubi.items() if u["player"] == 2]
    assert enemies, "scénario sans ennemi"

    # Sabotage : plus d'invalidation ciblée du pair-cache.
    monkeypatch.setattr(su, "_invalidate_pair_cache_for_unit", lambda *a, **k: None)

    detected = False
    # Pour chaque ennemi t : peuple (s,t) à la position courante de s, déplace s à ~8 hexs de t
    # (change la LoS, sans superposer), puis compare la valeur SERVIE (cache périmé) à la VÉRITÉ.
    for _tid, t_unit in enemies:
        compute_unit_los(gs, s_unit, t_unit)  # peuple v_old
        translate_squad_to_destination(gs, s, int(t_unit["col"]), int(t_unit["row"]) - 8)
        if str(s) not in gs["units_cache"]:
            break  # s a disparu (dégénéré) — on s'arrête
        served = compute_unit_los(gs, s_unit, t_unit)
        truth = _compute_unit_los_uncached(gs, s_unit, t_unit)
        if served != truth:
            detected = True
            break

    assert detected, (
        "aucune péremption servie détectée : l'invariant du test précédent n'a pas de dents"
    )
