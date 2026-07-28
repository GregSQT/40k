# V11 — Rétablissement de l'entraînement de l'agent (agent rework)

Date d'audit : 2026-07-14. Tous les faits ci-dessous ont été vérifiés dans le code actuel
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
## 0. ÉTAT AU 2026-07-28 — À LIRE EN PREMIER

> **Cette section ne contient QUE ce qui est ouvert et actionnable.**
> - Ce qui est résolu est en **§0hist — Historique résolu**, **en fin de document, après les [Pointeurs](#pointeurs)** :
>   entrées intégrales, ancres `### 0.x` inchangées, aucune preuve condensée.
> - Les avertissements et leçons de méthode durables sont regroupés en **§0bis — Pièges et
>   leçons de méthode**, qui en est la **copie canonique**.
>
> **Conventions de tenue de ce document — les respecter en le mettant à jour :**
> - **Un numéro d'entrée est attribué à vie.** Une entrée résolue descend en §0hist en gardant
>   son numéro ; un numéro n'est jamais réattribué. Prochaine entrée libre : `0.44` (`0.18`–`0.21` le 2026-07-20, `0.22` le 2026-07-21, `0.23`–`0.28` le 2026-07-22, `0.29` le 2026-07-22, `0.30` le 2026-07-26, `0.31` le 2026-07-27, `0.32`–`0.43` le 2026-07-28).
> - **Un contenu d'état vit à UN seul endroit.** Une entrée à moitié résolue est **scindée** :
>   la part résolue reste sous son numéro en §0hist, la part ouverte prend un numéro neuf ici,
>   et les deux se renvoient l'une à l'autre. Seuls les avertissements et leçons sont dupliqués
>   (§0bis fait foi).
> - Une entrée **périssable** (état de commit, mesure) porte sa date et l'ordre de la
>   reconfronter au réel avant usage.

### Tableau d'état — ce qui est ouvert

**Épuration du 2026-07-28** : les entrées **§0.22, §0.27, §0.28, §0.31, §0.32, §0.34, §0.35, §0.36,
§0.37** ont été descendues en **§0hist** (intégrales, ancres inchangées) — elles étaient closes mais
occupaient encore la section « ouvert ». Ne restent ici que les **cinq** chantiers réellement
actionnables (§0.39, ouverte puis close le même jour, est descendue en §0hist avec les autres ;
§0.40 ajoutée le 2026-07-28, contenu externalisé dès l'ouverture).

| # | Entrée | Statut | Ordre | Prochaine action concrète |
|---|---|---|---|---|
| **§0.14** | Re-mesure du run — win-rate par matchup | 🔴 **RUN 3 ARRÊTÉ** par l'utilisateur (2026-07-28, fin de nuit) pour livrer §0.40 (points 1, 2, 4 puis 5) — il avait été lancé ~23 h 20 depuis `main` (P3-2 inclus : `obs_size` **20768**, action space **1107**, rampe de déploiement **0.0 → 0.8**) | **1** | **RUN 4 à lancer** depuis la tête de `main` (§0.40 points 1, 2, 4 et 5 inclus — vérifier `git log` plutôt que de se fier à un hash écrit ici). `obs_size` **inchangé** (20768), donc aucun contrat d'archi cassé — mais le run 3 a entraîné le déploiement sur l'observation fausse, ses mesures de déploiement ne valent rien. ⛔ **Dès qu'un run tourne, WORKING TREE GELÉ** : aucun commit de code/config, aucun checkout, aucune édition — les doc `.md` sont sûres (jamais ré-importées). Historique : 🔴 **RUN 1 mort à 20 h 20** (§0.41+§0.42 mergés pendant lui, `obs_size` changé). 🔴 **RUN 2 mort à ~21 h 45** à la 1ʳᵉ éval (600 épisodes `error` en 7,1 s) : le `git checkout` de 21 h 39 a réécrit le code sur le disque, les workers d'éval `spawn` ont reconstruit l'architecture P3-2 (`action_net [17,320]` + `charge_query_net`) pour charger un snapshot P2 (`[18,320]`, sans) → `load_state_dict` lève → `BrokenProcessPool`. Diagnostic reproduit, leçon durcie en §0bis. Points d'observation : la 1ʳᵉ éval (marqueur 2000) doit **se terminer** (§0.27) ; aucun modèle ne peut être sauvé avant 10 000 (`save_best_min_episodes`) ; le livrable est le win-rate par matchup de l'éval finale. Checkpoints 720 k et 80 k : contrats périmés, inutilisables. |
| **[§9](V11_phaseA.md#s9)** | Phase A' — **P2 + P3 points 0/1/2 livrés**, **P3 tranches 3→8** (décisions restantes) | 🟢 **P2 + P3-0 + P3-1 + P3-2 TOUS MERGÉS sur `main`** (fast-forward du 2026-07-28 23 h ; `main` = `acd63b66`) | **2** | **P3-1 (cible de mêlée)** → §0.41 : une décision dont les candidats sont des ENTITÉS déjà observées se paramètre en **dimension d'action + tête pointeur**, pas en `CHOICE_k`. **P2 (mécanisme générique) + P3-0 (rule-choice)** → §0.42 : `CHOICE_0..5` pour les candidats qui ne sont **pas** des entités observées ; `raw_action_int % len(options)` n'existe plus. **P3-2 (cible de charge)** → §0.43 : patron P3-1, `TOTAL_ACTION_SIZE` **1107**, `obs_size` **20768**. Reste **P3-3→8** (unité à activer, allocation des pertes, pile-in/conso, move-after-shooting, FLY, optionnels), **P4**, **P5**. ⚠️ Aucune de ces 4 livraisons n'est MESURÉE : le run 3 est le premier à les entraîner. ⚠️ P3-0 est **inerte dans le training** (aucun roster SM/Ork ne porte de rule choice). ⛔ Toute tranche suivante se livre dans un **`git worktree` séparé** tant que le run tourne. |
| **§0.33** | Rollout buffer 46,9 Go pour 39 Go de RAM | 🟠 **CONDITIONNEL** — ne bloque que les profils à 48 envs | **4** (avant tout run 48 envs) | Vérifié 2026-07-28 dans la config : `x1`/`x5_new`/`x5_debug` = **8 envs** (passent) ; `x5_append`/`x1_debug` = **48 envs** (échouent à l'allocation). Ne pas lancer ces deux-là sans rouvrir l'entrée. |
| **§0.29** | Scénario SM vs Orks fixed/active + scheduler | 🟢 **USAGE CONFIGURÉ** le 2026-07-28 (`active_ratio_end` 0.0 → **0.8**, commit `acd63b66`) — et c'est le réglage CORRECT, cf. l'asymétrie ci-dessous | 5 | Le run 3 joue une part croissante d'épisodes en `active` (0 % au début → 80 % à la fin, `p_active = start + (end−start)·progress`, [w40k_core.py:934](../../engine/w40k_core.py#L934)). 🔴 **ASYMÉTRIE VÉRIFIÉE le 2026-07-28 23 h 30 — la rampe ne s'applique QU'À L'ENTRAÎNEMENT, jamais à l'éval.** `deployment_mode_schedule.training_only: true` + `_is_training_scenario_context()` qui exige `/scenarios/training/` dans le chemin ([w40k_core.py:693](../../engine/w40k_core.py#L693)) ⇒ les scénarios d'éval (`/scenarios/holdout_regular/`, tous en `deployment_type: "active"`) **jouent TOUJOURS une phase de déploiement**, quelle que soit la rampe. **Donc `active_ratio_end: 0.0` créait un décalage entraînement/éval** : agent entraîné 100 % en placement figé, puis noté sur des parties à déployer. La rampe à 0.8 **aligne** les deux — la remettre à 0 dégraderait la mesure. ✅ **Réserve levée les 2026-07-28 / 07-29** : les défauts 1, 2, 4 et 5 de l'observation du déploiement sont corrigés (§0.40, `obs_size` inchangé). Il reste le seul point 3 (les hexes candidats ne sont pas décrits), donc un plafond résiduel mais bien plus bas. ⚠️ Le run 3 lancé le 2026-07-28 à 23 h 20 est ANTÉRIEUR à ces correctifs : il a entraîné le déploiement sur une observation fausse. |
| **§0.40** | Observation de la phase de déploiement — **points 1, 2, 4 et 5 corrigés**, point 3 ouvert | 🟠 **PARTIELLEMENT OUVERT** — chantier externe | 6 | **Livrés** : point 1 (`0e0551e8`, obs = unité du masque), point 2 (`2893bbcb`, grille ancrée sur la zone), point 4 (le **vecteur** mesurait aussi depuis `(-1,-1)` — l'ordre des distances aux objectifs en était **inversé**), point 5 (une unité pas encore mise en place se déclarait **engagée au contact** — contraire à 03.04). `obs_size` **inchangé** (20768) sur les quatre, donc aucun modèle invalidé. Reste le **point 3** (décrire les 5 hexes-stratégies), qui change `obs_size` → run `--new`. Détail → §0.40. |
| **§0.42** | P2 « décision agent » | ✅ **MERGÉ** sur `main` — reste la MESURE (run 3 en cours) | — | Détail → §0.42. |
| **§0.43** | P3-2 « cible de charge » | ✅ **MERGÉ** sur `main` le 2026-07-28 23 h (fast-forward, 8 commits, 0 conflit) — reste la MESURE (run 3 en cours) | — | La branche `v11-p3-2-charge-target` est devenue identique à `main` (supprimable). Détail → §0.43. |
| **§0.19** | Revérifier T1→T5 et la section 9 ligne à ligne | ⏳ **PARTIEL** | continu | T1 soldé (§0.19.1→§0.19.3) ; section 9 auditée le 2026-07-24 (→ [§9.0](V11_phaseA.md#s9.0)). T2→T5 **jamais revérifiés** : ne pas s'appuyer sur leurs ✅ sans relecture. ⚠️ Sa **section** est restée en §0hist (elle y était déjà avant l'épuration) alors que sa part T2→T5 est ouverte — laissée en place plutôt que scindée, pour ne pas casser ses sous-ancres `§0.19.1`→`§0.19.3`. |

🟢 **TRANCHÉ le 2026-07-28 soir (arbitrage utilisateur) : `bot_eval_freq = 2000` ASSUMÉ**, pour
la **granularité des courbes de métriques**. La décision « 4000 » de §0.14 est **annulée** ;
HEAD (`x1: 2000`, commité `ea18e9ae`) et décision sont alignés — plus rien à committer.
Conséquence acceptée en connaissance de cause : sur 30 000 épisodes, les 4 évals des marqueurs
< `save_best_min_episodes` (10 000) ne peuvent sauvegarder aucun modèle — coût = du temps d'éval
« pour les courbes », aucune perte de modèle.

| Clé (profil `x1`) | Ancienne décision §0.14 (annulée) | HEAD = décision actuelle |
|---|---|---|
| `bot_eval_freq` | ~~4000~~ | **2000** |

**C'était le SEUL écart qui contredisait une décision.** Les autres changements du même commit
vont dans le bon sens : les `justification` d'`obs_size` sont mises à jour de « grille 32x32x7 » vers
« 32x32x9 » (**corrige** un texte périmé par §0.32 T-K/T-L), et les clés `perception_radius` /
`max_nearby_units` / `max_valid_targets` ont été **retirées des 5 profils** le 2026-07-28 — elles
n'alimentaient que le pipeline mono-figurine supprimé le même jour, plus aucun code ne les lit
(vérifié par grep sur `engine/`, `services/`, `ai/`, `config_loader.py`). Aucun impact sur le run.
Le run §0.14 peut donc être lancé tel quel, sans retouche de config.

⚠️ **Avant de vous appuyer sur une affirmation de ce document, lire §0bis** — en particulier la
réserve de méthode sur le document lui-même (T2→T5 et section 9 n'ont **pas** été revérifiés
ligne à ligne) et la règle de périmètre `ArmageddonAgent`.

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

### 0.40 Observation du déploiement — points 1, 2, 4 et 5 corrigés, point 3 ouvert — 🟠 (2026-07-29)

**Le contenu d'état vit dans [`observation_deploiement.md`](observation_deploiement.md)** (extrait
de l'audit archivé `Implémenté/V11_audit_observation.md` §11 le 2026-07-28, constats re-vérifiés
dans le code le même jour) — cette entrée n'est que le **pointeur d'orchestration**, conformément à
la règle « un contenu d'état vit à UN seul endroit ».

**Livré le 2026-07-28** (2 commits, tests de contrat rouges sous mutation) :
- **point 1 ✅** (`0e0551e8`) — l'obs de déploiement décrivait `next(iter(units_cache))` et non
  l'unité du masque. Source unique désormais : `ActionDecoder.get_deployment_active_unit`, qui
  **lève** sur pool vide au lieu de rendre une obs nulle.
- **point 2 ✅** (`2893bbcb`) — la grille égocentrique était centrée sur la sentinelle `(-1,-1)`,
  donc sur une autre région du plateau (0 % de la zone du joueur 1 visible). Elle est ancrée sur la
  **zone de déploiement** lue dans `deployment_state["deployment_pools"]`, géométrie
  `engine/spatial_grid` **inchangée** (seul l'ancrage bouge). 96 %/78 % de la zone visible après.

**Livré aussi — point 5 ✅** (2026-07-29), trouvé en re-vérifiant le point 4. Le point 4 réparait ce
qui est mesuré **depuis** l'escouade ; restaient les features qui affirment une **relation** à
l'ennemi. Une escouade pas encore mise en place se déclarait `engaged = 1`, `n_in_enemy_ez = 6`,
`n_fight_eligible = 6`, `n_models_engaging = 6` et `los_can_see = 1` sur les 6 slots ennemis —
toutes les unités non posées partagent la sentinelle `(-1,-1)`, donc leurs empreintes se
recouvrent. **C'est contraire à la règle 03.04** (`03 Moving.pdf`) : « A model's engagement range is
the area **of the battlefield** within 2" horizontally and 5" vertically of it » — une unité hors
table n'a pas d'engagement range. Filtre chez l'appelant, en un point (`on_battlefield`, coût mesuré
1,9 µs = 0,08 % d'une observation) ; la primitive moteur n'est pas touchée, elle recevait des
empreintes fantômes. `coherent` n'est délibérément PAS neutralisé (03.03 : « **if that unit is on
the battlefield**, it is in coherency » — et 0 dirait « escouade éparpillée », un mensonge pire que
le silence).

**Reste ouvert — point 3 seul** : les 5 slots sont 5 **stratégies** évaluées sur tous les hexes
valides, et l'obs n'en décrit aucun ; le cache de scoring du décodeur calcule déjà tout
(`los_exposure_by_hex`, centres d'objectifs, …). Extension de contrat d'obs → `obs_size` change →
**run `--new`**.

**Livré aussi — point 4 ✅** (2026-07-29), trouvé en vérifiant le correctif du point 2 et identifié
nulle part ailleurs : le **vecteur** mesurait lui aussi depuis la sentinelle `(-1,-1)` (son origine
est `_hex_center(centroid_col, centroid_row)`, et le centroïde d'une escouade non posée vaut
`(-1,-1)`). L'agent voyait l'objectif 0 à **38,3** — le plus proche — alors qu'il est à **178,9** de
sa zone, et ne voyait pas l'objectif 4 à **11,3** : l'**ordre des objectifs était inversé**, et les
trois actions de zone s'appuient sur ces nombres. L'origine d'une escouade non posée est désormais
celle de la grille (`squad_grid_anchor`), ce qui **rétablit** l'invariant §0.32 T-I « un seul repère
pour tout ce que l'obs exprime *depuis moi* ». Choix tranché : une entité pas encore posée n'a
**aucune** position relative (`col_rel`/`row_rel`, `self_models_cont`, `edge_distance` restent nuls,
le bit `deploy_not_on_board` porte l'information) — sans quoi déplacer l'origine les aurait toutes
empilées à une distance absurde au nord-ouest. Effet **borné au déploiement** (les réserves 20 ne
sont pas modélisées), `obs_size` **inchangé**.

⚠️ **Conséquence de mesure** : `obs_size` reste **20768** (verrouillé par test), donc aucun modèle
n'est invalidé — mais le CONTENU de l'obs de déploiement change. Un agent entraîné avant ces deux
commits a appris le déploiement sur une observation fausse : ne pas comparer sa qualité de
déploiement à celle d'un agent entraîné après.

<a id="s0.33"></a>
### 0.33 Rollout buffer 46,9 Go pour 39 Go de RAM — 🟠 CONDITIONNEL : bloque les profils à 48 envs, PAS le run à lancer (2026-07-28)

> ⚠️ **Titre corrigé le 2026-07-28** : « BLOQUANT le run » contredisait le corps de l'entrée, qui
> établit que `x1`, `x5_new` et `x5_debug` (8 envs, 7,8 Go) passent. Vérifié dans la config le
> 2026-07-28 : seuls `x5_append` et `x1_debug` portent `n_envs: 48`.

**Origine.** Point soulevé — sans être chiffré — par l'agent de la tranche T-K/T-L : « la spec
§8.3 de `move_action_space_spatial_rework.md` dimensionne le rollout buffer sur la grille, mais `obs_size` y pèse bien plus lourd depuis
§0.30/§0.31 ». Chiffré ici, sur la config réelle.

**Mesure (2026-07-28).** `DictRolloutBuffer` stocke **toutes** les clés d'observation, vecteur
compris, et il est alloué **d'un bloc au premier `learn()`** — pas progressivement.

| | floats / transition | |
|---|---|---|
| vecteur (`obs_size`) | 20 626 | **le poste dominant depuis §0.30/§0.31** |
| grille (9 × 32 × 32) | 9 216 | 7 168 avant §0.32 |
| **total** | **29 842** | soit **116,6 Ko** par transition en float32 |

| Profil | `n_envs × n_steps` | Transitions | Buffer |
|---|---|---|---|
| `x1`, `x5_new`, `x5_debug` | 8 × 8 192 | 65 536 | **7,8 Go** — passe |
| `x5_append`, `x1_debug` | 48 × 8 192 | 393 216 | **46,9 Go** — ne passe pas |

Machine : **39 Go physiques, 29 Go disponibles**. Les profils à 48 envs échouent à l'allocation,
avant le premier pas — ce n'est pas une lenteur, c'est un `MemoryError` immédiat.

⚠️ **Deux pièges de lecture à ne pas répéter.**
1. Le « 14,49 Go, sous la limite de 19,33 Go » de
   [`move_action_space_spatial_rework.md`](A_faire/move_action_space_spatial_rework.md) §8.3 ne
   compte **que la grille**. Il était juste quand l'obs vectorielle faisait 108 floats ; il est
   périmé depuis §0.30, pour une raison qui n'est pas celle de §0.32.
2. La ligne §0.14 annonce « run `x5_new`, 48 envs » alors que le profil `x5_new` porte
   `n_envs=8`. **Vérifier le profil ET les overrides CLI réellement lancés** avant de conclure
   quoi que ce soit d'un OOM ou de son absence.

**ARBITRAGE DU 2026-07-28 : aucun changement.** La commande réellement lancée porte
`--training-config x1` ⇒ **8 envs, 7,8 Go**, dans les 29 Go disponibles. §0.33 ne bloque **pas**
ce run. Il ne se déclenche que sur `x5_append` et `x1_debug`.
**MAJ 2026-07-28 soir (utilisateur)** : re-test effectué, **8 envs mesuré MEILLEUR** que 48 sur
cette machine — le régime 8 envs n'est pas un pis-aller, c'est le choix retenu. Un run 48 envs
reste conditionné au re-tuning décrit ci-dessous.

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

**Le vrai enseignement de §0.33.** Le régime validé de CoreAgent — `48 × 16 384` = 786 432
transitions — demanderait **93,9 Go** avec l'observation actuelle. **Il est devenu structurellement
inatteignable.** Sous 29 Go, le plafond à 48 envs est `n_steps ≈ 2048` (11,7 Go) à 3072 (17,6 Go),
soit **5 à 8× sous l'optimum mesuré**. Autrement dit : tout run à 48 envs sortira du régime validé,
et son hyperparamétrage devra être **re-tuné**, pas hérité. Ce n'est pas un réglage à trancher au
jugé — c'est un screening à refaire, du type de celui de
[`TUNING_NUIT.md`](../../config/agents/CoreAgent/TUNING_NUIT.md), quand le pipeline sera stable.

**Leviers, si un run à 48 envs devient nécessaire** (aucun n'est gratuit — tous déplacent la
baseline) : baisser `n_envs` · baisser `n_steps` en sachant qu'on quitte l'optimum mesuré ·
stocker la grille en `uint8` — qui ne suffit pas seul : elle ne pèse que 31 % de la transition,
donc 46,9 → **36,1 Go**, encore au-dessus des 29 Go disponibles.

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
   `episode_number/(total_episodes−1)`, Bernoulli(p) → `active`/`fixed`. Dans `reset()`, impose un
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
  règle moteur (03.03, `game_config` : `squad_min_neighbors`=1, `cohesion_distance_mode`="euclidean"
  bord-à-bord 2", étalement 9") n'exige qu'**≥1 voisin** ; le générateur vise ≥2 centre-à-centre =
  borne conservatrice. **L'oracle est la fonction moteur `validate_squad_coherency`** — c'est ELLE
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


<a id="s0.14"></a>
### 0.14 Re-mesure du run — 🟠 OUVERT : run `--new` À LANCER, aucun prérequis technique restant (màj 2026-07-28)

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
--new --training-config x5_new` (10k ép., 48 envs, `bot_eval_final=100`), lancée après le
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

Les 6 fichiers qui tenaient `_attack_sequence_rng` en vie portaient ~159 assertions vertes. En les
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
⚠️ `x5_debug` = **1000 épisodes** (~2h50 à 8 envs), pas un run de quelques minutes malgré son nom.

⚠️ **Ce que `x5_debug` ne produit PAS**, à cause de ses `callback_params` :
`save_best_min_episodes = 10000` et `checkpoint_save_freq = 10000` sont **supérieurs** à ses
1000 épisodes → **ni « best model » ni checkpoint** ne sont jamais écrits. `model_gating_enabled`
est `False` (le `Gate 🧱` de la barre de progression est purement décoratif) et `bot_eval_final`
vaut **1** épisode par bot — contre 60 pour le run de §0.7. C'est un run de **validation de
pipeline**, pas de mesure : il ne peut pas servir le critère [§10.6](V11_eval_strategy.md#s10.6).

**Tout run `x5_debug` ÉCRASE le modèle canonique (§0.0)**

- ⚠️ **Le modèle en place a été ÉCRASÉ par ce run** (`model_ArmageddonAgent.zip`, 2026-07-20
  02:14 — autorisation utilisateur explicite). C'est donc un modèle **de debug, 100 épisodes
  `--new`**, sans valeur de jeu : `save_best_robust: false` fait que
  [train.py:3548](../../ai/train.py#L3548) écrit le modèle final **inconditionnellement** en fin
  de run. Le modèle précédent (19/07 04:25, entraîné AVANT les `VALUE` Munitorum, avec la
  `WarTrakk` à 175) reste disponible dans
  `ai/models/_backup_pre_munitorum_20260719_232816/` — **vérifié intact après le run**.
  ⚠️ Tout run `x5_debug` ultérieur écrasera à nouveau le modèle canonique : sauvegarder avant
  si le modèle en place compte.

**`config/users.db` réapparaît modifié après chaque run (§0.0, dette 5)**

⚠️ `config/users.db` **réapparaît modifié** après chaque run d'entraînement — fichier
**protégé** (CLAUDE.md), ne JAMAIS l'inclure dans un commit.

**`bot_eval_scenario_pool` placé au mauvais niveau est silencieusement ignoré (§0.13)**

⚠️ **Piège latent voisin, découvert au passage.** Dans
`ArmageddonAgent_training_config.json`, `bot_eval_scenario_pool` est placé à la **racine** de
`x5_debug`, alors que `_resolve_callback_value` ([train.py:3273](../../ai/train.py#L3273)) le
cherche dans **`callback_params`** puis retombe sur `config/agents/_training_common.json`.
La clé racine est donc **ignorée**. Sans effet aujourd'hui (les deux valent `holdout`), mais
toute surcharge par agent placée à la racine serait **silencieusement sans effet**.

**`agent_roster_seed` neutralise le tirage de roster sans le moindre message (§0.10)**

⚠️ **Piège latent voisin — `agent_roster_seed`.** Cette clé de scénario est passée en
`random_seed` au tirage du roster AGENT ([game_state.py:1056](../../engine/game_state.py#L1056)),
et le RNG est reconstruit à chaque appel (`random.Random(seed)`,
[:1142](../../engine/game_state.py#L1142)). Si elle est renseignée, **le roster agent devient
identique à tous les épisodes** — le tirage est neutralisé sans le moindre message. Voulu pour les
scénarios holdout `bot-01..04` (qui la portent, pour la reproductibilité), mais ce serait un piège
silencieux dans un scénario d'entraînement. `scenario_training_armageddon.json` ne la porte pas
(`None`) : vérifié. **À contrôler avant de conclure quoi que ce soit sur une distribution de
matchups.**

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
(pondération de menace [reward_calculator.py:1442](../../engine/reward_calculator.py#L1442),
différentiel d'armée [observation_builder.py:367](../../engine/observation_builder.py#L367)) : cet
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
(`compute_candidate_footprint` — « Multi-hex footprints are only computed on Board ×10 ») : deux
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
| 7 | [§2](V11_tranches.md#s2) « État des lieux vérifié » | « Tous les imports du pipeline passent (`ai.train`, `ai.env_wrappers`, **`ai.multi_agent_trainer`**, …) » | `ai/multi_agent_trainer.py` **n'existe plus** (supprimé en §0.8, vérifié absent du disque le 2026-07-20). |
| 8 | §0.17 (par construction) | l'état de commit | Périmé dès le prochain `git commit` — l'entrée porte elle-même l'ordre de la reconfronter à `git status`. |
| 10 | §0.18, note annexe | « après ce crash le process … s'est terminé avec un **code de sortie 0** » | ❌ **FAUSSE, tranchée le 2026-07-20 — voir §0.20.** Le handler `return 1`, `sys.exit` propage, et l'exécution confirme `EXIT=1`. Cause probable : un pipe (`| tee`) côté shell lors de la mesure. Enseignement : une note **« hors périmètre »** échappe à la relecture *parce qu'*elle est marquée annexe. |
| 11-13 | [§6](V11_tranches.md#s6) (T2, T4), [§8.2](V11_tranches.md#s8.2) | layout d'actions « 41 », « 61 scénarios », `test_agent_interface_contract.py` | ➜ **détaillées en §0.19.1** (audit du 2026-07-20). Signalées, NON corrigées. |
| 9 | §0.14 (rédigée puis **corrigée le même jour**) | « Non-régression §0.11 ✅ **VALIDÉE EN BOUT-EN-BOUT** » | ❌ **FAUSSE, retirée le 2026-07-20** — cf. §0.18 : le run suivant a crashé sur ce même message. Cas d'école : l'affirmation a été produite **par l'auteur du run lui-même**, le jour même, à partir d'un unique run vert. Le motif n°1 de ce document ne vient pas que du passé. |

---

## 0ter. Notes post-implémentation — décisions assumées, non-travaux

> Choses **tranchées et closes** qui ne sont ni des bugs ni des dettes : des décisions de
> périmètre que l'utilisateur assume. À ne pas rouvrir comme des réserves.

- **§0.16(b) — `DefensiveSmartBot` reste hors éval (status quo, 2026-07-21).** Retiré à l'origine
  parce qu'il **sous-performait**. Conséquence acceptée : son unique appelant
  `_best_target_slot_by_threat` (7ᵉ site porté) n'est validé que par un **test unitaire**, jamais
  en éval runtime. Le réintroduire pour la seule couverture fausserait la composition d'éval
  (`combined`, poids) sans bénéfice. **Ne pas re-signaler comme un trou de couverture.**
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
| [`observation_deploiement.md`](observation_deploiement.md) | Observation de la phase de déploiement — déficiente (extrait de `V11_audit_observation.md` §11) | **vivant** |
| [`Replay.md`](Replay.md) | Replay : pipeline & contrat du `step.log`, registre des chantiers replay | **vivant** (outillage) |
| [`V11_move_build_acceleration.md`](V11_move_build_acceleration.md) | Perf du noyau `_build_multi_hex_vectorized` : périmètre, filet de validation, livré (L1 + L_bbox), impasses mesurées | **clos** (décision (B) STOP, 2026-07-21) |
| [`Implémenté/V11_move_pool_optimization.md`](Implémenté/V11_move_pool_optimization.md) | Cadrage d'origine du chantier move pool (§0.22) | **clos** — archive, ne plus s'y fier pour l'état du code |

## 0hist. Historique résolu

<a id="s0.43"></a>
### 0.43 [§9](V11_phaseA.md#s9) P3-2 — la cible de charge devient une dimension d'action (slots ennemis + pointeur) — ✅ LIVRÉ, NON MERGÉ, NON MESURÉ (2026-07-28)

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

**Ce qui était en cause.** `_attack_sequence_rng` (`shooting_handlers.py`, 180 lignes) n'avait
**aucun appelant de production** et n'était tenu en vie que par **6 fichiers de tests** qui
l'appelaient en direct — ~159 assertions vertes qui ne prouvaient rien sur le jeu et
**immunisaient** le mort contre toute détection de code inutilisé. Motif §0bis (« du code testé
mais jamais appelé »), quatrième occurrence après §0.4, T6-i et §0.39.

**Ce qui a été fait, dans l'ordre.** (1) Les 6 fichiers ont été re-pointés sur le chemin vif,
(2) chaque assertion re-vérifiée, (3) **puis seulement** la fonction supprimée, (4) puis les états
résiduels. Les 4 commits de la branche `v11-0.38-dead-code` suivent cet ordre.

---

#### Le résultat principal : DEUX écarts de conformité, et c'est le MORT qui avait tort

C'est ce que la migration devait faire apparaître, et elle l'a fait. Aucune assertion n'a été
assouplie : ces deux-là ont été **retirées parce que la règle leur donne tort**, PDF en main.

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
| `test_shoot_attack_sequence.py` | 7 tests sur le mort | **12** — séquence de tir bout-en-bout via `build_manual_shoot_allocation`, jusqu'aux PV retirés : les 4 issues, AP, invulnérable (ignore l'AP), 05.01/05.02/05.04 |
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

- **109 tests verts** sur les 12 fichiers concernés (6 migrés + 6 vifs complétés), plus les 22
  autres fichiers qui importent `shooting_handlers` — verts également.
- **Contre-épreuve par mutation** : 7 clauses du **vif** cassées une à une, chaque fois une
  vérification complète puis restauration. **7/7 rouges**, baseline et restauration vertes.

  | Mutation du vif | Résultat |
  |---|---|
  | 05.02 — la blessure critique n'est plus critique | 🔴 |
  | 24.16 — le bonus HEAVY n'est plus appliqué | 🔴 |
  | 24.38 — [TWIN-LINKED] ne relance plus | 🔴 |
  | 24.15 — la mêlée ne déclenche plus de jet de hasard | 🔴 |
  | 05.04 — l'AP n'aggrave plus la sauvegarde | 🔴 |
  | `closest_target_penetration` n'améliore plus l'AP | 🔴 |
  | 24.10 — DEVASTATING ne saute plus la sauvegarde | 🔴 |

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

**Conservé délibérément.** Les 4 branches `raise RuntimeError("… squad path expected")` de
`shooting_handlers.execute_action`. §9.2 les listait comme résidus ; vérification faite, le
dispatcher **est sur un chemin vif** ([w40k_core.py:6157](../../engine/w40k_core.py#L6157) — toute
action de tir non `squad_*` y passe). Ces `raise` sont des gardes explicites : les retirer ferait
retomber `activate_unit`/`shoot`/`left_click`/`invalid` sur le `else` final et transformerait une
erreur bruyante en `{"error": "invalid_action_for_phase"}` silencieux — exactement le contraire de
la règle « erreur explicite, jamais de fallback ».

**Hors périmètre, signalé.** `wound_ability_display_name` / `ap_modifier_ability_display_name` /
`hit_rule_modifier` : le mort les produisait pour le log, le vif ne les produit pas (il utilise des
**tokens** `[HEAVY]`/`[COVER]`/`[HAZARD]` dans le message, cf. `_emit_squad_shoot_log`). Aucune
règle de PDF n'est en jeu — c'est une convention d'affichage, pas une conformité. Conséquence à
noter : **le combat log ne signale pas qu'une relance a été accordée par une abilité d'unité**.
Les 3 clés sont encore lues par `w40k_core` (~L3754-3768) où elles valent toujours `None`.

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
   `_remove_model_artifacts` (rotation du meilleur modèle robuste, nettoyage legacy, nettoyage du
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
>   `⚠️ Évaluation NON FIABLE`, loggue le compteur TensorBoard `0_critical/0_eval_timeout_episodes`
>   et **sort avant** le gate, la métrique de win-rate, la sauvegarde du best model, l'early
>   stopping et l'historique robuste. Le training continue ; **le point de mesure est ignoré, pas
>   maquillé** — c'est le point clé : un score sur dénominateur tronqué n'alimente AUCUN signal.
> - `train.py` (gate de CURRICULUM) : `gate_now` exige maintenant `eval_reliable`. Une éval
>   abandonnée ne peut plus valider une transition de phase, et remet `consecutive_ok` à 0 —
>   sans tuer le run. Le `marker` reste synchronisé, donc la garde d'anti-désynchronisation
>   (`last_bot_eval_marker != total_global_episodes`) ne se déclenche pas.
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
> `x5_append` = 100, `x5_debug` = 100, `x1_debug` = 5. Et §0.14 a **explicitement retiré** la
> proposition de descendre à 20 (20 ép./bot ⇒ ±11 points d'erreur-type sur le win-rate, injectés
> dans `save_best_robust`). Cette ligne est donc conservée comme **trace de l'intention du
> 2026-07-26**, pas comme description de l'état : le paramètre qui a réellement bougé pour le run
> à lancer est `x1.bot_eval_freq` (2000 → 4000), et il est lui-même contredit par une
> modification non commitée du répertoire de travail (cf. l'alerte en §0).
> **MAJ 2026-07-28 soir : tranché dans l'autre sens — 2000 assumé et commité** (encadré 🟢 en §0).
>
> **Verrou** : `tests/unit/ai/test_eval_timeout_resilience.py` (**7** tests) — crash lève /
> crash+timeout lève (le crash prime) / timeout ne lève pas et n'atteint pas le gate / timeout
> loggue le compteur mais **jamais** un win-rate / éval propre atteint le gate (non-régression) /
> contrat des 3 compteurs / verrou **AST** sur `gate_now` exigeant `eval_reliable`.
> **Contre-épreuve mutation** : garde-fou remis sur `total_failed_episodes` + early-return
> neutralisé + `eval_reliable` retiré du gate → **3 rouges** ; restauré → 7 verts.
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
  `--new`**, sans valeur de jeu : `save_best_robust: false` fait que
  [train.py:3548](../../ai/train.py#L3548) écrit le modèle final **inconditionnellement** en fin
  de run. Le modèle précédent (19/07 04:25, entraîné AVANT les `VALUE` Munitorum, avec la
  `WarTrakk` à 175) reste disponible dans
  `ai/models/_backup_pre_munitorum_20260719_232816/` — **vérifié intact après le run**.
  ⚠️ Tout run `x5_debug` ultérieur écrasera à nouveau le modèle canonique : sauvegarder avant
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
l'axe par-bot déjà en place (`bot_eval/vs_*`, `0_critical/c_holdout_tactical`). Les deux listes
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
des 2 agents. Deux scalaires TensorBoard : `bot_eval/vs_tactical` et
`0_critical/c_holdout_tactical`.

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
  alimente `0_critical/b_worst_bot_score`.

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
au 2026-07-20 02:14 ; la sauvegarde `_backup_pre_munitorum_20260719_232816/` est intacte.

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
### 0.19 Revérifier T1→T5 et la section 9 ligne à ligne — ⏳ PARTIEL (T1 soldé §0.19.1→§0.19.3 ; section 9 auditée le 2026-07-24 → **NON FAITE**, cf. [§9.0](V11_phaseA.md#s9.0))

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

**Trois affirmations périmées repérées, SIGNALÉES et NON corrigées** (elles rejoignent le
tableau de §0bis) :

| # | Où | Affirmation | Pourquoi elle est périmée |
|---|---|---|---|
| 11 | [§6](V11_tranches.md#s6), critère **T2**, et [§8.2](V11_tranches.md#s8.2) | « `action_space.n == 41` », « `ACTION_WAIT` (18) », « `6+6+6+1+5+1+1+15 == 41` », « 19→shoot slot 0, 24→charge » | Le layout réel est **1047** actions : `ACTION_WAIT = 1024`, `SHOOT_SLOT_BASE = 1025`, `ACTION_CHARGE = 1030`, `ACTION_FIGHT = 1031` ([macro_intents.py:20-38](../../engine/macro_intents.py#L20-L38)). Changé par la refonte spatiale du move. **MAJ 2026-07-26 (§0.30 T-E)** : le layout est désormais **1062** — `SHOOT_SLOT_BASE = 1025` sur **20** slots, `ACTION_CHARGE = 1045`, `ACTION_FIGHT = 1046`. Le critère T2 **réel** (zéro littéral d'action dans `ai/`) reste, lui, satisfait. |
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
