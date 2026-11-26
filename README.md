# PyLake

PyLake is a modular, open-source lakehouse platform for ingestion, storage, transformation, SQL analytics, and data pipelines.

> **Beta readiness:** Student Beta v0.1 is not yet cleared for release. See [the readiness and release-gate report](docs/STUDENT_BETA_V0.1.md) and [validation evidence](docs/RELEASE_VALIDATION.md). The Compose configuration is local-development only, not production deployment configuration.

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
- MinIO console: http://localhost:9001 when the optional `minio` profile is enabled

The Compose file starts PostgreSQL, the API, frontend, and pipeline worker. Check `docker compose ps -a` after startup; the worker must remain running for pipeline execution. The checked-in Compose file uses local development credentials and `APP_ENV=local`. Do not expose it publicly or use it for production.

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

## Vercel deployment

The root `vercel.json` deploys the FastAPI backend and Next.js frontend as Vercel services. Requests under `/api/*` are routed to the backend; all other paths go to the frontend. The frontend calls the backend through this same-origin public route, so no service bindings are needed. Leave `NEXT_PUBLIC_API_URL` unset on Vercel; local development continues to use `http://localhost:8000` by default.

Configure production environment variables for the backend, including `APP_ENV=production`, `DATABASE_URL`, `AUTH_SECRET`, and `COOKIE_SECURE=true`. Use a managed PostgreSQL database and durable, remotely accessible object storage; Vercel function filesystems are ephemeral, so do not use local storage for deployed datasets. The pipeline worker is a continuously running process and must be deployed separately with access to the same database and object storage.

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

## Milestone 8 data catalog and lineage

The workspace catalog discovers uploaded datasets and Silver/Gold lakehouse tables. Catalog entries include descriptions, tags, ownership, format, layer, schema, and version metadata.

Authorized editors can update asset and column documentation. Profiling uses a bounded 10,000-row sample for available column statistics and records null counts, distinct counts, numeric minimum/maximum/mean, and uncomputed fields when unavailable.

Catalog APIs:

- `GET /api/v1/workspaces/{workspace_id}/catalog`
- `GET /api/v1/workspaces/{workspace_id}/catalog/{asset_id}`
- `PATCH /api/v1/workspaces/{workspace_id}/catalog/{asset_id}`
- `PATCH /api/v1/workspaces/{workspace_id}/catalog/{asset_id}/columns/{column_name}`
- `GET /api/v1/workspaces/{workspace_id}/catalog/{asset_id}/profile`
- `GET /api/v1/workspaces/{workspace_id}/catalog/{asset_id}/schema`
- `GET /api/v1/workspaces/{workspace_id}/catalog/{asset_id}/lineage`
- `GET /api/v1/workspaces/{workspace_id}/catalog/{asset_id}/impact`

The catalog is available at `/workspaces/{workspaceId}/catalog`. Lineage records actual Bronze-to-Silver/Gold promotions, transformations, successful SQL query sources, and successful pipeline materializations. Failed executions are not represented as successful output lineage.

## Milestone 7 observability and hardening

PyLake emits structured JSON logs with request IDs and logs only redacted operational context. Sensitive field names and bearer credentials are redacted.

Worker health is persisted in `worker_heartbeats`. Pipeline runs include retry counts, maximum retries, and failure classes. Stale workers and stale running jobs are detected through heartbeat and claim timestamps.

### Observability APIs

- `GET /api/v1/workspaces/{workspace_id}/pipelines/metrics`
- `GET /api/v1/workspaces/{workspace_id}/workers/health`
- `GET /api/v1/workspaces/{workspace_id}/audit?page=1&page_size=25`

Audit APIs require workspace ADMIN or OWNER access. Audit records contain actor, action, target, safe metadata and UTC timestamp.

Authentication login attempts use database-backed rate-limit events, allowing protection to work across API processes when PostgreSQL is used.

### Hardening variables

- `LOG_LEVEL`
- `AUTH_RATE_LIMIT_ATTEMPTS`
- `AUTH_RATE_LIMIT_WINDOW_SECONDS`
- `PIPELINE_STEP_TIMEOUT_SECONDS`
- `PIPELINE_MAX_RETRIES`
- `WORKER_STALE_SECONDS`
- `PIPELINE_JOB_CLAIM_SECONDS`

Backup and restore procedures are documented in [docs/BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md).

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

