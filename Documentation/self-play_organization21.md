# Self-Play PPO V2: progression efficace et structuree

## Objectif

Transformer le self-play actuel en systeme **progressif, stable et mesurable** sans gros refactor risqué.

Ce document est volontairement operationnel: il part de l'existant (`train.py`, `env_wrappers.py`, callbacks) et propose un chemin d'implementation en 3 iterations.

---

## 1) Etat actuel (constat franc)

### 1.1 Ce qui fonctionne deja

- mix bot/self-play via `opponent_mix`;
- ratio self-play progressif (`start -> end` avec warmup);
- publication periodique d'un snapshot adverse;
- evaluations bots/holdout et gating de robustesse deja en place.

### 1.2 Limites actuelles (a corriger)

- adversaire self-play = **snapshot unique** (latest-only de fait);
- pas de `recent_pool`, `historical_pool`, `boss_pool`;
- pas de selection par difficulte (band-pass);
- progression du ratio surtout basee sur episode index, pas sur validation go/no-go de palier;
- observabilite insuffisante pour piloter un vrai curriculum self-play.

Conclusion: la base est bonne, mais il manque la couche "organisation adversariale" qui fait la robustesse PPO.

---

## 2) Principes V2 (non negociables)

1. **Pas de latest-only prolongé**: toujours un melange de sources adverses.  
2. **Progression par paliers**: passage conditionne par metriques, pas uniquement par nombre d'episodes.  
3. **Selection de snapshots par difficulte utile**: ni trop facile, ni trop dur.  
4. **Conserver un socle bot** pendant tout le training.  
5. **Chaque decision importante est tracee** (source adverse, snapshot choisi, winrate associe, gate status).  

---

## 3) Architecture cible minimale

### 3.1 Couches d'adversaires

- `latest`: dernier snapshot valide;
- `recent_pool`: fenetre glissante des K derniers snapshots;
- `historical_pool`: reservoir long terme (diversite anti-oubli);
- `boss_pool`: meilleurs checkpoints eval (hard anchors);
- `bot_pool`: baseline stable (random/greedy/defensive deja existants).

### 3.2 Deux decisions separées

1) **Decision globale d'episode**: bot vs self-play (ratio global).  
2) **Si self-play**: choix de la source (`latest/recent/historical/boss`) puis d'un snapshot dans cette source.

### 3.3 Separation des roles

- `train.py`: orchestration snapshot publish + progression de stage;
- `env_wrappers.py` (ou composant dedie): choix adversaire par episode;
- `training_callbacks.py`: collecte metriques, calculs go/no-go et journalisation.

---

## 4) Plan d'implementation en 3 iterations

## Iteration 1 (MVP robuste): pool + mix source

### Scope

- Introduire un `snapshot_registry.json` (index metadata des snapshots);
- sauvegarder snapshots periodiques dans un dossier dedie (`.../selfplay/`);
- supporter `latest + recent + historical` (boss optionnel en I1);
- remplacer le chargement "un seul snapshot path" par "resolution d'un snapshot choisi".

### Livrables

- structure de donnees snapshot:
  - `snapshot_id`, `path`, `created_at_episode`, `stage`, `tags`;
- logique de tirage:
  - `source_mix`: latest/recent/historical;
  - tirage uniforme intra-pool (band-pass en I2);
- logs:
  - `opponent_mode`, `self_play_source`, `snapshot_id`.

### Criteres d'acceptance

- aucun episode self-play sans snapshot resolu;
- distribution source observee proche de la config (+/- 5 pts sur fenetre large);
- pas de regression throughput > 10%.

---

## Iteration 2 (efficacite PPO): band-pass + metriques opposees

### Scope

- eval periodique "agent courant vs snapshots echantillonnes";
- stockage d'un score de difficulte par snapshot:
  - `winrate_vs_current`;
- pondération band-pass:
  - favoriser snapshots autour de 40-60% de winrate.

### Exemple de poids

- `w < 0.20` -> 0.5  
- `0.20 <= w < 0.40` -> 1.0  
- `0.40 <= w <= 0.60` -> 2.0  
- `0.60 < w <= 0.80` -> 1.0  
- `w > 0.80` -> 0.5  

### Criteres d'acceptance

- baisse de variance des metriques d'entrainement (KL/clip/value) a ratio self-play equivalent;
- moins d'oscillation des winrates holdout;
- maintien d'une progression bot baseline.

---

## Iteration 3 (curriculum complet): paliers go/no-go

### Scope

- introduire des `stages` self-play explicites;
- ratio global self-play piloté par stage (pas interpolation brute);
- passage stage conditionne par 3 fenetres eval consecutives.

### GO

- baseline bot non regressif (tol. -2 pts);
- score pools snapshots stable/haussier;
- stabilite PPO acceptable (KL, clip frac, value loss).

### NO-GO

- baisse > 5 pts contre pool snapshots sur 2 fenetres;
- instabilite PPO avec degradation perfs;
- oscillation prolongee sans recuperation.

### Action en NO-GO

- prolonger stage (+5k a +10k episodes), re-evaluer;
- si persistant: rollback stage precedent + ajustement minimal (LR, entropy, mix adversaires).

### Criteres d'acceptance

