# Bot_refactor — capacités communes, jitter, benchmarks holdout, league self-play, exploiters

> **Statut** : document de CONCEPTION, ouvert le 2026-08-14. Aucune ligne de code écrite.
> **Les huit étapes A→H sont conçues ici.** Ce qui est phasé, c'est l'EXÉCUTION : la première
> tranche est A+B+C+D, E→H attendent leur budget machine (§0bis, §5).
> Il répond à une proposition externe (pipeline `bots → jitter → benchmarks → league → exploiters`)
> rédigée sans accès au dépôt. Ce document confronte cette proposition au code et aux mesures,
> dit ce qui est retenu, ce qui est re-cadré, ce qui est écarté — et pourquoi.
>
> **Convention** : un chantier ouvert vit dans `backlog/`. Ce fichier est à la racine de
> `Documentation/Chantiers/` parce que son chemin a été demandé explicitement — exception actée
> n°1 de [`ROADMAP_INDEX.md`](../Roadmap/ROADMAP_INDEX.md).
>
> **Ce document n'est PAS la source de l'ordre du travail** : c'est
> [`ROADMAP_INDEX.md`](../Roadmap/ROADMAP_INDEX.md). Il porte le CONTENU d'un chantier, pas sa
> priorité.

---

## 0bis. Décisions utilisateur — tenues à jour ici, elles priment sur le reste du document

| Date | Sujet | Décision |
|---|---|---|
| 2026-08-14 | **Périmètre de CONCEPTION** | **TOUT**, A→H. Les huit étapes sont spécifiées ici au même niveau de détail : conception, schéma de config, fichiers touchés, tests, critère de fin, coût. Commencer par le début du curriculum n'autorise pas à laisser la fin en pointillés — un plan qui s'arrête là où il devient cher n'est pas un plan. |
| 2026-08-14 | **Périmètre d'EXÉCUTION, première tranche** | **B** = étapes **A+B+C+D** (capacités communes, jitter, trois benchmarks, `benchmark_floor` + partition à trois familles). E→H sont **conçues** et leur exécution est différée : ce qui les diffère est le **budget machine** de leur run (~200 h pour P1→P10, ~60 h pour trois exploiters — le CODE d'E et F, lui, ne coûte rien) et un prérequis d'exécution (`x1_selfplay` jamais lancé). Jamais une conception manquante. La dernière section du §4 liste ce que A→D doit laisser ouvert pour ne pas les fermer. |
| 2026-08-14 | **Nombre de benchmarks** | **TROIS**, à condition que leurs comportements soient **complémentaires** — chacun teste un aspect différent du jeu. Le §4.C ci-dessous porte cette conception. La mesure du 2026-08-12 (une seule dimension) reste vraie ; elle n'est pas une raison de renoncer, elle est une raison de **mesurer** la complémentarité au lieu de la supposer (critère en §4.C.4). |
| 2026-08-15 | **Gating** | **TRANCHÉ — deux étages.** Un modèle qui écrase les six bots d'entraînement et s'effondre contre un benchmark **n'est pas sauvegardé** : `benchmark_floor` entre dans `_evaluate_model_gate`. Les trois `reference_*` gatent ; `tactical` reste scellé, exclu de tout signal. |
| 2026-08-15 | **Ce qu'un benchmark raté SIGNIFIE** | Un plancher raté dit que l'agent **n'a pas généralisé ce qu'il a vu à l'entraînement** — donc c'est **l'ENTRAÎNEMENT qu'il faut revoir**, pas seulement le modèle qu'il faut refuser. Ce qu'on diagnostique est le **COMPORTEMENT** de l'agent (s'est-il fait détruire ? a-t-il trop peu joué les objectifs ?), comparé entre benchmarks et bots d'entraînement : même faute des deux côtés ⇒ la RÉCOMPENSE ne la punit pas ; faute seulement contre les benchmarks ⇒ le CURRICULUM ne l'expose pas. §4.D.3. |
| 2026-08-15 | **Instrument manquant, ajouté au périmètre** | L'évaluation ne publie **aucune donnée de jeu** par adversaire (vérifié : `wins`/`losses`/`draws` + ventilations, rien d'autre ; `shoot_stats` produit puis jeté). La boucle ci-dessus est donc aveugle en l'état. **§4.D.4** ajoute le profil comportemental par adversaire — des deux côtés, ventilé par issue. Coût : zéro épisode supplémentaire, c'est du câblage. |
| 2026-08-15 | **Trois corrections d'audit** | (1) La persistance n'est PAS un bonus « × étalement » : toute échelle tirée du champ de candidats est mathématiquement INERTE pour `p < 1` (démonstration §2.5) — règle de conservation à échelle déclarée par critère (§4.A.3). (2) `tactical` entre à `0.0` dans `bot_eval_weights` de `x1_new_bots` : sans lui le témoin scellé de §4.D.1 ne produit AUCUN chiffre sur le profil actif ; +1 600 ép. par run de 50 000 (§4.D.2). (3) Les transformations d'état sont conscientes du SIGNE : `protect_lead` doit renforcer l'évitement d'`endgame` (`w_enemy` −0,35), pas l'affaiblir (§4.A.1). |
| 2026-08-04 | Holdout | `tactical` est un INDICATEUR, pas le critère ; sa valeur est GELÉE (§0.55) pour rester comparable. |
| 2026-08-12 | Orthogonalité | Abandonnée comme critère : les six styles d'entraînement forment une échelle de difficulté, pas six axes. |

---

## 0. Verdict en dix lignes

La proposition est bien construite et son ossature (capacités communes → jitter → holdout
d'adversaires → league historique → exploiters) est la bonne. Trois de ses postulats sont
cependant **contredits par des mesures déjà faites sur ce dépôt**, et un quatrième par le budget
machine :

1. **Le mot « orthogonaux » ne décrit pas ce qu'on peut obtenir** — l'orthogonalité a été
   ABANDONNÉE comme critère le 2026-08-12, décision utilisateur sur mesure : le format n'a qu'une
   dimension (seuls les objectifs marquent, zéro victoire par élimination sur 600 parties). Ce qui
   reste faisable, et qui est l'essentiel de la proposition, c'est **un adversaire qui RAISONNE
   autrement et que l'agent n'a jamais rencontré**. Les trois benchmarks du §4.C sont exactement
   ça ; ce qui n'est pas garanti d'avance, c'est qu'ils rendent trois signaux distincts — donc on
   le **mesure** (§4.C.4) au lieu de le supposer.
2. **`benchmark_floor >= 80 %` comme porte d'entrée du self-play** — la ligne de base actuelle est
   `combined = 0,7433`, pire bot `racer = 0,630`. Un holdout doit être PLUS dur que le panel
   d'entraînement : son plancher naîtrait sous 0,63. La porte ne s'ouvrirait jamais.
3. **Un holdout qui décide cesse d'être un holdout** — arbitrage utilisateur du 2026-08-04
   (`strategie_evaluation.md` §10.6). Faire du `benchmark_floor` un gate le contredisait frontalement.
   **Résolu le 2026-08-15 par deux étages** (§4.D.1) : les trois `reference_*` gatent, `tactical`
   reste scellé. Et le plancher ne sert pas qu'à refuser un modèle — il **diagnostique
   l'entraînement** (§4.D.3), ce qui rend le témoin scellé indispensable et non plus seulement
   élégant.
4. **FAIRE TOURNER la league jusqu'à P10 + 3 exploiters coûte ~11 jours de machine en continu**,
   mesuré sur le régime réel du dépôt (4 h 01 pour 10 000 épisodes, cf. AI_TRAINING.md §run 2026-08-10), évaluations non comprises.
   L'ÉCRIRE, en revanche, ne coûte rien de plus qu'une étape ordinaire (§4.E, §4.F) — la distinction
   commande tout l'ordre du §5. Et elle se bâtit sur un mécanisme de self-play **livré mais jamais
   exécuté une seule fois**.

Ce qui est **entièrement retenu** : les capacités communes (§4.A), le jitter (§4.B), les trois
benchmarks à mécanisme de décision différent (§4.C), les métadonnées de checkpoint, les métriques,
la distinction `randomness ≠ jitter`.

---

## 1. Architecture actuelle — relevée dans le code, pas déduite

### 1.1 Qui décide quoi

| Fichier | Rôle réel |
|---|---|
| [`ai/bot_doctrines.py`](../../ai/bot_doctrines.py) | Les SIX styles. `_DoctrineBot` = socle ; 4 points de variation : `target_score`, `wants_charge`, `movement_weights`, `PLACEMENT_WEIGHTS` |
| [`ai/evaluation_bots.py`](../../ai/evaluation_bots.py) | Les 5 anciens bots (**GELÉS**, condamnés après l'étape 7) + `tactical` (holdout) + les primitives d'espace d'action (`_best_slot_action`, `_target_slot_entries`, `_select_weighted_deployment_action`) |
| [`ai/bot_registry.py`](../../ai/bot_registry.py) | SOURCE UNIQUE clé → classe. `LEGACY_BOT_KEYS`, `DOCTRINE_BOT_KEYS`, `HOLDOUT_BOT_KEYS`, `SELECTION_BOT_KEYS = ALL − HOLDOUT` |
| [`config/bot_movement_weights.json`](../../config/bot_movement_weights.json) | 8 entrées de doctrine (6 styles + `endgame_push` + `attrition_withdraw`), 6 poids chacune, `hold_bonus` global. Aucun défaut : clé absente ⇒ lève |
| [`ai/env_wrappers.py`](../../ai/env_wrappers.py) `BotControlledEnv` | Tire le bot de l'épisode, applique le siège, choisit bot vs self-play, joue le tour adverse |
| [`ai/train.py`](../../ai/train.py) `_build_training_bots_from_config` | Construit un **pool de 100 instances** depuis `bot_training.ratios` |
| [`ai/bot_evaluation.py`](../../ai/bot_evaluation.py) | Évaluation parallèle par sous-processus ; `active_bot_names = tuple(bot_eval_weights.keys())` |
| [`ai/training_callbacks.py`](../../ai/training_callbacks.py) `BotEvaluationCallback` | Gating, score robuste, sauvegarde du best robust model |

### 1.2 Les cinq faits de code qui contraignent toute la suite

**(a) Un bot de poids 0 est quand même JOUÉ.** `active_bot_names` itère sur les CLÉS de
`bot_eval_weights` ; le poids ne pèse que sur `combined`. `tactical` (poids 0.0) joue donc
`bot_eval_final` épisodes comme les autres. ⇒ **ajouter un benchmark coûte un budget d'évaluation
plein, quel que soit son poids.** Sur `x1_long`/`x1_new_bots` (`bot_eval_final = 600`), chaque
benchmark ajouté = +600 épisodes à l'évaluation finale et +100 à chaque évaluation intermédiaire.

**(b) Le mécanisme de holdout existe déjà et il est complet.** `HOLDOUT_BOT_KEYS` retire un
adversaire de `SELECTION_BOT_KEYS`, donc du `combined`, du `worst_bot`, du gating et du score
robuste — vérifié aux trois sites (`selection_worst_bot`, `_evaluate_model_gate` ligne 1618,
score robuste ligne 2160). Un `reference_*` s'y branche sans architecture nouvelle.

**(c) Les instances de bots sont PARTAGÉES entre épisodes.** `random.choice` sur un pool de 100
(`env_wrappers` ~1163) : la même instance rejoue des dizaines d'épisodes. Tout état d'instance est
donc gardé par un marqueur d'épisode (`_deployment_episode_marker`, `DecapitationBot._focus_turn`
— les deux ont déjà causé une fuite inter-épisodes, cf. leurs docstrings). **Tout état de jitter
devra suivre exactement le même patron, sous peine de rejouer la fuite une troisième fois.**

**(d) L'entraînement n'ensemence PAS le RNG global ; l'évaluation si.** `grep random.seed ai/*.py`
→ 2 hits, tous deux dans `bot_evaluation.py` (~840, par épisode). Le tirage du bot et sa
`randomness` ne sont donc **pas reproductibles en entraînement aujourd'hui**. En revanche le siège
et le tirage self-play le sont, par `sha256(f"{global_seed}:{env_rank}:{episode_index}:...")`.
⇒ le jitter doit utiliser CE schéma, pas le `random` global — sans quoi l'exigence de
reproductibilité de la proposition serait affichée sans être tenue.

**(e) Le self-play existe, sur UN snapshot, et n'a jamais tourné.** `opponent_mix` (rampe
`start→end`, `warmup_episodes`, snapshot republié par `_publish_self_play_snapshot`, rechargé par
mtime) est câblé **uniquement sur le chemin rotation** — `create_multi_agent_model` lève
explicitement si on l'active ailleurs. Profil `x1_selfplay` : **livré, JAMAIS exécuté** (ROADMAP
§1 pt 8 : « le premier run est aussi son premier test d'intégration »).

