# Student Beta v0.1 release validation

**Validation date:** 2026-11-26
**Release decision:** **BLOCKED — do not tag, announce, or deploy this beta.**

This report supersedes the older Milestone 7.1 report, including its stale revision `20261125_0007` and 37-test claims. The current migration head is `20261125_0008`.

## Passed checks

- Host backend suite on Python 3.12: **42 passed**, 3 non-blocking warnings.
- New API-to-worker integration test: registered a user, created a workspace, uploaded CSV, promoted Silver, executed a queued pipeline that materialized Gold, and queried the resulting table.
- Worker retry regression test: failed step is re-queued without a completion timestamp, then succeeds on retry.
- Frontend ESLint, TypeScript typecheck, and Next.js production build: passed.
- `npm audit` and `npm audit --omit=dev`: 0 frontend vulnerabilities.
- Removed the unused `python-jose[cryptography]` dependency and its orphaned transitive packages with user approval; `pip check` found no broken requirements and post-removal `pip-audit` reported no known vulnerabilities. The scanner skipped the local `pylake-backend` distribution because it is not on PyPI.
- Fresh SQLite migration upgrade, downgrade to base, re-upgrade to head, and temporary-copy integrity check: passed; resulting revision `20261125_0008`.
- Fresh temporary PostgreSQL migration upgrade, downgrade to base, and re-upgrade to head: passed; temporary database was removed.
- Existing PostgreSQL database migration head: `20261125_0008`.
- Compose configuration validation: passed.
- Earlier in validation, backend `/api/v1/health` and frontend `/login` returned HTTP 200. A final smoke recheck timed out for both; the Docker daemon was not responsive, so current service availability could not be confirmed.
- A read-only security review reported no source-level findings in the changes it reviewed.

## Blocking and unverified gates

| Gate | Result | Evidence / next action |
|---|---|---|
| Live pipeline worker | **BLOCKED** | The Compose worker exited after a retry-finalization `TypeError`. Two underlying defects were fixed and regression-tested in the worktree, but the live worker has not been restarted. The existing PostgreSQL database has one `RUNNING` pipeline record; it was not altered or re-queued. |
| Current Docker image rebuild and service recheck | **BLOCKED** | A full backend/worker/frontend build exited with a Docker BuildKit `EOF` while the frontend build was running. Subsequent requests to the running routes timed out and the Docker daemon did not respond. The host frontend production build passed. Retry after Docker Desktop/BuildKit is healthy, then run tests in the rebuilt image. |
| Browser end-to-end | **NOT TESTED** | Only live route status checks and backend `TestClient` integration ran. There is no frontend test script or browser workflow covering signup through the authenticated UI. |
| MinIO integration | **NOT TESTED** | The optional MinIO profile and S3-compatible storage path were not exercised. |
| Application backup restore | **NOT TESTED** | Only a migration-only SQLite database copy was integrity-checked. No populated PostgreSQL plus object-storage restore drill was performed. |
| Production deployment | **BLOCKED** | `docker-compose.yml` embeds local development credentials and `APP_ENV=local`. No production Compose/configuration, TLS deployment, secrets management, or production rollback was validated. |
| CI automation | **NOT PRESENT** | No repository CI workflow was found. |
| Privacy and terms | **DRAFT ONLY** | The repository now includes internal drafts; operator and legal review is still required. |

The source-level review reported no findings in the changes it reviewed. The initial dependency findings were removed with user approval; the post-removal package audit is clean for installed dependencies, with the local project distribution explicitly skipped by the scanner.

## Fixes made during this validation

- Pipeline retries no longer compute elapsed duration after resetting `started_at`; UTC-aware and SQLite-naive datetimes are normalized before subtraction.
- `SOURCE_DATASET` worker configuration now validates and converts JSON dataset IDs to UUIDs before database lookup.
- Removed the unused JOSE dependency chain flagged by the initial Python dependency audit.
- Added retry-cycle and upload→Gold pipeline→SQL regression tests.
- Corrected the SQLite restore direction in [backup and restore](BACKUP_RESTORE.md), and marked local Compose as development-only in the README.

## Release decision

Do not create a beta commit or tag until the worker is rebuilt and safely recovered, Docker builds and container tests pass, and the remaining production/privacy/backup/browser gates have explicit owners and evidence. The Python dependency findings are resolved, though the scanner skips the local project distribution. See [Student Beta v0.1 readiness](STUDENT_BETA_V0.1.md), [rollback guidance](ROLLBACK.md), [privacy draft](PRIVACY_NOTICE_DRAFT.md), and [terms draft](TERMS_DRAFT.md).
