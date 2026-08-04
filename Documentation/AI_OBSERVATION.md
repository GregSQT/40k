# AI_OBSERVATION.md — ce que l'agent observe

Référence canonique de l'observation de l'agent : **le pipeline SQUAD en tenseurs d'entités**,
le seul sur lequel l'agent s'entraîne.

> **Ce document ne décrit QUE le code actuel.** Le pipeline mono-figurine (`obs_size = 359`,
> vecteur plat d'offsets `obs[N]`) a été déplacé dans
> **[`AI_OBSERVATION_Legacy.md`](AI_OBSERVATION_Legacy.md)** le 2026-07-28, puis **SUPPRIMÉ du
> code le même jour** : `build_observation`, `build_observation_for_unit`, leurs 33 méthodes
> d'encodage et la constante `PHASE2_OBS_SIZE` n'existent plus. Il vivait ici sous un bandeau
> d'avertissement, et induisait quand même en erreur à chaque lecture : ses offsets, ses
> « 12 unit-rule flags » et ses features calculées (`ranged_favorite_target`,
> `melee_favorite_target`…) n'existent plus. Le seul pipeline d'observation est celui décrit
> ci-dessous — le PvE y a été migré (`pve_controller.make_ai_decision`).
>
> **Version** : 3.0 — tenseurs d'entités (V11 §0.30 T-D), complétée par V11 §0.31.
> **Pipeline de training/évaluation** : `AI_TRAINING.md` (CLI, callbacks, évaluation contre bots).

**Source unique du contrat** : l'en-tête « OBSERVATION SQUAD — TENSEURS D'ENTITÉS » de
[`engine/observation_builder.py`](../engine/observation_builder.py) et le schéma
[`engine/observation_entities.py`](../engine/observation_entities.py). Ce document en donne la
lecture, jamais une copie de chiffres qui dériverait.

**L'observation n'est plus un vecteur plat.** Elle est un `Dict` de tenseurs :

| Clé | Forme | Contenu |
|---|---|---|
| `global_cont` / `global_bin` | (11,) / (27,) | ce qui n'appartient à aucune unité : tour, pas d'épisode, points de mission des deux camps, force d'usure, **distance à chacun des 5 objectifs** ; mon tour, **phase en one-hot de 6 bits**, contrôle + présence des 5 objectifs, **direction (cos/sin) vers chacun d'eux**. Ces distances/directions — comme les `col_rel`/`row_rel` des entités — sont mesurées depuis le **centroïde de l'escouade active**, ou depuis l'**ancre de sa zone de déploiement** tant qu'elle n'est pas posée (même repère que la grille, V11 §0.40 point 4). Une entité pas encore posée n'a **aucune** position relative ni **aucune relation géométrique** : `col_rel`/`row_rel`, `edge_distance`, `engaged`, `los_can_see`, `cover_vs_observer`, `n_fight_eligible`, `n_in_enemy_ez`, `n_models_engaging` sont nuls — règle 03.04, l'engagement range est une aire **du champ de bataille** (V11 §0.40 point 5) — et le bit `deploy_not_on_board` le dit. `coherent` fait exception : 03.03 ne teste la cohérence que « if that unit is on the battlefield » |
| `allies_cont` / `allies_bin` | (8, 19) / (8, 33) | **ligne 0 = l'unité ACTIVE**, lignes suivantes = mes autres escouades. Les 32 drapeaux incluent les **13 règles d'unité en vigueur** (19.04) et, pour les ennemis seulement, `los_can_see`, `cover_vs_observer` et `charge_reachable_max_roll` |
| `allies_wpn_cont` / `_bin` | (8, 20, 13) / (8, 20, 18) | profils d'armes par unité — **10 de tir puis 10 de mêlée**, avec porteurs vivants et bits/params de règles |
| `allies_types_cont` / `_bin` | (8, 6, 5) / (8, 6, 5) | types de figurines : profil défensif, rôle d'allocation (règle 19), effectif du type |
| `enemies_*` | idem avec **20 slots** | **ordre CONTRACTUEL = slots d'action de tir** (`get_enemy_slot_mapping`) |
| `self_models_cont` / `_bin` | (20, 2) / (20, 4) | ce qui est irréductiblement individuel : position relative, éligibilité au combat, engagement, **bit de présence** |
| `grid` | (9, 32, 32) | grille égocentrique : murs, **autres** escouades amies, ennemis, EZ, objectifs, niveau, couvert, **l'escouade active seule** (§0.32 T-L), **coût géodésique du pool de move** — encodé avec la frontière normal/advance à **0,5 exactement** (§0.32 T-K) ; escouade **engagée** : tout move est un Fall Back qui coûte le tir → toutes les cellules peintes sont **au-dessus de 0,5** (§0.37). **Centre de la fenêtre** (`ObservationBuilder.squad_grid_anchor`) : l'escouade active — sauf si elle n'est **pas encore posée** (`deployed_on_turn is None`, phase de déploiement), auquel cas c'est un hex de **sa zone de déploiement** ; avant V11 §0.40 la fenêtre était centrée sur la sentinelle `(-1,-1)`, donc sur une autre région du plateau |

### Structure Overview

Tailles **calculées, pas recopiées** : la somme des clés vaut `obs_size`, et
`tests/unit/engine/test_squad_obs_structure_doc.py` échoue si ce bloc dérive du schéma.

```
┌────────────────────────────────────────────────────────────────────────┐
│  OBSERVATION SQUAD — Dict de TENSEURS D'ENTITÉS  (20 780 scalaires)    │
├────────────────────────────────────────────────────────────────────────┤
│  CONTEXTE GLOBAL                                                       │
│    global_cont            (11,)                =      11               │
│    global_bin             (27,)                =      27               │
│                                                                        │
│  MES ESCOUADES — ligne 0 = l'unité ACTIVE          K_ALLY_SLOTS = 8    │
│    allies_cont            (8, 19)              =     152               │
│    allies_bin             (8, 33)              =     264               │
│    allies_wpn_cont        (8, 20, 13)          =   2 080               │
│    allies_wpn_bin         (8, 20, 18)          =   2 880               │
│    allies_types_cont      (8, 6, 5)            =     240               │
│    allies_types_bin       (8, 6, 5)            =     240               │
│                                                                        │
│  ESCOUADES ENNEMIES — ordre = slots d'action     K_ENEMY_SLOTS = 20    │
│    enemies_cont           (20, 19)             =     380               │
│    enemies_bin            (20, 33)             =     660               │
│    enemies_wpn_cont       (20, 20, 13)         =   5 200               │
│    enemies_wpn_bin        (20, 20, 18)         =   7 200               │
│    enemies_types_cont     (20, 6, 5)           =     600               │
│    enemies_types_bin      (20, 6, 5)           =     600               │
│                                                                        │
│  MES FIGURINES (individuel)                        SQUAD_TOP_K = 20    │
│    self_models_cont       (20, 2)              =      40               │
│    self_models_bin        (20, 3)              =      60               │
│                                                                        │
│  DÉCISION AGENT — candidats de CHOICE_i        MAX_DECISION_OPTIONS = 6│
│    decision_ctx_bin       (2,)                 =       2               │
│    decision_options_bin   (6, 14)              =      84               │
│                                                                        │
│  DÉPLOIEMENT — candidats des actions 4-8         N_DEPLOY_SLOTS = 5    │
│    deploy_cand_cont       (5, 8)               =      40               │
│    deploy_cand_bin        (5, 4)               =      20               │
├────────────────────────────────────────────────────────────────────────┤
│  TOTAL vectoriel (= obs_size)                      20 780              │
│  + grid  (9, 32, 32) = 9 216, fournie À PART (non comptée)             │
└────────────────────────────────────────────────────────────────────────┘

Coût d'UNE entité = 19 + 33 (unité) + 20 × (13 + 18) (armes) + 6 × (5 + 5) (types) = 732
   → le bloc ARMES fait 86 % du vecteur. C'est le seul bloc mémoïsé.
```

### Section Breakdown

Toutes les dimensions, dans l'ordre d'émission, avec pour chacune : **la clé du `Dict`** qui la
porte, son **index dans cette clé**, son nom et sa plage. Le titre de chaque bloc indique **qui le
normalise** (`VecNormalize` / `EntityRunningNorm` / jamais).

`[s]` = slot d'entité (0..K−1 ; pour `allies_*`, **0 = l'unité ACTIVE**) · `[w]` = slot d'arme
(0..9 = tir, 10..19 = mêlée) · `[t]` = slot de type de figurine · `[m]` = slot de figurine.
Une unité AMIE et une unité ENNEMIE ont **exactement** les mêmes colonnes : `[ACTIVE seule]` et
`[ENNEMIS seuls]` marquent les features à zéro ailleurs, avec `is_active` / `is_ally` pour masque.

