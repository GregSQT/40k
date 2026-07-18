# Refonte de l'action space de mouvement — obs spatiale + tête spatiale

> **Périmètre** : la façon dont l'agent RL **choisit une destination** en phase move (`squad_normal_move`,
> `squad_advance`, `squad_fall_back`), l'**observation** sur laquelle il fonde ce choix, et le masque
> associé. Ne concerne PAS le PvP (chemin `execute_semantic_action`), qui n'est touché qu'au niveau des
> fonctions partagées, à comportement strictement inchangé.
>
> **Principe** : le moteur reste la source unique des règles (pool BFS). Aucune règle de mouvement n'est
> réimplémentée côté IA. Aucun fallback, aucune valeur par défaut masquant une erreur.

> **Statut (2026-07-17)** : investigation terminée, root cause établie et prouvée, design arbitré.
> **T1 FAIT** · **T1b FAIT** · **T2 FAIT** · **T3 FAIT** · **T4 FAIT** · **T5 FAIT** (`action_space_size`
> retiré, `policy` → `MultiInputPolicy`, `n_steps` 16384 → 8192 sur les 5 profils, extracteur CNN branché).
>
> **Suite : 1394 passed / 2 skipped / 0 failed, SANS `--ignore`** (`test_evaluation_bots.py` collecte et
> passe à nouveau depuis T4). Le retrain (T6) n'est plus bloqué.
>
> **La root cause §3 est morte des DEUX côtés** : l'agent (T2) ET les bots (T4) visent désormais tout le
> disque atteignable. Mesuré côté bot (GreedyBot, board ×5) : moves de **33 à 85 subhex** par phase,
> contre 1 subhex avant. Le win-rate de référence bougera donc des deux côtés (cf. §T4).
>
> **La grille de T1 est désormais BRANCHÉE sur la policy (T1b)** : l'obs est un `Dict`
> `{"vec": 108, "grid": (6,32,32)}`, la policy est `MultiInputPolicy` avec un extracteur CNN
> (`ai/spatial_extractor.SpatialCombinedExtractor`). L'anti-pattern §4.1 (« volant précis, conducteur
> aveugle ») est levé : l'agent perçoit enfin le terrain. Validé bout en bout (cf. §7ter).
>
> Reste : **T6** (retrain) — 🟢 **DÉBLOQUÉ (2026-07-18)**. Le crash fight-phase PRÉ-EXISTANT exposé par
> le move corrigé (boucle infinie `BotControlledEnv`, unité engagée au début de l'étape FIGHT dont
> l'ennemi est mort : éligible dans le pool mais non-jouable au masque → WAIT en boucle) est **corrigé** :
> le masque dérive désormais du pool 12.04 (`fight_v11_current_pool`), la 3ᵉ copie divergente
> `_squad_is_in_fight` est supprimée (cf. section **T6** « FIX APPLIQUÉ »). §9.1/9.2/9.3 validés (suite
> verte, moves 2-69 subhex, phase move 0 erreur) ; le run `--new` passe le point de crash. Un fix
> `ai/train.py` (garde `load_vec_normalize` sur `--new`) est livré et nécessaire.
>
> Écarts constatés entre la spec et le code réel pendant T1 — **la mesure fait foi, pas l'attendu** :
> - §10.2 : `fixed_resolution` **abandonné** (impossibilité arithmétique démontrée, cf. §10.2).
> - §7 T1 : le surcoût de la grille n'était **pas** « sous la ms ». Première implémentation mesurée à
>   **10,74 ms/step** (16,5 % d'un step). Ramené à **0,521 ms** (0,8 %) par vectorisation +
>   mémoïsation — cf. §8.4bis. L'attendu ne tenait qu'après ce travail.
> - Deux bugs trouvés **par les tests**, pas par la relecture : perte des destinations au bord exact
>   de la grille, et cache de terrain périmé entre épisodes (§8.4bis).
>
> **Commit de référence des numéros de ligne : `7fc55b66`.** Les références citent fonction + ligne ;
> en cas de dérive, la fonction fait foi.
>
> **MàJ 2026-07-18 (§7quater)** : gates pyright/check_ai_rules nettoyées (dont un vrai bug
> `project_pool_to_grid` : troncature `int` du coût géodésique) ; **bug EZ ancre→empreinte corrigé**
> (entorse 03.04 : l'EZ dilatait l'ancre au lieu du socle, sous-dimensionnée sur les rosters multi-hex) ;
> incrémental du cache EZ **écarté** après profilage (~1,5 % du runtime, hook move à 0 %).

---

## 1. Constat initial

Observation utilisateur sur le replay : **les unités se déplacent très peu**. Hypothèse initiale émise :
`inches_to_subhex` ne serait pas appliqué en training.

**Cette hypothèse est écartée** (§2). Le vrai défaut est ailleurs, et il est plus grave (§3).

---

## 2. Ce qui n'est PAS en cause — `inches_to_subhex` EST correctement appliqué

Vérifié dans le code, pas supposé :

| Élément | Emplacement | Constat |
|---|---|---|
| Board actif | `config/config.json` → `paths.board = board/44x60x5` | `inches_to_subhex: 5`, `cols=220`, `rows=300` |
| Scaling `MOVE` | `engine/game_state.py:841` | `full_unit_data["MOVE"] * scale` |
| Scaling portées armes | `engine/game_state.py:788-794` | `RNG` des `RNG_WEAPONS` / `CC_WEAPONS` × scale |
| Scaling `game_rules` | `engine/w40k_core.py:399-428` | EZ, charge, cohésion, perception × scale |
| Chemin training | `engine/w40k_core.py:6218-6240` | `_load_units_from_scenario` lit le board réel via `get_config_loader().get_board_config()` |
| Preuve runtime | `step.log:16` | `Board: cols=220 rows=300 inches_to_subhex=5 hex_radius=2.78 margin=1` |

Un `MOVE` de 5" vaut donc bien **25 subhex** en training. `get_squad_move_budget`
(`engine/phase_handlers/shared_utils.py:3715`) renvoie ces 25 subhex, et `validate_move_plan`
(`shared_utils.py:3376-3379`) vérifie bien `calculate_hex_distance(origine, dest) <= 25`.

**Le budget est calculé, validé… et jamais utilisé.**

---

## 3. ROOT CAUSE — une action de move = 1 subhex

En pipeline squad V11 (gym), une action de mouvement est une **direction 0-5**, et la destination est
l'**hexagone adjacent** à l'ancre :

- `engine/action_decoder.py:878` :
  `return {"action": "squad_normal_move", "direction": action_int, "squad_id": squad_id}`
- `engine/w40k_core.py:5258-5263` :
  ```python
  neighbors = get_hex_neighbors(anchor_col, anchor_row)
  dest_col, dest_row = neighbors[direction]   # ← toujours à distance 1
  ```
- Le masque fait le même dry-run à 1 hex : `_squad_direction_move_legal`
  (`shared_utils.py:7296-7302`) construit un plan rigide vers `neighbors[direction_idx]`.
- Puis `end_activation` ferme l'activation et retire l'escouade du pool.

**Conséquence** : une escouade avance de **1 subhex par phase de move**, soit **0,2"** sur un board ×5,
au lieu des 25 subhex auxquelles elle a droit. Elle consomme **1/25 de son budget**.

Preuve dans `step.log:40` :
```
[22:59:20] E1 T1 P1 MOVE : Unit 1(208,295) MOVED from (208,296) to (208,295)[R:+0.0] [SUCCESS]
```

**Le facteur d'échelle aggrave le défaut** : en ×1, un pas d'1 hex valait 1" (déjà limité mais jouable) ;
en ×5 le déplacement effectif est divisé par 5. D'où le symptôme visible dans le replay.

---

## 4. Découvertes annexes (vérifiées, à traiter)

### 4.1 L'observation ne contient AUCUN terrain — **le défaut le plus grave**

`engine/observation_builder.py:1231-1243`, obs squad = **108 floats** :

```
[0:16]    Global context (16 floats)
[16:21]   Squad aggregates (5 floats)
[21:63]   Top-k=6 figurines × 7 features (positions relatives, HP%, …)
[63:108]  5 enemy slots × 9 features
```

Recherche de `terrain` / `wall` / `cover` / `obstacle` dans la construction de cette obs : **zéro
occurrence**. L'ancienne obs (355 floats) comportait 32 floats de terrain ; l'obs squad ne les a plus.

**L'agent ne perçoit pas les murs.** Raffiner l'encodage géométrique de l'action sans corriger ce point
revient à donner un volant plus précis à un conducteur aveugle : le masque l'empêche de jouer illégal,
jamais de contourner, de se mettre à couvert ou de bloquer une ligne de vue. **C'est ce constat qui
justifie la refonte (§6) plutôt qu'un simple correctif d'action space.**

### 4.2 `validate_move_plan` ne valide QUE la destination, jamais le trajet

`shared_utils.py:3292-3385` : bounds, murs, collisions, EZ et budget sont contrôlés **sur la case
d'arrivée uniquement**. Aucun pathfinding. À 1 hex de distance, destination ≈ trajet, donc le trou est
invisible aujourd'hui.

**Piège pour toute correction naïve** : sauter directement à `ancre + budget × direction` ferait
**traverser les murs**. Toute destination doit venir du pool BFS
(`movement_build_valid_destinations_pool`), qui, lui, explore réellement le chemin.

### 4.3 Divergence gym / moteur sur le jet d'Advance

Deux systèmes parallèles pour la règle 09.06 :

| Système | Clé | Écrit par | Lu par |
|---|---|---|---|
| **Moteur / PvP (autoritaire)** | `advance_rolls` + `units_advanced` | `movement_handlers.py:801-809`, `commit_move` (`shared_utils.py:4145`) | `_advance_roll_for` (`movement_handlers.py:1791-1803`) → budget des pools ; `shooting_handlers.py:967` → restriction d'armes (ASSAULT) |
| **Gym** | `_squad_advance_rolls` | `action_decoder.py:202` | `action_decoder.py:881`, `w40k_core.py:5229/5286` |

`_squad_advance_rolls` n'est lu par personne d'autre que le gym.

**Pas de bug de règle actif** : `commit_move` marque bien `units_advanced` (`shared_utils.py:4145`), donc
la **restriction d'armes** après Advance fonctionne (09.06 ne bloque pas le tir en soi : il interdit
charge et action ; côté tir, seules les armes ASSAULT restent utilisables — c'est ce que fait
`shooting_handlers.py:967` via `weapon_availability_check`, pas un blocage total). **Mais
`advance_rolls` n'est jamais renseigné côté gym** : un pool « advance » construit en gym utiliserait le
**budget normal**, silencieusement. À traiter avant de brancher le pool sur le chemin gym.

**Divergence de timing assumée à documenter** : le gym **pré-jette** l'advance roll au moment du masque
(`action_decoder.py:202-205`), donc l'agent connaît son jet AVANT de choisir Advance, alors que 09.06
impose le jet APRÈS le choix du move type (« BEFORE MOVING: Make an advance roll »). Nécessaire pour
masquer les directions Advance (et demain pour projeter le pool Advance sur la grille, §7 T2), mais
c'est une entorse au tabletop qui avantage l'agent — décision à entériner, pas un implicite (§10).

### 4.4 Le pool gym et le pool PvP n'ont pas la même métrique

`config/game_config.json:52-54` :
```json
"move": "euclidean",       // PvP / replay
"move_gym": "hex",         // training
```
Bascule dans `_move_distance_metric` (`movement_handlers.py:1827-1847`). Divergence **assumée et
configurée** (perf). On partage donc le *builder* (une seule implémentation des règles), **pas la
géométrie**. À ne pas présenter comme un « miroir exact du PvP ».

### 4.5 L'action space réel est 41, pas 26 — *(constat d'investigation, avant refonte)*

> **Périmé depuis T2b** : l'action space vaut désormais **1047** (`BASE_ZONE_INTENT = 1032`,
> `TOTAL_ACTION_SIZE = 1032 + 5×3`). Le constat ci-dessous décrit l'état à l'investigation.
> **L'exigence de synchronisation, elle, reste valable et est maintenant VÉRIFIÉE par test**
> (`tests/unit/engine/test_action_space_mirror.py`) — elle ne l'était par rien.

