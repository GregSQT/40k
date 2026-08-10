# Testing

## Lancer les tests

```bash
# Python — tous les tests (depuis la racine)
source .venv/bin/activate
pytest tests/unit/ -q -n 8 --dist worksteal

# Python — engine uniquement
pytest tests/unit/engine/ -q -n 8 --dist worksteal

# Python — intégration PvP (partie réelle pilotée par l'API Flask, in-process)
pytest tests/integration/pvp/ -q -n 6 --dist load

# Frontend (depuis frontend/)
npx vitest run
```

### Pourquoi `--dist worksteal` (mesuré 2026-07-26)

`--dist load` (défaut de `pytest-xdist`) envoie à chaque worker un **gros lot initial pris dans
l'ordre de collecte**. Les fichiers lourds étant voisins dans l'ordre alphabétique, ils atterrissent
sur le **même** worker : il finit seul pendant que les sept autres dorment, et la barre de
progression stagne dans les derniers pourcents. `worksteal` (xdist ≥ 3.2, 3.8 installé) rééquilibre
en cours de route — un worker inactif vole du travail à un worker chargé.

Mesure sur les 18 fichiers les plus lourds, même machine (8 cœurs) :

| Commande | Mur | `user` (CPU réellement occupé) |
|---|---|---|
| `-n 8` (`load` par défaut) | 3 min 10 | 4 min 22 → ~1,4 cœur en moyenne |
| `-n 8 --dist worksteal` | **1 min 34** | 5 min 13 |
| `-n 12 --dist worksteal` | 1 min 40 | 5 min 42 |

`-n 12` ne paie pas : la machine a 8 cœurs, l'oversubscription coûte plus qu'elle ne comble.

### Pourquoi `--dist load` sur l'intégration PvP, et pas `loadfile` (mesuré 2026-08-05)

Stratégie INVERSE de celle des unitaires, pour une raison de forme de la suite : `tests/integration/pvp/`
ne compte que **7 fichiers pour 59 tests**, et `test_shoot.py` pèse à lui seul **5 min 30 en série**
(trois tests de contrat de ciblage à 116 s, 81 s et 70 s). `--dist loadfile` colle un fichier entier sur
un worker : ce fichier-là devient le plancher de toute la suite, quel que soit `-n`. `--dist load`
répartit test par test et fait tomber le plancher au test le plus lourd (116 s).

| Commande | Mur |
|---|---|
| série (`-n 0`) | 17 min 07 |
| `-n 6 --dist loadfile` | 5 min 09 |
| `-n 6 --dist load` | **3 min 31** |
| `-n 12 --dist load` | 3 min 52 (`user` 25 min contre 17 : contention) |

C'est sûr ici : aucune fixture `scope="module"`/`"session"` dans le répertoire, et `api_isolated`
remet `api_server.engine = None` après chaque test — deux tests du même fichier n'ont donc aucun
état partagé à se transmettre.

### La suite d'intégration PvP a son décor à elle, et il est FIGÉ

`tests/integration/pvp/` démarre en mode `"pvp"` avec un `scenario_file` explicite —
`config/board/44x60x5/scenario/scenario_pvp_integration.json` (`conftest.INTEGRATION_SCENARIO`),
qui porte lui-même `terrain-integration.json` et ses murs en `wall_hexes` inline. Ce n'est pas un
aménagement de test : la route `/api/game/start` transmet déjà le `scenario_file` du client en
mode `"pvp"`, c'est le chemin de production.

Pourquoi pas le mode `"pvp_test"`, qui serait plus direct : il **impose**
`scenario_pvp_test.json`, le bac à sable jouable. Le 2026-08-06 (commit `training`, 02454a34) ce
fichier a été remplacé par un roster SM/Orks dont les deux armées sont à ~150 sous-hex l'une de
l'autre et **ne se rencontrent jamais en 5 tours** : les 59 tests sont passés à 32 rouges d'un
coup — ids attendus absents, `drain_to("charge")` inatteignable, `fight_subphase` à `None` du
début à la fin, et cinq assertions « aucun X dans ce scénario » (unité engagée, cible à couvert,
unité cachée hors portée). Le décor figé reprend exactement le contenu d'avant ce commit.

Corollaire : **ne pas retoucher `scenario_pvp_integration.json` ni `terrain-integration.json`
pour jouer.** Ces positions SONT ce que la suite mesure. Les bacs à sable jouables restent
`scenario_pvp_test.json` et `scenario_pvp_test_sm_tyranids.json`.

Les murs sont inline plutôt qu'en `wall_ref` pour une raison qui n'a rien à voir avec les tests :
un `walls-*.json` de plus dans `config/board/44x60x5/walls/` entrerait dans le tirage aléatoire
du training (`game_state._load_shared_walls_from_ref` sur `wall_ref: "random"`,
`ai/train._list_available_board_refs`). Le dossier `terrain/` n'est lu que par référence
explicite, d'où la copie dédiée.

### Le démarrage d'un worker (mesuré 2026-08-05)

Un worker xdist paie **8 à 12 s avant le premier test** — pour beaucoup de fichiers c'est plus que
les tests eux-mêmes (`test_engine_step.py` : 10,9 s de mur pour 0,2 s de tests). L'import de `torch`
en pesait 4,9 s à lui seul, et `tests/conftest.py` le payait dans CHAQUE worker pour un simple
`manual_seed` ; il est désormais semé depuis `sys.modules` sans être importé (verrouillé par
`tests/unit/ai/test_conftest_torch_seed.py`). Côté `tests/unit/` le gain est nul — la collecte
importe de toute façon `tests/unit/ai/test_pointer_head.py`, qui importe `torch` au niveau module —
mais côté PvP, où personne ne touche au RL, les 4,9 s par worker sont récupérés.

### Les tests les plus lourds (relevé 2026-08-06, `--durations=25`)