⚠️ **Ne pas recopier ces index dans du code.** Ils changent à chaque évolution du schéma —
utiliser `global_cont_index("nom")`, `global_bin_index("nom")`, `unit_cont_index("nom")`,
`unit_bin_index("nom")`. Les index ci-dessous sont vérifiés par
`tests/unit/engine/test_squad_obs_structure_doc.py`, qui échoue s'ils dérivent du schéma.

#### `global_cont` — contexte continu  ·  VecNormalize ✓

```python
global_cont[0]     = turn                                   # brut (numero de tour)
global_cont[1]     = episode_steps                          # brut (compteur de pas)
global_cont[2]     = my_victory_points                      # brut (VP)
global_cont[3]     = enemy_victory_points                   # brut (VP)
global_cont[4]     = my_value_ratio                         # 0.0-1.0 (VALUE vivante / depart)
global_cont[5]     = enemy_value_ratio                      # 0.0-1.0 (VALUE vivante / depart)
global_cont[6]     = objective_distance_0                   # subhex, hex le plus proche de l'objectif 0
global_cont[7]     = objective_distance_1                   # subhex, hex le plus proche de l'objectif 1
global_cont[8]     = objective_distance_2                   # subhex, hex le plus proche de l'objectif 2
global_cont[9]     = objective_distance_3                   # subhex, hex le plus proche de l'objectif 3
global_cont[10]    = objective_distance_4                   # subhex, hex le plus proche de l'objectif 4
```

#### `global_bin` — contexte discret  ·  jamais normalise

```python
global_bin[0]      = is_my_turn                             # 0.0 / 1.0
global_bin[1]      = phase_deployment                       # 0.0 / 1.0 — ONE-HOT de phase (6 bits, ordre GAME_PHASES)
global_bin[2]      = phase_command                          # 0.0 / 1.0
global_bin[3]      = phase_move                             # 0.0 / 1.0
global_bin[4]      = phase_shoot                            # 0.0 / 1.0
global_bin[5]      = phase_charge                           # 0.0 / 1.0
global_bin[6]      = phase_fight                            # 0.0 / 1.0
global_bin[7]      = objective_control_0                    # -1.0 / 0.0 / +1.0 (ennemi / conteste-vide / moi)
global_bin[8]      = objective_control_1                    # -1.0 / 0.0 / +1.0 (ennemi / conteste-vide / moi)
global_bin[9]      = objective_control_2                    # -1.0 / 0.0 / +1.0 (ennemi / conteste-vide / moi)
global_bin[10]     = objective_control_3                    # -1.0 / 0.0 / +1.0 (ennemi / conteste-vide / moi)
global_bin[11]     = objective_control_4                    # -1.0 / 0.0 / +1.0 (ennemi / conteste-vide / moi)
global_bin[12]     = objective_present_0                    # 0.0 / 1.0 (objectif present au scenario)
global_bin[13]     = objective_present_1                    # 0.0 / 1.0 (objectif present au scenario)
global_bin[14]     = objective_present_2                    # 0.0 / 1.0 (objectif present au scenario)
global_bin[15]     = objective_present_3                    # 0.0 / 1.0 (objectif present au scenario)
global_bin[16]     = objective_present_4                    # 0.0 / 1.0 (objectif present au scenario)
global_bin[17]     = objective_dir_cos_0                    # -1.0..1.0 (vecteur unitaire vers l'objectif)
global_bin[18]     = objective_dir_sin_0                    # -1.0..1.0
global_bin[19]     = objective_dir_cos_1                    # -1.0..1.0 (vecteur unitaire vers l'objectif)
global_bin[20]     = objective_dir_sin_1                    # -1.0..1.0
global_bin[21]     = objective_dir_cos_2                    # -1.0..1.0 (vecteur unitaire vers l'objectif)
global_bin[22]     = objective_dir_sin_2                    # -1.0..1.0
global_bin[23]     = objective_dir_cos_3                    # -1.0..1.0 (vecteur unitaire vers l'objectif)
global_bin[24]     = objective_dir_sin_3                    # -1.0..1.0
global_bin[25]     = objective_dir_cos_4                    # -1.0..1.0 (vecteur unitaire vers l'objectif)
global_bin[26]     = objective_dir_sin_4                    # -1.0..1.0
```

