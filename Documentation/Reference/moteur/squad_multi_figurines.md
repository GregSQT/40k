# Escouades multi-figurines — pipeline squad du moteur et du gym

**Objet** : le modèle de données `1 unit = 1 escouade (N figurines)` et les contrats du pipeline squad — caches, distances, cohésion, déplacement, charge, tir, mêlée, allocation des blessures, reward — partagés par le gym et le PvP.
**Sources absorbées** : `squad.md` (spec fondatrice v3.7, archivée dans `Documentation/Archives/docs/` avec bandeau retour). Le détail d'audit pré-implémentation reste dans [squad_audit.md](../../Archives/chantiers/squad_audit.md).
**L'état des chantiers fait foi dans Documentation/Roadmap/, jamais ici.**
Les chiffres volatils (obs_size, tailles d'espaces d'action, valeurs de reward) ne sont jamais recopiés : ce document dit où les lire dans le code.

---

## 1. Le modèle de données (PR1)

### 1.1 Escouade, figurines, ancre

- Une unité (`unit`) est une escouade ; ses figurines sont déclarées dans `unit["models"]` (liste ordonnée). Chaque figurine reçoit un id `"<unit_id>#<index>"`.
- **Rétro-compatibilité mono-figurine** : une unité sans clé `models` produit exactement une figurine dérivée de ses propres champs (`_build_models_for_unit`, [shared_utils.py](../../../engine/phase_handlers/shared_utils.py)).
- **Ancre** = figurine vivante de plus petit index (`def _recompute_squad_anchor`, shared_utils.py). `units_cache[squad_id]["col"/"row"]` porte toujours la position de l'ancre ; quand l'ancre meurt, `destroy_model` la recalcule et propage la nouvelle position.
- Chaque figurine porte ses propres caractéristiques : `HP_CUR`/`HP_MAX` (W du datasheet), `OC`, `T`, `ARMOR_SAVE`, `INVUL_SAVE`, `LD`, armes (`RNG_WEAPONS`/`CC_WEAPONS` + index sélectionnés), compteurs `SHOOT_LEFT`/`ATTACK_LEFT`, socle (`BASE_SHAPE`/`BASE_SIZE`, `orientation` 0..5), hauteur (`MODEL_HEIGHT`), niveau d'étage (`level`), keywords et règles propres (`UNIT_KEYWORDS`/`UNIT_RULES` par figurine — les règles « each model » lisent la figurine, jamais l'union d'escouade), et `attached_from` pour les figurines issues d'un personnage attaché (19.04, replié par `_fold_attached_characters`, [game_state.py](../../../engine/game_state.py)).
- Convention `INVUL_SAVE` : `7` = pas de sauvegarde invulnérable (sentinelle posée à l'init dans `_build_models_for_unit` ; un `0` hérité est converti en `7`).
- `SHOOT_LEFT` / `ATTACK_LEFT` sont des **compteurs** (pas des flags) : initialisés par `resolve_dice_value(weapon["NB"], ...)` au début de chaque activation (`squad_shooting_unit_activation_start` / `squad_fight_unit_activation_start`), décrémentés à la résolution, jamais réinitialisés en milieu de résolution.

### 1.2 Les caches (PR1 1b / 1c / 1d)

| Cache | Contenu | Symboles |
|---|---|---|
| `unit_by_id` | index `{unit_id: dict unité}` construit au reset — la convention du dépôt pour retrouver une unité | `get_unit_by_id` / `require_unit_by_id` ([game_utils.py](../../../engine/game_utils.py)) |
| `units_cache` | source de vérité des agrégats des escouades **vivantes** (morts absents du cache) | `build_units_cache`, `update_units_cache_hp`, `is_unit_alive`, `remove_from_units_cache` |
| `models_cache` | source de vérité par-figurine (clé `model_id`) — PR1 1b | `_build_models_for_unit`, `is_model_alive`, `update_model_position`, `update_model_hp`, `destroy_model` |
| `squad_models` | index inverse `squad_id -> [model_id, ...]` (ordre de création) — évite tout scan O(N) de `models_cache` | maintenu par `destroy_model` |
| `squad_cache` | métriques par escouade — PR1 1c | `_compute_squad_cache_entry`, `_recompute_squad_cache` |

#### Contrat units_cache

- `col`/`row` : position de l'ancre.
- `HP_CUR` : somme des HP des figurines vivantes, maintenue par `destroy_model` / `update_model_hp`.
- `OC_TOTAL` : somme des OC des figurines vivantes, **miroir** de `squad_cache["oc_total"]` (PR1 1d) — recalculé par `_recompute_squad_cache` ; l'observation et la logique d'objectifs le lisent ici.
- `occupied_hexes` : union des **empreintes** (footprints de socles) de toutes les figurines vivantes — recalculée par `_recompute_squad_occupied_hexes`.
- `occupied_hexes_by_model` : dict `{model_id: (col, row)}` — source de vérité par-modèle consommée par le frontend (PR4 4e-i), synchronisée à chaque mutation de position.
- `level_by_model`, `floor_height_by_model`, `MODEL_HEIGHT` : verticalité par figurine (engagement 3D §03.04).
- `models_meta_by_model` : profil visuel par figurine, exposé seulement pour les escouades hétérogènes (`_visual_meta`).
- Escouade entièrement détruite : `remove_from_units_cache(squad_id)` + purge de `squad_cache`.

#### Contrat models_cache et points_per_hp

`models_cache` est la source de vérité pendant la résolution des attaques pour tout ce qui est par-figurine (positions, HP, armes copiées à l'init). Aucune lecture de `unit["models"][i]` pendant la résolution.

`points_per_hp` est calculé **par figurine** : `points_per_hp_i = VALUE_i / HP_MAX_i`, où `VALUE_i` est la valeur en points de CETTE figurine (posée par `_build_enhanced_unit`, game_state.py), jamais `unit["VALUE"]` qui porte la valeur de l'escouade. Une escouade hétérogène en points (Boyz + Nob) donne des `points_per_hp` différents d'une figurine à l'autre — tuer le Nob rapporte plus qu'un Boy.

#### Contrat squad_cache

Champs : `is_coherent`, `model_count`, `model_count_at_start` (capturé à l'init, jamais recalculé — sert de dénominateur), `oc_total`, `centroid_col`/`centroid_row` (moyenne des positions vivantes).
Recalcul aux **deux seuls points d'écriture de présence/position** : `destroy_model` et `update_model_position` — systématiquement, jamais « quand ça semble nécessaire ». `model_count_at_start` est préservé à travers les recalculs.

Le même motif « photo de départ » existe au niveau joueur : `value_at_start` et l'effectif de départ par joueur sont capturés au même instant à l'init (les figurines détruites disparaissent des caches, la valeur initiale n'est plus dérivable ensuite).

#### Écriture des positions et HP

- Toute écriture de position passe par `update_model_position` (shared_utils.py) : validations AVANT toute écriture (garde §13.06 — un niveau écrit est un niveau résolu ; orientation 0..5), puis écriture `models_cache`, sync `occupied_hexes_by_model`, recalcul `occupied_hexes`, propagation de l'ancre à `units_cache`, recalcul `squad_cache`. Jamais d'écriture directe d'un cache sans l'autre.
- Toute écriture HP passe par `update_model_hp` / `destroy_model`.
- `validate_squad_coherency` est le recalcul indépendant ; `squad_cache["is_coherent"]` en est le cache de lecture rapide.

### 1.3 Cascade de mise à jour (`destroy_model`)

`destroy_model(game_state, model_id, reason)` retire une figurine et cascade :

- `reason ∈ {"combat", "coherency_removal", "deployment_no_space", "hazard", "strategic_reserves_timeout"}` — toute autre valeur lève.
- Étapes : retrait de `models_cache` puis `squad_models` → recalcul `occupied_hexes` → invalidation des paires LoS du squad → recalcul des règles d'unité en vigueur (19.04 : la mort du dernier bodyguard ou d'un leader éteint des sources de règles ; une figurine tuée par une attaque garde son effet jusqu'à la fin des attaques de l'attaquant via `_finalize_manual_allocation`) → événement `"dead"` explicite dans `action_logs` (chaque mort tracée par modèle + raison) → §24.08 DEADLY DEMISE si l'unité porte la clé → dernière figurine : `remove_from_units_cache` ; sinon recalcul de l'ancre, `HP_CUR` agrégé et `squad_cache`.
- `reason == "coherency_removal"` : retrait réglementaire, pas un kill — aucun reward de mort (le chemin reward discrimine par raison, voir `reward_calculator.py`).
- Damage en excès : si une attaque inflige D à une figurine à X HP (X < D), le surplus est **perdu** — jamais de report sur la figurine suivante.

### 1.4 Formats de données

- **Scénario, positions explicites** : une entrée `units[]` peut déclarer `"models": [{"col", "row", ...}, ...]` — pass-through vers le moteur (PR4 4c, `create_unit` dans game_state.py). Exemple vivant : [scenario_pvp_squad5.json](../../../config/scenario_pvp_squad5.json).
- **Rosters** : `composition[].models` = liste de noms d'unit_type par figurine (profils mixtes par nom : soldat de base, sergent, personnage attaché). `_build_enhanced_unit` pose les specs par figurine (dont `VALUE` par figurine) ; `_fold_attached_characters` replie les personnages attachés dans leur escouade (19.04). Rosters vivants : `config/agents/_p2_rosters/`.

---

## 2. Définition des distances en hex-grid

Contrat fondamental — toutes les distances de jeu sont en **subhexes** ; `inches_to_subhex` est l'échelle du scénario. `calculate_hex_distance` ([combat_utils.py](../../../engine/combat_utils.py)) retourne des subhexes, pas des pouces ni des hexes abstraits.

- **Engagement Range** : 1" horizontal (règle officielle) — mesuré par la primitive `unit_entries_within_engagement_zone` ([spatial_relations.py](../../../engine/spatial_relations.py)), qui applique la géométrie horizontale ET le gate vertical §03.04 (intervalle `[plancher, plancher + MODEL_HEIGHT]` par figurine).
- **Cohésion** : distances lues depuis `game_rules` (déjà pré-scalées ×`inches_to_subhex` par w40k_core à l'init) via `get_coherency_subhex` (`unit_model_cohesion_range`, officiel 2") et `get_cohesion_max_subhex` (`unit_global_cohesion_range`, officiel 9") — voir section 3.
- **`BASE_TO_BASE_SUBHEX = 1`** (shared_utils.py) : distance hexagonale stricte d'ancres. `is_base_to_base` reste le test générique de contact d'ancres ; il n'est **plus** le contrat de 12.03 / 12.08.

### Base-contact 12.03 / 12.08 — le seuil dépend de la métrique

Révisé le 2026-08-04. SOURCE UNIQUE : `model_in_base_contact(game_state, model_id, model_entry)` (shared_utils.py), consommée par le PvP (`_fight_model_in_base_contact`, alias dans fight_handlers.py) ET par le gym (`_assign_cells_toward_enemies`). Le gym gardait sa propre géométrie (`== BASE_TO_BASE_SUBHEX`, distance d'ancre) : deux verdicts opposés sur la même règle selon le chemin.

Le seuil de contact dépend de la métrique, et c'est la règle :

- `euclidean` (x5, x10) : socles multi-cases, « bord à bord » continu → contact = écart <= 0, zone d'engagement **0** ;
- `hex` (x1, cf. `geometry_is_hex`, spatial_relations.py) : `_scale_socle` normalise tout en `round`/1, une figurine tient dans UNE case → contact = cases **adjacentes**, zone **`BASE_TO_BASE_SUBHEX`**.

Un seuil unique ne peut pas servir les deux (mesuré : à x1, deux socles adjacents ont un écart euclidien de 0,2321 et une distance d'empreinte de 1). Verrouillé par [test_engagement_3d_is_data_driven.py](../../../tests/unit/engine/test_engagement_3d_is_data_driven.py) (`test_base_contact_threshold_follows_the_metric`). Le reste passe par la primitive d'engagement, sans une ligne de géométrie dans le prédicat.

### Directions hexagonales — offset avec parité de colonne

Le moteur utilise une convention offset dont les deltas dépendent de la **parité de la colonne** — il n'existe pas de deltas fixes universels. Ordre déterministe des 6 voisins : indices 0..5 = N, NE, SE, S, SW, NW (`get_hex_neighbors`, combat_utils.py ; colonnes paires : NE=(+1,-1), SE=(+1,0) ; impaires : NE=(+1,0), SE=(+1,+1)).

**Ne jamais hardcoder de deltas** pour NE/SE/SW/NW — toujours appeler `get_hex_neighbors(col, row)` et indexer le résultat. Les translations rigides de bloc se font en coordonnées **cube** (`offset_to_cube`/`cube_to_offset`, hex_utils.py) : en offset, une translation à dx impair change la parité de colonne et déforme le bloc.

---

## 3. Cohésion (03.03)

Source unique du verdict par figurine : `coherency_violation_flags` (shared_utils.py), partagée par le commit des plans (`_positions_in_coherency`) ET le voile rouge per-model des handlers move/charge/fight.

- **1re puce** — « within 2" of at least one other model », précisée par la FAQ : l'escouade doit former **une seule chaîne** (composantes connexes du graphe des voisins ; les figurines du composant minoritaire sont en violation). `game_rules.squad_min_neighbors` (`get_min_neighbors`) exige en plus un degré minimal par figurine.
- **2e puce** — « within 9" of every other model » : critère **par paires** (pas un cercle d'étalement — l'ancienne version en dessinait un, cassant l'invariance par translation dont dépendent `erode_move_pool_by_squad_block` et `explain_move_plan_rejection`).
- Escouade <= 1 figurine : jamais en violation.
- **Métrique** : `game_rules.cohesion_distance_mode` — `euclidean` (bord-à-bord continu, cohérent avec les halos du rendu) ou `footprint` (distance hex empreinte-à-empreinte). À `geometry_is_hex` (x1), le mode est forcé `footprint` : une figurine tient dans une case, la cohésion se mesure de centre d'hex à centre d'hex.
- `validate_squad_coherency(game_state, squad_id)` : recalcul indépendant depuis `models_cache` (ne lit jamais `squad_cache["is_coherent"]`) — pour les validations critiques ; le cache sert aux lectures rapides.
- Un move qui ne peut pas terminer en cohésion est **refusé en bloc** (aucun déplacement partiel) — voir la validation des plans, section 6.

### Retrait de fin de tour (PR3 3g)

Étape End of Turn — REGAINING COHERENCY (03.03), sur **toutes** les escouades des **deux** joueurs : `end_of_turn_regain_coherency_all_squads` (shared_utils.py).

- Sièges muets (bot PvE) et escouades de l'adversaire du joueur courant : retrait **automatique déterministe** — `end_of_turn_coherency_removal` retire en boucle la figurine la plus éloignée du centroïde (tie-break : index croissant), via `destroy_model(reason="coherency_removal")`, jusqu'à cohésion retrouvée.
- Sièges actifs du joueur courant (agent gym, humain PvP) : retrait **interactif** — queue `pending_coherency_removal_queue`, armée escouade par escouade par `arm_next_coherency_pending` ; l'ordre des candidats est celui de l'observation (`ObservationBuilder._squad_models_for_observation`).
- Les figurines retirées ainsi ne déclenchent aucune règle de mort (pas de reward kill — cf. section 1.3).

---

## 4. Move par-figurine — les briques

La numérotation « brique N » vient du plan de câblage du chantier move par-figurine ; le code en cite deux.

### Brique 1 — moteur : plan par-figurine et commit

- BFS des hexes atteignables pour **une** figurine ([movement_handlers.py](../../../engine/phase_handlers/movement_handlers.py), pool par-figurine) : budget = MOVE de l'escouade en subhexes, origine = position `models_cache` (les moves par-figurine ne sont pas committés avant Validate) ; le paramètre `provisional_plan` substitue les positions provisoires des figurines déjà déplacées du plan (leurs hexes d'origine ne bloquent pas).
- `commit_move_plan` (movement_handlers.py) : valide puis commit un plan provisoire — `action["plan"]` = liste `[model_id, col, row, level(, orientation)]` qui **doit couvrir toutes les figurines vivantes** de l'escouade (sinon la cohésion est fausse) ; move `normal` ou `fall_back` selon l'engagement de l'escouade au commit (`infer_squad_move_type` / `classify_squad_move_type`, shared_utils.py). Aucun reactive move n'est déclenché ici (note brique 1 du code).
- Budgets : `get_squad_move_budget` (shared_utils.py) ; Advance : jet D6 par escouade **figé** dans `game_state["advance_rolls"]`, relu par `_advance_roll_for` (movement_handlers.py) — un squad déjà advancé réutilise son jet.

### Brique 3 — front : mode plan par-figurine (PvP)

Flux dans [BoardPvp.tsx](../../../frontend/src/components/BoardPvp.tsx), [useEngineAPI.ts](../../../frontend/src/hooks/useEngineAPI.ts), [boardClickHandler.ts](../../../frontend/src/utils/boardClickHandler.ts) :

- **Plan provisoire non committé au backend** : état `squadMovePlan` — `models` (position + niveau + orientation provisoires par figurine), `originModels` (positions de **début de mode**, pour le reset par-figurine et le cancel escouade), `perModelValid` (voile rouge), `canValidate`.
- Entrée : single-clic sur une figurine en phase move ; le ghost rend les figurines aux positions du **plan** (pas `units_cache`) ; le fantôme ne suit le curseur que si une figurine est active.
- Voile rouge sur les figurines invalides (hex interdit OU hors cohésion) ; bouton Validate actif seulement quand toutes les figurines sont valides + cohésion OK → commit atomique (`commit_move_plan`).
- Clic droit en mode plan = annule le déplacement de la figurine (retour à `originModels`).
- Le budget de chaque figurine est mesuré depuis sa position d'**origine**, pas depuis sa destination après un premier déplacement — sinon le joueur contournerait son budget M.

---

## 5. Déploiement d'escouade

Le déploiement est un **plan par-figurine** ([deployment_handlers.py](../../../engine/phase_handlers/deployment_handlers.py), section « DÉPLOIEMENT PAR ESCOUADE (plan par-figurine) ») :

- pool d'ancres valides par figurine (miroir per-fig du pool de move : murs, occupation, clairance verticale de la figurine) ;
- pool de destinations du bloc d'escouade : `deployment_build_squad_destinations_pool` (les translations se font en coordonnées cube, même contrat que `build_rigid_plan`) ;
- positions explicites de scénario : si l'entrée `units[]` porte `"models": [...]`, les figurines sont posées exactement à ces positions (pass-through PR4 4c).

---

## 6. Mouvement d'escouade — pipeline mutualisé (PR2 2a)

Tous les types de déplacement partagent le même pipeline moteur ; seules les contraintes varient.

### Transaction atomique

1. Calculer le plan complet (destination par figurine) **sans** toucher `models_cache` ni `units_cache`.
2. Valider l'intégralité du plan.
3. Si valide : appliquer toutes les écritures en une passe. Si invalide : aucune écriture (pas de rollback nécessaire).
4. Une seule figurine illégale = refus global (aucun déplacement partiel).

Ce pattern s'applique à tous les moves : Normal, Advance, Fall Back, Charge, Pile In, Consolidation.

### Les trois primitives (shared_utils.py)

- `build_rigid_plan(anchor_dest_col, anchor_dest_row, squad_id, game_state)` : translation rigide depuis l'ancre en coordonnées cube, appliquée à toutes les figurines — Normal / Advance / Fall Back. Retourne le plan (4-uplets `(model_id, col, row, level)`) ou None. Aucune validation ici.
- `validate_move_plan(plan, game_state, constraints)` : plateau, collisions, budget par figurine, ER ennemi, cohésion — `constraints` paramétrable par type de déplacement. Commun à tous les types.
- `commit_move(plan, game_state, move_type)` : écrit toutes les positions en une passe et pose les flags post-move. `move_type ∈ {"normal", "advance", "fall_back", "charge", "pile_in", "overrun_pile_in", "consolidation"}` ; `"advance"` → `units_advanced.add`, `"fall_back"` → `units_fled.add`, les autres → aucun flag. Les entrées de plan portent le niveau demandé (résolu §13.06 par `place_model_at_effective_level` avant écriture) et optionnellement l'orientation. Mesure au passage la distance parcourue par figurine ([HEAVY] 24.16 + observation).

Charge, Pile In et Consolidation ont leurs propres planificateurs (déplacements individuels — sections 8 et 9) mais committent par `commit_move`.

Note : le snap automatique d'une figurine invalide vers un hex proche (`apply_snap_corrections`) n'a **jamais été câblé** et a été supprimé (décision 2026-08-03). Le flux retenu est le voile rouge : une figurine mal posée reste où elle est et s'affiche invalide, l'ajustement est manuel.

### Flags post-mouvement

- `units_advanced` : tir interdit ce tour sauf armes [ASSAULT] (`_advance_blocks_weapon`), charge interdite.
- `units_fled` : tir interdit (sauf règle d'unité `shoot_after_flee`), charge interdite.
- Les deux sets sont resetés en début de **Command phase** ([command_handlers.py](../../../engine/phase_handlers/command_handlers.py)) — reset global, correct car la Command phase précède Movement dans le même tour.

---

## 7. Charge d'escouade (PR2 2c)

- **Éligibilité** : au moins une figurine vivante à <= 12" d'au moins une figurine ennemie (`charge_max_distance`, mesure figurine la plus proche — jamais l'ancre) ; interdit si `units_advanced` / `units_fled` ; interdit si déjà en ER ennemi.
- **Jet** : 2D6 (`roll_charge_distance`, avec relance éventuelle `unit_can_reroll_charge`).
- **Plan** : `charge_build_valid_plan(game_state, squad_id, target_squad_ids, charge_roll, intent)` (shared_utils.py) — multi-cibles supporté (liste de cibles). Par figurine, index croissant :
  - (a) priorité : finir **engagée** avec une cible (11.04 WHILE MOVING — « each model that can end its move engaged with one or more charge targets must do so ») ;
  - (b) sinon : se rapprocher de la cible la plus proche, hors ER des non-cibles.
- **Validation finale** : l'**unité** doit être engagée avec **chacune** des cibles déclarées (11.04 AFTER MOVING ; 03.04 : une unité est engagée dès qu'une de ses figurines l'est) + cohésion (03.01). La condition (b) ne garantit pas l'engagement — une charge dont la validation finale échoue échoue en entier, aucune figurine ne bouge.
- **Engagement, pas adjacence** (révision 2026-08-01) : les destinations « au contact » sont filtrées par `unit_entries_within_engagement_zone` — la primitive de la validation finale — jamais par les voisins hexagonaux du centre d'une cible (à x5 un voisin est à 0,2" quand l'ER en vaut 2 ; l'ancienne géométrie faisait échouer toutes les charges d'escouade).
- **Verticalité** : une charge est un move (11.04 EFFECT) — la descente s'ajoute au jet (13.06, `squad_descent_penalty_subhex`), et le plan porte le niveau d'arrivée.
- Transaction atomique ; commit via `commit_move(plan, gs, "charge")` ; l'escouade rejoint `units_charged` et bénéficie de **Fights First** ce tour (`is_fights_first`, fight_handlers.py — ability 24.13, source V1 = charge move de ce tour).
- Côté gym, la cible de charge est une dimension d'action (slots simples et paires de cibles) — voir l'en-tête de [macro_intents.py](../../../engine/macro_intents.py).

---

## 8. Tir d'escouade (PR3 3a / 3b / 3c)

### Pending intents (PR3 3a)

- `game_state["pending_squad_shoot_intents"]` / `["pending_squad_fight_intents"]` : déclarations en attente, par escouade attaquante.
- Lifecycle : créés à l'activation (`squad_shooting_unit_activation_start` / `squad_fight_unit_activation_start`), nettoyés par `end_activation` quelle que soit l'issue, **jamais** persistés entre deux activations. Un pending résiduel au début d'une activation lève (`assert_no_pending_shoot_intent` / `assert_no_pending_fight_intent`) ; libération explicite par `clear_pending_shoot_intent` / `clear_pending_fight_intent`.
- Chaque intent de tir capture `target_squad_size_at_declaration` — la taille de l'escouade cible **au moment de la déclaration**, utilisée par le bonus [BLAST] à la résolution (`_blast_extra_dice_per_five`).

### Déclaration et verrouillage (PR3 3b)

Règle : toutes les cibles de toutes les armes sont sélectionnées **avant** la première résolution.

- Activation : `squad_shooting_unit_activation_start` — reset `SHOOT_LEFT` par figurine via `resolve_dice_value(NB)` de l'arme sélectionnée.
- Déclaration automatique : `squad_declare_shoot(game_state, attacker_squad_id, priority_target_squad_id, eligible_target_slots)` — par figurine, index croissant : (1) la cible prioritaire si la figurine peut la tirer ; (2) sinon le premier slot éligible ; (3) sinon la figurine ne tire pas. **Pas de TTK résiduel** (décision assumée dans le code : l'overkill est un signal implicite — les attaques sur une cible déjà morte sont perdues, aucune pénalité explicite).
- Ciblage par figurine (règles officielles) : chaque figurine peut cibler une escouade différente ; les attaques d'une même arme ranged ne se splittent pas entre cibles.
- Type de tir 10.04–10.06 : `resolve_squad_shooting_type` / `eligible_squad_shooting_types` commandent quelles armes sont sélectionnables ; tir indirect : `indirect_shooting_applies`.
- Flux manuel PvP : déclaration par figurine et par arme (`squad_declare_shoot_model`, `squad_declare_shoot_weapon`, quantités, undeclare) — mêmes intents, même verrouillage.
- Verrouillage : `squad_lock_shoot` — toute modification des intents après ce point est un bug ; la résolution lit la liste verrouillée et la nettoie en fin.

### Locked in combat et cibles protégées

- **04.02 — cible non engagée** : une escouade ennemie en zone d'engagement d'une unité alliée au tireur ne peut pas être ciblée (`_target_locked_by_ally`, `_shoot_engagement_blocks_target`, `_friendly_engagement_blocks_ranged_shot` dans shooting_handlers.py).
- **10.06 — tireur engagé** : ne peut tirer qu'avec une arme au trait CLOSE_QUARTERS (24.07), et seulement sur l'unité avec laquelle il est engagé (`_squads_are_engaged`).
- Monster/Vehicle : prédicat dédié `_model_is_monster_or_vehicle` pour les clauses 10.04–10.06 qui les concernent.
- Il suffit qu'**une** figurine de l'escouade soit engagée pour que l'escouade le soit (03.04).

### LOS cache — stratégie avec escouades

Contrat per-fig (cité par le code sous ce titre) : une figurine attaquante peut cibler l'escouade ennemie si **au moins une figurine cible** est à la fois à portée de l'arme sélectionnée ET visible depuis la position de la figurine attaquante — la LoS est testée **figurine → figurine cible**, jamais ancre → ancre (`_model_can_shoot_target`, `_attacker_model_can_reach_squad`, `squad_shoot_los_overview` dans shared_utils.py). La mort d'une figurine réduit le footprint du squad et invalide ses paires LoS (`_touch_unit_los`, appelé par `destroy_model`).

### Résolution (PR3 3c)

Séquence par attaque, identique tir et mêlée :

1. **Hit roll** vs BS/WS (modificateurs de règles d'armes : [attack_sequence.py](../../../engine/phase_handlers/attack_sequence.py)).
2. **Wound roll** — table W40K 10e (`wound_threshold(strength, toughness)`) : S >= 2T → 2+ ; S > T → 3+ ; S == T → 4+ ; S < T → 5+ ; S <= T/2 → 6+.
3. **Save roll** — `save_threshold(armor_save, invul_save, ap)` : meilleure des deux sauvegardes, AP appliquée à l'armure seulement.
4. **Damage** — alloué à la figurine réceptrice ; `HP_CUR` à 0 → `destroy_model` ; excès **perdu** (pas de carry-over).

- [BLAST] : attaques bonus par tranche de 5 figurines dans la cible **à la déclaration** (`_blast_extra_dice_per_five` × `target_squad_size_at_declaration`) ; interdit à bout portant si un ennemi est adjacent au tireur.
- Figurine attaquante morte en cours de résolution : ses attaques restantes sont annulées ; les attaques déclarées **contre** elle sont résolues normalement.
- Mortal Wounds : `allocate_mortal_wounds` (shared_utils.py).
- Le flux d'allocation manuelle (PvP) et la décision d'agent (gym) partagent le même pipeline : `_build_manual_allocation`, `_manual_allocation_step`, `_finalize_manual_allocation`, `build_manual_shoot_allocation`, `apply_manual_shoot_allocation` — mutualisé tir/mêlée/hazard.

### Allocation des blessures (05.04)

Point unique de variation : `_select_allocation_model(game_state, target_squad_id, alive)` — choisit la figurine du squad cible qui encaisse la prochaine attaque :

1. **(règle)** une figurine déjà blessée (`HP_CUR < HP_MAX`) en priorité — obligatoire ;
2. heuristique défensive sur les figurines pleines : tier de rôle croissant (base < special_weapon < sergeant < support < leader, `ROLE_TIER`) ;
3. proximité de l'ennemi le plus proche ;
4. index (tie-break déterministe).

En PvP, le défenseur humain choisit la figurine réceptrice (les blessées restent forcées d'abord) ; en gym, `_arm_allocation_model_decision` pose une décision d'agent quand tous les modèles du groupe sont sains. [PRECISION] : `_apply_precision_allocation_override`.

---

## 9. Fight phase d'escouade (PR3 3d / 3f)

### Structure V11 de la phase

La phase de combat est pilotée par `fight_subphase` ([fight_handlers.py](../../../engine/phase_handlers/fight_handlers.py)) :

1. **PILE IN** (12.02) — étape groupée : joueur **actif d'abord** (toutes ses unités éligibles), puis l'adverse (`fight_v11_grouped_next`) ; une unité = un move max par étape (`pile_in_done`).
2. **FIGHT** (12.04) — machine de sélection exhaustive `fight_v11_advance_selection` : `fight_step ∈ {"fights_first", "remaining"}`, `fight_selector` alterné entre joueurs avec handoff quand un camp n'a plus d'unité éligible ; à l'entrée de l'étape, sélecteur = joueur actif (`fight_v11_enter_fight_step`, qui prend le snapshot `engaged_at_fight_step_start` APRÈS le pile-in groupé) ; si des unités Fights First redeviennent éligibles pendant Remaining, retour au step fights_first. Une unité ne s'active qu'une fois (`units_selected_to_fight`).
3. **CONSOLIDATE** (12.07) — étape groupée, même ordre que le pile-in (`consolidation_done`).

**Fights First** : `is_fights_first` (24.13) — source actuelle = `units_charged` (le charge move de ce tour confère l'ability jusqu'à la fin du tour).

**Éligibilité à combattre** : au moins une figurine dans l'ER d'une unité ennemie, OU charge effectuée ce tour (`fight_v11_eligible_unit_ids`).

### Activation (PR3 3d)

`squad_fight_unit_activation_start` (shared_utils.py) : vérifie l'absence de pending résiduel, initialise `pending_squad_fight_intents[squad_id]`, reset `ATTACK_LEFT` par figurine via `resolve_dice_value(NB)` de l'arme CC sélectionnée. L'auto-sélection d'arme n'est PAS faite ici — elle exige de connaître T/Sv de la cible (voir Déclaration). `squad_fight_restart_activation` écrase une déclaration non résolue (chemins de résolution directe).

### Pile In

`fight_pile_in_plan(game_state, squad_id)` (shared_utils.py) — transaction atomique, aucune écriture cache :

- chaque figurine **non en base-contact** avec un ennemi peut se déplacer jusqu'à 3" pour (a) finir en base-contact si possible — **obligatoire** si les conditions sont remplies — sinon (b) minimiser la distance au plus proche ennemi ;
- une figurine déjà en base-contact ne bouge pas (12.03 WHILE MOVING — verdict par `model_in_base_contact`, section 2) ;
- ordre par index, tie-break déterministe ; placement par `_assign_cells_toward_enemies` (horizontal : chaque figurine reste à son étage) ;
- validation finale : cohésion + au moins une figurine dans l'ER ennemi ; échec → None, aucune figurine ne bouge ;
- variante overrun : `_fight_overrun_pile_in_plan` (commit `move_type="overrun_pile_in"`).

### Quelles figurines peuvent frapper — 04.02

⚠️ Corrigé le 2026-08-04 — **la « règle du buddy » n'existe pas.** 04.02 SELECT TARGETS, WHILE FIGHTING : « Each target must be engaged with the model that has that weapon » ; 03.04 : engagé = <= 2" horizontal ET <= 5" vertical. Il n'y a **qu'une** condition. Le relais d'attaque par une alliée au contact venait d'une édition antérieure : `base-contact` n'apparaît dans les 25 PDF que pour dire qu'une figurine au contact ne bouge pas au pile-in.

Le pool des figurines qui frappent est rendu par `get_fighting_models(game_state, squad_id, target_squad_id)` — la primitive `unit_entries_within_engagement_zone` sur une entrée synthétique par figurine, même mesure que la résolution, gate vertical §03.04 compris. `target_squad_id` porte la moitié « with the model » de 04.02 et n'est **pas** optionnel à la déclaration : sans lui, une escouade coincée entre A et B qui déclarait B frappait avec ses figurines qui ne touchent que A. La forme sans cible survit uniquement pour l'observation (« cette figurine est-elle au combat ? », calculée avant tout choix de cible).

### Déclaration des attaques (PR3 3f)

`squad_declare_fight(game_state, attacker_squad_id, target_squad_id)` :

- éligibilité par figurine = `get_fighting_models(..., target_squad_id)` (04.02) ;
- **auto-sélection de l'arme CC** par figurine : arme maximisant l'expected damage `P(hit) × P(wound) × P(failed_save) × D` contre la T et la sauvegarde **réelle** de la cible (invulnérable de Waaagh! comprise — `effective_invul_save`) ; à égalité, index le plus bas ; `ATTACK_LEFT` recalculé si l'arme change (§ « Auto-selection de l arme ») ; armes [EXTRA ATTACKS] ajoutées par `_extra_attacks_weapon_indices` ;
- règle officielle : les attaques de mêlée d'une même arme **peuvent** être splittées entre cibles — le flux auto déclare une cible unique par activation (déclaration puis résolution, même pattern que le tir) ; côté gym, la sélection multi-cibles passe par les actions de charge en paire et les activations successives ;
- déclarations verrouillées avant la première résolution ; résolution et allocation identiques au tir (section 8).

### Consolidation

`squad_consolidate_plan(game_state, squad_id)` — 12.08, 3" max par figurine, **cascade obligatoire** dont le mode est imposé par la situation (`fight_v11_consolidation_mode`, fight_handlers.py) :

1. **Ongoing** : l'unité est engagée → chaque figurine vers les ennemis engagés ;
2. **Engaging** : un ennemi à <= `consolidation_trigger_range` (3") → vers ces ennemis ;
3. **Objective** : un objectif à <= 3" → chaque figurine vers la zone de cet objectif ;
4. sinon : pas de consolidation.

Validations finales : cohésion toujours ; ER pour (1)/(2) ; zone d'objectif pour (3). Atomique — plan ou None.

---

## 10. Reward — shaping proportionnel aux points

Le reward des actions squad est **proportionnel à la valeur en points**, jamais plat ([reward_calculator.py](../../../engine/reward_calculator.py), `_squad_combat_shaping` — « Composantes (spec squad_multi_figurines.md) ») :

- `points_per_hp × hp_damage_weight × damage` — signal continu à chaque HP retiré ;
- `model_value × model_kill_bonus_factor` — bonus à la mort d'une figurine (VALUE de **cette** figurine : tuer le Nob rapporte plus qu'un Boy) ;
- `value × squad_kill_bonus_factor` — bonus de squad wipe ;
- symétrie défensive obligatoire : les mêmes composantes en négatif pour les pertes propres ;
- `-incoherent_weight` par escouade du joueur contrôlé hors cohésion.

Les coefficients (`squad_shaping` : `hp_damage_weight`, `model_kill_bonus_factor`, `squad_kill_bonus_factor`, `incoherent_weight`) se lisent dans `config/agents/<agent>/<agent>_rewards_config.json` — jamais recopiés ici.

Décisions actées :

- **Contrôle d'objectif** (2026-07-30) : `oc_weight` abandonné, jamais implémenté — le contrôle est payé par `objective_rewards.objective_reward_factor` × les VP que la mission attribue, versés une fois par tour à la phase command du joueur contrôlé (l'instant exact où la mission attribue les VP). Un bonus par fin de phase paierait des états de contrôle sans VP : l'agent optimiserait la mesure de substitution. La conservation d'un objectif d'un tour sur l'autre s'apprend par la value function, pas par un signal dense. Le contrôle lui-même est réévalué à chaque checkpoint (14.02, `run_objective_control_checkpoint`, game_state.py).
- **Overkill** : aucune pénalité explicite — déclarations verrouillées avant résolution, les attaques sur une cible déjà morte sont perdues (zéro damage, zéro reward). Signal implicite suffisant.
- **`reason="coherency_removal"`** : aucun reward négatif de mort (retrait réglementaire) ; `incoherent_weight` pénalise la situation en amont, pas le retrait. Même traitement pour `desperate_escape_died` et `select_coherency_removal` (le reward kill transite par le chemin combat).

---

## 11. Observation, masques et espace d'action (PR4 4b / 4d)

L'observation squad décrite par la spec d'origine (vecteur plat, top-k figurines, 5 slots ennemis) a été remplacée par les **tenseurs d'entités** V11. Référence canonique : [observation_et_actions.md](../training/observation_et_actions.md) — `obs_size` et les formes se lisent dans [observation_entities.py](../../../engine/observation_entities.py) et l'en-tête « OBSERVATION SQUAD » d'[observation_builder.py](../../../engine/observation_builder.py) (`build_squad_observation`), jamais ici.

- **Espace d'action** : layout et tailles dans l'en-tête de [macro_intents.py](../../../engine/macro_intents.py) (`TOTAL_ACTION_SIZE`, dérivations `*_SLOT_BASE`/`*_SLOT_COUNT`). Une action de mouvement désigne une **cellule** de la grille égocentrique ([observation_et_actions.md](../training/observation_et_actions.md)) ; le type de move (normal/advance/fall_back) n'est pas une dimension d'action — il est inféré du coût géodésique (`infer_squad_move_type`). Cibles de tir, de charge (simple et **paires** multi-cibles) et de mêlée sont des dimensions d'action indexées sur le même mapping de slots ennemis (invariant D1).
- **Masque squad** (PR4 4b) : `build_squad_action_mask` (shared_utils.py) — aucune action illégale ouverte ; toute règle d'éligibilité de ce document (flags advanced/fled, engagement, éligibilité fight) s'y reflète.
- **Slots ennemis** (PR4 4d ; V11 §0.30 T-E) : `init_enemy_slot_mapping` construit le mapping à l'init (idempotent), slots attribués par **menace décroissante**, départage par index de création. `_refresh_enemy_slot_mapping` maintient deux propriétés non négociables : une escouade vivante déjà mappée **garde** son slot (stabilité de l'invariant D1) ; une escouade vivante sans slot **en reçoit un** dès qu'un slot se libère (mort ou hors table) — sinon elle resterait intirable toute la partie. Un dépassement de capacité est logué, jamais silencieux. Lecture : `get_enemy_slot_mapping`.
- Entrée moteur des actions squad du gym : `_process_squad_action` ([w40k_core.py](../../../engine/w40k_core.py)).

---

## 12. Périmètre d'origine — état actuel des exclusions MVP

La spec d'origine excluait plusieurs règles « hors périmètre MVP ». État vérifié dans le code :

| Exclusion d'origine | État actuel |
|---|---|
| Leaders / Attached Units | **Implémenté** — 19.04 : `_fold_attached_characters` (game_state.py), `attached_from` par figurine, `recompute_unit_rules_in_effect` |
| Battleshock | **Implémenté** — 08.03 : `command_step_battle_shock` (command_handlers.py), impact OC et Fall Back (`squad_is_battle_shocked_in_enemy_er`) |
| Desperate Escape Tests | **Implémenté** — movement_handlers (Fall Back à travers l'EZ), raison de mort `desperate_escape_died` (reward_calculator.py) |
| Weapon keywords (Lethal Hits, etc.) | **Implémentés** — socle commun tir/mêlée dans attack_sequence.py ; prédicat `weapon_has_rule` (engine/utils/weapon_helpers.py) |
| Mortal Wounds natifs | **Implémenté** — `allocate_mortal_wounds` (shared_utils.py) |
| Charge multi-cibles | **Implémenté** — `charge_build_valid_plan(target_squad_ids)` + slots de paires côté action (macro_intents.py) |
| Deep Strike / réserves | **Implémenté** — voir [capacites.md](capacites.md) §4 ; raison de mort `strategic_reserves_timeout` (20.04) |
| Overwatch | **Toujours absent** (aucune occurrence dans engine/) |
| Wound allocation « this phase » | Déviation résorbée autrement : la priorité aux blessées lit `HP_CUR < HP_MAX` (persistant), pas un compteur par activation — section 8 |
| Split mêlée d'une même arme | Toujours auto-cible unique par activation dans le flux auto (section 9) |

---

## Historique et sources

- **Spec fondatrice** : `squad.md` v3.2 → v3.7 (2026-05), spec d'implémentation du passage `1 unit = 1 figurine` → `1 unit = 1 escouade`, plan en 4 PR. Audit pré-implémentation : [squad_audit.md](../../Archives/chantiers/squad_audit.md) (tranches 1a–1d, N_global, formats config).
- **PR livrées** : PR1 (data model + caches), PR2 (mouvement + charge, moteur), PR3 (tir + fight déclaration/résolution + retrait de cohésion), PR4 4a–4e-i (pipeline parallèle : obs/masque squad, pass-through modèles, slots ennemis, `occupied_hexes_by_model`). Les étapes PR4 4e-iii à 4e-viii (configs + wiring + retrain de l'ancienne obs 108-dim) ont été **supplantées par le pipeline V11** (obs tenseurs d'entités, `_process_squad_action`) — l'observation historique et ses dimensions sont décrites dans [AI_OBSERVATION_Legacy.md](../../Archives/docs/AI_OBSERVATION_Legacy.md).
- **Décisions datées structurantes** : 2026-07-30 abandon d'`oc_weight` ; 2026-08-01 charge par zone d'engagement (plus d'adjacence hexagonale) ; 2026-08-03 suppression du snap automatique jamais câblé ; 2026-08-04 suppression de la « règle du buddy » (04.02 : une seule condition d'engagement) et base-contact 12.03/12.08 dépendant de la métrique.
- Suppression historique : `fight_handler_new_bugged.py` (fichier mort, zéro référence) supprimé en PR1.

---

## Correspondance des sources

Identifiants cités par le code (`squad.md brique N`, `squad.md PRn xx`, `spec §"..."`) → section actuelle :

| Source (squad.md) | Identifiant cité | Section actuelle |
|---|---|---|
| Nouveau modele de donnees cible | — | §1 Le modèle de données |
| Contrat `units_cache` | spec §"Contrat units_cache" | §1.2 Contrat units_cache |
| Contrat `models_cache` / `points_per_hp` | PR1 1b | §1.2 Contrat models_cache |
| Contrat `squad_cache` | PR1 1c | §1.2 Contrat squad_cache |
| Miroir OC_TOTAL | PR1 1d | §1.2 Contrat units_cache |
| Cascade de mise a jour (`destroy_model`) | spec §"Cascade de mise a jour" | §1.3 Cascade de mise à jour |
| Definition des distances en hex-grid | squad.md §"Definition des distances en hex-grid" | §2 Définition des distances en hex-grid |
| Regles de cohesion | — | §3 Cohésion (03.03) |
| Retrait fin de tour | PR3 3g | §3 Retrait de fin de tour |
| Move par-figurine (moteur) | brique 1 | §4 Brique 1 — moteur |
| Move par-figurine (front PvP) | squad.md brique 3 | §4 Brique 3 — front |
| Deploiement escouade | — | §5 Déploiement d'escouade |
| Mouvement coordonne / infrastructure mutualisee | PR2 2a | §6 Mouvement d'escouade |
| Charge escouade | PR2 2c | §7 Charge d'escouade |
| Pending intents | PR3 3a | §8 Pending intents |
| Tir : declaration / lock | PR3 3b | §8 Déclaration et verrouillage |
| LOS cache — strategie avec escouades | squad.md §"LOS cache — strategie avec escouades" | §8 LOS cache — stratégie avec escouades |
| Tir : resolution | PR3 3c | §8 Résolution |
| HP tracking — allocation prioritaire | — | §8 Allocation des blessures (05.04) |
| Fight : activation + ordering | PR3 3d | §9 Structure V11 + Activation |
| Pile In | spec §"Pile In" | §9 Pile In |
| Auto-selection de l'arme | spec §"Auto-selection de l arme" | §9 Déclaration des attaques |
| Fight : declaration + resolution + consolidation | PR3 3f | §9 Déclaration / Consolidation |
| Reward function | « spec squad.md » (reward_calculator) | §10 Reward |
| Squad action mask | PR4 4b | §11 Observation, masques et espace d'action |
| Pass-through `models` scenario | PR4 4c | §1.4 Formats de données |
| Enemy slot mapping | PR4 4d ; V11 §0.30 T-E | §11 Slots ennemis |
| occupied_hexes_by_model | PR4 4e-i | §1.2 Contrat units_cache |
| Observation / action space (micro) | — | §11 (renvoi [observation_et_actions.md](../training/observation_et_actions.md)) |
| Perimetre MVP — hors scope | — | §12 Périmètre d'origine — état actuel |
