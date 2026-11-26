# PyLake rollback and recovery

## Current status

No production deployment, pinned beta image, or tested prior release has been established. This document is a cautious recovery procedure, not a validated production rollback automation.

## Before changing a deployment

1. Stop or quiesce API and worker writes using the deployment operator's documented controls.
2. Back up PostgreSQL metadata and the complete object-storage directory or bucket. See [backup and restore](BACKUP_RESTORE.md).
3. Record the deployed image digest, application commit, and Alembic revision.
4. Verify the backup in an isolated environment before replacing any live state.

## Application rollback

Roll back to an exact previously tested image digest, not a floating tag. Keep the database at the current revision unless that older application version is verified compatible with it. This repository does not currently provide a pinned beta image or a verified prior image digest.

## Schema rollback

Alembic downgrades are reversible in the migration code, but downgrades may drop tables, columns, or data. The migration chain was tested on fresh temporary SQLite and PostgreSQL databases; this does not prove a downgrade is safe for a populated deployment.

Do not run `alembic downgrade` against production as an automatic response to an application rollback. First inspect the exact migration's downgrade, take and verify a restorable backup, and test the rollback against a copy of the deployed database.

## Recovery after a worker failure

Inspect the worker logs and run state before restarting a worker. A stale `RUNNING` job may be reclaimed after the configured claim timeout and could repeat side effects. Confirm idempotency and inspect affected storage/version records before manually requeueing, cancelling, or deleting any run. Do not modify run records directly without a reviewed recovery procedure.