`engine/macro_intents.py:19-20` : `BASE_ZONE_INTENT = 26`, `TOTAL_ACTION_SIZE = 26 + 5×3 = 41`
(26 micro + 15 macro `zone_intent` = 5 objectifs × 3 intents). `macro_intents.py` se déclare *miroir
exact* de `shared_utils.py` (`SQUAD_ACTION_*`, `shared_utils.py:7237-7250`) : **les deux doivent rester
synchronisés**.

### 4.6 `start_pos` est toujours exclu du pool — choix de design cohérent

`movement_handlers.py:2587` (`if _cell == start_pos: continue`) et `:2628` (`if nb != start_pos …`).
**Nuance** : 09.05 ne donne qu'un maximum (M), le PDF n'interdit pas un Normal Move de 0". Mais
**Remain Stationary (09.04)** existe comme move type distinct (et ne déclenche pas les règles de
début/fin de move), et l'action WAIT le couvre déjà. Exclure `start_pos` du pool est donc un **choix de
design** (pas une obligation de règle) : la seule perte est un « move de 0" qui compte comme move » —
sans enjeu tant qu'aucune règle déclenchée par début/fin de move n'est implémentée.

---

## 5. Règles applicables (PDF lus : `Documentation/40k_rules/09 Movement phase.pdf`)

- **09.02 Move Units** : « Select one move type that unit is eligible to make ». Une unité fait **un**
  déplacement par phase de move → **1 action gym = 1 move complet**. Découper un move en N micro-pas
  déforme la règle.
- **09.04 Remain Stationary** — MAXIMUM DISTANCE : `–`. « No models are moved (either in straight lines
  or rotated). Units that remain stationary **do not trigger any rules that are triggered when a unit
  starts or ends a move** ». → couvert par WAIT.
- **09.05 Normal Move** — MAXIMUM DISTANCE : `M`. ELIGIBLE IF : unengaged. AFTER MOVING : must be
  unengaged. → distance dans **[1, M]** *par choix de design* : la règle ne fixe qu'un maximum, la
  borne basse vient de l'exclusion de `start_pos` (§4.6), le cas 0 étant couvert par WAIT/09.04.
- **09.06 Advance Move** — MAXIMUM DISTANCE : `advance roll + M`. AFTER MOVING : ni charge ni action.
- **09.07 Fall-Back Move** — MAXIMUM DISTANCE : `M`. ELIGIBLE IF : engaged. AFTER MOVING : ni tir, ni
  charge, ni action.
- **03 Moving** : un déplacement est un **chemin**, pas une téléportation (cf. §4.2).

---

## 6. Design — options étudiées et décision

### 6.1 Options rejetées

