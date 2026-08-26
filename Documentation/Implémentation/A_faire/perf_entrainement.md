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
(`ai/train.py:879` : `effective_n_steps = max(1, base_n_steps // n_envs)` → 341/env).

### Répartition d'un step d'env (cProfile 300 steps, chemin exact du run P1)

| Poste | Part du wall |
|---|---|
| Masque d'action (`get_squad_action_mask_and_eligible_units`) — dont carte BFS de move 14,5 % | 33,2 % |
| Observation (`build_squad_observation`) | 31,9 % |
| Tours des bots adverses joués dans le worker (`_run_bot_until_not_bot_turn`) | 30,7 % |
| Reward | 0,2 % |

Fonction la plus chaude : `entries_in_engagement_zone` (`engine/spatial_relations.py:503`) —
48 811 appels / 300 steps = 18,9 % du wall. Reset : 107,6 ms (rechargement scénario+rosters complet
à chaque épisode, cause `agent_roster_ref="training_random"` → `should_reload_scenario=True`).
Hors de cause (mesuré) : reward, callbacks, TensorBoard, évals (0 éval jouée sur les 4 630 premiers
épisodes, débit déjà à 96 ép./min).

### Goulots identifiés (fichier:ligne, vérifiés verbatim)

1. **2ᵉ RPC par step** : `sb3_contrib/common/maskable/utils.py:17`
   `return np.stack(env.env_method(EXPECTED_METHOD_NAME))` appelé par `ppo_mask.py:228` à chaque
   vec-step, en plus de `env.step` — 2 allers-retours pipe synchrones par step (~2,5 Mo picklés).
2. **Cache mono-slot du pool de move** : `engine/phase_handlers/shared_utils.py:13097`
   `_cache[str(squad_id)] = (_fp_key, result)` — l'alternance budget normal (choix d'activation)
   / budget advance (désignation) sur la même escouade rate systématiquement le cache
   → **2 BFS + érosions par activation de move** (`engine/action_decoder.py:592`).
3. **Fingerprint recalculé à chaque appel, hit compris** : `shared_utils.py:12990` — tuples triés
   sur toutes les unités + hexes occupés, payé même quand le cache sert.
4. **Scan linéaire** dans le prédicat le plus appelé du masque de tir :
   `_attacker_model_can_reach_squad` (`shared_utils.py:6947`) reparcourt `units` alors que
   `unit_by_id` existe.
5. **Double balayage du masque de tir** : `build_squad_action_mask` (`shared_utils.py:13187`) puis
   `shoot_weapon_sel_open_slots` (`shared_utils.py:13129`) refont chacun modèles × armes × cibles.
6. **Obs sans caches ciblés** : `charge_build_valid_plan` appelé 2× par état (masque jet réel + obs
   CHARGE_MAX_ROLL, `observation_builder.py:1519`) ; `edge_distance` recalculé par entité par step
   sans cache (`observation_builder.py:1350`) ; passe d'engagement et bloc TYPES recalculés par step ;
   ~27 `np.zeros` par build.
7. **Reset** : deepcopy du scénario JSON (`engine/game_state.py:485`) + glob/open/json.load des
   rosters **à chaque épisode** (`engine/w40k_core.py:9074`) + purge de tous les caches LoS/spatiaux.
8. **Update** : rollout **re-transféré intégralement au GPU à chaque epoch**
   (`sb3_contrib/common/maskable/buffers.py:219`), masques stockés en float32 (×4, `buffers.py:181`),
   ~225 `.item()` (syncs) de logging par update, `evaluate_actions` non compilé (torch.compile ne
   couvre que `policy.forward`, `ai/train.py:2207`).
9. **À-côtés par épisode** : `writer.flush()` TensorBoard à chaque épisode
   (`ai/metrics_tracker.py:656`) + boucle norme de gradient sur tous les tenseurs à chaque épisode
   (`ai/training_callbacks.py:1273`).
