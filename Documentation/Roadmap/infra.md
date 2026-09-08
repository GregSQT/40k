# Infra / Perf / DB — Tâches ouvertes

---

## Accélération de l'entraînement RL — phases 0→4 {#perf-entrainement}

**✅ Phases 0, 1, 2, 3 et 4 entièrement livrées.** Gains réels : Phase 1 = P99 −44 % et wall −32 % ;
Phase 2 = `time/fps` 200 → 226-233 (+13-16 %) ; Phase 4 = gate parallélisé + pool persistant + `bot_eval_n_workers` → 2.
Phase 3 livrée (2026-08-28) : collecte distribuée Option A — chaque worker déroule 340 steps en
autonome avec policy CPU gelée, retourne sa trajectoire ; learner fait uniquement l'update GPU.
**Gain time/fps mesuré (2026-08-28) : médiane 487 fps (3 reps x1_debug, machine au repos) vs 226-233 fps Phase 2 → +113 % (×2,1).** Voir §6 perf_entrainement.md.
Correctif qualité d'apprentissage (2026-08-29) : le re-scaling des sorties du critique par
`sqrt(old_ret_var)/sqrt(new_ret_var)` est retiré — au rollout 1 d'un run `--new` il valait 0,060
et écrasait les prédictions de 17×, `ret_var=1.0` n'étant que la valeur d'initialisation de
`RunningMeanStd`. Ce retrait était justifié mais n'était PAS la cause du non-apprentissage.
**ROOT CAUSE trouvée et corrigée (2026-08-29) : aliasing des buffers scratch d'observation** —
le worker Phase 3 stockait les obs par référence pendant 340 steps alors que le moteur les sert
dans des buffers réutilisés (`observation_builder`), donc le buffer du learner contenait l'état
FINAL répliqué (tout sauf `global_cont`) ; preuves : `diag/ratio_mb0` 0,92-0,95 au lieu de 1,
`explained_variance` figée à ~0 sur 47 updates, `last_values` GPU/CPU pourtant identiques.
Fix : copie profonde dans `normalize_obs_with_snapshot` + `terminal_observation` (2 sites) ;
verrous `test_obs_stored_are_copies_not_scratch_refs` + `test_terminal_observation_is_copied_before_reset`
(rouges constatés). Détail au journal §6 de `perf_entrainement.md`. **Validation en cours :
run `--etape P2` lancé le 2026-08-29, critère `ratio_mb0 = 1,0` + `explained_variance` croissante.**
**Jumeau `n_envs = 1` corrigé (2026-08-29)** : même aliasing sur le chemin `DummyVecEnv` — SB3
2.9 pose `info["terminal_observation"] = obs` puis appelle `env.reset()` puis `deepcopy` les
infos, donc le bootstrap `TimeLimit.truncated` de `patched_ppo` évaluait `V(obs initiale de
l'épisode suivant)`. Mesuré sur la chaîne de production (`Monitor(BotControlledEnv(ActionMasker(
W40KEngine)))`, épisode tronqué) : 28 clés sur 28 identiques à l'obs post-reset avant le fix,
4 clés différentes après. SB3 n'étant pas patchable, la copie est faite à la sortie des deux
wrappers gym (`BotControlledEnv.step`, `SelfPlayWrapper.step`), une fois par épisode — 9,1 µs
mesurés, le chemin subproc qui copie déjà côté worker n'en double rien de mesurable.
Verrous `test_terminal_observation_dummyvecenv.py` (2 tests, rouges constatés).
**Phase 2.1 réduite le 2026-09-07 — les observations sortent du buffer GPU.** Le profil de
lignée quadruple le rollout (`n_steps` 32640) et le bloc d'observations, 3,16 Gio, était résident
DEUX fois : en RAM numpy et en VRAM, `self.observations` n'étant jamais libéré après l'upload.
Sur une carte de 8 Go dont ~1 Go est déjà pris au repos, le débordement ne lève pas d'OOM sous
WSL2 — le driver bascule en mémoire système, la VM swappe et Windows la tue. Seuls les champs
compacts restent résidents (masques compris, 181 Mo à ce rollout) ; les observations partent
mini-lot par mini-lot. Mesuré par `torch.cuda.memory_allocated` aux dimensions de P2 : VRAM du
buffer **3,437 → 0,275 Gio**, contre **+3,24 s par update** de transferts, dont 1,4 s
d'indexation numpy qu'un tampon *pinned* ne rend pas (mesuré). Verrou
`test_observations_are_never_uploaded_in_bulk` (rouge constaté sur réintroduction de l'upload).
Goulots restants : aucun identifié de cette ampleur.

→ `Documentation/Chantiers/backlog/perf_entrainement.md`

---

## Noyau natif BFS move/empreintes {#noyau-natif}

**Lourd, EN PAUSE** (décision 2026-08-16 : non lancé). Le pool de déplacement (`build_squad_move_cell_map` → `erode_move_pool_by_squad_block` → `geodesic_move_reach`) pèse **29 % d'une partie d'évaluation** — calcul dérivé, optimisable sous verrou d'empreinte `step.log`.

Depuis le 2026-09-08, `geodesic_move_reach` est passé de **20,4 % à 8,0 %** du step en Python pur (index entiers de `hex_index_table` + expansion par couches, mesuré 3 fois, une variante par processus). Le noyau natif garde donc `erode_move_pool_by_squad_block` et `hex_line_iter` comme cibles principales, plus le BFS déjà allégé.

**Attention à l'instrument (2026-09-08)** : cProfile déforme ce banc d'un facteur **2,5** (240,9 s de `total_tt` contre 94,98 s de wall réel sur 600 steps) et gonfle spécifiquement les fonctions à très fort nombre d'appels. Deux « postes chauds » qu'il désignait sont des artefacts — `_model_fp` 7,5 % → **1,38 %** en échantillonnage, `generate_compact_formation` 3,9 % → **0,79 %** — tandis qu'il sous-estimait `hex_line_iter` (4,6 % → **9,22 %**). Conclure au `py-spy` ou au wall-clock, jamais au cProfile.

Répartition réelle du step (sans profileur, 600 steps, machine au repos) : move **44,2 %** (142 ms/step), shoot **35,0 %** (212 ms/step), charge **12,6 %** — mais à **731 ms/step**, la phase la plus chère du jeu —, command 3,0 %, fight 2,7 %, deployment 2,5 %. Les resets ne pèsent que 8,2 %.

- `hex_line_iter` : **gain Python facile déjà pris** le 2026-09-08 (dédup par cellule précédente au lieu d'un `set` qui ne retirait jamais rien — la i-ème cellule d'un cube-lerp est à distance cube `i`, donc toutes distinctes). **10,1 %** sur la boucle seule, mesuré sur corpus fixe, deux variantes alternées dans le même processus, 7 reps ; soit ~1 % du step, que la variance du banc complet (33-43 ms/step) ne résout pas. La fonction reste à **9,22 %** de temps propre : elle demeure une cible de noyau natif, pas un sujet clos.
- `arm_charge_placement_decision` (`charge_handlers.py`) : **13,08 %** du wall en échantillonnage, premier bloc identifié. Investigué le 2026-09-08, **aucune réécriture contenue n'est justifiée** — le coût est le VOLUME de la recherche (341 000 tests d'engagement de cellules candidates pour 200 steps), pas une primitive naïve. Les deux leviers évidents sont déjà pris : le cache `_EZ_PAIR_CACHE` exclut délibérément ces sondes (`memoise=False`, critère posé en quatre passes — les mémoïser fait tomber le taux de touche de 83 % à 29 %), et `euclidean_edge_distance` élague déjà par disque englobant avant de construire le moindre contour, y compris pour une paire 1×1. Le réduire demande de diminuer le nombre de cellules explorées : changement d'algorithme, à cadrer avant d'écrire.

