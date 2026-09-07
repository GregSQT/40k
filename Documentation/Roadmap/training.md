# Training — Tâches ouvertes

---

## 🔴 Régime de lignée — option A livrée, P2 à relancer depuis P1 {#regime-lignee-2026-09-07}

**Livré le 2026-09-07. Ce qui reste à faire : lancer P2.** Trois runs P2 successifs ont échoué en
faisant varier des hyperparamètres étape par étape ; l'option A supprime cette possibilité au lieu
de chercher les bonnes valeurs pour chaque étape.

**1. Un bloc `lineage_regime` en tête de `curriculum.json`, sept clés, appliqué à TOUTE étape
`init: "from:"`** — les dix learners comme les trois exploiteurs. `learning_rate` 0.001 et
`ent_coef` 0.03 **scalaires**, `n_steps` 32640, `batch_size` 4080, `vf_coef` 0.15,
`max_grad_norm` 0.5, `agent_seat_p2_ratio` 0.6. Les vingt rampes `decay_fraction` des étapes
disparaissent, ainsi que les surcharges de `vf_coef` / `max_grad_norm` de P2 et P3 ; une étape
reprise ne déclare plus que `total_episodes`, et le validateur refuse le reste. Le profil
`x1_long` garde ses rampes et son `vf_coef` 0.5 pour le seul départ à froid P0. Détail chiffré et
mesures : `Documentation/Reference/training/entrainement.md`, section « Rampes ».

**2. `P00` supprimée, `P0` passe en `init: "new"`, E1/E2/E3 passent en `init: "from:P0"`.** La
graine n'existait que pour éviter de repayer un warmup à chaque learner, ce que le chaînage a rendu
sans objet. Les exploiteurs ne partent plus des poids de leur cible : ils en étaient une copie à
qui l'on demandait de trouver sa propre faiblesse, donc ils commençaient à la parité par
construction et ne pouvaient s'en écarter qu'en désapprenant.

**3. Contrôle de continuité à l'ouverture.** `_pin_entropy_ramp_for_warm_start` est supprimé avec
les rampes qu'il corrigeait ; à sa place, `announce_lineage_continuity` lit `ent_coef` et
`learning_rate` dans le zip repris et annonce tout écart avec le bloc. Il n'en corrige aucun.

**4. Verrou de parité, qui ARRÊTE le run.** À l'épisode 0 d'une étape reprise, le modèle **est**
l'archive dont il reprend les poids : son score contre elle vaut 0.50 par identité. La baseline de
`PoolEarlyStoppingCallback` la mesure ; hors de `[0.40, 0.60]`, le run est refusé **avant le
premier épisode**. Les 2026-09-04 et 2026-09-05 ont chacun produit des heures d'entraînement sur
une baseline aberrante (0,477 puis 0,118) lue comme une mesure.
Il ne se pose qu'à `_stage_episode() == 0`, et pas sur la seule origine du compteur : après un
`--resume-from <checkpoint>` de reprise sur crash, l'origine reste celle de l'archive source alors
que le modèle a joué des milliers d'épisodes — le tester là arrêtait toute reprise dont la
politique avait progressé hors de la fenêtre.

