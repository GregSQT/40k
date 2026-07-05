# Implémentation — accélération (×10 objectif de travail)

> **Portée** : trois axes complémentaires pour réduire la latence perçue (activation mouvement, actions API, entraînement).  
> **Principe** : mesurer avant/après (`W40K_PERF_TIMING=1`, `perf_timing.log`) ; pas de contournement des règles métier (`Documentation/AI_TURN.md`, pas de fallbacks silencieux).

---

## Vue d’ensemble

| Axe | Cible principale | Effet attendu (honeste) |
|-----|------------------|-------------------------|
| **1. Noyau hors Python** | Boucle BFS + tests d’empreinte (`movement_build_valid_destinations_pool`) | Gain **variable** : fort si toute la boucle chaude est native avec structures compactes ; modéré si le binding repasse souvent en Python. |
| **2. Compression HTTP** | Octets sur le fil (gzip / Brotli) | Gain **fort** sur transfert réseau réel ; **faible ou nul** en localhost ; **ne réduit pas** le CPU `serialize` / `jsonify` mesuré côté serveur. |
| **3. Réponses HTTP allégées** | `make_json_serializable` + taille du JSON | Gain **direct** sur `serialize_game_state_s` et `response_encode_s` si moins de données à produire ; **effort d’API** (contrat frontend). |

Les trois axes **ne se substituent pas** : natif = moteur ; gzip = fil ; payload = CPU sérialisation + transfert.

---

## 1. Noyau hors Python (BFS mouvement / empreintes)

### 1.1 Objectif

Réduire le coût **CPU** de `engine/phase_handlers/movement_handlers.py` → `movement_build_valid_destinations_pool` pour unités multi-hex à grande empreinte (`precompute_footprint_offsets`, boucle sur voisins × offsets).

### 1.2 Prérequis de non-régression

- **Même entrées / mêmes sorties** que le Python : `valid_move_destinations_pool`, cohérence avec `enemy_adjacent_hexes`, murs, `enemy_occupied`, règle traversée alliés / fin interdite sur modèle.
- Tests de référence : scénarios figés (petit plateau + cas dread) comparant liste de destinations (triée) Python vs natif.
- **Pas** de valeur par défaut pour masquer une divergence : échec explicite si mismatch.

### 1.3 Stratégie d’implémentation recommandée

1. **Isoler** la logique pure dans une fonction à signature stable :  
   `(board_cols, board_rows, start, move_range, walls, enemy_occ, enemy_adj, occupied_all, offsets_even, offsets_odd, …) → list[tuple[int,int]]` (+ métadonnées pour preview si déplacées plus tard).
2. **Portage** (ordre suggéré) :
   - **Rust** (crate dans `engine/` ou `native/move_pool/`) avec `pyo3` / `maturin`, **ou**
   - **Cython** sur le fichier critique uniquement, **ou**
   - **C + ctypes** si contrainte toolchain minimale.
3. **Structures** : grilles ou ensembles **contigus** (bitset par chunk, `Vec<u32>` pour indices hex) ; éviter un appel Python par cellule visitée.
4. **Chemin de secours** : variable d’environnement `W40K_MOVE_POOL_NATIVE=0` pour forcer le Python (debug / bisect), pas un fallback silencieux en prod sans log.

### 1.4 Points de vigilance

- Parité colonnes paires / impaires (`offset odd-q`) : alignement strict avec `engine/hex_utils.py` et `precompute_footprint_offsets`.
- Unités **FLY** : branche séparée ; soit deux chemins natifs, soit natif uniquement pour le sol au premier incrément.
- **Engagement** : tests contre `_enemy_adj` identiques au moteur actuel.

### 1.5 Fichiers de référence

- `engine/phase_handlers/movement_handlers.py` — `movement_build_valid_destinations_pool`
- `engine/hex_utils.py` — `precompute_footprint_offsets`, `get_neighbors`
- `engine/phase_handlers/shared_utils.py` — `build_occupied_positions_set`, `build_enemy_occupied_positions_set`

### 1.6 Validation

- Tests unitaires : égalité des pools sur N cartes / N unités.
- Benchmark : `pytest` + script mesurant uniquement le build de pool avec `W40K_PERF_TIMING=1`.

---

## 2. Compression HTTP (gzip / Brotli)

### 2.1 Objectif

