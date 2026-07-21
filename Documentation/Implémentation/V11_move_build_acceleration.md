# V11 — Accélération du noyau de `_build_multi_hex_vectorized` (move pool)

> **Chantier moteur / perf — implémentation de l'« Option C » de `V11_move_pool_optimization.md`.**
> Objet : réduire le coût de `MOVE_POOL_BUILD` (95,6 % du temps d'un run x5) **sans jamais altérer
> le pool produit** (destinations, footprint zone, `out_costs`) ni le comportement PvP.
>
> ⚠️ **Le titre historique était « BFS_numba ». La mesure l'a démenti : le BFS `deque` n'est PAS
> l'unique goulot.** Ce document part des **profils réels** (2026-07-21, board de référence
> `config/board/44x60x5` = 220×300 subhex) et décrit l'implémentation de CHAQUE hotspot, pas d'une
> hypothèse. Toutes les ancres `fichier:ligne` sont vérifiées ; re-grep avant d'éditer.

Date : 2026-07-21. Décisions amont (`V11_move_pool_optimization.md §9`) : cible = x5 220×300 ;
portée jusqu'à C ; terrain immuable ; `numba`/`cython` autorisés.

---

## 0. Ce qui est DÉJÀ acquis / réfuté (ne pas refaire)

- ✅ **Filet d'équivalence en place** (`tests/unit/engine/test_movement_pool_build.py`) :
  `test_hex_multihex_pool_equals_oracle` (égalité stricte pool hex/gym vs `_oracle_pool`, socles
  ronds/carrés ez>1, **avec garde d'atteinte**) et `test_oval_base_hex_pool_snapshot` (golden
  pool+footprint pour les ovales `[20,14]`). **Tout portage ci-dessous doit les laisser verts.**
- 🔴 **Cache des masques parité/bornes (`col_parity_mask`, `bounds_bad`) : RÉFUTÉ par mesure**
  (0 % de gain ; les masques = 1,5 % du temps). Ne pas y revenir. Détail :
  `V11_move_pool_optimization.md §10`.
- 🎯 **Principe « calculer sur la sortie utile, pas sur le board » = levier transverse prioritaire
  (§6bis).** Vérifié 2026-07-21 : tout tourne en plein plateau 220×300 alors que `reach` est borné
  par `move_range`. Ce facteur **surface** (pur NumPy) prime sur le facteur **constant** de numba
  (L2/L3) — d'où l'ordre révisé §8. Chiffrage `|reach|`/board et sûreté `eng_bad` : cf. §6bis.

---

## 1. Contrainte NON négociable (rappel)

