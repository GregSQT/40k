# Architecture du moteur — modules, flux, caches

> **Objet** : référence de conception du moteur de jeu (`engine/`) — carte des modules, flux d'un step gym et d'une action PvP, invariants d'architecture, patterns transverses (validation, caches, logging).
> **Source absorbée** : `AI_IMPLEMENTATION.md` (ce dossier) — archivée dans `Documentation/Archives/docs/` avec un bandeau retour.
> **L'état des chantiers fait foi dans `Documentation/Roadmap/`, jamais ici.**
> Chiffres volatils (tailles d'espaces, obs, win-rates) : jamais recopiés ici — chaque fois, le fichier + symbole où les lire est indiqué.

---

## Règles de codage IA (CORE AI CODING RULES)

Ces règles s'appliquent à tout code du projet ; les en-têtes de fichiers qui citent « architecture_moteur.md COMPLIANCE » (armories TS, `engine/weapons/`, `engine/ai/weapon_selector.py`, `ai/env_wrappers.py`) renvoient à ce bloc.

- **No implicit recovery** : échec immédiat sur donnée manquante ou invalide.
- **No temporary/hacky solutions** : toujours la solution claire et minimale.
- **No hidden/implicit values** : tout paramètre réglable vit en configuration ou objet de domaine.
- **No silent defaults** : une valeur manquante lève une erreur.
- **Prefer simple and efficient designs** : pas d'abstraction inutile.
- **Respect AI_TURN.md** : chaque fonction/module se vérifie contre [tour_de_jeu.md](tour_de_jeu.md) ; s'arrêter si le comportement attendu est flou.

**Contrôle automatisé** : `scripts/check_ai_rules.py` détecte les violations (imprime fichier/ligne, sortie non nulle en cas d'erreur). Il appartient à la vérification large utilisateur (voir CLAUDE.md). Utilisable en hook pre-commit ou en CI.

**Validation des données et configurations** : module [`shared/data_validation.py`](../../../shared/data_validation.py) —
`def require_present(value, name)` lève si `None` ; `def require_key(mapping, key)` lève si la clé manque ; les deux lèvent `ConfigurationError` (défini dans ce même module). Règles : tout accès à une clé de config obligatoire passe par `require_key` ; toute valeur externe obligatoire passe par `require_present` au premier point d'entrée.

---

## Invariants d'architecture

### Source unique : `game_state`

Le dictionnaire `game_state` n'existe que dans `class W40KEngine` (`engine/w40k_core.py`). Tous les autres modules le reçoivent en paramètre ; **aucun module ne le copie ni ne le stocke**.

### `units_cache` et HP_CUR (source unique)

`game_state["units_cache"]` est la source unique de la **position** (`col`, `row`) et du **HP_CUR** des unités **vivantes**. **Mort = absent de `units_cache`.** Pendant la partie, HP_CUR n'est stocké **que** dans `units_cache` ; ne jamais lire/écrire `unit["HP_CUR"]` pour les PV courants. Les helpers vivent dans `engine/phase_handlers/shared_utils.py` :

- **Build** : `def build_units_cache` — appelé **uniquement au reset** (après initialisation des unités), pas en début de phase. Après reset, le cache existe toujours : `require_key(game_state, "units_cache")`, aucun fallback.
- **Écriture HP** : seul `def update_units_cache_hp` écrit HP_CUR (dans le cache uniquement). Les handlers calculent `new_hp` et l'appellent ; ils n'assignent jamais `unit["HP_CUR"]`.
- **Lecture HP** : `def get_hp_from_cache` — `None` si l'unité n'est pas au cache (morte ou absente).
- **Mort** : `update_units_cache_hp(..., 0)` retire l'entrée du cache.
- **Vie** : `def is_unit_alive` — présent au cache **et** `HP_CUR > 0`.
- **Position** : après tout déplacement (MOVE, ADVANCE, CHARGE, FLED), `def update_units_cache_position`.
- **Snapshot** : `game_state["units_cache_prev"]` — copie du cache au **début** de chaque `step()`, consommée par les features de direction de mouvement de l'observation.

### Activation séquentielle et fin de phase par éligibilité

Une unité traitée par step gym. Les pools d'activation par phase (`move_activation_pool`, `shoot_activation_pool`, …) tiennent la file ; une phase se termine quand son pool est vide — jamais par comptage arbitraire de steps. Les steps d'épisode sont comptés au seul endroit `w40k_core.py` (`game_state["episode_steps"]`).

### Champs UPPERCASE

Toutes les stats d'unité sont en MAJUSCULES (`HP_CUR`, `ARMOR_SAVE`, `RNG_ATK`, `CC_STR`, …), validées à l'initialisation par `def validate_uppercase_fields` (`engine/game_state.py`).

### Zéro wrapper

`W40KEngine` implémente directement `gym.Env` ; aucune classe wrapper susceptible de copier l'état.

### TypeScript → Python (source unique des données de jeu)

Unités et armes sont déclarées **une fois** en TypeScript ; Python les parse à l'exécution — aucune déclaration Python dupliquée :

- Unités : `frontend/src/roster/<faction>/units/*.ts`, parsées par `ai/unit_registry.py`.
- Armes : `frontend/src/roster/<faction>/armory.ts`, parsées par `engine/weapons/parser.py`.

Validation fail-fast : toute arme référencée doit exister dans l'armory (`KeyError` au chargement sinon) ; toute référence d'arme d'unité est validée à l'initialisation.

---

## Carte des modules (vérifiée sur le disque)

### `engine/` — racine

| Module | Rôle |
|---|---|
| `w40k_core.py` | `class W40KEngine(gym.Env)` : possède `game_state`, orchestre reset/step, route les phases, délègue tout. |
| `game_state.py` | `class GameStateManager` : initialisation d'état, création/validation d'unités (UPPERCASE), chargement scénario, conditions de fin (`check_game_over`, `determine_winner`). |
| `game_utils.py` | Utilitaires partagés : `get_unit_by_id(game_state, unit_id)` / `require_unit_by_id`, logs console/debug, garde-fous « une seule fois » (`once_claimed`/`once_claim`), limite de tours, `enter_phase`. |
| `observation_builder.py` | `class ObservationBuilder` : observation squad en **Dict de tenseurs d'entités** + grille égocentrique — contrat complet dans [AI_OBSERVATION.md](../training/AI_OBSERVATION.md). |
| `observation_entities.py` | Schéma unifié d'entité pour l'observation squad (V11 §0.30 T-D) : constantes de slots (`K_ALLY_SLOTS`, `SQUAD_TOP_K`, …). |
| `observation_weapon_profiles.py` | Encodage des profils d'armes et bits de règles dans l'observation. |
| `reward_calculator.py` | `class RewardCalculator` : rewards depuis la config de l'agent, pénalités système, rewards situationnels, intégration reward_mapper. |
| `action_decoder.py` | `class ActionDecoder` : masque d'action + décodage entier → action sémantique. |
| `macro_intents.py` | Layout de l'espace d'action — source unique des ids nommés côté `ai/` (miroir de `SQUAD_ACTION_*` de `shared_utils`). |
| `combat_utils.py` | Fonctions pures : normalisation de coordonnées, distance hex, table de blessure 40K, wrappers LoS. |
| `spatial_grid.py` | Géométrie de la grille égocentrique de mouvement — source unique du mapping grille↔hex, `GRID_CHANNELS`. |
| `spatial_relations.py` | Contacts d'empreintes et zones d'engagement (`def unit_entries_within_engagement_zone`). |
| `hex_utils.py` | Primitives hex offset odd-q — source unique (cf. [geometrie_et_distances.md](geometrie_et_distances.md) §2, ex-Boardx10-final §2.2–2.3). |
| `hex_union_boundary_polygon.py` | Contour d'union d'hex en coordonnées monde (`def compute_move_preview_mask_loops_world`) pour le payload preview. |
| `terrain_utils.py` | Appartenance des hex aux aires de terrain (zones polygonales rasterisées au chargement). |
| `objective_distance.py` | Distance d'un hex à l'**aire** d'un objectif (règle 14.02), pas à son centre. |
| `agent_decision.py` | Mécanisme générique « décision agent » (V11 §9.3 P2) : `pending_agent_decision` + candidats `CHOICE_i`. |
| `mask_verification.py` | Vérification par **recalcul** des données mémoïsées entre masque et exécution. |
| `episode_schedule.py` | Rampes pilotées par épisode (V11 §0.57) : conversion budget global → budget par env. |
| `perf_timing.py` | Mesures de latence optionnelles (`W40K_PERF_TIMING=1`). |
| `debug_trace.py` | Traces `[TRAIN DEBUG]` — point d'émission unique, par canal, formatage différé. |
| `action_log_utils.py` | `def append_action_log` + `logSeq` monotone sur les entrées d'`action_logs`. |
| `weapon_damage_cache.py` | Cache par épisode d'espérance de dégâts d'arme, lookup O(1). |
| `constants.py` | Constantes transverses (`DRAW_WINNER`). |
| `pve_controller.py` | `class PvEController` : charge le modèle IA du joueur 2 en PvE, décision par MaskablePPO, choix de règle par valeur (`def select_rule_choice_with_policy`). Aucun fallback heuristique. |
| `weapons/` | `parser.py` : `class ArmoryParser` (parse les armories TS, `get_weapon`/`get_weapons` fail-fast) ; `rules.py` : `class WeaponRulesRegistry` + `def validate_weapon_rules_field` (validation contre `config/weapon_rules.json`). |
| `ai/weapon_selector.py` | Sélection d'arme par espérance (`def select_best_ranged_weapon`, `def select_best_melee_weapon`) ; remplit `kill_probability_cache` à la demande. |
| `utils/` | `expected_damage.py` (espérance de dégâts contextualisée) ; `weapon_helpers.py` (accès aux données d'armes). |
| `roster/` | Paquet de définitions par faction côté moteur (spaceMarine, tyranid). |
| `engine_modules/` | Paquet vide (`__init__.py` seul). |

### `engine/phase_handlers/`

Chaque handler reçoit `game_state` en paramètre, retourne ses résultats sans stocker d'état, et implémente [tour_de_jeu.md](tour_de_jeu.md) exactement.

| Module | Rôle |
|---|---|
| `shared_utils.py` | Cœur mutualisé : `units_cache`, masque squad (`def build_squad_action_mask`, source unique partagée avec le décodeur), mapping de slots ennemis (`def get_enemy_slot_mapping`), résolution des règles d'unités, jets de hasard (`def roll_hazard_for_unit`), chemin squad shoot manuel, `def infer_squad_move_type`, `def calculate_target_priority_score`. |
| `movement_handlers.py` | Éligibilité, destinations valides, exécution du move, détection de fuite, masque monde du preview (`def _sync_move_preview_mask_loops` + cache LRU `_mask_loop_cache`). |
| `shooting_handlers.py` | Éligibilité, pools de cibles, jets hit/wound/save, dégâts, LoS (`def compute_unit_los` — primitive obscuring-aware, règle 13.10), advance quand aucune cible. |
| `charge_handlers.py` | Éligibilité, portée et exécution de charge (BFS de placement, profiling dédié). |
| `fight_handlers.py` | Éligibilité, sélection de cible de mêlée, résolution d'attaques, sous-phases de fight. |
| `command_handlers.py` | Phase de commandement : tâches administratives (reset des marques, purge de caches). |
| `deployment_handlers.py` | Phase de déploiement actif (voir ci-dessous). |
| `generic_handlers.py` | Fonctions génériques AI_TURN.md (END OF ACTIVATION). |
| `attack_sequence.py` | Séquence d'attaque **commune tir/mêlée** (PDF 05 + PDF 24) — une seule implémentation des jets, les PDF de `Documentation/40k_rules/` font foi sur `config/weapon_rules.json`. |
| `geodesic_move.py` | Primitives géodésiques euclidiennes partagées MOVE/CHARGE (la charge est un move, règle 11.04 — seul le budget change). |

### Phase de déploiement (mode `active`)

- Quand le scénario a `deployment_type == "active"`, le match démarre en `phase = "deployment"` ; l'init passe par `def deployment_phase_start` (`deployment_handlers.py`), appelé depuis `w40k_core.py`.
- **État** : `game_state["deployment_state"]` — `current_deployer`, `deployable_units_by_player`, `deployed_units`, `deployment_complete` ; comptabilité **mutable** de la phase, écrite seulement en mode `active`. Unités non placées : `col = -1`, `row = -1`.
- **Zones** : `game_state["deployment_pools"]`, à la **racine** et publiées **quel que soit le mode** (`active`, `fixed`, `random`). Donnée de **scénario**, pas de phase : la clause 20.04 (aucune figurine en zone adverse avant le 3e round) et l'ancre de grille d'une unité hors table en ont besoin hors déploiement. Les murs en sont soustraits **inconditionnellement** (un hex de mur n'est légal dans aucun mode ; l'ancre-barycentre doit être identique `fixed`↔`active`). Clé déclarée **statique** pour les snapshots PvP (`services/game_snapshots.py`) : ré-attachée depuis l'engine vivant au restore.
- **Action** : `deploy_unit { unitId, col, row }` — validation stricte (hex en zone, non mur, non occupé) puis position + ajout à `deployed_units`.
- **Ordre** : alterné P1/P2 (ou un joueur seul jusqu'à épuisement) ; fin de phase quand tout est placé → transition command/move.
- **Sources** : configs de plateau `config/board/<LxHxR>/`, zones `config/deployment/<board>/<zone>.json`, scénario (units, deployment_zone, deployment_type). Masque strict pour le RL : ni fallback ni placement automatique. Les stratégies de déploiement adressables par l'agent sont bornées par `DEPLOY_STRATEGY_COUNT` (`engine/macro_intents.py`).

---

## Flux d'un step (gym)

### 1. Masque puis décodage

```
W40KEngine.step(action: int)
├─ limite de tours (training_config), statut game_over
├─ BUILD MASK (une seule fois, réutilisé au décodage)
│  └─ ActionDecoder.get_squad_action_mask_and_eligible_units(game_state)
│     mémorise au passage la carte de cellules de move et le jet d'Advance,
│     que le décodeur RELIT (jamais reconstruits : ce serait rouvrir la
│     divergence masque/exécution ; engine/mask_verification.py recalcule
│     et vérifie ces données mémoïsées)
└─ ActionDecoder.convert_squad_action(action_int, game_state, eligible_units)
   └─ retour : action sémantique, ex. {"action": "squad_normal_move",
              "squad_id": "1", "destCol": 5, "destRow": 3}
```

**Espace d'action** : le layout vit dans [`engine/macro_intents.py`](../../../engine/macro_intents.py) (constantes `*_SLOT_BASE`/`*_SLOT_COUNT`, total `TOTAL_ACTION_SIZE`), verrouillé par `tests/unit/engine/test_action_space_mirror.py` (miroir avec `SQUAD_ACTION_*` de `shared_utils`). Ne jamais recopier les bornes : elles se décalent à chaque famille ajoutée. Les familles :

- **Cellules de move** : la destination est une cellule de la grille égocentrique 32×32 (`GRID_CELL_COUNT`, `engine/spatial_grid.py`) ; le **type** de move (normal/advance/fall back) n'est pas une dimension d'action, il est **inféré** du coût géodésique (`def infer_squad_move_type`) — cf. [move_action_space_spatial_rework.md](../training/move_action_space_spatial_rework.md) §6.2. En phase deployment, les premiers ids de cette plage servent de slots de déploiement — la **phase** désambiguïse.
- **Wait / fin d'activation** (`ACTION_WAIT` ; `command_wait` en phase command).
- **Slots de cible** : tir, tir indirect, charge (cible unique), paires de charge C(K,2), mêlée, Oath — tous indexés sur le **même** `get_enemy_slot_mapping`, donc la même ligne du tenseur ennemi de l'observation (**invariant D1** : désolidariser les comptes ferait pointer action i et observation i sur deux escouades différentes sans que rien ne lève). Logits par têtes pointeur (`ai/pointer_policy.py`) pour les slots-entités, têtes denses pour les paires et les armes.
- **Fight sans cible éligible** (`ACTION_FIGHT_NO_TARGET`) : 12.04/12.06, sélectionnée pour combattre, 0 attaque — état légal, action propre.
- **Zone intents** (objectifs × intentions invade/defend/attack).
- **`CHOICE_0..k`** : candidats de `game_state["pending_agent_decision"]` (V11 §9.3 P2) — **exclusives** : quand une décision est en attente, le masque n'expose qu'elles et le pool d'unités éligibles est vide (miroir du `waiting_for_player` PvP).
- **ACTIVATE** : choix de l'escouade alliée à activer (V11 §0.48 L2), un slot par ligne du tenseur allié (invariant D1 côté allié) ; masque exclusif tant que ce choix est ouvert.
- **Choix d'arme CC, retrait de cohérence (03.03), sélection de groupe d'arme au tir (split-fire)** : slots dérivés des constantes d'observation correspondantes, mêmes invariants D1.

> ⚠️ Toute intention non prévue LÈVE — aucun repli silencieux sur une action plausible. La parité masque↔décodeur (tout entier ouvert est décodable, tout entier fermé lève) est verrouillée par `tests/unit/engine/test_agent_interface_contract.py`. L'ancien espace 0-15 (`convert_gym_action`) a été supprimé le 2026-07-29 — pierre tombale dans `engine/action_decoder.py`.

### 2. Routage de phase et délégation

```
W40KEngine._process_semantic_action(action)
├─ lit game_state["phase"]
└─ route : _process_command_phase / _process_movement_phase /
   _process_shooting_phase / _process_charge_phase / _process_fight_phase
   └─ délègue à <phase>_handlers.execute_action(game_state, unit, action, config)
      ├─ valide (unité au pool, destination légale, statut de fuite, …)
      ├─ mutations via les helpers units_cache
      ├─ retire l'unité du pool d'activation
      └─ pool vide → {"phase_complete": True}
```

À la transition, le moteur appelle l'init de la phase suivante **via son handler** (`movement_phase_start`, `shooting_phase_start`, `deployment_phase_start`, …) qui reconstruit le pool d'activation par éligibilité. (Les init privées `_movement_phase_init`/`_charge_phase_init`/`_fight_phase_init` de `w40k_core` ont été supprimées le 2026-07-19 — code mort, cf. V11_agent_rework §0.4 ; seule `_shooting_phase_init` subsiste comme délégation.)

### 3. Observation, reward, fin de partie

- **Observation** : `_build_observation` / `_build_observation_and_mask` → `ObservationBuilder.build_squad_observation` (Dict de tenseurs d'entités) + `build_squad_grid` (grille égocentrique, `GRID_CHANNELS` canaux — lire `engine/spatial_grid.py`). Formes : `ObservationBuilder.squad_obs_shapes` ; taille du vecteur squad : `SQUAD_OBS_SIZE_TARGET` (calculée depuis le schéma, `engine/observation_builder.py`). Contrat complet : [AI_OBSERVATION.md](../training/AI_OBSERVATION.md). L'observation **relit la carte du masque**, jamais un second pool.
- **Reward** : `RewardCalculator.calculate_reward(success, result, game_state)` — pénalités système (action invalide/interdite), rewards par action depuis la config de l'agent (`config/agents/<agent>/<agent>_rewards_config.json`), rewards situationnels (win/loss/draw), breakdown conservé pour les métriques.
- **Fin** : `_check_game_over` (limite de tours, joueurs avec unités vivantes) ; `_determine_winner` (élimination, sinon comparaison à la limite de tours ; égalité = `DRAW_WINNER`). `info["episode"]` est rempli à la terminaison.

### Cycle d'épisode

`reset()` remet l'état (joueur, tour, steps, sets de tracking), réinitialise les unités (PV, munitions, positions ou déploiement selon le mode), reconstruit `units_cache`, initialise la première phase via son handler et rend l'observation initiale. La boucle enchaîne les phases de chaque joueur (séquence exacte : [tour_de_jeu.md](tour_de_jeu.md)) ; le compteur de tours s'incrémente au retour au joueur 0.

---

## Flux d'une action (PvP / API)

Serveur Flask [`services/api_server.py`](../../../services/api_server.py) ; état canonique : `engine.game_state`.

- `POST /api/game/start` — initialise la partie ; la réponse inclut le `game_state` sérialisé.
- `POST /api/game/action` — actions sémantiques (move, skip, shoot, charge, fight, advance, `deploy_unit`, `squad_shoot_assign`, `preview_shoot_from_position`, …). Corps JSON : `action` OU `{ col, row, selectedUnitId }` (clic plateau → move). Optionnel : `move_preview_mask_loops_client_hash` (voir « Masque monde du preview » ci-dessous). Traitement : `W40KEngine.execute_semantic_action(...)` ou handlers dédiés. Réponse : `game_state` via `def _game_state_for_json(...)` — **vue allégée**, pas une copie brute du moteur.
- `GET /api/game/state` — état courant (même vue, sans hash client).
- **Sérialisation** : orjson en priorité (types non natifs via `def _orjson_default`) ; repli `def make_json_serializable` si type exotique.
- Le code moteur (gym) utilise le `game_state` complet : les exclusions JSON ne concernent que les réponses HTTP.
- **PvE** : `W40KEngine.execute_ai_turn` fait jouer le joueur 2 via `PvEController` (modèle MaskablePPO chargé par `def load_ai_model_for_pve`, décision par `def make_ai_decision`).

### Advance (joueur humain, phase de tir)

Quand `valid_target_pool` est vide à l'activation : agent IA/gym → fin d'activation immédiate ; joueur humain → le backend renvoie `{"waiting_for_player": true, "allow_advance": true, ...}`. Le front (`useEngineAPI.ts`) affiche le popup d'avertissement (« won't allow you to shoot or charge ») avec trois issues : **Confirm** → le backend tire l'advance (1D6 depuis la config), calcule les destinations BFS (pas de mur, pas d'adjacence ennemie) et rend `advance_destinations` + `waiting_for_player` ; le clic sur un hex valide exécute le move, marque l'unité dans `units_advanced` (bloque la charge ; le tir reste possible pour les armes [ASSAULT]) et rend `activation_ended` + signaux de nettoyage (`reset_mode`, `clear_selected_unit`). **Skip** → retrait du pool. **Cancel** → aucune action backend, l'unité reste activable.

### Tir squad manuel (PvP humain)

Le chemin par-figurine (`squad_shoot_assign` → `def squad_declare_shoot_model` → `def _model_can_shoot_target` → `def _attacker_model_can_reach_squad`, pool par arme via `def _model_can_shoot_target_with_weapon` — tous dans `shared_utils.py`) est un chemin de résolution **distinct** du tir automatique. Son éligibilité/LoS passe par la même primitive obscuring-aware (`def _compute_visibility_with_obscuring`, `shooting_handlers.py`) : pool de cibles, blink/grisage, garde d'assignation et résolution sont d'accord avec `compute_unit_los`. Une unité passée derrière un terrain obscuring depuis l'activation ne peut plus être assignée ni résolue comme cible. Voir aussi [ligne_de_vue.md](ligne_de_vue.md).

---

## Patterns transverses

### Validation : require / ConfigurationError

Toute donnée obligatoire absente lève immédiatement (`ConfigurationError` via `require_key`/`require_present`, `shared/data_validation.py`). Aucun default silencieux, aucun repli anti-erreur : un fallback n'est légitime que comme comportement métier réellement valide (cf. T1, CLAUDE.md).

### Caches et invalidation

| Cache | Où | Contrat |
|---|---|---|
| `units_cache` / `units_cache_prev` | `game_state` | Source unique position+HP des vivants ; cf. invariants ci-dessus. |
| `unit["los_cache"]` / `unit["los_cover_cache"]` | unité active au tir | Construits par `def build_unit_los_cache` (`shooting_handlers.py`) **pour le tireur actif seulement** à `shooting_unit_activation_start` ; `shooting_phase_start` ne construit plus de cache global (il purge l'existant). Chaque cible est déléguée à `compute_unit_los` (obscuring-aware, règle 13.10) ; le couvert des cibles valides est lu du cache par `def build_cover_by_unit_id_for_valid_targets`, pas recalculé. Couvert = **−1 BS** au jet de touche (règle 13.08), pas un bonus de sauvegarde. |
| `_move_los_preview_cache` | module `shooting_handlers.py` | Mémoïse les résultats de preview backend (`includeLosCells=False`) sous clé stricte : pid, épisode, tour, step, joueur, unité, destination, empreinte `units_cache`, `units_advanced`, `units_fled`, empreinte de targetabilité des armes. |
| `kill_probability_cache` | `game_state`, rempli par `engine/ai/weapon_selector.py` | **Lazy** : rempli au premier usage (`select_best_ranged_weapon`/`select_best_melee_weapon`), plus jamais précalculé au début des phases (bloc O(unités×armes×ennemis) supprimé des transitions). |
| Cache espérance de dégâts | `engine/weapon_damage_cache.py` | Par épisode, lookup O(1). |
| `_mask_loop_cache` | module `movement_handlers.py` | LRU des boucles de masque monde, clé `(frozenset(footprint_zone), hex_radius, margin)`. |
| Configs de plateau | `_board_config_cache` (`engine/game_state.py`) | Les `board_config.json` des plateaux source (`config/board/<LxHxR>/`) sont lus une fois. |
| Données mémoïsées masque→exécution | `engine/mask_verification.py` | Le décodeur **relit** ce que le masque a mémorisé (carte de cellules, jet d'advance) ; ce module vérifie par recalcul. |

**Preview de move — contrat LoS / HP blink** :
- L'overlay visuel bleu/orange est rendu immédiatement côté front depuis le WASM (`buildLosPreviewFromSource`) — **non autoritaire**.
- Les HP blinks et indicateurs couvert/probabilité viennent **toujours** du backend : `preview_shoot_from_position` rend `blinking_units` et `cover_by_unit_id` ; le front doit utiliser cette map, pas le couvert WASM. Pour le preview, le front envoie `includeLosCells: false` (le backend saute la génération plein plateau).
- Politique front : overlay via `requestAnimationFrame` ; une seule requête preview en vol, seule la dernière destination en attente est gardée ; les réponses périmées sont ignorées.
- `def preview_shoot_valid_targets_from_position` travaille sur `copy.deepcopy(game_state)` — ne pas muter l'état vivant pour un preview sans stratégie de restauration prouvée. **Expériences rejetées** (ne pas réintroduire sans preuve) : mutation temporaire de l'état vivant (effets de bord non exclus) ; passe combinée remplaçant `build_unit_los_cache` + précheck d'armes (profiling sans gain, latence premier passage parfois pire).

**Masque monde du preview & payload API** :
- Moteur : `game_state["move_preview_footprint_mask_loops"]` produit par `_sync_move_preview_mask_loops` + `compute_move_preview_mask_loops_world` ; quand les boucles sont présentes, la vue HTTP n'expose pas la zone hex `move_preview_footprint_zone` (économie massive).
- Vue HTTP (`_game_state_for_json`) : ajoute `move_preview_footprint_mask_loops_hash` (SHA-256 canonique) ; boucles au format compact `[x0,y0,x1,y1,...]` ; **omission du tableau** si le `POST /api/game/action` porte un `move_preview_mask_loops_client_hash` égal au hash courant et que le contour dépasse le seuil `_MASK_LOOPS_OMIT_MIN_TOTAL_COORDS` (`services/api_server.py`) — réponse alors `move_preview_footprint_mask_loops_unchanged: true`. Les autres routes rendent toujours les boucles compactes.
- Front (`useEngineAPI.ts`) : cache module dernier payload + hash ; `mergeGameStatePreservingOmittedObjectives` et `hydrateApiGameStateMovePreviewTransport` réinjectent depuis le cache si `unchanged` + hash cohérent, invalident sinon (pas de repli silencieux) ; normalisation `normalizeMaskLoopsFromApi` (`frontend/src/utils/movePreviewFootprintMaskLoops.ts`), format compact **et** legacy.
- Rendu Pixi (`BoardDisplay.tsx` / `BoardPvp.tsx`) : `resolveMovePreviewMaskLoopsBeforeSmooth` priorise les boucles API ; sinon reconstruction locale `tryBuildHexUnionMaskPolygons`. Redraw partiel : `computeDrawBoardPartialRedrawFingerprint` sépare l'empreinte structurelle des highlights de la clé du polygone move ; structure identique → réutilisation du conteneur `highlights` (sans appeler `detachMovePreviewLayerCacheFromStage`) ; seule la clé polygone change → `updateMovePreviewPolygonLayerInHighlightContainer` ; sinon `drawBoard` complet. Pure couche présentation — moteur et sérialisation non concernés.

**Charge — profiling et décisions actées** : la transition shoot→charge est dominée par la construction du pool d'activation. Garder l'instrumentation `W40K_PERF_TIMING=1` autour de `CHARGE_PHASE_START`, `CHARGE_BUILD_POOL`, `CHARGE_DEST_BFS`, `CHARGE_REVERSE_GOAL_BFS` (`charge_handlers.py`) en cas de changement d'éligibilité. Optimisations en vigueur : borne inférieure hex bon marché avant BFS complet (désactivée pour les paires rond-vs-rond, qui exigent la clairance euclidienne exacte de `unit_entries_within_engagement_zone`, `engine/spatial_relations.py`) ; reverse goal BFS seulement pour `early_exit_if_valid=True` sans cible déclarée. **Rejetées** (ne pas réintroduire sans test de non-régression comparant éligibilité et destinations pour les grandes bases rondes, ovales et carrées) : tri des voisins BFS vers l'ennemi le plus proche (surcoût mesuré, `visited_n` inchangé) ; précalcul des ancres reverse-BFS depuis les zones d'engagement (augmentait `goal_build_s`).

### Système de règles et logging

#### Modèle de données des règles

Deux couches complémentaires pour les règles d'**unité** :

- **Registre global** : `config/unit_rules.json` — `id` (clé canonique), `name` (affichage), `alias` (indirection technique), `description`.
- **Règles attachées** : `UNIT_RULES` sur chaque unité — `ruleId`, `displayName`, `grants_rule_ids`, `usage` (`and`/`or`/`unique`/`always`), `choice_timing`.

Pour les règles d'**arme** :

- **Registre global** : `config/weapon_rules.json` — clé canonique (ex. `RAPID_FIRE`, `HEAVY`, `DEVASTATING_WOUNDS`), `name`, `description`, `has_parameter`.
- **Règles attachées** : `WEAPON_RULES` sur chaque entrée d'armory — forme statique (`"HEAVY"`) ou paramétrée (`"RAPID_FIRE:1"`).
- Pipeline : `engine/weapons/parser.py` charge les chaînes ; `engine/weapons/rules.py` valide chaque entrée contre le registre (fail-fast, aucun repli). Un seul registre canonique pour gameplay, front, replay et analyzer. En cas de divergence registre/PDF, **les PDF de `Documentation/40k_rules/` font foi** (arbitrage 2026-07-26, cf. `attack_sequence.py`).

#### Résolution (direct + alias + granted)

Helpers centraux dans `engine/phase_handlers/shared_utils.py` :

- `def _resolve_effect_rule_id_to_technical` — suit les chaînes d'alias, lève sur ID inconnu, alias invalide ou cycle.
- `def _resolve_unit_rule_entry_effect_rule_ids` — effets actifs d'une entrée `UNIT_RULES` : `and`/`always` → tous les granted ; `or`/`unique` → seulement `_selected_granted_rule_id`.
- `def unit_has_rule_effect` — check public des handlers.
- `def get_source_unit_rule_id_for_effect` / `def get_source_unit_rule_display_name_for_effect` — remontée effet → règle source et label à logguer (pour `or`/`unique`, le nom de la règle enfant sélectionnée, pas du parent).

#### Choix de règle à l'exécution

- Index : `def rebuild_choice_timing_index` (`shared_utils.py`) ; file et prompts gérés dans `w40k_core.py` ; application : `W40KEngine._apply_rule_choice_selection` stocke `_selected_granted_rule_id`.
- Gym/training : sélection déterministe depuis l'entier d'action (`w40k_core.py`). PvE : sélection par valeur (`PvEController.select_rule_choice_with_policy`). Aucun fallback heuristique.

#### Surfaces de log et contrats

**A) `action_logs` backend** (bus d'événements vers le front) : les handlers y appendent des événements structurés via `def append_action_log` (`engine/action_log_utils.py`, `logSeq` monotone). Exemple reactive move : type, message, unitId, player, `ability_display_name`, from/to, `range_roll`, coordonnées du déclencheur. Le front (`useEngineAPI.ts` → `useGameLog.ts`) les consomme pour le combat log.

**B) Combat log (front)** : affiche `action_logs[].message` (après nettoyage léger). Les tags `[RÈGLE]` sont interactifs — descriptions résolues depuis `unit_rules.json` et `weapon_rules.json` (priorité règle d'unité en cas de collision).

**C) `step.log`** (trace canonique replay/analyzer) : `ai/step_logger.py` (`class StepLogger.log_action`) formate avec enveloppe horodatage/épisode/tour/joueur/phase :

```text
[06:55:38] E11 T1 P2 MOVE : Unit 15(1,6) REACTIVE MOVED [SKULKING HORRORS] from (2,2) to (1,6) [Roll: 5] - trigger: Unit 2->(1,10) [R:+0.0] [SUCCESS]
[HH:MM:SS] E# T# P# FIGHT : Unit 3(7,12) chose [ADRENALISED ONSLAUGHT] [SUCCESS]
```

**Contrat tir/règles d'arme** — lignes déterministes par étapes : Hit raté → `Hit` seul ; Wound raté → `Hit` + `Wound` ; Save réussi → `Hit` + `Wound` + `Save` ; Save raté → + `Dmg:XHP` ; [DEVASTATING WOUNDS] (blessure critique) → `Save [DEVASTATING WOUNDS]` + `Dmg:XHP` (pas de jet de sauvegarde). Exemples canoniques :

```text
Unit 15(9,6) SHOT [RAPID FIRE:1] Unit 18(11,6) with [Bolt Pistol] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP
Unit 2(23,10) SHOT Unit 7(12,2) with [Heavy Bolter] - Hit 4(3+->2+) [HEAVY] - Wound 5(3+) - Save 2(3+) - Dmg:2HP
```

**Contrat HAZARDOUS / Desperate Escape** : les jets de hasard sont résolus par `def roll_hazard_for_unit` (`shared_utils.py`, règle 06.03) — en fin d'activation pour [HAZARDOUS] 24.15 (un jet par arme HAZARDOUS **sélectionnée**, cf. `attack_sequence.py`), par figurine pour Desperate Escape 09.07. La ligne de log porte le tag d'origine (`[HAZARDOUS]` ou `[DESPERATE ESCAPE]`), le détail des jets (`hazardousDiceRolls`, `hazardousWeaponCount` pour 24.15) et les blessures mortelles en champ structuré (`hazardousMortalWounds`) — émise **avant** l'allocation des pertes (auto en IA/gym, manuelle pour un défenseur humain).

**D) Attentes de l'analyzer** (`ai/analyzer.py`) : parse les reactive moves (`REACTIVE MOVED`, trigger, roll), les choix de règle (`chose [RULE]`) et les tags `[...]` des actions de combat. Conformité des choix : `correct` / `missing` (effet utilisé sans choix préalable) / `mismatch`. Contrôles d'armes : cohérence RAPID FIRE (marqueur/valeur, fenêtre des tirs bonus, plafond `rng_nb + bonus`) et DEVASTATING WOUNDS (compté seulement si `Save [DEVASTATING WOUNDS]` présent ; `correct` exige wound 6 et save sauté).

#### Conventions pour tout nouvel effet loggué

- Label de règle explicite entre crochets : `[RULE NAME]` ; message déterministe et parsable, une phraséologie canonique par type d'action.
- Motif recommandé : `Unit <id>(<col>,<row>) <ACTION VERB> [<RULE NAME>] <details...>`.
- Actions à effet de bord (reactive move, choix de règle, hasard) : entrée structurée dans `action_logs` **et** flush vers `step.log`.
- Tags d'affichage canoniques (`[RAPID FIRE:n]`, `[HEAVY]`, …) ; identifiants internes inchangés (`RAPID_FIRE`, …).

**Reactive move (règle d'unité)** : spécification complète (état, éligibilité, résolution, caches, erreurs, tests) dans [Unit_rules.md](../jeu/Unit_rules.md), section « 10) Specification : reactive_move ».

---

## Checklist de conformité pour tout changement substantiel

- **Règles** : respecte les CORE AI CODING RULES ; ne contredit pas [tour_de_jeu.md](tour_de_jeu.md).
- **Configuration** : toute nouvelle valeur réglable vit en fichier de config ; toute nouvelle clé est documentée dans [CONFIG_FILES.md](../outils/CONFIG_FILES.md) ou le guide pertinent.
- **Validation** : tout nouvel accès obligatoire passe par `require_key` / `require_present` (`shared/data_validation.py`).
- **Erreurs** : donnée manquante ou invalide → erreur explicite fail-fast ; aucun remplacement silencieux.
- **Architecture** : la conception la plus simple qui satisfait le besoin ; intégration sans duplication de responsabilité dans la carte des modules ci-dessus.

> ⚠️ Une doc d'API décrit ce qu'on a écrit, jamais ce que la production appelle : vérifier par `grep` (appelants réels) avant de s'appuyer sur une liste de méthodes — deux « Key Methods » de l'ancienne doc n'avaient aucun appelant (pierre tombale dans `engine/action_decoder.py`).

---

## Historique et sources

- **Observation 150 floats** : le pipeline mono-figurine (`build_observation`, `_encode_*`, `_calculate_danger_probability`, …) a été supprimé le 2026-07-28 ; l'observation est un Dict de tenseurs d'entités + grille égocentrique — voir [AI_OBSERVATION.md](../training/AI_OBSERVATION.md).
- **Espace d'action 0-15** (`convert_gym_action`) : supprimé le 2026-07-29 (pierre tombale dans `engine/action_decoder.py`). Tout mapping « 0-3 move / 4-8 shoot / 9 charge / 10 fight / 11 wait » est périmé.
- **« CPU 311 it/s » et « 4.7x speedup »** : mesures pré-V11 (obs Box 355 floats, MlpPolicy 256×256), invalidées par le profil V11 du 2026-08-26 (politique CNN sur CUDA, goulot côté workers CPU) — voir [perf_entrainement.md](../../Chantiers/backlog/perf_entrainement.md) §1/§6 et la section « CPU vs GPU » d'[AI_TRAINING.md](../training/AI_TRAINING.md). Les configs `debug`/`default` citées à l'époque n'existent plus (`config/agents/<agent>/<agent>_training_config.json`).
- **`get_all_valid_targets` / `can_melee_units_charge_target`** (ancien `action_decoder`) : supprimées le 2026-07-29, code mort sans appelant ; les pools de cibles réels sont construits par les handlers de phase.
- Ce document consolide `AI_IMPLEMENTATION.md` (archivé dans `Documentation/Archives/docs/`).

---

## Correspondance des sources

| Source | Ancien § | Section actuelle |
|---|---|---|
| AI_IMPLEMENTATION.md | CORE AI CODING RULES | Règles de codage IA (CORE AI CODING RULES) |
| AI_IMPLEMENTATION.md | EXECUTIVE SUMMARY / SUMMARY | Bandeau + Invariants d'architecture |
| AI_IMPLEMENTATION.md | AUTOMATED AI RULE CHECKS | Règles de codage IA |
| AI_IMPLEMENTATION.md | DATA AND CONFIGURATION VALIDATION | Règles de codage IA + Patterns transverses › Validation |
| AI_IMPLEMENTATION.md | ARCHITECTURE COMPLIANCE (dont « Units cache & HP_CUR ») | Invariants d'architecture |
| AI_IMPLEMENTATION.md | CODE ORGANIZATION / File Structure + sections par module | Carte des modules |
| AI_IMPLEMENTATION.md | phase_handlers/ › deployment_handlers | Carte des modules › Phase de déploiement |
| AI_IMPLEMENTATION.md | Rule System and Logging Patterns (§1–§5) | Patterns transverses › Système de règles et logging |
| AI_IMPLEMENTATION.md | HOW EVERYTHING WORKS TOGETHER › Complete Request Flow / Episode Lifecycle / Data Flow / Phase Transition Flow | Flux d'un step (gym) |
| AI_IMPLEMENTATION.md | HOW EVERYTHING WORKS TOGETHER › Integration Points + Advance Action Flow | Flux d'une action (PvP / API) |
| AI_IMPLEMENTATION.md | PERFORMANCE OPTIMIZATIONS › LoS Cache / Move Preview / masque monde / Rendu Pixi / Kill Probability Cache / Charge Phase Start Profiling | Patterns transverses › Caches et invalidation |
| AI_IMPLEMENTATION.md | Egocentric Observation (150 Floats) | Purgé — voir Historique ; contrat actuel dans AI_OBSERVATION.md |
| AI_IMPLEMENTATION.md | Coordinate Normalization (« jamais unit["col"] direct, toujours get/set_unit_coordinates ») | Purgé — règle jamais tenue par le code (accès directs dans `engine/macro_intents.py` et `engine/phase_handlers/shooting_handlers.py` ; les positions vivantes passent par `units_cache`) ; les helpers `get_unit_coordinates`/`set_unit_coordinates` existent toujours et restent utilisés là où ils le sont |
| AI_IMPLEMENTATION.md | CPU Optimization (311 it/s) / Combined Impact / SUCCESS METRICS | Historique et sources (réduit à l'historique) |
| AI_IMPLEMENTATION.md | RELATED DOCUMENTATION | Liens en place dans chaque section |
| AI_IMPLEMENTATION.md | SUMMARY › AI Architecture Compliance Checklist | Checklist de conformité |
