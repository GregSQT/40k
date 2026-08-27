# Migration PostgreSQL v3.3 (version de reference a figer)

## Pourquoi on tournait en rond

La boucle venait de 4 causes:

1. **Conflit niveau de detail**: vision produit melangee avec SQL execution.
2. **Contradictions techniques**: partitionnement annonce mais contraintes incompatibles.
3. **Manque de contrat d'acceptation**: pas de definition claire du "suffisamment bon".
4. **Pas de gouvernance de changement**: chaque version re-ouvrait tout le scope.

Cette v3.3 fixe ces points et sert de base unique pour implementation.

## 1) Decision

PostgreSQL devient la source unique de verite metier pour:
- roster,
- training PPO telemetry,
- audit et replay.

Decision: GO, avec migration par phases, parite PPO chifree obligatoire, et cutover protege.

## 2) Scope reel (non-negociable)

Le cutover ne concerne pas uniquement `frontend/src/roster/**`.
Il couvre aussi:

- `ai/unit_registry.py` (fin parsing TS runtime),
- `services/api_server.py`,
- pipeline training/replay (`ai/train.py`, `ai/macro_training_env.py`, `ai/training_callbacks.py`),
- instanciation runtime cote engine.

## 3) Principes

- Single source of truth metier: DB uniquement.
- Aucune valeur implicite, aucun fallback silencieux.
- Cohérence `snapshot_id` garantie par contraintes DB.
- Contrats API versionnes.
- Shadow mode obligatoire avant suppression legacy.
- Tout ecart hors seuil => stop cutover + correction root cause.

## 4) Schema SQL v3.3 (stable pour implementation)

### 4.1 Catalogue roster

```sql
CREATE TABLE roster_snapshot (
    snapshot_id BIGSERIAL PRIMARY KEY,
    version_label TEXT NOT NULL UNIQUE,
    source_note TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('draft', 'published', 'archived'))
);

CREATE TABLE faction (
    faction_id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL
);

CREATE TABLE unit_class (
    snapshot_id BIGINT NOT NULL REFERENCES roster_snapshot(snapshot_id) ON DELETE CASCADE,
    unit_class_id BIGSERIAL NOT NULL,
    faction_id BIGINT NOT NULL REFERENCES faction(faction_id),
    class_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role_primary TEXT NOT NULL CHECK (role_primary IN ('ranged', 'melee', 'hybrid', 'support')),
    role_target TEXT NOT NULL CHECK (role_target IN ('elite', 'swarm', 'neutral', 'objective')),
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_id, unit_class_id),
    UNIQUE (snapshot_id, faction_id, class_key)
);

CREATE TABLE unit_profile (
    snapshot_id BIGINT NOT NULL REFERENCES roster_snapshot(snapshot_id) ON DELETE CASCADE,
    unit_profile_id BIGSERIAL NOT NULL,
    unit_key TEXT NOT NULL,
    unit_class_id BIGINT NOT NULL,
    move INTEGER NOT NULL,
    toughness INTEGER NOT NULL,
    wounds INTEGER NOT NULL,
    armor_save INTEGER NOT NULL,
    invul_save INTEGER,
    objective_control INTEGER NOT NULL,
    leadership INTEGER,
    points_cost INTEGER,
    is_character BOOLEAN NOT NULL DEFAULT FALSE,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_id, unit_profile_id),
    UNIQUE (snapshot_id, unit_key),
    FOREIGN KEY (snapshot_id, unit_class_id)
      REFERENCES unit_class(snapshot_id, unit_class_id)
      ON DELETE RESTRICT
);

CREATE TABLE weapon_profile (
    snapshot_id BIGINT NOT NULL REFERENCES roster_snapshot(snapshot_id) ON DELETE CASCADE,
    weapon_profile_id BIGSERIAL NOT NULL,
    weapon_key TEXT NOT NULL,
    weapon_type TEXT NOT NULL CHECK (weapon_type IN ('ranged', 'melee')),
    attacks INTEGER,
    strength INTEGER,
    armor_penetration INTEGER,
    damage INTEGER,
    range_inches INTEGER,
    rules_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_id, weapon_profile_id),
    UNIQUE (snapshot_id, weapon_key)
);

CREATE TABLE unit_weapon (
    snapshot_id BIGINT NOT NULL REFERENCES roster_snapshot(snapshot_id) ON DELETE CASCADE,
    unit_profile_id BIGINT NOT NULL,
    weapon_profile_id BIGINT NOT NULL,
    slot_type TEXT NOT NULL CHECK (slot_type IN ('primary', 'secondary', 'optional')),
    is_default BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (snapshot_id, unit_profile_id, weapon_profile_id),
    FOREIGN KEY (snapshot_id, unit_profile_id)
      REFERENCES unit_profile(snapshot_id, unit_profile_id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id, weapon_profile_id)
      REFERENCES weapon_profile(snapshot_id, weapon_profile_id) ON DELETE CASCADE
);

CREATE TABLE roster_template (
    snapshot_id BIGINT NOT NULL REFERENCES roster_snapshot(snapshot_id) ON DELETE CASCADE,
    roster_template_id BIGSERIAL NOT NULL,
    template_key TEXT NOT NULL,
    constraints_json JSONB NOT NULL,
    PRIMARY KEY (snapshot_id, roster_template_id),
    UNIQUE (snapshot_id, template_key)
);
```

