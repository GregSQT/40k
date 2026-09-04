# Archives Training

| Date | Chantier | Détail |
|---|---|---|
| 2026-09-04 | Pool de workers des sondes — persistance réelle | `ExploiterProbeCallback` et `PoolEarlyStoppingCallback` créaient leur pool dans `_on_training_start` et le fermaient dans `_on_training_end`, que SB3 appaire autour de **chaque** `learn()` (sb3-contrib, lignes 448 et 467) : la boucle budgétée en épisodes en enchaînant un par tranche de quatre updates, le pool était recréé et refermé par tranche et chaque sonde repayait le démarrage de ses workers. Remplacé par `_EvalPoolOwnerMixin` — création paresseuse à la première sonde, fermeture par `shutdown_probe_eval_pools` dans le `finally` de la boucle `learn()`. Ce point de fermeture, et non `_close_curriculum_stage`, parce qu'il est le seul à couvrir l'échec et l'interruption, et qu'il libère les 4 workers AVANT l'évaluation finale qui prend les siens. L'exception qui remonte de `_probe` FERME désormais le pool au lieu de le détacher (workers orphelins). Mesuré sur harnais identique, 3 sondes à travers des frontières de `learn()` : 2,46/2,04/2,03 s → 2,57/0,02/0,00 s ; en sonde réelle s'y ajoute le chargement de l'archive adverse dans `_worker_ckpt_cache` (9,4 s pour 45 Mo), lui aussi économisé. Le rechargement du modèle P1 ne l'est pas — `_probe` écrit dans un `mkstemp` neuf, le jeton de version change de toute façon. Comptage de processus après fermeture : 0 orphelin. 3 mutations rouges, 66 tests verts | training+infra · — |
| 2026-08-17 | P3-4 Allocation pertes défenseur | `_select_allocation_model` branché sur décision agent ; obs_size 16659→16671 ; 12 tests |
| 2026-08-17 | Nettoyage configs | 6 profils actifs (`x1`/`x1_long`/`x1_debug` + `x5_new`/`x5_long`/`x5_debug`) ; 5 profils supprimés ; 29 tests mis à jour |
| 2026-08-17 | Étape 7 — purge anciens bots | 5 anciens bots supprimés de `bot_training.ratios` et `bot_eval_weights` des 9 profils |
| 2026-08-16 | Coût d'évaluation mesuré | 16 workers optimal (5,75× débit série) ; `bot_eval_final` 600→300 ; notes recalées |
| 2026-08-16 | `torch.compile` et inférence par lot abandonnés | Gains mesurés < 1 % — clé `bot_eval_torch_compile_cpu` retirée des 4 profils |
| 2026-08-11 | Métriques réserves et charge, barème, alignement charge 11.02 | 7 tranches, run `x1_long` du même jour — → `Documentation/Archives/chantiers/metriques_reserves_et_charge_2026-08-11.md` |
| 2026-08-11 | Distances de charge au `step.log` et métriques | 10 courbes `charge_distance/*` (2 camps × 5) depuis les mêmes lignes journal que `m_charge_attempts` |
| 2026-08-11 | Run `--new` ArmageddonAgent x1 | Base de développement, pas la mesure — `run_20260810-111734`, 10 000 épisodes |
| 2026-08-11 | Rampes par-épisode §0.57 | Compteur LOCAL / total GLOBAL — rampe de déploiement figée corrigée |
| 2026-08-20 | Run `x1_long --new` terminé 2026-08-20 — critères pipeline VERTS, `benchmark_floor` posé à 0,049 | training+bot · [bot.md#etape8](bot.md#etape8) |
| 2026-08-19 | **P3-6** Move-after-shooting + reactive move — constaté implémenté 2026-08-19 | training+moteur · [v11_chemin_critique.md#p3-6](v11_chemin_critique.md#p3-6) |
| 2026 | **P3-8** Optionnels — déploiement (08-19), charge multi-cibles (08-20), placement charge (08-24), split-fire (08-24) ; `TOTAL_ACTION_SIZE` 1159→1389 ; ré-entraînement `--new` nécessaire | training · [v11_chemin_critique.md#p3-8](v11_chemin_critique.md#p3-8) |
| 2026-08-19 | **P4** Observation de support — livré 2026-08-19 ; `obs_size` 16671→16703 | training+moteur · [v11_chemin_critique.md#p4](v11_chemin_critique.md#p4) |
| 2026-08-18 | **P5** Validation par tranche — tranché 2026-08-18 | training · [v11_chemin_critique.md#p5](v11_chemin_critique.md#p5) |
| 2026-08-26 | ✅ fix(ppo): `_n_updates` inflaté par n_epochs corrigé (2026-08-26) — incrément déplacé après la boucle epoch (SB3 upstream) ; flush TensorBoard sans seuil (0 perte sur crash) ; test rouge/vert n_epochs=4 | training · — |
| 2026-08-26 | ✅ fix(obs): pollution `_obs_scratch` par clé grid corrigée (findings code-review) — 2026-08-26 | training · — |
| 2026-08-26 | ✅ feat(ppo): `train/time_update` ajouté dans `PatchedMaskablePPO.train()` — 2026-08-26 | training · — |
| 2026-08-25 | ✅ obs slots réservés stratagèmes réactifs (2026-08-25) — slots `charged` UNIT_BIN + `fire_overwatch`/`heroic_intervention` AGENT_DECISION réservés dans l'obs avant R1 ; `fire_overwatch`/`heroic_intervention` sans handler retirés de GRANTABLE, garde GRANTABLE⊆RULE_EFFECT | training+moteur · — |
| 2026-08-18 | ✅ Benchmark floor gate §4.D livré (2026-08-18) — 3 bots de référence (balanced/denial/reactive) sur 4 scénarios holdout_regular ; seuil 0.90 après mesure ; `model_gating_enabled` sur x1_long | training+bot · [v11_chemin_critique.md#benchmark-gate](v11_chemin_critique.md#benchmark-gate) |
| 2026-08-18 | ✅ scenario_bench-01..04 dupliqués supprimés (2026-08-18) — fichiers byte-for-byte identiques aux scenario_bot-01..04, glob fallback ramassait 8 scénarios au lieu de 4, épisodes/scénario divisés par 2 sans contrepartie | training+bot · — |
| 2026-08-24 | ✅ fix combat reward V11 (2026-08-24) — correctif récompense combat gym V11 (worktree-fix-combat-reward-v11) | training · — |
| 2026-08-24 | ✅ fix self_model_encoder dim (2026-08-24) — sortie entity_dim (64) au lieu de model_dim (16) + trunk_dim aligné ; crash reshape [B,20,64] éliminé | training · — |
| 2026-08-19 | ✅ PLACEMENT_WEIGHTS slots 9/10 couverts (2026-08-19) — hotfix training, slots 9 et 10 ajoutés aux poids de placement | training · — |
| 2026-08-19 | ✅ crash results['control'] absent quand min_vs_control=0.0 corrigé (2026-08-19) — résultat dict guard sur clé control ; gate ne crashe plus si critère absent | training+gate · — |
| 2026-08-23 | ✅ fix-selfplay-metrics-validation — validation snapshot_label + déduplique log_selfplay_win (2026-08-23) | training · — |
| 2026-08-23 | ✅ fix-enemy-slot-reserves-oc-fallback — exclure réserves stratégiques ennemies du slot mapping + tests OC fallback (2026-08-23) | training · — |
| 2026-08-23 | ✅ simplify-ai-curriculum-train — dédup et simplifications curriculum/train/test_exploiter (2026-08-23) | training · — |
| 2026-08-23 | ✅ fix-snapshot-label-evaluate-checkpoints — `self_play_snapshot_label` manquant dans `evaluate_against_checkpoints` → crash clôture P1 (2026-08-23) ; verrou rouge/vert | training · — |
| 2026-08-23 | ✅ simplify vec-normalize factory (2026-08-23) — consolider, atleast_2d, drop asarray | training · — |
| 2026-08-23 | ✅ fix vec-normalize non-dict cache bypass (2026-08-23) — VecNormalize chemin non-dict utilisait le cache brut au lieu de vn.normalize_obs() | training · — |
| 2026-08-24 | ✅ expected_damage contextuelle reward_mapper (2026-08-24) — nouveau module expected_damage.py : NB×P(hit)×P(wound)×P(fail_sv)×DMG ; can_kill_in_one_phase remplace proxy NB×DMG brut ; 8 tests rouge/vert | training · [bot.md#recompense](bot.md#recompense) |
| 2026-08-25 | ✅ feat(curriculum) --etape + --resume-from combinables (2026-08-25) — reprendre un run de curriculum planté sans perdre les steps ; erreur explicite si init='new' ; 14 tests verts | training · — |
| 2026-08-22 | ✅ fix-exploiter-probe-trous (2026-08-22) — 4 trous + 2 simplifications `ExploiterProbeCallback` dans `ai/training_callbacks.py` | training · — |
| 2026-08-24 | ✅ fix _coherency_alive unit_by_id + fixture HP_MAX (2026-08-24) — _coherency_alive lit unit_by_id au lieu de squad_cache ; fixture HP_MAX alignée | ai · — |
| 2026-08-24 | ✅ fix spatial extractor sm_emb (2026-08-24) — zero absent sm_emb slots + purge model_dim mort dans ai/models | ai · — |
| 2026-08-24 | ✅ fix profils count 7→6 (2026-08-24) — x1_selfplay supprimé, références 7 profils → 6 mises à jour | training · — |
| 2026-08-24 | ✅ fix+simplify reward_mapper (2026-08-24) — stubs et code mort retirés ; get_kill_bonus_reward + _was_lowest_hp_target factorisés ; verrous rouge/vert | training · — |
| 2026-08-18 | ✅ Note `bot_eval_freq_normal` réécrite (2026-08-18) — d_bot_eval_seconds=98s, 5h54 pour 50k épisodes | training · — |
| 2026-08-21 | ✅ R0b : compteurs W/L/D ajoutés aux checkpoints figés, publiés en TensorBoard (2026-08-21) | training · — |
| 2026-08-26 | ✅ `training_config_overrides` par étape dans `curriculum.json` (2026-08-26) — surcharge `total_episodes`, `model_params` (lr, ent_coef, n_epochs, vf_coef) et `callback_params` (bot_eval_freq, bot_eval_final) sans créer de profils x1_P* ; P1 75k/n_epochs 5/vf 0.5/ent_coef decay 0.65, P2 100k mêmes HP ; whitelist + cohérence total_episodes/bot_eval_freq×3 ; 30 tests | training · — |
