# V11 — Rétablissement de l'entraînement de l'agent (agent rework)

Date d'audit : 2026-07-14. Tous les faits ci-dessous ont été vérifiés dans le code actuel
(lecture + exécution de smoke tests), puis contre-vérifiés par une review indépendante
(2026-07-14 soir). Chaque rupture est accompagnée de sa reproduction exacte.

**Convention d'ancrage** : l'ancre de référence est le NOM DE FONCTION ; les numéros de ligne
sont indicatifs (constaté pendant l'audit : fight_handlers.py a bougé de ~45 lignes en une
journée). Toujours re-localiser par grep du nom avant d'éditer.

---

## 0. ÉTAT AU 2026-07-19 — À LIRE EN PREMIER

> Ce bloc est le point d'entrée. Il est mis à jour à chaque session ; le reste du document est
> l'historique détaillé, dans lequel les entrées T6-x sont enfouies dans la section 5 (T6).

**LE TRAINING TOURNE (2026-07-19, après T6-h + T6-g).** La commande de repro historique passe
désormais de bout en bout :

```
python3 ai/train.py --agent CoreAgent --training-config x5_debug \
  --scenario config/agents/CoreAgent/scenarios/training/training_benchmark/scenario_training_benchmark.json \
  --new --resolution 5
```
→ 10/10 épisodes, 8 workers `SubprocVecEnv` vivants, **zéro** `execute_squad_move a échoué : …
incohérence masque/exécution`, exit 0. Idem en mono-env (`--step`, x1_debug). Les seules
exceptions résiduelles du run sont dans l'**ÉVALUATION** (`bot_evaluation`) et sont la dette
rosters connue (`roster_pool_schedule produced zero eligible training rosters`) — cf. §10.2,
c'est ce qui met les win-rates à 0.00, pas le moteur.

**Chemin critique — LES 2 FIXES SONT LIVRÉS** (détail en section 5, tranche T6) :

| # | Quoi | État |
|---|---|---|
| 1 | **T6-h** — `build_rigid_plan` translatait en OFFSET : à `dx` impair le bloc se DÉFORMAIT (mesuré : distance interne 2 → 1). Fix : translation en CUBE, miroir de `deployment_build_squad_destinations_pool`. **Deux consommateurs de translation de bloc portaient le MÊME bug et ont été alignés** : `translate_squad_to_destination` (l'écrivain du commit, partagé move/charge/fight/pile-in — le laisser en offset aurait fait committer une formation DIFFÉRENTE de celle que `validate_move_plan` avait acceptée) et `preview_hidden_models_after_move` (shooting_handlers). | ✅ FAIT — +10 tests (`test_rigid_plan_translation.py`, paramétrés `dx` pair ET impair, rouges sur le code d'avant) |
| 2 | **T6-g** — le pool BFS du move était construit sur l'ANCRE, mais `build_rigid_plan` translate TOUT le bloc sans le valider → figurines sur un mur / sur une autre escouade. Fix : **érosion morphologique** (`erode_move_pool_by_squad_block`, shared_utils), appelée dans `build_squad_move_cell_map` AVANT la projection sur la grille égocentrique. | ✅ FAIT — +6 tests (`test_move_pool_block_erosion.py`) |

**Sur l'érosion (T6-g), ce qu'il faut savoir pour la maintenir** : le prédicat de cellule est
celui de `validate_move_plan` sous `DEFAULT_MOVE_CONSTRAINTS` — bornes, murs, occupation des
autres escouades **par niveau**, ER ennemie. Ce sont les seules contraintes érodables. Les deux
autres ont été **vérifiées invariantes** par translation cube, donc déjà garanties par le pool
d'ancre : `budget_per_model` (`calculate_hex_distance` est une distance cube → la distance de
chaque figurine à son origine égale celle de l'ancre, bornée par le coût géodésique du pool) et
`require_coherency` / collision intra-plan (ne dépendent que des positions RELATIVES). Escouade
mono-figurine : l'ancre EST le bloc, le pool est déjà exact → court-circuit.

**Déjà corrigé et validé le 2026-07-19** (détail en T6-e / T6-f) : `_turn_step_limit` absent du
chemin single-scenario (T6-e, commité) ; commit de déploiement mono-ancre qui ne plaçait AUCUNE
figurine (T6-f, +10 tests, non commité).

**Suite au 2026-07-19 après T6-h/T6-g** : `9 failed, 1437 passed, 2 skipped`. Baseline vérifiée
par `git stash` : `9 failed, 1421 passed` — **mêmes 9 échecs préexistants** (rosters, cf. plus
bas), +16 = les tests des deux fixes. Zéro régression.

**Après le training** — ne PAS anticiper : **T7** (unification de la validation de déploiement,
section 5). Le déclencheur est « le training tourne » : T7 touche le masque, donc l'espace
d'action de l'agent, et exige une mesure avant/après impossible tant que rien ne tourne.

**⚠️ AVANT de lancer le premier vrai run, lire la section 10** (stratégie d'entraînement et
d'évaluation, décision utilisateur 2026-07-19). Deux points bloquants y sont établis :
- **§10.4** — toute la machinerie d'adversaires (bots pondérés + self-play `opponent_mix`)
  n'est câblée que sur `--scenario bot`. Le chemin single-scenario vectorisé (x5_debug,
  n_envs=8) tombe sur `SelfPlayWrapper(frozen_model=None)` dont le frozen n'est JAMAIS mis à
  jour (`update_frozen_model` : zéro appelant) → **P2 joue des actions ALÉATOIRES en
  permanence**. Comme `--scenario bot` est cassé (rosters), un run lancé aujourd'hui
  entraînerait contre du hasard **sans que rien ne le signale**. Même famille de divergence
  que T6-e.
- **§10.6** — le critère de succès T6 a été REMPLACÉ : l'ancien (« win-rate vs RandomBot sur
  holdout ») référence un holdout de rosters supprimé. Le holdout porte désormais sur
  l'**adversaire** (`TacticalBot`, réservé à l'évaluation), pas sur les rosters.

**État de la suite** : `tests/unit` — **9 échecs, tous préexistants et hors chemin critique** :
4 × banque de scénarios et 5 × déploiement/terrain, tous dus à des **rosters manquants ou
non résolus** (`roster_pool_schedule produced zero eligible training rosters`, fichiers de
roster holdout absents). Baseline vérifiée par `git stash` — aucune régression des fixes ci-dessus.
Ces rosters ont été supprimés VOLONTAIREMENT (commit `43eae95a`, obsolètes pré-escouades) : la
réparation n'est pas « les restaurer » mais recréer 2 rosters (SM, Orks) — cf. §10.2.

**Dettes à connaître avant de s'y remettre** :
- `--scenario bot` échoue en AMONT du moteur (roster) : utiliser `training_benchmark` pour
  reproduire, pas `bot-01`.
- Toute la banque (61 scénarios) tourne sur `terrain-mc1.json` depuis le 2026-07-19 (décision
  utilisateur : `terrain-train-01/02/03` obsolètes). mc1 porte 8 étages ; l'observation les voit
  via le canal 5 `GRID_CH_LEVEL`. ⚠️ `scripts/migrate_scenario_bank_v11.py` cycle encore sur les
  3 terrains plats — le RELANCER repointerait la banque et casserait le test de banque.
