# PyLake Architecture

## Simplest MVP architecture

PyLake will use a modular monolith for the backend rather than early microservices:

- **Frontend:** Next.js App Router application for the workspace UI
- **API:** FastAPI application organized by versioned feature routers
- **Application database:** PostgreSQL for users, workspaces, datasets, jobs, and history
- **Query engine:** DuckDB for uploaded and transformed analytical datasets
- **Object storage:** MinIO behind a storage service abstraction
- **Local fallback:** SQLite and local files for lightweight development
- **Data format:** Apache Parquet for analytical datasets
- **Data processing:** Polars for transformations and schema operations

This keeps operational complexity low while preserving clear module boundaries for later distributed processing.

## Proposed directory structure

```text
pylake/
├── backend/
│   ├── app/
│   │   ├── api/v1/
│   │   ├── core/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── engines/
│   │   └── storage/
│   └── tests/
├── frontend/
│   ├── app/
│   ├── components/
│   ├── features/
│   ├── hooks/
│   ├── lib/
│   └── types/
├── infrastructure/
│   ├── docker/
│   └── scripts/
├── docs/
├── docker-compose.yml
├── .env.example
└── README.md
```

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
| passlib / python-jose | Password hashing and future session tokens |
| Next.js / React / TypeScript | Frontend application |
| Tailwind CSS | Design system primitives |
| Lucide / Recharts / Monaco | Icons, analytics, and SQL editing |
| Pytest / HTTPX | Backend tests and API test clients |

## Technical risks

1. **Mixed local and container storage paths** must remain isolated behind the storage abstraction.
2. **SQL injection and unsafe SQL** require allowlisting read-only operations and dataset-scoped relation names.
3. **Large uploads** require streaming, size enforcement, and persisted upload state.
4. **Schema inference** differs across CSV, JSON, Parquet, and XLSX formats; use explicit validation and normalized schemas.
5. **Concurrency** can cause inconsistent job state unless pipeline runs use durable database records and controlled transitions.
6. **Python 3.14 package compatibility** may lag some libraries; production containers should use Python 3.12 until the project validates 3.14 support.
7. **Docker availability** differs on developer systems; the app must also provide direct local commands.
