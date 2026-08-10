# V11 §0.22 — Accélération du noyau de `_build_multi_hex_vectorized` (move pool)

> **ARCHIVÉ DANS `Implémenté/` LE 2026-08-08.** Il vivait à la racine `Implémentation/`, réservée
> aux chantiers EN COURS, alors qu'il est clos depuis le 2026-07-21. Ses trois tâches résiduelles
> (§5) restent **ouvertes et lisibles ici** — même régime que
> [`campagne_typage_et_replis_2026-07-29.md`](campagne_typage_et_replis_2026-07-29.md), archivé
> avec ses résidus nommés. État revérifié dans le code ce jour : **T1 ouvert** (aucun helper
> module-level, les 5 copies du motif slice-OR sont toujours des closures locales), **T2 ouvert**
> (`numba` toujours absent des deux `requirements*.txt` et importé nulle part), **T3 dépassé par
> §0.63/§0.64/§0.65** (cf. l'encadré de §5).

> **Chantier perf CLOS** (décision (B) STOP, utilisateur, 2026-07-21 — §3). Ce document est
> **réduit à sa valeur résiduelle le 2026-07-28** : le cadrage de leviers d'origine (~460 lignes de
> plan, tous tranchés depuis) a été supprimé. Ce qui subsiste : le périmètre de validité (§1), le
> filet de validation à respecter (§2), ce qui est livré (§3), les impasses mesurées à ne pas
> rouvrir (§4), les tâches encore ouvertes (§5), les mesures d'archive (§6).
>
> Ancres `fichier:ligne` vérifiées le **2026-07-28** ; re-grep avant d'éditer.
> Amont : [`V11_move_pool_optimization.md`](V11_move_pool_optimization.md)
> (cadrage, clos). Entrée de suivi : `V11_agent_rework.md §0.22` (barrée, résolue).

---

## 1. Périmètre de validité — À LIRE AVANT DE CITER UN CHIFFRE

Toutes les mesures de ce document ont été prises sur `config/board/44x60x5` = **220×300 subhex**,
`inches_to_subhex: 5`.

🔴 **Sur `config/board/44x60x1` (44×60, `inches_to_subhex: 1`), la fonction objet de ce document
n'est JAMAIS APPELÉE.** Démontré par le code (2026-07-28), pas estimé :

