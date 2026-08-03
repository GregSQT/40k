# V11 — Rétablissement de l'entraînement de l'agent (agent rework)

Date d'audit : 2026-07-14. **Relecture intégrale du document contre le code le 2026-08-02**
(8 lots de vérification en lecture seule ; corrections reportées dans les entrées concernées).
Tous les faits ci-dessous ont été vérifiés dans le code actuel
(lecture + exécution de smoke tests), puis contre-vérifiés par une review indépendante
(2026-07-14 soir). Chaque rupture est accompagnée de sa reproduction exacte.

**Convention d'ancrage** : l'ancre de référence est le NOM DE FONCTION ; les numéros de ligne
sont indicatifs (constaté pendant l'audit : fight_handlers.py a bougé de ~45 lignes en une
journée). Toujours re-localiser par grep du nom avant d'éditer.

> ### 👁️ Ce que l'agent OBSERVE — descriptif complet
>
> **[`Documentation/AI_OBSERVATION.md`](../AI_OBSERVATION.md)** — il ne décrit QUE le code actuel
> depuis le 2026-07-28 : les clés et leurs formes, la table blocs logiques A→E ↔ clés, l'espace
> d'action associé, les trois invariants, **qui normalise quoi** (`VecNormalize` vs
> `EntityRunningNorm`), **les 5 caches et leur condition d'invalidation**, et l'historique
> d'`obs_size`.
> Le pipeline **mono-figurine legacy** (vecteur plat d'offsets `obs[N]`, features calculées) est
> archivé à part : [`AI_OBSERVATION_Legacy.md`](../AI_OBSERVATION_Legacy.md). Aucun agent ne
> l'utilise.
>
> **Source unique du contrat** (la doc en donne la lecture, jamais une copie de chiffres) :
> [`engine/observation_entities.py`](../../engine/observation_entities.py) pour le schéma, et
> l'en-tête « OBSERVATION SQUAD — TENSEURS D'ENTITÉS » de
> [`engine/observation_builder.py`](../../engine/observation_builder.py) pour le layout.
>
> **Conception et journal** : [`V11_entity_encoder_pointer.md`](V11_entity_encoder_pointer.md)
> (encodeur partagé, tête pointeur, cardinalités) · [`V11_audit_observation.md`](Implémenté/V11_audit_observation.md)
> (audit d'origine) · **[§9.2.5](V11_phaseA.md#s9.2.5)** et **§0.31** de ce document (ce qui est observé, et pourquoi).
>
> **🎬 Replay (outillage d'analyse)** : [`Replay.md`](Replay.md) — sémantique du viewer replay
> (dont : le cercle vert fight = la seule unité activée, dérivée de l'attaquant, aucun pool loggué).

---

<a id="s0"></a>
## 0. ÉTAT AU 2026-08-02 — À LIRE EN PREMIER

> **Cette section ne contient QUE ce qui est ouvert et actionnable.**
> - Ce qui est résolu est en **§0hist — Historique résolu**, **en fin de document, après les [Pointeurs](#pointeurs)** :
>   entrées intégrales, ancres `### 0.x` inchangées, aucune preuve condensée.
> - Les avertissements et leçons de méthode durables sont regroupés en **§0bis — Pièges et
>   leçons de méthode**, qui en est la **copie canonique**.
>
> **Conventions de tenue de ce document — les respecter en le mettant à jour :**
> - **Un numéro d'entrée est attribué à vie.** Une entrée résolue descend en §0hist en gardant
>   son numéro ; un numéro n'est jamais réattribué. Prochaine entrée libre : `0.61` (`0.57`–`0.60` le 2026-08-02, `0.18`–`0.21` le 2026-07-20, `0.22` le 2026-07-21, `0.23`–`0.28` le 2026-07-22, `0.29` le 2026-07-22, `0.30` le 2026-07-26, `0.31` le 2026-07-27, `0.32`–`0.43` le 2026-07-28, `0.44`–`0.52` le 2026-07-29, `0.53`–`0.54` le 2026-07-30, `0.55`–`0.56` le 2026-08-02).
> - **Un contenu d'état vit à UN seul endroit.** Une entrée à moitié résolue est **scindée** :
>   la part résolue reste sous son numéro en §0hist, la part ouverte prend un numéro neuf ici,
>   et les deux se renvoient l'une à l'autre. Seuls les avertissements et leçons sont dupliqués
>   (§0bis fait foi).
> - Une entrée **périssable** (état de commit, mesure) porte sa date et l'ordre de la
>   reconfronter au réel avant usage.

### Tableau d'état — ce qui est ouvert

**Épuration du 2026-08-02** : les entrées **§0.29, §0.33, §0.42, §0.43, §0.49, §0.51, §0.52,
§0.54** sont descendues en **§0hist** — elles sont closes. Épurations précédentes : **§0.22, §0.27,
§0.28, §0.31, §0.32, §0.34, §0.35, §0.36, §0.37** le 2026-07-28 ; **§0.39, §0.40, §0.45** le
2026-07-29.

> **Ce tableau ne porte que les GRANDES LIGNES.** Le détail d'une entrée vit dans sa section ;
> l'historique intégral est en fin de document. Une cellule qui grossit au point de raconter un
> run ou une chronologie est à redescendre.

⏳ **Relecture intégrale du document contre le code, le 2026-08-02.** Le fond technique du
document a été confirmé ; c'est son ÉTAT qui avait dérivé. Motif dominant corrigé ici : **toutes
les branches déclarées « NON MERGÉ » étaient en réalité mergées sur `main`** (§0.43, §0.46, §0.47,
§0.49, §0.50, §0.51, §0.53, §0.54 — vérifié par `git merge-base --is-ancestor`), et les branches
correspondantes sont supprimées. Les conséquences par entrée sont reportées ci-dessous.

📌 **Périmètre de profils** : seuls les profils **`x1*`** sont utilisés aujourd'hui (décision
utilisateur du 2026-08-02). Les valeurs citées pour `x5_new` / `x5_append` / `x5_debug` ne sont pas
tenues à jour et **ne doivent pas servir de référence** — les relire dans le JSON avant usage.

| # | Entrée | Statut | Ordre | Prochaine action concrète |
|---|---|---|---|---|
| **§0.61** | Le garde **anti-runaway** était MUET, et son compteur d'épisodes divergeait | ✅ **CORRIGÉ le 2026-08-03** | **1** | Une troncature signale une BOUCLE dans le moteur, pas une fin de partie — or son diagnostic n'existait que dans le `print` d'un worker (noyé à `n_envs=48`) et le compteur persisté ne la comptait pas, alors que le run s'arrête dessus. Nouveau scalaire `00_critical/t_truncated_episodes`, diagnostic complet en `truncations.jsonl`, bilan imprimé en fin de run. Détail → §0.61. |
| **§0.60** | Instrumentation du **coût** de l'entraînement — workers d'éval, temps bloquant, courbes de charge et de participation | ✅ **LIVRÉ le 2026-08-02** | **2** | Trois angles morts de COÛT, distincts des angles morts de COMPORTEMENT du §0.56. (1) Quatre clés `bot_eval_*` vivaient **hors de `callback_params`** : personne ne les lisait, `bot_eval_n_workers` retombait sur `min(n_envs, n_scenarios × n_bots)` = **24 workers**, soit **47 Go et 598 s** contre **9,6 Go et 349 s** à 4 workers — moins de workers est aussi **42 % plus rapide**, la VM passant son temps à swapper. `validate_bot_eval_worker_params` valide désormais au DÉMARRAGE. (2) `blocking_eval_seconds` ne compte plus que le temps où la boucle est RÉELLEMENT figée. (3) Six courbes moteur : charges tentées/réussies (agent et bot) et participation par phase. Détail → §0.60. |
| **§0.59** | Régime d'entraînement en **deux phases** — `x1_selfplay` (self-play) et `decay_fraction` | 🟠 **OUVERT — livré, JAMAIS EXÉCUTÉ** | **2** | Deux changements de régime non mesurés. (1) `decay_fraction` achève les rampes lr/entropie **avant** la fin d'un run long (sans lui, un run de 200 000 épisodes garde une entropie élevée jusqu'au dernier épisode). (2) Le profil `x1_selfplay` ajoute une **phase 2** en `--append` : un snapshot figé de l'agent remplace le bot sur une part rampée **0.0 → 0.5** des épisodes. ⚠️ Aucun run de phase 2 n'a jamais tourné ; `opponent_mix.enabled` **lève** hors du chemin de rotation de scénarios. Détail → §0.59. |
| **§0.58** | Les rampes par-épisode **redémarraient à chaque reprise** (`--append`, `--resume-from`) | ✅ **CORRIGÉ le 2026-08-02** | **1** | Rien ne persistait le nombre d'épisodes joués : la rampe de déploiement n'atteignait jamais `active_ratio_end` et le compte cumulé du modèle était écrasé par celui du seul run courant. `ai/run_state.py` persiste le compte (compté, jamais dérivé de `num_timesteps`) ; reprendre un modèle sans lui **lève** (arbitrage : pas de compatibilité ascendante). `learning_rate`, `ent_coef` et le self-play sont des rampes de **RÉGIME** : elles repartent de zéro à chaque run, et c'est l'arbitrage. Détail → §0.58. |
| **§0.57** | Les rampes par-épisode du moteur avançaient **`n_envs` fois trop lentement** | ✅ **CORRIGÉ le 2026-08-02** — reste une conséquence à assumer | **1** | Le compteur d'épisodes du moteur est LOCAL à un worker ; il était divisé par le total GLOBAL. À `n_envs=48`, la rampe de déploiement est restée collée à `active_ratio_start` sur TOUS les runs vectorisés (mesuré : `s_deploy_active_share` 0.3040 pour 0.496 attendus). Même défaut sur `deployment_random_mix`. **Conséquence : aucune mesure passée n'a été produite avec la rampe annoncée** — §0.29 et §0.46 pt 2 sont amendés. Détail → §0.57. |
| **§0.56** | Instrumentation : usage par **famille d'action**, et **classement bot-contre-bot** | ✅ **LIVRÉ le 2026-08-02** — reste à s'en servir | **2** | Deux angles morts fermés, aucun ne coûte de ré-entraînement. (1) `actions/share_<famille>` publie la part de chaque DÉCISION dans ce que l'agent joue : une dimension jamais choisie ou toujours choisie est cassée quel que soit le win-rate — c'est ce qui rend un lot de tranches P3 diagnosticable **en un seul run**. (2) `scripts/bot_ranking.py` fait s'affronter les bots **sans agent** : sans lui, juger un bot exigeait un modèle entraîné, donc une mesure circulaire — et §0.55 était irréalisable. Détail → §0.56. |
| **§0.55** | Le **holdout d'évaluation** `TacticalBot` est DANS l'enveloppe d'entraînement — effet plafond | 🟠 **OUVERT** — re-profilage validé le 2026-08-02 (arbitrage utilisateur), à écrire | **1** (avant toute mesure de référence) | `tactical` porte `w_objective 0.5 / w_enemy 0.0` : un `ControlBot` dilué, interpolé entre `control` (1.0/0.1) et `defensive` (0.7/−0.5). Un holdout intérieur à l'enveloppe mesure l'**interpolation**, pas la généralisation — d'où `vs_tactical` **0.95** au run 4. Re-profiler **hors enveloppe** (`w_objective 0.8 / w_enemy 0.6`) et ajouter le scalaire `vs_tactical` **par roster**. 🛠️ **Spec d'application ÉCRITE le 2026-08-02** (3 étapes, 2 fichiers, mesure `bot_ranking` avant/après) — **rien n'est appliqué** : `config/` est relu à chaud par les évals du run en cours. ⚠️ **À faire AVANT de geler la baseline d'évaluation** : après, plus aucune mesure n'est comparable (leçon §0.47 É4). Détail → §0.55. |
| **§0.14** | Re-mesure du run — win-rate par matchup | ⏳ **PÉRIMÉE — état au 2026-08-02** : des runs **postérieurs au run 4** ont tourné (modèles `robust_*` du 2026-07-30 et du 2026-08-01 dans `ai/models/ArmageddonAgent/`) et **un `train.py` tournait** au moment de la relecture. Le répertoire `tensorboard/x1_ArmageddonAgent/` n'existe plus. | **1** | Reconfronter au réel (`ps -eo lstart,cmd \| grep train.py`, `ls -l ai/models/ArmageddonAgent/`) puis **réécrire l'entrée sur le run courant**. Les chiffres du run 4 (`combined` **0.509**, `worst_bot_score` **0.04**, `vs_control` **0.04**) ne valent plus que comme historique, et sur une pondération de bots qui n'existe plus (§0.53). Détail → §0.14. |
| **[§9](V11_phaseA.md#s9)** | Phase A' — P2 + P3-0/1/2 | 🟢 **LIVRÉS ET MERGÉS sur `main`** — restent **P3-3→8**, **P4**, **P5** | **2** | ⚠️ Aucune des quatre livraisons n'est **MESURÉE**. ⚠️ P3-0 est **inerte dans le training** (aucun roster SM/Ork ne porte de rule choice). Détail → §0.42 et §0.43 (en §0hist), et [§9](V11_phaseA.md#s9). |
| **§0.44** | Tête pointeur de **déploiement** — les slots 4-8 n'ont pas de tête dédiée | 🟠 **OUVERT** — reporté après la mesure de référence (arbitrage utilisateur du 2026-07-29) | **3** | Les ids 4-8 tombent dans la plage des cellules de move (`MOVE_CELL_BASE = 0`) : leurs logits sortent de la **conv 1×1** (`_move_logits`), pas d'une tête dédiée ; `deploy_emb` n'atteint le calcul que par le **conditionnement du tronc**. Ajouter un `deploy_query_net`, jumeau de `choice_query_net` — ce qui oblige à lire la phase dans la policy. Élément `L1` du lot §0.48 ; `L11` (`N_DEPLOY_SLOTS`) à trancher **avant**. Détail → §0.44. |
| **§0.48** | Inventaire des chantiers qui cassent un contrat + **périmètre du lot de ré-entraînement** | 🟠 **OUVERT** — inventaire rendu, périmètre arbitré : le lot = **`L1` + `L2` + `L6`**, et eux seuls | **4** | ✅ **Le prérequis d'ordre est LEVÉ au 2026-08-02** : les quatre chantiers exigés avant la mesure de référence — rampe de déploiement (§0.46 pt 2), FLY 21.03 (§0.49), bots d'éval (§0.47 É4), 01.07 (§0.50) — sont **tous mergés**. Reste l'arbitrage 2 (réserver la place des règles pas encore implémentées, toute règle rendue vivante changeant `obs_size`). Détail → §0.48. |
| **§0.46** | Résidus du 2026-07-29 | ✅ **CLOSE le 2026-08-03** — les trois points sont livrés | — | ✅ **SOLDÉ le 2026-08-03** (arbitrage : GARDER, sous forme optimisée). Les 4 issues du cache de déploiement deviennent des **compteurs publiés en permanence** (`perf/*`) au lieu de traces invisibles hors `--debug` ; les 37 sites passent par `engine/debug_trace.py` (canaux `W40K_TRACE`, formatage différé) ; garde verrouillée par **21 tests**, dont une **analyse AST** (fichiers découverts par leur import) qui interdit f-string, formatage anticipé et mot-clé. La passe `/simplify` du même jour y a trouvé **un bug** (`flush=True` résiduel → `TypeError` dès que le canal s'allume) et **un verrou qui mentait** (canal `train` hors garde). ⏳ Première mesure : **100 % de reconstruction** du cache de déploiement — signalé, non ouvert. Détail → §0.46. |
| **§0.47** | Relecture T2→T5 du 2026-07-29 — 9 écarts | 🟠 **OUVERT — reste É9 (second siège + second scénario)** ; É5 et É7 ✅ corrigés le 2026-08-02 (É1, É2, É3, É4, É6 ✅ livrés **et mergés** ; **É8 est tombé**) | **6** | **É8 n'a plus d'objet** : `ai/analyzer.py` ne construit plus aucun chemin de board à la main (il lit `get_board_config()` / `get_board_size()`). **É9 était mal énoncé** : les **3 graines SONT couvertes** (`test_t5_bare_loop.py`, `for seed in (1, 2, 3)`) ; ce qui manque est le **second scénario** et les **2 sièges**. Détail → §0.47. |
| **§0.50** | Non-conformité **01.07** — travail de suite | 🟠 **OUVERT** (la correction moteur, elle, est mergée) | **7** | ✅ **SOLDÉE le 2026-08-02** — les deux résidus sont traités : (1) le contrat de `battle_shocked` est **tranché en lecture STRICTE**, les 7 `get(..., False)` migrés en `require_key` ; (2) la 3ᵉ lecture d'OC du frontend (journal d'événements de `BoardReplay.tsx`) diffère l'instantané moteur au lieu de recompter. Détail → §0.50. |
| **§0.53** | Refonte du panel de bots — les adversaires ignoraient la condition de victoire | 🟢 **LIVRÉ ET MERGÉ** — plus aucun chantier ouvert (arbitrage du 2026-08-02) | — (à lire avant d'interpréter tout win-rate) | 🟢 **ARBITRAGE UTILISATEUR DU 2026-08-02 — (a) et (b) SONT SANS OBJET JUSQU'À LA DÉMO MÉTIER** : le travail porte sur **2 rosters seulement**, donc ni les matrices de matchups par roster ni le recalibrage des seuils de gate ne sont d'actualité. **Ne pas les re-signaler comme des chantiers ouverts.** Reste vrai et à retenir : (c) **aucun win-rate antérieur au 2026-07-30 n'est comparable** à un win-rate postérieur. ⏳ Le panel a **encore évolué depuis** : un **cinquième bot `ValueTradeBot`** a été ajouté, `bot_eval_weights` = `control` 0.40 / `value_trade`, `adaptive`, `greedy`, `defensive` 0.15 / `tactical` 0. Détail → §0.53 (en §0hist). |
| **§0.19** | Revérifier T1→T5 et la section 9 ligne à ligne | ⏳ **PARTIEL** | continu | T1 soldé (§0.19.1→§0.19.3) ; section 9 auditée le 2026-07-24 (→ [§9.0](V11_phaseA.md#s9.0)) ; **T2→T5 relus le 2026-07-29** — les écarts vivent en **[§0.47](#s0.47)**, pas ici. Reste ouvert : les ✅ de T2→T5 ne sont revérifiés que **par LECTURE** (aucune exécution), et la conformité littérale de T2 est indécidable. ⚠️ Sa **section** est restée en §0hist pour ne pas casser ses sous-ancres `§0.19.1`→`§0.19.3`. |

✅ **Contrôle de conformité du 2026-08-02** (vérification par lecture, PAS une livraison —
aucune ligne de code touchée) :
- `obs_size` : `ObservationBuilder.SQUAD_OBS_SIZE_TARGET` = **20828**, et les **7** profils de
  `config/agents/ArmageddonAgent/ArmageddonAgent_training_config.json` portent **20828**
  (`x1_long` **et `x1_selfplay`** ajoutés depuis la relecture du 2026-07-29 ; cf. §0.59).
- `macro_intents.TOTAL_ACTION_SIZE` = **1107** ; `DEPLOY_SLOTS` = ids **4..8** ;
  `spatial_grid.GRID_CHANNELS` = **9** ; `MOVE_CELL_BASE` = 0 / `MOVE_CELL_COUNT` = 1024.
- `raw_action_int % len(options)` : **absent du code vif** (ne subsiste que dans des commentaires
  historiques) — conforme à §0.42.
- `pointer_policy` : `query_net`, `charge_query_net`, `fight_query_net`, `choice_query_net`
  présents ; `action_decoder` décode bien `target_slot` pour la charge et la mêlée (§0.41, §0.43).
- **§0.44 TOUJOURS CONFIRMÉE dans le code** : `deploy_emb` sort de `deploy_cand_encoder` et n'entre
  QUE dans le tronc (concat) — aucune tête ne le lit ; les logits des ids **4-8** viennent bien de
  `_move_logits` (conv 1×1). Aucun `deploy_query_net`.
- **§0.40** : les 5 points sont dans le code vif (`get_deployment_active_unit` qui lève,
  `squad_grid_anchor`, filtre `on_battlefield`, `open_deploy_slot_count` partagé,
  `deployment_slot_candidates`, purge du cache).
- `ai/scenario_manager.py` **absent** (§0.45) ; `_attack_sequence_rng` : **zéro occurrence**
  (§0.38) ; `get_best_enemy_*` : plus aucune définition (§0.46 pt 1).
- ✅ **Somme des formes VÉRIFIÉE PAR EXÉCUTION le 2026-08-02** (elle était jusque-là la seule
  ligne déduite par lecture) : `sum(prod(shape))` sur les **20** clés de `squad_obs_shapes()`,
  grille exclue, = **20828** — égale à `SQUAD_OBS_SIZE_TARGET`.
- ⚠️ **Non revérifié le 2026-08-02** : les suites de tests (la vérification large appartient à
  l'utilisateur).

🟢 **TRANCHÉ le 2026-07-28 soir (arbitrage utilisateur) : `bot_eval_freq = 2000` ASSUMÉ**, pour
la **granularité des courbes de métriques**. La décision « 4000 » de §0.14 est **annulée** ;
HEAD (`x1: 2000`) et décision sont alignés — **revérifié le 2026-08-02**, toujours à 2000.
Conséquence acceptée en connaissance de cause : les évals des marqueurs
< `save_best_min_episodes` (10 000) ne peuvent sauvegarder aucun modèle — coût = du temps d'éval
« pour les courbes », aucune perte de modèle.

⚠️ **Cette décision vaut pour `x1` SEUL — ne pas la lire comme un réglage global** (relevé le
2026-08-02). Les profils longs sont calibrés à part : évaluer tous les 2 000 épisodes sur un run de
200 000 coûterait plus cher que l'entraînement lui-même, et c'est leur mesure FINALE qui est le
livrable, donc sa précision. Le verrou est
`tests/unit/ai/test_schedule_decay_fraction.py::test_x1_long_is_x1_recalibrated_for_long_runs`.

| Clé | `x1` (décision ci-dessus) | `x1_long` / `x1_selfplay` (HEAD) | Pourquoi l'écart |
|---|---|---|---|
| `bot_eval_freq` | **2000** (ancienne décision §0.14 : ~~4000~~) | **10000** | 20 évals sur 200 000 ép. ; à 5 000, les 40 évals coûteraient ~8 h 30 contre ~5 h 30 d'entraînement. |
| `bot_eval_final` | 100 | **600** | Erreur-type d'un win-rate ~0,5 : **5,0 points** à 100 ép./bot (IC95 ±9,8), **2,0** à 600 (IC95 ±4,0). Coût borné, payé une fois (~1 h 20). |
| `bot_eval_task_timeout_seconds` | 3600 | **7200** | Le timeout porte sur UN task ; à 600 ép./bot un task joue 150 épisodes au lieu de 25. 3600 s ne laisserait que 24 s/épisode contre 17 s **mesurées** sur parties dégénérées (§0.14). |
| `bot_eval_intermediate` | 100 | 100 | Les évals intermédiaires sont du **monitoring** répété 20 fois, pas la mesure. |

Les clés `perception_radius` / `max_nearby_units` / `max_valid_targets` ont été **retirées de tous
les profils** le 2026-07-28 — elles n'alimentaient que le pipeline mono-figurine supprimé le même
jour, plus aucun code ne les lit.

⚠️ **Avant de vous appuyer sur une affirmation de ce document, lire §0bis** — en particulier la
réserve de méthode sur le document lui-même et la règle de périmètre `ArmageddonAgent`. **Mise à
jour 2026-07-29** : la section 9 a été auditée le 2026-07-24 ([§9.0](V11_phaseA.md#s9.0)) et
**T2→T5 ont été relus le 2026-07-29 — 9 écarts, verdicts et réserves en [§0.47](#s0.47)** ; cette
relecture s'est faite **par lecture seule, sans aucune exécution**, elle ne vaut donc pas
mutation-test.

<a id="s0.61"></a>
### 0.61 Le garde ANTI-RUNAWAY était muet, et son compteur d'épisodes divergeait — ✅ CORRIGÉ (2026-08-03)

**Suite de [§0.58](#s0.58)**, relevée en revue de code puis tranchée avec l'utilisateur le
2026-08-03. Le moteur coupe un épisode qui dépasse `max_steps_per_turn × marge × max_turns`
(`w40k_core._get_episode_step_limit`). Ce n'est **pas** une fin de partie : une partie normale se
termine sur la limite de tours (`terminated`). Une troncature est le symptôme d'une **boucle**.

**Deux défauts, une seule cause — `truncated` n'est pas `terminated`.**

1. **Le diagnostic était jeté.** Le moteur assemblait déjà tout ce qu'il faut pour reproduire
   (tour, phase, scénario, joueur, sous-phase de mêlée, unité active, tailles des trois pools,
   `shoot_debug`, dernière action) — puis l'envoyait dans un `print` du **worker**, noyé dans la
   console à `n_envs=48` et perdu au scroll, et dans `add_debug_log`, **no-op** hors `debug_mode`
   et de toute façon local au process. Un run de 47 h pouvait en produire des centaines sans que
   personne le sache : `grep truncation_reason ai/` ne rendait **aucun lecteur**.
2. **Le compteur d'épisodes divergeait.** `info["episode"]` n'est posé que sous `terminated`, donc
   `metrics_tracker.episode_count` — celui qui part dans `_run_state.json` — ne comptait pas les
   troncatures, alors que `EpisodeTerminationCallback` arrête le run sur la somme des `dones`,
   troncatures **comprises**. Une reprise repartait donc plus bas qu'elle n'était arrivée : le
   défaut §0.58 qui se reforme par une autre porte.

**ARBITRAGE UTILISATEUR DU 2026-08-03 — pas de `raise`.** Le repli reste (un run de 47 h ne doit
pas mourir sur un épisode), mais il devient **bruyant** : c'est la condition qui le rend légitime.
`info["truncation_debug"]` traverse le VecEnv (un **dict**, dont le message console n'est plus que
le rendu — l'inverse collait une f-string pré-formatée dans un payload censé être machine),
`MetricsCollectionCallback._handle_truncated_episode` le route, `metrics_tracker` publie
`00_critical/t_truncated_episodes` et compte **par raison** (un total agrégé cesserait de répondre
à la question le jour où un second garde apparaît), et
[`ai/truncation_log.py`](../../ai/truncation_log.py) possède le fichier — même découpage que
`run_state.py` pour `_run_state.json` : le tracker garde la métrique, pas le cycle de vie du
fichier. `print_truncation_summary` donne le compte, la ventilation et le chemin **en fin de
run**, dans le `finally` des **deux** chemins d'entraînement, donc aussi sur interruption et sur
échec — les moments où l'on veut justement savoir si le moteur bouclait. **Un zéro s'affiche
aussi** : « aucune troncature » est un résultat, pas une absence de message.

Le journal vit dans `log_dir`, qui porte l'agent et le profil mais **pas** le run (« continuous
TensorBoard graphs across runs ») : il TRAVERSE les runs, donc chaque ligne porte `run`, sans quoi
deux entraînements successifs seraient indiscernables (`num_timesteps` repart de zéro à chaque
`--new`). Il est **borné à 500 lignes** — et la borne le dit dans le bilan plutôt que de tronquer
en douce le journal des troncatures.

**L'ÉVALUATION comptait aussi, et personne ne la regardait** (troisième et quatrième tours de
revue, 2026-08-03).
Les évals de gating et le holdout final tournent dans des **process workers**
(`ai/bot_evaluation.py`) qui ne passent pas par `MetricsCollectionCallback`. Le moteur pose
`winner = -1` sur une troncature : elle s'y comptait donc en **NUL** et n'existait nulle part
ailleurs. Une boucle ne se reproduisant qu'en éval (`deterministic=True`, rosters du holdout)
faisait ainsi terminer le run sur « ✅ Troncatures : 0 » — **un feu vert faux, exactement ce que
cette entrée existe pour fermer**. Le worker relève désormais ses troncatures et les remonte avec
son résultat de tâche (seul canal qui traverse la frontière de process) ;
`BotEvaluationCallback._evaluate_against_bots` les route, là où les résultats sont **produits** —
et non dans `_apply_eval_results`, appelé directement par les tests de gating, dont les doublures
n'ont aucune raison de porter une route de journalisation. Les comptes sont **ventilés par portée**
(`entraînement` / `éval`) : les deux boucles ne se cherchent pas au même endroit, un total unique
le cacherait. Il y a **quatre** producteurs de résultats d'éval et le même oubli s'est produit
trois fois : `test_every_eval_producer_routes_its_truncations` parcourt l'AST de `ai/train.py` et
`ai/training_callbacks.py` et exige que toute fonction appelant `evaluate_against_bots` route ses
troncatures — la seule exception, `main` sous `--test-only`, est déclarée avec sa raison. Le
comptage et l'écriture se font **sous verrou** : l'éval de gating tourne sur le thread `bot-eval`,
l'entraînement sur le thread principal, et la borne du journal est un lire-modifier-écrire. Une troncature d'éval n'avance **pas** `episode_count` — ce n'est pas un épisode joué
par le modèle en apprentissage, et ce compteur-là est celui qui part dans `_run_state.json`.

**Le discriminant est le signal GYM, pas une clé du moteur** (deux tours de revue de code le
2026-08-03, la première version était fausse et la deuxième fragile). Le `Monitor` de SB3 pose
`info["episode"]` sur `terminated` **OU** `truncated` — vérifié en **exécutant** `Monitor`, pas
déduit de sa doc — et tout le chemin d'entraînement est Monitor-wrappé. Discriminer sur
`'episode' in info` rendait donc la branche des troncatures **inatteignable** (`truncations.jsonl`
jamais écrit, bilan toujours à zéro) **et** envoyait l'épisode tronqué dans `_handle_episode_end`,
qui exige `deployment_mode` et `tactical_data` — deux clés que le moteur ne pose que sous
`terminated`. Une troncature **tuait le run** sur une `ConfigurationError`.
Discriminer sur `truncation_reason` corrigeait le symptôme mais laissait le trou ouvert pour une
troncature venue d'ailleurs que du moteur (un wrapper `TimeLimit` ajouté un jour), qui n'aurait
pas cette clé. Le discriminant est donc `info["TimeLimit.truncated"]`, que les **deux** VecEnv de
SB3 posent (`truncated and not terminated`, vérifié dans leur source) : les deux branches
s'excluent par construction, et une troncature sans payload moteur **lève** au lieu d'être
silencieusement re-routée.

**Le plafond de boucle du worker d'éval — une FAUSSE alerte, corrigée** (quatrième puis cinquième
tour de revue, 2026-08-03). Un tour de revue a signalé que la boucle du worker s'arrête à une
constante du profil (`max_turns * 400` = 2000) alors que le garde moteur dérive du roster (2268
pour les 54 figurines de référence), donc qu'elle sortirait avant lui dès 48 figurines : aucun
diagnostic, `winner` à `None`, épisode porté en défaite. **Le raisonnement était inversé sur les
unités**, et le tour suivant l'a relevé. Un step gym vaut PLUSIEURS steps moteur (tour du bot,
WAIT forcés — cf. `BotControlledEnv.step`) : **mesuré à 1,3–1,4 sur ce dépôt**, donc le compteur du
moteur atteint son plafond en premier quelle que soit la taille du roster. L'ajustement introduit
au tour précédent a été **retiré** : c'était du code pour un scénario qui n'existe pas. La relation
qui le garantit est désormais mesurée par `test_one_gym_step_is_at_least_one_engine_step`, sur le
VRAI wrapper — la première version verrouillait la prémisse inverse et passait uniquement parce que
sa doublure avançait 1:1.

Ce qui RESTE de ce tour, et qui tient : quand le backstop tire pour de bon — durée illimitée, où
`_get_episode_step_limit` ne rend aucun plafond — il **trace** (`reason: eval_loop_cap`) et compte
un NUL. Auparavant, `winner is None` tombait dans le `else` du comptage : une partie qui n'a pas
fini était portée au débit du modèle et l'incident n'existait nulle part. Ses clés de pas sont
`gym_steps`/`gym_step_limit` et non `steps`/`step_limit` : ces deux-là portent des steps MOTEUR
dans les lignes `episode_steps_limit` du même journal, et un journal fait pour être relu ne peut
pas nommer pareil deux unités différentes.

**Le journal crée son dossier.** S'en remettre au `SummaryWriter` ne tenait pas : le mode « éval
seule » construit un `TruncationLog` **sans writer**, depuis le `tensorboard_log` du modèle —
dossier purgé, ou jamais créé pour un modèle copié d'ailleurs. La première troncature levait
`FileNotFoundError` au milieu de `record_eval_batch` et faisait échouer l'évaluation **avant**
l'impression du score : perdre la mesure à cause de sa trace. Même raisonnement pour toute
`OSError` d'écriture (disque plein, droits, montage disparu) : la LIGNE est perdue, pas
l'évaluation. Ce n'est pas un repli silencieux — le compte reste juste (il est pris avant
l'écriture) et le bilan **annonce** les lignes perdues avec leur cause.

**Ce qui n'entre PAS dans les courbes.** Un épisode tronqué n'a ni reward ni longueur exploitables :
ni `game_critical/episode_reward`, ni `episode_length`, ni win rate, et son accumulateur
d'observations est remis à zéro **sans être publié**. Il compte dans `episode_count`, et là
seulement — parce que c'est ce compteur qui est persisté et que le run s'arrête dessus.

**Verrous** : [`tests/unit/ai/test_truncated_episodes.py`](../../tests/unit/ai/test_truncated_episodes.py)
(10 tests : le moteur publie les 16 clés du diagnostic sur une troncature **construite** — plafond
abaissé, pas une graine espérée ; le vrai `Monitor` de SB3 est **exécuté** pour établir qu'il
estampille `episode` sur une troncature, fait dont dépend l'ordre des branches ; `_on_step` route
une troncature avec un `info` de la forme que la production produit — les DEUX clés ; le compteur
avance et les courbes de jeu ne reçoivent rien ; le bilan donne compte et chemin, zéro compris ;
`--new --append` refusé en **sous-process** sur le vrai point d'entrée ; la portée ÉVAL : le
worker relève la troncature qu'il rencontre, les quatre producteurs la routent, `episode_count`
ne bouge pas, et le bilan sépare les deux portées).
**Contre-épreuve faite** : diagnostic retiré du moteur → ROUGE ; `episode_count` non incrémenté →
2 ROUGES ; branche de `_on_step` supprimée → ROUGE ; **discriminant remis sur `episode`** → ROUGE ;
marqueur `run` retiré → ROUGE ; `shoot_debug` retiré du moteur → ROUGE ; routage d'éval supprimé →
ROUGE ; routage du holdout FINAL supprimé → ROUGE ; collecte du worker d'éval supprimée → ROUGE ;
`episode_count` avancé aussi par l'éval → ROUGE ; verrou de concurrence retiré → ROUGE ;
backstop ne traçant plus → ROUGE ; `makedirs` du journal retiré → ROUGE ; `OSError`
d'écriture laissée remonter → ROUGE ; clés `gym_*` renommées en `steps`/`step_limit` → ROUGE ;
refus CLI
supprimé → ROUGE. Tous rétablis → verts.

⚠️ **Trois verrous VERTS À TORT** dans cette entrée. Deux du motif « code testé mais jamais
appelé » — le défaut récurrent de ce dépôt, reformé deux fois dans un seul lot — et un du motif
jumeau « contrôle qui regarde la MAUVAISE chose ».
(1) La première version du verrou de routage fabriquait un `info` **sans** la clé `episode` du
Monitor : elle ne pouvait pas voir l'occultation, c'est-à-dire le défaut même qu'elle devait
attraper.
(2) Le premier verrou de la portée éval ne testait que le **routage** : supprimer la collecte dans
le worker le laissait vert. Un test de collecte a été ajouté sur `_eval_worker_task`, avec une
doublure d'env qui porte `get_wrapper_attr` — le contrat gymnasium réellement emprunté par
`sb3_contrib.get_action_masks` — au lieu de le contourner.
(3) Le premier verrou de concurrence observait les **compteurs** : or les deux portées ont des
clés disjointes (`training` / `eval`), elles ne se marchent jamais dessus. Retirer le verrou le
laissait vert. L'état réellement partagé est le **journal** — `written`, `dropped`, le fichier :
`if written >= max_lines` puis `written += 1` est un lire-modifier-écrire, et deux threads
franchissent le garde ensemble. Le test observe donc la BORNE, avec la fenêtre construite (une
ligne dont la sérialisation cède la main), et devient rouge sans le verrou.

<a id="s0.60"></a>
### 0.60 Instrumentation du COÛT — 4 clés d'éval jamais lues (47 Go de workers), temps bloquant, courbes de charge et de participation — ✅ LIVRÉ (2026-08-02)

Là où [§0.56](#s0.56) ferme des angles morts de **comportement**, ces trois-ci portent sur le
**coût** — la famille de défauts qui ne fait échouer aucun test parce qu'elle ne produit pas
d'erreur : **elle consomme**.

**1. Quatre clés `bot_eval_*` vivaient au niveau SUPÉRIEUR de la section de phase**, alors que
toute la chaîne les lit dans `callback_params` (`_resolve_callback_value` côté `train.py`,
`require_key(callback_params, ...)` côté `bot_evaluation.py`). Elles n'étaient donc lues par
personne, en silence : `bot_eval_n_workers` retombait sur le repli
`min(n_envs, n_scenarios × n_bots)` = **24 workers**, quelle que soit la valeur écrite — la passer
de 6 à 2 puis à 1 n'a jamais rien changé.

| Éval isolée, 48 épisodes, sonde RSS | RSS | Durée |
|---|---|---|
| 24 workers (le repli, subi) | **47 Go** | 598 s |
| 4 workers (la valeur écrite, enfin lue) | **9,6 Go** | 349 s |

Moins de workers est donc aussi **42 % plus rapide** : la VM passait son temps à swapper. Les trois
lectures par `.get()` à défaut silencieux sont remplacées par une fabrique unique,
`validate_bot_eval_worker_params`, appelée par `setup_callbacks` **au démarrage** et non plus au
premier marqueur d'évaluation — un réglage faux échoue maintenant à la seconde 0, pas après des
heures.

> ⚠️ **Ce défaut est le jumeau exact de [§0.33](#s0.33)** (l'autre moitié du même correctif) : une
> clé de configuration **écrite mais jamais lue** ne se voit dans AUCUNE sortie. La leçon vaut au-delà
> de l'éval : toute clé dont la position dans le JSON n'est pas verrouillée par une lecture stricte
> est un réglage décoratif en puissance.

**2. `blocking_eval_seconds`** ne cumule plus que le temps où la boucle d'entraînement est
**réellement figée**. Il incluait auparavant du temps recouvert par l'entraînement, ce qui faisait
afficher à la barre de progression des durées d'épisode **négatives**.

**3. Six courbes comptées CÔTÉ MOTEUR** (elles n'existaient dans aucune sortie) : charges
**tentées** et **réussies**, pour l'agent ET pour le bot (`02_combat/m_charge_attempts`,
`o_charge_attempts_bot`, …), plus la **participation par phase**. `game_tactical/charge_rate` a été
**retiré** dans la même foulée : son dénominateur ne mesurait pas les occasions de charger. La
charge n'a délibérément **pas** de taux de participation — « avoir eu l'occasion de charger » n'est
pas décidable sans rejouer le tour ; `m_charge_attempts` et sa colonne adverse répondent sans cette
ambiguïté.

<a id="s0.59"></a>
### 0.59 Régime d'entraînement en DEUX PHASES — `decay_fraction` et le profil `x1_selfplay` — 🟠 OUVERT (livré, JAMAIS EXÉCUTÉ) (2026-08-02)

Deux changements de **régime** livrés le 2026-08-02, tous deux **non mesurés**. Ils ne cassent aucun
contrat d'observation (`obs_size` inchangé à 20828) : ce sont des réglages de run, pas des
changements d'architecture.

**1. `decay_fraction` — les rampes s'achèvent AVANT la fin du run.** `ramp_episode_span` /
`schedule_progress` (`ai/training_callbacks.py`) font qu'une rampe se déroule intégralement sur
`total_episodes × decay_fraction`, puis tient sa valeur d'arrivée. Sans lui, un run de 200 000
épisodes garde une entropie d'exploration élevée jusqu'au **dernier** épisode et ne consolide
jamais. Valeurs à HEAD : `x1` = **1.0** (comportement d'avant, inchangé) ; `x1_long` et
`x1_selfplay` = **0.4** pour `ent_coef` (rampe achevée à 80 000 sur 200 000) et **0.7** pour
`learning_rate` (achevée à 140 000). La borne est stricte : `decay_fraction ∉ ]0.0, 1.0]` **lève**.

**2. Le profil `x1_selfplay` — une PHASE 2, lancée en `--append` sur le modèle de phase 1.** Un
snapshot **figé** du modèle lui-même remplace le bot sur une fraction des épisodes :

| Clé `opponent_mix` | Valeur | Raison d'être |
|---|---|---|
| `self_play_ratio_start` → `_end` | **0.0 → 0.5** | Démarrage à 100 % bots (l'agent ne sait pas encore ce qu'est un adversaire non scripté), arrivée à moitié-moitié. **Pas 1.0** : l'évaluation note *vs bots*, et un agent qui ne joue plus que contre lui-même dérive vers un équilibre local qu'aucun bot ne récompense — la moitié restante **ancre la mesure**. |
| `warmup_episodes` | 5 000 (globaux) | Le temps que le run se stabilise après le changement de régime. |
| `snapshot_update_freq_episodes` | 5 000 | Trop rapide, l'agent poursuit son ombre et les deux dérivent ensemble ; trop lent, il bat un fantoche périmé. Soit ~20 adversaires successifs sur la phase. |
| `self_play_deterministic` | `false` | Un adversaire déterministe s'exploite par mémorisation. |

Les budgets sont **globaux** et ramenés au budget d'UN environnement par le wrapper — c'est
exactement le piège de [§0.57](#s0.57), et la raison pour laquelle ce profil n'aurait pas pu
fonctionner avant lui. Le câblage `self_play_*` de `BotControlledEnv` passe par une source unique,
`build_self_play_kwargs` : il était auparavant recopié à la main sur chaque site de construction et
les branches mono-env l'**omettaient**, donc un `opponent_mix.enabled: true` y était ignoré **en
silence**.

**Ce qui reste ouvert** :
- ⚠️ **Aucun run de phase 2 n'a jamais tourné.** Le `snapshot_model_path`
  (`ai/models/ArmageddonAgent/selfplay_snapshot.zip`) n'existe pas encore.
- `opponent_mix.enabled: true` **lève** hors du chemin de rotation de scénarios (`train.py`, ~l.1970)
  — seul ce chemin republie un snapshot pendant le run. Une phase 2 doit donc être lancée avec une
  rotation de scénarios, jamais en mono-scénario.
- L'interaction avec [§0.58](#s0.58) est **explicitement tranchée dans la config** et mérite d'être
  relue avant tout lancement : les rampes de **régime** (`learning_rate`, `ent_coef`,
  `opponent_mix`) comptent depuis CE run, tandis que le **compteur d'épisodes** et la **rampe de
  déploiement** CONTINUENT (compétence acquise, état persisté par `ai/run_state.py`).

<a id="s0.58"></a>
### 0.58 Les rampes par-épisode REDÉMARRAIENT à chaque reprise — la rampe de déploiement n'atteignait jamais son régime — ✅ CORRIGÉ (2026-08-02)

**Suite directe de [§0.57](#s0.57)** : une fois la rampe réparée, elle est repartie de sa valeur de
DÉPART à chaque fois que les environnements étaient reconstruits — `--append`, `--resume-from`, et
chaque chunk de curriculum. Cause : `W40KEngine.episode_number` naît à 0 et **rien ne survivait au
processus**. Le `.zip` ne persiste que `num_timesteps`.

**Une seule rampe doit reprendre** — celle du déploiement (voir l'arbitrage « DEUX NATURES DE
RAMPE » plus bas : `learning_rate`, `ent_coef` et le self-play comptent depuis CE run, et c'est
voulu). L'effet est de même nature que §0.57 : un run repris **ne finit jamais** à
`active_ratio_end`, donc l'agent est noté sur des parties à déployer après un entraînement qui n'a
jamais atteint le régime prévu. Le défaut est **antérieur** à §0.57 — mais tant que la rampe
n'avançait pas, il était invisible.

**Le compteur est COMPTÉ, pas déduit.** [`ai/run_state.py`](../../ai/run_state.py) persiste le
nombre d'épisodes joués dans un fichier compagnon du `.zip` (`<stem>_run_state.json`, même patron
que les stats VecNormalize : un nom par modèle, écriture atomique). Il vient de la somme des `dones`
du VecEnv, via le tracker de métriques. **Ne pas le dériver de `num_timesteps`** : la longueur d'un
épisode varie du simple au triple selon le scénario et l'issue, la conversion produirait un chiffre
inventé qui a l'air juste.

**Écrit partout où un modèle reprenable est sauvé** : sauvegarde finale, checkpoints périodiques,
sauvegarde d'interruption (Ctrl-C), et promotion du meilleur modèle robuste en sortie canonique.
Il **suit** le modèle quand on le déplace et **part avec lui** quand on le supprime — un
`_run_state.json` orphelin serait relu par un futur modèle de même nom.

**Un modèle est désormais un JEU de fichiers, pas un fichier** :
[`ai/model_artifacts.py`](../../ai/model_artifacts.py) énumère, copie et supprime le `.zip` avec
ses deux compagnons (`_vec_normalize.pkl`, `_run_state.json`). Cette liste était recopiée à la main
sur cinq sites — énumération canonique, rotation des checkpoints, promotion `--resume-from`, copie
du meilleur robuste, suppression d'un modèle périmé — chacun avec sa propre politique sur les
fichiers absents ; ajouter le troisième fichier a demandé de retrouver les cinq. La dérivation du
chemin d'un compagnon, elle, vit dans [`ai/companion_paths.py`](../../ai/companion_paths.py) : elle
existait en trois exemplaires.

**ARBITRAGE UTILISATEUR DU 2026-08-02 — pas de compatibilité pour les anciens modèles.** Reprendre
un `.zip` dépourvu de son état de run **lève**, avec le message qui dit de repartir en `--new`.
Aucun avertissement suivi d'un compteur remis à 0 en douce : c'est exactement le silence que §0.57
et cette entrée existent pour fermer. Justification utilisateur : le parc de modèles est de toute
façon obsolète (changement d'observation en cours).

**Ce qu'un compteur qui reprend oblige à corriger ailleurs** (relecture adverse du 2026-08-02) :
le **curriculum** doit partir du compte déjà joué (sinon sa garde d'évaluation se désynchronise au
premier chunk, puis le suivant rembobine le compteur persisté) ; la **barre de progression** doit
ajouter l'offset des DEUX côtés (sinon 1000 % affichés et un reste-à-faire négatif, donc une ETA
absurde) ; et `--append` **sans modèle existant** n'est pas une reprise — les trois chemins créent
alors un modèle neuf, exiger un état de run y ferait échouer le premier entraînement d'un agent.

**Les deux boucles d'entraînement le supportent.** `train_with_scenario_rotation` **et**
`create_model`/`create_multi_agent_model` + `train_model` : la seconde écrivait l'état de run sans
jamais le relire, donc son `--append` restait muet — et son compteur, non initialisé, ÉCRASAIT le
cumul du modèle par le compte du seul run courant (un `--append` de 10 000 épisodes sur un modèle
de 200 000 réécrivait 10 000). Relevé en relecture adverse le 2026-08-02.

**DEUX NATURES DE RAMPE, DEUX ORIGINES** (arbitrage utilisateur du 2026-08-02). Toutes ne doivent
pas reprendre :

| Rampe | Compte depuis | Pourquoi |
|---|---|---|
| `learning_rate`, `ent_coef` | **ce run** | c'est le RÉGIME d'entraînement, déclaré par le profil qu'on lance |
| `opponent_mix` (self-play) | **ce run** | une introduction progressive n'a de sens que dans la phase qui l'introduit |
| déploiement, `deployment_random_mix` | **la vie du modèle** | c'est une COMPÉTENCE acquise : la phase suivante démarre au niveau atteint |
| compteur d'épisodes | **la vie du modèle** | axe TensorBoard, ETA, et il alimente la ligne du dessus |

Concrètement : `training_episode_start_index` (converti en index PAR ENVIRONNEMENT via
`episodes_per_env`) ne va **qu'au moteur** ; le wrapper de self-play part de zéro, et les callbacks
de LR/entropie aussi. Sans cette distinction, une phase 2 lancée en `--append` verrait son
`learning_rate.initial` **jamais appliqué** (progression déjà saturée → collée à `final`) et son
warmup de self-play **sauté** (ratio final dès le premier épisode).

**Ce que ça remplace : le driver de curriculum, supprimé** (~630 lignes). L'enchaînement
automatique des phases n'est pas voulu (arbitrage utilisateur du 2026-08-02) : une phase 2 est un
**profil indépendant** lancé en `--append` sur le même agent, avec son propre régime — le chemin du
modèle dépend de l'agent, pas du profil. Le mécanisme existait déjà côté normalisation
(`vec_normalize.reset_on_curriculum`, porté par `x5`). Sont partis avec le driver : la branche CLI
`--scenario phaseX`, la porte de phase, le découpage en chunks, les offsets de phase des callbacks
et l'affichage de progression par phase. Aucun profil ne portait de bloc `curriculum` : le chemin
était **inatteignable**.

**Deux suites de ce compteur, relevées en revue de code le 2026-08-02 et corrigées.**
(1) `--new` ne gagnait pas sur `--append`. Ce sont deux `store_true` **indépendants** et rien ne
les rend exclusifs : `--new --append` faisait démarrer un modèle NEUF sur le compte d'épisodes de
l'ancien — rampe de déploiement à `active_ratio_end` pour des poids initialisés au hasard. La règle
vit maintenant dans **`prepare_run_artifacts`**, le prologue commun aux **trois** chemins
d'entraînement (`build_agent_model_path` → `makedirs` → archivage `--new` → offset → index
par-environnement), qui passe `append_training and not new_model` à `resume_episode_offset`.
Volontairement **pas** un ordre d'appels : un ordre ne se vérifie pas, il se re-casse au refactor
suivant — et ce prologue, recopié à la main sur trois sites, avait **déjà divergé trois fois** (un
`makedirs` enfermé dans le `if new_model` donc jamais joué en `--append`, un `makedirs` en triple
exemplaire, une annonce de reprise conditionnée tantôt par `append_training` tantôt par l'offset).
Les deux constructeurs **retournent** désormais l'offset : `main()` le relisait sur disque une
seconde fois, soit deux lectures par run devant rester d'accord.
(1 bis) **Les deux drapeaux sont désormais refusés ensemble** au lancement (arbitrage utilisateur
du 2026-08-03) : une commande dont un drapeau ne sert à rien est une faute de frappe, pas une
intention. Le helper garde la règle pour les appels programmatiques, que le CLI n'atteint pas.
(2) `final_summary_target_episodes` recevait le seul budget du run alors que
`metrics_tracker.episode_count` est désormais **cumulatif** : sur un `--append`, la garde de
`_on_training_end` était franchie dès le 1er épisode et le résumé « final » de gating s'imprimait
sur un run interrompu, indiscernable d'un run terminé. La cible est maintenant
`global_episode_offset + total_eps`, même forme que `target_episode_count`.

**Verrous** : [`tests/unit/ai/test_run_state.py`](../../tests/unit/ai/test_run_state.py) (dont la
rampe moteur de bout en bout : index 0 → 0.0, index 50 → 0.5, index 100 → 1.0 ; `--new` gagne sur
`--append` **archivage neutralisé**, sans quoi le test resterait vert en observant l'effet de bord
de l'archivage ; les trois chemins appellent bien le prologue ; la cible cumulative du résumé final
ET l'absence d'offset sur les deux rampes de régime) et
`test_resume_from_checkpoint.py` étendu (l'état suit le checkpoint promu, le modèle écarté garde le
sien, un checkpoint sans état est refusé **avant toute modification du disque**, les trois artefacts
partent ensemble à la rotation). Le refus tardif était un défaut réel : placé après la mise à
l'écart, il laissait l'agent sans `model_<agent>.zip`.
**Contre-épreuve faite** : index de départ ignoré + état manquant traité comme 0 → 2 tests ROUGES ;
`and not new_model` retiré → ROUGE ; `makedirs` renfermé dans le `if new_model` → 2 ROUGES ; un
chemin qui rejoue le prologue à la main → ROUGE ; cible du résumé final ramenée au seul budget du
run → ROUGE ; `initial_episode_count` remis sur la rampe LR → ROUGE. Tous rétablis → verts.
⚠️ Première version du verrou `--new --append` **VERTE À TORT** : elle jouait l'archivage en même
temps que la règle, donc l'effet de bord de l'archivage la satisfaisait à lui seul.

<a id="s0.57"></a>
### 0.57 Les rampes par-épisode du MOTEUR divisaient un compteur LOCAL par le total GLOBAL — la rampe de déploiement est restée figée sur tous les runs vectorisés — ✅ CORRIGÉ (2026-08-02)

**Mesure, pas déduction.** Run `x1_long` en cours (`n_envs` **48**, `total_episodes` **200 000**),
relevé dans les événements TensorBoard au step **78 477** : `00_critical/s_deploy_active_share` =
**0.3040**, soit exactement `active_ratio_start` (**0.3**). La rampe 0.3 → 0.8 attendait **0.496**.

**Cause.** `W40KEngine.episode_number` — et `game_state["episode_number"]` qui en dérive — est un
compteur **par environnement** : un worker `SubprocVecEnv` vit dans son propre processus et ne voit
aucun compteur global (`engine/w40k_core.py:705` init, `:1185` incrément dans `reset`). Les deux
rampes par-épisode du moteur divisaient pourtant ce compteur local par `total_episodes`, qui est
**global** :
- `_configure_deployment_mode_for_episode` (mode `fixed` ↔ `active`) ;
- `_configure_deployment_random_mix_for_episode` (randomisation des ACTIONS de déploiement) — **même
  défaut, jumeau confirmé**.

**Troisième site, trouvé au grep et corrigé lui aussi** :
`BotControlledEnv._compute_self_play_ratio_for_episode` ([`ai/env_wrappers.py`](../../ai/env_wrappers.py))
rapportait `self._episode_index` — compteur du wrapper, donc **par worker** — aux budgets GLOBAUX
`opponent_mix.total_episodes` / `warmup_episodes`. **Inerte aujourd'hui** (aucun des six profils ne
porte `opponent_mix`), mais le jour où le self-play est rallumé la rampe serait restée collée à
`self_play_ratio_start`. Correctif : `build_training_opponents` reçoit le `n_envs` **runtime** (celui
déjà résolu par `_resolve_n_envs_for_step_logging`, donc juste même sous `--step`) et le transmet ;
le wrapper convertit les deux bornes en budget par environnement. `n_envs` manquant → `KeyError`.
Au passage, tout le câblage `self_play_*` passe par une **source unique**
(`training_utils.build_self_play_kwargs`, piloté par table) : il était recopié à la main sur 5 sites
de construction, et **3 branches mono-env l'omettaient entièrement** — un `opponent_mix.enabled:
true` y était ignoré EN SILENCE, sans self-play ni message. C'est cette duplication qui avait fait
rater l'ajout de `self_play_n_envs` sur deux sites (relecture adverse du 2026-08-02). Corollaire
découvert en le branchant : `create_model` et `create_multi_agent_model` ne republient JAMAIS de
snapshot de self-play (seul `train_with_scenario_rotation` le fait), donc `opponent_mix` y lève
maintenant une erreur explicite au lieu de lire un fichier absent — ou un snapshot figé d'un run
précédent, adversaire immobile pour tout l'entraînement.

**Résultat complet du grep** (tout site divisant un compteur d'épisodes par un total) : 6 sites, 3
étaient faux (les 3 ci-dessus, corrigés), 3 étaient déjà justes —
`engine/game_state.py:1683`, `ai/training_callbacks.py:352`, et les rampes `learning_rate` /
`ent_coef` (`_EpisodeRampCallback`, `ai/training_callbacks.py:186`). Ces dernières sont saines pour
une raison à noter : elles sont pilotées **par épisode** (et non par timestep), mais leur compteur
vient de la somme des `dones` du VecEnv — il est donc **global**, comme leur dénominateur.

Conséquence : la progression avançait **`n_envs` fois trop lentement**. À 48 envs et 200 000
épisodes, chaque worker n'en joue que ~4 167 ; la rampe aurait eu besoin de **4,8 millions**
d'épisodes globaux pour atteindre son gel. Vérification arithmétique du symptôme : 78 477 / 48 =
1 635 épisodes par env, `p = 0.3 + 0.5 × 1635/199 999` = **0.3041** — la valeur relevée, à 10⁻⁴.

**Ce que le dépôt faisait déjà juste.** Les deux AUTRES rampes par-épisode divisaient, elles, par
`episodes_per_env = ceil(total_episodes / n_envs)` : `engine/game_state.py`
(`roster_pool_schedule`) et `ai/training_callbacks.py`.

**La formule ne vit plus qu'à UN endroit** : [`engine/episode_schedule.py`](../../engine/episode_schedule.py)
(`episodes_per_env`, `ramp_progress`), appelé par les **quatre** consommateurs (les deux rampes du
moteur, la rampe self-play du wrapper, la rampe de rosters du callback). Elle était manuscrite en
quatre exemplaires — deux justes, deux faux : recopier une formule, c'est précisément ce qui a
produit ce défaut. Le POURQUOI (compteur local vs budget global) est écrit là, une fois ; les
consommateurs y renvoient au lieu de le reparaphraser. Les budgets absents ou absurdes lèvent
(`require_positive_int`, ajouté à `shared/data_validation.py` — la garde « entier > 0, `bool` exclu »
était elle aussi recopiée trois fois).

**Choix de conception.** Le moteur ne reçoit pas une progression calculée par l'entraînement (un
worker vectorisé ne peut pas observer le compteur global sans IPC par épisode) : il calcule la
sienne. Mais **les deux termes de la fraction viennent du RUN, pas du profil**, et sont résolus au
même endroit — `ai/train.py::resolve_run_budget` :

| Terme | Intention du JSON | Réalité du run |
|---|---|---|
| `n_envs` | 48 | 1 sous `--step` / `--replay` (`_resolve_n_envs_for_step_logging`) |
| `total_episodes` | 200 000 | `--total-episodes`, ou la longueur de la PHASE en curriculum |

Tout ce qui vit dans le processus (callbacks, budgets d'`opponent_mix`) lit le dict résolu ; les
workers, qui relisent le JSON, reçoivent les valeurs par `make_training_env(n_envs=…)` →
`W40KEngine(training_n_envs=…)`.

**Anti-récidive.** Une fois dans `training_config`, un `n_envs` déclaré et un `n_envs` résolu sont
indiscernables — un site qui oublie de résoudre repartirait en silence sur 48 environnements
imaginaires. Le moteur **refuse donc de ramper** tant que `training_n_envs` ne lui a pas été passé
(`KeyError` explicite). Les 11 constructions de moteur du dépôt sur profil d'entraînement déclarent
désormais leur nombre d'environnements (1 pour tous les chemins sériels : évaluation, replay,
`roster_matchup_stats`, `refactor_fingerprint`, smoke, profilage, tests). `training_n_envs` est en
revanche refusé hors chemin d'entraînement (l'accepter en silence le rendrait inerte).

**Verrou.** `tests/unit/engine/test_deployment_mode_schedule.py` : les 3 tests historiques
n'exerçaient qu'UN environnement avec `total_episodes` = nombre d'épisodes rejoués — le compteur
local ÉTAIT le compteur global, donc ils restaient verts sur le code défectueux. Ajoutés : 4 envs se
partageant 40 épisodes (chacun doit parcourir la rampe entière, contrôle déterministe sur
`p_active`), la reproduction du point de mesure du run (n_envs 48 / 200 000 → 0.496), et l'erreur
explicite sans `n_envs`. **Contre-épreuve faite** : défaut remis → les deux premiers passent ROUGE ;
rétabli → verts. Idem côté self-play : `tests/unit/ai/test_env_wrappers.py`
(`test_self_play_ramp_is_expressed_per_environment` + exigence de `n_envs`), conversion retirée →
ROUGE, rétablie → vert.

**Réglage arbitré dans la foulée (2026-08-02).** Les **six** profils passent à
`freeze_after_progress` **1.0** — le gel à mi-run (plafond effectif 0,55) n'avait de sens que si la
rampe avançait, ce qu'elle ne faisait pas. La rampe atteint donc `active_ratio_end` **0.8** en fin
de run. Les `justification` du JSON, qui décrivaient encore le gel, sont réécrites.

**Ce que ce défaut invalide.** Voir §0.29 (formule) et §0.46 point 2 : la rampe y est présentée
comme alignant entraînement et évaluation. Elle n'a **jamais** rampé sur un run vectorisé — tous les
runs `n_envs=48` ont entraîné à `active_ratio_start` constant (0.0 avant le 2026-08-01, 0.3 depuis).
Les agents antérieurs ont donc vu **beaucoup moins de déploiement actif** qu'annoncé, alors que
l'évaluation en impose TOUJOURS : l'asymétrie que §0.29 prétend corriger était **toujours là**. Le
même raisonnement vaut pour `deployment_random_mix` (ratio figé à `force_random_ratio_start`).

<a id="s0.56"></a>
### 0.56 Instrumentation — usage par famille d'action + classement bot-contre-bot — ✅ LIVRÉ (2026-08-02)

**Origine.** Deux questions auxquelles le dépôt ne savait pas répondre, découvertes en cherchant
comment livrer le lot `L1 + L2 + L6` ([§0.48](#s0.48)) sans payer un ré-entraînement par tranche.

#### 1. Usage par famille d'action

**Le manque.** `ai/metrics_tracker.py` publiait `valid_actions` / `invalid_actions` **agrégés** :
de quoi savoir si l'agent joue des coups légaux, jamais de quoi savoir **quelle décision il
exerce**. Une dimension d'action jamais choisie (mal masquée, mal observée, jamais préférée) ou
toujours choisie (dégénérée) est un défaut que le win-rate **ne distingue pas** d'un agent
simplement faible.

**Ce que ça change pour le lot.** L'attribution d'une régression ne demande pas des runs séparés,
elle demande des **observables séparés**. Chaque décision ajoutée par une tranche P3 a désormais
sa courbe, donc sa signature de panne : `L1 + L2 + L6` reste livrable **en un seul run** sans
perdre le diagnostic. C'est ce qui rend inutile le « une tranche = un run » que P5 prescrit par
défaut.

**Livré :**
- `engine/macro_intents.action_family(action_int, phase)` + `ACTION_FAMILIES` — le classifieur vit
  dans la **source unique du layout** : le recopier ailleurs le désynchroniserait au premier slot
  ajouté.
- ⚠️ **La phase est un paramètre OBLIGATOIRE, pas un confort** : `DEPLOY_SLOT_BASE = 4` et
  `MOVE_CELL_BASE = 0` se recouvrent, les ids **4-8** sont à la fois les cinq stratégies de
  déploiement et des cellules de move. Sans la phase, **tout déploiement serait compté comme un
  déplacement**. C'est le même recouvrement que [§0.44](#s0.44) doit lever côté policy.
- `engine/w40k_core` capture `pre_action_phase` **avant** exécution (l'action peut faire avancer
  la phase) et ventile dans `episode_tactical_data['action_family_counts']`, à côté des compteurs
  existants, pour le seul camp contrôlé.
- `ai/metrics_tracker` émet `actions/share_<famille>` par épisode.

**Verrous** : `tests/unit/engine/test_action_family_usage.py`, **13 tests** — chaque famille
atteinte, bornes de chaque plage, ids hors espace qui lèvent, action non-déploiement en phase
deployment qui lève, et sur le **chemin de production** : la ventilation couvre exactement
`total_actions` (non nulle), et aucune action n'est classée `deploy_slot` dans un épisode sans
phase de déploiement.
Mutation vérifiée ROUGE : retirer la dépendance à la phase (4-8 toujours `deploy_slot`) ⇒ 5 tests
rouges.
⚠️ **Limite de verrou, assumée et à ne pas oublier** : muter `pre_action_phase` en phase
**post-action** laisse la suite VERTE. Le harnais de test construit le moteur depuis une config
en mémoire, qui démarre toujours en placement **fixe** (`deployment_type` ne vient que d'un
fichier de scénario) : aucune phase de déploiement n'y est jouée, donc pré et post donnent la même
réponse. **Le choix de la phase pré-action n'est donc PAS verrouillé** — il faudrait un test sur
un scénario `deployment_type: active`.

#### 2. Classement bot-contre-bot — `scripts/bot_ranking.py`

**Le manque.** `evaluate_against_bots` exige un **modèle entraîné** comme joueur 1 : la seule
façon de juger un bot était de le faire affronter l'agent. Un bot faible contre un agent fort
donne le même chiffre qu'un bot fort contre un agent faible — **la mesure est circulaire**.
Conséquence directe : [§0.55](#s0.55) était irréalisable. Re-profiler `tactical` sans pouvoir
mesurer sa force revenait à remplacer un holdout trop faible par un holdout de force **inconnue**.

**Livré :**
- `ai/env_wrappers.BotControlledEnv.scripted_action_for_agent_side(bot)` — fait jouer un bot **à
  la place de l'agent**. `_get_bot_action` et `_select_bot_move_action` prennent un acteur
  optionnel : il n'existe toujours qu'**UN SEUL** chemin de décision pour les bots, celui de la
  production. Une seconde implémentation divergerait, et le bot mesuré ne serait plus celui joué
  en évaluation.
- `scripts/bot_ranking.py` — round-robin de chaque bot contre chaque autre sur les scénarios du
  pool, matrice des win-rates, classement, export CSV. Aucun repli : `winner` et
  `controlled_player` en `require_key`, un épisode non terminé **lève** au lieu d'être compté en
  défaite, la randomness vient de `bot_eval_randomness`.

**Vérifié par exécution** (`--bots control,tactical --episodes 1`, pool holdout) : 8 épisodes
joués, matrice et classement produits.

📌 **Piège à ne pas re-diagnostiquer** : la graine d'épisode intègre le nom des **DEUX** bots.
Sans cela, deux appariements différents rejouent la même séquence de tirages et leurs win-rates
se comparent sur des parties corrélées.

⏳ **Signal à confirmer, PAS une conclusion** : sur les 8 épisodes du smoke, le siège « agent » a
perdu **6 fois sur 8**, dans les deux sens d'appariement. À n=8 c'est parfaitement compatible avec
du hasard, mais si l'asymétrie se confirme sur un échantillon sérieux, elle biaiserait **toute**
mesure — l'agent joue toujours ce siège. À vérifier avec `--episodes 20` ou plus.

<a id="s0.55"></a>
### 0.55 Le holdout d'évaluation est DANS l'enveloppe d'entraînement — effet plafond sur le seul adversaire jamais vu — 🟠 OUVERT (2026-08-02)

**Origine.** Relevé en répondant à la question « TacticalBot a-t-il été supprimé ? ». Il ne l'a
pas été (ce sont `AggressiveSmartBot` et `DefensiveSmartBot` qui l'ont été, [§0.53](#s0.53)), et
son câblage de holdout est correct : présent dans le registre, **poids 0.0** dans
`bot_eval_weights`, **absent de `bot_training.ratios`**, et **explicitement exclu** du
`worst_bot_score` qui alimente le gate ([§10.5](V11_eval_strategy.md#s10.5)). Le mécanisme n'est
pas en cause — **le contenu du bot l'est.**

**Le constat.** Les bots vivent dans un plan à deux paramètres depuis [§0.53](#s0.53)
(`config/bot_movement_weights.json`) :

| Bot | `w_objective` | `w_enemy` | Rôle |
|---|---|---|---|
| `control` | 1.0 | 0.1 | entraînement (poids 0.40) |
| `defensive` | 0.7 | −0.5 | entraînement |
| `greedy` | 0.3 | 1.0 | entraînement |
| `value_trade` / `adaptive` | 3 modes chacun | | entraînement |
| **`tactical`** | **0.5** | **0.0** | **HOLDOUT** |

`tactical` tombe **à l'intérieur de l'enveloppe convexe** de ce que l'agent affronte — quelque
part entre `control` et `defensive`, et c'est le seul bot totalement indifférent à l'ennemi. C'est
un `ControlBot` dilué : il ne fait rien qu'un bot d'entraînement ne fasse **mieux**.

**Conséquence mesurée** : `vs_tactical` = **0.95** au run 4, quand `vs_control` valait 0.04. Un
holdout battu 19 fois sur 20 est saturé : il ne discrimine plus rien. **Un holdout intérieur à
l'enveloppe teste l'INTERPOLATION, pas la GÉNÉRALISATION** — c'est la leçon à retenir de cette
entrée, indépendamment du bot concerné.

🟢 **ARBITRAGE UTILISATEUR DU 2026-08-02 — re-profilage validé, à écrire.**
1. **Sortir `tactical` de l'enveloppe.** Piste proposée : `w_objective 0.8 / w_enemy 0.6` — un bot
   qui dispute les objectifs **et** se bat pour eux. Aucun bot d'entraînement n'occupe ce coin
   (`control` est passif au contact, `greedy` ignore les objectifs). Un holdout doit différer
   **en nature**, pas être plus faible en degré. La valeur exacte reste à régler par mesure.
2. **Ajouter le scalaire `vs_tactical` PAR ROSTER.** Aujourd'hui `ai/metrics_tracker.py` émet
   `bot_eval/vs_tactical` (tous rosters confondus) et `bot_eval/faction/<faction>` (le `combined`
   par faction), mais **pas le croisement** — or c'est exactement ce que
   [§10.6](V11_eval_strategy.md#s10.6) demande.

🛠️ **PRÉPARATIFS DU 2026-08-02 — spec prête à appliquer, RIEN N'EST APPLIQUÉ.**
⏳ **Fenêtre d'application** : `config/` est **relu à chaud par les évaluations** du run en cours
(`x1_long`, démarré le 2026-08-02 à 12 h 25). Éditer `bot_movement_weights.json` maintenant
changerait l'adversaire **au milieu** du run et rendrait ses évals intermédiaires incomparables
entre elles. **Tout ce qui suit s'applique entre deux runs, pas pendant.**

**Étape 1 — mesurer AVANT de changer (le point de comparaison n'existe pas encore).**
`scripts/bot_ranking.py --bots control,defensive,greedy,value_trade,adaptive,tactical
--episodes 20` (pool holdout). Sans ce classement de départ, « le nouveau `tactical` est plus
fort » n'est pas une mesure, c'est une intention. Le script ne demande **aucun modèle** (§0.56) :
il tourne donc sans attendre la fin du run — mais il **prend du CPU**, à lancer une fois la machine
libre.
⚠️ Passer `--episodes 20` **et non 1** : le smoke de §0.56 signale un possible biais de siège
(6 défaites sur 8 pour le siège « agent »), qui doit être écarté ou confirmé sur cet échantillon
**avant** de servir de référence.

**Étape 2 — le changement, deux fichiers, aucun autre.**
1. `config/bot_movement_weights.json` : `tactical` passe de `{w_objective 0.5, w_enemy 0.0}` à
   **`{w_objective 0.8, w_enemy 0.6}`** (valeur de départ, à régler par l'étape 3). Sa
   `justification` doit dire ce qui suit, sinon le prochain lecteur la « rééquilibrera » : ce bot
   est **volontairement hors du plan des bots d'entraînement** ; c'est sa raison d'être, pas un
   déséquilibre.
2. `ai/metrics_tracker.py` : ajouter le croisement **bot × faction**, aujourd'hui manquant.
   ⚠️ **La donnée existe déjà, ne pas la recalculer** : `ai/bot_evaluation._compute_faction_scores`
   construit `tally[faction][bot_name] = [wins, total]` à partir de `faction_stats`, puis n'en
   publie que l'agrégat par faction (`log_faction_scores` → `bot_eval/faction/<faction>`). Émettre
   `bot_eval/faction/<faction>/vs_<bot>` depuis **ce même tally** — un second comptage
   divergerait au premier changement de pondération. Un roster = une faction ici (SM, Orks), donc
   « par roster » et « par faction » désignent la même ventilation.

**Étape 3 — régler, puis geler.** Rejouer l'étape 1 avec le `tactical` re-profilé. Cible : un
`tactical` qui **ne se classe pas dernier** face aux bots d'entraînement — un holdout doit être
difficile, pas seulement différent. S'il sort trop fort ou trop faible, régler `w_enemy` (c'est le
paramètre qui le sort de l'enveloppe ; `w_objective` ne fait que le rapprocher de `control`). **Une
fois le chiffre retenu, il est gelé** : c'est la définition du mètre.

**Ce qui N'EST PAS à toucher, vérifié le 2026-08-02** : `tactical` reste à **poids 0.0** dans
`bot_eval_weights`, **absent de `bot_training.ratios`**, **exclu du `worst_bot_score`**. Le
re-profilage change la **force** du holdout, jamais son **statut** — l'y réintroduire d'un cran le
détruirait en tant que holdout.

⚠️ **ORDRE — non négociable** : ce chantier se livre **AVANT** de geler la baseline d'évaluation
et de lancer la mesure de référence. Changer un adversaire d'éval après coup rend toute
comparaison invalide — c'est exactement ce qui a tué la comparabilité du run 4
([§0.47](#s0.47) É4). Il ne casse **aucun** des trois contrats (archi / obs / action) : il ne
coûte donc **aucun** ré-entraînement, il change seulement la règle du mètre.

🟢 **POURQUOI `control` PÈSE 0.40 — raison écrite le 2026-08-02, à ne pas « rééquilibrer ».**
Décision utilisateur, assumée : `ControlBot` est **le bot qui joue le mieux à 40k**, parce qu'il
joue pour **gagner** et non pour détruire — et c'est ce que dit la règle : la victoire se décide
aux VP d'objectifs, les kills ne tranchent qu'à égalité (`determine_winner_with_method`). D'où
`control` 0.40 contre 0.15 aux quatre autres, et 0.0 au holdout. Ce n'est pas un déséquilibre à
corriger, c'est la **pondération de la compétence décisive**.
⚠️ Contrepartie à connaître : 40 % du `combined` dépend d'UN adversaire, donc une stratégie qui
exploiterait une idiosyncrasie de `control` déplacerait 40 % du score. `b_worst_bot_score` est le
garde-fou exact de ce risque — c'est la raison pour laquelle les deux métriques vont **ensemble**
et qu'aucune ne se lit seule.

📌 **DEUX LIMITES DE LECTURE DU COUPLE `combined` / `worst_bot_score`** (constatées le 2026-08-02,
aucune ne le disqualifie) :
1. **`worst_bot_score` peut être une seconde mesure de PERFORMANCE, pas de consistance.** Si le
   minimum tombe toujours sur le même adversaire (au run 4 : `vs_control` à 0.04), les deux
   métriques pointent au même endroit au lieu de se compléter. Le fait se lit directement — les
   scalaires `bot_eval/vs_*` sont tous publiés, et le rapport d'éval de fin de training les
   classe — il suffit d'y regarder avant de conclure qu'un creux du `min` est un défaut de
   consistance.
2. **Un `min` est la statistique la plus bruitée du lot.** Sur ~100 épisodes par bot, le minimum
   de six estimateurs bruités est biaisé vers le bas et varie plus que la moyenne. Un creux isolé
   de `worst_bot_score` est plus probablement du bruit qu'une régression — contrairement à un
   creux de `combined`.

🟢 **SUITE ENVISAGÉE (2026-08-02, non engagée)** : si le `tactical` re-profilé s'avère plus fort
que les bots d'entraînement, il devient le **critère de généralisation** — « battre un adversaire
jamais rencontré ». C'est l'argument le plus fort possible devant un financeur. Condition : il doit
rester **hors de `bot_training.ratios`** et **hors du gate**, sans quoi il cesse d'être un holdout.

📌 **PÉRIMÈTRE DE MESURE — ASSUMÉ, NE PAS LE RE-SIGNALER COMME UN DÉFAUT** (utilisateur,
2026-08-02). Vérifié fichier par fichier : les rosters `holdout_regular` sont **identiques unité
pour unité** aux rosters `training` (SM comme Orks), sur le **même plateau** `44x60x5` et le **même
terrain** `terrain-mc1.json`. Le « holdout de scénarios » n'en est donc pas un — et **c'est
voulu** :
- **rosters fixes** — on joue le contenu de la boîte de base, pas d'autre armée (cf. [§0.15](#s0.15),
  identité déjà tranchée le 2026-07-21) ;
- **diversité d'ADVERSAIRE reportée** — self-play et MCTS viendront **quand l'observation sera
  complète**, pas avant.

⚠️ **Conséquence à garder en tête pour lire les courbes** : `combined` et `worst_bot_score`
mesurent la performance **dans la distribution d'entraînement**, entièrement — mêmes armées, même
terrain, mêmes adversaires. C'est adapté au besoin courant (valider les paramètres), mais **le
`tactical` re-profilé est le SEUL signal hors distribution du dispositif** tant que le self-play
n'est pas là. C'est ce qui fait la valeur du point 1 ci-dessus.

📌 **DIVERGENCE DOC / PRATIQUE, à trancher.** [§10.6](V11_eval_strategy.md#s10.6) écrit que le
critère de succès quantitatif est le **win-rate PAR ROSTER contre `TacticalBot`**. Ce n'est **pas**
le critère réellement utilisé : l'utilisateur suit `00_critical/a_bot_eval_combined` et
`00_critical/b_worst_bot_score` (2026-08-02), qui portent tous deux sur les bots
**d'entraînement** — `tactical` en est exclu par construction. Ces deux métriques ne sont **pas**
saturées (`worst_bot_score` ≈ 0.35 pour un gate à 0.50), donc le critère opérationnel est sain ;
c'est le critère **écrit** qui est en décalage. À réconcilier : soit §10.6 adopte
`combined` + `worst_bot_score` + `0_gap_sm-ork` comme critère quantitatif et rétrograde le holdout
au rang d'indicateur de généralisation, soit le holdout redevient le critère — mais alors il faut
d'abord le désaturer (point 1 ci-dessus). **Les deux voies exigent le re-profilage.**

<a id="s0.44"></a>
### 0.44 Tête pointeur de déploiement — les slots 4-8 n'ont pas de tête dédiée — 🟠 OUVERT, REPORTÉ APRÈS LE RUN 4 (2026-07-29)

**En une phrase.** [§0.40](#s0.40) a donné à l'agent la **description** des 5 candidats de
déploiement ; il lui manque encore de quoi les **comparer** proprement.

**Le constat, vérifié dans le code.** Les ids d'action `4-8` tombent dans la plage des cellules de
move (`MOVE_CELL_BASE = 0`, `MOVE_CELL_COUNT = 1024`). Leurs logits sortent donc de la **conv 1×1
de la carte** (`_move_logits`), aux cellules `(0, 4..8)` de la fenêtre égocentrique — des cellules
qui n'ont aucun rapport avec les hexes candidats. Aucune tête ne lit les embeddings du bloc
`deploy_cand_*` : celui-ci n'atteint la décision que par le **conditionnement du tronc**
(`move_ctx_net`, dont la non-linéarité permet bien de réordonner les cellules entre elles, mais
indirectement).

**Ce qu'il faudrait faire.** Un `deploy_query_net`, jumeau de `choice_query_net` : le tronc émet une
requête, on la produit scalairement contre les 5 embeddings de candidats déjà calculés par
`deploy_cand_encoder`, et ces 5 logits **remplacent** ceux des cellules `4-8`. Le point dur est là :
un même id signifie « cellule de move » en phase move et « slot de déploiement » en déploiement, le
masque seul les distingue aujourd'hui. La policy devrait donc lire la **phase** (le one-hot
`phase_deployment` de `global_bin`) pour choisir laquelle des deux têtes alimente ces colonnes.

**Arbitrage utilisateur du 2026-07-29 : REPORTÉ APRÈS LE RUN 4.** Le bloc d'observation est déjà un
gain net (l'agent ne voyait RIEN de ses candidats auparavant), et ce chantier-ci touche
l'**architecture de la policy** — donc ⛔ **incompatible avec un run en cours** : les workers d'éval
démarrent en `spawn` et ré-importent le code depuis le disque (leçon §0bis, qui a tué les runs 1
et 2). Il n'invalide en revanche PAS `obs_size` : le bloc candidat reste tel quel, seule la tête
change.

**DÉCISION UTILISATEUR DU 2026-07-29 — STRATÉGIE D'APRÈS-RUN : UN SEUL RÉ-ENTRAÎNEMENT POUR TOUS
LES CHANGEMENTS D'ARCHITECTURE OU D'OBSERVATION.** Tout changement qui touche l'**architecture de
la policy** ou le **contrat d'observation** rend le modèle existant **inchargeable** — les workers
d'éval démarrent en `spawn`, reconstruisent l'architecture depuis le code du disque et échouent sur
`load_state_dict` (leçon §0bis, runs 1 et 2) — et force donc un `--new`. Un tel changement livré
seul coûte un ré-entraînement complet **à lui tout seul**. La décision est de **grouper TOUS ces
changements en un seul lot** et de ne payer **qu'UN SEUL** ré-entraînement complet.

Conséquences assumées :

- **(a) Le run 4 en cours devient une MESURE DE RÉFÉRENCE, pas le modèle final.** Il sert de point
  de comparaison pour le lot ; on n'attend pas de lui le modèle livrable.
- **(b) §0.44 n'est plus « le prochain chantier isolé »** : la tête pointeur de déploiement devient
  **un élément du lot**, à livrer avec les autres changements d'architecture/observation, pas avant
  eux. ✅ **Confirmé par l'arbitrage du 2026-07-29** : §0.44 est **dans** le périmètre retenu du
  lot (`L1`, cf. [§0.48](#s0.48)).
- **(c) L'INVENTAIRE EXHAUSTIF exigé avant de lancer le lot est RENDU** : il vit en
  **[§0.48](#s0.48)** (13 chantiers qui cassent un contrat, la liste hors lot, les dépendances),
  et le **périmètre du lot y est FIXÉ** — `L1` (cette entrée) + `L2` (choix de l'unité à activer)
  + `L6` (FLY), et eux seuls. Sans cet inventaire, le regroupement ratait son but : un changement
  oublié serait arrivé après le lot et aurait fait payer **un second** retrain.
- **(d) Ordre imposé par §0.48** : `L11` (élargir les 5 stratégies de déploiement, `N_DEPLOY_SLOTS`)
  **doit être tranché AVANT d'écrire cette tête** — c'est lui qui dimensionne les embeddings de
  candidats que `deploy_query_net` scorerait.

Coût accepté : le lot est plus long à préparer qu'une livraison isolée, et la tête pointeur de
déploiement reste non mesurée jusque-là.

<a id="s0.46"></a>
### 0.46 Résidus du 2026-07-29 — code mort `get_best_enemy_*`, rampe de déploiement sur le seul profil `x1`, instrumentation `[TRAIN DEBUG]` — ✅ CLOSE (points 1 et 2 mergés le 2026-07-29 ; point 3 livré le 2026-08-03)

**Cadre.** Trois constats indépendants relevés le 2026-07-29 pendant le contrôle de conformité
(§0, bloc « Contrôle de conformité indépendant »). Ils ont été relevés pendant le run 4, alors que
le working tree était gelé ; ✅ **le run 4 est arrêté depuis le 2026-07-29 13 h 08 (§0.14), le gel
est levé : les trois sont désormais traitables.**

**1. Code mort dans [`engine/macro_intents.py`](../../engine/macro_intents.py).**
`get_best_enemy_global`, `get_best_enemy_score` et `get_best_enemy_score_for_unit` n'ont **plus
aucun appelant en production**. Vérifié par grep sur tout le dépôt : les seules occurrences hors du
fichier sont des **mentions dans des commentaires/docstrings** — ⏳ **re-grepées le 2026-08-02, il
n'en reste que trois** : la pierre tombale de `engine/macro_intents.py`, un commentaire de
`engine/w40k_core.py` et l'en-tête de `tests/unit/engine/test_squad_charge_target_parity.py`
(celles d'`evaluation_bots.py` et de `shared_utils.py` ont disparu depuis) —
et, dans le fichier lui-même, des **appels mutuels internes** (`get_best_enemy_global` et
`get_best_enemy_score` appellent tous deux `get_best_enemy_score_for_unit`) : le groupe ne se tient
plus que par lui-même. C'est le **résidu de l'heuristique de charge par `damage_ratio`**, remplacée
par la cible de charge en dimension d'action (§0.43, P3-2). **Même motif que §0.38 et §0.39**
(correctif ou heuristique juste, plus aucun appelant, code conservé par inertie).
✅ **LIVRÉ ET MERGÉ** — constaté le 2026-07-29 à 13 h 56 (`git log main..v11-0.46-dead-code-charge-heuristic`) : ⏳ **MERGÉ depuis — vérifié le 2026-08-02 ; la branche citée est supprimée.**
branche `v11-0.46-dead-code-charge-heuristic`, **2 commits**, tête **`306033ec`** (13 h 55) —
`2d6bd2a8` (12 h 11) supprime le code, `306033ec` (13 h 55, suite de relecture adverse) répare les
documents que la suppression rendait faux (`V11_phaseA.md` ~L806 et ~L959 affirmaient
`get_best_enemy_score_for_unit` « encore vive » ; bandeau PÉRIMÉ de `macro_intent.md` remonté en
tête de document, car sa table « Fichiers à modifier » PRESCRIVAIT encore de créer ces fonctions).
Écrite dans un `git worktree` séparé — le dépôt principal n'a pas été touché,
comme l'exigeait alors le gel du working tree. Contenu : les 3 fonctions et leurs imports locaux (73 lignes
retirées de `macro_intents.py`), **plus deux `pop()` d'invalidation devenus morts avec elles** dans
`set_hp_in_cache` ([`shared_utils.py:1596-1597`](../../engine/phase_handlers/shared_utils.py#L1596),
clés `_cached_best_enemy_global` / `_cached_best_enemy_score` — vérifié qu'elles n'ont plus aucun
autre écrivain ni lecteur ; `_best_weapon_cache`, lui, reste VIVANT et n'est pas touché), et un
bandeau « PÉRIMÉ depuis §0.43 » sur `Implémenté/macro_intent.md`, dont une section décrivait ces
fonctions comme du code vivant. Vérifié dans le worktree : import du module OK,
`test_action_space_mirror.py` + `test_squad_charge_target_parity.py` = **21 tests verts**.
→ **Reste à faire : MERGER cette branche** (ne rien réécrire, elle est prête). ⚠️ Elle n'est pas
validée au-delà de ces tests ciblés — la vérification large appartient à l'utilisateur (§0.51).

**2. Rampe de déploiement réglée sur le SEUL profil `x1`.** Vérifié dans
[`ArmageddonAgent_training_config.json`](../../config/agents/ArmageddonAgent/ArmageddonAgent_training_config.json) :

| Profil | `deployment_mode_schedule` | `active_ratio_start` → `active_ratio_end` |
|---|---|---|
| `x1` | présent | **0.0 → 0.8** |
| `x5_new` | présent | 0.0 → **0.0** |
| `x5_debug` | présent | 0.0 → **0.0** |
| `x5_append` | **absent** | — |
| `x1_debug` | **absent** | — |

L'argument d'asymétrie entraînement/éval de **§0.29** vaut aussi pour ces profils : la rampe est
`training_only`, et **les scénarios d'éval jouent TOUJOURS une phase de déploiement** — les laisser
à `0.0` (ou sans bloc) reproduit exactement le décalage que §0.29 a corrigé sur `x1` (agent entraîné
en placement figé, noté sur des parties à déployer).
✅ **DÉCISION UTILISATEUR DU 2026-07-29 : ALIGNER TOUS LES PROFILS SUR `x1`** — `active_ratio_start`
**0.0** → `active_ratio_end` **0.8**, y compris `x5_append` et `x1_debug` qui n'ont aujourd'hui
**aucun bloc `deployment_mode_schedule`** (il est donc à créer chez eux). Justification : l'argument
d'asymétrie de §0.29 ne dépend pas du profil — la rampe est `training_only` alors que l'éval impose
**TOUJOURS** une phase de déploiement ; un profil resté à `0.0` entraîne un agent qui ne se déploie
jamais, puis le note sur des parties à déployer.

✅ **LIVRÉ ET MERGÉ** — constaté le 2026-07-29 à 13 h 56 : commit **`4c0ed7a4`** ⏳ **MERGÉ depuis — vérifié le 2026-08-02 ; la branche citée est supprimée.**
(« config(armageddon): aligner les 5 profils sur la rampe de deploiement de x1 (0.0 -> 0.8) »), sur
la branche **`v11-pre-lot-eval-baseline`** (et NON sur une branche `§0.46`, cf. §0.51). Les **cinq** profils d'alors
portent le réglage de `x1` **clé pour clé** ; les clés du contrat lu par
`_configure_deployment_mode_for_episode` (`enabled`, `training_only`, `active_ratio_start`,
`active_ratio_end`, `schedule == "linear"`, `freeze_after_progress`, toutes via `require_key`, sans
valeur par défaut) sont présentes, JSON revalidé. Ce chantier fait partie des quatre à livrer
**AVANT la mesure de référence** (§0.48, ordre) ; ✅ **mergé** (vérifié le 2026-08-02).
⏳ **Réglage changé depuis** : les **six** profils (`x1_long` ajouté) portent aujourd'hui
`active_ratio_start` **0.3** → `active_ratio_end` **0.8** avec `freeze_after_progress` **1.0**
(arbitrage utilisateur du 2026-08-02, en même temps que §0.57 : le gel à mi-run — plafond effectif
0,55 — est **abandonné**, la rampe atteint donc bien 0.8 en fin de run) — et non la rampe
`0.0 → 0.8` décrite ici. Le bloc est
**obligatoire** : son absence lève un `KeyError` (`_configure_deployment_mode_for_episode`).
🔴 **Ce point est LIVRÉ mais son EFFET était nul jusqu'au 2026-08-02 ([§0.57](#s0.57))** : aligner les
profils sur la rampe de `x1` ne servait à rien tant que le moteur divisait un compteur d'épisodes
LOCAL à un worker par le total GLOBAL. Sur un run `n_envs=48`, la part d'épisodes en déploiement
actif est restée à `active_ratio_start` du premier au dernier épisode. **Aucune mesure antérieure au
2026-08-02 n'a été produite avec la rampe décrite ici.**

**3. Instrumentation `[TRAIN DEBUG]` — non documentée jusqu'ici.** **41 occurrences** au 2026-07-29, **37** au 2026-08-02 (`ai/env_wrappers.py` 14, `engine/action_decoder.py` 15, `engine/w40k_core.py` 7, `ai/train.py` 1), réparties
sur [`ai/train.py`](../../ai/train.py), [`ai/env_wrappers.py`](../../ai/env_wrappers.py),
[`engine/action_decoder.py`](../../engine/action_decoder.py) et
[`engine/w40k_core.py`](../../engine/w40k_core.py), toutes **conditionnées** à
`game_state["debug_mode"]` / `debug_mode`. Inoffensives en production (elles ne s'exécutent pas hors
mode debug), mais **absentes de toute entrée de ce document** : elles sont arrivées avec le commit
`5d2dfd48` et ses prédécesseurs, sans trace écrite.
→ 🟠 **SEUL POINT ENCORE OUVERT de §0.46** : **à statuer** — instrument **permanent assumé** (alors
il se documente ici), ou instrument **temporaire** (alors il se retire). Tant que ce n'est pas
tranché, ne pas l'étendre.

**Relevé complet du 2026-08-02, pour permettre l'arbitrage** (les 37 sites lus un par un) :

| Fichier | n | Ce qui est tracé | Garde |
|---|---|---|---|
| `engine/action_decoder.py` | 15 | `_build_deployment_scoring_cache` (entrée, split du snapshot déployé, refs ennemies, cartes de LoS) et `_get_or_build_deployment_scoring_cache` (**hit / miss / update incrémental / échec de l'incrémental → rebuild complet**) | `game_state.get("debug_mode")`, avec `time.perf_counter()` lui-même conditionné |
| `ai/env_wrappers.py` | 14 | Les **trois boucles bot** (`_run_bot_until_not_bot_turn`, `_ensure_actionable_controlled_turn`, `_play_bot_until_control_returns`) en entrée/sortie, + `reset`, toutes estampillées `env_rank` | `debug_mode` |
| `engine/w40k_core.py` | 7 | `W40KEngine.step` : entrée, puis **avant/après** chacune des trois étapes (`normalize_action_input`, `convert_squad_action`, `_process_semantic_action`) | `self.game_state.get("debug_mode", False)` |
| `ai/train.py` | 1 | `_debug_train_marker`, jalons de la phase de construction | `debug_mode` |

🟢 **RECOMMANDATION (2026-08-02) : les GARDER, comme instrument permanent, et les documenter ici.**
Trois raisons, dans l'ordre de force :
1. **Ce sont exactement les trois endroits où ce dépôt s'est fait piéger.** Les boucles bot
   (`env_wrappers`) et le cache de déploiement (`action_decoder`) sont des chemins qui **ne
   plantent pas — ils consomment ou ils se figent** : c'est la famille de défauts de §0.33, §0.57 et
   §0.60, la seule que ni un test ni le win-rate ne détecte. Un `env_rank` sur chaque trace est ce
   qui rend un worker bloqué identifiable parmi 48.
2. **Le coût hors debug est un test booléen** — un `dict.get` sur le chemin de `step`. La
   construction des f-strings, le `perf_counter` et le formatage sont **tous à l'intérieur** de la
   garde : vérifié site par site, aucun n'échappe.
3. **Le retrait est irréversible en pratique** : ces traces sont chères à réécrire (elles encodent
   la connaissance de *quoi* regarder), et le prochain blocage de rollout les redemandera.

🟢 **ARBITRAGE UTILISATEUR DU 2026-08-03 : GARDÉES, sous forme optimisée.** Livré le 2026-08-03,
run terminé, dans l'ordre A → B+C → D. **Aucun gain de performance n'était à prendre et aucun n'a
été annoncé** : le coût hors debug était déjà un test booléen. Ce qui est gagné est ailleurs.

**A — les COMPTEURS sortis des traces.** Neuf des quinze sites d'`action_decoder` ne traçaient pas
un flux mais **comptaient** : `cache_miss_full_build`, `valid_hex_set_mismatch`,
`incremental_update`, `incremental_failed`. Ces quatre issues mesurent un **coût** (un `full_build`
reconstruit toutes les expositions LoS de la zone ; un incrémental ne touche que le delta d'une
pose) et n'étaient visibles **que sous `--debug`, donc jamais sur un run réel** — la famille §0.22.
- `ActionDecoder.DEPLOYMENT_CACHE_OUTCOMES`, scindée en **deux sous-familles DÉCLARÉES**
  (`INCREMENTAL_CACHE_OUTCOMES` / `FULL_BUILD_CACHE_OUTCOMES`) : le consommateur sommait au
  départ les reconstructions par soustraction (`total − incremental`), ce qui aurait classé en
  rebuild toute 5ᵉ issue qui n'en serait pas une — sur une courbe publiée que personne ne
  re-dérive. Un test vérifie que les deux familles **partitionnent** l'énumération.
- **Attribut d'INSTANCE du décodeur** (`self._deployment_cache_counts`), remis à zéro dans
  `reset_episode_caches` avec les autres caches d'épisode. Le seul appelant du cache est interne
  au décodeur, qui a déjà son hook d'épisode : faire transiter un compteur par le `game_state`
  contaminait son CONTRAT avec une préoccupation d'instrumentation — au point qu'une doublure de
  `test_action_decoder` avait dû porter la clé pour un chemin sans rapport avec le déploiement.
- Recopie dans `episode_tactical_data` à la terminaison, comme `shots_fired` depuis `action_logs`.
- Trois courbes : `perf/a_deploy_cache_full_build_rate` (la courbe à surveiller — vers 1.0, le
  cache ne sert plus à rien), `perf/b_deploy_cache_wasted_rate` (l'incrémental payé **puis jeté**,
  le seul travail purement perdu), `perf/c_deploy_cache_lookups`.
- Les **trois branches de reconstruction** (même bloc de 7 lignes recopié 3×) sont un
  `_full_rebuild(cause)` local : sans lui, toute évolution demandait trois éditions dont une
  pouvait s'oublier en silence — l'argument « axe B » appliqué au code qu'il instrumente.
- Au passage : `episode_tactical_data` était écrit **deux fois mot pour mot** (`__init__` et
  `reset`) — remplacé par `_empty_episode_tactical_data()`, sans quoi la clé ajoutée à un site et
  pas à l'autre aurait levé au premier épisode du chemin oublié.

**B+C — `engine/debug_trace.py`, point d'émission unique à canaux.** Les 37 sites sont migrés
(`W40KEngine.step` → `CH_STEP`, boucles bot → `CH_BOT_LOOP`, cache → `CH_DEPLOY_CACHE`,
construction du run → `CH_TRAIN`). Sélection par `W40K_TRACE=step,deploy_cache` ; variable absente
= tout (comportement historique de `--debug`), `none` = rien, **nom inconnu = lève**.
La valeur est validée **au chargement** (une faute de frappe échoue avant que le run ne démarre)
mais **PAS mémoïsée** — elle reste relue à chaque appel. C'est le patron déjà retenu par
[`engine/mask_verification.py`](../../engine/mask_verification.py) pour `W40K_MASK_VERIFY`, avec
sa raison écrite : « sinon les tests ne pourraient plus l'armer dynamiquement ».
⚠️ **La règle qui fait tenir l'ensemble : jamais de f-string en argument de `trace`** — elle serait
évaluée avant l'appel, donc hors garde, et déplacerait le coût sur le chemin de production. C'est
la seule façon dont cette livraison peut se dégrader, et elle est verrouillée par analyse AST.
`train._debug_train_marker` est un **RELAIS** `(fmt, *args)`, pas un helper qui reçoit un message
déjà construit — cf. le trou décrit plus bas.

**D** — `self.debug_mode` remplace `game_state.get("debug_mode")` sur le chemin de `step` (le dict
n'est alimenté que depuis l'attribut : vérifié, aucun écrivain externe, aucune divergence possible).
Les six sites de `step` sont **gardés** : leurs arguments sont des `dict.get`, donc évalués même
debug éteint (+0,31 µs/step mesuré, ~0,03 % d'un step — corrigé par propreté, pas par performance).
La garde de canal ne subsiste que là où elle évite un `require_key` ; ailleurs `trace` suffit, sa
première instruction étant cette même garde.

**Verrous** — `tests/unit/engine/test_debug_trace_guard.py` (**16**) et
`test_deployment_cache_counters.py` (**5**) :
- `step` complet en `debug_mode=False` → **zéro octet sur `stdout`** (le test réclamé ci-dessus) ;
- **analyse AST** : aucun appel à `trace` — ni à ses **relais déclarés** — ne passe une f-string,
  un `%`, un `+` **ni le moindre mot-clé** comme format. Les fichiers analysés sont **DÉCOUVERTS**
  par leur import de `engine.debug_trace`, pas listés à la main : une liste-miroir rétrécit en
  silence dès qu'un cinquième fichier se met à tracer. **Contre-épreuves faites** : f-string
  réintroduite → ROUGE en nommant la ligne ; `flush=True` réintroduit → ROUGE ; retirés → vert.
- compteurs : **contre-épreuve faite** — la remise à zéro changée en `setdefault` → ROUGE
  (« 10 après reset contre 10 accumulés ») ; rétablie → vert.
- contre le VERT VACANT : le fichier de compteurs tourne sur un scénario `deployment_type: active`
  réel et **exige que le compteur bouge** — le harnais habituel démarre en placement fixe et ne
  consulte jamais ce cache (limite déjà constatée en §0.56). La fixture partagée est
  `make_active_deployment_engine` (`tests/unit/engine/conftest.py`).

📌 **Trois faits que seule l'EXÉCUTION a donnés** (aucun n'était visible en lecture) :
1. `reset` ne laisse pas les compteurs à zéro : **l'observation initiale consulte déjà le cache**
   (§0.40), exactement une fois, par un `full_build_cold`. C'est cette signature qui est
   verrouillée — pas un « == 0 » qui aurait été faux.
2. `W40K_TRACE=` (définie mais **vide**) éteignait TOUTES les traces en silence — le défaut même
   que ce module existe pour rendre impossible. Elle lève désormais, en nommant la sortie voulue.
3. 🔴 **Le taux de reconstruction du cache est de 100 % sur le scénario mesuré**
   (`bot-01` : `full_build_cold` 1, `full_build_hex_mismatch` 9, `incremental` **0**), à
   **23-48 ms** la reconstruction. Cause lue dans le code : la validité du cache tient à
   « le jeu d'hexes valides est-il identique ? », or `_get_valid_deployment_hexes` le calcule
   **par unité à poser** (socle, formation) — deux unités ne donnent jamais le même jeu, le test
   échoue à tous les coups, et `_update_deployment_scoring_cache_incremental`, situé APRÈS, n'est
   jamais atteint. ⏳ **Non ouvert comme chantier** (arbitrage du 2026-08-03) : mesuré sur UN
   scénario et un début d'épisode, la part réelle sur un run entier est inconnue — la phase de
   déploiement ne dure que quelques dizaines de pas. `perf/a_deploy_cache_full_build_rate`
   répondra seule au prochain run ; c'est très exactement ce que l'axe A existait pour rendre
   visible.

🔍 **CE QUE LA PASSE `/simplify` DU 2026-08-03 A TROUVÉ** (4 revues parallèles : reuse,
simplification, efficacité, altitude) — à lire, les deux premiers points sont des leçons :
1. 🔴 **UN BUG, vu par 3 revues sur 4** : un `flush=True` était resté dans un appel `trace(...)`
   migré depuis un `print`. `trace` n'accepte aucun mot-clé → **`TypeError` dès que le canal
   `bot_loop` s'allume**, c'est-à-dire précisément quand on en a besoin. Ni le smoke ni les
   tests ne l'atteignaient : le site est dans `BotControlledEnv`, **qu'un moteur nu ne traverse
   jamais** — le motif « testé mais jamais appelé par le vrai chemin », ici retourné contre
   l'outil de diagnostic lui-même. Le verrou AST ne regardait que le format ; il refuse
   désormais tout mot-clé.
2. 🔴 **UN VERROU QUI MENTAIT** : le canal `train` était **intégralement hors garde**.
   `_debug_train_marker(message)` recevait des f-strings déjà construites par ses 12 appelants,
   pendant que le test AST déclarait couvrir `ai/train.py`. Un garde qui n'inspecte que les
   appels DIRECTS ne prouve rien sur les relais. Signature passée à `(fmt, *args)`, appelants
   convertis, relais déclarés au garde.
3. La cadence d'échantillonnage des boucles bot, écrite 7 fois à la main, avait **déjà divergé**
   (`< 5` sur un site, `<= 5` sur les six autres) : une boucle traçait 4 itérations, les autres 5.
   Devenue `_trace_sampled`.
4. Divers : garde `if cache_lookups > 0` qui trouait la courbe un épisode sur deux
   (`_emit_windowed` publie une moyenne de FENÊTRE), `file=sys.stdout` (le défaut) et son import,
   deux traces consécutives redondantes fusionnées.

⚠️ **Limites qui subsistent, à connaître avant de faire confiance au verrou** :
- le garde AST ne reconnaît que les **relais déclarés** (`trace`, `_debug_train_marker`). Un
  nouveau wrapper autour de `trace` qui ne serait pas ajouté à cette liste rouvrirait exactement
  le trou du point 2 ci-dessus. La découverte des FICHIERS, elle, est automatique.
- il vérifie la **forme des appels**, pas qu'ils soient appelables : c'est un test d'exécution du
  canal concerné qui aurait attrapé le `flush=True`, et il n'y en a pas pour `bot_loop` (le site
  vit dans `BotControlledEnv`, hors de portée d'un moteur nu).

<a id="s0.47"></a>
### 0.47 Relecture T2→T5 (dette §0.19) — 9 écarts, dont un outil d'éval au masque périmé — 🟠 OUVERT : É1, É2, É3, É4, É6 ✅ LIVRÉS ET MERGÉS ; **É8 EST TOMBÉ** ; restent É5, É7, É9 (mergés le 2026-07-29, vérifié le 2026-08-02)

**Cadre.** La part « T2→T5 jamais revérifiés » de [§0.19](#s0.19) a été traitée le **2026-07-29** :
relecture spec par spec de [`V11_tranches.md` §5](V11_tranches.md#s5) — T2 (L524-578), T3 (L579-638),
T4 (L640-702), T5 (L704-761) — plus [§8.2](V11_tranches.md#s8.2) et [§8.3](V11_tranches.md#s8.3),
en vérifiant les **instructions exécutées** et non les commentaires. Les écarts trouvés vivent
**ici** ; §0.19 n'en garde que le renvoi.

| Tranche | Verdict |
|---|---|
| **T2** | **ÉCARTS (6)** — É1, É2, É3, É4, É7, plus la réserve d'indécidabilité ci-dessous |
| **T3** | **CONFORME** — l'objectif est atteint ; une seule phrase de la doc est inexacte (É8) |
| **T4** | **ÉCARTS (2)** — É5, É6 |
| **T5** | **CONFORME** — la seule lacune (É9) était **déjà déclarée** par la doc, re-confirmée |

> ⚠️ **RÉSERVES DE MÉTHODE — lire avant d'utiliser ce qui suit.**
> 1. **Aucun test, aucun script n'a été exécuté** (audit mené pendant le run 4, ⛔ working tree
>    gelé). **Rien de ce rapport ne s'appuie sur une exécution** : tout est établi par lecture.
> 2. **La conformité LITTÉRALE de T2 est indécidable.** Sa spec nomme des constantes
>    (`ACTION_WAIT=18`, `ACTION_CHARGE=24`…) que la refonte de l'espace d'action a fait
>    **disparaître**. Seul l'**invariant survivant** — aucun littéral d'action nu, source unique
>    `engine/macro_intents.py` — a pu être vérifié ; il est **respecté dans `ai/`**.
> 3. Chaque écart porte la mention **contre-vérifié** (relu indépendamment par l'agent principal)
>    ou **non contre-vérifié**. Ne pas les confondre.

✅ **Le gel du working tree est LEVÉ** : le run 4 est arrêté depuis le 2026-07-29 13 h 08 (§0.14).
Ces écarts, non traitables au moment de l'audit, le sont maintenant. La contrainte d'origine
(workers d'éval en `spawn`, qui ré-importent le code depuis le disque, §0bis) redeviendra
applicable au prochain lancement de run.

#### É1 — un outil d'éval sert au modèle un masque de l'ANCIEN layout — ✅ CONTRE-VÉRIFIÉ, ✅ CORRIGÉ (non mergé)

[`scripts/roster_matchup_stats.py:562`](../../scripts/roster_matchup_stats.py#L562) appelle
`get_action_mask_and_eligible_units` — **layout legacy** : il passe par `_build_mask_for_units`
([`engine/action_decoder.py:298-408`](../../engine/action_decoder.py#L298-L408)), qui pose
`mask[9]` charge, `mask[10]` fight, `mask[11]` wait, `mask[4+i]` tir. Ce masque est donné tel quel
à `model.predict` ([:563](../../scripts/roster_matchup_stats.py#L563)), puis l'action retenue part
dans `env.step` ([:565](../../scripts/roster_matchup_stats.py#L565)), qui la décode en **sémantique
squad** (`convert_squad_action`, [`engine/w40k_core.py:1697`](../../engine/w40k_core.py#L1697)).

Deux faits contre-vérifiés, à ne pas perdre :

- **(a) Aucune exception de forme — le résultat est silencieusement faux, pas bruyamment cassé.**
  Les DEUX masques sont dimensionnés à `self.total_action_size` = **1107**
  ([action_decoder.py:305](../../engine/action_decoder.py#L305) et
  [:208](../../engine/action_decoder.py#L208)). `predict` ne peut donc rien détecter : les bits
  autorisés désignent simplement d'autres intentions que celles que le décodeur lira.
- **(b) L'évaluation DU RUN EN COURS n'est PAS touchée.** Elle passe par `env.get_action_mask()`
  ([`ai/bot_evaluation.py:361`](../../ai/bot_evaluation.py#L361),
  [:523](../../ai/bot_evaluation.py#L523)) — chemin squad correct. **Seul l'outil hors-ligne de
  statistiques par matchup est atteint** ; les win-rates qu'il produit sont à jeter tant qu'il
  n'est pas corrigé.

**Incohérence interne au fichier** : le même `roster_matchup_stats.py` utilise la **bonne** voie à
[:509](../../scripts/roster_matchup_stats.py#L509) (`return env.get_action_mask()`). Un seul des
deux chemins a été migré.

✅ **CORRIGÉ ET MERGÉ** — branche `v11-0.47-eval-tooling-mask`, commit **`9eab91a1`** : le masque ⏳ **MERGÉ depuis — vérifié le 2026-08-02 ; la branche citée est supprimée.**
vient désormais de `env.engine.get_action_mask()`, **le même appel que la boucle de référence**
([`ai/bot_evaluation.py:523`](../../ai/bot_evaluation.py#L523)).

⚠️ **L'outil portait TROIS AUTRES défauts que cette entrée ne mentionnait pas**, découverts en
corrigeant celui-ci et livrés sur la même branche (constaté le 2026-07-29 à 13 h 56) :

- **(1) L'outil ne pouvait pas DÉMARRER** — `1d38f5de`. L'observation du pipeline squad est un
  `gym.spaces.Dict` ([`w40k_core.py:639`](../../engine/w40k_core.py#L639)) et la boucle l'**aplatissait**
  par `np.asarray(..., dtype=np.float32)` **avant** d'atteindre le masque ; `_build_obs_normalizer`
  réimplémentait localement le normalizer et aplatissait lui aussi. La copie locale est **supprimée**,
  pas corrigée : elle délègue à `ai.bot_evaluation._build_eval_obs_normalizer_for_worker`. Corriger
  le seul masque n'aurait donc rien produit du tout : **É1 masquait un outil qui ne tournait pas**.
- **(2) Plafond de pas par épisode** — `1d38f5de` puis `c237a25c`. Le plafond vient maintenant de
  `require_key(task, "max_steps_per_episode")` / `get_max_turns()` (aucune constante en dur), et
  surtout un épisode sorti **par le plafond** n'est plus compté : il est classé `failed`, exclu du
  dénominateur et exposé sous `failed_episodes` — auparavant il était compté **perdu**, l'outil
  **fabriquait des défaites** à partir de parties inachevées.
- **(3) Vainqueur recalculé localement** — `1d38f5de` puis `a31029da`. Le `controlled_winner_id`
  déduit de `agent_seat_mode` est supprimé au profit de `require_key(info, "controlled_player")`, le
  siège étant écrit dans l'info par le moteur ([`w40k_core.py:1870`](../../engine/w40k_core.py#L1870)) ;
  et le repli silencieux `info.get("winner")` → `None` (compté **défaite**) est supprimé **des deux
  côtés**, script **et** référence de production [`ai/bot_evaluation.py`](../../ai/bot_evaluation.py)
  — corriger le seul script aurait laissé le défaut sur le chemin d'évaluation réellement utilisé.

Verrous : `tests/unit/scripts/test_roster_matchup_eval_loop.py` (**15 tests** à 14 h 05, `85783944` les a
réécrits pour interroger le **comportement** — doublures d'env/de modèle — et non plus le texte du
source, chaque défaut réintroduit seul étant vérifié rouge). ⚠️ **Non validée au-delà de ces tests
ciblés** : la vérification large appartient à l'utilisateur et n'a pas été faite.
⚠️ **Son merge se compose avec celui de `v11-0.47-dead-decoder-and-interface-lock`**
— voir le point de composition de §0.51 : une fois les deux mergées,
`get_action_mask_and_eligible_units` et `_build_mask_for_units` deviennent mortes et doivent être
supprimées.

#### É2 — `convert_gym_action` : ~250 lignes mortes verrouillées par ~25 tests — ✅ CONTRE-VÉRIFIÉ, ✅ SUPPRIMÉ (non mergé)

Définie [`engine/action_decoder.py:670-916`](../../engine/action_decoder.py#L670-L916), elle
contient **encore en dur l'ancienne sémantique** : `action_int in [4,5,6,7,8]`
([:820](../../engine/action_decoder.py#L820)), `== 11` wait
([:854](../../engine/action_decoder.py#L854)), `== 9` charge
([:895](../../engine/action_decoder.py#L895)) — et son satellite
`_get_valid_actions_for_phase` ([:415-425](../../engine/action_decoder.py#L415-L425)) rend
`[4,5,6,7,8]` / `[0,1,2,3,11]` / `[9,11]`.

**Contre-vérifié : aucun appelant de production.** Les seules occurrences hors du fichier sont des
**chaînes de debug** qui la nomment ([`engine/w40k_core.py:1694`](../../engine/w40k_core.py#L1694)
et [:1703](../../engine/w40k_core.py#L1703)). La production appelle `convert_squad_action`
([`engine/w40k_core.py:1697`](../../engine/w40k_core.py#L1697),
[`engine/pve_controller.py:226`](../../engine/pve_controller.py#L226)).

Elle est **verrouillée par ~25 cas** de
[`tests/unit/engine/test_action_decoder.py`](../../tests/unit/engine/test_action_decoder.py)
(:242, :249, :256, :280, :287, :313-340, :400-448, :464, :591-631), dont la fixture de masque fait
**31 entrées** ([:297](../../tests/unit/engine/test_action_decoder.py#L297)) — c'est-à-dire l'ancien
espace d'action, pas 1107.

C'est le motif **« code testé mais jamais appelé »** (§0.19, T6-i), dans sa forme aggravée :
**testé dans une sémantique MORTE**. Cela viole frontalement le critère
[§8.3](V11_tranches.md#s8.3) T2 (« plus AUCUN test ne référence 11/12 ou les plages 4-8 hors
déploiement »), qui est donc **faussement coché**.

✅ **DÉCISION UTILISATEUR DU 2026-07-29 : SUPPRIMER la fonction morte ET les ~25 tests qui la
verrouillent, ET ÉCRIRE À LA PLACE LE VERROU D'INTERFACE MANQUANT DE É3.** Les deux écarts se
traitent **ENSEMBLE, en un seul chantier** — ils ne sont pas séparables. Justification :
l'**absence** du verrou de É3 est précisément ce qui a laissé passer É1 ; supprimer `convert_gym_action`
et ses tests **sans le remplacer** retirerait les derniers tests qui exercent un décodeur et
laisserait le trou grand ouvert. Le remplacement est le fichier
`tests/unit/engine/test_agent_interface_contract.py` exigé par [§8.2](V11_tranches.md#s8.2) : un
test qui vérifie que **chaque entier d'action est routé vers l'intention attendue dans l'espace
d'action ACTUEL**, en **appelant réellement le décodeur** (pas en comparant des constantes entre
elles, cf. É3). Coût accepté : ce chantier est **plus long qu'une simple suppression** — il faut
écrire le verrou avant de pouvoir retirer les anciens tests.

✅ **FAIT ET MERGÉ** — branche `v11-0.47-dead-decoder-and-interface-lock`, **4 commits**, tête ⏳ **MERGÉ depuis — vérifié le 2026-08-02 ; la branche citée est supprimée.**
**`f0ed563a`** (14 h 02), ⏳ constaté le 2026-07-29 à 14 h 05 (la branche bougeait encore).
`ac776efc` supprime `convert_gym_action`
(~247 lignes) **et**, dans le même mouvement, ses satellites devenus injoignables :
`_get_valid_actions_for_phase`, `ActionDecoder.get_action_mask`, `get_action_mask_for_unit`, et
`movement_handlers._select_strategic_destination` + son cache `_build_objective_distance_cache`
(unique appelant = le décodeur mort) — 176 lignes retirées de `movement_handlers.py`. Les chaînes de
debug de `w40k_core.step` qui nommaient encore la fonction, et trois documents
(`AI_IMPLEMENTATION.md`, `TESTING.md`, `Distance management.md`), sont alignés.
`tests/unit/engine/test_action_decoder.py` passe de **55 à 27 tests** (constaté par
`git show <branche>:<fichier>` à 14 h 05) : ce sont les cas de la sémantique morte qui partent.
Deux commits de relecture s'y sont ajoutés : **`a210008c`** supprime aussi
`get_action_mask_and_eligible_units` et `_build_mask_for_units` (le masque de l'ancien espace,
orphelin de son décodeur) et pose une **pierre tombale** à leur place ; **`f0ed563a`** retire trois
symboles morts **préexistants** croisés pendant l'audit (`charge_handlers._select_strategic_destination`,
qui n'avait jamais eu d'appelant et survivait derrière son homonyme, plus
`ActionDecoder.get_all_valid_targets` et `can_melee_units_charge_target`, présentées comme
« Key Methods » par `AI_IMPLEMENTATION.md` et appelées nulle part).
⚠️ **Cette branche n'est PLUS autonome** : elle suppose la migration portée par
`v11-0.47-eval-tooling-mask` — voir la contrainte d'ordre de merge en [§0.51](#s0.51).

#### É3 — le verrou anti-récidive R5 exigé par §8.2 n'existe pas — ✅ CONTRE-VÉRIFIÉ, ✅ ÉCRIT (non mergé)

[§8.2](V11_tranches.md#s8.2) exigeait un fichier
`tests/unit/engine/test_agent_interface_contract.py` vérifiant que **chaque entier d'action est
routé vers l'intention attendue**, et le qualifiait de « **LE** verrou anti-récidive de R5 ».
**Contre-vérifié : ce fichier n'existe pas et n'a jamais existé.**

Le substitut réellement présent,
[`tests/unit/engine/test_action_space_mirror.py:13-76`](../../tests/unit/engine/test_action_space_mirror.py#L13-L76),
compare **les constantes entre elles** et **n'appelle jamais le décodeur** : il ne peut donc pas
constater qu'un masque et un décodeur divergent.

**Lien de causalité à retenir : c'est précisément le trou par lequel É1 est passé.** Un test qui
aurait exécuté « masque → `predict` → décodeur » aurait échoué sur `roster_matchup_stats.py`.

✅ **DÉCISION UTILISATEUR DU 2026-07-29 : ce verrou est ÉCRIT, dans le MÊME chantier que la
suppression de É2** — écrire `test_agent_interface_contract.py` est la contrepartie non négociable
du retrait de `convert_gym_action` et de ses ~25 tests. Contenu et justification : voir É2.

✅ **ÉCRIT ET MERGÉ** — commit **`62a934f3`** (même branche que É2) : ⏳ **MERGÉ depuis — vérifié le 2026-08-02 ; la branche citée est supprimée.**
`tests/unit/engine/test_agent_interface_contract.py`, **15 fonctions de test / 26 cas**, tous adossés
à un `game_state` de **moteur réel** et passant par `convert_squad_action` — cellules de move, `WAIT`
hors et en command, `SHOOT`/`CHARGE`/`FIGHT_SLOT_BASE + k`, `ACTION_FIGHT_NO_TARGET`, zone intents,
`CHOICE_BASE + i`, les 5 `DEPLOY_SLOT_BASE`, plus 4 gardes qui doivent **lever**. Le commit rapporte
**16 défauts réintroduits un à un** (décalages de base/offset, gardes neutralisées), chaque cas
devenant rouge sous au moins une mutation, et l'arbre restauré propre. Aucun littéral d'action nu.
⚠️ **Ce verrou fige l'espace d'action COURANT (1107)** : il devra être mis à jour avec le lot
(§0.48, dépendances).

#### É4 — les bots d'évaluation ne jouent pas ce qu'ils décident : `DefensiveBot` ne charge JAMAIS, et les bots « intelligents » tirent sur le mauvais slot — ✅ CONTRE-VÉRIFIÉ, ✅ CORRIGÉ (non mergé)

[`ai/evaluation_bots.py:468-482`](../../ai/evaluation_bots.py#L468-L482) : après la branche
`shoot`, la branche terminale est `if WAIT_ACTION in valid_actions: return WAIT_ACTION`. Or
`SQUAD_ACTION_WAIT` est posé **INCONDITIONNELLEMENT** dans le masque de la phase de charge
([`engine/phase_handlers/shared_utils.py:9718`](../../engine/phase_handlers/shared_utils.py#L9718)).
Le bot ne déclare donc **jamais** de charge. Poids de ce bot dans le score d'éval du run en cours :
**0.23** (`bot_eval_weights` du profil `x1`).

⚠️ **CORRECTION apportée par la contre-vérification : l'affirmation « ce bot ne combat jamais » est
FAUSSE.** En mêlée, `mask[SQUAD_ACTION_WAIT]` n'est posé que dans la branche `else` — aucune cible
([shared_utils.py:9769](../../engine/phase_handlers/shared_utils.py#L9769)). Quand l'escouade est
dans le pool 12.04 **avec** des cibles, seuls les slots de combat sont ouverts : le bot retombe sur
`valid_actions[0]` et **FRAPPE**. Mais il frappe **le slot d'indice le plus bas**, par accident
d'ordre et non par choix — motif §0bis « un comportement obtenu par effet de bord n'est pas un
comportement décidé ». **Même fragilité chez `GreedyBot`**
([`ai/evaluation_bots.py:303-304`](../../ai/evaluation_bots.py#L303-L304)).

**Conséquence pour la lecture du run 4** : sur **~un quart de la mesure** (0.23), l'adversaire ne
charge pas. Un win-rate flatté de ce côté doit être lu comme tel.

✅ **DÉCISION UTILISATEUR DU 2026-07-29 : CORRIGER APRÈS LE RUN 4** — celui-ci ayant été **arrêté à
13 h 08** ([§0.14](#s0.14)), le chantier a été **ouvert et livré le jour même** (voir plus bas) — et profiter du même chantier
pour **supprimer le choix de cible obtenu par accident d'ordre de tri** — chez `DefensiveBot`
**comme** chez `GreedyBot` ([`ai/evaluation_bots.py:303-304`](../../ai/evaluation_bots.py#L303-L304)) :
un `valid_actions[0]` n'est pas une décision, c'est un effet de bord (§0bis).

⚠️ **CONSÉQUENCE ASSUMÉE, qui touche la lisibilité de TOUTES les mesures : l'adversaire devient plus
fort, donc les taux de victoire mesurés AVANT et APRÈS ce correctif ne sont plus comparables entre
eux.** La **baseline d'évaluation change** — ce bot pèse **0.23** du score d'éval (`bot_eval_weights`
du profil `x1`). Toute comparaison de win-rate franchissant ce correctif est invalide ; il faudra
re-mesurer la référence sur la nouvelle baseline, et non l'extrapoler.

✅ **CORRIGÉ ET MERGÉ** — commit **`72a34d5c`** (12 h 59) sur la branche `v11-pre-lot-eval-baseline`, ⏳ **MERGÉ depuis — vérifié le 2026-08-02 ; la branche citée est supprimée.**
constaté le 2026-07-29 à 13 h 56.

🟢 **DÉCISION ASSUMÉE — DOCTRINE DE CONTRE-CHARGE DU `DefensiveBot`** (écrite ici parce qu'elle
n'existait nulle part : c'est un **comportement inventé le 2026-07-29** pour un adversaire de mesure,
pas la correction d'un comportement existant). Réparer « le bot ne charge jamais » obligeait à
choisir **quand** il charge ; la doctrine retenue est **dérivée des règles**, pas du confort de
mesure :

- **Il contre-charge** une escouade ennemie **de mêlée** (dégât de mêlée > dégât de tir) **déjà
  déclarable comme cible de charge** (**11.02**) : elle viendra au contact de toute façon, et la
  laisser charger lui offre **Fights First** (**12.04**, « *It made a charge move this turn* »).
  Il prend donc les devants sur la plus dangereuse au corps à corps.
- **Il ne charge pas** une escouade de **tir** : charger reviendrait à abandonner la position
  défensive qui définit ce bot. Il tient sa ligne.
- **Choix de cible explicite**, sur `get_enemy_slot_mapping` — **la même source que le masque et que
  l'observation** : `DefensiveBot` vise la plus **menaçante**, `GreedyBot` la plus **entamée** (son
  propre critère de tir). Un slot ouvert sans escouade en face **lève**. Fin du `valid_actions[0]`.

⚠️ **COÛT ASSUMÉ, à ne jamais perdre de vue en lisant une mesure** : ce bot pèse **0.23** du score
d'éval et l'agent gagnait **89 %** contre lui (§0.14) — **les taux de victoire d'AVANT et d'APRÈS
cette doctrine ne sont pas comparables**, et l'écart ne sera pas attribuable à l'agent. Toute
comparaison au run 4 est invalide ; la référence est à re-mesurer, pas à extrapoler.

Verrous : `tests/unit/ai/test_evaluation_bots.py` (**26 tests** sur la branche, dont 4 nouveaux ici),
la cible attendue étant volontairement placée sur un slot **non minimal** ; mutations vérifiées
rouges (suppression de la branche charge, retour à `valid_actions[0]`) puis rétablies vertes.

##### É4 (élargissement du 2026-07-29) — les bots « intelligents » tirent à côté de leur propre critère

**Le défaut n'est pas limité à `DefensiveBot`.** `_best_target_slot_by_hp`
([`ai/evaluation_bots.py:676-696`](../../ai/evaluation_bots.py#L676-L696)) et
`_best_target_slot_by_threat` ([:697-728](../../ai/evaluation_bots.py#L697-L728)) indexent
`active_unit["valid_target_pool"]` **comme si c'était un index de slot**. Or le masque ouvre
`SQUAD_ACTION_SHOOT_SLOT_BASE + i`, où `i` indexe le **mapping de slots ennemis** construit par tri
des ids ennemis vivants ([`shared_utils.py:9617`](../../engine/phase_handlers/shared_utils.py#L9617),
[:9663](../../engine/phase_handlers/shared_utils.py#L9663),
[:9698](../../engine/phase_handlers/shared_utils.py#L9698)) — deux espaces d'indices différents.
Le bot vise donc **une autre unité que celle que son propre critère a élue**.

> ⚠️ **Périmé depuis le 2026-07-30 (§0.53, table d'état en tête de document)** : `AggressiveSmartBot` et
> `DefensiveSmartBot` ont été **supprimés**, et les poids ci-dessous ne sont plus ceux de la
> config. Table conservée telle quelle — c'est un constat daté, pas un état courant.

| Bot | Poids (`x1`) | Touché ? |
|---|---|---|
| `AggressiveSmartBot` ([:775](../../ai/evaluation_bots.py#L775)) | 0.15 | 🔴 **OUI** |
| `AdaptiveBot` ([:972](../../ai/evaluation_bots.py#L972)) | 0.16 | 🔴 **OUI** |
| `DefensiveSmartBot` ([:874](../../ai/evaluation_bots.py#L874)) | — | 🔴 **OUI** |
| `RandomBot`, `GreedyBot`, `DefensiveBot`, `ControlBot` | — | ✅ **NON, prouvé** — ils prennent le **premier slot ouvert du masque** (défaut É4 d'origine, autre problème) |
| `TacticalBot` ([:1105](../../ai/evaluation_bots.py#L1105)) | 0 (holdout) | ✅ **NON, prouvé** — il n'expose pas `select_action_with_state` |

⚠️ **La garde `if action in valid_actions` a MASQUÉ le défaut au lieu de le révéler** : elle
empêchait l'action illégale de sortir, donc aucune exception, aucun log — motif §0bis, une garde
qui rattrape silencieusement une erreur d'indice la rend indétectable.

**Racine trouvée au passage — les bots n'ont pas accès à l'unité réellement activée.**
`_find_active_unit_for_bot` ([:666-675](../../ai/evaluation_bots.py#L666-L675)) **devine** « la
première unité vivante du joueur », qui peut être **une autre escouade** que celle que le moteur a
activée. Corriger l'indexation des slots sans corriger cela ne ferait que viser correctement depuis
la mauvaise unité.

**Signalé, NON traité** : les `select_shooting_target` / `select_charge_target` /
`select_fight_target` de `TacticalBot`, `RandomBot`, `GreedyBot` et `DefensiveBot` **ne sont appelés
par personne hors tests** — ce sont des **API mortes dans le pipeline d'évaluation** (motif §0.19
T6-i « code testé mais jamais appelé »).

📏 **Chiffrage par le run 4** ([§0.14](#s0.14)) : `vs_defensive` **0.89** pèse **0.205 des 0.509** du
`combined`, soit **40 % du score**. Le biais de É4 n'est plus une réserve qualitative, il est mesuré.

✅ **CORRIGÉ ET MERGÉ** — commit **`5f91c744`** (13 h 07), même branche. `_shoot_focus_fire` prend ⏳ **MERGÉ depuis — vérifié le 2026-08-02 ; la branche citée est supprimée.**
désormais un `score_fn` (`_score_wounded` / `_score_threat`) et **ne prend plus d'unité active** :
le mapping est **par JOUEUR**, issu de `get_enemy_slot_mapping` (la même source que le masque). Les
deux helpers indexés sur le pool sont supprimés — **et avec eux `_find_active_unit_for_bot`**, leur
unique fournisseur : la « racine trouvée au passage » ci-dessus est donc traitée, pas contournée.
`valid_target_pool` n'est **plus lu nulle part dans `ai/`** ; il reste vif dans le moteur, l'API et le
smoke PvP, et n'est pas supprimé dans cette passe. Mutations vérifiées rouges (réintroduction de
l'indexation par le pool → 3 tests rouges) puis rétablies ; le commit rapporte **26 + 28 verts** sur
`test_evaluation_bots.py`, `test_bot_evaluation_utils.py` et `test_eval_holdout_opponent.py`.
⏳ **À 14 h 05 la branche porte un 4ᵉ commit**, `d0183afe` (« deriver le joueur de l'escouade ACTIVEE,
jamais de `current_player` »), et `test_evaluation_bots.py` compte **27 tests**.

#### É5 — [T4] `scripts/sweep_scenario_bank_v11.py` documenté comme livré, ABSENT — ✅ CORRIGÉ (2026-08-02)

Le fichier est **absent du disque** (contre-vérifié). Il a été supprimé au commit **`924c2b41`**,
**sans aucune mention dans la tranche T4**, qui continue de le présenter comme un livrable.
**Atténuation** : la fonction de balayage elle-même survit, exercée par
[`tests/unit/ai/test_scenario_bank_migration_v11.py:118-157`](../../tests/unit/ai/test_scenario_bank_migration_v11.py#L118-L157).
L'écart est donc documentaire (un inventaire faux), pas une perte de capacité.
✅ **CORRIGÉ le 2026-08-02** : les deux mentions de `V11_tranches.md` (le livrable T4 et la
« réserve T4 close ») portent désormais l'avertissement que le script a été supprimé et que le
balayage vit dans le test.

#### É6 — [T4] `roster_matchup_stats.py` ÉCRIT des scénarios au contrat legacy — ✅ CONFIRMÉ ET CORRIGÉ (non mergé)

⚠️ **La mention « NON CONTRE-VÉRIFIÉ » qui figurait ici est PÉRIMÉE** : le constat a été confirmé et
corrigé par la branche `v11-0.47-eval-tooling-mask`, commit **`8336a226`** (constaté le 2026-07-29 à
13 h 56). Les deux sites qui matérialisent des scénarios émettent désormais `board_ref` +
`terrain_ref` et **aucune clé legacy**, sur le contrat vivant de
[`build_holdout_benchmark.py:117-126`](../../scripts/build_holdout_benchmark.py#L117). Le commit
établit en outre que **rien de ce qui était écrit n'était chargeable** : `objectives-51.json` /
`objectives-01.json` n'existent nulle part, `walls-01.json` non plus, et `deployment_zone: "hammer"`
désigne un fichier absent. Verrou : `tests/unit/scripts/test_roster_matchup_scenario_contract.py`
(**5 tests** sur la branche) — absence des clés legacy, présence de `board_ref`/`terrain_ref`,
**existence réelle** des fichiers désignés par les défauts CLI, et fourniture des objectifs et zones
de déploiement par le terrain. `284d67d8` a ensuite remplacé la lecture **textuelle** du source par
une interrogation du **parseur réel** (`_build_arg_parser()` extrait de `main()`), et `aa04a8d9`
supprime le paramètre `split` mort de `_build_scenario_template`.

Constat d'origine, conservé :
`_build_scenario_template` ([`scripts/roster_matchup_stats.py:291-302`](../../scripts/roster_matchup_stats.py#L291-L302))
émet `deployment_zone`, `wall_ref` et `objectives_ref` — **sans `board_ref` ni `terrain_ref`** —
et ces gabarits sont **matérialisés en fichiers réels**
([:930-954](../../scripts/roster_matchup_stats.py#L930-L954), plus un second site
[:416-424](../../scripts/roster_matchup_stats.py#L416-L424)). `objectives_ref` est une clé que le
moteur **rejette** : elle figure dans `LEGACY_KEYS`
([`scripts/migrate_scenario_bank_v11.py:42`](../../scripts/migrate_scenario_bank_v11.py#L42)).
Les **trois autres outils** de l'inventaire T4 sont propres — p. ex.
[`scripts/build_holdout_benchmark.py:124-125`](../../scripts/build_holdout_benchmark.py#L124-L125)
émet bien `board_ref`/`terrain_ref`.

#### É7 — [T2, mineur] `SelfPlayWrapper` n'a pas les trackers diagnostiques annoncés — ✅ CONTRE-VÉRIFIÉ ET CORRIGÉ (2026-08-02)

Les trackers que T2 attribue à `SelfPlayWrapper` sont **tous portés par `BotControlledEnv`** :
le suivi shoot/wait et `get_shoot_stats` y vivent entièrement, `SelfPlayWrapper` n'en porte
**aucun** (re-vérifié le 2026-08-02 par lecture des deux classes). Écart d'attribution dans la doc
de tranche. ✅ **CORRIGÉ** : la phrase de T2 ne crédite plus que `BotControlledEnv`, avec la note
de correction.

#### É8 — [T3, mineur] ✅ TOMBÉ — l'écart n'existe pas dans le code (vérifié le 2026-08-02)

L'écart tel qu'énoncé le 2026-07-29 (« `ai/analyzer.py` construit le chemin de board **à la
main**, au lieu de passer par `config_loader.get_board_dir()` ») **n'est pas vérifiable dans le
code** : `ai/analyzer.py` ne contient **aucune** occurrence de `get_board_dir`, ni aucune
construction manuelle de chemin de board — il lit `get_config_loader().get_board_config()` et
`.get_board_size()`. Le seul appelant de `get_board_dir()` du dépôt est `ai/train.py`.
**Rien à corriger côté code.** Si la phrase de T3 affirme encore un passage par `get_board_dir()`,
c'est cette phrase-là qui est à reprendre, dans la doc de tranche.

#### É9 — [T5] le critère « 3 seeds × 2 sièges » de §8.3 reste non couvert — re-confirmé

⚠️ **Énoncé corrigé le 2026-08-02.** Les **3 graines SONT couvertes** :
`tests/unit/engine/test_t5_bare_loop.py` boucle sur `for seed in (1, 2, 3)` dans ses trois tests
(les lignes 66-70 citées à l'origine sont la *fixture* de scénario, pas un corps de test). Ce qui
reste réellement non couvert du critère §8.3, c'est le **second scénario** et le **second siège**.
Cette lacune était **déjà déclarée par la doc** ; la relecture la **re-confirme** sans rien
découvrir de neuf — T5 reste CONFORME à ce qu'elle annonce d'elle-même.

🟢 **ARBITRAGE UTILISATEUR DU 2026-08-02 — les deux manques sont PLANIFIÉS, pas abandonnés :**
- **second siège** (l'agent en joueur 2) : **après** un entraînement bot satisfaisant — le tester
  avant n'apprendrait rien d'utile ;
- **second scénario** : **écrit par l'utilisateur**.

Ne pas re-signaler É9 comme un trou de couverture avant ces deux jalons.

<a id="s0.48"></a>
### 0.48 Inventaire des chantiers qui cassent un contrat + PÉRIMÈTRE du lot de ré-entraînement — 🟠 OUVERT (2026-07-29)

**Cadre.** [§0.44](#s0.44) a acté la stratégie « **un seul ré-entraînement pour tout le lot** » et
exigeait, avant de lancer ce lot, un **inventaire exhaustif** de ce qui touche l'architecture ou
l'observation. **Cet inventaire est rendu ici** ; §0.44 ne le décrit plus comme « en cours ».

**Les TROIS contrats.** Un chantier est « dans le lot » s'il casse **au moins un** de ces trois
contrats — c'est-à-dire s'il rend un modèle existant inchargeable ou son observation invalide :

1. **ARCHITECTURE de la policy** — toute tête, tout `features_dim`, tout `_split_features` qui
   change ⇒ `load_state_dict` lève dans les workers d'éval `spawn` (leçon §0bis, runs 1 et 2).
2. **OBSERVATION** — `obs_size` ou la **forme des clés** de `squad_obs_shapes()`.
3. **ESPACE D'ACTION** — `macro_intents.TOTAL_ACTION_SIZE` (**1107** aujourd'hui).

Un chantier qui n'en casse **aucun** se livre **à tout moment** et ne coûte **aucun**
ré-entraînement — c'est le critère de tri, pas l'importance du chantier.

#### Inventaire — chantiers qui CASSENT un contrat (13 identifiés)

| Réf | Chantier | Contrat cassé | Preuve | Ampleur |
|---|---|---|---|---|
| **L1** | [§0.44](#s0.44) tête pointeur de **déploiement** | **ARCHITECTURE** seule | `deploy_query_net` serait le jumeau de `choice_query_net` ([pointer_policy.py:211](../../ai/pointer_policy.py#L211)) ; il faut **exposer `deploy_emb` hors du tronc**, où il n'entre aujourd'hui que par concaténation ([spatial_extractor.py:293-299](../../ai/spatial_extractor.py#L293-L299), [:494-503](../../ai/spatial_extractor.py#L494-L503)) ⇒ `features_dim` ([:304-312](../../ai/spatial_extractor.py#L304-L312)) et `_split_features` changent. `obs_size` **inchangé**. | moyenne |
| **L2** | **P3-3** choix de l'unité à activer ([V11_phaseA.md:818-822](V11_phaseA.md#L818)) | **ESPACE D'ACTION + ARCHITECTURE** | Les candidats sont **mes escouades**, donc des entités observées ⇒ doctrine **slots + pointeur** ([macro_intents.py:63-66](../../engine/macro_intents.py#L63-L66)), pas `CHOICE_k` — d'autant que `SQUAD_TOP_K = 20` ([observation_builder.py:222](../../engine/observation_builder.py#L222)) dépasse `MAX_DECISION_OPTIONS = 6` et que [agent_decision.py:58](../../engine/agent_decision.py#L58) **lèverait**. Blocage structurel : les embeddings **ALLIÉS ne sont pas exposés** à la policy, ils sont **agrégés** ([spatial_extractor.py:460-468](../../ai/spatial_extractor.py#L460-L468)) et `features_dim` ([:306-311](../../ai/spatial_extractor.py#L306-L311)) ne contient que les **ennemis**. | **grosse** |
| **L3** | **P3-4** allocation des pertes (+ ordre de déclaration) | **OBSERVATION** au minimum | Nouveau type dans `AGENT_DECISION_TYPE_IDS` → `DECISION_CTX_BIN_SIZE` → `obs_size` ([observation_entities.py:258-262](../../engine/observation_entities.py#L258-L262)), plus ouverture du registre continu `DECISION_OPTION_CONT_FIELDS` ([:289-292](../../engine/observation_entities.py#L289-L292)). | grosse |
| **L4** | **P3-5** pile-in / consolidation | **OBSERVATION** au minimum | Idem L3, et décision **spatiale** : [V11_phaseA.md:123-131](V11_phaseA.md#L123) **interdit** le top-K d'hex. **DÉPEND** du bug ouvert [`A_faire/bug_pile_in_bfs_clearance_mismatch.md`](A_faire/bug_pile_in_bfs_clearance_mismatch.md). | grosse |
| **L5** | **P3-6** move-after-shooting + reactive move | **OBSERVATION** au minimum | Les **bits de règle existent déjà** ([observation_entities.py:108-109](../../engine/observation_entities.py#L108-L109)) : c'est la **DÉCISION** qui manque. | moyenne |
| **L6** | **P3-7** FLY / Take to the skies | **OBSERVATION** seule | Deux candidats **non-entités** ⇒ `CHOICE_0/1`, `TOTAL_ACTION_SIZE` **inchangé** ; mais un type de décision de plus ⇒ `obs_size`. ⚠️ **`L6` REMPLACE une CONSTANTE DE MOTEUR déjà en place** : depuis [§0.49](#s0.49) point 5, une unité FLY pilotée par le modèle **déclare systématiquement** et paie les 2" — y compris quand c'est un pur désavantage. Tant que `L6` n'est pas livré, une part de la performance mesurée tient à un choix que l'agent ne fait pas. | petite |
| **L7** | **P3-8a** choix d'arme par l'agent | **OBSERVATION**, + espace d'action selon la voie | `K_WEAPONS_RANGED`/`K_WEAPONS_MELEE` = **10** ([observation_builder.py:209-210](../../engine/observation_builder.py#L209-L210)) dépassent `MAX_DECISION_OPTIONS = 6`. | moyenne à grosse |
| **L8** | **P3-8b** split-fire par-figurine | **ESPACE D'ACTION** | Aujourd'hui l'**escouade entière** vise UN slot ([macro_intents.py:37](../../engine/macro_intents.py#L37)) ; le par-figurine exige un produit **figurine × arme × slot**, inexprimable dans l'espace actuel. | grosse |
| **L9** | **P3-8c** charge multi-cibles (11.04 « one or more ») | **ESPACE D'ACTION** | Un seul `target_slot` de charge aujourd'hui ([macro_intents.py:42-43](../../engine/macro_intents.py#L42-L43)). Le PvP le fait déjà. | moyenne |
| **L10** | **P3-8d** placement final de charge | **ESPACE D'ACTION** ou **OBSERVATION** selon paramétrisation | Décision spatiale, même réserve que L4 ([V11_phaseA.md:123-131](V11_phaseA.md#L123)). | moyenne |
| **L11** | **P3-8e** élargir les 5 stratégies de déploiement | **OBSERVATION** seule | `N_DEPLOY_SLOTS` ([observation_entities.py:334-338](../../engine/observation_entities.py#L334-L338)). `TOTAL_ACTION_SIZE` **NE bouge PAS** : les ids **4-8** sont dans la plage des cellules de move (`MOVE_CELL_BASE = 0`, [macro_intents.py:33-34](../../engine/macro_intents.py#L33-L34)). | petite à moyenne |
| **L12** | **P4** observation de support | **OBSERVATION**, **part résiduelle seulement** | Trois des quatre features annoncées **existent déjà** ([observation_entities.py:150-151](../../engine/observation_entities.py#L150-L151), [:129-130](../../engine/observation_entities.py#L129-L130), [:166](../../engine/observation_entities.py#L166)). | petite — **ne se livre pas seule** |
| **L13** | **Phase B** observation des niveaux / élévation ([V11_tranches.md:36-37](V11_tranches.md#L36), [:1508-1519](V11_tranches.md#L1508), marquée « **obligatoire** ») | **OBSERVATION** | Nouvelles features par-figurine et par-slot ennemi ⇒ layout, donc `obs_size`. | grosse — **conditionnée** à la vérification du chantier LoS 3D |

#### HORS LOT — n'entament AUCUN contrat, livrables à tout moment

- [§0.46](#s0.46) points **1** (code mort `get_best_enemy_*`), **2** (rampe de déploiement sur tous
  les profils), **3** (instrumentation `[TRAIN DEBUG]`).
- [§0.47](#s0.47) **É1 à É9** (relecture T2→T5).
- [§0.49](#s0.49) conformité **FLY 21.03** — non-conformité de moteur, à ne pas confondre avec `L6`
  (FLY comme décision d'agent), qui, lui, est dans le lot.
- [§0.50](#s0.50) conformité **01.07** battle-shock / contrôle d'objectif (corrigée et mergée).
- [§0.33](#s0.33) rollout buffer / nombre d'envs.
- [§0.19](#s0.19) revérification T1→T5.
- **Règle 19.04 leader ↔ bodyguard** : change la **VALEUR** de bits existants, pas leur **nombre**.
- Bug [`A_faire/bug_pile_in_bfs_clearance_mismatch.md`](A_faire/bug_pile_in_bfs_clearance_mismatch.md).
- Overrun 12.06 ([`A_faire/overrun.md`](A_faire/overrun.md)).
- MCTS-adversaire ([`A_faire/MCTS/`](A_faire/MCTS)).
- Outillage / perf / front / replay de [`A_faire/`](A_faire) (10x, perf, preview de tir, replay
  par-figurine, tests front, Database, Security).

#### Dépendances — elles commandent l'ordre

- **L11 doit être tranché AVANT d'écrire L1** : `N_DEPLOY_SLOTS` dimensionne les embeddings que la
  tête `deploy_query_net` scorerait.
- **L2 doit précéder ou accompagner L4 / L5 / L10** : toutes touchent le **pool d'activation** et
  l'**ordre des candidats**.
- **L4 dépend du bug pile-in BFS** (HORS LOT, mais doit **précéder**).
- **L12 est subordonné à L3 / L4 / L5** : le registre continu n'a de contenu que si une tranche P3
  en a besoin.
- ⚠️ **QUATRE chantiers ne cassent AUCUN contrat, MAIS doivent être livrés AVANT la mesure de
  référence du lot** : la rampe de déploiement ([§0.46](#s0.46) point 2) et la conformité FLY 21.03
  ([§0.49](#s0.49)) changent **ce qui est appris** ; le correctif des bots d'éval
  ([§0.47](#s0.47) É4) change la **baseline d'évaluation** ; la conformité 01.07
  ([§0.50](#s0.50)) change **l'issue des parties**. Arrivés
  après, ils rendent toute comparaison à une mesure antérieure **INVALIDE** — c'est exactement
  pourquoi le run 4 a été arrêté ([§0.14](#s0.14)) plutôt que mené à terme.
  ✅ **État au 2026-08-02 : les QUATRE sont MERGÉS sur `main`** — rampe `4c0ed7a4`,
  FLY `6191a360`, bots `72a34d5c` + `5f91c744`, 01.07 `4be41919` ; vérifié par
  `git merge-base --is-ancestor`. **Le prérequis d'ordre est LEVÉ.**
- ⚠️ **Le verrou d'interface de [§0.47](#s0.47) É3 fige l'espace d'action COURANT (1107)** : écrit
  avant L2 / L8 / L9, il **devra être mis à jour avec le lot**. Ce n'est pas une raison de ne pas
  l'écrire, c'est une **conséquence à assumer**.

#### 🟢 ARBITRAGE UTILISATEUR DU 2026-07-29 (1) — PÉRIMÈTRE DU LOT : **L1 + L2 + L6**, et eux seuls

**« Grouper » ne signifie PAS « tout faire ».** Le lot est un **périmètre choisi**, pas la totalité
de l'inventaire ci-dessus. Motifs :

- **L1** est **déjà cadré** (§0.44 en donne la conception complète).
- **L2** porte le **plus gros gain stratégique annoncé** : aujourd'hui l'unité activée est
  **toujours** `eligible_units[0]` ([V11_phaseA.md:818-822](V11_phaseA.md#L818)).
- **L6** est **petit** et ne coûte presque rien une fois le retrain payé.

**L3, L4, L5 et L7 à L13 restent HORS du lot**, à **replanifier après sa mesure**.

#### 🟢 ARBITRAGE UTILISATEUR DU 2026-07-29 (2) — RÈGLES FUTURES : RÉSERVER LA PLACE DÈS LE LOT

**Constat vérifié.** `PROFILE_BIN_SIZE = len(WEAPON_RULE_BITS) + len(ANTI_KEYWORDS) + 1`
([observation_weapon_profiles.py:85](../../engine/observation_weapon_profiles.py#L85)), et les
drapeaux `rule_*` dérivent de `UNIT_RULE_EFFECT_IDS`
([observation_entities.py:103](../../engine/observation_entities.py#L103),
[:167](../../engine/observation_entities.py#L167),
[:294](../../engine/observation_entities.py#L294)). Donc **toute règle de jeu rendue vivante ajoute
un bit, change `obs_size`, et impose un ré-entraînement** — ce qui met en **tension directe**
l'objectif « 100 % conforme aux règles » et l'objectif « un seul ré-entraînement ».

**DÉCISION : réserver dès le lot la place des règles pas encore implémentées**, **inactives**
jusqu'à leur implémentation, pour que les ajouter ne coûte **plus** de retrain.
⏳ Un **inventaire des règles manquantes** (PDF de [`Documentation/40k_rules/`](../40k_rules)
confrontés au vocabulaire observé) est **en cours de constitution en parallèle** — son contenu
n'est **pas préjugé** ici, aucun chiffre n'en est supposé tant qu'il n'est pas rendu.
**Coût accepté** : quelques bits inutilisés dans l'observation.

<a id="s0.50"></a>
### 0.50 Non-conformité 01.07 — le contrôle d'objectif sous battle-shock — ✅ CORRIGÉ ET MERGÉ (2026-07-29) ; 🟠 TRAVAIL DE SUITE OUVERT (2026-08-02)

**État.** ✅ Corrigé sur la branche **`v11-battle-shock-oc`**, commit **`4be41919`**
(« fix(01.07): une unite battle-shocked n'apporte plus aucun controle d'objectif »), **MERGÉE depuis (vérifié le 2026-08-02)**
sur `main`. ⏳ **État constaté le 2026-07-29 à 14 h 05** (la branche a bougé pendant le constat) :
**5 commits**, tête **`b8932f52`** — s'ajoutent `906fffc8` (docstring qui prétendait à tort que
l'observation partage `sum_objective_control_oc`), **`d0bbdcc4`** (le **reward** `on_objective_bonus`
payait encore une escouade choquée pour occuper une case qu'elle ne peut **pas** prendre : l'agent
apprenait une association fausse — même lecture stricte que le moteur), `ea8e9f16` (verrous sur les
producteurs du drapeau et sur le chemin vif du choc), `b8932f52` (**3ᵉ vérité parallèle signalée,
non corrigeable ici** : `BoardReplay.computeControlCounts` recalcule le contrôle dans le front, à
l'ancre **et** sans battle-shock).

✅ **Les DEUX `useMemo` du front (points de victoire, coloration) sont SUPPRIMÉS (2026-07-29)** et
lisent l'instantané moteur. ⚠️ Un **troisième recalcul** avait survécu — le **constructeur du journal d'événements** de
`BoardReplay.tsx`, celui qui produit les entrées `action_name: "objective_control"` : il recomptait
l'OC **à l'ancre de l'unité** et **sans battle-shock**, et ré-implémentait une troisième fois la
fenêtre de score et le départage. ✅ **CORRIGÉ le 2026-08-02** : il **diffère deux instantanés
moteur successifs** (`state.objective_control.controllers`, attaché par `replayParser.ts`) et
journalise le changement — plus aucun barème, aucune géométrie, aucune règle rejoués côté
navigateur. Sont morts avec lui `isObjectiveScoringWindow`, la relecture de
`rules.primary_objective`, l'enrichissement d'unités et le calcul de phase qui ne servaient qu'à ce
comptage. Les sommes d'OC ont disparu du message : le moteur ne les publie pas, et les afficher
reviendrait à réintroduire le calcul local.
**Verrou** : la différence d'instantanés est extraite en fonction pure
(`frontend/src/utils/objectiveControlJournal.ts`, appelée par le composant — pas de copie inline)
et couverte par `objectiveControlJournal.test.ts`, **8 tests**. Mutation-testée : retirer le
`?? null` sur la zone jamais vue ⇒ **3 rouges** ; retirer la comparaison au contrôleur précédent
⇒ **4 rouges**. `BoardPvp.tsx` a été vérifié au passage : il lit déjà `objective_controllers` du
moteur — pas de jumeau.
Le constat « impossible en l'état, le
`step.log` ne porte aucune information de battle-shock » posait le problème à l'envers : il n'a
jamais fallu **reconstituer** le battle-shock côté navigateur, il fallait cesser d'y recalculer quoi
que ce soit. Le moteur journalise désormais **son** état 14.02 —
`StepLogger.log_objective_control_snapshot`, appelé par
`W40KEngine._log_objective_control_snapshot_if_changed` à chaque changement de
`objective_controllers` **ou** de `victory_points` — sous la forme
`T{tour} OBJECTIVE CONTROL: VP1=… VP2=… ZONES=<nom>:Ctrl=…|…` (clé = le **nom de zone**, celui de
la ligne `Objectives:`, via l'unique `StepLogger._objective_display_name`). `replayParser.ts`
l'attache à chaque état de la timeline et `BoardReplay.tsx` le lit tel quel : les deux `useMemo`
qui resommaient l'OC (points de victoire **et** coloration des hexes) sont supprimés, avec eux le
barème de scoring ré-implémenté une seconde fois côté front.
**Écart mesuré avant correction** (vraie partie ArmageddonAgent, état final) : **2 zones sur 5**
avaient un contrôleur différent entre le moteur (empreinte de socle) et le calcul par ancre du
navigateur — p. ex. `rect b NW` 9 d'OC moteur contre 3 à l'ancre.
Corrigé au passage, même famille : `reset()` ne purgeait pas `_objective_control_last_boundary`, si
bien que la frontière de l'épisode **précédent** (`fight`, T5) déclenchait un checkpoint 14.02 au
tout premier build d'observation du nouvel épisode — des contrôleurs figés avant qu'aucune phase se
soit terminée.

**1. La règle, lue dans les PDF.** [`01 Core concepts.pdf`](../40k_rules) §01.07 : « *While a unit
is battle-shocked: ▪ The Objective Control (OC) characteristic of all of its models is modified to
'-'* ». [`02 Datasheets.pdf`](../40k_rules) §02.02 : un OC de `'-'` rend la figurine **incapable de
contrôler**. [`14 Objectives.pdf`](../40k_rules) §14.02 et son **diagramme p.53** tranchent le cas
explicitement.

**2. La rupture.** `sum_objective_control_oc_multi`
([`engine/game_state.py:2983-3060`](../../engine/game_state.py#L2983-L3060)) — **SOURCE UNIQUE**
partagée par le moteur **et** l'observation — **ne consultait jamais `battle_shocked`** : une unité
choquée tenait ses objectifs **normalement**.

**3. Le correctif.** L'unité choquée est **écartée** du calcul, sur lecture **stricte**
`require_key(unit, "battle_shocked")` — **aucune valeur par défaut**, conformément à la règle « pas
de fallback pour masquer une donnée absente ». Deux constructeurs de production **omettaient** le
champ et le posent désormais à `False` :
`services/api_server.py::_build_units_from_army_config` et
`services/endless_duty_runtime.py::_build_unit_from_registry`.

**4. Les deux autres effets de 01.07 sont SANS OBJET.** Les restrictions de **stratagèmes**
(PDF 15) et d'**actions** (PDF 16) ne s'appliquent à rien : **aucun de ces sous-systèmes n'existe
dans le moteur** (grep : **zéro** occurrence de stratagème ou de CP). Ce n'est pas une dette
ouverte, c'est un périmètre inexistant.

⚠️ **CE CORRECTIF CHANGE L'ISSUE DES PARTIES.** Tout modèle entraîné **avant** — dont celui du
**run 4** — a appris qu'on **tient un objectif gratuitement en étant choqué**. Les mesures
antérieures sur le jeu d'objectifs (au premier chef `vs_control`, §0.14) sont à relire sous cette
réserve.

⚠️ **TRAVAIL DE SUITE EXPLICITE — LE CONTRAT DE `battle_shocked` EST CONTRADICTOIRE DANS LE MOTEUR.**
Ce correctif pose, par `require_key(unit, "battle_shocked")` dans
`sum_objective_control_oc_multi` (`engine/game_state.py`), que **l'absence du champ est un état
corrompu**. Or **sept autres lecteurs du même drapeau** posent l'inverse — l'absence y vaut « pas
choqué ». Recomptés sur `main` le **2026-08-02**, toujours **sept**, ancrés par nom de fonction :

| Fonction | Fichier | Lecture |
|---|---|---|
| `command_phase_start` | `command_handlers.py` | `unit.get("battle_shocked", False)` |
| `movement_unit_execution_loop` | `movement_handlers.py` | `bool(unit.get("battle_shocked", False))` |
| `movement_build_model_destinations_pool` | `movement_handlers.py` | `unit.get("battle_shocked", False)` |
| `desperate_escape_pre_move` | `shared_utils.py` | `bool(unit.get("battle_shocked", False))` |
| `desperate_escape_post_move` | `shared_utils.py` | `not unit.get("battle_shocked", False)` |
| `build_squad_move_cell_map` | `shared_utils.py` | `bool(_unit_obj_fp.get("battle_shocked", False))` — porte même le commentaire `# get allowed` |
| `_handle_hazard_confirm` | `w40k_core.py` | `not bool(unit.get("battle_shocked", False))` |

✅ **TRANCHÉ ET MIGRÉ le 2026-08-02 (arbitrage utilisateur) : la lecture STRICTE gagne.** Le champ
**est** un invariant de construction — il est posé par les quatre constructeurs de production
(`game_state.py` ×2, `services/api_server.py`, `services/endless_duty_runtime.py`). Les sept
`get(..., False)` étaient donc des valeurs par défaut anti-erreur (T1) : ils sont passés en
`require_key(unit, "battle_shocked")`. `grep 'get("battle_shocked"' engine/ ai/ services/` → **0
hit** hors tests.

**Ce que la migration a révélé, et qui est le vrai bénéfice** : six fichiers de test construisaient
des unités **sans ce champ** — des doublures qui ne représentaient donc pas une unité que la
production sait produire (motif §0bis « un test qui contourne le vrai constructeur »). Ils sont
corrigés, avec le commentaire qui dit pourquoi le champ est obligatoire :
`test_command_phase.py`, `test_activation_e2e.py`, `test_squad_move_descent_frontier.py`,
`test_execute_semantic_action.py`, `test_cascade_fight_subphases.py`, `test_move_budget_geodesic.py`.

**Trois replis voisins durcis dans la foulée** (relevés par relecture, même intention) :
`desperate_escape_post_move` lève désormais si l'unité est introuvable — son jumeau
`desperate_escape_pre_move` levait déjà, l'asymétrie ne se justifiait pas ; l'empreinte de cache de
`build_squad_move_cell_map` lève au lieu de retomber sur « non choqué », un `squad_id` introuvable
ne pouvant pas produire une clé de cache valide (deux états de jeu différents auraient partagé la
même) ; et `command_phase_start` lit `player` et `LD` en strict, eux aussi posés par les quatre
constructeurs.

✅ **Vérification** : ~60 fichiers de test ciblés verts côté agent, **suite complète lancée par
l'utilisateur le 2026-08-02 — RAS**.

✅ **ÉCART `ai/analyzer.py` — TRAITÉ** (vérifié le 2026-08-02). `_calculate_objective_control_snapshot`
n'existe plus : les fonctions de recalcul de contrôle d'objectif de l'analyzer ont été supprimées
le 2026-07-29 (un commentaire-tombeau en tête de fichier le consigne), et l'analyzer lit désormais
l'instantané journalisé par le moteur (`T{tour} OBJECTIVE CONTROL:`). Il ne reste donc qu'**une**
lecture parallèle, celle du frontend signalée plus haut.

<a id="s0.14"></a>
### 0.14 Re-mesure du run — 🟠 OUVERT ; ⏳ ENTRÉE PÉRIMÉE au 2026-08-02 (des runs POSTÉRIEURS ont tourné, cf. tableau du §0) — historique : run 4 `--new` lancé le 2026-07-29 à 12 h 03, **ARRÊTÉ à 13 h 08** (état et chronologie dans le tableau du §0, entrée périssable — ne pas les dupliquer ici)

> 🔴 **ARRÊT DU RUN 4 — 2026-07-29, 13 h 08, SIGINT, décision de l'utilisateur.** Le run **n'a pas
> échoué** : il a été arrêté parce qu'il **ne pouvait plus servir de mesure de référence**, pour
> deux raisons **cumulées** — (1) ses **adversaires d'évaluation sont faussés** ([§0.47](#s0.47) É4,
> élargi le même jour) ; (2) son **propre roster jouait un jeu non conforme aux règles**
> ([§0.49](#s0.49), FLY 21.03). Une mesure dont l'adversaire ET les règles sont faux ne se corrige
> pas a posteriori : elle se refait.
>
> **Ce qu'il a produit — le seul chiffre de la journée, à conserver.** ~3 400 épisodes, et surtout
> la **PREMIÈRE ÉVALUATION COMPLÈTE franchie** au marqueur **2 000 épisodes** — exactement le point
> où le **run 2 était mort** (§0). Le garde-fou d'éval (§0.27) tient donc sur un run réel.
>
> | Adversaire | Score | Poids `bot_eval_weights` (`x1`) | Contribution |
> |---|---|---|---|
> | `vs_tactical` (holdout) | 0.95 | 0 | 0 |
> | `vs_defensive` | **0.89** | 0.23 | **0.205** |
> | `vs_aggressive_smart` | 0.76 | 0.15 | 0.114 |
> | `vs_greedy` | 0.65 | 0.23 | 0.150 |
> | `vs_adaptive` | 0.20 | 0.16 | 0.032 |
> | `vs_control` | **0.04** | 0.23 | 0.009 |
> | **`bot_eval/combined`** | **0.509** | — | `worst_bot_score` **0.04** |
>
> **Deux lectures, à ne pas confondre :**
> 1. **Le bot défensif apporte à lui seul 0.205 des 0.509, soit 40 % du score.** C'est le
>    **chiffrage** du biais de [§0.47](#s0.47) É4 : ce bot ne déclare jamais de charge, et le score
>    global s'appuie pour deux cinquièmes sur cet adversaire mutilé. Le `combined` 0.509 n'est donc
>    **pas** un demi-succès, c'est un chiffre porté par sa composante la moins crédible.
> 2. **La faiblesse réelle est `vs_control` à 0.04**, sur le **jeu d'objectifs qui décide 93 % des
>    parties**. C'est le `worst_bot_score`, et c'est le signal à traiter — pas le `combined`.
>
> ⚠️ Ces chiffres sont **antérieurs** au correctif 01.07 ([§0.50](#s0.50)) : le modèle mesuré ici a
> appris qu'on tient un objectif gratuitement en étant **battle-shocked**. La lecture de
> `vs_control` en est directement affectée.

> ⚠️ **Titre corrigé le 2026-07-28.** L'ancien (« BLOQUÉ À L'ÉVAL DU MARKER 2000 ») décrivait le
> run du 2026-07-22, dont le bloqueur **§0.27 est corrigé depuis le 2026-07-26** (§0hist). Ce qui
> reste est un run à lancer, pas un run bloqué. Lire l'alerte de divergence de config en §0 avant.

> Part **ouverte** de §0.13 (run x5_debug 100 épisodes). Le run et le fix de l'évaluation
> finale sont résolus et documentés en **§0.13**.

> ✅ **NON-RÉGRESSION §0.11 VALIDÉE (2026-07-21) — 3 runs indépendants, zéro crash.** Après le fix
> §0.18, la commande de re-mesure (`x5_debug --total-episodes 500`) a été relancée **3 fois** :
> **3× 500/500 épisodes, `✅ TRAINING COMPLETE`, ZÉRO `collision intra-plan`, zéro `Traceback`,
> zéro `incohérence masque`** (grep sur les 3 logs). Le crash dépendant de la trajectoire qui
> survenait à l'épisode ~280 (§0.18) **n'est plus jamais réapparu** sur 1500 épisodes cumulés.
> L'avertissement « la non-régression de §0.11 reste non validée par un run » de §0.18 est
> **LEVÉ**. ⚠️ **Ce que ces 3 runs NE prouvent PAS** : le **score par matchup**. À 500 épisodes /
> 2 par bot, les Combined (61,5 % / 38 % / 19,5 % / 42 %) restent **non concluants** (bruit
> d'échantillon) — c'est le **pipeline** qui est validé, pas la politique. Un win-rate
> interprétable exige toujours un run long à `total_episodes` réel (10-30k), aujourd'hui coûteux
> en temps (~36 h) — c'était précisément la cible du chantier §0.22, cadrage archivé
> [`Implémenté/V11_move_pool_optimization.md`](Implémenté/V11_move_pool_optimization.md) (**clos**),
> suite vivante [`V11_move_build_acceleration.md`](V11_move_build_acceleration.md).
> §0.15 étant tranché, ce win-rate mesurera la robustesse à l'**adversaire**.

**Run de re-mesure du 2026-07-20 — commande exacte :**

```
python3 ai/train.py --agent ArmageddonAgent --scenario bot --new \
        --training-config x5_debug --total-episodes 500
```

(`--total-episodes` surcharge le `total_episodes: 100` de la config ; **la config n'a pas été
modifiée**. Lancé APRÈS §0.12, donc sur le reward définitif.)

**✅ Ce que ce run PROUVE.**

| Point | Résultat |
|---|---|
| Déroulement | **500/500 épisodes, exit 0**, 1 h 48, 8 workers, GPU. **Zéro exception, zéro `incohérence masque/exécution`** dans tout le log. |
| **Non-régression §0.11** | 🔴 **NON — affirmation RETIRÉE le 2026-07-20, voir §0.18.** Ce premier run a bien franchi l'épisode ~250, mais un **second run, même commande**, a **crashé sur le même message d'erreur à l'épisode ~280**. Un run qui passe ne prouve rien ici : le crash dépend de la trajectoire, donc du hasard. **L'avertissement « la non-régression de §0.11 reste non validée par un run » N'EST PAS levé.** |
| **Fix §0.13** | ✅ **VALIDÉ RUNTIME.** Le ranking porte sur `holdout_regular_bot-01` / `-02` — l'éval finale joue bien le pool **holdout**, plus le scénario d'entraînement. |
| Reward §0.12 | Le run tourne sans incident avec la `VALUE` par figurine et l'event `model_value`. Aucun crash du chemin d'allocation. |

**Résultats de l'évaluation finale (12 épisodes = 2 par bot) :**

```
  vs adaptive            :  50.0% (1W-1L-0D)
  vs aggressive_smart    :  50.0% (1W-1L-0D)
  vs control             :   0.0% (0W-2L-0D)
  vs defensive           : 100.0% (2W-0L-0D)
  vs greedy              : 100.0% (2W-0L-0D)
  vs tactical            : 100.0% (2W-0L-0D)   <-- holdout
  Combined Score:  61.5%

🏁 Scenario ranking (combined):
  - holdout_regular_bot-01: combined=0.770 | worst_bot_score=0.000
  - holdout_regular_bot-02: combined=0.460 | worst_bot_score=0.000
```

**🔴 Ce que ce run NE prouve PAS — le score reste NON CONCLUANT.**

- **2 épisodes par bot.** `bot_eval_final` vaut **2** dans la phase `x5_debug`. C'est bien
  « > 1 » comme l'exigeait cette entrée, mais **12 épisodes ne permettent aucune conclusion** :
  chaque bot est un 2W-0L / 1W-1L / 0W-2L, soit une résolution de 50 points de pourcentage.
  Le `61.5 %` est un chiffre **indicatif**, à ne PAS reporter dans [§10.6](V11_eval_strategy.md#s10.6).
- **500 épisodes d'entraînement, ce n'est pas un agent entraîné.** Les phases réelles sont à
  10 000–30 000 (`x1`, `x5_new`, `x5_append`). Ce run valide le **pipeline**, pas la politique.
- **`vs tactical: 100 %` ne vaut rien comme signal de holdout** à 2 épisodes — c'est
  précisément le chiffre qu'on voudrait fiable, et c'est celui qui a le moins d'échantillon.
- ⚠️ **`vs control : 0 % (0W-2L)`** est le seul résultat qui mérite un œil : c'est le
  `worst_bot_score=0.000` des deux scénarios. À 2 épisodes ce peut être du bruit pur ; **à
  reconfronter au prochain run long** avant d'y voir un trou de comportement.

**🔴 DEUXIÈME RUN — CRASH, voir §0.18.** Un run relancé avec la **même commande** après le
correctif de la rupture D s'est arrêté à l'**épisode ~280** sur
`ValueError: execute_squad_move a échoué … collision intra-plan`. **§0.11 n'est donc pas
résolu.** C'est la conclusion la plus importante de cette entrée, et elle contredit ce que le
premier run laissait croire.

**🔴 INVALIDÉ A POSTERIORI (même jour) — la rupture D de §0.12.** Ce run a tourné **avant** la
découverte de la régression d'observation (`value_over_ttk` extrapolait le `points_per_hp` de la
figurine d'index 0). Les deux rosters de [§10.2](V11_eval_strategy.md#s10.2) étant hétérogènes en points, **l'agent s'est
entraîné sur une observation fausse** pendant les 500 épisodes. Ce qui reste valable malgré
tout : la **non-régression §0.11** et la **validation runtime du fix §0.13**, qui ne dépendent
ni du reward ni de l'observation. Le score, lui, est à jeter deux fois plutôt qu'une.

**Ce qui reste à faire pour fermer cette entrée** : un run sur une phase à `bot_eval_final`
élevé (`x1`, `x5_new` et `x5_append` sont déjà à **100**) et à `total_episodes` réel, pour
produire un win-rate **par roster** interprétable au sens de [§10.6](V11_eval_strategy.md#s10.6). ⚠️ Cf. **§0.15** : les
rosters `training` et `holdout_regular` étant identiques, ce win-rate mesurera la robustesse à
l'**adversaire**, jamais au roster.

**🟠 MAJ 2026-07-22 — le run réel a ENFIN été lancé, et il a franchi la non-régression mais s'est
arrêté à l'éval.** Commande exacte : `python3 ai/train.py --agent ArmageddonAgent --scenario bot
--new --training-config x5_new` (10k ép. **à l'époque** — `x5_new` porte 5 000 épisodes depuis, relevé le 2026-08-02 ; 48 envs, `bot_eval_final=100`), lancée après le
réalignement complet de l'instrument (§0.23 logger per-figurine, §0.24 analyzer per-figurine) et la
correction d'un **vrai bug moteur de move** découvert par l'analyzer fiabilisé (§0.25 budget
ligne-droite → géodésique ; §0.26 régression cache). **Le training a atteint l'épisode 2000 (20 %)
sans un seul crash `incohérence masque/exécution`** en ~3 h 40 — la conformité move et la
non-régression tiennent sur un vrai run 48-envs. **Mais** le premier checkpoint d'évaluation (marker
2000) a déclenché le garde-fou strict d'éval : **500 épisodes d'éval `failed` sur timeout de task**
→ arrêt. **Aucun win-rate n'a donc été produit.** Le score par matchup reste dû, désormais bloqué par
**§0.27** (et non plus par la perf du pool §0.22, ni par un défaut d'instrument). ⚠️ Cette entrée
confirme une fois de plus la leçon §0bis « un run vert ne prouve rien » : le fix move §0.25 avait
passé un `--step` de 4 épisodes puis **crashé en 1 min** sur un vrai run 48-envs (cf. §0.26) — c'est
le run multi-env, pas le smoke, qui a validé.

<a id="s0bis"></a>
## 0bis. Pièges et leçons de méthode — 📌 SECTION CANONIQUE

> **Éditer les avertissements ICI.** Chacun est reproduit **mot pour mot** depuis son entrée
> d'origine, dont la référence est donnée. Les occurrences restées dans §0hist en sont des
> **copies** : elles y documentent le raisonnement local, mais la version qui fait foi est
> celle de cette section.
>
> Ces passages existent pour **empêcher de re-diagnostiquer un faux problème**. Aucun ne doit
> être résumé ni supprimé, même si l'entrée dont il vient est close.

### Un « ✅ SAIN » prononcé sur UNE règle ne dit rien des règles SATELLITES qui la modifient (§0.50, 2026-07-29)

Écrit en corrigeant 01.07 (une unité **battle-shocked** contrôlait ses objectifs normalement).
[`V11_tranches.md:157-159`](V11_tranches.md#L157) affirmait :
*« ✅ **Le vrai Objective Control est SAIN** : `_sum_objective_control_oc` compte bien
OC × figurines dans la zone (14.02). Ce sont les règles satellites qui n'ont pas suivi. »*
(la phrase est **barrée à la source** depuis le 2026-07-29, avec la mention « AFFIRMATION FAUSSE ») L'audit qui a produit cette phrase cherchait
**un** défaut précis — le calcul à l'ancre d'escouade au lieu du par-figurine — et l'a correctement
écarté. Mais la phrase écrite dit bien plus que ce qui a été vérifié, et c'est **elle** qui a rendu
le défaut invisible pendant des mois : quiconque relisait le contrôle d'objectif lisait d'abord
« SAIN » et passait. La fonction ne consultait **jamais** `battle_shocked`, alors que **01.07** met
l'OC de toutes les figurines d'une unité choquée à `'-'` et que **02.02** rend alors la figurine
incapable de contrôler.

**Règle.** Vérifier qu'une fonction applique correctement la règle **R** n'autorise à conclure que
sur **R**. Une caractéristique de jeu est presque toujours **modifiée par des règles satellites**
(états, mots-clés, auras, phases) qui vivent dans **d'autres PDF** que celui de la règle principale
— ici l'OC est décrit en 14.02, mais **modifié** en 01.07 et **interprété** en 02.02. Donc :

- **Ne jamais écrire « SAIN » / « CONFORME » sans le quantifier** : dire *« conforme à 14.02 sur le
  décompte par figurine »*, jamais *« le contrôle d'objectif est sain »*. Un verdict non borné est
  un **verdict faux dès la première règle non testée**.
- **Avant de conclure, énumérer les modificateurs** : quelles règles écrivent, annulent ou
  remplacent la caractéristique lue ? La recherche se fait dans les PDF (`Documentation/40k_rules/`),
  pas dans le code — le code ne peut pas révéler une règle qu'il n'implémente pas.
- **Le verdict le plus dangereux est le verdict RASSURANT.** Un « ÉCART » relance une lecture ; un
  « SAIN » la clôt. C'est pourquoi un ✅ mérite plus de justification écrite qu'un 🔴, et non moins.
- Corollaire pour ce document : une phrase de doc peut **couvrir** un bug aussi efficacement qu'un
  test faux. Quand un audit contredit une affirmation ✅ existante, l'affirmation doit être
  **annotée à sa source**, pas seulement contredite ailleurs.

### Un test qui contourne `__init__` atteste que la production ne peut pas construire l'objet (§0.45, 2026-07-29)

Écrit en supprimant `ai/scenario_manager.py`. Ses **9 tests** commençaient tous par le même stub :

```python
manager = ScenarioManager.__new__(ScenarioManager)   # constructeur JAMAIS appelé
manager.scenario_templates = {...}                    # etat injecte a la main
```

Le constructeur était contourné pour une raison précise : il **lève**. `_load_scenario_templates`
exige `config/scenario_templates.json`, absent du dépôt, et refuse tout fallback. Autrement dit
`ScenarioManager(…)` était **inconstructible en production depuis toujours**, et les tests
mesuraient un objet que le code applicatif ne pouvait pas obtenir. Ils étaient verts, et ils
n'ont jamais couvert un chemin exécutable.

**Règle** : `__new__`, `object.__setattr__`, un `MagicMock` substitué au constructeur, ou tout
montage qui saute l'initialisation réelle, sont des **indices de code mort**, pas des astuces de
test. Avant de les accepter, exiger la réponse à : *quel appelant de production construit cet
objet, et cette construction réussit-elle ?* Si la réponse est « aucun » ou « elle lève », le
sujet n'est pas le test — c'est la cible. Corollaire pour l'audit de code mort : **un compte de
tests verts n'est pas une preuve de vie**.

### Un canal d'observation NON VIDE ne prouve pas qu'il regarde au bon endroit (§0.40, 2026-07-28)

Écrit en corrigeant l'ancre de la grille égocentrique pendant le déploiement (§0.40 point 2).
Le premier verrou écrit était : *« pendant le déploiement, le canal murs et le canal objectifs de
la grille ne sont pas vides »*. Il était **vert AVANT le correctif** — donc il ne prouvait rien.

**Pourquoi** : le board fait 220×300 et la fenêtre égocentrique en couvre ±90. Ancrée sur la
sentinelle `(-1,-1)`, elle montrait le coin `(0,0)` du plateau — une région pleine de murs et
d'objectifs, simplement **pas celle où l'unité allait se poser** (la zone du joueur 1 commence à la
ligne 151). Une ancre fausse ne produit pas une grille vide : elle produit une grille **plausible
et fausse**, exactement le motif d'erreur le plus difficile à voir en lecture.

**Ce qui verrouille vraiment** — deux assertions, pas une :
1. une grandeur **quantifiée et comparable** (ici : la part des hexes de la zone de déploiement qui
   tombent dans la fenêtre — 0 %/25 % avant, 96 %/78 % après) plutôt qu'un `.any()` ;
2. une **égalité exacte** entre le canal produit et une rasterisation indépendante depuis l'ancre
   attendue. C'est elle, et elle seule, qui verrouille le **câblage** dans `build_squad_grid` :
   tester la fonction d'ancrage isolément laissait passer la mutation qui remettait l'ancienne
   ancre à l'appel.

**Règle** : un test d'observation spatiale doit affirmer **où** la fenêtre regarde, jamais
seulement **qu'elle contient quelque chose**. Et tout verrou d'obs se valide par mutation : casser
le correctif, exiger le rouge, restaurer, exiger le vert.

### Ne pas juger une conformité de règle par une reconstruction offline — mesurer sur le vrai chemin in-engine (§0.28, 2026-07-22)

Un soupçon de « tir à travers terrain » (obscuring 13.10) a coûté une **cascade de faux verdicts**
avant d'être **réfuté** par une mesure in-engine. Les pièges, dans l'ordre où ils ont trompé :
1. **Scan offline centre→centre** : la LoS légale est **footprint→footprint par-figurine** (06.01, un
   bord de socle voit ce que le centre ne voit pas). Tester centre→centre sur-flagge en masse. Ce
   motif est le **même** que celui qui a fait retirer le contrôle LoS de l'analyzer (§0.24 /
   `project_analyzer_los_verdict`).
2. **Rejeu headless non fidèle** : `place()` écrivait `unit["col"/"row"]` alors que le moteur lit
   `units_cache` (`require_unit_position`) → unités restées à `(-1,-1)` → LoS triviale. Puis même
   corrigé, l'arme/portée/état divergeaient du training. **Un rejeu doit vérifier son propre setup**
   (assert `require_unit_position == position attendue`) avant de conclure quoi que ce soit.
3. **Instrumenter le mauvais chemin** : 6 points instrumentés (compute_unit_los, valid_target_pool_build,
   pool cache-hit, w40k_core log, action_decoder legacy) ont montré **0 hit** — le pipeline squad V11
   n'emprunte AUCUN. Le vrai gate est `build_squad_action_mask` → `_model_can_shoot_target` →
   `_attacker_model_can_reach_squad`. **Toujours tracer `env.get_action_mask` d'abord**, ne pas deviner.
4. **Env var non propagée** : un audit gardé par `W40K_LOS_AUDIT` montrait 0 hit ; en inconditionnel,
   297. Vérifier qu'une instrumentation gardée **s'exécute vraiment** (heartbeat) avant d'interpréter un 0.

**Règle** : une affirmation de (non-)conformité de règle n'est valide **que** mesurée dans le moteur, sur
le chemin réellement emprunté, avec un heartbeat qui prouve que la sonde tourne. Une reconstruction
offline ne prouve rien sur la conformité.

### Sur ce document lui-même (§0.-1, §0.0)


**Réserve de méthode — ce qui n'a pas été revérifié (§0.0)**

**⚠️ Réserve de méthode sur ce document.** Les sections §0.x reflètent ce qui a été relu et
exécuté pendant la session du 2026-07-19 soir. **Le reste du document — T1 à T5, section 9 — n'a
PAS été revérifié ligne à ligne contre le code.** Trois affirmations périmées y ont été trouvées
et corrigées ce soir-là (« prochain bloqueur [§10.4](V11_eval_strategy.md#s10.4) » alors qu'il était résolu, « archivage des
holdouts à faire » alors qu'il l'était, « 9 échecs préexistants » alors que la suite est verte) —
**il peut en rester d'autres du même genre**. Vérifier dans le code avant de s'appuyer sur une
affirmation de ce document qui n'est pas datée de la session en cours.

➜ **Cette réserve est désormais une TÂCHE : voir §0.19** (méthode d'audit et historique des
démentis). Tant qu'elle n'est pas menée, la mise en garde ci-dessus reste pleinement valable.

➜ **Relecture T2→T5 menée le 2026-07-29 : voir [§0.47](#s0.47)** — **9 écarts** (T2 et T4 en
écart, T3 et T5 conformes). Elle confirme une fois de plus la réserve ci-dessus. **Elle ne la lève
pas** : elle s'est faite **par lecture seule, sans exécuter un seul test** (run 4 en cours,
working tree gelé), donc sans mutation-test.

➜ **Passe menée le 2026-07-20 : voir §0.19.1.** T2/T3/T4/T5 sont verrouillés par mutation-test ;
**T1 est repassée en ⏳** (R6 site 1 inatteignable au x5, R4 sans aucun test) ; la section 9 n'a
jamais été marquée ✅ (c'est un plan). La réserve reste valable pour **T1/R4**, dont le
mutation-test n'a pas pu être mené (`shared_utils.py` sous instrumentation §0.18), et pour [§7](V11_tranches.md#s7)/[§10](V11_eval_strategy.md#s10)
qui n'ont **pas** été audités.

**Comptages de tests : le seul verdict disponible est le code de sortie (§0.-1)**

⚠️ **Chiffre daté du 2026-07-19** — la suite a grossi depuis (+6 tests le 2026-07-20 : 4 en
§0.10, 2 en §0.13). **Ne pas traiter `1402` comme un compte à retrouver** : le reporter du
projet n'imprime pas la ligne de résumé de pytest, le seul verdict disponible est le **code de
sortie** (`exit 0`, vérifié après chaque lot du 2026-07-20).

**La règle de périmètre `ArmageddonAgent` et les 10 fichiers `CoreAgent` verts (§0.-1)**

⚠️ **10 fichiers de tests contiennent encore la chaîne `CoreAgent` et sont VERTS — c'est
normal.** Audités **un par un** (et non par échantillon — la première vérification avait manqué
`test_board_ref_resolver.py` ci-dessus en généralisant depuis 3 fichiers de `tests/unit/ai/`
alors que le seul cas fautif était dans `tests/unit/engine/`) : ce sont des chaînes passées à des
fonctions **pures** (`_load_bot_eval_params`, `build_agent_model_path`, `_scenario_name_from_file`),
des stubs (`SimpleNamespace`, `_DummyCfgLoader`, `_Cfg`), des arborescences **synthétiques dans
`tmp_path`**, ou de simples commentaires. **Aucun n'atteint la vraie config.** Ne pas les
« corriger » par un `sed` global.

**Leçon de méthode** : « vérifié un par un » sur un échantillon n'est pas une vérification.
Le seul contre-exemple était dans le répertoire non échantillonné.

### Un smoke à UN épisode ne voit pas un état qui fuit ENTRE épisodes (§0.42, 2026-07-28)

Le mécanisme de décision agent ([§9.3](V11_phaseA.md#s9.3) P2) a été validé par un smoke in-engine : 28 décisions
exposées et jouées, épisodes terminés, aucun masque vide. Le smoke lançait **un épisode par
moteur**. Le contre-audit a rejoué **3 épisodes enchaînés dans le MÊME moteur** : **16 décisions,
puis 2, puis 0**. `_choice_timing_fired_events` indexe ses événements sans le numéro d'épisode et
`reset()` ne le purgeait pas — le mécanisme s'éteignait après le premier épisode d'un run, sans
qu'aucun test ni aucun smoke ne rougisse.

**Règle** : tout état de `game_state` ajouté par une tranche doit être confronté au `reset()`, et
la mesure de validation doit **enchaîner plusieurs épisodes sur le même moteur** — c'est le seul
protocole qui montre une fuite d'état. Un compteur d'événements « déjà tirés » est le cas type :
il est correct dans l'épisode, faux entre deux.

### Un test qui passe du premier coup n'est pas encore un verrou (§0.43, 2026-07-28)

Les 8 premiers tests de parité masque/commit de la cible de charge sont passés **au premier
essai**. Trois mutations ont été appliquées pour vérifier qu'ils mordaient : masque sans filtre
d'éligibilité, commit sans garde d'éligibilité, décodeur décalé d'un slot — les trois ont bien
rougi. Mais l'une d'elles a révélé qu'un test **ne discriminait pas** : « les slots ouverts ==
les cibles déclarables » était vrai trivialement, parce que *toutes* les cibles mappées du
scénario étaient à portée. Il a fallu **fabriquer** le cas contraire (éloigner une cible au-delà
de 12" et vérifier que son slot se ferme) pour que l'assertion ait un contenu.

**Règle** : quand un test neuf passe sans avoir jamais échoué, appliquer la mutation qu'il est
censé attraper. Si elle ne le fait pas rougir, le test décrit la fixture, pas le code. Le même
raisonnement vaut pour une feature d'observation : la justifier exige une **contre-épreuve à
variable unique** (ici : même `edge_distance`, atteignabilité opposée), sinon rien ne prouve que
le champ existant ne suffisait pas.

### Migrer un test de code mort vers le vif est un AUDIT de conformité, pas un refactor (§0.38, 2026-07-28)

Les 5 fichiers qui tenaient `_attack_sequence_rng` en vie portaient 138 assertions vertes. En les
re-pointant sur le chemin vif, **11 d'entre elles se sont mises à contredire le moteur**. Le
réflexe naturel — assouplir l'assertion, ou « adapter le test au nouveau chemin » — aurait détruit
le seul résultat de valeur de la manœuvre : chacune de ces 11 assertions décrivait un comportement
**contraire au PDF**, que le code mort implémentait et que le vif avait corrigé ([HAZARDOUS] 24.15
jeté par attaque au lieu d'une fois par arme après toutes les attaques ; [HEAVY] 24.16 avec une
clause sur trois).

**Règle** : une assertion qui rougit en migrant est un **verdict à instruire**, pas un test à
réparer. On lit le PDF, on désigne qui a tort, et on écrit la réponse dans la doc comme un constat
de conformité. Corollaire opérationnel : ne jamais supprimer une assertion « parce qu'elle est
dupliquée ailleurs » sans avoir vérifié la couverture **assertion par assertion** — c'est ce
recensement qui a fait apparaître que [HAZARDOUS] en **mêlée** n'était couvert par rien, alors même
que le fichier censé le couvrir s'appelait `test_fight_special_rules.py` et ne testait que du tir.

**Second corollaire** : un état orphelin ne se juge jamais sur la ressemblance de son nom. Les
7 champs `_rapid_fire_*` supprimés ici étaient morts, mais [RAPID FIRE] 24.30 est bien VIVE — dans
un autre module, sous un autre mécanisme. Symétriquement, les branches `squad path expected` que
§9.2 listait comme résidus sont sur un chemin **vif** : les supprimer aurait dégradé une erreur
explicite en retour silencieux. Preuve d'appelant exigée dans les deux sens, avant toute suppression.

**Troisième corollaire, appris à la relecture** : *un grep sur un libellé n'est pas un recensement*.
Trois chiffres de la première rédaction de §0.38 étaient faux pour cette raison — « 6 fichiers de
tests » (5 appelaient réellement le mort, le 6ᵉ ne le citait qu'en commentaire), « ~159 assertions »
(138), « 4 branches-gardes » (5, la cinquième portant un autre message). Recompter coûte une
commande ; publier un chiffre repris d'un énoncé coûte la confiance dans tous les autres. Ce qui se
compte se compte **par la propriété visée** (`grep -c '= la_fonction('`, `raise RuntimeError`,
l'AST), jamais par la phrase qu'on s'attend à lire.

### Un script de mutation qui restaure par `git checkout --` DÉTRUIT le travail non commité (§0.38, 2026-07-29)

La contre-épreuve par mutation consiste à casser le code, relancer, puis restaurer. Restaurer avec
`git checkout -- <fichier>` marche tant que le fichier est **commité**. Le 2026-07-29, deux salves
ont tourné sur des correctifs **non encore commités** : chaque « restauration » a silencieusement
ramené le fichier au dernier commit, effaçant les modifications en cours. Aucune erreur, aucun
avertissement — le symptôme est apparu plus tard, sous la forme d'un « RESTAURÉ : rouge » en fin de
script, alors que le vrai dégât était déjà fait.

**Règle** : un harnais de mutation restaure depuis un **snapshot du contenu** pris juste avant la
mutation, jamais depuis git. Git ignore ce qui n'est pas commité, et c'est précisément ce qu'on est
en train d'écrire quand on teste. Corollaire : **commiter avant de lancer les mutations** — le
commit est de toute façon la bonne granularité (un fix = ses tests), et il rend le harnais inoffensif.

### Une garde « de performance » non mesurée est souvent du travail EN DOUBLE (§0.43, 2026-07-28)

`charge_reachable_max_roll` avait été écrit sous **deux** gardes : la phase de charge, et
l'éligibilité 11.02 de la cible. La première était documentée comme une garde de coût — et la
seconde aussi, dans les mêmes termes. Le contre-audit a mesuré : `charge_build_valid_plan`
**commence lui-même** par `charge_check_eligibility`, donc le pré-test était **double** pour une
cible déclarable et **sans gain** pour une cible hors portée. Il n'existait aucun cas où il
gagnait. Il a été retiré.

⚠️ Et la première rédaction de cette leçon affirmait exactement le contraire (« la seconde est
purement une garde de coût ») : **une justification de perf écrite sans mesure peut être fausse
au point de survivre à sa propre leçon.**

**Règle** : une garde présentée comme une optimisation se justifie par une **mesure**, et la
mesure la plus probante n'est pas le chrono (bruité, ici le gain — 42 µs par cible — était du
même ordre que la variance) mais le **comptage d'appels**, qui est déterministe : 4 appels
d'éligibilité pour 2 cibles disait tout. Compter avant de chronométrer.

### Un comportement obtenu par effet de bord n'est pas un comportement décidé (§0.42, 2026-07-28)

Une action `agent_decision` recevait un reward de 0.0 — la valeur voulue — mais **uniquement**
parce que son payload contient la clé `waiting_for_player`, qui la faisait classer « réponse
système » par `RewardCalculator`. Retirer cette clé du payload l'aurait basculée dans le chemin
« unité agissante » : reward d'unité arbitraire, ou `ValueError`. Le comportement était juste, sa
cause était accidentelle, et rien ne l'aurait signalé.

**Règle** : quand un chemin nouveau traverse un code de dispatch existant, vérifier **par quelle
branche** il passe, pas seulement **ce qu'il rend**. Un test qui n'observe que la valeur de sortie
ne distingue pas « par conception » de « par effet de bord » — il faut la mutation qui retire la
cause accidentelle.

### Sur le raisonnement et la preuve


**Une piste écrite dans une note « hors périmètre » est une hypothèse, pas un diagnostic (§0.34, 2026-07-28).**
La note de §0.32 désignait le bon fichier, la bonne fonction et la bonne ligne
(`erode_move_pool_by_squad_block`, court-circuit mono-figurine) — et **la mauvaise cause**. La vraie
divergence était en amont : la frontière normal/advance était calculée sur le `MOVE` **brut** quand le
pool et l'exécution appliquent `MOVE − coût de descente`. Le court-circuit ne faisait que **retirer le
filet** qui masquait le bug ailleurs : sur les escouades multi-figurines, l'érosion « corrigeait » la
bande morte en **supprimant silencieusement des Advances légaux**. Deux corollaires :
1. **Un bug partiellement masqué par un filet se déguise en cas particulier.** « Ça ne touche que les
   mono-figurines » était vrai pour le *crash* et faux pour le *défaut* : 100 % des escouades
   descendantes perdaient des coups légaux.
2. **Corriger là où ça crashe aurait aggravé le défaut** (érosion étendue au mono = crash supprimé,
   coups légaux perdus partout). Avant de corriger le site du raise, vérifier **quelle grandeur** chaque
   côté de l'invariant mesure — c'est le motif §0.18/§0.26 pour la troisième fois.

**Vérifier SUR QUEL scénario un chiffre a été mesuré avant de le transformer en blocage (§0.34, 2026-07-28).**
« 43 occurrences / 650 pas, le training ne peut pas tourner » : les 43 venaient du harnais de bench de
T-K/T-L, qui tourne sur **`scenario_pvp_test`** — le seul scénario portant une escouade à `level: 1`. Le
scénario d'ENTRAÎNEMENT mesuré dans les mêmes conditions donne **0**, en x1 comme en x5. Le bug était
réel et il est corrigé, mais il ne bloquait pas le run §0.14. Un chiffre sans son scénario n'est pas
une fréquence, c'est une anecdote.

**Prototyper + bencher AVANT d'intégrer un levier perf (§0.22, 2026-07-21) — la mesure prime sur le plan écrit.**
Le chantier `MOVE_POOL_BUILD` a fait CINQ mesures qui ont chacune démenti une hypothèse « évidente » du
plan §8 de `V11_move_build_acceleration.md`, et un prototype hors-prod les a toutes attrapées avant tout code de prod :
1. Le plan désignait le **BFS** comme reliquat n°1 (« 66 % sur petits socles », profil §2bis). Mesuré :
   le BFS deque isolé ne coûte que **0,30 ms à move_range=12** (le régime réel du training, lui aussi
   mesuré, pas supposé). Le profil §2bis englobait autre chose.
2. Le plan proposait un **wavefront bbox-NumPy** pour le BFS. Prototype prouvé équivalent (reach+dist)
   mais **plus lent à move 12** (0,46×) ; il ne gagne qu'à move≥30. Réfuté.
3. Le vrai hotspot mesuré (cProfile) = la **boucle Python sur les offsets** de `_dilate`/`_spread`
   (gros socles), que le §8 de `V11_move_build_acceleration.md` avait déclaré « caduc ». Réhabilité par la mesure.
4. **L2b par lignes** (décompo runs) : l'empreinte **ovale n'est pas contiguë par ligne** en coords hex
   → fallback sur le socle qui compte. Réfuté.
5. **L2b par colonnes** (sparse-table) : équivalent, mais 1,34× ovale seulement / <1× petits socles →
   gain net ~1,1× pour une vraie complexité. Non intégré.
**Leçon** : un profil agrégé (« X = 66 % ») ne dit PAS quel code optimiser — il faut mesurer le
**régime réel** (ici `move_range`, le socle, l'`ez`) et **prototyper le remplacement en A/B équivalent
+ bench AVANT de toucher la prod**. Le filet de tests (oracle + snapshot + A/B fenêtré==plein-board)
garantissait qu'aucune régression métier ne pouvait passer ; le bench a garanti qu'aucune complexité
inutile n'a été livrée. Seuls **L1 + L_bbox** (gain sûr, sans dépendance) ont été retenus ; décision
**(B) STOP**. Détail complet → `V11_move_build_acceleration.md §3`.

**« Un run vert ne prouve rien » — DEUX confirmations de plus la nuit du 2026-07-22 (§0.25/§0.26).**
Le motif §0.11/§0.18 s'est répété deux fois en une nuit : (1) le fix move §0.25 a passé un `--step` de
**4 épisodes mono-env**, puis a **crashé en ~1 min** sur un vrai run 48-envs (`incohérence
masque/exécution`, §0.26) — le crash dépend de la trajectoire, qu'un smoke court ne visite pas ;
(2) c'est un **test déterministe reproduisant la condition exacte du crash** (occupation sans bump de
version → cache périmé) qui a verrouillé le fix, pas un run vert. **Règle renforcée : pour un invariant
(masque⊆exécutable, terminaison, budget), la preuve est un TEST QUI REPRODUIT L'ÉCHEC, pas un run qui
passe.** Le vrai run multi-env reste le juge final (le `--step` mono-env est structurellement aveugle
aux races de cache et aux états rares). Corollaire opérationnel : ne JAMAIS relancer un run coûteux
(19 h) sur la foi d'un smoke ; passer par un run multi-env qui franchit la zone de crash connue.

**Vérifier le PÉRIMÈTRE d'un travail délégué avant de l'accepter (2026-07-22).** Un agent chargé de
corriger l'analyzer (puis un autre le moteur) a livré, **sans le déclarer**, une refonte hors-périmètre
de `services/api_server.py` (**366 lignes**, −265/+104) + un `defaults.agent` dans `config/config.json`
— non lu par le chemin d'entraînement, non demandé. Détecté par `git status` avant tout commit et
**révoqué** (`git checkout -- config/config.json services/api_server.py`). **Ne jamais faire confiance
au « je n'ai touché que X » d'un agent : diffuser `git status`/`git diff` sur l'ARBRE ENTIER, pas sur
les fichiers annoncés.** Les agents restaurent aussi leurs propres backups de modèle → vérifier le md5
du `.zip` canonique (il n'a PAS à changer hors run `--new` voulu).

**Mesurer/lire AVANT d'affirmer une root cause (2026-07-22).** Deux affirmations trop rapides corrigées
la même nuit : (a) les 5508 « erreurs » analyzer qualifiées de « faux positifs » **avant de les avoir
lues** — en réalité un mélange de vrais bugs analyzer (§0.24) ET d'un vrai bug moteur (§0.25) ; (b) le
crash §0.26 attribué à « l'érosion d'occupation » alors que la root cause était le **cache** (trouvée
en instrumentant `build_squad_move_cell_map`, pas en devinant). **Un profil/compteur agrégé ou une
analogie ne DÉSIGNENT pas la cause : instrumenter le régime réel, puis conclure.** (Même leçon que la
perf §0.22 ci-dessus, re-vérifiée côté correction de bug.)

**Fiabiliser l'INSTRUMENT avant de l'utiliser comme juge (2026-07-22, §0.23/§0.24).** L'analyzer était
l'unique validateur du training mais restait pré-squad (ancre) → il ne pouvait ni prouver la
conformité, ni être cru quand il criait. Tant qu'un instrument de validation n'est pas réaligné sur la
V11 (per-figurine) ET prouvé sans faux positif sur les vraies unités, **toute mesure produite avec est
suspecte dans les deux sens** (faux positifs qui masquent + potentiels vrais bugs non vus). Le
réalignement a **payé immédiatement** : l'analyzer fiabilisé a fait émerger un vrai bug moteur (§0.25)
invisible jusque-là.

**Une contrainte de conformité peut être INCOMPATIBLE avec une décision de perf close (2026-07-22).**
§0.22 a été clos « STOP » pour ne pas payer le BFS par-socle. Mais la conformité move (§0.25) l'EXIGE
(érosion géodésique par-figurine) : la décision perf est **rouverte de facto par une exigence règles**,
pas par un choix d'optimisation. Quand une entrée est close sur un arbitrage coût/gain, vérifier qu'une
exigence de correction ne la rend pas caduque avant de s'appuyer sur sa clôture. Conséquence vive :
§0.27 (éval trop lente).

**Une invariance est CONDITIONNELLE à son état initial (§0.1)**

**⚠️ Corollaire — une affirmation de ce document était fausse.** L'ancien §0 affirmait que
`require_coherency` est « invariante par translation cube, donc déjà garantie par le pool
d'ancre ». L'invariance est réelle mais **conditionnelle** : elle prouve *si l'origine est
cohérente, le plan l'est*. Elle ne prouve **rien** quand l'origine est déjà incohérente — et dans
ce cas le pool entier est offert alors que rien n'est exécutable. C'est cette demi-vérité qui a
laissé le trou ouvert après T6-g. **Toute contrainte « prouvée invariante » doit être relue en se
demandant : invariante à partir de quel état initial ?**

**Suite (2026-07-29) — les DEUX moitiés sont fermées.** (a) L'invariance elle-même était FAUSSE en
mode euclidien : la 2e puce de 03.03 centrait un cercle sur « la paire la plus éloignée », or
plusieurs paires sont souvent à distance maximale EXACTEMENT égale sur grille hex → le centre, donc
le verdict d'une figurine au bord, était départagé par le bruit flottant, qui change avec la position
absolue de l'escouade. Critère passé PAR PAIRES (ce que dit le PDF) ; verrou
`test_coherency_translation_invariance.py`. (b) L'état initial était réellement incohérent : la
réduction de roster x5→x1 (`_downscale_fixed_unit`) décalait chaque figurine indépendamment, borne
PAR FIGURINE qui ne dit rien de la formation. Elle pose maintenant une chaîne connexe par
construction ; verrou `test_roster_downscale_coherency.py`. C'était le SEUL chemin de placement du
moteur sans contrôle de cohérence.

**Vérifier qu'un point d'ancrage est APPELÉ avant d'y brancher quoi que ce soit (§0.1)**

⚠️ **Piège rencontré, à ne pas refaire** : le premier branchement a été posé en tête de
`_advance_to_next_player`, qui *semble* être la frontière de tour mais est **du code mort**
(cf. §0.4). Le run de vérification a reproduit le crash à l'identique. **Vérifier qu'un point
d'ancrage est appelé AVANT d'y brancher quoi que ce soit.**

**Motif récurrent : du code correct, testé, et jamais appelé (§0.4)**

> **Motif récurrent à surveiller dans ce projet** — six occurrences vérifiées à ce jour.
> **Cinq de type « jamais appelé »** : `update_frozen_model` ([§10.4](V11_eval_strategy.md#s10.4)),
> `end_of_turn_coherency_removal` (§0.1), `_advance_to_next_player` (§0.4),
> `game_replay_logger` (§0.8, 795 lignes + 8 tests), `log_unified_action` (§0.8). Du code
> correct, testé, et jamais appelé. **Devant toute fonction sur laquelle repose un
> raisonnement, vérifier d'abord qu'elle a un appelant.**
>
> **Une de type « jamais exercé »** (§0.11) : `test_move_mask_is_executable.py` est appelé, vert,
> et mesure le bon invariant sur le bon scénario — mais par exploration aléatoire, donc il ne
> visite jamais la configuration qui cassait. **Un test vert ne couvre que les états qu'il
> atteint ; sa docstring peut affirmer le contraire de bonne foi.**

**Un test qui explore au hasard ne prouve rien sur ce qu'il n'atteint pas (§0.11)**

🔴 **Pourquoi `test_move_mask_is_executable.py` n'a rien vu** — c'est le point le plus important
de cette entrée. Ce fichier mesure **cet invariant exact**, sur **ce scénario exact**, et il est
vert. Il ne vérifie l'invariant que sur les états atteints par **exploration aléatoire** (3 seeds,
400 steps) : la superposition inter-étages n'y survient jamais. Sa docstring affirme pourtant
combler précisément ce trou (« Ce test remplace ce raisonnement par une mesure »).

> **Quatrième variante du motif §0.4, et la plus sournoise.** Les trois premières étaient du code
> *jamais appelé*. Celle-ci est du code appelé, par un test vert, qui **n'exerce jamais le cas**.
> Un test qui explore au hasard ne prouve rien sur les configurations qu'il n'atteint pas — et sa
> docstring peut affirmer le contraire en toute bonne foi. **Devant un test de type « je déroule
> des parties et je vérifie un invariant », toujours se demander quelles configurations il ne
> visite jamais, et les construire explicitement.**

**Ne pas conclure à un biais de tirage sur quelques dizaines d'observations (§0.10)**

Mesuré sur **400 resets** : Ork/Ork 102 (25,5 %), Ork/SM 107 (26,8 %), SM/SM 104 (26,0 %),
SM/Ork 87 (21,8 %) — **les 4 matchups, équiprobables** (χ² = 2,38 pour un seuil de 7,81 à 3 ddl :
aucun biais détectable). Un premier tir de 40 resets donnait 15/13/9/**3** et laissait craindre un
biais : c'était du **bruit d'échantillonnage**, pas un bug. Leçon : ne pas conclure à un biais de
tirage sur quelques dizaines d'observations — refaire la mesure en grand avant de diagnostiquer.

> **Bandeau de fiabilité du recensement d'ancre** — il vit en **[§1bis](V11_tranches.md#s1bis), « Dette d'ancre restante »**
> et n'a pas été déplacé : seuls 4 sites y ont été relus à la main, le reste est un faisceau
> d'indices. **Ne pas ouvrir de chantier depuis une ligne non marquée ✅ sans avoir lu la
> fonction.** Le lire avant d'exploiter ce recensement.

### Sur les runs et l'outillage


**Un run déjà lancé n'est PAS protégé d'un changement de code : `spawn` relit le disque (§0.41, 2026-07-28)**

Les workers d'entraînement sont forkés une fois au démarrage, ce qui laisse croire qu'éditer le
code pendant un run est sans effet sur lui. **C'est faux.** `ai/bot_evaluation.py` crée ses
workers d'évaluation avec `mp.get_context("spawn")` — un worker `spawn` **ré-importe tout le code
depuis le disque**. Un changement d'espace d'action ou d'observation posé sur `main` pendant un
run fait donc diverger le modèle en mémoire (ancien `TOTAL_ACTION_SIZE`) et les workers d'éval
(nouveau) : plantage à l'évaluation suivante, ou pire, mesure fausse. **Avant de conclure qu'un
run en cours est protégé, vérifier le mode de démarrage de CHAQUE famille de sous-processus.**
Parade appliquée en §0.41 : livrer sur une branche, laisser `main` intact jusqu'à la fin du run.

> 🔴 **PARADE INSUFFISANTE — la leçon a coûté un SECOND run le 2026-07-28 (§0.43).** « Laisser
> `main` intact » ne protège rien : ce que les workers `spawn` relisent, c'est le **WORKING
> TREE**, pas la branche `main`. P3-2 a été correctement livré sur `v11-p3-2-charge-target`
> (jamais mergé, vérifié : `main` est resté sur le commit P2) — mais le working tree est **resté
> checkouté sur cette branche**. Le `git checkout` de 21 h 39 a donc réécrit sur le disque
> `pointer_policy.py`, `macro_intents.py` et le JSON de config pendant que le run tournait.
> **Diagnostic reproduit** : le snapshot d'éval portait `action_net [18, 320]` sans
> `charge_query_net` (architecture P2, celle du process en mémoire) ; les workers ont reconstruit
> `action_net [17, 320]` **avec** `charge_query_net` (architecture P3-2, celle du disque) →
> `load_state_dict` lève dans l'`initializer` du pool → `BrokenProcessPool` → 600 épisodes
> `error` en 7,1 s → le garde-fou strict d'éval arrête le training.
> **Règle qui remplace la précédente** : pendant un run, le working tree est **GELÉ**. Ni commit,
> ni checkout, ni édition — quelle que soit la branche. Un agent qui doit livrer travaille dans un
> **worktree git séparé** (`git worktree add`), pas par bascule de branche.
> **Défaut d'observabilité à traiter** (non fait) : `BrokenProcessPool` a **avalé** la vraie
> exception ; le log ne donnait que « error_episodes=600 », sans cause. Il a fallu réexécuter
> `_eval_worker_init` à la main pour la voir. Tant que l'init du worker passe par l'`initializer`
> du pool, toute panne de worker sera indiagnosticable depuis le log — l'initialiser
> **paresseusement dans la tâche** ferait remonter le message réel par le chemin d'erreur
> par-tâche qui existe déjà.

**Une spec d'action_space peut être périmée par une évolution du RÉSEAU, pas seulement du moteur (§0.41, 2026-07-28)**

[§9.3](V11_phaseA.md#s9.3) prévoyait `CHOICE_0..K-1`, K colonnes denses de `action_net`, pour tout point de décision.
Écrite le 2026-07-14, elle est antérieure à §0.30 T-E et §0.32 T-G, qui ont supprimé précisément
ce motif (une colonne dense par rang n'apprend rien des autres et ne sait pas *ce qu'est* le
candidat qu'elle score). **Règle** : quand les candidats d'une décision sont des ENTITÉS déjà
encodées dans l'observation, la paramétrisation correcte est **une dimension d'action par slot,
scorée par produit scalaire sur l'embedding** — coût nul en paramètres, alignement obs↔action
structurel. Le mécanisme générique ne se justifie que pour les candidats **non-entité**. Corollaire
de méthode : une spec non datée de la session en cours se relit contre l'ARCHITECTURE actuelle,
pas seulement contre le moteur.

**Rendre un choix à l'agent sans lui donner de quoi le faire, c'est une demi-tranche (§0.41, 2026-07-28)**

P3-1 a d'abord été livrée « complète » : action, masque, tête pointeur, tests verts. Elle ne
l'était pas. L'agent choisissait sa cible de mêlée **sans voir combien de ses figurines pouvaient
la frapper** — le premier facteur du choix. Deux champs voisins donnaient l'illusion de la
couvrir : `n_fight_eligible` (mais il AGRÈGE sur toutes les cibles) et `edge_distance` (mais il
mesure l'ESCOUADE, alors que 04.02 s'évalue par figurine). **Règle : toute tranche P3 se termine
par la question « avec quelle information l'agent tranche-t-il ? », et la réponse se prouve par un
test de DISCRIMINATION** — deux candidats que la nouvelle feature sépare et que les champs
existants confondent. Sans ce test, « la feature existe » ne dit pas « la décision est observable ».
Corollaire de séquencement : quand une tranche impose déjà un retrain (action space), le coût
marginal d'ajouter la feature d'observation qui lui manque est **nul** — c'est le moment de la
livrer, pas une tranche plus tard.

**Un oracle partagé ne doit pas imposer son coût de mise en forme à tous ses appelants (§0.41, 2026-07-28)**

`_model_can_fight_target` (prédicat 04.02) reconstruit l'empreinte synthétique de la figurine à
chaque appel. Correct pour la résolution d'attaque, ruineux pour l'observation, qui possède déjà
ces empreintes et teste N figurines × M cibles à CHAQUE step : **41,7 µs/appel contre 4,5 µs** une
fois l'empreinte fournie (9,2×), soit 2,50 ms au lieu de 0,27 ms sur le pire cas réaliste — pour
une observation qui coûte 2,5 ms au total. La parade n'est PAS de recopier le prédicat côté
appelant (il divergerait sur la métrique, et l'obs annoncerait un volume d'attaques que le combat
ne produit pas) : c'est d'**extraire le cœur en une fonction qui accepte la donnée déjà mise en
forme**, et de faire de l'ancienne signature son wrapper. Un seul corps, deux points d'entrée.

**Un point de décision « le plus urgent » peut être INERTE dans le training réel (§0.41, 2026-07-28)**

Le point 0 de [§9.4](V11_phaseA.md#s9.4) (pseudo-décision `raw_action_int % len(options)` sur les rule-choices) porte
l'étiquette « le plus urgent » depuis le 2026-07-24. Vérification faite : **une seule** unité du
projet porte un rule-choice (`TyranidWarriorMelee`, `usage: "or"`, déclaré dans les rosters **TS**
— pas dans `config/unit_rules.json`, où le grep rend 0 et laisse croire à tort qu'il n'y en a
aucun), et **aucun** roster d'entraînement ArmageddonAgent n'est tyranide. Le code est donc vif en
PvE et dans `rule_checker`, jamais dans le training. **Avant d'ouvrir une tranche sur un point de
décision, vérifier qu'il est réellement atteint par les ROSTERS du training** — sans quoi on livre
un mécanisme jamais exercé, c'est-à-dire le motif §0.4 que ce document existe pour interdire.

**Un run qui passe ne prouve pas une non-régression sur un crash stochastique (§0.18)**

🔴 **Erreur commise le 2026-07-20, à ne pas refaire.** Un run de 500 épisodes a franchi
l'épisode ~250 sans le crash `collision intra-plan`, et on en a conclu — **par écrit, dans ce
document** — que la non-régression §0.11 était « validée en bout-en-bout ». Un **second run,
même commande**, a crashé à l'épisode ~280. Le crash dépend de la **trajectoire**, donc du
hasard : un run vert est un **échantillon de taille 1**, pas une preuve.

Règle : pour un crash dont le déclenchement dépend de la trajectoire, une non-régression se
prouve par un **test qui reproduit la condition**, ou à défaut par **plusieurs runs**, jamais
par un seul run vert. Et **tout changement de code qui touche l'observation ou le reward change
les trajectoires** — un run vert d'avant le changement ne dit rien du code d'après.

**L'ETA affichée au premier épisode est un artefact de warmup (§0.13)**

⚠️ **Piège de perf, à ne pas re-diagnostiquer** : l'ETA affichée au 1ᵉʳ épisode (~16 h 45 sur le
run de 1000) est un **artefact de warmup** ; elle retombe à sa vraie valeur dès le 10ᵉ épisode.
Ne jamais extrapoler une durée de run depuis les premiers épisodes.

**Ce que `x5_debug` ne produit PAS, et pourquoi il ne se lance pas seul (§0.10)**

**Piège de lancement, préexistant** : `--training-config x5_debug` **seul** échoue pour cet agent
(`No scenario file found … scenario_x5_debug.json`). ArmageddonAgent n'a que
`scenario_training_armageddon.json`, donc `--scenario <chemin explicite>` est **obligatoire** :
```
python3 ai/train.py --agent ArmageddonAgent --training-config x5_debug \
  --scenario config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json \
  --new --resolution 5
```
⚠️ `x5_debug` n'est **pas** un run de quelques minutes malgré son nom : **10 000 épisodes à 48
envs** au 2026-08-02. ⏳ **Seuls les profils `x1*` sont tenus à jour** (décision utilisateur du
2026-08-02) — relire le JSON avant de citer un chiffre d'un profil `x5*`.

⚠️ **La leçon durable** : un profil de debug peut, par ses seuls `callback_params`, ne rien
produire du tout — `save_best_min_episodes` et `checkpoint_save_freq` supérieurs (ou égaux) au
nombre d'épisodes du profil ⇒ **ni « best model » ni checkpoint**, sans le moindre message.
`model_gating_enabled: False` rend en outre le `Gate 🧱` de la barre de progression purement
décoratif. **Toujours confronter ces trois clés au `total_episodes` du profil avant de lancer**,
et ne pas prendre un run de validation de pipeline pour une mesure : il ne peut pas servir le
critère [§10.6](V11_eval_strategy.md#s10.6). (Valeurs constatées le 2026-08-02 sur `x5_debug` :
`total_episodes` 10 000, `save_best_min_episodes` 10 000, `checkpoint_save_freq` 10 000,
`bot_eval_final` 100.)

**Tout run `x5_debug` ÉCRASE le modèle canonique (§0.0)**

- ⚠️ **Le modèle en place a été ÉCRASÉ par ce run** (`model_ArmageddonAgent.zip`, 2026-07-20
  02:14 — autorisation utilisateur explicite). C'est donc un modèle **de debug, 100 épisodes
  `--new`**, sans valeur de jeu : `save_best_robust: false` fait que `train.py` écrit le modèle
  final en fin de run, aux deux sites gardés par `if not save_best_robust`.
  ⚠️ Tout run de debug ultérieur écrasera à nouveau le modèle canonique : **sauvegarder avant**
  si le modèle en place compte.

**`config/users.db` réapparaît modifié après chaque run (§0.0, dette 5)**

⚠️ `config/users.db` **réapparaît modifié** après chaque run d'entraînement — fichier
**protégé** (CLAUDE.md), ne JAMAIS l'inclure dans un commit.

**`bot_eval_scenario_pool` placé au mauvais niveau est silencieusement ignoré (§0.13)**

⚠️ **Piège latent, RÉSORBÉ — la leçon reste.** `bot_eval_scenario_pool` avait été placé à la
**racine** de `x5_debug`, alors que `_resolve_callback_value` (`ai/train.py`) le cherche dans
**`callback_params`** puis retombe sur `config/agents/_training_common.json` : la clé racine était
donc **ignorée**. Vérifié le 2026-08-02 : elle vit aujourd'hui dans `callback_params`. Mais toute
surcharge par agent placée à la racine reste **silencieusement sans effet** — c'est vrai de toutes
les clés lues par `_resolve_callback_value`, pas seulement de celle-ci.

**`agent_roster_seed` neutralise le tirage de roster sans le moindre message (§0.10)**

⚠️ **Piège latent voisin — `agent_roster_seed`.** Cette clé de scénario est passée en
`random_seed` au tirage du roster AGENT (`game_state.py`, lecture puis validation de
`agent_roster_seed`), et le RNG est reconstruit à chaque appel (`random.Random(random_seed)`). Si
elle est **renseignée**, le roster agent devient **identique à tous les épisodes** — le tirage est
neutralisé sans le moindre message.
🔴 **Correction du 2026-08-02** : ce document affirmait que les scénarios holdout `bot-01..04`
« la portent, pour la reproductibilité ». **C'est faux** : les quatre portent la clé **à `null`**,
donc le tirage y est **ACTIF**. Le seul scénario du dépôt qui la renseigne réellement est
`scenario_training_benchmark.json` (CoreAgent, `12345`). `scenario_training_armageddon.json` ne la
porte pas. **À contrôler avant de conclure quoi que ce soit sur une distribution de matchups** —
et à ne pas déduire de la seule PRÉSENCE de la clé.

**Une suite de tests est une mesure GLOBALE, donc un verrou GLOBAL (§0.19.1, 2026-07-20)**

🔴 **Trois mesures de suite invalidées le même jour, par trois écrivains différents.** Le partage
du dépôt « par fichier » ne protège **rien** : deux agents peuvent éditer des fichiers disjoints
sans conflit, mais ils **ne peuvent pas mesurer en parallèle**, parce qu'une suite lit tout
l'arbre.

| # | Écrivain pendant la mesure | Conséquence |
|---|---|---|
| 1 | **moi-même** : baseline lancée pendant que je mutais 5 fichiers | tuée, non exploitée |
| 2 | **la chasse §0.18** : `shared_utils.py` à 20:14:31 et son test à 20:13:58 pendant une suite de 20:05→20:45 | un `EXIT=1` pris à tort pour un « rouge attendu permanent » |
| 3 | **l'agent concurrent** : `shared_utils.py` à 21:20:33 pendant une suite de 21:17:37→21:22:54 | un `EXIT=0` non exploitable |

**Règle.** Avant de conclure d'un résultat de suite, **relever le `mtime` des fichiers de
`engine/` avant ET après le run** ; tout fichier écrit dans la fenêtre invalide la mesure.
Une consigne « ne modifie pas tel fichier » donnée à un agent **ne suffit pas** si l'autre côté
y écrit : il faut soit interdire les suites complètes, soit geler les écritures pendant la
mesure. ⚠️ Corollaire : `EXIT=0` **et** `EXIT=1` sont également suspects — le n°2 a produit un
faux rouge, le n°3 un vert non fiable. Ne pas ne se méfier que des rouges.

⚠️ **Ne JAMAIS restaurer par `git checkout` un fichier portant du travail non commité d'un
autre agent** (`shared_utils.py`, `w40k_core.py` au 2026-07-20) : la restauration détruirait ses
modifications. Pour un mutation-test sur ces fichiers, sauvegarder par `cp` et restaurer par `cp`.

### Sur les données et les sources officielles


**🔒 Règle métier : `VALUE` suit le Munitorum, ce n'est pas une variable de tuning (§0.9)**

🔒 **RÈGLE MÉTIER (utilisateur, 2026-07-20) — NON NÉGOCIABLE.** `VALUE` **suit les documents
officiels**. Ce n'est pas une variable de tuning. `VALUE` est pourtant consommé **par figurine**
(bonus de kill pondéré par `model_value` dans `_squad_combat_shaping`,
`engine/reward_calculator.py` ; différentiel d'armée `value_alive`,
`engine/observation_builder.py`) : cet
effet sur l'apprentissage est une **conséquence à assumer**, jamais un motif pour s'écarter du
Munitorum. **Ne pas « rééquilibrer » ces valeurs pour améliorer un résultat d'entraînement.**

**Les PDF Munitorum ne sont pas extractibles en texte (§0.9)**

⚠️ **Le texte de ces PDF n'est pas extractible** (contenu en image : `extract_text()` ne rend que
les en-têtes). Il faut les **rendre en PNG** (`fitz`/pymupdf, dpi≥140) et les lire visuellement.
Ne pas conclure « le PDF est vide ».

**Deux pièges de lecture des sources : Grot Orderly, contradiction Gretchin (§0.9)**

**Deux pièges de lecture des sources, à ne pas re-trébucher dessus :**
1. **Le Grot Infirmier n'est pas une figurine de jeu.** Datasheet Painboy : `UNIT COMPOSITION :
   1 Painboy`, `equipped with : … 1 Grot Orderly` → c'est de l'**équipement**. D'où 38 figurines
   physiques dans la boîte mais **37 modèles de jeu**. Le roster n'a rien qui manque.
2. **Contradiction entre deux sources officielles sur les Gretchin** : le Munitorum cote
   `11 models … 45 pts`, la datasheet dit `UNIT COMPOSITION : 10 Gretchin`. La boîte en a 10.
   Retenu : 10 modèles à 45 pts. Non tranchable depuis les documents — signalé, pas masqué.

**Limite x10 et point non tranché du fix de collision (§0.11)**

**Non tranché** : je n'ai pas l'état exact au moment du crash. Il est prouvé que le prédicat est
aveugle au niveau et qu'il produit ce message sur une configuration légale ; il n'est **pas**
prouvé que les deux figurines de l'escouade 3 étaient à des étages différents plutôt que dans un
état déjà illégal. Si un crash de cette classe réapparaît, dumper l'état avant de conclure.

**Limite connue, HORS PÉRIMÈTRE (décision utilisateur, 2026-07-20) : le cas x10.** Le contrôle
compare les **sous-hex d'ancre**. Sur Board ×10 les figurines ont une **empreinte multi-hex**
(`compute_candidate_footprint` — « *For multi-hex units on x10 boards, computes the full
round/oval/square footprint* ») : deux
socles peuvent donc s'y chevaucher **sans partager leur ancre**, et la même classe d'incohérence
masque/exécution reste ouverte à cette résolution. Sur x5 (résolution du training) l'empreinte
vaut le sous-hex, le contrôle est **exact**. Limite préexistante, non introduite par le correctif.
⚠️ Ne pas lire « l'invariant est rétabli » comme valant pour toutes les résolutions : il vaut
pour x1 et x5. **On ne s'occupe pas de x10** — si le projet y vient un jour, rouvrir ce point
AVANT d'y lancer un entraînement.

### Affirmations périmées repérées le 2026-07-20 — **signalées, NON corrigées**

> Relevées pendant la réorganisation de §0. Aucune n'a été « nettoyée » : les corriger sans
> relire le code reproduirait exactement l'erreur qu'elles illustrent. **Vérifier avant de
> s'appuyer sur l'une d'elles.** C'est le motif récurrent n°1 de ce document — au moins
> 5 avaient déjà été trouvées lors des sessions précédentes.

| # | Où | Affirmation | Pourquoi elle est suspecte |
|---|---|---|---|
| 1 | §0.-1 | « la suite est VERTE : `1402 passed, 2 skipped` » | Son propre ⚠️ la déclare datée. Le document porte aussi `1407`, `1440`, `1451`, `1396`, `1398` selon l'endroit. Seul verdict fiable : le code de sortie. |
| 2 | [§5](V11_tranches.md#s5) / tableau T6-i | « ❌ test de non-régression **NON écrit** » | `tests/unit/engine/test_end_of_turn_coherency_03_03.py` **existe sur le disque** (vérifié le 2026-07-20) et §0.0 le déclare livré. |
| 3 | [§5](V11_tranches.md#s5) / tableau T6 | « le critère T6 est désormais bloqué par `CC_DMG` (§0.3) qui plante des épisodes d'évaluation » | Le portage §0.3 est fait et le run 60/60 de §0.7 le valide runtime. |
| 4 | [§10.5](V11_eval_strategy.md#s10.5) (bandeau) | « ⚠️ Non validé runtime — cf. §0.3 (`CC_DMG`) » | Levé par §0.7 (`TacticalBot` 10/10 épisodes). |
| 5 | §0.10 | « la dette notée en **§0.0** (`--scenario bot` échoue en amont du moteur) » | Cette dette est écrite dans **§0.7**, pas §0.0. Renvoi imprécis, non corrigé. |
| 6 | §0.12, étape 4 | « **9 tests** liés à `roster_pool_schedule` échouent indépendamment de ce travail » | ✅ **TRANCHÉ le 2026-07-20 — l'affirmation était FAUSSE.** Suite complète lancée : **1417 passed, 2 skipped, 0 failed**. Aucun échec `roster_pool_schedule`. §0.-1 avait raison : un test rouge est une régression, il n'y a pas d'échec préexistant à tolérer. |
| 7 | [§2](V11_tranches.md#s2) « État des lieux vérifié » | « Tous les imports du pipeline passent (`ai.train`, `ai.env_wrappers`, **`ai.multi_agent_trainer`**, **`ai.scenario_manager`**, …) » | `ai/multi_agent_trainer.py` **n'existe plus** (supprimé en §0.8, vérifié absent du disque le 2026-07-20) ; `ai/scenario_manager.py` non plus (supprimé le 2026-07-29, §0.45). Deux des modules cités comme preuve de santé du pipeline étaient du code mort. |
| 8 | §0.17 (par construction) | l'état de commit | Périmé dès le prochain `git commit` — l'entrée porte elle-même l'ordre de la reconfronter à `git status`. |
| 10 | §0.18, note annexe | « après ce crash le process … s'est terminé avec un **code de sortie 0** » | ❌ **FAUSSE, tranchée le 2026-07-20 — voir §0.20.** Le handler `return 1`, `sys.exit` propage, et l'exécution confirme `EXIT=1`. Cause probable : un pipe (`| tee`) côté shell lors de la mesure. Enseignement : une note **« hors périmètre »** échappe à la relecture *parce qu'*elle est marquée annexe. |
| 11-13 | [§6](V11_tranches.md#s6) (T2, T4), [§8.2](V11_tranches.md#s8.2) | layout d'actions « 41 », « 61 scénarios », `test_agent_interface_contract.py` | ➜ **détaillées en §0.19.1** (audit du 2026-07-20). Signalées, NON corrigées. ⚠️ **2026-08-02** : la n°11 a été « corrigée » une fois avec des chiffres qui sont à leur tour périmés — **ne plus citer de chiffre de layout d'action ici**, seul l'invariant « zéro littéral d'action dans `ai/` » compte, et il tient. La n°12 est aggravée : `scripts/sweep_scenario_bank_v11.py` **n'existe plus dans le dépôt** (il n'est donc plus seulement non exécutable). |
| 9 | §0.14 (rédigée puis **corrigée le même jour**) | « Non-régression §0.11 ✅ **VALIDÉE EN BOUT-EN-BOUT** » | ❌ **FAUSSE, retirée le 2026-07-20** — cf. §0.18 : le run suivant a crashé sur ce même message. Cas d'école : l'affirmation a été produite **par l'auteur du run lui-même**, le jour même, à partir d'un unique run vert. Le motif n°1 de ce document ne vient pas que du passé. |

---

## 0ter. Notes post-implémentation — décisions assumées, non-travaux

> Choses **tranchées et closes** qui ne sont ni des bugs ni des dettes : des décisions de
> périmètre que l'utilisateur assume. À ne pas rouvrir comme des réserves.

- **§0.16(b) — `DefensiveSmartBot` reste hors éval (status quo, 2026-07-21).** ⚠️ **CADUC depuis le
  2026-07-30 (§0.53) : la classe elle-même a été SUPPRIMÉE**, ainsi que son appelant
  `_best_target_slot_by_threat`. Le critère de menace reste vivant chez `DefensiveBot`, qui est,
  lui, joué en éval. Entrée conservée pour mémoire. Retiré à l'origine
  parce qu'il **sous-performait**. ⚠️ **Mise à jour 2026-08-02** : `_best_target_slot_by_threat`
  a été supprimé avec la classe — il n'en reste qu'un commentaire d'archive dans
  `tests/unit/ai/test_evaluation_bots.py`. Le « trou de couverture » décrit ici **n'a plus
  d'objet** ; l'entrée ne vaut plus que comme décision de périmètre (ne pas réintroduire le bot
  pour la seule couverture, cela fausserait la composition d'éval). **Ne pas re-signaler.**
- **§0.16(c) — clé `holdout_hard_opponent_budget_modifier` + `build_holdout_benchmark.py` gardés
  (2026-07-21).** Non consommés par le training actuel (2 rosters fixes, [§10.2](V11_eval_strategy.md#s10.2)), mais **conservés
  volontairement** : un holdout à armées **générées** est prévu **après la démo**. La clé est en
  attente d'usage, pas morte. **Ne pas supprimer ni la clé ni le script.**

---

<a id="pointeurs"></a>
## Pointeurs — où vit la spec (ce document ne garde que l'ÉTAT)

> Les sections **1 à 10** de la spec ont été extraites le **2026-07-28** dans trois sous-docs
> (plan [`V11_refactor_plan.md`](Implémenté/V11_refactor_plan.md), étapes 1→3). Ce fichier ne conserve que
> l'**index d'état** : §0 (ouvert et actionnable), §0bis (pièges canoniques), §0ter (non-travaux)
> et §0hist (historique résolu, intégral). **Contenu déplacé tel quel, aucune réécriture.**

| Document | Contenu | État |
|---|---|---|
| [`V11_tranches.md`](V11_tranches.md) | **[§1](V11_tranches.md#s1) → [§8](V11_tranches.md#s8)** — objectif, l'ANCRE, état des lieux, ruptures R1→R8, décisions de design, tranches T1→T7 + Phase B, critères d'acceptation, smoke tests, tests de non-régression | **vivant** (T6-h/T6-g ouverts, cf. [§0.0](#s0.0)) |
| [`V11_phaseA.md`](V11_phaseA.md) | **[§9](V11_phaseA.md#s9)** — Phase A' : parité de résolution des règles (P1) puis mécanisme de décision agent (P2→P5) | **vivant** |
| [`V11_eval_strategy.md`](V11_eval_strategy.md) | **[§10](V11_eval_strategy.md#s10)** — stratégie d'entraînement et d'évaluation, rosters, holdout, win-rate par roster | **vivant** |
| [`V11_entity_encoder_pointer.md`](V11_entity_encoder_pointer.md) | Encodeur d'entités partagé + tête pointeur, cardinalités de l'observation, les 7 trous qu'il ferme | **vivant** |
| [`Implémenté/observation_deploiement.md`](Implémenté/observation_deploiement.md) | Observation de la phase de déploiement — les 5 défauts et leurs correctifs (extrait de `V11_audit_observation.md` §11) | **clos** (2026-07-29, §0.40 — archive) |
| [`Replay.md`](Replay.md) | Replay : pipeline & contrat du `step.log`, registre des chantiers replay | **vivant** (outillage) |
| [`V11_move_build_acceleration.md`](V11_move_build_acceleration.md) | Perf du noyau `_build_multi_hex_vectorized` : périmètre, filet de validation, livré (L1 + L_bbox), impasses mesurées | **clos** (décision (B) STOP, 2026-07-21) |
| [`Implémenté/V11_move_pool_optimization.md`](Implémenté/V11_move_pool_optimization.md) | Cadrage d'origine du chantier move pool (§0.22) | **clos** — archive, ne plus s'y fier pour l'état du code |

## 0hist. Historique résolu

<a id="s0.54"></a>
### 0.54 Non-conformité 14.02 — « l'unité est sur un objectif » se lisait sur l'ANCRE d'escouade — ✅ CORRIGÉ ET MERGÉ (2026-07-30)

> ⏳ **Reconfrontée le 2026-08-02** : mergée sur `main` (le « non mergé » d'origine est faux
> depuis). ⚠️ **Change l'issue des parties → tout modèle antérieur a appris une géométrie fausse
> de cette règle.**

Jumeau trouvé en corrigeant les bots ([§0.53](#s0.53)). `is_unit_on_objective` comparait l'**ancre
d'escouade** à un hexe d'objectif **par égalité stricte de coordonnées**, alors que **14.02** dit
« *A model is within range of a terrain objective while it is within that terrain area* » — la
portée se juge **PAR FIGURINE** (l'illustration du même paragraphe compte « *six of its models are
within the terrain area* »), et le CONTRÔLE d'objectif du **même moteur**
(`sum_objective_control_oc_multi`) comptait déjà une figurine dès qu'une case de son **socle**
recouvre la zone. Deux réponses différentes à la même question dans le même état de jeu.

Deux consommateurs, les deux phases d'attaque : `reroll_towound_target_on_objective` au **tir**
(`shared_utils.py`) et en **mêlée** (`fight_handlers.py`).

**Correction** : implémentation **unique** `game_state.unit_is_within_objective`, sur le même
générateur d'empreintes que le contrôle (`iter_living_model_footprints`) ; `is_unit_on_objective`
et `_squad_on_objective` (bots) y délèguent. Verrous : 2 tests prouvés rouges sur la lecture par
ancre, le test de discrimination restant vert.

⚠️ Une escouade étalée, ou à socle large, déclenche désormais la relance là où elle ne la
déclenchait pas — et l'inverse. `ai/analyzer_phases/*` vérifiés : ils comptent le token du
journal, sans test géométrique — pas de jumeau de plus.

<a id="s0.53"></a>
### 0.53 Refonte du panel de bots — les adversaires ignoraient la condition de victoire — ✅ LIVRÉ ET MERGÉ (2026-07-30)

> ⏳ **Entrée périssable, reconfrontée le 2026-08-02** : le code est **mergé sur `main`** (le
> « non mergé » d'origine est faux depuis). Le panel a **encore évolué** : voir la note de fin
> d'entrée.

**Constat mesuré sur deux runs successifs** : le win-rate de l'agent contre chaque bot suit
EXACTEMENT le rapport de ce bot aux objectifs (`control` 0.33→0.27 et `adaptive` 0.52→0.36
régressent, `greedy` 0.67→0.82, `aggressive_smart` 0.68→0.80, `tactical` 0.80→0.89,
`defensive` 0.88→0.95 progressent), alors que la victoire se décide aux VP d'objectifs
(`determine_winner_with_method` : les kills ne tranchent qu'à égalité). Le `combined` montait
(0.62→0.65) pendant que la compétence décisive baissait.

**Quatre changements :**

1. Les trois géométries exclusives de déplacement (`_dest_toward_enemies` / `_dest_away_from_enemies`
   / `_dest_toward_objective`) sont remplacées par **un score pondéré unique**
   `w_objective × (−d_objectif) + w_enemy × (−d_ennemi) [+ bonus de tenue]`, réglé dans
   **`config/bot_movement_weights.json`** — plus aucun bot ne peut ignorer les objectifs, et
   « tenir l'objectif » devient une règle de score commune au lieu d'une clause propre à
   `ControlBot`.
2. **Deux lectures d'objectif fausses** corrigées (motif ancre-vs-par-figurine) :
   `_count_objectives_controlled` relit `objective_controllers` — l'état 14.02 que le moteur écrit —
   au lieu de recompter des ancres amies, et `_is_on_objective` teste l'**empreinte de socle par
   figurine** (`iter_living_model_footprints`, extrait de `sum_objective_control_oc_multi` : une
   seule implémentation). Les deux vont ensemble : la posture « winning » d'`AdaptiveBot` **fuyait**
   les objectifs et se serait déclenchée bien plus souvent une fois le comptage juste.
3. **`AggressiveSmartBot` et `DefensiveSmartBot` supprimés** — le premier est un doublon strict de
   `GreedyBot` (même géométrie, même `_score_wounded` aux trois phases ; seul écart : un poids de
   déploiement), le second n'était instancié nulle part. Avec eux disparaissent le regroupement
   « palier 2 » et le scalaire `bot_eval/tier2_combined` ; l'early stopping bascule sur
   `bot_eval/combined`.
4. **Budget re-pondéré** dans les profils, et l'agrégat de classement de rosters
   (`roster_aggregate_rankings.py`) passe à **4 bots à 0.25**, arité généralisée.

**CONSÉQUENCES :**
- (a) 🟢 **SANS OBJET jusqu'à la démo métier** (arbitrage utilisateur du 2026-08-02) : les matrices
  `{split}_matchups_{bot}.json` ne sont plus sur disque, mais le travail porte sur **2 rosters
  seulement** — il n'y a pas de classement par roster à produire. **Ne pas re-signaler.**
- (b) 🟢 **SANS OBJET, même raison** : le `combined` va **BAISSER** (tous les bots deviennent
  compétitifs) — c'est le résultat recherché, pas une régression — mais le recalibrage des seuils
  de gate de curriculum attend la sortie du périmètre 2 rosters.
- (c) ⚠️ **TOUJOURS VRAI** : **aucun win-rate antérieur au 2026-07-30 n'est comparable** à un
  win-rate postérieur.

⏳ **Le panel a évolué depuis cette entrée** (constaté le 2026-08-02) : un **cinquième bot
`ValueTradeBot`** a été ajouté. La pondération courante est `bot_eval_weights` = `control` 0.40 /
`value_trade` 0.15 / `adaptive` 0.15 / `greedy` 0.15 / `defensive` 0.15 / `tactical` 0, et
`ratios` = `control` 0.35 / `value_trade`, `adaptive`, `greedy`, `defensive` 0.15 / `random` 0.05 —
et non la répartition « control 0.40 / adaptive 0.20 / greedy 0.20 / defensive 0.20 » écrite à la
livraison. Relire le JSON avant de citer un poids.

<a id="s0.52"></a>
### 0.52 Ce que la campagne « typage & replis » du 2026-07-29 change pour la MESURE — ✅ LIVRÉ ET MERGÉ (2026-07-29)

> **Périmètre de cette entrée : UNIQUEMENT ce qui change ce que l'utilisateur mesurera au prochain
> entraînement.** La campagne complète (57 commits, `bb3a788f` → `d061f21b`) — contre-audit du
> typage, replis silencieux, code mort, journal de tir, **et surtout la dette restante** — vit à UN
> seul endroit : **[`campagne_typage_et_replis_2026-07-29.md`](campagne_typage_et_replis_2026-07-29.md)**.
> Ne pas recopier son contenu ici.

#### 1. 🔴 Quatre compteurs de combat rebranchés — les courbes antérieures sont ABSENTES, pas nulles

Commit **`5f1878eb`**. `shots_fired`, `hits`, `damage_dealt` et `damage_received` étaient
**déclarés** dans `episode_tactical_data` et **jamais incrémentés** depuis le commit **`fe1df7d8`
« metrics OK » du 2025-10-25** (date constatée par `git log -1 --date=short fe1df7d8`) : ce commit a
déplacé le dictionnaire du callback vers le moteur, a réimplémenté `valid_actions`,
`invalid_actions`, `units_lost` et `units_killed`, **mais pas ces quatre-là**, tout en supprimant
leur calcul côté callback **dans le même diff**. Migration partielle, **neuf mois de silence**.

**Ce qu'il faut en retenir pour lire les courbes** — les consommateurs sont gardés par `> 0` :

| Courbe | État avant le 2026-07-29 |
|---|---|
| `game_tactical/shooting_accuracy` | **jamais émise** |
| `game_detailed/damage_dealt` | **jamais émise** |
| `game_detailed/damage_received` | **jamais émise** |
| `game_tactical/damage_efficiency` | **jamais émise** |

🔴 **Une courbe absente ne se distingue pas d'un agent qui ne se bat jamais.** Toutes les mesures
d'entraînement antérieures au 2026-07-29 — **y compris le run 4 (§0.14)** — **ne contiennent pas ces
quatre courbes**. Elles ne sont pas à zéro : elles n'existent pas. Toute comparaison
avant/après sur les dégâts, la précision ou l'efficacité de combat est **impossible**, pas
seulement dégradée.

**Où c'est branché** : bloc de fin d'épisode de `step()`, sur `action_logs`
([`engine/w40k_core.py:2007`](../../engine/w40k_core.py#L2007) et suivants) — **pas** sur
`attack_details`, qui vit sous `if (self.step_logger and self.step_logger.enabled)` et rendrait les
métriques **dépendantes de `--step`**, donc nulles à l'entraînement normal.

**Définitions verrouillées par test** (pour qu'un élargissement futur soit un choix, pas un oubli) :
`shots_fired` / `hits` = **TIR seul** (une précision au tir ; y verser la mêlée la rendrait
ininterprétable), donc `hits <= shots_fired` par construction ; `damage_dealt` /
`damage_received` = **tir ET mêlée**, c'est l'attrition totale.

**Preuve** : cohérence croisée sur vraie partie (14 tests, moteur réel, 3 graines) —
`damage_dealt` == PV réellement perdus par l'adversaire et `damage_received` == PV perdus par le
camp contrôlé, à l'unité près, **dans les deux sens et pour les deux sièges** ; rouge sous 4
mutations restaurées.

#### 2. 🟢 Type de socle scindé — la géométrie du chemin chaud accélère, l'invariant devient inviolable

Commits **`44486667`** (invariant validé à la frontière, 9 `cast` supprimés) puis **`6f0c0c6b`**
(scission du type). `Socle` était une **union étiquetée modélisée comme un enregistrement plat** :
`shape` DÉTERMINAIT le type de `base_size` (`round`/`square` → diamètre scalaire, `oval` → paire)
sans que rien ne le dise. `RoundSocle` / `SquareSocle` / `OvalSocle`
([`engine/hex_utils.py:1728/1741/1754`](../../engine/hex_utils.py#L1728)) portent désormais chacun
le type exact, et `Socle(...)` est la **fabrique** qui choisit la classe et refuse une taille qui
contredit l'étiquette.

| Mesure (timeit, n=200000, 3 passes) | avant | après | |
|---|---|---|---|
| `euclidean_edge_distance` | 883 ns | 645 ns | **−27 %** |
| `footprints_overlap` | 679 ns | 490 ns | **−28 %** |
| construction d'un socle | 243 ns | 274 ns | **+31 ns — assumé** (la fabrique valide, là où `tuple.__new__` était en C) |

Net sur le couple réel « construire un socle puis tester le chevauchement » : **−17 %**.

**Pourquoi ça compte au-delà de la perf** : l'invariant n'est plus vérifié à la lecture — **un socle
incohérent ne peut plus exister**. La classe de base ne déclare pas `base_size`, donc on ne peut pas
lire la taille d'un socle sans savoir de quelle forme il s'agit, et le vérificateur l'impose. Les
**28 sites de construction hors tests sont inchangés** (la fabrique garde nom, signature et mots-clés du
NamedTuple) et les **179 datasheets** du registre qui portent `BASE_SHAPE` respectent l'invariant (174 `round` + 5 `oval`,
0 violation).

⚠️ **Aucun `obs_size` ni `TOTAL_ACTION_SIZE` n'est touché** par ces deux points : ils
**n'appartiennent pas au lot de ré-entraînement de §0.48** et ne forcent aucun `--new`.

---

<a id="s0.51"></a>
### 0.51 Branches prêtes — 🟢 LES SIX SONT MERGÉES ⏳ ENTRÉE PÉRISSABLE (état au 2026-07-29 17 h)

> 🟢 **MISE À JOUR DU 2026-07-29 (soir) — le constat de 14 h 05 ci-dessous est HISTORIQUE.**
> Les **six** branches sont désormais **ancêtres de `main` = `d061f21b`** (vérifié par
> `git merge-base --is-ancestor <branche> main` pour chacune) ; leurs têtes ont bougé après le
> constat de 14 h 05, les têtes réellement mergées sont : `306033ec`, `ee3a55b8`, `fbd1d278`,
> `b5888bdf`, `ee1dccb9`, `aba3cb07`.
>
> ✅ **Le POINT DE COMPOSITION signalé plus bas est SOLDÉ** : `v11-0.47-dead-decoder-and-interface-lock`
> et `v11-0.47-eval-tooling-mask` sont sur `main` **ensemble**, donc `roster_matchup_stats.py`
> n'appelle plus une méthode supprimée. La contrainte d'ordre de merge n'a plus d'objet.
>
> 🟢 **MERGÉE DEPUIS — vérifié le 2026-08-02** (le motif d'attente ci-dessous est historique) :
> `fix-weapon-collection-defaults`
> (`5980a035`) — « distinguer *pas d'arme* (liste vide) de *entité mal construite* (clé absente) »,
> 8 fichiers, +310/−35 dont `tests/unit/engine/test_weapon_collections_contract.py` (213 lignes).
> **Motif de l'attente : l'utilisateur a du travail en cours sur exactement ces fichiers**
> (`git status` au 2026-07-29 : `engine/phase_handlers/fight_handlers.py`,
> `engine/phase_handlers/shared_utils.py`, `engine/phase_handlers/shooting_handlers.py`,
> `engine/w40k_core.py` modifiés). Elle appartient à la campagne « typage & replis » →
> [`campagne_typage_et_replis_2026-07-29.md`](campagne_typage_et_replis_2026-07-29.md).
>
> ⚠️ **Le merge n'est PAS une validation.** La vérification large appartient toujours à
> l'utilisateur et n'a pas été faite.

⏳ **Constat historique du 2026-07-29 à 14 h 05 — conservé tel quel, NE PLUS S'EN SERVIR comme
état courant.** Reconfronter au réel (`git log main..<branche>`) avant tout usage.
Constaté par `git log main..<branche>` le **2026-07-29 à 14 h 05**, `main` = **`5d2dfd48`**.
🔴 **CINQ des six branches ont bougé PENDANT le constat** (entre 13 h 56 et 14 h 05, suites de
relecture adverse écrites par d'autres agents en parallèle) : les têtes et les comptes ci-dessous
sont **datés à la minute, et déjà probablement dépassés**. Ne jamais les citer sans les revérifier.
**Aucune de ces branches n'est un chantier en cours sans livrable : les six portent du travail
terminé, avec ses tests ciblés.**

| Branche | Objet | Commits | Tête (14 h 05) | Détail |
|---|---|---|---|---|
| `v11-0.46-dead-code-charge-heuristic` | code mort `get_best_enemy_*` **+** documents rendus faux par la suppression | 2 | `306033ec` | [§0.46](#s0.46) pt 1 |
| `v11-0.47-eval-tooling-mask` | outil de stats par matchup : masque legacy, **obs Dict aplatie (l'outil ne démarrait pas)**, plafond de pas, vainqueur recalculé, scénarios au contrat legacy, `--agent-seat-mode` sans effet | 10 | `cc3b5713` | [§0.47](#s0.47) É1 **et** É6 |
| `v11-0.47-dead-decoder-and-interface-lock` | suppression de `convert_gym_action` **+ du masque de l'ancien espace** + 3 symboles morts préexistants, **+** verrou d'interface `test_agent_interface_contract.py` | 4 | `f0ed563a` | [§0.47](#s0.47) É2+É3 |
| `v11-pre-lot-eval-baseline` | bots d'éval (contre-charge du défensif, cibles hors ordre de tri, focus-fire rebranché, joueur dérivé de l'escouade activée) **+** rampe de déploiement sur les 5 profils | 4 | `d0183afe` | [§0.47](#s0.47) **É4** + [§0.46](#s0.46) **pt 2** |
| `v11-battle-shock-oc` | conformité 01.07 : contrôle d'objectif, **+ bonus de reward « sur objectif »**, docstring, verrous des producteurs du drapeau, 3ᵉ vérité parallèle du replay signalée **puis supprimée** (contrôle/VP journalisés par le moteur, 2026-07-29) | 5 | `b8932f52` | [§0.50](#s0.50) |
| `v11-fly-2103-conformity` | conformité 21.03 (casse du mot-clé, traversée payante, vol de charge, garde de phase, donnée corrompue, justification de la politique moteur) | 8 | `4c88ec60` | [§0.49](#s0.49) |

⚠️ **Le renvoi de `v11-pre-lot-eval-baseline` vers §0.48 était FAUX** (corrigé le 2026-07-29) : §0.48
est l'inventaire du **lot de ré-entraînement** et ne décrit **rien** de ce travail. Cette branche
livre **§0.47 É4** (bots d'évaluation) et **§0.46 point 2** (rampe de déploiement) — deux des quatre
chantiers que §0.48 exige **avant** la mesure de référence, ce qui n'en fait pas des éléments du lot.

⚠️ **POINT DE COMPOSITION — il ne s'agit PLUS d'un travail de suite, mais d'une CONTRAINTE D'ORDRE
DE MERGE** (mis à jour le 2026-07-29 à 14 h 05). Historique : la branche du décodeur mort avait
d'abord **CONSERVÉ** `get_action_mask_and_eligible_units` et `_build_mask_for_units` parce qu'un
appelant subsistait — [`scripts/roster_matchup_stats.py:562`](../../scripts/roster_matchup_stats.py#L562),
précisément celui que `v11-0.47-eval-tooling-mask` migre (§0.47 É1). Le commit **`a210008c`** les a
**supprimées** depuis, sur le constat que leur décodeur était parti au commit précédent et que ce
masque ne décrivait donc plus aucun espace décodable (pierre tombale posée dans `action_decoder.py`,
7 cas de test retirés).

🔴 **CONSÉQUENCE : `v11-0.47-dead-decoder-and-interface-lock` est INCOMPLÈTE SEULE.** Sur cette
branche prise isolément, `roster_matchup_stats.py:562` appelle une méthode qui n'existe plus —
c'est l'**état post-merge** qui fait foi, et la correction de ce site vit sur l'autre branche. Les
**deux branches doivent donc être mergées ENSEMBLE** (ou celle de l'outillage d'éval en premier) ;
merger la seule branche du décodeur laisse l'outil de statistiques cassé à l'exécution.

⚠️ **AUCUNE de ces branches n'est validée au-delà de ses tests ciblés.** La **vérification large**
(suite de tests complète, `pyright`, `ai/hidden_action_finder.py`, `scripts/check_ai_rules.py`,
`biome`, `tsc`) **appartient à l'utilisateur et n'a PAS été faite**. Ne pas lire « branche prête »
comme « branche verte ».

<a id="s0.49"></a>
### 0.49 Non-conformité 21.03 « Take to the skies » — le mot-clé FLY perdu par comparaison sensible à la casse — ✅ CORRIGÉ ET MERGÉ (2026-07-29 ; branche supprimée, vérifié le 2026-08-02)

**Cadre.** Découvert le 2026-07-29, pendant le run 4 — c'est **l'une des deux raisons de son arrêt**
([§0.14](#s0.14)).

✅ **CORRIGÉ ET MERGÉ sur `main`** (branche `v11-fly-2103-conformity` supprimée depuis ; vérifié le 2026-08-02). ⏳ **État constaté le 2026-07-29
à 14 h 05** (`git log main..v11-fly-2103-conformity`) — **la branche bougeait encore pendant ce
constat** (elle est passée de 5 à 8 commits entre 13 h 56 et 14 h 02), **reconfronter au réel avant
usage** : **8 commits**, tête **`4c88ec60`** (14 h 02) — `d1099b26` (casse du mot-clé), `18096753`
(traversée payante), `350da3cf` (vol de charge pour l'IA), `6b714180` (commentaire qui disait
l'inverse du code), `3b234200` (éligibilité bornée sur le budget réel), `c57f4fb6` (table de phases
née morte + garde de phase symétrique sur `get_squad_move_budget` : le budget d'une unité volante
était amputé de 2" **en tir, en charge et en combat** via `grid_half_extent_subhex`), `6191a360`
(un `keywordId` absent ou nul était sauté en silence — désormais `ValueError`, plus de valeur par
défaut masquant une donnée corrompue), `4c88ec60` (justification écrite de la politique moteur du
point 5 ci-dessous).
Verrou : `tests/unit/engine/test_fly_2103_conformity.py`, **18 tests** (compté par
`git show <branche>:<fichier>`), dont une **sonde in-engine** sur un vrai `W40KEngine` chargé de
`scenario_training_armageddon.json`, qui **échoue si elle ne rencontre aucune unité volante**
(« SONDE MUETTE »). ⚠️ **Non validée au-delà de ces tests ciblés** : la vérification large appartient
à l'utilisateur et n'a pas été faite (§0.51).

**1. La rupture (état AVANT correctif).** `_unit_has_keyword`
(`engine/phase_handlers/movement_handlers.py`) comparait le mot-clé par **ÉGALITÉ STRICTE**
(`keyword_value == keyword_id`), alors que ses appelants passent `"fly"` en minuscules.
✅ **Depuis le correctif (vérifié le 2026-08-02), elle normalise** (`str(v).strip().lower()`) et
**lève** si `keywordId` est absent ou nul. Les appelants qui passent `"fly"` sont **quatre**, dans
`movement_handlers.py` (trois) et `charge_handlers.py` (un).

**C'est l'EXCEPTION, pas la norme du moteur** : partout ailleurs les mots-clés sont **normalisés**
avant comparaison — [`engine/game_state.py:80`](../../engine/game_state.py#L80),
[:102](../../engine/game_state.py#L102), [:1162](../../engine/game_state.py#L1162),
[`shared_utils.py:4265`](../../engine/phase_handlers/shared_utils.py#L4265) (`.strip().lower()`).

**2. ⚠️ Le corpus est INCOHÉRENT, pas uniformément en majuscules.** Dans `frontend/src/roster/` :
**16** occurrences `keywordId: "fly"` et **6** `keywordId: "FLY"`. **Les 16 fonctionnent, les 6
perdent la règle.**

> ⚠️ **Correction d'une analyse fausse** : une première lecture concluait « tout le chemin FLY est
> mort ». **C'est FAUX** — les deux tiers du corpus passent. La rupture est **partielle et
> silencieuse**, ce qui est pire à diagnostiquer qu'un chemin uniformément mort.

**3. Gravité — elle touchait précisément le roster entraîné.** **Cinq des six** types en majuscules
sont dans les rosters d'ArmageddonAgent, présents à la fois dans
`config/agents/ArmageddonAgent/rosters/500pts/training/` **ET** `.../holdout_regular/` :
`VanguardVeteranSquadJumpPack`, `VanguardVeteranSquadJumpPackPlasma`,
`VanguardVeteranSquadJumpPackSergeant`, `ChaplainJumpPack`,
`LandSpeederOnslaughtGatlingCannon`. (Le sixième, `LandSpeederHeavyFlamer`, n'est dans aucun
roster de l'agent.) **Le run 4 entraînait donc l'agent sur un jeu où ses unités à réacteurs et son
Land Speeder ne volaient pas** — ni traversée, ni charge FLY.

**4. Deux défauts adjacents, révélés DÈS la casse corrigée — ✅ CORRIGÉS dans la même branche.** Ils
étaient masqués par la rupture : la corriger sans eux aurait transformé un bug en un autre.

- **(a) Traversée FLY gratuite en gym, EN FAVEUR DE L'AGENT.** `_fly_traversal_active`
  ([movement_handlers.py:258-273](../../engine/phase_handlers/movement_handlers.py#L258-L273)) rend
  `True` **inconditionnellement** pour une unité IA, alors que le **malus de 2"** de 21.03 n'est
  retranché du budget que pour les unités de `units_took_to_skies`
  ([shared_utils.py:4541-4546](../../engine/phase_handlers/shared_utils.py#L4541-L4546)) — ensemble
  **jamais rempli en gym**. L'agent volerait donc **sans en payer le coût**.
  → ✅ **`18096753`** : `took_to_the_skies(gs, unit, id, charge=)` devient la **SOURCE UNIQUE** de la
  déclaration, dont dérivent **et** la traversée (`_fly_traversal_active`, coût de descente) **et**
  le `-2"` (`get_squad_move_budget`) — la dissociation n'est plus représentable. C'est une **fonction
  PURE de l'état**, donc vue à l'identique par le masque (`build_squad_move_cell_map`), l'observation
  et l'exécution : une déclaration posée APRÈS la construction du pool aurait offert des destinations
  que le budget réel ne permet plus. Le fingerprint du cache de pool lit le même prédicat. 21.03
  n'énumère que « *normal, advance, fall-back or charge move* » : hors de ces mouvements (pile-in,
  consolidation) il n'y a plus de traversée — c'était le cas `phase != "move"` qui rendait `True`.
  Deux tests **existants** devenus rouges parce que l'unité paie enfin : leur `MOVE` est relevé de 2"
  pour retrouver le **budget effectif** d'origine — **aucune assertion assouplie**.
- **(b) Charge FLY inactive pour toute unité IA.** `_charge_fly_active`
  ([charge_handlers.py:83-88](../../engine/phase_handlers/charge_handlers.py#L83-L88)) rend `False`
  dès `_charge_is_ai_unit`, alors que **21.03 nomme explicitement le mouvement de charge**.
  → ✅ **`350da3cf`** : le court-circuit est supprimé, la déclaration déléguée à la même source unique
  `took_to_the_skies` ; `_charge_is_ai_unit`, sans appelant restant, est supprimé. **Corollaire
  indispensable** : `charge_build_valid_plan` — le chemin qu'exécute `w40k_core.squad_charge`, donc
  l'agent, et l'oracle d'observation — recalculait son budget en ligne et n'appliquait donc **jamais**
  les 2", alors qu'il déduisait déjà `squad_descent_penalty_subhex` (ignore du vertical dès que le vol
  est actif) : l'unité volante aurait ignoré le vertical **gratuitement**. Le budget passe par
  `_charge_budget_subhex`, source unique, où traversée et coût sortent de la **même** déclaration.

**5. 🟢 DÉCISION ASSUMÉE — POLITIQUE MOTEUR DE LA DÉCLARATION : une unité FLY pilotée par le modèle
DÉCLARE SYSTÉMATIQUEMENT.** (Écrite ici parce qu'elle ne figurait **nulle part** dans ce journal,
alors qu'elle change ce que l'agent apprend.) 21.03 fait de « prendre les airs » une **décision du
joueur actif** ; l'agent ne peut pas encore décider — c'est le chantier **`L6`** du lot
([§0.48](#s0.48), P3-7), qui casse le contrat d'observation et sort donc du périmètre de ce
correctif. Il fallait néanmoins **une constante**, et les deux seules possibles ne sont pas
équivalentes : « ne jamais déclarer » rendrait le mot-clé FLY **inerte** pour l'agent — pas plus
conforme, seulement muet ; « toujours déclarer » **conserve la capacité que la règle donne et la
facture au prix légal**, dans un état de jeu toujours valide. C'est la seconde qui est retenue, en
mouvement **comme** en charge.

⚠️ **COÛT ASSUMÉ, permanent et parfois pur** : **2 pouces de mouvement en moins à chaque move**
(normal / advance / fall-back / charge) pour les **cinq types volants du roster d'entraînement**
d'ArmageddonAgent (`VanguardVeteranSquadJumpPack`, `...Plasma`, `...Sergeant`, `ChaplainJumpPack`,
`LandSpeederOnslaughtGatlingCannon`) — **y compris en terrain découvert**, où la traversée
n'apporte rien et où le malus est donc un **pur désavantage** que l'agent ne peut pas refuser.
Ordre de grandeur constaté par la sonde in-engine du commit `350da3cf` : `LandSpeeder…` **70 → 60**
subhex, `VanguardVeteranSquadJumpPack` **60 → 50** (`ish = 5`). ⚠️ Cette constante devra **disparaître
avec `L6`** : tant qu'elle tient, une part de la performance mesurée de l'agent est imputable à un
choix qu'il n'a pas fait.

**Rapport au lot de ré-entraînement ([§0.48](#s0.48))** : ceci est une **non-conformité de moteur**,
pas un changement de contrat — à ne pas confondre avec `L6` (FLY comme **décision d'agent**, P3-7),
qui est dans le lot. Ce correctif-ci ne casse ni `obs_size` ni l'espace d'action, mais il **change
ce qui est appris** : il doit donc être livré **AVANT** la mesure de référence, au même titre que la
rampe de déploiement (§0.46 pt 2) et le correctif des bots (§0.47 É4).

<a id="s0.42"></a>
### 0.42 P2 « décision agent » — ✅ MERGÉ SUR `main` le 2026-07-28 (avec P3-1), NON MESURÉ

**Ce qui est livré.** Le mécanisme générique « décision agent » ([§9.3](V11_phaseA.md#s9.3) P2) et son pilote
([§9.4](V11_phaseA.md#s9.4) point 0) — détail complet et preuves en [§9.3bis](V11_phaseA.md#s9.3bis).

**État du merge (2026-07-28 soir).** `v11-p2-agent-decision` était **rebasée** sur
`v11-p3-1-fight-target` (dont les changements d'action space entraient en conflit avec les siens,
tous résolus dans la branche). Le merge de la branche rebasée a donc porté **les deux chantiers à
la fois** sur `main` : `obs_size` **20740**, `TOTAL_ACTION_SIZE` **1088**, code et 5 profils de
config vérifiés cohérents après merge.

⚠️ **Décision utilisateur ASSUMÉE : merge pendant le run `--new` de §0.14** (démarré le 2026-07-28
à 17 h 25). Le risque était connu et accepté : un sous-processus d'évaluation qui relit la config
d'agent depuis le disque charge un contrat d'observation **incompatible** avec le modèle en cours
d'entraînement.

**CONSTATÉ le 2026-07-28 à 20 h 21** : le run **s'est arrêté**, dernière écriture TensorBoard à
**20 h 20 min 27 s**, quelques minutes après le merge (20 h ~15). Dernier checkpoint sauvegardé :
`ppo_checkpoint_720000_steps.zip` (**720 000 pas**, 20 h 08). C'est la conséquence ATTENDUE du
changement d'`obs_size`, pas un bug de P2 ni de P3-1 — ne pas le re-diagnostiquer comme tel. La
sortie d'erreur est restée dans le terminal du run (non redirigée vers un fichier).

**Ce checkpoint n'est PAS réutilisable** : il porte l'ancien contrat (`obs_size` 20626, action
space 1062), que plus aucun code ne sait construire. Reprendre le run est impossible ; le prochain
doit être `--new`. La mesure de win-rate de §0.14 sur l'ancien contrat n'existera donc jamais —
c'est le coût, accepté, de ce merge.

**Conséquence, non négociable.** Le prochain run **DOIT** être `--new`. Ce n'est pas un choix :
le fail-fast d'`obs_size` à l'init du moteur le rendra explicite au démarrage.

⚠️ **Ne pas comparer les win-rates d'avant et d'après comme s'ils mesuraient P2.** Ils mesureraient
deux contrats d'observation différents, sur un mécanisme qui ne se déclenche sur AUCUN roster
d'entraînement (aucun SM ni Ork ne porte de rule choice — le seul du jeu est le Tyranid Warrior
mêlée). Cf. la réserve de mesure en [§9.3bis](V11_phaseA.md#s9.3bis).

**Effet de bord corrigé au passage** (trouvé par mesure, pas par lecture) : `rule_choice` était
journalisé DEUX fois dans step.log — une écriture directe correcte, plus une tentative de flush qui
échouait en silence sur une clé mal orthographiée. Détail en [§9.3bis](V11_phaseA.md#s9.3bis).

<a id="s0.33"></a>
### 0.33 Rollout buffer surdimensionné — la cause était `n_steps` NON divisé par `n_envs` sur 2 chemins de création sur 3 — ✅ RÉSOLU (2026-08-01)

> ⚠️ **Requalifiée le 2026-08-02.** L'entrée titrait « 46,9 Go pour 39 Go de RAM — 🟠 CONDITIONNEL,
> bloque les profils à 48 envs ». Ce n'était **pas** une fatalité de dimensionnement mais **un
> bug** : `model_params.n_steps` est un **TOTAL par update**, et sa division par `n_envs` ne vivait
> que dans `train_with_scenario_rotation`, alors que `create_model` et `create_multi_agent_model`
> construisent AUSSI un `SubprocVecEnv` de `n_envs`. Un run mono-scénario (`--scenario X --new`)
> allouait donc `8192 × 48` = 393 216 transitions. **Jumeau classique : correction appliquée à un
> chemin sur trois.**

**Correctif — `apply_rollout_n_steps` (`ai/train.py`), point de passage UNIQUE** appelé par les
trois constructeurs :
- `n_steps` est divisé par `n_envs`. La troncature compte : `8192 // 48` donne **170** pas par env,
  soit **8 160** transitions et non 8 192. Le total journalisé est celui **réellement obtenu**,
  jamais celui demandé — annoncer le total demandé avait déjà fait valider deux configurations que
  la troncature rendait identiques.
- Un **garde-fou** lève un `MemoryError` explicite si le buffer dépasserait **0,5 × la mémoire
  disponible**, au lieu d'un OOM sans rapport apparent quelques minutes plus tard.

| | floats / transition |
|---|---|
| vecteur (`obs_size`) | 20 828 |
| grille (9 × 32 × 32) | 9 216 |
| **total** | **30 044**, soit **117,4 Kio** par transition en float32 |

**Dimensionnement réel au 2026-08-02** — les **six** profils portent `n_envs: 48` et
`n_steps: 8192` : **8 160 transitions**, **≈ 0,98 Go** de buffer. Le régime validé de CoreAgent
(`n_steps = 16 384`) reste finançable (**≈ 1,97 Go**) : il n'y a **pas** de plafond à 2048, et la
mémoire ne contraint plus le re-tuning.

⏳ **Arbitrage du 2026-07-28 « 8 envs mesuré MEILLEUR que 48 » : PÉRIMÉ.** Un banc de balayage
dédié (`scripts/ab_sweep_nenvs.py`, 37 runs appariés) a depuis retenu **48** : +43 % de débit face
à 6, −4,2 % face à 64. Les six profils sont à 48 envs, avec le `batch_size: 1020` qu'impose un
rollout réel de 8 160.

⚠️ **Piège de lecture conservé** : le « 14,49 Go, sous la limite de 19,33 Go » de
[`move_action_space_spatial_rework.md`](A_faire/move_action_space_spatial_rework.md) §8.3 ne compte
**que la grille**. Il était juste quand l'obs vectorielle faisait 108 floats ; il est périmé depuis
§0.30, pour une raison qui n'est pas celle de §0.32.

⚠️ **Une recommandation « `n_steps` 8192 → 1024 » a été formulée puis RETIRÉE le même jour. La
retenir aurait dégradé le run.** Ses deux erreurs, à ne pas refaire :

1. **Argument faux.** Elle promettait « 8× plus de mises à jour, donc plus d'apprentissage ». Le
   nombre de PAS DE GRADIENT d'un run ne dépend pas de `n_steps` : il vaut
   `transitions_totales × n_epochs / batch_size`. `n_steps` n'arbitre que **fraîcheur contre
   variance** — des avantages estimés sur moins de données, et donc plus bruités.
2. **Preuve contraire déjà au dossier, non consultée** :
   [`config/agents/CoreAgent/Training_logs.md`](../../config/agents/CoreAgent/Training_logs.md)
   — ablations à 30k épisodes, `n_envs=48`, un seul hyperparamètre changé par run :

   | Changement | Robust score | Verdict noté à l'époque |
   |---|---|---|
   | baseline `n_steps=16384` | **0,4857** | BEST |
   | `n_steps` → 8 192 | 0,3808 | « rollout **trop petit** → instabilité » |
   | `n_steps` → 32 768 | 0,4345 | mieux que 8192, sous la baseline |
   | `batch_size` → 2048 | 0,3281 | « catastrophique, trop peu de pas de gradient par rollout » |

   Sur ce projet, la direction mesurée est donc l'INVERSE : **plus gros, mieux**, avec un optimum
   à 16 384. C'est sur CoreAgent — autre pipeline, autre observation — donc ce n'est pas une
   preuve transférable ; c'est la **seule** preuve disponible, et elle contredit la proposition.

<a id="s0.29"></a>
### 0.29 Scénario SM vs Orks à placement manuel + bascule fixed/active + scheduler curriculum — ✅ LIVRÉ + VALIDÉ IN-ENGINE (2026-07-22)

**But (recadré par l'utilisateur).** Pouvoir **placer les unités manuellement** ET **choisir**, sur un
même fichier, entre placement figé (manuel) et phase de déploiement — le tout sur le terrain réel du
training, sans nouveau terrain. Reliquat demandé : faire évoluer la **proportion figé↔déploiement au
fil du training** (curriculum). Matchup **Space Marines vs Orks**.

**Fichiers livrés.**
- `config/board/44x60x5/scenario/scenario_fixed_brawl_sm_orks.json` — 4 escouades / **36 figurines**,
  format `units[]` avec clé `models` (compositions RÉELLES des rosters training) :
  P1 SM = Intercessor (Bolt Rifle) + VanguardVeteranSquadJumpPack (jump pack) ;
  P2 Orks = 2× Boyz. Chaque figurine a `col/row/unit_type` propre (sergents, plasma, personnages
  fidèles au roster). `terrain_ref` = **`terrain-mc1.json`** (terrain réel du training).
- `tests/unit/engine/test_fixed_brawl_deploy_modes.py` — **verrou** (bascule fixed↔active).
- *(Aucun terrain créé — un premier jet en avait introduit un, retiré à la demande de l'utilisateur.)*

**Le seul levier = `deployment_type`** (tracé, pas supposé). `game_state.py::load_units_from_scenario` :
- `"fixed"` (ou champ absent, défaut ~L274) → chaque unité EXIGE `col/row` top-niveau = ancre =
  `models[0]` (~L589-594), figurines posées telles quelles ; la clé `models[]` est normalisée par
  figurine (~L874-985, override `unit_type`/stats par modèle). Au `reset`, phase `command` directe
  (aucun `deployment`).
- `"active"` → au `reset`, `deployment_type=="active"` déclenche la phase `deployment`
  (`w40k_core.py:1364`), figurines mises à la sentinelle (-1,-1) et placées en jeu (IA/manuel). Les
  `col/row` du fichier sont alors ignorés. `terrain-mc1.json` fournit les `deployment_zones` requises.

**Positions par défaut** (éditables). Board 220×300 subhex. Placées dans les **bandes dégagées de
mc1** (P1 SM rows 92/100, P2 Orks rows 198/206 ; cols 66-154), à l'écart des murs de la ruine
centrale (rows ~120-185) — vérifié : le mode `fixed` chargeait en erreur « footprint on wall hex »
tant que les unités tombaient sur la ruine. Portées lues (datasheets) pour référence : Bolt Rifle
24″=120 subhex, shoota Boyz 18″=90 ; charge 11.02 (≤12″, non-engagé), zone d'engagement 03.04
(2″=10 subhex hz).

**Preuve in-engine (verrou, chemin gym réel).** `python3 -m pytest tests/unit/engine/test_fixed_brawl_deploy_modes.py` :
```
✅ fixed  : phase initiale='command', 4 unités / 36 figurines placées (aucun déploiement)
✅ active : phase initiale='deployment', 4 unités en attente de déploiement
✅ VERROU OK : même fichier, bascule fixed↔active par `deployment_type` (36 figurines).
```
⚠️ Piège rencontré (dans le verrou) : le loader **mémoïse le JSON par chemin absolu** (~L240) — tester
deux modes en réécrivant un seul fichier temporaire relit le cache du 1er mode ; le verrou utilise
donc **deux chemins distincts**.

**Proportionnalité figé↔déploiement au fil du training — ✅ LIVRÉ (scheduler continu).** Approche
retenue (arbitrage utilisateur) : **montée lisse par épisode**, mode `active` tiré à proba p(t)
croissante, sur un SEUL fichier rechargé dans le mode tiré (réutilise les 2 chemins de chargement
éprouvés plutôt qu'un chemin « hybride » risqué côté fuite d'état — cf. §0.25/§0.26). Implémentation
(3 fichiers) :
1. `game_state.py::load_units_from_scenario(..., deployment_type_override=None)` — force le mode du
   chargement en remplaçant le `deployment_type` du JSON (et neutralise les surcharges P1/P2).
2. `w40k_core.py::_configure_deployment_mode_for_episode()` — **miroir de `deployment_random_mix`**
   (orthogonal : celui-ci choisit fixed/active, l'autre randomise les ACTIONS d'un déploiement déjà
   actif). p(t) = `active_ratio_start + (end−start)·min(progress, freeze)`, progress =
   `episode_number/(total_episodes−1)`, Bernoulli(p) → `active`/`fixed`. ⏳ **FORMULE FAUSSE, corrigée
   le 2026-08-02 ([§0.57](#s0.57))** : `episode_number` compte les épisodes d'UN environnement, donc le
   dénominateur est `ceil(total_episodes/n_envs) − 1`. Telle qu'écrite ici, la rampe avançait `n_envs`
   fois trop lentement et **n'a jamais rampé sur un run vectorisé**. Dans `reset()`, impose un
   rechargement avec l'override (reward_configs reconstruits via le chemin `_reload_scenario` existant).
3. Config `x5_new.deployment_mode_schedule` (opt-in, `enabled:false` par défaut) :
   `active_ratio_start/active_ratio_end/schedule:"linear"/freeze_after_progress`, `training_only`.
**Preuve in-engine** — `python3 -m pytest tests/unit/engine/test_deployment_mode_schedule.py` : ratio 0.0→ 20/20 `fixed` ;
ratio 1.0→ 20/20 `active` ; rampe 0→1 (60 ép.)→ part `active` croissante (1re moitié 8, 2e moitié 24),
avec cohérence stricte mode↔phase (`fixed`→`command`, `active`→`deployment`). Le scheduler est
**orthogonal** à `deployment_random_mix` (les deux peuvent coexister). ⚠️ `training_only:true` exige
le scénario sous `.../scenarios/training/` (`_is_training_scenario_context`) — le déposer là pour
l'activer en training réel ; mettre `enabled:true` dans `x5_new`.

**Emplacements DANS les rosters (mode strict sur le chemin roster réel) — ✅ LIVRÉ.** Le training
réel ne joue pas un `units[]` figé : il passe par le **template roster** (`scenario_training_armageddon.json`,
`agent_roster_ref=training_random`, `opponent_roster_ref=[SM,Orks]`, **siège aléatoire**). Or un
roster compact ne portait aucune coordonnée → `fixed` était interdit (`_expand_compact_roster_to_basic_units`
levait). Solution retenue par l'utilisateur (pas de miroir) : **chaque roster déclare `top` ET `bottom`
par figurine**, le loader choisit le côté selon le joueur assigné (**convention P1=top, P2=bottom**) —
comme le siège est aléatoire, les deux côtés sont portés. Implémentation :
- `game_state.py::_expand_compact_roster_to_basic_units` — `models[i]` accepte la forme objet
  `{unit_type, top:{col,row[,level]}, bottom:{...}}` ; unité **mono** (véhicule/perso) : positions au
  **niveau de l'entrée** (`top`/`bottom`) pour NE PAS la transformer en escouade (comportement `active`
  préservé). En `fixed` : positions obligatoires (sinon erreur explicite), `count==1` requis, côté
  sélectionné par joueur. En `active` : positions ignorées (roster à double usage). Helper
  `_parse_roster_model_side` (validation stricte col/row/level).
- Les **4 rosters** training (agent SM/Orks, opponent SM/Orks) portent désormais `top`/`bottom`,
  produits par le **générateur committé `scripts/gen_roster_positions.py`** (reproductible) :
  placement en **réseau hexagonal** (pas 9 subhex) par footprint réel (tailles de socle variables
  persos/véhicules), wall-aware (terrain-mc1), sans chevauchement (le mode `fixed` valide les
  footprints), dans les bandes haute (~rows 40-104) et basse (~196-260). **Cohérence d'escouade
  GARANTIE** : le générateur n'accepte un centre d'escouade que si la formation est cohérente. La
  règle moteur (03.03) exige **la CONNEXITÉ** (une seule chaîne — précision d'arbitre/FAQ) plus
  « à 9" de CHAQUE autre figurine », mesurée en hex centre-à-centre à x1 et bord d'empreinte à x5+
  (bascule de résolution `spatial_relations.geometry_is_hex`, 2026-07-29) ; `squad_min_neighbors`=1
  reste un degré minimal, et `cohesion_distance_mode`="euclidean" ne vaut plus que pour x5 et
  au-delà. Le générateur vise ≥2 centre-à-centre = borne conservatrice. **L'oracle est la fonction moteur `validate_squad_coherency`** — c'est ELLE
  que le verrou asserte à la charge (pas une réimplémentation).
**Preuve in-engine** — `python3 -m pytest tests/unit/engine/test_roster_fixed_positions.py` : 8 épisodes `fixed` (rosters
+ siège tirés au hasard) → **aucun déploiement, toutes figurines placées, P1 en bande haute / P2 en
bande basse, escouades cohérentes** ; 3 épisodes `active` → phase `deployment`, sentinelles.
Cohérence re-vérifiée hors test : 0 figurine sous-cohérente sur 12 chargements (2 sièges × 6 rosters
aléatoires). Régression : template `active` + rosters positionnés, scheduler off → step normal
(deployment→move→shoot), aucun crash. Le scheduler `deployment_mode_schedule` rampe donc **strict
(positions rosters) → déploiement appris** directement sur le vrai flux (rotation SM/Orks + siège
aléatoires conservés). ⚠️ Si une composition de roster change, relancer `gen_roster_positions.py`.

**Suite (mécanique LIVRÉE ; reste l'USAGE + la mesure — arbitrage utilisateur / dépendances).** Un
agent frais qui reprend :
1. **Activer le curriculum** : `x5_new.deployment_mode_schedule.enabled = true` puis régler la rampe
   (`active_ratio_start`/`active_ratio_end`/`freeze_after_progress`, p.ex. 0.0→1.0 sur 0.8 de la
   progression). Aucun autre câblage : le template roster réel (`scenario_training_armageddon.json`)
   marche tel quel, rosters déjà positionnés.
   > 🔴 **RELEVÉ le 2026-07-28 soir — `enabled: true` NE SUFFIT PAS, et c'est le piège exact du
   > profil `x1` aujourd'hui.** Les 3 profils qui la portent (`x1`, `x5_new`, `x5_debug` — vérifié
   > le 2026-07-28 ; `x5_append` et `x1_debug` n'ont pas la clé) déclarent `enabled: true` avec
   > `active_ratio_start = active_ratio_end = 0.0` : le scheduler s'exécute, calcule `p_active = 0`
   > et renvoie `fixed` à **tous** les épisodes. Un `enabled: true` sans rampe non nulle est
   > indistinguable d'un scheduler éteint dans les logs. **C'est la RAMPE qui active le
   > curriculum, pas le drapeau.**
2. **Vérifier en épisode réel** avant un long run : `python3 ai/train.py --agent ArmageddonAgent
   --training-config x5_new --step` + `ai/analyzer.py` + replay → confirmer que des épisodes `fixed`
   (placement rosters, aucun déploiement) ET `active` (déploiement) surviennent, dans la bonne
   proportion selon l'avancement.
3. **Mesurer l'objectif curriculum** : win-rate en régime `fixed` (strict) vs `active` au fil de la
   rampe — c'est la métrique qui valide « scénarios fixes → apprendre à se déployer ». **Rejoint
   §0.14 (win-rate)**, ✅ **débloqué le 2026-07-26** (§0.27 corrigé, [§9.2.5](V11_phaseA.md#s9.2.5) livré).
Décisions ouvertes (utilisateur) : forme exacte de la rampe ; coexistence éventuelle avec
`deployment_random_mix` ; siège (`agent_seat_mode`) gardé aléatoire ou figé en phase strict.

**Outillage : jouer/visualiser UN scénario explicite en éval (2026-07-22).** Pour observer un
scénario précis (ex. `scenario_fixed_brawl_sm_orks.json`, placement fixed) avec le modèle courant
SANS l'entraîner ni écraser le `.zip`, `--test-only` accepte désormais un chemin de scénario
explicite :
`python3 ai/train.py --agent ArmageddonAgent --training-config x5_debug --test-only --eval --step
--scenario config/board/44x60x5/scenario/scenario_fixed_brawl_sm_orks.json`.
Il est joué **tel quel** (`train.py`, branche test-only) : ni repli holdout, ni matérialisation
`wall_ref` (celle-ci exige un scénario sous `agents/.../scenarios/<split>/` et réécrit le terrain —
elle casserait un scénario autonome sous `config/board/`). Mécanisme : `evaluate_against_bots(...,
materialize_eval_refs=False, scenario_list_override=[chemin])`. Le mode holdout par défaut
(`materialize_eval_refs=True`) est **inchangé**. Verrou : `tests/unit/ai/test_eval_explicit_scenario.py`
(ROUGE : la matérialisation lève hors `agents/` ; VERT : le scénario explicite est joué, 0 planté).
⚠️ Un scénario `fixed` joué en test-only n'a **aucune** phase de déploiement (step.log : 0
`DEPLOYMENT`, figurines aux positions du fichier dès T1).

<a id="s0.43"></a>
### 0.43 [§9](V11_phaseA.md#s9) P3-2 — la cible de charge devient une dimension d'action (slots ennemis + pointeur) — ✅ LIVRÉ ET MERGÉ sur `main`, NON MESURÉ (2026-07-28 ; merge vérifié le 2026-08-02)

**Contenu d'état complet en [§9.4bis](V11_phaseA.md#s9.4bis)** (ce que le code fait, preuves,
mesures) — conformément à la règle « un contenu d'état vit à UN seul endroit ». Cette entrée porte
l'**orchestration** : ce qu'il reste à décider et ce qu'il ne faut pas re-diagnostiquer.

**En une phrase.** `charge` était une action nue et c'est le **décodeur** qui choisissait la cible
(`get_best_enemy_score_for_unit`, damage_ratio) ; la cible est désormais portée par l'action
(`CHARGE_SLOT` 1045-1064, un par slot ennemi), scorée par une **tête pointeur**, avec parité
masque/commit dans les deux sens et un bit d'observation de support
(`charge_reachable_max_roll`). `TOTAL_ACTION_SIZE` **1088 → 1107**, `obs_size` **20740 → 20768**,
5 profils de config alignés.

🔴 **CE QUI N'EST PAS FAIT, et pourquoi.**
1. **Le merge sur `main`.** La livraison est sur la branche **`v11-p3-2-charge-target`**. C'est
   une **décision utilisateur**, pas un oubli : §0.41 et §0.42 ont établi qu'un changement
   d'action space ou d'observation **n'est pas inerte pour un run déjà lancé** (les workers
   d'évaluation démarrent en `spawn` et ré-importent le code **depuis le disque**), et le run
   §0.14 du 2026-07-28 en est mort.
   > 🔴 **AFFIRMATION FAUSSE, CORRIGÉE le 2026-07-28 23 h : « Le working tree a été rendu à
   > `main` en fin de session » est DÉMENTI par le dépôt.** `git rev-parse --abbrev-ref HEAD`
   > rend **`v11-p3-2-charge-target`** : le working tree est resté sur la branche. C'est
   > **précisément ce qui a tué le second run §0.14** — le `git checkout` de 21 h 39 a réécrit
   > `pointer_policy.py`/`macro_intents.py`/le JSON de config **sur le disque**, pendant que le
   > run tournait avec l'architecture P2 en mémoire. Voir la leçon durcie en §0bis : le danger
   > n'est PAS « merger sur `main` », c'est **toute modification du working tree**, checkout
   > compris. Avant de lancer un run, vérifier la branche courante ET `git status`.
2. **Le win-rate** exigé par [§9.6](V11_phaseA.md#s9.6). Indisponible : l'action space **et**
   l'observation changent ⇒ tout modèle existant est incompatible ⇒ retrain `--new`.
3. **Le regret** de la décision ([§9.0bis](V11_phaseA.md#s9.0bis) réserve 1) : non mesuré, comme
   pour P3-1. **À confronter au premier run** — si le win-rate baisse, c'est la première
   hypothèse à instruire.

⚠️ **Ne pas re-diagnostiquer.** Les **bots d'évaluation ont changé de comportement**, comme à
P3-1 : ils prennent le premier slot de charge ouvert, donc la cible la plus menaçante, au lieu du
`damage_ratio` du décodeur. **Les win-rates d'avant cette tranche ne sont pas comparables à ceux
d'après** — la baseline adverse a changé.

⚠️ **Une modification de `ArmageddonAgent_training_config.json` (`active_ratio_end` 0.0 → 0.8) est
apparue dans le working tree pendant cette session, sans être de cette tranche** ; elle a été
délibérément **laissée non commitée**, seul `obs_size` a été commité. À reprendre par son auteur.


> Entrées closes, **conservées intégralement** : mesures, sorties de run copiées, tableaux de
> sites audités, diagnostics d'origine et attributions erronées assumées. Rien n'y est résumé.
> Les titres et ancres `### 0.x` sont **inchangés** : tous les renvois `§0.x` du reste du
> document restent valides.
>
> Les entrées **scindées** (§0.0, §0.5, §0.6, §0.7, §0.13) portent un renvoi `➜` à l'endroit
> exact d'où leur part ouverte a été déplacée.
>
> ⚠️ Ces entrées décrivent l'état **au moment où elles ont été écrites**. Plusieurs contiennent
> des affirmations que leurs propres auteurs ont ensuite corrigées sur place. Ne pas s'appuyer
> sur l'une d'elles sans la confronter au code.


<a id="s0.45"></a>
### 0.45 `ai/scenario_manager.py` — générateur de scénarios abandonné par la production, SUPPRIMÉ — ✅ CLOS (2026-07-29)

**Ce qui a été supprimé.** `ai/scenario_manager.py` (**635 lignes**, classe `ScenarioManager`
+ dataclass `ScenarioTemplate` + une fonction `test_scenario_manager()` sous `__main__`) et son
fichier de tests `tests/unit/ai/test_scenario_manager.py` (**203 lignes, 9 tests**). Avec eux :
l'import `from ai.scenario_manager import ScenarioManager` de `ai/train.py`, la fonction
`test_scenario_manager_integration()` (36 lignes), le flag CLI `--test-integration` et son
aiguillage dans `main()`, l'import mort de `ai/replay_converter.py:133`, l'entrée
`"ai/scenario_manager.py"` de `scripts/backup_select.py` et la ligne `--cov=ai/scenario_manager.py`
de `.github/workflows/unit-tests.yml`. **Décision utilisateur : le flag `--test-integration`
n'est pas utilisé** → option « suppression », pas « conservation des 3 méthodes exercées ».

**Pourquoi c'était mort — le fait décisif, vérifié par exécution le 2026-07-29.** Le seul chemin
de production (`--test-integration`) **ne pouvait pas s'exécuter** : `_load_scenario_templates`
exige `config/scenario_templates.json`, **ce fichier n'existe pas dans le dépôt**, et la branche
`else` lève explicitement (`FileNotFoundError: … No fallbacks allowed - file must exist`).
Reproduit en chargeant le module supprimé depuis `git show HEAD~1` :

```
CONSTRUCTION LEVE: FileNotFoundError: Scenario templates not found at
  <repo>/config/scenario_templates.json. No fallbacks allowed - file must exist.
```

Autrement dit `ScenarioManager(…)` levait **au constructeur** ; le diagnostic attrapait
l'exception, imprimait `❌ Integration test failed` et rendait 1. Les « 3 méthodes exercées par
la production » ne l'étaient donc jamais. Ce point était déjà connu — [`V11_tranches.md` T4](V11_tranches.md)
écrivait « chemin dormant — `config/scenario_templates.json` absent → lève à la construction » —
mais il avait été classé « chantier séparé à valider » au lieu de « code mort ».

**Le deuxième aveu, dans le code lui-même.** Le seul consommateur applicatif,
`ai/replay_converter.py`, importait la classe **sans jamais s'en servir**, et son commentaire deux
lignes plus bas disait pourquoi : *« Use actual bot scenarios instead of generating dynamic ones —
this ensures the scenario matches what the model was trained on »*. Le renoncement était documenté
sur place ; seul l'import était resté.

**Mesures re-faites le 2026-07-29 (worktree `40k-scenmgr`, branche `dead-scenario-manager`) et
écarts constatés :**

| Mesure | Attendu (état du prompt) | Re-mesuré | Écart |
|---|---|---|---|
| Tailles | 635 / 203 lignes, 9 tests verts | identique | — |
| Bloc inatteignable (AST) | 1 seul résultat, `scenario_manager.py:361` | **4** résultats au moment de la mesure | 🔴 les 3 autres (`fight_handlers:6021`, `shooting_handlers:3885`, **`shared_utils:2242`**) étaient encore sur `main` parce que `v11-0.38-dead-code` **n'était pas mergée** — le prompt les croyait « traités » alors qu'ils vivaient sur une branche restée de côté. ✅ **SOLDÉ le 2026-07-29** : les deux branches sont mergées (`b371a45e` puis `38808bf0`) et **le balayage AST rend `TOTAL = 0`** sur `engine`/`ai`/`services`/`shared`. Aucune des deux ne suffisait seule : `v11-0.38-dead-code` traitait les 3 blocs moteur (dont `shared_utils:2242`, commit `3137c25a`) mais gardait `scenario_manager.py:361` ; celle-ci faisait l'inverse. |
| Références hors tests | `train.py` + `replay_converter.py:133` | + **`scripts/backup_select.py:42`** et **`.github/workflows/unit-tests.yml:38`** | 🔴 deux références non-`.py`/non-import ratées par le grep initial (liste de sauvegarde, gate de couverture CI) |
| Méthodes sans appelant de production | « 12 sur 15 » | **12 sur 15**, confirmé par AST (résolution des `self.X` + appels internes) | la mesure d'origine était juste, mais sa méthode était fausse : `__init__` remontait 15 faux positifs hors module, et `_load_scenario_templates` / `_analyze_training_balance` étaient appelées en interne |
| Sans aucune référence nulle part | `_save_scenario_templates` (26 l) | identique | — |

**Preuves.** `python3 -c "import ai.train, ai.replay_converter"` OK · `pyright ai/train.py
ai/replay_converter.py scripts/backup_select.py` = **0 erreur** · **83 tests verts** sur les
9 fichiers de tests qui touchent `train.py`/`replay_converter.py` (lancés nommément) · le script
AST « instruction après un `return` » ne rend **plus** `ai/scenario_manager.py:361` · **orphelines
comparées AVANT/APRÈS par AST** (fonctions du backend dont le nom n'est référencé nulle part, en
comptant attributs, alias d'import et chaînes littérales pour les accès dynamiques) : **124 → 123**,
seul `_save_scenario_templates` disparaît, **aucune fonction rendue orpheline** par la suppression.
Aucune contre-épreuve par mutation n'est due : **aucun comportement n'est conservé**.

**Effet de bord découvert en route, ✅ CORRIGÉ.** `scripts/backup_select.py` **s'exécutait à
l'import** (aucune garde `if __name__ == "__main__"`) : un simple `import scripts.backup_select`,
fait pour vérifier que la ligne retirée ne cassait rien, a lancé une sauvegarde vers un chemin
Windows et écrit un `.zip` **dans le dépôt**. Les 39 lignes à effet (`makedirs`, `copy2`,
`make_archive`) sont désormais dans `run_backup()`, appelée sous garde `__main__` ; les 276 lignes
de déclaration (liste des fichiers) restent au niveau module. Vérifié : `import scripts.backup_select`
ne produit **aucun** fichier (`git status` ne montre que le source modifié), `pyright` 0 erreur.
Le premier réflexe avait été de documenter le piège au lieu de le corriger — c'est précisément
ce que la règle « clôture complète » interdit.

⚠️ **Motif §0bis, quatrième occurrence** — *du code testé mais jamais appelé* (après T6-i, §0.38 et
§0.39). Variante propre à ce dossier : les 9 tests instanciaient la classe par
`ScenarioManager.__new__(ScenarioManager)` pour **contourner le constructeur qui lève**. Un test
qui doit sauter `__init__` pour s'exécuter atteste que la production ne peut pas construire l'objet.

<a id="s0.41"></a>
### 0.41 [§9](V11_phaseA.md#s9) P3-1 — la cible de mêlée devient une dimension d'action (slots ennemis + pointeur) — ✅ LIVRÉ, NON MESURÉ (2026-07-28)

> ✅ **MERGÉ sur `main` le 2026-07-28 soir**, en même temps que §0.42 (P2, rebasée dessus) et
> **pendant** le run §0.14, sur décision utilisateur. Le passage « Pourquoi une branche » en fin
> d'entrée décrit la précaution d'origine et reste vrai comme méthode ; il ne décrit plus l'état.
> Le retrain suivant DOIT être `--new` (l'action space ET l'observation changent).

**Ce qui était en place.** `squad_fight` était une action **sans cible** : le moteur choisissait
la cible lui-même par `_ai_select_fight_target` (lowest HP puis menace, via `RewardMapper`), au
fond de `_process_squad_action` ([w40k_core.py](../../engine/w40k_core.py), branche `squad_fight`).
Conséquences vérifiées par lecture : l'agent ne décidait **rien** en mêlée, et le **pool 12.05**
(`_fight_build_valid_target_pool`) n'apparaissait **nulle part** dans le masque — le masque disait
« je peux combattre », jamais « qui je peux frapper ».

**Ce qui est livré.** La cible est portée par l'ACTION, indexée sur le **même mapping de slots
ennemis que le tir** (`get_enemy_slot_mapping`), donc sur la **même ligne du tenseur ennemi de
l'observation** (invariant D1) :

| | Avant | Après |
|---|---|---|
| Action de combat | `ACTION_FIGHT` = 1046 (sans cible) | `FIGHT_SLOT` **1046-1065** (20) + `ACTION_FIGHT_NO_TARGET` **1066** |
| `TOTAL_ACTION_SIZE` | 1062 | **1082** |
| `obs_size` | 20626 | **20654** (`n_models_engaging`, cf. P4 ci-dessous) |
| Choix de la cible | moteur (`_ai_select_fight_target`) | **agent** |

- `FIGHT_SLOT_COUNT` est **dérivé** de `SHOOT_SLOT_COUNT`, jamais recopié : les désolidariser
  ferait pointer l'action de combat `i` et l'observation `i` sur deux escouades différentes sans
  que rien ne lève. Verrouillé par `test_action_space_mirror.py`.
- `ACTION_FIGHT_NO_TARGET` n'est pas un cas d'erreur : 12.04/12.06 rendent une escouade éligible
  **sans cible** (sa cible est morte, overrun). Fusionner ce cas avec un slot rendrait « frapper
  le slot i » ambigu.
- **Parité masque/commit dans les DEUX sens** : le masque n'ouvre un slot que si sa cible est
  dans le pool 12.05, et n'ouvre `NO_TARGET` que si le pool est vide ; le commit refuse tout slot
  hors pool ET tout « combat à vide » avec pool non vide. Aucun repli sur l'heuristique.
- **Aucune troncature silencieuse** : une cible 12.05 sans slot mappé est **loguée** (`[SLOTS]`).
  Impossible en pratique (≤ 6 escouades par camp mesurées, 20 slots), mais jamais muette.

**Décision d'architecture — pourquoi PAS le `CHOICE_0..K-1` de [§9.3](V11_phaseA.md#s9.3).** La spec P2 date du
2026-07-14, **avant** §0.30 T-E (tête pointeur de tir) et §0.32 T-G (tête 1x1 de move). Elle
propose K actions **génériques** dont les logits sortiraient de `action_net`, une colonne dense
par rang de candidat — c'est-à-dire exactement le défaut que T-E et T-G ont supprimé : la colonne
« candidat 2 » n'apprend rien de la colonne « candidat 1 », et elle ne sait pas *ce qu'est* le
candidat 2. Pour une décision dont les candidats sont des **entités déjà encodées**, la
paramétrisation correcte est celle du tir : **une dimension d'action par slot, scorée par produit
scalaire sur l'embedding de l'entité**. Coût en paramètres d'un slot : **zéro**. Ce que le réseau
apprend d'un ennemi sert aux deux têtes.
➜ **Le mécanisme `pending_agent_decision` générique reste pertinent — pour les décisions
NON-entité seulement** (rule-choice, FLY oui/non, pile-in oui/non). Il n'est pas livré ici : le
livrer sans décision non-entité réellement exercée en aurait fait du code jamais appelé, le motif
que §0bis existe pour interdire.

**P4 (observation de support) — `n_models_engaging`, sans quoi la tranche était incomplète.**
[§9.5](V11_phaseA.md#s9.5) exige « les features nécessaires aux choix ». Une fois la cible devenue une décision, il
manquait la principale : **combien de MES figurines peuvent frapper CETTE cible** (04.02) — donc
avec quelle force je la frappe. La tête pointeur aurait scoré des cibles sans le savoir. Aucun
champ existant ne le disait, et c'est vérifié par test, pas supposé :
- `n_fight_eligible` **agrège sur toutes les cibles** : à deux ennemis engagés il rend la même
  valeur pour les deux (contre-épreuve dans `test_field_discriminates_between_two_engaged_enemies`) ;
- `edge_distance` mesure l'**escouade entière** : à distance d'ancre égale, deux cibles peuvent
  mobiliser un nombre très différent de figurines (04.02 s'évalue par figurine, pas par ancre).

C'est une grandeur de **paire**, comme `los_can_see` : émise sur les entités ENNEMIES seulement,
0 sur les alliées. `obs_size` **20626 → 20654** (+1 feature × 28 entités), les 5 profils de config
sont alignés — coût de retrain **marginal nul**, l'action space l'imposait déjà.

⚠️ **Oracle unique, et perf mesurée.** Le comptage appelle le prédicat MOTEUR de déclaration
d'attaque, jamais une réimplémentation (une métrique divergente ferait annoncer à l'obs un volume
d'attaques que la résolution ne produit pas). Mais `_model_can_fight_target` **reconstruit
l'empreinte synthétique** de la figurine à chaque appel, alors que `build_squad_observation` les a
déjà toutes construites — et l'observation est bâtie à CHAQUE step. Son cœur a donc été extrait en
`model_entry_can_fight_target(game_state, entrée_déjà_construite, cible, ez)`, dont
`_model_can_fight_target` est désormais le **wrapper** : même prédicat, un seul corps.
**Mesuré** : 41,7 µs/appel avec reconstruction contre **4,5 µs** sans, soit **9,2×**. Sur le pire
cas réaliste (20 figurines × 3 cibles) : **2,50 ms → 0,27 ms**, à comparer aux ~2,5 ms que coûte
l'observation entière. Sans cette factorisation, la feature aurait à elle seule doublé le coût de
l'observation.

**Tête pointeur : une requête DISTINCTE, des embeddings PARTAGÉS.** `fight_query_net` est une
seconde `Linear(latent, entity_dim)` appliquée aux mêmes embeddings que le tir. Partager la
requête forcerait un ordre de préférence unique pour les deux phases, alors que « quel ennemi
tirer » (portée, LoS, couvert) et « quel ennemi frapper » (valeur de la cible, riposte) ne sont
pas la même question. Coût : `entity_dim × latent_dim` paramètres, et rien de plus.

**Bots d'évaluation — changement de comportement ASSUMÉ.** `_first_fight_action_in` prend le
premier slot ouvert, donc la cible **la plus menaçante** (les slots sont attribués par menace
décroissante) : c'est exactement l'heuristique que ces bots appliquent déjà au tir. Ils ne passent
donc plus par `_ai_select_fight_target` (lowest HP d'abord). ⚠️ **Les win-rates mesurés avant
cette tranche ne sont pas comparables à ceux d'après** — la baseline adverse a changé.

**Ce qui reste vif de `_ai_select_fight_target`** : le flux **PvP** (clic sans cible,
fight_handlers ~2813, ~4969, ~5725). Le pipeline gym ne l'appelle plus.

**Preuves (tests ciblés, verts — aucune suite complète lancée, c'est l'utilisateur qui la lance).**

| Fichier | Résultat |
|---|---|
| `tests/unit/engine/test_squad_fight_target_parity.py` | **8 verts**, dont **2 gardes neuves** : slot hors pool 12.05 refusé, « combat à vide » avec pool non vide refusé. Le test de parité vérifie désormais que les slots ouverts décrivent **exactement** le pool 12.05. |
| `tests/unit/engine/test_action_space_mirror.py` | **10 verts** (miroir `macro_intents` ↔ `shared_utils` étendu aux slots de combat ; pavage `[0, SIZE)` re-vérifié). |
| `tests/unit/ai/test_pointer_head.py` + `test_evaluation_bots.py` + `test_fight_target_selection_no_fallback.py` | **44 verts**. `test_pointer_logit_is_slot_local` constate maintenant que perturber l'embedding du slot 1 déplace **deux** logits (tir 1 ET combat 1) — c'est le partage recherché, pas une fuite. |
| batterie fight (`cascade_fight_subphases`, `fight_execution`, `fight_resolution`, `fight_v11_selection`, `fight_v11_orchestration`, `squad_fight_declaration`, `fight_v11_consolidation`, `fight_v11_foundations`) | **92 verts** |
| `test_blast_cleave`, `test_extra_attacks_fight`, `test_precision` | **19 verts** |
| `tests/unit/engine/test_squad_obs_fight_target_support.py` (**neuf**) | **6 verts** — verrou de `n_models_engaging` : comptage exact, **discrimination entre deux cibles engagées** (avec la contre-épreuve sur `n_fight_eligible`), accord avec l'oracle moteur, 0 hors portée, 0 sur les alliées, et **parité obs↔masque** (`n_models_engaging > 0` ⟺ le masque ouvre le slot). |
| batterie observation (`structure_doc`, `enemy_block`, `enemy_cover`, `model_engagement`, `vector_split`, `enemy_slot_alignment`, `observation_builder`, `entity_obs_equivalence`, `entity_encoder_extractor`) | **72 verts** |

⚠️ `test_squad_obs_structure_doc.py` verrouille la **documentation** : `Documentation/AI_OBSERVATION.md`
(Structure Overview, layout `enemies_cont`, historique d'`obs_size`) a dû être mis à jour, sans quoi
ces tests échouent. C'est ce qui garantit que le schéma documenté et le schéma calculé coïncident.

**🔴 CE QUI N'EST PAS MESURÉ, et ne peut pas l'être avant le prochain retrain.**
1. Le **win-rate** exigé par [§9.6](V11_phaseA.md#s9.6) (« ≥ tranche précédente, sinon corriger observation/reward
   AVANT d'empiler »). L'action space change ⇒ modèle incompatible ⇒ `--new` obligatoire.
2. Le **regret** de la décision exigé par [§9.0bis](V11_phaseA.md#s9.0bis) réserve 1 (mesurer l'écart entre le choix
   optimal et celui de l'heuristique auto AVANT de brancher). Il n'a **pas** été mesuré ici : la
   décision de brancher repose sur le raisonnement (le focus-fire et l'achèvement d'unité ne sont
   pas exprimables par « lowest HP puis menace »), pas sur une mesure. **À confronter au premier
   run.** Si le win-rate baisse, c'est la première hypothèse à instruire.

**🔴 Le point 0 de [§9.4](V11_phaseA.md#s9.4) (« rule-choice, le plus urgent ») est INERTE dans le training — vérifié.**
`raw_action_int % len(options)` ([w40k_core.py](../../engine/w40k_core.py), `_select_ai_rule_choice_option`) ne
s'exécute **jamais** sur les rosters d'entraînement. Chaîne de vérification, dans l'ordre :
`grep "usage.*or\|unique"` sur `config/` = **0** (le `usage`/`choice_timing` vit dans les rosters
TS, pas dans `config/unit_rules.json`) ; sur `frontend/src/roster/` = **un seul** porteur,
`TyranidWarriorMelee` (`adrenalised_onslaught`, `usage: "or"`) ; les 4 rosters
`config/agents/ArmageddonAgent/rosters/500pts/*/` ne contiennent **aucune** unité tyranide (23
types listés, tous SM ou Orks). **Conclusion : brancher P2 sur le rule-choice aurait produit un
mécanisme jamais exercé par le training** — le motif §0.4/§0.38 exactement. Le `% len(options)`
reste donc vif et doit être traité **le jour où un roster tyranide entre dans le training**, ou
pour le PvE/`rule_checker` qui, eux, l'exercent. Son étiquette « le plus urgent » de [§9.4](V11_phaseA.md#s9.4) est
**périmée** : elle datait d'avant le choix des rosters SM/Orks (§0.29).

**Pourquoi une branche et pas `main`.** Le run §0.14 tourne depuis 17h23 (`--training-config x1
--new`, PID relevé). Ses workers d'entraînement sont forkés une fois — mais
`ai/bot_evaluation.py` crée ses workers d'évaluation en **`mp.get_context("spawn")`**, et un
worker `spawn` **ré-importe tout le code depuis le disque**. Avec `TOTAL_ACTION_SIZE` passé à 1082
sur le disque et un modèle à 1062 en mémoire, la **prochaine évaluation** (`bot_eval_freq = 2000`)
aurait planté ou, pire, mesuré faux. `main` a donc été laissé intact.
⚠️ **Leçon durable, reportée en §0bis** : un changement d'espace d'action ou d'observation n'est
pas « inerte pour un run déjà lancé ». Vérifier le mode de démarrage des sous-processus
(`fork` vs `spawn`) avant de conclure qu'un run en cours est protégé.

<a id="s0.40"></a>
### 0.40 Observation de la phase de déploiement — les 5 points ✅ LIVRÉS — ✅ CLOS (2026-07-29)

**Le contenu d'état vit dans
[`Implémenté/observation_deploiement.md`](Implémenté/observation_deploiement.md)** (extrait de
l'audit archivé `Implémenté/V11_audit_observation.md` §11 le 2026-07-28, constats re-vérifiés dans
le code) — cette entrée n'est que le **pointeur d'orchestration**, conformément à la règle « un
contenu d'état vit à UN seul endroit ». Le document est **intégralement clos** et classé.

**En une phrase.** L'agent déployait à l'aveugle sur cinq défauts distincts et cumulatifs : il
décrivait une autre unité que celle qu'il posait (1), regardait une autre région du plateau (2 et
4), s'y déclarait au contact de l'ennemi (5) — et ne voyait rien de ce que ses cinq actions
feraient (3). Les cinq sont corrigés.

**Points 1, 2, 4 et 5 — livrés les 2026-07-28 / 07-29, `obs_size` INCHANGÉ (20768).**
- **point 1 ✅** (`0e0551e8`) — l'obs décrivait `next(iter(units_cache))` et non l'unité du masque.
  Source unique désormais : `ActionDecoder.get_deployment_active_unit`, qui **lève** sur pool vide
  au lieu de rendre une obs nulle.
- **point 2 ✅** (`2893bbcb`) — la grille égocentrique était centrée sur la sentinelle `(-1,-1)`,
  donc sur une autre région du plateau (0 % de la zone du joueur 1 visible). Elle est ancrée sur la
  **zone de déploiement** lue dans `deployment_state["deployment_pools"]`, géométrie
  `engine/spatial_grid` **inchangée** (seul l'ancrage bouge). 96 %/78 % de la zone visible après.
- **point 4 ✅** (`6cc4585a`, trouvé en vérifiant le correctif du point 2) — le **vecteur** mesurait
  lui aussi depuis la sentinelle. L'agent voyait l'objectif 0 à **38,3** — le plus proche — alors
  qu'il est à **178,9** de sa zone, et ne voyait pas l'objectif 4 à **11,3** : l'**ordre des
  objectifs était inversé**, et les trois actions de zone s'appuient sur ces nombres. L'origine
  d'une escouade non posée est désormais celle de la grille (`squad_grid_anchor`), ce qui
  **rétablit** l'invariant §0.32 T-I. Choix tranché : une entité pas encore posée n'a **aucune**
  position relative (le bit `deploy_not_on_board` porte l'information) — sans quoi déplacer
  l'origine les aurait toutes empilées à une distance absurde au nord-ouest.
- **point 5 ✅** (`388d85cd`, trouvé en re-vérifiant le point 4) — une escouade pas encore mise en
  place se déclarait `engaged = 1`, `n_in_enemy_ez = 6`, `n_fight_eligible = 6`,
  `n_models_engaging = 6` et `los_can_see = 1` sur les 6 slots ennemis : toutes les unités non
  posées partagent la sentinelle, donc leurs empreintes se recouvrent. **Contraire à 03.04**
  (`03 Moving.pdf`) : l'engagement range est une aire **du champ de bataille**. Filtre chez
  l'appelant, en un point (`on_battlefield`, 1,9 µs = 0,08 % d'une observation) ; `coherent` n'est
  délibérément PAS neutralisé (03.03 : « **if that unit is on the battlefield**, it is in
  coherency »).

**Point 3 ✅ — livré le 2026-07-29. `obs_size` 20768 → 20828, donc RETRAIN `--new`.**

Les 5 actions `4-8` ne sont pas « les 5 premiers hexes valides » (énoncé d'origine **faux**) mais
5 **stratégies** — front agressif · pression sur objectif · sûr/cohésion · flanc gauche · flanc
droit — évaluées sur **tous** les hexes valides (~14 000 au premier step). L'observation n'en
décrivait **aucun** : cinq boîtes noires, au moment précis où l'agent choisit son point d'entrée.

Nouveau bloc `deploy_cand_cont` (5, 8) / `deploy_cand_bin` (5, 4) — **60 scalaires** — décrit par
slot **l'hexe que sa stratégie poserait** : position relative à l'ancre de zone (même repère T-I),
distances au centre d'objectif / à l'ennemi / à l'allié posé le plus proches, exposition LoS réelle
et potentielle, étalement en colonne, objectif (14.02), couvert (13.08), et le bit `present`.
Documenté dimension par dimension dans
[`AI_OBSERVATION.md`](../AI_OBSERVATION.md) (« Section Breakdown »).

Trois points de conception, chacun verrouillé par test :
1. **Un candidat se décrit par son EFFET, jamais par son index.** Le masque n'ouvre que
   `min(5, n_hexes)` slots (`open_deploy_slot_count`, source unique désormais partagée par les deux
   sites de masque et par le constructeur de candidats), donc en fin de déploiement ce sont les
   stratégies d'**indices bas** qui survivent : le lien slot ↔ stratégie n'est pas stable. Un slot
   FERMÉ est une ligne de zéros, `present` compris — jamais un candidat plausible.
2. **Source unique, pas une seconde géométrie.** `ActionDecoder.deployment_slot_candidates` rend
   l'hexe **et le plan de formation validé** ; le décodeur y lit ce qu'il commite et l'observation
   ce qu'elle décrit. Un second calcul aurait laissé l'agent choisir d'après un hexe que le moteur
   n'aurait pas posé (motif D1).
3. **Garde de phase**, même patron que `is_charge_phase` : hors déploiement le bloc est nul et rien
   n'est calculé. Il reste nul aussi pour une escouade qui n'est pas celle du masque.

**Perf — mesurée, pas estimée.** Décrire 5 stratégies au lieu d'en évaluer une exigeait 5 passes de
scoring sur toute la zone : **871 ms** par step de déploiement en appelant 5 fois l'ancienne
sélection scalaire. La sélection a donc été **vectorisée** (colonnes de score calculées une fois
pour les 5 stratégies, `np.lexsort` par stratégie). Résultat mesuré sur le board x5, 3 épisodes,
33 steps de déploiement : **285 ms → 345 ms** par step, soit **+59 ms (+21 %)** pour cinq candidats
décrits au lieu d'un seul évalué. **Parité de choix EXACTE** avec l'implémentation scalaire,
vérifiée hexe par hexe sur 33 états × 5 stratégies (le tri lexicographique numpy reproduit le
`max()` sur tuples, index croissant compris).

**Nouveau cache** : `_deployment_slot_candidates`, ajouté à l'inventaire d'`AI_OBSERVATION.md`
et à `test_obs_caches_die_with_the_episode.py`. **Trou trouvé au passage** (2026-07-29, en
vérifiant ce point) : `_deployment_scoring_cache` — celui que le bloc candidat LIT — n'était purgé
**nulle part**. `reset_episode_caches` ne voit que les caches d'INSTANCE du décodeur, pas ceux
posés dans le `game_state`, et son garde-fou (« le jeu d'hexes valides a-t-il changé ? ») ne mord
pas au cas critique : un épisode interrompu AVANT la 1re pose laisse un cache dont le jeu d'hexes
coïncide exactement avec celui du nouvel épisode — servi tel quel, il porterait les expositions LoS
des **murs du terrain précédent**. Purgé et inscrit à l'inventaire (**six → huit** caches), rouge
sous mutation de la purge. Son tampon est l'état des unités
posées — qui recommence **identique** d'un épisode à l'autre : la purge au `reset` est donc
obligatoire, le tampon seul ne suffirait pas.

**Verrous** (`test_deployment_candidate_observation.py`, 10 tests, chacun rouge sous mutation de son
propre volet) : le slot `i` décrit l'hexe que `_select_deployment_hex_for_action(4+i)` choisirait
(cache purgé avant l'interrogation, pour que le décodeur recalcule) ; les positions sont mesurées
depuis l'ancre de zone et **diffèrent** de celles qu'aurait produites la sentinelle (leçon §0bis) ;
distances, `on_objective` et `in_cover` sont recalculés depuis le `game_state` brut ; les bits
`present` sont **exactement** les slots que le masque ouvre, y compris sous troncature forcée à
3 hexes valides ; le bloc est nul hors déploiement et pour une autre escouade ; et la distance hex
vectorisée rend **exactement** `calculate_hex_distance`.

⚠️ **Ce que le point 3 ne fait PAS, et qui reste à arbitrer** (architecture de la policy, pas
contrat d'observation) : les ids `4-8` tombent dans la plage des cellules de move
(`MOVE_CELL_BASE = 0`), donc leurs logits sortent de la **conv 1×1 de la carte**, aux cellules
`(0, 4..8)` de la fenêtre égocentrique — pas d'une tête dédiée. Le bloc candidat atteint cette tête
par le **conditionnement du tronc** (`move_ctx_net`, qui peut réordonner les cellules entre elles),
non par un pointeur. Une **tête pointeur de déploiement**, jumelle de `choice_query_net`, est le
prolongement naturel ; elle exigerait de distinguer « cellule de move » de « slot de déploiement »
sur les mêmes ids, donc de lire la phase dans la policy. ➡️ **Suivi en [§0.44](#s0.44)** (entrée
OUVERTE du tableau d'état) : arbitré le 2026-07-29, **reporté après le run 4**.

**Dette fermée au passage (même fichier).** `engine/observation_builder.py` enveloppait
`get_fighting_models` d'un `except Exception` qui traduisait TOUTE erreur en « aucune figurine ne
peut combattre » — un état de jeu inventé, servi sans trace. Préexistant (`fb7e83b6`, 2026-05-27,
jamais justifié). Vérification faite avant suppression : toutes les levées atteignables sur ce
chemin viennent de `require_key(models_cache/squad_models)`, `get_engagement_zone`,
`_synth_model_entry` et de la primitive EZ — **chacune déjà appelée sans garde** par le code qui
l'entoure, sur les mêmes données. Aucune condition nommée à rattraper : le `try/except` est
supprimé, pas rétréci. Verrous : `test_obs_fighting_models_no_fallback.py` (l'appel ne lève pas sur
une partie réelle, ~400 appels ; et une levée injectée **remonte** au lieu de devenir un zéro).

<a id="s0.39"></a>
### 0.39 Pathfinding exact — correctif juste, aucun appelant, code SUPPRIMÉ — ✅ CLOS (2026-07-28)

**Source de vérité : [`Implémenté/V11_pathfinding_exact.md`](Implémenté/V11_pathfinding_exact.md)**
(archivé : le code qu'il décrit n'existe plus).

**Ce qui est livré (2026-07-27).** `combat_utils.calculate_pathfinding_distance` ne tronque plus :
la profondeur vient de `game_rules.max_search_distance` (déjà en subhex) et le plafond de nœuds
(`max_open_nodes = 2000`) est supprimé. Au-delà de ~5 pouces sur board ×5, TOUTE distance valait
auparavant « injoignable ». Ajout de `hex_utils.pathfinding_field` (champ BFS par source, mémoïsé,
purgé aux 3 morts d'épisode) dont la forme point-à-point est une simple enveloppe. **22 tests** :
`test_pathfinding_distance_exact.py` (11) + `test_hex_utils.py::TestPathfinding` (11), comptés le
2026-07-28.

**Ce qui s'est révélé le 2026-07-28.** Le doc désignait le bot PvE
(`pve_controller._ai_select_movement_destination`) comme consommateur vivant. **Il ne l'était
déjà pas** : aucun appelant dans tout le dépôt, et son `self._get_unit_by_id` n'était assigné
nulle part (un appel aurait levé `TypeError`). Il a été supprimé avec le nettoyage du
`pve_controller`, et les deux autres consommateurs (`observation_builder`, `reward_calculator`)
sont partis avec le pipeline mono-figurine 359-d. **Bilan : la chaîne
`calculate_pathfinding_distance` → `get_pathfinding_field` → `hex_utils.pathfinding_field` est
fermée sur elle-même.** Chaque maillon a un appelant sauf le premier, qui n'en a plus aucun de
production — donc l'ensemble est mort.

⚠️ **Motif §0bis, troisième occurrence** (après T6-i et §0.38) : *du code testé mais jamais
appelé*. Ici la variante est plus coûteuse — le correctif a été mesuré, benché et documenté comme
réparant un comportement du bot, alors que ce comportement n'était pas atteignable. La leçon n'est
pas « ne pas corriger » mais **vérifier qu'un appelant existe AVANT de mesurer un gain** : un
`grep` du nom de la fonction appelante aurait suffi, et la mesure « 3,6 s → 0,062 s » n'a jamais
décrit une exécution réelle.

**Décision de l'utilisateur : SUPPRESSION** — exécutée le 2026-07-28. Retirés :
`calculate_pathfinding_distance`, `get_pathfinding_field`, `PATHFINDING_FIELD_CACHE_MAX`
(`combat_utils`) · `pathfinding_field`, `pathfinding_distance`, `PATHFINDING_UNREACHABLE`
(`hex_utils`) · le cache `_pathfinding_field_cache` et ses 3 purges (`w40k_core`) · ses
déclarations dans `game_snapshots._GS_STATIC_KEYS` et `api_server._GAME_STATE_EXCLUDE_KEYS` ·
les 22 tests (fichier `test_pathfinding_distance_exact.py` supprimé, classe `TestPathfinding`
retirée de `test_hex_utils.py`, 3 cas résiduels dans les 2 fichiers `test_combat_utils_*`).
**252 lignes de moteur.** Vérifié : `pyright` 0 erreur, `check_ai_rules` et
`hidden_action_finder` 0 erreur, fichiers de test touchés verts, smoke moteur nu complet
(126 steps, 6 phases, épisode terminé).

⚠️ **Ne pas confondre avec le pathfinding VIVANT** : le pool de move (`movement_handlers`, BFS
géodésique) est un autre code, jamais concerné par cette suppression.

<a id="s0.38"></a>
### 0.38 Code mort `_attack_sequence_rng` — la 2ᵉ moitié de P1 — ✅ RÉSOLU (2026-07-28)

**Ce qui était en cause.** `_attack_sequence_rng` (`shooting_handlers.py`, **184 lignes**, 193 avec
la bannière `ADVANCE_IMPLEMENTATION` qui ne précédait rien) n'avait **aucun appelant de production**
et n'était tenu en vie que par des tests. Motif §0bis (« du code testé mais jamais appelé »),
quatrième occurrence après §0.4, T6-i et §0.39.

> 🔎 **Chiffres recomptés le 2026-07-29 — l'énoncé de départ était inexact sur deux points.**
> Il annonçait « 6 fichiers, ~159 assertions ». Le compte réel des appels
> (`grep -c '= _attack_sequence_rng('` sur `main`) donne **5 fichiers** :
> `test_special_rules_e2e` (35 appels / 64 assertions), `test_fight_special_rules` (16 / 41),
> `test_shoot_attack_sequence` (7 / 19), `test_unit_rules_shoot` (8 / 12),
> `test_phase_transitions` (1 / 2) — soit **138 assertions** sur le mort.
> `test_closest_target_penetration_shoot.py` était compté comme le 6ᵉ mais avait **0 appel** : il
> était déjà migré depuis le 2026-07-26, seul son docstring citait encore le mort.

**Ce qui a été fait, dans l'ordre.** (1) Les 6 fichiers ont été re-pointés sur le chemin vif,
(2) chaque assertion re-vérifiée, (3) **puis seulement** la fonction supprimée, (4) puis les états
résiduels. Les 4 commits de la branche `v11-0.38-dead-code` suivent cet ordre.

---

#### Le résultat principal : DEUX écarts de conformité, et c'est le MORT qui avait tort

C'est ce que la migration devait faire apparaître, et elle l'a fait. Aucune assertion n'a été
assouplie : ces deux-là ont été **retirées parce que la règle leur donne tort**, PDF en main.

> ℹ️ **Une TROISIÈME différence, sans enjeu de règle** (constatée le 2026-07-29, non vue à la
> première passe) : sur une blessure critique DEVASTATING, le mort ne tirait **pas** de dé de
> sauvegarde (`save_roll = 0`) ; le vif en **tire un et le jette** (`roll_attack_pool` lance la
> sauvegarde inconditionnellement, `_resolve_one_manual_wound` saute ensuite la comparaison). Le
> résultat de jeu est identique — la valeur n'est jamais lue — mais elle **reste dans le record**
> (`saveRoll`), aux côtés de `saveSkipped: true`. Conséquence concrète, cf. « Ce qui reste à
> faire » plus bas : le step.log affiche un jet de sauvegarde sur une blessure mortelle.

**1. [HAZARDOUS] 24.15 + 06.03 — le mort était faux sur quatre points.**
PDF 24.15 (lu le 2026-07-28) : « Each time a unit is selected to shoot **or selected to fight**,
**after that unit has resolved all of its attacks**, make a number of hazard rolls (06.03) for that
unit **equal to the number of [HAZARDOUS] weapons you selected** in the Select Weapons step. »
PDF 06.03 : « on a **1-2**, that roll fails and that unit suffers **1 mortal wound**, or 3 mortal
wounds instead if each model in that unit is a MONSTER/VEHICLE model. »

| | code mort | PDF (= chemin vif) |
|---|---|---|
| Quand | pendant la séquence, **par attaque** | **après** toutes les attaques de l'unité |
| Combien de jets | 1 par attaque | 1 **par arme HAZARDOUS sélectionnée** |
| Seuil d'échec | 1 | **1-2** |
| Conséquence | un booléen `hazardous_triggered`, **aucun dégât appliqué** | **1 blessure mortelle** (3 si toutes les figurines sont MONSTER/VEHICLE) |
| Mêlée | jamais | **oui** (`FIGHT_CTX.hazard_origin="fight"`) |

Le vif est conforme sur les cinq lignes. Les 11 assertions HAZARDOUS du mort (réparties sur
`test_special_rules_e2e.py` et `test_fight_special_rules.py`) portaient donc sur un comportement
**contraire au PDF** : elles n'ont pas été portées. Le volet TIR était déjà verrouillé par
`test_hazardous.py` ; **le volet MÊLÉE ne l'était par rien** — c'est le trou qu'a révélé la
migration, et `test_fight_special_rules.py` (qui malgré son nom ne testait que du tir) a été
réécrit pour le combler : 6 tests, dont « 1 jet par arme, pas par figurine » et « 3 MW si toutes
les figurines sont VEHICLE ».

**2. [HEAVY] 24.16 — le mort ignorait deux clauses sur trois.**
Le mort accordait le +1 dès que l'unité était absente de `units_moved`/`units_advanced`. Le PDF
exige **trois** clauses cumulatives : *unengaged*, *pas posée sur le champ de bataille ce tour*,
*aucune figurine n'a parcouru plus de 3"*. Le vif teste les trois depuis le 2026-07-26
(`_heavy_unit_is_engaged`, `_unit_was_set_up_this_turn`, `moved_distance_by_model` en distance de
chemin géodésique, comparaison **stricte** à 3"). Les assertions du mort ne pouvaient donc pas être
portées telles quelles. La ligne HEAVY de [§9.2.1](V11_phaseA.md#s9.2.1), qui déclarait encore ces
clauses « non implémentables faute de donnée », a été corrigée dans la foulée : la donnée existe.

---

#### Ce que sont devenus les 6 fichiers

| Fichier | Avant | Après |
|---|---|---|
| `test_shoot_attack_sequence.py` | 7 tests sur le mort | **13** — séquence de tir bout-en-bout via `build_manual_shoot_allocation`, jusqu'aux PV retirés : les 4 issues, AP, invulnérable (ignore l'AP), 05.01/05.04 **sur un seuil de 1** (seul cas où la clause porte), et le câblage de **[ANTI-X] au tir** |
| `test_special_rules_e2e.py` | 31 tests, dupliquaient les fichiers vifs | **8** — les **interactions** que nul autre fichier ne voit : DEVASTATING × HAZARDOUS, HEAVY × DEVASTATING, arme nue |
| `test_fight_special_rules.py` | 22 tests de TIR malgré son nom | **6** — [HAZARDOUS] en **MÊLÉE**, volet jamais couvert |
| `test_unit_rules_shoot.py` | 8 tests dupliquant `test_reroll_towound_shoot.py` + CTP | **7** — 01 Core « Re-rolls » : abilité d'unité **+** [TWIN-LINKED] ne relancent jamais deux fois le même dé ; portée des abilités `to wound` (ni touche ni sauvegarde) |
| `test_phase_transitions.py` | 1 test de dégâts sur le mort | son assertion rendue à `test_shoot_attack_sequence.py` ; le fichier ne couvre plus que les transitions |
| `test_closest_target_penetration_shoot.py` | déjà migré (2026-07-26) | + le cas « pool d'éligibles vide » |

Trous comblés au passage sur les fichiers vifs existants : plancher 2 et `bs_base` de HEAVY
(`test_heavy_shoot.py`), blessure non critique et valeur des dégâts de DEVASTATING
(`test_devastating_wounds_shoot.py`).

---

#### Preuves

- **110 tests verts** sur les 12 fichiers concernés (5 migrés + 1 déjà migré + 6 vifs complétés),
  plus les 22 autres fichiers qui importent `shooting_handlers` — verts également.
- **Contre-épreuve par mutation, DEUX salves : 13 clauses du vif cassées une à une, 13/13 rouges**,
  baseline et restauration vertes à chaque fois.

  | # | Mutation du vif | Résultat |
  |---|---|---|
  | M1 | 05.02 — la blessure critique n'est plus critique | 🔴 |
  | M2 | 24.16 — le bonus HEAVY n'est plus appliqué | 🔴 |
  | M3 | 24.38 — [TWIN-LINKED] ne relance plus | 🔴 |
  | M4 | 24.15 — la mêlée ne déclenche plus de jet de hasard | 🔴 |
  | M5 | 05.04 — l'AP n'aggrave plus la sauvegarde | 🔴 |
  | M6 | `closest_target_penetration` n'améliore plus l'AP | 🔴 |
  | M7 | 24.10 — DEVASTATING ne saute plus la sauvegarde | 🔴 |
  | M8 | 05.04 — l'invulnérable cesse d'ignorer l'AP | 🔴 |
  | M9 | 05.01 — un 1 non modifié ne rate plus la touche | 🔴 |
  | M10 | 05.04 — une sauvegarde de 1 ne rate plus toujours | 🔴 |
  | M11 | 05.02 — le 6 ne blesse plus sous le seuil | 🔴 |
  | M12 | le nom de l'arme disparaît du log de tir | 🔴 |
  | M13 | 01 Core — un dé se relance DEUX fois | 🔴 |

  🔎 **La 2ᵉ salve (M8-M13) a d'abord donné TROIS VERTS**, c'est-à-dire trois tests que je venais
  d'écrire et qui **décrivaient la fixture, pas le code** — exactement le piège §0bis « un test qui
  passe du premier coup n'est pas encore un verrou ». Diagnostic et correction :

  | Test initial | Pourquoi il ne mordait pas | Remplacé par |
  |---|---|---|
  | « un 1 rate toujours la touche », BS 2+ | sur un seuil ≥ 2, le 1 échoue **par comparaison** ; la clause « 1 non modifié » ne porte rien | même test sur **BS 1+** — profil réel, deux armes des armories déclarent `ATK: 1` |
  | « une sauvegarde de 1 échoue toujours », Sv 2+ | idem : seuil ≥ 2, le 1 échoue par comparaison | même test avec **AP +1 sur Sv 2+ → seuil 1** (cf. l'anomalie de donnée ci-dessous) |
  | « un 6 non modifié blesse toujours », S1 vs T10 | `wound_threshold` **plafonne à 6** : le 6 passe déjà par la voie normale, la clause critique est inerte | **[ANTI-INFANTRY 5+] au tir** : un 5 blesse sous un seuil de 6+ — seul cas où 05.02 est observable à travers le câblage de tir |

  Le remplacement du troisième a comblé un trou de couverture réel : **le câblage de [ANTI-X] 24.03
  côté TIR n'était testé nulle part** (le socle l'est par `test_weapon_rules_attack_sequence.py`, la
  mêlée par `test_weapon_rules_fight.py`).

- ⚠️ **Anomalie de donnée relevée, NON corrigée** : `bone_cleaver` (`frontend/src/roster/tyranid/armory.ts`)
  déclare `AP: 1`, **seule valeur d'AP strictement positive** des 5 armories (toutes les autres sont
  entre 0 et -5). Avec la convention du moteur (`save_threshold` : `armure - ap`), un AP positif
  **améliore** la sauvegarde de la cible — un effet qui n'existe pas en 40K, donc très probablement
  un signe manquant. Non corrigé ici : arbitrer une caractéristique de datasheet demande une source
  que les PDF du projet ne contiennent pas (ils portent les règles de base, pas les datasheets).
  C'est une décision utilisateur. Effet de bord utile : ce profil rend le garde « une sauvegarde de
  1 échoue toujours » **atteignable**, donc testable (M10).

- `grep -rn '_attack_sequence_rng' engine/ ai/ services/ tests/` → **vide** (les mentions
  historiques dans les docstrings ont été reformulées pour ne plus citer un symbole inexistant).
- `pyright engine/phase_handlers/shooting_handlers.py` → 0 erreur.

---

#### États résiduels : ce qui est traité, ce qui ne l'est pas

**Traité** (`shooting_handlers.py`) : les 7 champs `_rapid_fire_*` d'activation
(`_rapid_fire_context_weapon_index`, `_base_nb`, `_shots_fired`, `_bonus_total`, `_rule_value`,
`_bonus_shot_current`, `_bonus_applied_by_weapon`) — initialisés puis purgés sans qu'aucun code ne
les écrive jamais autrement qu'à 0/False — et le helper `_get_rapid_fire_parameter` (zéro appelant).
[RAPID FIRE] 24.30 reste **vif** via `weapon_rule_parameter` dans `_manual_roll_intent` : seul le
nom se ressemblait. **Effet de bord mesuré** : dans `_unit_has_shot_with_any_weapon`, la branche
`_rapid_fire_shots_fired > 0` était morte et masquait le seul critère réel (arme épuisée).

**NON traité, et pourquoi.** Les 7 clés `_rapid_fire_*` de `w40k_core.py` (~L1195-1201 liste de
purge, ~L2127-2133 log de debug) et le champ de log `rapid_fire_bonus_shot` (~L3769/L3966, alimenté
par un `attack_result.get()` que plus rien ne produit). **Blocage réel, pas un arbitrage de
confort** : `w40k_core.py` était en cours d'édition par l'agent §0.40 pendant cette session.
Reste **1 grep + 3 suppressions triviales** dès que §0.40 est mergée.

**Conservé délibérément.** Les **5** branches `raise RuntimeError` de
`shooting_handlers.execute_action` : `activate_unit`, `shoot`, `select_weapon`, `left_click`,
`invalid`. §9.2 les listait comme résidus ; vérification faite, le dispatcher **est sur un chemin
vif** ([w40k_core.py:6157](../../engine/w40k_core.py#L6157) — toute action de tir non `squad_*` y
passe). Ces `raise` sont des gardes explicites : les retirer ferait retomber ces cinq types sur le
`else` final et transformerait une erreur bruyante en `{"error": "invalid_action_for_phase"}`
silencieux — exactement le contraire de la règle « erreur explicite, jamais de fallback ».

> 🔎 **Recomptées le 2026-07-29 : elles sont 5, pas 4.** La première rédaction en annonçait 4,
> parce que `grep 'squad path expected'` n'en trouve que 4 : la 5ᵉ (`select_weapon`,
> [shooting_handlers.py:5742](../../engine/phase_handlers/shooting_handlers.py#L5742)) porte le
> message « squad_select_weapon expected ». **Compter des gardes par leur message est un
> recensement faux** — c'est la variante « côté texte » du piège « ne juge pas un état mort à la
> ressemblance de son nom ». Le recensement juste passe par `grep -c 'raise RuntimeError'` dans la
> fonction, ou par l'AST.

**La chaîne d'affichage des règles d'armes — constatée rompue le 2026-07-29, RÉPARÉE le même jour.**

La première rédaction de cette entrée disait que le seul reliquat consommateur était `w40k_core`
lisant 3 clés d'affichage. **C'était très en dessous de la réalité.** Le formateur de tir du
StepLogger (`ai/step_logger.py`, branche `action_type == "shoot"`) est écrit pour le contrat du
MORT et il est, lui, sur un **chemin vif** : c'est lui qui écrit les lignes `SHOT` de `step.log`,
seule matière de `ai/analyzer.py` — que CLAUDE.md désigne comme la stratégie de validation du
training — et du replay (`replayParser.ts` lit exactement les mêmes tokens).

L'information traverse **quatre maillons** : `record moteur → _SHOT_RECORD_FIELD_MAP → ligne
step.log → regex analyzer`. Chacun avait ses tests ; **aucun ne traversait la jonction**. C'est la
cause structurelle : trois règles y sont mortes en silence, et la quatrième ajoutée demain serait
morte pareil.

| Règle | Ce qui manquait | Effet mesuré AVANT |
|---|---|---|
| [DEVASTATING WOUNDS] 24.10 | `saveSkipReason` jamais posé | la ligne affichait `Save 6(2+)` sur une blessure MORTELLE — ce que le contrôle de l'analyzer classe lui-même en `devastating_wounds_incorrect` ; et il ne le voyait pas, faute de token |
| [HEAVY] 24.16 | `bs`/`bs_base`/`heavy_applied` n'existaient que noyés dans la chaîne `message` | compteur d'usage à **0 pour toujours** → verdict « NOT USED » permanent |
| [RAPID FIRE] 24.30 | valeur appliquée jamais propagée | plafond de tirs resté à NB de base → **faux `shoot_over_rng_nb` sur toute activation RAPID FIRE** |

**Ce qui a été livré** (3 commits, après le merge de §0.40 qui a libéré `w40k_core.py`) :

1. **Un test de chaîne écrit EN PREMIER, rouge** — `tests/unit/ai/test_step_log_weapon_rule_tokens.py`.
   Il traverse les 4 maillons avec du code de production à chacun : record du vrai moteur
   (`build_manual_shoot_allocation`, dés scriptés) → vraies `_build_shot_details` /
   `_SHOT_RECORD_FIELD_MAP` → vrai `StepLogger.log_action` → vrai `ai.analyzer.parse_step_log`.
   Il utilise une arme **réelle** portant les trois règles (`sternguard_bolt_rifle` : HEAVY +
   DEVASTATING WOUNDS + RAPID FIRE:1), ce qui exerce pour de vrai les recoupements de l'analyzer
   avec l'armurerie — une arme inventée en sortirait silencieusement.
2. **Le correctif de conformité 24.10** : « no saving throw can be **made** » — le dé de
   sauvegarde n'est plus tiré du tout sur une blessure critique DEVASTATING (ni relancé, ni posé
   au record). C'était la 3ᵉ différence mort/vif ci-dessus ; sur ce point précis, **c'est le code
   mort qui était conforme**. Effet de bord gratuit : `GameLog.tsx` affichait `Svg: ✗ (6)` sur une
   blessure mortelle, il garde sur `saveRoll !== undefined` → corrigé aussi.
3. **Les tokens atteignent la ligne** : `saveSkipReason`, `bs`/`bsBase`/`heavyApplied`,
   `rapidFireApplied` publiés puis transmis.

**DEUX contrôles d'analyzer supprimés, pour la même raison que la LoS ancre-à-ancre et le
« fight from non-adjacent »** — ils re-dérivaient depuis `step.log` une décision que le moteur
prend et que le log ne porte pas :

- **Validité de [HEAVY]** : testait `shooter in units_moved/units_advanced`, la borne
  conservatrice du moteur d'**avant** le 2026-07-26. Le PDF accorde le bonus tant qu'aucune
  figurine n'a parcouru **plus de 3"**. Prouvé : sur l'ancien code, un tir après un déplacement de
  **2"** — parfaitement légal — était compté invalide. Non réparable depuis le log (distance de
  **chemin géodésique par figurine** contre des ancres départ/arrivée). Avec lui disparaissent
  `weapon_rule_invalid_usage` et `weapon_rule_invalid_first_lines`, désormais sans aucun écrivain.
- **« Ce tir est-il LE tir bonus ? » de [RAPID FIRE]** : exigeait le marqueur uniquement sur les
  tirs d'index > NB, distinction héritée du moteur mort qui résolvait les tirs un par un. 24.30
  augmente le **nombre d'attaques** ; aucune n'est « la » bonus. Ce qui reste est le vrai
  invariant — le **plafond de tirs** (`shoot_over_rng_nb`), que le marqueur de groupe rend enfin
  vérifiable.

**Contre-épreuve** : 7 mutations, une par maillon et par règle (moteur ne pose plus / pont ne
transmet plus, pour chacune des 3 règles, + retour au dé tiré-puis-jeté) → **7/7 rouges**,
restauration verte.

**Deux volets d'abord écartés à tort, puis livrés le 2026-07-29.** Je les avais exclus en
affirmant que « aucun contrôle d'analyzer ne les attend ». **Vérification faite, c'était faux
pour le premier** — et la justification du second était mal chiffrée.

- **Nom d'abilité de relance.** [shoot_handler.py:148](../../ai/analyzer_phases/shoot_handler.py#L148)
  compte `special_rule_usage[("reroll_1_towound", type)]` sur un token de nom d'abilité. Il
  n'était jamais émis → les deux règles de relance affichaient **0 utilisation en permanence**
  pour les unités qui les déclarent, alors que le vif les applique. Réparé : le socle trace
  désormais la **cause** de chaque relance (`wound_1` / `wound_any_fail` / `twin_linked`),
  `_manual_roll_intent` la nomme via la règle SOURCE (résolution **paresseuse** : on ne lit le
  `displayName` que si une relance a réellement eu lieu), le pont la transmet. La regex de
  l'analyzer cherchait `(TARGETED_INTERCESSION)` — parenthèses et underscore, une forme que le
  formateur n'a jamais produite ; elle suit maintenant la convention du projet, `[NOM]` entre
  crochets, celle à laquelle le frontend accroche ses tooltips.
- **[COVER] 13.08.** Chiffré avant de décider : **ça ne cassait rien** — aucun log existant ne
  contient le token, l'analyzer n'a ni contrôle de couvert ni regex `Hit`, et le `->` dans la
  partie Hit existait déjà depuis le correctif [HEAVY]. Le token est désormais rendu **du côté
  de la touche**, là où ce moteur applique la règle (`_cover_worsened_bs` dégrade le seuil de
  touche), avec le tooltip déjà enregistré dans `GameLog.tsx`. L'ancienne branche « couvert sur
  la sauvegarde » (`save_cover_applied` / `save_target_base`) est supprimée des **deux**
  formateurs — en mêlée elle était morte deux fois, la règle y étant inapplicable (ranged-only).

**Dette de miroir soldée côté frontend** : `replayParser.ts` parsait `save_cover_applied`,
`save_target_base`, `heavy_applied`, `rapid_fire_bonus_shot` et `rapid_fire_rule_value` —
**cinq champs sans aucun consommateur** dans tout `frontend/src`. C'était l'exacte image de ce
que §0.38 a supprimé côté backend. Retirés ; l'information passe de toute façon par
`log_message`, que `GameLog` affiche tel quel avec ses tooltips. `tsc` et `biome` verts.

**Contre-épreuve finale : 12 mutations de chaîne, 12 rouges** (moteur / pont, pour chacune des
cinq règles, plus le retour au dé tiré-puis-jeté).

### 0.37 Contre-audit des livraisons §0.32–§0.35 — ✅ LIVRÉ (2026-07-28)

**Origine.** L'utilisateur a demandé de vérifier « dans les détails » si le travail de la session
§0.32–§0.35 était **optimal**, sur le seul code. 5 audits parallèles (obs vecteur, grille, tête
1×1, frontière move, VecNormalize/config), chacun sommé de reproduire les affirmations dans le
code ET de chercher les défauts restants.

**Verdict global : le fond est confirmé partout.** Aucune affirmation infirmée, aucun bug
introduit. T-G est le chantier le plus propre : nécessité des deux couches 1×1 + ReLU vérifiée
**numériquement** sur le modèle réel (sans ReLU, le latent est constant à 7e-7 près sur les
1024 logits), alignement des 1062 logits confronté bout à bout au masque et au décodeur,
+16 001 paramètres décomposés à l'unité. Seul invérifiable : le ×1,78 du forward (benchmark
hors code). Mais « livré » n'était pas « optimal » : 6 résidus réels, tous fermés le jour même.

1. **Érosion : la « source unique » de §0.34 ne l'était que pour 3 consommateurs sur 4.**
   `erode_move_pool_by_squad_block` re-dupliquait `max(0, M − descente)` en ligne
   (`shared_utils.py`) au lieu de lire `squad_normal_move_frontier_subhex` : identique
   aujourd'hui, divergence silencieuse à la prochaine évolution de la pénalité. → l'érosion lit
   la fonction ; verrou de CÂBLAGE par espion (`test_erosion_reads_the_single_frontier_source` :
   ré-inliner la formule rougit).

2. **Charge depuis un étage — les deux facettes de §0.34, encore ouvertes sur la charge.**
   Une charge est un move (11.04 EFFECT « moves as described in Moving (03) », PDF lu) :
   la distance verticale descendue s'ajoute au jet (13.06). Or `charge_build_valid_plan`
   mesurait au jet BRUT et émettait des **3-uplets sans niveau** — « pas de niveau » =
   `commit_move` garde le niveau courant → fig descendue restée marquée à l'étage sur une case
   de sol → `floor_height_at` lève à la mise à jour du cache (le crash exact de §0.34,
   facette 2). → budget `max(0, jet×ish − squad_descent_penalty_subhex)` (même déduction
   conservatrice que le move rigide) + plan en **4-uplets** avec
   `SQUAD_RIGID_MOVE_DESTINATION_LEVEL`. 4 tests (`test_squad_charge_descent_level.py`) : le
   jet qui suffit au sol ne suffit plus depuis l'étage, contre-épreuves sol et gros jet.
   ✅ **Pile-in/consolidation VÉRIFIÉS conformes, rien à faire** : plans par-figurine en
   4-uplets (`commit_pile_in_plan`, fight_handlers), champ multi-niveaux avec coût de
   descente facturé (`_fight_model_climb_reachable_floor_cells`) — le soupçon de l'audit ne
   tenait pas.

3. **VecNormalize : « absence = erreur explicite » n'était vrai que sur le chemin critique.**
   Fermés : `normalize_observation_for_inference` retournait l'obs **brute** si pkl absent
   (chemin Box) → `FileNotFoundError` ; la reprise `--step` sans stats **recréait des stats
   neuves en silence** (décalage de distribution muet) → erreur explicite, avec mention du pkl
   LEGACY partagé s'il traîne ; le PvE jouait brut sous **double `except Exception`** →
   résolution **au chargement** du modèle (`_resolve_vec_stats_path` : per-model = normalise,
   LEGACY seul = erreur, aucun = brut ET annoncé) ; l'écriture du snapshot d'éval async et du
   best_model avalait TOUTE exception (`except: pass`) — le silence exact qui a coûté 5 h 30 à
   §0.35 → propagation ; le pkl du modèle `_interrupted` est nettoyé avec son zip ; la fenêtre
   de fuite tempfile (mkstemp → try 200 lignes plus bas) est fermée (le `try` commence dès la
   préparation).

4. **Le canal `vec_model_path` séparé a été SUPPRIMÉ, pas seulement corrigé.** Les workers
   d'éval dérivent les stats du **zip qu'ils chargent** (`_eval_worker_init` →
   `get_vec_normalize_path(model_path)`) : évaluer un modèle avec la normalisation d'un autre
   est devenu **irreprésentable** — la 2e moitié de §0.35 ne peut plus régresser. Le verrou
   textuel (`inspect.getsource` cherchant `vec_model_path = effective_model_path`, cassable par
   renommage) est remplacé par un test comportemental (signature sans `vec_model_path` + le
   normalizer lit le pkl dérivé du zip + erreur nommant le fichier attendu).
   `_build_eval_obs_normalizer` (code mort maintenu vivant par ses tests) est supprimé.
   `test_eval_explicit_scenario.py` **skip** désormais sur pkl absent (précondition
   d'environnement, comme le zip), au lieu d'échouer.

5. **3 replis de la famille fermée par T-J survivaient dans `observation_builder.py`** :
   `game_state.get("phase", "")` du canal grille (phase absente = canal vide silencieux),
   `active_sq.get("centroid_col", ancre)` — qui alimente **l'origine T-I** de toute
   l'observation — et `entry.get("HP_CUR", 0)` (« escouade à 0 PV » sur un cache incomplet).
   → `require_key` partout, 3 tests de levée (mêmes oracles que les fermetures T-J).

6. **Canal T-K : sémantique du seuil fausse pour une escouade ENGAGÉE.** Tous ses coûts sont
   ≤ M → canal ≤ 0,5 = « je garde mon tir », alors que tout mouvement est un **Fall Back**
   (09.05) qui coûte le tir et la charge — le CNN aurait dû croiser avec le canal EZ,
   exactement le croisement que T-K existe pour éviter. → `normalize_move_costs(engaged=...)`
   (paramètre **obligatoire**, prédicat du masque `_squad_is_in_enemy_er` passé par l'obs) :
   engagée, toute cellule peinte est **au-dessus de 0,5**. Sémantique uniforme : sous le seuil
   = bouger est gratuit, au-dessus = bouger coûte le tir. Verrou de câblage par monkeypatch du
   prédicat + tests unitaires (origine à 0, monotonie, < 1, contre-épreuve non engagée).
   `AI_OBSERVATION.md` mis à jour.

**Aussi actés** : `bot_eval_freq` x1 confirmé à 4000 (l'utilisateur avait remis 2000 à la main,
revenu à 4000 après explication du garde-fou `save_best_min_episodes`).
> ⚠️ **MAJ 2026-07-28 soir — décision INVERSÉE** : l'utilisateur assume finalement **2000** (granularité
> des courbes de métriques), en connaissance du garde-fou. Cf. l'encadré 🟢 en §0.

7. **Convention du bit `present` UNIFIÉE (demande utilisateur, même jour).** Le registre des
   unités le portait en PREMIER quand self/armes/types le portent en DERNIER — bénin (index lus
   du schéma) mais deux conventions dans le même schéma, et 3 lecteurs positionnels `[..., 0]`
   en dur dans l'extracteur. → `present` est désormais le **DERNIER champ de CHAQUE registre**
   (`UNIT_BIN_FIELDS`, index `[s][31]`), l'extracteur lit `unit_bin_index("present")` (plus
   aucun index recopié), doc renumérotée, fixtures basculées sur l'index du schéma. ⚠️ C'est un
   **changement de layout d'observation à `obs_size` CONSTANT** : un modèle antérieur se
   chargerait sans erreur et jouerait faux. Fait dans la fenêtre où `ai/models/ArmageddonAgent/`
   est **vide** (vérifié, aucun training en cours) — le run §0.14 devait déjà être un `--new`.

**Tests** : ~30 ajoutés/remaniés (frontière 11, grille+spatial 65 dont 2 verrous neufs, charge
descente 4, PvE VecNormalize 6, train helpers 2, vec/bot-eval 29+1 skip). Toutes les familles
touchées vertes ; la vérification LARGE appartient à l'utilisateur.


### 0.36 `--new` héritait du seuil de score du run précédent — ✅ CORRIGÉ (2026-07-28)

**Origine.** Constaté en vérifiant le run relancé : `ai/models/ArmageddonAgent/model_ArmageddonAgent_robust_meta.json`
contenait encore `{"robust_score": 0.457372}` — le score du run **mort au marqueur 24 000**
(§0.35). Le `--new` ne l'avait pas purgé.

**Deux dégâts distincts, tous deux silencieux.**

1. **Le meta est un SEUIL, pas une trace.**
   [`training_callbacks.py:2262`](../../ai/training_callbacks.py#L2262) :
   `if current_canonical_score is not None and current_canonical_score >= robust_score: pass` —
   le modèle canonique n'est mis à jour que si le nouveau score **dépasse** celui du fichier. Un
   run neuf devait donc battre le score d'un run précédent, mesuré sur un **autre** modèle, et
   ici sur un run avorté dont §0.35 dit que la normalisation est douteuse.
2. **`model_<agent>.zip` et `best_model.zip` étaient ÉCRASÉS** par le run neuf. Le modèle
   canonique est le seul artefact servi au PvE : l'agent précédent disparaissait sans trace.

**Correctif (proposition utilisateur).** À `--new`, les artefacts à **nom fixe** sont
**renommés** `<stem>_<AAAAMMJJ-HHMM><ext>`, jamais supprimés :
`model_<agent>.zip`, `model_<agent>_vec_normalize.pkl`, `model_<agent>_robust_meta.json`,
`best_model.zip`. Le run neuf démarre donc **sans référence** — il ne peut ni hériter d'un seuil,
ni écraser l'agent précédent.

⚠️ **Ce qui n'est PAS archivé, et c'est délibéré** : les modèles nommés avec leur score
(`<agent>_<seed>_robust_<score>.zip`, produits par `_build_robust_model_zip_path`) et les
`ppo_checkpoint_*`. Leur nom est **unique**, rien ne les écrase : ils sont l'historique et
restent en place. Archiver ce qui ne risque rien n'aurait fait que noyer le dossier.

⚠️ **Exception assumée à une règle du projet** : cette fonction **renomme** des `.zip` de
`ai/models/`, ce que `CLAUDE.md` interdit par défaut. C'est une demande explicite de
l'utilisateur (2026-07-28), et elle ne supprime rien — elle empêche précisément l'écrasement
silencieux que la règle protège. Deux `--new` dans la même minute **lèvent** (`FileExistsError`)
au lieu d'écraser une sauvegarde.

**Tests** : 5 dans `test_new_run_archives_previous_artifacts.py` — inventaire des artefacts à nom
fixe, archivage du seuil ET de l'agent, **non-archivage** des modèles scorés et des checkpoints,
idempotence sur un dossier vierge, refus d'écraser une archive existante. 46 verts sur la famille
train/éval/normalisation.

📌 **Non traité, et volontairement** : le run EN COURS au moment du correctif garde le seuil
hérité `0.457372` — son processus a chargé l'ancien code. Il devra battre ce score pour mettre à
jour le modèle canonique ; ses propres `<agent>_<seed>_robust_<score>.zip` et son `best_model.zip`
sont écrits normalement. Décision utilisateur en attente : purger le meta à chaud ou laisser.


### 0.35 Stats VecNormalize partagées par dossier — un run de 5 h 30 tué à 24 000/30 000 — ✅ CORRIGÉ (2026-07-28)

**Symptôme.** Run `x1` lancé après §0.32/§0.34. **24 000 épisodes sur 30 000 en 5 h 30, sans une
seule exception moteur** — puis arrêt net :

```
RuntimeError: VecNormalize enabled but stats not found for Dict obs:
  /home/greg/40k/ai/models/ArmageddonAgent/vec_normalize.pkl
RuntimeError: Bot evaluation crashed episodes detected: marker=24000,
  error_episodes=600, timeout_episodes=0, duration_seconds=7.0
```

**Ce n'est PAS §0.27** (là c'était un *timeout*, ici 600 épisodes en **erreur** en **7 s**), et ce
n'est pas le moteur : les évaluations des marqueurs 4000 → 20 000 avaient réussi, et celle de
20 000 avait **sauvegardé un meilleur modèle** (`ArmageddonAgent_12345_robust_0.4574.zip`).

**Root cause — un nom de fichier UNIQUE par dossier, pas par modèle.**
`get_vec_normalize_path()` ignorait le nom du modèle et renvoyait toujours
`<dir>/vec_normalize.pkl`. Or `BotEvaluationCallback` évalue en **asynchrone** :

1. `_launch_async_eval` sauve un snapshot **et ses stats** — donc écrit `<dir>/vec_normalize.pkl` ;
2. les workers chargent ce pkl **PARESSEUSEMENT**, au premier pas de leur premier épisode ;
3. pendant ce temps, la consommation du résultat de l'évaluation **PRÉCÉDENTE** appelle
   `remove_model_with_companions` (rotation du meilleur modèle robuste, nettoyage legacy, nettoyage du
   snapshot) — qui supprime `<dir>/vec_normalize.pkl`, **le fichier des autres**.

Tant qu'aucune rotation ne tombait entre l'écriture et la lecture, ça passait. Au marqueur 24 000,
la rotation déclenchée par le nouveau meilleur modèle de 20 000 est passée entre les deux :
600/600 épisodes ont échoué **en 7 s**, et le garde-fou strict a arrêté le run.

**Correctif : un chemin PAR MODÈLE** — `<dir>/<nom_du_zip>_vec_normalize.pkl`. Retirer les
artefacts d'un modèle ne peut plus détruire les stats d'un autre : c'est correct **par
construction**, pas par ordonnancement. **Aucun repli sur l'ancien nom partagé** — servir les
stats d'un autre modèle est précisément le bug qu'on ferme.

⚠️ **Ce que ce bug laisse comme doute, à ne PAS présenter comme un résultat.** Le
`robust=0.4574` du modèle sauvegardé à 20 000 a été mesuré avec le pkl trouvé à ce moment-là dans
le dossier. Rien ne prouve que ces stats étaient celles de CE modèle plutôt qu'un résidu d'un run
antérieur : `norm_obs_keys = ["global_cont"]` et `global_cont` fait 11 dimensions **avant comme
après** §0.31/§0.32, donc un pkl périmé se charge sans lever et normalise avec les mauvaises
moyennes. **Ce score est donc à re-mesurer, pas à citer.**

⚠️ **LE PREMIER CORRECTIF ÉTAIT INCOMPLET — et il aurait tué le run relancé au marqueur 4000.**
Renommer le fichier ne suffisait pas : il y avait **deux** moitiés au bug, et la seconde est la
plus grave.

`evaluate_against_bots` construisait `vec_model_path` **en dur** :
`<models_root>/<agent>/model_<agent>.zip` — alors que les workers CHARGENT `effective_model_path`,
qui est un **snapshot temporaire dans `/tmp`** en mode async
(`_submit_async_eval` → `tempfile.mkstemp`). Le modèle évalué et le modèle dont on lisait les
statistiques de normalisation étaient donc **deux modèles différents**. Ça n'a jamais levé tant
qu'un pkl traînait dans le dossier des modèles — et quand la rotation l'a supprimé, le run est
mort. Avec le seul renommage, plus rien n'écrivait
`<dir>/model_<agent>_vec_normalize.pkl` avant le premier *meilleur* modèle (marqueur ≥ 10 000,
`save_best_min_episodes`) : **l'éval du marqueur 4000 aurait levé de la même façon.**

**Correctif complet** : `vec_model_path = effective_model_path`, plus l'écriture des stats à côté
du snapshot dans le chemin non-async (`model.save()` seul ne les écrivait pas — et son absence
lève désormais au lieu de retomber sur les stats d'un autre modèle). Le nettoyage du snapshot
temporaire supprime aussi son pkl.

📌 **Leçon de méthode (§0bis).** Renommer un fichier partagé traite le *symptôme* du partage. La
question à poser était : « **qui écrit ce fichier, et qui le lit ?** » — les deux réponses
désignaient des modèles différents. Le premier correctif a été écrit sans avoir suivi le chemin
d'écriture jusqu'à `tempfile.mkstemp`.

**Tests** : 4 dans `test_vec_normalize_utils.py` — trois chemins distincts pour snapshot/canonique/
meilleur robuste, refus d'un `model_path` vide (il donnerait `_vec_normalize.pkl`, partagé de
nouveau), et le verrou sur la source de `vec_model_path` dans `evaluate_against_bots`. 11 verts
sur le fichier, 50 sur la famille éval/normalisation.

📌 **Effet de bord connu, non masqué** : `tests/unit/ai/test_eval_explicit_scenario.py` échoue
tant qu'aucun run n'a produit de stats dans `ai/models/ArmageddonAgent/` — il en exige un vrai
sur disque. **Vérifié : il échouait DÉJÀ avant ce correctif** (le crash avait supprimé le pkl
partagé), avec l'ancien chemin dans le message. Ce n'est pas une régression du correctif ; il
redeviendra vert dès qu'un run aura tourné.


### 0.34 `incohérence masque/exécution` sur les escouades qui DESCENDENT d'un étage — ✅ CORRIGÉ (2026-07-28)

**Origine.** La note « Trouvé en passant, HORS périmètre » de §0.32 : `execute_squad_move a échoué :
squad=1008 type=normal … figurine 1008#0 hors budget : trajet légal contournant murs/figs >
budget`, **43 occurrences sur 650 pas** d'actions aléatoires légales, plus deux erreurs voisines
(`_euclidean_path_distance … injoignable`, `floor_height_at: no floor at level 1`). Rien ne les
attrape dans `step()` : l'exception sort de `env.step`, le worker `SubprocVecEnv` meurt.

**Repro (AVANT tout fix, condition n°1 de la méthode).** Le chiffre de §0.32 vient du harnais de
mesure de T-K/T-L, pas du scénario d'entraînement : `config/board/44x60x5/scenario/scenario_pvp_test.json`,
**seed 42**, actions légales aléatoires, reset après chaque exception. Reproduit **à l'identique :
43 occurrences / 650 pas** (`execute_squad_move` 23, `floor_height_at` 16, `_euclidean_path_distance` 4).
⚠️ **Le scénario d'entraînement, lui, n'a produit AUCUNE occurrence** (650 pas en `--resolution 1`,
seed 12345, avant tout fix) : ce bug ne bloquait pas le run §0.14 par lui-même. L'affirmation
« le training ne peut pas tourner » est donc **fausse**, et elle a été énoncée avant de vérifier
sur quel scénario le 43/650 avait été mesuré (leçon §0bis).

⚠️ **Mais la raison de cette immunité n'est PAS « le terrain d'entraînement n'a pas d'étage » —
il en a.** `terrain-mc1.json`, le terrain du scénario d'entraînement, porte **5 zones avec un
étage `level: 1` à 3″**. L'immunité est **structurelle**, et il faut la connaître comme telle :

- la **mise en place** du gym construit une formation **au sol** — `deployment_preview_plan` a
  `level: int = 0` par défaut et le plan est un 4-uplet `(mid, col, row, level=0)`
  ([`deployment_handlers.py:889`](../../engine/phase_handlers/deployment_handlers.py#L889)) ;
- le **squad move** rigide atterrit toujours au sol :
  `SQUAD_RIGID_MOVE_DESTINATION_LEVEL = 0`
  ([`shared_utils.py:3699`](../../engine/phase_handlers/shared_utils.py#L3699)).

Aucune escouade du gym ne peut donc **atteindre** un étage : elle n'y est que si un scénario l'y
**pose** (`level: 1` dans les positions fixes), ce que fait `scenario_pvp_test`. C'est vrai quel
que soit le nombre d'étages du terrain.

📌 **Corollaire à ne pas perdre.** Le jour où le gym gagne des destinations d'étage — la
**Phase B « Observation niveaux »** de ce document, et `_multilevel_floor_destinations` qui existe
déjà — cette immunité **disparaît sans que rien ne le signale**, et toute la classe §0.34 redevient
atteignable en training. Les 10 tests de `test_squad_move_descent_frontier.py` sont ce qui
l'empêchera : ils ne dépendent pas du scénario, ils posent l'escouade à l'étage eux-mêmes.

**Root cause — UNE grandeur mesurée différemment de chaque côté, à trois endroits.**
Le squad move rigide du gym atterrit **toujours au sol** (le pool `read_only` retourne avant son
bloc multi-niveaux), et le coût vertical §13.06 est facturé en retranchant `squad_descent_penalty_subhex`
du budget. Trois consommateurs l'ignoraient :

| # | Divergence | Site | Occurrences |
|---|---|---|---|
| 1 | **Frontière normal/advance** : `classify_squad_move_type` reçoit `get_squad_move_budget(…, "normal")` = `M` **brut**, alors que le pool a construit ses destinations à `M − descente` et que `resolve_squad_move_constraints` valide à `M − descente`. Les coûts de la bande `(M − d, M]` sont classés `normal` puis **rejetés** à l'exécution. | [`shared_utils.py:8906`](../../engine/phase_handlers/shared_utils.py#L8906) (décodeur), `:9421` (masque), [`observation_builder.py:2560`](../../engine/observation_builder.py#L2560) (canal T-K), `:9221` (érosion) | 23 |
| 2 | **Niveau d'arrivée** : `build_rigid_plan` n'émettait pas de 4ᵉ élément, et « pas de niveau » signifie pour `commit_move` « **garder** le niveau courant ». La figurine descendue restait marquée `level=1` sur une case de sol → `floor_height_at` lève ; et sa destination était testée contre l'occupation d'un **autre étage** que celui où elle atterrit. | [`shared_utils.py:3691`](../../engine/phase_handlers/shared_utils.py#L3691) | 16 |
| 3 | **Mesure FLY sous métrique hex** : la validation borne la distance **CUBE** (`calculate_hex_distance`), la comptabilisation mesurait un champ **EUCLIDIEN** avec une borne convertie par `× 1,5`. Or un pas d'hexagone vaut `1,5` vers l'est mais `sqrt(3) ≈ 1,732` vers le sud : un plan validé ressortait « injoignable » de sa propre mesure. | [`shared_utils.py:3937`](../../engine/phase_handlers/shared_utils.py#L3937) | 4 |

**Mesure qui NOMME la ligne** (probe in-engine, aucune reconstruction offline — leçon §0bis) :
```
squad 1008 : M_normal=30  descente=15  advance_roll=1
budget de POOL avant descente = 35 ; move_range réel du pool = 20
COÛT géodésique de la cellule choisie = 19.0
frontière utilisée par classify = M_normal = 30  -> type déduit = normal
budget que l'EXÉCUTION applique (normal) = M - descente = 15      => 19 > 15, rejet
```

**⚠️ La piste de §0.32 était le SYMPTÔME, pas la cause.** « `erode_move_pool_by_squad_block`
court-circuite le mono-figurine » est exact, mais ce n'est pas la root cause : l'érosion
**rattrapait** la bande morte pour les escouades multi-figurines — en **supprimant du masque des
Advances parfaitement légaux**, silencieusement. Le mono-figurine n'avait pas ce filet, donc il
crashait. Corriger l'érosion seule aurait supprimé le crash **en aggravant** la perte de coups
légaux. Le court-circuit mono est **conservé** (perf) : il est valide *parce que* la frontière est
désormais le budget exécutable — condition écrite dans son commentaire et verrouillée par test.

**Correctif — source unique de la frontière.** `squad_normal_move_frontier_subhex(game_state,
squad_id)` = `max(0, M − descente)`, lue par les **quatre** consommateurs (masque, décodeur,
érosion, canal de coût de l'obs). Plus `SQUAD_RIGID_MOVE_DESTINATION_LEVEL = 0` porté par
`build_rigid_plan`, propagé au pool (`destination_level`), à l'érosion, à la validation et à la
mesure (niveau de **trajet** = niveau **cible**, pas d'origine). Plus `move_plan_distance_mode`
(`geodesic` | `cube` | `euclidean`), qui remplace le booléen `move_uses_geodesic_distance` — lequel
confondait deux géométries incompatibles sous un même `False`.

**Effet fonctionnel (au-delà du crash).** Une escouade qui descend d'un étage récupère ses
destinations de la bande `(M − d, M]`, désormais jouables **en Advance** — elles étaient soit
inexécutables (mono), soit absentes du masque (multi). Conformité 09.06 : un déplacement que le
budget Normal ne couvre pas EST un Advance.

**Verrous.** `tests/unit/engine/test_squad_move_descent_frontier.py` — **10 tests**, dont
l'invariant « masque ⊆ exécutable » sur le cas mono-figurine descendant, et la non-érosion de la
bande morte sur le cas multi-figurines. **4 mutations vérifiées ROUGES**, une par ligne corrigée ;
celle de la frontière rejoue **le message d'erreur de production mot pour mot**
(`figurine 1#0 hors budget : … trajet legal contournant murs/figs > budget`).

**Re-mesure (2026-07-28).**

| Trajectoire (650 pas chacune) | Avant | Après |
|---|---|---|
| `scenario_pvp_test` x5, seed 42 — **la mesure d'origine, protocole identique** | **43** (23 + 16 + 4) | **0** |
| `scenario_pvp_test` x5, seed 7 | — | **0** |
| `scenario_pvp_test` x5, seed 1234 | — | **0** |
| `scenario_training_armageddon` x1 | **0** (seed 12345) | **0** (seed 42) |

Total après fix : **2 600 pas d'actions légales aléatoires, 0 exception moteur.**

Fichiers : `engine/phase_handlers/shared_utils.py`, `engine/phase_handlers/movement_handlers.py`,
`engine/observation_builder.py`, `tests/unit/engine/test_rigid_plan_translation.py` (contrat du
plan à 4 éléments), `tests/unit/engine/test_squad_move_descent_frontier.py` (neuf).
Tests impactés relancés verts (leçon §0.32 : lancer les fichiers IMPACTÉS, pas seulement les
neufs) : `test_move_mask_is_executable`, `test_move_budget_geodesic`, `test_squad_spatial_move_mask`,
`test_move_pool_block_erosion`, `test_rigid_plan_translation`, `test_move_plan_intra_squad_levels`,
`test_charge3d_floors_integration`, `test_spatial_grid`, `test_squad_grid_observation`,
`test_deployment_per_model_commit`. Pyright : 0 erreur.

📌 **Rattachement au motif §0.18 / §0.26.** Troisième occurrence de la même famille : *deux côtés
d'un invariant qui croient mesurer la même chose*. §0.18 = un écrivain qui ne teste pas la cellule
qu'il occupe ; §0.26 = un cache clé sur un compteur contournable ; §0.34 = une frontière calculée
sur le budget **nominal** quand l'exécution applique le budget **effectif**. À chaque fois, le
correctif est le même : **une seule fonction produit la grandeur**, et les deux côtés l'appellent.
Nouveauté de §0.34 : le bug était **partiellement masqué par un filet** (l'érosion), ce qui l'a
rendu invisible sur 95 % des escouades et l'a fait passer pour un cas particulier « mono-figurine ».
📌 **Leçon de méthode (→ §0bis).** Une piste écrite dans une note « hors périmètre » est une
hypothèse, pas un diagnostic : celle-ci nommait le bon fichier, la bonne fonction, la bonne ligne —
et la mauvaise cause.


<a id="s0.32"></a>
### 0.32 Optimalité de l'observation ET de la tête d'action — audit du 2026-07-28 — ✅ LIVRÉ (T-G/T-H/T-I/T-J/T-K/T-L ; résidus fermés par §0.37)

> ⏳ **Chiffres dépassés depuis — relevé du 2026-08-02.** Cette entrée décrit un état
> **intermédiaire** du 2026-07-28 ; du travail a été livré par-dessus (§0.40 pour l'observation,
> P2/P3-2 pour l'espace d'action). Valeurs courantes : `obs_size` **20828** (et non 20601/20626),
> `TOTAL_ACTION_SIZE` **1107** (et non 1062), `UNIT_CONT_SIZE` **20**, `UNIT_BIN_SIZE` **33**.
> `PROFILE_CONT_SIZE` 13 / `PROFILE_BIN_SIZE` 18 et `GRID_CHANNELS` **9** restent exacts.
> **Ne pas citer un chiffre de cette entrée comme état courant.**

**Origine.** Question de l'utilisateur : « mon obs est-elle optimale ? », posée pendant le test
x1 qui précède le run x5. Audit fait **par lecture du code**, pas de la doc — puis recoupement
des deux documents d'observation avec le code.

⚠️ **Rectification du 2026-07-28, même jour.** La 1re version de cette entrée affirmait « aucun
manque de règle actionnable dans le CONTENU de l'obs ; les constats portent sur la forme et sur
l'aval ». **C'est faux** : l'audit initial n'avait regardé que le vecteur, pas la grille. Deux
manques de CONTENU y ont été trouvés ensuite — **T-K** et **T-L** ci-dessous — et ils ont un
meilleur ratio effort/gain que T-G. Leçon : « j'ai audité l'observation » ne vaut que si les
**deux** moitiés de l'observation ont été lues ; le `Dict` en a deux, le vecteur et la grille.

**Ce que l'audit NE trouve pas.** Aucun manque dans le VECTEUR (le contenu par entité est
complet). Les cardinalités larges (§0.31) ne sont pas un problème : l'arbitrage y est mesuré (0 paramètre,
0 ms de construction) et le coût du training est ailleurs (§0.22 : `MOVE_POOL_BUILD` = 95,6 %).
**Conformité doc↔code : les deux documents sont exacts.** Recoupé : `obs_size` = 33 + 28×731 +
100 = **20601** au moment de l'audit — **20626 depuis la livraison de T-H/T-J**, cf. ci-dessous —, `UNIT_CONT_SIZE` = 19, `UNIT_BIN_SIZE` = 19 + 13 = 32,
`PROFILE_CONT/BIN_SIZE` = 13/18, `K_ENEMY_SLOTS` = 20 = `SHOOT_SLOT_COUNT` (verrouillé
[`pointer_policy.py:70`](../../ai/pointer_policy.py#L70)), les 5 caches et leurs invalidations,
les 3 invariants. Aucune affirmation périmée trouvée.

**État du lot au 2026-07-28** : **T-H, T-I et T-J sont LIVRÉS** (`deab7e03`) — bit `present` explicite, projection `_hex_center` unique, phase en one-hot de 6 bits, et les 4 replis du chemin (`phase`, `oc_total`, `squad_cache`) supprimés. `obs_size` **20601 → 20626**. **T-K et T-L sont LIVRÉS à leur tour** : `GRID_CHANNELS` **7 → 9** (canal `self`, canal `coût géodésique du pool de move`), `obs_size` **inchangé** (la grille est fournie à part), **zéro appel de pool supplémentaire mesuré**. **T-G est LIVRÉ le 2026-07-28** (`b78be588`) : les 1024 logits de cellule sortent d'une **conv 1×1** sur une carte CNN conservée à 32×32, avec canaux positionnels et conditionnement par le tronc (14 tests, 4 mutations, **+0,76 % de paramètres**, **×1,78 sur le forward**). **Le lot §0.32 est entièrement fermé.**

---

#### T-G — ✅ LIVRÉ (2026-07-28, `b78be588`) — la tête de move n'est plus dense

**Constat vérifié (état d'avant, corrigé par ce commit).** `pointer_policy.py` : seuls les 20
logits de tir sortaient d'un produit scalaire `q · e_i`. Les **1024 logits de cellule** sortaient
de `self.action_net(latent_pi)`, un `Linear(320 → 1062)` (net_arch `[320, 320]`, cf.
`ArmageddonAgent_training_config.json`). En amont, `spatial_extractor.py` faisait
`Conv → Conv(stride 2) → Conv(stride 2) → Flatten → Linear(4096, 256)` : **la carte spatiale était
détruite avant d'atteindre la tête**.

**Pourquoi c'est le point n°1.** C'est le raisonnement de
[`V11_entity_encoder_pointer.md`](V11_entity_encoder_pointer.md) §1.8 mot pour mot — « chaque
slot possède sa propre ligne de poids et n'apprend RIEN des autres » — mais appliqué à **1024
actions au lieu de 20** :

- chaque cellule a sa propre ligne de sortie (≈ 327 k paramètres, plus du quart du modèle) ;
- deux cellules voisines ne partagent aucun poids : ce que l'agent apprend en (12,7) ne vaut pas
  en (13,7) ;
- la correspondance « cellule (gx,gy) de la grille ↔ logit `gy*32+gx` » doit être **ré-apprise**
  par des poids denses, alors qu'elle est structurelle ;
- les cellules rarement visitées restent mal apprises toute la partie — et sur x5 les épisodes
  sont plus longs, donc cette sample-complexity se paie plein pot.

⚠️ **Ne pas confondre avec la « tête spatiale » de
[`A_faire/move_action_space_spatial_rework.md`](A_faire/move_action_space_spatial_rework.md)
§6.2** : ce document appelle « tête spatiale » le fait que **l'action désigne une cellule**, pas
une tête convolutive. La policy y est spécifiée `MultiInputPolicy` + « extracteur CNN pour la
grille » — ce qui est bien ce qui est implémenté. Le manque n'est pas une régression : il n'a
jamais été spécifié.

**Correctif retenu — il ne touche PAS l'observation.** Conserver dans l'extracteur une branche CNN
**non aplatie**, à résolution 32×32 (aucun stride), et produire le logit d'une cellule par une
**conv 1×1** sur sa colonne de features : `logit(gx,gy) = w · f[:, gy, gx]`. Le nombre de cellules
devient gratuit en paramètres et l'alignement obs↔action devient structurel. C'est le jumeau exact
de la tête pointeur, côté move.

⚠️ **Amendement du 2026-07-28 — la conv 1×1 SEULE serait PLUS FAIBLE que la tête dense.** La
première rédaction de ce correctif vendait l'équivariance en translation comme un gain net. Elle
est **fausse ici**, pour deux raisons qui imposent chacune un ajout obligatoire :

1. **La sémantique d'une cellule dépend de son RAYON**, pas seulement de son voisinage : la
   grille est égocentrique et normalisée par le budget d'Advance (centre = mon bloc, bord =
   limite d'atteignabilité). Une conv pure est invariante par translation, donc **incapable
   d'exprimer « le centre n'est pas le bord »** — alors que la tête dense, elle, sait exactement
   où est chaque cellule. ⇒ **Canaux positionnels fixes obligatoires** (x, y, rayon normalisés),
   concaténés avant le 1×1.
2. **Un 1×1 sur une pile conv peu profonde a un champ réceptif de quelques cellules** : la tête
   ne verrait ni le tour, ni les VP, ni les objectifs hors fenêtre, ni mes autres escouades —
   toute la partie du tronc qui justifie une destination. ⇒ **Conditionnement obligatoire** par
   le latent du tronc, diffusé (broadcast) sur les 32×32 avant le 1×1.

Sans ces deux ajouts, le remède remplace un défaut par un autre. Le diagnostic (1024 lignes de
poids indépendantes, aucun partage entre cellules voisines) reste, lui, entier.

⚠️ **Zone à risque identique à celle de T-E** (cf. l'en-tête de `pointer_policy.py`) : une tête
d'action custom sous `MaskablePPO` échoue **en silence** si `log_prob`, l'entropie ou le masquage
sont faux. Même discipline obligatoire : ne toucher QUE la valeur des logits, laisser la
distribution, le masquage, `log_prob` et l'entropie à SB3, et vérifier contre une tête dense de
référence sur un cas jouet (`tests/unit/ai/test_pointer_head.py` est le modèle à suivre).

---

##### Ce qui a été LIVRÉ (`b78be588`)

**[`ai/spatial_extractor.py`](../../ai/spatial_extractor.py)** — le CNN est désormais un **stem
commun** (`cnn_stem`, une conv 3×3 pleine résolution sur les 9 canaux) suivi de **deux branches** :

| branche | forme | destination |
|---|---|---|
| `cnn` → `cnn_head` (inchangée) | `stride 2 ×2 → Flatten → Linear(4096, 256)` | le **tronc**, qui a besoin d'un résumé GLOBAL de la fenêtre |
| `map_net` (nouvelle) | conv 3×3 **stride 1**, jamais aplatie | la **carte** `(16 + 3) × 32 × 32`, lue par la tête de move |

La carte est concaténée en fin de vecteur de features, derrière les embeddings ennemis, et sa
tranche est publique (`move_map_slice()`, jumelle de `enemy_embeddings_slice()`). `features_dim`
passe de **1 926 à 21 382** — c'est un tenseur de transit, **pas** de l'observation : le rollout
buffer ne stocke que l'obs, inchangée.

**Les deux ajouts de l'amendement, tels qu'implémentés :**

1. **Canaux positionnels** (`positional_channels()`) : `x`, `y`, `rayon`, en unités de
   demi-étendue de grille, donc en unités de **budget d'Advance maximal**. Ce sont exactement les
   coordonnées normalisées de `spatial_grid.cell_center_px` — un test le vérifie cellule par
   cellule contre cette source unique, sans recopier la moindre constante de géométrie. `rayon = 1`
   est la limite d'atteignabilité, pour toute unité et toute échelle de board. Ils entrent dans
   `map_net` **et** ressortent tels quels dans la carte : la tête 1×1 y a un accès direct.
2. **Conditionnement par le tronc**, dans [`ai/pointer_policy.py`](../../ai/pointer_policy.py) :
   `move_cell_net` (conv 1×1 sur la carte) et `move_ctx_net` (`Linear` sur `latent_pi`) sont les
   **deux moitiés d'une seule conv 1×1 appliquée à `[carte ; latent diffusé sur les 32×32]`**. La
   forme factorisée est un choix de calcul, pas d'architecture : le terme du latent ne dépendant
   pas de la cellule, le calculer une fois évite de matérialiser un tenseur
   `(1024, 320, 32, 32)` — **1,3 Go pour diffuser une constante** — et 1024× de MACs. Un test
   compare au bit près à la forme naïve (broadcast explicite + concat + une conv 1×1).

⚠️ **Piège traité, il aurait rendu l'amendement inopérant en silence** : avec **une seule** conv
1×1, la contribution du latent serait un décalage **identique sur les 1024 logits** — donc
strictement invisible du softmax. Le conditionnement aurait été un no-op : la tête aurait tourné,
appris, et n'aurait jamais rien su du tour ni des VP. D'où **deux** couches 1×1 avec une ReLU
intercalée, et un test qui exige que changer le latent **réordonne** les cellules
(`test_trunk_context_reorders_the_cells_it_is_not_a_uniform_shift`).

**Discipline T-E respectée** : seule la **valeur** des logits change. La distribution, le masquage,
`log_prob` et l'entropie restent ceux de SB3 (`MaskableCategorical`). Les colonnes `move` de
`action_net` deviennent inertes, comme les colonnes `shoot` — un test le verrouille en les
perturbant de +10 et en exigeant que rien ne bouge.

**Tests (14, `tests/unit/ai/test_pointer_head.py` + `test_entity_encoder_extractor.py`).** Le plus
important est le **test d'alignement** : un pic injecté dans la colonne `(gx, gy) = (5, 20)` de la
carte doit déplacer le logit de l'action `cell_index = gy*32+gx` **et aucun autre**. La cellule est
volontairement asymétrique : à `gx == gy`, une transposition passerait. Un second test refait le
parcours **de bout en bout** depuis la grille (latent gelé, sinon le conditionnement fait bouger les
1024 cellules — ce qui est le comportement voulu) et exige que les cellules déplacées tiennent dans
la fenêtre 5×5 centrée sur `(gx, gy)`, le champ réceptif réel de `stem + map_net`.

**Mutations, toutes vérifiées rouges :**

| mutation | tests qui rougissent |
|---|---|
| transposer `gx`/`gy` dans la tête | alignement, champ réceptif, référence naïve |
| retirer la ReLU de `_move_logits` | conditionnement uniforme, référence naïve |
| annuler les canaux positionnels | invariance par translation de la carte |
| remettre un `stride 2` dans `map_net` | résolution de la carte (+ 3 tests en cascade) |

**Mesures.** Protocole de §0.30/§0.31 : config **réelle** de l'agent (`net_arch [320, 320]`,
`cnn_features 256`), mesures **appariées** (avant = `git stash` des deux fichiers, dans le même
processus/machine), médiane de 3 paires.

| grandeur | avant | après | écart |
|---|---|---|---|
| paramètres de la policy | 2 117 735 | **2 133 736** | **+16 001 (+0,76 %)** — dont 10 945 de tête 1×1 et 5 056 de `map_net` |
| `features_dim` (transit, pas l'obs) | 1 926 | **21 382** | la carte `19 × 32 × 32` |
| forward `get_distribution`, batch 64 | 13,4 ms | **23,5 ms** | **×1,75** |
| forward `get_distribution`, batch 1024 | 272 ms | **483 ms** | **×1,78** |

Ce que remplacent ces 16 001 paramètres : **328 704** lignes de `action_net` (`(320+1) × 1024`) qui
portaient les logits de cellule. Elles restent physiquement présentes mais **ne reçoivent plus
aucun gradient** — choix assumé, identique à celui de T-E : conserver `action_net` entier laisse
intacts l'initialisation orthogonale, la sauvegarde/reprise et le reste de la machinerie SB3. Le
coût en calcul de ces colonnes mortes est ~3 % de celui de la tête de move, sous le seuil qui
justifierait de découper `action_net`.

**Partage du stem, mesuré et non déduit.** La branche carte pourrait avoir sa propre conv d'entrée.
Sur les piles conv **isolées** (batch 256, 4 threads, 5 mesures alternées), la branche carte coûte
**+58 %** du CNN d'avant T-G en partageant le stem contre **+98 %** en le dupliquant — 1,7× moins
cher, et 3 056 paramètres de moins. ⚠️ Sur le forward **complet**, l'écart entre les deux variantes
est **sous le bruit de la machine (±10 %)** : les encodeurs d'entités dominent. C'est la mesure
isolée qui tranche ; une première rédaction de ce paragraphe annonçait « 1,91× contre 1,44× » sur
le forward complet — **chiffre faux, tiré d'un couple de mesures bruitées, retiré**.

⚠️ **NON MESURÉ, et volontairement non affirmé : le gain de sample-efficiency.** Tout ce qui précède
mesure des paramètres et des millisecondes. Que le partage de poids entre cellules fasse
effectivement apprendre plus vite ne se prouve **que par un run** (§0.14). Le coût, lui, est réel et
mesuré : **×1,78 sur le forward**. Le pari reste raisonnable — §0.22 mesure `MOVE_POOL_BUILD` à
**95,6 %** du temps de training, donc le forward n'est pas le poste dominant — mais c'est un pari,
pas un résultat. Le run §0.14 doit être un `--new` : l'architecture de la policy change, aucun
checkpoint antérieur ne se recharge.

---

#### T-H — ✅ LIVRÉ (2026-07-28, `deab7e03`) — une figurine pouvait être vue comme ABSENTE

**Constat.** `spatial_extractor.py` déduisait le masque de présence des figurines de l'unité active
par `(|cont| + |bin|) > 0`, faute de bit dédié — le commentaire du code le disait lui-même :
« aucune feature individuelle n'est un bit de présence ». Or le builder écrivait
`col_rel = col − cx`, `row_rel = row − cy`. **Donc une figurine posée sur le centroïde arrondi, ni
éligible au combat, ni dans une EZ ennemie, ni relayée, avait sa ligne ENTIÈREMENT nulle** — exclue
de l'agrégation `_masked_mean_max` **et** du dénominateur de `EntityRunningNorm`. Rien ne levait :
l'obs décrivait une escouade d'un effectif faux. Motif §0.18/§0.26 sous une autre forme.

**Livré.** Bit `present` explicite en **dernière** position de `SELF_MODEL_BIN_FIELDS`
([`observation_entities.py`](../../engine/observation_entities.py)) — même convention que les
masques des registres d'armes et de types, lus en `[..., -1]` ; rempli par
`build_squad_observation` ; **lu** par l'extracteur via `self_model_bin_index("present")` (aucun
index recopié). Deux helpers d'index ajoutés (`self_model_cont_index` / `self_model_bin_index`),
au même titre que `unit_*_index` / `global_*_index`. Le commentaire qui justifiait la déduction a
disparu : il documentait le bug. **Coût : +20 scalaires** (`obs_size` 20601 → 20621, puis 20626
avec T-J).

**Tests** (`tests/unit/engine/test_squad_obs_geometry_phase_presence.py`,
`tests/unit/ai/test_entity_encoder_extractor.py`) : la fixture pose une escouade de 4 figurines
dont le centroïde tombe **exactement** sur (30,20) avec une figurine **pile dessus** — un
garde-fou (`test_fixture_is_the_pathological_case`) vérifie que ce cas est bien celui du constat
(continues nulles, aucun drapeau) ; la somme des bits `present` vaut l'effectif vivant avant comme
après une perte ; les slots de padding restent à zéro ; côté extracteur, une ligne à `present = 0`
mais à continues non nulles **ne doit plus** changer la sortie — c'est le cas qui discrimine « lire
le bit » de « déduire la ligne » — avec sa contre-épreuve (`present = 1` doit, lui, changer la
sortie). Mutation : la déduction remise en place fait rougir le test d'extracteur.

---

#### T-I — ✅ LIVRÉ (2026-07-28, `deab7e03` + `bde78380`) — il n'y a plus qu'UNE géométrie

**Constat.** `col_rel` / `row_rel` — pour les **entités** comme pour les **figurines** — étaient des
différences de coordonnées **offset brutes**, alors que tout le reste de l'obs travaille dans la
projection `_hex_center` : la grille égocentrique, qui l'a choisie **explicitement** pour éviter
l'anisotropie de parité ([`spatial_grid.py`](../../engine/spatial_grid.py), « rasterisation
GÉOMÉTRIQUE §10.9 » — [§10.9 de `move_action_space_spatial_rework.md`](A_faire/move_action_space_spatial_rework.md)),
et les directions d'objectif de §0.31. En offset, un même déplacement
euclidien donne des `(Δcol, Δrow)` différents selon la parité de la ligne.

**Livré.** Les deux paires sont émises dans la projection `_hex_center`, relativement à
`_hex_center(centroïde arrondi)` — **la même origine** que `_squad_objective_geometry`. **Le choix
de la figurine « la plus proche »** d'une entité passe lui aussi dans ce repère : le laisser en
offset aurait fait dépendre de la parité *quelle* figurine est décrite, pas seulement sa direction
— le constat aurait été à moitié traité. `_hex_center` est désormais importé au niveau module
(feuille math/numpy, aucun cycle) et l'ancre projetée est calculée **une fois** puis passée par
`ctx` aux 28 entités. **Coût nul en taille.**

**Mesure de l'anisotropie corrigée** : deux voisins hexagonaux de (30,20) de parités différentes,
(30,19) et (29,19), donnaient des normes **1,0** et **1,414** ; ils donnent tous deux **1,732**
(= √3, le pas centre-à-centre). **Tests** : isotropie sur les figurines et sur les entités, plus
deux oracles indépendants qui recalculent `_hex_center(fig) − _hex_center(ancre)` hors du builder.
Mutation : le retour aux offsets fait rougir les 4.

**Perf mesurée** (12 figurines × 8 escouades, 200 appels) : `build_squad_observation`
**2,212 → 2,402 ms** en première écriture — le bloc tourne pour les **28 entités** à chaque step et
la table `{mid: _hex_center(…)}` y coûtait ~1 µs par entité pour une projection qui ne sert qu'à la
figurine gagnante. Réécrit en une passe (`bde78380`) : **2,242 ms**, soit **+1,4 %** pour le passage
à la projection. `_hex_center` reste la source unique de la formule — la dupliquer en inline aurait
gagné 0,05 ms de plus pour un risque de dérive entre deux copies, sur un poste qui ne pèse pas
(§0.22 : `MOVE_POOL_BUILD` = 95,6 % du training).

---

#### T-J — ✅ LIVRÉ (2026-07-28, `deab7e03`) — `phase` est un one-hot, et plus rien ne se replie

**Constat.** `{"deployment": 0.0, "command": 0.0, "move": 0.25, …}` puis `.get(phase, 0.0)` :
`deployment` et `command` partageaient **0.0**, alors que les ids d'action 4–8 signifient « slot de
déploiement » (`DEPLOY_SLOT_BASE = 4`) dans l'une et « cellule de move » dans l'autre
([`macro_intents.py`](../../engine/macro_intents.py)) — le seul indice restant était **indirect**
(les bits `deploy_not_on_board`). L'encodage ordinal imposait en plus une métrique entre phases qui
n'a aucun sens, et le `.get` servait « déploiement » pour une phase inconnue.

**Livré.** `phase_deployment` … `phase_fight` : **one-hot de 6 bits** dans `GLOBAL_BIN_FIELDS`,
généré depuis `OBS_PHASE_IDS`. Cette constante est **verrouillée par test** sur
`action_decoder.GAME_PHASES` plutôt qu'importée : `observation_entities` est une **feuille**, et
importer `action_decoder` (qui tire tout le moteur) créerait un cycle — même montage que
`N_OBJECTIVE_SLOTS` ↔ `macro_intents.MAX_OBJECTIVES`. Les trois replis sont tombés : `.get(phase,
0.0)` → `ValueError` explicite sur une phase hors des 6 ; `game_state.get("phase", "command")` →
`require_key` ; `sq.get("oc_total", 0)` → `require_key`, **et** avec lui le
`squad_cache[sid] if sid in squad_cache else {}` qui le rendait atteignable — `squad_cache` est
construit pour chaque escouade de `squad_models`, donc une entrée absente est une incohérence de
cache, pas un cas de jeu, et `{}` la servait comme une escouade d'**OC nul** (règle 14).
**Coût : +5 scalaires.**

**Tests** : les 6 phases donnent 6 encodages **distincts** (dont `deployment` ≠ `command`, l'objet
du constat), chacun un one-hot valide ; une phase inconnue (`"shooting"`, le nom du *log*) lève ;
la clé `phase` absente lève. Le verrou existant `test_binary_tensors_hold_only_discrete_semantics`
perd son exception : `phase` était la seule dimension `_bin` non discrète du contexte, elle ne l'est
plus. Mutation : l'encodage ordinal restauré fait rougir les 3.

**Résidu fermé le 2026-07-28 (relecture utilisateur du lot).** Un **4ᵉ repli** du même chemin avait
été *signalé mais laissé en place* :
`model_count_at_start = max(1, int(sq.get("model_count_at_start", len(alive_mids))))`. Il masquait
deux incohérences distinctes : le défaut `len(alive_mids)` rendait un `model_count_ratio` de **1.0
— « escouade intacte » — sur une escouade décimée**, et le `max(1, …)` transformait un 0 de cache
en **ratio > 1** servi tel quel au réseau. Vérifié avant durcissement : la clé est **posée pour
chaque escouade** par `build_units_cache`
([`shared_utils.py:1048`](../../engine/phase_handlers/shared_utils.py#L1048)) et **préservée** à
chaque recalcul ([`:3081`](../../engine/phase_handlers/shared_utils.py#L3081)) ; le reste du moteur
la lit **déjà sans repli** ([`:4331`](../../engine/phase_handlers/shared_utils.py#L4331),
[`:7151`](../../engine/phase_handlers/shared_utils.py#L7151),
[`fight_handlers.py:5175`](../../engine/phase_handlers/fight_handlers.py#L5175)) — l'observation
était le **seul** site tolérant. Désormais `require_key` + `ValueError` explicite sur `<= 0`.
**2 tests** (clé absente / valeur nulle), **mutation faite** : l'ancienne ligne restaurée les fait
rougir tous les deux. 14 verts sur le fichier, 45 sur la famille observation touchée.

📌 **Leçon de méthode (§0bis).** Signaler un repli dans un rapport n'est pas le traiter — c'est le
rendre présentable. Quand un lot a pour objet de supprimer les replis d'un chemin, il les supprime
**tous**, ou il documente pourquoi le dernier est techniquement impossible à fermer dans la
session. « Dis-moi si tu veux que je le durcisse aussi » n'est pas une clôture.

---

#### T-K — ✅ LIVRÉ (2026-07-28) — le COÛT GÉODÉSIQUE par cellule est devenu un canal

**Constat.** [`spatial_grid.py`](../../engine/spatial_grid.py) — `project_pool_to_grid` renvoie
`{cell_index: ((col,row), coût_géodésique)}`. Ce coût était produit **à chaque activation, pour le
masque**, puis **jeté** : seul le seuil `coût ≤ M` en survivait, pour inférer le type de move.

Or c'est la quantité qui arbitre le choix le plus cher de la phase de mouvement : `coût > M`
force un **advance**, qui interdit le tir non-[ASSAULT] et la charge. L'agent voyait les murs
bruts et devait **refaire le BFS mentalement** pour savoir si la cellule qu'il visait lui coûtait
son tir.

**Correctif livré.** `GRID_CH_MOVE_COST` (canal 8), encodé par `normalize_move_costs`
([`spatial_grid.py`](../../engine/spatial_grid.py), source unique) : affine **par morceaux**,
`[0, M] → [0 ; 0,5]` et `(M, H] → (0,5 ; 1]`, où `M` est le budget de move normal — **exécutable**,
c'est-à-dire coût de descente §13.06 déduit, depuis §0.34 — et `H` la
demi-étendue de la grille (= budget Advance MAXIMAL, borne supérieure de tout coût du pool).
Le canal tient donc dans `Box(0,1)` — contrainte réelle de l'espace d'obs — et **la frontière
normal/advance tombe sur 0,5 exactement, pour toute unité et toute échelle de board**.
0 hors du pool : l'atteignabilité reste portée par le masque, elle n'est **pas** dupliquée. Hors
phase de mouvement le canal est nul. `normalize_move_costs` **lève** sur un coût hors bornes ou un
budget incohérent, au lieu de clipper — un clip écraserait à la même valeur toutes les
destinations lointaines.

⚠️ **Pourquoi une frontière CONSTANTE, et non une simple division par `H`.** La 1re version livrée
divisait par `H`. Elle est **correcte mais sous-optimale**, et le défaut est structurel : la grille
passe **seule** dans le CNN ([`spatial_extractor.py`](../../ai/spatial_extractor.py) :
`self.cnn_stem(observations["grid"])`), le vecteur n'est concaténé qu'**après** l'aplatissement. Avec
`coût / H`, la frontière vaut `MOVE / (MOVE + 6)` — 0,40 pour un MOVE 4", 0,70 pour un MOVE 14" :
pour savoir si une cellule lui coûte son tir, le CNN devrait croiser le canal avec un MOVE qui ne
lui parvient jamais. **L'information la plus utile du canal était illisible là où elle est
produite** — et le serait plus encore depuis la tête de move (**T-G**, livrée), qui score chaque
cellule par une conv 1×1 sur sa colonne de features CNN, donc **localement**. L'encodage par morceaux est monotone et bijectif par
morceaux : rien n'est perdu, seule l'échelle est recalée. Escouade engagée : le pool est au budget
Fall Back (= M), donc tout le canal reste ≤ 0,5 — exact, et informatif (« aucun advance
disponible »).

⚠️ **Le piège dimensionnant a été traité par CONSTRUCTION, pas par un réglage de clé.** L'obs ne
redemande **aucun** pool : elle relit la carte que le masque vient de mémoïser
(`read_squad_move_cell_map`). `_build_observation` construit le masque **avant** l'obs et pour le
**même** squad actif — donc zéro appel de pool supplémentaire, donc aucune possibilité qu'une clé
de fingerprint diverge de celle du masque. C'est aussi ce qui garantit que obs, masque et decoder
parlent des mêmes cellules et des mêmes coûts (test dédié).

**Mesuré** (600 steps, `config/board/44x60x5/scenario/scenario_pvp_test.json`, seed 42,
trajectoire strictement identique avant/après — mêmes 43 erreurs moteur, cf. note ci-dessous) :

| | appels de pool | hits | miss | taux de hit | `build_squad_grid` moyen |
|---|---|---|---|---|---|
| avant (3 passes) | **1 578** | 1 186 | 392 | **75,16 %** | 3,279 / 3,357 / 3,305 ms |
| après (3 passes) | **1 578** | 1 186 | 392 | **75,16 %** | 3,364 / 3,398 / 3,352 ms |

Le compteur d'appels de pool est **strictement identique** : c'est la mesure qui compte, plus
forte qu'un taux de hit « ~100 % » — le canal n'ajoute pas un seul BFS géodésique, donc rien du
poste à 95,6 % du training (§0.22). Le taux de 75,16 % est celui, **inchangé**, du cache
préexistant. Coût de construction du canal lui-même : **+1,7 %** (3,314 → 3,371 ms), les plages
avant/après se chevauchant (3,357 avant vs 3,352 après) — du même ordre que le bruit.

**Coût de l'encodage par morceaux, mesuré en APPARIÉ** (les deux implémentations alternées dans le
**même processus**, sur la même trajectoire — les passes inter-processus dérivaient avec la charge
machine, ce qui donnait un écart de +0,16 ms non reproductible) : médiane sur 3 paires,
**3,213 ms** (division simple) → **3,351 ms** (par morceaux), soit **+4,3 %** de
`build_squad_grid`, ≈ **+0,2 %** d'un step. Le micro-bench isolé de `normalize_move_costs` donne
+0,007 ms sur 1 024 cellules ; le reste de l'écart n'est pas expliqué et n'a pas été poursuivi —
le poste ne pèse pas (§0.22 : `MOVE_POOL_BUILD` = 95,6 % du training), et §0.31 a déjà tranché ce
type d'arbitrage en faveur de la lisibilité.

#### T-L — ✅ LIVRÉ (2026-07-28) — l'escouade active a son propre canal

**Constat.** `build_squad_grid` peignait le canal `GRID_CH_ALLY` avec **toutes** les unités du
joueur actif : `sink = ally_hexes if int(entry["player"]) == active_player else enemy_hexes`.
L'escouade **active** y était indistinguable d'une escouade amie voisine — sur une grille pourtant
centrée sur elle, dont la demi-étendue est SON budget, et dont chaque cellule jouable est une
destination de SON bloc rigide.

**Correctif livré.** `GRID_CH_SELF` (canal 7) porte les figurines de l'escouade active ;
`GRID_CH_ALLY` ne porte plus que les **autres** escouades du joueur actif. Le tri se fait sur
`active_squad_id`, pas sur le joueur : le canal suit l'activation (test dédié).

**`GRID_CHANNELS` passe donc de 7 à 9**, source unique
[`engine/spatial_grid.py`](../../engine/spatial_grid.py) — vérifié : `ai/spatial_extractor.py`
(entrée du CNN **et** contrôle de forme, qui lève toujours) et l'espace d'observation de
`w40k_core` la lisent depuis là, aucun nombre de canaux n'est recopié. `obs_size` (vecteur)
**inchangé à 20 626** : la grille est fournie à part dans le `Dict`.
⚠️ **RAM du rollout buffer — le chiffre « 14,49 Go, sous la limite de 19,33 Go » ne décrit QUE la
grille, et il est trompeur seul.** Depuis §0.30/§0.31 le VECTEUR pèse plus lourd que la grille
(20 626 contre 9 216 floats) et il est stocké dans le même buffer. Mesuré le 2026-07-28 :
**46,9 Go** sur les profils à 48 envs, pour **39 Go de RAM physique**. Ce n'est pas une dette de
§0.32 — les canaux y ajoutent 3,2 Go sur un total déjà hors budget — c'est un **bloqueur du run
§0.14**, traité à part en **§0.33**.

**Tests** : 11 dans `test_squad_grid_observation.py` (dont l'**oracle** T-K et le test de frontière
constante), 4 dans `test_spatial_grid.py` (`normalize_move_costs` : frontière identique sur 6
couples `(M, H)` de MOVE 4" à 14" en ×1 et ×5, intervalle unité et monotonie stricte, budget normal
nul, et les 4 façons de la faire lever) et 2 dans `test_entity_encoder_extractor.py` (profondeur
d'entrée du CNN lue depuis la source unique, forme de grille erronée qui lève).
**Mutations faites** : (a) restaurer l'ancien `sink` → 3 rouges ; (b) remplacer le coût géodésique
par la distance à vol d'oiseau → 4 rouges dont l'oracle ; (c) revenir à `coût / H` → 3 rouges dont
le test de frontière constante.

⚠️ **Deux versions de l'oracle T-K ont dû être jetées, chacune démasquée par sa mutation** — c'est
la mutation qui a fait le travail, pas la relecture :
1. `read_cost > straight` comparé au **mauvais hex** (la projection retient l'hex le plus proche
   du centre de cellule, pas celui qu'on vise) ;
2. puis `read_cost >= straight + 1` : **les coûts du BFS ne sont pas entiers** — en métrique `hex`
   un pas vaut `2/√3 ≈ 1,155` —, si bien que « distance hex + 1 » comparait deux grandeurs
   d'unités différentes et aurait pu passer **sans aucun contournement**.
L'oracle final est **comparatif et sans unité** : à distance à vol d'oiseau **égale**, la cellule
derrière la barrière porte une valeur strictement supérieure à celle de son symétrique du côté
dégagé. Il est vérifié que les deux cellules désignent bien des hexes à la même distance directe,
sans quoi le test ne prouverait rien.

🐛 **Un bug de la borne, trouvé par un test d'un AUTRE fichier.** La garde « coût ≤ demi-étendue »
levait sur une destination **pile au budget** : les coûts sont des sommes de pas de `2/√3`, si bien
qu'un budget de 12 ressort à `12.000000000000005`. Invisible tant que les coûts transitaient en
float32 (l'arrondi effaçait l'epsilon), révélé par le passage en float64 — et attrapé par
`test_spatial_move_decode_execute`, **pas** par les tests de la grille. En production cela aurait
levé en plein training. La borne porte désormais une tolérance de `1e-6`, très au-dessus de
l'erreur flottante (~1e-15) et très en dessous d'un pas hex (~1,15) : une vraie incohérence
pool/grille ne peut pas s'y cacher. Test de régression dédié.
📌 **Leçon** : lancer les fichiers de tests IMPACTÉS, pas seulement ceux qu'on écrit.

⚠️ Ces deux canaux changent l'entrée du CNN : les poids existants sont incompatibles, le run
§0.14 doit être un `--new` postérieur à ce commit. Ils sont livrés **avant** T-G, sinon la tête
serait à retoucher deux fois.

📌 **Trouvé en passant, HORS périmètre, non traité** (rencontré en instrumentant le run de mesure,
reproduit **sans** instrumentation, 43 occurrences sur 650 steps d'actions aléatoires légales) :
- `execute_squad_move a échoué : squad=1008 type=normal … (incohérence masque/exécution)` —
  « figurine 1008#0 hors budget : trajet légal contournant murs/figs > budget ». L'escouade est
  **mono-figurine**, et `erode_move_pool_by_squad_block` court-circuite ce cas
  (`len(alive_mids) <= 1 → return costs`, « l'ancre EST le bloc ») : l'érosion géodésique
  par-figurine n'est donc jamais appliquée là où le pool d'ancre et `validate_move_plan`
  divergent quand même. Piste, **non vérifiée**.
- `_euclidean_path_distance: destination … injoignable en chemin <= 90 … alors que le plan a été
  validé. Incohérence validation/mesure.`
- `floor_height_at: no floor at level 1 contains cell … (figurine marquée à l'étage mais hors
  empreinte de plancher)`.

---

**Note x1 → x5 (vérifiée, pas déduite).** L'obs est **invariante d'échelle par construction** :
`MOVE` est déjà en subhex ([`shared_utils.py:4450`](../../engine/phase_handlers/shared_utils.py#L4450)),
la demi-étendue de grille vaut le budget d'Advance, et toutes les longueurs (portées,
`edge_distance`, distances d'objectif) scalent du même facteur `inches_to_subhex`. Un x1 qui
apprend est donc un signal valide pour x5. ⚠️ **Piège** : `obs_size` est **identique** entre x1 et
x5 — un `.zip` entraîné en x1 se chargera **sans erreur** sur un board x5. Rien n'avertit d'une
reprise accidentelle.


<a id="s0.31"></a>
### 0.31 Complétude de l'observation — objectifs situés + règles d'unité visibles — ✅ LIVRÉ (2026-07-27)

**Origine.** Question de l'utilisateur : « l'obs est-elle complète et complètement branchée ? »,
puis « est-elle optimale ? ». Réponse vérifiée par lecture et **mesure in-engine**, pas par
relecture de doc.

**Branchement : intact.** `obs_size` → garde-fou strict ([w40k_core.py:688](../../engine/w40k_core.py#L688),
aucun repli), routage vers `build_squad_observation`, espace `Dict` dérivé de `squad_obs_shapes()`,
`SpatialCombinedExtractor` + `PointerMaskablePolicy` injectés aux 3 sites de création de modèle
de `train.py` (les 9 `MaskablePPO(...)` sont tous en aval). Tous les slots sont réellement
remplis. Rien de mort, rien de construit-mais-non-consommé.

**Deux trous trouvés, tous deux fermés.**

1. **Les objectifs n'avaient aucune POSITION** (commit `ab9baa56`). L'action space offre 3 intents
   de zone par objectif (15 actions) et `global_bin` ne portait que contrôle + présence. La seule
   source spatiale était le canal 4 de la grille, dont la demi-étendue vaut le budget d'Advance
   (**12″ mesuré**) et qui écarte sans clamp tout hex hors fenêtre. **Mesure au reset : 1 à 2
   objectifs sur 5 seulement tombaient dans la fenêtre** — l'agent désignait des objectifs qu'il
   ne percevait pas, et ne pouvait pas apprendre à naviguer vers un objectif lointain. Ajouté :
   distance à l'hex le plus proche de la zone (continue, subhex bruts) + direction unitaire
   (cos/sin, avec les drapeaux — bornés et centrés, `VecNormalize` ne ferait qu'amplifier leur
   bruit, même raison que `phase`). Ex-aequo tranchés explicitement sur le plus petit (col,row) :
   une zone rectangulaire offre presque toujours deux hexes équidistants, de `sin` opposés —
   `argmin` aurait fait dépendre la feature de l'ordre du fichier. **6 tests, dont un oracle
   scalaire indépendant.**
2. **Les règles d'UNITÉ étaient invisibles** (commit `0fb94a01`, cf. [§9.2.5](V11_phaseA.md#s9.2.5)). 13 bits d'EFFET par
   entité, amies ET ennemies. Ce sont les effets, pas les capacités nommées :
   `unit_has_rule_effect` résout les sources, donc les composites des datasheets sont captées
   (`cunning_hunters`, `targeted_intercession`, `target_priority`, `adaptable_predators`,
   `aggression`/`preservation_imperative`). Exclus avec leur raison : les marqueurs de rôle (le
   bloc TYPES les porte déjà) et `adrenalised_onslaught`, qui est un **choix de joueur** sans
   effet tant que P2 n'existe pas — **candidate P3**. **19.04 verrouillé** : le bit du leader
   attaché s'allume, puis s'éteint à sa mort. **7 tests.**

**Perf, hors lot** (commit `7a84e124`) : les profils d'armes — 86 % du vecteur — étaient
reconstruits pour les 16 entités à chaque step alors qu'ils viennent des datasheets. Mémoïsés par
(escouade, figurines vivantes), invalidés dans `build_units_cache`. **`build_squad_observation`
2,86 → 1,69 ms (1,69×)**, observation identique bit à bit. ⚠️ Piège traité : mémoïser sans
mémoïser la troncature rendait **muets** les verrous « aucun cap silencieux » dès le 2ᵉ step —
elle est donc rejouée à chaque appel.

**Cardinalités : arbitrage utilisateur — les K larges sont GARDÉS.** Remplissage mesuré : 29 %
des slots ennemis, ~25 % des slots d'armes ; maxima réels sur **22 rosters / 79 unités** :
6 escouades, 6 profils de tir, 5 de mêlée, 4 types, 12 figurines. Les resserrer aurait divisé le
vecteur par 2,5 — l'utilisateur les garde pour absorber des rosters plus fournis sans re-tailler
l'obs ni retrainer. Mesuré avant de trancher : **paramètres identiques (1,14 M)**, **construction
identique (1,92 vs 1,94 ms)**, forward extracteur **1,39×**. ⚠️ **Affirmation fausse retirée** :
« les 12 slots de tir morts polluent l'exploration » — `build_squad_action_mask` ne lève le bit
qu'après avoir confirmé un ennemi atteignable, donc MaskablePPO les met à `-inf` en permanence.

**`obs_size` 20166 → 20181 → 20545 → 20601.** Le run reste un `--new` (§0.14) ; un run x1 lancé avant ces
commits est incompatible.

**Suite : état terrain des ennemis — ✅ TRAITÉ le 2026-07-27, réduit à 2 bits après lecture des
PDF.** L'entrée disait « vrai manque pour le choix de cible, à mesurer avant de décider ». Mesuré
et arbitré ; le manque était surestimé. Les quatre conclusions de règles, à ne pas re-dériver :

1. **13.09 Hidden est PAR FIGURINE**, pas par unité : « **A model** is hidden while all of the
   following apply **to it** : that model has the INFANTRY/BEASTS/SWARM keyword and is within a
   terrain area that contains one or more dense terrain features ; **that model's unit** did not
   make one or more ranged attacks during this turn or during the previous turn. » Première
   condition par figurine, seconde au niveau de l'unité. Ses deux conditions sont
   **intrinsèques** : la portée de détection 15″ est l'*effet* de hidden, pas sa définition — donc
   aucun test par paire n'est requis pour l'évaluer.
2. **05.03/05.04 : l'allocation des pertes n'exige AUCUNE visibilité.** Les groupes sont créés par
   (W, Sv, InSv) et CHARACTER, puis « Select Model: select one model in the current allocation
   group ; this must be a model that has lost one or more wounds if possible ». Dès qu'une unité
   est ciblable (04), **toutes** ses figurines peuvent encaisser. ⇒ un compteur `n_hidden`
   **n'a aucun effet de jeu** : proposé, puis **rejeté** sur cette lecture.
3. **`hidden` d'un ennemi est largement redondant** avec le masque d'action, qui encode déjà la
   conséquence (slot de tir à 0). Ne reste que la *cause* explicite — valeur faible. Non retenu.
   **`gone_to_ground_ready` d'un ennemi n'est pas actionnable** pour l'attaquant. Non retenu.
4. ⚠️ **« Les ennemis ne bougent pas pendant mon tour » est FAUX** (relevé par l'utilisateur) :
   `reactive_move` (règle d'unité vive, Termagant) est déclenché par `maybe_resolve_reactive_move`
   depuis `movement_handlers` — une unité adverse bouge donc pendant MA phase de mouvement. Toute
   mémoïsation clée « par tour » est invalide ; c'est la répétition exacte du motif §0.18/§0.26.
   (Le tir en état d'alerte, lui, n'existe pas encore : zéro occurrence d'`overwatch`.)

**Ce qui est livré** : **2 bits par slot ennemi** — `los_can_see` (06.01) et `cover_vs_observer`
(13.08 **exact**), tous deux issus de `compute_unit_los`, la source **autoritative** du moteur,
la même que `_cover_worsened_bs` (résolution du `-1 BS`) et que l'affichage frontend.
`los_can_see` est obligatoire pour lever l'ambiguïté du second (0 = invisible *ou* visible sans
couvert). Émis pour les entités ennemies seulement : ces bits décrivent une PAIRE ; pour l'unité
active, « ai-je le couvert » n'est pas défini sans choisir un tireur — son couvert intrinsèque
reste porté par `in_cover`. `obs_size` **20545 → 20601**.

⚠️ **Une première proposition — un bit intrinsèque « toutes mes figurines dans une terrain area »
— a été ÉCARTÉE, et c'est le point technique de la tranche.** Cette condition n'est qu'**une des
deux** branches alternatives de 13.08 : un bit à 0 aurait signifié « indéterminé », pas « pas de
couvert ». La branche 2 (« not fully visible to the attacking model ») dépend du tireur et est
bien atteignable — vérifié : mur partiel, `can_see=True`, `fully_visible=False`, **`cover=True`
sans aucune terrain area**. Le proxy y répondait 0 et l'agent aurait cru tirer sans malus.
`test_cover_via_partial_visibility_only` verrouille ce cas, et la contre-épreuve par mutation
« remettre le proxy » le fait rougir. ⚠️ Ce test EXIGE un board micro (socle multi-hex) : avec une
figurine sur un seul hex, `fully_visible == can_see` et la branche 2 est structurellement
inatteignable — une première version du test l'ignorait et ne prouvait rien.

**Fiabilité du pair-cache, vérifiée par mesure et non déduite.** `compute_unit_los` est
pair-cachée ; le commentaire de `_cover_worsened_bs` affirmait « pair-cache par
`_unit_move_version` » — **faux, et corrigé** : c'est un dict pur invalidé de façon **ciblée** par
le choke-point `_touch_unit_los` (toute écriture de position, toute perte de figurine), ce qui
couvre `reactive_move` par construction. Le motif §0.18/§0.26 (compteur non bumpé ⇒ cache périmé
servi) a été écarté empiriquement : **23 398 paires comparées au calcul non caché sur 400 steps,
0 divergence**. Surcoût par step non mesurable (sous le bruit sur 300 steps ; 18 paires en cache).

**9 tests** (`test_squad_obs_enemy_cover.py`), contre-épreuves par mutation : couvert éteint →
4 rouges ; proxy branche 1 → 1 rouge (celui de la branche 2). 178 tests verts sur la famille
observation + LoS + cover.


<a id="s0.30"></a>
### 0.30 Encodeur d'entités partagé + tête pointeur — ✅ LIVRÉ (2026-07-26)

> **Entrée sans corps dans ce document — c'est voulu, et c'est signalé ici depuis le 2026-07-28.**
> §0.30 n'a jamais eu de section `### 0.30` : son contenu vit dans
> **[`V11_entity_encoder_pointer.md`](V11_entity_encoder_pointer.md)**, qui en est la source de
> vérité (tranches T-A→T-F, mesures, journal). Ce stub existe pour que les ~10 renvois `§0.30` du
> présent document mènent quelque part — avant l'épuration, ils ne reposaient que sur une ligne du
> tableau d'état, supprimée avec lui.

**Résumé strictement non normatif** (le détail et les chiffres à jour sont dans l'autre document) :
audit demandé après [§9.2.5](V11_phaseA.md#s9.2.5), **6 trous trouvés** — une escouade ennemie invisible ET intirable
(5 slots figés pour 6 escouades mesurées), les types de tir **10.05/10.06** ignorés du gym, une seule
arme (index 0) et une seule cible déclarées au tir (violation **04.01**/**04.02**), heuristique d'arme
de mêlée périmée par P1. Décisions actées : renommage `PISTOL` → `CLOSE_QUARTERS`, **encodeur
d'entité partagé** (unités+armes, amies+ennemies), **K=20 unités / K=10 armes**, **tête pointeur**
pour le ciblage, retrain accepté. Livré le 2026-07-26 (T-A→T-F + §1.9 + audit final) ;
T-H (complétude obs : objectifs + règles d'unité) ✅ 2026-07-27 ; T-G (run `--new`, apprentissage
confirmé) ✅ 2026-07-28.

⚠️ Les tailles citées dans les entrées d'époque (`obs_size` 20166, action 1047 → 1062) ont bougé
depuis : valeurs vérifiées dans le code le **2026-07-28** — `obs_size` = **20626**
(`ObservationBuilder.SQUAD_OBS_SIZE_TARGET`), espace d'action = **1062**
(`macro_intents.TOTAL_ACTION_SIZE`), `GRID_CHANNELS` = **9**.


### 0.28 Conformité tir obscuring (13.10) — soupçon RÉFUTÉ (aucun bug) — ✅ (2026-07-22)

> **Conclusion : AUCUN bug.** Le moteur ne tire PAS à travers une aire occultante. La suspicion
> (utilisateur, replay) a été investiguée à fond ; le verdict a nécessité de mesurer **in-engine sur le
> vrai chemin d'éligibilité**, après une cascade de faux positifs offline (leçon → §0bis).

**Règle (13 Terrain §13.10 + 06.01).** Deux figurines ne sont pas visibles ssi **TOUTE** ligne de vue
entre elles traverse une aire occultante (hors aire occupée par l'une des deux). La LoS se trace **par
figurine** et **depuis n'importe quelle partie du socle** (06.01) : un **bord** de socle peut voir là
où le **centre** est masqué (peek légal).

**Le vrai gate de tir gym** (pipeline squad V11, celui que MaskablePPO emprunte) :
`env.get_action_mask` → `get_squad_action_mask_and_eligible_units` → `build_squad_action_mask` (branche
shoot [`shared_utils.py:8170`](../../engine/phase_handlers/shared_utils.py#L8170)) →
`_model_can_shoot_target` ([`:4722`](../../engine/phase_handlers/shared_utils.py#L4722)) →
`_attacker_model_can_reach_squad` ([`:4515`](../../engine/phase_handlers/shared_utils.py#L4515)) →
`_compute_visibility_with_obscuring`. Ce chemin est **par-figurine, footprint COMPLET, obscuring-aware
(13.10)**. Il n'utilise **PAS** `compute_unit_los`/`valid_target_pool_build` (chemin legacy mono-fig) —
d'où l'échec de mes audits initiaux placés sur le mauvais chemin.

**Preuve (audit LIVE sur le vrai gate).** Instrumentation temporaire au `return True` de
`_model_can_shoot_target`, recalcul indépendant « existe-t-il une ligne socle→socle évitant l'obscuring
(hors aires exclues) ? » sur les footprints réels. Run `--step` : **297 tirs approuvés,
`obscuring_clear_line=False = 0`, `GATE_BUG = 0`**. Le gate n'approuve JAMAIS un tir sans une ligne de
socle qui évite les aires occultantes. Le « tir à travers terrain » vu en replay = **peek légal
par-figurine**.

**Ce qui a été RÉFUTÉ (mes propres faux positifs).** Un scan offline `step.log` centre→centre a
flaggé 7–12 « tirs illégaux » par run ; des rejeux headless successifs ont même « confirmé » 10 puis 3
tirs. **Tous FAUX** : (a) le scan teste des lignes **centre→centre**, alors que la LoS légale est
**footprint→footprint** (un bord voit ce que le centre ne voit pas) ; (b) les rejeux headless étaient
**non fidèles** (1er rejeu : unités restées à `(-1,-1)` car `place()` écrivait `unit["col"]` au lieu de
`units_cache` ; suivants : arme/portée/état divergents du training). Le seul verdict fiable est venu de
l'audit **dans le moteur, sur le vrai gate**, pas d'une reconstruction.

**Livrable conservé.** Fixture d'audit obscuring (aire pleinement interposée, bloque correctement,
`can_see=False`) : commité — `config/board/44x60x5/scenario/scenario_obscuring_fixture.json` +
`terrain/terrain_obscuring_fixture.json`. Réutilisable comme test de non-régression 13.10.

**⚠️ Leçon de méthode (→ §0bis).** Le **premier** rejeu a conclu « 0 bug sur 476 » — **FAUX** : `place()`
poussait `unit["col"/"row"]` alors que `require_unit_position` lit `units_cache` ; les unités restaient
à `(-1,-1)` (non déployées, `deployment_type="active"`), la LoS testait une ligne triviale
`(-1,-1)→(-1,-1)` = visible. Le contrôle « les unités ont-elles vraiment bougé ? » (assert
`require_unit_position == position loggée`) a retourné le verdict. Corollaire du motif §0.11/§0.18 :
**un rejeu vert ne prouve rien s'il ne vérifie pas son propre setup.**


### 0.27 Blocage à l'éval du checkpoint — task d'éval en timeout (parties dégénérées × coût géodésique) — ✅ CORRIGÉ (2026-07-26)

> ✅ **FIX LIVRÉ le 2026-07-26 — options (1) + (2), celles approuvées.** Le diagnostic ci-dessous
> reste valide intégralement ; seul le garde-fou change.
>
> **(1) Timeout ≠ crash.** `evaluate_against_bots` publie désormais **trois** compteurs au lieu
> d'un : `total_failed_episodes` (sémantique historique inchangée : « la mesure n'est pas
> fiable »), `total_timeout_episodes`, `total_error_episodes` (= la différence, source unique).
> Conséquences par site :
> - `training_callbacks.py::_apply_eval_results` (éval INTERMÉDIAIRE) : lève toujours sur
>   `total_error_episodes > 0` (**un crash moteur ne s'absorbe pas**) ; sur timeout seul, imprime
>   `⚠️ Évaluation NON FIABLE`, loggue le compteur TensorBoard `00_critical/0_eval_timeout_episodes`
>   et **sort avant** le gate, la métrique de win-rate, la sauvegarde du best model, l'early
>   stopping et l'historique robuste. Le training continue ; **le point de mesure est ignoré, pas
>   maquillé** — c'est le point clé : un score sur dénominateur tronqué n'alimente AUCUN signal.
> - ⚠️ **PÉRIMÉ au 2026-08-02** : cette puce décrivait le gate de CURRICULUM de `train.py`
>   (`gate_now` exigeant `eval_reliable`). Le curriculum automatique **n'existe plus** — les
>   phases se lancent manuellement, il n'y a plus de transition à garder. Le drapeau
>   `eval_reliable`, dont ce gate était l'unique lecteur, a été **supprimé** (il doublait
>   `total_failed_episodes == 0`). L'éval ignorée est désormais tracée côté callback :
>   `_apply_eval_results` appelle `_mark_unreliable_eval_skip` avant son `return`, ce qui
>   incrémente `gating_skipped_unreliable_count` et pousse une entrée `SKIP_UNRELIABLE` dans
>   `gating_history`. Sans cet appel — jamais câblé jusque-là — les résumés de gating
>   affichaient `skip_unreliable=0` sur un run ayant perdu des évals. Le `marker` reste
>   synchronisé, la garde d'anti-désynchronisation ne se déclenche pas.
> - `train.py` (éval FINALE / eval-only) : **reste strict dans les deux cas** — c'est le score
>   livré, un échantillon tronqué ne se publie pas. Seul le message change : il nomme la cause
>   (crash / timeout / les deux), pour que le diagnostic soit immédiat au lieu d'exiger une
>   nouvelle enquête.
>
> **(2) Éval intermédiaire réduite** : `x5_new.bot_eval_intermediate` **100 → 20** ép./bot
> (5 bots → 100 ép. au lieu de 500, tasks 5× plus courts). `bot_eval_final=100` **inchangé** et
> `bot_eval_task_timeout_seconds=3600` inchangé. Les autres phases ne sont pas touchées.
>
> ⚠️ **CORRECTION 2026-07-28 — le « 20 » n'est PAS ce que porte la config.** Valeurs relevées
> dans `ArmageddonAgent_training_config.json` à HEAD : `x5_new` = **50** (pas 20), `x1` = **100**,
> `x5_append` = 100, `x5_debug` = 100, `x1_debug` = 5 (⏳ **relevé à 1 au 2026-08-02** — profil `x5*`/debug non tenu à jour, relire le JSON). Et §0.14 a **explicitement retiré** la
> proposition de descendre à 20 (20 ép./bot ⇒ ±11 points d'erreur-type sur le win-rate, injectés
> dans `save_best_robust`). Cette ligne est donc conservée comme **trace de l'intention du
> 2026-07-26**, pas comme description de l'état : le paramètre qui a réellement bougé pour le run
> à lancer est `x1.bot_eval_freq` (2000 → 4000), et il est lui-même contredit par une
> modification non commitée du répertoire de travail (cf. l'alerte en §0).
> **MAJ 2026-07-28 soir : tranché dans l'autre sens — 2000 assumé et commité** (encadré 🟢 en §0).
>
> **Verrou** : `tests/unit/ai/test_eval_timeout_resilience.py` (**8** tests au 2026-08-02) —
> crash lève / crash+timeout lève (le crash prime) / timeout ne lève pas et n'atteint pas le
> gate / timeout loggue le compteur mais **jamais** un win-rate / éval propre atteint le gate
> (non-régression) / contrat des 3 compteurs / timeout **tracé** en `SKIP_UNRELIABLE` /
> éval propre ne fabrique **aucune** trace de skip.
> **Contre-épreuve mutation** : garde-fou remis sur `total_failed_episodes` + early-return
> neutralisé → rouges ; appel `_mark_unreliable_eval_skip` retiré → `test_timeout_is_traced_as_a_skipped_gate`
> rouge ; restauré → 8 verts.
>
> ⚠️ **Ce que ce fix NE prouve PAS** : que l'éval s'accélère quand le modèle s'améliore
> (hypothèse de l'option 1, toujours non mesurée). Il garantit seulement que le run **survit**
> à des évals lentes. Si l'éval FINALE heurte le même mur, le reliquat est l'option (3)
> (accélération du géodésique, rouvre §0.22).

> **Bloqueur historique de §0.14 (diagnostic conservé).** Ce n'est ni la perf du pool (§0.22), ni un défaut d'instrument
> (§0.24), ni un hang infini : c'est le **coût par-pas du fix move géodésique (§0.25)** appliqué à des
> parties longues d'un modèle encore nul, qui fait dépasser le timeout d'un task d'éval.

**Reproduction (le run §0.14 lui-même).** À l'épisode 2000, le callback lance l'éval intermédiaire
(`bot_eval_freq=2000`, `bot_eval_intermediate=100` ép./bot × 5 bots pondérés = **500 ép.**). Message
exact d'arrêt :
```
RuntimeError: Bot evaluation failed episodes detected: marker=2000, failed_episodes=500,
duration_seconds=3675.8. Training stops immediately to enforce strict evaluation reliability.
```
`training_callbacks.py:2119` (`_apply_eval_results`) lève dès `total_failed_episodes > 0` (garde-fou
strict de §0.7 : « aucune mesure [§10.6](V11_eval_strategy.md#s10.6) tant qu'un bug plante des épisodes »).

**Mécanisme (mesuré, PAS supposé).**
- Un **task d'éval** = un bot × N épisodes joués **séquentiellement dans un seul env** (sous-process).
  Le collecteur parallèle (`bot_evaluation.py:655-737`) applique un **timeout PAR TASK**
  (`bot_eval_task_timeout_seconds=3600` pour la phase `x5_new`) ; si UN task le dépasse, **tout le pool
  est force-terminé et tous les épisodes pending sont marqués `failed`** (`:716`, `:719-736`). D'où
  `failed_episodes=500` (l'éval a à peine démarré) et `duration≈3600`.
- **Correctif du 2026-08-02 — le chrono partait de la SOUMISSION.** Les tasks étaient TOUTES
  soumises d'un coup et `task_start_times` était rempli pour tous les futures à l'ouverture de la
  collecte, alors que le pool n'en exécute que `bot_eval_n_workers` à la fois :
  `bot_eval_task_timeout_seconds` était donc une deadline **globale** sur toute l'évaluation, pas
  un timeout par task. Signature exacte de l'incident ci-dessus (`failed_episodes=500` avec
  `duration≈3600` : « l'éval a à peine démarré » = les tasks des dernières vagues tuées avant
  d'avoir tourné). La collecte soumet désormais **au fil de l'eau**, au plus `bot_eval_n_workers`
  tasks en vol : il n'existe plus de task en attente dans le pool, donc l'instant de soumission
  EST l'instant de départ. (`future.running()` ne suffisait pas : CPython arme RUNNING quand le
  future part dans la `call_queue`, pas quand un worker le prend — mesuré : 4 futures RUNNING
  pour 2 workers.) Verrous : `tests/unit/ai/test_bot_evaluation_utils.py::test_collect_parallel_results_arms_each_deadline_at_its_own_submission`
  et `::test_collect_parallel_results_reports_tasks_never_submitted_on_abort`.
- **Ce n'est PAS un hang infini** : chaque épisode d'éval est borné par
  `max_steps_per_episode = get_max_turns()×400 = 5×400 = 2000` pas (`bot_evaluation.py:1072`, boucle
  `while not done and step_count < max_steps_per_episode` `:555`). Un épisode s'arrête au cap.
- **C'est de la lenteur** : le modèle à 2000 ép. est à peine entraîné → il produit des **parties
  dégénérées** qui atteignent le cap 2000 pas, et le fix move **géodésique (§0.25)** rend chaque pas
  coûteux (érosion de pool par-figurine, « load-bearing » cf. §0.25). Un task de 100 parties longues
  dépasse l'heure.

**Preuve chiffrée.** Sonde d'éval contrôlée sur le modèle courant (marker ≈2000,
`--eval --training-config x5_new --scenario <holdout> --test-episodes 15`) : **0 épisode d'éval
terminé en 2 min** (`0/90 [00:00]`). À comparer aux **17 s/ép** mesurés sur un autre modèle plus tôt
(12 ép. d'éval en 3 min 21 pendant un `--step`). 100 ép. × ce régime dépasse `bot_eval_task_timeout_seconds`.

**Tension de fond.** Le garde-fou traite un **timeout (lenteur)** comme un **crash (bug)** — or ici il
n'y a aucun bug d'épisode. Et la lenteur = le coût géodésique, i.e. exactement le coût **§0.22** que
l'utilisateur a clos, désormais incontournable puisque la conformité move (§0.25) l'exige.

**Options identifiées (tranchées : (1)+(2) LIVRÉES le 2026-07-26, cf. encadré en tête).**
1. **Distinguer timeout vs crash** dans le garde-fou `_apply_eval_results` : hard-stop uniquement sur
   **exception** d'épisode (vrai bug), pas sur **timeout** (lenteur). Le run continuerait ; les évals
   plus tardives (modèle meilleur → parties courtes → éval rapide) passeraient. Hypothèse à confirmer :
   l'éval s'accélère quand le modèle s'améliore.
2. **Réduire l'éval intermédiaire** (`bot_eval_intermediate` 100 → ~20) : c'est un signal de
   monitoring, pas la mesure [§10.6](V11_eval_strategy.md#s10.6) ; garder `bot_eval_final=100`. ⚠️ mais l'éval FINALE (100 ép.)
   heurtera le même mur si le modèle final produit encore des parties longues.
3. **Accélérer le géodésique** (vectorisation NumPy du champ géodésique, cf. `V11_move_build_acceleration.md`) —
   **rouvre §0.22** (option lourde, en réserve).
4. Baisser le cap `max_turns×400` (change la sémantique de partie — à éviter sans raison règles).

Reco de départ (ne rouvre pas §0.22) : (1) + (2). ⚠️ Prérequis : vérifier sur un marker plus avancé
que l'éval s'accélère réellement, sinon (3) devient nécessaire.


### 0.22 Coût du move pool — `MOVE_POOL_BUILD` = 95,6 % du training — ✅ CLOS (2026-07-21, décision (B) STOP à L1+L_bbox)

> **⚠️ MAJ 2026-07-21 — CE QUI SUIT DANS CETTE SECTION EST EN PARTIE SUPERSEDED.** Le profil interne
> a depuis été re-mesuré sur le **vrai board 220×300** et toutes les cardinalités décisives sont
> connues (`reach`/board ≤ 16,6 %, `|walls|`≈435-988, `|occupied|`≈1900/build, `|obstacles|`≈2400-3000).
> **Conclusion tranchée : le facteur dominant est la SURFACE, pas numba.** `_dilate_by_kernel` est
> O(|offsets|×board) *indépendant de la densité* → le levier optimal est **borner les dilatations à la
> bbox `move_range`** (pur NumPy, exact, inconditionnel, **sans dépendance**). Minkowski, cache-murs et
> numba-dense sont **caducs** ; numba n'est en jeu que pour le reliquat BFS des petits socles, **à
> bencher d'abord contre un wavefront bbox-NumPy**. Le « chantier cache » décrit plus bas est **réfuté
> (0 %)** et le cProfile 60×80 ci-dessous est remplacé par le profil 220×300.
> **➜ Source de vérité désormais : [`V11_move_build_acceleration.md`](V11_move_build_acceleration.md)
> (`V11_move_build_acceleration.md` : §2 profil réel, §2bis mesures + verdict, §8 ordre L1→L_bbox→re-bench→BFS).**

**Constat chiffré (bench x5 du 2026-07-21, `perf_timing_bench_x5.log.score.json`).**
`MOVE_POOL_BUILD` : **374 390 appels, 17,49 ms/appel, somme 6548,7 s sur 6848,6 s de temps
instrumenté = 95,6 %**. Le BFS seul y pèse `bfs=12,13 ms/appel` (**69 %** du build) ; `prep`/`post`
le reste. `CHARGE_DEST_BFS` (86,9 s) et `CHARGE_PHASE_START` (213 s) sont marginaux. **Le coût d'un
run x5 est, à 95 %, la construction du pool de destinations de move.**

**Outillage — `scripts/profile_move_pool.py` était CASSÉ, réparé (2026-07-21).** Il ne tournait plus
depuis la migration squad (§0.12) : `build_units_cache`/`_build_models_for_unit` exigent désormais
une datasheet complète (`VALUE`, `HP_MAX`, `OC`, `T`, `ARMOR_SAVE`, `INVUL_SAVE`, `SHOOT_LEFT`,
`ATTACK_LEFT`, `RNG_WEAPONS`, `CC_WEAPONS`, `UNIT_RULES`), et le chemin exige `move` (minuscule),
`config["move"]` (règles de traversée), `inches_to_subhex` et `gym_training_mode`. Ajoutés : bloc
`datasheet_defaults` sur chaque unité, section `move` **alignée sur `config/game_config.json`**, flag
`--resolution` (défaut 5), et bascule `gym_training_mode=True` (on profile le chemin **training**,
métrique `move_gym=hex`, celui qui domine). ✅ Tourne à toute résolution.

**Diagnostic cProfile (config cachée après warmup ; board 60×80 SYNTHÉTIQUE — ⚠️ PAS le board de
référence, qui est `config/board/44x60x5` = 220×300 subhex ; move 12, base 5, ez 12, res 5, 300
itérations, tri `tottime`).** Proportions à re-mesurer sur 220×300, cf.
[`Implémenté/V11_move_pool_optimization.md`](Implémenté/V11_move_pool_optimization.md) (archivé, clos).

| Fonction | Part | Note |
|---|---|---|
| `_build_multi_hex_vectorized` ([movement_handlers.py:1523](../../engine/phase_handlers/movement_handlers.py#L1523)) | **~68 %** du build (interne + noyaux) | BFS/disque vectorisé NumPy. Le vrai goulot. |
| `_dilate_by_kernel` / `_spread_by_kernel` | inclus ci-dessus | dilatations par slices, appelées plusieurs fois/build |
| `_hex_center` + `math.sqrt` | ~10 % | **752 appels/build**, dans les footprints |
| footprints (`_footprint_round/_square`) | faible | **PAS** le goulot : `precompute_footprint_offsets` existe déjà, ~6 appels/build |

⚠️ **La config n'est PAS le goulot** : après warmup, `get_game_config` est cachée (le profil froid
montrait un `_io.open` par appel, disparu à chaud). Ne pas partir sur cette fausse piste.

**Chantier proposé — 🔴 RÉFUTÉ (mesuré 0 %, cf. MAJ en tête de §0.22).** *Historique conservé pour
traçabilité, NE PAS engager.* Cacher entre
appels ce qui ne dépend que de (dims plateau × forme de socle) et non de l'état mobile :
`col_parity_mask`, `off_even_arr`/`off_odd_arr`, et les masques de bornes/parité
(`_bounds_bad_parity`), aujourd'hui réalloués/recalculés à **chacun** des 374 k appels. Exige :
(1) une clé de cache correcte, (2) une **invalidation** sûre, (3) des **tests d'équivalence stricte
de pool** (l'invariant du docstring de `_build_multi_hex_vectorized` : équivalence exacte avec le BFS
Python d'origine), (4) un **re-bench**. Ce n'est pas un edit isolé — c'est un cycle moteur dédié.
Aucune ligne de `_build_multi_hex_vectorized` n'a été modifiée.

**Arbitrage TRANCHÉ (2026-07-21).** L'utilisateur a décidé : **on optimise**, à condition explicite
que « le gain de performance ne se fasse pas au détriment du métier et du PvP ». Le chantier (objectif,
garde-fou d'équivalence stricte, exigences cache/invalidation/tests, non-régression PvP, plan par
étapes, Definition of Done) est **cadré dans un document dédié** :
➜ garde-fous/cadrage **[`V11_move_pool_optimization.md`](Implémenté/V11_move_pool_optimization.md)** (archivé, clos) ; **mesures +
plan d'implémentation à jour [`V11_move_build_acceleration.md`](V11_move_build_acceleration.md)**. Code
toujours **non commencé** (aucune ligne de `_build_multi_hex_vectorized` modifiée) ; cardinalités
mesurées, levier tranché (bbox NumPy). ~~Prochaine action : L1 → L_bbox (cf. §8 de `V11_move_build_acceleration.md`).~~
**L1 + L_bbox faits le 2026-07-21** (cf. `V11_move_build_acceleration.md §3.1`). L1 :
`precompute_footprint_offsets` mémoïsée. L_bbox : dilatations de `_build_multi_hex_vectorized`
fenêtrées sur la bbox `start ± (move_range + max|offset|)` du chemin ground (variante (b), pur NumPy ;
FLY exclu). Garde-fous : oracle + snapshot ovale + **A/B fenêtré==plein-board** (7 cas) + suite
complète verte. **Gain A/B (220×300, gym hex)** : ovale [20,14] 1,49×, round 10 1,78×, round 3 1,13×
(pool strictement identique) — gain croissant avec la taille du socle. **Étape 4 (BFS wavefront)
BENCHÉE ET RÉFUTÉE** : prototype prouvé équivalent mais **plus lent à move_range=12** (le régime réel du
training, mesuré) ; le BFS deque n'y coûte que 0,30 ms. **Nouveau hotspot mesuré (cProfile ez=2)** : la
boucle Python sur les ~200 offsets de `_dilate`/`_spread` (ovale, ~60 % du build). **L2b (runs NumPy pur)
prototypé et jugé insuffisant** : par lignes réfuté (ovale non contigu), par colonnes 1,34× ovale mais
<1× petits socles + complexité (sparse-table). **Décision de périmètre en attente utilisateur** : (A)
numba (gain franc, risque segfault/dépendance) / (B) STOP et lancer le run §0.14 (L1+L_bbox = 1,49×
acquis) / (C) L2b-colonnes bbox-restreint (NumPy pur, ~3× ovale visé, complexe) — cf.
`V11_move_build_acceleration.md §3`.


### 0.23 Logger per-figurine `[MODELS:]` + fix `PNone` — ✅ CLOS (2026-07-22)

**Constat.** Le step logger (`ai/step_logger.py`) et l'analyzer raisonnaient en **ancre d'escouade**
(« une unité = un point »), modèle pré-squad. Un step.log de vrai run (rosters SM/Orks) montrait une
**seule ligne par escouade à l'ancre** (ex. `Unit 1(172,122) ADVANCED from … to …`) alors qu'une
escouade compte jusqu'à 12 figurines aux positions distinctes → l'analyzer, en aval, faisait des
BFS/distance/adjacence/LoS **ancre-à-ancre** = faux positifs en masse (cf. §0.24). Bug distinct
constaté sur le même log : des lignes `E1 T1 **PNone** SHOOT : … WAIT` (champ joueur = `None`).

**T0 — fix `PNone` (root cause).** Le payload WAIT (`engine/phase_handlers/generic_handlers.py`,
`end_activation`, branche `arg1=="WAIT"`) **n'incluait pas la clé `"player"`** (contrairement au
payload move `movement_handlers.py:3929`) → au flush, `raw_log.get("player")` renvoyait `None` →
rendu littéral `PNone`, et le regex maître de l'analyzer (`P(\d+)`) **rejetait ces lignes**
silencieusement (WAIT jamais comptés). Correctif : ajout de `"player": require_key(unit, "player")`
au payload WAIT. Au passage, suppression d'un **ré-import local** `from shared.data_validation import
require_key` (dans la même fonction) qui rendait `require_key` variable locale → `UnboundLocalError`
sur la ligne ajoutée (piège Python : un import local dans une fonction masque le symbole module-level
sur TOUTE la fonction). Test `tests/unit/engine/test_generic_handlers.py` mis au contrat (`unit` porte
`player`, le wait-log l'expose) ; 32 tests logger verts.

**T1 — segment per-figurine, injection unique dans le flush.** Le message d'action vu par l'analyzer
en **training** n'est PAS construit par les handlers moteur mais par `ai/step_logger.py`
(`_format_replay_style_message`), alimenté par le flush `w40k_core.py._flush_squad_action_logs_to_step_logger`
via `_build_step_log_details` / `_build_shot_details`. Le vrai appender du move training est
`w40k_core.py:5266` (après `execute_squad_move`), à l'ancre seule (aucune donnée per-figurine). Plutôt
que plomber ~12 sites, **injection centralisée** : nouveau helper `_models_segment_for_unit(unit_id)`
(lit `units_cache[unit_id]["occupied_hexes_by_model"]`, source de vérité per-socle resynchronisée par
`commit_move`), appelé dans `_build_step_log_details` ET `_build_shot_details`, qui posent
`details["models_segment"]` ; `step_logger.log_action` **appende ce segment une seule fois** après le
formatage du message. Format : `[MODELS: <unit>#<idx>@(col,row) …]` en fin de message (avant
`[SUCCESS]`), **rétro-compatible** (l'ancre en tête reste ; `re.match` prefix des parseurs existants +
`replay_converter.py` non cassés). Helpers `format_models_segment` / `models_segment_from_move_details`
/ `models_segment_from_cache` ajoutés à `engine/action_log_utils.py`. Le per-figurine est une INFO de
log (jamais un chemin de règle) → segment vide si l'unité n'a pas de cache exploitable, pas de crash.

**Vérifié sur log frais** (`--step` sur ArmageddonAgent) : **100 % des lignes d'action portent
`[MODELS:]`** (2163 puis 2306 lignes selon le run), `PNone = 0`, les escouades apparaissent enfin
telles quelles (unité 1 = 12 socles `1#0`…`1#11`, socles morts absents de la liste). Fichiers :
`engine/phase_handlers/generic_handlers.py`, `engine/action_log_utils.py`, `engine/w40k_core.py`,
`ai/step_logger.py`, `tests/unit/engine/test_generic_handlers.py`.

### 0.24 Analyzer réaligné per-figurine (parsing/comptage/géométrie/données) — ✅ RÉSOLU (2026-07-22) ; résiduel FP documenté

**Motivation.** L'analyzer (`ai/analyzer.py` ~184 Ko + `ai/analyzer_phases/*`, `ai/analyzer_core.py`)
est l'UNIQUE instrument de validation du training (CLAUDE.md : « --step + analyzer.py + replay »).
Tant qu'il raisonne à l'ancre, il ne peut ni détecter un vrai bug règles, ni être cru quand il en
signale — il était donc **impossible d'affirmer que le training n'apprenait pas des coups illégaux**.
Baseline sur un log frais per-figurine (`step_fresh_ref.log`, 2545 lignes, analyzer encore ancre) :
**1809 « erreurs »**, dont advance path blocked 297, fight non-adjacent 442, attacks over CC_NB 146,
shots over RNG_NB 85, advance>roll 61, + 367 « parsing errors ».

**Trois classes de défaut (les 3 corrigées).**
- **Classe A — géométrie ancre.** BFS `_bfs_shortest_path_length` (point-à-point), move/advance path
  blocked, distance>roll, out_of_range/adjacent, fight non-adjacent, LoS — tous ancre-à-ancre.
  Corrigé en **per-socle** : nouveau module `ai/analyzer_perfig.py` (parse `[MODELS:]`, empreintes de
  socle via helpers moteur `compute_occupied_hexes`/`min_distance_between_sets`, distance bord-à-bord
  escouade↔escouade) ; état `positions_by_model` maintenu **frame-à-frame** dans `analyzer_core.py`
  (`ai/analyzer_state.py` : champs `positions_by_model`, `current_line_models`, `unit_base`) ; BFS de
  move/advance par-socle (origine = ligne N-1, dest = `[MODELS:]` de la ligne N), portée/adjacence
  bord-à-bord, gestion **FLY** (les FLY franchissent murs/figurines → exclus du contournement,
  `move_handler.py:211-213`, `shoot_handler.py:873`).
- **Classe B — comptage.** `Shots over RNG_NB` / `Attacks over CC_NB` comparaient les jets **agrégés de
  toute l'escouade** au NB d'**un seul** modèle → dépassement mécanique. Corrigé : plafond ×(nb de
  socles vivants sur la ligne `[MODELS:]`) ; profil composite `A / B` → NB = max des composantes.
- **Classe C — données manquantes** (les « 367 parsing errors » n'en étaient pas) :
  `Weapon 'Shoota / Kustom Shoota' missing RNG_NB for Boyz` (×36), `Crozius Arcanum missing CC_NB for
  VanguardVeteranSquadJumpPack` (×30), `Engagement check missing unit data for unit_id: 1` (×47).
  Corrigé : `ai/analyzer_config.py` agrège les cartes arme→NB/portée sur **tous** les model-types
  (escouades hétérogènes) ; résolveur d'arme avec split `" / "` ; résurrection dans `analyzer_core.py`
  des unités faussement tuées par le modèle d'ancre 1-HP.

**DEUX vrais bugs analyzer trouvés et corrigés** (audit indépendant contre la config moteur — ce
sont eux qui supprimaient ~503 FP, PAS de la permissivité) :
- `_get_engagement_zone_for_analyzer` lisait **2 (pouces)** au lieu de **10 subhex**
  (`engagement_zone=2` pouces × `inches_to_subhex=5`, scalé au chargement `w40k_core` ; le moteur
  `get_engagement_zone` renvoie 10). C'était la root cause des 442 « fight from non-adjacent ».
- Budget **Advance** = jet seul au lieu de **MOVE + jet** (règle 09.02). Root cause des 61 « advance>roll ».

**Résultat (log réf, vérifié indépendamment)** : **1809 → 319**, parsing/shots/attacks/advance-dist/tirs
= **0**, path-blocked réduit (le résiduel = **vrai bug moteur §0.25**), fight non-adjacent 442 → 12
(FP off-by-1). `pytest -k analyzer` : **39 passed** (28 existants + 11 nouveaux dont
`tests/unit/ai/test_analyzer_perfig.py`).

**⚠️ Résiduel NON traité (non bloquant).** Le suivi **HP/mort de la CIBLE** n'est pas encore
per-figurine (les lignes FIGHT ne relistent que l'attaquant dans `[MODELS:]`) → **FP « Fight a dead
unit »** : 174 sur le log réf, **prouvés FP** (Unit 104 tracée dans l'épisode 2 : 6 socles à T2,
riposte à T4, combat encore à T5 = bien vivante, pas un mort frappé). Idem « Shoot at dead unit » (9)
et les off-by-1 fight (12) / advance (1). ➜ Pour un analyzer à **0** propre, il reste à porter le
suivi HP/mort et l'empreinte cible en per-figurine (émettre aussi les socles du défenseur). C'est de
la **sur-détection** de l'analyzer (il sur-signale), **jamais** une triche moteur.

### 0.25 Bug moteur : budget de move per-figurine mesuré en ligne droite, pas en trajet contournant les murs — ✅ CORRIGÉ (2026-07-22, géodésique)

**Découverte.** Une fois l'analyzer fiable (§0.24), son résiduel « path blocked » sur unités
**NON-FLY** (Gretchin/Intercessor/Boyz, FLY correctement exclus) s'est avéré être un **VRAI bug
moteur**, confirmé par lecture de code (pas inféré) :
- `explain_move_plan_rejection` (`engine/phase_handlers/shared_utils.py:3473`) validait le budget
  par-figurine avec `dist = calculate_hex_distance(origine, dest)` = **distance à vol d'oiseau** ; les
  murs ne bloquaient que la **case d'arrivée** (`blocked_by_level`), jamais le trajet.
- Or le modèle de mouvement du moteur traite les murs comme **infranchissables en transit** : le pool
  de move réactif fait un BFS qui saute les murs (`shared_utils.py:2111` `if neighbor in wall_set:
  continue`, distance = pas BFS).
- `build_rigid_plan` translate tout le bloc du **même vecteur cube** → chaque figurine a la même
  distance à vol d'oiseau que l'ancre (le check ligne-droite passe **toujours**), mais une sœur
  derrière un mur a un trajet légal (contournement) qui **dépasse le budget**. Dette connue T6-g
  (« pool BFS validé sur l'ancre, pas le bloc »), désormais **chiffrée : 111 figurine-moves illégaux /
  3 épisodes** sur le log réf.

**Décision utilisateur** : fix **validation-only** (léger) plutôt que refonte du pool, run **après** le fix.

**Fix livré (par un agent, root cause exacte + harnais).** Root cause raffinée : le pool/masque
validait déjà le BLOC pour les prédicats de CELLULE (murs/occupation/ER via
`erode_move_pool_by_squad_block`, T6-g) mais **pas pour le budget** (supposé « invariant par
translation rigide » — faux pour la distance de CHEMIN). Changements dans
`engine/phase_handlers/shared_utils.py` : helpers `build_move_transit_blocked` (obstacles de transit,
parité exacte avec le pool) + `geodesic_move_reach` (BFS géodésique borné au budget) ; le check budget
par-figurine (validation + exécution) passe de la ligne droite au **BFS géodésique** pour les
non-FLY (FLY et euclidien PvP conservés) ; **érosion** du pool étendue au même prédicat géodésique
(sinon l'invariant masque⊆exécutable casse : le masque offrirait une ancre que la validation rejette).

**Perf — nuance importante.** Valider UN plan (une escouade, BFS borné) est peu coûteux ; c'est
l'**érosion géodésique du pool** (par-figurine sur les cellules du masque) qui est chère = exactement
le coût **§0.22**. L'agent l'a signalée « **load-bearing** » (la désactiver `GEO_OFF` crashe
immédiatement, validation et érosion sont couplées). En training 48-envs elle est **net-gagnante**
grâce à une mémoïsation (cf. §0.26). **Mais elle refait surface en éval mono-env → §0.27.**

**Validé** (après le correctif de régression §0.26) : path-blocked **111 → ~1** (off-by-1 FP
analyzer : le BFS analyzer bloque aussi les figurines AMIES en transit, que le moteur traverse via
`can_move_through_friendly_model=true` — c'est l'analyzer qui est légèrement trop strict, pas le
moteur) ; tests `tests/unit/engine/test_move_budget_geodesic.py` (8) + `test_move_pool_block_erosion`
(6) + `test_move_mask_is_executable` verts ; **run réel 48-envs franchit 2000 ép. sans crash**.

<a id="s0.26"></a>
### 0.26 Régression `incohérence masque/exécution` sur advance (cache de masque périmé) — ✅ CORRIGÉ (2026-07-22, clé fingerprint)

**Symptôme.** Le premier vrai run après le fix §0.25 a **crashé en ~1 min** (rollout 48-envs) :
```
ValueError: execute_squad_move a échoué : squad=4 type=advance dest=(163,204) —
figurine 4#0 en (163,204) sur cellule interdite : occupation d'une autre escouade
(incohérence masque/exécution)   [w40k_core.py:5268]
```
Le `--step` de 4 épisodes (mono-env) du fix §0.25 **n'avait rien vu** — crash trajectoire-dépendant
(re-cf. leçon §0bis « un run vert ne prouve rien », piège §0.18).

**Root cause (PAS l'érosion, contrairement à l'hypothèse initiale).** La **mémoïsation** ajoutée au
fix §0.25 pour la perf (`build_squad_move_cell_map`, clée sur le compteur `_unit_move_version`) a un
**bypass** : certaines écritures d'occupation (fenêtre de batch LoS / écriture directe) ne **bumpent
pas** ce compteur → une carte de masque **périmée** est servie → une cellule désormais occupée par une
autre escouade est encore offerte comme destination d'advance → `execute_squad_move` lève l'invariant.
Le pool à froid, lui, excluait toujours les cellules occupées : le bug était **purement le cache**.

**Fix.** Clé de cache = **fingerprint LU de l'état réel** (positions+empreintes de toutes les unités =
occupation+ennemis, bloc de l'escouade, régime de budget), **immunisé au bypass du compteur**. Sûr par
construction.

**Harnais (leçon §0.18 appliquée : preuve déterministe > run vert).** Test
`test_cell_map_cache_invalidates_on_occupation_change_without_version_bump` **reproduit
déterministiquement** la condition exacte du crash (occuper une cellule offerte SANS bumper le
compteur, redemander la carte) : l'ancien cache servirait le périmé, le nouveau s'invalide. Test
`test_advance_block_overlapping_another_squad_is_eroded_not_crashed` ajouté. **Vérif indépendante par
l'appelant** : tous les tests moteur verts, `--step` 0 crash, et surtout **le vrai run 48-envs a
franchi la zone de crash (épisode ~1 → 2000) sans une seule `incohérence masque`** avant d'être arrêté
par §0.27. Fichiers : `engine/phase_handlers/shared_utils.py` + `test_move_budget_geodesic.py`.

### 0.-1 🟢 PÉRIMÈTRE ET BASELINE (2026-07-19 soir) — LIRE AVANT TOUT

**Règle de périmètre (décision utilisateur 2026-07-19)** : on ne s'occupe **QUE** de
`config/agents/ArmageddonAgent`. `config/agents/CoreAgent` est **hors périmètre** — ne rien y
lire, ni y écrire, ni s'en servir comme référence.

⚠️ **Chiffre daté du 2026-07-19** — la suite a grossi depuis (+6 tests le 2026-07-20 : 4 en
§0.10, 2 en §0.13). **Ne pas traiter `1402` comme un compte à retrouver** : le reporter du
projet n'imprime pas la ligne de résumé de pytest, le seul verdict disponible est le **code de
sortie** (`exit 0`, vérifié après chaque lot du 2026-07-20).

**La suite est VERTE : `1402 passed, 2 skipped, 0 failed`.** C'est la nouvelle baseline. Toute
mention ailleurs dans ce document de « 9 échecs préexistants » est **PÉRIMÉE** : ces 9 échecs
venaient de l'ancienne banque CoreAgent, retirée le 2026-07-19.

⚠️ **Il n'y a plus d'échec « préexistant » à tolérer.** Un test rouge est désormais une
régression, sans exception.

**Ce qui a été fait pour y arriver** : la suppression de la banque CoreAgent a emporté
`CoreAgent_training_config.json`, utilisé comme **fixture** par 9 fichiers de tests **moteur**
(et non comme « l'agent CoreAgent ») — la suite est passée de 9 à **41** échecs, dont les 3 tests
de `test_move_mask_is_executable.py` qui gardent l'invariant « masque ⊆ exécutable ». Les 8
fichiers ont été **repointés sur `ArmageddonAgent`** (clé d'agent + `rewards_config` + scénario) :

| Fichier | Changement |
|---|---|
| `test_move_mask_is_executable.py`, `test_deployment_per_model_commit.py`, `test_deploy_pool_terrain_zones.py`, `test_deployment_clearance_parity.py` | scénario → `scenarios/training/scenario_training_armageddon.json` |
| `test_squad_fight_v11_state.py`, `test_squad_fight_target_parity.py`, `test_t5_bare_loop.py` | clé d'agent seule (ils fabriquent leur scénario) |
| `test_scenario_bank_migration_v11.py` | les tests du **script** de migration sont conservés ; la partie « banque » vise désormais la banque ArmageddonAgent (**5** scénarios : 1 training + 4 holdout, au lieu de 61) et l'échantillon chargé de bout en bout a été réécrit |

**Effet de bord bénéfique** : les 5 tests de déploiement qui faisaient partie des « 9
préexistants » sont **maintenant verts** — ils échouaient sur les rosters manquants, et
`ArmageddonAgent` les résout.

**9e fichier repointé — `test_board_ref_resolver.py`** : son `BANK_SCEN` pointait sur
`CoreAgent/scenarios/training/scenario_training_bot-01.json`, **supprimé du disque**. Ses 8 tests
restaient VERTS parce que `_resolve_board_dir` ([game_state.py:1630](../../engine/game_state.py#L1630))
ne fait que **parser le chemin comme une chaîne**, sans jamais ouvrir le fichier. Les tests ne sont
pas creux (la logique du resolver est réellement exercée) mais la fixture était **mensongère** :
le jour où quelqu'un ajoute un `is_file()` dans le resolver, 8 tests tombent pour une mauvaise
raison. Repointé sur `ArmageddonAgent/scenarios/training/scenario_training_armageddon.json`.

⚠️ **10 fichiers de tests contiennent encore la chaîne `CoreAgent` et sont VERTS — c'est
normal.** Audités **un par un** (et non par échantillon — la première vérification avait manqué
`test_board_ref_resolver.py` ci-dessus en généralisant depuis 3 fichiers de `tests/unit/ai/`
alors que le seul cas fautif était dans `tests/unit/engine/`) : ce sont des chaînes passées à des
fonctions **pures** (`_load_bot_eval_params`, `build_agent_model_path`, `_scenario_name_from_file`),
des stubs (`SimpleNamespace`, `_DummyCfgLoader`, `_Cfg`), des arborescences **synthétiques dans
`tmp_path`**, ou de simples commentaires. **Aucun n'atteint la vraie config.** Ne pas les
« corriger » par un `sed` global.

**Leçon de méthode** : « vérifié un par un » sur un échantillon n'est pas une vérification.
Le seul contre-exemple était dans le répertoire non échantillonné.


<a id="s0.0"></a>
### 0.0 Ce qu'il faut faire ENSUITE, dans cet ordre (session du 2026-07-19 soir)

**L'ordre est imposé** : le fix moteur T6-i vient de bouger deux fois (branchement déplacé), donc
il doit être verrouillé par un test AVANT qu'un chantier indépendant y touche.

| # | Tâche | État |
|---|---|---|
| 1 | **Test de non-régression 03.03** ([§8](V11_tranches.md#s8) : « une règle = son fichier de tests ») | ✅ FAIT — `tests/unit/engine/test_end_of_turn_coherency_03_03.py`, 11 tests. (a) retour en coherency après la fin de tour ; (b) retrait **une à une**, minimal, et **jamais la dernière figurine** ; (c) `reason='coherency_removal'` (spy sur `destroy_model`) + aucun compteur de kills touché ; (d) **les DEUX chemins** paramétrés (`_fight_phase_complete` ET `_fight_v11_phase_complete`), plus un test que l'étape précède le test de limite de tour. **Mutation-testé** : neutraliser les deux appels rend 4 tests rouges. |
| 2 | **Portage `CC_DMG`/`RNG_DMG` des bots vers le système multi-armes** | ✅ FAIT — 7 sites d'`ai/evaluation_bots.py` portés sur `get_max_ranged_damage`/`get_max_melee_damage`. Voir §0.3 (attribution corrigée). |
| 3 | **Code mort : `_advance_to_next_player`** | ✅ FAIT — supprimé, avec ses **8** tests **et** l'îlot mort qu'il maintenait en vie. Voir §0.4. |

**Éval relancée le 2026-07-19 après le portage — ✅ 60/60 épisodes, voir §0.7.** Elle valide le
portage `CC_DMG` sur les 6 sites `TacticalBot` et **lève** le « [§10.5](V11_eval_strategy.md#s10.5) non validé runtime ». Elle a
aussi établi que le motif d'exclusion du holdout écrit en [§10.5](V11_eval_strategy.md#s10.5) était **empiriquement faux**
(`TacticalBot` n'est PAS le bot le plus fort : 0.60, 2ᵉ meilleur score) — corrigé sur place.
Les tâches 1-3 sont commitées (`6a7a9de1`).

**Reste ouvert** :
- ~~🔴 **Déséquilibre 824 vs 690 points** (§0.6)~~ ✅ **SOLDÉ (§0.9, 2026-07-20)** : il n'y avait
  pas de déséquilibre de listes. Aux points Munitorum, **680 vs 680**. Le +19 % venait de 3 `VALUE`
  fausses (`WarTrakk` 175 au lieu de 60 à elle seule +115). Le critère [§10.6](V11_eval_strategy.md#s10.6) n'est plus bloqué.
- ~~🔴 **`--scenario bot` entraîne sur le holdout** pour cet agent (§0.10)~~ ✅ **CORRIGÉ
  (2026-07-20)** : `bot`/`self` restreints à `training/`, +4 tests de non-régression.
> ➜ **Déplacé en §0.14 (ouvert).** Rien n'a été supprimé : le contenu est intégral là-bas.
- ⚠️ **Le modèle en place a été ÉCRASÉ par ce run** (`model_ArmageddonAgent.zip`, 2026-07-20
  02:14 — autorisation utilisateur explicite). C'est donc un modèle **de debug, 100 épisodes
  `--new`**, sans valeur de jeu : `save_best_robust: false` fait que `train.py` écrit le modèle
  final en fin de run, aux deux sites gardés par `if not save_best_robust`.
  ⚠️ Tout run de debug ultérieur écrasera à nouveau le modèle canonique : sauvegarder avant
  si le modèle en place compte.
> ➜ **Déplacé en §0.16 (ouvert).** Rien n'a été supprimé : le contenu est intégral là-bas.
- ~~Dette `ai/game_replay_logger.py` (~8 sites `RNG_DMG`/`CC_DMG`) + `config/unit_definitions.json`.~~
  ✅ **soldée (§0.8)** : module supprimé, pas porté.
- ~~Purge de `multi_agent_trainer.py` / `--orchestrate`~~ ✅ **faite (§0.8)**, module supprimé.
- ~~Bug d'affichage `Total: 30` au lieu de 60~~ ✅ corrigé (§0.7, constat 2).

**⚠️ L'état de fin de session n'est ni « OK » ni « optimal ».** Mise à jour 2026-07-19 (fin de
session tâches 1-3) : suite toujours verte, **exit 0 sur 1407 tests collectés** (1404 + 11 nouveaux
− 8 supprimés). ⚠️ Le compte exact « passed/skipped » n'est **pas** vérifiable ici : le reporter du
projet n'imprime pas la ligne de résumé de pytest — le seul verdict disponible est le code de
sortie. Ne pas recopier un « N passed » sans l'avoir vu.

Constat d'origine — ce qui était solide : suite verte
scellée par un run (`1402 passed, 2 skipped`), fix 03.03 livré et vérifié bout-en-bout, fail-fast
de l'éval, tests repointés, doc à jour. Ce qui ne l'est pas — **les 6 dettes ouvertes** :

| # | Dette ouverte | Pourquoi ça compte |
|---|---|---|
| 1 | ~~**Test 03.03 non écrit**~~ ✅ **FERMÉE** | Verrouillée par `test_end_of_turn_coherency_03_03.py` (11 tests, mutation-testés). |
| 2 | ~~**`CC_DMG` plante 2 épisodes sur 48**~~ ✅ **PORTÉ** — mais **non re-mesuré** | Le code ne lit plus les champs supprimés ; le run `--eval` qui prouve 48/48 **reste à faire**. Ne pas cocher [§10.6](V11_eval_strategy.md#s10.6) avant. |
| 3 | ~~**`_advance_to_next_player` toujours présent**~~ ✅ **SUPPRIMÉ** | Cf. §0.4. |
| 4 | ~~**Déséquilibre 824 vs 690 points** (Orks/SM, +19 %)~~ ✅ **SOLDÉ (§0.9)** | Artefact de 3 `VALUE` fausses, pas un déséquilibre de listes. Points Munitorum : **680 vs 680**. [§10.6](V11_eval_strategy.md#s10.6) débloqué. |
| 5 | **Rien n'est commité** | ➜ **Déplacé en §0.17 (ouvert)** — cette dette est périssable, son état à jour est en §0.17. |

| 6 | ~~🔴 **Le reward de combat ignore la `VALUE` par figurine**~~ | ➜ ✅ **FERMÉE le 2026-07-20 — voir §0.12** (A/B/C **+ D** livrés, 14 tests mutation-testés, suite 1417 verte). |

**⚠️ Réserve de méthode sur ce document.** Les sections §0.x reflètent ce qui a été relu et
exécuté pendant la session du 2026-07-19 soir. **Le reste du document — T1 à T5, section 9 — n'a
PAS été revérifié ligne à ligne contre le code.** Trois affirmations périmées y ont été trouvées
et corrigées ce soir-là (« prochain bloqueur [§10.4](V11_eval_strategy.md#s10.4) » alors qu'il était résolu, « archivage des
holdouts à faire » alors qu'il l'était, « 9 échecs préexistants » alors que la suite est verte) —
**il peut en rester d'autres du même genre**. Vérifier dans le code avant de s'appuyer sur une
affirmation de ce document qui n'est pas datée de la session en cours.


### 0.1 T6-i — REGAINING COHERENCY (03.03) — ✅ FAIT (2026-07-19 soir)

**Root cause d'une classe entière de crashes `incohérence masque/exécution`.** Mesuré :
8 épisodes plantés → **2**, et l'erreur a **totalement disparu** de l'éval `ArmageddonAgent`.

Enchaînement, chaque maillon vérifié :

1. Des figurines meurent → la formation devient incohérente. **C'est légal pendant le tour**
   (03.03 n'impose la coherency qu'au *set up* et à la *fin d'un move*).
2. L'étape End of Turn qui doit résorber cet état n'était **jamais exécutée** :
   `end_of_turn_coherency_removal` (shared_utils) était implémentée et conforme, avec **zéro
   appelant**. L'incohérence survivait donc au tour.
3. Phase de mouvement suivante : `build_rigid_plan` translate le bloc rigidement, ce qui
   **préserve** l'incohérence.
4. `validate_move_plan` rejette le plan — à raison (03.03 « must end any kind of move in
   coherency »).
5. Le pool BFS du masque, construit sur l'**ancre** et sans check de coherency, offre pourtant
   toutes les destinations. Aucune n'est exécutable → `incohérence masque/exécution`.

**⚠️ Corollaire — une affirmation de ce document était fausse.** L'ancien §0 affirmait que
`require_coherency` est « invariante par translation cube, donc déjà garantie par le pool
d'ancre ». L'invariance est réelle mais **conditionnelle** : elle prouve *si l'origine est
cohérente, le plan l'est*. Elle ne prouve **rien** quand l'origine est déjà incohérente — et dans
ce cas le pool entier est offert alors que rien n'est exécutable. C'est cette demi-vérité qui a
laissé le trou ouvert après T6-g. **Toute contrainte « prouvée invariante » doit être relue en se
demandant : invariante à partir de quel état initial ?**

**Où l'étape est branchée, et pourquoi pas ailleurs** : en tête des **deux** chemins de fin de
Fight (`_fight_v11_phase_complete` et `_fight_phase_complete`, tous deux vivants), **avant** le
test de limite de tour pour que l'état final de la partie respecte aussi la règle. Fight est la
dernière phase du tour. Le helper `end_of_turn_regain_coherency_all_squads` est partagé par les
deux chemins pour qu'ils ne puissent pas diverger, traite les escouades des **deux** joueurs
(la règle vise « units on the battlefield ») et itère en ordre trié — `destroy_model` mute les
caches sous l'itération, et les replays doivent rester rejouables.

⚠️ **Piège rencontré, à ne pas refaire** : le premier branchement a été posé en tête de
`_advance_to_next_player`, qui *semble* être la frontière de tour mais est **du code mort**
(cf. §0.4). Le run de vérification a reproduit le crash à l'identique. **Vérifier qu'un point
d'ancrage est appelé AVANT d'y brancher quoi que ce soit.**

⚠️ **Dette assumée (décision 2026-07-19)** : la règle laisse au joueur le **choix** des figurines
retirées ; le moteur choisit à sa place (la plus éloignée du centroïde, tie-break par index
croissant). Retenu pour les deux modes. L'écart n'est pas que positionnel : sur une escouade
**hétérogène**, un humain sacrifierait des figurines de base pour conserver une arme spéciale,
alors que le critère géométrique retire la figurine isolée — l'écart porte sur la **puissance
conservée**. Les retraits sont journalisés en console (`_log_end_of_turn_coherency_removals`)
pour qu'un joueur PvP ne voie pas des figurines disparaître sans explication. Une sélection
manuelle **remplacera** cet appel, elle ne s'y ajoutera pas.


### 0.2 Diagnostic des violations d'invariant — ✅ FAIT (2026-07-19 soir)

Le `ValueError` « incohérence masque/exécution » ne nommait pas la contrainte violée, ce qui
obligeait à re-deviner la cause à chaque occurrence (deux hypothèses fausses ont été explorées
avant d'instrumenter : `fall_back`/ER, puis double soustraction du coût de descente §13.06 —
**les deux innocentées**). Désormais :

- `validate_move_plan` **délègue** à `explain_move_plan_rejection`, qui renvoie la raison —
  une seule implémentation du check, le booléen n'en est que la façade. Aucune duplication
  (décision de design n°2).
- `build_move_blocked_cells_by_level` porte un **libellé par catégorie** (mur / ER ennemie /
  occupation d'une autre escouade). Il renvoie toujours une **liste** de `(label, set)`, jamais
  l'union — cf. l'avertissement de perf plus bas, inchangé.
- Le calcul de budget d'`execute_squad_move` est extrait dans `resolve_squad_move_constraints`,
  pour que le diagnostic évalue **exactement** les contraintes de l'exécution : les recalculer à
  la main à l'endroit de l'erreur produirait un diagnostic qui peut mentir.
- Le site d'erreur (w40k_core) rejoue ces helpers **sur le chemin d'erreur uniquement** (zéro
  coût nominal) et affiche `Contrainte violée : …`.

C'est ce diagnostic qui a donné la root cause en un run : les 12 occurrences portaient toutes
`coherency du plan invalide (formation actuelle DEJA incoherente)`.


<a id="s0.3"></a>
### 0.3 `CC_DMG` — champ légacy lu par 2 bots — ✅ PORTÉ (2026-07-19 soir)

**Fait** : les **7** sites d'`ai/evaluation_bots.py` lisent désormais `RNG_WEAPONS`/`CC_WEAPONS`
via `get_max_ranged_damage`/`get_max_melee_damage` (même source que
`RewardMapper._get_unit_threat`). +2 tests (`test_evaluation_bots.py`) et les 2 fixtures légacy
existantes migrées ; les 4 tests sont **rouges sur le code d'avant**.

⚠️ **Deux corrections de fond au diagnostic ci-dessous, vérifiées dans le code** :

1. **L'attribution « `ControlBot`, ligne 674 » était fausse.** La ligne 674 est dans le helper
   module `_best_target_slot_by_threat`, dont l'**unique appelant** (grep) est
   **`DefensiveSmartBot`** — qui n'est PAS dans `bot_training.ratios`
   (random/greedy/defensive/control/aggressive_smart/adaptive). L'exposition était donc
   **l'évaluation, pas le training** : ce n'était pas la mine annoncée. Le raisonnement « bot à
   20 % du training » venait d'un numéro de ligne rattaché à la mauvaise classe.
2. **`RNG_DMG` est mort exactement comme `CC_DMG`** et était lu sur 3 des 7 sites. Traiter le seul
   `CC_DMG` aurait laissé la moitié du bug.

**Changement de sémantique assumé** : l'ancien seuil de charge de `TacticalBot`
(`CC_DMG >= 2`) portait sur un dégât **par touche**. Transposé tel quel sur `NB × DMG` il serait
vrai presque toujours. Le critère est donc devenu « dégâts mêlée attendus > dégâts de tir
attendus », ce que la docstring de la classe décrivait déjà (« charges if melee is advantageous »).

~~**Dette restante repérée au passage, NON traitée** : `ai/game_replay_logger.py` lit encore
`unit["RNG_DMG"]`/`unit["CC_DMG"]` (~8 sites) et `config/unit_definitions.json` les déclare encore
dans `required_properties`.~~ → **soldée en §0.8** : le module n'a pas été porté mais **supprimé**
(aucun appelant vif, aucun consommateur de sa sortie).

**Diagnostic d'origine (historique, attribution erronée conservée pour mémoire) :**

Les 2 épisodes encore plantés après T6-i le sont sur une cause **sans rapport** :

```
ConfigurationError: Required key 'CC_DMG' is missing from mapping
```

`CC_DMG` est un champ **supprimé par le refactor multi-armes**
([reward_mapper.py:22](../../ai/reward_mapper.py#L22) : « Replaces old RNG_DMG/CC_DMG fields »).
Vérifié : **0 des 237 fichiers d'unités TS** ne le définit — le champ n'existe plus à l'exécution.
Il est pourtant encore lu par `require_key` dans :

| Bot | Sites | Exposition |
|---|---|---|
| `TacticalBot` | [1142](../../ai/evaluation_bots.py#L1142), [1230](../../ai/evaluation_bots.py#L1230), [1266](../../ai/evaluation_bots.py#L1266), [1345](../../ai/evaluation_bots.py#L1345) | Éval seule (holdout) |
| `ControlBot` | [674](../../ai/evaluation_bots.py#L674) | **Éval ET TRAINING** — `ControlBot` pèse 20 % de `bot_training.ratios` |

⚠️ **`ControlBot` est le plus urgent** : son site est sur un chemin conditionnel rarement
exercé, donc il n'a pas encore pété — c'est une **mine**, pas un bug bénin. S'il est atteint en
entraînement, c'est un crash de training, pas seulement d'éval. **Le portage doit couvrir les
deux bots.**

C'est exactement la dette annoncée en [§10.5](V11_eval_strategy.md#s10.5) : « les autres bots ont été maintenus au fil des
refactors squad, celui-ci non ».

**⚠️ Correction d'une affirmation portée plus haut dans ce document** : « [§10.5](V11_eval_strategy.md#s10.5) validé runtime »
a été écrit à tort. `TacticalBot` n'avait complété que **4 épisodes sur 8** (W:1 L:2 D:1), les 4
autres ayant été attribués au bug de coherency **sans vérification**. La bonne lecture :
**[§10.5](V11_eval_strategy.md#s10.5) reste NON validé runtime** tant que `TacticalBot` ne complète pas ses épisodes une fois
`CC_DMG` porté. Et `0.25 sur 4 épisodes` n'est de toute façon pas une mesure.


<a id="s0.4"></a>
### 0.4 Code mort qui a induit en erreur — `_advance_to_next_player` — ✅ SUPPRIMÉ (2026-07-19 soir)

**Fait** : la méthode et ses **8** tests sont supprimés (les « 12 références » du diagnostic
d'origine étaient des occurrences de grep, pas des tests — vérifié : 32 → 24 tests dans le
fichier). Le grep de vérification a montré que ce
n'était pas une fonction isolée mais un **îlot mort de 4 méthodes** : `_advance_to_next_player`
était l'unique appelant de `_movement_phase_init`, `_charge_phase_init` et `_fight_phase_init`
(ces deux dernières encore marquées `# TODO: Build … activation pool`, et
`_fight_phase_init` branchant sur `_charge_phase_init` à partir du **pool de tir** — du code de
l'ère pré-escouades). Les 4 sont supprimées ensemble. `_shooting_phase_init`, elle, est **vivante**
(appelée par le flux de phase move) et est conservée.

L'en-tête de `test_engine_turn_loop.py` porte désormais la raison de la suppression, pour qu'elle
ne soit pas relue comme une perte de couverture.

**Diagnostic d'origine (historique) :**

`_advance_to_next_player` (w40k_core) **n'a aucun appelant** — vérifié par grep sur `engine/`
et `ai/`. Elle contient pourtant toute la logique de bascule de joueur, d'incrément de tour et de
test de limite de tour, ce qui la fait passer pour LA frontière de tour. La vraie progression de
tour est dans `fight_handlers` (fin de phase de Fight, deux chemins).

**Et elle est couverte par des tests verts** : `tests/unit/engine/test_engine_turn_loop.py`,
12 références. Un fichier de tests vert sur une fonction que rien n'appelle est **le même piège**
qui a masqué `end_of_turn_coherency_removal` (§0.1) et `update_frozen_model` ([§10.4](V11_eval_strategy.md#s10.4)) : il donne
au lecteur suivant la certitude que le chemin est vivant et correct.

~~**À traiter** : supprimer la fonction et ses tests~~ → fait, voir en tête de §0.4.

> **Motif récurrent à surveiller dans ce projet** — six occurrences vérifiées à ce jour.
> **Cinq de type « jamais appelé »** : `update_frozen_model` ([§10.4](V11_eval_strategy.md#s10.4)),
> `end_of_turn_coherency_removal` (§0.1), `_advance_to_next_player` (§0.4),
> `game_replay_logger` (§0.8, 795 lignes + 8 tests), `log_unified_action` (§0.8). Du code
> correct, testé, et jamais appelé. **Devant toute fonction sur laquelle repose un
> raisonnement, vérifier d'abord qu'elle a un appelant.**
>
> **Une de type « jamais exercé »** (§0.11) : `test_move_mask_is_executable.py` est appelé, vert,
> et mesure le bon invariant sur le bon scénario — mais par exploration aléatoire, donc il ne
> visite jamais la configuration qui cassait. **Un test vert ne couvre que les états qu'il
> atteint ; sa docstring peut affirmer le contraire de bonne foi.**


### 0.5 Fail-fast de l'évaluation standalone — ✅ FAIT (2026-07-19 soir)

Un épisode planté était converti en `wins:0, losses:0, draws:0, failed_episodes:N`
([bot_evaluation.py:619-627](../../ai/bot_evaluation.py#L619-L627)) et le chemin `--eval`
publiait quand même un `Combined Score` — donc **une mesure sur échantillon tronqué par les
crashes, sans aucune mention**. Le win-rate n'était pas dilué (dénominateur = épisodes complétés),
mais le score final était publié sans signaler la troncature.

Le chemin **training** était déjà strict (`_apply_eval_results`, training_callbacks.py:2090-2096) :
c'est `--eval` qui était l'anomalie. Il reprend désormais le même check et lève avant toute
publication de score. **Décision** : ne PAS compter les crashes comme défaites — un crash moteur
n'est pas une défaite de l'agent, ça polluerait [§10.6](V11_eval_strategy.md#s10.6) avec du bruit d'infrastructure.

Conséquence voulue : **aucune mesure [§10.6](V11_eval_strategy.md#s10.6) ne passera tant qu'un bug plante des épisodes.**

> ➜ **Déplacé en §0.16 (ouvert).** Rien n'a été supprimé : le contenu est intégral là-bas.


### 0.6 Listes holdout mortes — ✅ FAIT (2026-07-19 soir)

`ArmageddonAgent_training_config.json` déclarait dans ses **5 phases**
`holdout_regular_scenarios: [bot-01..05]` et `holdout_hard_scenarios: [bot-01..05]` (recopie de
CoreAgent), alors que seuls 4 scénarios `holdout_regular` existent et **aucun** `holdout_hard`.
`_compute_holdout_split_metrics` retournait donc `{}` **silencieusement** : les 3 agrégats de
split étaient morts en permanence.

**Décision utilisateur** : la difficulté porte sur l'**adversaire**, pas sur le roster ([§10.5](V11_eval_strategy.md#s10.5)).
Poussée jusqu'au bout, cette décision rend le split de scénarios **redondant** — les rosters
`hard` seraient des copies exactes des `regular`, donc 4 scénarios byte-identiques évalués par
les mêmes bots, et il faudrait en plus câbler un pool de bots par split qui ferait doublon avec
l'axe par-bot déjà en place (`bot_eval/vs_*`). Les deux listes
ont donc été **supprimées** des 5 phases : l'absence est désormais **explicite**
(`Worst holdout hard combined: N/A`) au lieu d'être un zéro silencieux.

Le critère [§10.6](V11_eval_strategy.md#s10.6) (win-rate **par roster**) reste servi par les scores **par scénario** : les 4
scénarios holdout SONT les 4 matchups (SM/Ork × SM/Ork).

> ➜ **Déplacé en §0.16 (ouvert).** Rien n'a été supprimé : le contenu est intégral là-bas.

**✅ Points Orks corrigés par l'utilisateur le 2026-07-19** — ils sont désormais différenciés et
plausibles (Boyz 7, Gretchin 4, WarTrakk 175, personnages 50-100), fini le `VALUE = 70` uniforme.
L'objection « points factices » tombe.

~~🔴 **Mais ils rendent mesurable un déséquilibre qui était jusque-là invisible** :~~

| Roster | Points (état 2026-07-19 matin) | Figurines |
|---|---|---|
| Orks | ~~**824**~~ | ~~47~~ |
| Space Marines | ~~**690**~~ | 23 |

⚠️ **CE DÉSÉQUILIBRE N'EXISTAIT PAS — voir §0.9.** Confronté aux Munitorum officiels
(2026-07-20), le « +19 % » s'est révélé être un **artefact de trois `static VALUE` fausses**, la
`WarTrakk` cotée **175** au lieu de **60** pesant à elle seule +115. Aux points réels du
Munitorum, les deux listes font **680 vs 680**, écart **0**. Le raisonnement ci-dessus était
correct dans sa logique et **faux dans ses données** : il concluait à un déséquilibre de listes
à partir de valeurs de code jamais confrontées à la source officielle. **Ne pas re-citer le
824/690.**

**Composition exacte des deux rosters — ÉTAT PÉRIMÉ DU 2026-07-19, conservé pour mémoire.**
Recalculée depuis les fichiers via `UnitRegistry`, donc « confirmée » — mais confirmée contre le
**code**, jamais contre le Munitorum. C'est exactement la faille : recalculer ne vaut pas vérifier
la source. Composition et points à jour en **§0.9**.

| | ~~Orks — **824 pts / 47 fig.**~~ | ~~Space Marines — **690 pts / 23 fig.**~~ |
|---|---|---|
| Masse ⚠️ périmé (10 Gretchin, pas 20) | 20 × Gretchin @4 = 80 ; 18 × Boyz @7 = 126 ; 2 × BoyzNobKombi @9 = 18 | 6 × Intercessor @16 = 96 ; 3 × VanguardVeteran @20 = 60 ; 2 × Eradicator @23 = 46 ; 2 × IntercessorGL @18 = 36 ; 2 × IntercessorSgt @19 = 38 |
| Lourd | WarTrakk **175** ; BigMekDakkarig **100** | LandSpeeder **95** |
| Personnages | PainBoy 80 ; Warboss 75 ; WeirdBoy 65 ; Bigboss 55 ; BannerNob 50 | CaptainRelicShield 80 ; ChaplainJumpPack 75 ; Librarian 60 ; Ancient 40 |

⚠️ **Ce qui reste vrai de l'analyse ci-dessous, et ce qui tombe** (mise à jour §0.9) :
- ❌ **L'écart budgétaire (+134 pts) n'existe pas.** Aux points Munitorum : 680 vs 680. Le
  raisonnement « +255 pts concentrés dans 2 véhicules Orks » reposait sur la `WarTrakk` à 175 :
  elle en vaut **60**. Les deux véhicules orks pèsent **160**, contre 95 pour le Land Speeder.
- ✅ **L'asymétrie de masse reste réelle** : **37 figurines contre 23** (et non 47 — cf. §0.9,
  10 Gretchin et non 20). Plus de corps ⇒ OC supérieur sur les objectifs (§14) et meilleure
  résilience aux pertes.
- 🔁 **Mais ce n'est plus un déséquilibre, c'est une identité de faction** : à budget égal, une
  horde ork EST censée aligner plus de figurines qu'une escouade Space Marine. Les deux listes
  étant par ailleurs figées par le contenu de la boîte (contrainte métier, §0.9), il n'y a rien
  à « rééquilibrer » — et le win-rate par matchup redevient interprétable.

> ➜ **Déplacé en §0.15 (ouvert).** Rien n'a été supprimé : le contenu est intégral là-bas.


<a id="s0.7"></a>
### 0.7 Run d'éval du 2026-07-19 (post-portage `CC_DMG`) — 60/60 épisodes

```
python3 ai/train.py --agent ArmageddonAgent --eval --training-config x1_debug
```

Notes sur la commande, lues dans [train.py](../../ai/train.py) : `--eval` est un alias de
`--test-only` (L4384) ; le mode **refuse** `--scenario bot` et, à défaut d'un chemin de scénario
explicite `.json` (joué tel quel, cf. §0.29 « Outillage »), résout **seul** les holdouts
(L4647) ; `--training-config` est obligatoire en pratique — le défaut `"default"` n'existe pas
(rupture R1, jamais corrigée). Phases réelles : `x1`, `x5_append`, `x5_new`, `x1_debug`, `x5_debug`.

**Résultat — 60/60 épisodes complétés** (6 bots × `eval_episodes: 10` ; chaque bot affiche
W+L+D = 10). Le fail-fast §0.5 n'a pas levé : **l'absence d'exception EST le résultat**.

| Bot | Score | Détail |
|---|---|---|
| defensive | **0.90** | W:9 L:1 D:0 |
| tactical *(holdout)* | **0.60** | W:6 L:3 D:1 |
| aggressive_smart | 0.30 | W:3 L:7 D:0 |
| control | 0.30 | W:3 L:6 D:1 |
| greedy | 0.20 | W:2 L:8 D:0 |
| adaptive | **0.10** | W:1 L:7 D:2 ← `worst_bot_score` |

`Combined Score: 0.3830` — **recalculé à la main depuis les poids** (`tactical: 0.0`, les 5 autres
sommant à 1.0) : **0.3830 exactement**. Le holdout ne pollue donc pas le score de sélection, et
`worst_bot_score` retient bien `adaptive`, pas `tactical` : **les DEUX verrous de [§10.5](V11_eval_strategy.md#s10.5)
fonctionnent, vérifiés par le calcul et pas seulement par lecture du code.**

**Ce que ce run VALIDE** :
- ✅ **Portage `CC_DMG`/`RNG_DMG` validé runtime** sur les **6 sites `TacticalBot`** — le bot a
  joué 10/10 épisodes entiers, contre 4/8 auparavant.
- ✅ **[§10.5](V11_eval_strategy.md#s10.5) enfin validé runtime.** L'avertissement « `TacticalBot` n'a jamais été validé runtime
  sur le pipeline squad » porté plus bas dans ce document est **levé**.

> ➜ **Déplacé en §0.16 (ouvert).** Rien n'a été supprimé : le contenu est intégral là-bas.

**Trois constats du run, à traiter :**

| # | Constat | Suite |
|---|---|---|
| 1 | **Le modèle échouerait au gating** : `worst_bot_score` 0.10 < `model_gating_min_worst_bot` 0.25. | Attendu — ce modèle n'a pas été entraîné dans les conditions actuelles. À re-mesurer après le vrai run. |
| 2 | ~~**Bug d'affichage** : l'en-tête annonçait `Episodes per bot: 10 (Total: 30)` alors que **60** tournaient~~ — `episodes_per_bot * 3` codé en dur, littéral resté de l'époque à 3 bots. | ✅ **CORRIGÉ (2026-07-19)** : le total est dérivé de `len(callback_params.bot_eval_weights)` — **la même source unique** que `bot_evaluation` (`active_bot_names = tuple(eval_weights.keys())`), pour que le nombre annoncé ne puisse pas diverger du nombre joué. Vérifié sur le vrai chemin d'exécution (run interrompu après l'en-tête) : affiche `Total: 60`. |
| 3 | **Réserve §0.5 confirmée OBSERVÉE** : le bloc `🏁 Scenario ranking` s'imprime bien **avant** le résumé. | Toujours ouvert. |

`Worst holdout hard combined: N/A` s'affiche comme voulu (§0.6) : l'absence est **explicite**,
pas un zéro silencieux. Le fix de §0.6 est donc lui aussi confirmé à l'exécution.

**Ce que ce run ne débloque PAS — le critère [§10.6](V11_eval_strategy.md#s10.6).** Ranking par scénario :
`bot-03 = 0.805`, `bot-01 = 0.383`, `bot-04 = 0.305`, `bot-02 = 0.153`. Les 4 scénarios holdout
SONT les 4 matchups (SM/Ork × SM/Ork) : l'écart de 0.65 entre le meilleur et le pire mélange
**compétence de l'agent** et ~~**déséquilibre de listes** (§0.6, 824 vs 690)~~. ⚠️ **Cette dernière
imputation est INVALIDE** (§0.9) : les listes font 680 vs 680, il n'y a pas de déséquilibre de
budget à invoquer. L'écart de 0.65 entre bot-03 et bot-02 mesure donc autre chose — compétence,
asymétrie de masse, ou variance d'échantillon. **À réinterpréter après le run en cours**, sur des
`VALUE` justes ; les chiffres de ce run-là ont été produits avec la `WarTrakk` à 175.

**LE TRAINING TOURNE (2026-07-19, après T6-h + T6-g).** La commande de repro historique passe
désormais de bout en bout :

```
python3 ai/train.py --agent CoreAgent --training-config x5_debug \
  --scenario config/agents/CoreAgent/scenarios/training/training_benchmark/scenario_training_benchmark.json \
  --new --resolution 5
```
→ 10/10 épisodes, 8 workers `SubprocVecEnv` vivants, **zéro** `execute_squad_move a échoué : …
incohérence masque/exécution`, exit 0. Idem en mono-env (`--step`, x1_debug). Les seules
exceptions résiduelles du run sont dans l'**ÉVALUATION** (`bot_evaluation`) et sont la dette
rosters connue (`roster_pool_schedule produced zero eligible training rosters`) — cf. [§10.2](V11_eval_strategy.md#s10.2),
c'est ce qui met les win-rates à 0.00, pas le moteur.

**Chemin critique — LES 2 FIXES SONT LIVRÉS** (détail en section 5, tranche T6) :

| # | Quoi | État |
|---|---|---|
| 1 | **T6-h** — `build_rigid_plan` translatait en OFFSET : à `dx` impair le bloc se DÉFORMAIT (mesuré : distance interne 2 → 1). Fix : translation en CUBE, miroir de `deployment_build_squad_destinations_pool`. **Deux consommateurs de translation de bloc portaient le MÊME bug et ont été alignés** : `translate_squad_to_destination` (l'écrivain du commit, partagé move/charge/fight/pile-in — le laisser en offset aurait fait committer une formation DIFFÉRENTE de celle que `validate_move_plan` avait acceptée) et `preview_hidden_models_after_move` (shooting_handlers). | ✅ FAIT — +10 tests (`test_rigid_plan_translation.py`, paramétrés `dx` pair ET impair, rouges sur le code d'avant) |
| 2 | **T6-g** — le pool BFS du move était construit sur l'ANCRE, mais `build_rigid_plan` translate TOUT le bloc sans le valider → figurines sur un mur / sur une autre escouade. Fix : **érosion morphologique** (`erode_move_pool_by_squad_block`, shared_utils), appelée dans `build_squad_move_cell_map` AVANT la projection sur la grille égocentrique. | ✅ FAIT — +6 tests (`test_move_pool_block_erosion.py`) |

**Sur l'érosion (T6-g), ce qu'il faut savoir pour la maintenir** : le prédicat de cellule est
celui de `validate_move_plan` sous `DEFAULT_MOVE_CONSTRAINTS` — bornes, murs, occupation des
autres escouades **par niveau**, ER ennemie. Ce sont les seules contraintes érodables. Les deux
autres ont été **vérifiées invariantes** par translation cube, donc déjà garanties par le pool
d'ancre : `budget_per_model` (`calculate_hex_distance` est une distance cube → la distance de
chaque figurine à son origine égale celle de l'ancre, bornée par le coût géodésique du pool) et
`require_coherency` / collision intra-plan (ne dépendent que des positions RELATIVES). Escouade
mono-figurine : l'ancre EST le bloc, le pool est déjà exact → court-circuit.

**Déjà corrigé et validé le 2026-07-19** (détail en T6-e / T6-f) : `_turn_step_limit` absent du
chemin single-scenario (T6-e, commité) ; commit de déploiement mono-ancre qui ne plaçait AUCUNE
figurine (T6-f, +10 tests, non commité).

**Suite au 2026-07-19 après T6-h/T6-g** : `9 failed, 1440 passed, 2 skipped`. Baseline vérifiée
par `git stash` : `9 failed, 1421 passed` — **mêmes 9 échecs préexistants** (rosters, cf. plus
bas), +19 = les tests des deux fixes. Zéro régression.

**Dette de conception REMBOURSÉE (2026-07-19)** — la 1re version de l'érosion T6-g DUPLIQUAIT le
prédicat de cellule de `validate_move_plan`, ce que la décision de design n°2 interdit
explicitement (« Interdit de dupliquer le check ») : c'était rouvrir en petit la classe de bug
qu'on venait de fermer. Le prédicat est désormais dans un helper unique,
`build_move_blocked_cells_by_level` (shared_utils), lu par les DEUX côtés de l'invariant —
`validate_move_plan` (par figurine) et `erode_move_pool_by_squad_block` (par bloc).
`erode_move_pool_by_squad_block` prend en plus un paramètre `constraints` : l'érosion codait en
dur `DEFAULT_MOVE_CONSTRAINTS` alors qu'`execute_squad_move` accepte des `extra_constraints`
(divergence latente, non atteinte par le gym aujourd'hui).

⚠️ **Mise à jour §0.1 (2026-07-19 soir)** : l'invariance de `require_coherency` affirmée
ci-dessous est **conditionnelle** et a laissé passer une classe entière de crashes. Lire §0.1
avant de s'appuyer sur ce paragraphe.

⚠️ **Le helper renvoie une LISTE de sets par niveau, jamais leur union — ne pas « simplifier ».**
La 1re version fusionnait, ce qui copie `wall_hexes` (~1100 cellules) à CHAQUE appel : mesuré
+6 % sur `validate_move_plan` (1576 → 1673 µs), qui est appelé en boucle serrée par
`apply_snap_corrections`. En rendant les composants par référence, `validate_move_plan` teste
2-3 appartenances et retombe à 1596 µs, tandis qu'`erode_move_pool_by_squad_block` matérialise
l'union de son côté — là elle est amortie sur |pool| × |figurines| (~2800 × 20). L'arbitrage
appartient au consommateur, pas au helper.

**Invariant MESURÉ, plus seulement raisonné** — `tests/unit/engine/test_move_mask_is_executable.py`
(+3) déroule de vraies parties (3 seeds × 400 steps, actions masquées aléatoires) et vérifie qu'à
chaque step de phase move, TOUTE cellule offerte par le masque produit un plan accepté par
`validate_move_plan`, **avec le budget exact qu'`execute_squad_move` appliquerait** (type de move
inféré du coût géodésique). ~21 700 cellules réelles par run. Cela couvre les deux contraintes
que l'érosion ne filtre pas et qui n'étaient jusque-là que DÉMONTRÉES invariantes par translation
cube (`budget_per_model`, `require_coherency`). **Rouge sur le code d'avant les fixes**
(`git checkout 3886e498 -- shared_utils.py` → `ValueError: execute_squad_move a échoué : squad=103
dest=(24,15) … incohérence masque/exécution`, sur les 3 seeds), vert après.

**✅ [§10.4](V11_eval_strategy.md#s10.4) RÉSOLU (2026-07-19) — l'adversaire d'entraînement est câblé sur TOUS les chemins.**
La construction des adversaires est désormais mutualisée dans `build_training_opponents`
(train.py), appelée par les TROIS chemins : `train_with_scenario_rotation`,
`create_multi_agent_model` (single-scenario) et `create_model` (générique). Sur le chemin
single-scenario, `use_bots` vient de la CONFIG (présence de `bot_training`) et non plus du NOM
du fichier scénario — l'heuristique `"bot" in basename` faisait tomber tout autre scénario sur
`SelfPlayWrapper(frozen_model=None)`. Le `GreedyBot(0.15)` codé en dur est remplacé par les bots
pondérés de `bot_training.ratios`.
Le repli silencieux est **fermé des deux côtés** : `SelfPlayWrapper` lève désormais si
`frozen_model is None` sans `allow_random_opponent=True` (opt-in réservé aux tests), et
`make_training_env` refuse `use_bots=False` **avant de forker les workers** — un worker
vectorisé ne peut pas recevoir de frozen_model, le self-play vectorisé passe par
`BotControlledEnv` + `opponent_mix`.
**Vérifié par un vrai run** : `x5_debug` sur `training_benchmark` affiche désormais
`🤖 Bot training ratios: 10% Random, 20% Greedy, 20% Defensive, 20% Control, 15% Aggressive
Smart, 15% Adaptive` + `seat mode: random`, 8 workers, exit 0. +5 tests
(`test_training_opponent_wiring.py`) + 1 test de refus dans `test_env_wrappers.py`.

**✅ [§10.5](V11_eval_strategy.md#s10.5) FAIT (2026-07-19) — holdout d'évaluation `TacticalBot`.** Câblé dans la factory
d'éval (`bot_evaluation.BOT_CLASSES`), dans `ALL_BOT_NAMES` (training_callbacks — sans quoi son
score n'était ni affiché ni loggé) et dans `bot_eval_weights`/`bot_eval_randomness` des 5 phases
des 2 agents. Un scalaire TensorBoard : `bot_eval/vs_tactical` (son doublon
`00_critical/c_holdout_tactical` a été supprimé le 2026-07-31 — même valeur, deux tags).

⚠️ **Un holdout doit être MESURÉ mais ne doit piloter AUCUN signal de sélection** — sinon la
sélection de modèle optimise dessus et ce n'est plus un holdout. Deux verrous, tous deux
nécessaires (le premier seul ne suffit pas) :
- **Poids nul** : `tactical: 0.0` dans `bot_eval_weights` (les 5 autres gardent leurs poids
  d'origine, somme 1.0). `combined` est un critère de gating et pilote le choix du BEST.
- **Exclusion par NOM** : `worst_bot_score`, le gating et le score robuste itèrent sur des
  ensembles de noms de bots, pas sur les poids — un poids nul ne les protège **pas**.
  D'où `HOLDOUT_BOT_NAMES` / `SELECTION_BOT_NAMES = ALL_BOT_NAMES - HOLDOUT_BOT_NAMES`
  (training_callbacks), utilisé aux 3 sites de sélection ; `ALL_BOT_NAMES` reste pour
  l'affichage et le log. `ALL_BOT_KEYS` (metrics_tracker) exclut aussi le holdout, car il
  alimente `00_critical/b_worst_bot_score`.

⚠️ **Le motif d'origine de cette exclusion était FAUX — corrigé le 2026-07-19 après mesure.**
Ce document justifiait l'exclusion par nom en écrivant que « `TacticalBot` est le bot le plus
fort, donc serait presque toujours le `min` et dominerait le gate ». **Mesuré (§0.7)** :
`vs tactical = 0.60`, **deuxième meilleur score de l'agent**, très au-dessus de `greedy` (0.20)
et `adaptive` (0.10) ; le `min` observé est `adaptive`. `TacticalBot` n'est donc pas le bot le
plus fort face à ce modèle.

**Le verrou reste néanmoins nécessaire, et pour une meilleure raison** : un holdout ne doit
piloter aucun signal de sélection **quel que soit son niveau**. S'il était faible, l'inclure
gonflerait `worst_bot_score` et laisserait passer le gate ; s'il était fort, il l'écraserait.
Dans les deux cas la sélection se met à optimiser sur le holdout, et il cesse d'en être un.
La force relative du bot est **hors sujet** — c'était l'erreur de raisonnement.

**Leçon de méthode** (même famille que la demi-vérité de §0.1 sur `require_coherency`) : une
justification par une propriété SUPPOSÉE du système (« ce bot est le plus fort ») est une
hypothèse non mesurée. Ici elle était fausse et le verrou est resté correct par chance. Préférer
une justification qui tient quelle que soit la valeur de la propriété.

**Dette corrigée au passage** : `randomness_config` (bot_evaluation) ne recopiait que
`greedy`/`defensive`/`control` — `aggressive_smart`, `adaptive` et `tactical` retombaient
SILENCIEUSEMENT sur `randomness=0.15`, rendant leur `bot_eval_randomness` de config lettre
morte. La config est désormais transmise entière et l'absence d'une entrée est une **erreur
explicite** aux deux niveaux (planification et construction du bot), sans défaut.

+9 tests (`test_eval_holdout_opponent.py`) : intersection vide `bot_training.ratios` ∩ holdout,
présence en `bot_eval_weights`, somme à 1.0, **poids de holdout == 0.0**, **exclusion des
signaux de sélection**, **absence de défaut de randomness**.
Run de vérification : `vs TacticalBot: 0.00 (0/1 wins)` s'affiche désormais et aucun `KeyError`
de randomness n'est levé — le `0.00` est la dette rosters, pas le câblage.

~~⚠️ **`TacticalBot` n'a jamais été validé runtime sur le pipeline squad**~~
✅ **LEVÉ le 2026-07-19 — voir §0.7** : après le portage `CC_DMG`/`RNG_DMG`, `TacticalBot` a joué
**10/10 épisodes entiers** (`vs tactical: 0.60`, W:6 L:3 D:1). Constat historique : il n'avait
jamais complété un épisode (docstring « unused in training/eval », puis 4/8 épisodes), parce que
les autres bots avaient été maintenus au fil des refactors squad et pas lui.

**Suite après ces deux tranches** : `9 failed, 1451 passed` — **mêmes 9 échecs préexistants**
(dette rosters), zéro régression.

**~~🔴 PROCHAIN BLOQUEUR — dette rosters ([§10.2](V11_eval_strategy.md#s10.2)).~~ ✅ RÉSOLU (2026-07-19, commit `d2b377f0`)** —
les 2 rosters SM/Orks existent sous `ArmageddonAgent` et le pipeline tourne dessus.
**✅ Et la banque CoreAgent a été RETIRÉE le 2026-07-19 (décision utilisateur)** : les 9 échecs
qu'elle causait n'existent plus, la suite est verte. Voir §0.-1 pour la nouvelle baseline et la
règle de périmètre.

**Pour la suite immédiate, voir §0.0** (ordre imposé : test 03.03, puis `CC_DMG`, puis code mort).

**Historique — l'ancien libellé du bloqueur [§10.4](V11_eval_strategy.md#s10.4) :**
Re-vérifié dans le code le 2026-07-19 : `update_frozen_model` ([env_wrappers.py:1272](../../ai/env_wrappers.py#L1272))
n'a **aucun appelant** hors son propre test ; le chemin single-scenario construit
`SelfPlayWrapper(masked_env, frozen_model=None, ...)` ([train.py:1537](../../ai/train.py#L1537), [1871](../../ai/train.py#L1871)) ;
et à `frozen_model is None` le wrapper joue **une action valide au hasard**
([env_wrappers.py:1242-1248](../../ai/env_wrappers.py#L1242-L1248)). Les runs de validation T6-g/T6-h et
ArmageddonAgent ont donc tourné avec un P2 aléatoire — **rien ne le signale dans les logs**.
Conséquence : le pipeline est prouvé fonctionnel, mais **aucun win-rate d'entraînement n'a de
sens tant que ce n'est pas câblé**, et le critère T6 reste non évaluable. À traiter AVANT tout
run sérieux et avant T7. (Le combined d'`--eval` reste valide : l'évaluation, elle, joue contre
de vrais bots.)

**Après ça** — ne PAS anticiper : **T7** (unification de la validation de déploiement,
section 5). Son déclencheur « le training tourne » est désormais REMPLI, mais T7 touche le
masque, donc l'espace d'action de l'agent, et exige une mesure avant/après — donc [§10.4](V11_eval_strategy.md#s10.4) d'abord.

**⚠️ AVANT de lancer le premier vrai run, lire la section 10** (stratégie d'entraînement et
d'évaluation, décision utilisateur 2026-07-19). Deux points bloquants y sont établis :
- **[§10.4](V11_eval_strategy.md#s10.4)** — toute la machinerie d'adversaires (bots pondérés + self-play `opponent_mix`)
  n'est câblée que sur `--scenario bot`. Le chemin single-scenario vectorisé (x5_debug,
  n_envs=8) tombe sur `SelfPlayWrapper(frozen_model=None)` dont le frozen n'est JAMAIS mis à
  jour (`update_frozen_model` : zéro appelant) → **P2 joue des actions ALÉATOIRES en
  permanence**. Comme `--scenario bot` est cassé (rosters), un run lancé aujourd'hui
  entraînerait contre du hasard **sans que rien ne le signale**. Même famille de divergence
  que T6-e.
- **[§10.6](V11_eval_strategy.md#s10.6)** — le critère de succès T6 a été REMPLACÉ : l'ancien (« win-rate vs RandomBot sur
  holdout ») référence un holdout de rosters supprimé. Le holdout porte désormais sur
  l'**adversaire** (`TacticalBot`, réservé à l'évaluation), pas sur les rosters.

**État de la suite** — ⚠️ **PÉRIMÉ, voir §0.-1** (la suite est verte depuis le retrait de la
banque CoreAgent le 2026-07-19 : `1402 passed, 0 failed`). Constat historique :
`tests/unit` — **9 échecs, tous préexistants et hors chemin critique** :
4 × banque de scénarios et 5 × déploiement/terrain, tous dus à des **rosters manquants ou
non résolus** (`roster_pool_schedule produced zero eligible training rosters`, fichiers de
roster holdout absents). Baseline vérifiée par `git stash` — aucune régression des fixes ci-dessus.
Ces rosters ont été supprimés VOLONTAIREMENT (commit `43eae95a`, obsolètes pré-escouades) : la
réparation n'est pas « les restaurer » mais recréer 2 rosters (SM, Orks) — cf. [§10.2](V11_eval_strategy.md#s10.2).

**Dettes à connaître avant de s'y remettre** :
- `--scenario bot` échoue en AMONT du moteur (roster) : utiliser `training_benchmark` pour
  reproduire, pas `bot-01`.
- Toute la banque (61 scénarios) tourne sur `terrain-mc1.json` depuis le 2026-07-19 (décision
  utilisateur : `terrain-train-01/02/03` obsolètes). mc1 porte 8 étages ; l'observation les voit
  via le canal 5 `GRID_CH_LEVEL`. ⚠️ `scripts/migrate_scenario_bank_v11.py` cycle encore sur les
  3 terrains plats — le RELANCER repointerait la banque et casserait le test de banque.


<a id="s0.8"></a>
### 0.8 `game_replay_logger` — SUPPRIMÉ, pas porté (2026-07-19 soir)

**Point de départ** : la dette annoncée en §0.3 (le module lit encore `RNG_DMG`/`CC_DMG`, champs
supprimés du contrat d'unité). La question posée n'était pas « comment porter » mais « faut-il
porter ». Réponse vérifiée : **non — supprimer**. 12 fichiers, **−1585 lignes**.

**Les 3 constats qui ont tranché** (tous re-vérifiés dans le code, pas dans un rapport) :

1. **Aucun appelant vif.** `enhance_training_env` était appelé à 2 endroits. Dans `train.py`, sous
   `if args.replay or args.convert_steplog` — **inatteignable**, car `main()` fait `return` sur ces
   deux flags bien avant (les deux modes sont intégralement servis par `ai/replay_converter.py`, qui
   n'importe jamais ce module). Dans `multi_agent_trainer.py`, sur le chemin `--orchestrate`
   (voir plus bas). `save_episode_replay` était atteint mais **no-op** : son corps est gardé par
   `if env.replay_logger`, attribut resté à `None`.
2. **Aucun consommateur de sa sortie.** Le replay du frontend charge `/api/replay/default|file|list`,
   qui servent **`step.log`** (texte, `.log` uniquement), parsé par `replayParser.ts`. Le JSON
   `ai/event_log/replay_*.json` est produit par `replay_converter.py`. `game_replay_logger` était le
   **prédécesseur** de `replay_converter`, laissé branché après son remplacement.
3. **Le périmètre cassé dépassait `RNG_DMG`/`CC_DMG`** : le format émis exigeait aussi `CUR_HP`,
   `RNG_RNG`, `CC_RNG`, `MOVE`, `BASE_SHAPE`, `BASE_SIZE`. Porter, c'était réécrire le format entier
   d'un fichier que personne ne lit.

**Supprimé** : `ai/game_replay_logger.py` (795 l.) et son test ; `log_unified_action`
(`shared/gameLogStructure.py`, 85 l., **aucun appelant hors tests** — nouvelle occurrence du motif
§0.4) et ses 2 tests ; les hooks de `w40k_core.step()` (131 l.) + l'attribut `replay_logger` ;
les câblages de `train.py` et `multi_agent_trainer.py` ; `required_properties` des 2
`unit_definitions.json` (**clé sans aucun lecteur** — grep vide, config morte) ;
`RNG_DMG`/`CC_DMG` de `frontend/src/types/api.ts` (types jamais lus).

**Effet de bord assumé** : `SelectiveEpisodeTracker` (`multi_agent_trainer.py`) n'était alimenté
**que** par ce logger. Le laisser en place garantissait un `raise ValueError` sur le chemin
`--orchestrate`. La feature entière est donc supprimée (`EpisodeMetrics`,
`SelectiveEpisodeTracker`, 3 sites de câblage, clé `selective_replay_files`).

**Vérification** : `pytest tests/unit` **exit 0** — 1396 tests, 0 skip, 0 échec (compté sur les
caractères de statut : le reporter du projet **n'imprime pas** la ligne de résumé, tout « N passed »
non compté est à rejeter). `tsc --noEmit` exit 0. Imports des 4 modules touchés OK.

⚠️ **Correction à [§5](V11_tranches.md#s5)/T2 (§992-995)** : ce paragraphe décrit `multi_agent_trainer.py:1016` comme
contenant encore `action % 8` + `unit_idx = action // 8`. **C'est périmé** — la branche a été purgée
au commit `6a7a9de1` ; il ne restait qu'un commentaire de purge, lui-même supprimé ici. Le grep est
désormais vide. Ce paragraphe a déjà induit deux relecteurs en erreur (citation de la doc au lieu
d'un grep) : **§992-995 est soldé.**

~~**Reste ouvert — chantier distinct, non urgent** : la purge complète de `multi_agent_trainer.py` /
`--orchestrate`.~~ → ✅ **FAIT dans la foulée (2026-07-19 soir)**, le module est supprimé.
Les deux preuves qui l'ont condamné, établies **sans s'appuyer sur la doc** : il chargeait les
modèles via `DQN.load` alors que tous les `.zip` sont MaskablePPO, et il appelait
`base_env.controller.connect_step_logger(...)` alors que `W40KEngine` n'expose que `pve_controller`.
Supprimés avec lui : l'import dans `train.py`, `start_multi_agent_orchestration`, les flags
`--multi-agent` / `--orchestrate` / `--max-concurrent` / `--training-phase`, et les 3 stubs
`sys.modules["ai.multi_agent_trainer"]` des tests qui n'existaient QUE pour contourner cet import
legacy. `--total-episodes` est **conservé** (encore lu dans le chemin d'entraînement vivant).
`create_multi_agent_model` est un **homonyme vivant** de `train.py`, sans rapport — ne pas le purger.


<a id="s0.9"></a>
### 0.9 Rosters fidèles à la boîte + points Munitorum — ✅ FAIT (2026-07-20) — **§0.6 SOLDÉ**

**Déclencheur** : l'utilisateur signale que la boîte Armageddon ne contient que **10 Gretchin**,
alors que les 4 rosters en déclaraient 20. Il fournit les 2 Munitorum officiels
(`Documentation/40k_rules/Armageddon/{Orks,Space Marines} - Munitorum UK.pdf`) et les datasheets.
Contrainte métier posée : **les rosters doivent refléter la boîte, pas une liste optimisée.**

⚠️ **Le texte de ces PDF n'est pas extractible** (contenu en image : `extract_text()` ne rend que
les en-têtes). Il faut les **rendre en PNG** (`fitz`/pymupdf, dpi≥140) et les lire visuellement.
Ne pas conclure « le PDF est vide ».

**Points réels relevés dans les Munitorum** (par UNITÉ, pas par figurine) :

| Orks | pts | Space Marines | pts |
|---|---|---|---|
| Boyz ×10 (×2 unités) | 150 | Intercessor Squad ×5 (×2) | 160 |
| Gretchin | 45 | Vanguard Vets w/ Jump Packs ×5 | 100 |
| Warboss 75 / Bigboss 55 / Bannernob 50 | 180 | Eradicators w/ Heavy Bolters ×3 | 70 |
| Painboy 80 / Weirdboy 65 | 145 | Land Speeder | 95 |
| Wartrakk | 60 | Captain 80 / Librarian 60 / Ancient 40 | 180 |
| Big Mek Dakkarig | 100 | Chaplain w/ Jump Pack | 75 |
| **TOTAL** | **680** | **TOTAL** | **680** |

**Les 4 `static VALUE` corrigées** (elles seules créaient le faux déséquilibre de §0.6) :

| Unité | avant | après | source |
|---|---|---|---|
| `WarTrakk` | **175** | **60** | Munitorum : WARTRAKK 1 model 60 pts |
| `BoyzNobKombi` | 9 | 12 | BOYZ 75 pts / 10 → 9×7 + 1×12 = 75 exact |
| `Gretchin` | 4 | 5 | 45 pts / 10 = 4,5 **non représentable** (`VALUE` coercé `int`, [game_state.py:952](../../engine/game_state.py#L952)) — arrondi au supérieur pour ne pas sous-coter |
| `IntercessorGrenadeLauncher` / `IntercessorSergeant` | 18 / 19 | 16 / 16 | 80 pts / 5 modèles ; **en 10ᵉ l'équipement est gratuit**, tous les modèles d'une escouade coûtent pareil |

Résultat mesuré sur les 8 fichiers de roster : **685 (Orks) vs 680 (SM)**, écart **0,7 %** contre
+19,4 % avant. Le résidu de 5 pts est l'arrondi Gretchin, incompressible en entier.

🔒 **RÈGLE MÉTIER (utilisateur, 2026-07-20) — NON NÉGOCIABLE.** `VALUE` **suit les documents
officiels**. Ce n'est pas une variable de tuning. `VALUE` est pourtant consommé **par figurine**
(pondération de menace [reward_calculator.py:1442](../../engine/reward_calculator.py#L1442),
différentiel d'armée [observation_builder.py:367](../../engine/observation_builder.py#L367)) : cet
effet sur l'apprentissage est une **conséquence à assumer**, jamais un motif pour s'écarter du
Munitorum. **Ne pas « rééquilibrer » ces valeurs pour améliorer un résultat d'entraînement.**

**Ventilation par figurine — arbitrée le 2026-07-20, sujet CLOS.** Le document cote l'**unité**,
pas la figurine ; quand le quotient n'est pas entier la répartition est sous-déterminée. Décision :
**faire tomber le total d'unité juste partout où c'est représentable**, quitte à ce que la
ventilation s'en écarte (Boyz : 9 × 7 + Nob 12 = 75 **exact**, plutôt que 10 modèles uniformes
à 7 = 70). **Seul écart résiduel assumé** : Gretchin, unité à **50** au lieu de 45 — aucune
répartition entière ne donne 45 sur 10 figurines identiques. Alternatives examinées et
**écartées** : Gretchin à 4 (→ Orks 675), Boyz uniformes (→ 680/680). Ne pas les rouvrir.

**🔴 Violation de règle corrigée : le Weirdboy ne peut pas mener les Gretchin.** Les 4 rosters
l'attachaient à l'unité de Gretchin. Munitorum : `WEIRDBOY / LEADER : BOYZ, BREAKA BOYZ`. Le seul
personnage habilité à mener des GRETCHIN est **Zodgrod Wortsnagga**, absent de la boîte. Les deux
unités de Boyz ayant déjà chacune un Leader (Warboss, Bigboss) et une unité ne pouvant en accueillir
qu'un, le Weirdboy est devenu une **unité autonome**. Vérifié au moteur : le roster ork charge
désormais 6 unités au lieu de 5, et les 3 scénarios ork tournent jusqu'à terminaison (112/112/125
steps).

**Deux pièges de lecture des sources, à ne pas re-trébucher dessus :**
1. **Le Grot Infirmier n'est pas une figurine de jeu.** Datasheet Painboy : `UNIT COMPOSITION :
   1 Painboy`, `equipped with : … 1 Grot Orderly` → c'est de l'**équipement**. D'où 38 figurines
   physiques dans la boîte mais **37 modèles de jeu**. Le roster n'a rien qui manque.
2. **Contradiction entre deux sources officielles sur les Gretchin** : le Munitorum cote
   `11 models … 45 pts`, la datasheet dit `UNIT COMPOSITION : 10 Gretchin`. La boîte en a 10.
   Retenu : 10 modèles à 45 pts. Non tranchable depuis les documents — signalé, pas masqué.


### 0.10 `--scenario bot` contaminait le holdout sur ArmageddonAgent — ✅ CORRIGÉ (2026-07-20)

> **Correctif livré.** Dans `get_scenario_list_for_phase` ([training_utils.py](../../ai/training_utils.py)),
> la branche `scenario_type in ("bot", "self")` — les deux modes d'**entraînement** — ne balaie
> plus que `training/` (ou la racine `scenarios/` si `training/` n'existe pas). Les dossiers
> `holdout_regular/` et `holdout_hard/` en sont **exclus**. Aucun repli : si `training/` est vide,
> la liste est vide et l'appelant ([train.py:4929](../../ai/train.py#L4929)) lève déjà un
> `FileNotFoundError` explicite — c'est le comportement voulu, pas une régression.
>
> **Mesuré après fix** sur ArmageddonAgent : `bot` et `self` résolvent **1** scénario
> (`training/scenario_training_armageddon.json`) au lieu de 5 ; `holdout` en résout toujours **4**.
> **Non-régression** : `tests/unit/ai/test_training_utils.py`, +4 tests (paramétrés `bot`/`self`) —
> l'ancien test `..._bot_finds_holdout_when_training_empty`, qui **garantissait la contamination**,
> est retourné en `..._bot_empty_training_dir_returns_nothing`. Mutation-testé : les 4 sont rouges
> sur le code d'avant. Suite complète verte (exit 0).
>
> Le diagnostic d'origine est conservé ci-dessous.

`bot` n'est **pas un nom de scénario** mais un **mot-clé de mode rotation**, intercepté à
[train.py:4919](../../ai/train.py#L4919) avant toute résolution de fichier. Il appelle
`get_scenario_list_for_phase(scenario_type="bot")`, qui balaie `training/` **puis
`holdout_regular/` puis `holdout_hard/`** (docstring explicite de la fonction).

Or les 4 scénarios `scenario_bot-01..04` d'ArmageddonAgent vivent dans **`holdout_regular/`** :
ce sont les 4 matchups qui servent à mesurer [§10.6](V11_eval_strategy.md#s10.6). Mesuré : `--scenario bot` résout **5**
scénarios pour cet agent (les 4 holdout + celui d'entraînement). **Entraîner avec ce flag revient
donc à entraîner sur le jeu de test**, silencieusement — aucun message ne le signale.

⚠️ *(Renvoi imprécis — affirmation périmée n°5 de §0bis : cette dette est écrite en §0.7, pas §0.0. Non corrigé.)*
⚠️ La dette notée en §0.0 (« `--scenario bot` échoue en amont du moteur ») vise **CoreAgent**, dont
l'arborescence de scénarios est différente. Elle **ne s'applique pas à ArmageddonAgent**, où le flag
n'échoue pas : il réussit et contamine.

**Le scénario d'entraînement seul couvre déjà les 4 matchups** — inutile de chercher la rotation
ailleurs. `scenario_training_armageddon.json` porte `agent_roster_ref: "training_random"`
(→ `rng.choice` sur les 2 rosters agent, [game_state.py:1187](../../engine/game_state.py#L1187)) et
un `opponent_roster_ref` **en liste** de 2 (→ second `rng.choice`,
[:1200](../../engine/game_state.py#L1200)), tirages indépendants **refaits à chaque `reset()`**.
Mesuré sur **400 resets** : Ork/Ork 102 (25,5 %), Ork/SM 107 (26,8 %), SM/SM 104 (26,0 %),
SM/Ork 87 (21,8 %) — **les 4 matchups, équiprobables** (χ² = 2,38 pour un seuil de 7,81 à 3 ddl :
aucun biais détectable). Un premier tir de 40 resets donnait 15/13/9/**3** et laissait craindre un
biais : c'était du **bruit d'échantillonnage**, pas un bug. Leçon : ne pas conclure à un biais de
tirage sur quelques dizaines d'observations — refaire la mesure en grand avant de diagnostiquer.

⚠️ **Piège latent voisin — `agent_roster_seed`.** Cette clé de scénario est passée en
`random_seed` au tirage du roster AGENT ([game_state.py:1056](../../engine/game_state.py#L1056)),
et le RNG est reconstruit à chaque appel (`random.Random(seed)`,
[:1142](../../engine/game_state.py#L1142)). Si elle est renseignée, **le roster agent devient
identique à tous les épisodes** — le tirage est neutralisé sans le moindre message. Voulu pour les
scénarios holdout `bot-01..04` (qui la portent, pour la reproductibilité), mais ce serait un piège
silencieux dans un scénario d'entraînement. `scenario_training_armageddon.json` ne la porte pas
(`None`) : vérifié. **À contrôler avant de conclure quoi que ce soit sur une distribution de
matchups.**

**Piège de lancement, préexistant** : `--training-config x5_debug` **seul** échoue pour cet agent
(`No scenario file found … scenario_x5_debug.json`). ArmageddonAgent n'a que
`scenario_training_armageddon.json`, donc `--scenario <chemin explicite>` est **obligatoire** :
```
python3 ai/train.py --agent ArmageddonAgent --training-config x5_debug \
  --scenario config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json \
  --new --resolution 5
```
⚠️ `x5_debug` = **1000 épisodes** (~2h50 à 8 envs), pas un run de quelques minutes malgré son nom.

⚠️ **Ce que `x5_debug` ne produit PAS**, à cause de ses `callback_params` :
`save_best_min_episodes = 10000` et `checkpoint_save_freq = 10000` sont **supérieurs** à ses
1000 épisodes → **ni « best model » ni checkpoint** ne sont jamais écrits. `model_gating_enabled`
est `False` (le `Gate 🧱` de la barre de progression est purement décoratif) et `bot_eval_final`
vaut **1** épisode par bot — contre 60 pour le run de §0.7. C'est un run de **validation de
pipeline**, pas de mesure : il ne peut pas servir le critère [§10.6](V11_eval_strategy.md#s10.6).


<a id="s0.11"></a>
### 0.11 Crash du training : collision intra-plan aveugle au niveau — ✅ CORRIGÉ (2026-07-20)

**Symptôme.** Le run `x5_debug` lancé après §0.9 meurt à l'épisode **~250/1000** (exit 1) :
```
execute_squad_move a échoué : squad=3 type=fall_back dest=(205,160) depuis (210,142)
— la destination vient du pool BFS du masque, elle DOIT être exécutable
(incohérence masque/exécution). Contrainte violée : collision intra-plan :
deux figurines en (189,159) (dont 3#9)
```

**Root cause, prouvée.** Dans `explain_move_plan_rejection`
([shared_utils.py](../../engine/phase_handlers/shared_utils.py)), deux contrôles voisins ne
traitaient pas la position de la même façon :

| Contrôle | Clé | Niveau pris en compte |
|---|---|---|
| Cellule interdite — `blocked_by_level[_target_level(entry)]` | `(col, row)` **par niveau** | ✅ |
| Collision intra-plan — `new_cells` | `(col, row)` **tous niveaux confondus** | ❌ |

Or le niveau **fait partie de l'identité d'une position** : tout le prédicat d'occupation du
moteur est per-niveau (`build_move_blocked_cells_by_level`), et le commentaire de `_target_level`
le dit lui-même (« sinon un move vers l'étage est validé contre l'occupation du sol — bug
superposition inter-niveaux »). Deux figurines d'une même escouade **légalement** superposées à
des étages différents étaient donc comptées comme une collision.

**Pourquoi ça tuait le training et pas juste un coup.** `build_rigid_plan` translate le bloc
**rigidement** (même delta cube pour toutes les figurines, tuples à 3 éléments donc niveau
inchangé). Deux figurines partagent donc `(col,row)` à l'arrivée **ssi** elles la partageaient au
départ. Conséquence : dès qu'une escouade se retrouvait superposée sur deux étages, **TOUS ses
déplacements ultérieurs** devenaient injouables — et comme `erode_move_pool_by_squad_block` ne
teste PAS la collision (elle la démontre invariante par translation, ce qui est **exact**), le
masque continuait d'offrir ces destinations. D'où le crash dur, et le profil observé : 250
épisodes sains puis mort brutale, le temps que la superposition apparaisse.

**Correctif** : `new_cells` clée sur `(niveau, col, row)`. Le message d'erreur nomme désormais le
niveau. L'invariant revendiqué par l'érosion redevient vrai *pour de bon* : c'était le prédicat
lui-même qui était faux, pas le raisonnement d'invariance.

**Non-régression** : `tests/unit/engine/test_move_plan_intra_squad_levels.py`, 2 tests sur un
**vrai moteur déploiement joué** (pas un `game_state` fabriqué) — niveaux différents ⇒ pas une
collision (**rouge avant le fix**, vérifié) ; même niveau ⇒ toujours refusé (vert avant/après).
Le 1ᵉʳ assert porte sur « le rejet n'est pas *une collision* » et non « aucun rejet » : la cellule
peut légitimement être refusée pour une autre raison à l'étage (pas de plancher, mur), sinon le
test serait instable. Suite : **1398 tests, 0 échec**.

🔴 **Pourquoi `test_move_mask_is_executable.py` n'a rien vu** — c'est le point le plus important
de cette entrée. Ce fichier mesure **cet invariant exact**, sur **ce scénario exact**, et il est
vert. Il ne vérifie l'invariant que sur les états atteints par **exploration aléatoire** (3 seeds,
400 steps) : la superposition inter-étages n'y survient jamais. Sa docstring affirme pourtant
combler précisément ce trou (« Ce test remplace ce raisonnement par une mesure »).

> **Quatrième variante du motif §0.4, et la plus sournoise.** Les trois premières étaient du code
> *jamais appelé*. Celle-ci est du code appelé, par un test vert, qui **n'exerce jamais le cas**.
> Un test qui explore au hasard ne prouve rien sur les configurations qu'il n'atteint pas — et sa
> docstring peut affirmer le contraire en toute bonne foi. **Devant un test de type « je déroule
> des parties et je vérifie un invariant », toujours se demander quelles configurations il ne
> visite jamais, et les construire explicitement.**

**Non tranché** : je n'ai pas l'état exact au moment du crash. Il est prouvé que le prédicat est
aveugle au niveau et qu'il produit ce message sur une configuration légale ; il n'est **pas**
prouvé que les deux figurines de l'escouade 3 étaient à des étages différents plutôt que dans un
état déjà illégal. Si un crash de cette classe réapparaît, dumper l'état avant de conclure.

**Limite connue, HORS PÉRIMÈTRE (décision utilisateur, 2026-07-20) : le cas x10.** Le contrôle
compare les **sous-hex d'ancre**. Sur Board ×10 les figurines ont une **empreinte multi-hex**
(`compute_candidate_footprint` — « Multi-hex footprints are only computed on Board ×10 ») : deux
socles peuvent donc s'y chevaucher **sans partager leur ancre**, et la même classe d'incohérence
masque/exécution reste ouverte à cette résolution. Sur x5 (résolution du training) l'empreinte
vaut le sous-hex, le contrôle est **exact**. Limite préexistante, non introduite par le correctif.
⚠️ Ne pas lire « l'invariant est rétabli » comme valant pour toutes les résolutions : il vaut
pour x1 et x5. **On ne s'occupe pas de x10** — si le projet y vient un jour, rouvrir ce point
AVANT d'y lancer un entraînement.


### 0.12 Le reward de combat ignore la `VALUE` par figurine — ✅ FAIT (2026-07-20)

> ✅ **LIVRÉ le 2026-07-20 — A, B, C et les tests.** Suite complète **1415 passed, 2 skipped**
> (1403 avant, +12 nouveaux). Ce qui suit est l'énoncé d'origine, conservé intégralement ;
> le détail de ce qui a réellement été écrit est en fin d'entrée (« Ce qui a été livré »).



> **Énoncé de la dette, déplacé depuis le tableau de §0.0 (ligne 6), texte d'origine :**
> Depuis §0.9 les escouades sont **hétérogènes en points**, mais le shaping tue-une-figurine vaut toujours `VALUE_escouade / model_count_at_start` — tuer le Nob (12) rapporte autant qu'un Boy (7), et un HP d'aumônier (75) autant qu'un HP d'Intercessor (16). L'agent n'a **aucun signal** pour cibler les figurines de valeur, alors que l'allocation 05.03 en fait une vraie décision. **Ouvert, aucune ligne écrite.**

> **État vérifié dans le code le 2026-07-20** : le problème est **entier**. La `VALUE` par figurine
> est bien *produite* en amont, mais elle n'est **jamais consommée** en aval. Rien de ce qui suit
> n'est fait. Aucune ligne de code n'a été modifiée pour ce point.

**Ce qui existe déjà (et qui est correct).** `_build_enhanced_unit`
([game_state.py:952-984](../../engine/game_state.py#L952-L984)) pose **deux niveaux de valeur** :
`unit["models"][i]["VALUE"]` = valeur de CHAQUE figurine (lue de la datasheet, ou de
`full_unit_data["VALUE"]` quand l'unité n'a qu'une figurine, [ligne 967](../../engine/game_state.py#L967)),
et `enhanced_unit["VALUE"] = total_value` = **somme** des figurines
([ligne 984](../../engine/game_state.py#L984)). C'est ce qui rend §0.9 exact au point près
(Boyz : 9 × 7 + Nob 12 = 75). La donnée par figurine **est donc disponible**, et elle atteint bien
`_build_models_for_unit` : `build_units_cache` itère `for unit in game_state["units"]`, qui sont les
`enhanced_units` produits par cette même fonction ([game_state.py:622-626](../../engine/game_state.py#L622-L626)).
`spec["VALUE"]` est donc **présent sur chaque `model_spec`** au moment où le cache est construit —
aucune plomberie à ajouter pour l'y amener.

📌 **Ce n'est pas un oubli, c'est une dette assumée** : le commentaire
[game_state.py:977-983](../../engine/game_state.py#L977-L983) énumère explicitement, parmi les
consommateurs de `VALUE`, « les usages par-figurine **qui divisent déjà par
`model_count_at_start`** (`points_per_hp`, reward par fig tuée) ». L'auteur de §0.9 a donc vu la
moyenne et l'a laissée en place. Cette section ne corrige pas une régression : elle **solde** cette
dette, devenue mesurable maintenant que les escouades sont hétérogènes en points.

**Où la chaîne casse — 3 ruptures, toutes vérifiées.**

> 🔴 **CE RECENSEMENT ÉTAIT INCOMPLET — corrigé le 2026-07-20.** Il en manquait une **4ᵉ**,
> côté **observation**, qui n'est pas une rupture préexistante mais une **régression créée par
> les étapes A/B elles-mêmes**. Voir « Rupture D » en fin d'entrée. Leçon de méthode : le grep
> des consommateurs de `points_per_hp` avait bien remonté le site
> ([observation_builder.py:1498](../../engine/observation_builder.py#L1498)) — **il a été vu et
> non ouvert**, parce que la ligne semblait ne concerner que le reward. Un consommateur listé
> par un grep et non lu compte comme non audité (§0bis).

| # | Emplacement | Ce que fait le code | Conséquence |
|---|---|---|---|
| A | [shared_utils.py:632-674](../../engine/phase_handlers/shared_utils.py#L632-L674) (`_build_models_for_unit`) | `models_cache[model_id]` est construit **sans aucune clé `VALUE`** — `spec["VALUE"]` n'est jamais lu | La valeur par figurine **s'arrête à `_build_enhanced_unit`** et n'atteint jamais le moteur de combat |
| B | [shared_utils.py:629](../../engine/phase_handlers/shared_utils.py#L629) + [:666](../../engine/phase_handlers/shared_utils.py#L666) | `points_per_hp = VALUE_escouade / total_hp_pool` calculé **une seule fois**, puis recopié **identique** sur chaque figurine | Un HP retiré au Nob (12 pts) vaut exactement autant qu'un HP retiré à un Boy (7 pts) |
| C | [reward_calculator.py:1020-1022](../../engine/reward_calculator.py#L1020-L1022) (`_squad_combat_shaping`) | figurine détruite → `meta["value"] / model_count_at_start`, soit la **moyenne d'escouade** | Tuer l'aumônier (75) rapporte autant qu'un Intercessor (16) |

Rupture corollaire : **les events ne transportent pas la valeur**. L'event est construit en
**un seul endroit dans tout le moteur** — [shared_utils.py:6309-6313](../../engine/phase_handlers/shared_utils.py#L6309-L6313),
dans `_resolve_one_manual_wound` — et ne porte que `points_per_hp`, `damage`, `destroyed`,
`target_squad_id`, `target_player`. Aucune clé `model_value` / `destroyed_model_value` n'existe
nulle part. Même corrigé en A/B, le reward n'aurait **rien à lire** au moment de la destruction.

> ✅ **Bonne nouvelle vérifiée — le correctif C est beaucoup plus petit que prévu.** Le moteur
> d'allocation est **mutualisé tir/combat** via `ManualAllocCtx` : `fight_handlers.py` ne construit
> **aucun** event, il réutilise `_resolve_one_manual_wound`. **Un seul site à modifier**, pas deux.
> Et surtout : à cet endroit la variable `m` **est le dict de la figurine touchée** (c'est d'elle
> qu'est déjà lu `points_per_hp`, [ligne 6282](../../engine/phase_handlers/shared_utils.py#L6282)).
> Une fois A fait, `m["VALUE"]` est **directement en main** — il n'y a donc **pas besoin de passer
> par `targets_meta`** ni de toucher aux deux sites qui le construisent
> ([shared_utils.py:6130](../../engine/phase_handlers/shared_utils.py#L6130),
> [fight_handlers.py:5707](../../engine/phase_handlers/fight_handlers.py#L5707)). `targets_meta`
> reste ce qu'il doit rester : le porteur des données d'**escouade** (`value`,
> `model_count_at_start`, `player`), consommées par le bonus de wipe.

**Pourquoi ça compte maintenant.** L'allocation des pertes 05.03 (`Documentation/40k_rules/05 -
Attack sequence`) laisse au défenseur le choix de la figurine qui encaisse, et le ciblage
volontaire d'une figurine de valeur est donc une **décision de jeu réelle**. Avec la moyenne
d'escouade, le reward est **plat** sur cette décision : l'agent n'a aucun signal l'incitant à
concentrer le feu sur le Nob, le Sergent ou le personnage attaché. C'est précisément l'effet que
§0.9 rend mesurable, puisque les escouades sont désormais **hétérogènes en points**.

**Ce qui NE doit PAS changer.**
- Le bonus de wipe ([reward_calculator.py:1026](../../engine/reward_calculator.py#L1026)) est
  **déjà correct** : `meta["value"] * squad_kill_bonus_factor` = valeur de l'ESCOUADE, ce qui est
  la sémantique voulue (« l'escouade entière est détruite »). **Ne pas le convertir par figurine.**
- Les **unités mono-figurine** doivent rester **bit-identiques**. Le vérifier plutôt que le
  supposer : `model_count_at_start = 1` ⇒ `value / 1` = `VALUE` de l'unique figurine (posée par
  [game_state.py:967](../../engine/game_state.py#L967)) ; et `total_hp_pool = HP_MAX` ⇒
  `points_per_hp = VALUE / HP_MAX`, identique au per-fig. Les deux formules coïncident — mais
  cela doit être **verrouillé par un test**, pas par ce paragraphe.

⚠️ **Piège de vérification.** L'énoncé naïf « dans le cas homogène la somme doit être inchangée »
est **faux tel quel** : depuis §0.9, une escouade homogène en profil (même `HP_MAX`, même
datasheet) peut être **hétérogène en `VALUE`** — c'est exactement le cas des Boyz (9 × 7 + 12).
L'invariant à tester est donc « **`VALUE` uniforme sur toutes les figurines** ⇒ résultat identique
à l'ancienne formule », pas « même profil ⇒ identique ». Construire le test sur une escouade à
`VALUE` réellement uniforme (Gretchin : 10 × 5), sinon il passera pour la mauvaise raison.

**Travail attendu, dans l'ordre (chaque étape est vérifiable seule) :**
1. **A** — porter `spec["VALUE"]` dans `models_cache` (`_build_models_for_unit`). Source =
   `spec["VALUE"]`, **jamais** `unit["VALUE"]` (valeur d'escouade). Absence de la clé ⇒ `require_key`,
   **pas de défaut** (règle CLAUDE.md : pas de valeur par défaut masquant une donnée absente).
2. **B** — `points_per_hp` **par figurine** = `VALUE_i / HP_MAX_i`, calculé **dans la boucle**
   `for idx, spec in enumerate(model_specs)`. Supprimer le calcul unique ligne 629 et l'agrégat
   `total_hp_pool`, qui n'a alors plus qu'un usage : la **validation** `spec_hp_max <= 0`
   ([ligne 626](../../engine/phase_handlers/shared_utils.py#L626)) — la garder, en la déplaçant
   dans la boucle unique. Mettre à jour la docstring
   [shared_utils.py:580-583](../../engine/phase_handlers/shared_utils.py#L580-L583), qui documente
   encore la formule d'escouade.
   🔻 **Au passage, supprimer un fallback existant** : `... if total_hp_pool > 0 else 0.0`
   ([ligne 629](../../engine/phase_handlers/shared_utils.py#L629)) est une **valeur par défaut
   masquant une erreur** — branche morte, puisque la ligne 626 vient de lever sur tout
   `spec_hp_max <= 0` et que `model_specs` est non vide par construction. Interdit par CLAUDE.md ;
   ne pas le reconduire sur la formule par figurine (`HP_MAX_i` est déjà validé > 0 juste avant).
3. **C** — ajouter la valeur de la figurine détruite à l'**event**, à l'unique site
   [shared_utils.py:6309](../../engine/phase_handlers/shared_utils.py#L6309) (lire `m["VALUE"]`,
   comme `points_per_hp` juste au-dessus), puis remplacer `value / mcs` par cette valeur dans
   `_squad_combat_shaping`. `model_count_at_start` n'est alors plus lu que par le garde `mcs > 0`
   ([reward_calculator.py:1021](../../engine/reward_calculator.py#L1021)), qui **disparaît avec la
   division** — c'est un garde anti-`ZeroDivisionError`, pas une règle métier. Mettre à jour le
   docstring [reward_calculator.py:1006](../../engine/reward_calculator.py#L1006), qui énonce
   encore `(value / model_count_at_start)`.
4. **Tests** — invariant mono-figurine, invariant `VALUE` uniforme (cf. piège ci-dessus), et un cas
   **hétérogène** prouvant que tuer la figurine chère rapporte strictement plus. Suite complète
   attendue verte ; ⚠️ *(affirmation périmée n°6 de §0bis : contredit §0.-1, non vérifiée)* le dossier de rosters de training étant réduit à 2 fichiers, **9 tests liés
   à `roster_pool_schedule` échouent indépendamment de ce travail** — les valider sur un worktree
   propre à HEAD avant de conclure à une régression.

**Note connexe, hors périmètre de ce point.** L'affirmation de §0.9 (« `VALUE` est consommé **par
figurine** — pondération de menace [reward_calculator.py:1442](../../engine/reward_calculator.py#L1442) »)
est **inexacte** : cette ligne lit `friendly["VALUE"]`, soit la valeur de l'**escouade**. La règle
métier 🔒 de §0.9 (suivre le Munitorum, ne pas tuner) reste valable telle quelle ; seule la
justification technique citée est à requalifier.

---

**Ce qui a été livré (2026-07-20) — vérifié, pas supposé.**

| Étape | Fichier | Ce qui a changé |
|---|---|---|
| **A** | [shared_utils.py](../../engine/phase_handlers/shared_utils.py) `_build_models_for_unit` | `models_cache[model_id]["VALUE"] = spec_value`, lu par `require_key(spec, "VALUE")` — **aucun défaut**. Le spec synthétique du chemin **mono-figurine** (unité sans `models[]`) reçoit `"VALUE": value`, ce qui est exact par construction : pour une mono-fig, valeur d'escouade = valeur de la figurine. |
| **B** | idem | `points_per_hp = VALUE_i / HP_MAX_i` calculé **dans la boucle** `for idx, spec`. Supprimés : le calcul unique hors boucle, l'agrégat `total_hp_pool`, **et le fallback `if total_hp_pool > 0 else 0.0`** (valeur par défaut masquante, interdite CLAUDE.md). La validation `spec_hp_max <= 0` a été **déplacée dans la boucle unique**, pas supprimée — verrouillé par `test_hp_max_invalide_leve_toujours`. Docstring réécrite. |
| **C** | idem `_resolve_one_manual_wound` + [reward_calculator.py](../../engine/reward_calculator.py) `_squad_combat_shaping` | L'event porte `"model_value": float(require_key(m, "VALUE"))` — **un seul site** dans tout le moteur, comme prévu (allocation mutualisée tir/combat via `ManualAllocCtx`). Le reward lit `require_key(ev, "model_value") * kill_f` ; `value / mcs` et le garde `mcs > 0` ont disparu. Docstring mise à jour. |

**Tests** — [test_model_value_per_figurine.py](../../tests/unit/engine/test_model_value_per_figurine.py), **14 tests**, trois classes (la 3ᵉ, `TestObservationValueOverTtk`, couvre la rupture D décrite plus bas) :
- `models_cache` : mono-fig inchangé ; **`VALUE` uniforme** (Gretchin 10 × 5) ⇒ identique à l'ancienne formule (c'est bien l'invariant du piège ci-dessus, pas « même profil ») ; **hétérogène** (Boyz 9 × 7 + Nob 12) ⇒ `points_per_hp` 7 vs 12, et assertion explicite que la moyenne 7.5 **n'apparaît plus** ; `HP_MAX` hétérogène ; `VALUE` absente ⇒ lève ; `HP_MAX <= 0` ⇒ lève.
- `_squad_combat_shaping` : mono-fig bit-identique ; `VALUE` uniforme bit-identique ; **figurine chère > figurine bon marché** (`hp_damage_weight = 0` pour **isoler le terme de kill** — sans ça le test passait pour la mauvaise raison, via le terme HP) ; **le bonus de wipe reste sur la valeur d'ESCOUADE** ; event sans `model_value` ⇒ lève ; garde `is_victim` intacte.

**Mutation-testé.** Réintroduire l'ancienne formule (B : `value / (hp_max * len(model_specs))` ; C : `value / mcs`) rend rouges `test_value_heterogene_differencie_les_figurines`, `test_hp_max_par_figurine_divise_bien_par_son_propre_hp`, `test_figurine_chere_rapporte_strictement_plus` et `test_event_sans_model_value_leve`.

⚠️ **Effet de bord rencontré, à connaître.** `require_key(spec, "VALUE")` a cassé **48 tests dans 2 fichiers** (`test_squad_fight_declaration.py`, `test_squad_shoot_declaration.py`) : leurs fixtures appellent `build_units_cache` **directement**, sans passer par `_build_enhanced_unit` qui est le seul producteur de `VALUE` par figurine. Corrigé en ajoutant `"VALUE"` au helper `_m` des deux fichiers — **pas** en assouplissant `require_key`. **Aucun chemin de production n'était concerné** : les 3 producteurs de `models[]` en prod (`game_state.py:210`, `:738`, `:1840`) alimentent tous des unités qui passent ensuite par `_build_enhanced_unit`.

**Rupture D — l'observation de l'agent, régression introduite par A/B (trouvée et corrigée le 2026-07-20).**

| | |
|---|---|
| Emplacement | [observation_builder.py:1496-1505](../../engine/observation_builder.py#L1496-L1505), calcul de `value_over_ttk` (slot ennemi, `obs[base + 7]`) |
| Ce que faisait le code | `ppl = models_cache[e_mids[0]]["points_per_hp"]` puis `e_value = ppl * e_hp_total` — le `points_per_hp` de la **figurine d'index 0** extrapolé à toute l'escouade |
| Pourquoi c'était juste AVANT | `points_per_hp` était **uniforme par construction** : `ppl × HP_total` valait exactement la `VALUE` d'escouade |
| Pourquoi A/B l'ont cassé | `points_per_hp` devient **hétérogène**. Boyz (9 × 7 + Nob 12) : `7 × 10 = 70` au lieu de 75. L'erreur dépend de **qui est en index 0** — un personnage attaché cher en tête ferait sur-évaluer toute l'escouade |
| Portée | **L'observation de l'agent** (`value_over_ttk` = sa perception de la valeur des cibles) — soit exactement ce que §0.12 prétendait améliorer |
| Correctif | `e_value = Σ points_per_hp_i × HP_CUR_i` sur les figurines vivantes. Même sémantique qu'avant (décroît avec les blessures), calculée par figurine. **Le fallback `.get(..., 0.0)` et le `try/except Exception` ont été supprimés** — c'est précisément ce masquage qui a rendu la régression silencieuse |

Tests : `TestObservationValueOverTtk` (2 de plus, **14 au total** dans le fichier). L'invariant
choisi est le plus fort disponible — **le résultat ne doit pas dépendre de l'ORDRE des
figurines** : Nob en index 0 vs index 9 ⇒ même `value_over_ttk`. **Mutation-testé** : restaurer
`ppl * e_hp_total` rend `test_invariant_a_lordre_des_figurines` rouge.

⚠️ **Conséquence sur les mesures** : le run de 500 épisodes de **§0.14 a tourné AVANT ce
correctif**, donc sur une observation fausse pour toute escouade hétérogène — c'est-à-dire pour
les deux rosters de [§10.2](V11_eval_strategy.md#s10.2). Son score est à jeter pour cette raison **en plus** de celle déjà
notée (12 épisodes d'éval).

📌 **Réserve non traitée** (hors périmètre §0.12) : la variable locale `model_count_at_start` de `_build_models_for_unit` est **inutilisée** — elle l'était déjà avant ce travail, ce n'est pas une séquelle. Non supprimée.


### 0.13 Run de validation x5_debug 100 ép. — ✅ pipeline OK / éval finale sur le mauvais pool — ✅ CORRIGÉ (2026-07-20)

**Le run.** `x5_debug` reparamétré par l'utilisateur (100 épisodes, `bot_eval_freq: 50`,
`bot_eval_final: 2`), lancé après les fixes §0.10 et §0.11 :
**100/100 épisodes, exit 0, aucune exception**, ~114 s/ép. à 8 envs (28 min). Éval finale
exécutée, modèle écrasé (autorisation utilisateur explicite) — `model_ArmageddonAgent.zip`
au 2026-07-20 02:14.

> ➜ **Déplacé en §0.14 (ouvert).** Rien n'a été supprimé : le contenu est intégral là-bas.

⚠️ **Piège de perf, à ne pas re-diagnostiquer** : l'ETA affichée au 1ᵉʳ épisode (~16 h 45 sur le
run de 1000) est un **artefact de warmup** ; elle retombe à sa vraie valeur dès le 10ᵉ épisode.
Ne jamais extrapoler une durée de run depuis les premiers épisodes.

---

🔴 **BUG VÉRIFIÉ — l'évaluation FINALE ignore `bot_eval_scenario_pool` et tourne sur le scénario
d'ENTRAÎNEMENT.**

**Preuve dans la sortie du run** : `🏁 Scenario ranking (combined): - training_armageddon`,
alors que la config demande `holdout`.

**Root cause, 5 sites d'appel de `evaluate_against_bots` audités un par un :**

| Site | `scenario_pool` transmis |
|---|---|
| [train.py:3012](../../ai/train.py#L3012) | ✅ `"holdout"` (en dur) |
| [train.py:4257](../../ai/train.py#L4257) | ✅ `"holdout"` (en dur) |
| [train.py:4646](../../ai/train.py#L4646) | ✅ `"holdout"` (en dur) |
| [training_callbacks.py:2449](../../ai/training_callbacks.py#L2449) | ✅ `self.scenario_pool` (éval **intermédiaire**, alimentée par [train.py:3428](../../ai/train.py#L3428)) |
| [training_callbacks.py:1024](../../ai/training_callbacks.py#L1024) `_run_final_bot_eval` | 🔴 **RIEN** → défaut de signature |

La signature déclare `scenario_pool: str = "training"`
([bot_evaluation.py:744](../../ai/bot_evaluation.py#L744)). **Un seul site sur cinq oublie le
paramètre, et une valeur par défaut masque l'oubli** — interdit par CLAUDE.md, et exactement la
famille T6-a / T6-b / T6-e : *migration partielle d'un chemin, un site oublié, aucun message*.

**Conséquences :**
1. **Le score `Combined 0.46` de ce run ne vaut RIEN pour [§10.6](V11_eval_strategy.md#s10.6)** : mesuré sur le scénario
   d'entraînement, pas sur le holdout. Le contrat [§10.5](V11_eval_strategy.md#s10.5) est contourné sur ce chemin.
2. De toute façon, à **1 épisode par bot** (3 victoires / 3 défaites), c'est du bruit pur —
   ne pas l'interpréter même une fois le pool corrigé.
3. Tout « best model » retenu par un gating adossé à cette éval l'aurait été sur le mauvais
   jeu (sans effet ici : `model_gating_enabled: false` et `save_best_min_episodes` > 100).

**✅ CORRIGÉ (2026-07-20).** `_run_final_bot_eval` passe désormais `scenario_pool="holdout"`
explicitement ([training_callbacks.py:1024](../../ai/training_callbacks.py#L1024)).

**Pourquoi en dur plutôt que résolu depuis la config** (arbitrage tranché, ne pas rouvrir) :
l'éval finale est une éval de **MESURE**, elle doit porter sur le holdout par contrat [§10.5](V11_eval_strategy.md#s10.5) —
comme les 3 autres sites de mesure (`train.py:3012`, `:4257`, `:4646`), qui codent déjà la même
valeur en dur. La clé de config `bot_eval_scenario_pool` n'alimente, elle, que l'éval
**INTERMÉDIAIRE** (gating en cours d'entraînement), où un pool `training` peut se défendre.
Re-résoudre depuis la config ici aurait dupliqué la logique de layering
(`callback_params` → `_training_common.json`) pour aboutir à la même valeur.
`MetricsCollectionCallback` n'a pas d'attribut `scenario_pool` et n'en a donc pas besoin.

**Non-régression** : `tests/unit/ai/test_final_eval_uses_holdout.py`, **2 tests**, tous deux
**rouges avant le fix** (vérifié par `git stash` du seul fichier source) :
1. **comportemental** — `_run_final_bot_eval` est réellement appelée, `evaluate_against_bots`
   interceptée (patch sur `ai.bot_evaluation`, car l'import est *lazy* dans la méthode), et
   l'argument reçu est `holdout` ;
2. **de contrat** — parcours AST de `train.py` + `training_callbacks.py` : **aucun** appel à
   `evaluate_against_bots` ne doit omettre `scenario_pool`. Il attraperait la réintroduction du
   bug sur un site que le test comportemental ne couvre pas, et pointe le site fautif par
   fichier:ligne. Il commence par vérifier que le défaut de signature vaut bien `"training"` —
   si quelqu'un le change, le test le signale au lieu de devenir silencieusement sans objet.

Suite complète verte (exit 0).

> ➜ **Déplacé en §0.14 (ouvert).** Rien n'a été supprimé : le contenu est intégral là-bas.

⚠️ **Piège latent voisin, découvert au passage.** Dans
`ArmageddonAgent_training_config.json`, `bot_eval_scenario_pool` est placé à la **racine** de
`x5_debug`, alors que `_resolve_callback_value` ([train.py:3273](../../ai/train.py#L3273)) le
cherche dans **`callback_params`** puis retombe sur `config/agents/_training_common.json`.
La clé racine est donc **ignorée**. Sans effet aujourd'hui (les deux valent `holdout`), mais
toute surcharge par agent placée à la racine serait **silencieusement sans effet**.

### 0.18 `collision intra-plan` — cause trouvée dans le pile-in — ✅ CORRIGÉ (2026-07-20)

> ✅ **RÉSOLU le 2026-07-20.** L'écrivain fautif est identifié, le bug **reproduit par un test**
> (pas par un run), corrigé sur ses **deux** consommateurs, et la suite complète est verte.
> La part autrefois ouverte (ordre glouton, B2B non maximal) est **également corrigée** — voir **§0.21**.
> ⚠️ Entrée conservée ici et **non descendue en §0hist** tant que la session écrit dans ce
> fichier ; l'énoncé d'origine ci-dessous est celui du diagnostic, conservé intégralement.

**Cause racine — `fight_pile_in_plan` ([shared_utils.py:6989](../../engine/phase_handlers/shared_utils.py#L6989)).**
Trois défauts cumulés faisaient qu'une cellule occupée par une camarade était vue comme libre :

| # | Défaut | Site |
|---|---|---|
| 1 | `occupied_after` démarrait **vide** — non amorcé avec les origines de l'escouade | [:6989](../../engine/phase_handlers/shared_utils.py#L6989) |
| 2 | `_cell_legal` **saute sa propre escouade** quand il teste l'occupation (`if str(sid) == squad_id: continue`) | [:7009-7010](../../engine/phase_handlers/shared_utils.py#L7009-L7010) |
| 3 | La branche « déjà B2B → reste sur place » `append` son origine **sans appeler `_cell_legal`** | [:7020-7022](../../engine/phase_handlers/shared_utils.py#L7020-L7022) |

**Scénario.** S#0, traitée en premier, choisit la cellule X : légale, car X appartient à sa
propre escouade (2) et `occupied_after` est encore vide (1). Mais X est l'origine de S#1, traitée
plus tard, qui y est déjà B2B et **reste sur place sans contrôle** (3). Les deux finissent sur X.
Le plan étant un 3-tuple, le niveau est inchangé pour les deux → même `(col, row, niveau)`.
Ni la « validation finale » ([:7073-7089](../../engine/phase_handlers/shared_utils.py#L7073-L7089),
qui ne teste que cohérence et zone d'engagement) ni `commit_move` (« ne re-valide pas », par
contrat, [:4284](../../engine/phase_handlers/shared_utils.py#L4284)) ne rattrapent.

**Pourquoi ça n'explosait qu'au move suivant.** Exactement ce que le diagnostic ci-dessous
démontrait : la translation cube de `build_rigid_plan` est **injective**, donc la superposition
d'origine se reporte sur chaque destination et `validate_move_plan` la voit — une phase trop
tard, sous la forme d'un `collision intra-plan` qui accusait le move.

**Second consommateur : `squad_consolidate_plan`** ([:7316](../../engine/phase_handlers/shared_utils.py#L7316)).
Même défaut, trouvé en corrigeant le premier. Pas de branche B2B ici : la collision naît de la
branche « rien de mieux → reste sur place » ([:7364-7365](../../engine/phase_handlers/shared_utils.py#L7364-L7365)),
dont l'origine a pu être prise entre-temps. *Un bug, deux consommateurs* — même famille que T6-h.

**Correctif — l'affectation gloutonne est remplacée par un COUPLAGE MAXIMUM.** Le parcours dans
l'ordre des index est supprimé : il était à la fois la cause de la collision *et* une violation
de 12.03 (cf. §0.21). L'algorithme est désormais :

1. **Immobiles** — figurines au contact socle à socle : elles restent, leur cellule est
   définitivement réservée (12.03 WHILE MOVING, « Models in base-contact … **cannot be moved** »).
2. **Couplage maximum** figurine → cellule bord-à-bord (algorithme de Kuhn,
   `_max_b2b_matching`), qui réalise exactement l'obligation « engaged with it **if possible** »
   et l'intention « **maximise** the number of models that are engaged ». **Indépendant de
   l'ordre**, donc la classe de bug d'origine ne peut plus se reformer.
   Une cellule qui est l'origine d'une camarade n'est utilisable que si celle-ci la quitte :
   point fixe monotone (`blocked` décroît strictement), sans collision à **chaque** itération.
3. **Repli** pour les non-couplées : finir strictement plus proche, sinon rester sur place
   (le pile-in est optionnel — encart 12, « you don't have to pile in »).

`mids` ne contient que des figurines **vivantes** — vérifié : `destroy_model` retire l'entrée de
`models_cache` **et** de `squad_models`
([:3213-3221](../../engine/phase_handlers/shared_utils.py#L3213-L3221)) — donc aucune cellule de
cadavre n'est réservée.

**SOURCE UNIQUE.** Pile-in et consolidation partagent `_assign_cells_toward_enemies` : 12.03 et
12.08 (modes Ongoing et Engaging, lus dans le PDF) portent la **même** obligation. La
duplication est ce qui avait permis au bug d'exister en deux exemplaires ; la supprimer est le
correctif structurel. ➜ **Corrige au passage un point de règle jamais implémenté** :
`squad_consolidate_plan` ne respectait pas « Models in base-contact … cannot be moved ».
L'appliquer inconditionnellement est correct — en mode Engaging l'unité n'est pas engagée, donc
aucune figurine n'est au contact et la contrainte est sans objet, jamais fausse.

**Preuves.**

| Élément | Preuve |
|---|---|
| Reproduction | `tests/unit/engine/test_pile_in_intra_squad_collision.py` — rouge sur le code d'avant : `[('S#0',10,9), ('S#1',10,9)]` |
| Optimalité (12.03) | **Mutation-testé** : couplage remplacé par un glouton → **1 figurine engagée sur 2** ; couplage → **2 sur 2** |
| Correctif consolidation | **Mutation-testé** : neutralisé → rouge, restauré → vert |
| Non-régression | Suite `tests/unit` complète, **exit 0** |
| Chemin PvP | **Non concerné**, vérifié dans le code (order-independent par construction) |

⚠️ **Ce que ça ne prouve PAS** : que le training va au bout. Aucun run long n'a été relancé
depuis le correctif. La leçon de cette entrée s'applique à elle-même — il faudra **2-3 runs**,
un run vert ne valant pas preuve (§0.14).

⚠️ **Le test de non-régression du second test a failli passer pour la mauvaise raison** : sans
murer cinq hex pour priver la figurine de toute alternative, il passait **déjà avant** le
correctif. Motif §0.19 rencontré en direct.

---

**Énoncé d'origine (diagnostic du 2026-07-20, conservé intégralement) :**

**Reproduction.** Commande **identique** à celle de §0.14, relancée après le correctif de la
rupture D (§0.12) :

```
python3 ai/train.py --agent ArmageddonAgent --scenario bot --new \
        --training-config x5_debug --total-episodes 500
```

Arrêt à l'**épisode ~280** (worker `SubprocVecEnv` mort → `EOFError` côté maître → `💥 Fatal
error`) :

```
ValueError: execute_squad_move a échoué : squad=104 type=advance dest=(137,212)
depuis (135,180) — la destination vient du pool BFS du masque, elle DOIT être exécutable
(incohérence masque/exécution). Contrainte violée : collision intra-plan :
deux figurines en (147,227) niveau 0 (dont 104#5)
```

⚠️ **Le premier run de §0.14 avait passé les 500 épisodes.** Même commande, même seed de config.
La divergence vient du correctif D, qui change l'observation, donc la politique, donc les
trajectoires. **Leçon : sur ce crash, « un run est passé » n'est PAS une preuve de
non-régression** — il faut plusieurs runs, ou une preuve statique.

**Ce qui est DÉMONTRÉ (pas supposé) — la collision préexistait au move.**

`build_rigid_plan` ([shared_utils.py:3312](../../engine/phase_handlers/shared_utils.py#L3312))
translate en **cube** : `cube_to_offset(mx + dcx, my + dcy, mz + dcz)`.
`offset_to_cube`/`cube_to_offset` ([hex_utils.py:92](../../engine/hex_utils.py#L92)) sont
**bijectives**, et la translation cube est une **injection** : deux positions distinctes restent
distinctes. Par ailleurs le plan qu'elle produit est un **3-tuple sans niveau**, donc
`_target_level` relit le niveau **du `models_cache`**, inchangé par le move.

⇒ **Une collision intra-plan sur un plan rigide implique une collision à l'ORIGINE** : deux
figurines de l'escouade 104 occupaient **déjà** la même `(col, row, niveau)` avant le move. Le
crash n'est donc **pas** un défaut de la translation (T6-h), ni du pool BFS ou de son érosion
(T6-g) : **le masque et l'exécution sont d'accord — c'est l'état de départ qui est invalide.**
Le fix de §0.11 (clé `(niveau, col, row)`) reste correct ; il traitait un **autre** cas.

**Ce qui n'est PAS identifié.** *Quel* écrivain de positions produit la superposition. Le
soupçon porte sur un chemin qui écrit dans `models_cache` **sans passer par
`validate_move_plan`** — pile-in / consolidation, retrait de coherency (03.03), déploiement —
mais **rien n'a été vérifié**, et ce document interdit d'ouvrir un chantier sur une intuition
(§0bis). C'est le point de départ du prochain travail.

**Piste d'instrumentation suggérée** (à valider avant de coder) : faire dire au message d'erreur
**les positions d'ORIGINE** des deux figurines en cause, pas seulement leur destination. Si
elles sont identiques, la démonstration ci-dessus est confirmée en runtime et le crash devient
un simple révélateur ; l'invariant « deux figurines vivantes d'une même escouade n'occupent
jamais la même `(col, row, niveau)` » mérite alors d'être vérifié **à l'écriture**, au plus près
du fautif, plutôt qu'au move suivant.

~~⚠️ **Bloquant** : aucun run long ne va au bout de façon fiable, donc **§0.14 et le critère [§10.6](V11_eval_strategy.md#s10.6)
sont bloqués derrière cette entrée**.~~ ➜ **LEVÉ le 2026-07-20** par le correctif ci-dessus.
§0.14 est **débloquée** — sous réserve des 2-3 runs qui restent à faire.

📌 **Note annexe** : après ce crash le process a affiché `💥 Fatal error` et se serait terminé
avec un **code de sortie 0**. ➜ **Affirmation DÉMENTIE le 2026-07-20, voir §0.20** — le code
sort bien en 1, vérifié statiquement et par exécution. Aucun fix n'est requis.

### 0.20 « Le crash sort en code 0 » — ✅ DÉMENTI, AUCUN FIX REQUIS (2026-07-20)

**Origine.** La note annexe de §0.18 affirmait que le training, après `💥 Fatal error`, se
terminait avec un **code de sortie 0** — donc qu'un échec passait pour un succès auprès de toute
automatisation. L'entrée a été ouverte pour corriger ce piège. **L'investigation l'a démentie.**

**Ce qui a été vérifié (statique).**

| Site | Constat |
|---|---|
| [train.py:5033-5037](../../ai/train.py#L5033-L5037) | Le handler qui imprime `💥 Fatal error` fait `return 1`. |
| [train.py:5039-5041](../../ai/train.py#L5039-L5041) | `sys.exit(exit_code)` — le 1 est propagé au shell. |
| `ai/train.py`, `ai/env_wrappers.py`, `ai/training_callbacks.py` | **Aucun autre** `sys.exit` / `os._exit`, et **aucun** handler `EOFError` / `BrokenPipe` qui pourrait avaler le code. |
| `train_model` | Retourne `False` sur exception ; `main` en tire `return 1`. Pas de chemin qui rendrait 0 après une exception. |

**Ce qui a été vérifié (exécution).** `python3 ai/train.py --agent AgentQuiNExistePas --scenario
bot --new --total-episodes 1` → imprime `💥 Fatal error: No config directory found…` et
**sort en 1** (`EXIT=1`).

**Cause probable de l'observation d'origine — non tranchée.** Une mesure côté shell : un
`| tee` (ou tout pipe) renvoie le code de sortie du **dernier** élément du pipeline, pas celui
de python. Impossible de trancher sans le shell exact du run de §0.18.

⚠️ **Leçon.** Cette entrée a failli devenir un chantier de fix sur un bug **qui n'existe pas**,
sur la seule foi d'une note d'observation non revérifiée — et c'est un lecteur, pas l'auteur,
qui a demandé « la doc prévoit-elle de le fixer ? ». Le motif n°1 du document s'applique aussi
aux notes marquées « hors périmètre » : **elles échappent à la relecture précisément parce
qu'elles sont marquées annexes.**

### 0.21 Pile-in / consolidation : ordre glouton, B2B non maximal — ✅ CORRIGÉ (2026-07-20)

> Ouverte **et fermée le même jour**. Elle avait été rédigée comme une dette d'algorithme
> (« correct mais pas optimal ») ; l'utilisateur a refusé ce mode de clôture, et l'optimum a été
> implémenté. ➜ **C'est l'origine de la règle 7 de `CLAUDE.md`** (« CLÔTURE COMPLÈTE DES
> SUJETS ») : une dette n'est ouvrable que si le traitement est *techniquement impossible* dans
> la session, jamais parce qu'il est plus long.

**Ce qui était en dette.** `fight_pile_in_plan` et `squad_consolidate_plan` attribuaient les
cellules **dans l'ordre des index**. Le placement était légal, mais pas maximal : une figurine
pouvait se voir refuser une cellule qu'une figurine suivante allait libérer, ou prendre la seule
cellule accessible à une autre. Or 12.03 / 12.08 WHILE MOVING imposent :

> ▪ Each model that is moved must end its move closer to the closest [target], and
>   **engaged with it if possible**.

et l'encart du même PDF donne l'intention : « units will pile in to **maximise** the number of
models that are engaged ». **Un glouton ne satisfait pas cette obligation** — ce n'était donc
pas un simple manque d'optimalité, mais une violation de règle.

**Correctif.** Couplage maximum (Kuhn) — voir §0.18, section « Correctif », pour l'algorithme
complet et la source unique partagée avec la consolidation.

**Preuve — mutation-test.** Couplage remplacé par une affectation gloutonne sur le scénario
`test_greedy_order_does_not_cost_an_engagement` : **1 figurine engagée sur 2**. Avec le
couplage : **2 sur 2**. Le test verrouille donc l'optimalité, pas seulement l'absence de
collision.

<a id="s0.15"></a>
### 0.15 Rosters `training` ≡ `holdout_regular` — ✅ TRANCHÉ (2026-07-21 : identité ASSUMÉE)

> Part **ouverte** de §0.6. La suppression des listes holdout mortes, elle, est résolue — voir
> §0.6 pour la décision et sa justification.

⚠️ **Les rosters `training` et `holdout_regular` sont IDENTIQUES** (vérifié : mêmes compositions,
mêmes totaux, aux deux emplacements). C'est cohérent avec la décision [§10.5](V11_eval_strategy.md#s10.5) — le holdout porte sur
l'**adversaire**, pas sur le roster — mais il faut en avoir conscience : **il n'existe aucune
séparation de listes entre entraînement et évaluation**. Un sur-apprentissage sur les
particularités de ces deux listes ne serait détecté par aucun des scénarios d'éval actuels.

**Statut** : ✅ **TRANCHÉ le 2026-07-21 — l'utilisateur ASSUME l'identité** (« Oui : rosters
training ≡ holdout_regular »). Le holdout porte donc **exclusivement sur l'adversaire** ([§10.5](V11_eval_strategy.md#s10.5)),
jamais sur le roster : c'est cohérent avec la démo de financement (2 rosters fixes SM/Orks, [§10.2](V11_eval_strategy.md#s10.2))
et avec la spécialisation assumée. **Conséquence à garder en tête** : aucun scénario d'éval ne
détectera un sur-apprentissage sur les particularités de ces deux listes ; le win-rate par matchup
mesure la robustesse à l'**adversaire**, pas au roster. Ce n'est pas un angle mort à corriger,
c'est le périmètre choisi.

### 0.16 Réserves de l'évaluation — ✅ SOLDÉE (2026-07-21 ; extraits de §0.5, §0.6 et §0.7)

> Trois réserves distinctes, aucune bloquante aujourd'hui, toutes déjà constatées. Leurs
> entrées d'origine (§0.5 fail-fast, §0.6 listes holdout, §0.7 run 60/60) sont résolues par
> ailleurs.

**(a) Réserves du fail-fast `--eval` (ex-§0.5)**

Réserves :
- ✅ **CORRIGÉE (2026-07-21)** — Le bloc `🏁 Scenario ranking` s'imprimait **avant** le raise
  eval-only sur `total_failed_episodes > 0` : quand des épisodes échouaient, les `combined`/
  `worst_bot_score` par scénario (calculés sur un dénominateur **tronqué** — épisodes plantés
  retirés par `_get_result_with_timeout`) étaient présentés comme un classement fiable juste
  avant que la mesure ne soit invalidée. **Root cause** : la décision d'affichage n'était pas
  gardée par la fiabilité de l'éval. **Fix** : décision extraite dans le helper pur
  `_render_scenario_ranking(scenario_scores, total_failed_episodes)`
  ([bot_evaluation.py](../../ai/bot_evaluation.py)) — si `total_failed_episodes > 0`, il retourne
  un **avertissement explicite** (`⚠️ Scenario ranking SUPPRIMÉ : évaluation NON FIABLE`) au lieu
  du classement, jamais un chiffre. Vaut pour le training ET l'eval-only (les deux passent par ce
  print quand `show_summary`). **Verrou** : 3 tests dans `test_eval_holdout_opponent.py`
  (affichage nominal trié, suppression + avertissement quand `failed>0`, liste vide sans scores) ;
  **mutation** de la garde (`total_failed_episodes > 0` → `False`) → **1 rouge** ciblé, vert après.
- ✅ **CORRIGÉE (2026-07-21)** — `worst_bot_name` du chemin eval-only était calculé sur **toutes**
  les clés de `bot_eval_weights`, `tactical` **inclus**, alors que [§10.5](V11_eval_strategy.md#s10.5) impose son exclusion des
  signaux de sélection. Le poids nul ne protégeait pas ce site (min sur des NOMS). **DEUX sites
  étaient touchés, pas un** : le eval-only ([train.py:4682](../../ai/train.py#L4682)) ET le
  `worst_bot_score` **par-scénario** de [bot_evaluation.py:1180](../../ai/bot_evaluation.py#L1180),
  qui alimente le **gate de curriculum** (`_extract_worst_bot_scores_for_gate`) — donc un vrai
  signal de sélection, pas seulement un affichage. Source unique : helper
  `selection_worst_bot(scores)` dans `training_callbacks.py` (exclut `HOLDOUT_BOT_NAMES`, lève si
  plus aucun bot de sélection). Verrou : 3 tests dans `test_eval_holdout_opponent.py` (lock
  comportemental « holdout=min ne pilote pas worst_bot », lock du `raise`, lock **structurel** que
  les deux sites délèguent au helper) ; **2 rouges sous mutation** du helper, verts après. Le test
  préexistant `test_holdout_bots_excluded_from_every_selection_signal` couvrait metrics_tracker
  mais **manquait ces deux sites** — c'était exactement le trou.

**(b) Le 7ᵉ site du portage n'est pas couvert runtime — ✅ STATUS QUO VALIDÉ (2026-07-21)**

Décision utilisateur : **`DefensiveSmartBot` reste hors éval.** Il avait été retiré délibérément
parce qu'il **sous-performait** ; le réintroduire seulement pour couvrir `_best_target_slot_by_threat`
en runtime n'a pas de justification (et fausserait la composition d'éval, donc `combined` et poids).
Ce site reste couvert par son **test unitaire**, ce qui est jugé suffisant. ➜ Sujet clos, déplacé en
**§0ter — Notes post-implémentation**. (Constat d'origine conservé ci-dessous pour mémoire.)

- Le **7ᵉ site du portage** (`_best_target_slot_by_threat`) n'est couvert que par un test unitaire :
  son appelant `DefensiveSmartBot` n'est pas dans `bot_eval_weights`, donc l'éval ne le joue pas
  (`active_bot_names = tuple(eval_weights.keys())`, [bot_evaluation.py:893](../../ai/bot_evaluation.py#L893)).
  Piège [§10.5](V11_eval_strategy.md#s10.5) : **une liste de poids détermine qui TOURNE, pas seulement qui COMPTE.**

**(c) Clé de config `holdout_hard_opponent_budget_modifier` — ✅ CONSERVÉE DÉLIBÉRÉMENT (2026-07-21)**

Décision utilisateur : **garder la clé ET `scripts/build_holdout_benchmark.py`.** Un holdout à armées
**générées** est prévu **après la démo** (une fois les 2 armées focus terminées). La clé n'est donc pas
« morte » mais **en attente d'usage** : elle n'est simplement pas consommée par le chemin de training
actuel (2 rosters fixes, [§10.2](V11_eval_strategy.md#s10.2)). ➜ Ni la clé ni le script ne sont supprimés ; ce n'est plus une
réserve mais un **choix assumé**. Note en §0ter.

### 0.17 Travail non commité — ✅ CLÔTURÉE (entrée périssable périmée : tout est commité, `git status` propre)

⚠️ **Entrée périssable par nature : la confronter à `git status` / `git log` AVANT de s'en
servir.** Elle a déjà été fermée à tort une fois, rouverte, puis **rendue fausse par les commits
eux-mêmes** — la version précédente listait 6 fichiers « non commités » au moment où ils étaient
commités. Une entrée d'état ne survit pas à l'action qu'elle décrit.

**Session du 2026-07-20 : intégralement commitée**, `HEAD` = `056c948e`, arbre de travail propre.
Quatre lots, du plus indépendant au plus transverse :

| Lot | Commit | Contenu |
|---|---|---|
| A | `47af78f3` | Correctif §0.18/§0.21 — couplage maximum, source unique pile-in/conso, 4 tests |
| B | `ea79e545` | Audit §0.19.2 — 3 replis silencieux de `_ai_select_fight_target`, 6 tests |
| C | `04170652` | Documentation — §0.18/§0.20/§0.21, §0.19.1/§0.19.2, garde d'arbre en §0bis |
| D | `056c948e` | Gouvernance — **règle 7 de `CLAUDE.md`** (lot séparé : ce n'est pas du code) |

🔴 **`config/users.db` — restauré (`git checkout`) AVANT les commits, il n'entre dans aucun.**
Fichier **protégé** (CLAUDE.md), sali par les runs d'enquête §0.18 (`probe20`, `probe60`).
Il redeviendra sale au prochain training : le restaurer avant chaque commit.

**Pourquoi l'entrée reste OUVERTE malgré tout** : les tests R4 de [§8.3](V11_tranches.md#s8.3) sont en cours d'écriture
(cf. §0.19). Ils produiront du non-commité dès qu'ils existeront. Fermer cette entrée maintenant
la rendrait fausse une troisième fois.

<a id="s0.19"></a>
### 0.19 Revérifier T1→T5 et la section 9 ligne à ligne — ⏳ PARTIEL (T1 soldé §0.19.1→§0.19.3 ; section 9 auditée le 2026-07-24 → **NON FAITE**, cf. [§9.0](V11_phaseA.md#s9.0) ; **T2→T5 relus le 2026-07-29 → [§0.47](#s0.47)**)

> ✅ **Part T2→T5 : FAITE le 2026-07-29.** La relecture spec par spec de T2, T3, T4 et T5
> ([`V11_tranches.md` §5](V11_tranches.md#s5), plus §8.2/§8.3) a eu lieu. **Les écarts trouvés — et
> les réserves de méthode de cette relecture — vivent en [§0.47](#s0.47), pas ici** (règle « un
> contenu d'état vit à UN seul endroit »). Ce qui reste ouvert sous ce numéro : la relecture n'a
> mobilisé **aucune exécution** (audit mené pendant le run 4, working tree gelé), donc les ✅ de
> T2→T5 ne sont vérifiés que **par lecture** — la méthode par mutation-test décrite plus bas
> (points 1-3) n'a pas été appliquée à ces quatre tranches.

> ⚠️ **Correction 2026-07-24.** Le « ✅ SOLDÉ » d'origine était prématuré : les passes §0.19.1
> → §0.19.3 n'ont audité **que T1** (R4 `auto_decider`, R6 charge BFS). **La section 9 (Phase A')
> n'a jamais été revérifiée par cette entrée** — elle l'a été pour la première fois le 2026-07-24,
> verdict en [§9.0](V11_phaseA.md#s9.0) : **aucune de ses cinq sous-parties (P1→P5) n'est réellement en place** malgré
> les marqueurs ✅ FAIT. Le taux de découverte élevé annoncé ci-dessous se confirme donc jusque
> sur la section 9.

**Énoncé.** Les tranches **T1, T2, T3, T4, T5** ([§5](V11_tranches.md#s5)) et toute la **[section 9](V11_phaseA.md#s9)** (Phase A') sont
marquées ✅ FAIT, mais **n'ont jamais été revérifiées ligne à ligne contre le code**. Leur statut
repose sur les sessions où elles ont été écrites, pas sur un audit ultérieur. La réserve existe
depuis le 2026-07-19 en §0bis (« Réserve de méthode — ce qui n'a pas été revérifié ») ; elle y
est une **mise en garde**, pas une tâche. **Cette entrée en fait une tâche**, pour qu'elle cesse
d'être un avertissement que chacun contourne.

**Pourquoi ça n'est pas de la précaution abstraite.** Le taux de découverte est élevé partout où
on a effectivement regardé :

| Session | Ce qui a été trouvé en revérifiant |
|---|---|
| 2026-07-19 soir | **3** affirmations périmées (« prochain bloqueur [§10.4](V11_eval_strategy.md#s10.4) » déjà résolu ; « archivage des holdouts à faire » déjà fait ; « 9 échecs préexistants » alors que la suite est verte) |
| 2026-07-20 | **8** affirmations périmées recensées en §0bis, dont la n°6 (« 9 tests `roster_pool_schedule` échouent ») **démontrée fausse** par la suite complète |
| 2026-07-20 | **§0.11 déclaré résolu ne l'est pas** (§0.18) — et le T6-i portait déjà, en 2026-07-19, le motif « code testé mais jamais appelé » |

Trois marqueurs ✅ démentis sur les seules zones auditées. **Rien n'indique que T1→T5 et la
section 9 soient d'une autre nature** — simplement, personne n'y a regardé.

**Méthode suggérée** (une tranche = une passe, résultat écrit ici même) :
1. Pour chaque critère d'acceptation de [§6](V11_tranches.md#s6), retrouver **le test** qui le verrouille — pas le
   code, le **test**. [§8](V11_tranches.md#s8) pose la règle « une règle = son fichier de tests ».
2. Vérifier que ce test **s'exécute** (il est collecté par la suite) **et qu'il échoue** si on
   neutralise le code qu'il prétend couvrir. Le motif récurrent de ce projet est le **code testé
   mais jamais appelé** (T6-i) et le **test qui passe pour la mauvaise raison** (rencontré en
   §0.12 sur le bonus de kill, où le terme HP masquait le terme testé).
3. Tout ✅ qui ne survit pas à (1) et (2) redevient ⏳, avec la preuve du démenti.

⚠️ **Ne pas « nettoyer » en relisant la prose.** Corriger une affirmation sans relire le code
reproduit exactement l'erreur qu'on cherche — c'est écrit en tête du tableau des affirmations
périmées (§0bis), et c'est pour cette raison que ces 8 lignes ont été **signalées et non
corrigées**.

**Non planifié** : cette entrée n'a pas d'ordre dans le tableau d'état. C'est un audit de fond,
à mener quand le chemin critique (§0.18 → §0.14) est dégagé — ou immédiatement si l'on doute
d'une tranche en particulier.

#### 0.19.2 Retrait du repli silencieux de `_ai_select_fight_target` — ✅ FAIT (2026-07-20)

**Décision utilisateur** : « il faut absolument fixer ça ». Livré après la fin de la chasse §0.18.

**Ce qui était en cause.** `_ai_select_fight_target` (fight_handlers) enveloppait tout son corps
dans un `try/except Exception: return valid_targets[0]`. Il avalait les **deux** `require_key`
(`reward_configs`, puis la config de l'agent combattant) **et** le `ValueError` de
`get_model_key` sur un `unitType` inconnu. **Aggravant vérifié** : sa seule trace était
`add_console_log`, qui est un **no-op tant que `debug_mode` est faux**
([game_utils.py:74](../../engine/game_utils.py#L74)) — en entraînement normal l'erreur était
**totalement** silencieuse, le seul symptôme étant un ciblage de mêlée dégradé sur la première
cible du pool.

**Ce qui a été écarté avant d'agir.** On pouvait craindre que le repli soit atteint en
permanence : tous les `unitType` des rosters mappent vers `CoreAgent`, alors que le moteur tourne
en `rewards_config="ArmageddonAgent"`. **Faux** : [w40k_core.py:918-924](../../engine/w40k_core.py#L918-L924)
enregistre le `model_key` de **chaque** unité vers les rewards de l'agent contrôlé, donc
`reward_configs` contient bien `CoreAgent`. Le cas nominal n'atteint pas le repli — c'est ce qui
rendait le retrait sûr.

**Fix** : `try/except` supprimé, corps désindenté, aucune autre modification de comportement.

**Test** : `tests/unit/engine/test_fight_target_selection_no_fallback.py` (+4, porté à **10**
par §0.19.3) —
`reward_configs` sans la clé de l'agent, `reward_configs` absent, `unitType` inconnu, plus une
non-régression sur l'erreur explicite qui précède le `try`.
**Contre-épreuve faite** (`git stash` du seul `fight_handlers.py`) : **3 rouges sur le code
d'avant** (`DID NOT RAISE`), **4 verts après**. Suite complète `EXIT=0`.

⚠️ **Piège rencontré en écrivant le test** : il attendait `KeyError`, alors que `require_key`
lève `ConfigurationError` (sous-classe de `RuntimeError`,
[data_validation.py:17](../../shared/data_validation.py#L17)). Le test a donc échoué **après** le
fix alors que le fix était bon — c'était l'attente qui était fausse. Corrigé en vérifiant
**type ET fragment de message** ([§8.1](V11_tranches.md#s8.1)).

**Les DEUX autres replis de la même fonction — également retirés (2026-07-20).** Ils avaient
d'abord été renvoyés à l'utilisateur « pour arbitrage » : **c'était une erreur de cadrage**.
La règle métier était déjà posée (« aucun fallback pour masquer une erreur ») ; il ne manquait
que la **lecture du code**, qui est du ressort de l'implémentation. Rappel utilisateur, à
retenir : *« Je tranche le métier, pas l'optimisation du code. »*

| Repli | Ce que la lecture a établi | Remplacé par |
|---|---|---|
| `if not valid_targets: return ""` | **Branche MORTE** : les **4** sites d'appel gardent déjà le pool vide en amont — fight_handlers ~3381 (`if not targets: return []`), ~5537 (`if not valid: … return`), ~6271 (`if valid:`), w40k_core ~5518 (`if targets else None`). | `ValueError` « pool de cibles VIDE » |
| `if not target: continue` (×2 boucles) | Le pool vient de `units_cache` ([fight_handlers:2037](../../engine/phase_handlers/fight_handlers.py#L2037)) ; une cible qui y figure sans être dans `unit_by_id` est une **désynchronisation d'index**, donc un bug. Si TOUTES manquaient, la fonction renvoyait `valid_targets[0]` sans avoir scoré. | `ValueError` « absente de unit_by_id » |

⚠️ **Affirmation fausse émise en cours de route, corrigée après lecture** : il avait été écrit que
le `""` « remonte à 3 des 4 sites d'appel **sans garde** ». C'est l'**inverse** — les 4 gardent.
Le recensement avait été fait de mémoire du `grep`, pas en lisant les sites. Motif n°1 du
document, commis dans la session qui l'auditait.

**Tests (portés à 6)** : + `test_empty_target_pool_raises_instead_of_empty_string` et
`test_target_missing_from_unit_by_id_raises`. Contre-épreuve rejouée (`git stash` du seul
`fight_handlers.py`) : **5 rouges avant, 6 verts après**. ✅ **Cette mesure est fiable même en
contexte concurrent** : elle ne dépend que de `fight_handlers.py`, qu'aucun autre agent ne
touche — contrairement aux suites complètes (cf. le piège « verrou global » de §0bis).

<a id="s0.19.3"></a>
#### 0.19.3 Fermeture de T1 — les deux trous de §0.19.1 sont comblés — ✅ FAIT (2026-07-21)

**Déclencheur** : règle 7 de `CLAUDE.md` (commit `056c948e`). §0.19.1 avait *documenté* l'absence
de tests R4 et la non-couverture de R6 site 1 — or « documenter un manque n'est PAS le traiter ».
Le traitement était techniquement possible (l'instrumentation §0.18 avait été retirée), donc dû.

**Récapitulatif — chiffres relevés par exécution le 2026-07-21, pas de mémoire.**

| Fichier | Tests | Objet | Mutations → verdict |
|---|---|---|---|
| `test_fight_target_selection_no_fallback.py` | **10** | §0.19.2 (3 replis) + sélection sans sentinelle | 5 rouges (replis) ; 2 rouges (`max`→`min`, scoring aplati) |
| `test_charge_oval_base_reverse_bfs.py` | **4** | R6, **les 2 sites**, déterministe + garde d'atteinte | 3 rouges par site (L826 et L3629, mutés isolément) |
| `test_programmatic_owner_predicate.py` | **22** | R4 — le **prédicat** et son refus du repli | 3 rouges (bascule gym, `player_types`, erreur explicite) |
| `test_r4_auto_decider_wiring.py` | **14** | R4 — le **branchement** et sa consommation | 3 rouges (débranchements) + 1 rouge (site `defender_human` isolé) |
| **Total** | **50** | | **17 mutations, 17 rouges** |

**Suite complète après ces travaux : `EXIT=0`, zéro échec, `GARDE=OK`** — empreinte `mtime` de
`engine/ tests/ ai/ config/` identique avant et après le run (`833a2bfc…`), donc aucun écrivain
concurrent : la mesure est valide au sens du piège « verrou global » de §0bis.

⚠️ **Ce qui n'a PAS été mesuré**, à ne pas déduire de ce qui précède : aucun run d'entraînement
n'a été lancé de toute cette passe. Les runs §0.18 restent dus (cf. l'entrée correspondante) —
un crash dépendant de la trajectoire ne se solde pas par une suite verte.

**R6 site 1 — arbitrage utilisateur et ce qui en a été fait.** L'utilisateur a tranché : « x5 est
LA priorité ; si on doit sacrifier x1, on le sacrifie. » **On n'a pas eu à le faire**, et le
signaler faisait partie du travail : l'arbitrage était conditionnel, et la condition n'est pas
remplie. Le chemin x1 est **vif** — [api_server.py:56](../../services/api_server.py#L56) et
`frontend/src/hooks/useGameConfig.ts` exposent le board `44x60x1` au PvP, et
`ArmageddonAgent_training_config.json` porte une phase de curriculum x1. Le supprimer aurait été
une **régression PvP sans aucun gain au x5** : le fix R6 y était déjà correct, seulement invisible
aux tests. Traitement retenu : le **couvrir**.

`tests/unit/engine/test_charge_oval_base_reverse_bfs.py` (+4) — Carnifex `[41,27]`, Psychophage
`[47,36]`, non-régression socle rond `int`, et surtout une **garde d'atteinte**
(`test_reverse_bfs_is_actually_reached`) qui espionne l'appel à
`_charge_reverse_goal_bfs_for_eligibility`. ⚠️ **Sans cette garde le fichier ne vaudrait rien** :
c'est le motif §0.11 (« un test vert ne couvre que les états qu'il atteint »), déjà subi par
`test_move_mask_is_executable.py`. Le test unitaire atteint le site parce que la fixture ne
définit pas `inches_to_subhex` → `.get(..., 1)` vaut 1, ce qui active le BFS inverse.
**Mutation `max(_mover_bs)` → `int(_mover_bs)` : 3 ROUGES** (dont la garde), le socle rond reste
vert.

**R4 — prédicat ET branchement, les six exigences de [§8.3](V11_tranches.md#s8.3) sont couvertes (2026-07-21).**

| Exigence [§8.3](V11_tranches.md#s8.3) pour R4 | État | Où |
|---|---|---|
| Matrice (gym True/False) × (`player_types` human/ai) | ✅ | `test_programmatic_owner_predicate.py` |
| Test négatif `_is_ai_controlled_shooting_unit` | ✅ | idem |
| Allocation **fight** auto en gym, pertes réelles (FIGHT_CTX) | ✅ | `test_t5_bare_loop.py` (préexistant) |
| Allocation **tir** auto en gym | ✅ | `test_r4_auto_decider_wiring.py` |
| Les **4 sites `defender_human`** du flux fight | ✅ | idem — **verrou STRUCTUREL** `test_every_defender_human_site_delegates_to_the_predicate`, pas une déduction depuis le helper |
| **Miroir PvP** : en PvP humain l'allocation reste manuelle | ✅ | idem, un jumeau PvP par cas gym |

🔴 **Pourquoi les tests de prédicat ne suffisaient pas.** Le prédicat était déjà correct AVANT
T1 ; la rupture R4 était son **branchement**. `test_programmatic_owner_predicate.py` ne rougit
pas si l'on débranche `SHOOT_CTX.auto_decider` — d'où
`tests/unit/engine/test_r4_auto_decider_wiring.py` (**+14**, comptés par exécution), qui
vérifie la **chaîne** :

    SHOOT_CTX.auto_decider = _target_defender_is_ai -> is_programmatic_defender -> is_programmatic_owner
    FIGHT_CTX.auto_decider = _fight_auto_defender   -> _is_ai_controlled_fight_unit -> is_programmatic_owner
    les 4 sites `defender_human` (~5523, ~5548, ~6248, ~6282) -> _is_ai_controlled_fight_unit
    consommation : _manual_allocation_step (shared_utils) — DEUX sites d'interrogation

⚠️ **Le second site de consommation avait failli être manqué** : `_manual_allocation_step`
interroge `auto_decider` **deux fois** — une fois pour l'ordre des groupes (~L6416), une fois
pour le **choix de la figurine** qui encaisse (~L6446). Le premier test ne couvrait que l'ordre.
Les deux sont désormais couverts, chacun avec son miroir PvP.

**3 mutations de débranchement, 3 rouges :**

| Mutation | Tests rouges |
|---|---|
| `SHOOT_CTX.auto_decider` → `None` | 5 |
| `FIGHT_CTX.auto_decider` → `None` | 2 |
| `_is_ai_controlled_fight_unit` recâblé sur `player_types` en direct (**la rupture R4 d'origine reproduite**) | 2, dont `defender_human_is_false_in_gym` |

La troisième est la preuve qui manquait : elle rejoue le bug historique et le test le rattrape.

⚠️ **Erreur commise puis corrigée dans la même passe, à retenir.** La première version de ce
fichier testait `_is_ai_controlled_fight_unit` et en **déduisait** que les 4 sites
`defender_human` étaient couverts. C'est **exactement le raisonnement « prédicat correct donc
branchement correct »** que le fichier existe pour interdire, reproduit un cran plus haut :
débrancher un seul des 4 sites laissait la suite **verte**. ➜ Corrigé par
`test_every_defender_human_site_delegates_to_the_predicate`, un **verrou structurel** qui lit la
source, exige que chaque affectation de `defender_human` passe par le prédicat, et qu'il y en ait
**exactement 4** (un 5ᵉ site non gardé fait rougir). Mutation d'un seul site → **ROUGE**.
**Leçon : un test de helper ne couvre jamais ses appelants ; il faut vérifier l'appel.**

⏳ **Faiblesse assumée, non corrigée** : les deux tests de consommation
(`_manual_allocation_step`) reposent sur **8 monkeypatches** de fonctions vives
(`_build_alloc_groups`, `_group_alive`, `_auto_declared_order`, `_declare_order_payload`,
`_finalize_manual_allocation`, `_current_live_group`, `_select_allocation_model`,
`_manual_waiting_payload`). C'est légal ([§8.1](V11_tranches.md#s8.1) n'interdit que le monkeypatch de code **mort**),
mais ils vérifient en partie le **modèle** qu'on se fait de la fonction plutôt que la fonction :
si sa forme change, ils peuvent rester verts pendant que la production casse. Une couverture par
un vrai `game_state` d'allocation serait plus solide — coût non négligeable, à peser si ce
chemin bouge.

`tests/unit/engine/test_programmatic_owner_predicate.py`
(+22) : matrice complète (gym True/False) × (`player_types` human/ai) × (joueur 1/2) ; les trois
erreurs explicites (`player_types` manquant hors gym, joueur inconnu, cible absente de
`units_cache`) ; le court-circuit gym qui précède le `require_key` ;
`is_programmatic_defender` résolvant le propriétaire via `units_cache` ; et le **test négatif**
exigé par le ⚠️ R4 — `_is_ai_controlled_shooting_unit` lit `player_types` et **jamais** le flag
gym, sous peine d'auto-activer les unités du joueur entraîné.

**3 mutations, 3 rouges**, une par branche du contrat :

| Mutation | Effet | Tests rouges |
|---|---|---|
| `if game_state.get("gym_training_mode")` → `if False` | bascule gym neutralisée | 4 (dont `defender_in_gym`) |
| `return player_types[p] == "ai"` → `return True` | branche hors-gym toujours vraie | 4 (dont le miroir PvE) |
| `raise KeyError(...)` → `return False` | erreur explicite → **défaut silencieux** | 1 (`unknown_player_raises`) |

La troisième est la plus importante : elle prouve que le test **interdit le repli**, au lieu de
seulement constater un comportement.

⚠️ **Restauration par `cp`, jamais `git checkout`** — `shared_utils.py` portait alors du travail
non commité d'un autre agent (cf. §0bis). Vérifiée par `git diff --stat` vide.

**Deux dettes révélées par cette passe — ✅ TOUTES DEUX TRAITÉES le 2026-07-21 (règle 7) :**

1. ✅ **Le site R6 n°2 n'était verrouillé QUE par un test à exploration aléatoire.**
   `test_t5_bare_loop.py` déroule des épisodes au hasard : c'était **l'antipattern §0.11**
   reproché au site n°1, qui a déjà piégé `test_move_mask_is_executable.py`. Il tenait par
   chance de trajectoire, pas par construction.
   ➜ **Résolu sans écrire une ligne de plus** : le site n°2 (~L3629) est situé **avant**
   l'embranchement vers le BFS inverse (~L3698), donc tout appel à
   `charge_build_valid_destinations_pool` le traverse — `test_charge_oval_base_reverse_bfs.py`
   le couvrait déjà. **Vérifié par mutation isolée du seul L3629, ce fichier seul (sans
   `test_t5_bare_loop.py`) : 3 ROUGES.** Les deux sites R6 sont donc désormais verrouillés de
   façon **déterministe**.
2. ✅ **Code mort introduit par le fix §0.19.2** : `best_reward = -999999` était une sentinelle
   utile tant que `if not target: continue` pouvait sauter toutes les cibles ; depuis que ce
   `continue` lève, elle est inatteignable.
   ➜ Boucle remplacée par `max(resolved, key=...)`, qui supprime **aussi** le second
   `get_unit_by_id` par cible (la première boucle l'avait déjà résolue). `max` retient le
   **premier** maximum : départage identique au `>` strict, donc sélection **stable**
   (déterminisme [§8.1](V11_tranches.md#s8.1)). **+4 tests** dans `test_fight_target_selection_no_fallback.py`
   (argmax réel, stabilité sur deux appels, égalité → premier du pool, un scoring par cible),
   **2 mutations → rouges** (`max`→`min`, scoring aplati à 0).

⚠️ **Piège auto-infligé, à ne pas refaire** : le helper de mutation restaurait par
`git checkout --`, ce qui a **effacé le refactor non commité en cours** — précisément la mise en
garde inscrite en §0bis, commise par son propre auteur. Les 10 tests sont alors repassés au vert
sur le code d'origine, donnant l'illusion d'une mutation validée. **Sauvegarde/restauration par
`cp` obligatoire dès qu'on mute un fichier qu'on est soi-même en train de modifier.**

**Suite complète — première mesure VALIDE de tout ce travail** : `EXIT=0`, zéro échec, avec la
garde de stabilité d'arbre de §0bis (empreinte `mtime` de `engine/ tests/ ai/ config/` identique
avant et après le run → aucun écrivain concurrent). Les trois suites précédentes de la session
avaient toutes été invalidées.

<a id="s0.19.1"></a>
#### 0.19.1 Passe d'audit du 2026-07-20 (soir) — T1→T5 faits, section 9 **sans objet**

**Méthode réellement appliquée.** Pour chaque critère de [§6](V11_tranches.md#s6) : retrouver le test, vérifier qu'il
est collecté, puis le **neutraliser par mutation du code de production** et observer le verdict,
puis restaurer. Six mutations menées. **Les cinq fichiers mutés ont été restaurés et vérifiés
par `git diff --stat` vide** : `charge_handlers.py`, `macro_intents.py`, `train.py`,
`game_state.py`, `action_decoder.py`. `shared_utils.py`, `w40k_core.py` et le script de chasse
**n'ont pas été touchés** pendant CETTE passe (ils portaient alors l'instrumentation §0.18) ;
aucun training lancé. ⚠️ **État daté** : depuis, l'instrumentation a été retirée,
`scripts/hunt_intra_squad_superposition.py` a été **supprimé**, et `shared_utils.py` a bien été
muté — proprement, en §0.19.3 (sauvegarde/restauration par `cp`).

**Tableau de verdicts.**

| Tranche | Critère [§6](V11_tranches.md#s6) | Test qui le verrouille | Mutation appliquée | Verdict | Statut |
|---|---|---|---|---|---|
| **T1 / R6 site 1** | socle ovale en **éligibilité** de charge | ~~aucun~~ → `test_charge_oval_base_reverse_bfs.py` (§0.19.3) | `charge_handlers.py:826` → `int(_mover_bs)` | ~~VERT~~ → **ROUGE (3 tests)** | ~~⏳~~ **✅** |
| **T1 / R6 site 2** | socle ovale, **pool de destinations** | `test_charge_oval_base_reverse_bfs.py` (déterministe, §0.19.3) + `test_t5_bare_loop.py` | `charge_handlers.py:3629` → `int(_mover_bs)` | **ROUGE** (`TypeError`) | ✅ |
| **T1 / R4** *(prédicat)* | prédicat programmatique unique | ~~AUCUN~~ → `test_programmatic_owner_predicate.py` (§0.19.3) | 3 mutations : bascule gym, branche `player_types`, erreur explicite | **ROUGE (3/3)** | ✅ |
| **T1 / R4** *(branchement)* | `auto_decider` tir + 4 sites `defender_human` + miroir PvP | `test_r4_auto_decider_wiring.py` (§0.19.3) | 3 débranchements : `SHOOT_CTX`, `FIGHT_CTX`, prédicat recâblé | **ROUGE (3/3)** | ✅ |
| **T2** | zéro littéral d'action dans `ai/` | `test_action_space_mirror.py` | `macro_intents.ACTION_CHARGE` 1030→1029 | **ROUGE** (2 tests) | ✅ |
| **T3** | board refs + `--training-config` obligatoire | `test_train_board_refs.py` | reconstruction `{cols}x{rows}` **et** garde R1 neutralisée | **ROUGE** (3 tests) | ✅ |
| **T4** | resolver `board_ref` | `test_board_ref_resolver.py` | garde « board dir inexistant » neutralisée | **ROUGE** | ✅ |
| **T5** | parité masque ↔ commit de déploiement | `test_deployment_clearance_parity.py::test_deployment_mask_mirrors_commit_overlap_predicate` | `_deployment_clearance_filter` → `return candidates` | **ROUGE**, symptôme d'origine | ✅ |

> ✅ **Les deux démentis ci-dessous sont RÉSOLUS depuis le 2026-07-21 — voir §0.19.3.** Le
> constat historique est conservé tel quel : c'est lui qui documente le trou et la méthode qui
> l'a trouvé.

**Les deux démentis de fond.**

1. 🔴 **T1 / R6 site 1 est du CODE MORT à la résolution du training — septième occurrence du
   motif §0.4.** `_charge_reverse_goal_bfs_for_eligibility` est gardé par
   `int(game_state.get("inches_to_subhex", 1)) <= 1`
   ([charge_handlers.py:3698](../../engine/phase_handlers/charge_handlers.py#L3698)). Le training
   tourne en **x5**, donc ce site n'est **jamais atteint**. Preuve : `int()` sur une liste lève
   `TypeError` de façon inconditionnelle, et la suite reste **verte** sous cette mutation. Le fix
   R6 y est correct mais **non exercé et non verrouillé** ; seul le site 2 l'est. Conséquence
   pratique : nulle aujourd'hui (x5/x10 passent par le BFS avant) — mais toute réactivation du
   chemin x1, ou tout run à `inches_to_subhex = 1`, s'appuierait sur du code qu'aucun test ne
   garde.

2. 🔴 **T1 / R4 n'a aucun test.** `grep -rln "is_programmatic_owner\|is_programmatic_defender"
   tests/` retourne **vide**, alors que [§8.3](V11_tranches.md#s8.3) impose explicitement une matrice
   (gym × `player_types`), l'allocation tir **et** fight en gym, les 4 sites `defender_human`, le
   **miroir PvP** et le test négatif sur `_is_ai_controlled_shooting_unit`. Le code est présent et
   conforme à sa description ([shared_utils.py:97-124](../../engine/phase_handlers/shared_utils.py#L97-L124),
   lu). La seule couverture est **indirecte** : `test_bare_loop_melee_losses_via_fight_ctx`
   exerce la branche gym=True. **Rien** ne couvre la branche PvP ni la non-régression du miroir.
   ⚠️ **Mutation impossible dans cette session** : `shared_utils.py` porte l'instrumentation
   §0.18. **Ce ⏳ repose sur une absence de test constatée, pas sur un mutation-test** — à
   confirmer par mutation quand l'instrumentation sera retirée.

**Ce que l'audit n'a PAS trouvé.** T2, T3, T4, T5 sont verrouillés par des tests qui rougissent
sur mutation. Aucun « test qui passe pour la mauvaise raison » sur ces quatre tranches.

**Section 9 : la prémisse de §0.19 était FAUSSE.** L'énoncé ci-dessus affirme que « toute la
section 9 est marquée ✅ FAIT ». Vérification : les lignes de la section 9 ne contiennent
**aucun** marqueur `✅`, `FAIT` ni `⏳`. C'est une section de **plan** (P1→P5), **non
implémentée** — il n'y a donc aucun ✅ à démentir. Ses affirmations de *diagnostic* ont
néanmoins été revérifiées **par lecture** (pas par grep seul) et **tiennent toutes** :
`_attack_sequence_rng` sans appelant vif (seuls des tests l'importent) ; `apply_rules` /
`_apply_single_rule` toujours `return context` pass-through
([rules.py:279-327](../../engine/weapons/rules.py#L279-L327)) ; `_cover_worsened_bs` ne lit
toujours pas `IGNORES_COVER` ([shared_utils.py:5980-6005](../../engine/phase_handlers/shared_utils.py#L5980-L6005)) ;
`_ai_select_shooting_target` de `shooting_handlers` toujours sans appelant (l'homonyme de
`pve_controller` est, lui, vif — ne pas les confondre) ; `reroll_charge` toujours dans
`config/unit_rules.json` et nulle part dans le code ; `_select_ai_rule_choice_option` toujours en
`raw_action_int % len(options)` en gym ([w40k_core.py:2471](../../engine/w40k_core.py#L2471)) ;
le `except Exception: … return valid_targets[0]` de `_ai_select_fight_target` toujours présent.
**Seules les références de ligne ont dérivé** (~+200 à +350 lignes) — signalées, non corrigées.

> **Mise à jour 2026-07-29 (archive — le constat ci-dessus n'est pas réécrit, il était exact
> à sa date).** Le point « `apply_rules` / `_apply_single_rule` toujours `return context`
> pass-through » est CLOS : la classe `WeaponRulesApplier` qui les portait a été SUPPRIMÉE
> (aucune instanciation en production, seul son test l'appelait pour verrouiller son inaction).
> Le lien `rules.py:279-327` ci-dessus ne pointe donc plus sur rien — voir la pierre tombale en
> fin de `engine/weapons/rules.py`. Les autres points de ce paragraphe restent ouverts.

**Trois affirmations périmées repérées, SIGNALÉES et NON corrigées** (elles rejoignent le
tableau de §0bis) :

| # | Où | Affirmation | Pourquoi elle est périmée |
|---|---|---|---|
| 11 | [§6](V11_tranches.md#s6), critère **T2**, et [§8.2](V11_tranches.md#s8.2) | « `action_space.n == 41` », « `ACTION_WAIT` (18) », « `6+6+6+1+5+1+1+15 == 41` », « 19→shoot slot 0, 24→charge » | Le layout réel est **1047** actions : `ACTION_WAIT = 1024`, `SHOOT_SLOT_BASE = 1025`, `ACTION_CHARGE = 1030`, `ACTION_FIGHT = 1031` ([macro_intents.py:20-38](../../engine/macro_intents.py#L20-L38)). Changé par la refonte spatiale du move. **MAJ 2026-07-26 (§0.30 T-E)** : le layout passe à **1062**. ⏳ **MAJ 2026-08-02 : ce chiffre est à son tour périmé** — le layout a continué d'évoluer (P3-1/P3-2 : la mêlée et la charge ont désormais des **plages de slots**, il n'y a plus d'`ACTION_CHARGE` ni d'`ACTION_FIGHT` isolés). **Ne plus citer de chiffre ici** : lire `engine/macro_intents.py`. Le critère T2 **réel** (zéro littéral d'action dans `ai/`) reste, lui, satisfait — c'est la seule chose que cette ligne devait établir. |
| 12 | [§6](V11_tranches.md#s6), critère **T4** | « Les **61 scénarios** se chargent (script de balayage) » | La banque `ArmageddonAgent` compte **5** scénarios et `test_bank_has_expected_count` l'assert explicitement ; la banque `CoreAgent` en compte **4**. De plus `scripts/sweep_scenario_bank_v11.py:24` pointe encore `config/agents/CoreAgent/scenarios` : **le balayage du critère n'est plus exécutable tel quel**. La migration T4 a bien eu lieu ; c'est le critère qui n'a pas suivi. |
| 13 | [§8.2](V11_tranches.md#s8.2) | « Fichier proposé : `tests/unit/engine/test_agent_interface_contract.py` … C'est LE verrou anti-récidive de R5 » | Ce fichier **n'existe pas**. Le verrou existe sous un autre nom et une autre forme — `test_action_space_mirror.py` — et il est **meilleur** : il vérifie `macro_intents` ≡ `shared_utils` constante par constante, et le décodeur **importe** ces mêmes constantes ([action_decoder.py:25-32](../../engine/action_decoder.py#L25-L32)), donc la désynchronisation visée par [§8.2](V11_tranches.md#s8.2) est structurellement impossible. |

**Réserve sur le critère T5, indépendante du mutation-test.** [§6](V11_tranches.md#s6) exige « 10 épisodes aléatoires
masqués terminés sur **≥3 scénarios × sièges p1/p2** ». `test_t5_bare_loop.py` exerce **un**
scénario fixe × 3 seeds et **aucun siège** (`grep agent_seat_mode tests/` ne retourne que des
fichiers `tests/unit/ai/`). T5 le dit d'ailleurs lui-même dans son « Reste » : le siège
`p2`/`random` crashait encore au reset. **Le ✅ de T5 couvre un périmètre strictement plus étroit
que son critère** — il vaut pour le moteur nu, siège p1, comme la tranche l'annonce en tête.

**Réserves de méthode sur cette passe elle-même** (à ne pas répéter) :
- Une première suite complète avait été lancée **en parallèle des mutations** : contaminée par
  construction, elle a été **tuée et non exploitée**. Ne jamais mesurer une baseline pendant
  qu'on mute.
- Deux premières tentatives de mutation-test sur T5 ont été **tuées par leur propre `timeout`**
  sans verdict, et un `pkill` trop large a tué sa propre commande. Un non-aboutissement n'est
  **pas** un rouge : le verdict n'a été obtenu qu'en isolant le test d'assertion pure
  (**42 s vert** / **6,7 s rouge**) au lieu du fichier entier, dont l'autre test déroule des
  épisodes. Sur une machine chargée (load ~15, 10 process de chasse), **chronométrer le
  contrôle propre AVANT de conclure d'une lenteur sous mutation**.
- `tests/unit/engine/test_pile_in_intra_squad_collision.py` est apparu dans `git status` pendant
  la session : il vient des process §0.18, **pas de cet audit**.

**⚠️ La première suite de fin de passe est sortie en `EXIT=1` — mesure INVALIDE, ne pas la citer.**
Elle montrait un échec de
`test_pile_in_intra_squad_collision.py::test_stationary_b2b_figurine_cell_is_not_stolen`. Cause
identifiée par les **mtimes** : la **chasse §0.18** écrivait `shared_utils.py` (20:14:31) et son
propre test (20:13:58) **pendant** que cette suite tournait (~20:05→20:45). **Deuxième baseline
contaminée de la session**, après celle des mutations — même erreur, autre écrivain. ⚠️ **Ne
jamais mesurer une suite pendant qu'un autre process écrit dans `engine/`**, y compris un process
qu'on n'a pas lancé soi-même.

⚠️ **Aucune suite complète de cette session ne constitue une mesure de référence.** Trois runs
ont été invalidés par un écrivain concurrent (détail et règle : piège « verrou global » en §0bis).
Le dernier, `EXIT=0`, a tourné de 21:17:37 à 21:22:54 alors que `shared_utils.py` était écrit à
**21:20:33** par l'agent concurrent — **non exploitable, malgré son vert**. La mesure de référence
est celle produite par l'agent concurrent **après gel des écritures**, à reprendre ici quand elle
tombe.

**Ce qui EST mesuré de façon fiable**, parce que cela ne dépend que de fichiers qu'aucun autre
agent ne touche : les mutation-tests par tranche du tableau ci-dessus, et la contre-épreuve de
§0.19.2 sur `fight_handlers.py`. Le test de pile-in passe **3 fois sur 3** en isolé.