Ce sont eux qui fixent le plancher du mur : aucun découpage xdist ne peut fractionner un test.

| Test | Ce qu'il vérifie | Coût (`call`) |
|---|---|---|
| `test_reserves_full_episode` (9 tests dans le top 25) | épisodes complets avec roster à réserves | ~241 s cumulés, dont **83,7 s** pour `test_the_seed_sample_really_exercises_the_measuring_phases` |
| `test_obs_fighting_models_no_fallback::test_get_fighting_models_does_not_raise_on_the_observation_path` | idem sur une partie réelle, 119 steps | 51,3 s — **coût légitime, cf. plus bas** |
| `test_move_mask_is_executable` (×3 seeds) | invariant « masque ⊆ exécutable » sur de vraies parties, 400 steps | 40 à 46 s / seed |

Ne pas alléger `test_move_mask_is_executable` en réduisant `MAX_STEPS` ou le nombre de seeds : à ce
coût-là, la couverture d'invariant vaut plus que les secondes gagnées. Il était à **687 s** avant
l'optimisation du 2026-07-26 (cf. `Implémentation/Implémenté/V11_move_build_acceleration.md` §3.2).

`test_deployment_clearance_parity::test_deployment_mask_mirrors_commit_overlap_predicate`, cité ici
jusqu'au 2026-08-06 comme 2ᵉ plus lourd à ~20 s, est sorti du top 25.

**Ce qui a été retiré du plancher (2026-08-06)** : `test_charge3d_floors_integration::
test_a_floor_destination_is_validated_by_the_climb_field_not_the_2d_bfs` pesait **160,5 s** — le test
le plus lourd de toute la suite, et il n'était pas documenté ici. Il évaluait
`_charge_model_pos_is_closer` sur les **629** cases du champ climb (mesuré : 630 appels, 101,9 s sur
113,7) alors qu'il n'assertait que « au moins une est légale », puis opposait deux budgets sur UNE
seule case. Sortie au premier accepté, dans un ordre déterministe — coût de montée croissant puis
`(col, row)` depuis `e76280d0`, qui trie la moins chère en tête donc la plus susceptible d'être
acceptée d'emblée. Elle l'est : **2 appels** à `_charge_model_pos_is_closer` au lieu de 630 (mesuré,
verdicts `[True, False]` — la candidate puis le contre-test à budget serré). **160,5 s → 0,4 s**,
assertions inchangées. Contre-épreuve : en faisant décider le BFS 2D à la place du champ climb
(`charge_handlers`, garde `dest_level >= 1`), le test redevient ROUGE sur son message propre — le
verrou tient après l'allègement.

