# V11 — Rétablissement de l'entraînement de l'agent (agent rework)

Date d'audit : 2026-07-14. Tous les faits ci-dessous ont été vérifiés dans le code actuel
(lecture + exécution de smoke tests), puis contre-vérifiés par une review indépendante
(2026-07-14 soir). Chaque rupture est accompagnée de sa reproduction exacte.

**Convention d'ancrage** : l'ancre de référence est le NOM DE FONCTION ; les numéros de ligne
sont indicatifs (constaté pendant l'audit : fight_handlers.py a bougé de ~45 lignes en une
journée). Toujours re-localiser par grep du nom avant d'éditer.

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
  Détail en section 8.
- **Phase B (obligatoire)** : mise à niveau de l'observation — l'agent perçoit les niveaux
  (élévation) et les coûts associés.
- **Phase C (optionnelle, hors scope initial)** : nouveaux points de décision au-delà de la
  Phase A' (ex. montée d'étage). À ne PAS entamer sans validation utilisateur.

**Interdits absolus** (CLAUDE.md) : aucun fallback/workaround/valeur par défaut pour masquer une
erreur ; ne jamais modifier `config/users.db` ni `ai/models/**/*.zip` ; les règles de jeu se
vérifient dans `Documentation/40k_rules/` avant toute décision règles.

## 2. État des lieux vérifié (ce qui marche)

- Tous les imports du pipeline passent (`ai.train`, `ai.env_wrappers`, `ai.multi_agent_trainer`,
  `ai.reward_mapper`, `ai.scenario_manager`, `ai.unit_registry`, ... — vérifié par exécution).
- L'environnement gym EST le moteur : `W40KEngine(gym.Env)` ([w40k_core.py:147](../../engine/w40k_core.py#L147)),
  `reset()` L918, `step(action: int)` L1330. Espace d'action `Discrete(41)` (L629), observation
  `Box(108,)` (L660), les deux lus depuis `observation_params` de
  [CoreAgent_training_config.json](../../config/agents/CoreAgent/CoreAgent_training_config.json) (obs_size 108, action_space_size 41), sans défaut.
- Espace d'action squad actuel — source unique [macro_intents.py:8-20](../../engine/macro_intents.py#L8-L20) :
  - 0-5 move normal (6 directions), 6-11 advance (6 dir), 12-17 fall back (6 dir),
  - 18 wait/end activation, 19-23 shoot slots 0-4, 24 charge, 25 fight,
  - 26-40 zone intents (5 objectifs × 3 intents). Total 41.
