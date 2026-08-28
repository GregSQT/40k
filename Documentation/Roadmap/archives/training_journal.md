> **Archive de journal.** Ce fichier regroupe les sections de journal daté extraites de
> `AI_TRAINING.md` lors de la consolidation P4 (2026-08-28). Source vivante :
> `Documentation/Reference/training/entrainement.md`.

---

# Journal d'entraînement IA

Ce fichier archive les sections de journal datées : runs avec dates spécifiques, résultats chiffrés
de run, tableaux de mesures datés, tentatives d'optimisation performance.

---

## Journal de tuning performance

> Ce journal trace les tentatives d'optimisation avec leur résultat réel. But : ne pas répéter les mêmes erreurs, comprendre pourquoi ça a marché ou non.

---

### [2026-05] Accélération entraînement x10 — BFS pathfinding

**Contexte**

L'entraînement x10 (`--training-config x10 --resolution 10`, 48 SubprocVecEnv, n_steps=16384) tournait à ~230 s/ep (vs ~5.7 s/ep en x1). Un profiling via `W40K_PERF_TIMING_MIN_EPISODE=2` sur 48 épisodes a révélé :

- **94% du temps handler** est dans le BFS pathfinding (559s / 594s)
- Move BFS : 102s (~17% du total)
- Charge BFS : 237s (~40% du total)

Particularités x10 : board 360×312 = 112 320 hexes, empreintes de 433 hexes (base 25mm), move_range=60 hexes, pas de topologie .npz → tout le pathfinding est on-demand.

---

**Tentative 1 — numba JIT sur le move BFS** ❌ Revert

- **Cible** : `engine/phase_handlers/movement_handlers.py` — boucle deque Python remplacée par `@numba.njit(cache=True)` avec queue numpy préallouée (`engine/fast_bfs.py`)
- **Résultat x1** : 5.69 → 5.98 s/ep (légèrement plus lent, pas de gain)
- **Raisons de l'échec** :
  1. Sur x1 (25×21), le BFS visite ~37 nœuds → Python est quasi-instantané, l'overhead numba domine
  2. L'allocation de 3 tableaux `int32[112K]` à l'intérieur de la fonction JIT (1.3 MB) génère une pression mémoire par appel
  3. Move BFS = seulement 17% du temps total sur x10 → gain maximal théorique ~15%, insuffisant même parfait
- **Leçon** : numba est efficace quand la boucle est longue et les données déjà numpy. Ici, la fonction était appelée trop souvent avec une queue trop grande et trop peu de nœuds visités sur x1.

---

**Tentative 2 — numpy board arrays sur le charge BFS** ❌ Revert

- **Cible** : `engine/phase_handlers/charge_handlers.py`
- **Résultat x10** : 233.83 → 287.59 s/ep (**+23%, plus lent**)
- **Raisons de l'échec** :
  1. Sur x10, chaque appel initialise 5-6 tableaux `np.zeros((360, 312))` + itère en Python sur ~13K hexes — coût 3-5ms par appel
  2. Ce coût d'initialisation n'est pas amorti : le BFS peut être pruné tôt et ne visiter que quelques dizaines de nœuds near-enemy
  3. L'original utilisait des sets Python (lookups O(1) en C) très rapides pour des ensembles modérés
- **Erreur de diagnostic** : le log mesurait le temps CPU total sur 48 épisodes, pas le coût par appel BFS individuel.

---

**Leçons générales**

| Leçon | Détail |
|-------|--------|
| Tester sur la board cible | x1 n'est pas représentatif de x10 |
| Mesurer le coût d'init vs. gain per-nœud | Un `np.zeros(112K)` coûte plusieurs ms |
| Le profiling agrégé ne suffit pas | "BFS = 237s sur 48 épisodes" ne dit pas si c'est 1 appel lent ou 10 000 courts |
| Sets Python C sont déjà optimisés | `x in set` est O(1) en C |
| Le gain max borné | 17% du total → rendre instantané = 17% max |

---

**Pistes non explorées**

- Caching des board arrays entre appels (construire une fois par tour)
- Numba sur la boucle BFS entière (inputs numériques, board arrays précomputés au niveau épisode)

---

### [2026-05] Charge BFS — `bfs_cache_hits_n=0` ❌ Non optimisable

**Constat** : `CHARGE_BUILD_POOL` log `bfs_cache_hits_n=0` sur 473 calls (5.5s total). Le cache `_has_valid_charge_cache` ne produit aucun hit.

**Pourquoi** : le cache est invalidé à chaque incrément de `_unit_move_version`. `_unit_move_version` s'incrémente après chaque charge → toutes les clés ont une version périmée.

