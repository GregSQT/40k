# Archives Bot

| Date | Chantier | Détail |
|---|---|---|
| 2026-08-17 | Scorer réglé §12.17 | `w_contest` 3.5→2.0, `w_crowd` 6.0 ; fix moteur `no_gym_allocation_model` inclus |
| 2026-08-16 | C+D livrées | `ai/benchmark_bots.py` ; 3 bots `reference_*` ; `benchmark_floor` gate ; profil comportemental par adversaire ; 40 tests |
| 2026-08-16 | A+B livrées | Capacités communes (`late_game`, `preservation`, `persistence`) ; jitter SHA256 ; `config/bot_doctrine_profiles.json` ; 82 tests |
| 2026-08-16 | `AttritionBot.wants_charge` corrigé | `super()` manquant supprimait les capacités communes ; 3 tests verrouillage |
| 2026-08-16 | `bench_shortlist.py` livré §13.1 | K=8 → 8,5 % divergence, K=12 → 5,7 % ; 4 bots, 3 scénarios, 200 épisodes |
| 2026-08-15 | Cache contributions OC §13 | `objective_control_contributions` mis en cache par activation dans `_DoctrineBot` |
| 2026-08-13 | Scorer réglé §12.9 | 6 poids encadrés, 3 retenus ; passe de 1,93 à 2,33 zones au tour 5 |
| 2026-08-13 | Decapitation corrigé §12.11 | Marchait vers un ennemi et tirait sur un autre ; `w_objective` rejoué |
| 2026-08-13 | `bot_zone_direct --json-out` | Relevé par épisode ; bloc `run` avec graine/modèle/doctrine ; schéma v2 |
| 2026-08-13 | `bot_zone_direct` validation destination | Chemin vide/dossier/lecture seule échouent en 1 s ; écriture atomique |
| 2026-08-12 | §12.7 invalidé | Deux hausses de poids défaites après re-mesure isolée |
| 2026-08-13 | Nouvelle ligne de base | `combined = 0,7433`, pire bot `racer = 0,630`, rejoué §12.8 |
| 2026-08-11 | Six styles, panel étalé | Modèle de dégâts corrigé par figurine ; pire bot 0,837→0,62 ; §12.5 |
| 2026-08-22 | ✅ **R0a FERMÉ SANS FRANCHISSEMENT le 2026-08-22.** §3.1-§3.4 livrés 2026-08-21 ; §3.5 balayage 2026-08-22 (abandon) ; **R0a-bis livré 2026-08-22** : 3 défauts 1er ordre fixés + calibration (balanced 0,306 / denial 0,297 / reactive 0,280 à 20 ép.) — fourchette [0,40 ; 0,60] non franchie. **Les reference_\* sont abandonnés comme étalons** : `benchmark_floor` est RETIRÉ (x1_long à 0,0), remplacé par le plancher dur de 0,55 contre le champion le plus récent d'une étape ([bot.md#league](bot.md#league)). Plus aucune re-pose n'est en attente. **Suite 2026-08-26/27** : l'abandon est allé à son terme — les 4 bots à poids nul (`tactical` + les trois `reference_*`) sont **sortis du panel d'évaluation** (commit `8bb4e42e` ; un poids nul ne les empêchait pas d'être joués, la boucle itère sur les clés), et `model_gating_min_benchmark_floor` est **supprimé du code** (commit `16cf36b1`) au lieu d'être seulement mis à 0,0. Verrou : `test_bot_eval_bot_count_is_pinned`. **corrections /code-review + /simplify 2026-08-22** : 4 findings review appliqués (`_KILL_SENTINEL`, `_zone_contest_pull`, double-scan reactive, docstring) + 4 cleanups simplify (sentinel denial, if/else pull, dedup test gs, docstring) | bot · [bot.md#r0a-references](bot.md#r0a-references) |
| 2026-08-21 | ✅ **R0b** Échelle de checkpoints figés en éval (`vs_ckpt_*`) — livré 2026-08-21 | bot+training · [bot.md#r0b-echelle](bot.md#r0b-echelle) |
| 2026-08-26 | ✅ `written_by` dans `curriculum.log` (2026-08-26) — `append_curriculum_log` estampille le point d'entrée depuis `sys.argv[0]` ; clé fournie par l'appelant = erreur ; 3 verrous rouge/vert. Cause : un script jetable avait journalisé un refus de P1 mesuré sur 30 épisodes au lieu de 300, indistinguable d'une mesure du pipeline. Encadré de traçabilité dans `bot.md` | bot+training · [bot.md#league](bot.md#league) |
| 2026-08-21 | ✅ Étalon panel ré-épinglé (2026-08-21) — `robust_0.8692` ne charge plus depuis `charge_pair_net` (`d5ddffb5`), référence §12 passée à `robust_0.8463` ; ligne de base §12.14 marquée pré-rupture | bot · [bot.md#etape8](bot.md#etape8) |
| 2026-08-20 | ✅ Fix code-review benchmark_bots (2026-08-20) — import DESTINATION_SHORTLIST depuis bot_doctrines, précalcul geo_scores, mocks morts require_unit_from_cache supprimés | bot · — |
| 2026-08-20 | ✅ Scoring multi-critères reference bots + fix charge/CONTEST (2026-08-20) — 3 bots (balanced/denial/reactive), 4 scénarios holdout, fix charge/CONTEST, benchmark gate §4.D | bot · [bot.md#etape8](bot.md#etape8) |
| 2026-08-20 | ✅ bot_ranking parallélisé ProcessPoolExecutor (2026-08-20) — temps de tournoi réduit | bot · — |
| 2026-08-27 | ✅ fix(pool-shutdown) evaluate_against_bots (2026-08-27) — try/finally + shutdown workers orphelins ; fix evaluate_against_checkpoints | bot · — |
| 2026-08-27 | ✅ fix(bot-eval) /code-review 5 findings (2026-08-27) — env.close() try/finally, max_steps hoisted, pkl orphelin, global inutile, require_key T1 | bot · — |
| 2026-08-27 | ✅ simplify(bot-eval) /simplify (2026-08-27) — remove_model_with_companions réutilisé, deterministic/bot_name/scenario_name hoistés | bot · — |
| 2026-08-19 | ✅ Stratégies déploiement 5/6 (2026-08-19) — `centre_hub` + `safe_rear` ajoutées, regret P3-8 partiellement résorbé | bot · — |
| 2026-08-21 | ✅ Ligne de base §12.14 rejouée sur robust_0.8463 (2026-08-21) — mesure bot_zone_direct sur l'étalon courant post-rupture charge_pair_net ; test_aucune_recopie_dans_scripts rendu dynamique | bot · — |
| 2026-08-21 | ✅ 4 findings code-review bot_zone_direct (2026-08-21) — bot_units mort retiré, dead defaults _loss_rate, collect×5→×2 par pas, try/except focus_dist | bot · — |
| 2026-08-21 | ✅ `bot_evaluation` simplifié : `_strip_phase_suffix` extrait + `_resolve_seat_seed` migré (2026-08-21) | bot · — |
| 2026-08-22 | ✅ R0b : critère de compatibilité corrigé — sonde de chargement (§12.15) ; 5 archives pré-`charge_pair_net` skippées → 1 barreau réel (2026-08-22) | bot · — |
| 2026-08-21 | ✅ Fix seat-seed null explicite + migration `evaluate_against_bots` (2026-08-21) | bot · — |
