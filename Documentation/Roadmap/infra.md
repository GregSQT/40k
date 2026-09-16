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
**Fuite d'activations de l'échauffement critic corrigée (2026-09-16)** : en échauffement B6, les
pertes de la branche politique empilées avec leur graphe retenaient les activations de chaque
mini-lot jusqu'à la fin de l'update — **9,69 Gio alloués / 12,11 réservés par update** contre
1,79 / 2,08 en régime normal (réplique de `train()` sur le zip réel), réservation jamais rendue
sous WSL2 → 12 Gio à vie sur 8 Go de VRAM, `train/time_update` 5 s → 20-345 s dès que la
résidence est perturbée (run `run_20260916-092441`). Après correctif : **1,79 / 2,29**. Courbes
`train/cuda_peak_allocated_gib` et `train/cuda_reserved_gib` ajoutées. Verrou
`test_value_warmup_memory.py`. Journal §6 de `perf_entrainement.md`.

→ `Documentation/Chantiers/backlog/perf_entrainement.md`

---

## Noyau natif BFS move/empreintes {#noyau-natif}

**Lourd, EN PAUSE** (décision 2026-08-16 : non lancé). Le pool de déplacement (`build_squad_move_cell_map` → `erode_move_pool_by_squad_block` → `geodesic_move_reach`) pèse **29 % d'une partie d'évaluation** — calcul dérivé, optimisable sous verrou d'empreinte `step.log`.

Depuis le 2026-09-08, `geodesic_move_reach` est passé de **20,4 % à 5,2 %** du step en Python pur, en deux temps : index entiers de `hex_index_table` + expansion par couches (20,4 → 8,0 %), puis mémoïsation de la carte d'obstacles `BlockedBitmap` (8,0 → 5,2 %). Sur le périmètre complet obstacles + BFS, **8,8 % → 7,0 % du wall** (3 répétitions, une variante par processus, machine au repos). Le noyau natif garde donc `erode_move_pool_by_squad_block` et `hex_line_iter` comme cibles principales, plus le BFS déjà allégé.

**Verrou d'intégration (2026-09-09)** : `tests/integration/pvp/test_move_geodesic_x1.py` exerce `geodesic_move_reach` par le flux HTTP PvP sur le plateau `44x60x1` (fixture `game_x1`), seule résolution où `geometry_is_hex` impose la métrique hex — la suite d'intégration joue x5, en euclidien, et n'atteignait donc jamais ce chemin. Un portage natif se mesure désormais contre ce test en plus de l'empreinte `step.log`.

**Attention à l'instrument (2026-09-08)** : cProfile déforme ce banc d'un facteur **2,5** (240,9 s de `total_tt` contre 94,98 s de wall réel sur 600 steps) et gonfle spécifiquement les fonctions à très fort nombre d'appels. Deux « postes chauds » qu'il désignait sont des artefacts — `_model_fp` 7,5 % → **1,38 %** en échantillonnage, `generate_compact_formation` 3,9 % → **0,79 %** — tandis qu'il sous-estimait `hex_line_iter` (4,6 % → **9,22 %**). Conclure au `py-spy` ou au wall-clock, jamais au cProfile.

Répartition réelle du step (sans profileur, 600 steps, machine au repos) : move **44,2 %** (142 ms/step), shoot **35,0 %** (212 ms/step), charge **12,6 %** — mais à **731 ms/step**, la phase la plus chère du jeu —, command 3,0 %, fight 2,7 %, deployment 2,5 %. Les resets ne pèsent que 8,2 %.

