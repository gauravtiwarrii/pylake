# Data Trust Passport

The Trust Passport gives workspace members a reproducible, measurement-backed view of catalog asset quality. Snapshots are computed by the backend with Polars and stored with the asset, optional dataset version, trigger, sampling counts, rule outcomes, and limitations. Snapshot computation never requires an AI provider.

## Metrics and formulas

Each metric includes a score, status, observed value, detail, and measurement basis. Scores range from 0 to 100. A metric without enough evidence is `NOT_MEASURED`, has a null score, and is excluded from the overall score.

| Metric | Measurement |
| --- | --- |
| Completeness | 100 minus mean null-cell percentage across sampled columns. |
| Uniqueness | 100 minus duplicate whole-row percentage. |
| Validity | Passing enabled quality-rule checks, weighted by rule severity. It is not measured when no rules are enabled. |
| Consistency | Parseability for string columns that appear numeric/date-like, plus numeric IQR outlier rate. |
| Freshness | Linear decay from 100 at the configured target age to 0 at three times that age. Not measured until a freshness target exists. |
| Schema stability | 100 minus 20 for each breaking dropped-column or type-change event among the latest ten schema records. Not measured with fewer than two records. |
| Lineage completeness | 100 for an upstream lineage edge or raw ingested dataset; 50 when a derived asset has no upstream edge. |

The overall score is the weighted mean of measured metrics only, renormalized over available weights: completeness 0.20, uniqueness 0.15, validity 0.20, consistency 0.15, freshness 0.10, schema stability 0.10, and lineage completeness 0.10. Missing metrics are listed as excluded and never count as 100.

## Sampling and triggers

The configurable `trust_sample_rows` setting bounds measurement to at most 100,000 rows by default. Snapshots report whether rows were sampled and the observed total when available. Dataset ingestion, lakehouse promotion/transformation, and successful `DATA_QUALITY` pipeline steps trigger best-effort snapshots. Trigger failures are logged and do not fail the ingestion or pipeline operation. Manual recompute is also available to editors and above.

Quality rules are workspace and asset scoped. Supported types are `NOT_NULL`, `UNIQUE`, `RANGE`, `REGEX`, `ALLOWED_VALUES`, and `MIN_ROW_COUNT`; rule configuration is validated before storage. Editors and above can manage rules and freshness targets. Members can view snapshots and rules. Existing workspace authorization, CSRF checks on mutations, audit records, rate limiting, and cross-workspace 404 behavior apply.

AI explanations are optional and are clearly labelled estimates. They receive aggregate metrics and rule counts only, never source rows or raw field values. A disabled AI provider does not affect measurement or manual workflows.

## Limitations

Measurements are bounded samples where assets exceed the configured cap. Consistency uses explicit parseability and IQR heuristics; lineage completeness is a simple structural signal. These measurements do not establish business correctness. Pipeline validation indicates the most recent successful `DATA_QUALITY` validation when one exists. Execution and snapshot computation are synchronous.
