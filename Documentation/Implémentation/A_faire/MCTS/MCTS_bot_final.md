# MCTS comme adversaire d’entraînement — spécification finale

> **Fichier** : `Documentation/MCTS_bot_final.md`  
> **Statut** : **référence unique** pour la conception et l’implémentation d’un adversaire MCTS **hors policy PPO**. En cas de divergence avec toute version antérieure, **ce document fait foi** jusqu’à révision explicite.  
> **Contexte** : projet Warhammer 40K — moteur tactique Python, agent **PPO / MaskablePPO**, observation canonique `Documentation/AI_OBSERVATION.md`, pipeline `Documentation/AI_TRAINING.md`.

**Périmètre** : MCTS **uniquement** comme **opposant d’entraînement** sur une **fraction d’épisodes**, entre bots scriptés et self-play (snapshot). **Pas** comme politique PPO, **pas** fusionné au cœur du moteur de règles : le moteur reste la **source de vérité** ; MCTS est un **client** via un **`GameAdapter`**.

### Critères de succès (résumé)

1. **Diversité** : trajectoires d’entraînement plus variées qu’avec seuls bots / self-play, sans effondrer le débit (steps/s).  
2. **Généralisation** : pas de régression sur **holdouts** et métriques robustes du pipeline (`AI_TRAINING.md`) par rapport à un run sans MCTS à **budget de steps équivalent**.  
3. **Cohérence** : transitions adverses uniquement via le même chemin `apply` que les bots ; rollouts documentés côté siège PPO (**§9.3**).  
4. **Config** : mélange d’adversaires **sans ambiguïté** (normalisation §4.4) ; pas de fallback silencieux si MCTS indisponible ou budget dépassé mal défini (**§4.6**).  
5. **Validation** : toute montée de fraction MCTS validée par **A/B** et critères du **§16** — le gain learning n’est **pas** garanti par la spec seule.

---

## Table des matières