**Pourquoi l'invalidation est correcte** :
1. Une unité peut mourir pendant une charge (combat réactif) → les cibles valides changent
2. Une charge peut bloquer le chemin BFS vers une cible qui était atteignable avant

On ne peut pas clef par hash des positions ennemies seules car le chemin dépend aussi des alliés.

**Conclusion** : pas d'optimisation possible sans changer la sémantique du jeu. Le coût de 5.5s est incompressible.

---

### [2026-05] MOVE_POOL_BUILD BFS fly=False MOVE=60 — Non optimisable

**Constat** : 236 calls MOVE=60 fly=False, bfs_s moyen 27ms, max 146ms, total 6.4s. Visited ~10 600 hexes par call.

**Pourquoi ce n'est pas optimisable** : sur Board ×10, une unité MOVE=60 centrale peut atteindre π×60² ≈ 11 300 hexes. Le BFS en visite ~10 600 — c'est le coût exact du calcul correct. Il n'existe pas d'algorithme sub-linéaire pour calculer l'ensemble des hexes atteignables avec obstacles.

**MOVE=60 est réel** : ce sont des unités avec MOVE=6 en x1 mises à l'échelle ×10.

---

### [2026-05] MOVE_POOL_BUILD fly=True single-hex — `_build_multi_hex_vectorized` ❌ Revert

**Contexte**

Benchmark x10_debug : MOVE_POOL_BUILD coûte 1 962s cumulés (avg 35.5ms/call, 55K calls). Les 20 appels les plus lents sont `fly=True MOVE=120 base_size=1` à ~0.4–0.5s chacun, visitant jusqu'à 43 561 nœuds.

**Ce qui a été tenté**

Changer `_fly_single_hex = (ez <= 1 or base_size == 1)` → `_fly_single_hex = ez <= 1` dans `movement_handlers.py`.

**Résultat**

SCORE : 13.1587 → 13.1311 ms/call (**-0.21%, dans le bruit ±0.2%**). Revert.

**Pourquoi ça n'a pas marché**

Le chemin NumPy traite un array 360×312 = 112K cellules en entier (10 passes de spread sur 112K cells = ~60 opérations array). Le BFS Python optimisé visite 25K–43K nœuds avec des lookups O(1) en C. Les deux approches coûtent ~35ms.

---

### [2026-05] MOVE_POOL_BUILD fly=True single-hex — Énumération géométrique ✅ Appliqué

**Contexte**

Bottleneck : fly=True single-hex BFS Python visitait ~43K nœuds pour MOVE=120. Pour fly units, les obstacles sont traversés → distance BFS == distance cube → le disque est énumérable directement.

**Ce qui a été fait**

Remplacement du BFS par une énumération géométrique directe du disque cube dans `movement_handlers.py` :
- Conversion start offset → cube
- Double boucle dx/dy dans [-r, r]
- Reconversion cube → offset
- Filtrage bounds/walls/occupied/EZ identique

**Résultat**

| Mesure | SCORE | Delta |
|--------|-------|-------|
| Baseline | 13.1587 ms/call | — |
| Après (run 1) | 12.9837 ms/call | -1.33% |
| Après (run 2) | 12.8903 ms/call | -2.04% |
| Après (run 3) | 12.8027 ms/call | -2.70% |

**Analyse post-mesure**

La moyenne per-call fly=True MOVE=120 est passée de ~35ms (BFS) à ~81ms (géométrique). Le BFS avait des pics à 0.4–0.5s. L'énumération géométrique est **uniforme** → moins de stalls de synchronisation avec SubprocVecEnv 48 envs → meilleur débit malgré la moyenne plus élevée.

---

### [2026-05] MOVE_POOL_BUILD fly=True — Précomputation `_fly_ez_prox_set` ✅ Appliqué

**Contexte**

Analyse fine du breakdown de `bfs_s=66ms` sur fly=True MOVE=120 :
- Géométrie + bounds + tuple creation : 27ms (37%)
- Walls/occupied lookup : 11ms (15%)
- EZ checks (`_movement_engagement_violates`) : **35ms (47%)**

Les 35ms EZ : ~21ms proximity filter (N ennemis × `calculate_hex_distance` pour 43K hexes) + ~11ms appels `_movement_engagement_violates`.

**Ce qui a été fait**

Remplacement du proximity filter per-hex par une précomputation unique avant la boucle :

