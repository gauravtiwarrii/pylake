# PyLake AI Copilot setup

The AI Copilot is an optional backend capability. The default `AI_PROVIDER=disabled` leaves all non-AI application features available and causes AI generation requests to return a clear service-unavailable response.

## Supported provider adapters

| `AI_PROVIDER` | Adapter behavior | Required configuration |
|---|---|---|
| `disabled` | AI requests stay disabled | None |
| `openai` | Alias for the OpenAI-compatible adapter | `AI_API_KEY` and `AI_MODEL` |
| `openai_compatible` | Sends OpenAI Chat Completions requests and parses SSE streams | `AI_API_KEY` and `AI_MODEL` |
| `nvidia` | NVIDIA Nemotron through the OpenAI-compatible Chat Completions API, with NVIDIA request options | `NVIDIA_API_KEY` and `AI_MODEL` |
| `ollama` | Sends native Ollama `/api/chat` requests and parses newline-delimited JSON streams | A running Ollama server and an installed `AI_MODEL`; no key |

For `openai`, `openai_compatible`, and `nvidia`, `AI_BASE_URL` is the API base URL: the adapter appends `/chat/completions`. It must support the OpenAI Chat Completions request/response format and SSE streaming. Do not include `/chat/completions` in the configured base URL. Defaults are `https://api.openai.com/v1` for the first two providers and `https://integrate.api.nvidia.com/v1` for NVIDIA.

For `ollama`, `AI_BASE_URL` is the server URL: the adapter appends `/api/chat`. The default is `http://localhost:11434`. Provider status only checks local configuration; it does not check network reachability or whether the model is installed. Verify with a real request.

### NVIDIA Nemotron

The NVIDIA adapter reuses the existing HTTP provider boundary; it does not add an SDK or a separate chat endpoint. It sends `temperature`, `top_p`, `max_tokens`, `chat_template_kwargs`, and (when thinking is enabled) `reasoning_budget` in the request body. It reads only assistant `content` from responses. `reasoning_content` is intentionally ignored and is never sent to the frontend, saved as a conversation message, or written to usage records.

Configure these values in the backend environment:

```dotenv
AI_PROVIDER=nvidia
AI_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b
AI_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_API_KEY=
AI_TEMPERATURE=0.7
AI_TOP_P=0.95
AI_MAX_OUTPUT_TOKENS=4096
AI_ENABLE_THINKING=true
AI_REASONING_BUDGET=2048
```

Set `NVIDIA_API_KEY` locally through the ignored backend `.env`, the root `.env` used by Docker Compose, or a secret manager. Never use `NEXT_PUBLIC_NVIDIA_API_KEY`. A missing key or incompatible reasoning/output token budgets produce a clear `503` configuration error. When thinking is enabled, `AI_REASONING_BUDGET` must be lower than `AI_MAX_OUTPUT_TOKENS` to reserve output capacity. These settings are server-side and apply to NVIDIA requests; changing them requires a backend restart.

Model availability, quota, rate limits, context behavior, and account requirements are controlled by NVIDIA and can change. Check the [NVIDIA Nemotron API page](https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b) before use. PyLake does not automatically fall back to another provider if NVIDIA is unavailable; change `AI_PROVIDER` explicitly or disable AI.

### Hosted OpenAI-compatible examples

These services use the existing adapter; they do not require a new provider implementation. Model identifiers, availability, free quotas, and terms can change, so confirm them with the service before configuring:

| Service | `AI_BASE_URL` | `AI_MODEL` | Notes |
|---|---|---|---|
| OpenRouter | `https://openrouter.ai/api/v1` | `openrouter/free` | Uses its free-model router. Without purchased credits, the currently documented limit is 50 free-model API requests per day. Do not configure paid fallbacks. |
| Google Gemini API | `https://generativelanguage.googleapis.com/v1beta/openai` | A currently supported Gemini model ID | The unpaid API terms allow Google to use prompts and responses to improve products and permit human review. Never send sensitive, confidential, or personal data using unpaid quota. |
| Groq | `https://api.groq.com/openai/v1` | A currently supported model ID | Check current account limits and model availability; do not assume a free quota or production availability. |

OpenRouter's free router is the most practical hosted, zero-inference-cost option for development integration checks: it speaks the adapter's API and streaming format, but the selected model and availability may vary. OpenRouter is a proxy that forwards requests to model providers; use synthetic data only and review the current provider/privacy settings. This is not a recommendation to run a user-data beta on a free tier.

For local, private experimentation, Ollama makes no hosted API request and needs no API key. Small quantized models are more realistic on CPU-only or low-memory machines, but inference may be slow. Model weights are only part of memory use; runtime, context/KV cache, the operating system, and other processes also need RAM. A machine with about 10 GB of RAM has limited headroom for larger models or concurrent requests and should not be treated as a reliable multi-user beta server.

**Recommendation:** use OpenRouter's `openrouter/free` router with synthetic data for broad API/streaming development tests, or Ollama for private local experiments. Do not use a free hosted provider with real user, confidential, or sensitive workspace data. For an external beta with real data, select a provider and plan only after reviewing its data-processing terms, availability, limits, and cost.

## Configure safely

Set these variables in the backend environment or its `.env` file:

