# Training — Tâches ouvertes

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

## Pool de workers des sondes — recréé à chaque tranche {#pool-sondes}

`ExploiterProbeCallback` et `PoolEarlyStoppingCallback` créent leur pool de workers dans
`_on_training_start` et le ferment dans `_on_training_end`. Or SB3 appelle ces deux méthodes
autour de **chaque** `learn()` (`sb3_contrib/ppo_mask/ppo_mask.py`, lignes 448 et 467), et la
boucle budgétée en épisodes de `train_with_scenario_rotation` enchaîne un `learn()` par tranche de
quatre updates. Le pool est donc créé puis fermé une fois par tranche.

Rien n'est abandonné ni fuité — chaque pool est bien fermé par le `_on_training_end` de sa tranche
— mais la persistance que les docstrings annonçaient (« pool persistant pour toutes les sondes de
cette étape ») **n'existe pas** : chaque sonde repaie le démarrage de ses workers, moteur et
modèle compris. Les docstrings ont été corrigées le 2026-09-04 ; le comportement, lui, reste à
traiter.

Piste : déplacer création et fermeture hors du couple `_on_training_start`/`_on_training_end`, par
exemple une création paresseuse à la première sonde et une fermeture confiée à la fin d'étape
(`_close_curriculum_stage`) ou à un `atexit`. Le choix engage le cycle de vie des deux callbacks,
et un pool laissé ouvert après un `learn()` doit être fermé sur tous les chemins de sortie, y
compris l'exception qui remonte de `_probe`.

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
