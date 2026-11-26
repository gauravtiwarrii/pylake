# PyLake AI Copilot architecture

## Status

Architecture plan recorded before implementation. The backend, persistence migration, workspace APIs, frontend Copilot route/panel, contextual draft actions, and setup/security/user documentation are implemented against the existing FastAPI, SQLAlchemy/Alembic, Next.js, workspace authorization, DuckDB/SQLGlot, Polars, and pipeline graph layers.

## Design principles

- AI is optional. With `AI_PROVIDER=disabled` (the default), all existing PyLake features work normally and AI endpoints return a clear unavailable response.
- Provider credentials and configuration remain server-side. The browser never receives an API key.
- Every AI route is scoped to a workspace and checks the authenticated user's existing workspace membership before loading context or history.
- Provider context is assembled from an explicit allowlist of workspace metadata. No storage keys, filesystem paths, credentials, session tokens, complete datasets, or raw preview rows are sent.
- Dataset names, schemas, user prompts, saved content, and provider responses are untrusted data. AI suggestions are data, not executable commands.
- Generated SQL, transformation configurations, and pipeline graphs are validated against existing PyLake validators. AI endpoints only return drafts; they never execute SQL or modify lakehouse data or pipelines.
- Existing execution endpoints remain the only path to execute SQL, transformations, and pipelines, so their RBAC, SQLGlot, timeouts, limits, and confirmation UX remain authoritative.
- Conversation content is persisted only for the authenticated user's workspace conversations, is not written to ordinary logs, and can be deleted through the API. Workspace/user deletion cascades to associated AI records.

## Provider boundary

Add a small provider protocol with independent `complete` and `stream` operations, bounded timeouts, and generic provider errors that do not include response bodies or credentials.

Initial adapters:

- `openai_compatible`: configurable base URL, API key, and model, supporting hosted OpenAI-compatible services.
- `nvidia`: reuses the OpenAI-compatible HTTP and SSE implementation with NVIDIA-specific model settings and the `NVIDIA_API_KEY` secret.
- `ollama`: configurable local Ollama base URL and model, without a cloud credential.

The default provider is `disabled`. All adapters use the already-installed `httpx`; AI introduces no mandatory runtime package. NVIDIA requests use centrally configured temperature, top-p, output limit, thinking mode, and reasoning budget. The provider parser emits only assistant `content`; it discards `reasoning_content` before the application can persist or send it to the browser. Retry only transient connection/status failures before response content begins; do not retry an already-started stream. Provider and model status endpoints expose names and availability only, never secrets. Provider fallback is explicit configuration only; NVIDIA failures do not silently select another service.

## Backend components and persistence

- Add AI settings to `Settings`; use disabled-by-default configuration, explicit request/output/context bounds, NVIDIA API key and sampling/thinking controls, provider timeout/retry settings, and a database-backed per-user/workspace rate limit using the existing `RateLimitEvent` mechanism.
- Persist `AIConversation`, `AIMessage`, `AIUsage`, and `AIRecommendation` records. Recommendation rows retain their evidence, proposed action, risk/permission metadata, and the requesting user's accept/reject decision. Foreign keys cascade on workspace or user deletion.
- Keep the AI Copilot and recommendation persistence in reversible Alembic revisions after `20261125_0008`; revision `20261127_0010` adds recommendation tracking.
- Add a workspace context service that retrieves only rows filtered by the supplied workspace ID. It reads dataset/table schemas and counts, layer/version summaries, query execution status metadata, pipeline status/failure classes, bounded cached profile statistics, selected-asset lineage summaries, and (on audit/workspace views only) recent audit action/type/time. Page labels and active views are navigation hints, not authorization inputs; selected resource IDs are rechecked against the workspace before use.
- Record context access in `AuditLog` with resource categories/counts only; never include message text, schema values, SQL literals, or provider responses in audit metadata.
- Reuse catalog profiling and Polars for verified statistics. Profiling is bounded to the existing profile row cap; any sample-derived duplicate/anomaly result must be labeled as a sample result. No sample values are included in provider prompts.
- Expose routes under `/api/v1/workspaces/{workspace_id}/ai` for status, chat/streaming, conversation history/deletion, usage, dataset analysis, SQL generate/explain/debug, transformation/pipeline drafts, permission-filtered tool metadata, contextual recommendations, and per-user accept/reject feedback.
- Use a structured tool registry to declare supported page types, minimum workspace roles, application roles, read-only status, and approval requirements. Recommendations are grounded in server-verified facts and registry entries; accepting or dismissing one records feedback only and does not invoke an operation.
- Validate generated SQL with `validate_read_only_sql`, then resolve every referenced table through the workspace catalog. Invalid or unknown-table SQL is rejected as a draft; it is never run by AI endpoints.
- Validate pipeline drafts with Pydantic and `validate_pipeline_graph`, and transformation drafts against the existing transformation operation/configuration allowlist.