Réduire le **volume** des réponses JSON et, surtout en conditions réelles (latence réseau), le **temps de transfert** ; améliorer le parse côté navigateur si payload plus petit après décompression.

### 2.2 Ce que ça ne fait pas

- **Ne diminue pas** significativement `serialize_game_state_s` ni la construction de l’arbre Python avant encodage JSON (sauf si la stack compresse en streaming de manière à éviter de matérialiser tout le JSON en clair — rare en Flask simple).
- En **localhost**, le gain peut être **nul** ; le coût CPU de compression peut même **ajouter** quelques ms.

### 2.3 Implémentation recommandée

**Option A — Reverse proxy (production)**  
Nginx / Caddy / Traefik : `gzip on` ; `gzip_types application/json` ; pour Brotli, module `brotli` ou CDN.

**Option B — Flask / Werkzeug**  
Middleware ou `after_request` qui compresse le body si `Accept-Encoding: gzip` et taille > seuil (ex. 1 Ko). Vérifier la compatibilité avec Flask-CORS (headers `Vary: Accept-Encoding`).

**Option C — Client**  
`Accept-Encoding: gzip, br` déjà souvent envoyé par les navigateurs ; le serveur doit **annoncer** et **compresser**.

### 2.4 Mesure

- DevTools réseau : taille « transférée » vs « ressource ».
- Comparer latence totale requête sur **réseau throttlé** vs localhost.

### 2.5 Fichiers de référence

- `services/api_server.py` — routes `/api/game/action`, `/api/game/start`

---

## 3. Réponses HTTP allégées (game_state ciblé)

### 3.1 Objectif

Réduire **directement** le temps passé dans `make_json_serializable(_game_state_for_json(engine))` et la charge mémoire en ne sérialisant **que** ce dont le client a besoin pour l’action courante.

### 3.2 Analyse préalable

- Lister les champs consommés par le frontend après **chaque** type d’action (`activate_unit`, `move`, `left_click`, tir, etc.) — `frontend/src/hooks/useEngineAPI.ts`, composants plateau.
- Identifier les **gros blobs** serveur-only : caches LoS globaux, données d’observation RL, logs volumineux, duplications.

### 3.3 Stratégies (par ordre de risque croissant)

| Stratégie | Description | Risque |
|-----------|-------------|--------|
| **Exclusion par liste** | `_game_state_for_json` accepte `exclude_keys: frozenset[str]` ou mode `action_name` → ensemble de clés à omettre | Oublier un champ → bug UI |
| **Vue « delta »** | Réponse = `{ result, patches: { path, value } }` + client merge | Contrat complexe, tests E2E |
| **Deux endpoints** | `GET /api/game/state?scope=minimal` après action minimale | Double round-trip si mal utilisé |

### 3.4 Règles projet

- Utiliser `require_key` / pas de masquage d’erreur : si le frontend **exige** un champ, il doit être présent ou le contrat doit être explicite.
- Documenter la liste des champs par action dans ce fichier ou `Documentation/AI_IMPLEMENTATION.md` une fois stabilisée.

### 3.5 Fichiers de référence

- `services/api_server.py` — `make_json_serializable`, `_game_state_for_json`
- Frontend : consommation de `game_state` après `executeAction`

### 3.6 Validation

- Tests d’intégration API : chaque action critique avec payload réduit → même comportement UI (ou tests automatisés Playwright si disponibles).

---

## 4. Ordre de mise en œuvre suggéré

1. **Mesure de base** : conserver `perf_timing.log` + une ligne de référence (scénario PvP test, unité lourde).
2. **Compression** : faible risque en prod derrière proxy ; mesurer taille et latence réseau.
3. **Payload** : audit des champs + première exclusion des blobs évidents (caches non utilisés par le board).
4. **Noyau natif** : après gel de la sémantique BFS, avec tests bit-à-bit sur les pools.

---

## 5. Références croisées

- `engine/perf_timing.py` — activation `W40K_PERF_TIMING=1`, fichier `perf_timing.log`
- `Documentation/TODO/ENGINE_PROFILING_OPTIMIZATION.md` — py-spy / cProfile côté entraînement
- `Documentation/AI_TURN.md` — règles de phase mouvement
- `.cursor/rules/ai_turn_compliance.mdc` — contraintes handlers

---

## 6. Historique

| Date | Auteur | Note |
|------|--------|------|
| 2026-04-16 | — | Création : trois axes (natif, gzip, payload) avec critères d’honnêteté sur les gains. |
