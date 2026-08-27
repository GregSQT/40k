# V11 — Rétablissement de l'entraînement de l'agent (agent rework)

> ### 🧭 Ce fichier n'est PAS la roadmap
>
> **Ordre du travail, tout projet confondu : [`../../Roadmap/ROADMAP_INDEX.md`](../../Roadmap/ROADMAP_INDEX.md)** — s'y reporter
> pour savoir par quoi commencer, ce qui est bloqué et par quoi.
>
> Ce document porte le **détail de conception** de V11 : entrées ouvertes (§0), pièges et leçons de méthode (§0bis, copie canonique), historique résolu (§0hist).
> **Depuis la refonte du 2026-08-27, l'ÉTAT des chantiers fait foi dans `Documentation/Roadmap/`
> uniquement** — audit à l'appui : sur chaque chiffre échantillonné (TOTAL_ACTION_SIZE, obs_size,
> P3-8, T6), la roadmap était à jour et ce fichier retardait. Ses bandeaux et chiffres d'état sont
> donc à lire comme datés ; en cas de désaccord (état comme priorités), **la roadmap l'emporte**.
> Scission prévue (P3 de la refonte, `Roadmap/doc.md#refonte`) : ouvert → roadmap, §0bis → doc de
> méthode, §0hist → archive.

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
> **[`Documentation/Reference/training/AI_OBSERVATION.md`](../../Reference/training/AI_OBSERVATION.md)** — il ne décrit QUE le code actuel
> depuis le 2026-07-28 : les clés et leurs formes, la table blocs logiques A→E ↔ clés, l'espace
> d'action associé, les trois invariants, **qui normalise quoi** (`VecNormalize` vs
> `EntityRunningNorm`), **les 5 caches et leur condition d'invalidation**, et l'historique
> d'`obs_size`.
> Le pipeline **mono-figurine legacy** (vecteur plat d'offsets `obs[N]`, features calculées) est
> archivé à part : [`AI_OBSERVATION_Legacy.md`](../../Archives/docs/AI_OBSERVATION_Legacy.md). Aucun agent ne
> l'utilise.
>
> **Source unique du contrat** (la doc en donne la lecture, jamais une copie de chiffres) :
> [`engine/observation_entities.py`](../../../engine/observation_entities.py) pour le schéma, et
> l'en-tête « OBSERVATION SQUAD — TENSEURS D'ENTITÉS » de
> [`engine/observation_builder.py`](../../../engine/observation_builder.py) pour le layout.
>
> **Conception et journal** : [`V11_entity_encoder_pointer.md`](../../Reference/training/V11_entity_encoder_pointer.md)
> (encodeur partagé, tête pointeur, cardinalités) · [`V11_audit_observation.md`](../../Archives/chantiers/V11_audit_observation.md)
> (audit d'origine) · **[§9.2.5](V11_phaseA.md#s9.2.5)** et **§0.31** de ce document (ce qui est observé, et pourquoi).
>
> **🎬 Replay (outillage d'analyse)** : [`Replay.md`](../Replay.md) — sémantique du viewer replay
> (dont : le cercle vert fight = la seule unité activée, dérivée de l'attaquant, aucun pool loggué).

---

<a id="s0"></a>
## 0. ÉTAT AU 2026-08-10 — entrées ouvertes de V11

> **Cette section ne contient QUE ce qui est ouvert et actionnable.**
> - Ce qui est résolu est en **§0hist — Historique résolu**, **en fin de document, après les [Pointeurs](#pointeurs)** :
>   entrées intégrales, ancres `### 0.x` inchangées, aucune preuve condensée.
> - Les avertissements et leçons de méthode durables sont regroupés en **§0bis — Pièges et
>   leçons de méthode**, qui en est la **copie canonique**.
>
> **Conventions de tenue de ce document — les respecter en le mettant à jour :**
> - **Un numéro d'entrée est attribué à vie.** Une entrée résolue descend en §0hist en gardant
>   son numéro ; un numéro n'est jamais réattribué. Prochaine entrée libre : `0.71` (`0.70` le 2026-08-10, `0.69` et `0.68` le 2026-08-08, `0.67` le 2026-08-07, `0.66` le 2026-08-04, `0.63`–`0.65` le 2026-08-03, `0.57`–`0.60` le 2026-08-02, `0.18`–`0.21` le 2026-07-20, `0.22` le 2026-07-21, `0.23`–`0.28` le 2026-07-22, `0.29` le 2026-07-22, `0.30` le 2026-07-26, `0.31` le 2026-07-27, `0.32`–`0.43` le 2026-07-28, `0.44`–`0.52` le 2026-07-29, `0.53`–`0.54` le 2026-07-30, `0.55`–`0.56` le 2026-08-02).
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

📌 **Périmètre de profils** : seuls les profils **`x1*`** étaient utilisés jusqu'au 2026-08-09
(décision utilisateur du 2026-08-02). Depuis le **2026-08-10** une chaîne x5 est réglée et
verrouillée : `x5_new` (aligné sur `x1`, modèle neuf) → `x5_long` (200 000 ép., même recalibrage
que `x1_long`) → `x5_append` (30 000 ép. de prolongation, reprise aux planchers de `x5_long`).
Ces trois profils sont à jour et tenus par `tests/unit/ai/test_schedule_decay_fraction.py`.
`x5_debug`, lui, reste hors de ce périmètre : ses valeurs ne servent pas de référence.
⚠️ **Un `x5_debug` a tout de même tourné le 2026-08-09** (`tensorboard/x5_debug_ArmageddonAgent/run_20260809-103610`,
relevé le 2026-08-10) : la décision porte sur les runs qui MESURENT, elle n'interdit pas un debug
ponctuel — mais un artefact `x5_*` postérieur au 2026-08-02 n'est pas pour autant une référence.

| # | Entrée | Statut | Ordre | Prochaine action concrète |
|---|---|---|---|---|
| **§0.70** | Le `--new` du lot **TOURNE** — et c'est une **base de développement**, pas la mesure de référence | 🟢 **EN COURS depuis le 2026-08-10 11 h 17** ⏳ entrée périssable | **1** | `ai/train.py --agent ArmageddonAgent --training-config x1 --scenario bot --new --resolution 1` (`tensorboard/x1_ArmageddonAgent/run_20260810-111734`). Santé à 1 748 épisodes : **0 troncature**, `invalid_action_rate` **0.0**, PPO à 171 408 steps, `win_rate_overall` **0.24** en progression — le correctif [§0.68](#s0.68) tient, le run a franchi le point qui a tué le précédent. 🟢 **ARBITRAGE UTILISATEUR DU 2026-08-10 : ce run est une BASE DE DÉVELOPPEMENT** (faire JOUER l'agent), **la mesure de référence est DIFFÉRÉE** jusqu'à ce que P3-4, P3-5, P3-6, P3-8, P4 et P5 soient finis. ⚠️ **Son `combined` ne vaut PAS référence** et ne doit alimenter aucun gate. Détail → §0.70. |
| **§0.69** | Le choix d'**ARME en mêlée** n'existe pas côté agent | ✅ **LIVRÉ le 2026-08-23** | **3** (après le lot P3) | 10 slots FIGHT_WEAPON ajoutés (1349→1359). `squad_fight` arme `pending_fight_weapon_select` ; `squad_fight_weapon` résout. Masque exclusif pendant la sélection. Tête dense `fight_weapon_net` dans `pointer_policy`. Verrou rouge/vert (5 tests). Détail → §0.69. |
| **§0.71** | Le déploiement `auto` entrait dans le rollout PPO avec une action que le moteur avait remplacée ; `deployment_random_mix` faisait doublon | ✅ **CORRIGÉ le 2026-08-08** (absorption + suppression du doublon) | **1** (avant le run) | En mode `auto`, `W40KEngine.step` substituait sa propre pose à l'action échantillonnée : SB3 rangeait l'action et le `log_prob` de la politique pour une transition produite par une AUTRE action (~10 steps de déploiement par épisode, sur 70 % des épisodes en début de rampe). Ces steps sont désormais **absorbés** par `BotControlledEnv._ensure_actionable_controlled_turn`, comme les tours du bot et les `WAIT` forcés — l'apprenant ne les voit plus. Régression née avec `auto` : l'ancien mode `fixed` ne produisait aucune transition de déploiement. `deployment_random_mix` portait le MÊME motif et tirait ses poses par la MÊME fonction que `auto` : supprimé (code, 7 profils, doc). Détail → §0.71. |
| **§0.68** | Le premier `--new` du lot est **mort en rollout** : une instrumentation qui lisait l'observation PLATE, morte depuis la migration aux entités, réveillée par `L2` | ✅ **CORRIGÉ le 2026-08-08** (suppression) | **1** (le run repart) | `TypeError: Unsupported observation batch type: dict`. Le bloc `obs/<phase>_*` de `MetricsCollectionCallback` lisait le bloc « valid target » du vecteur plat mono-figurine (`obs[273:313]`), supprimé le 2026-07-28. Il n'était **pas atteint** jusqu'ici : aucune action d'agent ne portait de `phase` dans `('shoot','fight','charge')` — **mesuré**, 600 pas pilotés. `select_activation` (`L2`) est la première, et elle a tué le run. **Aucun run n'a jamais émis un seul de ces scalaires** (`obs/shoot` absent de tous les fichiers d'events). Détail → §0.68. |
| **§0.67** | Les **chantiers 01/03/04** puis le **lot `L1`+`L2`+`L6`** ont cassé les contrats d'observation ET d'action | 🟠 **OUVERT — le lot est COMPLET et son `--new` TOURNE ([§0.70](#s0.70)) ; il reste sans modèle ni mesure courants jusqu'à sa fin** | **1** (avant toute mesure) | ⚠️ **Le run en cours est une base de DÉVELOPPEMENT, il ne produit pas la mesure de référence** — arbitrage du 2026-08-10, cf. [§0.70](#s0.70). Vérifié par exécution le 2026-08-08, revérifié le 2026-08-10 : `obs_size` **16659**, `TOTAL_ACTION_SIZE` **1139**, **7** requêtes de pointeur. Tous les modèles du dossier (le plus récent : `ArmageddonAgent_12345_robust_0.8049.zip`, contrat 20780/1107) sont **inchargeables** ⇒ le **0.82 de §0.14 ne décrit plus le code courant**. ✅ `L1` (`91cc70d1`), `L2` (`b8be3f8e`) et `L6` (`7b4ace51`) sont **mergés sur `main`**, plus 3 correctifs post-merge de `L2` (2026-08-08). **Prochaine action : le `--new` unique, puis la mesure de référence.** Détail → §0.67. |
| **§0.66** | Le **journal du gym mentait à l'analyzer**, et deux règles de mouvement n'étaient pas appliquées | ✅ **CORRIGÉ le 2026-08-04** — ⚠️ **deux correctifs CHANGENT le jeu** | **1** | Fermeture de §0.62 par le bas : sur un run de **600 épisodes**, l'analyzer rendait **2353 erreurs**. **1014** venaient d'un `[FLY]` qu'AUCUN émetteur du gym n'écrivait (l'analyzer pathfindait les escouades volantes au sol), **898** d'armes aux règles différentes fusionnées dans un même lot 04.03, **144** d'un contrôle close-quarters qui mesurait une adjacence d'ancre là où 10.06 exige l'engagement. **2353 → 1204 mesuré.** Mais **71 erreurs étaient VRAIES** : la charge (11.04) et le pile-in/consolidation (12.03/12.08) bornaient à vol d'oiseau et ne validaient que la case d'arrivée — les escouades **traversaient les murs**. Et 122 violations d'alternance venaient d'une charge **ratée** comptée comme un charge move (Fights First indu). Détail → §0.66. |
| **§0.62** | L'**analyzer** mesurait à une autre échelle et avec d'autres règles que le run — et trois déplacements n'étaient pas contrôlés | ✅ **CORRIGÉ le 2026-08-03** — une conséquence à assumer | **1** | 206 erreurs → **0** sur un log de référence de 6 épisodes. L'échelle venait du `board_config` COURANT, pas de l'entête du log : un run x1 relu avec un `config.json` en x5 mesurait tout ×5 — il **fabriquait** des erreurs (132 faux « shoot at engaged enemy ») **et en masquait** (portées, budgets jamais dépassés). Même défaut, silencieux celui-là, sur `engagement_zone`, `distance_metric` et les toggles `move` : désormais journalisés en entête `Run rules:`. Charge, pile-in/consolidation et move réactif n'avaient **aucun** contrôle conforme (jet non converti, mesure d'ancre, pas de pathfinding). **Conséquence : aucun verdict d'analyzer antérieur ne vaut**, et deux correctifs MOTEUR changent le jeu (move réactif). Détail → §0.62. |
| **§0.61** | Le garde **anti-runaway** était MUET, et son compteur d'épisodes divergeait | ✅ **CORRIGÉ le 2026-08-03** | **1** | Une troncature signale une BOUCLE dans le moteur, pas une fin de partie — or son diagnostic n'existait que dans le `print` d'un worker (noyé à `n_envs=48`) et le compteur persisté ne la comptait pas, alors que le run s'arrête dessus. Nouveau scalaire `00_critical/t_truncated_episodes`, diagnostic complet en `truncations.jsonl`, bilan imprimé en fin de run. Détail → §0.61. |
| **§0.65** | Le prix de la conformité de §0.64, **rendu** : la LoS de déploiement vectorisée | ✅ **LIVRÉ le 2026-08-03** — **aucun** changement de valeur | — | La règle est inchangée, son EXÉCUTION est vectorisée : jumeau de `hex_line_iter` une source → N cibles (`batch_hex_line_steps`) + la règle de blocage (murs, obscuring 13.10) appliquée à la grille (`batch_ground_hex_can_see`). **Phase de déploiement 3,58 → 1,33 s** (−63 %), part LoS **1,58 → 0,09 s** (−94 %), **146 781 → 0** paire tracée en Python. **ISO-VALEUR prouvé** : égalité hexe par hexe sur la totalité du pool et 2 terrains (+ 2 contre-épreuves ROUGES), et 90 empreintes de l'observation §0.40 identiques à `main`. Donc **rien à ajouter au lot de ré-entraînement**. `/code-review` a en outre trouvé et fait corriger un défaut **structurel** de §0.64 : la clé du cache des expositions potentielles ignorait les areas **obscurantes** (aucun terrain actuel ne déclenche le cas). Détail → §0.65. |
| **§0.64** | Le scoring de déploiement calculait la **LoS avec une autre implémentation** que le moteur | ✅ **ALIGNÉ SUR LA RÈGLE le 2026-08-03** — ⚠️ ré-entraînement **RÉTROGRADÉ** (mesuré : le modèle d'avant joue à 0.82 sur `main` d'après) | — (entre dans le lot §0.48) | `batch_has_los_from_source` (grille de murs **2D**) contre `compute_unit_los` (la règle : obscuring 13.10, plancher-occulteur 3D) : **607 désaccords sur 16 104 hexes** pour une seule source, tous dans le même sens. L'observation de déploiement (§0.40) et le score des 5 stratégies reposent donc sur une LoS **approximative**, alors que le docstring de `_has_line_of_sight` affirme le contraire pour le déploiement. 🟢 **Arbitrage : aligner** — l'observation annonçait « l'exposition réelle » alors qu'elle surestimait le danger sur ~4 % des hexes, faisant fuir à l'agent des positions sûres. Les DEUX canaux (réel et potentiel) passent par `deployment_los` → `compute_unit_los` ; cache disque invalidé par `DEPLOYMENT_LOS_MODEL_VERSION`. Coût : phase de déploiement **1,46 → 2,85 s** (+42 % sur `main`, le gain de §0.63 en absorbant une part) — ⚠️ **chiffre périmé le jour même par [§0.65](#s0.65)**, qui rend ce surcoût et davantage, à la valeur près. `obs_size` ET espace d'action inchangés : le modèle d'avant se charge et joue à **combined 0.82** (éval du 2026-08-03, §0.14) — **aucun run dédié n'est dû**. Reste dans le lot §0.48 parce que `L1`/`L2`/`L6` imposeront un `--new`, mais ce sont eux qui l'imposent. Détail → §0.64. |
| **§0.63** | Le cache de scoring du déploiement **ne servait jamais** (100 % de reconstruction) | ✅ **CORRIGÉ le 2026-08-03** | — | Deux causes, la seconde invisible sans la première : cache indexé sur les hexes de l'unité (condition jamais satisfaite), et déploiement **en alternance** avec un delta incrémental limité à une pose. Correctif : sur-ensemble stable (pool moins murs), **un cache par joueur**, delta généralisé à N poses. **Neutre pour l'observation, mesuré** (0 écart) → aucun ré-entraînement. Gain **2,01 s → 1,46 s** (−27 %) sur la phase de déploiement, reconstruction **100 % → 20 %**. Détail → §0.63. |
| **§0.60** | Instrumentation du **coût** de l'entraînement — workers d'éval, temps bloquant, courbes de charge et de participation | ✅ **LIVRÉ le 2026-08-02** | **2** | Trois angles morts de COÛT, distincts des angles morts de COMPORTEMENT du §0.56. (1) Quatre clés `bot_eval_*` vivaient **hors de `callback_params`** : personne ne les lisait, `bot_eval_n_workers` retombait sur `min(n_envs, n_scenarios × n_bots)` = **24 workers**, soit **47 Go et 598 s** contre **9,6 Go et 349 s** à 4 workers — moins de workers est aussi **42 % plus rapide**, la VM passant son temps à swapper. `validate_bot_eval_worker_params` valide désormais au DÉMARRAGE. (2) `blocking_eval_seconds` ne compte plus que le temps où la boucle est RÉELLEMENT figée. (3) Six courbes moteur : charges tentées/réussies (agent et bot) et participation par phase. Détail → §0.60. |
| **§0.59** | Régime d'entraînement en **deux phases** — `x1_selfplay` (self-play) et `decay_fraction` | 🟠 **OUVERT — livré, JAMAIS EXÉCUTÉ** | **2** | Deux changements de régime non mesurés. (1) `decay_fraction` achève les rampes lr/entropie **avant** la fin d'un run long (sans lui, un run de 200 000 épisodes garde une entropie élevée jusqu'au dernier épisode). (2) Le profil `x1_selfplay` ajoute une **phase 2** en `--append` : un snapshot figé de l'agent remplace le bot sur une part rampée **0.0 → 0.5** des épisodes. ⚠️ Aucun run de phase 2 n'a jamais tourné ; `opponent_mix.enabled` **lève** hors du chemin de rotation de scénarios. Détail → §0.59. |
| **§0.58** | Les rampes par-épisode **redémarraient à chaque reprise** (`--append`, `--resume-from`) | ✅ **CORRIGÉ le 2026-08-02** | **1** | Rien ne persistait le nombre d'épisodes joués : la rampe de déploiement n'atteignait jamais `active_ratio_end` et le compte cumulé du modèle était écrasé par celui du seul run courant. `ai/run_state.py` persiste le compte (compté, jamais dérivé de `num_timesteps`) ; reprendre un modèle sans lui **lève** (arbitrage : pas de compatibilité ascendante). `learning_rate`, `ent_coef` et le self-play sont des rampes de **RÉGIME** : elles repartent de zéro à chaque run, et c'est l'arbitrage. Détail → §0.58. |
| **§0.57** | Les rampes par-épisode du moteur avançaient **`n_envs` fois trop lentement** | ✅ **CORRIGÉ le 2026-08-02** — reste une conséquence à assumer | **1** | Le compteur d'épisodes du moteur est LOCAL à un worker ; il était divisé par le total GLOBAL. À `n_envs=48`, la rampe de déploiement est restée collée à `active_ratio_start` sur TOUS les runs vectorisés (mesuré : `s_deploy_active_share` 0.3040 pour 0.496 attendus). Même défaut sur `deployment_random_mix` (mécanisme SUPPRIMÉ le 2026-08-08, cf. §0.69). **Conséquence : aucune mesure passée n'a été produite avec la rampe annoncée** — §0.29 et §0.46 pt 2 sont amendés. Détail → §0.57. |
| **§0.56** | Instrumentation : usage par **famille d'action**, et **classement bot-contre-bot** | ✅ **LIVRÉ le 2026-08-02** — reste à s'en servir | **2** | Deux angles morts fermés, aucun ne coûte de ré-entraînement. (1) `actions/share_<famille>` publie la part de chaque DÉCISION dans ce que l'agent joue : une dimension jamais choisie ou toujours choisie est cassée quel que soit le win-rate — c'est ce qui rend un lot de tranches P3 diagnosticable **en un seul run**. (2) `scripts/bot_ranking.py` fait s'affronter les bots **sans agent** : sans lui, juger un bot exigeait un modèle entraîné, donc une mesure circulaire — et §0.55 était irréalisable. Détail → §0.56. |
| **§0.55** | Le **holdout d'évaluation** `TacticalBot` est DANS l'enveloppe d'entraînement — effet plafond | ✅ **LIVRÉ le 2026-08-04 — le mètre est GELÉ** | **1** (avant toute mesure de référence) | `tactical` gelé à **`w_objective 2.0`** (mesuré sur **x1**) : l'agent passe de **0.89 à 0.72** contre lui, et le bot de **dernier (0.357) à premier (0.636)** sur 6. `combined` inchangé à 0.8200 — le holdout pèse 0.0, c'est le contrôle que son statut est intact. ✅ Croisement `bot_eval/faction/<faction>/vs_<bot>` publié (méthode dédiée, dérivé du tally unique). 🔴 **Deux des trois leviers de la spec n'avaient aucune prise** : `w_enemy` est INERTE pour ce bot (mesuré + verrou), et le pas `0.5 → 0.8` tombait dans la partie morte d'une réponse en MARCHE. 🔴 **Piège à retenir : `--training-config` ne choisit PAS le plateau** (`config.json` → x5 ; les évals de référence passent `--resolution 1`) — une campagne entière a été jetée pour ça, et en x5 le diagnostic s'inversait. Détail → §0.55. |
| **§0.14** | Re-mesure du run — win-rate par matchup | ✅ **MESURE OBTENUE le 2026-08-03** — ⏳ **PÉRIMÉE depuis les chantiers 01/03/04** : le modèle mesuré n'est plus chargeable, cf. [§0.67](#s0.67) ; ⚠️ **sa remplaçante est DIFFÉRÉE après P3-4/5/6/8, P4 et P5** ([§0.70](#s0.70)) — le projet reste donc SANS mesure de référence d'ici là, et c'est assumé | — | Run de **200 000 épisodes** (2026-08-02 12 h 26 → 2026-08-03 02 h 05, 19 points d'éval, 820 k → 12,1 M steps). `eval_bots/combined_win_rate` **0,283 → max 0,837 → 0,743**. Éval rejouée le 2026-08-03 sur le snapshot ROBUSTE (`robust_0.8049`), APRÈS §0.64/§0.65 : **combined 0.8200**, `tactical` 0.89, `defensive` 0.87, `greedy` 0.84, `adaptive` 0.83, **`control` 0.82**, **`value_trade` 0.74** (le pire), **0 troncature**. Le seuil de gating `vs_control ≥ 0.50` est **franchi** — le **0.04 du run 4 est périmé**. ⚠️ 0,743 → 0,820 est un écart best-contre-final, PAS l'effet de §0.64. Détail → §0.14. |
| **[§9](V11_phaseA.md#s9)** | Phase A' — P2 + P3-0/1/2/**3**/**7** | 🟢 **LIVRÉS ET MERGÉS sur `main`** — restent **P3-4, P3-5, P3-6, P3-8**, **P4**, **P5** | **2** | ⚠️ **P3-7 (FLY / take to the skies) est livré et mergé le 2026-08-07** (élément `L6`) — [§9.4](V11_phaseA.md#s9.4) point 7 le décrivait encore comme « auto pour l'IA », corrigé le 2026-08-10 ; le reliquat n'est donc PAS « P3-4→8 ». ⚠️ **P3-3 (désignation de l'unité à activer) est livré et mergé le 2026-08-07** (élément `L2`, `ACTIVATE_SLOT` 1127-1138, `activate_query_net`) — cette cellule le comptait encore comme restant, corrigé le 2026-08-08. ⚠️ Aucune des cinq livraisons n'est **MESURÉE**. ⚠️ P3-0 est **inerte dans le training** (aucun roster SM/Ork ne porte de rule choice). Détail → §0.42 et §0.43 (en §0hist), et [§9](V11_phaseA.md#s9). |
| **§0.44** | Tête pointeur de **déploiement** — les slots 4-11 n'avaient pas de tête dédiée | ✅ **LIVRÉ ET MERGÉ le 2026-08-07** (`91cc70d1`, élément `L1` du lot §0.48) — ⏳ **NON MESURÉ** : la mesure viendra du run du lot | — | `deploy_query_net`, jumeau exact de `choice_query_net`, score les 8 slots ; ses logits **remplacent** les colonnes 4-11 de la conv 1×1 **en phase de déploiement seulement**, le routage lisant le bit `phase_deployment` de `global_bin` par échantillon. `deploy_emb` est exposé PAR SLOT en queue du vecteur de features ; le tronc n'en garde que l'agrégation (jumeau des ennemis et des candidats de décision). Ni `obs_size` ni `TOTAL_ACTION_SIZE` (**1127** ce jour-là ; **1139** depuis `L2`) touchés **par `L1`** — architecture seule (le 14609 → **14615** du même jour vient du drapeau `declines`, pas d'ici). Détail → §0.44. |
| **§0.48** | Inventaire des chantiers qui cassent un contrat + **périmètre du lot de ré-entraînement** | 🟠 **OUVERT** — le lot = **`L1` + `L2` + `L6`** + **[§0.64](#s0.64)** (LoS de déploiement alignée le 2026-08-03 ; ⚠️ **n'impose PLUS de run à elle seule** — mesuré le 2026-08-03 : le modèle d'avant joue à 0.82 sur `main` d'après, cf. §0.14 — elle **voyage** avec `L1`/`L2`/`L6`) | **4** | ✅ **Le prérequis d'ordre est LEVÉ au 2026-08-02** : les quatre chantiers exigés avant la mesure de référence — rampe de déploiement (§0.46 pt 2), FLY 21.03 (§0.49), bots d'éval (§0.47 É4), 01.07 (§0.50) — sont **tous mergés**. ✅ **L'arbitrage 2 est LIVRÉ le 2026-08-07** (socle : règles d'armes en ids, types de décision et slots de déploiement pré-dimensionnés — cf. §0.67). 🟢 **Le lot est COMPLET le 2026-08-07** : `L1` ([§0.44](#s0.44)), `L6` (FLY 21.03 en décision d'agent) et `L2` (choix de l'unité à activer) sont **livrés et mergés**. ⚠️ `obs_size` vaut **16659** et `TOTAL_ACTION_SIZE` **1139** (vérifié par exécution le 2026-08-08). **Il ne reste que le `--new` unique et sa mesure.** Détail → §0.48. |
| **§0.46** | Résidus du 2026-07-29 | ✅ **CLOSE le 2026-08-03** — les trois points sont livrés | — | ✅ **SOLDÉ le 2026-08-03** (arbitrage : GARDER, sous forme optimisée). Les 4 issues du cache de déploiement deviennent des **compteurs publiés en permanence** (`perf/*`) au lieu de traces invisibles hors `--debug` ; les 37 sites passent par `engine/debug_trace.py` (canaux `W40K_TRACE`, formatage différé) ; garde verrouillée par **21 tests**, dont une **analyse AST** (fichiers découverts par leur import) qui interdit f-string, formatage anticipé et mot-clé. La passe `/simplify` du même jour y a trouvé **un bug** (`flush=True` résiduel → `TypeError` dès que le canal s'allume) et **un verrou qui mentait** (canal `train` hors garde). ⏳ Première mesure : **100 % de reconstruction** du cache de déploiement — signalé, non ouvert. Détail → §0.46. |
| **§0.47** | Relecture T2→T5 du 2026-07-29 — 9 écarts | 🟠 **OUVERT — reste É9 (second siège + second scénario)** ; É5 et É7 ✅ corrigés le 2026-08-02 (É1, É2, É3, É4, É6 ✅ livrés **et mergés** ; **É8 est tombé**) | **6** | **É8 n'a plus d'objet** : `ai/analyzer.py` ne construit plus aucun chemin de board à la main (il lit `get_board_config()` / `get_board_size()`). **É9 était mal énoncé** : les **3 graines SONT couvertes** (`test_t5_bare_loop.py`, `for seed in (1, 2, 3)`) ; ce qui manque est le **second scénario** et les **2 sièges**. Détail → §0.47. |
| **§0.50** | Non-conformité **01.07** — travail de suite | ✅ **CLOS le 2026-08-02** (statut corrigé le 2026-08-03 : la colonne disait encore OUVERT alors que la cellule disait SOLDÉE ; **revérifié sur `main`** — `get("battle_shocked")` hors tests **0 hit**, `computeControlCounts`/`isObjectiveScoringWindow` **0 hit** dans le front) | — | ✅ **SOLDÉE le 2026-08-02** — les deux résidus sont traités : (1) le contrat de `battle_shocked` est **tranché en lecture STRICTE**, les 7 `get(..., False)` migrés en `require_key` ; (2) la 3ᵉ lecture d'OC du frontend (journal d'événements de `BoardReplay.tsx`) diffère l'instantané moteur au lieu de recompter. Détail → §0.50. |
| **§0.53** | Refonte du panel de bots — les adversaires ignoraient la condition de victoire | 🟢 **LIVRÉ ET MERGÉ** — plus aucun chantier ouvert (arbitrage du 2026-08-02) | — (à lire avant d'interpréter tout win-rate) | 🟢 **ARBITRAGE UTILISATEUR DU 2026-08-02 — (a) et (b) SONT SANS OBJET JUSQU'À LA DÉMO MÉTIER** : le travail porte sur **2 rosters seulement**, donc ni les matrices de matchups par roster ni le recalibrage des seuils de gate ne sont d'actualité. **Ne pas les re-signaler comme des chantiers ouverts.** Reste vrai et à retenir : (c) **aucun win-rate antérieur au 2026-07-30 n'est comparable** à un win-rate postérieur. ⏳ Le panel a **encore évolué depuis** : un **cinquième bot `ValueTradeBot`** a été ajouté, `bot_eval_weights` = `control` 0.40 / `value_trade`, `adaptive`, `greedy`, `defensive` 0.15 / `tactical` 0. Détail → §0.53 (en §0hist). |
| **§0.19** | Revérifier T1→T5 et la section 9 ligne à ligne | ⏳ **PARTIEL** | continu | T1 soldé (§0.19.1→§0.19.3) ; section 9 auditée le 2026-07-24 (→ [§9.0](V11_phaseA.md#s9.0)) ; **T2→T5 relus le 2026-07-29** — les écarts vivent en **[§0.47](#s0.47)**, pas ici. Reste ouvert : les ✅ de T2→T5 ne sont revérifiés que **par LECTURE** (aucune exécution), et la conformité littérale de T2 est indécidable. ⚠️ Sa **section** est restée en §0hist pour ne pas casser ses sous-ancres `§0.19.1`→`§0.19.3`. |

✅ **Contrôle de conformité du 2026-08-08** (vérification par lecture + exécution, PAS une
livraison — aucune ligne de code touchée ; il REMPLACE le contrôle du 2026-08-07, dont les
chiffres d'architecture étaient périmés le jour même par `L1` puis `L2`) :
- `obs_size` : `ObservationBuilder.SQUAD_OBS_SIZE_TARGET` = **16659** (14615 avant `L2` du
  2026-08-07 ; 14609 avant le drapeau `declines` de `L1` ; 20727 avant le socle, cf. §0.67), et
  les **8** profils de
  `config/agents/ArmageddonAgent/ArmageddonAgent_training_config.json` portent **16659**
  (`x1`, `x1_long`, `x1_selfplay`, `x1_debug`, `x5_new`, `x5_append`, `x5_long`, `x5_debug` —
  `x5_long` ajouté le 2026-08-10).
- `squad_obs_shapes()` : **26** clés ; `sum(prod(shape))` grille exclue = **16659**, égale à
  `SQUAD_OBS_SIZE_TARGET` (exécuté). `allies_*` a **12** lignes depuis `L2` (`K_ALLY_SLOTS`, qui
  vit désormais dans `observation_entities` — l'espace d'action en dérive).
- `macro_intents.TOTAL_ACTION_SIZE` = **1139** (dont `OATH_SLOT_BASE` 1107, 20 slots, puis
  `ACTIVATE_SLOT_BASE` 1127, 12 slots — `L2`) ;
  `DEPLOY_SLOTS` = ids **4..11** (8 slots décrits) dont `DEPLOY_STRATEGY_SLOTS` = ids **4..8**
  (5 jouables, `DEPLOY_STRATEGY_COUNT = 5`) ; `spatial_grid.GRID_CHANNELS` = **9** ;
  `MOVE_CELL_BASE` = 0 / `MOVE_CELL_COUNT` = 1024.
- `pointer_policy` porte **7** requêtes (exécuté le 2026-08-08) : `query_net`,
  `charge_query_net`, `fight_query_net`, `choice_query_net`, `oath_query_net`,
  **`deploy_query_net`** (`L1`, §0.44 close) et **`activate_query_net`** (`L2`). Les mentions
  « 4 », « 5 » ou « 6 requêtes » ailleurs dans ce document sont des états historiques datés.
- Les slots d'Oath sont **consommés** (chantier 03) : `action_decoder` les décode
  (`OATH_SLOTS`, `OATH_SLOT_BASE`) et `env_wrappers` les câble à `pending_oath_selection` — la
  mention « aucun consommateur avant le chantier 03 » de §0.48 est périmée.
- Livraisons ✅ des entrées ci-dessous **revérifiées présentes dans le code** : `ai/run_state.py`
  (§0.58), `ai/truncation_log.py` + `t_truncated_episodes` (§0.61), `Run rules:` dans
  `ai/step_logger.py`/`ai/analyzer*` (§0.62), `DEPLOYMENT_LOS_MODEL_VERSION` (§0.64),
  `batch_hex_line_steps`/`batch_ground_hex_can_see` (§0.65), `validate_bot_eval_worker_params`
  (§0.60), `actions/share_` + `scripts/bot_ranking.py` (§0.56), `bot_eval/faction/` et
  `tactical.w_objective = 2.0` gelé (§0.55), `ValueTradeBot` + poids `control 0.40` /
  `value_trade`, `adaptive`, `greedy`, `defensive` 0.15 / `tactical` 0.0 (§0.53).
- `raw_action_int % len(options)` : **absent du code vif** (ne subsiste que dans des commentaires
  historiques) — conforme à §0.42.
- `pointer_policy` : `query_net`, `charge_query_net`, `fight_query_net`, `choice_query_net`
  présents ; `action_decoder` décode bien `target_slot` pour la charge et la mêlée (§0.41, §0.43).
- **§0.44 est CLOSE dans le code** (vérifié le 2026-08-08) : `deploy_emb` est exposé PAR SLOT en
  queue du vecteur de features (`deploy_embeddings_slice`), le tronc n'en voit plus que
  l'agrégation, et les ids **4-11** sortent de `deploy_query_net` en phase de déploiement
  (`pointer_policy._point(self.deploy_query_net, ...)`). Jumeau côté `L2` :
  `ally_embeddings_slice` + `activate_query_net` pour les ids **1127-1138**.
- **§0.40** : les 5 points sont dans le code vif (`get_deployment_active_unit` qui lève,
  `squad_grid_anchor`, filtre `on_battlefield`, `open_deploy_slot_count` partagé,
  `deployment_slot_candidates`, purge du cache).
- `ai/scenario_manager.py` **absent** (§0.45) ; `_attack_sequence_rng` : **zéro occurrence**
  (§0.38) ; `get_best_enemy_*` : plus aucune définition (§0.46 pt 1).
- ⏳ **Historique du contrat** (chaque valeur a été l'état courant à sa date) : **20780**
  (2026-08-02, 20 clés) → **20752** (chantier 01, les 13 bits `rule_<effet>` devenus 8 slots d'ids
  de capacité + 4 d'ids de statut) → **20718** (chantier 04, réserves) → **20725** (chantier 03,
  capacités de faction) → **20727** (commit `02454a34`, 2026-08-06) → **14609** (socle du
  2026-08-07 : règles d'armes en ids) → **14615** (drapeau `declines`, arrivé avec `L1`) →
  **16659** (`L2`, `K_ALLY_SLOTS` 8 → 12). `TOTAL_ACTION_SIZE` 1107 → **1127** au chantier 01 →
  **1139** avec `L2`. Conséquence en **§0.67**.
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
`tests/unit/ai/test_schedule_decay_fraction.py::test_long_profile_is_its_reference_recalibrated`.

| Clé | `x1` (décision ci-dessus) | `x1_long` / `x1_selfplay` (HEAD) | Pourquoi l'écart |
|---|---|---|---|
| `bot_eval_freq` | **2000** (ancienne décision §0.14 : ~~4000~~) | **10000** | 20 évals sur 200 000 ép. ; à 5 000, les 40 évals coûteraient ~8 h 30 contre ~23 h d'entraînement. |
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

<a id="s0.70"></a>
### 0.70 Le `--new` du lot TOURNE — et il produit une BASE DE DÉVELOPPEMENT, pas la mesure de référence — 🟢 EN COURS (2026-08-10)

**Le run.** `python3 ai/train.py --agent ArmageddonAgent --training-config x1 --scenario bot --new --resolution 1`.
C'est le `--new` unique qu'appelaient [§0.67](#s0.67) et [§0.48](#s0.48) : le lot `L1`+`L2`+`L6`
est complet et mergé. ⏳ **Entrée périssable — reconfronter au réel avant usage.** Deux lancements
le **2026-08-10** : celui de **11 h 14** (`run_20260810-111425`) a été **arrêté** au bout d'une
minute, le run courant est celui de **11 h 17** (`tensorboard/x1_ArmageddonAgent/run_20260810-111734`,
PID 842478).

**Santé relevée à 1 748 épisodes** (lecture des events du run courant, aucune interruption) :
`00_critical/t_truncated_episodes` **0**, `game_critical/invalid_action_rate` **0.0**, PPO à
**171 408** steps (fps 232), `win_rate_overall` **0.24** et en progression
(0.097 à 124 épisodes sur le lancement de 11 h 14). Le correctif de [§0.68](#s0.68) tient : le run
a franchi le point de rollout qui a tué le précédent, et il apprend.

🟢 **ARBITRAGE UTILISATEUR DU 2026-08-10 — ce run est une BASE DE DÉVELOPPEMENT.** L'objectif est
de **faire jouer l'agent** (avoir un modèle chargeable, vérifier que l'architecture apprend), pas
de produire un score. **La mesure de référence est différée** jusqu'à ce que tout soit fini.

**Pourquoi c'est le bon ordre, et non un compromis.** [§0.67](#s0.67) pose la règle : tout chantier
cassant un contrat livré avant un run en impose un second. Or il reste ouverts
**P3-4** (allocation des pertes), **P3-5** (pile-in/consolidation), **P3-6** (move-after-shooting +
reactive move), **P3-8**, **P4** et **P5** ([§9.4](V11_phaseA.md#s9.4)) — et **chacun ajoute des
dimensions d'action ou d'observation**. Un `x1_long` lancé aujourd'hui (200 000 épisodes, ~20 h)
serait donc invalidé par la prochaine tranche P3, exactement comme le `combined 0.82` du run de
200 000 épisodes du 2026-08-02 l'a été par `L1`/`L2`/`L6`. La mesure de référence se paie **une
fois**, quand P3→P5 sont livrés.

⚠️ **Ce qu'il faut tenir en conséquence — le `combined` de ce run ne vaut PAS référence.** `x1` =
**10 000** épisodes et `bot_eval_final` = **100** parties par bot, soit une erreur-type de **5,0
points** sur un win-rate autour de 0,5 (IC95 ≈ ±9,8) — de quoi répondre « l'agent joue-t-il », pas
« combien gagne-t-il ». Ne pas s'en servir pour le gate `vs_control ≥ 0.50` ([§0.14](#s0.14)), ni
pour comparer à un chiffre antérieur. Le profil de la mesure reste `x1_long` (600 parties par bot,
erreur-type 2,0), et c'est lui qui portera la référence le moment venu.

🔴 **CORRIGÉ le 2026-08-10 — l'erreur était ici, pas dans la config.** Cette section affirmait
« `x1` = 50 000 épisodes » et signalait comme périmée la justification `bot_eval_final_normal` de
`ArmageddonAgent_training_config.json` (« inacceptable sur x1 (10 000 episodes) »).
**C'est l'inverse** : `x1.total_episodes` vaut **10 000** ; le 50 000 est `total_episodes_normal`,
une clé de **commentaire** que `train.py` ne lit pas (il lit `total_episodes`, cf.
`ai/train.py` `resolved["total_episodes"] = require_positive_int(budget, "total_episodes")`).
La justification de la config est juste, aucune correction ne lui est due. Le ROADMAP §5 reprenait
la même erreur : corrigé dans la même livraison.

🟢 **DÉCISION UTILISATEUR DU 2026-08-10 (2) — le run va au bout.** Motif : disposer d'un modèle
chargeable et d'une sortie d'`analyzer.py` exploitable pendant les tranches P3. Ce que ça n'est
pas : une mesure. Le modèle devient inchargeable à P3-4 (nouvelle dimension d'action) — sa valeur
est le **diagnostic de comportement**, pas le score.

🟢 **DÉCISION UTILISATEUR DU 2026-08-10 (3) — le regret de P3-8 se mesure sur CE run.**
[§9.0bis](V11_phaseA.md#s9.0bis) exige de mesurer le regret avant de brancher un optionnel, mais
la mesure de référence est différée après P3-8 : la contrainte était circulaire. Elle est tranchée
en faveur de la base de développement — le regret est un écart **relatif** (choix branché vs
heuristique auto), il supporte l'imprécision de 10 000 épisodes, alors que l'attente rachèterait
un `x1_long` complet (~20 h) au premier optionnel retenu.
<a id="s0.71"></a>
### 0.71 Le déploiement `auto` corrompait le ratio PPO ; `deployment_random_mix` supprimé — ✅ CORRIGÉ (2026-08-08)

**Symptôme (établi par lecture de la chaîne d'appels, puis verrouillé par test).** En épisode `auto`
de la rampe `deployment_mode_schedule`, `W40KEngine.step` recevait l'action échantillonnée par la
politique et lui **substituait** une pose tirée par le moteur (`_should_auto_deploy_for_agent` →
`_pick_placement_action`). SB3 range dans son rollout l'action échantillonnée ET son `log_prob`,
alors que la transition observée vient d'un autre slot : PPO calculait son ratio sur une action
jamais exécutée. Ordre de grandeur : ~10 steps de déploiement sur ~200 par épisode, sur ~70 % des
épisodes en début de rampe (`active_ratio_start` 0.3).

**Ce n'est pas un défaut préexistant.** L'ancien mode `fixed` ne produisait AUCUNE transition de
déploiement (positions rejouées au chargement, sans phase). La régression naît avec `auto`.

**Correction.** Ces steps sont **absorbés** par `BotControlledEnv._ensure_actionable_controlled_turn`
(`ai/env_wrappers.py`), la boucle qui fait déjà avancer la partie sans remonter les steps à
l'apprenant — c'est ainsi que les tours du bot et les `WAIT` forcés restent invisibles pour SB3.
Le déploiement étant la première phase, l'absorption tombe de fait pendant `reset()` : dérouler le
déploiement dans `reset()` aurait dupliqué le même parcours. Le moteur expose
`auto_deployment_action(mask)`, qui rend la pose et l'**arme** ; le `step` qui la reçoit l'exécute
telle quelle et lève si l'appelant qui a armé rejoue autre chose. Un appelant du moteur nu (tests,
scripts) voit toujours son action remplacée par une pose — là où aucun apprentissage ne se fait, le
remplacement est le comportement voulu.

**Verrou** : `tests/unit/ai/test_auto_deployment_absorbed_by_wrapper.py` — un épisode complet en
`auto` où aucun état rendu à l'apprenant n'est un déploiement du joueur contrôlé (rouge prouvé en
neutralisant l'absorption), le symétrique `active` (le déploiement DOIT rester la décision de
l'agent), et le contrat de la pose armée.

🟢 **Arbitrage utilisateur : `deployment_random_mix` est SUPPRIMÉ.** Ce bloc portait exactement le
même motif de substitution (branche jumelle du même `step`) et tirait ses poses par la MÊME fonction
`_pick_placement_action`, avec le même filtre `open_placement_slots`. Il ne se distinguait de `auto`
que par sa rampe, et il était `enabled: false` dans les 7 profils. Supprimés : le mécanisme moteur
(configuration par épisode, prédicat, branche de `step`, 3 clés de `game_state`), le bloc des 7
profils, l'épinglage « à l'arrêt » de `tests/unit/engine/_config_helpers.py` (plus rien à
neutraliser), et les mentions de doc. Les mentions historiques datées sont conservées et annotées.

<a id="s0.68"></a>
### 0.68 Le premier run du lot est mort sur une instrumentation morte depuis la migration aux entités — ✅ CORRIGÉ (2026-08-08)

**Symptôme.** Le `--new` du lot ([§0.67](#s0.67)) s'arrête en rollout sur
`TypeError: Unsupported observation batch type for metrics extraction: dict`
(`ai/training_callbacks.py`, `MetricsCollectionCallback._on_step`).

**Cause, mesurée.** Le bloc fautif alimentait trois courbes par phase
(`obs/<phase>_best_kill_probability`, `_danger_to_me`, `_valid_target_count`) en relisant le
**bloc « valid target » du vecteur PLAT mono-figurine** — 5 slots × 8 features en `obs[273:313]`.
Ce layout a disparu le 2026-07-28 avec la migration aux tenseurs d'entités : l'observation est un
`Dict`, l'extracteur n'avait plus rien à lire.

Ce qui l'a rendu visible seulement maintenant est la partie instructive. La branche est gardée par
`info['phase'] ∈ ('shoot','fight','charge')` sous `is_controlled_action`, et **aucune action
d'agent ne posait de `phase`** : mesuré sur 600 pas pilotés, `squad_shoot`, `squad_fight` et
`squad_charge` rendent `phase=None` ; la seule action d'agent qui en posait une,
`select_oath_target` (chantier 01), tombe sur `"command"`, hors du trio. `select_activation`
(`L2`, `_handle_select_activation_action` renvoie `game_state["phase"]`) est **la première action
d'agent à porter `"shoot"`** — 40 occurrences sur 600 pas, d'où la mort immédiate du run.

**Preuve que rien n'est perdu** : `obs/shoot` est **absent de tous** les fichiers d'events
TensorBoard (200k, x1_debug) — ces courbes n'ont jamais eu un seul point. Le test qui les
« verrouillait » (`test_observation_metrics_per_env.py`) **monkeypatchait l'extracteur** : il n'a
jamais regardé le layout (vert vacant, §0bis).

🟢 **Arbitrage : SUPPRESSION.** Ces trois grandeurs étaient des features **pré-calculées à la
main** du pipeline legacy ; les rebâtir supposerait de ré-implémenter le scoring heuristique que
la migration a justement retiré, pour tracer une courbe que personne n'a jamais vue. Ce qu'elles
avaient d'utile est déjà couvert en amont : `actions/share_<famille>` ([§0.56](#s0.56)) pour
« l'agent joue-t-il cette dimension », la participation par phase ([§0.60](#s0.60)) côté moteur,
et « avait-il des cibles » se compte sur le **masque**, pas sur l'observation. Supprimés : le bloc
de `_on_step`, `_extract_valid_target_metrics_from_obs`, `_get_observation_batch_from_locals`,
`OBSERVATION_PHASES`, l'accumulateur par-env et son flush, `log_observation_phase_metrics` et ses
12 tags, et le test qui les mockait.

**Verrou** : `tests/unit/ai/test_callback_ignores_observation_batch.py` — le cas exact
(observation `Dict` + action d'agent en phase de tir) plus deux cas anti-récidive (aucun lecteur
d'observation dans le callback, aucun émetteur `obs/*` dans le tracker). **Les trois rougissent**
avec les fichiers d'avant restaurés, vérifié.

📌 **Leçon (→ §0bis)** : une garde qui rend un chemin INATTEIGNABLE le fait passer pour sain. Ici
le code était mort **deux fois** — layout disparu ET condition jamais vraie — et c'est un chantier
sans rapport (`L2`, qui ajoute un `phase` à une info) qui l'a réveillé, en rollout, sur le run le
plus cher du projet. Le signal qui aurait dû alerter existait : **la courbe n'avait aucun point**.

<a id="s0.69"></a>
### 0.69 Le choix d'ARME en mêlée n'existe pas côté agent — ✅ LIVRÉ le 2026-08-23

**Constat, vérifié sur le code.** En mêlée, l'agent choisit sa **cible** et rien d'autre. L'action
`FIGHT_SLOT_BASE + slot_i` porte `target_slot` (`action_decoder.py`), le moteur le résout contre le
pool 12.05 (`w40k_core.py`, `squad_fight`), puis `squad_declare_fight`
(`shared_utils.py`) **auto-sélectionne l'arme CC de chaque figurine** par dégâts attendus contre le
T/Sv de la cible. Les seuls types de décision déclarés sont `rule_choice`, `waaagh_call` et
`fly_declaration` (`observation_entities.py`) : aucun n'est une arme.

**Pourquoi ça mérite d'exister.** L'agent désigne UNE escouade cible par activation, et 04.02 exige
que la cible soit engagée avec **la figurine** qui porte l'arme : une escouade coincée entre deux
ennemis perd les attaques des figurines qui ne touchent que l'autre. Le choix fin (cible par
figurine, ou arme par figurine) est donc un vrai levier tactique, pas un raffinement cosmétique.

**Ce que ça coûte, et c'est moins qu'il n'y paraît.** Le moteur sait déjà le faire : les wrappers
PvP `squad_declare_fight_model`, `squad_declare_fight_weapon` et `squad_declare_fight_weapon_qty`
(`fight_handlers.py`) existent, en jumeaux exacts des `squad_shoot_*`. Ce qui manque n'est pas la
mécanique de combat, c'est son EXPOSITION dans l'espace d'action et l'observation (les profils
d'armes y sont déjà, cf. §0.27).

**Contrainte tenue par le lot « attente forcée » du 2026-08-08** (cf. tour_de_jeu.md, STEP 7) :
l'auto-jeu du moteur ne porte QUE sur `wait`, jamais sur `fight_slot`. Un combat à cible unique
reste donc une décision de l'agent, et cette porte reste ouverte sans rien à défaire — c'est un
choix délibéré, pris alors que l'auto-jouer aurait économisé 3,4 steps par épisode (1,7 %).

<a id="s0.67"></a>
### 0.67 Les chantiers 01/03/04 ont cassé les DEUX contrats — plus aucun modèle ni aucune mesure ne décrit le code courant — 🔴 OUVERT (2026-08-07)

**Constat, vérifié sur le code le 2026-08-07** (aucune ligne touchée) :

| Contrat | Valeur au moment de la mesure §0.14 | Valeur à HEAD | Cassé par |
|---|---|---|---|
| `obs_size` | 20780 | **16659** (exécuté le 2026-08-08 ; 14615 avant `L2`, 20727 avant le socle du 2026-08-07) | chantier 01 (20752), chantier 04 réserves (20718), chantier 03 capacités de faction (20725), `02454a34` (20727), socle (14609), drapeau `declines` (14615), **`L2`** (`K_ALLY_SLOTS` 8 → 12, +2 044) |
| `TOTAL_ACTION_SIZE` | 1107 | **1139** | chantier 01 (20 slots d'Oath of Moment, consommés au chantier 03), **`L2`** (12 slots d'activation) |
| Architecture policy | 4 requêtes | **7** (`oath_query_net`, `deploy_query_net`, `activate_query_net`) | chantier 01, puis `L1`, puis `L2` |

**Ce que cela invalide, factuellement** :
- `ai/models/ArmageddonAgent/ArmageddonAgent_12345_robust_0.8049.zip` (et tous les autres) porte
  le contrat 20780/1107 : il est **inchargeable** par le code courant. Le dernier artefact du
  dossier date du **2026-08-03** ; le seul run postérieur est un `x1_debug` du 2026-08-05
  (`tensorboard/x1_debug_ArmageddonAgent`).
- Donc **le `combined 0.82` de [§0.14](#s0.14) ne mesure plus le code courant** — ni le gel du
  mètre de [§0.55](#s0.55), acquis le 2026-08-04 sur ce même modèle. La première mesure de
  RÉFÉRENCE reste à produire, et elle le sera nécessairement par un `--new`.
- **[§0.48](#s0.48) change de nature** : le lot `L1`+`L2`+`L6` n'est plus ce qui *déclenche* le
  ré-entraînement (il est déjà dû). L'arbitrage « un seul ré-entraînement pour tout le lot » garde
  son sens, mais son échéance est maintenant **le prochain run, quel qu'il soit** : tout ce qui
  doit voyager avec lui doit être livré **avant** ce run, sans quoi il faudra en payer un second.

🟢 **ARBITRAGE UTILISATEUR DU 2026-08-07 : `L1` + `L2` + `L6` + l'arbitrage 2 ENTRENT dans ce
run.** Plan retenu : un **socle** d'abord (les dimensions, seules), puis `L1`, `L6` et `L2` en
worktrees parallèles, puis un `--new` unique.

✅ **SOCLE LIVRÉ le 2026-08-07** — il ne contient que des DIMENSIONS, aucune tête, aucune décision
(pré-câbler la queue de features sans tête qui la lise aurait été de la plomberie morte, §0bis) :

| Ce qui est gelé | Avant | Après | Effet |
|---|---|---|---|
| Règles booléennes d'armes | 12 drapeaux + one-hot `[ANTI]` de 5, **par profil** | **6 slots d'`obs_id`** (3ᵉ `EmbeddingBag`, registre `config/weapon_rules.json`) | −6 160 scalaires ; une règle d'arme de plus coûte **0** |
| One-hot de type de décision | 2 colonnes (= types déclarés) | **`AGENT_DECISION_TYPE_SLOTS = 8`** | +6 scalaires ; L3/L4/L5/**L6**/L7/L10 ouvrent leur type sans retrain |
| Slots de déploiement (`L11`) | 5 décrits = 5 stratégies | **8 décrits**, `DEPLOY_STRATEGY_COUNT = 5` jouables | +36 scalaires ; une 6ᵉ stratégie = une constante, sans retrain |

**`obs_size` 20727 → 14609** (−29,5 %) et **`TOTAL_ACTION_SIZE` inchangé à 1127** (les ids 4-11
tombent dans la plage des cellules de move). Le bloc « armes » passe de **84 % à 78 %** de
l'observation.

⚠️ **Ce que le pré-dimensionnement d'un slot d'ACTION exige, et qu'un bit de règle n'exige pas** :
un slot de déploiement réservé est un id jouable. Sa sûreté tient à **une** borne —
`open_deploy_slot_count` plafonne à `DEPLOY_STRATEGY_COUNT` — et le décodeur **lève** si un id
réservé lui arrive quand même (verrou : `test_reserved_deploy_slot_is_refused_never_reinterpreted`,
vérifié ROUGE en retirant la garde). Défaut trouvé et corrigé à cette occasion : les bots d'éval
tiraient leurs poses dans `DEPLOY_SLOTS` (tous les ids) au lieu des slots portant une stratégie —
`KeyError: Missing deployment weight for action 9`. D'où `DEPLOY_STRATEGY_SLOTS`.

✅ **`L6` LIVRÉ le 2026-08-07** (worktree `L6-fly-decision`) — « take to the skies » (21.03) est
une DÉCISION D'AGENT. Le type `fly_declaration` consomme une réserve d'`AGENT_DECISION_TYPE_SLOTS` :
**`obs_size` inchangé par `L6`** (il valait 14609 ce jour-là ; il vaut **14615** depuis le drapeau
`declines`, arrivé avec `L1`) et **`TOTAL_ACTION_SIZE` reste 1127**. Le point de choix est posé par
`arm_fly_declaration_decision` (`action_decoder`) **avant la construction du pool** — c'est le
moment exact où le moteur tranchait — et couvre d'un seul site les DEUX mouvements que 21.03
énumère (move et charge, via la garde de phase `_TAKE_TO_THE_SKIES_BY_PHASE`). La constante
« déclare toujours » de [§0.49](#s0.49) point 5 est **supprimée**. ⚠️ Deux sets et non un :
`units_fly_declaration_resolved{,_charge}` porte « la question a été posée », que le set de
déclaration ne peut pas porter (un refus le laisse vide) — sans lui le choix se reposerait à chaque
masque et l'escouade ne bougerait jamais.

✅ **`L1` LIVRÉ ET MERGÉ le 2026-08-07** (`91cc70d1`) — cf. [§0.44](#s0.44), close.

✅ **`L2` LIVRÉ ET MERGÉ le 2026-08-07** (`b8be3f8e`, moitié moteur `590838ad` + moitié réseau
`bd09a277`) — l'agent choisit quelle escouade activer. `TOTAL_ACTION_SIZE` **1127 → 1139**,
`obs_size` **14615 → 16659**. **Le lot `L1`+`L2`+`L6` est donc COMPLET.**

⚠️ **Trois correctifs POST-MERGE de `L2`, tous sur `main`** (2026-08-08) — ils ne touchent aucun
contrat (`obs_size` et `TOTAL_ACTION_SIZE` inchangés), mais deux d'entre eux **changent ce que
l'agent joue**, donc ils précèdent le `--new` :
- `058204ff` — en insérant sa sortie entre `L6` (déclaration de vol 21.03) et l'ingress (20.04),
  `L2` avait inversé deux règles : une escouade FLY **en réserves** se voyait poser la question de
  vol et payait les −2" sur un mouvement qu'elle ne faisait pas.
- `f4f126ac` — `active_shooting_unit` était épinglé sur la tête du pool **à la construction de
  celui-ci**, donc avant toute décision : la décision `ACTIVATE_SLOT` disparaissait. Le prédicat
  `player_types == "ai"` n'étant vrai qu'en PvE, l'agent était **entraîné à choisir qui tire et
  privé de ce choix au service**. Second défaut mis au jour par la mesure, antérieur à `L2` : la
  clé n'était jamais libérée ⇒ en PvE l'IA ne tirait qu'UNE escouade par phase, l'exception étant
  avalée par le `except` de `execute_ai_turn`.
- `a90a8627` — cohérences de validation du masque de move (charge / surface manuelle / 21.03).

✅ **Commité depuis** (vérifié le 2026-08-10, `git status` propre sur le fichier) : le cas de
verrou ajouté à `tests/unit/engine/test_activation_choice_contract.py` (le JUMEAU de `f4f126ac` :
`_handle_shooting_end_activation` ne doit jamais désigner l'activation suivante).

**Prochaine action concrète — EN COURS** : le **`--new` unique** du lot tourne depuis le
2026-08-10 11 h 17 ([§0.70](#s0.70)). ⚠️ Il ne produit **pas** la mesure de référence : c'est une
base de développement, et la mesure qui remplacera le `combined 0.82` périmé de [§0.14](#s0.14) est
différée après P3-4, P3-5, P3-6, P3-8, P4 et P5 (arbitrage du 2026-08-10). La règle « aucun chantier cassant un
contrat avant le run, sous peine d'en payer un second » **ne s'applique donc plus à ce run-ci** —
elle s'appliquera au run de RÉFÉRENCE, et c'est précisément elle qui justifie de le différer.

<a id="s0.66"></a>
### 0.66 Le JOURNAL DU GYM mentait à l'analyzer, et deux règles de mouvement n'étaient pas appliquées — ✅ CORRIGÉ (2026-08-04)

Suite directe de [§0.62](#s0.62), par le bas : §0.62 a rendu l'analyzer juste, ce qui a permis de
lui faire relire un run de **600 épisodes** (x1, board 44x60x1) au lieu des 6 épisodes de
référence. Verdict : **2353 erreurs**. Le tri les sépare en trois familles, et la troisième est
celle qui compte.

⚠️ **Les valeurs absolues ne se comparent pas aux 206 erreurs de §0.62** : 600 épisodes contre 6,
soit ~34 erreurs/épisode avant, ~2,3 après. Ce n'est pas une régression.

#### A. Le journal du gym ne disait pas ce que le moteur faisait — 2 correctifs, ~1150 erreurs

**Le `[FLY]` n'était écrit NULLE PART sur le chemin d'entraînement.** `grep -c "\[FLY\]"` sur
24 Mo de `step.log` : **0**, alors que `SUSTAINED HITS` y apparaît 410 fois — le journal venait
donc bien d'un moteur à jour. La plomberie existait pourtant de bout en bout : `movement_handlers`
posait le drapeau, `_build_step_log_details` le mappait, `step_logger` l'écrivait. Elle était
posée sur les **chemins PvP**, qui n'émettent aucun `move_type` — clé exigée par le drainage vers
`step.log` — donc ne peuvent pas l'alimenter. Le **seul** émetteur du gym est la branche
`squad_normal_move / squad_advance / squad_fall_back` de `_process_squad_action`, et elle ignorait
`is_fly_move`. Conséquence : l'analyzer pathfindait au SOL des escouades qui volent, murs et
figurines compris → **1014 faux « au-delà du budget »** (mesuré en injectant le marqueur dans une
copie du journal : 2353 → 1339).

Le jumeau `squad_charge` avait le **même** trou et n'a été vu qu'au `/code-review` : les lignes
`CHARGED` ne portaient pas `[FLY]` non plus, alors que le formateur savait déjà le lire.

**Les 1521 lignes `CONSOLIDATED` étaient toutes datées `T1`.** `_append_fight_move_log` lisait
`game_state["current_turn"]`, une clé qui n'existe dans **aucun** `game_state` de ce moteur (le
compteur s'appelle `turn`), avec un repli silencieux sur `1` — le défaut anti-erreur que T1
interdit, et qui l'a rendu invisible. 11 sites portaient le même motif, tous passés en
`require_key`. Effet de bord vertueux : `tests/_state_invariants.py` gagne `turn`, que les fixtures
omettaient alors que la production le pose toujours.

#### B. Le lot d'allocation 04.03 fusionnait des attaques NON identiques — 898 erreurs

La clé de groupe ne portait que la **moitié** de l'encadré IDENTICAL ATTACKS : « same BS/WS, S, AP
and D characteristics » — et pas « **and which are affected by the same applicable abilities and
rules** ». Sur le roster Ork, Shoota (`RAPID_FIRE:1`), Kombi Shoota (aucune règle) et Kustom Shoota
(`RAPID_FIRE:2`) partagent ATK/AP/DMG : elles tombaient dans un lot unique, nommé
`Shoota / Kombi Shoota / Kustom Shoota` et ne portant qu'**une** valeur de `[RAPID FIRE:X]`, celle
de la première arme rencontrée.

**La résolution, elle, était juste** — les attaques sont comptées par intent, donc par arme. C'est
le lot d'allocation et le log qui mélangeaient. Le commentaire de `rapid_fire_applied` affirmait
une clé « (arme, cible) » qui n'a jamais existé : c'est ce qui a caché le défaut.

La clé reçoit donc `weapon_rules` (signature normalisée, paramètre compris) **et**
`rapid_fire_applied` — 24.30 dit « **APPLICABLE** », et deux figurines de la même escouade avec la
même arme n'y sont pas soumises pareil selon la demi-portée. RNG et NB n'y entrent **pas** : 04.03
ne les compte pas parmi les caractéristiques d'identité, les y mettre séparerait des lots que la
règle fusionne (contre-épreuve verrouillée par test).

#### C. ⚠️ Deux règles de mouvement n'étaient PAS appliquées — l'analyzer avait raison

**C'est la partie qui change le jeu.** 11.04 EFFECT, 12.03 EFFECT et 12.08 disent mot pour mot
« **Your unit moves as described in Moving (03)** ». Le move normal borne chaque figurine par un
champ géodésique qui contourne murs et figurines. `charge_build_valid_plan` et
`_assign_cells_toward_enemies`, eux, retenaient une cellule sur
`calculate_hex_distance(origine, cellule) <= budget` et ne validaient que la case d'**arrivée** :
le trajet n'était jamais regardé.

Cas E301, vérifié socle par socle : six figurines franchissent la ligne de murs de la colonne 33
avec un jet de 8, pour des trajets légaux de 8, 9, 11, 11, 12 et 13. **43 charges et 28
consolidations** dans ce cas sur le run — de **vraies** violations, pas des faux positifs.

`model_reach_predicate` devient la source unique de la portée par-figurine des mouvements sans
pool BFS, et réutilise la machinerie du move (mêmes obstacles de transit, même champ mémoïsé,
même sélecteur de géométrie). Le `/code-review` a trouvé que la version livrée était **inerte en
métrique `euclidean`** — c'est-à-dire dans tout le PvP et le bot PvE, où `distance_metric.move`
vaut justement `euclidean` : elle retombait sur la ligne droite. Corrigé, les trois géométries sont
traitées ; seule `cube` (vol déclaré 21.03) rend la ligne droite exacte, et c'est la géométrie de la
règle, pas un repli.

**Une charge ratée ou un WAIT en phase de charge comptait comme un charge move.** 11.04 place le
grant de Fights First sous « AFTER MOVING » du charge move ; 12.03/12.04 disent « made a charge
move this turn ». `end_activation(..., Arg3=CHARGE, ...)` marquait `units_charged` dès la fin
d'activation. Ces faux chargeurs passaient devant les vrais : **122 violations d'alternance**, dont
**60 lignes sur 60** vérifiées appartiennent à une escouade ayant fini son activation sans charger.
Le jumeau PvP passait déjà `PASS` — c'était une divergence gym.

#### D. Un contrôle d'analyzer mesurait la mauvaise grandeur — 144 erreurs

10.06 CLOSE-QUARTERS SHOOTING borne un tireur engagé non-MONSTER/VEHICLE aux armes
[CLOSE-QUARTERS] **et** aux unités « **engaged with your unit** ». Le contrôle comptait une faute
dès que `calculate_hex_distance(ancre_tireur, ancre_cible) != 1`. Faux deux fois : ancre au lieu du
par-figurine, et adjacence au lieu de la zone d'engagement (10 subhex à x5). Le moteur, lui, gate
bien sur `enemy_engaged_with_shooter`. **Troisième occurrence** de la famille « ancre vs
par-figurine », après le contrôle LoS et le fight non-adjacent (§0bis).

Le contrôle jumeau — « arme non-[CLOSE_QUARTERS] tirée en étant engagé » — exigeait lui aussi une
adjacence d'ancre de 1, donc restait à **0 en permanence** : un VERT VACANT. Corrigé, il révèle
**13 vraies violations** de 10.06 qui n'avaient jamais été visibles.

#### Conséquences pour le ré-entraînement

Les correctifs **C** (borne de trajet, `units_charged`) et **B** (lots d'allocation) **changent les
résultats de partie**. Ils ne cassent **aucun** des trois contrats de [§0.48](#s0.48) — `obs_size`,
espace d'action et architecture sont inchangés, le modèle se charge et joue. Ils n'entrent donc
**pas** dans le lot `L1`/`L2`/`L6`.

Mais ⚠️ **la mesure de [§0.14](#s0.14) n'est plus comparable** : `combined 0.8200` a été obtenu sur
un moteur où les charges traversaient les murs et où des escouades gagnaient Fights First sans
charger. Le prochain run doit repartir de ce code, et son win-rate ne se compare pas au précédent.

Coût mesuré du passage « vol d'oiseau » → « trajet » : **×1,71** sur une observation de phase de
charge (escouade de 10, 6 escouades ennemies interrogées). Une passe `/simplify` en a récupéré une
partie sans toucher à la sémantique — budget sorti de la clé de mémoïsation (le champ rend
`{cellule: coût}`, donc un champ calculé pour 12 répond pour tout budget ≤ 12 : **2 BFS par
figurine → 1**), champ euclidien mémoïsé (4,47 ms/figurine recalculés à chaque appel), prédicat
construit pour les seules figurines mobiles (12.03 immobilise celles au contact, cas normal d'un
pile-in).

#### Ce qui reste OUVERT

1. **42 erreurs « unité morte »** — l'en-tête de `step.log` n'expose qu'un `HP_MAX` par escouade
   alors qu'un personnage attaché en a un autre (preuve : un `Dmg:4HP` sur une escouade annoncée à
   2 PV par socle, alors que le moteur plafonne le dégât aux PV restants). L'analyzer reconstruit
   les PV avec une heuristique « figurine de front » et dérive. **Aucune des deux corrections
   évidentes ne marche** : `[TARGET_MODELS:]` est **vide** quand l'escouade meurt, donc lire les
   survivants ne peut pas servir d'oracle de mort ; et le journal ne dit **jamais** quelle figurine
   a encaissé. Il faut **ajouter au contrat** `step.log` l'identité de la figurine touchée
   (`#SquadID#ModelID`) sur les lignes de dégâts **et** une ligne de destruction d'escouade.
   🟢 Arbitrage utilisateur du 2026-08-04 : à traiter avec le choix de la figurine tuée par
   l'agent (`L3`), dont c'est le prérequis — pas un doublon.
2. ~~**Aucune ligne `PILED IN` dans 24 Mo de journal**, pour 1521 `CONSOLIDATED`~~ — **RÉSOLU le
   2026-08-09.** La sonde avait raison de disculper l'émetteur : le gym produisait bien les deux
   action_logs `pile_in`. Ils étaient **jetés après émission** — les trois sites `advance_phase`
   appelaient `_process_squad_action` sans **drainer** ses `action_logs`, or c'est cette transition
   qui déclenche `fight_phase_start` puis tout le PILE IN groupé (12.02). Instrumenté à l'époque :
   plan calculé 24 fois, commité 24 fois, action_log appendu 24 fois, **drainé 0 fois**. Les trois
   sites passent par `_advance_phase_and_drain` (`engine/w40k_core.py`).
   **Re-mesuré le 2026-08-10** sur un run vivant : 6 `PILED IN` pour 3 `CONSOLIDATED`, sur 3 tours
   distincts. Détail et bornes de cette mesure → [`Replay.md`](../Replay.md) §2.3.
   Leçon : « l'émetteur émet » ne prouve rien sur ce qui **atteint** le journal — c'est le motif
   « code testé mais jamais appelé » de CLAUDE.md T4, déplacé d'un cran vers l'aval.
   Voir aussi le bug ouvert `Documentation/Archives/chantiers/pile_in_overrun_par_figurine_2026-08-18.md`.

#### Leçon de méthode — le miroir, rejoué TROIS fois dans le même lot

Les trois défauts trouvés par `/code-review` ont la **même** signature : une correction posée d'un
côté d'un miroir et pas de l'autre. `[FLY]` sur le move mais pas sur la charge ; la borne de trajet
en `hex` mais pas en `euclidean` ; une fixture de test sur trois. C'est le motif que CLAUDE.md
désigne comme le n°1 du dépôt, et l'avoir su n'a pas suffi à l'éviter — **le grep du jumeau doit
être fait sur chaque correction, pas sur le lot**. Reporté en **§0bis**, qui en est la copie canonique.

Le `/simplify` a montré le corollaire structurel : les payloads d'`action_log` du gym sont des
**copies manuelles** de ceux du PvP, et c'est *pour cela* que `[FLY]` a pu manquer des deux côtés.
`fight_handlers._append_fight_move_log` est le précédent à imiter — il manque son équivalent
move/charge, consommé par les deux flux. **Tant qu'il n'existe pas, le prochain champ de log sera
oublié de la même façon.**

<a id="s0.62"></a>
### 0.62 L'ANALYZER mesurait à une autre échelle et avec d'autres règles que le run — ✅ CORRIGÉ (2026-08-03)

CLAUDE.md désigne `ai/analyzer.py` comme la stratégie de validation du training. Il rendait des
verdicts faux. Relevé en lisant `analyzer.log`, tranché et livré le 2026-08-03 ; trois passes de
`/code-review` et une de `/simplify` ont suivi, chacune trouvant des défauts nés du lot précédent.

**La cause première : l'analyzer se relisait lui-même au lieu de relire le run.**
L'échelle subhex venait de `board_config` — le fichier tel qu'il est **au moment de l'analyse**,
pas tel qu'il était pendant le run. Un run joué sur `board/44x60x1` relu avec un `config.json`
pointant `board/44x60x5` mesurait toutes ses distances ×5. L'effet va dans les deux sens et c'est
ce qui le rend coûteux : la zone d'engagement à 10 subhex au lieu de 2 **fabriquait** 132 faux
« shoot at engaged enemy », pendant que les portées et les budgets de move ×5 **masquaient** les
vraies violations — « out of range » et « distance > budget » restaient à 0 par construction.
Mesure : `206 erreurs → 50` en corrigeant la seule échelle, puis `→ 0`.

Le même raisonnement s'applique mot pour mot à `engagement_zone`, `distance_metric` et aux
toggles `game_config['move']`, qui venaient eux aussi du fichier courant — **sans** le garde-fou
qui protège l'échelle. Basculer `distance_metric.engagement` de `hex` à `euclidean` changeait
tous les verdicts d'engagement d'un vieux journal, en silence. Le moteur journalise désormais ce
qu'il **applique** (entête `Run rules:`), l'analyzer lit de là, et l'absence de la ligne est un
refus explicite — comme pour `Board:`.

**Trois déplacements sur cinq n'étaient pas contrôlés.** Move et advance l'étaient ; charge,
pile-in/consolidation et move réactif ne l'étaient pas, ou pas conformément :
- le jet 2D6 de charge, **en pouces**, était comparé à une distance en cases — à x5, un jet de 7
  devenait un plafond de 7 subhex au lieu de 35, et **toute** charge réussie remontait en faute.
  Inerte à x1, d'où l'absence totale de signal ;
- la mesure se faisait d'**ancre à ancre** : en V11 l'ancre d'escouade peut bondir plus loin
  qu'aucune figurine (reformation) ou moins loin que l'une d'elles ;
- aucun **pathfinding** : une charge par-dessus un mur n'était jamais signalée, alors que 11.04
  renvoie à Moving (03) ;
- pile-in (12.03) et consolidation (12.08) — MAXIMUM DISTANCE 3" — n'étaient contrôlés par RIEN.

Le contrôle est aujourd'hui **unique** (`_per_model_move_violation`) et partagé par les cinq
sites. Il l'a fallu : les cinq copies avaient déjà dérivé, et le filtre des socles morts n'existait
que dans deux d'entre elles. Un seul verdict est exposé — « la figurine n'a pas pu atteindre sa
destination dans son budget » — parce que distinguer « trop long » de « bloqué » exige d'explorer
au-delà du budget (flood ×4, 1,6 → 6,3 ms par socle à x5) sans rien garantir ; les deux compteurs
séparés d'autrefois entretenaient une fiction, celui qui affichait « distance > budget » restant
à 0 en permanence.

**⚠️ CONSÉQUENCES À ASSUMER**

1. **Aucun verdict d'analyzer antérieur au 2026-08-03 ne vaut.** Ni les « 0 erreur » (les contrôles
   ne regardaient pas), ni les erreurs remontées (elles étaient majoritairement fausses).
2. **Les journaux antérieurs ne sont plus analysables** : les entêtes `Board:` et `Run rules:` sont
   exigées, et leur absence lève. C'est le contraire d'une régression — c'est le repli silencieux
   qu'on supprime.
3. **Deux correctifs MOTEUR changent le jeu**, tous deux sur `reactive_move` : son rayon de
   déclenchement (9") et son budget (D6") étaient consommés comme des nombres de CASES, donc
   1,8" et 1,2" à x5 — capacité quasi éteinte hors x1 ; et le move ne déplaçait que l'ANCRE, les
   figurines des escouades multi-socles ne bougeant pas du tout. **Les modèles entraînés avant ont
   appris contre l'ancien comportement.**
4. Deux marqueurs **entrent dans `step.log`** : `[FLY]` (21.03, vol déclaré) sur les quatre verbes
   de mouvement, et `[SUSTAINED HITS]` (24.36) au tir comme en mêlée. Le contrat est écrit dans
   [Replay.md §2.3bis](../Replay.md) ; tout lecteur de journal doit accepter un token optionnel entre
   le verbe et `from` — c'est la dérive de cette grammaire, écrite en cinq exemplaires, qui a
   produit le défaut le plus coûteux du lot.

**Ce qui reste ouvert :** `build_rigid_plan` force le niveau 0 alors que
`translate_squad_to_destination` n'écrit que col/row — une unité à l'étage est validée contre le
sol. Défaut **préexistant et documenté** (`SQUAD_RIGID_MOVE_DESTINATION_LEVEL`, §0.34), partagé
par move, charge, advance et pile-in : le move réactif y est désormais conforme, pas plus faux.

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
[`ai/truncation_log.py`](../../../ai/truncation_log.py) possède le fichier — même découpage que
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

**Verrous** : [`tests/unit/ai/test_truncated_episodes.py`](../../../tests/unit/ai/test_truncated_episodes.py)
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

<a id="s0.63"></a>
### 0.63 Le cache de scoring du déploiement ne servait JAMAIS — 100 % de reconstruction — ✅ CORRIGÉ (2026-08-03)

**Origine** : la toute première mesure produite par l'instrumentation de [§0.46](#s0.46) —
`incremental: 0`, `full_build: 10` sur `bot-01`, à **23-48 ms** la reconstruction. Le mécanisme
de mise à jour incrémentale existait, était maintenu, et **n'avait jamais tourné**.

**DEUX causes, la seconde invisible tant que la première n'est pas levée.**

1. **Le cache était calculé sur les hexes valides de l'UNITÉ courante.** Sa condition de
   validité — « même jeu d'hexes valides ? » — ne pouvait donc jamais passer : le jeu change à
   chaque unité (le socle change la clairance) ET à chaque pose (l'hexe occupé sort du jeu).
   Le chemin incrémental, situé APRÈS ce test, était inatteignable.
2. **Les joueurs déploient en ALTERNANCE** (mesuré : `1,2,1,2,…`). Un cache unique se fait donc
   invalider à chaque pose par le changement de déployeur, et la mise à jour incrémentale
   exigeait un delta d'**exactement une** pose — or au retour d'un joueur il y en a **deux**
   (la sienne et celle de l'adversaire). ⚠️ Corriger (1) seul ne gagne **rien** : mesuré, 9
   reconstructions sur 10, soit exactement l'état d'avant.

**Correctif.**
- `deployment_scoring_hexes(game_state, deployer)` — **sur-ensemble stable** : le pool du joueur
  moins les murs. Ne dépend ni du socle ni des poses. Le consommateur filtrait **déjà** à la
  lecture (`for h in valid_hexes: los[i] = los_exposure_by_hex[key]`), il n'a pas bougé.
- **Un cache par joueur** (`{deployer: cache}`) : les pools diffèrent, l'alternance n'invalide
  plus rien.
- **Mise à jour incrémentale généralisée à N poses** de delta.
- Les hexes occupés ne sont **pas** retirés du sur-ensemble : les écarter est le travail du
  filtre de lecture. Les retirer ici faisait diverger l'incrémental de la reconstruction — le
  test d'équivalence l'a signalé sur cet exact point.
- Issue de compteur `full_build_hex_mismatch` → **`full_build_cold`** seul subsiste comme cause
  normale (une fois par joueur et par épisode).

**Neutralité pour l'observation — MESURÉE avant d'écrire une ligne de correctif.** Les grandeurs
mises en cache sont des propriétés de l'HEXE, pas de l'unité : sur les cinq unités d'un roster,
tous les ensembles sont **inclus** dans le plus grand et l'on relève **0 écart** sur les
intersections (`los_exposure_by_hex`, `potential_los_exposure_by_hex`, `ally_col_counts`).
Donc **aucun ré-entraînement** : l'agent voit exactement les mêmes valeurs.

**Verrou — `tests/unit/engine/test_deployment_cache_equivalence.py` (4)**, dont l'essentiel :
à CHAQUE pose et pour CHAQUE joueur, le cache vivant doit être égal, champ par champ, à une
reconstruction complète du même état. C'est ce test qui remplace un raisonnement cas par cas sur
les mises à jour — et il a effectivement attrapé **trois** défauts pendant l'écriture : le
retrait des hexes occupés, le delta limité à une pose, et le désaccord de LoS de [§0.64](#s0.64).
S'y ajoutent : le chemin incrémental est réellement pris (contre le VERT VACANT), un cache par
joueur, et l'invariant `valid_hexes ⊆ deployment_scoring_hexes` vérifié pour toutes les unités à
chaque étape.
**Contre-épreuves faites** : delta ramené à une seule pose → ROUGE ; rétabli → vert.

🔴 **UNE RÉGRESSION INTRODUITE PAR CE CORRECTIF, trouvée par `/code-review` et corrigée.**
Généraliser le delta à N poses a rouvert un trou que l'ancienne garde (`len(added_ids) != 1`)
fermait **par accident** : un **REPOSITIONNEMENT** d'unité déjà posée
(`deployment_recommit_plan`, atteignable par l'API) ne change pas l'ensemble des ids, donc le
cache se déclarait à jour et servait des expositions calculées depuis l'**ancienne** position —
scénario exécuté par la revue : **966 hexes faux**, comptés `incremental`. Corrigé par une
comparaison explicite des positions des ids communs, et **verrouillé** par
`test_repositioning_an_already_deployed_unit_forces_a_rebuild` (contre-épreuve : garde retirée
→ ROUGE sur 40 expositions).
⚠️ **La leçon** : une garde qui protège d'un cas *sans le nommer* ne survit pas à la
généralisation de ce qu'elle gardait. L'ancien code ne parlait que du nombre d'ajouts ; le
repositionnement n'était couvert par personne, et rien ne le disait.

📌 **Trou du verrou lui-même, corrigé** : la liste des champs comparés omettait
`ally_deployed_hexes` — construit par `append` dans le chemin incrémental et lu par
`nearest_ally`, donc **dans l'observation**. Choisir soi-même les champs à comparer reproduit
son propre angle mort ; les deux champs manquants ont été ajoutés.

**Affinages mesurés (`/simplify`)** : sur-ensemble mémoïsé avec les autres caches d'épisode (il
était recalculé à chaque consultation, y compris sur le chemin incrémental où il est jeté) ;
tableau numpy et import hissés hors de la boucle par ennemi (1,31 ms/ennemi) ; accumulation par
`np.flatnonzero` au lieu d'une boucle sur 16 000 hexes dont 0,1 % sont vrais (1,05 → 0,01 ms) ;
branche `current_deployer` devenue inatteignable supprimée (le cache est indexé par joueur) ;
la branche mono-hex de `_get_valid_deployment_hexes` appelle `deployment_scoring_hexes` au lieu
d'en recopier l'expression, ce qui rend l'invariant vrai **par construction** sur ce chemin ;
clés du cache renommées `valid_hexes`/`valid_hex_set` → **`scoring_hexes`** — l'ancien nom
désignait la fausse dépendance qui a coûté 100 % de reconstruction.

✅ **Suspension levée le jour même** : `_has_line_of_sight_cached`, `_count_los_exposure` et
`_count_potential_los_from_reference_hexes` (~80 lignes sans appelant) et `los_pair_cache` sont
**supprimés** par [§0.64](#s0.64) — l'alignement passe par `deployment_los`, pas par ces
méthodes. C'était le SECOND modèle de LoS du fichier, celui qui divergeait.
📌 **Manque à gagner signalé, non traité** : le cache DISQUE des expositions potentielles n'est
réécrit que s'il n'existe pas (`if not os.path.exists`). Les fichiers déjà produits sur les
hexes d'UNE unité restent valides (la clé de topologie ne dépend pas des hexes évalués) mais
**partiels** — 93 863 octets sur `main` contre 131 842 écrits ici pour la même topologie — et ne
sont jamais complétés : chaque processus repaie les ~30 % manquants. ⚠️ **Caduc depuis**
[§0.65](#s0.65) : ce que repaie un processus est passé de ~0,8 s à **~0,11 s** mesurées, le
compléter ne vaut plus le code qu'il demanderait.

**Gain mesuré** (3 graines, phase de déploiement complète) : **2,01 s → 1,46 s**, soit **−27 %**.
Taux de reconstruction **100 % → 20 %** (2 reconstructions à froid, une par joueur, puis 8 mises
à jour). ⏳ La part sur un run entier reste à confirmer par `perf/a_deploy_cache_full_build_rate`.

📌 **Une garde retirée, et pourquoi** : la mise à jour incrémentale n'écarte PAS les coordonnées
sentinelles, contrairement à la reconstruction. `_build_deployed_snapshot` les filtre déjà, donc
une garde ici serait inatteignable — la mutation qui la supprime laisse le test d'équivalence
vert, ce qui le prouve. ⚠️ La garde équivalente de la reconstruction est **morte pour la même
raison** ; elle est signalée, non touchée (hors périmètre).

<a id="s0.64"></a>
### 0.64 Le scoring de déploiement calculait la LoS avec une AUTRE implémentation que le moteur — 607 désaccords sur 16 104 hexes — ✅ ALIGNÉ SUR LA RÈGLE (2026-08-03) ; ⚠️ RÉ-ENTRAÎNEMENT REQUIS

**Trouvé par accident**, en écrivant le test d'équivalence de [§0.61](#s0.61) : il a signalé
607 valeurs d'exposition divergentes, et la cause n'était pas le cache.

**Le constat, mesuré.** Deux implémentations de ligne de vue coexistent sur le chemin du
déploiement :
- la **reconstruction** du cache utilisait `engine.hex_utils.batch_has_los_from_source` (supprimé depuis, cf. [§0.65](#s0.65)) —
  vectorisée, qui trace la ligne d'hexes et teste une **grille de murs 2D** ;
- la **mise à jour incrémentale** utilisait `has_line_of_sight` → `shooting_handlers._has_line_of_sight`
  → **`compute_unit_los`**, la règle du moteur.

Sur UNE seule source ennemie vers les 16 104 hexes du pool : **607 désaccords** (3,8 %), tous
dans le même sens — le batch voit, la règle moteur ne voit pas.

⚠️ **Ce que dit le code lui-même.** Le docstring de `_has_line_of_sight` affirme :
« *Thin wrapper over compute_unit_los() — the single source of truth — so eligibility, target
validation, reward and **deployment exposure** all enforce the same visibility as the shooting
pool.* » **C'est faux pour le déploiement** : son exposition passe par le batch 2D, qui ignore
ce que `compute_unit_los` applique (obscuring 13.10, plancher-occulteur 3D — cf. la tranche LoS
3D du tir).

**Portée — à ne pas surestimer.** Jusqu'ici la mise à jour incrémentale **n'a jamais tourné**
(§0.63), donc la production n'a jamais mélangé les deux : tout ce que l'agent a observé vient du
batch, de façon cohérente. Le défaut n'est pas une incohérence en production, c'est que
**l'observation de déploiement et le score des 5 stratégies reposent sur une LoS approximative**,
différente de la règle appliquée partout ailleurs.

🟢 **ARBITRAGE UTILISATEUR DU 2026-08-03 : ALIGNER SUR LA RÈGLE, sans hésitation.** Le
raisonnement, et il est juste : ça ne viole aucune règle 40K — le scoring de déploiement est une
heuristique de placement — mais l'observation §0.40 **annonce à l'agent l'exposition réelle** d'un
hexe. Calculée autrement que la LoS du tir, elle lui donne un modèle du monde qui n'est pas le
monde : il croit une position exposée que le moteur ne verra pas. Les 607 désaccords vont tous
dans le même sens (le batch voit, la règle ne voit pas), donc l'agent **surestimait** le danger
sur ~4 % des hexes et fuyait des positions sûres. « Non optimal » ET « trompeur ».

**Livré.** Point d'entrée unique et public `ActionDecoder.deployment_los(game_state, from, to)`
→ `has_line_of_sight` → `compute_unit_los`. ⚠️ **Signature périmée le jour même par
[§0.65](#s0.65)** : le point d'entrée est resté unique mais est devenu BATCH
(`deployment_los(game_state, from_hex, to_hexes)` → `batch_ground_hex_can_see`), et il ne passe
plus par `has_line_of_sight` — donc plus par le `hex_los_cache`, qui ne servait à rien ici.
**Les DEUX canaux** y passent : exposition réelle
(ennemis posés) et exposition **potentielle** (hexes de référence du pool adverse), dans la
reconstruction comme dans la mise à jour incrémentale. Un point d'entrée unique parce que c'est
la divergence entre deux chemins — invisible tant que l'incrémental ne tournait pas — qui a
produit ces 607 valeurs fausses.

⚠️ **Cache DISQUE invalidé par version de modèle.** `DEPLOYMENT_LOS_MODEL_VERSION = 2` entre dans
la clé de hachage des fichiers `.cache/deployment_potential_los/`. Sans ça, un run aurait relu les
fichiers produits par le modèle 2D et **le changement aurait été sans effet, en silence** — le
pire résultat possible. À incrémenter à chaque évolution du modèle de LoS.

📌 **Le coût de régénération était le seul risque, il est levé** : contrairement à ce que
l'agent avait annoncé, le canal potentiel n'itère pas sur les 16 472 hexes du pool adverse mais
sur un **échantillon de 4 hexes de référence** — 64 416 paires, ~0,8 s par topologie, payées une
fois puis mises en cache disque. C'est le canal RÉEL (N ennemis × 16 104 hexes, à chaque pose)
qui porte le coût.

**Coût mesuré** (phase de déploiement complète, 3 graines, cache disque chaud) :
| | phase de déploiement |
|---|---|
| `main` avant tout | 2,00 s |
| après §0.63 (cache réparé) | **1,46 s** |
| après §0.64 (LoS alignée) | **2,85 s** |
Soit **+42 %** sur l'état d'origine, le gain de §0.63 absorbant une partie du prix de la
conformité. 🟢 Arbitrage utilisateur : « aligner d'abord, optimiser ensuite ».
✅ **Le « ensuite » est fait le jour même, et le prix de la conformité est plus que rendu** :
cf. [§0.65](#s0.65) — la règle est inchangée, son EXÉCUTION est vectorisée.

⚠️ **RÉ-ENTRAÎNEMENT — RÉTROGRADÉ LE JOUR MÊME, PAR LA MESURE.** `obs_size` est **inchangé**
(aucun champ ajouté) et l'espace d'action aussi ; seules les **valeurs** du bloc candidats de
déploiement changent, sur ~4 % des hexes. Le modèle entraîné AVANT cette date se charge donc tel
quel sur `main` d'après — et **y joue à `combined` 0.82** (éval du 2026-08-03, cf.
[§0.14](#s0.14)). ✅ **Aucun run dédié n'est dû pour §0.64.** L'entrée reste dans le lot
[§0.48](#s0.48) parce que `L1` (architecture), `L2` (espace d'action) et `L6` (`obs_size`)
imposeront un `--new` de toute façon — mais ce sont EUX qui l'imposent, pas §0.64.
📌 Non mesuré, et à ne pas confondre : le COÛT propre de §0.64 (même modèle, même éval, sur le
moteur d'avant — parent de `d9d18622`). L'éval ci-dessus prouve que le modèle n'est pas cassé,
pas que les 4 % d'hexes ne changent rien.

**Code mort supprimé dans la foulée** : `_has_line_of_sight_cached`, `_count_los_exposure` et
`_count_potential_los_from_reference_hexes` (~80 lignes) n'avaient plus aucun appelant, et
`los_pair_cache` n'était plus lu. C'était le SECOND modèle de LoS du fichier — celui-là même qui
divergeait ; le garder, c'était offrir à quelqu'un de le rebrancher.

<a id="s0.65"></a>
### 0.65 Le prix de la conformité rendu — la LoS de déploiement est VECTORISÉE, à la valeur près — ✅ LIVRÉ (2026-08-03)

Le « ensuite » de l'arbitrage de [§0.64](#s0.64) (« aligner d'abord, optimiser ensuite »).
**Contrainte tenue : STRICTEMENT ISO-VALEUR.** Le bloc candidats de déploiement de l'observation
(§0.40) vient déjà de changer, ce qui impose un `--new` ; un second changement de valeurs en
imposerait un autre. Rien n'a bougé — prouvé, pas affirmé (voir « Preuve » plus bas).

**Où partait le temps — mesuré, pas déduit** (harnais : phase de déploiement complète jouée
action par action sur `holdout_regular/scenario_bot-01`, `x1_debug`, cache disque chaud ; ce
harnais chronomètre AUSSI la construction du masque et l'observation, il ne coïncide donc pas
avec celui du tableau de §0.64 — les deux colonnes ci-dessous sont mesurées avec LE MÊME, sur
`main` et sur la branche) :

| poste, 1 graine | avant | après |
|---|---|---|
| **phase de déploiement** | **3,58 s** | **1,31–1,37 s** (−63 %) |
| cache de scoring (= la LoS) | 1,58 s | **0,09 s** (−94 %) |
| dont paires LoS calculées | 146 781 | **0** |
| `_get_valid_deployment_hexes` | 0,64 s | 0,60 s |
| 3 graines, total | 10,75 s | **3,9–4,1 s** |

**Trois pistes de l'énoncé sont mortes, mesurées** — elles valaient d'être instruites, pas d'être
suivies :
1. *Indexer `hex_los_cache` par signature de terrain au lieu de le vider à chaque épisode.*
   **Sans objet** : 146 776 consultations pour 146 781 calculs, soit **zéro** réutilisation. Une
   source ennemie qui se pose demande 16 104 paires JAMAIS posées ; le cache n'a pas été mal
   entretenu, on ne lui repose simplement jamais la même question. (Entre ÉPISODES, la question
   se reposerait — mais 🟢 **arbitrage utilisateur : ne pas mesurer**, de nouveaux terrains
   arrivent et rendraient la mesure trompeuse.)
2. *Ne pas scorer les 16 104 hexes du sur-ensemble.* Le consommateur lit `valid_hexes`, dont la
   taille est **du même ordre** que le sur-ensemble (pool moins murs, moins clairance) : il n'y a
   pas de gras à couper là.
3. *Écrire un équivalent vectorisé.* C'est **celle-là** qui portait tout le gain.

**Livré.**
- `hex_utils.batch_hex_line_steps` — jumeau vectorisé de `hex_line_iter` : une source, N cibles,
  rang par rang, avec arrêt anticipé des rayons déjà bloqués (le pendant vectoriel de l'arrêt au
  premier bloqueur). Même nudge de départage, même `a + (b - a) * t` recalculé à chaque rang.
- `shooting_handlers.batch_ground_hex_can_see` — la RÈGLE de blocage (mur, ou case obscurante
  dont l'area n'est ni celle de la source ni celle de la cible, 13.10), appliquée à la grille.
  Elle vit à côté de la règle scalaire, pas dans `hex_utils` : la géométrie d'un côté, la règle
  de l'autre, c'est ce qui empêche un 3ᵉ modèle de naître.
- `ActionDecoder.deployment_los` reste le point d'entrée UNIQUE de §0.64, mais devient **batch**
  (un hexe → N hexes). Les deux canaux et les deux chemins du cache (reconstruction et
  incrémental) y passent toujours.
- ⚠️ `DEPLOYMENT_LOS_MODEL_VERSION` **reste à 2** : le modèle de LoS n'a pas bougé, seule son
  exécution. Vérifié plutôt que supposé — les fichiers `.cache/deployment_potential_los/`
  produits par la branche sont **octet pour octet identiques** à ceux de `main`.

**POURQUOI CE JUMEAU NE ROUVRE PAS §0.64.** Écrire un second chemin de LoS est exactement la
faute que §0.64 vient de réparer. Ce qui le rend acceptable ici : sur les paires du déploiement —
et sur elles seules — `compute_unit_los` **se réduit** à un unique tracé 2D, et la réduction se
démontre terme à terme sur son propre code (dict coordonnées-seules → empreinte = l'ancre → pas
de vantage latéral ; pas de `MODEL_HEIGHT` → pas de plancher-occulteur ; pas de `level` → wall_set
complet). Le raisonnement ne suffirait pas : c'est le VERROU qui rend la chose sûre.

**Preuve — `tests/unit/engine/test_deployment_los_vectorized_equivalence.py` (5)** :
- **égalité hexe par hexe** entre le tracé scalaire (`compute_unit_los`) et le vectorisé, sur la
  **TOTALITÉ du pool** (16 104 hexes) et sur **deux terrains** (`terrain-mc1` de production et
  `terrain-train-02`, 545 murs contre 1 098, 10 areas obscurantes contre 15), depuis des sources
  **construites** pour couvrir ce qui fait diverger : unités posées, **dans** une area obscurante
  (l'exclusion 13.10 côté source, justement ce que le tracé 2D condamné ignorait), collée à un
  mur, aux deux coins du pool. Le test refuse de passer si l'échantillon de sources ne contient
  aucune area obscurante, et si aucune source ne voit quoi que ce soit (vert vacant).
- l'HYPOTHÈSE du jumeau — la déduplication de `hex_line_iter` ne retire jamais rien, donc les
  deux chemins testent les mêmes cellules — est **vérifiée** (1 308 lignes : `len(ligne) == n+1`
  et aucun doublon), au lieu d'être laissée en commentaire.
- `hex_los_cache` doit rester **vide** après un déploiement : un retour au chemin par paire le
  remplirait de nouveau, et c'est ce que ce test interdit.
- **Contre-épreuves faites** (sans elles, un test vert ne prouve rien) : exclusion obscurante de
  la source retirée → **ROUGE, 727 hexes** ; nudge de départage retiré du seul jumeau vectorisé →
  **ROUGE, 3 hexes** (les lignes rasantes, exactement ce que le nudge départage). Rétablis, vert.

**Preuve de bout en bout, en plus du verrou** : `los_exposure_by_hex`,
`potential_los_exposure_by_hex` et `ally_col_counts` empreintés à CHAQUE pose, sur 3 graines
(90 empreintes SHA-256) — **0 écart** entre `main` et la branche. C'est l'observation §0.40
elle-même qui est comparée, pas seulement le prédicat de LoS.

**Effet de bord, mesuré et voulu** : le déploiement remplissait `hex_los_cache` de 146 781 paires
que **personne ne relit** en production (seul `LOS_DEBUG=1` s'en sert) et que **chaque
déplacement d'unité** devait ensuite reparcourir pour les invalider — 0,17 s rien que pendant le
déploiement, et le coût continuait pendant tout l'épisode. Le chemin batch ne l'alimente plus.

**Code mort supprimé** : `hex_utils.batch_has_los_from_source` (le tracé vectorisé **2D**, celui
qui divergeait de la règle sur 607 hexes) — §0.64 lui avait retiré son dernier appelant sans le
supprimer. Garder à côté d'un tracé vectorisé conforme un tracé vectorisé faux, c'est offrir à
quelqu'un de rebrancher le mauvais. Avec lui part `ActionDecoder._build_wall_grid`, son seul
fournisseur de grille, et le champ `_wall_grid_cache`.

🔴 **UN DÉFAUT DE §0.64 TROUVÉ PAR `/code-review` SUR CETTE LIVRAISON, ET CORRIGÉ.** La clé du
cache des expositions POTENTIELLES — celle du dictionnaire mémoire ET celle du fichier
`.cache/deployment_potential_los/<digest>.pkl` — ne retenait du terrain que les **murs**. C'était
exact du tracé 2D d'avant §0.64 ; c'est faux depuis que `deployment_los` applique aussi
**13.10**. Deux terrains aux mêmes murs et aux areas obscurantes différentes partagent donc le
même fichier, et le second relit **en silence, définitivement**, les expositions du premier.
📌 **Aucun terrain du dépôt ne déclenche le cas aujourd'hui**, et l'affirmation contraire de la
première rédaction de cette entrée était FAUSSE (corrigée par la 2ᵉ passe de `/code-review`) :
les seuls fichiers aux murs identiques — `terrain-mc1.json` et `terrain-train-01.json` — ont
AUSSI les mêmes areas obscurantes (vérifié in-engine : 1 098 murs, 15 areas, 15 288 hexes
obscurcissants des deux côtés, **signature identique**) et ne diffèrent que par `floors`, que le
tracé au sol ne lit pas. Ils partagent donc ce cache, **correctement** — et il ne faut surtout
pas ajouter `floors` à la clé pour « les séparer ». Ce qui est corrigé ici est **structurel** :
la clé doit décrire ce que le modèle LIT, sinon le premier terrain qui bougera une area
obscurante sans toucher un mur sera faux sans bruit — et de nouveaux terrains arrivent.
⚠️ **Aucun `DEPLOYMENT_LOS_MODEL_VERSION` ne pouvait rattraper ça** : le modèle n'avait pas
changé, c'est la CLÉ qui ne décrivait pas ce que le modèle lit. Correctif :
`shooting_handlers.ground_los_blocking_signature` — **dérivée des grilles de blocage
elles-mêmes** (digest de leurs octets + leur forme), et posée à côté d'elles. C'est ce qui rend
la clé complète PAR CONSTRUCTION : `batch_ground_hex_can_see` ne lit rien d'autre que ces deux
grilles, donc un 3ᵉ bloqueur qui y entrerait un jour entre dans la clé sans que personne ait à y
penser. 📌 La 1ʳᵉ version, elle, vivait dans `ActionDecoder` et **relistait** les bloqueurs de
son côté (murs relus du JSON brut avec un parseur maison, areas via `_get_obscuring_area_sets`) :
deux énumérations de « ce qui bloque » à deux altitudes, dont une seule savait ce que la règle
applique — la forme de défaut même que §0.64 a payée. Corrigé par `/simplify` (agents altitude
et réutilisation, convergents). Coût mesuré : **5,8 ms par épisode** (2 appels), donc pas de
mémoïsation — elle coûterait une 3ᵉ clé de cache et deux sites de purge pour 0,45 % de la phase.
Verrouillé par
`test_deux_terrains_aux_memes_murs_ne_partagent_pas_le_cache_potentiel`, qui CONSTRUIT le cas
(mêmes murs, une area obscurante déplacée) ; **contre-épreuve** : obscuring retiré de la
signature → **ROUGE**. Les fichiers `.cache/` produits avant ce correctif sont orphelins (leur
digest change) ; les régénérer coûte ~0,11 s.

**Passe `/simplify` (4 agents), au-delà du point ci-dessus.** Retenu : `offset_to_cube_vec`
existait en **3 exemplaires** dont un seul sous test — il vit désormais dans `hex_utils`, avec la
géométrie, et `ActionDecoder._offset_to_cube_vec` délègue ; la clé disque prend la clé mémoire
telle quelle (deux listes de paramètres à synchroniser, et `terrain_signature` est justement ce
qu'une rédaction avait oublié d'un côté) ; `mask_y` était un intermédiaire mort ; la double
indexation de la boucle de blocage devient un seul `sel` ; les expositions s'accumulent dans un
tableau numpy au lieu d'une boucle Python sur ~9 600 hexes par ennemi (0,60 → 0,004 ms), dans les
DEUX chemins du cache. **Écartés, mesure à l'appui** : fusionner les deux grilles (−6 % du tracé,
mais 953 des 1 098 murs sont DANS une area obscurante et l'exclusion 13.10 s'en trouverait
faussée) ; rétrécir `idx` rang par rang (−3 % de 0,09 s) ; vectoriser plus bas, dans
`_los_line_segment_clear` (réécriture du chemin chaud du tir ET du miroir WASM, sur le code que
§0.64 vient de désigner comme la référence unique).

📌 **Ce qui coûte maintenant, et qui n'est PAS le sujet de cette entrée** : `_get_valid_deployment_hexes`
devient le premier poste de la phase (0,60 s, dont 0,39 s de filtre de clairance par socle). Ce
code est antérieur, correct, et sans rapport avec la LoS — **signalé, non touché**.

📌 **Une remarque de §0.63 devient caduque** : le « manque à gagner » du cache disque des
expositions potentielles (fichiers partiels jamais complétés, chaque processus repayant les
~30 % manquants) valait ~0,8 s ; la régénération complète coûte désormais **~0,11 s** mesurées.
Le compléter ne vaut plus le code qu'il demanderait.

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
contrat d'observation (à leur date, `obs_size` inchangé — la valeur **20828** écrite ici était
FAUSSE, le contrat valait 20780 le 2026-08-02 ; à HEAD il vaut **14615**, cf. [§0.67](#s0.67)) :
ce sont des réglages de run, pas des changements d'architecture.

⏳ **Revérifié le 2026-08-07 — TOUJOURS OUVERT, à l'identique** : `ai/train.py` **lève** encore
hors du chemin de rotation de scénarios (`self_play_is_enabled` → `raise`), et
`ai/models/ArmageddonAgent/selfplay_snapshot.zip` **n'existe pas**. Aucune phase 2 n'a tourné.

✅ **Chaîne de câblage vérifiée bout en bout le 2026-08-10** (lecture, aucune exécution) — la
question « est-ce déjà câblé ? » a une réponse **oui**, sur les six maillons :
`x1_selfplay.opponent_mix` (config) → validation par `require_key` + bornes `[0,1]`
(`train.py` ~) → `build_self_play_kwargs` (`training_utils.py`, **source unique**) →
`BotControlledEnv` (`env_wrappers.py`) → publication du snapshot par
`_publish_self_play_snapshot` (`train.py`), une fois au démarrage (~) puis tous les
`snapshot_update_freq_episodes` (~) → rampes `decay_fraction` lues par `require_key`
(`train.py`, `3370`). Tests présents : `test_training_opponent_wiring.py`,
`test_schedule_decay_fraction.py`.
⚠️ **Câblé n'est pas éprouvé** : rien de tout cela n'a jamais tourné, et le premier
`--append x1_selfplay` sera aussi son premier test d'intégration. Le garde de `train.py` ~
ne bloque QUE le chemin mono-scénario — avec `--scenario bot` (rotation), il passe.

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
- ⚠️ **Aucun run de phase 2 n'a jamais tourné.**
- ⚠️ **PÉRIMÉ depuis le 2026-08-22** (curriculum par étapes, [bot.md#league](../../Roadmap/bot.md#league)) :
  `snapshot_model_path` et `snapshot_update_freq_episodes` n'existent plus. `opponent_mix` porte
  désormais `pool`, une LISTE PONDÉRÉE d'adversaires FIGÉS (archives d'étapes antérieures),
  répartie par ENVIRONNEMENT. Plus rien n'est republié pendant le run, donc le refus
  d'`opponent_mix` hors chemin de rotation — qui ne tenait qu'à cette republication — est tombé
  avec elle : les deux chemins lisent les archives de la même façon.
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

**Le compteur est COMPTÉ, pas déduit.** [`ai/run_state.py`](../../../ai/run_state.py) persiste le
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
[`ai/model_artifacts.py`](../../../ai/model_artifacts.py) énumère, copie et supprime le `.zip` avec
ses deux compagnons (`_vec_normalize.pkl`, `_run_state.json`). Cette liste était recopiée à la main
sur cinq sites — énumération canonique, rotation des checkpoints, promotion `--resume-from`, copie
du meilleur robuste, suppression d'un modèle périmé — chacun avec sa propre politique sur les
fichiers absents ; ajouter le troisième fichier a demandé de retrouver les cinq. La dérivation du
chemin d'un compagnon, elle, vit dans [`ai/companion_paths.py`](../../../ai/companion_paths.py) : elle
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
| déploiement | **la vie du modèle** | c'est une COMPÉTENCE acquise : la phase suivante démarre au niveau atteint |
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

**Verrous** : [`tests/unit/ai/test_run_state.py`](../../../tests/unit/ai/test_run_state.py) (dont la
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
aucun compteur global (`engine/w40k_core.py` init, `:1185` incrément dans `reset`). Les deux
rampes par-épisode du moteur divisaient pourtant ce compteur local par `total_episodes`, qui est
**global** :
- `_configure_deployment_mode_for_episode` (mode `fixed` ↔ `active`) ;
- `_configure_deployment_random_mix_for_episode` (randomisation des ACTIONS de déploiement) — **même
  défaut, jumeau confirmé**. ⚠️ Ce second mécanisme est **SUPPRIMÉ le 2026-08-08** (§0.69) : il
  faisait doublon avec le mode `auto`, qui tire déjà ses poses au hasard par la même fonction.

**Troisième site, trouvé au grep et corrigé lui aussi** :
`BotControlledEnv._compute_self_play_ratio_for_episode` ([`ai/env_wrappers.py`](../../../ai/env_wrappers.py))
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
⚠️ **Ce dernier point est PÉRIMÉ depuis le 2026-08-22** : la republication de snapshot a été
retirée avec `snapshot_model_path`, donc ce refus est tombé avec sa raison d'être. La méthode
s'appelle désormais `_compute_pool_ratio_for_episode` et la rampe vit dans
`ai/curriculum.ramped_ratio`, partagée avec les étapes du curriculum.

**Résultat complet du grep** (tout site divisant un compteur d'épisodes par un total) : 6 sites, 3
étaient faux (les 3 ci-dessus, corrigés), 3 étaient déjà justes —
`engine/game_state.py`, `ai/training_callbacks.py`, et les rampes `learning_rate` /
`ent_coef` (`_EpisodeRampCallback`, `ai/training_callbacks.py`). Ces dernières sont saines pour
une raison à noter : elles sont pilotées **par épisode** (et non par timestep), mais leur compteur
vient de la somme des `dones` du VecEnv — il est donc **global**, comme leur dénominateur.

Conséquence : la progression avançait **`n_envs` fois trop lentement**. À 48 envs et 200 000
épisodes, chaque worker n'en joue que ~4 167 ; la rampe aurait eu besoin de **4,8 millions**
d'épisodes globaux pour atteindre son gel. Vérification arithmétique du symptôme : 78 477 / 48 =
1 635 épisodes par env, `p = 0.3 + 0.5 × 1635/199 999` = **0.3041** — la valeur relevée, à 10⁻⁴.

**Ce que le dépôt faisait déjà juste.** Les deux AUTRES rampes par-épisode divisaient, elles, par
`episodes_per_env = ceil(total_episodes / n_envs)` : `engine/game_state.py`
(`roster_pool_schedule`) et `ai/training_callbacks.py`.

**La formule ne vit plus qu'à UN endroit** : [`engine/episode_schedule.py`](../../../engine/episode_schedule.py)
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
même raisonnement valait pour `deployment_random_mix` (ratio figé à `force_random_ratio_start`),
mécanisme depuis SUPPRIMÉ (§0.69).

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
### 0.55 Le holdout d'évaluation est DANS l'enveloppe d'entraînement — effet plafond sur le seul adversaire jamais vu — ✅ LIVRÉ le 2026-08-04 (le mètre est gelé)

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

✅ **RE-MESURÉ SUR LE RUN 200k (2026-08-03), ET LE DIAGNOSTIC TIENT — autrement.** Le panel n'est
plus écrasé comme au run 4, mais `tactical` reste **l'adversaire le plus FACILE des six**
(cf. [§0.14](#s0.14)) :

| | run 4 | run 200k (fin) | robuste, éval du 2026-08-03 |
|---|---|---|---|
| `vs_tactical` (holdout) | 0.95 | 0.83 | **0.89** — le plus haut |
| `vs_control` | 0.04 | 0.71 | 0.82 |
| `vs_value_trade` (le plus dur) | — | 0.65 | **0.74** — le `worst_bot_score` |

L'écart entre le plus facile et le plus dur n'est plus que de **0,15**, et le holdout est du
mauvais côté : l'agent bat 9 fois sur 10 le bot censé mesurer sa généralisation, pendant que
`value_trade` — un bot d'ENTRAÎNEMENT — le bat encore 1 fois sur 4. ⚠️ Corollaire pour l'étape 3
ci-dessous : la cible « `tactical` ne doit pas se classer dernier » est déjà violée dans l'autre
sens — il est **premier**, c'est-à-dire le plus faible.

---

#### ✅ LIVRÉ LE 2026-08-04 — le mètre est gelé, et ce que la spec avait faux

⚠️ **Tout ce qui suit ce bloc (arbitrage du 2026-08-02, préparatifs, étapes 1-3) est conservé
comme HISTORIQUE de la décision.** Deux de ses trois leviers se sont révélés sans prise à la
mesure ; ne pas s'y référer comme à une consigne.

#### 🔴 LE PIÈGE QUI A COÛTÉ UNE JOURNÉE — le plateau n'est pas dans le profil

`--training-config x1` **ne choisit pas le plateau**. Sans `--resolution` ni `W40K_BOARD_PATH`,
le plateau vient de `config/config.json` → `paths.board` = **`board/44x60x5`**, quel que soit le
nom du profil. Les évals de référence, elles, passent `--resolution 1` → `board/44x60x1`.
`scripts/bot_ranking.py` n'a **aucun** drapeau de résolution : il prend donc x5 par défaut.

Une première campagne de réglage (4 évals de 600 parties + 3 classements de 2 400 épisodes) a
tourné sur **x5** et a été **JETÉE** : `w_objective` multiplie des distances alors que
`hold_bonus` est une constante, donc leur équilibre — et le réglage qui en découle — n'est pas le
même d'une résolution à l'autre.

📌 **Symptôme à reconnaître** : les **six** bots décalés ensemble par rapport à une mesure de
référence. Un changement de plateau déplace tout le panel ; un changement de poids d'UN bot ne
déplace que sa colonne. C'est exactement ce qu'a montré le contrôle de reproduction, et c'est ce
qui a permis de refuser la conclusion au lieu de la publier.

**Règle** : fixer la résolution AVANT toute mesure, et l'écrire à côté du chiffre obtenu.

#### Ce qui est gelé

`config/bot_movement_weights.json` → `tactical` : **`w_objective 2.0`, `w_enemy 0.0`**, mesuré sur
**x1** (`board/44x60x1`), avec la justification écrite DANS le fichier (statut de holdout, les
trois pièges de lecture, et la mention que la valeur est gelée).
Statut inchangé et vérifié : poids **0.0** dans `bot_eval_weights`, **absent** de
`bot_training.ratios`, **exclu** du `worst_bot_score` — le re-profilage change la FORCE du
holdout, jamais son STATUT.

| sur x1, modèle robuste 0.8049 | avant (`0.5`) | après (**`2.0`**) |
|---|---|---|
| agent → `vs_tactical` | 0.89 (le plus FACILE des six) | **0.72** |
| `tactical` bot-contre-bot | 0.357 — **dernier sur 6** | **0.636 — premier** |
| `00_critical/a_bot_eval_combined` | 0.8200 | 0.8200 — **inchangé** |

📌 Le `combined` ne bouge pas, et c'est le contrôle qui prouve que le statut est intact :
`tactical` pèse 0.0, donc durcir le holdout ne peut ni gonfler ni dégrader le score suivi. Un
`combined` qui aurait bougé aurait signalé une fuite du holdout dans le critère.

**Pourquoi 2.0** : côté agent la réponse est une **marche** puis un **plateau** — 1.0, 2.0 et 8.0
donnent tous 0.72-0.73, donc la valeur exacte n'y change rien. Le départage vient du
bot-contre-bot, plat lui aussi entre 1.0 et 3.0 (0.62-0.64) puis déclinant (5.0 → 0.571,
8.0 → 0.541). `2.0` est au **milieu** de ce plateau : c'est le point le moins sensible à une
erreur de mesure. Ce n'est pas un optimum, et il ne faut pas le lire comme tel.

#### Le croisement bot × faction est publié (étape 2b)

`bot_eval/faction/<faction>/vs_<bot>` est émis depuis le **comptage existant**. Le tally a été
extrait en `_faction_bot_tally`, construit **une seule fois** dans `evaluate_against_bots` puis
dérivé deux fois : `_compute_faction_scores` (agrégat pondéré) et `_compute_faction_bot_win_rates`
(ventilation brute). Même geste que `scenario_bot_stats`, construit puis dérivé — un second
parcours de `results_list` laisserait les deux ventilations diverger sur un filtre.
`tactical` porte un poids nul, donc il est **absent de l'agrégat** et **présent dans le
croisement** : c'est précisément le `vs_tactical` par roster que l'entrée demandait.

⚠️ **Le croisement n'est PAS la décomposition de `bot_eval/faction/<faction>`**, malgré le préfixe
commun : l'agrégat est pondéré et exclut le holdout, les cellules sont des win-rates bruts et
l'incluent. Leur moyenne ne redonne pas l'agrégat, et c'est voulu — le docstring de
`log_faction_bot_win_rates` le dit, parce que la première personne qui vérifiera l'identité
conclura sinon à un bug.

Publication par **méthode dédiée** `log_faction_bot_win_rates`, comme `log_holdout_split_metrics`
et `log_scenario_split_scores` : une ventilation = un point d'entrée. La greffer sur
`log_faction_scores` aurait obligé chaque ventilation suivante à rallonger sa signature.
Verrous : `tests/unit/ai/test_metrics_tracker_utils.py` (3), `tests/unit/ai/test_bot_evaluation_utils.py`
(2). Mutations vérifiées ROUGE : retirer la boucle d'émission ⇒ 2 rouges ; passer le segment de
tag de faction à `_metric_slug` ⇒ 1 rouge ; recopier dans le croisement le filtre « faction
incomplète » de l'agrégat ⇒ 2 rouges.

#### 🔴 CE QUE LA SPEC AVAIT FAUX — deux leviers sur trois n'ont aucune prise

**1. `w_enemy` est INERTE pour `TacticalBot`.** Ce bot ne score pas ses destinations dans le plan
(w_objective, w_enemy) des cinq autres : sa géométrie ennemie lui est propre (portée de tir /
fuite des menaces de mêlée), et `_select_destination` — **seul** consommateur de `w_enemy` — n'est
atteint que dans la branche « plus aucun ennemi vivant », où le terme ennemi est vide par
construction (`if enemy_positions:`). Les deux branches réellement jouées font `w_obj, _ =
self._weights()`.
**Mesuré, pas déduit** : même appariement `control`↔`tactical`, mêmes graines, joué avec
`w_enemy` 0.0 puis 5.0 → **résultats identiques sur les 8 matchs**. Verrou :
`test_tactical_bot_movement_ignores_w_enemy_on_both_live_branches` (mutation vérifiée ROUGE en
câblant `w_enemy` dans les deux branches vives ; le test porte aussi un contre-contrôle
`w_objective`, sans quoi son vert serait vacant).
⇒ **Le re-profilage `w_enemy 0.0 → 0.6` de l'étape 2a n'aurait rien changé du tout.**

**2. `w_objective` n'est pas à la même ÉCHELLE que pour les autres bots.** Chez eux il pondère
**tout** le score de destination ; ici il ne pondère qu'un **terme correctif ajouté** à une
géométrie exprimée en hexes bruts. Tant qu'il vaut ~1, la correction d'objectif est négligeable
devant des distances de plusieurs dizaines d'hexes. D'où un effet **à seuil et NON MONOTONE** :

**Balayage complet sur x1** (chaque colonne : 600 parties pour la ligne agent, 2 400 épisodes pour
la ligne bot-contre-bot) :

| `w_objective` | 0.5 | 1.0 | **2.0** | 3.0 | 5.0 | 8.0 |
|---|---|---|---|---|---|---|
| agent → `vs_tactical` | 0.89 | 0.72 | **0.72** | — | — | 0.73 |
| `tactical` bot-contre-bot | 0.357 (6ᵉ) | 0.623 (1ᵉʳ) | **0.636 (1ᵉʳ)** | 0.616 | 0.571 | 0.541 |

⇒ **`0.8` était bien le mauvais coin du plan.** La réponse est une **MARCHE** : rien ne se passe
sous ~1.0, tout se joue entre 0.5 et 1.0, puis c'est plat. Le pas proposé par la spec (0.5 → 0.8)
tombait entièrement dans la partie morte.
⚠️ **Ne jamais interpoler entre deux points mesurés**, et ne jamais reprendre un chiffre sans sa
résolution : la même courbe mesurée en x5 est NON MONOTONE et classait `tactical` 2ᵉ dès 0.5.

⏳ **Campagne x5 JETÉE** (4 évals de 600 parties, 3 classements de 2 400 épisodes). Elle a servi à
une chose : établir le piège du plateau, et le fait que `w_enemy` est inerte — deux conclusions
qui, elles, ne dépendent pas de la résolution.

#### Classement bot-contre-bot — AVANT et APRÈS (étapes 1 et 3)

`scripts/bot_ranking.py`, 6 bots, pool holdout, `--episodes 20`, **2 400 épisodes par colonne**.
📌 **MÉTHODE réutilisable** : le run monolithique demande ~5 h ; il se découpe **par paire**
(15 processus, ~1/5ᵉ du temps de mur) sans rien changer aux résultats — la graine ne dépend que de
(seed, p1, p2, index de scénario, index d'épisode) et chaque appariement crée son propre env.
Corollaire : seules les 10 cellules impliquant `tactical` sont à rejouer après un changement de
ses poids, les autres étant bit-à-bit indépendantes.
⚠️ **`bot_ranking.py` n'a pas de drapeau de résolution** : exporter `W40K_BOARD_PATH` avant.

| rang | AVANT (`w_objective 0.5`) | APRÈS (**`w_objective 2.0`**) |
|---|---|---|
| 1 | `value_trade` 0.574 | **`tactical` 0.636** |
| 2 | `control` 0.529 | `value_trade` 0.526 |
| 3 | `adaptive` 0.522 | `control` 0.468 |
| 4 | `greedy` 0.494 | `adaptive` 0.460 |
| 5 | `defensive` 0.440 | `greedy` 0.451 |
| 6 | **`tactical` 0.357** | `defensive` 0.372 |

✅ **La cible de l'étape 3 est atteinte** : `tactical` passe de **dernier** à **premier**. Le
diagnostic d'origine de cette entrée — « le holdout est le bot le plus faible » — était donc
**exact**, et il se lit dans les deux mesures : dernier entre bots, et le plus facile pour l'agent
(0.89). ⚠️ Ce n'est vrai que sur x1 : en x5 le même bot sortait 2ᵉ, ce qui avait fait conclure à
tort que la prémisse était fausse.

✅ **BIAIS DE SIÈGE DU §0.56 — ÉCARTÉ, sur les deux plateaux.** Le siège « agent » gagne **0.480**
sur x1 (2 400 épisodes) et 0.476 sur x5 : un désavantage réel de ~2 points, sans commune mesure
avec le 6/8 (0.25) du smoke à n=8, qui était du bruit d'échantillon. Il s'annule de toute façon
dans le classement, qui joue les deux sièges de chaque paire.

#### ✅ RÉSOLU — pourquoi §0.14 ne se reproduisait pas : le plateau

Une éval de contrôle rendait `combined 0.6755` / `tactical 0.63` là où [§0.14](#s0.14) inscrit
`0.8200` / `0.89`. Modèle (md5 identique au snapshot robuste, stats VecNormalize idem), profil et
code de jeu ont été écartés un à un ; **la différence était `--resolution 1`** (cf. le bloc en
tête). Les chiffres de §0.14 sont donc **bons**, ce sont les mesures de contrôle qui portaient sur
`board/44x60x5`.

📌 **Ce que le contrôle de reproduction a permis, et qui vaut d'être gardé comme méthode** : les
cinq bots dont les poids n'ont pas bougé servent de témoins. Ils sont rendus **bit-à-bit
identiques** d'un run à l'autre (l'éval est déterministe), donc tout écart sur `vs_tactical` est
imputable au seul paramètre modifié — et un décalage des SIX témoins signale que c'est
l'environnement qui a changé, pas le bot. Sans ce contrôle, la campagne x5 aurait été publiée.

---

🟢 **ARBITRAGE UTILISATEUR DU 2026-08-02 — re-profilage validé, à écrire.** ⏳ *Historique — voir
le bloc LIVRÉ ci-dessus : le point 1 s'est révélé sans prise à la mesure.*
1. **Sortir `tactical` de l'enveloppe.** Piste proposée : `w_objective 0.8 / w_enemy 0.6` — un bot
   qui dispute les objectifs **et** se bat pour eux. Aucun bot d'entraînement n'occupe ce coin
   (`control` est passif au contact, `greedy` ignore les objectifs). Un holdout doit différer
   **en nature**, pas être plus faible en degré. La valeur exacte reste à régler par mesure.
2. **Ajouter le scalaire `vs_tactical` PAR ROSTER.** Aujourd'hui `ai/metrics_tracker.py` émet
   `bot_eval/vs_tactical` (tous rosters confondus) et `bot_eval/faction/<faction>` (le `combined`
   par faction), mais **pas le croisement** — or c'est exactement ce que
   [§10.6](V11_eval_strategy.md#s10.6) demande.

🛠️ **PRÉPARATIFS DU 2026-08-02 — spec appliquée le 2026-08-04**, avec les deux corrections de fond
consignées dans le bloc LIVRÉ ci-dessus.
✅ **Fenêtre d'application** : elle était ouverte le 2026-08-04 (aucun `train.py` en cours,
re-vérifié avant chaque écriture dans `config/`). La contrainte reste vraie pour la prochaine
fois : `config/` est **relu à chaud par les évaluations**, donc ce chantier s'applique **entre
deux runs, jamais pendant**.

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
   métriques pointent au même endroit au lieu de se compléter. ✅ **Ce n'est plus le cas au 2026-08-03** :
   le minimum a MIGRÉ vers `value_trade` (0.74) pendant que `vs_control` montait à 0.82, donc les deux
   métriques se complètent de nouveau. Le fait se lit directement — les
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
✅ **Le re-profilage est fait (2026-08-04)**, donc le préalable commun aux deux voies est levé et
§10.6 le consigne. 🟠 **Le CHOIX entre les deux voies, lui, reste ouvert et appartient à
l'utilisateur** : le holdout est de nouveau mesurable comme critère, il n'est pas pour autant
adopté comme tel.

<a id="s0.44"></a>
### 0.44 Tête pointeur de déploiement — les slots 4-11 n'avaient pas de tête dédiée — ✅ LIVRÉ le 2026-08-07 (élément `L1`), NON MESURÉ

**Ce qui est livré (2026-08-07).** `ai/pointer_policy.py` porte une **6ᵉ requête**,
`deploy_query_net`, jumelle exacte de `choice_query_net` : les logits des ids `4-11` sont
`q_deploy · c_i / sqrt(d)` contre les embeddings de `deploy_cand_encoder`, et ils **remplacent**
les colonnes correspondantes de la conv 1×1 des cellules.

- **Exposition.** `SpatialCombinedExtractor` publie `deploy_embeddings_slice()`, ajoutée **en
  dernier** (derrière les candidats de décision) pour ne décaler aucune borne existante. Le tronc
  ne reçoit plus les 8 embeddings aplatis mais leur **agrégation masquée** (`2 × entity_dim`) :
  c'est le traitement des ennemis et des candidats de décision, et l'argument qui justifiait
  l'aplatissement (« les logits sortent d'une tête indexée par le slot ») tombe avec cette tête.
- **Routage — le point dur.** Un même id signifie « cellule de move » ou « slot de pose » selon la
  phase. La policy lit le bit `phase_deployment` de `global_bin`, publié par l'extracteur
  (`deployment_phase_flag_index()`, calculé à partir de la composition réelle du tronc), et
  bascule par `torch.where` **par échantillon** — un lot vectorisé mélange les phases, une branche
  scalaire trancherait pour tout le lot. Hors déploiement les colonnes restent celles de la conv :
  le bloc `deploy_cand_*` y est nul par contrat, donc router quand même donnerait 8 logits égaux
  sur 8 cellules parfaitement jouables. Le bit ne peut valoir que 0 ou 1 (`global_bin` est hors
  `norm_obs_keys`) et un contrôle explicite lève s'il cesse de l'être.
- **Contrats.** `L1` ne touche **ni** `obs_size` **ni** `TOTAL_ACTION_SIZE` (**1127**) — c'est un
  changement d'**architecture** seul. ⚠️ `obs_size` vaut néanmoins **14615** et non 14609 : le
  drapeau `declines` du bloc candidat de décision est arrivé le MÊME jour, dans le même commit, et
  il n'a rien à voir avec cette entrée (cf. l'historique d'`AI_OBSERVATION.md`). Les 3 slots réservés (`DEPLOY_STRATEGY_COUNT = 5` <
  `DEPLOY_SLOT_COUNT = 8`) sont scorables mais le masque ne les ouvre jamais : leur embedding est
  nul, leur logit aussi, et ils restent masqués — c'est le pré-dimensionnement de `L11`, pas un
  défaut.
- **Verrous** (`tests/unit/ai/test_pointer_head.py`, `test_entity_encoder_extractor.py`) : les
  deux moitiés du routage (déploiement → pointeur, **et** les 5 autres phases → conv) rougissent
  ensemble si le sens du `torch.where` est inversé ; l'alignement `4 + i ↔ candidat i` (invariant
  D1) ; l'index du drapeau vérifié phase par phase sur le vecteur RÉEL ; le routage par
  échantillon sur un lot mélangé ; le gradient de `deploy_query_net` exigé **non nul** (il est
  branché par un `torch.where`, donc un `.grad` existant ne prouverait rien).
- **Limite assumée, nommée.** L'**ingress** (mise en place depuis les réserves, 20.04, en phase de
  MOUVEMENT) ouvre lui aussi les ids 4-11, mais `deploy_cand_*` n'y est **pas rempli** (§0.40 : le
  bloc est conditionné à la phase `deployment`). Ces ids y restent donc sur la conv 1×1, comme
  avant ce chantier — aucune régression, aucun gain. Le combler suppose soit un bit d'observation
  supplémentaire (`setting_up`), soit remplir le bloc hors déploiement : les deux **changent
  `obs_size`**, ce que le périmètre de `L1` interdit explicitement. À trancher avec le prochain
  chantier qui casse le contrat d'observation.

**Historique — le constat d'origine (2026-07-29).** Les ids d'action `4-8` tombent dans la plage des cellules de
move (`MOVE_CELL_BASE = 0`, `MOVE_CELL_COUNT = 1024`). Leurs logits sortent donc de la **conv 1×1
de la carte** (`_move_logits`), aux cellules `(0, 4..8)` de la fenêtre égocentrique — des cellules
qui n'ont aucun rapport avec les hexes candidats. Aucune tête ne lit les embeddings du bloc
`deploy_cand_*` : celui-ci n'atteint la décision que par le **conditionnement du tronc**
(`move_ctx_net`, dont la non-linéarité permet bien de réordonner les cellules entre elles, mais
indirectement).

**Ce qu'il fallait faire — la conception, tenue à la lettre.** Un `deploy_query_net`, jumeau de `choice_query_net` : le tronc émet une
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

**1. Code mort dans [`engine/macro_intents.py`](../../../engine/macro_intents.py).**
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
documents que la suppression rendait faux (`V11_phaseA.md` ~806 et ~959 affirmaient
`get_best_enemy_score_for_unit` « encore vive » ; bandeau PÉRIMÉ de `macro_intent.md` remonté en
tête de document, car sa table « Fichiers à modifier » PRESCRIVAIT encore de créer ces fonctions).
Écrite dans un `git worktree` séparé — le dépôt principal n'a pas été touché,
comme l'exigeait alors le gel du working tree. Contenu : les 3 fonctions et leurs imports locaux (73 lignes
retirées de `macro_intents.py`), **plus deux `pop()` d'invalidation devenus morts avec elles** dans
`set_hp_in_cache` ([`shared_utils.py`](../../../engine/phase_handlers/shared_utils.py),
clés `_cached_best_enemy_global` / `_cached_best_enemy_score` — vérifié qu'elles n'ont plus aucun
autre écrivain ni lecteur ; `_best_weapon_cache`, lui, reste VIVANT et n'est pas touché), et un
bandeau « PÉRIMÉ depuis §0.43 » sur `Documentation/Archives/chantiers/macro_intent.md`, dont une section décrivait ces
fonctions comme du code vivant. Vérifié dans le worktree : import du module OK,
`test_action_space_mirror.py` + `test_squad_charge_target_parity.py` = **21 tests verts**.
→ **Reste à faire : MERGER cette branche** (ne rien réécrire, elle est prête). ⚠️ Elle n'est pas
validée au-delà de ces tests ciblés — la vérification large appartient à l'utilisateur (§0.51).

**2. Rampe de déploiement réglée sur le SEUL profil `x1`.** Vérifié dans
[`ArmageddonAgent_training_config.json`](../../../config/agents/ArmageddonAgent/ArmageddonAgent_training_config.json) :

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
sur [`ai/train.py`](../../../ai/train.py), [`ai/env_wrappers.py`](../../../ai/env_wrappers.py),
[`engine/action_decoder.py`](../../../engine/action_decoder.py) et
[`engine/w40k_core.py`](../../../engine/w40k_core.py), toutes **conditionnées** à
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
[`engine/mask_verification.py`](../../../engine/mask_verification.py) pour `W40K_MASK_VERIFY`, avec
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
3. 🔴 **Le taux de reconstruction du cache était de 100 %** (`bot-01` : `full_build` 10,
   `incremental` **0**), à 23-48 ms la reconstruction. ⏳ D'abord classé « signalé, non ouvert » —
   la part sur un run entier étant inconnue — puis **ouvert le jour même sur arbitrage
   utilisateur** et corrigé : cf. **[§0.63](#s0.63)** (deux causes, dont l'alternance des
   déployeurs) et, en cascade, **[§0.64](#s0.64)** (le test d'équivalence écrit pour le verrouiller
   a révélé que le scoring n'utilisait pas la LoS du moteur).
   📌 **C'est le meilleur argument rétrospectif pour l'axe A** : le défaut était là depuis
   l'origine, il ne levait rien, ne faisait échouer aucun test, et n'est devenu visible qu'au
   moment où un compteur l'a rendu observable.

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
relecture spec par spec de [`V11_tranches.md` §5](V11_tranches.md#s5) — T2 (524-578), T3 (579-638),
T4 (640-702), T5 (704-761) — plus [§8.2](V11_tranches.md#s8.2) et [§8.3](V11_tranches.md#s8.3),
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

[`scripts/roster_matchup_stats.py`](../../../scripts/roster_matchup_stats.py) appelle
`get_action_mask_and_eligible_units` — **layout legacy** : il passe par `_build_mask_for_units`
([`engine/action_decoder.py`](../../../engine/action_decoder.py)), qui pose
`mask[9]` charge, `mask[10]` fight, `mask[11]` wait, `mask[4+i]` tir. Ce masque est donné tel quel
à `model.predict` ([:563](../../../scripts/roster_matchup_stats.py)), puis l'action retenue part
dans `env.step` ([:565](../../../scripts/roster_matchup_stats.py)), qui la décode en **sémantique
squad** (`convert_squad_action`, [`engine/w40k_core.py`](../../../engine/w40k_core.py)).

Deux faits contre-vérifiés, à ne pas perdre :

- **(a) Aucune exception de forme — le résultat est silencieusement faux, pas bruyamment cassé.**
  Les DEUX masques sont dimensionnés à `self.total_action_size` = **1127**
  ([action_decoder.py](../../../engine/action_decoder.py) et
  [:208](../../../engine/action_decoder.py)). `predict` ne peut donc rien détecter : les bits
  autorisés désignent simplement d'autres intentions que celles que le décodeur lira.
- **(b) L'évaluation DU RUN EN COURS n'est PAS touchée.** Elle passe par `env.get_action_mask()`
  ([`ai/bot_evaluation.py`](../../../ai/bot_evaluation.py),
  [:523](../../../ai/bot_evaluation.py)) — chemin squad correct. **Seul l'outil hors-ligne de
  statistiques par matchup est atteint** ; les win-rates qu'il produit sont à jeter tant qu'il
  n'est pas corrigé.

**Incohérence interne au fichier** : le même `roster_matchup_stats.py` utilise la **bonne** voie à
[:509](../../../scripts/roster_matchup_stats.py) (`return env.get_action_mask()`). Un seul des
deux chemins a été migré.

✅ **CORRIGÉ ET MERGÉ** — branche `v11-0.47-eval-tooling-mask`, commit **`9eab91a1`** : le masque ⏳ **MERGÉ depuis — vérifié le 2026-08-02 ; la branche citée est supprimée.**
vient désormais de `env.engine.get_action_mask()`, **le même appel que la boucle de référence**
([`ai/bot_evaluation.py`](../../../ai/bot_evaluation.py)).

⚠️ **L'outil portait TROIS AUTRES défauts que cette entrée ne mentionnait pas**, découverts en
corrigeant celui-ci et livrés sur la même branche (constaté le 2026-07-29 à 13 h 56) :

- **(1) L'outil ne pouvait pas DÉMARRER** — `1d38f5de`. L'observation du pipeline squad est un
  `gym.spaces.Dict` ([`w40k_core.py`](../../../engine/w40k_core.py)) et la boucle l'**aplatissait**
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
  siège étant écrit dans l'info par le moteur ([`w40k_core.py`](../../../engine/w40k_core.py)) ;
  et le repli silencieux `info.get("winner")` → `None` (compté **défaite**) est supprimé **des deux
  côtés**, script **et** référence de production [`ai/bot_evaluation.py`](../../../ai/bot_evaluation.py)
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

Définie [`engine/action_decoder.py`](../../../engine/action_decoder.py), elle
contient **encore en dur l'ancienne sémantique** : `action_int in [4,5,6,7,8]`
([:820](../../../engine/action_decoder.py)), `== 11` wait
([:854](../../../engine/action_decoder.py)), `== 9` charge
([:895](../../../engine/action_decoder.py)) — et son satellite
`_get_valid_actions_for_phase` ([:415-425](../../../engine/action_decoder.py)) rend
`[4,5,6,7,8]` / `[0,1,2,3,11]` / `[9,11]`.

**Contre-vérifié : aucun appelant de production.** Les seules occurrences hors du fichier sont des
**chaînes de debug** qui la nomment ([`engine/w40k_core.py`](../../../engine/w40k_core.py)
et [:1703](../../../engine/w40k_core.py)). La production appelle `convert_squad_action`
([`engine/w40k_core.py`](../../../engine/w40k_core.py),
[`engine/pve_controller.py`](../../../engine/pve_controller.py)).

Elle est **verrouillée par ~25 cas** de
[`tests/unit/engine/test_action_decoder.py`](../../../tests/unit/engine/test_action_decoder.py)
(:242, :249, :256, :280, :287, :313-340, :400-448, :464, :591-631), dont la fixture de masque fait
**31 entrées** ([:297](../../../tests/unit/engine/test_action_decoder.py)) — c'est-à-dire l'ancien
espace d'action, pas 1127.

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
(`architecture_moteur.md`, `TESTING.md`, `geometrie_et_distances.md`), sont alignés.
`tests/unit/engine/test_action_decoder.py` passe de **55 à 27 tests** (constaté par
`git show <branche>:<fichier>` à 14 h 05) : ce sont les cas de la sémantique morte qui partent.
Deux commits de relecture s'y sont ajoutés : **`a210008c`** supprime aussi
`get_action_mask_and_eligible_units` et `_build_mask_for_units` (le masque de l'ancien espace,
orphelin de son décodeur) et pose une **pierre tombale** à leur place ; **`f0ed563a`** retire trois
symboles morts **préexistants** croisés pendant l'audit (`charge_handlers._select_strategic_destination`,
qui n'avait jamais eu d'appelant et survivait derrière son homonyme, plus
`ActionDecoder.get_all_valid_targets` et `can_melee_units_charge_target`, présentées comme
« Key Methods » par `architecture_moteur.md` et appelées nulle part).
⚠️ **Cette branche n'est PLUS autonome** : elle suppose la migration portée par
`v11-0.47-eval-tooling-mask` — voir la contrainte d'ordre de merge en [§0.51](#s0.51).

#### É3 — le verrou anti-récidive R5 exigé par §8.2 n'existe pas — ✅ CONTRE-VÉRIFIÉ, ✅ ÉCRIT (non mergé)

[§8.2](V11_tranches.md#s8.2) exigeait un fichier
`tests/unit/engine/test_agent_interface_contract.py` vérifiant que **chaque entier d'action est
routé vers l'intention attendue**, et le qualifiait de « **LE** verrou anti-récidive de R5 ».
**Contre-vérifié : ce fichier n'existe pas et n'a jamais existé.**

Le substitut réellement présent,
[`tests/unit/engine/test_action_space_mirror.py`](../../../tests/unit/engine/test_action_space_mirror.py),
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
⚠️ ~~**Ce verrou fige l'espace d'action COURANT (1107 alors, 1127 depuis le chantier 01)** : il devra être mis à jour avec le lot
(§0.48, dépendances).~~
✅ **MIS À JOUR PAR `L2` LE 2026-08-07 — la conséquence annoncée est payée.** `TOTAL_ACTION_SIZE`
**1127 → 1139** (12 slots d'activation). Trois verrous ont bougé, et **un quatrième a servi à
autre chose que ce pour quoi il avait été écrit** :

- `test_action_space_mirror.py` — la queue de l'espace n'est plus Oath mais l'ACTIVATION. Le cas
  a été reformulé sur la **chaîne** des blocs (`CHOICE → Oath → ACTIVATE → TOTAL`) et non sur
  « Oath ferme tout » : écrit ainsi, il redemandait une réécriture à chaque bloc ajouté.
  Nouveau cas `test_activate_slots_mirror_the_ally_slot_mapping` — le compte de slots est
  confronté à la cardinalité **réelle** du tenseur allié, pas seulement à sa constante.
- `test_agent_interface_contract.py` — même reformulation en chaîne, plus la **capture séparée du
  régime « choix d'activation »** (cf. ci-dessous), et la parité étendue à ce régime.
- `test_deployment_observation_contract.py` — `obs_size` 14615 → **16659** (valeur du test
  vérifiée dans le code le 2026-08-08).
- 🔴 **Quatre défauts trouvés en RELECTURE, tous sur le moteur piloté, aucun attrapé par les
  verrous ci-dessus** — ils sont corrigés et chacun a son cas, prouvé par mutation :
  (1) le marqueur d'activation survivait au **changement de phase** (les pools sont par phase, donc
  « sortir du pool » ne le périmait pas) — 9 des 20 premières activations à pool ≥ 2 se faisaient
  sans choix ; le marqueur porte désormais sa **portée (tour, phase, joueur)** ;
  (2) il survivait à **`reset()`**, et sa portée redevenait valide au tour 1 de l'épisode suivant ;
  (3) la garde portait sur `len(eligible_units)` au lieu de `len(slots)` — une escouade en réserves
  est éligible sans avoir de ligne alliée, d'où une décision à une seule action légale ;
  (4) ✅ **CORRIGÉ LE 2026-08-08 — divergence train/serve fermée** : `active_shooting_unit`
  épinglé à la construction du pool réduisait celui-ci à une escouade et supprimait le choix, ce
  qui ne se produisait qu'en **PvE** (`player_types["2"] == "ai"`). La clé suit désormais
  l'activation au lieu de la précéder — *elle désigne une activation de tir en cours* : les deux
  épinglages « tête du pool » sont supprimés, et `squad_shoot` ne l'écrit pas (l'activation de
  l'agent est atomique, donc une écriture n'aurait aucun lecteur et fuirait sur exception ; le
  front lit `result.unitId`). Elle reste donc absente de l'entraînement comme du chemin agent :
  aucun contrat touché, aucun ré-entraînement. La reprise a mis au jour un
  SECOND défaut, antérieur à `L2` : cette clé n'était jamais libérée sur le chemin de l'agent,
  donc la 2ᵉ activation de tir de l'IA levait `active_shooting_unit X is not in
  shoot_activation_pool` — avalé par `execute_ai_turn`, l'IA ne tirait qu'une escouade par phase
  en PvE. Détail et mesure → [V11_phaseA.md §9 P3-3](V11_phaseA.md#s9).
  ⚠️ **Leçon commune** : le premier cas d'auto-péremption ne faisait que **simuler** la sortie du
  pool, il restait donc vert sur (1). Un verrou qui construit une approximation de la situation ne
  verrouille que l'approximation.
- 🔴 **Ce que la garde anti-vacuité a attrapé, et qu'aucun de ces trois n'aurait vu.** Le masque du
  choix d'activation est EXCLUSIF : la **première** occurrence de `move`/`shoot` est désormais ce
  masque-là, pas celui de la phase. Le fixture de parité, qui capture la première occurrence,
  s'est donc mis à mesurer 5 actions au lieu de 144 — **son énumération restait verte**, et seule
  la garde de largeur (`total_open >= 50`) a signalé l'effondrement, de **166 → 15**. C'est
  exactement le « VERT VACANT » que cette garde existait pour attraper, sur un chantier qu'elle
  n'avait pas anticipé. Les deux régimes sont maintenant capturés séparément.

#### É4 — les bots d'évaluation ne jouent pas ce qu'ils décident : `DefensiveBot` ne charge JAMAIS, et les bots « intelligents » tirent sur le mauvais slot — ✅ CONTRE-VÉRIFIÉ, ✅ CORRIGÉ (non mergé)

[`ai/evaluation_bots.py`](../../../ai/evaluation_bots.py) : après la branche
`shoot`, la branche terminale est `if WAIT_ACTION in valid_actions: return WAIT_ACTION`. Or
`SQUAD_ACTION_WAIT` est posé **INCONDITIONNELLEMENT** dans le masque de la phase de charge
([`engine/phase_handlers/shared_utils.py`](../../../engine/phase_handlers/shared_utils.py)).
Le bot ne déclare donc **jamais** de charge. Poids de ce bot dans le score d'éval du run en cours :
**0.23** (`bot_eval_weights` du profil `x1`).

⚠️ **CORRECTION apportée par la contre-vérification : l'affirmation « ce bot ne combat jamais » est
FAUSSE.** En mêlée, `mask[SQUAD_ACTION_WAIT]` n'est posé que dans la branche `else` — aucune cible
([shared_utils.py](../../../engine/phase_handlers/shared_utils.py)). Quand l'escouade est
dans le pool 12.04 **avec** des cibles, seuls les slots de combat sont ouverts : le bot retombe sur
`valid_actions[0]` et **FRAPPE**. Mais il frappe **le slot d'indice le plus bas**, par accident
d'ordre et non par choix — motif §0bis « un comportement obtenu par effet de bord n'est pas un
comportement décidé ». **Même fragilité chez `GreedyBot`**
([`ai/evaluation_bots.py`](../../../ai/evaluation_bots.py)).

**Conséquence pour la lecture du run 4** : sur **~un quart de la mesure** (0.23), l'adversaire ne
charge pas. Un win-rate flatté de ce côté doit être lu comme tel.

✅ **DÉCISION UTILISATEUR DU 2026-07-29 : CORRIGER APRÈS LE RUN 4** — celui-ci ayant été **arrêté à
13 h 08** ([§0.14](#s0.14)), le chantier a été **ouvert et livré le jour même** (voir plus bas) — et profiter du même chantier
pour **supprimer le choix de cible obtenu par accident d'ordre de tri** — chez `DefensiveBot`
**comme** chez `GreedyBot` ([`ai/evaluation_bots.py`](../../../ai/evaluation_bots.py)) :
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
([`ai/evaluation_bots.py`](../../../ai/evaluation_bots.py)) et
`_best_target_slot_by_threat` ([:697-728](../../../ai/evaluation_bots.py)) indexent
`active_unit["valid_target_pool"]` **comme si c'était un index de slot**. Or le masque ouvre
`SQUAD_ACTION_SHOOT_SLOT_BASE + i`, où `i` indexe le **mapping de slots ennemis** construit par tri
des ids ennemis vivants ([`shared_utils.py`](../../../engine/phase_handlers/shared_utils.py),
[:9663](../../../engine/phase_handlers/shared_utils.py),
[:9698](../../../engine/phase_handlers/shared_utils.py)) — deux espaces d'indices différents.
Le bot vise donc **une autre unité que celle que son propre critère a élue**.

> ⚠️ **Périmé depuis le 2026-07-30 (§0.53, table d'état en tête de document)** : `AggressiveSmartBot` et
> `DefensiveSmartBot` ont été **supprimés**, et les poids ci-dessous ne sont plus ceux de la
> config. Table conservée telle quelle — c'est un constat daté, pas un état courant.

| Bot | Poids (`x1`) | Touché ? |
|---|---|---|
| `AggressiveSmartBot` ([:775](../../../ai/evaluation_bots.py)) | 0.15 | 🔴 **OUI** |
| `AdaptiveBot` ([:972](../../../ai/evaluation_bots.py)) | 0.16 | 🔴 **OUI** |
| `DefensiveSmartBot` ([:874](../../../ai/evaluation_bots.py)) | — | 🔴 **OUI** |
| `RandomBot`, `GreedyBot`, `DefensiveBot`, `ControlBot` | — | ✅ **NON, prouvé** — ils prennent le **premier slot ouvert du masque** (défaut É4 d'origine, autre problème) |
| `TacticalBot` ([:1105](../../../ai/evaluation_bots.py)) | 0 (holdout) | ✅ **NON, prouvé** — il n'expose pas `select_action_with_state` |

⚠️ **La garde `if action in valid_actions` a MASQUÉ le défaut au lieu de le révéler** : elle
empêchait l'action illégale de sortir, donc aucune exception, aucun log — motif §0bis, une garde
qui rattrape silencieusement une erreur d'indice la rend indétectable.

**Racine trouvée au passage — les bots n'ont pas accès à l'unité réellement activée.**
`_find_active_unit_for_bot` ([:666-675](../../../ai/evaluation_bots.py)) **devine** « la
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
[`tests/unit/ai/test_scenario_bank_migration_v11.py`](../../../tests/unit/ai/test_scenario_bank_migration_v11.py).
L'écart est donc documentaire (un inventaire faux), pas une perte de capacité.
✅ **CORRIGÉ le 2026-08-02** : les deux mentions de `V11_tranches.md` (le livrable T4 et la
« réserve T4 close ») portent désormais l'avertissement que le script a été supprimé et que le
balayage vit dans le test.

#### É6 — [T4] `roster_matchup_stats.py` ÉCRIT des scénarios au contrat legacy — ✅ CONFIRMÉ ET CORRIGÉ (non mergé)

⚠️ **La mention « NON CONTRE-VÉRIFIÉ » qui figurait ici est PÉRIMÉE** : le constat a été confirmé et
corrigé par la branche `v11-0.47-eval-tooling-mask`, commit **`8336a226`** (constaté le 2026-07-29 à
13 h 56). Les deux sites qui matérialisent des scénarios émettent désormais `board_ref` +
`terrain_ref` et **aucune clé legacy**, sur le contrat vivant de
[`build_holdout_benchmark.py`](../../../scripts/build_holdout_benchmark.py). Le commit
établit en outre que **rien de ce qui était écrit n'était chargeable** : `objectives-51.json` /
`objectives-01.json` n'existent nulle part, `walls-01.json` non plus, et `deployment_zone: "hammer"`
désigne un fichier absent. Verrou : `tests/unit/scripts/test_roster_matchup_scenario_contract.py`
(**5 tests** sur la branche) — absence des clés legacy, présence de `board_ref`/`terrain_ref`,
**existence réelle** des fichiers désignés par les défauts CLI, et fourniture des objectifs et zones
de déploiement par le terrain. `284d67d8` a ensuite remplacé la lecture **textuelle** du source par
une interrogation du **parseur réel** (`_build_arg_parser()` extrait de `main()`), et `aa04a8d9`
supprime le paramètre `split` mort de `_build_scenario_template`.

Constat d'origine, conservé :
`_build_scenario_template` ([`scripts/roster_matchup_stats.py`](../../../scripts/roster_matchup_stats.py))
émet `deployment_zone`, `wall_ref` et `objectives_ref` — **sans `board_ref` ni `terrain_ref`** —
et ces gabarits sont **matérialisés en fichiers réels**
([:930-954](../../../scripts/roster_matchup_stats.py), plus un second site
[:416-424](../../../scripts/roster_matchup_stats.py)). `objectives_ref` est une clé que le
moteur **rejette** : elle figure dans `LEGACY_KEYS`
([`scripts/migrate_scenario_bank_v11.py`](../../../scripts/migrate_scenario_bank_v11.py)).
Les **trois autres outils** de l'inventaire T4 sont propres — p. ex.
[`scripts/build_holdout_benchmark.py`](../../../scripts/build_holdout_benchmark.py)
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
### 0.48 Inventaire des chantiers qui cassent un contrat + PÉRIMÈTRE du lot de ré-entraînement — 🟠 OUVERT (2026-07-29) ; ✅ le lot `L1`+`L2`+`L6` est LIVRÉ ET MERGÉ (2026-08-07) — reste le `--new`

**Cadre.** [§0.44](#s0.44) a acté la stratégie « **un seul ré-entraînement pour tout le lot** » et
exigeait, avant de lancer ce lot, un **inventaire exhaustif** de ce qui touche l'architecture ou
l'observation. **Cet inventaire est rendu ici** ; §0.44 ne le décrit plus comme « en cours ».

**Les TROIS contrats.** Un chantier est « dans le lot » s'il casse **au moins un** de ces trois
contrats — c'est-à-dire s'il rend un modèle existant inchargeable ou son observation invalide :

1. **ARCHITECTURE de la policy** — toute tête, tout `features_dim`, tout `_split_features` qui
   change ⇒ `load_state_dict` lève dans les workers d'éval `spawn` (leçon §0bis, runs 1 et 2).
2. **OBSERVATION** — `obs_size` ou la **forme des clés** de `squad_obs_shapes()`.
3. **ESPACE D'ACTION** — `macro_intents.TOTAL_ACTION_SIZE` (**1139** depuis `L2` ; 1127 du
   chantier 01 au 2026-08-07, les chantiers 02 à 06 n'utilisant que des dimensions déjà déclarées).

Un chantier qui n'en casse **aucun** se livre **à tout moment** et ne coûte **aucun**
ré-entraînement — c'est le critère de tri, pas l'importance du chantier.

#### Inventaire — chantiers qui CASSENT un contrat (13 identifiés)

| Réf | Chantier | Contrat cassé | Preuve | Ampleur |
|---|---|---|---|---|
| **1** ✅ **LIVRÉ 2026-08-07** | [§0.44](#s0.44) tête pointeur de **déploiement** | **ARCHITECTURE** seule | ✅ Livré comme prévu : `deploy_query_net` jumeau de `choice_query_net`, `deploy_emb` exposé PAR SLOT en queue du vecteur (`deploy_embeddings_slice`, le tronc n'en garde que l'agrégation), routage sur `phase_deployment`. Ni `obs_size` ni `TOTAL_ACTION_SIZE` (**1127**) touchés par ce chantier — vérifié (le 14609 → 14615 du même jour vient du drapeau `declines`, pas de `1`). ⏳ Conception d'origine ci-dessous : `deploy_query_net` serait le jumeau de `choice_query_net` ([pointer_policy.py](../../../ai/pointer_policy.py)) ; il faut **exposer `deploy_emb` hors du tronc**, où il n'entre aujourd'hui que par concaténation ([spatial_extractor.py](../../../ai/spatial_extractor.py), [:494-503](../../../ai/spatial_extractor.py)) ⇒ `features_dim` ([:304-312](../../../ai/spatial_extractor.py)) et `_split_features` changent. `obs_size` **inchangé**. | moyenne |
| **2** ✅ **LIVRÉ 2026-08-07** | **P3-3** choix de l'unité à activer ([V11_phaseA.md](V11_phaseA.md)) | **ESPACE D'ACTION + OBSERVATION + ARCHITECTURE** | ✅ **LIVRÉ — moteur ET réseau.** `ACTIVATE_SLOT_BASE = 1127`, 12 slots ⇒ `TOTAL_ACTION_SIZE` **1127 → 1139** (c'est `2` qui met à jour le verrou d'interface de [§0.47](#s0.47) É3, comme annoncé). `K_ALLY_SLOTS` **8 → 12** et DÉMÉNAGE dans `observation_entities` (module feuille) : l'espace d'action en dérive, donc la constante ne pouvait pas rester dans `observation_builder` sans cycle ⇒ `obs_size` **14615 → 16659** (+2 044, **0 paramètre** : encodeur d'entités partagé). Nouveau `get_ally_slot_mapping`, jumeau de `get_enemy_slot_mapping` — **l'ordre des lignes alliées devient CONTRACTUEL** (D1 côté allié), là où le code affirmait qu'il n'avait « pas de sémantique ». Le blocage annoncé ici (les embeddings alliés AGRÉGÉS, absents de `features_dim`) est **LEVÉ** : `ally_embeddings_slice` les expose PAR SLOT en queue du vecteur — ligne 0 comprise, l'ancre du pool étant un candidat — et `activate_query_net`, jumelle de `deploy_query_net` livrée par `1`, les score. Livré en DEUX temps : la moitié moteur d'abord, avec 12 colonnes DENSES d'`action_net` faute de pouvoir toucher `spatial_extractor.py` pendant que `1` le réécrivait ; le pointeur les a remplacées après son merge, `action_net` repassant de 29 à 17 colonnes. | **grosse** |
| **3** | **P3-4** allocation des pertes (+ ordre de déclaration) | **OBSERVATION** au minimum | Nouveau type dans `AGENT_DECISION_TYPE_IDS` → `DECISION_CTX_BIN_SIZE` → `obs_size` ([observation_entities.py](../../../engine/observation_entities.py)), plus ouverture du registre continu `DECISION_OPTION_CONT_FIELDS` ([:289-292](../../../engine/observation_entities.py)). | grosse |
| **4** | **P3-5** pile-in / consolidation | **OBSERVATION** au minimum | Idem 3, et décision **spatiale** : [V11_phaseA.md](V11_phaseA.md) **interdit** le top-K d'hex. **DÉPEND** de la migration ouverte [`Documentation/Archives/chantiers/pile_in_overrun_par_figurine_2026-08-18.md`](Documentation/Archives/chantiers/pile_in_overrun_par_figurine_2026-08-18.md). | grosse |
| **5** | **P3-6** move-after-shooting + reactive move | **OBSERVATION** au minimum | Les **bits de règle existent déjà** ([observation_entities.py](../../../engine/observation_entities.py)) : c'est la **DÉCISION** qui manque. | moyenne |
| **L6** | **P3-7** FLY / Take to the skies | ✅ **LIVRÉ le 2026-08-07** — AUCUN contrat cassé | Deux candidats **non-entités** ⇒ `CHOICE_0/1`, `TOTAL_ACTION_SIZE` inchangé (**1127**) ; le type `fly_declaration` consomme une **réserve** d'`AGENT_DECISION_TYPE_SLOTS`, donc `obs_size` inchangé (**14609**) — l'arbitrage 2 du socle a rendu ce chantier gratuit en contrat. La **CONSTANTE DE MOTEUR** de [§0.49](#s0.49) point 5 (« déclare systématiquement », -2" y compris en pur désavantage) est **supprimée** : `took_to_the_skies` ne lit plus que la déclaration, pour tous les sièges. | petite |
| **7** | **P3-8a** choix d'arme par l'agent | **OBSERVATION**, + espace d'action selon la voie | `K_WEAPONS_RANGED`/`K_WEAPONS_MELEE` = **10** ([observation_builder.py](../../../engine/observation_builder.py)) dépassent `MAX_DECISION_OPTIONS = 6`. | moyenne à grosse |
| **8** | **P3-8b** split-fire par-figurine | **ESPACE D'ACTION** | Aujourd'hui l'**escouade entière** vise UN slot ([macro_intents.py](../../../engine/macro_intents.py)) ; le par-figurine exige un produit **figurine × arme × slot**, inexprimable dans l'espace actuel. | grosse |
| **9** | **P3-8c** charge multi-cibles (11.04 « one or more ») | **ESPACE D'ACTION** | Un seul `target_slot` de charge aujourd'hui ([macro_intents.py](../../../engine/macro_intents.py)). Le PvP le fait déjà. | moyenne |
| **10** | **P3-8d** placement final de charge | **ESPACE D'ACTION** ou **OBSERVATION** selon paramétrisation | Décision spatiale, même réserve que 4 ([V11_phaseA.md](V11_phaseA.md)). | moyenne |
| **11** | **P3-8e** élargir les 5 stratégies de déploiement | **OBSERVATION** seule | `N_DEPLOY_SLOTS` ([observation_entities.py](../../../engine/observation_entities.py)). `TOTAL_ACTION_SIZE` **NE bouge PAS** : les ids **4-8** sont dans la plage des cellules de move (`MOVE_CELL_BASE = 0`, [macro_intents.py](../../../engine/macro_intents.py)). | petite à moyenne |
| **12** | **P4** observation de support | **OBSERVATION**, **part résiduelle seulement** | Trois des quatre features annoncées **existent déjà** ([observation_entities.py](../../../engine/observation_entities.py), [:129-130](../../../engine/observation_entities.py), [:166](../../../engine/observation_entities.py)). | petite — **ne se livre pas seule** |
| **13** | **Phase B** observation des niveaux / élévation ([V11_tranches.md](V11_tranches.md), [:1508-1519](V11_tranches.md), marquée « **obligatoire** ») | **OBSERVATION** | Nouvelles features par-figurine et par-slot ennemi ⇒ layout, donc `obs_size`. | grosse — **conditionnée** à la vérification du chantier LoS 3D |

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
- Pile-in / Overrun 12.06 par-figurine ([`Documentation/Archives/chantiers/pile_in_overrun_par_figurine_2026-08-18.md`](Documentation/Archives/chantiers/pile_in_overrun_par_figurine_2026-08-18.md)) — fusion du bug BFS↔commit et de l'overrun.
- MCTS-adversaire ([`backlog/MCTS/`](../backlog/MCTS)).
- Outillage / perf / front / replay de [`backlog/`](../backlog) (10x, perf, preview de tir, replay
  par-figurine, tests front, Database, Security).

#### Dépendances — elles commandent l'ordre

- ~~**L11 doit être tranché AVANT d'écrire L1**~~ ✅ **TRANCHÉ le 2026-08-07** : `N_DEPLOY_SLOTS = 8`
  (5 stratégies jouables, 3 slots réservés). `deploy_query_net` se dimensionne donc sur **8**.
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
- ⚠️ **Le verrou d'interface de [§0.47](#s0.47) É3 fige l'espace d'action COURANT (1107 alors,
  1127 depuis le chantier 01)** : écrit
  avant L2 / L8 / L9, il **devra être mis à jour avec le lot**. Ce n'est pas une raison de ne pas
  l'écrire, c'est une **conséquence à assumer**.

#### 🟢 ARBITRAGE UTILISATEUR DU 2026-07-29 (1) — PÉRIMÈTRE DU LOT : **L1 + L2 + L6**, et eux seuls

**« Grouper » ne signifie PAS « tout faire ».** Le lot est un **périmètre choisi**, pas la totalité
de l'inventaire ci-dessus. Motifs :

- **L1** ✅ **LIVRÉ ET MERGÉ le 2026-08-07** (§0.44, `91cc70d1`).
- **L2** ✅ **LIVRÉ ET MERGÉ le 2026-08-07** (`b8be3f8e`) — il portait le **plus gros gain
  stratégique annoncé** : l'unité activée était **toujours** `eligible_units[0]`
  ([V11_phaseA.md](V11_phaseA.md)).
- **L6** ✅ **LIVRÉ ET MERGÉ le 2026-08-07** (`7b4ace51`) — petit, et gratuit en contrat.

⇒ **Le lot est complet ; il ne manque que le `--new` unique** (cf. [§0.67](#s0.67)).

**L3, L4, L5 et L7 à L13 restent HORS du lot**, à **replanifier après sa mesure**.

#### 🟢 ARBITRAGE UTILISATEUR DU 2026-07-29 (2) — RÈGLES FUTURES : RÉSERVER LA PLACE DÈS LE LOT

**Constat vérifié.** `PROFILE_BIN_SIZE = len(WEAPON_RULE_BITS) + len(ANTI_KEYWORDS) + 1`
([observation_weapon_profiles.py](../../../engine/observation_weapon_profiles.py)), et les
drapeaux `rule_*` dérivent de `UNIT_RULE_EFFECT_IDS`
([observation_entities.py](../../../engine/observation_entities.py),
[:167](../../../engine/observation_entities.py),
[:294](../../../engine/observation_entities.py)). Donc **toute règle de jeu rendue vivante ajoute
un bit, change `obs_size`, et impose un ré-entraînement** — ce qui met en **tension directe**
l'objectif « 100 % conforme aux règles » et l'objectif « un seul ré-entraînement ».

**DÉCISION : réserver dès le lot la place des règles pas encore implémentées**, **inactives**
jusqu'à leur implémentation, pour que les ajouter ne coûte **plus** de retrain.

✅ **LIVRÉ le 2026-08-07 (socle, cf. [§0.67](#s0.67))**, et pas sous la forme envisagée ici : la
mesure a écarté « réserver des bits ». Un drapeau de règle d'arme coûte **560 scalaires**
(28 entités × 20 profils), donc réserver douze bits en aurait coûté **6 720** — un tiers de
l'observation d'alors, à porter pour toujours. Le patron d'`obs_id` du chantier 01 a été appliqué
aux règles d'armes à la place : l'observation **maigrit** de 6 160 scalaires et une règle future
coûte 0. Restait vrai et traité au même endroit : les TYPES DE DÉCISION
(`AGENT_DECISION_TYPE_SLOTS = 8`) et les SLOTS DE DÉPLOIEMENT (`L11` : 8 décrits, 5 jouables).
⚠️ Ce qui n'est PAS réservé et ne peut pas l'être à ce prix : les règles d'armes **paramétrées**
(chacune porte une valeur continue par profil, donc une dimension). Une règle paramétrée nouvelle
coûtera encore un `obs_size`.
⏳ Un **inventaire des règles manquantes** (PDF de [`Documentation/40k_rules/`](../../40k_rules)
confrontés au vocabulaire observé) est **en cours de constitution en parallèle** — son contenu
n'est **pas préjugé** ici, aucun chiffre n'en est supposé tant qu'il n'est pas rendu.
**Coût accepté** : quelques bits inutilisés dans l'observation.

<a id="s0.50"></a>
### 0.50 Non-conformité 01.07 — le contrôle d'objectif sous battle-shock — ✅ CORRIGÉ ET MERGÉ (2026-07-29) ; ✅ TRAVAIL DE SUITE CLOS (2026-08-02, revérifié le 2026-08-03)

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

**1. La règle, lue dans les PDF.** [`01 Core concepts.pdf`](../../40k_rules) §01.07 : « *While a unit
is battle-shocked: ▪ The Objective Control (OC) characteristic of all of its models is modified to
'-'* ». [`02 Datasheets.pdf`](../../40k_rules) §02.02 : un OC de `'-'` rend la figurine **incapable de
contrôler**. [`14 Objectives.pdf`](../../40k_rules) §14.02 et son **diagramme p.53** tranchent le cas
explicitement.

**2. La rupture.** `sum_objective_control_oc_multi`
([`engine/game_state.py`](../../../engine/game_state.py)) — **SOURCE UNIQUE**
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
### 0.14 Re-mesure du run — ✅ MESURE OBTENUE le 2026-08-03 (run 200k) ; le RESTE de l'entrée est l'historique périmé du run 4

> ⚠️ **« MESURE OBTENUE » N'EST PAS « MESURE DE RÉFÉRENCE ».** Les deux mots coexistent dans ce
> document et ne désignent pas la même chose : ce run donne des chiffres **exploitables**, mais la
> mesure de RÉFÉRENCE — celle à laquelle les runs suivants se compareront — suppose un **mètre
> gelé**, donc [§0.55](#s0.55) livrée (holdout hors enveloppe, ventilation par roster). Tant que
> `tactical` est l'adversaire le plus facile, ces chiffres mesurent l'agent, pas sa généralisation.
>
> ✅ **LE MÈTRE EST GELÉ DEPUIS LE 2026-08-04** ([§0.55](#s0.55)) : `tactical` porte
> `w_objective 2.0` et l'agent tombe à **0.72** contre lui, au lieu de 0.89. Les chiffres de cette
> entrée restent donc une mesure OBTENUE ; **la première mesure de RÉFÉRENCE sera celle du
> prochain run**, seule comparable aux suivantes.
> 📌 **Ces chiffres valent pour `--resolution 1`, et cette précision n'est pas décorative** :
> `--training-config` ne choisit pas le plateau, et une éval lancée sans le drapeau tourne sur
> `board/44x60x5` et rend `combined 0.6755` / `tactical 0.63`. **Toujours citer la résolution avec
> le chiffre** — c'est ce qui a coûté une journée de mesures à §0.55.
>
> 🟢 **RUN DE 200 000 ÉPISODES — la première mesure exploitable du projet (2026-08-02 → 03).**
> Démarré le **2026-08-02 à 12 h 26**, dernier événement le **2026-08-03 à 02 h 05** (~13 h 30),
> 19 points d'évaluation de 820 k à 12,1 M steps. Modèle retenu :
> `ArmageddonAgent_12345_robust_0.8049.zip` (le snapshot ROBUSTE, md5-identique à
> `model_ArmageddonAgent.zip`).
>
> **Courbes du run** (`tensorboard/200k/x1_long_ArmageddonAgent_2`) :
>
> | scalaire | premier | max | dernier |
> |---|---|---|---|
> | `eval_bots/combined_win_rate` | 0,283 | **0,837** (pt 18/19) | 0,743 |
> | `bot_01` combined / worst | 0,290 / 0,120 | 0,826 / 0,760 | 0,790 / 0,640 |
> | `bot_02` combined / worst | 0,298 / 0,160 | 0,966 / 0,920 | 0,804 / 0,600 |
> | `bot_03` combined / worst | 0,290 / 0,160 | 0,808 / 0,640 | 0,808 / 0,600 |
> | `bot_04` combined / worst | 0,256 / 0,200 | 0,822 / 0,760 | 0,570 / 0,480 |
>
> **Ventilation par adversaire du run** (sortie d'évaluation, 100 parties par bot) : `tactical`
> 0.83, `greedy` 0.77, `defensive` 0.76, `adaptive` 0.75, **`control` 0.71**, `value_trade` 0.65.
>
> ⚠️ **La ventilation par adversaire n'est PAS dans les scalaires TensorBoard** — seuls
> `bot_eval/scenario/<scén>/combined`, `/worst_bot_score` et `eval_bots/combined_win_rate` y sont.
> Elle n'existe que dans la sortie d'évaluation, donc elle n'est ni tracée dans le temps, ni
> croisée par roster. C'est exactement ce que [§0.55](#s0.55) étape 2b demande de publier.
> ✅ **Le croisement l'est depuis le 2026-08-04** : `bot_eval/faction/<faction>/vs_<bot>`
> ([§0.55](#s0.55)). La ventilation par adversaire seule, elle, reste hors TensorBoard.
>
> ✅ **ÉVAL REJOUÉE LE 2026-08-03, APRÈS §0.64/§0.65** (LoS de déploiement alignée puis
> vectorisée), sur le **modèle robuste** :
>
> | | | | |
> |---|---|---|---|
> | `tactical` **0.89** | `defensive` 0.87 | `greedy` 0.84 | `adaptive` 0.83 |
> | `control` **0.82** | `value_trade` **0.74** | **combined 0.8200** | **0 troncature** |
>
> Scénarios : `bot-02` 0.966 / worst 0.920 · `bot-01` 0.808 / 0.720 · `bot-04` 0.756 / 0.720 ·
> `bot-03` **0.750 / 0.520**.
>
> 🔴 **DEUX LECTURES À NE PAS CONFONDRE, et c'est le piège de cette entrée.**
> 1. **0,743 → 0,820 n'est PAS l'effet de §0.64.** Le premier est le DERNIER point d'éval du run,
>    le second est le snapshot ROBUSTE (score propre 0.8049). L'écart mesure best-contre-final.
>    Isoler §0.64 demanderait la même éval, même modèle, sur le moteur d'avant (parent de
>    `d9d18622`) — non fait.
> 2. **Ce que l'éval établit, elle, est solide** : le modèle entraîné AVANT §0.64 se charge et
>    joue à 0.82 sur `main` d'après §0.64/§0.65. La LoS alignée ne casse pas le modèle existant.
>    ⚠️ **Le NIVEAU 0.82 n'est pas reproductible** (cf. la réserve en tête d'entrée) ; ce qui reste
>    établi est le fait qualitatif — le modèle se charge et joue sans régression fonctionnelle.
>
> 📌 **Conséquences.** (a) Le seuil `model_gating_min_vs_control: 0.50` est **franchi** —
> `vs_control` 0.71 en fin de run, 0.82 sur le robuste ; le **0.04 du run 4 ci-dessous est
> périmé**. (b) `tactical`, le HOLDOUT, était l'adversaire **le plus facile** des six (0.89) et
> `value_trade` le plus dur (0.74) : [§0.55](#s0.55) n'est pas de la cosmétique, c'est ce qui
> décide si le prochain chiffre veut dire quelque chose. ✅ **Traité le 2026-08-04** : le holdout
> re-profilé n'est plus le plus facile — `vs_tactical` passe de 0.89 à **0.72**, cf.
> [§0.55](#s0.55). (c) L'écart entre scénarios est large
> (0.750 à 0.966) : la moyenne cache un facteur roster, à ventiler ([§0.55](#s0.55) étape 2b).

<a id="s0.14hist"></a>
### 0.14hist Historique — run 4, ⏳ PÉRIMÉ au 2026-08-02 (des runs POSTÉRIEURS ont tourné, cf. tableau du §0) — historique : run 4 `--new` lancé le 2026-07-29 à 12 h 03, **ARRÊTÉ à 13 h 08** (état et chronologie dans le tableau du §0, entrée périssable — ne pas les dupliquer ici)

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
> [`Documentation/Archives/chantiers/V11_move_pool_optimization.md`](../../Archives/chantiers/V11_move_pool_optimization.md) (**clos**),
> suite vivante [`perf_move_pool.md`](../../Reference/moteur/perf_move_pool.md).
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

## 0bis. Pièges et leçons de méthode → Document de méthode autonome

> **Extrait le 2026-08-27 (refonte P3)** dans
> [`Documentation/Reference/training/V11_method_lessons.md`](../../Reference/training/V11_method_lessons.md).
> Ce document est la **copie canonique** des leçons de méthode — y faire les mises à jour,
> pas ici.

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
> (plan [`V11_refactor_plan.md`](../../Archives/chantiers/V11_refactor_plan.md), étapes 1→3). Ce fichier ne conserve que
> l'**index d'état** : §0 (ouvert et actionnable), §0bis (pièges canoniques), §0ter (non-travaux)
> et §0hist (historique résolu, intégral). **Contenu déplacé tel quel, aucune réécriture.**

| Document | Contenu | État |
|---|---|---|
| [`V11_tranches.md`](V11_tranches.md) | **[§1](V11_tranches.md#s1) → [§8](V11_tranches.md#s8)** — objectif, l'ANCRE, état des lieux, ruptures R1→R8, décisions de design, tranches T1→T7 + Phase B, critères d'acceptation, smoke tests, tests de non-régression | **vivant** (T6-h/T6-g ouverts, cf. [§0.0](#s0.0)) |
| [`V11_phaseA.md`](V11_phaseA.md) | **[§9](V11_phaseA.md#s9)** — Phase A' : parité de résolution des règles (P1) puis mécanisme de décision agent (P2→P5) | **vivant** |
| [`V11_eval_strategy.md`](V11_eval_strategy.md) | **[§10](V11_eval_strategy.md#s10)** — stratégie d'entraînement et d'évaluation, rosters, holdout, win-rate par roster | **vivant** |
| [`Documentation/Reference/training/V11_entity_encoder_pointer.md`](../../Reference/training/V11_entity_encoder_pointer.md) | Encodeur d'entités partagé + tête pointeur, cardinalités de l'observation, les 7 trous qu'il ferme | **clos** (T-A→T-H livrées) — **archivé le 2026-08-08** ; ⚠️ ses chiffres de dimensionnement sont datés, l'`obs_size` courant se lit ici en §0 |
| [`Documentation/Archives/chantiers/observation_deploiement.md`](../../Archives/chantiers/observation_deploiement.md) | Observation de la phase de déploiement — les 5 défauts et leurs correctifs (extrait de `V11_audit_observation.md` §11) | **clos** (2026-07-29, §0.40 — archive) |
| [`Replay.md`](../Replay.md) | Replay : pipeline & contrat du `step.log`, registre des chantiers replay | **vivant** (outillage) |
| [`perf_move_pool.md`](../../Reference/moteur/perf_move_pool.md) | Perf du noyau `_build_multi_hex_vectorized` : périmètre, filet de validation, livré (L1 + L_bbox), impasses mesurées | **clos** (décision (B) STOP, 2026-07-21) |
| [`Documentation/Archives/chantiers/V11_move_pool_optimization.md`](../../Archives/chantiers/V11_move_pool_optimization.md) | Cadrage d'origine du chantier move pool (§0.22) | **clos** — archive, ne plus s'y fier pour l'état du code |


## 0hist. Historique résolu → Archive

> **Déplacé le 2026-08-27 (refonte P3)** dans
> [`Documentation/Archives/chantiers/V11_agent_rework_history.md`](../../Archives/chantiers/V11_agent_rework_history.md).
> Les ancres `### 0.x` sont préservées dans l'archive pour ne pas casser les références.

