# Ask Lakehouse

Ask Lakehouse answers workspace questions from catalog metadata and validated, read-only queries. It remains useful with AI disabled: metadata questions use deterministic answers, and common totals, counts, rankings, and trends use SQL templates matched to the table schema. Questions that cannot be mapped confidently return table and column candidates for clarification.

## Endpoints

- `POST /api/v1/workspaces/{id}/ask` accepts a question, optional dataset/table scope, and execute flag. It returns a metadata, data, clarification, or unsupported answer with citations, limitations, confidence, and optional SQL/chart suggestion.
- `GET /api/v1/workspaces/{id}/ask/suggestions?page_type=ask` returns suggested prompts.
- `GET /api/v1/workspaces/{id}/ask/history` returns up to 30 recent asks for the signed-in workspace member.
- `POST /api/v1/workspaces/{id}/sql/analyze` validates and analyzes SQL without running it.

Workspace membership is checked for every endpoint; VIEWER members can ask and analyze. Dataset and table references are resolved only against the current workspace. Write operations are rejected by the shared SQLGlot read-only validator. Ask requests use the existing API rate limit and audit record flow; browser POSTs use the API CSRF protection.

## Answer sources and safety

Metadata answers cite the catalog, trust snapshot, pipeline, lineage, or version records they read. Data answers return the generated SQL, citations to referenced tables/columns and versions, row count, truncation state, and a deterministic chart suggestion. The SQL is validated and resolved against workspace catalog tables before execution. Results are capped by the configured Ask row limit (default 200) and are not fabricated. Dataset cell contents are treated as untrusted. If an optional aggregate-only AI explanation is provided, the UI labels it as an estimate and keeps it separate from measured query results; the current Ask response may omit this field.

With AI enabled, the shared structured engine can draft SQL from bounded schema context. The result still passes the same read-only, workspace-resolution, and row-limit checks. With AI disabled, deterministic templates support common `top/highest/lowest`, `total/average/count`, row-count, and date-trend requests. If matching is ambiguous or unsupported, Ask returns a clarification instead of silently selecting a metric or column.

SQL Analyze reuses the read-only validator and catalog resolver and never executes SQL. Its findings are heuristics: `SELECT *`, missing limits on known tables larger than 10,000 rows, cartesian or condition-less joins, unused CTEs, functions around filtered columns, and `ORDER BY` without a limit. Scanned row counts are estimates based on catalog row counts and SQL table references, not query planner statistics.

## Limitations

- Deterministic SQL templates cover common aggregation and trend patterns; more complex questions may need a narrower question or SQL Workspace.
- Column name fuzzy matching can be ambiguous. Ask reports candidate columns or tables when confidence is insufficient.
- Result tables display at most 200 rows. A truncation flag and limitation message indicate when output was capped.
- Chart selection is a presentation heuristic based on result shape and types; a chart suggestion does not change the executed query.
- Metadata quality and lineage answers depend on the most recent records available. Missing or stale metadata may limit an answer.
- SQL Analyze uses catalog row counts and static syntax checks; estimates do not account for filters, partition pruning, caching, or execution plans.
- Optional AI prose is an estimate over bounded result data. It is not the source of numeric results.
