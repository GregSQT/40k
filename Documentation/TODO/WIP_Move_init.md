# WIP — Optimisation de l’activation / initialisation déplacement (phase move)

> **Périmètre** : tout ce qui concerne l’action **`activate_unit`** en phase **move** (construction du pool de destinations valides, preview d’empreinte, masques pour l’UI) **et** le coût **HTTP** de renvoyer l’état au client après cette activation (et les **`move`** suivants).  
> **Principe** : mesurer avec `W40K_PERF_TIMING=1` (`perf_timing.log`) ; ne pas masquer les divergences de règles (`Documentation/AI_TURN.md`).

---

## 1. Chaîne fonctionnelle (rappel)

1. Le client envoie **`activate_unit`** sur une unité en phase move.
2. Le moteur exécute la sémantique (handlers) et, pour le déplacement, appelle typiquement **`movement_build_valid_destinations_pool`** (`engine/phase_handlers/movement_handlers.py`), qui :
   - prépare les caches (occupation, etc.) ;
   - explore les hex atteignables (**BFS** et voisinage) ;
   - construit l’union d’empreinte (**`move_preview_footprint_zone`**) et les **boucles de masque monde** (**`move_preview_footprint_mask_loops`**) pour l’aperçu plateau.
3. L’API Flask sérialise une vue allégée du **`game_state`** (`_game_state_for_json` dans `services/api_server.py`) puis encode la réponse JSON (**orjson** en priorité).

Les métriques **`engine_s`** (ligne `API_POST_ACTION`) et **`MOVE_POOL_BUILD`** décrivent surtout l’étape 2 ; **`serialize_game_state_s`**, **`response_encode_s`**, **`payload_bytes`** décrivent l’étape 3.

---

## 2. Ce qui a déjà été fait (moteur)

### 2.1 Construction du pool — instrumentation

- Ligne **`MOVE_POOL_BUILD`** dans `perf_timing.log` : découpe **`prep_s`**, **`bfs_s`**, **`post_bfs_s`**, puis **`footprint_union_s`**, **`mask_loops_s`**, **`total_s`**, compteurs **`visited`**, **`valid`**, **`anchors_n`**, **`footprint_hex_n`**, etc.
- Référence textuelle : `engine/perf_timing.py` (section lignes typiques `MOVE_POOL_BUILD`).

### 2.2 Contours de preview — vectorisation NumPy (`compute_move_preview_mask_loops_world`)

- **Fichier** : `engine/hex_union_boundary_polygon.py`.
- **Objectif** : produire **`move_preview_footprint_mask_loops`** (polygones en coordonnées monde) pour éviter d’envoyer des milliers de couples hex dans le JSON, tout en restant aligné sur le rendu plateau.
- **Optimisation** : calcul des centres hex, sommets, arêtes et quantification **vectorisés** (NumPy) ; la boucle Python restante traite les arêtes pour fusion / boucles (commentaire dans le fichier : gain sur des dizaines de milliers d’arêtes vs appels `float()` / `round()` par arête).
- **Tests** : `tests/unit/engine/test_hex_union_boundary_polygon.py`, `tests/unit/engine/test_movement_pool_build.py`.

### 2.3 Tests de non-régression sur le pool

- `movement_build_valid_destinations_pool` : scénarios figés, déterminisme, caches `enemy_adjacent_*` — voir `tests/unit/engine/test_movement_pool_build.py` et références dans ce fichier.

---

## 3. Ce qui a déjà été fait (API / JSON)

### 3.1 Encodage et perf HTTP

- **`api_json_response`** : **orjson** en priorité avec `default` pour types non natifs ; repli **`make_json_serializable`** puis **`jsonify`** si nécessaire (`services/api_server.py`).
- Ligne **`API_POST_ACTION`** : **`engine_s`**, **`serialize_game_state_s`**, **`response_encode_s`** (anciennement nommé dans l’esprit « jsonify »), **`total_wall_s`**, **`payload_bytes`**.

### 3.2 Vue `game_state` allégée (`_game_state_for_json`)

Exclusions et règles notables (non exhaustif — voir code) :

