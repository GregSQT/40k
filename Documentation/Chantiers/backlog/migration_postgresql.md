# Migration PostgreSQL — spec et plan d'exécution (à re-cadrer avant ouverture)

> **Objet** : spec v3.3 (figée) et plan d'exécution de la migration vers PostgreSQL comme source unique de vérité métier (roster, télémétrie PPO, audit/replay).
> **Chantier jamais commencé — SPEC PRÉ-V11 (mars 2026).** Le schéma SQL, les contrats (ingestion, parité, API) et la gouvernance restent réutilisables ; le scope training est à refaire : la spec visait `ai/macro_training_env.py`, supprimé par la refonte V11 — voir « Ce qui est périmé ».
> Sources absorbées : `Database/DB_migration.md` (spec v3.3) et `Database/DB_migration_prompt.md` (prompt d'exécution), destinées à `Documentation/Archives/docs/` avec bandeau retour.
> L'état des chantiers fait foi dans [Documentation/Roadmap/infra.md#postgresql](../../Roadmap/infra.md#postgresql), jamais ici.

---

# Ce qui reste valable

## Décision et principes

PostgreSQL devient la source unique de vérité métier pour :
- roster,
- télémétrie training PPO,
- audit et replay.

Décision : GO, avec migration par phases, parité PPO chiffrée obligatoire, et cutover protégé.

Principes non négociables :

- Single source of truth métier : DB uniquement.
- Aucune valeur implicite, aucun fallback silencieux.
- Cohérence `snapshot_id` garantie par contraintes DB.
- Contrats API versionnés.
- Shadow mode obligatoire avant suppression legacy.
- Tout écart hors seuil ⇒ stop cutover + correction root cause.

## Périmètre du cutover (re-cadré post-V11)

Le cutover ne concerne pas uniquement `frontend/src/roster/**`. Il couvre aussi :

- [`ai/unit_registry.py`](../../../ai/unit_registry.py) — fin du parsing TS runtime ; objectif toujours d'actualité : `class UnitRegistry` scanne et parse encore les fichiers `.ts` à chaud (`def _discover_all_units`, `def _parse_unit_file`) ;
- [`services/api_server.py`](../../../services/api_server.py) — aucun endpoint `/roster/snapshots` ou `/roster/compose` n'existe encore ;
- le pipeline training/replay — **partie à re-cadrer** : la spec citait `ai/macro_training_env.py`, supprimé ; les porteurs actuels du cycle épisode/step sont `class W40KEngine` ([`engine/w40k_core.py`](../../../engine/w40k_core.py)), `class StepLogger` ([`ai/step_logger.py`](../../../ai/step_logger.py)), les wrappers de [`ai/env_wrappers.py`](../../../ai/env_wrappers.py), plus [`ai/train.py`](../../../ai/train.py) et [`ai/training_callbacks.py`](../../../ai/training_callbacks.py) qui existent toujours ;
- l'instanciation runtime côté engine.

## Schéma SQL v3.3 (stable pour implémentation)

### Catalogue roster

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

### Training / replay (cohérence + idempotence)

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

Note post-V11 : les colonnes `training_config_name` et `rewards_config_name` restent valides comme concepts — les noms réels se lisent dans `config/agents/<agent>/` au moment de l'implémentation, jamais dans ce document.

## Contrat d'ingestion step-level

Mode officiel : **at-least-once + idempotence**.

- Writer en batch asynchrone.
- Dédupe événement : PK `(run_id, episode_index, step_index)`.
- Dédupe requête : `ingestion_batch(batch_id)`.
- SQL write : `INSERT ... ON CONFLICT DO NOTHING`.
- Retry borné + backoff exponentiel.
- DLQ si échec répété.
- Échec final ⇒ `training_run.status='failed'` + `error_reason` obligatoire.

Interdit : perte silencieuse de logs.

## SLO / SLA

- `POST /roster/compose` p95 < 120 ms, taux erreur < 0.5%.
- `POST /training/.../events:batch` p95 < 200 ms, taux erreur < 0.5%.
- Backlog writer < 10 000 events en nominal.
- Perte silencieuse de logs : 0.

## Partitionnement et rétention

### Stratégie de partitionnement (décision explicite)

La v3.3 retient `PARTITION BY HASH (run_id)` pour limiter les hotspots write.

Règle de décision opérationnelle :
- Si la rétention temporelle devient le besoin dominant (purge rapide par période), migrer vers `PARTITION BY RANGE (created_at)` mensuel.
- Si la priorité reste le débit d'écriture et la répartition uniforme, conserver HASH.

Décision immédiate :
- **Conserver HASH en v1.**
- Ouvrir une tâche de revue après 14 jours de charge réelle (latence write, coût purge, taille partitions).

### Rétention

- `training_step_event` : rétention 90 jours.
- `episode_artifact` : 180 jours.
- `run_artifact` : golden/release long terme ; standard 180 jours.
- Purge/archive quotidienne.

Ops : si le job de rétention échoue 3 jours consécutifs ⇒ alerte critique.

## Contrat de reproductibilité PPO

Run certifiable si présent :

- `snapshot_id` publié,
- `config_json` + `config_hash_sha256`,
- seeds (`global`, `env_seed_base`, `numpy`, `torch`),
- `git_commit`,
- versions runtime (`python`, `torch`, `sb3`, `gym`),
- `action_mask_version`, `obs_norm_version`, `reward_norm_version`.

## Contrat API v1 (minimal obligatoire)

Métier :

- `GET /roster/snapshots/:id`
- `GET /roster/snapshots/:id/factions/:code/units`
- `POST /roster/compose`

Training/audit :

- `POST /training/runs`
- `POST /training/runs/:run_id/episodes`
- `POST /training/runs/:run_id/episodes/:episode_index/events:batch`
- `POST /training/runs/:run_id/artifacts/run`
- `POST /training/runs/:run_id/episodes/:episode_index/artifacts`
- `GET /training/runs/:run_id`
- `GET /training/runs/:run_id/episodes/:episode_index/replay`

### Exemples de payload (forme du contrat — valeurs à régénérer)

Les valeurs des exemples ci-dessous (agent_key, noms de config, versions runtime) datent d'avant V11 : seule la **forme** (champs, types) est normative. Les valeurs actuelles se lisent dans `config/agents/` et l'environnement au moment de l'implémentation.

Exemple `POST /training/runs` :

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

Exemple `POST /training/runs/:run_id/episodes/:episode_index/events:batch` :

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

## Seuils de parité (Go/No-Go)

- Écart médian `total_reward` ≤ 5%,
- écart médian `episode_len` ≤ 5%,
- écart winrate ≤ 3 points,
- JS divergence actions/phase ≤ 0.05,
- 0 erreur validation snapshot/config,
- 0 perte de logs step-level.

Si un seuil échoue : STOP cutover + correction root cause + rerun complet.

## Plan de cutover (exécution)

1. Contrats + inventaire dépendances.
2. Infra DB + migrations.
3. Repository/API.
4. Import TS → DB + checks.
5. Shadow mode UnitRegistry legacy vs DB.
6. Training DB-first + telemetry/replay.
7. Engine DB-first.
8. Frontend DB-first.
9. Cutover + guardrails CI.

Guardrails CI :

- fail si training sans `snapshot_id`,
- fail si roster métier détecté en TS,
- fail si parser legacy runtime appelé.

### Definition of Ready (avant implémentation)

Le prompt d'implémentation doit refuser de démarrer si l'un des points manque :

- schéma SQL v3.3 validé (sans réserve bloquante),
- endpoints API v1 confirmés,
- seuils parité PPO confirmés,
- ownership map assignée,
- politique de rétention/rollback validée (RPO/RTO),
- **[ajout post-V11]** scope training re-confronté au code (voir « Ce qui est périmé »).

## Ownership

- DB/Infra : migrations, partitionnement, rétention, PITR.
- Backend : repository, validators, endpoints roster/training.
- Training/ML : instrumentation run/episode/step + parité PPO.
- Engine : UnitRegistry DB-backed + instanciation DTO.
- Frontend : roster UI API-only.
- QA/Ops : A/B seeds, dashboards SLO, vérification zero-loss logs.

## Rollback et gouvernance

- Avant cutover final : rollback legacy possible.
- Après cutover final : restore PITR + republish snapshot précédent.

Objectifs ops :
- RPO ≤ 5 min,
- RTO ≤ 30 min.

Décision cutover/rollback :
- Lead technique + responsable ML + responsable ops.
- 1 critère critique rouge suffit pour rollback.

## Change control (anti-version infinie)

À partir de la v3.3 :

- Les changements ne sont autorisés que si :
  1) bug technique prouvé,
  2) risque production prouvé,
  3) exigence métier nouvelle validée.