La phase est un **one-hot de 6 bits** depuis le 2026-07-28 (V11 §0.32 T-J). L'encodage ordinal
précédent (0 / .25 / .5 / .75 / 1) donnait la **même** valeur `0.0` à `deployment` et à `command`,
deux phases où les ids d'action 4–8 signifient l'un « slot de déploiement », l'autre « cellule de
move » — le seul indice restant était indirect. Une phase hors des 6 **lève** ; il n'y a plus de
`.get(…, 0.0)`.

#### `allies_cont[s]` / `enemies_cont[s]` — une unite, 19 features  ·  EntityRunningNorm

```python
[s][0]     = alive_models                           # brut (figurines vivantes)
[s][1]     = hp_total                               # brut (PV cumules)
[s][2]     = value_alive                            # brut (points, somme par figurine)
[s][3]     = oc_total                               # brut (OC cumule)
[s][4]     = model_count_ratio                      # 0.0-1.0 (vivantes / depart)
[s][5]     = wounded_hp_ratio                       # 0.0-1.0 (1.0 si aucune entamee)
[s][6]     = col_rel                                # projection _hex_center SIGNEE (fig la plus proche)
[s][7]     = row_rel                                # projection _hex_center SIGNEE (fig la plus proche)
[s][8]     = edge_distance                          # subhex, bord-a-bord [ENNEMIS/ALLIES non actifs]
[s][9]     = move                                   # brut (M de la datasheet)
[s][10]    = hp_max                                 # brut
[s][11]    = toughness                              # brut
[s][12]    = armor_save                             # brut (Sv)
[s][13]    = invul_save                             # brut (InSv, 0 = aucune)
[s][14]    = moved_max                              # subhex, distance de CHEMIN (max sur l'escouade)
[s][15]    = moved_sum                              # subhex, distance de CHEMIN (somme)
[s][16]    = n_fight_eligible                       # brut [ACTIVE seule]
[s][17]    = n_in_enemy_ez                          # brut [ACTIVE seule]
[s][18]    = n_models_engaging                      # brut [ENNEMIS seuls] — mes figurines
                                                    #   engagees avec CETTE cible (04.02).
                                                    #   Grandeur de PAIRE, comme los_can_see.
                                                    #   Support du choix de cible de melee
                                                    #   (V11 §9 P3-1) : combien d'attaques je
                                                    #   porte reellement contre elle.
```

#### `allies_bin[s]` / `enemies_bin[s]` — une unite, 33 drapeaux  ·  jamais normalise

```python
[s][0]     = is_ally                                # 0.0 / 1.0
[s][1]     = is_active                              # 0.0 / 1.0 — masque des features [ACTIVE seule]
[s][2]     = moved                                  # 0.0 / 1.0
[s][3]     = shot                                   # 0.0 / 1.0
[s][4]     = fought                                 # 0.0 / 1.0
[s][5]     = advanced                               # 0.0 / 1.0
[s][6]     = fled                                   # 0.0 / 1.0
[s][7]     = coherent                               # 0.0 / 1.0 (03.03)
[s][8]     = engaged                                # 0.0 / 1.0 (03.04)
[s][9]     = hidden                                 # 0.0 / 1.0 (13.09) [ACTIVE seule]
[s][10]    = gone_to_ground                         # 0.0 / 1.0 (13.5) [ACTIVE seule]
[s][11]    = in_cover                               # 0.0 / 1.0 (13.08 branche intrinseque) [ACTIVE seule]
[s][12]    = deploy_not_on_board                    # 0.0 / 1.0 — one-hot mise en place
[s][13]    = deploy_pre_battle                      # 0.0 / 1.0
[s][14]    = deploy_in_battle                       # 0.0 / 1.0
[s][15]    = deployed_this_turn                     # 0.0 / 1.0 (clause 2 de [HEAVY] 24.16)
[s][16]    = los_can_see                            # 0.0 / 1.0 (06.01) [ENNEMIS seuls]
[s][17]    = cover_vs_observer                      # 0.0 / 1.0 (13.08 EXACT, 2 branches) [ENNEMIS seuls]
[s][18]    = charge_reachable_max_roll              # 0.0 / 1.0 — un plan de charge legal existe au jet
                                                    #   MAXIMAL (11.02, 2D6 -> 12) [ENNEMIS seuls, phase
                                                    #   CHARGE seule ; masque = phase_charge]
[s][19]    = rule_charge_after_advance              # 0.0 / 1.0 — regle d'unite EN VIGUEUR (19.04)
[s][20]    = rule_charge_after_flee                 # 0.0 / 1.0 — regle d'unite EN VIGUEUR (19.04)
[s][21]    = rule_charge_impact                     # 0.0 / 1.0 — regle d'unite EN VIGUEUR (19.04)
[s][22]    = rule_closest_target_penetration        # 0.0 / 1.0 — regle d'unite EN VIGUEUR (19.04)
[s][23]    = rule_move_after_shooting               # 0.0 / 1.0 — regle d'unite EN VIGUEUR (19.04)
[s][24]    = rule_reactive_move                     # 0.0 / 1.0 — regle d'unite EN VIGUEUR (19.04)
[s][25]    = rule_reroll_1_save_fight               # 0.0 / 1.0 — regle d'unite EN VIGUEUR (19.04)
[s][26]    = rule_reroll_1_tohit_fight              # 0.0 / 1.0 — regle d'unite EN VIGUEUR (19.04)
[s][27]    = rule_reroll_1_towound                  # 0.0 / 1.0 — regle d'unite EN VIGUEUR (19.04)
[s][28]    = rule_reroll_charge                     # 0.0 / 1.0 — regle d'unite EN VIGUEUR (19.04)
[s][29]    = rule_reroll_towound_target_on_objective # 0.0 / 1.0 — regle d'unite EN VIGUEUR (19.04)
[s][30]    = rule_shoot_after_advance               # 0.0 / 1.0 — regle d'unite EN VIGUEUR (19.04)
[s][31]    = rule_shoot_after_flee                  # 0.0 / 1.0 — regle d'unite EN VIGUEUR (19.04)
[s][32]    = present                                # 0.0 / 1.0 — masque d'entite (0 = slot vide ou morte), DERNIER comme dans tous les registres (§0.37)
```

