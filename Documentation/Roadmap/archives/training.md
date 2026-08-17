# Archives Training

| Date | Chantier | Détail |
|---|---|---|
| 2026-08-17 | P3-4 Allocation pertes défenseur | `_select_allocation_model` branché sur décision agent ; obs_size 16659→16671 ; 12 tests |
| 2026-08-17 | Nettoyage configs | 6 profils actifs (`x1`/`x1_long`/`x1_debug` + `x5_new`/`x5_long`/`x5_debug`) ; 5 profils supprimés ; 29 tests mis à jour |
| 2026-08-17 | Étape 7 — purge anciens bots | 5 anciens bots supprimés de `bot_training.ratios` et `bot_eval_weights` des 9 profils |
| 2026-08-16 | Coût d'évaluation mesuré | 16 workers optimal (5,75× débit série) ; `bot_eval_final` 600→300 ; notes recalées |
| 2026-08-16 | `torch.compile` et inférence par lot abandonnés | Gains mesurés < 1 % — clé `bot_eval_torch_compile_cpu` retirée des 4 profils |
| 2026-08-11 | Métriques réserves et charge, barème, alignement charge 11.02 | 7 tranches, run `x1_long` du même jour — → `Implémenté/metriques_reserves_et_charge_2026-08-11.md` |
| 2026-08-11 | Distances de charge au `step.log` et métriques | 10 courbes `charge_distance/*` (2 camps × 5) depuis les mêmes lignes journal que `m_charge_attempts` |
| 2026-08-11 | Run `--new` ArmageddonAgent x1 | Base de développement, pas la mesure — `run_20260810-111734`, 10 000 épisodes |
| 2026-08-11 | Rampes par-épisode §0.57 | Compteur LOCAL / total GLOBAL — rampe de déploiement figée corrigée |
