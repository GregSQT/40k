# Recherche guidée par la policy (MCTS) — agent, distillation, champion

> **Fichier** : `Documentation/Chantiers/backlog/mcts.md`. **Statut** : spécification
> d'implémentation, écrite le 2026-09-08 sur MESURES du dépôt (§1), en réponse à la question
> « quel usage de MCTS est optimal, et quelle méthode d'entraînement ». Elle **remplace**
> `mcts_adversaire.md` (spec d'avril 2026, antérieure à V11, au pipeline squad, au pool et au
> curriculum — conservée avec bandeau pour l'historique ; §2 dit point par point pourquoi elle
> n'est pas retenue).
>
> **Place dans la roadmap** : suspendu jusqu'à la fin du curriculum P0→P10 et de la mesure de
> référence J3 (`ROADMAP_INDEX.md`, ligne « MCTS à l'inférence §10.7 »). Rien ici ne s'ouvre
> avant. Le chantier s'ouvre par une ligne dans `ROADMAP_INDEX.md`, puis S0 (§5).
>
> **Contrat de lecture pour l'agent implémenteur** : les chiffres du §1 sont des mesures du
> 2026-09-08 sur `x1_debug` ; ils se REFONT au début de S0 (§5.1) et le document se corrige si
> l'ordre de grandeur a bougé. Les noms de symboles cités sont ceux du code au 2026-09-08 ; un
> symbole disparu se cherche par son rôle, il ne s'invente pas.

---

## 0. Verdict en trois réponses

**1. Usage optimal : UN seul module de recherche, guidé par le réseau existant, en trois sièges.**
La recherche prend ses **priors** dans la policy MaskablePPO et sa **valeur de feuille** dans la
tête de valeur du même réseau ; elle joue les **deux camps** avec ce réseau, **tire les dés**
comme le moteur les tire, et cherche dans l'**espace d'action micro réel** (le masque). Aucun
espace macro, aucun `GameAdapter`, aucun état abstrait, aucun rollout de bot jusqu'au terminal :
tout cela est ce que `mcts_adversaire.md` proposait, et le §2 montre par la mesure que chacun de
ces choix est soit impossible au coût mesuré, soit inférieur à ce que le réseau fournit déjà.
Les trois sièges, dans l'ordre où ils rapportent de l'information par unité de coût :

| Siège | Ce qu'il apporte | Coût | Étape |
|---|---|---|---|
| **A. Inférence de l'agent** (démo PvE + évaluation) | corrige le coup absurde ponctuel **sans retraining** ; c'est aussi LA mesure qui dit si la tête de valeur porte une recherche | latence par décision (§1.3) ; zéro entraînement | S1 |
| **B. Distillation dans l'agent** (Expert Iteration, terme auxiliaire dans PPO) | l'agent devient meilleur **sans recherche à l'inférence** — ce que la démo exige, la latence en moins | +~30 % de temps de collecte à `fraction` 0,02 (§5.3) | S2 |
| **C. Champion + recherche dans le pool** (« MCTS pour le champion ») | un adversaire qui **re-planifie**, non exploitable par motif ; son modèle de l'agent est **exact** (les poids gelés du learner sont dans le worker) | ×10 par épisode de pool avec recherche (§5.4) | S3, optionnel |

**2. Méthode d'entraînement optimale : Expert Iteration en terme auxiliaire, pas AlphaZero, pas
« MCTS adversaire ».** AlphaZero (recherche à CHAQUE décision de collecte) multiplie le coût de
collecte par le budget de simulations : à 57 ms le pas moteur et 125 décisions par épisode
(§1), c'est ×16 à ×50 sur un curriculum déjà à ~200 h — hors de portée sur cette machine. Un
MCTS adversaire à rollouts de bots (l'ancien doc) coûte ~14 s par rollout jusqu'au terminal
(§2). La distillation (B) garde PPO **on-policy intact** — l'action jouée reste tirée de
π_θ — et n'ajoute qu'une cible supervisée π′ (la policy améliorée par la recherche) sur une
fraction des états ; c'est la seule forme qui convertit la force de la recherche en force du
réseau à un coût borné et mesurable.

**3. Ce qui décide de tout : une mesure, pas un choix.** Une recherche ne vaut que ce que vaut
la tête de valeur. **S1** mesure sur HOLDOUT le même checkpoint avec et sans recherche, mêmes
graines. Si le gain est sous le seuil G1 (§5.2), il n'y a **rien à distiller** et **rien à mettre
dans le pool** : le chantier se ferme sur S1 et la piste redevient « améliorer le critic ou le
coût du pas moteur », pas « plus de simulations ». C'est la raison de l'ordre A → B → C.

---

## 1. Ce que le code est aujourd'hui — mesures du 2026-09-08

Machine : 16 threads CPU, 39 Go RAM, RTX 4060 Laptop 8 Go, WSL2. Harnais de mesure :
`build_armageddon_engine` (`tests/unit/engine/_config_helpers.py`), scénario
`ACTIVE_DEPLOYMENT_SCENARIO`, profil `x1_debug`, 10 unités / 46 figurines, 120 pas moteur joués
à actions légales aléatoires (les deux camps), checkpoint
`ai/models/ArmageddonAgent_x1/ArmageddonAgent_x1_12345_robust_0.8689.zip` (3 192 553
paramètres, `PointerMaskablePolicy`). Scripts jetables, non conservés.

### 1.1 Coût des primitives

| Primitive | Mesure | Conséquence |
|---|---|---|
| `W40KEngine.step` (action légale aléatoire, obs comprise) | **médiane 57 ms**, p90 232 ms, max 446 ms | le pas moteur domine tout budget de simulation |
| `copy.deepcopy(game_state)` (187 clés) | **745 ms** | inutilisable tel quel |
| `capture_live_state` / `apply_live_state` (`services/game_snapshots.py`, clés statiques exclues) | **1 075 ms / 722 ms** | le rewind PvP n'est pas un clone de recherche |
| masque + observation (`get_squad_action_mask_and_eligible_units` + `_build_observation`) | 4,9 ms ; 28 tenseurs, 26 007 flottants | négligeable |
| forward CPU policy + valeur, batch 1 (1 thread) | **8,7 ms** ; 4 threads : 8,8 ms | un forward par nœud est abordable ; le multithread n'apporte rien à batch 1 |
| forward CPU batch 32 (4 threads) | 26,7 ms | évaluer les feuilles par lot divise le coût par ~10 |

### 1.2 Pourquoi le clone coûte 745 ms — profil par clé

Le `game_state` pèse 4,8 Mo picklés. Le temps de copie est dominé par des **caches dérivés**,
recalculables, et par des clés **statiques** déjà identifiées par `_GS_STATIC_KEYS`
(`services/game_snapshots.py`) :

| ms | Ko | clé | nature |
|---:|---:|---|---|
| 369 | 701 | `_deployment_scoring_cache` | cache dérivé |
| 269 | 676 | `weapon_damage_table` | statique |
| 180 | 243 | `_socle_wall_blocked_cache` | cache dérivé |
| 164 | 435 | `_move_spatial_cache` | cache dérivé |
| 151 | 264 | `config` | statique |
| 132 | 202 | `_objective_hex_zones_cache` | cache dérivé |
| 110 | 204 | `deployment_pools` | statique |
| 106 | 204 | `_deploy_pool_set_cache` | statique |
| 78 | 139 | `terrain_areas` | statique |
| 77 | 163 | `_obscuring_hex_to_area_cache` | cache dérivé |
| 68 | 93 | `_obscuring_area_sets_cache` | cache dérivé |
| 38 | 75 | `_squad_move_pool_cache` | cache dérivé |
| 16 | 22 | `units_cache` | **état de jeu** |

Sans les six clés les plus lourdes ni les statiques, il reste **205 ms pour 165 clés** — donc
d'autres caches encore (`enemy_adjacent_*` à ~20 ms chacune, etc.). L'état de jeu proprement dit
(unités, figurines, phase, objectifs, VP, décisions en attente) est **petit** : le clone rapide
(S0) est un tri des 187 clés en trois natures, pas une optimisation de `deepcopy`.
Vérifié après restore : masque identique à l'original (`np.array_equal` vrai).

### 1.3 Branchement réel et forme du prior

| Phase | décisions sur 120 pas | actions légales (médiane / max) |
|---|---:|---|
| deployment | 10 | 8 / 8 |
| command | 21 | 16 / 16 |
| move | 53 | **5** / 478 |
| shoot | 36 | 3 / 5 |

Le branchement effectif est **petit** hors move ; en move il monte à quelques centaines
(cellules de la grille 32×32). Le prior du checkpoint mesuré est **très piqué** : sur un état à
5 actions légales, top-1 = 0,996, 95 % de la masse sur **1** action. Conséquence pour la
recherche : sans bruit ni température à la racine, elle n'explore rien ; avec un tirage Gumbel
sur les logits (§3.2), les candidats hors argmax reçoivent bien des simulations.

### 1.4 Signal/bruit d'une recherche à un coup — la mesure qui borne le gain

Mesure du 2026-09-08, même harnais : sur des états de décision du joueur contrôlé, les 5
meilleurs candidats du prior sont chacun joués **4 fois avec des jeux de dés différents mais
communs à tous les candidats**, et notés Q = r_norm + γ·V(s′). `signal` = écart-type des Q
moyens **entre** candidats ; `bruit` = écart-type **intra**-candidat dû aux dés. Un moteur neuf
par état, avec contrôle de fidélité du restore (masque et V racine identiques, sinon l'état est
rejeté — 1 rejet sur 7).

| Phase | n | signal (médiane) | bruit (médiane) | argmax(V) ≠ argmax(prior) |
|---|---:|---:|---:|---|
| deployment | 5 | 0,54 – 0,68 | **0,000** | **5/5** |
| move | 3 | 0,42 | 0,012 | 2/3 (dont 1 égalité stricte) |
| shoot | 3 | 0,17 | **0,000** | 3/3 |

Trois conclusions, et elles pèsent plus que le reste du document :

1. **À un coup d'avance, le bruit de dés est négligeable** (0 à 0,016 contre un signal de 0,17 à
   0,68, soit un rapport de 16 à ∞). La stochasticité du jeu n'entre pas à cette profondeur :
   une ou deux répétitions par candidat suffisent, le budget va aux candidats, pas aux répétitions.
   ⚠️ Cela ne vaut QUE pour la profondeur 1 : chaque pas supplémentaire ramène des dés, et le
   `K` de répétitions devra être remesuré si v2 s'ouvre.
2. **La tête de valeur discrimine** : elle n'est pas plate sur les candidats, dans les trois phases.
   C'est la condition NÉCESSAIRE pour qu'une recherche apporte quelque chose. Elle n'est pas
   suffisante : rien ici ne prouve que son classement est meilleur que celui de la policy.
3. **Le désaccord est massif, pas marginal** : dans 10 des 11 états, la valeur classe en tête un
   autre candidat que la policy. Le déploiement est le cas extrême — prior saturé à 1,000, aucun
   dé, signal maximal, désaccord systématique — et c'est donc là qu'il faut tester en premier.

**Ce que cela implique pour le réglage.** Avec un prior aussi piqué (top-1 0,98–1,00) et
`c_visit` 50, σ(q̂) domine les logits : la recherche suivra le classement de la valeur presque
partout. À profondeur 1, elle **est** un « argmax de Q à un coup sur les k meilleurs candidats
du prior », le prior ne servant qu'à choisir les candidats. C'est défendable et c'est bon marché,
mais il faut le dire : le gain attendu est celui d'un regard à un coup d'avance, pas celui d'une
recherche profonde, et il est **entièrement gouverné par la calibration du critic**
(`explained_variance`, 0,85 au dernier relevé de lignée).

**Échantillon** : 11 états, un scénario, un checkpoint intermédiaire
(`robust_0.8689`, pas le champion final). À refaire sur le champion de P10 en tête de S1.

### 1.5 Faits de structure dont la conception dépend

- **Le moteur est un `gym.Env` à deux sièges** : `W40KEngine.step` applique l'action du joueur
  dont c'est la décision, quel qu'il soit. C'est `BotControlledEnv._play_bot_until_control_returns`
  (`ai/env_wrappers.py`) qui enchaîne les pas de l'adversaire jusqu'au retour de la main, en
  décidant à chaque pas qui décide (`MaskDecision`, `engine_is_paused_on_player_choice`). Un
  simulateur de recherche **réutilise cette boucle**, il ne la réécrit pas.
- **L'observation mute l'état** : `_build_observation` joue la frontière 14.02, le journal VP et
  `advance_phase` sur pool vide (docstring de `_build_observation_and_mask`). Sur un clone c'est
  sans conséquence ; sur l'état réel c'est interdit — d'où l'exigence « aucune lecture de
  l'état réel pendant la recherche » (§3.4).
- **La récompense est du point de vue de `config["controlled_player"]`**
  (`engine/reward_calculator.py`, `W40KEngine._calculate_reward`) — y compris pendant les pas de
  l'adversaire, que le wrapper crédite à l'agent (`cumulative_reward += bot_reward_before`).
  Un moteur de scratch qui cherche pour le siège 2 doit porter un `config` dont
  `controlled_player` vaut 2.
- **Les dés sont le RNG global du module `random`** : 20 sites dans 7 fichiers
  (`engine/combat_utils.py`, `engine/phase_handlers/shared_utils.py`, `charge_handlers.py`,
  `fight_handlers.py`, `movement_handlers.py`, `engine/w40k_core.py`, `engine/game_state.py`) ;
  un seul site injecte déjà `roll_d6=lambda: random.randint(1, 6)`. Le levier de la recherche est
  donc `random.getstate()/setstate()` + `random.seed(...)` autour de chaque simulation (§3.4),
  pas une injection de RNG sur 20 sites.
- **Le masque n'est pas pur** : `get_squad_action_mask_and_eligible_units` tire le jet
  d'Advance au premier appel d'une activation et mémoïse la carte de cellules (docstring de
  `BotControlledEnv._opponent_action_mask`). Un clone doit emporter ces mémoïsations OU les
  purger et recalculer — jamais les deux à moitié. `engine/mask_verification.py`
  (`_recompute_supplied_mask`) fait déjà un `deepcopy` complet pour cette raison : il devient
  un consommateur du clone rapide (jumeau T2).
- **Les workers portent une copie CPU de la policy courante** : Phase 3 de `perf_entrainement`,
  `_run_worker_trajectory` (`ai/maskable_subproc_vec_env.py`) déroule `n_steps` pas avec des
  poids gelés (`policy_bytes`) et un instantané VecNormalize, et **normalise les récompenses**
  comme SB3. La recherche côté learner (S2) et le modèle de l'adversaire côté champion (S3)
  trouvent donc dans le worker, sans plomberie nouvelle, les poids qu'il leur faut.
- **L'adversaire de pool joue dans le worker sur CPU** : `_reload_self_play_snapshot_if_needed`
  charge UNE archive par processus (`MaskablePPO.load(device="cpu")`), et
  `_get_self_play_opponent_action` l'appelle avec `deterministic=False`. C'est le point d'accroche
  du siège C.
- **Le réseau expose ce que la recherche consomme** : `PointerMaskablePolicy.get_distribution`
  (logits masqués) et `predict_values` (`ai/pointer_policy.py`). Les valeurs sont apprises sur
  des **récompenses normalisées** (`vec_normalize.norm_reward: true`, `gamma` 0,99, clip 10) :
  toute somme « récompense + γ·V » dans l'arbre normalise la récompense avec les MÊMES
  statistiques (`ret_rms` du `.pkl` VecNormalize), sinon elle additionne deux échelles.
- **Un 1-ply par valeur existe déjà** : `PvEController.select_rule_choice_with_policy`
  (`engine/pve_controller.py`) simule chaque option d'un choix de règle et prend le
  `predict_values` maximal. C'est le siège A à profondeur 0 sur un cas particulier ; S1
  l'absorbe (§5.2) au lieu d'en faire un second chemin.
- **Chemins d'évaluation** : `evaluate_against_bots` / `_eval_worker_task`
  (`ai/bot_evaluation.py`, boucle `_worker_model.predict(...)`), `evaluate_against_checkpoints`
  (pool, sondes `PoolEarlyStoppingCallback._probe`), gate `evaluate_stage_gate`
  (`ai/curriculum.py`). L'A/B de S1 s'y branche, il n'invente pas d'évaluateur.
- **Ordre de grandeur d'un épisode** : ~125 décisions de l'agent (≈200 pas/s global à 24 envs,
  ~96 épisodes/min, `perf_entrainement.md`), soit ~15 s par épisode et par env. Tout surcoût
  de recherche se lit contre ce chiffre.
- **Résolution x5** : pas moteur 3,4× plus lent qu'en x1 (`entrainement.md`, section
  performance). Tous les budgets ci-dessous sont des chiffres x1 ; en x5 ils se divisent d'autant.

---

## 2. Pourquoi `mcts_adversaire.md` n'est pas retenu

Ce qui en reste vrai et est repris ici : le moteur est la seule source de vérité des règles ;
aucun fallback silencieux (budget dépassé, config incomplète) ; validation par A/B à budget de
pas équivalent ; le winrate contre l'adversaire de recherche n'est jamais le critère. Le reste :

| Choix de l'ancien doc | Ce que la mesure dit | Décision |
|---|---|---|
| Rollouts jusqu'au terminal joués par des bots (§9) | ~250 pas moteur par partie × 57 ms ≈ **14 s par rollout** ; 128 simulations = 30 min par décision | **rejeté** ; la feuille est la tête de valeur, un forward de 9 ms |
| Espace **macro** `macro_action_set`, points de décision « début de tour », politique auxiliaire (§5, §10) | aucun registre macro n'existe ; le moteur ne commite que des actions micro ; le branchement micro réel est **petit** (§1.3) et le prior le réduit encore | **rejeté** ; recherche dans le masque réel, candidats par prior |
| `GameAdapter` + « état abstrait » optionnel (§6, §7) | `W40KEngine` EST l'adaptateur (`step`, masque, obs) ; l'abstraction crée le « reality gap » que le doc lui-même redoute | **rejeté** ; un clone rapide du vrai état (S0) |
| « Modèle du joueur PPO dans les rollouts » posé comme problème ouvert (§9.3) | dans le worker les poids gelés du learner sont disponibles (`policy_bytes`) : le modèle de l'adversaire est **exact** par construction | **résolu** par le siège C |
| MCTS = adversaire **indépendant**, hors policy, pour la « diversité » (§2.1 O1) | la diversité d'adversaires est déjà portée par le pool (champion, anciens, exploiteurs E1–E3) ; la recherche n'apporte quelque chose que si elle est **plus forte** que le réseau, ce que seule S1 mesure | **réordonné** : A/B d'abord, pool en dernier |
| Config `opponent_mix` avec `snapshot_model_path`, `self_play_ratio_*` (§10.2) | schéma remplacé le 2026-08-22 par `pool` pondéré par environnement (`bot.md#league`) | **périmé** |
| UCT pur, C=√2, `max_visits` (§8) | à 8–32 simulations par décision et un prior piqué à 0,996, UCT explore soit rien soit au hasard ; le régime petit budget est celui de Gumbel + Sequential Halving (§3.2) | **remplacé** |

---

## 3. Conception retenue

### 3.1 Principe

La recherche est un **opérateur d'amélioration de policy** posé sur le réseau existant :

- **Priors** : logits masqués de `PointerMaskablePolicy.get_distribution` sur l'observation
  canonique de la décision (la même que PPO consomme).
- **Valeur de feuille** : `predict_values` sur l'observation du joueur racine à sa prochaine
  décision. Échelle : retour actualisé **normalisé** (voir §1.4). Pas de rollout.
- **Les deux camps jouent avec un réseau** : le joueur racine par la recherche, l'adversaire par
  `predict(deterministic=False)` d'un modèle d'adversaire désigné en config (§3.5
  `opponent_model`). Les phases sans décision (jets, transitions) sont jouées par le moteur.
- **Dés** : à chaque simulation le moteur tire ses dés normalement, sous une graine dérivée ;
  l'arbre est **à boucle ouverte** (un nœud = une suite d'actions du joueur racine, pas un état),
  et la répétition des simulations d'un même candidat moyenne les dés. Aucun nœud de hasard
  explicite, aucun état déterminisé.
