# Observation et espace d'action

Référence canonique de l'observation et de l'espace d'action de l'agent : **le pipeline SQUAD en
tenseurs d'entités**, le seul sur lequel l'agent s'entraîne.

> **Ce document ne décrit QUE le code actuel.** Le pipeline mono-figurine (`obs_size = 359`,
> vecteur plat d'offsets `obs[N]`) a été supprimé du code le 2026-07-28 et archivé dans
> **[`AI_OBSERVATION_Legacy.md`](../../Archives/docs/AI_OBSERVATION_Legacy.md)**.
>
> **Version** : 3.0 — tenseurs d'entités (V11 §0.30 T-D), complétée par V11 §0.31 et §0.32.
> **Pipeline de training/évaluation** : `entrainement.md` (CLI, callbacks, évaluation contre bots).

**Source unique du contrat** : l'en-tête « OBSERVATION SQUAD — TENSEURS D'ENTITÉS » de
[`engine/observation_builder.py`](../../../engine/observation_builder.py) et le schéma
[`engine/observation_entities.py`](../../../engine/observation_entities.py). Ce document en donne la
lecture, jamais une copie de chiffres qui dériverait.

---

## Observation agent

**L'observation n'est plus un vecteur plat.** Elle est un `Dict` de tenseurs :

| Clé | Forme | Contenu |
|---|---|---|
| `global_cont` / `global_bin` | (13,) / (35,) | ce qui n'appartient à aucune unité : tour, pas d'épisode, points de mission des deux camps, **points de commandement des deux camps (08.02)**, force d'usure, **distance à chacun des 5 objectifs** ; mon tour, **phase en one-hot de 6 bits**, contrôle + présence des 5 objectifs, **direction (cos/sin) vers chacun d'eux**, **capacités de faction des deux camps (Waaagh! disponible/actif, désignation Oath en vigueur, clause du +1 Wound d'Oath ouverte — chantier 03)**. Ces distances/directions — comme les `col_rel`/`row_rel` des entités — sont mesurées depuis le **centroïde de l'escouade active**, ou depuis l'**ancre de sa zone de déploiement** tant qu'elle n'est pas posée (même repère que la grille, V11 §0.40 point 4). Une entité pas encore posée n'a **aucune** position relative ni **aucune relation géométrique** : `col_rel`/`row_rel`, `edge_distance`, `engaged`, `los_can_see`, `cover_vs_observer`, `n_fight_eligible`, `n_in_enemy_ez`, `n_models_engaging` sont nuls — règle 03.04, l'engagement range est une aire **du champ de bataille** (V11 §0.40 point 5) — et le bit `deploy_not_on_board` le dit. `coherent` fait exception : 03.03 ne teste la cohérence que « if that unit is on the battlefield » |
| `allies_cont` / `allies_bin` | (12, 20) / (12, 21) | **ligne 0 = l'unité ACTIVE**, lignes suivantes = mes autres escouades. Les drapeaux incluent, pour les ennemis seulement, `los_can_see`, `cover_vs_observer` et `charge_reachable_max_roll` |
| `allies_ability_ids` / `allies_status_ids` | (8, 8) / (8, 4) | **capacités et statuts EN VIGUEUR (19.04), en IDENTIFIANTS ENTIERS et non en bits** : `obs_id` des registres [`config/unit_rules.json`](../../../config/unit_rules.json) et [`config/unit_statuses.json`](../../../config/unit_statuses.json), **triés croissants**, paddés à `0`. Deux `nn.EmbeddingBag(128, 16, mode="sum", padding_idx=0)` en font une **lecture de ligne** : aucun one-hot n'est matérialisé, donc la longueur du vecteur est **indépendante du nombre de capacités existantes** — ajouter une capacité, un statut ou une faction entière ne change ni `obs_size`, ni le nombre de paramètres du réseau, donc n'impose **aucun retrain**. Débordement (> 8 capacités) → **erreur**, jamais troncature |
| `allies_wpn_cont` / `_bin` / `_rule_ids` | (8, 20, 13) / (8, 20, 1) / (8, 20, 6) | profils d'armes par unité — **10 de tir puis 10 de mêlée**, avec porteurs vivants, params de règles, et les règles booléennes en **ids** (3ᵉ `EmbeddingBag`, cf. `*_wpn_rule_ids`) |
| `allies_types_cont` / `_bin` | (8, 6, 5) / (8, 6, 5) | types de figurines : profil défensif, rôle d'allocation (règle 19), effectif du type |
| `enemies_*` | idem avec **20 slots** | **ordre CONTRACTUEL = slots d'action de tir** (`get_enemy_slot_mapping`) |
| `self_models_cont` / `_bin` | (20, 2) / (20, 3) | ce qui est irréductiblement individuel : position relative, éligibilité au combat, engagement, **bit de présence** |
| `grid` | (9, 32, 32) | grille égocentrique : murs, **autres** escouades amies, ennemis, EZ, objectifs, niveau, couvert, **l'escouade active seule** (§0.32 T-L), **coût géodésique du pool de move** — encodé avec la frontière normal/advance à **0,5 exactement** (§0.32 T-K) ; escouade **engagée** : tout move est un Fall Back qui coûte le tir → toutes les cellules peintes sont **au-dessus de 0,5** (§0.37). **Centre de la fenêtre** (`ObservationBuilder.squad_grid_anchor`) : l'escouade active — sauf si elle n'est **pas encore posée** (`deployed_on_turn is None`, phase de déploiement), auquel cas c'est un hex de **sa zone de déploiement** ; avant V11 §0.40 la fenêtre était centrée sur la sentinelle `(-1,-1)`, donc sur une autre région du plateau |

### Vue d'ensemble

Tailles **calculées, pas recopiées** : la somme des clés vaut `obs_size`, et
`tests/unit/engine/test_squad_obs_structure_doc.py` échoue si ce bloc dérive du schéma.

```
┌────────────────────────────────────────────────────────────────────────┐
│  OBSERVATION SQUAD — Dict de TENSEURS D'ENTITÉS  (16 735 scalaires)    │
├────────────────────────────────────────────────────────────────────────┤
│  CONTEXTE GLOBAL                                                       │
│    global_cont            (13,)                =      13               │
│    global_bin             (35,)                =      35               │
│                                                                        │
│  MES ESCOUADES — ordre = slots d'activation       K_ALLY_SLOTS = 12    │
│    allies_cont            (12, 20)             =     240               │
│    allies_bin             (12, 21)             =     252               │
│    allies_ability_ids     (12, 8)              =      96               │
│    allies_status_ids      (12, 4)              =      48               │
│    allies_wpn_cont        (12, 20, 13)         =   3 120               │
│    allies_wpn_bin         (12, 20, 1)          =     240               │
│    allies_wpn_rule_ids    (12, 20, 6)          =   1 440               │
│    allies_types_cont      (12, 6, 5)           =     360               │
│    allies_types_bin       (12, 6, 5)           =     360               │
│                                                                        │
│  ESCOUADES ENNEMIES — ordre = slots d'action     K_ENEMY_SLOTS = 20    │
│    enemies_cont           (20, 20)             =     400               │
│    enemies_bin            (20, 21)             =     420               │
│    enemies_ability_ids    (20, 8)              =     160               │
│    enemies_status_ids     (20, 4)              =      80               │
│    enemies_wpn_cont       (20, 20, 13)         =   5 200               │
│    enemies_wpn_bin        (20, 20, 1)          =     400               │
│    enemies_wpn_rule_ids   (20, 20, 6)          =   2 400               │
│    enemies_types_cont     (20, 6, 5)           =     600               │
│    enemies_types_bin      (20, 6, 5)           =     600               │
│                                                                        │
│  MES FIGURINES (individuel)                        SQUAD_TOP_K = 20    │
│    self_models_cont       (20, 2)              =      40               │
│    self_models_bin        (20, 3)              =      60               │
│                                                                        │
│  DÉCISION AGENT — candidats de CHOICE_i        MAX_DECISION_OPTIONS = 6│
│    decision_ctx_bin       (9,)                 =       9               │
│    decision_options_bin   (6, 9)               =      54               │
│    decision_options_cont  (6, 2)               =      12               │
│                                                                        │
│  DÉPLOIEMENT — candidats des actions 4-11        N_DEPLOY_SLOTS = 8    │
│    deploy_cand_cont       (8, 8)               =      64               │
│    deploy_cand_bin        (8, 4)               =      32               │
├────────────────────────────────────────────────────────────────────────┤
│  TOTAL vectoriel (= obs_size)                      16 735              │
│  + grid  (9, 32, 32) = 9 216, fournie À PART (non comptée)             │
└────────────────────────────────────────────────────────────────────────┘

Coût d'UNE entité = 19 + 20 (unité) + 8 + 4 (capacités/statuts) + 20 × (13 + 1 + 6) (armes)
   + 6 × (5 + 5) (types) = 511
   → le bloc ARMES fait 78 % du vecteur. C'est le seul bloc mémoïsé.
```

### Description des tenseurs

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
global_cont[6]     = my_command_points                       # brut (CP, regle 08.02)
global_cont[7]     = enemy_command_points                    # brut (CP, regle 08.02)
global_cont[8]     = objective_distance_0                   # subhex, hex le plus proche de l'objectif 0
global_cont[9]     = objective_distance_1                   # subhex, hex le plus proche de l'objectif 1
global_cont[10]    = objective_distance_2                   # subhex, hex le plus proche de l'objectif 2
global_cont[11]    = objective_distance_3                   # subhex, hex le plus proche de l'objectif 3
global_cont[12]    = objective_distance_4                   # subhex, hex le plus proche de l'objectif 4
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
global_bin[27]     = my_waaagh_available                    # 0.0 / 1.0 — Waaagh! pas encore appele (1x/partie)
global_bin[28]     = my_waaagh_active                       # 0.0 / 1.0 — Waaagh! en vigueur pour MON armee
global_bin[29]     = enemy_waaagh_available                 # 0.0 / 1.0 — l'adversaire peut encore l'appeler
global_bin[30]     = enemy_waaagh_active                    # 0.0 / 1.0 — Waaagh! adverse en vigueur (enjambe mon tour)
global_bin[31]     = my_oath_target_selected                # 0.0 / 1.0 — une designation Oath est en vigueur pour moi
global_bin[32]     = enemy_oath_target_selected             # 0.0 / 1.0 — idem cote adverse
global_bin[33]     = my_oath_wound_bonus_active             # 0.0 / 1.0 — clause du +1 Wound d'Oath ouverte pour MON armee
global_bin[34]     = enemy_oath_wound_bonus_active          # 0.0 / 1.0 — idem cote adverse
```

Les huit derniers bits sont les **capacites de FACTION** (chantier 03) : globales par construction,
une capacite de faction s'appliquant uniformement a toutes les unites de l'armee qui la porte.
**Quatre** bits pour le Waaagh! et non deux : sa duree court « until the start of your next Command
phase », donc elle enjambe le tour adverse — un Waaagh! ennemi *actif* change ce que je dois faire,
un Waaagh! ennemi encore *disponible* change ce que je dois craindre, et aucun des deux ne se deduit
de l'autre. Pour Oath, quatre bits egalement, et pour deux raisons distinctes. La designation
(`*_oath_target_selected`) ne dit QUE qu'un choix est en vigueur : l'identite de la cible est portee
par le statut `oath_target` de l'entite visee (`enemies_status_ids` / `allies_status_ids`), donc la
ou le reseau la lit avec l'unite qu'elle qualifie, pour 0 scalaire ici. La clause du +1 au jet de
blessure (`*_oath_wound_bonus_active`) est un bit SEPARE parce qu'elle ne se deduit pas de la
designation : elle depend du ROSTER (detachement Codex, et aucune unite BLOOD ANGELS / DARK ANGELS /
DEATHWATCH / SPACE WOLVES — unites MORTES comprises), donnee qu'aucune autre feature ne porte.

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
[s][19]    = effective_range                        # subhexes [ENNEMIS seuls] — portee MAXIMALE
                                                    #   des armes de tir de l'observatrice
                                                    #   (max RNG x inches_to_subhex).
                                                    #   Grandeur de PAIRE : meme valeur pour
                                                    #   tous les slots, directement comparable
                                                    #   a edge_distance (V11 §9.5 P4).
                                                    #   0 pour une unite corps-a-corps pure.
```

#### `allies_bin[s]` / `enemies_bin[s]` — une unite, 20 drapeaux  ·  jamais normalise

```python
[s][0]     = is_ally                                # 0.0 / 1.0
[s][1]     = is_active                              # 0.0 / 1.0 — masque des features [ACTIVE seule]
[s][2]     = moved                                  # 0.0 / 1.0
[s][3]     = shot                                   # 0.0 / 1.0
[s][4]     = fought                                 # 0.0 / 1.0
[s][5]     = advanced                               # 0.0 / 1.0
[s][6]     = fled                                   # 0.0 / 1.0
[s][7]     = charged                                # 0.0 / 1.0 — a fait une charge move ce tour (§15.11 HI)
[s][8]     = coherent                               # 0.0 / 1.0 (03.03)
[s][9]     = engaged                                # 0.0 / 1.0 (03.04)
[s][10]    = hidden                                 # 0.0 / 1.0 (13.09) [ACTIVE seule]
[s][11]    = gone_to_ground                         # 0.0 / 1.0 (13.5) [ACTIVE seule]
[s][12]    = in_cover                               # 0.0 / 1.0 (13.08 branche intrinseque) [ACTIVE seule]
[s][13]    = deploy_not_on_board                    # 0.0 / 1.0 — one-hot mise en place
[s][14]    = deploy_pre_battle                      # 0.0 / 1.0
[s][15]    = deploy_in_battle                       # 0.0 / 1.0
[s][16]    = deployed_this_turn                     # 0.0 / 1.0 (clause 2 de [HEAVY] 24.16)
[s][17]    = los_can_see                            # 0.0 / 1.0 (06.01) [ENNEMIS seuls]
[s][18]    = cover_vs_observer                      # 0.0 / 1.0 (13.08 EXACT, 2 branches) [ENNEMIS seuls]
[s][19]    = charge_reachable_max_roll              # 0.0 / 1.0 — un plan de charge legal existe au jet
                                                    #   MAXIMAL (11.02, 2D6 -> 12) [ENNEMIS seuls, phase
                                                    #   CHARGE seule ; masque = phase_charge]
[s][20]    = present                                # 0.0 / 1.0 — masque d'entite (0 = slot vide ou morte), DERNIER comme dans tous les registres (§0.37)
```

#### `*_ability_ids[s]` / `*_status_ids[s]` — ENSEMBLES D'IDENTIFIANTS  ·  jamais normalise

Ce ne sont **pas** des drapeaux indexés par position : ce sont des **ensembles**. Le slot `k` n'a
aucune sémantique propre — il porte le `k`-ième id du tri croissant, et `0` signifie « slot vide ».

```python
[s][0..7]  = ability_ids     # obs_id des capacites EN VIGUEUR (19.04), config/unit_rules.json,
                             #   TRIES croissants puis paddes a 0. Debordement -> ERREUR.
[s][0..3]  = status_ids      # obs_id des statuts EN VIGUEUR, config/unit_statuses.json :
                             #   battle_shock (08.03), oath_target, suppressed. Meme convention.
```

`obs_id` **stable a vie, jamais reattribue** : un id recycle apres suppression d'une regle ferait
pointer un modele deja entraine sur une ligne d'embedding qui ne veut plus dire la meme chose —
corruption silencieuse. Un id retire reste **brule**. Domaine `[1, 127]`, `0` reserve au padding
(`config_loader.OBS_ID_MIN/MAX`, valide au chargement : absent, hors domaine ou duplique -> erreur).

Cote reseau (`ai/spatial_extractor.py`), **deux** `nn.EmbeddingBag(128, 16, mode="sum",
padding_idx=0)` — deux tables et non une, parce qu'une capacite (« cette unite a Feel No Pain »)
et un statut (« cette unite est la cible Oath adverse ») ne sont pas de meme nature : un pooling
commun les additionnerait dans le meme espace. Le pooling **somme** est invariant par permutation
(l'ordre des slots ne change pas le vecteur) et preserve la **multiplicite** (un ensemble de 1
element ne se confond pas avec un de 3). Les 16 + 16 dimensions sont concatenees a la
representation d'entite, avant l'encodeur partage.

Les effets de **faction** n'entrent PAS dans ces ensembles : Waaagh! accorde quatre effets
identiques a toutes les unites orkes ; les repeter sur 28 entites ferait deborder les slots pour
zero information, alors que le reseau les reconstitue depuis deux informations GLOBALES
(« unite orke » + « Waaagh! actif »). Ils vivent dans `global_bin`.

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

#### `*_wpn_bin[s][w]` — un profil d'arme, 1 drapeau  ·  jamais normalise

```python
[s][w][0]     = mask                                   # 0.0 / 1.0 — 0 = slot d'arme vide
```

#### `*_wpn_rule_ids[s][w]` — les REGLES d'un profil, 6 slots d'ids  ·  jamais normalise

Meme convention que `*_ability_ids` : des `obs_id` du registre
[`config/weapon_rules.json`](../../../config/weapon_rules.json), **tries croissants**, paddes a `0`, lus
par une **troisieme** `nn.EmbeddingBag(128, 16, mode="sum", padding_idx=0)`. Le slot k n'a aucune
semantique propre — c'est un ENSEMBLE, pas des positions.

Vocabulaire ecrit ici : les 12 regles booleennes (`WEAPON_RULE_BITS` : `DEVASTATING_WOUNDS`,
`LETHAL_HITS`, `TORRENT`, `TWIN_LINKED`, `EXTRA_ATTACKS`, `PRECISION`, `PSYCHIC`, `HAZARDOUS`,
`HEAVY`, `IGNORES_COVER`, `CLOSE_QUARTERS`, `ASSAULT`, `INDIRECT_FIRE`) et l'IDENTITE de la regle `[ANTI-X]` portee
(`ANTI_INFANTRY`, `ANTI_VEHICLE`, `ANTI_FLY`, `ANTI_PSYKER`, `ANTI_MONSTER` — une seule, celle du
MEILLEUR seuil, 24.02). Son seuil Y+ reste continu (`*_wpn_cont[s][w][12]`) : c'est une valeur, pas
une categorie. Les regles PARAMETREES (`RAPID_FIRE`, `SUSTAINED_HITS`, `MELTA`, `CLEAVE`, `BLAST`)
n'ont pas d'id — leur presence se lit sur leur dimension continue.

Pourquoi des ids ici (V11 §0.48, arbitrage 2) : un drapeau positionnel coutait **560 scalaires**
(28 entites x 20 profils), et une regle de plus en coutait 560 de plus — la conformite aux regles
et l'objectif « un seul retrain » se contredisaient. Le vocabulaire est PRE-DIMENSIONNE
(`OBS_ID_VOCAB_SIZE = 128`) : rendre `[INDIRECT FIRE]` vivante se fera en lui donnant un `obs_id`,
sans toucher `obs_size` ni les poids du reseau. Debordement (> 6 regles sur une arme) → **erreur**,
jamais troncature ; maximum MESURE sur les 4 armureries = 4.

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
decision_ctx_bin[2]      = decision_type_waaagh_call         # 0.0 / 1.0 — appel du Waaagh! (chantier 03)
decision_ctx_bin[3]      = decision_type_fly_declaration     # 0.0 / 1.0 — « take to the skies » 21.03 (L6)
decision_ctx_bin[4]      = decision_type_allocation_model    # 0.0 / 1.0 — choix figurine réceptrice 05.04 (P3-4)
decision_ctx_bin[5]      = decision_type_charge_placement    # 0.0 / 1.0 — placement charge par figurine (chantier 04)
decision_ctx_bin[6]      = decision_type_reserved_0          # colonne RÉSERVÉE : le one-hot fait
                                                             # AGENT_DECISION_TYPE_SLOTS bits, donc ajouter un type
                                                             # consomme une réserve : les bits NE BOUGENT PAS.
decision_ctx_bin[7]      = decision_type_reserved_1          # colonne RÉSERVÉE (idem reserved_0)
decision_ctx_bin[8]      = decision_type_reserved_2          # colonne RÉSERVÉE (idem reserved_0)

decision_options_cont[c][0] = role_tier_norm                 # [0, 1] — ROLE_TIER / 4 (base=0, leader=1)
decision_options_cont[c][1] = dist_enemy_norm                # [0, 1] — distance ennemi / (cols+rows) du plateau
                                                             # Rempli seulement pour `allocation_model` ;
                                                             # zéro pour tous les autres types (no options_cont).

decision_options_bin[c][ 0] = grants_charge_after_flee                     # 0.0 / 1.0
decision_options_bin[c][ 1] = grants_reroll_1_save_fight                   # 0.0 / 1.0
decision_options_bin[c][ 2] = grants_reroll_1_tohit_fight                  # 0.0 / 1.0
decision_options_bin[c][ 3] = grants_reroll_1_towound                      # 0.0 / 1.0
decision_options_bin[c][ 4] = grants_reroll_towound_target_on_objective    # 0.0 / 1.0
decision_options_bin[c][ 5] = grants_shoot_after_advance                   # 0.0 / 1.0
decision_options_bin[c][ 6] = grants_shoot_after_flee                      # 0.0 / 1.0
decision_options_bin[c][ 7] = declines                                      # 0.0 / 1.0 — ce candidat NE FAIT RIEN
decision_options_bin[c][ 8] = present                                        # 0.0 / 1.0 — masque de candidat
```

**Ce registre n'est PAS le vocabulaire observé** (`UNIT_RULE_EFFECT_IDS`), et c'est délibéré
depuis le 2026-08-04. La source est désormais `DECISION_GRANTABLE_EFFECT_IDS` — les 7 effets
réellement accordables, recalculés depuis les rosters par un test de contrat
(`test_agent_decision_mechanism.py`), qui échoue **dans les deux sens** : un accordable non déclaré,
ou un déclaré que plus aucun roster n'accorde.

**L'ordre des candidats est CONTRACTUEL** (invariant D1) : `decision_options_bin[i]` décrit le
candidat que joue `CHOICE_i`. Le producteur du prompt garantit un ordre STABLE d'un step à l'autre.

**Un candidat est décrit par ce qu'il ACCORDE**, dans le même vocabulaire que les drapeaux
`rule_<id>` d'unité, pas par son index. C'est ce qui rend légitime l'encodeur **partagé**
(`decision_encoder`) et la tête **pointeur** qui score les candidats (`ai/pointer_policy.py`).

**Un candidat qui ne fait RIEN est décrit par `declines`** (le dernier drapeau avant `present`).
`waaagh_call` porte un `effect_ids` **vide** des DEUX côtés — sans `declines`, les deux candidats
sortaient la MÊME ligne `[0…0, present=1]` et les logits étaient indiscernables.

**Le bloc reste nul** quand aucune décision n'est en attente, **ou** quand celle en attente
appartient à l'autre camp. `decision_pending` est le seul bit qui distingue « aucune décision »
de « décision de type 0 ».

#### `deploy_cand_cont[s]` / `deploy_cand_bin[s]` — candidats de déploiement  ·  EntityRunningNorm / jamais normalisé

Bloc de la **décision de déploiement** (V11 §0.40 point 3). Les 5 actions `4-8` ne sont pas « les
5 premiers hexes valides » mais **5 stratégies** — front agressif · pression sur objectif ·
sûr/cohésion · flanc gauche · flanc droit — évaluées sur **tous** les hexes valides de la zone.
Ce bloc décrit, pour chaque slot, **l'hexe que sa stratégie poserait**.

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

**Un candidat est décrit par son EFFET, jamais par son index.** L'encodeur est **partagé** entre
les 5 slots (`deploy_cand_encoder`), avec une `EntityRunningNorm` commune. **L'ordre des slots est
CONTRACTUEL** (invariant D1) : `deploy_cand_*[i]` décrit ce que pose l'action
`DEPLOY_SLOT_BASE + i`.

**Source unique, jamais un second calcul** : `ActionDecoder.deployment_slot_candidates`, celle-là
même que le commit exécute — elle rend l'hexe **et le plan de formation validé** qui sera posé.

**Ce bloc est SCORÉ par une tête dédiée depuis le 2026-08-07** (§0.44, élément `L1` du lot §0.48).
`deploy_query_net` — le jumeau exact de `choice_query_net` — produit les logits des ids `4-11` par
produit scalaire contre les embeddings de candidats. Router hors déploiement serait pire que ne pas
router : le bloc y est nul par contrat. `obs_size` **inchangé** — c'est un changement
d'architecture, pas d'observation.

### Les blocs logiques A→E

L'observation a été conçue en **blocs thématiques** (A contexte, B mon escouade, C mes figurines,
D ennemis, E escouades amies). Ces blocs ont été matérialisés en **clés de tenseurs** par T-D.

| Bloc logique | Clé(s) actuelle(s) | Note |
|---|---|---|
| **A** — contexte général | `global_cont` / `global_bin` | y compris les objectifs : contrôle, présence, distance + direction |
| **B** — mon escouade | `allies_cont[0]` / `allies_bin[0]` | l'unité active est la **ligne 0** du bloc amis (contrat) ; les features « actif seulement » y sont, ailleurs à zéro |
| **C1** — types de figurines | `allies_types_*` / `enemies_types_*` | profil défensif + rôle d'allocation + effectif du type |
| **C2** — mes figurines | `self_models_*` | seulement l'irréductiblement individuel : position relative, éligibilité au combat, engagement |
| **D** — ennemis | `enemies_*` | **ordre contractuel = slots d'action de tir** ; porte `los_can_see` + `cover_vs_observer` + `charge_reachable_max_roll` |
| **E** — escouades amies | `allies_[1..K-1]` | les alliés sont **agrégés** par le réseau, leur ordre n'a pas de sémantique |
| *(transverse)* profils d'armes | `*_wpn_*` | même encodeur pour les deux camps ; 86 % du vecteur, seul bloc mémoïsé |
| *(transverse)* règles d'unité | `*_ability_ids` (8 slots d'`obs_id`) | sur **toute** entité, amie comme ennemie ; ids lus par embedding, ajouter une capacité coûte **zéro scalaire** |
| *(transverse)* terrain perçu | `grid` | **9** canaux égocentriques 32×32 |

⚠️ Deux blocs sont **transverses** : les profils d'armes et les règles d'unité vivent DANS chaque
entité par construction du schéma unifié. Chercher un « bloc armes » ou un « bloc règles » séparé
créerait une rupture de partage de poids.

### Qui normalise quoi

| Clé | Répliquée par slot ? | Normalisée par |
|---|---|---|
| `global_cont` | non (singleton) | **`VecNormalize`** (running mean/var) |
| `global_bin` | non (singleton) | **jamais** |
| `*_cont` d'entités et `self_models_cont` | oui | **`EntityRunningNorm`**, une stat par feature **commune à tous les slots et aux deux camps** |
| `*_bin` d'entités | oui | **jamais** |
| `grid` | — | **jamais** (canaux déjà dans [0,1]) |

⚠️ **`_bin` ne veut pas dire « binaire »** — il veut dire « **jamais normalisé** ». Deux groupes
de dimensions y sont non binaires : `objective_control_*` (dans {-1, 0, +1}) et
`objective_dir_cos/sin_*` (déjà bornés et centrés). Ne pas les déplacer vers `_cont`.

### Caches d'observation

L'observation lit **huit** caches, chacun avec sa propre condition d'invalidation. Un cache servi
trop longtemps ne lève rien, il décrit un état périmé. L'inventaire est verrouillé par
`tests/unit/engine/test_obs_caches_die_with_the_episode.py`.

| Cache | Ce qu'il porte | Clé | Invalidé par |
|---|---|---|---|
| `_obs_weapon_profiles_cache` | les sous-tenseurs d'armes (86 % du vecteur) | `(escouade, figurines vivantes)` | `build_units_cache` — à chaque perte et à chaque reset |
| `_obs_objective_hex_arrays` | hexes de chaque objectif (distances/directions) | par épisode | bloc de purges de `reset` |
| `_grid_static_hex_arrays` | murs / objectifs / couvert rasterisés | par épisode | idem |
| `_obs_solid_terrain_areas` | zones contenant un mur dense (Solid 13.11) | par épisode | idem |
| `_grid_deployment_zone_anchor` | l'hex sur lequel la grille est centrée pour une escouade **pas encore posée** | par joueur, par épisode | idem |
| `_deployment_scoring_cache` | expositions LoS par hexe (réelle et potentielle), alliés posés par colonne | `(déployeur, jeu d'hexes valides, snapshot des posées)` | mise à jour **incrémentale** à chaque pose, reconstruction complète sur dérive ; purgé au `reset` |
| `_deployment_slot_candidates` | l'hexe **et le plan de formation** que chaque slot 4-8 poserait | `(escouade, déployeur, état des unités posées)` | le tampon change à chaque pose ; purgé au `reset` |
| `_unit_los_pair_cache` | `los_can_see` / `cover_vs_observer` par paire | `(tireur, cible)` | **invalidation ciblée** au choke-point `_touch_unit_los` : toute écriture de position, toute perte de figurine |

`_unit_los_pair_cache` est le seul à ne PAS être « par épisode » : il doit suivre chaque mouvement.

### Invariants

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

### Historique de `obs_size`

**`obs_size`** (config d'agent, `observation_params.obs_size`) = nombre TOTAL de scalaires,
grille exclue — calculé par `ObservationBuilder.SQUAD_OBS_SIZE_TARGET`. Toute évolution du
schéma change cette valeur et rend les `.zip` existants incompatibles : le retrain `--new` est
obligatoire.

**Historique** : 108 (T6) → 199 → 1011 (profils d'armes et règles) → 5729 (tenseurs d'entités,
T-D) → 12284 (20 slots ennemis, T-E) → 20096 (K armes = 10, T-F) → 20166 → 20181 → 20545
→ 20601 → 20626 → 20654 → 20740 → 20768 → 20828 → 20780 → 20752 (chantier 01) → 20718
(chantier 02) → 20725 (chantier 03) → 20727 → **14609** (socle §0.48 : règles d'armes en ids)
→ 14615 (drapeau `declines`) → 14659 + 16653 (`L2`, `K_ALLY_SLOTS` 8 → 12) → 16671
→ 16703 (`effective_range`) → **16735** (`charged`, 2026-08-24).

**C'est la DERNIÈRE valeur de cette liste que le passage aux ids fait bouger pour une capacité.**
Depuis le chantier 01, une capacité, un statut ou une faction entière n'est qu'un `obs_id` de
plus dans un registre : ni `obs_size`, ni le nombre de paramètres du réseau, ni
`TOTAL_ACTION_SIZE` ne bougent.

---

## Encodeur partagé et tête pointeur

### Principe de découpe : « une action pointe-t-elle sur cette entité ? »

Ce n'est **pas** « ami vs ennemi ». C'est ce qui décide entre agrégation et identité par slot.

| Famille | Une action la désigne ? | Traitement | K |
|---|---|---|---|
| Unités **ennemies** | ✅ `shoot slot 0..K-1` | embeddings **par slot** + **tête pointeur** | 20 |
| Unités **amies** | ❌ — le moteur impose l'unité active | encodeur partagé + **agrégation** ; depuis `L2` les slots alliés sont **contractuels** (activation) | 12 |
| Armes **amies** | ❌ aujourd'hui | encodeur partagé + agrégation par unité | 10 / registre |
| Armes **ennemies** | ❌ jamais | encodeur partagé + agrégation par unité | 10 / registre |
| **Types de figurines** | ❌ | encodeur partagé + agrégation | 6 |

⚠️ **L'agrégation détruit l'identité par slot.** C'est pour cela qu'elle est **interdite pour les
ennemis** : l'alignement obs-slot-i ↔ action-slot-i est précisément ce que l'invariant D1 rétablit.

### Principe : embeddings par entité TOUJOURS, agrégation seulement au tronc

Les embeddings par entité sont **toujours calculés et conservés** ; seule l'entrée du tronc agrège
ceux qu'aucune action ne désigne aujourd'hui. Le jour où une action pointe sur une **arme** (choix
d'arme agent) ou sur une **unité amie** (ordre d'activation), il suffit de **brancher une tête
pointeur de plus sur des embeddings qui existent déjà**. Aucune réécriture, aucune migration
d'observation.

### Schéma

```
armes (K=10 × F_w)  ──► E_w partagé ──► embeddings d_w ──┐
                                                          ├─► concat ──► E_u partagé ──► e_i (d_u)
features d'unité (F_u brut, + bit is_ally) ───────────────┘

  e_own ────────────────────────────────┐
  Σ/max e_ally  (agrégation)            ├─► tronc MLP ──► q (requête)
  Σ/max e_enemy (agrégation, contexte)  │                  │
  features globales + CNN(grille)  ─────┘                  │
                                                            ▼
                              logits de tir_i = q · e_enemy_i     (K-indépendant)
                              logits de charge_i / fight_i = q_charge/q_fight · e_enemy_i  (§9 P3-1/P3-2)
                              logits de move : conv 1x1 sur la carte (§0.32 T-G)
                              logits de wait / fight-sans-cible / zone intent : tête dense
```

- `E_w` est **le même** pour mes armes et celles de l'ennemi.
- `E_u` est **le même** pour mes escouades et les ennemies, avec un bit `is_ally` et un **schéma de
  features unifié** (les features propres à un camp sont à zéro pour l'autre, avec leur masque).
- Le réseau **généralise entre slots** : ce qu'il apprend sur le slot 2 sert au slot 9.

### Cardinalités : décision actée (2026-07-27)

Un audit a mesuré 29 % de remplissage des slots ennemis et ~25 % des slots d'armes sur les rosters
d'entraînement (max réels : **6 escouades**, **6 profils de tir**, **5 de mêlée**, **4 types**,
**12 figurines**). Décision utilisateur : les K larges sont **gardés** pour absorber des rosters
plus fournis sans re-tailler l'obs ni retrainer. Le coût mesuré valide la décision :

| | K larges (20 / 10+10) | K serrés (8 / 7+6) |
|---|---|---|
| paramètres de l'extracteur | 1,14 M | 1,14 M — **identiques** |
| construction d'une obs | 1,92 ms | 1,94 ms — **aucun écart** |
| forward extracteur (batch 1024, CPU) | 248 ms | 179 ms — **1,39×** |

Un slot de plus coûte **zéro paramètre**, donc aucune capacité ni généralisation perdue. Reste un
surcoût de forward, seul poste réel. Les slots des escouades mortes sont rendus, et toute escouade
vivante sans slot en reçoit un (une escouade vivante mappée ne change JAMAIS de slot). Tout
dépassement de K est **logué**, jamais silencieux.

---

## Espace d'action — grille égocentrique

### Root cause : action = 1 subhex

En pipeline squad V11 (gym), l'action de mouvement désignait une **direction 0-5**, et la
destination était l'**hexagone adjacent** à l'ancre. Conséquence : une escouade avançait de
**1 subhex par phase de move**, soit 0,2" sur un board ×5, au lieu des 25 subhex de son budget.
Le facteur d'échelle aggravait le défaut : en ×1, un pas d'1 hex valait 1" ; en ×5 le déplacement
effectif était divisé par 5.

En parallèle, l'observation ne contenait **aucun terrain** — murs, couverture, zones d'engagement
absents. L'agent ne percevait pas le terrain sur lequel il évoluait.

### Décision : obs spatiale égocentrique + tête spatiale

**Observation** : ajout d'une **grille locale égocentrique 32×32** autour de l'escouade active,
avec **9 canaux** : murs/obstacles, occupation alliée, occupation ennemie, zone d'engagement,
objectifs, niveau, couvert, escouade active seule (T-L), coût géodésique du pool de move (T-K).

La demi-étendue de la grille = budget Advance **MAXIMAL** (`M + 6" × inches_to_subhex`), et **non**
le budget du jet effectivement tiré. La géométrie de la grille doit être **identique entre l'obs,
le masque et le decoder** et **stable d'un step à l'autre** — l'indexer sur le D6 ferait respirer
l'échelle spatiale au gré du jet, détruisant la sémantique apprise par le CNN.

**Action** : l'action de mouvement désigne une **cellule de cette grille**, masquée par le pool BFS
projeté dessus. **Le type de move n'est PAS choisi par l'agent : il est inféré de la cellule** :
- escouade engagée → `fall_back`
- coût géodésique ≤ M → `normal`
- coût géodésique > M → `advance` (jet pré-roulé)

L'inférence utilise le **coût géodésique** (distance de chemin du BFS), pas la distance à vol
d'oiseau. Sans cette inférence, `MaskablePPO` masquerait type et cellule **indépendamment** — le
combo `normal` + cellule au-delà de M serait illégal mais non masqué.

**Tête spatiale** : les 1024 logits de cellule de move sortent d'une **conv 1×1** sur la colonne de
features de leur cellule, prise sur une carte CNN conservée à résolution 32×32
(`SpatialCombinedExtractor.move_map_slice()`), et non d'une ligne dédiée du `action_net` dense.
Une cellule de plus ne coûte donc **aucun paramètre**, et l'alignement `cellule (gx,gy) ↔ action
gy*32+gx` est **structurel** (un `reshape`) au lieu d'être ré-appris.

Deux ajouts sont indissociables de cette tête et ne doivent jamais être retirés :
- **Canaux positionnels fixes** (x, y, rayon) : une conv est invariante par translation et ne
  saurait pas que le bord de la grille est la limite d'atteignabilité.
- **Conditionnement par le latent du tronc** : sans lui, la tête ne voit ni le tour, ni les VP,
  ni les objectifs hors fenêtre.

**Source unique du masque et du décodage** : `build_squad_move_cell_map()` — la carte
cellule → (destination, coût) est construite **une fois** au masque, mémoïsée, puis relue au
décodage. Évite un 2ᵉ BFS par step **et** rend la divergence masque/exécution structurellement
impossible.

**Invariance à l'échelle** : plus rien dans l'action ne dépend de `inches_to_subhex`. Passer en ×10
ne touche ni l'action space, ni la policy, ni l'obs. Le bug d'origine disparaît structurellement.

**Mesure (board ×5)** : l'agent passe de 12 destinations atteignables (6 directions × 2 types) à
**5 386**, avec des moves de 33 à 85 subhex par phase.

### Coût géodésique et frontière normal/advance

Le coût géodésique de chaque cellule est encodé dans le canal T-K de la grille avec la frontière
normal/advance à **0,5 exactement** : une cellule atteignable en Normal est ≤ 0,5, une cellule
exigeant Advance est > 0,5. Pour une escouade **engagée**, tout move est un Fall Back qui coûte le
tir → toutes les cellules peintes sont **au-dessus de 0,5** (§0.37).

### Policy

`MultiInputPolicy` sur obs `Dict` (grille + vecteur), extracteur CNN `SpatialCombinedExtractor`
(`ai/spatial_extractor.py`) pour la grille. VecNormalize reçoit `norm_obs_keys=["global_cont"]`
(la grille 0/1 n'est jamais normalisée).
