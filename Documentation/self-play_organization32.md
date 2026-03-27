# Self-Play PPO V3: version definitive (progressive, stable, mesurable)

## Objectif

Definir une strategie self-play **definitive** pour PPO qui maximise la probabilite de bons resultats d'entrainement sur ce projet:
- progression reelle et controlee;
- robustesse contre oscillations et oubli catastrophique;
- implementation incrementalement deployable;
- metriques explicites pour decisions go/no-go.

Cette version fusionne:
- la prudence operationnelle (stabilite d'abord);
- la structure technique complete (pools, selection, stages, gating).

---

## 1) Principes non negociables

1. **Stabilite runtime avant complexite**: pas de self-play avance sur pipeline instable.  
2. **Pas de latest-only prolonge**: introduire un melange de snapshots.  
3. **Progression par paliers valides**: passage base sur metriques, pas uniquement sur episodes.  
4. **Bot floor permanent**: conserver une part bots pour baseline stable et detection regressions.  
5. **Un changement majeur a la fois**: eviter de toucher simultanement self-play structure + hyperparametres PPO.

---

## 2) Etat de reference et cible

## 2.1 Etat actuel (v1)

- ratio global self-play progressif via `opponent_mix`;
- warmup deja present;
- snapshot adverse unique (`latest`) recharge periodiquement;
- melange bots random/greedy/defensive.

## 2.2 Cible definitive (v3)

- selection adverse en 2 etapes:
  1) bot vs self-play (ratio global par stage)
  2) si self-play: source `latest/recent/historical/boss` puis snapshot
- pools snapshots persistants avec metadata;
- ponderation band-pass par difficulte;
- stage controller go/no-go sur fenetres d'evaluation;
- journalisation complete des decisions.

---

## 3) Roadmap definitive en 3 increments

## Increment 1 - Fiabilisation v1 (obligatoire)

But:
- garantir des runs longs stables;
- valider que le ratio self-play observe suit la config;
- preparer l'observabilite necessaire aux increments suivants.

Scope:
- fiabiliser publication snapshot atomique;
- traiter les erreurs reset invalide (episodes sans tour agent);
- logger distribution reelle `vs_bot` / `vs_selfplay`;
- verifier absence de crash bloquant sur run long.

Critere de sortie I1:
- run long complet sans crash bloquant;
- ecart ratio observe/cible < 3 points sur fenetre;
- pas de regression durable vs baseline bots.

## Increment 2 - Pools snapshots et mix source

But:
- sortir de latest-only;
- reduire cycles et oubli catastrophique.

Scope:
- `latest_snapshot`;
- `recent_pool` (FIFO, ex 20);
- `historical_pool` (reservoir fixe, ex 50);
- source mix self-play:
  - latest: 0.30
  - recent: 0.50
  - historical: 0.20
- tirage uniforme intra-pool (band-pass active en I3).

Critere de sortie I2:
- distribution source conforme a la config (+/- 5 points);
- variance perf reduite vs I1 a ratio global comparable;
- baseline bots non regressive.

## Increment 3 - Band-pass + stage controller go/no-go

But:
- maximiser sample efficiency et stabilite PPO;
- automatiser progression/rollback selon signaux.

Scope:
- calcul periodique `winrate(current_agent vs snapshot)` sur echantillons;
- ponderation band-pass:
  - w < 0.20 -> 0.5
  - 0.20 <= w < 0.40 -> 1.0
  - 0.40 <= w <= 0.60 -> 2.0
  - 0.60 < w <= 0.80 -> 1.0
  - w > 0.80 -> 0.5
- stages explicites avec `min/target/max episodes`;
- gate sur 3 fenetres fixes.

Critere de sortie I3:
- transitions de stage explicables et tracees;
- moins de regressions longues;
- robustesse holdout + pool snapshots en hausse.

---

## 4) Schedules recommandes

## 4.1 Ratio global self-play par stage

Profil conservative (recommande par defaut):
- s0: 0.05 (0-20k)
- s1: 0.20 (20k-60k)
- s2: 0.35 (60k-120k)
- s3: 0.50 (120k+)

Profil aggressive (uniquement si I1 et I2 tres stables):
- s0: 0.10
- s1: 0.30
- s2: 0.50
- s3: 0.70

Regle:
- maintenir un `bot_ratio_floor` non nul (ex: 0.30).

## 4.2 Cadence snapshots et eval

