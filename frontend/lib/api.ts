const DEFAULT_API_URL = process.env.NODE_ENV === "production" ? "" : "http://localhost:8000";
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_URL;

function csrfToken(): string | undefined {
  if (typeof document === "undefined") return undefined;
  const match = document.cookie
    .split("; ")
    .find((entry) => entry.startsWith("pylake_csrf="));
  return match?.slice("pylake_csrf=".length);
}

type ErrorBody = {
  detail?: unknown;
  request_id?: string;
  error?: { message?: string };
} | null;

/** Extract a safe, user-facing string from a FastAPI `detail` field. */
function detailMessage(detail: unknown): string | undefined {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) return "Request validation failed. Please check the highlighted fields.";
  return undefined;
}

/**
 * Map an HTTP failure to a safe message. Never surfaces stack traces,
 * database errors, or raw platform error pages.
 */
export function describeHttpError(status: number, body: ErrorBody, path = ""): string {
  const detail = detailMessage(body?.detail);
  const isLogin = path.endsWith("/auth/login");
  let message: string;
  if (status >= 500) {
    message = "The service is temporarily unavailable. Please try again in a moment.";
  } else if (status === 401) {
    message = isLogin ? "Invalid email or password." : "Your session has expired. Please sign in again.";
  } else if (status === 403) {
    message = detail === "CSRF validation failed"
      ? "Your session security token is missing or expired. Please refresh the page and sign in again."
      : detail ?? "You do not have permission to perform this action.";
  } else if (status === 422) {
    message = "Request validation failed. Please check your input.";
  } else if (status === 429) {
    message = detail ?? "Too many attempts. Please try again later.";
  } else {
    message = detail ?? "The request could not be completed.";
  }
  return body?.request_id ? `${message} (Reference: ${body.request_id})` : message;
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<{ data?: T; error?: string; status?: number }> {
  const method = options.method ?? "GET";
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const token = csrfToken();
    if (token) headers.set("X-CSRF-Token", token);
  }

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers,
      credentials: "include",
    });
  } catch {
    return { error: "Network connection failed. Check your internet connection and try again.", status: 0 };
  }

  if (response.status === 204) return { status: 204 };
  const body = (await response.json().catch(() => null)) as ErrorBody;
  if (!response.ok) {
    return { error: describeHttpError(response.status, body, path), status: response.status };
  }
  return { data: body as T, status: response.status };
}

export async function streamApi(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<Response> {
  const headers = new Headers({
    Accept: "text/event-stream",
    "Content-Type": "application/json",
  });
  const token = csrfToken();
  if (token) headers.set("X-CSRF-Token", token);
  return fetch(`${API_URL}${path}`, {
    method: "POST",
    headers,
    credentials: "include",
    body: JSON.stringify(body),
    signal,
  });
}