**5. Toutes les décisions passent sur la moyenne des `probe_window` dernières sondes**
(`pool_eval/vs_<tag>_<probe_window>ep` — 3 aujourd'hui ; le tag porte la fenêtre réelle, il
annonçait `_3ep` quelle que soit la valeur configurée). Promotion et arrêt si ≥ 0.55 contre le
champion **et** ≥ 0.50 contre chaque autre membre après 50 000 épisodes d'étape ; arrêt pour
destruction si < 0.40 contre le champion après 20 000. Le gate de fin applique les mêmes seuils sur
une moyenne de 3 blocs d'évaluation, et un seuil de promotion **sous** le plancher du gate est
refusé au chargement (sinon le run s'arrête en se déclarant promu sur un score que le gate
refusera, et jette le budget non dépensé avec l'étape). Le pool **entier** est sondé, plus
seulement le champion : une étape pouvait être promue en battant son prédécesseur immédiat tout en
ayant régressé contre tout le reste. Une archive du pool écartée par l'évaluation **arrête le
run** au lieu d'être signalée : sans elle, ni promotion ni destruction ne peuvent plus être
décidées, et l'étape brûlait son budget entier pour une ligne ⚠️ par sonde.

**6. Un verdict `destroy` est souverain : le gate ne le rejuge pas.** L'étape est refusée sans
mesure. Sous `save_best_robust` (les profils du curriculum), le zip canonique est l'instantané
robuste pris plus tôt dans le run — **d'autres poids que ceux jugés** : le gate pouvait donc
l'accepter et le promouvoir, et `curriculum.log` portait `pool_stop_verdict: "destroy"` à côté de
`gate_accepted: true`. Un verdict `promote`, lui, laisse le gate mesurer normalement.

⚠️ **`base_seed` de `evaluate_against_checkpoints` est désormais TIRÉ AU HASARD.** Il valait 42 en
dur, donc deux évaluations d'un même modèle rejouaient les mêmes parties et rendaient le même score
au bit près (vérifié le 2026-09-07 : 16/24/0 aux deux appels) — moyenner trois blocs identiques
n'est pas une moyenne. Conséquence à assumer : **un gate n'est plus reproductible à l'identique**,
et les scores de `curriculum.log` antérieurs au 2026-09-07 portent un échantillon unique et figé.

**À mesurer au prochain run** : `00_critical/g_grad_share_policy_mb0` doit monter de 0,235 vers
~0,62 dès les premières updates — effet arithmétique de `vf_coef`, pas un effet d'apprentissage.
Si elle ne bouge pas, le régime n'a pas pris et il est inutile d'attendre. `n_steps` × 4 quadruple
la mémoire du rollout buffer : **coût horloge et mémoire non chronométrés** à ce volume.

### Six défauts de la livraison, fermés le 2026-09-07

**Le premier était bloquant pour toute la chaîne.** `_apply_curriculum_model_params` posait un
`ConstantSchedule` sur `model.learning_rate`, que SB3 sérialise dans le `data` du zip — un objet
cloudpickle là où `_model_scalar` attend un nombre. Tant que le LR était une **rampe**, le
callback d'ordonnancement réécrivait un flottant à chaque épisode et masquait le défaut ; le
régime posant un LR **scalaire**, aucun callback n'est monté. P2 (repris de P1, dont le zip porte
encore un flottant) tournait, mais P3 aurait levé au contrôle de continuité — et avec lui P4…P10
et E1…E3. `learning_rate` porte désormais le nombre, `lr_schedule` le callable, comme le fait déjà
`LearningRateScheduleCallback._apply`.

**Une reprise sur crash enchaînait les sondes manquées.** `_next_probe_episode` partait du premier
cran alors que le compteur d'étape, ancré sur l'archive source, valait déjà des dizaines de
milliers d'épisodes : les crans manqués se déclenchaient d'affilée sur des pas consécutifs, sans
mise à jour de politique entre eux. À la deuxième, l'historique atteignait deux points et un
verdict tombait — sur deux mesures des **mêmes** poids, au-dessus de `promote_min_episodes` : le
run de reprise pouvait être promu ou déclaré détruit après **zéro épisode entraîné**. Même défaut
que les 8 sondes consécutives mesurées le 2026-09-04, revenu par une autre porte. La cadence
rattrape désormais au prochain cran au lieu d'avancer d'un pas ; corrigé sur les deux sondes
(pool et exploiteur).

**`--close-stage` rouvrait la promotion d'une étape détruite.** Le verdict `destroy` n'existait que
dans le `run_info` du processus : la commande de reprise le reconstruit depuis les artefacts du
disque, où il n'apparaît pas. Comme une étape détruite n'écrit aucun `model_<agent>_<etape>.zip`,
le garde « déjà promue » ne voyait rien non plus, et la clôture remesurait l'instantané robuste —
d'autres poids que ceux jugés, qui pouvaient franchir le gate. `_run_info_from_disk` relit
désormais le verdict dans `curriculum.log`, filtré sur `written_by == ai/train.py`.