- Masque : `ActionDecoder.get_squad_action_mask_and_eligible_units`
  ([action_decoder.py:146](../../engine/action_decoder.py#L146)) ; exposé par `W40KEngine.get_action_mask()` (L5563), branché
  MaskablePPO via `ActionMasker` ([train.py:1448-1451](../../ai/train.py#L1448-L1451)).
- Observation squad 108 : `build_squad_observation` ([observation_builder.py:1253](../../engine/observation_builder.py#L1253)) —
  16 global + 5 agrégats squad + 6 figurines × 7 features + 5 slots ennemis × 9 features.
  Layout **purement 2D** (col/row) : aucune feature de niveau/élévation.
- Rewards : `RewardCalculator` ([reward_calculator.py:23](../../engine/reward_calculator.py#L23)) piloté par
  `CoreAgent_rewards_config.json` (squad_shaping, base_actions, situational_modifiers,
  zone_intent_shaping) — pas de valeurs par défaut, à une nuance près :
  `situational_modifiers` est optionnel dans une branche (~L782). OK à interface constante.
- Le moteur distingue déjà training et PvP : `gym_training_mode` (auto-résolution des prompts,
  `_is_player_human` renvoie False — [w40k_core.py:2201-2206](../../engine/w40k_core.py#L2201-L2206)) et `pve_mode` (adversaire géré
  par wrapper externe en training, `pve_mode=False`, [w40k_core.py:226-229](../../engine/w40k_core.py#L226-L229)).
- Wrappers : `BotControlledEnv` (scénarios "bot", GreedyBot, [train.py:1749-1791](../../ai/train.py#L1749-L1791)) et
  `SelfPlayWrapper` (self-play, modèle gelé) dans [env_wrappers.py](../../ai/env_wrappers.py).
- Un smoke test moteur nu (actions aléatoires masquées, scénario board actuel) déroule
  deployment/command/move/shoot/charge/fight jusqu'au tour 5 une fois les ruptures R4/R6
  contournées — le cœur par-figurine (fight V11 auto, footprints, descente §13.06) fonctionne
  en gym.

**Contexte de divergence (git)** : dernier commit sur `ai/env_wrappers.py` = 2026-05-30, sur
`ai/train.py` = 2026-05-31. Toutes les features suivantes sont postérieures : charge rework
(06-01), fight V11 (06-12→07), LoS unifiée (07-02), niveaux + coût descente §13.06 (07-09),
perModelMove (07-10), replay/snapshots (07). Le pipeline RL est resté sur le modèle de fin mai.

## 3. Ruptures vérifiées (avec reproduction)

### R1 — Phase de training `default` absente
**Repro** : `python3 ai/train.py --agent CoreAgent --scenario bot --step` →
`KeyError: "Phase 'default' not found in CoreAgent_training_config.json. Available:
['x1','x5_append','x5_new','x1_debug','x5_debug']"` (config_loader.py:274).
`--training-config` a pour défaut `"default"` ([train.py:4232](../../ai/train.py#L4232)).

### R2 — train.py reconstruit le chemin board depuis {cols}x{rows}
**Repro** : `python3 ai/train.py --agent CoreAgent --scenario bot --step --training-config x1_debug`
→ `FileNotFoundError: Board walls directory not found: config/board/220x300/walls`.
Cause : `_list_available_board_refs` ([train.py:586-591](../../ai/train.py#L586-L591)) construit
`config/board/{cols}x{rows}/` (= 220x300, dimensions subhex) alors que le dossier réel est
`config/board/44x60x5/` (44x60 pouces, scale 5). La source de vérité existe déjà :
`config_loader.get_board_dir()` ([config_loader.py:79-87](../../config_loader.py#L79-L87), gère `W40K_BOARD_PATH` + `paths.board`).
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
  un dossier nommé exactement `scenario/` sous un board ([game_state.py:1646-1651](../../engine/game_state.py#L1646-L1651)) ; idem pour
  `wall_ref: "random"` ([game_state.py:1437-1441](../../engine/game_state.py#L1437-L1441)) et `terrain_ref` (L1496-1505).
  **Repro** : charger `holdout_hard/scenario_bot-01.json` → `ValueError: must be located in a
  'config/board/<board>/scenario/' directory`.
- **(b) Objectifs** : les clés `objectives`, `objectives_ref`, `objective_hexes` sont SUPPRIMÉES et
  lèvent une erreur explicite ([game_state.py:320-329](../../engine/game_state.py#L320-L329)). Source unique désormais : terrains
  flaggés `"objective": true` dans le `terrain_ref` (règles 14.01/14.02). **Tous** les scénarios
  de la banque utilisent `objectives_ref` → tous invalides.
- **(c) Refs de walls périmées** : `config/board/44x60x5/walls/` ne contient que `walls-33`,
  `walls-mc1`, `walls-none`. 28 scénarios de la banque référencent `walls-11` (inexistant) —
  27 avec extension `.json`, 1 sans (format à normaliser au passage) ; les 33 autres utilisent
  `"random"`.
- **(d) Zones de déploiement** : voie moderne = section `deployment_zones` du terrain_ref
  (polygones par joueur, [game_state.py:400-432](../../engine/game_state.py#L400-L432)) ; voie legacy = fichier nommé
  `config/deployment/{cols}x{rows}/<zone>.json` (L436-440), or `config/deployment/220x300/` ne
  contient que `mc1.json` — le `deployment_zone: "hammer"` de toute la banque est introuvable.
- **(e) Niveaux** : les scénarios d'entraînement n'ont pas de `terrain_ref`, donc aucun étage —
  l'agent ne s'entraînerait jamais sur la feature niveaux même une fois le reste réparé.
- **(f) La training config ELLE-MÊME est cassée** (raté des deux premiers audits) : dans les
  5 phases de `CoreAgent_training_config.json`, `scenario_sampling.train_wall_ref_weights` =
  `walls-11/21/31.json` (0.3 chacun, inexistants) et `eval_objectives_refs` =
  `objectives-51.json` (le dossier `objectives/` n'existe plus). Après le fix R2,
  `_expand_random_ref_weights` lèvera « unknown refs for board walls » ([train.py:623-628](../../ai/train.py#L623-L628)).
- **(g) Chemin d'éval holdout cassé dans `ai/bot_evaluation.py`** :
  `_materialize_eval_scenario_refs` ÉMET `objectives_ref` (L75, clé rejetée par le moteur) et
  les `eval_wall_refs`/`eval_objectives_refs` pointent les mêmes fichiers inexistants.
  Consommé par les callbacks d'éval de train.py (~L3231/3340), l'éval finale (~4185) —
  cassera même après T3/T4 si seul train.py est migré.

### R4 — Allocation des pertes : gym non reconnu comme "défenseur IA" (BLOQUANT runtime)
**Repro** (moteur nu, gym_training_mode=True, scénario board valide) : première action
`squad_shoot` → `RuntimeError: squad_shoot: allocation tir non terminee en auto pour squad 1001
(defenseur non-IA ?)` ([w40k_core.py:4938-4943](../../engine/w40k_core.py#L4938-L4943)).
Cause : le moteur d'allocation mutualisé tir/fight décide humain-vs-auto via des prédicats qui
lisent UNIQUEMENT `game_state["player_types"]` ; en training self-play `pve_mode=False` →
`player_types = {"1":"human","2":"human"}` ([w40k_core.py:454-456](../../engine/w40k_core.py#L454-L456)) → l'allocation attend un
humain. Il y a en réalité **QUATRE prédicats divergents** :
- `W40KEngine._is_player_human` — consciente de `gym_training_mode` (L2201-2206) ;
- `_target_defender_is_ai` ([shared_utils.py:89-101](../../engine/phase_handlers/shared_utils.py#L89-L101)) — player_types only, `auto_decider` de SHOOT_CTX ;
- `_is_ai_controlled_fight_unit` (fight_handlers, def ~L97) — player_types only ; utilisée par
  `_fight_auto_defender` (def ~L5705) → `auto_decider` de **FIGHT_CTX** (~L5715-5728) et par
  les 4 décisions `defender_human` du flux fight (~L5425, L5450, L6150, L6184) ;
- `_is_ai_controlled_shooting_unit` (shooting_handlers, def ~L2144) — player_types only, pilote
  l'auto-activation `active_shooting_unit` (cf. ⚠️ ci-dessous : ne PAS la rendre vraie en gym).
**La mêlée crashe de la même façon que le tir** (vérifié par lecture) : `squad_fight` →
`build_manual_fight_allocation` non `done` → `RuntimeError "squad_fight: allocation combat non
terminee en auto"` ([w40k_core.py:5026-5031](../../engine/w40k_core.py#L5026-L5031)), garde jumelle dans fight_handlers
(~L3352-3357). Le gate `is_gym_training` de la consolidation (~L1552) ne couvre PAS
l'allocation.
**Fix vérifié par simulation côté tir uniquement** (monkeypatch : `_target_defender_is_ai`
renvoie True si `game_state["gym_training_mode"]`) : le tir s'auto-résout ensuite correctement.
⚠️ Le smoke test « moteur nu jusqu'au tour 5 » ne prouve PAS le chemin d'allocation fight :
seule `_target_defender_is_ai` était patchée — la seule explication cohérente est qu'aucune
blessure de mêlée n'a été réussie pendant le smoke. À couvrir explicitement en T1 (scénario de
smoke avec pertes en mêlée garanties).
⚠️ Ne PAS "fixer" en mettant `player_types` à `"ai"` : cela active l'auto-activation tir
(`active_shooting_unit`, [shooting_handlers.py:1082-1086](../../engine/phase_handlers/shooting_handlers.py#L1082-L1086)) qui reste alors périmé après
l'activation et fait exploser le décodeur (`active_shooting_unit X is not in
shoot_activation_pool`, [action_decoder.py:418-423](../../engine/action_decoder.py#L418-L423)) — vérifié par exécution.

### R5 — Wrappers et bots sur l'ANCIEN layout d'actions (BLOQUANT runtime)
**Repro** (pile complète `BotControlledEnv(ActionMasker(W40KEngine))` + GreedyBot) :
`env_wrappers.py:436` force `self.env.step(11)` comme "WAIT" → dans l'espace actuel 11 =
**advance direction 5** → `ValueError: convert_squad_action: advance_roll manquant`
([action_decoder.py:885](../../engine/action_decoder.py#L885)).
- `ai/evaluation_bots.py:36` : `WAIT_ACTION = 11` (actuel : **18**) ; usages de `12` comme action
  spéciale (actuel : fall back dir 0) ; slots de tir supposés 4-8 (actuel : **19-23**) ;
  `DEPLOYMENT_ACTIONS = [4..8]` réutilisé comme slots de TIR (L86) ; moves supposés 0-3
  (`0 in valid_actions` L135, `[0, 1, 2, 3, WAIT_ACTION]` L179) au lieu de 0-5.
- `ai/env_wrappers.py` : littéraux `11` périmés en L436 (`step(11)`), L796 (`action == 11`),
  L900 (`bot_action == 11`) ; plages shoot 4-8 codées en dur L793, L871, L898. Le fichier
  **mélange déjà les deux espaces** : les branches "Pool empty -> advance phase via WAIT"
  retournent, elles, `18` (valeur correcte) — L556, L854 (BotControlledEnv) et L1172, L1188
  (SelfPlayWrapper). C'est la preuve d'une migration partielle, pas un layout cohérent.
- `ai/game_replay_logger.py:774-828` (raté des deux premiers audits) : layout encore PLUS
  ancien à 8 actions (`action % 8`, moves 0-3, shoot=4, charge=5, wait=6, fight=7) — les
  replays de training décoderaient n'importe quoi ; à migrer ou à condamner explicitement.
- Les actions de déploiement 4-8 sont, elles, TOUJOURS valides ([action_decoder.py:160-175](../../engine/action_decoder.py#L160-L175)).
- L'incohérence est documentée dans la config elle-même : `justification` dit
  "action_space_size=31 (16 micro + 15 macro)" alors que le champ vaut 41 (26 micro + 15 macro)
  — les wrappers/bots sont restés sur un layout intermédiaire.

### R6 — Bug moteur : socles ovales en éligibilité de charge (touche AUSSI le PvP)
**Repro** : scénario contenant un Carnifex ou Psychophage (seuls types à `BASE_SIZE` liste,
vérifié via UnitRegistry : `[41,27]` et `[47,36]`) → à l'entrée en phase charge,
`charge_build_valid_destinations_pool` → `TypeError: can only concatenate list (not "int") to
list` ([charge_handlers.py:3627-3628](../../engine/phase_handlers/charge_handlers.py#L3627-L3628)) : `_mover_bs = unit["BASE_SIZE"]` puis
`(_mover_bs + 1) // 2` sans gérer le cas liste, alors que le même bloc le gère pour l'ennemi
6 lignes plus bas (`_e_bs_int = max(_e_bs) if isinstance(_e_bs, (list, tuple)) ...`, L3634-3635).
Chemin atteignable en PvP via `_has_valid_charge_target` (L3390) → à corriger indépendamment du
training. Les rosters d'entraînement Tyranids peuvent contenir ces unités.
**DEUXIÈME occurrence du même pattern** : `_charge_reverse_goal_bfs_for_eligibility`
([charge_handlers.py:825-826](../../engine/phase_handlers/charge_handlers.py#L825-L826)), même asymétrie avec l'ennemi (L832-833), calcul fait AVANT le
garde `BASE_SHAPE == "round"`. Nuance vérifiée : la fonction est DÉSACTIVÉE sur boards scalés
(appelée seulement si `inches_to_subhex <= 1`, ~L3693-3697 ; notre board = 5) → site
inatteignable en pratique sur 44x60x5. Le fix T1 couvre quand même LES DEUX sites (défense en
profondeur) ; seul le premier (L3627) crashe réellement.

### R7 — Fin d'épisode au tour limite : masque vide sans terminaison (moteur nu)
**Repro** (moteur nu, sans wrapper, scénario fight, R4 simulé) : au dernier tour, phase fight
du joueur 2, tous les pools vides, aucun état fight pendant → masque entièrement vide,
`terminated=False`. MaskablePPO crashe sur masque vide.
Analyse statique concordante : SEULE `_fight_phase_complete` (fight_handlers, def ~L1867,
appelée ~L1488/1904/2408) pose `game_over` en vif — et uniquement **au sein d'un `step()`**.
Masque vide = plus aucun step légal = la complétion de phase n'est jamais déclenchée.
⚠️ `_advance_to_next_player` (w40k_core ~L5427) est du CODE MORT en production (aucun appelant
hors `test_engine_turn_loop.py`, vérifié par grep) — ne PAS s'appuyer dessus pour le fix.
Nuance config : la limite de tours existe en deux endroits — `max_turns` (game_config.json L14)
et `max_turns_per_episode` (training config) ; clarifier en T5 lequel fait foi en moteur nu.
Dans la pile réelle, ce cas est censé être absorbé par le "WAIT forcé" du wrapper
([env_wrappers.py:427-436](../../ai/env_wrappers.py#L427-L436)) — actuellement cassé par R5. **À revalider après R5** : si le
deadlock persiste à travers le wrapper, corriger la root cause côté moteur (la complétion de la
phase fight du dernier tour doit déclencher la fin d'épisode sans exiger une action illégale),
pas en injectant des actions bidon.

### R8 — Interface agent aveugle aux nouvelles règles (non bloquant pour Phase A)
Vérifié par lecture concordante :
- **Niveaux** : aucune feature d'élévation dans l'observation (ni 108 ni 357) ; l'agent subit le
  coût de descente §13.06 (retranché du budget rigide, [shared_utils.py:3760-3763](../../engine/phase_handlers/shared_utils.py#L3760-L3763)) sans pouvoir
  le percevoir ; il ne peut pas monter (commentaire moteur : "l'IA directionnelle 2D ne monte
  pas", même bloc). Le moteur, lui, gère montée/descente (`_model_climb_reachable_floor_cells`
  [movement_handlers.py:2889](../../engine/phase_handlers/movement_handlers.py#L2889), `reachable_multilevel_field`
  [engine/phase_handlers/geodesic_move.py:148](../../engine/phase_handlers/geodesic_move.py#L148)).
- **Pivot/perModelMove** : résolus automatiquement par le moteur (plan rigide) — aucun point de
  décision agent. Légal règles (un placement légal parmi d'autres), sous-optimal seulement.
- **Fight V11** : action 25 = pile-in + déclaration + résolution + consolidation auto
  (`_ai_select_pile_in_destination` fight_handlers.py:1686, `_ai_select_fight_target` L1725,
  `_ai_select_consolidation_destination` L1436). Légal, choix internes non pilotés par la policy.
- **LoS/engagement 3D** : gate vertical implémenté ([spatial_relations.py:143-231](../../engine/spatial_relations.py#L143-L231)) mais le module
  lève lui-même "câblage incomplet" si les données verticales manquent (L186-189, chantier 4) ;
  l'observation utilise une `los_topology` 2D "legacy boards" (observation_builder.py:741).
  → Le chantier LoS 3D (Documentation projet "Chantier 5") est un PRÉREQUIS règles pour le tir
  multi-niveaux ; le training Phase A n'en dépend pas tant que les scénarios d'entraînement
  restent mono-niveau, mais la Phase B avec terrains à étages OUI. Vérifier l'état du chantier
  avant d'activer des terrains à étages en training.

### Notes non bloquantes (à traiter en T6)
- `active_shooting_unit` : cycle de vie sain uniquement pour le flux PvP/PvE ; ne pas l'activer
  en gym (cf. R4 ⚠️).
- `ai/target_selector.py` : orphelin (importé seulement par son test unitaire).
- Docs périmées : AI_OBSERVATION.md décrit 357 floats, AI_TRAINING.md 355 — aucun ne décrit le
  pipeline squad 108 actif ; `justification` de la config dit 31 au lieu de 41. Les snapshots
  `BEST_CoreAgent_training_config.json` (obs 355) sont incompatibles avec le code actuel
  (`build_observation` exige 357, [observation_builder.py:1094-1097](../../engine/observation_builder.py#L1094-L1097)).

## 4. Décisions de design imposées

1. **Phase A à interface constante** : on garde `Discrete(41)` / `Box(108)`. Aucun ancien modèle
   n'est réutilisable de toute façon (layout obs squad + VecNormalize stats) → tout run se fait
   avec `--new`. Ne jamais écraser les zips existants (protégés).
2. **Source de vérité unique "joueur programmatique"** : le prédicat "ce joueur est piloté par la
   machine (auto-résolution)" doit exister en UN seul endroit, consultable depuis game_state
   (le flag `gym_training_mode` y est déjà copié, [w40k_core.py:491](../../engine/w40k_core.py#L491)/1011). Les QUATRE prédicats
   recensés en R4 (`W40KEngine._is_player_human`, `_target_defender_is_ai`,
   `_is_ai_controlled_fight_unit`, `_is_ai_controlled_shooting_unit`) doivent s'appuyer dessus.
   Interdit de dupliquer le check. ⚠️ La bascule gym ne doit s'appliquer qu'aux décisions
   d'ALLOCATION/résolution, pas aux mécanismes d'auto-activation type `active_shooting_unit`
   (cf. ⚠️ R4) : auditer chaque site d'appel avant de brancher le prédicat unique.
3. **Plus aucun ID d'action littéral dans ai/** : importer les constantes depuis
   `engine/macro_intents.py`. État réel : **AUCUNE constante d'action n'existe** — le mapping
   n'est qu'en commentaire (L9-18) ; seuls `INTENT_*`, `MAX_OBJECTIVES`, `BASE_ZONE_INTENT`,
   `TOTAL_ACTION_SIZE` sont définis. TOUT est donc à créer : `ACTION_WAIT = 18`,
   `SHOOT_SLOT_BASE = 19`, bases move/advance/fallback, `ACTION_CHARGE = 24`,
   `ACTION_FIGHT = 25`, `DEPLOY_SLOTS = range(4, 9)`. Un littéral d'action dans ai/ = bug de
   revue.
4. **Scénarios : référence de board explicite** — les scénarios d'agent restent sous
   `config/agents/<agent>/scenarios/` (banque par agent, rosters aléatoires) mais déclarent
   `"board_ref": "44x60x5"`. Le résolveur ([game_state.py:1646](../../engine/game_state.py#L1646), 1437, 1496) accepte alors :
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
     ([game_state.py:1026-1057](../../engine/game_state.py#L1026-L1057)) ; trois formes supportées : `"training_random"` (tirage
     dans `config/agents/<agent_key>/rosters/<scale>/training/agent_training_roster*.json`),
     ref explicite `"training/<fichier>.json"`, ou **liste de refs** → `rng.choice`
     ([game_state.py:1176-1186](../../engine/game_state.py#L1176-L1186)) ;
   - **voie retenue** : dossier `config/agents/<NouvelAgent>/rosters/<scale>/training/` ne
     contenant QUE les 2 fichiers (pattern `agent_training_roster*.json` obligatoire, clé
     interne `roster_id` requise) + `"agent_roster_ref": "training_random"` dans les scénarios
     → tirage 50/50 par épisode ;
   - `config/agents/_p2_rosters/` est PARTAGÉ entre agents (pool de tirage
     `150pts/training/` = 151 fichiers ; le dossier 150pts en contient bien plus, holdouts
     inclus) : si les 2 rosters incluent l'adversaire, restreindre `opponent_roster_ref`
     (ref explicite ou liste) — sinon P2 continue de tirer dans toute la banque ;
   - désactiver `roster_pool_schedule` dans la training config
     (`_filter_training_roster_candidates`, game_state ~L1322-1393) : le filtre progressif
     swarm/troop/elite peut vider un pool de 2 fichiers → `ValueError
     "roster_pool_schedule produced zero eligible training rosters"` (~L1422-1426).
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
     [step_logger.py:188-194](../../ai/step_logger.py#L188-L194)), jamais l'agrégé seul (critère T6.3 à lire par-roster).

## 5. Tranches d'implémentation

Chaque tranche se termine par sa validation (section 6) AVANT de passer à la suivante.

### T1 — Fixes moteur neutres (R4, R6) — ✅ FAIT (2026-07-15)

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
   (~L3627-3628) ET `_charge_reverse_goal_bfs_for_eligibility` (~L825-826).
2. **R4** : introduire un prédicat unique (proposé : `is_programmatic_defender(game_state,
   target_sid)` dans shared_utils) : renvoie True si `game_state.get("gym_training_mode")` est
   True, sinon comportement actuel (player_types, erreurs explicites conservées). Sites à
   brancher — inventaire vérifié :
   - `SHOOT_CTX.auto_decider = _target_defender_is_ai` (shared_utils ~L113), consommé par
     `_manual_allocation_step` (~L6212, L6242) ;
   - `FIGHT_CTX.auto_decider = _fight_auto_defender` (fight_handlers ~L5728), les checks
     `defender_human` du flux fight (~L5425, L5450, L6150, L6184), ET les deux gardes
     `RuntimeError "allocation ... non terminee en auto"` (`squad_shoot`/`squad_fight` dans
     w40k_core + garde jumelle fight_handlers ~L3352-3357) qui doivent cesser de crasher une
     fois le prédicat branché ;
   - `HAZARD_CTX` (shared_utils ~L6423-6437) n'a pas d'`auto_decider` : le hazard est DÉJÀ
     gym-aware au call-site (`auto_resolve = gym_training_mode`, [w40k_core.py:2634](../../engine/w40k_core.py#L2634)) sans lire
     player_types — rien à faire en gym ; corollaire à vérifier : en PvE, un défenseur IA
     passerait par l'allocation hazard MANUELLE ;
   - chemins `squad_shoot_validate` ([w40k_core.py:4685](../../engine/w40k_core.py#L4685)) et prompts rule-choice
     ([w40k_core.py:2527](../../engine/w40k_core.py#L2527)) — déjà sur `_is_player_human`, vérifier qu'ils basculent sur le
     prédicat unique sans changement de comportement PvP.
   Ne PAS toucher `player_types`. Ne PAS brancher `_is_ai_controlled_shooting_unit`
   (auto-activation) sur la bascule gym (cf. ⚠️ R4).
   Ajouter au smoke test T1 un scénario garantissant des **pertes en mêlée** (le chemin
   FIGHT_CTX n'a jamais été exercé en gym, cf. R4).
3. Vérification de non-régression PvP : `python3 -m pytest tests/ -x -q` (suite existante,
   1152 tests collectés au 2026-07-14) + une partie PvP manuelle rapide côté utilisateur.

### T2 — Migration wrappers + bots vers l'espace squad (R5)
1. Ajouter dans [macro_intents.py](../../engine/macro_intents.py) les constantes nommées manquantes (WAIT=18, bases des
   plages move/advance/fallback/shoot, CHARGE=24, FIGHT=25, DEPLOY_SLOTS=range(4,9)) et les
   utiliser partout dans `ai/env_wrappers.py` et `ai/evaluation_bots.py` (supprimer
   `WAIT_ACTION = 11`, les littéraux 11/12, les plages 4-8 hors déploiement ; remplacer aussi
   les `return 18` déjà corrects mais en dur — L556, L854, L1172, L1188 — par la constante).
2. **Auditer la logique de chaque bot phase par phase** contre le mapping actuel : la sélection
   "shoot" doit itérer les slots 19-23 (slots ennemis via `get_enemy_slot_mapping`), "charge"=24,
   "fight"=25, les moves par direction 0-5/6-11/12-17. Les bots choisissent des actions dans le
   masque : tout choix hors masque = erreur explicite (comportement existant à préserver).
3. `SelfPlayWrapper` : mêmes corrections (WAIT forcé, détection "pool empty").
4. Auditer `ai/train.py`, `ai/bot_evaluation.py` ET `ai/game_replay_logger.py` (layout 8
   actions, L774-828) pour les mêmes littéraux périmés — y compris les dicts de poids
   `{4: 0.50, ...}` d'evaluation_bots (6 occurrences) et les `return 10/4`.

### T3 — Chemins board + config training (R1, R2)
1. **R2** : remplacer la reconstruction `{cols}x{rows}` de `_list_available_board_refs`
   ([train.py:586-591](../../ai/train.py#L586-L591)) par `config_loader.get_board_dir()`. Même motif déjà repéré ailleurs :
   `ai/analyzer.py:224` (et `analyzer_avant_refactor.py:224`) reconstruisent
   `config/board/{cols}x{rows}/objectives`. Greper `ai/` et `scripts/` pour le solde.
1bis. **train.py émet encore `objectives_ref`** : `_load_scenario_objectives_ref`
   ([train.py:562-577](../../ai/train.py#L562-L577)) et le sampler `train_objectives_ref_weights` (~L873, L887-893)
   expansent des refs `objectives-*.json` — clé que le moteur REJETTE (game_state:320-329).
   Cette branche doit être supprimée/migrée vers les terrains (T4), sinon le tirage de
   scénarios de train.py casse après migration.
1ter. **Migrer la training config et le chemin d'éval** (R3-f/R3-g) : purger
   `train_wall_ref_weights`/`eval_wall_refs`/`eval_objectives_refs` des refs inexistantes
   dans les 5 phases de `CoreAgent_training_config.json`, et migrer
   `_materialize_eval_scenario_refs` (bot_evaluation.py:59-98, émission d'`objectives_ref`)
   vers le contrat terrain — les callbacks d'éval train.py en dépendent.
2. **R1** : décision de config (pas de code) : soit ajouter une phase `default` pointant vers la
   config x1 courante dans `CoreAgent_training_config.json`, soit rendre `--training-config`
   obligatoire (erreur explicite listant les phases disponibles). Recommandé : la seconde (pas
   d'alias silencieux). À valider avec l'utilisateur au checkpoint T3.
3. La voie legacy `config/deployment/{cols}x{rows}/` ([game_state.py:436-440](../../engine/game_state.py#L436-L440)) : si la banque
   migrée (T4) n'utilise plus `deployment_zone` nommée, ne pas y toucher ; sinon fournir les
   fichiers de zones pour `220x300` (décision en T4).

### T4 — Migration de la banque de scénarios (R3)
1. Implémenter la clé **`board_ref`** dans le résolveur (décision de design n°4) :
   `_resolve_shared_config_path`, `_load_shared_walls_from_ref` (branche "random") et
   `_read_terrain_file` ([game_state.py:1646](../../engine/game_state.py#L1646), 1437, 1496). Erreur explicite si ni parent
   `scenario/` ni `board_ref`.
2. Créer les **terrains d'entraînement** sous `config/board/44x60x5/terrain/` : chaque terrain
   porte objectifs (`"objective": true`) et `deployment_zones` (polygones J1/J2). Point de départ:
   dériver des terrains existants (`terrain-mc1.json`, `terrain-floors-test.json`) et des
   anciennes refs objectives/walls de la banque. Phase A : terrains PLATS uniquement (pas
   d'étages) — les étages arrivent en Phase B (cf. R8/LoS 3D).
   ⚠️ Piège vérifié : un terrain SANS aucune area `"objective": true` donne une liste
   d'objectifs VIDE en silence (game_state ~L376-381) — le script de migration doit valider
   ≥ 1 objectif par terrain produit.
3. Migrer les **61 scénarios** de la banque (training 30 + training_benchmark 4,
   holdout_regular 10, holdout_hard 10 + matchups 7) : supprimer `objectives_ref`, remplacer
   `deployment_zone`/`wall_ref` par `terrain_ref` (+ `wall_ref` réel encore supporté) +
   `board_ref`. Statuer sur `scenarios/training_save/` (30 JSONs) : migrer ou archiver.
   Écrire un script de migration dans `scripts/` (one-shot, vérifiable) plutôt qu'une édition
   manuelle. Les refs `"random"` (walls/terrain)
   doivent piocher dans le board résolu — vérifier le support côté train.py
   (`_expand_random_ref_weights`, [train.py:603](../../ai/train.py#L603)) après le fix R2.
4. Outillage impacté — état vérifié :
   - `scripts/build_holdout_benchmark.py` **ÉMET les clés legacy** (`deployment_zone: "hammer"`
     L110, `objectives_ref` L118/246/254) → à migrer, pas seulement à vérifier ;
   - `ai/scenario_manager.py` : utilise des `deployment_zones` avec clés joueur **0/1** alors
     que les terrains modernes utilisent **"1"/"2"** → incompatibilité à résoudre ;
   - `scripts/rebalance_holdout_hard_scenarios.py`, `scripts/build_dynamic_rosters.py` : aucune
     clé legacy détectée, re-vérifier après migration.

### T5 — Boucle complète et fin d'épisode (R7)
1. Rejouer le smoke test pile complète (annexe A) après T1+T2 : 10 épisodes aléatoires masqués
   doivent se terminer (`terminated=True`, winner déterminé), zéro masque vide, zéro exception.
2. Si le deadlock R7 persiste : corriger côté moteur la complétion de phase fight au dernier
   tour, via le SEUL chemin vif : `_fight_phase_complete` (fight_handlers, def ~1867) doit
   aboutir à `terminated` sans exiger une action supplémentaire quand le pool est vide.
   `_advance_to_next_player` (w40k_core ~5427) est mort en production (cf. R7) — ne pas s'en
   servir ; statuer sur sa suppression. Interdit de résoudre par injection d'action côté
   wrapper.
3. Étendre le smoke test aux scénarios migrés (T4), sièges p1/p2/random, et à un scénario
   contenant Carnifex/Psychophage (validation R6).

### T6 — Entraînement de validation + hygiène
1. `python3 ai/train.py --agent CoreAgent --scenario bot --new --training-config x1_debug --step`
   → run court complet sans erreur ; puis `ai/analyzer.py` sur les résultats + replay.
2. Vérifier les métriques TensorBoard (cf. mémoire projet : métriques PPO manquantes dans
   0_critical — diagnostiquer si toujours le cas).
3. Baseline bots : l'agent frais doit apprendre à battre RandomBot/GreedyBot sur quelques
   scénarios avant tout tuning (critère de succès : stabilité multi-scénarios, pas un pic).
4. Hygiène (ne bloque pas) : corriger la `justification` (31→41) de la config ; mettre à jour
   AI_OBSERVATION.md/AI_TRAINING.md (pipeline squad 108) ; statuer sur `ai/target_selector.py`
   (mort → suppression à valider utilisateur) ; marquer les configs snapshot obs 355 comme
   archives.

### Phase B (après T6 ET Phase A' — section 8 — validés) — Observation niveaux
Spec à figer à ce moment-là, principes déjà actés :
- Ajouter aux 7 features par-figurine un `level` normalisé (source : champ `level` de la
  figurine, posé game_state.py ~L162) et aux 9 features par slot ennemi le niveau de l'ancre ;
  exposer aussi un signal de coût de descente pour l'activation courante
  (`squad_descent_penalty_subhex`, movement_handlers.py:276). Toute modif de layout change
  `obs_size` (config + constantes `SQUAD_*` observation_builder ~L1245-1251) → nouveau modèle from
  scratch, mettre à jour la `justification` en même temps.
- Terrains d'entraînement à étages : SEULEMENT après vérification de l'état du chantier LoS 3D
  (spatial_relations.py:186-189 "câblage incomplet") — sinon l'agent apprendrait sur un tir
  non conforme aux règles.
- Action "monter" (nouveau slot) = Phase C, décision utilisateur explicite requise.

## 6. Critères d'acceptation

| Tranche | Critère (tous vérifiables par commande) |
|---|---|
| T1 | Suite de tests verte ; smoke test moteur nu (annexe A) passe la phase shoot, la phase charge avec Carnifex ET une phase fight avec pertes allouées (chemin FIGHT_CTX) sans exception |
| T2 | Zéro littéral d'action dans ai/. Le grep n'est qu'une HEURISTIQUE (3 versions successives ont toutes eu des trous : `== 11`, `X in valid_actions`, listes, `return 10/12/18`, dicts de poids `{4: 0.50,...}`, `action % 8`, sous-dossiers, + faux positifs légitimes dans train.py) — le critère réel est un AUDIT MANUEL exhaustif des 4 fichiers `evaluation_bots.py`, `env_wrappers.py`, `bot_evaluation.py`, `game_replay_logger.py` : chaque comparaison/émission d'entier d'action passe par une constante de macro_intents. Grep de contrôle : `grep -rnE "(step\([0-9]+\)|WAIT_ACTION|==\s*[0-9]+\b|\b[0-9]+ in valid_actions|return 1[028]\b|% 8)" ai/` avec revue de chaque hit. Smoke test pile complète avance au-delà du premier WAIT forcé |
| T3 | `train.py --step --training-config x1_debug` dépasse la résolution walls/objectives sans FileNotFoundError |
| T4 | Les 61 scénarios se chargent (`W40KEngine(scenario_file=...)` + reset, script de balayage) ; zéro clé legacy ; sort de training_save/ statué |
| T5 | 10 épisodes aléatoires masqués terminés sur ≥3 scénarios × sièges p1/p2 ; zéro masque vide |
| T6 | Run `--new` court complet + analyzer + replay OK ; win-rate vs RandomBot en progression |

## 7. Annexe A — Smoke tests de référence

Deux scripts éprouvés pendant l'audit (à recréer dans `scripts/` ou en scratch ; ne pas
committer les monkeypatches, ils simulent les fixes T1) :

1. **Moteur nu** : `W40KEngine(gym_training_mode=True, scenario_file=<board scenario>)`,
   boucle `reset()` puis `step(choice(flatnonzero(get_action_mask())))` jusqu'à
   terminated/masque vide, 3 seeds. Diagnostic à imprimer si masque vide : phase, tour, joueur,
   pools `*_activation_pool`, états `pending_*`/`fight_*`.
2. **Pile complète** : `Monitor(BotControlledEnv(ActionMasker(engine), GreedyBot(0.15),
   registry, agent_seat_mode="random", global_seed=...))` — miroir exact de
   [train.py:1777-1791](../../ai/train.py#L1777-L1791).

Résultats d'audit (2026-07-14) : moteur nu OK jusqu'au tour 5 avec fixes R4 simulés (deadlock
R7 en fin de partie) ; pile complète bloquée immédiatement par R5 (`step(11)`).
Réserve : seul le décideur tir était patché — le chemin d'allocation de pertes en mêlée
(FIGHT_CTX) n'a pas été prouvé par ce smoke test (cf. R4/T1).

## 8. Phase A' — Toutes les règles implémentées dans le training (P1-P5)

Décision utilisateur (2026-07-14) : l'agent doit s'entraîner sur TOUTES les règles déjà
implémentées, et chaque fois que les règles laissent un choix au joueur, c'est l'agent qui
choisit. Périmètre strict : règles présentes dans le moteur — on n'entraîne sur AUCUNE feature
absente (stratagèmes, CP, FNP, transports, etc. restent hors scope). Prérequis : Phase A
(T1-T6) validée.

### 8.1 Constat d'architecture (audit 2026-07-14, vérifié par lecture)

Il existe DEUX moteurs de résolution d'attaque :
- **Chemin vif** (PvP ET gym) : résolution squad — `_manual_roll_intent`
  ([shared_utils.py:5905-5993](../../engine/phase_handlers/shared_utils.py#L5905-L5993)) + `_resolve_one_manual_wound` (L6038-6114).
- **Code mort** : `_attack_sequence_rng` (shooting_handlers, ~L5820-6003) — zéro site
  d'appel vif (utilisé seulement par des tests via monkeypatch) ; les branches `execute_action`
  qui y menaient lèvent des RuntimeError « squad ... expected » (shoot ~L5510-5529,
  activate_unit ~L5519-5523, select_weapon ~L5534-5538 « squad_select_weapon expected »,
  left_click ~L5589-5593, invalid ~L5627-5631) ; état orphelin `_rapid_fire_*` dans
  w40k_core (~L1055-1061, L2055-2061) et sites shooting_handlers associés (~L230, L947-953,
  L2500-2506, L4912-4925, L5689-5696). NB : w40k_core ~L3561 est un simple champ de LOG
  `rapid_fire_bonus_shot`, pas de l'état — le grep `_rapid_fire_` ne l'attrape pas.
- `WeaponRulesApplier.apply_rules` est un placeholder pass-through ([rules.py:279-327](../../engine/weapons/rules.py#L279-L327)) :
  les règles d'armes sont validées/parsées mais PAS appliquées par ce système.

Conséquence : toute règle implémentée uniquement dans `_attack_sequence_rng` est inactive
partout (gym ET PvP).

### 8.2 P1 — Parité de résolution : réimplémentation depuis les PDFs, puis suppression du mort

⚠️ **Le code mort N'EST PAS une spec à porter** — vérifié contre les PDFs du projet (24 Core
abilities lu) : il implémente une AUTRE édition des règles. Il ne sert que d'indice de point
d'insertion. Chaque règle se réimplémente depuis le PDF du projet.

Règles à implémenter dans le chemin vif (absentes du vif, présentes dans le mort sous forme
non conforme) — descriptions = PDF projet :

| Règle (PDF projet) | Indice mort | Point d'insertion vif |
|---|---|---|
| HEAVY (24.16) : +1 to hit si unité unengaged ET pas posée sur la table ce tour ET aucun modèle bougé de plus de 3" ce tour — PAS « remained stationary » | ~:5869-5880 | `_manual_roll_intent` (seuil de touche) |
| HAZARDOUS (24.15) : après que l'unité a résolu TOUTES ses attaques, un hazard roll (06.03) PAR ARME hazardous sélectionnée — pas un jet par attaque. NB : `roll_hazard_for_unit` (vif, shared_utils ~3410, câblé au move via w40k_core ~2635) implémente déjà 06.03 → réutiliser | ~:5887, :5916 | fin d'activation tir/fight |
| IGNORES_COVER : 17 armes la déclarent, la feature est OBSERVÉE, mais `_cover_worsened_bs` (shared_utils ~5745) ne la vérifie jamais — le malus de couvert est infligé À TORT à ces armes (gym ET PvP ; le commentaire w40k_core ~4380 « appliqué côté frontend » est faux pour la résolution backend) | — (jamais implémentée) | `_cover_worsened_bs` (bypass si arme IGNORES_COVER) |
| DEVASTATING_WOUNDS (24.10) : critical wound → la séquence de CETTE attaque s'arrête, la cible subit D blessures mortelles APRÈS les dégâts normaux, max 1 figurine endommagée par critical wound — PAS « save sauté » (le mort n'est pas conforme non plus) | ~:5970-5980 | `_resolve_one_manual_wound` + moteur MW |
| RAPID_FIRE : attaques bonus à mi-portée (conforme PDF) | état w40k_core ~:1055-1061 | `_manual_roll_intent` (calcul NB à la déclaration, comme Blast) |
| closest_target_penetration (règle projet unit_rules.json) : AP+1 sur la cible éligible la plus proche | ~:5836-5840 | `_manual_roll_intent` (AP effectif) |
| reroll_1_towound au TIR | ~:5935-5940 | `_manual_roll_intent` — déjà vif en fight (`_manual_roll_fight_intent`) : asymétrie tir/fight à combler |
| reroll_towound_target_on_objective au TIR | ~:5945-5957 | idem |

Méthode : une règle = une tranche (PDF relu AVANT implémentation + test unitaire dédié).
⚠️ Le chemin squad est partagé PvP/gym : chaque implémentation corrige AUSSI le PvP — c'est
voulu (conformité accrue partout), à annoncer à l'utilisateur (équilibre de jeu modifié).

Cas particulier : **`reroll_charge`** est déclaré dans `config/unit_rules.json` mais
n'existe NULLE PART dans le code (grep zéro, ni vif ni mort). À statuer : implémenter
(charge_handlers, reroll du 2D6) ou retirer de la config.

Déjà vifs (rien à porter) : charge_impact (règle d'unité D6 4+ → 1 MW, `_apply_charge_impact`
~L4551), charge/shoot_after_advance/flee, move_after_shooting, reactive_move,
**Desperate Escape (09.07)**, les 4 rerolls de fight, Blast, Pistol (10.06), couvert 13.08
(mécanique conforme PDF SAUF le cas IGNORES_COVER ci-dessus), obscuring, invuln, allocation
05.03/05.04, T du bodyguard 19.02.
NB : `closest_target_penetration` apparaît aussi comme feature d'OBSERVATION
(observation_builder) — actuellement observée sans effet en résolution.

**Périmètre à statuer (utilisateur)** : ~10 règles d'armes sont déclarées dans les armories ET
observées (observation_builder ~65-92) mais appliquées NULLE PART (ni vif ni mort) : TORRENT,
TWIN_LINKED, SUSTAINED_HITS, LETHAL_HITS, MELTA, ANTI_*, INDIRECT_FIRE, EXTRA_ATTACKS,
PSYCHIC. Elles sont hors périmètre A' (« règles présentes dans le moteur ») — MAIS
IGNORES_COVER fait exception (intégrée au tableau P1 ci-dessus) car son absence rend FAUSSE
une règle implémentée (le couvert). Pour les autres : soit les implémenter (extension de
périmètre à valider), soit retirer leurs canaux d'observation (bruit pur pour PPO), jamais
le statu quo silencieux.

Suppression du code mort (fin de P1) : `_attack_sequence_rng` (~5820-6003), les branches
`squad path expected` (shoot, left_click, select_weapon, invalid — cf. 8.1), l'état
`_rapid_fire_*` de w40k_core (~1055-1061, 2055-2061) ET ses sites shooting_handlers
(~L230, 947-953, 2500-2506, 4912-4925, 5689-5696), le champ de log `rapid_fire_bonus_shot`
(w40k_core ~3561, non attrapé par le grep), et les tests qui monkeypatchent le mort.
Critère : grep `_attack_sequence_rng|_rapid_fire_|rapid_fire_bonus_shot` vide (hors nouvelle
implémentation vive) + suite verte.

### 8.3 P2 — Mécanisme générique « décision agent »

Un seul mécanisme pour tous les choix joueur, au lieu d'actions ad hoc par décision :
- quand le moteur atteint un point de choix joueur en gym, au lieu d'appeler une heuristique
  `_ai_select_*`, il pousse un `pending_agent_decision` (type + liste ORDONNÉE et STABLE de
  ≤ K candidats) ;
- le masque expose K actions génériques `CHOICE_0..K-1` ; l'observation gagne un bloc
  « contexte de décision » (type one-hot + features par candidat) ;
- l'agent choisit, le moteur applique. **Miroir exact des prompts PvP `waiting_for_player`**
  (même sémantique, consommateur différent) — conforme à la règle projet « le flux gym copie
  le flux PvP » ;
- les heuristiques `_ai_select_*` sont CONSERVÉES pour le bot adversaire (GreedyBot) uniquement.

Impact interface : action_space 41 → 41+K (recommandé K=6, aligné sur les 6 slots figurines ;
actions dédiées plutôt que surcharge des slots tir 19-23, pour la lisibilité du masque) ;
obs_size change → nouveau modèle from scratch (`--new`, déjà acté). Mettre à jour la
`justification` de la config en même temps.

### 8.4 P3 — Branchement décision par décision (une tranche = une décision + validation)

⚠️ Les sites à remplacer sont ceux du PIPELINE VIF gym (vérifiés par contre-review), pas les
heuristiques `_ai_select_*` qui ne sont que des fallbacks/chemins legacy.

Ordre par valeur tactique :
0. **Prompts rule-choice** (le plus urgent — pseudo-décision aléatoire structurelle) : en gym,
   `_select_ai_rule_choice_option` choisit par `raw_action_int % len(options)`
   ([w40k_core.py:2494](../../engine/w40k_core.py#L2494)) — l'agent « choisit » via une action émise pour tout autre chose,
   sans voir le prompt. À remplacer par une vraie décision P2.
1. **Cible de mêlée** — le site vif est la boucle `get_best_enemy_score_for_unit` de
   `squad_fight` (w40k_core ~L4999-5011), PAS `_ai_select_fight_target` (fight_handlers ~1725,
   simple fallback quand la cible préférée est morte) ; pilote du mécanisme P2.
2. **Cible de charge** — le site vif est la même boucle de scoring dans `convert_squad_action`
   du décodeur (action_decoder ~L917-940), PAS `charge_handlers:1506` (chemin
   `convert_gym_action`, hors gym mais encore vif en PvE via pve_controller — ne pas le
   supprimer, juste ne pas le brancher).
3. **Choix de l'unité à activer** par phase — `eligible_units[0]` a 9 occurrences dans
   action_decoder ; les sites DÉCISIFS du flux vif sont dans `convert_squad_action`
   (~L837, L876), les autres sont dans la construction du masque ; le plus gros gain
   stratégique. Contrainte règles : l'ordre en fight reste borné par Fights First
   (11.04/12.04) et les pools alternés — le choix agent se fait DANS le pool légal courant.
4. **Allocation des pertes défenseur** — remplace `_select_allocation_model`
   (shared_utils ~5643) ; candidats = figurines éligibles 05.03/06.02 ; inclut l'allocation
   hazard ET l'ordre de déclaration des groupes (`declare_order`, décision défenseur 05.03,
   aujourd'hui `_auto_declared_order`).
5. **Pile-in / consolidation** — les sites vifs sont `fight_pile_in_plan`
   (shared_utils ~6708) et `squad_consolidate_plan` (~7038) appelés par `squad_fight`,
   PAS les `_ai_select_*` de fight_handlers ; candidats = top-K destinations du pool.
   NB règles : pile-in/conso sont OPTIONNELS et la consolidation a 3 modes en cascade (dont
   vers objectif) — l'espace de choix doit inclure « ne pas bouger ». ⚠️ Le site vif gym
   `squad_consolidate_plan` n'implémente que le mode (1) (docstring : option (2) « vers
   objectif » déférée) — le flux PvP (fight_handlers ~1161-1176) a la cascade complète :
   écart gym/PvP à combler quand cette tranche s'ouvre.
6. **Move-after-shooting** (destination — remplace
   `_select_move_after_shooting_destination_for_ai`, shooting_handlers ~4961) et
   **reactive_move** (accepter/décliner + destination — protocole `decline_reactive_move`
   déjà formalisé, shared_utils ~2190).
7. **FLY / Take to the skies** — déclaration binaire (aujourd'hui auto pour l'IA,
   movement_handlers ~261/271).
8. **Optionnels, à statuer utilisateur** : split-fire (en gym, l'escouade entière vise UN
   slot ; le PvP a `squad_shoot_assign` par-figurine), choix d'arme — deux régimes distincts
   en gym : RNG = `selectedRngWeaponIndex` pris tel quel (shared_utils ~4489), CC =
   auto-sélection par expected damage `_auto_select_cc_weapon_for_fig` (shared_utils ~6938,
   appel ~7016) — les deux sont des décisions joueur auto-résolues,
   déclaration multi-cibles de charge (PvP oui, gym mono-cible), placement final de charge
   (`charge_build_valid_plan`, shared_utils ~3955), déploiement (les actions 4-8 sont 5
   STRATÉGIES scorées, action_decoder ~1682-1698, pas « les 5 premiers hex » — élargir ou non).

Hors scope A' (reste auto, conforme règles car « un placement légal parmi d'autres ») :
placement par-figurine du move rigide, pivot. Montée d'étage = Phase C.

### 8.5 P4 — Observation de support

Bloc décision (P2) + features nécessaires aux choix : LoS/couvert par slot ennemi, portée
effective de l'arme active vs distance du slot, flags advanced/fell_back de l'unité active.
Les niveaux/élévation restent en Phase B (scénarios plats jusque-là).

### 8.6 P5 — Validation par tranche

Chaque tranche P3 : suite de tests verte + smoke 10 épisodes + run court `x1_debug` +
win-rate vs GreedyBot ≥ tranche précédente. Si l'ajout d'un point de décision DÉGRADE le
win-rate, la décision est mal observée ou mal récompensée → corriger avant d'empiler la
suivante. Interdits : masquer une régression en retirant silencieusement la décision.

Points de vigilance :
- l'ordre des candidats doit être déterministe et stable (sinon l'assignation de crédit PPO
  est brouillée) ;
- chaque décision ajoutée allonge l'épisode en steps → surveiller `episode_steps` vs la
  normalisation `/100` de l'observation globale ;
- les heuristiques du RewardMapper utilisées par les anciens `_ai_select_*`
  (`get_shooting_priority_reward`) peuvent devenir du reward shaping pour guider les
  nouvelles décisions — à statuer par tranche, jamais en silence. NB : un de ses deux
  consommateurs, `_ai_select_shooting_target` (shooting_handlers, def ~2093), est DÉJÀ mort
  (zéro appelant) — à inclure dans la suppression P1.