- `hex_line_iter` : **gain Python facile déjà pris** le 2026-09-08 (dédup par cellule précédente au lieu d'un `set` qui ne retirait jamais rien — la i-ème cellule d'un cube-lerp est à distance cube `i`, donc toutes distinctes). **8,0 %** sur la boucle seule (9,3 % sur le minimum), mesuré sur corpus fixe de 3 000 lignes, la VRAIE fonction de production contre l'ancien corps replacé AU NIVEAU MODULE, alternées dans le même processus, 9 reps. Le premier chiffre publié, 10,1 %, comparait deux copies LOCALES d'un script : à portée de noms inégale, il surestimait de 2 points — comparer des fonctions locales à du code de module est un biais de mesure, pas un détail. Soit ~1 % du step, que la variance du banc complet (33-43 ms/step) ne résout pas. La fonction pesait encore **9,22 %** de temps propre — part mesurée AVANT la mémoïsation `BlockedBitmap`, donc à re-mesurer : le step ayant raccourci, sa part a mécaniquement augmenté. Elle demeure une cible de noyau natif, pas un sujet clos.
- `arm_charge_placement_decision` (`charge_handlers.py`) : **13,59 %** du wall en échantillonnage (re-mesuré le 2026-09-09 APRÈS `BlockedBitmap` ; c'était 13,08 % avant, le « plancher » annoncé est donc confirmé). Reste le premier bloc identifié. Le coût est le VOLUME de la recherche : `charge_build_valid_plan` produit 303 979 calculs d'engagement pour 200 steps, soit **97,5 % de tout le calcul d'engagement du step** (attribution par inspection de pile, pas par déduction). Deux leviers restent hors de portée et ne doivent pas être re-tentés : `_EZ_PAIR_CACHE` exclut délibérément ces sondes (`memoise=False`, critère posé en quatre passes — les mémoïser fait tomber le taux de touche de 83 % à 29 %), et `euclidean_edge_distance` élague déjà par disque englobant avant de construire le moindre contour, y compris pour une paire 1×1.
- **Mémo d'engagement entre les 5 intentions — livré le 2026-09-09.** `intent` ne pilote que la clé de tri : le verdict « cette cellule engage-t-elle une cible ? » est identique d'une intention à l'autre, et il est désormais partagé par les cinq appels (`charge_engage_memo`, `shared_utils.py`). **Gain compté, avec et sans mémo sur le même run de 200 steps : 348 613 → 284 631 calculs d'engagement, soit 18,4 % supprimés.** Et non les ~70 % que la part des intentions 1-4 laissait espérer : `occupied_after` diverge dès la première figurine posée, et les gardes d'atteignabilité et de légalité éliminent la plupart des cellules avant ce test. **Le wall du banc ne résout pas ce gain** (~3 % attendu contre une variance inter-reps de 33 à 46 s sur 400 steps, machine au repos) — se fier au compte déterministe, pas au chronomètre. **Double verrou, posé le 2026-09-09** : `tests/unit/engine/test_charge_intent_memo_contract.py` compare les 5 plans avec mémo aux 5 plans sans aucune mémoïsation, sur de vrais états de charge ; `tests/unit/engine/test_charge_memo_steplog_footprint.py` est le **verrou d'empreinte `step.log`** exigé par ce chantier — il compare la trace COMPLÈTE d'une partie ensemencée, avec et sans mémo.
- **Champ de montée par-figurine (`_model_multilevel_reachable_field`, cible de `erode_move_pool_by_squad_block`) — livré le 2026-09-12 : −7,9 % de temps CPU** (`ab_bench.py --episodes 24 --paires 5`, verdict 0,921, couples sans dérive 0,914–0,927 ; empreinte `refactor_fingerprint.py --episodes 8` identique). Deux économies sans changement de résultat : (1) pré-check de portée `multilevel_target_within_straight_bound` (`geodesic_move.py`) — borne inférieure ligne droite + |Δhauteur| avec la tolérance `_SEG_TOL` du Dijkstra ; 305 des 675 champs d'un run de 8 épisodes n'atteignaient aucun niveau cible (34 % du temps de ces champs) et sont rendus vides sans passe ; jumeau charge `_charge_model_multilevel_reachable_cells` traité ; (2) portails `_build_level_transitions` mémoïsés par VALEUR (frozensets d'étage, hauteurs, plateau, flag — jamais `id()`), reconstruits 675 fois auparavant. Verrous `test_multilevel_field_precheck_memo.py` (7 tests, rouges constatés). Écartée à x1, livrée en lot B le 2026-09-12 (suite 102) : la réutilisation du champ euclidien par-figurine dans `ascent_field_for_model` — à x1 le mode est `geodesic` (3 231 appels) / `cube` (95), jamais `euclidean` : 0 hit de cache sur 679 appels, gain nul sur ce chemin ; en métrique euclidienne (x5 : PvE, phase finale `gym_distance_metric`), l'érosion mémoïse le champ de plain-pied (`eucl`) AVANT le champ de montée, dont la passe de niveau 0 est le même Dijkstra — il est injecté en `precomputed_start_field` de `reachable_multilevel_field` SEULEMENT s'il est déjà en cache (jamais calculé : le pré-check de portée reste devant). Mesuré sur 1 épisode x5 euclidien : champ en cache pour 93 appels sur 93, 44 passes de départ supprimées, champ de montée 8,1 s → 1,0 s sur ~155 s d'épisode (≈ 4,5 %) ; `ab_bench.py --board board/44x60x5 --gym-metric euclidean --episodes 4 --paires 5` verdict 0,861 mais étendue 0,750–0,973 sur machine saturée (load 22, sessions parallèles) — seul le couple à wall ≈ cpu (0,973) est lisible : gain retenu **3 à 5 %** de l'épisode x5 euclidien, nul en hex. Empreintes `refactor_fingerprint.py --episodes 8` identiques avant/après pour x1 (`074ad56e…`), x5 hex (`7c223205…`, `--board`) et x5 euclidien (`f926e1a2…`, `--gym-metric`, override EN MÉMOIRE par décoration du loader, jamais dans un JSON). Dans le même lot : la case de départ retirée des obstacles sol du champ de montée (miroir du champ à plat ; sans effet sous la config livrée `can_move_through_enemy_engagement_zone: true` — 0 occurrence sur 675/602/645 champs des trois runs — mais nécessaire à l'identité des deux champs dès que la bande d'EZ est infranchissable). Verrous `test_ascent_field_reuses_euclidean_field.py` (8 tests : égalité `geodesic_field` / `geodesic_field_multi_source` sur source unique avec murs, ennemi et contact ; champ identique avec/sans réutilisation, passe de départ comptée ; cache-only ; départ en hauteur ; figurine dans la bande d'EZ). Poste dominant mesuré au passage : le champ euclidien de plain-pied lui-même = 62–65 % du wall d'un épisode x5 euclidien.

Trois choses mesurées en le posant, à savoir avant de le rejouer ailleurs :
- **La trace est déterministe.** Deux runs identiques de 150 pas rendent le même nombre de lignes, et les seules qui diffèrent portent `Duration=<n>s`, du temps de mur. C'est, avec l'horodatage de début de ligne, la seule chose à normaliser. **La GRAINE, elle, est un paramètre de mesure et pas une constante** : une politique aléatoire masquée ne rejoue pas la même partie après un changement de moteur, et la graine 42 d'origine (402 lignes, 2 charges) a cessé de produire la moindre charge dès l'ouverture de la verticalité au move (13.06), qui ajoute un point de décision. Re-mesuré le 2026-09-09 sur SEIZE graines, par le harnais du verrou lui-même : neuf en produisent, la **10** en produit 5 — c'est elle que porte le verrou (338 lignes). Elle a remplacé la 0, retenue le matin même (323 lignes, 3 charges) et tombée à zéro charge dès les livraisons suivantes du jour : le tirage se redécale à chaque changement du moteur, ce qui fait de cette ligne une mesure à refaire, jamais une constante.
- **`step.log` porte bien le par-figurine sur la charge.** Le segment `[MODELS: <mid>@(c,r,z) …]` est capturé immédiatement après `commit_move` (`def _finish_charge_after_placement`, `engine/w40k_core.py`) et accolé génériquement par `log_action` : 244 lignes sur 338 le portent, les 5 lignes de charge comprises. Un verrou d'empreinte voit donc un placement par figurine modifié — il n'est PAS limité à l'ancre d'escouade.
- **Le verrou ne passe pas par `--test-only --step`, et c'est un choix, pas un contournement.** Au 2026-09-09 le modèle `ArmageddonAgent_x1` précède la dernière croissance de l'observation (`global_bin` 83 contre 94, `global_cont` 13 contre 23, `grid` 9 canaux contre 12), donc le chargement refuse le checkpoint et le run s'arrête — comportement VOULU (T1 : erreur explicite plutôt que reprise silencieuse sur poids aléatoires), qui se résout par un ré-entraînement `--new` et n'a rien d'un défaut. Surtout, un verrou d'empreinte adossé à un modèle serait à refaire à chaque ré-entraînement : celui-ci pilote l'env par politique aléatoire MASQUÉE et ensemencée, donc il porte sur le MOTEUR et survit aux changements de policy et d'observation.

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
