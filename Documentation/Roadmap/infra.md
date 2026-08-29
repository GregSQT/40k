# Infra / Perf / DB — Tâches ouvertes

---

## Accélération de l'entraînement RL — phases 0→4 {#perf-entrainement}

**✅ Phases 0, 1, 2, 3 et 4 entièrement livrées.** Gains réels : Phase 1 = P99 −44 % et wall −32 % ;
Phase 2 = `time/fps` 200 → 226-233 (+13-16 %) ; Phase 4 = gate parallélisé + pool persistant + `bot_eval_n_workers` → 2.
Phase 3 livrée (2026-08-28) : collecte distribuée Option A — chaque worker déroule 340 steps en
autonome avec policy CPU gelée, retourne sa trajectoire ; learner fait uniquement l'update GPU.
**Gain time/fps mesuré (2026-08-28) : médiane 487 fps (3 reps x1_debug, machine au repos) vs 226-233 fps Phase 2 → +113 % (×2,1).** Voir §6 perf_entrainement.md.
Correctif qualité d'apprentissage (2026-08-29) : le re-scaling des sorties du critique par
`sqrt(old_ret_var)/sqrt(new_ret_var)` est retiré — au rollout 1 d'un run `--new` il valait 0,060
et écrasait les prédictions de 17×, `ret_var=1.0` n'étant que la valeur d'initialisation de
`RunningMeanStd`. **Effet sur la vitesse d'apprentissage non mesuré : à relever au prochain
run `x1_long --new`** (`explained_variance` et `ep_rew_mean` à ~750 k steps, références au journal).
Goulots restants : aucun identifié de cette ampleur.

→ `Documentation/Chantiers/backlog/perf_entrainement.md`

---

## Noyau natif BFS move/empreintes {#noyau-natif}

**Lourd, EN PAUSE** (décision 2026-08-16 : non lancé). Le pool de déplacement (`build_squad_move_cell_map` → `erode_move_pool_by_squad_block` → `geodesic_move_reach`) pèse **29 % d'une partie d'évaluation** — calcul dérivé, optimisable sous verrou d'empreinte `step.log`.

→ `Documentation/Chantiers/backlog/perf_noyau_natif_et_gzip.md` §2

---

## Migration PostgreSQL {#postgresql}

**Lourd, re-cadrer avant reprise.** Plusieurs semaines. Spec de mars 2026 visant des modules `ai/` réécrits par V11 depuis — re-confronter au code avant.

→ `Documentation/Chantiers/backlog/migration_postgresql.md` ; prompt d'exécution : `Documentation/Chantiers/backlog/migration_postgresql.md`

---

## MCTS adversaire d'entraînement {#mcts}

**Lourd.** Plusieurs semaines (P0+P1 ≈ 1-2 sem.). Après stabilité obs/masques.

Distinct du MCTS à l'inférence ([bot.md#mcts-inference](bot.md#mcts-inference)).

→ `Documentation/Chantiers/backlog/mcts_adversaire.md`
