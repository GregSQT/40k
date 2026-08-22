# Roadmap Index — Ordre global du travail

> **Source unique de priorité.** Ce fichier tranche l'ordre, les fichiers sujets tranchent le
> contenu. Historique d'un sujet : `archives/<sujet>.md`. `archives/ROADMAP.md` est un FOSSILE
> gelé (l'ancien fichier monolithique) : ne pas le lire en session, ne plus le mettre à jour.
>
> **Règles d'arbitrage :** Code > décision datée > priorité ici > tout autre doc.
> Conflit résiduel → demander à l'utilisateur.
>
> **Discipline.** Ouvrir = ajouter une ligne ici D'ABORD. Livrer = marquer ✅ ici + vider/archiver
> dans le fichier sujet, dans la même livraison.
>
> **Outillage.** `python3 scripts/check_doc_references.py` contrôle ce fichier, les fichiers
> sujets et les deux contrats permanents (renvois, liens, valeurs recopiées, ancres, sortes),
> et vérifie qu'aucun chantier ouvert de `Documentation/Implémentation/A_faire/` n'est devenu
> inatteignable depuis ce fichier — un document que plus aucun fichier sujet ne cite n'est plus
> priorisé, il est seulement stocké.
> La porte de fusion `scripts/check_roadmap_declared.py` (hook `prepare-commit-msg`, versionné
> dans `.githooks/`) : une fusion dans `main` est refusée quand **2** chantiers ont été livrés
> sans que ce fichier bouge. Se débloquer : écrire la ligne du chantier puis `git add` (l'index
> vaut déclaration) ; fusion hors chantier : `ROADMAP_GATE=off git commit`.
>
> **Contrats permanents** (jamais archivés, hors roadmap) :
> `Documentation/Implémentation/Replay.md` (contrat `step.log`, pipeline replay) et
> `Documentation/Implémentation/analyzer_couverture.md` (matrice règle → contrôle → champs de
> log) — relus à chaque livraison qui touche le journal.
>
> **Exceptions actées** (numérotées ici et nulle part ailleurs) : `Bot_refactor.md` vit à la racine d'`Documentation/Implémentation/` au lieu d'`A_faire/` (chantier vivant, chemin demandé) ; `archives/v11.md` porte l'historique du programme V11 entier et sert d'archive au sujet `v11_chemin_critique.md`.
>
> **Pendant entraînement.** `⚡` = peut démarrer sans interrompre un run (ne touche pas
> `config/**/*.json`, ne modifie pas le moteur). `🚫` = ne pas démarrer : risque de biaiser le
> run ou conflit direct avec le processus d'entraînement.

---

## Direction — le fil

**CAP : la démo de financement** — un agent RL crédible sur les deux rosters retenus (Space
Marines / Orks, décision 2026-07-19), prouvé par une mesure quantitative (win-rate `x1_long`
contre le panel) et une validation qualitative par un joueur externe.

Tout chantier sert un jalon ci-dessous, ou attend. Les jalons sont séquentiels ; le soutien
(analyzer, security, infra, hygiène doc) avance en parallèle quand un jalon le réclame.

| Jalon | Contenu | Critère de sortie |
|---|---|---|
| **J1 — Pipeline prouvé, ligne de base** ✅ | Run `x1_long --new` terminé le 2026-08-20 ; ligne de base REJOUÉE le 2026-08-21 sur `robust_0.8463` (post-rupture §12.15) : combined agent `0,8567`, pire bot `attrition = 0,810` ; reference bots mesurés bot-contre-bot (balanced `0,168`, denial `0,155`, reactive `0,139`) ; `benchmark_floor` remis à `0,90` le 2026-08-20 (le `0,049` mélangeait les sémantiques, re-pose en R0a) | Critères de [training.md#run-verif](training.md#run-verif) verts ; ligne de base panel rejouée ✅ |
| **J2 — Le gym décide tout** | Chemin critique lignes 1–4 (P3-5, P3-6, P3-8, P4) ; le dégel de `TOTAL_ACTION_SIZE` qu'elles ouvrent embarque P3-0 | Plus aucune décision de jeu jouée par une heuristique à la place de l'agent, hors optionnels statués par mesure de regret |
| **J3 — Mesure de référence** | Chemin critique lignes 5–6 : profil de validation P5, puis `x1_long` (~20 h) | LE chiffre officiel du projet — solde §0.14, §0.67 et le critère T6 (via §10.6) |
| **J4 — Dépasser la mesure** | Self-play §0.59 (ligne 7), capacités 06, É9 second scénario — priorisés selon ce que la mesure révèle | Win-rate au-dessus de la mesure de référence, reproductible |
| **J5 — Démo** | Validation qualitative §10.6 volet 2 (joueur externe), validations navigateur front soldées | Un externe joue contre l'agent et le trouve crédible ; le front tient la partie de bout en bout |

---

## J1 ✅ Terminé — 2026-08-20

| Priorité | Sujets | Chantier | Fichier |
|---|---|---|---|
| ✅ | training+bot | Run `x1_long --new` terminé 2026-08-20 — critères pipeline VERTS, `benchmark_floor` posé à 0,049 | [bot.md#etape8](bot.md#etape8) |

---

## 🔴 URGENCE — Curriculum : adversaires et étalons (décision 2026-08-21)

**Décision utilisateur du 2026-08-21 — passe devant les lignes J2.** Les instruments
d'évaluation sont saturés (reference_* battus 93-100 % dès 10k épisodes, `vs_tactical` à 1,00
dès 30k) : R0a/R0b se livrent AVANT le prochain run long, puis le curriculum R1→R3 enchaîne
(R2 = ligne 7 du chemin critique, R3 = chantier récompense). tactical reste gelé (§0.55/D10).
Détail : `Documentation/Implémentation/A_faire/curriculum_adversaires_etalons.md`.

| # | Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|---|
| 1 | bot | 🟡 **R0a** §3.1-§3.4 livrés 2026-08-21 ; §3.5 balayage 2026-08-22 (abandon) ; **R0a-bis livré 2026-08-22** : 3 défauts 1er ordre fixés + calibration (balanced 0,306 / denial 0,297 / reactive 0,280 à 20 ép.) — fourchette [0,40 ; 0,60] non franchie, `benchmark_floor` reste à 0,90 ; reste re-pose gate (décision utilisateur) ; **corrections /code-review + /simplify 2026-08-22** : 4 findings review appliqués (`_KILL_SENTINEL`, `_zone_contest_pull`, double-scan reactive, docstring) + 4 cleanups simplify (sentinel denial, if/else pull, dedup test gs, docstring) | [bot.md#r0a-references](bot.md#r0a-references) | ⚡ (la re-pose du gate touche la config : entre deux runs) |
| 2 | bot+training | ✅ **R0b** Échelle de checkpoints figés en éval (`vs_ckpt_*`) — livré 2026-08-21 | [bot.md#r0b-echelle](bot.md#r0b-echelle) | ⚡ |
| 3 | training | **R1→R3** Séquence des runs du curriculum (un levier par run) | [training.md#curriculum](training.md#curriculum) | 🚫 |

---

## J2–J4 — Chemin critique vers la mesure de référence

Ordre imposé — ne pas réorganiser sans décision explicite.

| # | Sujets | Chantier | Fichier | Bloqueur | ⚡/🚫 |
|---|---|---|---|---|---|
| 1 | moteur+training | **P3-5** Pile-in / consolidation | [v11_chemin_critique.md#p3-5](v11_chemin_critique.md#p3-5) | P5 à trancher ([v11_chemin_critique.md#p5](v11_chemin_critique.md#p5)) | 🚫 |
| 2 | training+moteur | **P3-6** Move-after-shooting + reactive move | [v11_chemin_critique.md#p3-6](v11_chemin_critique.md#p3-6) | — | 🚫 |
| 3 | training | **P3-8** Optionnels à statuer | [v11_chemin_critique.md#p3-8](v11_chemin_critique.md#p3-8) | — | 🚫 |
| 4 | training+moteur | **P4** Observation de support | [v11_chemin_critique.md#p4](v11_chemin_critique.md#p4) | — | 🚫 |
| 5 | training | **P5** Validation par tranche (profil manquant) | [v11_chemin_critique.md#p5](v11_chemin_critique.md#p5) | — | 🚫 |
| 6 | training | Mesure de référence `x1_long` | [v11_chemin_critique.md#mesure](v11_chemin_critique.md#mesure) | — | 🚫 |
| 7 | training+bot | Self-play §0.59 (livré, jamais exécuté) | [v11_chemin_critique.md#selfplay](v11_chemin_critique.md#selfplay) | — | 🚫 |

---

## J4 — Capacités

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| moteur+training | **06** Armageddon abilities — 0/6 passes | [capacites.md#armageddon-06](capacites.md#armageddon-06) | 🚫 |

---

## Suspendus — ne pas commencer avant leur jalon

| Sujets | Chantier | Fichier | Jalon | ⚡/🚫 |
|---|---|---|---|---|
| moteur | **P3-0** Cohérence 03.03 — choix joueur/agent | [moteur.md#p3-0](moteur.md#p3-0) | Prochain dégel `TOTAL_ACTION_SIZE` (attendu en J2 ; celui du 2026-08-17 est passé sans lui) | 🚫 |
| moteur | **T7** Unification validation déploiement | [moteur.md#t7](moteur.md#t7) | Fix faux — re-analyser avant | 🚫 |
| moteur | **Phase B** Observation des niveaux | [moteur.md#phase-b](moteur.md#phase-b) | Phase A' validée + LoS 3D complet | 🚫 |
| training+bot | **É9** Second siège + second scénario | [training.md#e9](training.md#e9) | J4 — entraînement bot satisfaisant | 🚫 |
| training+bot | Validation qualitative §10.6 volet 2 | [bot.md#validation-externe](bot.md#validation-externe) | J5 — requis pour la démo | ⚡ |
| bot | MCTS à l'inférence §10.7 (plan B anti-coups-absurdes) | [bot.md#mcts-inference](bot.md#mcts-inference) | Après J3, seulement si la démo l'exige | 🚫 |

---

## Soutien — backlog hors jalons

### Prêt à démarrer

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| analyzer | ✅ PROJ.1.4 double_pile_in corrigé (2026-08-18) — overrun 12.06 loggué \"OVERRUN PILED IN\", faux positifs éliminés | — | ⚡ |
| analyzer | ✅ models_segment capturé après commit_move (2026-08-18) — faux positifs pile-in éliminés (fight_handler + w40k_core) | — | ⚡ |
| analyzer | ✅ Réserves PvP 04b tests code-review corrigés (2026-08-18) — symétrie garde, formule sentinelle, commentaire xdist | — | ⚡ |
| analyzer | ✅ Borne vert-vacant calculate_hex_distance (2026-08-18) — métrique cohérente avec charge_check_eligibility | — | ⚡ |
| analyzer | ✅ alloc_model_unknown HAZARDOUS/DE (2026-08-19) — grammar 6 + hazardDetails→target_model_id ; alloc_model_id lit [ALLOC_MODEL:] au lieu du legacy ordered_living_mids[0] ; 4 occurrences éliminées | — | ⚡ |
| analyzer | ✅ step_logger [DESPERATE ESCAPE] vs [HAZARDOUS] séparés (2026-08-18) — roll_hazard_for_unit tag distinct 09.07/24.15 | — | ⚡ |
| analyzer | ✅ analyzer_core branche [DESPERATE ESCAPE] (2026-08-18) — _apply_damage_and_handle_death appelée, HP/kill tracking opérationnel ; constante HAZARD_CONTEXT_DESPERATE_ESCAPE partagée | — | ⚡ |
| analyzer | ✅ test_analyzer_hazardous verrou [DESPERATE ESCAPE] vs [HAZARDOUS] (2026-08-18) — test rouge/vert sur branche DESPERATE ESCAPE + seuil source inspect corrigé | — | ⚡ |
| analyzer | ✅ analyzer overrun PILED IN regex (2026-08-18) — handle_fight_move matche OVERRUN PILED IN, faux positifs double_pile_in éliminés | — | ⚡ |
| analyzer | ✅ HAZARDOUS branche action_unit_id stale (2026-08-18) — _hz_unit_id = _dmg_actor_id or action_unit_id ; damage + lookup armurerie sur l'unité de la ligne, pas le header | — | ⚡ |
| analyzer | ✅ analyzer_core _hz_unit_id code mort supprimé + verrou HAZARDOUS unité morte (2026-08-18) — ligne 1702 dupliquée retirée ; test rouge/vert HAZARDOUS→unité morte→damage_missing_unit_hp | — | ⚡ |
| moteur+analyzer | ✅ step_logger event [DEAD] + pré-capture [MODELS:] tir/move (2026-08-19) — destroy_model émet un event dead dans action_logs pour toute raison ; [MODELS:] SHOOT/MOVE pré-capturés avant effets (hazardous, etc.) | — | ⚡ |
| tests | ✅ _charge_budget_subhex unit= optionnel (2026-08-19) — paramètre unit= rendu optionnel, perf micro | — | ⚡ |
| tests | ✅ couverture deploy_squad_destinations + select_rule_choice (2026-08-19) — tests humain pour ces deux paths | — | ⚡ |
| tests | ✅ simplification fixture deploy_game (2026-08-19) — retrait assertion vacuuse | — | ⚡ |
| tests | ✅ deep merge game_rules dans build_engine_config (2026-08-20) — fusion profonde game_rules seul ; verrou rouge/vert ; 4 clés consolidation_trigger_range redondantes retirées | — | ⚡ |
| tests | ✅ généraliser fusion profonde à toutes sections dict dans build_engine_config (2026-08-20) — _deep_merge_section appliqué à toutes les clés dict, pas seulement game_rules | — | ⚡ |
| moteur | ✅ charge_succeeded préservé lors des cascades de phase (2026-08-20) — merge {**result, **phase_init_result} au lieu de remplacement complet dans _process_squad_action ; verrou rouge/vert 3 tests | — | ⚡ |
| step_logger+analyzer | ✅ hazardous 0-MW no raise (2026-08-19) — wounds=0 (aucun dé raté) → [NO ALLOC] sans require_key ; analyzer saute _apply_damage si mw==0 (HAZARDOUS + DESPERATE ESCAPE) | — | ⚡ |
| moteur+analyzer | ✅ dead events step.log + pré-capture tir protégée (2026-08-19) — _build_step_log_details mappe model_id/reason ; _emit_squad_shoot_log try/except ConfigurationError ; is None strict | — | ⚡ |
| analyzer | ✅ Champs manquants `step.log` L11/L12/L15/L26 (2026-08-20) — [DESPERATE ESCAPE]/[ORDERED RETREAT] + Hazard:rolls (L11, 09.07/06.03) ; FNP:saves/seuil+ ×tentatives (L12, 24.12) ; [HAZARDOUS:n] Roll:dice (L15, 24.15) ; [POINT-BLANK] + base+->eff+ généralisé (L26, 10.06) ; 40 tests verts chantier | [analyzer.md#champs-step-log](analyzer.md#champs-step-log) | ⚡ |
| bot | ✅ Étalon panel ré-épinglé (2026-08-21) — `robust_0.8692` ne charge plus depuis `charge_pair_net` (`d5ddffb5`), référence §12 passée à `robust_0.8463` ; ligne de base §12.14 marquée pré-rupture | [bot.md#etape8](bot.md#etape8) | ⚡ |
| bot | ✅ Fix code-review benchmark_bots (2026-08-20) — import DESTINATION_SHORTLIST depuis bot_doctrines, précalcul geo_scores, mocks morts require_unit_from_cache supprimés | — | ⚡ |
| bot | ✅ Scoring multi-critères reference bots + fix charge/CONTEST (2026-08-20) — 3 bots (balanced/denial/reactive), 4 scénarios holdout, fix charge/CONTEST, benchmark gate §4.D | [bot.md#etape8](bot.md#etape8) | ⚡ |
| analyzer | ✅ Corpus de règles vérifiable — Lot 6 (2026-08-20) — V4/V8/V13 fermés, 10.02/12.07 câblés, COUVERT 65/267, 0 vert vacant ouvert, 64 tests verts | — | ⚡ |
| bot | ✅ bot_ranking parallélisé ProcessPoolExecutor (2026-08-20) — temps de tournoi réduit | — | ⚡ |
| moteur | ✅ fix desperate_escape gym : purger _flee_mode/_desperate_escape_rolls sur unité morte (2026-08-20) — 3 tests verts, cycle rouge/vert | — | ⚡ |
| moteur | ✅ simplify desperate_escape : .pop() symétrique PvP + helper test _engine_battle_shocked (2026-08-20) — 3 tests verts | — | ⚡ |
| moteur+bot | ✅ simplify charge_handlers allTargetCoords via get_unit_position + Counter dupes bots (2026-08-20) — 2 sites charge_handlers migrés, O(n) détection doublons | — | ⚡ |
| front | ✅ Tests front T7+T8–T13 livrés + T11 hook complet (2026-08-19) — 82 tests vitest verts (Couche B), Playwright 14 scénarios (T12-1..T12-8), hook __W40K_TEST__ étendu (movePreviewHexes/blinkTargetUnitIds/currentMode/hexToScreenCoords), data-testid board-viewport+board-canvas-container | [front.md#tests](front.md#tests) | ⚡ |
| front | ✅ buildTargetPreviewStats extraite (2026-08-19) — fonction pure testable hors jsdom, supprime le calcul inline redondant overallProbability/expectedDamage dans useEngineAPI ; 4 nouveaux tests rouge/vert | — | ⚡ |
| front | ✅ Tests review-test-assertions corrigés (2026-08-19) — assertions test HazardWarning et BoardWithAPI nettoyées | — | ⚡ |
| front | ✅ HazardWarningModal + AdvanceWarningModal simplifiés (2026-08-19) — composants nettoyés | — | ⚡ |
| front | ✅ woundTargetFromSTR_T helper + fight blink délégué (2026-08-19) — cascade 4× factorisée en un helper partagé ; fight path blinkingHPBar délègue à calculateCombatOverallProbability | — | ⚡ |
| front | Validations navigateur en attente | [front.md#validations-nav](front.md#validations-nav) | ⚡ |
| training+bot | ✅ Benchmark floor gate §4.D livré (2026-08-18) — 3 bots de référence (balanced/denial/reactive) sur 4 scénarios holdout_regular ; seuil 0.90 après mesure ; `model_gating_enabled` sur x1_long | [v11_chemin_critique.md#benchmark-gate](v11_chemin_critique.md#benchmark-gate) | |
| training+bot | ✅ scenario_bench-01..04 dupliqués supprimés (2026-08-18) — fichiers byte-for-byte identiques aux scenario_bot-01..04, glob fallback ramassait 8 scénarios au lieu de 4, épisodes/scénario divisés par 2 sans contrepartie | — | |
| analyzer | ✅ Alternance EPISODE END (2026-08-19) — vérification paire (T_{N-1}, T_N) manquante à EPISODE END ; finding /code-review valide ; finding 2 écarté (last_phase=None reset dans turn-change) | — | ⚡ |
| analyzer | ✅ Tests weapon-rules lot2 mêlée/tir (2026-08-20) — verrous rouge/vert pour les règles d'armes lot2 (fight weapon rules) | — | ⚡ |
| analyzer | ✅ phase_seq par joueur — faux négatifs phase_order (2026-08-20) — gate phase_seq indexé par joueur ; élimine 64 faux positifs cross-player phase_order | — | ⚡ |
| analyzer | ✅ Verrou E383 fantôme P1 bloque BFS avance Gretchin P2 hors engagement (2026-08-20) — test BFS pur sans advance_from_adjacent ; mur (36,17) + fantôme (37,17) ; rouge/vert validé | — | ⚡ |
| analyzer | ✅ §2.8/§1.2/§1.4 DEAD-before-SHOOT corrigés (2026-08-19) — `dead_model_positions_episode` dans `freeze_select_targets` restitue géométrie+effectif réels au Select Targets step ; 6013+133+56 faux positifs → 0 ; 3 verrous rouge/vert | — | ⚡ |
| analyzer | ✅ purge stale dead positions on removed={} (2026-08-19) — dead positions purgées quand removed vide (fix-analyzer-stale-dead-positions) | — | ⚡ |
| tests | ✅ isolation _deployment_slot_order +5/+6 (2026-08-19) — couverture isolation slot order ; 5-6 tests supplémentaires (test-deployment-slot-order-isolation) | — | ⚡ |
| bot | ✅ Stratégies déploiement 5/6 (2026-08-19) — `centre_hub` + `safe_rear` ajoutées, regret P3-8 partiellement résorbé | — | ⚡ |
| analyzer | ✅ T1 dead_model_ids_episode requis (2026-08-19) — `alloc_model_id` fourni sans `dead_model_ids_episode` lève ConfigurationError ; verrou rouge/vert | — | ⚡ |
| moteur | ✅ require_unit_by_id canonique T0 (2026-08-19) — fonction unique dans game_utils, ConfigurationError si absente, re-exportée depuis combat_utils, importée dans shooting_handlers + w40k_core ; 5 tests rouge/vert | — | ⚡ |
| moteur | ✅ Fix §11.04 budget charge par-figurine gym (2026-08-19) — `_attempt_charge_to_destinations` rejetait pas les destinations roll+extra ; verrou + test rouge/vert | — | ⚡ |
| training | ✅ PLACEMENT_WEIGHTS slots 9/10 couverts (2026-08-19) — hotfix training, slots 9 et 10 ajoutés aux poids de placement | — | ⚡ |
| moteur+training | ✅ Endless Duty obstacles 5+6 levés (2026-08-19) — fix obstacles 5 et 6 du scénario Endless Duty | — | ⚡ |
| tests | ✅ docstring/commentaire test_deployment_slot_order_strategies corrigé (2026-08-19) — commentaires erronés alignés sur l'intention du test | — | ⚡ |
| analyzer | ✅ dead_model_positions_episode cross-activation fix (2026-08-19) — setdefault accumulation périmée corrigée par heuristique seuil 20 lignes ; 2 nouveaux verrous rouge/vert intra/cross-activation | — | ⚡ |
| moteur | ✅ metric= fight_handlers propagé (2026-08-21) — engagement_distance_metric(game_state) passé sur 11 fonctions fight_handlers ; justification singleton fausse documentée dans spatial_relations (commit 2dc65810) ; pattern absorbé par le chantier « primitive porteuse de game_state » | — | ⚡ |
| tests+infra | ✅ gate roadmap fix-roadmap-gate-tests (2026-08-21) — tests check_roadmap_declared corrigés | — | ⚡ |
| moteur | ✅ fix-fight-build-valid-target-pool-metric (2026-08-21) — metric EZ depuis game_state dans build_valid_target_pool | — | ⚡ |
| moteur+tests | ✅ fix-singleton-metric-ez-game-state-primitives (2026-08-21) — `unit_entries_within_engagement_zone` accepte `game_state=` et résout `engagement_distance_metric(game_state)` ; tous call-sites propagent `game_state=` (BFS serrés : pré-calcul `metric=` une fois ; range-checks : sans game_state, intentionnel) ; `_target_locked_by_ally` reçoit `game_state` ; T2 `_count_engaged_models_after_charge` ; 5 tests verrou (un call-site par fichier, mutation ROUGE confirmée) | — | ⚡ |
| moteur+tests | ✅ fix active_socle hors table (2026-08-21) — active_socle non construit quand escouade active hors table ; imports _uc en tête de fichier ; guard col<0 dans units_cache_entry ; consolider 13 helpers _uc → units_cache_entry dans _state_builders ; socle_from_cache_entry via entry_footprint | — | ⚡ |
| tests | ✅ 5 pannes isolation xdist + _uc occupied_hexes vide (2026-08-21) — occupied_hexes=set() → {(col, row)} dans 14 helpers tir/fight + garde moteur + isolation module W40K_BOARD_PATH | — | ⚡ |
| tests | ✅ simplify duplication test_reserves_full_episode (2026-08-21) — extraire charge_range = CHARGE_THRESHOLD_INCHES * ish | — | ⚡ |
| tests | ✅ placement control resolution-agnostique dans test_reserves (2026-08-21) — fix placement control resolution-agnostique | — | ⚡ |
| tests | ✅ 4 findings code-review test_reserves_full_episode (2026-08-21) — 4 corrections code-review sur test_reserves_full_episode | — | ⚡ |
| moteur | ✅ fix type de tir effacé dans 3 chemins PvP (2026-08-21) — type de tir effacé dans les 3 chemins PvP manquants | — | ⚡ |
| infra | ✅ gate roadmap exclut merges tests-only (2026-08-21) — `merge_only_touches_tests` dans `check_roadmap_declared.py` : un merge ne touchant que `tests/` n'est plus compté dans la dette ; 26 tests verts | — | ⚡ |
| tests | ✅ consolider _uc AI-side → units_cache_entry dans _fabriques (2026-08-21) — 2 helpers _uc identiques dans tests/unit/ai/ fusionnés en units_cache_entry dans _fabriques.py | — | ⚡ |
| bot | ✅ Ligne de base §12.14 rejouée sur robust_0.8463 (2026-08-21) — mesure bot_zone_direct sur l'étalon courant post-rupture charge_pair_net ; test_aucune_recopie_dans_scripts rendu dynamique | — | ⚡ |
| moteur | ✅ simplify-reactive-coherency (2026-08-21) — simplification cohérence réactive moteur | — | ⚡ |
| bot | ✅ 4 findings code-review bot_zone_direct (2026-08-21) — bot_units mort retiré, dead defaults _loss_rate, collect×5→×2 par pas, try/except focus_dist | — | ⚡ |
| moteur+services | ✅ Fix review-findings (2026-08-18) — surface refus moteur squad, wsgi leading-comma, message vide | — | |
| services | ✅ VALUE/REQUISITION_COST séparés ED obstacle 7 (2026-08-19) — coût et valeur des unités ED dissociés en deux champs distincts | — | ⚡ |
| moteur+tests | ✅ JSDoc bcKey périmé + test vert vacant buildBoardGeomKey (2026-08-19) — JSDoc corrigé, test vacant renforcé | — | ⚡ |
| services | ✅ require_key slot_picks T1 (2026-08-19) — ed_state.get(slot_picks)+fallback remplacé par require_key ; absent = ConfigurationError ; 2 tests rouge/vert | — | ⚡ |
| services+front | ✅ Endless Duty obstacles 5+6 levés (2026-08-19) — ILLUSTRATION_RATIO sur 18 fiches TS ; BASE_SHAPE/BASE_SIZE/MODEL_HEIGHT/orientation/level émis par _build_unit_from_registry ; MOVE+RNG convertis en subhex ; slot mapping par ID réel ; _load_allowed_profiles_by_slot dédupliqué ; 9 tests verts | — | ⚡ |
| security | ✅ Chantier clos (2026-08-19) — F1–F15 résolues, validation navigateur OK, doc déplacé dans Implémenté/ | [archives/security.md](archives/security.md) | ⚡ |
| moteur | ✅ get_unit_by_id signature alignée (game_state, unit_id) (2026-08-19) — 6 sites cassés corrigés (movement_handlers+combat_utils), 49 ancienne-ordre mis à jour dans deployment_handlers, action_decoder, reward_calculator, observation_builder, game_state, w40k_core, shared_utils + tests ; 41 tests verts | — | ⚡ |
| analyzer | ✅ FP familles 1+2 grammaire 4 corrigés (2026-08-19) — token [CLOSE-QUARTERS] override is_close_quarters + shooter_engaged_with_target ; 7 tests rouge/vert ; famille 3 déjà close ; famille 4 = bug moteur (advance E383 : 103#8 dépasse budget 9) | — | ⚡ |
| analyzer | ✅ doublon fam2 cq-grammar4-token remplacé par scénario grammar=3 (2026-08-19) — test cq_grammar4 dédoublonné | — | ⚡ |
| training+gate | ✅ crash results['control'] absent quand min_vs_control=0.0 corrigé (2026-08-19) — résultat dict guard sur clé control ; gate ne crashe plus si critère absent | — | ⚡ |
| analyzer | ✅ lot2 rules — compteurs usage ANTI-X/TORRENT/LETHAL HITS/IGNORES_COVER/EXTRA_ATTACKS (2026-08-19) ; fix DW threshold ANTI-X:N+ (N<6) ; Roll:1 HAZARDOUS counter ; validité TORRENT+LETHAL HITS ; 16 tests rouge/vert | — | ⚡ |
| analyzer | ✅ lot3 rules unités — charge_impact (seuil/dégât), reroll_charge, reroll_1_save_fight, oath_target, CTP, leader/support ; waaagh_invul retiré du snapshot EFFECTS ; 9 tests rouge/vert (2026-08-20) | — | ⚡ |
| analyzer | ✅ phase_seq par joueur (2026-08-20) — séquences vérifiées par joueur indépendamment ; élimine 64 faux positifs phase_order (FIGHT P1 avant CHARGE P2 dans le même tour) ; 2 verrous rouge/vert | — | ⚡ |
| analyzer | ✅ fix phase_order faux positifs gate séquence joueur sur COMMAND (2026-08-20) — analyzer_core gate phase_seq indexé par joueur ; faux positifs cross-player éliminés | — | ⚡ |
| tests | ✅ corriger IDs 101#8/9, EZ dynamique, doublon (2026-08-20) — test_analyzer_coherency_ghost_opposite_camp : IDs figurines et EZ corrigés, doublon supprimé | — | ⚡ |
| tests | ✅ _fought_line embed [MODEL_TYPES:] — paramètre mort unit_type actif, symétrie _fight_body_line (2026-08-20) | — | ⚡ |
| analyzer | ✅ suppression player_alternation_violations (2026-08-20) — check retiré : 40K priorité par roll-off, aucune alternance stricte ; 204 faux positifs éliminés | — | ⚡ |
| analyzer | ✅ verrou P1 priorité multi-tours (2026-08-20) — test verrou : P1 ouvre COMMAND sur 3 tours consécutifs → 0 violation ; docstring à jour | — | ⚡ |
| analyzer | ✅ §2.9 faux positif DEAD en phase adverse (2026-08-20) — lignes DEAD exclues du suivi phase_seq_current_turn ; unité P1 tuée pendant SHOOT P2 ne pollue plus la séquence P1 ; verrou rouge/vert | — | ⚡ |
| tests | ✅ §2.2 collision charge après mort ancre cible (2026-08-20) — `test_conformite_03_01_09_05` : destination bloquée même si l'ancre cible meurt avant le commit charge ; verrou rouge/vert | — | ⚡ |
| step_logger+moteur | ✅ [ENGAGED_MODELS: N/total] sur lignes CHARGED (2026-08-20) — step_logger + charge_handlers émettent le ratio engagés/total sur chaque ligne CHARGED ; verrou intégration | — | ⚡ |
| moteur+ai | ✅ Charge multi-cibles L9 (2026-08-20) — C(20,2)+20 = 210 slots (1045–1254), tête dense séparée dans pointer_policy, logique PvP réutilisée, verrou test_action_space_mirror + test_pointer_head ; TOTAL_ACTION_SIZE 1159→1349 | [v11_chemin_critique.md#p3-8](v11_chemin_critique.md#p3-8) | ⚡ |
| analyzer | ✅ DEAD@COMMAND fix §2.9 + purge reset phase sur DEAD events (2026-08-20) — dead lines exclues du suivi phase_seq_current_turn ; verrou rouge/vert | — | ⚡ |
| step_logger | ✅ is_pair dans action_log + [PAIR] step.log (2026-08-20) — charge multi-cibles loggue explicitement le flag is_pair ; verrou rouge/vert | — | ⚡ |
| moteur+ai | ✅ Fix action_family shoot_indirect_slot + commentaires post-L9 (2026-08-20) — branche SHOOT_INDIRECT_SLOTS ajoutée, branche CHOICE morte retirée, offsets commentaires mis à jour (1086→1276 etc.), docstring pointer_policy corrigée ; verrou rouge/vert | — | ⚡ |
| tests | ✅ Purge tests non-verrou sentinel skip (2026-08-20) — tests non-verrou et imports pytest morts supprimés dans suite charge | — | ⚡ |
| step_logger | ✅ Verrou [PAIR] token step_logger charge/charge_fail (2026-08-20) — is_pair=True → [PAIR] dans la ligne ; is_pair=False/absent → absent ; verrou rouge/vert | — | ⚡ |
| tests+moteur | ✅ Fix conformité 03.01/09.05 isolation (2026-08-20) — verrous contre-épreuve renforcés et exclusion isolation corrigée | — | ⚡ |
| moteur | ✅ Fix §11.04 target_subhex cible primaire (2026-08-20) — boucle pair remplacée par appel unique sur target_squad_ids[0], miroir PvP charge_target_selection_handler ; test mis à jour + cas absent charge_fail ajouté | — | ⚡ |
| moteur+tests | ✅ fix-fight-mask-commit-parity overrun 12.06 socle par-figurine (2026-08-22) — pool post-overrun utilise `_model_can_fight_target` (socle modèle) au lieu de `_fight_build_valid_target_pool` (socle escouade) ; personnage attaché à plus grand socle ne crash plus bot_ranking ; diagnostic retiré ; verrou rouge/vert `test_overrun_post_pilin_uses_per_model_base_size_x5` x5 euclidien | — | ⚡ |
| infra | Perf `generate_compact_formation` | [infra.md#perf-formation](infra.md#perf-formation) | ⚡ |
| infra | ✅ gzip + Brotli livrés (2026-08-18) — stage `brotli-builder`, `load_module` contexte main, directives server | [archives/infra.md](archives/infra.md) | ⚡ |

### Bloqués par une décision utilisateur

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| moteur | Replis `unit_by_id` — T1–T3 (56 sites, T0 livré le 2026-08-19, signature `(game_state, unit_id)`) | [moteur.md#unit-by-id](moteur.md#unit-by-id) | 🚫 |
| moteur | ✅ Endless Duty obstacles 1 et 3 soldés (2026-08-19) — board_ref "44x60x5" + terrain-endless-duty.json (objectif fixe centre 110,150), objective_pool/selection supprimés, ED_START_LEADER mis à jour, signet test 2+4 ouverts | [moteur.md#endless-duty](moteur.md#endless-duty) | 🚫 |
| front | ~~Scission `bcKey` géométrie/contrôle~~ ✅ livré 2026-08-19 | [front.md](front.md) | ⚡ |

### À cadrer avant d'ouvrir

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| moteur | LoS 3D : tir à travers un mur depuis un étage (signalé 2026-08-11, jamais cadré) | [moteur.md#los-mur-etage](moteur.md#los-mur-etage) | 🚫 |
| bot+training | Chantier récompense distinct (relevé du chantier panel) | [bot.md#recompense](bot.md#recompense) | 🚫 |

### Lourds — re-cadrer avant toute reprise

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| moteur | Preview de tir sans deepcopy | [moteur.md#preview-tir](moteur.md#preview-tir) | 🚫 |
| infra | Noyau natif BFS move/empreintes — pool de move = 29 % d'une partie d'évaluation | [infra.md#noyau-natif](infra.md#noyau-natif) | ⚡ |
| infra | Migration PostgreSQL | [infra.md#postgresql](infra.md#postgresql) | ⚡ |
| infra | MCTS adversaire d'entraînement | [infra.md#mcts](infra.md#mcts) | 🚫 |
| bot | Tranches 2-3 benchmark — schedule P0→P10 + exploiters : code et tests livrés 2026-08-22 (`--etape`, `curriculum.json`, pool figé par-env) ; restent les 14 runs (~260 h) | [bot.md#league](bot.md#league) | 🚫 |

---

## Hygiène documentaire

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| doc | `obs_size` justification à mettre à jour | [doc.md#obs-size](doc.md#obs-size) | ⚡ |
| doc | Notes vitesse entraînement périmées | [doc.md#vitesse](doc.md#vitesse) | ⚡ |
| doc | Ancres de ligne périmées docs V11 | [doc.md#ancres](doc.md#ancres) | ⚡ |
| doc | Dette d'ancres G1/G2/G4 de V11_tranches §1bis | [doc.md#dette-tranches](doc.md#dette-tranches) | ⚡ |
| doc | Bandeaux périmés V11_agent_rework §0bis (assumés depuis 2026-07-20) | [doc.md#bandeaux-0bis](doc.md#bandeaux-0bis) | ⚡ |
| doc | §0.19 : les ✅ T2→T5 revérifiés par lecture seule | [doc.md#reverif-t2-t5](doc.md#reverif-t2-t5) | ⚡ |
| training | ✅ Note `bot_eval_freq_normal` réécrite (2026-08-18) — d_bot_eval_seconds=98s, 5h54 pour 50k épisodes | — | |
| bot | ✅ `bot_evaluation` simplifié : `_strip_phase_suffix` extrait + `_resolve_seat_seed` migré (2026-08-21) | — | |
| training | ✅ R0b : compteurs W/L/D ajoutés aux checkpoints figés, publiés en TensorBoard (2026-08-21) | — | |
| bot | ✅ R0b : critère de compatibilité corrigé — sonde de chargement (§12.15) ; 5 archives pré-`charge_pair_net` skippées → 1 barreau réel (2026-08-22) | — | |
| bot | ✅ Fix seat-seed null explicite + migration `evaluate_against_bots` (2026-08-21) | — | |
| engine | ✅ Constante `DRAW_WINNER = -1` introduite dans `engine/constants.py`, tous les littéraux remplacés (2026-08-21) | — | |