- Topologies / caches moteur lourds : `los_topology`, `pathfinding_topology`, murs, `los_cache`, pools charge avancée, etc.
- **`weapon_damage_table`** : table statique moteur ; le client web n’en a pas besoin dans chaque réponse.
- **`config`** : copie volumineuse (~1 Mo JSON) ; le client charge déjà la config via `useGameConfig` (`/config/game_config.json`, `/api/config/board`) ; `gameState.config` n’est qu’un repli optionnel dans l’UI (ex. `BoardPvp`).
- Caches par joueur : préfixes **`enemy_adjacent_hexes_player_*`**, **`enemy_adjacent_counts_player_*`** (non utilisés par le frontend repéré).
- **`units_cache`** réduit aux champs utiles au plateau : `(col, row, HP_CUR, player)`.
- Si **`move_preview_footprint_mask_loops`** est présent : suppression de **`move_preview_footprint_zone`** dans le JSON (évite la duplication masque / zone).
- Si le pool de move est non vide : suppression de **`preview_hexes`** (alias du même pool).

### 3.3 Diagnostic payload (optionnel)

- Variable **`W40K_PERF_PAYLOAD_BREAKDOWN=1`** : ligne **`API_PAYLOAD_BREAKDOWN`** (tailles par clé, alignement **`orjson_full_payload`** / **`payload_bytes`** après correction du repli `jsonify`).
- **`_api_json_body_length`** : même chaîne d’encodage que la réponse réelle (évite les `-1` fantômes sur gros objets).

---

## 4. Évolution des métriques (références `perf_timing.log`)

> **Conditions** : même scénario de jeu local (phase **move**, **tour 1**, activation d’une unité multi-hex lourde **unit=3**, puis actions **`move`**), `W40K_PERF_TIMING=1`, machine de dev (ex. WSL2). Les durées sont indicatives (bruit OS, charge).  
> **`serialize_game_state_s`** reste typiquement **&lt; 0,1 ms** sur toute la série — le goulot API est **`response_encode_s`**, proportionnel à **`payload_bytes`**, une fois le dict `game_state` filtré.

### 4.1 Tableau récapitulatif

| Étape | Changements principaux (API / JSON) | `payload_bytes` `activate_unit` (octets) | `payload_bytes` `move` (octets) | `response_encode_s` `activate_unit` (s) | `response_encode_s` `move` (s) | `engine_s` `activate_unit` (s) | Notes |
|-------|-------------------------------------|--------------------------------------------|---------------------------------|----------------------------------------|------------------------------|-------------------------------|--------|
| **0 — Baseline** | Avant réductions ciblées du `game_state` HTTP (orjson + `_game_state_for_json` déjà en place, mais payload encore maximal côté champs lourds) | **≈ 4 176 837** | **≈ 3 827 552** | **≈ 0,19–0,29** | **≈ 0,28–0,35** | **≈ 0,11–0,20** | Découverte : ~4 Mo de JSON ; `weapon_damage_table`, `config`, caches `enemy_adjacent_*_player_*` dominaient le breakdown. |
| **1 — Exclusions moteur « non UI »** | Retrait du JSON : **`weapon_damage_table`**, caches **`enemy_adjacent_hexes_player_*`** / **`enemy_adjacent_counts_player_*`** (moteur inchangé en mémoire) | **≈ 2 661 339** | **≈ 2 301 769** | **≈ 0,11–0,20** | **≈ 0,08–0,34** | **≈ 0,17–0,20** | Gros gain taille ; **`game_state.config`** restait ~**971 Ko** seul. |
| **2 — Exclusion `config`** | Retrait de **`config`** du JSON (client : `useGameConfig` + repli `gameState.config` optionnel dans `BoardPvp`) | **≈ 1 366 945** | **≈ 1 007 375** | **≈ 0,05–0,12** | **≈ 0,07–0,18** | **≈ 0,17–0,22** | **`total_wall_s`** sur `activate_unit` ~**0,27 s** vs ~**0,39 s** en baseline. Reste lourd : **`objectives`** ~160 Ko, preview move (`pool` + `mask_loops`). |

### 4.2 À mettre à jour dans ce tableau

Lors d’une nouvelle optimisation mesurable, **ajouter une ligne** (ou une colonne de version) avec : date brève, hash / PR si utile, et les mêmes champs issus d’une **reprise du scénario de référence** pour comparabilité.

### 4.3 Moteur (même scénario — ligne `MOVE_POOL_BUILD`)

