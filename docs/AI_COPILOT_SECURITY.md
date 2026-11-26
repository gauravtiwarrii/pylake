# PyLake AI Copilot security and data handling

## Authentication and authorization

- AI APIs require the existing authenticated session and CSRF protections.
- Every endpoint checks workspace membership before reading or writing Copilot data.
- Conversations are scoped to both the workspace and the user. Conversation IDs are not sufficient to access another user's history.
- Dataset, table, and pipeline context is queried only within the authorized workspace.
- Context reads are recorded as `AI_CONTEXT_ACCESSED` audit events without recording prompts or conversation contents.

## Provider boundary and privacy

When enabled, the current user prompt, prior messages in that user's selected conversation, and bounded workspace context are sent from the backend to the configured provider. Provider credentials and base URLs stay server-side and are never returned by status or error responses. NVIDIA authentication uses `NVIDIA_API_KEY`; it must not be exposed through `NEXT_PUBLIC_*`, logs, or browser storage.

Chat context can include workspace names; dataset/table names, formats, ingestion status, row and column counts, and schema names/types; recent pipeline status; and query execution status/duration/result-count metadata. A user-supplied SQL string is parsed and SQL literals/comments are redacted before it is included in context. SQL supplied for explanation/debugging is also bounded.

Chat context does not include raw dataset rows, storage object keys, credentials, query-history SQL, or query error content. Dataset profiling reads a bounded 10,000-row sample on the backend and sends aggregate statistics only to the provider; the profile response identifies sample-based duplicate and outlier results. Provider usage and duration are persisted, but prompts and provider response bodies are not copied into audit metadata.

Review the configured provider's data retention, region, and training policies before enabling it for sensitive workspaces. Use `AI_PROVIDER=disabled` when external processing is not permitted.

For NVIDIA Nemotron, the provider adapter deliberately ignores `reasoning_content` in complete and streaming responses. Only `content` is returned to the chat endpoint; internal reasoning is not rendered, persisted as an assistant message, or included in usage records. The configured output cap and reasoning budget limit generation; when thinking is enabled, the reasoning budget must be lower than the output-token limit. There is no automatic provider fallback, so an NVIDIA failure does not send workspace data to another service.

## Generation is not execution

- Chat responses are rendered as text; they are not interpreted as HTML or executable code.
- SQL drafts must pass the existing read-only SQL validator and workspace catalog resolver. The AI API does not execute them or create SQL history records.
- Transformation drafts are parsed against existing transformation schemas and validated against workspace columns and layers. They are suggestions only.
- Pipeline drafts are validated against existing graph rules, supported step types, workspace resources, and read-only SQL restrictions. They are returned with `DRAFT` status and are not persisted or run by the AI API.
- Users must explicitly review and apply any suggestion through the existing product workflows.

## Abuse and resource limits

- AI requests are rate-limited per user and workspace using database-backed rate-limit events.
- Provider timeout, retry count, output tokens, input characters, context size, history size, and daily token budget are configurable.
- Daily token enforcement relies on token counts reported by the provider. Some streaming-compatible providers do not report streaming token usage; in that case, the UI indicates that token usage is unavailable while request rate limits remain active.
- Provider errors are replaced with generic client messages and logs omit provider exception content.

## Retention and deletion

Conversation messages are stored so that authorized users can resume their own conversations. A conversation can be deleted through the Copilot UI or `DELETE /api/v1/workspaces/{workspace_id}/ai/conversations/{conversation_id}`; its messages are removed, while usage records are retained with their conversation reference cleared so deletion cannot erase quota accounting. Usage history is summarized over the last 30 days by the API.