**Un verdict `promote` publie désormais les poids VIVANTS** (décision du 2026-09-07, option A).
L'early-stop rend ce verdict sur les poids courants, mesurés contre tout le pool ; sous
`save_best_robust` le zip canonique était pourtant l'instantané robuste, choisi sur le score
contre les **bots** et jamais dégradé en cours de run (la copie n'a lieu que si le score robuste
progresse — `training_callbacks.py`, condition `robust_score > best_robust_score`). Le gate de fin
mesurait donc un modèle que personne n'avait jugé, pouvait le refuser, et le run s'était déjà
arrêté : le budget non dépensé partait avec l'étape — l'inverse exact de ce que l'arrêt anticipé
annonce (« le budget restant serait payé pour rien »). Publier est l'exception que
`save_best_robust` peut accepter : le verdict **est** une validation contre l'intégralité du pool.
Le verdict `destroy`, lui, ne publie rien.
⚠️ **Le seuil de score robuste du canonique (`canonical_robust_meta_path`) est effacé à cette
publication.** Il décrit le modèle remplacé, et il **survit à l'étape** (seul `--new` l'écarte,
via `archive_canonical_artifacts_for_new_run`) : laissé en place, il
imposerait à l'étape suivante de battre le score d'un modèle disparu avant de republier son propre
canonique — le défaut constaté en production sous V11 §0.36.

**Cadence des sondes dédoublée** (décision du 2026-09-07, option B). Sonder le pool entier à
chaque sonde faisait suivre le coût à la **taille** du pool, qui croît d'une étape à l'autre : à
P10 (13 membres, 300 000 épisodes, cadence 10 000, 300 épisodes par membre) cela fait **117 000
épisodes d'évaluation bloquants** sur le fil d'entraînement pour 300 000 entraînés, là où la sonde
champion seul d'avant en coûtait 9 000. Le champion est désormais mesuré à **chaque** sonde, les
autres membres **un tour sur `full_pool_probe_every`** (3 dans la config livrée) : il reste
~48 600 épisodes, soit **-58 %**. Les deux verdicts n'ont pas le même besoin de fraîcheur — la
destruction ne lit que le champion et doit couper vite, la promotion lit tout le pool mais ne
s'ouvre qu'à 50 000 épisodes d'étape. **Ce qui n'est pas dégradé** : le verdict lit toujours le
pool entier, les membres non sondés au tour courant gardant leur dernière moyenne connue, au plus
trois sondes en arrière. Les **deux premiers tours restent pleins** quelle que soit la valeur :
aucun verdict n'est rendu tant qu'un membre n'a pas deux points, et sans eux la destruction
attendrait 40 000 épisodes au lieu des 20 000 que son seuil demande.

**Trois fermetures plus petites.** La clôture dérivait le champion par un `next(...)` local là où
`stage_champion_label` **refuse** un pool à plusieurs champions, que `validate_curriculum` accepte
— elle prenait le premier venu en silence. Le plombage `timesteps_origin` était mort depuis la
suppression du garde `min_steps` : `stage_origin` ouvrait le zip source pour cette seule valeur.
Et la docstring de `pool_monotonicity_diagnostic` dimensionnait encore son bruit contre
`gate.target_score_vs_champion` (0.60), clé supprimée par cette même livraison.

---

## 🔴 Régime d'entraînement révisé — P2 à relancer depuis P1 {#regime-2026-09-06}

Deux changements livrés le 2026-09-06, plus un réglage d'évaluation du 2026-09-04 resté non déclaré
jusqu'ici. **Ce qui reste à faire : relancer P2 depuis P1.** P1 n'est pas rejoué (décision du
2026-09-06 : le temps est déjà payé), sa config est seulement homogénéisée.

**1. Le déploiement `auto` pose désormais les deux camps.** Il ne posait que le joueur contrôlé :
l'agent était placé au hasard pendant que son adversaire — bot à doctrine, ou champion du pool
jouant son réseau — se déployait avec sa politique apprise. `r_win_rate_deploy_auto` mesurait donc
un handicap unilatéral et non l'adaptabilité qu'elle prétend mesurer. Mesure du run x1_long du
2026-09-06 (~64 000 épisodes) : **0.304** de win-rate en `auto` contre **0.684** en `active`, avec
un différentiel d'objectifs de **-0.76** contre **+0.19** — l'agent tenait trois quarts d'objectif
de moins que son adversaire. La référence du 2026-08-12 (0.866 / 0.646, les deux différentiels
positifs) avait été prise contre des bots à doctrine de pose fixe, bien moins capables d'exploiter
une pose adverse médiocre.

⚠️ **`r_win_rate_deploy_auto` et `q_obj_held_diff_deploy_auto` changent de définition** : leurs
valeurs antérieures au 2026-09-06 ne se comparent pas aux suivantes. Attendu au prochain run : la
courbe `auto` doit remonter vers 0.5 en P2, puisque l'agent EST le champion à l'épisode 0. Si elle
reste basse, c'est qu'il reste autre chose à chercher.