### 4.2 Training / replay (coherence + idempotence)

```sql
CREATE TABLE training_run (
    run_id TEXT PRIMARY KEY,
    snapshot_id BIGINT NOT NULL REFERENCES roster_snapshot(snapshot_id),
    agent_key TEXT NOT NULL,
    training_config_name TEXT NOT NULL,
    rewards_config_name TEXT NOT NULL,
    config_json JSONB NOT NULL,
    config_hash_sha256 TEXT NOT NULL,
    git_commit TEXT NOT NULL,
    python_version TEXT NOT NULL,
    torch_version TEXT NOT NULL,
    sb3_version TEXT NOT NULL,
    gym_version TEXT NOT NULL,
    global_seed BIGINT NOT NULL,
    env_seed_base BIGINT NOT NULL,
    numpy_seed BIGINT NOT NULL,
    torch_seed BIGINT NOT NULL,
    action_mask_version TEXT NOT NULL,
    obs_norm_version TEXT,
    reward_norm_version TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'aborted')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    error_reason TEXT,
    UNIQUE (run_id, snapshot_id),
    CHECK (
      (status = 'running' AND ended_at IS NULL)
      OR (status IN ('completed', 'failed', 'aborted') AND ended_at IS NOT NULL)
    )
);

CREATE TABLE training_episode (
    run_id TEXT NOT NULL,
    snapshot_id BIGINT NOT NULL,
    episode_index BIGINT NOT NULL,
    scenario_template_key TEXT,
    roster_template_key TEXT,
    sampled_payload_json JSONB NOT NULL,
    total_reward DOUBLE PRECISION NOT NULL,
    episode_len INTEGER NOT NULL,
    done_reason TEXT,
    winner INTEGER,
    duration_ms BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, episode_index),
    UNIQUE (run_id, episode_index, snapshot_id),
    FOREIGN KEY (run_id, snapshot_id)
      REFERENCES training_run(run_id, snapshot_id)
      ON DELETE CASCADE
);

CREATE TABLE training_step_event (
    run_id TEXT NOT NULL,
    snapshot_id BIGINT NOT NULL,
    episode_index BIGINT NOT NULL,
    step_index BIGINT NOT NULL,
    phase_key TEXT NOT NULL,
    player INTEGER NOT NULL,
    unit_id INTEGER,
    action_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    action_mask_hash TEXT NOT NULL,
    reward DOUBLE PRECISION NOT NULL,
    terminated BOOLEAN NOT NULL,
    truncated BOOLEAN NOT NULL,
    success BOOLEAN NOT NULL,
    event_schema_version TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    obs_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, episode_index, step_index),
    FOREIGN KEY (run_id, episode_index, snapshot_id)
      REFERENCES training_episode(run_id, episode_index, snapshot_id)
      ON DELETE CASCADE
) PARTITION BY HASH (run_id);

CREATE TABLE training_step_event_p0 PARTITION OF training_step_event FOR VALUES WITH (modulus 8, remainder 0);
CREATE TABLE training_step_event_p1 PARTITION OF training_step_event FOR VALUES WITH (modulus 8, remainder 1);
CREATE TABLE training_step_event_p2 PARTITION OF training_step_event FOR VALUES WITH (modulus 8, remainder 2);
CREATE TABLE training_step_event_p3 PARTITION OF training_step_event FOR VALUES WITH (modulus 8, remainder 3);
CREATE TABLE training_step_event_p4 PARTITION OF training_step_event FOR VALUES WITH (modulus 8, remainder 4);
CREATE TABLE training_step_event_p5 PARTITION OF training_step_event FOR VALUES WITH (modulus 8, remainder 5);
CREATE TABLE training_step_event_p6 PARTITION OF training_step_event FOR VALUES WITH (modulus 8, remainder 6);
CREATE TABLE training_step_event_p7 PARTITION OF training_step_event FOR VALUES WITH (modulus 8, remainder 7);

CREATE TABLE ingestion_batch (
    run_id TEXT NOT NULL,
    episode_index BIGINT NOT NULL,
    batch_id TEXT NOT NULL,
    event_count INTEGER NOT NULL CHECK (event_count > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, episode_index, batch_id),
    FOREIGN KEY (run_id, episode_index)
      REFERENCES training_episode(run_id, episode_index)
      ON DELETE CASCADE
);

CREATE TABLE run_artifact (
    run_id TEXT NOT NULL REFERENCES training_run(run_id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL CHECK (artifact_type IN ('model_zip', 'tensorboard', 'eval_report', 'config_export')),
    storage_uri TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL,
    size_bytes BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, artifact_type)
);

CREATE TABLE episode_artifact (
    run_id TEXT NOT NULL,
    episode_index BIGINT NOT NULL,
    artifact_type TEXT NOT NULL CHECK (artifact_type IN ('step_log_raw_gzip', 'replay_json')),
    storage_uri TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, episode_index, artifact_type),
    FOREIGN KEY (run_id, episode_index)
      REFERENCES training_episode(run_id, episode_index)
      ON DELETE CASCADE
);

CREATE INDEX idx_training_run_agent_snapshot
  ON training_run(agent_key, snapshot_id, started_at DESC);
CREATE INDEX idx_training_episode_run
  ON training_episode(run_id, episode_index);
CREATE INDEX idx_training_step_event_phase_action
  ON training_step_event(phase_key, action_type);
```