```python
# Une seule fois avant la boucle
_fly_ez_prox_set = set()
for _fec, _fer, _feth in _fly_prox_list:
    _fly_ez_prox_set |= dilate_hex_set({(_fec, _fer)}, _feth, board_cols, board_rows)

# Dans la boucle : O(1) set lookup
if _fly_ez_prox_set is not None and nb not in _fly_ez_prox_set:
    valid_destinations.append(nb)
elif not _movement_engagement_violates(...):
    valid_destinations.append(nb)
```

**Résultat**

| Mesure | SCORE | Delta |
|--------|-------|-------|
| Baseline (post charge-fix) | 12.0060 ms/call | — |
| Après fix | **11.5560 ms/call** | **-3.75%** |

**Cumulé depuis le baseline original (13.1587) : -12.2%.**

---

### [2026-05] CHARGE_REVERSE_GOAL_BFS — Suppression `dilate_hex_set({start_pos}, 120)` ✅ Appliqué

**Contexte**

`CHARGE_HAS_VALID_TARGET` / `CHARGE_REVERSE_GOAL_BFS` coûtaient 100ms/call avec seulement 18ms de BFS réel. Root cause : `dilate_hex_set({start_pos}, 120, 360, 312)` à chaque appel pour construire le `start_reach_disk` (~43K hexes). Cache `_charge_reach_disk_cache` → 100% de cache misses (chaque chargeur à une position différente).

**Ce qui a été fait**

Remplacement de `dilate_hex_set({start_pos}, bfs_max_distance)` par un filtre géométrique direct :

```python
# Avant — O(43K BFS) + O(n) intersection
start_reach_disk = dilate_hex_set({start_pos}, 120, ...)  # ~60ms
goal_zone = enemy_goal_zone & start_reach_disk

# Après — O(|enemy_goal_zone|) checks de distance
goal_zone = {h for h in enemy_goal_zone if hex_distance(h[0], h[1], start_col, start_row) <= _bfs_max}
```

`enemy_goal_zone` ≈ 786 hexes → 786 appels O(1) au lieu de 43K BFS. Suppression du cache `_charge_reach_disk_cache`.

**Résultat**

| Mesure | SCORE | Delta vs baseline fly-fix (12.80) |
|--------|-------|-----------------------------------|
| Baseline fly-fix | 12.80 ms/call | — |
| Après (run 1, 192 ep) | 12.5802 ms/call | -1.72% |
| Après (run 2, 192 ep) | 12.4334 ms/call | -2.86% |
| Après (600 ep) | **12.0060 ms/call** | **-6.2%** |

**Cumulé depuis le baseline original (13.1587) : -8.8%.**

---

### [2026-05] Méthode d'évaluation des optimisations perf — Référence

