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

Frontend:

```powershell
cd frontend
npm install
npm run dev
```
