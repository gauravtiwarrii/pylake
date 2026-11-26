# PyLake architecture

## Current implementation

PyLake is a modular monolith with a separate database-backed pipeline worker:

- **Frontend:** Next.js App Router, React, and TypeScript.
- **API:** FastAPI with versioned routers and workspace-scoped authorization.
- **Application database:** PostgreSQL in the Compose setup; SQLite is supported for local tests and development.
- **Migrations:** Alembic migrations are the schema history and can be upgraded or downgraded.
- **Analytical execution:** DuckDB runs bounded, read-only SQL over authorized lakehouse versions.
- **Data processing:** Polars and PyArrow handle ingestion, schema operations, and Parquet output.
- **Object storage:** Local filesystem or S3-compatible MinIO through a storage adapter.
- **Pipeline execution:** A separate worker claims durable PostgreSQL/SQLite runs and persists step state.

The current Compose file is for local development only. It embeds development credentials and sets `APP_ENV=local`; it is not a production deployment configuration.

## Backend boundaries

- `backend/app/api/v1/` contains HTTP routing and request authorization.
- `backend/app/core/` contains settings, database/session configuration, security, and observability.
- `backend/app/models/` and `backend/alembic/` define persistence and schema migrations.
- `backend/app/services/` contains workspace-scoped application and orchestration logic.
- `backend/app/engines/` contains SQL validation and DuckDB execution.
- `backend/app/storage/` hides local and MinIO object-storage details.
- `frontend/app/` contains public and authenticated App Router pages; `frontend/lib/` contains API access.

Authentication uses Argon2 password hashes and opaque, revocable server-side sessions. Browser sessions use HTTP-only cookies, with a separate CSRF token for state-changing requests. No JWT is required by this session architecture.

## Dependency purpose

| Dependency | Purpose |
|---|---|
| FastAPI | Versioned REST API |
| Pydantic / Pydantic Settings | Validation and environment configuration |
| SQLAlchemy / Alembic | Application persistence and migrations |
| psycopg | PostgreSQL driver |
| DuckDB | Local analytical SQL execution |
| Polars / PyArrow | DataFrame processing and Parquet I/O |
| boto3 | S3-compatible MinIO access |
| argon2-cffi | Password hashing |
| Next.js / React / TypeScript | Frontend application |
| Tailwind CSS | Design system primitives |
| Lucide / Recharts / Monaco | Icons, analytics, and SQL editing |
| Pytest / HTTPX | Backend tests and API test clients |

The unused `python-jose[cryptography]` dependency was removed after the beta audit; no application import was found, and it was not part of the opaque-session flow. A post-removal `pip-audit` run reported no known vulnerabilities in installed dependencies; the local `pylake-backend` distribution itself is skipped because it is not published on PyPI. See [Release validation](RELEASE_VALIDATION.md).

## Known technical and release risks

1. **Mixed local and container storage paths** must remain isolated behind the storage abstraction.
2. **SQL injection and unsafe SQL** require allowlisting read-only operations and dataset-scoped relation names.
3. **Large uploads** require streaming, size enforcement, and persisted upload state.
4. **Schema inference** differs across CSV, JSON, Parquet, and XLSX formats; use explicit validation and normalized schemas.
5. **Concurrency** can cause inconsistent job state unless pipeline runs use durable database records and controlled transitions.
6. **Runtime support:** the container uses Python 3.12; other supported Python versions have not been comprehensively validated.
7. **Operations:** the Compose worker was found exited during beta validation. A retry-finalization bug was fixed and regression-tested, but the live worker has not been restarted against the existing database.
8. **Production deployment:** TLS termination, production secrets, hardened database/storage credentials, backup restoration, and deployment automation still require validation.
9. **End-to-end coverage:** frontend automated/browser workflows are not currently part of the test suite.

## Catalog and lineage

Catalog assets are lightweight workspace-scoped discovery records:

- `DATASET` assets represent original uploaded datasets and Bronze sources.
- `TABLE` assets represent lakehouse tables and their current layer.
- Catalog columns retain business documentation independently from physical schemas.
- Profile snapshots cache bounded profiling results and are linked to a specific dataset version.
- Schema history records the schema observed for each catalog version.
- Lineage edges persist source/target asset and execution metadata.

Lineage is recorded by successful promotions, transformations, SQL executions, and pipeline materializations. The graph and impact APIs never infer dependencies from asset names alone.
