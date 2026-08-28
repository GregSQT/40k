# Perf — noyau natif BFS et compression HTTP

> **Réduction (2026-08-10) de `10x/10x_acceleration.md`**, qui portait trois axes dont deux sont
> périmés :
> - **axe 3 « réponses allégées » : FAIT**, mesuré et documenté ailleurs — voir
>   [`Documentation/Archives/chantiers/10x_Move_init.md`](../../Archives/chantiers/10x_Move_init.md) §3-4 (exclusions JSON,
>   4,1 Mo → ~0,4 Mo de payload) ;
> - **renvois morts** : `Documentation/TODO/10x_acceleration.md` et
>   `Documentation/TODO/ENGINE_PROFILING_OPTIMIZATION.md` — le dossier `Documentation/TODO/`
>   n'existe plus.
>
> Ne restent ici que les **deux axes réellement ouverts**. Le dossier `10x/` a été supprimé
> (son autre fichier, un chantier terminé, est passé en `Documentation/Archives/chantiers/`).
>
> **Principe** : mesurer avant/après (`W40K_PERF_TIMING=1`, `perf_timing.log`) ; pas de
> contournement des règles métier, pas de fallback silencieux (CLAUDE.md T1).

---

## 1. Compression HTTP (gzip + Brotli) — ✅ livré 2026-08-18, validé runtime 2026-08-18

`frontend/nginx.conf` : `gzip on`, niveau 6, seuil 1 Ko, `gzip_proxied any`, `gzip_vary on`
(Vary: Accept-Encoding — Flask-CORS + caches intermédiaires), types JSON/JS/CSS/SVG/fonts.

**Brotli** ✅ : stage `brotli-builder` dans `frontend/Dockerfile` — `apk cmake build-base`,
clone `ngx_brotli --recurse-submodules`, `cmake -S deps/brotli -B deps/brotli/out` (lib brotli
statique obligatoire avant link), `./configure --with-compat --add-dynamic-module`, `make modules` ;
`.so` copiés dans `/usr/lib/nginx/modules/` ; `load_module` injecté en tête de
`/etc/nginx/nginx.conf` (contexte main) ; directives `brotli on/static/level 6/min 1 Ko` dans
le bloc server. `text/html` absent des listes de types (nginx l'inclut par défaut — le laisser
génère un `duplicate MIME type` warn). Validé end-to-end : `nginx -t` ok + `Accept-Encoding: br`
→ `content-encoding: br` sur asset JS (`index-iqIg_nHK.js`).

---

## 2. Noyau hors Python (BFS mouvement / empreintes) — lourd, EN PAUSE

**Statut** : 🔴 **jamais commencé et déclassé.** `W40K_MOVE_POOL_NATIVE` : **0 occurrence dans le
dépôt** (vérifié 2026-08-10). Les accélérations réelles du move pool ont été menées autrement, en
Python, et sont closes : [`Documentation/Archives/chantiers/V11_move_pool_optimization.md`](../../Archives/chantiers/V11_move_pool_optimization.md),
[`Documentation/Reference/moteur/perf_move_pool.md`](../../Reference/moteur/perf_move_pool.md)
(décision **(B) STOP** du 2026-07-21, `index_v11.md` §0.22).

Chantier de plusieurs semaines, **hors chemin critique** — ne pas l'ouvrir sans un profil récent
montrant que `bfs_s` domine à nouveau.

### Objectif

Réduire le coût CPU de `movement_build_valid_destinations_pool`
(`engine/phase_handlers/movement_handlers.py`) pour les unités multi-hex à grande empreinte
(`precompute_footprint_offsets`, boucle voisins × offsets).

### Prérequis de non-régression

- **Mêmes entrées / mêmes sorties** que le Python : `valid_move_destinations_pool`, cohérence avec
  `enemy_adjacent_hexes`, murs, `enemy_occupied`, traversée alliés / fin interdite sur modèle.
- Tests de référence : scénarios figés (petit plateau + cas dread) comparant la liste **triée** de
  destinations Python vs natif.
- **Pas** de valeur par défaut masquant une divergence : échec explicite si mismatch.

### Stratégie

1. **Isoler** la logique pure derrière une signature stable :
   `(board_cols, board_rows, start, move_range, walls, enemy_occ, enemy_adj, occupied_all,
   offsets_even, offsets_odd, …) → list[tuple[int,int]]`.
2. **Portage**, par ordre : Rust (`native/move_pool/`, `pyo3`/`maturin`) ; ou Cython sur le seul
   fichier critique ; ou C + ctypes si contrainte de toolchain.
3. **Structures contiguës** (bitset par chunk, `Vec<u32>` d'indices hex) : éviter un appel Python
   par cellule visitée — c'est là que se joue le gain, un binding bavard l'annule.
4. **Chemin de debug** : `W40K_MOVE_POOL_NATIVE=0` force le Python (bisect), avec log — jamais un
   repli silencieux en production.

### Points de vigilance

- Parité colonnes paires/impaires (`offset odd-q`) : alignement strict avec `engine/hex_utils.py`
  et `precompute_footprint_offsets`.
- Unités **FLY** : branche séparée (deux chemins natifs, ou natif au sol seulement en v1).
- **Engagement** : tests contre `_enemy_adj` identiques au moteur actuel.

### Fichiers de référence

- `engine/phase_handlers/movement_handlers.py` — `movement_build_valid_destinations_pool`
- `engine/hex_utils.py` — `precompute_footprint_offsets`, `get_neighbors`
- `engine/phase_handlers/shared_utils.py` — `build_occupied_positions_set`,
  `build_enemy_occupied_positions_set`
- `engine/perf_timing.py` — `W40K_PERF_TIMING=1`, `perf_timing.log`
- Procédure de profilage réutilisable : [`Documentation/Archives/chantiers/10x_Move_init.md`](../../Archives/chantiers/10x_Move_init.md)
  (`scripts/profile_move_pool.py`)

### Validation

Égalité des pools sur N cartes × N unités en test unitaire, plus un benchmark isolant le seul
build de pool sous `W40K_PERF_TIMING=1`.

---

## 3. Voisinage

- [`perf_generate_compact_formation.md`](../../Archives/chantiers/perf_generate_compact_formation.md) — même famille
  (érosion morphologique), à mesurer avant d'implémenter.
- [`preview_tir_position_virtuelle.md`](preview_tir_position_virtuelle.md) — même objectif de
  latence perçue, côté tir (suppression du `deepcopy`).