1. `_scale_socle` ([game_state.py:28-52](../../../engine/game_state.py#L28)) — **autorité unique du
   scaling `BASE_SIZE`** (commentaire d'autorité [:185](../../../engine/game_state.py#L185), appliqué
   en [:1030](../../../engine/game_state.py#L1030)) — retourne `("round", 1)` **inconditionnellement**
   dès `inches_to_subhex <= 1` : « à `inches_to_subhex == 1`, une figurine tient dans UNE case —
   c'est la définition même de cette résolution ». Donc à x1, `base_size == 1` pour **toute** figurine.
2. `is_single_hex = (ez <= 1 or base_size == 1)`
   ([movement_handlers.py:2710](../../../engine/phase_handlers/movement_handlers.py#L2710)) est donc
   toujours vrai à x1 — et doublement, puisque `engagement_zone × inches_to_subhex = 1` ⟹ `ez == 1`.
   Idem FLY : `_fly_single_hex` ([:2512](../../../engine/phase_handlers/movement_handlers.py#L2512)).
3. `_build_multi_hex_vectorized` n'est appelée que sous `not is_single_hex`
   ([:2852](../../../engine/phase_handlers/movement_handlers.py#L2852)) et `not _fly_single_hex`
   ([:2530](../../../engine/phase_handlers/movement_handlers.py#L2530)).

⟹ Le profil `x1` du curriculum (celui du run en cours, cf. `V11_agent_rework.md §0.33`) passe par le
chemin **mono-hex**. Ni les chiffres ni les leviers ci-dessous ne s'y appliquent ; ils redeviennent
pertinents dès le retour en `x5` (phase 2 du curriculum) ou en `x10`.

⚠️ **Ce qui ne dépend PAS de ce périmètre** : L1, L1b, L_neighbors et L_movecache (§3.2) portent sur
des fonctions appelées **à toutes les résolutions** ; et 3 des 5 copies du motif slice-OR (§5, T1)
vivent hors de `_build_multi_hex_vectorized`.

⚠️ **Le coût combattu ici est redevenu INCONTOURNABLE** (`V11_agent_rework.md §0.22`, MAJ 2026-07-22) :
le fix de conformité move §0.25 exige une **érosion géodésique par-figurine**, exactement le poste que
ce chantier réduisait ; il a resurgi en §0.27 (timeout d'éval d'1 h). La décision (B) n'a pas supprimé
le coût — elle a acté qu'aucun levier mesuré ne le réduisait à un ratio gain/risque acceptable.

---

## 2. Contrainte non négociable et filet de validation

**Le pool produit doit rester strictement identique, hex pour hex.** Un pool faux ne lève aucune
exception : c'est une corruption **silencieuse** de l'entraînement. Validation = équivalence A/B,
jamais « le run passe ». Une non-amélioration perf sur certains boards est tolérée ; une divergence de
pool **nulle part**.

Filet en place, à laisser vert pour toute modification du noyau :

| Verrou | Ce qu'il couvre |
|---|---|
| `test_movement_pool_build.py::test_hex_multihex_pool_equals_oracle` | égalité stricte vs `_oracle_pool`, socles ronds/carrés `ez>1`, **avec garde d'atteinte** |
| `test_movement_pool_build.py::test_oval_base_hex_pool_snapshot` | golden pool+footprint pour les ovales `[20,14]` (non couvrables par l'oracle : `int(BASE_SIZE)`) |
| `test_move_pool_geodesic_costs.py` | `out_costs` — **obligatoire** dès qu'on touche au BFS, la valeur portée EST le coût |
| A/B `_bbox_window=True` vs `False` | garde-fou permanent fenêtré == plein-board (paramètre conservé exprès) |
| `scripts/profile_move_pool.py` | re-bench avant/après (seul script de mesure survivant) |

⚠️ **`out_costs` est l'invariant le plus délicat** : c'est le coût **géodésique** (distance de chemin,
docstring [l.1598-1604](../../../engine/phase_handlers/movement_handlers.py#L1598)) qui décide normal vs
advance côté gym. Le BFS FIFO garantit que la 1ʳᵉ visite d'une case est sa distance minimale — toute
réécriture doit préserver cet ordre exact, sinon le type de move diverge silencieusement.

⚠️ **`scipy.ndimage` est interdit ici** : segfauts constatés, cf. le commentaire du code
[l.1655](../../../engine/phase_handlers/movement_handlers.py#L1655). C'est aussi la raison qui a fait
écarter `numba` (§4).

Non-régression PvP : le PvP standard prend le chemin **euclidean**
(`_euclidean_ground_anchor_multihex`, [l.2834](../../../engine/phase_handlers/movement_handlers.py#L2834)),
donc `_build_multi_hex_vectorized` est **hors** du chemin PvP par défaut — le risque PvP est
structurellement faible, mais `scripts/pvp_smoke_test.py` reste le garde-fou.

---

## 3. Ce qui est LIVRÉ

### 3.1 Build du pool (2026-07-21, commits `ff2293e0`, `6f268d38`)

- **L1 — mémoïsation de `precompute_footprint_offsets`**
  ([hex_utils.py:1376](../../../engine/hex_utils.py#L1376)) : dict module-level
  `_FOOTPRINT_OFFSETS_CACHE` clé `(base_shape, base_size normalisé tuple, orientation)`. Géométrie
  pure/déterministe, sortie immuable, aucune invalidation (contrairement aux caches dépendant des
  murs). Même pattern que `_SINGLE_BASE_HEX_COUNT_CACHE`
  ([spatial_relations.py:72](../../../engine/spatial_relations.py#L72)). Piège traité : `base_size` peut
  être une **liste** `[major, minor]` (socles ovales) — non hashable → normalisation en tuple pour la
  clé. Verrouillé par `TestPrecomputeFootprintOffsetsMemoization` (5 tests).
- **L_bbox — dilatations fenêtrées sur la bbox `move_range`** : toutes les dilatations slice-OR de
  `_build_multi_hex_vectorized` (`_dilate_by_kernel` → `bad_dest`/`bad_traverse`/`eng_bad` ez==1 ;
  `_spread_by_kernel` → footprint) sont bornées à `start ± (move_range + max|offset|)` sur le chemin
  **ground**. Helper `_ground_move_bbox_window`
  ([l.1523](../../../engine/phase_handlers/movement_handlers.py#L1523)), param additif `_bbox_window`
  ([l.1582](../../../engine/phase_handlers/movement_handlers.py#L1582)). **Variante retenue (b)** :
  tableaux plein-board conservés, seuls les **indices de slice** bornés → aucun remapping de
  coordonnées, parité `col & 1` absolue préservée, pur NumPy. **FLY exclu** (disque, étendue row
  ~1,5×move_range).
  **Preuve de correction** : pas BFS ∈ {-1,0,1}² ⇒ `reach ⊆ start ± move_range`, et les masques ne
  sont jamais **lus** hors bbox (`cd >= move_range → continue` borne les voisins testés). La bbox est
  connue *a priori* (avant le BFS) — pas de circularité avec `bad_traverse`, qui conditionne le BFS.
  **Gain (bench A/B, 220×300, gym hex)** : ovale `[20,14]` **1,49×** (15,85→10,66 ms/appel), round 10
  **1,78×**, round 3 **1,13×** — croissant avec `|offsets|`. `out_costs` invariant par construction.

### 3.2 Chemin de VALIDATION du masque (2026-07-26, commit `924c2b41`)

Chantier rouvert par un autre bout : un profil du prédicat `explain_move_plan_rejection` (4 212 appels
sur `test_move_mask_is_executable`) a montré un gisement bien plus gros que le build — **403 s sur
428**, dont **352 s de BFS géodésique** et **94,7 M appels** à `get_hex_neighbors`. Cause : le prédicat
reconstruisait à **chaque cellule candidate** des ensembles qui ne dépendent pas de la destination.

- **L_neighbors** — `get_hex_neighbors` ([combat_utils.py:145](../../../engine/combat_utils.py#L145)),
  fonction pure de deux entiers, mémoïsée dans `_HEX_NEIGHBORS_CACHE` (borné par le plateau, aucune
  invalidation). C'est la boucle interne de **tous** les BFS du moteur. Renvoie un **tuple immuable**
  et non une liste : le résultat étant partagé, une liste exposerait le cache à une mutation (55 sites
  d'appel vérifiés, aucun ne mute).
- **L1b** — `compute_occupied_hexes` ([hex_utils.py:1241](../../../engine/hex_utils.py#L1241)) **traduit**
  les offsets déjà mémoïsés au lieu de rebalayer un carré avec trigonométrie par cellule. Le balayage
  brut survit sous `_compute_occupied_hexes_raw` ([:1276](../../../engine/hex_utils.py#L1276)), appelé par
  le précalcul **et par les tests comme oracle**. ⚠️ L'oracle de la classe de test L1 a dû être
  **repointé** sur le brut — laissé sur `compute_occupied_hexes`, il serait devenu tautologique.
- **L_movecache** — `_move_spatial_cache`
  ([shared_utils.py:3485](../../../engine/phase_handlers/shared_utils.py#L3485)) mémoïse cellules
  interdites, ensemble de transit et champs géodésiques au niveau de l'**état**. Clé = **fingerprint LU
  de l'état réel** (position ET niveau de chaque figurine, phase, zones d'engagement ennemies),
  **jamais un compteur de version** : c'est exactement le piège de la régression masque⊆exécutable
  §0.18 (un chemin d'écriture qui ne bumpe pas le compteur ⟹ cache périmé servi). Effet de bord traité :
  le `deepcopy` de la preview LoS de tir partage ce cache **par référence**, sans risque puisque chaque
  lecture revalide le fingerprint.

| Test | Avant | Après | Facteur |
|---|---|---|---|
| `test_move_mask_is_executable[0]` | 687,2 s | 36,2 s | **19,0×** |
| `test_move_mask_is_executable[1]` | 542,6 s | 36,1 s | **15,0×** |
| `test_move_mask_is_executable[2]` | 526,0 s | 36,7 s | **14,3×** |
| `test_deployment_mask_mirrors_commit_overlap_predicate` | 31,0 s | 20,2 s | 1,5× |
| `test_deployment_per_model_commit` (5 tests) | ~9,7 s pièce | ~5,5 s pièce | 1,8× |

Le BFS géodésique et les empreintes étant sur le **chemin chaud du masque**, le gain porte aussi sur le
training, pas seulement sur les tests.

---

## 4. Impasses MESURÉES — ne pas rouvrir

| Piste | Verdict mesuré |
|---|---|
| Cache des masques parité/bornes (`col_parity_mask`, `bounds_bad`) | **0 % de gain** — ces masques ne pèsent que 1,5 % du build. Implémenté, prouvé équivalent, **reverté**. |
| BFS wavefront bbox-NumPy (remplacer le `deque`) | Prouvé **strictement équivalent** (reach ET dist) mais **0,46× à move_range 12** — le régime réel du gym. Ne gagne qu'à move ≥ 30 (1,05×) / 60 (1,68×). À move 12, le deque isolé ne coûte que **0,30 ms** : le BFS n'est pas le reliquat. |
| L2b décomposition en runs, par **lignes** | L'empreinte ovale **n'est pas contiguë par ligne** en coords hex offset → fallback. 0,38-0,81× sur les socles décomposables. |
| L2b décomposition en runs, par **colonnes** (sparse-table) | Équivalent, mais **1,34× ovale seulement** et **<1× sur petits socles** (round3 0,27×) car la sparse-table alloue plein-board. Apport net ≈ 1,1×. |
| Minkowski inverse sur les obstacles | `|obstacles|` réel ≈ **2400-3000** ⟹ ~5·10⁵ itérations Python, ne bat pas la bbox-NumPy. Ne gagnerait que si le set était ≪ épars. |
| Cache des murs dilatés | `_dilate_by_kernel` est O(|offsets|×surface) **indépendamment de la densité** ⟹ `dilate(occupied)` coûte autant que `dilate(walls∪occupied)` : le cache seul ne réduit pas le coût par-build. |
| numba sur la dilatation dense | N'accélère que la **constante** d'une opération déjà vectorisée C, sur une surface surdimensionnée. Rendu caduc par L_bbox. |
| numba en général | **Écarté** : dépendance + **risque de segfault** (le code a fui `scipy` pour ça, §2), non couvert par les tests → tuerait un run long. Levier de **repli** si un jour le coût redevient bloquant : à encadrer (épingler la dépendance, chemin Python conservé, A/B numba==Python). |

**Constat de fond** : sur de PETITS tableaux (bbox ~25×25), la boucle offsets de prod fait des slice-OR
**in-place sans allocation** ; toute décomposition NumPy qui alloue des temporaires part avec un
handicap d'overhead. Seul un chemin **sans allocation par offset** peut battre franchement la boucle.

**Acquis conceptuel réutilisable** : le facteur dominant était la **surface** (board vs sortie utile),
pas la constante d'un portage natif. `reach/board` ≤ 16,6 % ⟹ borner le calcul à la sortie utile bat
l'accélération de la constante. Deux implémentations existent — **(a)** test par-ancre après le BFS
(O(|reach|×|offsets|), Python, exige numba) et **(b)** dilatation bornée à la bbox (même slice-OR
vectorisé sur tableau réduit, pur NumPy, exact, inconditionnel). **(b) gagne**, et c'est ce qui a été
livré.

⚠️ Toutes ces réfutations sont mesurées sur **x5** (§1). Un changement durable de régime de board les
rendrait **à re-mesurer**, pas fausses.

---

## 5. Tâches ouvertes : AUCUNE (T1, T2 et T3 livrés le 2026-08-08)

Les trois tâches que ce §5 portait sont traitées. Ce qui suit est leur état FINAL, pas un plan.

### T1 — Mutualiser les copies du motif slice-OR. FAIT.

| # | Emplacement | Fenêtrée ? |
|---|---|---|
| 1 | `_dilate_by_kernel`/`_spread_by_kernel` de `_build_multi_hex_vectorized` [l.1648-1730](../../../engine/phase_handlers/movement_handlers.py#L1648) | ✅ param `bbox` |
| 2 | closures branche **hex** de `_compute_mover_ez_forbidden_mask` [l.1430-1466](../../../engine/phase_handlers/movement_handlers.py#L1430) | ❌ |
| 3 | inline euclidien de `_euclidean_mover_ez_forbidden_mask` [l.1361-1369](../../../engine/phase_handlers/movement_handlers.py#L1361) | ❌ |
| 4 | dilatation `ez == 1` [l.1787-1791](../../../engine/phase_handlers/movement_handlers.py#L1787) | ✅ passe `_bbox` |
| 5 | `_spread`/`_dilate` de [`fight_handlers.py:463-480`](../../../engine/phase_handlers/fight_handlers.py#L463) | ✅ **par coords locales `(c0, r0)`** |
Source unique : **`hex_utils.offset_slice_windows`**
([hex_utils.py:1329](../../../engine/hex_utils.py#L1329)). Elle rend les deux fenêtres de slice
`(source, destination)` d'un décalage de grille, `None` quand le décalage ne laisse aucune case
commune (le `continue` que chaque copie écrivait).

Convention **unique** : `src = dst + (dc, dr)`, c'est-à-dire une DILATATION. Une propagation est la
même opération avec le décalage OPPOSÉ — d'où un seul calcul pour les deux sens, au lieu des deux
jeux de bornes symétriques d'avant. Le fenêtrage est explicite : `clamp="dst"` (sortie utile connue,
L_bbox) ou `clamp="src"` (sources non nulles connues, union d'empreintes), l'autre côté étant
re-dérivé du décalage et jamais clampé lui aussi.

⚠️ **L'inventaire de 5 copies de ce document était périmé.** Relevé réel au 2026-08-08 : **six**
copies, et pas les mêmes — `fight_handlers` n'en portait plus aucune (0 occurrence), tandis que le
décodeur de déploiement en portait une que le document ignorait. Les six sites migrés :

| # | Site | Sens | Fenêtré |
|---|---|---|---|
| 1 | `_dilate_by_kernel` de `_build_multi_hex_vectorized` [movement_handlers.py:2103](../../../engine/phase_handlers/movement_handlers.py#L2103) | dilate | ✅ `clamp="dst"` |
| 2 | `_spread_by_kernel` idem [:2134](../../../engine/phase_handlers/movement_handlers.py#L2134) | spread | ✅ `clamp="src"` |
| 3 | `_dilate_by_kernel` de `_compute_mover_ez_forbidden_mask` [:1894](../../../engine/phase_handlers/movement_handlers.py#L1894) | dilate | ❌ |
| 4 | `_spread_by_kernel` idem [:1912](../../../engine/phase_handlers/movement_handlers.py#L1912) | spread | ❌ |
| 5 | inline de `_euclidean_mover_ez_forbidden_mask` [:1831](../../../engine/phase_handlers/movement_handlers.py#L1831) | dilate | ❌ |
| 6 | érosion du pool de déploiement [action_decoder.py:1506](../../../engine/action_decoder.py#L1506) | **érode (`&`)** | ❌ |

### T3 — Pôle « scoring de déploiement » : MESURÉ, ~~JAMAIS TRAITÉ~~ — **PARTIELLEMENT TRAITÉ DEPUIS, par d'autres chantiers**.

🔴 **Mise à jour du 2026-08-08 — le constat ci-dessous date du 2026-07-28 et a été dépassé sans que
ce document soit repris.** Trois chantiers d'août ont travaillé ce pôle, tous documentés dans
[`V11_agent_rework.md`](../1_Agent/V11_agent_rework.md) :
- **§0.63** (2026-08-03) : le cache de scoring **ne servait jamais** — 100 % de reconstruction.
  Corrigé (sur-ensemble stable, un cache par joueur, delta généralisé à N poses) : reconstruction
  **100 % → 20 %**, phase de déploiement **2,01 → 1,46 s**.
- **§0.64** (2026-08-03) : la LoS du scoring était une **autre implémentation** que la règle
  (607 désaccords sur 16 104 hexes) — alignée sur `compute_unit_los`, coût 1,46 → 2,85 s.
- **§0.65** (2026-08-03) : ce coût **rendu et davantage** par la vectorisation
  (`batch_hex_line_steps`, `batch_ground_hex_can_see`) : phase de déploiement **3,58 → 1,33 s**,
  part LoS **1,58 → 0,09 s**, à l'ISO-VALEUR prouvée.

Ce qui reste vrai : `_get_valid_deployment_hexes` et `_build_deployment_scoring_cache` existent
toujours (vérifié le 2026-08-08) et **aucune mesure de profil n'a été refaite depuis** — les
chiffres ci-dessous (18,8 s / 8,8 s, 835 k `score_for_hex`) sont **périmés** et ne doivent pas
servir de référence. Re-profiler avant de rouvrir quoi que ce soit ici.

Constat d'origine, conservé pour mémoire :


Après les gains §3.2, le test de déploiement le plus lourd (20,2 s) est dominé par
`_get_valid_deployment_hexes` ([action_decoder.py:1013](../../../engine/action_decoder.py#L1013), 18,8 s
cumulés / 98 appels) et `_build_deployment_scoring_cache`
([:1487](../../../engine/action_decoder.py#L1487), 8,8 s / 66 appels) — 835 k appels à `score_for_hex`,
8,4 M à `calculate_hex_distance`. **Vérifié 2026-07-28 : les deux fonctions sont inchangées, et leurs
caches internes (`_deployment_pool_cache`, `_get_or_build_deployment_scoring_cache`) datent de mai,
donc antérieurs à la mesure — ils n'y répondent pas.** ⚠️ Ce n'est **pas** une mémoïsation neutre comme
celles de §3.2 : c'est l'heuristique de déploiement de l'IA, y toucher est un changement de
comportement potentiel, à cadrer et bencher séparément. C'est le seul chiffrage de ce pôle dans toute
la documentation.
Le site 6 partage le calcul de bornes mais pas l'opérateur (érosion, pas dilatation) et travaille sur
la grille étendue `grid_cols/grid_rows`, pas sur le plateau : c'est bien le même calcul, jamais la
même opération. La copie « dilatation `ez == 1` » que le document comptait comme distincte était déjà
devenue un simple APPEL de (1).

**Verrou** : [`test_offset_slice_windows.py`](../../../tests/unit/engine/test_offset_slice_windows.py) —
équivalence exhaustive contre l'indexation naïve case par case, pour les deux sens, sur 6 formes de
grille × 81 décalages (dont ceux entièrement hors plateau), plus les deux régimes de fenêtrage
exprimés comme des égalités vérifiables (`clamp="dst"` == plein-board masqué à la fenêtre ;
`clamp="src"` == propagation d'une source effacée hors fenêtre). Verrou PROUVÉ : un `-dr` changé en
`dr` dans les bornes rend 8 tests rouges. Aucun changement de perf attendu ni mesuré : les bornes
sont le même calcul, au même endroit de la boucle.

### T2 — Statut de `numba`. TRANCHÉ : ce n'est pas une dépendance du projet.

Acté par écrit dans [`requirements.runtime.txt`](../../../requirements.runtime.txt) (le fichier de
dépendances curaté ; `requirements.txt` est un `pip freeze` de l'environnement de travail, qui
contient bien d'autres choses que ce projet). Raisons, toutes déjà mesurées en §4 : le gain visé
portait sur la **constante** d'une opération déjà vectorisée en C, il est rendu **caduc par L_bbox**
(qui attaque la surface), et une extension native non couverte par les tests fait courir un risque de
**segfault sur un run long** — la raison même pour laquelle ce code a fui `scipy.ndimage`. L'épingler
« pour garder le levier » coûterait une contrainte forte sur numpy/llvmlite au bénéfice d'un chemin de
code qui n'existe pas (0 import dans `engine/`, `ai/`). Si le besoin revient, la décision se reprend
là, avec A/B numba==Python et chemin Python conservé.

### T3 — Pôle « scoring de déploiement ». FAIT, mais pas sur la cible annoncée.

🔴 **Le chiffrage de ce document était périmé et son verdict faux.** Re-mesuré le 2026-08-08 sur le
chemin réel du gym (`W40K_BOARD_PATH=board/44x60x5`, 3 épisodes à déploiement actif, 25 steps) :

- `_build_deployment_scoring_cache` : **0,14 s / 3 appels** (le document annonçait 8,8 s / 66). Le
  poste a été absorbé par §0.46/§0.64/§0.65 (sur-ensemble stable, LoS en batch NumPy, cache disque,
  incrémental à N poses) — postérieurs à la mesure de 2026-07-28.
- `score_for_hex` : **la fonction n'existe plus** (0 occurrence dans le dépôt). `calculate_hex_distance`
  est tombée de 8,4 M appels à **2 935** (0,002 s).
- ⚠️ Le verdict « c'est l'heuristique de déploiement, y toucher change le comportement » ne
  s'appliquait donc **pas** au poste réellement coûteux.

Le poste réel était `_get_valid_deployment_hexes` (**3,10 s sur 7,19 s** de phase de déploiement), et
sa cause n'est pas l'heuristique mais du **recalcul à l'identique** : mesuré **121 appels pour 12
états distincts, soit 90,1 %**, jusqu'à 15 fois la même clé. Le masque
(`get_squad_action_mask_and_eligible_units`, 72 appels), l'observation (`deployment_slot_candidates`,
22) et le commit (`convert_squad_action`, 24) demandent le même pool pour le même état — exactement le
motif que §3.2 a traité côté move.

**Livré** : mémoïsation par fingerprint LU de l'état,
[`_deployment_valid_hexes_fingerprint`](../../../engine/action_decoder.py#L1348) →
[`_get_valid_deployment_hexes`](../../../engine/action_decoder.py#L1400), cache d'instance jeté par
`reset_episode_caches` avec le pool et les murs dont il dérive. **Aucun changement de comportement** :
le scoring, l'ordre des stratégies et les hexes rendus sont inchangés — c'est le même calcul, fait
une fois.

La clé porte l'**empreinte** de chaque voisin posé (`entry_footprint`, donc `occupied_hexes`) et pas
seulement son ancre : `_build_deployed_snapshot_version`, le tampon du cache de scoring d'à côté, ne
voit que `(player, col, row)` et servirait un pool calculé contre une autre empreinte — la régression
masque⊆exécutable §0.18, qui ne lève rien. Verrou PROUVÉ : remplacer ce hash par une constante rend
`test_changing_only_a_neighbour_footprint_invalidates_the_cache` rouge.

Elle ne porte **pas** l'identité de l'unité candidate : le calcul ne lit d'elle que
`(BASE_SHAPE, BASE_SIZE, orientation)`, et son exclusion du filtre de clairance est déjà dans la clé
via `neighbours`, énuméré avec `exclude_id=unit_id`. Deux unités hors table de même socle partagent
donc l'entrée (le roster en a trois en `round 6`), tandis qu'une unité DÉJÀ POSÉE ne partage avec
personne — elle est absente de son propre `neighbours` et présente dans celui des autres. Les deux
propriétés sont verrouillées (`..._share_the_cache_entry`, `..._does_not_share_with_an_off_table_twin`)
et PROUVÉES : remettre `unit_id` rend la première rouge, retirer l'`exclude_id` rend la seconde rouge.

Le cache est **une seule entrée** `(fingerprint, pool)`, pas un dictionnaire. Un dictionnaire retenait
toutes les poses déjà jouées jusqu'à la fin de l'épisode — mesuré ~9,4 Mo par environnement à x5
(10 entrées, 131 k couples), de l'ordre du gigaoctet à 48 envs — alors qu'une seule entrée peut encore
être servie : les trois consultations d'un step portent sur l'unité active et l'état courant, et une
pose ne se dépose pas. Mesuré : l'entrée unique **ne coûte aucun hit** (24 calculs pour 121 appels,
contre 22 pour 118 avec le dictionnaire).

**Mesure A/B, x5, 3 épisodes de déploiement actif, `cache` contre fingerprint rendu unique à chaque
appel — les deux variantes DANS LE MÊME PROCESSUS**, 3 répétitions, meilleur temps retenu :

| | sans cache | avec cache | Facteur |
|---|---|---|---|
| wall de la phase de déploiement | 6,29 s | 3,72 s | **1,69×** (−41 %) |
| calculs réels (`_deployment_clearance_filter`) | 121 | **24** | 5,0× |

⚠️ **Ne pas comparer des mesures prises à des moments différents sur cette machine** : sur du code
identique, le wall de cette même phase a varié de 5,7 s à 9,3 s selon la charge, soit plus que l'effet
qu'on cherche à mesurer. Un premier chiffrage « 7,19 → 5,67 s (1,27×) » a été produit ainsi et il est
FAUX — il comparait deux exécutions distantes. Seul l'A/B en un seul processus ci-dessus est valide.

Retiré au passage : une variable morte `ez` (avec son import) dans `_get_valid_deployment_hexes`,
résidu du prédicat `ez <= 1` remplacé par `geometry_is_hex` — un appel payé à chaque calcul de pool.

**Ce qui domine MAINTENANT la phase de déploiement** : `build_validated_deployment_plan` (2,74 s), via
`generate_compact_formation` → `_legal_socle` (49 361 appels). Mesuré **23 % de redondance seulement**
(139 appels, 107 clés distinctes) : c'est du calcul utile — un plan par ancre candidate — donc **pas**
un candidat mémoïsation. Toute reprise de ce poste devra attaquer le coût par plan, pas sa répétition.

---

## 6. Archive des mesures x5 (2026-07-21) — pour un éventuel retour en x5/x10

⚠️ Valables **uniquement** sur `44x60x5` (220×300 = 66 000 cases). Les deux scripts qui les ont
produites (`measure_move_pool_reach_obstacles.py`, `measure_move_pool_occupied.py`) ont été
**supprimés le 2026-07-26** ; seul `scripts/profile_move_pool.py` subsiste.

**Profil interne du build** (cProfile, 40 appels, MOVE 30) — le hotspot dépend du socle :

| Socle | build/appel | Postes dominants |
|---|---|---|
| rond base 6 (45 % des appels réels) | 4,8 ms | `_build…` **self** ~66 % (boucle BFS `deque` [l.1863-1884](../../../engine/phase_handlers/movement_handlers.py#L1863)) ; `_dilate` 12 % ; deque 8 % ; `_spread` 6 % |
| ovale `[20,14]` (17,7 %) | 17,6 ms | `_dilate` ~35 % ; `_build…` self ~22 % ; `_spread` ~17 % ; `precompute` non mémoïsé ~17 % |

**Cardinalités mesurées** (scénario stress ez=10) :

| Grandeur | Valeur |
|---|---|
| `\|offsets\|` | rond base6 = **19** ; ovale `[20,14]` = **187** |
| `reach / board` | MOVE 12 = **0,7 %** ; MOVE 30 = **4,2 %** ; MOVE 60 = **16,6 %** |
| `\|walls\|` (terrains training rasterisés) | 988 / 435 / 557 cellules |
| `\|occupied\|` (2 rosters training 500 pts) | **2016** cellules = 3,05 % du board ; ≈ **1800-2000** par-build |
| `move_range` réel du chemin gym hex | **12** |

**Reliquat mesuré APRÈS L_bbox** (cProfile, ez=2, move 12) — le point de reprise si le sujet rouvre :
sur l'ovale, `_dilate` **41 %** + `_spread` **19 %** du build, car le fenêtrage a réduit le travail
NumPy par slice mais **pas la boucle Python sur les ~200 offsets** (1,35 M appels à `max()`/`min()` de
bornes). Sur round 3, le hotspot est le **corps** de `_build_multi_hex_vectorized` (allocations
plein-board `col_parity_mask`/`_dist_arr`/`ravel(order='F')`/`np.where`) → le levier serait de fenêtrer
le corps lui-même (variante (a), écartée par prudence en L_bbox). À ez=10,
`_euclidean_mover_ez_forbidden_mask`
([l.1270](../../../engine/phase_handlers/movement_handlers.py#L1270)) grimpe à ~40 % pour l'ovale : le
hotspot dépend de l'ez.
