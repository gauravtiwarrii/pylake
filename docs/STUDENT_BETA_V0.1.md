# PyLake Student Beta v0.1 readiness

## Decision

**Not ready for release.** This is a readiness assessment, not a release announcement. Do not use the current build with sensitive, regulated, confidential, or production data. No beta tag or production deployment has been created.

The detailed evidence and blocking gates are in [release validation](RELEASE_VALIDATION.md). Architecture is summarized in [the architecture document](ARCHITECTURE.md).

## Implemented product

PyLake is a Next.js frontend and FastAPI modular backend. PostgreSQL/Alembic persist accounts, workspaces, datasets, versions, saved SQL, query history, pipelines, schedules, audit events, and worker state. SQLite is used for local testing. DuckDB runs bounded read-only SQL over workspace-authorized lakehouse versions; Polars and PyArrow handle data processing and Parquet output. Uploaded and derived files use local filesystem storage or an S3-compatible adapter. A separate worker claims and executes persisted pipeline runs.

Authentication uses Argon2 password hashes, opaque server-side sessions, HTTP-only cookies, and CSRF protection for state-changing requests. Workspace membership and roles scope API access.

## Local development

The checked-in Compose stack is intended only for local development. It contains fixed development credentials and `APP_ENV=local`; do not expose its ports publicly or treat it as a production deployment.

From the repository root in PowerShell:

```powershell
docker compose up --build -d
docker compose ps -a
```

Open:

- Frontend: <http://localhost:3000>
- API health: <http://localhost:8000/api/v1/health>
- Local API documentation: <http://localhost:8000/docs>

The API and worker run Alembic migrations during container startup. For a local migration check:

```powershell
docker compose exec backend python -m alembic current
```

For direct backend development:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
python -m alembic upgrade head
python -m pytest tests
```

Run the frontend separately with:

```powershell
cd frontend
npm ci
npm run dev
```

See [student onboarding](STUDENT_BETA_ONBOARDING.md) and [README](../README.md) for a first-use path and API reference.

## Release gates

| Area | Current status |
|---|---|
| Host backend suite | **PASS** — 42 tests |
| Frontend lint, typecheck, production build | **PASS** |
| Frontend dependency audit | **PASS** — 0 vulnerabilities reported |
| Fresh SQLite and PostgreSQL migration reversibility | **PASS** |
| Python dependency audit | **PASS** — no known vulnerabilities in installed dependencies after removing the unused JOSE chain; scanner skips the local project distribution |
| Live worker operation | **BLOCKED** — worker exited; one run remains `RUNNING` in the current database |
| Current Docker rebuild and service recheck | **BLOCKED** — BuildKit returned EOF; later route checks timed out and Docker daemon did not respond |
| Browser-driven product workflow | **NOT TESTED** |
| MinIO storage path | **NOT TESTED** |
| Populated database and object-store restore | **NOT TESTED** |
| Production deployment and rollback | **BLOCKED** |
| Privacy/terms publication | **BLOCKED** — drafts require operator and legal review |
| CI release workflow | **NOT PRESENT** |

## Known limitations and beta safeguards

- The current source fixes two pipeline-worker defects, but the running worker image has not been rebuilt and safely restarted. The existing `RUNNING` record must be inspected and recovered by an operator; do not delete or requeue it blindly.
- `docker-compose.yml` is not production configuration. There is no verified TLS ingress, secrets manager, production database/storage credential setup, or deployment automation.
- `pip-audit` skips the local `pylake-backend` distribution because it is not published on PyPI; the installed dependency scan found no known vulnerabilities.
- Backend API integration tests exercise real services with isolated SQLite and temporary local storage. Browser-based auth/workspace workflows have not been tested.
- MinIO startup, object-store backup/restore, and a populated PostgreSQL disaster-recovery drill remain unverified.
- Do not upload student personal data or other sensitive material until the privacy notice, terms, retention, deletion, and incident-response details are finalized.

Related operational documents:

- [Backup and restore](BACKUP_RESTORE.md)
- [Rollback and recovery](ROLLBACK.md)
- [Privacy notice draft](PRIVACY_NOTICE_DRAFT.md)
- [Student beta terms draft](TERMS_DRAFT.md)
- [Feedback guidance](BETA_FEEDBACK.md)