#### `*_wpn_cont[s][w]` — un profil d'arme, 13 continues  ·  EntityRunningNorm

```python
[s][w][0]     = NB                                     # brut (caracteristique)
[s][w][1]     = ATK                                    # brut (caracteristique)
[s][w][2]     = STR                                    # brut (caracteristique)
[s][w][3]     = AP                                     # brut (caracteristique)
[s][w][4]     = DMG                                    # brut (caracteristique)
[s][w][5]     = range                                  # subhex (portee)
[s][w][6]     = carriers                               # brut — porteurs VIVANTS du profil
[s][w][7]     = param_RAPID_FIRE                       # brut (0 = regle absente ; forme nue -> 0)
[s][w][8]     = param_SUSTAINED_HITS                   # brut (0 = regle absente ; forme nue -> 0)
[s][w][9]     = param_MELTA                            # brut (0 = regle absente ; forme nue -> 0)
[s][w][10]    = param_CLEAVE                           # brut (0 = regle absente ; forme nue -> 0)
[s][w][11]    = param_BLAST                            # brut (0 = regle absente ; forme nue -> 1)
[s][w][12]    = anti_threshold                         # brut (Y+ de [ANTI-X], 0 = aucune)
```

#### `*_wpn_bin[s][w]` — un profil d'arme, 18 drapeaux  ·  jamais normalise

```python
[s][w][0]     = rule_DEVASTATING_WOUNDS                # 0.0 / 1.0
[s][w][1]     = rule_LETHAL_HITS                       # 0.0 / 1.0
[s][w][2]     = rule_TORRENT                           # 0.0 / 1.0
[s][w][3]     = rule_TWIN_LINKED                       # 0.0 / 1.0
[s][w][4]     = rule_EXTRA_ATTACKS                     # 0.0 / 1.0
[s][w][5]     = rule_PRECISION                         # 0.0 / 1.0
[s][w][6]     = rule_PSYCHIC                           # 0.0 / 1.0
[s][w][7]     = rule_HAZARDOUS                         # 0.0 / 1.0
[s][w][8]     = rule_HEAVY                             # 0.0 / 1.0
[s][w][9]     = rule_IGNORES_COVER                     # 0.0 / 1.0
[s][w][10]    = rule_CLOSE_QUARTERS                    # 0.0 / 1.0
[s][w][11]    = rule_ASSAULT                           # 0.0 / 1.0
[s][w][12]    = anti_INFANTRY                          # 0.0 / 1.0 — one-hot du keyword cible par [ANTI-X]
[s][w][13]    = anti_VEHICLE                           # 0.0 / 1.0 — one-hot du keyword cible par [ANTI-X]
[s][w][14]    = anti_FLY                               # 0.0 / 1.0 — one-hot du keyword cible par [ANTI-X]
[s][w][15]    = anti_PSYKER                            # 0.0 / 1.0 — one-hot du keyword cible par [ANTI-X]
[s][w][16]    = anti_MONSTER                           # 0.0 / 1.0 — one-hot du keyword cible par [ANTI-X]
[s][w][17]    = mask                                   # 0.0 / 1.0 — 0 = slot d'arme vide
```

#### `*_types_cont[s][t]` — un type de figurine, 5 continues  ·  EntityRunningNorm

```python
[s][t][0]     = hp_max                                 # brut
[s][t][1]     = toughness                              # brut
[s][t][2]     = armor_save                             # brut (Sv)
[s][t][3]     = invul_save                             # brut (InSv, 0 = aucune)
[s][t][4]     = alive_count                            # brut (figurines de ce type)
```

#### `*_types_bin[s][t]` — un type de figurine, 5 drapeaux  ·  jamais normalise

```python
[s][t][0]     = role_special_weapon                    # 0.0 / 1.0 — one-hot role (regle 19)
[s][t][1]     = role_sergeant                          # 0.0 / 1.0
[s][t][2]     = role_support                           # 0.0 / 1.0
[s][t][3]     = role_leader                            # 0.0 / 1.0
[s][t][4]     = present                                # 0.0 / 1.0 — 0 = slot de type vide
```

#### `self_models_cont[m]` / `self_models_bin[m]` — mes figurines  ·  EntityRunningNorm / jamais normalise

```python
cont[m][0]     = col_rel                                # projection _hex_center SIGNEE (vs centroide arrondi)
cont[m][1]     = row_rel                                # projection _hex_center SIGNEE (vs centroide arrondi)
bin[m][0]      = fight_eligible                         # 0.0 / 1.0
bin[m][1]      = in_enemy_ez                            # 0.0 / 1.0
bin[m][2]      = present                                # 0.0 / 1.0 — masque du bloc (0 = slot vide)
```

**Le masque de ce bloc est le bit `present`**, comme pour les registres d'armes et de types
(§0.32 T-H, 2026-07-28). Il était auparavant **déduit** de la ligne entière
(`(|cont| + |bin|) > 0`), ce qui comptait **absente** une figurine posée sur le centroïde arrondi
et sans aucun drapeau : ligne entièrement nulle, donc exclue de l'agrégation ET du dénominateur de
`EntityRunningNorm`. La somme des bits `present` vaut désormais l'effectif observé.