- **Horizon** : une simulation s'arrête à la **prochaine décision du joueur racine** (profondeur
  1, v1) ou après `max_depth_root_decisions` décisions racine (v2), ou au terminal, ou au plafond
  `max_engine_steps_per_simulation` (§3.3).
- **Perspective unique** : toute valeur est celle du joueur racine, c'est-à-dire du
  `controlled_player` du moteur de scratch. L'adversaire n'a pas de nœud de décision dans
  l'arbre : il fait partie de l'environnement simulé, exactement comme dans l'env PPO.

### 3.2 Algorithme — Gumbel + Sequential Halving (racine), sélection déterministe (intérieur)

Référence : Danihelka et al., « Policy improvement by planning with Gumbel », ICLR 2022. C'est
l'algorithme du **petit budget** : il garantit une policy améliorée dès quelques simulations et
fournit directement la cible de distillation (S2). Notation : ℓ(a) logits masqués à la racine,
N(a) visites, q̂(a) moyenne des retours simulés de a, v_racine = V(obs racine).

1. **Candidats** : tirer g(a) ~ Gumbel(0) i.i.d. sur les actions légales ; garder les
   `root_candidates` = m meilleurs par g(a) + ℓ(a) (m ≤ nombre d'actions légales ; si moins
   d'actions légales que m, tous). Une seule action légale → la jouer sans simulation, le
   compter dans `search/trivial_share`.
2. **Sequential Halving** avec budget `n_simulations` = n : ⌈log₂ m⌉ phases ; à chaque phase,
   chaque candidat survivant reçoit ⌊n / (⌈log₂ m⌉ · |survivants|)⌋ simulations (≥ 1, sinon
   erreur de config) ; on garde la moitié supérieure par g(a) + ℓ(a) + σ(q̂(a)).
3. **σ(q̂) = (c_visit + max_b N(b)) · c_scale · q̃(a)**, avec q̃ = q̂ ramené dans [0, 1] par
   min–max sur les candidats visités (écart nul → 0). Défauts du papier : `c_visit` 50,
   `c_scale` 1,0.
4. **Action jouée** : argmax sur les survivants finaux de g(a) + ℓ(a) + σ(q̂(a)).
5. **Policy améliorée** (cible S2, publiée sur TOUT le masque) :
   π′(a) = softmax_a( ℓ(a) + σ(Q̄(a)) ), où Q̄(a) = q̂(a) si a visité, sinon v_mix =
   (v_racine + ΣN · Σ_{visités} π(a) q̂(a) / Σ_{visités} π(a)) / (1 + ΣN).
6. **Simulation d'un candidat a (profondeur 1)** : restaurer le clone racine → `step(a)` →
   jouer l'adversaire et les transitions jusqu'à la prochaine décision racine (§3.3) → retour
   G = Σ r_norm (récompenses du `controlled_player`, normalisées par `ret_rms`, sur TOUS les pas
   traversés) + γ · V(obs racine à l'arrivée) ; terminal → G = Σ r_norm. Chaque nouvelle
   simulation de a ajoute G à q̂(a).
7. **v2, profondeur > 1** : en dessous de la racine, sélection déterministe
   argmax_a [ π′_nœud(a) − N(a) / (1 + ΣN) ] (papier, §5), même cible π′ par nœud, mêmes q̃ par
   min–max de l'arbre entier. v2 ne s'ouvre qu'après S1, et seulement si S1 montre un gain à
   profondeur 1 : approfondir multiplie le coût par le nombre de pas traversés, il faut d'abord
   savoir que la valeur porte.

Les feuilles d'une même phase de Sequential Halving sont indépendantes : leurs forwards se font
**par lot** (§1.1, batch 32 en 27 ms). Les `step` restent séquentiels.

### 3.3 Fin de simulation et plafond de pas

Une simulation traverse, après l'action racine : les activations restantes du joueur racine
dans la phase (aucune, la main lui revient aussitôt) — cas **intra-phase**, 1 pas moteur ; ou
la phase / le tour de l'adversaire — cas **fin de phase**, jusqu'à ~25 pas moteur et autant de
forwards adverses. Le second cas coûte ~1,5 s par simulation à 57 ms le pas : c'est le poste
qui borne la latence, et S1 le **mesure par classe** (`search/latency_ms_intra`,
`search/latency_ms_end_of_phase`).

Règle v1, **explicite et publiée** : `max_engine_steps_per_simulation` borne la simulation ;
si le plafond tombe pendant le tour adverse, le retour est Σ r_norm accumulé + γ · V(dernière
observation du joueur racine sur le chemin), et la simulation est comptée dans
`search/truncated_share`. Si `truncated_share` dépasse 0,2 sur une évaluation S1, le plafond
est faux, pas la recherche : le remonter et remesurer. Une observation « du point de vue du
joueur racine pendant le tour adverse » n'existe pas dans le moteur (l'obs est égocentrique à
l'escouade active du joueur courant) ; en écrire une est un chantier moteur distinct, à ouvrir
seulement si S1 prouve que la troncature coûte des points.

### 3.4 Clone d'état et isolement — contrat S0

Un **moteur de scratch** par processus (worker, évaluateur, API) : un `W40KEngine` construit avec
la même config, le même scénario et le même `rewards_config` que le moteur réel, dont le
`config` est une copie superficielle avec `controlled_player` = siège racine.

Deux primitives, dans `engine/state_clone.py` :

- `capture_search_state(engine) -> SearchSnapshot` : copie profonde des SEULES clés « état de
  jeu » ; les clés « cache dérivé » sont **purgées** au restore (recalculées à la demande par
  leurs producteurs, comme après un reset) ; les clés « statiques » sont partagées par
  référence. La classification des 187 clés est une **table nommée dans le module**, avec une
  quatrième colonne « inconnue » qui doit être **vide** : une clé de `game_state` absente de la
  table fait lever `capture_search_state` (T1 — une clé nouvelle se classe, elle ne se devine
  pas). Les attributs d'engine mutables (drapeaux d'init de phase, compteurs) suivent la règle de
  `_ENGINE_PLAIN_TYPES` / `_ENGINE_STATIC_ATTRS` de `services/game_snapshots.py`.
- `restore_search_state(scratch_engine, snapshot)` : idempotente ; deux restores successifs
  donnent le même masque et la même observation.

**Jumeaux T2 de S0** : `services/game_snapshots.py` (`_GS_STATIC_KEYS`, `capture_live_state`,
`apply_live_state`) et `engine/mask_verification.py` (`_recompute_supplied_mask`,
`_recompute_move_cell_map`) doivent consommer la même table — deux listes de clés statiques
divergeraient en silence. Le rewind PvP garde sa sémantique (il capture aussi les caches sûrs
qu'il déclare) mais lit la classification au même endroit.

**Isolement RNG** : autour de chaque simulation, `state = random.getstate()` ;
`random.seed(seed_simulation)` avec `seed_simulation = hash(search_seed, index_candidat,
index_simulation)` ; `random.setstate(state)` en `finally`. Le flux de dés de la partie réelle
est ainsi intact — les gates du curriculum et `--test-only` sont graînés, la recherche ne doit
pas les déplacer. `search_seed` dérive de la graine d'épisode et du numéro de décision
(`seed_mode: "derived"`), ou est fixe (`"fixed"`, tests).

**Mesure de sortie S0** (à écrire dans ce document) : coût de `capture` + `restore` sur l'état
de §1, objectif **≤ 30 ms** ; masque et observation identiques à l'original après restore ;
empreinte mémoire d'un moteur de scratch par worker (24 workers — `perf_entrainement.md` a
refusé `n_envs` 32 pour la RAM, le scratch ne doit pas la reprendre) ; aucune mutation du
moteur réel pendant 100 simulations (empreinte `scenario_fingerprint`-like sur `game_state`
avant/après).

### 3.5 Interface et arborescence `ai/search/`

```
ai/search/
├── __init__.py
├── config.py        # SearchConfig : lecture require_key, validation, AUCUN défaut
├── decider.py       # SearchDecider(engine, model, normalizer, opponent_model, config).decide(decision) -> SearchResult
├── simulator.py     # moteur de scratch, restore, « jouer jusqu'à la prochaine décision racine »
├── gumbel.py        # candidats, Sequential Halving, σ, π′, v_mix — pur, testable sans moteur
└── metrics.py       # agrégats latence / simulations / troncature / désaccord, publiés en search/*
engine/state_clone.py   # S0 (§3.4)
```

`SearchDecider.decide(decision: MaskDecision) -> SearchResult(action: int, improved_policy:
np.ndarray[TOTAL_ACTION_SIZE], root_value: float, stats: dict)`. `decision` est le couple
masque / pool **déjà servi** pour cet état (jamais reconstruit : §1.4, masque non pur). Le
décideur ne lit l'état réel qu'une fois, à la capture ; tout le reste se passe sur le scratch.

Le `simulator` réutilise `BotControlledEnv._play_bot_until_control_returns` par **extraction**
d'une fonction de module « jouer l'adversaire jusqu'au retour de la main » paramétrée par la
fonction d'action adverse — le wrapper et le simulateur l'appellent tous deux. Une seconde
boucle divergerait sur la prochaine règle (décision en attente, déploiement `auto`).

Le modèle d'adversaire est un objet à `predict(obs, deterministic, action_masks)` — le même type
que `_NormalizedFrozenModel` (`ai/vec_normalize_utils.py`) : le réseau lui-même (siège A), les
poids gelés du learner (siège C), ou la policy chargée dans l'API (démo).

### 3.6 Points d'accroche par siège

| Siège | Site | Ce qui change |
|---|---|---|
| A — démo | `PvEController.make_ai_decision` (`engine/pve_controller.py`) | si `inference.search.enabled`, la décision passe par `SearchDecider` ; `select_rule_choice_with_policy` et `_evaluate_rule_choice_option_value` sont **supprimés** : un choix de règle est une décision `CHOICE_i` du masque, la recherche la couvre |
| A — évaluation | `_eval_worker_task` (`ai/bot_evaluation.py`), boucle `_worker_model.predict` ; `evaluate_against_checkpoints` | option `search` du worker ; `--search` sur `--test-only` ; les métriques `search/*` remontent avec le résultat |
| B — collecte | `_run_worker_trajectory` (`ai/maskable_subproc_vec_env.py`) | pour une fraction `distill.fraction` des décisions du learner, `SearchDecider` avec `frozen_policy` comme prior et modèle adverse ; `info["search_policy"]` = π′ ; l'action jouée reste tirée de π_θ |
| B — buffer | `ai/gpu_rollout_buffer.py` | champs `search_policy` (float32 [n, A], RAM comme les obs) et `has_search_policy` (bool) ; upload par mini-lot |
| B — loss | `PatchedMaskablePPO.train` (`ai/patched_ppo.py`) | terme `distill.coef · mean_{has}( −Σ_a π′(a) log π_θ(a\|s) )` ; entre dans la décomposition de norme de gradient `_diag_grad_norms_mb0` (instrument permanent, jumeau T2) ; publié `train/distill_loss`, `train/distill_kl` |
| C — pool | `BotControlledEnv._get_self_play_opponent_action` ; `assign_pool_members_to_envs`, `stage_pool_members` (`ai/curriculum.py`) | membre de pool `kind: "champion_search"` ; le worker reçoit les poids gelés du learner comme `opponent_model` (ils sont déjà dans `_run_worker_trajectory`) |

### 3.7 Configuration — clés exactes, `require_key`, aucun défaut

Bloc `search` d'un **profil d'entraînement** (`config/agents/<Agent>/<Agent>_training_config.json`),
hérité par `extends` comme le reste :

```json
"search": {
  "enabled": false,
  "root_candidates": 8,
  "n_simulations": 16,
  "max_depth_root_decisions": 1,
  "max_engine_steps_per_simulation": 40,
  "c_visit": 50.0,
  "c_scale": 1.0,
  "opponent_model": "self",
  "seed_mode": "derived",
  "time_budget_ms": null,
  "min_completed_simulations": 8,
  "distill": { "enabled": false, "fraction": 0.02, "coef": 0.5 }
}
```

- `enabled: false` = comportement actuel, toutes les autres clés **quand même exigées** (T1 :
  un bloc absent lève, un bloc présent se valide entier, pour que l'activation ne découvre pas
  une clé manquante à la première décision).
- `opponent_model` : `"self"` (le réseau qui cherche) ou `"learner"` (siège C, poids gelés du
  learner du worker) ; toute autre valeur lève.
- `time_budget_ms` : `null` en entraînement et en évaluation (le budget est `n_simulations`,
  la mesure doit être comparable) ; un entier en démo. Budget temps atteint avec moins de
  `min_completed_simulations` simulations → **erreur explicite**, jamais « première action
  légale ». Atteint après → l'action est prise sur les simulations faites et le cas est compté
  dans `search/time_budget_hits`.
- `distill.fraction` ∈ [0, 1] ; `distill.coef` ≥ 0 ; `distill.enabled: true` exige
  `enabled: true`.
- Démo : bloc `inference.search` de même schéma sans `distill`, chargé par
  `services/api_server.py` via le loader, avec `time_budget_ms` obligatoire non nul.
- Curriculum : `kind: "champion_search"` accepté par `stage_pool_members` avec la même forme
  qu'un `champion` ; une étape qui l'utilise doit tourner sur un profil dont `search.enabled`
  est vrai, sinon refus au chargement (`validate_curriculum`). Une étape de distillation est un
  `learner` sur un profil `x1_lineage_distill` (`extends: x1_lineage`, `search.enabled` et
  `distill.enabled` vrais) ; le contrôle « profil conforme à la nature de l'étape »
  (`_validate_training_configs`) accepte un profil qui **étend** celui de la nature.

---

## 4. Métriques et protocole de mesure

### 4.1 Métriques `search/*` (TensorBoard en entraînement, JSON de résultat en évaluation)

| Tag | Sens |
|---|---|
| `search/latency_ms_p50`, `_p95`, `_intra`, `_end_of_phase` | par décision, par classe (§3.3) |
| `search/simulations_per_decision` | budget effectif (< n si trivial ou budget temps) |
| `search/truncated_share` | part des simulations arrêtées par le plafond de pas |
| `search/trivial_share` | décisions à une seule action légale |
| `search/argmax_disagreement` | part des décisions où l'action jouée ≠ argmax du prior — **la** mesure de ce que la recherche change |
| `search/root_value`, `search/q_spread` | V racine ; max − min des q̂ des candidats |
| `search/time_budget_hits` | démo |
| `train/distill_loss`, `train/distill_kl`, part du gradient `distill` | S2 |
| `train/steps_per_second` (existant : `time/fps`) | régression de débit, S2/S3 |

### 4.2 Protocole A/B — la règle unique

Même checkpoint, mêmes scénarios HOLDOUT, **mêmes graines d'épisode** (`_episode_seed` de
`ai/bot_evaluation.py`), deux bras : recherche désactivée / activée. La recherche n'a pas le
droit de déplacer le flux de dés de la partie (§3.4), donc les deux bras jouent les mêmes
premiers coups jusqu'à la première décision où `argmax_disagreement` bascule — c'est ce qui
rend la comparaison appariée. Taille : 900 épisodes par bras (erreur-type ≈ 1,7 point à
p ≈ 0,5, la valeur retenue par le gate de curriculum), sur le panel de bots ET contre le pool
(`evaluate_against_checkpoints`). On lit : combined, pire bot, par siège, `vs_<champion>`,
et la latence par classe. Jamais le winrate contre un adversaire lui-même en recherche comme
critère.

