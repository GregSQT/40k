# V11 — Stratégie d'entraînement et d'évaluation

> ### 🧭 Ce fichier n'est PAS la roadmap
>
> **Ordre du travail, tout projet confondu : [`../ROADMAP.md`](../ROADMAP.md)** — s'y reporter
> pour savoir par quoi commencer, ce qui est bloqué et par quoi.
>
> Ce document porte la **stratégie d'entraînement et d'évaluation** : panel de bots, critères, holdout, MCTS.
> Il fait foi sur le **détail** et l'**état** de V11 ; il ne fait pas foi sur les **priorités**.
> En cas de désaccord sur l'ordre entre ce fichier et le ROADMAP, **le ROADMAP l'emporte** — et
> l'écart se corrige dans la même livraison (règle T2 de CLAUDE.md).

> **Origine.** Section §10 extraite de [`V11_agent_rework.md`](V11_agent_rework.md) le 2026-07-28
> (plan [`V11_refactor_plan.md`](../Implémenté/V11_refactor_plan.md), étape 2). Contenu déplacé **tel quel**,
> aucune réécriture.
>
> **Rôle.** Décision utilisateur du 2026-07-19 : rosters, progression d'adversaires, holdout,
> critère de succès, place du MCTS. L'**état** (fait / à faire) reste dans l'index
> [`V11_agent_rework.md`](V11_agent_rework.md).
>
> **Convention.** Les renvois `§10.x` internes restent en texte nu ; les renvois vers l'index sont
> des liens de fichier.

---
<a id="s10"></a>
## 10. Stratégie d'entraînement et d'évaluation — DÉCISION UTILISATEUR (2026-07-19)

<a id="s10.1"></a>
### 10.1 Contexte et arbitrage

**Objectif métier** : présenter le jeu avec une IA « acceptable » pour obtenir un financement.
La démo oppose un **joueur humain** à l'IA, avec les **armées de la boîte de base**.

**Arbitrage assumé** : l'agent n'apprendra PAS à jouer 40K, il apprendra à jouer **ces deux
rosters**. C'est un choix délibéré pour éviter des semaines de tuning — la spécialisation réduit
la variance de composition, donc le signal d'apprentissage est plus net et la convergence plus
rapide. Pour une démo, un agent spécialisé est indiscernable d'un agent généraliste.

⚠️ **Ne PAS « corriger » ce choix** en réintroduisant de la diversité de rosters : c'est une
décision produit, pas un oubli.

<a id="s10.2"></a>
### 10.2 Rosters et matchups

- **2 rosters** : Space Marines (SM) et Orks — les armées de la boîte de base, donc celles de
  la démo. L'entraînement est aligné sur ce qui sera montré.
- **3 matchups** : SM vs Orks, SM vs SM, Ork vs Ork.
- Les rosters de l'ancienne banque ont été **supprimés volontairement** (commit `43eae95a`,
  370 fichiers) : ils précédaient l'implémentation des escouades, donc obsolètes. Les nouveaux
  sont à créer.

**✅ FAIT le 2026-07-19 — agent `ArmageddonAgent`, scale `500pts`.** Les 2 rosters existent et
le pipeline tourne de bout en bout sur eux (training + évaluation).