- save snapshot: toutes les 1000 episodes (valeur actuelle acceptable);
- refresh band-pass: toutes les 5000 episodes;
- gate eval: toutes les 2000 episodes;
- windows pour gate: 3.

---

## 5) Gating de palier (definition definitive)

## 5.1 Conditions GO

GO uniquement si toutes vraies:
- winrate bots baseline non regressif (tol max -2 points);
- score vs pools snapshots stable/haussier;
- reward moyen stable/haussier;
- KL sans pics repetes;
- clip fraction non saturante durablement;
- value loss sans explosion durable.

## 5.2 Conditions NO-GO

NO-GO si un signal fort:
- baisse > 5 points vs pools sur 2 fenetres;
- instabilite PPO + degradation performance;
- oscillation policy/value prolongee.

Action NO-GO:
- prolonger stage (+5k a +10k episodes), re-evaluer;
- si persistant: rollback stage precedent + ajuster un seul levier.

---

## 6) Architecture technique cible

Composants recommandes:
- `ai/self_play_registry.py`: index snapshots, pools, reservoir;
- `ai/self_play_selector.py`: decision source + tirage snapshot;
- `ai/self_play_stages.py`: logique stage/gate/transitions;
- `ai/train.py`: publication snapshot + orchestration loop;
- `ai/env_wrappers.py`: selection adversaire par episode;
- `ai/training_callbacks.py`: metriques gate + logs decisions.

Migration:
- conserver compat `opponent_mix` actuel;
- activer V3 via flag dedie apres validation I1.

---

## 7) Schema de config cible (definitif)

```json
{
  "opponent_mix_v3": {
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
    "band_pass": {
      "enabled": true,
      "refresh_episodes": 5000
    },
    "stages": [
      { "name": "s0", "self_play_total": 0.05, "min_episodes": 15000, "target_episodes": 20000, "max_episodes": 30000 },
      { "name": "s1", "self_play_total": 0.20, "min_episodes": 15000, "target_episodes": 20000, "max_episodes": 30000 },
      { "name": "s2", "self_play_total": 0.35, "min_episodes": 15000, "target_episodes": 20000, "max_episodes": 30000 },
      { "name": "s3", "self_play_total": 0.50, "min_episodes": 15000, "target_episodes": 20000, "max_episodes": 30000 }
    ],
    "gate": {
      "eval_interval_episodes": 2000,
      "eval_windows": 3,
      "baseline_regression_tolerance_points": 2,
      "pool_drop_fail_points": 5
    }
  }
}
```

---

## 8) Pseudo-flow definitif

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
        snapshot = weighted_choice_from_pool(pool, weights)
    else:
        snapshot = uniform_choice(pool)

    return SnapshotOpponent(path=snapshot.path, snapshot_id=snapshot.id, source=source)
```

```python
def should_advance_stage(eval_history):
    if not has_n_windows(eval_history, n=3):
        return False
    if baseline_regressed(eval_history, tolerance_points=2):
        return False
    if pool_drop_too_large(eval_history, fail_points=5):
        return False
    if not ppo_stability_ok(eval_history):  # KL, clip frac, value loss
        return False
    return True
```

---

## 9) Instrumentation obligatoire

A logger en continu:
- ratio reel bot vs self-play;
- ratio reel par source (`latest/recent/historical/boss`);
- `snapshot_id` choisi et frequence d'utilisation;
- winrate bots baseline (holdout regular/hard);
- winrate vs echantillon pools snapshots;
- KL, clip_fraction, value_loss, entropy;
- decisions de gate (`PASS/FAIL/SKIP`) + raison.

Sans ces logs, aucun pilotage fiable des paliers.

---

## 10) Discipline d'experimentation PPO

- Ne modifier qu'un levier majeur par iteration.
- Garder seeds d'eval fixes pour comparer les gates.
- Comparer I(n) vs I(n-1) a budget episodes equivalent.
- Si regression: rollback et corriger avant ajout de complexite.

---

## 11) Definition de succes

Le self-play est considere "reussi" si:
- runs longues stables sans crash bloquant;
- progression de robustesse sur bots holdout et pools snapshots;
- oscillations reduites pour budget episodes comparable;
- transitions de stage explicables par metriques, pas arbitraires.

---

## Resume executif

- Commencer par la stabilite runtime (I1), puis ajouter pools (I2), puis gating+band-pass (I3).
- Garder une base bots permanente pour prevenir les regressions silencieuses.
- Utiliser des metriques explicites pour chaque decision de progression.
- Cette sequence est le meilleur compromis entre performance potentielle et risque d'echec.

