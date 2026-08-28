# V11 — Tranches et ruptures : objectif, ancre, R1→R8, T1→T7, critères, tests

> ### 🧭 Ce fichier n'est PAS la roadmap
>
> **Ordre du travail, tout projet confondu : [`../../Roadmap/ROADMAP_INDEX.md`](../../Roadmap/ROADMAP_INDEX.md)** — s'y reporter
> pour savoir par quoi commencer, ce qui est bloqué et par quoi.
>
> Ce document porte la **spec** V11 : objectif, ancre, ruptures R1→R8, tranches T1→T7, critères et tests.
> **L'ÉTAT des tranches fait foi dans `Documentation/Roadmap/` uniquement** (refonte 2026-08-27) —
> les strates d'état datées du corps ont été purgées le 2026-08-28 (lot P4 v11).
> Il fait foi sur le **détail de conception** ; il ne fait foi ni sur l'**état** ni sur les **priorités**.
> En cas de désaccord sur l'ordre entre ce fichier et le ROADMAP, **le ROADMAP l'emporte** — et
> l'écart se corrige dans la même livraison (règle T2 de CLAUDE.md).

> **Origine.** Sections **§1 → §8** extraites de [`index_v11.md`](index_v11.md) le
> **2026-07-28** (étape 3 de [`V11_refactor_plan.md`](../../Archives/chantiers/V11_refactor_plan.md)), **sans aucune
> réécriture** : blocs déplacés tels quels, seuls les liens ont été recâblés.
>
> **Rôle.** La **spec** V11 : objectif, concept d'ANCRE, ruptures R1→R8, décisions de design,
> tranches T1→T7 + Phase B, critères d'acceptation, smoke tests et tests de non-régression.
>
> **Retour à l'index d'état** (entrées ouvertes, pièges canoniques, historique résolu) :
> [`index_v11.md`](index_v11.md). Les autres sous-docs de la spec :
> [`decisions_du_joueur.md`](decisions_du_joueur.md) — [§9](decisions_du_joueur.md#s9), Phase A' P1→P5 — et
> [`strategie_evaluation.md`](strategie_evaluation.md) — [§10](strategie_evaluation.md#s10), stratégie
> d'entraînement et d'évaluation.
>
> **Convention.** Les renvois de 1 à 8 **internes à ce fichier** restent en texte nu ; les renvois
> vers l'index (sections 0) et vers les sous-docs frères (sections 9 et 10) sont des liens.

---

<a id="s1"></a>
## 1. Objectif

Rétablir un entraînement fonctionnel de `CoreAgent` (`python3 ai/train.py --agent CoreAgent
--scenario bot ...`) sur le moteur actuel (board 44x60x5, niveaux, per-model, fight V11,
allocation des pertes par-figurine), en trois phases :

- **Phase A (obligatoire)** : remise en route — le pipeline tourne de bout en bout sans erreur,
  à interface agent constante (action 41 / obs 108).
- **Phase A' (obligatoire, décision utilisateur 2026-07-14)** : entraîner l'agent sur TOUTES les
  règles implémentées — (P1) porter dans le chemin vif les règles restées dans le code mort puis
  supprimer le code mort, (P2-P3) donner à l'agent chaque décision que les règles laissent au
  joueur (mécanisme générique de décision), (P4-P5) observation de support + validation par
  tranche. Périmètre strict : règles DÉJÀ implémentées — aucune feature absente du moteur.
  Détail en [section 9](decisions_du_joueur.md#s9).
- **Phase B (obligatoire)** : mise à niveau de l'observation — l'agent perçoit les niveaux
  (élévation) et les coûts associés.
- **Phase C (optionnelle, hors scope initial)** : nouveaux points de décision au-delà de la
  Phase A' (ex. montée d'étage). À ne PAS entamer sans validation utilisateur.

**Interdits absolus** (CLAUDE.md) : aucun fallback/workaround/valeur par défaut pour masquer une
erreur ; ne jamais modifier `config/users.db` ni `ai/models/**/*.zip` ; les règles de jeu se
vérifient dans `Documentation/40k_rules/` avant toute décision règles.

<a id="s1bis"></a>
## 1bis. L'ANCRE — concept central, source commune des ruptures V11

> Rédigé le 2026-07-20 après que le plan T7 se soit révélé faux faute d'avoir ce concept écrit
> quelque part. **À lire avant de toucher à toute validation de position.**

### Définition

Une unité 40K est un **ensemble de figurines**, chacune sur son propre hex. Mais l'agent doit
produire une **action discrète** (« déploie l'unité 3 ici ») : il ne peut pas émettre N
coordonnées. L'**ancre** est le point unique qui représente l'unité entière dans les interfaces
qui ne savent manipuler qu'UNE position — l'espace d'action, et le code moteur legacy écrit
quand une unité *était* une seule figurine.

Deux structures parallèles coexistent, et tout se joue là :

| Structure | Contenu | Statut |
|---|---|---|
| `models_cache` | position de **chaque figurine** (`col`, `row`, `level`) | la **vérité** |
| `units_cache` | **une** position par unité | l'ancre, un **résumé** |

L'ancre **n'est pas un objet physique**. C'est la position de la **figurine vivante d'index
minimal** ([shared_utils.py](../../../engine/phase_handlers/shared_utils.py), commentaire
« n'update `units_cache` que si la figurine est l'ancre courante (index minimum vivant) » —
`grep "index minimum vivant"`).
Ce n'est ni le centre, ni le barycentre de l'unité : un simple délégué désigné par convention.
**Corollaire à ne pas oublier : quand la figurine d'index minimal meurt, l'ancre SAUTE** sur la
suivante — la position « de l'unité » change sans qu'aucune figurine n'ait bougé.

### Trois usages, de natures différentes

1. **Désigner** — l'agent choisit un hex : c'est l'ancre visée. ✅ légitime.
2. **Translater** — `build_rigid_plan` calcule un delta entre ancre de départ et ancre
   d'arrivée, puis l'applique à TOUTES les figurines. ✅ légitime *si* le delta est réellement
   rigide (ce qui était faux avant T6-h, cf. parité de `dx`).
3. **Résumer pour valider** — les fonctions legacy (`compute_candidate_footprint(col, row,
   unit, …)`) prennent l'ancre + le `BASE_SIZE` de l'**unité** et testent *un socle* à cet
   endroit. 🔴 **C'est un mensonge** : elles testent un objet qui n'existe pas.

### Le motif de bug unique

**Quelque chose est VALIDÉ sur l'ancre, puis EXÉCUTÉ sur les figurines** — et les deux divergent.
D'où le message récurrent `incohérence masque/exécution`. Toutes les ruptures traitées en V11
sont des variantes du même mensonge :

| Tranche | Variante |
|---|---|
| **T6-f** | le commit n'écrivait QUE l'ancre → figurines restées à `(-1,-1)` |
| **T6-g** | le pool BFS validait l'ancre → le bloc translaté débordait |
| **T6-h** | la translation « rigide » déformait le bloc selon la parité de `dx` |
| **[§0.11](index_v11.md)** | la collision intra-plan ignorait le **niveau**, autre attribut d'identité écrasé par le résumé |
| **T7** | le contrôle mono-ancre de `deploy_unit` teste ce socle fantôme |

### ⚠️ Le piège : « ancre » désigne TROIS contrats différents

Le mot est le même partout, le contrat non — et c'est précisément ce qui a fait écrire un plan
T7 faux :

| Chemin | Ce que « ancre » veut dire |
|---|---|
| `units_cache` | position de la figurine d'index minimal (dérivée, elle SAUTE aux pertes) |
| action de l'agent | point de **désignation** (contraignant : ce qui est désigné doit être exécuté) |
| **déploiement** | **simple suggestion** : `generate_compact_formation` part de l'ancre en spirale BFS et retient la 1ʳᵉ case légale — l'ancre **oriente**, elle ne **contraint pas**. Une ancre hors zone place l'unité 22 colonnes plus loin au lieu d'échouer (mesuré, cf. T7). |

**Avant d'écrire ou de supprimer une validation de position, déterminer LEQUEL des trois contrats
s'applique sur ce chemin.** Ne jamais supposer que « le contrôle par-figurine valide déjà
l'ancre » : au déploiement, c'est faux.

### Dette d'ancre restante — recensement du 2026-07-20

> Balayage de `engine/` + `ai/`. Les sites marqués ✅ *vérifié* ont été relus directement ; les
> autres viennent du balayage et **restent à confirmer par lecture avant toute action**.
>
> 🔴 **Statut de fiabilité de ce recensement — à lire avant de s'en servir.** Il est issu d'un
> balayage automatique dont **seuls 4 sites ont été relus à la main** (le pool de move, les 2
> sites objectif, la ventilation LoS). Le reste est un **faisceau d'indices, pas un audit**.
> Un premier essai d'exploitation a déjà produit une conclusion fausse : « la charge n'a pas
> d'équivalent de l'érosion T6-g » a été écrit ici sur la seule absence de fonction `erode_*`,
> alors qu'une machinerie per-model existe ailleurs dans le même fichier (cf. la ligne charge
> ci-dessous). **Ne pas ouvrir de chantier depuis une ligne non marquée ✅ sans avoir lu la
> fonction.** C'est la même erreur de méthode que [§0.11](index_v11.md) (« vérifié un par un » sur un
> échantillon n'est pas une vérification) et que le plan T7 (conclusion tirée sans lire les
> deux avertissements présents dans le code).

**Le levier unique** : `def compute_candidate_footprint(col, row, unit, game_state)`
([shared_utils.py](../../../engine/phase_handlers/shared_utils.py)) ne calcule **qu'UNE
base** (le `BASE_SHAPE`/`BASE_SIZE` de l'unité) centrée sur `(col,row)`. Passée une unité
multi-figurines, elle rend l'empreinte d'**une figurine à l'ancre**, jamais celle de l'escouade.
C'est la source commune des gravités 1-2 ci-dessous.

**G1 — pool/masque construit à l'ancre, commit exécuté par figurine**

| Site | Décision prise sur l'ancre |
|---|---|
| `movement_build_valid_destinations_pool` (movement, 2870) | ✅ *vérifié* : le pool ne valide QUE l'ancre — [shared_utils.py](../../../engine/phase_handlers/shared_utils.py) l'écrit. ⚠️ **Le chemin du MASQUE GYM est couvert** : `erode_move_pool_by_squad_block` (T6-g) est appliquée juste après, en [:7671](../../../engine/phase_handlers/shared_utils.py). **Les autres consommateurs n'érodent PAS** — `pve_controller.py`, `movement_handlers.py/846`, `shooting_handlers.py`, `action_decoder.py`, `w40k_core.py`. À auditer : le PvP tombe-t-il dans le même mismatch, ou son preview le rattrape-t-il ? |
| `charge_build_valid_destinations_pool` ([charge](../../../engine/phase_handlers/charge_handlers.py), 166) | Portée de charge 2d6 + légalité d'arrivée mesurées depuis l'ancre, empreinte mono-base ; commit per-model. **Le code admet la dette** : charge_handlers.py. ⚠️ **STATUT NON ÉTABLI — ne pas partir de cette ligne pour ouvrir un chantier.** Il n'existe aucune fonction `erode_*` dans `charge_handlers.py`, MAIS la charge possède une machinerie **par figurine** ailleurs : [`_compute_plan_context`](../../../engine/phase_handlers/charge_handlers.py) calcule un champ de portée per-model (`_euclidean_reach(m, sib, …)`, avec le `BASE_SHAPE`/`BASE_SIZE` **de chaque figurine**). **Question ouverte, à trancher par lecture de `charge_build_valid_destinations_pool` :** ce contexte per-model réconcilie-t-il le pool d'ancre, ou les deux coexistent-ils sans se parler ? Tant que ce n'est pas lu, « la charge a le même trou que le move » est une **hypothèse, pas un constat**. |
| `charge_target_selection_handler` (charge:4360) | `charge_reference_hex` = ancre → décide quelles cibles sont engagées. |

**G2 — éligibilité de phase décidée sur l'ancre**

| Site | Décision |
|---|---|
| `get_eligible_units` (movement:544, 573, 599) | « L'unité peut-elle bouger ? » = existe-t-il un voisin de **l'ancre** où une base tient. Une escouade dont l'ancre est bloquée mais dont d'autres figurines peuvent bouger est déclarée inéligible — et l'inverse. |
| pile-in / consolidation (fight:545, 726, 893, 1116, 1203, 1372, 1731) | BFS et distances mesurés sur une base à l'ancre, alors que le pile-in 12.03 et la consolidation 12.08 sont **par figurine** (cf. `project_pile_in_par_figurine`). |
| `action_decoder.py` | Case décodée validée sur une empreinte mono-base avant exécution per-model. |

**G3 — règles satellites d'objectif sur position unique** (✅ *les deux vérifiés*)

| Site | Décision |
|---|---|
| [shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py) | Règle `reroll_towound_target_on_objective` : « la cible est-elle sur un objectif ? » testée sur `target["col"]/["row"]` = **l'ancre**. Une escouade dont seule une figurine non-ancre tient l'objectif est ratée. ⚠️ Utilise en plus `target.get("col", -1)` — **valeur par défaut masquant une absence**, interdite par CLAUDE.md. |
| [fight_handlers.py](../../../engine/phase_handlers/fight_handlers.py) `_is_unit_on_objective` | Même bug côté mêlée (`require_unit_position` = ancre). |

~~✅ **Le vrai Objective Control est SAIN** : `_sum_objective_control_oc`
([game_state.py](../../../engine/game_state.py)) compte bien OC × figurines dans la zone
(14.02). Ce sont les règles *satellites* qui n'ont pas suivi.~~

⛔ **AFFIRMATION FAUSSE, CORRIGÉE LE 2026-07-29** (§0.50 de [`index_v11.md`](index_v11.md#s0.50),
branche `v11-battle-shock-oc`, commit `4be41919`). Le décompte était ✅ conforme à **14.02**
(OC × figurines dont l'empreinte recouvre la zone) mais ⛔ **PAS conforme à 01.07** : `battle_shocked`
n'était jamais consulté, alors que la règle met l'OC de toutes les figurines d'une unité choquée à
« - » — donc à zéro (02.02, et le diagramme p.53 de `14 Objectives.pdf` tranche le cas
explicitement). Une unité démoralisée tenait ses objectifs normalement.

⚠️ **C'est cette phrase qui a rendu le défaut invisible** : un « SAIN » non borné, prononcé sur UNE
règle, a été lu comme un verdict sur le contrôle d'objectif en général. Leçon durcie en §0bis de
[`index_v11.md`](index_v11.md#s0bis) : un verdict de conformité se borne à la règle
vérifiée et énumère les règles satellites qui la modifient ; un ✅ exige plus de justification qu'un
🔴, parce que personne ne va le revérifier.

📍 Le pointeur ci-dessus est lui aussi périmé : la source unique actuelle est
`sum_objective_control_oc_multi` ([game_state.py](../../../engine/game_state.py)), dont
`_sum_objective_control_oc` n'est plus qu'une délégation d'une ligne.

**G4 — heuristiques IA à l'ancre** (aucun impact règles, biais de politique seulement) :
~~`_select_strategic_destination` (movement:3923+, charge:4169)~~ — **les DEUX supprimées le
2026-07-29**, code mort (la destination de move et la cible de charge sont devenues des
dimensions d'action ; pierres tombales dans `movement_handlers.py` et `charge_handlers.py`).
Restent : `observation_builder.py/2332`
(« Anchor-based distance (approx, sufficient for RL obs) »), `analyzer.py`. Assumé et
auto-documenté. (La réserve « charge:4169 n'a **pas** de justification écrite » est sans objet
depuis la suppression : le code qu'elle visait n'existe plus.)

**Ce qui est SAIN et ne doit pas être touché** : la **LoS** est entièrement par-figurine
(`_compute_unit_los_uncached`, `_unit_can_see_any`, couvert 13.08 — itèrent sur `models_cache`) ;
les **portées de tir/mêlée** passent par `occupied_hexes` (union per-model) avec l'ancre en simple
repli ; `units_cache[sid]["occupied_hexes"]` **est** l'union par-figurine
([shared_utils.py](../../../engine/phase_handlers/shared_utils.py)) ; les logs et la sync
d'ancre post-commit sont des résumés légitimes.

⚠️ **Indice de méthode** : [shared_utils.py](../../../engine/phase_handlers/shared_utils.py)
porte le commentaire « Fix F2 (audit) : `occupied_hexes` doit couvrir TOUTES les figs, pas
seulement le footprint de l'ancre ». La correction analogue a donc **déjà** été faite à cet
endroit, et **pas** aux sites G1-G2. Le motif se répare site par site depuis des années.

<a id="s2"></a>
## 2. État des lieux vérifié (ce qui marche)

⚠️ **Affirmation périmée n°7 — voir la table de [§0bis](index_v11.md#s0bis)** : `ai.multi_agent_trainer` n'existe plus (supprimé en [§0.8](index_v11.md)). Ligne conservée telle quelle, non corrigée.

- Tous les imports du pipeline passent (`ai.train`, `ai.env_wrappers`, `ai.multi_agent_trainer`,
  `ai.reward_mapper`, `ai.scenario_manager`, `ai.unit_registry`, ... — vérifié par exécution).
- L'environnement gym EST le moteur : `W40KEngine(gym.Env)` ([w40k_core.py](../../../engine/w40k_core.py)),
  `reset()` 918, `step(action: int)` 1330. Espace d'action `Discrete(41)` (629), observation
  `Box(108,)` (660), les deux lus depuis `observation_params` de
  `config/agents/CoreAgent/CoreAgent_training_config.json` (obs_size 108, action_space_size 41), sans
  défaut. ⚠️ **Fichier SUPPRIMÉ depuis** (commit `20a2d479`, « retrait de la banque CoreAgent », avec
  ses 3 variantes `BEST_*`/`*_BEST_X1`/`*_save_avant_X10`) : lien retiré le 2026-07-28, valeurs
  conservées pour la trace historique. La config vivante est
  [ArmageddonAgent_training_config.json](../../../config/agents/ArmageddonAgent/ArmageddonAgent_training_config.json).
- Espace d'action squad actuel — source unique [macro_intents.py](../../../engine/macro_intents.py) :
  - 0-5 move normal (6 directions), 6-11 advance (6 dir), 12-17 fall back (6 dir),
  - 18 wait/end activation, 19-23 shoot slots 0-4, 24 charge, 25 fight,
  - 26-40 zone intents (5 objectifs × 3 intents). Total 41.
- Masque : `ActionDecoder.get_squad_action_mask_and_eligible_units`
  ([action_decoder.py](../../../engine/action_decoder.py)) ; exposé par `W40KEngine.get_action_mask()` (5563), branché
  MaskablePPO via `ActionMasker` ([train.py](../../../ai/train.py)).
- Observation squad 108 : `build_squad_observation` ([observation_builder.py](../../../engine/observation_builder.py)) —
  16 global + 5 agrégats squad + 6 figurines × 7 features + 5 slots ennemis × 9 features.
  Layout **purement 2D** (col/row) : aucune feature de niveau/élévation.
- Rewards : `RewardCalculator` ([reward_calculator.py](../../../engine/reward_calculator.py)) piloté par
  `CoreAgent_rewards_config.json` (squad_shaping, base_actions, situational_modifiers,
  zone_intent_shaping) — pas de valeurs par défaut, à une nuance près :
  `situational_modifiers` est optionnel dans une branche (~782). OK à interface constante.
- Le moteur distingue déjà training et PvP : `gym_training_mode` (auto-résolution des prompts,
  `_is_player_human` renvoie False — [w40k_core.py](../../../engine/w40k_core.py)) et `pve_mode` (adversaire géré
  par wrapper externe en training, `pve_mode=False`, [w40k_core.py](../../../engine/w40k_core.py)).
- Wrappers : `BotControlledEnv` (scénarios "bot", GreedyBot, [train.py](../../../ai/train.py)) et
  `SelfPlayWrapper` (self-play, modèle gelé) dans [env_wrappers.py](../../../ai/env_wrappers.py).
- Un smoke test moteur nu (actions aléatoires masquées, scénario board actuel) déroule
  deployment/command/move/shoot/charge/fight jusqu'au tour 5 une fois les ruptures R4/R6
  contournées — le cœur par-figurine (fight V11 auto, footprints, descente §13.06) fonctionne
  en gym.

**Contexte de divergence (git)** : dernier commit sur `ai/env_wrappers.py` = 2026-05-30, sur
`ai/train.py` = 2026-05-31. Toutes les features suivantes sont postérieures : charge rework
(06-01), fight V11 (06-12→07), LoS unifiée (07-02), niveaux + coût descente §13.06 (07-09),
perModelMove (07-10), replay/snapshots (07). Le pipeline RL est resté sur le modèle de fin mai.

<a id="s3"></a>
## 3. Ruptures vérifiées (avec reproduction)

### R1 — Phase de training `default` absente
**Repro** : `python3 ai/train.py --agent CoreAgent --scenario bot --step` →
`KeyError: "Phase 'default' not found in CoreAgent_training_config.json. Available:
['x1','x5_append','x5_new','x1_debug','x5_debug']"` (config_loader.py).
`--training-config` a pour défaut `"default"` ([train.py](../../../ai/train.py)).

### R2 — train.py reconstruit le chemin board depuis {cols}x{rows}
**Repro** : `python3 ai/train.py --agent CoreAgent --scenario bot --step --training-config x1_debug`
→ `FileNotFoundError: Board walls directory not found: config/board/220x300/walls`.
Cause : `_list_available_board_refs` ([train.py](../../../ai/train.py)) construit
`config/board/{cols}x{rows}/` (= 220x300, dimensions subhex) alors que le dossier réel est
`config/board/44x60x5/` (44x60 pouces, scale 5). La source de vérité existe déjà :
`config_loader.get_board_dir()` ([config_loader.py](../../../config_loader.py), gère `W40K_BOARD_PATH` + `paths.board`).
**Auditer toute reconstruction `f"{cols}x{rows}"` dans ai/ et engine/** (même motif ailleurs, cf. R3-d).

### R3 — Banque de scénarios d'entraînement incompatible avec le contrat scénario actuel
La banque vit dans `config/agents/CoreAgent/scenarios/` — **61 JSONs** : training/ 30 +
training/training_benchmark/ 4, holdout_regular/ 10, holdout_hard/ 10 + holdout_hard/matchups/ 7
(dans des sous-sous-dossiers `matchups/run_*/` ; attention : ne pas compter les dossiers comme
des fichiers) + rosters
`config/agents/_p2_rosters/`. Il existe aussi `scenarios/training_save/` (30 JSONs de plus) —
statuer en T4 : migrer ou archiver. Le contrat moteur a changé
(commit `540d0674` "terrain OK") — cinq incompatibilités indépendantes, toutes vérifiées par
exécution ou lecture :

- **(a) Localisation obligatoire** : `_resolve_shared_config_path` exige que le scénario soit dans
  un dossier nommé exactement `scenario/` sous un board ([game_state.py](../../../engine/game_state.py)) ; idem pour
  `wall_ref: "random"` ([game_state.py](../../../engine/game_state.py)) et `terrain_ref` (1496-1505).
  **Repro** : charger `holdout_hard/scenario_bot-01.json` → `ValueError: must be located in a
  'config/board/<board>/scenario/' directory`.
- **(b) Objectifs** : les clés `objectives`, `objectives_ref`, `objective_hexes` sont SUPPRIMÉES et
  lèvent une erreur explicite ([game_state.py](../../../engine/game_state.py)). Source unique désormais : terrains
  flaggés `"objective": true` dans le `terrain_ref` (règles 14.01/14.02). **Tous** les scénarios
  de la banque utilisent `objectives_ref` → tous invalides.
- **(c) Refs de walls périmées** : `config/board/44x60x5/walls/` ne contient que `walls-33`,
  `walls-mc1`, `walls-none`. 28 scénarios de la banque référencent `walls-11` (inexistant) —
  27 avec extension `.json`, 1 sans (format à normaliser au passage) ; les 33 autres utilisent
  `"random"`.
- **(d) Zones de déploiement** : voie moderne = section `deployment_zones` du terrain_ref
  (polygones par joueur, [game_state.py](../../../engine/game_state.py)) ; voie legacy = fichier nommé
  `config/deployment/{cols}x{rows}/<zone>.json` (436-440), or `config/deployment/220x300/` ne
  contient que `mc1.json` — le `deployment_zone: "hammer"` de toute la banque est introuvable.
- **(e) Niveaux** : les scénarios d'entraînement n'ont pas de `terrain_ref`, donc aucun étage —
  l'agent ne s'entraînerait jamais sur la feature niveaux même une fois le reste réparé.
- **(f) La training config ELLE-MÊME est cassée** (raté des deux premiers audits) : dans les
  5 phases de `CoreAgent_training_config.json`, `scenario_sampling.train_wall_ref_weights` =
  `walls-11/21/31.json` (0.3 chacun, inexistants) et `eval_objectives_refs` =
  `objectives-51.json` (le dossier `objectives/` n'existe plus). Après le fix R2,
  `_expand_random_ref_weights` lèvera « unknown refs for board walls » ([train.py](../../../ai/train.py)).
- **(g) Chemin d'éval holdout cassé dans `ai/bot_evaluation.py`** :
  `_materialize_eval_scenario_refs` ÉMET `objectives_ref` (75, clé rejetée par le moteur) et
  les `eval_wall_refs`/`eval_objectives_refs` pointent les mêmes fichiers inexistants.
  Consommé par les callbacks d'éval de train.py (~3231/3340), l'éval finale (~4185) —
  cassera même après T3/T4 si seul train.py est migré.

### R4 — Allocation des pertes : gym non reconnu comme "défenseur IA" (BLOQUANT runtime)
**Repro** (moteur nu, gym_training_mode=True, scénario board valide) : première action
`squad_shoot` → `RuntimeError: squad_shoot: allocation tir non terminee en auto pour squad 1001
(defenseur non-IA ?)` ([w40k_core.py](../../../engine/w40k_core.py)).
Cause : le moteur d'allocation mutualisé tir/fight décide humain-vs-auto via des prédicats qui
lisent UNIQUEMENT `game_state["player_types"]` ; en training self-play `pve_mode=False` →
`player_types = {"1":"human","2":"human"}` ([w40k_core.py](../../../engine/w40k_core.py)) → l'allocation attend un
humain. Il y a en réalité **QUATRE prédicats divergents** :
- `W40KEngine._is_player_human` — consciente de `gym_training_mode` (2201-2206) ;
- `_target_defender_is_ai` ([shared_utils.py](../../../engine/phase_handlers/shared_utils.py)) — player_types only, `auto_decider` de SHOOT_CTX ;
- `_is_ai_controlled_fight_unit` (fight_handlers, def ~97) — player_types only ; utilisée par
  `_fight_auto_defender` (def ~5705) → `auto_decider` de **FIGHT_CTX** (~5715-5728) et par
  les 4 décisions `defender_human` du flux fight (~5425, 5450, 6150, 6184) ;
- ~~`_is_ai_controlled_shooting_unit`~~ (shooting_handlers) — player_types only ; pilotait
  l'auto-activation `active_shooting_unit` (cf. ⚠️ ci-dessous). **Supprimé le 2026-08-08 avec
  l'auto-activation elle-même** : plus aucun appelant. La matrice R4 reste couverte par
  `is_programmatic_owner` / `is_programmatic_defender` et `_is_ai_controlled_fight_unit`.
**La mêlée crashe de la même façon que le tir** (vérifié par lecture) : `squad_fight` →
`build_manual_fight_allocation` non `done` → `RuntimeError "squad_fight: allocation combat non
terminee en auto"` ([w40k_core.py](../../../engine/w40k_core.py)), garde jumelle dans fight_handlers
(~3352-3357). Le gate `is_gym_training` de la consolidation (~1552) ne couvre PAS
l'allocation.
**Fix vérifié par simulation côté tir uniquement** (monkeypatch : `_target_defender_is_ai`
renvoie True si `game_state["gym_training_mode"]`) : le tir s'auto-résout ensuite correctement.
⚠️ Le smoke test « moteur nu jusqu'au tour 5 » ne prouve PAS le chemin d'allocation fight :
seule `_target_defender_is_ai` était patchée — la seule explication cohérente est qu'aucune
blessure de mêlée n'a été réussie pendant le smoke. À couvrir explicitement en T1 (scénario de
smoke avec pertes en mêlée garanties).
⚠️ Ne PAS "fixer" en mettant `player_types` à `"ai"` : cela active l'auto-activation tir
(`active_shooting_unit`, [shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py)) qui reste alors périmé après
l'activation et fait exploser le décodeur (`active_shooting_unit X is not in
shoot_activation_pool`, [action_decoder.py](../../../engine/action_decoder.py)) — vérifié par exécution.
✅ **CE MODE D'ÉCHEC EST FERMÉ LE 2026-08-08** : l'auto-activation « tête du pool » n'existe plus
(ni au montage du pool, ni en fin d'activation), et `squad_shoot` libère la clé à la fin de
l'activation. Basculer `player_types` sur `"ai"` ne fait donc plus exploser le décodeur — mesuré
sur les trois configurations. L'avertissement reste ici pour l'historique du diagnostic R4 ; il ne
décrit plus le code. Cf. [decisions_du_joueur.md §9 P3-3](decisions_du_joueur.md#s9).

### R5 — Wrappers et bots sur l'ANCIEN layout d'actions (BLOQUANT runtime)
**Repro** (pile complète `BotControlledEnv(ActionMasker(W40KEngine))` + GreedyBot) :
`env_wrappers.py` force `self.env.step(11)` comme "WAIT" → dans l'espace actuel 11 =
**advance direction 5** → `ValueError: convert_squad_action: advance_roll manquant`
([action_decoder.py](../../../engine/action_decoder.py)).
- `ai/evaluation_bots.py` : `WAIT_ACTION = 11` (actuel : **18**) ; usages de `12` comme action
  spéciale (actuel : fall back dir 0) ; slots de tir supposés 4-8 (actuel : **19-23**) ;
  `DEPLOYMENT_ACTIONS = [4..8]` réutilisé comme slots de TIR (86) ; moves supposés 0-3
  (`0 in valid_actions` 135, `[0, 1, 2, 3, WAIT_ACTION]` 179) au lieu de 0-5.
- `ai/env_wrappers.py` : littéraux `11` périmés en 436 (`step(11)`), 796 (`action == 11`),
  900 (`bot_action == 11`) ; plages shoot 4-8 codées en dur 793, 871, 898. Le fichier
  **mélange déjà les deux espaces** : les branches "Pool empty -> advance phase via WAIT"
  retournent, elles, `18` (valeur correcte) — 556, 854 (BotControlledEnv) et 1172, 1188
  (SelfPlayWrapper). C'est la preuve d'une migration partielle, pas un layout cohérent.
- `ai/game_replay_logger.py` (raté des deux premiers audits) : layout encore PLUS
  ancien à 8 actions (`action % 8`, moves 0-3, shoot=4, charge=5, wait=6, fight=7) — les
  replays de training décoderaient n'importe quoi ; à migrer ou à condamner explicitement.
- Les actions de déploiement 4-8 sont, elles, TOUJOURS valides ([action_decoder.py](../../../engine/action_decoder.py)).
- L'incohérence est documentée dans la config elle-même : `justification` dit
  "action_space_size=31 (16 micro + 15 macro)" alors que le champ vaut 41 (26 micro + 15 macro)
  — les wrappers/bots sont restés sur un layout intermédiaire.

### R6 — Bug moteur : socles ovales en éligibilité de charge (touche AUSSI le PvP)
**Repro** : scénario contenant un Carnifex ou Psychophage (seuls types à `BASE_SIZE` liste,
vérifié via UnitRegistry : `[41,27]` et `[47,36]`) → à l'entrée en phase charge,
`charge_build_valid_destinations_pool` → `TypeError: can only concatenate list (not "int") to
list` ([charge_handlers.py](../../../engine/phase_handlers/charge_handlers.py)) : `_mover_bs = unit["BASE_SIZE"]` puis
`(_mover_bs + 1) // 2` sans gérer le cas liste, alors que le même bloc le gère pour l'ennemi
6 lignes plus bas (`_e_bs_int = max(_e_bs) if isinstance(_e_bs, (list, tuple)) ...`, 3634-3635).
Chemin atteignable en PvP via `_has_valid_charge_target` (3390) → à corriger indépendamment du
training. Les rosters d'entraînement Tyranids peuvent contenir ces unités.
**DEUXIÈME occurrence du même pattern** : `_charge_reverse_goal_bfs_for_eligibility`
([charge_handlers.py](../../../engine/phase_handlers/charge_handlers.py)), même asymétrie avec l'ennemi (832-833), calcul fait AVANT le
garde `BASE_SHAPE == "round"`. Nuance vérifiée : la fonction est DÉSACTIVÉE sur boards scalés
(appelée seulement si `inches_to_subhex <= 1`, ~3693-3697 ; notre board = 5) → site
inatteignable en pratique sur 44x60x5. Le fix T1 couvre quand même LES DEUX sites (défense en
profondeur) ; seul le premier (3627) crashe réellement.

### R7 — Fin d'épisode au tour limite : masque vide sans terminaison (moteur nu)
**Repro** (moteur nu, sans wrapper, scénario fight, R4 simulé) : au dernier tour, phase fight
du joueur 2, tous les pools vides, aucun état fight pendant → masque entièrement vide,
`terminated=False`. MaskablePPO crashe sur masque vide.
Analyse statique concordante : SEULE `_fight_phase_complete` (fight_handlers, def ~1867,
appelée ~1488/1904/2408) pose `game_over` en vif — et uniquement **au sein d'un `step()`**.
Masque vide = plus aucun step légal = la complétion de phase n'est jamais déclenchée.
⚠️ `_advance_to_next_player` était du CODE MORT en production — **supprimée le 2026-07-19**
(cf. [§0.4](index_v11.md)) : elle n'existe plus, ne pas la chercher.
Nuance config : la limite de tours existe en deux endroits — `max_turns` (game_config.json L14)
et `max_turns_per_episode` (training config) ; clarifier en T5 lequel fait foi en moteur nu.
Dans la pile réelle, ce cas est censé être absorbé par le "WAIT forcé" du wrapper
([env_wrappers.py](../../../ai/env_wrappers.py)) — actuellement cassé par R5. **À revalider après R5** : si le
deadlock persiste à travers le wrapper, corriger la root cause côté moteur (la complétion de la
phase fight du dernier tour doit déclencher la fin d'épisode sans exiger une action illégale),
pas en injectant des actions bidon.

### R8 — Interface agent aveugle aux nouvelles règles (non bloquant pour Phase A)
Vérifié par lecture concordante :
- **Niveaux** : aucune feature d'élévation dans l'observation (ni 108 ni 357) ; l'agent subit le
  coût de descente §13.06 (retranché du budget rigide, [shared_utils.py](../../../engine/phase_handlers/shared_utils.py)) sans pouvoir
  le percevoir ; il ne peut pas monter (commentaire moteur : "l'IA directionnelle 2D ne monte
  pas", même bloc). Le moteur, lui, gère montée/descente (`_model_climb_reachable_floor_cells`
  [movement_handlers.py](../../../engine/phase_handlers/movement_handlers.py), `reachable_multilevel_field`
  [engine/phase_handlers/geodesic_move.py](../../../engine/phase_handlers/geodesic_move.py)).
- **Pivot/perModelMove** : résolus automatiquement par le moteur (plan rigide) — aucun point de
  décision agent. Légal règles (un placement légal parmi d'autres), sous-optimal seulement.
- **Fight V11** : action 25 = pile-in + déclaration + résolution + consolidation auto
  (`_ai_select_pile_in_destination` fight_handlers.py, `_ai_select_fight_target` 1725,
  `_ai_select_consolidation_destination` 1436). Légal, choix internes non pilotés par la policy.
- **LoS/engagement 3D** : gate vertical implémenté ([spatial_relations.py](../../../engine/spatial_relations.py)) mais le module
  lève lui-même "câblage incomplet" si les données verticales manquent (186-189, chantier 4) ;
  l'observation utilise une `los_topology` 2D "legacy boards" (observation_builder.py).
  → Le chantier LoS 3D (Documentation projet "Chantier 5") est un PRÉREQUIS règles pour le tir
  multi-niveaux ; le training Phase A n'en dépend pas tant que les scénarios d'entraînement
  restent mono-niveau, mais la Phase B avec terrains à étages OUI. Vérifier l'état du chantier
  avant d'activer des terrains à étages en training.

### Notes non bloquantes (à traiter en T6)
- ✅ **RÉSOLU le 2026-08-08** — `active_shooting_unit` : le cycle de vie est désormais le même
  partout (la clé désigne l'activation de tir EN COURS, posée par son début, retirée par sa fin).
  Elle reste absente du gym parce que `player_types` y vaut `human/human`, non parce que le
  chemin serait malsain. Cf. [decisions_du_joueur.md §9 P3-3](decisions_du_joueur.md#s9).
- `ai/target_selector.py` : orphelin (importé seulement par son test unitaire).
- Docs périmées : AI_OBSERVATION.md décrit 357 floats, AI_TRAINING.md 355 — aucun ne décrit le
  pipeline squad 108 actif ; `justification` de la config dit 31 au lieu de 41. Les snapshots
  `BEST_CoreAgent_training_config.json` (obs 355) sont incompatibles avec le code actuel
  (`build_observation` exige 357, [observation_builder.py](../../../engine/observation_builder.py)).

<a id="s4"></a>
## 4. Décisions de design imposées

1. **Phase A à interface constante** : on garde `Discrete(41)` / `Box(108)`. Aucun ancien modèle
   n'est réutilisable de toute façon (layout obs squad + VecNormalize stats) → tout run se fait
   avec `--new`. Ne jamais écraser les zips existants (protégés).
2. **Source de vérité unique "joueur programmatique"** : le prédicat "ce joueur est piloté par la
   machine (auto-résolution)" doit exister en UN seul endroit, consultable depuis game_state
   (le flag `gym_training_mode` y est déjà copié, [w40k_core.py](../../../engine/w40k_core.py)/1011). Les QUATRE prédicats
   recensés en R4 (`W40KEngine._is_player_human`, `_target_defender_is_ai`,
   `_is_ai_controlled_fight_unit`, ~~`_is_ai_controlled_shooting_unit`~~ — supprimé le
   2026-08-08 avec l'auto-activation de tir, il n'en reste donc que TROIS) doivent s'appuyer
   dessus. Interdit de dupliquer le check. ⚠️ La bascule gym ne doit s'appliquer qu'aux décisions
   d'ALLOCATION/résolution, jamais au CHOIX de l'escouade à activer, qui appartient à l'agent
   depuis V11 §0.48 `L2` (cf. ⚠️ R4) : auditer chaque site d'appel avant de brancher le prédicat
   unique.
3. **Plus aucun ID d'action littéral dans ai/** : importer les constantes depuis
   `engine/macro_intents.py`. État réel : **AUCUNE constante d'action n'existe** — le mapping
   n'est qu'en commentaire (L9-18) ; seuls `INTENT_*`, `MAX_OBJECTIVES`, `BASE_ZONE_INTENT`,
   `TOTAL_ACTION_SIZE` sont définis. TOUT est donc à créer : `ACTION_WAIT = 18`,
   `SHOOT_SLOT_BASE = 19`, bases move/advance/fallback, `ACTION_CHARGE = 24`,
   `ACTION_FIGHT = 25`, `DEPLOY_SLOTS = range(4, 9)`. Un littéral d'action dans ai/ = bug de
   revue.
4. **Scénarios : référence de board explicite** — les scénarios d'agent restent sous
   `config/agents/<agent>/scenarios/` (banque par agent, rosters aléatoires) mais déclarent
   `"board_ref": "44x60x5"`. Le résolveur ([game_state.py](../../../engine/game_state.py), 1437, 1496) accepte alors :
   parent == `scenario/` d'un board (comportement actuel, inchangé pour le PvP) OU clé
   `board_ref` présente → `config/board/<board_ref>/`. Absence des deux = erreur explicite
   (pas de fallback). Alternative rejetée : déplacer la banque sous
   `config/board/44x60x5/scenario/` — casse la structure par-agent et le check exige un parent
   nommé exactement `scenario` (pas de sous-dossiers training/holdout).
5. **Miroir PvP strict** : la phase A ne modifie AUCUNE règle de jeu ; les fixes moteur (R4, R6)
   doivent être neutres pour le flux PvP manuel (mémoire projet : le flux gym copie le flux
   PvP, jamais le durcir/diverger). Seuils/conversions via `inches_to_subhex`.
6. **Prochain agent : 2 rosters seulement** (décision utilisateur 2026-07-14). Le nouvel agent
   ne s'entraîne que sur 2 rosters différents — spécialisation assumée, pas de généralisation
   multi-rosters. Câblage vérifié dans le code, AUCUNE modif moteur nécessaire :
   - la résolution passe par `agent_roster_ref`/`opponent_roster_ref` du scénario
     ([game_state.py](../../../engine/game_state.py)) ; trois formes supportées : `"training_random"` (tirage
     dans `config/agents/<agent_key>/rosters/<scale>/training/agent_training_roster*.json`),
     ref explicite `"training/<fichier>.json"`, ou **liste de refs** → `rng.choice`
     ([game_state.py](../../../engine/game_state.py)) ;
   - **voie retenue** : dossier `config/agents/<NouvelAgent>/rosters/<scale>/training/` ne
     contenant QUE les 2 fichiers (pattern `agent_training_roster*.json` obligatoire, clé
     interne `roster_id` requise) + `"agent_roster_ref": "training_random"` dans les scénarios
     → tirage 50/50 par épisode ;
   - `config/agents/_p2_rosters/` est PARTAGÉ entre agents (pool de tirage
     `150pts/training/` = 151 fichiers ; le dossier 150pts en contient bien plus, holdouts
     inclus) : si les 2 rosters incluent l'adversaire, restreindre `opponent_roster_ref`
     (ref explicite ou liste) — sinon P2 continue de tirer dans toute la banque ;
   - désactiver `roster_pool_schedule` dans la training config
     (`_filter_training_roster_candidates`, game_state ~1322-1393) : le filtre progressif
     swarm/troop/elite peut vider un pool de 2 fichiers → `ValueError
     "roster_pool_schedule produced zero eligible training rosters"` (~1422-1426).
     Si le schedule reste actif : le nommage doit matcher `(elite|swarm|troop)_(\d+)$`
     sinon écart SILENCIEUX du fichier ;
   - contraintes fichiers : suffixes `_kpis`/`_matchups` exclus du tirage, composition non
     vide. ⚠️ L'unicité des `roster_id` internes n'est PAS vérifiée au tirage (contrôlée
     seulement sur un chemin marginal) : deux fichiers au même roster_id passent en silence
     et fausseraient le suivi win-rate par-roster — vérifier à la main les 2 fichiers ;
   - `agent_roster_seed` (clé scénario) fige le tirage AGENT seulement — il ne fige PAS le
     tirage opponent (seed non transmis, `random_seed=None`) ;
   - conséquences training attendues : convergence plus rapide (distribution d'observations
     quasi stationnaire), holdouts multi-rosters non pertinents comme critère ; risque
     principal = un roster qui domine le gradient → **suivre le win-rate PAR roster**
     (`roster_info`/`agent_roster_id` déjà loggé par épisode,
     [step_logger.py](../../../ai/step_logger.py)), jamais l'agrégé seul (critère T6.3 à lire par-roster).

<a id="s5"></a>
## 5. Tranches d'implémentation

Chaque tranche se termine par sa validation (section 6) AVANT de passer à la suivante.

### T1 — Fixes moteur neutres (R4, R6) — ✅ FAIT, prédicat ET branchement verrouillés (2026-07-21)

> **Historique du statut** : ✅ (2026-07-15) → ⏳ PARTIEL (audit [§0.19.1](index_v11.md), 2026-07-20) → ✅
> ([§0.19.3](index_v11.md), 2026-07-21).
>
> 🔴 **Le démenti de [§0.19.1](index_v11.md)** : le code de T1 était en place et conforme, mais deux de ses trois
> volets n'étaient **verrouillés par aucun test** — le **site R6 n°1**
> (`_charge_reverse_goal_bfs_for_eligibility`, inatteignable au x5 : mutation `int()` sur une
> liste, suite **verte**) et **R4** (zéro occurrence de `is_programmatic_owner` /
> `is_programmatic_defender` dans `tests/`, alors que §8.3 impose une matrice complète).
>
> ✅ **R6 comblé en [§0.19.3](index_v11.md)** : `test_charge_oval_base_reverse_bfs.py` (+4, avec garde
> d'atteinte) — les DEUX sites rougissent désormais sur mutation.
>
> ✅ **R4 comblé** : `test_programmatic_owner_predicate.py` (+22) verrouille le **prédicat** et
> son refus du repli ; `test_r4_auto_decider_wiring.py` (+14) verrouille son **BRANCHEMENT** —
> or c'était ça, la rupture R4. Les **6** exigences de §8.3 sont couvertes, chaque cas gym ayant
> son jumeau PvP. 6 mutations au total, toutes rouges, dont une qui **rejoue la rupture R4
> d'origine**. Détail en [§0.19.3](index_v11.md). Le texte ci-dessous est celui de la session d'origine,
> **conservé tel quel**.

Réalisé : R6 normalisé dans les 2 sites ; prédicat unique `is_programmatic_owner` /
`is_programmatic_defender` (shared_utils), délégation de `_target_defender_is_ai` (SHOOT_CTX)
et `_is_ai_controlled_fight_unit` (FIGHT_CTX + 4 defender_human) ; `player_types` et
`_is_ai_controlled_shooting_unit` non touchés. Validé : 1152 passed / 2 skipped ; smoke gym
3 seeds — charge Carnifex OK, pertes fight réellement allouées via FIGHT_CTX (kill constaté).
Le masque vide au tour 5 (fin de fight P2) a été RE-CONSTATÉ → confirme R7, à traiter en T5.
Reste : validation PvP manuelle rapide (non-régression) côté utilisateur.
1. **R6** : normaliser `_mover_bs` en miroir exact du traitement ennemi
   (`_mover_bs_int = max(_mover_bs) if isinstance(_mover_bs, (list, tuple)) else
   int(_mover_bs)`) dans les DEUX sites : `charge_build_valid_destinations_pool`
   (~3627-3628) ET `_charge_reverse_goal_bfs_for_eligibility` (~825-826).
2. **R4** : introduire un prédicat unique (proposé : `is_programmatic_defender(game_state,
   target_sid)` dans shared_utils) : renvoie True si `game_state.get("gym_training_mode")` est
   True, sinon comportement actuel (player_types, erreurs explicites conservées). Sites à
   brancher — inventaire vérifié :
   - `SHOOT_CTX.auto_decider = _target_defender_is_ai` (shared_utils ~113), consommé par
     `_manual_allocation_step` (~6212, 6242) ;
   - `FIGHT_CTX.auto_decider = _fight_auto_defender` (fight_handlers ~5728), les checks
     `defender_human` du flux fight (~5425, 5450, 6150, 6184), ET les deux gardes
     `RuntimeError "allocation ... non terminee en auto"` (`squad_shoot`/`squad_fight` dans
     w40k_core + garde jumelle fight_handlers ~3352-3357) qui doivent cesser de crasher une
     fois le prédicat branché ;
   - `HAZARD_CTX` (shared_utils ~6423-6437) n'a pas d'`auto_decider` : le hazard est DÉJÀ
     gym-aware au call-site (`auto_resolve = gym_training_mode`, [w40k_core.py](../../../engine/w40k_core.py)) sans lire
     player_types — rien à faire en gym ; corollaire à vérifier : en PvE, un défenseur IA
     passerait par l'allocation hazard MANUELLE ;
   - chemins `squad_shoot_validate` ([w40k_core.py](../../../engine/w40k_core.py)) et prompts rule-choice
     ([w40k_core.py](../../../engine/w40k_core.py)) — déjà sur `_is_player_human`, vérifier qu'ils basculent sur le
     prédicat unique sans changement de comportement PvP.
   Ne PAS toucher `player_types`. ~~Ne PAS brancher `_is_ai_controlled_shooting_unit`
   (auto-activation) sur la bascule gym (cf. ⚠️ R4)~~ — sans objet depuis le 2026-08-08 :
   l'auto-activation de tir et son prédicat n'existent plus.
   Ajouter au smoke test T1 un scénario garantissant des **pertes en mêlée** (le chemin
   FIGHT_CTX n'a jamais été exercé en gym, cf. R4).
3. Vérification de non-régression PvP : `python3 -m pytest tests/ -x -q` (suite existante,
   1152 tests collectés au 2026-07-14) + une partie PvP manuelle rapide côté utilisateur.

### T2 — Migration wrappers + bots vers l'espace squad (R5) — ✅ FAIT (2026-07-15)

Réalisé : constantes nommées dans `macro_intents.py` (MOVE/ADVANCE/FALL_BACK_DIRS, ACTION_WAIT=18,
SHOOT_SLOTS=19-23, ACTION_CHARGE=24, ACTION_FIGHT=25, DEPLOY_SLOTS=4-8 — miroir de
`SQUAD_ACTION_*` de shared_utils). `evaluation_bots.py` : 8 bots migrés (helper `_first_action_in`,
`_shoot_focus_fire` sur SHOOT_SLOTS, dicts de poids déploiement via DEPLOYMENT_ACTIONS, TacticalBot
inclus) — zéro littéral d'action résiduel. `env_wrappers.py` : bug phare R5 corrigé (`step(11)` →
`ACTION_WAIT`), `return 18` et trackers diagnostiques shoot/wait migrés (BotControlledEnv).
⚠️ **Attribution corrigée le 2026-08-02 (§0.47 É7)** : cette ligne créditait aussi
`SelfPlayWrapper`. C'est faux — les trackers shoot/wait et `get_shoot_stats` vivent
**entièrement dans `BotControlledEnv`** ; `SelfPlayWrapper` n'en porte aucun. `game_replay_logger.log_action` (layout `% 8` mort + lit `self.env.controller`
absent du moteur squad, aucun appelant vif) CONDAMNÉ (NotImplementedError explicite). Tests migrés
(`test_evaluation_bots.py`, `test_env_wrappers.py`, `test_game_replay_logger.py`). Audit train.py /
multi_agent_trainer / bot_evaluation : aucun littéral d'action (les `objectives_ref` restent T3/T4).
Validé : 1152 passed / 2 skipped ; smoke moteur nu 3 seeds (shoot+charge+fight, unité socle-ovale
BASE_SIZE liste présente → charge franchie sans TypeError R6, 2 pertes mêlée via FIGHT_CTX) ; smoke
pile complète (BotControlledEnv + GreedyBot migré) avance 45-48 steps → **dépasse le 1er WAIT forcé**
(preuve que R5 est levé). Persiste : deadlock fight pile_in fin de partie (boucle 1000 steps /
masque vide sur eligible units) = R7, UNMASQUÉ par le fix R5, à traiter en T5 (déjà prévu par le doc).

**Contre-vérification indépendante (2026-07-15)** — T2 confirmée conforme (code relu, suite
rejouée verte, grep de contrôle passé, smoke pile complète rejoué), avec 3 précisions :
1. ~~**Inexactitude du rapport** : `multi_agent_trainer.py` contient encore `action % 8` +
   `unit_idx = action // 8` (monkeypatch legacy de `controller.execute_gym_action`). Branche
   INERTE (gardée par `hasattr(actual_env, 'controller')`, attribut absent du moteur squad)
   mais « aucun littéral dans multi_agent_trainer » est faux — à condamner/purger comme
   `game_replay_logger.log_action` (raccroché à T6 hygiène ou T5).~~
   → ✅ **SOLDÉ, NE PLUS CITER (voir [§0.8](index_v11.md)).** Le monkeypatch a été purgé au commit `6a7a9de1`,
   le commentaire de purge qui l'a remplacé a disparu avec [§0.8](index_v11.md), et `game_replay_logger` est
   supprimé. **`grep 'action % 8' ai/multi_agent_trainer.py` est vide.** Ce point a induit deux
   relecteurs en erreur *après* sa résolution, parce qu'ils l'ont cité depuis cette doc au lieu de
   grep le fichier — d'où le rappel : **une doc n'est pas une source, le code l'est.**
2. **Précision sur le smoke pile complète** : les épisodes 40-48 steps ne se terminent PAS
   normalement — ils sont tués par le garde « 1000 steps » du wrapper, en deadlock
   `squad_wait` fight/pile_in dès le **TOUR 1** (scénario à unités pré-engagées), pas
   seulement au tour limite. Le périmètre T5 est donc PLUS LARGE que « fin d'épisode au
   dernier tour » : toute phase fight avec pile-in éligibles peut boucler.
3. **Nouveau symptôme, même famille (T5)** : avec `agent_seat_mode="p2"` ou `"random"`
   (= la config réelle de train.py), le RESET crashe —
   `RuntimeError "bot-owned eligible units with empty action mask"` en fight tour 1
   (le bot P1 déroule son tour jusqu'à la phase fight alternée où l'unité éligible
   n'appartient plus au joueur courant). Seul seat="p1" passe. À couvrir en T5.

1. Ajouter dans [macro_intents.py](../../../engine/macro_intents.py) les constantes nommées manquantes (WAIT=18, bases des
   plages move/advance/fallback/shoot, CHARGE=24, FIGHT=25, DEPLOY_SLOTS=range(4,9)) et les
   utiliser partout dans `ai/env_wrappers.py` et `ai/evaluation_bots.py` (supprimer
   `WAIT_ACTION = 11`, les littéraux 11/12, les plages 4-8 hors déploiement ; remplacer aussi
   les `return 18` déjà corrects mais en dur — 556, 854, 1172, 1188 — par la constante).
2. **Auditer la logique de chaque bot phase par phase** contre le mapping actuel : la sélection
   "shoot" doit itérer les slots 19-23 (slots ennemis via `get_enemy_slot_mapping`), "charge"=24,
   "fight"=25, les moves par direction 0-5/6-11/12-17. Les bots choisissent des actions dans le
   masque : tout choix hors masque = erreur explicite (comportement existant à préserver).
3. `SelfPlayWrapper` : mêmes corrections (WAIT forcé, détection "pool empty").
4. Auditer `ai/train.py`, `ai/bot_evaluation.py` ET `ai/game_replay_logger.py` (layout 8
   actions, 774-828) pour les mêmes littéraux périmés — y compris les dicts de poids
   `{4: 0.50, ...}` d'evaluation_bots (6 occurrences) et les `return 10/4`.

### T3 — Chemins board + config training (R1, R2) — ✅ FAIT (2026-07-15)

Réalisé : **R2** — `_list_available_board_refs` (train.py) et `analyzer.py` résolvent via
`config_loader.get_board_dir()` (plus aucune reconstruction `{cols}x{rows}` en ai/ ; grep ai/
+ scripts/ = seuls ces 2 sites vifs, `analyzer_avant_refactor.py` = backup jamais importé, laissé
tel quel). **R1** — `--training-config` sans défaut silencieux : helper `_require_training_config_phase`
lève une erreur explicite listant les phases (`['x1','x5_append','x5_new','x1_debug','x5_debug']`)
quand un agent est sélectionné sans phase (décision recommandée du doc retenue en MODE NUIT).
**1bis** — retrait de la dimension objectives du tirage de scénarios (`_load_scenario_objectives_ref`
supprimée, `_apply_wall_ref_weighting` en wall-only, `_materialize_scenario_with_refs` n'émet plus
objectives_ref via ce chemin). **1ter** — training config purgée dans les 5 phases
(`train_wall_ref_weights` → `{"default":1.0}`, `eval_wall_refs` → walls-33/mc1 réels,
`train_objectives_ref_weights`/`eval_objectives_refs` supprimées) ; `bot_evaluation.py`
(`_materialize_eval_scenario_refs`) migré : n'émet plus `objectives_ref`/`objectives`/`objective_hexes`
(objectifs = contrat terrain). Point 3 (deployment legacy `{cols}x{rows}`) : différé T4 (décision T4).
Tests ajoutés : `tests/unit/ai/test_train_board_refs.py` (get_board_dir, expand refs inconnus/valides,
R1 message) + `tests/unit/ai/test_bot_evaluation_eval_refs.py` (objectives_ref absent du matérialisé) +
maj `test_analyzer_utils.py` (fake loader get_board_dir).
Validé : **1162 passed / 2 skipped** (baseline 1152 + 10 tests T3, zéro régression) ;
`train.py --step --training-config x1_debug` **dépasse la résolution walls/objectives** (500 entrées
pondérées, plus de FileNotFoundError board dir) — le crash suivant = **R3-a** (scénario hors dossier
`scenario/`) = T4, hors périmètre T3. Smoke moteur nu (Annexe A.1) + pile GreedyBot (A.2), 3 seeds ×
scénario Psychophage/ScreamerKiller : **charge franchie sans TypeError (R6 non régressé)**, toutes
phases atteintes, zéro exception.
⚠️ **Pertes de mêlée non re-démontrées end-to-end** : le smoke A.1 (aléatoire non dirigé, adversaire
passif) ne les produit pas *par conception* (réserve explicite Annexe A) ; le smoke A.2 (GreedyBot des
2 camps) bute sur le **deadlock R7/T5 `fight/pile_in` dès le tour 1** AVANT toute résolution de
blessure. Ce blocage est un item OUVERT (T5), indépendant de T3 (aucun code moteur touché) — la
preuve FIGHT_CTX reste celle de T1 (committée). À re-valider après T5.

**Contre-vérification indépendante (2026-07-15)** — T3 confirmée conforme : repro R1 rejouée
(erreur explicite avec les 5 phases), repro R2/x1_debug rejouée (« 500 entries, 100 unique
files », crash suivant = R3-a exactement), 1162 tests collectés / suite verte, config purgée
vérifiée dans les 5 phases, aucun code moteur touché (git status). UNE réserve mineure :
`_materialize_scenario_with_refs` (train.py ~642-668) conserve un paramètre `objectives_ref`
et sa branche d'émission `scenario_copy["objectives_ref"] = ...` — MORTE (l'unique appelant
~854 ne passe que wall_ref) mais tout futur appelant réémettrait une clé rejetée par le
moteur. À purger en T4 (avec la migration) ou T6.

1. **R2** : remplacer la reconstruction `{cols}x{rows}` de `_list_available_board_refs`
   ([train.py](../../../ai/train.py)) par `config_loader.get_board_dir()`. Même motif déjà repéré ailleurs :
   `ai/analyzer.py` (et `analyzer_avant_refactor.py`) reconstruisent
   `config/board/{cols}x{rows}/objectives`. Greper `ai/` et `scripts/` pour le solde.
1bis. **train.py émet encore `objectives_ref`** : `_load_scenario_objectives_ref`
   ([train.py](../../../ai/train.py)) et le sampler `train_objectives_ref_weights` (~873, 887-893)
   expansent des refs `objectives-*.json` — clé que le moteur REJETTE (game_state:320-329).
   Cette branche doit être supprimée/migrée vers les terrains (T4), sinon le tirage de
   scénarios de train.py casse après migration.
1ter. **Migrer la training config et le chemin d'éval** (R3-f/R3-g) : purger
   `train_wall_ref_weights`/`eval_wall_refs`/`eval_objectives_refs` des refs inexistantes
   dans les 5 phases de `CoreAgent_training_config.json`, et migrer
   `_materialize_eval_scenario_refs` (bot_evaluation.py, émission d'`objectives_ref`)
   vers le contrat terrain — les callbacks d'éval train.py en dépendent.
2. **R1** : décision de config (pas de code) : soit ajouter une phase `default` pointant vers la
   config x1 courante dans `CoreAgent_training_config.json`, soit rendre `--training-config`
   obligatoire (erreur explicite listant les phases disponibles). Recommandé : la seconde (pas
   d'alias silencieux). À valider avec l'utilisateur au checkpoint T3.
3. La voie legacy `config/deployment/{cols}x{rows}/` ([game_state.py](../../../engine/game_state.py)) : si la banque
   migrée (T4) n'utilise plus `deployment_zone` nommée, ne pas y toucher ; sinon fournir les
   fichiers de zones pour `220x300` (décision en T4).

### T4 — Migration de la banque de scénarios (R3) — ✅ FAIT (2026-07-15)

Réalisé : **resolver `board_ref`** — helper `_resolve_board_dir(scenario_file, board_ref,
purpose)` dans game_state.py (seul fichier moteur touché) : parent `scenario/` (voie PvP
inchangée) OU `board_ref` → `config/board/<board_ref>/` ; erreurs explicites (absence des
deux, board inexistant, traversal), câblé dans `_resolve_shared_config_path`,
`_load_shared_walls_from_ref` (random) et `_read_terrain_file` + call-sites. **Bug moteur
corrigé au passage** : `pool_set` gardé derrière le NOM legacy `deployment_zone` → les zones
issues du terrain (voie moderne) ne peuplaient pas le pool de déploiement random/fixed
(fix neutre PvP, commenté en ~576). **Terrains plats** `terrain-train-01/02/03.json`
(5 objectifs, deployment_zones "1"/"2", 0 étage). **Migration** :
`scripts/migrate_scenario_bank_v11.py` (idempotent) — 61 scénarios migrés (0 clé legacy,
`board_ref`+`terrain_ref`), `training_save/` (30) archivé sous `_archive_pre_v11/`.
**Outillage** : `build_holdout_benchmark.py` migré ; `scenario_manager.py` NON touché
(chemin dormant — `config/scenario_templates.json` absent → lève à la construction ; son
alignement 0/1 vs 1/2 traverse multi_agent_trainer = chantier séparé à valider).
> ⚠️ **Périmé depuis le 2026-07-29** : « chemin dormant » était en fait du **code mort**, et
> `ai/scenario_manager.py` a été **supprimé** — l'alignement 0/1 vs 1/2 n'a plus d'objet.
> Cf. [§0.45](index_v11.md).
**Balayage** : `scripts/sweep_scenario_bank_v11.py` — 61/61 chargés + reset. Tests +83.
> ⚠️ **Le script n'existe plus** (supprimé au commit `924c2b41`, constaté le 2026-08-02) : cette
> ligne décrit ce qui a été fait à l'époque, pas un livrable disponible. **La capacité de
> balayage, elle, survit** — elle est exercée par
> [`tests/unit/ai/test_scenario_bank_migration_v11.py`](../../../tests/unit/ai/test_scenario_bank_migration_v11.py).
> (Écart §0.47 É5.)
Validé : 1245 passed / 2 skipped ; Carnifex en charge 3 seeds sans TypeError (R6).
⚠️ Pertes de mêlée toujours non démontrables end-to-end (deadlock R7/T5 fight/pile_in tour 1,
confirmé 3 voies) — inchangé depuis T2/T3, aucun code fight/charge touché par T4.

**Contre-vérification indépendante (2026-07-15)** — T4 confirmée conforme : balayage rejoué
(61/61 + reset, 0 clé legacy hors archive — grep indépendant), suite rejouée (1245 collectés,
verte), sample de scénario migré inspecté (clés legacy absentes, refs présentes), 3 terrains
inspectés (5 objectifs, dz 1/2, 0 floor), resolver relu (zéro fallback, traversal gardé),
`users.db` propre, `charge_handlers` non touché (non-régression R6 structurelle). Réserves
mineures : (1) les scripts `migrate_/sweep_scenario_bank_v11.py` n'ont pas de bootstrap
`sys.path` — exécutables uniquement avec `PYTHONPATH=.` ; (2) la réserve T3 (paramètre
`objectives_ref` mort de `_materialize_scenario_with_refs`, train.py ~645-668) n'a PAS été
purgée en T4 → reste pour T6.

Plan d'origine (réalisé ci-dessus) :
1. Implémenter la clé **`board_ref`** dans le résolveur (décision de design n°4) :
   `_resolve_shared_config_path`, `_load_shared_walls_from_ref` (branche "random") et
   `_read_terrain_file` ([game_state.py](../../../engine/game_state.py), 1437, 1496). Erreur explicite si ni parent
   `scenario/` ni `board_ref`.
2. Créer les **terrains d'entraînement** sous `config/board/44x60x5/terrain/` : chaque terrain
   porte objectifs (`"objective": true`) et `deployment_zones` (polygones J1/J2). Point de départ:
   dériver des terrains existants (`terrain-mc1.json`, `terrain-floors-test.json`) et des
   anciennes refs objectives/walls de la banque. Phase A : terrains PLATS uniquement (pas
   d'étages) — les étages arrivent en Phase B (cf. R8/LoS 3D).
   ⚠️ Piège vérifié : un terrain SANS aucune area `"objective": true` donne une liste
   d'objectifs VIDE en silence (game_state ~376-381) — le script de migration doit valider
   ≥ 1 objectif par terrain produit.
3. Migrer les **61 scénarios** de la banque (training 30 + training_benchmark 4,
   holdout_regular 10, holdout_hard 10 + matchups 7) : supprimer `objectives_ref`, remplacer
   `deployment_zone`/`wall_ref` par `terrain_ref` (+ `wall_ref` réel encore supporté) +
   `board_ref`. Statuer sur `scenarios/training_save/` (30 JSONs) : migrer ou archiver.
   Écrire un script de migration dans `scripts/` (one-shot, vérifiable) plutôt qu'une édition
   manuelle. Les refs `"random"` (walls/terrain)
   doivent piocher dans le board résolu — vérifier le support côté train.py
   (`_expand_random_ref_weights`, [train.py](../../../ai/train.py)) après le fix R2.
4. Outillage impacté — état vérifié :
   - `scripts/build_holdout_benchmark.py` **ÉMET les clés legacy** (`deployment_zone: "hammer"`
     110, `objectives_ref` 118/246/254) → à migrer, pas seulement à vérifier ;
   - ~~`ai/scenario_manager.py` : utilise des `deployment_zones` avec clés joueur **0/1** alors
     que les terrains modernes utilisent **"1"/"2"** → incompatibilité à résoudre~~ **SANS OBJET
     depuis le 2026-07-29 : le fichier a été supprimé** (code mort, [§0.45](index_v11.md)) ;
   - `scripts/rebalance_holdout_hard_scenarios.py`, `scripts/build_dynamic_rosters.py` : aucune
     clé legacy détectée, re-vérifier après migration.

### T5 — Boucle complète et fin d'épisode (R7) — ✅ FAIT (moteur nu, 2026-07-16) — verrou confirmé par mutation ([§0.19.1](index_v11.md))

> ✅ **Confirmé le 2026-07-20** : le fix `_deployment_clearance_filter` est verrouillé —
> neutralisé, `test_deployment_mask_mirrors_commit_overlap_predicate` rougit en 6,7 s avec le
> symptôme d'origine (42 s vert sans mutation).
> ⚠️ **Mais le critère §6 de T5 est plus large que ce ✅** : il exige « ≥3 scénarios × sièges
> p1/p2 », alors que `test_t5_bare_loop.py` exerce **un** scénario × 3 seeds et **aucun siège**.
> Le ✅ vaut pour le **moteur nu, siège p1**, comme la tranche l'annonce dans son « Reste ».

Réalisé (périmètre MOTEUR NU, décision utilisateur : « smoke moteur nu avec pertes en mêlée
garanties + Carnifex en phase charge ») :

- **R7 ne se manifeste PAS en moteur nu** : `W40KEngine.get_action_mask()`
  ([w40k_core.py](../../../engine/w40k_core.py)) auto-avance déjà la phase fight quand ses pools sont vides
  (boucle `fight_phase_end` tant que masque vide ET pas game_over) → l'invariant
  `mask.any() or game_over` tient à CHAQUE step. Vérifié sur 3 scénarios `active` × 3 seeds +
  scénario fixe pré-engagé : zéro masque vide sans terminaison, zéro exception, toutes les
  parties se terminent (turn limit). Le fix conditionnel T5.2 sur `_fight_phase_complete`
  n'était donc PAS requis — non touché ; `_advance_to_next_player` (mort) laissé tel quel
  **à l'époque, supprimé depuis le 2026-07-19 ([§0.4](index_v11.md))**.
- **Vraie rupture bloquante en moteur nu = déploiement `active`, PAS R7 (nouvelle, hors R1-R8)** :
  `ActionDecoder._get_valid_deployment_hexes` ([action_decoder.py](../../../engine/action_decoder.py)) testait le
  chevauchement inter-unités par CELLULES (`build_occupied_positions_set`), alors que le commit
  `deployment_handlers.deploy_unit` (~1017) le teste par CLEARANCE euclidien CONTINU
  (`candidate_overlaps_any_unit`, plus strict rond↔rond). Le masque proposait donc des hexes que
  le commit rejetait (`deploy_footprint_occupied`) ; l'action restant dans le masque, elle
  échouait en boucle → deadlock (épisode tué au garde 1000 steps ; ~2/3 des seeds sur bot-01).
  **Fix** : `_get_valid_deployment_hexes` filtre désormais les candidats cellule-valides par le
  MÊME modèle que le commit (nouveau `_deployment_clearance_filter` : broad-phase numpy
  distance-centres puis `candidate_overlaps_any_unit` exact), miroir strict (règle projet « le
  déploiement copie la phase move »). Neutre PvP (même prédicat que le commit ; volet bornes/murs/
  pool inchangé). Seul `action_decoder.py` touché.
- **Smoke moteur nu (`scripts/smoke_t5_bare.py`, committé, sans monkeypatch)** :
  (A) bot-01/02/03 × seeds 1-3 → terminate + zéro masque vide ;
  (B) scénario fixe (ScreamerKiller P1 pré-engagé vs Termagant P2 ; Carnifex P1 à portée de
  charge d'un Termagant P2) → **pertes en mêlée réelles via FIGHT_CTX à chaque seed** (kill
  `squad_fight` constaté) + **Carnifex éligible en phase charge sans TypeError (R6)**.
- **Tests ajoutés (+7)** : `tests/unit/engine/test_deployment_clearance_parity.py` (4 : parité
  masque↔commit + anti-deadlock en clustering forcé) et `tests/unit/engine/test_t5_bare_loop.py`
  (3 : invariant `mask.any() or game_over`, pertes mêlée FIGHT_CTX, Carnifex charge R6). Suite
  `tests/unit/` verte (baseline 1245 + 7).

Reste (hors moteur nu, non couvert par cette tranche) : le smoke **pile complète** (wrapper
`BotControlledEnv`) — cf. contre-vérif T2 : reset crashe encore avec `agent_seat_mode="p2"/"random"`
(`bot-owned eligible units with empty action mask` en fight tour 1). Chantier wrapper/pool alterné
distinct, à traiter avant l'entraînement réel T6 avec la config de siège de train.py.

Plan d'origine :
1. Rejouer le smoke test pile complète (annexe A) après T1+T2 : 10 épisodes aléatoires masqués
   doivent se terminer (`terminated=True`, winner déterminé), zéro masque vide, zéro exception.
2. Si le deadlock R7 persiste : corriger côté moteur la complétion de phase fight au dernier
   tour, via le SEUL chemin vif : `_fight_phase_complete` (fight_handlers, def ~1867) doit
   aboutir à `terminated` sans exiger une action supplémentaire quand le pool est vide.
   `_advance_to_next_player` était mort en production (cf. R7) — **supprimée le 2026-07-19**
   ([§0.4](index_v11.md)), donc plus rien à statuer. Interdit de résoudre par injection d'action côté
   wrapper.
3. Étendre le smoke test aux scénarios migrés (T4), sièges p1/p2/random, et à un scénario
   contenant Carnifex/Psychophage (validation R6).

### T6 — Entraînement de validation + hygiène — ✅ FAIT (2026-07-19)

> T6-a→T6-h résolus — clôture 2026-07-19. T6.3 (baseline bots win-rate sur x1_debug) non
> démontrée sur 467 épisodes (bruit), mais hors critère : la mesure de référence est déportée sur
> `x1_long` (chemin critique — [v11_chemin_critique.md](../../Roadmap/v11_chemin_critique.md)). Les
> entrées ci-dessous sont chronologiques.

**Préalable levé** : le bloqueur résiduel laissé par T5 (« reset crashe avec
`agent_seat_mode="p2"/"random"` — `bot-owned eligible units with empty action mask` en fight
tour 1 ») **ne se reproduit plus**. Vérifié en miroir exact de train.py
(`ActionMasker` + `BotControlledEnv` + `GreedyBot`) sur `scenario_training_bot-01` × sièges
p1/p2/random × 2 seeds : les 6 combinaisons terminent (`terminated=True`, turn=5), zéro masque
vide. Le fix de parité déploiement de T5 l'a manifestement couvert.

**Rappel des critères de sortie (re-démontrés sur l'arbre T6)** : suite `tests/unit/` verte ;
smoke moteur nu `scripts/smoke_t5_bare.py` → `(A) invariant/terminaison=OK | (B) mêlée+Carnifex=OK`
avec `melee_kills_total=5` (pertes réelles via FIGHT_CTX) et `carnifex_charge_any=True` (R6).

**Deux ruptures T6 vérifiées et corrigées** (aucune ne figure dans R1-R8 — ce sont des reliquats
de T4/de code latent) :

- **T6-a — `wall_ref` exigé par le sampler alors que T4 l'a supprimé (BLOQUANT, crash immédiat)**
  **Repro** : `train.py --agent CoreAgent --scenario bot --new --training-config x1_debug --step`
  → `ConfigurationError: Required key 'wall_ref' is missing from mapping`
  (`_load_scenario_wall_ref`, train.py ~556, via `_apply_wall_ref_weighting`).
  **Cause** : `migrate_scenario_bank_v11.py` supprime délibérément `wall_ref` (docstring : « supprime
  les clés legacy … wall_ref ») — les 61 scénarios migrés sont TERRAIN-ONLY (`board_ref` +
  `terrain_ref`, vérifié : 61/61 sans `wall_ref`). Le contrat moteur rend `wall_ref` OPTIONNEL
  (`wall_hexes` XOR `wall_ref`, `terrain_ref` additif — game_state.py ~285-314). T4 a migré la
  banque mais pas ce sampler.
  **Fix** : `_load_scenario_wall_ref` renvoie `Optional[str]` — `None` quand la clé est ABSENTE
  (état légitime du contrat, pas une valeur par défaut masquant une erreur) ; une clé présente
  reste strictement validée (erreur explicite si vide/non-string). `None` traverse
  `_apply_wall_ref_weighting` sans override (poids `"default"` = « garde les murs du scénario »,
  ~853) → aucun `wall_ref` injecté.

- **T6-b — `--step` était un no-op SILENCIEUX (bloque analyzer + replay)**
  **Repro** : le run affiche « 📝 Step logging enabled » puis « ✅ StepLogger connected », et
  `step.log` reste réduit à son en-tête (7 lignes) après 20 min d'entraînement.
  **DEUX causes indépendantes, les deux corrigées** :
  1. *Le StepLogger n'est branché que sur la branche mono-env* (`if step_logger:
     base_env.step_logger = step_logger`) ; les **trois** branches vectorisées construisent leurs
     envs avec `step_logger_enabled=False`. Avec `n_envs=48` (x1_debug), `--step` ne pouvait rien
     produire. Le code forçait déjà `n_envs=1` pour `--replay`/`--convert-steplog` (~1326) mais
     PAS pour `--step`. → helper unique `_resolve_n_envs_for_step_logging` (train.py ~571) branché
     aux **3** sites de résolution de `n_envs` (~1354, ~1665, ~2129) : force l'env unique ET le
     DIT. Factorisé volontairement — trois gardes dupliqués sont exactement le motif de migration
     partielle qui a produit R5. ⚠️ Piège vérifié : les 3 sites impriment le MÊME message
     « 🚀 Creating N parallel environments » — ne pas se fier au log pour identifier le site actif
     (`--scenario bot` passe par `train_with_scenario_rotation`, site ~2129).
  2. *Bug latent : l'env est RECRÉÉ sans reconnecter le StepLogger* (train.py ~2637-2651,
     « For n_envs==1: recreate env with frozen model for self-play »). Ce second `base_env` reçoit
     `_metrics_tracker` mais jamais `step_logger` → le run journalisait « StepLogger connected »
     pour un env aussitôt jeté, puis s'entraînait sur un moteur MUET. Chemin exigeant `n_envs==1`
     (config = 48) → jamais emprunté, donc jamais vu. **Révélé par le fix (1).**
     → reconnexion en miroir de ~2377.
  ⚠️ `StepLogger.log_episode_start` avale toute exception (`except Exception: print("⚠️ Episode
  start logging error")`, step_logger.py ~254) — un step.log vide peut donc masquer une erreur.
  Ici le diagnostic a été fait par élimination (aucun warning émis ⇒ la fonction n'était PAS
  appelée ⇒ le moteur entraîné n'avait pas de logger).

- **T6-c — `squad_fight` : le COMMIT gym divergeait du PvP (crash d'épisode) — ✅ CORRIGÉ**
  **Repro** (déterministe) : `MELEE_SCENARIO` + actions tirées par `default_rng(seed*777+i)`,
  seed=1 → `ValueError: squad_fight: aucune cible pour squad 3 — mask aurait dû l'empêcher`.
  Seul seed=1 échoue (2 et 3 passent) → **un smoke vert ne prouvait pas son absence**
  (`smoke_t5_bare.py` tire avec `seed*99991+steps`, séquence différente).
  **Verdict contre-intuitif** : ce n'était PAS le masque. `_squad_is_in_fight` (« a chargé OU en
  ER ») est CONFORME à 12.04 et au prédicat PvP `fight_v11_is_eligible_to_fight`, explicitement
  « indépendant de la présence de cibles ». C'est le commit qui cherchait sa cible dans le
  **mapping de slots gelé du TIR** (`get_enemy_slot_mapping`) scoré par menace globale, **sans
  filtre de zone d'engagement** — donc capable de frapper hors ER (violation 12.05) et de crasher
  quand tous les slots sont morts (chargeur dont la cible meurt avant son activation).
  **Fix** (`w40k_core.py` SEUL, gym-only — `_process_squad_action` n'est appelé que par `step()`) :
  le commit consomme le prédicat du flux PvP (`_fight_build_valid_target_pool` +
  `_ai_select_fight_target`, cf. `_fight_v11_resolve_attacks`) ; pile-in avant la sélection de
  cible (ordre V11 12.02→12.04) ; pool vide = fight « à vide » via le MÊME moteur d'allocation
  (0 intent → summary vide, `done=True`). Garde `ValueError` supprimée : elle interdisait un cas
  légal (12.04/12.06) déjà accepté par le PvP. **Neutralité PvP totale** (`fight_handlers` intact).
  **Tests (+5)** : `tests/unit/engine/test_squad_fight_target_parity.py` (2 vérifiés comme
  échouant sur l'ancien code). Détail : `Documentation/Archives/chantiers/bug_squad_fight_mask_mismatch.md`.
  ⚠️ **Impact sur le plan [§9.4](decisions_du_joueur.md#s9.4)** : le site vif de la cible de mêlée a changé → cf. [§9.4](decisions_du_joueur.md#s9.4) point 1.

- **T6-d — dettes constatées pendant T6-c — DÉCISION UTILISATEUR (2026-07-16) : traiter AVANT le training**
  - **✅ RÉSOLU (2026-07-16) — Le gym n'entrait PAS dans la machine V11.** Mesuré sur épisode
    complet : en phase fight, l'état était invariablement `(fight_subphase='pile_in',
    snapshot_present=False, nb_selected_to_fight=0)`. `fight_phase_start` initialisait la machine,
    puis `squad_fight` (`_process_squad_action`) déroulait le sien — pile-in + fight +
    consolidation **par escouade, en une passe** — sans jamais avancer les états V11.

    **Diagnostic — deux ruptures, pas une.** (1) *États jamais posés* :
    `engaged_at_fight_step_start` absent (branche 12.04 « was engaged at the start of this step »
    inapplicable), `units_selected_to_fight` vide (12.04 « has not already been selected to fight
    this phase » **non appliqué** → une escouade engagée pouvait être re-sélectionnée dans la même
    phase ; 12.08 « was eligible to fight this phase » dérive du même set), `pile_in_done` vide.
    (2) *Ordre de phase faux* : 12.02 exige que TOUS les pile-in des DEUX joueurs précèdent le
    premier combat, et 12.04 date son snapshot du début de l'étape FIGHT — impossible tant que le
    pile-in d'une escouade s'intercale entre deux combats. Aucune pose d'état a posteriori ne
    corrige ça : c'est la découpe de l'action qui était fausse.

    **Fix — `w40k_core.py` seul, `fight_handlers` NON touché (neutralité PvP).** `squad_fight`
    devient **UNE sélection de l'étape FIGHT (12.04)**, encadrée par `_fight_v11_gym_settle` qui
    résout les deux étapes groupées (PILE IN 12.02 puis CONSOLIDATE 12.07) via les planificateurs
    **par-figurine** existants (`fight_pile_in_plan` / `squad_consolidate_plan` — jamais les
    helpers par-ancre condamnés). Aucune perte d'agence : l'agent ne choisissait déjà aucune
    destination de pile-in/consolidation, seulement l'unité qui combat. Action space, taxonomie de
    reward et compte de steps inchangés. Le driver **ne termine pas la phase** : le gym transitionne
    par `advance_phase` sur masque vide, comme toutes les autres phases — compléter depuis une
    action d'unité déclencherait la cascade, qui **remplace** le résultat de l'action et ferait
    perdre à l'agent le `fight_result` (donc le reward) du combat clôturant la phase.

    **Vérifié** : `fight_subphase` atteint `fight` puis `consolidate`, snapshot posé après les
    pile-in, alternance des sélecteurs P1↔P2 réelle, 17 `squad_fight` (vs 6) sur le même épisode.
    Suite 1293 verte, smoke `(A)/(B)` OK (5 kills mêlée, Carnifex charge), 18 épisodes
    BotControlledEnv+GreedyBot (p1/p2/random × 2 seeds) sans échec. Verrou :
    `tests/unit/engine/test_squad_fight_v11_state.py` (6 tests, tous rouges sur l'ancien code).
    Effet de bord corrigé au passage : `end_activation(arg4=FIGHT)` dérivait `phase_complete` des
    pools V10 que V11 ne construit plus (toujours vides → toujours `True`) ; signal mort écarté.
  - **Overrun 12.06 absent du gym** — n'existe qu'en modèle par-ancre, condamné par la décision
    « le pile-in de référence est le par-figurine du PvP » (2026-07-16). Légal (12.06 : « **can**
    make one additional pile-in move »). Spec complète : `Documentation/Archives/chantiers/pile_in_overrun_par_figurine_2026-08-18.md`.
  - **Mismatch cellules/clearance du BFS pile-in/conso** — mesuré 1102 ancres sur 72857 ; fix
    écrit, mesuré (0/71755 après, perf 2m01→1m33), puis **REVERTÉ** : `fight_handlers` est partagé
    et le changement n'est pas neutre PvP. Ne concerne que du code par-ancre condamné → priorité
    basse. Détail + mesures : `Documentation/Archives/chantiers/pile_in_overrun_par_figurine_2026-08-18.md` §6 (fix REJETÉ : la cible est la migration par-figurine, §5).

- **T6-e — `_turn_step_limit` absent sur le chemin single-scenario (BLOQUANT, crash immédiat) —
  ✅ CORRIGÉ (2026-07-19)**
  **Repro** : `train.py --agent CoreAgent --training-config x5_debug --scenario <fichier.json>
  --new --resolution 5` → `ConfigurationError: Required key '_turn_step_limit' is missing from
  mapping` dans `setup_callbacks` ([train.py](../../../ai/train.py)).
  **Cause** (même famille que T6-a/T6-b : migration partielle d'un chemin de train.py) :
  `training_config["_turn_step_limit"]` n'était écrit que par DEUX chemins — la rotation de
  scénarios (`train_with_scenario_rotation`, bloc inline de calcul du budget) et MacroController
  ([train.py](../../../ai/train.py), relevé sur son propre moteur). Le chemin
  **single-scenario** (`--scenario <fichier>` → `create_multi_agent_model` → `setup_callbacks`)
  ne l'écrivait jamais, alors que TROIS lecteurs le `require_key` :
  [train.py](../../../ai/train.py), [train.py](../../../ai/train.py),
  `multi_agent_trainer.py` (⚠️ **fichier SUPPRIMÉ depuis** — commit `748d5591`, « purge de
  `--orchestrate`/`multi_agent_trainer` » ; lien retiré le 2026-07-28, ce 3ᵉ lecteur n'existe plus).
  Crash systématique, quel que soit le scénario.
  **Fix** : le bloc inline de la rotation est extrait en helper
  `resolve_turn_step_limit(scenario_files, training_config, use_bots, log)`
  ([train.py](../../../ai/train.py)) — MÊME formule (`compute_turn_step_limit` sur le
  scénario au max de figurines, probe des sièges p1/p2/random si `use_bots`) — appelé par les
  deux chemins : rotation ([train.py](../../../ai/train.py)) et single-scenario
  ([train.py](../../../ai/train.py), `use_bots` dérivé de « bot » dans le nom du
  scénario, miroir du choix `BotControlledEnv` ~1830). Factorisation volontaire : deux calculs
  dupliqués = le motif exact qui a produit R5 et T6-a. Code mort supprimé au passage dans le
  bloc extrait (`num_phases`/import `GAME_PHASES`, calculé et jamais lu).

- **T6-f — Commit de déploiement `deploy_unit` mono-ancre : `models_cache` JAMAIS écrit
  (BLOQUANT gym, crash DIFFÉRÉ en phase move ; touche AUSSI des chemins PvP) — ✅ FAIT
  (2026-07-19, +10 tests `test_deployment_per_model_commit.py`)**
  ⚠️ Cet en-tête est resté « ❌ À FAIRE » jusqu'au 2026-07-19 alors que le fix était livré et
  testé : il contredisait [§0](index_v11.md#s0) ET le tableau des critères. Corrigé. L'analyse ci-dessous reste
  valable comme historique de la rupture.
  **Rayon (vérifié par lecture, conséquence runtime démontrée côté gym seulement)** : le commit
  fautif est PARTAGÉ — (a) gym via l'action decoder ; (b) auto-déploiement P2 du tutoriel
  ([api_server.py](../../../services/api_server.py)) ; (c) drag mono-socle PvP encore
  actif quand `deployment_type != "active"` (`handleDeployUnit`,
  [useEngineAPI.ts](../../../frontend/src/hooks/useEngineAPI.ts), cf.
  [BoardPvp.tsx](../../../frontend/src/components/BoardPvp.tsx)) et sa route
  sémantique ([w40k_core.py](../../../engine/w40k_core.py)). Tous laissent les
  figurines à `(-1,-1)`.
  **C'est un TROISIÈME bug de déploiement, distinct** de la parité masque/commit T5
  (`_deployment_clearance_filter` — divergence de prédicat, mono-ancre des deux côtés) et du
  logging analyzer (§ « Le déploiement n'était PAS journalisé ») : ici c'est le COMMIT lui-même
  qui est resté pré-V11.
  **Repro** (déterministe, moteur nu, scénario `training_benchmark`, premier index du masque à
  chaque step) : crash au step 7, première action de move —
  `ValueError: execute_squad_move a échoué : squad=1 type=fall_back dest=(214,96) depuis
  (217,154) — incohérence masque/exécution`. Indépendant du terrain (reproduit avec
  `terrain-mc1` ET `terrain-train-01`) et du roster.
  **Root cause (tracée sur l'état)** : après le déploiement gym, `units_cache["1"]` porte bien
  l'ancre `(217,154)` mais les 6 figurines de `models_cache` restent à `(-1,-1)`. La branche
  `deploy_unit` d'`execute_deployment_action`
  ([deployment_handlers.py](../../../engine/phase_handlers/deployment_handlers.py)) commit
  via `set_unit_coordinates` + `update_units_cache_position`
  ([shared_utils.py](../../../engine/phase_handlers/shared_utils.py) — n'écrit que
  `units_cache` + carte d'occupation, jamais `models_cache`). Le chemin PvP `deploy_commit` →
  `_apply_deploy_plan`
  ([deployment_handlers.py](../../../engine/phase_handlers/deployment_handlers.py)), lui,
  écrit chaque figurine via `update_model_position` puis synchronise l'ancre.
  **Mécanisme du crash** : le pool BFS du masque de move part de l'ancre `units_cache` (valide),
  mais `build_rigid_plan` ([shared_utils.py](../../../engine/phase_handlers/shared_utils.py))
  translate depuis `models_cache` : 6 figurines confondues en `(-1,-1)` → plan = 6 figs sur le
  MÊME hex destination, et `validate_move_plan` rejette (budget per-model : distance 215 depuis
  `(-1,-1)` > 60 ; collision intra-plan en second rideau). Le masque avait autorisé la cellule →
  la garde « incohérence masque/exécution » de `_process_squad_action` lève. En vectorisé, les
  8 workers `SubprocVecEnv` meurent (EOFError côté parent).
  **Pourquoi invisible jusqu'ici** : T5 a validé la boucle moteur nu AVANT la migration squad
  par-figurine du move (T6/refonte spatiale) — tant que l'exécution du move raisonnait par
  ancre, des figurines à `(-1,-1)` ne faisaient rien crasher (elles produisaient seulement les
  fausses collisions analyzer, cf. § logging).
  **Fix appliqué (2026-07-19) — le commit produit et exécute un plan PAR-FIGURINE validé, pour
  les TROIS chemins d'un coup** (`deployment_handlers.py` + `action_decoder.py`) :
  1. Nouveau `build_validated_deployment_plan` (deployment_handlers) : `generate_compact_formation`
     autour de l'ancre + `deployment_preview_plan` ; rend le plan (4-uplets, niveau 0) SI toutes
     les figurines sont légales, sinon `None`. Lecture pure et déterministe.
  2. `deploy_unit` commit désormais via `_apply_deploy_plan` — le MÊME écrivain que le flux PvP
     par escouade (`update_model_position` par figurine + sync de l'ancre). Plan illégal =
     refus explicite `deploy_plan_invalid`. Comme les trois chemins du rayon partagent cette
     branche, ils sont corrigés ensemble.
  3. `_select_deployment_hex_for_action` (décodeur) retient la meilleure ancre de la stratégie
     **dont la formation est exécutable** : le `max` est remplacé par un parcours par score
     décroissant qui s'arrête au 1er plan valide ; épuisement = `ValueError` explicite. Sans
     ça, une ancre au bord de zone pouvait scorer 1re et n'admettre aucune formation → deadlock
     masque/commit, exactement la classe de bug corrigée en T5.
  4. Le plan validé par le décodeur est mémoisé (`store_/read_validated_deployment_plan`, tampon
     escouade+ancre+phase+nb déployés) pour que le commit ne le RECALCULE pas. Pure économie —
     le helper étant déterministe (verrouillé par test), la mémo n'est jamais une source de
     vérité divergente ; son absence (chemins PvP sans décodeur) est un état légitime.
  **Résultat mesuré** : déploiement gym complet, `training_benchmark` — 0 figurine à `(-1,-1)`
  (6/6 escouades). Chemin « ancre imposée » (drag PvP / auto-deploy tutoriel) exercé sur les
  16 104 hexes de la zone : 6/6 escouades posées, refus répartis en 1815
  `deploy_footprint_out_of_bounds` + 263 `outside_zone` + 31 `occupied` (tous de la validation
  mono-ancre PRÉEXISTANTE) et seulement **2** `deploy_plan_invalid` — le fix ne restreint
  quasiment pas les placements.
  **Coût, et son optimisation** (phase de déploiement complète, board x5, 6 escouades) :
  | étape | temps | note |
  |---|---|---|
  | avant le fix | 1,03 s | ne plaçait AUCUNE figurine — coût non représentatif |
  | fix naïf | 2,31 s | `generate_compact_formation` payé 2× (décodeur + commit) |
  | + mémoisation (point 4) | 1,70 s | supprime le doublon |
  | + empreinte pré-calculée | **1,37 s** | voir ci-dessous |
  5. **Empreinte par translation d'offsets dans `generate_compact_formation`.** cProfile :
     `_legal_socle` = 92 % du coût de la fonction, dont 67 % à reconstruire l'empreinte du socle
     via `compute_occupied_hexes`/`_footprint_round` — **2 590 reconstructions et 341 660 appels
     à `_hex_center` pour UNE formation**, parce que la spirale BFS recalcule la forme à chaque
     case. Remplacé par `precompute_footprint_offsets` (deux jeux d'offsets, parité de colonne),
     le helper prévu exactement pour ça (docstring : « expensive when called per-BFS-step ») et
     déjà utilisé par `_get_valid_deployment_hexes`. **50 ms → 17,4 ms par formation (×2,9).**
     Équivalence stricte vérifiée par test aux deux parités — code partagé avec le déploiement
     PvP par escouade, une divergence déplacerait des socles à l'écran.
  **Perf soldée le 2026-08-23** : `_deploy_pool_set` est mémoïsé par joueur dans `game_state`
  (−26 % par formation, 10,79 → 7,94 ms) et l'anneau bloquant est devenu incrémental. L'érosion
  morphologique de la spirale a été MESURÉE non rentable (−6 % net dans les deux régimes) :
  l'hypothèse « la spirale s'arrête en quelques cases » était fausse, et le vrai goulot est la
  marge inter-figurines, qui est dynamique et non érodable. Mesures et pièges :
  [`Documentation/Archives/chantiers/perf_generate_compact_formation.md`](../../Archives/chantiers/perf_generate_compact_formation.md).
  **Tests (+10)** : `tests/unit/engine/test_deployment_per_model_commit.py` — placement de toutes
  les figurines, ancre = figurine d'index minimal (l'invariant dont `build_rigid_plan` dépend),
  légalité du plan committé, déterminisme + lecture pure du helper, invalidation de la mémo sur
  tampon périmé, équivalence de l'empreinte pré-calculée aux deux parités. Les 8 premiers sont
  rouges sur l'ancien code. Suite `tests/unit` : mêmes échecs préexistants qu'avant le fix
  (baseline vérifiée par `git stash`), aucune régression.
  **Dette assumée** : `deploy_unit` porte désormais DEUX modèles de validation — la mono-ancre
  héritée de T5 (empreinte du socle de l'unité ⊆ pool, miroir du masque) et la par-figurine.
  La première n'a plus de sens géométrique strict une fois le placement fait par figurine ; elle
  ne survit que parce que le masque T5 s'y aligne. **Planifié en T7** (section 5), déclencheur
  « le training tourne » — le fondement règles y est établi par lecture des PDF (la mise en place
  est PAR FIGURINE, aucun socle à l'ancre dans les règles).
  ⚠️ **Écarté après analyse — deux fausses bonnes idées** :
  - *Filtrer le pool entier par `deployment_build_squad_destinations_pool`*
    ([deployment_handlers.py](../../../engine/phase_handlers/deployment_handlers.py)) :
    INSUFFISANT (ne teste que zone-fit du bloc rigide — pas les murs par-figurine, pas le
    chevauchement d'unités déployées, pas §13.06, tous exigés par `deployment_preview_plan`) et
    SURDIMENSIONNÉ (~16 000 hexes validés pour 5 slots-stratégies utilisés).
  - *Valider les ancres DANS le masque* : impossible sans le réécrire — le masque n'active que
    5 slots (`mask[4+i]`) et ne connaît PAS les ancres, qui sont calculées au décodage par
    `_select_deployment_hex_for_action`. C'est donc le décodeur qui doit filtrer (point 3).
  ⚠️ **Comportement non évident vérifié et verrouillé par test** : dans
  `generate_compact_formation`, l'ancre ORIENTE le placement mais ne le CONTRAINT pas (sa
  spirale retient la 1re case légale) — une ancre hors zone place l'escouade dans la zone la
  plus proche au lieu d'échouer. Le refus d'une ancre hors zone reste donc porté par la
  validation mono-ancre de `deploy_unit` (`deploy_footprint_outside_zone`), à ne pas retirer.
  ⚠️ **Chemin tutoriel PvP** : sans objet — le mode tutoriel a été supprimé le 2026-07-28
  (`config/tutorial/` compris). Le chemin a été validé par son équivalent fonctionnel
  (commit à ancre imposée, ci-dessus).

- **T6-g — Le pool BFS du move valide l'ANCRE, pas le BLOC translaté — ✅ FAIT (2026-07-19)**
  **Réalisé** : `erode_move_pool_by_squad_block` (shared_utils), appelée par
  `build_squad_move_cell_map` sur les `costs` du BFS, AVANT `project_pool_to_grid` — donc la
  grille égocentrique, le masque et le décodage lisent tous le pool érodé (la source unique
  reste unique). Le bloc est réduit à ses offsets CUBE relatifs à l'ancre (invariants depuis
  T6-h), **groupés par NIVEAU** (une figurine ne collisionne qu'avec les figs d'un autre squad
  au même étage — miroir exact de `validate_move_plan`), et les cellules interdites sont
  pré-agrégées par niveau en un seul set (murs ∪ occupation ∪ ER ennemie) → un test
  d'appartenance par figurine et par candidate, pas d'appel à `validate_move_plan` dans la
  boucle. Invariants non érodés car démontrés invariants par translation : budget per-model et
  cohésion (cf. [§0](index_v11.md#s0)). Aucune règle de jeu modifiée : l'érosion ne fait que RETIRER du masque des
  destinations que l'exécution refusait déjà.
  **Validation** : +6 tests dédiés (mur/autre escouade/ER sous une SŒUR alors que l'ANCRE est
  légale, débordement de plateau, non-sur-filtrage, court-circuit mono-figurine) ; run x5_debug
  8 workers 10/10 épisodes et run mono-env x1_debug, **zéro** « incohérence masque/exécution ».
  ⚠️ **Ce « zéro » ne vaut que pour les 10 épisodes mesurés** : une AUTRE cause de la même
  classe a tué un run de 250 épisodes le 2026-07-20 — cf. **[§0.11](index_v11.md)** (collision intra-plan
  aveugle au niveau). L'érosion de T6-g reste correcte ; c'était le prédicat de collision
  qu'elle ne teste pas — à raison — qui était faux.
  Historique de la rupture ci-dessous.
  **Repro** (moteur nu, `training_benchmark`, premier index du masque) : dès que les figurines
  sont réellement placées, le crash T6-f se déplace au squad suivant —
  `ValueError: execute_squad_move a échoué : squad=3 type=normal dest=(195,163) depuis
  (197,168) — incohérence masque/exécution`.
  **Root cause (tracée entrée par entrée sur le plan rigide)** : `build_squad_move_cell_map`
  ([shared_utils.py](../../../engine/phase_handlers/shared_utils.py)) construit le pool
  via `movement_build_valid_destinations_pool`, qui raisonne sur l'**ancre** de l'escouade, puis
  le projette sur la grille égocentrique. Mais l'exécution passe par `build_rigid_plan`, qui
  **translate TOUTES les figurines** du même vecteur — sans qu'aucune contrainte n'ait été
  testée sur elles. Sur le plan rejeté : 3 figurines (`3#4`, `3#5`, `3#6`) atterrissent sur une
  autre escouade et 1 (`3#17`) sur un mur, alors que l'ancre `3#0` est parfaitement légale.
  `validate_move_plan` rejette donc une destination que le masque avait offerte.
  **Ce n'est PAS une régression de T6-f** : le mismatch est structurel (pool d'ancre vs
  exécution de bloc) et préexistait ; il était simplement masqué par T6-f, qui faisait échouer
  le move plus tôt, pour une autre raison.
  **Modèle retenu (décision utilisateur 2026-07-19) : érosion morphologique** — éroder la grille
  des cellules acceptables par l'empreinte COMBINÉE de l'escouade, puis lire le résultat à
  l'ancre. Exact (les autres unités sont fixes pendant le move de l'escouade), vectorisable, et
  le code a déjà ce précédent exact dans `_get_valid_deployment_hexes` (érosion par empreinte,
  DEUX jeux d'offsets selon la parité de colonne). Écarté : `validate_move_plan` en post-filtre
  des candidates — exact aussi mais Python pur, |pool| × |figurines| par step (~2800 × 20).
  ⚠️ **Ordre imposé par T6-h** : l'érosion suppose des offsets de bloc INVARIANTS par
  translation. C'est faux aujourd'hui (cf. T6-h) — corriger la translation AVANT d'éroder,
  sinon l'érosion valide une forme que l'exécution ne reproduit pas.
  **À ne pas oublier dans le filtre** : bornes, murs, occupation des autres escouades PAR NIVEAU
  et `forbid_enemy_er` (toutes des contraintes de cellule, donc érodables). La cohésion et le
  budget per-model deviennent invariants une fois T6-h corrigé (translation réellement rigide),
  mais `validate_move_plan` mesure le budget par `calculate_hex_distance` depuis chaque origine :
  le vérifier plutôt que le supposer.

- **T6-h — `build_rigid_plan` : la translation « rigide » DÉFORME le bloc (bug de parité hex) —
  ✅ FAIT (2026-07-19)**
  **Réalisé** : translation en coords CUBE (`offset_to_cube` / `cube_to_offset`) dans
  `build_rigid_plan`. **L'audit « autres consommateurs de translation de bloc » demandé par le
  plan a trouvé DEUX autres sites portant le même bug**, tous deux alignés :
  - `translate_squad_to_destination` (shared_utils) — **le plus grave** : c'est l'ÉCRIVAIN du
    commit, partagé par move / charge / fight / pile-in / consolidation. Corriger
    `build_rigid_plan` seul aurait fait committer une formation DIFFÉRENTE de celle que
    `validate_move_plan` venait d'accepter (plan validé en cube, commit appliqué en offset) —
    soit exactement la classe de bug « validé ≠ exécuté » que T6-g élimine ;
  - `preview_hidden_models_after_move` (shooting_handlers) — simulation read-only du statut
    « caché » (13.09) après move, dont la docstring se réclame explicitement du miroir de
    `translate_squad_to_destination` : à `dx` impair, le preview affichait un bloc déformé,
    donc un statut caché faux (impact PvP direct, pas seulement gym).
  **Validation** : +10 tests paramétrés sur `dx` pair ET impair (distances internes préservées,
  ancre exactement sur la destination) — **rouges sur le code d'avant** aux seules parités
  impaires, verts après. Historique de la rupture ci-dessous.
  **Mesure** (2 figurines voisines, translation du bloc en offset puis distance interne
  recalculée par `calculate_hex_distance`) :
  `dx` pair → écart 0 (forme préservée) ; **`dx` impair → écart 1** : deux figurines à distance
  2 se retrouvent à distance 1.
  **Cause** : `build_rigid_plan`
  ([shared_utils.py](../../../engine/phase_handlers/shared_utils.py)) applique
  `new_col = col + dx, new_row = row + dy` en coordonnées OFFSET. En grille hexagonale offset,
  une translation à `dx` impair change la parité de colonne de chaque figurine et n'est donc PAS
  une translation hexagonale — la formation se déforme.
  **Le projet connaît déjà ce piège et l'évite ailleurs** :
  `deployment_build_squad_destinations_pool`
  ([deployment_handlers.py](../../../engine/phase_handlers/deployment_handlers.py)) passe
  explicitement par les coords CUBE, docstring « La translation rigide passe par les coords cube
  (pas de bug de parité) ». `build_rigid_plan` n'a pas reçu ce traitement.
  **Conséquences** : cohésion et collisions intra-plan faussées (deux figurines peuvent se
  télescoper alors que le bloc d'origine était valide), distances per-model non uniformes, et
  toute optimisation supposant des offsets constants (dont l'érosion de T6-g) invalide.
  **Fix** : translater en cube (`offset_to_cube` / `cube_to_offset`), miroir du helper de
  déploiement. Vérifier au passage les autres consommateurs de translation de bloc.
  ⚠️ **Distinct de T6-g** : le crash T6-g mesuré avait `dx = -2` (pair), donc sans déformation —
  les deux bugs sont indépendants et cumulatifs.

**T6.2 — métriques TensorBoard : RÉSOLU, la mémoire projet était périmée.** Inspection directe
des `events.out.tfevents.*` (EventAccumulator) sur training neuf : `00_critical/` porte bien les
métriques PPO — `f_loss_mean`, `g_explained_variance`, `h_clip_fraction`, `i_approx_kl`,
`j_entropy_loss`, `m_immediate_reward_ratio_mean`, **56 points chacune** ; `training_critical/` expose ses
6 tags. Le fix `_dump_with_capture` du 2026-05-22 tient. Nuance non diagnostiquée (sans impact) :
`train/*` et `training_critical/*` n'ont qu'1 point là où `00_critical/*` en a 56 — répartition
entre les deux fichiers d'events (`CoreAgent/` et `x1_debug_CoreAgent_1/`).

**Run T6.1 — « run court complet sans erreur » : DÉMONTRÉ sur les deux chemins.**
- **n_envs=48** : **467/500 épisodes, zéro exception** (`win_rate_overall = 0.296` à l'ép. 467),
  coupé par le `timeout 2400` de l'opérateur — pas par une erreur.
- **mono-env (`--step`, après fixes T6-b)** : **475/500 épisodes, zéro exception**, step.log de
  12 561 lignes, coupé par le `timeout 5400` de l'opérateur.
x1_debug (500 ép.) demande > 40 min à n_envs=48 et > 90 min en mono-env — dimensionner le timeout
en conséquence pour un run réellement complet.

**T6.3 — baseline bots : NON DÉMONTRÉE (données insuffisantes, pas une régression).**
Mesuré sur le run de 467 épisodes (adversaire = GreedyBot randomness=0.15 via BotControlledEnv) :
- `win_rate_100ep` (glissant) ~0.33 au milieu → **0.296** à la fin ; `win_rate_overall` plat
  autour de **0.30** (0.270 → 0.320 → 0.307 → 0.305 → 0.296 par tranches de 100).
- `episode_reward` (moyenne 100 premiers vs 100 derniers) : **-12.53 → -8.33** (progression nette).
Lecture honnête : le reward progresse, le win-rate stagne à ~30 % (l'agent ne bat PAS GreedyBot).
**Mais 467 épisodes sur un budget nominal de 50 000 (`total_episodes_normal` de x1_debug) est du
bruit** — ni preuve de succès ni preuve d'échec. Le critère « win-rate en progression / stabilité
multi-scénarios » exige la phase `x1` réelle + `bot_evaluation` sur holdout (vs RandomBot), pas
`x1_debug` (500 ép.). ⚠️ Ne pas conclure sur ces chiffres.

### ✅ T6-c — RÉSOLU (2026-07-16) : le StepLogger n'avait jamais été migré vers le pipeline squad

**Décision utilisateur : migrer (option a).** Fait. `ai/analyzer.py` tourne désormais de bout en
bout sur un step.log produit par le pipeline squad.

**Root cause réelle — pas « le step logger n'a pas été câblé », mais un CONTRAT MOTEUR VIOLÉ.**
`end_activation(game_state, unit, arg1, ...)` (generic_handlers ~70-101) définit :
`arg1="ACTION"` → « *Log the action (action already logged by handlers)* » ;
`arg1="WAIT"` → `end_activation` émet lui-même l'action_log ; `arg1="NO"` → rien.
Or `_process_squad_action` appelait `end_activation(..., ACTION, ...)` après un move et une charge
réussis — donc en PROMETTANT que le handler avait journalisé — alors que `execute_squad_move` et
`charge_build_valid_plan` n'émettaient **aucun** `append_action_log` (contrairement au chemin
legacy par-figurine, movement_handlers ~3701/4107, charge_handlers ~5597/5877).
**`game_state["action_logs"]` était donc incomplet sur le chemin squad** ; le step.log vide n'en
était qu'un symptôme.

**Solution — réparer le contrat, pas dupliquer 17 sites de journalisation** :
1. **Émission des action_logs manquants** dans `_process_squad_action` (miroir des payloads
   legacy) : `move` (avec `move_type` portant normal/advance/fall_back), `charge`, `charge_fail`,
   **`deploy_unit`** (cf. ci-dessous). `shoot`/`combat`/`hazard`/`wait` en émettaient déjà.
2. **Un point d'accroche UNIQUE** : `_flush_squad_action_logs_to_step_logger` (w40k_core), appelé
   depuis `step()` après le dispatch. Draine `action_logs[curseur:]` → `log_action`, via une table
   `_STEP_LOG_TYPE_MAP` (type moteur → action_type du formateur) et `_build_step_log_details`
   (camelCase moteur → snake_case formateur). No-op complet sans `--step`.
3. **Émission PAR JET** pour `shoot`/`combat` : le moteur agrège les jets d'un groupe (arme,
   cible) dans `shootDetails`, le formateur travaille par attaque → une ligne par jet, via
   `_SHOT_RECORD_FIELD_MAP` (`attackRoll`→`hit_roll`, `strengthRoll`→`wound_roll`,
   `saveSuccess`→`save_result`…). Les 11 champs sont exigés même sur un MISS (présence de la clé) :
   `None` est correct, le formateur ne rend `Wound` que si `hit_result == "HIT"`.
4. **État fight capturé AVANT l'action** (`_pre_action_fight_state`) : le formateur `combat`
   exige `fight_subphase` + les 3 pools d'activation (contrat replay), et l'action les mute.

⚠️ **Rayon PvP : NUL, vérifié.** `execute_squad_move` n'a qu'UN appelant (`_process_squad_action`)
et `_process_squad_action` n'est appelé que depuis `step()`/`_build_observation` = gym,
**plus `execute_ai_turn` depuis le 2026-07-28** (le bot PvE a été migré sur le contrat squad :
même observation, même masque, même décodeur que l'entraînement — cf. `AI_OBSERVATION_Legacy.md`).
Le PvP humain (`services/api_server.py`) passe toujours par `execute_semantic_action` →
`_process_semantic_action`, inchangé.

**Le déploiement n'était PAS journalisé non plus** (`deployment_handlers` : grep
`append_action_log` = 0). Conséquence mesurée et non évidente : `log_episode_start` écrit les
unités non déployées en `(-1,-1)`, et sans log de déploiement l'analyzer n'apprenait JAMAIS leur
position réelle → **49 fausses « collisions »** (contrôle 2.2). Émettre `deploy_unit` les a
résolues d'un coup (49 → 0).

**Bug de règle trouvé DANS l'analyzer** (faux positifs, pas un bug moteur) :
`_track_action_phase_accuracy` (analyzer.py ~835) attendait `"advance": "SHOOT"`. **Faux** :
PDF projet « 09 Movement phase.pdf », règle **09.02 MOVE UNITS > Select Move Type** liste
l'*Advance move* parmi les types de mouvement de la **phase de Mouvement** (avec Normal move,
Fall-back move, Remain stationary). Le moteur le résout bien en phase MOVE. Corrigé en
`"advance": "MOVE"` → **105 faux positifs supprimés**.

**Résultat sur le VRAI `train.py --agent CoreAgent --scenario bot --new --training-config
x1_debug --step`** (56 épisodes, **3452 lignes d'action**, **0 erreur avalée**) — `ai/analyzer.py`
tourne de bout en bout et rendait **14 erreurs** ; après le traitement du faux positif LoS
(2026-07-16) il n'en reste **2**, le seul ❌ étant l'artefact 2.6 ci-dessous :
- ✅ 1.1 move : 0 ; ✅ 1.3 charge : 0 ; ✅ 1.4 fight : 0 ; ✅ 1.5 wrong phase : 0 ;
  ✅ 1.6 double-activation : 0 ; ✅ 2.1 dead units : 0 ; ✅ **2.2 positions : 0** ;
  ✅ 2.3 DMG : 0 ; ✅ 2.5 episode ending : 0 ; ✅ 2.7 core issue : 0.
- ✅ **1.2 erreurs en phase de shooting : 0** — **TRANCHÉ ET TRAITÉ le 2026-07-16**, était 12
  (`shoot_through_wall = 6` + `shoot_invalid.no_los = 6` = les MÊMES 6 tirs, incrémentés dans la
  MÊME branche, shoot_handler.py ~165). **Verdict : faux positifs de l'analyzer, aucun bug
  moteur, backend non modifié.** Détail complet, preuve et options rejetées :
  `Documentation/Archives/chantiers/analyzer_los_ancre_vs_perfig.md`.
  **Cause structurelle confirmée — le CONTRÔLEUR est périmé, pas le moteur** (et il n'y a
  AUCUNE divergence training/PvP : le moteur est unique et pilote les deux) :
  - L'analyzer n'a PAS sa propre LoS — il appelle bien `engine.hex_utils.compute_los_state`
    (analyzer.py ~602, docstring : « same algorithm as the game engine »). **Mais il l'appelle
    ANCRE-À-ANCRE** : `has_line_of_sight(shooter_col, shooter_row, target_col, target_row,
    wall_hexes)` — un point contre un point.
  - Le moteur, lui, fait `_attacker_model_can_reach_squad` (shared_utils ~4243) : LoS
    **PER-FIGURINE**, origine = **empreinte COMPLÈTE du socle tireur** (« pas son seul centre »),
    distance bord-à-bord, via `_compute_visibility_with_obscuring` (murs denses + obscurcissant,
    13.10). **Son propre commentaire décrit exactement ce faux positif** : « une grosse base dont
    le centre est masqué par un terrain (mais dont un bord voit la cible) était grisée à tort ».
  - → L'analyzer refait le test centre-à-centre que le moteur a DÉLIBÉRÉMENT abandonné. Même
    dette que R5 / le step logger / les objectifs de l'analyzer : outil resté sur le modèle
    pré-squad « une unité = un point ».
  - Second suspect : `except Exception: return False` (analyzer.py ~630) — **écarté par mesure**
    (aucune exception levée : `compute_los_state` brut rend le même `False`). Supprimé quand même
    (CLAUDE.md). Troisième suspect « murs incomplets » écarté aussi : ligne `Walls:` complète.
  - **Confirmé sur un tir précis** (E7 T3 P1 `Unit 4(215,155) SHOT Unit 104(116,66)`) : l'ancre
    rend `can_see=False`, mais **3 des 19 cellules** de l'empreinte du socle (`round/6`) voient la
    cible. Règle 06.01 (PDF lu) : « from **any part** of that model to **any part** of the model
    being observed » → l'ancre-à-ancre est plus restrictif que la règle.
  - **Correction (option c)** : le contrôle est SUPPRIMÉ de l'analyzer et la vérification
    DÉPLACÉE dans `tests/unit/engine/test_shoot_los_perfig_parity.py`, où `game_state` existe.
    Le réparer sur place était impossible : les primitives moteur exigent `game_state`
    (empreintes, obscurcissant 13.10, LoS 3D) que step.log ne porte pas ; et logger le verdict du
    moteur serait circulaire (le tir est déjà gaté par `_attacker_model_can_reach_squad`).
  ⚠️ **La journalisation n'est fidèle que pour les JETS** (`Hit 6(3+) - Wound 5(5+) - Save 1(4+) -
  Dmg:2HP` ; un MISS ne rend que `Hit 2(3+)`). **Ses COORDONNÉES sont fausses** :
  `_emit_squad_shoot_log` (shared_utils ~5758) loggue l'ancre d'ESCOUADE, pas la figurine qui
  tire — dette V11 « une unité = un point » non traitée, chantier séparé.
- ❌ 2.6 « Sample missing (2/5) : charge, fight » = artefact du run (agent frais : ne charge ni
  ne combat jamais sur 56 épisodes), PAS un défaut.

**C'est la valeur du chantier T6-c** : l'outil de validation du projet fonctionne enfin, et il a
IMMÉDIATEMENT trouvé une divergence LoS analyzer↔moteur qu'aucun test unitaire ne voyait.

**Résultat sur un step.log de moteur nu (3 épisodes, actions aléatoires)** — `157 erreurs → 52 → 3` :
- ✅ 1.1/1.2/1.3/1.4 erreurs par phase : 0 ; ✅ 1.5 wrong phase : **0** (était 105) ;
  ✅ 1.6 double-activation : 0 ; ✅ 2.1 dead units : 0 ; ✅ 2.2 positions incohérentes : **0**
  (était 49) ; ✅ 2.3 DMG issues : 0 ; ✅ 2.5 episode ending : 0 ; ✅ 2.7 core issue : 0.
- ❌ 2.6 « Sample missing (3/5) : shoot, charge, fight » = **artefact du run** (actions aléatoires
  non dirigées : ni tir ni charge ni combat), PAS un défaut. Le scénario de mêlée garantie produit
  bien `FOUGHT`/`FAILED CHARGE` (vérifié : 40 lignes `FOUGHT` avec détail par jet
  « Hit 3(3+) - Wound 5(2+) - Save 2(7+) - Dmg:1HP »), et zéro erreur avalée.

⚠️ **Piège vérifié** : `StepLogger.log_action` et `log_episode_start` AVALENT toute exception
(`except Exception: print("⚠️ ... logging error")`, step_logger.py ~254). Un champ manquant
produit une ligne SILENCIEUSEMENT absente, pas un crash. **Contrôler `grep -c "logging error"`
après tout changement de mapping** — c'est ainsi qu'ont été trouvés les manques `hit_roll` puis
`deploy … position data`.

Plan d'origine (résolu ci-dessus) :

**Fait vérifié (statique)** : `_process_squad_action` (w40k_core.py, def ~4750, plage ~4750-5146)
— le chemin VIF du pipeline squad en gym — contient **ZÉRO appel à `step_logger.log_action`**
(grep sur la plage = 0). Son docstring l'annonce : « Dispatch sémantique squad vers helpers squad.
**Remplace `_process_semantic_action`** ». Or les **17** sites `log_action` vivent dans
`_process_semantic_action` (def ~2725) et ses handlers, atteignables seulement via
`execute_semantic_action` (~2090) et `execute_ai_turn` (~2114) = chemins PvE/legacy.

> **Clôture 2026-07-29** : ce diagnostic était juste, et le constat a été poussé à son terme. Ces
> 17 sites n'étaient pas seulement « legacy » : ils étaient **inatteignables**, aucun appelant de
> `execute_semantic_action` n'assignant de StepLogger. Le bloc a été **supprimé** (pierre tombale
> dans `_process_semantic_action`) ; `_flush_squad_action_logs_to_step_logger` est désormais le
> seul chemin de journalisation. Détail : [`Documentation/Archives/chantiers/campagne_typage_et_replis_2026-07-29.md`](../../Archives/chantiers/campagne_typage_et_replis_2026-07-29.md) §3.1.

**Preuve empirique (run mono-env réel, 475 épisodes, après les fixes T6-b)** :
- `Steps=0` sur **474/475** épisodes (`episode_step_count` n'est jamais incrémenté) ;
- **0 ligne** correspondant à `Unit N (MOVED|SHOT|CHARGED|FOUGHT|WAITED)` sur 12 561 lignes ;
- ~26 lignes/épisode = les seuls en-têtes (`Scenario`, `Rosters`, `Walls`, `Objectives`, `Rules`,
  `Board`) + `EPISODE END` + `OBJECTIVE CONTROL`.

⚠️ **Nuance vérifiée (à ne pas sur-simplifier)** : `log_action` n'est pas TOTALEMENT inatteignable
depuis le gym — **3 épisodes sur 475** portent `Actions=9|9|18`. Ce sont exclusivement des
`rule_choice` (« Unit 105 chose [AGGRESSION IMPERATIVE] »), émis par le site w40k_core ~2416-2425
dont le commentaire dit explicitement « select_rule_choice **bypasses normal step logger flow** ».
C'est donc le seul `log_action` atteignable — précisément parce qu'il court-circuite le flux
normal — et il n'incrémente pas `step_count`. **Toutes les actions de JEU (move/shoot/charge/
fight/wait), celles à `step_increment=True` dont l'analyzer a besoin, ne sont jamais journalisées.**

**Conséquence** : `ai/analyzer.py` échoue en `Missing objective control snapshot at episode end`
(analyzer_core.py ~250) — il construit ses snapshots de contrôle d'objectif à chaque action
`step_inc` (~861-907), et il n'y en a aucune. Aucun réglage de l'analyzer ne peut compenser :
**la matière première n'est pas produite**.

**Même famille que R5 et `game_replay_logger`** (condamné en T2 pour exactement ce motif : code
resté sur l'architecture pré-squad). La migration RL de fin mai a laissé derrière elle TOUTE la
chaîne d'observabilité, pas seulement les wrappers.

**À statuer (utilisateur)** : (a) migrer `log_action` vers `_process_squad_action` (chemin partagé
PvP/gym → impacte aussi la journalisation PvP, à cadrer) ; (b) condamner explicitement `--step`
sur le pipeline squad, comme `game_replay_logger.log_action` (NotImplementedError), et retirer
« analyzer + replay » du critère T6 ; (c) laisser en l'état. **Interdit : laisser `--step`
annoncer « Step logging enabled » en ne produisant que des en-têtes.**
Cadrage PvP si (a) : les 17 sites legacy sont tous gardés par `if self.step_logger`, et le
logger n'est branché QUE par train.py → instrumenter `_process_squad_action` avec la même
garde est neutre PvP par construction. Granularité : l'action squad (move dir, shoot slot,
charge, fight, wait) — ce que l'analyzer consomme.

**Décisions annexes actées (2026-07-16)** :
1. **Modèles de validation** : les runs de validation/baseline écrivent leurs artefacts sous
   `ai/models/_validation/<run_id>/` — JAMAIS dans `ai/models/<agent_key>/` (zips protégés,
   CLAUDE.md). Règle permanente : plus aucun arbitrage ponctuel `--new` vs zips à chaque run.
2. **Raccrochés au chantier (a)** (même fichier, même passe) : le 3e site `--step` encore non
   gardé dans train.py (les 3 sites impriment le même message — ajouter au passage un
   identifiant de site dans le log), et la ligne `OBJECTIVE CONTROL:` de step.log au format
   `Obj<id_string>` que personne ne lit (l'aligner sur le format attendu `Obj(\d+)` du parser,
   ou la supprimer — pas de statu quo).

### Corrections T6 faites en chemin vers l'analyzer (toutes vérifiées)

- **Parser d'armes — bug SILENCIEUX sur les apostrophes** (`engine/weapons/parser.py`, motif
  `["\']([^"\']+)["\']`) : ouvrait sur `"` ou `'`, capturait tout sauf CES DEUX caractères, fermait
  sur l'un ou l'autre. Une apostrophe DANS une chaîne à guillemets doubles cassait la lecture —
  or les noms Orks en sont pleins. `display_name: "Dok's Tools"` → capturait **`"Dok"`** (tronqué,
  SANS erreur) ; `"'eadbanger'"`, `"'urty Syringe"`, `"'Waaagh! Staff"` → **aucun match**, la clé
  `display_name` n'était jamais posée et l'absence explosait ailleurs
  (`require_key(weapon, "display_name")`, analyzer_config.py). **Impacte aussi le PvP.**
  → constante `_TS_QUOTED_STRING = r'(["\'])((?:(?!\1).)*)\1'` (backréférence : fermeture sur le
  MÊME guillemet), appliquée à `display_name`, `COMBI_WEAPON` et `WEAPON_RULES`. Strictement
  identique pour tout nom sans apostrophe. Résultat : registre à **176 unités, 0 erreur de
  parsing** (contre 107 erreurs).
- **Donnée corrigée en conséquence** : `wolf_guard_weapon` déclarait `WEAPON_RULES: [""]`
  (spaceMarine/armory.ts) — une chaîne VIDE que l'ancien motif (`+`, 1 car. min.) avalait
  silencieusement. Le motif corrigé la lit fidèlement → règle vide rejetée. `[""]` → `[]` :
  comportement inchangé (l'ancien parser produisait déjà `[]`), la donnée dit enfin ce que le code
  comprenait. Occurrence unique dans tout le projet.
- **`_resolve_scenario_path` (analyzer.py) résolvait vers l'ARCHIVE** : T4 a déposé la banque
  pré-V11 sous `scenarios/_archive_pre_v11/` — donc DANS l'arbre parcouru par `os.walk` →
  `ValueError: Ambiguous scenario path for 'scenario_training_bot-29'` (l'archivé garde ses clés
  legacy, sa signature d'objectifs diffère du migré homonyme). → la marche élague les dossiers
  `_archive*`. Aligné sur la convention du projet : `get_scenario_list_for_phase`
  (training_utils.py) travaille sur une liste blanche explicite (training/, holdout_regular/,
  holdout_hard/) et n'a jamais eu ce problème.
- **`_get_objective_name_to_id_map` (analyzer.py) était resté sur le contrat LEGACY** : lisait
  `objectives` inline / `objectives_ref` → `config/board/<board>/objectives/` (dossier supprimé).
  T3 avait migré train.py et bot_evaluation.py, **pas analyzer.py**. → migrée vers la source
  unique terrain (areas `"objective": true`, miroir de `resolved_scenario_objectives` de
  game_state.py), via un nouveau `_resolve_terrain_path_for_scenario` (miroir du resolver
  `board_ref` de T4). Nuance : les ids terrain sont des STRINGS (`rect_b_nw_OK`) alors que
  l'analyzer indexe par int → id positionnel (1..N, ordre du fichier terrain = stable) ; seul le
  NOM sert d'appariement, et c'est bien le `name` de l'area que le StepLogger écrit.
  ⚠️ **Reste incohérent** (non corrigé, car sous le bloqueur T6-c) : la ligne `OBJECTIVE CONTROL:`
  de FIN D'ÉPISODE écrit `Obj<id_string>` (`Objrect_b_nw_OK`) alors que le parser attend `Obj(\d+)`
  (analyzer_core.py ~112) — **trois formats coexistent** (nom / `Obj`+string / `Obj`+int).
  ✅ **Résolu le 2026-07-29** : l'analyzer ne construit plus aucun id d'objectif. Il lit les
  instantanés `T{tour} OBJECTIVE CONTROL: VP1=… ZONES=…` du moteur (indexés par **nom de zone**,
  la même clé que la ligne `Objectives:`) et `_get_objective_name_to_id_map` est supprimée avec
  tout l'appariement positionnel. Les trois formats ne coexistent plus : seul subsiste le
  récapitulatif de fin d'épisode `Obj<id_string>`, que plus personne ne parse.
  Détail → `Replay.md` §4.D.

**✅ Bloqueur résolu (historique) — `ai/analyzer.py` ne démarrait pas** :
`ConfigurationError: Required key 'RNG' is missing` (`analyzer_config.py`) —
`load_analyzer_config` itère TOUT `unit_registry.units`, donc 4 armes de TIR de l'armory Ork sans
clé `RNG` bloquaient l'analyzer QUEL QUE SOIT le scénario, même sans Ork. Renseignées par
l'utilisateur (`RNG: 24`) le 2026-07-16 : `kombi_rokkit`, `kombi_shoota`, `rokkit_launcha`,
`rokkit_launcha_heavy`. A permis de découvrir les blocages suivants (parser d'apostrophes,
archive T4, contrat objectifs legacy) puis le vrai mur structurel T6-c.

Plan d'origine :
1. `python3 ai/train.py --agent CoreAgent --scenario bot --new --training-config x1_debug --step`
   → run court complet sans erreur ; puis `ai/analyzer.py` sur les résultats + replay.
2. Vérifier les métriques TensorBoard (cf. mémoire projet : métriques PPO manquantes dans
   00_critical — diagnostiquer si toujours le cas).
3. Baseline bots : l'agent frais doit apprendre à battre RandomBot/GreedyBot sur quelques
   scénarios avant tout tuning (critère de succès : stabilité multi-scénarios, pas un pic).
4. Hygiène (ne bloque pas) : corriger la `justification` (31→41) de la config ; mettre à jour
   AI_OBSERVATION.md/AI_TRAINING.md (pipeline squad 108) ; statuer sur `ai/target_selector.py`
   (mort → suppression à valider utilisateur) ; marquer les configs snapshot obs 355 comme
   archives.

**Hygiène T6.4 — état réalisé (2026-07-16)** :
- ✅ `justification` corrigée dans les **5 phases** : `action_space_size=41 (26 micro [6 move +
  6 advance + 6 fall back + 1 wait + 5 shoot + 1 charge + 1 fight] + 15 macro)`. Décompte vérifié
  contre macro_intents.py.
- ✅ **AI_OBSERVATION.md / AI_TRAINING.md** : bandeau de tête « ne décrit PAS le pipeline actif »
  + table de correspondance (obs 108 / action 41, layout squad, routage `_build_observation` par
  `obs_size`). Les corps de doc (355/357) sont conservés : le pipeline mono-fig reste atteignable
  via `obs_size=357`. `obs_size: 355` de l'exemple de config AI_TRAINING.md corrigé en 108.
- ✅ **Snapshots obs 355 marqués archives** : clé `_ARCHIVE` en tête de
  `BEST_CoreAgent_training_config.json`, `CoreAgent_training_config_BEST_X1.json`,
  `CoreAgent_training_config_save_avant_X10.json`. Sûr : aucun code ne les charge
  (`load_agent_training_config` résout `<AGENT>_training_config.json`) — vérifié par grep.
  Contenu strictement préservé (comparaison JSON parsée vs `git show HEAD:` = identique).
- ✅ **Réserve T2 purgée** : `multi_agent_trainer.py` ~996-1040 — monkeypatch
  `controller.execute_gym_action` portant le dernier layout à 8 actions (`action // 8`,
  `action % 8`). Code mort ET cassé : `W40KEngine` n'a aucun attribut `controller` (grep vide) et
  le patch appelait 6 méthodes inexistantes (`_get_gym_eligible_units`,
  `_convert_gym_action_to_mirror`, `_log_gym_action`…). Supprimé.
- ✅ **Réserve T3/T4 purgée** : paramètre `objectives_ref` de `_materialize_scenario_with_refs`
  (branche morte qui aurait émis une clé REJETÉE par le moteur — game_state ~329). ⚠️ La purge
  avait laissé un `NameError` latent (`hash_payload` référençait encore la variable) — attrapé par
  le test `test_materialize_scenario_with_refs_wall_override_emits_no_legacy_key`, corrigé.
- ✅ **Réserve T4 close** : `sweep_scenario_bank_v11.py` a désormais son bootstrap `sys.path`
  (L19) ; `migrate_scenario_bank_v11.py` n'a **aucun import projet** → n'en a pas besoin.
  ⚠️ **2026-08-02 : `sweep_scenario_bank_v11.py` a depuis été SUPPRIMÉ du dépôt** (`924c2b41`) ;
  cette réserve n'a plus d'objet, le balayage vit dans `test_scenario_bank_migration_v11.py`.
  ⚠️ **2026-08-13 : `migrate_scenario_bank_v11.py` a désormais SON bootstrap `sys.path`** (32) :
  il importe `shared/json_atomic.py` pour l'écriture atomique. C'est bien un import *projet*
  depuis le 2026-08-13 (le module a quitté `scripts/` pour `shared/`, seul dossier d'helpers
  importable depuis `ai/`, `services/` et `engine/`), et le bootstrap pointe donc la RACINE du
  dépôt. Il doit tenir aussi quand le script est chargé par chemin
  (`test_scenario_bank_migration_v11.py`), d'où le bootstrap plutôt qu'un import nu.
- ✅ **`ai/target_selector.py` SUPPRIMÉ** (validation utilisateur obtenue le 2026-07-16), avec son
  test `tests/unit/ai/test_target_selector.py`. Mort confirmé par grep exhaustif avant suppression :
  aucun importeur hors le module lui-même et son propre test (-9 tests collectés).
- ⚠️ **Contradiction non résolue (décision produit requise)** : T6.1 impose `--new`, qui écrit
  `ai/models/CoreAgent/model_CoreAgent.zip` — or CLAUDE.md (51-53, 215) et la décision de design
  n°1 interdisent d'écraser les zips protégés, et `ai/models/` est **gitignoré** (aucune
  récupération git). Écrasement autorisé ponctuellement par l'utilisateur (2026-07-16 : « le modèle
  est obsolète » — effectivement pré-squad, obs 355/357 incompatible avec obs 108). Voie propre à
  acter : chemin de sortie dédié pour les runs de validation (ex. `ai/models/_validation/<run_id>/`).

**Tests** :
- **+11** — `tests/unit/ai/test_train_wall_ref_contract.py` : `_load_scenario_wall_ref`
  (absent→None ; présent→strict ; présent-mais-invalide→erreur explicite, 5 cas paramétrés),
  `_apply_wall_ref_weighting` sur scénario terrain-only (repro de T6-a),
  `_materialize_scenario_with_refs` (param `objectives_ref` purgé, aucune clé legacy émise,
  passthrough sans override).
- **-9** — suppression de `test_target_selector.py` (module mort supprimé, cf. hygiène).
- **+2 nets** — `tests/unit/ai/test_analyzer_utils.py` : les 2 tests encodant le contrat LEGACY
  (`objectives` inline / `objectives_ref`) ont été MIGRÉS vers le contrat terrain — pas
  neutralisés : c'est LE comportement testé qui a changé par décision documentée (T3/T4), seule
  exception admise par §8. Ajout de 2 non-régressions : terrain sans area `"objective": true`
  → erreur explicite (piège T4 « liste vide en silence ») ; l'archive `_archive_pre_v11` de T4 ne
  masque pas un scénario vif.

**Bilan suite `tests/unit/` : VERTE, 1259 collectés** (1255 baseline T5 + 11 − 9 + 2), zéro échec,
zéro erreur. Smoke `scripts/smoke_t5_bare.py` rejoué après TOUS les fixes T6 :
`(A) invariant/terminaison=OK | (B) mêlée+Carnifex=OK`, `melee_kills_total=5`,
`carnifex_charge_any=True` — aucune régression moteur.

### T7 — Unification de la validation de déploiement — ⏸️ EN ATTENTE (déclencheur explicite)

**Déclencheur : le training tourne** (donc T6-h puis T6-g livrés, cf. [§0](index_v11.md#s0)). **Ne PAS commencer
avant** — voir « pourquoi pas maintenant ».

**Le problème.** Depuis T6-f, `deploy_unit` enchaîne DEUX contrôles :
1. **mono-ancre** (hérité de T5) : l'empreinte d'UN socle posé à l'ancre ⊆ zone, hors mur,
   clearance — miroir exact de `_get_valid_deployment_hexes` ;
2. **par-figurine** (T6-f) : la formation entière validée par `deployment_preview_plan`.

Le contrôle 1 teste **un objet qui n'existe plus** : l'unité n'occupe pas un socle à l'ancre,
elle occupe N socles répartis ; l'ancre est un point de référence, pas une figurine.

**Fondement règles (PDF lus, pas supposés)** :
- « 18 Transports.pdf » : « Set up **each model** in your unit wholly within the set-up
  distance » → la mise en place est PAR FIGURINE.
- « 24 Core abilities.pdf » : « set up that unit anywhere that is **wholly within** your
  deployment zone » → la contrainte porte sur l'unité ENTIÈRE, c.-à-d. toutes ses figurines.

Aucune règle ne mentionne un socle à l'ancre. Le contrôle 1 refuse donc des placements **légaux
au sens des règles** — typiquement une ancre en bord de zone dont le socle déborde alors que la
formation tiendrait entièrement dedans. Ordre de grandeur mesuré sur le balayage des 16 104
hexes de la zone (T6-f) : 263 refus `outside_zone` + 1 815 `out_of_bounds`, dont une part est
légale au sens 40K.

**Fix visé** : supprimer le contrôle mono-ancre du commit ET du masque, et laisser le décodeur
(`_select_deployment_hex_for_action`, qui valide déjà la formation depuis T6-f) être le SEUL
filtre. Un seul modèle de validation, aligné sur les règles, et l'agent récupère des placements
aujourd'hui interdits.

> 🔴 **CE FIX EST FAUX EN L'ÉTAT — NE PAS L'APPLIQUER (mesuré le 2026-07-20).**
>
> Il repose sur l'idée que le contrôle par-figurine « valide déjà la formation » à l'ancre
> demandée. **C'est faux** : `build_validated_deployment_plan` passe par
> `generate_compact_formation`, dont la spirale BFS retient la 1ʳᵉ case **légale** — l'ancre
> **oriente** le placement, elle ne le **contraint** pas.
>
> **Mesure** (balayage des 16 104 hexes de zone × 5 unités = 80 520 ancres, scénario
> d'entraînement réel). Sur les ancres refusées par le mono-ancre mais pour lesquelles un plan
> existe, **aucune figurine n'est posée à l'ancre demandée** :
> ```
> unit 3  ancre=(2,299)  mono=outside_zone   fig_à_l_ancre=False  plan=[(24,293)]
> unit 3  ancre=(3,298)  mono=outside_zone   fig_à_l_ancre=False  plan=[(24,293)]
> unit 3  ancre=(4,298)  mono=outside_zone   fig_à_l_ancre=False  plan=[(24,293)]
> unit 1  ancre=(2,299)  mono=out_of_bounds  fig_à_l_ancre=False  plan=[(8,297),(14,293),…]
> ```
> Quatre ancres distinctes → **le même plan**, à 22 colonnes de là.
>
> ⚠️ **Le chiffre « 14 859 ancres refusées à tort (18,5 %) », produit pendant cette session, est
> RETIRÉ.** Il mesure « il existe un placement légal quelque part », pas « ce placement-ci est
> légal ». Ne pas le recycler.
>
> **Supprimer le contrôle 1 ne débloquerait donc pas des placements légaux : ça rendrait 18,5 %
> de l'espace d'action non déterministe** — l'agent désigne une ancre et l'unité atterrit
> ailleurs. C'est la classe de bug « validé ≠ exécuté » que T6-g/T6-h ont éliminée.
>
> **Le code l'écrit déjà deux fois**, et l'audit T7 ne les avait pas lus :
> [deployment_handlers.py](../../../engine/phase_handlers/deployment_handlers.py)
> (« ne pas la retirer en croyant ce helper suffisant ») et le test dédié
> `test_anchor_is_a_suggestion_not_a_constraint`
> ([test_deployment_per_model_commit.py](../../../tests/unit/engine/test_deployment_per_model_commit.py)).
>
> **Le fond de T7 reste valide** : le contrôle 1 teste un socle unique à l'ancre, objet qui
> n'existe plus, et refuse de vraies formations légales en bord de zone. Mais le fix ne peut pas
> être « supprimer le contrôle 1 ». Il faut d'ABORD rendre le plan **contraint par l'ancre**
> (échec si la formation ne tient pas autour d'elle, au lieu de glisser), ce qui **inverse** le
> test ci-dessus — donc une **décision de design**, pas une correction de bug, à arbitrer
> explicitement. Périmètre restreint : `build_validated_deployment_plan` n'est appelé que par le
> décodeur gym ([action_decoder.py](../../../engine/action_decoder.py)) et le commit
> `deploy_unit` ; le flux PvP par escouade passe par
> [:859](../../../engine/phase_handlers/deployment_handlers.py) et n'est PAS touché.

**Pourquoi pas maintenant (raisonnement à ne pas re-dérouler)** : ça modifie le masque de
déploiement, donc **l'espace d'action de l'agent** — ça invalide les modèles entraînés et exige
une mesure avant/après. Le faire pendant que le training ne tourne pas ajoute du risque sans
pouvoir l'évaluer. Ordre optimal : **T6-h → T6-g → training qui tourne → T7**, dans sa propre
tranche, avec avant/après mesuré (win-rate et taux de refus de déploiement).

**Critère d'acceptation** : un seul prédicat de validation de déploiement dans le code (grep :
plus de `compute_candidate_footprint` dans `deploy_unit`) ; un placement légal au sens 40K mais
refusé aujourd'hui (ancre en bord de zone, formation entièrement dedans) est ACCEPTÉ — test
dédié, rouge avant le fix ; suite verte hors échecs préexistants ; PvP non régressé (le drag
mono-socle et l'auto-déploiement passent par le même commit).

### Phase B (après T6 ET Phase A' — [section 9](decisions_du_joueur.md#s9) — validés) — Observation niveaux
Spec à figer à ce moment-là, principes déjà actés :
- Ajouter aux 7 features par-figurine un `level` normalisé (source : champ `level` de la
  figurine, posé game_state.py ~162) et aux 9 features par slot ennemi le niveau de l'ancre ;
  exposer aussi un signal de coût de descente pour l'activation courante
  (`squad_descent_penalty_subhex`, movement_handlers.py). Toute modif de layout change
  `obs_size` (config + constantes `SQUAD_*` observation_builder ~1245-1251) → nouveau modèle from
  scratch, mettre à jour la `justification` en même temps.
- Terrains d'entraînement à étages : SEULEMENT après vérification de l'état du chantier LoS 3D
  (spatial_relations.py "câblage incomplet") — sinon l'agent apprendrait sur un tir
  non conforme aux règles.
- Action "monter" (nouveau slot) = Phase C, décision utilisateur explicite requise.

<a id="s6"></a>
## 6. Critères d'acceptation

| Tranche | Critère (tous vérifiables par commande) |
|---|---|
| T1 | Suite de tests verte ; smoke test moteur nu (annexe A) passe la phase shoot, la phase charge avec Carnifex ET une phase fight avec pertes allouées (chemin FIGHT_CTX) sans exception |
| T2 | Zéro littéral d'action dans ai/. Le grep n'est qu'une HEURISTIQUE (3 versions successives ont toutes eu des trous : `== 11`, `X in valid_actions`, listes, `return 10/12/18`, dicts de poids `{4: 0.50,...}`, `action % 8`, sous-dossiers, + faux positifs légitimes dans train.py) — le critère réel est un AUDIT MANUEL exhaustif des 4 fichiers `evaluation_bots.py`, `env_wrappers.py`, `bot_evaluation.py`, `game_replay_logger.py` : chaque comparaison/émission d'entier d'action passe par une constante de macro_intents. Grep de contrôle : `grep -rnE "(step\([0-9]+\)|WAIT_ACTION|==\s*[0-9]+\b|\b[0-9]+ in valid_actions|return 1[028]\b|% 8)" ai/` avec revue de chaque hit. Smoke test pile complète avance au-delà du premier WAIT forcé |
| T3 | `train.py --step --training-config x1_debug` dépasse la résolution walls/objectives sans FileNotFoundError |
| T4 | Les 61 scénarios se chargent (`W40KEngine(scenario_file=...)` + reset, script de balayage) ; zéro clé legacy ; sort de training_save/ statué |
| T5 | 10 épisodes aléatoires masqués terminés sur ≥3 scénarios × sièges p1/p2 ; zéro masque vide |
| T6 | ⚠️ *(périmée n°3 de [§0bis](index_v11.md#s0bis) : le blocage par `CC_DMG` est levé — [§0.3](index_v11.md) porté, run 60/60 en [§0.7](index_v11.md) — cellule conservée telle quelle, non corrigée)* Run `--new` court complet + analyzer + replay OK ; ~~win-rate vs RandomBot en progression~~ → **critère REMPLACÉ le 2026-07-19, voir [section 10.6](strategie_evaluation.md#s10.6)** (win-rate PAR ROSTER contre un adversaire de holdout jamais vu à l'entraînement + absence de comportement absurde en partie humaine). L'ancien critère référençait un holdout de rosters qui n'existe plus. — ⏳ **PARTIEL (2026-07-16)**. ✅ Run `--new` : déroule sans AUCUNE exception (467/500 ép.). ✅ Suite verte (1293) + smoke `(A)/(B)` OK (mêlée 5 kills, Carnifex charge). ✅ T6-c résolu : `_process_squad_action` journalise, analyzer tourne, `1.2 erreurs shooting = 0`. ✅ **T6-d résolu** : `squad_fight` = sélection FIGHT 12.04, machine V11 déroulée par `_fight_v11_gym_settle` (ordre 12.02→12.04→12.07 respecté, snapshot posé, double activation interdite). ❌ **win-rate NON concluant** : ~30 % vs GreedyBot sur 467 ép. (bruit) — mesuré AVANT T6-d, donc sur un moteur où la mêlée était fausse ; **à re-mesurer** avec phase `x1` + `bot_evaluation` holdout vs RandomBot. ✅ **Le run TOURNE de nouveau depuis le 2026-07-19** : T6-g et T6-h sont livrés (cf. [§0](index_v11.md#s0)), x5_debug 8 workers 10/10 ép. exit 0. ❌ **Le critère T6 reste NON évaluable**, mais pour une raison DIFFÉRENTE et désormais isolée : **[§10.4](strategie_evaluation.md#s10.4)** — sur le chemin single-scenario, P2 joue ALÉATOIRE (`SelfPlayWrapper(frozen_model=None)`, `update_frozen_model` sans appelant). Tout win-rate mesuré aujourd'hui est du bruit. ~~C'est le prochain bloqueur.~~ **✅ [§10.4](strategie_evaluation.md#s10.4) RÉSOLU le 2026-07-19** (adversaires câblés sur les 3 chemins) ; le critère T6 reste néanmoins NON évalué, ~~désormais bloqué par `CC_DMG` ([§0.3](index_v11.md)) qui plante des épisodes d'évaluation~~ — CC_DMG levé (§0.3 porté, 60/60 en §0.7). État courant : [v11_chemin_critique.md](../../Roadmap/v11_chemin_critique.md). |
| T6-i | ⚠️ *(périmée n°2 de [§0bis](index_v11.md#s0bis) : le test de non-régression existe : `test_end_of_turn_coherency_03_03.py` — cellule conservée telle quelle, non corrigée)* Une escouade rendue incohérente par des pertes est ramenée en coherency à la fin du tour (03.03), sur les **deux** chemins de fin de Fight, avant le test de limite de tour ; aucune destination du masque de move n'est rejetée pour cause de coherency — ⏳ **PARTIEL (2026-07-19 soir)** : ✅ fix livré et vérifié par run bout-en-bout (8 épisodes plantés → 2, erreur `incohérence masque/exécution` disparue, suite sans régression) ; ❌ **test de non-régression NON écrit** — §8 l'impose, c'est la tâche n°1 de [§0.0](index_v11.md) |
| T6-f | Après le commit de déploiement, AUCUNE figurine vivante à `(-1,-1)` et ancre `units_cache` = figurine d'index minimal, sur les 3 chemins (gym, ancre imposée tutoriel, drag) — ✅ **FAIT (2026-07-19)** |
| T6-g | Toute cellule offerte par le masque de move est exécutable : sur N épisodes aléatoires, zéro `ValueError` « incohérence masque/exécution » — et un test dédié où une escouade dont le BLOC déborde (mur / autre escouade) ne voit PAS la cellule dans son masque — ✅ **FAIT (2026-07-19)** : `test_move_pool_block_erosion.py` (+6, mur/escouade/ER sous une SŒUR, débordement plateau, non-sur-filtrage, mono-fig) ; runs x5_debug 8 workers (10/10 ép.) et mono-env x1_debug, zéro occurrence |
| T6-h | La translation de bloc préserve les distances internes pour TOUTES les parités de `dx` (test paramétré `dx` pair ET impair) — rouge sur le code actuel — ✅ **FAIT (2026-07-19)** : `test_rigid_plan_translation.py` (+10), rouge avant le fix aux seules parités impaires ; fix étendu à `translate_squad_to_destination` (écrivain du commit) et `preview_hidden_models_after_move` |

<a id="s7"></a>
## 7. Annexe A — Smoke tests de référence

Deux scripts éprouvés pendant l'audit (à recréer dans `scripts/` ou en scratch ; ne pas
committer les monkeypatches, ils simulent les fixes T1) :

1. **Moteur nu** : `W40KEngine(gym_training_mode=True, scenario_file=<board scenario>)`,
   boucle `reset()` puis `step(choice(flatnonzero(get_action_mask())))` jusqu'à
   terminated/masque vide, 3 seeds. Diagnostic à imprimer si masque vide : phase, tour, joueur,
   pools `*_activation_pool`, états `pending_*`/`fight_*`.
2. **Pile complète** : `Monitor(BotControlledEnv(ActionMasker(engine), GreedyBot(0.15),
   registry, agent_seat_mode="random", global_seed=...))` — miroir exact de
   [train.py](../../../ai/train.py).

Résultats d'audit (2026-07-14) : moteur nu OK jusqu'au tour 5 avec fixes R4 simulés (deadlock
R7 en fin de partie) ; pile complète bloquée immédiatement par R5 (`step(11)`).
Réserve : seul le décideur tir était patché — le chemin d'allocation de pertes en mêlée
(FIGHT_CTX) n'a pas été prouvé par ce smoke test (cf. R4/T1).

<a id="s8"></a>
## 8. Tests de non-régression (obligatoires, toutes tranches)

Commande canonique (à lancer après CHAQUE modification, avant de déclarer une tranche finie) :

```bash
source /home/greg/40k/.venv/bin/activate && python3 -m pytest tests/unit/ -q
```

**Baseline vérifiée (2026-07-15)** : 1152 tests collectés dans `tests/unit/` (ai/ engine/
services/ shared/), zéro erreur de collecte, 1152 passed / 2 skipped après T1. Toute exécution
qui passe SOUS ce compte de collectés = suppression de test à justifier explicitement (jamais
en silence). Un test qui devient rouge après une tranche = STOP, corriger la root cause (jamais
adapter le test pour le faire passer, sauf si c'est LE comportement testé qui change par
décision documentée ici).

<a id="s8.1"></a>
### 8.1 Principes (non négociables)

- **Un fix = ses tests dans la même tranche** : chaque rupture R1-R7 corrigée s'accompagne de
  tests qui reproduisent la panne d'origine (le test doit échouer sur l'ancien code) ET
  verrouillent le comportement corrigé.
- **Miroir PvP** : pour tout prédicat/chemin bifurquant gym vs PvP, tester LES DEUX branches —
  le test PvP fige le comportement d'avant-fix (neutralité), le test gym fige le fix.
- **Zéro monkeypatch de code mort** : fait le 2026-07-28 (§0.38) — les 6 fichiers qui patchaient
  `_attack_sequence_rng` ont été re-pointés sur le chemin vif, puis la fonction supprimée.
  Aucun nouveau test ne doit s'appuyer sur du code sans site d'appel vif.
- **Déterminisme** : tout test utilisant du RNG fixe sa seed ; tout test d'ordre de candidats
  (P2/P3) vérifie la STABILITÉ de l'ordre sur deux appels identiques.
- **Erreurs explicites testées** : chaque garde « erreur explicite, pas de fallback » ajoutée
  par le plan a un test `pytest.raises` vérifiant le TYPE et le MESSAGE (fragment discriminant).
- Les tests règles encodent le PDF du projet (référence 40k_rules citée en docstring), jamais
  le comportement du code mort.

<a id="s8.2"></a>
### 8.2 Socle transverse — tests de contrat d'interface (à écrire en T2, maintenus ensuite)

Fichier proposé : `tests/unit/engine/test_agent_interface_contract.py`.
- `action_space.n == 41` et `observation_space.shape == (108,)` lus depuis la config (échec
  explicite si la config change sans migration de modèle actée).
- **Cohérence constantes ↔ décodeur** : pour chaque constante de `macro_intents.py` créée en T2
  (`ACTION_WAIT`, `SHOOT_SLOT_BASE`, bases move/advance/fallback, `ACTION_CHARGE`,
  `ACTION_FIGHT`, `DEPLOY_SLOTS`), un test vérifie que `ActionDecoder` route bien cet entier
  vers l'intention attendue (wait→wait, 19→shoot slot 0, 24→charge...). C'est LE verrou
  anti-récidive de R5 : tout futur re-layout casse ce test au lieu de casser le training.
- Somme du layout : `6+6+6+1+5+1+1+15 == TOTAL_ACTION_SIZE == 41`.
- Le masque retourné par `get_action_mask()` a exactement `shape (41,)`, dtype bool.

<a id="s8.3"></a>
### 8.3 Couverture par tranche

**T1 (fait — tests à vérifier présents, compléter si trous)** :
- R6 : éligibilité + destinations de charge avec `BASE_SIZE` liste (Carnifex `[41,27]`,
  Psychophage `[47,36]`) dans les DEUX sites (`charge_build_valid_destinations_pool`,
  `_charge_reverse_goal_bfs_for_eligibility`) — plus cas socle rond int (non-régression).
- R4 : `is_programmatic_owner`/`is_programmatic_defender` — matrice complète :
  (gym_training_mode True/False) × (player_types human/ai) ; allocation tir auto en gym ;
  **allocation fight auto en gym avec pertes réellement allouées** (le chemin FIGHT_CTX,
  jamais exercé avant T1) ; les 4 sites `defender_human` du flux fight ; en PvP humain,
  l'allocation reste manuelle (miroir) ; ~~`_is_ai_controlled_shooting_unit` NON branché sur
  gym (test négatif : pas d'auto-activation `active_shooting_unit` en gym)~~ — **sans objet
  depuis le 2026-08-08** : l'auto-activation de tir et son prédicat sont supprimés, le risque
  est structurellement impossible et non simplement non testé.

**T2** :
- Tests 8.2 ci-dessus.
- `env_wrappers` : WAIT forcé émet `ACTION_WAIT` (18) ; détection « pool empty » ; plus AUCUN
  test ne référence 11/12 ou les plages 4-8 hors déploiement.
- `evaluation_bots` : pour chaque phase (move/shoot/charge/fight), le bot ne choisit QUE des
  actions du masque ; choix hors masque = erreur explicite (test `raises`) ; les dicts de
  poids déploiement pointent des actions de `DEPLOY_SLOTS`.
- ~~`game_replay_logger` : décodage correct du layout 41 (un cas par famille d'action) — ou, si
  condamné, erreur explicite testée.~~ → **sans objet : le module est supprimé ([§0.8](index_v11.md)).** Ne pas
  réécrire de test pour lui.

**T3** :
- `_list_available_board_refs` retourne les refs du board résolu par
  `config_loader.get_board_dir()` (test avec `W40K_BOARD_PATH` pointant un board de fixture) ;
  plus aucune reconstruction `{cols}x{rows}` (test sur analyzer si migré).
- `_expand_random_ref_weights` : refs inconnues → erreur explicite listant les refs
  disponibles ; refs valides → expansion correcte.
- R1 selon la décision : phase `default` existante OU `--training-config` manquant → erreur
  explicite listant les phases (test du message).
- `_materialize_eval_scenario_refs` n'émet PLUS `objectives_ref` (clé absente du scénario
  matérialisé — test de sortie).

**T4** :
- Résolveur `board_ref` : (a) parent `scenario/` sans `board_ref` → OK (comportement PvP
  inchangé) ; (b) `board_ref` valide hors `scenario/` → OK ; (c) ni l'un ni l'autre → erreur
  explicite ; (d) `board_ref` inexistant → erreur explicite. Idem pour `wall_ref: "random"`
  et `terrain_ref`.
- **Balayage de la banque** (test paramétré sur les 61 scénarios migrés) :
  `W40KEngine(scenario_file=...)` + `reset()` sans exception ; zéro clé legacy
  (`objectives`, `objectives_ref`, `objective_hexes`, `deployment_zone`) ; ≥ 1 objectif
  résolu (piège « liste vide en silence », game_state ~376-381) ; `deployment_zones` avec
  clés `"1"`/`"2"`.
- Script de migration : idempotence (2e passage = zéro diff).

**T5** :
- R7 : scénario minimal amené au dernier tour, phase fight du dernier joueur, pools vides →
  `terminated=True`, winner déterminé, JAMAIS masque vide avec `terminated=False`. Cas
  symétriques P1/P2.
- Invariant global (smoke intégré en test, 3 seeds × 2 sièges, plafonné en steps) : à chaque
  step, `mask.any() or terminated` — c'est l'invariant qui protège MaskablePPO.

**T6** : à l'origine « pas de test unitaire nouveau (validation par run réel + analyzer +
replay), suite complète verte ». Les ruptures T6-c→T6-h ont imposé des verrous :
- `test_squad_fight_target_parity.py` (T6-c, +5) et `test_squad_fight_v11_state.py` (T6-d, +6).
- `test_deployment_per_model_commit.py` (T6-f, +10) : aucune figurine à `(-1,-1)` après commit ;
  ancre = figurine d'index minimal (invariant de `build_rigid_plan`) ; légalité du plan
  committé ; déterminisme + lecture pure de `build_validated_deployment_plan` ; invalidation de
  la mémo sur tampon périmé ; équivalence de l'empreinte pré-calculée aux DEUX parités de
  colonne (l'optimisation touche du code partagé PvP).
- `test_rigid_plan_translation.py` (T6-h, +10) : distances internes du bloc préservées, paramétré
  sur `dx` PAIR **et** IMPAIR — un test qui n'exerce que `dx` pair passe sur le code buggé.
- `test_move_pool_block_erosion.py` (T6-g, +6) : mur / autre escouade / ER ennemie sous une SŒUR
  alors que l'ANCRE est légale, débordement de plateau, absence de sur-filtrage, court-circuit
  mono-figurine. `game_state` fabriqué — d'où le test suivant.
- `test_move_mask_is_executable.py` (T6-g/T6-h, +3) : l'invariant « masque ⊆ exécutable » sur le
  VRAI moteur (3 seeds × 400 steps, ~21 700 cellules par run), avec le budget exact
  qu'`execute_squad_move` appliquerait. Couvre les deux contraintes que l'érosion ne filtre pas
  et qui n'étaient que RAISONNÉES invariantes par translation cube (`budget_per_model`,
  `require_coherency`).
  ⚠️ **Contre-épreuve obligatoire pour ce genre de test** : il a d'abord été « validé » par un
  `git stash` qui, les fixes ayant été committés entre-temps, n'annulait que le refactor — le
  test passait donc pour une mauvaise raison. La vraie épreuve est
  `git checkout 3886e498 -- engine/phase_handlers/shared_utils.py` : le test devient ROUGE sur
  les 3 seeds avec l'erreur d'origine (`squad=103 dest=(24,15) … incohérence masque/exécution`).
  Un test de non-régression qu'on n'a pas vu échouer ne garde rien.

⚠️ **La suite n'est PAS verte et ne l'était pas avant ces fixes** : 9 échecs préexistants
(4 banque de scénarios + 5 déploiement/terrain), tous dus à des rosters manquants ou non
résolus. Le critère réel est donc « pas de NOUVEL échec », à établir par baseline `git stash`
avant de conclure quoi que ce soit sur une régression.

<a id="s8.4"></a>
### 8.4 Couverture Phase A' (une règle = son fichier de tests, AVANT suppression du code mort)

- Chaque règle du tableau P1 ([section 9.2](decisions_du_joueur.md#s9.2)) : tests sur le chemin VIF (`_manual_roll_intent` /
  `_resolve_one_manual_wound`) encodant le PDF — cas nominal, cas limite, cas d'inapplicabilité.
  Minimum par règle : HEAVY (les 3 conditions 24.16, chacune isolée) ; HAZARDOUS (un jet PAR
  ARME sélectionnée, pas par attaque ; réutilisation de `roll_hazard_for_unit`) ;
  IGNORES_COVER (bypass du malus, ET non-régression : arme sans le trait subit toujours
  13.08) ; DEVASTATING_WOUNDS (arrêt de séquence, MW après dégâts normaux, max 1 figurine
  par critical wound) ; RAPID_FIRE (bonus à mi-portée exacte, rien au-delà) ;
  closest_target_penetration (AP+1 seulement sur la cible la plus proche) ; rerolls tir
  (parité avec les tests fight existants).
- Suppression du code mort : après purge, la suite passe SANS les tests monkeypatchés
  supprimés, et un test-sentinelle vérifie que `execute_action` sur les anciennes branches
  lève l'erreur « squad path expected ».
- P2/P3 (par décision branchée) : ordre des candidats déterministe et stable (deux appels →
  même liste) ; masque expose exactement les `CHOICE_i` des candidats valides ; décision
  appliquée = candidat choisi ; en PvP le prompt `waiting_for_player` équivalent est intact
  (miroir) ; heuristique `_ai_select_*` toujours utilisée par le bot adversaire.

<a id="s8.5"></a>
### 8.5 Critère d'acceptation global

`python3 -m pytest tests/unit/ -q` vert (0 failed, 0 error, skips justifiés) est une condition
NÉCESSAIRE de sortie de CHAQUE tranche (T1→T6, puis chaque tranche P1/P3) — en complément des
critères spécifiques de la section 6, jamais à leur place.

---

## Correspondance des sources

| Ancien fichier | Ancien § | Section actuelle |
|---|---|---|
| `V11_agent_rework.md` / `1_Agent/V11_agent_rework.md` | §1→§8 | [`tranches_et_ruptures.md`](tranches_et_ruptures.md) §1→§8 (ce fichier) |
| `index_v11.md` avant découpage (2026-07-28) | §1→§8 | [`tranches_et_ruptures.md`](tranches_et_ruptures.md) §1→§8 (ce fichier) |
| `V11_tranches.md` | (ancienne tentative de nom) | [`tranches_et_ruptures.md`](tranches_et_ruptures.md) (ce fichier) |
