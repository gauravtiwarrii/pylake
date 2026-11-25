# PyLake backup and restore

## Scope

PyLake stores two distinct types of state:

- PostgreSQL or SQLite application metadata: users, workspaces, datasets, lakehouse versions, query history, pipelines, runs, schedules, audit logs and worker state.
- Object storage: original Bronze files and Silver/Gold Parquet versions.

No object contents should be considered recoverable from the metadata database alone.

## PostgreSQL backup

Use `pg_dump` when PostgreSQL is the production database:

```powershell
pg_dump --format=custom --file=pylake.metadata.dump --dbname="$env:DATABASE_URL"
```

Verify the archive:

```powershell
pg_restore --list pylake.metadata.dump
```

## SQLite backup

Stop writers and copy the SQLite file:

```powershell
Copy-Item pylake.db pylake.db.backup
```

Verify the copy with SQLite integrity checking:

```powershell
sqlite3 pylake.db.backup "PRAGMA integrity_check;"
```

## Object storage backup

For MinIO, use MinIO client tools or approved S3-compatible replication:

```powershell
mc mirror minio/pylake ./pylake-storage-backup
```

For local storage, copy the configured `LOCAL_STORAGE_DIR` directory while writers are stopped or quiesced:

```powershell
Copy-Item -Recurse .\storage .\pylake-storage-backup
```

Record checksums for the copied object archive before restore.

## Restore

Restore objects first, then metadata. Do not restore over an active database or object bucket.

PostgreSQL:

```powershell
pg_restore --clean --if-exists --dbname="$env:DATABASE_URL" pylake.metadata.dump
```

SQLite:

```powershell
Copy-Item pylake.db pylake.db.backup
```

MinIO:

```powershell
mc mirror ./pylake-storage-backup minio/pylake
```

After restore, run migrations and verify dataset versions resolve to existing storage keys.
