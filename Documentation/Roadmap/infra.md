# Infra / Perf / DB — Tâches ouvertes

---

## Accélération de l'entraînement RL — phases 0→4 {#perf-entrainement}

**Phases 0, 1, 2 et 4.1 livrées et mesurées.** Gains réels : Phase 1 =
P99 −44 % et wall −32 % (la queue, pas la moyenne) ; Phase 2 = `time/fps` 200 → 226-233 (+13-16 %) ;
Phase 4.1 = gate parallélisé, parité confirmée (2026-08-27).
L'estimation initiale de ×2-3 pour 1+2+4 n'est pas atteinte : le lockstep de collecte (~73 % du
budget d'un cycle) est structurel et ne cède qu'à la Phase 3.
Phase 4 (évals/curriculum) : 4.1 ✅ gate parallélisé (B1–B7 livrés, décision B) ; **4.2 🟡** pool
persistant (jeton de version manquant) ; **4.3 🟡** `bot_eval_n_workers` fixé à 6 (était 16 → OOM),
1re mesure ~28 s/ép, clôture = 3 reps `duration 6` machine au repos.
Phase 3 (collecte distribuée, option A) = actée mais non lancée, chantier dédié hors
période de run — c'est elle qui porte le ×3-6.
Goulots restants : lockstep de collecte (Phase 3), pool d'éval non persistant (4.2).

→ `Documentation/Implémentation/A_faire/perf_entrainement.md`

---

## Noyau natif BFS move/empreintes {#noyau-natif}

**Lourd, EN PAUSE** (décision 2026-08-16 : non lancé). Le pool de déplacement (`build_squad_move_cell_map` → `erode_move_pool_by_squad_block` → `geodesic_move_reach`) pèse **29 % d'une partie d'évaluation** — calcul dérivé, optimisable sous verrou d'empreinte `step.log`.

→ `Documentation/Implémentation/A_faire/perf_noyau_natif_et_gzip.md` §2

---

## Migration PostgreSQL {#postgresql}

**Lourd, re-cadrer avant reprise.** Plusieurs semaines. Spec de mars 2026 visant des modules `ai/` réécrits par V11 depuis — re-confronter au code avant.

→ `Documentation/Implémentation/A_faire/Database/DB_migration.md` ; prompt d'exécution : `Documentation/Implémentation/A_faire/Database/DB_migration_prompt.md`

---

## MCTS adversaire d'entraînement {#mcts}

**Lourd.** Plusieurs semaines (P0+P1 ≈ 1-2 sem.). Après stabilité obs/masques.

Distinct du MCTS à l'inférence ([bot.md#mcts-inference](bot.md#mcts-inference)).

→ `Documentation/Implémentation/A_faire/MCTS/MCTS_bot_final.md`
