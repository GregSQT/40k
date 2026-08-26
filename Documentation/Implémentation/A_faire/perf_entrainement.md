# Performances — Accélération de l'entraînement RL

> **Créé le 2026-08-26** à partir de l'audit multi-agents du même jour (4 lecteurs code + 2 mesureurs :
> cProfile d'un env réel sur le chemin exact du run P1, bench GPU du réseau reconstruit à l'identique),
> mené pendant que le run `x1_long --etape P1` (PID 4198) tournait — run vérifié intact.
> **Objectif** : accélérer l'entraînement **sans casser le métier** (règles de jeu, sémantique
> d'apprentissage). **Principe** : mesurer avant/après chaque étape ; aucune modification
> d'hyperparamètre implicite ; parité bit-à-bit exigée pour toute optimisation « pure perf ».
> Relecture croisée : audit externe du 2026-08-26 (utilisateur) — diagnostic confirmé, séquence
> « mesurer avant de s'engager sur la Phase 3 » actée.

---

## 1. État mesuré — référence du 2026-08-26

**Machine** : i9-13900H (16 threads WSL2), 39 Go RAM, RTX 4060 Laptop 8 Go. torch 2.13 cu130.
**Run observé** : `x1_long --etape P1 --resolution 1` (curriculum : 75 000 épisodes, `n_epochs=5`,
`vf_coef=0.5`, lr 0.001→0.0005).

**Débit réel : ~200 steps/s global (SB3 `time/fps`), ~96 ép./min** → P1 ≈ 13 h au rythme courant.
Mesure de référence antérieure : `x1_long` nu 50 000 ép. = 5 h 54 (2026-08-18).

### Budget d'un cycle PPO (8 184 transitions = 341 vec-steps ≈ 41 s de wall)

| Poste | Mesure | Part |
|---|---|---|
| **Attente pure** : lockstep sur l'env le plus lent + 2 allers-retours IPC/step + syncs GPU | ~30 s | **~73 %** |
| Update GPU : 5 epochs × (8×1020 + 1×24) minibatches × 142 ms, eager, ~4-5 Go de re-transferts H2D | ~6 s | ~15 % |
| Calcul réel des envs : 9,47 ms/step (mesuré sans profiler), en parallèle sur 24 workers | ~3,2 s | ~8 % |
| Inférence rollout : 341 forwards batch 24 × 5,84 ms (dont 1,78 ms de conversion H2D, 28 clés d'obs) | ~2 s | ~5 % |

**Utilisation** : 24 workers SubprocVecEnv à ~11-13 % CPU chacun, learner ~43 %, machine idle ~72 %,
GPU 20-38 % (3 Go/8). `n_steps=8192` de la config est un **total** divisé par `n_envs`
(`ai/train.py` : `effective_n_steps = max(1, base_n_steps // n_envs)` → 341/env).

### Répartition d'un step d'env (cProfile 300 steps, chemin exact du run P1)

| Poste | Part du wall |
|---|---|
| Masque d'action (`get_squad_action_mask_and_eligible_units`) — dont carte BFS de move 14,5 % | 33,2 % |
| Observation (`build_squad_observation`) | 31,9 % |
| Tours des bots adverses joués dans le worker (`_run_bot_until_not_bot_turn`) | 30,7 % |
| Reward | 0,2 % |

Fonction la plus chaude : `entries_in_engagement_zone` (`engine/spatial_relations.py`) —
48 811 appels / 300 steps = 18,9 % du wall. Reset : 107,6 ms (rechargement scénario+rosters complet
à chaque épisode, cause `agent_roster_ref="training_random"` → `should_reload_scenario=True`).
Hors de cause (mesuré) : reward, callbacks, TensorBoard, évals (0 éval jouée sur les 4 630 premiers
épisodes, débit déjà à 96 ép./min).

### Goulots identifiés (fichier:ligne, vérifiés verbatim)

1. **2ᵉ RPC par step** : `sb3_contrib/common/maskable/utils.py`
   `return np.stack(env.env_method(EXPECTED_METHOD_NAME))` appelé par `ppo_mask.py` à chaque
   vec-step, en plus de `env.step` — 2 allers-retours pipe synchrones par step (~2,5 Mo picklés).
2. **Cache mono-slot du pool de move** : `engine/phase_handlers/shared_utils.py`
   `_cache[str(squad_id)] = (_fp_key, result)` — l'alternance budget normal (choix d'activation)
   / budget advance (désignation) sur la même escouade rate systématiquement le cache
   → **2 BFS + érosions par activation de move** (`engine/action_decoder.py`).
3. **Fingerprint recalculé à chaque appel, hit compris** : `shared_utils.py` — tuples triés
   sur toutes les unités + hexes occupés, payé même quand le cache sert.
4. **Scan linéaire** dans le prédicat le plus appelé du masque de tir :
   `_attacker_model_can_reach_squad` (`shared_utils.py`) reparcourt `units` alors que
   `unit_by_id` existe.
5. **Double balayage du masque de tir** : `build_squad_action_mask` (`shared_utils.py`) puis
   `shoot_weapon_sel_open_slots` (`shared_utils.py`) refont chacun modèles × armes × cibles.
6. **Obs sans caches ciblés** : `charge_build_valid_plan` appelé 2× par état (masque jet réel + obs
   CHARGE_MAX_ROLL, `observation_builder.py`) ; `edge_distance` recalculé par entité par step
   sans cache (`observation_builder.py`) ; passe d'engagement et bloc TYPES recalculés par step ;
   ~27 `np.zeros` par build.