**Idem pour `test_obs_fighting_models_no_fallback::test_a_failure_of_get_fighting_models_now_propagates`
(2026-08-06) : 49,3 s → 0,20 s.** Son helper `_play_until` demandait de traverser
`{"deployment", "command", "move"}` et se contentait d'un `break` en cas d'échec. Or la phase
`deployment` n'apparaît JAMAIS sur `scenario_training_armageddon` (unités pré-placées, mesuré) :
l'helper jouait donc l'ÉPISODE ENTIER, 119 steps, avant de rendre la main sur épuisement des actions
légales. Un repli silencieux, et il masquait un vrai défaut : le test choisissait son escouade par
`next(iter(units_cache))`, or au tour 1 cette première clé est justement l'escouade **en réserves**
(mesuré : 1 hors table sur 10, et c'est elle). Le site d'observation était donc court-circuité par sa
garde `on_battlefield` — le test ne passait que parce que les 119 steps parasites laissaient à cette
escouade le temps d'arriver (`deployed_on_turn=2`). Vert pour la mauvaise raison. L'helper lève
désormais, et l'escouade est choisie parmi celles réellement posées.

**Le premier test du même fichier, lui, garde ses 119 steps** : la charge n'est atteinte qu'au
step 46 et la phase de fight au step 59, alors que son seuil `calls >= 400` tombe dès le step 42.
Tronquer sur le seuil lui retirerait la phase de combat, c'est-à-dire son sujet. Vérifié que
l'extraction du prédicat `_is_on_battlefield` ne change rien à ce qu'il exerce : 119 steps,
1 177 appels, 23 escouades filtrées — identiques avant/après, 0 divergence entre l'ancien
prédicat inline et le nouveau.

---

## État actuel

### Python — `tests/unit/engine/` + `tests/unit/services/`

**⚠️ Chiffre périmé : « 990 tests, ~2.2s » (2 skipped).** L'inventaire ci-dessous n'a pas suivi la
croissance de la suite. Ordre de grandeur réel (2026-07-26) : **150 fichiers, ~1 550 fonctions `test_`
avant expansion des `parametrize`**. Le total collecté et le mur exacts sont à relever sur la commande
de vérification complète (§ Lancer les tests) — ils ne sont pas re-postés ici tant qu'ils ne sont pas
mesurés sur la suite entière.

| Fichier | Tests | Ce qui est couvert |
|---|---|---|
| `test_hex_utils.py` | 89 | LoS (`compute_los_visibility`, `compute_los_state`), voisins hex, distances, pathfinding |
| `test_movement_pool_build.py` | 7 | `movement_build_valid_destinations_pool`, `_movement_engagement_violates` |
| `test_move_eligibility.py` | 12 | `get_eligible_units` (move), activation pool, `movement_preview`, `movement_clear_preview` |
| `test_move_resolution.py` | 5 | BFS destinations : plateau vide, murs, alliés, EZ, unité FLY |
| `test_fly_2103_conformity.py` | 31 | **Take to the skies (21.03)** : mot-clé FLY insensible à la casse sur le VRAI roster d'ArmageddonAgent chargé par `UnitRegistry` ; malus de 2″ converti par `inches_to_subhex` ; invariant « traversée ⟺ 2″ payés » (jamais dissociables) ; couverture move ET charge, exclusion de pile-in/consolidation ; éligibilité au move bornée par le budget réel et non par `MOVE` brut (masque ⊆ exécutable, §0.34) ; garde de phase du malus ; **preuve in-engine** sur `scenario_training_armageddon1.json` avec sonde qui échoue si elle n'a rien vu |
| `test_move_execution.py` | 16 | `_attempt_movement_to_destination` : position, cache, flee, EZ, enemy_adjacent_hexes + socles non ronds |
| `test_charge_eligibility.py` | 9 | `get_eligible_units` (charge) — filtres player/EZ/fled/cannot_charge/advanced/no-target |
| `test_charge_resolution.py` | — | BFS destinations charge |
| `test_charge_execution.py` | 17 | `charge_phase_start`, `_has_valid_charge_target`, `charge_build_valid_destinations_pool` (BFS) |
| `test_charge_manual_surface.py` | 29 | **Surface PvP manuelle de la charge — les branches de REFUS.** `charge_build_valid_targets` (ennemi déjà engagé écarté 11.02, mémo indexé sur `_unit_move_version`), `_charge_model_pos_is_closer` (« end closer » 11.04 WHILE, interdit d'engager un non-cible 11.04 AFTER, collision coéquipière ET son filtre par niveau 03.04, borne du jet, cible absente), `charge_preview_move_plan` (cohérence 03.03, cible engagée par personne, jet absent), `charge_target_selection_handler` (cible manquante, liste multi-cibles conservée, jet raté consommé 11.02 FAILED CHARGES), `charge_commit_move_plan_handler` (6 refus dont plan ne couvrant pas toutes les figurines vivantes + 1 contrôle positif), `charge_autoplace_plan` (5 levées d'entrées manquantes, repli traînards, couverture dure infaisable). Plateau nu 1 sous-hex = 1″, chaque test construit sa situation et vérifie ses prémisses. **28 mutations rejouées, 28 rouges.** Écrit après mesure : ces fonctions étaient appelées par `tests/integration/pvp/test_charge.py` mais uniquement sur le chemin nominal (62-89 % de lignes, tous les trous côté refus) |
| `test_shooting_activation_pool.py` | 7 | `shooting_build_activation_pool` — filtres player/HP_CUR/no-targets |
| `test_shoot_resolution.py` | 4 | `_has_valid_shooting_targets` — adjacence, pistol, fuite |
| `test_shoot_execution.py` | 16 | HP partiel/létal/limites, cascade mort pools, `active_shooting_unit`, `is_unit_alive` |
| `tests/unit/ai/test_step_log_weapon_rule_tokens.py` | 18 | **Chaîne moteur → step.log → analyzer** pour [DEVASTATING WOUNDS], [HEAVY], [RAPID FIRE], [COVER], [SUSTAINED HITS] et les abilités de relance : le maillon de jonction que rien ne testait (V11 §0hist.38). La touche additionnelle de 24.36 n'a **pas de jet** (`Hit None`) — sans son marqueur, rien ne la distingue d'une ligne malformée, elle comptait dans le plafond de tirs et la règle s'affichait simultanément « NOT USED » |
| `tests/unit/ai/test_analyzer_scale_vehicle_fly.py` | 18 | Trois verdicts que l'analyzer rendait faux : **échelle** prise dans le config courant au lieu de l'entête `Board:` du log analysé (×5 sur toutes les distances — fabriquait des erreurs ET en masquait) ; **10.06 / 17.03**, un MONSTER/VEHICLE engagé tire avec toutes ses armes ; **21.03**, la traversée FLY est déclarée et son marqueur n'atteignait jamais step.log. Plus l'engagement per-figurine (une escouade n'est pas son ancre) et l'exclusion des socles morts d'une cible fauchée |
| `tests/unit/ai/test_analyzer_charge_fight_moves.py` | 14 | Charge, pile-in (12.03) et consolidation (12.08) contrôlés comme move et advance : jet converti en subhex (à x5 un jet de 7 valait un plafond de 7 cases au lieu de 35, **toute** charge réussie remontait en faute), mesure per-figurine, chemin vérifié, 2″ de 21.03 retranchés. Et les **règles du run** lues dans l'entête `Run rules:` : valeurs volontairement différentes du config, sans quoi le test ne regarderait rien |
| `tests/unit/ai/test_analyzer_no_heavy_after_move_false_positive.py` | 3 | L'analyzer n'invente plus d'usage invalide de [HEAVY] après un déplacement ≤ 3" |
| `tests/unit/ai/test_evaluation_bots.py` | 27 | **Bots d'évaluation** : critère de cible explicite (jamais l'ordre des slots), joueur dérivé de l'escouade ACTIVÉE et non de `current_player` (la sélection 12.04 alterne), contre-charge du `DefensiveBot`, divergence masque/mapping = erreur explicite |
| `tests/unit/ai/test_eval_holdout_opponent.py` | 12 | Holdout d'évaluation (V11 §10.5) : `TacticalBot` hors `bot_training.ratios`, contrat exigé par `BotControlledEnv`, ranking masqué si l'éval n'est pas fiable |
| `tests/unit/engine/test_deployment_mode_schedule.py` | 10 | Scheduler fixed↔active sur le VRAI moteur (bornes 0.0/1.0, rampe croissante) **+ lecture du vrai fichier de config** : les 5 profils portent la rampe, bloc manquant dans un profil = erreur explicite |
| `tests/unit/engine/test_deployment_model_destinations_pool.py` | 5 | **Pool par-figurine de mise en place** (`deployment_build_model_destinations_pool`) — la fonction qui décide de TOUTES les cases où poser une figurine, au déploiement comme à l'arrivée de réserves (20.04), et qui n'avait aucun test direct. Ses trois décisions sont verrouillées séparément : érosion (l'empreinte translatée tient dans les cases acceptables), niveau EFFECTIF §13.06 (une candidate n'est taguée étage que si son empreinte tient sur le plancher — pool CONSTRUIT exprès au-dessus d'un plancher, sinon la branche n'est jamais exercée), et clairance euclidienne contre les sœurs (propriété que la borne de portée ne doit pas relâcher). Plus l'oracle naïf de la primitive d'érosion `erode_pool_by_block_offsets` sur des offsets qui EXCLUENT l'ancre — le cas que les deux appelants de production masquent. Cet oracle est aussi ce qui verrouille `erode_pool_by_block_offsets_multi` (N ensembles acceptables sur le MÊME pool, pour n'éroder qu'une fois par niveau) : la fonction à un argument y délègue, donc l'oracle traverse les deux. Verrous prouvés rouges : borne rétrécie, branche étage neutralisée, marge de grille supprimée |
| `test_shoot_attack_sequence.py` | 13 | Séquence de tir BOUT-EN-BOUT sur le chemin vif (`build_manual_shoot_allocation`) — les 4 issues, AP, invulnérable, 05.01/05.04 sur seuil 1, **[ANTI-X] au tir** (câblage couvert par rien avant), jusqu'aux PV retirés |
| `test_fight_special_rules.py` | 6 | `[HAZARDOUS]` 24.15 en MÊLÉE (`build_manual_fight_allocation`) — clause « or selected to fight », 1 jet par arme, 06.03 (1-2 → 1 MW, 3 si tout MONSTER/VEHICLE) |
| `test_fight_activation_pools.py` | 9 | `fight_build_activation_pools` — pools charging/alternating, `units_fought` |
| `test_fight_resolution.py` | 5 | `_fight_build_valid_target_pool` — EZ, mort, allié, multi-cibles |
| `test_fight_execution.py` | 20 | HP management, cascade mort fight, `resolve_dice_value` (couches 5-7) |
| `test_fight_attack_sequence.py` | 10 | `_execute_fight_attack_sequence` — to_hit, to_wound, save, dégâts, kill, logs, dés fixés |
| `test_reactive_move.py` | 28 | `maybe_resolve_reactive_move` : déclenchement, reentrance, cleanup, logs. Et les trois invariants d'échelle/plan : le **rayon de déclenchement** (9″) comme le **budget** (D6″) sont convertis ×`inches_to_subhex` — comparés bruts à une distance de grille, ils valaient 1,8″ et 1,2″ à x5, soit une capacité quasi éteinte hors x1 ; le pool ne retient que les destinations dont le **plan rigide** est valide (une destination dont le 2ᵉ socle tombe dans un mur est écartée alors que le BFS d'ancre l'accepterait), ce qui autorise la translation du bloc au lieu du seul déplacement d'ancre ; `require_coherency` y est désactivé — la translation étant rigide, l'exiger ferait rejeter toutes les destinations d'une escouade sortie de coherency par une perte, éteignant la capacité sans un log |
| `test_phase_start.py` | 18 | `movement_phase_start`, `shooting_phase_start`, `fight_phase_start` — phase, cache, pools |
| `test_phase_transitions.py` | 14 | Transitions end-to-end move→shoot→fight : phase_start, BFS, attack sequence, kill |
| `test_reward_calculator.py` | 8 | `_determine_winner` ; `_calculate_on_objective_reward` — le bonus « sur objectif » n'est PAS versé à une escouade battle-shocked (01.07 : OC de toutes ses figurines à '-', elle ne peut rien prendre). Compte relevé par collecte réelle : le 23 précédent, et la mention de `_calculate_wound_target` / `_calculate_expected_damage` (absents de ce fichier), étaient périmés |
| `test_agent_interface_contract.py` | 40 | V11 §8.2 — verrou d'interface agent. (1) **Parité masque↔décodeur** : tout entier ouvert par le masque de production est décodable, à chaque phase jouée (~166 actions réelles) ; le rejet hors masque est verrouillé une couche plus haut, dans `validate_action_against_mask`. Comme les trois fichiers `test_deployment_*`, son fixture passe par `_config_helpers.pin_active_deployment`, qui ÉPINGLE `deployment_mode_schedule` (déploiement actif) sur l'instance moteur — jamais dans la config — pour ne dépendre ni d'un réglage que l'utilisateur arbitre, ni de l'absence d'un réglage. (2) Routage entier → intention, cas par cas, sur `convert_squad_action` (cellule de move, wait, slots tir/charge/mêlée, combat sans cible, zone intent, CHOICE, slot de déploiement, **chevauchement 4-8 move/déploiement**) + les gardes qui doivent lever. Vérifié par mutation |
| `test_action_decoder.py` | 27 | `normalize_action_input`, `validate_action_against_mask`, masque legacy `_build_mask_for_units`, sélection d'hex de déploiement (les cas `convert_gym_action` sont partis avec le décodeur mort) |
| `test_observation_builder.py` | 22 | `ObservationBuilder.__init__`, wound_target, expected_damage, favorite_target |
| `test_engine_turn_loop.py` | 24 | `W40KEngine._check_game_over`, `GameStateManager.determine_winner` (les 8 tests de `_advance_to_next_player` ont été supprimés avec la méthode, code mort — cf. V11 §0.4) |
| `test_los_cache_invalidation.py` | 7 | `_invalidate_los_cache_for_moved_unit` — invalidation sélective/totale |
| `test_combat_utils*.py` | 16 | Coordonnées, dés, voisins, LoS cachée |
| `test_shared_utils*.py` | 12 | Cache unités, HP, positions |
| `test_generic_handlers.py` | 6 | `end_activation` — tracking, step, logs |
| `test_spatial_relations.py` | 5 | Relations spatiales entre empreintes |
| Autres | ~28 | Armes, polygones, replay, hex union |
| `tests/unit/services/test_api_endpoints.py` | 22 | Flask endpoints : `/api/game/state`, `/api/game/action`, `/api/health`, `/api/game/reset`, racine |
| `tests/unit/engine/test_execute_semantic_action.py` | 19 | Flux e2e `execute_semantic_action` : skip, move valide/invalide, advance_phase (cascade), phase inconnue, game_over, action inconnue + routing shoot/fight |
| `tests/unit/engine/test_cross_phase_cascade.py` | 15 | Cascade inter-phases : mort en fight/shoot retire des pools croisés, units_fled/advanced exclus de charge et tir |
| `tests/unit/engine/test_cascade_fight_subphases.py` | 9 | Cascade charge→fight : fight vide, unités adjacentes, sous-phases charging/alternating, player switch, pools nettoyés |
| `tests/unit/engine/test_engine_init.py` | 9 | `W40KEngine.__init__` : échecs sans controlled_agent / rewards_config / board / objectives ; succès config minimale |
| `tests/unit/engine/test_engine_reset.py` | 18 | `W40KEngine.reset()` : turn=1, game_over=False, tracking sets vidés, HP/positions restaurés, units_cache reconstruit, episode_number incrémenté |
| `tests/unit/engine/test_special_rules_e2e.py` | 8 | Règles spéciales de tir en INTERACTION, bout-en-bout sur le vif : DEVASTATING × HAZARDOUS, HEAVY × DEVASTATING, arme nue |
| `tests/unit/services/test_api_integration.py` | 14 | API Flask flux réel (engine semi-réel, sans mock execute_semantic_action ni _game_state_for_json) : sérialisation JSON, champs requis, no set leak |
| `tests/unit/engine/test_engine_step.py` | 13 | `W40KEngine.step()` : signature tuple×5, types obs/reward/terminated/truncated/info, turn_limit→terminated, pool vide→phase auto-advance |
| `tests/unit/engine/test_forced_wait_not_penalised.py` | 9 | **Attente FORCÉE** (le masque n'ouvre que `wait`) : elle ne coûte plus la pénalité de passivité, et le moteur la joue lui-même au lieu de rendre la main. Situation CONSTRUITE (ennemi hors de portée d'arme), témoin à portée pour la non-régression, `info` qui reste celui de l'action de l'agent, borne au joueur qui vient d'agir, et **bilan d'épisode remonté** quand la partie se termine PENDANT la chaîne auto-jouée (`TERMINAL_INFO_KEYS`) |
| `tests/unit/engine/test_game_state_contract.py` | 28 | Contrat game_state produit par `__init__` réel : clés scalaires, tracking sets, pools, structures complexes (units_cache après reset) |
| `tests/unit/engine/test_objective_scoring.py` | 15 | `apply_primary_objective_scoring` : guard clauses, VP par condition (control_at_least_one/two, control_more_than_opponent), cap max_points, round5 phase spéciale, liste multi-objectifs ; **battle-shock (01.07)** : une unité sous le choc n'apporte aucun OC, bascule l'objectif à l'adversaire, ne marque plus de VP, et l'absence du champ `battle_shocked` lève (aucune valeur par défaut) |
| `tests/unit/engine/test_command_phase.py` | 16 | `command_phase_start` en isolation et via `W40KEngine.reset()` ; **sonde vive battle-shock** : vrai moteur, demi-effectif, dés forcés → l'étape 08.03 pose elle-même le drapeau et le décompte 14.02 du moteur tombe à zéro (la sonde échoue si elle ne voit pas le contrôle exister avant le choc) |
| `tests/unit/services/test_unit_builders_battle_shock.py` | 3 | Contrat des constructeurs d'unités hors moteur : `_build_units_from_army_config` (change_roster) et `_build_unit_from_registry` (spawn endless duty) posent toujours `battle_shocked`, que `sum_objective_control_oc_multi` lit sans défaut |
| `tests/unit/engine/test_unit_rules_shoot.py` | 7 | UNIT_RULES × WEAPON_RULES sur le même dé (01 Core « Re-rolls ») : abilité + [TWIN-LINKED] ne relancent jamais deux fois ; portée des abilités `to wound` |
| `tests/unit/engine/test_activation_e2e.py` | 9 | Activation e2e via `execute_semantic_action` : routing pool, skip, game_over, tir→HP réduit, mort→units_cache cleanup, pool cleanup, units_shot, all_attack_results |
| `tests/unit/engine/test_off_table_geometry.py` | 8 | **Unités HORS TABLE (20.01) — aucun chemin géométrique ne les mesure.** Contrat des primitives de `spatial_relations` : `entry_footprint` et `entries_in_engagement_zone` LÈVENT, `unit_within_engagement_zone_footprints` rend `False` (réponse de règle), `entries_on_battlefield` / `enemy_entries_on_battlefield` écartent. Puis les deux familles par le chemin de PRODUCTION, avec la géométrie **construite** : ENGAGEMENT (unité réelle amenée en `(1,1)`, à distance hex 1 de la sentinelle) et DISTANCE (tireur amené au coin du plateau, donc fantôme dans sa portée d'arme). ⚠️ Sans cette construction le test resterait VERT avec le défaut — la sentinelle est à ~274 subhex des zones de déploiement. Chaque garde a son test symétrique « la primitive rend bien quelque chose sur une entrée normale » (anti vert vacant). Verrou prouvé : défaut remis → 4 des 8 rouges |

| `tests/unit/engine/test_faction_abilities.py` | 42 | **Capacités de FACTION (Waaagh! ORKS, Oath of Moment ADEPTUS ASTARTES).** La DÉCISION : 08.04 pose un `pending_agent_decision` (Waaagh!) ou une désignation `pending_oath_selection` (Oath), le masque devient EXCLUSIF, et l'appel ne se propose qu'UNE fois par partie — vérifié sur le MASQUE, pas sur l'état, car c'est lui qui décide de ce que l'agent peut jouer. L'invariant **D1** : `OATH_SLOT_i` désigne la même escouade que la ligne *i* du tenseur ennemi (3 ennemis, sinon toute permutation serait l'identité). La DURÉE : « until the start of your next Command phase » enjambe le tour adverse — un test qui n'observerait que le tour du déclarant resterait vert avec une extinction en fin de tour. Les EFFETS sur le chemin VIF (`build_manual_shoot_allocation` / `roll_fight_intent`, dés scriptés) : invulnérable 5+ lue sur le `saveTarget` que la résolution compare, +1 S / +1 A mesurés au seuil de blessure ET au nombre de dés consommés, relance de touche d'Oath contre la cible désignée **et pas** contre une autre. La clause de DÉTACHEMENT sur les 4 mots-clés (un balayage qui n'en connaîtrait que 3 passerait avec un seul cas), champ de config absent → lève. La chaîne `hitAbility` jusqu'à `step.log` (record → mapping `_SHOT_RECORD_FIELD_MAP` → les DEUX formateurs). Verrous prouvés : 7 défauts remis un par un, chacun rougit. **Puis 7 de plus, apportés par deux revues** : la clause d'exclusion d'Oath lisait la table de mots-clés où les sous-factions ne sont JAMAIS déclarées (morte, donc), la décision d'un joueur figeait la phase de l'autre, l'expiration ne purgeait ni l'Oath ni le Waaagh! restés en attente (le second FAIT LEVER 08.04), quatre appelants hors moteur jetaient le retour de `command_phase_start`, et les deux actions du frontend n'étaient routées que sur le chemin du GYM. Le dernier verrou monte un `W40KEngine` réel, hors gym, deux sièges humains, et passe par `execute_semantic_action` — le point d'entrée de `/api/game/action`, pas celui du gym : la première version de ce test exerçait `_process_squad_action` et passait au vert sur un chemin que le widget n'emprunte jamais. **Puis 2 de plus, sur l'OPPOSABILITÉ de l'arrêt** : la phase s'arrêtait sur la décision sans REFUSER les autres actions, or `advance_phase` est intercepté avant le dispatch de phase — il terminait la phase, désignation encore posée, donc purgée sans avoir servi et plus aucune relance de touche du tour. Les deux points d'entrée sont exercés (UI PvP et gym : le second est inatteignable, masque exclusif, mais c'est le jumeau). Le second verrou ferme le vocabulaire de la phase (`zone_intent` / `skip` et rien d'autre) et mesure l'INERTIE du refus : ni solde de la déclaration du tour précédent, ni consommation des free steps. **Puis la review a trouvé le troisième** : la reprise ANNONÇAIT la phase de mouvement sans la démarrer (les deux routes de décision sortent avant la boucle de cascade, seul endroit où une transition s'exécute) — le gym s'en sortait par son WAIT, le PvP restait bloqué en commandement une fois l'Oath désigné. Le test du cycle réel assert désormais `phase == move` ET un pool de mouvement construit, pas un `phase_complete` |
| `tests/unit/ai/test_env_wrappers.py` (bloc Oath) | 5 | **Les quatre replis « pool vide → `ACTION_WAIT` » ne connaissaient qu'UN mécanisme d'arrêt sur choix joueur.** La désignation d'Oath en est un second et elle n'est PAS optionnelle : le masque n'ouvre aucun WAIT, donc le repli rendait une action HORS MASQUE et le décodeur levait — trouvé sur un vrai run, pas déduit. Les 4 sites (`_get_bot_action`, `_get_frozen_model_action` avec et sans modèle, `_get_self_play_opponent_action`) prouvés rouges. Les mécanismes vivent depuis dans UNE table, `_PLAYER_CHOICE_MECHANISMS`, lue par les deux consommateurs — le prédicat `engine_is_paused_on_player_choice` (sites à modèle) et le tirage `random_action_for_pending_choice` (sites bot) : ils ne peuvent plus diverger, et un 3ᵉ mécanisme n'y ajoute qu'une ligne. ⚠️ `_decision_from_mask` est un 5ᵉ lecteur qui ne consulte PAS la table et reste correct par deux propriétés de l'Oath (phase `command`, détenu par `current_player`) — écrites sur place, parce que deux revues ont dû les re-dériver |
| `tests/unit/engine/test_auto_deployment_positions.py` | 3 x 2 terrains | Le déploiement `auto` (ex-`fixed`) pose TOUTES les figurines, chacune DANS la zone de déploiement de son joueur (`deployment_pools`), escouades cohérentes 03.03 via l'oracle moteur ; `active` → sentinelle. Rejoué sur `terrain-mc1` ET `terrain-mc2` : le critère est l'appartenance à la zone, pas une bande top/bottom — les zones de `mc1` sont TRIANGULAIRES. Plus le cas construit « réserves 20.01 » : les zones ne vivaient que dans `deployment_state`, écrit uniquement quand un joueur déploie — une unité en réserves étant hors table dès le reset, `squad_grid_anchor` et la clause 20.04 levaient, et le reset entier avec. Le cas est ÉPINGLÉ sur la fixture à réserves des deux côtés, pas espéré d'un tirage |
| `tests/unit/engine/test_deploy_pool_terrain_zones.py` | 4 | Peuplement du deploy-pool depuis les zones du terrain (banque `random`/`active`, neutralité du placement fixe PvP). Plus **l'identité des zones entre modes** : les murs n'étaient soustraits que si un joueur déployait en `random`/`active` — sans effet tant que les zones ne servaient qu'à la phase, mais l'ancre de grille est le BARYCENTRE du pool, donc la même unité sur le même plateau recevait un centrage différent selon le tirage fixed↔active (mesuré : 0 mur en `active`, 149 et 151 en `fixed`). Le test compare les DEUX modes plutôt que de compter les murs d'un seul — c'est l'identité qui est le contrat. Verrou prouvé rouge |
| `tests/unit/services/test_game_snapshots_static_keys.py` | 3 | **Les zones de déploiement survivent au restore d'un snapshot PvP, y compris d'un snapshot ANCIEN.** Les snapshots sont picklés sur disque et `build_game_state` reconstruit l'état à partir des SEULES clés déclarées statiques (prises de l'engine vivant) plus la copie mutable ; `deployment_pools` n'y étant pas, un pickle d'avant son déplacement à la racine restaurait un état sans zones — 500 côté API au premier clic de déploiement. Le cas de migration est CONSTRUIT (clé racine retirée de la partie capturée), pas espéré. Un test anti vert-vacant vérifie d'abord que le moteur publie bien les zones. Verrous prouvés rouges |

