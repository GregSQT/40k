# WIP — Optimisation de l’activation / initialisation déplacement (phase move)

> **Périmètre** : tout ce qui concerne l’action **`activate_unit`** en phase **move** (construction du pool de destinations valides, preview d’empreinte, masques pour l’UI) **et** le coût **HTTP** de renvoyer l’état au client après cette activation (et les **`move`** suivants).  
> **Principe** : mesurer avec `W40K_PERF_TIMING=1` (`perf_timing.log`) ; ne pas masquer les divergences de règles (`Documentation/AI_TURN.md`).

> **Statut (avril 2026)** : les optimisations **API / JSON** (étapes 0–3) et le **cache LRU** des mask loops côté moteur sont en place. La suite **perf moteur** (BFS / masque sur cas extrêmes, éventuel noyau natif) est **volontairement en pause** tant que le ressenti produit ne l’exige pas — le profilage reproductible reste disponible (**§9**, `scripts/profile_move_pool.py`). Exemple de cas limite réel : **`MOVE_POOL_BUILD`** avec **`bfs_s` ≈ 0,088 s**, **`mask_loops_s` ≈ 0,070 s**, **`MOVE=80`**, **`base=35`**, **`footprint_hex_n` ≈ 8,7k** — les deux postes sont du même ordre ; pas de levier JSON sur ces durées.

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

### 2.4 Cache LRU des boucles de masque (empreinte → polygones monde)

- **Fichier** : `engine/phase_handlers/movement_handlers.py` — fonction **`_sync_move_preview_mask_loops`**.
- **Principe** : clé **`(frozenset(footprint_zone), hex_radius, margin)`** ; jusqu’à **64** entrées (ordre LRU). Si la même union d’hex et la même géométrie plateau se représentent, on réutilise **`move_preview_footprint_mask_loops`** sans rappeler **`compute_move_preview_mask_loops_world`** (y compris lorsque le résultat est **`None`**).
- **Sémantique** : inchangée — même sortie que sans cache pour une entrée donnée.

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
- **`POST /api/game/action`** et **`POST /api/game/ai-turn`** : omission de **`objectives`** dans le JSON (`for_post_action=True`) — le client réinjecte via **`mergeGameStatePreservingOmittedObjectives`** (`frontend/src/hooks/useEngineAPI.ts`) pour ne pas perdre l’affichage plateau.
- **`activate_unit`** (move, attente joueur) : **`result`** allégé (**`valid_destinations`**, **`preview_data`**) car redondant avec **`game_state`** ; l’IA utilise un repli sur **`valid_move_destinations_pool`** si besoin.

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
| **3 — Objectifs + résultat + cache masque** | Omission **`objectives`** sur `POST` action + merge client ; slim **`result`** sur `activate_unit` ; cache LRU mask loops (§2.4) | **≈ 199 363** | **≈ 50–51 × 10³** | **≈ 0,006–0,007** | **≈ 0,001–0,002** | **≈ 0,15** | Mesure type avril 2026 (même scénario unit=3) : JSON **~×7 plus léger** sur `activate_unit` vs étape 2 ; **`response_encode_s`** ~**1 ms** sur `move`. **`engine_s`** inchangé (moteur). |

### 4.2 À mettre à jour dans ce tableau

Lors d’une nouvelle optimisation mesurable, **ajouter une ligne** (ou une colonne de version) avec : date brève, hash / PR si utile, et les mêmes champs issus d’une **reprise du scénario de référence** pour comparabilité.

### 4.3 Moteur (même scénario — ligne `MOVE_POOL_BUILD`)

Les durées **`bfs_s`**, **`mask_loops_s`**, **`total_s`** ne sont **pas** réduites par les étapes API **0–3** (hors cache mask §2.4). Exemple (étape 3, même unité lourde) : **`total_s`** ~**0,15 s** avec **`bfs_s`** ~**0,08 s** et **`mask_loops_s`** ~**0,07 s** — les deux postes restent comparables ; le prochain levier est le **profilage puis noyau natif** (voir §5 et §9), pas le JSON.

---

## 5. Pistes pour continuer (moteur — activation move)