---

## 5. Étapes de livraison

Chaque étape : périmètre fermé (T2), tests rouge→vert, mesure de sortie écrite ICI, et un
critère qui autorise ou interdit la suivante. Les étapes ne se recouvrent pas : S1 ne contient
aucune plomberie de S2.

### 5.1 S0 — Clone rapide et isolement (prérequis, moteur)

**Livrables** : `engine/state_clone.py` (§3.4) ; table de classification des clés ;
`services/game_snapshots.py` et `engine/mask_verification.py` relus sur la table ; fonction
extraite « jouer l'adversaire jusqu'au retour de la main » (§3.5), consommée par
`BotControlledEnv`.

**Tests** (`tests/unit/engine/test_state_clone.py`, `tests/unit/ai/test_play_until_control.py`) :
- clé de `game_state` hors table → lève (rouge en retirant une clé de la table) ;
- capture → mutation du scratch (un `step`) → l'original a la même empreinte qu'avant (rouge en
  partageant une clé d'état par référence) ;
- restore idempotent : masque et obs identiques sur deux restores (rouge en laissant un cache
  mémoïsé survivre au restore) ;
- RNG : 100 simulations sous `getstate/setstate` laissent `random.getstate()` inchangé, et deux
  simulations de même graine donnent le même retour (rouge en retirant le `setstate`) ;
- la fonction extraite reproduit pas pour pas l'ancienne boucle sur un scénario enregistré
  (rouge en changeant l'ordre d'une garde).
**Sortie** : mesures §3.4 écrites dans ce document. **Bloque S1 si** capture + restore > 30 ms
(refaire le tri avant de continuer — pas de recherche à 700 ms le clone).

### 5.2 S1 — Module de recherche + siège A + mesure G1

**Livrables** : `ai/search/*` (§3.5, v1 profondeur 1) ; `--search` sur `--test-only` et sur
`evaluate_against_checkpoints` ; `PvEController` sur le décideur, `select_rule_choice_with_policy`
supprimé ; bloc `search` dans les six profils (`enabled: false`) et `inference.search` ;
métriques §4.1 ; `scripts/pvp_smoke_test.py` joue une partie avec `inference.search.enabled`.

**Tests** :
- `tests/unit/ai/search/test_gumbel.py` : sur un bandit synthétique à retours connus, la
  policy améliorée met plus de masse que le prior sur l'action de meilleure valeur ; Sequential
  Halving distribue exactement n simulations (rouge en cassant la répartition) ; σ à écart nul
  vaut 0 ; v_mix reproduit la formule sur un cas à la main ;
- `tests/unit/ai/search/test_decider.py` (moteur `build_armageddon_engine`) : l'action rendue
  est dans le masque ; l'état réel est intact après `decide` (empreinte) ; `min_completed_simulations`
  non atteint sous budget temps → lève (rouge en repliant sur le prior) ; une seule action
  légale → pas de simulation ;
- `tests/unit/ai/search/test_config.py` : chaque clé manquante lève, `opponent_model` inconnu
  lève, `distill.enabled` sans `enabled` lève ;
- `tests/unit/engine/test_pve_controller_search.py` : un `CHOICE_i` passe par le décideur
  (rouge en rétablissant l'ancien chemin) ;
- `tests/unit/ai/test_bot_evaluation_search.py` : `--search` remonte `search/*` et les deux
  bras à recherche désactivée sont bit-à-bit identiques à l'évaluation actuelle.

**Mesure G1** (§4.2) sur le champion final du curriculum, `n_simulations` 16 et 32,
`root_candidates` 8. **Ordre de test imposé par §1.4** : d'abord la recherche limitée aux
décisions de DÉPLOIEMENT (aucun dé, signal maximal, désaccord systématique, ~10 décisions par
partie donc latence négligeable) ; c'est le cas le plus favorable connu, et un échec là rend
inutile de mesurer les autres phases. **Seuil** : Δcombined ≥ **+4 points** (≈ 2,4 erreurs-types) sans
dégradation du pire bot au-delà de −2 points, à latence p95 intra-phase ≤ 2 s. Trois issues,
toutes écrites ici :
- G1 franchi → S2 s'ouvre ; la démo peut activer `inference.search` avec `time_budget_ms`
  fixé à la latence p95 mesurée.
- G1 non franchi avec `argmax_disagreement` < 0,05 → la recherche ne change rien : refaire G1
  avec `root_candidates` 16 avant de conclure. **Issue jugée improbable** : la mesure §1.4 donne
  un désaccord de 10/11 sur un checkpoint intermédiaire.
- G1 non franchi avec désaccord ≥ 0,05 → la tête de valeur ne porte pas la recherche : **fin du
  chantier**, le levier est ailleurs (critic, coût du pas). S2 et S3 ne s'ouvrent pas.

### 5.3 S2 — Distillation (siège B)

**Livrables** : `info["search_policy"]` dans `_run_worker_trajectory` ; champs du buffer ;
terme de loss et sa part de gradient ; profil `x1_lineage_distill` ; étape de curriculum
`P11` (`learner`, `init: from:P10`, pool de la même FORME que P10 décalé d'un cran — champion
`P10`, anciens `P0`..`P9`, exploiteurs `E1`–`E3`, mêmes poids 0,25 / 0,4 / 0,2) ; règle
« profil étendant la nature » dans `_validate_training_configs`.

**Tests** :
- `tests/unit/ai/test_worker_search_policy.py` : à `fraction` 1,0 chaque pas porte une π′ qui
  somme à 1 sur le masque et vaut 0 hors masque ; à 0,0 aucun ; l'action jouée est tirée de
  π_θ et non de π′ (rouge en jouant l'argmax de π′) ;
- `tests/unit/ai/test_gpu_rollout_buffer_search.py` : les champs traversent `get()` alignés
  sur les obs (rouge en décalant d'un indice) ;
- `tests/unit/ai/test_patched_ppo_distill.py` : `coef` 0 → loss identique à l'actuelle au
  bit près ; `coef` > 0 → le gradient sur les états à cible est non nul et nul ailleurs ; la
  décomposition de norme porte une entrée `distill` (rouge en l'omettant) ;
- `tests/unit/ai/test_curriculum_search.py` : `champion_search` refusé sur un profil sans
  `search.enabled` ; profil étendant la nature accepté, profil étranger refusé.

**Mesure** : P11 contre P10 sur le pool entier (`evaluate_stage_gate`, promotion au gate
existant) ET holdout A/B **sans recherche** à l'inférence — c'est le point : la distillation
doit se lire sur le réseau nu. Débit : `time/fps` de P11 contre P10, attendu ≥ 0,7× à
`fraction` 0,02 ; en dessous, réduire `fraction` avant `n_simulations`.
**Ferme le chantier si** P11 n'est pas promu à `coef` 0,5 puis 1,0 : la recherche améliore
l'inférence mais pas les poids — la démo garde le siège A, S3 ne s'ouvre pas.

### 5.4 S3 — Champion + recherche dans le pool (siège C, optionnel)

Ne s'ouvre que si S1 ET S2 ont franchi leurs seuils, et si le learner dépasse 0,60 contre le
pool entier sur trois sondes (le pool n'apprend plus rien à l'agent). **Livrables** : membre
`champion_search`, `opponent_model: "learner"`, plomberie des poids gelés vers
`BotControlledEnv`. **Mesure** : une étape `P12` avec un membre `champion_search` à poids 0,25 ;
critère = gate existant + `time/fps` ≥ 0,5× P11. Le coût attendu est ×10 par épisode de pool
avec recherche (125 décisions × 16 simulations × ~100 ms intra-phase) : à 25 % du pool et 85 %
de part de pool, ≈ ×3 sur l'étape. Si ce coût n'est pas tenable, S3 se ferme sans dette :
le siège C n'est jamais une condition des sièges A et B.

### 5.5 Le curriculum après la recherche — ce qui change, ce qui ne change pas

**Rien ne se rejoue.** P0→P10 sont acquis ; la recherche n'invalide aucune étape et n'oblige à
aucun `--new`. Le layout d'observation, l'espace d'action et le format des poids sont inchangés
— la recherche ne fait que LIRE le réseau. La chaîne se prolonge :

```
… P9 → P10        (acquis, régime de lignée x1_lineage)
       ↓
      P11   learner, init from:P10, profil x1_lineage_distill   ← S2, distillation
       ↓
      P12   learner, init from:P11, profil x1_lineage_distill   ← S3, pool avec recherche
             pool : champion_search(P11) 0,25 + champion(P11) + anciens + exploiteurs
```

Chaque étape reste **UN run** de `ai/train.py --etape <nom>`, avec le même gate
(`evaluate_stage_gate`, 900 épisodes), les mêmes sondes (`PoolEarlyStoppingCallback`, moyenne
des 3 dernières sur le pool entier), le même verrou de parité et la même promotion. Ajouter
`P11` = deux entrées dans `curriculum.json` (`order` et `stages`) et un profil qui `extends`
`x1_lineage` — pas un second pipeline.

**Ce que P11 change à l'intérieur du run, et rien d'autre.** L'adversité est identique à P10
(mêmes bots à 15 %, même forme de pool). Le seul changement est dans la collecte : pour ~2 %
des décisions de l'agent, le worker calcule en plus la policy améliorée π′ et la joint à la
transition ; la loss porte un terme supervisé de plus. **L'action jouée reste tirée de π_θ** —
donc les épisodes collectés, les récompenses, le pool et les métriques gardent exactement leur
sémantique, et PPO reste on-policy. C'est la règle « un seul levier par run » du chantier panel :
P11 ne bouge que la loss, P12 ne bouge que l'adversaire.

**L'évaluation n'a besoin d'aucun instrument nouveau.** Puisque la recherche ne joue jamais
l'action réelle en S2, les sondes et le gate mesurent déjà le **réseau nu** — c'est-à-dire
précisément ce que la distillation doit améliorer. Un P11 promu par le gate existant EST la
preuve que la recherche est passée dans les poids. Le seul ajout est le A/B holdout de §4.2,
qui sépare le gain dû à la distillation du gain dû au fait de chercher à l'inférence.

**Le verrou de parité reste valide.** P11 part des poids de P10 et son champion EST P10 : à
l'épisode 0 son score contre lui vaut 0,50 par identité, comme pour toute étape de la chaîne.
La recherche ne s'active dans aucune évaluation d'entraînement, donc elle ne peut pas déplacer
cette baseline.

**Coût.** P11 ≈ 1,3× le temps horloge de P10 à `fraction` 0,02 (mesure de sortie S2). P12 ≈ 3×
(§5.4). Aux ~20 h d'une étape de lignée, cela fait une nuit pour P11, trois pour P12 — à
comparer aux ~200 h déjà payées pour P0→P10.

---

## 6. Risques et réponses

| Risque | Réponse |
|---|---|
| La tête de valeur estime V^π normalisé, pas une probabilité de victoire | min–max sur les candidats (§3.2) rend σ insensible à l'échelle ; le seul usage absolu est G = r_norm + γV, cohérent parce que r est normalisé par le même `ret_rms` |
| ~~Prior piqué → recherche inerte~~ — **écarté par la mesure §1.4** : le désaccord est de 10/11 | — |
| **Risque inverse, lui réel : la recherche suit le critic presque aveuglément** (σ domine un prior piqué) | à profondeur 1 elle vaut un argmax de Q à un coup ; si G1 échoue avec un désaccord élevé, c'est le classement du critic qui est en cause, pas le budget — baisser `c_visit` ou fermer le chantier, jamais monter `n_simulations` |
| Fin de phase = simulation à travers le tour adverse | plafond + troncature explicite + `truncated_share` (§3.3) ; latence publiée par classe |
| `_build_observation` mute l'état | tout se joue sur le scratch ; test d'empreinte S0/S1 |
| Dés déplacés dans la partie réelle → gates non comparables | `getstate/setstate` par simulation, test S0 |
| RAM : un moteur de scratch par worker | mesure S0 ; refus documenté de `n_envs` 32 pour la RAM (`perf_entrainement.md`) fait loi |
| Distillation off-policy | l'action jouée reste π_θ ; π′ n'est qu'une cible auxiliaire ; part de gradient publiée, `coef` réglé sur elle comme `vf_coef` l'a été (0,15 sur mesure) |
| x5 | tous les budgets se divisent par 3,4 ; aucun chiffre x5 n'est extrapolé ici, il se mesure |
| Le coût du pas moteur (57 ms) borne tout | ce n'est pas ce chantier : `perf_entrainement.md`, `perf_noyau_natif_et_gzip.md`. Un noyau natif changerait l'ordre de grandeur de la recherche ; ce document ne le suppose pas |

---

## 7. Ce que ce document ne décide pas

- La **date** d'ouverture et sa **place** relative à J4/J5 : `ROADMAP_INDEX.md` seul.
- La **valeur** finale de `coef`, `fraction`, `n_simulations` : mesurées en S1/S2, écrites ici.
- **v2** (profondeur > 1) : spécifiée §3.2 point 7, ouverte seulement sur mesure de S1.
- Une observation « joueur racine pendant le tour adverse » (§3.3) : chantier moteur distinct,
  ouvert seulement si la troncature coûte des points mesurés.

---

## 8. Références

| Document / code | Usage |
|---|---|
| `Documentation/Chantiers/backlog/mcts_adversaire.md` | spec antérieure, remplacée (§2) |
| `Documentation/Chantiers/v11/strategie_evaluation.md` §10.3, §10.7 | progression d'adversaires ; les deux usages du MCTS |
| `Documentation/Roadmap/bot.md#mcts-inference`, `infra.md#mcts` | entrées roadmap |
| `Documentation/Reference/training/entrainement.md`, `observation_et_actions.md` | interface agent, obs Dict, espace d'action 1 389, VecNormalize |
| `Documentation/Chantiers/backlog/perf_entrainement.md` | débit, Phase 3 (workers autonomes), refus `n_envs` 32 |
| `Documentation/Chantiers/backlog/curriculum_adversaires_etalons.md`, `config/agents/ArmageddonAgent_x1/curriculum.json` | pool, gate, sondes, natures d'étape |
| `services/game_snapshots.py`, `engine/mask_verification.py` | clones existants, jumeaux de S0 |
| `ai/env_wrappers.py`, `ai/maskable_subproc_vec_env.py`, `ai/patched_ppo.py`, `ai/gpu_rollout_buffer.py`, `ai/bot_evaluation.py`, `ai/curriculum.py`, `engine/pve_controller.py`, `ai/pointer_policy.py` | points d'accroche (§3.6) |
| Danihelka, Guez, Schrittwieser, Silver — *Policy improvement by planning with Gumbel*, ICLR 2022 | algorithme §3.2 |
| Anthony, Tian, Barber — *Thinking Fast and Slow with Deep Learning and Tree Search*, NeurIPS 2017 | Expert Iteration, siège B |