#### Couverture par couche

| Couche | Périmètre | État |
|--------|-----------|------|
| 0 — Géométrie / hex | hex_utils, spatial_relations, polygones | ✅ solide |
| 1 — units_cache / shared | build_units_cache, HP, positions | ✅ solide |
| 2 — Éligibilité | move, charge, shoot, fight | ✅ solide |
| 3 — Pools d'activation | move, shoot, fight, charge | ✅ solide |
| 4 — BFS destinations / target pools | move, fight, shoot, charge, focus fire | ✅ solide |
| 5 — Exécution action | move, fight, shoot (primitives), socles non ronds | ✅ OK |
| 6 — Résolution dés | `resolve_dice_value` + expected_value | ✅ OK |
| 7 — Transitions / cascade mort | retrait pools, enemy_adjacent_hexes | ✅ OK |
| 8 — Séquences d'attaque end-to-end | `_execute_fight_attack_sequence`, `attack_sequence.roll_attack_pool` (socle tir+mêlée) | ✅ OK |
| 8b — Règles spéciales | DEVASTATING_WOUNDS, HAZARDOUS | ✅ OK |
| 9 — Initialisation de phase | `movement/shooting/fight/charge_phase_start` | ✅ OK |
| 10 — IA / Observations | `RewardCalculator`, `ActionDecoder`, `ObservationBuilder` | ✅ OK |
| 11 — Boucle tour / fin de partie | `_check_game_over`, `determine_winner` ; la progression de tour réelle est en fin de phase Fight (`fight_handlers`, deux chemins) | ✅ OK |
| 12 — Mouvement réactif | `maybe_resolve_reactive_move` | ✅ OK |
| 13 — API Flask | endpoints REST `/api/game/*` | ✅ OK |
| 14 — Flux e2e `execute_semantic_action` | skip, move, advance_phase, routing shoot/fight, game_over | ✅ OK |
| 15 — Cascade inter-phases | mort→pools, fled/advanced exclusions | ✅ OK |
| 15b — Cascade charge→fight | sous-phases charging/alternating, player switch, fight vide | ✅ OK |
| 16 — Init W40KEngine réel | échecs config, succès config minimale | ✅ OK |
| 16b — Reset W40KEngine | turn/game_over/pools/HP/positions restaurés entre épisodes | ✅ OK |
| 17 — API intégration (flux réel) | sérialisation JSON sans set leak, champs requis | ✅ OK |
| 18 — Règles spéciales tir | DEVASTATING_WOUNDS, HAZARDOUS, HEAVY — résultats et flags | ✅ OK |
| 19 — step() gym interface | reset→step×N→game_over, turn_limit, phase auto-advance, tuple×5 | ✅ OK |
| 20 — Contrat game_state | clés critiques produites par `__init__` réel, types vérifiés | ✅ OK |
| 21 — Scoring objectifs primaires | VP par condition, cap, round5, déduplication, liste multi-obj | ✅ OK |
| 22 — UNIT_RULES dynamiques (tir) | reroll_1_towound, reroll_towound_on_obj, closest_target_penetration | ✅ OK |
| 23 — Activation e2e complète | tir→HP→mort→cleanup pool via execute_semantic_action | ✅ OK |
| 24 — Capacités de faction | Waaagh! / Oath : décision 08.04, durée qui enjambe le tour adverse, effets tir ET mêlée, clause de détachement, invariant D1 | ✅ OK |

