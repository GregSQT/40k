# Archives Analyzer

| Date | Chantier | Détail |
|---|---|---|
| 2026-08-17 | Trous couverture `hazardous` + `oath_wound` | Branche dispatcher + compteurs `hazardous_mortal_wounds` ; `oath_wound` magnitude depuis EFFECTS ; 5 tests |
| 2026-08-17 | Compteurs `abilities/` | 8 règles × 2 camps, count brut + exposition ; famille A (action_log) + famille B (shot_records) ; 26 tests |
| 2026-08-17 | Proxy count `hit_reroll_exposure` | `max(existant, count > 0)` miroir `oath_wound_bonus` ; 2 tests rouge→vert |
| 2026-08-17 | `damage_exceeds_hp` retiré | Irréalisable par construction ; remplacé par test moteur |
| 2026-08-17 | PSYCHIC statut N/A | `_INTERACTION_ONLY_WEAPON_RULES` ; exclu table §1.8 et résumé ; 3 sites |
| 2026-08-17 | Corpus contrôle §1.2–§2.8 | `rules_corpus.json` étendu ; scalaire `#` pour `state_resync` ; 188 tests |
| 2026-08-17 | Marqueur SHOOT 10.02 | `is_shoot_activation_start` dans `is_activation_marker` ; reset début de tour ; 2 tests |
| 2026-08-12 | Conformité moteur — mort fantôme soldée (2026-08-12) | 3 chemins de retrait fixés (cohérence 03.03, MW par socle `str(unit_id)`, réserves timeout) ; tests `test_analyzer_coherency_removal_ghost.py` + `test_analyzer_hazard_models_ghost.py` ; 0 mort fantôme |
| 2026-08-12 | Portée jugée AVANT les pertes | `[TARGET_MODELS:]` → liste survivants post-pertes ; gel au Select Targets step ; 31 verdicts → 0 |
| 2026-08-12 | Engagement jugé AVANT les pertes | Gel état au Select Targets step ; jumeau mêlée 12.04 corrigé |
| 2026-08-12 | Journal nomme figurine allouée | `LOG_GRAMMAR_VERSION` ; 496 lignes non vérifiables → 0 ; → `Documentation/Archives/chantiers/figurine_allouee_nommee_au_journal_2026-08-12.md` |
| 2026-08-12 | Non-allouée contrôle retiré | Faux positifs par construction ; invariant en test moteur |
| 2026-08-12 | Deux familles move soldées 03.01+09.05 | `update_units_cache_position` écrasait `occupied_hexes` sur mort ancre ; fix déjà en place depuis 08-12 |
| 2026-08-12 | CC_NB : 24 → 0 (CLEAVE trouvé) | `[CLEAVE:X]` token absent ; `[BLAST]` jumeau traité |
| 2026-08-11 | Mesure cesse de mentir | 370 → 53 erreurs ; 4 fichiers de test créés |
| 2026-08-18 | ✅ PROJ.1.4 double_pile_in corrigé (2026-08-18) — overrun 12.06 loggué \"OVERRUN PILED IN\", faux positifs éliminés | analyzer · — |
| 2026-08-18 | ✅ models_segment capturé après commit_move (2026-08-18) — faux positifs pile-in éliminés (fight_handler + w40k_core) | analyzer · — |
| 2026-08-18 | ✅ Réserves PvP 04b tests code-review corrigés (2026-08-18) — symétrie garde, formule sentinelle, commentaire xdist | analyzer · — |
| 2026-08-18 | ✅ Borne vert-vacant calculate_hex_distance (2026-08-18) — métrique cohérente avec charge_check_eligibility | analyzer · — |
| 2026-08-19 | ✅ alloc_model_unknown HAZARDOUS/DE (2026-08-19) — grammar 6 + hazardDetails→target_model_id ; alloc_model_id lit [ALLOC_MODEL:] au lieu du legacy ordered_living_mids[0] ; 4 occurrences éliminées | analyzer · — |
| 2026-08-18 | ✅ step_logger [DESPERATE ESCAPE] vs [HAZARDOUS] séparés (2026-08-18) — roll_hazard_for_unit tag distinct 09.07/24.15 | analyzer · — |
| 2026-08-18 | ✅ analyzer_core branche [DESPERATE ESCAPE] (2026-08-18) — _apply_damage_and_handle_death appelée, HP/kill tracking opérationnel ; constante HAZARD_CONTEXT_DESPERATE_ESCAPE partagée | analyzer · — |
| 2026-08-18 | ✅ test_analyzer_hazardous verrou [DESPERATE ESCAPE] vs [HAZARDOUS] (2026-08-18) — test rouge/vert sur branche DESPERATE ESCAPE + seuil source inspect corrigé | analyzer · — |
| 2026-08-18 | ✅ analyzer overrun PILED IN regex (2026-08-18) — handle_fight_move matche OVERRUN PILED IN, faux positifs double_pile_in éliminés | analyzer · — |
| 2026-08-18 | ✅ HAZARDOUS branche action_unit_id stale (2026-08-18) — _hz_unit_id = _dmg_actor_id or action_unit_id ; damage + lookup armurerie sur l'unité de la ligne, pas le header | analyzer · — |
| 2026-08-18 | ✅ analyzer_core _hz_unit_id code mort supprimé + verrou HAZARDOUS unité morte (2026-08-18) — ligne 1702 dupliquée retirée ; test rouge/vert HAZARDOUS→unité morte→damage_missing_unit_hp | analyzer · — |
| 2026-08-19 | ✅ hazardous 0-MW no raise (2026-08-19) — wounds=0 (aucun dé raté) → [NO ALLOC] sans require_key ; analyzer saute _apply_damage si mw==0 (HAZARDOUS + DESPERATE ESCAPE) | step_logger+analyzer · — |
| 2026-08-20 | ✅ Champs manquants `step.log` L11/L12/L15/L26 (2026-08-20) — [DESPERATE ESCAPE]/[ORDERED RETREAT] + Hazard:rolls (L11, 09.07/06.03) ; FNP:saves/seuil+ ×tentatives (L12, 24.12) ; [HAZARDOUS:n] Roll:dice (L15, 24.15) ; [POINT-BLANK] + base+->eff+ généralisé (L26, 10.06) ; 40 tests verts chantier | analyzer · [analyzer.md#champs-step-log](analyzer.md#champs-step-log) |
| 2026-08-20 | ✅ Corpus de règles vérifiable — Lot 6 (2026-08-20) — V4/V8/V13 fermés, 10.02/12.07 câblés, COUVERT 65/267, 0 vert vacant ouvert, 64 tests verts | analyzer · — |
| 2026-08-19 | ✅ Alternance EPISODE END (2026-08-19) — vérification paire (T_{N-1}, T_N) manquante à EPISODE END ; finding /code-review valide ; finding 2 écarté (last_phase=None reset dans turn-change) | analyzer · — |
| 2026-08-20 | ✅ Tests weapon-rules lot2 mêlée/tir (2026-08-20) — verrous rouge/vert pour les règles d'armes lot2 (fight weapon rules) | analyzer · — |
| 2026-08-20 | ✅ phase_seq par joueur — faux négatifs phase_order (2026-08-20) — gate phase_seq indexé par joueur ; élimine 64 faux positifs cross-player phase_order | analyzer · — |
| 2026-08-20 | ✅ Verrou E383 fantôme P1 bloque BFS avance Gretchin P2 hors engagement (2026-08-20) — test BFS pur sans advance_from_adjacent ; mur (36,17) + fantôme (37,17) ; rouge/vert validé | analyzer · — |
| 2026-08-19 | ✅ §2.8/§1.2/§1.4 DEAD-before-SHOOT corrigés (2026-08-19) — `dead_model_positions_episode` dans `freeze_select_targets` restitue géométrie+effectif réels au Select Targets step ; 6013+133+56 faux positifs → 0 ; 3 verrous rouge/vert | analyzer · — |
| 2026-08-19 | ✅ purge stale dead positions on removed={} (2026-08-19) — dead positions purgées quand removed vide (fix-analyzer-stale-dead-positions) | analyzer · — |
| 2026-08-19 | ✅ T1 dead_model_ids_episode requis (2026-08-19) — `alloc_model_id` fourni sans `dead_model_ids_episode` lève ConfigurationError ; verrou rouge/vert | analyzer · — |
| 2026-08-19 | ✅ dead_model_positions_episode cross-activation fix (2026-08-19) — setdefault accumulation périmée corrigée par heuristique seuil 20 lignes ; 2 nouveaux verrous rouge/vert intra/cross-activation | analyzer · — |
| 2026-08-19 | ✅ FP familles 1+2 grammaire 4 corrigés (2026-08-19) — token [CLOSE-QUARTERS] override is_close_quarters + shooter_engaged_with_target ; 7 tests rouge/vert ; famille 3 déjà close ; famille 4 = bug moteur (advance E383 : 103#8 dépasse budget 9) | analyzer · — |
| 2026-08-19 | ✅ doublon fam2 cq-grammar4-token remplacé par scénario grammar=3 (2026-08-19) — test cq_grammar4 dédoublonné | analyzer · — |
| 2026-08-19 | ✅ lot2 rules — compteurs usage ANTI-X/TORRENT/LETHAL HITS/IGNORES_COVER/EXTRA_ATTACKS (2026-08-19) ; fix DW threshold ANTI-X:N+ (N<6) ; Roll:1 HAZARDOUS counter ; validité TORRENT+LETHAL HITS ; 16 tests rouge/vert | analyzer · — |
| 2026-08-20 | ✅ lot3 rules unités — charge_impact (seuil/dégât), reroll_charge, reroll_1_save_fight, oath_target, CTP, leader/support ; waaagh_invul retiré du snapshot EFFECTS ; 9 tests rouge/vert (2026-08-20) | analyzer · — |
| 2026-08-20 | ✅ phase_seq par joueur (2026-08-20) — séquences vérifiées par joueur indépendamment ; élimine 64 faux positifs phase_order (FIGHT P1 avant CHARGE P2 dans le même tour) ; 2 verrous rouge/vert | analyzer · — |
| 2026-08-20 | ✅ fix phase_order faux positifs gate séquence joueur sur COMMAND (2026-08-20) — analyzer_core gate phase_seq indexé par joueur ; faux positifs cross-player éliminés | analyzer · — |
| 2026-08-20 | ✅ suppression player_alternation_violations (2026-08-20) — check retiré : 40K priorité par roll-off, aucune alternance stricte ; 204 faux positifs éliminés | analyzer · — |
| 2026-08-20 | ✅ verrou P1 priorité multi-tours (2026-08-20) — test verrou : P1 ouvre COMMAND sur 3 tours consécutifs → 0 violation ; docstring à jour | analyzer · — |
| 2026-08-20 | ✅ §2.9 faux positif DEAD en phase adverse (2026-08-20) — lignes DEAD exclues du suivi phase_seq_current_turn ; unité P1 tuée pendant SHOOT P2 ne pollue plus la séquence P1 ; verrou rouge/vert | analyzer · — |
| 2026-08-20 | ✅ [ENGAGED_MODELS: N/total] sur lignes CHARGED (2026-08-20) — step_logger + charge_handlers émettent le ratio engagés/total sur chaque ligne CHARGED ; verrou intégration | step_logger+moteur · — |
| 2026-08-20 | ✅ DEAD@COMMAND fix §2.9 + purge reset phase sur DEAD events (2026-08-20) — dead lines exclues du suivi phase_seq_current_turn ; verrou rouge/vert | analyzer · — |
| 2026-08-20 | ✅ is_pair dans action_log + [PAIR] step.log (2026-08-20) — charge multi-cibles loggue explicitement le flag is_pair ; verrou rouge/vert | step_logger · — |
| 2026-08-20 | ✅ Verrou [PAIR] token step_logger charge/charge_fail (2026-08-20) — is_pair=True → [PAIR] dans la ligne ; is_pair=False/absent → absent ; verrou rouge/vert | step_logger · — |
| 2026-08-23 | ✅ Faux positifs flee-unengaged + collisions inter-camps (2026-08-23) — fallback ancre si surviving_start_models retourne position périmée (frontale tuée avant fall-back) ; skip paires ennemies dans move_normal/move_fled/charge ; bypass [DESPERATE ESCAPE] quand géométrie inaccessible ; 53 FP éliminés, 8+3 tests verts | analyzer · — |
| 2026-08-23 | ✅ Filtre joueur manquant boucle ADVANCE (2026-08-23) — shoot_handler ADVANCE ne filtrait pas les ennemis dans real_colliding_units contrairement à MOVE/FLED/CHARGE ; 3 tests rouge/vert (MOVE+MOVE alliés, ADVANCE+ennemi, ADVANCE+allié) | analyzer · — |
| 2026-08-23 | ✅ Simplify collision filter (2026-08-23) — hoist mover_player hors boucle (4 sites) ; suppression garde always-True FLED ; _move(player=) dans les tests | analyzer · — |
| 2026-08-25 | ✅ corpus lot7 — 5 règles ABSENT_LOGGABLE câblées (TORRENT, LETHAL_HITS, BLAST, 20.03, charge_impact) (2026-08-25) | analyzer · — |
| 2026-08-24 | ✅ collision ingress-ennemi détectée dans _handle_move (2026-08-24) — unité arrivée des réserves (action=ingress) au même hex qu'une unité en déplacement le même tour désormais reportée dans unit_position_collisions | analyzer · — |