## Milestone 9 AI Copilot

The optional workspace-aware Copilot supports streamed chat, dataset profiling, SQL explanation/debugging, and validated SQL, transformation, and pipeline drafts. AI is disabled by default. Generated SQL is validated as read-only and is never executed by the Copilot; transformation and pipeline suggestions are returned as drafts and are never applied or run automatically.

The provider is configured on the backend, not in the browser. Supported providers are OpenAI-compatible chat-completion APIs and Ollama. Configure `AI_PROVIDER`, `AI_MODEL`, and, for an OpenAI-compatible provider, `AI_API_KEY`; use `AI_BASE_URL` for a compatible endpoint or an Ollama server. Keep credentials server-side and never commit real values. The full environment reference and setup steps are in [the AI Copilot setup guide](docs/AI_COPILOT_SETUP.md).

Workspace conversations, messages, and request usage metadata are stored in the application database. Context is membership-scoped and limited to workspace names, dataset/table schemas and counts, pipeline status, query status metadata, and the current SQL after literal redaction. Dataset profile explanations use aggregate statistics only; raw dataset rows and storage keys are not sent as chat context. Provider requests are external when an external provider is configured; review [the AI Copilot security guide](docs/AI_COPILOT_SECURITY.md) before enabling it.

### Database migration

After configuring `DATABASE_URL`, apply the reversible AI persistence migration:

```powershell
cd backend
.\.venv\Scripts\alembic.exe upgrade head
```

The migration adds `ai_conversations`, `ai_messages`, and `ai_usage`. To reverse the latest migration during development:

```powershell
.\.venv\Scripts\alembic.exe downgrade 20261125_0008
```

### AI API

- `GET /api/v1/workspaces/{workspace_id}/ai/status`
- `POST /api/v1/workspaces/{workspace_id}/ai/chat` (server-sent events)
- `GET /api/v1/workspaces/{workspace_id}/ai/conversations`
- `GET /api/v1/workspaces/{workspace_id}/ai/conversations/{conversation_id}`
- `DELETE /api/v1/workspaces/{workspace_id}/ai/conversations/{conversation_id}`
- `GET /api/v1/workspaces/{workspace_id}/ai/usage`
- `POST /api/v1/workspaces/{workspace_id}/ai/datasets/{dataset_id}/analyze`
- `POST /api/v1/workspaces/{workspace_id}/ai/sql/generate`
- `POST /api/v1/workspaces/{workspace_id}/ai/sql/explain`
- `POST /api/v1/workspaces/{workspace_id}/ai/sql/debug`
- `POST /api/v1/workspaces/{workspace_id}/ai/transformations/generate`
- `POST /api/v1/workspaces/{workspace_id}/ai/pipelines/generate`

The Copilot is available from the workspace sidebar at `/workspaces/{workspaceId}/ai`, from the collapsible application-shell panel, and through contextual actions in Data Explorer, SQL Workspace, and Pipelines. See [the user guide](docs/AI_COPILOT_USER_GUIDE.md) for interaction details.

## Direct uploads (Vercel / S3 / R2)

Vercel function payloads are capped at ~4.5 MB and the filesystem is ephemeral, so multipart uploads through the backend do not work for large files in production. Setting `DIRECT_UPLOAD_ENABLED=true` switches the upload dialog to a three-step flow:

1. The frontend calls `GET .../datasets/upload-config` to learn whether direct upload is active and what the size limit is.
2. It calls `POST .../datasets/upload-url` with the filename, size, and content type. The backend validates the request (auth, CSRF, role, extension, size) and returns a short-lived presigned PUT URL — the object key is always server-generated and workspace-scoped.
3. The browser PUTs the file directly to the storage bucket (no credentials or CSRF header needed — the URL carries a time-limited signature). Progress is shown via XHR upload events.
4. The frontend calls `POST .../datasets/{dataset_id}/upload-complete`. The backend HEADs the object to verify it exists and matches the declared size, then runs the same schema-detection and catalog ingestion as the multipart path.

The multipart path (`POST .../datasets/upload`) is unchanged and continues to work for `STORAGE_BACKEND=local` development.

### Required environment variables