### Python — `tests/unit/scripts/`

**Ce qu'on met ici** : les tests des outils de `scripts/` — générateurs de scénarios, collecte
de statistiques, migrations de banque. Ces outils ne sont pas le moteur : ils **écrivent des
fichiers de configuration** et **produisent des chiffres**, deux choses qui échouent en
silence. Un scénario au mauvais contrat n'est découvert qu'au chargement, un taux de victoire
faux n'est jamais découvert du tout.

Contrainte propre au répertoire : **un test de `scripts/` ne fait jamais tourner de partie**.
Ces outils lancent des épisodes complets ; les exercer réellement volerait le CPU d'un
entraînement en cours et rendrait la suite inutilisable. On teste donc les fonctions qui
décident, avec des doublures (faux environnement, faux modèle) — pas le script de bout en
bout. Corollaire : ce qui compte doit être extrait dans une fonction appelable, sinon il
n'est pas testable.

| Fichier | Tests | Ce qui est couvert |
|---|---|---|
| `tests/unit/scripts/test_roster_matchup_eval_loop.py` | 18 | Boucle d'évaluation de `roster_matchup_stats.py`, exercée avec un faux env (obs `Dict` + masque) et un faux modèle qui enregistre ce qu'il reçoit : obs `Dict` servie non aplatie, chemin legacy `Box` converti en float32/batch, masque venant de `engine.get_action_mask` (voie legacy jamais lue), arrêt exact au plafond de pas, épisode tronqué compté `failed` et jamais en partie, vainqueur et siège lus dans `info` (absence → erreur explicite), les deux générateurs aléatoires graînés, normalizer délégué à `ai/bot_evaluation.py`, `--agent-seat-mode` transmis dans les modes bot **et** agent |
| `tests/unit/scripts/test_roster_matchup_scenario_contract.py` | 5 | Contrat V11 des scénarios écrits par `roster_matchup_stats.py` : aucune clé legacy (`objectives_ref`, `wall_ref`, `deployment_zone`), `board_ref`/`terrain_ref` présents, défauts CLI lus sur le parseur réel et pointant des fichiers existants, terrain par défaut porteur d'aires `objective: true` et de `deployment_zones` |