| Variable | Purpose | Default |
|---|---|---|
| `AI_PROVIDER` | `disabled`, `openai`, `openai_compatible`, `nvidia`, or `ollama` | `disabled` |
| `AI_BASE_URL` | OpenAI-compatible API base URL or Ollama server URL | Provider default |
| `AI_API_KEY` | Server-side API key for OpenAI-compatible services | Empty |
| `NVIDIA_API_KEY` | Server-side NVIDIA API key; used only when `AI_PROVIDER=nvidia` | Empty |
| `AI_MODEL` | Model identifier | `gpt-4o-mini` |
| `AI_TIMEOUT_SECONDS` | Provider request timeout, 0-300 seconds | `45` |
| `AI_MAX_RETRIES` | Retry count for transient connection and provider errors | `1` |
| `AI_MAX_OUTPUT_TOKENS` | Maximum provider output tokens | `4096` |
| `AI_TEMPERATURE` | NVIDIA sampling temperature | `0.7` |
| `AI_TOP_P` | NVIDIA nucleus-sampling value | `0.95` |
| `AI_ENABLE_THINKING` | Enables NVIDIA model thinking mode | `true` |
| `AI_REASONING_BUDGET` | NVIDIA reasoning-token budget when thinking is enabled | `2048` |
| `AI_MAX_CONTEXT_CHARS` | Upper bound for workspace metadata context | `12000` |
| `AI_MAX_INPUT_CHARS` | Upper bound for each provider input and its chat history | `30000` |
| `AI_MAX_HISTORY_MESSAGES` | Maximum prior messages considered for chat context | `12` |
| `AI_RATE_LIMIT_REQUESTS` | Per-user, per-workspace AI requests per window | `30` |
| `AI_RATE_LIMIT_WINDOW_SECONDS` | AI request rate-limit window | `3600` |
| `AI_DAILY_TOKEN_LIMIT` | Daily provider-reported token limit per user/workspace; `0` disables this check | `100000` |

For example, the non-secret OpenRouter settings are:

```dotenv
AI_PROVIDER=openai_compatible
AI_BASE_URL=https://openrouter.ai/api/v1
AI_MODEL=openrouter/free
```

Set `AI_API_KEY` separately in a local ignored `.env` file or a secret manager. The repository `.gitignore` ignores `.env`; do not force-add it. Never paste keys into chat, commit them, put them in `.env.example`, frontend variables, `NEXT_PUBLIC_*`, logs, screenshots, or browser storage. The frontend receives only non-secret provider availability status.

For local Ollama, install Ollama, pull and start a model that is compatible with your use and its license, then configure:

```dotenv
AI_PROVIDER=ollama
AI_BASE_URL=http://localhost:11434
AI_MODEL=<installed-model-name>
AI_API_KEY=
```

When the backend runs in Docker and Ollama runs on the host, use a host-reachable URL such as `http://host.docker.internal:11434`. Confirm Ollama is reachable from the backend container and restrict host firewall/network access; do not expose the Ollama port to the public internet. Running the backend on the host avoids this container-to-host networking setup.

For Docker Compose, place local settings in the repository-root `.env` file; for a directly run backend, set process environment variables or use an ignored `.env` in the backend working directory. Configuration changes require restarting the backend.

### Smoke test

1. Use only a synthetic prompt and synthetic workspace data.
2. Authenticate and call `GET /api/v1/workspaces/{workspace_id}/ai/status`. Confirm the expected provider and model are reported; this is a configuration check, not a connectivity check.
3. Send a short chat prompt and a follow-up, then verify the response streams in the UI.
4. Confirm a missing key or disabled provider returns the documented `503`; confirm an unreachable server, invalid model, or upstream failure is surfaced as a provider error without exposing credentials.
5. Test dataset analysis and draft generation with synthetic data only. AI-generated SQL and operations remain drafts and must pass existing validation and explicit user approval.

## Apply database migrations

The migration adds conversation, message, and usage tables. Set `DATABASE_URL` to the intended database, then from `backend` run:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
```

For local development, the project can use SQLite where configured. PostgreSQL is the recommended shared/deployment database. To reverse only the Copilot migration:

```powershell
.\.venv\Scripts\alembic.exe downgrade 20261125_0008
```

Back up persistent data before downgrading a database that contains conversations or usage history.

## Start locally

From the repository root, start the usual services:

```powershell
docker compose up --build
```

Or run the backend and frontend separately using the existing development instructions in the repository README. The local frontend is served at `http://localhost:3000`; the API is served at `http://localhost:8000`.

## Troubleshooting

- `GET /api/v1/workspaces/{workspace_id}/ai/status` reports whether a provider is configured, without returning secrets.
- A `503` from an AI generation endpoint means the provider is disabled, unsupported, missing required configuration, or has incompatible NVIDIA reasoning/output token budgets.
- A `502` means the provider request failed; provider response bodies and credentials are not returned to the client.
- Streaming provider errors after the SSE response begins are returned as a generic `error` event; incomplete assistant content is not persisted as a successful answer. Provider retries occur only before content starts.
- `429` indicates the configured request or token limit was reached.
- PyLake does not automatically switch providers after an NVIDIA failure.
- The feature requires normal authentication, workspace membership, and CSRF validation for state-changing requests.

## Provider references

- [OpenRouter free models](https://openrouter.ai/docs/guides/routing/model-variants/free), [FAQ and current limits/privacy details](https://openrouter.ai/docs/faq)
- [Gemini OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai), [Gemini API terms, including unpaid-service data use](https://ai.google.dev/gemini-api/terms)
- [Groq supported models](https://console.groq.com/docs/models)
- [NVIDIA Nemotron 3.5 Lightning API](https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b)
- [Ollama API](https://docs.ollama.com/api), [hardware support](https://docs.ollama.com/gpu)