## 5) Ingestion step-level (contrat implementation)

Mode officiel: **at-least-once + idempotence**.

- Writer en batch asynchrone.
- Dedupe evenement: PK `(run_id, episode_index, step_index)`.
- Dedupe requete: `ingestion_batch(batch_id)`.
- SQL write: `INSERT ... ON CONFLICT DO NOTHING`.
- Retry borne + backoff exponentiel.
- DLQ si echec repete.
- Echec final => `training_run.status='failed'` + `error_reason` obligatoire.

Interdit: perte silencieuse de logs.

## 6) SLO / SLA

- `POST /roster/compose` p95 < 120 ms, taux erreur < 0.5%.
- `POST /training/.../events:batch` p95 < 200 ms, taux erreur < 0.5%.
- backlog writer < 10 000 events en nominal.
- perte silencieuse de logs: 0.

## 7) Retention et volumetrie

### 7.1 Strategie de partitionnement (decision explicite)

Cette v3.3 retient `PARTITION BY HASH (run_id)` pour limiter les hotspots write.

Regle de decision operationnelle:
- Si la retention temporelle devient le besoin dominant (purge rapide par periode), migrer vers `PARTITION BY RANGE (created_at)` mensuel.
- Si la priorite reste le debit d'ecriture et la repartition uniforme, conserver HASH.

Decision immediate:
- **Conserver HASH en v1**.
- Ouvrir une tache de revue apres 14 jours de charge reelle (latence write, cout purge, taille partitions).

### 7.2 Retention

- `training_step_event`: retention 90 jours.
- `episode_artifact`: 180 jours.
- `run_artifact`:
  - golden/release: long terme,
  - standard: 180 jours.
- purge/archive quotidienne.

Ops:
- si job retention echoue 3 jours consecutifs => alerte critique.

## 8) Contrat reproductibilite PPO

Run certifiable si present:

- `snapshot_id` publie,
- `config_json` + `config_hash_sha256`,
- seeds (`global`, `env_seed_base`, `numpy`, `torch`),
- `git_commit`,
- versions runtime (`python`, `torch`, `sb3`, `gym`),
- `action_mask_version`, `obs_norm_version`, `reward_norm_version`.

## 8.1 Exemples payload API (implementation)

Exemple `POST /training/runs`:

```json
{
  "run_id": "1f9f2a94-b923-4a24-a2c6-2f61a9f4f0da",
  "snapshot_id": 42,
  "agent_key": "SpaceMarine_Infantry_Troop_RangedSwarm",
  "training_config_name": "default",
  "rewards_config_name": "SpaceMarine_Infantry_Troop_RangedSwarm",
  "config_json": {"total_episodes": 60000},
  "config_hash_sha256": "d1e59c...f9",
  "git_commit": "a1b2c3d4",
  "python_version": "3.12.3",
  "torch_version": "2.4.0",
  "sb3_version": "2.3.2",
  "gym_version": "0.29.1",
  "global_seed": 12345,
  "env_seed_base": 200000,
  "numpy_seed": 12345,
  "torch_seed": 12345,
  "action_mask_version": "v2",
  "obs_norm_version": "vecnorm_2026_02_17",
  "reward_norm_version": null
}
```