10. **Gate de fin d'étape curriculum** : 300 épisodes **séquentiels mono-process CPU** (~72 min à
    14,5 s/ép, `ai/bot_evaluation.py:2084`) alors que le pool 16 workers existe pour l'éval finale.
11. **Éval intermédiaire** : les 10 clés de `bot_eval_weights` sont jouées, poids 0,0 compris
    (`ai/bot_evaluation.py:1428`) — 4 bots / 10 = mesure pure, hors signal de sélection.

**Déjà en place (ne pas re-livrer)** : SubprocVecEnv 24 workers ; masque construit 1×/step nominal
avec handoff masque→obs (`w40k_core.py:2602`) ; `action_masks()` servi sans recalcul
(`env_wrappers.py:1356`) ; obs différée (1 build/step gym) ; cache LoS par paire avec invalidation
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
- ⚠️ **`bench_env_step.py` se lance MACHINE AU REPOS, jamais pendant un run.** Mesuré le
  2026-08-26 sur le même binaire et la même graine : **10,14 ms** de médiane machine au repos
  contre **32,97 ms** pendant le run P1 (24 workers + learner) — un facteur **×3,25** qui vient
  entièrement de la contention CPU, pas du code. Une mesure « après » prise au repos comparée à
  une mesure « avant » prise sous charge fabriquerait un gain de ×3 imaginaire. Les 10,14 ms au
  repos recoupent les 9,47 ms de la ligne de base d'audit : c'est cette valeur-là qui fait foi.
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
| 4 | Sonnet 5 | standard | Parallélisation sur un pool existant + tests seeds fixes |

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
| 1.1 | Cache **2 slots** (budget normal + advance) pour `build_squad_move_cell_map` — supprime le double BFS par activation de move | `shared_utils.py:13097` | 🟡 |
| 1.2 | Fingerprint sur hit → compteur de version d'état (invalidation à la mutation : commit_move, mort, phase) | `shared_utils.py:12990` | 🟡 |
| 1.3 | `_attacker_model_can_reach_squad` : scan linéaire → index `unit_by_id` | `shared_utils.py:6947` | 🟡 |
| 1.4 | Masque de tir : fusionner les 2 balayages modèles×armes×cibles (partager les résultats de la 1ʳᵉ passe avec `shoot_weapon_sel_open_slots`) | `shared_utils.py:13174/13129` | 🟡 |
| 1.5 | Obs : mémoïser `charge_build_valid_plan` (masque + obs dans le même état) | `observation_builder.py:1519` | 🟡 |
| 1.6 | Obs : pair-cache `edge_distance` avec invalidation au mouvement (motif LoS éprouvé) | `observation_builder.py:1350` | 🟡 |
| 1.7 | Obs : cache du bloc TYPES + réutilisation des buffers numpy (~27 `np.zeros`/build) | `observation_builder.py:1081/1183` | 🟡 |
| 1.8 | Pair-cache `entries_in_engagement_zone` (invalidation motif `_touch_unit_los`) | `spatial_relations.py:503` | 🟡 |
| 1.9 | Reset : cacher les `json.load` des rosters + supprimer le deepcopy complet du scénario (copies ciblées) | `w40k_core.py:9074`, `game_state.py:485` | 🟡 |
| 1.10 | **Mesure de clôture** : ms/step + fps offline ; consigner §6 | — | 🟡 |

Gain attendu : ms/step −30-50 % et réduction de la queue → fps ×1,5-2.
Verrou par item : parité bit-à-bit (0.2) + test rouge/vert.

### Phase 2 — Pipeline SB3 (learner) — zéro changement de maths

**Ordre imposé 2.1 → 2.2 → 2.3** : l'étape 2.3 est la seule que l'option A (Phase 3) jetterait —
elle se fait en dernier et **se saute si la décision A est prise entre-temps**.