**`col_rel` / `row_rel` sont exprimés dans la projection `_hex_center`** — ici comme dans
`allies_cont` / `enemies_cont`, et comme la grille égocentrique et les directions d'objectif
(§0.32 T-I). Il n'y a plus qu'**une** géométrie dans l'observation : en coordonnées offset, deux
voisins hexagonaux de parités de ligne différentes n'avaient pas la même norme. Le choix de la
figurine « la plus proche » d'une entité se fait dans le même repère, pour la même raison.

#### `decision_ctx_bin` / `decision_options_bin[c]` — décision agent  ·  jamais normalisé

Bloc du **mécanisme générique « décision agent »** (V11 §9.3, P2). Il décrit le point de choix sur
lequel le moteur s'est arrêté — l'exact miroir d'un `waiting_for_player` PvP — et **chaque
candidat** que les actions `CHOICE_0..5` (`macro_intents.CHOICE_SLOTS`) désignent.

```python
decision_ctx_bin[0]      = decision_pending                  # 0.0 / 1.0 — masque du bloc entier
decision_ctx_bin[1]      = decision_type_rule_choice         # 0.0 / 1.0 — one-hot du type

decision_options_bin[c][ 0] = grants_charge_after_advance                  # 0.0 / 1.0
decision_options_bin[c][ 1] = grants_charge_after_flee                     # 0.0 / 1.0
decision_options_bin[c][ 2] = grants_charge_impact                         # 0.0 / 1.0
decision_options_bin[c][ 3] = grants_closest_target_penetration            # 0.0 / 1.0
decision_options_bin[c][ 4] = grants_move_after_shooting                   # 0.0 / 1.0
decision_options_bin[c][ 5] = grants_reactive_move                         # 0.0 / 1.0
decision_options_bin[c][ 6] = grants_reroll_1_save_fight                   # 0.0 / 1.0
decision_options_bin[c][ 7] = grants_reroll_1_tohit_fight                  # 0.0 / 1.0
decision_options_bin[c][ 8] = grants_reroll_1_towound                      # 0.0 / 1.0
decision_options_bin[c][ 9] = grants_reroll_charge                         # 0.0 / 1.0
decision_options_bin[c][10] = grants_reroll_towound_target_on_objective    # 0.0 / 1.0
decision_options_bin[c][11] = grants_shoot_after_advance                   # 0.0 / 1.0
decision_options_bin[c][12] = grants_shoot_after_flee                      # 0.0 / 1.0
decision_options_bin[c][13] = present                                        # 0.0 / 1.0 — masque de candidat
```

**Pourquoi ce bloc existe.** Sans lui, `CHOICE_i` serait un choix à l'aveugle — exactement le
défaut de la pseudo-décision `raw_action_int % len(options)` qu'il remplace (§9.4 point 0), où
l'agent « choisissait » via une action émise pour tout autre chose, sans jamais voir le prompt.

**L'ordre des candidats est CONTRACTUEL**, comme celui des slots ennemis (invariant D1) :
`decision_options_bin[i]` décrit le candidat que joue `CHOICE_i`. Le producteur du prompt garantit
un ordre STABLE d'un step à l'autre — un ordre mouvant brouillerait l'assignation de crédit PPO.

**Un candidat est décrit par ce qu'il ACCORDE**, dans le même vocabulaire que les drapeaux
`rule_<id>` d'unité, pas par son index : l'option 0 d'un prompt n'a rien à voir avec l'option 0
d'un autre. C'est aussi ce qui rend légitime l'encodeur **partagé** (`decision_encoder`) et la
tête **pointeur** qui score les candidats (`ai/pointer_policy.py`) : le nombre de candidats est
gratuit en paramètres, et ce que le réseau apprend d'un candidat vaut pour tous.

**Le bloc reste nul** quand aucune décision n'est en attente, **ou** quand celle en attente
appartient à l'autre camp : décrire à un joueur un choix qui n'est pas le sien lui ferait observer
des candidats qu'aucune de ses actions ne peut jouer. `decision_pending` est le seul bit qui
distingue « aucune décision » de « décision de type 0 ».

