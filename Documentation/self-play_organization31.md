# Self-Play PPO: plan progressif, efficace et implementable

## Objectif

Mettre en place un self-play robuste pour PPO, sans big-bang, en partant de l'existant:
- melange bot + self-play progressif deja en place (`opponent_mix`);
- publication periodique d'un snapshot adverse (`latest`);
- environnement vectorise (48 envs) et training long.

Ce document est volontairement operationnel: il priorise la stabilite de training, puis la puissance du self-play.

---

## 1) Etat actuel (resume honnete)

### 1.1 Ce qui existe deja (bon socle)

- Ratio global self-play progressif (`self_play_ratio_start -> self_play_ratio_end`).
- Warmup episodes.
- Snapshot adverse unique recharge periodiquement.
- Melange bots (random/greedy/defensive) + self-play.

### 1.2 Ce qui manque encore

- Pas de pool adversaires (`recent/historical/boss`).
- Pas de logique de difficulte (band-pass).
- Pas de stage controller formel (go/no-go paliers).
- Pas de boucle d'evaluation dediee "vs snapshots pool".

### 1.3 Contraintes de realite

Avant d'ajouter de la complexite:
- stabiliser les points de fragilite runtime (publication snapshot, reset invalide en worker);
- garder une base baseline bots pour detecter les regressions;
- minimiser la non-stationnarite injectee a chaque increment.

---

## 2) Strategie recommandee: 3 increments

Principe: chaque increment est deployable, mesurable, et reversible.

### Increment 1 - Stabiliser le self-play v1 (latest + bots)

But:
- fiabiliser 100% le pipeline actuel;
- eviter les crashes qui ruinent les longues runs;
- obtenir des courbes PPO propres avant complexification.

Actions:
- verrouiller la publication snapshot atomique et surveiller ses erreurs;
- traiter en priorite les cas "episode ended before controlled player turn during reset";
- ajouter un suivi explicite des episodes `vs_bot` et `vs_selfplay` par fenetre;
- confirmer que la progression de ratio observee correspond bien au ratio cible.