7. **Reset** : deepcopy du scénario JSON (`engine/game_state.py`) + glob/open/json.load des
   rosters **à chaque épisode** (`engine/w40k_core.py`) + purge de tous les caches LoS/spatiaux.
8. **Update** : rollout **re-transféré intégralement au GPU à chaque epoch**
   (`sb3_contrib/common/maskable/buffers.py`), masques stockés en float32 (×4, `buffers.py`),
   ~225 `.item()` (syncs) de logging par update, `evaluate_actions` non compilé (torch.compile ne
   couvre que `policy.forward`, `ai/train.py`).
9. **À-côtés par épisode** : `writer.flush()` TensorBoard à chaque épisode
   (`ai/metrics_tracker.py`) + boucle norme de gradient sur tous les tenseurs à chaque épisode
   (`ai/training_callbacks.py`).
10. **Gate de fin d'étape curriculum** : 300 épisodes **séquentiels mono-process CPU** (~72 min à
    14,5 s/ép, `ai/bot_evaluation.py`) alors que le pool 16 workers existe pour l'éval finale.
11. **Éval intermédiaire** : les 10 clés de `bot_eval_weights` sont jouées, poids 0,0 compris
    (`ai/bot_evaluation.py`) — 4 bots / 10 = mesure pure, hors signal de sélection.

**Déjà en place (ne pas re-livrer)** : SubprocVecEnv 24 workers ; masque construit 1×/step nominal
avec handoff masque→obs (`w40k_core.py`) ; `action_masks()` servi sans recalcul
(`env_wrappers.py`) ; obs différée (1 build/step gym) ; cache LoS par paire avec invalidation
au mouvement ; bloc armes de l'obs mémoïsé ; VecNormalize limité à `global_cont` (13 floats) ;
OMP/MKL=1 ; TF32 ; torch.compile sur `policy.forward`.

### Pièges de mesure

- Le run P1 **ralentit de lui-même après l'épisode 5000** : la rampe self-play (0→0,40) active un
  forward CPU mono-thread + une obs complète par décision adverse dans les workers. Toute
  comparaison avant/après se fait au **bench offline de la Phase 0**, pas au `time/fps` d'un run
  en cours de rampe.
- `time/fps` SB3 est une **moyenne cumulée** depuis le début du run, pas un débit instantané.
- L'overhead cProfile est ×2,6 : les **%** du profil font foi, les ms absolues viennent du run
  sans profiler (9,47 ms/step).
- ⚠️ **`bench_env_step.py` se lance MACHINE AU REPOS, jamais pendant un run.** Une mesure
  « après » prise au repos comparée à une mesure « avant » prise sous charge (24 workers +
  learner) fabriquerait un gain imaginaire.
- ⚠️ **Le bench n'est PAS déterministe run-à-run, malgré `seed=42`** (constaté le 2026-08-26 au
  soir, machine au repos) : sur le même commit, 3 répétitions donnent 70 → 112 s de wall et
  27,9 → 32,7 ms de médiane. La dispersion vient des tours de bots adverses joués dans l'env
  (`_run_bot_until_not_bot_turn`, P99 > 1 s) et de la rotation des rosters `training_random`.
  **Conséquence opérationnelle : une répétition unique ne prouve rien sous ~30 % d'écart.** Toute
  mesure de clôture (1.10, 2.4, 4.3) se prend en **≥ 3 répétitions**, et se lit sur la **médiane
  et le P99**, jamais sur un tirage isolé. C'est ce qui a fait entrer un **10,14 ms fantôme** dans
  le journal §6 le 2026-08-26 : rejoué sur le même commit, il ne se reproduit pas.
  Toute ligne du journal §6 doit donc nommer l'état de la machine.

---

## 2. Cibles chiffrées (estimations, pas des mesures)

| Palier | Gain visé | x1_long 50k ép. | League (14 runs, ~260 h estimées) |
|---|---|---|---|
| Aujourd'hui | — | 5 h 54 | ~260 h |
| Phases 1+2+4 | ×2-3 | ~2-3 h | ~90-130 h |
| + Phase 3 option A | ×4-8 | ~1-1,5 h | ~50-80 h |

Chaque phase se clôt par une mesure fps réelle avant d'ouvrir la suivante ; les gains des phases 1
et 3 **ne s'additionnent pas** (voir §5 Phase 3).

---

## 3. Verrous « sans casser le métier »

- **Parité bit-à-bit** : harnais Phase 0 — N épisodes à seed fixe, hash(masque+obs) et `step.log`
  identiques avant/après toute optimisation pure-perf. Le mécanisme de vérification de masque
  (gate `mask_verification`, no-op désarmé) existe déjà dans le moteur et peut être armé en test.
- **Tests rouge/vert** par item (CLAUDE.md T4) + suite pytest ciblée sur les fichiers touchés.
- **Aucun changement d'hyperparamètre implicite** : `n_epochs`, `batch_size`, `n_envs`, AMP,
  device adversaire = Phase 5, chacun une décision utilisateur explicite.
- **Jamais de merge dans `main` pendant un run** : les workers d'éval sont des process `spawn` qui
  ré-importent le code du disque en cours de run (mélange de versions = biais). Développement en
  worktree, merge entre deux runs. Jamais de modification de `config/**/*.json` pendant un run.

---

## 4. Roadmap étape par étape

Statuts : 🟡 à faire · 🔵 en cours · ✅ livré · ⛔ bloqué (décision).

### Configuration agent par phase (décision 2026-08-26)

Une phase = un prompt/chantier, jamais tout d'un coup : des checkpoints de mesure ferment chaque
phase et l'arbitrage A vs C tombe entre la 2 et la 3.