| Quoi | Où |
|---|---|
| Rosters agent (training) | `config/agents/ArmageddonAgent/rosters/500pts/training/agent_training_roster_{space_marines,orks}.json` |
| Rosters adversaire (training) | `config/agents/_p2_rosters/500pts/training/opponent_training_roster_{space_marines,orks}.json` — le dossier `500pts` n'existait pas côté P2 |
| Scénario d'entraînement | `config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json` — `agent_roster_ref: "training_random"` (tirage 50/50, **pas de `agent_roster_seed`** : il figerait le tirage agent), `opponent_roster_ref` = liste explicite des 2 fichiers (sinon P2 tire dans tout `_p2_rosters`) |
| Config agent | `ArmageddonAgent_training_config.json` (copie CoreAgent, `roster_pool_schedule.enabled = false` dans les **5** phases) + `ArmageddonAgent_rewards_config.json` (clé racine renommée : le moteur indexe le fichier par nom d'agent, cf. `_build_reward_configs_for_current_units`) |
| Holdout (rosters + scénarios) | `rosters/500pts/holdout_regular/agent_holdout_regular_roster_*.json`, `_p2_rosters/500pts/holdout_regular/opponent_holdout_regular_roster_*.json`, `scenarios/holdout_regular/scenario_bot-0{1..4}.json` (les 4 matchups) |

**Vérifié** : 16 resets → les 4 matchups sortent, plus aucun `roster_pool_schedule produced zero
eligible training rosters` ; training `x5_debug` 8 workers **10/10 épisodes, exit 0** ;
`--eval --test-episodes 2` **exit 0**, combined 0.69 sur 5 bots (le `.zip` du modèle vérifié
intact par md5 — jamais réécrit).

⚠️ **Dette assumée (décision utilisateur 2026-07-19) : le holdout est fait par DUPLICATION des
2 rosters de training**, ce qui **contredit §10.6** (le holdout devait porter sur l'ADVERSAIRE,
pas sur les rosters — ici l'agent est évalué sur les armées qu'il a vues à l'entraînement).
Retenu comme point de départ, à raffiner plus tard. La voie propre est documentée : le résolveur
accepte une ref à **split explicite** (`training/agent_training_roster_orks.json` depuis un
scénario holdout — cf. commentaire « cross-split evaluation P1 holdout vs P2 training »,
`_resolve_roster_ref`), ce qui permettrait de garder les mêmes armées et de ne faire porter le
holdout que sur `TacticalBot`.

⚠️ **Les points des unités Orks sont factices** : `VALUE = 70` pour TOUTES (Boyz, Gretchin,
Warboss, WarTrakk, BigMek…). Le total « 3290 pts » du roster Orks n'a aucun sens, et le moteur
ne valide PAS les points (`scale` n'est qu'un nom de dossier). ~~Déséquilibre réel à surveiller :
**47 figurines côté Orks contre 23 côté SM**.~~ → chiffre périmé : **37 contre 23** depuis [§0.9](V11_agent_rework.md#s0.9)
(10 Gretchin et non 20), et ce n'est pas un déséquilibre mais une identité de faction à 680 vs 680.

**Bug corrigé au passage (registry d'unités)** : `LandSpeederOnslaughtGatlingCannon.ts` et
`LandSpeederHeavyFlamer.ts` déclaraient TOUS DEUX `export class LandSpeeder`. `UnitRegistry`
scanne les `.ts` et indexe par nom de classe → les deux s'écrasaient, `HeavyFlamer` gagnait au
hasard de l'ordre de parcours et la variante Onslaught était **inatteignable**. Classes
renommées (+ `NAME`, `DISPLAY_NAME`) et les deux variantes ajoutées à `config/unit_registry.json`
ET `frontend/public/config/unit_registry.json` (159 → 161). Reste ouvert : les deux pointent vers
`/icons/LandSpeeder.webp`, absent de `frontend/public/icons/` (cosmétique frontend).

**Défaut structurel constaté (non corrigé)** : au TOUT PREMIER run d'un agent neuf, l'évaluation
finale échoue avec `VecNormalize enabled but stats not found: <agent>/vec_normalize.pkl` — le pkl
est écrit à la FIN du run, l'éval tourne avant. CoreAgent ne le voyait jamais (pkl hérité de mai).
Ne se reproduit pas aux runs suivants. Si on veut le traiter : ordonnancer la sauvegarde
VecNormalize avant l'éval finale dans `train.py`.

<a id="s10.3"></a>
### 10.3 Progression d'adversaires (l'axe qui porte la robustesse)

Le risque dominant pour cette démo n'est PAS la composition des armées, c'est **l'écart entre
l'adversaire d'entraînement et l'humain de la démo**. Trois niveaux, qualitativement différents :

| Niveau | Nature | Limite |
|---|---|---|
| 1. Bots scriptés | politique **fixe** | l'agent apprend un exploit ; le win-rate monte sans que la compétence monte |
| 2. Self-play | politique **non-stationnaire** qui s'adapte en retour | les exploits cessent de payer ; risque de catastrophic forgetting |
| 3. MCTS | adversaire qui **cherche** | non exploitable par pattern ; coûteux |

**Plan retenu** : (1) les bots scriptés → (2) introduction **progressive** du self-play →
(3) MCTS **seulement si** la perf mesurée est insuffisante.

⚠️ « Diversité d'adversaires » = diversité des **distributions de comportement**, pas nombre de
classes de bots. Huit bots appliquant la même heuristique gloutonne ne font qu'UN adversaire du
point de vue de l'apprentissage.

**Déjà implémenté, à paramétrer et non à développer — mais UNIQUEMENT sur le chemin rotation**
(`--scenario bot`, cf. §10.4) :
- `training_config.bot_training.ratios` — mélange pondéré de bots
  (`_build_training_bots_from_config`, train.py ~L91 ; 5 classes supportées, toutes pondérées
  dans la config actuelle depuis la refonte du panel du 2026-07-30 — `aggressive_smart` et
  `defensive_smart` ont été supprimés). Configuré dans les 5 phases.
- `training_config.opponent_mix` — self-play progressif : `self_play_ratio_start` →
  `self_play_ratio_end`, `warmup_episodes`, snapshot publié par
  `_publish_self_play_snapshot` (train.py ~L2854) et rechargé par mtime dans
  `BotControlledEnv` (env_wrappers ~L515). Chaîne complète vérifiée : parse → publication →
  rechargement. Le « progressivement » est donc de la config.
  ⚠️ `opponent_mix` n'est PARSÉ que dans `train_with_scenario_rotation` (~L2362) —
  `create_multi_agent_model` l'ignore totalement.

<a id="s10.4"></a>
### 10.4 ⚠️ Écart CODE vs PLAN à corriger avant le premier run

> **Statut 2026-07-19 : ✅ RÉSOLU** — construction d'adversaires mutualisée dans
> `build_training_opponents`, `use_bots` dérivé de la config (`bot_training`) et non du nom de
> fichier, repli aléatoire refusé explicitement par `SelfPlayWrapper` et `make_training_env`.
> Détail et vérification en [§0](V11_agent_rework.md#s0). Le constat ci-dessous est conservé comme historique.
>
> **Constat d'origine — les trois faits ci-dessous ont été
> re-vérifiés dans le code ce jour (aucun n'a bougé). Ce n'est plus théorique : les runs de
> validation de T6-g/T6-h (`x5_debug`, n_envs=8, `training_benchmark`) **et** le run de mise en
> service d'`ArmageddonAgent` (§10.2) sont tous passés par la ligne 2 du tableau — donc **contre
> un P2 aléatoire**. Ces runs prouvent que le PIPELINE tourne (zéro exception, épisodes
> complets) ; ils ne prouvent RIEN sur l'apprentissage. C'est le bloqueur n°1, cf. [§0](V11_agent_rework.md#s0).

**Toute la machinerie d'adversaires (bots pondérés + opponent_mix) n'est câblée que sur le
chemin ROTATION.** L'adversaire réel du chemin single-scenario dépend de `n_envs` et du NOM du
fichier scénario — vérifié branche par branche :

| Chemin | Adversaire d'entraînement RÉEL |
|---|---|
| `--scenario bot` (`train_with_scenario_rotation`) | ✅ `bots=training_bots` pondérés (~L2492, ~L2755) + self-play `opponent_mix` |
| `--scenario <fichier>`, `n_envs > 1` (cas RÉEL : x5_debug = 8) | ❌ `make_training_env` appelé SANS `use_bots`/`training_bots` (~L1782) → `SelfPlayWrapper(frozen_model=None)` → **ACTIONS ALÉATOIRES UNIFORMES, en permanence** (voir ci-dessous) |
| `--scenario <fichier>`, `n_envs == 1`, nom contenant « bot » | `GreedyBot(randomness=0.15)` EN DUR (~L1855) |
| `--scenario <fichier>`, `n_envs == 1`, autre nom (dont `scenario_training_benchmark.json`) | ❌ `SelfPlayWrapper` → **aléatoire permanent** aussi (~L1871) |

**Pourquoi « aléatoire permanent » et pas du self-play** (bug latent distinct, vérifié) :
`SelfPlayWrapper._get_frozen_model_action` (env_wrappers ~L1237) retombe sur
`random.choice(valid_actions)` tant que `frozen_model is None` — et
**`update_frozen_model` n'a AUCUN appelant** dans tout `ai/` (grep = 0 ; le compteur
`frozen_model_update_frequency = 100` de train.py ~L2690 est du code mort). Le « self-play »
du chemin single-scenario n'en est pas : P2 joue au hasard du premier au dernier épisode.
Ne pas confondre avec le VRAI self-play (`opponent_mix` → `BotControlledEnv`, chemin rotation),
qui recharge un snapshot publié sur disque et fonctionne.

Or `--scenario bot` est cassé en amont (rosters, cf. [§0](V11_agent_rework.md#s0)) : le chemin réellement utilisable est
le single-scenario. **Un run x5_debug lancé aujourd'hui entraînerait donc contre un adversaire
ALÉATOIRE, sans qu'aucun log ne le signale** — pire que « spécialisé sur GreedyBot » : un agent
qui n'a jamais rencontré d'opposition cohérente.

C'est la même famille de divergence que **T6-e** (`_turn_step_limit` absent du chemin
single-scenario) : deux chemins de `train.py` qui ont divergé. À traiter de la même façon —
faire passer les deux par la même construction d'adversaires (`training_bots` + `opponent_mix`
dans `make_training_env`, qui accepte DÉJÀ ces paramètres : seul l'appel de
`create_multi_agent_model` ne les transmet pas).

<a id="s10.5"></a>
### 10.5 Évaluation : le holdout porte sur l'ADVERSAIRE, pas sur les rosters

> **Statut 2026-07-19 : ✅ CÂBLÉ** — `TacticalBot` est le holdout, à poids nul et exclu de tout
> signal de sélection ; le défaut silencieux de `randomness` est supprimé. Détail en [§0](V11_agent_rework.md#s0).
> ⚠️ **Affirmation périmée n°4 — voir la table de [§0bis](V11_agent_rework.md#s0bis)** (levée par [§0.7](V11_agent_rework.md#s0.7) : `TacticalBot` a joué 10/10 épisodes). Conservée telle quelle.
> ⚠️ **Non validé runtime** — cf. [§0.3](V11_agent_rework.md#s0.3) (`CC_DMG`). L'archivage des scénarios holdout était à
> faire (voir plus bas). Le constat ci-dessous décrit l'état d'AVANT.

**Constat (historique)** : les bots d'évaluation viennent de `callback_params.bot_eval_weights`
(`_load_bot_eval_params`, bot_evaluation.py ~L168 ; itération sur `eval_weights.keys()` ~L886).
Config actuelle, identique dans les 5 phases : `{control, adaptive, greedy, defensive}` (+
`tactical` à poids nul, le holdout) — un **sous-ensemble strict des bots d'entraînement**
(`bot_training.ratios` = les mêmes 4 + `random`). L'agent n'est donc évalué QUE contre des adversaires rencontrés à
l'entraînement : ce win-rate mesure **l'exploitation apprise, pas la compétence**, et sera
systématiquement optimiste par rapport au comportement face à un humain.

**Décision** : le holdout est un **adversaire réservé à l'évaluation**, jamais vu en
entraînement. Candidat déjà disponible : **`TacticalBot`** — le seul des 8 qui n'est utilisé
nulle part (`evaluation_bots.py` L19 : « unused in training/eval »).

À faire : ajouter `TacticalBot` aux bots d'évaluation, et **garantir qu'il n'entre jamais**
dans `bot_training.ratios` (test de non-régression : l'intersection entre bots d'entraînement
et bots de holdout est vide).

Cela remplace avantageusement le holdout de rosters supprimé, et répond à la question
« 2 ou 4 rosters » : **rester à 2**, et mettre le holdout sur l'axe adversaire.

⚠️ Les 20 scénarios de `holdout_regular/` + `holdout_hard/` pointent vers des rosters supprimés :
ils ne chargent pas. **À archiver** dans `_archive_pre_v11/`. Tant qu'ils sont là,
`bot_eval_scenario_pool: "holdout"` (présent dans les 5 phases de
`CoreAgent_training_config.json`) pointe sur un pool mort.
NB — répartition VÉRIFIÉE des 9 échecs de la suite (cause relue test par test) : **8 viennent
des scénarios TRAINING** (`agent_roster_ref: "training_random"` →
`roster_pool_schedule produced zero eligible training rosters`, candidates=1 : le pool de
rosters d'entraînement est quasi vide depuis le cleanup `43eae95a`) et **1 seul** d'un fichier
de roster holdout absent. Archiver les holdouts n'en fait tomber qu'un : le gros de la
réparation est la création des nouveaux rosters SM/Orks (§10.2) + la mise à jour des scénarios
training qui les référencent.

<a id="s10.6"></a>
### 10.6 Critère de succès (remplace le critère T6 « win-rate vs RandomBot »)

> 🟢 **ARBITRAGE UTILISATEUR DU 2026-08-04 — le holdout est un INDICATEUR, pas le critère.**
> Le volet 1 ci-dessous désignait `TacticalBot` comme adversaire du critère quantitatif. Il ne
> l'est pas et ne le sera pas :
>
> **Le critère quantitatif est `00_critical/a_bot_eval_combined` + `00_critical/b_worst_bot_score`**
> (les deux se lisent ensemble, cf. [§10.5](#s10.5)), plus `00_critical/0_gap_sm-ork` pour
> l'équilibre entre rosters. `vs_tactical` est l'**indicateur de généralisation** : on le cite, il
> ne décide pas.
>
> **Pourquoi** — la raison décisive est la troisième :
> 1. un seul adversaire sur ~100 parties porte ~±5 points d'erreur-type ; `combined` en agrège cinq ;
> 2. `worst_bot_score` alimente déjà le gate de curriculum — deux critères de décision finiraient
>    par se contredire sans règle d'arbitrage ;
> 3. **un holdout qui décide cesse d'être un holdout.** Dès qu'un chiffre valide un run, on
>    optimise dessus — et on perd le seul adversaire dont on puisse dire « jamais rencontré,
>    jamais visé ». C'est exactement ce qui fait sa valeur, y compris devant un financeur.
>
> ✅ **Le win-rate PAR ROSTER, lui, est publié depuis le 2026-08-04** :
> `bot_eval/faction/<faction>/vs_<bot>` (`W40KMetricsTracker.log_faction_bot_win_rates`), dérivé du
> même `_faction_bot_tally` que l'agrégat par faction. ⚠️ Ce sont des win-rates **bruts** incluant
> le holdout ; leur moyenne ne redonne pas `bot_eval/faction/<faction>`, qui est pondéré et
> l'exclut.
>
> ✅ **Le holdout est désaturé et GELÉ depuis le 2026-08-04** ([§0.55](V11_agent_rework.md#s0.55)) :
> `w_objective 2.0`, `vs_tactical` passe de 0.89 à **0.72** et le bot passe de dernier à premier du
> panel. L'indicateur mesure donc enfin quelque chose. Le volet 2 (qualitatif) reste entièrement
> valide.

Le critère historique référençait une capacité qui n'existe plus (holdout de rosters). Nouveau
critère, en deux volets — **les deux sont requis** :

1. **Quantitatif** : **win-rate PAR ROSTER** contre l'adversaire de holdout (`TacticalBot`),
   jamais rencontré à l'entraînement. Par roster, car avec seulement 2 rosters, un effondrement
   sur l'un pendant que l'autre monte est la **signature du catastrophic forgetting** (piège
   listé dans CLAUDE.md) et le seul garde-fou qui reste. Un win-rate agrégé le masquerait.
2. **Qualitatif — décisif pour l'objectif démo** : **absence de comportement absurde** sur N
   parties jouées par quelqu'un n'ayant pas travaillé sur le projet, cherchant activement à
   surprendre l'agent (déploiement inhabituel, tactique atypique).

**Pourquoi le volet 2 n'est pas optionnel** : devant un financeur, ce qui convainc est que l'IA
paraisse *sensée* (elle va sur les objectifs, tire sur des cibles plausibles, charge quand c'est
logique). Un agent à 45 % de victoires qui joue de façon lisible impressionne davantage qu'un
agent à 70 % qui gagne en exploitant une faiblesse de bot et produit un coup absurde au pire
moment. **En démo, l'incohérence coûte plus cher que la défaite.**

<a id="s10.7"></a>
### 10.7 MCTS — deux usages distincts, ne pas les confondre

| Document | Usage | Effet |
|---|---|---|
| `A_faire/MCTS/MCTS_bot_final.md` | MCTS comme **adversaire d'entraînement** (fraction d'épisodes, entre bots et self-play) | améliore l'entraînement → demande un cycle complet de plus |
| `A_faire/MCTS/MCTS_bot_final.md` §20 bis | MCTS **dans l'agent**, à l'inférence | corrige les coups absurdes **sans retraining** |

Pour l'objectif démo (§10.6 volet 2), c'est le **second** qui a le meilleur rapport
effort/résultat : c'est l'absurdité ponctuelle qui coûte cher, et une recherche à l'inférence la
corrige directement. Contre-argument à mesurer : la **latence** en temps réel devant un public —
`MCTS_bot_final.md` §20 bis note lui-même « micro à chaque activation + rollouts = beaucoup
plus lourd » et suggère « macro + feuille value seule » comme prototype. Un MCTS macro peu
profond, ou limité aux seules décisions critiques, suffirait probablement.

**À ne PAS anticiper** : plan B après mesure. Rien ne sert de décider avant de savoir si le PPO
spécialisé suffit.