**2. La part de bots tombe à 30 % en P1, 20 % en P2, 15 % de P3 à P10.** Les six bots sont saturés
— EndgameBot 0.99, DecapitationBot 0.95, RacerBot 0.94, AlphaStrikeBot 0.93, AttritionBot 0.92,
ScorerBot 0.86, aucun sous 0.86 — quand le champion du pool est à 0.502 (parité) et P0 à 0.626.
637 500 épisodes de la lignée partaient contre des adversaires dominés, soit 23 % du budget ; il
en reste 455 000. Pas 15 % partout : la part de bots suit la **taille du pool**, pas la force de
l'agent — à 15 %, P1 jouerait 85 % de ses parties contre son unique membre de pool, soit le régime
d'un exploiteur alors qu'il est promu champion. La rampe d'adversité de P1 est supprimée au
passage (elle le faisait démarrer à 100 % de bots), résidu du nettoyage qui avait retiré les neuf
autres.

**3. `bot_eval_intermediate` de `x1_long` passe à 100 épisodes par bot** (2026-09-04), pour la
précision de chaque point intermédiaire : à 30, l'erreur-type d'un win-rate autour de 0,5 valait
0,5/√30 = 9,1 points, du même ordre que les écarts qu'on cherche à lire d'un point au suivant ; à
100 elle tombe à 5,0. Contrepartie : l'évaluation intermédiaire passe de 6 × 30 = 180 à
6 × 100 = 600 épisodes, **coût horloge non rechronométré** à ce volume — les durées de
`bot_eval_freq_normal` valent pour 180. À mesurer au prochain run avant d'être citées.
`x5_long` reste à 30 : les deux profils `_long` divergent sur cette clé, et c'est assumé — le
chiffre publié sort de `x1_long`. La sonde d'entraînement, elle, reste à 3 avec son +33 %.
Le réglage et la divergence sont désormais verrouillés profil par profil
(`tests/unit/ai/test_schedule_decay_fraction.py`), ce qu'ils n'étaient pas : le verrou de
comparabilité était rouge depuis le 2026-09-04, avec quatre autres tests, et personne ne le voyait.

**Mesure incidente, non élucidée.** Le run P1 a joué **31,3 %** contre P0 (25 063 épisodes sur
80 075, `tensorboard/P1`), là où sa config annonçait 50 %. L'écart n'est pas expliqué par la rampe
seule, qui s'achève en ~417 épisodes par env et ne pèse que 12 % du run. Non investigué : le run
n'est pas rejoué. À retenir : un `ratio_end` n'est pas une mesure — la part réellement jouée se lit
sur le rapport entre les points de `03_selfplay/<membre>` et ceux de `actions/share_deploy_slot`,
à 500 près (la fenêtre de lissage).

---

## ⚠️ Courbes de santé PPO — historique des défauts {#courbes-ppo-reprise}

Trois défauts vivaient sur la capture des métriques PPO
(`MetricsCollectionCallback._on_training_start`), corrigés le 2026-09-04. Ce qu'ils rendent
illisible sur les runs antérieurs :

**Sur les runs REPRIS uniquement** (`--resume-from`, donc toute étape de curriculum à
`init: "from:..."`) — les quatre courbes de santé PPO de `00_critical` ne sont **pas lissées** et
ne doivent pas être lues : `g_explained_variance`, `h_clip_fraction`, `i_approx_kl`,
`j_entropy_loss` — lettres d'AVANT le 2026-09-06, conservées ici parce que ce sont celles que
portent réellement les fichiers `events` de ces runs ; depuis, l'insertion de
`g_grad_share_policy_mb0` les a décalées en `h_`, `i_`, `j_` et `k_`. L'enveloppe posée sur `logger.dump` n'était jamais retirée, et SB3 appaire
pourtant `on_training_start`/`on_training_end` autour de chaque `learn()`. Sur un run neuf le
logger est reconstruit à chaque `learn()` et l'enveloppe morte partait avec lui ; en reprise
`model.set_logger` le rend persistant et les couches s'accumulaient. Chaque update était alors
capturé autant de fois qu'il y avait de couches, et la fenêtre de vingt valeurs de
`_calculate_smoothed_metric` finissait par couvrir vingt copies du même update. Mesure sur le run
P1 du 2026-09-03 : 41 756 points sur `training_critical/clip_fraction` pour **575 updates réels**,
contre 1 063 points pour 1 063 updates sur un run neuf comparable. Les courbes paraissaient 4× à
14× plus bruitées, sans que la politique ni le régime d'update soient en cause.