| # | Étape | Ancre | Statut |
|---|---|---|---|
| 2.1 | Rollout **résident GPU** : buffer custom qui garde obs+masques sur le GPU (fin des ~4-5 Go H2D re-transférés à chaque epoch) + masques en bool (float32 ×4 aujourd'hui) | `maskable/buffers.py:219/181` | 🟡 |
| 2.2 | Logging différé : accumuler les scalaires sur GPU et ne `.item()` qu'en fin d'update (~225 syncs/update) ; `writer.flush()` et norme de gradient tous les N épisodes | `ppo_mask.py:394`, `metrics_tracker.py:656`, `training_callbacks.py:1273` | 🟡 |
| 2.3 | **Un seul RPC par step** : le masque voyage dans le retour de `step()` (infos) ; VecEnv custom ou surcharge de `collect_rollouts` — sautable si option A actée | `maskable/utils.py:17`, `ppo_mask.py:228` | 🟡 |
| 2.4 | **Mesure de clôture** : fps + durée d'update ; consigner §6 | — | 🟡 |

Sous-classes locales (dans `ai/`), jamais de fork du venv. Verrou : masques identiques bit-à-bit
vs `env_method`, loss/approx_kl identiques à seed fixe sur un run court.

### Phase 3 — Architecture de la collecte — ⛔ ARBITRAGE utilisateur

**Problème** : même après les phases 1-2, la collecte reste en pas cadencé — les 24 workers et le
GPU s'attendent mutuellement à chaque step. C'est structurel, pas optimisable localement.

- **Option A — collecte dans les workers, poids gelés par cycle** : chaque worker déroule ses
  341 steps avec une copie CPU de la policy (3,1 M de paramètres) et renvoie sa trajectoire ; le
  learner ne fait plus que l'update. Gain ×3-6 estimé ; coût 1-2 semaines + validation lourde.
- **Option B — VecEnv mémoire partagée + 2 envs/process** : garde la boucle SB3, supprime le
  pickle (~2,5 Mo/step). Gain ×1,3-1,6 ; coût 2-4 jours ; risque faible.
- **Option C — s'arrêter aux phases 1-2-4** : ×2-3 au total. Défendable si la league peut attendre.

**RECOMMANDATION : A** — seule option alignée sur le profil réel de la charge (moteur Python lourd,
réseau minuscule), et mathématiquement neutre : SB3 gèle déjà la policy pendant toute la collecte,
donc collecter avec les mêmes poids gelés dans les workers produit le même batch on-policy.

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
| 4.1 | Gate de fin d'étape parallélisé sur le pool subprocess 16 workers existant (aujourd'hui 300 ép. séquentiels mono-process ≈ 72 min → ~7 min ; ×14 runs ≈ ~15 h récupérées) | `bot_evaluation.py:2084`, `train.py:4818` | 🟡 |
| 4.2 | Pool d'éval persistant entre évals (init ~46 s payée à chaque éval : process spawn + rechargement modèle CPU) | `bot_evaluation.py:816` | 🟡 |
| 4.3 | **Mesure de clôture** : durée gate + durée éval ; consigner §6 | — | 🟡 |

Verrou : mêmes win-rates qu'en séquentiel à seeds fixes.

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
| 2026-08-26 | `bench_env_step.py` **machine au repos** (run P1 terminé), même binaire et même graine que la ligne au-dessus | ms/step médiane · P95 · P99 | **10,14 ms · 214 ms · 489 ms** — **×3,25 plus rapide qu'avec le run vivant (32,97 ms)**. Recoupe les 9,47 ms de l'audit : c'est la valeur de référence. ⇒ **toute mesure Phase 1+ se prend machine au repos** (cf. §1 Pièges de mesure) |
| 2026-08-26 | Harnais parité après `/code-review` (5 findings appliqués) | statut · durée | **3 verts · 54 s** — un test dupliqué supprimé par la review ; bench revalidé fonctionnel |