## Streaming and errors

The chat request creates or verifies a conversation and stores the user's message before opening the provider stream. SSE events carry only metadata, user-facing content deltas, completion usage, or a generic failure. NVIDIA `reasoning_content` is discarded at the provider boundary. Provider exception text and response bodies are not forwarded to users. Usage status and assistant text are finalized after the stream; incomplete responses are marked failed/interrupted and are not represented as successful completions.

All non-streaming generation endpoints use the same provider boundary, context bounds, rate limiter, audit rules, and usage tracking. A missing provider configuration returns a clear `503` without affecting normal application routes.

## Frontend integration

- Add a dedicated `/workspaces/[workspaceId]/ai` page and a collapsible assistant panel reachable from the authenticated workspace shell. The shared panel receives current page/view context and selected dataset, table, pipeline, catalog asset, or SQL state from existing workspace screens.
- Reuse the current cookie-based API client and CSRF header behavior. Streaming fetches include credentials and the CSRF header; no token is put in browser storage.
- Show conversation history, suggested prompts, response mode, provider availability, loading/errors, and usage. Render model output as escaped React text; do not insert model-provided HTML.
- Use page-specific prompts and evidence cards across overview, Data Explorer/dataset detail, Lakehouse quality/lineage, SQL Workspace, Pipelines, Catalog, and Audit views. Context remains bounded metadata; complete data rows are not sent.
- Keep suggestions separate from the existing execution forms. Require an explicit user action before applying a SQL draft, transformation, or pipeline draft through its existing endpoint.
- Preserve the current authenticated shell, public landing page, theme tokens, responsive layout, and reduced-motion behavior.

## Validation plan

- Unit tests: provider adapters and stream parsing, disabled/missing-key behavior, timeout/retry/error redaction, prompt/context bounds, SQL and pipeline draft validation, and rate/usage limits.
- API tests: registration/login cookie auth, CSRF, workspace isolation, member/viewer permissions, conversation ownership/deletion, resource scoping, usage visibility, and no content leakage in audit/log metadata.
- Security regression tests: malicious dataset names/column names and uploaded-file text remain untrusted; no tool execution occurs; generated SQL must pass the existing validator; provider errors must not leak secrets or response bodies.
- Dataset tests use temporary local storage and assert actual Polars-derived results, including sample-bounded labels.
- Run backend tests, frontend lint/typecheck/build, and migration upgrade/downgrade checks. External provider integration is only reported as run when credentials and a reachable provider are explicitly configured.

## Documentation and configuration

Add safe placeholders and the disabled default to `.env.example` and pass the server-side settings through the backend Compose service. Document provider setup, local Ollama, data sent to providers, retention/deletion, limits, supported capabilities, and unimplemented limitations in:

- `docs/AI_COPILOT_SETUP.md`
- `docs/AI_COPILOT_SECURITY.md`
- `docs/AI_COPILOT_USER_GUIDE.md`

This architecture document is the design reference for the implementation and its security review.
