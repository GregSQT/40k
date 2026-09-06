# Training — Tâches ouvertes

---

## 🔴 Régime d'entraînement révisé — P2 à relancer depuis P1 {#regime-2026-09-06}

Deux changements livrés le 2026-09-06. **Ce qui reste à faire : relancer P2 depuis P1.** P1 n'est
pas rejoué (décision du 2026-09-06 : le temps est déjà payé), sa config est seulement homogénéisée.

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

**3. `bot_eval_intermediate` de `x1_long` revient à 30 épisodes par bot.** Il avait été porté à 100
le 2026-09-04 par un commit d'une ligne, sans note ni mesure, contre la décomposition
« 6 bots × 30 = 180 » que le profil documente lui-même dans la clé voisine et contre `x5_long`,
resté à 30. L'écart n'était pas visible : le verrou de comparabilité des profils
(`tests/unit/ai/test_schedule_decay_fraction.py`) était rouge depuis, en même temps que quatre
autres tests. Effet sur le run à relancer : l'évaluation intermédiaire redescend de 600 à
180 épisodes, soit le tiers de son coût. La sonde d'entraînement, elle, reste à 3 et garde son
+33 % — elle est désormais verrouillée nommément, profil par profil.

**Mesure incidente, non élucidée.** Le run P1 a joué **31,3 %** contre P0 (25 063 épisodes sur
80 075, `tensorboard/P1`), là où sa config annonçait 50 %. L'écart n'est pas expliqué par la rampe
seule, qui s'achève en ~417 épisodes par env et ne pèse que 12 % du run. Non investigué : le run
n'est pas rejoué. À retenir : un `ratio_end` n'est pas une mesure — la part réellement jouée se lit
sur le rapport entre les points de `03_selfplay/<membre>` et ceux de `actions/share_deploy_slot`,
à 500 près (la fenêtre de lissage).

---

## ⚠️ Courbes de santé PPO — runs lancés avant le 2026-09-04 {#courbes-ppo-reprise}

Trois défauts vivaient sur la capture des métriques PPO
(`MetricsCollectionCallback._on_training_start`), corrigés le 2026-09-04. Ce qu'ils rendent
illisible sur les runs antérieurs :

**Sur les runs REPRIS uniquement** (`--resume-from`, donc toute étape de curriculum à
`init: "from:..."`) — les quatre courbes de santé PPO de `00_critical` ne sont **pas lissées** et
ne doivent pas être lues : `g_explained_variance`, `h_clip_fraction`, `i_approx_kl`,
`j_entropy_loss`. L'enveloppe posée sur `logger.dump` n'était jamais retirée, et SB3 appaire
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