| Variable | Purpose |
|---|---|
| `STORAGE_BACKEND` | Set to `minio` for any S3-compatible store (MinIO, R2, AWS S3) |
| `STORAGE_ENDPOINT_URL` | Full endpoint URL, e.g. `https://<account>.r2.cloudflarestorage.com` |
| `STORAGE_REGION` | Region for SigV4 signing — Cloudflare R2 requires `auto` |
| `STORAGE_PUBLIC_ENDPOINT_URL` | Optional separate endpoint for presigned URL generation (CDN / R2 public hostname) |
| `MINIO_ACCESS_KEY` | S3-compatible access key ID |
| `MINIO_SECRET_KEY` | S3-compatible secret key |
| `MINIO_BUCKET` | Bucket name |
| `DIRECT_UPLOAD_ENABLED` | Set to `true` to enable the presigned-URL upload path |
| `DIRECT_UPLOAD_URL_TTL_SECONDS` | Presigned URL lifetime in seconds (default: 900) |

Leave `MINIO_ENDPOINT` and `MINIO_SECURE` at their defaults when using `STORAGE_ENDPOINT_URL`.

### Bucket CORS rule

The bucket must permit PUT requests from the frontend origin. Example rule (JSON / R2 / S3-compatible):

```json
[
  {
    "AllowedOrigins": [
      "https://pylake.hellogaurav.me",
      "http://localhost:3000"
    ],
    "AllowedMethods": ["PUT", "GET", "HEAD"],
    "AllowedHeaders": ["Content-Type"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3600
  }
]
```

Apply via the Cloudflare R2 dashboard → Bucket settings → CORS, or with `aws s3api put-bucket-cors`.

### New endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/workspaces/{id}/datasets/upload-config` | Returns `{direct_upload, max_upload_size_bytes}` |
| `POST` | `/api/v1/workspaces/{id}/datasets/upload-url` | Validates request, creates pending dataset, returns presigned PUT URL |
| `POST` | `/api/v1/workspaces/{id}/datasets/{dataset_id}/upload-complete` | Verifies object, runs ingestion, returns completed dataset |

---

## Hosted pipeline worker (Railway)

The pipeline worker is a long-lived process that cannot run as a Vercel function. Deploy it as a separate Railway service pointing at the same database and object storage.

### Setup

1. In the Railway project, create a new service from the same GitHub repository.
2. Set the root directory to the repository root (not `backend/`).
3. Railway will detect `backend/railway.json` automatically, which sets the builder to `backend/Dockerfile` and the start command to `python -m app.worker`.

### Required environment variables

Configure the same values used by the backend API:

| Variable | Notes |
|---|---|
| `APP_ENV` | Set to `production` |
| `DATABASE_URL` | Neon (or other managed Postgres) **unpooled** URL: `postgresql+psycopg://user:pass@host/db?sslmode=require` — use the unpooled connection string because the worker holds long-lived transactions |
| `AUTH_SECRET` | Same value as the API service |
| `STORAGE_BACKEND` | `minio` |
| `STORAGE_ENDPOINT_URL` | Same R2 / S3 endpoint as the API |
| `STORAGE_REGION` | Same value as the API |
| `MINIO_ACCESS_KEY` | Same credentials as the API |
| `MINIO_SECRET_KEY` | Same credentials as the API |
| `MINIO_BUCKET` | Same bucket as the API |
| `PIPELINE_JOB_CLAIM_SECONDS` | How long a worker holds a claimed job before another worker can steal it |
| `PIPELINE_WORKER_POLL_SECONDS` | How often the worker polls for new jobs when idle |
| `PIPELINE_STEP_TIMEOUT_SECONDS` | Per-step execution timeout |
| `PIPELINE_MAX_RETRIES` | Maximum retries per run |
| `WORKER_STALE_SECONDS` | Heartbeat age after which a worker is considered offline |

The worker and API **must** share the same object storage bucket; datasets created through the API are stored there and read by the worker during pipeline execution.

### One-time database setup on first deploy

On Vercel the API does **not** run Alembic; it creates missing tables at startup with `Base.metadata.create_all`, so the production database has tables but no Alembic version record. The worker does not run migrations. Run this once against the production database (from a local or Railway shell with `DATABASE_URL` set) before applying any future migration:

```bash
cd backend
python -m alembic stamp head
```

This records the current migration version without running migrations or changing data. Only run it when the tables already match the latest models.

The Railway worker service does **not** expose a port or health-check endpoint; remove any Railway-generated health check from the service settings.