**Sur TOUS les runs, neufs compris** :

- `training_diagnostic/entropy_coef` et `training_diagnostic/gradient_norm` portent **un point par
  ÉPISODE** et non par update. `_handle_episode_end` appelle `logger.dump` à chaque fin d'épisode,
  et la capture s'y déclenchait alors qu'aucun update PPO n'y figure — les gradients y sont ceux
  laissés par le dernier `train()`. Mesure sur le run neuf du 2026-08-29 : 101 415 points pour
  100 000 épisodes et 1 063 updates.
- Toutes les courbes `training_critical/*` et `training_diagnostic/*` sont **décalées d'un dump**
  sur l'axe des pas : l'abscisse était posée après l'écriture, donc chaque update partait au pas du
  dump précédent.

**Ce qu'il faut lire sur ces runs** : les séries brutes `training_critical/clip_fraction`,
`approx_kl`, `explained_variance` et `training_diagnostic/entropy_loss`. Les valeurs y sont
exactes ; sur un run repris elles sont répétées, et les copies d'un même update se superposent à
la **même** abscisse plutôt que de former un escalier — la courbe reste donc lisible, à condition
de la lire comme une suite de paliers et non comme un signal bruité.

Les courbes de jeu (`d_win_rate`, `e_episode_reward_smooth`, `03_selfplay/*`) ne passent pas par
ce chemin et n'ont jamais été touchées.

Le run P1 en cours au 2026-09-04 a chargé le code avant le correctif : ses courbes restent
fausses jusqu'à sa fin. Verrou : `tests/unit/ai/test_metrics_dump_wrapper_idempotent.py`.

**Quatrième défaut, distinct des trois précédents, corrigé le 2026-09-06** — celui-ci touchait
**tous** les runs, neufs compris, et il est indépendant de l'empilement d'enveloppes. Les cinq
courbes `00_critical/f..j` et les huit lignes `thresholds/*` étaient republiées à **chaque fin
d'épisode** alors que leur source n'est alimentée qu'une fois par update : 39 430 points pour 529
valeurs distinctes sur `run_20260906-123804`, soit 74,5 copies par valeur, contre 532 points et
532 valeurs sur les jumelles `train/*` de SB3. Le curseur de lissage de TensorBoard comptant des
points, il aurait fallu le régler sur ~1 500 pour couvrir la fenêtre glissante de 20 updates. Aucune
valeur n'était fausse — l'enveloppe de l'escalier est la bonne série — mais le curseur était
inopérant et les runs de cadences d'update différentes n'étaient pas comparables point pour point.
Ces treize tags portent désormais un point par update. Verrou :
`tests/unit/ai/test_metrics_tracker_utils.py::test_les_courbes_de_sante_ppo_suivent_la_cadence_de_l_update`.
Les runs antérieurs au 2026-09-06 gardent l'escalier, à lire comme une suite de paliers.

---

## Sonde win-rate scénarios d'entraînement {#training-probe}

**Livré 2026-09-06.** `training_probe_every_n_evals` dans `BotEvaluationCallback` publie
`bot_eval/training_combined` sur TensorBoard, calculé contre les scénarios d'ENTRAÎNEMENT (pas
holdout), en mode déterministe, tous les N evals holdout.

Motif : gap factor 2,5 mesuré le 2026-09-06 entre +13 pts sur les scénarios d'entraînement et
+5 pts holdout, invisible sur le dashboard existant. Les deux courbes permettent de distinguer :

- courbe plate → **n'apprend pas** → correction : hyperparamètres, récompense, obs.
- courbe haute / gap large → **n'généralise pas** → correction : pool de scénarios, régularisation.

Ne gate rien. Activé à 3 (`x1_long` profile, `callback_params.training_probe_every_n_evals`).
Coût : +33 % du budget eval distribué uniformément.

---

## Critères pipeline du run en cours (ex-« run x1 de vérification ») {#run-verif}

