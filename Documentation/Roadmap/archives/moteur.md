# Archives Moteur

| Date | Chantier | Détail |
|---|---|---|
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
