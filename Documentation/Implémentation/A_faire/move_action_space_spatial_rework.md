# Refonte de l'action space de mouvement — obs spatiale + tête spatiale

> **Périmètre** : la façon dont l'agent RL **choisit une destination** en phase move (`squad_normal_move`,
> `squad_advance`, `squad_fall_back`), l'**observation** sur laquelle il fonde ce choix, et le masque
> associé. Ne concerne PAS le PvP (chemin `execute_semantic_action`), qui n'est touché qu'au niveau des
> fonctions partagées, à comportement strictement inchangé.
>
> **Principe** : le moteur reste la source unique des règles (pool BFS). Aucune règle de mouvement n'est
> réimplémentée côté IA. Aucun fallback, aucune valeur par défaut masquant une erreur.

> **Statut (2026-07-17)** : investigation terminée, root cause établie et prouvée, design arbitré
> (refonte validée par l'utilisateur). **Aucun code modifié à ce jour.** Reste : implémentation (§7),
> validation (§9).
>
> **Commit de référence des numéros de ligne : `7fc55b66`.** Les références citent fonction + ligne ;
> en cas de dérive, la fonction fait foi.

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

### 4.5 L'action space réel est 41, pas 26

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
  objectifs, niveau (étages). Deux modes de mapping grille↔hex, A/B testés (§10.2) :
  `budget_normalized` (la grille couvre toujours le disque atteignable, invariance à l'échelle) et
  `fixed_resolution` (granularité constante en subhex).
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

### T1 — Observation spatiale
- `engine/observation_builder.py` : nouvelle grille égocentrique **32×32×6** ; canaux
  murs / alliés / ennemis / EZ / objectifs / niveau. Obs devient un `Dict` (`{"vec": …, "grid": …}`).
- Mapping grille↔hex paramétré par `grid_mode` (§10.2) ; rasterisation **géométrique** via les centres
  euclidiens normalisés des hexes, pas leurs indices offset (§10.9).
- Rasterisation depuis les caches existants (`wall_hexes`, `build_occupied_positions_set`,
  `enemy_adjacent_hexes_player_*`) — **ne pas recalculer** ce qui est déjà en cache.
- Mesurer le surcoût par step (attendu : « sous la ms » face aux 65 ms — **à confirmer**, §8).

### T2 — Espace d'action + masque
- `engine/phase_handlers/shared_utils.py` : constantes `SQUAD_ACTION_*` ; masque du type d'action ;
  **projection du pool BFS sur la grille** (source du masque spatial).
- `engine/macro_intents.py` : **miroir exact obligatoire** (cf. §4.5).
- `engine/w40k_core.py:629` : `action_space` (`Discrete` → structure spatiale).
- Optimisation du masque : Normal et Fall Back s'excluent (`in_er`) et le pool Advance **contient** le
  pool Normal (budget supérieur) → **1 seul BFS au budget Advance** suffit, en conservant le **coût
  géodésique** de chaque cellule : c'est lui qui sert à l'inférence du type (coût ≤ M → `normal`,
  coût > M → `advance`, cf. §6.2). Plus aucun masque de type de move : une cellule = un move légal.

### T3 — Décodage et exécution
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

### T4 — Propagation
`ai/env_wrappers.py`, `ai/train.py`, `ai/bot_evaluation.py`, `ai/evaluation_bots.py`,
`engine/pve_controller.py` : tout site qui manipule une action entière ou un masque plat.

### T5 — Configuration
- `config/agents/CoreAgent/CoreAgent_training_config.json` : `obs_size`, `action_space_size`,
  `policy` (`MlpPolicy` → `MultiInputPolicy`), `net_arch`, grille 32×32×6, `grid_mode` (§10.2),
  **`n_steps` 16384 → 8192** (§8.3). Mettre à jour les `justification` (structure exacte).
- Erreur explicite si la grille ne couvre pas le budget max des unités du scénario (pas de troncature
  silencieuse).

### T6 — Réentraînement et validation (§9)
Deux runs from scratch (A/B `grid_mode`, §10.2) : `budget_normalized` puis `fixed_resolution`,
comparaison win-rate multi-scénarios. Le mode gagnant devient le défaut documenté.

### Fichiers impactés (récapitulatif)
```
engine/observation_builder.py          engine/action_decoder.py
engine/phase_handlers/shared_utils.py  engine/phase_handlers/movement_handlers.py
engine/w40k_core.py                    engine/macro_intents.py
engine/pve_controller.py               ai/env_wrappers.py
ai/train.py                            ai/bot_evaluation.py
ai/evaluation_bots.py                  config/agents/CoreAgent/CoreAgent_training_config.json
tests/unit/…                           (+ ai/analyzer*.py si l'action space est reflété)
```

---

## 8. Mesures et contraintes chiffrées

### 8.1 Matériel et configuration (relevés le 2026-07-16/17)
- CPU : **8 cœurs** (`nproc`) — RAM **47 Go** (40 disponibles)
- GPU : **RTX 4060 Laptop, 8 Go VRAM**, torch 2.5.1+cu124, CUDA **disponible**
- sb3 / sb3-contrib **2.6.0**, gymnasium 1.1.1
- `x5_new` : `n_envs=48`, `n_steps=16384`, `batch_size=1024`, `n_epochs=3`, `MlpPolicy`,
  `total_episodes=30000`, `max_turns_per_episode=5`, `obs_size=108`, `action_space_size=41`

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

### 8.4 Ce qui ne coûte PAS
- **Le CNN** (attendu, à confirmer — §8.5) : la policy tourne sur GPU ; le débit est fixé par le
  **moteur** (65 ms/step de calcul moteur pur, hors réseau). Passer de `MlpPolicy` à un CNN ne devrait
  pas déplacer la durée d'un entraînement — **hypothèse non mesurée**, comme le débit réel (§8.5).
- **Le BFS** : ~11 % d'un step ; neutre une fois les dry-runs supprimés (§8.2).

### 8.5 Points non mesurés (à ne pas affirmer sans mesure)
- **Débit réel du training** (steps/s avec `n_envs=48`). Un calcul « 8 cœurs ÷ 65 ms » suppose un moteur
  purement CPU-bound et parfaitement parallèle — hypothèse **non vérifiée**, et les statistiques de
  training de l'utilisateur indiquent que `n_envs=48` sur 8 cœurs est **bénéfique** (IPC, sérialisation
  et amortissement de l'inférence en batchs ne sont pas du CPU-bound). **Se fier aux stats réelles.**
- Surcoût de rasterisation de la grille par step (T1).
- Sample complexity du nouvel espace d'action.
- Coût d'inférence + backprop du CNN sur GPU (l'affirmation « neutre » de §8.4 est un attendu, pas une
  mesure).

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
   forgetting. Comparaison A/B des deux `grid_mode` (§10.2) sur les mêmes scénarios.
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
2. **Normalisation : A/B testé** — **TRANCHÉ (2026-07-17)** : le mapping grille↔hex devient un
   paramètre de config (`grid_mode: budget_normalized | fixed_resolution`), le reste du pipeline
   (canaux, masque, decoder) est identique. Coût réel : **2 réentraînements from scratch** + comparaison
   win-rate (§9.6). `budget_normalized` = invariance à l'échelle mais granularité variable
   Normal/Advance ; `fixed_resolution` = granularité constante mais grille dimensionnée sur le budget
   max du scénario (erreur explicite si dépassement, cf. T5).
3. ~~Décodage cellule → destination~~ — **TRANCHÉ (2026-07-17)** : l'hex du pool **le plus proche du
   centre géométrique de la cellule** ; départage déterministe par (col, row) min. L'action exécutée
   correspond au plus près à ce que l'agent a visé ; testable unitairement.
4. ~~Pré-roll de l'advance roll au masque~~ — **ENTÉRINÉ (2026-07-17)** : divergence assumée vs le
   timing 09.06 (« BEFORE MOVING »). Nécessaire au masque spatial (le disque atteignable dépend du
   jet) ; avantage faible et symétrique (les deux camps en profitent). Alternatives écartées : budget
   pessimiste M+1 (interdit des destinations légales 5 fois sur 6), budget moyen (mismatch
   masque/exécution possible).
5. **Périmètre PvP** : ajout de paramètres au builder partagé — à valider avant implémentation (§7 T3).
6. **§4.3** (divergence `advance_rolls`) : corriger dans cette refonte ou en préalable isolé ?
7. **`n_envs=48` sur 8 cœurs** : conservé (les stats de training le justifient) — hors périmètre.
8. **`step.log` loggue l'ancre d'escouade** au lieu de la figurine (dette V11 connue, hors périmètre).
9. ~~CNN sur grille hex en coordonnées offset~~ — **TRANCHÉ (2026-07-17)** : rasterisation
   **géométrique** — les hexes sont projetés dans la grille via leurs **centres euclidiens normalisés**
   (pas via leurs indices offset), ce qui élimine l'anisotropie de parité pour le mode
   `budget_normalized`. Pour le mode `fixed_resolution` (cellule = hex), utiliser des coordonnées
   **axiales** (les 6 voisins hex deviennent un motif constant du voisinage 3×3, sans trous mémoire —
   préférable au doubled-height qui double la hauteur de grille).
10. **Reward de mouvement : aucun, par design (décision utilisateur 2026-07-17)** — un bon move est
    récompensé **indirectement** via ce qu'il rend accessible (tir, combat, objectifs). Ne pas ajouter
    de reward shaping de déplacement si les unités bougent peu après la refonte : diagnostiquer
    d'abord obs/masque/credit assignment.