### 1.3 La ligne de base à ne pas perdre

| Grandeur | Valeur | Source |
|---|---|---|
| `combined` panel refondu | **0,7433** | chantier `panel_bots.md` §12.14, 100 ép./bot, `robust_0.8721` |
| Pire bot | **`racer` = 0,630** | idem |
| Pire scénario | **0,6867** | idem |
| Régime machine | **10 000 épisodes = 4 h 01** | AI_TRAINING.md §run 2026-08-10 |
| Victoires par élimination | **0 sur 600 parties** | §12.1 du chantier |

⚠️ Chaque poids de `bot_movement_weights.json` porte un `_justification` avec son protocole
(60 ép./bot, UN poids par run, dérive des cinq contrôles 0,000). **Toute capacité ajoutée à un bot
périme la mesure de ses poids.** C'est le vrai coût des étapes A et B, et il n'apparaît pas dans la
proposition.

---

## 2. Les huit écarts entre la proposition et le dépôt

### 2.1 « Orthogonaux » est le mauvais mot pour la bonne idée

Décision utilisateur du 2026-08-12 (`panel_bots.md` §3 pt 2) : les six bots **se déplacent
en bloc** d'un modèle à l'autre (+3 à +7 points, **ordre strictement identique**). Ils forment une
seule dimension mesurée à six niveaux. La cause est le FORMAT, pas le dessin des bots : seuls les
objectifs marquent, et il y a eu **zéro victoire par élimination sur 600 parties**.

**Ce qui reste vrai de la proposition, et c'en est l'essentiel** : un adversaire qui **raisonne
autrement** et que l'agent n'a **jamais rencontré** mesure la généralisation, qu'il ouvre ou non un
axe nouveau. C'est même le seul instrument qui la mesure : un win-rate contre des bots
d'entraînement mesure l'exploitation apprise (`strategie_evaluation.md` §10.5, textuel).

**Ce qui n'est pas garanti** : que trois benchmarks rendent trois signaux DISTINCTS. Sur une
échelle à une dimension, ils peuvent classer les modèles dans le même ordre — auquel cas c'est un
signal payé trois fois. Ce n'est pas une raison de n'en faire qu'un : c'est une raison de **le
mesurer** et de le publier.

