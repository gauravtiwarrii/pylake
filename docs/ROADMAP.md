# Implementation Roadmap

## Milestone 0: Repository inspection

- Inspect existing code and configuration
- Confirm repository state
- Define architecture and constraints

**Completed:** Repository was empty. Greenfield implementation selected.

## Milestone 1: Project scaffold

- Create monorepo structure
- Configure Next.js, FastAPI, PostgreSQL, MinIO, and Docker Compose
- Add health endpoints and initial tests
- Document local startup commands

## Milestone 2: Backend foundation and workspace UI

- Implement application models and migrations
- Add authentication and secure session management
- Create workspace CRUD and basic roles
- Build the navigation shell and theme foundation

## Milestone 3: Dataset ingestion

- Upload CSV, JSON, Parquet, and XLSX
- Validate file type and size
- Detect schemas, row counts, metadata, and previews
- Store raw data in the Bronze layer

## Milestone 4: Storage and data explorer

- Convert analytical datasets to Parquet
- Implement Bronze, Silver, and Gold listing
- Add metadata and preview endpoints
- Add guarded dataset deletion

## Milestone 5: SQL analytics

- Integrate DuckDB
- Restrict queries to read-only SELECT-style operations
- Register uploaded datasets safely
- Add history, saved queries, CSV export, and result metadata

## Milestone 6: Transformations

- Implement column, null, duplicate, filter, type, and calculated-column operations
- Build visual transformation controls
- Export transformed datasets to Silver or Gold

## Milestone 7: Pipelines

- Add pipeline definitions and sequential run execution
- Record run status and error logs
- Support source selection and ordered transformations

## Milestone 8: Data catalog and lineage

- Discover datasets and lakehouse tables
- Support catalog documentation and tags
- Profile bounded asset statistics
- Capture transformation, SQL, and pipeline lineage
- Provide upstream, downstream, and impact queries
- Build the catalog and lineage frontend

## Milestone 9: Security and deployment

- Complete authorization checks
- Add upload and SQL abuse defenses
- Configure CI, linting, tests, health checks, and container startup
- Document production configuration limitations

## Milestone 10: AI assistant

- Add an optional provider abstraction
- Build schema, SQL, cleaning, and error explanation workflows
- Require explicit consent before sending private data externally