Le pool produit après optimisation doit être **strictement identique**, hex pour hex. Un pool faux
ne lève aucune exception (corruption **silencieuse** de l'entraînement). Validation = équivalence
A/B (oracle + snapshot + comparaison avant/après), jamais « le run passe ». La cible perf est le x5
220×300 ; une non-amélioration sur d'autres boards est tolérée, une divergence de pool **nulle
part**.

---

## 2. Profil interne MESURÉ — le hotspot dépend du socle

cProfile de `_build_multi_hex_vectorized`, 220×300, 40 appels, tri `tottime` (2026-07-21). Deux
socles représentatifs des 374 k appels réels (base=6 : 45 % ; ovale `[20,14]` : 17,7 %) :

**Socle rond base 6, MOVE 30 — build ≈ 4,8 ms/appel :**

| Poste | tottime | Part | Nature |
|---|---|---|---|
| `_build_multi_hex_vectorized` **self** | 0,128 | **~66 %** | boucle BFS `deque` (l.1770-1791) + code inline |
| `_dilate_by_kernel` | 0,023 | 12 % | dilatation morpho. par footprint |
| deque `append`+`popleft` | 0,015 | 8 % | file BFS |
| `_spread_by_kernel` | 0,012 | 6 % | union d'empreintes |

**Socle ovale `[20,14]`, MOVE 30 — build ≈ 17,6 ms/appel (≈ le 17,49 ms du bench x5 réel) :**

| Poste | tottime | Part | Nature |
|---|---|---|---|
| `_dilate_by_kernel` | 0,244 | **~35 %** | dilatation par un GROS footprint |
| `_build_multi_hex_vectorized` **self** | 0,152 | ~22 % | boucle BFS + inline |
| `_spread_by_kernel` | 0,121 | ~17 % | union d'empreintes |
| `_footprint_oval`+`_hex_center`+`max`+`sqrt` | ~0,12 | ~17 % | `precompute_footprint_offsets` **non mémoïsé** |

**Lecture.** Petit socle → la **boucle deque** domine. Gros socle → les **dilatations
morphologiques** (`_dilate_by_kernel` + `_spread_by_kernel`, ~52 %) dominent, plus le **recalcul de
footprint** (~17 %). Les gros socles étant aussi les plus lents en valeur absolue (17,6 vs 4,8 ms),
ils pèsent lourd dans les 374 k appels. **Il faut donc traiter les trois : footprint, dilatations,
BFS.**

---

## 2bis. Mesures de cardinalités (2026-07-21) — ce qui tranche les leviers

Mesuré via capture des kwargs réels de `_build_multi_hex_vectorized`
([scripts/measure_move_pool_reach_obstacles.py](../../scripts/measure_move_pool_reach_obstacles.py),
`|reach|` recalculé par BFS fidèle sur `compute_footprint_placement_mask`, prouvé équivalent à
`_placement_bad` ; `|occupied|` par
[scripts/measure_move_pool_occupied.py](../../scripts/measure_move_pool_occupied.py) depuis les
rosters training). **Reproductibles pour le re-bench avant/après (§8 étape 3).** Board 220×300 =
**66 000 cases**, scénario stress ez=10.

| Grandeur | Valeur mesurée |
|---|---|
| `\|offsets\|` (footprint) | rond base6 = **19** ; ovale `[20,14]` = **187** |
| `reach / board` | MOVE 12 = **0,7 %** ; MOVE 30 = **4,2 %** ; MOVE 60 = **16,6 %** |
| `\|walls\|` **réel** (terrains training rasterisés) | terrain-train-01 = **988** ; -02 = **435** ; -03 = **557** cellules |
| `\|occupied\|` **réel** (2 rosters training 500 pts, ~45 modèles, socles scalés `round(bs×5/10)`) | **2016** cellules total board = **3,05 %** ; par-build (mover exclu) ≈ **1800-2000** |

**Faits établis :**
1. **`reach` est toujours ≪ board** (0,7 % → 16,6 % selon MOVE) : les masques sont dilatés sur 66 k
   cases mais consommés sur ≤ 1/6 du plateau. C'est le facteur **surface** (§6bis), robuste car
   quasi indépendant des obstacles (les murs ne font que rétrécir `reach`).
2. **`|walls|` réel = quelques centaines** (435-988), ni 0 ni des milliers ; **`|occupied|` réel ≈ 1900**
   par-build (mesuré). Donc `|obstacles|` réel ≈ **2400-3000** cellules.

**⚠️ Point critique découvert à la mesure — `_dilate_by_kernel` est O(|offsets|×board) INDÉPENDAMMENT
du nombre de cellules à `True` dans `src`** (il boucle sur les offsets, chacun un OR de slice plein
plateau). Conséquences qui corrigent les leviers §4 :
- Le **cache-murs (L1bis) SEUL ne réduit PAS le coût par-build** : `dilate(occupied)` coûte autant que
  `dilate(walls∪occupied)`. Son seul gain = supprimer la **double dilatation des murs** (dest+traverse)
  et la re-dilatation inter-builds. Pour exploiter la rareté du set dynamique il faut dilater
  `occupied` en **Minkowski** (O(|occupied|×|offsets|)), pas en `_dilate`.
- **Minkowski en Python pur ne gagne que si le set opérant est épars** : `|walls|≈700` rend le
  Minkowski complet marginal en Python (≈|obst|×|off| itérations interprétées vs dilatation NumPy
  vectorisée C). Le vrai candidat Python-pur = **cache-murs (statique, amorti) + Minkowski sur le seul
  `occupied`** (~centaines).
- **La restriction-à-reach a DEUX implémentations — une seule exige numba (corrigé 2026-07-21)** :
  **(a)** le test d'empreinte **par-ancre** en Python (|reach|×|offsets| ≈ 5·10⁵ pour l'ovale) perd
  contre la dilatation vectorisée → exige numba ; **(b)** la **dilatation bornée à la bbox `move_range`**
  est le MÊME slice-OR vectorisé (`_dilate_by_kernel`, [l.1600-1613](../../engine/phase_handlers/movement_handlers.py#L1600))
  sur un tableau réduit au lieu du plein board → **pur NumPy, exact, inconditionnel, aucune dépendance**.
  (b) est la bonne forme (bbox connue *a priori*, cf. §8) : elle capte le facteur surface sans numba.
- **L2 (numba sur la dilatation dense) est le levier le plus FAIBLE** : il n'accélère que la constante
  d'une opération déjà vectorisée C, sur une surface (board) surdimensionnée vs `reach`.

**VERDICT (toutes cardinalités mesurées 2026-07-21).** `|obstacles_dest|` réel = `|walls|` (435-988)
+ `|occupied|` (~1900) ≈ **2400-3000 cellules**. Comparé aux op-counts (ovale, `|off|`=187,
board=66 k, `reach`@MOVE30=2791) :

| Candidat placement-bad | Op-count | Nature | Verdict |
|---|---|---|---|
| dilate dense **actuel** | `|off|`×board = 1,2·10⁷ | NumPy vectorisé C | surdimensionné (surface board) |
| **dilate bornée bbox `move_range`** | `|off|`×bbox ≈ 187×~3,7k = 7·10⁵ | **NumPy vectorisé C** | ✅ **GAGNANT : ~18× moins, pur NumPy, inconditionnel, exact, 0 dépendance** |
| Minkowski | `|obst|`×`|off|` = 2500×187 = 4,7·10⁵ | Python interprété | marginal : à `|obst|`≈2500 les ~5·10⁵ itérations Python ≈ / > bbox-NumPy. Ne gagne en Python pur que si `|obst|` ≪ (réfuté ici) |
| test-par-ancre-sur-reach | `|reach|`×`|off|` = 2791×187 = 5,2·10⁵ | Python (numba requis) | équivalent à Minkowski en op-count ; exige numba pour battre bbox-NumPy |

**Conclusion : la dilatation bornée à la bbox `move_range` (facteur surface, pur NumPy, sans numba)
est le levier optimal pour le placement-bad — elle rend caducs à la fois L2-numba-dense ET la
sur-ingénierie Minkowski/reach.** `|occupied|`≈1900 et `|walls|`≈700 confirment que le set d'obstacles
n'est PAS assez épars pour que Minkowski-Python gagne. Le seul poste où numba reste incontournable est
le **BFS L3** (66 % des petits socles, seule boucle réellement interprétée par cellule).

---

## 3. Levier L1 — Mémoïser `precompute_footprint_offsets` (sûr, ~10 %, à faire en premier)

**Constat.** `precompute_footprint_offsets` ([hex_utils.py:1274](../../engine/hex_utils.py#L1274))
recalcule `compute_occupied_hexes` → `_footprint_oval`/`_footprint_round`
([hex_utils.py:1307-1324](../../engine/hex_utils.py#L1307)) à **chaque** appel, alors qu'elle ne
dépend que de `(base_shape, base_size, orientation)` — **immuable**. Elle est appelée plusieurs
fois par build (mover + chaque ennemi, dans `_euclidean_mover_ez_forbidden_mask`
[l.1345/1358](../../engine/phase_handlers/movement_handlers.py#L1345) et en amont du pool), et
`_footprint_oval` fait une double boucle avec `_hex_center` (≈ 1226 appels/footprint mesurés).

**Mesure du gain (2026-07-21, ovale 220×300)** : **14,92 ms → 13,37 ms (~10 %)**, sans changer le
résultat. Sûr et local.

**Portée réelle sous-estimée (vérifié 2026-07-21, décompte corrigé).** `precompute_footprint_offsets`
est appelée depuis **~5 modules prod hors du move** (`action_decoder`, `deployment`, `charge`,
`fight`, `spatial_relations`) — grep. ⚠️ `shooting` **n'appelle PAS** `precompute` (0 occurrence, il
passe par `compute_occupied_hexes`) : ne pas le compter. Un cache **niveau module** les accélère TOUS,
pas seulement le
+10 % ovale du move. Précédent déjà en place : `_single_base_hex_count`
([spatial_relations.py:75](../../engine/spatial_relations.py#L75)) mémoïse déjà le *count* d'un socle
par `(shape, size, orientation, parity)` ; L1 étend le **même pattern** aux *offsets*. Le gain L1 est
donc plus large que la seule mesure move ci-dessus.

**Implémentation.**
- Envelopper dans un `functools.lru_cache`. **Piège vérifié** : `base_size` peut être une **liste**
  `[major, minor]` (17,7 % des cas, socles ovales) — **non hashable**. Il faut un wrapper qui
  normalise `base_size` en `tuple` pour la clé, et le repasse tel quel au corps.
- `orientation` par défaut `0` : garder la signature. `maxsize=None` (nombre de socles distincts
  borné : quelques dizaines).
- **Portée** : cache de niveau module (immuable, aucune dépendance à l'état/plateau) — pas besoin de
  purge au `reset()`, contrairement aux caches dépendant des murs.
- **Implémentation cohérente repo** : préférer un **dict-module** (`{clé: offsets}` avec
  `tuple(base_size)` en clé) au `functools.lru_cache`, pour coller au pattern maison déjà en place
  (`_SINGLE_BASE_HEX_COUNT_CACHE`, [spatial_relations.py:72](../../engine/spatial_relations.py#L72)).
  Même effet, style homogène.

**Équivalence.** Aucune : la valeur retournée est identique, seul le recalcul disparaît. Tests
existants (oracle + snapshot) suffisent ; ajouter un test que deux appels retournent des offsets
égaux (déjà garanti) et un micro-test que le wrapper accepte `base_size` liste ET int.

**Risque** : quasi nul. `compute_occupied_hexes` est pur (aucun effet de bord observé — à
re-confirmer par lecture avant d'implémenter).

---

## 4. Levier L2 — Porter `_dilate_by_kernel` / `_spread_by_kernel` en `numba` (gros gain sur socles larges)

**Le hotspot n°1 des gros socles** (35 % + 17 % = 52 % du build ovale). Les deux fonctions sont des
closures internes de `_build_multi_hex_vectorized`
([l.1591-1637](../../engine/phase_handlers/movement_handlers.py#L1591)).

**Ce qu'elles font (vérifié).**
- `_dilate_by_kernel(src, kernel)` : `out[c,r] = OR_{(dc,dr)∈kernel} src[c+dc, r+dr]`. Boucle Python
  sur les `|kernel|` offsets, chacun un OR de slices NumPy bornées. Coût ∝ `|kernel| × board`.
  `|kernel|` = taille du footprint (ovale `[20,14]` ≈ plusieurs centaines).
- `_spread_by_kernel(src, kernel)` : symétrique (`out[c+dc, r+dr] |= src[c,r]`), pour la propagation
  et l'union d'empreintes.

**Pourquoi c'est lent en Python** : la boucle `for dc, dr in kernel` est interprétée ; pour un gros
footprint, des centaines d'itérations, chacune allouant/indexant des slices.

**⚠️ Décision préalable — le placement-bad a une alternative de MEILLEURE complexité déjà présente
(vérifié 2026-07-21).** Il faut distinguer les deux usages de `_dilate_by_kernel`/`_spread_by_kernel` :

- **`_dilate_by_kernel` sur les OBSTACLES** (`_placement_bad`, appelé 4×/build : dest+traverse × 2
  parités, [l.1675-1687](../../engine/phase_handlers/movement_handlers.py#L1675)) — c'est l'essentiel
  des 35 % de l'ovale (le profil est en `engagement=euclidean`, donc la branche `ez==1` n'est pas
  prise). Or il existe **déjà dans le même module** une fonction équivalente **non branchée** :
  `compute_footprint_placement_mask`
  ([hex_utils.py:1209](../../engine/hex_utils.py#L1209), **0 caller en production** — grep : seuls 2
  fichiers de test l'utilisent). Elle calcule **le même** masque par **Minkowski inverse** en
  **O(|obstacles| × |offsets|)** au lieu de l'**O(|offsets| × board)** de la dilatation. Équivalence
  démontrée ligne à ligne : ancre bad ⟺ `∃ offset : anchor+offset ∈ obstacles` (dilate : `nc=fc-dc`
  ⟹ `fc=nc+dc`), même dispatch de parité, mêmes bornes.
  - **Ce qui tranche = `|obstacles|`, jamais mesuré par ce plan.** La dilatation NumPy actuelle n'est
    PAS naïve (boucle board vectorisée en C, seules ~|offsets| itérations Python) ; et
    `compute_footprint_placement_mask` est aujourd'hui en **Python pur** O(|obstacles|×|offsets|),
    donc plus lente si `|obstacles|` est grand. Le gain n'existe que si on **numba-ise Minkowski** ET
    que `|obstacles| < board` (66 000 cellules). **Bonus Minkowski** : il prend le *set* d'obstacles
    directement, donc évite aussi le `_mask_from_cells` (scatter NumPy,
    [l.1650](../../engine/phase_handlers/movement_handlers.py#L1650)) que la voie dilate paie en amont.
    Sur le board de ref, `occupied_set` (footprints des
    unités) + `walls_set` est vraisemblablement de l'ordre de quelques centaines à quelques milliers
    → Minkowski numba gagnerait ~10-30×, mais **ce n'est validé que par une mesure de `|obstacles|`
    à faire AVANT de coder**.
  - **Candidat Python-pur supplémentaire — décomposition statique/dynamique des murs (vérifié
    2026-07-21).** `_placement_bad` dilate `walls|occupied` pour `bad_dest`
    ([l.1684](../../engine/phase_handlers/movement_handlers.py#L1684)) ET `walls|enemy/friendly` pour
    `bad_traverse` ([l.1687](../../engine/phase_handlers/movement_handlers.py#L1687)) : les **murs sont
    dilatés 2× par build**, et re-dilatés à chaque build alors que **`walls_set` est immuable**
    (terrain immuable, passé en paramètre). La dilatation **distribue sur l'union**
    (`dilate(walls∪occ) = dilate(walls) ∪ dilate(occ)`), donc : **cacher `dilate(walls, offsets)` par
    `(shape, size, orient, board)`** (même espace de clés borné que L1) puis ne faire par-build qu'une
    dilatation/Minkowski sur le **petit set dynamique** `occupied` (~centaines de cellules). Supprime
    la dilatation lourde des murs **sans numba, sans risque**. Gain ∝ `|walls|` → à mesurer avec
    `|obstacles|`. C'est un **4ᵉ candidat** pour le même bench, potentiellement le plus rentable si les
    murs dominent.
  - **Action L2 (obstacles)** : instrumenter `|walls|`, `|occupied|`, `|obstacles_dest|`,
    `|obstacles_traverse|` ET `|reach|` (cf. §6bis) sur le bench ovale, puis benchmarker les candidats
    — dilate dense (numba) / Minkowski (numba) / cache-murs+dynamique (Python) / test-par-ancre-sur-reach
    — et retenir le gagnant. Ne PAS numba-iser la dilatation dense sans cette mesure : ce serait
    accélérer la constante d'une complexité que le repo sait déjà réduire, potentiellement en Python pur.
- **`_spread_by_kernel` sur `valid_mask`** (union footprint_zone,
  [l.1807-1811](../../engine/phase_handlers/movement_handlers.py#L1807)) : source **dense** (≈ disque
  atteignable, des milliers de cellules) → Minkowski inverse n'aide PAS ici. **⚠️ numba n'y est PAS
  automatiquement gagnant** : `_spread` a la structure **identique** à `_dilate` (slice-OR déjà
  vectorisée C, [l.1616-1637](../../engine/phase_handlers/movement_handlers.py#L1616)) ; numba ne
  retire que le surcoût d'interprétation des ~|offsets| itérations, PAS le OR mémoire (débit C déjà).
  Le gain y est donc **aussi non prouvé et doit être benché à l'identique** — l'affirmer sans mesure =
  l'hypothèse que ce plan bannit. Idem dilatation `ez==1`.

**Portage `numba` proposé** (à n'appliquer qu'aux briques où le bench prouve le gain — cf. §8 : le
seul poste où numba gagne *structurellement* est le BFS L3, seule boucle réellement interprétée
par cellule ; sur les dilatations/spread vectorisées le gain est marginal et conditionnel).
- Sortir les deux fonctions au **niveau module** (elles capturent seulement `board_cols`,
  `board_rows` → les passer en arguments), décorées `@njit(cache=True)`.
- Signatures : `src: bool[:, :]` (ou `uint8[:, :]`), `kernel: int64[:, :]` (le `off_*_arr` déjà
  `reshape(-1,2)`), `board_cols/board_rows: int64`. Retour `bool[:, :]`.
- Corps : **boucle explicite** `for k in range(kernel.shape[0]): dc=kernel[k,0]; dr=kernel[k,1]; …`
  avec les mêmes bornes de slice que l'actuel (recopier **exactement** le calcul de
  `c_src_lo/hi`, `r_src_lo/hi`, décalage `-dc/-dr`). numba compile la double boucle
  cellule-par-cellule efficacement ; garder la logique de bornes **à l'identique** est l'invariant.
- ⚠️ Le commentaire du code interdit `scipy.ndimage` (segfaults constatés,
  [l.1594](../../engine/phase_handlers/movement_handlers.py#L1594)). numba est une compilation JIT
  locale, pas une extension C tierce — mais **valider sur l'environnement cible** (WSL2 + venv)
  qu'il n'y a ni segfault ni divergence numérique.

**Équivalence** : exacte (opérations entières/booléennes, aucune arithmétique flottante). Test A/B :
comparer `_dilate_by_kernel_numba(src, kernel)` au `_dilate_by_kernel` Python actuel sur un
échantillon randomisé de `(src, kernel)` — **modèle exact** de `test_deployment_footprint_erosion.py`
(déjà un test d'équivalence vectorisé-vs-scalaire randomisé massif).

**Risque** : moyen. Premier compile numba = latence de warmup (amortie sur 374 k appels). Types
d'entrée à figer (dtype des masques). Garder le chemin Python comme repli testable.

---

## 5. Levier L3 — Porter la boucle BFS `deque` en `numba` (gros gain sur socles petits)

**Le hotspot n°1 des petits socles** (66 % du build rond). Boucle
[l.1770-1791](../../engine/phase_handlers/movement_handlers.py#L1770) :

```
_bfs_queue = deque([(start_col, start_row, 0)])
while _bfs_queue:
    cc, cr, cd = popleft()
    if cd >= move_range: continue
    nb_t = _nb_even_t if (cc & 1)==0 else _nb_odd_t   # 6 voisins hex par parité
    for dc, dr in nb_t:
        nc, nr = cc+dc, cr+dr
        if hors bornes: continue
        _vidx = nc + nr*board_cols
        if _vis_bfs[_vidx]: continue
        if _tb_flat[_vidx]: continue                  # traverse_bad (obstacle)
        _vis_bfs[_vidx]=1; reach[nc,nr]=True
        if _dist_arr is not None: _dist_arr[nc,nr]=nd  # coût géodésique (out_costs)
        append((nc,nr,nd))
```

**Portage `numba` proposé.**
- Fonction module `@njit(cache=True)` recevant : `start_col, start_row, move_range, board_cols,
  board_rows` (int64), `traverse_bad: bool[:, :]` (au lieu du `bytearray _tb_flat` — numba préfère
  un ndarray), et un flag `want_costs: bool`. Retourne `reach: bool[:, :]` et `dist: float64[:, :]`
  (rempli à `-1` si `want_costs` faux, ou un tableau vide).
- **File** : numba ne supporte pas `collections.deque`. La remplacer par un **anneau/array
  préalloué** de taille `board_cols*board_rows` (borne dure du nombre de cellules visitables) avec
  indices `head`/`tail` — FIFO strict (invariant : la 1ʳᵉ visite = distance minimale, ne PAS casser
  l'ordre BFS niveau par niveau, sinon `out_costs` diverge).
- **Voisinages** : `_nb_even_t`/`_nb_odd_t` (l.1767-1768) en `int64[6,2]` constants numba.
- **`visited`** : un `bool[:, :]` (ou `uint8`) au lieu du `bytearray`.

**⚠️ Invariant critique — `out_costs`.** `_dist_arr` est le coût **géodésique** (distance de chemin)
qui détermine normal vs advance (docstring l.1550-1555). Le BFS FIFO garantit que la 1ʳᵉ visite
d'une case EST sa distance minimale. **Toute réécriture doit préserver cet ordre FIFO exact**, sinon
les coûts changent et le type de move (donc le comportement gym) diverge silencieusement. C'est le
point le plus délicat du portage.

**Équivalence** : exacte (entiers). Test : le pool ET les `out_costs` doivent être identiques.
`test_move_pool_geodesic_costs.py` verrouille déjà les coûts — l'étendre à un cas gym/hex ez>1 (via
`gym=True`, cf. §7 du doc de cadrage) est **obligatoire** ici, car la valeur portée EST le coût.

**Risque** : élevé (c'est le cœur sémantique). À faire en dernier, une fois L1/L2 validés.

---

## 6. Un 4ᵉ poste à instruire — `_euclidean_mover_ez_forbidden_mask`

Sur l'ovale, `_hex_center` (196 k appels/40 builds) et `max`/`sqrt` pèsent ~17 %. Une part vient de
`precompute` (traité en L1) ; le reste est dans `_euclidean_mover_ez_forbidden_mask`
([l.1270](../../engine/phase_handlers/movement_handlers.py#L1270)) — déjà partiellement vectorisé
(`_stamp_disc`), mais la boucle `for dc, dr in offs` de dilatation finale
([l.1361-1369](../../engine/phase_handlers/movement_handlers.py#L1361)) est une copie du
motif de `_dilate_by_kernel`. **Décompte corrigé (vérifié 2026-07-21) : il y a 4 copies du motif, pas
3** — (1) closures de `_build_multi_hex_vectorized` [l.1591-1637](../../engine/phase_handlers/movement_handlers.py#L1591) ;
(2) closures de la branche **hex** de `_compute_mover_ez_forbidden_mask`
[l.1430-1466](../../engine/phase_handlers/movement_handlers.py#L1430) ; (3) inline euclidien
[l.1361-1369](../../engine/phase_handlers/movement_handlers.py#L1361) ; (4) dilatation `ez==1`
[l.1696-1697](../../engine/phase_handlers/movement_handlers.py#L1696). La branche hex (2) est HORS du
chemin euclidien profilé (`engagement=hex` seulement) donc non urgente, mais un « noyau numba unique »
(DoD §8) doit **toutes** les absorber pour ne pas laisser de copie divergente. **À mutualiser avec L2**
plutôt que d'optimiser à part. ⚠️ Cette fonction n'est atteinte qu'en `engagement=euclidean` (le défaut) et `ez>1` — le
mesurer sur un cas sans ennemi proche donnerait 0, d'où l'importance de profiler avec ennemis à
portée (fait ici).

---

## 6bis. Principe transverse — calculer les masques sur la SORTIE UTILE, pas sur le board (vérifié 2026-07-21)

Généralisation du levier Minkowski (§4) que le doc n'appliquait qu'aux obstacles. Les trois masques
sont **dilatés sur 66 k cases** mais **consommés sur ~|reach|** (disque atteignable, ~quelques
milliers) :

- `bad_dest` + `eng_bad` : lus uniquement en `reach & ~bad_dest & ~eng_bad`
  ([l.1743](../../engine/phase_handlers/movement_handlers.py#L1743) fly /
  [l.1793](../../engine/phase_handlers/movement_handlers.py#L1793) ground). Optimum =
  **tester l'empreinte seulement sur les ancres de `reach`, après le BFS** → O(|reach|×|offsets|),
  borné par la sortie utile, pas par le board. Subsume dilate ET Minkowski pour ces deux masques.
- `bad_traverse` : ⚠️ **piège apparent** — il ne se restreint PAS à `reach` car il **conditionne** le
  BFS ([l.1785](../../engine/phase_handlers/movement_handlers.py#L1785) lit `_tb_flat`) : `reach` est
  *défini par* lui (circularité). **Résolu sans BFS-fold par la bbox (préféré, cf. §8)** : la bbox
  `move_range` est un sur-ensemble de `reach` **connu a priori** (avant le BFS, via
  `get_squad_move_budget`) → dilater `bad_traverse` sur la bbox est exact pour toutes les cases que le
  BFS peut visiter, en NumPy vectorisé, sans passer chaque pas en O(|offsets|). (Le pli-dans-le-BFS
  reste une option, mais socle-dépendante — cf. caveat ci-dessous.)
- `footprint_zone` (`_spread` de `valid_mask`, [l.1809](../../engine/phase_handlers/movement_handlers.py#L1809)) :
  kernel contient l'origine ⟹ `footprint_zone = valid_mask ∪ dilate(∂valid_mask)`. Ne dilater que la
  **bande frontière** donne le même résultat. Gain net pour petit footprint, modeste pour gros (bande
  épaisse).

**Estimation a-priori de `|reach|` vs board (arithmétique, vérifiée 2026-07-21).** `move_range` =
`MOVE` en subhex (`config["MOVE"] × inches_to_subhex`,
[shared_utils.py:3854](../../engine/phase_handlers/shared_utils.py#L3854)) ; à res 5, MOVE 6" = 30
subhex, advance ≤ +30, unité rapide ≤ ~90. Disque atteignable / plateau : move normal r≈30 → ~7 %
(~14× moins de cellules) ; advance r≈60 → ~27 % ; rapide r≈90 → ~60 %. Confirme `|reach| ≪ board`
pour le move commun (gros gain), modeste pour les mobiles rapides — **la distribution réelle de
`move_range` sur les 374 k appels reste à mesurer** (étape 3 §8).

**Sûreté `eng_bad` restreint à reach (vérifiée 2026-07-21).** Les ennemis sont déjà pré-filtrés à
`MOVE + r_m + r_e + ez + 1` de `start` par `_enemy_items_within_move_engagement_horizon`
([l.207](../../engine/phase_handlers/movement_handlers.py#L207)), et chaque disque `_stamp_disc` est
déjà bbox-borné ([l.1312](../../engine/phase_handlers/movement_handlers.py#L1312)) → aucun ennemi
pertinent hors de la fenêtre atteignable. Restreindre le test d'engagement à `reach` est exact.

**⚠️ Le caveat socle-dépendant ne vise QUE le pli-dans-le-BFS / le test par-ancre (variante (a) §8),
PAS la dilatation-bbox (variante (b), pur NumPy, inconditionnelle).** Plier l'empreinte dans le BFS
fait passer chaque pas de O(1) à O(|offsets|) : gain sur l'**ovale** (|offsets|≈187, dilatation = 52 %),
mais **surcoût** sur le **base6** (|offsets|≈19, BFS déjà à 66 % et O(1)/case) — le cœur que L3 veut
accélérer. Ce compromis n'existe **pas** pour la bbox (b), qui garde le O(1)/case du BFS et ne fait
que rétrécir le tableau des dilatations. **Action : appliquer d'abord la bbox (b) — gain sûr sans
arbitrage — puis instrumenter `|occupied|` (§2bis) avant tout numba, la bbox rendant L2 (numba-dilate
dense) très probablement caduc.**

---

## 7. Stratégie de validation (identique pour chaque levier)

1. **Test A/B de la brique** portée (numba vs Python) sur échantillon randomisé — modèle
   `test_deployment_footprint_erosion.py` / `test_project_pool_to_grid_equivalence.py`.
2. **Oracle + snapshot** (`test_movement_pool_build.py`) restent verts → le pool complet est
   inchangé (ronds/carrés + ovales).
3. **`test_move_pool_geodesic_costs.py`** étendu à un cas gym/hex → les `out_costs` inchangés
   (obligatoire pour L3).
4. **Suite move complète** verte (les 6 fichiers listés dans `V11_move_pool_optimization.md §7`).
5. **Re-bench** `scripts/profile_move_pool.py` (réparé) avant/après, sur ronds ET ovales →
   consigner le gain réel dans ce document.
6. **Non-régression PvP** : le PvP standard prend le chemin **euclidean**
   (`_euclidean_ground_anchor_multihex`), donc `_build_multi_hex_vectorized` est **hors** du chemin
   PvP par défaut — le risque PvP est structurellement faible. Néanmoins passer `pvp_smoke_test.py`
   après L2 (les dilatations sont partagées avec des chemins voisins).

---

## 8. Ordre recommandé & Definition of Done

**⚠️ Le facteur dominant est la SURFACE (board vs `reach`), pas la constante numba (mesuré §2bis).**
`_dilate_by_kernel` est O(|offsets|×board) **indépendant de la densité** ([l.1600-1613](../../engine/phase_handlers/movement_handlers.py#L1600)),
et `reach`/board ≤ 16,6 % (0,7 % en MOVE 12). Borner **toutes** les dilatations/spread/stamp à la
bbox `move_range` divise le board par ~6-100× selon MOVE, en **NumPy pur vectorisé, sans dépendance**.
C'est le plus gros gain sûr et il **précède tout numba**. Corollaire : L2 (numba-dilate dense) devient
quasi caduc ; le seul poste que la bbox ne réduit pas est la **boucle BFS `deque`** (déjà O(reach)),
d'où le débat wavefront-NumPy-vs-numba (étape 4).

**Distinction clé (corrige §2bis/§6bis).** « Restreindre à `reach` » a **deux** implémentations :
**(a)** test d'empreinte **par-ancre** après le BFS — O(|reach|×|offsets|) en Python → perd vs
dilatation vectorisée, exige numba ; **(b)** **dilatation bornée à la bbox `move_range`** — même
slice-OR vectorisé sur un tableau réduit → **pur NumPy, exact, inconditionnel**. La bbox est connue
*a priori* (`start ± (move_range + max|offset| + 1)`, via `get_squad_move_budget`, **avant** le BFS)
→ pas de circularité, ce qui règle aussi le piège `bad_traverse` du §6bis. (b) subsume `bad_dest`,
`bad_traverse`, `eng_bad` ET le `_spread` footprint. Variante mini-risque : garder les tableaux
plein-board (alloc = 1,5 %) et **borner les indices de slice** de `_dilate`/`_spread`/`_stamp` à la
bbox — zéro remapping de coordonnées, parité `col & 1` absolue préservée.

**Ordre (du plus sûr/rentable au plus délicat) :**
1. **L1** — mémoïser `precompute_footprint_offsets` (~10 % ovale + ~5 modules hors-move, risque quasi
   nul, Python pur). Livrable immédiat, indépendant du reste.
2. **L_bbox — fenêtrer toutes les dilatations/spread/stamp sur la bbox `move_range`** (variante (b)).
   **Pur NumPy, exact, inconditionnel — le plus gros gain sûr** (facteur surface, mesuré : 0,7-16,6 %
   du board réellement consommé). Couvre `bad_dest`, `bad_traverse`, `eng_bad`, footprint d'un coup ;
   aucune dépendance, aucun BFS-fold, aucun test par-ancre. Verrouillé par l'A/B (§7).
3. **Re-bench** après L1+L_bbox (`|occupied|` **déjà mesuré** : ~1900/build, §2bis — plus un inconnu).
   Vérifier que le gain surface se matérialise et qu'aucun reliquat de dilatation ne subsiste.
4. **BFS (petits socles, 66 %)** — seul poste que la bbox ne réduit pas (déjà O(reach)). **Bencher
   d'abord un wavefront bbox-NumPy** (move_range itérations de dilatation de frontière sur la bbox ;
   `out_costs` = n° d'itération, obtenu gratuitement) **vs** le portage `deque`→`numba` (array-queue
   FIFO). Par cohérence avec le principe « NumPy pur avant numba », le wavefront se teste **avant**
   d'ajouter numba ; numba seulement s'il gagne au bench. `out_costs` (ordre FIFO / niveau) =
   l'invariant critique des deux formes.
5. **cache-murs / Minkowski-occupied / L2 numba-dense** — **caducs** : `|obstacles|`≈2400-3000 mesuré
   (§2bis) → Minkowski (Python, `|obst|`×`|off|` ≈ 5·10⁵ itérations interprétées) ne bat PAS la
   bbox-NumPy ; le cache-murs seul ne réduit pas le coût par-build (`_dilate` density-independent). Ne
   ré-ouvrir QUE si l'étape 3 exhibe un reliquat inattendu. Décision tranchée par mesure, pas différée.
6. **Copies dupliquées du motif dilate (§6)** — mutualiser les **copies vivantes (1)(3)** dans un
   **helper Python partagé** ; ne PAS porter en numba les copies **(2) hex** et **(4) ez==1** si elles
   sont hors config atteinte (`engagement=euclidean` + `ez>1` — **à confirmer par board avant tout
   travail**). Un helper pur-Python unique évite la divergence sans ajouter de risque numba sur du
   code jamais exécuté.

**DoD :** oracle + snapshot + `out_costs` + suite move + `pvp_smoke` verts ; gain re-benché et
reporté ici (ronds ET ovales) ; `numba` validé sans segfault sur l'environnement cible, chemin
Python conservé comme repli ; `V11_move_pool_optimization.md §10` et `V11_agent_rework.md §0.22`
mis à jour avec les chiffres finaux.

**Estimation d'enveloppe (mesurée, indicative)** : L1 ≈ −10 % (ovale, **et gain non chiffré sur ~5
modules hors-move** action_decoder/deployment/charge/fight) ; **L_bbox** vise les ~50 % de dilatations
sur socles larges en **Python pur** (facteur surface board→bbox, mesuré 0,7-16,6 % consommé → ~6-100×
selon MOVE) — sans dépendance ; l'attaque du BFS (~66 % sur socles petits) vise le reliquat non réduit
par la bbox, wavefront-NumPy ou numba selon bench. Un run x5 étant à 95,6 % dans ce noyau, un facteur
2-4 sur le noyau réduit le temps de run d'autant — c'est l'enjeu (training réel 10-30k épisodes,
~36 h aujourd'hui).

---

## 9. Risques transverses `numba`

- **Build/portabilité** : première compilation JIT (warmup) ; `cache=True` persiste le binaire.
  Valider sur WSL2 + le venv du projet. **État réel (vérifié 2026-07-21)** : `numba 0.65.1` est **déjà
  installé dans le venv** (`import numba` OK sous `.venv`) mais **absent de `requirements.txt` /
  `requirements.runtime.txt`** → l'**épingler** dans les requirements (reproductibilité), ce n'est PAS
  une compilation native à installer.
- **Types** : figer les dtypes des masques (`bool` vs `uint8`) — une incohérence de type fait
  recompiler ou lever. Convertir explicitement aux frontières.
- **Repli** : garder les implémentations Python (renommées) et un flag/try-import, pour diagnostic
  et pour les environnements sans numba. Un test doit vérifier que repli Python et numba donnent le
  **même** résultat (c'est le test A/B).
- **`out_costs` (L3)** : le seul endroit à arithmétique de distance — préserver l'ordre FIFO.

---

## 10. État

**L1 FAIT (2026-07-21).** `precompute_footprint_offsets` ([hex_utils.py:1274](../../engine/hex_utils.py#L1274))
est mémoïsée par un dict module-level `_FOOTPRINT_OFFSETS_CACHE` clé `(base_shape, base_size normalisé
tuple, orientation)` : géométrie pure/déterministe, sortie immuable, aucune invalidation. Verrouillée par
`TestPrecomputeFootprintOffsetsMemoization` (5 tests : équivalence stricte vs oracle géométrique sur
round/oval/square × orientations, hit de cache = même objet, clé list≡tuple, non-collision, erreur
préservée à travers le cache). Non-régression : `test_hex_utils` (103) + `test_movement_pool_build` +
`test_deployment_footprint_erosion` + balayage move/charge/fight/deploy/action_decoder/spatial (475)
verts. Gain non re-benché isolément (le DoD re-benche après L1+L_bbox, étape 3). **Reste : L_bbox.**

**L_bbox FAIT (2026-07-21).** Toutes les dilatations slice-OR de `_build_multi_hex_vectorized`
(`_dilate_by_kernel` → `bad_dest`/`bad_traverse`/`eng_bad` ez==1 ; `_spread_by_kernel` → footprint)
sont fenêtrées sur la bbox `start ± (move_range + max|offset|)` du chemin **ground** (variante (b) :
tableaux plein-board conservés, seuls les indices de slice bornés → parité `col&1` absolue préservée,
pur NumPy). FLY exclu (disque, étendue row ~1,5×move_range). Fenêtre calculée par le helper
module-level `_ground_move_bbox_window` ; param additif `_bbox_window=True` (False = plein-board pour
l'A/B). **Preuve de correction** : pas BFS ∈ {-1,0,1}² ⇒ `reach ⊆ start ± move_range`, et
`bad_*`/`eng_bad`/footprint ne sont jamais **lus** hors bbox (`cd >= move_range → continue` borne les
voisins testés). **Garde-fous verts** : oracle ground (ez 1/5/10, round/square/walls) + snapshot ovale
MOVE 12 (pool+footprint hash inchangés) + **A/B fenêtré==plein-board** sur 7 cas (round/square/oval ×
orientations/walls/ez/edge-clamp, pool ET footprint strictement égaux) + garde de narrowing du helper ;
suite complète verte (exit 0). `out_costs` invariant par construction (rempli par le BFS, non fenêtré).
**Gain mesuré (bench A/B, board 220×300 res 5, gym hex)** : ovale [20,14] **1,49×** (15,85→10,66 ms/appel),
round 10 **1,78×**, round 3 **1,13×** — gain croissant avec |offsets| (les gros socles, dont l'ovale =
17,7% du training, portent le coût). Reliquat sur petits socles = le BFS `deque` (étape 4). **Reste :
BFS wavefront/numba (étape 4).**

**Étape 4 (BFS) — NON COMMENCÉE (code).** Cadrage d'implémentation basé sur profils réels + **cardinalités mesurées**
(2026-07-21, §2bis). `movement_handlers.py` et `hex_utils.py` **intacts**. Filet de tests d'équivalence
déjà en place (§0). Acquis de la mesure : `reach`/board ≤ 16,6 %, `|walls|` réel ≈ 435-988,
`_dilate` O(|offsets|×board) indépendant de la densité → L2-dense = levier le plus faible ; le facteur
surface (reach) domine et se capte en **NumPy pur** par la **dilatation-bbox `move_range`** (variante
(b) §8), **sans numba** — numba n'est en jeu que pour le reliquat BFS des petits socles, et seulement
si un wavefront bbox-NumPy ne suffit pas. **`|occupied|` désormais MESURÉ** (~1900/build, 2 rosters
training §2bis) → `|obstacles|`≈2400-3000 → Minkowski/cache-murs/L2-numba-dense **caducs** (pas assez
épars pour battre la bbox-NumPy). **Aucun inconnu bloquant restant.** ~~Prochaine action code : L1
(mémoïsation, indépendante) puis L_bbox (pur NumPy, gain surface).~~ **L1 + L_bbox faits le 2026-07-21
(cf. début de §10 ; gain ovale 1,49×, round10 1,78×, pool strictement identique). Prochaine action code :
étape 4 — BFS wavefront bbox-NumPy vs numba (reliquat sur petits socles).**
