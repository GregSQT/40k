# Archives soutien — livraisons descendues de l'index

| Date | Chantier | Sujets · Fichier |
|---|---|---|
| 2026-08-19 | ✅ _charge_budget_subhex unit= optionnel (2026-08-19) — paramètre unit= rendu optionnel, perf micro | tests · — |
| 2026-08-19 | ✅ couverture deploy_squad_destinations + select_rule_choice (2026-08-19) — tests humain pour ces deux paths | tests · — |
| 2026-08-19 | ✅ simplification fixture deploy_game (2026-08-19) — retrait assertion vacuuse | tests · — |
| 2026-08-20 | ✅ deep merge game_rules dans build_engine_config (2026-08-20) — fusion profonde game_rules seul ; verrou rouge/vert ; 4 clés consolidation_trigger_range redondantes retirées | tests · — |
| 2026-08-20 | ✅ généraliser fusion profonde à toutes sections dict dans build_engine_config (2026-08-20) — _deep_merge_section appliqué à toutes les clés dict, pas seulement game_rules | tests · — |
| 2026-08-19 | ✅ isolation _deployment_slot_order +5/+6 (2026-08-19) — couverture isolation slot order ; 5-6 tests supplémentaires (test-deployment-slot-order-isolation) | tests · — |
| 2026-08-19 | ✅ docstring/commentaire test_deployment_slot_order_strategies corrigé (2026-08-19) — commentaires erronés alignés sur l'intention du test | tests · — |
| 2026-08-21 | ✅ gate roadmap fix-roadmap-gate-tests (2026-08-21) — tests check_roadmap_declared corrigés | tests+infra · — |
| 2026-08-21 | ✅ 5 pannes isolation xdist + _uc occupied_hexes vide (2026-08-21) — occupied_hexes=set() → {(col, row)} dans 14 helpers tir/fight + garde moteur + isolation module W40K_BOARD_PATH | tests · — |
| 2026-08-21 | ✅ simplify duplication test_reserves_full_episode (2026-08-21) — extraire charge_range = CHARGE_THRESHOLD_INCHES * ish | tests · — |
| 2026-08-21 | ✅ placement control resolution-agnostique dans test_reserves (2026-08-21) — fix placement control resolution-agnostique | tests · — |
| 2026-08-21 | ✅ 4 findings code-review test_reserves_full_episode (2026-08-21) — 4 corrections code-review sur test_reserves_full_episode | tests · — |
| 2026-08-21 | ✅ consolider _uc AI-side → units_cache_entry dans _fabriques (2026-08-21) — 2 helpers _uc identiques dans tests/unit/ai/ fusionnés en units_cache_entry dans _fabriques.py | tests · — |
| 2026-08-19 | ✅ VALUE/REQUISITION_COST séparés ED obstacle 7 (2026-08-19) — coût et valeur des unités ED dissociés en deux champs distincts | services · — |
| 2026-08-19 | ✅ require_key slot_picks T1 (2026-08-19) — ed_state.get(slot_picks)+fallback remplacé par require_key ; absent = ConfigurationError ; 2 tests rouge/vert | services · — |
| 2026-08-19 | ✅ Endless Duty obstacles 5+6 levés (2026-08-19) — ILLUSTRATION_RATIO sur 18 fiches TS ; BASE_SHAPE/BASE_SIZE/MODEL_HEIGHT/orientation/level émis par _build_unit_from_registry ; MOVE+RNG convertis en subhex ; slot mapping par ID réel ; _load_allowed_profiles_by_slot dédupliqué ; 9 tests verts | services+front · — |
| 2026-08-20 | ✅ corriger IDs 101#8/9, EZ dynamique, doublon (2026-08-20) — test_analyzer_coherency_ghost_opposite_camp : IDs figurines et EZ corrigés, doublon supprimé | tests · — |
| 2026-08-20 | ✅ _fought_line embed [MODEL_TYPES:] — paramètre mort unit_type actif, symétrie _fight_body_line (2026-08-20) | tests · — |
| 2026-08-20 | ✅ §2.2 collision charge après mort ancre cible (2026-08-20) — `test_conformite_03_01_09_05` : destination bloquée même si l'ancre cible meurt avant le commit charge ; verrou rouge/vert | tests · — |
| 2026-08-20 | ✅ Purge tests non-verrou sentinel skip (2026-08-20) — tests non-verrou et imports pytest morts supprimés dans suite charge | tests · — |
| 2026-08-20 | ✅ Fix conformité 03.01/09.05 isolation (2026-08-20) — verrous contre-épreuve renforcés et exclusion isolation corrigée | tests+moteur · — |
| 2026-08-23 | ✅ verrou combat à vide sans pending_fight_weapon_select (2026-08-23) — test_combat_a_vide_ne_pose_pas_pending_fight_weapon_select : squad pool 12.04, cibles mortes → résolution directe sans §0.69 ; rouge/vert prouvés | tests · — |
| 2026-08-24 | ✅ fix-fight-weapon-slot-tests (2026-08-24) — 30 tests rouges corrigés : reward_calculator waiting_for_weapon_select, PENDING_FIGHT_WEAPON_KEY purgé à fin phase fight, x1_selfplay retiré du config, damage_received toujours émis, self_play_snapshot_label, mock build_snapshot_normalizer, fight_weapon_slot/shoot_indirect_slot dans ACTION_FAMILIES, TOTAL_ACTION_SIZE chaîne complète, _weapon code, _stub_rewards patch build_squad_grid, _ranged_episode exige damage_received > 0 | tests · — |
| 2026-08-24 | ✅ fix-pytest-errors (2026-08-24) — hex_utils + reward_calculator + test_reward_calculator corrigés | tests+infra · — |
| 2026-08-24 | ✅ fix pyright test files + once_claim avant acting_unit (2026-08-24) — 5 erreurs pyright tests corrigées ; once_claim posé avant check acting_unit dans _calculate_coherency_penalty_per_turn et _calculate_objective_reward_per_turn | tests+moteur · — |
| 2026-08-24 | ✅ simplify once_claim test helpers + invariant comment (2026-08-24) — helpers de test once_claim simplifiés, commentaire invariant ajouté | tests · — |
| 2026-08-24 | ✅ simplify reward_mapper (2026-08-24) — simplify + cleanup : 86 lignes retirées, signature clarifiée, tests mis à jour | tests+ai · — |
| 2026-08-24 | ✅ fix(types) pyright test_expected_damage (2026-08-24) — 12 erreurs pyright corrigées ; signature expected_damage à 2 args | tests · — |
| 2026-08-24 | ✅ fix(tests) clé 'code' armes synthétiques (2026-08-24) — champ code: ajouté dans _weapon() pour aligner les fixtures sur le schéma attendu | tests · — |
| 2026-08-24 | ✅ fix(tests) 4 findings code-review test_expected_damage (2026-08-24) — chemin mêlée, branche hp≤0, frontière entière, nb chaîne couverts ; 11 tests verts | tests · — |
| 2026-08-26 | ✅ purge erreurs logs check_ai_rules/pytest/pyright (2026-08-26) — 18 fichiers corrigés, 0 erreur après correction | tests+infra · — |
| 2026-08-26 | ✅ fix 119 tests rouges bugs A–O (2026-08-26) — charge id, unit_by_id fixtures, analyzer, obs, rollout ; suite verte | tests · — |
| 2026-08-27 | ✅ fix(ai): ep_offset=0 ajouté aux tâches de test manquantes (2026-08-27) | tests · — |
| 2026-08-24 | ✅ fix clé 'code' manquante dans les armes synthétiques de test (2026-08-24) — 88 fichiers de test : dicts armes construits à la main reçoivent un code stable ; require_key shared_utils:8426 ne lève plus ConfigurationError sur les tests | tests · — |
| 2026-08-26 | ✅ verrou cache _cbvp_key inclut intent (2026-08-26) — 2 tests TestChargeBuildValidPlanIntents : séparation clé cache + distinctivité géométrique 2-figurines ; rouge/vert sur mutant | tests · — |