### Frontend — `frontend/src/utils/`

**68 tests**

| Fichier | Tests | Ce qui est couvert |
|---|---|---|
| `blinkingHPBar.test.ts` | 16 | `buildChargeMinRollOverlay`, `buildWeaponSignature`, `calculateWoundProbability`, `calculateDamagePerAttack`, z-index |
| `movePoolRefsSync.test.ts` | 15 | `addHexKeysToSet` (formats array/objet/string), `syncMoveDestinationPoolRefs` |
| `activationClickTarget.test.ts` | 11 | Cibles de clic d'activation |
| `gameHelpers.test.ts` | 6 | Helpers généraux de jeu |
| `hexUnionBoundaryPolygon.test.ts` | 5 | Polygones d'union hex |
| `polygonSmooth.test.ts` | 5 | Lissage de polygones |
| `weaponHelpers.test.ts` | 4 | Sélection et parsing d'armes |
| `replayParser.test.ts` | 3 | Parsing de replays |
| `pointInPolygon.test.ts` | 2 | Point-dans-polygone |
| `losPreviewHelpers.test.ts` | 1 | Preview LoS |

---

## Conventions

### Principes non négociables

- Test = déterministe, rapide, isolé, explicite.
- Aucune dépendance externe réelle (réseau, DB, I/O lourd).
- Aucun fallback pour faire passer un test.
- Tout bugfix inclut un test de non-régression.
- Toute logique critique nouvelle arrive avec tests associés.