Les durées **`bfs_s`**, **`mask_loops_s`**, **`total_s`** du pool varient peu entre les étapes **0–2** ci-dessus (les changements ont surtout touché l’**API**). Ordre de grandeur observé sur ce cas : **`total_s` (MOVE_POOL_BUILD)** ~**0,17–0,22 s** ; le levier principal restant est le **code natif / mémoïsation** (voir §5), pas le JSON.

---

## 5. Pistes pour continuer (moteur — activation move)

| Piste | Description | Risque / effort |
|-------|-------------|-----------------|
| **Noyau natif BFS / pool** | Porter la boucle chaude de `movement_build_valid_destinations_pool` (Rust / Cython / C) avec structures compactes (bitsets, etc.). | **Élevé** ; tests de **parité** obligatoires (liste de destinations, règles murs / alliés / FLY). Voir `Documentation/TODO/10x_acceleration.md` §1. |
| **Mémoïsation des mask loops** | Si les entrées (empreinte, plateau) sont identiques entre deux calculs, réutiliser **`move_preview_footprint_mask_loops`** avec invalidation stricte sur tout changement d’état pertinent. | **Moyen** ; bug d’invalidation = silhouette incorrecte. |
| **Affiner `mask_loops_s` vs `bfs_s`** | Lire `MOVE_POOL_BUILD` : si **`mask_loops_s`** reste du même ordre que **`bfs_s`**, poursuivre le profilage ciblé (cProfile / py-spy) sur `compute_move_preview_mask_loops_world` et la phase « union empreinte ». | Faible risque si pas de changement sémantique. |
| **Variable `W40K_MOVE_POOL_NATIVE`** | Prévue dans la doc ×10 pour forcer le chemin Python en debug — à implémenter si le natif arrive. | — |

---

## 6. Pistes pour continuer (API / client)

| Piste | Description | Risque / effort |
|-------|-------------|-----------------|
| **`objectives`** | Ne plus renvoyer à chaque **`/api/game/action`** : envoi au **`/api/game/start`** (ou cache client) + merge côté React. | **Moyen** ; reconnexion / refresh / cohérence UI. |
| **Réduire `result`** | Pour **`activate_unit`**, n’exposer que les champs réellement lus par le front (audit `useEngineAPI.ts`). | Contrat par type d’action. |
| **Preview move** | Éviter de renvoyer **`valid_move_destinations_pool`** + **`move_preview_footprint_mask_loops`** à chaque hover si le client peut réutiliser le dernier snapshot (nécessite analyse UX + état client). | Moyen. |
| **gzip / Brotli** | En production derrière un reverse proxy : moins d’octets réseau ; **ne remplace pas** la réduction CPU du JSON en localhost. | Infra ; peu d’effet en dev. |

---

## 7. Pistes hors périmètre « move init » mais liées

- **Entraînement RL** : `Documentation/TODO/ENGINE_PROFILING_OPTIMIZATION.md` — py-spy sur `W40KEngine.step()`, observations, masques ; souvent **orthogonal** à la latence Flask d’une partie web.
- **Autres phases** (tir, charge, fight) : lignes perf dédiées dans `engine/perf_timing.py` ; traiter au cas par cas.

---

## 8. Fichiers de référence rapide

| Sujet | Fichiers |
|-------|----------|
| Pool move + logs perf | `engine/phase_handlers/movement_handlers.py`, `engine/perf_timing.py` |
| Masque / boucles monde | `engine/hex_union_boundary_polygon.py` |
| API JSON + exclusions | `services/api_server.py` (`_game_state_for_json`, `_GAME_STATE_EXCLUDE_KEYS`, `api_json_response*`) |
| Stratégie ×10 (gzip, natif, payload) | `Documentation/TODO/10x_acceleration.md` |
| Profilage moteur RL | `Documentation/TODO/ENGINE_PROFILING_OPTIMIZATION.md` |

---

## 9. Historique (traces dans le dépôt)

| Date | Note |
|------|------|
| 2026-04-20 | Rédaction initiale : synthèse moteur (pool, mask loops NumPy), API (orjson, exclusions, perf), pistes documentées. |
| 2026-04-20 | §4 : tableau d’évolution des métriques `API_POST_ACTION` / `payload_bytes` sur scénario de référence (étapes baseline → exclusions → sans `config`). |
