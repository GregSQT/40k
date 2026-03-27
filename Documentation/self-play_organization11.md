# Self-Play PPO: theorie et implementation

## Objectif

Definir une organisation de self-play stable et performante pour PPO, avec:
- progression de la proportion de self-play pendant le training;
- selection robuste des snapshots adverses;
- criteres explicites de passage de palier (go/no-go);
- garde-fous contre oscillations, oubli catastrophique et sur-specialisation.

Ce document est volontairement operationnel: il explique le "pourquoi" et le "comment".

---

## 1) Theorie: pourquoi organiser le self-play

### 1.1 PPO + adversaire qui change = non-stationnarite

En self-play, la distribution des transitions change car l'adversaire evolue.
Pour PPO, cela peut provoquer:
- politique instable (oscillations entre strategies);
- value function qui suit une cible mouvante;
- regressions locales mal detectees.

Conclusion: le self-play est utile, mais doit etre structure.

### 1.2 Pourquoi eviter "latest-only"

Jouer uniquement contre le dernier snapshot ("latest-only") augmente le risque de cycle:
- l'agent apprend a battre une strategie recente;
- oublie des contre-strategies plus anciennes;
- re-regresse lorsque le meta change.

Le pool historique casse ce cycle en imposant de la diversite.

### 1.3 Role des snapshots historiques

Les snapshots historiques ne servent pas seulement a "faciliter":
- certains sont plus faibles, oui;
- d'autres representent des styles de jeu differents;
- ensemble, ils limitent l'oubli et renforcent la robustesse.

Objectif reel: diversite + stabilite, pas "easy mode".

### 1.4 Pourquoi des paliers avec stabilisation

Augmenter le self-play trop vite peut detruire le signal d'apprentissage.
Des paliers avec une phase de stabilisation:
- laissent PPO converger sur une distribution presque fixe;
- reduisent les sauts de distribution;
- donnent des points de controle mesurables.

---

## 2) Strategie recommandee

## 2.1 Progression du ratio global self-play

Exemple de schedule (episodes):
- 0-20k: self_play_total = 0.10
- 20k-60k: self_play_total = 0.30
- 60k-120k: self_play_total = 0.50
- 120k+: self_play_total = 0.70

Conserver une part non nulle de bot/scripted pour une baseline stable.

### 2.2 Decomposition interne du self-play

Quand un episode est en self-play, choisir la source adverse:
- latest: 30%
- recent pool: 50%
- historical pool: 20%

Important: "self-play" inclut latest + pools de snapshots.

### 2.3 Stabilisation par palier

Par palier:
- minimum: 10k-15k episodes;
- cible: 20k;
- maximum: 30k avant decision forcee.

Ne pas changer de palier tant que les criteres go/no-go ne sont pas valides.

---

## 3) Selection des snapshots

### 3.1 Que sauvegarder

Sauvegarder un snapshot a intervalle fixe (ex: toutes les 5k episodes).

Conserver:
- `latest`: dernier snapshot valide;
- `recent_pool`: derniers K snapshots (ex: K=20);
- `historical_pool`: reservoir fixe (ex: max 50);
- `boss_pool`: top checkpoints eval (ex: 5).

### 3.2 Tirage d'un snapshot adverse

Pour un episode self-play:
1. Tirer une couche (`latest`, `recent_pool`, `historical_pool`) selon ratio configure.
2. Tirer un snapshot dans cette couche via poids de difficulte.

### 3.3 Poids de difficulte (band-pass)

Mesurer periodiquement `w = winrate(agent_courant vs snapshot)`.
Favoriser les snapshots ni trop faciles ni trop durs:
- `w < 0.20` -> poids 0.5
- `0.20 <= w < 0.40` -> poids 1.0
- `0.40 <= w <= 0.60` -> poids 2.0
- `0.60 < w <= 0.80` -> poids 1.0
- `w > 0.80` -> poids 0.5

Recalculer ces poids tous les 5k-10k episodes.

---

## 4) Criteres go/no-go de passage de palier

Verifier sur 3 fenetres d'evaluation consecutives (meme seeds d'eval):

GO si tout est vrai:
- winrate vs bot baseline non regressif (tolerance max -2 points);
- winrate vs pools snapshots stable ou en hausse;
- reward moyen stable/haussier;
- KL PPO sans pics repetes;
- clip fraction non saturante sur une longue periode;
- value loss sans explosion durable.

NO-GO si un signal fort apparait:
- baisse >5 points vs pool snapshots sur 2 fenetres;
- forte instabilite KL + degradation de perf;
- oscillation policy/value prolongee sans recuperation.

Action en NO-GO:
- prolonger le palier (+5k a +10k episodes), puis re-evaluer;
- si persistant: revenir au palier precedent et ajuster (LR, entropy, composition adversaires).

---

## 5) Implementation pratique (pseudo-flow)

```python
def choose_opponent(training_state):
    # 1) Decide if episode is self-play
    if random() > training_state.self_play_total:
        return BOT_BASELINE

    # 2) Choose self-play source
    source = weighted_choice({
        "latest": 0.30,
        "recent": 0.50,
        "historical": 0.20,
    })

    if source == "latest":
        return training_state.latest_snapshot

    if source == "recent":
        return weighted_snapshot_draw(training_state.recent_pool, training_state.snapshot_weights)

    return weighted_snapshot_draw(training_state.historical_pool, training_state.snapshot_weights)
```

```python
def should_advance_stage(eval_history):
    # eval_history contains last 3 eval windows
    if not baseline_non_regressive(eval_history, tolerance_points=2):
        return False
    if not snapshot_pool_stable_or_up(eval_history):
        return False
    if not ppo_stability_ok(eval_history):  # KL, clip frac, value loss
        return False
    return True
```

---

## 6) Configuration cible (exemple)

- `snapshot_save_interval_episodes`: 5000
- `recent_pool_size`: 20
- `historical_pool_max_size`: 50
- `boss_pool_size`: 5
- `self_play_source_mix`:
  - latest: 0.30
  - recent: 0.50
  - historical: 0.20
- `stage_min_episodes`: 15000
- `stage_target_episodes`: 20000
- `stage_max_episodes`: 30000
- `eval_interval_episodes`: 2000
- `eval_windows_for_gate`: 3

---

## 7) Erreurs frequentes a eviter

- Monter le ratio self-play sans phase de stabilisation.
- Faire du latest-only trop longtemps.
- Changer plusieurs hyperparametres PPO en meme temps pendant un palier.
- Evaluer avec des seeds variables a chaque gate (bruit eleve).
- Supprimer trop vite les snapshots historiques utiles.

---

## 8) Resume executif

- Oui au self-play progressif.
- Oui aux paliers avec stabilisation.
- Non au latest-only.
- Oui a un melange latest + recent + historical.
- Oui a des gates go/no-go bases sur metriques, pas seulement sur "X episodes".

