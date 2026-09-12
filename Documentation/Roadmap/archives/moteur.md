# Archives Moteur

| Date | Chantier | Détail |
|---|---|---|
| 2026-09-12 | ✅ **20.01 — la déclaration se compose PAR CAMP, sans ordre ni question fermée** | la file alternée escouade par escouade n'avait aucune base dans 20.01 (« select one or more friendly units », un ensemble, sans ordre, sans question binaire). Décision utilisateur : déclaration par joueur à écran ouvert, un seul mécanisme tous modes. Siège humain : `Reserve` à la sélection / `Cancel` au conteneur / `Validate` au bandeau ; siège modèle : inchangé (`CHOICE_0`/`CHOICE_1`), espace d'action et observation intacts — contrat d'entraînement à zéro écart, aucun `--new`. Save TL08 → TL09. Trois défauts de la livraison trouvés avant merge (crash camp saturé, blocage sortie de phase, siège non déplacé — revue de code), chacun rouge→vert — section conservée : [moteur.md#declaration-reserves-2001-par-camp](../moteur.md#declaration-reserves-2001-par-camp) |
| 2026-09-10 | ✅ **20.01 — le siège suit la question, et le bot répond pour lui-même** | source : `engine/phase_handlers/deployment_handlers.py` (`move_seat_to_pending_reserves_declaration`), `engine/w40k_core.py` (reset), `frontend/src/utils/strategicReservesUi.ts`. Le déplacement du siège vers le camp interrogé n'existait que sur le chemin gym : aucune route HTTP ne construit de masque (`grep get_squad_action_mask_and_eligible_units services/` → 0 hit), donc en partie servie par l'API `current_deployer` restait sur le joueur 1 pendant que la file alternait. En PvE, la question du bot était offerte à l'humain sans filtre de siège et le tour IA ne partait jamais. 20.01 : « **you** can select one or more friendly units ». Le siège suit la question au reset puis après chaque réponse ; la route humaine refuse une question posée à un siège modèle ; le client ne rend les boutons que sur un siège humain. **Aucune clé de save nouvelle**, aucun bump de format. Livré le 2026-09-10, complété le même jour : la route du siège modèle ne faisait pas suivre le siège (le bot répondait à la question de l'humain au tour IA suivant — mesuré), les deux routes passent par un écrivain unique `resolve_reserves_declaration_answer`, et le tour IA du client est gardé par l'écran de préparation encore ouvert — section conservée ci-dessous : [moteur.md#siege-question-2001](moteur.md#siege-question-2001) |
| 2026-09-09 | ✅ **13.06 — le move gym peut FINIR EN HAUTEUR** | déclaration de montée sur les `CHOICE_*` existants, niveau par figurine, coût vertical facturé à celle qui monte ; livré le 2026-09-09. `obs_size` 16971 → **17055** et `GRID_CHANNELS` 11 → **12** : **`--new` obligatoire**. Rendement mesuré : 0,8 % des cellules masquées — section conservée ci-dessous : [moteur.md#verticalite-move-gym](moteur.md#verticalite-move-gym) |
| 2026-09-08 | ✅ **13.09 — statut « caché » rafraîchi à chaque perte ET à chaque tir** | option C livrée le 2026-09-08 aux deux choke-points, un par membre de la règle ; change les parties jouées, `--new` obligatoire pour tout modèle pré-diff — section conservée ci-dessous : [moteur.md#hidden-fraicheur](moteur.md#hidden-fraicheur) |
| 2026-09-10 | ✅ **20.01 — la déclaration de réserves passe AVANT le déploiement** | `SQUAD_ACTION_WAIT` portait la mise en réserves pendant le tour de déploiement de chaque unité : mesuré en déploiement actif, le joueur 2 gardait le slot ouvert avec quatre unités adverses déjà posées, alors que 20.01 situe la déclaration à l'étape Declare Battle Formations. File alternée figée au reset, une question par unité déclarable, `reserves_declaration` répondu par `CHOICE_i`, `deploy_commit` refusé tant que l'étape est ouverte. `obs_size` et `TOTAL_ACTION_SIZE` inchangés, mais la politique de déploiement change : les win-rates d'avant ne sont plus comparables. Suite livrée le même jour : le siège suit la question (§ `siege-question-2001`). moteur · — |
| 2026-08-18 | Pile-in/Overrun 12.06 par-figurine | Migration par-figurine, purge du modèle par-ancre (commit `babc3234`) ; prérequis de P3-5 levé ; → `Documentation/Archives/chantiers/pile_in_overrun_par_figurine_2026-08-18.md` |
| 2026-08-17 | INDIRECT FIRE 24.19 | 7 pièces ; `TOTAL_ACTION_SIZE` 1139→1159 ; gym+PvP+journal+analyzer ; 8 tests analyzer |
| 2026-08-17 | Root cause 03.01/09.05 + fix renforcé | `_recompute_squad_occupied_hexes` ; 6 tests, 4 mutations ROUGE ; commits `640cdb53`, `8c2a85f2` |
| 2026-08-17 | `ANTI_INFANTRY:1→2` + garde domaine | `urty_syringe` corrigé ; `MIN_ANTI_THRESHOLD = 2` ; balayage corpus |
| 2026-08-17 | Marqueur activation SHOOT 10.02 | `is_shoot_activation_start` ; `analyzer_couverture.md` mis à jour |
| 2026-08-16 | Réorganisation metrics par phase | `ai/metrics_tracker.py` restructuré ; compteurs charges par épisode |
| 2026-08-12 | Empreinte par figurine fight (pile-in destinations) | 21 sites → `_fight_model_fp_pair` ; 3 cases sur 330 changées ; → `Documentation/Archives/chantiers/empreinte_par_figurine_fight_2026-08-12.md` |
| 2026-08-12 | Engagement par figurine socle | 13 sites + 14ᵉ jumeau ; 21 530 cases sur 575 515 changées ; `MODEL_HEIGHT` par-figurine |
| 2026-08-12 | Clairance par figurine | 11 appels `low_clearance_ground_hexes` ; `FloorIndex.low_clearance` mémoïsé par hauteur |
| 2026-08-12 | Primitive commune « poser un plan » | `resolve_model_effective_level` + `place_model_at_effective_level` ; 18 sites (6 annoncés + 12 au grep) ; garde dur |
| 2026-08-12 | Contrôle objectif — phases enchaînées | `game_utils.enter_phase` = écrivain unique ; file de frontières ; `run_objective_control_checkpoint` |
| 2026-08-12 | Distance objectif mesurée à l'aire | `engine/objective_distance.py` ; 0,3 µs/appel ; 4 sites migrés ; centroïdes supprimés |
| 2026-08-12 | Deux familles move soldées (empreinte escouade) | `update_units_cache_position` ; 2 violations → 0 sur 2 259 moves ; 2 appelants migrés |
| 2026-08-11 | Socle vs mur — géométrie unique | `hex_utils.socle_blocked_anchor_cells` ; 9 sites placement ; Fall Back 0→1 277 destinations ; 125 tests |
| 2026-08-11 | PvE figé (aperçu tir sans position) | `_require_preview_destination_on_table` ; sort sans requête si unité hors table |
| 2026-08-11 | Masque move exact socles non ronds | Somme de Minkowski ; violation 09.05 0→0 sur WarTrakk |
| 2026-08-11 | Déploiement auto — positions figées supprimées | Déploiement joué par le moteur ; générateur de positions fixées supprimé |
| 2026-08-11 | Perf géométrie — cache engagement par paire | +3,42 s x1, +0,76 s x5 ; 32 Mo/processus ; 18 tests |
| 2026-08-11 | Résidus T1/T2/T3 move pool | `hex_utils.offset_slice_windows` ; `numba` acté non-dépendance ; cache pool d'ancres déploiement |
| 2026-08-18 | **P3-5** Pile-in / consolidation — livré 2026-08-18 | moteur+training · [v11_chemin_critique.md#p3-5](v11_chemin_critique.md#p3-5) |
| 2026-08-23 | ✅ **P3-0** Cohérence 03.03 — choix joueur/agent — livré 2026-08-23 | moteur · [moteur.md#p3-0](moteur.md#p3-0) |
| 2026-08-25 | ✅ **Plunging Fire (22.05) + Deadly Demise (24.08)** livré 2026-08-25 — +1 BS tireur ≥3" ou TOWERING ≤12" (cible au sol) ; explosion D6/6+ sur destroy_model ; step_logger [PLUNGING FIRE]/[DEADLY DEMISE] ; analyzer + corpus câblés ; 14 tests rouge/vert | moteur · [moteur.md#plunging-fire](moteur.md#plunging-fire) |
| 2026-08-25 | ✅ fix(shoot) escouades hors table filtrées (2026-08-25) — `shoot_weapon_eligible`/`remaining_eligible_slots` ignorent les escouades sans figurines sur la table | moteur · — |
| 2026-08-19 | ✅ step_logger event [DEAD] + pré-capture [MODELS:] tir/move (2026-08-19) — destroy_model émet un event dead dans action_logs pour toute raison ; [MODELS:] SHOOT/MOVE pré-capturés avant effets (hazardous, etc.) | moteur+analyzer · — |
| 2026-08-20 | ✅ charge_succeeded préservé lors des cascades de phase (2026-08-20) — merge {**result, **phase_init_result} au lieu de remplacement complet dans _process_squad_action ; verrou rouge/vert 3 tests | moteur · — |
| 2026-08-19 | ✅ dead events step.log + pré-capture tir protégée (2026-08-19) — _build_step_log_details mappe model_id/reason ; _emit_squad_shoot_log try/except ConfigurationError ; is None strict | moteur+analyzer · — |
| 2026-08-20 | ✅ fix desperate_escape gym : purger _flee_mode/_desperate_escape_rolls sur unité morte (2026-08-20) — 3 tests verts, cycle rouge/vert | moteur · — |
| 2026-08-20 | ✅ simplify desperate_escape : .pop() symétrique PvP + helper test _engine_battle_shocked (2026-08-20) — 3 tests verts | moteur · — |
| 2026-08-20 | ✅ simplify charge_handlers allTargetCoords via get_unit_position + Counter dupes bots (2026-08-20) — 2 sites charge_handlers migrés, O(n) détection doublons | moteur+bot · — |
| 2026-08-19 | ✅ require_unit_by_id canonique T0 (2026-08-19) — fonction unique dans game_utils, ConfigurationError si absente, re-exportée depuis combat_utils, importée dans shooting_handlers + w40k_core ; 5 tests rouge/vert | moteur · — |
| 2026-08-19 | ✅ Fix §11.04 budget charge par-figurine gym (2026-08-19) — `_attempt_charge_to_destinations` rejetait pas les destinations roll+extra ; verrou + test rouge/vert | moteur · — |
| 2026-08-19 | ✅ Endless Duty obstacles 5+6 levés (2026-08-19) — fix obstacles 5 et 6 du scénario Endless Duty | moteur+training · — |
| 2026-08-21 | ✅ metric= fight_handlers propagé (2026-08-21) — engagement_distance_metric(game_state) passé sur 11 fonctions fight_handlers ; justification singleton fausse documentée dans spatial_relations (commit 2dc65810) ; pattern absorbé par le chantier « primitive porteuse de game_state » | moteur · — |
| 2026-08-21 | ✅ fix-fight-build-valid-target-pool-metric (2026-08-21) — metric EZ depuis game_state dans build_valid_target_pool | moteur · — |
| 2026-08-21 | ✅ fix-singleton-metric-ez-game-state-primitives (2026-08-21) — `unit_entries_within_engagement_zone` accepte `game_state=` et résout `engagement_distance_metric(game_state)` ; tous call-sites propagent `game_state=` (BFS serrés : pré-calcul `metric=` une fois ; range-checks : sans game_state, intentionnel) ; `_target_locked_by_ally` reçoit `game_state` ; T2 `_count_engaged_models_after_charge` ; 5 tests verrou (un call-site par fichier, mutation ROUGE confirmée) | moteur+tests · — |
| 2026-08-21 | ✅ fix active_socle hors table (2026-08-21) — active_socle non construit quand escouade active hors table ; imports _uc en tête de fichier ; guard col<0 dans units_cache_entry ; consolider 13 helpers _uc → units_cache_entry dans _state_builders ; socle_from_cache_entry via entry_footprint | moteur+tests · — |
| 2026-08-21 | ✅ fix type de tir effacé dans 3 chemins PvP (2026-08-21) — type de tir effacé dans les 3 chemins PvP manquants | moteur · — |
| 2026-08-21 | ✅ simplify-reactive-coherency (2026-08-21) — simplification cohérence réactive moteur | moteur · — |
| 2026-08-18 | ✅ Fix review-findings (2026-08-18) — surface refus moteur squad, wsgi leading-comma, message vide | moteur+services · — |
| 2026-08-19 | ✅ JSDoc bcKey périmé + test vert vacant buildBoardGeomKey (2026-08-19) — JSDoc corrigé, test vacant renforcé | moteur+tests · — |
| 2026-08-19 | ✅ get_unit_by_id signature alignée (game_state, unit_id) (2026-08-19) — 6 sites cassés corrigés (movement_handlers+combat_utils), 49 ancienne-ordre mis à jour dans deployment_handlers, action_decoder, reward_calculator, observation_builder, game_state, w40k_core, shared_utils + tests ; 41 tests verts | moteur · — |
| 2026-08-20 | ✅ Charge multi-cibles L9 (2026-08-20) — C(20,2)+20 = 210 slots (1045–1254), tête dense séparée dans pointer_policy, logique PvP réutilisée, verrou test_action_space_mirror + test_pointer_head ; TOTAL_ACTION_SIZE 1159→1349 | moteur+ai · [v11_chemin_critique.md#p3-8](v11_chemin_critique.md#p3-8) |
| 2026-08-20 | ✅ Fix action_family shoot_indirect_slot + commentaires post-L9 (2026-08-20) — branche SHOOT_INDIRECT_SLOTS ajoutée, branche CHOICE morte retirée, offsets commentaires mis à jour (1086→1276 etc.), docstring pointer_policy corrigée ; verrou rouge/vert | moteur+ai · — |
| 2026-08-20 | ✅ Fix §11.04 target_subhex cible primaire (2026-08-20) — boucle pair remplacée par appel unique sur target_squad_ids[0], miroir PvP charge_target_selection_handler ; test mis à jour + cas absent charge_fail ajouté | moteur · — |
| 2026-08-22 | ✅ fix-fight-mask-commit-parity overrun 12.06 socle par-figurine (2026-08-22) — pool post-overrun utilise `_model_can_fight_target` (socle modèle) au lieu de `_fight_build_valid_target_pool` (socle escouade) ; personnage attaché à plus grand socle ne crash plus bot_ranking ; diagnostic retiré ; verrou rouge/vert `test_overrun_post_pilin_uses_per_model_base_size_x5` x5 euclidien | moteur+tests · — |
| 2026-08-23 | ✅ §0.69 choix d'arme CC par l'agent (2026-08-23) — FIGHT_WEAPON_SLOT + pending_fight_weapon_select ; agent sélectionne l'arme de mêlée via masque dédié | moteur+training · — |
| 2026-08-23 | ✅ Retrait figurine hors cohérence 03.03 (2026-08-23) — p3-0 : choix de retrait par joueur hors zone de cohérence End of Turn | moteur · — |
| 2026-08-24 | ✅ simplify-move-handler-altitude (2026-08-24) — guard HP<=0 dans `_check_fall_back_move` | moteur · — |
| 2026-08-24 | ✅ analyzer-move-handler-fixes (2026-08-24) — 4 corrections code-review move_handler | moteur+analyzer · — |
| 2026-08-24 | ✅ simplify-coherency (2026-08-24) — COHERENCY_SLOT_COUNT + dicts fusionnés + tests mis à jour | moteur+tests · — |
| 2026-08-24 | ✅ coherency-fixes (2026-08-24) — double-pop v11 + T1 player_types + queue inter-joueurs | moteur+tests · — |
| 2026-08-24 | ✅ move_handler 6 guards/corrections post code-review (2026-08-24) — 6 findings code-review appliqués sur move_handler | moteur+analyzer · — |
| 2026-08-24 | ✅ perf LoS cache projections tireur x5 (2026-08-24) — `_shooter_lateral_vantage_hexes` : projections précalculées une fois par `_compute_visibility_with_obscuring` au lieu de O(n×m) ; test_reserves[mc2] timeout éliminé | moteur · — |
| 2026-08-24 | ✅ L10 placement de charge décision agent (2026-08-24) — CHARGE_PAIR_SLOTS C(20,2)=190 + tête dense séparée dans pointer_policy, 20 tests verts | moteur+training · — |
| 2026-08-24 | ✅ P3-8 split-fire ranged weapons gym (2026-08-24) — 10 SHOOT_WEAPON_SEL_SLOTS (1379–1388), TOTAL_ACTION_SIZE 1379→1389, shoot_weapon_sel_net, 2-step flow miroir §0.69, 7 tests rouge/vert | moteur+training · [v11_chemin_critique.md#p3-8](v11_chemin_critique.md#p3-8) |
| 2026-08-24 | ✅ fix review findings reward-hex (2026-08-24) — corrections /code-review appliquées | moteur · — |
| 2026-08-24 | ✅ fix split-fire finally bug (2026-08-24) — squad_shoot_split_target : try/except au lieu de finally, shooting_type préservé si waiting_for_player=True, test rouge/vert | moteur · — |
| 2026-08-24 | ✅ fix 3 bugs split-fire silencieux (2026-08-24) — F1/F2/F3 corrigés | moteur · — |
| 2026-08-24 | ✅ simplify split-fire shared_utils (2026-08-24) — _squad_rng_profiles + collect_weapon_profiles module-level + pkey_to_carriers dans build_squad_action_mask | moteur · — |
| 2026-08-24 | ✅ simplify objective_hex_zones + once_claim (2026-08-24) — objective_hex_zones dans charge_build_valid_plan ; once_claim retiré du branch mort | moteur · — |
| 2026-08-24 | ✅ simplify objective_hex_sets + _combat_result_key (2026-08-24) — objective_hex_sets + _combat_result_key dans reward_calculator | moteur+training · — |
| 2026-08-24 | ✅ fix P3-8 IndexError + split-fire reward + test timeout (2026-08-24) — IndexError split-fire gym, reward et timeout corrigés | moteur+training · — |
| 2026-08-24 | ✅ simplify charge placement (2026-08-24) — objective_hex_zones + occupied_hexes dans charge placement ; chemin mort round×round purge _ez_offset_kernels | moteur · — |
| 2026-08-24 | ✅ once_claim après _get_controlled_player_unit + test objective reward idempotent (2026-08-24) — once_claim posé après _get_controlled_player_unit dans coherency + test idempotence objective reward | moteur+training · — |
| 2026-08-24 | ✅ fix(P3-8) COMBI_WEAPON masque/commit divergence split-fire gym (2026-08-24) — shared_utils + w40k_core corrigés ; 59 tests rouge/vert | moteur+tests · — |
| 2026-08-25 | ✅ fix(unit_registry) dice string rule_args WeirdBoy deadly_demise D3 (2026-08-25) — regex rule_args étendu aux dés supportés par resolve_dice_value | moteur · — |
| 2026-08-25 | ✅ refactor/simplify _get_unit_rule_arg helper shared_utils (2026-08-25) — délégation _get_required_rule_int_argument + simplification ; unique VALID_DICE_STRINGS + tests paramétrés | moteur · — |
| 2026-08-25 | ✅ 5 CR findings corrigés (2026-08-25) — reactive-order, advance_status, turn_limit-reward, monster-firable, los-T1 | moteur · — |
| 2026-08-25 | ✅ replis unit_by_id T2 (2026-08-25) — 46 sites Forme B convertis en require_unit_by_id ; unit_is_on_battlefield supprimée (code mort) ; 13 verrous rouge/vert | moteur+analyzer · [moteur.md#unit-by-id](moteur.md#unit-by-id) |
| 2026-08-27 | ✅ fix(pyright): 5 erreurs _ez_offset_kernels + cas round×round manquant (2026-08-27) | moteur+tests · — |
| 2026-08-27 | ✅ 4 findings code-review (2026-08-27) — T1 footprint span lève ValueError, FLY BFS OOB dans fly_visited, wall-ref sum(ord) vs len, doublons scénarios guards | moteur+ai · — |
| 2026-08-25 | ✅ Replis `unit_by_id` T3 (2026-08-25) — 20 sites Forme D convertis (shared_utils, fight/shoot/charge_handlers, obs_builder, w40k_core, action_decoder) ; display_save_threshold_with_waaagh + _select_fight_weapon_indices_for_fig non-Optionnalisées ; 6 verrous rouge/vert | moteur · [moteur.md#unit-by-id](moteur.md#unit-by-id) |
| 2026-08-25 | ✅ Replis `unit_by_id` T4-bis (2026-08-25) — 7 gardes résiduelles fenêtre 4 lignes (shared_utils ×6, action_decoder ×1) + import require_unit_by_id manquant action_decoder ; 9 verrous rouge/vert | moteur · [moteur.md#unit-by-id](moteur.md#unit-by-id) |
| 2026-08-25 | ✅ Replis `unit_by_id` T4-ter (2026-08-25) — 39 gardes résiduelles fenêtre 4 lignes dans 6 fichiers T3 non couverts par T4-bis (shared_utils, shooting_handlers, observation_builder, w40k_core, charge_handlers, action_decoder) ; 4 légitimes conservées ; 17 verrous rouge/vert | moteur · [moteur.md#unit-by-id](moteur.md#unit-by-id) |
| 2026-08-19 | ✅ Endless Duty obstacles 1 et 3 soldés (2026-08-19) — board_ref "44x60x5" + terrain-endless-duty.json (objectif fixe centre 110,150), objective_pool/selection supprimés, ED_START_LEADER mis à jour, signet test 2+4 ouverts | moteur · [moteur.md#endless-duty](moteur.md#endless-duty) |
| 2026-08-24 | ✅ fix fight weapon mask ordering (2026-08-24) — pending_cr/pending_fw vérifiés avant eligible_units dans get_squad_action_mask | moteur+ai · — |
| 2026-08-24 | ✅ fix(P3-8) COMBI_WEAPON masque/commit divergence split-fire gym (2026-08-24) — purge_combi_siblings lève IndexError si slot hors range ; shared_utils + w40k_core + 59 tests split_fire_gym | moteur+training · — |
| 2026-08-21 | ✅ Constante `DRAW_WINNER = -1` introduite dans `engine/constants.py`, tous les littéraux remplacés (2026-08-21) | engine · — |

---

## Sections archivées — chantiers livrés (texte conservé tel quel)

## ✅ 20.01 — le siège suit la question, et le bot répond pour lui-même {#siege-question-2001}

**Livré le 2026-09-10.** Le déplacement du siège vers le camp interrogé n'existait que sur le
chemin gym (`arm_reserves_declaration_decision`, appelé par le seul constructeur de masque). Aucune
route HTTP ne construit de masque — `grep get_squad_action_mask_and_eligible_units services/` : zéro
hit — donc dans une partie servie par l'API, `current_deployer` restait sur le joueur 1 pendant
toute l'étape pendant que la file, elle, alternait les deux camps.

Conséquence en PvE : la question du bot était rendue au client sur la ligne de roster de son
escouade, sans aucun filtre de siège, et le tour IA ne partait jamais — le déclencheur de
`BoardWithAPI` lit `current_deployer`, et `execute_ai_turn` refuse hors `current_player == 2`.
L'humain répondait donc à la place du bot, ou la partie n'avançait plus. 20.01 dit « **you** can
select one or more friendly units » : la liste d'un camp se décide depuis son siège.

Ce qui change, sur les deux routes et par une seule écriture
(`move_seat_to_pending_reserves_declaration`) : le siège suit la question au reset, puis après
chaque réponse ; la route humaine REFUSE une question posée à un siège piloté par le modèle
(`reserves_declaration_seat_is_not_human`) ; le client ne rend plus les deux boutons que sur un
siège humain, par la même lecture de `player_types` que l'avertissement 20.04.

Le recalage au reset n'est pas décoratif : la tête de file n'est pas toujours le joueur 1, ses
unités inéligibles (FORTIFICATION, plafond de 50 %) étant retirées sans réponse. Même raison au
`change_roster`, TROISIÈME site où la file est (re)bâtie : elle y repart d'un autre roster alors
que le déployeur d'avant le remplacement est restauré tel quel.

**Aucune clé de save nouvelle**, donc aucun bump de format : seuls `current_deployer` et
`current_player` — déjà sauvegardés — changent de valeur.

**Complément du 2026-09-10, même chantier.** Une seule des deux routes de réponse déplaçait le
siège : `apply_reserves_declaration_decision` (siège du modèle) fermait l'étape sans le faire
suivre. Mesuré sur le chemin de l'API — le modèle répond à la question du joueur 2, le siège RESTE
à 2, le client relance un tour IA, le garde `current_player == 2` d'`execute_ai_turn` (lu AVANT le
build de masque) passe, et c'est ce build qui arme la question du JOUEUR 1 pour le modèle :
l'unité 2 du joueur 1 partait en réserves sur décision du bot. Les deux routes passent désormais
par un écrivain unique, `resolve_reserves_declaration_answer` — file amputée, mise en réserves,
siège de la question suivante.

Côté client, ce même recalage peut poser `current_player = 2` dès le reset alors que l'écran de
préparation est encore ouvert (première question due appartenant au bot, file amputée des unités
inéligibles du joueur 1). L'orchestration du tour IA de `BoardWithAPI` n'était gardée par aucun
`deploymentStarted` : le bot répondait à 20.01 avant « Start Deployment », et `change_roster`
était ensuite refusé sur le seul écran où l'humain peut encore choisir son armée. Le déclencheur
lit maintenant `isPopupVisible`, miroir du filtre humain `isReservesDeclarationPendingFor`. Le
départ différé du tour IA est de plus annulé au démontage du composant — sans quoi le timer
survivait à la sortie de partie et lançait un tour sur un composant mort.

Verrous : `tests/unit/engine/test_reserves_declaration_step_2001.py` (4 tests ajoutés, chaque
défaut réintroduit et constaté rouge ; celui de la route modèle passe par `_process_squad_action`,
le chemin de l'API — le step gym reconstruit le masque et masquerait le défaut),
`frontend/src/utils/strategicReservesUi.test.ts` (siège du camp interrogé) et
`frontend/src/components/BoardWithAPI.test.tsx` (le CÂBLAGE du composant, que le prédicat seul ne
prouvait pas : aucun `POST /api/game/ai-turn` avant « Start Deployment », un après).

---

## ✅ 13.06 — le move gym peut finir en hauteur {#verticalite-move-gym}

**Livré le 2026-09-09.** Le move d'escouade du pipeline gym atterrissait TOUJOURS au sol :
`build_rigid_plan` écrivait `SQUAD_RIGID_MOVE_DESTINATION_LEVEL` pour toutes ses figurines et le
pool d'ancre sortait avant son bloc multi-niveaux. Mesuré avant : 710 275 destinations sur 6
épisodes, **aucune** à l'étage, alors que les deux terrains d'entraînement portent 8 étages chacun.

Ce qui change : une escouade **déclare** (13.06, point de choix `ascent_declaration`, sur les
emplacements `CHOICE_*` existants — zéro action nouvelle) qu'elle finira en hauteur, puis chaque
figurine finit au niveau résolu à SA case d'arrivée. Une escouade à cheval sol/étage est un plan
légal (03.03 tolère 5" de dénivelé), pas un cas limite. Le coût vertical est facturé **à la
figurine qui monte**, dans son propre budget de trajet — jamais en forfait au bloc : la pénalité de
descente n'en est pas le miroir (elle dépend du départ, la montée dépend de l'arrivée).

**Sans déclaration, tout le pipeline est bit-à-bit celui d'avant** — c'est ce qui borne le lot.

**Impose un retrain `--new`** : `obs_size` 16971 → 17055 (`max_floor_height`, `has_ground_model`,
`elevated`) et `GRID_CHANNELS` 11 → 12 (`occupant_level`). Sans ces features la montée serait un
état CACHÉ à effet sur la récompense (+1 BS de Plunging Fire 22.05, coût de descente au move
suivant) — le motif d'aliasing qui a déjà coûté un run à ce projet.

**Coût du point de choix, mesuré et resserré (2026-09-09)** : la question « montes-tu ? »
consomme un step d'épisode. Armée sur la seule distance à vol d'oiseau, elle prenait **9,1 % des
steps** (52 sur 572 joués). La borne d'armement déduit désormais le coût de montée — condition
NÉCESSAIRE, puisque le trajet réel est toujours >= la distance à vol d'oiseau, donc elle ne peut
écarter que des questions dont la réponse ne pouvait être que « non » : **5,3 %** (30 sur 561),
à rendement de montée inchangé (0,8 %). Une borne fondée sur le pool de move réel a été mesurée
et écartée : elle n'en retire que 2 sur 52, le pool de sol étant vaste — ce qui mord, c'est le
budget vertical, pas l'accès au plancher.

**Rendement mesuré, à connaître avant d'espérer** : sur 3 parties gym à x1, déclaration toujours
acceptée, **62 cellules sur 7 408** offertes par le masque (0,8 %) mettent au moins une figurine à
l'étage. La verticalité est désormais *jouable*, elle n'est pas *fréquente* : à x1 un socle ne tient
que sur 34 des 72 cases d'étage de `terrain-mc1` (13.06 interdit tout débordement du bord), et la
montée coûte 3" sur un MOVE de 6".

**Correctifs de revue (2026-09-09)** : deux défauts de ce lot, corrigés avant tout retrain.
L'érosion du masque bornait au niveau 0 une figurine qui PART d'un étage et y RESTE, quand la
validation la borne au niveau de son plan — une figurine ennemie postée à l'étage était donc
invisible du masque, et une ennemie au sol lui retirait des destinations légales. Les deux côtés
lisent désormais le même niveau. Et le mémo `floor_level_by_cell`, clé par `id(terrain_areas)`,
ne retenait pas la liste : une adresse recyclée à signature de forme identique aurait servi la
carte de niveaux d'un autre terrain, en silence.

Reste ouvert : la **charge**, le **pile-in** et la **consolidation** gardent leur destination au
sol (`SQUAD_RIGID_MOVE_DESTINATION_LEVEL`), et **FLY + étages** reste hors périmètre — le pool
d'ancre renvoie avant son bloc multi-niveaux quand la traversée est active, exclusion préexistante.

---

## ✅ 13.09 — le statut « caché » suit les pertes et les tirs {#hidden-fraicheur}

**Livré le 2026-09-08 (option C).** Change les parties jouées : `--new` obligatoire pour tout modèle
entraîné avant ce correctif.

13.09 décrit un état **continu** — « a model is hidden WHILE all of the following apply » — mais le
moteur ne posait le drapeau qu'au début de la phase de tir, et la porte 13.09 du pool de cibles
lisait cette valeur gelée. Une escouade dont la dernière figurine exposée mourait en cours de phase
restait ciblable au-delà de la portée de détection. Ce n'est pas un cas de bord : les pertes sont
allouées en priorité à la figurine la plus proche de l'ennemi, donc à l'exposée.

Le statut est désormais rafraîchi dans `destroy_model`, **choke-point unique** de retrait de
figurines — donc pour les huit causes de mort, mêlée comprise, et non par un appel ajouté sur le
chemin du tir. `compute_hidden_status_for_unit` porte le calcul d'une escouade et
`compute_hidden_statuses` n'en est plus que la boucle : une seule implémentation des gardes 13.09,
aucun chemin parallèle. Le placement est contraint des deux côtés — après le recalcul de l'empreinte,
avant l'invalidation LoS qui purge le cache du pool.

**DEUX déclencheurs, un par membre de la règle** — correction de périmètre du 2026-09-08 : la
rédaction initiale n'en voyait qu'un, et s'y tenir fermait la règle à moitié.

1. **Membre géométrique** (les figurines vivantes) → `destroy_model`, décrit ci-dessus.
2. **Membre « did not make one or more ranged attacks during this turn »** →
   `end_activation(arg3="SHOOTING")` (`generic_handlers.py`), seul site d'alimentation de
   `units_shot` et donc seul déclencheur possible de ce membre. Sans lui, une escouade qui tirait
   depuis une zone obscurante restait marquée cachée jusqu'à la fin de la phase — 42 activations de
   tir sur 682 sur 20 épisodes. Le rafraîchissement passe par la fonction de règle plutôt que par
   un `hidden = False` écrit sur place : l'issue y est déterministe, mais la coder en dur ouvrirait
   un second endroit où vit 13.09.

   **Portée exacte de ce second déclencheur**, mesurée et non extrapolée : c'est un durcissement,
   pas la correction d'un ciblage aujourd'hui atteignable. `shooting_build_activation_pool` filtre
   sur `current_player`, donc seul le joueur actif tire pendant sa phase et le statut périmé de ses
   propres escouades est réécrit par le balayage complet au début de la phase adverse. Ce que le
   déclencheur apporte : un état exact entre-temps pour les quatre lecteurs de `unit['hidden']` et
   pour l'affichage PvP, et la clause fermée par avance pour tout tir hors de son propre tour.

**Contrat D1 étendu dans le temps** : `test_d1_survives_a_loss_mid_phase`
(`test_squad_obs_hidden_enemies.py`) vérifie que l'observation et le pool basculent ensemble après
une perte, sans rejouer le balayage de début de phase. Le membre « a tiré » a son propre couple
rouge/vert dans `test_hidden_1309_previous_turn.py` — `test_shooting_breaks_hidden_at_once` et sa
contre-épreuve `test_charging_does_not_break_hidden`, qui interdit un rafraîchissement posé sur
toute fin d'activation. Le balayage complet reste en place au début de la phase de tir et à chaque
sérialisation PvP.

**Limite connue, hors périmètre** : aucun MOUVEMENT ne rafraîchit le drapeau — il reste périmé
pendant le move et après un pile-in adverse. C'est la raison pour laquelle l'observation continue de
recalculer 13.09 à chaud plutôt que de lire `unit['hidden']`.

---
