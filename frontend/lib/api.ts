const DEFAULT_API_URL = process.env.NODE_ENV === "production" ? "" : "http://localhost:8000";
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_URL;

function csrfToken(): string | undefined {
  if (typeof document === "undefined") return undefined;
  const match = document.cookie
    .split("; ")
    .find((entry) => entry.startsWith("pylake_csrf="));
  return match?.slice("pylake_csrf=".length);
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<{ data?: T; error?: string }> {
  const method = options.method ?? "GET";
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const token = csrfToken();
    if (token) headers.set("X-CSRF-Token", token);
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
    credentials: "include",
  });

  if (response.status === 204) return {};
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    return { error: body?.detail ?? "The request could not be completed" };
  }
  return { data: body as T };
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