### Contrat d'erreurs

`require_key()` lève `ConfigurationError`, pas `KeyError`.  
Toujours vérifier le **type** d'exception et un fragment de message stable :

```python
from shared.data_validation import ConfigurationError

with pytest.raises(ConfigurationError, match=r"Required key 'MOVE'"):
    require_key({}, "MOVE")
```

### Nommage

- Fichier : `test_<module>.py`
- Fonction : `test_<comportement>_<condition>_<résultat>`

---

## Ajouter un test Python

### Pattern `game_state` minimal

```python
from engine.phase_handlers.shared_utils import build_units_cache, build_enemy_adjacent_hexes

def _make_game_state(units, current_player=1):
    gs = {
        "config": {"game_rules": {"engagement_zone": 1, "max_base_size_hex": 35},
                   "board": {"default": {"hex_radius": 1.0, "margin": 0.0}}},
        "board_cols": 25, "board_rows": 21,
        "current_player": current_player,
        "phase": "move",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "console_logs": [],
    }
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, current_player)
    return gs
```

### Fonctions avec dépendances complexes (LoS, BFS)

Utiliser `monkeypatch` pour isoler les filtres :

```python
def test_unit_fled_excluded(monkeypatch):
    monkeypatch.setattr(
        "engine.phase_handlers.charge_handlers._has_valid_charge_target",
        lambda gs, unit, occupied=None: True,
    )
    # ... tester uniquement le filtre units_fled
```

