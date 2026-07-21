# V11 — Optimisation du coût de construction du pool de move

> **Chantier moteur / perf dédié.** Sorti de `V11_agent_rework.md §0.22` (qui reste le pointeur).
> Objet : réduire le coût de `MOVE_POOL_BUILD`, **sans jamais altérer le pool produit** (métier)
> **ni le comportement PvP**. Rien n'est implémenté à ce jour : ce document est le cadrage.
>
> Date de cadrage : 2026-07-21. Décision utilisateur : « Il faut travailler là-dessus, et
> s'assurer que le gain de performance ne se fasse pas au détriment du métier et du PvP. »
>
> Toutes les affirmations de code sont ancrées `fichier:ligne` (vérifiées le 2026-07-21 par
> lecture directe + cartographie). Les numéros de ligne sont indicatifs : re-grep avant d'éditer.

---

## 1. Objectif et contrainte NON négociable

**Objectif.** Réduire le temps de construction du pool de destinations de move, qui domine le coût
d'un run (95,6 %, cf. §3). **Cible = le run x5 sur le board de référence `config/board/44x60x5`**
(décision §9-D1) : 44×60 pouces à résolution 5 → **grille 220×300 subhex**
([board_config.json](../../config/board/44x60x5/board_config.json) : `cols=220, rows=300,
inches_to_subhex=5`). C'est ce mode qu'on optimise ; une perte de perf sur x1/x10 est acceptable,
une perte de **métier** ne l'est nulle part.

