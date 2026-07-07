#!/usr/bin/env python3
"""Test de non-régression LoS pair-cache (LoS_unique_source_of_truth.md §6).

Construit un vrai jeu (board 44x60x5, murs walls-mc1, unités placées) puis exerce DIRECTEMENT
chaque fonction du choke-point d'invalidation LoS sur des unités réelles, en vérifiant après chaque
opération l'invariant :

    pour toute paire inter-camps (s, t) :
        compute_unit_los(gs, s, t)  ==  _compute_unit_los_uncached(gs, s, t)

`compute_unit_los` sert la valeur du pair-cache ; `_compute_unit_los_uncached` est la source de
vérité recalculée. Une entrée périmée (survivante d'un mouvement / d'une perte de figurine qui aurait
dû l'invalider) produit une divergence → AssertionError.

Chemins exercés : translate_squad_to_destination (move/charge/fight-translate), commit_move batch
(pile-in par-figurine), update_model_position figurine non-ancre, destroy_model (perte de figurine).

CONTRÔLE DE DENTS : le test désactive volontairement l'invalidation ciblée du pair-cache et vérifie
que l'invariant DÉTECTE la péremption (AssertionError attendue). Sans ce contrôle, un test vert ne
prouverait rien (il pourrait passer sans jamais exercer la péremption).

Lancement : python3 scripts/los_cache_invariant_test.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.training_utils import setup_imports
from ai.unit_registry import UnitRegistry
from services.api_server import get_agents_from_scenario
import engine.phase_handlers.shared_utils as su
from engine.phase_handlers.shared_utils import (
    translate_squad_to_destination,
    commit_move,
    update_model_position,
    destroy_model,
    assert_los_pair_cache_consistent,
)

SCENARIO = "config/board/44x60x5/scenario/scenario_pvp_test.json"


def build_env():
    W40KEngine, _ = setup_imports()
    ur = UnitRegistry()
    sf = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), SCENARIO)
    if not os.path.exists(sf):
        raise FileNotFoundError(sf)
    env = W40KEngine(
        rewards_config="default",
        training_config_name="x5_new",
        controlled_agent=sorted(get_agents_from_scenario(sf, ur))[0],
        scenario_file=sf,
        unit_registry=ur,
        quiet=True,
        gym_training_mode=True,
    )
    env.reset(seed=42)
    return env


def positions(gs):
    return [(u["col"], u["row"]) for u in gs["unit_by_id"].values()]


def main() -> int:
    env = build_env()
    gs = env.game_state
    ubi = gs["unit_by_id"]
    p1 = [str(k) for k, u in ubi.items() if u["player"] == 1]
    p2 = [str(k) for k, u in ubi.items() if u["player"] == 2]
    if not p1 or not p2:
        raise RuntimeError("Scénario sans deux camps")

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
    for uid in p1:
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
    multi = [uid for uid in p2 if len(sm.get(uid, [])) > 1]
    for uid in multi[:4]:
        mids = [m for m in sm.get(uid, []) if m in mc]
        if len(mids) < 2:
            continue
        # Plan par-figurine : décale chaque fig de (+1,+1) — footprint change, ancre incluse.
        plan = [(m, int(mc[m]["col"]) + 1, int(mc[m]["row"]) + 1) for m in mids]
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

    print(f"✅ INVARIANT OK — {ops} opérations choke-point, {checks} vérifications de paires, zéro divergence.")

    # ---- CONTRÔLE DE DENTS : prouver que l'invariant détecte une péremption ----
    from engine.phase_handlers.shooting_handlers import compute_unit_los, _compute_unit_los_uncached
    env2 = build_env()
    gs2 = env2.game_state
    ubi2 = gs2["unit_by_id"]
    s = next(str(k) for k, u in ubi2.items() if u["player"] == 1)
    s_unit = ubi2[s]
    enemies = [(str(k), u) for k, u in ubi2.items() if u["player"] == 2]

    original = su._invalidate_pair_cache_for_unit
    su._invalidate_pair_cache_for_unit = lambda *a, **k: None  # sabotage : plus d'invalidation ciblée
    detected = False
    try:
        # Pour chaque ennemi t : peuple (s,t) à la position courante de s, déplace s à ~8 hexs de t
        # (change la LoS, sans superposer), puis compare la valeur SERVIE (cache périmé) à la VÉRITÉ.
        for tid, t_unit in enemies:
            compute_unit_los(gs2, s_unit, t_unit)  # peuple v_old
            translate_squad_to_destination(gs2, s, int(t_unit["col"]), int(t_unit["row"]) - 8)
            if str(s) not in gs2["units_cache"]:
                break  # s a disparu (dégénéré) — on s'arrête
            served = compute_unit_los(gs2, s_unit, t_unit)
            truth = _compute_unit_los_uncached(gs2, s_unit, t_unit)
            if served != truth:
                detected = True
                break
    finally:
        su._invalidate_pair_cache_for_unit = original

    if detected:
        print("✅ CONTRÔLE DE DENTS OK — sans invalidation, le pair-cache sert une valeur périmée "
              "que l'invariant détecte.")
        return 0
    print("❌ CONTRÔLE DE DENTS ÉCHOUÉ — aucune péremption servie détectée : test sans valeur.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