Go/no-go increment 1:
- 1 run long sans crash bloquant;
- ratio self-play observe proche du plan (< 3 points d'ecart sur fenetre);
- pas de degradation franche vs baseline bots.

### Increment 2 - Ajouter les pools adverses (recent/historical)

But:
- sortir du "latest-only";
- reduire oubli catastrophique et cycles.

Actions:
- conserver `latest`;
- ajouter `recent_pool` (FIFO) et `historical_pool` (reservoir fixe);
- lors d'un episode self-play, tirer d'abord la source, puis le snapshot:
  - latest: 30%
  - recent: 50%
  - historical: 20%
- evaluer periodiquement winrate contre snapshots echantillonnes.

Go/no-go increment 2:
- variance perf reduite (moins d'oscillations que v1);
- pas de regression durable vs baseline bots;
- progression stable vs pool snapshots.

### Increment 3 - Stage controller + band-pass difficulte

But:
- rendre la progression auto-regulee et plus sample-efficient.

Actions:
- introduire des paliers avec `min/target/max episodes`;
- gate go/no-go sur 3 fenetres fixes;
- appliquer ponderation band-pass par difficulte snapshot:
  - trop facile/trop dur = poids reduit;
  - zone 40-60% winrate = poids maximal;
- en NO-GO: prolonger, puis rollback de stage si necessaire.

Go/no-go increment 3:
- paliers franchis majoritairement en GO (sans rollback repetitif);
- KL/clip/value stables sur la duree;
- robustesse amelioree sur holdout bot + snapshot pools.

---

## 3) Schedules recommandes (pragmatiques)

## 3.1 Ratio global self-play

Version conservative (recommandee pour ton setup):
- 0-20k: 0.05
- 20k-60k: 0.20
- 60k-120k: 0.35
- 120k+: 0.50

Version aggressive (seulement si increment 1 tres stable):
- 0-20k: 0.10
- 20k-60k: 0.30
- 60k-120k: 0.50
- 120k+: 0.70

Regle:
- garder une proportion non nulle de bots en permanence.

## 3.2 Mix interne self-play (increment 2+)

- latest: 0.30
- recent: 0.50
- historical: 0.20

Note:
- si oscillations fortes: monter `recent`, baisser `latest`.

---

## 4) Design des pools snapshots

### 4.1 Structures minimales

- `latest_snapshot`: dernier snapshot publie.
- `recent_pool`: derniers K snapshots (FIFO), ex K=20.
- `historical_pool`: reservoir fixe, ex max=50.
- `boss_pool` (optionnel v3): top checkpoints eval, ex 5.

### 4.2 Frequence de snapshot

- toutes les 1000-5000 episodes selon cout I/O.
- ton setup actuel est deja a 1000 episodes (coherent pour v1/v2).

### 4.3 Tirage adverse self-play

Pseudo-flow:

```python
def choose_self_play_opponent(state):
    source = weighted_choice({
        "latest": state.mix_latest,
        "recent": state.mix_recent,
        "historical": state.mix_historical,
    })
    if source == "latest":
        return state.latest_snapshot
    if source == "recent":
        return weighted_draw(state.recent_pool, state.snapshot_weights)
    return weighted_draw(state.historical_pool, state.snapshot_weights)
```

---

## 5) Gating des paliers (increment 3)

## 5.1 Fenetres et cadence

- eval_interval_episodes: 2000 (ordre de grandeur)
- eval_windows_for_gate: 3
- seeds fixes d'eval entre fenetres

## 5.2 Conditions GO

GO seulement si tout est vrai:
- winrate vs baseline bots non regressif (tol max -2 points);
- winrate vs snapshots pools stable/haussier;
- reward moyen stable/haussier;
- KL sans pics repetes;
- clip fraction non saturante durablement;
- value loss sans explosion.

## 5.3 Conditions NO-GO

NO-GO si un signal fort apparait:
- baisse > 5 points vs pools sur 2 fenetres;
- instabilite KL + degradation perf;
- oscillation policy/value prolongee.

Action NO-GO:
- prolonger le palier (+5k a +10k episodes), re-evaluer;
- si persistant: revenir au palier precedent et ajuster un seul levier.

---

## 6) Hyperparametres: discipline de changement

Regle critique:
- ne pas changer plusieurs hyperparametres PPO en meme temps que la structure self-play.

Ordre recommande:
1. stabiliser pipeline (increment 1);
2. ajouter pools (increment 2), hyperparams inchanges;
3. ajouter gates (increment 3);
4. ensuite seulement micro-ajustements LR/entropy/clip.

---

## 7) Instrumentation minimale a avoir

- compteur episodes par type adversaire:
  - `episodes_vs_bot`
  - `episodes_vs_selfplay_latest`
  - `episodes_vs_selfplay_recent`
  - `episodes_vs_selfplay_historical`
- distribution effective des adversaires sur fenetres;
- winrates eval:
  - vs bots holdout
  - vs echantillon pools snapshots
- sante PPO:
  - KL
  - clip_fraction
  - value_loss
  - entropy

Sans ces 4 blocs, le stage controller devient aveugle.

---

## 8) Definition de "progressif et efficace"

Progressif:
- distribution adversaire qui evolue par paliers;
- non-stationnarite controlee;
- decisions de passage basees metriques, pas calendrier fixe.

Efficace:
- peu de runs perdues sur crash pipeline;
- robustesse qui monte sur bots + snapshots;
- moins d'oscillations pour un meme budget episodes.

---

## 9) Plan d'execution concret (ordre de dev)

1. Increment 1 (stabilite runtime + observabilite ratio).
2. Increment 2 (pools recent/historical + tirage source).
3. Eval comparative v1 vs v2 (meme seeds).
4. Increment 3 (gates paliers + band-pass).
5. Ajustements fins (un levier a la fois).

---

## 10) Resume executif

- Ton architecture actuelle est une bonne base, mais encore v1.
- Le meilleur ROI: stabilite runtime, puis pools, puis gating.
- Eviter le big-bang est la cle pour PPO en self-play.
- Objectif final: self-play progressif, mesurable, et anti-regression.