- `config/tutorial/scenario_etape*.json` ne se charge plus (`wall_ref` legacy sans `board_ref`).

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
  Détail en section 9.
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

### T2 — Migration wrappers + bots vers l'espace squad (R5) — ✅ FAIT (2026-07-15)

Réalisé : constantes nommées dans `macro_intents.py` (MOVE/ADVANCE/FALL_BACK_DIRS, ACTION_WAIT=18,
SHOOT_SLOTS=19-23, ACTION_CHARGE=24, ACTION_FIGHT=25, DEPLOY_SLOTS=4-8 — miroir de
`SQUAD_ACTION_*` de shared_utils). `evaluation_bots.py` : 8 bots migrés (helper `_first_action_in`,
`_shoot_focus_fire` sur SHOOT_SLOTS, dicts de poids déploiement via DEPLOYMENT_ACTIONS, TacticalBot
inclus) — zéro littéral d'action résiduel. `env_wrappers.py` : bug phare R5 corrigé (`step(11)` →
`ACTION_WAIT`), `return 18` et trackers diagnostiques shoot/wait migrés (BotControlledEnv +
SelfPlayWrapper). `game_replay_logger.log_action` (layout `% 8` mort + lit `self.env.controller`
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
1. **Inexactitude du rapport** : `multi_agent_trainer.py:1016` contient encore `action % 8` +
   `unit_idx = action // 8` (monkeypatch legacy de `controller.execute_gym_action`). Branche
   INERTE (gardée par `hasattr(actual_env, 'controller')`, attribut absent du moteur squad)
   mais « aucun littéral dans multi_agent_trainer » est faux — à condamner/purger comme
   `game_replay_logger.log_action` (raccroché à T6 hygiène ou T5).
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
`_materialize_scenario_with_refs` (train.py ~L642-668) conserve un paramètre `objectives_ref`
et sa branche d'émission `scenario_copy["objectives_ref"] = ...` — MORTE (l'unique appelant
~L854 ne passe que wall_ref) mais tout futur appelant réémettrait une clé rejetée par le
moteur. À purger en T4 (avec la migration) ou T6.

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

### T4 — Migration de la banque de scénarios (R3) — ✅ FAIT (2026-07-15)

Réalisé : **resolver `board_ref`** — helper `_resolve_board_dir(scenario_file, board_ref,
purpose)` dans game_state.py (seul fichier moteur touché) : parent `scenario/` (voie PvP
inchangée) OU `board_ref` → `config/board/<board_ref>/` ; erreurs explicites (absence des
deux, board inexistant, traversal), câblé dans `_resolve_shared_config_path`,
`_load_shared_walls_from_ref` (random) et `_read_terrain_file` + call-sites. **Bug moteur
corrigé au passage** : `pool_set` gardé derrière le NOM legacy `deployment_zone` → les zones
issues du terrain (voie moderne) ne peuplaient pas le pool de déploiement random/fixed
(fix neutre PvP, commenté en ~L576). **Terrains plats** `terrain-train-01/02/03.json`
(5 objectifs, deployment_zones "1"/"2", 0 étage). **Migration** :
`scripts/migrate_scenario_bank_v11.py` (idempotent) — 61 scénarios migrés (0 clé legacy,
`board_ref`+`terrain_ref`), `training_save/` (30) archivé sous `_archive_pre_v11/`.
**Outillage** : `build_holdout_benchmark.py` migré ; `scenario_manager.py` NON touché
(chemin dormant — `config/scenario_templates.json` absent → lève à la construction ; son
alignement 0/1 vs 1/2 traverse multi_agent_trainer = chantier séparé à valider).
**Balayage** : `scripts/sweep_scenario_bank_v11.py` — 61/61 chargés + reset. Tests +83.
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
`objectives_ref` mort de `_materialize_scenario_with_refs`, train.py ~L645-668) n'a PAS été
purgée en T4 → reste pour T6.

Plan d'origine (réalisé ci-dessus) :
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

### T5 — Boucle complète et fin d'épisode (R7) — ✅ FAIT (moteur nu, 2026-07-16)

Réalisé (périmètre MOTEUR NU, décision utilisateur : « smoke moteur nu avec pertes en mêlée
garanties + Carnifex en phase charge ») :