- Toute proposition doit citer : impact SQL, impact code modules, impact SLO/parité, plan de migration des données.
- Si ces 4 points ne sont pas fournis, la proposition est rejetée.

## Definition of Done

Migration validée si :

- DB est source unique effective.
- Run/episode/step/replay persistés sans perte silencieuse.
- Cohérence snapshot garantie par contraintes DB.
- Parité PPO validée sur seuils fixés.
- Parser TS legacy retiré du pipeline métier.
- Aucun fallback silencieux introduit.

---

# Ce qui est périmé et pourquoi (preuves)

1. **`ai/macro_training_env.py` (scope §2 de la spec, étape 5 du prompt)** — fichier supprimé par la refonte V11. Preuve : le fichier n'existe pas dans `ai/` ; l'unique occurrence du nom dans le code est un commentaire de [`ai/train.py`](../../../ai/train.py) qui atteste sa mort (« Preuve de mort au-dela des stubs : ai/macro_training_env.py (les wrappers macro) n'existe pas », près de `def resolve_turn_step_limit`). Les porteurs actuels du cycle épisode/step sont `class W40KEngine` (gym.Env, [`engine/w40k_core.py`](../../../engine/w40k_core.py)), `class StepLogger` ([`ai/step_logger.py`](../../../ai/step_logger.py)) et les wrappers `class BotControlledEnv` / `SelfPlayWrapper` ([`ai/env_wrappers.py`](../../../ai/env_wrappers.py)). Toute instrumentation `training_episode` / `training_step_event` doit être re-spécifiée contre ces modules.
2. **Valeurs des exemples de payload** — `agent_key: "SpaceMarine_Infantry_Troop_RangedSwarm"` relève du nommage par faction/rôle pré-V11 ; les agents actuels se lisent dans `config/agents/` (ex. `ArmageddonAgent`, `CoreAgent`). `training_config_name: "default"` ne correspond plus aux configs actuelles (`config/agents/<agent>/`). Les versions runtime de l'exemple sont illustratives. La forme des payloads reste normative, les valeurs non.
3. **Rien d'autre n'est invalidé par le code** : `ai/unit_registry.py`, `services/api_server.py`, `ai/train.py`, `ai/training_callbacks.py` et `frontend/src/roster/**` existent tous ; le parsing TS runtime que la migration doit éteindre est toujours vivant (`def _parse_unit_file` dans `ai/unit_registry.py`), et aucun endpoint roster/training de l'API v1 n'existe encore dans `services/api_server.py`.

---

# Prompt d'exécution (à régénérer après re-cadrage)

> **Ne pas exécuter tel quel.** Ce prompt dérive de la spec pré-V11 ; son étape 5 cible `ai/macro_training_env.py`, supprimé (voir ci-dessus). À régénérer depuis ce document une fois le scope training re-cadré. Conservé ici comme trame.

<details>
<summary>Prompt v1 (péremption : étape 5)</summary>

## Objectif

Migrer vers PostgreSQL comme source unique pour :
- roster métier,
- télémétrie PPO (run/episode/step),
- audit/replay.

## Contraintes non négociables

- Aucun fallback silencieux.
- `snapshot_id` obligatoire et cohérent de `training_run` à `training_step_event`.
- Ingestion logs : at-least-once + idempotence (`ON CONFLICT DO NOTHING`).
- Zéro perte silencieuse de step logs.
- Respect strict des seuils de parité PPO avant cutover.

## Ordre d'implémentation (obligatoire)

1. **Migrations SQL**
   - Créer `migrations/001_init.sql` selon le schéma v3.3 ci-dessus.
   - Inclure PK/FK composites, `ingestion_batch`, `run_artifact`, `episode_artifact`, indexes obligatoires.

2. **Couche DB roster**
   - Implémenter `ai/roster_db/repository.py`
   - Implémenter `ai/roster_db/validators.py`
   - Implémenter `ai/roster_db/service.py`
   - Ajouter `ai/roster_db/models.py` si nécessaire

3. **API v1**
   - Dans `services/api_server.py`, ajouter/adapter les endpoints du « Contrat API v1 » ci-dessus.

4. **Import roster TS → DB**
   - Créer `scripts/import_roster_ts_to_db.py`.
   - Vérifier cardinalités, références, et équivalence stats/armes/rules.

5. **Training instrumentation** — **PÉRIMÉ, à récrire** :
   - `ai/train.py` : lifecycle `training_run` (running/completed/failed/aborted) — toujours valide.
   - ~~`ai/macro_training_env.py` : création `training_episode` + events step-level~~ — fichier supprimé ; re-spécifier contre `class W40KEngine` (`engine/w40k_core.py`) et `class StepLogger` (`ai/step_logger.py`).
   - `ai/training_callbacks.py` : batch flush, retry, DLQ, erreurs explicites — module toujours présent, rôle à confirmer au re-cadrage.

6. **Shadow mode + parité**
   - Comparer legacy vs DB-first avec seeds fixes.
   - Bloquer cutover si seuils non respectés.

## Seuils Go/No-Go, guardrails CI, Definition of Done

Identiques aux sections « Seuils de parité (Go/No-Go) », « Plan de cutover » et « Definition of Done » ci-dessus (le prompt source les dupliquait verbatim).

</details>

---

# Correspondance des sources

| Source | Ancien § | Section actuelle |
|---|---|---|
| `DB_migration.md` | « Pourquoi on tournait en rond » | Historique et sources |
| `DB_migration.md` | §1 Decision | Décision et principes |
| `DB_migration.md` | §2 Scope reel (non-negociable) | Périmètre du cutover (re-cadré post-V11) |
| `DB_migration.md` | §3 Principes | Décision et principes |
| `DB_migration.md` | §4 Schema SQL v3.3 (4.1, 4.2) | Schéma SQL v3.3 |
| `DB_migration.md` | §5 Ingestion step-level | Contrat d'ingestion step-level |
| `DB_migration.md` | §6 SLO / SLA | SLO / SLA |
| `DB_migration.md` | §7 Retention et volumetrie (7.1, 7.2) | Partitionnement et rétention |
| `DB_migration.md` | §8 Contrat reproductibilite PPO | Contrat de reproductibilité PPO |
| `DB_migration.md` | §8.1 Exemples payload API | Contrat API v1 → Exemples de payload |
| `DB_migration.md` | §8.2 Contrat API v1 | Contrat API v1 (minimal obligatoire) |
| `DB_migration.md` | §9 Seuils de parite (Go/No-Go) | Seuils de parité (Go/No-Go) |
| `DB_migration.md` | §10 Plan migration | Plan de cutover (exécution) |
| `DB_migration.md` | §10.1 Definition of Ready | Plan de cutover → Definition of Ready |
| `DB_migration.md` | §11 Ownership | Ownership |
| `DB_migration.md` | §12 Rollback et gouvernance | Rollback et gouvernance |
| `DB_migration.md` | §13 Change control | Change control (anti-version infinie) |
| `DB_migration.md` | §14 Definition of done | Definition of Done |
| `DB_migration_prompt.md` | (document entier) | Prompt d'exécution (à régénérer après re-cadrage) |

---

# Historique et sources

- **Spec v3.3 (mars 2026)** : version de référence figée après une boucle v1→v3.3 causée par 4 défauts identifiés — conflit de niveau de détail (vision produit mêlée au SQL d'exécution), contradictions techniques (partitionnement annoncé avec contraintes incompatibles), absence de contrat d'acceptation, absence de gouvernance de changement. La v3.3 a fixé ces points ; sa section « Change control » en est la conséquence directe.
- **Péremption V11** : la refonte V11 a supprimé `ai/macro_training_env.py` et réorganisé le pipeline training autour de `class W40KEngine` ; [Roadmap/infra.md#postgresql](../../Roadmap/infra.md#postgresql) a acté « re-confronter au code avant » reprise.
- Sources absorbées : `Documentation/Chantiers/backlog/Database/DB_migration.md` (spec v3.3, 487 l.) et `Documentation/Chantiers/backlog/Database/DB_migration_prompt.md` (prompt d'exécution v1, 77 l.) — destination `Documentation/Archives/docs/`.
