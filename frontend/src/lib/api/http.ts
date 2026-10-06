import { clearSession, getAccessToken } from "@/lib/auth-storage";

// Same-origin by default: Next rewrites /api/v1 → the API (see next.config.ts).
// Override only if the browser must call the API on a different host.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

export class ApiError extends Error {
  status: number;
  /** Machine-readable reason, when the endpoint sends `detail: {code, message}`. */
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function parseError(res: Response): Promise<ApiError> {
  try {
    const data = await res.json();
    const detail = data.detail;
    if (typeof detail === "string") return new ApiError(detail, res.status);
    if (typeof detail?.message === "string") {
      return new ApiError(detail.message, res.status, detail.code);
    }
    if (Array.isArray(detail)) {
      const message = detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join("; ");
      return new ApiError(message, res.status);
    }
    if (data.message) return new ApiError(data.message, res.status);
    if (data.error) return new ApiError(data.error, res.status);
  } catch {
    /* ignore */
  }
  return new ApiError(res.statusText || "Request failed", res.status);
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  auth = true,
): Promise<T> {
  const headers = new Headers(options.headers);
  // FormData needs the browser to set its own Content-Type (with the multipart
  // boundary) — forcing JSON here would break file uploads.
  if (!headers.has("Content-Type") && options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (auth) {
    const token = getAccessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }

  // no-store: API responses are per-request and shouldn't be served from the
  // browser's HTTP cache — and, concretely, this is what stops a stale cached
  // redirect (e.g. an old permanent redirect for a since-fixed route) from
  // being replayed silently instead of hitting the network.
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers, cache: "no-store" });

  if (res.status === 401 && auth) {
    clearSession();
    if (typeof window !== "undefined" && window.location.pathname !== "/") {
      // Hard redirect (not router.push): this runs outside React/Next.js routing context
      // and must force a full reset of all client state, not just navigate.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = "/";
    }
  }

  if (!res.ok) {
    throw await parseError(res);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/** Like apiFetch, but for binary/text responses (audio, transcript files) that
 * aren't JSON — same auth header + 401 handling, no res.json() parsing. */
export async function apiFetchBlob(path: string, options: RequestInit = {}): Promise<Blob> {
  const headers = new Headers(options.headers);
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers, cache: "no-store" });

  if (res.status === 401) {
    clearSession();
    if (typeof window !== "undefined" && window.location.pathname !== "/") {
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = "/";
    }
  }

  if (!res.ok) {
    throw await parseError(res);
  }

  return res.blob();
}

export function langQuery(langs: string[]): string {
  if (!langs.length) return "";
  return `?languages=${encodeURIComponent(langs.join(","))}`;
}