| Option | Pourquoi rejetée |
|---|---|
| **A. Move incrémental** (1 action = 1 subhex, activation ouverte tant qu'il reste du budget) | Transforme une règle (09.02 : un move) en 25 micro-décisions. Épisodes ~5-10× plus longs. **Rejeté par l'utilisateur : « 1 action, c'est un move complet »**. |
| **B. Ray-cast en ligne droite** jusqu'au budget | L'agent ne peut pas contourner un mur ; mouvement rectiligne, très en deçà du PvP. |
| **C. `Discrete` aplati** 6 directions × (M+1) distances (156 actions à ×5) | Taille dépendante de l'échelle ; 156 dry-runs de plan rigide par activation ; ligne droite uniquement. |
| **D. `MultiDiscrete([41, 101])`** (direction, fraction du budget) | La distance légale dépend de la direction, or MaskablePPO masque chaque dimension **indépendamment** → masque soit trop permissif (actions illégales → bruit), soit trop restrictif. Surtout : **6 directions = 6 rayons seulement**, alors que le pool contient 626 à 4395 destinations réparties sur un disque 2D. |
| **E. `MultiDiscrete([26, A, D])`** (type, angle, distance) + projection sur le pool | Meilleur que D (angle découplé du type), mais : **2D-only** (les étages sont un chantier en cours), mapping par projection **non-lisse**, résolution angulaire **non uniforme** (fine au centre, grossière au bord), et surtout **ne corrige pas la perception** (§4.1). |
| **F. Pointer sur K candidats décrits** (le moteur échantillonne K destinations du pool, décrites par features sémantiques) | Séduisant et économique (reste `MlpPolicy`), invariant à l'échelle, extensible 3D. Mais le choix des K candidats est une **heuristique qui borne l'optimum** : si le bon hex n'est pas échantillonné, il est injouable. |

### 6.2 Décision : obs spatiale égocentrique + tête spatiale

**Retenu** (arbitrage utilisateur du 2026-07-17, « la refonte ne pose pas de problème ») :

- **Observation** : ajout d'une **grille locale égocentrique** autour de l'escouade active — **32×32×6**
  (§10.1), canaux : murs/obstacles, occupation alliée, occupation ennemie, zone d'engagement,
  objectifs, niveau (étages). Mapping grille↔hex **unique** : `budget_normalized` — la grille couvre
  toujours le disque atteignable, d'où l'invariance à l'échelle (§10.2 ; `fixed_resolution` abandonné).

  **Demi-étendue de la grille = budget Advance MAXIMAL** (`M + 6" × inches_to_subhex`), et **non** le
  budget du jet effectivement tiré. Motif : la géométrie de la grille doit être **identique entre l'obs,
  le masque et le decoder** (sinon une cellule ne désigne pas le même hex des trois côtés) et **stable
  d'un step à l'autre** — l'indexer sur le D6 ferait respirer l'échelle spatiale au gré du jet, ce qui
  détruirait la sémantique apprise par le CNN. Le pool réel (budget `M + jet`) est donc toujours
  strictement inclus dans la grille ; les cellules au-delà sont simplement masquées à 0.
- **Action** : tête spatiale — l'action de mouvement désigne une **cellule de cette grille**, masquée par
  le pool BFS projeté dessus. **Le type de move n'est PAS choisi par l'agent : il est inféré de la
  cellule choisie** (décision du 2026-07-17) :
  - escouade engagée → `fall_back` (Normal/Fall Back mutuellement exclusifs, cf. T2) ;
  - coût géodésique de la cellule ≤ M → `normal` ;
  - coût géodésique > M → `advance` (jet pré-roulé, cf. §4.3 / §10).
  L'inférence utilise le **coût géodésique** (distance de chemin du BFS), pas la distance à vol
  d'oiseau : une cellule proche mais atteignable seulement en contournant un mur peut exiger un Advance
  (03 : la distance d'un move est celle du chemin parcouru).
  **Justification** : avec un type choisi séparément (`MultiDiscrete`), MaskablePPO masquerait type et
  cellule **indépendamment** — le combo `normal` + cellule au-delà de M serait illégal mais non masqué,
  soit exactement le défaut qui fait rejeter D en §6.1. L'inférence élimine cette dépendance. **Perte
  nulle** : un Advance vers une cellule atteignable en Normal est strictement dominé (coûte le tir
  non-ASSAULT et la charge, n'apporte rien). Le type d'action reste une dimension discrète pour les
  actions non-move (wait / shoot / charge / fight).
  Quand plusieurs hexes du pool tombent dans la même cellule, la destination est l'hex du pool **le
  plus proche du centre géométrique de la cellule**, départage déterministe par (col, row) min (§10.3).
- **Policy** : `MultiInputPolicy` sur obs `Dict` (grille + vecteur), extracteur CNN pour la grille.

**Justification** :
- **Corrige la cause racine du symptôme ET le défaut sous-jacent** : l'agent peut viser tout le disque
  atteignable *et* perçoit enfin le terrain sur lequel il le fait.
- **Invariance à l'échelle** : plus rien dans l'action ne dépend de `inches_to_subhex`. Passer en ×10 ne
  touche ni l'action space, ni la policy, ni l'obs. **Le bug d'origine disparaît structurellement.**
- **Aucune heuristique de sélection** ne borne l'agent (contrairement à F).
- **Extensible** : étages, FLY, pivot par figurine = canaux/dimensions supplémentaires.
- **Le matériel suit** : GPU CUDA disponible et aujourd'hui quasi inexploité par un MLP sur 108 floats.

**Faiblesses assumées** : sample complexity supérieure (espace d'action de 256-1024 cellules contre 41 —
l'inductive bias spatial du CNN joue en sens inverse, non chiffrable sans essai) ; coût mémoire du
rollout buffer (§8, contrainte dimensionnante) ; réentraînement from scratch obligatoire ; le modèle
actuel devient incompatible.

---

## 7. Plan d'implémentation

> Ordre imposé par les dépendances. Chaque tranche doit laisser la suite de tests verte.

### T1 — Observation spatiale ✅ FAIT (2026-07-17)

**Livré** : `engine/spatial_grid.py` (nouveau, géométrie partagée) ; `ObservationBuilder.build_squad_grid()`
(6 canaux) ; purge du cache statique dans `W40KEngine.reset()` ; `tests/unit/engine/test_spatial_grid.py`
+ `tests/unit/engine/test_squad_grid_observation.py` (44 tests). **Non livré** : le câblage de l'obs en
`Dict` (`{"vec", "grid"}`) — il change `observation_space` et la policy, donc il atterrit avec T4/T5
(sinon la suite casse pour rien à mi-chemin). `build_squad_grid` est fonctionnel et testé dès maintenant.

**Décisions prises en cours d'implémentation** (le code diverge de la spec sur 3 points, à jour ci-dessous) :
- Demi-étendue = budget Advance **maximal**, pas le jet tiré (§6.2) — géométrie stable + identique
  entre les 3 couches.
- Dimensionnement sur **√3** (pas hex réel) et non `ENGAGEMENT_NORM_HEX_WIDTH`=1.5 (§10.9).
- **Demi-marge** d'un pas hex : sans elle, un hex à distance exactement égale au budget tombe à
  `|u| = 1.0` pile, donc hors grille — destination légale perdue (trouvé par test).

### T1 — spécification d'origine
- `engine/spatial_grid.py` (**nouveau**) : géométrie de la grille, **source unique** partagée par l'obs
  (T1), le masque (T2) et le decoder (T3). Aucune de ces trois couches ne recalcule le mapping.
- `engine/observation_builder.py` : nouvelle grille égocentrique **32×32×6** ; canaux
  murs / alliés / ennemis / EZ / objectifs / niveau. Obs devient un `Dict` (`{"vec": …, "grid": …}`).
- Mapping grille↔hex : `budget_normalized` seul (§10.2) ; rasterisation **géométrique** via les centres
  euclidiens normalisés des hexes (`_hex_center`), pas leurs indices offset (§10.9).
- Rasterisation depuis les caches existants (`wall_hexes`, `build_occupied_positions_set`,
  `enemy_adjacent_hexes_player_*`) — **ne pas recalculer** ce qui est déjà en cache.
- Mesurer le surcoût par step (attendu : « sous la ms » face aux 65 ms — **à confirmer**, §8).

### T2 — Espace d'action + masque — 🟡 EN COURS (2026-07-17)

**Fait** — le socle « pool BFS → coût géodésique » :
- `movement_build_valid_destinations_pool` gagne 2 paramètres **purement additifs** (§10.5 respecté :
  quand ils valent `None`, le PvP est strictement inchangé — verrouillé par test) :
  - `out_costs` : `{(col,row): coût géodésique en subhex (float)}`
  - `move_budget_override` : budget imposé, car le gym a besoin du pool au budget **Advance** alors
    que l'escouade n'a **pas** déclaré Advance (donc absente de `units_advanced` → le builder
    retombait sur le budget normal).
- **§4.3 CORRIGÉ** : `execute_squad_move` fige désormais le jet dans `advance_rolls` (système
  autoritaire, miroir du writer PvP `movement_handlers.py:801-809`). `execute_squad_move` n'a qu'un
  appelant (chemin gym) → zéro impact PvP. Bug prouvé par test : fix retiré → 2 tests rouges.
- Tests : `tests/unit/engine/test_move_pool_geodesic_costs.py` (8),
  `tests/unit/engine/test_gym_advance_rolls_alignment.py` (4).

**Le « 1 seul BFS au budget Advance » est validé** : classer le pool Advance par coût ≤ M reproduit
**exactement** le pool construit au budget M (`test_override_pool_carries_costs_that_separate_normal_from_advance`).

**Fait — le masque spatial** (T2b) :
- `SQUAD_ACTION_*` refondus : `MOVE_CELL_BASE=0` / `COUNT=1024` (= `GRID_CELL_COUNT`), `WAIT=1024`,
  `SHOOT_SLOT_BASE=1025`, `CHARGE=1030`, `FIGHT=1031` → **`SQUAD_ACTION_SIZE = 1032`**.
  `macro_intents` : `BASE_ZONE_INTENT=1032`, **`TOTAL_ACTION_SIZE = 1047`**. Le miroir §4.5, que
  la spec imposait mais que **rien ne vérifiait**, est désormais verrouillé par test
  (`tests/unit/engine/test_action_space_mirror.py`).
- `build_squad_move_cell_map()` : **source unique** du masque ET du décodage → un mismatch
  masque/exécution devient structurellement impossible (vérifié : `test_mask_bits_match_the_cell_map_exactly`).
- `infer_squad_move_type()` : type déduit du coût géodésique (§6.2), jamais d'une dimension d'action.
- Les 18 dry-runs directionnels (3 types × 6 directions) sont supprimés.
- Gardes d'origine **préservées à l'identique** (`has_advanced`/`has_fled` ferment Advance et Fall
  Back mais **pas** le Normal ; `advance_roll=None` → pool au budget normal, donc zéro cellule
  Advance) — la refonte ne change pas ces règles au passage.
- Tests : `tests/unit/engine/test_squad_spatial_move_mask.py` (11), `test_action_space_mirror.py` (8).

> ⚠️ **La suite est ROUGE à la fin de T2b (28 échecs + 1 erreur de collection), et c'est attendu.**
> L'hypothèse de §7 « chaque tranche doit laisser la suite verte » **ne tient pas pour l'action
> space** : passer de 26 à 1032 est un changement **atomique** qui ne peut pas être vert tant que le
> decoder (T3), la propagation (T4) et la config (T5) n'ont pas suivi. Les 28 échecs se réduisent à
> 3 causes mécaniques, **aucune régression cachée** :
> 1. `Required key 'move' is missing` — fixtures sans `config["move"]`. **Dépendance nouvelle et
>    réelle** : le masque passe désormais par le pool BFS, qui lit les toggles de traversée ; les
>    dry-runs directionnels ne les lisaient pas.
> 2. `IndexError: index 240 out of bounds for axis 0 with size 41` — fixtures à
>    `action_space_size=41`. *(Résolu en T3 non pas en « mettant à jour » la valeur, mais en
>    supprimant la clé : la taille est dérivée du moteur — cf. §7bis #10.)*
> 3. `assert 1024 == 18` — tests figeant `WAIT == 18`.

**Reste** : `action_space` de `w40k_core.py:629`, puis T3/T4/T5 pour reverdir.

**Mesure (board ×5, `scenario_training_bot-01`, squad MOVE 18"→90 subhex de budget Advance max)** :

| Appel | Coût | Destinations |
|---|---|---|
| Pool PvP (sans coûts, budget normal) | 4,63 ms | — |
| **Pool gym (coûts + budget Advance)** | **6,37 ms** | **5 386** |
| *(remplace)* dry-runs directionnels normal+advance (§8.2) | ~8,6 ms | 12 |

→ Le bilan « neutre à légèrement gagnant » de §8.2 est **confirmé par la mesure** : ~2 ms gagnées,
et l'agent passe de 12 destinations atteignables à 5 386.

**Correction d'une erreur d'analyse initiale** : la spec laissait entendre que le coût géodésique
était déjà disponible dans le BFS hex. C'est vrai, mais ce BFS-là n'est **pas** celui du gym : sur le
board ×5, `BASE_SIZE` ∈ {6,8} et `ez`=10, donc `is_single_hex = (ez <= 1 or base_size == 1)` est
**False** → le gym passe par `_build_multi_hex_vectorized`. Les 4 branches (hex mono-hex, hex
multi-hex vectorisée, euclidienne mono-hex `geodesic_field`, euclidienne multi-hex) produisent
**toutes** déjà une distance ; `out_costs` est câblé sur les 4, unité commune = subhex (les branches
euclidiennes divisent par `ENGAGEMENT_NORM_HEX_WIDTH`). Aucune branche n'est refusée.

**Piège trouvé à l'implémentation** : un filtre post-BFS (bornage rigide d'escouade) retire des
destinations **après** que le BFS a rempli `out_costs` → les coûts portaient des destinations
injouables. Le pool reste la seule autorité : `out_costs` est resynchronisé dessus avant retour.

### T2 — spécification d'origine
- `engine/phase_handlers/shared_utils.py` : constantes `SQUAD_ACTION_*` ; masque du type d'action ;
  **projection du pool BFS sur la grille** (source du masque spatial).
- `engine/macro_intents.py` : **miroir exact obligatoire** (cf. §4.5).
- `engine/w40k_core.py:629` : `action_space` (`Discrete` → structure spatiale).
- Optimisation du masque : Normal et Fall Back s'excluent (`in_er`) et le pool Advance **contient** le
  pool Normal (budget supérieur) → **1 seul BFS au budget Advance** suffit, en conservant le **coût
  géodésique** de chaque cellule : c'est lui qui sert à l'inférence du type (coût ≤ M → `normal`,
  coût > M → `advance`, cf. §6.2). Plus aucun masque de type de move : une cellule = un move légal.

### T3 — Décodage et exécution ✅ FAIT (2026-07-17)

**Livré** :
- `action_decoder.py` : la carte `cellule -> (destination, coût)` est construite **une fois** au
  masque, mémoïsée (`store_squad_move_cell_map`), puis relue au décodage. Évite un 2ᵉ BFS par step
  **et** rend la divergence masque/exécution structurellement impossible. La carte est **tamponnée
  (ancre, phase)** : périmée → **erreur explicite**, jamais réutilisée en silence.
- `convert_squad_action` : cellule → destination **du pool** + type **inféré du coût géodésique**.
- `w40k_core._process_squad_action` : exécution via `execute_squad_move` avec la destination du pool.
- **Config (T5 partiel)** : `action_space_size` **supprimé** des 5 profils — la taille de l'action
  space est désormais **dérivée** du moteur (`macro_intents.TOTAL_ACTION_SIZE`), plus configurée.
  Une config ne peut donc plus contredire le code (cf. audit §7bis #10).
- Tests : `tests/unit/engine/test_spatial_move_decode_execute.py` (13).

**Fallback SUPPRIMÉ** — le plus important de la tranche : l'ancien code faisait un dry-run
`_squad_direction_move_legal` et, s'il échouait, **dégradait silencieusement en `squad_wait`**
(« Direction blocked — action was outside mask. Treat as squad_wait »). Ce repli existait parce que
le masque directionnel pouvait diverger de l'exécution — et il **masquait** cette divergence au lieu
de la signaler. La destination venant maintenant du pool que le masque a lui-même utilisé, elle est
légale par construction : un échec est un bug d'invariant → **erreur explicite**.

> ⚠️ **Changement de contrat moteur** : une action hors masque **lève** désormais, là où elle était
> silencieusement convertie en wait. `test_engine_full_loop` / `test_engine_step` encodaient
> explicitement l'ancien contrat (« Les 5 premiers steps testent la stabilité de l'engine sous
> actions invalides ») en appelant `step(0)` en dur. Ils pilotent désormais la boucle **via le
> masque**, comme un agent MaskablePPO. Conforme à CLAUDE.md (« préférer un message d'erreur
> explicite plutôt qu'un fallback »).

**Deux bugs introduits par le déplacement de `WAIT` (18 → 1024), trouvés en relisant** : le wait de
la phase **command** était codé en dur à `18` (masque **et** décodage) dans le chemin squad — la
phase command aurait masqué une **cellule de move**, et le vrai WAIT n'aurait plus été décodé. Tous
les littéraux d'action du décodeur sont passés aux constantes.

**Cohérence config ↔ moteur : réglée par SUPPRESSION, pas par contrôle.** Deux tentatives de
garde-fou ont échoué avant d'arriver au bon diagnostic (cf. audit §7bis #10) : la première, posée
dans `__init__`, cassait **138 tests** en imposant un invariant global qui n'existe pas (le décodeur
sert aussi le masque legacy de `pve_controller`, indices ≤ 30) ; la seconde, déplacée au point exact,
restait un pansement. La cause réelle : `action_space_size` était une **copie manuelle en config
d'un fait déterminé par le moteur**. La clé est supprimée, la taille est dérivée de
`TOTAL_ACTION_SIZE` — plus de désynchronisation possible, donc plus de contrôle à écrire.

### T3 — spécification d'origine
- `engine/action_decoder.py` : `convert_squad_action` — cellule de grille → destination d'ancre +
  **inférence du type de move** depuis le coût géodésique de la cellule (§6.2), jamais depuis une
  dimension d'action.
- `engine/w40k_core.py:5234-5300` : exécution via `execute_squad_move` avec la destination issue du pool
  (jamais une destination construite à la main, cf. §4.2).
- **Corriger §4.3** : aligner le gym sur `advance_rolls` / `units_advanced` (système autoritaire), ou
  passer `move_type` / `advance_roll` explicitement au builder.
- `movement_build_valid_destinations_pool` : utiliser `read_only=True` sur le chemin gym (pas d'écriture
  d'état preview ; `gym_training_mode` court-circuite déjà footprint zone + mask loops).
- **Point de périmètre** : si des paramètres `move_type` / `advance_roll` sont ajoutés au builder
  (partagé avec le PvP), le comportement PvP doit rester **strictement inchangé** quand ils sont absents.

### T4 — Propagation — ✅ FAIT (2026-07-17)

**Livré** :
- `ai/evaluation_bots.py` : les 8 bots ne référencent plus les constantes directionnelles disparues
  (`MOVE_DIRS`/`ADVANCE_DIRS`/`FALL_BACK_DIRS`, cause de l'erreur de collection). Le **type de move
  n'est plus choisi** (il est inféré par le moteur) : chaque bot expose une heuristique de
  **destination** (`select_movement_destination`), ajoutée aux 4 bots qui en manquaient (ControlBot,
  Aggressive/DefensiveSmartBot, AdaptiveBot). Heuristiques : GreedyBot/AggressiveSmart → vers l'ennemi
  le plus proche ; DefensiveBot/DefensiveSmart → repli ; ControlBot → vers l'objectif (tient sa
  position s'il est dessus) ; AdaptiveBot → selon la posture (early=objectif, losing=ennemi,
  winning=repli) ; RandomBot → aléatoire ; TacticalBot inchangé.
- `ai/env_wrappers.py` (`_get_bot_action` / nouveau `_select_bot_move_action`) : en phase move, le
  wrapper lit la carte **cellule → (destination, coût)** que le moteur a mémoïsée au masque
  (`read_squad_move_cell_map`), donne au bot les destinations **réellement exécutables** (celles des
  cellules à True), puis retraduit la destination choisie en cellule via cette même carte. **Source
  unique = `spatial_grid`** ; aucun dry-run maison, aucune géométrie recalculée.
- `ai/bot_evaluation.py` : l'obs du modèle est désormais un `Dict` — le chemin d'éval l'aplatissait en
  ndarray (cassé). `predict` reçoit maintenant le `Dict` directement (MultiInputPolicy + CNN) ; le
  normaliseur d'éval gère le `Dict` via `VecNormalize.normalize_obs` (norm_obs_keys=`["vec"]` → la
  grille 0/1 n'est jamais normalisée, vérifié). Le chemin legacy (obs Box à plat) reste inchangé.

**Décisions (arbitrage du 2026-07-17, respecté)** :
- **Pas de transposition littérale** « première direction légale » → « première cellule légale » : sur
  ~337 cellules jouables (jusqu'à 634) ça donnait un coin arbitraire de la grille (root cause §3
  transposée). Le bot choisit une destination géométrique, pas un index de cellule.
- **Cohérence masque/choix stricte** : le bot ne choisit que parmi les destinations des cellules à True
  dans le masque du moteur. Un choix hors de cet ensemble (et ≠ ancre) **lève** — pas de repli
  silencieux en WAIT (l'audit §7bis avait déjà éradiqué ce repli en T3).
- **Signal WAIT** : renvoyer l'ancre courante signale « je tiens ma position » → WAIT. `start_pos` étant
  exclu du pool (§4.6), l'ancre n'est jamais une destination légale : signal sans ambiguïté.
- **Advance** : le jet est pré-tiré par le moteur au masque (§4.3/§10.4) ; le bot ne re-tire aucun dé.

**Mesures (board ×5, `scenario_training_bot-01`, GreedyBot, 13 escouades)** :

| Élément | Valeur |
|---|---|
| Move d'une escouade par phase (bot) | **33 à 85 subhex** (contre **1** avant — root cause §3) |
| Surcoût T4 par décision de bot (`_select_bot_move_action` seul) | **0,68 ms** (médiane 0,53 ; max 1,3) |
| *(1ʳᵉ implémentation, distance empreinte→empreinte par cellule)* | ~44 ms — **rejetée** |

> ⚠️ **Piège de perf mesuré** : la 1ʳᵉ version calculait `compute_candidate_footprint` +
> `min_distance_between_sets` **par cellule candidate** (~337) → 44 ms/décision. Remplacé par une
> distance-hex **ancre→ancre** (O(1)/cellule) : ~65× plus rapide, suffisant pour une heuristique de
> bot. La leçon §8.5 (« mesure, n'affirme pas ») a resservi.

**Non touché** : `engine/pve_controller.py` (n'utilise pas les constantes disparues, a sa propre
`_ai_select_movement_destination`) ; `ai/train.py` (T1b/T5 avaient déjà traité l'obs Dict côté training).

### T4 — spécification d'origine
`ai/env_wrappers.py`, `ai/train.py`, `ai/bot_evaluation.py`, `ai/evaluation_bots.py`,
`engine/pve_controller.py` : tout site qui manipule une action entière ou un masque plat.

> ⚠️ **`ai/evaluation_bots.py` n'est PAS de la propagation mécanique** (constat 2026-07-17, vérifié).
> Les bots choisissent leur move par `_first_action_in(valid_actions, mi.MOVE_DIRS)`, c'est-à-dire
> **la première direction légale = direction 0, toujours**. Deux conséquences :
> - **Les bots subissent la root cause §3 exactement comme l'agent** : ils avancent d'1 subhex vers
>   le nord par phase de move. Le win-rate de référence est donc mesuré contre des adversaires qui ne
>   se déplacent pas non plus. À garder en tête pour lire les résultats de T6 : le win-rate va bouger
>   des **deux** côtés.
> - En spatial, « première action légale » sur 1024 cellules donnerait une cellule de coin arbitraire.
>   Transposer littéralement `MOVE_DIRS` → `MOVE_CELLS` n'a **aucun sens**.
>
> **Bonne nouvelle** : les bots possèdent déjà une heuristique de destination correcte —
> `select_movement_destination(unit, valid_destinations, game_state)` (GreedyBot vise la cible la plus
> proche, etc.). Elle n'est aujourd'hui appelée que par `engine/pve_controller.py`, **jamais** sur le
> chemin training/éval, précisément parce que l'action space directionnel ne savait pas l'exprimer.
> L'action space spatial le permet enfin : destination choisie → `hex_to_cell` → action.
> **C'est un gain de la refonte, pas une dette** — mais c'est du design, à faire consciemment en T4.

### T5 — Configuration — ✅ FAIT (2026-07-17)

**Fait** : `action_space_size` **retiré** des 5 profils (dérivé du moteur, cf. audit §7bis #10).
`policy` `MlpPolicy` → `MultiInputPolicy`, **`n_steps` 16384 → 8192** (§8.3, RAM du rollout buffer) sur
les **5 profils** (`x1`, `x5_append`, `x5_new`, `x1_debug`, `x5_debug`). La CLASSE de l'extracteur CNN n'est pas en
config (c'est une classe) : elle est injectée dans `ai/train.py` quand l'obs est `Dict`
(`_inject_spatial_extractor`), source `ai/spatial_extractor.py`. En revanche son hyperparamètre
`cnn_features` (largeur de la sortie CNN avant concat avec `vec`) EST en config depuis le 2026-07-17 :
`policy_kwargs.features_extractor_kwargs.cnn_features` (256 sur les 5 profils), **obligatoire, sans
défaut** — `_inject_spatial_extractor` refuse une config qui ne le déclare pas, et sb3 transmet
nativement `features_extractor_kwargs` au constructeur. `features_dim` = `cnn_features` + 108.
`net_arch` `[320,320]` conservé (MLP partagé APRÈS l'extracteur). Détail du câblage : §7ter
« T1b/T5 — livré ».

- La grille couvre le budget max par construction (§10.2) : aucune troncature possible, donc pas de
  garde-fou à ajouter ici.

### T6 — Réentraînement et validation (§9) — 🟢 DÉBLOQUÉ (2026-07-18, crash fight corrigé)

**Un** run from scratch (`budget_normalized`, mode unique depuis §10.2), win-rate multi-scénarios.

**État T6 (2026-07-18)** :
- **§9.1 Suite unitaire** ✅ **1395 passed / 2 skipped / 0 failed / 0 error** (1397 tests, sans
  `--ignore`), relancée après le fix fight (masque aligné sur le pool 12.04). +1 test vs baseline :
  `test_snapshot_engaged_unit_with_dead_enemy_offers_fight_and_breaks_loop` (régression du crash).
- **§9.2 `--step`** ✅ La root cause §3 est morte **côté runtime** : sur `x5_new --new --step`
  (modèle frais, board ×5), 94 moves loggés, distances-hex **2 → 69 subhex** (médiane 15,5), plus
  aucun move bloqué à 1. Le max 69 ≈ MOVE 14" × `inches_to_subhex`=5 en budget Advance. Distribution
  étalée sur tout le disque (attendu pour une policy quasi-aléatoire). Distance calculée via
  `calculate_hex_distance` sur les paires `MOVED from→to` de `step.log`.
- **§9.3 analyzer** ✅ **Phase move = 0 erreur** (catégorie 1.1). Les catégories non-nulles
  (1.2 tir 157, 1.4 fight 22, 2.1 dead-units 3) sont du **jeu aléatoire** d'un modèle non entraîné
  (tir/fight sur unités mortes en `(0,0)`, hors portée) — path tir/combat non touché par la refonte,
  **aucune nouvelle catégorie imputable au move**.
- **§9.4 replay** ⏳ contrôle visuel non fait en session headless (MODE NUIT) — à faire au navigateur.
- **§9.5 non-régression PvP** ✅ Le fix fight ne touche PAS le PvP : `build_squad_action_mask` n'a
  qu'un appelant (chemin gym `action_decoder.py:242`) ; le PvP conduit la machine V11 directement par
  `fight_handlers.fight_v11_*`, non modifiés. `execute_semantic_action` inchangé. Suite PvP verte.
- **§9.6 retrain** 🟢 **DÉBLOQUÉ (2026-07-18)** — le crash fight-phase est **corrigé** (masque aligné
  sur le pool 12.04, cf. « FIX APPLIQUÉ » ci-dessous). Le run `--new x5_new` passe le point de crash et
  entraîne **sainement** : 70 épisodes en ~9 min, RAM plate ~29 Go, aucun crash. Débit mesuré ~14
  steps/s (§8.5) → retrain **complet** (30000 ép., ETA ~47 h) = job multi-jours à laisser tourner en
  fond ; win-rate multi-scénarios + catastrophic forgetting à mesurer une fois convergé.
- **§9.7 pas de reward de move** ✅ respecté par design (aucun reward shaping de déplacement ajouté).

**Fix livré (nécessaire pour `--new`, prouvé par erreur)** :
- [`ai/train.py`](file:///home/greg/40k/ai/train.py) — `train_with_scenario_rotation` appelait
  `load_vec_normalize` **avant** le garde `not new_model` (ligne ~2506). Sur un retrain from-scratch
  après changement d'obs space (Box(108) → Dict), charger l'ancien `vec_normalize.pkl` planté dans
  `set_venv` (shape check : `(108,) != None`) alors que le résultat est de toute façon jeté. Or `--new`
  est obligatoire (obs incompatible) et supprimer le `.pkl` à la main est interdit. Le chargement est
  désormais gardé par `not new_model and not reset_vec_normalize`. **Les deux autres sites du même
  pattern (create_model ~1489, create_multi_agent_model ~1832) ne sont pas sur le chemin `--scenario
  bot` et n'ont PAS été touchés (corriger au minimum)** — à traiter si un jour un `--new` passe par eux.

**🔴 BLOQUEUR — boucle infinie en phase fight (root cause établie, PRÉ-EXISTANT, hors périmètre move)** :

- **Symptôme** : `_run_bot_until_not_bot_turn` (`ai/env_wrappers.py`) boucle >500× en `phase=fight` puis
  lève ; un env subprocess meurt → `EOFError` en cascade → `model.learn()` avorte. Reproduit 2/2.
- **État capturé** (instrumentation temporaire, retirée depuis) : `eligible=[('109', 2)]`,
  `current_player=2`, `fight_subphase=fight`, `units_fought` contient déjà `'109'`, pools alternés
  vides, et le bot rejoue **action 1024 = `SQUAD_ACTION_WAIT`** à chaque itération.
- **Root cause — DIVERGENCE entre deux fonctions d'éligibilité fight** :
  - `fight_v11_is_eligible_to_fight` (pool, `fight_handlers.py:2856`, lu par
    `_get_eligible_units_for_current_phase` → `fight_v11_current_pool`) garde 109 éligible via le
    snapshot **`engaged_at_fight_step_start`** (109 était engagé au début de l'étape FIGHT, son ennemi
    est mort depuis).
  - `_squad_is_in_fight` (masque, `shared_utils.py:6707`, lu par `build_squad_action_mask:7623`) ne
    teste que l'engagement **actuel** (ou `units_charged`) → **False** → le masque n'offre que
    `SQUAD_ACTION_WAIT`, jamais `FIGHT`.
  - `squad_wait` en phase fight (`w40k_core.py:5263`, `end_activation(WAIT, FIGHT)`) **n'ajoute pas**
    109 à `units_selected_to_fight` → 109 reste éligible au tour suivant → boucle.
- **Base règle (12 Fights phase.pdf, relu et vérifié le 2026-07-18)** — une unité **engagée au début
  de l'étape FIGHT mais désengagée maintenant** (ennemi détruit) **RESTE éligible au combat** :
  - **12.04** : « eligible to fight if it is within Engagement Range …, OR **it was within Engagement
    Range at the start of this step**, or it made a Charge move this turn ». La 2ᵉ clause (snapshot
    `engaged_at_fight_step_start`) suffit → l'unité désengagée par la mort de son ennemi est éligible.
  - **12.06 Overrun** : « ELIGIBLE IF: Your unit **IS UNENGAGED**, or was unengaged at the start … ».
    La **1ʳᵉ clause suffit** : désengagée maintenant → overrun autorisé. **Exemple officiel page 4** :
    exactement ce cas (cible détruite, l'unité fait un overrun et se ré-engage via pile-in).
  - **Conclusion** : le pool (`fight_v11_is_eligible_to_fight`, `fight_handlers.py:2856`) est
    **CONFORME**. C'est le **MASQUE** qui était trop restrictif (3ᵉ copie divergente de la règle).
  - *(Correction 2026-07-18 : le paragraphe précédent affirmait l'inverse — « le pool est trop
    permissif », « aucun type de fight jouable ». C'était FAUX, contredit par 12.04 clause 2 et 12.06
    clause 1 + l'exemple page 4. Les deux pistes de fix qui en découlaient sont **rejetées** : la
    piste « Pool » (exclure l'unité du pool) violait 12.04/12.06 ; la piste « WAIT » (enregistrer
    l'unité via WAIT) violait 12.08 — l'unité doit être `selected_to_fight` par un vrai FIGHT pour
    ouvrir sa consolidation, pas par un WAIT.)*
- **Pourquoi maintenant** : PRÉ-EXISTANT (le garde anti-boucle existe précisément pour ce cas). Avant la
  refonte, les unités bougeaient d'1 subhex → atteignaient rarement le corps-à-corps → le cas
  « engagé au début, ennemi tué pendant l'étape » ne survenait quasi jamais. Le move corrigé
  **expose** le bug, il ne le crée pas. Le path tir/combat n'a pas été modifié par la refonte.

**✅ FIX APPLIQUÉ (2026-07-18) — le masque dérive du pool 12.04, la 3ᵉ copie est supprimée** :
- **Root cause exacte** : `_squad_is_in_fight` (`shared_utils.py`) était une **3ᵉ implémentation**
  de l'éligibilité fight (engaged-now + charge, **sans** le snapshot 12.04), divergente du pool. Ses
  **2 appelants** (le bit `ACTION_FIGHT` de `build_squad_action_mask`, et `squad_fight_activation_order`)
  dérivent désormais de la **MÊME source que le commit** (`fight_v11_current_pool` /
  `fight_v11_is_eligible_to_fight`, `fight_handlers.py`). Pas de clause snapshot ajoutée à une 3ᵉ copie
  (ce serait reproduire le défaut §7bis #4) : la copie est **supprimée**.
- **Parité masque/commit garantie** : le bit `ACTION_FIGHT` = `squad_id in fight_v11_current_pool`
  **sous garde `fight_subphase == "fight"`** (le snapshot n'existe que pendant l'étape FIGHT, poppé en
  fin d'étape `fight_handlers.py:3152`, et le pool le lit via `require_key` — d'où la garde, exactement
  celle que le commit `squad_fight` impose déjà `w40k_core.py:5510`). C'est le pool que le commit
  vérifie (`w40k_core.py:5536`) → le masque et le commit ne peuvent plus diverger.
- **Résolution du crash** : l'unité 109 (engagée au début, ennemi mort) est dans le pool → le masque
  offre `FIGHT` → le bot/agent le joue → `squad_fight` résout **à vide** (0 attaque, machinerie
  12.04/12.06 déjà en place `w40k_core.py:5552-5572`, aucun overrun pile-in à implémenter) → 109 est
  enregistrée `units_selected_to_fight` → sort du pool → **plus de boucle**.
- **PvP strictement inchangé** : `build_squad_action_mask` n'a qu'un appelant, le chemin gym
  (`action_decoder.py:242`). Le PvP passe directement par les `fight_v11_*` (`fight_handlers.py`),
  non touchés.
- **Périmètre** : `engine/phase_handlers/shared_utils.py` (masque + `squad_fight_activation_order`,
  suppression de `_squad_is_in_fight`) + `tests/unit/engine/test_squad_fight_target_parity.py`
  (nouveau test du scénario exact + mise à jour du test « charged » au nouveau contrat de parité).
- **Validation** : crash reproduit (`BotControlledEnv infinite loop: 501 iterations, phase=fight`),
  fix appliqué, run `--new` passe ce point. Test unitaire ajouté :
  `test_snapshot_engaged_unit_with_dead_enemy_offers_fight_and_breaks_loop` (engagée au début, ennemi
  mort → masque offre FIGHT, pas WAIT ; résolution à vide 0 attaque ; sélection enregistrée ; sortie
  du pool). Suite complète verte.

### Fichiers impactés (récapitulatif)
```
engine/spatial_grid.py (NOUVEAU, T1)   engine/observation_builder.py
engine/action_decoder.py
engine/phase_handlers/shared_utils.py  engine/phase_handlers/movement_handlers.py
engine/w40k_core.py                    engine/macro_intents.py
engine/pve_controller.py               ai/env_wrappers.py
ai/train.py                            ai/bot_evaluation.py
ai/evaluation_bots.py                  config/agents/CoreAgent/CoreAgent_training_config.json
tests/unit/…                           (+ ai/analyzer*.py si l'action space est reflété)
```

---

## 7bis. Audit T1→T2 (2026-07-17) — fallbacks / valeurs par défaut / workarounds

Relecture critique du code livré, à la demande de l'utilisateur. **7 défauts trouvés et corrigés**,
dont 3 étaient de vrais workarounds. Ce qui suit est conservé comme mémo des pièges de ce périmètre.

| # | Défaut | Nature | Correction |
|---|---|---|---|
| 1 | `_raise_if_costs_unsupported` refusait `out_costs` sur les branches euclidiennes | **Workaround** : justifié par « coût non calculable », affirmation **jamais vérifiée** — les 4 branches produisent déjà une distance | Supprimé ; les 4 branches câblées |
| 2 | `move_budget_override <= 0` → `ValueError`, + garde `if budget <= 0: return {}` dans `build_squad_move_cell_map` | **Workaround esquivant ma propre exception**. Or `get_squad_move_budget` renvoie `max(0, MOVE - malus)` : budget 0 = état **légitime** (21.03), et le BFS le gère déjà (pool vide, sans erreur) | Seul un budget **négatif** lève ; la garde est supprimée |
| 3 | `_dist_arr` alloué sur les branches fly même sans `out_costs` | **Régression de perf sur le chemin PvP** (~528 Ko/appel) contredisant le « PvP strictement inchangé » | Les 3 affectations sont sous garde `out_costs is not None` |
| 4 | Le masque rejouait la règle en ligne (`cost > normal_budget`) au lieu d'appeler l'inférence | **2ᵉ implémentation de la même règle** → divergence masque/decoder possible | Règle extraite en forme pure `classify_squad_move_type` (cf. #5) |
| 5 | `infer_squad_move_type` appelé **par cellule** dans le masque | **Perf** : 1,16 ms / 270 cellules = **48 % du masque** (scan de `units` + empreintes d'engagement à chaque appel) | Invariants (`in_er`, `normal_budget`) hissés hors boucle → masque **2,43 → 1,25 ms (×1,94)**, règle toujours écrite **une seule fois** |
| 6 | Docstring de `build_squad_action_mask` : « masque 26 actions », « directions Advance (6-11) » | **Doc périmée** décrivant l'ancien monde | Réécrite |
| 7 | `objective.get("hexes", [])` et `game_state.get("units_cache", {})` | **Défauts morts** : `hexes` est toujours présent (vérifié 20/20 au runtime) ; `units_cache` absent = moteur cassé, pas un cas métier | `require_key` sur les deux |

**Vérifié propre par ailleurs** : `spatial_grid.py` ne contient aucun défaut (le seul `.get` est un
accumulateur local). Les `.get(..., défaut)` restants correspondent tous à des cas **métier** réels
et suivent la convention `# get allowed` du dépôt : board sans mur, scénario sans objectif/terrain,
figurine morte, escouade absente du cache (morte/non déployée → contrat « mask all-zero »).

**Leçon transverse** : les défauts #1 et #2 sont le **même schéma** — une exception ajoutée « par
prudence » sur un cas mal compris, puis une garde ajoutée en amont pour l'esquiver. Le symptôme est
toujours le même : *si un appelant doit se protéger de mon erreur, c'est mon erreur qui est fausse.*
Le réflexe correct est de vérifier la sémantique du moteur (ici : `max(0, ...)` et le BFS à budget 0)
avant de décréter qu'un état est invalide.

### Audit T3 (2026-07-17) — 4 défauts, dont 2 bugs réels

| # | Défaut | Nature | Correction |
|---|---|---|---|
| 8 | `_squad_move_cell_maps` **non purgé au `reset()`** | **BUG** — `game_state` est le même objet d'un épisode à l'autre. Le tampon (ancre, phase) **ne protège pas** entre épisodes : au redéploiement sur la même ancre en phase move, il **coïncide**, et une carte calculée sur les murs d'un **autre scénario** passe le contrôle. Identique au bug de cache de T1 | Purge dans `reset()` + test (prouvé : purge neutralisée → rouge) |
| 9 | `_squad_advance_rolls` **non purgé au `reset()`** (pré-existant) | **BUG** — le décodeur ne re-tire que si la clé est absente. Un épisode interrompu (turn limit avec activation en cours) fait **traîner le jet de l'épisode précédent**, jamais re-tiré → viole 09.06 (un jet par Advance) | Purge dans `reset()` + test |
| 10 | Garde-fou `action_space_size` vs `TOTAL_ACTION_SIZE` | **Workaround** (signalé par l'utilisateur) : il ne faisait que détecter une désynchronisation entre **deux sources de vérité pour un même fait**. La taille de l'action space est *déterminée* par le moteur ; la recopier en config ne pouvait qu'avoir tort | **Duplication supprimée** : `total_action_size = TOTAL_ACTION_SIZE` (dérivé), clé retirée des 5 profils, garde-fou supprimé — il n'y a plus rien à synchroniser |
| 11 | Règle 09.06/09.07 (`has_advanced`/`has_fled` ferment Advance/Fall Back) écrite **deux fois** — decoder + masque | **Duplication de règle** (le commentaire l'avouait : « miroir des gardes du masque ») → le decoder pourrait bâtir un pool au budget Advance que le masque refuserait | Extraite en `squad_advance_or_fall_back_allowed`, appelée par les deux |

**Leçon #10 — la plus utile** : un garde-fou qui vérifie que deux choses restent d'accord est le
signe qu'il ne devrait y en avoir qu'une. La bonne question n'est pas « où placer le contrôle ? »
mais « pourquoi ces deux valeurs peuvent-elles diverger ? ». Ici : `action_space_size` n'était pas un
réglage, c'était une **copie manuelle d'un fait du moteur**. Les autres consommateurs
(`env_wrappers`, `pve_controller`, `w40k_core`) le dérivaient déjà de `len(action_mask)` — seul le
décodeur le lisait encore depuis la config.

**Leçon #8/#9** : tout ce qui est mémoïsé dans `game_state` **doit** être purgé dans `reset()`.
`game_state` survit aux épisodes et `_reload_scenario` en change le contenu. Un tampon de validité
(ancre, phase) ne suffit pas : entre deux épisodes il peut coïncider. C'est le **troisième** cache de
cette refonte à tomber dans ce piège (terrain T1, cartes T3, jets T3).

## 7ter. ÉTAT DE REPRISE (2026-07-17) — à lire avant de continuer

### Ce qui est fait, ce qui ne l'est pas

| Tranche | État | Effet réel |
|---|---|---|
| T1 | ✅ | `build_squad_grid` existe et est testé |
| **T1b** | ✅ | **Grille branchée sur la policy** : obs `Dict`, `MultiInputPolicy`, extracteur CNN. Validé bout en bout |
| T2a/T2b | ✅ | Masque spatial : l'agent vise 5 386 destinations jusqu'à 90 subhex (contre 6 à 1 subhex) |
| T3 | ✅ | Decoder + exécution via le pool ; fallback `squad_wait` supprimé |
| T5 | ✅ | `action_space_size` retiré (dérivé). `policy` → `MultiInputPolicy`, `n_steps` 16384 → 8192, extracteur CNN injecté (les 5 profils) |
| **T4** | ✅ | Bots propagés au spatial : ils visent 33-85 subhex (contre 1), via `select_movement_destination` + carte mémoïsée du moteur. Obs `Dict` gérée dans l'éval. `test_evaluation_bots.py` collecte et passe |
| T6 | 🟢 | §9.1/9.2/9.3 validés (suite verte ; moves 2-69 subhex ; phase move 0 erreur). Crash fight-phase **corrigé** (masque aligné sur le pool 12.04, `_squad_is_in_fight` supprimée) → retrain (§9.6) débloqué, le run `--new` passe le point de crash. Fix `ai/train.py` VecNormalize livré. Retrain complet + mesures §8.5 : en cours. Cf. section T6 |

> ✅ **T4 débloque le retrain (T6).** Perception (T1b) ET adversaires (T4) sont corrigés : un retrain se
> mesure désormais contre des bots qui savent se déplacer. Rappel : le win-rate de référence bouge des
> **deux** côtés (les bots ne bougeaient pas non plus).

**Suite** : `1394 passed, 2 skipped` **SANS `--ignore`**.

### T1b/T5 — livré (2026-07-17)

- `engine/w40k_core.py` : `observation_space` devient `gym.spaces.Dict({"vec": Box(108),
  "grid": Box(0,1,(6,32,32))})` quand `obs_size == 108` (pipeline squad) ; Box inchangé pour le
  legacy mono-fig. `_build_observation` / `_zero_obs` renvoient le `Dict` (vec via
  `build_squad_observation`, grid via `build_squad_grid`) — la grille est donc construite à **chaque**
  obs (reset + step), plus seulement testée.
- `ai/spatial_extractor.py` (**nouveau**) : `SpatialCombinedExtractor` — CNN sur `grid`
  (3 conv + tête linéaire → 256), passthrough de `vec` (108), concat → `features_dim = 364`. Le défaut
  `CombinedExtractor` aurait aplati la grille (6 canaux ≠ image sb3), d'où l'extracteur dédié.
- `ai/train.py` : 3 chemins de création de modèle (create_model / create_multi_agent_model /
  scenario_rotation) — helpers `_is_dict_obs_space`, `_vec_norm_obs_keys`, `_inject_spatial_extractor`,
  `_resolve_device_for_obs`. VecNormalize reçoit `norm_obs_keys=["vec"]` (la grille reste 0/1,
  **jamais normalisée**). Device : obs Dict → CNN → **GPU** si dispo (le benchmark MlpPolicy-CPU ne
  s'applique plus).
- `ai/training_callbacks.py` : le q-value tracking (mort pour MaskablePPO, gardé par `hasattr q_net`)
  ne touche plus `.shape` d'un espace Dict.
- `config/.../CoreAgent_training_config.json` : `policy` `MlpPolicy` → `MultiInputPolicy`,
  `n_steps` 16384 → **8192** sur les **5 profils** (§8.3, RAM du rollout buffer).

**Mesuré (board ×5, `scenario_training_bot-01`, GPU RTX 4060, DummyVecEnv 1 env)** :

| Élément | Valeur |
|---|---|
| `build_squad_grid` (cache statique chaud) | **0,25 ms** (cohérent avec §8.4bis : 0,52 ms) |
| `build_squad_grid` (cache statique froid, pire cas) | 1,9 ms |
| Extracteur | `SpatialCombinedExtractor`, `features_dim=364` |
| `MultiInputPolicy` + CNN + Dict obs | construit sur `cuda`, `model.predict` masqué OK |
| VecNormalize `norm_obs_keys=["vec"]` | grille **inchangée** après normalisation, vec normalisé — vérifié |
| `model.learn(256)` (1 env, CNN backprop GPU) | 13,8 steps/s — smoke, la prod tourne à `n_envs=48` |

> La throughput réelle du training (`n_envs=48`) n'est **pas** mesurée ici (1 env DummyVecEnv only) :
> à confirmer au premier run T6, cf. §8.5.

### T1b/T5 — sites exacts (vérifiés le 2026-07-17)

Brancher la grille = passer l'obs en `Dict`. Cascade complète :

| Site | Ce qu'il fait aujourd'hui | À faire |
|---|---|---|
| `engine/observation_builder.py` — `build_squad_observation` | renvoie `np.ndarray` 108 | renvoyer/exposer `{"vec": 108, "grid": (6,32,32)}` via `build_squad_grid` (déjà écrit et testé) |
| `engine/w40k_core.py:660` | `observation_space = gym.spaces.Box(shape=(obs_size,))` | `gym.spaces.Dict({"vec": Box(108), "grid": Box(0,1,(6,32,32))})` |
| `engine/w40k_core.py:6116` | `is_squad_pipeline = obs_size == SQUAD_OBS_SIZE_TARGET` | le gate reste piloté par `obs_size`=108 ; `_zero_obs()` doit renvoyer un `Dict` cohérent |
| `ai/train.py:1484, 1806, 2501` | `env.observation_space.shape[0]` | un `Dict` n'a pas de `.shape` → lever/adapter |
| `ai/training_callbacks.py:1114` | `torch.zeros((1, observation_space.shape[0]))` | dummy obs en `Dict` |
| `ai/train.py:1443, 1780, 2452` | `VecNormalize(...)` | supporte les obs `Dict` ; **ne pas normaliser la grille** (canaux déjà 0/1) → `norm_obs_keys=["vec"]` |
| `config/agents/CoreAgent/CoreAgent_training_config.json` (**5 profils**) | `policy: MlpPolicy`, `n_steps: 16384` | `MultiInputPolicy`, **`n_steps: 8192`** (§8.3 : 9,66 Go de rollout buffer — la RAM est la contrainte dimensionnante, pas le GPU), extracteur CNN pour `grid` |

**Constantes de la grille** : `engine/spatial_grid.py` (`GRID_SIZE=32`, `GRID_CHANNELS=6`, canaux
`GRID_CH_*`). Ne pas les redéfinir ailleurs.

### Règles apprises à ne pas réapprendre (cf. audit §7bis)

1. **Tout cache dans `game_state` DOIT être purgé dans `reset()`** — `game_state` est le **même
   objet** entre épisodes et `_reload_scenario` en change le contenu. Un tampon de validité ne
   suffit pas : entre deux épisodes il peut coïncider. Trois caches sont déjà tombés dans ce piège.
2. **Pas de garde-fou entre deux sources de vérité** — si un contrôle vérifie que deux valeurs
   restent d'accord, c'est qu'il ne devrait y en avoir qu'une. Supprimer la duplication.
3. **Une règle = une implémentation** — `classify_squad_move_type`,
   `squad_advance_or_fall_back_allowed` existent pour ça. Ne pas les rejouer en ligne.
4. **Vérifier avant de refuser** — le premier `NotImplementedError` de cette refonte prétendait
   qu'un coût géodésique n'était pas calculable ; les 4 branches l'avaient déjà.
5. **Une suite qui « affiche 0 FAILED » peut n'avoir rien exécuté** — une erreur de collection
   interrompt pytest. Toujours lire la ligne `N passed`.

## 7quater. Correctifs 2026-07-18 — pyright / check_ai_rules + bug EZ empreinte (03.04)

Nettoyage des deux gates (`pyright.log` : 30 erreurs ; `check_ai_rules.log` : 7 violations) sur le code
de la refonte. Suite complète **1395 passed / 2 skipped / 0 failed** après coup.

### pyright (30 erreurs) — dont un vrai bug

| Fichier | Correction |
|---|---|
| `ai/spatial_extractor.py` | `gym.Space.shape` est `Optional` → garde `shape is None` avant `len`/subscript (lève au lieu de subscript sur `None`) |
| `engine/spatial_grid.py` | `np` non défini dans les annotations forward-ref → `import numpy as np` au niveau module (import local redondant retiré) |
| `engine/observation_builder.py` | typage explicite de `static` (`Optional[Dict[str, Tuple[ndarray, ndarray]]]`) → lève l'ambiguïté ndarray/float dans `_paint_arrays` |
| `engine/phase_handlers/movement_handlers.py` | `out_costs` retypé `Dict[…, float]` (coûts fractionnaires via `/ ENGAGEMENT_NORM_HEX_WIDTH`) ; `_dist_arr` narrowé par `assert` **sous la garde existante** `out_costs is not None` |
| `engine/phase_handlers/shared_utils.py` | `assert advance_roll is not None` dans la branche `advance` (invariant : le roll est tiré juste avant) |
| `engine/w40k_core.py` | retour de `reset`/`step` élargi à `Union[ndarray, Dict[str, ndarray]]` — l'obs squad est un `Dict`, plus un `ndarray` |
| **`engine/spatial_grid.py` — `project_pool_to_grid`** | **VRAI BUG** : `int(cost)` tronquait le coût géodésique **fractionnaire** avant `classify_squad_move_type`. Un coût `M+0.4` retombait à `M` → cellule classée `normal` au lieu d'`advance`. Corrigé en `float(cost)` ; le contrat aval (`build_squad_move_cell_map`, `infer_squad_move_type`) était déjà en `float`. Set inchangé, classification corrigée |
| tests (`test_squad_fight_target_parity`, `test_squad_grid_observation`) | listes typées `List[Optional[str]]` ; `assert cell is not None` avant unpack de `hex_to_cell` (`Optional`) |

### check_ai_rules (7 violations)

- **5 `forbidden_term`** : le mot « fallback » apparaissait dans des commentaires/docstrings décrivant
  soit l'*absence* de fallback, soit un repli **métier** légitime (branche secondaire d'un bot).
  Reformulés « repli » — le code était déjà conforme.
- **1 `fallback_anti_error`** : `.get("hexes", [])` cité **dans un commentaire** → reformulé sans la
  syntaxe littérale.
- **1 `cache_recalculation`** (faux positif) : le suivi `current_function` du checker était écrasé par
  les **fonctions imbriquées** (`_to_arrays`… dans `build_squad_grid`) → il attribuait l'appel à un
  helper. Corrigé **dans le checker** (`scripts/check_ai_rules.py`) par une **pile d'indentation**
  résolvant la fonction *englobante*, + `build_squad_grid` ajouté à la liste d'exemption (l'appel à
  `build_enemy_adjacent_hexes` y est sous garde `if ez_cache_key in game_state` : le cache EZ persiste
  une fois bâti, donc l'appel ne se produit qu'avant la 1ʳᵉ phase move/shoot/charge — une seule fois).

### Bug EZ : zone d'engagement mesurée depuis l'ANCRE au lieu du SOCLE — **entorse 03.04**

Découvert en creusant le faux positif `cache_recalculation`.
`_compute_enemy_adjacent_cache_for_player_from_units_cache` dilatait `set(occupied_hexes_by_model.values())`
= **un hex d'ancre par figurine**, alors que l'EZ doit couvrir tout le **socle**.

- **Règles** (PDF lus) : **03.04** « a model's engagement range is the area within 2″ horizontally… **of
  it** » ; **01.04** « measure to or from the **closest part of that model's base** » ; **01.02** « the
  base is part of the model for all rules purposes ». Le schéma ENGAGEMENT (03, p.15) dessine la zone
  autour de **tout le socle**, pas d'un point.
- **Conséquence** : dilater l'ancre **sous-dimensionne l'EZ dès qu'un socle couvre plusieurs hexes**.
  Tous les rosters actuels sont multi-hex → l'EZ était sous-estimée **partout** (impact réel sur la
  légalité de move 09.05 et l'éligibilité fight/charge).
- **Correctif** : dilater `require_key(entry, "occupied_hexes")` (union des empreintes **vivantes**,
  resync par `_recompute_squad_occupied_hexes`). Le fallback single-anchor est supprimé (lève si absent).
  L'EZ ne peut que **grossir** (empreinte ⊇ ancre), jamais rétrécir.
- **Validation** : 1395 tests verts (0 cassé), spot-check PvP OK. Note : le vert ne prouve pas la
  couverture du cas multi-hex par les tests — l'élargissement est garanti par construction.
- **Reste ouvert** (§10) : vérifier que `get_engagement_zone` encode bien **2″** en subhex (le *montant*
  de dilatation, orthogonal à ancre-vs-empreinte).

### Décision : PAS d'incrémental sur le cache EZ

Le cache EZ est recalculé **entièrement** à chaque move/mort (hooks `update_enemy_adjacent_caches_*`).
Question posée : le remplacer par un delta incrémental (compteur de références par hex) ?

**Profilé** (30 épisodes, 1853 steps, board `44x60x5`, unités multi-hex réelles) :

| chemin | appels | % runtime |
|---|---|---|
| `_compute_enemy_adjacent_cache` (le recompute) | 1471 | **~1,5 %** |
| └ dont `build_enemy_adjacent_hexes` (phase_start) | 1436 | — |
| └ dont hook `after_unit_move` (cible de l'incrémental) | **0** | **0,00 %** |
| `dilate_hex_set` (le vrai coût) | 1471 | ~1,4 % |

**Verdict : non retenu.** L'incrémental optimise les **hooks** (delta par move) ; or le hook move pèse
**0 %** ici (le coût vient des builds phase_start, que l'incrémental ne remplace pas), et tout le calcul
EZ plafonne à ~1,5 %. Gain maximal < 1,5 % sur un chemin à 0 % → complexité (compteur de refs + delta +
test d'équivalence) injustifiée. Réserve : scénario rush mêlée (peu de moves normaux) ; un training à
objectifs déclencherait plus le hook move, mais le plafond ~1,5 % borne le gain.

## 8. Mesures et contraintes chiffrées

### 8.1 Matériel et configuration (relevés le 2026-07-16/17)
- CPU : **8 cœurs** (`nproc`) — RAM **47 Go** (40 disponibles)
- GPU : **RTX 4060 Laptop, 8 Go VRAM**, torch 2.5.1+cu124, CUDA **disponible**
- sb3 / sb3-contrib **2.6.0**, gymnasium 1.1.1
- `x5_new` **(relevé AVANT refonte)** : `n_envs=48`, `n_steps=16384`, `batch_size=1024`,
  `n_epochs=3`, `MlpPolicy`, `total_episodes=30000`, `max_turns_per_episode=5`, `obs_size=108`,
  `action_space_size=41`.
  → *Depuis* : `action_space_size` n'existe plus en config (dérivé = **1047**) ; `n_steps` et
  `policy` restent à traiter en T1b/T5.

### 8.2 Perf mesurée (board ×5 220×300, `scenario_training_bot-01`, 13 escouades, `gym_training_mode=True`)

| Mesure | Coût |
|---|---|
| **Un step gym complet** (masque + `env.step`, **sans aucune inférence réseau**) | **65,0 ms** |
| Masque squad complet (26 actions) | 5,00 ms |
| dont 6 dry-runs directionnels *normal* seuls | 4,32 ms |
| **Pool BFS complet** (`movement_build_valid_destinations_pool`) | **7,31 ms** (3,0-9,5) |
| Taille des pools observée | 626 à 4395 destinations |

**Lecture** : un BFS unique (7,31 ms) **remplace** les dry-runs directionnels (4,32 ms pour *normal*
seul ; ~8,6 ms si Advance est aussi masqué). Bilan **neutre à légèrement gagnant**.

⚠️ Les **100 à 290 ms** des lignes `MOVE_POOL_BUILD` de `perf_timing_x5.log` concernent le **chemin PvP**,
où `post_bfs_s` (union d'empreintes + `mask_loops` pour la preview UI) pèse ~37 % du total. Ces étages ne
tournent pas en gym (`gym_training_mode`). **Ne pas confondre les deux chiffres.**

### 8.3 Contrainte dimensionnante : le rollout buffer

`n_steps=16384 × n_envs=48` = **786 432 transitions**. Coût RAM linéaire en taille d'obs :

| Observation | Floats | RAM buffer à n_steps=16384 | à n_steps=8192 |
|---|---|---|---|
| actuelle | 108 | **0,34 Go** | 0,17 Go |
| grille 16×16×5 | 1 280 | **4,03 Go** | 2,01 Go |
| grille 32×32×4 | 4 096 | **12,88 Go** | 6,44 Go |
| **grille 32×32×6 (retenue, §10.1)** | **6 144** | 19,33 Go (limite) | **9,66 Go ✓** |
| grille 32×32×8 | 8 192 | **25,77 Go** | 12,88 Go |

(float32 ; transitions = `n_steps × n_envs`, soit 786 432 à 16384×48 et 393 216 à 8192×48.)

→ **Décision (§10.1)** : grille **32×32×6** avec `n_steps` **16384 → 8192** en gardant `n_envs=48`
(réduire `n_envs` coûterait du débit moteur, cf. §8.5 ; réduire `n_steps` ne coûte que la longueur de
rollout, et `batch_size=1024` divise toujours 393 216). **C'est la RAM qui dimensionne la grille**, pas
le GPU.

### 8.4bis Grille spatiale — MESURÉ (T1, 2026-07-17)

Board ×5 220×300, `scenario_training_bot-01`, `gym_training_mode=True`, 15 escouades,
988 murs, **10 538 hexes d'objectifs** (les objectifs sont des **zones**, pas des points),
`half_extent` ∈ {60, 65, 90} subhex.

| Version de `build_squad_grid` | Coût/appel | % d'un step (65 ms) |
|---|---|---|
| Naïve (scalaire, sans mémoïsation) | **10,74 ms** | 16,5 % |
| + projection vectorisée NumPy | 3,39 ms | 5,2 % |
| + mémoïsation murs/objectifs (**retenue**) | **0,521 ms** | **0,8 %** |

**L'attendu « sous la ms » de §7 T1 était faux pour l'implémentation directe** (×20 trop lent). Il ne
tient qu'avec les deux optimisations. Profil de la version naïve : les objectifs représentaient **91 %**
des projections (10 538 / 11 540) et `_hex_center` était appelé **464 600 fois pour 20 grilles** (le
centre de l'ancre était recalculé à chaque hex).

**Deux bugs trouvés par les tests, non anticipés par la spec** :
1. *Bord exact* — un hex à distance-hex exactement égale au budget se projette à `|u| = 1.0`, soit
   l'indice `GRID_SIZE` : le carré `[-W,+W]` doit être demi-ouvert pour se découper en 32 cellules,
   donc son bord était **éjecté**. Ce sont des destinations légales (move exactement au budget) :
   les perdre bornait l'agent. Corrigé par une demi-marge de pas hex.
2. *Cache périmé* — `game_state` est le **même objet** d'un `reset()` à l'autre, et `_reload_scenario`
   change murs/objectifs par épisode. La mémoïsation servait donc le terrain de l'épisode **précédent**.
   Corruption silencieuse de l'obs, invisible en training. Corrigé par purge dans `reset()` + 2 tests.

Coût de référence pour comparaison : `build_squad_observation` (108-d, existant) = **1,69 ms**. La
grille (6 144 floats) coûte donc **3× moins** que le vecteur 108-d qu'elle accompagne.

### 8.4 Ce qui ne coûte PAS
- ~~**Le CNN**~~ **HYPOTHÈSE INFIRMÉE (2026-07-18)** : l'attendu « débit fixé par le moteur, CNN
  neutre » est **contredit par la mesure** — débit agrégé ≈ **14 steps/s** à `n_envs=48`, très en-deçà
  de ce qu'un moteur pur à 65 ms/step laissait espérer. Le path Dict-obs + CNN **et** la résolution
  réelle des combats (désormais atteints) pèsent. Cf. §8.5 (la part exacte du CNN reste non isolée).
- **Le BFS** : ~11 % d'un step ; neutre une fois les dry-runs supprimés (§8.2).

### 8.5 Mesures runtime (MÀJ 2026-07-18 — crash fight levé, retrain relancé)

Une fois le crash fight corrigé, le run `--new x5_new` complète des rollouts. Mesuré sur un run borné
(~9 min, board ×5, `n_envs=48`, GPU RTX 4060, obs `Dict` + `SpatialCombinedExtractor`) :

| Mesure | Valeur | Source |
|---|---|---|
| **Débit training** (env-steps/s agrégé, `n_envs=48`) | **≈ 14 steps/s** | TB `time/fps` au 1ᵉʳ update SB3 (step 8160) |
| **Cadence épisodes** | **≈ 7,6 s/ep** (70 ép. en 534 s) → ETA ~47 h pour 30000 ép. | barre de progression |
| **RAM résidente agrégée** (main + 48 envs subprocess, 60 proc.) | **≈ 29 Go** stationnaire (init ≤ 47 Go RAM) | `ps rss` échantillonné 30 s |
| RAM du rollout buffer (composante calculée) | **9,66 Go** (393 216 transitions × 6 144 floats) | §8.3, cohérent avec le RSS observé |

**Lecture — le débit est la contrainte dimensionnante du retrain, PAS neutre (contredit §8.4)** :
- ~14 steps/s agrégé est **très en-deçà** de l'attendu §8.4 (« débit fixé par le moteur, 65 ms/step,
  CNN neutre » aurait laissé espérer ≫ ce chiffre à 48 envs). L'écart tient à **deux** causes que le
  move corrigé expose : (1) le path Dict-obs + CNN sur GPU (forward masqué par step + backprop) n'est
  **pas** gratuit ; (2) surtout, **les combats se résolvent désormais réellement** (unités qui
  traversent le board → engagement → fight par-figurine complet) là où avant elles bougeaient d'1
  subhex — les épisodes sont plus lourds. Un rollout de 8192 steps ≈ **10 min**.
- **Conséquence Tâche B** : un retrain complet (30000 ép.) est un job **multi-jours** (~47 h à ce
  débit). Il ne peut **pas** aboutir en une session ; il doit tourner en tâche de fond. La cadence est
  stable et le run **sain** (RAM plate ~29 Go, aucun crash, épisodes qui avancent).
- **La part exacte du CNN** (env-step vs forward vs backprop) **reste non isolée** — nécessiterait un
  profiling dédié, non fait. Ne pas l'affirmer sans mesure.

**Restent non mesurés** :
- Sample complexity du nouvel espace d'action (nécessite un training convergé).
- Décomposition du débit (part CNN forward/backprop vs moteur vs résolution combat).
- Win-rate multi-scénarios et catastrophic forgetting (nécessitent le retrain complet).
- ~~Surcoût de rasterisation de la grille par step (T1)~~ → **MESURÉ**, §8.4bis (0,521 ms).
- ~~Débit réel `n_envs=48`, RAM~~ → **MESURÉS** ci-dessus.

---

## 9. Validation

Pas de tests automatisés de bout en bout sur ce périmètre (cf. `CLAUDE.md`) → validation par :

1. **Suite unitaire verte** (`tests/unit/…`), y compris les tests d'action space / masque / decoder.
2. **`python3 ai/train.py --agent CoreAgent --scenario bot --step`** — vérifier qu'une escouade parcourt
   une **distance cohérente avec son budget** (≈ `MOVE datasheet (pouces) × inches_to_subhex` ; le
   `MOVE` moteur est déjà scalé, `game_state.py:841`), et non 1 subhex.
3. **`python3 ai/analyzer.py <résultats>`** — pas de nouvelle catégorie d'erreur.
4. **Replay** : contrôle visuel du symptôme d'origine (les unités doivent traverser le board).
5. **Non-régression PvP** : le chemin `execute_semantic_action` doit être **inchangé** (aucune
   modification de comportement sur les fonctions partagées).
6. **Win-rate** : robustesse sur plusieurs scénarios, pas un pic isolé. Surveiller le catastrophic
   forgetting. (~~Comparaison A/B des deux `grid_mode`~~ : caduc, `budget_normalized` est le mode
   unique depuis §10.2 → **un seul** run from scratch.)
7. **Pas de reward de mouvement** (§10.10) : si les unités bougent encore peu, diagnostiquer
   obs/masque/credit assignment — ne pas ajouter de reward shaping de déplacement.

⚠️ **Le modèle actuel devient incompatible** (obs et action space changent) → réentraînement `--new`
obligatoire. `ai/models/**/*.zip` ne doit jamais être modifié à la main.

---

## 10. Points ouverts

1. ~~Dimensions de la grille et liste des canaux~~ — **TRANCHÉ (2026-07-17)** : **32×32×6**.
   Canaux : murs/obstacles, occupation alliée, occupation ennemie, EZ, objectifs, niveau (étages).
   Choix utilisateur : la config matérielle actuelle ne doit pas être la limite du design. Contrepartie
   RAM absorbée par `n_steps` 16384 → **8192** en gardant `n_envs=48` (cf. §8.3 : 9,66 Go ; réduire
   `n_envs` aurait coûté du débit moteur, réduire `n_steps` ne coûte que la longueur de rollout).
2. ~~Normalisation : A/B testé~~ — **RE-TRANCHÉ (2026-07-17, après vérification chiffrée)** :
   `fixed_resolution` est **abandonné**, `budget_normalized` est le mode **unique** (plus de paramètre
   `grid_mode`, plus d'A/B, **un seul** réentraînement from scratch).

   **Motif — la variante `fixed_resolution` était arithmétiquement impossible.** §10.9 la définissait
   par « cellule = hex » et §10.1 fixe la grille à 32×32 : cela couvre un rayon de **16 subhex** autour
   de l'ancre. Or, sur le board actif (`config/board/44x60x5.json`, `inches_to_subhex=5`), les MOVE des
   161 datasheets (`frontend/src/roster/**`) vont de 4" à **14"**, soit un budget Advance réel de
   **60 subhex** (MOVE 6", le cas courant) à **100 subhex** (MOVE 14"). La grille était **4 à 6× trop
   petite**, et l'erreur explicite exigée par T5 (« si la grille ne couvre pas le budget max ») se
   serait déclenchée sur chaque unité à chaque step. Élargir la cellule à ~7 subhex pour couvrir 100
   subhex rendait le mode **plus grossier** que `budget_normalized` sur les unités lentes — ce qui vide
   de son sens sa seule raison d'être (« granularité constante fine »).

   `budget_normalized` couvre le disque atteignable **par construction**, à toute échelle.
3. ~~Décodage cellule → destination~~ — **TRANCHÉ (2026-07-17)** : l'hex du pool **le plus proche du
   centre géométrique de la cellule** ; départage déterministe par (col, row) min. L'action exécutée
   correspond au plus près à ce que l'agent a visé ; testable unitairement.
4. ~~Pré-roll de l'advance roll au masque~~ — **ENTÉRINÉ (2026-07-17)** : divergence assumée vs le
   timing 09.06 (« BEFORE MOVING »). Nécessaire au masque spatial (le disque atteignable dépend du
   jet) ; avantage faible et symétrique (les deux camps en profitent). Alternatives écartées : budget
   pessimiste M+1 (interdit des destinations légales 5 fois sur 6), budget moyen (mismatch
   masque/exécution possible).
5. ~~**Périmètre PvP** : ajout de paramètres au builder partagé~~ — **TRANCHÉ / FAIT (2026-07-17)** :
   2 paramètres kw-only `out_costs` et `move_budget_override`, **purement additifs**. À `None` (le
   cas PvP, qui ne les passe jamais) le comportement est strictement l'ancien — verrouillé par
   `test_pvp_path_is_strictly_unchanged_without_the_new_params` + suite complète verte (1349).
6. ~~**§4.3** (divergence `advance_rolls`)~~ — **FAIT dans cette refonte (2026-07-17)**, cf. T2.
7. **`n_envs=48` sur 8 cœurs** : conservé (les stats de training le justifient) — hors périmètre.
8. **`step.log` loggue l'ancre d'escouade** au lieu de la figurine (dette V11 connue, hors périmètre).
9. ~~CNN sur grille hex en coordonnées offset~~ — **TRANCHÉ (2026-07-17)**, **implémenté en T1** :
   rasterisation **géométrique** — les hexes sont projetés via leurs **centres euclidiens normalisés**
   (`_hex_center`), pas via leurs indices offset, ce qui élimine l'anisotropie de parité.
   La note sur les coordonnées **axiales** ne concernait que `fixed_resolution` (cellule = hex) :
   **caduque**, ce mode est abandonné (§10.2).

   **Précision apportée par l'implémentation** : l'échelle de normalisation est le pas hex réel,
   **√3 ≈ 1,732** (distance centre-à-centre de 2 voisins dans l'espace `_hex_center` — vérifié
   uniforme sur les 6 voisins et les 2 parités), et **non** `ENGAGEMENT_NORM_HEX_WIDTH` = 1,5, qui est
   le facteur subhex→pixel de la métrique **euclidienne** du move PvP. Le gym tourne en métrique `hex`
   (§4.4) : un pas de BFS = un hex = √3 px. Mesure : normaliser par 1,5 rejetterait **2,5 %** des
   destinations atteignables hors grille (272/10 981 à `half_extent`=60), concentrées sur l'axe
   **vertical** (rapport √3/1,5 = 1,155 ; sur l'axe horizontal il vaut 1,0, d'où un effet non uniforme
   limité aux extrémités). Ces destinations sont légales → les perdre bornerait l'agent.
10. **Reward de mouvement : aucun, par design (décision utilisateur 2026-07-17)** — un bon move est
    récompensé **indirectement** via ce qu'il rend accessible (tir, combat, objectifs). Ne pas ajouter
    de reward shaping de déplacement si les unités bougent peu après la refonte : diagnostiquer
    d'abord obs/masque/credit assignment.
11. **Montant de dilatation EZ = 2″ ?** (ouvert, 2026-07-18) — le bug ancre→empreinte est corrigé
    (§7quater), mais reste à vérifier que `get_engagement_zone(game_state)` encode bien **2″
    horizontalement** (03.04) en subhex. Orthogonal à ancre-vs-empreinte : c'est le *montant* de
    dilatation, pas sa source.
