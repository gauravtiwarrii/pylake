# Milestone 7.1 release validation

## Environment

Host validation was attempted on Windows because Docker and WSL were unavailable at the start.

- Docker Desktop was installed, but the Docker engine could not start.
- WSL could not be enabled because elevated Windows permissions were unavailable.
- Native DuckDB and SQLAlchemy DLL loading is blocked by Windows Application Control.
- PostgreSQL, MinIO, and Docker Compose integration were therefore not executable.

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

## Blocked validation

The following checks were not marked passed:

- Backend full suite on this host because native DuckDB/SQLAlchemy imports are blocked.
- Docker/PostgreSQL/MinIO startup.
- Real DuckDB SELECT/JOIN/CTE/window integration.
- End-to-end pipeline worker execution.
- Multi-worker and stale-job integration.
- Scheduler restart and missed-occurrence integration.
- Backup restore of live PostgreSQL and object storage.

## Reproducible fixes applied

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