| Phase | Modèle | Effort | Justification |
|---|---|---|---|
| 0+1 | Sonnet 5 | **high** | Items localisés et indépendants, le filet est le harnais de parité (0.2) ; high pour les cas limites d'invalidation de cache (1.2/1.6/1.8) — une invalidation manquée = corruption silencieuse |
| 2 | **Opus 5** | high pour 2.1, standard sinon | Refactor >3 fichiers interdépendants (buffer custom + collect + train.py + callbacks, contrat SB3) ; 2.1 croise device/minibatch/epochs |
| 3 (option A) | **Opus 5** | **high** | Architecture difficilement réversible + équivalence mathématique de la collecte distribuée |
| 4 | Sonnet 5 | standard | Unification des deux harnais d'éval dans un seul fichier (`bot_evaluation.py`) + tests à seeds fixes ; le risque est concentré sur deux invariants nommés (injection avant reset, murs de référence), pas sur l'architecture |

Réglage unique « confort » si on ne veut pas moduler : Opus 5 + effort high partout (plus lent et
plus cher là où Sonnet suffit).

### Phase 0 — Harnais de mesure et de parité (préalable, ~0,5 j)

| # | Étape | Statut |
|---|---|---|
| 0.1 | Committer `scripts/bench_env_step.py` (repris du profil d'audit : construit UN env sur le chemin exact de `train.py`, 600 steps masqués aléatoires, sort ms/step + top cProfile) | ✅ |
| 0.2 | Committer le harnais de parité : N épisodes seed fixe → hash(masque, obs) par step + `step.log`, comparés avant/après ; armer `mask_verification` en test | ✅ |
| 0.3 | Consigner la ligne de base dans le journal §6 (9,47 ms/step ; 200 fps ; 142 ms/minibatch 1020) | ✅ |

### Phase 1 — Queue de distribution d'un step env (workers) — zéro risque métier

C'est la **queue** (pas la moyenne) qui fixe le lockstep : chaque vec-step attend l'env le plus lent.

| # | Étape | Ancre | Statut |
|---|---|---|---|
| 1.1 | Cache **2 slots** (budget normal + advance) pour `build_squad_move_cell_map` — supprime le double BFS par activation de move | `shared_utils.py` (`build_squad_move_cell_map`) | ✅ |
| 1.2 | Fingerprint sur hit → compteur de version d'état (invalidation à la mutation : commit_move, mort, phase) | `shared_utils.py` (`build_squad_move_cell_map`) | ✅ |
| 1.3 | `_attacker_model_can_reach_squad` : scan linéaire → index `unit_by_id` | `shared_utils.py` (`_attacker_model_can_reach_squad`) | ✅ |
| 1.4 | Masque de tir : fusionner les 2 balayages modèles×armes×cibles (partager les résultats de la 1ʳᵉ passe avec `shoot_weapon_sel_open_slots`) | `shared_utils.py` (`_target_locked_by_ally`, `build_squad_move_cell_map`) | ✅ |
| 1.5 | Obs : mémoïser `charge_build_valid_plan` (masque + obs dans le même état) | `observation_builder.py` (`_encode_unit_entity`) | ✅ |
| 1.6 | Obs : pair-cache `edge_distance` avec invalidation au mouvement (motif LoS éprouvé) | `observation_builder.py` (`_encode_unit_entity`) | ✅ |
| 1.7 | Obs : cache du bloc TYPES **✅** (`_entity_types_cache`) · réutilisation des buffers numpy (~27 `np.zeros`/build) **✅** — `_obs_scratch` + `_unit_ent_cont`/`_unit_ent_bin` réutilisés, fill(0) avant chaque usage ; parité bit-à-bit verte, 2 tests rouge/vert ajoutés | `observation_builder.py` (`_empty_squad_observation`, `_encode_unit_entity`) | ✅ |
| 1.8 | Pair-cache `entries_in_engagement_zone` (invalidation motif `_touch_unit_los`) | `spatial_relations.py` (`engagement_distance_metric`) | ✅ |
| 1.9 | Reset : cacher les `json.load` des rosters + supprimer le deepcopy complet du scénario (copies ciblées) | `w40k_core.py` (`_reload_scenario`), `game_state.py` (`load_units_from_scenario`) | ✅ |
| 1.10 | **Mesure de clôture** : ms/step + fps offline ; consigner §6 | — | ✅ (repos, 3+3 répétitions, 2026-08-26) |

Gain attendu : ms/step −30-50 % et réduction de la queue → fps ×1,5-2.
Verrou par item : parité bit-à-bit (0.2) + test rouge/vert.

### Phase 2 — Pipeline SB3 (learner) — zéro changement de maths

**Ordre imposé 2.1 → 2.2 → 2.3** : l'étape 2.3 est la seule que l'option A (Phase 3) jetterait —
elle se fait en dernier et **se saute si la décision A est prise entre-temps**.

| # | Étape | Ancre | Statut |
|---|---|---|---|
| 2.1 | Rollout **résident GPU** : buffer custom qui garde obs+masques sur le GPU (fin des ~4-5 Go H2D re-transférés à chaque epoch) + masques en bool (float32 ×4 aujourd'hui) | `ai/gpu_rollout_buffer.py` (`GpuMaskableDictRolloutBuffer`) | ✅ |
| 2.2 | Logging différé : accumuler les scalaires sur GPU et ne `.item()` qu'en fin d'update (~225 syncs/update) ; `writer.flush()` et norme de gradient tous les N épisodes | `ai/patched_ppo.py` (`train()`), `ai/metrics_tracker.py`, `ai/training_callbacks.py` | ✅ |
| 2.3 | **Un seul RPC par step** : le masque voyage dans le retour de `step()` (infos) ; VecEnv custom ou surcharge de `collect_rollouts` — sautable si option A actée | `ai/maskable_subproc_vec_env.py` (`MaskableSubprocVecEnv`), `ai/patched_ppo.py` (`collect_rollouts`) | ✅ |
| 2.4 | **Mesure de clôture** : `time/fps` run réel = **226–233 fps** (steps 33k–65k, run 20260826-171446, pre-rampe self-play) vs baseline 200 fps → **+13–16 %** ; non-régression env ✅ (bench_env_step 3×, médiane 29–31 ms) | — | ✅ |

Sous-classes locales (dans `ai/`), jamais de fork du venv. Verrou : masques identiques bit-à-bit
vs `env_method`, loss/approx_kl identiques à seed fixe sur un run court.

**Verrou de parité numérique livré (2026-08-26)** : `TestPatchedVsReferenceParity` dans
`tests/unit/ai/test_phase2_sb3_pipeline.py` — même rollout (seed=42, permutation fixe),
evaluate_actions déterministe → 6 métriques (pg_loss, value_loss, entropy_loss, approx_kl,
clip_fraction, loss) bit-à-bit identiques entre `PatchedMaskablePPO.train()` et
`MaskablePPO.train()` référence sb3_contrib. Détecte toute déviation ≥ 1e-6.
Note documentée : divergence sémantique sur `approx_kl` avec plusieurs minibatches par epoch
(référence = last-epoch only, patché = all-epochs mean) — prouvée dans
`test_approx_kl_semantic_gap_documented_for_multi_minibatch`. Impact production = négligeable
(valeurs convergent entre epochs en entraînement réel).

### Phase 3 — Architecture de la collecte — ✅ Option A actée (2026-08-26)

**Problème** : même après les phases 1-2, la collecte reste en pas cadencé — les 24 workers et le
GPU s'attendent mutuellement à chaque step. C'est structurel, pas optimisable localement.

**Décision : Option A** — collecte dans les workers, poids gelés par cycle : chaque worker déroule ses
341 steps avec une copie CPU de la policy (3,1 M de paramètres) et renvoie sa trajectoire ; le
learner ne fait plus que l'update. Gain ×3-6 estimé ; coût 1-2 semaines + validation lourde.

Seule option alignée sur le profil réel de la charge (moteur Python lourd, réseau minuscule), et
mathématiquement neutre : SB3 gèle déjà la policy pendant toute la collecte, donc collecter avec
les mêmes poids gelés dans les workers produit le même batch on-policy.

**Équivalences et écarts (analyse du 2026-08-26, confirmée par audit croisé)** :
- Synchro des poids : triviale (3,1 Mo × 24, une fois par cycle).
- Épisodes à cheval sur les frontières de collecte : le worker tronque à 341 steps et bootstrappe
  avec `predict_values` sur ses poids gelés — **exactement** la sémantique SB3 actuelle.
- **Seul vrai écart sémantique** : VecNormalize. Version propre = stats embarquées avec les poids,
  **gelées pendant le cycle**, mises à jour au learner au retour des trajectoires — diffère de SB3
  qui met à jour les stats à chaque step de collecte. Ne touche que `global_cont` (13 floats) +
  reward ; impact attendu négligeable mais À VERROUILLER : test dédié + run court de contrôle
  (win-rate vs référence).
- Les compteurs par-env (rampe déploiement §0.57, opponent_mix) sont **déjà** locaux aux workers —
  convention en place, rien à migrer.

**Règle de décision (à trancher AVANT de lancer la série league)** : après phases 1-2-4, mesurer
le fps sur profil P* au bench offline ; projection league > ~100 h → faire A d'abord ;
< ~60-70 h → C défendable. Les gains des phases 1 et 3 ne s'additionnent pas, chacun re-cote l'autre : la Phase 1
réduit la queue que le lockstep attend — si elle marche très bien, le gain marginal de A diminue ;
si elle déçoit, le dossier de A se renforce. Décider sur chiffres réels, pas sur estimations.

**Exécution (si A)** : chantier dédié, hors période de run (aucun merge possible pendant la league).
Modèle suggéré : Opus 5 (refactor >3 fichiers interdépendants, architecture difficilement
réversible) ; effort high (équivalence mathématique de la collecte distribuée).

### Phase 4 — Évals et curriculum (gains d'heures sur la league)

| # | Étape | Ancre | Statut |
|---|---|---|---|
| 4.1 | Gate de fin d'étape parallélisé — unification du harnais checkpoint dans le harnais bot (décision B, ci-dessous) | `bot_evaluation.py` | 🔵 |
| 4.2 | Pool d'éval persistant entre évals — **sorti du chantier 4.1**, voir « Pourquoi 4.2 n'est pas gratuite » | `bot_evaluation.py` | 🟡 |
| 4.3 | **Mesure de clôture** : durée gate ; calibrage du nombre de tranches ; consigner §6 | — | 🟡 |

Verrou : mêmes win-rates qu'en séquentiel à seeds fixes.

#### État mesuré du gate (2026-08-26, lecture de code)

`gate.eval_episodes = 300` **par membre de pool** (`config/agents/ArmageddonAgent/curriculum.json`),
holdout = **4 scénarios** (`scenarios/holdout_regular`, `holdout_hard` vide). Pools : P1 = 1 membre
(300 ép.), P2 = 2 (600 ép.), P3 = 3 (900 ép.). Le gate est joué séquentiellement dans le process
appelant par `evaluate_against_checkpoints` (`bot_evaluation.py`), boucle archive → scénario →
épisode.

**Conséquence de calibrage** : une granularité de tâche (checkpoint × scénario) ne produit que
**4 tâches** sur le gate de P1 — 4 workers occupés sur 16, gain plafonné à ×4 et non au ×10
annoncé initialement. Le découpage doit donc aller jusqu'à la **tranche d'épisodes**.

#### Décision B (2026-08-26) — unifier plutôt que dupliquer

Le corps de `evaluate_against_checkpoints` est un **duplicata dégradé** de `_eval_worker_task` :
même boucle d'épisode, mais sans journal de troncatures, sans ventilation faction/roster/siège, et
les épisodes plafonnés y tombent dans un seau `_timeouts` silencieux au lieu du « nul + trace »
qu'impose V11 §0.61 partout ailleurs.

Options écartées : (A) un second harnais checkpoint parallélisé — deux boucles à maintenir, 4.2 à
faire deux fois, trou §0.61 conservé ; (C) parallélisation au-dessus dans `_score_stage_against_pool`
— n'accélère que le gate, laisse l'éval R0b et la sonde exploiteur séquentielles.

**Retenu : B.** L'adversaire checkpoint devient une variante de tâche du harnais bot ;
`evaluate_against_checkpoints` devient un constructeur de tâches. Bénéfice de forme vérifié :
les tâches checkpoint passant par `_eval_worker_task`, le `pool.submit(_eval_worker_task, task)`
codé en dur dans `_collect_parallel_results_with_timeouts` **n'a pas à être touché** — c'était le
coût principal de l'option A.

Trois appelants de production, tous préservés sans changement de signature (les paramètres de
parallélisation sont lus dans la fonction via `validate_bot_eval_worker_params`, comme le fait
déjà `evaluate_against_bots`) : `train.py` (gate), `train.py` (éval R0b de `--test-only`),
`training_callbacks.py` (`ExploiterProbeCallback._probe`). La sonde tournant **pendant**
l'entraînement, elle hérite du `bot_eval_n_workers` déjà calibré contre la contention.

#### Étapes d'implémentation

| # | Étape | Ancre |
|---|---|---|
| B1 | Adversaire polymorphe : `checkpoint_zip` / `checkpoint_label` / `device` optionnels ; sans eux, comportement inchangé bit-à-bit | `bot_evaluation.py` (`_create_eval_env`) |
| B2 | Cache checkpoint par worker (`MaskablePPO.load` + normalizer + `_NormalizedFrozenModel` mémoïsés par `zip_path`) — sans lui, un worker recharge le zip à chaque tranche | `bot_evaluation.py` (`_eval_worker_init`, `_eval_worker_task`) |
| B3 | `ep_offset` dans la boucle d'épisode ; défaut 0 ⇒ chemin bot intact | `bot_evaluation.py` (`_eval_worker_task`) |
| B4 | Probe-load des archives dans le parent avant construction des tâches (préserve le skip §12.15, qui deviendrait sinon un crash de tâche opaque) | `bot_evaluation.py` (`evaluate_against_checkpoints`) |
| B5 | Réécriture en constructeur de tâches (archive × scénario × tranche), `bot_name = score_label` | `bot_evaluation.py` (`evaluate_against_checkpoints`) |
| B6 | Agrégation vers la forme de retour existante ; ventilations droppées ; docstring périmée de `_eval_worker_task` corrigée (annonce un `shoot_stats` qui n'existe pas au retour) | `bot_evaluation.py` |
| B7 | Sonde exploiteur câblée sur `bot_eval_n_workers_intermediate` : elle évalue **pendant** l'entraînement, et la parallélisation la ferait sinon concourir à 16 workers contre les 24 de collecte (régime documenté : 47 Go de RSS, éval 42 % plus lente qu'à 4) | `training_callbacks.py` (`ExploiterProbeCallback`), `train.py` |

#### Invariants à verrouiller (pièges vérifiés dans le code)

1. **Injection avant le premier `reset()`.** `_reload_self_play_snapshot_if_needed` est *paresseux*
   et gardé par `self._self_play_snapshot_frozen and self._frozen_model is not None`
   (`env_wrappers.py`), l'appel partant du reset. Injecter après le premier reset ferait charger à
   l'env un `MaskablePPO` **nu, sans normalisation** — la violation de spec R0b que documente déjà
   le commentaire de `evaluate_against_checkpoints`. Ça ne lève pas et ça ne crashe pas : ça rend
   un score faux. Invariant testé, pas simple convention d'écriture.
2. **Murs de référence désactivés sur le chemin checkpoint.** Le constructeur de tâches bots
   matérialise des murs sur le holdout via `_materialize_eval_scenario_refs`, indexés par
   `(scenario_index + len(bot_name)) % len(eval_wall_refs)`. `evaluate_against_checkpoints` ne l'a
   jamais fait. Router les tâches checkpoint par ce chemin changerait la valeur des scores du gate
   **et** ferait dépendre le terrain de la longueur de l'étiquette d'étape (« P0 » vs « P10 »).
   Dérive métier déguisée en refactor de perf, invisible dans les chiffres : à neutraliser
   explicitement et à verrouiller par un test.
3. **`scenario_index` reste l'index global** dans `scenario_list` ; la tranche ne le touche pas,
   sans quoi les graines de deux tranches d'un même scénario collisionnent.
4. **`RandomBot()` conservé** pour une tâche checkpoint : il n'est jamais consulté (ratio
   self-play = 1.0) mais reste obligatoire — `BotControlledEnv.__init__` lève
   `requires either 'bot' or 'bots'` sur `bot=None`. C'est déjà ce que faisait la boucle
   historique. (Le plan initial annonçait « ne rien construire » : faux, vérifié au code.)
5. **`episode_start_index = ep_offset` sur chaque tranche — TROUVÉ PAR LA MESURE, pas par la
   lecture.** `BotControlledEnv._episode_index` est local au wrapper et sert de matériau de
   graine à trois tirages : le siège quand `agent_seat_mode='random'` (le cas de `x1_long`), le
   self-play, et le RNG du bot, tous bâtis sur `f"{global_seed}:{env_rank}:{episode_index}"`.
   Une tranche construite sans lui repart à 0 et rejoue le siège de l'épisode 0 — alors que ses
   graines d'épisode, elles, sont correctes. **La divergence est donc invisible côté graines**, et
   aucun des tests unitaires ne la voyait : ils mockent tous le worker.
   Mesure du défaut (2026-08-26, vrai chemin, `model_P1` contre archive `P0`, 8 épisodes
   holdout) : **3 victoires sur 8 en parallèle contre 1 sur 8 en série**. Après câblage de
   `episode_start_index` : 1 sur 8 des deux côtés. Verrouillé par deux tests + mutation rouge.

**Leçon de méthode** : le seul contrôle qui a attrapé ce défaut est le smoke sur le vrai chemin de
production. La parité d'un découpage ne se démontre pas en raisonnant sur les graines d'épisode —
il faut exécuter les deux côtés et comparer les issues.

#### Changement de sémantique assumé

Un épisode atteignant le plafond de steps sans finir est aujourd'hui compté dans `total` mais dans
aucun seau, et ressort en `_timeouts`. Il devient un **nul + une entrée `eval_loop_cap`** au journal
de troncatures — le comportement V11 §0.61 qui manquait à ce chemin. **Le win-rate ne bouge pas**
(`total` et `wins` identiques), seule la ventilation D/T change ; le compteur `_timeouts` est
conservé en le dérivant des troncatures `eval_loop_cap` pour que l'affichage R0b reste juste.

#### Tests (rouge/vert)

1. Partition des graines : séquence `_episode_seed` sur `[0..300)` identique découpée en tranches —
   unitaire pur, sans env.
2. Parallèle ≡ séquentiel : mêmes `wins/losses/draws` par label à graines fixes, **comparaison
   tranche par tranche des graines** et pas seulement des agrégats (un total juste peut l'être par
   compensation).
3. Injection : après construction et premier reset, `env._frozen_model` est l'instance du cache
   worker, jamais une instance rechargée (invariant 1).
4. Murs : une tâche checkpoint consomme le fichier de scénario brut (invariant 2).
5. `episode_start_index` : la tranche le reçoit égal à `ep_offset` (invariant 5).
6. Archive incompatible → skip journalisé §12.15, pas de crash de tâche ; une `RuntimeError`
   autre que « Missing key » remonte.
7. Épisode plafonné → nul + entrée `eval_loop_cap`, ratio inchangé.
8. Épisodes non joués (timeout de tâche) → lève, jamais un win-rate sur dénominateur tronqué.
9. Non-régression du chemin bot : `ep_offset` absent ⇒ démarrage à 0.
10. Sonde exploiteur : passe `bot_eval_n_workers_intermediate`, pas les 16 de l'éval finale.

**Smoke de production obligatoire** : les tests ci-dessus mockent le worker et ne peuvent pas voir
une divergence d'état d'environnement. La parité parallèle/série se mesure sur le vrai chemin
(vrai modèle, vrais scénarios holdout, issues comparées), pas seulement sur les graines.

Les deux tests existants de `tests/unit/ai/test_checkpoint_evaluation.py` patchent l'intérieur de la
fonction et sont réancrés (périmètre T2). `tests/unit/ai/test_exploiter_stage.py` patche la fonction
entière, donc insensible.

#### Pourquoi 4.2 n'est pas gratuite (correction du 2026-08-26)

Estimation initiale : « pool persistant ≈ gratuit si le pool est injecté plutôt que créé dans la
fonction ». **Faux.** `_eval_worker_init` charge le **modèle principal** dans le worker, et ce
modèle change entre deux évals d'un même run. Un pool persistant servirait donc un modèle périmé —
un faux vert silencieux, la classe de défaut que T1 interdit.

4.2 exige une étape de conception propre : sortir le chargement du modèle de l'initializer et le
faire par tâche sous jeton de version (mtime ou hash du zip), le worker ne rechargeant que si le
jeton a changé. Faisable, dans l'esprit de la 4.2, mais ce n'est pas de la plomberie. **4.1 se livre
et se mesure seule d'abord.**

#### Calibrage des tranches (à mesurer en 4.3, pas à figer)

Chaque tâche paie une construction de `W40KEngine` et un reset complet (107,6 ms mesurés au §1)
avant d'amortir sur ses épisodes. À 300 épisodes découpés en 16 tranches, l'amortissement ne porte
que sur 19 épisodes par tâche. Le nombre de tranches est un paramètre de mesure, pas une constante
égale à `n_workers`. Mesure de clôture : durée du gate avant/après, **≥ 3 répétitions, lecture sur
la médiane**, machine au repos (règle §1 « Pièges de mesure », établie par la Phase 1).

### Phase 5 — Options qui touchent au métier — ⛔ chacune = décision utilisateur explicite

À ne rouvrir qu'après mesure des phases 1-3. Aucune n'est recommandée par défaut.

| Option | Effet perf | Ce que ça change au métier |
|---|---|---|
| AMP/bf16 sur l'update | update plus court | numérique de l'apprentissage (gradients) |
| `batch_size` 1020 → 1023 | supprime le 9ᵉ minibatch de 24 (8184 = 8×1023) | hyperparamètre |
| `n_envs` 24 → 32/48 | amortit la latence par step | corrélation du batch, frontières GAE (341→~170 steps/env), RAM (~0,64 Go/worker) |
| Bots poids 0,0 exclus de l'éval intermédiaire | −40 % du budget d'éval | perte de la mesure continue holdout/benchmark |
| Device/format de l'adversaire self-play (GPU partagé, quantization) | steps self-play plus rapides | le jeu de l'adversaire gelé peut dévier numériquement |
| Sonde exploiteur E1-E3 parallélisée | jusqu'à ~10 h/run E* | protocole exploiteur gelé (`validate_exploiter_protocol`) à réviser |

---

## 5. Liens

- Goulot BFS natif (chantier lourd EN PAUSE, pré-existant) :
  `Documentation/Implémentation/A_faire/perf_noyau_natif_et_gzip.md` §2 — les étapes 1.1-1.2 ci-dessus
  sont le traitement **Python** du même goulot ; le noyau natif ne se rouvre que si, après Phase 1,
  le profil montre que le BFS domine encore.
- Optimisations move pool déjà livrées : `Documentation/Implémentation/Implémenté/V11_move_pool_optimization.md`,
  `V11_move_build_acceleration.md`, `perf_generate_compact_formation.md`.
- Procédure de profilage : `engine/perf_timing.py` (`W40K_PERF_TIMING=1`) — ne jamais l'armer sur un run vivant.
- ✅ (2026-08-26) La section « CPU vs GPU » de `Documentation/AI_TRAINING.md` a été réécrite sur les
  mesures du §1/§6 (l'ancienne « CPU 10 % plus rapide », 311 it/s, datait de l'ère pré-V11 : obs
  355 floats, MlpPolicy). Le jumeau `Documentation/AI_IMPLEMENTATION.md` § « CPU Optimization
  (311 it/s) » est marqué obsolète.

## 6. Journal des mesures

| Date | Contexte | Métrique | Valeur |
|---|---|---|---|
| 2026-08-18 | `x1_long --new` 50k ép. (pré-P3-8/P4) | durée totale | 5 h 54 |
| 2026-08-26 | run P1 vivant (pré-rampe self-play, 0 éval) | `time/fps` global · débit épisodes | ~200 steps/s · ~96 ép./min |
| 2026-08-26 | bench offline 1 env, chemin P1 exact, 600 steps | ms/step env (sans profiler) · ms/reset | 9,47 · 107,6 |
| 2026-08-26 | cProfile 300 steps (overhead ×2,6, % seuls) | masque · obs · tours bots · reward | 33,2 % · 31,9 % · 30,7 % · 0,2 % |
| 2026-08-26 | bench GPU (RTX 4060, contention run vivant = bornes inférieures) | forward rollout batch 24 · minibatch update 1020 · update complet (5 epochs) | 5,84 ms · 142,4 ms (7 163 éch/s) · ~5,7-6,0 s |
| 2026-08-26 | bench GPU minibatch 4080 | débit | 2 769 éch/s (×2,6 pire que 1020 — VRAM 8 Go saturée, 8160 infaisable) |
| 2026-08-26 | **Ligne de base Phase 0 (audit)** — run P1 vivant au moment de la mesure | ms/step · fps global SB3 · minibatch 1020 | **9,47 ms/step · 200 fps · 142 ms/minibatch** |
| 2026-08-26 | `bench_env_step.py` 600 steps, x1_long+bot, run P1 vivant (24 workers+learner actifs = contention CPU) | ms/step médiane · P95 · P99 (resets EXCLUS des step_times) | **32,97 ms · 662 ms · 1 882 ms** — médiane ×3,5 vs audit : contention CPU + tours bots longs via BotControlledEnv |
| 2026-08-26 | `bench_env_step.py` --profile 20 steps, top cProfile | poste dominant | reset initial 4,9 s sur 5,9 s total (exclu du timing réel depuis le fix) ; tours bots (`_run_bot_until_not_bot_turn`) = 3,9 s sur 5 appels = 777 ms/appel |
| 2026-08-26 | Harnais parité `test_parity_harness.py`, 4 tests | statut · durée | **4 verts · 55 s** — reproductibilité, détection mutation, gate mask_verification armée |
| 2026-08-26 | `bench_env_step.py` **machine au repos** (run P1 terminé) | ms/step médiane · P95 · P99 | ~~**10,14 ms · 214 ms · 489 ms**~~ — ⚠️ **CHIFFRE IRREPRODUCTIBLE, NE PAS UTILISER COMME RÉFÉRENCE.** Rejeu du 2026-08-26 (soir) sur le MÊME commit `8ba1db9c`, même binaire, même graine, machine au repos : médiane **27,94 / 31,02 / 32,70 ms** sur 3 répétitions — jamais 10 ms. La conclusion « machine au repos = référence » reste vraie ; la VALEUR était un tirage isolé. Baseline pré-Phase 1 corrigée dans les lignes du bas. |
| 2026-08-26 | Harnais parité après `/code-review` (5 findings appliqués) | statut · durée | **3 verts · 54 s** — un test dupliqué supprimé par la review ; bench revalidé fonctionnel |
| 2026-08-26 | **Phase 1 complète (1.1–1.9)**, `bench_env_step.py` 600 steps depuis worktree, run actif | ms/step médiane · P95 · P99 | **28,93 ms · 623 ms · 1163 ms** — −12 % médiane vs baseline run-actif (32,97 ms). Deux bugs d'invalidation corrigés en livraison : (a) `_squad_move_pool_cache`/`_charge_plan_cache`/`_edge_distance_cache` non purgés au reset épisode → stale hits en version 0 ; (b) `_ez_fp` non purgé dans `_recompute_squad_occupied_hexes` (modèle non-ancre). Mesure repos (machine au repos) à refaire hors run pour chiffre définitif. |
| 2026-08-26 | **/simplify post-livraison** (3 corrections sur les caches Phase 1) | — | (a) `_cbvp_key` n'incluait pas `intent` → `arm_charge_placement_decision` (intent=1–4) retournait systématiquement le plan intent=0, L10 charge placement silencieusement non-fonctionnel ; (b) `_shoot_pass_cache` absent du reset épisode → cache stale inter-épisode sur chemins API directs ; (c) sentinelle `object.__new__(object)` locale → constante module `_CBVP_MISS`. |
| 2026-08-26 (soir) | **Rejeu de contrôle machine au repos, 600 steps, seed=42, 3 répétitions par côté** — pré-Phase 1 = worktree détaché sur `8ba1db9c` (parent de la livraison Phase 1), post-Phase 1 = `main` | wall total · médiane · P99 | **PRÉ : 112,2 / 70,0 / 83,5 s · 32,70 / 27,94 / 31,02 ms · 1948 / 1849 / 1437 ms**<br>**POST : 64,9 / 68,9 / 46,6 s · 31,38 / 29,44 / 24,36 ms · 1076 / 1062 / 770 ms** |
| 2026-08-26 (soir) | **Verdict Phase 1** (même données que la ligne ci-dessus) | gain réel | **Le gain porte sur la QUEUE, pas sur la moyenne** — exactement la cible annoncée de la Phase 1. **P99 −44 %** (1745 → 969 ms de moyenne ; aucun chevauchement entre les 3 échantillons pré et les 3 post : min pré 1437 > max post 1076) · **wall −32 %** (88,6 → 60,1 s) · **médiane −7 %** (30,6 → 28,4 ms, du même ordre que le bruit). Aucune régression. |
| 2026-08-26 (soir) | **Défaut du harnais 0.1 constaté** | reproductibilité | Le bench **n'est PAS déterministe run-à-run** malgré `seed=42` : 70 → 112 s de wall sur le même commit. Une répétition unique ne peut pas trancher un écart < 30 %. ⇒ **toute mesure de clôture (1.10, 2.4, 4.3) exige ≥ 3 répétitions et se lit sur la médiane et le P99, jamais sur un tirage isolé.** |
| 2026-08-26 | **Item 1.7 — buffers numpy réutilisés** (`_obs_scratch`, `_unit_ent_cont`/`_unit_ent_bin`), `bench_env_step.py` 600 steps, machine au repos, 3 répétitions | wall total · médiane · P99 | **91,5 / 75,1 / 66,7 s · 30,0 / 33,3 / 28,3 ms · 1714 / 1355 / 1262 ms** — médiane dans la plage post-Phase 1 (24–31 ms) ; P99 dans la dispersion constatée (770–1948 ms). Gain isolable sur la médiane indistinguable du bruit (allocation ~27 × np.zeros ≪ coût des tours bots) ; la valeur est la suppression de l'allocation et la pression GC sur les runs longs. Parité bit-à-bit verte (5 tests, 56 s). |
| 2026-08-26 | **Mesure 2.4 — Phase 2 (non-régression env)**, `bench_env_step.py` 600 steps, machine au repos, 3 répétitions | wall total · médiane · P95 · P99 | **77,2 / 75,8 / 72,5 s · 31,2 / 30,3 / 29,2 ms · 703 / 688 / 676 ms · 1551 / 1455 / 1455 ms** — médiane dans la plage Phase 1 (24–31 ms), aucune régression côté env. |
| 2026-08-26 | **Mesure 2.4 — Phase 2 (gain learner)**, run réel `run_20260826-171446`, `x1 --new`, steps 33k–65k, pre-rampe self-play | `time/fps` (moyenne cumulée SB3) | **226 / 232 / 233 / 226 / 226 fps** sur 5 updates — **baseline pre-Phase 2 : 200 fps → +13–16 %**. Cohérent avec Phase 2 qui améliore l'update (~15 % du budget) d'un facteur ×2 : gain global attendu ≈ +15 %. `train/time_update` absent de SB3 par défaut ; seul `time/fps` disponible. |
| 2026-08-26 | **Phase 4 / B — parité parallèle vs série, vrai chemin** : `model_ArmageddonAgent_P1` contre archive `P0`, 8 épisodes sur les 4 scénarios holdout, machine au repos | W/L/D et win-rate | **AVANT correction : parallèle 3W/5L (0,375) vs série 1W/7L (0,125)** — divergence causée par `_episode_index` reparti à 0 sur chaque tranche (siège `agent_seat_mode='random'`, self-play, RNG bot). **APRÈS câblage de `episode_start_index=ep_offset` : 1W/7L (0,125) des DEUX côtés.** Aucun test unitaire ne voyait ce défaut — ils mockent tous le worker. |
| 2026-08-26 | **Phase 4 / B — coût au très petit budget** (même run que ci-dessus, 8 épisodes seulement) | wall parallèle · wall série | **322 s · 208 s — le parallèle est PLUS LENT à cette taille**, et c'est attendu : 8 épisodes sur 8 tâches font 1 épisode par tâche, donc le coût fixe (init du pool ~46 s, construction de `W40KEngine`, reset complet, chargement de l'archive par worker) n'est amorti par rien. Ce chiffre ne dit RIEN du gate réel (300 épisodes) ; il confirme en revanche que **le nombre de tranches doit être calibré en 4.3**, pas figé à `n_workers`. |