**Aucun registre continu** : `rule_choice` n'a aucune grandeur continue à décrire, et un champ
rempli de zéros serait une valeur par défaut sans signifiant. Les tranches P3 qui en auront besoin
(distance d'une destination, dégâts attendus sur une cible) ouvriront `DECISION_OPTION_CONT_FIELDS`
à ce moment-là — `obs_size` changera, donc retrain `--new`.

#### `deploy_cand_cont[s]` / `deploy_cand_bin[s]` — candidats de déploiement  ·  EntityRunningNorm / jamais normalisé

Bloc de la **décision de déploiement** (V11 §0.40 point 3). Les 5 actions `4-8` ne sont pas « les
5 premiers hexes valides » mais **5 stratégies** — front agressif · pression sur objectif ·
sûr/cohésion · flanc gauche · flanc droit — évaluées sur **tous** les hexes valides de la zone
(~14 000 au premier step). Ce bloc décrit, pour chaque slot, **l'hexe que sa stratégie poserait**.

```python
deploy_cand_cont[s][0] = col_rel                 # projection _hex_center SIGNEE, vs ancre de zone
deploy_cand_cont[s][1] = row_rel                 # idem
deploy_cand_cont[s][2] = objective_distance      # subhex, hex le plus proche d'un CENTRE d'objectif
deploy_cand_cont[s][3] = enemy_distance          # subhex, reference ennemie la plus proche
deploy_cand_cont[s][4] = ally_distance           # subhex, allie POSE le plus proche (masque ci-dessous)
deploy_cand_cont[s][5] = los_exposure            # nb d'ennemis DEJA POSES qui voient cet hexe (06.01)
deploy_cand_cont[s][6] = potential_los_exposure  # nb d'ancres de la zone ennemie qui le voient
deploy_cand_cont[s][7] = ally_col_count          # nb d'allies poses sur la MEME colonne (etalement)
deploy_cand_bin[s][0]  = has_deployed_ally       # 0.0 / 1.0 — masque d'`ally_distance`
deploy_cand_bin[s][1]  = on_objective            # 0.0 / 1.0 — 14.02
deploy_cand_bin[s][2]  = in_cover                # 0.0 / 1.0 — 13.08
deploy_cand_bin[s][3]  = present                 # 0.0 / 1.0 — slot OUVERT par le masque
```

**Pourquoi ce bloc existe.** Depuis §0.40 points 1/2/4 l'agent sait quelle unité il pose, voit le
terrain de sa zone et mesure tout depuis elle. Il ne savait toujours pas **ce que chaque slot en
ferait** : cinq boîtes noires, sans position, sans distance, sans couvert, sans exposition — au
moment précis où il choisit son point d'entrée dans la partie.

**Un candidat est décrit par son EFFET, jamais par son index**, comme les candidats de décision
ci-dessus. La raison est ici plus forte qu'ailleurs : le masque n'ouvre que `min(5, n_hexes)` slots
(`open_deploy_slot_count`), donc en fin de déploiement, quand il reste moins de 5 hexes valides, ce
sont les stratégies d'**indices bas** qui survivent. Le lien slot ↔ stratégie n'est pas stable, et
un réseau qui aurait appris « le slot 7 va à gauche » se tromperait précisément là. L'encodeur est
donc **partagé** entre les 5 slots (`deploy_cand_encoder`), avec une `EntityRunningNorm` commune.

**L'ordre des slots est CONTRACTUEL** (invariant D1) : `deploy_cand_*[i]` décrit ce que pose
l'action `DEPLOY_SLOT_BASE + i`. Un slot **fermé** est une ligne de zéros, `present` compris — un
candidat plausible pour une action interdite serait pire que le silence.

**Source unique, jamais un second calcul** : `ActionDecoder.deployment_slot_candidates`, celle-là
même que le commit exécute — elle rend l'hexe **et le plan de formation validé** qui sera posé.
Décrire les candidats depuis une géométrie parallèle aurait laissé l'agent choisir d'après un hexe
que le moteur n'aurait pas posé (motif D1). Les grandeurs continues sortent telles quelles du cache
de scoring du décodeur ; `on_objective` / `in_cover` sont lus dans `_grid_static_hex_arrays`, le
MÊME ensemble que les canaux « objectifs » et « couvert » de la grille.

**Garde obligatoire, à DEUX conditions.** Le bloc n'est rempli que si (a) la phase est
`deployment` — même patron que `is_charge_phase` pour `charge_reachable_max_roll` — **et** (b)
l'escouade observée n'est **pas encore posée** (`deployed_on_turn`, la même source que le bit
`deploy_not_on_board`). La seconde n'est pas une précaution : une unité déjà sur le champ de
bataille ne choisit plus où se déployer, par la règle. Elle rend la garde plus STRICTE — l'unité
que le masque déploie n'est jamais posée — et évite d'interroger le décodeur pour toutes les
escouades déjà en place. Le bloc reste nul, enfin, pour une escouade qui n'est pas celle sur
laquelle le masque ouvre les slots 4-8. Coût **mesuré**
sur le board x5 (3 épisodes, 33 steps de déploiement) : **285 ms → 345 ms** par step de
déploiement, soit **+59 ms** pour décrire les 5 stratégies au lieu d'en évaluer une seule. Le
surcoût est contenu parce que la sélection a été **vectorisée** au passage (`np.lexsort` sur des
colonnes calculées une fois pour les 5 stratégies, au lieu d'une passe scalaire par stratégie) :
appeler 5 fois l'ancienne sélection aurait coûté **871 ms** par step. La parité de choix avec
l'implémentation scalaire est exacte, vérifiée hexe par hexe sur 33 états × 5 stratégies.

⚠️ **Ce que ce bloc ne fait PAS.** Les logits des actions `4-8` ne viennent pas d'une tête dédiée :
ces ids tombent dans la plage des cellules de move (`MOVE_CELL_BASE = 0`), donc ils sortent de la
conv 1×1 de la carte, aux cellules `(0, 4..8)` de la fenêtre égocentrique. Ce bloc atteint cette
tête par le **conditionnement du tronc** (`move_ctx_net`, qui peut réordonner les cellules entre
elles), pas par un pointeur sur les candidats. Une tête pointeur de déploiement — le jumeau de
`choice_query_net` — est le prolongement naturel ; elle touche l'architecture de la policy, pas le
contrat d'observation. Suivi en [`V11_agent_rework.md`](Implémentation/V11_agent_rework.md#s0.44)
**§0.44** — arbitré le 2026-07-29 : **reporté après le run 4**.

### Les blocs logiques A→E, et ce qu'ils sont devenus

L'observation a été conçue en **blocs thématiques** (`V11_audit_observation.md` §7.2 et §8 : A
contexte, B mon escouade, C mes figurines, D ennemis, E escouades amies). Ces blocs n'ont pas
disparu — T-D les a matérialisés en **clés de tenseurs**. Table de passage, parce que les deux
vocabulaires coexistent dans la doc V11 :

| Bloc logique | Clé(s) actuelle(s) | Note |
|---|---|---|
| **A** — contexte général | `global_cont` / `global_bin` | y compris les objectifs : contrôle, présence, **et depuis §0.31 distance + direction** |
| **B** — mon escouade | `allies_cont[0]` / `allies_bin[0]` | l'unité active est la **ligne 0** du bloc amis (contrat) ; les features « actif seulement » y sont, ailleurs à zéro |
| **C1** — types de figurines | `allies_types_*` / `enemies_types_*` | profil défensif + rôle d'allocation + effectif du type ; décrit l'escouade ENTIÈRE sans plafonner l'effectif |
| **C2** — mes figurines | `self_models_*` | seulement l'irréductiblement individuel : position relative, éligibilité au combat, engagement |
| **D** — ennemis | `enemies_*` | **ordre contractuel = slots d'action de tir** ; porte depuis §0.31 `los_can_see` + `cover_vs_observer`, depuis §9 P3-2 `charge_reachable_max_roll` |
| **E** — escouades amies | `allies_[1..K-1]` | livré avec T-D : les alliés sont **agrégés** par le réseau, donc leur ordre n'a pas à être inventé |
| *(transverse)* profils d'armes | `*_wpn_*` | même encodeur pour les deux camps ; 86 % du vecteur, et le seul bloc mémoïsé |
| *(transverse)* règles d'unité | 13 bits dans `*_bin` | §0.31 : sur **toute** entité, amie comme ennemie (schéma unifié) |
| *(transverse)* terrain perçu | `grid` | **9** canaux égocentriques ; **ne porte que la fenêtre** du budget d'Advance. Depuis §0.32 : un canal `self` distinct du canal allié (T-L) et le **coût géodésique** de chaque cellule du pool de move (T-K), encodé pour que la frontière normal/advance soit **constante** — la grille passe seule dans le CNN, elle doit être lisible sans le vecteur |

⚠️ Deux blocs sont **transverses** et non des blocs à part : les profils d'armes et les règles
d'unité vivent DANS chaque entité, par construction du schéma unifié (invariant 1). Chercher un
« bloc armes » ou un « bloc règles » séparé serait chercher ce qui n'existe pas — et le
recréerait en cassant le partage de poids.

**Espace d'action** : une action de tir par slot ennemi (`SHOOT_SLOT_BASE + i`, 20 slots depuis
T-E) ; les logits de ces actions sont produits par une **tête pointeur** (`ai/pointer_policy.py`)
qui score `q · e_i` sur les embeddings — un slot de plus ne coûte donc aucun paramètre. **Les
1024 logits de cellule de move ont la même propriété depuis V11 §0.32 T-G** : ils sortent d'une
**conv 1×1** sur la colonne de features de leur cellule, prise sur une carte CNN conservée à
résolution 32×32 (`SpatialCombinedExtractor.move_map_slice()`), et non plus d'une ligne dédiée du
`action_net` dense. Une cellule de plus ne coûte donc, elle non plus, aucun paramètre, et
l'alignement `cellule (gx,gy) ↔ action gy*32+gx` est **structurel** (un `reshape`) au lieu d'être
ré-appris. Deux ajouts sont indissociables de cette tête et ne doivent jamais être retirés : les
**canaux positionnels fixes** (x, y, rayon — une conv est invariante par translation et ne
saurait pas que le bord de la grille est la limite d'atteignabilité) et le **conditionnement par
le latent du tronc** (sans lui, la tête ne voit ni le tour, ni les VP, ni les objectifs hors
fenêtre). Le mapping slot ↔ escouade est rafraîchi : les slots des escouades mortes sont rendus, et toute
escouade vivante sans slot en reçoit un (une escouade vivante mappée ne change JAMAIS de slot).

**Pourquoi ce format.** Au format plat, la première couche du réseau portait un jeu de poids
DISTINCT par slot ennemi (mesuré : 640 paramètres par dimension d'observation, ~226 k par slot) :
le réseau réapprenait « évaluer un ennemi » autant de fois qu'il y avait de slots, et ajouter un
slot coûtait des centaines de milliers de paramètres. En tenseurs d'entités, **le même encodeur
est appliqué à chaque unité et à chaque arme, des DEUX camps** (`ai/spatial_extractor.py`) : le
réseau généralise d'un slot à l'autre et le coût d'un slot supplémentaire est nul en paramètres.

**Trois invariants à ne jamais casser :**
1. **Schéma unifié** — une unité amie et une unité ennemie portent EXACTEMENT les mêmes features
   (les features propres à l'unité active sont à zéro ailleurs, avec le bit `is_active` pour
   masque). Sans cela, l'encodeur partagé n'a plus de sens.
2. **Ordre des slots ennemis** — `enemies_*[i]` décrit l'ennemi que désigne l'action de tir de
   slot `i` (invariant D1). Les alliés, eux, sont AGRÉGÉS : leur ordre n'a pas de sémantique.
3. **Normalisation** — `VecNormalize` ne touche que `global_cont`. Les tenseurs d'entités sont
   normalisés DANS l'extracteur par une statistique **commune à tous les slots**
   (`EntityRunningNorm`) : une normalisation élément par élément donnerait à chaque slot ses
   propres échelles et annulerait le partage de poids. Les clés `_bin` ne sont jamais normalisées.

### Qui normalise quoi — la règle se lit sur la CLÉ, jamais sur la dimension

| Clé | Répliquée par slot ? | Normalisée par | Où c'est décidé |
|---|---|---|---|
| `global_cont` | non (singleton) | **`VecNormalize`** (running mean/var) | `_vec_norm_obs_keys` ([ai/train.py](../ai/train.py)) |
| `global_bin` | non (singleton) | **jamais** | idem (hors `norm_obs_keys`) |
| `*_cont` d'entités et `self_models_cont` | oui | **`EntityRunningNorm`**, une stat par feature **commune à tous les slots et aux deux camps** | `ENTITY_CONT_KEYS` ([observation_builder.py](../engine/observation_builder.py)) + [ai/spatial_extractor.py](../ai/spatial_extractor.py) |
| `*_bin` d'entités | oui | **jamais** | — |
| `grid` | — | **jamais** (canaux déjà dans [0,1]) | `_vec_norm_obs_keys` |

⚠️ **`_bin` ne veut pas dire « binaire »** — il veut dire « **jamais normalisé** ». Deux groupes
de dimensions y sont non binaires, et y sont **exprès** parce que des statistiques glissantes
détruiraient leur sémantique ou amplifieraient leur bruit : `objective_control_*` (dans
{-1, 0, +1}) et `objective_dir_cos/sin_*` (déjà bornés et centrés). Ne pas « corriger » cela en les
déplaçant vers `_cont`. (`phase` était le troisième cas, comme scalaire ordinal ; c'est désormais
un one-hot, donc réellement binaire — et toujours hors normalisation.)

### Ce qui est mémoïsé, et par quelle clé d'invalidation

L'observation lit **huit** caches, chacun avec sa propre condition d'invalidation. C'est le point
le plus fragile du pipeline : un cache servi trop longtemps ne lève rien, il décrit simplement un
état périmé (régressions V11 §0.18 et §0.26). L'inventaire est verrouillé par
`tests/unit/engine/test_obs_caches_die_with_the_episode.py`, qui rougit si un cache d'observation
survit à un reset — **ajouter un cache sans l'y ajouter fait échouer ce test**.

| Cache | Ce qu'il porte | Clé | Invalidé par |
|---|---|---|---|
| `_obs_weapon_profiles_cache` | les sous-tenseurs d'armes (86 % du vecteur) | `(escouade, figurines vivantes)` | `build_units_cache` — donc à chaque perte et à chaque reset |
| `_obs_objective_hex_arrays` | hexes de chaque objectif (distances/directions) | par épisode | bloc de purges de `reset` |
| `_grid_static_hex_arrays` | murs / objectifs / couvert rasterisés | par épisode | idem |
| `_obs_solid_terrain_areas` | zones contenant un mur dense (Solid 13.11) | par épisode | idem |
| `_grid_deployment_zone_anchor` | l'hex sur lequel la grille est centrée pour une escouade **pas encore posée** (V11 §0.40) | par joueur, par épisode | idem — la zone de déploiement change avec le terrain rechargé |
| `_deployment_scoring_cache` | expositions LoS par hexe (réelle et potentielle), alliés posés par colonne, snapshot des unités posées — **lu par le bloc candidat de déploiement**, donc sa péremption deviendrait une observation fausse | `(déployeur, jeu d'hexes valides, snapshot des posées)` | mise à jour **incrémentale** à chaque pose, reconstruction complète sur dérive ; purgé au `reset` — son garde-fou ne mord pas si un épisode s'interrompt AVANT la 1re pose (le jeu d'hexes coïncide alors avec celui du nouvel épisode, murs différents compris) |
| `_deployment_slot_candidates` | l'hexe **et le plan de formation** que chaque slot 4-8 poserait (V11 §0.40 point 3) — lu par le décodeur ET par l'observation, donc calculé une seule fois par step | `(escouade, déployeur, état des unités posées)` | le tampon change à chaque pose ; purgé au `reset` — l'état « aucune unité posée » recommence identique d'un épisode à l'autre, donc le tampon seul ne suffirait pas |
| `_unit_los_pair_cache` | `los_can_see` / `cover_vs_observer` par paire | `(tireur, cible)` | **invalidation ciblée** au choke-point `_touch_unit_los` : toute écriture de position, toute perte de figurine — donc correct même quand un ennemi bouge pendant mon tour (`reactive_move`) |

`_unit_los_pair_cache` est le seul à ne PAS être « par épisode » : il doit suivre chaque mouvement. Sa
fiabilité a été vérifiée par mesure — 23 398 paires comparées au calcul non caché sur 400 steps,
0 divergence (V11 §0.31).

**`obs_size`** (config d'agent, `observation_params.obs_size`) = nombre TOTAL de scalaires,
grille exclue — calculé par `ObservationBuilder.SQUAD_OBS_SIZE_TARGET`. Historique : 108 (T6) →
199 (refonte du vecteur, 2026-07-25) → 1011 (profils d'armes et règles, 2026-07-26) → 5729
(tenseurs d'entités, T-D) → 12284 (20 slots ennemis, T-E) → 20096 (K armes = 10 par registre,
T-F) → 20166 (plafond du bloc figurines 6 → 20, 2026-07-26) → 20181 (géométrie des objectifs,
2026-07-27) → 20545 (règles d'unité, 13 bits par entité) → 20601 (couvert et visibilité exacts par
slot ennemi, 2026-07-27) → 20626 (bit `present` par figurine + phase en one-hot de 6 bits,
§0.32 T-H/T-J, 2026-07-28) → 20654 (`n_models_engaging` : mes figurines engagées avec chaque
cible ennemie, support du choix de cible de mêlée, §9 P3-1, 2026-07-28) → 20740 (bloc
« contexte de décision », §9.3 P2, 2026-07-28) → 20768 (`charge_reachable_max_roll` :
support du choix de cible de charge, §9 P3-2, 2026-07-28) → 20828 (bloc « candidats de
déploiement » : ce que chacune des 5 actions 4-8 poserait, §0.40 point 3, 2026-07-29)
→ **20780** (RETRAIT de `ez_relayed_by_ally` et `n_relayed_ez` avec la clause « buddy » :
04.02 WHILE FIGHTING n'autorise à frapper qu'une figurine ENGAGÉE avec la cible, le relais par
une alliée au contact venait d'une édition antérieure de 40K, 2026-08-04). **Toute évolution du
schéma change cette valeur et rend les `.zip` existants incompatibles : le retrain `--new` est
obligatoire.**

**Les règles d'unité** sont exposées depuis le 2026-07-27 : 13 bits `rule_<effet>` **par entité**
(amie ET ennemie) dans `UNIT_BIN_FIELDS`. ⚠️ Ne pas les confondre avec les « 12 unit-rule flags »
du layout `obs[314:346]` que décrit [`AI_OBSERVATION_Legacy.md`](AI_OBSERVATION_Legacy.md) : ceux-là
appartiennent au pipeline mono-figurine et ont longtemps fait croire que le pipeline squad les
portait déjà.

**Historique et décisions** : [`Implémentation/V11_audit_observation.md`](Implémentation/Implémenté/V11_audit_observation.md)
(§8, §10 ; §7 pour la découpe en blocs A→E) ·
[`V11_agent_rework.md`](Implémentation/V11_agent_rework.md) §9.2.5 (ce qui est observé des règles),
**§0.31** (objectifs situés, règles d'unité, couvert exact, caches) et **§0.32** (audit
d'optimalité du 2026-07-28 : T-H/T-I/T-J livrés — masque de présence, géométrie unique, phase en
one-hot ; **T-G, la tête de move dense, reste ouvert**) ·
[`V11_entity_encoder_pointer.md`](Implémentation/V11_entity_encoder_pointer.md) (§1 constats
mesurés, §3 architecture, §6 journal) · [`AI_OBSERVATION_Legacy.md`](AI_OBSERVATION_Legacy.md)
(archive du pipeline mono-figurine).

