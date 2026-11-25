# PyLake

PyLake is a modular, open-source lakehouse platform for ingestion, storage, transformation, SQL analytics, and data pipelines.

## Milestone 1 status

The initial repository scaffold includes:

- Next.js frontend shell
- FastAPI backend foundation
- PostgreSQL and MinIO Docker services
- Environment-based configuration
- Versioned API health endpoint
- Initial backend and frontend build configuration

## Milestone 2 authentication and workspaces

PyLake uses opaque, revocable server-side sessions stored in the `auth_sessions` table:

- Passwords are hashed with Argon2.
- Browser session cookies are HTTP-only and never stored in localStorage.
- A separate readable CSRF cookie and `X-CSRF-Token` header protect authenticated state changes.
- Sessions expire after 24 hours by default.
- Workspace access is enforced by membership and OWNER/ADMIN/EDITOR/VIEWER roles.
- Workspace IDs are scoped through membership queries to prevent cross-user access.

### Database migrations

Create the local environment and run:

```powershell
cd backend
.\.venv\Scripts\alembic.exe upgrade head
```

For PostgreSQL, set `DATABASE_URL` to a valid SQLAlchemy PostgreSQL URL before upgrading. SQLite remains supported for local tests.

Downgrade the latest Milestone 2 schema with:

```powershell
.\.venv\Scripts\alembic.exe downgrade base
```

### Authentication environment

| Variable | Purpose |
|---|---|
| `AUTH_SECRET` | Reserved application secret for future signed values |
| `AUTH_COOKIE_NAME` | Session cookie name |
| `CSRF_COOKIE_NAME` | CSRF cookie name |
| `SESSION_TTL_HOURS` | Session lifetime |
| `COOKIE_SECURE` | Set to `true` behind HTTPS |

### Milestone 2 API

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `POST /api/v1/workspaces`
- `GET /api/v1/workspaces`
- `GET /api/v1/workspaces/{workspace_id}`
- `PATCH /api/v1/workspaces/{workspace_id}`
- `DELETE /api/v1/workspaces/{workspace_id}`
- `GET /api/v1/workspaces/{workspace_id}/members`
- `POST /api/v1/workspaces/{workspace_id}/members`
- `PATCH /api/v1/workspaces/{workspace_id}/members/{member_id}`
- `DELETE /api/v1/workspaces/{workspace_id}/members/{member_id}`

## Local development

### Option 1: Run services with Docker Compose

Docker Compose is the recommended full-stack setup:

```powershell
docker compose up --build
```

- Frontend: http://localhost:3000
- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- MinIO console: http://localhost:9001

### Option 2: Run without Docker

