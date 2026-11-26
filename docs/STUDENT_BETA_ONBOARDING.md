# PyLake student beta onboarding

## Status

Student Beta v0.1 is not yet cleared for use with real or sensitive data. The current Docker Compose setup is for local development only. See [beta readiness](STUDENT_BETA_V0.1.md) before treating this as a release.

## Start a local instance

From the repository root in PowerShell:

```powershell
docker compose up --build -d
docker compose ps -a
```

Open the frontend at <http://localhost:3000>. The API health check is <http://localhost:8000/api/v1/health>. Before using pipelines, confirm the `worker` service is running; a stopped worker leaves queued work unprocessed.

The Compose file contains local-only credentials and publishes development ports. Do not expose it to the public internet.

## First use

1. Register an account through the application.
2. Create a workspace.
3. Upload a small, non-sensitive CSV or JSON file.
4. Inspect the dataset and promote it to Silver or Gold before querying it.
5. Open SQL Workspace and run a bounded, read-only query.
6. If testing pipelines, verify the run reaches a terminal status and inspect its step logs.

Use synthetic or otherwise non-sensitive data until the privacy notice and terms have been reviewed and the beta release gates pass.

## Local development and tests

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
python -m alembic upgrade head
python -m pytest tests
```

Frontend:

```powershell
cd frontend
npm ci
npm run lint
npm run typecheck
npm run build
```

See [README](../README.md) for API routes, local service details, and feature limits.