⇒ **Re-cadrage du critère** : pas « orthogonal » (propriété qu'on ne peut pas garantir) mais
« **mécanisme de décision différent, jamais vu à l'entraînement, et complémentarité mesurée** ».
**TROIS** benchmarks, décision utilisateur du 2026-08-14 (§0bis), conçus pour punir trois fautes
différentes de l'agent et accompagnés du critère de complémentarité du §4.C.4.

### 2.2 `benchmark_floor >= 80 %` — la porte ne s'ouvrirait jamais

Le panel d'ENTRAÎNEMENT tient l'agent à `combined = 0,7433`, pire bot 0,630. Un benchmark de
holdout est censé être plus dur (c'est sa raison d'être). Poser 0,80 comme condition d'entrée en
self-play, c'est poser une condition que le modèle actuel rate déjà **contre les bots qu'il
connaît**.

⇒ Le seuil ne peut pas être posé AVANT la première mesure des benchmarks. Poser un chiffre rond
avant de mesurer est exactement le mode d'échec du §12.7 du chantier panel : deux hausses de poids
« posées par doctrine » ont été **défaites** le lendemain, dont une qui faisait l'inverse de ce
qu'elle annonçait.

### 2.3 Un holdout qui décide cesse d'être un holdout — arbitrage du 2026-08-04

`strategie_evaluation.md` §10.6, arbitrage utilisateur, textuel : *« un holdout qui décide cesse
d'être un holdout. Dès qu'un chiffre valide un run, on optimise dessus »*. La proposition fait du
`benchmark_floor` **la** porte d'entrée du self-play et un gate de promotion Pn→Pn+1. C'est un
conflit frontal avec une décision datée.

⇒ **Tranché le 2026-08-15** (§4.D) : **deux étages**, `reference_*` (holdout d'entraînement,
autorisé à gater) et `tactical` (holdout **scellé**, exclu de tout signal, le seul chiffre qu'on
puisse montrer à un financeur en disant « personne n'a optimisé dessus »). `tactical` est déjà
exactement ça, et sa valeur est GELÉE depuis le 2026-08-04 (§0.55) précisément pour rester
comparable.

⇒ Et une réponse que la proposition ne portait pas : un plancher raté **n'est pas seulement un
modèle à refuser, c'est un entraînement à revoir** (§4.D.3). C'est ce qui déplace le sujet — le
`benchmark_floor` cesse d'être un filtre de sortie pour devenir un diagnostic sur le curriculum.
Et c'est aussi ce qui rend le rôle de `tactical` non négociable : dès qu'on corrige l'entraînement
en réaction à un benchmark, il faut un témoin que la correction n'a pas touché.

### 2.4 La mémoire de cible : deux mécanismes confondus en un

La proposition veut généraliser « la mémoire de `decapitation` » en bonus de persistance pour tous.
Or `DecapitationBot` ne fait pas de la persistance, il fait de la **concentration** :
`_focus_target` est une mémoire **partagée entre escouades**, et sa propre docstring dit pourquoi
— *« les bots décident escouade par escouade sans se voir les unes les autres, donc aucun critère
local ne peut produire une concentration »*. Le déplacement lui-même suit la cible commune
(`_enemy_anchors` surchargé).

Deux capacités distinctes, donc :
- **persistance** : *cette* escouade garde *sa* cible précédente — généralisable à tous, par une
  règle de conservation (§2.5) ;
- **concentration** : *toutes* les escouades partagent UNE cible — c'est la doctrine de
  `decapitation`, elle reste un drapeau de style, pas un curseur.

Les confondre transformerait `decapitation` en « un bot qui insiste un peu plus », c'est-à-dire
supprimerait le style en croyant le généraliser.

### 2.5 L'échelle du bonus de persistance n'est pas un réglage, c'est une conception

La proposition écrit « adapter l'échelle aux scores réels du moteur ». Les scores ne sont pas sur
une échelle commune, et pas même de signe constant :

| critère | forme du score |
|---|---|
| `_score_efficiency` | dégâts espérés (~5 à 20) |
| `_score_kill_now` | `1000 si létal + dégâts` |
| `_score_value_removed` | `VALUE × fraction de PV retirée` |
| `_score_contester` | `−distance × 10 + dégâts` (**négatif** hors zone) |

Un bonus additif fixe (0,10 … 0,95) est ininterprétable là-dedans : il est invisible chez
`_score_kill_now` et dominant chez `_score_contester`.

**Et un bonus relatif au champ de candidats ne vaut pas mieux — il est INERTE** (trouvé à l'audit
du 2026-08-15, après avoir été retenu ici même) : avec `bonus = p × (meilleur − second)`, une
cible précédente qui n'est pas déjà la meilleure vaut au plus `second`, donc son score ajusté au
plus `second + p × (meilleur − second) < meilleur` pour tout `p < 1` — le mécanisme ne change
JAMAIS une décision, à aucun `p` du panel (0,10 … 0,95). Toute échelle calculée sur le champ
dégénère de même : à DEUX candidats, l'écart-type vaut la moitié de l'écart, il faudrait `p > 2`.
Or le duel à deux cibles est le cas fréquent de fin de partie — précisément là où la persistance
compte.

⇒ **L'échelle vient du CRITÈRE, pas du champ** : garder la cible précédente ssi
`meilleur − précédente ≤ p × échelle`, où chaque critère déclare son échelle dans sa définition —
`score de la précédente` pour les trois critères positifs (forme ratio : on ne lâche que pour une
cible `(1+p)` fois meilleure), `10,0` (un hex, l'unité du critère) pour `_score_contester`.
Interprétable par style, sans dimension, testable — y compris le test de bascule à deux candidats
que la forme « étalement » rendait impossible. Ça impose une sélection locale à
`bot_doctrines.py` (§4.A.3) — `evaluation_bots._best_slot_action` ne peut pas être touché, les
5 anciens bots sont gelés jusqu'à l'étape 7 du chantier panel.

### 2.6 Généraliser les capacités COMPRIME le panel, et périme ses mesures

Donner à tous les bots la conscience de fin de partie et la préservation les rend **plus
compétents et plus semblables**. Sur un panel qui est déjà une échelle de difficulté à une
dimension, c'est défendable — on relève l'échelle — mais il faut le dire : ce n'est pas « rendre le
panel plus riche », c'est « rendre les bots meilleurs ». Et les 8 jeux de poids ont tous été
mesurés sur le comportement d'AVANT : la ligne de base 0,7433 / 0,630 **devra être rejouée** après
l'étape A (protocole §12.13 du chantier panel).

### 2.7 `alpha` n'est pas dans les ratios d'entraînement — la décision devra être reprise

`x1_new_bots.bot_training.ratios` = `racer 0.35, scorer/attrition/decapitation/endgame 0.15,
random 0.05`. **`alpha` est absent**, volontairement (justification de la config : l'agent le bat à
93 %, « son exposition n'apporte pas de gradient utile »). Après l'étape A, `alpha` gagne la
préservation et l'adaptation de tempo : ce jugement est à refaire, pas à reconduire.

### 2.8 La league : ordre et budget

ROADMAP §1 (chemin critique, ordre imposé par décisions des 2026-08-07 et 2026-08-10) : P3-4 →
P3-5 → P3-6 → P4 → P5 (profil de validation) → **mesure de référence `x1_long`** → §0.59 phase 2
self-play → refonte du panel de bots. La league proposée arrive donc **après** la mesure de
référence, et la phase 2 self-play — sur laquelle elle se bâtit — n'a jamais tourné.

Budget, au régime mesuré (10 000 ép. = 4 h 01, soit ~0,69 ép./s, cf. AI_TRAINING.md §run 2026-08-10) :

| Poste | Épisodes | Heures |
|---|---|---|
| P1 → P10, 50 000 ép./génération | 500 000 | ~200 h |
| E1, E2, E3 à 50 000 ép. | 150 000 | ~60 h |
| **Total entraînement seul** | **650 000** | **~260 h ≈ 11 jours continus** |

Évaluations non comprises — et elles **croissent avec la league** : évaluer Pn contre n champions
+ 6 bots + 2 benchmarks à 600 épisodes chacun, c'est `(n+8) × 600` épisodes par évaluation finale.
À P10 : 10 800 épisodes, soit ~4 h 20 pour la seule évaluation finale d'une génération.

---

## 3. Décisions de conception prises dans ce document

| # | Décision | Motif |
|---|---|---|
| D1 | Les capacités sont des **modulations des points de variation existants**, jamais de nouveaux points | 4 points de variation suffisent ; en ajouter un cinquième oblige à re-vérifier les 6 styles |
| D2 | Une capacité s'exprime par **une transformation canonique unique + un gain par style**, jamais par un jeu de poids complet par état | 6 gains à mesurer au lieu de 72 poids posés à l'aveugle |
| D3 | Un style peut déclarer un **override explicite** de vecteur pour un état | `endgame_push` et `attrition_withdraw` sont MESURÉS : ils survivent au bit près, la ligne de base reste comparable |
| D4 | `gain = 0` reproduit le comportement actuel **exactement**, et c'est un test | même contrat que `jitter = 0` ; c'est ce qui rend l'étape A vérifiable sans run |
| D5 | **Persistance ≠ concentration** : deux mécanismes, deux mots, deux tests | cf. §2.4 |
| D6 | La persistance est une **règle de conservation à échelle de critère** (`gap ≤ p × échelle`), jamais un bonus relatif au champ de candidats | cf. §2.5 — toute échelle tirée du champ (étalement, écart-type) est inerte pour `p < 1` ; corrigé le 2026-08-15 |
| D7 | **Trois** benchmarks, chacun punissant une faute différente, + un critère de complémentarité MESURÉ ; **deux étages** de holdout | décision utilisateur 2026-08-14 (§0bis) ; cf. §2.1, §2.3, §4.C |
| D8 | Les seuils (`benchmark_floor`, gates de promotion) sont **posés après la première mesure**, jamais avant | cf. §2.2 et le §12.7 défait du chantier panel |
| D9 | La league réutilise le tirage `sha256(seed:rank:episode:…)` déjà en place | seul schéma reproductible du wrapper ; le `random` global ne l'est pas (§1.2.d) |
| D10 | `evaluation_bots.py` n'est **pas** touché (5 anciens bots gelés) | décision 2026-08-11, étape 7 du chantier panel non commencée |

---

## 4. Le plan, par étapes

Chaque étape est **livrable et testable seule**. Les étapes A et B ne demandent **aucun run
d'entraînement** pour être validées — c'est ce qui les met en tête.

### Étape A — capacités communes (`late_game`, `preservation`, `persistence`)

**Objectif** : sortir les trois capacités des styles qui les monopolisent, sans transformer les
styles en clones ni inventer des poids non mesurés.

**Nouveau fichier de config** : `config/bot_doctrine_profiles.json`

```
{
  "_comment": "Gains de capacité par style. 0.0 = capacité inerte, comportement d'avant au bit pres.",
  "late_game_transform": { "push_gain": <k>, "protect_gain": <k> },   // constantes globales, mesurees UNE fois
  "profiles": {
    "racer":        { "late_game": 0.8, "preservation": 0.1, "persistence": 0.10, "focus_shared": false },
    "endgame":      { "late_game": 1.0, "preservation": 0.5, "persistence": 0.40, "focus_shared": false },
    "alpha":        { "late_game": 0.4, "preservation": 0.0, "persistence": 0.50, "focus_shared": false },
    "attrition":    { "late_game": 0.4, "preservation": 1.0, "persistence": 0.60, "focus_shared": false },
    "decapitation": { "late_game": 0.6, "preservation": 0.3, "persistence": 0.95, "focus_shared": true  },
    "scorer":       { "late_game": 0.8, "preservation": 0.6, "persistence": 0.15, "focus_shared": false }
  },
  "state_overrides": { "endgame": {"desperate_push": "endgame_push"},
                       "attrition": {"preserve": "attrition_withdraw"} }
}
```

Aucun défaut : une clé absente lève (`require_key`), comme `bot_movement_weights.json`.
Les valeurs ci-dessus sont celles de la proposition, **posées et non mesurées** — elles sont un
point de départ, à régler par le protocole §12.13 du chantier panel.

#### A.1 `late_game` — état de partie partagé

Une fonction **sans doctrine**, testable seule :

```
late_game_state(game_state, player) -> "protect_lead" | "normal" | "desperate_push"
```

Entrées : `turn`, `get_effective_turn_limit`, différentiel de VP, zones contrôlées, zones
contestables. Une seule implémentation, aucun `if style ==`.

Effet, **transformation canonique unique** appliquée au vecteur de poids, modulée par le gain `g`
du style :

| état | transformation |
|---|---|
| `desperate_push` | `w_objective ×(1+g·k)`, `w_contest ×(1+g·k)`, `w_risk ×(1−g)` |
| `protect_lead` | `w_risk ×(1+g·k)`, `w_enemy ×(1−g)`, `w_contest ×(1−g)` |
| `normal` | identité |

⚠️ **Signe — corrigé le 2026-08-15.** `×(1−g)` est une atténuation et suppose un poids POSITIF.
Sur la seule colonne signée du panel — `w_enemy` (`endgame` −0,35 ; `attrition_withdraw` −1,0 est
un override, routé avant la transformation) — elle affaiblirait l'évitement au moment même de
protéger une avance. Règle : `w > 0 → ×(1−g)` (moins d'attraction), `w < 0 → ×(1+g·k)` (plus
d'évitement), `0` reste `0`. Verrouillé par test (§4.A.5).

et sur `wants_charge` : `desperate_push` abaisse le seuil d'échange, `protect_lead` le relève.

**`endgame` garde son vecteur mesuré** : `state_overrides` le route vers `endgame_push`, qui gagne
donc sur la transformation générique. Sa doctrine reste la plus liée au temps (gain 1.0 + le seul
override de poussée), exactement comme le demande la proposition.

⚠️ `EndgameBot.PUSH_LAST_TURNS` disparaît au profit de `late_game_state` — mais la bascule sur
5 tours doit rester **au tour 3**, sinon la ligne de base n'est plus comparable. C'est un test.

#### A.2 `preservation` — pression continue par unité

Généralisation d'`AttritionBot._withdrawing`, qui reste la référence de forme : le prédicat
« entamée » est une question de RÈGLE, tranchée par `is_unit_at_or_below_half_strength` (08.03) et
jamais par un `HP < HP_MAX/2` maison — `units_cache["HP_CUR"]` est la SOMME des PV de l'escouade
alors que `unit["HP_MAX"]` est le PV d'UNE figurine.

```
preservation_pressure(unit, game_state) -> float   # 0..1, sans doctrine
```
Facteurs : effectif restant (08.03), VALUE relative aux autres escouades du camp, dégâts entrants
espérés (déjà calculés par `_firepower_profile`), utilité au scoring (dans/proche d'une zone),
tours restants, différentiel de VP.

Effet : `pression × sensibilité_du_style` module le vecteur comme `protect_lead`, et coupe
`wants_charge` au-delà d'un seuil. `attrition` route vers son override `attrition_withdraw`.
`alpha` à 0.0 **connaît** la capacité et ne l'exerce jamais — ce que demande la proposition, et ce
qui est obtenu sans une seule branche par style.

#### A.3 `persistence` — règle de conservation à échelle de critère (≠ concentration)

Nouveau `_best_slot_action_persistent(...)` **dans `bot_doctrines.py`** (D10), qui réutilise
`_target_slot_entries` importé de `evaluation_bots` :

1. score de chaque cible ouverte par le masque (`None` écarte, contrat inchangé) ;
2. si la cible précédente **de cette escouade** est candidate : elle est CONSERVÉE ssi
   `meilleur − score(précédente) ≤ p × échelle`, l'échelle étant déclarée par le critère de
   ciblage du style — `score(précédente)` pour `_score_efficiency` / `_score_kill_now` /
   `_score_value_removed` (ratio : on ne lâche que pour une cible `(1+p)` fois meilleure),
   `10,0` (un hex) pour `_score_contester` ;
3. sinon : `argmax`.

Sémantique de `p`, désormais lisible : `racer` (0,10) lâche dès +10 % ; `decapitation` (0,95)
exige presque le double. Le `+1000` létal de `_score_kill_now` force toujours la bascule vers un
kill disponible — sauf si la précédente est létale aussi, auquel cas on la finit. Pourquoi pas un
bonus « × étalement » : démonstration d'inertie au §2.5.

Rupture de mémoire, sans exception : cible morte, hors table (20.01), absente du masque, dégât
espéré nul (`base <= 0`, le prédicat que `DecapitationBot` utilise déjà), fin de tour.

`focus_shared: true` (seul `decapitation`) conserve **en plus** la mémoire partagée entre escouades
et la surcharge d'`_enemy_anchors` : le style ne change pas.

#### A.4 Fichiers touchés

`ai/bot_doctrines.py` · `config/bot_doctrine_profiles.json` (nouveau) ·
`config/bot_movement_weights.json` (aucun poids modifié — seulement, si le réglage l'impose,
de nouveaux blocs d'override) · tests.
**Non touchés** : `ai/evaluation_bots.py`, `ai/bot_registry.py`, `ai/train.py`, l'évaluation.

#### A.5 Tests (pytest, `tests/unit/ai/`)

- `test_bot_capabilities_neutral.py` : **gains à 0 ⇒ décision identique** à l'implémentation
  actuelle, sur un état fabriqué, pour les six styles (le verrou de D4) ;
- `test_bot_late_game_state.py` : `protect_lead` / `normal` / `desperate_push` sur trois états
  construits ; bascule d'`endgame` toujours au tour 3 sur une bataille de 5 ; `protect_lead` sur
  `endgame` **renforce** l'évitement (`|w_enemy|` effectif ≥ base — le poids signé ne s'atténue
  pas à contresens, §4.A.1) ;
- `test_bot_preservation.py` : `attrition > alpha` en sensibilité sur la MÊME unité entamée ;
  unité saine ⇒ pression nulle ; porteur d'objectif ⇒ pression réduite ;
- `test_bot_target_persistence.py` : **bascule effective à DEUX candidats** — précédente
  légèrement sous la meilleure ⇒ conservée à `p` fort, lâchée à `p = 0` (le verrou qui aurait
  attrapé l'inertie des formes « × étalement », cf. §2.5) ; échelle par critère (ratio sur les
  trois positifs, un hex sur `contester`) ; bascule forcée vers un kill létal si la précédente ne
  l'est pas ; rupture sur cible morte / hors masque / dégât nul, et **`decapitation` reste
  concentré** (deux escouades, une seule cible).

Chaque verrou prouvé ROUGE par mutation (T4), `__pycache__` purgé entre les deux passes.

#### A.6 Critère de fin

Tests verts + verrous prouvés + **ligne de base rejouée** (`scripts/bot_ranking.py` ou
`scripts/bot_zone_direct.py --json-out`, 60 ép./bot minimum, plateau `board/44x60x1` fixé, md5 du
modèle relevé). Le nouveau `combined` remplace 0,7433 dans le ROADMAP et dans §12.14 du chantier
panel — un chiffre rendu faux par sa propre livraison est une régression (T2).

---

### Étape B — jitter

**Objectif** : PPO ne doit pas apprendre les coefficients exacts d'un bot, mais une *famille*.

**Config** — deux clés, dans `bot_training`, **obligatoires** (valeur `0.0` autorisée, écrite
explicitement dans les 10 profils : pas de défaut silencieux) :

```
"bot_training": { "ratios": {...}, "randomness": {...},
                  "movement_weight_jitter": 0.10,
                  "behavior_parameter_jitter": 0.05 }
```

**Tirage** — au `reset` de `BotControlledEnv`, APRÈS le tirage du bot, par
`sha256(f"{global_seed}:{env_rank}:{episode_index}:jitter:{bot_key}")` (D9), stocké sur l'instance
et gardé par le marqueur d'épisode, **exactement** comme `_deployment_episode_marker` (§1.2.c).

**Application** — multiplicative sur le tuple RENDU par `load_doctrine_weights`, jamais sur la
config chargée : `w' = w × U(1−j, 1+j)`. Un poids nul reste nul, un poids négatif garde son signe,
la config source n'est pas mutée — les trois contraintes de la proposition sont tenues par la seule
forme multiplicative.

`behavior_parameter_jitter` porte sur les scalaires de l'étape A (`late_game`, `preservation`,
`persistence`, seuil de charge) et reste **faible** : `alpha` ne doit jamais devenir `scorer`.
Un test le verrouille par un invariant d'ordre (le `w_enemy` effectif d'`alpha` reste le plus haut
du panel sur N tirages).

**Évaluation** : le jitter vient de `bot_training`, que `bot_evaluation.py` ne lit pas. Il est donc
nul en évaluation **par construction**, pas par un drapeau qu'on pourrait oublier. `bot_ranking.py`
et `bot_zone_direct.py` sont dans le même cas — le protocole de réglage §12.13 reste valide.

**`randomness` n'est pas touché** et ne le sera pas : `randomness` = le bot joue parfois au hasard
(`select_action_with_state`, ligne 539) ; `jitter` = le bot reste rationnel, sa personnalité varie
d'un épisode à l'autre. Deux mécanismes, deux clés, deux tests.

**Sous-tâche du même périmètre** : le tirage du bot lui-même (`random.choice`, `random` global non
ensemencé, §1.2.d) passe au même schéma sha256. Sans ça, annoncer « jitter reproductible » serait
faux — le bot tiré ne l'est pas.

**Tests** : jitter 0 ⇒ nominal exact · bornes respectées · même graine ⇒ mêmes facteurs · graines
différentes ⇒ facteurs différents · constance pendant l'épisode · config source non mutée
(`Object.is` du côté Python : comparaison du dict rechargé) · poids nul reste nul · poids négatif
garde son signe · identité de style préservée.

---

### Étape C — TROIS benchmarks de holdout, à mécanisme de décision différent

> ⛔ **CE DISPOSITIF N'EST PLUS ACTIF (2026-08-26).** Les trois `reference_*` et `tactical` ont été
> retirés de `bot_eval_weights` sur les six profils (commit `8bb4e42e`). Comme la boucle
> d'évaluation itère sur les CLÉS de ce dictionnaire — le mécanisme décrit au §1.2.a — ils ne sont
> **plus joués du tout**, ni en évaluation intermédiaire ni en évaluation finale.
> **Motif** : ces bots sont saturés à 1.00, constat déjà acté dans `ai/curriculum.py`
> (`evaluate_stage_gate`) — « un plancher posé dessus est franchi par n'importe quel modèle et ne
> sépare rien ». Un témoin qui rend toujours la même valeur ne mesure rien, et le coût chiffré au
> §D.1 ci-dessous (+1 600 épisodes par run de 50 000) l'achetait pour rien.
> Les trois bots restent **définis et jouables** (`ai/bot_registry.py`, `BENCHMARK_BOT_KEYS`,
> `scripts/bot_ranking.py`) : c'est leur participation automatique à l'évaluation qui est
> supprimée, pas les bots. La conception ci-dessous reste la référence si le dispositif est
> réarmé un jour — auquel cas il faudra d'abord traiter la saturation.

**Ce qui les sépare des six styles d'entraînement, et c'est le cœur de l'étape.** Les six styles
notent CHAQUE destination par une somme pondérée `Σ(poids × features)` et choisissent leur cible
par un critère unique fixé par la doctrine. Les trois benchmarks ne font ni l'un ni l'autre :

1. **Intention macro d'abord, géométrie ensuite.** Le bot élit une intention pour l'unité
   (`SCORE`, `DENY`, `KILL`, `PRESERVE`, `PREPARE`, `BOARD_CONTROL`) à partir de l'état de partie,
   **puis** cherche une destination cohérente avec cette intention. Un bot d'entraînement peut
   marcher vers un objectif et tirer sur autre chose sans jamais s'en apercevoir — c'est
   exactement le défaut qui a été corrigé sur `decapitation` le 2026-08-13. Ici, l'intention est
   la contrainte, pas une résultante de poids.
2. **Ciblage par swing espéré**, une seule formule pour les trois :
   `P(kill) × VALUE + VP refusés + menace retirée − overkill`, au lieu des quatre critères
   incompatibles du panel (`_score_efficiency`, `_score_kill_now`, `_score_value_removed`,
   `_score_contester`).
3. **Aucun de leurs paramètres ne vient de `bot_movement_weights.json`.** Un benchmark réglé sur
   le même fichier que les bots d'entraînement finirait par être réglé en même temps qu'eux.

Ce qui les sépare **entre eux** : l'intention qu'ils privilégient à état égal, donc la faute
qu'ils punissent.

#### C.1 `reference_balanced` — l'arbitrage permanent

Aucune intention privilégiée : à chaque activation il compare le gain de marquer, de tuer et de
survivre, et prend le meilleur. Il change de registre en cours de partie sans prévenir.

**Faute punie** : l'agent qui a **un** plan. Un agent entraîné contre une échelle de difficulté à
une dimension apprend une recette ; un adversaire qui alterne les registres la casse.
**Ce qu'il mesure** : la force générale contre une logique jamais vue.

#### C.2 `reference_denial` — le refus de laisser marquer

Il ne cherche pas d'abord à marquer lui-même : il vise à ce que l'agent **ne marque pas**.
Concrètement : contester au dernier moment plutôt que tenir tôt, occuper les accès plutôt que les
zones, retirer le porteur d'objectif juste avant la frontière de phase qui compte les VP.

**Faute punie** : l'agent qui marque **par défaut**, parce que personne ne conteste. C'est le
risque structurel du panel actuel : mesuré le 2026-08-12, les bots empilaient 2,6 à 3,0 escouades
sur 1,7 zone pendant que l'agent en couvrait 2,9 — l'agent n'a jamais eu à défendre un score.
**Ce qu'il mesure** : la sécurisation du score, pas sa production.

#### C.3 `reference_reactive` — la non-stationnarité

Il révise son plan sur ce que l'agent **vient de faire** : change de cible quand une pièce
s'expose, conteste les objectifs tenus par l'adversaire après un échange perdu (CONTEST), bascule en pression quand il décroche au score. Ses
transitions dépendent de l'historique du tour, pas seulement de l'état courant.

**Faute punie** : l'agent exploitable par un adversaire qui s'adapte. C'est le seul des trois qui
préfigure ce que fera le self-play — et donc le seul dont le score prédit quelque chose sur
l'étape E.
**Ce qu'il mesure** : la robustesse à un adversaire non stationnaire.

⚠️ C'est aussi le plus cher à écrire et le plus facile à rater : un bot « réactif » mal fait
oscille entre deux plans sans jamais en exécuter un. Sa mémoire de tour doit suivre le patron déjà
éprouvé du dépôt (marqueur `(episode_number, turn)` de `DecapitationBot._focus_turn`), et un test
doit vérifier qu'il **exécute** un plan sur au moins N activations avant d'en changer.

#### C.4 Complémentarité — mesurée, jamais supposée

Trois benchmarks ne valent trois signaux que s'ils **classent les modèles différemment**. La mesure
du 2026-08-12 dit que les six bots d'entraînement, eux, ne le font pas (ordre strictement
identique d'un modèle à l'autre).

**Critère, à publier à la première évaluation** : évaluer **au moins trois modèles de forces
différentes** (les archives `robust_*` en donnent) contre les trois benchmarks, et publier la
**corrélation de rang** entre les trois classements, plus l'amplitude de chaque benchmark
(écart entre le meilleur et le pire modèle).

- amplitude sous l'incertitude d'échantillon (±5,0 points à 600 épisodes) ⇒ **le benchmark ne
  mesure rien**, quelle que soit sa doctrine — c'est le sort qu'a connu `standoff` (amplitude 0,05
  sur trois agents, supprimé le 2026-08-11) ;
- trois classements identiques ⇒ un signal payé trois fois : le fait est **publié**, la décision de
  garder ou non les trois revient à l'utilisateur.

Ce critère n'est pas une condition pour écrire les trois bots. Il est ce qui empêche de croire
qu'on mesure trois choses pendant deux ans.

#### C.5 Branchement

Nouvelle famille dans `ai/bot_registry.py` (source unique) :
`BENCHMARK_BOT_KEYS = ("reference_balanced", "reference_denial", "reference_reactive")`,
plus leur entrée dans `BOT_DISPLAY_NAMES` et dans `bot_classes()` — le verrou
`tests/unit/ai/test_bot_registry_names.py` interdit déjà aux deux de diverger.

Poids `0.0` dans `bot_eval_weights` (la somme des poids doit rester à `1.0`, contrôle explicite de
`_load_bot_eval_params`), `bot_eval_randomness` renseigné pour chacun — son absence lève, il n'y a
plus de défaut à 0.15 depuis V11 §10.5.

**Test de non-régression obligatoire** : intersection VIDE entre `bot_training.ratios` et
`BENCHMARK_BOT_KEYS ∪ SEALED_HOLDOUT_KEYS`, vérifiée sur les **10 profils** du fichier de config
d'agent (`x1`, `x1_long`, `x1_selfplay`, `x5_append`, `x5_new`, `x5_long`, `x1_debug`, `x5_debug`,
`x1_panel`, `x1_new_bots` — comptés dans le fichier, la mention « 9 profils » du ROADMAP §1 pt 6
date d'avant l'ajout de `x1_new_bots`).

#### C.6 Coût, et il n'est pas négligeable

Un bot présent dans `bot_eval_weights` est **joué à plein budget quel que soit son poids**
(§1.2.a). Trois benchmarks sur `x1_new_bots` (`bot_eval_final = 600`,
`bot_eval_intermediate = 100`, `bot_eval_freq = 5000` sur 50 000 épisodes, soit 10 évaluations
intermédiaires) :

| poste | épisodes ajoutés |
|---|---|
| évaluations intermédiaires | 3 × 100 × 10 = **3 000** |
| évaluation finale | 3 × 600 = **1 800** |
| **total par run** | **4 800** |

Soit **+50 %** sur le budget d'évaluation d'un run à six bots. À arbitrer une fois le premier
chiffre connu : baisser `bot_eval_intermediate` pour les benchmarks seuls est possible (ils ne
pilotent pas la courbe de progression), mais ça demande un budget par bot et non global — ce que
`bot_evaluation.py` ne sait pas faire aujourd'hui (`total_episodes = len(active_bot_names) ×
n_episodes`, ligne 1501). **C'est le seul développement d'infrastructure que l'étape C peut
exiger**, et seulement si le coût mesuré le justifie.

---

### Étape D — `benchmark_floor` : deux étages, et ce qu'un plancher raté veut dire

> ⛔ **`benchmark_floor` A ÉTÉ SUPPRIMÉ DU CODE (2026-08-26, commit `16cf36b1`).** Le paramètre
> `model_gating_min_benchmark_floor`, sa logique de gating dans `ai/training_callbacks.py`, ses
> courbes TensorBoard et ses tests n'existent plus. Deux raisons cumulées : le mécanisme était
> **saturé** — `ai/curriculum.py` le dit verbatim, « les bots de reference sont satures a 1.00,
> donc un plancher pose dessus est franchi par n'importe quel modele et ne separe rien » — et il
> avait déjà été **remplacé** par `evaluate_stage_gate`, un plancher dur posé sur le score contre
> le champion le plus récent, seul étalon dont la force suit celle de l'agent. Il était par
> ailleurs configuré à `0.0` partout, donc inactif.
> Tout le §D ci-dessous décrit donc un dispositif **retiré**. Conservé comme référence de
> conception et pour le raisonnement sur les deux étages, qui reste valable.

> **TRANCHÉ le 2026-08-15** (§0bis). Deux étages : les trois `reference_*` gatent, `tactical` reste
> scellé. **Et un plancher raté n'est pas seulement un modèle refusé : c'est un entraînement à
> revoir** — décision utilisateur, elle commande le §D.3 ci-dessous.

**Le problème qui était posé** : la proposition voulait que le plancher des benchmarks décide.
L'arbitrage du 2026-08-04 dit qu'un holdout qui décide n'est plus un holdout — dès qu'un chiffre
valide un run, on optimise dessus, et la sélection du best robust model est déjà une optimisation.
Les deux besoins sont réels et ne tiennent pas sur le même adversaire.

#### D.1 Conception retenue — deux étages

| étage | membres | dans `combined`/`worst_bot` ? | peut gater ? | rôle |
|---|---|---|---|---|
| Panel d'entraînement | les 6 styles | oui | oui | apprentissage + sélection |
| **Benchmarks** | les 3 `reference_*` | **non** | **oui**, via `benchmark_floor` | généralisation à un adversaire jamais vu, ET critère de décision |
| **Holdout scellé** | `tactical` (gelé §0.55) | non | **jamais** | le seul chiffre sur lequel personne n'a optimisé |

Ce que ça coûte, dit franchement : à partir du moment où `benchmark_floor` gate, la sélection de
modèle optimise indirectement sur les trois `reference_*`. Ils restent un holdout d'**entraînement**
(l'agent ne joue jamais contre eux, il n'apprend pas à les exploiter) mais ils cessent d'être un
holdout de **sélection**. `tactical`, lui, ne bouge pas : il est le témoin, et il reste comparable
à toutes les mesures antérieures depuis son gel du 2026-08-04.

#### D.2 Câblage

Trois familles au lieu de deux, dans `bot_registry` (source unique) :
`SELECTION_BOT_KEYS`, `BENCHMARK_BOT_KEYS`, `SEALED_HOLDOUT_KEYS`. **CINQ sites** lisent
aujourd'hui la partition — `grep -rn "SELECTION_BOT_NAMES\|SELECTION_BOT_KEYS\|HOLDOUT_BOT_KEYS"
--include=*.py ai/ scripts/` hors registre : `training_callbacks.py` 84 (`selection_worst_bot`),
1618 (gate), 1933 (pires cas robustes), 2160 (score robuste), et `metrics_tracker.py` 1879
(`worst_bot_score` TensorBoard). Les cinq lisent la partition, jamais une liste écrite à la main —
c'est la leçon de `metrics_tracker`, qui avait exactement cette liste-là écrite à la main et restée
sur l'ancien panel.

**Métrique** : `benchmark_floor = min(WR sur BENCHMARK_BOT_KEYS)`, publiée en
`00_critical/` à côté de `b_worst_bot_score`, plus `benchmark_mean`.

**Témoin sur le profil actif — ajouté le 2026-08-15.** `tactical` est ABSENT de
`bot_eval_weights` de `x1_new_bots` (vérifié : seuls les six styles y figurent) : `vs_tactical`
n'existe donc pas sur le profil qui sert, et tout le §D.1 reposait sur un chiffre que personne ne
produit. Il y entre à `0.0`, avec son `bot_eval_randomness`. Coût, par §1.2.a (poids 0 = budget
plein) : +600 à l'évaluation finale, +100 × 10 intermédiaires — **+1 600 épisodes par run de
50 000**, le prix du témoin tant que le budget par bot (§4.C.6) n'existe pas.

**Seuil** : **posé après la première mesure** (D8). Protocole : évaluer le modèle robuste courant
contre les trois benchmarks à 600 épisodes, lire le plancher, poser le seuil d'entrée en self-play
à ce plancher **+ une marge documentée**, pas à 0,80. Le chiffre s'écrit avec la mesure qui le
fonde, à côté de lui — c'est la règle qu'ont apprise les `_justification` de
`bot_movement_weights.json`, et le §12.7 défait du chantier panel dit ce qu'il en coûte de ne pas
la suivre.

**Ajout au gate existant** : une cinquième ligne `benchmark_floor` dans `_evaluate_model_gate`, sur
le même patron que `vs_control` — seuil `0.0` = désarmé explicitement, seul désarmement admis.

#### D.3 Un plancher raté est un diagnostic sur l'ENTRAÎNEMENT, pas seulement un modèle refusé

**Décision utilisateur du 2026-08-15.** Si l'agent bat les six bots d'entraînement et échoue contre
un benchmark, ce n'est pas un accident de sélection : c'est que **ce qu'il a appris ne se transfère
pas**. Le refuser est nécessaire ; relancer le même entraînement est vain, parce que l'entraînement
est précisément ce qui a produit le trou.

**(a) Ce qu'on regarde, c'est le COMPORTEMENT de l'agent — pas le benchmark.**
La question n'est pas « lequel des trois a échoué » mais « **qu'est-ce que l'agent a mal fait** » :
s'est-il fait détruire ? a-t-il trop peu joué les objectifs ? a-t-il gagné les combats et perdu la
partie ? A-t-il marqué tôt puis tout rendu ? Ensuite seulement on **compare cette même mesure**
entre les benchmarks et les bots d'entraînement. C'est cette comparaison qui donne le levier, et
non l'identité du benchmark en échec.

⚠️ Prérequis : le profil comportemental par adversaire, qui **n'existe pas aujourd'hui** — cf. §D.4,
et c'est la pièce qui rend tout ce paragraphe exécutable plutôt que rhétorique.

**(b) La partition qui donne le levier.**

| observation | lecture | levier |
|---|---|---|
| même comportement fautif **contre les bots d'entraînement**, mais l'agent gagne quand même | les bots ne PUNISSENT pas cette faute, donc rien n'a jamais appris à l'agent qu'elle en était une | **RÉCOMPENSE** — le signal ne pénalise pas ce qu'il devrait |
| comportement **bon contre les bots, fautif contre le benchmark** | l'agent a appris une réponse conditionnée à ce que font les bots ; un adversaire qui fait autrement la casse | **CURRICULUM** — `bot_training.ratios`, jitter (§4.B), gains de capacité (§4.A) |
| comportement fautif **partout**, et l'agent perd **partout** | ce n'est pas un défaut de généralisation, c'est un défaut de NIVEAU | ni l'un ni l'autre : durée de run, hyperparamètres, ou une tranche V11 manquante |

La troisième ligne n'est pas du remplissage : sans elle, un modèle simplement faible se lirait comme
une non-généralisation, et on corrigerait un curriculum qui n'a rien fait de mal.

**(c) La détection porte sur la PERSISTANCE, pas sur l'incident.**
Un plancher raté sur une évaluation isolée est du bruit (±5,0 points à 600 épisodes par adversaire,
davantage en intermédiaire). Le signal est la conjonction : `benchmark_floor` sous le seuil sur `N`
évaluations consécutives **pendant que `combined` progresse** — l'agent devient meilleur contre ce
qu'il connaît et pas contre ce qu'il ne connaît pas. Le run est alors déclaré **non généralisant** :

- compteur dédié dans `BotEvaluationCallback`, à côté de `gating_history` qui tient déjà
  l'historique PASS/FAIL ;
- courbe `00_critical/` explicite, message terminal qui **nomme le benchmark** et le nombre
  d'évaluations concernées, **plus l'écart de profil** qui a servi au diagnostic (§D.4) ;
- clé de config `stop_on_no_generalization` (nombre d'évaluations, `0` = désarmé) — **valeur
  obligatoire dans chaque profil, pas de défaut** : au régime mesuré, laisser tourner un run de
  50 000 épisodes qui ne généralisera pas coûte jusqu'à 20 h de machine pour un modèle qu'on
  refusera de toute façon.

**(d) UN SEUL LEVIER PAR RUN — contrainte de méthode, pas de préférence.**
Les deux leviers de (b) ne se tirent **jamais dans le même run**. C'est déjà une décision datée du
chantier panel (§3 pt 5) : `ai/reward_mapper.py` a été explicitement tenu hors de la refonte des
bots parce que corriger la récompense en même temps que les adversaires rend les deux effets
impossibles à démêler — « ce qui viderait de son sens tout ce protocole ». La boucle de diagnostic
utilise les deux leviers ; elle ne les utilise pas simultanément.

⚠️ **Signal déjà connu, à traiter le jour où le levier RÉCOMPENSE est tiré** : `reward_mapper.py`
porte le **même proxy faux** (`max(NB × DMG)` d'une seule arme) que la refonte des bots a corrigé à
la racine — ni jet pour toucher, ni Force contre Endurance, ni AP contre sauvegarde, ni nombre de
figurines. Il y a donc déjà une récompense fausse en attente, indépendamment de tout benchmark.

**(e) Hygiène de la boucle** — pas un défaut de conception, une règle à tenir.
Itérer « mesurer → corriger → re-mesurer » de nombreuses fois **est** une descente de gradient à la
main sur les benchmarks, même quand chaque correction est justifiée séparément. Deux garde-fous
suffisent :

1. **`tactical` est le témoin.** Scellé, gelé depuis le 2026-08-04, il ne bouge sous aucune
   correction. Si les corrections successives font monter les `reference_*` pendant que
   `vs_tactical` stagne, c'est qu'on optimise les benchmarks et non la compétence. Rien d'autre ne
   peut le dire.
2. **Chaque correction est CONSIGNÉE** : date, observation qui l'a déclenchée (l'écart de profil,
   pas seulement le win-rate), levier tiré, et l'avant/après sur les trois `reference_*`, les six
   bots ET `tactical`. Sans ce journal, la troisième correction ne saura plus si les deux premières
   ont servi — c'est ce que les `_justification` de `bot_movement_weights.json` tiennent déjà pour
   les poids, et pour la même raison.

⚠️ **Coût de la boucle** : un tour est dominé par le run (4 h 01 pour 10 000 épisodes, cf. AI_TRAINING.md §run 2026-08-10). Ce n'est pas
une boucle qu'on itère à la journée — d'où l'importance de (c) : détecter tôt qu'un run ne
généralisera pas vaut plus cher que le détecter finement.

#### D.4 Le profil comportemental par adversaire — l'instrument qui manque

**Constat, vérifié dans le code le 2026-08-15.** `_eval_worker_task` (`ai/bot_evaluation.py` 953)
retourne `wins` / `losses` / `draws`, les ventilations par faction / siège / roster, les troncatures,
et `shoot_stats`. **Aucune donnée de jeu** : ni VP, ni zones tenues, ni pertes subies ou infligées,
ni charges, aucune courbe par tour. Et `results["{bot}_shoot_stats"]` (1594) n'a **aucun
consommateur** dans tout le dépôt (`grep -rn "shoot_stats" --include=*.py .` → produit puis jeté).

Les métriques comportementales qui existent (`02_combat/*`, contrôle de zone, VP) viennent de la
boucle d'**entraînement**, tous adversaires confondus dans le même agrégat : elles ne se ventilent
pas par bot non plus.

⇒ **Aujourd'hui, « s'est-il fait détruire ? a-t-il trop peu joué les objectifs ? » est une question
sans instrument.** Le §D.3 en dépend entièrement.

**Ce qui est publié, par adversaire** — le minimum pour trancher la partition de D.3.b :

| grandeur | pourquoi elle est là |
|---|---|
| VP par tour | « marquer tôt puis tout rendre » ne se voit pas sur le VP final |
| zones tenues par tour | la seule voie de victoire du format (§12.1 : 0 victoire par élimination sur 600 parties) |
| pertes subies et infligées (figurines **et** VALUE) | « s'est-il fait détruire » ; la VALUE parce que c'est elle qui départage (`determine_winner_with_method`) |
| charges déclarées / réussies | le seul geste qui immobilise, et l'aspect que `alpha` teste |
| tirs pris / opportunités | `shoot_stats` existe déjà, il suffit de le PUBLIER au lieu de le jeter |
| tours joués | une partie qui finit au tour 3 ne se compare pas à une qui va au bout |

**Deux exigences de forme, sans lesquelles le profil ment :**

- **DES DEUX CÔTÉS.** « L'agent s'est fait détruire contre `reference_denial` » ne dit rien tant
  qu'on ignore si ce bot tue plus par construction. Ce qui s'interprète, c'est l'**écart** entre le
  profil de l'agent et celui de son adversaire sur les mêmes épisodes. L'évaluation voit les deux,
  ça ne coûte rien de plus.
- **VENTILÉ PAR ISSUE.** Une moyenne sur 600 épisodes peut recouvrir deux populations : gagner
  largement la moitié du temps et se faire écraser l'autre moitié rend le même profil moyen qu'un
  jeu médiocre partout — et les deux appellent des corrections opposées. Le décompte sépare déjà
  victoires / défaites / nuls ; le profil suit la même partition.

**Conception.**

- Relevé **par épisode**, agrégé au même endroit et selon le même patron que `faction_stats` /
  `seat_stats` / `roster_stats` : **un seul site d'écriture**, sur le modèle de `_count_episode` —
  sa docstring dit pourquoi (deux sites incrémentant le même seau divergent).
- ⚠️ **JAMAIS un second oracle.** Les valeurs se LISENT sur les accesseurs du moteur, ceux-là mêmes
  dont vivent les métriques d'entraînement ; elles ne se recalculent pas dans l'évaluation. C'est le
  mode d'échec le plus documenté du dépôt — le comptage d'objectif des bots, corrigé le 2026-08-12,
  tranchait la présence sur l'hexe-centre pendant que le moteur comptait l'empreinte de socle et
  retirait les escouades battle-shocked : deux réponses à la même question, divergentes dans les
  deux sens.
- Un couple (adversaire, grandeur) **sans épisode joué n'est pas publié** — même règle que
  `_compute_bot_win_rates` : « un 0.0 y serait un score inventé ».
- Publication : `bot_eval/profile/<bot>/<grandeur>` en TensorBoard, dump lisible au rapport de fin
  de run, et report dans `results_at_promotion` du `policy.json` quand la league existera (§E.2).
- `shoot_stats` : soit il entre dans le profil, soit il est **supprimé**. Une donnée produite,
  transportée à travers la frontière de process et jamais lue est un faux témoin — elle donne
  l'impression qu'un aspect est instrumenté alors qu'il ne l'est pas.

**Coût** : la collecte est une lecture d'état en fin d'épisode, sur des épisodes **déjà joués** —
aucun épisode supplémentaire, aucun run supplémentaire. C'est du câblage.

**Tests** : profil présent pour chaque adversaire du panel · deux côtés renseignés · ventilation par
issue dont la somme redonne `wins + losses + draws` · un adversaire sans épisode n'a pas d'entrée
(et non une entrée à zéro) · les valeurs lues coïncident avec celles du moteur sur un épisode
fabriqué (le verrou anti-second-oracle) · `shoot_stats` a un consommateur ou n'existe plus.

---

### Étape E — league historique (pool de champions figés)

**Prérequis dur** : avoir exécuté `x1_selfplay` **une fois** (§1.2.e). Un premier run qui est aussi
son premier test d'intégration ne se généralise pas avant d'avoir tourné. Ce prérequis est un
prérequis d'**exécution**, pas de conception : tout ce qui suit s'écrit sans lui.

**Ce qui existe déjà et ne se réécrit pas** : rampe de ratio (`_compute_self_play_ratio_for_episode`),
warmup, publication atomique du snapshot (`_publish_self_play_snapshot`, brouillon + `os.replace`),
rechargement par mtime, tirage d'adversaire par épisode, `predict(action_masks=…)` sur le modèle
figé, et le refus explicite hors chemin rotation. **Une league n'est pas un mécanisme nouveau :
c'est ce mécanisme-là avec N membres au lieu d'un.**

**Ce qui manque, exactement** : `opponent_mix` ne connaît qu'**un** chemin de snapshot, republié en
place — donc l'adversaire précédent est détruit à chaque republication.

> ✅ **COMBLÉ le 2026-08-22** ([bot.md#league](../Roadmap/bot.md#league)). `opponent_mix` porte
> `pool`, une liste pondérée d'adversaires FIGÉS, et la republication a été retirée (plus rien
> ne l'écoutait). Deux écarts avec le plan ci-dessous : le pool est réalisé par la répartition
> des ENVIRONNEMENTS et non par un tirage par épisode (un membre par worker, chargé une fois —
> l'empreinte mémoire reste celle d'un seul modèle figé par processus), et il n'y a ni PFSP ni
> cache LRU. `_compute_self_play_ratio_for_episode` s'appelle désormais
> `_compute_pool_ratio_for_episode` et délègue à `ai/curriculum.ramped_ratio`.

#### E.1 Disposition sur disque

```
ai/models/ArmageddonAgent/league/
  champions/
    P0/  model.zip  model_vec_normalize.pkl  model_run_state.json  policy.json
    P1/  …
  exploiters/
    E1/  model.zip  …  policy.json
  matchup_stats.json          ← écrit par l'évaluation, lu par le sampler (§F)
  league.json                 ← index : membres, type, génération, statut
```

- **Un membre = un DOSSIER, jamais un fichier.** Le `.zip` seul ne suffit pas : `ai/model_artifacts.py`
  est déjà la source unique de la liste des compagnons, et sa docstring dit pourquoi — un modèle
  chargé avec les statistiques de normalisation d'un autre run **mesure autre chose**. C'est le
  piège n°1 d'une league, et il est silencieux. La copie passe par
  `copy_model_with_companions`, jamais par un `shutil.copy` du zip.
- **`league/` est en écriture SEULE-AJOUT.** Aucun chemin de code n'y écrase ni n'y supprime un
  membre existant. Un test le vérifie en tentant la promotion d'un `policy_id` déjà présent : elle
  doit lever, pas remplacer.
- **`league/` n'est pas dans `config/`.** Les JSON de `config/` sont relus **à chaud** par les
  évaluations (ROADMAP §10 pt 4) : y poser des statistiques de league ferait changer un run pendant
  qu'il tourne.

#### E.2 Métadonnées — `policy.json`, schéma complet

```
{
  "schema_version": 1,
  "policy_id": "P3",
  "type": "champion",                    // champion | exploiter
  "generation": 3,
  "parent_policy": "P2",                 // poids dont il est parti
  "target_policy": null,                 // exploiter seulement : la cible figée
  "training_config": "x1_league",        // profil du run qui l'a produit
  "training_seed": 12345,
  "episodes_trained": 50000,
  "created_at": "2026-…",                // horodatage, jamais dérivé du mtime
  "model_md5": "…",                      // ce que `bot_zone_direct.py` a appris a coûté cher
  "obs_size": 16659,                      // refus de chargement si l'observation a changé de taille
  "results_at_promotion": {
    "bots":       { "racer": 0.63, … , "combined": 0.74, "worst": 0.63 },
    "benchmarks": { "reference_balanced": …, "…denial": …, "…reactive": …, "floor": … },
    "league":     { "P0": …, "P1": …, "P2": …, "mean": …, "worst": … },
    "sealed":     { "tactical": … }
  }
}
```

Écriture par `shared/json_atomic.py` — brouillon publié par `os.replace`, pour la même raison que
`bot_zone_direct.py --json-out` : un run interrompu ne doit pas détruire le relevé précédent.

⚠️ **`obs_size` et `model_md5` ne sont pas décoratifs.** Un champion figé devient inchargeable dès
qu'une tranche V11 change la taille de l'observation — c'est arrivé (199 → 1011, puis 16659) et
c'est annoncé pour les tranches P3-4/P3-5/P3-6 du chemin critique. Sans ce champ, la league se
remplirait de modèles morts qu'on ne découvrirait qu'au chargement, en plein run. Le contrôle est
au **démarrage** du run, sur tous les membres du pool, pas à la première fois qu'on tire le membre.

#### E.3 Câblage

`opponent_pool`, nouveau bloc de config. `opponent_mix` reste lisible (les profils existants ne
bougent pas) ; un profil porte l'un **OU** l'autre, jamais les deux — contrôle explicite au
démarrage, message qui nomme le profil fautif.

```
"opponent_pool": {
  "enabled": true,
  "league_dir": "ai/models/ArmageddonAgent/league/",
  "warmup_episodes": 5000,
  "buckets": { "bots": 0.15, "previous_champion": 0.25, "historical": 0.40, "exploiters": 0.20 },
  "members": { "previous_champion": "P9", "historical": ["P0", …, "P8"], "exploiters": ["E1","E2","E3"] },
  "sampling": { "mode": "pfsp", "target_band": [0.30, 0.70], "min_weight": 0.02 },
  "model_cache_size": 3,
  "device": "cpu"
}
```

- La somme des `buckets` vaut `1.0`, contrôle explicite — même règle que `bot_training.ratios` et
  `bot_eval_weights`, tous deux déjà gardés ainsi. Un bucket à `0.0` est légal (c'est ainsi que la
  phase 1 s'exprime : `bots 0.60`, `previous_champion 0.40`, le reste à zéro) ; un bucket non nul
  dont la liste de membres est vide **lève**.
- **Point d'insertion unique** : `_select_opponent_mode_for_episode` (`env_wrappers.py` ~955), qui
  choisit déjà entre deux modes par tirage sha256. Il passe de « bot ou snapshot » à « bot, ou
  membre M du pool », et `_get_opponent_action` route en conséquence. Le reste du wrapper —
  construction de l'observation, masque, invalidation de la décision après `predict` — ne bouge
  pas : c'est déjà le chemin du self-play, et sa docstring explique pourquoi l'invalidation vit
  dans la signature.
- **Tirage** : bucket puis membre, par `sha256(f"{seed}:{rank}:{episode}:opponent")` (D9). Jamais
  le `random` global, non ensemencé en entraînement (§1.2.d).
- **`min_weight` garantit qu'aucun membre ne disparaît** : c'est le seul détecteur de forgetting.
  Un P0 tiré 2 % du temps coûte peu et dit tout de suite si l'agent a oublié comment le battre.

#### E.4 Cache de modèles — à dimensionner AVANT, pas après

Chaque environnement charge les modèles adverses. À 48 environnements et 10 champions, un cache
non borné charge jusqu'à 480 modèles en mémoire. Le rechargement par mtime actuel suffit pour UN
snapshot ; il faut ici un **LRU borné par `model_cache_size`**, avec le coût assumé : un membre
évincé se recharge (~quelques centaines de ms), donc un cache de 1 sur un pool de 10 paierait un
chargement à presque chaque épisode.

À mesurer au premier run de league, et à écrire à côté du chiffre : temps de chargement d'un
modèle, taux d'éviction, `perf/` correspondant. Le dimensionnement par défaut (`3`) est un point de
départ, pas un réglage.

#### E.5 Promotion d'un champion

La promotion n'est pas un effet de bord d'un run qui se termine : c'est une **décision gardée**.
Elle étend `BotEvaluationCallback`, qui porte déjà la sélection du best robust model :

1. le run se termine (budget ou gates atteints) ;
2. le modèle candidat est le **best robust model** du run, pas le dernier — c'est déjà la
   sémantique de livraison du dépôt ;
3. les quatre gates de promotion (§H) sont évalués sur son évaluation finale ;
4. si tous passent : copie dans `league/champions/P{n}/` avec compagnons + `policy.json`, mise à
   jour de `league.json`. Sinon : rien n'entre dans la league, et le run est déclaré non promu —
   ce n'est pas un échec technique, c'est un résultat.

#### E.6 Tests

- `league/` en écriture seule-ajout : promouvoir un `policy_id` existant lève ;
- compagnons présents et appariés après promotion (le zip seul doit être refusé) ;
- refus au démarrage d'un membre dont `obs_size` diverge, avec le nom du membre dans le message ;
- somme des buckets ≠ 1.0 ⇒ lève ; bucket non nul à liste vide ⇒ lève ;
- `opponent_mix` et `opponent_pool` ensemble ⇒ lève, en nommant le profil ;
- tirage reproductible : mêmes `(seed, rank, episode)` ⇒ même membre, deux exécutions ;
- un membre n'est **jamais** un benchmark ni `tactical` (test croisé sur les trois familles de D) ;
- LRU : un pool plus grand que le cache ne dépasse pas `model_cache_size` chargements simultanés.

#### E.7 Coût

~50 000 épisodes par génération ≈ **20 h** au régime mesuré, plus une évaluation finale qui croît
avec la league (§2.8).

---

### Étape F — échantillonnage PFSP

**Ce qu'il résout** : un pool uniforme fait rejouer P0 aussi souvent que P9. Un adversaire battu à
96 % n'apprend rien au learner ; la matière est entre 30 % et 70 %.

#### F.1 Où viennent les chiffres

Les win-rates courants du learner contre chaque membre sont produits par l'évaluation
(`BotEvaluationCallback`) et écrits dans `league/matchup_stats.json` — **pas** dans `config/`
(§E.1). Format : par membre, `wins`, `total`, `win_rate`, `evaluated_at_episode`. Un membre jamais
évalué n'a **pas** de score : il prend le poids d'amorçage (`min_weight` × un facteur documenté),
jamais un 0,5 inventé.

#### F.2 Pondération

`poids(m) ∝ f(win_rate(m))`, `f` maximale au centre de `target_band` et décroissante vers les
bords, plancher `min_weight` appliqué **après** normalisation. Une seule fonction, testable seule,
sans état.

#### F.3 Abstraction

```
class OpponentSampler:
    def pick(self, seed_material: str) -> OpponentRef      # bucket puis membre, déterministe
    def refresh(self, matchup_stats: dict) -> None         # appelé après chaque évaluation
```

Deux implémentations dès le départ : `UniformSampler` (le comportement d'un pool sans PFSP, qui
sert de **contrôle** dans les tests) et `PfspSampler`. Le wrapper ne connaît que l'interface — c'est
ce qui permet de remplacer la règle par un PFSP complet, ou par un Elo, sans y toucher.

#### F.4 Tests

Ratios de bucket respectés sur N tirages · un membre dans la bande est tiré plus souvent qu'un
membre à 96 % · aucun membre à poids nul (`min_weight` tenu) · membre sans statistique = poids
d'amorçage, jamais 0,5 · `refresh` change les poids et non l'ordre du tirage · déterminisme à
graine égale · `UniformSampler` rend exactement des fréquences uniformes (le contrôle négatif).

---

### Étape G — exploiters

**Définition opérationnelle** : un exploiter est un run d'entraînement **ordinaire** dont
`opponent_pool` n'a qu'un membre à 100 %, plus un callback d'arrêt. Aucun mécanisme nouveau — c'est
la raison pour laquelle E doit être conçu correctement : G en tombe presque gratuitement.

#### G.1 Profil `x1_exploiter`

`bot_training` **absent** (donc `use_bots = False`, dérivé de la config et non d'un nom de
fichier), `opponent_pool.buckets = {"target": 1.0}`, `members.target = "<policy_id>"`,
`total_episodes = 50000`, initialisation des poids depuis `P0` par défaut — configurable, parce que
comparer des exploiters entre générations exige la même initialisation.

#### G.2 Critère d'arrêt

Arrêt si `WR >= 0.70` sur une évaluation dédiée, **ou** budget épuisé. Deux pièges à traiter dans le
code, pas dans le commentaire :

- le seuil se lit sur une évaluation d'un échantillon suffisant : à 100 épisodes, l'erreur-type d'un
  win-rate vers 0,7 vaut ~4,6 points, donc un franchissement à 0,70 est indiscernable de 0,66. La
  cadence et la taille d'évaluation de ce profil sont un **réglage à justifier**, pas un copié-collé
  de `x1` ;
- l'arrêt anticipé fige le modèle **au moment du franchissement**, et c'est ce modèle qui est
  archivé — pas le meilleur robuste, dont la sémantique (moyenne mobile, drawdown) n'a pas de sens
  pour un exploiter dont le but est un pic contre une cible unique.

#### G.3 Métriques

`WR@5k / @10k / @20k / @30k / @50k`, `episodes_to_60`, `episodes_to_70`, `max_WR`, publiées en
TensorBoard **et** dans le `policy.json` de l'exploiter. `episodes_to_70` est la mesure
d'exploitabilité recherchée.

#### G.4 Archivage et réinjection

Gelé dans `league/exploiters/E{n}/`, jamais réentraîné, jamais écrasé (même règle qu'en E.1),
réinjecté comme adversaire par le bucket `exploiters` et pondéré par le même PFSP (§F) : un
exploiter battu à 98 % devient rare mais **ne disparaît pas** — s'il remonte à 67 % dix générations
plus tard, il redevient fréquent tout seul, et c'est le signal de régression.

#### G.5 Le piège d'interprétation, à écrire dans le rapport

« E3 n'a jamais atteint 70 % » **n'est pas** une preuve que P8 est robuste. C'est aussi ce que rend
un exploiter mal initialisé, un budget trop court, un réglage d'hyperparamètres inadapté ou un run
planté. La mesure n'a de sens que **relativement** : elle exige que E1 et E2 aient réussi sous le
même protocole (même initialisation, même budget, même profil). Un tableau
`champion → exploiter → episodes_to_70` dont une ligne vaut `>50k` sans que les autres soient
renseignées ne dit rien.

#### G.6 Tests

Cible figée pendant tout le run (le zip de la cible ne change pas de md5) · 100 % des épisodes
contre la cible, aucun bot ni autre membre · arrêt à 70 % · arrêt au budget · le modèle archivé est
bien celui du franchissement · métadonnées `type: exploiter` et `target_policy` renseignées ·
réinjection comme adversaire et pondération par le sampler.

---

### Étape H — schedule P0 → P10 et gates de promotion

#### H.1 Le schedule est de la CONFIG

Un bloc par génération dans le fichier de config d'agent, repris de la table de la proposition. Ce
qui est du code, c'est la **lecture** du bloc ; les ratios eux-mêmes ne sont jamais en dur.

```
"league_schedule": [
  { "policy_id": "P1", "init_from": "P0", "profile": "x1_league",
    "buckets": { "bots": 0.60, "previous_champion": 0.40, "historical": 0.0, "exploiters": 0.0 } },
  { "policy_id": "P2", "init_from": "P1",
    "buckets": { "bots": 0.40, "previous_champion": 0.40, "historical": 0.20, "exploiters": 0.0 } },
  …
  { "policy_id": "E1", "type": "exploiter", "init_from": "P0", "target": "P3",
    "profile": "x1_exploiter", "max_episodes": 50000, "success_win_rate": 0.70 },
  …
]
```

#### H.2 Les quatre gates de promotion

Une génération n'est **pas** définie par un nombre d'épisodes : elle l'est par le passage des
quatre gates, évalués sur l'évaluation finale du candidat.

| gate | contrôle | seuil |
|---|---|---|
| 1 — champion précédent | le candidat bat significativement Pn−1 | à poser après mesure (D8) ; ordre de grandeur 0,55–0,60, sur un échantillon qui rende l'écart discernable |
| 2 — non-régression league | aucun effondrement contre un ancien champion | écart maximal toléré vs `results_at_promotion` du candidat précédent |
| 3 — non-régression bots | `worst_bot` ne s'effondre pas | réutilise `model_gating_min_worst_bot`, déjà en place |
| 4 — non-régression benchmarks | `ckpt_min` ne baisse pas significativement | remplace `benchmark_floor` (commit 16cf36b1) ; produit par `evaluate_against_checkpoints` dans `ai/bot_evaluation.py` |

⚠️ **Gate 1 et la taille d'échantillon.** À `bot_eval_final = 600` par adversaire, l'erreur-type
d'un win-rate vers 0,55 vaut ~2,0 points. Un gate à 0,55 sur 100 parties (±5,0) accepterait un
candidat réellement à 0,50 une fois sur trois — et une league qui promeut du bruit accumule du
bruit. La taille d'échantillon du gate 1 est un **paramètre de la league**, pas un détail
d'évaluation.

#### H.3 Ce qui est publié à chaque génération

`ckpt_min` et `ckpt_mean` (échelle de checkpoints figés, §R0b — reprennent le rôle de plancher et
de moyenne de généralisation contre des adversaires non saturables), win-rate par membre de league,
`historical_mean`, `historical_worst`, win-rate par exploiter, `exploiters_worst`,
`training_bot_floor`, et score du gate contre Pn−1 (`evaluate_stage_gate` — reprend le rôle de
référence fixe par génération ; la propriété de témoin scellé de `vs_tactical` n'est pas reprise :
aucun équivalent non saturable et hors gate n'existe). Ces courbes sont l'objet même de la league :
sans elles, on paierait 260 heures pour un unique chiffre de fin.

> **TRANCHÉ le 2026-08-27.** `benchmark_floor`, `benchmark_mean` (commit `16cf36b1`) et
> `vs_tactical` (commit `8bb4e42e`) sont supprimés pour saturation — ils mesuraient des adversaires
> battus à ~100 % et ne séparaient plus aucun modèle. Leurs remplaçants, non saturables par
> construction :
>
> | Ancienne courbe | Propriété reprise | Nouvelle courbe | Producteur |
> |---|---|---|---|
> | `benchmark_floor` | plancher contre adversaire jamais vu en entraînement | `ckpt_min` | R0b — `evaluate_against_checkpoints` dans `ai/bot_evaluation.py` |
> | `benchmark_mean` | moyenne de généralisation | `ckpt_mean` | R0b — idem |
> | `vs_tactical` | référence fixe par génération | score du gate contre Pn−1 | `evaluate_stage_gate` dans `ai/curriculum.py` |
>
> Propriété **non reprise** : `tactical` était hors gate et hors sélection — l'optimisation du
> learner ne pesait pas dessus. Le score contre Pn−1 est utilisé en gate, donc la pression est
> directe. C'est la seule perte de signal : aucun équivalent non saturable et non gaté n'existe
> dans le dispositif actuel.

#### H.4 Coût total, à connaître avant de commencer

P1→P10 à 50 000 épisodes ≈ **200 h** · trois exploiters ≈ **60 h** · évaluations en sus, croissantes
avec la league (à P10, une évaluation finale porte 10 champions + 3 exploiters + 6 bots + 3
benchmarks + `tactical` = 23 adversaires × 600 = 13 800 épisodes). **≈ 11 jours machine en continu**,
sur une machine qui porte aussi le chemin critique du ROADMAP.

---

### Ce que le périmètre A→D doit laisser OUVERT pour E→H

C'est la raison d'être de la conception complète ci-dessus : trois points livrés en A→D fermeraient
la league s'ils étaient faits à la légère.

| livré en A→D | ce qui doit être prévu | sinon |
|---|---|---|
| partition à trois familles (`bot_registry`, D) | une 4ᵉ famille `LEAGUE_MEMBER` s'y ajoute sans toucher les 5 consommateurs | la league réintroduirait une liste de bots écrite à la main — le défaut déjà vécu par `metrics_tracker` |
| profil comportemental par adversaire (D.4) | le profil est indexé par **clé d'adversaire**, pas par « bot » : un champion `P3` ou un exploiter `E1` s'y range sans réécriture | la league mesurerait ses matchups en win-rate nu, et le diagnostic de D.3 s'arrêterait à la frontière du self-play — précisément là où il devient le plus utile |
| `ckpt_min` via `evaluate_against_checkpoints` (R0b, D) | les gates de promotion (H.2) réutilisent le même mécanisme de contrôle nommé + seuil | deux systèmes de gates, qui divergeront |
| tirage sha256 dans `BotControlledEnv` (B) | un point d'insertion UNIQUE pour « quel adversaire cet épisode » | le jitter, le self-play et la league tireraient chacun de leur côté |
| écriture de métadonnées (`policy.json`) | le writer atomique existe déjà (`shared/json_atomic.py`) et est utilisé dès A→D pour les relevés | un writer par usage, dont un qui perd un fichier sur run interrompu |

---

## 5. Ordre d'exécution — la conception, elle, est complète

**Conception : A→H, toutes livrées dans ce document.** **Exécution : par tranches**, et ce qui les
sépare est le budget machine, pas un trou de conception.

| Rang | Étape | Tranche | Coût machine | Bloque quoi |
|---|---|---|---|---|
| 1 | **A** — capacités communes | **1** | 0 pour le code, ~6 runs de 60 ép./bot pour rejouer la ligne de base | B |
| 2 | **B** — jitter | **1** | idem | rien |
| 3 | **C** — les 3 benchmarks | **1** | +4 800 ép. par run d'entraînement (§4.C.6) | D |
| 4 | **D.4** — profil comportemental par adversaire | **1** | **0** (lecture d'état sur des épisodes déjà joués) | D.3 |
| 5 | **D** — `ckpt_min` (R0b), gate, partition à 3 familles, détecteur de non-généralisation | **1** | une évaluation dédiée pour poser le seuil | E, H |
| — | *(ROADMAP §1 : P3-4 → P3-6, P4, P5, mesure de référence `x1_long`)* | — | ~20 h | **oui** — l'ordre du travail est là, pas ici |
| 6 | premier run `x1_selfplay` | **2** | ~40 h (100 000 ép.) | E |
| 7 | **E** — league (dossiers, métadonnées, câblage, cache) | **2** | 0 pour le code | F, G |
| 8 | **F** — sampler PFSP | **2** | 0 pour le code | — |
| 9 | **G** — exploiters | **3** | ~60 h (3 × 50 000 ép.) | — |
| 10 | **H** — schedule P0→P10 + gates de promotion | **3** | ~200 h | — |

⚠️ **D.4, E et F ne coûtent rien en machine** : ce sont du code et des tests, verrouillables comme A
et B. Ce qui coûte, c'est de **faire tourner** la league et les exploiters (rangs 9 et 10). Le
chiffre global de « ~11 jours » du §2.8 porte sur ces deux rangs-là, pas sur les étapes qui les
précèdent.

⚠️ **D.4 vient AVANT D bien qu'il soit numéroté après** : le diagnostic de D.3 le lit. L'ordre du
document suit la logique d'exposition (le gate d'abord, l'instrument ensuite) ; l'ordre d'exécution
est celui de ce tableau.

A et B en tête parce qu'ils sont les seuls à ne rien coûter en run et à ne rien bloquer : ils se
livrent, se verrouillent par tests, et le seul prix est la re-mesure de la ligne de base. C et D
ensuite parce que le `benchmark_floor` est **le prérequis de mesure** de tout ce qui suit — sans
lui, la league progresserait sans qu'on sache si elle généralise, et c'est précisément la question
qu'elle est censée trancher.

**Dépendance interne** : C avant D (le plancher n'existe pas sans ses membres), A avant B (le
jitter comportemental porte sur les scalaires que A introduit). A et C sont indépendants et
peuvent se faire dans les deux sens ; C ne touche pas `bot_doctrines.py`.

---

## 6. Risques de régression, nommés

| Risque | Mécanisme | Parade |
|---|---|---|
| La ligne de base 0,7433 devient incomparable | toute capacité ajoutée périme les 8 jeux de poids mesurés | D3/D4 : overrides conservés, gains à 0 = comportement exact ; re-mesure obligatoire au critère de fin de A |
| `decapitation` perd sa doctrine | persistance confondue avec concentration | D5 + test « deux escouades, une seule cible » |
| La persistance domine, disparaît — ou ne fait RIEN | 4 critères, 4 échelles, dont une signée ; toute échelle tirée du champ de candidats est inerte pour `p < 1` | D6 corrigé : règle de conservation à échelle de critère + test de bascule à deux candidats (§2.5) |
| `protect_lead` affaiblit l'évitement d'`endgame` | `×(1−g)` appliqué au seul poids signé du panel (`w_enemy` = −0,35) | transformation consciente du signe (§4.A.1) + test dédié (§4.A.5) |
| Le jitter fuit d'un épisode à l'autre | instances de bots partagées dans un pool de 100 | marqueur d'épisode, patron `_deployment_episode_marker` (déjà mordu deux fois) |
| Le jitter contamine les mesures | `bot_ranking`, `bot_zone_direct`, `bot_evaluation` | il vient de `bot_training`, qu'aucun des trois ne lit — par construction, pas par discipline |
| Un benchmark entre à l'entraînement | copie de `bot_eval_weights` dans `bot_training.ratios` | test d'intersection vide sur les 10 profils |
| Un benchmark ne mesure rien et personne ne le voit | amplitude sous le bruit d'échantillon, cas déjà vécu avec `standoff` | §4.C.4 : amplitude et corrélation de rang publiées dès la première évaluation |
| `reference_reactive` oscille sans exécuter de plan | un bot « réactif » qui change d'avis à chaque activation | mémoire de tour au patron `(episode_number, turn)` + test « N activations sur le même plan » |
| Le profil comportemental devient un SECOND oracle | l'évaluation recalcule VP/zones/pertes au lieu de les lire sur le moteur | §D.4 : lecture des accesseurs du moteur uniquement, + verrou de coïncidence sur un épisode fabriqué. Le comptage d'objectif des bots a déjà divergé ainsi (corrigé le 2026-08-12) |
| Un profil moyen masque deux populations opposées | moyenne sur 600 épisodes mêlant victoires larges et défaites écrasantes | §D.4 : ventilation par issue, somme vérifiée contre `wins + losses + draws` |
| Une correction de récompense et une correction de panel dans le même run | les deux effets deviennent indémêlables | §D.3.d : un seul levier par run — c'est déjà la décision du §3 pt 5 du chantier panel |
| Un modèle de league chargé avec les stats d'un autre | `_vec_normalize.pkl` non apparié | `model_artifacts.copy_model_with_companions`, jamais `shutil.copy` du seul zip |
| La mémoire explose avec la league | N champions × 48 environnements | cache LRU borné, dimensionné avant P3 |
| Le `worst_bot` du gate se met à lire un benchmark | listes de bots recopiées à la main | partition unique dans `bot_registry`, trois consommateurs |

---

## 7. Ce qui appartient à l'utilisateur

**Tranché le 2026-08-14** (reporté en §0bis, ne pas rouvrir) : le périmètre est **B** (A+B+C+D) ;
les benchmarks sont **trois**, avec le critère de complémentarité mesuré du §4.C.4.

**Tranché le 2026-08-15** : `benchmark_floor` **gate** (deux étages, §4.D.1), et un plancher raté
de façon persistante est traité comme un **défaut d'entraînement**, pas comme un modèle malchanceux
(§4.D.3).

**Aucun arbitrage n'est ouvert.** La conception A→H est complète et décidée ; ce qui reste devant
n'est plus une question posée à l'utilisateur mais du travail :

- **écrire** la tranche 1 (A + B + C + D.4 + D) ;
- **mesurer**, une fois C, D.4 et D livrés, le premier `benchmark_floor` — c'est lui qui pose le
  seuil (D8), qui dit si l'agent généralise déjà, et donc ce que la league aurait réellement à
  apporter ;
- **le levier RÉCOMPENSE reste un chantier distinct** (§4.D.3.d) : le jour où le diagnostic le
  désigne, il se tire seul, dans son propre run. `ai/reward_mapper.py` porte déjà le proxy faux que
  la refonte des bots a corrigé — cette correction-là n'attend aucun benchmark pour être due ;
- **calendrier** de la tranche 3 (rangs 8 et 9 du §5, ~200 h + ~60 h) : à placer par rapport au
  chemin critique du ROADMAP, sur la machine qui le porte aussi. C'est une décision de planning,
  pas de conception.

---

## 8. Références

- [`ROADMAP_INDEX.md`](../Roadmap/ROADMAP_INDEX.md) — source unique de l'ordre du travail
- [`Documentation/Reference/training/panel_bots.md`](../Reference/training/panel_bots.md) — panel refondu : décisions,
  mesures, protocole de réglage (§12.13), ligne de base (§12.14)
- [`Documentation/Chantiers/v11/strategie_evaluation.md`](v11/strategie_evaluation.md) — §10.3 progression d'adversaires,
  §10.5 holdout d'adversaire, §10.6 critère de succès et arbitrage du 2026-08-04
- [`Documentation/Chantiers/v11/index_v11.md`](v11/index_v11.md) — §0.55 gel de `tactical`,
  §0.57 rampes par épisode, §0.59 phase 2 self-play
