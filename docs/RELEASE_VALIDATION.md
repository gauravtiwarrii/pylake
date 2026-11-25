# Milestone 7.1 release validation

## Environment

Host validation was run on Windows with Docker Desktop and Linux containers enabled.

- Native DuckDB and SQLAlchemy tests pass in the Linux container.
- PostgreSQL, backend, frontend, and worker services pass core Compose startup.
- MinIO remains optional because no supported public image endpoint was available in this environment.

The Linux/Docker release command is:

```powershell
docker compose up --build
```

For migration, backend, worker, and native-engine validation in Linux:

```powershell
docker compose exec backend alembic upgrade head
docker compose exec backend pytest
docker compose exec backend python -m app.worker
```

## Executed validation

- Fresh SQLite migration through revision `20261125_0007`: passed.
- Pipeline graph and observability unit tests: passed.
- SQLGlot dangerous-external-access rejection tests: passed.
- Frontend ESLint: passed.
- Frontend TypeScript typecheck: passed.
- Frontend production build: passed.
- Docker Desktop engine started and responded.
- Core Compose stack passed: PostgreSQL, backend, frontend, and worker.
- PostgreSQL migration head verified at `20261125_0007`.
- Live backend health: `200 OK`.
- Live frontend login route: `200 OK`.
- Live worker heartbeat records verified in PostgreSQL.
- Full Linux backend suite: `37 passed`.
- Native DuckDB SQL tests passed after Linux integration fixes.

## Blocked validation

The following checks were not marked passed:

- Backend full suite on this host because native DuckDB/SQLAlchemy imports are blocked.
- MinIO startup and MinIO-specific integration (Docker Hub namespace unavailable; optional Quay profile requires registry access).
- Complete end-to-end pipeline worker orchestration under multiple workers.
- End-to-end pipeline worker execution.
- Multi-worker and stale-job integration.
- Scheduler restart and missed-occurrence integration.
- Backup restore of live PostgreSQL and object storage.

## Reproducible fixes applied

- Added a frontend `public` directory required by the standalone Docker runner.
- Backend and worker images now copy Alembic and run migrations before application startup.
- Backend images now install development dependencies and copy tests for container validation.
- Added an optional MinIO Compose profile so core services are not blocked by registry availability.
- Fixed DuckDB temporary view registration and bounded result serialization.
- Added CTE alias exclusion to catalog resolution.

- Pipeline schedule occurrences now have unique database identity.
- Scheduled missed occurrences are recovered individually.
- Worker claims use an atomic update in addition to row locking.
- Materialized pipeline outputs use run-and-step-specific storage keys.
- Stale worker execution resets running step records.
- Running pipeline runs refresh cancellation state.
- Pipeline steps have configurable timeout enforcement on Linux workers.
- External DuckDB file/network table functions are rejected by SQLGlot validation and keyword guards.
- Production startup rejects SQLite, wildcard CORS, weak secrets, and insecure cookies.
- PostgreSQL authentication limits use transaction advisory locks.