- **R7 ne se manifeste PAS en moteur nu** : `W40KEngine.get_action_mask()`
  ([w40k_core.py:5563](../../engine/w40k_core.py#L5563)) auto-avance déjà la phase fight quand ses pools sont vides
  (boucle `fight_phase_end` tant que masque vide ET pas game_over) → l'invariant
  `mask.any() or game_over` tient à CHAQUE step. Vérifié sur 3 scénarios `active` × 3 seeds +
  scénario fixe pré-engagé : zéro masque vide sans terminaison, zéro exception, toutes les
  parties se terminent (turn limit). Le fix conditionnel T5.2 sur `_fight_phase_complete`
  n'était donc PAS requis — non touché ; `_advance_to_next_player` (mort) laissé tel quel.
- **Vraie rupture bloquante en moteur nu = déploiement `active`, PAS R7 (nouvelle, hors R1-R8)** :
  `ActionDecoder._get_valid_deployment_hexes` ([action_decoder.py:961](../../engine/action_decoder.py#L961)) testait le
  chevauchement inter-unités par CELLULES (`build_occupied_positions_set`), alors que le commit
  `deployment_handlers.deploy_unit` (~L1017) le teste par CLEARANCE euclidien CONTINU
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
   `_advance_to_next_player` (w40k_core ~5427) est mort en production (cf. R7) — ne pas s'en
   servir ; statuer sur sa suppression. Interdit de résoudre par injection d'action côté
   wrapper.
3. Étendre le smoke test aux scénarios migrés (T4), sièges p1/p2/random, et à un scénario
   contenant Carnifex/Psychophage (validation R6).

### T6 — Entraînement de validation + hygiène — ⏳ EN COURS (màj 2026-07-19)

> **Bloqueurs actifs : T6-h puis T6-g** (cf. §0). T6-a→T6-f sont résolus. Les entrées ci-dessous
> sont chronologiques ; chercher `T6-g` / `T6-h` pour le chemin critique.

**Préalable levé** : le bloqueur résiduel laissé par T5 (« reset crashe avec
`agent_seat_mode="p2"/"random"` — `bot-owned eligible units with empty action mask` en fight
tour 1 ») **ne se reproduit plus**. Vérifié en miroir exact de train.py:1673-1716
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
  (`_load_scenario_wall_ref`, train.py ~L556, via `_apply_wall_ref_weighting`).
  **Cause** : `migrate_scenario_bank_v11.py` supprime délibérément `wall_ref` (docstring : « supprime
  les clés legacy … wall_ref ») — les 61 scénarios migrés sont TERRAIN-ONLY (`board_ref` +
  `terrain_ref`, vérifié : 61/61 sans `wall_ref`). Le contrat moteur rend `wall_ref` OPTIONNEL
  (`wall_hexes` XOR `wall_ref`, `terrain_ref` additif — game_state.py ~L285-314). T4 a migré la
  banque mais pas ce sampler.
  **Fix** : `_load_scenario_wall_ref` renvoie `Optional[str]` — `None` quand la clé est ABSENTE
  (état légitime du contrat, pas une valeur par défaut masquant une erreur) ; une clé présente
  reste strictement validée (erreur explicite si vide/non-string). `None` traverse
  `_apply_wall_ref_weighting` sans override (poids `"default"` = « garde les murs du scénario »,
  ~L853) → aucun `wall_ref` injecté.

- **T6-b — `--step` était un no-op SILENCIEUX (bloque analyzer + replay)**
  **Repro** : le run affiche « 📝 Step logging enabled » puis « ✅ StepLogger connected », et
  `step.log` reste réduit à son en-tête (7 lignes) après 20 min d'entraînement.
  **DEUX causes indépendantes, les deux corrigées** :
  1. *Le StepLogger n'est branché que sur la branche mono-env* (`if step_logger:
     base_env.step_logger = step_logger`) ; les **trois** branches vectorisées construisent leurs
     envs avec `step_logger_enabled=False`. Avec `n_envs=48` (x1_debug), `--step` ne pouvait rien
     produire. Le code forçait déjà `n_envs=1` pour `--replay`/`--convert-steplog` (~L1326) mais
     PAS pour `--step`. → helper unique `_resolve_n_envs_for_step_logging` (train.py ~L571) branché
     aux **3** sites de résolution de `n_envs` (~L1354, ~L1665, ~L2129) : force l'env unique ET le
     DIT. Factorisé volontairement — trois gardes dupliqués sont exactement le motif de migration
     partielle qui a produit R5. ⚠️ Piège vérifié : les 3 sites impriment le MÊME message
     « 🚀 Creating N parallel environments » — ne pas se fier au log pour identifier le site actif
     (`--scenario bot` passe par `train_with_scenario_rotation`, site ~L2129).
  2. *Bug latent : l'env est RECRÉÉ sans reconnecter le StepLogger* (train.py ~L2637-2651,
     « For n_envs==1: recreate env with frozen model for self-play »). Ce second `base_env` reçoit
     `_metrics_tracker` mais jamais `step_logger` → le run journalisait « StepLogger connected »
     pour un env aussitôt jeté, puis s'entraînait sur un moteur MUET. Chemin exigeant `n_envs==1`
     (config = 48) → jamais emprunté, donc jamais vu. **Révélé par le fix (1).**
     → reconnexion en miroir de ~L2377.
  ⚠️ `StepLogger.log_episode_start` avale toute exception (`except Exception: print("⚠️ Episode
  start logging error")`, step_logger.py ~L254) — un step.log vide peut donc masquer une erreur.
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
  échouant sur l'ancien code). Détail : `Implémenté/bug_squad_fight_mask_mismatch.md`.
  ⚠️ **Impact sur le plan §9.4** : le site vif de la cible de mêlée a changé → cf. §9.4 point 1.

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
    make one additional pile-in move »). Spec complète : `A_faire/overrun.md`.
  - **Mismatch cellules/clearance du BFS pile-in/conso** — mesuré 1102 ancres sur 72857 ; fix
    écrit, mesuré (0/71755 après, perf 2m01→1m33), puis **REVERTÉ** : `fight_handlers` est partagé
    et le changement n'est pas neutre PvP. Ne concerne que du code par-ancre condamné → priorité
    basse. Détail + mesures : `A_faire/bug_pile_in_bfs_clearance_mismatch.md`.

- **T6-e — `_turn_step_limit` absent sur le chemin single-scenario (BLOQUANT, crash immédiat) —
  ✅ CORRIGÉ (2026-07-19)**
  **Repro** : `train.py --agent CoreAgent --training-config x5_debug --scenario <fichier.json>
  --new --resolution 5` → `ConfigurationError: Required key '_turn_step_limit' is missing from
  mapping` dans `setup_callbacks` ([train.py:3096](../../ai/train.py#L3096)).
  **Cause** (même famille que T6-a/T6-b : migration partielle d'un chemin de train.py) :
  `training_config["_turn_step_limit"]` n'était écrit que par DEUX chemins — la rotation de
  scénarios (`train_with_scenario_rotation`, bloc inline de calcul du budget) et MacroController
  ([train.py:4786](../../ai/train.py#L4786), relevé sur son propre moteur). Le chemin
  **single-scenario** (`--scenario <fichier>` → `create_multi_agent_model` → `setup_callbacks`)
  ne l'écrivait jamais, alors que TROIS lecteurs le `require_key` :
  [train.py:3096](../../ai/train.py#L3096), [train.py:3469](../../ai/train.py#L3469),
  [multi_agent_trainer.py:556](../../ai/multi_agent_trainer.py#L556). Crash systématique, quel
  que soit le scénario.
  **Fix** : le bloc inline de la rotation est extrait en helper
  `resolve_turn_step_limit(scenario_files, training_config, use_bots, log)`
  ([train.py:2102](../../ai/train.py#L2102)) — MÊME formule (`compute_turn_step_limit` sur le
  scénario au max de figurines, probe des sièges p1/p2/random si `use_bots`) — appelé par les
  deux chemins : rotation ([train.py:2302](../../ai/train.py#L2302)) et single-scenario
  ([train.py:1757](../../ai/train.py#L1757), `use_bots` dérivé de « bot » dans le nom du
  scénario, miroir du choix `BotControlledEnv` ~L1830). Factorisation volontaire : deux calculs
  dupliqués = le motif exact qui a produit R5 et T6-a. Code mort supprimé au passage dans le
  bloc extrait (`num_phases`/import `GAME_PHASES`, calculé et jamais lu).

- **T6-f — Commit de déploiement `deploy_unit` mono-ancre : `models_cache` JAMAIS écrit
  (BLOQUANT gym, crash DIFFÉRÉ en phase move ; touche AUSSI des chemins PvP) — ❌ À FAIRE
  (constaté 2026-07-19)**
  **Rayon (vérifié par lecture, conséquence runtime démontrée côté gym seulement)** : le commit
  fautif est PARTAGÉ — (a) gym via l'action decoder ; (b) auto-déploiement P2 du tutoriel
  ([api_server.py:2255](../../services/api_server.py#L2255)) ; (c) drag mono-socle PvP encore
  actif quand `deployment_type != "active"` (`handleDeployUnit`,
  [useEngineAPI.ts:5512](../../frontend/src/hooks/useEngineAPI.ts#L5512), cf.
  [BoardPvp.tsx:10875](../../frontend/src/components/BoardPvp.tsx#L10875)) et sa route
  sémantique ([w40k_core.py:5265](../../engine/w40k_core.py#L5265)). Tous laissent les
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
  ([deployment_handlers.py:953](../../engine/phase_handlers/deployment_handlers.py#L953)) commit
  via `set_unit_coordinates` + `update_units_cache_position`
  ([shared_utils.py:1255](../../engine/phase_handlers/shared_utils.py#L1255) — n'écrit que
  `units_cache` + carte d'occupation, jamais `models_cache`). Le chemin PvP `deploy_commit` →
  `_apply_deploy_plan`
  ([deployment_handlers.py:824](../../engine/phase_handlers/deployment_handlers.py#L824)), lui,
  écrit chaque figurine via `update_model_position` puis synchronise l'ancre.
  **Mécanisme du crash** : le pool BFS du masque de move part de l'ancre `units_cache` (valide),
  mais `build_rigid_plan` ([shared_utils.py:3243](../../engine/phase_handlers/shared_utils.py#L3243))
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
  **Reste optimisable (non fait)** : la spirale teste encore chaque case par balayage de son
  empreinte (~77 % du résiduel) et `_deploy_pool_set` est reconstruit à chaque appel (~13 %).
  Pistes, mesures et pièges : [`A_faire/perf_generate_compact_formation.md`](A_faire/perf_generate_compact_formation.md).
  ⚠️ Le gain d'une érosion n'est PAS acquis dans le cas nominal (spirale qui s'arrête en
  quelques cases) — à mesurer avant d'implémenter. Non bloquant : le vrai frein du training est
  T6-g/T6-h, pas cette perf.
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
    ([deployment_handlers.py:552](../../engine/phase_handlers/deployment_handlers.py#L552)) :
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
  ⚠️ **Chemin tutoriel PvP non validé runtime** : `config/tutorial/scenario_etape*.json` ne se
  charge plus du tout (`wall_ref` legacy sans `board_ref` →
  `ValueError` dans `_resolve_board_dir`, game_state ~L1664) — dette T4 indépendante de ce fix
  (la migration de banque n'a pas couvert `config/tutorial/`). Le chemin a été validé par son
  équivalent fonctionnel (commit à ancre imposée, ci-dessus).

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
  cohésion (cf. §0). Aucune règle de jeu modifiée : l'érosion ne fait que RETIRER du masque des
  destinations que l'exécution refusait déjà.
  **Validation** : +6 tests dédiés (mur/autre escouade/ER sous une SŒUR alors que l'ANCRE est
  légale, débordement de plateau, non-sur-filtrage, court-circuit mono-figurine) ; run x5_debug
  8 workers 10/10 épisodes et run mono-env x1_debug, **zéro** « incohérence masque/exécution ».
  Historique de la rupture ci-dessous.
  **Repro** (moteur nu, `training_benchmark`, premier index du masque) : dès que les figurines
  sont réellement placées, le crash T6-f se déplace au squad suivant —
  `ValueError: execute_squad_move a échoué : squad=3 type=normal dest=(195,163) depuis
  (197,168) — incohérence masque/exécution`.
  **Root cause (tracée entrée par entrée sur le plan rigide)** : `build_squad_move_cell_map`
  ([shared_utils.py:7394](../../engine/phase_handlers/shared_utils.py#L7394)) construit le pool
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
  ([shared_utils.py:3243](../../engine/phase_handlers/shared_utils.py#L3243)) applique
  `new_col = col + dx, new_row = row + dy` en coordonnées OFFSET. En grille hexagonale offset,
  une translation à `dx` impair change la parité de colonne de chaque figurine et n'est donc PAS
  une translation hexagonale — la formation se déforme.
  **Le projet connaît déjà ce piège et l'évite ailleurs** :
  `deployment_build_squad_destinations_pool`
  ([deployment_handlers.py:552](../../engine/phase_handlers/deployment_handlers.py#L552)) passe
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
des `events.out.tfevents.*` (EventAccumulator) sur training neuf : `0_critical/` porte bien les
métriques PPO — `f_loss_mean`, `g_explained_variance`, `h_clip_fraction`, `i_approx_kl`,
`j_entropy_loss`, `m_value_loss_smooth`, **56 points chacune** ; `training_critical/` expose ses
6 tags. Le fix `_dump_with_capture` du 2026-05-22 tient. Nuance non diagnostiquée (sans impact) :
`train/*` et `training_critical/*` n'ont qu'1 point là où `0_critical/*` en a 56 — répartition
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
`end_activation(game_state, unit, arg1, ...)` (generic_handlers ~L70-101) définit :
`arg1="ACTION"` → « *Log the action (action already logged by handlers)* » ;
`arg1="WAIT"` → `end_activation` émet lui-même l'action_log ; `arg1="NO"` → rien.
Or `_process_squad_action` appelait `end_activation(..., ACTION, ...)` après un move et une charge
réussis — donc en PROMETTANT que le handler avait journalisé — alors que `execute_squad_move` et
`charge_build_valid_plan` n'émettaient **aucun** `append_action_log` (contrairement au chemin
legacy par-figurine, movement_handlers ~L3701/4107, charge_handlers ~L5597/5877).
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
et `_process_squad_action` n'est appelé que depuis `step()`/`_build_observation` = gym.
Le PvP (`services/api_server.py`) passe par `execute_semantic_action` → `_process_semantic_action`.

**Le déploiement n'était PAS journalisé non plus** (`deployment_handlers` : grep
`append_action_log` = 0). Conséquence mesurée et non évidente : `log_episode_start` écrit les
unités non déployées en `(-1,-1)`, et sans log de déploiement l'analyzer n'apprenait JAMAIS leur
position réelle → **49 fausses « collisions »** (contrôle 2.2). Émettre `deploy_unit` les a
résolues d'un coup (49 → 0).

**Bug de règle trouvé DANS l'analyzer** (faux positifs, pas un bug moteur) :
`_track_action_phase_accuracy` (analyzer.py ~L835) attendait `"advance": "SHOOT"`. **Faux** :
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
  MÊME branche, shoot_handler.py ~L165). **Verdict : faux positifs de l'analyzer, aucun bug
  moteur, backend non modifié.** Détail complet, preuve et options rejetées :
  `A_faire/analyzer_los_ancre_vs_perfig.md`.
  **Cause structurelle confirmée — le CONTRÔLEUR est périmé, pas le moteur** (et il n'y a
  AUCUNE divergence training/PvP : le moteur est unique et pilote les deux) :
  - L'analyzer n'a PAS sa propre LoS — il appelle bien `engine.hex_utils.compute_los_state`
    (analyzer.py ~L602, docstring : « same algorithm as the game engine »). **Mais il l'appelle
    ANCRE-À-ANCRE** : `has_line_of_sight(shooter_col, shooter_row, target_col, target_row,
    wall_hexes)` — un point contre un point.
  - Le moteur, lui, fait `_attacker_model_can_reach_squad` (shared_utils ~L4243) : LoS
    **PER-FIGURINE**, origine = **empreinte COMPLÈTE du socle tireur** (« pas son seul centre »),
    distance bord-à-bord, via `_compute_visibility_with_obscuring` (murs denses + obscurcissant,
    13.10). **Son propre commentaire décrit exactement ce faux positif** : « une grosse base dont
    le centre est masqué par un terrain (mais dont un bord voit la cible) était grisée à tort ».
  - → L'analyzer refait le test centre-à-centre que le moteur a DÉLIBÉRÉMENT abandonné. Même
    dette que R5 / le step logger / les objectifs de l'analyzer : outil resté sur le modèle
    pré-squad « une unité = un point ».
  - Second suspect : `except Exception: return False` (analyzer.py ~L630) — **écarté par mesure**
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
  `_emit_squad_shoot_log` (shared_utils ~L5758) loggue l'ancre d'ESCOUADE, pas la figurine qui
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
(`except Exception: print("⚠️ ... logging error")`, step_logger.py ~L254). Un champ manquant
produit une ligne SILENCIEUSEMENT absente, pas un crash. **Contrôler `grep -c "logging error"`
après tout changement de mapping** — c'est ainsi qu'ont été trouvés les manques `hit_roll` puis
`deploy … position data`.

Plan d'origine (résolu ci-dessus) :

**Fait vérifié (statique)** : `_process_squad_action` (w40k_core.py, def ~L4750, plage ~4750-5146)
— le chemin VIF du pipeline squad en gym — contient **ZÉRO appel à `step_logger.log_action`**
(grep sur la plage = 0). Son docstring l'annonce : « Dispatch sémantique squad vers helpers squad.
**Remplace `_process_semantic_action`** ». Or les **17** sites `log_action` vivent dans
`_process_semantic_action` (def ~L2725) et ses handlers, atteignables seulement via
`execute_semantic_action` (~L2090) et `execute_ai_turn` (~L2114) = chemins PvE/legacy.

**Preuve empirique (run mono-env réel, 475 épisodes, après les fixes T6-b)** :
- `Steps=0` sur **474/475** épisodes (`episode_step_count` n'est jamais incrémenté) ;
- **0 ligne** correspondant à `Unit N (MOVED|SHOT|CHARGED|FOUGHT|WAITED)` sur 12 561 lignes ;
- ~26 lignes/épisode = les seuls en-têtes (`Scenario`, `Rosters`, `Walls`, `Objectives`, `Rules`,
  `Board`) + `EPISODE END` + `OBJECTIVE CONTROL`.

⚠️ **Nuance vérifiée (à ne pas sur-simplifier)** : `log_action` n'est pas TOTALEMENT inatteignable
depuis le gym — **3 épisodes sur 475** portent `Actions=9|9|18`. Ce sont exclusivement des
`rule_choice` (« Unit 105 chose [AGGRESSION IMPERATIVE] »), émis par le site w40k_core ~L2416-2425
dont le commentaire dit explicitement « select_rule_choice **bypasses normal step logger flow** ».
C'est donc le seul `log_action` atteignable — précisément parce qu'il court-circuite le flux
normal — et il n'incrémente pas `step_count`. **Toutes les actions de JEU (move/shoot/charge/
fight/wait), celles à `step_increment=True` dont l'analyzer a besoin, ne sont jamais journalisées.**

**Conséquence** : `ai/analyzer.py` échoue en `Missing objective control snapshot at episode end`
(analyzer_core.py ~L250) — il construit ses snapshots de contrôle d'objectif à chaque action
`step_inc` (~L861-907), et il n'y en a aucune. Aucun réglage de l'analyzer ne peut compenser :
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
  (`require_key(weapon, "display_name")`, analyzer_config.py:150). **Impacte aussi le PvP.**
  → constante `_TS_QUOTED_STRING = r'(["\'])((?:(?!\1).)*)\1'` (backréférence : fermeture sur le
  MÊME guillemet), appliquée à `display_name`, `COMBI_WEAPON` et `WEAPON_RULES`. Strictement
  identique pour tout nom sans apostrophe. Résultat : registre à **176 unités, 0 erreur de
  parsing** (contre 107 erreurs).
- **Donnée corrigée en conséquence** : `wolf_guard_weapon` déclarait `WEAPON_RULES: [""]`
  (spaceMarine/armory.ts:142) — une chaîne VIDE que l'ancien motif (`+`, 1 car. min.) avalait
  silencieusement. Le motif corrigé la lit fidèlement → règle vide rejetée. `[""]` → `[]` :
  comportement inchangé (l'ancien parser produisait déjà `[]`), la donnée dit enfin ce que le code
  comprenait. Occurrence unique dans tout le projet.
- **`_resolve_scenario_path` (analyzer.py) résolvait vers l'ARCHIVE** : T4 a déposé la banque
  pré-V11 sous `scenarios/_archive_pre_v11/` — donc DANS l'arbre parcouru par `os.walk` →
  `ValueError: Ambiguous scenario path for 'scenario_training_bot-29'` (l'archivé garde ses clés
  legacy, sa signature d'objectifs diffère du migré homonyme). → la marche élague les dossiers
  `_archive*`. Aligné sur la convention du projet : `get_scenario_list_for_phase`
  (training_utils.py:308) travaille sur une liste blanche explicite (training/, holdout_regular/,
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
  de step.log écrit `Obj<id_string>` (`Objrect_b_nw_OK`) alors que le parser attend `Obj(\d+)`
  (analyzer_core.py ~L112) — **trois formats coexistent** (nom / `Obj`+string / `Obj`+int).

**✅ Bloqueur résolu (historique) — `ai/analyzer.py` ne démarrait pas** :
`ConfigurationError: Required key 'RNG' is missing` (`analyzer_config.py:167`) —
`load_analyzer_config` itère TOUT `unit_registry.units`, donc 4 armes de TIR de l'armory Ork sans
clé `RNG` bloquaient l'analyzer QUEL QUE SOIT le scénario, même sans Ork. Renseignées par
l'utilisateur (`RNG: 24`) le 2026-07-16 : `kombi_rokkit`, `kombi_shoota`, `rokkit_launcha`,
`rokkit_launcha_heavy`. A permis de découvrir les blocages suivants (parser d'apostrophes,
archive T4, contrat objectifs legacy) puis le vrai mur structurel T6-c.

Plan d'origine :
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
- ✅ **Réserve T2 purgée** : `multi_agent_trainer.py` ~L996-1040 — monkeypatch
  `controller.execute_gym_action` portant le dernier layout à 8 actions (`action // 8`,
  `action % 8`). Code mort ET cassé : `W40KEngine` n'a aucun attribut `controller` (grep vide) et
  le patch appelait 6 méthodes inexistantes (`_get_gym_eligible_units`,
  `_convert_gym_action_to_mirror`, `_log_gym_action`…). Supprimé.
- ✅ **Réserve T3/T4 purgée** : paramètre `objectives_ref` de `_materialize_scenario_with_refs`
  (branche morte qui aurait émis une clé REJETÉE par le moteur — game_state ~L329). ⚠️ La purge
  avait laissé un `NameError` latent (`hash_payload` référençait encore la variable) — attrapé par
  le test `test_materialize_scenario_with_refs_wall_override_emits_no_legacy_key`, corrigé.
- ✅ **Réserve T4 close** : `sweep_scenario_bank_v11.py` a désormais son bootstrap `sys.path`
  (L19) ; `migrate_scenario_bank_v11.py` n'a **aucun import projet** → n'en a pas besoin.
- ✅ **`ai/target_selector.py` SUPPRIMÉ** (validation utilisateur obtenue le 2026-07-16), avec son
  test `tests/unit/ai/test_target_selector.py`. Mort confirmé par grep exhaustif avant suppression :
  aucun importeur hors le module lui-même et son propre test (-9 tests collectés).
- ⚠️ **Contradiction non résolue (décision produit requise)** : T6.1 impose `--new`, qui écrit
  `ai/models/CoreAgent/model_CoreAgent.zip` — or CLAUDE.md (L51-53, L215) et la décision de design
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

**Déclencheur : le training tourne** (donc T6-h puis T6-g livrés, cf. §0). **Ne PAS commencer
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

### Phase B (après T6 ET Phase A' — section 9 — validés) — Observation niveaux
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
| T6 | Run `--new` court complet + analyzer + replay OK ; ~~win-rate vs RandomBot en progression~~ → **critère REMPLACÉ le 2026-07-19, voir section 10.6** (win-rate PAR ROSTER contre un adversaire de holdout jamais vu à l'entraînement + absence de comportement absurde en partie humaine). L'ancien critère référençait un holdout de rosters qui n'existe plus. — ⏳ **PARTIEL (2026-07-16)**. ✅ Run `--new` : déroule sans AUCUNE exception (467/500 ép.). ✅ Suite verte (1293) + smoke `(A)/(B)` OK (mêlée 5 kills, Carnifex charge). ✅ T6-c résolu : `_process_squad_action` journalise, analyzer tourne, `1.2 erreurs shooting = 0`. ✅ **T6-d résolu** : `squad_fight` = sélection FIGHT 12.04, machine V11 déroulée par `_fight_v11_gym_settle` (ordre 12.02→12.04→12.07 respecté, snapshot posé, double activation interdite). ❌ **win-rate NON concluant** : ~30 % vs GreedyBot sur 467 ép. (bruit) — mesuré AVANT T6-d, donc sur un moteur où la mêlée était fausse ; **à re-mesurer** avec phase `x1` + `bot_evaluation` holdout vs RandomBot. ❌ **Le run est de nouveau IMPOSSIBLE depuis le 2026-07-19** : T6-f a révélé T6-g/T6-h (cf. §0) — le critère T6 ne peut pas être réévalué avant ces 2 fixes |
| T6-f | Après le commit de déploiement, AUCUNE figurine vivante à `(-1,-1)` et ancre `units_cache` = figurine d'index minimal, sur les 3 chemins (gym, ancre imposée tutoriel, drag) — ✅ **FAIT (2026-07-19)** |
| T6-g | Toute cellule offerte par le masque de move est exécutable : sur N épisodes aléatoires, zéro `ValueError` « incohérence masque/exécution » — et un test dédié où une escouade dont le BLOC déborde (mur / autre escouade) ne voit PAS la cellule dans son masque — ✅ **FAIT (2026-07-19)** : `test_move_pool_block_erosion.py` (+6, mur/escouade/ER sous une SŒUR, débordement plateau, non-sur-filtrage, mono-fig) ; runs x5_debug 8 workers (10/10 ép.) et mono-env x1_debug, zéro occurrence |
| T6-h | La translation de bloc préserve les distances internes pour TOUTES les parités de `dx` (test paramétré `dx` pair ET impair) — rouge sur le code actuel — ✅ **FAIT (2026-07-19)** : `test_rigid_plan_translation.py` (+10), rouge avant le fix aux seules parités impaires ; fix étendu à `translate_squad_to_destination` (écrivain du commit) et `preview_hidden_models_after_move` |

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

### 8.1 Principes (non négociables)

- **Un fix = ses tests dans la même tranche** : chaque rupture R1-R7 corrigée s'accompagne de
  tests qui reproduisent la panne d'origine (le test doit échouer sur l'ancien code) ET
  verrouillent le comportement corrigé.
- **Miroir PvP** : pour tout prédicat/chemin bifurquant gym vs PvP, tester LES DEUX branches —
  le test PvP fige le comportement d'avant-fix (neutralité), le test gym fige le fix.
- **Zéro monkeypatch de code mort** : les tests qui patchent `_attack_sequence_rng` disparaissent
  avec lui (P1) ; aucun nouveau test ne doit s'appuyer sur du code sans site d'appel vif.
- **Déterminisme** : tout test utilisant du RNG fixe sa seed ; tout test d'ordre de candidats
  (P2/P3) vérifie la STABILITÉ de l'ordre sur deux appels identiques.
- **Erreurs explicites testées** : chaque garde « erreur explicite, pas de fallback » ajoutée
  par le plan a un test `pytest.raises` vérifiant le TYPE et le MESSAGE (fragment discriminant).
- Les tests règles encodent le PDF du projet (référence 40k_rules citée en docstring), jamais
  le comportement du code mort.

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

### 8.3 Couverture par tranche

**T1 (fait — tests à vérifier présents, compléter si trous)** :
- R6 : éligibilité + destinations de charge avec `BASE_SIZE` liste (Carnifex `[41,27]`,
  Psychophage `[47,36]`) dans les DEUX sites (`charge_build_valid_destinations_pool`,
  `_charge_reverse_goal_bfs_for_eligibility`) — plus cas socle rond int (non-régression).
- R4 : `is_programmatic_owner`/`is_programmatic_defender` — matrice complète :
  (gym_training_mode True/False) × (player_types human/ai) ; allocation tir auto en gym ;
  **allocation fight auto en gym avec pertes réellement allouées** (le chemin FIGHT_CTX,
  jamais exercé avant T1) ; les 4 sites `defender_human` du flux fight ; en PvP humain,
  l'allocation reste manuelle (miroir) ; `_is_ai_controlled_shooting_unit` NON branché sur
  gym (test négatif : pas d'auto-activation `active_shooting_unit` en gym).

**T2** :
- Tests 8.2 ci-dessus.
- `env_wrappers` : WAIT forcé émet `ACTION_WAIT` (18) ; détection « pool empty » ; plus AUCUN
  test ne référence 11/12 ou les plages 4-8 hors déploiement.
- `evaluation_bots` : pour chaque phase (move/shoot/charge/fight), le bot ne choisit QUE des
  actions du masque ; choix hors masque = erreur explicite (test `raises`) ; les dicts de
  poids déploiement pointent des actions de `DEPLOY_SLOTS`.
- `game_replay_logger` : décodage correct du layout 41 (un cas par famille d'action) — ou, si
  condamné, erreur explicite testée.

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
  résolu (piège « liste vide en silence », game_state ~L376-381) ; `deployment_zones` avec
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
- **À écrire avec T6-g / T6-h** : cf. critères d'acceptation (section 6). Pour T6-h, paramétrer
  sur `dx` PAIR **et** IMPAIR — un test qui n'exerce que `dx` pair passe sur le code buggé.

⚠️ **La suite n'est PAS verte et ne l'était pas avant ces fixes** : 9 échecs préexistants
(4 banque de scénarios + 5 déploiement/terrain), tous dus à des rosters manquants ou non
résolus. Le critère réel est donc « pas de NOUVEL échec », à établir par baseline `git stash`
avant de conclure quoi que ce soit sur une régression.

### 8.4 Couverture Phase A' (une règle = son fichier de tests, AVANT suppression du code mort)

- Chaque règle du tableau P1 (section 9.2) : tests sur le chemin VIF (`_manual_roll_intent` /
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

### 8.5 Critère d'acceptation global

`python3 -m pytest tests/unit/ -q` vert (0 failed, 0 error, skips justifiés) est une condition
NÉCESSAIRE de sortie de CHAQUE tranche (T1→T6, puis chaque tranche P1/P3) — en complément des
critères spécifiques de la section 6, jamais à leur place.

## 9. Phase A' — Toutes les règles implémentées dans le training (P1-P5)

Décision utilisateur (2026-07-14) : l'agent doit s'entraîner sur TOUTES les règles déjà
implémentées, et chaque fois que les règles laissent un choix au joueur, c'est l'agent qui
choisit. Périmètre strict : règles présentes dans le moteur — on n'entraîne sur AUCUNE feature
absente (stratagèmes, CP, FNP, transports, etc. restent hors scope). Prérequis : Phase A
(T1-T6) validée.

### 9.1 Constat d'architecture (audit 2026-07-14, vérifié par lecture)

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

### 9.2 P1 — Parité de résolution : réimplémentation depuis les PDFs, puis suppression du mort

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
`squad path expected` (shoot, left_click, select_weapon, invalid — cf. 9.1), l'état
`_rapid_fire_*` de w40k_core (~1055-1061, 2055-2061) ET ses sites shooting_handlers
(~L230, 947-953, 2500-2506, 4912-4925, 5689-5696), le champ de log `rapid_fire_bonus_shot`
(w40k_core ~3561, non attrapé par le grep), et les tests qui monkeypatchent le mort.
Critère : grep `_attack_sequence_rng|_rapid_fire_|rapid_fire_bonus_shot` vide (hors nouvelle
implémentation vive) + suite verte.

### 9.3 P2 — Mécanisme générique « décision agent »

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

### 9.4 P3 — Branchement décision par décision (une tranche = une décision + validation)

⚠️ Les sites à remplacer sont ceux du PIPELINE VIF gym (vérifiés par contre-review), pas les
heuristiques `_ai_select_*` qui ne sont que des fallbacks/chemins legacy.

Ordre par valeur tactique :
0. **Prompts rule-choice** (le plus urgent — pseudo-décision aléatoire structurelle) : en gym,
   `_select_ai_rule_choice_option` choisit par `raw_action_int % len(options)`
   ([w40k_core.py:2494](../../engine/w40k_core.py#L2494)) — l'agent « choisit » via une action émise pour tout autre chose,
   sans voir le prompt. À remplacer par une vraie décision P2.
1. **Cible de mêlée** — ⚠️ **MIS À JOUR le 2026-07-16 (le fix du bug `squad_fight` a déplacé ce
   site)** : la boucle `get_best_enemy_score_for_unit` de `squad_fight` **n'existe plus** — elle
   sélectionnait sa cible dans le mapping de slots gelé du tir, sans filtre de zone d'engagement
   (violation 12.05) et crashait quand ce mapping était vide (cf.
   `Implémenté/bug_squad_fight_mask_mismatch.md`). Le site vif est **désormais
   `_ai_select_fight_target`** (fight_handlers ~L1725), que `squad_fight` consomme via
   `_fight_build_valid_target_pool` — en miroir du flux PvP (`_fight_v11_resolve_attacks`).
   Ce n'est donc plus un « fallback » : c'est le sélecteur vif, partagé gym/PvP.
   ⚠️ Il porte un `except Exception: … return valid_targets[0]` (~L1781) qui masque toute erreur
   de config/registry — vérifié : jamais déclenché sur la suite + smoke. Retrait = backend
   partagé, arbitrage requis (cf. `A_faire/bug_pile_in_bfs_clearance_mismatch.md` §dernier).
   La boucle `get_best_enemy_score_for_unit` reste vive pour la **cible de charge** (point 2).
   Pilote du mécanisme P2.
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

### 9.5 P4 — Observation de support

Bloc décision (P2) + features nécessaires aux choix : LoS/couvert par slot ennemi, portée
effective de l'arme active vs distance du slot, flags advanced/fell_back de l'unité active.
Les niveaux/élévation restent en Phase B (scénarios plats jusque-là).

### 9.6 P5 — Validation par tranche

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

---

## 10. Stratégie d'entraînement et d'évaluation — DÉCISION UTILISATEUR (2026-07-19)

### 10.1 Contexte et arbitrage

**Objectif métier** : présenter le jeu avec une IA « acceptable » pour obtenir un financement.
La démo oppose un **joueur humain** à l'IA, avec les **armées de la boîte de base**.

**Arbitrage assumé** : l'agent n'apprendra PAS à jouer 40K, il apprendra à jouer **ces deux
rosters**. C'est un choix délibéré pour éviter des semaines de tuning — la spécialisation réduit
la variance de composition, donc le signal d'apprentissage est plus net et la convergence plus
rapide. Pour une démo, un agent spécialisé est indiscernable d'un agent généraliste.

⚠️ **Ne PAS « corriger » ce choix** en réintroduisant de la diversité de rosters : c'est une
décision produit, pas un oubli.

### 10.2 Rosters et matchups

- **2 rosters** : Space Marines (SM) et Orks — les armées de la boîte de base, donc celles de
  la démo. L'entraînement est aligné sur ce qui sera montré.
- **3 matchups** : SM vs Orks, SM vs SM, Ork vs Ork.
- Les rosters de l'ancienne banque ont été **supprimés volontairement** (commit `43eae95a`,
  370 fichiers) : ils précédaient l'implémentation des escouades, donc obsolètes. Les nouveaux
  sont à créer.

### 10.3 Progression d'adversaires (l'axe qui porte la robustesse)

Le risque dominant pour cette démo n'est PAS la composition des armées, c'est **l'écart entre
l'adversaire d'entraînement et l'humain de la démo**. Trois niveaux, qualitativement différents :

| Niveau | Nature | Limite |
|---|---|---|
| 1. Bots scriptés | politique **fixe** | l'agent apprend un exploit ; le win-rate monte sans que la compétence monte |
| 2. Self-play | politique **non-stationnaire** qui s'adapte en retour | les exploits cessent de payer ; risque de catastrophic forgetting |
| 3. MCTS | adversaire qui **cherche** | non exploitable par pattern ; coûteux |

**Plan retenu** : (1) les bots scriptés → (2) introduction **progressive** du self-play →
(3) MCTS **seulement si** la perf mesurée est insuffisante.

⚠️ « Diversité d'adversaires » = diversité des **distributions de comportement**, pas nombre de
classes de bots. Huit bots appliquant la même heuristique gloutonne ne font qu'UN adversaire du
point de vue de l'apprentissage.

**Déjà implémenté, à paramétrer et non à développer — mais UNIQUEMENT sur le chemin rotation**
(`--scenario bot`, cf. §10.4) :
- `training_config.bot_training.ratios` — mélange pondéré de bots
  (`_build_training_bots_from_config`, train.py ~L91 ; 7 classes supportées, 6 pondérées dans
  la config actuelle — `defensive_smart` n'y est pas). Configuré dans les 5 phases.
- `training_config.opponent_mix` — self-play progressif : `self_play_ratio_start` →
  `self_play_ratio_end`, `warmup_episodes`, snapshot publié par
  `_publish_self_play_snapshot` (train.py ~L2854) et rechargé par mtime dans
  `BotControlledEnv` (env_wrappers ~L515). Chaîne complète vérifiée : parse → publication →
  rechargement. Le « progressivement » est donc de la config.
  ⚠️ `opponent_mix` n'est PARSÉ que dans `train_with_scenario_rotation` (~L2362) —
  `create_multi_agent_model` l'ignore totalement.

### 10.4 ⚠️ Écart CODE vs PLAN à corriger avant le premier run

**Toute la machinerie d'adversaires (bots pondérés + opponent_mix) n'est câblée que sur le
chemin ROTATION.** L'adversaire réel du chemin single-scenario dépend de `n_envs` et du NOM du
fichier scénario — vérifié branche par branche :

| Chemin | Adversaire d'entraînement RÉEL |
|---|---|
| `--scenario bot` (`train_with_scenario_rotation`) | ✅ `bots=training_bots` pondérés (~L2492, ~L2755) + self-play `opponent_mix` |
| `--scenario <fichier>`, `n_envs > 1` (cas RÉEL : x5_debug = 8) | ❌ `make_training_env` appelé SANS `use_bots`/`training_bots` (~L1782) → `SelfPlayWrapper(frozen_model=None)` → **ACTIONS ALÉATOIRES UNIFORMES, en permanence** (voir ci-dessous) |
| `--scenario <fichier>`, `n_envs == 1`, nom contenant « bot » | `GreedyBot(randomness=0.15)` EN DUR (~L1855) |
| `--scenario <fichier>`, `n_envs == 1`, autre nom (dont `scenario_training_benchmark.json`) | ❌ `SelfPlayWrapper` → **aléatoire permanent** aussi (~L1871) |

**Pourquoi « aléatoire permanent » et pas du self-play** (bug latent distinct, vérifié) :
`SelfPlayWrapper._get_frozen_model_action` (env_wrappers ~L1237) retombe sur
`random.choice(valid_actions)` tant que `frozen_model is None` — et
**`update_frozen_model` n'a AUCUN appelant** dans tout `ai/` (grep = 0 ; le compteur
`frozen_model_update_frequency = 100` de train.py ~L2690 est du code mort). Le « self-play »
du chemin single-scenario n'en est pas : P2 joue au hasard du premier au dernier épisode.
Ne pas confondre avec le VRAI self-play (`opponent_mix` → `BotControlledEnv`, chemin rotation),
qui recharge un snapshot publié sur disque et fonctionne.

Or `--scenario bot` est cassé en amont (rosters, cf. §0) : le chemin réellement utilisable est
le single-scenario. **Un run x5_debug lancé aujourd'hui entraînerait donc contre un adversaire
ALÉATOIRE, sans qu'aucun log ne le signale** — pire que « spécialisé sur GreedyBot » : un agent
qui n'a jamais rencontré d'opposition cohérente.

C'est la même famille de divergence que **T6-e** (`_turn_step_limit` absent du chemin
single-scenario) : deux chemins de `train.py` qui ont divergé. À traiter de la même façon —
faire passer les deux par la même construction d'adversaires (`training_bots` + `opponent_mix`
dans `make_training_env`, qui accepte DÉJÀ ces paramètres : seul l'appel de
`create_multi_agent_model` ne les transmet pas).

### 10.5 Évaluation : le holdout porte sur l'ADVERSAIRE, pas sur les rosters

**Constat** : les bots d'évaluation viennent de `callback_params.bot_eval_weights`
(`_load_bot_eval_params`, bot_evaluation.py ~L168 ; itération sur `eval_weights.keys()` ~L886).
Config actuelle, identique dans les 5 phases : `{greedy, defensive, control, aggressive_smart,
adaptive}` — un **sous-ensemble strict des bots d'entraînement** (`bot_training.ratios` = les
mêmes 5 + `random`). L'agent n'est donc évalué QUE contre des adversaires rencontrés à
l'entraînement : ce win-rate mesure **l'exploitation apprise, pas la compétence**, et sera
systématiquement optimiste par rapport au comportement face à un humain.

**Décision** : le holdout est un **adversaire réservé à l'évaluation**, jamais vu en
entraînement. Candidat déjà disponible : **`TacticalBot`** — le seul des 8 qui n'est utilisé
nulle part (`evaluation_bots.py` L19 : « unused in training/eval »).

À faire : ajouter `TacticalBot` aux bots d'évaluation, et **garantir qu'il n'entre jamais**
dans `bot_training.ratios` (test de non-régression : l'intersection entre bots d'entraînement
et bots de holdout est vide).

Cela remplace avantageusement le holdout de rosters supprimé, et répond à la question
« 2 ou 4 rosters » : **rester à 2**, et mettre le holdout sur l'axe adversaire.

⚠️ Les 20 scénarios de `holdout_regular/` + `holdout_hard/` pointent vers des rosters supprimés :
ils ne chargent pas. **À archiver** dans `_archive_pre_v11/`. Tant qu'ils sont là,
`bot_eval_scenario_pool: "holdout"` (présent dans les 5 phases de
`CoreAgent_training_config.json`) pointe sur un pool mort.
NB — répartition VÉRIFIÉE des 9 échecs de la suite (cause relue test par test) : **8 viennent
des scénarios TRAINING** (`agent_roster_ref: "training_random"` →
`roster_pool_schedule produced zero eligible training rosters`, candidates=1 : le pool de
rosters d'entraînement est quasi vide depuis le cleanup `43eae95a`) et **1 seul** d'un fichier
de roster holdout absent. Archiver les holdouts n'en fait tomber qu'un : le gros de la
réparation est la création des nouveaux rosters SM/Orks (§10.2) + la mise à jour des scénarios
training qui les référencent.

### 10.6 Critère de succès (remplace le critère T6 « win-rate vs RandomBot »)

Le critère historique référençait une capacité qui n'existe plus (holdout de rosters). Nouveau
critère, en deux volets — **les deux sont requis** :

1. **Quantitatif** : **win-rate PAR ROSTER** contre l'adversaire de holdout (`TacticalBot`),
   jamais rencontré à l'entraînement. Par roster, car avec seulement 2 rosters, un effondrement
   sur l'un pendant que l'autre monte est la **signature du catastrophic forgetting** (piège
   listé dans CLAUDE.md) et le seul garde-fou qui reste. Un win-rate agrégé le masquerait.
2. **Qualitatif — décisif pour l'objectif démo** : **absence de comportement absurde** sur N
   parties jouées par quelqu'un n'ayant pas travaillé sur le projet, cherchant activement à
   surprendre l'agent (déploiement inhabituel, tactique atypique).

**Pourquoi le volet 2 n'est pas optionnel** : devant un financeur, ce qui convainc est que l'IA
paraisse *sensée* (elle va sur les objectifs, tire sur des cibles plausibles, charge quand c'est
logique). Un agent à 45 % de victoires qui joue de façon lisible impressionne davantage qu'un
agent à 70 % qui gagne en exploitant une faiblesse de bot et produit un coup absurde au pire
moment. **En démo, l'incohérence coûte plus cher que la défaite.**

### 10.7 MCTS — deux usages distincts, ne pas les confondre

| Document | Usage | Effet |
|---|---|---|
| `A_faire/MCTS/MCTS_bot_final.md` | MCTS comme **adversaire d'entraînement** (fraction d'épisodes, entre bots et self-play) | améliore l'entraînement → demande un cycle complet de plus |
| `A_faire/MCTS/MCTS_agent_implementation.md` | MCTS **dans l'agent**, à l'inférence | corrige les coups absurdes **sans retraining** |

Pour l'objectif démo (§10.6 volet 2), c'est le **second** qui a le meilleur rapport
effort/résultat : c'est l'absurdité ponctuelle qui coûte cher, et une recherche à l'inférence la
corrige directement. Contre-argument à mesurer : la **latence** en temps réel devant un public —
`MCTS_agent_implementation.md` note lui-même « micro à chaque activation + rollouts = beaucoup
plus lourd » et suggère « macro + feuille value seule » comme prototype. Un MCTS macro peu
profond, ou limité aux seules décisions critiques, suffirait probablement.

**À ne PAS anticiper** : plan B après mesure. Rien ne sert de décider avant de savoir si le PPO
spécialisé suffit.