**Contrainte absolue (garde-fou métier).** Le pool produit après optimisation doit être
**strictement identique**, hex pour hex (destinations, footprint zone, coûts géodésiques
`out_costs`), à celui produit aujourd'hui. C'est l'invariant déjà inscrit dans le docstring de
`_build_multi_hex_vectorized` ([movement_handlers.py:1557](../../engine/phase_handlers/movement_handlers.py#L1557)) :
« équivalence stricte avec le BFS Python hex orig. ». Un cache qui accélère mais change **un seul**
hex du pool est une **régression métier ET PvP**, pas une optimisation.

**Corollaire — le risque réel.** Un pool faux ne lève **aucune exception** : l'agent s'entraîne et
le PvP joue sur des destinations invalides **silencieusement**. Ce chantier ne peut donc pas se
valider par « le run passe » : il se valide par un test d'**équivalence A/B** (pool avec cache ==
pool sans cache) et une **non-régression PvP**.

---

## 2. Portée EXACTE de la fonction ciblée (à ne pas se tromper de cible)

`_build_multi_hex_vectorized` ([movement_handlers.py:1523](../../engine/phase_handlers/movement_handlers.py#L1523))
a **exactement deux sites d'appel**, tous deux internes à `movement_build_valid_destinations_pool`
(même fichier) :

- **Appel 1 — FLY multi-hex** ([movement_handlers.py:2425](../../engine/phase_handlers/movement_handlers.py#L2425), `fly=True`),
  gardé par `if not _fly_single_hex` avec `_fly_single_hex = (ez <= 1 or _fly_base_size == 1)`.
- **Appel 2 — GROUND multi-hex, métrique hex** ([movement_handlers.py:2747](../../engine/phase_handlers/movement_handlers.py#L2747)),
  dans le `else` de `if _move_distance_metric == "euclidean"`.

**Conséquence vérifiée : la fonction ne sert QUE les unités multi-hex (`BASE_SIZE > 1`) avec
`ez > 1`.** Les autres pools passent ailleurs :
- **single-hex ground** (`base_size == 1` ou `ez <= 1`) → **BFS Python `deque` dédié**
  ([movement_handlers.py:~2650-2718](../../engine/phase_handlers/movement_handlers.py#L2650)),
  ce n'est PAS cette fonction ;
- **multi-hex ground euclidean** (preview escouade PvP) → `_euclidean_ground_anchor_multihex`
  ([movement_handlers.py:2733](../../engine/phase_handlers/movement_handlers.py#L2733)).

La fonction **ne sert pas** les phases charge / pile-in / consolidation, qui ont leurs propres BFS
(`CHARGE_DEST_BFS`, `FIGHT_CONSOLIDATION_BFS`, [perf_timing.py:99-122](../../engine/perf_timing.py#L99)).

> ✅ **ÉTAPE 0 FAITE (2026-07-21) — cible confirmée.** Agrégation des **374 390** lignes
> `MOVE_POOL_BUILD` de `perf_timing_bench_x5.log` (bench x5 réel sur `44x60x5`) :
> **100 % des appels sont `fly=False single_hex=False`** = **ground multi-hex** → passent tous par
> `_build_multi_hex_vectorized` (appel 2, [movement_handlers.py:2747](../../engine/phase_handlers/movement_handlers.py#L2747)).
> **Aucun** single-hex, **aucun** fly. La cible est donc unique et certaine.
> Décomposition du temps : `bfs_s` (= durée de `_build_multi_hex_vectorized` entière) =
> **4542 s / 6549 s = 69,4 %** ; `prep_s + post_bfs_s` (sets walls/occupied/enemy + footprint) =
> **30,6 %**. Socles réels (distribution exacte sur les 374 390 lignes du log) : `base=6` 45,4 %,
> `base=[20,14]` 17,7 %, `base=18` 9,5 %, `base=5` 9,4 %, `base=10` 9,3 %, `base=8` 8,7 %.
> ✅ **« base=None » ÉLUCIDÉ (2026-07-21) — faux problème.** Il n'existe **aucune** ligne `base=None`
> dans `perf_timing_bench_x5.log` (`grep -c base=None` → 0) : le socle est loggé partout. Les 17,7 %
> attribués à `base=None` sont **exactement** les socles **ovales/rectangulaires** `base=[20,14]`
> (66 164 / 374 390 = 17,7 %) — un `BASE_SIZE` **liste** rendu `[20,14]` par `perf_field`
> ([perf_timing.py:272](../../engine/perf_timing.py#L272), suppression des espaces). C'est le script
> d'agrégation de `score.json` qui a rendu la liste comme `None`, pas le moteur. **Conséquence pour
> la clé de cache** : `BASE_SIZE` peut être un **scalaire int** OU une **liste `[major, minor]`**
> (17,7 % des appels), et l'ovale n'est pas symétrique → la clé socle doit porter
> `(base_shape, base_size, orientation)` sans supposer un int (cf. §6). Ce n'est pas un socle manquant.

**Chemin chaud** (origine des 374 k appels) : `build_squad_move_cell_map`
([shared_utils.py:7711](../../engine/phase_handlers/shared_utils.py#L7711), `read_only=True`,
`out_costs`) → appelé par `build_squad_action_mask` et via
[action_decoder.py:235](../../engine/action_decoder.py#L235) → **1 appel par escouade éligible à
chaque construction de masque**, donc à chaque pas gym en phase move. Le pool raisonne sur
**l'ANCRE d'escouade**, jamais par figurine ([shared_utils.py:7715](../../engine/phase_handlers/shared_utils.py#L7715)).

---

## 3. Diagnostic chiffré (bench x5 réel du 2026-07-21)

`perf_timing_bench_x5.log.score.json` :

| Métrique | Valeur |
|---|---|
| `MOVE_POOL_BUILD` | **374 390 appels, 17,49 ms/appel, 6548,7 s / 6848,6 s instrumentés = 95,6 %** |
| dont `bfs_s` (= durée de `_build_multi_hex_vectorized` entre `_m_bfs_start`/`_m_bfs_end`) | **12,13 ms/appel = 69 % du build** |
| `CHARGE_DEST_BFS` / `CHARGE_PHASE_START` | 86,9 s / 213 s (marginaux) |

Profil cProfile (config cachée après warmup, board **60×80 SYNTHÉTIQUE**, move 12, **base 5**, ez 12,
res 5, 300 it) — ⚠️ **PAS le board de référence** : le bench x5 ci-dessus (95,6 %, 374 k) tourne sur
`44x60x5` = **220×300**, ~11× plus de cellules. Les proportions internes ci-dessous sont donc
**indicatives** et à **re-mesurer sur 220×300** (Étape 0/1) — l'allocation répétée de masques
`220×300` y pèse bien plus qu'à 60×80, ce qui **augmente** l'intérêt du cache §4.1 :

| Fonction | Part | Note |
|---|---|---|
| `_build_multi_hex_vectorized` | **~68 %** du build | le vrai goulot |
| `_dilate_by_kernel` / `_spread_by_kernel` | inclus | dilatations par slices, plusieurs/build |
| `_hex_center` + `math.sqrt` | ~10 % | 752 appels/build (footprints) |
| footprints (`_footprint_round/_square`) | faible | `precompute_footprint_offsets` déjà en place |

⚠️ **Fausse piste écartée** : la config n'est PAS le goulot (`get_game_config` cachée après warmup).

Outil : `scripts/profile_move_pool.py` **réparé** (2026-07-21), tourne à toute résolution en mode
training (`gym_training_mode=True`, `move_gym=hex`).

---

## 4. Anatomie de `_build_multi_hex_vectorized` — cachable vs mobile

Décomposition ligne à ligne (lecture du 2026-07-21). **C'est le cœur du cadrage : ce qui peut être
caché sans risque, et ce qui ne le peut pas.**

### 4.1 Invariant par (dims plateau × socle) — CACHABLE, recalculé à chaque appel

| Structure | Lignes | Dépend de | Coût |
|---|---|---|---|
| `off_even_arr` / `off_odd_arr` (reshape socle) | [1583-1584](../../engine/phase_handlers/movement_handlers.py#L1583) | forme+taille+orientation socle | alloc |
| `col_is_even` / `col_parity_mask` | [1586-1589](../../engine/phase_handlers/movement_handlers.py#L1586) | `board_cols`, `board_rows` | alloc `cols×rows` bool + copy |
| `bounds_bad` (via `_bounds_bad_parity` ×2 + `np.where`) | [1661-1682](../../engine/phase_handlers/movement_handlers.py#L1661) | (socle × dims plateau) | appelé **2-4×/build** (dans `_placement_bad`) |

Ces trois familles ne dépendent **jamais** de l'état mobile (positions, obstacles). Les cacher par
clé `(board_cols, board_rows, base_shape, base_size, orientation)` est **sûr par construction**.

### 4.2 Dépend de l'état mobile — NON cachable

| Structure | Lignes | Dépend de |
|---|---|---|
| `obstacles_dest_mask`, `obstacles_traverse_mask` (`_mask_from_cells`) | [1649-1659](../../engine/phase_handlers/movement_handlers.py#L1649) | `walls_set`, `occupied_set`, `enemy_occupied_set` |
| `hit = _dilate_by_kernel(obstacles_mask,…)` dans `_placement_bad` | [1676-1678](../../engine/phase_handlers/movement_handlers.py#L1676) | obstacles mobiles |
| `eng_bad` (engagement) | [1689-1700](../../engine/phase_handlers/movement_handlers.py#L1689) | ennemis (mobiles) |
| **la boucle BFS `deque`** | [1770-1791](../../engine/phase_handlers/movement_handlers.py#L1770) | `start_col/row` + `traverse_bad` (mobile) |
| `valid_mask`, `footprint_zone`, `out_costs` | [1793-1822](../../engine/phase_handlers/movement_handlers.py#L1793) | tout ce qui précède |

**Le BFS `deque` Python (l.1770-1791) est le poste le plus lourd du chemin ground et il n'est pas
cachable** par l'approche §0.22 : il dépend de la position de départ et des obstacles, qui changent
à chaque appel. Le cache des masques de §4.1 **n'y touche pas**.

### 4.3 Nuance « murs seuls » (compromis métier — cf. §9)

`walls_set` (terrain) est **fixe par scénario**, mais mélangé à `occupied_set` (mobile) dès
[l.1649](../../engine/phase_handlers/movement_handlers.py#L1649) (`walls_set | occupied_set`). On
**pourrait** précalculer le masque des murs seuls par plateau et ne redilater que la part mobile —
gain supplémentaire. **Mais cela suppose que les murs sont immuables pendant une partie** (pas de
terrain destructible). C'est un **compromis métier à trancher** (§9), pas une évidence de code.

---

## 5. Le second site — code de masques dupliqué

`_compute_mover_ez_forbidden_mask` ([movement_handlers.py:~1380-1520](../../engine/phase_handlers/movement_handlers.py#L1380)),
appelée depuis `_build_multi_hex_vectorized` en `ez > 1`
([l.1691](../../engine/phase_handlers/movement_handlers.py#L1691)), **re-définit localement** le
même `col_parity_mask`, `off_even_arr/odd_arr`, `_dilate_by_kernel`, `_spread_by_kernel` et les
kernels de voisinage ([l.1422-1473](../../engine/phase_handlers/movement_handlers.py#L1422)). Un
cache doit servir **les deux** via une **source unique** (sinon on optimise la moitié du chemin et
on maintient deux copies). Le reste de cette fonction (dilatation de l'empreinte ennemie) dépend
des ennemis → mobile, non cachable.

---

## 6. Clé de cache et invalidation — le risque PvP/training

- **La clé DOIT inclure les dimensions plateau ET la résolution**, pas seulement le socle.
  `board_cols`/`board_rows`/`inches_to_subhex` sont posés **une fois à l'init** du `game_state`
  ([w40k_core.py:575](../../engine/w40k_core.py#L575), [game_state.py:381](../../engine/game_state.py#L381),
  [:512](../../engine/game_state.py#L512)) et **invariants dans un run**, mais **diffèrent entre
  runs** : training `44x60x5` (**220×300**) vs autres boards (`44x60x10`, `25x21`) de dims
  différentes. Un cache de niveau processus partagé entre deux
  environnements **sans les dims dans la clé** servirait à l'un le masque de l'autre → **pool faux
  en PvP**. C'est le risque n°1.
- ✅ **Réserve levée (2026-07-21) — dims immuables prouvées sur tous les chemins.** `board_cols` /
  `board_rows` / `inches_to_subhex` sont posés **une seule fois** dans le dict `game_state`
  ([w40k_core.py:575](../../engine/w40k_core.py#L575)) et **jamais réécrits** : `grep` global des
  affectations `game_state["board_cols"/"board_rows"/"inches_to_subhex"] =` → **zéro** hors ce dict
  initial. `reset()` réutilise le **même** objet `game_state` mais son `update(...)`
  ([w40k_core.py:1002](../../engine/w40k_core.py#L1002)) ne touche pas aux dims, et `_reload_scenario`
  (rotation de scénario random) ne fait que **lire** les dims
  ([w40k_core.py:6220](../../engine/w40k_core.py#L6220), `.get()`), jamais les écrire. Un env est donc
  lié à un seul plateau pour toute sa vie. **Conséquence** : un cache **attaché au `game_state`** (portée
  ci-dessous) est sûr avec une **clé par socle seul** — les dims n'ont pas besoin d'y figurer. Les
  `(board_cols, board_rows, inches_to_subhex)` dans la clé ne restent nécessaires que pour un cache
  **partagé au niveau processus** (singleton module), où deux envs de dims différentes se croiseraient.
- **Portée du cache** : préférer un cache **attaché au `game_state`** (ou à l'env) plutôt qu'un
  singleton module global — l'isolation par run élimine par construction le risque de fuite
  PvP↔training. À défaut, clé pleinement qualifiée par les dims.
- **Invalidation** : par construction (clé complète), une entrée n'est lue que pour un
  (plateau × socle) identique. Rien à invalider en cours de partie **si** la portée §4.1 est
  respectée (aucune dépendance mobile). Si on cache aussi les murs (§4.3), il faut invalider au
  changement de terrain — d'où le compromis §9.
- 🔴 **`game_state` est RÉUTILISÉ d'un épisode à l'autre — suivre le précédent de purge existant
  (vérifié 2026-07-21).** `reset()` garde le **même objet** `game_state` et
  `_reload_scenario` en change les **murs** (le board, lui, ne change pas) ; le code y purge déjà
  explicitement `_grid_static_hex_arrays` et **`_squad_move_cell_maps`**
  ([w40k_core.py:975-980](../../engine/w40k_core.py#L975)) avec l'avertissement littéral : « une
  carte calculée sur d'**AUTRES murs** passerait le contrôle ». **Conséquence pour ce chantier :**
  un cache attaché au `game_state` **y survit entre épisodes**. Pour les invariants §4.1 c'est
  **bénin** (dims constantes → même valeur). **Mais tout cache dépendant des murs (§4.3, option B)
  DOIT être purgé dans `reset()` au même endroit que `_squad_move_cell_maps`**, sinon corruption
  **silencieuse** du pool à l'épisode suivant — c'est exactement le piège déjà traité pour le cache
  de move. **Suivre ce précédent, ne pas réinventer l'invalidation.** (`_squad_move_cell_maps` est
  d'ailleurs le cache de move existant : s'en inspirer pour la portée et la purge.)

---

## 7. Oracle & tests existants (état vérifié)

- **Pas de BFS Python de référence coexistant en production** (grep `use_vectoriz|reference_bfs|
  legacy_bfs|VECTORIZED_MOVE` → rien). Le docstring parle d'équivalence *de spécification*, pas
  d'une implémentation activable.
- **Oracle brute-force en test uniquement** : `_oracle_pool`
  ([test_movement_pool_build.py:288-387](../../tests/unit/engine/test_movement_pool_build.py#L288)),
  « BFS Python de référence, niveau par niveau ».
- ⚠️ **L'égalité STRICTE `set(pool) == _oracle_pool` n'est verrouillée que pour `ez=1` multi-hex**
  ([test_movement_pool_build.py:480](../../tests/unit/engine/test_movement_pool_build.py#L480)).
  Or la fonction ciblée ne tourne qu'en **`ez > 1`**, où les tests n'imposent que des **invariants**
  (`_assert_euclidean_pool_invariants`, [:390](../../tests/unit/engine/test_movement_pool_build.py#L390)),
  pas l'égalité exacte. **Il n'existe donc aujourd'hui aucun test d'égalité stricte sur le pool
  réellement produit en training.**
- 🔑 **Pour tester le chemin hex (`_build_multi_hex_vectorized`), le game_state doit porter
  `gym_training_mode=True`** (vérifié 2026-07-21) : `_move_distance_metric`
  ([movement_handlers.py:1878](../../engine/phase_handlers/movement_handlers.py#L1878)) lit
  `distance_metric["move_gym"]` (=`hex`) en gym, sinon `["move"]` (=`euclidean`, chemin PvP
  `_euclidean_ground_anchor_multihex`). Les `_run_pool(...)` existants **ne posent pas** ce flag →
  ils testent le chemin **euclidean**, pas la cible. C'est pourquoi le trou existe. Un test
  d'égalité stricte de la cible doit donc forcer `gym_training_mode=True`.
- ⚠️ **Limite de `_oracle_pool` : socles à `BASE_SIZE` SCALAIRE seulement.** Il fait
  `int(BASE_SIZE)` ([test_movement_pool_build.py:306](../../tests/unit/engine/test_movement_pool_build.py#L306))
  → **plante sur un socle ovale `[20,14]`** (17,7 % du training, §2). L'égalité stricte à l'oracle
  ne couvre donc PAS les ovales : ils relèvent du **test A/B cache-vs-sans-cache** (§8.1, sans
  oracle absolu) ou d'un **oracle étendu aux socles liste** à écrire si l'on veut leur égalité
  stricte. À prévoir : les ovales sont le 2ᵉ socle le plus fréquent.
- **Déterminisme** verrouillé : `test_movement_build_valid_destinations_pool_deterministic`
  ([:495](../../tests/unit/engine/test_movement_pool_build.py#L495)) — deux appels → mêmes
  ancres/zone. Utile pour un cache.
- **Modèle d'équivalence randomisée réutilisable** : `test_deployment_footprint_erosion.py` et
  `test_project_pool_to_grid_equivalence.py` comparent vectorisé vs scalaire sur échantillon
  aléatoire massif — **exactement le patron à copier pour le test A/B du cache**.
- Autres tests qui exercent le pool/masque (à faire tourner en non-régression) :
  `test_move_pool_geodesic_costs.py`, `test_squad_spatial_move_mask.py`, `test_move_resolution.py`,
  `test_move_pool_block_erosion.py`, `test_phase_transitions.py`, `test_spatial_move_decode_execute.py`.

---

## 8. Stratégie de validation (le « ne rien casser »)

1. **Test A/B cache-vs-sans-cache — le garde-fou central.** Sur un échantillon randomisé de
   (plateau × socle × positions × obstacles × ez × toggles de traversée), exiger
   `pool_cache == pool_sans_cache` **exactement** (destinations, footprint zone, `out_costs`).
   Modèle : `test_deployment_footprint_erosion.py`. Ce test ne dépend d'aucun oracle absolu et
   prouve directement l'invariance de sémantique — c'est LUI qui protège le métier.
2. **Combler le trou `ez>1`** : ajouter, tant qu'on y est, un test d'égalité stricte
   `pool == _oracle_pool` sur au moins un cas `ez>1` multi-hex représentatif du training (le pool
   qui tourne réellement n'a aujourd'hui aucun verrou d'égalité exacte, §7).
3. **Non-régression PvP** : `scripts/pvp_smoke_test.py` (déjà : pool non vide, dans le board,
   commit/preview cohérents — [pvp_smoke_test.py:329-380](../../scripts/pvp_smoke_test.py#L329)).
   ⚠️ Il ne compare pas le **contenu** du pool à un oracle : il faut le compléter d'une comparaison
   de pool avant/après sur un board de dims **différentes** du training (ex. `25x21` ou
   `44x60x10`), pour couvrir explicitement le risque de clé §6.
4. **Suite complète verte** + les tests move de §7.
5. **Re-bench** `scripts/profile_move_pool.py` avant/après : chiffrer le gain réel et vérifier
   qu'aucune régression n'est introduite ailleurs.

---

## 9. Décisions de compromis — ✅ TRANCHÉES (2026-07-21)

**(D1) Portée & cible — TRANCHÉ.** L'utilisateur : « le plus important, c'est le **x5** ; c'est pour
ce mode qu'on doit tout optimiser. Si les autres (x1 ou x10) y perdent quelque chose, c'est pas
grave. Ensuite, on peut aller jusqu'à **C**, mais s'assurer que le métier en x5 soit respecté. »
**Board de référence confirmé (correction 2026-07-21) : `config/board/44x60x5` = 220×300 subhex.**
- **Cible perf = le run x5 sur `44x60x5` (220×300)** (le mode d'entraînement dominant, celui des
  374 k appels). Toute optimisation est calibrée pour lui.
- **Portée autorisée = jusqu'à C** (cache invariants → murs → refonte BFS), menée par étapes.
- **Régression de PERF tolérée sur x1 / x10** si elle sert le x5 (ex. un cache dimensionné pour
  220×300 qui n'aide pas un autre board). ⚠️ **Régression de MÉTIER tolérée nulle part** : « pas
  grave » porte sur la **perf**, jamais sur l'exactitude du pool. Un board PvP de dims différentes
  reste un **garde-fou dur** (§8.3) — un pool faux y casserait le jeu même qu'on teste. Le métier x5
  est le critère explicite, le métier PvP en est le corollaire non négociable.

**(D2) Terrain — TRANCHÉ : IMMUABLE.** Les murs ne changent pas pendant une partie.
➜ **Option B autorisée** : le masque des murs (§4.3) peut être précalculé par plateau et **jamais
invalidé** en cours de partie. La clé de cache murs = les dims plateau + l'empreinte du terrain
(id de scénario/board suffit si le terrain est figé au déploiement).

**(D3) Dépendance externe — TRANCHÉ : `numba` / `cython` ACCEPTÉS.**
➜ **Option C ouverte** avec extension native pour le BFS `deque` (l.1770-1791), si le wavefront
NumPy pur ne suffit pas ou met en péril l'équivalence de `out_costs`. Contreparties à gérer : build,
portabilité, CI. ⚠️ Rappel du code : `scipy.ndimage` a causé des **segfaults** ici
([movement_handlers.py:1594](../../engine/phase_handlers/movement_handlers.py#L1594)) — valider
`numba`/`cython` sur l'environnement cible **avant** de s'y engager, et garder le chemin NumPy pur
comme repli testable.

**Conséquence sur le plan** : les trois étapes A → B → C sont toutes autorisées ; chacune reste
**verrouillée par le test A/B (§8.1) sur des cas x5 `44x60x5` (220×300) représentatifs** avant de
passer à la suivante, avec la non-régression PvP en garde-fou dur.

---

## 10. Plan par étapes (avancement 2026-07-21)

0. ✅ **Étape 0 FAITE** (§2) : 100 % des 374 k appels = ground multi-hex → cible = `_build_multi_
   hex_vectorized`, confirmée. `bfs_s`=69,4 %, prep+post=30,6 %.
1. ✅ **Étape 1 FAITE (socles ronds/carrés)** : le trou ez>1 est comblé. `_build_multi_hex_
   vectorized` (forcé via `gym=True` → move_gym=hex) est désormais verrouillé en **égalité stricte**
   contre `_oracle_pool` — 3 cas (base2/base3 ez10, base2+murs ez5) dans
   `tests/unit/engine/test_movement_pool_build.py::test_hex_multihex_pool_equals_oracle`, **+ garde
   d'atteinte** (`test_hex_oracle_test_actually_reaches_build_multi_hex_vectorized`) et **mutation
   confirmée** (tronquer le pool → 3 rouges, garde verte). Fichier complet vert (11 tests).
   ⏳ **Reste dans l'Étape 1** : les socles **ovales** `[20,14]` (17,7 %) — non couvrables par
   `_oracle_pool` (`int(BASE_SIZE)`), à couvrir par un **snapshot A/B** (capturer le pool ovale
   actuel avant refacto, vérifier l'invariance) au moment de l'Étape 2/3.
2-3. 🔴 **Extraction + cache des masques §4.1 : IMPLÉMENTÉS, MESURÉS INUTILES, RÉVERTÉS
   (2026-07-21).** Le cache (masques mémoïsés par `(dims × socle)` sur le `game_state`) a été
   codé, prouvé strictement équivalent (oracle + snapshot + A/B des masques, tout vert) **puis
   mesuré** :

   | Mesure (board 220×300, socle round base6) | Valeur |
   |---|---|
   | `_move_pool_static_masks` seul | **0,059 ms/appel = 1,5 %** du build (~3,8 ms) |
   | build AVEC cache vs SANS cache (60 appels) | **0,0 % de gain** (3,83 ms ≡ 3,83 ms) |

   ➜ **L'approche « cacher les masques parité/bornes » (le plan initial de §0.22) est un
   cul-de-sac** : ces masques ne pèsent que 1,5 %, et le lookup annule le gain. **Code revert**
   (`movement_handlers.py` intact) pour ne pas laisser de complexité à gain nul sur du code métier
   critique. **Acquis conservé** : les tests d'équivalence (Étape 1 + snapshot ovale) restent —
   ils verrouillent le pool hex du training, ce qu'aucun test ne faisait avant.
4. 🎯 **SEUL LEVIER RÉEL = le BFS (Option C).** Les 69 % de `bfs_s` sont la boucle `deque` Python
   (l.1770-1791) + les dilatations d'obstacles **mobiles** — rien de cachable. Réduire ce coût
   exige de réécrire le BFS lui-même : wavefront NumPy borné (risque `out_costs`) ou
   `numba`/`cython` (autorisés, D3). ⏳ **À arbitrer/lancer** : c'est un chantier à part entière.
5. ⏳ **Re-bench** après l'attaque du BFS.

Chaque étape = une passe verrouillée par test. **Jamais « optimisation + validation par un run ».**

> 📌 **Leçon (2026-07-21).** Le cadrage initial (§4.1, §9) présumait que l'allocation répétée des
> masques pesait « bien plus » sur 220×300. **La mesure l'a démenti : 1,5 %.** On a évité de livrer
> une optimisation à gain nul en **mesurant avant de conclure** (§8.5) — exactement ce que le
> chantier imposait. Le temps est ailleurs (BFS) ; y aller directement.

---

## 11. Definition of Done

- Pool **strictement identique** prouvé par test A/B (training) **et** par comparaison de contenu
  PvP (board de dims différentes, ex. 25×21 / 44x60x10) — pas seulement « non vide ».
- Trou §7 comblé : au moins un test d'égalité stricte sur un cas `ez>1` multi-hex.
- Gain `MOVE_POOL_BUILD` chiffré par re-bench avant/après, reporté ici.
- Aucune ligne de logique de pool modifiée sans test A/B la couvrant.
- `V11_agent_rework.md §0.22` mis à jour (résolu, chiffres finaux).

---

## 12. État (2026-07-21)

- ✅ **Étape 0** faite : cible confirmée (100 % ground multi-hex, §2).
- ✅ **Étape 1** faite : le pool hex du training est verrouillé — égalité stricte vs oracle (socles
  ronds/carrés) + **snapshot golden ovales** (`test_movement_pool_build.py`,
  `test_hex_multihex_pool_equals_oracle`, `test_oval_base_hex_pool_snapshot`, garde d'atteinte).
  **C'est le livrable net de cette session** : ce chemin n'avait aucun test d'égalité avant.
- 🔴 **Étapes 2-3** (extraction + cache des masques) : implémentées, prouvées équivalentes,
  **mesurées à 0 % de gain, RÉVERTÉES** (§10). `movement_handlers.py` **intact**.
- 🎯 **Reste le seul vrai levier : le BFS (Option C)** — chantier `numba`/`cython` à part entière,
  **à arbitrer/lancer** (§10 point 4). Non commencé.

`V11_agent_rework.md §0.22` pointe ici. Prochaine décision : engager (ou non) la refonte du BFS.