| Piste | Description | Risque / effort |
|-------|-------------|-----------------|
| **Noyau natif BFS / pool** | Porter la boucle chaude de `movement_build_valid_destinations_pool` (Rust / Cython / C) avec structures compactes (bitsets, etc.). | **Élevé** ; tests de **parité** obligatoires (liste de destinations, règles murs / alliés / FLY). Voir `Documentation/TODO/10x_acceleration.md` §1. **Ne pas livrer** sans jeux de tests bit-à-bit sur les pools. |
| **Mémoïsation des mask loops** | **Fait (§2.4)** — cache LRU sur **`(footprint, hr, margin)`**. Extension possible : invalider explicitement au changement de tour / scénario si un jour la géométrie plateau dépend d’autres clés. | Faible si les clés restent complètes. |
| **Affiner `mask_loops_s` vs `bfs_s`** | Utiliser §9 (cProfile + **`MOVE_POOL_BUILD`**) pour décider si le prochain chantier est **`compute_move_preview_mask_loops_world`** ou le BFS / vectorisé multi-hex. | Faible risque si pas de changement sémantique. |
| **Variable `W40K_MOVE_POOL_NATIVE`** | Prévue dans la doc ×10 pour forcer le chemin Python en debug — à implémenter **en même temps** qu’un module natif optionnel (pas avant). | — |

---

## 6. Pistes pour continuer (API / client)

| Piste | Description | Risque / effort |
|-------|-------------|-----------------|
| **`objectives`** | **Fait (étape 3)** : omission sur `POST` action + **`mergeGameStatePreservingOmittedObjectives`**. Si un jour les objectifs **changent** en cours de partie côté moteur, prévoir un flag ou les renvoyer sur l’action concernée. | Évolutif. |
| **Réduire `result`** | **Fait pour `activate_unit` move (attente joueur)** : **`valid_destinations`** / **`preview_data`** retirés du `result` (pool dans **`game_state`**). Autres actions : audit au cas par cas. | — |
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
| Script profilage pool move (scénario stress + logs) | `scripts/profile_move_pool.py` |
| Preview move disque + masque (Chaikin, flou RT) | `frontend/src/components/BoardDisplay.tsx`, `frontend/src/utils/polygonSmooth.ts` |

---

## 9. Profilage ciblé `bfs_s` / `mask_loops_s` (sans changer les règles)

> Objectif : savoir **où** dépenser le CPU avant d’écrire du natif — **aucune** étape ci-dessous ne modifie le comportement du jeu.

### 9.1 Mesure wall-clock (déjà en place)

1. `export W40K_PERF_TIMING=1`
2. Rejouer le **scénario de référence** (activation unité lourde phase move).
3. Lire **`MOVE_POOL_BUILD`** dans `perf_timing.log` : comparer **`bfs_s`**, **`mask_loops_s`**, **`footprint_union_s`**, **`total_s`**.

**Reproductible sans serveur API** : depuis la racine du dépôt, avec le venv actif —

```bash
python scripts/profile_move_pool.py
python scripts/profile_move_pool.py --board-cols 96 --board-rows 60 --move 12 --base-size 3
python scripts/profile_move_pool.py --no-profile
```

Le script active **`game_state["perf_timing"]`** (et **`perf_profile`** sauf `--no-profile`), construit un plateau **multi-hex + ez>1** plus grand que les tests unitaires, puis appelle **`movement_build_valid_destinations_pool`** : les lignes **`MOVE_POOL_BUILD`** / **`PERF_PROFILE_DUMP`** sont écrites comme en jeu. Les variables d’environnement **`W40K_PERF_*`** restent prioritaires si tu les définis (chemins de log, etc.).

### 9.2 cProfile sur le build de pool uniquement

1. `export W40K_PERF_TIMING=1` et **`export W40K_PERF_PROFILE=1`** (ou `game_state["perf_profile"] = True` si le moteur est piloté par script — le script **`scripts/profile_move_pool.py`** le fait pour toi).
2. Condition : `perf_timing` déjà actif — voir `engine/perf_timing.py` (`perf_profile_enabled`).
3. Le décorateur **`@profile_move_pool_build`** sur **`movement_build_valid_destinations_pool`** écrit un dump dans **`perf_timing_profile.log`** et une ligne **`PERF_PROFILE_DUMP`** dans **`perf_timing.log`**.
4. Ouvrir le bloc **`PERF_PROFILE`** : fonctions en tête = premiers candidats optimisation **après** analyse manuelle (éviter les micro-optimisations sur du bruit).

### 9.3 py-spy (optionnel, processus vivant)

- Voir **`Documentation/TODO/ENGINE_PROFILING_OPTIMIZATION.md`** : `py-spy top` / `record` sur le PID du serveur API ou d’un worker d’entraînement.
- Utile si le coût est **mélangé** avec d’autres phases (tir, charge) dans la même requête.