Backend:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --port 8000
```

Set `DATABASE_URL` to a PostgreSQL URL or leave it unset to use SQLite for local development.

## Milestone 3 data ingestion

Supported formats:

- CSV
- JSON arrays and newline-delimited JSON
- Apache Parquet
- XLSX read-only worksheets

Upload metadata is stored in PostgreSQL. Dataset contents are stored outside the database using local filesystem storage or private MinIO storage.

### Storage configuration

| Variable | Purpose |
|---|---|
| `STORAGE_BACKEND` | `local` or `minio` |
| `LOCAL_STORAGE_DIR` | Local dataset storage root |
| `MAX_UPLOAD_SIZE_BYTES` | Maximum uploaded file size |
| `MINIO_ENDPOINT` | MinIO host and port |
| `MINIO_ACCESS_KEY` | MinIO access credential |
| `MINIO_SECRET_KEY` | MinIO secret credential |
| `MINIO_BUCKET` | Private bucket name |
| `MINIO_SECURE` | Use HTTPS for MinIO |

With `STORAGE_BACKEND=local`, no external storage service is required. With `STORAGE_BACKEND=minio`, configure MinIO and ensure the bucket remains private.

### Dataset API

- `POST /api/v1/workspaces/{workspace_id}/datasets/upload`
- `GET /api/v1/workspaces/{workspace_id}/datasets`
- `GET /api/v1/workspaces/{workspace_id}/datasets/{dataset_id}`
- `GET /api/v1/workspaces/{workspace_id}/datasets/{dataset_id}/preview`
- `GET /api/v1/workspaces/{workspace_id}/datasets/{dataset_id}/schema`
- `DELETE /api/v1/workspaces/{workspace_id}/datasets/{dataset_id}`
- `GET /api/v1/workspaces/{workspace_id}/datasets/{dataset_id}/download`
- `GET /api/v1/workspaces/{workspace_id}/datasets/{dataset_id}/status`

Dataset listings support `page`, `page_size`, and `search` query parameters. Previews are limited to 100 rows per request.

## Milestone 4 lakehouse

PyLake catalogs ingested datasets as Bronze, Silver, or Gold lakehouse tables.

- Bronze versions preserve the original uploaded source object.
- Silver and Gold promotions create standardized Snappy-compressed Parquet versions.
- Every promotion or transformation creates a new immutable version.
- Transformations record their source, configuration, output version, status, and creator.
- Quality summaries report rows, columns, duplicate rows, null counts, and empty columns.
- Storage usage sums actual `StorageObject` metadata by lakehouse layer.

### Lakehouse API

- `GET /api/v1/workspaces/{workspace_id}/lakehouse/tables`
- `GET /api/v1/workspaces/{workspace_id}/lakehouse/tables/{table_id}`
- `GET /api/v1/workspaces/{workspace_id}/lakehouse/tables/{table_id}/versions`
- `GET /api/v1/workspaces/{workspace_id}/lakehouse/tables/{table_id}/versions/{version_id}`
- `POST /api/v1/workspaces/{workspace_id}/lakehouse/tables/{table_id}/promote`
- `POST /api/v1/workspaces/{workspace_id}/lakehouse/tables/{table_id}/transform`
- `GET /api/v1/workspaces/{workspace_id}/lakehouse/tables/{table_id}/quality`
- `GET /api/v1/workspaces/{workspace_id}/lakehouse/storage/usage`

The lakehouse explorer is available at `/workspaces/{workspaceId}/lakehouse`.

Supported transformations include rename, drop, cast, deduplicate, filter, fill null, normalize names, calculated columns, select, and sort. Rollback is implemented safely as a new version from an older source version.

Partition columns are validated and recorded as metadata. Very high-cardinality partition columns are rejected. Physical partition directories are not yet generated by this milestone.

## Milestone 5 SQL analytics

PyLake uses a process-local DuckDB connection for each analytical query. Each connection executes in-memory and registers only authorized, workspace-scoped lakehouse Parquet versions.

Logical table names:

- Lakehouse tables are normalized to lowercase names with hyphens and spaces replaced by underscores.
- The latest completed Parquet version in the table is published by default.
- Bronze sources are not queryable unless promoted to Parquet.
- Catalog and table resolution always use workspace metadata.

Example:

```sql
SELECT name, score
FROM customers
WHERE score >= 20
ORDER BY score DESC
LIMIT 100;
```

### SQL restrictions

- Exactly one read-only `SELECT` or `UNION` statement
- No statements or functions that access files, databases, networks, extensions, or application storage
- Maximum 100,000 SQL characters
- Maximum 1,000 returned rows
- Configurable execution timeout and result-byte limit
- In-memory isolated connections with 512 MB memory and one thread

### SQL API

- `POST /api/v1/workspaces/{workspace_id}/sql/execute`
- `GET /api/v1/workspaces/{workspace_id}/sql/history`
- `GET /api/v1/workspaces/{workspace_id}/sql/history/{query_id}`
- `DELETE /api/v1/workspaces/{workspace_id}/sql/history/{query_id}`
- `GET /api/v1/workspaces/{workspace_id}/sql/catalog`
- `GET /api/v1/workspaces/{workspace_id}/sql/catalog/{table_name}/schema`
- `GET /api/v1/workspaces/{workspace_id}/sql/saved`
- `POST /api/v1/workspaces/{workspace_id}/sql/saved`
- `PATCH /api/v1/workspaces/{workspace_id}/sql/saved/{saved_query_id}`
- `DELETE /api/v1/workspaces/{workspace_id}/sql/saved/{saved_query_id}`

The SQL editor is available at `/workspaces/{workspaceId}/sql`.

DuckDB provides local analytical SQL rather than distributed execution or complete PostgreSQL compatibility.

## Milestone 6 pipeline orchestration

Pipeline runs are queued in PostgreSQL/SQLite and executed by a separate database-backed worker. The worker atomically claims `QUEUED` runs, executes dependency-ordered steps, persists step state, and recovers stale `RUNNING` jobs after a configurable timeout.

Supported step types:

- `SOURCE_DATASET`
- `TRANSFORM`
- `DATA_QUALITY`
- `SQL_QUERY`
- `MATERIALIZE`

The pipeline editor is available at `/workspaces/{workspaceId}/pipelines`.

### Pipeline API

- `POST /api/v1/workspaces/{workspace_id}/pipelines`
- `GET /api/v1/workspaces/{workspace_id}/pipelines`
- `GET /api/v1/workspaces/{workspace_id}/pipelines/{pipeline_id}`
- `PATCH /api/v1/workspaces/{workspace_id}/pipelines/{pipeline_id}`
- `DELETE /api/v1/workspaces/{workspace_id}/pipelines/{pipeline_id}`
- `POST /api/v1/workspaces/{workspace_id}/pipelines/{pipeline_id}/validate`
- `POST /api/v1/workspaces/{workspace_id}/pipelines/{pipeline_id}/runs`
- `GET /api/v1/workspaces/{workspace_id}/pipelines/{pipeline_id}/runs`
- `GET /api/v1/workspaces/{workspace_id}/pipelines/runs/{run_id}`
- `POST /api/v1/workspaces/{workspace_id}/pipelines/runs/{run_id}/cancel`
- `GET /api/v1/workspaces/{workspace_id}/pipelines/runs/{run_id}/logs`
- `POST /api/v1/workspaces/{workspace_id}/pipelines/{pipeline_id}/schedules`
- `GET /api/v1/workspaces/{workspace_id}/pipelines/{pipeline_id}/schedules`
- `PATCH /api/v1/workspaces/{workspace_id}/pipelines/schedules/{schedule_id}`
- `DELETE /api/v1/workspaces/{workspace_id}/pipelines/schedules/{schedule_id}`

### Worker commands

Local worker:

```powershell
cd backend
python -m app.worker
```

Docker Compose worker:

```powershell
docker compose up --build worker
```

The API and worker share the PostgreSQL database. Scheduled runs use standard cron expressions and explicit IANA timezones.

Frontend:

```powershell
cd frontend
npm install
npm run dev
```