- transitions de stage explicables et tracees;
- moins de regressions longues;
- robustesse holdout en hausse a budget egal.

---

## 5) Schema de configuration cible (V2)

```json
{
  "opponent_mix_v2": {
    "enabled": true,
    "bot_ratio_floor": 0.30,
    "snapshot_save_interval_episodes": 1000,
    "snapshot_registry_path": "ai/models/CoreAgent/selfplay/snapshot_registry.json",
    "snapshot_dir": "ai/models/CoreAgent/selfplay/snapshots",
    "source_mix": {
      "latest": 0.30,
      "recent": 0.50,
      "historical": 0.20
    },
    "recent_pool_size": 20,
    "historical_pool_max_size": 50,
    "boss_pool_size": 5,
    "band_pass_enabled": true,
    "band_pass_refresh_episodes": 5000,
    "stages": [
      { "name": "s0", "self_play_total": 0.10, "min_episodes": 15000, "target_episodes": 20000, "max_episodes": 30000 },
      { "name": "s1", "self_play_total": 0.30, "min_episodes": 15000, "target_episodes": 20000, "max_episodes": 30000 },
      { "name": "s2", "self_play_total": 0.50, "min_episodes": 15000, "target_episodes": 20000, "max_episodes": 30000 },
      { "name": "s3", "self_play_total": 0.70, "min_episodes": 15000, "target_episodes": 20000, "max_episodes": 30000 }
    ],
    "gate_eval_interval_episodes": 2000,
    "gate_eval_windows": 3
  }
}
```

Notes:
- garder `opponent_mix` actuel en compat backward pendant migration;
- activer `opponent_mix_v2` seulement apres validation I1.

---

## 6) Pseudo-flow V2

```python
def choose_episode_opponent(state):
    stage = state.current_stage
    self_play_total = stage.self_play_total

    if random() > self_play_total:
        return BOT_BASELINE

    source = weighted_choice(state.source_mix)  # latest/recent/historical/boss
    pool = resolve_pool(source, state.registry)

    if state.band_pass_enabled:
        weights = build_band_pass_weights(pool, state.snapshot_winrates)
        snap = weighted_choice_from_pool(pool, weights)
    else:
        snap = uniform_choice(pool)

    return SNAPSHOT(snap.path, snap.id, source)
```

```python
def maybe_advance_stage(gate_history):
    if not enough_windows(gate_history, n=3):
        return False
    if baseline_regressed_too_much(gate_history, tolerance_points=2):
        return False
    if not pool_scores_stable_or_up(gate_history):
        return False
    if not ppo_stability_ok(gate_history):  # KL, clip frac, value loss
        return False
    return True
```

---

## 7) Organisation des fichiers (proposee)

- `ai/self_play_registry.py`: CRUD registry, pools, reservoir sampling;
- `ai/self_play_selector.py`: logique de selection adversaire (source + snapshot);
- `ai/self_play_stages.py`: gestion stage, gates, transitions;
- `ai/train.py`: orchestration publication snapshot + wiring config;
- `ai/env_wrappers.py`: appel a selector pour choisir l'adversaire d'episode;
- `ai/training_callbacks.py`: calcul/trace des metriques de gate.

Si besoin de minimiser le diff, I1 peut rester dans `env_wrappers.py` et `train.py`, puis extraire apres stabilisation.

---

## 8) Metriques obligatoires a logger

- ratio reel bot vs self-play;
- ratio reel par source (`latest/recent/historical/boss`);
- `snapshot_id` choisi et frequence;
- winrate agent vs baseline bot;
- winrate agent vs pool snapshots (global + par source);
- KL, clip_fraction, value_loss (fenetres);
- decisions gate (`PASS`, `FAIL`, `SKIP`) + raison.

Sans ces metriques, impossible de piloter un self-play progressif proprement.

---

## 9) Risques et garde-fous

- **Risque**: surcout inference (chargements snapshots).  
  **Garde-fou**: cache en memoire des snapshots frequents + refresh periodique.

- **Risque**: non-stationnarite accrue si snapshots trop recents.  
  **Garde-fou**: mix impose + historical reservoir + bot floor.

- **Risque**: gate trop strict qui bloque progression.  
  **Garde-fou**: min/target/max episodes par stage + extension contrôlee.

- **Risque**: complexite excessive trop tot.  
  **Garde-fou**: I1 minimal, I2/I3 activables par flags.

---

## 10) Checklist "pret prod"

- [ ] I1 stable (pool + source mix + logs)  
- [ ] I2 valide (band-pass actif, metriques difficulte fiables)  
- [ ] I3 valide (gates stage passes sur plusieurs runs seeds fixes)  
- [ ] holdout regular/hard non regressif  
- [ ] aucune erreur silencieuse, aucune valeur inventee, aucune fallback anti-erreur  

---

## Resume executif

- Garder la base actuelle (mix bot/self-play + snapshots periodiques), mais la faire evoluer vers un **pool multi-snapshots**.  
- Implementer d'abord le **MVP I1** (fort impact / faible risque), puis **band-pass I2**, puis **gates de stage I3**.  
- Piloter les decisions par metriques explicites et logs complets.  
- Objectif final: un self-play PPO plus robuste, moins oscillant, et mieux explicable.