## 8.2 Contrat API v1 (minimal obligatoire)

Metier:

- `GET /roster/snapshots/:id`
- `GET /roster/snapshots/:id/factions/:code/units`
- `POST /roster/compose`

Training/audit:

- `POST /training/runs`
- `POST /training/runs/:run_id/episodes`
- `POST /training/runs/:run_id/episodes/:episode_index/events:batch`
- `POST /training/runs/:run_id/artifacts/run`
- `POST /training/runs/:run_id/episodes/:episode_index/artifacts`
- `GET /training/runs/:run_id`
- `GET /training/runs/:run_id/episodes/:episode_index/replay`

Exemple `POST /training/runs/:run_id/episodes/:episode_index/events:batch`:

```json
{
  "batch_id": "0e215f83-4a77-4fab-8898-e8e9ea38139f",
  "events": [
    {
      "run_id": "1f9f2a94-b923-4a24-a2c6-2f61a9f4f0da",
      "snapshot_id": 42,
      "episode_index": 128,
      "step_index": 17,
      "phase_key": "shooting",
      "player": 0,
      "unit_id": 12,
      "action_id": 64,
      "action_type": "shoot",
      "action_mask_hash": "a5d8d1...",
      "reward": 0.35,
      "terminated": false,
      "truncated": false,
      "success": true,
      "event_schema_version": "1.0.0",
      "payload_json": {"target_id": 31, "damage": 2},
      "obs_ref": null
    }
  ]
}
```

## 9) Seuils de parite (Go/No-Go)

- ecart median `total_reward` <= 5%,
- ecart median `episode_len` <= 5%,
- ecart winrate <= 3 points,
- JS divergence actions/phase <= 0.05,
- 0 erreur validation snapshot/config,
- 0 perte de logs step-level.

Si un seuil echoue: STOP cutover + correction root cause + rerun complet.

## 10) Plan migration (execution)

1. Contrats + inventaire dependances.
2. Infra DB + migrations.
3. Repository/API.
4. Import TS -> DB + checks.
5. Shadow mode UnitRegistry legacy vs DB.
6. Training DB-first + telemetry/replay.
7. Engine DB-first.
8. Frontend DB-first.
9. Cutover + guardrails CI.

Guardrails CI:

- fail si training sans `snapshot_id`,
- fail si roster metier detecte en TS,
- fail si parser legacy runtime appele.

## 10.1 Definition of Ready (avant implementation)

Le prompt d'implementation doit refuser de demarrer si l'un des points manque:

- schema SQL v3.3 valide par l'equipe (sans reserve bloquante),
- endpoints API v1 confirmes,
- seuils parite PPO confirmes,
- ownership map assignee,
- politique de retention/rollback validee (RPO/RTO).

## 11) Ownership

- DB/Infra: migrations, partitionnement, retention, PITR.
- Backend: repository, validators, endpoints roster/training.
- Training/ML: instrumentation run/episode/step + parite PPO.
- Engine: UnitRegistry DB-backed + instanciation DTO.
- Frontend: roster UI API-only.
- QA/Ops: A/B seeds, dashboards SLO, verification zero-loss logs.

## 12) Rollback et gouvernance

- Avant cutover final: rollback legacy possible.
- Apres cutover final: restore PITR + republish snapshot precedent.

Objectifs ops:
- RPO <= 5 min,
- RTO <= 30 min.

Decision cutover/rollback:
- Lead technique + responsable ML + responsable ops.
- 1 critere critique rouge suffit pour rollback.

## 13) Change control (anti-version infinie)

A partir de cette v3.3:

- Les changements ne sont autorises que si:
  1) bug technique prouve,
  2) risque production prouve,
  3) exigence metier nouvelle validee.
- Toute proposition doit citer:
  - impact SQL,
  - impact code modules,
  - impact SLO/parite,
  - plan de migration des donnees.
- Si ces 4 points ne sont pas fournis, la proposition est rejetee.

## 14) Definition of done

Migration validee si:

- DB est source unique effective.
- Run/episode/step/replay persistes sans perte silencieuse.
- Cohérence snapshot garantie par contraintes DB.
- Parite PPO validee sur seuils fixes.
- Parser TS legacy retire du pipeline metier.
- Aucun fallback silencieux introduit.