→ `Documentation/Chantiers/backlog/perf_noyau_natif_et_gzip.md` §2

---

## Migration PostgreSQL {#postgresql}

**Lourd, re-cadrer avant reprise.** Plusieurs semaines. Spec de mars 2026 visant des modules `ai/` réécrits par V11 depuis — re-confronter au code avant.

→ `Documentation/Chantiers/backlog/migration_postgresql.md` ; prompt d'exécution : `Documentation/Chantiers/backlog/migration_postgresql.md`

---

## MCTS adversaire d'entraînement {#mcts}

**Suspendu — re-spécifié le 2026-09-08.** La spec `mcts_adversaire.md` (rollouts de bots,
espace macro, `GameAdapter`) est remplacée par `mcts.md` : un seul module de recherche guidé
par la policy (priors + tête de valeur du réseau, dés tirés, espace micro réel), en trois
sièges ordonnés par la mesure — inférence de l'agent (S1, gate G1), distillation Expert
Iteration dans PPO (S2), puis seulement champion + recherche dans le pool (S3). L'usage
« adversaire indépendant » de l'ancienne spec est rejeté sur mesure (pas moteur 57 ms, clone
745 ms avant tri des caches). Prérequis S0 : un clone d'état rapide côté moteur (nouveau module, spécifié
dans `mcts.md` §3.4), jumeau de `services/game_snapshots.py`. Ne s'ouvre qu'après J3 (`ROADMAP_INDEX.md`).

Même sujet que le MCTS à l'inférence ([bot.md#mcts-inference](bot.md#mcts-inference)) : un
seul document désormais.

→ `Documentation/Chantiers/backlog/mcts.md` (fait foi) ;
`Documentation/Chantiers/backlog/mcts_adversaire.md` (historique, bandeau)