Un run `x1` de vérification dédié avait été décidé le 2026-08-11 pour prouver que le pipeline
tourne avec l'espace de décision modifié. Le run `x1_long --new` lancé le 2026-08-17
([bot.md#etape8](bot.md#etape8)) embarque le même code à HEAD : **les critères se lisent sur SES
courbes**, un run séparé n'a plus d'objet sauf si celui-ci échoue.

✅ Critères vérifiés sur le run `x1_long --new` du 2026-08-20 :

- ✅ `game_critical/invalid_action_rate` reste à **0**
- ✅ `02_combat/m_charge_attempts` **non nul**
- ✅ `02_combat/n_charge_success_rate` **non nul** (en V11 la déclaration est gratuite — l'agent déclare « au cas où » puis choisit ses cibles après le jet ; un taux bas ne signifie pas un dysfonctionnement)
- ✅ Courbes `reserves/*` et `05_charge/*` **peuplées** (`charge_distance/*` était le nom de la clé interne, le tag TensorBoard réel est `05_charge/*`)

⚠️ Pour tout re-run : `--new` et non `--append` — `--append` réapplique `ent_coef = 0,1` et écrase le modèle canonique.

---

## ✅ Curriculum R1→R3 — absorbés par le curriculum `--etape` {#curriculum}

**Décision 2026-08-30 — R1→R3 abandonnés comme runs standalone.**

Deux raisons rendent ces runs redondants :

1. Le bug d'aliasing obs Phase 3 (corrigé 2026-08-29) invalide toute ligne de base antérieure.
   La validation du fix s'est faite sur le run `--etape P2` (ratio_mb0=1.0, EV→0.85) — ce run
   tient lieu de R1.
2. Le curriculum `--etape` P0→P10 intègre déjà les trois leviers séquentiellement : P0 = bots
   purs (≡ R1), P1/P2/… = self-play progressif (≡ R2), levier récompense = à tester via
   `--etape` sur un run ultérieur si D.4 le justifie (≡ R3).

Mesurer R1/R2/R3 en standalone n'apporterait que la décomposition du gain par levier — utile
pour arbitrer, mais le curriculum `--etape` les intègre tous et la mesure J3 se fera sur le
champion final.

**Le chiffre J3 se lit sur le champion issu du curriculum P0→P10, pas sur un run standalone.**

→ `Documentation/Chantiers/backlog/curriculum_adversaires_etalons.md` §5-7 (historique)

---

## Mode exploiteur E1/E2/E3 {#exploiteur}

**Livré 2026-08-22.** `--etape E1/E2/E3` mesure l'exploitabilité de sa cible (P3, P5, P8) :
budget = épisodes pour passer de 50 % à 70 % de win-rate contre la cible figée.

- `ExploiterProbeCallback` : sonde synchrone tous les 2000 épisodes (100 ép. bon marché →
  une seule confirmation de 500 ép.), sans Future ni ThreadPoolExecutor.
- `validate_exploiter_protocol` : refuse le run si `training_config`, `ratio`, `warmup`
  ou `profile_total_episodes < budget_cap` divergent du protocole gelé (`exploiter_config`).
- `curriculum.log` : budget entier ou `'>50000'` (censuré) + courbe win_rate complète.
- 28 tests verrou (4 verrous : refus protocole, budget_cap atteignable, pas de sonde abandonnée, valeur censurée).
- `training_config_required` : `x1_long` (50 000 épisodes = `budget_cap`).

Lancer : `python3 ai/train.py --agent ArmageddonAgent --training-config x1_long --scenario bot --etape E1`

---

## É9 — Second siège + second scénario {#e9}

**Suspendu** — après entraînement bot satisfaisant (jalon J4). Second scénario écrit par l'utilisateur (décision 2026-08-02).

→ `Documentation/Chantiers/v11/index_v11.md` §0.47

**2026-08-28 — levier d'exposition livré, indépendamment de É9.** `agent_seat_p2_ratio` rend pondérable le tirage de siège en entraînement (il était figé à 50/50 par la parité d'un hachage) ; réglage posé à 0.65 sur les six profils. Motivation : 12 points d'écart p1/p2 mesurés sur le run x1_long du 2026-08-12. L'évaluation garde son tirage équitable. É9 reste ouvert : il porte le second SCÉNARIO, que ceci ne traite pas. Effet à mesurer au prochain run — voir `Documentation/Reference/training/entrainement.md`.