**Métrique de référence** : la colonne **`ms/ep`** (coût de l'événement par épisode), affichée par `python3 engine/perf_timing.py <log>` et sauvegardée sous `ms_per_episode` dans `<log>.score.json`.

**Pourquoi pas le `SCORE` ms/call** :
- moyenne par appel : une optimisation qui *supprime* des appels la fait **monter** alors que le temps réel baisse
- son numérateur additionne des timers **imbriqués** → ~20% du total est compté deux fois

**Stabilité — mesurée, par métrique** :
- `ms/call` : variance ±0.16%, delta > 1% significatif
- `ms/ep` : besoin d'un échantillon d'épisodes — **192 épisodes minimum**, delta doit dépasser ~15% pour être concluant

| Ligne | 48 épisodes (étendue) | 192 épisodes (étendue) |
|---|---|---|
| `MOVE_POOL_BUILD` | 12,2 % | **5,7 %** |
| `CHARGE_PHASE_START` | 26,7 % | **4,5 %** |
| `CHARGE_BUILD_POOL` | 31,7 % | **5,7 %** |
| `CHARGE_REVERSE_GOAL_BFS` | 61,0 % | **12,8 %** |

**Seuils à retenir** :
- **48 épisodes : inutilisable.**
- **192 épisodes : delta > ~15% nécessaire.** En dessous, ne rien conclure.
- Pour un gain plus fin : passer à l'**A/B entrelacé** (`scripts/ab_bench.py`).

**Commande de la mesure de stabilité** :
```bash
W40K_PERF_TIMING=1 W40K_PERF_TIMING_MIN_EPISODE=2 W40K_PERF_TIMING_LOG=stab_N.log \
  python3 ai/train.py --agent ArmageddonAgent --training-config x1_debug --scenario bot \
  --new --total-episodes 192 --param n_envs 4 --resolution 1
python3 engine/perf_timing.py stab_N.log
```
Coût : 2 min 11 s par run (mesuré), soit ~7 min pour les trois.

**Commande benchmark x10** :
```bash
W40K_PERF_TIMING=1 W40K_PERF_TIMING_LOG=perf_timing_bench_x10.log W40K_PERF_TIMING_MIN_EPISODE=2 \
  python3 ai/train.py --agent CoreAgent --training-config x10_debug \
  --scenario config/agents/CoreAgent/scenarios/training/training_benchmark/scenario_training_benchmark.json \
  --new --resolution 10 && python3 engine/perf_timing.py perf_timing_bench_x10.log
```

**Barre de progression depuis le 2026-08-01** : `[s/ep (48 env): cur 0.300, moy 0.211, min/max: 0.240/0.338]`. `moy` = `(elapsed − temps bloqué par l'éval) / episode_count`. L'amorçage est signalé : `[s/ep (48 env, 10/48 slots): …]` — pendant cette phase les quatre chiffres décrivent une population incomplète.

**Comparer deux `n_envs`** : utiliser `scripts/ab_bench_nenvs.py` (entrelacement, appariement). La barre seule ne suffit pas — la latence mesurée par slot croît mécaniquement avec `n_envs`.

---

### [2026-08] Comparer un hyperparamètre : quel banc, quelle grandeur

Deux questions distinctes, deux outils :

| Question | Outil | Grandeur | Coût |
|---|---|---|---|
| « ça tourne plus vite ? » | `scripts/ab_bench_param.py` | `moy` : secondes par épisode de boucle | ~2 runs × `--paires` |
| « ça apprend mieux ? » | `scripts/ab_bench_perf.py` | win-rate combiné (holdout) | 2 entraînements complets + 2 évals par graine |

- `ab_bench_nenvs.py` reste l'outil de référence pour `n_envs`.
- **Aiguillage** : `n_envs`, `n_steps`, `n_epochs` → débit (mais un gain en vitesse peut coûter en qualité) ; `batch_size`, `learning_rate`, `gamma`, `gae_lambda`, `ent_coef` → qualité.
- **Contrôle anti-confusion** : les deux bancs relisent la valeur **effectivement instanciée par PPO** dans le membre `data` du modèle sauvegardé.
- **Pourquoi ≥ 5 graines côté qualité** : le test des signes bilatéral ne peut pas descendre sous `2 × 0,5ⁿ`, soit 0,25 à 3 graines.
- **`learning_rate` et `ent_coef` sont schedulés en `x1`** : leur donner une valeur scalaire supprime le callback. Les bancs refusent par défaut et exigent `--autoriser-suppression-schedule`.
- **`n_steps` n'est pas une égalité** : la config donne le total par mise à jour, PPO reçoit `base // n_envs`.
- **Environnement propre exigé** : `env | grep W40K` avant toute campagne — 12 variables `W40K_*` peuvent changer la vitesse ou l'objet du run.

```bash
git worktree add /tmp/40k-bench HEAD
python3 scripts/ab_bench_param.py --param model_params.n_steps --a 8192 --b 4096 \
    --episodes 96 --paires 5 --training-config x1
python3 scripts/ab_bench_perf.py --param model_params.batch_size --a 1024 --b 2048 \
    --episodes 2000 --graines 1,2,3,4,5 --eval-episodes 100 --training-config x1
git worktree remove /tmp/40k-bench
```

---

### [2026-08] Classement de `n_envs` — 37 runs, 6,6 h ⚠️ À REPRENDRE

> **Classement établi sur le wall-clock complet, démarrage inclus.** Les bancs mesurent désormais
> la boucle seule (`moy`) — ce verdict « 48 optimal » peut être un artefact de fork. **À refaire
> avec les bancs actuels avant de s'appuyer dessus.**

> ⛔ **CONCLUSION N'EST PLUS APPLICABLE (2026-08-26).** `n_envs: 48` est REFUSÉ. La configuration
> courante est `n_envs: 24` sur les 6 profils — la RAM fait exploser la VM pendant le self-play.
> Les 16,3 Go libres relevés à 48 ci-dessous sont hors self-play. De plus `n_steps` vaut désormais
> 8160 (commit `7c466b15`, 2026-08-26) au lieu de 8192. **`batch_size: 1020` reste juste** :
> à `n_steps: 8160` / `n_envs: 24`, le rollout vaut `8160 = 8 × 1020`.

Deux campagnes, machine 8 cœurs / 40 Go, `ArmageddonAgent` phase `x1`, évaluation bot désactivée. Reproduction :

```bash
git worktree add /tmp/40k-bench HEAD
python3 scripts/ab_sweep_nenvs.py --envs 6,8,16,48 --episodes 144 --deadline 08:30
python3 scripts/ab_sweep_nenvs.py --envs 48,64 --episodes 192 --tours 3
git worktree remove /tmp/40k-bench
```

Première campagne — débit relatif au pivot `n_envs=6`, médiane sur 7 tours :

| `n_envs` | débit relatif | étendue | débit absolu | 144 épisodes |
|---|---|---|---|---|
| **48** | **1,435** | 1,366–1,626 | 0,285 ep/s | 8,4 min |
| 16 | 1,238 | 1,214–1,345 | 0,251 ep/s | 9,6 min |
| 8 | 1,098 | 0,997–1,185 | 0,219 ep/s | 11,0 min |
| 6 | 1,000 | — | 0,201 ep/s | 12,0 min |

Campagne complémentaire 48 vs 64 (3 tours, 192 épisodes) : **`64` est 4,2% PLUS LENT que `48`** (débit relatif 0,958, étendue 0,945–0,971). Mémoire libre : 30,5 Go à `n_envs=6`, 16,3 Go à 48, 10,0 Go à 64.

- **Plus d'environments que de cœurs reste gagnant** : 48 processus sur 8 cœurs battent 6 processus de 43%. Le goulot n'est pas le CPU de collecte.
- **Ce banc mesure le débit, pas la qualité d'apprentissage.** À 48 envs, ~2 parties par mise à jour (vs ~18 à 6 envs) — composition du lot différente.

---

### [2026-05] Suppression invalidation hex_los_cache / _hex_los_state_cache ✅ Appliqué

**Contexte**

Profiling sur scénario x10_debug. Budget des hotspots sur ~98.7s :

| Hotspot | Temps | % |
|---|---|---|
| ADVANCE `los_cache_s` | 30.7s | 31% |
| MOVE_COMMIT `los_cache_s` | 20.1s | 20% |
| MOVE_POOL_BUILD BFS | 24.9s | 25% |

**Diagnostic**

`_invalidate_los_cache_for_moved_unit` itérait en O(N) sur TOUT `_hex_los_state_cache` à chaque mouvement. Avec un cache de ~27 000 entrées : ~19ms/call × 1054 moves = 20s.

**Pourquoi l'invalidation était incorrecte**

`_hex_los_state_cache` stocke des résultats géométriques purement dépendants de `wall_set` (terrain statique). En 40K, les unités ne bloquent pas le LOS — seuls les murs comptent. Le résultat LOS entre deux hexes est une constante de la map.

**Correction**

| Cache | Dépend de | Traitement |
|---|---|---|
| `_hex_los_state_cache` | `wall_set` (terrain statique) | **Jamais invalidé** |
| `hex_los_cache` | `occupied_hexes` via `_has_line_of_sight` | Invalidation sélective maintenue |

**Gain estimé**

- MOVE_COMMIT `los_cache_s` : 20s → ~0
- **Total estimé : ~40-45s récupérés sur 50.8s**

> **⚠️ Superseded [2026-06] — terrain obscuring.** Ce chemin est désormais legacy. Le chemin de tir
> passe par **`compute_unit_los`** (obscuring-aware) : en plus des murs, les terrains obscuring
> bloquent. Le résultat LoS n'est **plus** une constante de la map. D'où un nouveau cache
> **par-paire** `_unit_los_pair_cache` (invalidé au `_unit_move_version`).

**Tests mis à jour**

`tests/unit/engine/test_los_cache_invalidation.py` — 2 tests remplacés. Suite : 8/8 ✅

---

## Notes de runs datées

### Durées de run mesurées

| Profil | Date | Durée | Épisodes | Notes |
|--------|------|-------|----------|-------|
| `x1` | 2026-08-10 | 4 h 01 | 10 000 | 11 h 17 → 15 h 18, évaluations non comprises |
| `x1_long` | 2026-08-18 | 5 h 54 | 50 000 | — |

> ⚠️ **Aucun taux d'épisodes par heure n'est publiable.** Extrapoler `x1 × 5` donnait « ~20 h »
> pour `x1_long` — faux d'un facteur 3,4. La pente n'est pas linéaire (la durée d'un épisode dépend
> de ce que la politique a appris) et les deux runs ne portent pas sur le même état du code. **Donc :
> chaque profil n'annonce que SA propre mesure directe, ou aucune durée.**
> Le `0.1 s/ep → 36k ép./h` que répétaient les anciennes notes `total_episodes_normal` datait du
> régime d'avant la refonte d'observation V11 ; il en a été retiré le 2026-08-23.
