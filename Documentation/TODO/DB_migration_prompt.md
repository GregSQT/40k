# Prompt implementation - Migration PostgreSQL (v1)

Utilise `Documentation/DB_migration33.md` comme source de verite.

## Objectif

Migrer vers PostgreSQL comme source unique pour:
- roster metier,
- telemetry PPO (run/episode/step),
- audit/replay.

## Contraintes non-negociables

- Aucun fallback silencieux.
- `snapshot_id` obligatoire et coherent de `training_run` a `training_step_event`.
- Ingestion logs: at-least-once + idempotence (`ON CONFLICT DO NOTHING`).
- Zéro perte silencieuse de step logs.
- Respect strict des seuils de parite PPO avant cutover.

## Ordre d'implementation (obligatoire)

1. **Migrations SQL**
   - Creer `migrations/001_init.sql` selon schema v3.3 de `DB_migration33.md`.
   - Inclure PK/FK composites, `ingestion_batch`, `run_artifact`, `episode_artifact`, indexes obligatoires.

2. **Couche DB roster**
   - Implementer `ai/roster_db/repository.py`
   - Implementer `ai/roster_db/validators.py`
   - Implementer `ai/roster_db/service.py`
   - Ajouter `ai/roster_db/models.py` si necessaire

3. **API v1**
   - Dans `services/api_server.py`, ajouter/adapter:
     - `GET /roster/snapshots/:id`
     - `GET /roster/snapshots/:id/factions/:code/units`
     - `POST /roster/compose`
     - `POST /training/runs`
     - `POST /training/runs/:run_id/episodes`
     - `POST /training/runs/:run_id/episodes/:episode_index/events:batch`
     - `POST /training/runs/:run_id/artifacts/run`
     - `POST /training/runs/:run_id/episodes/:episode_index/artifacts`

4. **Import roster TS -> DB**
   - Creer `scripts/import_roster_ts_to_db.py`.
   - Verifier cardinalites, references, et equivalence stats/armes/rules.

5. **Training instrumentation**
   - `ai/train.py`: lifecycle `training_run` (running/completed/failed/aborted).
   - `ai/macro_training_env.py`: creation `training_episode` + events step-level.
   - `ai/training_callbacks.py`: batch flush, retry, DLQ, erreurs explicites.

6. **Shadow mode + parite**
   - Comparer legacy vs DB-first avec seeds fixes.
   - Bloquer cutover si seuils non respectes.

## Seuils Go/No-Go (bloquants)

- ecart median `total_reward` <= 5%
- ecart median `episode_len` <= 5%
- ecart winrate <= 3 points
- JS divergence actions/phase <= 0.05
- 0 erreur validation snapshot/config
- 0 perte step logs

## Guardrails CI (a mettre avant cutover final)

- fail si training sans `snapshot_id`
- fail si roster metier detecte en TS
- fail si parser legacy runtime est appele

## Definition of done

- DB source unique effective.
- Run/episode/step/replay persistés sans perte silencieuse.
- Reproductibilite run certifiable.
- Parite PPO validee.
- Parser TS legacy retire du pipeline metier.
