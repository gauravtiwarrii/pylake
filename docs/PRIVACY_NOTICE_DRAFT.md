# PyLake privacy notice (draft)

**Status: internal draft only. Do not publish or rely on this as a final privacy notice. Operator and legal review are required before inviting students to use a hosted beta.**

## Data the current application can store

The application schema and API currently support storing:

- Account email address, full name, Argon2 password hash, and session/CSRF token hashes.
- Workspace names, descriptions, memberships, and roles.
- Uploaded source files, derived lakehouse versions, filenames, schemas, and dataset metadata.
- Saved SQL and query history, including SQL text and execution results metadata.
- Pipeline definitions, configurations, run/step status, and error messages.
- Catalog descriptions, tags, profiles, lineage, audit events, and rate-limit events.

Passwords are stored as hashes. Browser session credentials are opaque cookies; the database stores token hashes rather than the raw session token.

## Operational logging

The API logs request method, path, status, duration, and request ID. The logging formatter redacts configured sensitive key names and bearer-token text. The application does not intentionally log request bodies in this middleware. Infrastructure, proxy, container, database, or storage logs may have separate behavior and retention controlled by the operator.

## Storage and service operators

The application supports local filesystem storage and an S3-compatible storage adapter. A hosted deployment's database provider, object-storage provider, hosting location, access controls, subprocessors, and cross-border transfer practices have not been selected or verified by this repository review. Operators must document those details before collecting user data.

## Retention and deletion

This repository does not establish a complete retention schedule or verify end-to-end deletion of all backups, logs, database records, and stored objects. Backup retention and recovery are operator responsibilities. The [backup and restore guide](BACKUP_RESTORE.md) is operational guidance, not a deletion or retention guarantee.

## Required before publication

The operator must identify the controller/contact, deployment and data regions, subprocessors, retention periods, account/data deletion process, student age requirements, incident contact, and applicable legal obligations. Do not use this draft as a substitute for legal review.

Until that review is complete, use only local development instances and non-sensitive test data.
