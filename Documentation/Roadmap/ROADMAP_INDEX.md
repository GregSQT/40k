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
> et vérifie qu'aucun chantier ouvert de `Documentation/Chantiers/backlog/` n'est devenu
> inatteignable depuis ce fichier — un document que plus aucun fichier sujet ne cite n'est plus
> priorisé, il est seulement stocké.
> La porte de fusion `scripts/check_roadmap_declared.py` (hook `prepare-commit-msg`, versionné
> dans `.githooks/`) : une fusion dans `main` est refusée quand **2** chantiers ont été livrés
> sans que ce fichier bouge. Se débloquer : écrire la ligne du chantier puis `git add` (l'index
> vaut déclaration) ; fusion hors chantier : `ROADMAP_GATE=off git commit`.
>
> **Contrats permanents** (jamais archivés, hors roadmap) :
> `Documentation/Chantiers/Replay.md` (contrat `step.log`, pipeline replay) et
> `Documentation/Chantiers/analyzer_couverture.md` (matrice règle → contrôle → champs de
> log) — relus à chaque livraison qui touche le journal.
>
> **Exceptions actées** (numérotées ici et nulle part ailleurs) : `Bot_refactor.md` vit à la racine de `Documentation/Chantiers/` au lieu de `backlog/` (chantier vivant, chemin demandé) ; `archives/v11.md` porte l'historique du programme V11 entier et sert d'archive au sujet `v11_chemin_critique.md`.
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
| **J1 — Pipeline prouvé, ligne de base** ✅ | Run `x1_long --new` terminé le 2026-08-20 ; ligne de base REJOUÉE le 2026-08-21 sur `robust_0.8463` (post-rupture §12.15) : combined agent `0,8567`, pire bot `attrition = 0,810` ; reference bots mesurés bot-contre-bot (balanced `0,168`, denial `0,155`, reactive `0,139`) ; `benchmark_floor` remis à `0,90` le 2026-08-20 (le `0,049` mélangeait les sémantiques) — gate RETIRÉ depuis, le 2026-08-22 | Critères de [training.md#run-verif](training.md#run-verif) verts ; ligne de base panel rejouée ✅ |
| **J2 — Le gym décide tout** ✅ | P3-5, P3-6, P3-8, P4, P5 livrés ; `TOTAL_ACTION_SIZE` 1159→1389, `obs_size` 16671→16703 ; ré-entraînement `--new` nécessaire | Plus aucune décision de jeu jouée par une heuristique à la place de l'agent, hors optionnels statués par mesure de regret ✅ |
| **J3 — Mesure de référence** | Curriculum R1→R3 (URGENCE), puis `x1_long` (~6 h) | LE chiffre officiel du projet — solde §0.14, §0.67 et le critère T6 (via §10.6) |
| **J4 — Dépasser la mesure** | Capacités 06, É9 second scénario — priorisés selon ce que la mesure révèle | Win-rate au-dessus de la mesure de référence, reproductible |
| **J5 — Démo** | Validation qualitative §10.6 volet 2 (joueur externe), validations navigateur front soldées | Un externe joue contre l'agent et le trouve crédible ; le front tient la partie de bout en bout |

---

## ✅ URGENCE — Curriculum : adversaires et étalons (décision 2026-08-21)

**R0a/R0b livrés. R1→R3 absorbés par le curriculum `--etape` (décision 2026-08-30)** : le fix
aliasing obs Phase 3 (2026-08-29) invalide toute baseline antérieure ; le run `--etape P2`
post-fix tient lieu de R1 (ratio_mb0=1.0, EV→0.85). Le curriculum P0→P10 intègre les leviers
R2 (self-play) et R3 (récompense, si D.4 le justifie) séquentiellement — mesurer en standalone
n'apporterait que la décomposition du gain par levier. Fermé sans dette.
Détail : `Documentation/Chantiers/backlog/curriculum_adversaires_etalons.md`.

---

## J3 — Mesure de référence

| # | Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|---|
| 7 | training | Mesure de référence — `--test-only --step` sur champion final P10 (~8 min) | [v11_chemin_critique.md#mesure](v11_chemin_critique.md#mesure) | 🚫 |

---

## J4 — Capacités

Tâches J4 archivées → `archives/doc.md#hygiene-correctifs-ponctuels`

---

## Suspendus — ne pas commencer avant leur jalon

| Sujets | Chantier | Fichier | Jalon | ⚡/🚫 |
|---|---|---|---|---|
| moteur | **T7** Unification validation déploiement | [moteur.md#t7](moteur.md#t7) | Fix faux — re-analyser avant | 🚫 |
| moteur+training | **Force dispositions & missions** — home obj, VP scoring 4 missions, obs mission, reward conditionné, sampling, métriques | [missions.md](missions.md) | Terrains 4 missions créés par utilisateur | 🚫 |
| moteur | **Phase B** Observation des niveaux | [moteur.md#phase-b](moteur.md#phase-b) | Phase A' validée + LoS 3D complet | 🚫 |
| training+bot | **É9** Second siège + second scénario — levier `agent_seat_p2_ratio` livré 2026-08-28, plus deux correctifs de suivi le même jour : `_resolve_seat_p2_ratio` et `get_seat_stats` retournent `None` en modes de siège fixes au lieu d'un `0.5` interne trompeur (`ai/env_wrappers.py`, `ai/train.py`, tests rouge→vert). Le second SCÉNARIO reste ouvert | [training.md#e9](training.md#e9) | J4 — entraînement bot satisfaisant | 🚫 |
| training+bot | Validation qualitative §10.6 volet 2 | [bot.md#validation-externe](bot.md#validation-externe) | J5 — requis pour la démo | ⚡ |
| bot | MCTS à l'inférence §10.7 (plan B anti-coups-absurdes) | [bot.md#mcts-inference](bot.md#mcts-inference) | Après J3, seulement si la démo l'exige | 🚫 |

---

## ✅ Hygiène — correctifs ponctuels

Correctifs ponctuels livrés → `archives/doc.md#hygiene-correctifs-ponctuels`

Correctifs hors chantier (2026-09-03) : `worktree-fix-terrain-empty-string` (rejette chaîne vide dans accepts), `worktree-fix-biome-terrain-imports` (ordre imports Biome), `worktree-test-terrain-list-not-loaded` (trou test resolveSelectedTerrain liste non chargée + corrige accepts listLoaded), `worktree-fix-terrain-findings` (résolution conflit trim()), `worktree-fix-terrain-review-findings` (corrige 3 findings review terrain), `worktree-fix-terrain-review2` (guard availableTerrains + STORAGE_KEY test + trim test), `worktree-fix-terrain-simplify` (doublon import + trim redondant), `worktree-config-opus-default` (modèle par défaut Opus 5 + critères bannières CLAUDE.md), `worktree-suppress-objective-gamelog` (supprime le log des objectifs du game log PvP), `worktree-doc-hex-line-tiebreak-bias` (documente le biais de départage `hex_line` sur segments horizontaux), `worktree-cover-badge-per-model` + `worktree-cover-badge-ab-distinction` (badge de couvert par figurine — **ANNULÉS le 2026-09-03**, code restauré à l'identique de `9ec912e7` : le rendu obtenu en PvP était faux, et le badge unité-niveau d'origine fonctionnait. Cf. `archives/front.md` avant toute nouvelle tentative), `worktree-fix-promote-run-state` + `worktree-fix-promote-run-state-t1` (bug curriculum : `episode_count_total` non propagé dans le run_state de l'étape promue — `promote_stage_model` copiait le run_state canonical à 0 ; fix : `save_run_state` explicite juste avant la promotion dans `_close_curriculum_stage`, levée si la clé est absente, test rouge→vert).

---

## Soutien — backlog hors jalons

### Prêt à démarrer

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| moteur+training | **Stratagèmes réactifs** — Fire Overwatch §15.08 + Heroic Intervention §15.11 ; **slots obs réservés avant R1** (`"charged"` UNIT_BIN + 2 types AGENT_DECISION) livrés 2026-08-25, implémentation J4 | [moteur.md#reactive-stratagems](moteur.md#reactive-stratagems) | 🚫 |
| front | Validations navigateur en attente | [front.md#validations-nav](front.md#validations-nav) | ⚡ |

### À cadrer avant d'ouvrir

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| moteur | LoS 3D : tir à travers un mur depuis un étage (signalé 2026-08-11, jamais cadré) | [moteur.md#los-mur-etage](moteur.md#los-mur-etage) | 🚫 |
| bot+training | Chantier récompense distinct (relevé du chantier panel) | [bot.md#recompense](bot.md#recompense) | 🚫 |

### Lourds — re-cadrer avant toute reprise

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| moteur | Preview de tir sans deepcopy | [moteur.md#preview-tir](moteur.md#preview-tir) | 🚫 |
| infra | **Accélération entraînement RL** — Phase 0 ✅ + Phase 1 ✅ **mesurée machine au repos 2026-08-26** (1.1–1.9 livrés ; **1.7 ✅ buffers numpy livrés (2026-08-26)** ; gain réel sur la QUEUE — P99 −44 %, wall −32 %, médiane −7 % sur 3+3 répétitions) ; bench_env_step ✅ **reproductible (2026-08-26)** ; **Phase 2 ✅ complète (2.1–2.4, 2026-08-26)** (GPU buffer, GPU metrics, inline masks ; +13–16 % fps mesuré run réel) ; **Phase 4 : 4.1 ✅ livré (2026-08-27)** — gate d'étape parallélisé, décision B actée et implémentée (B1–B7, unification du harnais checkpoint dans le harnais bot, parité confirmée 8-ép + tests) ; **4.2 ✅ livré (2026-08-27)** — pool persistant + jeton version `(model_path, mtime)`, rechargement seulement sur changement, `create_checkpoint_eval_pool`, `ExploiterProbeCallback._on_training_start/end` ; **4.3 ✅** `bot_eval_n_workers` → 2 (n=6 plus lent que n=2, F_6=1 293 s vs F_2=58 s, 2026-08-27) ; **Phase 3 ✅ livrée (2026-08-28)** — collecte distribuée Option A : workers déroulent 340 steps en autonome avec policy CPU gelée, retournent trajectoire, learner update-only ; 4 bugs review corrigés (double norm, raw_gc corrompu, ordre bootstrap, num_timesteps) ; 34+5 tests verts ; **gain time/fps mesuré : médiane 487 fps (3 reps x1_debug, machine au repos, 2026-08-28) vs 229 fps Phase 2 → +113 % (×2,1)** ; **correctifs Phase 3 (2026-08-28)** : durées épisodes distribuées injectées depuis les workers (cross-traj sentinel -1.0, reset exclu), crash action_dist workers corrigé (PointerMaskablePolicy recrée action_dist absent), 5 bugs timing/guard/stale corrigés, simplification harnais ; 35 tests verts ; **correctifs Phase 3 (2026-08-29)** : fix-pyright-check-ai-rules (20 erreurs pyright + terme interdit), fix-tests-back (8 tests rouges ai corrigés), phase3-reward-fix (normalisation rewards cold-start + diag/ TF), fix-ret_var-rescaling (value_loss gonflé — clip×rescale 15×), diag-logprob-drift (instrumentation drift log_prob/ratio mb0 — `diag/logprob_drift_mean_abs_mb0` + `diag/ratio_mb0_mean`, exp(mean) pour éviter débordement float32 et biais Jensen) ; 27 tests verts ; **retrait du re-scaling du critique (2026-08-29)** — deux approches successives du même défaut cold-start : d'abord une garde `count > 1.0` (test-cold-start-value-scale, `689729a0`), puis la suppression complète du facteur `sqrt(old_ret_var)/sqrt(new_ret_var)` sur `values`, `last_values` et le bootstrap (phase3-supprimer-rescaling-values, `ed091ab6`), qui rend la garde caduque : au rollout 1 d'un run `--new` le facteur valait 0,060 et écrasait les prédictions du critique de 17× (`value_loss` 15,1 et `explained_variance` −0,37 au rollout suivant), `ret_var=1.0` n'étant que la valeur d'initialisation de `RunningMeanStd` ; SB3 et le chemin stepwise ne rescalent jamais. Verrous durcis ensuite (audit-verrous-cold-start) : assertion exacte `returns[-1] = r_last + gamma*last_value` au lieu d'un seuil sur `returns.mean()` qui laissait passer un `last_values ×0.5` (vérifié vert), et couverture du chemin de clipping (`raw_reward=150`, le cas que le `ret_var` gelé saturait à 10,0) ; un test comparant deux scalaires calculés sur place a été supprimé, prouvé vert face au défaut réintroduit ; 31 tests verts. **ROOT CAUSE du non-apprentissage trouvée et corrigée (2026-08-29)** : aliasing des buffers scratch d'observation — le worker distribué stockait les obs PAR RÉFÉRENCE pendant 340 steps alors que le moteur les sert dans des buffers réutilisés (`observation_builder`, contrat « ne jamais stocker au-delà du step courant ») → buffer du learner = état final répliqué (tout sauf `global_cont`), d'où `diag/ratio_mb0` 0,92-0,95 (attendu 1,0), `explained_variance` figée à ~0, critique effondré sur une constante ; le chemin stepwise était protégé par accident (pickle du pipe) ; présent depuis `4b2fe20d` (commit initial Phase 3) — le retrait du re-scaling était justifié mais n'était pas la cause. Fix : copie profonde dans `normalize_obs_with_snapshot` + `terminal_observation` (2 sites), verrous rouge/vert `test_obs_stored_are_copies_not_scratch_refs` + `test_terminal_observation_is_copied_before_reset` ; 33 tests verts ; **jumeau `n_envs = 1` corrigé (2026-08-29)** — `DummyVecEnv` (SB3 2.9) pose `terminal_observation = obs` puis `reset()` puis `deepcopy`, donc le bootstrap `TimeLimit.truncated` évaluait l'obs INITIALE de l'épisode suivant (mesuré chaîne de production : 28/28 clés identiques au post-reset avant fix, 4/28 différentes après) ; copie à la sortie de `BotControlledEnv.step` et `SelfPlayWrapper.step`, 2 verrous rouge/vert. **Validation en cours : run `--etape P2` du 2026-08-29, critère `ratio_mb0 = 1,0` exactement + `explained_variance` croissante dès les premiers rollouts** | [infra.md#perf-entrainement](infra.md#perf-entrainement) | ⚡ |
| infra | Noyau natif BFS move/empreintes — pool de move = 29 % d'une partie d'évaluation | [infra.md#noyau-natif](infra.md#noyau-natif) | ⚡ |
| infra | Migration PostgreSQL | [infra.md#postgresql](infra.md#postgresql) | ⚡ |
| infra | MCTS adversaire d'entraînement | [infra.md#mcts](infra.md#mcts) | 🚫 |
| bot | Tranches 2-3 benchmark — schedule P0→P10 + exploiters : code et tests livrés 2026-08-22 (`--etape`, `curriculum.json`, pool figé par-env, `ExploiterProbeCallback` sondage synchrone + `validate_exploiter_protocol` + `exploiter_config`, 24 tests verrou) ; restent les 14 runs (~260 h) | [bot.md#league](bot.md#league) | 🚫 |

---

## Hygiène documentaire

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| doc | 🟠 **Refonte Documentation/** — P1–P3 livrées (2026-08-27) ; P4 consolidation : moteur+backlog (16→9 docs, 20 sources archivées), training (7→5 docs, 7 sources archivées) et **jeu+outils** (jeu 3→3 noms d'objet, outils 7→4 dont fusion 5→1 `outils_conformite`, 11 sources archivées) livrés 2026-08-28 ; **v11** (5 renommages d'objet, strates §9.4 purges) et **infra** (3 renommages d'objet, corps re-vérifiés, gardes re-pointées) livrés 2026-08-28 — P4 complète, les 5 lots livrés ; correctif de suivi : slot `m` du dashboard de `metriques.md` réaligné sur `m_immediate_reward_ratio_mean` (l'ancien tag n'est plus émis) ; **correctif de suivi 2026-08-28** : 2 tests rouges de vérification documentaire recalés sur les noms P4 (V11_phaseA → decisions_du_joueur, V11_agent_rework → index_v11), lot P4 v11 finalisé (sweep 5 refs code, strate périmée §9.4bis + T6, tables correspondance 5 docs) | [doc.md#refonte](doc.md#refonte) | ⚡ |