### 9.4 Suite logique après profilage

1. Si **`bfs_s`** domine : suivre **`Documentation/TODO/10x_acceleration.md`** §1 (noyau natif ou Cython) **avec** tests de parité sur **`valid_move_destinations_pool`** (triés, mêmes entrées plateau).
2. Si **`mask_loops_s`** domine : profiler **`compute_move_preview_mask_loops_world`** (`engine/hex_union_boundary_polygon.py`) ; le cache LRU §2.4 a déjà supprimé les recalculs identiques — gains supplémentaires = algorithme ou portions encore en Python dans la boucle d’arêtes.
3. Ne pas activer de **fallback silencieux** entre Python et natif : échec explicite ou variable **`W40K_MOVE_POOL_NATIVE=0`** documentée quand le natif existera.

---

## 10. Bordure visuelle de la preview move (frontend)

Le rendu du **disque vert** masqué par l’union d’empreinte est dans **`frontend/src/components/BoardDisplay.tsx`**, fonction **`renderMoveAdvanceDestPoolCircleLayer`**. Chaîne actuelle (résumé) :

1. **Géométrie** : boucles **`move_preview_footprint_mask_loops`** (ou union hex côté client) → **`smoothMaskLoopsForRender`** (`frontend/src/utils/polygonSmooth.ts`) — **Chaikin** sur le contour fermé (**`MOVE_ADVANCE_MASK_POLYGON_CHAIKIN_ITERATIONS`**, aujourd’hui **2** passes).
2. **Masque** : polygone(s) lissé(s) rendu(s) dans une **RenderTexture**, puis **flou** sur le **sprite masque** — **`MOVE_ADVANCE_MASK_SPRITE_BLUR_STRENGTH`** / **`MOVE_ADVANCE_MASK_SPRITE_BLUR_QUALITY`** (le commentaire dans le code indique que le **flou** compense surtout l’**aliasage** du masque binaire en RT, pas seulement les angles du polygone).

**Pistes pour un bord encore plus « smooth »** (sans changer les règles du jeu) :

| Piste | Effet attendu | Prudence |
|-------|----------------|----------|
| **Augmenter légèrement le flou masque** (`BLUR_STRENGTH` 2 → 3 ou 4, éventuellement `BLUR_QUALITY` 2) | Bord plus doux, moins crénelé | Contour un peu plus « diffus » ; coût GPU léger |
| **Une passe Chaikin de plus** (3 au lieu de 2) | Courbes plus rondes avant rasterisation | Plafond **`MAX_VERTS_AFTER_ONE_CHAIKIN_STEP`** dans `polygonSmooth.ts` — surveiller les unions énormes |
| **Contour vectoriel multi-traits** (comme le halo charge dans le même fichier : plusieurs **`lineStyle`** de largeurs décroissantes) | Lissage visuel type « glow » sur le bord, proche du pattern déjà utilisé pour **`chargeEngagementHalo`** | Il faut dessiner le **contour** des boucles lissées (stroke), pas seulement le fill du masque — travail UI dédié |
| **RT masque à résolution plus haute** ou **MSAA** sur la RenderTexture | Moins d’escaliers sur le bord du alpha | Mémoire GPU / coût de rendu ; à valider sur grands plateaux |

**Piste à éviter pour le « smooth »** : augmenter **`Q`** ou changer la quantification côté **`compute_move_preview_mask_loops_world`** uniquement pour le look — ça touche au **moteur** et au hit-test ; préférer le **rendu** Pixi.

---

## 11. Historique (traces dans le dépôt)

| Date | Note |
|------|------|
| 2026-04-20 | Rédaction initiale : synthèse moteur (pool, mask loops NumPy), API (orjson, exclusions, perf), pistes documentées. |
| 2026-04-20 | §4 : tableau d’évolution des métriques `API_POST_ACTION` / `payload_bytes` sur scénario de référence (étapes baseline → exclusions → sans `config`). |
| 2026-04-20 | §4 étape **3** + §2.4 cache mask + §6 mises à jour ; **§9** procédure de profilage `bfs_s` / `mask_loops_s` (cProfile, py-spy, suite vers natif). |
| 2026-04-20 | **`scripts/profile_move_pool.py`** : scénario stress reproductible + **§9.1** / tableau §8. |
| 2026-04-20 | **Statut pause** perf moteur (intro) + exemple **`MOVE_POOL_BUILD`** cas limite ; **§10** bordure preview (Chaikin, flou Pixi, pistes UI). |