---

## Ajouter un test Frontend

Les fonctions testables sont les **fonctions pures** (pas de PIXI, pas de React state).

```ts
import { describe, expect, it } from "vitest";
import { maFonction } from "./monModule";

describe("maFonction", () => {
  it("retourne X dans le cas nominal", () => {
    expect(maFonction(input)).toBe(expected);
  });
});
```

Vérifier : `npx vitest run src/utils/<module>.test.ts`

---

## CI

```yaml
# Python
pytest tests/unit/ -q
pytest tests/unit/engine/ -q --cov=engine --cov-fail-under=70
pytest tests/unit/shared/ -q --cov=shared --cov-fail-under=80

# Frontend
npm --prefix frontend run test:run
```

---

## Definition of Done

Une PR n'est pas complète si :

- Un changement métier critique n'a pas de test associé
- Un bugfix n'a pas de test de non-régression
- Des tests sont rouges en local
- Une exception attendue n'est pas vérifiée (type + message)

Checklist :
- [ ] Cas nominal couvert
- [ ] Cas d'erreur métier couvert
- [ ] Assertions explicites et lisibles
- [ ] Pas de dépendance externe réelle
- [ ] Test de non-régression présent si bugfix

---

## Périmètre non couvert

### Lacunes résiduelles (risque modéré)

| Comportement | Prochaine étape |
|---|---|
| Ghost / LoS preview (UnitRenderer.tsx) | Composant PIXI — test E2E Playwright |
| Tests UI de bout en bout | Playwright sur les parcours critiques |
| Init W40KEngine avec config réelle complète | Trop coûteux en fichiers ; mocké partiellement dans test_engine_init.py (limite documentée) |
| Déploiement phase (`deployment_handlers`) | Trop couplé au scénario complet — exclure du périmètre unitaire |
| PvEController / chemin IA (modèle chargé) | Hors périmètre tests unitaires |
| `_reload_scenario` | Dépendances fichier lourd — exclure du périmètre unitaire |
| Rewards multi-agents (RewardMapper, phase suffixes) | Couvert partiellement via reward_calculator ; flux multi-agents non exercé |
