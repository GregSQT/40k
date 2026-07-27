# AI_OBSERVATION.md — ce que l'agent observe

Référence canonique de l'observation de l'agent : **le pipeline SQUAD en tenseurs d'entités**,
le seul sur lequel l'agent s'entraîne.

> **Ce document ne décrit QUE le code actuel.** Le pipeline mono-figurine (`obs_size = 359`,
> vecteur plat d'offsets `obs[N]`) a été déplacé dans
> **[`AI_OBSERVATION_Legacy.md`](AI_OBSERVATION_Legacy.md)** le 2026-07-28. Il vivait ici sous un
> bandeau d'avertissement, et induisait quand même en erreur à chaque lecture : ses offsets, ses
> « 12 unit-rule flags » et ses features calculées (`ranged_favorite_target`,
> `melee_favorite_target`…) n'existent plus. Aucun agent ne l'utilise.
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
| `global_cont` / `global_bin` | (11,) / (22,) | ce qui n'appartient à aucune unité : tour, pas d'épisode, points de mission des deux camps, force d'usure, **distance à chacun des 5 objectifs** ; mon tour, phase, contrôle + présence des 5 objectifs, **direction (cos/sin) vers chacun d'eux** |
| `allies_cont` / `allies_bin` | (8, 19) / (8, 32) | **ligne 0 = l'unité ACTIVE**, lignes suivantes = mes autres escouades. Les 32 drapeaux incluent les **13 règles d'unité en vigueur** (19.04) et, pour les ennemis seulement, `los_can_see` + `cover_vs_observer` |
| `allies_wpn_cont` / `_bin` | (8, 20, 13) / (8, 20, 18) | profils d'armes par unité — **10 de tir puis 10 de mêlée**, avec porteurs vivants et bits/params de règles |
| `allies_types_cont` / `_bin` | (8, 6, 5) / (8, 6, 5) | types de figurines : profil défensif, rôle d'allocation (règle 19), effectif du type |
| `enemies_*` | idem avec **20 slots** | **ordre CONTRACTUEL = slots d'action de tir** (`get_enemy_slot_mapping`) |
| `self_models_cont` / `_bin` | (20, 2) / (20, 3) | ce qui est irréductiblement individuel : position relative, éligibilité au combat, engagement |
| `grid` | (7, 32, 32) | grille égocentrique : murs, alliés, ennemis, EZ, objectifs, niveau, couvert |

### Structure Overview

Tailles **calculées, pas recopiées** : la somme des clés vaut `obs_size`, et
`tests/unit/engine/test_squad_obs_structure_doc.py` échoue si ce bloc dérive du schéma.

```
┌────────────────────────────────────────────────────────────────────────┐
│  OBSERVATION SQUAD — Dict de TENSEURS D'ENTITÉS  (20 601 scalaires)    │
├────────────────────────────────────────────────────────────────────────┤
│  CONTEXTE GLOBAL                                                       │
│    global_cont            (11,)                =      11               │
│    global_bin             (22,)                =      22               │
│                                                                        │
│  MES ESCOUADES — ligne 0 = l'unité ACTIVE          K_ALLY_SLOTS = 8    │
│    allies_cont            (8, 19)              =     152               │
│    allies_bin             (8, 32)              =     256               │
│    allies_wpn_cont        (8, 20, 13)          =   2 080               │
│    allies_wpn_bin         (8, 20, 18)          =   2 880               │
│    allies_types_cont      (8, 6, 5)            =     240               │
│    allies_types_bin       (8, 6, 5)            =     240               │
│                                                                        │
│  ESCOUADES ENNEMIES — ordre = slots d'action     K_ENEMY_SLOTS = 20    │
│    enemies_cont           (20, 19)             =     380               │
│    enemies_bin            (20, 32)             =     640               │
│    enemies_wpn_cont       (20, 20, 13)         =   5 200               │
│    enemies_wpn_bin        (20, 20, 18)         =   7 200               │
│    enemies_types_cont     (20, 6, 5)           =     600               │
│    enemies_types_bin      (20, 6, 5)           =     600               │
│                                                                        │
│  MES FIGURINES (individuel)                        SQUAD_TOP_K = 20    │
│    self_models_cont       (20, 2)              =      40               │
│    self_models_bin        (20, 3)              =      60               │
├────────────────────────────────────────────────────────────────────────┤
│  TOTAL vectoriel (= obs_size)                      20 601              │
│  + grid  (7, 32, 32) = 7 168, fournie À PART (non comptée)             │
└────────────────────────────────────────────────────────────────────────┘

Coût d'UNE entité = 19 + 32 (unité) + 20 × (13 + 18) (armes) + 6 × (5 + 5) (types) = 731
   → le bloc ARMES fait 86 % du vecteur. C'est le seul bloc mémoïsé.
```

### Section Breakdown

⚠️ **Repérage par NOM, jamais par index.** Les index se lisent via `global_cont_index("nom")`,
`global_bin_index("nom")`, `unit_cont_index("nom")`, `unit_bin_index("nom")` — ils changent à
chaque évolution du schéma, les noms non. Écrire `obs[314]` dans du code ou un test est
exactement l'erreur que le pipeline legacy a payée.

#### 1. `global_cont` — contexte continu (le seul bloc normalisé par `VecNormalize`)

`turn` · `episode_steps` · `my_victory_points` · `enemy_victory_points` · `my_value_ratio` ·
`enemy_value_ratio` · **`objective_distance_0..4`** — distance à l'hex le plus proche de chaque
zone, en subhex bruts.

#### 2. `global_bin` — contexte discret (JAMAIS normalisé)

`is_my_turn` · `phase` (0 / .25 / .5 / .75 / 1) · `objective_control_0..4` (dans {−1, 0, +1}) ·
`objective_present_0..4` · **`objective_dir_cos_0..4`** et **`objective_dir_sin_0..4`** — vecteur
unitaire vers chaque objectif.

#### 3. `*_cont` d'une unité — 19 features, MÊME schéma ami/ennemi

| Groupe | Features |
|---|---|
| effectif et état | `alive_models`, `hp_total`, `value_alive`, `oc_total`, `model_count_ratio`, `wounded_hp_ratio` |
| position | `col_rel`, `row_rel` (figurine la plus proche du centroïde observateur, **pas** l'ancre), `edge_distance` (bord-à-bord ⚠ non-actives seulement) |
| datasheet | `move`, `hp_max`, `toughness`, `armor_save`, `invul_save` |
| mouvement du tour | `moved_max`, `moved_sum` — distance de **CHEMIN**, porte la clause 3 de [HEAVY] 24.16 |
| engagement ⚠ ACTIVE seule | `n_fight_eligible`, `n_in_enemy_ez`, `n_relayed_ez` |

#### 4. `*_bin` d'une unité — 32 drapeaux, MÊME schéma ami/ennemi

| Groupe | Drapeaux |
|---|---|
| masques | `present` (0 = slot vide ou unité morte), `is_ally`, `is_active` |
| activation du tour | `moved`, `shot`, `fought`, `advanced`, `fled` |
| état | `coherent` (03.03), `engaged` (03.04) |
| terrain ⚠ ACTIVE seule | `hidden` (13.09), `gone_to_ground` (13.5), `in_cover` (13.08, branche intrinsèque) |
| mise en place | `deploy_not_on_board`, `deploy_pre_battle`, `deploy_in_battle`, `deployed_this_turn` (clause 2 de [HEAVY]) |
| paire ⚠ ENNEMIS seuls | `los_can_see` (06.01), `cover_vs_observer` (**13.08 exact**, ses deux branches) |
| **règles d'unité** (13) | `rule_charge_after_advance`, `rule_charge_after_flee`, `rule_charge_impact`, `rule_closest_target_penetration`, `rule_move_after_shooting`, `rule_reactive_move`, `rule_reroll_1_save_fight`, `rule_reroll_1_tohit_fight`, `rule_reroll_1_towound`, `rule_reroll_charge`, `rule_reroll_towound_target_on_objective`, `rule_shoot_after_advance`, `rule_shoot_after_flee` |

**⚠ ACTIVE seule** = à zéro pour les autres entités, masque = `is_active` ·
**⚠ ENNEMIS seuls** = décrit une paire observateur → cible, à zéro pour tout allié.
C'est ce qui préserve le schéma unifié : mêmes colonnes partout, remplies ou masquées.

#### 5. `*_wpn_*` — un profil d'arme (10 slots de tir **puis** 10 de mêlée)

- **13 continues** : `NB`, `ATK`, `STR`, `AP`, `DMG`, portée, **porteurs vivants** — ce dernier
  distingue 1 rokkit de 9 shootas, le volume de feu étant `porteurs × NB` — puis les 5 paramètres
  de règles (`RAPID_FIRE`, `SUSTAINED_HITS`, `MELTA`, `CLEAVE`, `BLAST`), puis le seuil `Y+` de
  [ANTI-X] (0 = aucune règle ANTI).
- **18 drapeaux** : 12 bits de règles (`DEVASTATING_WOUNDS`, `LETHAL_HITS`, `TORRENT`,
  `TWIN_LINKED`, `EXTRA_ATTACKS`, `PRECISION`, `PSYCHIC`, `HAZARDOUS`, `HEAVY`, `IGNORES_COVER`,
  `CLOSE_QUARTERS`, `ASSAULT`) + one-hot du keyword ciblé par [ANTI-X] (`INFANTRY`, `VEHICLE`,
  `FLY`, `PSYKER`, `MONSTER`) + le **mask** du slot.
- ⚠️ [INDIRECT FIRE] 24.19 est **délibérément absente** : la règle n'est pas implémentée, un bit
  pour elle serait du bruit pur. Profils regroupés par identité de caractéristiques ; tout
  dépassement de K est **logué**, jamais silencieux.

#### 6. `*_types_*` — types de figurines (6 slots par unité)

- **5 continues** : `hp_max`, `toughness`, `armor_save`, `invul_save`, `alive_count`.
- **5 drapeaux** : one-hot du rôle d'allocation (règle 19) — `role_special_weapon`,
  `role_sergeant`, `role_support`, `role_leader`, aucun bit = figurine de base — + `present`.

Décrit l'escouade **entière** en quelques dimensions, au lieu de répéter 20 fois le même profil.

#### 7. `self_models_*` — mes figurines (20 slots, l'irréductiblement individuel)

- **2 continues** : `col_rel`, `row_rel`, relatives au centroïde de l'escouade.
- **3 drapeaux** : `fight_eligible`, `in_enemy_ez`, `ez_relayed_by_ally`.

#### 8. `grid` — 7 canaux 32×32 égocentriques

`0` murs · `1` occupation alliée · `2` occupation ennemie · `3` zone d'engagement ennemie ·
`4` objectifs · `5` niveau (étages) · `6` couvert (13.08, dilaté au rayon de socle).

Demi-étendue = **budget d'Advance maximal** de l'escouade (`M + 6″`), ce qui rend la géométrie
indépendante de `inches_to_subhex`. ⚠️ **Aucun clamp** : ce qui dépasse est écarté, pas rabattu
sur le bord — d'où la nécessité des distances/directions d'objectif dans `global_*`.

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
| **D** — ennemis | `enemies_*` | **ordre contractuel = slots d'action de tir** ; porte depuis §0.31 `los_can_see` + `cover_vs_observer` |
| **E** — escouades amies | `allies_[1..K-1]` | livré avec T-D : les alliés sont **agrégés** par le réseau, donc leur ordre n'a pas à être inventé |
| *(transverse)* profils d'armes | `*_wpn_*` | même encodeur pour les deux camps ; 86 % du vecteur, et le seul bloc mémoïsé |
| *(transverse)* règles d'unité | 13 bits dans `*_bin` | §0.31 : sur **toute** entité, amie comme ennemie (schéma unifié) |
| *(transverse)* terrain perçu | `grid` | 7 canaux égocentriques ; **ne porte que la fenêtre** du budget d'Advance |

⚠️ Deux blocs sont **transverses** et non des blocs à part : les profils d'armes et les règles
d'unité vivent DANS chaque entité, par construction du schéma unifié (invariant 1). Chercher un
« bloc armes » ou un « bloc règles » séparé serait chercher ce qui n'existe pas — et le
recréerait en cassant le partage de poids.

**Espace d'action** : une action de tir par slot ennemi (`SHOOT_SLOT_BASE + i`, 20 slots depuis
T-E) ; les logits de ces actions sont produits par une **tête pointeur** (`ai/pointer_policy.py`)
qui score `q · e_i` sur les embeddings — un slot de plus ne coûte donc aucun paramètre. Le
mapping slot ↔ escouade est rafraîchi : les slots des escouades mortes sont rendus, et toute
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

⚠️ **`_bin` ne veut pas dire « binaire »** — il veut dire « **jamais normalisé** ». Trois groupes
de dimensions y sont continues, et y sont **exprès** parce que des statistiques glissantes
détruiraient leur sémantique ou amplifieraient leur bruit : `phase` (scalaire ordonné dans
[0,1]), `objective_control_*` (dans {-1, 0, +1}), et `objective_dir_cos/sin_*` (déjà bornés et
centrés). Ne pas « corriger » cela en les déplaçant vers `_cont`.

### Ce qui est mémoïsé, et par quelle clé d'invalidation

L'observation lit **cinq** caches, chacun avec sa propre condition d'invalidation. C'est le point
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
| `_unit_los_pair_cache` | `los_can_see` / `cover_vs_observer` par paire | `(tireur, cible)` | **invalidation ciblée** au choke-point `_touch_unit_los` : toute écriture de position, toute perte de figurine — donc correct même quand un ennemi bouge pendant mon tour (`reactive_move`) |

Le dernier est le seul à ne PAS être « par épisode » : il doit suivre chaque mouvement. Sa
fiabilité a été vérifiée par mesure — 23 398 paires comparées au calcul non caché sur 400 steps,
0 divergence (V11 §0.31).

**`obs_size`** (config d'agent, `observation_params.obs_size`) = nombre TOTAL de scalaires,
grille exclue — calculé par `ObservationBuilder.SQUAD_OBS_SIZE_TARGET`. Historique : 108 (T6) →
199 (refonte du vecteur, 2026-07-25) → 1011 (profils d'armes et règles, 2026-07-26) → 5729
(tenseurs d'entités, T-D) → 12284 (20 slots ennemis, T-E) → 20096 (K armes = 10 par registre,
T-F) → 20166 (plafond du bloc figurines 6 → 20, 2026-07-26) → 20181 (géométrie des objectifs,
2026-07-27) → 20545 (règles d'unité, 13 bits par entité) → **20601** (couvert et visibilité exacts par slot ennemi, 2026-07-27). **Toute évolution du
schéma change cette valeur et rend les `.zip` existants incompatibles : le retrain `--new` est
obligatoire.**

**Les règles d'unité** sont exposées depuis le 2026-07-27 : 13 bits `rule_<effet>` **par entité**
(amie ET ennemie) dans `UNIT_BIN_FIELDS`. ⚠️ Ne pas les confondre avec les « 12 unit-rule flags »
du layout `obs[314:346]` que décrit [`AI_OBSERVATION_Legacy.md`](AI_OBSERVATION_Legacy.md) : ceux-là
appartiennent au pipeline mono-figurine et ont longtemps fait croire que le pipeline squad les
portait déjà.

**Historique et décisions** : [`Implémentation/V11_audit_observation.md`](Implémentation/V11_audit_observation.md)
(§8, §10 ; §7 pour la découpe en blocs A→E) ·
[`V11_agent_rework.md`](Implémentation/V11_agent_rework.md) §9.2.5 (ce qui est observé des règles)
et **§0.31** (objectifs situés, règles d'unité, couvert exact, caches) ·
[`V11_entity_encoder_pointer.md`](Implémentation/V11_entity_encoder_pointer.md) (§1 constats
mesurés, §3 architecture, §6 journal) · [`AI_OBSERVATION_Legacy.md`](AI_OBSERVATION_Legacy.md)
(archive du pipeline mono-figurine).