1. [Résumé exécutif](#1-résumé-exécutif)  
2. [Objectifs, non-objectifs et sièges](#2-objectifs-non-objectifs-et-sièges)  
3. [Place dans la stack](#3-place-dans-la-stack)  
4. [Lien avec `opponent_mix` et normalisation](#4-lien-avec-opponent_mix-et-normalisation)  
5. [Périmètre des décisions : macro vs micro](#5-périmètre-des-décisions--macro-vs-micro)  
6. [Interface `GameAdapter`](#6-interface-gameadapter)  
7. [État abstrait (optionnel)](#7-état-abstrait-optionnel)  
8. [Algorithme : UCT, expansion, valeur de feuille, rétropropagation, choix racine](#8-algorithme--uct-expansion-valeur-de-feuille-rétropropagation-choix-racine)  
9. [Politique de rollout et modèle du joueur PPO](#9-politique-de-rollout-et-modèle-du-joueur-ppo)  
10. [Configuration JSON](#10-configuration-json)  
11. [Intégration logicielle](#11-intégration-logicielle)  
12. [Arborescence cible `ai/mcts/`](#12-arborescence-cible-aimcts)  
13. [Performance et scalabilité](#13-performance-et-scalabilité)  
14. [Métriques et évaluation (A/B)](#14-métriques-et-évaluation-ab)  
15. [Risques et mitigations](#15-risques-et-mitigations)  
16. [Validation empirique (hypothèses)](#16-validation-empirique-hypothèses)  
17. [Phases de livraison P0–P4](#17-phases-de-livraison-p0p4)  
18. [Glossaire](#18-glossaire)  
19. [Références croisées](#19-références-croisées)  
20. [Annexe A — PUCT / priors (optionnel)](#20-annexe-a--puct--priors-optionnel)  
21. [Historique documentaire](#21-historique-documentaire)

---

## 1. Résumé exécutif

Le **Monte Carlo Tree Search (MCTS)** est un **module d’adversaire** branché sur la **même boucle d’entraînement** que les bots et le self-play : sur une fraction d’épisodes, le siège adverse choisit ses actions par **recherche arborescente** (sélection UCT + simulations + rétropropagation), au lieu d’une heuristique fixe ou d’une policy réseau figée.

**Invariants** : la **policy apprise** reste **MaskablePPO** sur l’**observation canonique** ; le **moteur** est la seule source de vérité des règles ; MCTS **ne produit pas** de gradient. La valeur pour PPO réside surtout dans une **diversité de trajectoires** contrôlée et un adversaire **localement cohérent** — sous réserve que les **rollouts** modélisent correctement les **deux** joueurs (voir §9.3) et que l’**évaluation** ne se limite pas au seul winrate contre MCTS (voir §14).

**Critère de succès principal pour PPO** : amélioration ou maintien de la **généralisation** (holdout, suites de bots, métriques robustes du pipeline), **pas** seulement le winrate contre MCTS — ce dernier peut monter **sans** traduire une politique transferable.

---

## 2. Objectifs, non-objectifs et sièges

### 2.1 Objectifs

| ID | Objectif | Détail |
|----|----------|--------|
| O1 | **Diversité des trajectoires** | Réduire la sur-spécialisation aux bots et à la méta auto-induite du self-play pur. |
| O2 | **Adversaire « recherche »** | Explorer localement un sous-arbre d’actions sans modifier la politique PPO. |
| O3 | **Contrôle du coût** | Budget (simulations, profondeur, abstraction) comme **paramètre d’entraînement** borné. |
| O4 | **Cohérence moteur** | Transitions uniquement via les **mêmes primitives** que le reste de l’entraînement. |
| O5 | **Observabilité** | Métriques dédiées (latence, part d’épisodes, qualité rollouts) pour calibrer les phases P0–P4. |

### 2.2 Non-objectifs

| ID | Non-objectif | Justification |
|----|--------------|---------------|
| N1 | **MCTS comme tête de politique PPO** | Pas de gradient depuis MCTS ; l’apprenant reste le MLP MaskablePPO. |
| N2 | **MCTS dans `engine/`** | Aucune UCT/rollout dans le moteur au titre des règles. |
| N3 | **Optimalité Nash / niveau expert** | Budget et rollout limitent la force ; objectif prioritaire = **diversité + coût maîtrisé**. |
| N4 | **Micro-action complète à chaque nœud** par défaut | Branchement trop large pour le throughput usuel ; viser **macro** ou sous-ensemble. |
| N5 | **Remplacer le self-play** | MCTS est **complémentaire** (fraction d’épisodes), sauf étude explicite. |
| N6 | **Fusionner MCTS avec l’observation / masque PPO** | Seul l’**adversaire** utilise MCTS ; le pipeline PPO inchangé. |

### 2.3 Ce que MCTS n’est pas

MCTS n’est **pas** un « super bot » au sens d’une heuristique monolithique : c’est un **algorithme de recherche** (arbre + UCT/PUCT + simulations). Des **heuristiques** et une **politique de rollout** restent **à l’intérieur** des simulations (uniforme, greedy, ε-greedy, snapshot figée, etc.).

### 2.4 Hypothèse de conception (H1)

L’adversaire MCTS est invoqué lorsque le **siège adverse** agit, selon la même mécanique de sélection que les autres adversaires (ex. au `reset`), avec une distribution documentée compatible avec `opponent_mix` / `mcts_opponent` (§4).

### 2.5 Invariants siège (seat-aware)

Le projet peut utiliser le **seat-aware training** (`Documentation/AI_TRAINING.md`). **Règles** :

- MCTS décide **toujours** pour le **joueur adverse** dans l’épisode (celui **non** contrôlé par la policy PPO en train).  
- Le **nœud racine** de la recherche correspond à une décision **du siège adverse**, pas du siège PPO.  
- L’adaptateur expose `current_player` pour que les rollouts alternent correctement les camps lorsque la simulation le requiert.

---

## 3. Place dans la stack

### 3.1 Schéma ASCII

```
                    ┌─────────────────────────────────────┐
                    │  Stable-Baselines3 / MaskablePPO    │
                    │  Policy + Value sur obs canonique   │
                    └──────────────────┬──────────────────┘
                                       │ actions apprenant
                                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  VecEnv / W40KEngine + wrappers (récompenses, masques, logging)          │
│  Un siège = agent contrôlé ; l’autre = adversaire                        │
└──────────────────────────────────────────────────────────────────────────┘
         │                                    │
         │ tour apprenant                     │ tour adverse
         ▼                                    ▼
   ┌─────────────┐              ┌──────────────────────────────┐
   │  Masques +  │              │  Sélection type d’adversaire │
   │  prédiction │              │  (par épisode / match)       │
   └─────────────┘              └──────────────┬───────────────┘
                                             │
       ┌──────────────┬─────────────────────┼─────────────────────┐
       ▼              ▼                     ▼                     ▼
 ┌──────────┐  ┌──────────┐        ┌──────────────┐      ┌─────────────┐
 │ Bot      │  │ Bot      │        │ MCTS         │      │ Self-play   │
 │ scripté  │  │ (autre)  │        │ (ce doc)     │      │ (snapshot)  │
 └────┬─────┘  └────┬─────┘        └──────┬───────┘      └──────┬──────┘
      │           │                     │                     │
      └───────────┴─────────────────────┴─────────────────────┘
                                        │
                                        ▼
                          ┌─────────────────────────────┐
                          │  GameAdapter → moteur W40K  │
                          │  (transitions légales)      │
                          └─────────────────────────────┘
```

MCTS vit au **même niveau** que « action bot » ou « inférence snapshot self-play », pas dans le cœur du moteur.

### 3.2 Flux d’un épisode (rappel)

1. Reset scénario → état initial.  
2. Tant que non terminal : si tour **PPO**, policy + masque puis `step`.  
3. Si tour **adversaire MCTS** : construire l’adaptateur depuis l’état courant → boucle MCTS (budget N) sur **clones** → action choisie → **un seul** `apply` « officiel » sur le fil réel puis `step` (pas de mutation de l’état réel pendant la recherche).  
4. **Récompenses** et **terminaison** : inchangées par rapport aux autres adversaires.

### 3.3 Rôles par couche

| Couche | Rôle |
|--------|------|
| **PPO** | Apprend depuis *(obs, action, reward, …)* ; MCTS = boîte noire produisant des actions légales. |
| **Env** | Orchestre ; appelle l’opposant sans connaître UCT. |
| **MCTS** | Simulations sur **clones** via `GameAdapter`. |
| **Moteur** | Aucune dépendance à MCTS. |

### 3.4 Chemin d’exécution : VecEnv / moteur (Python) vs API HTTP

En **entraînement**, les transitions utilisent typiquement le **VecEnv**, les wrappers et le moteur en **appels Python directs** dans le processus worker. Une **API HTTP** (ex. Flask pour l’UI ou des services) **n’est pas** le chemin obligatoire pour un pas de jeu dans la boucle PPO. Le **`GameAdapter`** MCTS doit s’aligner sur le **même chemin** que les bots (**env / engine** en Python), sauf architecture **explicitement** imposée et documentée ailleurs.

---

## 4. Lien avec `opponent_mix` et normalisation

### 4.1 État actuel (référence)

`config/agents/<Agent>/<Agent>_training_config.json` peut définir `opponent_mix` avec notamment : `enabled`, `self_play_ratio_start`, `self_play_ratio_end`, `warmup_episodes`, `snapshot_model_path`, `snapshot_update_freq_episodes`, `self_play_snapshot_device`, `self_play_deterministic`. Chargement décrit dans `Documentation/AI_TRAINING.md` et `ai/train.py`.

### 4.2 Troisième mode : comparaison

| Dimension | Bot scripté | MCTS | Self-play |
|-----------|-------------|------|-----------|
| Origine des actions | Heuristique | Recherche + rollout | Policy NN figée |
| Coût CPU | Faible | Élevé (réglable) | Moyen (inférence) |
| Diversité | Moyenne (biais fixe) | Élevée si rollout riche | Dépend de la méta PPO |

### 4.3 Extension schéma : deux familles

| Option | Description |
|--------|-------------|
| **A** | Étendre `opponent_mix` avec des clés `mcts_*` (ratios, budget, etc.). |
| **B** | Bloc parallèle `mcts_opponent` au même niveau ; tirage documenté qui combine bot / MCTS / self-play. |

À trancher en implémentation ; **une seule** source de vérité pour le tirage (pas de défaut implicite qui masque une part manquante — erreur explicite si config incomplète).

### 4.4 Normalisation des parts (obligatoire à figer)

Deux modélisations valides **si documentées** :

| Modèle | Description |
|--------|-------------|
| **Global** | \(p_{\text{bot}} + p_{\text{mcts}} + p_{\text{self}} = 1\) à chaque épisode (éventuellement interpolé dans le temps). |
| **Hiérarchique** | Ex. tirer d’abord self-play vs non-self-play, puis parmi non-self-play tirer bot vs MCTS. |

Les deux sont acceptables ; l’implémentation doit **rejeter** une config ambiguë ou sous-spécifiée.

### 4.5 Cohérence temporelle

Les ratios peuvent dépendre du **numéro d’épisode** (comme `self_play_ratio_*`). Pour MCTS : part **constante** ou **décroissante** lorsque le self-play augmente (moins besoin de diversité externe). **Logger** les courbes effectives (TensorBoard / métadonnées de run).

### 4.6 Règles d’ingénierie

1. **Warmup** : MCTS exclu ou non pendant `warmup_episodes` — **paramètre explicite**.  
2. **Déterminisme** : `mcts_deterministic` / graines de rollout et tie-break UCT.  
3. **Pas de fallback silencieux** : si MCTS est sélectionné mais indisponible → **erreur explicite**, pas de bascule bot implicite.  
4. **Dépassement budget temps** : politique **explicite** (erreur, réduction de budget documentée, ou arrêt avec log) — **pas** de « première action légale » silencieuse comme comportement par défaut (alignement règles projet).

### 4.7 Non-stationnarité

La policy PPO **évolue** pendant l’entraînement : le « monde » vu par MCTS (via rollouts ou stand-in) **n’est pas fixe**. Surveiller l’**eval** et les holdouts ; **décroître** la part MCTS en fin de run si les métriques utiles se dégradent (voir aussi §15).

---

## 5. Périmètre des décisions : macro vs micro

### 5.1 Micro

À chaque **activation** adverse, MCTS choisit dans l’espace isomorphe au masque MaskablePPO pour ce pas. **Très coûteux** ; réservé prototypes, eval, ou budgets extrêmement bas.

### 5.2 Macro (défaut recommandé)

MCTS ne décide qu’à des **points espacés** (ex. début de tour / phase, ou intention stratégique). Le bloc *macro intent* dans `Documentation/AI_OBSERVATION.md` peut servir de **vocabulaire** sémantique (sans imposer le même encodage vectoriel). Viser **K petit** (souvent K ≤ 8–16).

### 5.3 Politique auxiliaire

Entre deux décisions MCTS, l’adversaire joue via une **politique auxiliaire** : bot existant (`greedy`, `defensive`, …), uniforme masquée, ou (hors v1) mini-modèle **non** entraîné par le gradient PPO principal. **Non-stationnarité** : la policy PPO change au cours du run ; MCTS planifie sur des clones — surveiller l’eval et éventuellement **décroître** la part MCTS en fin de run (§15).

### 5.4 Tableau comparatif

| Critère | Micro | Macro |
|---------|-------|-------|
| Branchement | Très large | Faible |
| Réalisme fin | Élevé si budget | Dépend de l’auxiliaire |
| Coût CPU | Très élevé | Modéré |
| Couplage obs PPO | Fort | Faible |

---

## 6. Interface `GameAdapter`

Aucune règle de jeu dans le module UCT ; uniquement des opérations sur un **état encapsulé** branché sur le moteur / le wrapper d’entraînement (**chemin Python direct** type env / engine — voir §3.4 ; pas via HTTP pour le pas de jeu sauf architecture dédiée explicite).

### 6.1 Contrat minimal

| Méthode | Rôle |
|---------|------|
| `clone(state)` | Copie profonde ou COW ; pas de fuite mutable entre rollouts. |
| `current_player(state)` | Joueur actif (jeu alterné / sièges). |
| `terminal(state)` / `is_terminal(state)` | Fin de partie (ou borne de recherche). |
| `legal_actions(state)` | Actions dans l’**espace MCTS** (macro ou micro) ; pas d’illégalités. |
| `apply(state, action)` | Transition légale ; peut retourner `(state', reward, done, info)` aligné sur un pas « bot » réel. |
| `outcome_utility(state, perspective_player)` [optionnel] | Utilité terminale pour feuille si reward partiel. |

### 6.2 Invariants

- **Légalité** : `apply` uniquement après `legal_actions` cohérent sur le même état.  
- **Pas de mutation** de l’état réel pendant la recherche : **clones** uniquement jusqu’au commit de l’action racine.  
- **Commit** : une fois l’action choisie, un seul chemin d’application sur le fil réel (comme un bot).

### 6.3 Pseudocode

```
fonction mcts_decide(adapter_racine, budget, rng):
    racine = noeud(adapter_racine.clone())
    pour i de 1 à budget:
        nœud = sélection_UCT(racine)
        si non terminal et non pleinement développé:
            nœud = expansion(nœud)
        valeur = rollout(nœud.state, rng)
        rétropropager(nœud, valeur)
    retourner meilleure_action_racine(nœud, config.final_selection)
```

---

## 7. État abstrait (optionnel)

**Motivation** : réduire coût de clone et branchement en projetant `game_state` → `AbstractState` (agrégats par zone ou escouade, buckets PV, objectifs, menaces approximatives).

| Aspect | État complet | Abstrait |
|--------|--------------|----------|
| Fidélité | Maximale | Risque de **reality gap** |
| Coût clone | Élevé | Souvent plus bas |

**Exigences** :

- **Cohérence** : si le mapping `abstract` est pur, `abstract(clone(état))` reste cohérent avec l’abstraction de l’état source.  
- **Réalisabilité** : toute action légale en abstrait doit pouvoir être **commitée** sur le moteur au moment du choix racine ; sinon filtrage + **erreur explicite** en debug.  
- **Pas d’action fantôme** : aucune transition abstraite sans réalisation moteur vérifiable.

**Recommandation** : valider d’abord **clone moteur complet** + macro ; n’introduire l’abstraction qu’avec **tests de régression** (distribution d’actions légales échantillonnée sur des états réels).

**Projection** (pattern utile) : `project_full_to_abstract(game_state) -> AbstractState` ; `commit_abstract_action_to_engine(game_state, action)` pour la **seule** action racine après MCTS.

---

## 8. Algorithme : UCT, expansion, valeur de feuille, rétropropagation, choix racine

### 8.1 Sélection (UCT)

\[
\text{UCT}(c) = \frac{Q(c)}{N(c)} + C \sqrt{\frac{\ln N(\text{parent})}{N(c)}}
\]

\(C\) à calibrer sur l’échelle de récompense réelle (souvent \(\sqrt{2}\) si valeurs dans \([0,1]\)). Enfants non visités : règle d’expansion explicite (première action non essayée ou prior — voir [§20 Annexe A](#20-annexe-a--puct--priors-optionnel)).

### 8.2 Expansion

`apply` sur clone pour chaque enfant ; si `legal_actions` vide et non terminal → **erreur**.

### 8.3 Valeur de feuille

| Source | Usage |
|--------|--------|
| **Terminal** | Utilité outcome pour le joueur MCTS (+1 / 0 / -1 ou reward cumulé moteur). |
| **Horizon** | Troncature + heuristique ou somme de rewards partiels. |
| **Value head externe** | Hors scope v1 ; option **P4** (non confondue avec la tête de valeur PPO). |

Parties courtes : mélange outcome + **shaping** léger peut stabiliser les Q (coefficients **configurés**).

### 8.4 Rétropropagation

Mise à jour des statistiques le long du chemin ; **jeu à deux joueurs** : signe alterné (zero-sum) ou valeur toujours du point de vue du joueur racine — **une convention, documentée**.

### 8.5 Choix à la racine

- **`max_visits`** (souvent plus stable) ou **`max_mean_value`**.  
- Option entraînement : **léger tirage stochastique** proportionnel aux visites pour **diversifier** les trajectoires (config explicite `root_stochasticity`).

---

## 9. Politique de rollout et modèle du joueur PPO

### 9.1 Options de rollout (côté « suite » de la simulation)

| Type | Description |
|------|-------------|
| **Uniforme masquée** | Baseline, bruyant, rapide. |
| **Bot scripté** | Souvent le meilleur compromis **signal / coût** vs le projet. |
| **ε-greedy** | Mélange bot / hasard. |
| **Policy snapshot** | Figée (comme self-play) ; coût inférence. |

**Horizon** : `max_rollout_depth` obligatoire (ou terminal seul si profondeur moyenne maîtrisée).

### 9.2 Contraintes

Légalité stricte ; graine dérivée de `episode_seed` si reproductibilité.

### 9.3 Modèle du joueur PPO dans les rollouts (critique pour l’utilité de l’opposition)

Les rollouts font souvent jouer **à la fois** le siège MCTS et le siège **correspondant à l’agent PPO** jusqu’à horizon ou terminal. Le comportement du **côté PPO** dans la simulation **n’est pas** la policy en cours d’entraînement (sauf coût prohibitif d’inférence partout). Options :

| Option | Effet |
|--------|--------|
| **Snapshot** self-play (même mécanisme que l’eval) | Plus fidèle, plus lourd. |
| **Bot stand-in** | Approximation ; souvent **préférable** au hasard pur si budget limité. |
| **Uniforme masqué** | Diversité extrême ; MCTS peut optimiser contre un **fantôme** non représentatif. |

**Risque** : entraîner contre un adversaire MCTS qui planifie contre un **modèle incorrect** du joueur — sous-utilité du signal pour la généralisation. **À documenter dans la config** (`ppo_side_rollout_policy`) et à **suivre en ablation** (§14).

---

## 10. Configuration JSON

### 10.1 Convention macro (une seule source)

- **`macro_action_set`** : identifiant de **registre** (factory / table en code) qui définit l’espace d’actions macro pour MCTS — **recommandé** pour éviter la duplication avec l’observation PPO.  
- Alternative : liste explicite **`macro_intent_vocab`** dans le JSON — **un seul** mécanisme doit être actif par config ; si les deux sont présents sans règle de priorité, **erreur** à la validation (`require_key` / schéma strict).

Les clés de fraction d’épisodes MCTS sont notées ici **`episode_ratio_*`** ; si l’implémentation retient `episode_fraction_*` ou un autre nom, **aligner le code et ce document** puis figer le schéma (voir §10.3).

### 10.2 Exemple minimal (v1 — UCT, sans PUCT)

Exemple **illustratif** ; clés et noms finaux = **`require_key`** dans `shared/data_validation.py` (ou équivalent) une fois l’implémentation alignée.

```json
{
  "opponent_mix": {
    "enabled": true,
    "self_play_ratio_start": 0.15,
    "self_play_ratio_end": 0.35,
    "warmup_episodes": 500,
    "snapshot_model_path": "ai/models/CoreAgent/model_CoreAgent.zip",
    "snapshot_update_freq_episodes": 50,
    "self_play_snapshot_device": "cpu",
    "self_play_deterministic": true
  },
  "mcts_opponent": {
    "enabled": true,
    "episode_ratio_start": 0.05,
    "episode_ratio_end": 0.12,
    "schedule_total_episodes": 200000,
    "warmup_episodes_mcts": 0,
    "mix_normalization": "global",
    "decision_mode": "macro",
    "macro_action_set": "macro_intent_v1",
    "decision_points": ["turn_start"],
    "budget_simulations": 128,
    "max_rollout_depth": 80,
    "uct_exploration_c": 1.414,
    "auxiliary_policy": "greedy_bot",
    "rollout_policy": "greedy_bot",
    "ppo_side_rollout_policy": "greedy_bot",
    "leaf_evaluation": "rollout_to_terminal",
    "final_selection": "max_visits",
    "root_stochasticity": 0.0,
    "use_abstract_state": false,
    "max_decision_ms": 250,
    "mcts_deterministic": false,
    "thread_pool_size": 1
  }
}
```

**Notes** : `mix_normalization` — voir §4.4 ; `budget_simulations` vs `max_decision_ms` — politique explicite en code ; `ppo_side_rollout_policy` — §9.3.

### 10.3 Extension sélection PUCT (optionnelle)

Si la sélection utilise **PUCT** au lieu d’UCT seul, ajouter notamment (voir [§20 Annexe A](#20-annexe-a--puct--priors-optionnel)) :

```json
"use_puct": true,
"cpuct": 2.0
```

Si `use_puct` est `true`, **`cpuct`** est requis ; les priors \(P(s,a)\) doivent être fournis par heuristique ou module dédié — sinon **erreur** à l’init. Si `use_puct` est `false`, ne pas utiliser `cpuct` pour la sélection (UCT pur).

### 10.4 Gel du schéma (`require_key`)

**Après** choix d’implémentation définitif (noms `episode_ratio_*` vs `episode_fraction_*`, présence ou non de `use_puct`, convention `macro_action_set` seule, etc.) :

1. Documenter les clés **exactes** dans ce fichier et dans `config/agents/<Agent>/<Agent>_training_config.json`.  
2. Valider au chargement avec **`require_key`** (ou schéma JSON strict) — **aucune** clé obligatoire omise, **aucun** `null` senti comme contournement d’erreur pour champs requis.  
3. Toute évolution de schéma = **changement de version** documenté au §21.

---

## 11. Intégration logicielle

- Point d’accroche : là où l’adversaire est instancié (bots / snapshot), ajouter une branche **`MCTSOpponentPlayer`** (ou équivalent) avec la **même interface** que les autres joueurs adverses (`get_action` / conventions du moteur par activation).  
- **Aucune** modification du calcul de gradient PPO.  
- **Déterminisme** : `seed_episode = f(global_seed, episode_id, opponent_type)` (forme exacte à figer en code).  
- **Journalisation** (debug / analyse) : nombre de simulations, temps par décision, action racine choisie — utile pour calibrer budget et `C` / PUCT.  
- **Dépendances** : pas d’import circulaire lourd depuis `mcts` vers `train.py` — **injection** de factory / config.

---

## 12. Arborescence cible `ai/mcts/`

**Variante plate (simple)** :

```
ai/mcts/
├── __init__.py
├── types.py
├── game_adapter.py
├── abstract_state.py          # optionnel
├── uct.py
├── mcts.py
├── rollout.py
├── config.py
└── metrics.py
```

**Variante modulaire (évolutive)** :

```
ai/mcts/
├── __init__.py
├── adapter/
│   ├── game_adapter.py
│   └── abstract_state.py      # optionnel
├── search/
│   ├── mcts.py
│   ├── uct.py
│   └── node.py
├── policies/
│   ├── rollout.py
│   └── auxiliary.py
└── config/
    └── mcts_config.py
```

**Règle** : aucun import depuis `engine/` vers `mcts` ; `engine` ne connaît pas MCTS. `shared/data_validation.py` pour la config stricte.

---

## 13. Performance et scalabilité

### 13.1 Ordres de grandeur (indicatifs, à profiler)

- Entraînement = **très nombreux** pas environnement ; un épisode MCTS ne doit pas multiplier le temps par un ordre de grandeur **sans** le vouloir.  
- Cibles **indicatives** : macro — de l’ordre de **10²–10³** simulations par **point de décision**, **1–3** points par partie ; adapter complet souvent **incompatible** avec le même budget que l’abstrait → réduction de simulations ou usage **eval** seulement.

### 13.2 Leviers

| Levier | Effet |
|--------|--------|
| `budget_simulations` | Linéaire |
| Mode macro | Réduit largeur |
| Clone rapide | Critique (profiler `game_state`) |
| `n_envs` | Multiplicateur si plusieurs MCTS parallèles |
| Parallélisation intra-MCTS | Root parallel — option **P4** ; GIL Python à anticiper |

### 13.3 Stratégies

Budget adaptatif **documenté**, cache `legal_actions` sur hash d’état abstrait (prudence mémoire), réduction de la **fraction d’épisodes** MCTS plutôt que collapse du budget par nœud.

---

## 14. Métriques et évaluation (A/B)

### 14.1 Métriques MCTS / train

| Métrique | Description |
|----------|-------------|
| `mcts/episode_share` | Part réelle vs cible d’épisodes MCTS. |
| `mcts/latency_ms` (p50/p95) | Temps par décision. |
| `mcts/simulations_per_decision` | Budget effectif. |
| `mcts/root_entropy` | Diversité des actions racine. |
| `train/steps_per_second` | Détection régression throughput. |

### 14.2 Métriques qualité (ne pas isoler)

| Métrique | Attention |
|----------|-----------|
| Winrate vs MCTS (eval) | Peut monter **sans** généraliser — **ne pas** l’utiliser seul. |
| **Holdout / bots** (`bot_eval`, scénarios robustes) | Critère principal de **non-régression** (voir `AI_TRAINING.md`). |

### 14.3 Protocole A/B

Comparer run **sans MCTS** vs **avec X % MCTS** à **budget total de steps environnement équivalent** (pas seulement wall-clock), pour mesurer l’effet sur métriques **combined robust** / **worst scenario** / holdouts — pas uniquement sur le winrate contre MCTS.

---

## 15. Risques et mitigations

| Risque | Mitigation |
|--------|------------|
| Throughput effondré | Macro, budget serré, faible fraction d’épisodes |
| **Reality gap** (abstraction) | Valider clone complet d’abord ; tests légaux |
| **MCTS faible** (rollout naïf) | Bot rollout + §9.3 explicite |
| **Sur-adaptation** à MCTS | Majorité bots + self-play ; holdout strict |
| **Non-stationnarité** (PPO change) | Surveiller eval ; décroissance part MCTS possible |
| Incohérence adapter / moteur | Tests d’intégration ; une seule source `apply` |
| Config ambiguë | `require_key` ; pas de défaut masquant une part manquante |
| Dépassement budget temps | Politique explicite (§4.6), pas de contournement silencieux |

---

## 16. Validation empirique (hypothèses)

Le **gain en apprentissage** (meilleure généralisation, sample efficiency) n’est **pas** garanti par cette spécification seule : il dépend du jeu, du budget, des rollouts, du mix d’adversaires et de la stabilité PPO.

Avant d’augmenter la fraction d’épisodes MCTS ou le budget par décision :

1. Vérifier **non-régression** sur holdouts, **`worst_bot`** / **`worst_scenario`** (si applicable) et métriques robustes définies dans `Documentation/AI_TRAINING.md`.  
2. Vérifier que le **throughput** (steps/s ou épisodes/h) reste dans une enveloppe acceptable pour le run.  
3. Effectuer une comparaison **A/B** à **budget de steps environnement équivalent** (§14.3), pas seulement à temps wall-clock identique.  
4. **Diagnostic** : si le **winrate vs MCTS** monte mais que le **holdout** stagne ou se dégrade, ou si les métriques utiles se dégradent alors que le winrate « vs MCTS » augmente — **revoir** dans l’ordre : politiques de **rollout** et **`ppo_side_rollout_policy`** (§9.3), **ratio** MCTS, **espace d’actions macro** (`macro_action_set` / vocabulaire), et **sur-adaptation** à l’opposant MCTS (§14–15).

---

## 17. Phases de livraison P0–P4

Roadmap **unique** :

| Phase | Contenu | Sortie indicielle |
|-------|---------|-------------------|
| **P0** | `GameAdapter` minimal + UCT sur **jeu jouet** (MDP discret) ; tests unitaires arbre | UCT > aléatoire sur jouet |
| **P1** | Adaptateur **moteur réel** (clone) ou abstrait **validé** ; **macro** + auxiliaire + rollout ; hors VecEnv ou 1 env | Parties end-to-end, latence mesurée |
| **P2** | Intégration **sélection d’adversaire** + ratios + TensorBoard `mcts/*` ; fraction **basse** (ex. 1–5 %) | Courbes stables, pas de crash |
| **P3** | Tuning \(C\) / **PUCT si activé** (§10.3, [§20](#20-annexe-a--puct--priors-optionnel)), budget adaptatif optionnel, cache légal ; montée progressive du ratio | Plateau qualité sur scénarios ref. |
| **P4** | Option : micro sur sous-ensemble, parallélisation rollouts, adapter eval-only complet, value feuille avancée | Revue coût / gain |

Le **micro-MCTS** sur masque complet reste **option expérimentale** (souvent P4 ou eval seulement) — pas le chemin par défaut pour le débit d’entraînement.

---

## 18. Glossaire

| Terme | Définition |
|-------|------------|
| **MCTS** | Monte Carlo Tree Search. |
| **UCT** | Upper Confidence bounds applied to Trees. |
| **PUCT** | Variante avec prior sur les actions ([§20 Annexe A](#20-annexe-a--puct--priors-optionnel)). |
| **Rollout** | Simulation après expansion jusqu’à feuille ou horizon. |
| **Politique auxiliaire** | Joue les pas entre deux décisions MCTS macro. |
| **Macro / micro** | Espaces de décision gros grain vs pas-à-pas masque complet. |
| **GameAdapter** | Façade clone / legal / apply vers le moteur. |
| **Self-play** | Adversaire = snapshot de policy (voir `opponent_mix`). |
| **MaskablePPO** | PPO avec masque d’actions légales. |

---

## 19. Références croisées

| Document | Usage |
|----------|--------|
| [Documentation/AI_OBSERVATION.md](AI_OBSERVATION.md) | Macro intent, structure d’observation. |
| [Documentation/AI_TRAINING.md](AI_TRAINING.md) | Pipeline PPO, `opponent_mix`, seat-aware, eval, callbacks. |
| [Documentation/AI_TURN.md](AI_TURN.md) | Phases légales — quand placer les points de décision. |
| [Documentation/AI_IMPLEMENTATION.md](AI_IMPLEMENTATION.md) | Handlers — effets de bord des transitions. |
| `config/agents/CoreAgent/CoreAgent_training_config.json` | Config effective agents. |
| `ai/train.py` | Chargement `opponent_mix`, construction env. |

---

## 20. Annexe A — PUCT / priors (optionnel)

Pour une prior \(P(s,a)\) (heuristique ou réseau séparé), une forme usuelle :

\[
\text{PUCT}(s,a) = \frac{Q(s,a)}{N(s,a)} + C_{\text{puct}} \cdot P(s,a) \cdot \frac{\sqrt{N(s)}}{1+N(s,a)}
\]

Utile si priors informatifs ; **v1** peut rester sur **UCT pur** (exemple §10.2 sans extension §10.3). Bruit de Dirichlet sur les priors à la racine (style AlphaZero) : optionnel, surtout si priors non triviaux.

---

## 21. Historique documentaire

| Version | Date | Changement |
|---------|------|------------|
| **final** | 2026-04 | **Compilation unique** : base `MCTS_bot22.md` + §3.4 VecEnv/Flask (`MCTS_bot32`) + §4.7 non-stationnarité + §16 diagnostic fusionné (`MCTS_bot12` §17) + convention macro + JSON minimal + §10.3 PUCT + §10.4 gel `require_key` ; TOC / ancres harmonisés ; prédécesseurs listés en en-tête. |
| bot22 / bot12 / bot32 / antérieurs | 2026-04 | Archives — voir en-tête. |

---

*Fin de `Documentation/MCTS_bot_final.md`.*
